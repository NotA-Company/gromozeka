"""Entry point for the Max webhook receiver process.

Full-lib launcher (module-invocable like ``lib.stats.stats_pages``; deployed
command ``./venv/bin/python3 -m lib.max_webhook_receiver --config <path>
[--dotenv-file <path>]``). Parses command-line arguments, populates the
environment from an optional dotenv file, loads the receiver's OWN single
TOML config file, substitutes ``${VAR}`` placeholders, reads the
``webhook-receiver`` section, guards against unresolved secrets, constructs
a :class:`DatabaseManager` over the receiver's OWN
``webhook-receiver.database`` config section (the receiver never touches the
bot's database and never runs the bot's migrations — startup self-heals the
webhook_updates table AND index), builds the aiohttp application via
:func:`createApp`, optionally enables TLS, and starts serving.

ZERO internal imports: this package is bot-free by construction (D17).
"""

import argparse
import logging
import ssl
import tomllib

from aiohttp import web

from lib.db.manager import DatabaseManager
from lib.max_webhook_receiver.app import createApp
from lib.max_webhook_receiver.repository import WebhookUpdatesRepository
from lib.utils.utils import load_dotenv, substituteEnvVars

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def parseArgs() -> argparse.Namespace:
    """Parse command-line arguments for the webhook receiver.

    Returns:
        Parsed argument namespace with ``config`` (path to the receiver's
        single TOML config file) and ``dotenv_file`` (path string)
        attributes.
    """
    parser = argparse.ArgumentParser(description="Max Messenger Webhook Receiver")
    parser.add_argument(
        "--config",
        default="webhook-receiver.toml",
        help="Path to the receiver's TOML config file (cwd-relative default)",
    )
    parser.add_argument(
        "--dotenv-file",
        default=".env",
        help="Path to .env file",
    )
    return parser.parse_args()


def main() -> None:
    """Run the webhook receiver process.

    Loads the receiver's own config file, validates the webhook secret,
    wires the receiver's own database manager and repository, and serves
    the aiohttp application.
    Exits with a non-zero status when ``webhook-receiver.secret`` is empty,
    unset, or an unresolved ``${VAR}`` env var placeholder (the latter would
    otherwise be treated as a literal, publicly-known secret).

    Raises:
        SystemExit: When the config file is not found or unreadable, or
            when ``webhook-receiver.secret`` is not configured or is an
            unresolved env var placeholder.
    """
    args = parseArgs()

    # Dotenv first, so ${VAR} placeholders resolve from it (lib code since
    # the stats arc; a missing file logs an error and returns {}).
    load_dotenv(args.dotenv_file)

    # Single-file config load: stdlib tomllib (py3.12) + lib-side env
    # substitution (D18). NO ConfigManager exists in this package.
    try:
        with open(args.config, "rb") as configFile:
            rawConfig = tomllib.load(configFile)
    except FileNotFoundError:
        logger.error(f"Config file not found: {args.config} -- exiting")
        raise SystemExit(1)
    config = substituteEnvVars(rawConfig)

    webhookConfig = config.get("webhook-receiver", {})
    host = webhookConfig.get("listen-host", "127.0.0.1")
    port = webhookConfig.get("listen-port", 8443)
    secret = webhookConfig.get("secret", "")
    getUpdatesSecret = webhookConfig.get("get-updates-secret", "")
    webhookPath = webhookConfig.get("webhook-path", "/webhook")
    enableCleanup = webhookConfig.get("enable-cleanup", True)
    markOnSubsequentPoll = webhookConfig.get("mark-on-subsequent-poll", True)

    if not secret or (secret.startswith("${") and secret.endswith("}")):
        logger.error("webhook-receiver.secret is not configured (missing or unresolved env var) -- exiting")
        raise SystemExit(1)

    # The receiver's OWN database (D12): a DatabaseManager over the
    # webhook-receiver.database config section — pure nested navigation, no
    # dict-building. NEVER the internal Database wrapper and NEVER the bot's
    # [database] config: the receiver must not run the bot's migrations or
    # touch the bot's DB file. Startup self-heals the webhook_updates table
    # AND index instead (see lib.max_webhook_receiver.schema).
    dbConfig = webhookConfig.get("database", {})
    manager = DatabaseManager(dbConfig)  # pyright: ignore[reportArgumentType]
    repository = WebhookUpdatesRepository(manager)

    app = createApp(
        repository=repository,
        manager=manager,
        secret=secret,
        getUpdatesSecret=getUpdatesSecret,
        webhookPath=webhookPath,
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
