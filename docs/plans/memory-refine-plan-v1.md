# User Memory Refinement — Plan v1

**Status:** IMPLEMENTED (2026-07-04) — see [`docs/llm/memories/user-memory-refinement.md`](../llm/memories/user-memory-refinement.md) for the durable implementation summary. Production files: `internal/bot/common/handlers/user_data.py`, `internal/bot/common/handlers/base.py`, `internal/bot/common/handlers/manager.py`, `internal/bot/models/{user_metadata,chat_settings,ensured_message}.py`, `internal/bot/constants.py`, `internal/database/repositories/chat_messages.py`, `configs/00-defaults/{bot-defaults,user-memory}.toml`.

> **Historical note (read before relying on §3 / §17):** This plan captures the v1 design as originally written and is kept for provenance. A subsequent refactor + Gate-1 fixes changed several aspects, so §3 and §17 below are **stale** relative to the shipped code:
> - `lastRefinedTS` moved from `chat_users.metadata` (persisted) to **in-memory only** on `UserDataHandler._lastRefinedTS`. The persisted `UserMemoryThreadDict` now carries only `summary`, `lastProcessedMessageId`, `lastProcessedMessageDate`. §3 line 45 / §17 item 1 still show the old shape.
> - Refinement prompts moved from the `[user-memory.prompts]` TOML section to **per-chat settings** (`MEMORY_REFINE_SYSTEM_PROMPT` / `MEMORY_REFINE_USER_PROMPT_TEMPLATE`, defaults under `[bot.defaults]`). §17 item 10 still describes splitting `[user-memory.prompts]`.
> - The due-list sort `(-elapsed, -count)` and the bail-path `_lastRefinedTS` reset were added after this plan and are not reflected in §6 / §8.
> - Subsequent refactor: the `(-elapsed, -count)` collect-all-then-sort was itself replaced by an **online top-K by smallest `lastRefinedTS`** (bounded `due` list maintained during the scan — the 3rd tuple element is `lastRefinedTS` int, not `elapsed` float), and the `isNeverRefined` new-message-count pre-filter that sat between the two was removed (refinement of never-refined users pulls lifetime messages via `getChatMessagesSince(None)`, so gating the skip on the new-message counter was over-conservative). Neither the top-K scan nor the skip removal is reflected in §6 / §8; see [`docs/llm/architecture.md`](../llm/architecture.md) ADR-014 and [`docs/llm/memories/user-memory-refinement.md`](../llm/memories/user-memory-refinement.md) for the current shape.
> - `DEFAULT_THREAD_ID_STR` (§13 line 267) was dead code and removed; use `DEFAULT_THREAD_ID` from `internal.database.utils`.
> - **Simplification (2026-07-05):** the `BaseBotHandler.getUserMemorySummary` reader introduced in §10 (and the `MEMORY_REFINEMENT_ENABLED` gate that wrapped it at the two call sites) was removed entirely. The per-thread summary extraction now lives on `EnsuredMessage.applyUserMetadata(metadata)`, invoked from `BaseBotHandler._updateEMessageUserData` and `HandlersManager._processMessageRec` after they fetch the full `UserMetadataDict` via `cache.getUserMetadata`. Injection is intentionally no longer gated on the chat setting — the write side (`_persistMemoryEntry`) still gates, so absence-of-summary is the gate; a stale summary for a since-disabled chat still injects (accepted). The four extraction tests moved to `tests/bot/models/test_ensured_message.py` (`TestApplyUserMetadata`). §10 below still shows the old `getUserMemorySummary` helper.
>
> For the current state, always defer to [`docs/llm/memories/user-memory-refinement.md`](../llm/memories/user-memory-refinement.md), [`docs/llm/architecture.md`](../llm/architecture.md) ADR-014, and [`docs/llm/configuration.md`](../llm/configuration.md) §`[user-memory]`. Do not treat this plan as authoritative for the final shape.

**Supersedes:** `docs/plans/memory-refine-plan-v0.md`.
**Owner handler:** `internal/bot/common/handlers/user_data.py` (`UserDataHandler`).

## 1. Goal

Give the bot a rolling, per-(chat, user, thread) memory refined in the background by an LLM, so future replies carry short-term context about each user without re-reading their whole history. Two deliverables:

1. Tighten the existing `add_user_data` LLM-tool description so the model persists only durable facts.
2. Add a background refinement loop: when a user has accumulated enough new messages (or enough time has passed), run an LLM call over the recent messages plus the user's existing summary to (a) extract durable facts into `user_data` via tools and (b) produce a new short summary that replaces the old one.

## 2. Decisions (from discussion)

| Decision | Choice |
|---|---|
| Summary storage | `chat_users.metadata` column (already exists), keyed per-thread |
| Counters | `newMessagesCount` per (chatId, userId, threadId), in-memory only (lost on restart; refinement re-fires after threshold). A single GLOBAL `asyncio.Lock` on `UserDataHandler` serializes all refinement — prevents flooding the LLM provider when a run takes >60s. |
| New LLM tools | Add `delete_user_data` only (no `get` — userData is already injected into context) |
| Cron home | Extend `UserDataHandler` (cron + increment + refinement all in `user_data.py`). |
| Counter increment | Top of `UserDataHandler.newMessageHandler`, before any gates |
| Model config | Dedicated `MEMORY_REFINE_MODEL` + `MEMORY_REFINE_FALLBACK_MODEL` keys |
| Per-chat enable | New `ChatSettingsKey.MEMORY_REFINEMENT_ENABLED` (default False, True for friend tier via `[bot.tier-defaults.friend]`). Guards both counting and refinement. Separate from the global `[user-memory].enabled` kill switch. |
| Thresholds | `countThreshold = 5`, `timeThreshold = 6h`, `messageCap = 128` (all config-overridable) |
| Refine prompt | Split into system prompt (how to work) + user-prompt template (what to do, with data interpolated). |

## 3. Storage design

No new migration. The `chat_users.metadata TEXT DEFAULT '' NOT NULL` column already exists (`migration_003_add_metadata_to_chat_users.py`, re-asserted in `migration_013_remove_timestamp_defaults.py`). Read/write helpers exist on `BaseBotHandler`:

- `parseUserMetadata(userInfo: Optional[ChatUserDict]) -> UserMetadataDict` (`internal/bot/common/handlers/base.py`, ~line 1055)
- `setUserMetadata(chatId, userId, metadata, isUpdate=False)` (`internal/bot/common/handlers/base.py`, ~line 1073) — `isUpdate=True` does read-then-merge.

Repository: `ChatUsersRepository.updateUserMetadata(chatId, userId, metadata: str)` (`internal/database/repositories/chat_users.py`, ~line 126) — partial-column UPDATE touching only `metadata` + `updated_at`.

Extend `UserMetadataDict` (`internal/bot/models/user_metadata.py`) with a per-thread memory sub-dict:

```python
class UserMemoryThreadDict(TypedDict, total=False):
    summary: str
    """Rolling short summary/bio of the user in this thread."""
    lastProcessedMessageId: str   # MessageId.asStr() — logging/debug only
    lastProcessedMessageDate: str # ISO datetime — the MESSAGE cursor for getChatMessagesSince (not the refinement-run time)
    lastRefinedTS: int           # unix timestamp of the last refinement RUN (drives the time threshold)

class UserMetadataDict(TypedDict, total=False):
    isSpammer: bool
    notSpammer: bool
    dropMessages: bool
    leftChat: bool
    memoryRefinement: Dict[str, UserMemoryThreadDict]  # keyed by str(threadId); "0" for main
```

Note: `lastProcessedMessageDate` (cursor for `getChatMessagesSince`) and `lastRefinedTS` (drives the 6h time threshold) are distinct — they diverge when there is lag between the newest ingested message and the refinement run.

Thread key is `str(threadId)` (DEFAULT_THREAD_ID = 0 → "0") — JSON object keys are strings, so this is the natural shape.

Write path (read-modify-write of the NESTED dict — do NOT rely on `setUserMetadata(isUpdate=True)` alone):

`setUserMetadata(..., isUpdate=True)` does a one-level shallow merge (`{**oldMetadata, **newMetadata}`, `base.py:1085-1090`). Passing `{"memoryRefinement": {<threadId>: {...}}}` would REPLACE the entire `memoryRefinement` sub-dict, wiping every other thread's summary. The refinement code must therefore:

1. `userInfo = await self.db.chatUsers.getChatUser(chatId, userId)`
2. `metadata = self.parseUserMetadata(userInfo)`
3. `memoryRefinement = metadata.get("memoryRefinement", {})`
4. `memoryRefinement[str(threadId)] = {summary, lastProcessedMessageId, lastProcessedMessageDate, lastRefinedTS}` (mutate only this thread's entry)
5. `metadata["memoryRefinement"] = memoryRefinement`
6. `await self.setUserMetadata(chatId, userId, metadata, isUpdate=True)` — now the shallow top-level merge is safe because we re-passed the full `memoryRefinement` dict.

## 4. In-memory accounting

Handler-instance counter dict on `UserDataHandler`, plus a single global lock:

```python
_accounting: Dict[Tuple[int, int, int], int]  # key = (chatId, userId, threadId) -> newMessagesCount
_refineLock: asyncio.Lock  # single global lock; serializes ALL refinement runs
```

`_accounting` holds only the in-memory `newMessagesCount` per key (lost on restart; refinement re-fires after the next threshold crossing). `_refineLock` is a single `asyncio.Lock` created in `__init__`; the cron checks `if self._refineLock.locked(): return` at the top and otherwise runs the entire due batch under `async with self._refineLock:`. This serializes all refinement across the whole bot, so a slow LLM call (>60s) blocks the next tick's refinement rather than spawning a concurrent one — preventing provider flooding.

Increment site: `UserDataHandler.newMessageHandler`, at the very top, BEFORE the `chatType != PRIVATE` early-return and BEFORE the wizard-state check, so every user message in every chat type counts. The increment is guarded by the per-chat `ChatSettingsKey.MEMORY_REFINEMENT_ENABLED` setting (no counting when disabled). Because the handler now does work (counting) for every message, it returns `HandlerResultStatus.NEXT` (project philosophy: NEXT = did work, SKIPPED = did nothing) instead of `SKIPPED` for non-wizard messages. The wizard path still returns `FINAL`.

## 5. Cron job

Register in `UserDataHandler.__init__`, mirroring `ChatSearchHandler` (`chat_search.py:201`):

```python
self.queueService.registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB, self._dtCronJob)
```

`_dtCronJob` runs every tick (the `CRON_JOB` delayed task self-reschedules every 60s in `QueueService`). The handler signature MUST match the `DelayedTaskHandler = Callable[[DelayedTask], Awaitable[None]]` alias (`internal/services/queue_service/types.py:71`) — i.e. accept the `task` argument:

```python
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction

async def _dtCronJob(self, task: DelayedTask) -> None:
    ...
```

(See `chat_search.py:284` for the canonical shape.) Flow:

1. Early-return if the global `[user-memory].enabled` flag is off.
2. `if self._refineLock.locked(): return` — another refinement batch is still running (a single LLM call can exceed the 60s tick); bail this tick.
3. `async with self._refineLock:` — acquire the single global lock for the whole batch.
4. Inside the lock, build the due list by scanning `_accounting`:
   - skip entries whose per-chat `ChatSettingsKey.MEMORY_REFINEMENT_ENABLED` is off (runtime-disable safe);
   - `elapsed = now - lastRefinedTS` (from `memoryRefinement[threadId].lastRefinedTS`); absence means 'never refined' → due;
   - due if `newMessagesCount >= MEMORY_COUNT_THRESHOLD` OR `elapsed >= MEMORY_TIME_THRESHOLD_SECONDS`.
5. Process due entries SEQUENTIALLY (await each, do not `createTask` — the global lock already serializes everything), bounded by `MEMORY_MAX_REFINES_PER_TICK` (pick oldest-due / highest-count first). For each: `await self._runRefinement(chatId, userId, threadId)`; on success or failure (try/except + `logger.exception` per entry) reset that entry's `newMessagesCount = 0`.

Because the whole batch holds the global lock, subsequent ticks that arrive while a batch is running simply early-return at step 2.

## 6. Refinement call (`_runRefinement`)

1. `chatSettings = await self.cache.getChatSettings(chatId)`.
2. Load user metadata; `entry = memoryRefinement.get(str(threadId))` → existing summary + `lastProcessedMessageDate`.
3. `sinceDateTime = parse(entry.lastProcessedMessageDate)` or `None` (first run).
4. `messages = await self.db.chatMessages.getChatMessagesSince(chatId, sinceDateTime, threadId=threadId, limit=MEMORY_MAX_MESSAGES_PER_RUN, userId=userId)` — requires the new `userId` param (section 7). Pass `userId` as a keyword argument (it sits after `messageCategory` in the positional list, before the `*, dataSource` keyword-only marker).
5. If `len(messages) < MEMORY_MIN_MESSAGES_TO_REFINE`, bail.
6. Render messages for the LLM using the same pattern as `SummarizationHandler._doSummarization` (`internal/bot/common/handlers/summarization.py`): for each `ChatMessageDict`, `eMsg = await EnsuredMessage.fromDBChatMessage(msg, self.db)` then `await eMsg.formatForLLM(self.db, LLMMessageFormat.JSON, stripAtsign=True)`. Concatenate the rendered JSON strings (the `username`/`full_name` JOIN columns are already present on the row, so sender identity is included). Do NOT hand-roll a text renderer — reuse the existing one so prompt shape stays consistent with chat context.
7. Synthesize a minimal `EnsuredMessage` for `extraData` so the `add_user_data`/`delete_user_data` tools can resolve chatId/userId (they read `extraData["ensuredMessage"].recipient.id` and `.sender.id` — `user_data.py:127-128`). `EnsuredMessage.__init__` (`ensured_message.py:413-425`) is keyword-only and requires four fields. Helper:

   ```python
   def _makeSyntheticEnsuredMessage(self, chatId: int, userId: int) -> EnsuredMessage:
       return EnsuredMessage(
           sender=MessageSender(id=userId, name="", username=""),
           recipient=MessageRecipient(
               id=chatId,
               chatType=ChatType.PRIVATE if chatId > 0 else ChatType.GROUP,
           ),
           messageId=0,
           date=datetime.datetime.now(datetime.timezone.utc),
       )
   ```

   Only `.recipient.id` and `.sender.id` are read by the two tool handlers; all other fields are dummies. `threadId` is not needed on the synthetic message (the tools don't read it).
8. Build two prompts from config: `[user-memory].system-prompt` (how to do the work — biases toward durable facts, instructs to call `add_user_data`/`delete_user_data` and to return a new short summary as plain text) and `[user-memory].user-prompt-template` (what to do — interpolates the existing summary and the rendered messages, e.g. `Existing summary: {existingSummary}` / `Recent messages: {messages}`). Both have sensible defaults in config.
9. Call:
   ```python
   result = await self.llmService.generateTextViaLLM(
       messages=[...],
       chatId=None,  # skips rate-limiting for background call (see generateText docstring, service.py:862-863)
       chatSettings=chatSettings,
       modelKey=ChatSettingsKey.MEMORY_REFINE_MODEL,
       fallbackModelKey=ChatSettingsKey.MEMORY_REFINE_FALLBACK_MODEL,
       useTools={
           ToolName.ADD_USER_DATA: True,
           ToolName.DELETE_USER_DATA: True,
           ToolName.SEARCH_MESSAGES: True,
           ToolName.GET_CURRENT_DATETIME: True,
       },
       extraData={"ensuredMessage": synthEnsuredMessage},
   )
   ```

   (`keepLastN` defaults to 1 already — `service.py:426` — so it is omitted.) Tools are registered globally on `LLMService.toolsHandlers` (`service.py:110, 187`) and resolved by name via `_resolveTools` regardless of which handler registered them, so requesting `SEARCH_MESSAGES` (registered by `ChatSearchHandler`) and `GET_CURRENT_DATETIME` (registered by `CommonHandler`) from `UserDataHandler`'s refinement call works.
10. `newSummary = result.resultText` (the model's final text answer).
11. Persist via the read-modify-write described in §3: fetch `userInfo`, parse metadata, mutate only `memoryRefinement[str(threadId)]` (set `summary`, `lastProcessedMessageId`, `lastProcessedMessageDate`, `lastRefinedTS: int(now)`), then `setUserMetadata(..., isUpdate=True)`. Do NOT pass a partial `{"memoryRefinement": {<threadId>: ...}}` — that would wipe other threads (shallow merge, `base.py:1085-1090`). The newest processed message is the FIRST entry in the DESC-ordered list returned by `getChatMessagesSince`.
12. Reset accounting: `self._accounting[(chatId, userId, threadId)] = 0`. The global `_refineLock` is held by the cron caller (`_dtCronJob`), not acquired here — it releases when the cron's `async with` block exits.

Wrap `_runRefinement` in try/except + `logger.exception`; never raise out of it (the cron caller resets the counter and continues to the next entry regardless).

## 7. `getChatMessagesSince` — add `userId` filter

`internal/database/repositories/chat_messages.py`, `getChatMessagesSince` (~line 208). Add optional `userId: Optional[int] = None` param AFTER `messageCategory` and BEFORE the `*, dataSource` keyword-only marker, and add `AND (:userId IS NULL OR c.user_id = :userId)` to the WHERE clause; add `{"userId": userId}` to the params dict. Purely additive; all 8 existing call sites (`llm_messages.py:745`, `summarization.py:167`, `spam.py:759`, `resender.py:356`, `scripts/reproduce_llm_dialog.py:365`, and tests) pass every argument by keyword or are mocked, so none break.

## 8. `delete_user_data` LLM tool

Register in `UserDataHandler.__init__` alongside `ADD_USER_DATA`. Mirror `_llmToolSetUserData`; call `self.cache.unsetChatUserData(chatId=ensuredMessage.recipient.id, userId=ensuredMessage.sender.id, key=key)`. Parameters: `key: str` (required). Description: remove a stale/incorrect persistent fact by key.

## 9. `add_user_data` tool description rewrite

Bias toward durable facts; explicitly discourage transient/contextual notes. Suggested text:

> Remember **durable, long-lived** facts about the user who sent the last message — things that will still be true weeks from now. Use it for: real name, birthday, profession, stable preferences (language, formatting, communication style), long-term goals, important relationships.
> Do NOT use it for: transient states (current mood, what they're doing today), one-off requests, conversation-specific context, things likely to change soon. When in doubt, skip.

## 10. Summary injection into LLM context

Today `userData` is attached per-message and serialized as a `userData` JSON field in `EnsuredMessage.formatForLLM` (`internal/bot/models/ensured_message.py`, ~line 1131), described in `chat-prompt-suffix`. Add a sibling field:

1. `internal/bot/models/ensured_message.py` — `EnsuredMessage` uses `__slots__` (lines 386-411), so adding a `userSummary` attribute requires TWO changes: (a) add `"userSummary"` to the `__slots__` tuple, and (b) initialize `self.userSummary: Optional[str] = None` in `__init__`. Then include `"userSummary": self.userSummary` in the JSON branch of `formatForLLM` next to `userData` (line 1131), gated by the same `if v` truthiness filter (line 1133). Also add a `setUserSummary(self, summary: Optional[str]) -> None` helper mirroring `setUserData` for symmetry.
2. Populate `userSummary` at the two existing `getChatUserData` attachment points:
   - `internal/bot/common/handlers/manager.py` `_processMessageRec` (~line 1015, the `ensuredMessage.setUserData(...)` call)
   - `internal/bot/common/handlers/base.py` `_updateEMessageUserData` (~line 372)

   The summary lives in `chat_users.metadata` (NOT in the `user_data` table that `cache.getChatUserData` reads), so add a `BaseBotHandler` helper:

   ```python
   async def getUserMemorySummary(self, chatId: int, userId: int, threadId: int) -> Optional[str]:
       userInfo = await self.db.chatUsers.getChatUser(chatId=chatId, userId=userId)
       if userInfo is None:
           return None
       memoryRefinement = self.parseUserMetadata(userInfo).get("memoryRefinement", {})
       return memoryRefinement.get(str(threadId), {}).get("summary")
   ```

   Call it at both attachment points using `ensuredMessage.threadId` (default to `DEFAULT_THREAD_ID = 0` if `None`), then `ensuredMessage.setUserSummary(summary)`.
3. `configs/00-defaults/bot-defaults.toml` `chat-prompt-suffix` — add a line:
   > `userSummary` - Краткое резюме/био о пользователе (при наличии).

## 11. Config

New file `configs/00-defaults/user-memory.toml`:

```toml
[user-memory]
enabled = false  # feature-flagged off by default

[user-memory.thresholds]
message-count = 5
time-seconds = 21600        # 6 hours
min-messages-to-refine = 5
max-messages-per-run = 128
max-refines-per-tick = 3

[user-memory.prompts]
system-prompt = """..."""          # how to do the work (default provided)
user-prompt-template = """..."""   # what to do; interpolates {existingSummary}, {messages}
```

(Prompts live in a distinct `[user-memory.prompts]` sub-table — re-declaring `[user-memory]` twice is a TOML parse error.)

New model keys under `[bot.defaults]` in `configs/00-defaults/bot-defaults.toml`:

```toml
memory-refine-model          = "openrouter/free"
memory-refine-fallback-model = "aliceai-llm-flash"
```

New `ChatSettingsKey` members (`internal/bot/models/chat_settings.py`):

```python
MEMORY_REFINE_MODEL = "memory-refine-model"
MEMORY_REFINE_FALLBACK_MODEL = "memory-refine-fallback-model"
```

### Per-chat enable setting

Add a per-chat boolean chat setting (follows the `add-chat-setting` four-site convention):

```python
MEMORY_REFINEMENT_ENABLED = "memory-refinement-enabled"
```

- `_chatSettingsInfo` entry (model on other boolean settings like `ALLOW_SANDBOX`).
- Default `false` under `[bot.defaults]` in `configs/00-defaults/bot-defaults.toml`:
  ```toml
  memory-refinement-enabled = false
  ```
- Enabled for the friend tier in `configs/common/01-bot-defaults.toml` under `[bot.tier-defaults.friend]`:
  ```toml
  memory-refinement-enabled = true
  ```
- Read at runtime via `chatSettings[ChatSettingsKey.MEMORY_REFINEMENT_ENABLED].toBool()`. Guards both the increment in `newMessageHandler` and the refinement in `_runRefinement` (runtime-disable safe).

Follow the `add-chat-setting` skill convention — all four sites must change together: `ChatSettingsKey` enum value, `_chatSettingsInfo` TypedDict entry (model the entries on the existing `SUMMARY_MODEL` / `SUMMARY_FALLBACK_MODEL` entries at `internal/bot/models/chat_settings.py:617-628`), the TOML default under `[bot.defaults]`, and the consumer code in `UserDataHandler._runRefinement`. The boolean `MEMORY_REFINEMENT_ENABLED` key follows the same convention.

## 12. Constants (module-level in `user_data.py`)

```python
MEMORY_COUNT_THRESHOLD = 5                       # newMessagesCount to trigger refinement
MEMORY_TIME_THRESHOLD_SECONDS = 6 * 60 * 60      # 6 hours
MEMORY_MIN_MESSAGES_TO_REFINE = 5                # don't refine on fewer messages
MEMORY_MAX_MESSAGES_PER_RUN = 128                # cap on messages fed to the LLM
MEMORY_MAX_REFINES_PER_TICK = 3                  # bound LLM calls per 60s cron tick
DEFAULT_THREAD_ID_STR = "0"                      # str(DEFAULT_THREAD_ID) — JSON object key
```

## 13. File-by-file change list

| File | Change |
|---|---|
| `internal/bot/models/user_metadata.py` | Add `UserMemoryThreadDict` + `memoryRefinement` field to `UserMetadataDict`. |
| `internal/bot/models/ensured_message.py` | Add `"userSummary"` to `__slots__`; initialize `self.userSummary` in `__init__`; add `setUserSummary` helper; include `userSummary` in `formatForLLM` JSON branch. |
| `internal/bot/models/chat_settings.py` | Add `MEMORY_REFINE_MODEL`, `MEMORY_REFINE_FALLBACK_MODEL` to `ChatSettingsKey` AND matching entries to `_chatSettingsInfo` (model on `SUMMARY_MODEL`/`SUMMARY_FALLBACK_MODEL` at ~lines 617-628) AND add `MEMORY_REFINEMENT_ENABLED` (boolean) with its `_chatSettingsInfo` entry (model on `ALLOW_SANDBOX` at ~lines 854-864). |
| `internal/bot/constants.py` | Add `DELETE_USER_DATA` to `ToolName`. |
| `internal/database/repositories/chat_messages.py` | Add `userId` param to `getChatMessagesSince`. |
| `internal/bot/common/handlers/user_data.py` | Rewrite `ADD_USER_DATA` description; register `DELETE_USER_DATA` tool; add `_accounting`; increment in `newMessageHandler`; register `_dtCronJob(self, task: DelayedTask)`; add `_runRefinement`; add `_makeSyntheticEnsuredMessage` helper. |
| `internal/bot/common/handlers/manager.py` | Attach `userSummary` (via new `getUserMemorySummary` helper) alongside `userData` in `_processMessageRec`. |
| `internal/bot/common/handlers/base.py` | Add `getUserMemorySummary` helper; attach `userSummary` in `_updateEMessageUserData`. |
| `configs/00-defaults/user-memory.toml` | New file: `[user-memory]` + `[user-memory.thresholds]` + `[user-memory.prompts]` sections. |
| `configs/00-defaults/bot-defaults.toml` | Add `memory-refine-model`/`memory-refine-fallback-model` to `[bot.defaults]`; add `memory-refinement-enabled = false` default; add `userSummary` line to `chat-prompt-suffix`. |
| `configs/common/01-bot-defaults.toml` | Add `memory-refinement-enabled = true` under `[bot.tier-defaults.friend]` (alongside `allow-sandbox = true` at line 116). |

## 14. Testing plan

- `tests/database/...`: extend `getChatMessagesSince` tests with the `userId` filter (other users' records excluded).
- `tests/bot/handlers/test_user_data.py`:
  - `delete_user_data` tool removes a key.
  - `newMessageHandler` increments accounting for every message (private + group, wizard-active or not).
  - `_dtCronJob` fires refinement when count threshold met; does not fire below threshold; early-returns when the global `_refineLock` is already held; respects `enabled = false`.
  - `_runRefinement` writes summary + cursor to `chat_users.metadata.memoryRefinement[threadId]`.
  - `_runRefinement` bails when `len(messages) < MEMORY_MIN_MESSAGES_TO_REFINE`.
- `tests/bot/models/test_ensured_message.py`: `formatForLLM` includes `userSummary` when set, omits when falsy.
- Golden test for the refine LLM call under `tests/lib/.../golden/` (do not hit real APIs).

## 15. Sequencing / phases

Each phase = one `software-developer` brief + Gate 1 review:

1. **Storage + types + config defaults**: extend `UserMetadataDict`; add all three `ChatSettingsKey`s + their `_chatSettingsInfo` entries; add `DELETE_USER_DATA` to `ToolName`; write the TOML defaults (`memory-refinement-enabled = false`, `memory-refine-model`, `memory-refine-fallback-model` in `configs/00-defaults/bot-defaults.toml`; `memory-refinement-enabled = true` under `[bot.tier-defaults.friend]` in `configs/common/01-bot-defaults.toml`; new `configs/00-defaults/user-memory.toml`). The four-site convention requires enum + `_chatSettingsInfo` + TOML default to land together — without the TOML default, any `chatSettings[MEMORY_REFINEMENT_ENABLED]` access would `KeyError`.
2. **Repo**: add `userId` to `getChatMessagesSince` + tests.
3. **Handler core**: rewrite `ADD_USER_DATA` description; register `DELETE_USER_DATA` tool + handler; add `_accounting` + increment in `newMessageHandler`; module constants.
4. **Cron + refinement**: register `_dtCronJob(self, task: DelayedTask)`; implement `_runRefinement` (incl. the read-modify-write persistence from §3 and the `_makeSyntheticEnsuredMessage` helper from §6 step 7).
5. **Context injection**: `userSummary` attr + `__slots__` extension + `setUserSummary` + `formatForLLM` + `getUserMemorySummary` helper on `BaseBotHandler` + the two attachment points + `chat-prompt-suffix` line.
6. **Prompt tuning**: finalize `[user-memory.prompts]` system/user-prompt-template copy (no structural changes — phase 1 already created the file with sensible defaults).
7. **Tests** for all of the above.
8. **Docs**: `update-project-docs` skill pass.
9. **Whole-work review** (Gate 2).

## 16. Risks / open items

- **EnsuredMessage synthesis (RESOLVED)**: the constructor (`ensured_message.py:413-425`) is keyword-only with four required fields (`sender`, `recipient`, `messageId`, `date`). The `_makeSyntheticEnsuredMessage(chatId, userId)` helper in §6 step 7 builds exactly those four; the two tool handlers only read `.recipient.id` and `.sender.id` (`user_data.py:127-128`), so dummy values for everything else are safe. No remaining unknowns.
- **Cost**: refinement fires per active (chat,user,thread). With `MEMORY_MAX_REFINES_PER_TICK=3` and 60s ticks, upper bound is 3 LLM calls/min — bounded but watch the bill. Config-overridable.
- **Private chats**: use `DEFAULT_THREAD_ID = 0` → key `"0"`. No special-casing.
- **Refine prompt wording**: left as a config string with a sensible default; review/tune during phase 4.
- **`max-messages-per-run` overflow (accepted risk)**: `getChatMessagesSince` is called with `limit = max-messages-per-run` (default 128). A burst larger than the cap means older messages beyond the cap are never fetched for that run and are permanently skipped (the cursor advances to the newest of the returned slice). Since refinement re-summarises recent context rather than being a durable log, this is accepted; `_runRefinement` emits a `logger.warning` when `len(messages) >= max-messages-per-run` so the overflow is observable. Tunable via `[user-memory.thresholds].max-messages-per-run`.

## 17. Architect review corrections

Applied 2026-07-04 against actual source. Each entry lists the fix + one-line rationale.

1. **§3 write-path rewritten as explicit read-modify-write of the nested `memoryRefinement` dict.** `setUserMetadata(isUpdate=True)` does a shallow top-level merge (`base.py:1085-1090`); passing a single-thread `{"memoryRefinement": {<threadId>: ...}}` would replace the whole sub-dict and silently wipe every other thread's summary. BLOCKER.
2. **§5 `_dtCronJob` signature pinned to `async def _dtCronJob(self, task: DelayedTask) -> None:` with the correct import.** `DelayedTaskHandler = Callable[[DelayedTask], Awaitable[None]]` (`queue_service/types.py:71`); canonical shape at `chat_search.py:284`. Without the `task` param, registration fails at call time. IMPORTANT.
3. **§6 step 6 render path pinned to `EnsuredMessage.fromDBChatMessage` + `formatForLLM(JSON, stripAtsign=True)`.** Vague "reuse or lightweight text render" replaced with the in-pattern renderer used by `SummarizationHandler._doSummarization`. IMPORTANT.
4. **§6 step 7 synthetic EnsuredMessage helper spelled out (keyword-only ctor, four required fields).** Constructor verified at `ensured_message.py:413-425`; only `.recipient.id`/`.sender.id` are read by the tool handlers (`user_data.py:127-128`). Removes the "verify in phase 4" hedging. IMPORTANT.
5. **§6 step 9 dropped redundant `keepLastN=1` (already the default, `service.py:426`); added note that tools are registered globally on `LLMService.toolsHandlers` so cross-handler tool requests work.** NIT + correctness clarification.
6. **§6 step 11 persistence rewritten to reference the §3 read-modify-write.** Reinforces the BLOCKER fix at the call site. BLOCKER.
7. **§7 `userId` param placement specified (after `messageCategory`, before `*, dataSource`); all 8 call sites confirmed safe.** NIT.
8. **§10 step 1: `userSummary` requires extending `__slots__` AND `__init__` initialization (not just "add attribute").** `EnsuredMessage` uses `__slots__` (`ensured_message.py:386-411`); bare assignment raises `AttributeError`. IMPORTANT.
9. **§10 step 2: added `getUserMemorySummary(chatId, userId, threadId)` helper on `BaseBotHandler`.** The summary lives in `chat_users.metadata`, NOT in the `user_data` table that `cache.getChatUserData` reads — the original "read from `chat_users.metadata...`" was correct conceptually but had no concrete read path. IMPORTANT.
10. **§11: split `[user-memory]` redefinition into `[user-memory]` + `[user-memory.prompts]`.** Duplicate `[user-memory]` table header is a TOML parse error. IMPORTANT.
11. **§13 file-by-file table: added `__slots__` note to `ensured_message.py` row, `ALLOW_SANDBOX` model reference to `chat_settings.py` row, `_makeSyntheticEnsuredMessage` + `_dtCronJob(self, task)` signature to `user_data.py` row, `getUserMemorySummary` helper to `base.py` row, expanded `user-memory.toml` section list, and pinned the friend-tier override line number (116) in `configs/common/01-bot-defaults.toml`.** IMPORTANT.
12. **§15 phase 1 expanded to include all TOML defaults + tier override + new `user-memory.toml`.** The four-site convention requires enum + `_chatSettingsInfo` + TOML default to land together; otherwise `chatSettings[MEMORY_REFINEMENT_ENABLED]` `KeyError`s between phases. IMPORTANT.
13. **§16 first risk item rewritten as RESOLVED.** Constructor fully verified; no remaining unknowns. NIT.
