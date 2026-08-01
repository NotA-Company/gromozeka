"""Tests for STTService lifecycle (Phase 2 — singleton, init, close).

Covers: singleton identity, disabled no-op, enabled provider construction
with proxy resolution, validation errors (missing creds, unresolved vars,
unknown provider, non-positive caps), idempotent initialization,
isEnabled after failed init, full provider kwarg forwarding, cross-field
poll-delay validation, and aclose behaviour.
"""

from __future__ import annotations

import re
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from internal.services.stt.service import STTService


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
        "max-duration-seconds": 600,
        "max-transcript-chars": 48000,
        "max-concurrency": 2,
        "admission-timeout": 20,
        "request-timeout": 30,
        "operation-timeout": 180,
        "poll-initial-delay": 2,
        "poll-max-delay": 10,
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


def _makeDatabase() -> Mock:
    """Build a mock Database handle.

    Returns:
        Mock: Mocked Database instance.
    """
    return Mock()


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
        svc.initialize(_makeConfigManager({"enabled": False}), _makeDatabase())
        assert svc.isEnabled() is False

    def test_providerIsNone(self) -> None:
        """_provider is None when disabled."""
        svc = STTService.getInstance()
        svc.initialize(_makeConfigManager({"enabled": False}), _makeDatabase())
        assert svc._provider is None

    async def test_acloseNoException(self) -> None:
        """aclose() does not raise when disabled."""
        svc = STTService.getInstance()
        svc.initialize(_makeConfigManager({"enabled": False}), _makeDatabase())
        await svc.aclose()  # should not raise


# -----------------------------------------------------------------------
# 3. Enabled + valid → provider constructed with resolved proxy
# -----------------------------------------------------------------------


class TestEnabledValidConstructsProviderWithResolvedProxy:
    """When enabled=true with valid config, provider is constructed."""

    @patch("internal.services.stt.service.YandexSpeechKitProvider")
    @patch("internal.services.stt.service.ProxyService")
    def test_providerConstructed(self, mockProxyServiceCls: Mock, mockProviderCls: Mock) -> None:
        """Provider is constructed when enabled with valid config."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        svc = STTService.getInstance()
        svc.initialize(_makeConfigManager(_validSttConfig()), _makeDatabase())

        assert svc.isEnabled() is True
        mockProviderCls.assert_called_once()
        callKwargs = mockProviderCls.call_args[1]
        assert callKwargs["apiKey"] == "test-api-key"
        assert callKwargs["folderId"] == "test-folder-id"

    @patch("internal.services.stt.service.YandexSpeechKitProvider")
    @patch("internal.services.stt.service.ProxyService")
    def test_resolveProxyCalledWithLabel(self, mockProxyServiceCls: Mock, mockProviderCls: Mock) -> None:
        """ProxyService.resolveProxy is called with label 'stt'."""
        mockProxyService = MagicMock()
        mockResolvedProxy = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=mockResolvedProxy)
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        configManager = _makeConfigManager(_validSttConfig())
        svc = STTService.getInstance()
        svc.initialize(configManager, _makeDatabase())

        mockProxyService.resolveProxy.assert_called_once_with(configManager.getSttConfig(), "stt")

    @patch("internal.services.stt.service.YandexSpeechKitProvider")
    @patch("internal.services.stt.service.ProxyService")
    def test_proxyConfigPassedToProvider(self, mockProxyServiceCls: Mock, mockProviderCls: Mock) -> None:
        """The resolved ProxyConfig is passed as provider's proxyConfig kwarg."""
        mockProxyService = MagicMock()
        mockResolvedProxy = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=mockResolvedProxy)
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        svc = STTService.getInstance()
        svc.initialize(_makeConfigManager(_validSttConfig()), _makeDatabase())

        callKwargs = mockProviderCls.call_args[1]
        assert callKwargs["proxyConfig"] is mockResolvedProxy


# -----------------------------------------------------------------------
# 4. Enabled + missing api-key → ValueError
# -----------------------------------------------------------------------


class TestEnabledMissingCredsRaisesValueError:
    """When enabled=true but api-key is empty/missing, ValueError."""

    def test_missingApiKey(self) -> None:
        """Empty api-key raises ValueError."""
        config = _validSttConfig()
        config["api-key"] = ""
        svc = STTService.getInstance()
        with pytest.raises(ValueError, match="api-key"):
            svc.initialize(_makeConfigManager(config), _makeDatabase())

    def test_missingFolderId(self) -> None:
        """Empty folder-id raises ValueError."""
        config = _validSttConfig()
        config["folder-id"] = ""
        svc = STTService.getInstance()
        with pytest.raises(ValueError, match="folder-id"):
            svc.initialize(_makeConfigManager(config), _makeDatabase())


# -----------------------------------------------------------------------
# 5. Enabled + unresolved ${...} → ValueError
# -----------------------------------------------------------------------


class TestEnabledUnresolvedEnvVarRaisesValueError:
    """Literal ${...} placeholder in credentials raises ValueError."""

    def test_unresolvedApiKey(self) -> None:
        """api-key with unresolved ${VAR} raises ValueError."""
        config = _validSttConfig()
        config["api-key"] = "${YC_API_KEY}"
        svc = STTService.getInstance()
        with pytest.raises(ValueError, match="unresolved"):
            svc.initialize(_makeConfigManager(config), _makeDatabase())

    def test_unresolvedFolderId(self) -> None:
        """folder-id with unresolved ${VAR} raises ValueError."""
        config = _validSttConfig()
        config["folder-id"] = "${YC_FOLDER_ID}"
        svc = STTService.getInstance()
        with pytest.raises(ValueError, match="unresolved"):
            svc.initialize(_makeConfigManager(config), _makeDatabase())


# -----------------------------------------------------------------------
# 6. Enabled + unknown provider → ValueError
# -----------------------------------------------------------------------


class TestEnabledUnknownProviderRaisesValueError:
    """Unknown provider name raises ValueError."""

    def test_unknownProvider(self) -> None:
        """provider='foo' raises ValueError."""
        config = _validSttConfig()
        config["provider"] = "foo"
        svc = STTService.getInstance()
        with pytest.raises(ValueError, match="unknown provider"):
            svc.initialize(_makeConfigManager(config), _makeDatabase())


# -----------------------------------------------------------------------
# 7. Enabled + non-positive cap → ValueError
# -----------------------------------------------------------------------


class TestEnabledNonPositiveCapRaisesValueError:
    """Non-positive numeric caps raise ValueError."""

    @pytest.mark.parametrize(
        "key,value",
        [
            ("max-source-bytes", 0),
            ("max-source-bytes", -1),
            ("max-duration-seconds", 0),
            ("max-transcript-chars", -1),
            ("max-concurrency", 0),
            ("admission-timeout", 0),
            ("request-timeout", 0),
            ("operation-timeout", -1),
            ("poll-initial-delay", 0),
            ("poll-max-delay", 0),
            ("max-result-bytes", 0),
        ],
    )
    def test_nonPositiveCap(self, key: str, value: int) -> None:
        """Non-positive value for {key} raises ValueError."""
        config = _validSttConfig()
        config[key] = value
        svc = STTService.getInstance()
        with pytest.raises(ValueError, match=re.escape(key)):
            svc.initialize(_makeConfigManager(config), _makeDatabase())


# -----------------------------------------------------------------------
# 8. aclose closes provider exactly once
# -----------------------------------------------------------------------


class TestAcloseClosesProviderOnceWhenEnabled:
    """aclose() delegates to provider.aclose() exactly once."""

    @patch("internal.services.stt.service.YandexSpeechKitProvider")
    @patch("internal.services.stt.service.ProxyService")
    async def test_acloseCallsProviderAcloseOnce(self, mockProxyServiceCls: Mock, mockProviderCls: Mock) -> None:
        """aclose() calls provider.aclose() exactly once."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        mockProvider = MagicMock()
        mockProvider.aclose = AsyncMock()
        mockProviderCls.return_value = mockProvider

        svc = STTService.getInstance()
        svc.initialize(_makeConfigManager(_validSttConfig()), _makeDatabase())

        await svc.aclose()
        mockProvider.aclose.assert_awaited_once()

    @patch("internal.services.stt.service.YandexSpeechKitProvider")
    @patch("internal.services.stt.service.ProxyService")
    async def test_acloseSwallowsException(self, mockProxyServiceCls: Mock, mockProviderCls: Mock) -> None:
        """aclose() never raises even if provider.aclose() raises."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        mockProvider = MagicMock()
        mockProvider.aclose = AsyncMock(side_effect=RuntimeError("boom"))
        mockProviderCls.return_value = mockProvider

        svc = STTService.getInstance()
        svc.initialize(_makeConfigManager(_validSttConfig()), _makeDatabase())

        # Should not raise
        await svc.aclose()


# -----------------------------------------------------------------------
# 9. No circular import
# -----------------------------------------------------------------------


class TestNoCircularImport:
    """import main succeeds (covered by make lint, explicit assertion)."""

    def test_importMain(self) -> None:
        """import main does not raise."""
        import main  # noqa: F401


# -----------------------------------------------------------------------
# 10. isEnabled() is False after a failed initialize (I1)
# -----------------------------------------------------------------------


class TestIsEnabledFalseAfterFailedInitialize:
    """If enabled=true but validation fails, isEnabled() stays False."""

    def test_isEnabledFalseAfterFailedInitialize(self) -> None:
        """isEnabled() returns False and _provider is None after ValueError."""
        config = _validSttConfig()
        config["api-key"] = "${UNRESOLVED}"
        svc = STTService.getInstance()
        with pytest.raises(ValueError, match="unresolved"):
            svc.initialize(_makeConfigManager(config), _makeDatabase())
        assert svc.isEnabled() is False
        assert svc._provider is None


# -----------------------------------------------------------------------
# 11. Full provider kwarg forwarding with value + type (I2)
# -----------------------------------------------------------------------


class TestEnabledValidForwardsAllProviderKwargs:
    """All 10 provider kwargs are forwarded with correct value and type."""

    @patch("internal.services.stt.service.YandexSpeechKitProvider")
    @patch("internal.services.stt.service.ProxyService")
    def test_enabledValidForwardsAllProviderKwargs(self, mockProxyServiceCls: Mock, mockProviderCls: Mock) -> None:
        """All provider constructor kwargs have correct value and type."""
        mockProxyService = MagicMock()
        mockResolvedProxy = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=mockResolvedProxy)
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        svc = STTService.getInstance()
        config = _validSttConfig()
        config["request-timeout"] = 45
        config["operation-timeout"] = 300
        config["poll-initial-delay"] = 3
        config["poll-max-delay"] = 20
        config["max-result-bytes"] = 10485760
        svc.initialize(_makeConfigManager(config), _makeDatabase())

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
        # proxyConfig type checked via identity, not isinstance (it's a Mock).

        assert callKwargs["requestTimeoutSeconds"] == 45.0
        assert isinstance(callKwargs["requestTimeoutSeconds"], float)

        assert callKwargs["operationBudgetSeconds"] == 300.0
        assert isinstance(callKwargs["operationBudgetSeconds"], float)

        assert callKwargs["pollIntervalSeconds"] == 3.0
        assert isinstance(callKwargs["pollIntervalSeconds"], float)

        assert callKwargs["maxPollIntervalSeconds"] == 20.0
        assert isinstance(callKwargs["maxPollIntervalSeconds"], float)

        assert callKwargs["maxResultBytes"] == 10485760
        assert isinstance(callKwargs["maxResultBytes"], int)


# -----------------------------------------------------------------------
# 12. Cross-field: poll-max-delay < poll-initial-delay → ValueError (R1)
# -----------------------------------------------------------------------


class TestEnabledPollMaxBelowInitialRaisesValueError:
    """poll-max-delay < poll-initial-delay raises ValueError."""

    def test_enabledPollMaxBelowInitialRaisesValueError(self) -> None:
        """poll-max-delay < poll-initial-delay raises ValueError."""
        config = _validSttConfig()
        config["poll-initial-delay"] = 20
        config["poll-max-delay"] = 10
        svc = STTService.getInstance()
        with pytest.raises(ValueError, match="poll-max-delay"):
            svc.initialize(_makeConfigManager(config), _makeDatabase())


# -----------------------------------------------------------------------
# 13. initialize is idempotent (R2)
# -----------------------------------------------------------------------


class TestInitializeIsIdempotent:
    """Second initialize() call is a no-op; provider constructed once."""

    @patch("internal.services.stt.service.YandexSpeechKitProvider")
    @patch("internal.services.stt.service.ProxyService")
    def test_initializeIsIdempotent(self, mockProxyServiceCls: Mock, mockProviderCls: Mock) -> None:
        """Provider is constructed exactly once despite two initialize calls."""
        mockProxyService = MagicMock()
        mockProxyService.resolveProxy = Mock(return_value=MagicMock())
        mockProxyServiceCls.getInstance = Mock(return_value=mockProxyService)

        svc = STTService.getInstance()
        svc.initialize(_makeConfigManager(_validSttConfig()), _makeDatabase())
        svc.initialize(_makeConfigManager(_validSttConfig()), _makeDatabase())

        assert mockProviderCls.call_count == 1
