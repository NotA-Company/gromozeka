# Gromozeka — Library API Quick Reference

> **Audience:** LLM agents  
> **Purpose:** Complete API reference for all lib/ subsystems  
> **Self-contained:** Everything needed for library usage is here

---

## Table of Contents

1. [lib/ai — LLM Abstraction](#1-libai--llm-abstraction)
2. [lib/cache — Generic Cache Interface](#2-libcache--generic-cache-interface)
3. [lib/rate_limiter — Rate Limiting](#3-librate_limiter--rate-limiting)
4. [lib/markdown — Markdown Parser](#4-libmarkdown--markdown-parser)
5. [lib/max_bot — Max Messenger Client](#5-libmax_bot--max-messenger-client)
6. [lib/bayes_filter — Spam Filter](#6-libbayes_filter--spam-filter)
7. [lib/openweathermap — Weather Client](#7-libopenweathermap--weather-client)
8. [lib/geocode_maps — Geocoding](#8-libgeocode_maps--geocoding)
9. [lib/stats — Statistics Collection](#9-libstats--statistics-collection)
10. [lib/divination — Tarot & Runes Logic](#10-libdivination--tarot--runes-logic)
11. [lib/sandbox — Sandboxed Code Execution](#11-libsandbox--sandboxed-code-execution)
12. [lib/utils — Utilities & TTLDict](#12-libutils--utilities--ttldict)

---

## 1. `lib/ai` — LLM Abstraction

**Import paths:**
```python
from lib.ai import LLMManager, AbstractModel, ModelMessage, ModelResultStatus, ModelStructuredResult
from lib.ai.models import (
    ModelMessage,
    ModelImageMessage,
    ModelRunResult,
    ModelStructuredResult,
    ModelResultStatus,
    LLMToolFunction,
    LLMFunctionParameter,
    LLMParameterType,
    LLMAbstractTool,
    LLMToolCall,
)
```

**Key classes:**

| Class | File | Purpose |
|---|---|---|
| [`LLMManager`](../../lib/ai/manager.py:49) | `lib/ai/manager.py` | Registry for providers and models |
| [`AbstractModel`](../../lib/ai/abstract.py:47) | `lib/ai/abstract.py` | ABC for all LLM models |
| [`AbstractLLMProvider`](../../lib/ai/abstract.py) | `lib/ai/abstract.py` | ABC for LLM providers |
| [`ModelMessage`](../../lib/ai/models.py) | `lib/ai/models.py` | Standard text message for LLM |
| [`ModelImageMessage`](../../lib/ai/models.py) | `lib/ai/models.py` | Message with embedded image |
| [`ModelRunResult`](../../lib/ai/models.py) | `lib/ai/models.py` | LLM response container |
| [`ModelStructuredResult`](../../lib/ai/models.py) | `lib/ai/models.py` | Structured-output result; adds `data: Optional[Dict]` |
| [`ModelResultStatus`](../../lib/ai/models.py) | `lib/ai/models.py` | `FINAL`, `ERROR`, `TIMEOUT`, etc. |
| [`LLMToolFunction`](../../lib/ai/models.py:243) | `lib/ai/models.py` | Tool/function definition for LLM |
| [`LLMFunctionParameter`](../../lib/ai/models.py:175) | `lib/ai/models.py` | Tool parameter definition |
| [`LLMParameterType`](../../lib/ai/models.py:151) | `lib/ai/models.py` | `STRING`, `NUMBER`, `BOOLEAN`, `ARRAY`, `OBJECT` |

**Key methods on `AbstractModel`:**
```python
model.generateText(
    messages: Sequence[ModelMessage],
    tools=None,
    *,
    fallbackModels: Optional[List[AbstractModel]] = None,
) -> ModelRunResult
model.generateImage(
    messages: Sequence[ModelMessage],
    *,
    fallbackModels: Optional[List[AbstractModel]] = None,
) -> ModelRunResult
model.generateStructured(
    messages: Sequence[ModelMessage],
    schema: Dict[str, Any],
    *,
    schemaName: str = "response",
    strict: bool = True,
    fallbackModels: Optional[List[AbstractModel]] = None,
) -> ModelStructuredResult
model.getEstimateTokensCount(messages: list) -> int
model.contextSize  # int
model.temperature  # float
model.modelId      # str
```

**Fallback mechanism:**
All three public generation methods (`generateText`, `generateImage`, `generateStructured`)
support an optional `fallbackModels` parameter. When provided, the methods will
automatically try each model in the list until one succeeds (returns non-error status).

The `fallbackModels` parameter is an ordered list where:
- The first element is the primary model (the model you're calling the method on)
- Subsequent elements are fallback models to try if the primary fails

Example:
```python
primaryModel = llmManager.getModel("primary-model")
fallbackModel = llmManager.getModel("fallback-model")

result = await primaryModel.generateText(
    messages,
    tools=tools,
    fallbackModels=[fallbackModel],
)

if result.isFallback:
    print("Used fallback model!")
```

**Statistics recording:**
`AbstractModel` automatically records generation statistics to the stats storage backend:
- Records metrics: generation count, input/output/total tokens, error status, fallback status
- Tracked labels: modelName, modelId, provider, generationType, status
- Integration: `LLMManager` receives `statsStorage` in constructor and propagates to all `AbstractModel` instances

**Key methods on `LLMManager`:**
```python
manager.getModelInfo(modelName: str) -> Optional[Dict[str, Any]]
manager.getModel(modelName: str) -> Optional[AbstractModel]
manager.listModels() -> List[str]
```

**Creating a message:**
```python
# Text message
msg = ModelMessage(role="user", content="Hello")
msg = ModelMessage(role="system", content="You are helpful")
msg = ModelMessage(role="assistant", content="Response text")

# Image message
imgMsg = ModelImageMessage(
    role="user",
    content="Describe this image",
    image=bytearray(imageData),
)
```

**Structured (JSON-Schema) output:**

`generateStructured` sends a JSON Schema to the model and returns a
`ModelStructuredResult` — a thin subclass of `ModelRunResult` that adds:

- `data: Optional[Dict[str, Any]]` — the parsed JSON object on success;
  `None` on parse failure or any other error.
- On JSON parse failure: `status == ERROR`, `error` carries the
  `json.JSONDecodeError` / `ValueError`, and `resultText` still holds
  the raw model text for debugging.
- `resultText` always carries the raw string the model emitted.

**Capability flag:** set `support_structured_output = true` in a model's
`extraConfig` block; surfaces via `model.getInfo()["support_structured_output"]`.
When the flag is `False`, the public `generateStructured` raises
`NotImplementedError` immediately (see [`lib/ai/abstract.py`](../../lib/ai/abstract.py)).

**Tool mutual exclusion:** `generateStructured` has no `tools=` parameter.
Combining structured output with tool calls is not supported in v1.

**No auto-injected JSON hint:** callers should include a system message
hinting at JSON output; the wrapper does not inject one.

**Provider support:** implemented for OpenAI-compatible providers
(`custom-openai`, `openrouter`, `yc-openai`) and the `yc-sdk` provider.
The `yc-sdk` provider implements `_generateStructured` via `response_format`
with JSON Schema (see [`lib/ai/providers/yc_sdk_provider.py`](../../lib/ai/providers/yc_sdk_provider.py)).

**YC SDK tool calling:** the `yc-sdk` provider also supports tool/function
calling via `_generateText(tools=[...])`. Tools are converted from
`LLMAbstractTool` to SDK `FunctionTool` via `_convertTools()`, and
`result.tool_calls` are extracted into `LLMToolCall` objects. When tool
calls are present, `ModelResultStatus.TOOL_CALLS` is returned.

**YC SDK per-request model creation:** each `_generate*` call creates a
fresh SDK model via `_getModel(**configOverrides)` instead of reusing a
shared model instance. This avoids the `.configure()` mutation problem
where concurrent callers with different configurations would clobber each
other.

**YC SDK auth:** supports `auth_type` config values `"auto"` (default,
env-var detection), `"api_key"`, `"iam_token"`, and `"yc_cli"`. See
[`configuration.md`](configuration.md) for details.

**YC SDK tokenization:** `getExactTokensCount()` uses the SDK's
`model.tokenize()` for precise counts, falling back to the heuristic
`getEstimateTokensCount()` if tokenize is unavailable.

**YC SDK error handling:** all generation methods catch `AIStudioError`
and route through `_handleSDKError()`, which maps `AioRpcError` details
(e.g. content filter violations → `CONTENT_FILTER`) and logs `RunError`
specifically.

**Abstract/split pattern:** Similar to `generateText` / `_generateText`,
the image generation methods follow the same pattern:
- `_generateImage` — the `@abstractmethod` that providers implement
- `generateImage` — the public wrapper that handles fallback and JSON logging
This split allows the public API to provide consistent behavior (fallback,
JSON logging) while keeping provider implementations simple.

**Image generation transports:** OpenAI-compatible providers support two
image-generation transports:

1. **Chat-completions path** (default): Uses `chat.completions.create()` with
   `modalities = ["image", "text"]`. The image is returned in
   `response.choices[0].message.images`. This is the path used when
   `image_generation_api` is not set or set to any value other than
   `"openai-images"`.

2. **OpenAI Images API path**: Uses `client.images.generate()` directly.
   Enabled by setting `image_generation_api = "openai-images"` in model config.
   This path calls `_generateImageViaImagesApi()` which extracts a plain-text
   prompt from messages and sends it to the Images API.

**Hook methods for image generation:**

| Method | Class | Purpose |
|--------|-------|---------|
| `_getImageModelId()` | `BasicOpenAIModel` | Returns model ID for Images API. Override to use a different ID (e.g., YC uses `art://...`). |
| `_getImageRequestOptions()` | `BasicOpenAIModel` | Returns whitelisted options from `image_options` config. Prevents arbitrary config injection. |
| `_getClientParams()` | `BasicOpenAIProvider` | Returns extra params for OpenAI client init (applied to all requests). YC overrides it to return `{"project": folderId}`, which is required by YC's Images API and also present on text calls via the `OpenAI-Project` header. |

**Yandex Cloud OpenAI image models:** YC uses a distinct URI scheme for image
models: `art://{folderId}/{modelId}/{modelVersion}` (vs. `gpt://...` for text).
The `_getImageModelId()` override in `YcOpenaiModel` constructs this URI.
Additionally, `_getClientParams()` in `YcOpenaiProvider` adds the `project`
parameter required by YC's Images API endpoint.

**Schema requirements (strict mode).** Most providers forward your
schema to OpenAI's `response_format = {"type": "json_schema",
"json_schema": {"strict": true, ...}}` mode. To be portable
across all backends:

* Every property under `properties` MUST also appear in
  `required`. Optional fields are not allowed in strict mode.
* Every object level MUST set `"additionalProperties": false`.
* Root-level `oneOf` / `anyOf` is rejected — wrap unions inside a
  named property.

YC OpenAI's native models (yandexgpt, aliceai-llm, yc/deepseek-v32)
enforce these rules strictly; OpenRouter-hosted gpt-oss/qwen/gemma
tolerate violations silently. Always write to the strict subset.

Reference: https://platform.openai.com/docs/guides/structured-outputs

**Example - Divination layout discovery schema:**

```python
# From DivinationHandler - layout discovery uses structured output
layoutSchema = {
    "type": "object",
    "properties": {
        "systemId": {"type": "string"},
        "layoutId": {"type": "string"},
        "nameEn": {"type": "string"},
        "nameRu": {"type": "string"},
        "description": {"type": "string"},
        "nSymbols": {"type": "integer"},
        "positions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["systemId", "layoutId", "nameEn", "nameRu", "nSymbols", "positions"],
    "additionalProperties": False,
}
```

**Import:**
```python
from lib.ai import ModelStructuredResult
```

**Adding a new LLM provider:**

1. Create `lib/ai/providers/my_provider.py`
2. Class: `MyProvider(AbstractLLMProvider)`
3. Must implement: `_createModel(modelConfig) -> AbstractModel`
4. Register in `lib/ai/manager.py:118` — add to `providerTypes` dict: `{"my-provider": MyProvider}`
5. Tests in `tests/lib/ai/providers/test_my_provider.py`

**FastEmbed provider (`fastembed`):**

[`FastembedProvider`](../../lib/ai/providers/fastembed_provider.py) hosts any number of `fastembed`-backed embedding models under the standard `addModel` pattern. Models are configured with `support_embeddings=true` (and `support_text=false` to keep them out of the chat-completion model pool). Output dimensionality can be set explicitly via `embedding_dimensions` in `extraConfig` (preferred — keeps startup fast) or detected via a one-shot probe on first use.

| Aspect | Detail |
|---|---|
| Provider name | `fastembed` |
| Backend | `fastembed` (ONNX-based, no PyTorch). Optional dependency — `ImportError` raised at provider init when not installed |
| Model class | `FastembedModel` — extends `AbstractModel`; overrides `_generateEmbeddings` only |
| Extra-config keys | `support_embeddings` (required `true`), `support_text` (set `false`), `embedding_dimensions` (optional), plus any fastembed kwargs (`cache_dir`, `threads`, `max_length`, ...) |
| Concurrency | `asyncio.to_thread` wraps the sync `TextEmbedding.embed` so the event loop stays unblocked; per-model `threading.Lock` serialises lazy model construction |
| Text / image gen | `NotImplementedError` — local embeddings are embedding-only |

**Usage example:**

```toml
[models.providers.fastembed]
type = "fastembed"

[models.models."local-minilm"]
provider = "fastembed"
model_id = "sentence-transformers/all-MiniLM-L6-v2"
model_version = "latest"
temperature = 0.0
context = 0
support_text = false
support_embeddings = true
embedding_dimensions = 384
tier = "free"
enabled = true
```

```python
model = llmManager.getModel("local-minilm")
vector: list[float] = await model.generateEmbeddings("hello world")
```

The vector is a plain `list[float]` — same shape every embedding backend in the codebase returns, so the chat-search pipeline (`saveMessageEmbedding` / `searchChatMessages`) works unchanged across OpenAI, Yandex, and local providers.

**Default model:** `local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-dim, ~0.22 GB, ~50 languages, 512 token context) is the per-chat default for the `EMBEDDING_MODEL` chat setting via `embedding-model = "local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"` under `[bot.defaults]` in [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml). Both this model and the larger alternative `local/jinaai/jina-embeddings-v3` (1024-dim, ~2.24 GB, ~100 languages, 1024 token context) are registered in [`configs/00-defaults/fastembed-models.toml`](../../configs/00-defaults/fastembed-models.toml). The model resolution chain in `ChatSearchHandler._dtCronJob` (backfill) and the `MessagePreprocessorHandler` embedding dispatch is single-tier: the per-chat `EMBEDDING_MODEL` setting provides the value, and an empty / unresolvable model is a silent no-op for that chat on that tick. The server-wide `[search-history.embeddings].model` and `[search-history.embeddings].on-save` config keys were removed — the per-chat default already provides the model name, and the on-save dispatch is now unconditional whenever `[search-history].enabled` and `EMBEDDINGS_ENABLED` are both on. See [`configuration.md`](configuration.md) for the full `[search-history]` reference.

**Proxy support:** `LLMManager.__init__()` accepts an optional `proxyConfig` keyword argument containing the global `[proxy]` config dict. This is passed through to `BasicOpenAIProvider.__init__()`, which creates a `ProxyConfig` via `ProxyConfig.fromServiceConfig()` and calls `ProxyConfig.toKwargs()` in `_initClient()` to configure a custom `httpx.AsyncClient` for the OpenAI SDK. Image download (`_generateImageViaImagesApi`) and OpenRouter `listRemoteModels()` also resolve proxy.

---

## 2. `lib/cache` — Generic Cache Interface

**Import:**
```python
from lib.cache import CacheInterface, DictCache
from lib.cache import StringKeyGenerator, HashKeyGenerator, JsonKeyGenerator
from lib.cache import ValueConverter, JsonValueConverter, StringValueConverter
```

**Key classes:**

| Class | File | Purpose |
|---|---|---|
| [`CacheInterface[K,V]`](../../lib/cache/interface.py:15) | `lib/cache/interface.py` | Generic ABC for any cache |
| `DictCache[K,V]` | `lib/cache/dict_cache.py` | In-memory dict implementation |
| `StringKeyGenerator` | `lib/cache/key_generator.py` | Simple string key gen |
| `HashKeyGenerator` | `lib/cache/key_generator.py` | SHA512 hash key gen |
| `JsonKeyGenerator` | `lib/cache/key_generator.py` | JSON serialization + hash |
| `ValueConverter` | `lib/cache/types.py` | Protocol for value conversion |
| `StringValueConverter` | `lib/cache/value_converter.py` | Pass-through string converter |
| `JsonValueConverter` | `lib/cache/value_converter.py` | JSON string/value converter |

**Interface methods:**
```python
await cache.get(key: K, ttl: Optional[int] = None) -> Optional[V]
await cache.set(key: K, value: V) -> bool
await cache.clear() -> None
cache.getStats() -> Dict[str, Any]
```

**DictCache constructor:**
```python
cache = DictCache[K, V](
    keyGenerator: KeyGenerator[K],  # Required: strategy for converting keys
    defaultTtl: int = 3600,         # Optional: default TTL in seconds
    maxSize: Optional[int] = 1000,  # Optional: max entries before eviction
    threadSafe: bool = True,        # Optional: enable thread safety with RLock
    valueConverter: ValueConverter = None  # Optional: value conversion strategy
)
```

**NOTE:** For bot cache operations (chat settings, user data, admin cache), use [`CacheService`](services.md) instead of `lib/cache` directly

---

## 3. `lib/rate_limiter` — Rate Limiting

**Import:**
```python
from lib.rate_limiter import RateLimiterManager, RateLimiterInterface, SlidingWindowRateLimiter
```

**Interface methods** ([`RateLimiterInterface`](../../lib/rate_limiter/interface.py:19)):
```python
await limiter.initialize() -> None
await limiter.destroy() -> None
await limiter.applyLimit(queue: str = "default") -> None
limiter.getStats(queue: str = "default") -> Dict[str, Any]
limiter.listQueues() -> List[str]
```

**For bot usage, use** [`RateLimiterManager`](services.md#5-ratelimitermanager) **from services**

---

## 4. `lib/markdown` — Markdown Parser

**Import:**
```python
from lib.markdown.parser import markdownToMarkdownV2
```

**Key function:**
```python
# Convert standard markdown to Telegram MarkdownV2 format
result: str = markdownToMarkdownV2(text: str) -> str
```

**Tests:** `tests/lib/markdown/` — run with `make test`

---

## 5. `lib/max_bot` — Max Messenger Client

**Import:**
```python
import lib.max_bot as libMax
import lib.max_bot.models as maxModels
from lib.max_bot import MaxBotClient, MAX_MESSAGE_LENGTH
```

**Key class:** [`MaxBotClient`](../../lib/max_bot/client.py) — async HTTP client for Max Bot API

**Key constants:**
- `MAX_MESSAGE_LENGTH` — max message length for Max platform

**Key model submodules:**
- [`lib/max_bot/models/message.py`](../../lib/max_bot/models/message.py) — Message models
- [`lib/max_bot/models/chat.py`](../../lib/max_bot/models/chat.py) — Chat models
- [`lib/max_bot/models/attachment.py`](../../lib/max_bot/models/attachment.py) — Attachment models
- [`lib/max_bot/models/enums.py`](../../lib/max_bot/models/enums.py) — Enum types
- [`lib/max_bot/models/keyboard.py`](../../lib/max_bot/models/keyboard.py) — Keyboard/button models
- [`lib/max_bot/models/update.py`](../../lib/max_bot/models/update.py) — Update/event models

**IMPORTANT gotcha — Max platform sticker stubs:**
Animated stickers have stub URLs, not real images. Always check `url.startswith(...)` before processing

**Proxy support:** `MaxBotClient.__init__()` accepts an optional `proxyKwargs` keyword argument (dict to spread into `httpx.AsyncClient`). When proxy is enabled for the bot, `MaxBotApplication._runPolling()` creates a `ProxyConfig` via `ProxyConfig.fromServiceConfig()` and passes the resulting kwargs from `ProxyConfig.toKwargs()`.

---

## 6. `lib/bayes_filter` — Spam Filter

**Import:**
```python
from lib.bayes_filter.bayes_filter import BayesFilter, BayesConfig
from lib.bayes_filter.models import SpamScore
```

**Key class:** `BayesFilter` — Naive Bayes classifier

**Config fields:**
```python
BayesConfig(
    alpha=1.0,                # Laplace smoothing
    minTokenCount=2,          # Min token occurrences
    perChatStats=True,        # Per-chat or global stats
    defaultThreshold=50.0,    # Spam threshold 0-100
    minConfidence=0.1,        # Min classification confidence
    maxTokensPerMessage=2000, # Performance cap
)
```

**Multi-source database support:** `BayesFilter` supports `dataSource` parameter for multi-source routing

---

## 7. `lib/openweathermap` — Weather Client

**Import:**
```python
from lib.openweathermap.client import OpenWeatherMapClient
```

**Key methods:**
```python
client = OpenWeatherMapClient(apiKey="...", cacheTtl=3600)
weather = await client.getCurrentWeather(lat=55.75, lon=37.62)
geocoding = await client.geocode(cityName="Moscow")
```

**Tests:** Uses golden data framework in `tests/lib/openweathermap/test_weather_client.py`

**Proxy support:** `OpenWeatherMapClient.__init__()` accepts an optional `proxyKwargs` keyword argument (dict to spread into `httpx.AsyncClient`). The `WeatherHandler` creates a `ProxyConfig` via `ProxyConfig.fromServiceConfig(openWeatherMapConfig)`, calls `ProxyConfig.getCombined()` to merge with the global config, then `ProxyConfig.toKwargs()` and passes the result to the client constructor.

---

## 8. `lib/geocode_maps` — Geocoding

**Import:**
```python
from lib.geocode_maps.client import GeocodeMapsClient
```

**Key methods:**
```python
client = GeocodeMapsClient(apiKey="...")
result = await client.geocode(address="Moscow, Russia")
result = await client.reverseGeocode(lat=55.75, lon=37.62)
```

**Config:** Configured via `[geocode-maps]` TOML section, accessed via `configManager.getGeocodeMapsConfig()`

**Proxy support:** `GeocodeMapsClient.__init__()` accepts an optional `proxyKwargs` keyword argument (dict to spread into `httpx.AsyncClient`). The `WeatherHandler` creates a `ProxyConfig` via `ProxyConfig.fromServiceConfig(geocodeMapsConfig)`, calls `ProxyConfig.getCombined()` to merge with the global config, then `ProxyConfig.toKwargs()` and passes the result to the client constructor.

---

## 9. `lib/stats` — Statistics Collection

Generic, storage-agnostic interface for recording time-series statistics events and aggregating them into periodic buckets.

**Import:**
```python
from lib.stats import StatsStorage, NullStatsStorage, GLOBAL_CONSUMER_ID
```

**Key constants:**
- `GLOBAL_CONSUMER_ID` — Sentinel value `"__global__"` for global (all-consumer) aggregation

**Key classes:**

| Class | File | Purpose |
|---|---|---|
| [`StatsStorage`](../../lib/stats/stats_storage.py:11) | `lib/stats/stats_storage.py` | ABC for statistics storage backends |
| [`NullStatsStorage`](../../lib/stats/stats_storage.py:81) | `lib/stats/stats_storage.py` | No-op implementation (discards all events) |

**Interface methods on `StatsStorage`:**
```python
await statsStorage.record(
    stats: dict[str, float | int],
    *,
    consumerId: Optional[str] = None,
    labels: Optional[dict[str, str]] = None,
    eventTime: Optional[datetime] = None,
) -> None

await statsStorage.aggregate(
    *,
    limit: int = 1000,
    orphanTimeoutSeconds: int = 3600,
) -> int
```

**Usage example:**
```python
from lib.stats import NullStatsStorage

storage = NullStatsStorage()
await storage.record(
    {"tokens": 150, "request_count": 1},
    consumerId="chat_123",
    labels={"model": "gpt-4o", "provider": "openrouter"},
)
```

**DB-backed implementation:** [`DatabaseStatsStorage`](../../internal/database/stats_storage.py:39) in `internal/database/stats_storage.py` — backed by `stat_events` (append-only log) and `stat_aggregates` (period buckets). Created in `main.py` when `stats.enabled = true`.

**Integration points:**
- `LLMManager` receives `statsStorage` in constructor and propagates to all `AbstractModel` instances
- `AbstractModel` records generation stats (tokens, errors, status) via `_recordAttemptStats()`
- `LLMService` passes `consumerId=str(chatId)` to LLM generation methods

**Best-effort design:** `record()` implementations must never raise — log and return silently on error.

---

## 10. `lib/divination` — Tarot & Runes Logic

Pure-logic library for tarot and rune divination. Depends ONLY on `lib/ai` (no bot, no DB)

**Layout:**

| Path | Purpose |
|---|---|
| [`lib/divination/base.py`](../../lib/divination/base.py) | `BaseDivinationSystem` ABC plus `Symbol`, `DrawnSymbol`, `Reading` dataclasses |
| [`lib/divination/layouts.py`](../../lib/divination/layouts.py) | `Layout` dataclass (with `systemId`, `description` fields), `TAROT_LAYOUTS`, `RUNES_LAYOUTS`, `resolveLayout()` |
| [`lib/divination/drawing.py`](../../lib/divination/drawing.py) | `drawSymbols()` — uses `random.SystemRandom()` by default; tests inject seeded `random.Random` |
| [`lib/divination/localization.py`](../../lib/divination/localization.py) | `SYMBOL_NAMES`, `POSITION_NAMES`, `LAYOUT_NAMES` (Russian translations) + `tr()` helper |
| [`lib/divination/tarot.py`](../../lib/divination/tarot.py) | `TarotSystem(BaseDivinationSystem)` |
| [`lib/divination/runes.py`](../../lib/divination/runes.py) | `RunesSystem(BaseDivinationSystem)` |
| [`lib/divination/decks/tarot_rws.py`](../../lib/divination/decks/tarot_rws.py) | Full 78-card Rider-Waite-Smith deck |
| [`lib/divination/decks/runes_elder_futhark.py`](../../lib/divination/decks/runes_elder_futhark.py) | 24 Elder Futhark runes |

**Predefined layouts:**
- Tarot: `one_card`, `three_card`, `celtic_cross`, `relationship`, `yes_no`
- Runes: `one_rune`, `three_runes`, `five_runes`, `nine_runes`

**Layout name parsing** in `resolveLayout()` is case-, dash-, underscore-, and space-insensitive.

**Boundary rule:** `lib/divination/` is consumed by `internal/bot/common/handlers/divination.py`; the library itself must never import from `internal/`. A boundary-import test enforces this

**Usage from a handler:**
```python
from lib.divination.tarot import TarotSystem
from lib.divination.layouts import resolveLayout
from lib.divination.drawing import drawSymbols

system = TarotSystem()
layout = resolveLayout(system, "three_card")
reading = drawSymbols(system, layout, question="What about my career?")
```

---

## 11. `lib/sandbox/` — Sandboxed Code Execution

Safely execute untrusted Python code in Docker containers. Provides a
singleton `SandboxManager` entry point that composes a backend (Docker),
runtimes (Python), metadata store (filesystem), and lock registry.

- **Coding patterns & constraints:** [`sandbox.md`](sandbox.md)
- **Design:** [`docs/plans/python-sandboxing-v1.md`](../plans/python-sandboxing-v1.md)
- **Integration:** [`docs/plans/python-sandboxing-v1-integration.md`](../plans/python-sandboxing-v1-integration.md)

Key modules:

| Module | Purpose |
|--------|---------|
| [`manager.py`](../../lib/sandbox/manager.py) | `SandboxManager` singleton — sessions, runs, files, libraries, GC, health, recovery |
| [`types.py`](../../lib/sandbox/types.py) | Public dataclasses (`RunResult`, `SessionInfo`, `ResourceLimits`, etc.) |
| [`enums.py`](../../lib/sandbox/enums.py) | `RuntimeName`, `BackendName` |
| [`config.py`](../../lib/sandbox/config.py) | Configuration dataclasses (`SandboxConfig`, `StorageConfig`, etc.) |
| [`errors.py`](../../lib/sandbox/errors.py) | Exception hierarchy (`SandboxError` → `ConfigError`, `BackendError`, `SessionError`, `SandboxRuntimeError`, `RunError`, `LibraryError`, `FileError`, `SandboxBusy`, `SessionBusy`, `SessionDropped`) |
| [`locks.py`](../../lib/sandbox/locks.py) | Per-session mutex registry with bounded waiters and force-cancel, global run semaphore, pool flock |
| [`storage.py`](../../lib/sandbox/storage.py) | Workspace path resolution, atomic JSON writes, directory layout |
| [`gc.py`](../../lib/sandbox/gc.py) | Garbage collector for expired sessions, orphan workspaces, run records |
| [`backends/docker.py`](../../lib/sandbox/backends/docker.py) | Docker backend via `aiodocker` |
| [`runtimes/python/runtime.py`](../../lib/sandbox/runtimes/python/runtime.py) | Python runtime with `timeout` wrapper and artifact detection |
| [`metadata/filesystem.py`](../../lib/sandbox/metadata/filesystem.py) | Filesystem-backed metadata store (JSON) |

**Import:**
```python
from lib.sandbox import SandboxManager
from lib.sandbox.config import SandboxConfig, StorageConfig
from lib.sandbox.types import RunResult, SessionInfo, ResourceLimits
from lib.sandbox.enums import RuntimeName, BackendName
```

**Quick start:**
```python
from lib.sandbox import SandboxManager, SandboxConfig, StorageConfig

config = SandboxConfig(storage=StorageConfig(rootDir="/var/lib/gromozeka/sandbox"))
SandboxManager.injectConfig(config)
manager = SandboxManager.getInstance()

session = await manager.createSession("my-session")
result = await manager.runCode(session.sessionId, "print(2 + 2)")
print(result.exitCode)  # 0

await manager.shutdown()
```

See [`sandbox.md`](sandbox.md) for the complete coding patterns, configuration rules, and anti-patterns. Note that package installation is administered via admin-only operations; see the security considerations in [`sandbox.md`](sandbox.md#security-considerations) for details on how arbitrary package spec injection is prevented.

---

## 12. `lib/utils` — Utilities & TTLDict

General-purpose utilities and a TTL-enabled dictionary.

**Import:**
```python
from lib.utils import TTLDict, getAgeInSecs, parseDelay, jsonDumps, packDict, unpackDict
```

**Key classes:**

| Class | File | Purpose |
|---|---|---|
| [`TTLDict`](../../lib/utils/ttl_dict.py) | `lib/utils/ttl_dict.py` | Dict subclass with per-entry TTL and automatic expiration |

**TTLDict usage:**
```python
from lib.utils import TTLDict

d = TTLDict[str, int]()
d.setDefaultTTL(60)       # Default TTL: 60 seconds
d.set("key1", 1, ttl=120) # Custom TTL: 120 seconds
d.set("key2", 2)          # Uses default TTL
d.set("key3", 3, ttl=None) # Never expires
d.gc(force=True)          # Remove expired entries
```

**TTLDict key behaviors:**

- `set(key, value, ttl=...)` — `ttl` defaults to `defaultTTL`; passing `ttl=None` explicitly clears any previous expiration, making the entry never expire. This is important: rewriting an entry that previously had a TTL with `ttl=None` removes the expiration, preventing stale entries from being collected.
- `__setitem__` delegates to `set()` with default TTL.
- `gc(force=False)` only runs if `gcTimeout` seconds have passed since the last GC; `gc(force=True)` always runs.
- Thread-safe via `RLock`.

**Other utilities:**

| Function | Purpose |
|---|---|
| `getAgeInSecs(dt)` | Seconds elapsed since a `datetime` |
| `parseDelay(s)` | Parse human delay strings (`"1d2h30m"`) into seconds |
| `jsonDumps(obj, **kw)` | JSON serialization with datetime support |
| `packDict(d)` / `unpackDict(d)` | Dict serialization helpers |
| `load_dotenv(path)` | Load `.env` files into `os.environ` |

---

## 13. `lib/proxy` — Proxy Resolution

Class-based proxy resolution package. Lives in `lib/` with no imports from `internal/`.

**Import:**
```python
from lib.proxy import ProxyConfig, ProxyHelper, ProxyType, ProxyKwargs
```

**Types:**

| Type | Purpose |
|---|---|
| `ProxyType` | `StrEnum("http", "socks5", "none")` — supported proxy protocol types |
| `HealthCheckType` | `StrEnum("none", "url", "command")` — health check mechanism for proxy lifecycle |
| `ProxyKwargs(TypedDict)` | Keyword arguments for `httpx.AsyncClient` — either `proxy: str` or `transport: AsyncProxyTransport` |
| `ProxyLifecycleConfigDict(TypedDict)` | Optional lifecycle configuration with 7 fields: `startCommand`, `stopCommand`, `restartCommand`, `healthCheckType`, `healthCheckUrl`, `healthCheckCommand`, `healthCheckInterval` |

**Classes:**

| Class | Purpose |
|---|---|
| `ProxyConfig` | Immutable proxy configuration (`__slots__`). Created via `fromServiceConfig()` or `fromDict()`. Methods: `getCombined()` (merge with global), `getProxyURL(maskPassword=False)` (build URL), `toKwargs()` (httpx kwargs). Has optional `lifecycle` field of type `ProxyLifecycleConfigDict`. |
| `ProxyHelper` | Singleton storing the global proxy config. `setGlobalProxyConfig()` called once from `main.py`; `getGlobalProxyConfig()` used internally by `ProxyConfig.getCombined()`. |

**Helper functions:**

| Function | Purpose |
|---|---|
| `_kebabToCamelCase(s)` | Converts TOML kebab-case keys to Python camelCase field names (used by `ProxyConfig.fromDict()` for lifecycle config parsing) |

**Usage pattern in service constructors:**
```python
from lib.proxy import ProxyConfig

proxyConfig = ProxyConfig.fromServiceConfig(serviceConfig)
proxyKwargs = proxyConfig.toKwargs()
proxyUrl = proxyConfig.getProxyURL(maskPassword=True)
if proxyUrl:
    logger.info(f"Proxy enabled: {proxyUrl}")

# Then in HTTP calls:
async with httpx.AsyncClient(**proxyKwargs, timeout=30) as client:
    ...
```

**Per-service override semantics (`fromServiceConfig`):** When a service sets `use-proxy = true` with a `[service.proxy]` sub-section, `fromServiceConfig` delegates to `fromDict` which reads `enabled` from the sub-dict via `data.get("enabled") is True`. If the sub-section omits `enabled: true`, the resulting ProxyConfig has `enabled=False`, and `getCombined()` treats it as "inherit from global" — the per-service override fields (`type`, `address`, etc.) are silently ignored. Always include `enabled: true` in the proxy sub-section when you intend to override the global config for a specific service. This is intentional behavior.

**Password masking in `__repr__` / `__str__`:** Non-empty passwords render as `'***'` in `repr()` and `str()` output. This prevents accidental credential leaks through logging/debugging while keeping other fields visible. When password is `None` or an empty string, it renders verbatim. This is separate from `getProxyURL(maskPassword=True)` which replaces the password with `"REDACTED"` in the built URL.

**SQLink proxy — lazy resolution:** `SQLinkProvider.__init__` accepts `proxy` and `use-proxy` inside `parameters` (see `configuration.md`) and stores a `ProxyConfig` object. The proxy URL is not resolved at construction time — resolution happens in `connect()` via `self._proxy.getProxyURL()`. This ensures the global proxy config (set by `main.py`) is available at resolution time.

---

## See Also

## 14. `sqlite-vec` — Native Vector Search Extension

**Pinned dependency:** `sqlite-vec==0.1.9` (in `requirements.direct.txt` under `# Runtime`). Optional at runtime — the `SQLite3Provider` guards the import with a module-level `try/except ImportError` and an `_SQLITE_VEC_AVAILABLE` flag; if absent, `isVectorSearchSupported()` returns `False` and semantic search falls back to the numpy path.

**Purpose:** provides the `vec0` virtual table module for native cosine-similarity KNN search inside the SQLite process, eliminating the transfer of all embedding BLOBs to Python on every search. Loaded by `SQLite3Provider.connect()` via aiosqlite's `enable_load_extension` / `load_extension` / `enable_load_extension(False)` (wrapped in `try/finally`).

**Used by:** `internal/database/providers/sqlite3.py` (`SQLite3Provider`), `internal/database/repositories/chat_embeddings.py` (dual-write to `vec_message_embeddings_{N}`), `internal/database/repositories/chat_search.py` (`_nativeVectorSearch`). See [`database.md`](database.md) §7 "Vector search types" for the provider interface and the vec0 schema, and [`docs/design/vector-search-native.md`](../design/vector-search-native.md) for the design.

**No config key** — auto-detected at connect time. To disable native search: `pip uninstall sqlite-vec`.

---

## See Also

- [`index.md`](index.md) — Project overview, lib/ directory map
- [`services.md`](services.md) — Higher-level service wrappers (CacheService, LLMService, etc.)
- [`configuration.md`](configuration.md) — Configuring lib integrations via TOML
- [`testing.md`](testing.md) — Golden data framework for API testing
- [`tasks.md`](tasks.md) — Step-by-step: "add new API integration" decision tree
