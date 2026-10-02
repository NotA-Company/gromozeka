---
category: guide
---

# Libraries Reference

The reusable libraries under lib/: AI/LLM providers, caching, rate limiting, API clients, and sandboxed execution - plus recipes for adding new integrations.

## 8. Libraries Reference

### 8.1 AI/LLM System (`lib/ai/`)

The AI system provides a provider-agnostic interface for interacting with multiple LLM backends

**Key classes:**

| Class | File | Description |
|---|---|---|
| [`LLMManager`](/lib/ai/manager.py:49) | `manager.py` | Top-level registry of providers and models |
| [`AbstractLLMProvider`](/lib/ai/abstract.py:904) | `abstract.py` | Base class for providers |
| [`AbstractModel`](/lib/ai/abstract.py:47) | `abstract.py` | Base class for individual models |
| `BasicOpenAIProvider` | `providers/basic_openai_provider.py` | Base OpenAI-compatible API provider |
| `CustomOpenAIProvider` | `providers/custom_openai_provider.py` | OpenAI-compatible API provider (extends BasicOpenAIProvider) |
| `FastembedProvider` | `providers/fastembed_provider.py` | Fast embedding model provider |
| `OpenrouterProvider` | `providers/openrouter_provider.py` | OpenRouter.ai provider |
| `YcOpenaiProvider` | `providers/yc_openai_provider.py` | Yandex Cloud OpenAI-compatible |
| `YcAIProvider` | `providers/yc_sdk_provider.py` | Yandex Cloud native SDK (supports structured output, tool calling, multiple auth methods) |

**Usage example:**

```python
from lib.ai.manager import LLMManager
from lib.ai import ModelMessage, ModelResultStatus
from internal.services.llm import LLMService

llmManager = LLMManager(config={
    "providers": {
        "openrouter": {
            "type": "openrouter",
            "api-key": "sk-or-...",
        }
    },
    "models": {
        "my-model": {
            "provider": "openrouter",
            "model_id": "mistralai/mistral-7b-instruct",
            "customParams": {"temperature": 0.7},
            "context": 32768,
        }
    }
})

# After creating LLMManager, inject it into LLMService so handlers can access it:
LLMService.getInstance().injectLLMManager(llmManager)

model = llmManager.getModel("my-model")
messages = [
    ModelMessage(role="system", content="You are helpful"),
    ModelMessage(role="user", content="Hello!"),
]
result = await model.generateText(messages)

if result.status == ModelResultStatus.SUCCESS:
    print(result.resultText)
```

**Adding a new LLM provider:**

1. Create `lib/ai/providers/my_provider.py` implementing [`AbstractLLMProvider`](/lib/ai/abstract.py:904) and the model class extending [`AbstractModel`](/lib/ai/abstract.py:47)
2. Register it in [`LLMManager._initProviders()`](/lib/ai/manager.py:36) by adding it to `providerTypes`:

```python
providerTypes = {
    "yc-openai": YcOpenaiProvider,
    "openrouter": OpenrouterProvider,
    "my-provider": MyProvider,   # Add here
    ...
}
```

3. Configure in TOML:

```toml
[models.providers.my-provider]
type = "my-provider"
api-key = "${MY_PROVIDER_API_KEY}"
```

### 8.2 Cache System (`lib/cache/`)

A generic, type-safe cache library for any key-value storage need Not to be confused with `CacheService` (which is bot-specific), this is a general-purpose cache

**Key classes:**

| Class | File | Description |
|---|---|---|
| [`CacheInterface[K, V]`](/lib/cache/interface.py:15) | `interface.py` | Abstract base for all caches |
| `DictCache[K, V]` | `dict_cache.py` | In-memory dict-backed cache |
| `NullCache` | *(imported from lib.cache)* | No-op cache (caching disabled) |

**Usage example:**

```python
from lib.cache import DictCache
from lib.cache.key_generator import StringKeyGenerator

# Create a typed cache
cache: CacheInterface[str, dict] = DictCache[str, dict](
    keyGenerator=StringKeyGenerator(),
    defaultTtl=3600,    # 1 hour TTL
    maxSize=500,
)

# Store value
await cache.set("user:123", {"name": "Prinny", "level": 99})

# Retrieve value (None if expired or missing)
userData = await cache.get("user:123")

# Override TTL for specific get
userData = await cache.get("user:123", ttl=600)

# Get stats
stats = cache.getStats()
print(f"Entries: {stats['entries']}, Max: {stats['maxSize']}")

# Clear all
await cache.clear()
```

### 8.3 Rate Limiter (`lib/rate_limiter/`)

Sliding window rate limiter with a global singleton manager Used to limit API call rates for external services

**Key classes:**

| Class | File | Description |
|---|---|---|
| [`RateLimiterManager`](/lib/rate_limiter/manager.py:12) | `manager.py` | Singleton manager of named limiters |
| `SlidingWindowRateLimiter` | `sliding_window.py` | Sliding window implementation |
| `RateLimiterInterface` | `interface.py` | Abstract base class |

**Usage example:**

```python
from lib.rate_limiter import RateLimiterManager

# Get singleton
manager = RateLimiterManager.getInstance()

# Apply rate limit before making an API call (will sleep/wait if needed)
await manager.applyLimit("openweathermap")

# Get stats
stats = manager.getStats("openweathermap")
print(f"Requests in window: {stats['requestsInWindow']}/{stats['maxRequests']}")

# Queue-to-limiter bindings are configured via TOML [ratelimiter] section
```

### 8.4 Max Bot Client (`lib/max_bot/`)

An async HTTP client for the Max Messenger Bot API Analogous to `python-telegram-bot` but for Max Messenger

**Key classes:**

| Class | File | Description |
|---|---|---|
| [`MaxBotClient`](/lib/max_bot/client.py:75) | `client.py` | Main async client |
| `MaxBotError` | `exceptions.py` | Base exception class |
| `AuthenticationError` | `exceptions.py` | Auth failures |
| `RateLimitError` | `exceptions.py` | Rate limit hit |
| `AttachmentNotReadyError` | `exceptions.py` | Media not ready yet |

**Usage example:**

```python
from lib.max_bot import MaxBotClient

client = MaxBotClient(token="your-max-bot-token")

# Send a message
result = await client.sendMessage(
    chatId=123456,
    text="Hello from Gromozeka",
)

# Get bot info
botInfo = await client.getBotInfo()

# Get chat members
members = await client.getChatMembers(chatId=123456)

# Upload and send a photo
uploadResult = await client.uploadPhoto(photoBytes)
await client.sendMessage(
    chatId=123456,
    text="Look at this",
    attachments=[uploadResult.asAttachment()],
)
```

**Constants** from [`lib/max_bot/constants.py`](/lib/max_bot/constants.py):

```python
# Max API v2 (platform-api2.max.ru). Old endpoints kept as comments only:
#   - https://platform-api.max.ru  — original endpoint (deprecated)
#   - https://botapi.max.ru        — legacy endpoint
API_BASE_URL = "https://platform-api2.max.ru"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 5
RETRY_BACKOFF_FACTOR = 1.0
# platform-api2 enforces 30 rps (down from 100 on platform-api.max.ru)
DEFAULT_RATE_LIMIT = 30
```

### 8.5 OpenWeatherMap Client (`lib/openweathermap/`)

Async client for the OpenWeatherMap One Call API 3.0 with integrated caching and rate limiting

```python
from lib.openweathermap import OpenWeatherMapClient
from lib.cache import DictCache

weatherCache = DictCache(defaultTtl=3600)        # 1 hour
geocodingCache = DictCache(defaultTtl=2592000)   # 30 days

client = OpenWeatherMapClient(
    apiKey="your-api-key",
    weatherCache=weatherCache,
    geocodingCache=geocodingCache,
    requestTimeout=10,
    defaultLanguage="ru",
    rateLimiterQueue="openweathermap",   # Must match a ratelimiter queue name
)

# Get coordinates for a city
location = await client.getCoordinates("Moscow", "RU")

# Get current weather by coordinates
weather = await client.getWeather(lat=55.7558, lon=37.6173)

# Combined: city name -> weather (with geocoding cache)
result = await client.getWeatherByCity("Moscow", "RU")
print(f"Temperature: {result.current.temp}°C")
print(f"Description: {result.current.weather[0].description}")
```

### 8.6 Yandex Search Client

Provides web search via Yandex Search API. Configured with `[yandex-search]` in TOML. Used by `YandexSearchHandler`

### 8.7 Geocode Maps Client (`lib/geocode_maps/`)

Async client for the Geocode Maps API (geocode.maps.co) with forward/reverse geocoding and OSM lookup

```python
from lib.geocode_maps import GeocodeMapsClient
from lib.cache import DictCache

client = GeocodeMapsClient(
    apiKey="your-api-key",
    searchCache=DictCache(defaultTtl=2592000),
    reverseCache=DictCache(defaultTtl=2592000),
    lookupCache=DictCache(defaultTtl=2592000),
    acceptLanguage="ru",
    rateLimiterQueue="geocode-maps",
)

# Forward geocoding (address -> coordinates)
results = await client.search("Angarsk, Russia")
if results:
    print(f"Lat: {results[0].lat}, Lon: {results[0].lon}")

# Reverse geocoding (coordinates -> address)
location = await client.reverse(lat=52.5443, lon=103.8882)

# OSM ID lookup
places = await client.lookup(["R2623018"])
```

### 8.8 Bayes Filter (Spam Detection)

The Naive Bayes spam filter lives in the database layer at [`internal/database/bayes_storage.py`](/internal/database/bayes_storage.py) and is used by `SpamHandler`

**How it works:**
1. Every message is scored against the trained Bayes model
2. If the spam score exceeds `spam-ban-treshold` (default: 90), the user is banned and messages deleted
3. If it exceeds `spam-warn-treshold` (default: 60), a warning is added
4. New users (fewer than `auto-spam-max-messages` messages) are always checked
5. The filter auto-learns from confirmed spam/ham decisions

**Relevant config keys in `[bot.defaults]`:**

```toml
detect-spam = true
bayes-enabled = true
bayes-auto-learn = true
bayes-min-confidence = 0.5
bayes-use-trigrams = false
bayes-min-confedence-to-autolearn-spam = 0.6
bayes-min-confedence-to-autolearn-ham = 0.9
spam-ban-treshold = 90
spam-warn-treshold = 60
auto-spam-max-messages = 10
spam-delete-all-user-messages = true
```

### 8.9 Markdown Parser (`lib/markdown/`)

A custom Markdown parser that converts standard Markdown to Telegram's MarkdownV2 format (and optionally HTML) This is necessary because Telegram MarkdownV2 has many edge cases that LLM outputs often violate

**Pipeline stages:**

1. `Tokenizer` — splits input into tokens
2. `BlockParser` — identifies block-level elements (headers, lists, code blocks)
3. `InlineParser` — processes inline elements (bold, italic, links)
4. `Renderer` — converts the AST to target format

**Usage:**

```python
from lib.markdown.parser import markdownToMarkdownV2, MarkdownParser

# Quick conversion for bot messages (most common use case)
mdv2Text = markdownToMarkdownV2("**Hello** from _Gromozeka_")

# More control with the parser directly
parser = MarkdownParser(options={
    "preserve_soft_line_breaks": False,
    "ignore_indented_code_blocks": True,
})
mdv2 = parser.toMarkdownV2("# Header\n\n**Bold** text")
html = parser.toHTML("# Header\n\n**Bold** text")
```

### 8.10 Sandboxed Code Execution (`lib/sandbox/`)

Safely execute untrusted Python code in Docker containers. Provides a `SandboxManager` singleton that manages sessions, runs, files, libraries, and garbage collection.

**Key classes:**

| Class | File | Description |
|---|---|---|
| `SandboxManager` | `lib/sandbox/manager.py` | Singleton entry point — sessions, runs, files, libraries, GC, health |
| `SandboxConfig` | `lib/sandbox/config.py` | Top-level configuration dataclass |
| `StorageConfig` | `lib/sandbox/config.py` | Storage paths and permissions |
| `BackendConfig` | `lib/sandbox/config.py` | Backend selection and settings |
| `SecurityConfig` | `lib/sandbox/config.py` | Container security constraints |
| `ConcurrencyConfig` | `lib/sandbox/config.py` | Global and per-session concurrency limits |
| `GcConfig` | `lib/sandbox/config.py` | GC schedule and retention policies |
| `BasicRuntimeConfig` | `lib/sandbox/config.py` | Python runtime configuration |
| `RunResult` | `lib/sandbox/types.py` | Result of a code execution run |
| `SessionInfo` | `lib/sandbox/types.py` | Session metadata |
| `ResourceLimits` | `lib/sandbox/types.py` | Container resource limits |

**Usage example:**

```python
from lib.sandbox import SandboxManager, SandboxConfig, StorageConfig

config = SandboxConfig(storage=StorageConfig(rootDir="/var/lib/gromozeka/sandbox"))
SandboxManager.injectConfig(config)
manager = SandboxManager.getInstance()

# Create a session and run code
session = await manager.createSession("my-session")
result = await manager.runCode(session.sessionId, "print(2 + 2)")
print(result.exitCode, result.stdout)  # 0, "4\n"

# Install a library
await manager.installLibrary(session.sessionId, "numpy")

# Clean up
await manager.shutdown()
```

**Configuration:** Defaults in [`configs/00-defaults/sandbox.toml`](/configs/00-defaults/sandbox.toml). See [Section 13 - Bootstrapping the Sandbox](operations.md#13-bootstrapping-the-sandbox) for setup instructions.

---

### 14.2 Adding a New API Integration

Let's say you want to integrate the "CoolAPI" service

**Step 1**: Create the library module

```
lib/
└── coolapi/
    ├── __init__.py
    ├── client.py       # CoolApiClient class
    ├── models.py       # Response data models
    └── README.md       # Document the integration
```

**Step 2**: Implement the client following the established pattern

```python
# lib/coolapi/client.py
"""CoolAPI async client with caching and rate limiting"""

import logging
from typing import Optional

import httpx2 as httpx

from lib.cache import CacheInterface, NullCache
from lib.rate_limiter import RateLimiterManager

from .models import CoolApiResponse

logger = logging.getLogger(__name__)


class CoolApiClient:
    """Async client for CoolAPI

    Args:
        apiKey: API authentication key
        cache: Optional cache for responses
        cacheTtl: Cache TTL in seconds (default: 3600)
        requestTimeout: HTTP timeout in seconds (default: 10)
        rateLimiterQueue: Rate limiter queue name
    """

    API_BASE: str = "https://api.coolservice.example.com/v1"

    def __init__(
        self,
        apiKey: str,
        cache: Optional[CacheInterface] = None,
        cacheTtl: Optional[int] = 3600,
        requestTimeout: int = 10,
        rateLimiterQueue: str = "coolapi",
    ) -> None:
        """Initialize CoolAPI client

        Args:
            apiKey: API authentication key
            cache: Optional cache implementation
            cacheTtl: Cache TTL in seconds
            requestTimeout: HTTP request timeout in seconds
            rateLimiterQueue: Rate limiter queue to use
        """
        self.apiKey = apiKey
        self.cache = cache or NullCache()
        self.cacheTtl = cacheTtl
        self.requestTimeout = requestTimeout
        self.rateLimiterQueue = rateLimiterQueue
        self._rateLimiter = RateLimiterManager.getInstance()

    async def getData(self, query: str) -> Optional[CoolApiResponse]:
        """Fetch data from CoolAPI

        Args:
            query: Search query string

        Returns:
            CoolApiResponse if successful, None on error
        """
        cacheKey: str = f"coolapi:{query}"
        cached = await self.cache.get(cacheKey, ttl=self.cacheTtl)
        if cached is not None:
            return cached

        await self._rateLimiter.applyLimit(self.rateLimiterQueue)

        async with httpx.AsyncClient(timeout=self.requestTimeout) as client:
            response = await client.get(
                f"{self.API_BASE}/data",
                params={"q": query, "key": self.apiKey},
            )
            response.raise_for_status()
            data = CoolApiResponse(**response.json())

        await self.cache.set(cacheKey, data)
        return data
```

**Step 3**: Add a config section in `configs/00-defaults/00-config.toml`

```toml
[coolapi]
enabled = false
api-key = "${COOLAPI_KEY}"
cache-ttl = 3600
request-timeout = 10
ratelimiter-queue = "coolapi"
```

**Step 4**: Add a rate limiter queue

```toml
[ratelimiter.ratelimiters.coolapi]
type = "SlidingWindow"
[ratelimiter.ratelimiters.coolapi.config]
windowSeconds = 60
maxRequests = 30

[ratelimiter.queues]
coolapi = "coolapi"
```

**Step 5**: Add a `getCoolApiConfig()` method to [`ConfigManager`](/internal/config/manager.py:59).

**Step 6**: Create a handler that uses the client and register it in [`HandlersManager`](/internal/bot/common/handlers/manager.py:382).

**Step 7**: Write tests using the golden data fixture pattern

### 14.3 Adding a New LLM Provider

**Step 1**: Create the provider file

```python
# lib/ai/providers/my_provider.py
"""My LLM provider implementation"""

from typing import Any, Dict, Optional, Sequence

from lib.ai.abstract import AbstractLLMProvider, AbstractModel
from lib.ai.models import LLMAbstractTool, ModelMessage, ModelResultStatus, ModelRunResult
from lib.stats import StatsStorage


class MyProviderModel(AbstractModel):
    """A model served by MyProvider

    Args:
        provider: The parent provider instance
        modelId: Unique model identifier
        modelVersion: Model version string
        contextSize: Max context tokens
        extraConfig: Additional configuration dict
        customParams: Per-model custom parameters passed through to the
            underlying API call (temperature, top_p, max_tokens, ...).
            Defaults to an empty dict.
    """

    def __init__(
        self,
        provider: "MyProvider",
        modelId: str,
        *,
        modelVersion: str,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Optional[Dict[str, Any]] = None,
        customParams: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the model"""
        super().__init__(
            provider,
            modelId,
            modelVersion=modelVersion,
            contextSize=contextSize,
            statsStorage=statsStorage,
            extraConfig=extraConfig,
            customParams=customParams,
        )

    async def _generateText(
        self,
        messages: Sequence[ModelMessage],
        tools: Optional[Sequence[LLMAbstractTool]] = None,
    ) -> ModelRunResult:
        """Generate text using MyProvider API

        Args:
            messages: Input message sequence
            tools: Optional tool definitions

        Returns:
            ModelRunResult with text and status
        """
        # TODO: Implement actual API call here
        raise NotImplementedError("Implement me")

    async def generateImage(self, messages: Sequence[ModelMessage]) -> ModelRunResult:
        """Generate image (not supported by this provider)

        Args:
            messages: Input message sequence

        Returns:
            ModelRunResult with ERROR status
        """
        return ModelRunResult(
            rawResult=None,
            status=ModelResultStatus.ERROR,
            error=NotImplementedError("Image generation not supported by MyProvider"),
        )


class MyProvider(AbstractLLMProvider):
    """Provider for MyLLM service

    Args:
        config: Provider configuration dict with api-key and optional base-url
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize provider with config

        Args:
            config: Configuration dict (must contain 'api-key')
        """
        super().__init__(config)
        self.apiKey: str = config["api-key"]
        self.baseUrl: str = config.get("base-url", "https://api.myllm.example.com")

    def addModel(
        self,
        name: str,
        modelId: str,
        *,
        modelVersion: str,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Optional[Dict[str, Any]] = None,
        customParams: Optional[Dict[str, Any]] = None,
    ) -> AbstractModel:
        """Add a model to this provider

        Args:
            name: Human-readable model name for registry
            modelId: Provider-specific model ID
            modelVersion: Model version string
            contextSize: Maximum context token count
            statsStorage: StatsStorage instance for recording LLM usage statistics
            extraConfig: Additional model configuration
            customParams: Per-model custom parameters forwarded to the
                underlying API call (temperature, top_p, max_tokens, ...).

        Returns:
            Newly created model instance
        """
        model = MyProviderModel(
            self,
            modelId,
            modelVersion=modelVersion,
            contextSize=contextSize,
            statsStorage=statsStorage,
            extraConfig=extraConfig,
            customParams=customParams,
        )
        self.models[name] = model
        return model
```

#### Registering the Provider in LLMManager

**Step 2**: Register in [`LLMManager._initProviders()`](/lib/ai/manager.py:36)

```python
# In lib/ai/manager.py, add import:
from .providers.my_provider import MyProvider

# In _initProviders(), add to providerTypes dict:
providerTypes = {
    "yc-openai": YcOpenaiProvider,
    "openrouter": OpenrouterProvider,
    "yc-sdk": YcAIProvider,
    "custom-openai": CustomOpenAIProvider,
    "my-provider": MyProvider,    # Add here
}
```

#### Configuring the Provider in TOML

**Step 3**: Configure in TOML

```toml
[models.providers.my-llm]
type = "my-provider"
api-key = "${MY_LLM_API_KEY}"
base-url = "https://api.myllm.example.com"

[models.models.my-model]
provider = "my-llm"
model_id = "myllm-v1"
model_version = "latest"
customParams.temperature = 0.5
context = 16384
enabled = true
support_images = false
support_tools = false
tier = "free"
```
