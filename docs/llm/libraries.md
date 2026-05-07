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
9. [lib/divination — Tarot & Runes Logic](#9-libdivination--tarot--runes-logic)

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
| [`LLMManager`](../../lib/ai/manager.py:17) | `lib/ai/manager.py` | Registry for providers and models |
| [`AbstractModel`](../../lib/ai/abstract.py:19) | `lib/ai/abstract.py` | ABC for all LLM models |
| [`AbstractLLMProvider`](../../lib/ai/abstract.py) | `lib/ai/abstract.py` | ABC for LLM providers |
| [`ModelMessage`](../../lib/ai/models.py) | `lib/ai/models.py` | Standard text message for LLM |
| [`ModelImageMessage`](../../lib/ai/models.py) | `lib/ai/models.py` | Message with embedded image |
| [`ModelRunResult`](../../lib/ai/models.py) | `lib/ai/models.py` | LLM response container |
| [`ModelStructuredResult`](../../lib/ai/models.py) | `lib/ai/models.py` | Structured-output result; adds `data: Optional[Dict]` |
| [`ModelResultStatus`](../../lib/ai/models.py) | `lib/ai/models.py` | `FINAL`, `ERROR`, `TIMEOUT`, etc. |
| [`LLMToolFunction`](../../lib/ai/models.py:64) | `lib/ai/models.py` | Tool/function definition for LLM |
| [`LLMFunctionParameter`](../../lib/ai/models.py:37) | `lib/ai/models.py` | Tool parameter definition |
| [`LLMParameterType`](../../lib/ai/models.py:27) | `lib/ai/models.py` | `STRING`, `NUMBER`, `BOOLEAN`, `ARRAY`, `OBJECT` |

**Key methods on `AbstractModel`:**
```python
model.generateText(messages: Sequence[ModelMessage], tools=None) -> ModelRunResult
model.generateStructured(
    messages: Sequence[ModelMessage],
    schema: Dict[str, Any],
    *, schemaName: str = "response",
    strict: bool = True,
) -> ModelStructuredResult
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
(`custom-openai`, `openrouter`, `yc-openai`). The `yc-sdk` provider
overrides `_generateStructured` to raise `NotImplementedError` — see
[`docs/plans/lib-ai-structured-output.md`](../plans/lib-ai-structured-output.md) §3.6.

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

**Import:**
```python
from lib.ai import ModelStructuredResult
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

**NOTE:** For bot cache operations (chat settings, user data, admin cache), use [`CacheService`](services.md) instead of `lib/cache` directly

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

**Tests:** `lib/markdown/test/` — run with `make test`

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

**Tests:** Uses golden data framework in `lib/openweathermap/test_weather_client.py`

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

---

## 9. `lib/divination` — Tarot & Runes Logic

Pure-logic library for tarot and rune divination. Depends ONLY on `lib/ai` (no bot, no DB)

**Layout:**

| Path | Purpose |
|---|---|
| [`lib/divination/base.py`](../../lib/divination/base.py) | `BaseDivinationSystem` ABC plus `Symbol`, `DrawnSymbol`, `Reading` dataclasses |
| [`lib/divination/layouts.py`](../../lib/divination/layouts.py) | `Layout` dataclass, `TAROT_LAYOUTS`, `RUNE_LAYOUTS`, `resolveLayout()` |
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

## See Also

- [`index.md`](index.md) — Project overview, lib/ directory map
- [`services.md`](services.md) — Higher-level service wrappers (CacheService, LLMService, etc.)
- [`configuration.md`](configuration.md) — Configuring lib integrations via TOML
- [`testing.md`](testing.md) — Golden data framework for API testing
- [`tasks.md`](tasks.md) — Step-by-step: "add new API integration" decision tree

---

*This guide is auto-maintained and should be updated whenever library APIs change*  
*Last updated: 2026-05-06*
