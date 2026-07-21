"""Dependency-usage regression tests pinning the sqlite-vec vec0 contract.

``sqlite-vec`` (pinned ``0.1.9``) is a loadable native SQLite extension that
provides the ``vec0`` virtual table used for cosine KNN search. Gromozeka's
semantic search over chat messages and user memories leans on three behaviours
that are NOT stable API guarantees of vec0:

1. **``ORDER BY distance`` honoured** — the KNN queries carry an explicit
   ``ORDER BY distance`` (see the test queries at lines ~327, ~353), which is
   exactly what production emits at
   ``internal/database/providers/sqlite3.py:540``. What is pinned here is that
   vec0 HONOURS ``ORDER BY`` on the ``distance`` pseudo-column of a vec0
   virtual table and returns rows ascending by distance. This is NOT a pin on
   vec0's implicit (no-ORDER-BY) ordering — production never relies on that. A
   future bump that stops honouring ``ORDER BY distance`` is what this guards.
   See ``internal/database/repositories/chat_search.py`` (vec0 KNN at lines
   ~728, ~764-785) and
   ``internal/database/repositories/user_memories.py`` (~881, ~925-943).
2. **``score = 1.0 - distance`` mapping** — both repositories convert vec0's
   returned ``distance`` into a similarity score via ``1.0 - distance``
   (``user_memories.py:943``, ``chat_search.py:785``). vec0's cosine distance
   is defined as ``1.0 - cosine_similarity``; these tests pin that mapping
   against numpy-computed cosine within float32 epsilon.
3. **DELETE-by-metadata semantics** — production
   (``internal/database/repositories/user_memories.py:1188-1208``) carries a
   LITERAL ``TODO: Test on latest sqlite-vec and leave only one way``. The
   code tries a metadata-WHERE DELETE (``chat_id``+``user_id``+``memory_id``)
   and falls back to a rowid DELETE on exception. The authors already hit
   version drift on which WHERE predicates vec0 accepts. vec0's WHERE-predicate
   restrictions and shadow-table behaviour are not stable across releases, and
   the pip package bundles a binary that changes per release.

These tests pin the CURRENT observed behaviour under ``sqlite-vec 0.1.9`` so a
version bump that silently breaks vector search or flips the DELETE shape fails
loudly here instead of in production.

Methodology: every operation below was run against the pinned ``sqlite-vec
0.1.9`` FIRST to OBSERVE the actual output, THEN the assertions were written to
match observed reality. They do NOT assert what sqlite-vec "should" do — they
assert what it DOES today. If a bump changes any pinned value, update the test
after re-verifying the production code paths still behave correctly.
"""

import array
import sqlite3
from typing import List, Tuple

import numpy as np
import pytest

#: ``sqlite-vec`` is an optional dependency. When the package is not installed
#: at all, ``importorskip`` skips the whole module rather than failing
#: collection. (A separate failure mode — the wheel is installed but its bundled
#: native binary won't load — is handled by the ``RuntimeError`` raised inside
#: ``loadVecConnection`` further down.) ``importorskip`` returns the module
#: object so the rest of this file (``sqlite_vec.loadable_path()``, etc.) works
#: unchanged.
sqlite_vec = pytest.importorskip("sqlite_vec")

# ---------------------------------------------------------------------------
# Constants — mirror production's vec0 user-memories table
# (internal/database/repositories/user_memories.py:1162-1186).
# ---------------------------------------------------------------------------

#: Pinned sqlite-vec version these assertions were observed against.
PINNED_VEC_VERSION: str = "v0.1.9"

#: Embedding dimension used throughout (production uses 384/1024; 4 suffices
#: to exercise every vec0 code path deterministically).
VEC_DIM: int = 4

#: Query vector for the KNN / score / orthogonality scenarios — points along
#: dimension 0 so cosine to any vector equals that vector's first component
#: when the rest is orthogonal.
QUERY_VEC: List[float] = [1.0, 0.0, 0.0, 0.0]

#: vec0 table name, built the same way production builds it
#: (``f"vec_user_memories_{dim}"`` at user_memories.py:1162).
VEC_TABLE: str = f"vec_user_memories_{VEC_DIM}"

#: The EXACT DDL production's ``SQLite3Provider.createVectorTable`` emits for
#: the user-memories columns (see sqlite3.py:604-630 — ``PARTITION KEY`` is
#: upper-cased and the cosine metric comes from the ``VectorDistanceMetric``
#: StrEnum whose value is ``"cosine"``). Mirrored verbatim so a vec0 change in
#: accepted column syntax is caught here.
CREATE_VEC_USER_MEMORIES: str = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS {VEC_TABLE} USING vec0(
    memory_id TEXT,
    chat_id INTEGER PARTITION KEY,
    user_id INTEGER PARTITION KEY,
    model TEXT PARTITION KEY,
    permanent INTEGER,
    embedding FLOAT[{VEC_DIM}] distance_metric=cosine
)
"""

#: Four vectors with distinct, unambiguous cosine similarity to ``QUERY_VEC``
#: (no ties), in non-ranked insertion order so the ordering test is meaningful.
#:   v0 [1.0, 0.0, 0.0, 0.0] -> cos 1.0 (dist 0.0)
#:   v1 [0.8, 0.6, 0.0, 0.0] -> cos 0.8 (dist ~0.2)
#:   v2 [0.6, 0.8, 0.0, 0.0] -> cos 0.6 (dist ~0.4)
#:   v3 [0.0, 1.0, 0.0, 0.0] -> cos 0.0 (dist 1.0)
ORDERING_ROWS: List[Tuple[str, List[float]]] = [
    ("memD", [0.0, 1.0, 0.0, 0.0]),
    ("memB", [0.8, 0.6, 0.0, 0.0]),
    ("memA", [1.0, 0.0, 0.0, 0.0]),
    ("memC", [0.6, 0.8, 0.0, 0.0]),
]
#: Expected KNN order (closest first) for ``QUERY_VEC``.
EXPECTED_ORDER: List[str] = ["memA", "memB", "memC", "memD"]


# ---------------------------------------------------------------------------
# Helpers — each test spins its OWN in-memory connection (self-contained, no
# shared state, mirrors the extension-load path in
# internal/database/providers/sqlite3.py:200,209).
# ---------------------------------------------------------------------------


def floats32(values: List[float]) -> bytes:
    """Serialize a float list to little-endian float32 bytes.

    Mirrors production's ``array.array("f", embedding).tobytes()`` used at
    ``user_memories.py:881,1161`` and ``chat_search.py:728``.

    Args:
        values: The float vector to serialize.

    Returns:
        The float32 (4 bytes per element) representation as ``bytes``.
    """
    return array.array("f", values).tobytes()


def cosineSimilarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors via numpy.

    Used as the independent oracle for the ``score = 1.0 - distance`` mapping
    pin.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        The cosine similarity in ``[-1.0, 1.0]`` as a Python float.
    """
    vecA = np.asarray(a, dtype=np.float32)
    vecB = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(vecA) * np.linalg.norm(vecB))
    if denom == 0.0:
        return 0.0
    return float((vecA @ vecB) / denom)


def loadVecConnection() -> sqlite3.Connection:
    """Create a fresh in-memory SQLite connection with sqlite-vec loaded.

    Mirrors the production load path
    (``enable_load_extension(True)`` -> ``load_extension(sqlite_vec.loadable_path())``
    -> ``enable_load_extension(False)``) from
    ``internal/database/providers/sqlite3.py:63-76,200,209``. Each test calls
    this so vec0 state never leaks between tests.

    Returns:
        An open ``sqlite3.Connection`` on ``:memory:`` with vec0 registered.

    Raises:
        RuntimeError: If the extension fails to load (re-raised with context so
            the suite fails loudly rather than silently skipping).
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.enable_load_extension(True)
        conn.load_extension(sqlite_vec.loadable_path())
        conn.enable_load_extension(False)
    except sqlite3.OperationalError as exc:
        conn.close()
        raise RuntimeError(f"sqlite-vec extension failed to load: {exc}") from exc
    return conn


def createVecUserMemoriesTable(conn: sqlite3.Connection) -> None:
    """Create the production-shaped vec0 user-memories table.

    Runs :data:`CREATE_VEC_USER_MEMORIES` verbatim.

    Args:
        conn: An open connection returned by :func:`loadVecConnection`.
    """
    conn.execute(CREATE_VEC_USER_MEMORIES)
    conn.commit()


def insertMemory(
    conn: sqlite3.Connection,
    memoryId: str,
    chatId: int,
    userId: int,
    model: str,
    permanent: int,
    embedding: List[float],
) -> None:
    """Insert one row into the vec0 user-memories table.

    Mirrors the production INSERT shape
    (``user_memories.py:1210-1222``).

    Args:
        conn: An open connection with the vec0 table created.
        memoryId: Memory identifier (TEXT).
        chatId: Chat id (INTEGER partition key).
        userId: User id (INTEGER partition key).
        model: Embedding-model name (TEXT partition key).
        permanent: Permanent flag 0/1 (INTEGER).
        embedding: Float vector of length :data:`VEC_DIM`.
    """
    conn.execute(
        f"INSERT INTO {VEC_TABLE} (memory_id, chat_id, user_id, model, permanent, embedding) "
        f"VALUES (?, ?, ?, ?, ?, ?)",
        (memoryId, chatId, userId, model, permanent, floats32(embedding)),
    )
    conn.commit()


def countMatching(
    conn: sqlite3.Connection,
    chatId: int,
    userId: int,
    memoryId: str,
) -> int:
    """Count vec0 rows matching the (chat_id, user_id, memory_id) metadata key.

    Args:
        conn: An open connection with the vec0 table created.
        chatId: Chat id.
        userId: User id.
        memoryId: Memory identifier.

    Returns:
        The number of matching rows.
    """
    row = conn.execute(
        f"SELECT count(*) FROM {VEC_TABLE} " f"WHERE chat_id = ? AND user_id = ? AND memory_id = ?",
        (chatId, userId, memoryId),
    ).fetchone()
    return int(row[0]) if row is not None else 0


# ---------------------------------------------------------------------------
# 1. Extension loads + vec0 table creates with the production schema.
# ---------------------------------------------------------------------------


class TestExtensionLoadAndTableCreate:
    """Pin that sqlite-vec loads and the production vec0 DDL is accepted.

    The extension is loaded from the pip package's bundled binary via
    ``sqlite_vec.loadable_path()`` (``sqlite3.py:200``). A bump that ships a
    broken binary, or a vec0 release that tightens accepted column syntax,
    fails here before any KNN/DELETE test runs.
    """

    def testExtensionLoadsAndReportsPinnedVersion(self) -> None:
        """The loaded extension reports the pinned sqlite-vec version string.

        ``SELECT vec_version()`` is the production capability probe
        (``sqlite3.py:67``). Under the pinned ``0.1.9`` it returns ``"v0.1.9"``.
        If a bump changes the version, this asserts and the operator must
        re-verify every other pin in this file.
        """
        conn = loadVecConnection()
        try:
            row = conn.execute("SELECT vec_version()").fetchone()
            assert row is not None
            assert row[0] == PINNED_VEC_VERSION
        finally:
            conn.close()

    def testLoadablePathResolves(self) -> None:
        """``sqlite_vec.loadable_path()`` resolves to a non-empty string.

        Production relies on this path existing
        (``sqlite3.py:200``); a wheel that mis-bundles the binary returns a
        path that fails to load.
        """
        path = sqlite_vec.loadable_path()
        assert isinstance(path, str)
        assert len(path) > 0

    def testVec0TableCreateSucceedsWithProductionSchema(self) -> None:
        """The exact production vec0 DDL for user memories is accepted.

        Runs :data:`CREATE_VEC_USER_MEMORIES` (the same column list, partition
        keys, and ``distance_metric=cosine`` that
        ``SQLite3Provider.createVectorTable`` emits) and asserts no error is
        raised and the table is registered in ``sqlite_master``.
        """
        conn = loadVecConnection()
        try:
            createVecUserMemoriesTable(conn)
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                (VEC_TABLE,),
            ).fetchall()
            assert rows == [(VEC_TABLE,)]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 2. KNN returns correct ordering (closest first).
# ---------------------------------------------------------------------------


class TestKnnOrdering:
    """Pin that a vec0 MATCH KNN query honours ``ORDER BY distance``.

    Production constructs ``SELECT ... WHERE embedding MATCH :q AND k = :k
    ORDER BY distance`` (``sqlite3.py:536,540``) and consumes the rows in
    returned order. This pins that vec0 HONOURS that ``ORDER BY`` on the
    ``distance`` pseudo-column and returns rows ascending by distance — not
    vec0's implicit (no-ORDER-BY) ordering, which production never relies on.
    A bump that stops honouring ``ORDER BY distance`` (e.g. returns rows in
    insertion order) would silently re-rank semantic-search results.
    """

    def testKnnReturnsClosestFirst(self) -> None:
        """Four distinct-cosine vectors come back in exact ascending-distance order.

        Inserts :data:`ORDERING_ROWS` (in non-ranked order) and queries with
        :data:`QUERY_VEC`, ``k = 10``. Asserts the returned ``memory_id``
        sequence equals :data:`EXPECTED_ORDER` (``memA`` cos 1.0 → ``memB``
        cos 0.8 → ``memC`` cos 0.6 → ``memD`` cos 0.0).
        """
        conn = loadVecConnection()
        try:
            createVecUserMemoriesTable(conn)
            for memoryId, embedding in ORDERING_ROWS:
                insertMemory(conn, memoryId, chatId=100, userId=1, model="m", permanent=0, embedding=embedding)

            rows = conn.execute(
                f"SELECT memory_id, distance FROM {VEC_TABLE} "
                f"WHERE embedding MATCH ? AND k = 10 AND chat_id = 100 ORDER BY distance",
                (floats32(QUERY_VEC),),
            ).fetchall()
            orderedIds = [r[0] for r in rows]
            assert orderedIds == EXPECTED_ORDER
        finally:
            conn.close()

    def testKnnRespectsPartitionKeyFilter(self) -> None:
        """The ``chat_id`` partition-key filter scopes the KNN scan.

        Inserts the same vectors under TWO different ``chat_id`` partitions and
        asserts a KNN restricted to one chat only returns that chat's rows.
        Production always carries ``chat_id = :chatId`` in the filter clause
        (``user_memories.py:912``, ``chat_search.py:733``).
        """
        conn = loadVecConnection()
        try:
            createVecUserMemoriesTable(conn)
            # Partition 100: the parallel vector (cos 1.0).
            insertMemory(conn, "a100", chatId=100, userId=1, model="m", permanent=0, embedding=[1.0, 0.0, 0.0, 0.0])
            # Partition 200: an orthogonal vector.
            insertMemory(conn, "b200", chatId=200, userId=1, model="m", permanent=0, embedding=[0.0, 1.0, 0.0, 0.0])

            rows = conn.execute(
                f"SELECT memory_id FROM {VEC_TABLE} "
                f"WHERE embedding MATCH ? AND k = 10 AND chat_id = 100 ORDER BY distance",
                (floats32(QUERY_VEC),),
            ).fetchall()
            assert rows == [("a100",)]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 3. score = 1.0 - distance mapping.
# ---------------------------------------------------------------------------


class TestScoreMapping:
    """Pin that ``1.0 - vec0_distance`` equals the numpy cosine similarity.

    Both production repositories map the vec0 ``distance`` column to a
    similarity score via ``1.0 - distance``
    (``user_memories.py:943``: ``scoreByMemoryId[mid] = 1.0 - vr["distance"]``;
    ``chat_search.py:785``: ``scoreByMessageId[mid.asStr()] = 1.0 - vr["distance"]``).
    vec0's cosine distance is defined as ``1.0 - cosine_similarity``; this pins
    that definition holds within float32 accumulation epsilon against an
    independent numpy computation.
    """

    def testScoreMatchesNumpyCosineWithinEpsilon(self) -> None:
        """``1.0 - distance`` equals numpy cosine similarity within ``1e-5``.

        Uses the ``[0.8, 0.6, 0.0, 0.0]`` vector whose cosine to ``QUERY_VEC``
        is exactly ``0.8`` (as float32: ``0.800000011920929``). Observed under
        0.1.9: vec0 distance = ``0.19999998807907104``, so
        ``1.0 - distance = 0.800000011920929`` matching numpy to within
        ``~3e-8``.
        """
        conn = loadVecConnection()
        try:
            createVecUserMemoriesTable(conn)
            candidate = [0.8, 0.6, 0.0, 0.0]
            insertMemory(conn, "mem", chatId=100, userId=1, model="m", permanent=0, embedding=candidate)

            row = conn.execute(
                f"SELECT distance FROM {VEC_TABLE} " f"WHERE embedding MATCH ? AND k = 1 AND chat_id = 100",
                (floats32(QUERY_VEC),),
            ).fetchone()
            assert row is not None
            vecDistance = float(row[0])
            productionScore = 1.0 - vecDistance
            expectedCosine = cosineSimilarity(QUERY_VEC, candidate)

            assert abs(productionScore - expectedCosine) < 1e-5
            # Explicit pinned literal (observed under 0.1.9): vec0's distance comes from a fixed native
            # C extension (deterministic per version), so the exact literal IS meaningful here — contrast
            # a pure-numpy cosine pipeline, where accumulation order is NOT deterministic and only
            # tolerance would be pinned.
            assert abs(productionScore - 0.800000011920929) < 1e-6
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 4. Orthogonal / parallel vector distance correctness.
# ---------------------------------------------------------------------------


class TestOrthogonalAndParallelVectors:
    """Pin vec0 cosine distance at the boundary cases.

    A vector parallel to the query must yield distance ≈ 0.0 (score ≈ 1.0);
    an orthogonal vector must yield distance ≈ 1.0 (score ≈ 0.0). These are
    the endpoints of the ``score = 1.0 - distance`` range that production
    clamps consumer expectations against.
    """

    def testParallelVectorHasDistanceZeroScoreOne(self) -> None:
        """A query-parallel vector yields distance ≈ 0.0 → score ≈ 1.0.

        Observed under 0.1.9: distance is exactly ``0.0``.
        """
        conn = loadVecConnection()
        try:
            createVecUserMemoriesTable(conn)
            insertMemory(conn, "parallel", chatId=100, userId=1, model="m", permanent=0, embedding=[1.0, 0.0, 0.0, 0.0])

            row = conn.execute(
                f"SELECT distance FROM {VEC_TABLE} " f"WHERE embedding MATCH ? AND k = 1 AND chat_id = 100",
                (floats32(QUERY_VEC),),
            ).fetchone()
            assert row is not None
            distance = float(row[0])
            assert abs(distance - 0.0) < 1e-6
            assert abs((1.0 - distance) - 1.0) < 1e-6
        finally:
            conn.close()

    def testOrthogonalVectorHasDistanceOneScoreZero(self) -> None:
        """A query-orthogonal vector yields distance ≈ 1.0 → score ≈ 0.0.

        Observed under 0.1.9: distance is exactly ``1.0``.
        """
        conn = loadVecConnection()
        try:
            createVecUserMemoriesTable(conn)
            insertMemory(
                conn, "orthogonal", chatId=100, userId=1, model="m", permanent=0, embedding=[0.0, 1.0, 0.0, 0.0]
            )

            row = conn.execute(
                f"SELECT distance FROM {VEC_TABLE} " f"WHERE embedding MATCH ? AND k = 1 AND chat_id = 100",
                (floats32(QUERY_VEC),),
            ).fetchone()
            assert row is not None
            distance = float(row[0])
            assert abs(distance - 1.0) < 1e-6
            assert abs((1.0 - distance) - 0.0) < 1e-6
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 5. DELETE-by-metadata: pin the CURRENT (0.1.9) raise-vs-succeed shape.
#    This is the high-value test for the production TODO.
# ---------------------------------------------------------------------------


class TestDeleteByMetadataShape:
    """Pin the CURRENT raise-vs-succeed shape of vec0 DELETE-by-metadata.

    Production (``internal/database/repositories/user_memories.py:1188-1208``)
    carries a LITERAL ``TODO: Test on latest sqlite-vec and leave only one
    way``. The code tries Shape A — a metadata-WHERE DELETE on
    ``chat_id``+``user_id``+``memory_id`` — and on exception falls back to
    Shape B — a ``rowid`` lookup SELECT followed by ``DELETE ... WHERE rowid``.
    The TODO exists because the authors already saw vec0 builds restrict WHERE
    predicates to partition keys only.

    FINDING under ``sqlite-vec 0.1.9``:

    - **Shape A SUCCEEDS.** A ``DELETE`` whose WHERE includes ``memory_id``
      (which is NOT a partition key — only ``chat_id``/``user_id``/``model``
      are) is accepted and deletes all matching rows. The fallback in
      production is therefore never exercised today.
    - **Shape B SUCCEEDS.** The ``SELECT rowid ... WHERE chat_id, user_id,
      memory_id`` lookup returns the rowid, and ``DELETE ... WHERE rowid``
      removes the row.

    These tests pin BOTH shapes as succeeding. If a version bump flips Shape A
    to raising (e.g. restricting DELETE WHERE to partition keys), this test
    fails and the production fallback becomes load-bearing — at which point the
    production TODO must be resolved before shipping the bump.
    """

    def testShapeAMetadataWhereDeleteSucceeds(self) -> None:
        """Shape A: ``DELETE ... WHERE chat_id, user_id, memory_id`` succeeds.

        Mirrors ``user_memories.py:1193-1197``. Inserts two rows sharing the
        same ``(chat_id, user_id, memory_id)`` metadata key and asserts the
        metadata DELETE removes BOTH (vec0 has no unique constraint on
        metadata columns, so duplicates are allowed and all match).

        Under 0.1.9: no exception raised, both rows deleted.
        """
        conn = loadVecConnection()
        try:
            createVecUserMemoriesTable(conn)
            insertMemory(conn, "mem2", chatId=100, userId=1, model="m", permanent=0, embedding=[0.9, 0.4, 0.0, 0.0])
            insertMemory(conn, "mem2", chatId=100, userId=1, model="m", permanent=0, embedding=[0.1, 0.1, 0.1, 0.1])
            assert countMatching(conn, chatId=100, userId=1, memoryId="mem2") == 2

            # Shape A — the metadata WHERE DELETE.
            conn.execute(
                f"DELETE FROM {VEC_TABLE} WHERE chat_id = ? AND user_id = ? AND memory_id = ?",
                (100, 1, "mem2"),
            )
            conn.commit()

            assert countMatching(conn, chatId=100, userId=1, memoryId="mem2") == 0
        finally:
            conn.close()

    def testShapeBRowidFallbackDeleteSucceeds(self) -> None:
        """Shape B: ``SELECT rowid ...`` then ``DELETE ... WHERE rowid`` succeeds.

        Mirrors ``user_memories.py:1199-1208``. Inserts one row, looks up its
        rowid via a metadata WHERE SELECT, then deletes by rowid.

        Under 0.1.9: rowid lookup returns a non-None rowid, the rowid DELETE
        succeeds, and the row is gone.
        """
        conn = loadVecConnection()
        try:
            createVecUserMemoriesTable(conn)
            insertMemory(conn, "mem3", chatId=100, userId=1, model="m", permanent=0, embedding=[0.6, 0.8, 0.0, 0.0])
            assert countMatching(conn, chatId=100, userId=1, memoryId="mem3") == 1

            # Shape B — the rowid fallback.
            row = conn.execute(
                f"SELECT rowid FROM {VEC_TABLE} WHERE chat_id = ? AND user_id = ? AND memory_id = ?",
                (100, 1, "mem3"),
            ).fetchone()
            assert row is not None
            rowid = int(row[0])

            conn.execute(f"DELETE FROM {VEC_TABLE} WHERE rowid = ?", (rowid,))
            conn.commit()

            assert countMatching(conn, chatId=100, userId=1, memoryId="mem3") == 0
        finally:
            conn.close()

    def testMetadataWhereSelectSucceeds(self) -> None:
        """The metadata WHERE SELECT (Shape B's lookup) succeeds and scopes.

        The rowid-fallback path depends on a ``SELECT rowid ... WHERE chat_id,
        user_id, memory_id`` returning the correct row. Under 0.1.9 this SELECT
        is accepted (``memory_id`` is usable in the WHERE even though it is not
        a partition key) and returns only the matching partition's row.
        """
        conn = loadVecConnection()
        try:
            createVecUserMemoriesTable(conn)
            insertMemory(conn, "mem1", chatId=100, userId=1, model="m", permanent=0, embedding=[1.0, 0.0, 0.0, 0.0])
            insertMemory(conn, "memX", chatId=200, userId=1, model="m", permanent=0, embedding=[0.0, 1.0, 0.0, 0.0])

            rows = conn.execute(
                f"SELECT rowid, memory_id FROM {VEC_TABLE} " f"WHERE chat_id = ? AND user_id = ? AND memory_id = ?",
                (100, 1, "mem1"),
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][1] == "mem1"
        finally:
            conn.close()

    def testNonPartitionColumnDeleteSucceeds(self) -> None:
        """A DELETE WHERE on a non-partition, non-key column also succeeds.

        ``permanent`` is an INTEGER metadata column that is NOT a partition key.
        Under 0.1.9 a ``DELETE WHERE permanent = ?`` is accepted and removes
        every matching row. This broadens the Shape A pin: 0.1.9 places no
        partition-key-only restriction on DELETE predicates at all, which is
        exactly the freedom the production TODO is nervous about losing.

        Removal/survival is verified via the partition-filtered
        :func:`countMatching` SELECT used everywhere else in this file — NOT via
        a full-scan ``SELECT count(*) FROM {VEC_TABLE}``, which is itself a
        version-sensitive vec0 capability unrelated to the DELETE under test and
        could fail for the wrong reason on a future build.
        """
        conn = loadVecConnection()
        try:
            createVecUserMemoriesTable(conn)
            insertMemory(conn, "p0a", chatId=100, userId=1, model="m", permanent=0, embedding=[1.0, 0.0, 0.0, 0.0])
            insertMemory(conn, "p0b", chatId=200, userId=2, model="m", permanent=0, embedding=[0.0, 1.0, 0.0, 0.0])
            insertMemory(conn, "p1", chatId=300, userId=3, model="m", permanent=1, embedding=[0.0, 0.0, 1.0, 0.0])

            conn.execute(f"DELETE FROM {VEC_TABLE} WHERE permanent = ?", (0,))
            conn.commit()

            # Verify via PARTITION-FILTERED counts keyed on (chat_id, user_id,
            # memory_id): both targeted rows gone, the permanent=1 survivor
            # remains. This routes the outcome through a query shape the rest of
            # the file already depends on rather than a full-scan vec0 count.
            assert countMatching(conn, chatId=100, userId=1, memoryId="p0a") == 0  # removed
            assert countMatching(conn, chatId=200, userId=2, memoryId="p0b") == 0  # removed
            assert countMatching(conn, chatId=300, userId=3, memoryId="p1") == 1  # permanent=1 survivor
        finally:
            conn.close()
