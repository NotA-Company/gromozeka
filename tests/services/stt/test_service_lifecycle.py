"""Tests for STTService lifecycle (Phase 2 — singleton, init, close).

Covers: singleton identity, disabled no-op, enabled provider construction
with proxy resolution, idempotent initialization, isEnabled after failed
init, full provider kwarg forwarding, aclose behaviour, unknown-provider
validation, provider ValueError propagation, statsStorage forwarding,
partial Object-Storage config rejection, and default-off invariant
(v1.1 Phase 5).
"""

from __future__ import annotations

from typing import Generator
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from internal.services.stt.service import STT_PROVIDERS_MAP, STTService
from lib.stats.stats_storage import StatsStorage


def _validSttConfig() -> dict:
    """Return a valid [stt] config dict for testing.

    Returns:
        dict: Config dict with enabled=true and valid credentials.
    """
    return {
        "enabled": True,
        "provider": "yandex-speechkit",
        "use-proxy": False,
        "api-key": "test-api-key",
        "folder-id": "test-folder-id",
        "model": "general",
        "language": "ru-RU",
        "max-source-bytes": 67108864,
        "max-concurrency": 2,
        "request-timeout-seconds": 30.0,
        "operation-budget-seconds": 2400.0,
        "poll-interval-seconds": 3.0,
        "max-poll-interval-seconds": 20.0,
        "max-result-bytes": 5242880,
        "chat-ratelimiter-queue": "stt-chat",
        "global-ratelimiter-queue": "stt-global",
    }


@pytest.fixture(autouse=True)
def resetSttServiceSingleton() -> Generator[None, None, None]:
    """Reset STTService singleton between tests to prevent state leakage.

    Yields:
        None: Fixture runs before and after each test.
    """
    STTService._instance = None

    yield

    STTService._instance = None


def _makeConfigManager(sttConfig: dict) -> Mock:
    """Build a mock ConfigManager that returns the given stt config.

    Args:
        sttConfig: The [stt] section dict to return from getSttConfig.

    Returns:
        Mock: Mocked ConfigManager with getSttConfig configured.
    """
    mockCm = Mock()
    mockCm.getSttConfig = Mock(return_value=sttConfig)
    return mockCm


# -----------------------------------------------------------------------
# 1. Singleton identity
# -----------------------------------------------------------------------


class TestGetInstanceIsSingleton:
    """Two getInstance() calls return the same object; reset works."""

    def test_getInstanceIsSingleton(self) -> None:
        """Two getInstance() calls return the same object."""
        a = STTService.getInstance()
        b = STTService.getInstance()
        assert a is b

    def test_resetClearsInstance(self) -> None:
        """Resetting _instance yields a new object on next getInstance."""
        a = STTService.getInstance()
        STTService._instance = None
        b = STTService.getInstance()
        assert a is not b


# -----------------------------------------------------------------------
# 2. Disabled → no provider, isEnabled() False, aclose() no-op
# -----------------------------------------------------------------------


class TestDisabledConstructsNoProvider:
    """When enabled=false, no provider is built and aclose is a no-op."""

    def test_isEnabledFalse(self) -> None:
        """isEnabled() returns False when enabled=false."""
        svc = STTService.getInstance()
        svc.initialize(_makeConfigManager({"enabled": False}))
        assert svc.isEnabled() is False

    def test_providerIsNone(self) -> None:
        """_provider is None when disabled."""
        svc = STTService.getInstance()
        svc.initialize(_makeConfigManager({"enabled": False}))
        assert svc._provider is None

    async def test_acloseNoException(self) -> None:
        """aclose() does not raise when disabled."""
        svc = STTService.getInstance()
        svc.initialize(_makeConfigManager({"enabled": False}))
        await svc.aclose()  # should not raise


# -----------------------------------------------------------------------
# 3. Enabled + valid → provider constructed with resolved proxy
# -----------------------------------------------------------------------


class TestEnabledValidConstructsProviderWithResolvedProxy:
    """When enabled=true with valid config, provider is constructed."""

    @patch("internal.services.stt.service.ProxyService")
    def test_providerConstructed(self, mockProxyServiceCls: Mock) -> None:
        """Provider is constructed when enabled with valid config."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        mockProviderCls = MagicMock()
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc = STTService.getInstance()
            svc.initialize(_makeConfigManager(_validSttConfig()))

        assert svc.isEnabled() is True
        mockProviderCls.assert_called_once()
        callKwargs = mockProviderCls.call_args[1]
        assert callKwargs["apiKey"] == "test-api-key"
        assert callKwargs["folderId"] == "test-folder-id"

    @patch("internal.services.stt.service.ProxyService")
    def test_resolveProxyCalledWithLabel(self, mockProxyServiceCls: Mock) -> None:
        """ProxyService.resolveProxy is called with label 'stt'."""
        mockProxyService = MagicMock()
        mockResolvedProxy = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=mockResolvedProxy)
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        configManager = _makeConfigManager(_validSttConfig())
        mockProviderCls = MagicMock()
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc = STTService.getInstance()
            svc.initialize(configManager)

        mockProxyService.resolveProxy.assert_called_once_with(configManager.getSttConfig(), "stt")

    @patch("internal.services.stt.service.ProxyService")
    def test_proxyConfigPassedToProvider(self, mockProxyServiceCls: Mock) -> None:
        """The resolved ProxyConfig is passed as provider's proxyConfig kwarg."""
        mockProxyService = MagicMock()
        mockResolvedProxy = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=mockResolvedProxy)
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        mockProviderCls = MagicMock()
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc = STTService.getInstance()
            svc.initialize(_makeConfigManager(_validSttConfig()))

        callKwargs = mockProviderCls.call_args[1]
        assert callKwargs["proxyConfig"] is mockResolvedProxy


# -----------------------------------------------------------------------
# 4. Enabled + unknown provider → ValueError (service-level validation)
# -----------------------------------------------------------------------


class TestEnabledUnknownProviderRaisesValueError:
    """Unknown provider name raises ValueError."""

    def test_unknownProvider(self) -> None:
        """provider='foo' raises ValueError."""
        config = _validSttConfig()
        config["provider"] = "foo"
        svc = STTService.getInstance()
        with pytest.raises(ValueError, match="unknown provider"):
            svc.initialize(_makeConfigManager(config))


# -----------------------------------------------------------------------
# 5. initialize propagates provider ValueError (e.g. missing apiKey)
# -----------------------------------------------------------------------


class TestInitializePropagatesProviderValidationError:
    """initialize propagates ValueError from the provider constructor."""

    @patch("internal.services.stt.service.ProxyService")
    def test_initializePropagatesProviderValidationError(self, mockProxyServiceCls: Mock) -> None:
        """Provider constructor raising ValueError (missing apiKey) propagates through initialize."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        mockProviderCls = MagicMock(side_effect=ValueError("apiKey must be a non-empty string"))
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            config = _validSttConfig()
            config["api-key"] = ""
            svc = STTService.getInstance()
            with pytest.raises(ValueError, match="apiKey"):
                svc.initialize(_makeConfigManager(config))


# -----------------------------------------------------------------------
# 6. aclose closes provider exactly once
# -----------------------------------------------------------------------


class TestAcloseClosesProviderOnceWhenEnabled:
    """aclose() delegates to provider.aclose() exactly once."""

    @patch("internal.services.stt.service.ProxyService")
    async def test_acloseCallsProviderAcloseOnce(self, mockProxyServiceCls: Mock) -> None:
        """aclose() calls provider.aclose() exactly once."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        mockProvider = MagicMock()
        mockProvider.aclose = AsyncMock()
        mockProviderCls = MagicMock(return_value=mockProvider)
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc = STTService.getInstance()
            svc.initialize(_makeConfigManager(_validSttConfig()))

        await svc.aclose()
        mockProvider.aclose.assert_awaited_once()

    @patch("internal.services.stt.service.ProxyService")
    async def test_acloseSwallowsException(self, mockProxyServiceCls: Mock) -> None:
        """aclose() never raises even if provider.aclose() raises."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        mockProvider = MagicMock()
        mockProvider.aclose = AsyncMock(side_effect=RuntimeError("boom"))
        mockProviderCls = MagicMock(return_value=mockProvider)
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc = STTService.getInstance()
            svc.initialize(_makeConfigManager(_validSttConfig()))

        # Should not raise
        await svc.aclose()


# -----------------------------------------------------------------------
# 7. No circular import
# -----------------------------------------------------------------------


class TestNoCircularImport:
    """import main succeeds (covered by make lint, explicit assertion)."""

    def test_importMain(self) -> None:
        """import main does not raise."""
        import main  # noqa: F401


# -----------------------------------------------------------------------
# 8. isEnabled() is False after a failed initialize
# -----------------------------------------------------------------------


class TestIsEnabledFalseAfterFailedInitialize:
    """If enabled=true but validation fails, isEnabled() stays False."""

    def test_isEnabledFalseAfterFailedInitialize(self) -> None:
        """isEnabled() returns False and _provider is None after ValueError."""
        config = _validSttConfig()
        config["provider"] = "nonexistent"
        svc = STTService.getInstance()
        with pytest.raises(ValueError, match="unknown provider"):
            svc.initialize(_makeConfigManager(config))
        assert svc.isEnabled() is False
        assert svc._provider is None


# -----------------------------------------------------------------------
# 9. Full provider kwarg forwarding with value + type
# -----------------------------------------------------------------------


class TestEnabledValidForwardsAllProviderKwargs:
    """All provider kwargs are forwarded with correct value and type."""

    @patch("internal.services.stt.service.ProxyService")
    def test_enabledValidForwardsAllProviderKwargs(self, mockProxyServiceCls: Mock) -> None:
        """All provider constructor kwargs are forwarded with correct values and types."""
        mockProxyService = MagicMock()
        mockResolvedProxy = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=mockResolvedProxy)
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        svc = STTService.getInstance()
        config = _validSttConfig()
        config["request-timeout-seconds"] = 45.0
        config["operation-budget-seconds"] = 300.0
        config["poll-interval-seconds"] = 5.0
        config["max-poll-interval-seconds"] = 25.0
        config["max-result-bytes"] = 10485760

        mockProviderCls = MagicMock()
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc.initialize(_makeConfigManager(config))

        callKwargs = mockProviderCls.call_args[1]

        assert callKwargs["apiKey"] == "test-api-key"
        assert isinstance(callKwargs["apiKey"], str)

        assert callKwargs["folderId"] == "test-folder-id"
        assert isinstance(callKwargs["folderId"], str)

        assert callKwargs["model"] == "general"
        assert isinstance(callKwargs["model"], str)

        assert callKwargs["language"] == "ru-RU"
        assert isinstance(callKwargs["language"], str)

        assert callKwargs["proxyConfig"] is mockResolvedProxy

        assert callKwargs["requestTimeoutSeconds"] == 45.0
        assert isinstance(callKwargs["requestTimeoutSeconds"], float)

        assert callKwargs["operationBudgetSeconds"] == 300.0
        assert isinstance(callKwargs["operationBudgetSeconds"], float)

        assert callKwargs["pollIntervalSeconds"] == 5.0
        assert isinstance(callKwargs["pollIntervalSeconds"], float)

        assert callKwargs["maxPollIntervalSeconds"] == 25.0
        assert isinstance(callKwargs["maxPollIntervalSeconds"], float)

        assert callKwargs["maxResultBytes"] == 10485760
        assert isinstance(callKwargs["maxResultBytes"], int)


# -----------------------------------------------------------------------
# 10. initialize is idempotent
# -----------------------------------------------------------------------


class TestInitializeIsIdempotent:
    """Second initialize() call is a no-op; provider constructed once."""

    @patch("internal.services.stt.service.ProxyService")
    def test_initializeIsIdempotent(self, mockProxyServiceCls: Mock) -> None:
        """Provider is constructed exactly once despite two initialize calls."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        mockProviderCls = MagicMock()
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc = STTService.getInstance()
            svc.initialize(_makeConfigManager(_validSttConfig()))
            svc.initialize(_makeConfigManager(_validSttConfig()))

        assert mockProviderCls.call_count == 1


# -----------------------------------------------------------------------
# 11. v1.1 Phase 5 — statsStorage is forwarded to the provider
# -----------------------------------------------------------------------


class TestStatsStorageForwardedToProvider:
    """statsStorage kwarg is passed through to the provider constructor."""

    @patch("internal.services.stt.service.ProxyService")
    def test_statsStorageNoneByDefault(self, mockProxyServiceCls: Mock) -> None:
        """When statsStorage is not passed, provider receives statsStorage=None."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        mockProviderCls = MagicMock()
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc = STTService.getInstance()
            svc.initialize(_makeConfigManager(_validSttConfig()))

        callKwargs = mockProviderCls.call_args[1]
        assert callKwargs["statsStorage"] is None

    @patch("internal.services.stt.service.ProxyService")
    def test_statsStorageForwarded(self, mockProxyServiceCls: Mock) -> None:
        """When statsStorage is passed, provider receives the same object."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        fakeStats = MagicMock(spec=StatsStorage)
        mockProviderCls = MagicMock()
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc = STTService.getInstance()
            svc.initialize(_makeConfigManager(_validSttConfig()), statsStorage=fakeStats)

        callKwargs = mockProviderCls.call_args[1]
        assert callKwargs["statsStorage"] is fakeStats


# -----------------------------------------------------------------------
# 12. v1.1 Phase 5 — partial Object-Storage config → ValueError
# -----------------------------------------------------------------------


class TestPartialObjectStorageConfigRaisesValueError:
    """Provider raises ValueError when OS config is partial (all-or-nothing)."""

    @patch("internal.services.stt.service.ProxyService")
    def test_partialOsConfigBucketWithoutKeysRaises(self, mockProxyServiceCls: Mock) -> None:
        """object-storage-bucket set without keys → ValueError propagated."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        config = _validSttConfig()
        config["object-storage-bucket"] = "test-bucket"
        # keys intentionally omitted

        mockProviderCls = MagicMock(side_effect=ValueError("objectStorageKeyId is required when bucket is set"))
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc = STTService.getInstance()
            with pytest.raises(ValueError, match="objectStorageKeyId"):
                svc.initialize(_makeConfigManager(config))

    @patch("internal.services.stt.service.ProxyService")
    def test_partialOsConfigBucketAndKeyIdOnlyRaises(self, mockProxyServiceCls: Mock) -> None:
        """object-storage-bucket + key-id without key-secret → ValueError propagated."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        config = _validSttConfig()
        config["object-storage-bucket"] = "test-bucket"
        config["object-storage-key-id"] = "key-id"

        mockProviderCls = MagicMock(side_effect=ValueError("objectStorageKeySecret is required when bucket is set"))
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc = STTService.getInstance()
            with pytest.raises(ValueError, match="objectStorageKeySecret"):
                svc.initialize(_makeConfigManager(config))


# -----------------------------------------------------------------------
# 13. v1.1 Phase 5 — inline-only when no OS config (provider._objectStorage is None)
# -----------------------------------------------------------------------


class TestInlineOnlyDefaultNoObjectStorage:
    """With no OS keys, the provider receives no OS kwargs and is inline-only."""

    @patch("internal.services.stt.service.ProxyService")
    def test_noOsKeysNoObjectStorageKwargs(self, mockProxyServiceCls: Mock) -> None:
        """Provider receives no objectStorage* kwargs when OS is not configured."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        mockProviderCls = MagicMock()
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc = STTService.getInstance()
            svc.initialize(_makeConfigManager(_validSttConfig()))

        callKwargs = mockProviderCls.call_args[1]
        assert "objectStorageBucket" not in callKwargs
        assert "objectStoragePrefix" not in callKwargs
        assert "objectStorageKeyId" not in callKwargs
        assert "objectStorageKeySecret" not in callKwargs


# -----------------------------------------------------------------------
# 14. v1.1 Phase 5 — full OS config initializes without ValueError
# -----------------------------------------------------------------------


class TestFullOsConfigInitializes:
    """Full Object-Storage config initializes without ValueError; statsStorage=None."""

    @patch("internal.services.stt.service.ProxyService")
    def test_fullOsConfigWithStatsStorageNone(self, mockProxyServiceCls: Mock) -> None:
        """Full OS config → no ValueError, provider receives statsStorage=None."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        config = _validSttConfig()
        config["object-storage-bucket"] = "test-bucket"
        config["object-storage-prefix"] = "stt/"
        config["object-storage-key-id"] = "test-key-id"
        config["object-storage-key-secret"] = "test-key-secret"

        mockProviderCls = MagicMock()
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc = STTService.getInstance()
            svc.initialize(_makeConfigManager(config))

        assert svc.isEnabled() is True
        callKwargs = mockProviderCls.call_args[1]
        assert callKwargs["statsStorage"] is None


# -----------------------------------------------------------------------
# 15. v1.1 Phase 5 — default-off invariant (00-defaults config)
# -----------------------------------------------------------------------


class TestDefaultOffInvariant:
    """With shipped 00-defaults config (no OS keys),
    initialize succeeds, provider is inline-only, statsStorage is None."""

    @patch("internal.services.stt.service.ProxyService")
    def test_defaultOffInitializeSucceeds(self, mockProxyServiceCls: Mock) -> None:
        """Default-off config initializes without error, inline-only, statsStorage=None."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        # Mirrors the 00-defaults/stt.toml keys (no OS keys)
        config = _validSttConfig()

        mockProviderCls = MagicMock()
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc = STTService.getInstance()
            svc.initialize(_makeConfigManager(config))

        assert svc.isEnabled() is True
        callKwargs = mockProviderCls.call_args[1]
        # No OS kwargs forwarded
        assert "objectStorageBucket" not in callKwargs
        # statsStorage is None (not passed → defaults to None)
        assert callKwargs["statsStorage"] is None


# -----------------------------------------------------------------------
# 16. v1.1 Phase 5 — max-inline-bytes forwarded to provider
# -----------------------------------------------------------------------


class TestMaxInlineBytesForwarded:
    """max-inline-bytes is forwarded to the provider via kebabToCamelCase spread."""

    @patch("internal.services.stt.service.ProxyService")
    def test_maxInlineBytesForwarded(self, mockProxyServiceCls: Mock) -> None:
        """max-inline-bytes=41943040 is forwarded as maxInlineBytes to the provider."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        config = _validSttConfig()
        config["max-inline-bytes"] = 41943040

        mockProviderCls = MagicMock()
        with patch.dict(STT_PROVIDERS_MAP, {"yandex-speechkit": mockProviderCls}):
            svc = STTService.getInstance()
            svc.initialize(_makeConfigManager(config))

        callKwargs = mockProviderCls.call_args[1]
        assert callKwargs["maxInlineBytes"] == 41943040
