"""Tests for SandboxManager singleton skeleton (lib.sandbox.manager).

Covers:
- getInstance() returns the same object on repeated calls (singleton identity).
- getInstance() without config on first call raises ValueError.
- getInstance(config) returns a SandboxManager instance.
- Every public async method raises NotImplementedError with the method name.
- Every public method is an async coroutine (asyncio.iscoroutinefunction).
- Calling __init__ twice does not re-initialize (the initialized guard).
- getInstance(config) stores the config on the instance.
"""

import asyncio

import pytest

from lib.sandbox.config import SandboxConfig, StorageConfig
from lib.sandbox.manager import SandboxManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _resetSingleton():
    """Reset the SandboxManager singleton before and after each test."""
    SandboxManager._instance = None
    SandboxManager._configInstance = None
    yield
    SandboxManager._instance = None
    SandboxManager._configInstance = None


def _makeConfig() -> SandboxConfig:
    """Create a minimal SandboxConfig for testing."""
    return SandboxConfig(storage=StorageConfig(rootDir="/tmp/sandbox-test"))


# ---------------------------------------------------------------------------
# Singleton identity tests
# ---------------------------------------------------------------------------


class TestSingletonIdentity:
    """Verify that SandboxManager behaves as a singleton."""

    async def test_getInstanceReturnsSameObject(self) -> None:
        """Two calls to getInstance() return the same object."""
        config = _makeConfig()
        SandboxManager.injectConfig(config)
        first = SandboxManager.getInstance()
        second = SandboxManager.getInstance()
        assert first is second

    async def test_getInstanceWithoutConfigRaises(self) -> None:
        """Calling getInstance() without config before initialisation raises RuntimeError."""
        with pytest.raises(RuntimeError, match="SandboxConfig not injected"):
            SandboxManager.getInstance()

    async def test_getInstanceWithConfigReturnsInstance(self) -> None:
        """Calling getInstance(config) returns a SandboxManager instance."""
        config = _makeConfig()
        SandboxManager.injectConfig(config)
        manager = SandboxManager.getInstance()
        assert isinstance(manager, SandboxManager)

    async def test_getInstanceWithConfigAfterInitIgnoresConfig(self) -> None:
        """After initialisation, passing a different config does not replace the stored config."""
        config1 = _makeConfig()
        SandboxManager.injectConfig(config1)
        first = SandboxManager.getInstance()
        # Calling getInstance with a config should be ignored (no longer supported)
        second = SandboxManager.getInstance()
        assert first is second
        assert first._config is config1


# ---------------------------------------------------------------------------
# Initialisation guard tests
# ---------------------------------------------------------------------------


class TestInitGuard:
    """Verify that __init__ does not re-initialise on subsequent calls."""

    async def test_initGuardPreventsReinitialization(self) -> None:
        """Calling __init__ a second time does not overwrite the stored config."""
        config = _makeConfig()
        SandboxManager.injectConfig(config)
        manager = SandboxManager.getInstance()
        assert manager._config is config
        # Calling __init__ directly should be a no-op due to the initialized guard
        manager.__init__()
        assert manager._config is config

    async def test_configStoredOnInit(self) -> None:
        """The config passed to getInstance() is stored on the instance."""
        config = _makeConfig()
        SandboxManager.injectConfig(config)
        manager = SandboxManager.getInstance()
        assert manager._config is config


# ---------------------------------------------------------------------------
# Async method tests
# ---------------------------------------------------------------------------


# Collect all public async methods that still raise NotImplementedError.
# Session lifecycle methods (createSession, getSessionInfo, getSessionUsage,
# listSessions, touchSession, dropSession) are now implemented and tested
# separately in test_manager_sessions.py.
# collectGarbage is now implemented and tested in test_gc.py.
# healthcheck, shutdown, recover are now implemented and tested in
# test_manager_ops.py.
_NOT_IMPLEMENTED_METHODS: list[tuple[str, tuple[object, ...], dict[str, object]]] = []


@pytest.mark.parametrize(
    "methodName,args,kwargs",
    _NOT_IMPLEMENTED_METHODS,
    ids=[m[0] for m in _NOT_IMPLEMENTED_METHODS],
)
class TestNotImplementedMethods:
    """Every public async method must raise NotImplementedError with its name."""

    async def test_raisesNotImplementedError(
        self,
        methodName: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> None:
        """Calling the method raises NotImplementedError containing the method name."""
        config = _makeConfig()
        SandboxManager.injectConfig(config)
        manager = SandboxManager.getInstance()
        method = getattr(manager, methodName)
        with pytest.raises(NotImplementedError, match=methodName):
            await method(*args, **kwargs)


# ---------------------------------------------------------------------------
# Async coroutine tests
# ---------------------------------------------------------------------------


# All public methods that should be async coroutines.
_ASYNC_METHOD_NAMES = [name for name, _, _ in _NOT_IMPLEMENTED_METHODS]


@pytest.mark.parametrize("methodName", _ASYNC_METHOD_NAMES, ids=_ASYNC_METHOD_NAMES)
class TestAsyncMethods:
    """Every public method must be an async coroutine function."""

    def test_isAsyncCoroutineFunction(self, methodName: str) -> None:
        """The method is recognised as a coroutine function by asyncio."""
        config = _makeConfig()
        SandboxManager.injectConfig(config)
        manager = SandboxManager.getInstance()
        method = getattr(manager, methodName)
        assert asyncio.iscoroutinefunction(method), f"{methodName} is not a coroutine function"
