"""Unit tests for lib/proxy/__init__.py — proxy configuration using class-based API."""

import unittest.mock
from typing import Generator

import pytest

from lib.proxy import HealthCheckType, ProxyConfig, ProxyConfigDict, ProxyHelper, ProxyType


@pytest.fixture
def resetProxyHelper() -> Generator[ProxyHelper, None, None]:
    """Reset ProxyHelper singleton and set a default global proxy config.

    Sets the global config to ``{enabled: True}`` so that the kill-switch in
    ``getCombined()`` is open by default. Individual tests that need a different
    global state can call ``setGlobalProxyConfig()`` to override it.

    Yields:
        The ProxyHelper singleton instance.
    """
    ProxyHelper._instance = None
    helper = ProxyHelper.getInstance()
    helper.setGlobalProxyConfig({"enabled": True})
    yield helper
    ProxyHelper._instance = None


class TestProxyType:
    """Tests for ProxyType StrEnum members and string comparison."""

    def test_members(self) -> None:
        """Verify that all three members exist with correct string values.

        Args:
            None

        Returns:
            None
        """
        assert ProxyType.NONE == "none"
        assert ProxyType.HTTP == "http"
        assert ProxyType.SOCKS5 == "socks5"

    def test_string_equality(self) -> None:
        """ProxyType.HTTP should compare equal to the string \"http\".

        Args:
            None

        Returns:
            None
        """
        assert ProxyType.HTTP == "http"
        assert ProxyType.NONE == "none"

    def test_string_inequality(self) -> None:
        """Different ProxyType values should not compare equal.

        Args:
            None

        Returns:
            None
        """
        assert ProxyType.HTTP != ProxyType.SOCKS5
        assert ProxyType.HTTP != "socks5"


class TestProxyConfigFromDict:
    """Tests for ProxyConfig.fromDict() classmethod."""

    def test_useProxyFalse_returnsNONE(self) -> None:
        """When useProxy is False, the config type must be ProxyType.NONE regardless of input.

        Args:
            None

        Returns:
            None
        """
        result = ProxyConfig.fromDict({}, useProxy=False)
        assert result.type == ProxyType.NONE
        assert result.address == ""
        assert result.user == ""
        assert result.password == ""

    def test_useProxyTrue_emptyDict_returnsNoneType(self) -> None:
        """When useProxy is True but the dict is empty, proxyType is None (no default).

        Args:
            None

        Returns:
            None
        """
        result = ProxyConfig.fromDict({}, useProxy=True)
        assert result.type is None
        assert result.address is None
        assert result.user is None
        assert result.password is None

    def test_useProxyTrue_withAddress_returnsConfigWithGivenAddress(self) -> None:
        """When useProxy is True and address is provided, address is stored.

        Note: fromDict does NOT default missing type to HTTP.
        That default happens in getCombined().

        Args:
            None

        Returns:
            None
        """
        result = ProxyConfig.fromDict({"address": "http://p:80"}, useProxy=True)
        assert result.type is None
        assert result.address == "http://p:80"
        assert result.user is None
        assert result.password is None

    def test_missingType_defaultsToNone(self) -> None:
        """When the \"type\" key is absent, fromDict returns proxyType=None.

        The fallback to HTTP happens later in getCombined(), not in fromDict.

        Args:
            None

        Returns:
            None
        """
        result = ProxyConfig.fromDict({"address": "http://p:80"}, useProxy=True)
        assert result.type is None

    def test_credentials_preserved(self) -> None:
        """User and password from the dict are stored as-is.

        Args:
            None

        Returns:
            None
        """
        result = ProxyConfig.fromDict(
            {"address": "http://p:80", "user": "myuser", "password": "mypass"},
            useProxy=True,
        )
        assert result.address == "http://p:80"
        assert result.user == "myuser"
        assert result.password == "mypass"

    def test_useProxyDefault_enabledTrue_usesEnabled(self) -> None:
        """When useProxy is not given and enabled is True, proxy is enabled.

        Args:
            None

        Returns:
            None
        """
        result = ProxyConfig.fromDict({"enabled": True, "type": ProxyType.HTTP, "address": "http://p:80"})
        assert result.type == ProxyType.HTTP
        assert result.address == "http://p:80"

    def test_useProxyDefault_enabledFalse_usesNONE(self) -> None:
        """When useProxy is not given and enabled is False, type is preserved and enabled is False.

        The ``enabled`` flag is independent of ``proxyType`` — ``enabled=False``
        means "inherit from global in getCombined()", not that the proxy type
        is forced to NONE.

        Args:
            None

        Returns:
            None
        """
        result = ProxyConfig.fromDict({"enabled": False, "type": ProxyType.HTTP, "address": "http://p:80"})
        assert result.type == ProxyType.HTTP
        assert result.enabled is False

    def test_disabledWithEmptyAddress_doesNotRaiseValueError(self) -> None:
        """Regression: ``enabled=False`` with empty address no longer raises ValueError.

        Previously, the combination ``{"enabled": False, "type": HTTP, "address": ""}``
        caused ProxyConfig.__init__ to validate the address before checking
        ``enabled``, resulting in a ValueErrror at startup. The fix removed
        the premature validation, so the constructor now accepts this input.

        Args:
            None

        Returns:
            None
        """
        result = ProxyConfig.fromDict({"enabled": False, "type": ProxyType.HTTP, "address": ""})
        # No ValueError raised
        assert result.type == ProxyType.HTTP
        assert result.enabled is False
        assert result.address == ""


class TestProxyConfigFromServiceConfig:
    """Tests for ProxyConfig.fromServiceConfig() classmethod."""

    def test_noUseProxy_returnsNONE(self) -> None:
        """When the dict has no \"use-proxy\" key, proxy is disabled (type NONE).

        Args:
            None

        Returns:
            None
        """
        result = ProxyConfig.fromServiceConfig({})
        assert result.type == ProxyType.NONE
        assert result.address == ""

    def test_useProxyFalse_returnsNONE(self) -> None:
        """When \"use-proxy\" is False, proxy is disabled (type NONE).

        Args:
            None

        Returns:
            None
        """
        result = ProxyConfig.fromServiceConfig({"use-proxy": False})
        assert result.type == ProxyType.NONE

    def test_useProxyTrue_noProxySection_returnsNoneType(self) -> None:
        """When \"use-proxy\" is True but no \"proxy\" sub-section, proxyType is None.

        The address/user/password come from the empty default dict.

        Args:
            None

        Returns:
            None
        """
        result = ProxyConfig.fromServiceConfig({"use-proxy": True})
        assert result.type is None
        assert result.address is None
        assert result.user is None
        assert result.password is None

    def test_useProxyTrue_withProxySection_returnsConfigFromSection(self) -> None:
        """When \"use-proxy\" is True and \"proxy\" section has address, it is stored.

        Args:
            None

        Returns:
            None
        """
        result = ProxyConfig.fromServiceConfig({"use-proxy": True, "proxy": {"address": "http://s:80"}})
        assert result.type is None
        assert result.address == "http://s:80"

    def test_useProxyTrue_withProxyType_returnsSpecifiedType(self) -> None:
        """When \"proxy\" section specifies a type, it is stored directly.

        Args:
            None

        Returns:
            None
        """
        result = ProxyConfig.fromServiceConfig(
            {"use-proxy": True, "proxy": {"type": ProxyType.SOCKS5, "address": "socks5://s:1080"}}
        )
        assert result.type == ProxyType.SOCKS5
        assert result.address == "socks5://s:1080"

    def test_useProxyTrue_noExplicitEnabled_returnsEnabledFalse(self) -> None:
        """When ``use-proxy`` is True but the proxy sub-section has no ``enabled``
        key, ``enabled`` defaults to False.

        This is intentional: ``fromServiceConfig`` reads ``enabled`` from the
        ``proxy`` sub-dict via ``fromDict``, and ``fromDict`` uses
        ``data.get("enabled") is True``. The ``use-proxy`` flag controls
        whether the config is treated as a service override (True) or a
        global config (None), but does NOT set ``enabled`` directly.

        When ``enabled`` is False:
          - ``getCombined()`` ignores the service fields and returns a copy of
            the global config instead.
          - Put ``enabled: true`` in the ``proxy`` sub-section to use
            service-level proxy settings.

        Args:
            None

        Returns:
            None
        """
        result = ProxyConfig.fromServiceConfig(
            {"use-proxy": True, "proxy": {"type": ProxyType.SOCKS5, "address": "socks5://service:1080"}}
        )
        assert result.type == ProxyType.SOCKS5
        assert result.address == "socks5://service:1080"
        assert result.enabled is False


class TestProxyConfigGetProxyURL:
    """Tests for ProxyConfig.getProxyURL() method.

    getProxyURL() calls getCombined() internally, so ProxyHelper must be
    configured with a global proxy config before calling it.
    """

    def test_httpNoAuth(self, resetProxyHelper: ProxyHelper) -> None:
        """When proxy has no credentials, return the address unchanged.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        resetProxyHelper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
        config = ProxyConfig(ProxyType.HTTP, "http://p:80")
        assert config.getProxyURL() == "http://p:80"

    def test_httpWithAuth(self, resetProxyHelper: ProxyHelper) -> None:
        """When proxy has credentials, embed them in the URL.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        resetProxyHelper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
        config = ProxyConfig(ProxyType.HTTP, "http://p:80", "u", "pw")
        assert config.getProxyURL() == "http://u:pw@p:80"

    def test_socks5WithAuth(self, resetProxyHelper: ProxyHelper) -> None:
        """SOCKS5 proxy with credentials embeds them in the URL.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        resetProxyHelper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
        config = ProxyConfig(ProxyType.SOCKS5, "socks5://p:1080", "u", "pw")
        assert config.getProxyURL() == "socks5://u:pw@p:1080"

    def test_maskPassword(self, resetProxyHelper: ProxyHelper) -> None:
        """When maskPassword=True, the password is replaced with REDACTED.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        resetProxyHelper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
        config = ProxyConfig(ProxyType.HTTP, "http://p:80", "u", "pw")
        assert config.getProxyURL(maskPassword=True) == "http://u:REDACTED@p:80"

    def test_noneType_returnsNone(self, resetProxyHelper: ProxyHelper) -> None:
        """When combined proxy type is NONE, getProxyURL returns None.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        resetProxyHelper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
        config = ProxyConfig(ProxyType.NONE, "")
        assert config.getProxyURL() is None

    def test_emptyAddress_acceptedInConstructor(self, resetProxyHelper: ProxyHelper) -> None:
        """Non-NONE type with empty address is accepted by the constructor.

        The constructor no longer validates that non-NONE proxy types have a
        non-empty address. Validation now happens in ``_buildProxyUrl``, which
        checks that the address has a parseable hostname. This means a
        ``ProxyConfig`` with type=HTTP and address="" can be created and
        passed to ``getCombined()`` without errors — the error only surfaces
        when ``getProxyURL()`` or ``toKwargs()`` calls ``_buildProxyUrl``.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        resetProxyHelper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
        # Constructor no longer raises — empty address is accepted
        config = ProxyConfig(ProxyType.HTTP, "")
        assert config.type == ProxyType.HTTP
        assert config.address == ""

        # The error now surfaces in _buildProxyUrl, which getProxyURL calls
        with pytest.raises(ValueError, match="missing or unparseable"):
            config.getProxyURL()

    def test_specialCharsEncoded(self, resetProxyHelper: ProxyHelper) -> None:
        """Special characters in user/password are percent-encoded in the URL.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        resetProxyHelper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
        config = ProxyConfig(ProxyType.HTTP, "http://p:80", "u", "p@ss")
        assert config.getProxyURL() == "http://u:p%40ss@p:80"

    def test_noExplicitPort_omitsPort(self, resetProxyHelper: ProxyHelper) -> None:
        """When address has no explicit port, port is omitted from the URL.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        resetProxyHelper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
        config = ProxyConfig(ProxyType.HTTP, "http://proxy", "u", "pw")
        assert config.getProxyURL() == "http://u:pw@proxy"

    def test_colonInPassword_encoded(self, resetProxyHelper: ProxyHelper) -> None:
        """Password with ':' is percent-encoded.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        resetProxyHelper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
        config = ProxyConfig(ProxyType.HTTP, "http://p:80", "u", "p:ss")
        assert config.getProxyURL() == "http://u:p%3Ass@p:80"


class TestProxyConfigToKwargs:
    """Tests for ProxyConfig.toKwargs() method.

    toKwargs() calls getCombined() internally, so ProxyHelper must be
    configured with a global proxy config before calling it.
    """

    def test_noneType_returnsEmptyDict(self, resetProxyHelper: ProxyHelper) -> None:
        """NONE proxy type returns an empty ProxyKwargs dict.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        resetProxyHelper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
        config = ProxyConfig(ProxyType.NONE, "")
        result = config.toKwargs()
        assert result == {}
        assert isinstance(result, dict)

    def test_httpProxy_returnsProxyKwarg(self, resetProxyHelper: ProxyHelper) -> None:
        """HTTP proxy type returns a dict with 'proxy' key containing the URL.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        resetProxyHelper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
        config = ProxyConfig(ProxyType.HTTP, "http://p:80")
        result = config.toKwargs()
        assert result == {"proxy": "http://p:80"}

    async def test_socks5Proxy_returnsTransportKwarg(self, resetProxyHelper: ProxyHelper) -> None:
        """SOCKS5 proxy type returns a dict with 'transport' key.

        Requires httpx_socks to be importable; otherwise the test is skipped.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        try:
            from httpx_socks import AsyncProxyTransport  # pyright: ignore[reportMissingImports]
        except ImportError:
            pytest.skip("httpx_socks not installed")

        resetProxyHelper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
        config = ProxyConfig(ProxyType.SOCKS5, "socks5://p:1080")
        result = config.toKwargs()
        assert "transport" in result
        transport = result["transport"]
        assert isinstance(transport, AsyncProxyTransport)

    async def test_socks5MissingHttpxSocks_raisesImportError(self, resetProxyHelper: ProxyHelper) -> None:
        """When httpx_socks is not importable and type is SOCKS5, raise ImportError.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        resetProxyHelper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
        config = ProxyConfig(ProxyType.SOCKS5, "socks5://p:1080")
        with unittest.mock.patch("lib.proxy._HTTPX_SOCKS_AVAILABLE", False):
            with pytest.raises(ImportError, match="httpx-socks"):
                config.toKwargs()


class TestProxyHelper:
    """Tests for ProxyHelper singleton and global config storage."""

    def test_singleton(self) -> None:
        """getInstance() returns the same instance on repeated calls.

        Args:
            None

        Returns:
            None
        """
        ProxyHelper._instance = None
        h1 = ProxyHelper.getInstance()
        h2 = ProxyHelper.getInstance()
        assert h1 is h2

    def test_setAndGet_roundtrip(self, resetProxyHelper: ProxyHelper) -> None:
        """Setting a global config and reading it back via getGlobalProxyConfig.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        resetProxyHelper.setGlobalProxyConfig(
            {"enabled": True, "type": ProxyType.HTTP, "address": "http://p:80", "user": "u", "password": "pw"}
        )
        result = resetProxyHelper.getGlobalProxyConfig()
        assert result.type == ProxyType.HTTP
        assert result.address == "http://p:80"
        assert result.user == "u"
        assert result.password == "pw"

    def test_getBeforeSet_raisesTypeError(self) -> None:
        """Calling getGlobalProxyConfig before setGlobalProxyConfig raises TypeError.

        Resets the singleton and calls getGlobalProxyConfig() without
        setting a config first, verifying the guard clause.

        Args:
            None

        Returns:
            None
        """
        ProxyHelper._instance = None
        helper = ProxyHelper.getInstance()
        with pytest.raises(TypeError, match="setGlobalProxyConfig"):
            helper.getGlobalProxyConfig()

    def test_setThenReset_works(self, resetProxyHelper: ProxyHelper) -> None:
        """Overwriting global config with a new dict works correctly.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        resetProxyHelper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.HTTP, "address": "http://first:80"})
        resetProxyHelper.setGlobalProxyConfig(
            {"enabled": True, "type": ProxyType.SOCKS5, "address": "socks5://second:1080"}
        )
        result = resetProxyHelper.getGlobalProxyConfig()
        assert result.type == ProxyType.SOCKS5
        assert result.address == "socks5://second:1080"


class TestProxyConfigGetCombined:
    """Tests for ProxyConfig.getCombined() — merging service config with global config."""

    GLOBAL: ProxyConfigDict = {
        "enabled": True,
        "type": ProxyType.HTTP,
        "address": "http://global:80",
        "user": "gu",
        "password": "gpw",
    }

    def _setupGlobal(self, helper: ProxyHelper) -> None:
        """Configure ProxyHelper with the standard GLOBAL dict.

        Args:
            helper: The ProxyHelper instance.

        Returns:
            None
        """
        helper.setGlobalProxyConfig(self.GLOBAL)

    def test_serviceProxy_usesServiceAddress(self, resetProxyHelper: ProxyHelper) -> None:
        """When the service config has an address, it takes precedence over global.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        self._setupGlobal(resetProxyHelper)
        serviceConfig = ProxyConfig.fromServiceConfig(
            {"use-proxy": True, "proxy": {"enabled": True, "address": "http://s:80"}}
        )
        combined = serviceConfig.getCombined()
        assert combined.address == "http://s:80"

    def test_serviceProxy_inheritsGlobalType(self, resetProxyHelper: ProxyHelper) -> None:
        """When the service config has no type, inherit HTTP from global config.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        self._setupGlobal(resetProxyHelper)
        serviceConfig = ProxyConfig.fromServiceConfig({"use-proxy": True, "proxy": {"address": "http://s:80"}})
        combined = serviceConfig.getCombined()
        assert combined.type == ProxyType.HTTP

    def test_serviceProxy_overridesGlobalType(self, resetProxyHelper: ProxyHelper) -> None:
        """When the service config specifies a type, it overrides the global type.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        self._setupGlobal(resetProxyHelper)
        serviceConfig = ProxyConfig.fromServiceConfig(
            {"use-proxy": True, "proxy": {"enabled": True, "type": ProxyType.SOCKS5, "address": "socks5://s:1080"}}
        )
        combined = serviceConfig.getCombined()
        assert combined.type == ProxyType.SOCKS5
        assert combined.address == "socks5://s:1080"

    def test_serviceProxy_inheritsCredentials(self, resetProxyHelper: ProxyHelper) -> None:
        """When the service config has no user/password, inherit from global.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        self._setupGlobal(resetProxyHelper)
        serviceConfig = ProxyConfig.fromServiceConfig({"use-proxy": True, "proxy": {"address": "http://s:80"}})
        combined = serviceConfig.getCombined()
        assert combined.user == "gu"
        assert combined.password == "gpw"

    def test_serviceProxy_overridesCredentials(self, resetProxyHelper: ProxyHelper) -> None:
        """When the service config specifies user/password, they override global.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        self._setupGlobal(resetProxyHelper)
        serviceConfig = ProxyConfig.fromServiceConfig(
            {
                "use-proxy": True,
                "proxy": {"enabled": True, "address": "http://s:80", "user": "su", "password": "spw"},
            }
        )
        combined = serviceConfig.getCombined()
        assert combined.user == "su"
        assert combined.password == "spw"

    def test_serviceProxy_emptyAddress_fallsToGlobal(self, resetProxyHelper: ProxyHelper) -> None:
        """When the service proxy address is empty, fall through to global address.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        self._setupGlobal(resetProxyHelper)
        serviceConfig = ProxyConfig.fromServiceConfig({"use-proxy": True, "proxy": {"address": ""}})
        combined = serviceConfig.getCombined()
        assert combined.address == "http://global:80"

    def test_serviceProxy_emptyAddress_inheritsGlobalCredentials(self, resetProxyHelper: ProxyHelper) -> None:
        """When service has empty address and no credentials, inherit everything from global.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        self._setupGlobal(resetProxyHelper)
        serviceConfig = ProxyConfig.fromServiceConfig({"use-proxy": True, "proxy": {"address": ""}})
        combined = serviceConfig.getCombined()
        assert combined.type == ProxyType.HTTP
        assert combined.address == "http://global:80"
        assert combined.user == "gu"
        assert combined.password == "gpw"

    def test_serviceUseProxyTrue_noProxySection_usesGlobal(self, resetProxyHelper: ProxyHelper) -> None:
        """When use-proxy is True but no proxy sub-section, use global config.

        The service config has proxyType=None, address="", user=None, password=None.
        getCombined should fall through to global for all fields.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        self._setupGlobal(resetProxyHelper)
        serviceConfig = ProxyConfig.fromServiceConfig({"use-proxy": True})
        combined = serviceConfig.getCombined()
        assert combined.type == ProxyType.HTTP
        assert combined.address == "http://global:80"
        assert combined.user == "gu"
        assert combined.password == "gpw"

    def test_serviceUseProxyFalse_returnsNONE(self, resetProxyHelper: ProxyHelper) -> None:
        """When use-proxy is False, combined config falls to NONE despite global being enabled.

        Args:
            resetProxyHelper: Fixture setting up ProxyHelper singleton.

        Returns:
            None
        """
        self._setupGlobal(resetProxyHelper)
        serviceConfig = ProxyConfig.fromServiceConfig({"use-proxy": False})
        combined = serviceConfig.getCombined()
        assert combined.type == ProxyType.NONE
        assert combined.address == ""


class TestProxyLifecycleConfig:
    """Tests for proxy lifecycle configuration types and merge logic."""

    def test_fromDictWithLifecycle(self) -> None:
        """fromDict() converts kebab-case lifecycle keys to camelCase and casts healthCheckType to enum."""
        data: ProxyConfigDict = {
            "enabled": True,
            "type": ProxyType.SOCKS5,
            "address": "socks5://127.0.0.1:1080",
            "lifecycle": {
                "start-command": ["ssh", "-D", "1080"],
                "stop-command": ["pkill", "-f", "ssh"],
                "health-check-type": "url",
                "health-check-url": "https://example.com",
                "health-check-interval": 10,
            },
        }
        config = ProxyConfig.fromDict(data)
        assert config.lifecycle is not None
        assert config.lifecycle["startCommand"] == ["ssh", "-D", "1080"]
        assert config.lifecycle["stopCommand"] == ["pkill", "-f", "ssh"]
        assert config.lifecycle["healthCheckType"] is HealthCheckType.URL
        assert config.lifecycle["healthCheckUrl"] == "https://example.com"
        assert config.lifecycle["healthCheckInterval"] == 10

    def test_fromDictLifecycleNotDict(self) -> None:
        """fromDict() silently ignores a non-dict lifecycle value."""
        data: ProxyConfigDict = {
            "enabled": True,
            "type": ProxyType.HTTP,
            "address": "http://proxy:8080",
            "lifecycle": "not-a-dict",  # type: ignore[typeddict-item]
        }
        config = ProxyConfig.fromDict(data)  # type: ignore[arg-type]
        assert config.lifecycle is None

    def test_fromDictEmptyLifecycle(self) -> None:
        """fromDict() preserves an empty lifecycle dict as {}."""
        data: ProxyConfigDict = {
            "enabled": True,
            "type": ProxyType.HTTP,
            "address": "http://proxy:8080",
            "lifecycle": {},
        }
        config = ProxyConfig.fromDict(data)
        assert config.lifecycle == {}

    def test_fromDictInvalidHealthCheckType(self) -> None:
        """fromDict() falls back to NONE for an unrecognized health-check-type."""
        data: ProxyConfigDict = {
            "enabled": True,
            "type": ProxyType.HTTP,
            "address": "http://proxy:8080",
            "lifecycle": {"health-check-type": "invalid_value"},
        }
        config = ProxyConfig.fromDict(data)
        assert config.lifecycle is not None
        assert config.lifecycle["healthCheckType"] is HealthCheckType.NONE

    def test_copyPreservesLifecycle(self) -> None:
        """copy() creates a shallow copy of the lifecycle dict."""
        original = ProxyConfig(
            proxyType=ProxyType.SOCKS5,
            address="socks5://127.0.0.1:1080",
            lifecycle={
                "startCommand": ["ssh"],
                "healthCheckType": HealthCheckType.COMMAND,
                "healthCheckCommand": ["nc", "-z", "127.0.0.1", "1080"],
                "healthCheckInterval": 5,
            },
        )
        copied = original.copy()
        assert copied.lifecycle is not None
        assert copied.lifecycle is not original.lifecycle  # different dict object
        assert copied.lifecycle["startCommand"] == ["ssh"]
        assert copied.lifecycle["healthCheckType"] is HealthCheckType.COMMAND

    def test_getCombinedMasterKillSwitchNoLifecycle(self, resetProxyHelper: ProxyHelper) -> None:
        """When global proxy is disabled, getCombined() returns NONE with no lifecycle."""
        resetProxyHelper.setGlobalProxyConfig({"enabled": False, "type": ProxyType.HTTP, "address": "http://p:8080"})
        service = ProxyConfig(proxyType=ProxyType.SOCKS5, address="socks5://127.0.0.1:1080", enabled=True)
        combined = service.getCombined()
        assert combined.type == ProxyType.NONE
        assert combined.lifecycle is None

    def test_getCombinedServiceDisabledInheritsGlobalLifecycle(self, resetProxyHelper: ProxyHelper) -> None:
        """When service proxy is disabled, getCombined() inherits global lifecycle."""
        resetProxyHelper.setGlobalProxyConfig(
            {
                "enabled": True,
                "type": ProxyType.HTTP,
                "address": "http://p:8080",
                "lifecycle": {
                    "start-command": ["global-start"],
                    "health-check-type": "command",
                    "health-check-command": ["nc"],
                },
            }
        )
        service = ProxyConfig(proxyType=ProxyType.SOCKS5, address="socks5://127.0.0.1:1080", enabled=False)
        combined = service.getCombined()
        assert combined.lifecycle is not None
        assert combined.lifecycle["startCommand"] == ["global-start"]

    def test_getCombinedServiceLifecycleOverridesGlobal(self, resetProxyHelper: ProxyHelper) -> None:
        """When both enabled and service has lifecycle, service lifecycle wins."""
        resetProxyHelper.setGlobalProxyConfig(
            {
                "enabled": True,
                "type": ProxyType.HTTP,
                "address": "http://p:8080",
                "lifecycle": {"start-command": ["global-start"]},
            }
        )
        service = ProxyConfig(
            proxyType=ProxyType.SOCKS5,
            address="socks5://127.0.0.1:1080",
            enabled=True,
            lifecycle={"startCommand": ["service-start"]},
        )
        combined = service.getCombined()
        assert combined.lifecycle is not None
        assert combined.lifecycle["startCommand"] == ["service-start"]

    def test_getCombinedServiceNoLifecycleInheritsGlobal(self, resetProxyHelper: ProxyHelper) -> None:
        """When both enabled and service has no lifecycle, global lifecycle is inherited."""
        resetProxyHelper.setGlobalProxyConfig(
            {
                "enabled": True,
                "type": ProxyType.HTTP,
                "address": "http://p:8080",
                "lifecycle": {"start-command": ["global-start"]},
            }
        )
        service = ProxyConfig(
            proxyType=ProxyType.SOCKS5,
            address="socks5://127.0.0.1:1080",
            enabled=True,
            lifecycle=None,
        )
        combined = service.getCombined()
        assert combined.lifecycle is not None
        assert combined.lifecycle["startCommand"] == ["global-start"]

    def test_reprWithLifecycle(self) -> None:
        """__repr__() shows lifecycle=present when lifecycle is set."""
        config = ProxyConfig(proxyType=ProxyType.HTTP, address="http://p:8080", lifecycle={})
        r = repr(config)
        assert "lifecycle=present" in r

    def test_reprWithoutLifecycle(self) -> None:
        """__repr__() shows lifecycle=None when lifecycle is not set."""
        config = ProxyConfig(proxyType=ProxyType.HTTP, address="http://p:8080")
        r = repr(config)
        assert "lifecycle=None" in r


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
