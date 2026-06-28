# Native Vector Search in the SQL Provider Abstraction

**Task**: Add native vector similarity search to `BaseSQLProvider`, with SQLite (`sqlite-vec`) as the primary backend.
**Date**: 2026-06-28
**Status**: Design (not yet implemented)

---

## 1. Overview

### 1.1 Problem Statement

Semantic search in Gromozeka currently loads ALL embeddings for a `(chatId, modelName)` pair into Python memory and computes cosine similarity via numpy. The hot path in `ChatSearchRepository._semanticSearch()` (`internal/database/repositories/chat_search.py:266-389`) is:

1. `SELECT me.message_id, me.embedding FROM message_embeddings ...` -- fetches every matching BLOB.
2. Deserialise each BLOB: `list(array.array("f", row["embedding"]))`.
3. Build a numpy matrix (N x D), normalise, compute `similarities = normalizedMatrix @ queryNorm`.
4. `np.argpartition` for top-K.
5. Fetch full message rows for the winning IDs.

This is O(N x D) per query where N = stored embeddings (capped at `max-messages-for-semantic-search`, default 100,000) and D = dimensions (384 or 1024). It transfers megabytes of BLOBs over the SQLite wire on every search and allocates the full matrix in Python heap.

### 1.2 Goals

- **G1**: Push cosine similarity computation into the database engine so vectors never leave the DB process on a search query.
- **G2**: Define a provider-level interface (`isVectorSearchSupported`, `vectorSearch`) that any backend can implement with its native vector extension.
- **G3**: Implement the SQLite backend using `sqlite-vec`'s ``vec0`` virtual table as the primary path, with the scalar function approach documented as a fallback.
- **G4**: Keep the existing numpy fallback fully functional for providers that lack native support and as a safety net if the extension fails to load.
- **G5**: Zero configuration required — the provider auto-detects ``sqlite-vec`` at connect time and falls back to numpy if unavailable.
- **G6**: Dimension-aware vec0 table naming (``vec_message_embeddings_N`` where ``N`` is the embedding dimension) so multiple dimension sizes coexist without conflict.

### 1.3 Non-Goals

- Approximate nearest-neighbour (ANN) indexing. `sqlite-vec`'s `vec0` virtual table does brute-force today; ANN (IVF, DiskANN) is on their roadmap but not stable. This design is brute-force-aware.
- Implementing `vectorSearch` for PostgreSQL, MySQL, or SQLink providers. The interface must be general enough for them, but concrete implementations are out of scope.
- Changing the embedding CRUD path (`ChatEmbeddingsRepository.saveMessageEmbedding`) -- storage format stays as-is.
- Removing the numpy dependency (it is still used elsewhere and remains the fallback).

---

## 2. Current Architecture

### 2.1 Embedding Storage

```
message_embeddings
  chat_id     INTEGER NOT NULL        -- PK part 1
  message_id  TEXT    NOT NULL        -- PK part 2
  embedding   BLOB    NOT NULL        -- float32 bytes via array.array("f", ...).tobytes()
  dimensions  INTEGER NOT NULL
  model       TEXT    NOT NULL
  created_at  TIMESTAMP NOT NULL
  updated_at  TIMESTAMP NOT NULL
  PRIMARY KEY (chat_id, message_id)

idx_message_embeddings_chat_model ON (chat_id, model)
```

Defined in `migration_017` and `migration_018` under `internal/database/migrations/versions/`.

### 2.2 Search Flow

```
searchChatMessages(chatId, queryEmbedding, ...)
  |
  v
_semanticSearch()
  |
  +-- _loadEmbeddingsFromDb()       -- SELECT all BLOBs for (chatId, model)
  +-- _filterMessageIds()           -- SQL pre-filter: user, category, age, thread
  +-- numpy cosine similarity       -- build matrix, normalize, dot product
  +-- _fetchSearchResultRows()      -- SELECT full rows for top-K IDs
```

### 2.3 Provider Hierarchy

```
BaseSQLProvider  (abstract, 17 total methods — 10 abstract, 7 concrete)
  |
  +-- SQLite3Provider   (aiosqlite, wired in factory)
  +-- SQLinkProvider    (remote SQL client, wired in factory)
  +-- PostgreSQLProvider (asyncpg, NOT wired)
  +-- MySQLProvider     (aiomysql, NOT wired)
```

Factory: `internal/database/providers/__init__.py:getSqlProvider()`.

---

## 3. Proposed Interface

### 3.1 New TypedDict for Results

Add to `internal/database/providers/base.py`:

```python
from typing import TypedDict

class VectorSearchResult(TypedDict):
    """A single row from a native vector similarity search.

    Attributes:
        rowKey: Mapping of column name to string value for each
            requested return column. For composite primary keys,
            all key columns are present (e.g. ``{"chat_id": "42",
            "message_id": "abc"}``). For single-column keys, the
            dict has one entry.
        distance: Raw distance/dissimilarity score from the database
            engine. Lower is more similar for cosine distance. Callers
            convert to similarity via ``1.0 - distance`` when the
            metric is cosine.
    """

    rowKey: dict[str, str]
    """Column-name-to-value mapping for the requested return columns."""
    distance: float
    """Distance score (metric-dependent; lower = more similar for cosine)."""
```

Design notes:
- `rowKey` is a `dict[str, str]` mapping column names to their string values for all columns listed in ``returnColumns``. This supports both single-column keys (``{"message_id": "abc"}``) and composite keys (``{"chat_id": "42", "message_id": "abc"}``).
- `distance` is the *raw* value from the database. For `sqlite-vec` cosine distance, this is `1.0 - cosine_similarity` (range 0..2). The caller converts.
- Keeping it minimal (two fields) avoids coupling the provider to any particular table schema.

### 3.2 `isVectorSearchSupported()`

Add to `BaseSQLProvider` as a concrete (non-abstract) method with a default:

```python
def isVectorSearchSupported(self) -> bool:
    """Check if this provider supports native vector similarity search.

    Providers that load a vector extension (e.g. sqlite-vec, pgvector)
    override this to return ``True`` after confirming the extension is
    operational. The default returns ``False``.

    Returns:
        ``True`` if :meth:`vectorSearch` is available, ``False`` otherwise.
    """
    return False
```

Not `async` because the check should be cached at connect-time and returned synchronously. The provider sets a private flag (`_vectorSearchAvailable: bool`) during `connect()` (initialized to `False` in `__init__`, set to `True` in `connect()`).

### 3.3 `vectorSearch()`

Add to `BaseSQLProvider` as a concrete method with a default that raises:

```python
async def vectorSearch(
    self,
    *,
    table: str,
    vectorColumn: str,
    returnColumns: list[str],
    queryVector: bytes,
    k: int,
    filterClause: str = "",
    filterParams: Optional[dict[str, str | int | float | None]] = None,
    distanceMetric: VectorDistanceMetric = VectorDistanceMetric.COSINE,
) -> list[VectorSearchResult]:
    """Perform a native KNN vector similarity search.

    Executes a provider-specific nearest-neighbour query over the
    ``vectorColumn`` in ``table``, returning the ``k`` closest rows.

    The query vector must be pre-serialised to the provider's expected
    binary format (e.g. ``array.array("f", floats).tobytes()`` for
    sqlite-vec float32). This avoids an extra copy/conversion inside
    the provider.

    Args:
        table: Table (or virtual table) name containing the vectors.
        vectorColumn: Column holding the vector BLOB.
        returnColumns: List of column names whose values populate
            the :attr:`VectorSearchResult.rowKey` dict in results.
        queryVector: The query vector as raw bytes in the format
            expected by the provider.
        k: Maximum number of nearest neighbours to return.
        filterClause: Optional SQL WHERE fragment to pre-filter rows.
            Must use ``:named`` placeholders referencing keys in
            ``filterParams``. Example:
            ``"chat_id = :chatId AND model = :modelName"``.
            Empty string means no extra filter.
        filterParams: Named parameters for ``filterClause``. ``None``
            or empty dict when ``filterClause`` is empty.
        distanceMetric: Distance metric to use for the similarity
            comparison. Providers validate support at call time.

    Returns:
        List of :class:`VectorSearchResult` ordered by distance
        ascending (most similar first). May contain fewer than ``k``
        results if the table has fewer matching rows.

    Raises:
        NotImplementedError: When the provider does not support native
            vector search (default implementation).
        ValueError: When ``distanceMetric`` is not supported by this
            provider.
    """
    raise NotImplementedError(
        f"{type(self).__name__} does not support native vector search"
    )
```

Key design decisions:

| Decision | Rationale |
|---|---|
| `queryVector` is `bytes`, not `list[float]` | Avoids serialisation inside the provider; caller already has the BLOB from `array.array("f", ...).tobytes()`. sqlite-vec accepts raw bytes directly. |
| `filterClause` is a raw SQL fragment | The existing search has complex filters (user, category, age, thread). Structured filter objects would over-abstract with no gain -- filters are always built by trusted repository code, never user input. |
| `returnColumns` is a list | Supports composite primary keys. The provider builds ``rowKey`` as ``{col: str(row[col]) for col in returnColumns}``. |
| `distanceMetric` is a ``VectorDistanceMetric`` enum | Type-safe; prevents typos and makes supported values discoverable. Each provider maps to native syntax. |
| Return type is `list[VectorSearchResult]` | Minimal contract. The repository builds `ChatMessageDict` results from the IDs in a separate step (via `_fetchSearchResultRows`). |
| Not abstract | Only providers with vector support override it. Others inherit the `NotImplementedError` default. |

### 3.4 `VectorDistanceMetric` StrEnum

Add to `internal/database/providers/base.py`, alongside the other enums:

```python
from enum import StrEnum

class VectorDistanceMetric(StrEnum):
    """Distance metrics for native vector similarity search.

    Each provider maps these to its native syntax. If a provider does
    not support a particular metric, it raises ``ValueError``.
    """

    COSINE = "cosine"
    """Cosine distance (1.0 - cosine_similarity). Range [0, 2]."""
    L2 = "l2"
    """Euclidean (L2) distance."""
    # Future: DOT_PRODUCT = "dot_product"
    # Future: HAMMING = "hamming"
```

Design rationale:
- Using ``StrEnum`` rather than ``Literal["cosine", "l2"]`` provides named constants, string serialisation, and self-documenting usage.
- The ``match`` block in each provider's ``vectorSearch()`` maps enum members to native syntax. Unsupported metrics raise ``ValueError``.
- New metrics can be added without changing the interface.

### 3.5 `VectorColumnType` StrEnum

Add to `internal/database/providers/base.py`, alongside `VectorDistanceMetric`:

```python
from enum import StrEnum

class VectorColumnType(StrEnum):
    """Column types for vector table creation.

    Providers map these to their native type names. The ``VECTOR`` type
    is special — it creates a vector/embedding column with dimension
    and distance metric parameters.
    """

    TEXT = "text"
    """Variable-length text."""
    INTEGER = "integer"
    """Integer."""
    FLOAT = "float"
    """Floating-point number."""
    BLOB = "blob"
    """Binary data."""
    VECTOR = "vector"
    """Vector/embedding column. Requires ``vectorDimension`` and
    optionally ``distanceMetric`` in the column definition."""
```

### 3.6 `VectorColumnDef` TypedDict

Add to `internal/database/providers/base.py`:

```python
from typing import NotRequired, TypedDict

class VectorColumnDef(TypedDict):
    """Definition of a single column for :meth:`createVectorTable`.

    Attributes:
        name: Column name.
        columnType: Logical column type from :class:`VectorColumnType`.
        isPartitionKey: If ``True``, the column is a partition key
            (vec0 ``PARTITION KEY`` syntax). Used to prune search space.
            Default ``False``.
        vectorDimension: For ``VECTOR`` columns, the embedding
            dimension (e.g. 384, 1024). Required when ``columnType`` is
            ``VECTOR``.
        distanceMetric: For ``VECTOR`` columns, the distance metric.
            Default depends on provider.
    """

    name: str
    columnType: VectorColumnType
    isPartitionKey: NotRequired[bool]
    vectorDimension: NotRequired[int]
    distanceMetric: NotRequired[VectorDistanceMetric]
```

### 3.7 `listTables()`

Add to `BaseSQLProvider` as a concrete method with a default ``NotImplementedError``:

```python
async def listTables(self, likePattern: str = "%") -> list[str]:
    """List table names matching a LIKE pattern.

    Each provider implements this with its native introspection query.
    Used by the vector search subsystem to discover vec0 tables for
    cleanup and to check whether a dimension-specific table exists.

    Args:
        likePattern: SQL LIKE pattern (e.g. ``"vec_message_embeddings_%"``).
            The default ``"%"`` matches all tables.

    Returns:
        List of matching table names.

    Raises:
        NotImplementedError: If the provider does not support table
            listing (default implementation).
    """
    raise NotImplementedError(
        f"{type(self).__name__} does not support table listing"
    )
```

### 3.8 `createVectorTable()`

Add to `BaseSQLProvider` as a concrete method with a default ``NotImplementedError``:

```python
async def createVectorTable(
    self,
    tableName: str,
    columns: list[VectorColumnDef],
) -> None:
    """Create a vector table/index for native similarity search.

    Each provider maps the column definitions to its native DDL.
    Providers without vector support raise ``NotImplementedError``.

    Args:
        tableName: Name for the new table (e.g. ``"vec_message_embeddings_384"``).
        columns: Ordered list of column definitions. At least one
            column must have ``columnType=VectorColumnType.VECTOR``.

    Raises:
        NotImplementedError: If the provider does not support vector
            tables (default implementation).
        ValueError: If no ``VECTOR`` column is present or required
            fields are missing.
    """
    raise NotImplementedError(
        f"{type(self).__name__} does not support vector table creation"
    )
```

### 3.9 Updated `__all__` Export

Add ``VectorSearchResult``, ``VectorDistanceMetric``, ``VectorColumnType``, ``VectorColumnDef`` to ``internal/database/providers/__init__.py`` ``__all__``.

Also export the new methods in the provider's public API: ``listTables``, ``createVectorTable``.

---

## 4. SQLite Implementation (`sqlite-vec`)

The primary implementation uses `sqlite-vec`'s ``vec0`` virtual table, which provides native KNN search with partition-key pruning and metadata columns. A fallback to scalar functions (`vec_distance_cosine`) on the physical `message_embeddings` table is documented but is not the default path.

### 4.1 Extension Loading

In `SQLite3Provider.connect()`, after the existing PRAGMA setup, attempt to load `sqlite-vec`:

```python
# --- In connect(), after foreign key PRAGMA ---
self._vectorSearchAvailable = False
if _SQLITE_VEC_AVAILABLE:
    version = await _loadSqliteVecExtension(connection)
    if version is not None:
        logger.info(f"sqlite-vec {version} loaded successfully")
        self._vectorSearchAvailable = True
    else:
        logger.debug("sqlite-vec not available (extension loading failed)")
```

**Loading mechanism**: The `sqlite-vec` PyPI package (`pip install sqlite-vec`) ships a pre-compiled shared library. The Python binding provides `sqlite_vec.load(conn)` which calls `conn.load_extension(...)` under the hood. For `aiosqlite` the pattern is:

```python
import sqlite_vec

# aiosqlite wraps the raw sqlite3.Connection
rawConn = connection._conn  # access underlying sqlite3.Connection
sqlite_vec.load(rawConn)
```

However, directly accessing `connection._conn` is fragile. The cleaner approach uses aiosqlite's built-in async wrappers `enable_load_extension` and `load_extension`, which dispatch onto the connection's background thread internally:

```python
async def _loadSqliteVecExtension(connection: aiosqlite.Connection) -> Optional[str]:
    """Load sqlite-vec into an aiosqlite connection.

    Uses aiosqlite's built-in extension-loading API.

    Args:
        connection: Open aiosqlite connection.

    Returns:
        sqlite-vec version string on success, or None if loading fails.

    Raises:
        No exception — failures are returned as None.
    """
    try:
        await connection.enable_load_extension(True)
        await connection.load_extension(sqlite_vec.loadable_path())
        await connection.enable_load_extension(False)

        # Verify extension is operational.
        async with connection.execute("SELECT vec_version()") as cursor:
            row = await cursor.fetchone()
            version = row[0]
        return version
    except Exception:
        return None
```

The `_SQLITE_VEC_AVAILABLE` boolean flag follows the project's optional-dependency pattern (top-of-file `try/except ImportError`):

```python
try:
    import sqlite_vec
    _SQLITE_VEC_AVAILABLE = True
except ImportError:
    _SQLITE_VEC_AVAILABLE = False
```

**Slot and init note**: Because `SQLite3Provider` uses `__slots__`, the
``_vectorSearchAvailable`` attribute **must** be declared in the class's
``__slots__`` tuple and initialized in ``__init__()``, not only in
``connect()``. Without this, calling ``isVectorSearchSupported()`` before
``connect()`` (e.g. during early initialization or from error-handling
paths) raises ``AttributeError``.

- Add ``"_vectorSearchAvailable"`` to the ``__slots__`` tuple in
  ``SQLite3Provider``.
- Set ``self._vectorSearchAvailable: bool = False`` in
  ``SQLite3Provider.__init__()`` alongside other attribute initializations
  (e.g. alongside ``self._connection = None``).

### 4.2 `isVectorSearchSupported()` Override

```python
def isVectorSearchSupported(self) -> bool:
    """Check if sqlite-vec extension is loaded and operational.

    Returns:
        ``True`` if ``sqlite-vec`` was successfully loaded during
        :meth:`connect`, ``False`` otherwise.
    """
    return self._vectorSearchAvailable
```

### 4.3 `vectorSearch()` Override — Primary Path (vec0 Virtual Table)

The primary implementation uses the ``vec0`` virtual table with dimension-aware naming
(``vec_message_embeddings_N``).

**vec0 virtual table schema (dimension-aware)**:

The table name embeds the embedding dimension so multiple dimension sizes
coexist without conflict:

```sql
CREATE VIRTUAL TABLE vec_message_embeddings_384 USING vec0(
    message_id TEXT,
    chat_id INTEGER PARTITION KEY,
    model TEXT PARTITION KEY,
    date TEXT,   -- ISO-8601 timestamp from chat_messages; enables maxMessages pre-filter
    embedding FLOAT[384] distance_metric=cosine
);
```

For a 1024-dim model the table would be ``vec_message_embeddings_1024``
with ``FLOAT[1024]``. The repository constructs the name dynamically:
``f"vec_message_embeddings_{dimension}"``.

- ``chat_id`` and ``model`` as **partition keys** — ``WHERE chat_id = X AND model = Y`` prunes the search to exactly that partition.
- ``date`` as a regular metadata column — ISO-8601 timestamp from chat_messages; enables maxMessages pre-filter.
- ``message_id`` as a regular column (not vector identifier) — returned in SELECT.
- ``embedding FLOAT[N]`` — N matches the dimension from the embedding model.

**Column types**: vec0 accepts ``text``, ``integer``, ``boolean``, ``float``
for metadata columns. The ``date`` column is declared as ``TEXT`` since
``chat_messages.date`` stores ISO-8601 strings, and lexicographic comparison
(``date >= :minDate``) works correctly on TEXT columns. The provider's
:meth:`createVectorTable` maps ``VectorColumnType`` values to these native
types (see Section 4.5).

```python
async def vectorSearch(
    self,
    *,
    table: str,
    vectorColumn: str,
    returnColumns: list[str],
    queryVector: bytes,
    k: int,
    filterClause: str = "",
    filterParams: Optional[dict[str, str | int | float | None]] = None,
    distanceMetric: VectorDistanceMetric = VectorDistanceMetric.COSINE,
) -> list[VectorSearchResult]:
    """Native KNN search using sqlite-vec vec0 virtual table.

    Constructs a MATCH query:

        SELECT {', '.join(returnColumns)}, distance
        FROM {table}
        WHERE embedding MATCH :_queryVector
            AND k = :_k
            {AND filterClause parts}

    Args:
        table: vec0 virtual table name.
        vectorColumn: Must be the embedding column name (e.g.
            ``"embedding"``).
        returnColumns: Column names to return in ``rowKey``.
        queryVector: Query vector as float32 bytes.
        k: Number of nearest neighbours.
        filterClause: Optional SQL WHERE fragment with ``:named``
            params. Use for partition-key and metadata filters.
        filterParams: Parameters for ``filterClause``.
        distanceMetric: Distance metric. Must match the metric
            declared in the vec0 table definition.

    Returns:
        List of :class:`VectorSearchResult` ordered by distance
        ascending (most similar first).

    Raises:
        ValueError: If ``distanceMetric`` is not supported by
            sqlite-vec's vec0 implementation.
    """
    # Validate metric — vec0 table is hardcoded to cosine distance.
    if distanceMetric != VectorDistanceMetric.COSINE:
        raise ValueError(
            f"SQLite3Provider vec0 table uses cosine distance. "
            f"Requested metric '{distanceMetric}' is not supported. "
            f"To use other metrics, create a vec0 table with the desired distance_metric."
        )

    # NOTE: The distance metric is fixed at vec0 table creation time.
    # To support L2, a second vec0 table with distance_metric=l2 would
    # be needed, and vectorSearch() would route to it based on
    # distanceMetric. This is deferred until L2 is actually required.

    returnCols = ", ".join(returnColumns)
    whereParts: list[str] = [f"{vectorColumn} MATCH :_queryVector", "AND k = :_k"]
    if filterClause:
        whereParts.append(f"AND {filterClause}")

    query = f"""
        SELECT {returnCols}, distance
        FROM {table}
        WHERE {' '.join(whereParts)}
        ORDER BY distance
    """

    params: dict[str, str | int | float | bytes | None] = dict(filterParams) if filterParams else {}
    params["_queryVector"] = queryVector
    params["_k"] = k

    rows = await self.executeFetchAll(query, params)
    results: list[VectorSearchResult] = []
    for row in rows:
        rowKey: dict[str, str] = {col: str(row[col]) for col in returnColumns}
        results.append(VectorSearchResult(
            rowKey=rowKey,
            distance=float(row["distance"]),
        ))
    return results
```

**Complexity**: This is still O(N x D) brute-force inside SQLite's C engine (vec0 does not yet support ANN indexing), but it eliminates:
- Transferring all N BLOBs to Python.
- Deserialising N float32 arrays in Python.
- Building an N x D numpy matrix in Python heap.
- The cosine similarity computation in Python/numpy.

The computation now happens in C (with potential SIMD on supported platforms) inside the SQLite process. Only the top-K ``(rowKey, distance)`` rows cross the boundary.

### 4.4 `listTables()` Override

Add to `SQLite3Provider`:

```python
async def listTables(self, likePattern: str = "%") -> list[str]:
    """List table names matching a LIKE pattern using SQLite's
    ``sqlite_master`` table.

    Args:
        likePattern: SQL LIKE pattern (e.g. ``"vec_message_embeddings_%"``).
            The default ``"%"`` matches all tables.

    Returns:
        List of matching table names.
    """
    rows = await self.executeFetchAll(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE :pattern",
        {"pattern": likePattern},
    )
    return [row["name"] for row in rows]
```

### 4.5 `createVectorTable()` Override

Add to `SQLite3Provider`:

```python
async def createVectorTable(
    self,
    tableName: str,
    columns: list[VectorColumnDef],
) -> None:
    """Create a vec0 virtual table.

    Maps ``VectorColumnDef`` to vec0 DDL:

    - ``VECTOR`` → ``FLOAT[{dim}] distance_metric={metric}``
    - ``isPartitionKey`` → appends ``PARTITION KEY`` after the type
    - Other types → native type name (``TEXT``, ``INTEGER``, ``FLOAT``, ``BLOB``)

    Args:
        tableName: Name for the new vec0 virtual table
            (e.g. ``"vec_message_embeddings_384"``).
        columns: Ordered list of column definitions. At least one
            column must have ``columnType=VectorColumnType.VECTOR``.

    Raises:
        ValueError: If no ``VECTOR`` column is present.
    """
    if not any(col["columnType"] == VectorColumnType.VECTOR for col in columns):
        raise ValueError(
            "At least one column with columnType=VECTOR is required"
        )

    colDefs: list[str] = []
    for col in columns:
        parts: list[str] = [col["name"]]
        match col["columnType"]:
            case VectorColumnType.VECTOR:
                dim = col.get("vectorDimension", 0)
                metric = col.get("distanceMetric", VectorDistanceMetric.COSINE)
                parts.append(f"FLOAT[{dim}] distance_metric={metric}")
            case VectorColumnType.TEXT:
                parts.append("TEXT")
            case VectorColumnType.INTEGER:
                parts.append("INTEGER")
            case VectorColumnType.BLOB:
                parts.append("BLOB")
            case VectorColumnType.FLOAT:
                parts.append("FLOAT")
        if col.get("isPartitionKey"):
            parts.append("PARTITION KEY")
        colDefs.append(" ".join(parts))

    query = (
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {tableName} USING vec0(\n"
        + ",\n".join(f"    {d}" for d in colDefs)
        + "\n)"
    )
    await self.execute(query)
```

### 4.6 Fallback: Scalar Function Path

If the vec0 virtual table is unavailable (e.g. corrupted, schema mismatch, or a temporary issue), the provider can fall back to scalar distance functions on the physical ``message_embeddings`` table:

```sql
SELECT message_id,
       vec_distance_cosine(embedding, :queryVector) AS distance
FROM message_embeddings
WHERE chat_id = :chatId AND model = :modelName
ORDER BY distance ASC
LIMIT :k
```

This approach requires no virtual table and works directly on the existing schema. The same ``VectorSearchResult`` interface is used; the ``returnColumns`` parameter is ``["message_id"]`` and ``rowKey`` is ``{"message_id": "..."}``.

**When to use the fallback**:
- The vec0 virtual table creation failed during migration.
- The extension upgrade broke the vec0 schema (rare).
- For testing / comparison between vec0 and scalar paths.

The fallback is not the default path — the vec0 virtual table is created during the initial migration and is the primary interface.

### 4.7 Dimension Handling

vec0 requires fixed dimensions at table creation. Dimension-aware naming
(``vec_message_embeddings_N``) solves the multi-dimension problem:
each embedding dimension gets its own vec0 table. The repository selects
the correct table at runtime based on the model's output dimension.

When a new dimension is first encountered during a write operation,
:meth:`createVectorTable` creates the corresponding ``vec0`` virtual table
automatically (see Section 9.2). No advance configuration or migration is
required.

The current project default is 384-dim (``text-embedding-ada-002`` variant).
When a chat switches to a 1024-dim model, the dual-write in
``saveMessageEmbedding()`` inserts into ``vec_message_embeddings_1024``
alongside the existing ``vec_message_embeddings_384`` rows, and searches
use the table matching the current model's dimension.

---

## 5. Repository Integration

### 5.1 Changes to `ChatSearchRepository._semanticSearch()`

The method at `internal/database/repositories/chat_search.py:266` gains a fast path:

```python
async def _semanticSearch(self, ...) -> List[ChatMessageDict]:
    try:
        sqlProvider = await self.manager.getProvider(
            chatId=chatId, dataSource=dataSource, readonly=True
        )

        # --- NEW: native vector search fast path ---
        if sqlProvider.isVectorSearchSupported():
            try:
                # Dimension is inferred from the query vector length,
                # avoiding dependency on model introspection APIs that
                # vary across embedding providers.
                dimension = len(queryEmbedding)
                nativeResults = await self._nativeVectorSearch(
                    sqlProvider=sqlProvider,
                    chatId=chatId,
                    queryEmbedding=queryEmbedding,
                    limit=limit,
                    topK=topK,
                    userFilter=userFilter,
                    categoryFilter=categoryFilter,
                    maxAgeDays=maxAgeDays,
                    rootMessageId=rootMessageId,
                    modelName=modelName,
                    maxMessages=maxMessages,
                    dimension=dimension,
                )
                if nativeResults:  # Only use native results if non-empty.
                    return nativeResults
                # Empty result — vec0 table may be empty (pre-backfill).
                # Fall through to numpy path.
            except Exception as e:
                logger.warning(
                    f"Native vector search failed, falling back to numpy: {e}"
                )
                # Fall through to numpy path below.

        # --- EXISTING: numpy fallback (unchanged) ---
        embeddingList, messageIds = await self._loadEmbeddingsFromDb(...)
        # ... rest of current code ...
```

### 5.2 New Method: `_nativeVectorSearch()`

This new private method replaces steps 1-3 of the current flow:

```python
async def _nativeVectorSearch(
    self,
    sqlProvider: BaseSQLProvider,
    chatId: int,
    queryEmbedding: list[float],
    *,
    limit: Optional[int],
    topK: int,
    userFilter: Optional[int],
    categoryFilter: Optional[Sequence[MessageCategory]],
    maxAgeDays: Optional[int],
    rootMessageId: Optional[MessageId],
    modelName: Optional[str],
    maxMessages: Optional[int],
    dimension: int,
) -> list[ChatMessageDict]:
    """Semantic search using the provider's native vector search.

    Pushes the cosine distance computation into the database engine,
    avoiding loading all embeddings into Python memory. Any exceptions
    propagate to the caller, which falls back to the numpy path.

    If the native search returns an empty result (vector table exists
    but no matching rows — e.g. during pre-backfill period), the caller
    checks the return value and falls through to numpy. If the vec0 table
    does not exist at all (no embeddings written yet for this dimension),
    ``sqlProvider.vectorSearch()`` raises an exception, which propagates
    to the ``try/except`` in ``_semanticSearch()`` and triggers numpy
    fallback. Table creation happens solely in the write path
    (``saveMessageEmbedding()`` → ``_upsertVecMessageEmbedding()``),
    which correctly uses ``readonly=False``.

    The approach:
    1. If ``maxMessages`` is set, compute ``minDate`` by querying
       the date of the Nth most recent message in ``chat_messages``.
    2. Call ``sqlProvider.vectorSearch()`` with partition-key filter
       (chatId, model) and optionally ``date >= :minDate`` to cap
       the candidate pool to the ``maxMessages`` most recent messages.
    3. Apply user/category/age/thread post-filters.
    4. Convert distances to similarity scores and re-rank.
    5. Fetch full message rows via ``_fetchSearchResultRows()``.

    ``maxMessages`` is handled via **Option B** (pre-filter): a date
    cutoff is computed and pushed into the vec0 MATCH query via the
    ``filterClause`` / ``filterParams`` parameters. This ensures the
    native path mirrors the numpy path's semantics: both paths rank
    over the same candidate pool. Option A (post-filter after
    ranking) was rejected because it produces different results from
    the numpy path.

    If vec0 does not support WHERE on non-partition metadata columns
    (like ``date``), fall back to a post-filter approach: retrieve
    candidates with a wider ``topK``, fetch their dates from
    ``chat_messages``, filter by recency, and re-trim to ``topK``.

    Args:
        sqlProvider: The SQL provider (must have isVectorSearchSupported() == True).
        chatId: Chat to search in.
        queryEmbedding: Query vector as list[float].
        limit: Max results after ranking.
        topK: How many nearest neighbours to retrieve.
        userFilter: Optional user ID filter.
        categoryFilter: Optional category filter.
        maxAgeDays: Only messages newer than N days.
        rootMessageId: Optional thread root filter.
        modelName: Embedding model name filter.
        maxMessages: If set, limit candidates to the N most recent
            messages by date. Applied as a pre-filter via ``date >=
            :minDate`` in the vec0 MATCH query. None means no
            date-based cap.
        dimension: Embedding dimension (e.g. 384, 1024). Used to
            construct the vec0 table name:
            ``f"vec_message_embeddings_{dimension}"``.

    Returns:
        List of ChatMessageDict with ``score`` set to cosine similarity.
        Returns empty list if the vec0 table is not yet created or
        contains no matching rows (caller handles via numpy fallback).
    """
    if modelName is None:
        return []

    # Guard against zero or near-zero query vectors (cosine distance is undefined).
    queryNorm = float(np.linalg.norm(np.asarray(queryEmbedding, dtype=np.float32)))
    if queryNorm < 1e-8:
        logger.warning(
            f"Query embedding has near-zero norm ({queryNorm}) for chat {chatId}; "
            f"semantic search results will be arbitrary"
        )
        return []

    # Build the query vector as bytes
    queryVectorBytes: bytes = array.array("f", queryEmbedding).tobytes()

    # The vec0 virtual table handles partition-key filtering natively.
    # For user/category/age/thread, we use a post-filter approach:
    # call vectorSearch on vec_message_embeddings_{dimension} with (chatId, model)
    # filter, then apply _filterMessageIds in a second step.
    # This reuses the existing battle-tested filter code and keeps
    # the vectorSearch interface simple.

    # Build filter for vectorSearch — partition-key filter always present.
    filterParts: list[str] = ["chat_id = :chatId AND model = :modelName"]
    filterParams: dict[str, str | int | float | bytes | None] = {
        "chatId": chatId,
        "modelName": modelName,
    }

    # Option B: pre-filter by date to enforce maxMessages cap.
    # Compute the date of the Nth most recent message; messages older
    # than this cutoff are excluded from the candidate pool. This
    # mirrors the numpy path's semantics (LIMIT on recent messages
    # before ranking).
    if maxMessages is not None:
        cutoffQuery = """
            SELECT date FROM chat_messages
            WHERE chat_id = :chatId
            ORDER BY date DESC
        """
        cutoffQuery = sqlProvider.applyPagination(
            cutoffQuery, limit=1, offset=maxMessages - 1
        )
        cutoffRow = await sqlProvider.executeFetchOne(
            cutoffQuery, {"chatId": chatId}
        )
        if cutoffRow is not None:
            filterParts.append("date >= :minDate")
            filterParams["minDate"] = cutoffRow["date"]

    # NOTE: This requires vec0 to support WHERE clauses on
    # non-partition-key metadata columns like ``date``. If the
    # installed version of sqlite-vec does not support this, fall
    # back to post-filter (Option A): retrieve candidates without
    # the date constraint, fetch their dates from chat_messages,
    # filter by recency client-side, and re-trim to topK.
    # Verify empirically before writing the implementation.

    # Build dimension-aware table name. The vec0 table is created
    # lazily in the write path (_upsertVecMessageEmbedding) with
    # readonly=False, not here. If the table doesn't exist yet,
    # vectorSearch() will raise an exception that the caller
    # catches and falls through to numpy.
    vecTable = f"vec_message_embeddings_{dimension}"

    vecResults = await sqlProvider.vectorSearch(
        table=vecTable,
        vectorColumn="embedding",
        returnColumns=["message_id", "date"],
        queryVector=queryVectorBytes,
        k=topK,
        filterClause=" AND ".join(filterParts),
        filterParams=filterParams,
        distanceMetric=VectorDistanceMetric.COSINE,
    )

    if not vecResults:
        return []

    # Convert to MessageId + similarity score.
    # sqlite-vec cosine distance = 1.0 - cosine_similarity
    candidateIds: list[MessageId] = []
    scoreByMessageId: dict[str, float] = {}
    for vr in vecResults:
        mid = MessageId(vr["rowKey"]["message_id"])
        candidateIds.append(mid)
        scoreByMessageId[mid.asStr()] = 1.0 - vr["distance"]

    # Apply post-filters (user, category, age, thread) if any are set.
    needsPostFilter: bool = (
        userFilter is not None
        or categoryFilter is not None
        or maxAgeDays is not None
        or rootMessageId is not None
    )
    if needsPostFilter:
        candidateIds = await self._filterMessageIds(
            sqlProvider=sqlProvider,
            chatId=chatId,
            candidateMessageIds=candidateIds,
            userFilter=userFilter,
            categoryFilter=categoryFilter,
            maxAgeDays=maxAgeDays,
            rootMessageId=rootMessageId,
        )
        if not candidateIds:
            return []

    # Re-order by score descending (best match first).
    candidateIds.sort(
        key=lambda mid: scoreByMessageId.get(mid.asStr(), 0.0),
        reverse=True,
    )

    # Trim to top-K after filtering.
    # NOTE: This slice is typically a no-op because vectorSearch was called
    # with k=topK and _filterMessageIds can only remove elements. We keep it
    # for defensive consistency; if overscan is desired later, increase the
    # vectorSearch k parameter (e.g. k=topK*3) and allow the trim to be
    # meaningful.
    topIds = candidateIds[:topK]
    topScores = [scoreByMessageId.get(mid.asStr(), 0.0) for mid in topIds]

    return await self._fetchSearchResultRows(
        sqlProvider=sqlProvider,
        chatId=chatId,
        topIds=topIds,
        topScores=topScores,
        limit=limit,
    )
```

### 5.3 Flow Diagram

```
searchChatMessages(chatId, queryEmbedding, ...)
  |
  v
_semanticSearch()
  |
  +-- isVectorSearchSupported()?
  |     |
  |     YES --> _nativeVectorSearch()
  |     |        |
  |     |        +-- sqlProvider.vectorSearch()       <-- cosine in C
  |     |        +-- _filterMessageIds()             <-- reuse existing post-filter
  |     |        +-- _fetchSearchResultRows()        <-- reuse existing row fetch
  |     |        |
  |     |        +-- (on exception) ~~~ falls back to numpy path below
  |     |
  |     NO  --> _loadEmbeddingsFromDb()              <-- existing numpy path
  |              +-- _filterMessageIds()
  |              +-- numpy cosine similarity
  |              +-- _fetchSearchResultRows()
```

### 5.4 Post-Filter Trade-off

The native path retrieves the top-K by vector distance first, then applies ``_filterMessageIds`` as a post-filter. This means:

- If a user filter removes 80% of the top-K, the effective result set is smaller than K.
- The numpy path pre-filters before ranking, so it always delivers the true top-K from the filtered set.

This trade-off is acceptable because:
1. Pre-filtering in SQL with JOINs inside ``vectorSearch`` would require the provider interface to support arbitrary JOINs, which violates the "simple interface" goal.
2. The ``topK`` parameter is already generous (default 100) relative to the final ``limit`` (default 10), providing headroom for post-filter attrition.
3. If post-filter attrition is a problem in practice, the caller can increase ``topK``.
4. The vec0 table supports partition-key filters (``chat_id``, ``model``) natively, but the remaining filters (user, category, age, thread) span a separate table (``chat_messages``) and are handled as a post-filter for simplicity.

### 5.5 Model Change Cleanup

When a chat's embedding model changes (e.g. from 384-dim to 1024-dim),
old embeddings from the previous model linger in the old vec0 tables.
The CRON job (``ChatSearchHandler._dtCronJob()``) handles cleanup.

**Mechanism**: Stateless, idempotent cleanup that runs on every CRON
tick for chats with embeddings enabled. On each tick, discover all
vec0 tables and delete rows whose model does not match the current
model. This avoids in-memory state (which would be empty after
restart) and handles model changes even when they occurred before the
last restart.

```python
# In ChatSearchHandler._dtCronJob(), within the per-chat loop
# for each chat with embeddings enabled:
currentModelName = ...  # from chat settings
tables = await sqlProvider.listTables("vec_message_embeddings_%")
for table in tables:
    await sqlProvider.execute(
        f"DELETE FROM {table} "
        f"WHERE chat_id = :chatId AND model != :currentModel",
        {"chatId": chatId, "currentModel": currentModelName},
    )
```

This is cheap on the common path (model unchanged): the DELETE
matches zero rows. No tracking dict is needed.

The ``date`` column also handles staleness indirectly: older embeddings
naturally age out via the ``maxMessages`` pre-filter. But explicit cleanup
at model-switch time is more precise and prevents cross-model pollution
of search results even when the old model's dimension happens to match.

**Important design note**: The ``listTables`` approach inspects the actual
database rather than relying on a hardcoded set of tables, so it is
automatically correct regardless of which dimensions have been used
historically.

---

## 6. Other Providers (Forward-Looking)

The interface is designed to accommodate future implementations:

### 6.1 PostgreSQL (`pgvector`)

```sql
-- Extension: CREATE EXTENSION IF NOT EXISTS vector;
-- Column type: embedding vector(384)
-- Query:
SELECT message_id,
       embedding <=> :queryVector::vector AS distance
FROM message_embeddings
WHERE chat_id = :chatId AND model = :modelName
ORDER BY distance ASC
LIMIT :k;
```

`PostgreSQLProvider` would:
- Check for `pgvector` in `connect()` via `SELECT * FROM pg_extension WHERE extname = 'vector'`.
- Override `vectorSearch()` with `<=>` (cosine distance) or `<->` (L2 distance) operators.
- Accept `queryVector` as bytes and cast to `::vector` in the query.
- Override ``listTables()`` using ``pg_catalog.pg_tables``:

  ```sql
  SELECT tablename FROM pg_catalog.pg_tables
  WHERE schemaname = 'public' AND tablename LIKE :pattern
  ```
- Override ``createVectorTable()`` to emit ``pgvector`` DDL:

  ```sql
  CREATE TABLE IF NOT EXISTS {tableName} (
      message_id TEXT,
      chat_id INTEGER,
      model TEXT,
      date TEXT,
      embedding vector({dim})
  );
  CREATE INDEX IF NOT EXISTS {tableName}_idx ON {tableName}
      USING hnsw (embedding vector_cosine_ops);
  ```

  (Future work — pgvector is not yet wired in the factory.)

### 6.2 MySQL (HeatWave Vector Store)

MySQL 9.0+ has `VECTOR` type and `VECTOR_DISTANCE()` function. Similar scalar-function approach to the sqlite-vec fallback (Section 4.6).
- Override ``listTables()`` with ``SHOW TABLES LIKE :pattern``.
- ``createVectorTable()`` is future work if MySQL vector support is needed.

### 6.3 SQLink

Depends on the remote server's capabilities. If the remote server has vector extensions, `SQLinkProvider` could pass through the vector query. For now, SQLink falls back to the numpy path.
- ``listTables()``: may not be supported on a remote SQLink server (inherits ``NotImplementedError`` from the base class).
- ``createVectorTable()``: not supported via SQLink (inherits ``NotImplementedError``).

---

## 7. Configuration

No configuration key is needed. The provider auto-detects ``sqlite-vec`` availability at connect time. If the extension is not installed, ``isVectorSearchSupported()`` returns ``False`` and the numpy fallback is used transparently. To disable native search, uninstall ``sqlite-vec`` (``pip uninstall sqlite-vec``).

The new methods (``listTables``, ``createVectorTable``) are also
provider-specific and require no configuration. ``listTables`` queries
database introspection and ``createVectorTable`` creates tables on demand.

---

## 8. Testing Strategy

### 8.1 Unit Tests for Provider Interface

File: `tests/database/providers/test_vector_search.py`

```python
class TestVectorSearchInterface:
    """Test the BaseSQLProvider vector search defaults."""

    async def test_isVectorSearchSupportedDefaultFalse(self):
        """Default isVectorSearchSupported returns False."""
        # Use a minimal concrete subclass or mock.

    async def test_vectorSearchDefaultRaises(self):
        """Default vectorSearch raises NotImplementedError."""
```

### 8.2 Unit Tests for SQLite3Provider

File: `tests/database/providers/test_sqlite3_vector_search.py`

Two scenarios:

**8.2.1 sqlite-vec installed (real extension)**:
```python
class TestSQLite3VectorSearchReal:
    """Tests with real sqlite-vec extension."""

    @pytest.fixture
    async def providerWithVec(self, tmp_path):
        """SQLite3Provider with sqlite-vec loaded."""
        provider = SQLite3Provider(dbPath=str(tmp_path / "test.db"), ...)
        await provider.connect()
        if not provider.isVectorSearchSupported():
            pytest.skip("sqlite-vec not installed")
        yield provider
        await provider.disconnect()

    async def test_vectorSearchCosine(self, providerWithVec):
        """Basic cosine search returns correct ordering."""
        # Insert known vectors, search, verify top-1 is the closest.

    async def test_vectorSearchWithFilter(self, providerWithVec):
        """Filter clause restricts results."""

    async def test_vectorSearchEmptyTable(self, providerWithVec):
        """Empty table returns empty list."""

    async def test_vectorSearchUnsupportedMetric(self, providerWithVec):
        """Unknown metric raises ValueError."""
```

**8.2.2 sqlite-vec NOT installed (mock/skip)**:
```python
class TestSQLite3VectorSearchFallback:
    """Tests for graceful fallback when sqlite-vec is unavailable."""

    async def test_isVectorSearchSupportedFalseWithoutExtension(self):
        """Provider reports False when sqlite-vec is not loaded."""

    async def test_vectorSearchRaisesWithoutExtension(self):
        """vectorSearch raises NotImplementedError without sqlite-vec."""
```

**8.2.3 listTables and createVectorTable**:
```python
class TestSQLite3VecTableManagement:
    """Tests for listTables and createVectorTable."""

    async def test_listTablesReturnsTables(self, providerWithVec):
        """listTables returns vec0 tables matching pattern."""
        # Create vec_message_embeddings_384 and another table.
        # Verify listTables("vec_message_embeddings_%") returns only
        # the matching tables.

    async def test_listTablesAll(self, providerWithVec):
        """listTables with default '%' returns all tables."""

    async def test_createVectorTableBasic(self, providerWithVec):
        """createVectorTable creates a vec0 table successfully."""
        columns = [
            {"name": "message_id", "columnType": VectorColumnType.TEXT},
            {"name": "chat_id", "columnType": VectorColumnType.INTEGER, "isPartitionKey": True},
            {"name": "embedding", "columnType": VectorColumnType.VECTOR,
             "vectorDimension": 384,              "distanceMetric": VectorDistanceMetric.COSINE},
        ]
        await providerWithVec.createVectorTable("vec_message_embeddings_384", columns)
        tables = await providerWithVec.listTables("vec_message_embeddings_%")
        assert "vec_message_embeddings_384" in tables

    async def test_createVectorTableNoVectorColumn(self, providerWithVec):
        """createVectorTable raises ValueError without VECTOR column."""

    async def test_createVectorTableIdempotent(self, providerWithVec):
        """createVectorTable is idempotent (CREATE VIRTUAL TABLE IF NOT EXISTS)."""

    async def test_createVectorTableDifferentDimensions(self, providerWithVec):
        """Tables with different dimensions coexist."""
        cols384 = [
            {"name": "message_id", "columnType": VectorColumnType.TEXT},
            {"name": "embedding", "columnType": VectorColumnType.VECTOR,
             "vectorDimension": 384, "distanceMetric": VectorDistanceMetric.COSINE},
        ]
        cols1024 = [
            {"name": "message_id", "columnType": VectorColumnType.TEXT},
            {"name": "embedding", "columnType": VectorColumnType.VECTOR,
             "vectorDimension": 1024, "distanceMetric": VectorDistanceMetric.COSINE},
        ]
        await providerWithVec.createVectorTable("vec_message_embeddings_384", cols384)
        await providerWithVec.createVectorTable("vec_message_embeddings_1024", cols1024)
        tables = await providerWithVec.listTables("vec_message_embeddings_%")
        assert "vec_message_embeddings_384" in tables
        assert "vec_message_embeddings_1024" in tables

    async def test_vectorSearchDimensionAware(self, providerWithVec):
        """vectorSearch on dimension-specific table returns correct results."""
```

### 8.3 Integration Tests for Repository

File: `tests/database/repositories/test_chat_search_native.py`

```python
class TestChatSearchNativeVectorSearch:
    """Test _nativeVectorSearch path in ChatSearchRepository."""

    async def test_nativePathUsedWhenAvailable(self, mockProvider):
        """When isVectorSearchSupported() is True, native path is taken."""
        # Mock provider.isVectorSearchSupported() -> True
        # Mock provider.vectorSearch() -> known results with rowKey
        # Verify _loadEmbeddingsFromDb is NOT called
        # Verify vectorSearch IS called

    async def test_fallbackWhenNotAvailable(self, mockProvider):
        """When isVectorSearchSupported() is False, numpy path is taken."""
        # Mock provider.isVectorSearchSupported() -> False
        # Verify _loadEmbeddingsFromDb IS called

    async def test_nativeResultsMatchFallback(self, realDbWithVec):
        """Both paths return equivalent results for the same data."""
        # Insert embeddings into vec0 table and message_embeddings,
        # run both paths, compare top-K IDs and scores.

    async def test_postFilterApplied(self, mockProvider):
        """User/category/age filters work on native path."""
        # Mock vectorSearch to return rowKey dicts, verify
        # _filterMessageIds is called with extracted message_ids.

    async def test_vectorSearchReturnsRowKey(self, realDbWithVec):
        """vectorSearch returns rowKey dict with correct columns."""
```

**8.3.1 Model Change Cleanup Tests**:
```python
class TestModelChangeCleanup:
    """Tests for model change cleanup logic (Section 5.5)."""

    async def test_cleanupDeletesOldModelRows(self, realDbWithVec):
        """DELETE removes embeddings for old model from vec0 tables."""
        # Insert embeddings for modelA and modelB in the same chat.
        # Run cleanup for modelA → modelB switch.
        # Verify modelA rows are gone, modelB rows remain.

    async def test_cleanupOnlyAffectsSpecifiedChat(self, realDbWithVec):
        """Cleanup for one chat does not delete rows for other chats."""

    async def test_cleanupAcrossMultipleTables(self, realDbWithVec):
        """When model switch changes dimension, cleanup deletes from
        all vec0 tables (old and new dimension)."""

    async def test_noopWhenModelUnchanged(self, realDbWithVec):
        """No cleanup when model has not changed."""
```

### 8.4 CI Considerations

- `sqlite-vec` should be added to `requirements.direct.txt` (under `# Runtime`) so CI has the extension.
- Tests that require sqlite-vec use `pytest.skip("sqlite-vec not installed")` when `_SQLITE_VEC_AVAILABLE` is `False`, ensuring the test suite passes even if the dependency is missing (e.g., in minimal dev environments).
- The `test_nativeResultsMatchFallback` test is the critical correctness test -- it verifies both paths produce the same ranking.
- The vec0 virtual table tests require the extension to be loaded; skip them gracefully if ``isVectorSearchSupported()`` returns ``False``.

---

## 9. Migration Plan

vec0 IS Phase 1. There is no two-phase approach — the ``vec0`` virtual table is created in the initial migration and used as the primary native search path.

### 9.1 No Migration Needed

vec0 tables are **not** created in a migration. Instead, they are created
dynamically at runtime via ``createVectorTable()`` on the first write
operation for a given dimension. This is the key design decision that
eliminates several problems:

- No migration version to manage for each dimension.
- No backfill SQL (no ``INSERT...SELECT...JOIN``) — the existing CRON job
  (which already regenerates embeddings via ``embedAndSaveMessage()``)
  populates both ``message_embeddings`` and the vec0 table.
- Zero coordination between vector table schema and the migration
  sequence.

**Pre-existing embeddings note**: For a deployment with pre-existing
embeddings (already stored in ``message_embeddings`` before the native
search feature was added), the CRON job's first cycle will regenerate
embeddings for messages that lack them (i.e. new messages since the
last cycle) and populate vec0 via the dual-write in
``saveMessageEmbedding()``. Messages that already have embeddings for
the current model are skipped by
``getMessagesWithoutEmbeddings()`` — they never enter the vec0 table
during the first cycle. Those existing embeddings will be picked up
on subsequent CRON cycles when ``REGENERATE_EMBEDDINGS`` is enabled,
or when the embedding model changes (triggering cleanup +
regeneration). The empty-result-to-numpy fallback (Section 5.1)
ensures searches work correctly during this transitional period:
when the vec0 table is empty, ``_semanticSearch()`` falls through to
the existing numpy path and returns correct results.

**Down migration**: If a rollback is needed, the ``down()`` handler
discovers and drops all vec0 tables dynamically:

```python
async def down(self, sqlProvider: BaseSQLProvider) -> None:
    """Drop all vec0 virtual tables discovered via listTables.

    Args:
        sqlProvider: SQL provider abstraction.

    Returns:
        None.
    """
    tables = await sqlProvider.listTables("vec_message_embeddings_%")
    for table in tables:
        await sqlProvider.execute(
            f"DROP TABLE IF EXISTS {table}"
        )
```

### 9.2 Dual-Write in Repository

In ``ChatEmbeddingsRepository.saveMessageEmbedding()``, after the existing
upsert to ``message_embeddings``, add an INSERT/DELETE into the
dimension-specific vec0 table:

```python
# After the existing upsert to message_embeddings:
if sqlProvider.isVectorSearchSupported():
    await _upsertVecMessageEmbedding(
        sqlProvider=sqlProvider,
        chatId=chatId,
        messageId=messageId,
        model=model,
        date=date,
        embedding=embeddingBytes,
        dimensions=dimensions,
    )
```

The helper ``_upsertVecMessageEmbedding`` determines the dimension from
``len(embeddingBytes) / 4`` (since each float32 is 4 bytes) or from the
model config, then lazily creates the vec0 table if needed and performs
the DELETE + INSERT:

```python
async def _upsertVecMessageEmbedding(
    sqlProvider: BaseSQLProvider,
    chatId: int,
    messageId: str,
    model: str,
    date: str,
    embedding: bytes,
    dimensions: int,
) -> None:
    """Upsert a row into the dimension-specific vec0 table.

    Lazily creates the vec0 virtual table on first use. Uses DELETE +
    INSERT because vec0 does not support conventional UPSERT.

    Args:
        sqlProvider: SQL provider abstraction.
        chatId: Chat ID.
        messageId: Message ID.
        model: Embedding model name.
        date: ISO-8601 message date string.
        embedding: Float32 embedding bytes.
        dimensions: Embedding dimension (inferred from model config).
    """
    tableName = f"vec_message_embeddings_{dimensions}"

    existingTables = await sqlProvider.listTables("vec_message_embeddings_%")
    if tableName not in existingTables:
        columns: list[VectorColumnDef] = [
            {"name": "message_id", "columnType": VectorColumnType.TEXT},
            {"name": "chat_id", "columnType": VectorColumnType.INTEGER, "isPartitionKey": True},
            {"name": "model", "columnType": VectorColumnType.TEXT, "isPartitionKey": True},
            {"name": "date", "columnType": VectorColumnType.TEXT},
             {"name": "embedding", "columnType": VectorColumnType.VECTOR,
              "vectorDimension": dimensions, "distanceMetric": VectorDistanceMetric.COSINE},
        ]
        await sqlProvider.createVectorTable(tableName, columns)

    # If vec0 does not support DELETE with WHERE on metadata columns,
    # fall back to SELECT rowid first, then DELETE by rowid.
    await sqlProvider.execute(
        f"DELETE FROM {tableName} "
        f"WHERE chat_id = :chatId AND message_id = :messageId AND model = :model",
        {"chatId": chatId, "messageId": messageId, "model": model},
    )
    await sqlProvider.execute(
        f"INSERT INTO {tableName} "
        f"(message_id, chat_id, model, date, embedding) "
        f"VALUES (:messageId, :chatId, :model, :date, :embedding)",
        {"messageId": messageId, "chatId": chatId, "model": model,
         "date": date, "embedding": embedding},
    )
```

**Verification required**: Confirm that vec0 supports DELETE with WHERE
predicates on metadata/partition-key columns. If not, the helper must
first SELECT the ``rowid`` then DELETE by ``rowid``:

```python
    # If vec0 does not support DELETE with WHERE on metadata columns,
    # fall back to SELECT rowid first, then DELETE by rowid.
    row = await sqlProvider.executeFetchOne(
        f"SELECT rowid FROM {tableName} WHERE chat_id = :chatId AND message_id = :messageId AND model = :model",
        {"chatId": chatId, "messageId": messageId, "model": model},
    )
    if row is not None:
        await sqlProvider.execute(f"DELETE FROM {tableName} WHERE rowid = :rowid", {"rowid": row["rowid"]})
```

If the vec0 insert fails for any reason (extension unloaded, schema
mismatch, data corruption), the error is logged at ``warning`` level and
swallowed. The physical ``message_embeddings`` row is unaffected and
remains the source of truth. The first CRON cycle backfills existing
messages into the vec0 table naturally (since the CRON job calls
``embedAndSaveMessage()`` which triggers the dual-write).

### 9.3 Rollback

Run the down migration to drop all ``vec_message_embeddings_%`` tables.
The authoritative data remains in ``message_embeddings``. The numpy
fallback continues to work transparently.

---

## 10. Implementation Plan

### Step 1: Add `sqlite-vec` Dependency
- Add `sqlite-vec==0.1.10a4` (or latest) to `requirements.direct.txt` under `# Runtime`.
- Re-freeze `requirements.txt`.
- Verify `make install` succeeds.

### Step 2: Add Types and Provider Interface
- Add `VectorSearchResult` TypedDict to `internal/database/providers/base.py`.
- Add `VectorDistanceMetric` StrEnum and `VectorColumnType` StrEnum to `internal/database/providers/base.py`.
- Add `VectorColumnDef` TypedDict to `internal/database/providers/base.py`.
- Add `isVectorSearchSupported()`, `vectorSearch()`, `listTables()`, and `createVectorTable()` to `BaseSQLProvider` with defaults.
- Update `__all__` in `internal/database/providers/__init__.py` to include all new types and method exports.
- Write unit tests for defaults (including `listTables` and `createVectorTable` raising `NotImplementedError`).

### Step 3: Implement SQLite3Provider Override
- Add `_SQLITE_VEC_AVAILABLE` flag and import guard at module top.
- Add `_vectorSearchAvailable` slot and loading logic in `connect()`.
- Override `isVectorSearchSupported()`, `vectorSearch()` (vec0 MATCH query), `listTables()`, and `createVectorTable()`.
- Write provider-level tests with vec0 virtual table, including dimension-aware table creation and listing.

### Step 4: Repository Integration
- Add dual-write logic in ``ChatEmbeddingsRepository.saveMessageEmbedding()``: after upserting to ``message_embeddings``, also INSERT/DELETE into the dimension-specific vec0 table (lazy creation via ``createVectorTable``).
- Add ``_nativeVectorSearch()`` to ``ChatSearchRepository`` with ``dimension`` parameter and dimension-aware table construction.
- Add the fast-path check in ``_semanticSearch()``, resolving ``dimension`` from model config.
- Add model change cleanup (Section 5.5) in ``ChatSearchHandler._dtCronJob()``.
- Write integration tests including the equivalence test, maxMessages post-filter test, dimension-aware naming, and model change cleanup.

### Step 5: Quality Gates
- `make format lint` before and after.
- `make test` (full suite, must pass).
- Manual smoke test with a real chat that has embeddings.

### Step 6: Documentation Update
Dispatch `update-project-docs` skill. Docs to update:
- `docs/llm/database.md` -- new provider methods (`vectorSearch`, `isVectorSearchSupported`), ``VectorSearchResult`` / ``VectorDistanceMetric`` types, vec0 virtual table schema.
- `docs/llm/services.md` -- if ChatSearchHandler logic changes.
- `docs/llm/libraries.md` -- new `sqlite-vec` dependency.
- `docs/llm/configuration.md` -- no new config key needed (native search auto-detects).
- `docs/database-schema.md` and `docs/database-schema-llm.md` -- add `vec_message_embeddings_N` virtual table schema (one per dimension) with columns (message_id, chat_id, model, date, embedding).

---

## 11. Open Questions and Risks

### 11.1 sqlite-vec Maturity

`sqlite-vec` is at v0.1.10-alpha. The ``vec0`` virtual table API may evolve before v1.0. **Mitigation**: The vec0 schema is ephemeral (virtual table backed by the physical ``message_embeddings`` table). If the vec0 API changes, the virtual table can be recreated via a migration. The authoritative data always resides in ``message_embeddings``. If vec0 stability is a concern, the provider can fall back to scalar functions on the physical table (see Section 4.6).

### 11.2 macOS Extension Loading

The default macOS Python (Apple-supplied) disables `enable_load_extension()`. Homebrew Python works. The project's `run.sh` uses `./venv/bin/python3` which is typically Homebrew-sourced on macOS. **Mitigation**: If loading fails, the provider silently falls back to numpy. Log a debug message so the issue is diagnosable.

### 11.3 aiosqlite Thread Safety

`sqlite-vec` functions are thread-safe (they operate on the connection's data, not global state). `aiosqlite` serialises all operations through a single background thread per connection, so there are no concurrent-access concerns. **No mitigation needed.**

### 11.4 Post-Filter Attrition (Section 5.4)

The native path applies user/category/age/thread filters *after* vector ranking, potentially reducing the result set below the desired K. **Mitigation**: The default `topK=100` provides 10x headroom over the default `limit=10`. Monitor in practice; increase `topK` or push filters into the SQL if needed.

### 11.5 Multiple Dimensions

**Solved** by dimension-aware table naming. Each embedding dimension gets
its own vec0 table (``vec_message_embeddings_384``, ``vec_message_embeddings_1024``,
etc.). The repository constructs the table name dynamically from the
embedding model's output dimension, so the correct table is always used.

When a chat switches embedding models (e.g., 384-dim to 1024-dim):
- New writes go to ``vec_message_embeddings_1024``.
- Old 384-dim embeddings remain in ``vec_message_embeddings_384``.
- ``vectorSearch()`` uses the table matching the current model's dimension.
- The model change cleanup (Section 5.5) deletes old-dimension embeddings
  when the model switch is detected.

No migration or manual table creation is needed — tables are created lazily
on first write via ``createVectorTable()``.

### 11.6 BLOB Format Compatibility

The existing embedding storage uses `array.array("f", vec).tobytes()` which produces little-endian IEEE 754 float32 bytes on all platforms Python 3.12 supports. `sqlite-vec` expects the same format. `sqlite_vec.serialize_float32()` produces the identical output (it uses `struct.pack`). **No conversion needed.**

### 11.7 SQLink `listTables` Compatibility

``SQLinkProvider`` may not support ``listTables()`` because it proxies
queries to a remote server whose introspection capabilities are unknown.
The base class default raises ``NotImplementedError``. The vector search
subsystem must handle this gracefully:

- In ``_nativeVectorSearch()``: if ``listTables()`` raises
  ``NotImplementedError``, fall back to catching the exception and
  assuming the vec0 table does not exist (which triggers creating it).
  This is safe because ``createVectorTable`` uses ``CREATE VIRTUAL TABLE
  IF NOT EXISTS``.
- In model change cleanup (Section 5.5): if ``listTables()`` is not
  supported, skip cleanup for that provider (log a debug message).

### 11.8 Performance Validation

The claim "faster in C" should be validated with a benchmark before shipping. Suggested: a test with 10K, 50K, and 100K embeddings at 384 dimensions, comparing wall-clock time and peak memory for the vec0 path vs. the numpy fallback. **Action**: Include a `@pytest.mark.benchmark` test in Step 4 (repository integration).
