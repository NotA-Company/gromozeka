# Plan: Embedding Model Lookup Refactor v1

Status: **APPROVED** — all design decisions resolved; self-review pass
complete (R2/R5/Q4 closed; one new risk R6 surfaced and encoded in §6/§13)
Date: 2026-07-20
Owner: TBD
Companion docs: [`docs/design/vector-search-native.md`](../design/vector-search-native.md), [`docs/database-schema.md`](../database-schema.md), [`docs/database-schema-llm.md`](../database-schema-llm.md)

> All open questions (Q1–Q3) and the D7 PK deviation were ratified by the
> user on 2026-07-20; see §5 for the final decision set. A rigorous
> self-review on the same date closed R2 (D6 extended to cover
> `searchChatMessages`), R5 (`upsert(..., updateExpressions={})`), and Q4
> (`deleted_at` intentionally excluded from `_SELECT_COLUMNS`); surfaced
> one new risk R6 (migration backfill re-run safety) and encoded the
> probe-then-insert fix in §6 Step 2.

## Summary

Normalise embedding provenance into a single `models` lookup table. Move the
per-row `(model, dimensions)` pair off every embedding-bearing row and onto one
`model_id` FK-like integer. Drop the `message_embeddings` BLOB side table and
its numpy cosine-safety-net from `chat_search.py` so vec0 becomes the sole
vector store for **both** message search and memory search. Scope is one
migration (`migration_025`), touching `chat_messages`, `user_memories`, the
new `models` table, and both `vec_*` virtual-table families.

This is a **plan document only** — research/design artefact. No production
code is changed by this file. Implementation work is executed against the
phasing in §11 by dispatching `software-developer` (code) and `docs-writer`
(doc sync) tasks; the final documentation pass must load the
`update-project-docs` skill.

---

## 1. Motivation / Goals

1. **Stop storing `(model, dimensions)` redundantly on every embedding row.**
   Today each `message_embeddings` row carries a `model TEXT` + `dimensions
   INTEGER`, and each `user_memories` row carries `embedding_model TEXT` +
   `embedding_dimensions INTEGER` (different column names for the same
   concept). These are duplicated millions of times across chats for a set of
   maybe a dozen active models. A `models` lookup table keyed by a small
   integer collapses this to one row per distinct `(model, dimensions)` pair.

2. **Retire the numpy fallback technical debt in message search.**
   `internal/database/repositories/chat_search.py` carries a hand-rolled
   numpy cosine-similarity path (`_loadEmbeddingsFromDb` + inline matrix
   multiply at lines ~410-480) that exists only as a fallback when vec0 is
   unavailable, raises, or returns `[]`. It forces a second embedding store
   (`message_embeddings` BLOB), doubles write load, and pins a heavy direct
   dependency (`numpy==2.5.1`) plus a brittle tie-break contract pinned in
   [`tests/dependencies/test_numpy.py`](../../tests/dependencies/test_numpy.py).
   Memories never had this fallback; messages should not either.

3. **Unify the storage story.** After this refactor, vec0 is the sole vector
   store for both features. `message_embeddings` is gone. `user_memories`
   drops its provenance columns. Both rows point at `models.model_id`. The
   `vec_message_embeddings_{N}` and `vec_user_memories_{N}` lazy-create DDL
   both gain `model_id INTEGER PARTITION KEY` (replacing `model TEXT
   PARTITION KEY` on the message side; memories had no model partition key
   before).

4. **Make model drift cheaper to detect and clean.** `deleteObsoleteModel*
   Embeddings` becomes a single-integer comparison (`model_id !=
   :currentModelId`) instead of a `(model, dimensions)` tuple comparison,
   and there is exactly one place that needs to know the active model id.

## 2. Non-goals

- **Changing the `EMBEDDING_MODEL` chat setting** or any other
  `ChatSettingsKey`. The handler still reads `chatSettings[ChatSettingsKey.
  EMBEDDING_MODEL].toStr()` to obtain the model name string; resolution to
  `model_id` happens inside the repository layer (see Decision D5 below and
  §8 "Handler-layer signature stability").
- **Migrating the `/search` slash-command caller** in
  `internal/bot/common/handlers/chat_search.py:~1322` to route through
  `LLMService.generateEmbedding`. That caller still resolves the model from
  settings and calls `model.generateEmbeddings(...)` directly. It passes
  `modelName=...` to `searchChatMessages`; the repo resolves to `model_id`
  internally per extended D6 (see §8.5). The call shape itself is not
  being re-architected here.
- **Changing the vec0 distance metric.** Both families stay
  `distance_metric=cosine`.
- **Adding new embedding providers** or changing `lib/ai/`. The
  `LLMService.generateEmbedding` contract (`(modelName, vector)` return) is
  untouched.
- **Touching `chat_summarization_cache`** or any other table that does not
  carry embedding provenance.
- **Switching the primary backend** away from SQLite or turning on the
  PostgreSQL/MySQL providers. All SQL in this plan stays portable per
  [`docs/sql-portability-guide.md`](../sql-portability-guide.md).
- **Removing numpy from production code.** **None.** numpy is being
  retired entirely from production code in this refactor (Decision D8;
  see §5 and Phase 4). The message-side fallback in `chat_search.py` is
  dropped AND the single `numpy.linalg.norm` call in
  `user_memories.py:872` is replaced with `math.sqrt(...)`.

## 3. Current state (authoritative — from exploration)

Five logical stores touch embedding provenance today:

| # | Store | Kind | Model column(s) | Dimensions column(s) | Created by |
|---|-------|------|-----------------|----------------------|------------|
| 1 | `message_embeddings` | regular SQL table | `model TEXT NOT NULL` | `dimensions INTEGER NOT NULL` | [`migration_017`](../../internal/database/migrations/versions/migration_017_message_embeddings.py); index `idx_message_embeddings_chat_model` on `(chat_id, model)` from [`migration_018`](../../internal/database/migrations/versions/migration_018_message_embeddings_index.py) |
| 2 | `user_memories` | regular SQL table | `embedding_model TEXT` (nullable) | `embedding_dimensions INTEGER` (nullable) | [`migration_020`](../../internal/database/migrations/versions/migration_020_user_memories.py) + soft-delete `deleted_at` from [`migration_021`](../../internal/database/migrations/versions/migration_021_user_memories_soft_delete.py) |
| 3 | `vec_message_embeddings_{N}` | vec0 virtual table (dimension-sharded, lazy) | `model TEXT PARTITION KEY` | implicit (table name suffix) | runtime: [`ChatEmbeddingsRepository._upsertVecMessageEmbedding`](../../internal/database/repositories/chat_embeddings.py) at lines ~166-263 |
| 4 | `vec_user_memories_{N}` | vec0 virtual table (dimension-sharded, lazy) | — (no model partition key) | implicit (table name suffix) | runtime: [`UserMemoriesRepository._upsertVecMemoryEmbedding`](../../internal/database/repositories/user_memories.py) at lines ~1162-1186 |
| 5 | `chat_messages` | regular SQL table | **none** | **none** | recreated by [`migration_013`](../../internal/database/migrations/versions/migration_013_remove_timestamp_defaults.py); **no dedicated indexes** — only PK `(chat_id, message_id)` |

Notable divergences:
- The two SQL tables spell the provenance columns **differently**
  (`model`/`dimensions` vs `embedding_model`/`embedding_dimensions`).
- Only `message_embeddings` has a BLOB column (`embedding BLOB` = float32 LE
  via `array.array('f', vec).tobytes()`). `user_memories` does not — vec0 is
  already its sole vector store.
- `chat_messages` carries no embedding columns at all; provenance lives
  only in the sidecar `message_embeddings` row keyed by `(chat_id,
  message_id)`.

Where it is read/written (all production callers live in
`internal/bot/common/handlers/`; `lib/` has none):
- `ChatEmbeddingsRepository` ([`chat_embeddings.py`](../../internal/database/repositories/chat_embeddings.py)):
  `saveMessageEmbedding`, `_upsertVecMessageEmbedding`, `getMessageEmbedding`
  (**tests only**), `deleteChatEmbeddings` (**tests only**),
  `deleteObsoleteModelEmbeddings`, `getMessagesWithoutEmbeddings`.
- `ChatSearchRepository` ([`chat_search.py`](../../internal/database/repositories/chat_search.py)):
  `searchChatMessages` dispatcher → `_semanticSearch` (the numpy fallback
  lives at lines ~410-480, gated by `isVectorSearchSupported()` at ~368,
  exception catch at ~402, empty-result fall-through at ~398) →
  `_nativeVectorSearch` (lines ~707-905). `_loadEmbeddingsFromDb` at lines
  ~485-553 serves only the numpy path.
- `UserMemoriesRepository` ([`user_memories.py`](../../internal/database/repositories/user_memories.py)):
  `_SELECT_COLUMNS` constant at lines 74-78 includes
  `embedding_model, embedding_dimensions`. All read/write methods touch
  these columns. `_semanticSearchMemories` at line ~809 uses
  `numpy.linalg.norm` at line ~872 for query-vector norm guarding (NOT a
  fallback path — a single pure-math use; retired entirely by Decision
  D8 — see §5).
- Handler call sites: [`message_preprocessor.py`](../../internal/bot/common/handlers/message_preprocessor.py)
  (lines 114-121, 210-216), [`chat_search.py`](../../internal/bot/common/handlers/chat_search.py)
  (lines ~476-496, ~558-564, ~725-736, ~1338-1348), [`user_memories.py`](../../internal/bot/common/handlers/user_memories.py)
  (lines ~476-545, ~598-634, ~723-733, ~874-893, ~920-926, ~1870-1893,
  ~2220, ~2670-2682, ~2889-2896).
- Maintenance script [`scripts/clear_memory_embeddings.py`](../../scripts/clear_memory_embeddings.py)
  issues raw SQL bypassing the repos (`DROP TABLE vec_user_memories_{N}` +
  `UPDATE user_memories SET embedding_model=NULL, embedding_dimensions=NULL`
  at line 293).

How `model` / `dimensions` are sourced today:
- `model` name string = `chatSettings[ChatSettingsKey.EMBEDDING_MODEL].toStr()`.
- `dimensions` = `len(embedding)` at write time (derived, never threaded
  into callers). For drift detection *before* generating a vector:
  `await model.getDimensions()` (`AbstractModel.getDimensions` in
  [`lib/ai/abstract.py`](../../lib/ai/abstract.py) ~line 589-605), which can
  return `None` for OpenAI-style models that don't expose
  `embedding_dimensions` until first generation.
- `LLMService.generateEmbedding(text, *, chatId, chatSettings)` returns
  `Optional[Tuple[str, List[float]]]` = `(modelName, vector)`.

Migration precedent for the temp-table swap is
[`migration_013_remove_timestamp_defaults.py`](../../internal/database/migrations/versions/migration_013_remove_timestamp_defaults.py)
(the only such precedent in the tree). It recreated 19 tables via the
`CREATE _new → INSERT...SELECT → DROP old → RENAME → CREATE INDEX` shape.

## 4. Target state

After `migration_025` + the code changes land:

### 4.1 New `models` lookup table

```sql
CREATE TABLE IF NOT EXISTS models (
    model_id   INTEGER PRIMARY KEY NOT NULL,   -- app-generated sequential (see D2)
    model      TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL,
    UNIQUE (model, dimensions)
)
```

`model_id` is allocated app-side by `ModelsRepository.getOrCreateModelId`
(see D2). No `AUTOINCREMENT` / `SERIAL` — the DB does not generate IDs.

### 4.2 Slimmed `chat_messages` (+ `model_id`)

```sql
CREATE TABLE chat_messages (
    chat_id          INTEGER NOT NULL,
    message_id       TEXT NOT NULL,
    date             TIMESTAMP NOT NULL,
    user_id          INTEGER NOT NULL,
    reply_id         TEXT,
    thread_id        INTEGER NOT NULL DEFAULT 0,
    root_message_id  TEXT,
    message_text     TEXT NOT NULL,
    message_type     TEXT DEFAULT 'text' NOT NULL,
    message_category TEXT DEFAULT 'user' NOT NULL,
    quote_text       TEXT,
    media_id         TEXT,
    media_group_id   TEXT,
    markup           TEXT DEFAULT "" NOT NULL,
    metadata         TEXT DEFAULT "" NOT NULL,
    created_at       TIMESTAMP NOT NULL,
    model_id         INTEGER,                   -- NEW; NULL = not yet embedded
    PRIMARY KEY (chat_id, message_id)
)
```

No dedicated indexes (none exist today — verified by grep across
`internal/database/migrations/versions/`). No FK constraint — kept portable
across SQLite/PostgreSQL/MySQL (the existing codebase does not use FK
constraints; referential integrity is enforced at the application layer).

### 4.3 Slimmed `user_memories` (- provenance pair, + `model_id`)

```sql
CREATE TABLE user_memories (
    chat_id    INTEGER   NOT NULL,
    user_id    INTEGER   NOT NULL,
    thread_id  INTEGER,
    memory_id  TEXT      NOT NULL,
    type       TEXT      NOT NULL,
    content    TEXT      NOT NULL,
    tags       TEXT      NOT NULL DEFAULT '[]',
    permanent  INTEGER   NOT NULL DEFAULT 0,
    source     TEXT      NOT NULL DEFAULT 'refinement',
    deleted_at TIMESTAMP,                        -- from migration_021
    model_id   INTEGER,                          -- NEW; NULL = not yet embedded
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, user_id, memory_id)
)
-- Indexes (recreated unchanged from migration_020):
--   idx_user_memories_chat_user_thread   (chat_id, user_id, thread_id, updated_at DESC)
--   idx_user_memories_chat_user_permanent (chat_id, user_id, permanent, updated_at DESC)
--   idx_user_memories_type               (chat_id, user_id, type)
```

### 4.4 New vec0 lazy-create DDL (both families)

`vec_message_embeddings_{N}` — replaces `model TEXT PARTITION KEY` with
`model_id INTEGER PARTITION KEY`:

```python
await sqlProvider.createVectorTable(
    tableName,
    [
        {"name": "message_id", "columnType": VectorColumnType.TEXT},
        {"name": "chat_id", "columnType": VectorColumnType.INTEGER, "isPartitionKey": True},
        {"name": "model_id", "columnType": VectorColumnType.INTEGER, "isPartitionKey": True},
        {"name": "date", "columnType": VectorColumnType.TEXT},
        {
            "name": "embedding",
            "columnType": VectorColumnType.VECTOR,
            "vectorDimension": dimensions,
            "distanceMetric": VectorDistanceMetric.COSINE,
        },
    ],
)
```

`vec_user_memories_{N}` — gains a `model_id INTEGER PARTITION KEY` (it had
none before):

```python
await sqlProvider.createVectorTable(
    tableName,
    [
        {"name": "memory_id", "columnType": VectorColumnType.TEXT},
        {"name": "chat_id", "columnType": VectorColumnType.INTEGER, "isPartitionKey": True},
        {"name": "user_id", "columnType": VectorColumnType.INTEGER, "isPartitionKey": True},
        {"name": "model_id", "columnType": VectorColumnType.INTEGER, "isPartitionKey": True},
        {"name": "permanent", "columnType": VectorColumnType.INTEGER},
        {
            "name": "embedding",
            "columnType": VectorColumnType.VECTOR,
            "vectorDimension": dimensions,
            "distanceMetric": VectorDistanceMetric.COSINE,
        },
    ],
)
```

### 4.5 Gone

- `message_embeddings` table (and its `idx_message_embeddings_chat_model`
  index from `migration_018`) — dropped.
- All `vec_message_embeddings_{N}` virtual tables (and their sqlite-vec
  shadow tables `_*_chunks`, `_*_rowids`, etc.) — dropped; recreated lazily
  by the next embed call with the new `model_id` DDL.
- All `vec_user_memories_{N}` virtual tables — dropped; recreated lazily.
- The numpy fallback block in `chat_search.py` (`_loadEmbeddingsFromDb` and
  the inline cosine matrix at lines ~410-480).

## 5. Decisions (all user-confirmed)

- **D1 — vec0 migration: DROP & lazily recreate.** Migration drops both
  vec0 families; the next embed call recreates with the new
  `model_id`-partitioned DDL. Re-embedding cost on next backfill is
  accepted. Rationale: vec0 DDL is not ALTER-able; full drop is the only
  portable option. **Irreversible — see Risk R1.**
- **D2 — `model_id` allocation: app-generated, via `ModelsRepository`
  cache.** New repo `ModelsRepository.getOrCreateModelId(model, dimensions)`
  uses `INSERT OR IGNORE` with app-picked id
  (`SELECT COALESCE(MAX(model_id),0)+1 FROM models`) then `SELECT model_id
  FROM models WHERE model=:model AND dimensions=:dimensions`. Process-local
  dict cache `{(model, dimensions): model_id}`. Single-process app → no
  DB-level autoincrement needed. Complies with the AGENTS.md
  "application-generated ID" rule (the DB does not generate IDs).
- **D3 — Keep `ChatEmbeddingsRepository` as a separate repo.** It still
  owns save (now `chat_messages.model_id` UPDATE + vec0 insert), backfill
  discovery, and model-drift cleanup. Drop `getMessageEmbedding` and
  `deleteChatEmbeddings` (no production callers — tests only).
- **D4 — Accept re-embedding cost on `message_embeddings` drop.** Any
  BLOB-only vectors that were never dual-written to vec0 are lost; vec0
  gets repopulated via the existing backfill cron on next access. This is
  the explicit trade for retiring the BLOB store.
- **D5 — Scope: BOTH messages AND user_memories in a single migration.**
  One migration `migration_025` does: create `models`, swap `user_memories`
  (temp-table pattern), swap `chat_messages` (temp-table pattern), drop
  `message_embeddings`, drop both vec0 families.
- **D6 — Handler-layer signature stability (the brief's recommendation
  (b), adopted; user-confirmed 2026-07-20; extended during self-review).**
  Repos continue to accept the model **name string** (and, where relevant,
  the optional dimensions integer) at their public boundary. Every
  repository method that handlers call today keeps its current param shape:
  - `saveMessageEmbedding(..., model=modelName)` — unchanged.
  - `searchMemories(..., embeddingModel=modelName)` — unchanged.
  - `searchChatMessages(..., modelName=modelName)` — unchanged (the
    original draft proposed flipping this to `modelId: Optional[int]`,
    which would have forced every handler caller — both the LLM-tool path
    at `chat_search.py:725-736` AND the `/search` slash-command path at
    `chat_search.py:1338-1348` — to resolve `model_id` themselves; that
    is exactly the blast radius D6 exists to avoid).
  - `deleteObsoleteModelEmbeddings(chatId, currentModel: str, *,
    currentDimensions=None)` — unchanged.
  - `deleteObsoleteMemoryEmbeddings(chatId, currentModel: str,
    currentDimensions: Optional[int])` — unchanged.
  - `getMessagesWithoutEmbeddings(chatId, *, limit, modelName=None,
    dimensions=None, dataSource=None)` — unchanged.
  - `getMemoriesWithoutEmbeddings(chatId, *, limit, modelName=None,
    dimensions=None, dataSource=None)` — unchanged.

  Resolution to `model_id` happens inside each repo via the injected
  `ModelsRepository.getOrCreateModelId` (see D10 — every embedding-touching
  repo receives the resolver). This keeps the blast radius small: handler
  call sites in `internal/bot/common/handlers/*.py` change **zero lines**.
  The cost is that the drift-detection repos gain a cross-repo dependency
  via the injected resolver (see D10). See §8 for the full rationale and
  the alternative that was rejected.

  **Subtle case (dimensions unknown):** when `AbstractModel.getDimensions()`
  returns `None` (OpenAI-style models), the repo cannot resolve a single
  canonical `model_id` for `(currentModel, None)`. The repo handles this
  internally by falling back to a `model_id NOT IN (SELECT model_id FROM
  models WHERE model = :currentModel)` subquery — semantically equivalent
  to today's `model != :currentModel` predicate. When dimensions IS known,
  the repo resolves a single id and uses the cheaper `model_id !=
  :resolvedId` predicate. Both branches are the repo's concern; handlers
  keep passing the same `(currentModel, currentDimensions)` pair they do
  today.
- **D7 — `models` PK uses `INTEGER PRIMARY KEY NOT NULL` with app-generated
  sequential ids, NOT the AGENTS.md-default TEXT UUID
  (user-confirmed 2026-07-20).** Justified by: (a) small sequential ints
  are more compact and faster as vec0 partition keys than 32-char UUID
  strings; (b) the process-local cache makes allocation O(1) after
  warmup; (c) single-process app means no concurrent-writer hazard. This
  is a documented, intentional deviation from preference #3 in the
  AGENTS.md "Primary keys" rule. The deviation complies with the hard
  rule ("no `AUTOINCREMENT` / `SERIAL` / `AUTO_INCREMENT`", "never
  delegate ID generation to the DB") — it just uses `INTEGER` instead of
  `TEXT`.
- **D8 — numpy is retired entirely from production code (user-confirmed
  2026-07-20; was D8-deferred, now full-removal).** The message-side
  fallback (the matrix cosine block in `chat_search.py:410-480`) is
  dropped, AND the single `numpy.linalg.norm` call in
  `user_memories.py:872` is replaced with
  `math.sqrt(sum(x*x for x in queryEmbedding))`. `numpy==2.5.1` is
  removed from `requirements.direct.txt` and `requirements.txt` is
  regenerated via `freeze-requirements`. `tests/dependencies/test_numpy.py`
  is deleted.
- **D9 — `vec_user_memories_{N}` gets a `model_id INTEGER PARTITION KEY`
  (user-confirmed 2026-07-20).** Mirrors the message side; enables drift
  cleanup by `model_id` without scanning. Free since D1 already drops and
  recreates both vec0 families.
- **D10 — Cross-repo access via constructor-injected resolver
  (user-confirmed 2026-07-20; extended during self-review).**
  `ChatEmbeddingsRepository`, `ChatSearchRepository`, and
  `UserMemoriesRepository` each gain a constructor parameter
  `modelIdResolver: Callable[[str, int], Awaitable[int]]` (concrete form —
  see §8.4/§8.5/§8.6 for the exact constructor signatures). Tests inject
  a mock resolver. The `Database` wiring in `internal/database/database.py`
  constructs `ModelsRepository` first and passes its `getOrCreateModelId`
  bound method to the three consuming repos' constructors. This is option
  (b) from the original Q3 — keeps `DatabaseManager` repo-agnostic and
  makes the dependency explicit.

  `ChatSearchRepository` is on the resolver list because D6 was extended
  during self-review to keep `searchChatMessages(..., modelName=...)` stable
  — the repo resolves `(modelName, len(queryEmbedding))` to `model_id`
  internally before the vec0 lookup. (Original draft flipped
  `searchChatMessages` to `modelId: Optional[int]`, which would have
  forced every handler caller to resolve; that was the contradiction
  surfaced and fixed in this revision.)

### Resolved by sign-off 2026-07-20

All previously-flagged items above (D7 PK deviation, D8 numpy scope, D9
vec0 partition key, D10 resolver injection) were ratified in this
sign-off round. There are no remaining architect-flagged decisions;
every entry in §5 is user-confirmed.

### Extended during self-review 2026-07-20

D6 was broadened to cover every handler-facing repo method (originally
listed only `saveMessageEmbedding` and `searchMemories`; now also
`searchChatMessages`, `deleteObsoleteModelEmbeddings`,
`deleteObsoleteMemoryEmbeddings`, `getMessagesWithoutEmbeddings`,
`getMemoriesWithoutEmbeddings`). D10's resolver-injection list grew from
two repos (`ChatEmbeddingsRepository`, `UserMemoriesRepository`) to three
(added `ChatSearchRepository`). Together these close the contradiction
between §8.5 (which had proposed flipping `searchChatMessages` to
`modelId: Optional[int]`) and §8.8 (which had claimed handler callers do
not change). See the closed Risk R2 in §13.

## 6. Database migration design — `migration_025`

File: `internal/database/migrations/versions/migration_025_embedding_model_lookup.py`
Class: `Migration025EmbeddingModelLookup(BaseMigration)`
Fields: `version: int = 25`, `description: str = "Normalise embedding provenance into models lookup; drop message_embeddings BLOB store and numpy fallback"`
Methods: `async def up(self, sqlProvider: BaseSQLProvider) -> None`,
         `async def down(self, sqlProvider: BaseSQLProvider) -> None`
Module-level: `def getMigration() -> Type[BaseMigration]: return Migration025EmbeddingModelLookup`
Imports (mirror `migration_013` / `migration_020`):
```python
from typing import Type
import lib.utils as libUtils
from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration
```

The migration must run in the order below. Each numbered step is a
self-contained `await sqlProvider.batchExecute([...])` block (or, for the
Python-loop backfill of `models`, a sequence of `executeFetchAll` +
`execute` calls). The ordering constraint is: **`models` must be populated
before the `user_memories` and `chat_messages` backfill SELECTs run**,
because those SELECTs LEFT JOIN to `models`.

### Step 1 — Create the `models` table

```python
await sqlProvider.batchExecute([
    ParametrizedQuery("""
        CREATE TABLE IF NOT EXISTS models (
            model_id   INTEGER PRIMARY KEY NOT NULL,
            model      TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL,
            UNIQUE (model, dimensions)
        )
    """),
])
```

### Step 2 — Populate `models` from existing data

A pure-SQL `INSERT ... SELECT DISTINCT ... UNION ...` is *almost* enough,
but the app-generated sequential `model_id` allocation
(`COALESCE(MAX(model_id),0)+1`) is not expressible portably across all three
target RDBMS in a single statement. Use a Python loop in the migration body
(same pattern `migration_020` uses for its UUID backfills):

```python
# Collect distinct (model, dimensions) pairs from both stores.
messageRows = await sqlProvider.executeFetchAll(
    "SELECT DISTINCT model, dimensions FROM message_embeddings"
)
memoryRows = await sqlProvider.executeFetchAll(
    "SELECT DISTINCT embedding_model AS model, embedding_dimensions AS dimensions "
    "FROM user_memories WHERE embedding_model IS NOT NULL"
)

seen: set[tuple[str, int]] = set()
now = libUtils.now()
for row in list(messageRows) + list(memoryRows):
    modelName: str = row["model"]
    dims: int = int(row["dimensions"])
    key = (modelName, dims)
    if key in seen:
        continue
    seen.add(key)

    # Re-run safety: the migration framework does NOT wrap up() in a
    # transaction (see ``internal/database/migrations/manager.py:285-300`` —
    # ``_setVersion`` is only called after up() returns; a crash mid-loop
    # leaves the migration half-applied AND with its version not bumped, so
    # the next run re-enters up() from the top with a fresh ``seen`` set).
    # The plain ``INSERT`` below would therefore hit the UNIQUE(model,
    # dimensions) constraint on re-run and raise. Probe-and-skip makes the
    # loop idempotent across runs: if the pair is already in ``models`` (from
    # a partial prior run), skip it; otherwise allocate the next id. The
    # cache + INSERT in ModelsRepository (§8.1) layers the same probe on top
    # for runtime writes.
    existing = await sqlProvider.executeFetchOne(
        "SELECT model_id FROM models WHERE model = :model AND dimensions = :dimensions",
        {"model": modelName, "dimensions": dims},
    )
    if existing is not None:
        continue

    idRow = await sqlProvider.executeFetchOne(
        "SELECT COALESCE(MAX(model_id), 0) + 1 AS nextId FROM models"
    )
    nextId: int = int(idRow["nextId"])
    # Plain INSERT is safe here because the probe above guaranteed the pair
    # is absent; the UNIQUE constraint is the defensive second guard in case
    # of a concurrent writer (not possible in the single-process app, but
    # the constraint costs nothing and matches the cross-RDBMS contract).
    await sqlProvider.execute(
        "INSERT INTO models (model_id, model, dimensions, created_at) "
        "VALUES (:modelId, :model, :dimensions, :createdAt)",
        {"modelId": nextId, "model": modelName, "dimensions": dims, "createdAt": now},
    )
```

Rows from `message_embeddings` and `user_memories` are de-duplicated by the
in-run `seen` set; the **probe-then-insert** pattern (NOT the UNIQUE
constraint alone) is what makes the loop safe to re-run after a partial
failure — a plain `INSERT` against an already-present pair would raise
`IntegrityError` on the UNIQUE constraint, and the migration framework
does not wrap `up()` in a transaction (verified in
[`internal/database/migrations/manager.py`](../../internal/database/migrations/manager.py)
lines 285-300 — `_setVersion` is only called after `up()` returns, so a
crash mid-loop leaves the schema half-migrated with the version pointer
unchanged, and the next run re-enters `up()` from the top with a fresh
`seen` set).

### Step 3 — Swap `user_memories` (temp-table pattern from `migration_013`)

```python
await sqlProvider.batchExecute([
    # 3a. Create the new shape
    ParametrizedQuery("""
        CREATE TABLE user_memories_new (
            chat_id    INTEGER   NOT NULL,
            user_id    INTEGER   NOT NULL,
            thread_id  INTEGER,
            memory_id  TEXT      NOT NULL,
            type       TEXT      NOT NULL,
            content    TEXT      NOT NULL,
            tags       TEXT      NOT NULL DEFAULT '[]',
            permanent  INTEGER   NOT NULL DEFAULT 0,
            source     TEXT      NOT NULL DEFAULT 'refinement',
            deleted_at TIMESTAMP,
            model_id   INTEGER,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            PRIMARY KEY (chat_id, user_id, memory_id)
        )
    """),
    # 3b. Backfill with LEFT JOIN to models. Rows where embedding_model was
    #     NULL (never embedded) get model_id = NULL via the LEFT JOIN miss.
    ParametrizedQuery("""
        INSERT INTO user_memories_new (
            chat_id, user_id, thread_id, memory_id, type, content, tags,
            permanent, source, deleted_at, model_id, created_at, updated_at
        )
        SELECT
            um.chat_id, um.user_id, um.thread_id, um.memory_id, um.type,
            um.content, um.tags, um.permanent, um.source, um.deleted_at,
            m.model_id, um.created_at, um.updated_at
        FROM user_memories um
        LEFT JOIN models m
            ON m.model = um.embedding_model
            AND m.dimensions = um.embedding_dimensions
    """),
    ParametrizedQuery("DROP TABLE user_memories"),
    ParametrizedQuery("ALTER TABLE user_memories_new RENAME TO user_memories"),
    # 3c. Recreate the three indexes from migration_020
    ParametrizedQuery("""
        CREATE INDEX IF NOT EXISTS idx_user_memories_chat_user_thread
            ON user_memories (chat_id, user_id, thread_id, updated_at DESC)
    """),
    ParametrizedQuery("""
        CREATE INDEX IF NOT EXISTS idx_user_memories_chat_user_permanent
            ON user_memories (chat_id, user_id, permanent, updated_at DESC)
    """),
    ParametrizedQuery("""
        CREATE INDEX IF NOT EXISTS idx_user_memories_type
            ON user_memories (chat_id, user_id, type)
    """),
])
```

### Step 4 — Swap `chat_messages` (temp-table pattern)

```python
await sqlProvider.batchExecute([
    # 4a. Create the new shape — model_id appended after created_at
    ParametrizedQuery("""
        CREATE TABLE chat_messages_new (
            chat_id          INTEGER NOT NULL,
            message_id       TEXT NOT NULL,
            date             TIMESTAMP NOT NULL,
            user_id          INTEGER NOT NULL,
            reply_id         TEXT,
            thread_id        INTEGER NOT NULL DEFAULT 0,
            root_message_id  TEXT,
            message_text     TEXT NOT NULL,
            message_type     TEXT DEFAULT 'text' NOT NULL,
            message_category TEXT DEFAULT 'user' NOT NULL,
            quote_text       TEXT,
            media_id         TEXT,
            media_group_id   TEXT,
            markup           TEXT DEFAULT "" NOT NULL,
            metadata         TEXT DEFAULT "" NOT NULL,
            created_at       TIMESTAMP NOT NULL,
            model_id         INTEGER,
            PRIMARY KEY (chat_id, message_id)
        )
    """),
    # 4b. Backfill via message_embeddings → models LEFT JOIN chain.
    #     Rows that never had a message_embeddings row get model_id = NULL.
    ParametrizedQuery("""
        INSERT INTO chat_messages_new (
            chat_id, message_id, date, user_id, reply_id, thread_id,
            root_message_id, message_text, message_type, message_category,
            quote_text, media_id, media_group_id, markup, metadata,
            created_at, model_id
        )
        SELECT
            c.chat_id, c.message_id, c.date, c.user_id, c.reply_id, c.thread_id,
            c.root_message_id, c.message_text, c.message_type, c.message_category,
            c.quote_text, c.media_id, c.media_group_id, c.markup, c.metadata,
            c.created_at, m.model_id
        FROM chat_messages c
        LEFT JOIN message_embeddings me
            ON me.chat_id = c.chat_id AND me.message_id = c.message_id
        LEFT JOIN models m
            ON m.model = me.model AND m.dimensions = me.dimensions
    """),
    ParametrizedQuery("DROP TABLE chat_messages"),
    ParametrizedQuery("ALTER TABLE chat_messages_new RENAME TO chat_messages"),
    # 4c. No dedicated chat_messages indexes exist today (verified by grep
    #     across internal/database/migrations/versions/). Nothing to recreate.
])
```

### Step 5 — Drop `message_embeddings` (and its index from `migration_018`)

```python
await sqlProvider.batchExecute([
    ParametrizedQuery("DROP INDEX IF EXISTS idx_message_embeddings_chat_model"),
    ParametrizedQuery("DROP TABLE IF EXISTS message_embeddings"),
])
```

### Step 6 — Drop both vec0 families (enumerate via `sqlProvider.listTables`)

vec0 shadow tables (`vec_*_chunks`, `vec_*_rowids`, `vec_*_info`) are dropped
implicitly with their parent virtual table on SQLite. Enumerate parents
through the provider abstraction — `BaseSQLProvider.listTables(likePattern)`
already abstracts the per-dialect introspection query (see
[`internal/database/providers/base.py`](../../internal/database/providers/base.py)
line 558), and the existing `ChatEmbeddingsRepository.deleteObsoleteModelEmbeddings`
at [`chat_embeddings.py:420`](../../internal/database/repositories/chat_embeddings.py)
already uses `sqlProvider.listTables("vec_message_embeddings_%")` for the
same purpose. The migration should follow that precedent so its reads go
through the provider abstraction and stay portable when the PostgreSQL /
MySQL providers are wired up. A Python-side regex filter narrows the LIKE
result to the strict `_<digits>` suffix shape (defensive against a stray
non-numeric suffix):

```python
import re

vecTableNamePattern = re.compile(r"^vec_(message_embeddings|user_memories)_\d+$")

# Primary form — go through the provider. listTables maps to
# sqlite_master on SQLite, information_schema on PostgreSQL/MySQL.
candidates = (
    await sqlProvider.listTables("vec_message_embeddings_%")
    + await sqlProvider.listTables("vec_user_memories_%")
)
toDrop = [name for name in candidates if vecTableNamePattern.match(name)]

if toDrop:
    dropStatements = [ParametrizedQuery(f"DROP TABLE IF EXISTS {name}") for name in toDrop]
    await sqlProvider.batchExecute(dropStatements)
```

If `listTables` is ever unavailable on the configured provider (the default
`BaseSQLProvider` implementation raises `NotImplementedError`), the
SQLite-specific raw form below is the concrete fallback — keep it as a
comment-labelled branch in the implementation, not the primary path:

```python
# Fallback (SQLite-only — do NOT use as the primary form; prefer
# sqlProvider.listTables above). Shown for concreteness only.
# allTables = await sqlProvider.executeFetchAll(
#     "SELECT name FROM sqlite_master WHERE type='table'"
# )
# toDrop = [row["name"] for row in allTables if vecTableNamePattern.match(row["name"])]
```

### `down()` strategy (honestly lossy on the vec0 side)

```python
async def down(self, sqlProvider: BaseSQLProvider) -> None:
    """Best-effort rollback.

    Restores the pre-refactor SQL shape:
    - re-creates message_embeddings EMPTY (vectors cannot be regenerated
      from model_id alone — the float32 BLOBs were dropped in up()).
    - restores user_memories.embedding_model / embedding_dimensions columns
      as NULL via temp-table swap.
    - restores chat_messages without model_id via temp-table swap.
    - drops the models table.

    The vec_message_embeddings_* and vec_user_memories_* virtual tables are
    NOT recreated here — they are lazily created at runtime regardless of
    schema version, and the vectors they held before up() ran are gone.
    Downgrading therefore yields a system with empty vector stores that
    will repopulate via the normal backfill cron. Document this clearly to
    operators: down() is schema-correct but data-lossy for search until
    re-embedding catches up.
    """
```

The `down()` body re-creates `message_embeddings` empty (DDL from
`migration_017`), temp-table-swaps `user_memories` back to the
`embedding_model`/`embedding_dimensions` shape (all NULL), temp-table-swaps
`chat_messages` back to the pre-`model_id` shape, and `DROP TABLE models`.
It does NOT attempt to restore vec0 data — that is irrecoverable.

## 7. TypedDict changes

In [`internal/database/models.py`](../../internal/database/models.py):

- **NEW** `ModelDict`:
  ```python
  class ModelDict(TypedDict):
      """Row in the ``models`` lookup table.

      Attributes:
          model_id: App-generated sequential integer primary key.
          model: Embedding model name string (e.g. the resolved value of the
              ``EMBEDDING_MODEL`` chat setting).
          dimensions: Vector dimensionality (e.g. 384, 1024).
          created_at: Row creation timestamp.
      """
      model_id: int
      model: str
      dimensions: int
      created_at: datetime.datetime
  ```
- **CHANGE** `UserMemoryDict` (lines ~551-599): drop `embedding_model:
  Optional[str]` and `embedding_dimensions: Optional[int]`, add
  `model_id: Optional[int]` ("``None`` when the memory has not been embedded
  yet"). Update the class docstring's `Attributes:` block correspondingly.
- **CHANGE** `ChatMessageDict` (lines ~108-160): add `model_id:
  Optional[int]` ("Embedding model lookup key; ``None`` when the message has
  not been embedded yet. Absent on rows produced before
  ``migration_025``"). Place it next to `created_at` to mirror the physical
  column order after the swap.
- **DROP** `MessageEmbeddingDict` (lines ~189-212) — the backing table is
  gone. Verify zero remaining imports via
  `rg "MessageEmbeddingDict" internal/ lib/ tests/` after the change; the
  only current importer is `chat_embeddings.py:34`.

## 8. Code changes — per file

Conventions for all snippets below: camelCase methods/params, PascalCase
classes, docstrings with `Args:` / `Returns:` on every public method, type
hints everywhere, no `Any` (except genuine passthrough). Imports at the top
of the file — no in-method imports.

### 8.1 NEW `internal/database/repositories/models.py`

```python
"""Repository for the ``models`` embedding-provenance lookup table.

Provides :meth:`ModelsRepository.getOrCreateModelId` — the app-side
allocation point for the small integer that identifies a distinct
``(model, dimensions)`` pair. Every embedding write resolves its
``model_id`` through this method.
"""

import logging
from typing import Dict, List, Optional, Tuple

import lib.utils as libUtils

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import ModelDict
from ..providers.base import BaseSQLProvider
from .base import BaseRepository

logger = logging.getLogger(__name__)


class ModelsRepository(BaseRepository):
    """Lookup and allocation for the ``models`` table.

    Holds a process-local cache ``{(model, dimensions): model_id}`` so the
    common path (a hot model that's already been allocated) is a single
    dict hit and skips the DB round-trip entirely. The cache is
    per-instance; Gromozeka is a single-process app, so there is no
    cross-writer hazard.

    Attributes:
        _cache: Process-local ``{(model, dimensions): model_id}`` map.
    """

    __slots__ = ("manager", "_cache")

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialise the repository with an empty cache.

        Args:
            manager: Database manager instance for provider access.
        """
        super().__init__(manager)
        self._cache: Dict[Tuple[str, int], int] = {}

    async def getOrCreateModelId(self, model: str, dimensions: int) -> int:
        """Return the ``model_id`` for *model*/*dimensions*, allocating one if needed.

        Cache-first: a hit returns immediately. On miss, allocate the next
        sequential id (``COALESCE(MAX(model_id), 0) + 1``), call
        ``provider.upsert(..., updateExpressions={})`` (portable
        ``ON CONFLICT DO NOTHING`` — see below), then ``SELECT`` back the
        canonical id (handles the race where another row sneaked in between
        the MAX and the INSERT). Cache and return.

        Args:
            model: Embedding model name string.
            dimensions: Vector dimensionality.

        Returns:
            The integer ``model_id``.
        """
        cacheKey = (model, dimensions)
        cached = self._cache.get(cacheKey)
        if cached is not None:
            return cached

        sqlProvider = await self.manager.getProvider(readonly=False)
        now = libUtils.now()

        # Allocate next id app-side (AGENTS.md: never delegate ID generation
        # to the DB). ``upsert(..., updateExpressions={})`` maps to
        # ``ON CONFLICT(model, dimensions) DO NOTHING`` on every provider
        # (verified in ``SQLite3Provider.upsert`` at
        # internal/database/providers/sqlite3.py:426-439 — empty
        # updateExpressions triggers the DO NOTHING branch). The subsequent
        # SELECT-back returns the canonical id regardless of whether the
        # INSERT actually inserted or was short-circuited by the conflict.
        idRow = await sqlProvider.executeFetchOne(
            "SELECT COALESCE(MAX(model_id), 0) + 1 AS nextId FROM models"
        )
        nextId = int(idRow["nextId"])
        await sqlProvider.upsert(
            table="models",
            values={
                "model_id": nextId,
                "model": model,
                "dimensions": dimensions,
                "created_at": now,
            },
            conflictColumns=["model", "dimensions"],
            updateExpressions={},  # DO NOTHING on conflict — see base.py:426-439
        )
        canonical = await sqlProvider.executeFetchOne(
            "SELECT model_id FROM models WHERE model = :model AND dimensions = :dimensions",
            {"model": model, "dimensions": dimensions},
        )
        modelId = int(canonical["model_id"])
        self._cache[cacheKey] = modelId
        return modelId

    async def getModelById(self, modelId: int) -> Optional[ModelDict]:
        """Fetch a single model row by id (diagnostic/admin use).

        Args:
            modelId: The model_id primary key.

        Returns:
            :class:`ModelDict` or ``None`` if not found.
        """
        sqlProvider = await self.manager.getProvider(readonly=True)
        row = await sqlProvider.executeFetchOne(
            "SELECT model_id, model, dimensions, created_at FROM models WHERE model_id = :modelId",
            {"modelId": modelId},
        )
        if row is None:
            return None
        # Convert the raw provider row into the typed dict shape — this is
        # the repo convention in this codebase (see
        # ``ChatEmbeddingsRepository.getMessageEmbedding`` which post-decodes
        # the BLOB then calls ``dbUtils.sqlToTypedDict``). Repositories
        # return typed dicts, not raw rows.
        return dbUtils.sqlToTypedDict(row, ModelDict)

    async def listModels(self) -> List[ModelDict]:
        """List all known models (diagnostic/admin use).

        Returns:
            List of :class:`ModelDict` rows ordered by ``model_id``.
        """
        sqlProvider = await self.manager.getProvider(readonly=True)
        rows = await sqlProvider.executeFetchAll(
            "SELECT model_id, model, dimensions, created_at FROM models ORDER BY model_id"
        )
        return [dbUtils.sqlToTypedDict(row, ModelDict) for row in rows]
```

**Portability note (resolved):** the original draft proposed a raw
`INSERT OR IGNORE INTO models ...` (SQLite dialect) plus a new
`BaseSQLProvider.insertOrIgnore(...)` helper to wrap the dialect variants
(SQLite `INSERT OR IGNORE`, PostgreSQL/MySQL `INSERT ... ON CONFLICT ... DO
NOTHING`). This is unnecessary — `BaseSQLProvider.upsert(table, values,
conflictColumns, updateExpressions={})` already implements the
`ON CONFLICT ... DO NOTHING` semantics portably (see
[`SQLite3Provider.upsert`](../../internal/database/providers/sqlite3.py)
lines 426-439: an empty `updateExpressions` dict triggers the DO-NOTHING
branch). The plan therefore goes through `provider.upsert(...)` and the
`insertOrIgnore` helper is **not** added. See Risk R5 in §13 (resolved).

### 8.2 `internal/database/repositories/__init__.py`

Add `from .models import ModelsRepository` (alphabetical: before
`from .spam`), and add `"ModelsRepository"` to the `__all__` list (before
`"SpamRepository"`).

### 8.3 `internal/database/database.py`

Following the existing wiring pattern (lines ~204-218):

1. Add the import: `from .repositories.models import ModelsRepository`
   alongside the other repo imports.
2. Add `"models"` to the module-level `__all__`-equivalent list (the one
   that contains `"webhookUpdates"` at line ~124).
3. Add a class-level type annotation in the `Database` class body (near
   line ~175, next to `webhookUpdates: WebhookUpdatesRepository`):
   ```python
   models: ModelsRepository
   """Repository for the ``models`` embedding-provenance lookup table."""
   ```
4. Instantiate in `__init__` (near line ~218, next to
   `self.webhookUpdates = ...`):
   ```python
   self.models = ModelsRepository(self.manager)
   ```
5. **Inject the `getOrCreateModelId` resolver into the three consuming
   repos** (Decision D10). The `ModelsRepository` instance must be
   constructed **before** `ChatEmbeddingsRepository`,
   `ChatSearchRepository`, and `UserMemoriesRepository`, and its
   `getOrCreateModelId` bound method passed into their constructors:
   ```python
   self.models = ModelsRepository(self.manager)
   # ... chatEmbeddings / chatSearch / userMemories constructed after self.models ...
   self.chatEmbeddings = ChatEmbeddingsRepository(
       self.manager, modelIdResolver=self.models.getOrCreateModelId
   )
   self.chatSearch = ChatSearchRepository(
       self.manager, modelIdResolver=self.models.getOrCreateModelId
   )
   self.userMemories = UserMemoriesRepository(
       self.manager, modelIdResolver=self.models.getOrCreateModelId
   )
   ```
   The consuming repos' existing `__init__(self, manager: DatabaseManager)`
   signatures gain one keyword parameter (see §8.4 / §8.5 / §8.6 for the
   exact shapes). The bound-method form is preferred over passing the
   `ModelsRepository` instance directly: it keeps the consuming repo's
   dependency surface to a single callable, which is trivially mockable
   in tests. `ChatSearchRepository` is on the list because D6 was
   extended to keep `searchChatMessages(..., modelName=...)` stable
   (the repo resolves the id internally before the vec0 lookup).

### 8.4 `internal/database/repositories/chat_embeddings.py`

- **Imports:** drop `from ..models import ... MessageEmbeddingDict` (line
  34). Keep `ChatMessageDict`. Add `array` stays (still used for vec0 byte
  serialisation). Add `from ..models import ModelDict` only if needed for
  type hints in new helpers. Add `from typing import Callable, Awaitable`
  for the resolver signature (see constructor change below).
- **`__init__` signature (Decision D10):** gains one keyword parameter:
  ```python
  def __init__(
      self,
      manager: DatabaseManager,
      *,
      modelIdResolver: Callable[[str, int], Awaitable[int]],
  ) -> None:
      """Initialize the chat embeddings repository.

      Args:
          manager: Database manager instance for provider access.
          modelIdResolver: Callable that resolves ``(modelName, dimensions)``
              to a ``model_id`` integer. Wired in
              :meth:`Database.__init__` to
              ``ModelsRepository.getOrCreateModelId`` (the bound method).
              Tests inject a mock.
      """
      super().__init__(manager)
      self._modelIdResolver = modelIdResolver
  ```
  **`__slots__` change (concrete edit, not a Phase-3 deferral):** the
  existing `__slots__ = ()` at
  [`chat_embeddings.py:59`](../../internal/database/repositories/chat_embeddings.py)
  must change to `__slots__ = ("_modelIdResolver",)`. The instance
  assignment `self._modelIdResolver = modelIdResolver` in the new
  `__init__` body will raise `AttributeError` against an empty slot
  tuple — this is the load-bearing reason the slot list must change
  alongside the constructor. Verify the corresponding slot change in
  `user_memories.py` and `chat_search.py` (their `BaseRepository`
  inherits may or may not declare `__slots__` — check at edit time;
  `internal/database/repositories/base.py` is the source of truth).
- **`_resolveModelId` private helper (new):** thin wrapper around the
  injected resolver:
  ```python
  async def _resolveModelId(self, model: str, dimensions: int) -> int:
      """Resolve ``(model, dimensions)`` to a ``model_id`` via the injected resolver.

      Args:
          model: Embedding model name string.
          dimensions: Vector dimensionality.

      Returns:
          The integer ``model_id``.
      """
      return await self._modelIdResolver(model, dimensions)
  ```
- **`saveMessageEmbedding(chatId, messageId, embedding, model, *,
  date=None) -> bool`** (lines 72-164): signature unchanged at the public
  boundary (Decision D6). New body:
  ```python
  dimensions = len(embedding)
  blob = array.array("f", embedding).tobytes()
  sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

  # Resolve model_id via ModelsRepository (Decision D2/D6).
  modelId = await self._resolveModelId(model, dimensions)

  # UPDATE chat_messages.model_id (the row already exists — this is not an upsert).
  await sqlProvider.execute(
      "UPDATE chat_messages SET model_id = :modelId "
      "WHERE chat_id = :chatId AND message_id = :messageId",
      {"modelId": modelId, "chatId": chatId, "messageId": messageId.asStr()},
  )

  # Dual-write to vec0 (same shape as before, but model_id replaces model).
  if await sqlProvider.isVectorSearchSupported():
      try:
          actualDate = date if date is not None else libUtils.now().isoformat()
          await self._upsertVecMessageEmbedding(
              sqlProvider=sqlProvider, chatId=chatId, messageId=messageId.asStr(),
              modelId=modelId, date=actualDate, embedding=blob, dimensions=dimensions,
          )
      except Exception:
          logger.error("Failed to write vec0 embedding for chat %s message %s",
                       chatId, messageId, exc_info=True)
  return True
  ```
  where `_resolveModelId` is the thin private helper defined above that
  delegates to the injected `modelIdResolver` (see the constructor
  signature change earlier in this section).
- **`_upsertVecMessageEmbedding(...)`** (lines 166-263): change the
  `model: str` parameter to `modelId: int`. The `createVectorTable` column
  list changes `model TEXT PARTITION KEY` → `model_id INTEGER PARTITION
  KEY`. DELETE/INSERT SQL uses `model_id = :modelId` instead of
  `model = :model`.
- **DROP** `getMessageEmbedding` (lines 265-314) and
  `deleteChatEmbeddings` (lines 316-335) — no production callers (verified
  by the brief). Tests that reference them are rewritten (see §10).
- **`deleteObsoleteModelEmbeddings(chatId, currentModel: str, *,
  currentDimensions: Optional[int]=None) -> bool`** (lines 337-464):
  **signature unchanged per extended D6** — handler callers keep passing
  `(currentModel, currentDimensions)`. Body resolves internally:
  ```python
  if currentDimensions is not None:
      # Both known → resolve a single canonical id.
      currentModelId = await self._resolveModelId(currentModel, currentDimensions)
      await sqlProvider.execute(
          "UPDATE chat_messages SET model_id = NULL "
          "WHERE chat_id = :chatId AND model_id IS NOT NULL AND model_id != :currentModelId",
          {"chatId": chatId, "currentModelId": currentModelId},
      )
  else:
      # Dimensions unknown (OpenAI-style model) → use a subquery against
      # the models table. Semantically equivalent to today's
      # ``model != :currentModel`` predicate.
      await sqlProvider.execute(
          "UPDATE chat_messages SET model_id = NULL "
          "WHERE chat_id = :chatId "
          "AND model_id IS NOT NULL "
          "AND model_id NOT IN (SELECT model_id FROM models WHERE model = :currentModel)",
          {"chatId": chatId, "currentModel": currentModel},
      )
  # vec0 cleanup: same predicate shape, per-table loop unchanged.
  # When dimensions are known, skip the matching-dim vec0 table (its rows
  # belong to the current model). When dimensions are None, clean every
  # vec_message_embeddings_{N} table for the chat.
  ```
- **`getMessagesWithoutEmbeddings(chatId, *, limit=100,
  modelName: Optional[str]=None, dimensions: Optional[int]=None,
  dataSource=None) -> List[ChatMessageDict]`** (lines 466-558):
  **signature unchanged per extended D6.** Body becomes a single-table
  query against `chat_messages` (no more `NOT EXISTS` against
  `message_embeddings`):
  ```python
  if modelName is not None and dimensions is not None:
      currentModelId = await self._resolveModelId(modelName, dimensions)
      predicate = "(c.model_id IS NULL OR c.model_id != :currentModelId)"
      params = {"chatId": chatId, "currentModelId": currentModelId}
  elif modelName is not None:
      # Dimensions unknown → subquery against models.
      predicate = (
          "(c.model_id IS NULL OR c.model_id NOT IN "
          "(SELECT model_id FROM models WHERE model = :modelName))"
      )
      params = {"chatId": chatId, "modelName": modelName}
  else:
      predicate = "c.model_id IS NULL"
      params = {"chatId": chatId}
  query = f"""
      SELECT c.*, u.username, u.full_name
      FROM chat_messages c
      JOIN chat_users u
          ON u.chat_id = c.chat_id AND u.user_id = c.user_id
      WHERE c.chat_id = :chatId AND c.message_text IS NOT NULL AND c.message_text != ''
          AND {predicate}
      ORDER BY c.date DESC, c.message_id DESC
  """
  query = sqlProvider.applyPagination(query=query, limit=int(limit))
  ```
  The `JOIN chat_users` is kept because the return shape is
  `ChatMessageDict` which carries `username`/`full_name` — existing
  contract preserved.

### 8.5 `internal/database/repositories/chat_search.py`

This repo gains the same constructor-injected `modelIdResolver` as
`ChatEmbeddingsRepository` (see §8.4 — Decision D10 extended during
self-review). The `_resolveModelId` private helper is added identically.
`__slots__` audit: same as §8.4 — if `ChatSearchRepository` declares
`__slots__`, add `_modelIdResolver` to the tuple.

- **Imports:** drop `import numpy as np` (line 32). Audit lines 14, 109,
  328, 366-367, 401-408, 729-734, 738, 747, 752, 786, 816, 831 for stale
  numpy references in comments/docstrings and rewrite them.
- **Lines 485-553:** DELETE `_loadEmbeddingsFromDb` entirely.
- **`_semanticSearch(...)`** (lines 303-483): collapse the fallback
  ladder. Keep the vec0 path; on `isVectorSearchSupported() == False`, on
  exception in `_nativeVectorSearch`, OR on empty result, return `[]`. The
  numpy block (lines 410-480) is removed. Update the method docstring to
  state the new contract: "Returns ``[]`` when vec0 is unavailable,
  raises, or yields no matches. There is no in-process fallback.".
- **`_nativeVectorSearch(...)`** (lines 707-905): vec0 filter changes from
  `model = :modelName` to `model_id = :modelId`. **Per D6, the
  `modelName: Optional[str]` param stays at the public-boundary
  `searchChatMessages` dispatcher; `_nativeVectorSearch` is a private
  helper and resolves internally** — `modelId =
  await self._resolveModelId(modelName, len(queryEmbedding))` when both
  are available, `None` otherwise (which short-circuits to `[]` exactly as
  today's `modelName is None` branch does). The `maxMessages` cutoff
  query (which currently does `JOIN message_embeddings me ON ...`)
  changes to a single-table query against `chat_messages`:
  ```sql
  SELECT message_id, date FROM chat_messages
  WHERE chat_id = :chatId AND model_id = :modelId
  ORDER BY date DESC, message_id DESC
  ```
  **numpy removal (line 793):** the query-norm guard
  `queryNorm = float(np.linalg.norm(np.asarray(queryEmbedding, dtype=np.float32)))`
  is the SECOND numpy use in this file (the first being the cosine block
  at lines 410-480). It is replaced with
  `math.sqrt(sum(x * x for x in queryEmbedding))` — same pure-Python form
  the memory side adopts at `user_memories.py:872`. Add `import math` at
  the top of the file. This was missed in the original draft and surfaces
  during self-review (the draft would have left a dangling `np.linalg.norm`
  reference after `import numpy as np` was removed).
- **`searchChatMessages(...)` dispatcher:** **signature unchanged**
  (Decision D6). The `modelName: Optional[str]` param stays; the repo
  resolves to `modelId` internally via `_resolveModelId(modelName,
  len(queryEmbedding))` and threads it into `_nativeVectorSearch`. When
  `queryEmbedding is None` (filter-only mode) or `modelName is None`,
  `modelId` is `None` and the semantic path returns `[]` exactly as today.
  Handlers therefore need **zero changes** at the call sites (the
  `/search` slash-command path at `chat_search.py:1338-1348` AND the
  LLM-tool path at `chat_search.py:725-736` both keep passing
  `modelName=...`). This eliminates the contradiction flagged in
  self-review — the original draft's "signature becomes
  `modelId: Optional[int]`" would have forced both call sites to resolve,
  breaking D6.

### 8.6 `internal/database/repositories/user_memories.py`

- **Line 52:** `import numpy` — **REMOVED** (Decision D8 — numpy fully
  retired). Replace the single `numpy.linalg.norm` use at line ~872 with
  `math.sqrt(sum(x*x for x in queryEmbedding))`; add `import math` at the
  top of the file (verify it isn't already imported). See Phase 4 in §11.
- **`__init__` signature (Decision D10):** gains one keyword parameter,
  mirroring the `ChatEmbeddingsRepository` change in §8.4:
  ```python
  def __init__(
      self,
      manager: DatabaseManager,
      *,
      modelIdResolver: Callable[[str, int], Awaitable[int]],
  ) -> None:
      """Initialize the user memories repository.

      Args:
          manager: Database manager instance for provider access.
          modelIdResolver: Callable that resolves ``(modelName, dimensions)``
              to a ``model_id`` integer. Wired in :meth:`Database.__init__`
              to ``ModelsRepository.getOrCreateModelId``. Tests inject a mock.
      """
      super().__init__(manager)
      self._modelIdResolver = modelIdResolver
  ```
   Add `from typing import Callable, Awaitable` to the imports at the top
   of the file (verify it isn't already there). The same private
   `_resolveModelId(self, model, dimensions)` helper as in §8.4 is added
   here — `return await self._modelIdResolver(model, dimensions)`.
   **`__slots__` audit:** same concrete edit as §8.4 — if
   `UserMemoriesRepository` declares `__slots__` (check at edit time;
   inherit through `BaseRepository`), add `_modelIdResolver` to the tuple
   so the new instance attribute can be set.
- **Lines 74-78 `_SELECT_COLUMNS`:** replace `embedding_model,
  embedding_dimensions` with `model_id`. The full constant becomes:
  ```python
  _SELECT_COLUMNS: str = (
      "chat_id, user_id, thread_id, memory_id, type, content, tags, "
      "permanent, source, model_id, "
      "created_at, updated_at"
  )
  ```
  (`deleted_at` is intentionally NOT in this constant — confirmed during
  self-review by reading every consumer: `deleted_at` is filtered on
  (`WHERE deleted_at IS NULL`) by the read methods, never returned in the
  row shape, and is absent from `UserMemoryDict`. The migration's
  temp-table swap in §6 Step 3 preserves `deleted_at` as a column, but
  it remains outside `_SELECT_COLUMNS`. Q4 in §13 is resolved
  affirmatively by this verification.)
- **`addMemory(...)`** (lines ~156+): **signature unchanged per extended
  D6** — keep `embedding: Optional[List[float]]` and
  `embeddingModel: Optional[str]` params (handler callers at
  `user_memories.py:533-545` and `:2670-2682` pass both). The INSERT
  column list drops `embedding_model, embedding_dimensions` (the row's
  `model_id` takes its DEFAULT NULL — matches today's behaviour where the
  INSERT explicitly wrote `NULL, NULL` for the provenance pair, then
  `saveMemoryEmbedding` filled them in via UPDATE). The conditional call
  to `saveMemoryEmbedding` at lines 230-237 is unchanged.
- **`saveMemoryEmbedding(chatId, userId, memoryId, embedding,
  embeddingModel: str)`:** per extended D6, keep the public param name
  `embeddingModel` (string) — minimum handler churn. Internally resolve
  to `modelId = await self._resolveModelId(embeddingModel, len(embedding))`
  and UPDATE `user_memories SET model_id = :modelId, updated_at = :now
  WHERE ...`.
- **`_upsertVecMemoryEmbedding(...)`** (lines ~1162-1186): new DDL gains
  `model_id INTEGER PARTITION KEY` (the memories vec0 table had no model
  partition before — see §4.4 and Decision D9). INSERT carries `model_id`.
- **`deleteMemoryEmbedding(...)`** (lines ~1251+): UPDATE
  `SET model_id = NULL` replaces `SET embedding_model = NULL,
  embedding_dimensions = NULL`.
- **`deleteObsoleteMemoryEmbeddings(chatId, currentModel: str,
  currentDimensions: Optional[int]) -> int`** (lines ~1430+):
  **signature unchanged per extended D6.** Predicate resolves internally
  — when `currentDimensions is not None`, resolve a single `model_id` and
  use `model_id != :currentModelId`; when `currentDimensions is None`,
  use `model_id NOT IN (SELECT model_id FROM models WHERE model =
  :currentModel)`. Plus `deleted_at IS NULL` filter as today.
- **`getMemoriesWithoutEmbeddings(chatId, *, limit=50, modelName:
  Optional[str]=None, dimensions: Optional[int]=None, dataSource=None)
  -> List[UserMemoryDict]`:** **signature unchanged per extended D6.**
  Predicate shape mirrors the `getMessagesWithoutEmbeddings` pattern in
  §8.4 — three-branch resolution (both known → single id, modelName only
  → subquery, both None → match NULL).
- **`searchMemories(...)` and `_semanticSearchMemories(...)`:** the
  public `embeddingModel: str` arg is kept per extended D6; resolve
  internally to `modelId = await self._resolveModelId(embeddingModel,
  len(queryEmbedding))`. vec0 filter changes to `model_id = :modelId`.
  **The `numpy.linalg.norm` use at line ~872 is replaced with
  `math.sqrt(sum(x*x for x in queryEmbedding))` per Decision D8** (Q1
  resolved affirmatively).
- **`UserMemoryDict`** shape updated per §7.

### 8.7 `internal/bot/common/handlers/message_preprocessor.py`

Per Decision D6, **no changes required** at lines 114-121 (the
`searchMemories(..., embeddingModel=embeddingModel, ...)` call) and 210-216
(the `saveMessageEmbedding(..., model=embeddings[0], ...)` call). The
handler continues to pass the model name string; resolution to `model_id`
is the repo's job. This is the blast-radius-minimising choice.

**Caveat:** the repo resolver IS injected via constructor (Decision D10 —
Q3 resolved). The handler itself does not change, but the repo constructor
signature does, and any test that directly instantiates the repo must be
updated to pass the `modelIdResolver` (see §8.4 / §8.5 / §8.6 for the new
constructor shape; a mock resolver is the test-time stand-in).

### 8.8 `internal/bot/common/handlers/chat_search.py`

Per D6 (extended during self-review), **every call site in this handler
needs zero changes**:

- Lines ~476-480 — `deleteObsoleteModelEmbeddings(chatId, currentModel=modelName, currentDimensions=currentDims)`: signature kept stable; repo resolves `(currentModel, currentDimensions)` to `model_id` internally (the `currentDimensions is None` case uses a `NOT IN (SELECT model_id FROM models WHERE model = :currentModel)` subquery).
- Lines ~491-496 — `getMessagesWithoutEmbeddings(chatId, limit, modelName=modelName, dimensions=currentDims)`: same — repo-side resolution.
- Lines ~558-564 — `saveMessageEmbedding(..., model=...)`: unchanged.
- Lines ~725-736 — `searchChatMessages(..., modelName=queryEmbedding[0] if queryEmbedding else None)`: unchanged (the original draft's `modelId: Optional[int]` flip was reverted in self-review).
- Lines ~1338-1348 — `/search` slash-command caller `searchChatMessages(..., modelName=embeddingModelName)`: unchanged.

This is a substantive change from the original draft, which singled out
the `/search` slash-command caller (line ~1322) as the one site that D6
could not shield (Risk R2). With D6 extended to `searchChatMessages`, that
exception is gone — see Risk R2 in §13 (resolved during self-review).

### 8.9 `internal/bot/common/handlers/user_memories.py`

Per D6 (extended during self-review), the ~14 call sites at lines 476-545,
598-634, 723-733, 874-893, 920-926, 1870-1893, 2220, 2670-2682, 2889-2896
should require **no changes**:

- Lines 874-878 — `deleteObsoleteMemoryEmbeddings(chatId, currentModel=modelName, currentDimensions=currentDims)`: repo-side resolution.
- Lines 888-893 — `getMemoriesWithoutEmbeddings(chatId, limit, modelName=modelName, dimensions=currentDims)`: repo-side resolution.
- Every `saveMemoryEmbedding(..., embeddingModel=...)`, `searchMemories(..., embeddingModel=...)`, `addMemory(...)`: unchanged.

Verify each site during Phase 5; the contract is "zero handler lines
change". (Original draft mentioned dropping a `dimensions=...` arg —
unnecessary under extended D6.)

### 8.10 `scripts/clear_memory_embeddings.py`

Line 293 raw SQL changes:
```python
# Before:
conn.execute("UPDATE user_memories SET embedding_model = NULL, embedding_dimensions = NULL")
# After:
conn.execute("UPDATE user_memories SET model_id = NULL")
```
Update the docstring at lines 8-9 and 24-25 to reference `model_id`
instead of the provenance pair. The `DROP TABLE vec_user_memories_{N}`
logic at line ~293 is unchanged in shape. Test file
[`tests/scripts/test_clear_memory_embeddings.py`](../../tests/scripts/test_clear_memory_embeddings.py)
updates its assertions correspondingly.

## 9. `LLMService.generateEmbedding` impact

**None.** The signature
`generateEmbedding(text: str, *, chatId: int, chatSettings: ...) -> Optional[Tuple[str, List[float]]]`
and the `(modelName, vector)` return shape are unchanged. Downstream
resolution from `modelName` to `model_id` is the repository's job (Decision
D6). [`lib/ai/`](../../lib/ai/) is not touched by this refactor.

The one subtlety: `AbstractModel.getDimensions()` can return `None` for
OpenAI-style models. The `ModelsRepository.getOrCreateModelId` contract
requires a concrete `dimensions: int`. The `saveMessageEmbedding` /
`saveMemoryEmbedding` write paths always have `len(embedding)` available
at call time, so they resolve the id directly. The drift-detection /
backfill-discovery paths (`deleteObsoleteModelEmbeddings`,
`getMessagesWithoutEmbeddings`, `deleteObsoleteMemoryEmbeddings`,
`getMemoriesWithoutEmbeddings`) keep their handler-facing signatures
`(chatId, currentModel: str, currentDimensions: Optional[int])` per
extended D6 — the repo resolves `(currentModel, currentDimensions)` to
`model_id` internally when both are known, and falls back to a
`model_id NOT IN (SELECT model_id FROM models WHERE model = :currentModel)`
subquery when `currentDimensions is None` (semantically equivalent to
today's `model != :currentModel` predicate). No handler-side branching
on `None` is required. See Risk R3.

## 10. Tests

Existing test files that need rewriting:

- [`tests/database/repositories/test_chat_embeddings.py`](../../tests/database/repositories/test_chat_embeddings.py)
  — full rewrite. Drop every test that exercises the BLOB path
  (`getMessageEmbedding`, `deleteChatEmbeddings`, the BLOB round-trip in
  `saveMessageEmbedding`). New coverage: `saveMessageEmbedding` writes
  `chat_messages.model_id` + vec0 row with `model_id` partition key;
  `deleteObsoleteModelEmbeddings(chatId, currentModel, currentDimensions=...)`
  keeps its handler-facing signature per extended D6; `getMessagesWithoutEmbeddings`
  uses the single-table predicate. The repo constructor now takes
  `modelIdResolver=...` — every test that instantiates `ChatEmbeddingsRepository`
  directly must inject a mock resolver (see §8.4).
- [`tests/database/repositories/test_chat_search.py`](../../tests/database/repositories/test_chat_search.py)
  — drop every test that exercises `_loadEmbeddingsFromDb` or the numpy
  fallback block. Assert `_semanticSearch` returns `[]` when vec0 is
  unsupported (not a numpy-fallback result). The `searchChatMessages(...)`
  signature is unchanged (extended D6), so callers keep passing
  `modelName=...`; only assertions on the vec0 filter change (`model_id =
  :modelId` instead of `model = :modelName`). Repo constructor needs the
  mock resolver.
- [`tests/database/repositories/test_chat_search_native.py`](../../tests/database/repositories/test_chat_search_native.py)
  — update `_nativeVectorSearch` tests to pass `modelName=...` (unchanged
  signature); the vec0 filter assertion changes to `model_id = :modelId`.
  **Critical: the existing `patch.object(ChatSearchRepository,
  "_loadEmbeddingsFromDb")` patches at lines 65 and 93 MUST be removed** —
  once `_loadEmbeddingsFromDb` is deleted from the class, those patches
  raise `AttributeError` at collection time. The tests they backstop
  (the numpy fallback assertion) no longer exist post-refactor. Repo
  constructor needs the mock resolver.
- [`tests/database/repositories/test_user_memories.py`](../../tests/database/repositories/test_user_memories.py)
  — swap `embedding_model` / `embedding_dimensions` for `model_id` in
  fixtures and assertions (lines 107-108, 719-720, 732-733, 765-766, 828,
  833, 868, 873, 910, 915, 929-932, 973-974, 1102, 1113-1114, 1117).
  `deleteObsoleteMemoryEmbeddings` keeps its handler-facing signature
  `(chatId, currentModel, currentDimensions)` per extended D6.
  `getMemoriesWithoutEmbeddings` keeps `(chatId, *, limit, modelName=None,
  dimensions=None, dataSource=None)` — assertions at lines 839, 880, 888,
  935, 1119 keep working. Repo constructor needs the mock resolver.
- [`tests/database/repositories/test_chat_messages.py`](../../tests/database/repositories/test_chat_messages.py)
  — module-docstring-only update: the comment at lines 11-12 mentions
  `saveMessageEmbedding`, `getMessageEmbedding`, `deleteChatEmbeddings` as
  living in `ChatEmbeddingsRepository`; the latter two are being dropped.
  Rewrite the docstring to drop those mentions. No test logic changes
  (this file tests `getMessageThread`, not embedding CRUD).
- [`tests/scripts/test_clear_memory_embeddings.py`](../../tests/scripts/test_clear_memory_embeddings.py)
  — assert the script issues `UPDATE user_memories SET model_id = NULL`.
  The fixtures and column-list helpers at lines 85-86, 97-98, 119-120,
  125, 137, 146, 151, 180, 186, 190, 238-239 swap the provenance pair for
  `model_id`.

Handler-layer tests that build `UserMemoryDict` fixtures:

- [`tests/bot/common/handlers/test_base.py`](../../tests/bot/common/handlers/test_base.py)
  — the `_makeMemoryDict` helper at lines 282-299 builds a `UserMemoryDict`
  with `embedding_model` and `embedding_dimensions` keys. Swap them for
  `model_id: None`. The dict shape is what `UserMemoryDict` (TypedDict)
  enforces — once §7 lands, the old keys are a type error.
- [`tests/bot/common/handlers/test_user_memories_memory_regen.py`](../../tests/bot/common/handlers/test_user_memories_memory_regen.py)
  — same `_makeMemoryDict` shape at lines 175-189 (swap
  `embedding_model`/`embedding_dimensions` for `model_id`). The docstring
  at line 546 mentions `embedding_dimensions` — update.
- [`tests/bot/common/handlers/test_user_memories.py`](../../tests/bot/common/handlers/test_user_memories.py)
  — the fixture at lines 1849-1850 swaps `embedding_model` /
  `embedding_dimensions` for `model_id`. The assertions at lines 3320 and
  3362 reference `embedding_model is None` — reword to `model_id is None`.
- [`tests/bot/common/handlers/test_chat_search_cleanup.py`](../../tests/bot/common/handlers/test_chat_search_cleanup.py)
  — module-docstring-only update: lines 6-7 reference
  `message_embeddings` and `vec_message_embeddings_{N}` as the cleanup
  targets; reword to reference `chat_messages.model_id` and the vec0
  family.
- [`tests/bot/common/handlers/test_chat_search.py`](../../tests/bot/common/handlers/test_chat_search.py)
  — the `searchChatMessages` mocks (lines 417, 436, 467, 509, 536, 560,
  675, 935, 967, 1000, 1685-1696, 1776, 1802, 1920) keep passing
  `modelName=...` kwargs unchanged (extended D6). The line 1181 test name
  `test_cron_skips_when_embedding_model_missing` is fine (refers to a
  chat setting, not the column). Repo-constructor mocks: any test that
  instantiates the handler with a real `Database` gets the resolver wiring
  automatically; tests that mock the repo at the attribute level are
  unaffected.

New test file:

- `tests/database/repositories/test_models.py`
  (NEW — to be created by this refactor) — coverage for `ModelsRepository`:
  - `getOrCreateModelId` cache hit (second call returns same id, no second
    INSERT).
  - `getOrCreateModelId` cache miss allocates `MAX(model_id)+1`.
  - concurrent-insert idempotency: two calls for the same `(model, dims)`
    return the same id (the `INSERT OR IGNORE` + `SELECT`-back contract).
  - `getModelById` / `listModels` round-trip.

Schema-introspection tests with hardcoded table lists (per memory note:
recurring maintenance point when tables are added/dropped):

- [`tests/integration/test_database_operations.py`](../../tests/integration/test_database_operations.py)
  line ~440 (`expectedTables`): remove `"message_embeddings"`, add
  `"models"`.
- [`tests/database/test_db_wrapper.py`](../../tests/database/test_db_wrapper.py)
  line ~1898 (`requiredTables`): same edit.
- [`tests/database/migrations/test_migrations.py`](../../tests/database/migrations/test_migrations.py)
  lines ~110 and ~556 (`expectedTables`): same edit.

Migration rollback-step counts (per memory note: bump when a new migration
lands above the rollback target):

- [`tests/database/test_migration_020_user_memories.py`](../../tests/database/test_migration_020_user_memories.py)
  line 79: `rollback(steps=5)` → `rollback(steps=6)`.
- [`tests/database/test_migration_021_user_memories_soft_delete.py`](../../tests/database/test_migration_021_user_memories_soft_delete.py)
  line 56: `rollback(steps=5)` → `rollback(steps=6)`.
- [`tests/database/test_migration_022_drop_user_data.py`](../../tests/database/test_migration_022_drop_user_data.py)
  line 61: `rollback(steps=3)` → `rollback(steps=4)`.
- [`tests/database/test_migration_023_rename_memory_injection_enabled_to_memory_enabled.py`](../../tests/database/test_migration_023_rename_memory_injection_enabled_to_memory_enabled.py)
  lines 91, 138, 173: `rollback(steps=2)` → `rollback(steps=3)`.
- NEW `tests/database/test_migration_025_embedding_model_lookup.py`
  (to be created by this refactor), following the established pattern
  (`_rollbackToPre025` helper with
  `rollback(steps=1)`): asserts (a) `models` table created, (b)
  `message_embeddings` dropped, (c) `user_memories.model_id` backfilled
  correctly from legacy `embedding_model`/`embedding_dimensions` via the
  LEFT JOIN, (d) `chat_messages.model_id` backfilled from
  `message_embeddings` + `models`, (e) both vec0 families dropped, (f)
  the `models` backfill is idempotent under partial re-runs (probe-then-
  insert pattern from §6 Step 2 — re-run the migration after a partial
  apply and confirm no UNIQUE-constraint violation).
  **No `test_migration_024_*.py` exists** (verified by globbing
  `tests/database/test_migration_*.py`); migration_024 only adds an index
  and ships no dedicated rollback test, so no rollback-step bump is
  needed for it.

Dependency-usage regression tests:

- [`tests/dependencies/test_numpy.py`](../../tests/dependencies/test_numpy.py)
  — this file pins the numpy cosine-ranking contract that lived in
  `chat_search.py` lines ~403-424. Once the numpy block is deleted, this
  test file is **deleted unconditionally** (Decision D8 — numpy fully
  retired; Q1 resolved affirmatively). Its whole reason for existing is
  to pin the inline numpy algorithm; with the algorithm gone AND the
  `user_memories.py:872` `numpy.linalg.norm` use also retired, there is
  nothing to pin.
- **Post-refactor numpy-import grep (verification step).** Because
  `numpy==2.5.1` is being dropped from `requirements.direct.txt`, verify
  at Phase 4 implementation time that **no production file imports
  numpy**. Run
  `rg "import numpy" internal/ lib/` — the result must be **0 matches**
  post-refactor. If any match surfaces, either retire that use too
  (preferred) or document why it must stay and re-add the dependency
  with an inline rationale. Test files may still import numpy if a test
  explicitly exercises a numpy comparison; that is acceptable as long as
  the import does not exist in production code (the production code must
  not require numpy at runtime).
- [`tests/dependencies/test_sqlite_vec.py`](../../tests/dependencies/test_sqlite_vec.py)
  — unaffected; sqlite-vec remains the vec0 backend. No changes.

## 11. Phasing / sequencing

Recommended execution order for the eventual implementation. Each phase is
a separable commit (or PR) that keeps the tree green; phases 1-2 can land
behind a feature flag if early merge is wanted.

- **Phase 1 — New `models` repo + TypedDicts + Database wiring (no
  production callers yet).**
  - Add `ModelDict` to `internal/database/models.py`.
  - Create `internal/database/repositories/models.py`.
  - Export from `internal/database/repositories/__init__.py`.
  - Wire `self.models` in `internal/database/database.py`.
  - Add `tests/database/repositories/test_models.py`.
  - Run `make format lint test`. No production behaviour change — the
    table doesn't exist yet, no one calls the repo.
- **Phase 2 — Migration `025` (full DDL with temp-table swaps).**
  - Create `migration_025_embedding_model_lookup.py` per §6.
  - Create `tests/database/test_migration_025_embedding_model_lookup.py`.
  - Bump rollback steps in tests for migrations 020, 021, 022, 023 (§10).
  - Update `expectedTables` / `requiredTables` lists (§10).
  - At this point: schema is migrated, but production repos still query
    the old (now-missing) columns → **the app will crash on any embed
    call**. Phase 2 must land together with Phase 3, OR Phase 2's
    migration must be feature-flagged off until Phase 3 lands. The
    cleanest sequencing is **Phase 2+3 as one PR**.
- **Phase 3 — Update `chat_embeddings.py`, `chat_search.py`, and
  `user_memories.py`.**
  - Slim columns, add `model_id` resolution, update vec0 DDL builders,
    drop `getMessageEmbedding` / `deleteChatEmbeddings`, keep handler-
    facing signatures stable per extended D6 (drift-detection methods
    resolve internally; `searchChatMessages` keeps `modelName`).
  - Constructor injection (D10): all THREE repos gain the
    `modelIdResolver` keyword parameter; `Database.__init__` wires
    `self.models.getOrCreateModelId` into all three (order matters —
    `self.models` constructed first).
  - `chat_search.py:793` `np.linalg.norm` is removed HERE (the
    `_nativeVectorSearch` query-norm guard) along with `import numpy
    as np` — this is necessary because removing `import numpy` breaks
    line 793 immediately. The full numpy retirement (including
    `_loadEmbeddingsFromDb` deletion and requirements regen) follows in
    Phase 4. The intermediate state after Phase 3 has `import numpy as
    np` removed from `chat_search.py` only if the cosine block at
    lines 410-480 is ALSO removed in Phase 3 (recommended — both numpy
    uses in `chat_search.py` are co-located logically); `user_memories.py`
    keeps `import numpy` until Phase 4.
  - Rewrite `tests/database/repositories/test_chat_embeddings.py` and
    `test_user_memories.py`.
  - Run `make format lint test`.
- **Phase 4 — Drop numpy from production code entirely (Decision D8 —
  Q1 resolved YES).** This phase replaces the old "drop message-side
  numpy only" Phase 4 and folds in the old Phase 5 conditional
  `user_memories.py:872` retirement. Recommended split into two
  micro-phases so the dependency removal is reviewable in isolation:
  - **Phase 4a (code edits):**
    - `internal/database/repositories/chat_search.py`: confirm `import
      numpy as np` is gone (Phase 3 should have removed it together
      with line 793 and lines 410-480); delete `_loadEmbeddingsFromDb`
      (lines 485-553) if not already removed; rewrite
      `tests/database/repositories/test_chat_search.py` and
      `test_chat_search_native.py`.
    - `internal/database/repositories/user_memories.py`: remove
      `import numpy` (line 52), replace the `numpy.linalg.norm` use at
      line ~872 with `math.sqrt(sum(x*x for x in queryEmbedding))`; add
      `import math` at the top if not already present.
    - **Delete `tests/dependencies/test_numpy.py` unconditionally.**
    - **Verification grep:** run `rg "import numpy" internal/ lib/` — must
      return 0 matches in production code (test matches are acceptable if
      a test exercises a numpy comparison, but production must not require
      numpy at runtime).
  - **Phase 4b (dependency removal):**
    - Drop `numpy==2.5.1` from
      [`requirements.direct.txt`](../../requirements.direct.txt) (Runtime
      section). Regenerate [`requirements.txt`](../../requirements.txt)
      via `freeze-requirements` per AGENTS.md (the frozen/locked file is
      never edited by hand).
    - This is a separate micro-phase because `freeze-requirements`
      regenerates the full lock file (potentially many transitive bumps if
      numpy was holding something else back); it deserves its own review
      surface. Run `make test` after to confirm nothing broke.
- **Phase 5 — Update handlers + script + remaining test rewrites.**
  - Verify all `internal/bot/common/handlers/{message_preprocessor,
    chat_search, user_memories}.py` call sites (extended D6 says zero
    changes expected at ANY site, including `/search` and drift
    detection).
  - Update `scripts/clear_memory_embeddings.py` + its test.
  - Update the handler-layer fixture tests listed in §10 (`test_base.py`,
    `test_user_memories_memory_regen.py`, the `UserMemoryDict` fixtures
    in `test_user_memories.py`, docstring in `test_chat_search_cleanup.py`,
    docstring in `test_chat_messages.py`).
  - Run `make format lint test`.
- **Phase 6 — Docs sync.**
  - Load the `update-project-docs` skill; apply the decision matrix.
  - Update `docs/database-schema.md` AND `docs/database-schema-llm.md`
    (dual doc — keep in sync).
  - Update `docs/database-README.md` (table list).
  - Update `docs/llm/architecture.md` (embedding storage section).
  - Update `docs/design/vector-search-native.md` (numpy-fallback framing).
  - Update `docs/llm/memories/vector-search.md` (operational contract).
  - Update `docs/llm/database.md` if it carries portability notes.
  - Update `docs/llm/memories/dependency-usage-tests.md` and
    `docs/llm/testing.md` (numpy row dropped, file/test counts
    recomputed).
  - Add `CHANGELOG.md` `[Unreleased]` entry under Changed.
  - Run `make check-docs`.

Specialists to dispatch:
- Phase 1, 3, 4a, 5 → `software-developer` (per-file code + tests).
- Phase 2 → `software-developer` with the `add-database-migration` skill
  loaded.
- Phase 4b → `software-developer` (requirements regen via
  `freeze-requirements`); validate via `make test`.
- Phase 6 → `docs-writer` with the `update-project-docs` skill loaded.
- Final verification → `run-quality-gates` skill (`make format lint test`).

## 12. Docs to update (post-implementation)

Schema- and storage-bearing docs:

- [`docs/database-schema.md`](../database-schema.md) — drop the
  `message_embeddings` section (and its
  `idx_message_embeddings_chat_model` index entry); add a `models` section;
  update the `chat_messages` section (add `model_id`); update the
  `user_memories` section (drop `embedding_model`/`embedding_dimensions`,
  add `model_id`); document the new vec0 lazy-create DDL with `model_id`
  partition keys; update the `vec_message_embeddings_N` section
  (`model_id INTEGER PARTITION KEY` replaces `model TEXT PARTITION KEY`)
  and the `vec_user_memories_N` section (gains `model_id` partition key);
  remove the "speeds up `_loadEmbeddingsFromDb`" index note (the loader
  is gone); update repository method signatures in the per-table
  "Interface" blocks (`deleteObsoleteModelEmbeddings`,
  `getMessagesWithoutEmbeddings`, `deleteObsoleteMemoryEmbeddings`,
  `getMemoriesWithoutEmbeddings`, `searchChatMessages`,
  `saveMemoryEmbedding` — handler-facing signatures stay; just remove
  mentions of `embedding_model`/`embedding_dimensions` in the prose).
- [`docs/database-schema-llm.md`](../database-schema-llm.md) — same
  updates; remove the "user_memories has no BLOB side table" note (now
  NEITHER feature has a BLOB side table — the asymmetry is gone, which is
  the point of the refactor).
- [`docs/database-README.md`](../database-README.md) — the table list at
  lines 89-91 references `message_embeddings` and
  `vec_message_embeddings_N` under "Chat Search Tables". Add a `models`
  entry and either drop `message_embeddings` (the table is gone) or
  reword the section header to reflect the new storage.
- [`docs/llm/database.md`](../llm/database.md) — many references:
  - Line 39: `chatSearch.searchChatMessages(...)` signature table row —
    drop `message_embeddings` mention from the description; signature
    unchanged per extended D6.
  - Line 43: `chatEmbeddings.deleteChatEmbeddings(chatId)` row — DELETE
    this row (method dropped).
  - Lines 73-74: `userMemories.getMemoriesWithoutEmbeddings` and
    `saveMemoryEmbedding` rows — signature unchanged; description swaps
    `embedding_model`/`embedding_dimensions` for `model_id`.
  - Line 331: `MessageEmbeddingDict` row — DELETE (TypedDict dropped per §7).
  - Lines 394, 410, 417, 455, 457, 715, 729-731, 736-745, 833-834, 836:
    the §5.5 `message_embeddings` schema section, the §7 vec0 schema
    block, and the migration-history table. Remove the BLOB-store section
    entirely; rewrite the vec0 schema block to show `model_id INTEGER
    PARTITION KEY`; drop the `idx_message_embeddings_chat_model` index
    reference; drop the "falls back to numpy" framing throughout; update
    migration_017/018/020/021 history entries to reflect that
    `message_embeddings` is later dropped by migration_025 (add a
    migration_025 row).

Architectural and design docs:

- [`docs/llm/architecture.md`](../llm/architecture.md) — update the
  embedding-storage section (line 580) and the numpy-fallback description.
  Drop the "user_memories has no BLOB side table" asymmetry note.
- [`docs/design/vector-search-native.md`](../design/vector-search-native.md)
  — update the "numpy fallback as safety net" framing: it's gone for
  messages; memories never had it. The "vec0 is the sole vector store"
  statement becomes true for both features. Multiple references to
  `_loadEmbeddingsFromDb`, the numpy path, and `model TEXT PARTITION KEY`
  throughout (lines 13-37, 69-71, 600-601, 767-811, 1011-1015, 1151-1159,
  1307-1313, 1389-1392, 1518, 1574, 1622).
- [`docs/llm/memories/vector-search.md`](../llm/memories/vector-search.md)
  — separate from the design doc; covers the operational contract.
  Update lines 24-26 (vec0 schema now has `model_id`), line 40 (numpy
  fallback gone), lines 48-50 (native path no longer "falls through to
  numpy" — returns `[]`), lines 54-55 and 59 (`maxMessages` cutoff no
  longer joins `message_embeddings` — queries `chat_messages.model_id`
  directly).
- [`docs/sql-portability-guide.md`](../sql-portability-guide.md) — no
  `insertOrIgnore` provider hook is being added (R5 resolved by using
  `upsert(..., updateExpressions={})`). If the guide mentions
  `INSERT OR IGNORE` anywhere, leave it; this refactor does not introduce
  any new dialect-specific SQL.

Dependency- and testing-docs:

- [`docs/llm/memories/dependency-usage-tests.md`](../llm/memories/dependency-usage-tests.md)
  — line 8 lists `numpy 2.5.1` as a PURE dep; line 18 documents the
  cosine top-K pinning rationale; line 26 lists `test_numpy` as one of
  the 6 files; line 31 captures the numpy tie-break finding. With numpy
  retired from production and `test_numpy.py` deleted (D8), update all
  four references and drop the numpy row from the PURE-deps list. The
  file count drops 6 → 5; the test count (79) drops accordingly —
  recompute via `make test --co -q | wc -l` at Phase 4 time.
- [`docs/llm/testing.md`](../llm/testing.md) — line 36 lists `numpy` in
  the dep-usage-test roster and cites "79 tests across 6 files". Update
  to drop `numpy` and recompute the count (6 → 5 files; test count via
  the command above).
- [`docs/llm/index.md`](../llm/index.md) — if it cites the dependency-test
  file count (the memory note mentions "3300+"), update after Phase 4
  settles.

Requirements and changelog:

- [`requirements.direct.txt`](../../requirements.direct.txt) — remove the
  `numpy==2.5.1` line (Runtime section). Regenerate
  [`requirements.txt`](../../requirements.txt) via `freeze-requirements`
  per AGENTS.md (the frozen/locked file is never edited by hand).
- [`CHANGELOG.md`](../../CHANGELOG.md) — one-line `[Unreleased]` entry
  under **Changed**: "Embedding model/dimensions provenance normalised
  into a `models` lookup table; `message_embeddings` BLOB store and numpy
  cosine fallback dropped; vec0 is now the sole vector store for both
  message search and memory search. **Heads-up:** existing vec0 vectors
  are dropped and regenerated on next backfill — see migration_025."

## 13. Risks / open questions

- **R1 — vec0 DROP is irreversible.** The migration drops
  `vec_message_embeddings_{N}` and `vec_user_memories_{N}` (and their
  sqlite-vec shadow tables). Vectors cannot be regenerated from `model_id`
  alone — they require re-running the embedding model over the source
  text. **Mitigation:** confirm a fresh DB backup exists before running
  the migration in production; document in `CHANGELOG.md` that search
  quality is temporarily degraded until the backfill cron catches up
  (existing pattern, same as a model switch today). The `down()` path is
  schema-correct but data-lossy for vectors — documented honestly in §6.
- **R3 — `AbstractModel.getDimensions()` can return `None`.** The repo
  side handles this internally per extended D6: when `currentDimensions`
  is `None` (OpenAI-style models that don't expose `embeddingDimensions`
  until generation), the repo uses a `model_id NOT IN (SELECT model_id
  FROM models WHERE model = :currentModel)` subquery instead of resolving
  a single id. This mirrors today's `model != :currentModel` predicate
  exactly. The save paths (`saveMessageEmbedding`, `saveMemoryEmbedding`)
  always have `len(embedding)` available and resolve a canonical id
  directly. No handler-side branching on `None` is required — the
  subquery is an internal repo concern.
- **R6 — Migration backfill re-run safety depends on probe-then-insert
  (NEW, surfaced during self-review).** The migration framework does
  NOT wrap `up()` in a transaction
  ([`internal/database/migrations/manager.py`](../../internal/database/migrations/manager.py)
  lines 285-300 — `_setVersion` runs only after `up()` returns, so a
  crash mid-`up()` leaves the schema partially applied AND the version
  pointer unchanged). The §6 Step 2 backfill loop MUST therefore probe
  for an existing `(model, dimensions)` row BEFORE allocating
  `MAX(model_id)+1` and inserting — a plain INSERT against an
  already-present pair would raise `IntegrityError` on the UNIQUE
  constraint. The plan's §6 Step 2 encodes this probe-then-insert
  pattern explicitly; the dedicated test in §10
  (`test_migration_025_embedding_model_lookup.py`) includes an
  idempotency assertion that re-runs `up()` after a partial apply and
  verifies no UNIQUE-constraint violation. **This is a load-bearing
  invariant — the implementer MUST NOT simplify the probe away as
  "defensive double-guard" (the original draft framed it that way and
  was wrong).**

**Open questions:** none remaining.

**Resolved during self-review (folded into §5 decisions or §8 spec):**

- ~~R2 — `/search` slash-command caller bypasses
  `LLMService.generateEmbedding`.~~ → **resolved** by extending D6 to
  cover `searchChatMessages`. The handler-facing signature stays
  `modelName: Optional[str]`; the repo resolves the id internally via
  the injected resolver. Both call sites (`chat_search.py:725-736` and
  `chat_search.py:1338-1348`) keep passing `modelName=...` unchanged.
- ~~R5 — `INSERT OR IGNORE` portability.~~ → **resolved** by switching
  `ModelsRepository.getOrCreateModelId` to
  `provider.upsert(table, values, conflictColumns, updateExpressions={})`,
  which already maps to `ON CONFLICT … DO NOTHING` portably across all
  three providers (verified in
  [`SQLite3Provider.upsert`](../../internal/database/providers/sqlite3.py)
  lines 426-439). No `insertOrIgnore` helper is added.
- ~~Q4 — `deleted_at` membership in `_SELECT_COLUMNS`.~~ → **resolved
  affirmatively** by reading every consumer of the constant:
  `deleted_at` is filtered on (`WHERE deleted_at IS NULL`) by the read
  methods, never returned in the row shape, and absent from
  `UserMemoryDict`. The migration's temp-table swap in §6 Step 3
  preserves `deleted_at` as a column; it stays out of `_SELECT_COLUMNS`.

**Resolved in the 2026-07-20 sign-off (folded into §5 decisions):**

- ~~Q1 — retire `user_memories.py:872` numpy use?~~ → **resolved YES**
  → Decision D8.
- ~~Q2 — `vec_user_memories_{N}` partition key?~~ → **resolved YES**
  → Decision D9.
- ~~Q3 — cross-repo access pattern?~~ → **resolved YES (option (b),
  constructor-injected resolver)** → Decision D10.
- ~~R4 — `numpy` remains a direct dependency if Q1 is unresolved~~ →
  **removed** (Q1 resolved YES; numpy is fully retired per D8).

## Verification (for this plan document)

- `make format lint` — the new file is `.md`; black/isort are no-ops on
  it, but the lint pass runs flake8 on the surrounding tree (must be
  clean — this plan introduces no `.py` changes).
- `make check-docs` — validates internal markdown links resolve. Every
  `[...](../../path)` link in this document points at a real file (all
  paths verified during research).
- No production code modified. Only this one plan markdown file is
  written.

## References

- [`docs/plans/llm-empty-truncated-final-handling-v1.md`](./llm-empty-truncated-final-handling-v1.md)
  — sibling plan whose header style this document mirrors.
- [`docs/plans/python-sandboxing-v1.md`](./python-sandboxing-v1.md) —
  retained design reference; style precedent for code-heavy plan docs.
- [`internal/database/migrations/versions/migration_013_remove_timestamp_defaults.py`](../../internal/database/migrations/versions/migration_013_remove_timestamp_defaults.py)
  — temp-table swap precedent.
- [`internal/database/migrations/versions/migration_020_user_memories.py`](../../internal/database/migrations/versions/migration_020_user_memories.py)
  — Python-loop backfill precedent (UUID allocation pattern).
- [`internal/database/repositories/chat_embeddings.py`](../../internal/database/repositories/chat_embeddings.py)
  — primary repo to refactor (message side).
- [`internal/database/repositories/chat_search.py`](../../internal/database/repositories/chat_search.py)
  — numpy fallback removal target.
- [`internal/database/repositories/user_memories.py`](../../internal/database/repositories/user_memories.py)
  — primary repo to refactor (memory side).
- [`internal/database/repositories/base.py`](../../internal/database/repositories/base.py)
  — `BaseRepository` pattern to mirror for `ModelsRepository`.
- [`internal/database/models.py`](../../internal/database/models.py) —
  TypedDict definitions (`MessageEmbeddingDict`, `UserMemoryDict`,
  `ChatMessageDict`).
- [`docs/sql-portability-guide.md`](../sql-portability-guide.md) — the
  portability rules every SQL snippet in §6 follows.
- [`AGENTS.md`](../../AGENTS.md) — camelCase/PascalCase conventions,
  `BaseSQLProvider` usage, "application-generated ID" rule, no-pydantic.
