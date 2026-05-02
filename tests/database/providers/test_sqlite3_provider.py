"""
Tests for SQLite3 provider implementation.

This module tests the SQLite3Provider class including:
- Connection management
- Query execution
- Upsert operations
- Batch operations
- Parameter binding
"""

import pytest

from internal.database.providers.base import ExcludedValue, FetchType, ParametrizedQuery
from internal.database.providers.sqlite3 import SQLite3Provider


@pytest.fixture
async def sqliteProvider():
    """Create an in-memory SQLite provider for testing."""
    provider = SQLite3Provider(":memory:")
    await provider.connect()
    yield provider
    await provider.disconnect()


class TestConnectionManagement:
    """Tests for connection management."""

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self):
        """Test connecting and disconnecting from database."""
        provider = SQLite3Provider(":memory:")
        assert provider._connection is None

        await provider.connect()
        assert provider._connection is not None

        await provider.disconnect()
        assert provider._connection is None

    @pytest.mark.asyncio
    async def test_connect_already_connected(self):
        """Test that connecting when already connected is a no-op."""
        provider = SQLite3Provider(":memory:")
        await provider.connect()
        connection = provider._connection

        # Connect again
        await provider.connect()
        assert provider._connection is connection

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test using provider as async context manager."""
        async with SQLite3Provider(":memory:") as provider:
            assert provider._connection is not None  # type: ignore
        assert provider._connection is None  # type: ignore

    @pytest.mark.asyncio
    async def test_is_readonly(self):
        """Test isReadOnly method."""
        provider = SQLite3Provider(":memory:", readOnly=True)
        assert await provider.isReadOnly() is True

        provider = SQLite3Provider(":memory:", readOnly=False)
        assert await provider.isReadOnly() is False


class TestQueryExecution:
    """Tests for query execution."""

    @pytest.mark.asyncio
    async def test_execute_no_fetch(self, sqliteProvider):
        """Test execute with NO_FETCH."""
        result = await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_fetch_one(self, sqliteProvider):
        """Test execute with FETCH_ONE."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        await sqliteProvider.execute("INSERT INTO test (id, name) VALUES (1, 'test')")

        result = await sqliteProvider.execute("SELECT * FROM test WHERE id = 1", fetchType=FetchType.FETCH_ONE)
        assert result is not None
        assert result["id"] == 1
        assert result["name"] == "test"

    @pytest.mark.asyncio
    async def test_execute_fetch_all(self, sqliteProvider):
        """Test execute with FETCH_ALL."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        await sqliteProvider.execute("INSERT INTO test (id, name) VALUES (1, 'test1')")
        await sqliteProvider.execute("INSERT INTO test (id, name) VALUES (2, 'test2')")

        result = await sqliteProvider.execute("SELECT * FROM test", fetchType=FetchType.FETCH_ALL)
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2

    @pytest.mark.asyncio
    async def test_execute_with_params(self, sqliteProvider):
        """Test execute with named parameters."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        await sqliteProvider.execute("INSERT INTO test (id, name) VALUES (:id, :name)", {"id": 1, "name": "test"})

        result = await sqliteProvider.executeFetchOne("SELECT * FROM test WHERE id = :id", {"id": 1})
        assert result is not None
        assert result["name"] == "test"

    @pytest.mark.asyncio
    async def test_execute_fetch_one_convenience(self, sqliteProvider):
        """Test executeFetchOne convenience method."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        await sqliteProvider.execute("INSERT INTO test (id, name) VALUES (1, 'test')")

        result = await sqliteProvider.executeFetchOne("SELECT * FROM test WHERE id = 1")
        assert result is not None
        assert result["id"] == 1

    @pytest.mark.asyncio
    async def test_execute_fetch_all_convenience(self, sqliteProvider):
        """Test executeFetchAll convenience method."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        await sqliteProvider.execute("INSERT INTO test (id, name) VALUES (1, 'test1')")
        await sqliteProvider.execute("INSERT INTO test (id, name) VALUES (2, 'test2')")

        result = await sqliteProvider.executeFetchAll("SELECT * FROM test")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_execute_with_parametrized_query(self, sqliteProvider):
        """Test execute with ParametrizedQuery object."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")

        query = ParametrizedQuery("INSERT INTO test (id, name) VALUES (:id, :name)", {"id": 1, "name": "test"})
        await sqliteProvider.execute(query)

        result = await sqliteProvider.executeFetchOne("SELECT * FROM test WHERE id = 1")
        assert result is not None
        assert result["name"] == "test"


class TestUpsert:
    """Tests for upsert operations."""

    @pytest.mark.asyncio
    async def test_upsert_insert(self, sqliteProvider):
        """Test upsert for insert (new record)."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT, value INTEGER)")

        result = await sqliteProvider.upsert(
            table="test", values={"id": 1, "name": "test", "value": 100}, conflictColumns=["id"]
        )
        assert result is True

        row = await sqliteProvider.executeFetchOne("SELECT * FROM test WHERE id = 1")
        assert row is not None
        assert row["name"] == "test"
        assert row["value"] == 100

    @pytest.mark.asyncio
    async def test_upsert_update(self, sqliteProvider):
        """Test upsert for update (existing record)."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT, value INTEGER)")

        # Insert initial record
        await sqliteProvider.upsert(
            table="test", values={"id": 1, "name": "test", "value": 100}, conflictColumns=["id"]
        )

        # Update with upsert
        await sqliteProvider.upsert(
            table="test", values={"id": 1, "name": "updated", "value": 200}, conflictColumns=["id"]
        )

        row = await sqliteProvider.executeFetchOne("SELECT * FROM test WHERE id = 1")
        assert row is not None
        assert row["name"] == "updated"
        assert row["value"] == 200

    @pytest.mark.asyncio
    async def test_upsert_with_excluded_value(self, sqliteProvider):
        """Test upsert with ExcludedValue."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT, value INTEGER)")

        # Insert initial record
        await sqliteProvider.upsert(
            table="test", values={"id": 1, "name": "test", "value": 100}, conflictColumns=["id"]
        )

        # Update only name, keep value from excluded
        await sqliteProvider.upsert(
            table="test",
            values={"id": 1, "name": "updated", "value": 999},
            conflictColumns=["id"],
            updateExpressions={"name": ExcludedValue(), "value": "value + 1"},  # Increment value
        )

        row = await sqliteProvider.executeFetchOne("SELECT * FROM test WHERE id = 1")
        assert row is not None
        assert row["name"] == "updated"
        assert row["value"] == 101  # 100 + 1

    @pytest.mark.asyncio
    async def test_upsert_with_custom_excluded_column(self, sqliteProvider):
        """Test upsert with ExcludedValue specifying column name."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT, value INTEGER)")

        # Insert initial record
        await sqliteProvider.upsert(
            table="test", values={"id": 1, "name": "test", "value": 100}, conflictColumns=["id"]
        )

        # Update with ExcludedValue (should use excluded.name and excluded.value)
        await sqliteProvider.upsert(
            table="test",
            values={"id": 1, "name": "updated", "value": 200},
            conflictColumns=["id"],
            updateExpressions={"name": ExcludedValue("name"), "value": ExcludedValue("value")},
        )

        row = await sqliteProvider.executeFetchOne("SELECT * FROM test WHERE id = 1")
        assert row is not None
        assert row["name"] == "updated"
        assert row["value"] == 200

    @pytest.mark.asyncio
    async def test_upsert_multiple_conflict_columns(self, sqliteProvider):
        """Test upsert with multiple conflict columns."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER, name TEXT, value INTEGER, PRIMARY KEY (id, name))")

        # Insert initial record
        await sqliteProvider.upsert(
            table="test", values={"id": 1, "name": "test", "value": 100}, conflictColumns=["id", "name"]
        )

        # Update with same id and name
        await sqliteProvider.upsert(
            table="test", values={"id": 1, "name": "test", "value": 200}, conflictColumns=["id", "name"]
        )

        row = await sqliteProvider.executeFetchOne("SELECT * FROM test WHERE id = 1 AND name = 'test'")
        assert row is not None
        assert row["value"] == 200

    @pytest.mark.asyncio
    async def test_upsert_without_update_expressions(self, sqliteProvider):
        """Test upsert without updateExpressions (default behavior)."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT, value INTEGER)")

        # Insert initial record
        await sqliteProvider.upsert(
            table="test", values={"id": 1, "name": "test", "value": 100}, conflictColumns=["id"]
        )

        # Update without updateExpressions (should update all non-conflict columns)
        await sqliteProvider.upsert(
            table="test", values={"id": 1, "name": "updated", "value": 200}, conflictColumns=["id"]
        )

        row = await sqliteProvider.executeFetchOne("SELECT * FROM test WHERE id = 1")
        assert row is not None
        assert row["name"] == "updated"
        assert row["value"] == 200


class TestBatchExecute:
    """Tests for batch operations."""

    @pytest.mark.asyncio
    async def test_batch_execute(self, sqliteProvider):
        """Test batch execute with multiple queries."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")

        queries = [
            ParametrizedQuery("INSERT INTO test (id, name) VALUES (1, 'test1')"),
            ParametrizedQuery("INSERT INTO test (id, name) VALUES (2, 'test2')"),
            ParametrizedQuery("INSERT INTO test (id, name) VALUES (3, 'test3')"),
        ]

        results = await sqliteProvider.batchExecute(queries)
        assert len(results) == 3

        rows = await sqliteProvider.executeFetchAll("SELECT * FROM test")
        assert len(rows) == 3

    @pytest.mark.asyncio
    async def test_batch_execute_with_params(self, sqliteProvider):
        """Test batch execute with parameters."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")

        queries = [
            ParametrizedQuery("INSERT INTO test (id, name) VALUES (:id, :name)", {"id": 1, "name": "test1"}),
            ParametrizedQuery("INSERT INTO test (id, name) VALUES (:id, :name)", {"id": 2, "name": "test2"}),
        ]

        results = await sqliteProvider.batchExecute(queries)
        assert len(results) == 2

        rows = await sqliteProvider.executeFetchAll("SELECT * FROM test")
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_batch_execute_rollback_on_error(self, sqliteProvider):
        """Test that batch execute rolls back on error."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")

        queries = [
            ParametrizedQuery("INSERT INTO test (id, name) VALUES (1, 'test1')"),
            ParametrizedQuery("INSERT INTO test (id, name) VALUES (1, 'test2')"),  # Duplicate ID
            ParametrizedQuery("INSERT INTO test (id, name) VALUES (3, 'test3')"),
        ]

        with pytest.raises(Exception):
            await sqliteProvider.batchExecute(queries)

        # All inserts should be rolled back
        rows = await sqliteProvider.executeFetchAll("SELECT * FROM test")
        assert len(rows) == 0


class TestHelperMethods:
    """Tests for provider helper methods."""

    @pytest.mark.asyncio
    async def test_get_case_insensitive_comparison(self, sqliteProvider):
        """Test getCaseInsensitiveComparison returns SQLite expression."""
        comparison = sqliteProvider.getCaseInsensitiveComparison("username", "username")
        assert comparison == "LOWER(username) = LOWER(:username)"

    @pytest.mark.asyncio
    async def test_apply_pagination(self, sqliteProvider):
        """Test applyPagination adds LIMIT and OFFSET."""
        query = "SELECT * FROM test"
        paginated = sqliteProvider.applyPagination(query, limit=10, offset=5)
        assert paginated == "SELECT * FROM test LIMIT 10 OFFSET 5"

    @pytest.mark.asyncio
    async def test_get_text_type(self, sqliteProvider):
        """Test getTextType returns TEXT for SQLite."""
        textType = sqliteProvider.getTextType()
        assert textType == "TEXT"


class TestParameterBinding:
    """Tests for parameter binding."""

    @pytest.mark.asyncio
    async def test_named_parameters(self, sqliteProvider):
        """Test named parameter binding."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT, value INTEGER)")

        await sqliteProvider.execute(
            "INSERT INTO test (id, name, value) VALUES (:id, :name, :value)", {"id": 1, "name": "test", "value": 100}
        )

        result = await sqliteProvider.executeFetchOne(
            "SELECT * FROM test WHERE id = :id AND name = :name", {"id": 1, "name": "test"}
        )
        assert result is not None
        assert result["value"] == 100

    @pytest.mark.asyncio
    async def test_parameter_with_special_characters(self, sqliteProvider):
        """Test parameter binding with special characters."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")

        await sqliteProvider.execute(
            "INSERT INTO test (id, name) VALUES (:id, :name)",
            {"id": 1, "name": "test with 'quotes' and \"double quotes\""},
        )

        result = await sqliteProvider.executeFetchOne("SELECT * FROM test WHERE id = 1")
        assert result is not None
        assert "quotes" in result["name"]

    @pytest.mark.asyncio
    async def test_parameter_with_null(self, sqliteProvider):
        """Test parameter binding with NULL value."""
        await sqliteProvider.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")

        await sqliteProvider.execute("INSERT INTO test (id, name) VALUES (:id, :name)", {"id": 1, "name": None})

        result = await sqliteProvider.executeFetchOne("SELECT * FROM test WHERE id = 1")
        assert result is not None
        assert result["name"] is None
