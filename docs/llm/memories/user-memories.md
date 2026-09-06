---
category: reference
---

# User Memories (v1) — Task Memory

Durable implementation notes for the **unified per-`(chat, user, thread)`
structured memory system** that replaced the legacy rolling-bio summary.
Implemented from [`docs/archive/plans/user-memories-v1.md`](../../archive/plans/user-memories-v1.md)
(authoritative spec). This doc is the canonical durable summary; the plan is
the implementation record and [`../architecture.md`](../architecture.md)
ADR-016 carries the architecture decision (the unified store + vec0 + tools),
building on ADR-014's refinement machinery (cron + global lock). The
memory-compaction-v1 change (compact per-message storage + by-id cache +
soft-delete) is recorded in [`../../archive/plans/memory-compaction-v1.md`](../../archive/plans/memory-compaction-v1.md)
and ADR-017.

This system **supersedes** the rolling-bio subsystem documented in
[`user-memory-refinement.md`](user-memory-refinement.md) (that doc is kept as
a historical snapshot — see its SUPERSEDED banner for what carried over).

## Overview

Every durable fact, preference, event, relationship, or high-level bio note
about a user lives as one row in the `user_memories` table, tagged with a
`MemoryType` discriminator and a freeform `tags` set. Two classes of memory:

- **Permanent** (`permanent = 1`) — always injected into the user's
  messages, capped at `PERMANENT_INJECTION_CAP = 10` per `(chat, user)`.
  Includes the maintained `type=bio` summary (one per thread) and
  cross-thread facts (e.g. `user_data`-migrated rows, `thread_id IS NULL`).
- **Ephemeral** (`permanent = 0`) — retrieved per turn, newest- or
  relevant-mode, capped at `EPHEMERAL_RETRIEVAL_LIMIT = 5`.

Each memory carries a vector embedding in a vec0 virtual table
(`vec_user_memories_{dim}`) so memories are **searchable and
de-duplicated** via cosine similarity. Three LLM tools let the model manage
memories itself: `add_memory`, `delete_memory`, `search_memories`.

Owner handler: `UserMemoriesHandler` (`internal/bot/common/handlers/user_memories.py`)
owns the three LLM tools, the refinement cron, and the regen cron. **Injection**
is centralised in `MessagePreprocessorHandler.injectMemories()`
(`internal/bot/common/handlers/message_preprocessor.py`) at message-arrival
time (see "Injection"). Schema: `migration_020_user_memories`. Repository:
`UserMemoriesRepository` (`internal/database/repositories/user_memories.py`).

## Schema

### `user_memories` table (`migration_020`)

| Column | Type | Notes |
|---|---|---|
| `chat_id` | INTEGER NOT NULL | PK part. |
| `user_id` | INTEGER NOT NULL | PK part. |
| `thread_id` | INTEGER | `NULL` = cross-thread (migration-backfilled `user_data` facts). Tool-created memories — permanent or ephemeral — are scoped to the current thread (Amendment #7). |
| `memory_id` | TEXT NOT NULL | App-generated `uuid.uuid4().hex`; unique within `(chat_id, user_id)`. |
| `type` | TEXT NOT NULL | `MemoryType` value (`bio`/`preference`/`fact`/`event`/`relationship`). |
| `content` | TEXT NOT NULL | Free-text body; source of truth for re-embedding. |
| `tags` | TEXT NOT NULL DEFAULT `'[]'` | JSON-encoded list of freeform tag strings. |
| `permanent` | INTEGER NOT NULL DEFAULT `0` | Boolean-as-int (`0`/`1`). |
| `source` | TEXT NOT NULL DEFAULT `'refinement'` | Provenance: `refinement` \| `chat` \| `migration` \| `user`. |
| `model_id` | INTEGER | `NULL` = not yet embedded. FK into the `models` lookup table (`migration_025_embedding_model_lookup`); replaces the former `embedding_model`/`embedding_dimensions` pair — the model name + dimensions are resolved once via the constructor-injected `modelIdResolver` and cached on the `model_id` side. |
| `created_at` | TIMESTAMP NOT NULL | Set application-side (no `DEFAULT CURRENT_TIMESTAMP`). |
| `updated_at` | TIMESTAMP NOT NULL | Set application-side; bumped on every write. |
| `deleted_at` | TIMESTAMP NULL | Soft-delete timestamp (migration 021). Set application-side in `deleteMemory` via `dbUtils.getCurrentTimestamp()` (no DB default). `NULL` = live; non-`NULL` = soft-deleted (row survives for historical reads; every live read filters `AND deleted_at IS NULL`). |

- **Primary key:** composite natural key `(chat_id, user_id, memory_id)` —
  no `AUTOINCREMENT` (cross-RDBMS portability, AGENTS.md). `deleted_at` is **not**
  part of the key and has no index — `AND deleted_at IS NULL` is a cheap residual
  predicate on the already-indexed `(chat_id, user_id, ...)` row set.
- **Indexes (3):** `idx_user_memories_chat_user_thread`
  `(chat_id, user_id, thread_id, updated_at DESC)`,
  `idx_user_memories_chat_user_permanent`
  `(chat_id, user_id, permanent, updated_at DESC)`,
  `idx_user_memories_type` `(chat_id, user_id, type)`.
- **No BLOB embeddings table.** Since `migration_025_embedding_model_lookup`, both `user_memories` AND `chat_messages` share this property — the `message_embeddings` BLOB side table was dropped. Embeddings live **only** in vec0; the embedding model is tracked via `model_id` (FK into the `models` lookup table) on `user_memories` itself (the chat-search side stores `model_id` on `chat_messages`). Semantic search is vec0-only (no numpy fallback) — when vec0 is unavailable, `searchMemories` returns `[]`.

### vec0 virtual table `vec_user_memories_{dim}`

- **Lazy-created at runtime** by
  `UserMemoriesRepository._upsertVecMemoryEmbedding` on first write of a
  given dimension (mirror of `_upsertVecMessageEmbedding` in
  `chat_embeddings.py`). **NOT created by the migration.**
- Carries denormalised metadata columns (`chat_id`, `user_id`, `model_id`
  partition keys, `permanent`) plus the `embedding`
  vector column with cosine distance metric. The `model_id` partition key
  (INTEGER FK into the `models` lookup table added in `migration_025`; was
  TEXT `model` pre-migration) scopes vectors per embedding model so a model
  swap does not pollute one model's vector space with another's.
- `thread_id` and `type` are deliberately NOT carried in vec0 (they
  were previously written as denormalised copies but never read back for
  filtering, search, or deletion). The JOIN step in
  `_semanticSearchMemories` applies both filters on the authoritative
  `user_memories` columns. `permanent` is immutable post-creation so it
  is pushed into the vec0 filter directly; `model_id` is a partition key and
  is always part of the vec0 filter clause.

## Repository — `UserMemoriesRepository`

`internal/database/repositories/user_memories.py` (12 public methods in the
documented core set — the `/memory_config` wizard helpers `getMemory` /
`getDistinctTags` are tracked separately; all SQL goes through
`BaseSQLProvider` and rows decode via
`dbUtils.sqlToTypedDict(row, UserMemoryDict)`). Method params are camelCase;
dict keys are snake_case to match columns.

### Write and read methods

- **Writes:** `addMemory` (INSERT — requires `embedding: Optional[List[float]]`,
  `embeddingModel: Optional[str]`, and `source: UserMemorySource`; `threadId`
  is keyword-only; embeds during add when both `embedding` and `embeddingModel`
  are provided), `deleteMemory` (SOFT DELETE — sets `deleted_at` + bumps
  `updated_at`, drops the vec0 row, nulls `model_id`; unrestricted — may target a permanent memory). There
  is no in-place PATCH: content changes go through `deleteMemory` + `addMemory`
  (the dedup state machine in `add_memory` already handles the "similar exists →
  delete-old + re-add-updated" path via the refinement LLM).
- **Reads:** `getPermanentMemories` (cross-thread `NULL` + this-thread
  permanent, newest-updated-first, capped at `PERMANENT_INJECTION_CAP`),
  `getLatestMemories` (ephemeral-only, newest-updated-first, capped at
  `EPHEMERAL_RETRIEVAL_LIMIT`),
  `getMemoriesByIds(memoryIds: List[str], *, chatId: Optional[int] = None,
  dataSource: Optional[str] = None)` (the single read path that does NOT
  filter `deleted_at` — resolves UUIDs to content for historical message
  reconstruction; no `chatId`/`userId` scoping in the WHERE clause since UUIDs
  are globally unique; `chatId`/`dataSource` are routing-only — forwarded to
  `getProvider(chatId=..., dataSource=..., readonly=True)`; default `None` →
  default DB). Every live read method adds `AND deleted_at IS NULL` so
  soft-deleted rows are skipped on the live injection/search path.

### Search and embedding methods

- **Search:** `searchMemories` — filter-only (`queryEmbedding is None`, plain
  SQL scan, `score = 0.0`) and semantic (`queryEmbedding` is a `List[float]`,
  vec0 native, `score = 1.0 - distance`). `embeddingModel: str` is required
  (keyword-only — pass `None` for filter-only mode); it replaces the old
  `dimensions: int` arg. Internally the `(modelName, dimensions)` pair is
  resolved to a `model_id` via the constructor-injected `modelIdResolver`
  (D10 — handler-facing signatures are unchanged). Always scoped to
  `chat_id = :chatId AND user_id = :userId` — no cross-user leaks. The vec0
  filter clause includes `model_id = :modelId` (per-model scoping) plus the
  immutable `permanent` flag. `tags` is applied as a portable SQL `LIKE`
  filter (`tags LIKE '%"tagN"%'`, ANY-match) — the `tags` column is stored as
  JSON TEXT via provider auto-serialization of the Python list. In semantic
  mode `threadId` / `type` are re-applied in a JOIN step on the authoritative
  `user_memories` columns (which also filters `deleted_at IS NULL`).
- **Embedding persistence:** `saveMemoryEmbedding` (takes `embeddingModel: str`
  + `List[float]`; resolves the model name to `model_id` via the injected
  `modelIdResolver`, lazy vec0 upsert + provenance UPDATE; vec0 write must
  succeed before provenance is set — a failure leaves `model_id = NULL`
  so the regen cron retries), `deleteMemoryEmbedding` (best-effort, iterates
  every `vec_user_memories_{N}`, never raises).
- **Model-drift regen helpers:** `getMemoriesWithoutEmbeddings` (single-table
  stale detection — also serves the initial backfill since a `NULL`
  `model_id` surfaces here; takes keyword-only `dimensions:
  Optional[int] = None` so rows embedded under a different dimensionality are
  re-surfaced — the dimensions arg is resolved internally to the candidate
  `model_id` set via `modelIdResolver`), `deleteObsoleteMemoryEmbeddings`
  (resets `model_id` to `NULL` + drops stale vec0 rows for rows whose model
  drifted; returns `int` and swallows exceptions → a silent failure mode). The two are a
  **complementary belt-and-suspenders pair**: `deleteObsoleteMemoryEmbeddings`
  is the destructive cleanup (regen step 5), and
  `getMemoriesWithoutEmbeddings(dimensions=currentDims)` (step 6) is the
  defensive re-surface that catches rows the destructive stage silently
  failed to reset. The `dimensions` param is **symmetric** with
  `getMessagesWithoutEmbeddings` in
  [`/internal/database/repositories/chat_embeddings.py`](/internal/database/repositories/chat_embeddings.py)
  (the message-search analog — a DIFFERENT file from the memory repo; both
  regen crons forward the current dimensionality so cross-dimensional drift
  is detected on each path).

### `deleteMemory` soft-delete semantics

`deleteMemory` soft-delete semantics: instead of hard-`DELETE`-ing the row,
`deleteMemory` runs `UPDATE user_memories SET deleted_at = :deletedAt,
updated_at = :updatedAt WHERE ... AND deleted_at IS NULL` and then calls
`deleteMemoryEmbedding(..., vecOnly=False)` — which drops the vec0 row AND
nulls `model_id` (so the regen cron never re-embeds a deleted memory and it is never a semantic-search hit). The content
row survives with `deleted_at` set so `getMemoriesByIds` (no `deleted_at`
filter) can still resolve it for historical reads. A re-delete of an
already-soft-deleted `memory_id` returns `False` (the existence pre-check is
scoped to the live row via `AND deleted_at IS NULL`). The whole body stays in
its never-raise `try/except` (returns `False` on any DB error). Vec0 columns
are written once at embed time and never edited, so there is no embedding-sync
trigger — content changes go through `deleteMemory` + `addMemory`.

## MemoryType

`internal/database/models.py` — `StrEnum` (AGENTS.md mandates `StrEnum`
over `Literal[...]`). It lives in the database layer (not
`internal/bot/models/`) so `UserMemoryDict` and the rest of
`internal.database` can reference it without an upward import into
`internal.bot.models` (which would create a startup-time circular import —
`internal.database` initialises before `internal.bot`). It is still
re-exported as `from internal.bot.models import MemoryType` for callers in
the bot layer:

- `BIO` (`"bio"`) — high-level evolving summary; exactly one permanent bio
  maintained per `(chat, user, thread)` by the refinement pass; the
  rolling-bio migration seeds it.
- `PREFERENCE` (`"preference"`) — stated/inferred preference.
- `FACT` (`"fact"`) — durable non-preferential fact.
- `EVENT` (`"event"`) — point-in-time happening.
- `RELATIONSHIP` (`"relationship"`) — connection to another person/entity.

Freeform categorisation beyond these is handled by the JSON `tags` column.

## Memory lifecycle

### Creation

1. **LLM tools** (chat-time + refinement): `add_memory` inserts a row with
   `source="chat"` or `source="refinement"`.
2. **Refinement pass** (`_runSingleRefinement`): the background LLM curates the
   store directly via the three tools (Phase 4a rewrite — see "Refinement").
3. **Migration backfill** (`migration_020`): legacy `user_data` → permanent
   cross-thread `fact`; legacy rolling-bio blob → permanent thread-scoped
   `bio` (see "Migration from old system").
4. **Manual (``/memory_config`` wizard)**: the "➕ Добавить память" button in
   the memory list starts a free-text-entry flow (`AddMemory` →
   `SetMemoryContent`). The user types the content; the wizard inserts an
   ephemeral (`permanent=False`), user-authored (`source="user"`) memory of
   the currently-selected `MemoryType`, with no embedding (the regen cron
   embeds it later). Only offered when a specific type is selected (not
   "all"), so the memory always inherits a concrete type.

### Retrieval

- **Injection** — `MessagePreprocessorHandler.injectMemories()` loads
  permanent + ephemeral at message-arrival time. Since the memory-compaction-v1
  change, the message's `metadata["memories"]` stores **compact memory IDs**
  (`{"permanentIds": [...], "shortTermIds": [...]}`) rather than full content.
  Since the context-dedup change (ADR-018), resolution is **lazy** — there is no
  per-message content field; `formatForLLM` resolves the IDs → content on-demand
  via the `MEMORIES` cache at render time, and renders each memory **exactly once
  per context** (newest→oldest dedup). `formatForLLM` builds the resolved block
  into a LOCAL dict and emits it under JSON key `userMemories` (see
  "Render-time resolution (lazy + dedup)").
- **`search_memories` tool** — the chat LLM can call `search_memories` to
  look up prior memories on demand (semantic or filter-only).

### Dedup state machine (`add_memory`)

`add_memory` optionally embeds the candidate content and runs a
`searchMemories(limit=1)` for near-duplicates, then:

| Cosine similarity (top hit) | Action |
|---|---|
| `>= MEMORY_DEDUP_DUPLICATE_THRESHOLD` (`0.95`) | **duplicate** — no-op insert, returns `existing_memory_id`. |
| `> MEMORY_DEDUP_SIMILAR_THRESHOLD` (`0.85`) | **grey zone** — at refinement time (`isRefinement`) returns `similar_exists` so the LLM can merge/delete/re-add; at chat-time folds to `duplicate` (no mid-turn curation). |
| `<= 0.85` | **insert** — new row + best-effort embed. |

Dedup is **best-effort**: any embedding/search failure is caught and the
insert proceeds with no dedup (a transient embedding outage must never
prevent the memory from being stored).

### Regeneration (model-drift cron)

`_runMemoryEmbeddingRegen` in `UserMemoriesHandler` runs every 60s tick
(outside `_refineLock`) and mirrors `ChatSearchHandler._dtCronJob`
one-to-one, adapted for the single-store model:

1. **Chat discovery (in-memory)** — round-robin over
   `self._trackedChats: MutableSet[int]`, populated by `newMessageHandler`
   when it sees a message in a chat where memory embeddings are active
   (`MEMORY_ENABLED && EMBEDDINGS_ENABLED`). There is **no DB scan** —
   the previous DB-scan discovery (the deleted
   `ChatSettingsRepository` method that queried `chat_settings`) and that
   repository method were both removed. **Cold-start
   tradeoff (intentional):** `_trackedChats` is empty on restart and only
   grows from live inbound messages, so a chat with a pre-existing
   backlog that stays quiet after a restart is not backfilled until the
   next qualifying message arrives. **Eviction is one-way:** when a
   tracked chat's per-chat gate (step 3) fails, it is removed via
   `.discard()` and is not re-added until the next message — re-enabling
   embeddings on a chat does not repopulate the set on its own.
2. **Round-robin pick** — one chat per tick via `_memoryBackfillIndex`
   over `sorted(self._trackedChats)` (stable order across ticks).
3. **Per-chat gate (runtime re-validation)** — bail — and `.discard()`
   the chat from `_trackedChats` — when `MEMORY_ENABLED` or
   `EMBEDDINGS_ENABLED` is now explicitly false.
4. **Model resolution** — `EMBEDDING_MODEL`; bail when empty, unknown, or
   not embedding-capable.
5. **Stale cleanup (model-drift detection)** — when the in-memory
   `_memoryEmbeddingModelTracker[chatId]` differs from the resolved
   `modelKey` (`"modelName"` or `"modelName:dimensions"`), call
   `deleteObsoleteMemoryEmbeddings` (resets stale rows' `model_id` to
   `NULL`); advance the tracker unconditionally so cleanup fires once per
   model switch.
 6. **Stale detection** — `getMemoriesWithoutEmbeddings` (forwards
    `modelName` and `dimensions` so rows embedded under a different model or
    dimensionality are re-surfaced; `NULL` `model_id` rows surface
    here too, serving the initial backfill).
7. **Re-embed loop** — each `UserMemoryDict` re-embedded via
   `LLMService.generateEmbedding` (returns `(modelName, List[float])` or
   `None`) and persisted through `UserMemoriesRepository.saveMemoryEmbedding`
   with an inter-call sleep; `generateEmbedding` swallows its own failures
   (returns `None`, the loop skips the save).

Never raises — a regen failure never breaks the refinement body sharing the
same tick. Batch size: `[user-memory.thresholds].memory-reindex-batch-size`
(default `50`).

## LLM tools

Registered in `UserMemoriesHandler.__init__`, gated on the global
`[user-memory].enabled` kill switch (no registration when off → nothing
exposed via the chat-time `useTools` wildcard). Per-chat availability is
additionally controlled in `_sendLLMChatMessage`. All three are async,
never raise (errors → `{"done": False, "error": ...}`), and resolve chat
context from `extraData["ensuredMessage"]` (`recipient.id` / `sender.id` /
`threadId`).

### `add_memory` (`_llmToolAddMemory`)

Params: `content` (required), `type` (required, `MemoryType` value),
`tags` (optional, normalised to lowercase on insert), `permanent` (optional,
default false). Returns
`{"done": True, "action": "added"|"duplicate"|"similar_exists", ...}` on
success (see dedup state machine). `source` is set to `"refinement"` when
`extraData["isRefinement"]` is truthy, else `"chat"`. Best-effort embeds
after insert via `LLMService.generateEmbedding` +
`saveMemoryEmbedding` (never raises; regen cron picks up failures).

### `delete_memory` (`_llmToolDeleteMemory`) — refinement-only at chat time

Params: `memory_id` (by-id, takes precedence) or `query` (semantic), plus
optional `type` filter for the by-query path. **D3 gating** (plan §8.3): the
tool is registered globally, but `_sendLLMChatMessage` forces
`useTools[ToolName.DELETE_MEMORY] = False` on **every** chat-time turn, so it
is only ever callable from the refinement pass (which sets it to `True`).

- **By-id delete** — unrestricted; may target a permanent memory (explicit
  action). Best-effort vec0 cleanup via `deleteMemoryEmbedding`.
- **By-query delete** — embeds the query, `searchMemories(limit=5)`, deletes
  only matches with `score >= MEMORY_DEDUP_SIMILAR_THRESHOLD` (`0.85`). Each
  deletion is an explicit, query-driven action reviewed by the refinement
  LLM, so this path can also reach permanent memories.

### `search_memories` (`_llmToolSearchMemories`)

Params: `query` (optional — semantic when provided, filter-only when
omitted), `type`, `tags` (ANY-match), `limit` (default `20`, clamped to
`[1, MEMORY_SEARCH_MAX_LIMIT = 100]`), `permanent`, `user` (optional —
search a different user's memories instead of the caller's; accepts a login
with or without `@` or a numeric `user_id`; when the login cannot be
resolved, returns `{"done": False, "error": ...}` without searching).
Returns `{"done": True, "results": [...], "count": int}`. By default
searches the calling user's own memories; when `user` is provided, resolves
it via `BaseBotHandler._resolveUserId` (shared with `search_messages`) and
searches that user's memories. When no embedding model is available with a
`query`, falls back to filter-only.

## Injection

Injection is **centralised** in
`MessagePreprocessorHandler.injectMemories()` (`internal/bot/common/handlers/message_preprocessor.py`),
called once per inbound message **at arrival time** (inside
`newMessageHandler`, AFTER `saveChatMessage`). The previous
`BaseBotHandler._buildMemoriesBlock` / `_formatMemoriesBlock` /
`_injectMemoriesBlock` / `_safeEmbedQuery` helpers and the four
handler-level injection sites (`getThreadByMessageForLLM`, `handleMention`,
`handleRandomMessage`, `handleReply`) were **deleted** in the
refactoring — there is no longer a `<user-memories>` system-message block.

### Flow (`MessagePreprocessorHandler.injectMemories`)

The embedding (when needed) is generated **in `newMessageHandler`**, not inside
`injectMemories`. `newMessageHandler` computes `chatMemoriesEmbeddingsEnabled =
MEMORY_ENABLED && EMBEDDINGS_ENABLED` and, when that gate **plus non-empty
message text** holds, embeds the message inline via `generateEmbedding`. The
resulting vector (or `None`) is then passed into `injectMemories` as
`queryEmbedding`. With the ChatSettingsKey consolidation, memory embeddings
are active iff `MEMORY_ENABLED && EMBEDDINGS_ENABLED` (there is no separate
memory-embeddings toggle or retrieval-mode selector any more): when active,
`injectMemories` receives a query embedding and runs semantic retrieval; when
either flag is off, no query embedding is produced, so `injectMemories` is
called with `queryEmbedding=None` and degrades to `getLatestMemories` (latest
retrieval). Empty/whitespace message text skips the embedding block for the same reason
(no garbage vector) and likewise falls through to the `getLatestMemories`
fallback. The guard is on **formatted** text, not raw `messageText`:
`formatForLLM` injects a `<media-description>` for media-only messages, so
media-only messages DO produce a non-empty formatted string, get embedded, and
trigger semantic memory retrieval (the description is the searchable content).
Truly-empty messages (no text + no media) format to empty and skip embedding.

#### Injection steps

1. Bail when `MEMORY_ENABLED` is false.
2. **Permanent** — read from the write-through permanent-memories cache via
   `cache.getChatUserPermanentMemories(chatId, userId, threadId)`
   (cross-thread `NULL` + this-thread permanent, already capped at
   `PERMANENT_INJECTION_CAP = 10`, returned as `list[SingleMemoryDict]`).
3. **Ephemeral (short-term)** — chosen by `queryEmbedding` (produced upstream
   in `newMessageHandler`):
   - `queryEmbedding` is a vector (relevant mode, embeddings enabled,
     non-empty text, embedding succeeded) →
     `searchMemories(queryEmbedding=<floats>, embeddingModel=<modelName>,
     permanent=False)` (vec0-ranked).
   - `queryEmbedding is None` (latest mode — `MEMORY_ENABLED` or
     `EMBEDDINGS_ENABLED` off / empty text / `generateEmbedding`
     returned `None` due to no model, rate limit, or provider error) →
     `getLatestMemories` (cap `EPHEMERAL_RETRIEVAL_LIMIT = 5`, ephemeral-only).
4. **Write compact IDs to `metadata["memories"]` (no cache warming).**
   `injectMemories` writes the compact `CompactMemoryIdsDict`
   `{"permanentIds": [...], "shortTermIds": [...]}` directly into
   `ensuredMessage.metadata["memories"]`, extracting the id of each entry:
   permanent entries come from the permanent-memories cache already shaped as
   `SingleMemoryDict` (the cache loader runs
   `convertDBMemoryToSingleMemoryDict(..., keepId=True)`, so each entry carries
   its `id`) and are read via `m.get("id")` — entries without a usable `id`
   are silently dropped; short-term entries are raw `UserMemoryDict` rows
   straight from `getLatestMemories` / `searchMemories` and are read via
   `m["memory_id"]`. No slimming happens inside `injectMemories` itself — the
   DB→`SingleMemoryDict` conversion for the by-id resolution path is deferred
   to `cache.getMemoriesByIds` at render time (see below).
   `injectMemories()` writes compact memory IDs into
   `ensuredMessage.metadata["memories"]` only (no cache warming); the by-id
   cache is populated lazily (cache-aside) on the first `formatForLLM` call
   via `cache.getMemoriesByIds`. The fetched content is NOT hung off the
   message — there is no `userMemories` content field any more (resolution is
   lazy, in `formatForLLM`; see "Render-time resolution (lazy + dedup)"). The
   `setUserMemories` setter method was removed in the context-dedup change
   (ADR-018).

#### Persistence and compaction context

`injectMemories()` is called inside `newMessageHandler` AFTER `saveChatMessage`;
the compact IDs are then re-persisted via a separate
`db.chatMessages.updateChatMessageMetadata(...)` call so they ride per message in
`chat_messages.metadata`. This is the memory-compaction-v1 change (see
[`docs/archive/plans/memory-compaction-v1.md`](../../archive/plans/memory-compaction-v1.md) and
[`../architecture.md`](../architecture.md) ADR-017): instead of persisting a
~2–3 KB full content snapshot per message (the permanent block being
byte-identical across a whole thread), each message carries just the UUID
lists. The context-dedup change (ADR-018) then made resolution **lazy**
(inside `formatForLLM`) and **deduplicated per rendered context** so each
memory renders once — see "Render-time resolution (lazy + dedup)".

> **TypedDict note:** the compact ID shape is typed as
> `CompactMemoryIdsDict` (`internal/bot/models/message_metadata.py`) —
> `{permanentIds: list[str], shortTermIds: list[str], shortTermScores?:
> dict[str, float]}`. The optional `shortTermScores` (mapping `memory_id ->
> score`) is populated ONLY in semantic-search mode and ONLY for the
> short-term cohort — see "Semantic-relevance score for short-term memories"
> below.
> `MetadataDict.memories` is typed as `CompactMemoryIdsDict` (the legacy
> `UserMemoriesDict` content-shape union member was removed once every live
> write path had migrated to compact IDs), so `sqlToCustomType` no longer
> needs to try multiple shapes and the `# type: ignore[assignment]`
> annotations that previously guarded the compact-metadata writes are gone.

### Render-time resolution (lazy + dedup)

Memory resolution moved out of load time entirely (ADR-018). There is no
`resolveMemories` method and no per-message `userMemories` content field any
more. When a message is formatted for the LLM, `EnsuredMessage.formatForLLM`
resolves the compact IDs **on-demand** in its JSON branch:

- `formatForLLM` / `toModelMessage` / `toModelMessageList` take **required**
  keyword-only `cache: Optional[CacheService]` and `excludeMemoryIds: Set[str]`
  (no defaults — pyright enforces every caller, so a forgotten `cache=` is a
  type error, not a silent memory drop). When `cache is None` (non-chat / TEXT
  paths) the `"userMemories"` JSON key is omitted entirely. When `cache` is
  provided, the JSON branch reads `permanentIds`/`shortTermIds` from
  `metadata["memories"]`, subtracts `excludeMemoryIds` from each cohort, then
  resolves the survivors via `cache.getMemoriesByIds(permanentIds + shortTermIds,
  chatId=self.recipient.id)` and renders the resolved entries into a LOCAL dict
  under JSON key `"userMemories"`. `self.metadata` is **never mutated** (the
  condense branch of `getThreadByMessageForLLM` persists `eRootMessage.metadata`
  to DB, so re-pointing it during render would corrupt the persisted compact
  IDs — the invariant ADR-017 deviation #1 established). When all referenced IDs
  fail to resolve (or none survive the exclude filter), the `"userMemories"` key
  is omitted entirely.

#### Dedup mechanics across render sites

- **Per-context dedup** is applied **inline at each call site** (no shared
  helper). Each site walks its message sequence newest→oldest, accumulating an
  exclude-set: for each message it applies `excludeMemoryIds = ownIds ∩ seen`
  (where `ownIds = getMemoryIds()`), then adds its own IDs to `seen`. The
  newest message renders its full memory set; each older message renders only
  memories not already shown by any newer message; each memory appears exactly
  once, at its latest (newest) occurrence. `getThreadByMessageForLLM` walks the
  tail messages newest→oldest into a `deque` (the `excludedMemoryIds` set
  accumulates each message's IDs); `handleRandomMessage` does the same across
  its history+current sequence. Condense-summary plain-text messages carry no
  memory blocks and never participate in dedup. Genuine single-message render
  sites (mention, image-prompt fallback) pass `excludeMemoryIds=set()` — the one
  message renders its full resolved set.
- **Condense-replay root exemption (accepted trade-off):** in the
  condense-replay branch of `getThreadByMessageForLLM`, the single
  `keepFirstN` (root) message is EXEMPT from dedup — it renders its full memory
  set (`excludeMemoryIds=set()`) to keep the assembly code simple. A memory
  present in both the root and a newer tail message may therefore appear twice
  (once at the root, once at its latest tail occurrence). The common
  (non-condensed) thread case is unaffected — there the root participates in
  the newest→oldest walk and deduplicates normally.

#### Compact-format support and render sites

Only the **compact format** (`{"permanentIds": [...], "shortTermIds": [...]}`)
is supported. Old-format messages (`{"permanent": [...], "shortTerm": [...]}`,
from before compaction) have no `permanentIds`/`shortTermIds` keys, so
`getMemoryIds` returns an empty set and they render with no memories (and log a
conversion warning until cleared by the cleanup script). A one-time cleanup
script
([`scripts/clear_old_format_memories.py`](../../../scripts/clear_old_format_memories.py))
removes stale old-format `memories` from `chat_messages.metadata` so the stored
payload does not carry dead data.

The render sites that pass `cache=self.cache` (gated on each site's
`MEMORY_ENABLED` condition, i.e. `cache=self.cache if needMemories
else None`) are: `getThreadByMessageForLLM`
(`base.py` — keepFirstN + tail render loops, with per-message `excludeMemoryIds`
accumulated inline newest→oldest), `handleMention` (`llm_messages.py`), the
`handleReply` fallback, `handleRandomMessage` (`llm_messages.py`), and the
image-prompt fallback in `draw_command` (`media.py`). Non-chat / TEXT callers
(some search/summarization/user-memories render paths) pass
`cache=None, excludeMemoryIds=set()` explicitly. A structural AST guard
([`tests/test_memory_resolution_coverage.py`](../../../tests/test_memory_resolution_coverage.py))
scans the render methods (`formatForLLM`/`toModelMessage`/`toModelMessageList`)
for the required `cache=`/`excludeMemoryIds=` keywords so a future caller cannot
silently drop memories.

> **By-id cache `keepId=False` invariant (unchanged):** the `MEMORIES` /
> `getMemoriesByIds` cache stores entries with `keepId=False`. The cache is the
> render-time resolver: entries are looked up by dict key (the key IS the id)
> and `formatForLLM` renders the content verbatim, so storing `id` would leak a
> uuid into the LLM prompt. The separate permanent-memories cache uses
> `keepId=True` so the write path (`injectMemories`) can extract `permanentIds`.

> **Empty-memories render difference:** a zero-memory compact-format message
> (empty `permanentIds`/`shortTermIds`) renders WITHOUT a `userMemories` block
> in `formatForLLM` (nothing resolves → the local dict stays `None` → the
> dict-comprehension drops the falsy value) — an improvement over the old
> format, which rendered an empty `{"permanent": [], "shortTerm": []}` block.

The memories seen by the model are therefore the snapshot known at the time
the message arrived — every message in a thread carries its own context, and
resolution happens lazily at render time (just a cache lookup of the persisted
IDs), deduplicated so each memory renders once per context.

### Semantic-relevance score for short-term memories

Each short-term memory retrieved via **semantic search** carries its
relevance score end-to-end into the rendered `userMemories` JSON block the
LLM sees. The score originates in `UserMemoriesRepository.searchMemories`
as `score = 1.0 - cosine_distance` (vec0 cosine metric) and is plumbed
injection → metadata → render without any extra DB/vector calls at render
time:

- **Injection** — `MessagePreprocessorHandler.injectMemories`, in the
  semantic branch (`queryEmbedding` is a vector), captures
  `{memory_id -> score}` from the `searchMemories` result and writes it
  into `ensuredMessage.metadata["memories"]["shortTermScores"]`. The key
  is OMITTED in latest-mode (`getLatestMemories`) fallback and never
  populated for permanent memories (permanent entries do not flow through
  `searchMemories` on the injection path).
- **Render** — `EnsuredMessage.formatForLLM` reads `shortTermScores` from
  `rawMemories` and, for each resolved short-term entry whose `memory_id`
  is in the map, merges `"score": <float>` into the entry via a shallow
  copy (`{**entry, "score": shortTermScores[mid]}`). The shallow copy is
  load-bearing: entries returned by `cache.getMemoriesByIds` are direct
  references into the LRU cache, so mutating one in place would leak the
  `score` into subsequent renders of other messages (the
  `test_cacheMutation_bug_shortTermScoresLeakBetweenCalls` regression
  locks this in). Permanent entries are NEVER scored (the loop only walks
  `shortTermIds`).

**Scoping rule (locked):** the score appears ONLY for
semantically-searched ephemeral memories. Permanent memories and
latest-mode (`getLatestMemories`) ephemeral memories OMIT the `score`
field entirely. The score is model-visible (lands in the `userMemories`
JSON block). Backward compatible: old persisted messages simply lack
`shortTermScores` → render omits `score` on those entries. No DB
migration was needed — the score is transient per-message metadata
carried in the existing JSON `metadata` column, not a stored column.

The `CompactMemoryIdsDict.shortTermScores: NotRequired[dict[str, float]]`
field in `internal/bot/models/message_metadata.py` is the typed surface
of this contract; the score is also a `NotRequired[float]` on
`SingleMemoryDict` (`"score"`) so it survives the round trip through the
by-id cache shape.

### Permanent-memories cache

The permanent cohort is served from a write-through cache in `CacheService`
rather than re-queried on every inbound message:

- `getChatUserPermanentMemories(chatId, userId, threadId)` →
  `list[SingleMemoryDict]` — lazily loads + memoises the permanent block for
  `(chatId, userId, threadId)`; the loader calls `getPermanentMemories` and
  converts via `convertDBMemoryToSingleMemoryDict(m, keepId=True)` so each
  entry carries its `id` (the write path needs the ids to build
  `permanentIds`; `injectMemories` then strips `id` from the injected content).
- `invalidateChatUserPermanentMemories(chatId, userId, threadId)` — drops the
  cached block so the next read re-queries. Called by the memory-write paths
  (`add_memory` / `delete_memory` / the refinement tools) so a freshly added
  permanent memory is visible on the next inbound message.

The old `getChatUserData` / `setChatUserData` / `unsetChatUserData` /
`clearChatUserData` cache methods (legacy `user_data` key-value blob) were
**deleted** (replaced by `getChatUserPermanentMemories` / `invalidateChatUserPermanentMemories` above); `invalidateChatUser(chatId, userId)` still exists but only `del`s
`userInfo` and intentionally preserves the permanent-memories cache. The
`HCChatUserCacheDict.data` field (which held the legacy `user_data` blob
alongside `userInfo`) is gone — the TypedDict body is just `permanentMemories`
+ `userInfo` now (the bridge methods that populated `data` were deleted in the
`85aa945` refactoring; five stale prose references in docstrings/comments were
cleaned up in the post-v1-retirement pass).

### By-id resolution cache (`MEMORIES`)

The render-time resolver. `CacheService.getMemoriesByIds(
memoryIds: List[str], *, chatId: Optional[int] = None, dataSource: Optional[str] = None
) -> Dict[str, Optional[SingleMemoryDict]]` is a cache-aside lookup in the
`CacheNamespace.MEMORIES` namespace (MEMORY_ONLY persistence — never written
to disk, cleared on process restart):

- Each requested ID is looked up in the namespace; misses are batch-queried
  via `db.userMemories.getMemoriesByIds(missingIds, chatId=chatId,
  dataSource=dataSource)` (which deliberately has NO `deleted_at` filter, so
  a soft-deleted memory still resolves to its preserved content — the whole
  point of soft-delete), converted via `convertDBMemoryToSingleMemoryDict`
  with the default `keepId=False`, and populated back into the cache.
- IDs not found in the DB are **negative-cached as `None`** so a repeated miss
  does not re-query.
- `chatId`/`dataSource` are **routing-only**: they tell the repo
  `getProvider(chatId=..., dataSource=..., readonly=True)` which data source
  to query on a miss. The cache key is the memory UUID (globally unique per
  DB), so a cache hit returns the correct content regardless of which source
  was originally queried. When both are `None` (the default), the default DB
  is queried. `formatForLLM` passes `chatId=self.recipient.id`.
- **No invalidation method exists** for this namespace: soft-delete preserves
  content (so a cached entry stays valid — there is no `updateMemory` to
  invalidate), `addMemory` does not invalidate a not-yet-cached entry, and
  process restart clears the cache naturally. The only writer to the cache is
  `getMemoriesByIds` itself (cache-aside on miss). Note: `warmMemoriesByIds`
  was planned (context-dedup plan v2 §5.3) but NOT shipped — `injectMemories`
  writes compact IDs only, so the by-id cache is populated lazily on the first
  `formatForLLM` call's cache miss into `getMemoriesByIds`.

### Code anchor: `getThreadByMessageForLLM`

The thread-assembly method in
[`/internal/bot/common/handlers/base.py`](/internal/bot/common/handlers/base.py)
(approximately `:646-832`; line numbers drift — re-locate by symbol) is the
primary multi-message render site for memory resolution. Its structure:

- **Branch A** (`rootMessageId is None`, standalone message) — single-row
  fetch, build + render the one `EnsuredMessage`, return immediately.
- **Branch B** (thread) — **upfront batch fetch** via
  `getChatMessagesByRootId` (all rows loaded before any render). The root
  `eRootMessage` is built from the first row but **never rendered for the
  LLM** — it only carries the `condensedThread` cache (read on entry,
  persisted on the condense path).
- **`keepFirstN` loop** — builds + renders the retained root-adjacent
  messages.
- **Main loop** — builds + renders the tail messages; per-message
  `excludeMemoryIds` accumulated inline newest→oldest (see "Render-time
  resolution").
- **Condense gate** — when the rendered context fits within the token
  budget, return immediately (no metadata write).
- **Condense path** — `condenseContext` replaces the assembled list; the
  condensed cache is written into `eRootMessage.metadata["condensedThread"]`
  and the **whole metadata dict** is persisted via
  `updateChatMessageMetadata` (approximately `:825-830`). This re-persistence
  is the reason `formatForLLM` must never mutate `self.metadata`: the
  condense path would write resolved content over the persisted compact IDs
  (the ADR-017 deviation #1 invariant — see "Render-time resolution").

`handleReply` delegates to this method; its own fallback builds from the
live incoming `EnsuredMessage` (no DB-row metadata path — covered by the
write-path `injectMemories`).

## Deferred (memory-compaction-v1 scope boundaries)

Two follow-up features are explicitly out of scope and noted as known
limitations (see [`docs/archive/plans/memory-compaction-v1.md`](../../archive/plans/memory-compaction-v1.md)
§8):

- **Prompt hoisting** (permanent block → a single system message). This change
  stores memories compactly per-message (a prerequisite for hoisting) but
  memories still attach per-message, resolved from cache at render time.
  Hoisting is a separate future feature.
- **GC for soft-deleted rows.** Soft-deleted rows accumulate in `user_memories`
  over time (the content survives for historical reads). If GC becomes
  necessary, the shape is: hard-delete soft-deleted memories older than N days
  that no live message references (the message-reference check is a non-trivial
  join over `chat_messages.metadata` JSON TEXT — tracked as a follow-up).

## Refinement (Phase 4a rewrite)

`UserMemoriesHandler._runSingleRefinement` was rewritten for the unified store. The
accounting / cron / locking machinery is **unchanged** from the rolling-bio
system (see [`user-memory-refinement.md`](user-memory-refinement.md)
"Concurrency model" — still accurate): `_dtCronJob` (60s tick), `_accounting`
counter (credit-consumed reset), `_refineLock` (single global lock), the
online top-K due-list by smallest `_lastRefinedTS`, the never-refined-not-
skipped rule, the bail-path TS reset.

**What changed:**

- **Pre-loads memories** — `getPermanentMemories` + `getLatestMemories` are
  fetched before the LLM call and rendered via `_formatMemoriesBlockRaw`
  into the `{existingMemories}` prompt placeholder (failures tolerated →
  empty list, so a transient DB error can't abort the run). Replaces the
  old `{existingUserData}` / `{existingSummary}` placeholders — those are
  **no longer supported**; a deployed per-chat override still carrying them
  raises `KeyError` (caught by the outer try/except, refinement stops for
  that user this tick).
- **Manages memories via tools** — `useTools` enables `ADD_MEMORY`,
  `DELETE_MEMORY`, `SEARCH_MEMORIES`, `SEARCH_MESSAGES`,
  `GET_CURRENT_DATETIME`. `extraData["isRefinement"] = True` so `add_memory`
  returns the `similar_exists` grey-zone signal (D5). Memories persist
  **live** via the tools during the LLM call.
- **No summary blob** — the rolling-bio `summary` is no longer written to
  `chat_users.metadata.memoryRefinement[threadId]`. Only the message cursor
  (`lastProcessedMessageId` / `lastProcessedMessageDate`) is persisted after
  the call (still via the read-modify-write + `chatUserMetadataLock()`
  pattern — see ADR-014/015). The `userSummary` field / `applyUserMetadata`
  reader / `formatForLLM` key were removed entirely in Phase 4b (no
  remaining writers/readers — see [`../../archive/plans/user-memories-v1.md`](../../archive/plans/user-memories-v1.md) §9.3).
- **Refinement now requires memory embeddings** — the scan gate is
  `MEMORY_REFINEMENT_ENABLED && MEMORY_ENABLED && EMBEDDINGS_ENABLED`;
  the dispatch re-checks all three per candidate and candidates failing
  the gate are dropped from `_accounting` / `_lastRefinedTS`. Rationale:
  refinement's `search_memories` LLM tool is semantic and returns nothing
  without embeddings, so refinement is only meaningful when memory
  embeddings are active (`MEMORY_ENABLED && EMBEDDINGS_ENABLED`). A chat
  with `MEMORY_REFINEMENT_ENABLED=true` but memory embeddings off will not
  refine. (`_runSingleRefinement`'s own runtime re-check is
  `MEMORY_REFINEMENT_ENABLED`-only — an intentional asymmetry; the
  per-candidate scan already enforced the memory+embeddings gates.)
- **JSONL log extended with tool-call counts** — when
  `[user-memory.json-logging].enabled`, `_writeRefinementJsonLog` writes one
  JSONL line per successful run. The `summary` field is now the LLM's raw
  text output (often empty, since the model emits tool calls instead of a
  dossier); the per-tool counts (`addCount` / `deleteCount` / `searchCount`,
  derived via `_countRefinementToolCalls` over `result.toolUsageHistory`) are
  the primary observability for the grey-zone dedup review.

The new prompt instructs the model to study the rendered recent messages,
`search_memories` for prior context, extract durable facts as discrete
memories via `add_memory`, maintain exactly one permanent `type=bio`
summary, and use `delete_memory` to remove stale/conflicting memories.

## Settings

### Chat settings (1 master gate — `page = ChatSettingsPage.FRIEND`)

Defined in `ChatSettingsKey` (`internal/bot/models/chat_settings.py`) with
metadata in `_chatSettingsInfo` (four-site convention — see
[`../tasks.md`](../tasks.md) §4.1). The formerly-separate injection toggle,
retrieval-mode selector, memory-embeddings toggle, and memory-regen trigger
were consolidated into a single master per-chat gate:

| `ChatSettingsKey` | TOML key | Type | Purpose |
|---|---|---|---|
| `MEMORY_ENABLED` | `memory-enabled` | BOOL | Master per-chat gate for ALL memory features. Gates `MessagePreprocessorHandler.injectMemories()` (the message-arrival injection of compact IDs into `EnsuredMessage.metadata.memories`) AND the chat-time availability of `add_memory` / `search_memories`. **Memory embeddings are active when `MEMORY_ENABLED && EMBEDDINGS_ENABLED`** (derived — no separate flag): semantic memory retrieval (`searchMemories` via `LLMService.generateEmbedding`) runs only when both are on, otherwise retrieval is `latest` (`getLatestMemories`), with a runtime semantic→latest fallback preserved on embedding-generation failure. The regen cron admits/evicts a chat on `MEMORY_ENABLED && EMBEDDINGS_ENABLED` (round-robins over the in-memory `_trackedChats` set populated by `newMessageHandler`, NOT a DB scan — the old `ChatSettingsRepository` discovery method was removed). `EMBEDDING_MODEL` is shared across message-search and user-memory vectors. Cold-start note: `_trackedChats` is empty on restart and only grows from live messages (intentional). |

The five refinement settings from the rolling-bio system are unchanged:
`MEMORY_REFINEMENT_ENABLED`, `MEMORY_REFINE_MODEL`,
`MEMORY_REFINE_FALLBACK_MODEL`, `MEMORY_REFINE_SYSTEM_PROMPT`,
`MEMORY_REFINE_USER_PROMPT_TEMPLATE`. Note: the refinement scan gate is
`MEMORY_REFINEMENT_ENABLED && MEMORY_ENABLED && EMBEDDINGS_ENABLED` — the
dispatch re-checks all three per candidate, because refinement's
`search_memories` LLM tool is semantic and returns nothing without
embeddings. A chat with `MEMORY_REFINEMENT_ENABLED=true` but memory
embeddings off will not refine. (`_runSingleRefinement`'s own runtime
re-check is `MEMORY_REFINEMENT_ENABLED`-only — an intentional asymmetry; the
per-candidate scan already enforced the memory+embeddings gates.)

### Config — `[user-memory]` (`configs/00-defaults/user-memory.toml`)

Read ONCE in `UserMemoriesHandler.__init__` and cached as instance attributes
(the cron hot path and `_runSingleRefinement` perform no `configManager.get(...)`
calls). Defaults live in `configs/00-defaults/user-memory.toml`:

- `[user-memory].enabled` — global kill switch (default `false`); also gates
  tool registration.
- `[user-memory.thresholds]` — `message-count` (5), `time-seconds` (21600),
  `min-messages-to-refine` (5), `max-messages-per-run` (128),
  `max-refines-per-tick` (3), `memory-reindex-batch-size` (50, regen cron).
- `[user-memory.json-logging]` — `enabled` (false) / `file`
  (`logs/user-memory-refinement-json.log`) / `add-date-suffix` (true).

See [`../configuration.md`](../configuration.md) §`[user-memory]`.

## Migration from old system (`migration_020`)

Two backfills run as Python loops inside `up()` (the `memory_id` is an
app-generated UUID — never delegated to the DB). Both are idempotent via a
sentinel probe (`source='migration' AND type=...`) so a crash-mid-backfill +
restart does not insert duplicates:

- **Backfill A — `user_data` → permanent cross-thread `fact`.** Each legacy
  `(user_id, chat_id, key, data)` row becomes a permanent `type='fact'`
  memory with `thread_id=NULL` (cross-thread — `user_data` has no thread
  concept), content `"{key}: {data}"`, empty tags, `source='migration'`,
  NULL embedding columns. Original timestamps preserved. The `user_data`
  **table** was kept at `migration_020` time for rollback safety but was later
  DROPPED by `migration_022` once the v2 system was confirmed stable (see
  "Post-v2 cleanup & deploy migrations" below); the tools that wrote it
  (`add_user_data` / `delete_user_data`) were retired in Phase 5a.
- **Backfill B — rolling-bio → permanent thread-scoped `bio`.** Each
  `chat_users.metadata.memoryRefinement[str(threadId)]` entry with a
  non-empty `summary` becomes a permanent `type='bio'` memory scoped to the
  original thread (`thread_id=<thread>`), `tags=["migrated_bio"]`,
  `source='migration'`. Summary text preserved verbatim in `content`.

The old `userSummary` injection path was **removed entirely** in Phase 4b:
`EnsuredMessage.applyUserMetadata`, the `userSummary` field, and the
`formatForLLM` `userSummary` key are gone (the `chat-prompt-suffix` line
documenting the `userSummary` JSON field was dropped in the same phase). The
stale rolling-bio blob in `chat_users.metadata` is left unread — the
per-message compact memory IDs (injected at arrival time and persisted in
`chat_messages.metadata.memories`) fully replace it. See
[`../../archive/plans/user-memories-v1.md`](../../archive/plans/user-memories-v1.md) §9.3 for
the decision record.

## Post-v2 cleanup & deploy migrations

After the v2 `user_memories` system shipped and the ChatSettings
consolidation landed, three deploy artifacts cleaned up the legacy surface:

- **`migration_022` (`migration_022_drop_user_data.py`)** — drops the legacy
  `user_data` table once the `migration_020` backfill was confirmed stable.
  `up()` is `DROP TABLE IF EXISTS user_data` via `provider.batchExecute`;
  `down()` re-creates the EMPTY table (post-`migration_013` shape —
  `user_id`/`chat_id INTEGER NOT NULL`, `key`/`data TEXT NOT NULL`,
  `created_at`/`updated_at TIMESTAMP NOT NULL`,
  `PRIMARY KEY (user_id, chat_id, key)`; no `AUTOINCREMENT`, no
  `DEFAULT CURRENT_TIMESTAMP`, portable types) for STRUCTURAL reversibility
  only (data is unrecoverable). `UserDataRepository` and the `db.userData`
  accessor were deleted in the same pass (replaced by `UserMemoriesRepository`
  / `db.userMemories`). The `migration_020` backfill
  descriptions (which read FROM `user_data`) remain accurate as historical
  record.
- **`migration_023` (`migration_023_rename_memory_injection_enabled_to_memory_enabled.py`)**
  — pure DATA migration (no DDL) from the ChatSettings consolidation: renames
  the persisted `memory-injection-enabled` key to `memory-enabled` via
  `UPDATE chat_settings SET key=:newKey WHERE key=:oldKey` through
  `provider.batchExecute`. Idempotent and down-reversible (factored
  `OLD_KEY`/`NEW_KEY` constants).
- **[`/scripts/prune_unknown_chat_settings.py`](/scripts/prune_unknown_chat_settings.py)**
  — drops persisted rows for removed `ChatSettingsKey` members (the four
  consolidation casualties and any future-unknown keys). Reads the valid set
  live from `ChatSettingsKey` (`{member.value for member in ChatSettingsKey}`);
  supports `--dry-run` (`dest="dryRun"`). Run order: deploy new code
  (migration 023 auto-runs at startup and renames the key) → stop the bot →
  run the prune script → restart (the stop avoids a TOCTOU race with live
  setting writes). Follows `clear_memory_refinement.py` conventions.

## Cross-references

- [`../../archive/plans/user-memories-v1.md`](../../archive/plans/user-memories-v1.md) —
  authoritative implementation spec (planning document, amended post-impl).
- [`../../archive/plans/memory-compaction-v1.md`](../../archive/plans/memory-compaction-v1.md)
  — the compact-ID storage + by-id cache + soft-delete change (status:
  IMPLEMENTED). This doc's "Injection" / "Render-time resolution (lazy + dedup)"
  / "By-id resolution cache" sections summarise it; see ADR-017 for the decision.
  [`../../archive/plans/memories-context-dedup-plan-v1.md`](../../archive/plans/memories-context-dedup-plan-v1.md)
  / [`memories-context-dedup-plan-v2.md`](../../archive/plans/memories-context-dedup-plan-v2.md)
  — the lazy-resolution + per-context-dedup change (status: IMPLEMENTED); see
  ADR-018.
- [`../architecture.md`](../architecture.md) ADR-016 — unified
  `user_memories` store decision (structured memories + vec0 + tool
  self-management + centralised arrival-time injection); ADR-017 — compact-ID
  per-message storage + by-id cache + soft-delete; ADR-018 — context
  deduplication (lazy render-time resolution + newest→oldest per-context dedup).
  ADR-014 covers the
  background refinement machinery (cron + global lock + accounting) that
  still governs `_runSingleRefinement`; ADR-015 covers the `chat_users` cache used
  by the cursor persist.
- [`user-memory-refinement.md`](user-memory-refinement.md) — the predecessor
  rolling-bio subsystem (SUPERSEDED, kept as historical context).
- [`../handlers.md`](../handlers.md) `UserMemoriesHandler` row;
  [`../configuration.md`](../configuration.md) §`[user-memory]`;
  [`../database.md`](../database.md) for migration patterns.

## Semantic Relevance Score (2026-08-11)

- **User-memories relevance score (2026-08-11, IMPLEMENTED):** Ephemeral ("short-term") memories now carry a semantic-relevance score through to the LLM context. Contract: score originates in `UserMemoriesRepository.searchMemories` as `score = 1.0 - cosine_distance` (vec0 COSINE); `MessagePreprocessorHandler.injectMemories` captures `{memory_id -> score}` into `metadata["memories"]["shortTermScores"]` in semantic-search mode ONLY; `EnsuredMessage.formatForLLM` merges it into resolved short-term `SingleMemoryDict` entries (by `mid`, via shallow copy — see gotcha above). Scoping: semantic ephemeral ONLY — permanent memories and latest-mode (`getLatestMemories`) ephemeral never carry a score; the field is simply absent. No DB migration (score is transient per-message JSON metadata). Tools (`search_memories`/`add_memory`) already returned score pre-feature. Docs: `docs/llm/memories/user-memories.md`, `memories-context-dedup.md`. Terminology: code says "ephemeral" (`permanent = 0`) = user-facing "short-term".
