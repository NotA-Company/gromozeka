# User Memory Refinement — Task Memory

Durable implementation notes for the background per-`(chat, user, thread)` memory-refinement subsystem. Implemented 2026-07-04 from [`docs/plans/memory-refine-plan-v1.md`](../../plans/memory-refine-plan-v1.md) (status line there updated to IMPLEMENTED). Owner handler: `UserDataHandler` (`internal/bot/common/handlers/user_data.py`).

## Subsystem at a glance

- Every incoming message increments an in-memory `UserDataHandler._accounting[(chatId, userId, threadId)]` counter (gated by the per-chat `MEMORY_REFINEMENT_ENABLED` setting), at the very top of `newMessageHandler`, before any other gate.
- A 60s `CRON_JOB` (`_dtCronJob`) scans the counter; when a user crosses the count threshold (`5`) OR the time threshold (6h since the in-memory `_lastRefinedTS`), it runs `_runRefinement`. All `[user-memory]` config is read ONCE in `__init__` and cached as instance attributes (`_memoryRefineEnabled`, `_memoryCountThreshold`, `_memoryTimeThresholdSeconds`, `_memoryMinMessagesToRefine`, `_memoryMaxMessagesPerRun`, `_memoryMaxRefinesPerTick`); the cron hot path and `_runRefinement` perform NO `configManager.get(...)` calls.
- `_runRefinement` fetches the user's recent messages via `getChatMessagesSince` (new `userId` filter), renders them, and calls `LLMService.generateTextViaLLM` with `chatId=None` (skips rate-limiting) and a per-tool dict: `ADD_USER_DATA`, `DELETE_USER_DATA`, `SEARCH_MESSAGES`, `GET_CURRENT_DATETIME`. The resulting summary text replaces the old one.
- The summary is injected into normal chat context as `EnsuredMessage.userSummary` (omitted from JSON when `None` → byte-identical default output).

## Storage convention (NO migration)

- `chat_users.metadata TEXT DEFAULT '' NOT NULL` (added by `migration_003`, re-asserted by `migration_013`). No schema change for this feature.
- JSON shape: `UserMetadataDict` (`internal/bot/models/user_metadata.py`, `total=False`) = boolean flags (`isSpammer`, `notSpammer`, `dropMessages`, `leftChat`) + optional `memoryRefinement: Dict[str(threadId), UserMemoryThreadDict]`.
- Per-thread entry: `{summary, lastProcessedMessageId (MessageId.asStr, debug only), lastProcessedMessageDate (ISO — the MESSAGE cursor for getChatMessagesSince)}`. The `lastRefinedTS` (drives the 6h time threshold) is NO LONGER persisted — it is tracked in-memory on `UserDataHandler._lastRefinedTS[(chatId, userId, threadId)]` (lost on restart; absent → 0 → treated as due).

## CRITICAL gotcha — nested metadata writes

`BaseBotHandler.setUserMetadata(chatId, userId, metadata, isUpdate=True)` does a **one-level shallow merge** (`{**oldMetadata, **newMetadata}`). Passing a partial `{"memoryRefinement": {<threadId>: ...}}` **replaces the entire `memoryRefinement` sub-dict**, wiping every other thread's summary.

The refinement write path (`user_data.py` `_persistMemoryEntry`) bypasses `setUserMetadata` entirely and does read-modify-write through `CacheService` (see ADR-015 — all single-row `chat_users` reads/writes route through the cache layer, not `self.db.chatUsers.*` directly):

```python
metadata = await self.cache.getUserMetadata(chatId=chatId, userId=userId)
refinement = metadata.get("memoryRefinement", {})
refinement[str(threadId)] = {  # mutate only this thread's entry
    "summary": summary,
    "lastProcessedMessageId": lastProcessedMessageId,
    "lastProcessedMessageDate": lastProcessedMessageDate,
}
metadata["memoryRefinement"] = refinement
await self.cache.updateUserMetadata(chatId=chatId, userId=userId, metadata=metadata)
# lastRefinedTS is tracked in-memory only, NOT in the persisted dict:
self._lastRefinedTS[(chatId, userId, threadId)] = int(time.time())
```

**Cache routing (2026-07-05, no behavior change):** `_readMemoryEntry`, `_persistMemoryEntry`, and `getUserMemorySummary` now read/write via `CacheService.getUserMetadata` / `updateUserMetadata` instead of `self.db.chatUsers.*`. The nested-write invariant above is preserved — `updateUserMetadata` does a full-dict replace with NO merge, so the explicit full-read + nested-mutate + full-write pattern is unchanged. See [`../architecture.md`](../architecture.md) ADR-015.

This is also recorded as a reusable gotcha in [`tasks.md`](../tasks.md) §3.

## Concurrency model

- A **single global `asyncio.Lock`** (`UserDataHandler._refineLock`) serializes the whole scan+dispatch. The cron does `if self._refineLock.locked(): return` then `async with self._refineLock:` — there is no `await` between the bail check and acquisition, so from asyncio's point of view acquisition is instantaneous and no second tick can slip past the bail.
- Bounded by `max-refines-per-tick` (default 3); runs execute sequentially under the lock. No per-entry locks, no `createTask`.
- The counter uses a **credit-consumed** reset in the `finally` block: `_accounting[key] = max(0, _accounting.get(key, 0) - preCount)` where `preCount` is the count captured at scan time. This preserves increments from messages that arrived during the (possibly multi-second) LLM call. When the result is `0` the key is **popped** from `_accounting` (not kept at `0`) so empty keys aren't re-iterated next tick. The OLD unconditional `= 0` wiped those increments — a race fixed in follow-up #1.
- **Due-list selection (online top-K)** — the scan maintains a bounded `due` list of size ≤ `_memoryMaxRefinesPerTick`, keeping the entries with the SMALLEST `lastRefinedTS` (oldest-due / never-refined carry TS=0). When full, a new candidate with a smaller `lastRefinedTS` than the running max evicts that max; the running max is then recomputed. The 3rd tuple element is `lastRefinedTS` (int), not `elapsed` (float). This replaces the previous collect-all → `due.sort(key=lambda x: (-x[2], -x[1]))` (largest-elapsed-first) → `[:maxRefinesPerTick]`. Dispatch order within the selected K is unspecified — acceptable since K is tiny and all selected entries get processed in the happy path.
- **Never-refined users are NOT skipped** — the old pre-filter (`isNeverRefined and newMessagesCount < minMessages: continue`, which gated on the new-message counter and did NOT reset it) was removed because refinement of a never-refined user pulls *lifetime* messages via `getChatMessagesSince(sinceDateTime=None)`. The skip was over-conservative — it blocked users with plenty of pre-existing chat history but few messages since feature-enable. Now never-refined users (TS=0 → due-by-time) enter the due list normally; if genuinely too few lifetime messages, `_runRefinement` bails once on the `< min-messages-to-refine` path and advances the in-memory `_lastRefinedTS` (no retry until the count/time threshold fires again).
- **Bail-path TS reset** — `_runRefinement` sets `self._lastRefinedTS[(chatId, userId, threadId)] = int(time.time())` on the `< min-messages` bail path, so idle (e.g. post-restart, previously-refined) users aren't re-scanned and re-bailed on every 60s tick until enough new messages accumulate. The count threshold still fires independently. Without this the cron hot-loops over idle due-by-time users.

## Context injection sites

- `BaseBotHandler.getUserMemorySummary(chatId, userId, threadId)` — reads `parseUserMetadata(...).get("memoryRefinement", {}).get(str(threadId), {}).get("summary")`.
- `BaseBotHandler._updateEMessageUserData` (`base.py`) and `HandlersManager._processMessageRec` (`manager.py`, via `self.handlers[0][0]`) attach it as `ensuredMessage.userSummary`, gated on the per-chat setting.
- `EnsuredMessage.formatForLLM` emits `"userSummary"` in the JSON branch; the dict comprehension drops falsy values, so a `None` summary is omitted → byte-identical output for chats with the feature off.
- The `chat-prompt-suffix` in `configs/00-defaults/bot-defaults.toml` documents the new `userSummary` field to the chat model.

## Config locations

- `configs/00-defaults/user-memory.toml` (tracked): `[user-memory].enabled` (global kill switch, default false) and `[user-memory.thresholds]`. The `[user-memory.prompts]` section was REMOVED — prompts are now per-chat settings (see below).
- `configs/00-defaults/bot-defaults.toml` (tracked): `memory-refine-model` (`"openrouter/free"`), `memory-refine-fallback-model` (`"aliceai-llm-flash"`), `memory-refinement-enabled = false`, `memory-refine-system-prompt`, `memory-refine-user-prompt-template` — all under `[bot.defaults]`.
- **`configs/common/` is gitignored** — the friend-tier `memory-refinement-enabled = true` lives in the local overlay (`configs/common/01-bot-defaults.toml` under `[bot.tier-defaults.friend]`), same model as `allow-sandbox`. It will NOT propagate via git; it's a per-deployment manual overlay step. See [`teamlead-memory.md`](../teamlead-memory.md) "Configs Tracking Gotcha".

## Chat settings (four-site convention)

All five are `page = ChatSettingsPage.FRIEND` in `_chatSettingsInfo` (`internal/bot/models/chat_settings.py`):

| `ChatSettingsKey` | TOML key | Type |
|---|---|---|
| `MEMORY_REFINEMENT_ENABLED` | `memory-refinement-enabled` | BOOL |
| `MEMORY_REFINE_MODEL` | `memory-refine-model` | MODEL |
| `MEMORY_REFINE_FALLBACK_MODEL` | `memory-refine-fallback-model` | MODEL |
| `MEMORY_REFINE_SYSTEM_PROMPT` | `memory-refine-system-prompt` | STRING |
| `MEMORY_REFINE_USER_PROMPT_TEMPLATE` | `memory-refine-user-prompt-template` | STRING |

New tool: `ToolName.DELETE_USER_DATA = "delete_user_data"` (`internal/bot/constants.py`), registered alongside the existing `ADD_USER_DATA`.

## Synthetic EnsuredMessage for background tool calls

The `add_user_data` / `delete_user_data` tool handlers read `extraData["ensuredMessage"].recipient.id` and `.sender.id`. The background cron call has no real message, so `_makeSyntheticEnsuredMessage(chatId, userId, threadId)` builds a minimal `EnsuredMessage` (keyword-only ctor, four required fields) with `recipient.id = chatId`, `sender.id = userId`, and dummy values for the rest. Only those two fields are read by the tools.

## Tests

- `tests/database/test_db_wrapper.py` — `testGetChatMessagesSinceWithUserId` (the new `userId` filter).
- `tests/bot/common/handlers/test_user_data.py` — delete tool, increment/NEXT, threadId normalization, cron early-returns (disabled / lock-held), dispatch + counter reset + cursor persistence + in-memory `lastRefinedTS`, bail-on-too-few, never-refined dispatch + bail-on-too-few-lifetime-messages (post-refactor: never-refined users are refined from lifetime history, not pre-skipped), credit-consumed counter reset (increments during LLM call preserved).
- `tests/bot/models/test_ensured_message.py` — `userSummary` omit-when-None (byte-identity) + include-when-set.
- `tests/bot/common/handlers/test_base.py` — `getUserMemorySummary` across 4 cases.
