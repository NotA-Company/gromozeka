---
category: reference
---

# User Memory Refinement — Task Memory

> **⚠ SUPERSEDED (2026-07-07) by the unified user-memories system.** This
> doc describes the **rolling-bio** subsystem that was replaced. The
> canonical durable doc is now
> [`user-memories.md`](user-memories.md); the implementation spec is
> [`docs/archive/plans/user-memories-v1.md`](../../archive/plans/user-memories-v1.md).
>
> **What is superseded (described below as LIVE behaviour — no longer
> shipped):**
> - The rolling-bio **summary** artefact and its injection as
>   `EnsuredMessage.userSummary` (via `applyUserMetadata`, serialised by
>   `formatForLLM` under the `userSummary` key) — removed entirely in
>   Phase 4b of the user-memories plan (§9.3). Replaced by the structured
>   `<user-memories>` block (`_buildMemoriesBlock`).
> - The `_runRefinement` write of the `summary` blob — `_runRefinement` now
>   persists only the message cursor; memories are authored live via the
>   `add_memory` / `delete_memory` / `search_memories` tools.
> - The `add_user_data` / `delete_user_data` LLM tools — retired.
>
> **What is still accurate and was adapted for the new system** (the
> accounting / cron / locking / cursor machinery is unchanged and still
> governs `_runRefinement`):
> - The `_dtCronJob` (60s) + `_accounting` counter (credit-consumed reset) +
>   single global `_refineLock` + online top-K due-list selection —
>   "Concurrency model" below is accurate.
> - The message cursor (`lastProcessedMessageId` /
>   `lastProcessedMessageDate`) persisted to
>   `chat_users.metadata.memoryRefinement[str(threadId)]` via the
>   read-modify-write + `chatUserMetadataLock()` pattern — still used
>   (cursor-only now; the `summary` key is gone).
> - The nested-metadata-write invariant + ADR-014/015 lock ordering — still
>   apply (see "CRITICAL gotcha — nested metadata writes").
> - `_makeSyntheticEnsuredMessage` — reused by the new tools.
>
> This file is retained for historical context. Do not implement from it;
> implement from [`user-memories.md`](user-memories.md).
>
> **Note:** the `<user-memories>` block referenced below was itself
> superseded by centralized preprocessor injection
> (`MessagePreprocessorHandler.injectMemories`) — see
> [`user-memories.md`](user-memories.md) for the current architecture.

Durable implementation notes for the background per-`(chat, user, thread)` memory-refinement subsystem. Implemented 2026-07-04 from [`docs/archive/plans/memory-refine-plan-v1.md`](../../archive/plans/memory-refine-plan-v1.md) (status line there updated to IMPLEMENTED). Owner handler: ~~`UserDataHandler` (`internal/bot/common/handlers/user_data.py`)~~ — file deleted; class renamed to `UserMemoriesHandler` in [`internal/bot/common/handlers/user_memories.py`](/internal/bot/common/handlers/user_memories.py).

## Subsystem at a glance

> **[SUPERSEDED — see banner]** The handler, file, and tool names below describe the rolling-bio system that was removed; kept as a historical record.

- Every incoming message increments an in-memory `UserDataHandler._accounting[(chatId, userId, threadId)]` counter (gated by the per-chat `MEMORY_REFINEMENT_ENABLED` setting), at the very top of `newMessageHandler`, before any other gate.
- A 60s `CRON_JOB` (`_dtCronJob`) scans the counter; when a user crosses the count threshold (`5`) OR the time threshold (6h since the in-memory `_lastRefinedTS`), it runs `_runRefinement`. All `[user-memory]` config is read ONCE in `__init__` and cached as instance attributes (`_memoryRefineEnabled`, `_memoryCountThreshold`, `_memoryTimeThresholdSeconds`, `_memoryMinMessagesToRefine`, `_memoryMaxMessagesPerRun`, `_memoryMaxRefinesPerTick`); the cron hot path and `_runRefinement` perform NO `configManager.get(...)` calls.
- `_runRefinement` fetches the user's recent messages via `getChatMessagesSince` (new `userId` filter), renders them, and calls `LLMService.generateTextViaLLM` with `chatId=None` (skips rate-limiting) and a per-tool dict: ~~`ADD_USER_DATA`, `DELETE_USER_DATA`, `SEARCH_MESSAGES`, `GET_CURRENT_DATETIME`~~ (all retired; current tools are `add_memory` / `delete_memory` / `search_memories` — see [`user-memories.md`](user-memories.md)). The resulting summary text replaces the old one. If the fetch hits the `max-messages-per-run` cap (default 128), older overflow messages are silently skipped and a `logger.warning` is emitted (accepted risk: a burst >128 permanently loses the tail for that run — see [`../../archive/plans/memory-refine-plan-v1.md`](../../archive/plans/memory-refine-plan-v1.md) §16).
- ~~The summary is injected into normal chat context as `EnsuredMessage.userSummary` (omitted from JSON when `None` → byte-identical default output).~~ **[SUPERSEDED]** — `userSummary` / `applyUserMetadata` / the `formatForLLM` key were removed in Phase 4b; replaced by the structured `<user-memories>` block (`_buildMemoriesBlock`).

## Storage convention (NO migration)

- `chat_users.metadata TEXT DEFAULT '' NOT NULL` (added by `migration_003`, re-asserted by `migration_013`). No schema change for this feature.
- JSON shape: `UserMetadataDict` (`internal/bot/models/user_metadata.py`, `total=False`) = boolean flags (`isSpammer`, `notSpammer`, `dropMessages`, `leftChat`) + optional `memoryRefinement: Dict[str(threadId), UserMemoryThreadDict]`.
- Per-thread entry (rolling-bio shape, **now legacy**): `{summary (REMOVED in Phase 4a), lastProcessedMessageId (MessageId.asStr, debug only), lastProcessedMessageDate (ISO — the MESSAGE cursor for getChatMessagesSince)}`. The current `UserMemoryThreadDict` TypedDict (`internal/bot/models/user_metadata.py`) carries ONLY `lastProcessedMessageId` + `lastProcessedMessageDate` — the `summary` field is gone (see banner). The `lastRefinedTS` (drives the 6h time threshold) is NO LONGER persisted — it is tracked in-memory on `UserMemoriesHandler._lastRefinedTS[(chatId, userId, threadId)]` (lost on restart; absent → 0 → treated as due).

## CRITICAL gotcha — nested metadata writes

`BaseBotHandler.setUserMetadata(chatId, userId, metadata, isUpdate=True)` does a **one-level shallow merge** (`{**oldMetadata, **newMetadata}`). Passing a partial `{"memoryRefinement": {<threadId>: ...}}` **replaces the entire `memoryRefinement` sub-dict**, wiping every other thread's summary.

The refinement write path (`user_memories.py`'s `_runSingleRefinement` inlined cursor-persist block, formerly the standalone `_persistMemoryEntry` method) bypasses `setUserMetadata` entirely and does read-modify-write through `CacheService` (see ADR-015 — all single-row `chat_users` reads/writes route through the cache layer, not `self.db.chatUsers.*` directly):

```python
async with self.cache.chatUserMetadataLock():
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

The `chatUserMetadataLock()` context manager (a single process-global `asyncio.Lock` on `CacheService`, `_chatUsersMetadataLock`) serializes the full RMW so concurrent metadata writers (`setUserMetadata(isUpdate=True)` is the other one) cannot lose updates. Lock ordering inside the refinement flow: `_refineLock` (outer) → `chatUserMetadataLock` (inner) — see [`../architecture.md`](../architecture.md) ADR-014 / ADR-015.

**Cache routing (2026-07-05, no behavior change):** `_readMemoryEntry` and `_runSingleRefinement`'s inlined cursor-persist (formerly `_persistMemoryEntry`) now read/write via `CacheService.getUserMetadata` / `updateUserMetadata` instead of `self.db.chatUsers.*`. (The former `BaseBotHandler.getUserMemorySummary` reader was folded into `EnsuredMessage.applyUserMetadata` — see "Context injection sites" below.) The nested-write invariant above is preserved — `updateUserMetadata` does a full-dict replace with NO merge, so the explicit full-read + nested-mutate + full-write pattern is unchanged. See [`../architecture.md`](../architecture.md) ADR-015.

This is also recorded as a reusable gotcha in [`tasks.md`](../tasks.md) §3.

## Concurrency model

> **Class rename:** `UserDataHandler` → `UserMemoriesHandler` (file `user_data.py` deleted; class now in `internal/bot/common/handlers/user_memories.py`). The method `_runRefinement` was renamed to `_runSingleRefinement` in the same pass. The locks and counters below carried over unchanged.

- **Two locks** govern the scan+dispatch. The **single global `asyncio.Lock`** (`UserMemoriesHandler._refineLock`) still serializes the whole scan+dispatch: the cron does `if self._refineLock.locked(): return` then `async with self._refineLock:` — there is no `await` between the bail check and acquisition, so from asyncio's point of view acquisition is instantaneous and no second tick can slip past the bail. A **second `asyncio.Lock`** (`_accountingLock`, added post-v1) now serializes all mutations of `_accounting` and `_lastRefinedTS` (increment in `newMessageHandler`, credit-consumed subtract/drop in `_dtCronJob`, TS writes in `_runSingleRefinement`'s body and finally block, TS reads in the due-list scan) so the scan never observes a half-updated timestamp. The snapshot `list(self._accounting.items())` that seeds the scan is taken WITHOUT `_accountingLock` — `dict.items()` is atomic w.r.t. `await` on a single event loop.
- Bounded by `max-refines-per-tick` (default 3); runs execute sequentially under the lock. No `createTask`.
- The counter uses a **credit-consumed** reset in the `finally` block: `_accounting[key] = max(0, _accounting.get(key, 0) - preCount)` where `preCount` is the count captured at scan time. This preserves increments from messages that arrived during the (possibly multi-second) LLM call. When the result is `0` the key is **popped** from `_accounting` (not kept at `0`) so empty keys aren't re-iterated next tick. The OLD unconditional `= 0` wiped those increments — a race fixed in follow-up #1.
- **Due-list selection (online top-K)** — the scan maintains a bounded `due` list of size ≤ `_memoryMaxRefinesPerTick`, keeping the entries with the SMALLEST `lastRefinedTS` (oldest-due / never-refined carry TS=0). When full, a new candidate with a smaller `lastRefinedTS` than the running max evicts that max; the running max is then recomputed. The 3rd tuple element is `lastRefinedTS` (int), not `elapsed` (float). This replaces the previous collect-all → `due.sort(key=lambda x: (-x[2], -x[1]))` (largest-elapsed-first) → `[:maxRefinesPerTick]`. Dispatch order within the selected K is unspecified — acceptable since K is tiny and all selected entries get processed in the happy path.
- **Never-refined users are NOT skipped** — the old pre-filter (`isNeverRefined and newMessagesCount < minMessages: continue`, which gated on the new-message counter and did NOT reset it) was removed because refinement of a never-refined user pulls *lifetime* messages via `getChatMessagesSince(sinceDateTime=None)`. The skip was over-conservative — it blocked users with plenty of pre-existing chat history but few messages since feature-enable. Now never-refined users (TS=0 → due-by-time) enter the due list normally; if genuinely too few lifetime messages, `_runRefinement` bails once on the `< min-messages-to-refine` path and advances the in-memory `_lastRefinedTS` (no retry until the count/time threshold fires again).
- **Bail-path TS reset** — `_runRefinement` sets `self._lastRefinedTS[(chatId, userId, threadId)] = int(time.time())` on the `< min-messages` bail path, so idle (e.g. post-restart, previously-refined) users aren't re-scanned and re-bailed on every 60s tick until enough new messages accumulate. The count threshold still fires independently. Without this the cron hot-loops over idle due-by-time users.

## Context injection sites

> **[SUPERSEDED — entire section.]** Every site below (`applyUserMetadata`,
> the `_updateEMessageUserData` / `_processMessageRec` metadata fetch, the
> `formatForLLM` `userSummary` key, the `chat-prompt-suffix` docs line) was
> removed in Phase 4b. The structured `<user-memories>` block
> (`_buildMemoriesBlock`) is now injected at four system-message
> construction sites instead — see [`user-memories.md`](user-memories.md)
> "Injection". This section is kept verbatim as a record of how the old
> system wired the summary into context.

- `EnsuredMessage.applyUserMetadata(metadata)` — reads `metadata.get("memoryRefinement", {}).get(str(threadId or DEFAULT_THREAD_ID), {}).get("summary")` and, when non-empty, assigns it to `self.userSummary`. Pure reader of the passed-in dict; does NOT persist `metadata`.
- `BaseBotHandler._updateEMessageUserData` (`base.py`) and `HandlersManager._processMessageRec` (`manager.py`) fetch the full `UserMetadataDict` via `cache.getUserMetadata(...)` and pass it to `ensuredMessage.applyUserMetadata(...)`. Intentionally NOT gated on the per-chat `MEMORY_REFINEMENT_ENABLED` setting at injection — the write side (`UserMemoriesHandler._runSingleRefinement`) only persists summaries when the feature is on, so absence of a summary in metadata is the gate. A stale summary for a since-disabled chat will still be injected; this is accepted as the intended simplification.
- `EnsuredMessage.formatForLLM` emits `"userSummary"` in the JSON branch; the dict comprehension drops falsy values, so a `None` summary is omitted → byte-identical output for chats with the feature off.
- The `chat-prompt-suffix` in `configs/00-defaults/bot-defaults.toml` documents the new `userSummary` field to the chat model.

## Config locations

- `configs/00-defaults/user-memory.toml` (tracked): `[user-memory].enabled` (global kill switch, default false) and `[user-memory.thresholds]`. The `[user-memory.prompts]` section was REMOVED — prompts are now per-chat settings (see below).
- `configs/00-defaults/bot-defaults.toml` (tracked): `memory-refine-model` (`"openrouter/free"`), `memory-refine-fallback-model` (`"aliceai-llm-flash"`), `memory-refinement-enabled = false`, `memory-refine-system-prompt`, `memory-refine-user-prompt-template` — all under `[bot.defaults]`.
- **`configs/common/` is gitignored** — the friend-tier `memory-refinement-enabled = true` lives in the local overlay (`configs/common/01-bot-defaults.toml` under `[bot.tier-defaults.friend]`), same model as `allow-sandbox`. It will NOT propagate via git; it's a per-deployment manual overlay step. See [`teamlead-memory.md`](../teamlead-memory.md) "Configs Tracking Gotcha".

## JSONL refinement log (optional, 2026-07-06)

Configurable JSONL logging of every successful refinement run, mirroring the LLM-interaction logger (`AbstractModel.printJSONLog`). Config: `[user-memory.json-logging]` sub-table (3 keys: `enabled`/`file`/`add-date-suffix`, defaults `false`/`"logs/user-memory-refinement-json.log"`/`true`) in `configs/00-defaults/user-memory.toml`. Read ONCE in `UserDataHandler.__init__` into `_refineLogEnabled` / `_refineLogFile` / `_refineLogAddDateSuffix` (same cache-once pattern as the other `[user-memory]` keys); see [`configuration.md`](../configuration.md) §`[user-memory.json-logging]`.

**Hook placement** (`_runSingleRefinement`, `internal/bot/common/handlers/user_memories.py` — historically `_runRefinement` in the deleted `user_data.py`): AFTER the LLM returns and the tool-call counts are derived, BEFORE the cursor persist. Consequences (largely unchanged from rolling-bio):

- **Success path:** logged, then persisted.
- **Empty summary:** logged (empty string), then early-returns without persisting. (Intentional — the user decided to log empty summaries too.)
- **Exception during the LLM call:** NOT logged — the exception re-raises (caught by the outer `try/except` which logs and returns) before the hook runs. Success-path-only by design, mirroring `printJSONLog`.

The hook is guarded by `if self._refineLogEnabled:` so no work happens when disabled (the default).

**12 logged fields** (one JSONL line per successful run, `utils.jsonDumps(data, sort_keys=False)`):

> **[UPDATED for Phase 4a]** The original rolling-bio `model` / `elapsedTime` fields were DROPPED and three per-tool count fields (`addCount` / `deleteCount` / `searchCount`, derived via `_countRefinementToolCalls` over `result.toolUsageHistory`) were ADDED when refinement switched from "emit a summary blob" to "curate memories via tools". The `summary` field is still emitted but is now just the LLM's raw text output (often empty — the model emits tool calls instead of a dossier).

- `date` — UTC ISO timestamp of the log write.
- `chatId`, `threadId`, `userId` — int identifiers of the refined scope.
- `login` — the user's `username` (`messages[0]["username"]`, JOIN'd from `chat_users`; may be `""`).
- `messagesCount` — `len(messages)` (≤ `_memoryMaxMessagesPerRun`, default 128).
- `firstMessageId` — `messages[-1]["message_id"].asStr()` (oldest, DESC order).
- `lastMessageId` — `messages[0]["message_id"].asStr()` (newest — the cursor advanced to).
- `summary` — `result.resultText` (stripped; the exact value the model emitted — often empty in the tools-driven Phase 4a path; kept for debugging).
- `addCount` — number of `add_memory` tool calls in the run (the primary observability for the grey-zone dedup review).
- `deleteCount` — number of `delete_memory` tool calls in the run.
- `searchCount` — number of `search_memories` tool calls in the run.

**File write** — `_writeRefinementJsonLog`: bare `open(file, "a")` + `utils.jsonDumps(data) + "\n"` (append mode). Wrapped in `try/except OSError` with `logger.debug` on failure — refinement must not break over a log write. **This intentionally diverges from `printJSONLog`, which has no error handling.** Date-suffix, when enabled, appends `.<YYYY-MM-DD>` (UTC) to the filename. No shared JSONL-writer utility was extracted — `_writeRefinementJsonLog` is handler-local.

## Chat settings (four-site convention)

All five live in `_chatSettingsInfo` (`internal/bot/models/chat_settings.py`); pages are tier-mixed (not all on one page):

| `ChatSettingsKey` | TOML key | Type | Page |
|---|---|---|---|
| `MEMORY_REFINEMENT_ENABLED` | `memory-refinement-enabled` | BOOL | `LLM_PAID` |
| `MEMORY_REFINE_MODEL` | `memory-refine-model` | MODEL | `LLM_MODELS` |
| `MEMORY_REFINE_FALLBACK_MODEL` | `memory-refine-fallback-model` | MODEL | `LLM_MODELS` |
| `MEMORY_REFINE_SYSTEM_PROMPT` | `memory-refine-system-prompt` | STRING | `BOT_OWNER_SYSTEM` |
| `MEMORY_REFINE_USER_PROMPT_TEMPLATE` | `memory-refine-user-prompt-template` | STRING | `BOT_OWNER_SYSTEM` |

New tool: ~~`ToolName.DELETE_USER_DATA = "delete_user_data"` (`internal/bot/constants.py`), registered alongside the existing `ADD_USER_DATA`.~~ **[SUPERSEDED]** — both `add_user_data` and `delete_user_data` were retired; the new tools are `add_memory` / `delete_memory` / `search_memories` (see [`user-memories.md`](user-memories.md) "LLM tools").

## Synthetic EnsuredMessage for background tool calls

The `add_user_data` / `delete_user_data` tool handlers read `extraData["ensuredMessage"].recipient.id` and `.sender.id`. The background cron call has no real message, so `_makeSyntheticEnsuredMessage(chatId, userId, threadId)` builds a minimal `EnsuredMessage` (keyword-only ctor, four required fields) with `recipient.id = chatId`, `sender.id = userId`, and dummy values for the rest. Only those two fields are read by the tools.

## Tests

- `tests/database/test_db_wrapper.py` — `testGetChatMessagesSinceWithUserId` (the new `userId` filter).
- `tests/bot/common/handlers/test_user_data.py` — delete tool, increment/NEXT, threadId normalization, cron early-returns (disabled / lock-held), dispatch + counter reset + cursor persistence + in-memory `lastRefinedTS`, bail-on-too-few, never-refined dispatch + bail-on-too-few-lifetime-messages (post-refactor: never-refined users are refined from lifetime history, not pre-skipped), credit-consumed counter reset (increments during LLM call preserved).
- `tests/bot/models/test_ensured_message.py` — `userSummary` omit-when-None (byte-identity) + include-when-set (`TestFormatForLLMUserSummary`), and the relocated 4 extraction cases driving `EnsuredMessage.applyUserMetadata` directly (`TestApplyUserMetadata`).
