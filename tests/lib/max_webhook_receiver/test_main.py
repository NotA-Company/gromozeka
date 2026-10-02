"""Tests for lib.max_webhook_receiver.__main__ (the receiver launcher).

These tests exercise the launcher's argument parsing, config loading,
environment variable substitution, secret validation, database manager
construction, and the path to ``web.run_app`` invocation.

Per design §5.3: real temp TOML + temp dotenv files (NO ConfigManager patches).
The test matrix covers:

* secret present and resolved via dotenv (launcher proceeds)
* secret missing (SystemExit(1))
* secret unresolved placeholder (SystemExit(1))
* missing [webhook-receiver] section (SystemExit(1))

All tests mock ``web.run_app`` at the module-attribute level
(``lib.max_webhook_receiver.__main__.web.run_app``) to avoid starting a real HTTP server.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lib.max_webhook_receiver.__main__ import main


class TestLauncherConfig:
    """The launcher's config loading and secret validation against REAL TOML files.

    Each test writes a temporary TOML config and/or dotenv file, patches
    ``parseArgs`` to point at the real paths, then drives ``main()``. Env hygiene
    via ``monkeypatch.setenv``/``delenv`` so a developer shell exporting
    ``MAX_WEBHOOK_SECRET`` cannot flip the placeholder test.
    """

    def _writeConfig(self, tmp_path: Path, tomlBody: str) -> str:
        """Write a TOML config file under tmp_path.

        Args:
            tmp_path: Per-test temporary directory.
            tomlBody: Raw TOML text to write.

        Returns:
            str: Absolute path of the written config file.
        """
        configPath = tmp_path / "webhook-receiver.toml"
        configPath.write_text(tomlBody, encoding="utf-8")
        return str(configPath)

    def _writeDotenv(self, tmp_path: Path) -> str:
        """Write a dotenv file defining MAX_WEBHOOK_SECRET under tmp_path.

        Args:
            tmp_path: Per-test temporary directory.

        Returns:
            str: Absolute path of the written dotenv file.
        """
        dotenvPath = tmp_path / ".env"
        dotenvPath.write_text("MAX_WEBHOOK_SECRET=resolved-secret\n", encoding="utf-8")
        return str(dotenvPath)

    def testSecretPresentAndResolvedProceeds(self, tmp_path: Path, monkeypatch) -> None:
        """Launcher proceeds when secret is present and resolved via dotenv.

        Full D19 shape incl. ``[webhook-receiver.database]`` + dotenv file.
        Proceeds: ``DatabaseManager`` called ONCE with the nested ``database``
        dict UNMODIFIED (the pure-passthrough contract), ``WebhookUpdatesRepository``
        + ``createApp`` called, ``web.run_app`` called with the file's host/port.

        Args:
            tmp_path: Per-test temporary directory.
            monkeypatch: pytest fixture for env hygiene.

        Returns:
            None
        """
        monkeypatch.delenv("MAX_WEBHOOK_SECRET", raising=False)

        configPath = self._writeConfig(
            tmp_path,
            """[webhook-receiver]
listen-host = "127.0.0.1"
listen-port = 8443
secret = "${MAX_WEBHOOK_SECRET}"
get-updates-secret = ""
webhook-path = "/webhook"
enable-cleanup = true
mark-on-subsequent-poll = true

[webhook-receiver.database]
default = "default"

[webhook-receiver.database.providers.default]
provider = "sqlite3"

[webhook-receiver.database.providers.default.parameters]
dbPath = ":memory:"
readOnly = false
timeout = 30
useWal = false
keepConnection = false
""",
        )
        dotenvPath = self._writeDotenv(tmp_path)

        with patch("lib.max_webhook_receiver.__main__.parseArgs") as mockParseArgs:
            mockParseArgs.return_value = MagicMock(config=configPath, dotenv_file=dotenvPath)

            with patch("lib.max_webhook_receiver.__main__.web.run_app") as mockRunApp:
                with patch("lib.max_webhook_receiver.__main__.createApp") as mockCreateApp:
                    with patch("lib.max_webhook_receiver.__main__.DatabaseManager") as mockDbMgr:
                        mockCreateApp.return_value = MagicMock()

                        main()

                        # DatabaseManager should be called with the nested database config
                        mockDbMgr.assert_called_once()
                        dbConfigArg = mockDbMgr.call_args[0][0]
                        assert dbConfigArg["default"] == "default"
                        assert dbConfigArg["providers"]["default"]["provider"] == "sqlite3"
                        assert dbConfigArg["providers"]["default"]["parameters"]["dbPath"] == ":memory:"

                        # createApp should be called with repository, manager, and the config values
                        mockCreateApp.assert_called_once()
                        callKwargs = mockCreateApp.call_args[1]
                        assert callKwargs["secret"] == "resolved-secret"
                        assert callKwargs["getUpdatesSecret"] == ""
                        assert callKwargs["webhookPath"] == "/webhook"
                        assert callKwargs["enableCleanup"] is True
                        assert callKwargs["markOnSubsequentPoll"] is True
                        assert "repository" in callKwargs
                        assert "manager" in callKwargs

                        # web.run_app should be called with host and port from config
                        mockRunApp.assert_called_once()
                        assert mockRunApp.call_args[1]["host"] == "127.0.0.1"
                        assert mockRunApp.call_args[1]["port"] == 8443

    def testSecretMissingExits(self, tmp_path: Path, monkeypatch) -> None:
        """Launcher exits when secret key is absent.

        Args:
            tmp_path: Per-test temporary directory.
            monkeypatch: pytest fixture for env hygiene.

        Returns:
            None
        """
        monkeypatch.delenv("MAX_WEBHOOK_SECRET", raising=False)

        configPath = self._writeConfig(
            tmp_path,
            """[webhook-receiver]
listen-host = "127.0.0.1"
listen-port = 8443
get-updates-secret = ""
webhook-path = "/webhook"
enable-cleanup = true
mark-on-subsequent-poll = true

[webhook-receiver.database]
default = "default"

[webhook-receiver.database.providers.default]
provider = "sqlite3"

[webhook-receiver.database.providers.default.parameters]
dbPath = ":memory:"
readOnly = false
timeout = 30
useWal = false
keepConnection = false
""",
        )
        dotenvPath = tmp_path / ".env"
        dotenvPath.write_text("", encoding="utf-8")

        with patch("lib.max_webhook_receiver.__main__.parseArgs") as mockParseArgs:
            mockParseArgs.return_value = MagicMock(config=configPath, dotenv_file=dotenvPath)

            with patch("lib.max_webhook_receiver.__main__.DatabaseManager") as mockDbMgr:
                with pytest.raises(SystemExit) as excInfo:
                    main()

                assert excInfo.value.code == 1
                mockDbMgr.assert_not_called()

    def testSecretUnresolvedPlaceholderExits(self, tmp_path: Path, monkeypatch) -> None:
        """Launcher exits when secret is an unresolved ${VAR} placeholder.

        The placeholder survives substitution because the env var is not set.

        Args:
            tmp_path: Per-test temporary directory.
            monkeypatch: pytest fixture for env hygiene.

        Returns:
            None
        """
        monkeypatch.delenv("MAX_WEBHOOK_SECRET", raising=False)

        configPath = self._writeConfig(
            tmp_path,
            """[webhook-receiver]
listen-host = "127.0.0.1"
listen-port = 8443
secret = "${MAX_WEBHOOK_SECRET}"
get-updates-secret = ""
webhook-path = "/webhook"
enable-cleanup = true
mark-on-subsequent-poll = true

[webhook-receiver.database]
default = "default"

[webhook-receiver.database.providers.default]
provider = "sqlite3"

[webhook-receiver.database.providers.default.parameters]
dbPath = ":memory:"
readOnly = false
timeout = 30
useWal = false
keepConnection = false
""",
        )
        dotenvPath = tmp_path / ".env"
        dotenvPath.write_text("", encoding="utf-8")

        with patch("lib.max_webhook_receiver.__main__.parseArgs") as mockParseArgs:
            mockParseArgs.return_value = MagicMock(config=configPath, dotenv_file=dotenvPath)

            with patch("lib.max_webhook_receiver.__main__.DatabaseManager") as mockDbMgr:
                with pytest.raises(SystemExit) as excInfo:
                    main()

                assert excInfo.value.code == 1
                mockDbMgr.assert_not_called()

    def testMissingSectionExits(self, tmp_path: Path, monkeypatch) -> None:
        """Launcher exits when [webhook-receiver] section is entirely absent.

        Args:
            tmp_path: Per-test temporary directory.
            monkeypatch: pytest fixture for env hygiene.

        Returns:
            None
        """
        monkeypatch.delenv("MAX_WEBHOOK_SECRET", raising=False)

        configPath = self._writeConfig(
            tmp_path,
            """[other-section]
some-key = "some-value"
""",
        )
        dotenvPath = tmp_path / ".env"
        dotenvPath.write_text("", encoding="utf-8")

        with patch("lib.max_webhook_receiver.__main__.parseArgs") as mockParseArgs:
            mockParseArgs.return_value = MagicMock(config=configPath, dotenv_file=dotenvPath)

            with patch("lib.max_webhook_receiver.__main__.DatabaseManager") as mockDbMgr:
                with pytest.raises(SystemExit) as excInfo:
                    main()

                assert excInfo.value.code == 1
                mockDbMgr.assert_not_called()

    def testTlsAbsentRunsAppWithNoneSslContext(self, tmp_path: Path, monkeypatch) -> None:
        """Launcher calls web.run_app with ssl_context=None when TLS keys are not configured.

        This test intentionally builds a REAL DatabaseManager (shape validation only,
        no provider opened — verified side-effect-free) to ensure the launcher passes
        the database config correctly.

        Args:
            tmp_path: Per-test temporary directory.
            monkeypatch: pytest fixture for env hygiene.

        Returns:
            None
        """
        monkeypatch.delenv("MAX_WEBHOOK_SECRET", raising=False)

        configPath = self._writeConfig(
            tmp_path,
            """[webhook-receiver]
listen-host = "127.0.0.1"
listen-port = 8443
secret = "test-secret"
get-updates-secret = ""
webhook-path = "/webhook"
enable-cleanup = true
mark-on-subsequent-poll = true

[webhook-receiver.database]
default = "default"

[webhook-receiver.database.providers.default]
provider = "sqlite3"

[webhook-receiver.database.providers.default.parameters]
dbPath = ":memory:"
readOnly = false
timeout = 30
useWal = false
keepConnection = false
""",
        )
        dotenvPath = tmp_path / ".env"
        dotenvPath.write_text("", encoding="utf-8")

        with patch("lib.max_webhook_receiver.__main__.parseArgs") as mockParseArgs:
            mockParseArgs.return_value = MagicMock(config=configPath, dotenv_file=dotenvPath)

            with patch("lib.max_webhook_receiver.__main__.web.run_app") as mockRunApp:
                with patch("lib.max_webhook_receiver.__main__.createApp") as mockCreateApp:
                    mockCreateApp.return_value = MagicMock()

                    main()

                    # web.run_app should be called with ssl_context=None
                    mockRunApp.assert_called_once()
                    assert mockRunApp.call_args[1]["ssl_context"] is None
