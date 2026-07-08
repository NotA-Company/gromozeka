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

Owner handler: `UserDataHandler` (`internal/bot/common/handlers/user_data.py`)
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
- Carries denormalised metadata columns (`chat_id`, `user_id`, `model`
  partition keys, `thread_id`, `permanent`, `type`) plus the `embedding`
  vector column with cosine distance metric. The `model` partition key
  scopes vectors per embedding model so a model swap does not pollute one
  model's vector space with another's.
- Denormalised `type`/`thread_id` go **stale** after `updateMemory`, so the
  JOIN step in `_semanticSearchMemories` re-applies those filters on the
  authoritative `user_memories` columns (see "Search" below). `permanent`
  is immutable post-creation so it is pushed into the vec0 filter directly;
  `model` is a partition key and is always part of the vec0 filter clause.

## Repository — `UserMemoriesRepository`

`internal/database/repositories/user_memories.py` (10 public methods in the
documented core set — the `/knowledge_config` wizard helpers `getMemory` /
`getDistinctTags` are tracked separately; all SQL goes through
`BaseSQLProvider` and rows decode via
`dbUtils.sqlToTypedDict(row, UserMemoryDict)`). Method params are camelCase;
dict keys are snake_case to match columns.

- **Writes:** `addMemory` (INSERT — requires `embedding: Optional[List[float]]`,
  `embeddingModel: Optional[str]`, and `source: UserMemorySource`; `threadId`
  is keyword-only; embeds during add when both `embedding` and `embeddingModel`
  are provided), `updateMemory` (PATCH + invalidate embedding on content
  change), `deleteMemory` (by-id, unrestricted — may target a permanent
  memory).
- **Reads:** `getPermanentMemories` (cross-thread `NULL` + this-thread
  permanent, newest-updated-first, capped at `PERMANENT_INJECTION_CAP`),
  `getLatestMemories` (ephemeral-only, newest-updated-first, capped at
  `EPHEMERAL_RETRIEVAL_LIMIT`).
- **Search:** `searchMemories` — filter-only (`queryEmbedding is None`, plain
  SQL scan, `score = 0.0`) and semantic (`queryEmbedding` is a `List[float]`,
  vec0 native, `score = 1.0 - distance`). `embeddingModel: str` is required
  (keyword-only — pass `None` for filter-only mode); it replaces the old
  `dimensions: int` arg. Always scoped to
  `chat_id = :chatId AND user_id = :userId` — no cross-user leaks. The vec0
  filter clause includes `model = :modelName` (per-model scoping) plus the
  immutable `permanent` flag. `tags` is applied as a portable SQL `LIKE`
  filter (`tags LIKE '%"tagN"%'`, ANY-match) — the `tags` column is stored as
  JSON TEXT via provider auto-serialization of the Python list. In semantic
  mode `threadId` / `type` are re-applied in a JOIN step on the authoritative
  `user_memories` columns (the denormalised vec0 columns go stale after
  `updateMemory`).
- **Embedding persistence:** `saveMemoryEmbedding` (takes `embeddingModel: str`
  + `List[float]`; lazy vec0 upsert + provenance UPDATE; vec0 write must
  succeed before provenance is set — a failure leaves `embedding_model = NULL`
  so the regen cron retries), `deleteMemoryEmbedding` (best-effort, iterates
  every `vec_user_memories_{N}`, never raises).
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
2. **Refinement pass** (`_runRefinement`): the background LLM curates the
   store directly via the three tools (Phase 4a rewrite — see "Refinement").
3. **Migration backfill** (`migration_020`): legacy `user_data` → permanent
   cross-thread `fact`; legacy rolling-bio blob → permanent thread-scoped
   `bio` (see "Migration from old system").

### Retrieval

- **Injection** — `MessagePreprocessorHandler.injectMemories()` loads
  permanent + ephemeral at message-arrival time, persists them into the
  chat message's `metadata`, and they ride per-message via
  `EnsuredMessage.setUserMemories` / `formatForLLM` (JSON key `userMemories`).
  See "Injection".
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
   `LLMService.generateEmbedding` (returns `(modelName, List[float])` or
   `None`) and persisted through `UserMemoriesRepository.saveMemoryEmbedding`
   with an inter-call sleep; `generateEmbedding` swallows its own failures
   (returns `None`, the loop skips the save).

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
`[1, MEMORY_SEARCH_MAX_LIMIT = 100]`), `permanent`. Returns
`{"done": True, "results": [...], "count": int}`. Only the caller's own
memories are ever returned. When no embedding model is available with a
`query`, falls back to filter-only.

## Injection

Injection is **centralised** in
`MessagePreprocessorHandler.injectMemories()` (`internal/bot/common/handlers/message_preprocessor.py`),
called once per inbound message **at arrival time** (inside
`newMessageHandler`, before `saveChatMessage`). The previous
`BaseBotHandler._buildMemoriesBlock` / `_formatMemoriesBlock` /
`_injectMemoriesBlock` / `_safeEmbedQuery` helpers and the four
handler-level injection sites (`getThreadByMessageForLLM`, `handleMention`,
`handleRandomMessage`, `handleReply`) were **deleted** in the
refactoring — there is no longer a `<user-memories>` system-message block.

### Flow (`MessagePreprocessorHandler.injectMemories`)

1. Bail when `MEMORY_INJECTION_ENABLED` is false.
2. **Permanent** — read from the write-through permanent-memories cache via
   `cache.getChatUserPermanentMemories(chatId, userId, threadId)`
   (cross-thread `NULL` + this-thread permanent, already capped at
   `PERMANENT_INJECTION_CAP = 10`, returned as `list[SingleMemoryDict]`).
3. **Ephemeral (short-term)** — chosen by `MEMORY_RETRIEVAL_MODE`:
   - `"relevant"` + non-empty message text →
     `LLMService.generateEmbedding(messageText, chatId, chatSettings)`
     (returns `(modelName, List[float])` or `None`); on a non-`None` result,
     `searchMemories(queryEmbedding=<floats>, embeddingModel=<modelName>,
     permanent=False)` (vec0-ranked); on `None` (no embedding model, rate
     limit, provider error) falls back to `getLatestMemories`.
   - Anything else (`"latest"`, relevant-but-no-embed) →
     `getLatestMemories` (cap `EPHEMERAL_RETRIEVAL_LIMIT = 5`, ephemeral-only).
4. The ephemeral rows are slimmed to `SingleMemoryDict` via
   `convertDBMemoryToSingleMemoryDict` (drops DB plumbing keys, keeps
   `type`/`content`/`tags`/`score`).
5. `ensuredMessage.setUserMemories({"permanent": permanentMemories,
   "shortTerm": shortTermMemories})` — a deep copy is stored on
   `EnsuredMessage.userMemories` and mirrored into
   `metadata["memories"]`.

Because step 5 runs **before** `saveChatMessage`, the snapshot is persisted
into the chat message's `metadata` JSON and **rides per message**: when the
message is later loaded into an LLM turn (thread context, mention, random,
reply), `EnsuredMessage.fromDBChatMessage(..., injectMemories=True)` reads
the `memories` key back via `setUserMemories`, and `formatForLLM` emits them
under the JSON key **`userMemories`** (a per-message field, not a
system-message block). The memories seen by the model are therefore the
snapshot known at the time the message arrived — every message in a thread
carries its own context, and there is no per-turn re-fetch at the LLM call
site.

### Permanent-memories cache

The permanent cohort is served from a write-through cache in `CacheService`
rather than re-queried on every inbound message:

- `getChatUserPermanentMemories(chatId, userId, threadId)` →
  `list[SingleMemoryDict]` — lazily loads + memoises the permanent block for
  `(chatId, userId, threadId)`; the loader calls `getPermanentMemories` and
  converts via `convertDBMemoryToSingleMemoryDict`.
- `invalidateChatUserPermanentMemories(chatId, userId, threadId)` — drops the
  cached block so the next read re-queries. Called by the memory-write paths
  (`add_memory` / `delete_memory` / the refinement tools) so a freshly added
  permanent memory is visible on the next inbound message.

The old `getChatUserData` / `setChatUserData` / `unsetChatUserData` /
`clearChatUserData` cache methods (legacy `user_data` key-value blob) were
**deleted**; `invalidateChatUser(chatId, userId)` still exists but only drops
`userInfo` and intentionally preserves the permanent-memories cache.

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
| `MEMORY_INJECTION_ENABLED` | `memory-injection-enabled` | BOOL | Gate `MessagePreprocessorHandler.injectMemories()` (the message-arrival injection into `EnsuredMessage.userMemories`) AND the chat-time availability of `add_memory` / `search_memories`. |
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
per-message `userMemories` snapshot (injected at arrival time and persisted
in `chat_messages.metadata.memories`) fully replaces it. See
[`../../plans/user-memories-v1.md`](../../plans/user-memories-v1.md) §9.3 for
the decision record.

## Cross-references

- [`../../plans/user-memories-v1.md`](../../plans/user-memories-v1.md) —
  authoritative implementation spec (planning document, amended post-impl).
- [`../architecture.md`](../architecture.md) ADR-016 — unified
  `user_memories` store decision (structured memories + vec0 + tool
  self-management + centralised arrival-time injection). ADR-014 covers the
  background refinement machinery (cron + global lock + accounting) that
  still governs `_runRefinement`; ADR-015 covers the `chat_users` cache used
  by the cursor persist.
- [`user-memory-refinement.md`](user-memory-refinement.md) — the predecessor
  rolling-bio subsystem (SUPERSEDED, kept as historical context).
- [`../handlers.md`](../handlers.md) `UserDataHandler` row;
  [`../configuration.md`](../configuration.md) §`[user-memory]`;
  [`../database.md`](../database.md) for migration patterns.
