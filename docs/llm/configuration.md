# Gromozeka — Configuration Reference

> **Audience:** LLM agents  
> **Purpose:** Complete reference for TOML configuration sections, ConfigManager methods, and per-chat settings  
> **Self-contained:** Everything needed for configuration work is here

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

**Key:** Later files override earlier ones. Nested dicts are merged recursively

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

**IMPORTANT:** `bot_owners` can be username OR int ID — both are valid. Handle both types in owner checks

### `[database]`

| Key | Type | Purpose |
|---|---|---|
| `default` | str | Default provider name |
| `providers.<name>.provider` | str | Provider type: `"sqlite3"` or `"sqlink"` (selectable); `"mysql"` and `"postgresql"` exist but are not yet selectable |
| `providers.<name>.parameters.dbPath` | str | Database file path (SQLite providers) |
| `providers.<name>.parameters.readOnly` | bool | Read-only flag |
| `providers.<name>.parameters.timeout` | int | Connection timeout (seconds) |
| `providers.<name>.parameters.useWal` | bool | Enable WAL mode (SQLite providers) |
| `providers.<name>.parameters.keepConnection` | bool\|null | Connect immediately (true), on demand (false) |
| `chatMapping.<chatId>` | str | Map chat ID to provider name |

**Example:**
```toml
[database]
default = "default"

[database.providers.default]
provider = "sqlite3"

[database.providers.default.parameters]
dbPath = "bot_data.db"
readOnly = false
timeout = 30
useWal = true
keepConnection = true  # Connect on creation and keep connection open

[database.chatMapping]
-1001234567890 = "default"
```

**Multi-source example:**
```toml
[database]
default = "default"

[database.providers.default]
provider = "sqlite3"

[database.providers.default.parameters]
dbPath = "bot.db"
readOnly = false
timeout = 30
useWal = true
keepConnection = true

[database.providers.readonly]
provider = "sqlink"

[database.providers.readonly.parameters]
dbPath = "archive.db"
readOnly = true
timeout = 10

[database.chatMapping]
-1001234567890 = "readonly"  # Old inactive chat
-1002345678901 = "readonly"  # Another old chat
```

**`keepConnection` parameter details:**
- `true` — Connect immediately when provider is created (good for readonly replicas, in-memory DBs)
- `false` — Connect on first query (default for file-based DBs, saves resources)
- **Special case:** In-memory SQLite3 (`:memory:`) defaults to `true` to prevent data loss

**Note:** Database configuration uses `providers` (not `sources`) for provider abstraction with `provider = "sqlite3"` or `"sqlink"`. MySQL and PostgreSQL providers exist in the codebase but are not selectable yet. See [`database.md`](database.md) for details on multi-source routing and repository usage.

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
- `yc-sdk` — Yandex Cloud native SDK (supports `auth_type`: `"auto"`, `"api_key"`, `"iam_token"`, `"yc_cli"`)
- `custom-openai` — Custom OpenAI-compatible API

**YC SDK auth configuration (`auth_type`):**
- `"auto"` (default) — detects `YC_API_KEY` env var, then `YC_IAM_TOKEN`, then falls back to `yc` CLI
- `"api_key"` — uses `api_key` from config or `YC_API_KEY` env var
- `"iam_token"` — uses `iam_token` from config or `YC_IAM_TOKEN` env var
- `"yc_cli"` — uses `yc` CLI (requires `yc_profile` for non-default profiles)

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

### `[divination]`

Defaults live in [`configs/00-defaults/divination.toml`](../../configs/00-defaults/divination.toml). The handler is registered conditionally on `enabled = true`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `enabled` | bool | `false` | Master switch — operator must flip to register `DivinationHandler` |
| `discovery-enabled` | bool | `true` | Enable automatic layout discovery via LLM + web search for unknown layouts |
| `tarot-enabled` | bool | `true` | Enable `/taro` command and `do_tarot_reading` LLM tool |
| `runes-enabled` | bool | `true` | Enable `/runes` command and `do_runes_reading` LLM tool |
| `image-generation` | bool | `true` | Whether to call `generateImage` per reading |
| `tools-enabled` | bool | `true` | Whether to register the LLM tools (independent from slash commands) |

**Slash commands** (category `CommandCategory.TOOLS`):
- `/taro <layout> <question>` (aliases: `/tarot`, `/таро`) — REQUIRES layout
- `/runes <layout> <question>` (aliases: `/rune`, `/руны`) — REQUIRES layout

Layout name parsing is case-, dash-, underscore-, and space-insensitive.

**Predefined layouts:**
- Tarot: `one_card`, `three_card`, `celtic_cross`, `relationship`, `yes_no`
- Runes: `one_rune`, `three_runes`, `five_runes`, `nine_runes`

**LLM tools** (registered when `tools-enabled = true`):
- `do_tarot_reading(question, layout?, generate_image?)` — defaults `layout="three_card"`, image off
- `do_runes_reading(question, layout?, generate_image?)` — defaults `layout="three_runes"`, image off

When invoked via LLM tool, the handler **does not send a text bot message**. The interpretation is returned in the JSON tool result so the host LLM can use it directly. Only the generated image (if enabled and successful) is sent to the user. Tool return shape:
```json
{"done": true, "summary": "Drew 3 symbol(s) with the three_card layout (system=tarot).", "interpretation": "<full LLM-generated text>", "imageGenerated": true}
```

**Chat settings keys** (defined in [`internal/bot/models/chat_settings.py`](../../internal/bot/models/chat_settings.py); defaults under `[bot.defaults]` in [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml)):

| `ChatSettingsKey` enum | Setting key | Page | Notes |
|---|---|---|---|
| `TAROT_SYSTEM_PROMPT` | `tarot-system-prompt` | `LLM_BASE` | System prompt for tarot interpretations |
| `RUNES_SYSTEM_PROMPT` | `runes-system-prompt` | `LLM_BASE` | System prompt for rune interpretations |
| `DIVINATION_USER_PROMPT_TEMPLATE` | `divination-user-prompt-template` | `BOT_OWNER_SYSTEM` | Template for the user message sent to the LLM |
| `DIVINATION_IMAGE_PROMPT_TEMPLATE` | `divination-image-prompt-template` | `BOT_OWNER_SYSTEM` | Template used when `image-generation = true` |
| `DIVINATION_REPLY_TEMPLATE` | `divination-reply-template` | `BOT_OWNER_SYSTEM` | Template for the user-visible reply on the **slash-command path only** (`/taro`, `/runes`). Placeholders: `{layoutName}`, `{drawnSymbolsBlock}`, `{interpretation}`. The LLM-tool path still returns the bare interpretation in JSON and does not use this template. |
| `DIVINATION_DISCOVERY_SYSTEM_PROMPT` | `divination-discovery-system-prompt` | `BOT_OWNER_SYSTEM` | System instruction for layout discovery (both web search and parsing LLM calls) |
| `DIVINATION_DISCOVERY_INFO_PROMPT` | `divination-discovery-info-prompt` | `BOT_OWNER_SYSTEM` | Prompt for web search LLM call (finds layout info via web_search tool) |
| `DIVINATION_DISCOVERY_STRUCTURE_PROMPT` | `divination-discovery-structure-prompt` | `BOT_OWNER_SYSTEM` | Prompt for structured JSON parsing LLM call (converts description to schema) |

User-template placeholders: `{userName}`, `{question}`, `{layoutName}`, `{positionsBlock}`, `{cardsBlock}`.
Image-template placeholders: `{layoutName}`, `{spreadDescription}`, `{styleHint}`.
Reply-template placeholders: `{layoutName}` (Russian layout name), `{drawnSymbolsBlock}` (numbered list of drawn symbols with position, name, and reversal flag), `{interpretation}` (raw LLM-generated text).
Discovery-info-template placeholders: `{systemId}`, `{layoutName}`.
Discovery-structure-template placeholders: `{description}` (from web search results).

---

### `[stats]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `enabled` | bool | `false` | Master switch for statistics collection |
| `llm-stats-data-source` | str | `"default"` | Database data source for LLM stats storage |

**Note:** Disabled by default until aggregation trigger and query API are implemented. When enabled, `DatabaseStatsStorage` is initialized in `main.py` and passed to `LLMManager` for recording LLM usage metrics. Statistics are stored in the data source specified by `llm-stats-data-source` (default: "default") with `stat_events` (append-only log) and `stat_aggregates` (period buckets) tables created by `migration_016`.

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
| `getStatsConfig()` | `Dict[str, Any]` | `[stats]` section |

---

## 4. Adding Configuration

### Step 1: Add getter to ConfigManager

**File:** [`internal/config/manager.py`](../../internal/config/manager.py:180)

```python
def getMyFeatureConfig(self) -> Dict[str, Any]:
    """Get my feature configuration

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

*This guide is auto-maintained and should be updated whenever configuration sections change*
*Last updated: 2026-05-09*
