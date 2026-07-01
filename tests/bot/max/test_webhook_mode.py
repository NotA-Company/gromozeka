"""Tests for MaxBotApplication webhook-receiver config gating.

These tests verify that ``MaxBotApplication._runPolling()`` reads the
``[webhook-receiver]`` config block correctly and branches accordingly:

- whether the local receiver URL/token are forwarded to ``MaxBotClient``;
- whether ``setWebhook`` is called against the Max API on startup;
- whether ``postStop()`` unregisters the webhook on shutdown.

Heavy collaborators (``MaxBotClient``, ``ProxyService``, ``HandlersManager``,
``QueueService``, ``RateLimiterManager``) are patched at the
``internal.bot.max.application`` module so only the config-reading branch
logic is exercised.
"""

from typing import Any, Dict, Generator, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from internal.bot.max import application as maxApp
from internal.bot.max.application import MaxBotApplication


def makeConfigManager(
    webhookConfig: Optional[Dict[str, Any]] = None,
    botConfig: Optional[Dict[str, Any]] = None,
) -> Mock:
    """Build a mock ConfigManager whose ``config`` is a real dict.

    Args:
        webhookConfig: Contents of the ``[webhook-receiver]`` block. When
            None, the block is omitted so ``config.get("webhook-receiver", {})``
            resolves to the empty dict (matching the absent-config case).
        botConfig: Return value of ``getBotConfig()``.

    Returns:
        A Mock ConfigManager whose ``.config`` attribute is a plain dict
        (so ``.get()`` works) and whose ``getBotConfig()`` returns the
        provided ``botConfig``.
    """
    configManager = Mock()
    configManager.config = {}
    if webhookConfig is not None:
        configManager.config["webhook-receiver"] = webhookConfig
    configManager.getBotConfig.return_value = botConfig if botConfig is not None else {"token": "test-token"}
    return configManager


def buildApp(configManager: Mock) -> MaxBotApplication:
    """Construct a MaxBotApplication wired to a mock database.

    Args:
        configManager: The mock ConfigManager to install on the app.

    Returns:
        A MaxBotApplication instance. Callers must have the ``mockedDeps``
        fixture active so that the collaborators the constructor pokes
        (``HandlersManager``, ``QueueService``) are patched out.
    """
    return MaxBotApplication(
        configManager=configManager,
        botToken="test-token",
        database=Mock(),
    )


@pytest.fixture
def mockedDeps() -> Generator[Dict[str, Any], None, None]:
    """Patch all heavy collaborators of MaxBotApplication for the test.

    Yields:
        dict: Handles to the patched collaborators, keyed by name:
            - ``libMax``: the patched ``lib.max_bot`` module reference;
            - ``maxBotClient``: the mock instance returned by the patched
              ``MaxBotClient`` constructor;
            - ``handlerManager``: the mock HandlersManager instance;
            - ``rateLimiterManager``: the patched RateLimiterManager class.
    """
    with (
        patch.object(maxApp, "libMax") as mockLibMax,
        patch.object(maxApp, "ProxyService") as mockProxyServiceCls,
        patch.object(maxApp, "HandlersManager") as mockHandlersManagerCls,
        patch.object(maxApp, "QueueService") as mockQueueServiceCls,
        patch.object(maxApp, "RateLimiterManager") as mockRateLimiterCls,
    ):
        # --- Mock MaxBotClient instance ---
        mockClient = MagicMock()
        mockClient.getMyInfo = AsyncMock()
        mockClient.setWebhook = AsyncMock()
        mockClient.deleteWebhook = AsyncMock()
        mockClient.startPolling = AsyncMock()
        mockClient.aclose = AsyncMock()
        # _pollingTask is awaited when truthy; None short-circuits _runPolling.
        mockClient._pollingTask = None
        mockLibMax.MaxBotClient.return_value = mockClient

        # --- Mock ProxyService.getInstance().resolveProxy(...) ---
        mockProxyConfig = Mock()
        mockProxyConfig.getProxyURL.return_value = None
        mockProxyServiceInstance = Mock()
        mockProxyServiceInstance.resolveProxy.return_value = mockProxyConfig
        mockProxyServiceCls.getInstance.return_value = mockProxyServiceInstance

        # --- Mock HandlersManager instance ---
        mockHandlerManager = Mock()
        mockHandlerManager.initialize = AsyncMock()
        mockHandlerManager.shutdown = AsyncMock()
        mockHandlersManagerCls.return_value = mockHandlerManager

        # --- Mock QueueService.getInstance() ---
        mockQueueServiceCls.getInstance.return_value = Mock()

        # --- Mock RateLimiterManager.getInstance().destroy() ---
        mockRateManager = Mock()
        mockRateManager.destroy = AsyncMock()
        mockRateLimiterCls.getInstance.return_value = mockRateManager

        yield {
            "libMax": mockLibMax,
            "maxBotClient": mockClient,
            "handlerManager": mockHandlerManager,
            "rateLimiterManager": mockRateLimiterCls,
        }


class TestMaxBotApplicationWebhookMode:
    """Webhook-receiver config gating in MaxBotApplication.

    Covers the three branching points in ``_runPolling`` / ``postStop``:
    (1) receiver URL/token forwarding to MaxBotClient, (2) setWebhook on
    startup, and (3) deleteWebhook on shutdown.
    """

    # ------------------------------------------------------------------
    # (1) basePollingUrl / localReceiverToken forwarding to MaxBotClient
    # ------------------------------------------------------------------

    async def testWebhookDisabledDefaultBehavior(self, mockedDeps: Dict[str, Any]) -> None:
        """With the webhook-receiver block absent, no receiver URL/token reach MaxBotClient.

        The default config (no ``[webhook-receiver]``) leaves webhook mode
        off, so ``basePollingUrl`` and ``localReceiverToken`` must be None
        and ``setWebhook`` must not be invoked.
        """
        configManager = makeConfigManager(webhookConfig=None)
        app = buildApp(configManager)

        await app._runPolling()

        assert app._webhookMode is False
        kwargs = mockedDeps["libMax"].MaxBotClient.call_args.kwargs
        assert kwargs["basePollingUrl"] is None
        assert kwargs["localReceiverToken"] is None
        mockedDeps["maxBotClient"].setWebhook.assert_not_called()

    async def testWebhookDisabledExplicitFalse(self, mockedDeps: Dict[str, Any]) -> None:
        """An explicit ``enabled = false`` keeps basePollingUrl unset."""
        configManager = makeConfigManager(webhookConfig={"enabled": False})
        app = buildApp(configManager)

        await app._runPolling()

        assert app._webhookMode is False
        kwargs = mockedDeps["libMax"].MaxBotClient.call_args.kwargs
        assert kwargs["basePollingUrl"] is None
        assert kwargs["localReceiverToken"] is None

    async def testWebhookEnabledPassesBasePollingUrl(self, mockedDeps: Dict[str, Any]) -> None:
        """``enabled = true`` forwards ``base-polling-url`` to MaxBotClient."""
        configManager = makeConfigManager(
            webhookConfig={
                "enabled": True,
                "base-polling-url": "http://127.0.0.1:9999",
                "webhook-url": "https://example.com/webhook",
                "register-webhook": False,
            }
        )
        app = buildApp(configManager)

        await app._runPolling()

        assert app._webhookMode is True
        kwargs = mockedDeps["libMax"].MaxBotClient.call_args.kwargs
        assert kwargs["basePollingUrl"] == "http://127.0.0.1:9999"

    async def testWebhookEnabledDefaultsBasePollingUrlWhenMissing(self, mockedDeps: Dict[str, Any]) -> None:
        """``enabled = true`` with no ``base-polling-url`` falls back to the documented default."""
        configManager = makeConfigManager(
            webhookConfig={
                "enabled": True,
                "webhook-url": "https://example.com/webhook",
                "register-webhook": False,
            }
        )
        app = buildApp(configManager)

        await app._runPolling()

        kwargs = mockedDeps["libMax"].MaxBotClient.call_args.kwargs
        assert kwargs["basePollingUrl"] == "http://127.0.0.1:8443"

    async def testWebhookEnabledPassesLocalReceiverToken(self, mockedDeps: Dict[str, Any]) -> None:
        """``enabled = true`` forwards ``get-updates-secret`` as localReceiverToken."""
        configManager = makeConfigManager(
            webhookConfig={
                "enabled": True,
                "get-updates-secret": "my-secret",
                "webhook-url": "https://example.com/webhook",
                "register-webhook": False,
            }
        )
        app = buildApp(configManager)

        await app._runPolling()

        kwargs = mockedDeps["libMax"].MaxBotClient.call_args.kwargs
        assert kwargs["localReceiverToken"] == "my-secret"

    async def testWebhookEnabledEmptyTokenBecomesNone(self, mockedDeps: Dict[str, Any]) -> None:
        """An empty ``get-updates-secret`` normalises to None (no auth header sent)."""
        configManager = makeConfigManager(
            webhookConfig={
                "enabled": True,
                "get-updates-secret": "",
                "webhook-url": "https://example.com/webhook",
                "register-webhook": False,
            }
        )
        app = buildApp(configManager)

        await app._runPolling()

        kwargs = mockedDeps["libMax"].MaxBotClient.call_args.kwargs
        assert kwargs["localReceiverToken"] is None

    # ------------------------------------------------------------------
    # (2) setWebhook on startup
    # ------------------------------------------------------------------

    async def testRegisterWebhookTrueCallsSetWebhook(self, mockedDeps: Dict[str, Any]) -> None:
        """``register-webhook = true`` triggers setWebhook with the configured URL/secret/types."""
        configManager = makeConfigManager(
            webhookConfig={
                "enabled": True,
                "register-webhook": True,
                "webhook-url": "https://example.com/webhook",
                "secret": "shared-secret",
                # Empty list normalises to None ("all types") in _runPolling.
                "webhook-update-types": [],
            }
        )
        app = buildApp(configManager)

        await app._runPolling()

        mockedDeps["maxBotClient"].setWebhook.assert_called_once_with(
            url="https://example.com/webhook",
            types=None,
            secret="shared-secret",
        )

    async def testRegisterWebhookFalseSkipsSetWebhook(self, mockedDeps: Dict[str, Any]) -> None:
        """``register-webhook = false`` suppresses setWebhook even with webhook mode on."""
        configManager = makeConfigManager(
            webhookConfig={
                "enabled": True,
                "register-webhook": False,
                "webhook-url": "https://example.com/webhook",
            }
        )
        app = buildApp(configManager)

        await app._runPolling()

        mockedDeps["maxBotClient"].setWebhook.assert_not_called()

    async def testRegisterWebhookTrueMissingUrlRaises(self, mockedDeps: Dict[str, Any]) -> None:
        """``register-webhook = true`` with an empty ``webhook-url`` raises RuntimeError."""
        configManager = makeConfigManager(
            webhookConfig={
                "enabled": True,
                "register-webhook": True,
                "webhook-url": "",
            }
        )
        app = buildApp(configManager)

        with pytest.raises(RuntimeError, match="webhook-url"):
            await app._runPolling()

    async def testRegisterWebhookUnresolvedPlaceholderSecretRaises(self, mockedDeps: Dict[str, Any]) -> None:
        """An unresolved ``${VAR}`` placeholder secret is rejected before setWebhook.

        Without this guard the literal placeholder string (committed verbatim in
        the default config when the env var is unset) would be registered as the
        webhook secret with Max, defeating the shared-secret check on the
        receiver.
        """
        configManager = makeConfigManager(
            webhookConfig={
                "enabled": True,
                "register-webhook": True,
                "webhook-url": "https://example.com/webhook",
                "secret": "${MAX_WEBHOOK_SECRET}",
            }
        )
        app = buildApp(configManager)

        with pytest.raises(RuntimeError, match="unresolved env var placeholder"):
            await app._runPolling()

    async def testRegisterWebhookEmptySecretRaises(self, mockedDeps: Dict[str, Any]) -> None:
        """An empty ``secret`` is rejected before setWebhook.

        The placeholder guard catches an unresolved ``${VAR}``, but an empty
        string slips past it and would be registered as the webhook secret with
        Max, defeating the shared-secret check on the receiver.
        """
        configManager = makeConfigManager(
            webhookConfig={
                "enabled": True,
                "register-webhook": True,
                "webhook-url": "https://example.com/webhook",
                "secret": "",
            }
        )
        app = buildApp(configManager)

        with pytest.raises(RuntimeError, match="secret is empty"):
            await app._runPolling()

        mockedDeps["maxBotClient"].setWebhook.assert_not_called()

        mockedDeps["maxBotClient"].setWebhook.assert_not_called()

    # ------------------------------------------------------------------
    # (3) deleteWebhook on shutdown (postStop)
    # ------------------------------------------------------------------
    # postStop() is tested in isolation by setting the _webhookMode / maxBot
    # state that _runPolling() establishes, so the shutdown branch is exercised
    # without driving the full polling loop (which already calls postStop in
    # its own finally block).

    async def testPostStopUnregisterWebhookTrueCallsDeleteWebhook(self, mockedDeps: Dict[str, Any]) -> None:
        """On shutdown with webhook mode + unregister-webhook, deleteWebhook is called."""
        configManager = makeConfigManager(
            webhookConfig={
                "enabled": True,
                "register-webhook": True,
                "unregister-webhook": True,
                "webhook-url": "https://example.com/webhook",
            }
        )
        app = buildApp(configManager)
        # Mirror the state _runPolling() leaves behind before shutdown.
        app._webhookMode = True
        app.maxBot = mockedDeps["maxBotClient"]

        await app.postStop()

        mockedDeps["maxBotClient"].deleteWebhook.assert_called_once_with("https://example.com/webhook")

    async def testPostStopUnregisterWebhookFalseSkipsDeleteWebhook(self, mockedDeps: Dict[str, Any]) -> None:
        """``unregister-webhook = false`` suppresses deleteWebhook even with register-webhook = true.

        This is the independence check: the two flags now gate separate
        lifecycle phases, so disabling unregistration does not require also
        disabling registration.
        """
        configManager = makeConfigManager(
            webhookConfig={
                "enabled": True,
                "register-webhook": True,
                "unregister-webhook": False,
                "webhook-url": "https://example.com/webhook",
            }
        )
        app = buildApp(configManager)
        app._webhookMode = True
        app.maxBot = mockedDeps["maxBotClient"]

        await app.postStop()

        mockedDeps["maxBotClient"].deleteWebhook.assert_not_called()

    async def testPostStopWebhookModeDisabledSkipsDeleteWebhook(self, mockedDeps: Dict[str, Any]) -> None:
        """When webhook mode was never enabled, postStop skips deleteWebhook entirely."""
        configManager = makeConfigManager(
            webhookConfig={
                "enabled": False,
                "register-webhook": True,
                "webhook-url": "https://example.com/webhook",
            }
        )
        app = buildApp(configManager)
        app._webhookMode = False
        app.maxBot = mockedDeps["maxBotClient"]

        await app.postStop()

        mockedDeps["maxBotClient"].deleteWebhook.assert_not_called()
