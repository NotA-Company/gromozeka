# Gromozeka

Gromozeka is a production-ready, multi-platform AI bot supporting Telegram and Max Messenger.

See [CHANGELOG.md](CHANGELOG.md) for notable changes.

## Requirements

- Python 3.12+
- SQLite3 (stdlib)
- libmagic (5.46+)
- Telegram or Max Messenger bot token

## Key Features

- **Multi-provider LLM**: OpenRouter, Yandex Cloud (SDK and OpenAI-compatible), OpenAI, custom endpoints
- **Provider fallback**: Automatic failover between AI providers
- **AI tool calling**: Function calling support for extended capabilities
- **Image generation and analysis**: Text-to-image and image/sticker understanding
- **ML-powered spam detection**: Naive Bayes classifier with learning (`/spam`, `/learn_spam`, `/learn_ham`)
- **Divination**: Tarot and runes readings with LLM-based layout discovery
- **Weather**: Real-time weather via OpenWeatherMap with geocoding
- **Web search**: Yandex Search integration with caching and rate limiting
- **Chat summarization**: Summarize conversations and topics
- **Hierarchical TOML config**: Layered `--config-dir` overrides with `${VAR}` substitution
- **SQLite with provider abstraction**: PostgreSQL and MySQL providers exist; 19 versioned migrations
- **Rate limiting**: Sliding window algorithm with multiple queues
- **File storage**: Local filesystem or S3-compatible via `StorageService`
- **Custom handler loading**: Dynamic handler loading via TOML config

## Quick Start

```bash
git clone <repository-url> && cd gromozeka
make install
# Configure .env with your bot token and API keys (see docs/llm/configuration.md)
./run.sh
```

## Minimal Configuration

```toml
[bot]
mode = "telegram"             # "telegram" or "max"
token = "${BOT_TOKEN}"

[database.providers.default]
provider = "sqlite3"

[database.providers.default.parameters]
dbPath = "bot_data.db"

[logging]
level = "INFO"
```

Full config documentation: [docs/llm/configuration.md](docs/llm/configuration.md), [docs/developer-guide.md](docs/developer-guide.md).

## Run Commands

```bash
./run.sh                                                                # default (loads .env, default + local configs)
./run.sh --env=prod                                                     # production environment
./venv/bin/python3 main.py --config-dir configs/00-defaults --config-dir configs/local
./venv/bin/python3 main.py --print-config --config-dir configs/00-defaults --config-dir configs/local
```

## Max Messenger Webhook Mode

By default the bot long-polls the Max API (`platform-api2.max.ru`). For webhook
mode, the deployment is **two processes**: a standalone webhook receiver that
accepts Max's `POST /webhook` calls, plus the bot itself, which polls the
receiver's local `GET /updates` instead of the real Max API.

**1. Configure** `[webhook-receiver]` (defaults in
[`configs/00-defaults/webhook-receiver.toml`](configs/00-defaults/webhook-receiver.toml)):

```toml
[bot]
mode = "max"

[webhook-receiver]
enabled = true                                          # bot polls the local receiver
register-webhook = true                                 # bot registers the subscription with Max
webhook-url = "https://bot.example.com/webhook"         # public HTTPS URL (port 443, CA-trusted cert)
secret = "${MAX_WEBHOOK_SECRET}"                        # shared secret (env var)
base-polling-url = "http://127.0.0.1:8443"              # where the bot polls
```

Set the shared secret in your `.env` (never commit it):

```bash
MAX_WEBHOOK_SECRET=some-long-random-secret
```

**2. TLS.** Max requires a CA-trusted HTTPS certificate on port 443. Run a
reverse proxy (nginx, Caddy, …) that terminates TLS and forwards `POST /webhook`
to the receiver's `127.0.0.1:8443`; alternatively set `tls-cert-file` and
`tls-key-file` under `[webhook-receiver]` so the receiver serves HTTPS directly.

**3. Start both processes** (start the receiver first):

```bash
# Receiver process
./venv/bin/python3 -m internal.max_webhook_receiver \
    --config-dir configs/00-defaults --config-dir configs/local

# Bot process
./venv/bin/python3 main.py --config-dir configs/00-defaults --config-dir configs/local
```

The receiver refuses to start if `secret` is empty or an unresolved `${VAR}`.
In production, run the two as separate systemd units sharing the same config
and `.env` (so they share the SQLite database).

Full details: [docs/llm/architecture.md](docs/llm/architecture.md) (ADR-013),
[docs/llm/configuration.md](docs/llm/configuration.md) (`[webhook-receiver]`).

## Key Commands

| Command | Description |
|---|---|
| `/start` | Start interaction with the bot |
| `/help` | Show available commands and usage |
| `/configure` | Interactive chat configuration wizard |

See `/help` in-chat for the full command list.

## Development

```bash
make format lint          # before committing
make test                 # after any change
make ci                   # run the full CI pipeline locally in the Alpine container (mirrors .sourcecraft/ci.yaml); needs Docker
```

For code style, testing, handler creation, migrations, and architecture details, see
[docs/developer-guide.md](docs/developer-guide.md) and [docs/llm/index.md](docs/llm/index.md).

## Troubleshooting

Check logs in `logs/`, verify your `.env` file, and see [docs/developer-guide.md](docs/developer-guide.md).

## Contributing

PRs welcome. Run `make format lint test` before submitting.

## License

BSD 3-Clause -- see [LICENSE](LICENSE).

## Acknowledgments

Built with python-telegram-bot, OpenAI, Yandex Cloud, OpenRouter, OpenWeatherMap, and Yandex Search API.
