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
| Use or modify the sandbox library | [`sandbox.md`](sandbox.md) |
| Add or change TOML configuration | [`configuration.md`](configuration.md) |
| Write or run tests, understand test fixtures | [`testing.md`](testing.md) |
| Maintain or extend the golden-data record/replay library (`lib/aurumentation`) | [`aurumentation.md`](aurumentation.md) |
| Follow a step-by-step task workflow or avoid pitfalls | [`tasks.md`](tasks.md) |
| Maintain `CHANGELOG.md` (when to update, entry style, semver) | [`changelog.md`](changelog.md) |
| Reuse durable cross-task memory and repo gotchas | [`teamlead-memory.md`](teamlead-memory.md) |
| Review large diffs that exceed single-pass agent budget | [`reviewing-large-changes.md`](reviewing-large-changes.md) |
| Reuse archived task-specific memories for completed subsystems | [`memories/index.md`](memories/index.md) |

---

## 1. Project Identity

| Field | Value |
|---|---|
| Project name | Gromozeka |
| Type | Multi-platform AI bot (Telegram + Max Messenger) |
| Python | 3.12+ |
| Architecture | Modular, async, singleton services |
| Test count | ~3737 (as of 2026-08-08; verify with `./venv/bin/pytest --collect-only -q`) |
| Status | Production-ready, active development |

### Key Features

- Multi-platform bot support (Telegram and Max Messenger)
- Max Messenger webhook mode: standalone aiohttp webhook-receiver process that buffers Max webhook POSTs in `webhook_updates` and serves them back to the bot via a local GET /updates endpoint (two-process local-API-proxy pattern; see [`architecture.md`](architecture.md) ADR-013)
- Advanced LLM integration with multiple providers (YC SDK, OpenAI-compatible, OpenRouter)
- Comprehensive API integrations (Weather, Search, Geocoding)
- ML-powered spam detection with Bayes filter
- Golden data testing framework for reliable API testing
- Service layer with cache and queue services
- Multi-source database routing with SQLite
- Chat accessibility tracking: the bot records per-chat presence in `chat_info.bot_status`, excludes kicked/inaccessible chats from chat lists by default (so `/configure` and similar no longer crash on them), surfaces them to the owner via `/list_chats all`, and auto-recovers on the next inbound message. Design: [`docs/design/chat-accessibility-tracking.md`](../design/chat-accessibility-tracking.md).

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
./venv/bin/pytest tests/database/test_db_wrapper.py -v
```

---

## 3. Mandatory Rules

### 3.1 Naming Conventions (MUST follow)

| Entity | Convention | Example |
|---|---|---|
| Variables | camelCase | `chatId`, `messageText` |
| Arguments | camelCase | `configManager`, `botProvider` |
| Class fields | camelCase | `self.llmService`, `self.db` |
| Functions | camelCase | `getChatSettings()`, `sendMessage()` |
| Methods | camelCase | `newMessageHandler()`, `getBotId()` |
| Classes | PascalCase | `BaseBotHandler`, `CacheService` |
| Constants | UPPER_CASE | `DEFAULT_THREAD_ID`, `MIGRATION_VERSION_KEY` |

**Source:** [`AGENTS.md`](../../AGENTS.md)

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

**Source:** [`AGENTS.md`](../../AGENTS.md)

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

### 3.6 Enum Conventions

String enums are used throughout the project for named string constants with
explicit serialisation behaviour. Always use :class:`~enum.StrEnum` from the
standard library, **not** ``typing.Literal["a", "b"]``.

.. code-block:: python

   from enum import StrEnum

   class HandlerResultStatus(StrEnum):
       CONTINUE = "continue"
       STOP = "stop"

:class:`StrEnum` is preferred over :class:`str, enum.Enum` and over
``typing.Literal`` because it provides:

- Named constants that are self-documenting.
- String-based identity — ``ProxyType.HTTP == "http"`` is ``True``.
- Implicit ``str`` conversion for logging and serialisation.
- IDE-friendly auto-completion (unlike ``Literal``).

When you would write ``Literal["a", "b"]``, write a :class:`StrEnum` instead.

### 3.7 Import Placement

**All imports must be at the top of the file.** Never place imports inside
methods, functions, or conditional branches of a function. This rule applies
equally to third-party and standard-library imports.

For **optional dependencies** that may not be installed, use a module-level
``try/except ImportError`` block with an ``_AVAILABLE`` boolean guard:

.. code-block:: python

   try:
       import sqlite_vec
       _SQLITE_VEC_AVAILABLE = True
   except ImportError:
       _SQLITE_VEC_AVAILABLE = False

The ``_AVAILABLE`` flag is checked at usage sites rather than relying on a
runtime ``ImportError`` during execution. Inline imports are **only** acceptable
when a genuine cyclic dependency makes a top-level import impossible — this is
vanishingly rare in the Gromozeka codebase.

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
| `tests/` | Test suite — **all** tests live here, mirroring source structure (`lib/X/Y.py` → `tests/lib/X/test_Y.py`; `internal/X/Y.py` → `tests/X/test_Y.py`). No collocated tests in `lib/` or `internal/`. **Sanctioned exception:** `tests/dependencies/` holds dependency-usage regression tests that pin pinned third-party library behavior (they map to libraries, not source files). |
| `docs/` | Documentation |
| `docs/llm/memories/` | Archived task-specific working memories for completed features/subsystems |

### 4.2 Entry Points

| File | Class/Function | Purpose |
|---|---|---|
| [`main.py`](../../main.py) | `GromozekBot` | Top-level orchestrator |
| [`main.py`](../../main.py) | `main()` | CLI entry point |
| [`internal/bot/telegram/application.py`](../../internal/bot/telegram/application.py) | `TelegramBotApplication` | Telegram runner |
| [`internal/bot/max/application.py`](../../internal/bot/max/application.py) | `MaxBotApplication` | Max Messenger runner |

### 4.3 Key Singleton Services (import + get instance)

| Service | Import | `getInstance()` call |
|---|---|---|
| [`CacheService`](../../internal/services/cache/service.py) | `from internal.services.cache import CacheService` | `CacheService.getInstance()` |
| [`QueueService`](../../internal/services/queue_service/service.py) | `from internal.services.queue_service import QueueService` | `QueueService.getInstance()` |
| [`LLMService`](../../internal/services/llm/service.py) | `from internal.services.llm import LLMService` | `LLMService.getInstance()` |
| [`StorageService`](../../internal/services/storage/service.py) | `from internal.services.storage import StorageService` | `StorageService.getInstance()` |
| [`RateLimiterManager`](../../lib/rate_limiter/manager.py) | `from lib.rate_limiter import RateLimiterManager` | `RateLimiterManager.getInstance()` |
| [`ProxyService`](../../internal/services/proxy/service.py) | `from internal.services.proxy import ProxyService` | `ProxyService.getInstance()` |
| [`STTService`](../../internal/services/stt/service.py) | `from internal.services.stt import STTService` | `STTService.getInstance()` (default-off; see ADR-020) |
| [`SandboxManager`](../../lib/sandbox/manager.py) | `from lib.sandbox import SandboxManager` | `SandboxManager.getInstance()` |
| [`ProxyHelper`](../../lib/proxy/__init__.py) | `from lib.proxy import ProxyHelper` | `ProxyHelper.getInstance()` |
| [`StatsAggregationService`](../../internal/services/stats/service.py) | `from internal.services.stats import StatsAggregationService` | `StatsAggregationService.getInstance()` |

### 4.4 Critical File Paths

| Path | Purpose |
|---|---|
| [`main.py`](../../main.py) | App entry, `GromozekBot`, daemon mode |
| [`internal/bot/common/bot.py`](../../internal/bot/common/bot.py) | `TheBot` – platform-agnostic bot ops |
| [`internal/bot/common/handlers/base.py`](../../internal/bot/common/handlers/base.py) | `BaseBotHandler`, `HandlerResultStatus` |
| [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py) | `HandlersManager` – handler chain |
| [`internal/database/database.py`](../../internal/database/database.py) | `Database` – all DB operations with repository pattern |
| [`internal/config/manager.py`](../../internal/config/manager.py) | `ConfigManager` – TOML loading |
| [`internal/services/cache/service.py`](../../internal/services/cache/service.py) | `CacheService` singleton |
| [`internal/services/llm/service.py`](../../internal/services/llm/service.py) | `LLMService` singleton |
| [`internal/services/queue_service/service.py`](../../internal/services/queue_service/service.py) | `QueueService` singleton |
| [`internal/services/storage/service.py`](../../internal/services/storage/service.py) | `StorageService` singleton |
| [`internal/services/stats/service.py`](../../internal/services/stats/service.py) | `StatsAggregationService` singleton |
| [`lib/ai/abstract.py`](../../lib/ai/abstract.py) | `AbstractModel`, `AbstractLLMProvider` |
| [`lib/ai/manager.py`](../../lib/ai/manager.py) | `LLMManager` – provider + model registry |

### 4.5 `internal/` Directory

 | Path | Purpose |
|---|---|
| [`internal/bot/common/bot.py`](../../internal/bot/common/bot.py) | `TheBot` — platform-agnostic bot API |
  | [`internal/bot/common/handlers/`](../../internal/bot/common/handlers/) | All 20+ handler implementations (incl. `DivinationHandler` for `/taro` & `/runes`, `SandboxHandler` for code execution, `ChatSearchHandler` for `/search` command and `search_messages`/`list_users`/`get_thread`/`get_messages_by_ids` LLM tools, `StatsHandler` for `/stats`/`/stats_web`, plus base/manager/module_loader, tests, examples, and 15+ functional handlers) |
| [`internal/bot/common/handlers/base.py`](../../internal/bot/common/handlers/base.py) | `BaseBotHandler` — handler base class |
| [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py) | `HandlersManager` — handler chain |
| [`internal/bot/telegram/application.py`](../../internal/bot/telegram/application.py) | Telegram-specific bot application |
| [`internal/bot/max/application.py`](../../internal/bot/max/application.py) | Max Messenger bot application |
| [`internal/bot/models/`](../../internal/bot/models/) | Bot model types (EnsuredMessage, ChatSettings, etc.) |
| [`internal/config/manager.py`](../../internal/config/manager.py) | `ConfigManager` — TOML config loading |
| [`internal/database/database.py`](../../internal/database/database.py) | `Database` — all DB operations with repository pattern |
| [`internal/database/migrations/`](../../internal/database/migrations/) | `MigrationManager`, `BaseMigration`, version files |
| [`internal/models/`](../../internal/models/) | Shared types (`MessageId` class, `MessageType` enum) |
| [`internal/services/cache/service.py`](../../internal/services/cache/service.py) | `CacheService` singleton |
| [`internal/services/llm/service.py`](../../internal/services/llm/service.py) | `LLMService` singleton |
| [`internal/services/queue_service/service.py`](../../internal/services/queue_service/service.py) | `QueueService` singleton |
| [`internal/services/proxy/service.py`](../../internal/services/proxy/service.py) | `ProxyService` singleton — proxy lifecycle management |
| [`internal/services/proxy/lifecycle.py`](../../internal/services/proxy/lifecycle.py) | `ProxyLifecycle` — per-config proxy process manager |
| [`internal/services/storage/service.py`](../../internal/services/storage/service.py) | `StorageService` singleton |
| [`internal/max_webhook_receiver/`](../../internal/max_webhook_receiver/) | Standalone Max webhook receiver process (`aiohttp.web`): accepts Max webhook POSTs, stores raw payloads in `webhook_updates`, serves them to the bot via GET /updates. Run with `./venv/bin/python3 -m internal.max_webhook_receiver`. See [`architecture.md`](architecture.md) ADR-013. |

### 4.6 `lib/` Directory

| Path | Purpose |
|---|---|
| [`lib/ai/abstract.py`](../../lib/ai/abstract.py) | `AbstractModel`, `AbstractLLMProvider` |
| [`lib/ai/manager.py`](../../lib/ai/manager.py) | `LLMManager` — model + provider registry |
| [`lib/ai/models.py`](../../lib/ai/models.py) | `ModelMessage`, `ModelRunResult`, `LLMToolFunction`, etc. |
| [`lib/ai/providers/`](../../lib/ai/providers/) | Provider implementations (OpenAI-compatible, OpenRouter, Yandex Cloud, `fastembed`) |
| [`lib/cache/interface.py`](../../lib/cache/interface.py) | `CacheInterface[K,V]` — generic cache ABC |
| [`lib/cache/dict_cache.py`](../../lib/cache/dict_cache.py) | In-memory dict-based cache impl |
| [`lib/rate_limiter/interface.py`](../../lib/rate_limiter/interface.py) | `RateLimiterInterface` — ABC |
| [`lib/rate_limiter/manager.py`](../../lib/rate_limiter/manager.py) | `RateLimiterManager` singleton |
| [`lib/rate_limiter/sliding_window.py`](../../lib/rate_limiter/sliding_window.py) | `SlidingWindowRateLimiter` impl |
| [`lib/bayes_filter/bayes_filter.py`](../../lib/bayes_filter/bayes_filter.py) | Naive Bayes spam filter |
| [`lib/markdown/parser.py`](../../lib/markdown/parser.py) | Markdown → MarkdownV2 parser |
| [`lib/max_bot/client.py`](../../lib/max_bot/client.py) | Max Messenger HTTP client |
| [`lib/openweathermap/client.py`](../../lib/openweathermap/client.py) | OpenWeatherMap API client |
| [`lib/proxy/__init__.py`](../../lib/proxy/__init__.py) | Proxy resolution package — `ProxyConfig` class, `ProxyHelper` singleton, `ProxyType`/`HealthCheckType` StrEnums, `ProxyKwargs`/`ProxyLifecycleConfigDict` TypedDicts |
| [`internal/services/proxy/`](../../internal/services/proxy/) | `ProxyService` singleton (lifecycle orchestration) + `ProxyLifecycle` (per-config process manager) |
| [`lib/yandex_search/`](../../lib/yandex_search/) | Yandex Search API client |
| [`lib/geocode_maps/client.py`](../../lib/geocode_maps/client.py) | Geocode Maps API client |
| [`lib/stats/`](../../lib/stats/) | Statistics collection library (`StatsStorage`, `NullStatsStorage`, `GLOBAL_CONSUMER_ID`; read-side `StatsAnalyzer` + period helpers in `analysis.py`) |
| [`lib/stats/stats_pages/`](../../lib/stats/stats_pages/) | Module-invocable stats-page HTML generator: STDIN JSON → self-contained HTML file → stdout `{"id","url"}` (subprocess CLI contract), plus `launcher.runCliCommand` — the shared subprocess helper `StatsHandler` uses for both generation and TTL deletion; zero new deps |
| [`lib/ext_modules/`](../../lib/ext_modules/) | External custom modules (Grabliarium etc.) |
| [`lib/divination/`](../../lib/divination/) | Tarot & runes pure-logic library (decks, layouts, drawing); used by `DivinationHandler` |
| [`lib/sandbox/`](../../lib/sandbox/) | Sandboxed code execution (Docker + Python); `SandboxManager` singleton |
| [`lib/stt/`](../../lib/stt/) | Provider-neutral Speech-to-Text library — data models/enums (`STTErrorCode`, `TranscriptionResult`, etc.), typed extraction exceptions, `AbstractSTTProvider` (never-raise `stt(data)` entry), PyAV `extractAudio`, and the concrete Yandex SpeechKit v3 provider (`YandexSpeechKitProvider`). The transcript formatter moved to `internal/services/stt/formatter.py` (thin). Held directly by the stateless `STTService`; owns no DB/bot/config. Spec: [`docs/design/lib-stt-v1.md`](../design/lib-stt-v1.md); golden suite: [`aurumentation.md`](aurumentation.md) (`tests/lib/stt/golden/`) |
| [`lib/utils/`](../../lib/utils/) | Utilities: `TTLDict` (TTL-enabled dict), `getAgeInSecs`, `parseDelay`, `jsonDumps`, `packDict`/`unpackDict` |
| [`lib/logging_utils.py`](../../lib/logging_utils.py) | `initLogging()` helper |

---

## 5. LLM Tool Registration

The `ToolName` StrEnum in [`internal/bot/constants.py`](../../internal/bot/constants.py) is the canonical registry of all registered LLM tool names. When adding a new tool that the LLM can call, you **must** add a member there (its value is the string the model sees) and use `ToolName.YOUR_TOOL` in the matching `registerTool(name=...)` call site in the handler's `__init__`. Raw string literals for `name=` are discouraged.

See [`teamlead-memory.md`](teamlead-memory.md) for the full pattern (`_llmTool*` method naming, handler signature, dict return semantics) and the [add-handler skill](../../.agents/skills/add-handler/SKILL.md) Step 5 for the end-to-end registration workflow.

---

## See Also

- [`architecture.md`](architecture.md) — ADRs, component dependencies, design patterns
- [`handlers.md`](handlers.md) — Handler system, creation checklist, command decorators
- [`database.md`](database.md) — DB operations, migrations, schema, multi-source routing
- [`services.md`](services.md) — CacheService, QueueService, LLMService, StorageService, RateLimiter
- [`libraries.md`](libraries.md) — lib/ai, lib/cache, lib/markdown, lib/max_bot and more
- [`sandbox.md`](sandbox.md) — Sandbox coding patterns, configuration, and anti-patterns
- [`configuration.md`](configuration.md) — TOML config sections, ConfigManager methods
- [`testing.md`](testing.md) — Test fixtures, pytest patterns, golden data framework
- [`aurumentation.md`](aurumentation.md) — `lib/aurumentation` internals: HTTP record/replay transports, masking, the consumer suite pattern, gotchas
- [`tasks.md`](tasks.md) — Step-by-step task workflows, anti-patterns
- [`changelog.md`](changelog.md) — Canonical changelog process (Keep a Changelog, semver, entry style)
- [`teamlead-memory.md`](teamlead-memory.md) — Durable cross-task memory, repo gotchas, workflow lessons
- [`reviewing-large-changes.md`](reviewing-large-changes.md) — Methodology for reviewing diffs exceeding single-pass budget
- [`memories/index.md`](memories/index.md) — Task-specific memory index for completed subsystems/features

---

*This guide is auto-maintained and should be updated whenever significant architectural changes are made*
*Last updated: 2026-07-18*
