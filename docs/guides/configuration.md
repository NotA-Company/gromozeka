---
category: guide
---

# Configuration

The hierarchical TOML configuration system: load order, environment-variable substitution, config sections, per-chat defaults, and proxy setup.

## 4. Configuration System

The configuration system uses hierarchical TOML files Configs are merged in sorted order from all specified directories, with later files overriding earlier ones

### How Config Loading Works

[`ConfigManager`](/internal/config/manager.py:59) loads configs in the following priority order (lowest to highest)

1. Config files from `--config-dir` directories (loaded recursively, sorted alphabetically)
2. The single `--config` file (default: `config.toml`)

When files have the same keys, later files override earlier ones. Nested dictionaries are **deep-merged**, not replaced

```bash
# Load from a directory (all .toml files loaded recursively in sorted order)
./venv/bin/python3 main.py --config-dir configs/00-defaults --config-dir configs/common

# Print the merged config and exit
./venv/bin/python3 main.py --config-dir configs/00-defaults --print-config
```

### Environment Variable Substitution

Any value in TOML can reference environment variables using `${VAR_NAME}` syntax

```toml
[bot]
token = "${TELEGRAM_BOT_TOKEN}"

[database.providers.default.parameters]
dbPath = "${DB_PATH}"
```

The `.env` file (default path, configurable with `--dotenv-file`) is loaded before substitution happens

### Config Sections

#### `[application]`

```toml
[application]
root-dir = "storage"   # Change working directory to this path on startup
```

#### `[bot]`

```toml
[bot]
mode = "telegram"                    # "telegram" or "max"
token = "YOUR_BOT_TOKEN_HERE"        # Bot token from @BotFather or Max
bot_owners = ["username", 123456]    # List of usernames/IDs with owner privileges
spam-button-salt = "some_salt"       # Salt for signing spam action buttons
max-tasks = 1024                     # Max concurrent message tasks globally
max-tasks-per-chat = 512             # Max concurrent tasks per chat
```

#### `[bot.defaults]` — Global per-chat defaults

These are the default settings applied to all chats They can be overridden per-chat via the `/configure` command or database

```toml
[bot.defaults]
admin-can-change-settings = true
bot-nicknames = "Громозека, Gro"
llm-message-format = "smart"          # "text", "json", or "smart"
use-tools = true
parse-attachments = true
allow-tools-commands = true
detect-spam = false
bayes-enabled = true
allow-mention = true
allow-reply = true
random-answer-probability = 0.01
chat-model = "openrouter/mistral-7b-instruct:free"
fallback-model = "openrouter/gemma-3-12b-it:free"
summary-model = "openrouter/gemma-3-12b-it:free"
chat-prompt = "You are a helpful assistant..."
random-answer-prompt = """..."""   # Appended only in handleRandomMessage; defines the <skip> abstention sentinel
```

#### `[bot.private-defaults]`, `[bot.group-defaults]`, `[bot.channel-defaults]`

These override `[bot.defaults]` for specific chat types

```toml
[bot.private-defaults]
random-answer-probability = 1       # Always respond in private chats
detect-spam = false
base-tier = "free-personal"

[bot.group-defaults]
random-answer-probability = 0.01    # Rarely respond randomly in groups

[bot.channel-defaults]
allow-mention = false
allow-reply = false
random-answer-probability = 0
```

#### `[bot.tier-defaults.<tier_name>]`

```toml
[bot.tier-defaults.free]
# Settings for free-tier chats
[bot.tier-defaults.paid]
# Settings for paid-tier chats
```

#### `[database]`

```toml
[database]
default = "default"           # Name of the default provider

[database.providers.default]
provider = "sqlite3"

[database.providers.default.parameters]
dbPath = "bot_data.db"
readOnly = false
timeout = 30
useWal = true
keepConnection = false        # Connect on demand (default for file-based DBs)

# Multi-source: map specific chats to different databases
[database.chatMapping]
"-1001234567890" = "secondary"   # Chat ID string -> provider name
```

**`keepConnection` parameter:**
- `true` — Connect immediately when provider is created (good for readonly replicas, in-memory DBs)
- `false` — Connect on first query (default for file-based DBs, saves resources)
- `null` — Auto-detect: `true` for in-memory SQLite3, `false` otherwise
- **Special case:** In-memory SQLite3 (`:memory:`) defaults to `true` to prevent data loss

#### `[ratelimiter]`

```toml
[ratelimiter.ratelimiters.default]
type = "SlidingWindow"
[ratelimiter.ratelimiters.default.config]
windowSeconds = 5
maxRequests = 5

[ratelimiter.ratelimiters.one-per-second]
type = "SlidingWindow"
[ratelimiter.ratelimiters.one-per-second.config]
windowSeconds = 1
maxRequests = 1

[ratelimiter.queues]
yandex-search = "default"
openweathermap = "default"
geocode-maps = "one-per-second"
chat-default = "default"
```

#### `[models]`

```toml
[models.providers.openrouter]
type = "openrouter"
api-key = "${OPENROUTER_API_KEY}"

[models.providers.yandex]
type = "yc-openai"
api-key = "${YC_API_KEY}"
folder-id = "${YC_FOLDER_ID}"

[models.models.my-model]
provider = "openrouter"
model_id = "mistralai/mistral-7b-instruct"
customParams.temperature = 0.7
context = 32768
enabled = true
# Capability flags
support_images = false
support_tools = true
# Tier access
tier = "free"     # "free", "free-personal", "paid", "friend", "bot-owner", "banned"
```

#### `[logging]`

```toml
[logging]
level = "INFO"
format = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
console = true
file = "logs/gromozeka.log"
error-file = "logs/gromozeka.err.log"
rotate = true
```

### `ConfigManager` API

```python
from internal.config.manager import ConfigManager

configManager = ConfigManager(
    configPath="config.toml",
    configDirs=["configs/00-defaults"],
    dotEnvFile=".env",
)

botConfig = configManager.getBotConfig()
dbConfig = configManager.getDatabaseConfig()
modelsConfig = configManager.getModelsConfig()
loggingConfig = configManager.getLoggingConfig()
rateLimiterConfig = configManager.getRateLimiterConfig()
weatherConfig = configManager.getOpenWeatherMapConfig()
yandexConfig = configManager.getYandexSearchConfig()
```

---

## 12. Proxy Configuration

Gromozeka supports routing outbound HTTP traffic through configurable HTTP or SOCKS5 proxies. This is useful when the bot runs in environments where direct internet access is restricted.

### Enabling Proxy

Proxy is **disabled by default** — enabling it requires setting `[proxy].enabled = true` and opting in each service individually.

**Step 1:** Add proxy credentials to your `.env` file (never commit these):

```bash
# .env.local (never committed)
PROXY_ADDRESS="http://proxy.corp.example.com:8080"
PROXY_USER="bot-user"
PROXY_PASSWORD="s3cret"
```

**Step 2:** Create a proxy config override (e.g., `configs/local/proxy.toml`):

```toml
# configs/local/proxy.toml
[proxy]
enabled = true
type = "http"              # "http" or "socks5"
address = "${PROXY_ADDRESS}"
user = "${PROXY_USER}"
password = "${PROXY_PASSWORD}"
```

**Step 3:** Opt in individual services by adding `use-proxy = true` to their config sections:

```toml
# In your local config override:
[yandex-search]
enabled = true
use-proxy = true              # Opt this service into the global proxy
api-key = "${YANDEX_API_KEY}"

[openweathermap]
enabled = true
use-proxy = true
api-key = "${OWM_API_KEY}"

[geocode-maps]
use-proxy = true

[bot]
use-proxy = true              # Route Telegram/Max bot traffic through proxy
```

**Step 4:** Restart the bot. Proxy config is loaded at startup only — changes require a restart.

### Per-Service Overrides

Any service can override the global proxy with its own `proxy` sub-table:

```toml
[yandex-search]
enabled = true
use-proxy = true
api-key = "${YANDEX_API_KEY}"

[yandex-search.proxy]
type = "socks5"
address = "${YANDEX_SOCKS5_ADDRESS}"
user = ""
password = ""
```

### SOCKS5 Setup

For SOCKS5 proxies, set `type = "socks5"`. SOCKS5 support is built into `httpx2[socks]` (the `socksio` extra, already in `requirements.direct.txt` via `httpx2[http2,socks]==2.10.0`) — no separate package is needed:

```toml
[proxy]
enabled = true
type = "socks5"
address = "socks5://proxy.example.com:1080"
user = "${PROXY_USER}"
password = "${PROXY_PASSWORD}"
```

HTTP/2 works over SOCKS5 proxies (HTTP/2 is negotiated via TLS ALPN entirely above the SOCKS5 tunnel; httpcore2 supports it natively). The Yandex Search web-fetch client (`_downloadUrl()`) always enables HTTP/2, and ALPN degrades gracefully to HTTP/1.1 if the target server lacks h2 support.

### How Resolution Works

The `ProxyConfig` class in `lib/proxy/__init__.py` applies a 4-step resolution:

1. **Master kill-switch:** If `[proxy].enabled` is `false` or absent → no proxy for any service.
2. **Service opt-in:** If `use-proxy` is falsy or absent in the service config → no proxy for that service.
3. **Per-service override:** If the service has a `proxy` sub-table with a non-empty `address` → use the override (missing fields fall back to global).
4. **Global fallback:** Use the global `[proxy]` settings.

### Services That Support Proxy

| Service | Config Section | Proxy Resolution |
|---|---|---|
| Telegram bot | `[bot]` | `TelegramBotApplication.run()` |
| Max Messenger bot | `[bot]` | `MaxBotApplication._runPolling()` |
| OpenAI-compatible LLM providers | `[models.providers.<name>]` | `BasicOpenAIProvider._initClient()` via `_globalProxy` |
| Image download (LLM) | `[models.providers.<name>]` | `BasicOpenAIProvider._generateImageViaImagesApi()` via `_globalProxy` |
| OpenRouter `listRemoteModels()` | `[models.providers.openrouter]` | `OpenrouterProvider.listRemoteModels()` via `_globalProxy` |
| Yandex Search | `[yandex-search]` | `YandexSearchHandler.__init__()` |
| Web-fetch (Yandex Search) | `[yandex-search]` | Same proxy as Yandex Search |
| OpenWeatherMap | `[openweathermap]` | `WeatherHandler.__init__()` |
| Geocode Maps | `[geocode-maps]` | `WeatherHandler.__init__()` |

---

### 14.5 Adding a New Chat Setting

Chat settings are key-value pairs stored per-chat and cached in [`CacheService`](/internal/services/cache/service.py:88)

**Step 1**: Add the key to `ChatSettingsKey` enum in [`internal/bot/models/chat_settings.py`](/internal/bot/models/chat_settings.py)

```python
class ChatSettingsKey(StrEnum):
    # ... existing keys ...
    MY_NEW_SETTING = "my-new-setting"
```

**Step 2**: Add the setting metadata in `getChatSettingsInfo()` for type/validation info

**Step 3**: Add a default value in [`configs/00-defaults/bot-defaults.toml`](/configs/00-defaults/bot-defaults.toml)

```toml
[bot.defaults]
my-new-setting = "default_value"
```

**Step 4**: Use it in your handler

```python
settings = self.getChatSettings(chatId=ensuredMessage.recipient.id)
# Production code subscripts settings directly and uses the typed accessor:
myValue: str = settings[ChatSettingsKey.MY_NEW_SETTING].toStr()
```

---
