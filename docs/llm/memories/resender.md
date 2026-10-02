---
category: reference
---

# Resender Module

Durable notes from the Resender module implementation (2026-07-03). Read this when working on `internal/bot/common/handlers/resender.py` or message forwarding features.

- **Core file**: `internal/bot/common/handlers/resender.py` (508 lines). Cron-based handler (fires every 60s via `QueueService.CRON_JOB`). Reads messages from source chat's DB, reconstructs text/media, sends as new bot-authored messages to `targetChatId`. 13 tests in `tests/bot/common/handlers/test_resender.py` (covers `ForwardTarget`/`ResendJob.forwardTo` data model + the forward loop in `resendCronJob`).
- **Config**: `configs/00-defaults/resender.toml` — `enabled = false` by default, one example job. No override in `configs/common/` or `configs/local/` — disabled everywhere.
- **Registration**: `manager.py:565-571`, gated on `resender.enabled`. `HandlerParallelism.PARALLEL`. 3rd of 6 config-gated handlers (after Weather, YandexSearch; before Divination, Sandbox, ChatSearch).
- **Flow**: `_dtCronJob` → `resendCronJob` → for each job: `getChatMessagesSince(sourceChatId, since=lastMessageDate)` → reconstruct text via `FormatEntity.parseText` → prefix/suffix template substitution → `self.sendMessage(None, text=..., chatId=targetChatId)` with `replyToMessage=None` → update `lastMessageDate` in settings table (key: `resender:{job.id}:lastMessageDate`).
- **`sendMessage` returns `List[EnsuredMessage]`** with `messageId` — consumed only when `job.forwardTo` is configured (`messageIds = [m.messageId for m in sentMessages]` then passed to `TheBot.forwardMessages`). No persistence of the resent messages' IDs otherwise.
- **Media groups**: waits for completion via `mediaGroupDelaySecs` (default 10s), retrieves binary data from `StorageService` via `local_url` key (not re-downloaded from platform), sends via `send_media_group`.
- **Error handling**: resend failure → error notification sent to target chat, `lastMessageDate` NOT advanced (retry next tick). Backoff: `messageSendDelay` doubles from 0.25s to max 10s between successful sends.
- **`ResendJob.__slots__`**: `id`, `dataSource`, `sourceChatId`, `sourceTheadId` (typo — should be `sourceThreadId`), `targetChatId`, `forwardTo`, `messageTypes`, `messagePrefix`, `messageSuffix`, `lastMessageDate`, `notification`, `mediaGroupDelaySecs`, `_lock`.
- **No native forward API** (`copyMessage`/`forwardMessage`/`copyMessages`) exists anywhere in the codebase. Max's `MaxBotClient.sendMessage()` accepts `forwardFrom: Optional[str]` but no call site passes it.
- **Forward feature** (implemented 2026-07-03, plan: `docs/archive/plans/resender-forward-feature.md`): `ForwardTarget` TypedDict with `chatId: int`, `threadId: NotRequired[int]`, `notify: NotRequired[bool]`. `ResendJob.forwardTo: Optional[List[ForwardTarget]]` (defaults to `[]`). Forward loop in `resendCronJob` (`resender.py:455-474`) iterates targets with `await asyncio.sleep(0.1)` between them, calls `TheBot.forwardMessages(fromChatId, messageIds, toChatId, *, threadId, notify)`. Skipped entirely when `sentMessages` is empty or `self._bot` is None. Telegram: `tgBot.copy_messages()`. Max: loops over all `messageIds`, calls `sendMessage(forwardFrom=)` per message. Failures swallowed per-target (`TheBot.forwardMessages` logs traceback via `logger.exception` before re-raising), don't block `lastMessageDate` advancement. Config: `docs/llm/configuration.md` `[resender]` section (`configuration.md:340`), `configs/00-defaults/resender.toml` commented example.
