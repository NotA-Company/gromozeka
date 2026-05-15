# Gromozeka

Gromozeka is a production-ready, multi-platform AI bot supporting Telegram and Max Messenger.

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
- **SQLite with provider abstraction**: PostgreSQL and MySQL providers exist; 16 versioned migrations
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
