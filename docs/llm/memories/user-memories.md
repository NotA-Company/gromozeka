# User Memories (v1) — Task Memory

Durable implementation notes for the **unified per-`(chat, user, thread)`
structured memory system** that replaced the legacy rolling-bio summary.
Implemented from [`docs/plans/user-memories-v1.md`](../../plans/user-memories-v1.md)
(authoritative spec). This doc is the canonical durable summary; the plan is
the implementation record and [`../architecture.md`](../architecture.md)
ADR-016 carries the architecture decision (the unified store + vec0 + tools),
building on ADR-014's refinement machinery (cron + global lock).

This system **supersedes** the rolling-bio subsystem documented in
[`user-memory-refinement.md`](user-memory-refinement.md) (that doc is kept as
a historical snapshot — see its SUPERSEDED banner for what carried over).

## Overview

Every durable fact, preference, event, relationship, or high-level bio note
about a user lives as one row in the `user_memories` table, tagged with a
`MemoryType` discriminator and a freeform `tags` set. Two classes of memory:

- **Permanent** (`permanent = 1`) — always injected into the chat system
  message, capped at `PERMANENT_INJECTION_CAP = 10` per `(chat, user)`.
  Includes the maintained `type=bio` summary (one per thread) and
  cross-thread facts (e.g. `user_data`-migrated rows, `thread_id IS NULL`).
- **Ephemeral** (`permanent = 0`) — retrieved per turn, newest- or
  relevant-mode, capped at `EPHEMERAL_RETRIEVAL_LIMIT = 5`.

Each memory carries a vector embedding in a vec0 virtual table
(`vec_user_memories_{dim}`) so memories are **searchable and
de-duplicated** via cosine similarity. Three LLM tools let the model manage
memories itself: `add_memory`, `delete_memory`, `search_memories`.

Owner handler: `UserDataHandler` (`internal/bot/common/handlers/user_data.py`).
Schema: `migration_020_user_memories`. Repository:
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
| `embedding_model` | TEXT | `NULL` = not yet embedded. |
| `embedding_dimensions` | INTEGER | `NULL` = not yet embedded. |
| `created_at` | TIMESTAMP NOT NULL | Set application-side (no `DEFAULT CURRENT_TIMESTAMP`). |
| `updated_at` | TIMESTAMP NOT NULL | Set application-side; bumped on every write. |

- **Primary key:** composite natural key `(chat_id, user_id, memory_id)` —
  no `AUTOINCREMENT` (cross-RDBMS portability, AGENTS.md).
- **Indexes (3):** `idx_user_memories_chat_user_thread`
  `(chat_id, user_id, thread_id, updated_at DESC)`,
  `idx_user_memories_chat_user_permanent`
  `(chat_id, user_id, permanent, updated_at DESC)`,
  `idx_user_memories_type` `(chat_id, user_id, type)`.
- **No BLOB embeddings table.** Unlike chat-history search, embeddings live
  **only** in vec0; `embedding_model`/`embedding_dimensions` are tracked on
  `user_memories` itself. Semantic search is vec0-only (no numpy fallback) —
  when vec0 is unavailable, `searchMemories` returns `[]`.

### vec0 virtual table `vec_user_memories_{dim}`

- **Lazy-created at runtime** by
  `UserMemoriesRepository._upsertVecMemoryEmbedding` on first write of a
  given dimension (mirror of `_upsertVecMessageEmbedding` in
  `chat_embeddings.py`). **NOT created by the migration.**
- Carries denormalised metadata columns (`chat_id`, `user_id` partition keys,
  `thread_id`, `permanent`, `type`) plus the `embedding` vector column with
  cosine distance metric.
- Denormalised `type`/`thread_id` go **stale** after `updateMemory`, so the
  JOIN step in `_semanticSearchMemories` re-applies those filters on the
  authoritative `user_memories` columns (see "Search" below).

## Repository — `UserMemoriesRepository`

`internal/database/repositories/user_memories.py` (11 public methods). All
SQL goes through `BaseSQLProvider`; rows decode via
`dbUtils.sqlToTypedDict(row, UserMemoryDict)`. Method params are camelCase;
dict keys are snake_case to match columns.

- **Writes:** `addMemory` (INSERT), `updateMemory` (PATCH + invalidate
  embedding on content change), `deleteMemory` (by-id, unrestricted — may
  target a permanent memory), `deleteMemoriesByQuery` (bulk ephemeral-only —
  always adds `AND permanent = 0`).
- **Reads:** `getPermanentMemories` (cross-thread `NULL` + this-thread
  permanent, newest-updated-first, capped at `PERMANENT_INJECTION_CAP`),
  `getLatestMemories` (ephemeral-only, newest-updated-first, capped at
  `EPHEMERAL_RETRIEVAL_LIMIT`).
- **Search:** `searchMemories` — filter-only (`queryEmbedding is None`, plain
  SQL scan, `score = 0.0`) and semantic (`queryEmbedding` is bytes, vec0
  native, `score = 1.0 - distance`). Always scoped to
  `chat_id = :chatId AND user_id = :userId` — no cross-user leaks.
  `tags` is applied as a Python set-intersection post-fetch (ANY-match)
  because JSON-in-SQL `LIKE` is non-portable. In semantic mode `threadId` /
  `type` are re-applied in a JOIN step on the authoritative `user_memories`
  columns (the denormalised vec0 columns go stale after `updateMemory`).
- **Embedding persistence:** `saveMemoryEmbedding` (lazy vec0 upsert +
  provenance UPDATE; vec0 write must succeed before provenance is set — a
  failure leaves `embedding_model = NULL` so the regen cron retries),
  `deleteMemoryEmbedding` (best-effort, iterates every
  `vec_user_memories_{N}`, never raises).
- **Model-drift regen helpers:** `getMemoriesWithoutEmbeddings` (single-table
  stale detection — also serves the initial backfill since a `NULL`
  `embedding_model` surfaces here), `deleteObsoleteMemoryEmbeddings`
  (resets provenance to `NULL` + drops stale vec0 rows for rows whose
  model/dimensions drifted).

`updateMemory` content-change invalidation: when `content` is provided, the
stored vec0 vector (derived from the OLD content) is stale, so
`embedding_model`/`embedding_dimensions` are reset to `NULL` **and** the
stale vec0 row is dropped (best-effort) so `getMemoriesWithoutEmbeddings`
re-surfaces it. This is the **sole** trigger that keeps embeddings in sync
with content edits — regen only re-embeds on model drift.

## MemoryType

`internal/bot/models/memory_type.py` — `StrEnum` (AGENTS.md mandates `StrEnum`
over `Literal[...]`):

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
2. **Refinement pass** (`_runRefinement`): the background LLM curates the
   store directly via the three tools (Phase 4a rewrite — see "Refinement").
3. **Migration backfill** (`migration_020`): legacy `user_data` → permanent
   cross-thread `fact`; legacy rolling-bio blob → permanent thread-scoped
   `bio` (see "Migration from old system").

### Retrieval

- **Injection block** — `_buildMemoriesBlock` on `BaseBotHandler` loads
  permanent + ephemeral and renders the `<user-memories>` block (see
  "Injection").
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

`_runMemoryEmbeddingRegen` in `UserDataHandler` runs every 60s tick
(outside `_refineLock`) and mirrors `ChatSearchHandler._dtCronJob`
one-to-one, adapted for the single-store model:

1. **Chat discovery** — `listChatsBySetting(MEMORY_EMBEDDINGS_ENABLED)`,
   filtered through `ChatSettingsValue(...).toBool()`.
2. **Round-robin pick** — one chat per tick via `_memoryBackfillIndex`
   (stable order across ticks).
3. **Per-chat gate** — bail when `MEMORY_REGENERATE_EMBEDDINGS` is false.
4. **Model resolution** — `EMBEDDING_MODEL`; bail when empty, unknown, or
   not embedding-capable.
5. **Stale cleanup (model-drift detection)** — when the in-memory
   `_memoryEmbeddingModelTracker[chatId]` differs from the resolved
   `modelKey` (`"modelName"` or `"modelName:dimensions"`), call
   `deleteObsoleteMemoryEmbeddings` (resets stale rows' provenance to
   `NULL`); advance the tracker unconditionally so cleanup fires once per
   model switch.
6. **Stale detection** — `getMemoriesWithoutEmbeddings` (forwards
   `modelName` so rows embedded under a different model are re-surfaced;
   `NULL` `embedding_model` rows surface here too, serving the initial
   backfill).
7. **Re-embed loop** — each `UserMemoryDict` re-embedded via
   `embedAndSaveMemory` with an inter-call sleep; per-row failures
   swallowed inside the helper.

Never raises — a regen failure never breaks the refinement body sharing the
same tick. Batch size: `[user-memory.thresholds].memory-reindex-batch-size`
(default `50`).

## LLM tools

Registered in `UserDataHandler.__init__`, gated on the global
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
after insert via `embedAndSaveMemory` (never raises; regen cron picks up
failures).

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
`[1, MEMORY_SEARCH_MAX_LIMIT = 100]`), `permanent`. Returns
`{"done": True, "results": [...], "count": int}`. Only the caller's own
memories are ever returned. When no embedding model is available with a
`query`, falls back to filter-only.

## Injection

`BaseBotHandler._buildMemoriesBlock` (`internal/bot/common/handlers/base.py`)
builds the `<user-memories>` system-prompt block for a chat turn:

1. Bail when `MEMORY_INJECTION_ENABLED` is false (returns `None`).
2. Load permanent via `getPermanentMemories(..., limit=PERMANENT_INJECTION_CAP)`
   (cap 10 — includes cross-thread `NULL` + this-thread permanent).
3. Load ephemeral by `MEMORY_RETRIEVAL_MODE`:
   - `"relevant"` + non-empty message text + `EMBEDDINGS_ENABLED` →
     `_safeEmbedQuery` (best-effort; any failure falls back to latest) then
     `searchMemories(permanent=False, limit=EPHEMERAL_RETRIEVAL_LIMIT)` (cap 5).
   - Anything else (`"latest"`, relevant-but-embeddings-off,
     relevant-but-no-embed, relevant-but-search-empty) → `getLatestMemories`
     (cap 5, ephemeral-only).
4. `None` when both sections empty; otherwise `_formatMemoriesBlock`.

**Never-crash contract:** the whole body is wrapped in a top-level
`try/except Exception` so a transient DB error downgrades to `None` rather
than breaking the message turn.

### Rendering (`_formatMemoriesBlock`)

Format (plan §9.1):

```
<user-memories>
Permanent:
[bio] <content>  #<tag> ...
[preference] <content>
Recent:
[fact] <content>
[event] <content>
</user-memories>
```

- Each line: `[type] content #tag1 #tag2` (tags omitted when empty).
- Permanent sorted by `(type, updated_at)`; ephemeral ordered newest-first.
- The `Permanent:`/`Recent:` header + body are omitted entirely when that
  list is empty (lets permanent-empty render as just the `Recent:` block).
- **Soft char cap** `MEMORIES_BLOCK_SOFT_CHAR_CAP = 2000`: when exceeded and
  `len(ephemeral) > 1`, the recent section is trimmed first (each recent
  line is smaller and lower-value); when a lone ephemeral line would blow
  the cap it is still kept (the cap is a guideline — losing the only recent
  signal is the wrong trade-off).

`_injectMemoriesBlock` appends the block to `messages[0].content` (the
system message) after a blank-line separator; no-op when `block` is falsy
or `messages` is empty.

### Injection sites (4)

All four system-message construction sites inject the block about the
relevant user (`recipient.id` / `sender.id` / `dbMessage["user_id"]`),
driving relevant-mode search with the incoming message text:

1. `base.py` `getThreadByMessageForLLM` — thread context (the thread's
   root-message sender is the user the thread is about).
2. `llm_messages.py` `handleMention`.
3. `llm_messages.py` `handleRandomMessage` non-thread branch (the message
   list is built here before `_sendLLMChatMessage` is called).
4. `llm_messages.py` `handleReply` fallback path (fires when
   `getThreadByMessageForLLM` returned `[]` so the block would otherwise be
   missing — mirrors site 1; the list is built here before
   `_sendLLMChatMessage` is called).

Site 1 and the thread branch of site 3 are mutually exclusive (the thread
branch gets the block via `getThreadByMessageForLLM`, so injecting there too
would double-inject).

## Refinement (Phase 4a rewrite)

`UserDataHandler._runRefinement` was rewritten for the unified store. The
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
  old `{existingUserData}` / `{existingSummary}` placeholders (kept as
  backward-compat aliases so a per-chat override referencing them still
  formats without `KeyError`).
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
  remaining writers/readers — see [`../../plans/user-memories-v1.md`](../../plans/user-memories-v1.md) §9.3).
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

### Chat settings (4 — all `page = ChatSettingsPage.FRIEND`)

Defined in `ChatSettingsKey` (`internal/bot/models/chat_settings.py`) with
metadata in `_chatSettingsInfo` (four-site convention — see
[`../tasks.md`](../tasks.md) §4.1):

| `ChatSettingsKey` | TOML key | Type | Purpose |
|---|---|---|---|
| `MEMORY_INJECTION_ENABLED` | `memory-injection-enabled` | BOOL | Gate the `<user-memories>` block injection AND the chat-time availability of `add_memory` / `search_memories`. |
| `MEMORY_RETRIEVAL_MODE` | `memory-retrieval-mode` | STRING | `latest` (default) or `relevant` — how ephemeral memories are chosen. |
| `MEMORY_EMBEDDINGS_ENABLED` | `memory-embeddings-enabled` | BOOL | Gate the regen cron's chat discovery for this chat. |
| `MEMORY_REGENERATE_EMBEDDINGS` | `memory-regenerate-embeddings` | BOOL | Per-chat gate for re-embedding stale rows (only acts when `MEMORY_EMBEDDINGS_ENABLED` is on). |

The five refinement settings from the rolling-bio system are unchanged:
`MEMORY_REFINEMENT_ENABLED`, `MEMORY_REFINE_MODEL`,
`MEMORY_REFINE_FALLBACK_MODEL`, `MEMORY_REFINE_SYSTEM_PROMPT`,
`MEMORY_REFINE_USER_PROMPT_TEMPLATE`.

### Config — `[user-memory]` (`configs/00-defaults/user-memory.toml`)

Read ONCE in `UserDataHandler.__init__` and cached as instance attributes
(the cron hot path and `_runRefinement` perform no `configManager.get(...)`
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
  **table** is kept for rollback safety (only the tools that wrote it —
  `add_user_data` / `delete_user_data` — were retired).
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
structured `<user-memories>` block fully replaces it. See
[`../../plans/user-memories-v1.md`](../../plans/user-memories-v1.md) §9.3 for
the decision record.

## Cross-references

- [`../../plans/user-memories-v1.md`](../../plans/user-memories-v1.md) —
  authoritative implementation spec (planning document, amended post-impl).
- [`../architecture.md`](../architecture.md) ADR-016 — unified
  `user_memories` store decision (structured memories + vec0 + tool
  self-management + `<user-memories>` block injection). ADR-014 covers the
  background refinement machinery (cron + global lock + accounting) that
  still governs `_runRefinement`; ADR-015 covers the `chat_users` cache used
  by the cursor persist.
- [`user-memory-refinement.md`](user-memory-refinement.md) — the predecessor
  rolling-bio subsystem (SUPERSEDED, kept as historical context).
- [`../handlers.md`](../handlers.md) `UserDataHandler` row;
  [`../configuration.md`](../configuration.md) §`[user-memory]`;
  [`../database.md`](../database.md) for migration patterns.
