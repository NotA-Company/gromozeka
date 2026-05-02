# Gromozeka — Configuration Reference

> **Audience:** LLM agents, dood!  
> **Purpose:** Complete reference for TOML configuration sections, ConfigManager methods, and per-chat settings, dood!  
> **Self-contained:** Everything needed for configuration work is here, dood!

---

## Table of Contents

1. [Config Loading Order](#1-config-loading-order)
2. [Config Sections Reference](#2-config-sections-reference)
3. [ConfigManager Methods](#3-configmanager-methods)
4. [Adding Configuration](#4-adding-configuration)

---

## 1. Config Loading Order

1. File at `--config` path (default: `config.toml`)
2. All `*.toml` files in `--config-dir` directories, sorted alphabetically, merged recursively

**Key:** Later files override earlier ones. Nested dicts are merged recursively, dood!

**Default config locations:**
- [`configs/00-defaults/00-config.toml`](../../configs/00-defaults/00-config.toml) — base app defaults
- [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml) — bot defaults
- [`configs/common/00-config.toml`](../../configs/common/00-config.toml) — common overrides

---

## 2. Config Sections Reference

### `[application]`

| Key | Type | Purpose |
|---|---|---|
| `root-dir` | str | Working directory after startup |

### `[bot]`

| Key | Type | Purpose |
|---|---|---|
| `mode` | `"telegram"` or `"max"` | Bot platform |
| `token` | str | Bot API token |
| `bot_owners` | list[str\|int] | Owner usernames or user IDs |
| `spam-button-salt` | str | Salt for signing spam action buttons |
| `max-tasks` | int | Global task queue limit (default: 1024) |
| `max-tasks-per-chat` | int | Per-chat queue limit (default: 512) |
| `defaults` | dict | Default chat settings for all chats |
| `private-defaults` | dict | Default settings for private chats |
| `group-defaults` | dict | Default settings for group chats |
| `tier-defaults` | dict | Tier-specific default settings |

**IMPORTANT:** `bot_owners` can be username OR int ID — both are valid. Handle both types in owner checks, dood!

### `[database]`

| Key | Type | Purpose |
|---|---|---|
| `default` | str | Default provider name |
| `providers.<name>.provider` | str | Provider type (`"sqlite3"` or `"sqlink"`) |
| `providers.<name>.parameters.dbPath` | str | SQLite file path |
| `providers.<name>.parameters.readOnly` | bool | Read-only flag |
| `providers.<name>.parameters.timeout` | float | Connection timeout (seconds) |
| `providers.<name>.parameters.useWal` | bool | Enable WAL mode (default: `true`) |
| `chatMapping.<chatId>` | str | Map chat ID to provider name |

**Example:**
```toml
[database]
default = "primary"

[database.providers.primary]
provider = "sqlite3"

[database.providers.primary.parameters]
dbPath = "bot_data.db"
readOnly = false
timeout = 30.0
useWal = true

[database.chatMapping]
-1001234567890 = "primary"
```

**Multi-source example:**
```toml
[database]
default = "primary"

[database.providers.primary]
provider = "sqlite3"

[database.providers.primary.parameters]
dbPath = "bot.db"
readOnly = false
timeout = 30.0

[database.providers.archive]
provider = "sqlite3"

[database.providers.archive.parameters]
dbPath = "archive.db"
readOnly = true
timeout = 30.0

[database.chatMapping]
-1001234567890 = "archive"  # Old inactive chat
-1002345678901 = "archive"  # Another old chat
```

### `[models]`

```toml
[models.providers.<name>]
type = "yc-openai"  # or "openrouter", "yc-sdk", "custom-openai"
# provider-specific config...

[models.models.<name>]
provider = "<provider-name>"
model_id = "gpt-4o"
model_version = "latest"
temperature = 0.5
context = 32768
tier = "free"  # "free", "paid", etc.
enabled = true
```

**Provider types:**
- `yc-openai` — Yandex Cloud OpenAI-compatible API
- `openrouter` — OpenRouter multi-model API
- `yc-sdk` — Yandex Cloud native SDK
- `custom-openai` — Custom OpenAI-compatible API

### `[ratelimiter]`

```toml
[ratelimiter.ratelimiters.<name>]
type = "SlidingWindow"
[ratelimiter.ratelimiters.<name>.config]
windowSeconds = 5
maxRequests = 5

[ratelimiter.queues]
yandex-search = "<limiter-name>"
openweathermap = "<limiter-name>"
```

### `[logging]`

| Key | Type | Purpose |
|---|---|---|
| `level` | str | Log level (`INFO`, `DEBUG`, etc.) |
| `format` | str | Log format string |
| `console` | bool | Log to console |
| `file` | str | Log file path |
| `error-file` | str | Error log file path |
| `rotate` | bool | Enable log rotation |

### `[storage]`

```toml
[storage]
type = "fs"  # "fs", "s3", "null"

[storage.fs]
base-dir = "./storage/objects"

# OR for S3:
[storage.s3]
endpoint = "https://s3.amazonaws.com"
region = "us-east-1"
key-id = "..."
key-secret = "..."
bucket = "my-bucket"
prefix = "objects/"
```

**Storage backend types:**
- `null` — no-op, discards all data
- `fs` — filesystem storage
- `s3` — AWS S3 or compatible (e.g., MinIO, Yandex Object Storage)

### `[openweathermap]`

| Key | Type | Purpose |
|---|---|---|
| `enabled` | bool | Enable weather handler |
| `api-key` | str | OpenWeatherMap API key |
| `geocoding-cache-ttl` | int | Geocoding cache TTL (seconds) |
| `weather-cache-ttl` | int | Weather data cache TTL |

### `[yandex-search]`

| Key | Type | Purpose |
|---|---|---|
| `enabled` | bool | Enable Yandex Search handler |
| `api-key` | str | Yandex Search API key |

### `[resender]`

| Key | Type | Purpose |
|---|---|---|
| `enabled` | bool | Enable resender handler |

**Resender jobs config:**
```toml
[[resender.jobs]]
id = "telegram-to-max"
sourceChatId = -1001234567890
targetChatId = 9876543210
mediaGroupDelaySecs = 5.0  # Optional, defaults to 5.0
```

### `[geocode-maps]`

| Key | Type | Purpose |
|---|---|---|
| `api-key` | str | Geocode Maps API key |
| `cache-ttl` | int | Cache TTL for geocoding results (seconds) |

---

## 3. ConfigManager Methods

**File:** [`internal/config/manager.py:59`](../../internal/config/manager.py:59)

| Method | Returns | Purpose |
|---|---|---|
| `get(key, default)` | `Any` | Generic config value getter |
| `getBotConfig()` | `Dict[str, Any]` | `[bot]` section |
| `getDatabaseConfig()` | `Dict[str, Any]` | `[database]` section |
| `getLoggingConfig()` | `Dict[str, Any]` | `[logging]` section |
| `getRateLimiterConfig()` | `RateLimiterManagerConfig` | `[ratelimiter]` section |
| `getModelsConfig()` | `Dict[str, Any]` | `[models]` section |
| `getBotToken()` | `str` | Bot API token (exits if missing) |
| `getOpenWeatherMapConfig()` | `Dict[str, Any]` | `[openweathermap]` section |
| `getYandexSearchConfig()` | `Dict[str, Any]` | `[yandex-search]` section |
| `getStorageConfig()` | `Dict[str, Any]` | `[storage]` section |
| `getGeocodeMapsConfig()` | `Dict[str, Any]` | `[geocode-maps]` section |

---

## 4. Adding Configuration

### Step 1: Add getter to ConfigManager

**File:** [`internal/config/manager.py`](../../internal/config/manager.py:180)

```python
def getMyFeatureConfig(self) -> Dict[str, Any]:
    """Get my feature configuration, dood!

    Returns:
        Dict with feature configuration settings
    """
    return self.get("my-feature", {})
```

### Step 2: Add default TOML entry

**File:** `configs/00-defaults/00-config.toml` (or a new file in `configs/00-defaults/`)

```toml
[my-feature]
enabled = false
api-key = ""
cache-ttl = 3600
```

### Step 3: Use in handler

```python
# In handler __init__ or method:
myConfig: Dict[str, Any] = self.configManager.getMyFeatureConfig()
isEnabled: bool = myConfig.get("enabled", False)
apiKey: str = myConfig.get("api-key", "")
```

### Checklist for adding config

- [ ] Getter method in `ConfigManager` with docstring and type hints
- [ ] Default TOML entry in `configs/00-defaults/`
- [ ] Documentation of config key meanings (here or in `developer-guide.md`)
- [ ] Ran `make format lint`

---

## See Also

- [`index.md`](index.md) — Project overview, mandatory rules
- [`architecture.md`](architecture.md) — ADR-007 (configuration layering)
- [`handlers.md`](handlers.md) — Conditional handler registration based on config
- [`services.md`](services.md) — Service TOML config sections
- [`libraries.md`](libraries.md) — Library API config usage
- [`tasks.md`](tasks.md) — Step-by-step: "add new API integration" (includes config steps)

---

*This guide is auto-maintained and should be updated whenever configuration sections change, dood!*
*Last updated: 2026-05-02, dood!*
