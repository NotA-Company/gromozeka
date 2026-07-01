"""Entry point for the Max webhook receiver process.

Parses command-line arguments, loads configuration via :class:`ConfigManager`,
reads the ``webhook-receiver`` config section, initializes the
:class:`Database`, builds the aiohttp application via :func:`createApp`,
optionally enables TLS, and starts serving with :func:`aiohttp.web.run_app`.
"""

import argparse
import logging
import ssl

from aiohttp import web

from internal.config.manager import ConfigManager
from internal.database import Database

from .app import createApp

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def parseArgs() -> argparse.Namespace:
    """Parse command-line arguments for the webhook receiver.

    Returns:
        Parsed argument namespace with ``config_dir`` (list of paths or None)
        and ``dotenv_file`` (path string) attributes.
    """
    parser = argparse.ArgumentParser(description="Max Messenger Webhook Receiver")
    parser.add_argument(
        "--config-dir",
        action="append",
        help="TOML config directory (can be specified multiple times)",
    )
    parser.add_argument(
        "--dotenv-file",
        default=".env",
        help="Path to .env file",
    )
    return parser.parse_args()


def main() -> None:
    """Run the webhook receiver process.

    Reads the ``webhook-receiver`` config section, initializes the
    :class:`Database`, builds the aiohttp application, optionally enables
    TLS, and starts serving. Exits with a non-zero status when
    ``webhook-receiver.secret`` is empty, unset, or an unresolved
    ``${VAR}`` env var placeholder (the latter would otherwise be treated
    as a literal, publicly-known secret).

    Raises:
        SystemExit: When ``webhook-receiver.secret`` is not configured
            or is an unresolved env var placeholder.
    """
    args = parseArgs()
    configManager = ConfigManager(
        configPath="config.toml",
        configDirs=args.config_dir,
        dotEnvFile=args.dotenv_file,
    )

    webhookConfig = configManager.config.get("webhook-receiver", {})
    host = webhookConfig.get("listen-host", "127.0.0.1")
    port = webhookConfig.get("listen-port", 8443)
    secret = webhookConfig.get("secret", "")
    getUpdatesSecret = webhookConfig.get("get-updates-secret", "")
    webhookPath = webhookConfig.get("webhook-path", "/webhook")
    datasource = webhookConfig.get("datasource", "") or None
    enableCleanup = webhookConfig.get("enable-cleanup", True)
    markOnSubsequentPoll = webhookConfig.get("mark-on-subsequent-poll", True)

    if not secret or (secret.startswith("${") and secret.endswith("}")):
        logger.error("webhook-receiver.secret is not configured (missing or unresolved env var) -- exiting")
        raise SystemExit(1)

    database = Database(configManager.getDatabaseConfig())  # pyright: ignore[reportArgumentType]

    app = createApp(
        database=database,
        secret=secret,
        getUpdatesSecret=getUpdatesSecret,
        webhookPath=webhookPath,
        datasource=datasource,
        enableCleanup=enableCleanup,
        markOnSubsequentPoll=markOnSubsequentPoll,
    )

    # Optional TLS: serve HTTPS directly when both cert and key are configured.
    sslCtx = None
    certFile = webhookConfig.get("tls-cert-file")
    keyFile = webhookConfig.get("tls-key-file")
    if certFile and keyFile:
        sslCtx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        sslCtx.load_cert_chain(certFile, keyFile)

    web.run_app(app, host=host, port=port, ssl_context=sslCtx)


if __name__ == "__main__":
    main()
