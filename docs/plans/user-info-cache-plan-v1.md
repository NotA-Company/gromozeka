# Plan: write-through `chat_users` cache in `CacheService` (v1)

Status: IMPLEMENTED (2026-07-05). See [`docs/llm/architecture.md`](../llm/architecture.md) ADR-015.

## 1. Problem

On every inbound message the bot reads the `chat_users` row for the sender multiple times. Confirmed hot paths (from the call-site map):

- `BaseBotHandler._updateEMessageUserData` (`internal/bot/common/handlers/base.py:380`) — called **per context message** during LLM history reconstruction — calls `getUserMemorySummary` (`base.py:1119`) → `db.chatUsers.getChatUser`.
- `HandlersManager._processMessageRec` (`internal/bot/common/handlers/manager.py:1026`) — calls `getUserMemorySummary` → `getChatUser`.
- `SpamHandler.checkSpam` (`internal/bot/common/handlers/spam.py:253`) — runs on every group-chat message → `getChatUser`.
- `BaseBotHandler.saveChatMessage` (`base.py:1038`) — per-message `updateChatUser` upsert (username/fullName).
- `setUserMetadata(isUpdate=True)` (`base.py:1096`) — internal read inside every metadata write.

With memory-refinements enabled, Gate 2 of the memory-refine feature measured 2–5 redundant `chat_users` reads per inbound message. This plan eliminates that via a write-through cache layer in `CacheService`, mirroring the existing `user_data` cache.

## 2. Non-goals

- Caching aggregate/by-username queries (`getChatUserByUsername`, `getChatUsers`, `getUserChats`, `getAllGroupChats`, `getUserIdByUserName`) — out of scope; these are not single-row PK lookups.
- Keeping `messages_count` accurate in the cache. The column is incremented by a raw SQL `UPDATE` inside `ChatMessagesRepository.saveChatMessage` (`internal/database/repositories/chat_messages.py:154`), bypassing `ChatUsersRepository` entirely. A cached row's `messages_count` therefore drifts. Callers needing an accurate count use the new `refresh=True` parameter (§5). This is an explicit, documented trade-off.

## 3. Storage / cache layer

### 3.1 Reuse `CacheNamespace.CHAT_USERS`

Do **not** add a new namespace. The existing `CHAT_USERS` namespace is keyed `f"{chatId}:{userId}"` (helper `CacheService._getChatUserKey`, `internal/services/cache/service.py:840`) and its value is the TypedDict `HCChatUserCacheDict` (`internal/services/cache/types.py:130`). Today that TypedDict has a single field `data` (the `user_data` table blob). We extend it with a second field `userInfo`, lazily loaded by presence-of-key — the same multi-field-per-entry pattern already used by `HCChatCacheDict` in the `CHATS` namespace. <!-- §14-correction-1: the multi-field precedent is valid, but HCChatCacheDict is NOT total=False; see §14. -->

Extend `HCChatUserCacheDict` (`internal/services/cache/types.py`):

```python
class HCChatUserCacheDict(TypedDict):
    # existing (unchanged):
    data: NotRequired[UserDataType]
    """The user_data key/value blob (backed by the user_data table)."""
    # NEW:
    userInfo: NotRequired[Optional[ChatUserDict]]
    """The chat_users row for this (chatId, userId). None once loaded means the row does not exist."""
```

<!-- §14-correction-1: the v1 body proposed `total=False` + bare `data: UserDataType`; that misrepresents the current state. The real definition is `total=True` (default) with `data: NotRequired[UserDataType]`. Keep that style and add `userInfo` as another `NotRequired` field — functionally equivalent, stylistically consistent with `HCChatCacheDict`. -->

A freshly-created entry can carry either field independently because both are `NotRequired` (mirrors how `data` is lazily set today via `if "data" not in userCache:`). The sentinel for "loaded but absent row" is `userInfo: None`; the sentinel for "not yet loaded" is "key absent". This distinction matters: `getChatUser` must not re-query the DB every tick for a user whose row genuinely doesn't exist.

`ChatUserDict` is imported from `internal/database/models.py:163`.

Persistence: `CHAT_USERS` is `MEMORY_ONLY` (`CacheNamespace.getPersistenceLevel()`, `internal/services/cache/models.py:62-85`), so `persistAll`/`loadFromDatabase` ignore it. Durability for the `userInfo` field comes from explicit write-through inside the new setter methods (same model as `setChatUserData` which writes through to the `user_data` table inline). The `chat_users` table remains the source of truth; the cache is a read-aside/write-through acceleration layer.

### 3.2 New `CacheService` methods

All in `internal/services/cache/service.py`, grouped next to the existing `getChatUserData`/`setChatUserData` family.

```python
async def getChatUser(
    self, chatId: int, userId: int, *, refresh: bool = False
) -> Optional[ChatUserDict]:
    """Return the chat_users row, read-aside from the CHAT_USERS cache.

    On cache miss or refresh=True, falls back to db.chatUsers.getChatUser,
    stores the result (including None) under the cached entry's userInfo key,
    and returns it. refresh=True always re-fetches from DB and overwrites the
    cached value.

    Note: the cached row's messages_count is best-effort stale (incremented by
    a raw SQL UPDATE in ChatMessagesRepository.saveChatMessage, bypassing this
    cache). Pass refresh=True when an accurate count is required.
    """
```

Semantics:
- `userKey = self._getChatUserKey(chatId, userId)`.
- `userCache = self.chatUsers.get(userKey, {})`.
- If `refresh` OR `"userInfo" not in userCache`: fetch `row = await self.database.chatUsers.getChatUser(chatId=chatId, userId=userId)`; set `userCache["userInfo"] = row`; `self.chatUsers.set(userKey, userCache)`; return `row`.
- Else return `userCache["userInfo"]`.
- If `self.database is None`, degrade to `return None` (mirror `getChatUserData`'s no-DB branch).

```python
async def updateChatUser(
    self, chatId: int, userId: int, username: str, fullName: str
) -> None:
    """Write-through upsert of username/fullName with a skip-when-unchanged optimisation.

    If the cached row's username and fullName already equal the supplied values,
    skip the DB upsert entirely (and do not bump updated_at). Otherwise upsert
    via db.chatUsers.updateChatUser and update the cached row in place.

    On cache miss, perform the upsert unconditionally (the row may not exist yet),
    then warm the cache via the DB row.
    """
```

Semantics:
- `userKey = self._getChatUserKey(chatId, userId)`.
- `userCache = self.chatUsers.get(userKey, {})`.
- `cached = userCache.get("userInfo")`.
- If `cached is not None and cached["username"] == username and cached["full_name"] == fullName`: return (no DB call).
- Else: `await self.database.chatUsers.updateChatUser(chatId=chatId, userId=userId, username=username, fullName=fullName)`.
  - If `cached is not None`: mutate cached in place — `cached["username"] = username; cached["full_name"] = fullName; cached["updated_at"] = dbUtils.getCurrentTimestamp()` — and `self.chatUsers.set(userKey, userCache)`.
  - If `cached is None` (miss or row-absent): warm via `row = await self.database.chatUsers.getChatUser(chatId=chatId, userId=userId)`; `userCache["userInfo"] = row`; `self.chatUsers.set(userKey, userCache)`.
- If `self.database is None`: no-op (mirror existing setters' posture).

Note: `dbUtils.getCurrentTimestamp()` is `internal/database/utils.getCurrentTimestamp` (defined at `internal/database/utils.py:377`). `service.py` already imports it as `import internal.database.utils as dbUtils` (`service.py:33`), so no new import is needed in `service.py`; the §10 import list entry for `dbUtils.getCurrentTimestamp` is redundant. The cross-reference to `ChatUsersRepository.updateUserMetadata` is only an idiomatic reference, not a new import path. <!-- §14-correction-2 -->

```python
async def getUserMetadata(self, chatId: int, userId: int) -> UserMetadataDict:
    """Return the parsed metadata dict for (chatId, userId).

    Reads the cached chat_users row (via getChatUser), parses its metadata
    column with stdlib json.loads (empty/None -> {}). Does NOT refresh; for an
    accurate messages_count use getChatUser(refresh=True).
    """
```

Semantics:
- `userInfo = await self.getChatUser(chatId=chatId, userId=userId)`.
- `if userInfo is None: return {}`.
- `metadataStr = userInfo["metadata"]`.
- `return json.loads(metadataStr) if metadataStr else {}`.

This mirrors `BaseBotHandler.parseUserMetadata` (`base.py:1055`); the parsing logic moves to the cache layer so callers consume parsed metadata directly. `BaseBotHandler.parseUserMetadata` stays as a thin pure-parse helper (callers that already hold a `ChatUserDict` keep using it).

```python
async def updateUserMetadata(
    self, chatId: int, userId: int, metadata: UserMetadataDict
) -> None:
    """Write-through replace of the full metadata dict for (chatId, userId).

    Serializes via utils.jsonDumps, calls db.chatUsers.updateUserMetadata, and
    updates the cached row's metadata field. Performs NO merge — callers compose
    their own merge policy by reading getUserMetadata first and mutating.

    CRITICAL for nested sub-dicts (e.g. memoryRefinement): callers must read the
    FULL metadata, mutate the single nested key, and write the FULL metadata
    back. A shallow top-level merge ({**old, **new}) would wipe sibling keys.
    """
```

Semantics:
- `metadataStr = utils.jsonDumps(metadata)`.
- `await self.database.chatUsers.updateUserMetadata(chatId=chatId, userId=userId, metadata=metadataStr)`.
- Warm/refresh the cached row so the metadata field is current: `userInfo = await self.getChatUser(chatId=chatId, userId=userId, refresh=True)`; (the refresh re-reads the row we just wrote, so the cache reflects the serialized-then-stored value).
- If `self.database is None`: no-op.

```python
def invalidateChatUser(self, chatId: int, userId: int) -> None:
    """Drop the cached chat_users row for (chatId, userId).

    Escape hatch for callers that know the row was mutated out-of-band (none
    today, but provided for safety and future use). The next getChatUser
    re-fetches from DB.
    """
```

Semantics: `self.chatUsers.pop(self._getChatUserKey(chatId, userId), None)`. Synchronous (no DB).

### 3.3 Write-through ordering

All setters write the DB first and update the cache only on success. If `db.chatUsers.updateChatUser`/`updateUserMetadata` raises, the cache is left untouched — no cache-DB divergence. (The repository methods return bool but do not raise on "row absent"; they do raise on genuine DB errors, which we let propagate.)

## 4. Call sites to refactor

After Phase 1, route these through `self.cache.*`. The map is exhaustive (production code under `internal/`).

### 4.1 `getChatUser` call sites

| File:line | Context | New call |
|---|---|---|
| `internal/bot/common/handlers/base.py:1096` | `setUserMetadata(isUpdate=True)` merge-read | replaced by `cache.getUserMetadata` (see 4.3) |
| `internal/bot/common/handlers/base.py:1119` | `getUserMemorySummary` | `cache.getUserMetadata` then read `memoryRefinement[str(threadId)]` |
| `internal/bot/common/handlers/base.py:1244` | `getUserChats` command | `cache.getChatUser` |
| `internal/bot/common/handlers/spam.py:253` | `checkSpam` (hot path) | `cache.getChatUser` |
| `internal/bot/common/handlers/spam.py:518` | `markAsSpam` | `cache.getChatUser` |
| `internal/bot/common/handlers/spam.py:992` | not-spam callback | `cache.getChatUser` |
| `internal/bot/common/handlers/spam.py:1596` | `/unban` | `cache.getChatUser` |
| `internal/bot/common/handlers/spam.py:1714` | `/mark_for_delete` | `cache.getChatUser` |
| `internal/bot/common/handlers/user_data.py:444` | `_readMemoryEntry` | `cache.getUserMetadata` |
| `internal/bot/common/handlers/user_data.py:577` | `_persistMemoryEntry` read | `cache.getUserMetadata` |

### 4.2 `updateChatUser` call sites

| File:line | Context | New call |
|---|---|---|
| `internal/bot/common/handlers/base.py:902` | `updateChatInfo` admin refresh (throttled 12h) | `cache.updateChatUser` |
| `internal/bot/common/handlers/base.py:1038` | `saveChatMessage` (hot path) | `cache.updateChatUser` |
| `internal/bot/common/handlers/message_preprocessor.py:169` | `newChatMemberHandler` | `cache.updateChatUser` |
| `internal/bot/common/handlers/message_preprocessor.py:217` | `leftChatMemberHandler` | `cache.updateChatUser` |

### 4.3 `updateUserMetadata` / `setUserMetadata` call sites

| File:line | Context | New call |
|---|---|---|
| `internal/bot/common/handlers/base.py:1100` | inside `setUserMetadata` | `cache.updateUserMetadata` (full dict after shallow merge) |
| `internal/bot/common/handlers/user_data.py:586` | `_persistMemoryEntry` write | `cache.updateUserMetadata` (full dict after nested mutate) |

`setUserMetadata(isUpdate=True)` (`base.py:1073-1090`) refactors to:
```python
async def setUserMetadata(self, chatId, userId, metadata, isUpdate=False):
    if isUpdate:
        existing = await self.cache.getUserMetadata(chatId=chatId, userId=userId)
        metadata = {**existing, **metadata}   # shallow top-level merge — caller's intent
    await self.cache.updateUserMetadata(chatId=chatId, userId=userId, metadata=metadata)
```

`_persistMemoryEntry` (`user_data.py:551-586`) <!-- §14-correction-3: v1 body cited 495-531, which is inside _runRefinement; see §13 drift list. --> refactors to read `metadata = await self.cache.getUserMetadata(...)`, mutate `metadata.setdefault("memoryRefinement", {})[str(threadId)] = entry`, then `await self.cache.updateUserMetadata(...)`. The nested-mutation logic is unchanged — only the read/write targets move from DB to cache. The CRITICAL docstring about shallow-merge stays.

### 4.4 `getUserMemorySummary` refactor (`base.py:1102`)

```python
async def getUserMemorySummary(self, chatId, userId, threadId) -> Optional[str]:
    metadata = await self.cache.getUserMetadata(chatId=chatId, userId=userId)
    refinement = metadata.get("memoryRefinement", {})
    entry = refinement.get(str(threadId))
    return (entry or {}).get("summary") or None
```

The per-chat `MEMORY_REFINEMENT_ENABLED` gate stays at the call sites (`base.py:380`, `manager.py:1026`) — unchanged.

### 4.5 Unchanged

`getChatUserByUsername`, `getChatUsers`, `getUserChats` (aggregate), `getAllGroupChats`, `getUserIdByUserName` — aggregate/by-alternate-key queries, out of scope.

## 5. `messages_count` staleness

Cached `messages_count` drifts (incremented by raw SQL in `chat_messages.py:154`, never routed through this cache). Audit consumers of `ChatUserDict["messages_count"]`:

- The aggregate `getChatUsers(minMessages=...)` is a separate query — not affected.
- Direct reads of a single row's `messages_count` field (grep `["messages_count"]` and `.messages_count`) — route those through `getChatUser(refresh=True)` if accuracy matters. **At least one hot-path correctness-critical reader exists today: `spam.py:275` reads `userInfo["messages_count"]` inside `checkSpam` and compares it against the `AUTO_SPAM_MAX_MESSAGES` threshold at `spam.py:277`. See §14-risk-1 — the v1 body's "likely few or none in the hot path" estimate is wrong.** Document each reader in §13.

The cache method docstrings (§3.2) call this out explicitly. ADR (§11) records the trade-off.

## 6. Hard invariants

- **Write-through ordering**: DB write first, cache update only on success.
- **Nested-write safety**: `_persistMemoryEntry` keeps its explicit full-read + nested-mutate + full-write pattern. The cache provides dumb read/write primitives (option i); it performs NO merge. The shallow-merge hazard lives only in `setUserMetadata(isUpdate=True)` where it is the caller's explicit intent.
- **Lazy field independence**: a cached entry may have `data` loaded without `userInfo`, or vice versa. Presence-of-key is the "loaded" sentinel; `userInfo: None` means "loaded, row absent".
- **`updated_at` semantics shift**: the skip-when-unchanged optimisation means `updated_at` no longer refreshes on a no-op `updateChatUser`. Accepted trade-off; documented.
- **No new namespace**: extend `CHAT_USERS`, do not add a namespace.

## 7. Phase breakdown

1. **Phase 1 — CacheService additions.** Extend `HCChatUserCacheDict` (`types.py`); add `getChatUser`, `updateChatUser`, `getUserMetadata`, `updateUserMetadata`, `invalidateChatUser` to `service.py`; import `ChatUserDict`, `UserMetadataDict`, `json`, `utils.jsonDumps`, `dbUtils.getCurrentTimestamp` as needed. Cache unit tests (warm/cold/refresh, skip-unchanged, write-through ordering, metadata round-trip, nested-write safety).
2. **Phase 2 — `base.py` helpers.** Refactor `setUserMetadata`, `getUserMemorySummary`, `getUserChats`'s `getChatUser`, `updateChatInfo`'s + `saveChatMessage`'s `updateChatUser` to route through `self.cache`. Keep `parseUserMetadata` as a pure helper.
3. **Phase 3 — remaining call sites.** `spam.py` (5 `getChatUser` reads; its `setUserMetadata` calls go via the refactored base helper automatically), `message_preprocessor.py` (2 `updateChatUser` + 2 `setUserMetadata` via helper), `user_data.py` (`_readMemoryEntry`, `_persistMemoryEntry`).
4. **Phase 4 — `messages_count` audit.** Grep direct `messages_count` readers; apply `refresh=True` where accuracy matters; document.
5. **Phase 5 — Tests.** Cache unit tests (phase 1) + a regression test asserting one inbound message from a warm `(chat, user)` produces zero `chat_users` DB reads (mock the repository, count calls) + update existing handler tests that stub `db.chatUsers` to instead stub `cache.*`.
6. **Phase 6 — Docs.** ADR in `docs/llm/architecture.md`; cache-service section in `docs/llm/services.md`; memory-refinement memory file (`docs/llm/memories/user-memory-refinement.md`) updated to note the cache; `docs/llm/tasks.md` gotcha about `messages_count` staleness + the `refresh=True` escape hatch.

## 8. Risks

- **Cache-DB divergence on write failure**: mitigated by DB-first ordering (§3.3).
- **Stale `messages_count`**: accepted; `refresh=True` escape hatch (§5).
- **Cold-path cost**: first message per `(chat, user)` per process still hits DB (upsert + warm). Warm path is zero-DB. Acceptable.
- **`invalidateChatUser` misuse**: provided but has no callers today; future use must be justified.
- **Test churn**: existing handler tests that mock `db.chatUsers.getChatUser`/`updateUserMetadata`/`updateChatUser` need rewiring to mock the cache layer instead. Phase 5 covers this.

## 9. Test strategy

- **Cache unit tests** (`tests/services/cache/test_user_info.py` or extension of an existing cache test): warm hit returns cached; cold miss fetches DB and populates; `refresh=True` re-fetches; `updateChatUser` skips DB when unchanged; `updateChatUser` writes DB + updates cache when changed; `updateChatUser` cold path upserts + warms; `getUserMetadata` parses empty/None/valid; `updateUserMetadata` writes through + refreshes cache; `invalidateChatUser` drops the entry; nested-write safety (a `setUserMetadata`-style shallow merge and a `_persistMemoryEntry`-style nested mutate coexist without wiping each other).
- **Regression**: a handler-level test that sends one message through a warm cache and asserts `mockRepo.getChatUser.call_count == 0` and `mockRepo.updateChatUser.call_count == 0` (skip-unchanged).
- **Existing tests**: any test that asserts on `db.chatUsers.*` call counts/args gets updated to the cache equivalent.

## 10. File-by-file change map

| File | Change |
|---|---|
| `internal/services/cache/types.py` | Add `userInfo: Optional[ChatUserDict]` to `HCChatUserCacheDict`; import `ChatUserDict`. |
| `internal/services/cache/service.py` | Add 5 methods (§3.2); import `ChatUserDict`, `UserMetadataDict`, `utils.jsonDumps`, `dbUtils.getCurrentTimestamp`, `json`. |
| `internal/bot/common/handlers/base.py` | Refactor `setUserMetadata`, `getUserMemorySummary`, `getUserChats` (line 1244 read), `updateChatInfo` (902) + `saveChatMessage` (1038) upserts to route via `self.cache`. `parseUserMetadata` unchanged. |
| `internal/bot/common/handlers/spam.py` | 5 `getChatUser` reads → `self.cache.getChatUser`. |
| `internal/bot/common/handlers/message_preprocessor.py` | 2 `updateChatUser` → `self.cache.updateChatUser`. |
| `internal/bot/common/handlers/user_data.py` | `_readMemoryEntry` + `_persistMemoryEntry` read/write via `self.cache`. |
| Tests | Cache unit tests + regression + rewired handler tests. |
| Docs | ADR + services.md + memory file + tasks.md gotcha. |

## 11. ADR (to land in `docs/llm/architecture.md`)

**ADR-015: write-through `chat_users` cache.** Decision: extend `CacheNamespace.CHAT_USERS` with a lazily-loaded `userInfo` field holding the `chat_users` row; route all single-row `(chatId, userId)` reads and username/fullName/metadata writes through `CacheService`; accept stale `messages_count` with a `refresh=True` escape hatch. Rationale: eliminates 2–5 redundant `chat_users` reads per inbound message; mirrors the established `user_data` cache pattern; keeps the cache dumb (no merge logic) and the nested-write safety in the caller.

## 12. Open questions for architect review

- Is `dbUtils.getCurrentTimestamp()` the right timestamp source for the in-place `updateChatUser` cache mutation, or should we reuse the value the repo writes (it currently computes its own inside `updateUserMetadata`)? Minor consistency question.
- Should `invalidateChatUser` be async for API symmetry even though it's a pure in-memory op? Lean sync (matches `pop`).
- Confirm no production code reads `ChatUserDict["messages_count"]` from a single-row lookup in a correctness-critical way (Phase 4 audit will verify).

## 13. Path verification

Spot-checked every cited `file:line` ref against source on 2026-07-05.

**Verified exact (no drift):**

- `internal/bot/common/handlers/base.py:380` — `_updateEMessageUserData` → `getUserMemorySummary` call ✓
- `internal/bot/common/handlers/base.py:902` — `updateChatInfo` admin-refresh `updateChatUser` (12h throttle) ✓
- `internal/bot/common/handlers/base.py:1038` — `saveChatMessage` `updateChatUser` ✓
- `internal/bot/common/handlers/base.py:1096` — `setUserMetadata(isUpdate=True)` `getChatUser` read ✓
- `internal/bot/common/handlers/base.py:1100` — `setUserMetadata` → `updateUserMetadata` ✓
- `internal/bot/common/handlers/base.py:1102` — `getUserMemorySummary` def ✓
- `internal/bot/common/handlers/base.py:1119` — `getUserMemorySummary` `getChatUser` ✓
- `internal/bot/common/handlers/base.py:1244` — `getUserChats` `getChatUser` ✓
- `internal/bot/common/handlers/manager.py:1026` — `_processMessageRec` → `getUserMemorySummary` ✓
- `internal/bot/common/handlers/spam.py:253` — `checkSpam` `getChatUser` ✓
- `internal/bot/common/handlers/spam.py:518` — `markAsSpam` `getChatUser` ✓
- `internal/bot/common/handlers/spam.py:992` — not-spam callback `getChatUser` ✓
- `internal/bot/common/handlers/spam.py:1596` — `/unban` `getChatUser` ✓
- `internal/bot/common/handlers/spam.py:1714` — `/mark_for_delete` `getChatUser` ✓
- `internal/bot/common/handlers/user_data.py:444` — `_readMemoryEntry` `getChatUser` ✓
- `internal/bot/common/handlers/user_data.py:577` — `_persistMemoryEntry` read `getChatUser` ✓
- `internal/bot/common/handlers/user_data.py:586` — `_persistMemoryEntry` write `updateUserMetadata` ✓
- `internal/bot/common/handlers/message_preprocessor.py:169` — `newChatMemberHandler` `updateChatUser` ✓
- `internal/bot/common/handlers/message_preprocessor.py:217` — `leftChatMemberHandler` `updateChatUser` ✓
- `internal/database/repositories/chat_messages.py:154` — raw SQL `messages_count + 1` ✓
- `internal/services/cache/service.py:840` — `_getChatUserKey` ✓
- `internal/services/cache/types.py:130` — `HCChatUserCacheDict` ✓
- `internal/database/models.py:163` — `ChatUserDict` ✓
- `internal/services/cache/models.py:62-85` — `CacheNamespace.getPersistenceLevel` ✓

**Drift found (line numbers only; plan substance unaffected):**

1. **`base.py:1055`** (cited for `parseUserMetadata`) — actual `def parseUserMetadata` is at **`base.py:1065`** (≈ +10). Line 1055 is the `rootMessageId=rootMessageId,` arg inside `saveChatMessage`. Appears in §3.2 `getUserMetadata` note.
2. **`base.py:1073-1090`** (cited for the `setUserMetadata` body) — actual `async def setUserMetadata` is at **`base.py:1083`**, body spans **1083-1100** (≈ +10). Appears in §4.3 prose.
3. **`user_data.py:495-531`** (cited for `_persistMemoryEntry`) — actual `async def _persistMemoryEntry` is at **`user_data.py:551`**, body spans **551-586**. Lines 495-531 are inside `_runRefinement` (the LLM-generation block), **not** `_persistMemoryEntry`. Appears in §4.3 prose. (The per-line refs `user_data.py:577` and `:586` inside that function are correct — see verified list above.)

No substantive disagreement between the plan's descriptions and the code; all cited call sites exist and match the stated context. Only the three line/range numbers above should be corrected when the plan is next edited.

## 14. Architect review corrections

Verified against source on 2026-07-05. Corrections are grouped: (A) materially wrong claims fixed inline above and summarised here, (B) confirmations of claims the architect was asked to check explicitly, (C) opinions on the three §12 open questions, (D) newly-flagged risks the v1 body misses.

### 14.A Material corrections (already applied inline above)

#### 14.A.1 `HCChatUserCacheDict` is `total=True` with `NotRequired`, NOT `total=False`

The v1 body (§3.1) presented the proposed snippet as `class HCChatUserCacheDict(TypedDict, total=False):` with a bare `data: UserDataType` field, and described `total=False` as if it were the existing state ("Today that TypedDict has a single field `data` ... `total=False` so a freshly-created entry can carry either field independently").

Source (`internal/services/cache/types.py:130-143`):

```python
class HCChatUserCacheDict(TypedDict):
    data: NotRequired[UserDataType]
```

The real shape is `total=True` (the default) with `data: NotRequired[UserDataType]`. The plan's `total=False` rewrite is a **style change**, not the existing state. `total=False` and per-field `NotRequired` are functionally equivalent (both make every key optional), but the codebase consistently uses the `NotRequired` style: `HCChatCacheDict` (`types.py:85-110`) — cited by the plan as the multi-field precedent — is itself `total=True` with five `NotRequired` fields (`settings`, `cachedSettings`, `info`, `topicInfo`, `admins`). The precedent claim ("multi-field-per-entry pattern already used by `HCChatCacheDict`") is **correct in substance** (that TypedDict genuinely has multiple fields), but it is **not** precedent for `total=False` — it is precedent for `total=True` + `NotRequired`.

Correction applied: keep `total=True`, add `userInfo: NotRequired[Optional[ChatUserDict]]`. This is consistent with `HCChatCacheDict`, requires no behavioural change, and `Optional` is already imported in `types.py` (`types.py:17`). `ChatUserDict` needs adding to the existing `from internal.database.models import ...` line in `types.py` (`types.py:19`).

#### 14.A.2 `dbUtils.getCurrentTimestamp` is already imported in `service.py`

§3.2's note ("import it the same way `ChatUsersRepository.updateUserMetadata` does") and §10's import list entry imply a new import. Source: `service.py:33` already has `import internal.database.utils as dbUtils`. `ChatUsersRepository` imports it as `from .. import utils as dbUtils` (`chat_users.py:18`) — different aliasing, same module. No new import is needed in `service.py`; the §10 import-list entries for `dbUtils.getCurrentTimestamp`, `utils.jsonDumps`, and `json` are also redundant (`service.py:26` imports `json`, `service.py:38` imports `from lib import utils`). The only genuinely new import is `ChatUserDict` (and `UserMetadataDict` if not already present).

#### 14.A.3 `_persistMemoryEntry` line range was wrong in the §4.3 prose

Already recorded in the §13 drift list but still present in the §4.3 body. Actual: `user_data.py:551-586`. Lines 495-531 are inside `_runRefinement`. Inline marker added.

#### 14.A.4 `messages_count` hot-path reader exists; v1 estimate was wrong

§5's "Likely few or none in the hot path" and §12's third open question ("Confirm no production code reads `ChatUserDict["messages_count"]` ... in a correctness-critical way") are both answered **negatively** by `internal/bot/common/handlers/spam.py:275`:

```python
userMessages = userInfo["messages_count"]
maxCheckMessages = chatSettings[ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES].toInt()
if not userMetadata.get("isSpammer", False) and maxCheckMessages != 0 and userMessages >= maxCheckMessages:
```

`checkSpam` runs on every group-chat message (the plan itself flags `spam.py:253` as a hot path in §1). The `messages_count` comparison gates the spam heuristic. Once `spam.py:253` is routed through `cache.getChatUser` (§4.1), the count it reads will be stale by however many messages the user has sent since cache load (the increment at `chat_messages.py:154` bypasses the cache). This is a **behavioural regression risk**, not just a documented trade-off. Mitigation options: (a) route `spam.py:253` through `cache.getChatUser(refresh=True)` (defeats the cache for the hottest path — net negative), (b) have `ChatMessagesRepository.saveChatMessage` call `cache.invalidateChatUser(chatId, userId)` (or a new `bumpMessagesCount` cache hook) after the raw increment so the next read re-fetches, (c) accept the staleness and lower `AUTO_SPAM_MAX_MESSAGES`'s effective semantics to "approximate threshold". The architect recommends (b): the increment already happens inside `saveChatMessage`, which is called from `BaseBotHandler.saveChatMessage` (`base.py:1038` region) — that handler holds a `self.cache` reference and can invalidate the row in the same `await` block. This preserves the cache for read-heavy paths (memory summary, metadata) while keeping `messages_count` correct for the spam gate. The plan must pick one before Phase 4.

### 14.B Explicit confirmations (architect was asked to verify)

| Claim | Source | Verdict |
|---|---|---|
| `CHAT_USERS` value type is `HCChatUserCacheDict` with a single `data` field | `types.py:130-143` | ✓ (single `data: NotRequired[UserDataType]` field) |
| Adding `userInfo: Optional[ChatUserDict]` is consistent with the namespace's value type | `types.py:130`, `models.py:163` | ✓ (TypedDict extension; `ChatUserDict` is a plain `TypedDict`) |
| `getChatUserData`/`setChatUserData` use the LRU-lookup + DB-fallback-on-miss + dirty-tracking + write-through pattern the plan mirrors | `service.py:855-933` | ✓ exact match (`userCache = self.chatUsers.get(userKey, {})`; `if "data" not in userCache:` DB fallback; `self.chatUsers.set(userKey, userCache)`; inline DB write inside setter) |
| `_getChatUserKey(chatId, userId) -> str` returns `f"{chatId}:{userId}"` | `service.py:840-853` | ✓ |
| `CHAT_USERS` resolves to `MEMORY_ONLY` via `getPersistenceLevel()` | `models.py:81-85` (the `case _:` arm) | ✓ |
| `dbUtils.getCurrentTimestamp` is importable cleanly from `service.py` (no circular import) | `service.py:33` (already imported); `utils.py:377` (definition) | ✓ already imported |
| `setUserMetadata(isUpdate=True)` does a shallow top-level merge `{**old, **new}` | `base.py:1097`: `metadata = {**self.parseUserMetadata(userInfo), **metadata}` | ✓ |
| `_persistMemoryEntry` does an explicit full-read + nested-mutate + full-write; the refactor preserves that invariant | `user_data.py:577-586` | ✓ the proposed `metadata.setdefault("memoryRefinement", {})[str(threadId)] = entry` is functionally equivalent to the current `get` + reassign pattern |
| `chat_messages.py:154` is the only writer to `messages_count` and bypasses `ChatUsersRepository` | `chat_messages.py:154-164` (raw `UPDATE chat_users SET messages_count = messages_count + 1`) | ✓ only writer; also bumps `updated_at` independently (line 158) — note this already double-writes `updated_at` relative to the `updateChatUser` call at `base.py:1038` |
| `ChatUsersRepository.updateChatUser` does NOT touch `metadata` or `messages_count` on conflict (only `username`, `full_name`, `updated_at`) | `chat_users.py:48-91` (`updateExpressions` dict at lines 82-86) | ✓ |
| `ChatUsersRepository.updateUserMetadata` only writes `metadata` + `updated_at` | `chat_users.py:126-162` | ✓ (does not touch `messages_count`, `username`, `full_name`) |
| `ChatUserDict` lives at `internal/database/models.py:163` | `models.py:163-186` | ✓ |
| `HCChatCacheDict` has multiple fields (precedent for multi-field-per-entry) | `types.py:85-110` (5 fields) | ✓ in substance; but it is `total=True` + `NotRequired`, NOT `total=False` (see §14.A.1) |
| `setChatUserData` marks `self.dirtyKeys[CacheNamespace.CHAT_USERS]` dirty | `service.py:925` | ✓ |
| `CHAT_USERS` dirty set is never flushed (because `MEMORY_ONLY`) | `service.py:1176-1200` (`persistAll` skips `MEMORY_ONLY` namespaces at lines 1179-1181 and clears their dirty set without persisting) | ✓ |
| `loadFromDatabase` does not load `CHAT_USERS` (because nothing is ever persisted for it) | `service.py:1204-1259` (loads only from `cache_storage` table, which `persistAll` never writes for `MEMORY_ONLY` namespaces) | ✓ |

### 14.C Opinions on the §12 open questions

1. **Timestamp source for the in-place `updateChatUser` cache mutation (§12 q1).** Use `dbUtils.getCurrentTimestamp()` — the same function the repository uses (`chat_users.py:78`, `chat_users.py:156`). This guarantees the cached `updated_at` and the DB `updated_at` are drawn from the same clock source, so a subsequent cache-vs-DB diff (e.g. in tests or in a future consistency check) won't flap. Do **not** try to reuse "the value the repo writes": the repo computes the timestamp internally inside `upsert(...)`/`execute(...)` and does not return it, so the only way to read it back is the redundant `getChatUser(refresh=True)` round-trip the plan already uses for `updateUserMetadata` (see §14.D.2 — don't add a second such round-trip here). Compute `dbUtils.getCurrentTimestamp()` once in `updateChatUser` and mutate the cached row in place. Minor consistency note closed.

2. **Sync vs async `invalidateChatUser` (§12 q2).** Keep it **synchronous**. Reasoning: (a) it is a pure `OrderedDict.pop` (`self.chatUsers.pop(...)`), no `await` needed; (b) making it `async` would force every caller to `await` a no-IO operation, adding friction without benefit; (c) the existing cache API already mixes sync and async methods by the same criterion — `getUserState`/`setUserState` are sync (`service.py:1007`, `service.py:1027`), `getChatUserData`/`setChatUserData` are async. The deciding line is "does this touch the DB or another awaitable?" If no, sync. Match `setUserState`. The architect disagrees with the "API symmetry" argument in §12 — symmetry across the sync/async boundary is worse than honest per-method typing.

3. **`messages_count` correctness-critical readers (§12 q3).** Answered under §14.A.4: at least one exists (`spam.py:275`). Phase 4 cannot just "document" it; it must pick a mitigation. Recommend the invalidation-hook approach (§14.A.4 option b).

### 14.D Newly-flagged risks the v1 body misses

#### 14.D.1 Aliasing: `getChatUser` returns the SAME `ChatUserDict` reference the cache holds

The plan's `getChatUser` returns `userCache["userInfo"]` directly (same object the LRU holds). This mirrors `getChatUserData`, which returns `userCache.get("data", {})` — also the live reference. Two consequences:

- **Caller mutation corrupts the cache.** If any caller does `userInfo["username"] = ...` or `userInfo["metadata"] = ...` on the returned dict, it mutates the cached row out from under the write-through layer, producing silent cache-DB divergence. A grep of the call sites in §4.1 shows the current callers only **read** the returned dict (`spam.py:275` reads `["messages_count"]`; `base.py:1097` reads `["metadata"]` via `parseUserMetadata`; `getUserMemorySummary` reads `["metadata"]`; `getUserChats` reads `["chat_id"]`/`["user_id"]`/`["metadata"]`). So no current caller mutates — but the API offers no protection, and a future caller (or a careless refactor of `spam.py:257-267`, which today constructs a **local** synthetic dict and would now receive a cached one) could introduce the bug silently.
- **Concurrent reads during an in-place mutation.** `updateChatUser`'s in-place mutation path (`cached["username"] = username; ...`) mutates the same object other tasks may be reading. In CPython this is data-race-safe at the bytecode level for dict item assignment, but a reader doing `for k, v in userInfo.items():` concurrently could observe a half-updated row. Low probability (the bot is single-process async, no `asyncio.to_thread` on these paths), but worth a docstring note.

Recommendation: `getChatUser` should return a **shallow copy** of the cached `ChatUserDict` (`dict(cached)` or `cached.copy()`). `ChatUserDict` is a flat TypedDict of scalars + a `metadata` JSON string, so a shallow copy is sufficient — no nested aliasing. The cost (one dict allocation per read) is negligible compared to the DB call it eliminates, and it converts a footgun into a contract. If the team prefers zero-copy for the hot path, alternative is to return the live reference but document " callers MUST NOT mutate the returned dict" in the docstring and add an assertion in tests. The architect recommends the copy.

Note: `getUserMetadata` is unaffected — it returns a freshly-parsed dict from `json.loads`, so callers can freely mutate it. The aliasing risk is specific to `getChatUser`.

#### 14.D.2 `updateUserMetadata`'s `refresh=True` re-read is a redundant DB round-trip

§3.2's `updateUserMetadata` semantics end with:

> Warm/refresh the cached row so the metadata field is current: `userInfo = await self.getChatUser(chatId=chatId, userId=userId, refresh=True)`; (the refresh re-reads the row we just wrote, so the cache reflects the serialized-then-stored value).

The plan already has everything needed to update the cache without re-reading:

```python
metadataStr = utils.jsonDumps(metadata)
await self.database.chatUsers.updateUserMetadata(chatId=chatId, userId=userId, metadata=metadataStr)
# in-place warm, no DB round-trip:
userCache = self.chatUsers.get(self._getChatUserKey(chatId, userId), {})
cached = userCache.get("userInfo")
if cached is not None:
    cached["metadata"] = metadataStr
    cached["updated_at"] = dbUtils.getCurrentTimestamp()
    self.chatUsers.set(self._getChatUserKey(chatId, userId), userCache)
else:
    # cold cache: store the metadata string under a partial row so a later
    # getChatUser hit doesn't re-query. This is optional — see note below.
    ...
```

This avoids one `SELECT * FROM chat_users` per metadata write. In the memory-refinement loop (`_persistMemoryEntry`), metadata writes happen per refined thread per user — eliminating the redundant SELECT is a measurable win on the exact workload this plan exists to optimise.

The "the refresh re-reads the row we just wrote, so the cache reflects the serialized-then-stored value" justification is weak: `utils.jsonDumps` is deterministic, so `metadataStr` is exactly what landed in the DB. There is no transformation the DB applies that the application doesn't already know about. The only field that could differ is `updated_at`, and §14.C q1 already established we should compute that with `dbUtils.getCurrentTimestamp()` in the same call.

Edge case to decide: on a **cold cache** (`userInfo` not yet loaded), should `updateUserMetadata` write a partial row (`{"metadata": metadataStr, "updated_at": ts, ...}` with other fields absent) into the cache? The architect recommends **no** — drop the cache entry (`invalidateChatUser`) on a cold write, so the next `getChatUser` does a clean full-row load. A partial row would violate the `ChatUserDict` TypedDict contract (every field is required) and surprise the next reader. This is the same posture `setChatUserData` takes today: it doesn't fabricate a `userInfo`, it only manages `data`.

#### 14.D.3 `updateChatUser`'s cold-path "warm via getChatUser" re-reads immediately after the upsert

Same shape as §14.D.2, smaller impact. §3.2's `updateChatUser` semantics for the `cached is None` branch say:

> If `cached is None` (miss or row-absent): warm via `row = await self.database.chatUsers.getChatUser(...)`; `userCache["userInfo"] = row`; ...

The upsert at `chat_users.py:48-91` does not return the row, so a re-read is needed to warm the cache with the canonical post-upsert values (including `messages_count`, `created_at`, `timezone`, `metadata`, which the upsert did not all set). This re-read is **justified** for `updateChatUser` (unlike `updateUserMetadata`) because the caller doesn't have a fully-formed row in hand. Accept it, but note it means the cold path costs `1 upsert + 1 select` per first-message-per-(chat,user)-per-process — exactly what §8 "Cold-path cost" already documents. No change needed; flagging only so reviewers don't conflate this with §14.D.2.

#### 14.D.4 `setUserMetadata(isUpdate=True)` shallow merge now reads stale cache

After the §4.3 refactor, `setUserMetadata(isUpdate=True)` becomes:

```python
existing = await self.cache.getUserMetadata(chatId=chatId, userId=userId)
metadata = {**existing, **metadata}
await self.cache.updateUserMetadata(...)
```

`getUserMetadata` reads from the cached row. If the cache was loaded long ago, `existing` may be missing keys that a concurrent (or in-process sequential) `_persistMemoryEntry` write added — but `_persistMemoryEntry` now also writes through `cache.updateUserMetadata`, so the cache is current. The only divergence source is the `messages_count` increment (which doesn't touch `metadata`) and out-of-band DB edits (none today). Conclusion: the refactor is **safe** under the current write-through invariant, but it creates a new implicit coupling — `setUserMetadata`'s correctness now depends on **every** metadata writer routing through the cache. If a future contributor adds a raw `db.chatUsers.updateUserMetadata(...)` call that bypasses the cache (the way `chat_messages.py:154` bypasses it for `messages_count`), `setUserMetadata(isUpdate=True)` will silently merge against stale data and clobber the bypass-writer's keys.

Mitigation: the regression test in §9 should add a case — "raw DB write to `metadata` between cache load and `setUserMetadata(isUpdate=True)` is not reflected" — to document the trade-off explicitly. The architect does not consider this a blocker (no such bypass exists today), but it should be a docstring note on `setUserMetadata` and a row in §8 Risks.

#### 14.D.5 `dirtyKeys` for `CHAT_USERS` — conclusion the plan asked for

The plan asks (in the review brief, not in §12): should `updateChatUser`/`updateUserMetadata` also touch `self.dirtyKeys[CacheNamespace.CHAT_USERS]`, the way `setChatUserData` does at `service.py:925`?

**No.** Verified: `persistAll` (`service.py:1176-1200`) skips every `MEMORY_ONLY` namespace at lines 1179-1181 (`if persistenceLevel == CachePersistenceLevel.MEMORY_ONLY: self.dirtyKeys[namespace].clear(); continue`). The dirty set for `CHAT_USERS` is never read by anyone — `setChatUserData`'s `self.dirtyKeys[CacheNamespace.CHAT_USERS].add(userKey)` at line 925 is dead work (harmless but pointless; it just grows a set that gets cleared on the next `persistAll` without ever being iterated). The new methods should not copy this pattern; adding to `dirtyKeys` for a `MEMORY_ONLY` namespace is misleading because it implies the entry will be persisted, when it will not. Recommendation: the new methods leave `dirtyKeys` untouched. (A separate cleanup PR could remove the dead `setChatUserData` line, but that is out of scope for this plan.)

#### 14.D.6 No `loadFromDatabase` interaction (confirming the architect's question)

Confirmed: `loadFromDatabase` (`service.py:1204-1259`) reads only from the `cache_storage` DB table, which is written exclusively by `persistAll`. Since `persistAll` skips `MEMORY_ONLY` namespaces, nothing is ever stored for `CHAT_USERS`, and `loadFromDatabase` therefore loads nothing for it on startup. The new `userInfo` field inherits this: cold cache at startup, warmed lazily on first `getChatUser`. No `loadFromDatabase` change needed. §3.1's claim ("`persistAll`/`loadFromDatabase` ignore it") is correct.

### 14.E Verification of this review

No code was modified. `make format lint` was not run because the only edits are to a Markdown document under `docs/plans/`, which is excluded from flake8/isort/pyright (the lint pipeline only touches `*.py`). The repo's lint config does not lint Markdown. If the team wants a sanity check that no Python was accidentally touched, `git diff --stat` should show exactly one file: `docs/plans/user-info-cache-plan-v1.md`.

### 14.F Summary of corrections applied to the v1 body

1. §3.1 TypedDict snippet: rewritten from `total=False` + bare `data` to `total=True` + `NotRequired[...]` for both fields (matches the actual current state and the `HCChatCacheDict` precedent). Inline marker `§14-correction-1`.
2. §3.1 prose: replaced the `total=False` justification with a `NotRequired` justification. Inline marker `§14-correction-1`.
3. §3.2 `updateChatUser` note on `dbUtils.getCurrentTimestamp`: clarified that no new import is needed (`service.py:33` already imports it). Inline marker `§14-correction-2`.
4. §4.3 `_persistMemoryEntry` line range: `495-531` → `551-586` in prose. Inline marker `§14-correction-3`.
5. §5 `messages_count` reader estimate: "Likely few or none in the hot path" → flagged `spam.py:275` as a concrete hot-path correctness-critical reader. Inline marker added pointing to §14.A.4.

No other body changes. §1-§13 otherwise verified accurate (the §13 drift list is complete and correct).

## 15. Resolved decisions

Locked in ahead of Phase 1 implementation. One line each.

- **A = (b)**: `messages_count` staleness for the `spam.py:275` hot-path reader is
  mitigated by wiring `refresh=True` at that read site in Phase 4 (the cache stays
  warm for the read-heavy paths; only the spam gate re-fetches). The
  cached-then-re-fetch-if-below-threshold micro-optimisation is postponed to a
  future task. (See §14.A.4 option b discussion.)
- **B = defensive copy**: `getChatUser` returns `dict(cachedRow)` (shallow copy),
  so callers cannot mutate the cached row. (See §14.D.1.)

Refinements adopted from the architect review (§14.C / §14.D):

- **In-place `updateUserMetadata`**: the cached row's `metadata` + `updated_at`
  are mutated in place (computed via `dbUtils.getCurrentTimestamp()`); no
  `refresh=True` DB round-trip. On cold `userInfo`, the cache is left cold — the
  next `getChatUser` lazy-loads the fresh row. No partial `ChatUserDict` is
  fabricated. (See §14.D.2.)
- **Sync `invalidateChatUser`**: it pops ONLY the `userInfo` field from the cache
  entry (NOT the whole entry — the `data` user_data blob is preserved).
  Synchronous (pure in-memory op). (See §14.C q2.)
- **No `dirtyKeys` touching**: the new methods do not add to
  `self.dirtyKeys[CacheNamespace.CHAT_USERS]`; that set is never flushed because
  `CHAT_USERS` is `MEMORY_ONLY` (§14.D.5).
