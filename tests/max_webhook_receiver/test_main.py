"""Tests for the Max webhook receiver entry point (``__main__.main``).

Focuses on the startup guard that rejects an empty or unresolved
``${VAR}`` placeholder ``webhook-receiver.secret``. When the env var backing
the placeholder is unset, :class:`ConfigManager` leaves the placeholder
verbatim; a naive ``if not secret`` check would pass because the placeholder
string is truthy, and the receiver would then accept webhook POSTs signed
with a publicly-known literal secret.
"""

from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from internal.max_webhook_receiver import __main__ as receiverMain


def _makeArgs() -> MagicMock:
    """Build a fake argparse namespace as returned by :func:`parseArgs`.

    Returns:
        A MagicMock whose ``config_dir``/``dotenv_file`` attributes exist.
        Their values are irrelevant here because :class:`ConfigManager` is
        patched, so no real config files are read.
    """
    args = MagicMock()
    args.config_dir = None
    args.dotenv_file = ".env"
    return args


@contextmanager
def _patchMainEnv(mockConfigManager: Any) -> Any:
    """Patch the collaborators ``main()`` touches.

    Args:
        mockConfigManager: Object to return from the patched ``ConfigManager``
            constructor. Its ``.config`` attribute must be a real dict so the
            ``webhook-receiver`` block can be read.

    Yields:
        dict: The mock objects, keyed by the patched attribute name
        (``parseArgs``, ``ConfigManager``, ``Database``, ``createApp``, ``web``).
    """
    with ExitStack() as stack:
        yield {
            "parseArgs": stack.enter_context(patch.object(receiverMain, "parseArgs", return_value=_makeArgs())),
            "ConfigManager": stack.enter_context(
                patch.object(receiverMain, "ConfigManager", return_value=mockConfigManager)
            ),
            "Database": stack.enter_context(patch.object(receiverMain, "Database")),
            "createApp": stack.enter_context(patch.object(receiverMain, "createApp")),
            "web": stack.enter_context(patch.object(receiverMain, "web")),
        }


class TestMainSecretGuard:
    """The startup guard for ``webhook-receiver.secret`` in :func:`main`."""

    @pytest.mark.parametrize("secret", ["", "${MAX_WEBHOOK_SECRET}"])
    def testMainExitsWhenSecretMissingOrUnresolved(self, secret: str) -> None:
        """An empty or unresolved-placeholder secret exits before serving.

        Args:
            secret: The unresolved/empty secret value to inject into the
                ``webhook-receiver.secret`` config slot.
        """
        mockConfigManager = MagicMock()
        mockConfigManager.config = {"webhook-receiver": {"secret": secret}}

        with _patchMainEnv(mockConfigManager) as patches:
            with pytest.raises(SystemExit) as excInfo:
                receiverMain.main()

        assert excInfo.value.code == 1
        patches["Database"].assert_not_called()
        patches["createApp"].assert_not_called()
        patches["web"].run_app.assert_not_called()

    def testMainProceedsWithResolvedSecret(self) -> None:
        """A concrete (non-placeholder) secret proceeds to build and serve the app."""
        mockConfigManager = MagicMock()
        mockConfigManager.config = {
            "webhook-receiver": {
                "secret": "real-secret",
                "listen-host": "127.0.0.1",
                "listen-port": 8443,
                "webhook-path": "/webhook",
            }
        }
        mockConfigManager.getDatabaseConfig.return_value = {}

        with _patchMainEnv(mockConfigManager) as patches:
            receiverMain.main()

        patches["createApp"].assert_called_once()
        patches["web"].run_app.assert_called_once()
