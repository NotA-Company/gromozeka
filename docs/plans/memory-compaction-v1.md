# Memory Compaction v1

**Status:** PLANNING (not yet implemented)
**Date:** 2026-07-09
**Author:** planning pass
**Related:**
- [`docs/plans/user-memories-v1.md`](user-memories-v1.md) — predecessor (the unified
  `user_memories` store), IMPLEMENTED. This plan compacts its storage path.
- [`docs/llm/memories/user-memories.md`](../llm/memories/user-memories.md) — canonical
  feature doc (current architecture).
- [`docs/llm/architecture.md`](../llm/architecture.md) ADR-016 — the unified
  `user_memories` store decision this builds on.

> This is a **planning document**, not a spec the code currently honours. It is
> written so a developer agent can execute it phase-by-phase without further
> design decisions. Every file path and `file:line` anchor was verified against
> the tree at planning time. The ten design decisions in §1.2 are **LOCKED by the
> user** — do not re-litigate them during implementation. `[DESIGN CHOICE]` marks
> a judgement call that goes beyond the locked decisions; the executing agent
> should flag these in its PR description but is not expected to re-litigate them.

### Review pass (2026-07-09)

The plan was re-verified end-to-end against the tree (every cited file read; an
explore agent confirmed 8 claims; two repo-wide greps). The ten locked decisions
in §1.3 stand unchanged. The following gaps/errors were corrected in this pass —
the executing agent should read them before starting:

- **§5.2.4 (new): `handleMention` text-reply bypass.** `llm_messages.py:722`
  calls `setUserMemories(metadata.get("memories"))` directly, bypassing
  `fromDBChatMessage`. Under the compact format this would render the ID-list
  dict as the `userMemories` block (garbage). Fixed by routing through the new
  `loadMemoriesMetadata` helper + `resolveMemories`.
- **§5.2.3: missed `injectMemories=True` site.** `media.py:652-653`
  (`_llmToolGenerateImage`) renders memories into the image prompt; it needs a
  `resolveMemories` call. Added to the site table.
- **§5.1: `keepId=True` leaked `id` into the LLM prompt.** The cache loader
  change is kept, but `injectMemories` now strips `id` from the injected content
  form (`permanentContent`) so no uuid reaches `formatForLLM`.
- **§5.2.1/§5.2.2: `None`-memories `TypeError`.** Format detection now guards
  `isinstance(rawMemories, dict)` (reachable via the `:722` bypass when stored
  metadata lacks `memories`).
- **§5.2: false justification corrected.** `fromDBChatMessage` is `async`, not
  sync; the real blocker to inlining resolution is a **circular import**
  (`CacheService` already imports from `internal.bot.models`).
- **§7.3/§8: grep-guard replaced with an AST-based coverage guard.** No
  production site uses the literal `injectMemories=True`; the guard must be
  AST-based and cover both the `fromDBChatMessage` shape and the
  `setUserMemories(metadata-derived)` bypass shape.
- **§5.2.2: `resolveMemoriesBatch` elevated to v1** for the
  `getThreadByMessageForLLM` list path (one DB query per thread on a cold cache,
  vs one per message).
- **§3.3: `deleteObsoleteMemoryEmbeddings` filter marked redundant**
  (defense-in-depth only — `embedding_model IS NOT NULL` already excludes
  soft-deleted rows).

---

## 1. Overview

### 1.1 What & why

The user-memories feature stores a **full content snapshot** of the injected
memories per message in `chat_messages.metadata.memories`. For a user with 10
permanent + 5 ephemeral memories, that is roughly **2–3 KB per message**. The
permanent block (~1.5 KB) is **byte-identical across every message from the same
`(chat, user, thread)`** — a 50-message thread therefore carries ~75 KB of
duplicated permanent-memory JSON in `chat_messages.metadata`.

The root cause is the injection design documented in
[`docs/llm/memories/user-memories.md`](../llm/memories/user-memories.md)
"Injection": `MessagePreprocessorHandler.injectMemories()` calls
`ensuredMessage.setUserMemories(...)` **before** `saveChatMessage`, so the
snapshot is persisted into the message's metadata and "rides per message" so
that `formatForLLM` can render it later without a re-fetch. That was correct for
read-path simplicity, but it duplicates immutable-per-thread content on every
row.

### 1.2 Solution (scope)

Store **memory IDs** (not content) per message, and resolve IDs → content at
read time via a cache layer backed by a new `getMemoriesByIds` repository
method. Add **soft-delete** to `user_memories` so deleted memories survive for
historical reconstruction (a historical message that references a now-deleted
memory must still resolve its content for the LLM).

**In scope:** storage compaction + historical-accuracy preservation.

**Out of scope (explicitly deferred — see §8):**

- **Prompt compaction / hoisting.** Memories still attach per-message (resolved
  from cache); hoisting the permanent block to a single system message is a
  separate future feature. The compact storage this plan introduces is a
  prerequisite for hoisting, not the hoisting itself.
- **GC for soft-deleted rows.** Noted as a known limitation; the table grows
  over time.
- **Backfill of old messages.** Old messages keep their content snapshots
  indefinitely (no migration to convert them to the ID format). They work
  correctly but don't benefit from the compaction.

### 1.3 Locked design decisions

These are **decided**. Do not re-litigate during implementation.

1. **Soft-delete:** `user_memories.deleted_at TIMESTAMP NULL`. `deleteMemory`
   sets `deleted_at` + deletes vec0 embeddings + nulls provenance. The memory
   content row survives.
2. **All existing read methods skip deleted** (`AND deleted_at IS NULL`). These
   power the CURRENT injection path (live memories only).
3. **New `getMemoriesByIds(memoryIds: List[str])`** repo method — fetches by UUID
   list, **NO `deleted_at` filter** (returns soft-deleted memories for historical
   reconstruction). No `chatId`/`userId` (UUID is globally unique; internal
   callers only). Routes to the default DB (single-DB assumption — confirmed:
   `DatabaseManager.getProvider(chatId=None, readonly=True)` falls back to the
   default source at [`manager.py:162-168`](../../internal/database/manager.py)).
4. **Store IDs per message:** `metadata["memories"] = {"permanentIds": [...],
   "shortTermIds": [...]}` instead of full `SingleMemoryDict` content.
5. **New `CacheNamespace.MEMORIES_BY_ID`** + `CacheService.getMemoriesByIds(memoryIds)`
   — full cache namespace with a MEMORY_ONLY TTL strategy. Cache-first
   (`memory_id` → `SingleMemoryDict`), batch-DB-query for misses, populate.
   Returns `Dict[str, Optional[SingleMemoryDict]]`.
6. **Remove `updateMemory`** — zero production callers (verified by grep: all
   `updateMemory` matches are the method definition, internal comments, and
   `tests/database/repositories/test_user_memories.py`; no production call site).
   6 test functions + 8 doc references to clean up.
7. **Backward compat:** old messages have full content dicts
   (`{"permanent": [...], "shortTerm": [...]}`). New messages have ID lists
   (`{"permanentIds": [...], "shortTermIds": [...]}`). The read path detects
   format and handles both. No backfill.
8. **Prompt hoisting deferred** — memories still attach per-message (resolved
   from cache), just stored compactly.
9. **GC for soft-deleted memories deferred** — note as a known limitation.
10. **Cache invalidation:** soft-delete does NOT invalidate (content preserved
    for historical reads). No `updateMemory` to invalidate. `addMemory` does NOT
    invalidate (new memory, not yet cached). Process restart clears the cache
    (MEMORY_ONLY).

---

## 2. Schema change

### 2.1 Migration 021

**File:** `internal/database/migrations/versions/migration_021_user_memories_soft_delete.py`

Next migration number is **021** (verified: latest is
`migration_020_user_memories.py`). Class shape mirrors
`migration_020_user_memories.py` exactly — `class Migration021UserMemoriesSoftDelete(BaseMigration)`
with `version: int = 21`, `description: str = "Add deleted_at to user_memories"`,
`async def up(self, sqlProvider)`, `async def down(self, sqlProvider)`,
`def getMigration() -> Type[BaseMigration]`. DDL via
`sqlProvider.batchExecute([ParametrizedQuery(sql), ...])` (mirror
`migration_017_message_embeddings.py:26-91`).

> Before adding the migration, scaffold via the `add-database-migration` skill
> and follow its SQL-portability rules.

**`up()`:**

```sql
ALTER TABLE user_memories ADD COLUMN deleted_at TIMESTAMP NULL;
```

**`down()`:** SQLite cannot `DROP COLUMN` portably across the target RDBMS set,
and a rebuild-via-temp-table is heavier than warranted for a rollback of a
nullable column. The `down()` is therefore a **no-op that logs**: it cannot
drop the column portably, but the column is nullable and additive, so leaving
it in place on rollback is safe. Document this in the migration docstring.

### 2.2 No index

No index on `deleted_at`. The table is small (per-chat memory volume is tiny
relative to messages), every live-memory read already filters on the composite
`(chat_id, user_id, ...)` indexes from migration 020, and `AND deleted_at IS NULL`
is a cheap residual predicate on the already-filtered row set. If a profiler
later shows the soft-delete scan dominating, a partial index
`CREATE INDEX ... WHERE deleted_at IS NULL` is the portable shape — but do not
add it speculatively.

### 2.3 SQL portability notes

> AGENTS.md SQL-portability rules honoured.

- **Portable `TIMESTAMP` type, nullable, no `DEFAULT`.** No
  `DEFAULT CURRENT_TIMESTAMP` (AGENTS.md: migration 013 removed it from every
  table for cross-DB compatibility; app code sets timestamps explicitly). The
  soft-delete timestamp is set application-side in `deleteMemory` via
  `dbUtils.getCurrentTimestamp()`.
- Additive nullable column — `ALTER TABLE ... ADD COLUMN` is portable across
  SQLite / PostgreSQL / MySQL.
- No `AUTOINCREMENT`, no `SERIAL` (N/A — this migration adds no key).

---

## 3. Repository changes

**File:** `internal/database/repositories/user_memories.py`

### 3.1 Remove `updateMemory`

`updateMemory` (`user_memories.py:187-302`) has **zero production callers**.
Verified by `grep updateMemory` across the tree: every match is either the
method definition, a docstring/comment inside `user_memories.py` referencing it,
or a test in `tests/database/repositories/test_user_memories.py`. No handler,
service, or other repository calls it.

**Remove:**

- The `updateMemory` method definition (`user_memories.py:187-302`).
- **6 test functions** in `tests/database/repositories/test_user_memories.py`:
  - `test_updateMemory_contentOnly` (~:208)
  - `test_updateMemory_tagsOnly` (~:227)
  - `test_updateMemory_typeOnly` (~:247)
  - `test_updateMemory_noMatchReturnsFalse` (~:266)
  - `test_updateMemory_noFieldsReturnsFalse` (~:271)
  - `test_updateMemory_contentInvalidatesEmbedding` (~:941)
- **Comments/docstrings referencing `updateMemory`** inside `user_memories.py`
  (~8 references in docstrings of `deleteMemory`, `searchMemories`,
  `_semanticSearchMemories`, `deleteMemoryEmbedding`, and the module docstring
  at `:10`). Each must be reworded: the "denormalised vec0 columns go stale
  after `updateMemory`" rationale disappears once `updateMemory` is gone — vec0
  columns are now written once at embed time and never edited.
- **Doc references** in `docs/llm/memories/user-memories.md` (the "Writes" bullet
  at `:101-103`, the "`updateMemory` content-change invalidation" paragraph at
  `:132-137`, and the vec0-staleness notes at `:83-87`/`:119-120`). These are
  synced in Phase 4.

> `[DESIGN CHOICE]` — if content changes are needed in the future, use
> `deleteMemory` + `addMemory` (the dedup state machine in `add_memory` already
> handles the "similar exists → delete-old + re-add-updated" path via the
> refinement LLM; D3/D5 in `user-memories-v1.md`). `updateMemory`'s in-place
> PATCH with embedding invalidation is therefore redundant machinery.

### 3.2 Soft-delete in `deleteMemory`

Change `deleteMemory` (`user_memories.py:304-374`) from a hard `DELETE` to a
soft delete: `UPDATE user_memories SET deleted_at = :now WHERE ...`.

**Keep unchanged:**

- vec0 embedding deletion via `deleteMemoryEmbedding(chatId, userId, memoryId, vecOnly=True)` (`:365`).
- Provenance nulling (`embedding_model`/`embedding_dimensions`) — currently done
  inside `deleteMemoryEmbedding` only when `vecOnly=False`. Since the soft-delete
  keeps the row, provenance nulling must still happen so the regen cron does not
  re-embed a deleted memory. Call `deleteMemoryEmbedding(..., vecOnly=False)`
  instead of `vecOnly=True` so the provenance columns are reset. (The
  `deleteMemoryEmbedding` provenance UPDATE at `:1238-1256` uses
  `SET embedding_model = NULL, embedding_dimensions = NULL, updated_at = :updatedAt`
  — that bumps `updated_at`, which is fine alongside setting `deleted_at`.)

**Change:**

- The `DELETE FROM user_memories WHERE ...` statement (`:354-363`) becomes
  `UPDATE user_memories SET deleted_at = :now WHERE chat_id = :chatId AND
  user_id = :userId AND memory_id = :memoryId AND deleted_at IS NULL`.
- **Return bool** (found AND not already deleted): the existence pre-check
  (`:341-352`) currently matches any row regardless of `deleted_at`. Tighten it
  to `AND deleted_at IS NULL` so a re-delete of an already-soft-deleted memory
  returns `False` (mirrors the existing "re-delete returns False" contract at
  `:317-320`, now scoped to the live row).
- **Never-raise contract preserved:** the whole body stays in its existing
  `try/except Exception` (`:334`/`:367-374`) returning `False` on error.

> `[DESIGN CHOICE]` — null provenance on soft-delete. The vec0 row is deleted
> (a deleted memory must never be a semantic-search hit), and provenance is
> nulled so `getMemoriesWithoutEmbeddings` does not surface a deleted memory for
> re-embedding. The content row survives with `deleted_at` set so
> `getMemoriesByIds` (no `deleted_at` filter) can still resolve it for
> historical reads.

### 3.3 Fix all read methods to skip deleted

Every existing read method that powers the **live** injection/search path gains
`AND deleted_at IS NULL`. (The historical-resolution method `getMemoriesByIds`
in §3.4 is the single deliberate exception.)

Add `AND deleted_at IS NULL` to the WHERE clause of:

| Method | Location | Current WHERE anchor |
|---|---|---|
| `getPermanentMemories` | `user_memories.py:408-417` | `:411-415` |
| `getLatestMemories` | `user_memories.py:455-464` | `:458-462` |
| `getMemory` | `user_memories.py:498-507` | `:502-505` (the `/memory_config` wizard single-row read — live only, so a deleted memory must not appear in the wizard) |
| `getDistinctTags` | `user_memories.py:549-558` | `:552-555` (wizard tag picker — live only) |
| `searchMemories` → `_filterOnlySearchMemories` | `user_memories.py:745-756` | `:748-754` |
| `searchMemories` → `_semanticSearchMemories` (JOIN step) | `user_memories.py:944-954` | `:947-953` |
| `getMemoriesWithoutEmbeddings` | `user_memories.py:1356-1370` | `:1359-1368` (regen cron — never re-embed a deleted memory) |
| `deleteObsoleteMemoryEmbeddings` (stale-row predicate) | `user_memories.py:1477-1492` | `:1478-1488` (the `staleWhere` string) |

> The vec0 search itself (`_semanticSearchMemories` vec0 step, `:877-900`) does
> NOT need a `deleted_at` filter: `deleteMemory` already drops the vec0 row, so
> a deleted memory has no vec0 row to be a hit. The `deleted_at IS NULL` filter
> on the authoritative-row JOIN (`:947-953`) is belt-and-suspenders against a
> partially-failed delete.
>
> **`deleteObsoleteMemoryEmbeddings` filter is redundant defense-in-depth.** Its
> `staleWhere` already requires `embedding_model IS NOT NULL` (`:1479`/`:1488`),
> and §3.2's soft-delete nulls `embedding_model` (via
> `deleteMemoryEmbedding(..., vecOnly=False)`), so soft-deleted rows are already
> excluded before the `deleted_at` predicate ever runs. Keeping the filter is
> harmless (and cheap on the already-filtered set), but do not treat it as
> load-bearing. **Contrast:** `getMemoriesWithoutEmbeddings`'s `deleted_at IS NULL`
> filter **is** load-bearing — a soft-deleted row has `embedding_model IS NULL`
> and would otherwise be re-surfaced by the regen cron, re-embedded, and its
> vec0 rows recreated, violating "a deleted memory must never be a search hit."

### 3.4 New `getMemoriesByIds`

```python
async def getMemoriesByIds(
    self,
    memoryIds: List[str],
) -> List[UserMemoryDict]:
    """Fetch memories by UUID list, including soft-deleted rows.

    The single read path that does NOT filter ``deleted_at``: a historical
    message that references a now-deleted memory must still resolve its
    content for LLM context reconstruction. UUIDs are globally unique, so no
    ``chatId``/``userId`` scoping is needed (internal callers only).

    Args:
        memoryIds: List of memory UUID hex strings.

    Returns:
        List of :class:`UserMemoryDict` (including soft-deleted rows). Rows
        whose ``memory_id`` is not present are simply absent from the result
        (the caller maps request → result by ``memory_id``).
    """
```

**SQL:**

```sql
SELECT { _SELECT_COLUMNS }
FROM user_memories
WHERE memory_id IN (:id0, :id1, ...)
```

- **NO `deleted_at IS NULL` filter** (returns soft-deleted memories).
- **NO `chatId`/`userId`** (UUID globally unique).
- **Routing:** `self.manager.getProvider(chatId=None, readonly=True)` → default
  source. Confirmed: `DatabaseManager.getProvider` falls back to `self.default`
  when `chatId is None and dataSource is None`
  ([`manager.py:162-168`](../../internal/database/manager.py)). This matches the
  locked single-DB assumption.
- **`IN (...)` with a variable-length list:** use the `:id0, :id1, ...` named-
  placeholder expansion already used in `_semanticSearchMemories`
  (`user_memories.py:940-943`) — build `placeholders`/`fetchParams` in a loop.
  The sqlite3 provider handles `:named` params for lists exactly this way (no
  `qmark`-list binding needed).
- **Empty `memoryIds`:** return `[]` immediately (no SQL round-trip).
- Decode via `[dbUtils.sqlToTypedDict(row, UserMemoryDict) for row in rows]`
  (same as every other read).
- **`_SELECT_COLUMNS`** (`user_memories.py:72-76`) does not select `deleted_at`,
  and `UserMemoryDict` ([`internal/database/models.py`](../../internal/database/models.py))
  has no `deleted_at` key. Leave both as-is — `deleted_at` is plumbing the
  read-path consumers do not need; `getMemoriesByIds` returns live and
  soft-deleted rows in the same shape.

> `[DESIGN CHOICE]` — single-DB routing only. In a multi-DB deployment the
> caller would have to pass routing info, but production is single-DB today
> (AGENTS.md: "SQLite is the only backend wired up in production right now").
> Flagged as a known limitation in §8.

---

## 4. Cache layer

### 4.1 New `CacheNamespace.MEMORIES_BY_ID`

**File:** `internal/services/cache/models.py`

Add a member to the `CacheNamespace(StrEnum)` (`models.py:38-60`):

```python
    MEMORIES_BY_ID = "memoriesById"
    """Namespace for the memory_id -> SingleMemoryDict resolution cache.

    Keys memory UUID strings to their slimmed :class:`SingleMemoryDict` form.
    MEMORY_ONLY persistence (never written to disk; cleared on process restart).
    Used by :meth:`CacheService.getMemoriesByIds` to resolve the compact ID
    format (§5) back to content at read time.
    """
```

`getPersistenceLevel` (`models.py:62-85`) already returns `MEMORY_ONLY` for
anything that is not `USERS`/`CHAT_PERSISTENT`, so no change needed there —
`MEMORIES_BY_ID` picks up `MEMORY_ONLY` automatically. This satisfies locked
decision #5/#10 (no disk persistence; cleared on restart).

### 4.2 Wire the namespace into `CacheService`

**File:** `internal/services/cache/service.py`

Three edits mirroring how the existing four namespaces are wired
(`service.py:263-293`):

1. **`_caches` dict** (`:263-284`): add an `LRUCache[str, Optional[SingleMemoryDict]]`
   entry under `CacheNamespace.MEMORIES_BY_ID` (keyType=str,
   valueType=Optional[SingleMemoryDict]). Extend the dict's union type hint
   accordingly.
2. **`dirtyKeys` dict** (`:288-293`): add `CacheNamespace.MEMORIES_BY_ID: set()`.
   (Even though MEMORY_ONLY never persists, the existing code initialises
   `dirtyKeys` for every namespace; mirror it to avoid a KeyError in any
   generic persistence walk.)
3. **Accessor property** (`:321-359`): add
   `@property def memoriesById(self) -> LRUCache[str, Optional[SingleMemoryDict]]:`
   returning `self._caches[CacheNamespace.MEMORIES_BY_ID]`, mirroring the
   `chats`/`chatUsers`/`users`/`chatPersistent` property shape.

### 4.3 `CacheService.getMemoriesByIds`

```python
async def getMemoriesByIds(self, memoryIds: List[str]) -> Dict[str, Optional[SingleMemoryDict]]:
    """Resolve memory IDs to their SingleMemoryDict form, cache-aside.

    Cache-first: each requested ID is looked up in the MEMORIES_BY_ID namespace.
    Misses are batch-queried via ``db.userMemories.getMemoriesByIds(missingIds)``,
    converted to ``SingleMemoryDict`` via
    :func:`convertDBMemoryToSingleMemoryDict`, and populated back into the cache.
    Returns a dict mapping every requested ID to its resolved entry, or
    ``None`` for IDs not found in the DB (a missing ID is cached as ``None`` so
    a repeated miss does not re-query).

    Args:
        memoryIds: Memory UUID hex strings to resolve.

    Returns:
        ``Dict[str, Optional[SingleMemoryDict]]`` keyed by the requested IDs.
        Empty dict when ``memoryIds`` is empty or no database is wired.
    """
```

**Flow:**

1. If `memoryIds` is empty → return `{}`.
2. Walk `memoryIds`, partitioning into hits (present in `self.memoriesById`)
   and misses (absent).
3. If misses is non-empty: `dbRows = await self.database.userMemories.getMemoriesByIds(missingIds)`,
   convert each via `convertDBMemoryToSingleMemoryDict(dbRow)` (with
   `keepId=True` so the resolved entry carries its `id` — matches the slim form
   the read path renders), build `resolvedBy: Dict[str, SingleMemoryDict]`.
4. Populate the cache: for each `mid` in `missingIds`, set
   `self.memoriesById.set(mid, resolvedBy.get(mid, None))` — **cache `None` for
   IDs not found in the DB** so a repeated miss does not re-query (negative
   caching). Guard with `if not self.database:` returning empty list (mirror
   `getChatUserPermanentMemories` at `service.py:895-897`).
5. Return `{mid: self.memoriesById.get(mid, None) for mid in memoryIds}` (the
   property accessor returns the cached value, which is now populated for every
   requested ID).

> The cache stores **resolved content only** (no `deleted_at` plumbing), so a
> soft-deleted memory resolves to its preserved content just like a live one.
> This is the whole point of soft-delete: historical reads see the content even
> after the memory is no longer "live".

### 4.4 Cache invalidation

Per locked decisions #10:

- **Soft-delete:** NO invalidation. Content is preserved for historical reads;
  the cached `SingleMemoryDict` stays valid (it was correct when cached and the
  content never changes after a soft-delete — there is no `updateMemory`).
- **`updateMemory`:** N/A (being removed — §3.1).
- **`addMemory`:** NO invalidation. A brand-new memory is not yet cached; it
  will be cached on first read via `getMemoriesByIds`.
- **Process restart:** clears the cache naturally (MEMORY_ONLY persistence —
  `getPersistenceLevel` returns `MEMORY_ONLY`, never written to disk).

There is therefore **no invalidation method to add** to `CacheService` for this
namespace. The only writer to the cache is `getMemoriesByIds` itself (cache-aside
on miss).

---

## 5. Storage format change

### 5.1 Write path — `MessagePreprocessorHandler.injectMemories`

**File:** `internal/bot/common/handlers/message_preprocessor.py`

`injectMemories` (`message_preprocessor.py:77-120`) currently ends with:

```python
shortTermMemories = [convertDBMemoryToSingleMemoryDict(memory) for memory in memories]
ensuredMessage.setUserMemories({"permanent": permanentMemories, "shortTerm": shortTermMemories})
```

`setUserMemories` (`ensured_message.py:873-883`) sets **both** `self.userMemories`
and `self.metadata["memories"]` to the content. For the compact format these
must **diverge**:

```python
shortTermMemories = [convertDBMemoryToSingleMemoryDict(memory) for memory in memories]
# Extract IDs for PERSISTENCE before the content form is finalised:
permanentIds = [m["id"] for m in permanentMemories if "id" in m]
shortTermIds = [m["memory_id"] for m in memories if m.get("memory_id")]
# Content for the CURRENT turn's LLM context — STRIP `id` from each permanent
# entry so the injected form honours SingleMemoryDict.id's "absent on injected
# snapshots" invariant (id is useless at chat time; delete_memory is a
# refinement-only tool, and a leaked uuid adds a token per permanent memory):
permanentContent = [{k: v for k, v in m.items() if k != "id"} for m in permanentMemories]
ensuredMessage.userMemories = {"permanent": permanentContent, "shortTerm": shortTermMemories}
# IDs for PERSISTENCE (compact metadata — what gets saved into chat_messages.metadata):
ensuredMessage.metadata["memories"] = {
    "permanentIds": permanentIds,
    "shortTermIds": shortTermIds,
}
```

Details:

- **`permanentMemories`** comes from `cache.getChatUserPermanentMemories(...)` (`:88-92`),
  which returns `list[SingleMemoryDict]`. The permanent-memories cache loader
  (`service.py:899-905`) currently converts via `convertDBMemoryToSingleMemoryDict(m)`
  **without** `keepId=True`, so permanent entries lack `id`. **Fix:** change the
  loader at `service.py:905` to `convertDBMemoryToSingleMemoryDict(m, keepId=True)`
  so permanent IDs are extractable here. **Then strip `id` from the content form**
  (see `permanentContent` above) — keeping `id` in the injected `userMemories`
  would leak a uuid into every permanent memory in every injected message
  (`formatForLLM` renders the dict verbatim), contradicting `SingleMemoryDict.id`'s
  "absent on injected snapshots" invariant and adding tokens for no chat-time
  benefit. The cache keeps `id`; the injected content does not.
- **`memories`** (ephemeral) comes from `getLatestMemories`/`searchMemories`
  (`:103-116`) as `list[UserMemoryDict]` — each carries `memory_id`, so extract
  `[m["memory_id"] for m in memories]` BEFORE the `convertDBMemoryToSingleMemoryDict`
  conversion (the slim form drops `memory_id` unless `keepId=True`).
- **Filter out falsy IDs** defensively (`if "id" in m` / `if m.get("memory_id")`)
  so a malformed row never writes `None` into the ID list.

> This deliberately bypasses `setUserMemories` (which would overwrite
> `metadata["memories"]` with content). Assigning `userMemories` and
> `metadata["memories"]` separately is the contract divergence point. Note it
> in a code comment.

### 5.2 Read path — `fromDBChatMessage` + new `resolveMemories`

Resolution cannot live inside `fromDBChatMessage` (`ensured_message.py:784-871`)
for two reasons: (a) it would require `EnsuredMessage` to depend on
`CacheService`, but `CacheService` already imports from `internal.bot.models`
(it uses `convertDBMemoryToSingleMemoryDict` at `service.py:905`), so a
back-import from `ensured_message` would create a **circular import** (caught by
`make lint`'s `import main` check); (b) the handler layer already holds
`self.cache` in scope, so resolving there is the natural seam. Note
`fromDBChatMessage` is in fact `async` (it awaits
`db.mediaAttachments.getMediaAttachmentsByGroupId` at `:853`) — asynchronicity
is **not** the blocker; the import cycle is. The split:

**5.2.1 `fromDBChatMessage` — detect format (`ensured_message.py:867-868`):**

Replace

```python
if injectMemories and "memories" in metadata:
    ensuredMessage.setUserMemories(metadata["memories"])
```

with a call to a new stash helper (defined in §5.2.2) that detects the format
without resolving IDs:

```python
if injectMemories and "memories" in metadata:
    ensuredMessage.loadMemoriesMetadata(metadata["memories"])
```

`loadMemoriesMetadata` stashes the raw compact IDs into `metadata["memories"]`
and leaves `userMemories=None` (resolved later by `resolveMemories`); old
content format is applied via `setUserMemories` as before; `None`/non-dict is a
no-op (regression guard — see §5.2.2). Inlining the detection here would
duplicate it at the `:722` bypass (§5.2.4), so it is factored into the helper.

**5.2.2 New `EnsuredMessage` memory methods.**

Three methods: a sync stash/detect helper, an async per-message resolver, and a
static batch prefetch variant for the list path (§5.2.3).

```python
def loadMemoriesMetadata(self, rawMemories: Optional[Dict[str, object]]) -> None:
    """Stash raw memories metadata without resolving IDs to content.

    Compact format (``permanentIds``/``shortTermIds``) leaves ``userMemories``
    unset — resolved later by :meth:`resolveMemories`. Old content format is
    applied via :meth:`setUserMemories` as before. ``None``/non-dict is a no-op
    (tolerant of bypass sites that did ``metadata.get("memories")`` on a dict
    lacking the key, or stored ``None`` — regression guard against the old
    ``"permanentIds" in None`` ``TypeError``).

    Args:
        rawMemories: The raw value of ``metadata["memories"]`` (compact ID dict,
            old content dict, or ``None``).

    Returns:
        None.
    """
    if not isinstance(rawMemories, dict):
        return
    if "permanentIds" in rawMemories or "shortTermIds" in rawMemories:
        # Compact format: keep raw IDs in metadata; userMemories stays None
        # (resolving here would import CacheService -> circular import; see §5.2).
        self.metadata["memories"] = rawMemories
    else:
        # Old content format: content is already inline.
        self.setUserMemories(rawMemories)


async def resolveMemories(self, cache: "CacheService") -> None:
    """Resolve the compact memory-ID format to content via the cache.

    No-op when ``userMemories`` is already populated (old content format, or
    the current-turn write path that sets content directly). Otherwise, when
    ``metadata["memories"]`` carries the compact ID lists (``permanentIds`` /
    ``shortTermIds``), resolves all IDs in one cache call and populates
    ``userMemories`` with the resolved content. Called by read-path consumers
    AFTER building the message list and BEFORE ``formatForLLM``.

    Args:
        cache: CacheService singleton for ID->content resolution.

    Returns:
        None.
    """
    if self.userMemories is not None:
        return  # already resolved (old format or current-turn content)
    rawMemories = self.metadata.get("memories")
    if not isinstance(rawMemories, dict):
        return  # None / non-dict (tolerant of bypass sites that stored None)
    permanentIds = rawMemories.get("permanentIds", []) or []
    shortTermIds = rawMemories.get("shortTermIds", []) or []
    if not permanentIds and not shortTermIds:
        return
    allIds = permanentIds + shortTermIds
    resolved = await cache.getMemoriesByIds(allIds)
    self.setUserMemories(
        {
            "permanent": [resolved[mid] for mid in permanentIds if resolved.get(mid)],
            "shortTerm": [resolved[mid] for mid in shortTermIds if resolved.get(mid)],
        }
    )


@staticmethod
async def resolveMemoriesBatch(messages: List["EnsuredMessage"], cache: "CacheService") -> None:
    """Prefetch all compact memory IDs across ``messages`` in one cache call,
    then resolve each (cache hits after the prefetch).

    Equivalent to calling :meth:`resolveMemories` per message but with a single
    miss-batch DB query instead of one per message on a cold cache. Intended for
    the list path (``getThreadByMessageForLLM``) where N messages reference the
    same permanent cohort. Old-format and already-resolved messages are no-ops.

    Args:
        messages: Messages to resolve (mixed old/new format is fine).
        cache: CacheService singleton for ID->content resolution.

    Returns:
        None.
    """
    allIds: List[str] = []
    for msg in messages:
        if msg.userMemories is not None:
            continue
        raw = msg.metadata.get("memories")
        if isinstance(raw, dict):
            allIds.extend(raw.get("permanentIds", []) or [])
            allIds.extend(raw.get("shortTermIds", []) or [])
    if allIds:
        await cache.getMemoriesByIds(allIds)  # prefetch -> warms the cache
    for msg in messages:
        await msg.resolveMemories(cache)  # cache hits after prefetch
```

(`setUserMemories` deep-copies and re-points `metadata["memories"]` at the
resolved content, which is fine — the compact IDs have served their purpose once
resolved. No read-path consumer re-persists the message, so overwriting
`metadata["memories"]` in-memory is safe.)

**5.2.3 Wire `resolveMemories` into read-path consumers.**

Every consumer that builds an `EnsuredMessage` from stored message data and
then renders it for the LLM must call `await msg.resolveMemories(self.cache)`
(or `resolveMemoriesBatch` for the list path) **before**
`formatForLLM`/`toModelMessageList`/`toModelMessage`. There are two shapes of
such site — those that go through `fromDBChatMessage` (covered by §5.2.1's
`loadMemoriesMetadata`, which leaves `userMemories=None` for the compact format)
and one **bypass** that calls `setUserMemories` directly (covered by §5.2.4).
Both shapes need the `resolveMemories` call.

The full set (verified by grepping every `fromDBChatMessage(..., injectMemories=)`
and every `setUserMemories(` site in production):

| Consumer | File:line | Shape | Notes |
|---|---|---|---|
| `getThreadByMessageForLLM` | `internal/bot/common/handlers/base.py:695, 717, 725, 754` | `fromDBChatMessage` | Builds `eMessage`/`eRootMessage` then `toModelMessageList`. **Hottest path — use `resolveMemoriesBatch` on the whole list (DESIGN CHOICE below).** |
| `handleMention` (non-text-message branch) | `internal/bot/common/handlers/llm_messages.py:745-747` | `fromDBChatMessage` | `eStoredReply` built from DB; call `resolveMemories` before `toModelMessage` at `:749`. |
| `handleMention` (text-message-reply branch) | `internal/bot/common/handlers/llm_messages.py:718-724` | **bypass** (§5.2.4) | Manually parses `storedReply["metadata"]` JSON and calls `ensuredReply.setUserMemories(metadata.get("memories"))` at `:722`. Under the compact format this would set `userMemories` to the raw ID-list dict → garbage in the LLM context. **Must be rewritten per §5.2.4.** |
| `handleRandomMessage` (non-thread branch) | `internal/bot/common/handlers/llm_messages.py:882` | `fromDBChatMessage` | `eMsg` built from DB; call `resolveMemories` before its `toModelMessage`/list append. |
| `_llmToolGenerateImage` (image-prompt fallback) | `internal/bot/common/handlers/media.py:652-653` | `fromDBChatMessage` | `eMsg` built from DB, then `toModelMessage` (`:656`) → `llmService.generateText` (`:664`). Injection is gated by `MEMORY_INJECTION_ENABLED`, so when enabled this site renders memories into the image prompt — call `resolveMemories` before `:656`. |

`handleReply` (`llm_messages.py:535`) delegates to `getThreadByMessageForLLM`,
so it is covered transitively.

> **No production site passes the literal `injectMemories=True`.** All pass a
> bool variable (`needMemories` at `base.py:676`; `injectMemories` at
> `llm_messages.py:695/807`) or an inline `.toBool()` (`media.py:653`). The
> literal-`False` sites (`summarization.py:215/676/679`, `chat_search.py:411/664`,
> `user_data.py:1422`, `media.py:329`) never inject memories and need no
> `resolveMemories`. `scripts/reproduce_llm_dialog.py:387` is a dev/repro
> `injectMemories=var` site — low priority, but worth wiring for consistency.

> `[DESIGN CHOICE]` — per-message `resolveMemories` for the single-message
> paths (mention/random/media) and the **batch** variant (`resolveMemoriesBatch`,
> §5.2.2) for `getThreadByMessageForLLM` (the list path). The list path builds N
> messages all referencing the same permanent cohort; per-message resolution
> means N cache lookups (the first warms the cache, the rest hit, but the
> miss-batch DB query is still issued once per message until warm). The batch
> variant collects every ID across the list and issues a single
> `getMemoriesByIds` — one DB query for the whole thread instead of
> one-per-message on a cold cache. **Recommend: batch for
> `getThreadByMessageForLLM` in v1**, per-message `resolveMemories` for the
> single-message paths. (The cache makes the per-message form's repeated calls
> cheap once warm, so the batch is a cold-cache optimisation, not a correctness
> requirement — if the implementer prefers to defer it, per-message everywhere
> is correct, just slower on a cold first turn.)

### 5.2.4 Fix the `handleMention` text-reply bypass (`llm_messages.py:718-724`)

`handleMention`'s text-message-reply branch does **not** build its
`EnsuredMessage` via `fromDBChatMessage`; it manually parses the stored reply's
metadata JSON and calls `setUserMemories(metadata.get("memories"))` directly
(`:722`). Under the compact format, `metadata["memories"]` is
`{"permanentIds": [...], "shortTermIds": [...]}` — an ID list, not content — so
`setUserMemories` would set `userMemories` to that dict and `formatForLLM` would
render it verbatim as the `userMemories` block (garbage). This is the **only**
`setUserMemories(metadata-derived)` bypass in production (the other two
`setUserMemories` sites are the write path at `message_preprocessor.py:120` and
`fromDBChatMessage` itself at `ensured_message.py:868`).

**Fix:** make this site defer resolution the same way `fromDBChatMessage` does,
by calling the §5.2.2 stash helper instead of `setUserMemories`:

```python
# llm_messages.py:722 — was: ensuredReply.setUserMemories(metadata.get("memories"))
ensuredReply.loadMemoriesMetadata(metadata.get("memories"))
```

and add `await ensuredReply.resolveMemories(self.cache)` before the
`toModelMessage` render at `:749` (covered by the §5.2.3 table). Factoring the
detection into `loadMemoriesMetadata` (rather than inlining it here) keeps the
format-detection logic in one place — important for the §7.3 coverage guard,
which must catch **both** the `fromDBChatMessage` shape and this bypass shape.

### 5.3 `formatForLLM` — unchanged

`formatForLLM` (`ensured_message.py:1050-1123`) renders
`"userMemories": self.userMemories` (`:1104`) regardless of how `userMemories`
was populated. As long as `resolveMemories` (or the old path's `setUserMemories`)
runs before `formatForLLM`, the output is identical. **No change to
`formatForLLM`.**

---

## 6. Implementation phases

Each phase ends with `make test` green and a self-contained behaviour change.
Phases are ordered so earlier phases do not depend on later ones.

### Phase 1 — Migration + repo changes (no behaviour change for existing messages)

- Migration 021 (`deleted_at` column) — §2.
- Remove `updateMemory` + clean up its 6 tests and ~8 doc/comment references — §3.1.
- Soft-delete in `deleteMemory` — §3.2.
- Add `AND deleted_at IS NULL` to every read method listed in §3.3.
- New `getMemoriesByIds` (no `deleted_at` filter) — §3.4.

**Exit:** `make test` green; existing messages unaffected (no `deleted_at` set
on any row, so live reads return the same rows as before; `getMemoriesByIds` is
not yet called anywhere). `deleteMemory` now soft-deletes — covered by a new
regression test asserting the row survives with `deleted_at` set and is skipped
by `getPermanentMemories`.

### Phase 2 — Cache layer

- New `CacheNamespace.MEMORIES_BY_ID` — §4.1.
- Wire the namespace into `CacheService.__init__` (`_caches` + `dirtyKeys` +
  `memoriesById` property) — §4.2.
- `CacheService.getMemoriesByIds` — §4.3.
- **No** invalidation method (§4.4).

**Exit:** cache works in isolation (unit-tested against a stub DB). Not yet
called by the read path.

### Phase 3 — Storage format change (behaviour change: new messages use compact format)

- `injectMemories` stores IDs + strips `id` from the injected content form — §5.1
  (including the `keepId=True` fix in the permanent-memories cache loader at
  `service.py:905`, and the `permanentContent` id-stripping so no uuid leaks
  into the LLM prompt).
- `fromDBChatMessage` detects the new format via `loadMemoriesMetadata` (with
  the `None`/non-dict guard) — §5.2.1.
- New `EnsuredMessage` memory methods (`loadMemoriesMetadata`, `resolveMemories`,
  `resolveMemoriesBatch`) — §5.2.2.
- Rewrite the `handleMention` text-reply bypass at `llm_messages.py:722` to use
  `loadMemoriesMetadata` — §5.2.4.
- Wire `resolveMemories`/`resolveMemoriesBatch` into `getThreadByMessageForLLM`
  (batch), `handleMention` (both branches), `handleRandomMessage`, and
  `_llmToolGenerateImage` — §5.2.3.

**Exit:** new messages are stored compactly (verify by inspecting a freshly
saved `chat_messages.metadata.memories` — it has `permanentIds`/`shortTermIds`,
not `permanent`/`shortTerm`); the read path resolves them correctly; old
messages still render unchanged.

### Phase 4 — Docs sync

- Update [`docs/llm/memories/user-memories.md`](../llm/memories/user-memories.md):
  - Schema table: add `deleted_at` row.
  - Repository section: remove `updateMemory` from the "Writes" bullet and drop
    the "`updateMemory` content-change invalidation" paragraph; add
    `getMemoriesByIds`; note the `AND deleted_at IS NULL` filter on live reads
    and the soft-delete semantics in `deleteMemory`.
  - Injection section: document the compact ID format + cache resolution +
    `resolveMemories` call sites.
- Update [`docs/database-schema.md`](../database-schema.md) and
  [`docs/database-schema-llm.md`](../database-schema-llm.md) for the
  `deleted_at` column.
- Update [`docs/llm/handlers.md`](../llm/handlers.md) if the read-path
  `resolveMemories` wiring changes handler behaviour notes.
- Add an ADR entry to [`docs/llm/architecture.md`](../llm/architecture.md) for
  the soft-delete + ID-storage + cache decision.
- Note GC deferral (§8) and prompt-hoisting deferral in the canonical doc.

> Load the `update-project-docs` skill for Phase 4 and follow its decision
> matrix.

---

## 7. Test strategy

All tests under `tests/` (AGENTS.md: "All new test files MUST go under
`tests/`"). Existing repo tests live at
`tests/database/repositories/test_user_memories.py`; cache tests at
`tests/services/cache/` (mirror the existing structure); ensured-message tests
under `tests/bot/models/` (or wherever the existing `EnsuredMessage` tests
live — confirm at implementation time).

### 7.1 Phase 1 tests

- **Soft-delete behaviour:** after `deleteMemory`, the row survives with
  `deleted_at` set; `getPermanentMemories`/`getLatestMemories`/`searchMemories`
  skip it; `getMemory` returns `None`; `getDistinctTags` excludes its tags.
- **`deleteMemory` idempotency:** a second `deleteMemory` on the same
  `(chatId, userId, memoryId)` returns `False` (already soft-deleted).
- **`deleteMemory` never-raises:** inject a DB error (e.g. readonly provider)
  and assert `False`, no exception.
- **vec0 + provenance cleanup on soft-delete:** after `deleteMemory`, the vec0
  row is gone and `embedding_model`/`embedding_dimensions` are `NULL` on the
  surviving row; `getMemoriesWithoutEmbeddings` does NOT re-surface it (because
  `deleted_at IS NULL` filter excludes it).
- **`getMemoriesByIds` returns soft-deleted:** after soft-deleting a memory,
  `getMemoriesByIds([thatId])` still returns it (content preserved).
- **`getMemoriesByIds` ignores `chatId`/`userId`:** memories from two different
  `(chatId, userId)` scopes are both returned by a single ID-list call.
- **`getMemoriesByIds` empty list:** `getMemoriesByIds([])` returns `[]` with no
  SQL round-trip.
- **`getMemoriesByIds` missing IDs:** an ID not in the DB is simply absent from
  the result list.
- **`updateMemory` removal regression:** the 6 removed test functions are gone
  and `make test` still passes (no dangling import of `updateMemory`).

### 7.2 Phase 2 tests

- **Cache miss → DB query:** cold cache, `getMemoriesByIds(["a","b"])` calls
  `db.userMemories.getMemoriesByIds(["a","b"])` once and returns both.
- **Cache hit → no DB:** warm cache (second call with the same IDs) does NOT
  call the DB.
- **Batch resolution:** a single miss batch covers multiple IDs in one DB query.
- **Missing IDs cached as `None`:** an ID absent from the DB is cached as `None`
  so a second call does not re-query.
- **Empty input:** `getMemoriesByIds([])` returns `{}` with no DB call.
- **No database wired:** `getMemoriesByIds(["a"])` returns `{"a": None}` (or
  `{}`) and logs, mirroring `getChatUserPermanentMemories`'s no-DB guard.

### 7.3 Phase 3 tests

- **New-format message resolves via cache:** an `EnsuredMessage` whose
  `metadata["memories"]` has `permanentIds`/`shortTermIds` and `userMemories is None`
  resolves to content after `await msg.resolveMemories(cache)`.
- **`resolveMemories` is a no-op when `userMemories` already set:** old-format
  message (content inline) is untouched.
- **`resolveMemories` is a no-op when no memories metadata:** message with no
  `metadata["memories"]` is untouched.
- **`resolveMemories` is a no-op on second call:** after the first resolution,
  a second call does nothing (`userMemories` already populated).
- **`loadMemoriesMetadata` tolerates `None`:** passing `None` (the state
  reachable when a bypass site did `metadata.get("memories")` on a metadata dict
  lacking `"memories"`) leaves `userMemories` unset and raises no `TypeError` —
  regression guard for the old `"permanentIds" in None` crash.
- **`handleMention` text-reply bypass resolves:** a stored reply whose
  `metadata["memories"]` is the compact ID form, loaded via the rewritten
  `:722` bypass (`loadMemoriesMetadata`), leaves `userMemories=None` until
  `resolveMemories` is called, then renders content correctly — i.e. the ID
  list is **never** rendered as the `userMemories` block.
- **`injectMemories` writes compact metadata:** after `injectMemories`, the
  ensured message's `metadata["memories"]` has `permanentIds`/`shortTermIds`
  (not `permanent`/`shortTerm` content) AND `userMemories` has the resolved
  content (for the current turn).
- **`injectMemories` strips `id` from injected content:** after `injectMemories`,
  no entry in `userMemories["permanent"]` carries an `id` key (the uuid stays
  only in `metadata["memories"]["permanentIds"]`). Regression guard against
  leaking uuids into the LLM prompt.
- **`injectMemories` `keepId=True` for permanent:** the permanent cache loader
  now sets `id` on each entry, so `permanentIds` is non-empty for a user with
  permanent memories.
- **Mixed thread (old + new messages):** a thread containing one old-format
  message (content inline) and one new-format message (IDs) renders both
  correctly via `getThreadByMessageForLLM` — the old one via inline content, the
  new one via `resolveMemories`.
- **`formatForLLM` output identical:** for the same resolved content, the JSON
  `userMemories` block is byte-identical between old-format and new-format
  messages (regression guard on the read path).
- **Batch resolution issues one DB query:** `resolveMemoriesBatch` on a list of
  N new-format messages referencing overlapping IDs issues a single
  `getMemoriesByIds` (one miss-batch), not N.
- **Coverage guard (AST-based):** a test that walks the AST of every
  `fromDBChatMessage(...)` call whose `injectMemories` argument is not the
  literal `False`, AND every `setUserMemories(` call whose argument is derived
  from message metadata, and asserts each is followed (in its enclosing
  function) by a `resolveMemories`/`resolveMemoriesBatch` call before any
  `toModelMessage`/`toModelMessageList`/`formatForLLM`/`generateText` render.
  This is the structural guard against silently forgetting a resolution site
  (see §8). A plain grep for `injectMemories=True` does **not** work — no
  production site uses the literal `True`.

---

## 8. Known limitations / deferred

- **Prompt hoisting (permanent → system message)** — future feature. This plan
  stores memories compactly, which is a prerequisite for hoisting, but memories
  still attach per-message (resolved from cache). Hoisting is a separate plan.
- **GC for soft-deleted memories** — deferred. The `user_memories` table grows
  over time as memories are soft-deleted. If GC becomes necessary, the shape
  is: hard-delete soft-deleted memories older than N days that no live message
  references (messages would also need to be older than N, since a historical
  message referencing a GC'd memory would resolve to `None` and silently drop
  from the rendered memory block). Note: implementing this safely requires a
  join against `chat_messages.metadata` to check ID references, which is
  non-trivial over JSON TEXT — track as a follow-up.
- **`getMemoriesByIds` routes to the default DB only** (no `dataSource`/
  `chatId` routing) — fine for single-DB production; a multi-DB deployment would
  need the caller to pass routing info. The UUID is globally unique, but the
  *row* lives in exactly one DB; in a sharded setup `getMemoriesByIds` would
  have to fan out across providers.
- **`updateMemory` removed** — future content changes via `deleteMemory` +
  `addMemory` (the dedup state machine already handles "similar exists →
  delete-old + re-add"). No in-place PATCH path.
- **Score field absent for new-format messages** — old messages may carry a
  `score` in their inline snapshots (from the semantic-search path at inject
  time); new messages resolve via `getMemoriesByIds`, which does not compute
  score. The LLM does not consume `score` (it is a search-ranking field), so
  this is not a behaviour change in practice. If `score` is ever needed on the
  read path, `getMemoriesByIds` would have to be extended — not in scope.
- **Backward compat without backfill** — old messages keep their content
  snapshots indefinitely. They work correctly but don't benefit from the
  compaction. A future backfill could extract IDs from old snapshots and
  rewrite `metadata` to the compact form — but the old snapshot content would
  first have to be matched back to a `user_memories` row by content (lossy),
  so this is fragile and noted only as optional.
- **Forgetting a `resolveMemories` site silently drops memories.** Any future
  read path that builds an `EnsuredMessage` from stored data and renders it for
  the LLM — whether via `fromDBChatMessage(..., injectMemories=<truthy>)` or via
  a `setUserMemories(metadata-derived)` bypass (the `llm_messages.py:722` shape)
  — must call `resolveMemories`/`resolveMemoriesBatch` before rendering, or the
  compact-format message renders with no `userMemories`. The Phase 3 wiring
  covers all current sites (§5.2.3); the AST-based coverage guard in §7.3
  enforces it going forward. Note: a plain `grep injectMemories=True` does NOT
  work as a guard — no production site uses the literal `True` (all pass a bool
  variable or an inline `.toBool()`); the guard must be AST-based and must also
  cover the `setUserMemories(metadata-derived)` bypass shape.
- **Permanent-cache invalidation unchanged.** `delete_memory` (the refinement
  tool) calls `invalidateChatUserPermanentMemories`, which drops the permanent
  cache entry so the next `getPermanentMemories` re-queries. Under soft-delete
  that re-query now filters `deleted_at IS NULL`, so a soft-deleted memory is
  excluded from the freshly-loaded permanent cohort — no change needed to the
  invalidation flow. (Noted explicitly so a reader doesn't worry that
  soft-delete + the permanent cache interact badly.)

---

## 9. AGENTS.md compliance notes

This plan honours the hard rules in [`AGENTS.md`](../../AGENTS.md) and the
deeper guide in [`docs/llm/index.md`](../llm/index.md):

- **camelCase** identifiers (`memoryIds`, `permanentIds`, `shortTermIds`,
  `getMemoriesByIds`, `resolveMemories`); **PascalCase** classes
  (`Migration021UserMemoriesSoftDelete`); **UPPER_CASE** constants
  (`CacheNamespace.MEMORIES_BY_ID`). The `permanentIds`/`shortTermIds` **dict
  keys** are camelCase here because they are application-level identifiers
  consumed by Python code (not DB columns) — this differs from the snake_case
  convention for `UserMemoryDict` keys that map to columns (see the amendment
  note in `user-memories-v1.md` §5.4: "AGENTS.md's camelCase rule governs Python
  *identifiers*, not dict string keys that map to columns"). These metadata keys
  are identifiers, so camelCase is correct.
- **SQL portability:** no `AUTOINCREMENT`/`SERIAL` (N/A — additive nullable
  column); `:named` placeholders throughout (`getMemoriesByIds` uses the
  `:id0, :id1, ...` expansion already proven in `_semanticSearchMemories`);
  portable `TIMESTAMP` type; **no `DEFAULT CURRENT_TIMESTAMP`** (the soft-delete
  timestamp is set application-side via `dbUtils.getCurrentTimestamp()`); all
  SQL goes through `BaseSQLProvider` (`getProvider`/`executeFetchAll`), never
  raw `sqlite3`.
- **`StrEnum`:** `CacheNamespace` is already a `StrEnum` (`cache/models.py:38`);
  the new `MEMORIES_BY_ID` member follows the existing shape. No `Literal[...]`.
- **Docstrings:** every new method (`getMemoriesByIds` on the repo and on
  `CacheService`, `loadMemoriesMetadata`/`resolveMemories`/`resolveMemoriesBatch`
  on `EnsuredMessage`) carries a docstring with `Args:`/`Returns:` describing
  all params and the return type, per the AGENTS.md "Docstrings required" rule.
- **Type hints** on all params/returns; **no `Any`** (`Dict[str, Optional[SingleMemoryDict]]`,
  `List[str]`, `List[UserMemoryDict]`, `Optional[Dict[str, object]]`,
  `List["EnsuredMessage"]`, `None`). (`object` is the concrete root type, not
  `Any` — used for `loadMemoriesMetadata`'s raw-metadata param, which is a dict
  of mixed value types.)
- **Migration numbering:** 021 is the next free number (verified: latest is
  `migration_020_user_memories.py`). Scaffold via the `add-database-migration`
  skill.
- **Tests under `tests/`:** no collocated tests in `lib/` or `internal/`. Repo
  tests extend `tests/database/repositories/test_user_memories.py`; cache tests
  under `tests/services/cache/`; ensured-message tests under `tests/bot/models/`
  (confirm exact path at implementation time).
- **Regression tests on every bug fix / behaviour change:** the soft-delete
  change to `deleteMemory` is a behaviour change that gets a regression test
  (row survives, live reads skip it). The `updateMemory` removal is verified by
  the test suite passing after the 6 functions are deleted.
- **No pydantic:** `SingleMemoryDict`/`UserMemoryDict` are `TypedDict`s; the
  compact metadata is a raw dict. No change to this convention.
- **Singletons via `Service.getInstance()`:** `CacheService.getInstance()` is
  the access pattern; `getMemoriesByIds` is a method on it. No change.
- **`./venv/bin/python3`** for any script; `make format lint` before AND after
  edits; `make test` after every phase.
