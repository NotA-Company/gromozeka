# Gromozeka — Library API Quick Reference

> **Audience:** LLM agents, dood!  
> **Purpose:** Complete API reference for all lib/ subsystems, dood!  
> **Self-contained:** Everything needed for library usage is here, dood!

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

---

## 1. `lib/ai` — LLM Abstraction

**Import paths:**
```python
from lib.ai import LLMManager, AbstractModel, ModelMessage, ModelResultStatus
from lib.ai.models import (
    ModelMessage,
    ModelImageMessage,
    ModelRunResult,
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
| [`LLMManager`](../../lib/ai/manager.py:17) | `lib/ai/manager.py` | Registry for providers and models |
| [`AbstractModel`](../../lib/ai/abstract.py:19) | `lib/ai/abstract.py` | ABC for all LLM models |
| [`AbstractLLMProvider`](../../lib/ai/abstract.py) | `lib/ai/abstract.py` | ABC for LLM providers |
| [`ModelMessage`](../../lib/ai/models.py) | `lib/ai/models.py` | Standard text message for LLM |
| [`ModelImageMessage`](../../lib/ai/models.py) | `lib/ai/models.py` | Message with embedded image |
| [`ModelRunResult`](../../lib/ai/models.py) | `lib/ai/models.py` | LLM response container |
| [`ModelResultStatus`](../../lib/ai/models.py) | `lib/ai/models.py` | `FINAL`, `ERROR`, `TIMEOUT`, etc. |
| [`LLMToolFunction`](../../lib/ai/models.py:64) | `lib/ai/models.py` | Tool/function definition for LLM |
| [`LLMFunctionParameter`](../../lib/ai/models.py:37) | `lib/ai/models.py` | Tool parameter definition |
| [`LLMParameterType`](../../lib/ai/models.py:27) | `lib/ai/models.py` | `STRING`, `NUMBER`, `BOOLEAN`, `ARRAY`, `OBJECT` |

**Key methods on `AbstractModel`:**
```python
model.generateText(messages: Sequence[ModelMessage], tools=None) -> ModelRunResult
model.getEstimateTokensCount(messages: list) -> int
model.contextSize  # int
model.temperature  # float
model.modelId      # str
```

**Key methods on `LLMManager`:**
```python
manager.getModelInfo(modelName: str) -> Optional[Dict[str, Any]]
manager.getModel(modelName: str) -> Optional[AbstractModel]
manager.listModels() -> List[str]
```

**Creating a message:**
```python
# Text message
msg = ModelMessage(role="user", content="Hello, dood!")
msg = ModelMessage(role="system", content="You are helpful")
msg = ModelMessage(role="assistant", content="Response text")

# Image message
imgMsg = ModelImageMessage(
    role="user",
    content="Describe this image",
    image=bytearray(imageData),
)
```

**Adding a new LLM provider:**

1. Create `lib/ai/providers/my_provider.py`
2. Class: `MyProvider(AbstractLLMProvider)`
3. Must implement: `_createModel(modelConfig) -> AbstractModel`
4. Register in `lib/ai/manager.py:40` — add to `providerTypes` dict: `{"my-provider": MyProvider}`
5. Tests in `lib/ai/providers/test_my_provider.py`

---

## 2. `lib/cache` — Generic Cache Interface

**Import:**
```python
from lib.cache import CacheInterface, DictCache
from lib.cache.key_generator import StringKeyGenerator
```

**Key classes:**

| Class | File | Purpose |
|---|---|---|
| [`CacheInterface[K,V]`](../../lib/cache/interface.py:15) | `lib/cache/interface.py` | Generic ABC for any cache |
| `DictCache[K,V]` | `lib/cache/dict_cache.py` | In-memory dict implementation |
| `StringKeyGenerator` | `lib/cache/key_generator.py` | Simple string key gen |

**Interface methods:**
```python
await cache.get(key: K, ttl: Optional[int] = None) -> Optional[V]
await cache.set(key: K, value: V) -> bool
await cache.clear() -> None
cache.getStats() -> Dict[str, Any]
```

**NOTE:** For bot cache operations (chat settings, user data, admin cache), use [`CacheService`](services.md) instead of `lib/cache` directly, dood!

---

## 3. `lib/rate_limiter` — Rate Limiting

**Import:**
```python
from lib.rate_limiter import RateLimiterManager, RateLimiterInterface, SlidingWindowRateLimiter
```

**Interface methods** ([`RateLimiterInterface`](../../lib/rate_limiter/interface.py:5)):
```python
await limiter.initialize() -> None
await limiter.destroy() -> None
await limiter.applyLimit(queue: str = "default") -> None
limiter.getStats(queue: str = "default") -> Dict[str, Any]
limiter.listQueues() -> List[str]
```

**For bot usage, use** [`RateLimiterManager`](services.md#5-ratelimitermanager) **from services, dood!**

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

**Tests:** `lib/markdown/test/` — run with `make test`, dood!

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
Animated stickers have stub URLs, not real images. Always check `url.startswith(...)` before processing, dood!

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

**Multi-source database support:** `BayesFilter` supports `dataSource` parameter for multi-source routing, dood!

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

**Tests:** Uses golden data framework in `lib/openweathermap/test_weather_client.py`, dood!

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

**Config:** Configured via `[geocode-maps]` TOML section, accessed via `configManager.getGeocodeMapsConfig()`, dood!

---

## See Also

- [`index.md`](index.md) — Project overview, lib/ directory map
- [`services.md`](services.md) — Higher-level service wrappers (CacheService, LLMService, etc.)
- [`configuration.md`](configuration.md) — Configuring lib integrations via TOML
- [`testing.md`](testing.md) — Golden data framework for API testing
- [`tasks.md`](tasks.md) — Step-by-step: "add new API integration" decision tree

---

*This guide is auto-maintained and should be updated whenever library APIs change, dood!*  
*Last updated: 2026-04-18, dood!*
