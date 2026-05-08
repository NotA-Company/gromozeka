# Gromozeka LLM Agent Guide — Index & Quick Reference

> **Audience:** LLM agents (Roo, Cline, GitHub Copilot, Cursor, etc.)  
> **Purpose:** Entry point and quick reference for navigating the Gromozeka project  
> **NOT for humans** — use [`docs/developer-guide.md`](../developer-guide.md) for human-friendly docs

---

## Navigation — Which Doc Should I Read?

| If you need to... | Read this doc |
|---|---|
| Understand project overview, commands, mandatory rules | **This file** (`index.md`) |
| Understand architecture, ADRs, design decisions | [`architecture.md`](architecture.md) |
| Create or modify a bot command handler | [`handlers.md`](handlers.md) |
| Add/modify database tables, migrations, or queries | [`database.md`](database.md) |
| Use Cache, Queue, LLM, Storage, or RateLimiter services | [`services.md`](services.md) |
| Use lib/ai, lib/cache, lib/markdown, lib/max_bot, etc. | [`libraries.md`](libraries.md) |
| Add or change TOML configuration | [`configuration.md`](configuration.md) |
| Write or run tests, understand test fixtures | [`testing.md`](testing.md) |
| Follow a step-by-step task workflow or avoid pitfalls | [`tasks.md`](tasks.md) |

---

## 1. Project Identity

| Field | Value |
|---|---|
| Project name | Gromozeka |
| Type | Multi-platform AI bot (Telegram + Max Messenger) |
| Python | 3.12+ |
| Architecture | Modular, async, singleton services |
| Test count | 1185+ |
| Status | Production-ready, active development |

### Key Features

- Multi-platform bot support (Telegram and Max Messenger)
- Advanced LLM integration with multiple providers (YC SDK, OpenAI-compatible, OpenRouter)
- Comprehensive API integrations (Weather, Search, Geocoding)
- ML-powered spam detection with Bayes filter
- Golden data testing framework for reliable API testing
- Service layer with cache and queue services
- Multi-source database routing with SQLite

---

## 2. Critical Commands

```bash
# ALWAYS run before AND after changes
make format lint

# Run AFTER any change
make test

# Run bot from project root ONLY (never cd into subdirs)
./venv/bin/python3 main.py --config-dir configs/

# Run single test file
./venv/bin/pytest tests/test_db_wrapper.py -v
```

---

## 3. Mandatory Rules

### 3.1 Naming Conventions (MUST follow)

| Entity | Convention | Example |
|---|---|---|
| Variables | camelCase | `chatId`, `messageText` |
| Arguments | camelCase | `configManager`, `botProvider` |
| Class fields | camelCase | `self.llmManager`, `self.db` |
| Functions | camelCase | `getChatSettings()`, `sendMessage()` |
| Methods | camelCase | `newMessageHandler()`, `getBotId()` |
| Classes | PascalCase | `BaseBotHandler`, `CacheService` |
| Constants | UPPER_CASE | `DEFAULT_THREAD_ID`, `MIGRATION_VERSION_KEY` |

**Source:** [`.roo/rules/camelCase.md`](../../.roo/rules/camelCase.md)

### 3.2 Docstrings (MUST have)

- Every module, class, method, field, and function MUST have a docstring
- Docstrings MUST be concise but describe all arguments and return type
- Use Google-style docstrings with `Args:` and `Returns:` sections

**Example (correct):**
```python
def getChatSettings(self, chatId: Optional[int], *, returnDefault: bool = True) -> ChatSettingsDict:
    """Get merged chat settings with tier-aware filtering

    Args:
        chatId: Chat ID to retrieve settings for, or None for defaults only
        returnDefault: If True, merge per-chat settings with global defaults

    Returns:
        Dictionary mapping ChatSettingsKey to ChatSettingsValue
    """
```

**Source:** [`.roo/rules/doctrings.md`](../../.roo/rules/doctrings.md)

### 3.3 Type Hints (MUST have)

- ALWAYS write type hints for function/method arguments
- ALWAYS write type hints for returned values
- Write type hints for local variables when type is not obvious

```python
# CORRECT
def parseCommand(self, ensuredMessage: EnsuredMessage) -> Optional[Tuple[str, str]]:
    commandText: str = ensuredMessage.messageText.strip()
    ...

# WRONG - no type hints
def parseCommand(self, ensuredMessage):
    ...
```

### 3.4 Python Runtime (MUST follow)

- Use `./venv/bin/python3` to run Python — NOT `python` or `python3`
- Do NOT `cd` into subdirectories — run all scripts from project root
- Do NOT use `python -c ...` for one-time tests — create a test script file instead

```bash
# CORRECT
./venv/bin/python3 main.py

# WRONG
python main.py
cd internal && python test.py
```

### 3.5 Code Quality Workflow (MUST run)

```bash
# Step 1 - Before making changes
make format lint

# Step 2 - After making changes
make format lint

# Step 3 - Final verification
make test
```

**Linting tools:** Black (120 chars), Flake8, Pyright, isort  
**Config:** [`pyproject.toml`](../../pyproject.toml)

---

## 4. Project Map

### 4.1 Root Structure

| Path | Purpose |
|---|---|
| [`main.py`](../../main.py) | Application entry point |
| [`Makefile`](../../Makefile) | Build, format, lint, test commands |
| [`pyproject.toml`](../../pyproject.toml) | Black, Flake8, Pyright, isort, pytest config |
| `requirements.txt` | Python dependencies |
| `configs/` | Configuration directory (TOML files) |
| `internal/` | Internal application code |
| `lib/` | Reusable library code |
| `tests/` | Integration test suite |
| `docs/` | Documentation |

### 4.2 Entry Points

| File | Class/Function | Line | Purpose |
|---|---|---|---|
| [`main.py`](../../main.py:31) | [`GromozekBot`](../../main.py:31) | 31 | Top-level orchestrator |
| [`main.py`](../../main.py:202) | [`main()`](../../main.py:202) | 202 | CLI entry point |
| [`internal/bot/telegram/application.py`](../../internal/bot/telegram/application.py) | `TelegramBotApplication` | — | Telegram runner |
| [`internal/bot/max/application.py`](../../internal/bot/max/application.py) | `MaxBotApplication` | — | Max Messenger runner |

### 4.3 Key Singleton Services (import + get instance)

| Service | Import | `getInstance()` call |
|---|---|---|
| [`CacheService`](../../internal/services/cache/service.py:88) | `from internal.services.cache import CacheService` | `CacheService.getInstance()` |
| [`QueueService`](../../internal/services/queue_service/service.py:49) | `from internal.services.queue_service import QueueService` | `QueueService.getInstance()` |
| [`LLMService`](../../internal/services/llm/service.py:37) | `from internal.services.llm import LLMService` | `LLMService.getInstance()` |
| [`StorageService`](../../internal/services/storage/service.py:24) | `from internal.services.storage import StorageService` | `StorageService.getInstance()` |
| [`RateLimiterManager`](../../lib/rate_limiter/manager.py:12) | `from lib.rate_limiter import RateLimiterManager` | `RateLimiterManager.getInstance()` |

### 4.4 Critical File Paths (with approximate line counts)

| Path | Lines | Purpose |
|---|---|---|
| [`main.py`](../../main.py) | 241 | App entry, `GromozekBot`, daemon mode |
| [`internal/bot/common/bot.py`](../../internal/bot/common/bot.py) | 1000 | `TheBot` – platform-agnostic bot ops |
| [`internal/bot/common/handlers/base.py`](../../internal/bot/common/handlers/base.py) | 1974 | `BaseBotHandler`, `HandlerResultStatus` |
| [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py) | 1148 | `HandlersManager` – handler chain |
| [`internal/database/database.py`](../../internal/database/database.py) | 297 | `Database` – all DB operations with repository pattern |
| [`internal/config/manager.py`](../../internal/config/manager.py) | 280 | `ConfigManager` – TOML loading |
| [`internal/services/cache/service.py`](../../internal/services/cache/service.py) | 796 | `CacheService` singleton |
| [`internal/services/llm/service.py`](../../internal/services/llm/service.py) | 531 | `LLMService` singleton |
| [`internal/services/queue_service/service.py`](../../internal/services/queue_service/service.py) | 447 | `QueueService` singleton |
| [`internal/services/storage/service.py`](../../internal/services/storage/service.py) | 304 | `StorageService` singleton |
| [`lib/ai/abstract.py`](../../lib/ai/abstract.py) | 341 | `AbstractModel`, `AbstractLLMProvider` |
| [`lib/ai/manager.py`](../../lib/ai/manager.py) | 162 | `LLMManager` – provider + model registry |

### 4.5 `internal/` Directory

 | Path | Purpose |
|---|---|
| [`internal/bot/common/bot.py`](../../internal/bot/common/bot.py) | `TheBot` — platform-agnostic bot API |
| [`internal/bot/common/handlers/`](../../internal/bot/common/handlers/) | All 21+ handler implementations (incl. `DivinationHandler` for `/taro` & `/runes`, plus base/manager/module_loader, tests, examples, and 15+ handlers) |
| [`internal/bot/common/handlers/base.py`](../../internal/bot/common/handlers/base.py) | `BaseBotHandler` — handler base class |
| [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py) | `HandlersManager` — handler chain |
| [`internal/bot/telegram/application.py`](../../internal/bot/telegram/application.py) | Telegram-specific bot application |
| [`internal/bot/max/application.py`](../../internal/bot/max/application.py) | Max Messenger bot application |
| [`internal/bot/models/`](../../internal/bot/models/) | Bot model types (EnsuredMessage, ChatSettings, etc.) |
| [`internal/config/manager.py`](../../internal/config/manager.py) | `ConfigManager` — TOML config loading |
| [`internal/database/database.py`](../../internal/database/database.py) | `Database` — all DB operations with repository pattern (297 lines) |
| [`internal/database/migrations/`](../../internal/database/migrations/) | `MigrationManager`, `BaseMigration`, version files |
| [`internal/models.py`](../../internal/models.py) | Shared type aliases (`MessageIdType`, `MessageType`) |
| [`internal/services/cache/service.py`](../../internal/services/cache/service.py) | `CacheService` singleton |
| [`internal/services/llm/service.py`](../../internal/services/llm/service.py) | `LLMService` singleton |
| [`internal/services/queue_service/service.py`](../../internal/services/queue_service/service.py) | `QueueService` singleton |
| [`internal/services/storage/service.py`](../../internal/services/storage/service.py) | `StorageService` singleton |

### 4.6 `lib/` Directory

| Path | Purpose |
|---|---|
| [`lib/ai/abstract.py`](../../lib/ai/abstract.py) | `AbstractModel`, `AbstractLLMProvider` |
| [`lib/ai/manager.py`](../../lib/ai/manager.py) | `LLMManager` — model + provider registry |
| [`lib/ai/models.py`](../../lib/ai/models.py) | `ModelMessage`, `ModelRunResult`, `LLMToolFunction`, etc. |
| [`lib/ai/providers/`](../../lib/ai/providers/) | Provider implementations (OpenAI, OpenRouter, YC) |
| [`lib/cache/interface.py`](../../lib/cache/interface.py) | `CacheInterface[K,V]` — generic cache ABC |
| [`lib/cache/dict_cache.py`](../../lib/cache/dict_cache.py) | In-memory dict-based cache impl |
| [`lib/rate_limiter/interface.py`](../../lib/rate_limiter/interface.py) | `RateLimiterInterface` — ABC |
| [`lib/rate_limiter/manager.py`](../../lib/rate_limiter/manager.py) | `RateLimiterManager` singleton |
| [`lib/rate_limiter/sliding_window.py`](../../lib/rate_limiter/sliding_window.py) | `SlidingWindowRateLimiter` impl |
| [`lib/bayes_filter/bayes_filter.py`](../../lib/bayes_filter/bayes_filter.py) | Naive Bayes spam filter |
| [`lib/markdown/parser.py`](../../lib/markdown/parser.py) | Markdown → MarkdownV2 parser |
| [`lib/max_bot/client.py`](../../lib/max_bot/client.py) | Max Messenger HTTP client |
| [`lib/openweathermap/client.py`](../../lib/openweathermap/client.py) | OpenWeatherMap API client |
| [`lib/yandex_search/`](../../lib/yandex_search/) | Yandex Search API client |
| [`lib/geocode_maps/client.py`](../../lib/geocode_maps/client.py) | Geocode Maps API client |
| [`lib/ext_modules/`](../../lib/ext_modules/) | External custom modules (Grabliarium etc.) |
| [`lib/divination/`](../../lib/divination/) | Tarot & runes pure-logic library (decks, layouts, drawing); used by `DivinationHandler` |
| [`lib/logging_utils.py`](../../lib/logging_utils.py) | `initLogging()` helper |

---

## See Also

- [`architecture.md`](architecture.md) — ADRs, component dependencies, design patterns
- [`handlers.md`](handlers.md) — Handler system, creation checklist, command decorators
- [`database.md`](database.md) — DB operations, migrations, schema, multi-source routing
- [`services.md`](services.md) — CacheService, QueueService, LLMService, StorageService, RateLimiter
- [`libraries.md`](libraries.md) — lib/ai, lib/cache, lib/markdown, lib/max_bot and more
- [`configuration.md`](configuration.md) — TOML config sections, ConfigManager methods
- [`testing.md`](testing.md) — Test fixtures, pytest patterns, golden data framework
- [`tasks.md`](tasks.md) — Step-by-step task workflows, anti-patterns

---

*This guide is auto-maintained and should be updated whenever significant architectural changes are made*  
*Last updated: 2026-05-06*
