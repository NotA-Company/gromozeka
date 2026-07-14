# Vector Search — Native Provider Support

Durable notes from the vector search design and native sqlite-vec implementation (2026-06-28/29). Read this when working on `ChatSearchRepository`, `ChatEmbeddingsRepository`, `SQLite3Provider`, or vector search infrastructure.

## Design

Design document: [`docs/design/vector-search-native.md`](../../design/vector-search-native.md) — produced 2026-06-28, reviewed and corrected through 5 review cycles.

### Interface — BaseSQLProvider additions

- `isVectorSearchSupported() -> bool` — concrete, default `False`.
- `vectorSearch(*, table, vectorColumn, returnColumns: list[str], queryVector: bytes, k, filterClause, filterParams, distanceMetric: VectorDistanceMetric) -> list[VectorSearchResult]` — concrete, default `NotImplementedError`.
- `listTables(likePattern: str = "%") -> list[str]` — concrete, default `NotImplementedError`. SQLite: `SELECT name FROM sqlite_master WHERE type='table' AND name LIKE :pattern`.
- `createVectorTable(tableName: str, columns: list[VectorColumnDef]) -> None` — concrete, default `NotImplementedError`.
- `VectorSearchResult` TypedDict: `rowKey: dict[str, str]` (column-name-to-value, supports composite keys) + `distance: float`.
- `VectorDistanceMetric` StrEnum: `COSINE`, `L2`.
- `VectorColumnType` StrEnum: `TEXT`, `INTEGER`, `FLOAT`, `BLOB`, `VECTOR`.
- `VectorColumnDef` TypedDict: `name: str`, `columnType: VectorColumnType`, `isPartitionKey: NotRequired[bool]`, `vectorDimension: NotRequired[int]`, `distanceMetric: NotRequired[VectorDistanceMetric]`. Uses `NotRequired[]` (NOT `total=False` — pyright rejects bracket access on total=False).
- No config key — auto-detection at connect time. `pip uninstall sqlite-vec` to disable.

### SQLite backend: sqlite-vec, vec0-first, dimension-aware

- **Table naming**: `vec_message_embeddings_{dimension}` (e.g. `vec_message_embeddings_384`). Enables multiple dimensions to coexist.
- **Schema**: `message_id TEXT`, `chat_id INTEGER PARTITION KEY`, `model TEXT PARTITION KEY`, `date TEXT` (ISO-8601), `embedding FLOAT[N] distance_metric=cosine`.
- **Tables created lazily**: in `saveMessageEmbedding()` write path (`readonly=False`), NOT in search path (`readonly=True` would fail — SQLite PRAGMA query_only blocks DDL). If vec0 table missing during search → exception → numpy fallback.
- **No migration backfill**: vec0 tables start empty, populated by CRON job + dual-write. Empty vec0 results → fall through to numpy (not return `[]`). Pre-existing embeddings populate via `REGENERATE_EMBEDDINGS` or model change.
- **maxMessages cap**: pre-filter `date >= :minDate` in vec0 MATCH query (Option B). `minDate` computed from `chat_messages`. Fallback: post-filter if vec0 doesn't support WHERE on non-partition metadata columns.
- **Dimension resolution**: `len(queryEmbedding)` — always available, no model introspection needed.
- **Model change cleanup**: stateless, idempotent — on every CRON tick, `DELETE FROM {table} WHERE chat_id = :chatId AND model != :currentModel` across all vec0 tables discovered via `listTables("vec_message_embeddings_%")`. No in-memory tracking dict.
- **Dual-write**: always DELETE first (by metadata columns or fallback to SELECT rowid → DELETE by rowid), then INSERT. Vec0 has no unique constraint on metadata columns. Write failures logged at `warning`, swallowed.

### aiosqlite / sqlite-vec gotchas

- Extension loading: `enable_load_extension(True)`, `load_extension(sqlite_vec.loadable_path())`, `enable_load_extension(False)`. No `run()`, no bare `SELECT load_extension('vec0')`.
- `aiosqlite.execute()` returns async context manager — use `async with ... as cursor:`.
- `SQLite3Provider.__slots__`: `_vectorSearchAvailable` must be in both `__slots__` AND `__init__`.
- `BaseSQLProvider`: 17 total methods (10 abstract + 7 concrete).
- Vec0 compatibility verifications needed: TIMESTAMP → TEXT, INSERT...SELECT...JOIN may not work, DELETE WHERE metadata may not work, WHERE on non-partition columns may not work — all have documented fallbacks.
- BLOB format: `array.array("f", vec).tobytes()` is already sqlite-vec compatible.
- Native path wrapped in try/except with numpy fallback. Empty vec0 results also fall through to numpy.

## Native Implementation

The design in [`docs/design/vector-search-native.md`](../../design/vector-search-native.md) has been implemented. Concrete implementation facts (supplement the design notes above):

- **New dependency**: `sqlite-vec==0.1.9` in `requirements.direct.txt` under `# Runtime`. Optional at runtime — guarded by a module-level `try/except ImportError` + `_SQLITE_VEC_AVAILABLE` flag in `internal/database/providers/sqlite3.py`.
- **Dual-write**: `ChatEmbeddingsRepository.saveMessageEmbedding()` writes to BOTH `message_embeddings` (authoritative) and the dimension-specific `vec0` table `vec_message_embeddings_{N}` (lazily created via `_upsertVecMessageEmbedding()` → `provider.createVectorTable()` with `readonly=False`). vec0 has no unique constraint on metadata columns, so dual-write is DELETE-then-INSERT (delete by metadata columns, or fallback SELECT rowid → DELETE by rowid).
- **Native search path**: `ChatSearchRepository._semanticSearch()` calls `isVectorSearchSupported()`; if true, tries `_nativeVectorSearch()` first. On exception OR empty native results, falls through to the numpy path. **Empty native results are NOT returned as `[]`** — they fall through to numpy so a pre-backfill vec0 table doesn't silently return nothing.
- **Dimension-aware table naming**: `vec_message_embeddings_{N}` where `N = len(queryEmbedding)` (e.g. `vec_message_embeddings_384`, `vec_message_embeddings_1024`). Multiple dimensions coexist; the repository picks the table from the query vector length. No model introspection API needed.
- **Auto-connect in `vectorSearch()`**: `vectorSearch()` may be called on a provider whose connection was opened lazily (`keepConnection=false`) or that has not yet connected. It auto-connects when needed to handle the lazy connection lifecycle. Table creation happens ONLY in the write path (`readonly=False`); the search path uses `readonly=True` (SQLite PRAGMA `query_only` blocks DDL), so a missing vec0 table raises and triggers numpy fallback rather than attempting to create it.
- **Extension loading via aiosqlite**: `enable_load_extension(True)` → `load_extension(sqlite_vec.loadable_path())` → `enable_load_extension(False)`, wrapped in `try/finally` so loading is always disabled afterward (safety against leaving extension loading on after a failure). No `sqlite_vec.load(conn)` (that touches the raw `connection._conn` and is fragile), no bare `SELECT load_extension('vec0')`. Version verified via `SELECT vec_version()`.
- **Model-change cleanup with in-memory tracking**: `ChatSearchHandler._dtCronJob()` delegates to `ChatEmbeddingsRepository.deleteObsoleteModelEmbeddings()` (returns `bool`). Gated by an in-memory `_embeddingModelTracker: Dict[int, str]` (chatId → modelKey where modelKey is `modelName` or `modelName:dimensions`). Cleanup only fires once per model switch; skipped on subsequent ticks until the model changes again. Tracker is only updated on successful cleanup (prevents one-shot misses on transient failures). The repo method cleans **both** `message_embeddings` (authoritative) **and** all `vec_message_embeddings_{N}` tables, skipping the vec0 table matching `currentDimensions`. Dimension-aware: DELETE from `message_embeddings` matches on `(model, dimensions)` tuple; vec0 cleanup skips the current-dimension table (its rows are not stale).
- **vec0 tables are ephemeral**: `message_embeddings` is authoritative. vec0 tables are rebuildable sidecar indexes — they carry nothing the app cannot reconstruct. No migration creates them; no backfill job is required to populate them (dual-write + CRON re-embed catch them up). They exist only when `sqlite-vec` is loaded.
- **maxMessages cutoff joins `message_embeddings`** (not just `chat_messages`) in the native path to mirror the numpy path's candidate-pool semantics: `minDate` is computed and pushed into the vec0 MATCH query via `filterClause` (`date >= :minDate`) as a pre-filter (Option B from the design), so both paths rank over the same recent-N candidate set.
- **No config key needed**: auto-detection at connect time. To disable native search: `pip uninstall sqlite-vec` → `isVectorSearchSupported()` returns `False` → numpy path used transparently. There is no `[vector-search]` TOML section.
- **Custom extension path (Alpine Linux / source builds)**: When the `sqlite-vec` pip package is unavailable (no musl wheel), set `vectorExtensionPath = "/path/to/vec0.so"` under `[database.providers.<name>.parameters]` in TOML. The provider loads the extension from that path instead of `sqlite_vec.loadable_path()`. Use `${VEC0_EXTENSION_PATH}` env-var substitution for Docker flexibility. Commented example in `configs/00-defaults/00-config.toml`. The pip package takes priority when both are present.
- **`SQLite3Provider.__slots__`**: `_vectorSearchAvailable` must be declared in `__slots__` AND initialized in `__init__()` (to `False`), not only in `connect()`. Otherwise `isVectorSearchSupported()` called before `connect()` (early init / error paths) raises `AttributeError`.
- **Known transitional limitation: partial vec0 mirror**: After rollout, pre-existing embeddings in `message_embeddings` are only dual-written to vec0 when re-generated (via `REGENERATE_EMBEDDINGS` chat setting or model change). Until then, vec0 may have fewer rows than `message_embeddings` for the same chat+model, and native results reflect only the dual-written subset. Resolution: enable `REGENERATE_EMBEDDINGS` for affected chats to trigger a full re-embedding pass (populates vec0 via dual-write). Documented in a code comment in `_semanticSearch()`. Note: changing the `EMBEDDING_MODEL` or its dimensions now triggers `deleteObsoleteModelEmbeddings()` on both `message_embeddings` AND vec0, so model switches cleanly re-embed from scratch — this limitation only applies to same-model initial rollout.
- **maxMessages timestamp ties**: The native path uses a compound filter `(date > :minDate OR (date = :minDate AND message_id >= :minMessageId))` to match the numpy path's `ORDER BY c.date DESC, me.message_id DESC` + `LIMIT/OFFSET` semantics. Both `date` and `message_id` are captured from the cutoff query which joins `message_embeddings` to `chat_messages`.

## vec0 column audit (2026-07-11)

Audit of vec0 virtual-table columns confirmed which columns are live vs. dead, and locked in the schema-change mechanics. Durable conclusions (do not re-derive):

- **`vec_message_embeddings_{N}`: 5 columns, NO dead columns.** All of `message_id`/`chat_id`/`model`/`date`/`embedding` (the schema in the Design section above) are read AND written. Audited fully — do NOT re-investigate this table.
- **`vec_user_memories_{N}`: 6 live columns (was 8).** `thread_id`+`type` were confirmed write-only and dropped; partition keys are `chat_id`/`user_id`/`model` only (`permanent` is a plain filterable metadata column). The column-by-column detail lives in [`user-memories.md`](user-memories.md) (vec0 virtual table section) — not duplicated here.
- **vec0 virtual tables cannot `ALTER TABLE`.** Changing columns requires DROP + lazy-recreate. Existing prod tables carrying the old schema must be dropped manually; they are non-durable and rebuild via the regen CRON (consistent with the ephemerality note above). This matches the precedent set when the `model` partition key was added.
- **`createVectorTable` is the sole vec0-creation entry point** (`/internal/database/providers/sqlite3.py`, takes `list[VectorColumnDef]`); there is no other path that materialises a vec0 table. Vec0 has no native `TIMESTAMP` or `BOOLEAN` type: `date` is stored as TEXT (ISO-8601) and booleans as INTEGER `0`/`1`. There is no real UPSERT on metadata columns — both repos use the DELETE-then-INSERT-with-rowid-fallback pattern already documented above for the message-embeddings repo; the user-memories repo follows the identical shape.
