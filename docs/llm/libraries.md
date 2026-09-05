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
13. [lib/proxy — Proxy Resolution](#13-libproxy--proxy-resolution)
14. [sqlite-vec — Native Vector Search Extension](#14-sqlite-vec--native-vector-search-extension)
15. [aiohttp — HTTP Server for the Webhook Receiver](#15-aiohttp--http-server-for-the-webhook-receiver)
16. [lib/stt — Provider-neutral Speech-to-Text](#16-libstt--provider-neutral-speech-to-text)
17. [lib/stats/stats_pages/ — Statistics Page Generator](#17-libstatsstats_pages--statistics-page-generator)
18. [lib/db — SQL Provider Abstraction + DatabaseManager](#18-libdb--sql-provider-abstraction--databasemanager)
19. [lib/max_webhook_receiver — Standalone Max Webhook Receiver](#19-libmax_webhook_receiver--standalone-max-webhook-receiver)

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

`LLMToolCall(id: str, name: str, parameters: Dict[str, Any], errorMessage: Optional[str] = None)` is the tool-call payload the model emits. The `errorMessage` field is **internal plumbing** — it is NOT serialised by `__str__` / `toDict()` and is NOT sent back to the provider. When set, the call was synthesised from a malformed but recognisable tool-call attempt and the handler must NOT be executed; instead `errorMessage` is fed back to the model as a retry error. Left as `None` for ordinary tool calls.

**Key classes:**

| Class | File | Purpose |
|---|---|---|
| [`LLMManager`](../../lib/ai/manager.py:49) | `lib/ai/manager.py` | Registry for providers and models |
| [`AbstractModel`](../../lib/ai/abstract.py:47) | `lib/ai/abstract.py` | ABC for all LLM models |
| [`AbstractLLMProvider`](../../lib/ai/abstract.py) | `lib/ai/abstract.py` | ABC for LLM providers |
| [`OpencodeGoProvider`](../../lib/ai/providers/opencode_go_provider.py) / [`OpencodeGoModel`](../../lib/ai/providers/opencode_go_provider.py) | `lib/ai/providers/opencode_go_provider.py` | OpenCode Go endpoint — like `custom-openai`, but attaches the mandatory `x-opencode-session` header to every request (see "Request session identification" below) |
| [`ModelMessage`](../../lib/ai/models.py:550) | `lib/ai/models.py` | Standard text message for LLM. `__slots__ = (role, content, contentKey, toolCalls, toolCallId, weight, source)` — `source` is an optional passthrough for the originating handler message (used by the llm-messages-handler to round-trip provenance, see [`memories/llm-messages-handler.md`](memories/llm-messages-handler.md)) |
| [`ModelImageMessage`](../../lib/ai/models.py) | `lib/ai/models.py` | Message with embedded image |
| [`ModelRunResult`](../../lib/ai/models.py:965) | `lib/ai/models.py` | LLM response container. `__slots__` add `isFallback`, `isToolsUsed`, `roundLimitHit` (set by `LLMService.generateTextViaLLM` when the `maxRounds` tool-loop budget is exhausted, regardless of resulting status — see [`memories/user-memory-refinement.md`](memories/user-memory-refinement.md)), and the optional provider-reported usage fields `cachedInputTokens` (subset of `inputTokens`, from `prompt_tokens_details.cached_tokens`), `reasoningTokens` (subset of `outputTokens`, from `completion_tokens_details.reasoning_tokens` / YC SDK `usage.reasoning_tokens`), and `cost` (USD, e.g. OpenRouter's extra `usage.cost`) — all `None` when the provider doesn't report them |
| [`ModelStructuredResult`](../../lib/ai/models.py) | `lib/ai/models.py` | Structured-output result; adds `data: Optional[Dict]` |
| [`ModelResultStatus`](../../lib/ai/models.py) | `lib/ai/models.py` | `FINAL`, `ERROR`, `TIMEOUT`, etc. |
| [`LLMToolFunction`](../../lib/ai/models.py:345) | `lib/ai/models.py` | Tool/function definition for LLM |
| [`LLMFunctionParameter`](../../lib/ai/models.py:277) | `lib/ai/models.py` | Tool parameter definition |
| [`LLMParameterType`](../../lib/ai/models.py:253) | `lib/ai/models.py` | `STRING`, `NUMBER`, `BOOLEAN`, `ARRAY`, `OBJECT` |

**Key methods on `AbstractModel`:**
```python
model.generateText(
    messages: Sequence[ModelMessage],
    tools: Optional[Sequence[LLMAbstractTool]] = None,
    *,
    fallbackModels: Optional[Sequence[AbstractModel]] = None,
    consumerId: Optional[str] = None,
    sessionId: Optional[str] = None,
) -> ModelRunResult
model.generateImage(
    messages: Sequence[ModelMessage],
    *,
    fallbackModels: Optional[Sequence[AbstractModel]] = None,
    consumerId: Optional[str] = None,
    sessionId: Optional[str] = None,
) -> ModelRunResult
model.generateStructured(
    messages: Sequence[ModelMessage],
    schema: Dict[str, Any],
    *,
    schemaName: str = "response",
    strict: bool = True,
    fallbackModels: Optional[Sequence[AbstractModel]] = None,
    consumerId: Optional[str] = None,
    sessionId: Optional[str] = None,
) -> ModelStructuredResult
model.generateEmbeddings(
    text: str,
    *,
    attempts: int = 3,
    consumerId: Optional[str] = None,
    sessionId: Optional[str] = None,
) -> list[float]
model.getEstimateTokensCount(data: Any) -> int
model.contextSize  # int
model.getInfo()["customParams"]  # Dict[str, Any] — per-model request params (temperature, top_p, ...)
model.modelId      # str
```

`consumerId` (typically `str(chatId)`) is forwarded by `LLMService` to every generation method and used as the stats-storage partition key — see [`services.md`](services.md). Embeddings have **no** `fallbackModels` parameter: vectors from different models live in incompatible spaces, so swapping mid-stream would silently corrupt downstream cosine scores.

**Request session identification (`sessionId`):** every public generation
method accepts an optional `sessionId` — a stable conversation identifier
the bot fills as `gromozeka-<chatId>-<rootMessageId>` (built by
`BaseBotHandler.getLLMRequestSessionId`, `internal/bot/common/handlers/base.py`).
For the duration of the call it is exposed to provider code via a
task-local `ContextVar` (`getCurrentRequestSessionId()` in
[`lib/ai/abstract.py`](../../lib/ai/abstract.py)) — task-local means
concurrent requests never observe each other's session. `LLMService`
threads `sessionId` through `generateTextViaLLM` / `generateText` /
`generateStructured` / `generateImage` / `generateEmbedding`, including the
condensing path inside the tool loop. Consumer: the `opencode-go` provider
uses it to fill the mandatory `x-opencode-session` header (OpenCode Go
requires it from 2026-09-06 for prompt-cache optimization); when no
request session is set, the provider falls back to its `session_fallback`
config value (default `"gromozeka"`). User `customParams.extra_headers`
merge at the header level and win per header name. Separately, all
OpenAI-compatible clients identify themselves with a
`User-Agent: GromozekaBot/<version>` `default_headers` entry
(`DEFAULT_USER_AGENT` in `basic_openai_provider.py`) instead of the broad
`Python OpenAI client` SDK default.

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
(`custom-openai`, `openrouter`, `yc-openai`, `opencode-go`) and the `yc-sdk` provider.
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
| `_getImageRequestOptions()` | `BasicOpenAIModel` | Returns `dict(self._customParams)` verbatim — no whitelist — to be merged into the OpenAI Images-API request. All image-API params (`size`, `quality`, `output_format`, `moderation`, ...) flow through the model's `customParams.*` TOML namespace. |
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
| Extra-config keys | `support_embeddings` (required `true`), `support_text` (set `false`), `embedding_dimensions` (optional). Fastembed kwargs (`cache_dir`, `threads`, `max_length`, ...) go under `customParams.*`, NOT `extraConfig` — they are forwarded verbatim to `TextEmbedding(...)` via `**customParams` |
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
context = 0
support_text = false
support_embeddings = true
embedding_dimensions = 384
tier = "free"
enabled = true
```

Fastembed-specific kwargs (`cache_dir`, `threads`, `max_length`, ...) go under
`customParams.*` and are forwarded verbatim to
`TextEmbedding(model_name=..., **customParams)` on first use — there is no
`_CONSUMED_EXTRA_KEYS` filter anymore, so only put keys that
`TextEmbedding.__init__` actually accepts.

```python
model = llmManager.getModel("local-minilm")
vector: list[float] = await model.generateEmbeddings("hello world")
```

The vector is a plain `list[float]` — same shape every embedding backend in the codebase returns, so the chat-search pipeline (`saveMessageEmbedding` / `searchChatMessages`) works unchanged across OpenAI, Yandex, and local providers.

**Default model:** `local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-dim, ~0.22 GB, ~50 languages, 512 token context) is the per-chat default for the `EMBEDDING_MODEL` chat setting via `embedding-model = "local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"` under `[bot.defaults]` in [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml). Both this model and the larger alternative `local/jinaai/jina-embeddings-v3` (1024-dim, ~2.24 GB, ~100 languages, 1024 token context) are registered in [`configs/00-defaults/fastembed-models.toml`](../../configs/00-defaults/fastembed-models.toml). The model resolution chain in `ChatSearchHandler._dtCronJob` (backfill) and the `MessagePreprocessorHandler` embedding dispatch is single-tier: the per-chat `EMBEDDING_MODEL` setting provides the value, and an empty / unresolvable model is a silent no-op for that chat on that tick. The server-wide `[search-history.embeddings].model` and `[search-history.embeddings].on-save` config keys were removed — the per-chat default already provides the model name, and the on-save dispatch is now unconditional whenever `[search-history].enabled` and `EMBEDDINGS_ENABLED` are both on. See [`configuration.md`](configuration.md) for the full `[search-history]` reference.

**Proxy support:** `LLMManager.__init__()` itself does not take a proxy argument — proxy is resolved per-provider from each provider's own service config. `BasicOpenAIProvider._initClient()` calls `ProxyConfig.fromServiceConfig(self.config)` then `ProxyConfig.toKwargs()` to construct a custom `httpx2.AsyncClient` for the OpenAI SDK (stored on `self._proxyHttpClient`) — httpx2 is aliased as `httpx` process-wide via `httpx2.alias_httpx()`, so source reads `httpx.AsyncClient` (see [`architecture.md`](architecture.md) ADR-021). Image download (`BasicOpenAIModel._generateImageViaImagesApi`) and OpenRouter `listRemoteModels()` likewise call `ProxyConfig.fromServiceConfig(self.config).toKwargs()` to wire the proxy into their ad-hoc HTTP clients.

---

## 2. `lib/cache` — Generic Cache Interface

**Import:**
```python
from lib.cache import CacheInterface, DictCache, NullCache, GenericDatabaseCache
from lib.cache import StringKeyGenerator, HashKeyGenerator, JsonKeyGenerator
from lib.cache import ValueConverter, JsonValueConverter, StringValueConverter
```

**Key classes:**

| Class | File | Purpose |
|---|---|---|
| [`CacheInterface[K,V]`](../../lib/cache/interface.py:15) | `lib/cache/interface.py` | Generic ABC for any cache |
| `DictCache[K,V]` | `lib/cache/dict_cache.py` | In-memory dict implementation |
| `NullCache[K,V]` | `lib/cache/null_cache.py` | No-op cache (testing / disabled caching) |
| [`GenericDatabaseCache[K,V]`](../../lib/cache/sql_cache.py:38) | `lib/cache/sql_cache.py` | Database-backed implementation (owns `cache`-table SQL; ADR-024) |
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
await cache.clearOld(ttl: Optional[int]) -> bool
cache.getStats() -> Dict[str, Any]
```

**DictCache constructor:**
```python
cache = DictCache[K, V](
    keyGenerator: KeyGenerator[K],        # Required: strategy for converting keys
    defaultTtl: int = 3600,               # Optional: default TTL in seconds
    maxSize: Optional[int] = 1000,        # Optional: max entries before eviction
)
```
(Thread safety is unconditional — all mutations run under an internal `threading.RLock`.)

**DB-backed implementation:** [`GenericDatabaseCache`](../../lib/cache/sql_cache.py:38) in `lib/cache/sql_cache.py` — backed by the `cache` table (namespace/key/data with `updated_at`, per `migration_012`). Takes a `DatabaseManager` directly (`__init__(manager, namespace: str, keyGenerator=None, valueConverter=None, *, dataSource=None)`; per-call `manager.getProvider(...)`) — no `Database` wrapper (ADR-024). Owns ALL `cache`-table SQL inline (`get`/`set`/`clear` + the `clearOld(ttl)` TTL sweep; `ttl > 0` deletes entries strictly older than `now − ttl`, `ttl` of `0`/`None` deletes every namespace entry); `CacheRepository` (`db.cache`) no longer touches this table — it keeps only the `cache_storage` trio backing `CacheService` persistence. Constructed by the `weather` (5 caches) and `yandex_search` (3 caches) handlers over `self.db.manager`, passing `CacheType` StrEnum members as `namespace` (they bind directly as `str`); `HandlersManager._cleanupOldData` builds transient per-namespace instances for the weekly TTL sweep (single pass over all `CacheType` members with conditional TTL: 7-day aggressive TTL for `WEATHER`/`YANDEX_SEARCH`/`URL_CONTENT`/`URL_CONTENT_CONDENSED`, 365-day default floor for the rest).

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
await limiter.applyLimit(queue: str = "default", timeout: Optional[int] = None) -> bool  # True = applied; False = wait would exceed timeout (slot not consumed)
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

**API endpoint:** [`API_BASE_URL`](../../lib/max_bot/constants.py) = `https://platform-api2.max.ru` (Max API v2; migrated from the deprecated `platform-api.max.ru` and legacy `botapi.max.ru`, both kept as comments only). Deadline: 2026-07-19.

**TLS / Минцифры CA certs:** the v2 endpoint is signed by the Russian Ministry of Digital Development (Минцифры) root CA, which is not in the system bundle. `libMax.utils.buildMaxSslContext(caBundlePath)` loads the additional PEM files from the `[bot].max-ca-bundle` directory into an `ssl.SSLContext`. The path resolves relative to the current working directory at call time (same convention as every other project path); the default value is `"../certs/max"`, which — because `application.root-dir` is `"storage"` — resolves to `<repo-root>/certs/max/`. The `caBundlePath` is passed to `MaxBotClient(caBundlePath=...)`, which builds the SSL context internally via `buildMaxSslContext()` and forwards it to `httpx2.AsyncClient(verify=...)` in `_getHttpClient` (httpx2 is aliased as `httpx` process-wide — see [`architecture.md`](architecture.md) ADR-021). When the key is empty/unset, httpx2 falls back to its default trust resolution (httpx2 ≥ 2.3 uses `truststore` / the OS trust store rather than bundled `certifi` certs). SOCKS5 proxies are handled by httpx2's native `proxy="socks5://..."` support; the SSL context is applied uniformly at the client level via `verify=self._sslContext` (see [`MaxBotClient._getHttpClient`](../../lib/max_bot/client.py)).

**Key constants:**
- `MAX_MESSAGE_LENGTH` — max message length for Max platform
- `DEFAULT_RATE_LIMIT` — `30` requests per second (down from `100` on the deprecated `platform-api.max.ru`; enforced server-side on platform-api2)
- `MAX_RETRIES` — `5`

**Key model submodules:**
- [`lib/max_bot/models/message.py`](../../lib/max_bot/models/message.py) — Message models
- [`lib/max_bot/models/chat.py`](../../lib/max_bot/models/chat.py) — Chat models
- [`lib/max_bot/models/attachment.py`](../../lib/max_bot/models/attachment.py) — Attachment models
- [`lib/max_bot/models/enums.py`](../../lib/max_bot/models/enums.py) — Enum types
- [`lib/max_bot/models/keyboard.py`](../../lib/max_bot/models/keyboard.py) — Keyboard/button models
- [`lib/max_bot/models/update.py`](../../lib/max_bot/models/update.py) — Update/event models

**IMPORTANT gotcha — Max platform sticker stubs:**
Animated stickers have stub URLs, not real images. Always check `url.startswith(...)` before processing

**Proxy support:** `MaxBotClient.__init__()` accepts an optional `proxyKwargs` keyword argument (dict to spread into `httpx2.AsyncClient` — httpx2 is aliased as `httpx` process-wide via `httpx2.alias_httpx()`, see [`architecture.md`](architecture.md) ADR-021). When proxy is enabled for the bot, `MaxBotApplication._runPolling()` creates a `ProxyConfig` via `ProxyConfig.fromServiceConfig()` and passes the resulting kwargs from `ProxyConfig.toKwargs()` — a single-key `{proxy: str}` (the proxy URL, `http://...` or `socks5://...`) for both HTTP and SOCKS5.

**SSL support:** `MaxBotClient.__init__()` also accepts an optional `caBundlePath: Optional[str]` keyword argument. When provided, the client builds an `ssl.SSLContext` internally via `buildMaxSslContext(caBundlePath)` and forwards it to `httpx2.AsyncClient(verify=...)` in `_getHttpClient`. The `verify=<sslContext>` is applied uniformly at the client level for **both** HTTP and SOCKS5 proxies — httpx2's native `proxy="socks5://..."` support (no separate `transport=`) accepts a top-level `verify=`, so the old SOCKS5 special-case (`AsyncProxyTransport.from_url(url, verify=sslContext)` + the `"transport" not in proxyKwargs` guard) is gone. The `caBundlePath` value comes from the `max-ca-bundle` config key — see TLS note above. When `buildMaxSslContext()` cannot load a cert (typically the GOST certs on a non-GOST OpenSSL build) it is skipped with a warning; if any are skipped a summary warning is logged (`Loaded N CA cert(s) but M were skipped ... TLS to platform-api2.max.ru may fail if the chain requires them`) so operators can tell a skipped-cert failure from a missing-bundle failure.

**Webhook-mode polling:** when `basePollingUrl` is set (Max webhook receiver mode — see [`architecture.md`](architecture.md) ADR-013), `getUpdates()` does not hit `platform-api2.max.ru`; instead it routes through `_makeLocalRequest()` to the receiver's `GET /updates`. Three consequences of that routing: (1) the `lastEventId` marker is widened to `Optional[Union[int, str]]` — the real API uses an int marker, but the local receiver returns a compound string marker `"{received_at}|{rowId}"` that the bot echoes back on its next poll (and returns `null` in immediate/at-most-once mode); (2) a dedicated, reusable `httpx2.AsyncClient` (`_localHttpClient`, created lazily on first poll and closed in `aclose()`; httpx2 is aliased as `httpx` — see [`architecture.md`](architecture.md) ADR-021) handles the local polls so connection pooling is reused across the polling loop, bypassing the main client's base URL / proxy / TLS settings; (3) a non-JSON 200 body from the receiver (e.g. a crash mid-response) is caught and re-raised as `NetworkError` rather than letting `json.JSONDecodeError` escape the polling loop.

**Chat discovery:** the client intentionally exposes no `getChats()` wrapper. The Max server's `GET /chats` endpoint is deprecated on `platform-api2.max.ru`, so chat discovery is subscription-based only (see `ENDPOINT_SUBSCRIPTIONS = "/subscriptions"` in [`constants.py`](../../lib/max_bot/constants.py) and the bot's subscription handlers).

---

## 6. `lib/bayes_filter` — Spam Filter

**Import:**
```python
from lib.bayes_filter.bayes_filter import NaiveBayesFilter, BayesConfig
from lib.bayes_filter.models import SpamScore
```

**Key class:** `NaiveBayesFilter` — Naive Bayes classifier (the public name is `NaiveBayesFilter`; the module path is `lib/bayes_filter/bayes_filter.py` and it is re-exported from `lib/bayes_filter/__init__.py`)

**Constructor:**
```python
NaiveBayesFilter(storage: BayesStorageInterface, config: Optional[BayesConfig] = None)
```

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

**Multi-source storage:** the filter is storage-agnostic — pass any implementation of `BayesStorageInterface` (`lib/bayes_filter/storage_interface.py`). The production backend is `DatabaseBayesStorage` in [`internal/database/bayes_storage.py`](../../internal/database/bayes_storage.py); per-chat vs. global routing is controlled by `BayesConfig.perChatStats`, not by a constructor argument.

---

## 7. `lib/openweathermap` — Weather Client

**Import:**
```python
from lib.openweathermap.client import OpenWeatherMapClient
```

**Key methods:**
```python
client = OpenWeatherMapClient(apiKey="...")
coords = await client.getCoordinates(city="Moscow")              # GeocodingResult
weather = await client.getWeather(lat=55.75, lon=37.62)          # WeatherData (One Call API)
weather = await client.getWeatherByCity(city="Moscow")           # convenience: geocode + getWeather
```

**Tests:** Uses golden data framework in `tests/lib/openweathermap/test_weather_client.py`

**Proxy support:** `OpenWeatherMapClient.__init__()` accepts an optional `proxyConfig: Optional[ProxyConfig]` keyword argument (a `ProxyConfig` instance, NOT a kwargs dict). `WeatherHandler` resolves it via `ProxyService.getInstance().resolveProxy(openWeatherMapConfig, "openweathermap")` (which internally calls `ProxyConfig.fromServiceConfig()` and registers any per-service lifecycle) and passes the resulting `ProxyConfig` directly to the client constructor. The client runs on httpx2 (aliased as `httpx` process-wide — see [`architecture.md`](architecture.md) ADR-021).

---

## 8. `lib/geocode_maps` — Geocoding

**Import:**
```python
from lib.geocode_maps.client import GeocodeMapsClient
```

**Key methods:**
```python
client = GeocodeMapsClient(apiKey="...")
results  = await client.search("Moscow, Russia")             # forward geocode  -> Optional[SearchResponse]
location = await client.reverse(55.75, 37.62)                # reverse geocode  -> Optional[ReverseResponse]
places   = await client.lookup(["R2623018", "N107775"])      # OSM lookup by ID -> Optional[LookupResponse]
```

`search()` and `lookup()` return lists (cast to `SearchResponse` / `LookupResponse`); `reverse()` returns a single object. All three return `None` on any HTTP / parse / API error — the client logs and swallows exceptions rather than raising.

**Config:** Configured via `[geocode-maps]` TOML section, accessed via `configManager.getGeocodeMapsConfig()`

**Proxy support:** `GeocodeMapsClient.__init__()` accepts an optional `proxyConfig: Optional[ProxyConfig]` keyword argument (a `ProxyConfig` instance, NOT a kwargs dict). `WeatherHandler` resolves it via `ProxyService.getInstance().resolveProxy(geocodeMapsConfig, "geocode-maps")` (which internally calls `ProxyConfig.fromServiceConfig()` and registers any per-service lifecycle) and passes the resulting `ProxyConfig` directly to the client constructor. The client internally calls `proxyConfig.toKwargs()` once per request when constructing each `httpx2.AsyncClient` (httpx2 is aliased as `httpx` process-wide — see [`architecture.md`](architecture.md) ADR-021).

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
| [`StatsStorage`](../../lib/stats/stats_storage.py:13) | `lib/stats/stats_storage.py` | ABC for statistics storage backends |
| [`NullStatsStorage`](../../lib/stats/stats_storage.py:141) | `lib/stats/stats_storage.py` | No-op implementation (discards all events) |
| [`StatsAnalyzer`](../../lib/stats/analysis.py) | `lib/stats/analysis.py` | Read-side filtering/grouping/aggregation over `query()` rows (pure Python) |
| `StatsAggregateDict` + `STATS_QUERY_ROW_LIMIT` | `lib/stats/types.py` | TypedDict for one aggregated stats row (5 camelCase fields, labels parsed from JSON) and the shared default `query()` row limit (`STATS_QUERY_ROW_LIMIT: int = 10000`) |

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

await statsStorage.purgeProcessed(
    *,
    retentionDays: int,
) -> int

await statsStorage.query(
    *,
    eventType: str,
    periodType: Optional[str] = None,
    periodStartFrom: Optional[str] = None,
    periodStartTo: Optional[str] = None,
    limit: int = 10000,
    offset: int = 0,
) -> list[StatsAggregateDict]
```

**Method details:**

- `record()`: Append a raw stat event to the log. Failures are logged but not raised.
- `aggregate()`: Claim up to `limit` unprocessed (or orphaned) events, aggregate into hourly/daily/monthly/total buckets, upsert into the aggregation table, and mark events as processed. Returns the number of events processed (0 if nothing to do).
- `purgeProcessed()`: Delete this storage's own event type's processed events older than the retention window (``processed = 1 AND event_type = :eventType AND created_at < cutoff`` through this storage's own data source). ``retentionDays <= 0`` is a no-op (returns 0, deletes nothing). Errors propagate to the caller (matching ``aggregate()``'s contract). Used by `StatsAggregationService` per storage after each aggregation cycle to clean up old processed events. `NullStatsStorage` returns 0.
- `query()`: Read aggregated rows filtered by `eventType` (required), `periodType` (optional: `'hourly'`, `'daily'`, `'monthly'`, or `'total'`), and optional inclusive bounds `periodStartFrom` / `periodStartTo` (ISO-8601 UTC strings). Returns rows with labels parsed from JSON as `StatsAggregateDict` (fields: `periodStart`, `periodType`, `labels`, `metricKey`, `metricValue`). Applies `limit`/`offset` via provider's `applyPagination()`. Raises on database/provider errors. `NullStatsStorage` returns `[]`.

**Analysis (read-side)** — [`lib/stats/analysis.py`](../../lib/stats/analysis.py), re-exported from the package root; pure-Python post-processing over `query()` rows (no SQL label filtering), used by `StatsHandler`:
- `StatsAnalyzer(rows)` — immutable analyzer over `list[StatsAggregateDict]`; filter methods return new instances: `filterByLabelIn(key, values)` / `filterByLabel(key, value)` (callers filter the `consumer` label to concrete chat IDs, which naturally excludes `__global__` rows), plus `sumMetric(metricKey)`, `groupSum(groupLabel, metricKey)`, `topN(groupLabel, metricKey, n)`, and `average(valueKey, countKey)` (weighted average Σvalue / Σcount — never an average of averages).
- `mapPeriodArgToPeriodType(periodArg)` — maps `/stats` period args to query granularity (constants in `PeriodArg` / `PeriodType`, both `StrEnum`): `1h`–`24h` → `hourly`, `1d`–`31d` → `daily`, `Nm` (`N ≥ 1`, calendar months) → `monthly`, `all` → `total`; `ValueError` otherwise.
- `computePeriodRange(periodArg, *, now=None)` — returns `(periodStartFrom, periodStartTo)` ISO-8601 UTC bounds (`(None, None)` for `all`); the start is truncated to the period boundary so the partial current day is included (7d → 8 daily buckets, 30d → 31). `now` is keyword-only; when supplied it MUST be timezone-aware (`ValueError` on a naive datetime) and is normalized to UTC; `None` defaults to the current UTC time.

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

**DB-backed implementation:** [`DatabaseStatsStorage`](../../lib/stats/sql_storage.py:44) in `lib/stats/sql_storage.py` — backed by `stat_events` (append-only log) and `stat_aggregates` (period buckets). Takes a `DatabaseManager` directly (`__init__(manager, eventType, *, dataSource)`; per-call `manager.getProvider(...)`) — no `Database` wrapper (ADR-023). Keeps a plain `dataSource` attribute (`str`) used for provider routing (`getProvider(dataSource=...)`); there is no `dataSource` member on the `StatsStorage` ABC. Constructed solely by the `StatsAggregationService` factory (`createStatsStorage`, [`internal/services/stats/service.py`](../../internal/services/stats/service.py:251)); `main.py` initializes the service and loops the event types — each call gated on `[stats].enabled` inside the factory.

**Integration points:**
- `LLMManager` receives `statsStorage` in constructor and propagates to all `AbstractModel` instances
- `AbstractModel` records generation stats (tokens, errors, status) via `_recordAttemptStats()`: per attempt — `generation_{text|structured|image}`, `request_count`, `input_tokens`, `output_tokens`, `total_tokens`, `is_error`, `tool_calls_count` (`len(result.toolCalls)`), `status_{STATUS}`, `elapsed_time`, plus optional `cached_input_tokens` / `reasoning_tokens` / `cost` recorded **only when the provider reported them** (absent metric = not reported, not zero)
- `LLMService` passes `consumerId=str(chatId)` to LLM generation methods
- `message` events — `BaseBotHandler.saveChatMessage` records `message_count`/`text_length` for messages in **both directions** (stats `{message_count: 1, text_length: len(text)}`). Direction comes from sender identity, not category: the `sent` label is `"True"` when `sender.id` equals the bot id (resolved via `TheBot.getBotId()`, memoized with a 1 h TTL — `BOT_ID_CACHE_TTL_SECONDS`; failures are never cached, and if resolution fails recording still proceeds with `sent = "False"` — unknown identity counts as non-bot) and `"False"` otherwise. Labels: `user_id`/`chat_type`/`message_type`/`message_category`/`sent`. Only `DELETED`/`UNSPECIFIED` categories are excluded (rewrites/defaults); every raw save counts, so split message parts each record one event. The `StatsAggregationService` factory builds the `messageStatsStorage` (gated on `[stats].enabled`; `main.py` loops the event types) and threads it through both bot applications into `HandlersManager`, which injects it post-construction onto every handler. Default is `NullStatsStorage` so stats-off needs no `None` checks.
- `llm_tool_call` events — `LLMService.injectStatsStorage` receives a `DatabaseStatsStorage` built by the `StatsAggregationService` factory (key `[stats].tool-stats-data-source`; wired from `main.py`); every tool dispatch in the `generateTextViaLLM` loop records `tool_call_count`/`elapsed_time`/`is_error` with `user_id`/`toolName` labels. Tools that raise propagate unrecorded (never-raise contract makes that a bug, not a stats gap).
- `command` events — `HandlersManager.handleCommand` records `command_count`/`is_error` with `user_id`/`commandName` (lowercased) labels for every **executed** command (denials/unrecognized commands are not recorded); `consumerId` is the chat ID. The `StatsAggregationService` factory builds the storage (key `[stats].command-stats-data-source`, gated on `[stats].enabled`); `main.py` threads it through both bot applications into `HandlersManager`.

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

**Usage from a handler:** `TarotSystem` / `RunesSystem` inherit classmethods from `BaseDivinationSystem` — no instances are needed. `resolveLayout(name)` and `draw(layout)` operate on the class-level deck and layouts.
```python
from lib.divination.tarot import TarotSystem

layout = TarotSystem.resolveLayout("three_card")  # case/separator-insensitive -> Optional[Layout]
if layout is None:
    raise ValueError("Unknown layout")
draws = TarotSystem.draw(layout)  # -> Tuple[DrawnSymbol, ...]; uses random.SystemRandom by default
```

---

## 11. `lib/sandbox/` — Sandboxed Code Execution

Safely execute untrusted Python code in Docker containers. Provides a
singleton `SandboxManager` entry point that composes a backend (Docker),
runtimes (Python), metadata store (filesystem), and lock registry.

- **Coding patterns & constraints:** [`sandbox.md`](sandbox.md)
- **Design:** [`docs/plans/python-sandboxing-v1.md`](../plans/python-sandboxing-v1.md), [`docs/plans/sandbox-update-v1.md`](../plans/sandbox-update-v1.md) (staged install + atomic swap for pool installs/updates)
- **Integration:** [`docs/archive/plans/python-sandboxing-v1-integration.md`](../archive/plans/python-sandboxing-v1-integration.md) (archived)

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
| [`gc.py`](../../lib/sandbox/gc.py) | Garbage collector for expired sessions, orphan workspaces, run records, stale staging artifacts under `<root>/tmp` |
| [`backends/docker.py`](../../lib/sandbox/backends/docker.py) | Docker backend via `aiodocker` |
| [`runtimes/python/runtime.py`](../../lib/sandbox/runtimes/python/runtime.py) | Python runtime with `timeout` wrapper and artifact detection |
| [`runtimes/python/pool_pip_runner.py`](../../lib/sandbox/runtimes/python/pool_pip_runner.py) | In-container pip runner for staged pool installs/updates (dry-run `--report` and `--install-into` modes; mounted into containers, not baked into the image) |
| [`runtimes/python/pool_staging.py`](../../lib/sandbox/runtimes/python/pool_staging.py) | Host-side staging module — dist-info/METADATA enumeration, RECORD parsing with jail checks, staged-delta merge, atomic pool swap |
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

> **httpx2 (aliased as `httpx`) note:** the package produces plain kwargs dicts
> consumed by `httpx2.AsyncClient` (the runtime alias of `httpx.AsyncClient` —
> see [`architecture.md`](architecture.md) ADR-021). It does **not** import
> `httpx`/`httpx2` itself and has no dependency on `httpx-socks` — SOCKS5 is
> handled by httpx2's native `proxy="socks5://..."` support (the `httpx2[socks]`
> extra pulls `socksio`). `ProxyKwargs` is a single-key `{proxy: str}` for both
> HTTP and SOCKS5; there is no `transport` key and no `verify` argument.

**Import:**
```python
from lib.proxy import ProxyConfig, ProxyHelper, ProxyType, ProxyKwargs
```

**Types:**

| Type | Purpose |
|---|---|
| `ProxyType` | `StrEnum("http", "socks5", "none")` — supported proxy protocol types |
| `HealthCheckType` | `StrEnum("none", "url", "command")` — health check mechanism for proxy lifecycle |
| `ProxyKwargs(TypedDict)` | Keyword arguments for `httpx2.AsyncClient` — a single `proxy: str` key (the proxy URL, `http://...` or `socks5://...`). Both HTTP and SOCKS5 produce the same shape; the caller applies `verify=<ssl.SSLContext>` at the client level. |
| `ProxyLifecycleConfigDict(TypedDict)` | Optional lifecycle configuration with 7 fields: `startCommand`, `stopCommand`, `restartCommand`, `healthCheckType`, `healthCheckUrl`, `healthCheckCommand`, `healthCheckInterval` |

**Classes:**

| Class | Purpose |
|---|---|
| `ProxyConfig` | Immutable proxy configuration (`__slots__`). Created via `fromServiceConfig()` or `fromDict()`. Methods: `getCombined()` (merge with global), `getProxyURL(maskPassword=False)` (build URL), `toKwargs()` (httpx2 kwargs — a single-key `{proxy: str}` for both HTTP and SOCKS5; no `transport` key, no `verify` argument). Has optional `lifecycle` field of type `ProxyLifecycleConfigDict`. |
| `ProxyHelper` | Singleton storing the global proxy config. `setGlobalProxyConfig()` called once at startup inside `ProxyService.initialize()` (triggered from `main.py`; standalone scripts use `scripts/_lib/bootstrap.py`); `getGlobalProxyConfig()` used internally by `ProxyConfig.getCombined()`. |

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

# Then in HTTP calls (httpx2 is aliased as httpx process-wide — see ADR-021):
async with httpx.AsyncClient(**proxyKwargs, timeout=30) as client:
    ...
```

**Per-service override semantics (`fromServiceConfig`):** When a service sets `use-proxy = true` with a `[service.proxy]` sub-section, `fromServiceConfig` delegates to `fromDict` which reads `enabled` from the sub-dict via `data.get("enabled") is True`. If the sub-section omits `enabled: true`, the resulting ProxyConfig has `enabled=False`, and `getCombined()` treats it as "inherit from global" — the per-service override fields (`type`, `address`, etc.) are silently ignored. Always include `enabled: true` in the proxy sub-section when you intend to override the global config for a specific service. This is intentional behavior.

**Password masking in `__repr__` / `__str__`:** Non-empty passwords render as `'***'` in `repr()` and `str()` output. This prevents accidental credential leaks through logging/debugging while keeping other fields visible. When password is `None` or an empty string, it renders verbatim. This is separate from `getProxyURL(maskPassword=True)` which replaces the password with `"REDACTED"` in the built URL.

**SQLink proxy — lazy resolution:** `SQLinkProvider.__init__` accepts `proxy` and `use-proxy` inside `parameters` (see `configuration.md`) and stores a `ProxyConfig` object. The proxy URL is not resolved at construction time — resolution happens in `connect()` via `self._proxy.getProxyURL()`. This ensures the global proxy config (set by `main.py`) is available at resolution time.

---

## 14. `sqlite-vec` — Native Vector Search Extension

**Pinned dependency:** `sqlite-vec==0.1.9` (in `requirements.direct.txt` under `# Runtime`). Optional at runtime — the `SQLite3Provider` guards the import with a module-level `try/except ImportError` and an `_SQLITE_VEC_AVAILABLE` flag; if absent, `isVectorSearchSupported()` returns `False` and semantic search returns `[]` (no numpy fallback — the previous numpy fallback path in `chat_search.py` / `user_memories.py` was retired in `migration_025_embedding_model_lookup`).

**Purpose:** provides the `vec0` virtual table module for native cosine-similarity KNN search inside the SQLite process, eliminating the transfer of all embedding BLOBs to Python on every search. Loaded by `SQLite3Provider.connect()` via aiosqlite's `enable_load_extension` / `load_extension` / `enable_load_extension(False)` (wrapped in `try/finally`).

**Used by:** `lib/db/providers/sqlite3.py` (`SQLite3Provider`), `internal/database/repositories/chat_embeddings.py` (writes to `vec_message_embeddings_{N}`; the previous dual-write to the `message_embeddings` BLOB table was retired in `migration_025` — embeddings now live only in vec0 with the model tracked via `chat_messages.model_id`), `internal/database/repositories/chat_search.py` (`_nativeVectorSearch`). See [`database.md`](database.md) §7 "Vector search types" for the provider interface and the vec0 schema, and [`docs/design/vector-search-native.md`](../design/vector-search-native.md) for the design.

**No config key** — auto-detected at connect time. To disable native search: `pip uninstall sqlite-vec`.

---

## 15. `aiohttp` — HTTP Server for the Webhook Receiver

**Pinned dependency:** `aiohttp==3.14.3` (in `requirements.direct.txt` under `# Runtime`). Promoted from a transitive dependency (pulled in via `aiodocker`) to a direct one because the Max webhook receiver imports it directly.

**Purpose:** provides the `aiohttp.web` server that the standalone Max webhook receiver process runs on. The receiver itself is documented as a lib package in §19 below.

**Used by:** [`lib/max_webhook_receiver/`](../../lib/max_webhook_receiver/) — `__main__.py` (`web.run_app`) and `app.py` (`createApp`, `handleWebhook`, `handleGetUpdates`). See [`architecture.md`](architecture.md) ADR-013/ADR-025, §19 below, and [`configuration.md`](configuration.md) §`[webhook-receiver]`.

**No config key of its own** — the receiver's listen address, port, and TLS are configured in the receiver's own config file (see §19 and [`configuration.md`](configuration.md)).

---

## 16. `lib/stt` — Provider-neutral Speech-to-Text

Provider-neutral Speech-to-Text library: PyAV-based audio extraction with container-driven format negotiation (probe → pass-through / transcode; pass-through preserves source channels, transcode converts out-of-spec channels/rates via AudioResampler), a typed extraction-exception taxonomy, provider-neutral models/enums, an abstract provider exposing a **never-raise** `stt(data)` entry, and a single concrete provider (Yandex SpeechKit v3). It owns no DB rows, no bot state, no admission/concurrency policy, no caps, no transcript formatting, and no config reading.

> **Service formatter:** [`internal/services/stt/formatter.py`](../../internal/services/stt/formatter.py) formats the structured result, not `lib/stt`. It emits `[Speaker#<tag>] [start..end] text` for a non-empty `attributionTag` on a `SPEAKER` result; for `CHANNEL`, it emits `[Ch#<tag>] [start..end] text` only when more than one distinct non-empty tag is present, otherwise `[start..end] text`. Speaker labels are opaque and recording-local. One timestamp is used when start equals end.

**Authoritative spec:** [`docs/design/lib-stt-v1.md`](../design/lib-stt-v1.md) — this section is a quick-reference; the design doc is the single source of truth for `lib/stt` internals (contracts, module layout, test matrix). **Integration status** (now wired via the stateless `STTService`) lives in [`docs/archive/design/stt-next-steps.md`](../archive/design/stt-next-steps.md) and [`services.md`](services.md) §7.

**Dependency firewall (load-bearing):** `lib/stt` is bot-free — it must never import `internal.bot`, `internal.database`, or any singleton service. The proxy is **injected** into the provider constructor (never resolved inside `lib/stt`); the audio bytes are a plain `bytes` argument to `extractAudio` / `stt` (never a bot download callable). The Yandex SpeechKit HTTP client runs on httpx2 (aliased as `httpx` process-wide — see [`architecture.md`](architecture.md) ADR-021). Sits alongside other bot-free libraries (`lib/ai/`, `lib/yandex_search/`, `lib/openweathermap/`).

**Key modules:**

| Module | Purpose |
|--------|---------|
| [`abstract.py`](../../lib/stt/abstract.py) | `AbstractSTTProvider`: concrete `stt(data, *, consumerId=None)` never-raise entry (wraps extract + transcribe), concrete `transcribe(audio, *, consumerId=None)` template-method (timing + `_recordStats` + `except Exception`→`PROVIDER_ERROR`; providers override the abstract `_transcribe(audio)`), `supportedInputFormats()` method, `aclose()` |
| [`audio.py`](../../lib/stt/audio.py) | `extractAudio(data, supportedInputFormats)` — PyAV probe + container-only format negotiation (pass-through/transcode); pass-through preserves source channels, transcode clamps channels+rate to the target spec's `[min,max]` bounds via `AudioResampler`; unconditional `import av`. **No caps** — the caller bounds source bytes before calling |
| [`models.py`](../../lib/stt/models.py) | `STTResultStatus`, `STTAttributionType` (`CHANNEL`/`SPEAKER`), `STTErrorCode` (shared failure vocabulary — 9 members as of v1.1: the new `OBJECT_STORAGE_ERROR` joins `NO_AUDIO`/`PROVIDER_ERROR`/`PROTOCOL_ERROR`/`SOURCE_TOO_LARGE`/…; `SOURCE_TOO_LARGE` ownership was extended to the provider for the over-threshold-without-OS case), `STTAudioContainerType` (+ `toYandexSpeechKit()`), `TranscriptionWord`/`TranscriptionSegment`/`TranscriptionResult`/`AudioFormatSpec`/`ExtractedAudio` (frozen, slots). Each segment has one optional generic `attributionTag`; the result-level type declares its role. `STTAttributionType` is publicly re-exported by `lib.stt`. |
| [`exceptions.py`](../../lib/stt/exceptions.py) | Typed extraction exceptions (`STTExtractionError` base → `NoAudioTrackError`/`AudioDecodeError`/`EncoderError`), each mapping 1:1 to an `STTErrorCode` via a class attribute |
| [`providers/yandex_speechkit.py`](../../lib/stt/providers/yandex_speechkit.py) | Yandex SpeechKit v3 wire protocol (submit / poll / get / best-effort delete + retry); `supportedInputFormats()` returns `(OGG_OPUS, MP3, WAV)`. `forceMono=false` preserves normal ranges; `true` advertises mono-only descriptors, forcing compatible multi-channel input through the existing downmix/re-encode path. Whenever final extracted audio is mono, both inline and `uri` submit bodies request speaker labeling; the parser then marks generic tags with the `SPEAKER` role. **v1.1:** routes clips ≥ `max-inline-bytes` through the co-located `YandexObjectStorage` helper; stats recording lives in base `AbstractSTTProvider.transcribe`. |
| [`providers/yandex_object_storage.py`](../../lib/stt/providers/yandex_object_storage.py) | **v1.1 (gate-3)** — co-located Yandex-Object-Storage-specific helper used directly by `YandexSpeechKitProvider`. boto3 is a hard, unconditional top-level import (pinned dependency); the boto3 client is built once with a bounded `botocore.config.Config` (connect/read timeouts + retry cap). `upload(data) -> str` (key `{prefix}{uuid}`, `put_object`, returns the SpeechKit URI) and `delete(uri) -> None` (missing object = no-op). Yandex endpoint/region are constants baked into the helper. boto3 is *external* (not `internal.*`), so the `lib/stt` firewall is intact |
| [`providers/yandex_events.py`](../../lib/stt/providers/yandex_events.py) | `getRecognition` streaming-JSON event parser. It reads only canonical envelope `channelTag` into generic attribution (missing/null/empty → `None`; all other JSON values → `str(value)`) and ignores deprecated `final.channelTag`. The result role is `CHANNEL` normally or `SPEAKER` when labeling was requested; refinement retains attribution and uses the canonical tag with a valid cursor to correlate speakers. |

**Never-raise contract:** `AbstractSTTProvider.stt(data: bytes)` is the integration entry point. It wraps `extractAudio` + `transcribe` and catches every failure — a typed `STTExtractionError` maps to `TranscriptionResult(ERROR, errorCode=exc.errorCode)`; any other exception maps to `TranscriptionResult(ERROR, PROVIDER_ERROR)`. So calling `stt(data)` can never raise for any expected or unexpected failure. The only runtime raise-point inside `lib/stt` is `audio.extractAudio()` when called **directly** (not via `stt()`); constructors may raise `ValueError` on startup config validation (the `YandexSpeechKitProvider` constructor owns cred / `${...}`-placeholder / cap-positivity / cross-field validation — see [`configuration.md`](configuration.md) `[stt]`). The downstream `STTService` is the final never-raise boundary — see [ADR-020](architecture.md#adr-020-sttservice--synchronous-stateless-stt-service-and-dependency-firewall).

**Accepted decoded-memory gap (load-bearing):** `extractAudio` does **NOT** bound decoded PCM memory — a large/long source can decode to hundreds of MB during probe/measure/transcode. This is an accepted simplification: the owning service (`STTService`) bounds source bytes AND duration BEFORE calling `stt(data)`. If RSS gate-5 ([`stt-next-steps.md`](../archive/design/stt-next-steps.md) §4) fails at release, the ratified fallback is to restore a decoded-buffer cap inside `extractAudio`, not a service-side change. Documented in the `extractAudio` docstring and [`docs/design/lib-stt-v1.md`](../design/lib-stt-v1.md) §5.

**PyAV prerequisite:** pins `av==18.0.0` (parent §8.4). The `import av` is now **unconditional** — the pre-simplification `_PYAV_AVAILABLE` guarded-import pattern is gone, so any `import lib.stt.*` hard-requires PyAV at import time (latent breakage only, since `av` is always in the frozen env).

**Tests:** `tests/lib/stt/` mirrors source paths, with service formatter coverage in `tests/services/stt/test_formatter.py` and `tests/services/stt/test_transcribe.py`, plus a golden-data suite under `tests/lib/stt/golden/`. Two sanitized live SpeechKit replays require `FINAL`, non-empty segments, generic attribution-tag set `{"0", "1"}`, and role `SPEAKER`; no transcript text is asserted. `async def test_...` needs no decorator (`asyncio_mode = "auto"`).

---

## 17. `lib/stats/stats_pages/` — Statistics Page Generator

Self-contained HTML page generator for statistics display. Used by `StatsHandler` via subprocess invocation for the `--web` tier. Module-invocable: `./venv/bin/python3 -m lib.stats.stats_pages`. Zero new runtime dependencies (stdlib `argparse`/`html`/`json`/`uuid`/`pathlib` only).

**Layout:**

| Path | Purpose |
|---|---|
| [`lib/stats/stats_pages/__init__.py`](../../lib/stats/stats_pages/__init__.py) | Package exports (`StatsPageGenerator`, `StatsPayload`, `ChatListEntry`, `StatsCliError`/`StatsCliErrorReason`, `runCliCommand`) |
| [`lib/stats/stats_pages/__main__.py`](../../lib/stats/stats_pages/__main__.py) | Main entry point for module invocation |
| [`lib/stats/stats_pages/generator.py`](../../lib/stats/stats_pages/generator.py) | Core generator class (`StatsPageGenerator`), `StatsPayload`/`ChatListEntry` TypedDicts, server-side grouping + SVG rendering, CLI handlers |
| [`lib/stats/stats_pages/launcher.py`](../../lib/stats/stats_pages/launcher.py) | Shared subprocess helper used by BOTH generation and deletion: `runCliCommand(argv, *, stdinPayload=None, timeoutSeconds=30.0) -> (returncode, stdout, stderr)` (async; kills the child on timeout AND on cancellation of the awaiting task; stdout/stderr decoded with `errors="replace"`) and `StatsCliError` with `StatsCliErrorReason.TIMEOUT`/`SPAWN` (StrEnum values are lowercase `"timeout"`/`"spawn"`; only spawn-time `OSError` maps to `SPAWN` — `OSError`s raised during `communicate()` are a distinct failure path, not spawn failures). Mirrors the subprocess conventions of `internal/services/proxy/lifecycle.py`. |

**CLI contract:**

- `generate` — reads a raw-rows JSON payload from stdin (see `StatsPayload` TypedDict), renders a self-contained static HTML page server-side (UUID filename, inline CSS, inline SVG charts, no external resources, no JS), prints `{"pageId": "<uuid>", "url": ...}` to stdout. Flags: `--base-url` (when given, `url` = `baseUrl.rstrip("/") + "/" + <uuid>.html`; without it, `url` is the bare `<uuid>.html` filename) and `--output-dir` (default `.`).
- `delete PAGE_ID` — validates the pageId against `^[0-9a-f]{32}$` first and prints `{"deleted": 0}` on mismatch without touching the filesystem (path-traversal guard); otherwise removes the page by UUID filename stem and prints `{"deleted": 0\|1}` to stdout (0 = no such page, still a success exit). Accepts `--output-dir` flag.
- Exit codes: 0 for success, nonzero for any failure (with a human-readable stderr line).
- Failure modes: invalid JSON on stdin → nonzero exit + error message; missing required fields in payload → nonzero exit + error message; file write errors → nonzero exit + error message.

**StatsPayload TypedDict** (stdin JSON contract — the bot applies ONLY scope/granularity/range filters and the 10000-row limit; ALL grouping, time-series construction, and rendering happens server-side in the generator):
```python
class StatsPayload(TypedDict):
    userId: str                    # User ID who requested the page
    chatId: str                    # Chat ID the page is for
    chatTitle: str                 # Chat title or name
    chatType: str                  # "private", "group", or "channel"
    platform: str                  # "telegram" or "max"
    period: str                    # e.g., "6h", "7d", "2m", "all"
    periodType: str                # "hourly", "daily", "monthly", or "total"
    generatedAt: str               # ISO-8601 UTC timestamp
    rows: dict[str, list[StatsAggregateDict]]
                                   # raw aggregate rows keyed by eventType:
                                   # "message", "command", "llm_tool_call",
                                   # "llm_request", "stt_request"
    chatList: NotRequired[list[ChatListEntry]]  # user's chats (private scope)
    truncatedEventTypes: NotRequired[list[str]]  # eventTypes that hit the 10000-row limit
```

`ChatListEntry` (`chatId`, `title`, `messagesCount`) is the TypedDict for `chatList` rows. `rows` values are `StatsAggregateDict` (from [`lib/stats/types.py`](../../lib/stats/types.py)) — already consumer-filtered to the target chat by the bot, and user-filtered for the user-level event types (`message`, `command`, `llm_tool_call`) when a `--user` filter is active.

**Rendering from raw rows** (no per-section view-model TypedDicts — those were deleted in the U12 raw-rows rework; the generator groups rows itself):
- One section per eventType present in `rows`: messages, commands, tools (`llm_tool_call`), LLM (`llm_request` with an STT subsection for `stt_request`).
- Each section gets an inline SVG bar chart of the time series built from the rows; `periodType == "total"` produces no time series (single sentinel bucket), so total-granularity pages skip charts. Hourly series are capped at 24 bars with an "… and N more" note.
- Truncation honesty: a "results may be incomplete" line is rendered for a section when its eventType appears in `truncatedEventTypes` (recorded by the bot BEFORE consumer filtering, when the raw query returned exactly 10000 rows) — the flag is the ONLY input; there is no fallback heuristic when it is absent.

**HTML rendering:**
- Self-contained: inline `<style>` block only, no `<link rel="stylesheet">`, no `<script src`, no CDN references.
- Escapes all text content via `html.escape()`.
- UTC timestamps labeled explicitly.
- Large numbers formatted with commas (e.g., `15,000`).
- Emojis used as section headers: 💬 Messages, 🔧 Commands, 🛠️ Tools, 🧠 LLM, 📋 Your Chats, 🎤 Speech-to-Text.
- Responsive design: max-width 900px container, clean table layout, hover effects.

**Integration with bot:**
- Not imported as a handler dependency for state — pure lib package; `StatsHandler` imports only the payload/entry TypedDicts and the launcher.
- Generation and deletion both go through `launcher.runCliCommand` (one subprocess helper, per D11 "exactly once" at the subprocess level): stdin payload JSON, 30-second timeout, kill-on-timeout, `StatsCliError` on TIMEOUT/SPAWN.
- The bot uses the stdout `url` VERBATIM as the reply link — it never composes URLs itself. Full URLs come from putting `--base-url` in the configured `generate-command` template; without it the CLI returns the bare `<uuid>.html` filename.
- Deletion is bot-managed via one-shot per-page `DelayedTaskFunction.STATS_PAGES_CLEANUP` tasks (scheduled after each successful generation; delay = `ttl-hours × 3600`; single attempt, no reschedule) — the CLI itself only provides the `delete` verb.

**Tests:**
- `tests/lib/stats/test_stats_pages_generator.py` — in-process generator tests with rows-shaped payloads (UUID filenames, base-URL construction, per-eventType grouping from raw rows, `sent`-direction split, top-users, SVG chart rendering for time series, file I/O, deletion).
- `tests/lib/stats/test_stats_pages_cli.py` — subprocess CLI contract tests (`{"pageId","url"}` stdout, `--base-url` full-URL and bare-filename variants, missing-field and invalid-JSON nonzero exits, SVG present for time series / absent for `total`, delete verb).
- `tests/lib/stats/test_stats_pages_launcher.py` — `runCliCommand` tests (success capture, stdin delivery, timeout kill, spawn failure → `StatsCliError`).

---

## 18. `lib/db` — SQL Provider Abstraction + `DatabaseManager`

Bot-free SQL layer: the `BaseSQLProvider` abstraction (portable `execute` / `executeFetchOne` / `executeFetchAll` / `batchExecute` / `upsert` + dialect hooks like `applyPagination` / `getTextType` / `getCaseInsensitiveComparison`), concrete SQLite3 and SQLink provider implementations, the `getSqlProvider` factory, and `DatabaseManager` (multi-source provider routing: `dataSource` > `chatId` mapping > default source). Extracted from `internal/database/` in a single big-bang move (git-mv, no shim, no dual-home) — see [`architecture.md`](architecture.md) ADR-022 and [`docs/design/lib-db-extraction-v1.md`](../design/lib-db-extraction-v1.md).

**Import:**
```python
from lib.db import BaseSQLProvider, DatabaseManager, DatabaseManagerConfig, getSqlProvider, SQLProviderConfig
from lib.db.providers.base import ExcludedValue, ParametrizedQuery, VectorColumnDef
```

(`lib/db/__init__.py` also re-exports `FetchType`, `QueryResult*`, `SQLite3Provider`, `SQLinkProvider`, `SQLProviderInitializationHook`, the vector-search types — `VectorColumnType`, `VectorDistanceMetric`, `VectorSearchResult` — and the decode exports from `utils.py`: `sqlToTypedDict`, `sqlToCustomType`, `FORCE_SQL_TIMEZONE` — ADR-023.)

**Key modules:**

| Module | Purpose |
|---|---|
| [`lib/db/providers/base.py`](../../lib/db/providers/base.py) | `BaseSQLProvider` ABC, `ParametrizedQuery`, `FetchType`, `QueryResult*`, `ExcludedValue` (portable upsert marker), vector-search TypedDicts/enums (`VectorColumnDef`, `VectorDistanceMetric`, `VectorSearchResult`) |
| [`lib/db/providers/__init__.py`](../../lib/db/providers/__init__.py) | `getSqlProvider` factory + `SQLProviderConfig`; registers exactly `sqlite3` + `sqlink` |
| [`lib/db/providers/sqlite3.py`](../../lib/db/providers/sqlite3.py) | `SQLite3Provider` (aiosqlite; optional `sqlite-vec` vector search via the `_SQLITE_VEC_AVAILABLE` guarded-import flag — module name deliberately shadows stdlib `sqlite3` in name only) |
| [`lib/db/providers/sqlink.py`](../../lib/db/providers/sqlink.py) | `SQLinkProvider` (SQLite-over-REST; proxy config resolved lazily via `lib.proxy` — see §13 "SQLink proxy") |
| [`lib/db/providers/mysql.py`](../../lib/db/providers/mysql.py) / [`lib/db/providers/postgresql.py`](../../lib/db/providers/postgresql.py) | Dormant providers — moved AS-IS with hard `aiomysql` / `asyncpg` imports, unregistered in the factory (known temporary deviation from the `_AVAILABLE` convention; ADR-022) |
| [`lib/db/providers/utils.py`](../../lib/db/providers/utils.py) | `convertToSQLite` and friends; defines the module-local `SQLStringifiable` `@runtime_checkable` Protocol (`.asStr()`) that replaced the former `internal.models.MessageId` import |
| [`lib/db/manager.py`](../../lib/db/manager.py) | `DatabaseManager` (provider routing + lifecycle), `DatabaseManagerConfig`, `SQLProviderInitializationHook` |
| [`lib/db/utils.py`](../../lib/db/utils.py) | SQL decode trio `sqlToTypedDict` / `sqlToCustomType` (plus private `_checkType` + container-type constants), `getCurrentTimestamp`, `DEFAULT_THREAD_ID`, `FORCE_SQL_TIMEZONE` — the whole module moved from `internal/database/utils.py` (ADR-023); deliberate coexistence with `providers/utils.py`, which is the ENCODE side (`convertToSQLite`) |

**Dependency firewall (load-bearing):** `lib/db` is bot-free — it imports only `lib.proxy`, `lib.utils`, stdlib, and third-party packages; never `internal.*`. Dependency direction is `internal → lib.db → {lib.proxy, lib.utils, stdlib, 3rd-party}`, guarded by the `make lint` `import main` cycle check. `internal/database/` survives with everything bot-specific (`Database` wrapper, repositories, migrations, models) and imports the SQL layer from here.

**Used by:** [`internal/database/`](../../internal/database/) — the `Database` wrapper, `MigrationManager` + versioned migrations, and the repositories. See [`database.md`](database.md) §7 for the provider helper-method reference (paths, upserts, vector search) and [`database.md`](database.md) §3 for multi-source routing.

**Tests:** `tests/lib/db/providers/` — provider unit tests (`test_base_provider.py`, `test_sqlite3_provider.py`, `test_sqlite3_vector_search.py`, `test_vector_search.py`), `test_sqlink_provider.py` (SQLinkProvider hermetic suite with FakeAsyncConnection mocking at the sqlink.asyncConnect boundary — no live server; also locks in the `__repr__` password redaction as `***`), `test_get_sql_provider.py` (factory tests), and `test_utils.py` (the `SQLStringifiable` Protocol regression test — ADR-022); plus decode/timestamp unit tests at `tests/lib/db/test_utils.py` (moved from `tests/database/` with the module — ADR-023).

---

## 19. `lib/max_webhook_receiver` — Standalone Max Webhook Receiver

Fully standalone aiohttp receiver process implementing ADR-013's two-process webhook architecture: accepts Max webhook POSTs, buffers them in the `webhook_updates` table in its OWN SQLite database, and serves them back to the bot via a `GET /updates` endpoint speaking the Max API protocol. Extracted from `internal/` in a single big-bang move (the old `internal/max_webhook_receiver/` package deleted; no shims) — see [`architecture.md`](architecture.md) ADR-025 and [`docs/design/lib-max-webhook-receiver-extraction-v1.md`](../design/lib-max-webhook-receiver-extraction-v1.md).

**Entry point** (module-invocable like `lib.stats.stats_pages`):

```bash
./venv/bin/python3 -m lib.max_webhook_receiver --config webhook-receiver.toml [--dotenv-file .env]
```

**Import:**

```python
from lib.max_webhook_receiver.app import createApp
from lib.max_webhook_receiver.models import WebhookUpdatesRow
from lib.max_webhook_receiver.repository import WebhookUpdatesRepository
from lib.max_webhook_receiver.schema import ensureWebhookUpdatesSchema, getForwardDDL
```

(The package `__init__.py` also re-exports `WebhookUpdatesRow`, `WebhookUpdatesRepository`, `WEBHOOK_UPDATES_TABLE_DDL`, `WEBHOOK_UPDATES_INDEX_DDL`, `ensureWebhookUpdatesSchema`, and `getForwardDDL` — but deliberately NOT `createApp`; see the firewall note below.)

**Key modules:**

| Module | Purpose |
|---|---|
| [`app.py`](../../lib/max_webhook_receiver/app.py) | `createApp(*, repository, manager, secret, getUpdatesSecret="", webhookPath="/webhook", enableCleanup=True, markOnSubsequentPoll=True) -> web.Application`; the two handlers (`handleWebhook` POST with `X-Max-Bot-Api-Secret` verification, `handleGetUpdates` GET /updates with the compound-marker deferred/immediate acknowledgment protocol); the 1h-TTL background cleanup task; and the `ensureSchema` startup self-heal |
| [`repository.py`](../../lib/max_webhook_receiver/repository.py) | `WebhookUpdatesRepository(manager)` — `addUpdate`, `getUnprocessedUpdates(limit=100)` (marker filtering), `markProcessed`, `markProcessedBeforeMarker`, `deleteProcessedOlderThan(ttlSeconds=3600)`; provider-level portable SQL (`:named` placeholders, `applyPagination`, app-side timestamps); deliberately does NOT subclass the internal `BaseRepository` (inlined `__slots__ = ("manager",)` — it lives outside the internal repository tree) |
| [`models.py`](../../lib/max_webhook_receiver/models.py) | `WebhookUpdatesRow` TypedDict (moved verbatim from `internal/database/models.py`) |
| [`schema.py`](../../lib/max_webhook_receiver/schema.py) | Canonical `webhook_updates` DDL (`WEBHOOK_UPDATES_TABLE_DDL`, `WEBHOOK_UPDATES_INDEX_DDL`), `getForwardDDL()` — the migration-side batch consumed by `migration_019.up()` and `migration_029.down()` — and `ensureWebhookUpdatesSchema(sqlProvider)`, the startup self-heal that creates BOTH the table and the index |
| [`__main__.py`](../../lib/max_webhook_receiver/__main__.py) | The launcher: `load_dotenv` → stdlib `tomllib` → `substituteEnvVars` ([`lib/utils/utils.py`](../../lib/utils/utils.py)) → `[webhook-receiver]` reads → `${VAR}` secret guard (`SystemExit(1)`) → `DatabaseManager` over `[webhook-receiver.database]` (pure passthrough) → `createApp(...)` → optional TLS → `web.run_app` |

**Own config + own database (ADR-025):** the receiver does NOT use `ConfigManager` — it reads its OWN single TOML config file (`--config`, default `webhook-receiver.toml`; `[webhook-receiver]`-rooted, dotenv + `${VAR}` substitution). Its `[webhook-receiver.database]` section (same shape as the bot's `[database]`) feeds a bare `DatabaseManager` pointing at the receiver's own file (`webhook_receiver_data.db` by default). The receiver never runs the bot's migrations and never touches the bot's database — the bot's chain dropped `webhook_updates` via `migration_029`, so the startup self-heal is the only schema authority for the receiver's database. `secret`/`get-updates-secret` are maintained in BOTH the bot config and the receiver file (drift = 403s) — see [`configuration.md`](configuration.md) §`[webhook-receiver]` for the split and the dual-secret cost.

**Dependency firewall (load-bearing):** the package is bot-free — zero `internal.*` imports anywhere (including the launcher), and `ConfigManager` must never re-enter it. The package `__init__.py` deliberately does NOT import `.app`: the bot's migrations (019 `up()` / 029 `down()`) import `.schema` transitively at bot startup, and aiohttp must stay out of that import chain — import `createApp` from `lib.max_webhook_receiver.app` directly.

**Deployment artifacts:** the package ships its own container support — a pinned standalone [`requirements.txt`](../../lib/max_webhook_receiver/requirements.txt) covering exactly the receiver's module-level import closure (aiohttp+deps, python-dateutil+six, aiosqlite+sqlink via the eagerly-imported providers; pins mirror the root lockfile with NO real `httpx`: the package `__init__` calls `httpx2.alias_httpx()` BEFORE its own imports — under `python -m lib.max_webhook_receiver` this `__init__` runs before `__main__`, and in the bot process `main.py` aliases first, so the repeat call is a no-op — so sqlink's hard `import httpx` resolves to httpx2 and the deployment lockfile therefore carries `httpx2`/`httpcore2`/`truststore` instead; because sqlink's metadata still declares `httpx>=0.28`, the Dockerfile installs with `pip install --no-deps`, which plain resolution would defeat by pulling real httpx back in) and a [`Dockerfile`](../../lib/max_webhook_receiver/Dockerfile) (python:3.13-alpine, non-root uid 10001, `/data` volume, config mounted at `/app/webhook-receiver.toml`) built from the repo root so the root [`.dockerignore`](../../.dockerignore) trims the context; sqlink is commit-pinned to a private git host, fetched at build time via a BuildKit `--secret id=netrc`. Operator-facing build/run instructions: [`max-webhook-setup.md`](../max-webhook-setup.md) §Docker deployment.

**Tests:** `tests/lib/max_webhook_receiver/` — `test_repository.py` (15 tests, incl. the `TestReceiverBringUp` self-heal pin over a manager-only bring-up), `test_app.py` (20 endpoint/lifecycle tests via `aiohttp.test_utils`), `test_main.py` (5 `TestLauncherConfig` tests over real temp TOML/dotenv files — no config mocks), `test_init.py` (fresh-subprocess guard that a bare package import aliases httpx→httpx2 without pytest's conftest aliasing); plus the bot-side migration test `tests/database/test_migration_029_drop_webhook_updates.py`.

---

## See Also

- [`index.md`](index.md) — Project overview, lib/ directory map
- [`services.md`](services.md) — Higher-level service wrappers (CacheService, LLMService, etc.)
- [`configuration.md`](configuration.md) — Configuring lib integrations via TOML
- [`testing.md`](testing.md) — Golden data framework for API testing
- [`tasks.md`](tasks.md) — Step-by-step: "add new API integration" decision tree
