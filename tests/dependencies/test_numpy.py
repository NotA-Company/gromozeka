"""Dependency-usage regression tests pinning numpy's cosine-ranking contract.

Gromozeka's semantic-search ranking (chat history + user memories) is built on
hand-rolled numpy. The production code in
``internal/database/repositories/chat_search.py`` (the inline cosine-sim +
top-K block, lines ~403-424) does, in order:

    queryVec        = np.asarray(queryEmbedding, dtype=np.float32)
    candidateMatrix = np.asarray([…], dtype=np.float32)
    queryVecNorm    = np.linalg.norm(queryVec)
    queryNorm       = queryVec / (queryVecNorm or 1.0)
    rowNorms        = np.linalg.norm(candidateMatrix, axis=1, keepdims=True)
    rowNorms[rowNorms == 0.0] = 1.0          # zero-vector guard
    normalizedMatrix = candidateMatrix / rowNorms
    similarities     = normalizedMatrix @ queryNorm
    k                = min(int(topK), similarities.shape[0])
    topPartition     = np.argpartition(-similarities, k - 1)[:k]
    topPartition     = topPartition[np.argsort(-similarities[topPartition])]

That block is **inline inside the larger ``semanticSearch`` method** — it is NOT
a discrete callable, so it cannot be driven through its own wrapper without
spinning up a DB-backed repository. To still lock the numpy contract (and avoid
DB coupling), these tests replicate the EXACT algorithm above in
``computeSimilarities`` / ``selectTopK`` and run it against FIXED inputs.

Why this matters — two version-sensitive risks a numpy bump carries:

1. **``np.argpartition``/``np.argsort`` tie-breaking is unspecified.** When two
   rows have identical cosine similarity, numpy does not guarantee which id wins;
   the observed order under numpy 2.5.1 is pinned in ``TestCosineTieOrder``. A
   bump that reorders ties would silently change which message wins semantic
   search, so we fail loudly instead.
2. **float32 promotion semantics.** If a bump silently promotes the similarity
   array to float64, accumulation changes and tie-breaking can shift. The
   ``TestFloat32Dtype`` class pins ``dtype == np.float32`` end-to-end; that
   dtype assertion is the authoritative signal. Intra-float32 accumulation
   order is explicitly NOT pinned (it is not a contract production relies on),
   so value assertions are checked to tolerance, not to float32 round-trip
   literals. ``TestNormCorrectness`` and the high-dimensional case add a
   realistic-width (768-dim) stress of the float32 accumulation path.

Methodology: the algorithm was run first to OBSERVE the current output under
numpy 2.5.1, then the assertions below pin that observed reality. They do NOT
assert what numpy "should" do.
"""

import importlib.metadata
from typing import List, Tuple

import numpy as np

#: Pinned ``numpy`` distribution version these assertions were observed against.
#: A bump that changes ranking, tie-breaking, or dtype semantics must be
#: re-verified against every pin in this file before shipping.
PINNED_VERSION: str = "2.5.1"

# ---------------------------------------------------------------------------
# Faithful replica of the production inline block
# (internal/database/repositories/chat_search.py, lines ~403-424).
# Keep this in lock-step with the source; if the source refactors, update here.
# ---------------------------------------------------------------------------


def computeSimilarities(
    embeddingList: List[List[float]],
    queryEmbedding: List[float],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Replicate the production cosine-similarity computation.

    Mirrors the source's numpy calls exactly: float32 cast, per-row norm with
    the ``rowNorms == 0.0 -> 1.0`` zero-vector guard, then matrix-vector dot
    product. The divisor uses ``(queryVecNorm or 1.0)`` so a degenerate query
    cannot divide by zero.

    Note: production also has an ``if queryVecNorm < 1e-8: logger.warning(...)``
    block. That branch is log-only and has NO computational effect (the divisor
    guard above only substitutes ``1.0`` at exactly ``0.0``), so the replica
    omits it rather than carrying a dead no-op.

    Args:
        embeddingList: Candidate embedding rows (one row per candidate).
        queryEmbedding: The query embedding vector.

    Returns:
        A tuple ``(queryNorm, normalizedMatrix, similarities)`` where
        ``similarities[i]`` is the cosine similarity of candidate ``i`` to the
        query. All arrays are ``np.float32``.
    """
    queryVec = np.asarray(queryEmbedding, dtype=np.float32)
    candidateMatrix = np.asarray(embeddingList, dtype=np.float32)
    queryVecNorm = np.linalg.norm(queryVec)
    queryNorm = queryVec / (queryVecNorm or 1.0)
    rowNorms = np.linalg.norm(candidateMatrix, axis=1, keepdims=True)
    rowNorms[rowNorms == 0.0] = 1.0  # avoid div-by-zero for zero-vectors
    normalizedMatrix = candidateMatrix / rowNorms
    similarities = normalizedMatrix @ queryNorm
    return queryNorm, normalizedMatrix, similarities


def selectTopK(similarities: np.ndarray, topK: int) -> Tuple[np.ndarray, List[float]]:
    """Replicate the production argpartition + argsort top-K selection.

    Args:
        similarities: 1-D cosine-similarity array (one score per candidate).
        topK: Maximum number of top results to return.

    Returns:
        A tuple ``(topPartition, topScores)`` where ``topPartition`` is the
        array of candidate indices ordered by similarity descending (ties in
        whatever order numpy yields), and ``topScores`` is the parallel list of
        scores as Python floats.
    """
    k = min(int(topK), similarities.shape[0])
    topPartition = np.argpartition(-similarities, k - 1)[:k] if k > 0 else np.array([], dtype=np.int64)
    topPartition = topPartition[np.argsort(-similarities[topPartition])]
    topScores = [float(similarities[int(i)]) for i in topPartition]
    return topPartition, topScores


# ---------------------------------------------------------------------------
# Test inputs (FIXED).
# ---------------------------------------------------------------------------

#: Query vector used across the tie and dtype scenarios — points along dim 0.
QUERY_VEC: List[float] = [1.0, 0.0, 0.0, 0.0]

#: Interleaved candidate matrix with TWO deliberate ties:
#:   - ids 200 and 300 both hit cosine 1.0 (rows are parallel to the query),
#:   - ids 100, 400, 500 all hit cosine 0.0 (orthogonal or the zero row),
#: and the tied indices are NOT contiguous, so the tie-break order is
#: non-trivial. The zero row (id 400) exercises the zero-vector guard.
TIES_MATRIX: List[List[float]] = [
    [0.0, 2.0, 0.0, 0.0],  # id 100 -> cos 0.0
    [4.0, 0.0, 0.0, 0.0],  # id 200 -> cos 1.0
    [1.0, 0.0, 0.0, 0.0],  # id 300 -> cos 1.0  (TIE with id 200)
    [0.0, 0.0, 0.0, 0.0],  # id 400 -> zero vector -> cos 0.0  (TIE group)
    [0.0, 0.0, 1.0, 0.0],  # id 500 -> cos 0.0  (TIE group)
]
TIES_IDS: List[int] = [100, 200, 300, 400, 500]

#: Candidate matrix with an unambiguous ranking (no ties).
CLEAR_MATRIX: List[List[float]] = [
    [1.0, 0.0, 0.0, 0.0],  # id 10 -> cos 1.0
    [0.8, 0.6, 0.0, 0.0],  # id 20 -> cos 0.8
    [0.0, 1.0, 0.0, 0.0],  # id 30 -> cos 0.0
    [0.6, 0.0, 0.8, 0.0],  # id 40 -> cos 0.6
]
CLEAR_IDS: List[int] = [10, 20, 30, 40]

#: Candidate matrix including an ANTI-CORRELATED row (id 33, cosine -1.0).
#: Production's ``argpartition(-similarities)`` / ``argsort(-similarities)``
#: paths interact with negative scores (realistic for anti-correlated
#: embeddings), and the negation behaves differently around the zero-vector
#: guard, so this exercises a region the other matrices never reach. The
#: ranking is unambiguous (distinct cosines), so the observed order is pinned.
ANTI_MATRIX: List[List[float]] = [
    [1.0, 0.0, 0.0, 0.0],  # id 11 -> cos 1.0
    [0.8, 0.6, 0.0, 0.0],  # id 22 -> cos 0.8
    [-1.0, 0.0, 0.0, 0.0],  # id 33 -> cos -1.0  (anti-correlated)
    [0.0, 1.0, 0.0, 0.0],  # id 44 -> cos 0.0
]
ANTI_IDS: List[int] = [11, 22, 33, 44]

#: Seeded high-dimensional candidate matrix and query (64 rows, 768 dims — a
#: typical embedding width). float32 accumulation error (the core of the
#: precision contract) only materialises at realistic widths; the tiny 4-dim
#: matrices above cannot exercise it. Built deterministically from a fixed
#: seed via ``np.random.default_rng(0)``: generated as float64 then cast to
#: float32 (``default_rng().random`` has no dtype kwarg).
_HIGH_DIM_RNG: np.random.Generator = np.random.default_rng(0)
HIGH_DIM_MATRIX: np.ndarray = _HIGH_DIM_RNG.random((64, 768)).astype(np.float32)
HIGH_DIM_QUERY: np.ndarray = _HIGH_DIM_RNG.random(768).astype(np.float32)


# ---------------------------------------------------------------------------
# 0. Pinned distribution version.
# ---------------------------------------------------------------------------


class TestPinnedVersion:
    """Force a conscious re-verification pass on any ``numpy`` bump.

    The whole point of this suite is that a dependency bump which silently
    changes behaviour fails loudly. A docstring version string can rot without
    a failing test; this assertion compares the ACTUAL installed distribution
    version against :data:`PINNED_VERSION` so a bump fails on a real assertion.
    When it fails, re-verify every other pin in this file against the new
    version before updating the constant.
    """

    def testPinnedVersion(self) -> None:
        """The installed ``numpy`` distribution matches :data:`PINNED_VERSION`.

        Args:
            None (self).

        Returns:
            None. Asserts the installed distribution version string.
        """
        assert importlib.metadata.version("numpy") == PINNED_VERSION


# ---------------------------------------------------------------------------
# 1. Deliberate ties -> exact ordered id list (the load-bearing test).
# ---------------------------------------------------------------------------


class TestCosineTieOrder:
    """Pin the EXACT tie-break order numpy 2.5.1 yields on a fixed matrix.

    numpy does NOT specify the tie-breaking order of ``np.argpartition`` or
    ``np.argsort`` (``argsort`` defaults to quicksort, which is unstable). When
    multiple candidates share an identical cosine similarity, which id "wins" is
    an implementation detail of numpy. These tests pin the order OBSERVED under
    numpy 2.5.1 so a version bump that silently reorders ties fails this suite
    instead of silently reordering semantic-search results in production.
    """

    def testFullOrderPinsObservedTieOrder(self) -> None:
        """Top-K=all must return the exact observed id sequence.

        Observed under numpy 2.5.1:
            ids    [200, 300, 100, 400, 500]
            scores [1.0, 1.0, 0.0, 0.0, 0.0]
        The two 1.0-tied ids come out as [200, 300] (ascending row index), and
        the three 0.0-tied ids as [100, 400, 500] (ascending row index). If a
        numpy bump reorders either tied group, this assertion fails.
        """
        _, _, similarities = computeSimilarities(TIES_MATRIX, QUERY_VEC)
        topPartition, topScores = selectTopK(similarities, topK=len(TIES_IDS))

        orderedIds = [TIES_IDS[int(i)] for i in topPartition]
        assert orderedIds == [200, 300, 100, 400, 500]
        assert topScores == [1.0, 1.0, 0.0, 0.0, 0.0]

    def testTopKTwoReturnsOnlyTheTiedWinners(self) -> None:
        """Top-K=2 returns exactly the two tied 1.0 ids in observed order.

        Observed: [200, 300]. This pins that argpartition's partial selection of
        the tied top group keeps row-index order [1, 2].
        """
        _, _, similarities = computeSimilarities(TIES_MATRIX, QUERY_VEC)
        topPartition, topScores = selectTopK(similarities, topK=2)

        orderedIds = [TIES_IDS[int(i)] for i in topPartition]
        assert orderedIds == [200, 300]
        assert topScores == [1.0, 1.0]


# ---------------------------------------------------------------------------
# 2. Zero-vector guard fires.
# ---------------------------------------------------------------------------


class TestZeroVectorGuard:
    """Pin the behaviour of the ``rowNorms[rowNorms == 0.0] = 1.0`` guard.

    Without the guard, a zero row would compute ``0 / 0 -> NaN`` and poison the
    similarity array (``NaN @ queryNorm -> NaN``). The production guard replaces
    a zero row norm with 1.0, yielding a deterministic zero similarity. These
    tests pin that the guard produces ``0.0`` (finite) and that no NaN leaks
    anywhere into the similarities.
    """

    def testZeroRowProducesZeroNotNan(self) -> None:
        """The zero row (id 400, index 3) must yield exactly 0.0 similarity.

        Args: (none — uses module-level ``TIES_MATRIX`` / ``QUERY_VEC``)
        """
        _, _, similarities = computeSimilarities(TIES_MATRIX, QUERY_VEC)

        zeroRowIndex = TIES_IDS.index(400)
        assert similarities[zeroRowIndex] == 0.0
        assert np.isfinite(similarities[zeroRowIndex])

    def testNoNanAnywhereAcrossSimilarities(self) -> None:
        """The whole similarity array must be free of NaN despite the zero row."""
        _, _, similarities = computeSimilarities(TIES_MATRIX, QUERY_VEC)

        assert not bool(np.isnan(similarities).any())

    def testGuardIsLoadBearing(self) -> None:
        """Without the guard the zero row would be NaN, proving the guard matters.

        Replicates the same computation but SKIPS the
        ``rowNorms[rowNorms == 0.0] = 1.0`` line, then asserts the zero row
        becomes NaN. This documents why the guard exists; the guarded path is
        covered by the two tests above.
        """
        queryVec = np.asarray(QUERY_VEC, dtype=np.float32)
        candidateMatrix = np.asarray(TIES_MATRIX, dtype=np.float32)
        queryVecNorm = np.linalg.norm(queryVec)
        queryNorm = queryVec / (queryVecNorm or 1.0)
        rowNorms = np.linalg.norm(candidateMatrix, axis=1, keepdims=True)
        # NOTE: guard intentionally omitted here. The divide emits a RuntimeWarning
        # ("invalid value encountered in divide") — that is the whole point: a
        # 0/0 produces NaN. Suppress it so the run stays clean.
        with np.errstate(invalid="ignore", divide="ignore"):
            unguardedSimilarities = (candidateMatrix / rowNorms) @ queryNorm

        zeroRowIndex = TIES_IDS.index(400)
        assert bool(np.isnan(unguardedSimilarities[zeroRowIndex]))


# ---------------------------------------------------------------------------
# 3. float32 dtype preserved end-to-end.
# ---------------------------------------------------------------------------


class TestFloat32Dtype:
    """Pin that the similarity pipeline stays ``np.float32`` throughout.

    A numpy bump that silently promotes any stage to float64 would change
    accumulation order and could shift tie-breaking. These tests pin
    ``dtype == np.float32`` on the query-normalised vector, the row-normalised
    matrix, and the final similarity array.
    """

    def testSimilaritiesAreFloat32(self) -> None:
        """The final similarity array dtype is exactly ``np.float32``."""
        _, _, similarities = computeSimilarities(TIES_MATRIX, QUERY_VEC)

        assert similarities.dtype == np.float32

    def testQueryNormAndNormalizedMatrixAreFloat32(self) -> None:
        """The intermediate normalised query vector and matrix are float32.

        Args: (none — uses module-level ``TIES_MATRIX`` / ``QUERY_VEC``)
        """
        queryNorm, normalizedMatrix, _ = computeSimilarities(TIES_MATRIX, QUERY_VEC)

        assert queryNorm.dtype == np.float32
        assert normalizedMatrix.dtype == np.float32

    def testScoresAreFloat32Derived(self) -> None:
        """Top scores match the expected cosines, checked to tolerance.

        The dtype-promotion signal is owned authoritatively by
        ``testSimilaritiesAreFloat32`` (which fails on ANY float64 promotion).
        Here we only assert the ranking VALUES are the expected cosines
        (1.0, 0.8, 0.6) within tolerance. Exact float32 round-trip literals
        (e.g. ``0.8 -> 0.800000011920929``) are deliberately NOT pinned: a
        numpy/BLAS bump that changes intra-float32 summation order WITHOUT
        promoting dtype would trip an exact literal on identical production
        rankings — a false alarm, since accumulation order is not a contract
        we rely on. The tolerance (1e-6) is far looser than float32 epsilon
        (~1.2e-7) but tight enough to catch any real ranking drift.
        """
        _, _, similarities = computeSimilarities(CLEAR_MATRIX, QUERY_VEC)
        _, topScores = selectTopK(similarities, topK=3)

        # 1.0 is exactly representable and arises from a single non-zero term
        # (no accumulation), so it stays exact.
        assert topScores[0] == 1.0
        # 0.8 / 0.6 each involve float32 norm accumulation, hence tolerance.
        assert abs(topScores[1] - 0.8) < 1e-6
        assert abs(topScores[2] - 0.6) < 1e-6

    def testHighDimSimilaritiesStayFloat32(self) -> None:
        """dtype stays float32 at realistic embedding width (768 dims).

        The 4-dim matrices cannot surface float32 accumulation error (the core
        of the precision contract); a 64x768 seeded matrix can. This is a
        stronger regression catch for a silent promotion at production scale.

        Args: (none — uses module-level ``HIGH_DIM_MATRIX`` / ``HIGH_DIM_QUERY``)
        """
        queryNorm, normalizedMatrix, similarities = computeSimilarities(
            HIGH_DIM_MATRIX.tolist(), HIGH_DIM_QUERY.tolist()
        )

        assert queryNorm.dtype == np.float32
        assert normalizedMatrix.dtype == np.float32
        assert similarities.dtype == np.float32


# ---------------------------------------------------------------------------
# 4. Top-K correctness on a clear case (no ties).
# ---------------------------------------------------------------------------


class TestTopKNoTies:
    """Pin top-K selection when the ranking is unambiguous (no ties)."""

    def testTopKThreeReturnsIdsInDescendingOrder(self) -> None:
        """Top-K=3 returns ids [10, 20, 40] (cosines 1.0, 0.8, 0.6).

        Args: (none — uses module-level ``CLEAR_MATRIX`` / ``QUERY_VEC``)
        """
        _, _, similarities = computeSimilarities(CLEAR_MATRIX, QUERY_VEC)
        topPartition, _ = selectTopK(similarities, topK=3)

        orderedIds = [CLEAR_IDS[int(i)] for i in topPartition]
        assert orderedIds == [10, 20, 40]

    def testScoresAreStrictlyDescending(self) -> None:
        """The selected scores are strictly monotonically descending."""
        _, _, similarities = computeSimilarities(CLEAR_MATRIX, QUERY_VEC)
        _, topScores = selectTopK(similarities, topK=3)

        assert topScores[0] > topScores[1] > topScores[2]

    def testTopKExceedingCountReturnsAllInOrder(self) -> None:
        """Top-K larger than the candidate count returns all, ranked.

        Args: (none — uses module-level ``CLEAR_MATRIX`` / ``QUERY_VEC``)
        """
        _, _, similarities = computeSimilarities(CLEAR_MATRIX, QUERY_VEC)
        topPartition, _ = selectTopK(similarities, topK=999)

        orderedIds = [CLEAR_IDS[int(i)] for i in topPartition]
        assert orderedIds == [10, 20, 40, 30]


# ---------------------------------------------------------------------------
# 5. Negative-cosine (anti-correlated) ranking.
# ---------------------------------------------------------------------------


class TestNegativeCosine:
    """Pin ranking behaviour when a candidate is anti-correlated (cosine < 0).

    The other matrices only ever produce scores in ``[0.0, 1.0]``. Production's
    ``np.argpartition(-similarities)`` / ``np.argsort(-similarities)`` paths
    also interact with negative scores (realistic for anti-correlated
    embeddings), and the negation behaves differently around the zero-vector /
    NaN guard. These tests pin the observed order on a matrix containing one
    anti-correlated row.
    """

    def testAntiCorrelatedRowRanksLast(self) -> None:
        """The -1.0 cosine row (id 33) must rank last (lowest similarity).

        Observed under numpy 2.5.1 on ``ANTI_MATRIX`` with ``QUERY_VEC``:
            ids    [11, 22, 44, 33]
            scores [1.0, 0.8, 0.0, -1.0]
        The ranking is unambiguous (distinct cosines), so this pins that the
        ``-similarities`` negation places the negative score correctly below 0.0
        rather than, say, treating it as NaN or flipping sign incorrectly.

        Args: (none — uses module-level ``ANTI_MATRIX`` / ``QUERY_VEC``)
        """
        _, _, similarities = computeSimilarities(ANTI_MATRIX, QUERY_VEC)
        topPartition, topScores = selectTopK(similarities, topK=len(ANTI_IDS))

        orderedIds = [ANTI_IDS[int(i)] for i in topPartition]
        assert orderedIds == [11, 22, 44, 33]
        # Exact where representable (single-term / orthogonal): 1.0, 0.0, -1.0.
        # The 0.8 score involves float32 norm accumulation -> tolerance, not a
        # round-trip literal (same rationale as testScoresAreFloat32Derived).
        assert topScores[0] == 1.0
        assert abs(topScores[1] - 0.8) < 1e-6
        assert topScores[2] == 0.0
        assert topScores[3] == -1.0

    def testNoNanOrInfDespiteNegativeScore(self) -> None:
        """The whole similarity array stays finite with a negative cosine.

        Args: (none — uses module-level ``ANTI_MATRIX`` / ``QUERY_VEC``)
        """
        _, _, similarities = computeSimilarities(ANTI_MATRIX, QUERY_VEC)

        assert bool(np.isfinite(similarities).all())


# ---------------------------------------------------------------------------
# 6. Empty-candidate branch of ``selectTopK``.
# ---------------------------------------------------------------------------


class TestEmptyCandidates:
    """Pin the ``k == 0`` empty-candidate branch of ``selectTopK``.

    ``selectTopK`` mirrors production's
    ``np.argpartition(...) if k > 0 else np.array([], dtype=np.int64)``
    fallback (chat_search.py:420). That branch is reached when there are zero
    candidates. These tests pin it returns cleanly without crashing.
    """

    def testTopKZeroOverEmptyReturnsEmpty(self) -> None:
        """``topK=0`` on an empty similarity array returns ``([], [])``.

        Args: (none)
        """
        empty = np.array([], dtype=np.float32)
        topPartition, topScores = selectTopK(empty, topK=0)

        assert topPartition.tolist() == []
        assert topScores == []

    def testTopKLargerThanEmptyReturnsEmpty(self) -> None:
        """``topK`` exceeding the (zero) candidate count also returns empty.

        Exercises ``k = min(topK, 0) == 0`` then the ``else`` empty branch.

        Args: (none)
        """
        empty = np.array([], dtype=np.float32)
        topPartition, topScores = selectTopK(empty, topK=5)

        assert topPartition.tolist() == []
        assert topScores == []


# ---------------------------------------------------------------------------
# 7. Norm computation correctness.
# ---------------------------------------------------------------------------


class TestNormCorrectness:
    """Pin ``np.linalg.norm`` results on known vectors.

    A sanity pin: the cosine pipeline leans on ``np.linalg.norm`` twice (query
    and per-row). If a bump changed norm semantics or return dtype, the
    downstream ranking would drift.
    """

    def testKnownPythagoreanNorm(self) -> None:
        """``norm([3, 4]) == 5.0`` for a float32 input."""
        vec = np.asarray([3.0, 4.0], dtype=np.float32)

        assert np.linalg.norm(vec) == 5.0

    def testNormOfFloat32InputIsFloat32(self) -> None:
        """A float32 input yields a float32 scalar norm (no promotion)."""
        vec = np.asarray([3.0, 4.0], dtype=np.float32)
        norm = np.linalg.norm(vec)

        assert np.asarray(norm).dtype == np.float32

    def testPerRowNormMatchesExpected(self) -> None:
        """Per-row norms of the ties matrix match hand-computed values.

        Row norms of ``TIES_MATRIX``: sqrt(4)=2, sqrt(16)=4, sqrt(1)=1,
        0 (zero row), sqrt(1)=1.
        """
        candidateMatrix = np.asarray(TIES_MATRIX, dtype=np.float32)
        rowNorms = np.linalg.norm(candidateMatrix, axis=1)

        assert rowNorms.tolist() == [2.0, 4.0, 1.0, 0.0, 1.0]

    def testHighDimNormsAreFiniteAndFloat32(self) -> None:
        """Per-row norms of a 768-dim seeded matrix are finite and float32.

        At realistic embedding width, float32 accumulation error in the norm
        could in principle overflow to inf for adversarial inputs; this pins
        that a normal seeded matrix yields finite norms with no dtype
        promotion.

        Args: (none — uses module-level ``HIGH_DIM_MATRIX`` / ``HIGH_DIM_QUERY``)
        """
        rowNorms = np.linalg.norm(HIGH_DIM_MATRIX, axis=1)
        queryNormScalar = np.linalg.norm(HIGH_DIM_QUERY)

        assert rowNorms.dtype == np.float32
        assert bool(np.isfinite(rowNorms).all())
        assert bool(np.isfinite(queryNormScalar))
