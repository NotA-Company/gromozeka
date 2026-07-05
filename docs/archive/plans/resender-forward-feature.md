# Resender Forward Feature

Add native message forwarding to the Resender module — after a message is resent to
`targetChatId`, it can also be natively forwarded (copied) to one or more
additional chats.

**Status**: design proposal  
**Date**: 2026-07-03

## Motivation

The Resender currently reads messages from a source chat's database, reconstructs text
and media, and sends them as **new bot-authored messages** to a single `targetChatId`.
There is no way to also forward the resulting message to another chat or channel.

Adding a native forward (using Telegram's `copyMessage`/`copyMessages` API and Max's
`forwardFrom` mechanism) preserves platform-native attribution and creates the message
in the target chat without additional content reconstruction — the forwarded message
references the original on the platform.

## Current State

The Resender handler (`internal/bot/common/handlers/resender.py`, 456 lines) is a
cron-based service (fires every 60 seconds via `QueueService.CRON_JOB`). Each
`ResendJob` defines a one-to-one mapping:

| Field | Type | Purpose |
|---|---|---|
| `sourceChatId` | `int` | Source chat to read messages from (DB) |
| `targetChatId` | `int` | Single destination chat |
| `messageTypes` | `Sequence[MessageCategory]` | Filter by message category |
| `messagePrefix` / `messageSuffix` | `str` | Template strings with `{{var}}` substitution |
| `lastMessageDate` | `datetime` | Cursor for incremental reads |
| `mediaGroupDelaySecs` | `float` | Wait time for media group completion |

The per-message send flow:

```
For each message from DB:
  ├─ Reconstruct text with FormatEntity markup → platform-specific formatting
  ├─ Apply prefix/suffix template substitution
  ├─ Build attachmentList from StorageService (if media group)
  ├─ self.sendMessage(None, text=..., chatId=targetChatId, ...)  ← replyToMessage=None
  │    Returns: List[EnsuredMessage] (currently DISCARDED)
  └─ Update lastMessageDate in settings table
```

Key observations:
- `sendMessage` returns `List[EnsuredMessage]` with `messageId` — currently **discarded**
- No native forward API (`copyMessage`/`forwardMessage`/`copyMessages`) exists anywhere in the codebase
- Zero tests for the Resender module

## Proposed Design

### New Config Fields on `ResendJob`

One new `__slots__` field and a TypedDict for forward targets:

```python
class ForwardTarget(TypedDict, total=False):
    """Target chat for forwarding a resent message."""
    chatId: int
    threadId: Optional[int]
    notify: Optional[bool]
```

| Field | Type | Default | Purpose |
|---|---|---|---|
| `forwardTo` | `Optional[List[ForwardTarget]]` | `None` | List of target chats to natively forward the resent message to. `None` or `[]` = disabled. |

Example TOML with multiple forward targets:

```toml
[[resender.jobs]]
id = "resend-from-chat"
sourceChatId = -123
targetChatId = -321
messageTypes = ["user"]

[[resender.jobs.forwardTo]]
chatId = -456
threadId = 0
notify = true

[[resender.jobs.forwardTo]]
chatId = -789
# threadId and notify omitted — use platform defaults
```

### New Method on `TheBot`: `forwardMessages`

A single method handling both single messages and media groups, across both platforms:

```python
async def forwardMessages(
    self,
    fromChatId: int,
    messageIds: List[MessageId],
    toChatId: int,
    *,
    threadId: Optional[int] = None,
    notify: Optional[bool] = None,
) -> List[MessageId]:
```

Always accepts a list — for single messages it's `[messageId]`, for media groups it's
all message IDs. The method dispatches per platform:

| Platform | Implementation |
|---|---|
| **Telegram** | `self.tgBot.copy_messages(chat_id=toChatId, from_chat_id=fromChatId, message_ids=[m.asInt() for m in messageIds], message_thread_id=threadId, disable_notification=...notify)` — `copy_messages` works for both single messages and groups |
| **Max** | `self.maxBot.sendMessage(chatId=str(toChatId), forwardFrom=messageIds[0].asStr())` — Max media groups are always a single message, so only the first ID is used |

### ResenderHandler Wiring

After `sendMessage` returns, forward the resulting messages to every target in
`job.forwardTo`:

```python
sentMessages = await self.sendMessage(
    None,
    messageText=messagePrefix + messageText + messageSuffix,
    messageCategory=MessageCategory.BOT_RESENDED,
    chatId=job.targetChatId,
    notify=job.notification,
    attachmentList=attachmentList,
)

if job.forwardTo:
    messageIds = [m.messageId for m in sentMessages]
    for target in job.forwardTo:
        try:
            await self._bot.forwardMessages(
                fromChatId=job.targetChatId,
                messageIds=messageIds,
                toChatId=target["chatId"],
                threadId=target.get("threadId"),
                notify=target.get("notify"),
            )
        except Exception as e:
            logger.error(
                "Failed to forward message to chat %d: %s",
                target["chatId"],
                e,
            )
```

The method signature accepts `List[MessageId]` — single messages produce a
one-element list, media groups produce all message IDs. No `isinstance` or
`botProvider` branching needed at the call site.

### Error Handling

| Scenario | Behavior |
|---|---|
| Forward fails with any exception | `logger.error()`, `lastMessageDate` still advances — primary resend already succeeded |
| Resend itself fails (existing behavior) | Error notice sent to target chat, `lastMessageDate` NOT advanced → retry next tick |

No error notification is sent to any chat for forward failures — the forward is
best-effort. If the resend itself succeeds, the cursor advances regardless of forward
outcome.

## Platform Behavior Summary

| | Any message |
|---|---|
| **Telegram** | `copy_messages` — works for single messages and albums alike |
| **Max** | `sendMessage(forwardFrom=messageIds[0])` — Max media groups are single messages |

## Files Changed

| File | Change |
|---|---|
| `internal/bot/common/bot.py` | New `forwardMessages` method on `TheBot` |
| `internal/bot/common/handlers/resender.py` | New `ForwardTarget` TypedDict + `forwardTo` field in `ResendJob.__slots__` + `__init__`; capture `sendMessage` return; per-target forward loop in `resendCronJob` |
| `configs/00-defaults/resender.toml` | Commented example `forwardTo` array (`[[resender.jobs.forwardTo]]`) |
| `docs/llm/configuration.md` | New `[resender.jobs]` config keys documented |

## Tests

New test file: `tests/bot/common/handlers/test_resender.py` (zero tests exist today).

| Test | What it verifies |
|---|---|
| `test_resend_without_forward` | `forwardTo=None` → no `forwardMessages` called |
| `test_resend_forward_single_text` | Single text message → `forwardMessages` called with `[messageId]` |
| `test_resend_forward_single_photo` | Single photo → `forwardMessages` called, `lastMessageDate` advances |
| `test_resend_forward_media_group_telegram` | 3-photo album → `forwardMessages` called with all 3 IDs |
| `test_resend_forward_max` | Max platform → `forwardMessages` via `sendMessage(forwardFrom=messageIds[0])` |
| `test_resend_forward_multiple_targets` | `forwardTo` has 2 entries → `forwardMessages` called twice with same messageIds |
| `test_resend_forward_failure_no_block` | `forwardMessages` raises → error logged, `lastMessageDate` still saved, next target still tried |
| `test_forward_job_config_parsing` | `forwardTo` list parsed from job dict, each entry as `ForwardTarget` |
| `test_forward_job_config_defaults` | Missing `forwardTo` → `None` (backward-compatible) |

## Implementation Phases

1. **Add `forwardMessages` to `TheBot`** — single method, both platforms, with tests
2. **Extend `ResendJob`** — new `ForwardTarget` TypedDict, `forwardTo` field in `__slots__` + `__init__`, config parsing
3. **Wire into `ResenderHandler`** — capture `sendMessage` return, per-target forward loop
4. **Update default config** — commented example keys in `resender.toml`
5. **Write resender tests** — new test file covering all scenarios
6. **Update documentation** — `docs/llm/configuration.md`
