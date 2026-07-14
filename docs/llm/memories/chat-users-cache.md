# Chat Users Cache (ADR-015)

Write-through `chat_users` cache in `CacheService`, eliminating 2–5 redundant `chat_users` reads per inbound message (memory-summary reads during LLM history reconstruction, spam `checkSpam`, per-message `updateChatUser` upsert, internal metadata-read inside `setUserMetadata`). Read this file when working on `CacheService` chat-user methods, `SpamHandler._getUserInfoFreshIfMessagesLessThan`, any `chat_users.metadata` writer, or the `chatUserMetadataLock()` concurrency contract. Canonical decision: ADR-015 in [`../architecture.md`](../architecture.md); plan of record: [`../../plans/user-info-cache-plan-v1.md`](../../plans/user-info-cache-plan-v1.md). For the nested-write hazard as it affects the refinement path, see the companion [`user-memory-refinement.md`](user-memory-refinement.md); for the structured-memory rewrite that still relies on this cache for the message-cursor persist, see [`user-memories.md`](user-memories.md).

## Cache design

- **Reused `CacheNamespace.CHAT_USERS`** (keyed `f"{chatId}:{userId}"`, `MEMORY_ONLY`); no new namespace. The value TypedDict `HCChatUserCacheDict` was extended with a second lazily-loaded field `userInfo: NotRequired[ChatUserDict]` (non-Optional; presence-of-key = "loaded") alongside the existing `permanentMemories`.
- **Lazy-field independence:** `permanentMemories` and `userInfo` load independently. Both are `NotRequired`; presence-of-key is the "loaded" sentinel. A cached entry may carry `permanentMemories` without `userInfo`, or vice versa. `CHAT_USERS` is `MEMORY_ONLY`, so `persistAll`/`loadFromDatabase` ignore it — cold cache at startup, warmed lazily on first `getChatUser`. The new methods do not touch `self.dirtyKeys` (that set is never flushed for `MEMORY_ONLY` namespaces).
- **Absent DB row is NOT memoized:** `getChatUser` returns `None` and leaves the cache cold, so the next call re-queries the DB. An absent `(chatId, userId)` row indicates something went wrong upstream (e.g. a message arrived before the row was seeded) and is not worth caching.

## `CacheService` methods

Five new methods in `internal/services/cache/service.py`:

- `getChatUser(chatId, userId, *, refresh=False)` — LRU read, DB fallback on miss/`refresh`. Returns a **defensive shallow copy** (`dict(cachedRow)`) so callers cannot mutate the cached row. On a miss OR `refresh=True`, the row is read from DB: if found, it is cached and a copy returned; if absent, `None` is returned WITHOUT caching the absence.
- `updateChatUser(chatId, userId, username, fullName)` — write-through upsert with **skip-when-unchanged** (if the cached row's `username`/`full_name` already equal the supplied values, the DB upsert is skipped entirely). On a cache hit the cached row is mutated in place; **on a cache miss the cache is intentionally LEFT COLD** (no warming re-read) — the next `getChatUser` lazy-loads it if needed, so a warming re-read would be a wasted query on the write path.
- `getUserMetadata(chatId, userId)` — parses the cached row's `metadata` column via `json.loads` (empty/None → `{}`). Returns a freshly-parsed dict (no aliasing).
- `updateUserMetadata(chatId, userId, metadata)` — write-through **full-dict replace** (serializes via `utils.jsonDumps`, writes via `db.chatUsers.updateUserMetadata`, then updates the cached row's `metadata`/`updated_at` in place). Performs **NO merge**.
- `invalidateChatUser(chatId, userId)` — sync; pops **only** the `userInfo` key (preserves the `permanentMemories` cache). Escape hatch for out-of-band mutations; no callers today.

All single-row `(chatId, userId)` handler reads/writes route through `self.cache.*`, not `self.db.chatUsers.*`. Aggregate/by-username queries (`getChatUserByUsername`, `getChatUsers`, `getUserChats`, `getAllGroupChats`, `getUserIdByUserName`) are NOT cached.

**Write-through ordering:** all setters write the DB first and update the cache only on success, so a DB failure leaves the cache untouched (no cache-DB divergence).

## Skip-when-unchanged optimization

Because `updateChatUser` is a no-op when `username`/`full_name` are unchanged, `updated_at` no longer refreshes on such calls. Accepted trade-off; callers must not assume `updated_at` moves on every `updateChatUser` invocation. (`saveChatMessage`'s raw `messages_count` increment still bumps `updated_at` independently on every message.)

## `messages_count` staleness hazard

`messages_count` is stale on a cached row — incremented by raw SQL in `ChatMessagesRepository.saveChatMessage` ([`/internal/database/repositories/chat_messages.py`](/internal/database/repositories/chat_messages.py) line 154), bypassing the cache. Callers needing an accurate count SHOULD use the conditional-refresh helper `SpamHandler._getUserInfoFreshIfMessagesLessThan(chatId, userId, threshold)`, which re-fetches only when the cached count is strictly below the threshold (a monotonic value at/above the threshold stays valid). Because `messages_count` is monotonically non-decreasing, an at-or-above value can only stay there or grow, so it remains valid for any `>=` / `>` gate; only a cached value strictly below the threshold might have drifted up past it, so only that case pays for a `refresh=True` re-fetch.

The two correctness-critical spam readers (gating on `AUTO_SPAM_MAX_MESSAGES`) use it with gate-direction-appropriate thresholds:

- `checkSpam` (a `>=` gate) passes the threshold unchanged.
- `markAsSpam` (a STRICT `>` gate) passes `threshold + 1` so the boundary case (`cached == maxSpamMessages`) still triggers a refresh, closing the false-ban window.

A direct `getChatUser(..., refresh=True)` is still available when an unconditional refresh is genuinely required.

## Nested-write invariant

`updateUserMetadata` does NO merge. Nested writers (the refinement cursor-persist path (`_runSingleRefinement`)) must read full metadata → mutate one nested key → write full dict back. A blind shallow top-level merge (`{**old, **new}`) would wipe sibling keys — e.g. a partial `{"memoryRefinement": {<threadId>: ...}}` passed to `setUserMetadata(isUpdate=True)` replaces the entire `memoryRefinement` sub-dict, wiping every other thread's summary. The same hazard ADR-014 documents for `setUserMetadata(isUpdate=True)`.

## Coupling note

Every `metadata` writer MUST route through the cache. `setUserMetadata(isUpdate=True)` and the refinement cursor-persist path (`_runSingleRefinement`) now read/merge against the cached row. A future raw `db.chatUsers.updateUserMetadata(...)` bypass would silently desync the cache and corrupt subsequent `setUserMetadata(isUpdate=True)` merges. Do not add such bypasses for `metadata` — the `messages_count` increment is the sole accepted bypass, and it does not touch `metadata`.

## Metadata RMW lock

`CacheService._chatUsersMetadataLock` (single process-global `asyncio.Lock`) serializes `chat_users.metadata` access. Exposed via `chatUserMetadataLock()` async context manager (`@contextlib.asynccontextmanager`, `-> AsyncIterator[None]`). Intentionally process-global rather than per-`(chat, user)` — metadata writes are infrequent, so cross-user contention is negligible.

**Holders:**

- `BaseBotHandler.setUserMetadata` — BOTH the `isUpdate=True` read-merge-write AND the `isUpdate=False` full-replace branches. The `async with` wraps the entire method body; serializing the full-replace prevents it from being clobbered by a concurrent RMW. (The `isUpdate=False` branch holds the lock not because the bare full-replace needs it, but to prevent a concurrent RMW elsewhere from clobbering the full-replace write.)
- `UserMemoriesHandler._runSingleRefinement` (the Phase 4a refinement rewrite inlined the cursor-persist that was formerly the standalone `_persistMemoryEntry` method).

**Non-holders:** plain `getUserMetadata` reads and bare `cache.updateUserMetadata(...)` calls with no preceding read.

**Lock ordering:** `_refineLock` (outer) → `chatUserMetadataLock` (inner) — no reverse path exists (`setUserMetadata` never takes `_refineLock`). A new metadata-RMW site added inside the refinement flow must respect the same ordering.

**Widening correction (2026-07-05):** an earlier version of this note claimed `isUpdate=False` did NOT take the lock — that was superseded when the user widened the lock to wrap both branches. Do not "optimize" the full-replace path back out of the lock.

## Exploration Q2 — sole write path

`CacheService.updateUserMetadata` is the SOLE production write path for `chat_users.metadata`. The repo method `ChatUsersRepository.updateUserMetadata` (`internal/database/repositories/chat_users.py` lines 126-162) has exactly one production caller (the cache). All 6 handler `setUserMetadata(isUpdate=True)` callsites (`spam.py` x4, `message_preprocessor.py` x2) + the 1 `_runSingleRefinement` direct caller route through `cache.updateUserMetadata`. No `_chatUsersLock` existed prior to the metadata RMW fix. The `chat_messages.py:154` raw SQL bypass only touches `messages_count`, not `metadata` — irrelevant to the metadata race.

## Accepted memory-refinement risks (documented alongside, 2026-07-05)

Documented as part of the same review-fix round. These are memory-summarization risks — nothing breaks:

1. `_dtCronJob` subtracts `preCount` from accounting regardless of messages actually ingested by `_runRefinement` (capped at 128).
2. `_runRefinement` cursor advances to `messages[0]` (newest) so bursts > `_memoryMaxMessagesPerRun` (128) permanently skip overflow.

Mitigation: `logger.warning` fires when `len(messages) >= _memoryMaxMessagesPerRun` (overflow detection). Both accepted because it is memory summarization — nothing breaks. For the full refinement-machinery context, see [`user-memory-refinement.md`](user-memory-refinement.md).

## Line-number drift notes

Line numbers drift with edits — verify before relying. Authoritative current locations (as of the 2026-07-05 review):

- `chat_settings.py` is at [`/internal/bot/models/chat_settings.py`](/internal/bot/models/chat_settings.py) (NOT `internal/bot/common/`).
- `setUserMetadata` @ `base.py:1157-1184` (re-verified 2026-07-14; re-locate by symbol if it drifts again).
- `spam.py` `_getUserInfoFreshIfMessagesLessThan` @ **202-243** (not 199-241 as an earlier review reported).
- `chat_messages.py:154` — the raw SQL `messages_count` increment bypass site.

## Tests

- [`/tests/services/cache/test_user_info.py`](/tests/services/cache/test_user_info.py) — cache unit tests.
- [`/tests/bot/common/handlers/test_user_info_cache_regression.py`](/tests/bot/common/handlers/test_user_info_cache_regression.py) — regression: a warm-message produces 0 `chat_users` DB reads/writes.
- [`/tests/bot/common/handlers/test_spam_microopt.py`](/tests/bot/common/handlers/test_spam_microopt.py) — conditional-refresh helper: at-or-above-threshold no-refresh, below-threshold refresh, cold-cache no-refresh, strict-`<` boundary + `markAsSpam` `+1` form.

## Cross-references

- ADR-015 in [`../architecture.md`](../architecture.md) — canonical decision.
- [`../../plans/user-info-cache-plan-v1.md`](../../plans/user-info-cache-plan-v1.md) — plan of record (§16 supersedes §3/§14/§15 for the post-review contract).
- [`user-memory-refinement.md`](user-memory-refinement.md) — companion: nested-write hazard and `chatUserMetadataLock()` as used by the refinement path.
- [`user-memories.md`](user-memories.md) — companion: structured-memory rewrite that still relies on this cache for the message-cursor persist.
- [`../tasks.md`](../tasks.md) §3 — reusable gotchas (`setUserMetadata(isUpdate=True)` shallow-merge hazard, cached `messages_count` staleness).
- [`../services.md`](../services.md) — `chat_users` row cache summary in the services doc.
