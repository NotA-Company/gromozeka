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
| `use-proxy` | bool | Route bot platform traffic through the global proxy (requires `[proxy].enabled = true`) |
| `max-ca-bundle` | str | Directory with additional PEM CA certs for the Max API (`platform-api2.max.ru`, Минцифры CA). Path relative to `application.root-dir` (typically `storage/`). Default: `"../certs/max"` resolves to `<repo-root>/certs/max/`. Set to `""` to use system CAs. Max mode only. |
| `defaults` | dict | Default chat settings for all chats |
| `private-defaults` | dict | Default settings for private chats |
| `group-defaults` | dict | Default settings for group chats |
| `tier-defaults` | dict | Tier-specific default settings |

**IMPORTANT:** `bot_owners` can be username OR int ID — both are valid. Handle both types in owner checks

#### `[bot.defaults]` LLM base prompts (`random-answer-prompt`, `chat-prompt`, `chat-prompt-suffix`)

Core LLM system-prompt settings applied to `LLMMessageHandler` paths. Defined in [`internal/bot/models/chat_settings.py`](../../internal/bot/models/chat_settings.py); defaults under `[bot.defaults]` in [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml).

| `ChatSettingsKey` enum | Setting key | Type | Page | Notes |
|---|---|---|---|---|
| `CHAT_PROMPT` | `chat-prompt` | STRING | `LLM_BASE` | Base system prompt ("bot personality"). Used by all three LLM handler paths (`handleReply`, `handleMention`, `handleRandomMessage`). |
| `CHAT_PROMPT_SUFFIX` | `chat-prompt-suffix` | STRING | `BOT_OWNER_SYSTEM` | Suffix appended to `chat-prompt` on every LLM path. Describes the structured message-JSON fields the chat model sees (`userData`, `mediaDescription`, etc.) — do not change outside testing. (The former `userSummary` line was dropped in Phase 4b when the `<user-memories>` block replaced per-message summary injection.) |
| `RANDOM_ANSWER_PROMPT` | `random-answer-prompt` | STRING | `LLM_BASE` | Extra system-prompt fragment appended **only inside `handleRandomMessage`** (both thread and non-thread assembly paths). Tells the model it is overhearing a chat rather than being addressed, and defines the `<skip>` abstention sentinel (see below). Never appended in `handleReply` / `handleMention`. |

The default `random-answer-prompt` is a Russian triple-string (full text in [`bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml)); its key lines:
- States the bot is **not** being addressed directly — it is one participant in an ongoing chat and merely saw the latest message in the feed.
- Rules: no clarifying questions, no greeting/farewell without cause, join in only with something natural and brief, otherwise return exactly `<skip>`.

##### `<skip>` abstention sentinel convention

When the model decides it has nothing to add, it returns exactly `<skip>` (optionally surrounded by whitespace and/or backticks). Detection runs inside [`_sendLLMChatMessage`](../../internal/bot/common/handlers/llm_messages.py) — **after** `<media-description>` extraction, **before** the image-generation branch (so `<skip>` never triggers image generation). The JSON-unwrap that precedes it runs **only in TEXT-format chats** (a heuristic for models that emit JSON despite being asked for text), so a JSON-wrapped `{"text": "<skip>"}` abstains **only in TEXT-format chats**; in explicit JSON-format chats the raw JSON string won't match `== "<skip>"` and this path cannot abstain — an accepted v1 limitation (plan §3 non-goals defer JSON-shape `<skip>` recognition):

```python
if lmRetText.strip().strip("`").strip() == "<skip>":
    return LLMReplyOutcome.SKIPPED_BY_MODEL
```

On `SKIPPED_BY_MODEL`, `handleRandomMessage` returns `False` → `newMessageHandler` falls through to `HandlerResultStatus.NEXT` (nothing is sent). Only `random-answer-prompt` asks for `<skip>`, but the check is global in `_sendLLMChatMessage`; see [`handlers.md`](handlers.md) "Random-answer context & model abstention" for the full `LLMReplyOutcome` plumbing.

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

Defaults live in [`configs/00-defaults/resender.toml`](../../configs/00-defaults/resender.toml). The handler is disabled by default and registered conditionally on `enabled = true`.

| Key | Type | Default | Purpose |
|---|---|---|---|
| `enabled` | bool | `false` | Enable resender handler |

**Job keys** (`[[resender.jobs]]` entries; see `ResendJob` in [`internal/bot/common/handlers/resender.py`](../../internal/bot/common/handlers/resender.py)):

| Key | Type | Default | Purpose |
|---|---|---|---|
| `id` | str | _(required)_ | Unique job identifier; used in the `resender:{id}:lastMessageDate` settings key |
| `dataSource` | str | _(required)_ | Name of the data source to read messages from |
| `sourceChatId` | int | _(required)_ | Source chat ID to resend messages from |
| `sourceTheadId` | int | `None` | Optional source thread ID to filter messages from |
| `targetChatId` | int | _(required)_ | Target chat ID to resend messages to |
| `forwardTo` | array of dicts | `[]` (empty) | List of additional chats to natively forward the resent message to. Each entry is a dict with keys: `chatId` (int, required), `threadId` (int, optional), `notify` (bool, optional). Forwarding is best-effort — failures are logged but don't block the main resend. |
| `messageTypes` | array of str | _(required)_ | Sequence of message categories to resend (e.g. `["user"]`) |
| `messagePrefix` | str | `""` | Optional prefix prepended to resent messages (supports template placeholders) |
| `messageSuffix` | str | `""` | Optional suffix appended to resent messages (supports template placeholders) |
| `lastMessageDate` | str/datetime | `None` | Cursor — timestamp of the last processed message (ISO string or `datetime`) |
| `notification` | bool | `None` | Notification override for the resent message (`None` = platform default) |
| `mediaGroupDelaySecs` | float | `10.0` | Delay used to coalesce media-group messages before resending |

**Resender jobs config:**
```toml
[[resender.jobs]]
id = "telegram-to-max"
dataSource = "telegram-ro"
sourceChatId = -1001234567890
targetChatId = 9876543210
messageTypes = ["user"]
mediaGroupDelaySecs = 10.0  # Optional, defaults to 10.0

# Optional: forward the resent message to additional chats (best-effort).
# Each entry is a separate forward target. Forward failures are logged and
# do not block the primary resend or cursor advancement.
# forwardTo = [
#     { chatId = -456, threadId = 0, notify = true },
# ]
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
| `enabled` | bool | `false` | Master switch — operator must flip to register `ChatSearchHandler` and enable the `search_messages`, `list_users`, `get_thread` LLM tools |

#### `[search-history.embeddings]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `reindex-batch-size` | int | `100` | Per-batch page size for the backfill `CRON_JOB` handler in `ChatSearchHandler._dtCronJob` (`getMessagesWithoutEmbeddings(limit=...)`) |

The default `EMBEDDING_MODEL` is the per-chat chat-setting default wired under `[bot.defaults].embedding-model` in [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml) (currently `"local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"`). A previous server-wide `[search-history.embeddings].model` key was removed because the per-chat default already provides the value, and `ChatSearchHandler._dtCronJob` resolves the model from the chat's `EMBEDDING_MODEL` setting (with no model being a silent no-op for that chat on that tick). There is no in-memory embedding cache in the DB layer — that responsibility belongs to the handler layer (via `CacheService`) and is intentionally not implemented at the repository level (decoded embeddings are re-loaded from `message_embeddings` on every search).

The `MessagePreprocessorHandler.newMessageHandler` always schedules a background embedding task after a successful `saveChatMessage` when both `[search-history].enabled` (cached in `_searchEnabled` at construction time) and the per-chat `EMBEDDINGS_ENABLED` setting are on — there is no per-config kill switch on the dispatch path. To stop embedding generation entirely, set `[search-history].enabled = false` and restart the bot, or clear `EMBEDDINGS_ENABLED` for individual chats.

#### `[search-history.defaults]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `max-results` | int | `10` | Default `limit` passed to `chatMessages.searchChatMessages` by the `/search` command |
| `default-days` | int | `30` | Default `maxAgeDays` for the `/search` command when `days:` is not specified |

**Chat settings keys** (defined in [`internal/bot/models/chat_settings.py`](../../internal/bot/models/chat_settings.py); defaults under `[bot.defaults]` in [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml)):

| `ChatSettingsKey` enum | Setting key | Page | Type | Notes |
|---|---|---|---|---|
| `EMBEDDING_MODEL` | `embedding-model` | `BOT_OWNER` | `STRING` | Per-chat embedding model override. Resolved by `ChatSearchHandler._dtCronJob` (backfill) and the `MessagePreprocessorHandler` embedding dispatch from the per-chat `EMBEDDING_MODEL` setting (default `"local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"` from `bot-defaults.toml`). `STRING` rather than `MODEL` because the existing `MODEL` picker does not filter on `support_embeddings` |
| `EMBEDDINGS_ENABLED` | `embeddings-enabled` | `BOT_OWNER` | `BOOL` | Per-chat kill-switch. Required for `MessagePreprocessorHandler` to embed a message after save; the LLM tools (`search_messages`, `list_users`, `get_thread`) work regardless (they only read `chat_messages`, not `message_embeddings`) |
| `REGENERATE_EMBEDDINGS` | `regenerate-embeddings` | `BOT_OWNER` | `BOOL` | One-shot trigger. Setting it to `"true"` makes `ChatSearchHandler._dtCronJob` re-walk all un-embedded (or model-mismatched) messages for the chat. The flag **must be manually reset** via `/settings` after re-embedding is complete — it does not self-reset. |
| `MAX_MESSAGES_FOR_SEMANTIC_SEARCH` | `max-messages-for-semantic-search` | `BOT_OWNER` | `INT` | Cap on per-chat backfill volume. Read by `ChatSearchHandler._dtCronJob`; falls back to `100_000` on missing / unparsable / non-positive values |

**Slash command** (category `CommandCategory.TOOLS`, permission `CommandPermission.DEFAULT`):
- `/search [args]` — parse a small DSL of `key: value` filters, then return matching messages as a raw, human-readable list (no LLM summary). Arguments:
  - `keywords: <text>` — substring filter on `message_text` (case-insensitive). The first known key wins; tokens without a key prefix are merged into `keywords`. Multiple `keywords:` occurrences are concatenated.
  - `user: @username` — resolve against `chat_users.username` (case-insensitive) via `chatUsers.getChatUsers`.
  - `days: N` — `maxAgeDays` window. Defaults to `[search-history.defaults].default-days`.
  - `category: user|bot|system|channel` — filter by `MessageCategory` group (see `_CATEGORY_GROUPS` in `chat_search.py`).
  - `thread: <message_id>` — restrict to a thread (`root_message_id`).
  - `chat: <chat_id>` — search in another chat (requires admin privileges).
  - Example: `/search keywords: meeting days: 7 user: @alice`.
  - Example: `/search chat: -1001234567890 days: 3`.

- `/users [limit=N] [min_messages=N] [last_active=N]` — list chat participants with activity statistics. Arguments:
  - `limit: N` — max users to return. Defaults to the handler's default.
  - `min_messages: N` — minimum message count for inclusion. Defaults to 1.
  - `last_active: N` — only users active within last N days.
  - Example: `/users`, `/users limit=20 min_messages=100`.

**LLM tools** (always registered when `ChatSearchHandler` is constructed, gated only by the handler-level `[search-history].enabled` switch, each gated by the chat's `ALLOW_TOOLS_COMMANDS` setting):
- `search_messages(query, limit?, max_age_days?, user_name?, thread_message_id?)` — semantic search over chat history. Uses embeddings to find messages similar to `query`. `limit` defaults to `[search-history.defaults].max-results` (10). `max_age_days` defaults to `[search-history.defaults].default-days` (30). `user_name` filters by username. `thread_message_id` restricts to a thread. Returns matching message texts with metadata.
- `list_users(limit?, min_messages?)` — list chat participants with activity statistics. `limit` defaults to 50, `min_messages` defaults to 1. Returns username, display name, and message count per user.
- `get_thread(message_id)` — retrieve full conversation thread for a given root message. Returns all messages in chronological order.

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

### `[webhook-receiver]`

Max Messenger webhook receiver configuration. Defaults live in [`configs/00-defaults/webhook-receiver.toml`](../../configs/00-defaults/webhook-receiver.toml). This section is read by **both** the standalone webhook receiver process ([`internal/max_webhook_receiver/`](../../internal/max_webhook_receiver/)) and the bot process (Max mode). See [`architecture.md`](architecture.md) ADR-013 for the two-process model.

| Key | Type | Default | Purpose |
|---|---|---|---|
| `enabled` | bool | `false` | Master switch for the **bot**. When `true`, the bot's `MaxBotClient` polls the local receiver's `GET /updates` (via `base-polling-url`) instead of long-polling `platform-api2.max.ru`. The receiver process always runs regardless of this flag. |
| `register-webhook` | bool | `true` | Whether the **bot** registers the webhook subscription with Max on startup (`POST /subscriptions`). Set `false` to manage the subscription externally. |
| `unregister-webhook` | bool | `false` | Whether the **bot** unregisters the webhook subscription on shutdown (`DELETE /subscriptions`). Independent of `register-webhook`; only applies when `enabled = true`. Defaults to `false` so a bot restart does not tear down the Max subscription; set `true` to clean up on shutdown. |
| `webhook-url` | str | `""` | Public HTTPS URL (port 443, CA-trusted cert) that Max POSTs to. Required when `register-webhook = true`. |
| `secret` | str | `"${MAX_WEBHOOK_SECRET}"` | Shared secret verifying webhook POSTs. Max sends it in the `X-Max-Bot-Api-Secret` header. Set via the `MAX_WEBHOOK_SECRET` env var — never commit the value. The receiver refuses to start when this is empty or an unresolved `${VAR}` placeholder; the bot likewise rejects an unresolved `${VAR}` whenever `enabled = true` and requires it non-empty when `register-webhook = true`. |
| `webhook-update-types` | list[str] | `[]` | Update types to subscribe to. Empty list = all types. |
| `base-polling-url` | str | `"http://127.0.0.1:8443"` | URL of the receiver's `GET /updates` endpoint. The bot polls this when `enabled = true`. Becomes `MaxBotClient.basePollingUrl` (trailing slash stripped). |
| `mark-on-subsequent-poll` | bool | `true` | Delivery semantics for `GET /updates`. When `true` (deferred mode, at-least-once), fetched updates are NOT marked processed on read — they are acknowledged only when the bot passes the returned marker back on its next poll (`markProcessedBeforeMarker`), so a crash between polls re-delivers unacknowledged updates. When `false` (immediate mode, at-most-once), updates are marked processed on read (`markProcessed`); a crash after serving but before handling loses them. |
| `listen-host` | str | `"127.0.0.1"` | Receiver HTTP listen address. Default localhost-only — use a reverse proxy for external TLS. |
| `listen-port` | int | `8443` | Receiver HTTP listen port. |
| `webhook-path` | str | `"/webhook"` | URL path for the webhook POST endpoint. Change if your reverse proxy routes to a different path. |
| `get-updates-secret` | str | `""` | Optional secret for the `GET /updates` endpoint (checked against the `Authorization` header). Empty disables the check — relies on localhost binding. The bot rejects an unresolved `${VAR}` here whenever `enabled = true` (it would otherwise be sent verbatim as the `Authorization` header). |
| `enable-cleanup` | bool | `true` | Whether the receiver's background task periodically deletes processed updates past the TTL. Set `false` to keep all updates indefinitely (useful for debugging). |
| `datasource` | str | `""` | Optional data source name (must match a `[database.providers]` entry) used by the receiver for all webhook DB operations. Empty uses the default database provider, so webhook data can live in a separate DB from the main bot. |
| `tls-cert-file` | str | unset | Optional path to a TLS cert. When both this and `tls-key-file` are set, the receiver serves HTTPS directly (no reverse proxy needed). |
| `tls-key-file` | str | unset | Optional path to a TLS key. See `tls-cert-file`. |

**Deployment modes:**
- **Reverse proxy (default)** — receiver binds `127.0.0.1:8443` plain HTTP; a reverse proxy (nginx/Caddy) terminates TLS and forwards to `<listen-host>:<listen-port>`.
- **Direct TLS** — set `tls-cert-file` + `tls-key-file` and the receiver serves HTTPS itself.

**Secrets discipline:** `secret` uses `${MAX_WEBHOOK_SECRET}` substitution. Document the env var name only — never paste the value. See [`docs/llm/tasks.md`](tasks.md) and root `AGENTS.md` for the project's secrets rules.

**Restart required:** Config is loaded at startup. Changing it requires restarting the receiver process (and the bot, for the bot-side keys).

---

### `[user-memory]`

Unified per-`(chat, user, thread)` structured memory system. Defaults live in [`configs/00-defaults/user-memory.toml`](../../configs/00-defaults/user-memory.toml). The feature is owned by `UserDataHandler` (see [`handlers.md`](handlers.md) `UserDataHandler` row, [`architecture.md`](architecture.md) ADR-016 for the unified-store decision and ADR-014 for the refinement machinery). Canonical durable summary: [`memories/user-memories.md`](memories/user-memories.md).

| Key | Type | Default | Purpose |
|---|---|---|---|
| `enabled` | bool | `false` | Global kill switch. When `false`, the refinement cron early-returns, the regen cron early-returns, AND the three memory tools (`add_memory`/`delete_memory`/`search_memories`) are not registered. Per-chat enable is a separate gate — the `memory-injection-enabled` chat setting (see "Memory chat settings" below). |

#### `[user-memory.thresholds]`

| Key | Type | Default | Purpose |
|---|---|---|---|
| `message-count` | int | `5` | Per-`(chat, user, thread)` new-message count that triggers a refinement run |
| `time-seconds` | int | `21600` | Max seconds since the last refinement run (in-memory `_lastRefinedTS`) before another is forced (6 hours) |
| `min-messages-to-refine` | int | `5` | Bail if fewer new messages are available (prevents refining tiny bursts) |
| `max-messages-per-run` | int | `128` | Cap on messages fed to a single refinement LLM call |
| `max-refines-per-tick` | int | `3` | Upper bound on refinement LLM calls per 60s cron tick |
| `memory-reindex-batch-size` | int | `50` | Per-tick cap on memory rows re-embedded by the regen cron (`_runMemoryEmbeddingRegen`) — mirrors `[search-history.embeddings].reindex-batch-size` for chat-history search |

#### `[user-memory.json-logging]`

Optional JSONL log of every successful memory-refinement run, mirroring the LLM-interaction logger (`AbstractModel.printJSONLog`). Read ONCE in `UserDataHandler.__init__` into `_refineLogEnabled` / `_refineLogFile` / `_refineLogAddDateSuffix` (same cache-once pattern as the other `[user-memory]` keys). The writer is a best-effort synchronous append guarded by `if self._refineLogEnabled:` so the default (off) does zero work on the hot path.

| Key | Type | Default | Purpose |
|---|---|---|---|
| `enabled` | bool | `false` | Kill switch for the per-run JSONL refinement log |
| `file` | str | `"logs/user-memory-refinement-json.log"` | Target JSONL file path |
| `add-date-suffix` | bool | `true` | Append a `.<YYYY-MM-DD>` (UTC) suffix to the filename (one file per day) |

**Logged fields** (one JSONL line per successful run, written via `utils.jsonDumps` = `json.dumps(ensure_ascii=False, default=str, sort_keys=True)`):

| Field | Type | Source |
|---|---|---|
| `date` | str | UTC ISO timestamp of the log write |
| `chatId` | int | Refined scope chat id |
| `threadId` | int | Refined scope thread id (`0` = main thread) |
| `userId` | int | Refined scope user id |
| `login` | str | User's `username` from `chat_users` (JOIN'd into the fetched messages; may be `""`) |
| `messagesCount` | int | Messages analyzed this run (≤ `max-messages-per-run`, default 128) |
| `firstMessageId` | str | Oldest analyzed message id (`MessageId.asStr()`) |
| `lastMessageId` | str | Newest analyzed message id (the cursor the refinement advances to) |
| `summary` | str | The new summary (stripped LLM output — the exact value persisted to `chat_users.metadata`) |
| `model` | str | Model id that served the request (`memory-refine-model`, or `memory-refine-fallback-model` when `result.isFallback`) |
| `elapsedTime` | float\|null | Seconds the LLM call took |

**Behavior notes:**

- **Success-path-only.** The hook sits in `_runRefinement` ([`internal/bot/common/handlers/user_data.py`](../../internal/bot/common/handlers/user_data.py)) AFTER the LLM returns and `newSummary` is bound, BEFORE the empty-summary early-return guard. An exception during the LLM call re-raises before the hook, so failed runs are NOT logged (mirrors `printJSONLog`).
- **Empty summaries ARE logged** (as `""`) — the hook runs before the `if not newSummary: return` guard, by design.
- **IO-failure tolerant.** The write is wrapped in `try/except OSError` with `logger.debug` on failure — a logging failure never breaks the refinement pipeline. This intentionally diverges from `printJSONLog`, which has no error handling.

#### Refinement prompts (chat settings)

The refinement prompts are **per-chat settings** (not `[user-memory.prompts]` config — that section was removed). Defaults live under `[bot.defaults]` in [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml) and can be overridden per chat. The Phase 4a rewrite switched the refinement pass from emitting a summary string to **curating the `user_memories` store live via the three tools**, so the user-prompt template now interpolates the rendered memory block (`{existingMemories}`) — the old `{existingUserData}` / `{existingSummary}` placeholders are kept as backward-compat aliases only (a per-chat override referencing them still formats without `KeyError`).

| `ChatSettingsKey` enum | Setting key | Type | Page | Purpose |
|---|---|---|---|---|
| `MEMORY_REFINE_SYSTEM_PROMPT` | `memory-refine-system-prompt` | STRING | `FRIEND` | System instruction for the refinement LLM call (tool-curation model — instructs the model to manage memories via `add_memory`/`delete_memory`/`search_memories`, maintain one permanent `type=bio` summary, and emit tool calls rather than a summary paragraph) |
| `MEMORY_REFINE_USER_PROMPT_TEMPLATE` | `memory-refine-user-prompt-template` | STRING | `FRIEND` | User message template. Placeholders: `{existingMemories}` (rendered permanent+recent block), `{messages}` (recent chat messages). Legacy aliases `{existingUserData}` / `{existingSummary}` still format but are no longer populated by the rewrite |

**Related `[bot.defaults]` keys** (in [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml)) — all are `ChatSettingsKey` defaults wired via the four-site convention:

| `ChatSettingsKey` enum | Setting key | Type | Page | Purpose |
|---|---|---|---|---|
| `MEMORY_REFINEMENT_ENABLED` | `memory-refinement-enabled` | BOOL | `FRIEND` | Per-chat gate for the refinement cron. Default `false`. Enabled for the friend tier via the local config overlay (`configs/common/` is gitignored — same model as `allow-sandbox`; see [`teamlead-memory.md`](teamlead-memory.md) "Configs Tracking Gotcha") |
| `MEMORY_REFINE_MODEL` | `memory-refine-model` | MODEL | `FRIEND` | Primary LLM for refinement runs (default `"openrouter/free"`) |
| `MEMORY_REFINE_FALLBACK_MODEL` | `memory-refine-fallback-model` | MODEL | `FRIEND` | Fallback when the primary fails (default `"aliceai-llm-flash"`) |
| `MEMORY_REFINE_SYSTEM_PROMPT` | `memory-refine-system-prompt` | STRING | `FRIEND` | System prompt for the refinement call (default in `bot-defaults.toml`) |
| `MEMORY_REFINE_USER_PROMPT_TEMPLATE` | `memory-refine-user-prompt-template` | STRING | `FRIEND` | User-prompt template with `{existingMemories}`/`{messages}` placeholders (legacy `{existingUserData}`/`{existingSummary}` aliases kept for backward-compat) |

#### Memory chat settings (injection + embeddings)

Four additional `ChatSettingsKey` defaults under `[bot.defaults]`, all `page = FRIEND`, wired via the four-site convention. These gate the chat-time **injection** of the `<user-memories>` block and the **regen cron** chat discovery (distinct from the refinement cron above):

| `ChatSettingsKey` enum | Setting key | Type | Page | Default | Purpose |
|---|---|---|---|---|---|
| `MEMORY_INJECTION_ENABLED` | `memory-injection-enabled` | BOOL | `FRIEND` | `false` | Gate `MessagePreprocessorHandler.injectMemories()` (the message-arrival injection into `EnsuredMessage.userMemories` / `metadata.memories`) AND the chat-time availability of the `add_memory` / `search_memories` tools (the chat LLM can only call them when this is on). `delete_memory` is always forced off at chat time (D3 gating) |
| `MEMORY_RETRIEVAL_MODE` | `memory-retrieval-mode` | STRING | `FRIEND` | `latest` | How ephemeral memories are chosen for injection: `latest` (newest-updated-first via `getLatestMemories`) or `relevant` (semantic via `LLMService.generateEmbedding` + `searchMemories`; falls back to `latest` when no embedding model is configured, the query embed fails, or search returns empty) |
| `MEMORY_EMBEDDINGS_ENABLED` | `memory-embeddings-enabled` | BOOL | `FRIEND` | `false` | Gate the regen cron's chat discovery for this chat (`_runMemoryEmbeddingRegen` discovers chats via `listChatsBySetting(MEMORY_EMBEDDINGS_ENABLED)`, filtered through `ChatSettingsValue.toBool()`). Must be on for any memory to receive a vec0 embedding |
| `MEMORY_REGENERATE_EMBEDDINGS` | `memory-regenerate-embeddings` | BOOL | `FRIEND` | `true` | Per-chat gate for re-embedding stale rows (only acts when `MEMORY_EMBEDDINGS_ENABLED` is on). Mirrors the chat-history `REGENERATE_EMBEDDINGS` semantics — defaults true so it is rarely persisted; must be manually reset via `/settings` (does not self-reset) |

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
