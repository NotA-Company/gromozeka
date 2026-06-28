"""Tests for SQLite3Provider vector search — fallback path (no sqlite-vec)."""

import array
from typing import Any

import pytest

from internal.database.providers.base import (
    VectorColumnType,
    VectorDistanceMetric,
)
from internal.database.providers.sqlite3 import SQLite3Provider


class TestSQLite3VectorSearchFallback:
    """Tests for graceful fallback when sqlite-vec is unavailable."""

    @pytest.fixture
    def providerWithoutVec(self, tmp_path, monkeypatch):
        """SQLite3Provider with sqlite-vec module-level flag mocked to False.

        Uses ``monkeypatch`` so the flag stays ``False`` for the entire
        test body (including any ``connect()`` call).

        Returns:
            A :class:`SQLite3Provider` instance with the module-level
            ``_SQLITE_VEC_AVAILABLE`` flag patched to ``False``.
        """
        monkeypatch.setattr(
            "internal.database.providers.sqlite3._SQLITE_VEC_AVAILABLE",
            False,
        )
        provider = SQLite3Provider(dbPath=str(tmp_path / "test.db"))
        return provider

    async def test_isVectorSearchSupportedFalseWithoutExtension(self, providerWithoutVec):
        """Provider reports False when sqlite-vec is not loaded.

        Before connect(), _vectorSearchAvailable is False (set in __init__).
        """
        assert await providerWithoutVec.isVectorSearchSupported() is False

    async def test_vectorSearchRaisesWithoutExtension(self, providerWithoutVec):
        """vectorSearch raises NotImplementedError without sqlite-vec."""
        with pytest.raises(NotImplementedError, match="vector search"):
            await providerWithoutVec.vectorSearch(
                table="test",
                vectorColumn="embedding",
                returnColumns=["id"],
                queryVector=b"test",
                k=10,
            )

    async def test_isVectorSearchSupportedAfterConnectWithoutVec(self, providerWithoutVec):
        """After connect() without sqlite-vec available, still returns False."""
        await providerWithoutVec.connect()
        try:
            assert await providerWithoutVec.isVectorSearchSupported() is False
        finally:
            await providerWithoutVec.disconnect()


@pytest.fixture
async def providerWithVec(tmp_path):
    """SQLite3Provider with sqlite-vec loaded.

    Creates a temporary database, connects, and skips if
    sqlite-vec is not installed.

    Yields:
        A connected :class:`SQLite3Provider` with ``isVectorSearchSupported()``
        returning ``True``.
    """
    from internal.database.providers.sqlite3 import _SQLITE_VEC_AVAILABLE

    if not _SQLITE_VEC_AVAILABLE:
        pytest.skip("sqlite-vec not installed")

    provider = SQLite3Provider(dbPath=str(tmp_path / "test.db"))
    await provider.connect()
    if not await provider.isVectorSearchSupported():
        await provider.disconnect()
        pytest.skip("sqlite-vec extension not loaded")
    yield provider
    await provider.disconnect()


class TestSQLite3VectorSearchReal:
    """Tests with real sqlite-vec extension."""

    async def test_vectorSearchAutoConnectsWhenUnconnected(self, tmp_path):
        """vectorSearch() auto-connects if the provider was not yet connected.

        Regression: capability detection happens in ``connect()`` (the
        sqlite-vec extension is loaded there). When a caller invokes
        ``vectorSearch()`` on a fresh provider with ``keepConnection=False``,
        the provider must auto-connect so ``_vectorSearchAvailable`` is
        populated and the search can proceed — without the caller having to
        manually call ``connect()`` (which would break the
        ``keepConnection=False`` lifecycle by leaving ``wasConnected=True``
        for subsequent ``cursor()`` invocations).
        """
        from internal.database.providers.sqlite3 import _SQLITE_VEC_AVAILABLE

        if not _SQLITE_VEC_AVAILABLE:
            pytest.skip("sqlite-vec not installed")

        provider = SQLite3Provider(dbPath=str(tmp_path / "autodb.db"))
        assert provider._connection is None
        assert provider._vectorSearchAvailable is False

        # Build a vec0 table + rows while connected, then disconnect so
        # the subsequent vectorSearch() starts from an unconnected state.
        columns: list[Any] = [
            {"name": "id", "columnType": VectorColumnType.INTEGER},
            {
                "name": "embedding",
                "columnType": VectorColumnType.VECTOR,
                "vectorDimension": 2,
                "distanceMetric": VectorDistanceMetric.COSINE,
            },
        ]
        try:
            await provider.connect()
            if not await provider.isVectorSearchSupported():
                pytest.skip("sqlite-vec extension not loaded")
            await provider.createVectorTable("vec_autoconn", columns)
            await provider.execute(
                "INSERT INTO vec_autoconn (id, embedding) VALUES (:id, :embedding)",
                {"id": 1, "embedding": array.array("f", [1.0, 0.0]).tobytes()},
            )
            await provider.disconnect()

            # Pre-condition: provider is now disconnected.
            assert provider._connection is None

            queryBytes = array.array("f", [1.0, 0.0]).tobytes()
            results = await provider.vectorSearch(
                table="vec_autoconn",
                vectorColumn="embedding",
                returnColumns=["id"],
                queryVector=queryBytes,
                k=1,
            )

            # Auto-connect happened: the extension loaded (capability flag
            # is set during connect() and persists across disconnect), and
            # the query returned results without the caller ever calling
            # connect() explicitly. Without auto-connect, vectorSearch()
            # would have raised NotImplementedError because
            # _vectorSearchAvailable starts False.
            assert await provider.isVectorSearchSupported() is True
            assert len(results) == 1
            assert results[0]["rowKey"]["id"] == "1"
        finally:
            await provider.disconnect()

    async def test_vectorSearchCosine(self, providerWithVec):
        """Basic cosine search returns correct ordering."""
        columns: list[Any] = [
            {"name": "id", "columnType": VectorColumnType.INTEGER},
            {
                "name": "embedding",
                "columnType": VectorColumnType.VECTOR,
                "vectorDimension": 3,
                "distanceMetric": VectorDistanceMetric.COSINE,
            },
        ]
        await providerWithVec.createVectorTable("vec_test", columns)

        # Vector A: [1.0, 0.0, 0.0] — closest to query [1.0, 0.0, 0.0]
        vecA = array.array("f", [1.0, 0.0, 0.0]).tobytes()
        # Vector B: [0.0, 1.0, 0.0] — orthogonal to query
        vecB = array.array("f", [0.0, 1.0, 0.0]).tobytes()
        # Vector C: [-1.0, 0.0, 0.0] — opposite to query
        vecC = array.array("f", [-1.0, 0.0, 0.0]).tobytes()

        await providerWithVec.execute(
            "INSERT INTO vec_test (id, embedding) VALUES (:id, :embedding)",
            {"id": 1, "embedding": vecA},
        )
        await providerWithVec.execute(
            "INSERT INTO vec_test (id, embedding) VALUES (:id, :embedding)",
            {"id": 2, "embedding": vecB},
        )
        await providerWithVec.execute(
            "INSERT INTO vec_test (id, embedding) VALUES (:id, :embedding)",
            {"id": 3, "embedding": vecC},
        )

        queryBytes = array.array("f", [1.0, 0.0, 0.0]).tobytes()
        results = await providerWithVec.vectorSearch(
            table="vec_test",
            vectorColumn="embedding",
            returnColumns=["id"],
            queryVector=queryBytes,
            k=3,
        )

        assert len(results) == 3
        # First result should be id=1 (cosine distance ~0.0)
        assert results[0]["rowKey"]["id"] == "1"
        assert results[0]["distance"] < 0.001
        # Second should be id=2 (cosine distance = 1.0, orthogonal)
        assert results[1]["rowKey"]["id"] == "2"
        assert 0.9 < results[1]["distance"] < 1.1
        # Third should be id=3 (cosine distance = 2.0, opposite)
        assert results[2]["rowKey"]["id"] == "3"
        assert 1.9 < results[2]["distance"] < 2.1

    async def test_vectorSearchWithFilter(self, providerWithVec):
        """Filter clause restricts results."""
        columns: list[Any] = [
            {"name": "id", "columnType": VectorColumnType.INTEGER},
            {"name": "category", "columnType": VectorColumnType.TEXT},
            {
                "name": "embedding",
                "columnType": VectorColumnType.VECTOR,
                "vectorDimension": 2,
                "distanceMetric": VectorDistanceMetric.COSINE,
            },
        ]
        await providerWithVec.createVectorTable("vec_test_filter", columns)

        vec = array.array("f", [1.0, 0.0]).tobytes()
        await providerWithVec.execute(
            "INSERT INTO vec_test_filter (id, category, embedding) VALUES (:id, :category, :embedding)",
            {"id": 1, "category": "keep", "embedding": vec},
        )
        await providerWithVec.execute(
            "INSERT INTO vec_test_filter (id, category, embedding) VALUES (:id, :category, :embedding)",
            {"id": 2, "category": "drop", "embedding": vec},
        )

        queryVec = array.array("f", [1.0, 0.0]).tobytes()
        results = await providerWithVec.vectorSearch(
            table="vec_test_filter",
            vectorColumn="embedding",
            returnColumns=["id"],
            queryVector=queryVec,
            k=10,
            filterClause="category = :cat",
            filterParams={"cat": "keep"},
        )

        assert len(results) == 1
        assert results[0]["rowKey"]["id"] == "1"

    async def test_vectorSearchEmptyTable(self, providerWithVec):
        """Empty table returns empty list."""
        columns: list[Any] = [
            {"name": "id", "columnType": VectorColumnType.INTEGER},
            {
                "name": "embedding",
                "columnType": VectorColumnType.VECTOR,
                "vectorDimension": 2,
                "distanceMetric": VectorDistanceMetric.COSINE,
            },
        ]
        await providerWithVec.createVectorTable("vec_test_empty", columns)

        queryVec = array.array("f", [1.0, 0.0]).tobytes()
        results = await providerWithVec.vectorSearch(
            table="vec_test_empty",
            vectorColumn="embedding",
            returnColumns=["id"],
            queryVector=queryVec,
            k=10,
        )
        assert results == []

    async def test_vectorSearchUnsupportedMetric(self, providerWithVec):
        """Requesting L2 metric on a cosine-configured vec0 table raises ValueError."""
        columns: list[Any] = [
            {"name": "id", "columnType": VectorColumnType.INTEGER},
            {
                "name": "embedding",
                "columnType": VectorColumnType.VECTOR,
                "vectorDimension": 2,
                "distanceMetric": VectorDistanceMetric.COSINE,
            },
        ]
        await providerWithVec.createVectorTable("vec_test_metric", columns)

        queryVec = array.array("f", [1.0, 0.0]).tobytes()
        with pytest.raises(ValueError, match="cosine distance"):
            await providerWithVec.vectorSearch(
                table="vec_test_metric",
                vectorColumn="embedding",
                returnColumns=["id"],
                queryVector=queryVec,
                k=10,
                distanceMetric=VectorDistanceMetric.L2,
            )


class TestSQLite3VecTableManagement:
    """Tests for listTables and createVectorTable."""

    async def test_listTablesReturnsTables(self, providerWithVec):
        """listTables returns vec0 tables matching pattern."""
        columns: list[Any] = [
            {"name": "id", "columnType": VectorColumnType.INTEGER},
            {
                "name": "embedding",
                "columnType": VectorColumnType.VECTOR,
                "vectorDimension": 2,
                "distanceMetric": VectorDistanceMetric.COSINE,
            },
        ]
        await providerWithVec.createVectorTable("vec_message_embeddings_384", columns)
        await providerWithVec.createVectorTable("other_table", columns)

        tables = await providerWithVec.listTables("vec_message_embeddings_%")
        assert "vec_message_embeddings_384" in tables
        assert "other_table" not in tables

    async def test_listTablesAll(self, providerWithVec):
        """listTables with default '%' returns all tables."""
        columns: list[Any] = [
            {"name": "id", "columnType": VectorColumnType.INTEGER},
            {
                "name": "embedding",
                "columnType": VectorColumnType.VECTOR,
                "vectorDimension": 2,
                "distanceMetric": VectorDistanceMetric.COSINE,
            },
        ]
        await providerWithVec.createVectorTable("vec_msg_384", columns)
        tables = await providerWithVec.listTables()
        assert "vec_msg_384" in tables

    async def test_createVectorTableBasic(self, providerWithVec):
        """createVectorTable creates a vec0 table successfully."""
        columns: list[Any] = [
            {"name": "message_id", "columnType": VectorColumnType.TEXT},
            {
                "name": "chat_id",
                "columnType": VectorColumnType.INTEGER,
                "isPartitionKey": True,
            },
            {
                "name": "embedding",
                "columnType": VectorColumnType.VECTOR,
                "vectorDimension": 384,
                "distanceMetric": VectorDistanceMetric.COSINE,
            },
        ]
        await providerWithVec.createVectorTable("vec_message_embeddings_384", columns)
        tables = await providerWithVec.listTables("vec_message_embeddings_%")
        assert "vec_message_embeddings_384" in tables

    async def test_createVectorTableNoVectorColumn(self, providerWithVec):
        """createVectorTable raises ValueError without VECTOR column."""
        columns: list[Any] = [
            {"name": "id", "columnType": VectorColumnType.INTEGER},
        ]
        with pytest.raises(ValueError, match="VECTOR"):
            await providerWithVec.createVectorTable("test_no_vec", columns)

    async def test_createVectorTableIdempotent(self, providerWithVec):
        """createVectorTable is idempotent (CREATE VIRTUAL TABLE IF NOT EXISTS)."""
        columns: list[Any] = [
            {"name": "id", "columnType": VectorColumnType.INTEGER},
            {
                "name": "embedding",
                "columnType": VectorColumnType.VECTOR,
                "vectorDimension": 2,
                "distanceMetric": VectorDistanceMetric.COSINE,
            },
        ]
        await providerWithVec.createVectorTable("vec_test_idem", columns)
        # Creating again should not raise.
        await providerWithVec.createVectorTable("vec_test_idem", columns)

    async def test_createVectorTableDifferentDimensions(self, providerWithVec):
        """Tables with different dimensions coexist."""
        cols384: list[Any] = [
            {"name": "message_id", "columnType": VectorColumnType.TEXT},
            {
                "name": "embedding",
                "columnType": VectorColumnType.VECTOR,
                "vectorDimension": 384,
                "distanceMetric": VectorDistanceMetric.COSINE,
            },
        ]
        cols1024: list[Any] = [
            {"name": "message_id", "columnType": VectorColumnType.TEXT},
            {
                "name": "embedding",
                "columnType": VectorColumnType.VECTOR,
                "vectorDimension": 1024,
                "distanceMetric": VectorDistanceMetric.COSINE,
            },
        ]
        await providerWithVec.createVectorTable("vec_message_embeddings_384", cols384)
        await providerWithVec.createVectorTable("vec_message_embeddings_1024", cols1024)
        tables = await providerWithVec.listTables("vec_message_embeddings_%")
        assert "vec_message_embeddings_384" in tables
        assert "vec_message_embeddings_1024" in tables

    async def test_vectorSearchDimensionAware(self, providerWithVec):
        """vectorSearch on dimension-specific table returns correct results."""
        cols2: list[Any] = [
            {"name": "id", "columnType": VectorColumnType.INTEGER},
            {
                "name": "embedding",
                "columnType": VectorColumnType.VECTOR,
                "vectorDimension": 2,
                "distanceMetric": VectorDistanceMetric.COSINE,
            },
        ]
        cols4: list[Any] = [
            {"name": "id", "columnType": VectorColumnType.INTEGER},
            {
                "name": "embedding",
                "columnType": VectorColumnType.VECTOR,
                "vectorDimension": 4,
                "distanceMetric": VectorDistanceMetric.COSINE,
            },
        ]
        await providerWithVec.createVectorTable("vec_test_2d", cols2)
        await providerWithVec.createVectorTable("vec_test_4d", cols4)

        vec2dA = array.array("f", [1.0, 0.0]).tobytes()
        vec4d = array.array("f", [0.9, 0.1, 0.0, 0.0]).tobytes()

        await providerWithVec.execute(
            "INSERT INTO vec_test_2d (id, embedding) VALUES (:id, :embedding)",
            {"id": 1, "embedding": vec2dA},
        )
        await providerWithVec.execute(
            "INSERT INTO vec_test_4d (id, embedding) VALUES (:id, :embedding)",
            {"id": 2, "embedding": vec4d},
        )

        # Search 2D table with 2D query
        query2d = array.array("f", [1.0, 0.0]).tobytes()
        results2d = await providerWithVec.vectorSearch(
            table="vec_test_2d",
            vectorColumn="embedding",
            returnColumns=["id"],
            queryVector=query2d,
            k=10,
        )
        assert len(results2d) == 1
        assert results2d[0]["rowKey"]["id"] == "1"

        # Search 4D table with 4D query
        query4d = array.array("f", [0.9, 0.1, 0.0, 0.0]).tobytes()
        results4d = await providerWithVec.vectorSearch(
            table="vec_test_4d",
            vectorColumn="embedding",
            returnColumns=["id"],
            queryVector=query4d,
            k=10,
        )
        assert len(results4d) == 1
        assert results4d[0]["rowKey"]["id"] == "2"

    async def test_isVectorSearchSupportedAfterConnect(self, providerWithVec):
        """After successful connect with sqlite-vec, returns True."""
        assert await providerWithVec.isVectorSearchSupported() is True
