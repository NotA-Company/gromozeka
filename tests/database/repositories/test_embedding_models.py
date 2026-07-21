"""Tests for :class:`EmbeddingModelsRepository`.

Coverage of the ``models`` embedding-provenance lookup table
(introduced by the embedding-model-lookup refactor — see
``docs/plans/embedding-model-lookup-refactor-v1.md`` §8.1).

Exercises the cache, the app-side id allocation, the probe-then-insert
idempotency (the runtime analogue of migration R6), and the read-side
helpers (``getModelById`` / ``listModels``). Uses the shared
``testDatabase`` fixture from ``tests/conftest.py`` so each test gets
a fresh in-memory SQLite database with all current migrations applied
— no mocks of the provider layer.
"""

import datetime
from unittest.mock import AsyncMock, patch

from internal.database import Database
from internal.database.manager import DatabaseManager


class TestEmbeddingModelsRepository:
    """End-to-end coverage of :class:`EmbeddingModelsRepository`.

    Every test goes through the real SQLite provider against an
    in-memory ``models`` table — no provider mocking — so the
    portability-critical SQL (the ``upsert(..., updateExpressions={})``
    DO-NOTHING pattern and the probe-then-SELECT-back) is exercised
    end-to-end.
    """

    @staticmethod
    async def _insertModelDirectly(
        db: Database,
        *,
        modelId: int,
        model: str,
        dimensions: int,
        createdAt: datetime.datetime,
    ) -> None:
        """Insert a row into ``models`` bypassing the repository.

        Used to set up preconditions (existing rows, race scenarios)
        without exercising the code under test.

        Args:
            db: Database with the ``models`` table.
            modelId: ``model_id`` primary key to insert.
            model: Model name.
            dimensions: Vector dimensionality.
            createdAt: Row creation timestamp.

        Returns:
            None.
        """
        sqlProvider = await db.manager.getProvider(readonly=False)
        await sqlProvider.execute(
            "INSERT INTO models (model_id, model, dimensions, created_at) "
            "VALUES (:modelId, :model, :dimensions, :createdAt)",
            {
                "modelId": modelId,
                "model": model,
                "dimensions": dimensions,
                "createdAt": createdAt,
            },
        )

    async def test_getOrCreateModelId_creates_new_entry(self, testDatabase: Database) -> None:
        """First call on an empty table creates a row with ``model_id=1`` and returns 1."""
        firstId = await testDatabase.embeddingModels.getOrCreateModelId("alpha", 384)

        assert firstId == 1

        # Row was actually persisted — read it back via the public read API.
        row = await testDatabase.embeddingModels.getModelById(firstId)
        assert row is not None
        assert row["model"] == "alpha"
        assert row["dimensions"] == 384

    async def test_getOrCreateModelId_returns_existing(self, testDatabase: Database) -> None:
        """Pre-existing row: call returns the canonical id, no new row created."""
        await self._insertModelDirectly(
            testDatabase,
            modelId=5,
            model="preexisting",
            dimensions=768,
            createdAt=datetime.datetime.now(datetime.timezone.utc),
        )

        returnedId = await testDatabase.embeddingModels.getOrCreateModelId("preexisting", 768)

        # Returns the pre-existing id (5), not a freshly-allocated one.
        assert returnedId == 5

        # No new row was added — the table still has exactly one entry.
        allRows = await testDatabase.embeddingModels.listModels()
        assert len(allRows) == 1
        assert allRows[0]["model_id"] == 5

    async def test_getOrCreateModelId_caches_result(self, testDatabase: Database) -> None:
        """Second call for the same (model, dims) returns the cached id without touching the DB.

        A cache hit must short-circuit before ``manager.getProvider`` is
        ever called — we assert that by patching ``getProvider`` at the
        ``DatabaseManager`` class level to a strict mock that raises if
        awaited. ``DatabaseManager`` declares ``__slots__``, so the
        patch must target the class, not the instance.
        """
        repo = testDatabase.embeddingModels

        # First call: cache miss → allocates id, populates the cache, returns.
        firstId = await repo.getOrCreateModelId("cached_model", 384)
        assert firstId == 1

        # Sanity-check the cache dict was actually populated. This is the
        # load-bearing state for the next assertion.
        assert ("cached_model", 384) in repo._cache
        assert repo._cache[("cached_model", 384)] == firstId

        # Second call: cache hit. Patch getProvider on the class to a
        # strict mock — a cache hit returns before ever acquiring a
        # provider, so the mock must not be awaited.
        strictProvider = AsyncMock()
        strictProvider.side_effect = AssertionError("cache hit must not acquire a provider")
        with patch.object(type(testDatabase.manager), "getProvider", strictProvider):
            secondId = await repo.getOrCreateModelId("cached_model", 384)

        assert secondId == firstId
        strictProvider.assert_not_called()

    async def test_getOrCreateModelId_distinct_models_get_distinct_ids(self, testDatabase: Database) -> None:
        """Two different model names get distinct sequential ids."""
        firstId = await testDatabase.embeddingModels.getOrCreateModelId("model_a", 384)
        secondId = await testDatabase.embeddingModels.getOrCreateModelId("model_b", 384)

        assert firstId == 1
        assert secondId == 2
        assert firstId != secondId

    async def test_getOrCreateModelId_same_model_different_dimensions(self, testDatabase: Database) -> None:
        """Same model name at different dimensionalities gets distinct ids.

        The UNIQUE constraint is on ``(model, dimensions)``, so a model
        configured at two dimensionalities occupies two rows (mirrors
        today's behaviour where a 384-dim variant and a 1024-dim variant
        of the same name are distinct embedding configurations).
        """
        lowDim = await testDatabase.embeddingModels.getOrCreateModelId("multidim", 384)
        highDim = await testDatabase.embeddingModels.getOrCreateModelId("multidim", 1024)

        assert lowDim == 1
        assert highDim == 2
        assert lowDim != highDim

        # Both rows exist with the same ``model`` value.
        allRows = await testDatabase.embeddingModels.listModels()
        assert len(allRows) == 2
        modelNames = {r["model"] for r in allRows}
        assert modelNames == {"multidim"}

    async def test_getOrCreateModelId_idempotent_under_concurrent_inserts(self, testDatabase: Database) -> None:
        """A row that sneaks in between MAX and upsert does not cause a duplicate id.

        Simulates the race that R6 calls out for the migration backfill:
        the MAX query computes ``nextId``, but a row with the same
        ``(model, dimensions)`` is inserted before our upsert lands. The
        upsert's DO-NOTHING-on-conflict path swallows the collision, the
        SELECT-back returns the canonical id of the row that won the
        race, and the caller never observes a duplicate or an
        ``IntegrityError``.
        """
        # Pre-insert as if a concurrent writer had won the race.
        await self._insertModelDirectly(
            testDatabase,
            modelId=1,
            model="race_model",
            dimensions=256,
            createdAt=datetime.datetime.now(datetime.timezone.utc),
        )

        # Cold-cache call: the cache is empty, so the code takes the
        # MAX → upsert → SELECT-back path. The MAX returns 2, the upsert
        # attempts id=2 but collides on (model, dimensions) and is
        # short-circuited (DO NOTHING), and the SELECT-back returns 1.
        returnedId = await testDatabase.embeddingModels.getOrCreateModelId("race_model", 256)

        assert returnedId == 1, "must return the pre-existing id, not allocate a new one"

        # Exactly one row — the pre-existing one. The wasted MAX-based
        # id (2) was never persisted.
        allRows = await testDatabase.embeddingModels.listModels()
        assert len(allRows) == 1
        assert allRows[0]["model_id"] == 1

    async def test_getModelById_returns_typed_dict(self, testDatabase: Database) -> None:
        """getModelById returns a :class:`ModelDict` with all four fields populated."""
        ts = datetime.datetime.now(datetime.timezone.utc)
        await self._insertModelDirectly(
            testDatabase,
            modelId=7,
            model="shape_test",
            dimensions=512,
            createdAt=ts,
        )

        row = await testDatabase.embeddingModels.getModelById(7)

        assert row is not None
        # All four declared fields are present with the declared types.
        # ``sqlToTypedDict`` is responsible for the SQLite → Python
        # conversion (in particular ``created_at`` from a TEXT column to
        # ``datetime.datetime``); this test pins that contract.
        assert isinstance(row["model_id"], int)
        assert row["model_id"] == 7
        assert isinstance(row["model"], str)
        assert row["model"] == "shape_test"
        assert isinstance(row["dimensions"], int)
        assert row["dimensions"] == 512
        assert isinstance(row["created_at"], datetime.datetime)
        # Round-trip preserves the value (sub-second precision included).
        assert row["created_at"] == ts

    async def test_getModelById_returns_none_for_missing(self, testDatabase: Database) -> None:
        """Fetching an id that was never inserted returns ``None``."""
        row = await testDatabase.embeddingModels.getModelById(9999)
        assert row is None

    async def test_listModels_returns_ordered(self, testDatabase: Database) -> None:
        """listModels returns rows ordered by ``model_id`` regardless of insertion order."""
        now = datetime.datetime.now(datetime.timezone.utc)
        # Insert out of order: 3, then 1, then 2.
        for mid in (3, 1, 2):
            await self._insertModelDirectly(
                testDatabase,
                modelId=mid,
                model=f"m{mid}",
                dimensions=384,
                createdAt=now,
            )

        rows = await testDatabase.embeddingModels.listModels()

        assert len(rows) == 3
        assert [r["model_id"] for r in rows] == [1, 2, 3]
        # Each row matches the TypedDict shape.
        for r in rows:
            assert isinstance(r["model"], str)
            assert isinstance(r["dimensions"], int)
            assert isinstance(r["created_at"], datetime.datetime)

    async def test_listModels_empty(self, testDatabase: Database) -> None:
        """listModels on an empty table returns ``[]``."""
        rows = await testDatabase.embeddingModels.listModels()
        assert rows == []

    ###
    # dataSource routing (multi-source deployment contract)
    ###
    async def test_getOrCreateModelId_routesDataSourceToProviderOnCacheMiss(self, testDatabase: Database) -> None:
        """getOrCreateModelId forwards ``dataSource`` to ``getProvider`` on a cache miss.

        Cache MUST miss for this test to be load-bearing — a fresh
        ``(model, dimensions)`` pair is used and the cache is reset
        defensively. ``DatabaseManager`` uses ``__slots__``, so the spy
        is installed at the CLASS level (an instance-level
        ``patch.object`` raises ``AttributeError``). The spy wraps the
        real bound method so the allocation still runs end-to-end.
        """
        # Defensive: clear the cache so an earlier test's entry cannot
        # short-circuit this call (a cache hit skips getProvider entirely).
        testDatabase.embeddingModels._cache.clear()

        original = testDatabase.manager.getProvider
        with patch.object(DatabaseManager, "getProvider", new=AsyncMock(wraps=original)) as spy:
            await testDatabase.embeddingModels.getOrCreateModelId("route-test-model", 384, dataSource="custom-src")

        # Strict: exactly one getProvider call expected on a cache miss.
        # Without this guard, a future regression that adds a second
        # getProvider call (e.g. an eager cache-fill) would silently
        # pass while ``call_args`` only inspects the LAST invocation.
        spy.assert_called_once()
        lastCall = spy.call_args
        assert lastCall.kwargs.get("dataSource") == "custom-src"
        # Write path: readonly must be False for an allocating call.
        assert lastCall.kwargs.get("readonly") is False

    async def test_getOrCreateModelId_cacheHitDoesNotConsultDataSource(self, testDatabase: Database) -> None:
        """On a cache hit, ``getProvider`` is NOT called — ``dataSource`` is irrelevant.

        Complementary to the routing test above: the cache-hit path must
        short-circuit before acquiring a provider, so ``dataSource`` has
        no effect on it. Patches ``getProvider`` to a strict mock that
        raises if awaited.
        """
        repo = testDatabase.embeddingModels

        # First call populates the cache (cache miss).
        firstId = await repo.getOrCreateModelId("cache-hit-model", 384)
        assert ("cache-hit-model", 384) in repo._cache

        # Second call: cache hit. Patch getProvider to raise if awaited.
        strictProvider = AsyncMock(side_effect=AssertionError("cache hit must not acquire a provider"))
        with patch.object(DatabaseManager, "getProvider", strictProvider):
            secondId = await repo.getOrCreateModelId("cache-hit-model", 384, dataSource="custom-src")

        assert secondId == firstId
        strictProvider.assert_not_called()

    async def test_getModelById_routesDataSourceToProvider(self, testDatabase: Database) -> None:
        """getModelById forwards ``dataSource`` to ``getProvider``.

        ``getModelById`` has no cache, so every call hits the DB; the
        spy must observe the ``dataSource`` kwarg.
        """
        # Seed a row so the call has something to fetch (not strictly
        # required — routing happens before the SELECT — but keeps the
        # test honest about the read path).
        await testDatabase.embeddingModels.getOrCreateModelId("getbyid-model", 384)

        original = testDatabase.manager.getProvider
        with patch.object(DatabaseManager, "getProvider", new=AsyncMock(wraps=original)) as spy:
            await testDatabase.embeddingModels.getModelById(1, dataSource="custom-src")

        # Strict: exactly one getProvider call expected (no cache on this path).
        spy.assert_called_once()
        lastCall = spy.call_args
        assert lastCall.kwargs.get("dataSource") == "custom-src"
        # Read path.
        assert lastCall.kwargs.get("readonly") is True

    async def test_listModels_routesDataSourceToProvider(self, testDatabase: Database) -> None:
        """listModels forwards ``dataSource`` to ``getProvider``.

        ``listModels`` has no cache, so every call hits the DB; the spy
        must observe the ``dataSource`` kwarg.
        """
        # Seed a row (not required for the routing assertion, but keeps
        # the read path real).
        await testDatabase.embeddingModels.getOrCreateModelId("list-model", 384)

        original = testDatabase.manager.getProvider
        with patch.object(DatabaseManager, "getProvider", new=AsyncMock(wraps=original)) as spy:
            await testDatabase.embeddingModels.listModels(dataSource="custom-src")

        # Strict: exactly one getProvider call expected (no cache on this path).
        spy.assert_called_once()
        lastCall = spy.call_args
        assert lastCall.kwargs.get("dataSource") == "custom-src"
        # Read path.
        assert lastCall.kwargs.get("readonly") is True
