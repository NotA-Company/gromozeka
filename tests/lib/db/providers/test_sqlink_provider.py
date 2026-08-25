"""
Tests for SQLink provider implementation

This module tests the SQLinkProvider class including:
- Initialization and configuration
- Connection management
- Auto-connection lifecycle
- Query execution
- Upsert operations
- Read-only detection
- Provider hooks for SQL portability
"""

import asyncio
from typing import Any, Optional, Sequence

import pytest
import sqlink

from lib.db.providers.base import ExcludedValue, FetchType, ParametrizedQuery, VectorColumnDef, VectorColumnType
from lib.db.providers.sqlink import SQLinkProvider
from lib.proxy import ProxyConfig, ProxyConfigDict, ProxyHelper, ProxyType

_UNSET_SENTINEL = object()


class FakeAsyncConnection:
    """Fake AsyncConnection for testing SQLink provider.

    Records all executions and provides controlled responses. This hand-rolled
    fake avoids the class-based AsyncMock prohibition while providing realistic
    sqlink.QueryResult and sqlink.DatabaseInfo objects.

    Attributes:
        executed: List of (sql, params) tuples for each execute call.
        batches: List of batch query lists for each executeBatch call.
        closed: Whether close() was called.
        databasesResult: List of DatabaseInfo objects returned by databases().
        executeError: Optional error to raise from execute.
    """

    executed: list[tuple[str, Any]]
    batches: list[list[tuple[str, Any]]]
    closed: bool
    databasesResult: list[sqlink.DatabaseInfo]
    executeError: Optional[Exception]

    def __init__(self) -> None:
        """Initialize fake connection with empty state."""
        self.executed = []
        self.batches = []
        self.closed = False
        self.databasesResult = []
        self.executeError = None

    async def execute(
        self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
    ) -> sqlink.QueryResult:
        """Fake execute that records calls and returns controlled results.

        Args:
            sql: SQL query string.
            params: Query parameters.
            database: Optional database name (ignored in fake).

        Returns:
            A sqlink.QueryResult with empty results by default.

        Raises:
            Exception: If executeError is set.
        """
        if self.executeError:
            raise self.executeError
        self.executed.append((sql, params))
        return makeQueryResult(columns=[], rows=[])

    async def executeBatch(
        self, queries: Sequence[tuple[str, Any]], *, database: Optional[str] = None
    ) -> Sequence[sqlink.QueryResult]:
        """Fake executeBatch that records calls.

        Args:
            queries: Sequence of (sql, params) tuples.
            database: Optional database name (ignored in fake).

        Returns:
            List of empty QueryResult objects.
        """
        self.batches.append(list(queries))
        return [makeQueryResult(columns=[], rows=[]) for _ in queries]

    async def databases(self) -> Sequence[sqlink.DatabaseInfo]:
        """Return configured database list.

        Returns:
            List of DatabaseInfo objects.
        """
        return self.databasesResult

    async def close(self) -> None:
        """Fake close that records the call."""
        self.closed = True


def makeQueryResult(columns: list[str], rows: list[tuple[Any, ...]]) -> sqlink.QueryResult:
    """Create a real sqlink.QueryResult for testing.

    Args:
        columns: Column names.
        rows: Row data as tuples.

    Returns:
        A sqlink.QueryResult object with the specified data.
    """
    return sqlink.QueryResult(columns=columns, rows=rows)


@pytest.fixture
def provider() -> SQLinkProvider:
    """Create an unconnected SQLinkProvider for testing.

    Tests are responsible for monkeypatching sqlink.asyncConnect as needed.

    Returns:
        Unconnected SQLinkProvider.
    """
    return SQLinkProvider(url="http://fake", user="u", password="secret", database="db")


@pytest.fixture
def fakeConnection() -> FakeAsyncConnection:
    """Create a FakeAsyncConnection for testing.

    Returns:
        Fresh FakeAsyncConnection instance.
    """
    return FakeAsyncConnection()


@pytest.fixture
def connectedProvider(fakeConnection: FakeAsyncConnection, monkeypatch) -> SQLinkProvider:
    """Create a SQLinkProvider with sqlink.asyncConnect monkeypatched.

    Args:
        fakeConnection: FakeAsyncConnection to return from asyncConnect.
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        Unconnected SQLinkProvider with mocked sqlink dependency.
    """

    async def fakeAsyncConnect(
        url: str,
        *,
        username: str,
        password: str,
        database: str,
        timeout: float,
        autoRefresh: bool,
        proxy: Optional[str] = None,
    ) -> sqlink.AsyncConnection:
        return fakeConnection  # type: ignore[return-value]

    monkeypatch.setattr("sqlink.asyncConnect", fakeAsyncConnect)

    return SQLinkProvider(url="http://fake", user="u", password="secret", database="db")


class TestInit:
    """Tests for SQLinkProvider initialization."""

    def test_required_kwargs_stored(self, provider: SQLinkProvider):
        """Test that required kwargs are stored correctly."""
        assert provider.url == "http://fake"
        assert provider.user == "u"
        assert provider.password == "secret"
        assert provider.database == "db"

    def test_timeout_default_30(self):
        """Test that timeout defaults to 30 when not specified."""
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")
        assert provider.timeout == 30

    def test_keepConnection_none_to_false(self):
        """Test that keepConnection=None is converted to False."""
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db", keepConnection=None)
        assert provider.keepConnection is False

    def test_proxy_dict_stored_as_proxy_config_object(self):
        """Test that proxy dict is stored as ProxyConfig object."""
        proxyConfig: ProxyConfigDict = {
            "type": ProxyType.HTTP,
            "address": "http://proxy:8080",
        }
        provider = SQLinkProvider(
            url="http://fake",
            user="u",
            password="secret",
            database="db",
            proxy=proxyConfig,
            # use-proxy=True is required to opt in; without it the proxy dict
            # is forced to ProxyType.NONE and the address is wiped.
            **{"use-proxy": True},
        )

        assert isinstance(provider._proxy, ProxyConfig)
        # Verify the address round-trips correctly
        assert provider._proxy.address == "http://proxy:8080"

    def test_use_proxy_kebab_kwarg_flows_to_fromDict(self):
        """Test that use-proxy kebab kwarg flows to ProxyConfig.fromDict.

        Construct with the same proxy dict twice: once with use-proxy=True
        and once without. The opted-in case stores the configured address
        and type, while the opted-out case stores type=ProxyType.NONE.
        """
        proxyConfig: ProxyConfigDict = {
            "type": ProxyType.HTTP,
            "address": "http://proxy:8080",
        }

        # With use-proxy=True: proxy is configured
        providerWithProxy = SQLinkProvider(
            url="http://fake",
            user="u",
            password="secret",
            database="db",
            proxy=proxyConfig,
            **{"use-proxy": True},
        )

        assert isinstance(providerWithProxy._proxy, ProxyConfig)
        assert providerWithProxy._proxy.type == ProxyType.HTTP
        assert providerWithProxy._proxy.address == "http://proxy:8080"

        # Without use-proxy: proxy is forced to NONE
        providerWithoutProxy = SQLinkProvider(
            url="http://fake",
            user="u",
            password="secret",
            database="db",
            proxy=proxyConfig,
        )

        assert isinstance(providerWithoutProxy._proxy, ProxyConfig)
        assert providerWithoutProxy._proxy.type == ProxyType.NONE

    def test_unknown_kwargs_silently_swallowed(self):
        """Test that unknown kwargs are silently swallowed without error."""
        provider = SQLinkProvider(
            url="http://fake",
            user="u",
            password="secret",
            database="db",
            readOnly=True,  # type: ignore[arg-type, call-arg]
        )
        assert provider.url == "http://fake"

    def test_repr_redacts_password(self):
        """Test that __repr__ redacts password literal."""
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")
        reprStr = repr(provider)
        assert "password='***'" in reprStr
        assert "password='secret'" not in reprStr
        assert "url=" in reprStr
        assert "user=" in reprStr
        assert "database=" in reprStr


class TestConnectDisconnect:
    """Tests for connect and disconnect behavior."""

    async def test_connect_passes_exact_kwargs(self, connectedProvider: SQLinkProvider, monkeypatch):
        """Test that connect passes exact kwargs to sqlink.asyncConnect."""
        connectKwargs: dict[str, Any] = {}
        capturedProxy: Any = _UNSET_SENTINEL

        async def captureConnect(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            nonlocal capturedProxy
            capturedProxy = proxy
            connectKwargs.update(
                {
                    "url": url,
                    "username": username,
                    "password": password,
                    "database": database,
                    "timeout": timeout,
                    "autoRefresh": autoRefresh,
                    "proxy": proxy,
                }
            )
            return FakeAsyncConnection()  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", captureConnect)

        await connectedProvider.connect()

        assert connectKwargs == {
            "url": "http://fake",
            "username": "u",
            "password": "secret",
            "database": "db",
            "timeout": 30.0,
            "autoRefresh": True,
            "proxy": None,
        }
        # Verify proxy was explicitly None (not unset)
        assert capturedProxy is None
        assert "proxy" in connectKwargs

    async def test_second_connect_no_op(self, connectedProvider: SQLinkProvider):
        """Test that second connect is a no-op when already connected."""
        await connectedProvider.connect()
        connection = connectedProvider._connection

        await connectedProvider.connect()
        assert connectedProvider._connection is connection

    async def test_concurrent_connect_single_call(self, connectedProvider: SQLinkProvider, monkeypatch):
        """Test that concurrent connects only call asyncConnect once via lock."""
        callCount = 0

        async def countingConnect(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            nonlocal callCount
            callCount += 1
            await asyncio.sleep(0.01)
            return FakeAsyncConnection()  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", countingConnect)

        await asyncio.gather(connectedProvider.connect(), connectedProvider.connect())
        assert callCount == 1

    async def test_disconnect_closes_and_clears_slot(
        self, connectedProvider: SQLinkProvider, fakeConnection: FakeAsyncConnection
    ):
        """Test that disconnect closes connection and clears slot."""
        await connectedProvider.connect()
        await connectedProvider.disconnect()
        assert connectedProvider._connection is None
        assert fakeConnection.closed is True

    async def test_disconnect_noop_when_unconnected(self, connectedProvider: SQLinkProvider):
        """Test that disconnect is a no-op when not connected."""
        await connectedProvider.disconnect()
        assert connectedProvider._connection is None

    async def test_context_manager_connects_disconnects(self, monkeypatch):
        """Test that async context manager connects and disconnects."""

        async def fakeAsyncConnect(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return FakeAsyncConnection()  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", fakeAsyncConnect)

        async with SQLinkProvider(url="http://fake", user="u", password="secret", database="db") as provider:
            assert provider._connection is not None  # type: ignore[attr-defined]
        assert provider._connection is None  # type: ignore[attr-defined]


class TestAutoConnection:
    """Tests for _autoConnection context manager behavior."""

    async def test_auto_connection_opened_and_closed(
        self, connectedProvider: SQLinkProvider, fakeConnection: FakeAsyncConnection
    ):
        """Test that auto-connection is opened and closed when keepConnection=False."""
        result = await connectedProvider.execute("SELECT 1")
        assert result is None
        assert connectedProvider._connection is None
        assert fakeConnection.closed is True

    async def test_keep_connection_true_stays_open(self, monkeypatch):
        """Test that keepConnection=True keeps connection open."""
        fake = FakeAsyncConnection()

        async def fakeAsyncConnect(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", fakeAsyncConnect)

        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db", keepConnection=True)
        await provider.execute("SELECT 1")
        assert provider._connection is not None
        await provider.disconnect()

    async def test_pre_existing_connection_not_closed(self, connectedProvider: SQLinkProvider):
        """Test that pre-existing connection is not closed by auto-connection."""
        await connectedProvider.connect()
        connection = connectedProvider._connection
        await connectedProvider.execute("SELECT 1")
        assert connectedProvider._connection is connection
        await connectedProvider.disconnect()

    async def test_body_raise_connection_still_closed(self, provider: SQLinkProvider, monkeypatch):
        """Test that connection is closed even when body raises."""
        fake = FakeAsyncConnection()
        fake.executeError = RuntimeError("test error")

        async def errorConnect(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", errorConnect)

        with pytest.raises(RuntimeError, match="test error"):
            await provider.execute("SELECT 1")

        assert provider._connection is None


class TestExecute:
    """Tests for _execute method and query execution."""

    async def test_no_fetch_returns_none(self, provider: SQLinkProvider, monkeypatch):
        """Test that NO_FETCH returns None even with rows."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        result = await provider.execute("SELECT 1", fetchType=FetchType.NO_FETCH)
        assert result is None

    async def test_fetch_one_multi_row_returns_first_dict(self, provider: SQLinkProvider, monkeypatch):
        """Test that FETCH_ONE with multiple rows returns first row as dict."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def fakeExecute(
            self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
        ) -> sqlink.QueryResult:
            return makeQueryResult(columns=["id", "name"], rows=[(1, "a"), (2, "b")])

        monkeypatch.setattr(FakeAsyncConnection, "execute", fakeExecute)

        result = await provider.execute("SELECT * FROM test", fetchType=FetchType.FETCH_ONE)
        assert result == {"id": 1, "name": "a"}

    async def test_fetch_one_zero_rows_returns_none(self, provider: SQLinkProvider, monkeypatch):
        """Test that FETCH_ONE with zero rows returns None."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def fakeExecute(
            self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
        ) -> sqlink.QueryResult:
            return makeQueryResult(columns=["id"], rows=[])

        monkeypatch.setattr(FakeAsyncConnection, "execute", fakeExecute)

        result = await provider.execute("SELECT * FROM test", fetchType=FetchType.FETCH_ONE)
        assert result is None

    async def test_fetch_all_returns_list_of_dicts(self, provider: SQLinkProvider, monkeypatch):
        """Test that FETCH_ALL returns list of row dicts."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def fakeExecute(
            self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
        ) -> sqlink.QueryResult:
            return makeQueryResult(columns=["id", "name"], rows=[(1, "a"), (2, "b")])

        monkeypatch.setattr(FakeAsyncConnection, "execute", fakeExecute)

        result = await provider.execute("SELECT * FROM test", fetchType=FetchType.FETCH_ALL)
        assert result == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]

    async def test_zero_rows_returns_empty_list(self, provider: SQLinkProvider, monkeypatch):
        """Test that FETCH_ALL with zero rows returns empty list."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def fakeExecute(
            self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
        ) -> sqlink.QueryResult:
            return makeQueryResult(columns=["id"], rows=[])

        monkeypatch.setattr(FakeAsyncConnection, "execute", fakeExecute)

        result = await provider.execute("SELECT * FROM test", fetchType=FetchType.FETCH_ALL)
        assert result == []

    async def test_named_dict_passed_verbatim_after_conversion(self, provider: SQLinkProvider, monkeypatch):
        """Test that named dict is passed verbatim after convertContainerElementsToSQLite."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def fakeExecute(
            self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
        ) -> sqlink.QueryResult:
            assert params == {"flag": 1}
            return makeQueryResult(columns=[], rows=[])

        monkeypatch.setattr(FakeAsyncConnection, "execute", fakeExecute)

        await provider.execute("SELECT * FROM test WHERE flag = :flag", {"flag": True})

    async def test_no_params_empty_list_not_none(self, provider: SQLinkProvider, monkeypatch):
        """Test that no params results in empty list not None."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def fakeExecute(
            self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
        ) -> sqlink.QueryResult:
            assert params == []
            return makeQueryResult(columns=[], rows=[])

        monkeypatch.setattr(FakeAsyncConnection, "execute", fakeExecute)

        await provider.execute("SELECT 1")

    async def test_sqlink_error_propagates_unwrapped(self, provider: SQLinkProvider, monkeypatch):
        """Test that sqlink errors propagate unwrapped."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def errorExecute(
            self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
        ) -> sqlink.QueryResult:
            raise RuntimeError("sqlink error")

        monkeypatch.setattr(FakeAsyncConnection, "execute", errorExecute)

        with pytest.raises(RuntimeError, match="sqlink error"):
            await provider.execute("SELECT 1")


class TestUpsert:
    """Tests for upsert operation."""

    async def test_default_expressions_none_updates_all_non_conflict(self, provider: SQLinkProvider, monkeypatch):
        """Test that default updateExpressions=None updates all non-conflict columns."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def captureExecute(
            self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
        ) -> sqlink.QueryResult:
            normalizedSql = " ".join(sql.split())
            assert "excluded.name" in normalizedSql
            assert "excluded.value" in normalizedSql
            assert "excluded.id" not in normalizedSql
            return makeQueryResult(columns=[], rows=[])

        monkeypatch.setattr(FakeAsyncConnection, "execute", captureExecute)

        result = await provider.upsert(
            table="test", values={"id": 1, "name": "a", "value": 100}, conflictColumns=["id"]
        )
        assert result is True

    async def test_excluded_value_default_uses_column_name(self, provider: SQLinkProvider, monkeypatch):
        """Test that ExcludedValue() with no column uses the key name."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def captureExecute(
            self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
        ) -> sqlink.QueryResult:
            normalizedSql = " ".join(sql.split())
            assert "excluded.name" in normalizedSql
            return makeQueryResult(columns=[], rows=[])

        monkeypatch.setattr(FakeAsyncConnection, "execute", captureExecute)

        result = await provider.upsert(
            table="test",
            values={"id": 1, "name": "a"},
            conflictColumns=["id"],
            updateExpressions={"name": ExcludedValue()},
        )
        assert result is True

    async def test_excluded_value_custom_uses_custom_column(self, provider: SQLinkProvider, monkeypatch):
        """Test that ExcludedValue('other') uses the custom column name."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def captureExecute(
            self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
        ) -> sqlink.QueryResult:
            normalizedSql = " ".join(sql.split())
            assert "excluded.other" in normalizedSql
            return makeQueryResult(columns=[], rows=[])

        monkeypatch.setattr(FakeAsyncConnection, "execute", captureExecute)

        result = await provider.upsert(
            table="test",
            values={"id": 1, "name": "a"},
            conflictColumns=["id"],
            updateExpressions={"name": ExcludedValue("other")},
        )
        assert result is True

    async def test_string_expression_passes_raw(self, provider: SQLinkProvider, monkeypatch):
        """Test that string expressions pass through raw."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def captureExecute(
            self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
        ) -> sqlink.QueryResult:
            normalizedSql = " ".join(sql.split())
            assert "messages_count = messages_count + 1" in normalizedSql
            return makeQueryResult(columns=[], rows=[])

        monkeypatch.setattr(FakeAsyncConnection, "execute", captureExecute)

        result = await provider.upsert(
            table="test",
            values={"id": 1, "messages_count": 5},
            conflictColumns=["id"],
            updateExpressions={"messages_count": "messages_count + 1"},
        )
        assert result is True

    async def test_empty_expressions_dict_does_nothing(self, provider: SQLinkProvider, monkeypatch):
        """Test that empty updateExpressions={} results in DO NOTHING."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def captureExecute(
            self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
        ) -> sqlink.QueryResult:
            normalizedSql = " ".join(sql.split())
            assert "DO NOTHING" in normalizedSql
            return makeQueryResult(columns=[], rows=[])

        monkeypatch.setattr(FakeAsyncConnection, "execute", captureExecute)

        result = await provider.upsert(
            table="test", values={"id": 1, "name": "a"}, conflictColumns=["id"], updateExpressions={}
        )
        assert result is True

    async def test_multiple_conflict_columns_comma_joined(self, provider: SQLinkProvider, monkeypatch):
        """Test that multiple conflict columns are comma-joined."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def captureExecute(
            self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
        ) -> sqlink.QueryResult:
            normalizedSql = " ".join(sql.split())
            assert "ON CONFLICT(id, user_id)" in normalizedSql
            return makeQueryResult(columns=[], rows=[])

        monkeypatch.setattr(FakeAsyncConnection, "execute", captureExecute)

        result = await provider.upsert(
            table="test", values={"id": 1, "user_id": 2, "name": "a"}, conflictColumns=["id", "user_id"]
        )
        assert result is True

    async def test_values_converted_before_send(self, provider: SQLinkProvider, monkeypatch):
        """Test that values are converted before sending (bool->1)."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def captureExecute(
            self, sql: str, params: Optional[Any] = None, *, database: Optional[str] = None
        ) -> sqlink.QueryResult:
            assert params == {"id": 1, "active": 1}
            return makeQueryResult(columns=[], rows=[])

        monkeypatch.setattr(FakeAsyncConnection, "execute", captureExecute)

        result = await provider.upsert(table="test", values={"id": 1, "active": True}, conflictColumns=["id"])
        assert result is True


class TestIsReadOnly:
    """Tests for isReadOnly method."""

    async def test_access_ro_returns_true(self, provider: SQLinkProvider, monkeypatch):
        """Test that database with access='ro' returns True."""
        fake = FakeAsyncConnection()
        dbInfo = sqlink.DatabaseInfo(name="db", access="ro")
        fake.databasesResult = [dbInfo]

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        result = await provider.isReadOnly()
        assert result is True

    async def test_access_rw_returns_false(self, provider: SQLinkProvider, monkeypatch):
        """Test that database with access='rw' returns False."""
        fake = FakeAsyncConnection()
        dbInfo = sqlink.DatabaseInfo(name="db", access="rw")
        fake.databasesResult = [dbInfo]

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        result = await provider.isReadOnly()
        assert result is False

    async def test_missing_database_returns_true_fail_safe(self, provider: SQLinkProvider, monkeypatch):
        """Test that missing database returns True as fail-safe."""
        fake = FakeAsyncConnection()
        otherDb = sqlink.DatabaseInfo(name="other", access="rw")
        fake.databasesResult = [otherDb]

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        result = await provider.isReadOnly()
        assert result is True


class TestProviderHooks:
    """Tests for provider hook methods (sync tests)."""

    def test_apply_pagination_limit_only(self):
        """Test applyPagination with limit only."""
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")
        result = provider.applyPagination("SELECT * FROM test", limit=10)
        assert result == "SELECT * FROM test LIMIT 10"

    def test_apply_pagination_limit_and_offset(self):
        """Test applyPagination with limit and offset."""
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")
        result = provider.applyPagination("SELECT * FROM test", limit=10, offset=5)
        assert result == "SELECT * FROM test LIMIT 10 OFFSET 5"

    def test_apply_pagination_offset_zero_omits_offset(self):
        """Test applyPagination with offset=0 omits OFFSET clause."""
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")
        result = provider.applyPagination("SELECT * FROM test", limit=10, offset=0)
        assert result == "SELECT * FROM test LIMIT 10"

    def test_apply_pagination_limit_none_unchanged(self):
        """Test applyPagination with limit=None returns unchanged query."""
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")
        query = "SELECT * FROM test"
        result = provider.applyPagination(query, limit=None)
        assert result is query

    def test_get_text_type_always_text(self):
        """Test that getTextType always returns 'TEXT'."""
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")
        assert provider.getTextType() == "TEXT"
        assert provider.getTextType(maxLength=100) == "TEXT"

    def test_get_case_insensitive_comparison_exact_string(self):
        """Test getCaseInsensitiveComparison returns exact string."""
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")
        result = provider.getCaseInsensitiveComparison("name", "param")
        assert result == "LOWER(name) = LOWER(:param)"

    def test_get_like_comparison_exact_string(self):
        """Test getLikeComparison returns exact string."""
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")
        result = provider.getLikeComparison("name", "param")
        assert result == "LOWER(name) LIKE LOWER(:param)"


class TestBatchExecute:
    """Tests for batchExecute operation."""

    async def test_pairs_built_in_order_with_conversion(self, provider: SQLinkProvider, monkeypatch):
        """Test that query pairs are built in order with bool conversion."""
        fake = FakeAsyncConnection()
        capturedPairs: list[tuple[str, Any]] = []

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def captureBatch(
            self, queries: Sequence[tuple[str, Any]], *, database: Optional[str] = None
        ) -> Sequence[sqlink.QueryResult]:
            nonlocal capturedPairs
            capturedPairs = list(queries)
            return [makeQueryResult(columns=[], rows=[]) for _ in queries]

        monkeypatch.setattr(FakeAsyncConnection, "executeBatch", captureBatch)

        queries = [
            {"query": "INSERT INTO test VALUES (:id, :flag)", "params": {"id": 1, "flag": True}},
            {"query": "INSERT INTO test VALUES (:id, :flag)", "params": {"id": 2, "flag": False}},
            {"query": "INSERT INTO test VALUES (:id, :flag)", "params": {"id": 3, "flag": True}},
        ]

        parametrizedQueries = [ParametrizedQuery(query=q["query"], params=q["params"]) for q in queries]

        await provider.batchExecute(parametrizedQueries)

        # Verify pairs are built in order with bool->1 conversion
        # True -> 1, False -> 0
        assert capturedPairs == [
            ("INSERT INTO test VALUES (:id, :flag)", {"id": 1, "flag": 1}),
            ("INSERT INTO test VALUES (:id, :flag)", {"id": 2, "flag": 0}),
            ("INSERT INTO test VALUES (:id, :flag)", {"id": 3, "flag": 1}),
        ]

    async def test_mixed_fetch_types_drive_result_shapes(self, provider: SQLinkProvider, monkeypatch):
        """Test that per-query fetchType drives result shapes in a mixed batch."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def fakeBatch(
            self, queries: Sequence[tuple[str, Any]], *, database: Optional[str] = None
        ) -> Sequence[sqlink.QueryResult]:
            # Return results matching the query order
            return [
                makeQueryResult(columns=["id"], rows=[(1,)]),  # FETCH_ONE
                makeQueryResult(columns=["id"], rows=[(2,), (3,)]),  # FETCH_ALL
                makeQueryResult(columns=["id"], rows=[]),  # NO_FETCH
                makeQueryResult(columns=["id"], rows=[(4,), (5,), (6,)]),  # FETCH_ALL
            ]

        monkeypatch.setattr(FakeAsyncConnection, "executeBatch", fakeBatch)

        queries = [
            ParametrizedQuery(query="SELECT 1", params={}, fetchType=FetchType.FETCH_ONE),
            ParametrizedQuery(query="SELECT 2", params={}, fetchType=FetchType.FETCH_ALL),
            ParametrizedQuery(query="SELECT 3", params={}, fetchType=FetchType.NO_FETCH),
            ParametrizedQuery(query="SELECT 4", params={}, fetchType=FetchType.FETCH_ALL),
        ]

        results = await provider.batchExecute(queries)

        # Verify fetchType drives result shapes
        assert results == [{"id": 1}, [{"id": 2}, {"id": 3}], None, [{"id": 4}, {"id": 5}, {"id": 6}]]

        # TODO: Known truncation risk: zip() in batchExecute silently truncates if server returns
        # fewer results than queries. This is deliberately unpinned as the provider contract assumes
        # equal-length responses; a mismatch indicates a server bug. Adding length-check would require
        # raising an error, which changes provider behavior from "trust server" to "validate server".

    async def test_results_order_preserved(self, provider: SQLinkProvider, monkeypatch):
        """Test that results order matches query order."""
        fake = FakeAsyncConnection()

        async def connectReturning(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            return fake  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", connectReturning)

        async def fakeBatch(
            self, queries: Sequence[tuple[str, Any]], *, database: Optional[str] = None
        ) -> Sequence[sqlink.QueryResult]:
            # Return distinct results in order
            return [
                makeQueryResult(columns=["x"], rows=[(1,)]),
                makeQueryResult(columns=["x"], rows=[(2,)]),
                makeQueryResult(columns=["x"], rows=[(3,)]),
            ]

        monkeypatch.setattr(FakeAsyncConnection, "executeBatch", fakeBatch)

        queries = [
            ParametrizedQuery(query="SELECT 1", params={}, fetchType=FetchType.FETCH_ONE),
            ParametrizedQuery(query="SELECT 2", params={}, fetchType=FetchType.FETCH_ONE),
            ParametrizedQuery(query="SELECT 3", params={}, fetchType=FetchType.FETCH_ONE),
        ]

        results = await provider.batchExecute(queries)

        # Verify order preservation
        assert results == [{"x": 1}, {"x": 2}, {"x": 3}]


class TestProxyWiring:
    """Tests for proxy configuration wiring."""

    async def test_per_provider_proxy_with_enabled_global(self, monkeypatch):
        """Test that per-provider proxy with enabled global passes resolved URL to asyncConnect."""
        # Enable global proxy (minimal valid ProxyConfigDict)
        globalConfig: ProxyConfigDict = {
            "enabled": True,
            "type": ProxyType.HTTP,
            "address": "http://global:8080",
        }
        ProxyHelper.getInstance().setGlobalProxyConfig(globalConfig)

        capturedProxy: Any = _UNSET_SENTINEL

        async def captureConnect(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            nonlocal capturedProxy
            capturedProxy = proxy
            return FakeAsyncConnection()  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", captureConnect)

        proxyConfig: ProxyConfigDict = {
            "enabled": True,
            "type": ProxyType.HTTP,
            "address": "http://per-service:9090",
        }

        # use-proxy=True is required to opt the provider into proxying; without
        # it, fromDict(useProxy=False) forces ProxyType.NONE (lib/proxy/__init__.py).
        provider = SQLinkProvider(
            url="http://fake",
            user="u",
            password="secret",
            database="db",
            proxy=proxyConfig,
            **{"use-proxy": True},  # type: ignore[arg-type]
        )

        try:
            await provider.connect()

            # Per-service proxy should win when enabled
            assert capturedProxy == "http://per-service:9090"
        finally:
            # Restore global disabled state
            ProxyHelper.getInstance().setGlobalProxyConfig({"enabled": False})

    async def test_global_disabled_passes_none_explicitly(self, monkeypatch):
        """Test that global disabled results in proxy=None passed explicitly."""
        capturedProxy: Any = _UNSET_SENTINEL

        async def captureConnect(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            nonlocal capturedProxy
            capturedProxy = proxy
            return FakeAsyncConnection()  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", captureConnect)

        # Global is disabled by autouse fixture; no per-service proxy
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")

        await provider.connect()

        # Should pass None explicitly (not empty string, not omitted)
        assert capturedProxy is None

    async def test_lazy_resolution_picks_up_late_global_config(self, monkeypatch):
        """Test that lazy resolution picks up global config enabled after construction."""
        # Start with global disabled (minimal valid ProxyConfigDict)
        disabledConfig: ProxyConfigDict = {"enabled": False}
        ProxyHelper.getInstance().setGlobalProxyConfig(disabledConfig)

        capturedProxy: Any = _UNSET_SENTINEL

        async def captureConnect(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            nonlocal capturedProxy
            capturedProxy = proxy
            return FakeAsyncConnection()  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", captureConnect)

        # Construct provider while global is disabled. use-proxy=True with no
        # proxy dict opts the provider into proxying without a per-provider
        # override, so getCombined() inherits whatever global config is set at
        # connect() time (lazy resolution).
        provider = SQLinkProvider(
            url="http://fake",
            user="u",
            password="secret",
            database="db",
            **{"use-proxy": True},  # type: ignore[arg-type]
        )

        try:
            # Enable global proxy AFTER construction (lazy resolution regression shape)
            enabledConfig: ProxyConfigDict = {
                "enabled": True,
                "type": ProxyType.HTTP,
                "address": "http://late:8080",
            }
            ProxyHelper.getInstance().setGlobalProxyConfig(enabledConfig)

            await provider.connect()

            # Should pick up the late global config
            assert capturedProxy == "http://late:8080"
        finally:
            # Restore global disabled state
            ProxyHelper.getInstance().setGlobalProxyConfig({"enabled": False})


class TestErrorPaths:
    """Tests for error handling in connect lifecycle."""

    async def test_async_connect_raises_propagates_and_leaves_none(self, monkeypatch):
        """Test that asyncConnect raises, propagates, and leaves _connection None."""

        async def errorConnect(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            raise RuntimeError("connection failed")

        monkeypatch.setattr("sqlink.asyncConnect", errorConnect)

        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")

        with pytest.raises(RuntimeError, match="connection failed"):
            await provider.connect()

        # Connection slot must remain None (no poisoned state)
        assert provider._connection is None

    async def test_failed_connect_then_successful_retry_works(self, monkeypatch):
        """Test that failed connect followed by successful retry works."""
        callCount = 0

        async def flakyConnect(
            url: str,
            *,
            username: str,
            password: str,
            database: str,
            timeout: float,
            autoRefresh: bool,
            proxy: Optional[str] = None,
        ) -> sqlink.AsyncConnection:
            nonlocal callCount
            callCount += 1
            if callCount == 1:
                raise RuntimeError("first attempt fails")
            return FakeAsyncConnection()  # type: ignore[return-value]

        monkeypatch.setattr("sqlink.asyncConnect", flakyConnect)

        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")

        # First connect fails
        with pytest.raises(RuntimeError, match="first attempt fails"):
            await provider.connect()
        assert provider._connection is None

        # Second connect succeeds
        await provider.connect()
        assert provider._connection is not None


class TestVectorDefaults:
    """Tests for vector-related method defaults inherited from BaseSQLProvider."""

    async def test_is_vector_search_supported_false(self):
        """Test that isVectorSearchSupported returns False by default."""
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")

        result = await provider.isVectorSearchSupported()
        assert result is False

    async def test_vector_search_raises_not_implemented(self):
        """Test that vectorSearch raises NotImplementedError."""
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")

        with pytest.raises(NotImplementedError, match="SQLinkProvider does not support native vector search"):
            await provider.vectorSearch(
                table="test",
                vectorColumn="vec",
                returnColumns=["id"],
                queryVector=b"\x00" * 4,
                k=10,
            )

    async def test_list_tables_raises_not_implemented(self):
        """Test that listTables raises NotImplementedError."""
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")

        with pytest.raises(NotImplementedError, match="SQLinkProvider does not support table listing"):
            await provider.listTables("%")

    async def test_create_vector_table_raises_not_implemented(self):
        """Test that createVectorTable raises NotImplementedError."""
        provider = SQLinkProvider(url="http://fake", user="u", password="secret", database="db")

        with pytest.raises(NotImplementedError, match="SQLinkProvider does not support vector table creation"):
            await provider.createVectorTable(
                tableName="test_vec",
                columns=[
                    VectorColumnDef(name="id", columnType=VectorColumnType.TEXT),
                    VectorColumnDef(name="vec", columnType=VectorColumnType.VECTOR),
                ],
            )


class TestDependencySurface:
    """Tests for sqlink dependency surface tripwire."""

    def test_sqlink_asyncconnection_has_required_methods(self):
        """Assert sqlink.AsyncConnection has required methods (tripwire for unpinned dep).

        This test provides early warning if the unpinned sqlink dependency
        (via git in requirements.direct.txt) drifts in a way that breaks
        our interface assumptions. The dependency is deliberately unpinned
        because we track a git reference; this tripwire catches breaking
        changes before they reach production.

        Raises:
            AssertionError: If sqlink.AsyncConnection lacks required methods.
        """
        # AsyncConnection interface
        assert hasattr(sqlink.AsyncConnection, "execute")
        assert hasattr(sqlink.AsyncConnection, "executeBatch")
        assert hasattr(sqlink.AsyncConnection, "databases")
        assert hasattr(sqlink.AsyncConnection, "close")

        # Module-level interface
        assert hasattr(sqlink, "asyncConnect")

        # QueryResult interface (properties, not methods)
        assert hasattr(sqlink.QueryResult, "columns")
        assert hasattr(sqlink.QueryResult, "rows")
