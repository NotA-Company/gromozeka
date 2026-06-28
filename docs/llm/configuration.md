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
| `providers.<name>.parameters.use-proxy` | bool | Enable proxy routing for this provider (sqlink only; requires `[proxy].enabled = true`) |
| `providers.<name>.parameters.proxy.type` | str | Proxy protocol override for this provider: `"http"` or `"socks5"` |
| `providers.<name>.parameters.proxy.address` | str | Proxy address override for this provider |
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

**Proxy support for sqlink providers:** sqlink uses HTTP/HTTPS internally and supports proxy routing. Enable it with `use-proxy = true` under `[database.providers.<name>.parameters]` (requires `[proxy].enabled = true` globally). Optionally override the global proxy with a `[database.providers.<name>.parameters.proxy]` sub-table.

**IMPORTANT:** The `use-proxy` and `proxy` keys for sqlink must be nested under `parameters`, not directly under the provider block. `getSqlProvider()` extracts `config["parameters"]` and forwards it to the provider constructor. Keys at the provider-block level are ignored. If overriding the global proxy with a per-provider `[database.providers.<name>.parameters.proxy]` sub-table, include `enabled = true` inside the sub-table for the override to take effect (see proxy task memory for `fromServiceConfig` semantics).

```toml
# Example: sqlink provider with proxy
[database.providers.archive]
provider = "sqlink"

[database.providers.archive.parameters]
url = "https://sqlink.example.com"
user = "bot"
password = "${SQLINK_PASSWORD}"
database = "archive"
timeout = 30
keepConnection = true
use-proxy = true
# [database.providers.archive.parameters.proxy]
# type = "http"
# address = "${DB_PROXY_ADDRESS}"
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
- `yc-sdk` — Yandex Cloud native SDK (supports `auth_type`: `"auto"`, `"api_key"`, `"iam_token"`, `"yc_cli"`)
- `custom-openai` — Custom OpenAI-compatible API

**YC SDK auth configuration (`auth_type`):**
- `"auto"` (default) — detects `YC_API_KEY` env var, then `YC_IAM_TOKEN`, then falls back to `yc` CLI
- `"api_key"` — uses `api_key` from config or `YC_API_KEY` env var
- `"iam_token"` — uses `iam_token` from config or `YC_IAM_TOKEN` env var
- `"yc_cli"` — uses `yc` CLI (requires `yc_profile` for non-default profiles)

**Model configuration keys:**

| Key | Type | Default | Purpose |
|-----|------|---------|---------|
| `provider` | str | required | Provider name from `[models.providers]` |
| `model_id` | str | required | Model identifier for API calls |
| `model_version` | str | `"latest"` | Model version string |
| `temperature` | float | required | Sampling temperature (0.0–2.0) |
| `context` | int | required | Max context window in tokens |
| `tier` | str | `"free"` | Access tier for rate limiting |
| `enabled` | bool | `true` | Whether model is available |
| `support_tools` | bool | `false` | Enable tool/function calling |
| `support_text` | bool | `true` | Enable text generation |
| `support_images` | bool | `false` | Enable image generation |
| `support_structured_output` | bool | `false` | Enable JSON schema output |
| `image_generation_api` | str | unset | Image transport: `"openai-images"` for Images API, unset for chat-completions |
| `image_options` | table | `{}` | Whitelisted image generation options |

**Image generation configuration:**

The `image_generation_api` key selects the transport for image generation:

| Value | Transport | Description |
|-------|-----------|-------------|
| unset or any other | Chat-completions | Uses `chat.completions.create()` with `modalities = ["image", "text"]` |
| `"openai-images"` | OpenAI Images API | Uses `client.images.generate()` directly |

**Provider support:** Any OpenAI-compatible provider (any ``BasicOpenAIModel``
subclass) can use ``image_generation_api = "openai-images"`` by setting it in the
model config. Providers that don't set it continue using the chat-completions
image path by default.

When `image_generation_api = "openai-images"`, the `image_options` table provides
model-level defaults for image requests. Only whitelisted keys are forwarded:

| Key | Type | Example | Purpose |
|-----|------|---------|---------|
| `size` | str | `"1024x1024"` | Image dimensions |
| `quality` | str | `"hd"` | Image quality level |
| `output_format` | str | `"png"` | Output format: `"png"`, `"jpeg"`, `"webp"` |
| `background` | str | `"transparent"` | Background type |
| `moderation` | str | `"low"` | Content moderation level |
| `n` | int | `1` | Number of images to generate |
| `response_format` | str | `"b64_json"` | Response format |
| `user` | str | `"user-123"` | User identifier for tracking |

**Example — Yandex Cloud image model:**
```toml
[models.models."aliceai-image-art"]
provider                 = "yc-openai"
model_id                 = "aliceai-image-art-3.0"
model_version            = "latest"
temperature              = 0.2
context                  = 500
support_tools            = false
support_text             = false
support_images           = true
support_structured_output = false
image_generation_api     = "openai-images"
tier                     = "paid"

[models.models."aliceai-image-art".image_options]
size           = "1024x1024"
output_format  = "png"
```

**Security note:** The `image_options` table is whitelisted to prevent arbitrary
config keys from being forwarded to the API. Only the keys listed above are
recognized; unknown keys are silently ignored.

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

### `[search-history]`

Chat-history semantic search configuration. Defaults live in [`configs/00-defaults/search-history.toml`](../../configs/00-defaults/search-history.toml). The `ChatSearchHandler` is registered conditionally on `enabled = true`; the per-chat `EMBEDDINGS_ENABLED` setting must also be on for messages in a given chat to be embedded and searched.

| Key | Type | Default | Purpose |
|---|---|---|---|
| `enabled` | bool | `false` | Master switch — operator must flip to register `ChatSearchHandler` and enable the `get_summary` LLM tool |

#### `[search-history.embeddings]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `reindex-batch-size` | int | `100` | Per-batch page size for the backfill `CRON_JOB` handler in `ChatSearchHandler._dtCronJob` (`getMessagesWithoutEmbeddings(limit=...)`) |

The default `EMBEDDING_MODEL` is the per-chat chat-setting default wired under `[bot.defaults].embedding-model` in [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml) (currently `"local-embedding"`). A previous server-wide `[search-history.embeddings].model` key was removed because the per-chat default already provides the value, and `ChatSearchHandler._dtCronJob` resolves the model from the chat's `EMBEDDING_MODEL` setting (with no model being a silent no-op for that chat on that tick). There is no in-memory embedding cache in the DB layer — that responsibility belongs to the handler layer (via `CacheService`) and is intentionally not implemented at the repository level (decoded embeddings are re-loaded from `message_embeddings` on every search).

The `MessagePreprocessorHandler.newMessageHandler` always schedules a background embedding task after a successful `saveChatMessage` when both `[search-history].enabled` (cached in `_searchEnabled` at construction time) and the per-chat `EMBEDDINGS_ENABLED` setting are on — there is no per-config kill switch on the dispatch path. To stop embedding generation entirely, set `[search-history].enabled = false` and restart the bot, or clear `EMBEDDINGS_ENABLED` for individual chats.

#### `[search-history.defaults]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `max-results` | int | `10` | Default `limit` passed to `chatMessages.searchChatMessages` by the `/search` command |
| `default-days` | int | `30` | Default `maxAgeDays` for the `/search` command when `days:` is not specified |

**Chat settings keys** (defined in [`internal/bot/models/chat_settings.py`](../../internal/bot/models/chat_settings.py); defaults under `[bot.defaults]` in [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml)):

| `ChatSettingsKey` enum | Setting key | Page | Type | Notes |
|---|---|---|---|---|
| `EMBEDDING_MODEL` | `embedding-model` | `BOT_OWNER` | `STRING` | Per-chat embedding model override. Resolved by `ChatSearchHandler._dtCronJob` (backfill) and the `MessagePreprocessorHandler` embedding dispatch from the per-chat `EMBEDDING_MODEL` setting (default `"local-embedding"` from `bot-defaults.toml`). `STRING` rather than `MODEL` because the existing `MODEL` picker does not filter on `support_embeddings` |
| `EMBEDDINGS_ENABLED` | `embeddings-enabled` | `BOT_OWNER` | `BOOL` | Per-chat kill-switch. Required for `MessagePreprocessorHandler` to embed a message after save; the `get_summary` LLM tool works regardless (it only reads `chat_messages`, not `message_embeddings`) |
| `REGENERATE_EMBEDDINGS` | `regenerate-embeddings` | `BOT_OWNER` | `BOOL` | One-shot trigger. Setting it to `"true"` makes `ChatSearchHandler._dtCronJob` re-walk all un-embedded (or model-mismatched) messages for the chat. The flag **must be manually reset** via `/settings` after re-embedding is complete — it does not self-reset. |
| `MAX_MESSAGES_FOR_SEMANTIC_SEARCH` | `max-messages-for-semantic-search` | `BOT_OWNER` | `INT` | Cap on per-chat backfill volume. Read by `ChatSearchHandler._dtCronJob`; falls back to `100_000` on missing / unparsable / non-positive values |

**Slash command** (category `CommandCategory.TOOLS`, permission `CommandPermission.DEFAULT`):
- `/search [args]` — parse a small DSL of `key: value` filters, then AI-summarise the matches. Arguments:
  - `keywords: <text>` — substring filter on `message_text` (case-insensitive). The first known key wins; tokens without a key prefix are merged into `keywords`. Multiple `keywords:` occurrences are concatenated.
  - `user: @username` — resolve against `chat_users.username` (case-insensitive) via `chatUsers.getChatUsers`.
  - `days: N` — `maxAgeDays` window. Defaults to `[search-history.defaults].default-days`.
  - `category: user|bot|system|channel` — filter by `MessageCategory` group (see `_CATEGORY_GROUPS` in `chat_search.py`).
  - `thread: <message_id>` — restrict to a thread (`root_message_id`).
  - Example: `/search keywords: meeting days: 7 user: @alice`.

**LLM tool** (always registered when `ChatSearchHandler` is constructed, gated only by the handler-level `[search-history].enabled` switch):
- `get_summary(scope, value?, thread_message_id?, from_date?, until_date?)` — recaps a slice of chat history. Scopes: `last_hours` (default 24h), `last_days` (default 7), `last_messages` (default 100, hard-capped at 500), `thread` (uses `thread_message_id`), `date_range` (uses `from_date` and `until_date` ISO-8601 strings). Returns a dict with `done`, `summary`, `messageCount`, `scopeDescription`, and (on error) `error`. Gated by the chat's `ALLOW_TOOLS_COMMANDS` setting.

**Per-chat backfill:** Even when a chat only just opted in to `EMBEDDINGS_ENABLED`, the `ChatSearchHandler._dtCronJob` `CRON_JOB` tick (every 60s) will close the gap for chats with `EMBEDDINGS_ENABLED = true` and no `message_embeddings` rows (greedy pass), plus any chat with `REGENERATE_EMBEDDINGS = true` (explicit trigger). Per-tick batch size is capped at `[search-history.embeddings].reindex-batch-size` (default 100 messages) with a small inter-message sleep (`BACKFILL_INTER_MESSAGE_DELAY_SECS = 0.1`) so a long pass does not monopolise the asyncio loop; the next tick picks up where the previous one stopped, so a backlog naturally walks down minute by minute. There is no separate `BackfillWorker` class — the backfill duty lives in `ChatSearchHandler`.

---

### `[proxy]`

Global proxy configuration for routing outbound HTTP traffic through an HTTP or SOCKS5 proxy. Defaults live in [`configs/00-defaults/proxy.toml`](../../configs/00-defaults/proxy.toml).

| Key | Type | Default | Purpose |
|---|---|---|---|
| `enabled` | bool | `false` | Master kill-switch. When `false`, NO service uses proxy regardless of per-service `use-proxy` flags. |
| `type` | `"http"` \| `"socks5"` | `"http"` | Proxy protocol type. |
| `address` | str | `""` | Full proxy URL including scheme and port (e.g., `"http://proxy:8080"`, `"socks5://proxy:1080"`). Use `${ENV_VAR}` substitution for secrets. |
| `user` | str | `""` | Username for proxy authentication. Leave empty if no auth. Use `${ENV_VAR}` substitution. |
| `password` | str | `""` | Password for proxy authentication. Leave empty if no auth. Use `${ENV_VAR}` substitution. |

**Resolution model:** The `[proxy]` section is a global default. Individual services opt in with `use-proxy = true` in their own config section and can override the global proxy with a `[<service>.proxy]` sub-table (with the same `type`, `address`, `user`, `password` keys). Resolution is handled by the `ProxyConfig` class in [`lib/proxy/__init__.py`](../../lib/proxy/__init__.py), using `ProxyConfig.fromServiceConfig()` for per-service resolution and `ProxyConfig.getCombined()` to merge with the global config. `ProxyHelper.getInstance().setGlobalProxyConfig()` is called once from `main.py` to store the global config.

**Example — enable proxy for a specific service:**

```toml
# configs/local/proxy.toml
[proxy]
enabled = true
type = "http"
address = "${PROXY_ADDRESS}"
user = "${PROXY_USER}"
password = "${PROXY_PASSWORD}"

# In the service's config (e.g., bot-defaults.toml or 00-config.toml):
[yandex-search]
enabled = true
use-proxy = true          # Opt this service into the global proxy
api-key = "${YANDEX_API_KEY}"
```

**Example — per-service override:**

```toml
[openweathermap]
enabled = true
use-proxy = true
api-key = "${OWM_API_KEY}"

[openweathermap.proxy]
enabled = true              # REQUIRED: without this, the override is silently ignored
type = "socks5"
address = "${OWM_PROXY_ADDRESS}"
user = ""
password = ""
```

**When `enabled` is omitted from the `[service.proxy]` sub-section**, `ProxyConfig.fromServiceConfig()` produces a config with `enabled=False`, which `getCombined()` treats as "inherit from global." The per-service override fields (`type`, `address`, etc.) are ignored. Always include `enabled = true` when you intend to override the global proxy for a specific service.

#### `[proxy.lifecycle]`

Optional sub-section for managing the proxy process lifecycle (start, health-check, restart, stop). Omit the entire section to disable lifecycle management. Defaults live in [`configs/00-defaults/proxy.toml`](../../configs/00-defaults/proxy.toml).

| Key | Type | Default | Purpose |
|---|---|---|---|
| `start-command` | list[str] | `[]` | Command and arguments to start the proxy process. Executed via `asyncio.create_subprocess_exec` on startup. |
| `stop-command` | list[str] | `[]` | Command to stop the proxy process. Executed on shutdown and before restart (if no `restart-command`). |
| `restart-command` | list[str] | `[]` | Command to restart the proxy. Optional — if omitted, restart = stop + start sequentially. |
| `health-check-type` | `"none"` \| `"url"` \| `"command"` | `"none"` | Health check mechanism. `"none"`: no monitoring. `"url"`: HTTP GET through the proxy; 2xx = pass. `"command"`: run command; exit 0 = pass. |
| `health-check-url` | str | `""` | URL to probe when `health-check-type = "url"`. |
| `health-check-command` | list[str] | `[]` | Command to run when `health-check-type = "command"`. |
| `health-check-interval` | int | `5` | Health check interval in minutes. The CRON_JOB fires every ~60s; the check runs every Nth tick (gated by modulo counter). |

**Example:**
```toml
[proxy]
enabled = true
type = "socks5"
address = "socks5://localhost:1080"

[proxy.lifecycle]
start-command = ["ssh", "-D", "1080", "-N", "proxy-host"]
stop-command = ["pkill", "-f", "ssh -D 1080"]
health-check-type = "url"
health-check-url = "http://httpbin.org/ip"
health-check-interval = 5
```

**Services that support proxy:** Telegram bot, Max Messenger bot, all OpenAI-compatible LLM providers, OpenRouter `listRemoteModels()`, image downloads, Yandex Search (including web-fetch), OpenWeatherMap, Geocode Maps, sqlink database providers.

**Restart required:** Proxy config is loaded at startup. Changing it requires a bot restart.

---

### `[sandbox]`

Sandboxed code execution configuration. Defaults live in [`configs/00-defaults/sandbox.toml`](../../configs/00-defaults/sandbox.toml). The handler is registered conditionally on `enabled = true` and per-chat gated by the `allow-sandbox` chat setting.

| Key | Type | Default | Purpose |
|---|---|---|---|
| `enabled` | bool | `false` | Master switch — operator must flip to register `SandboxHandler` |

#### `[sandbox.storage]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `root-dir` | str | `"/var/lib/gromozeka/sandbox"` | Host-side root directory for sandbox workspaces and data |
| `dir-mode` | str (octal) | `"0o700"` | Octal permission mode for created directories |
| `file-mode` | str (octal) | `"0o600"` | Octal permission mode for created files |

#### `[sandbox.backend]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `name` | str | `"docker"` | Execution backend (`"docker"` is the only backend currently) |

#### `[sandbox.backend.docker]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `base-url` | str | `"unix:///var/run/docker.sock"` | Docker daemon socket URL or TCP address |
| `image-pull-policy` | str | `"if-not-present"` | When to pull images: `"never"`, `"if-not-present"`, or `"always"` |

#### `[sandbox.defaults]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `idle-ttl-minutes` | int | `30` | Minutes of inactivity before a session is eligible for GC |

#### `[sandbox.limits]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `memory-mb` | int | `512` | Memory limit per container in megabytes |
| `memory-swap-mb` | int | `512` | Swap memory limit in megabytes (same as `memory-mb` means no swap) |
| `cpu-count` | float | `1.0` | CPU count limit per container |
| `pids-limit` | int | `64` | Maximum number of PIDs inside the container |
| `timeout-seconds` | int | `30` | Default run timeout in seconds |
| `timeout-grace-seconds` | int | `5` | Grace period after timeout before killing the container |

#### `[sandbox.security]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `user` | str | `"1000:1000"` | `uid:gid` for the container process |
| `read-only-rootfs` | bool | `true` | Mount the container root filesystem as read-only |
| `no-new-privileges` | bool | `true` | Prevent privilege escalation inside the container |
| `drop-capabilities` | list[str] | `["ALL"]` | Linux capabilities to drop |
| `privileged` | bool | `false` | Run the container in privileged mode (dangerous) |

#### `[sandbox.concurrency]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `max-queued-runs-per-session` | int | `4` | Maximum queued runs per session before rejecting |
| `max-concurrent-runs-global` | int | `8` | Maximum concurrent runs across all sessions |
| `global-queue-wait-seconds` | int | `60` | Maximum seconds a run waits in the global queue |

#### `[sandbox.gc]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `enabled` | bool | `true` | Enable the GC loop |
| `orphan-container-retention-minutes` | int | `10` | Minutes to retain orphaned containers |
| `orphan-workspace-retention-minutes` | int | `60` | Minutes to retain orphaned workspace directories |
| `run-retention-minutes` | int | `1440` | Minutes to retain completed run records |

#### `[sandbox.runtimes.python]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `run-image-tag` | str | `"gromozeka-sandbox-python:run"` | Docker image tag for code execution |
| `install-image-tag` | str | `"gromozeka-sandbox-python:install"` | Docker image tag for library installation |
| `run-dockerfile` | str | `"lib/sandbox/runtimes/python/Dockerfile"` | Path to the Dockerfile for the run image |
| `install-dockerfile` | str | `"lib/sandbox/runtimes/python/Dockerfile.install"` | Path to the Dockerfile for the install image |
| `lib-mount-path` | str | `"/sandbox/libs"` | Container-side path where the library pool is mounted |

#### `[sandbox.runtimes.python.env]`

Default environment variables injected into Python containers. Keys are variable names, values are strings.

| Key | Default | Purpose |
|---|---|---|
| `PYTHONUNBUFFERED` | `"1"` | Disable Python output buffering |
| `PYTHONDONTWRITEBYTECODE` | `"1"` | Don't write `.pyc` files |
| `MPLBACKEND` | `"Agg"` | Matplotlib non-interactive backend |
| `PYTHONPATH` | `"/sandbox/libs"` | Python module search path |

#### `[sandbox.runtimes.python.install-container]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `timeout-seconds` | int | `600` | Wall-clock timeout for the install container |
| `memory-mb` | int | `1024` | Memory limit for the install container in megabytes |
| `pids-limit` | int | `256` | Maximum PIDs inside the install container |

#### `[sandbox.bootstrap]`

Used by `scripts/sandbox_bootstrap.py` — not by the library itself.

| Key | Type | Default | Purpose |
|---|---|---|---|
| `starter-packages` | list[str] | `["numpy", "pandas", "matplotlib", ...]` | Packages pre-installed into the install image during bootstrap |

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
| `getProxyConfig()` | `Dict[str, Any]` | `[proxy]` section |
| `getSearchHistoryConfig()` | `Dict[str, Any]` | `[search-history]` section (returns `{}` when missing) |

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
*Last updated: 2026-06-26*
