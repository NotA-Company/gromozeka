---
description: "Testing guide — writing and running tests, shared fixtures, markers, and the golden-data API-test framework"
tags: [agent, testing]
category: guide
---

# Gromozeka — Testing Guide

> **Audience:** LLM agents  
> **Purpose:** Complete guide for writing and running tests, using fixtures, and the golden data framework  
> **Self-contained:** Everything needed for testing work is here

---

## Table of Contents

1. [Test Directory Structure](#1-test-directory-structure)
2. [Available Fixtures](#2-available-fixtures)
3. [Pytest Configuration](#3-pytest-configuration)
4. [Writing Handler Tests](#4-writing-handler-tests)
5. [Writing Database Tests](#5-writing-database-tests)
6. [Golden Data Tests](#6-golden-data-tests)
7. [Writing a New Test File Template](#7-writing-a-new-test-file-template)

---

## 1. Test Directory Structure

> **MANDATORY RULE — all new tests MUST follow this layout. No exceptions.**
> Never add test files inside `lib/` or `internal/`. Every test file lives under `tests/`.

The mirror layout is the only valid location for test files:

- `internal/X/Y.py` → `tests/X/test_Y.py` (strip `internal/` prefix)
- `lib/X/Y.py` → `tests/lib/X/test_Y.py` (preserve `lib/` prefix)
- Cross-cutting tests go in `tests/integration/` or `tests/verification/`

**No collocated tests.** If you find an old test file inside `lib/` or `internal/`, move it to the corresponding `tests/` location before adding new test cases.

Example: to test `lib/ai/manager.py`, create `tests/lib/ai/test_manager.py` — never `lib/ai/test_manager.py`.

**Sanctioned exception — `tests/dependencies/`:** This directory is the home for **dependency-usage regression tests** that pin the *current* behavior of pinned third-party libraries (`python-dateutil`, `tomli`, `python-magic`, `html-to-markdown`, `sqlite-vec`) so that a version bump silently changing behavior fails loudly. 58 tests across 5 files; each asserts its pinned library version via `importlib.metadata.version()` (sqlite-vec via `SELECT vec_version()`). These tests map to **libraries, not source files**, so the mirror-layout convention does not apply — but they still live under `tests/`, so the "no collocated tests" rule is honored.

**Sanctioned exception — `lib/ext_modules/grabliarium/tests/`:** The `lib/ext_modules/` subtree holds vendored extension subpackages (e.g. `grabliarium`) that ship with their own `pyproject.toml` and a collocated `tests/` directory *inside* the subpackage. This carve-out is intentional: each subpackage is treated as a self-contained unit, which is also why `make format` iterates `lib/ext_modules/*/` separately rather than auto-traversing them (see `AGENTS.md`). New vendored subpackages added under `lib/ext_modules/` may follow the same pattern.

```
tests/
├── conftest.py                              # Global fixtures
├── utils.py                                 # Test helper functions
├── bot/                                     # Bot handler tests
│   ├── common/handlers/
│   ├── max/                                 # Max platform adapter tests
│   ├── models/
│   ├── test_divination_discovery.py
│   ├── test_divination_handler.py
│   └── test_sandbox.py
├── config/                                  # Config tests
├── database/                                # Database tests
│   ├── integration/
│   ├── migrations/
│   ├── performance/
│   └── repositories/
├── dependencies/                            # Dependency-usage regression tests (pin pinned-library behavior; exception to mirror layout)
├── fixtures/                                # Golden data / test fixtures
├── integration/                             # Cross-cutting integration tests
├── lib/                                     # Library tests (mirrors lib/ structure)
│   ├── ai/                                  # LLMManager / AI tests + golden data
│   ├── aurumentation/
│   ├── bayes_filter/
│   ├── cache/
│   ├── db/                                  # SQL provider abstraction tests (mirrors lib/db/)
│   │   └── providers/                       # BaseSQLProvider / sqlite3 / vector search
│   ├── divination/                          # Divination tests + golden data
│   ├── geocode_maps/                        # Geocoding tests + golden data
│   ├── markdown/
│   ├── max_bot/                             # MaxBotClient tests
│   ├── max_webhook_receiver/                # Max webhook receiver tests (ADR-025): test_repository.py (15) + test_app.py (20) + test_main.py (5) over the receiver's OWN database; bot-side table drop covered by tests/database/test_migration_029_drop_webhook_updates.py (6)
│   ├── openweathermap/                      # Weather tests + golden data
│   ├── rate_limiter/
│   ├── sandbox/
│   ├── stats/
│   ├── utils/
│   └── yandex_search/                       # Search tests + golden data
├── models/                                  # Model tests
├── scripts/                                 # Script tests
├── services/                                # Service tests
│   ├── cache/
│   ├── llm/
│   ├── proxy/                               # ProxyService + ProxyLifecycle tests
│   ├── queue_service/
│   └── storage/
└── verification/                            # Cross-cutting verification tests
```

**Test discovery** (from `[tool.pytest.ini_options]` in [`pyproject.toml`](../../pyproject.toml)):
- `testpaths = ["tests", "lib", "internal"]` — only `tests/` contains test files; `lib/` and `internal/` are kept in config for pytest collection compatibility but have no collocated test files. New tests must never be added inside `lib/` or `internal/`.

---

## 2. Available Fixtures

From [`tests/conftest.py`](../../tests/conftest.py):

| Fixture | Scope | Returns | Purpose |
|---|---|---|---|
| `eventLoop` | session | `asyncio.AbstractEventLoop` | Shared event loop |
| `inMemoryDbPath` | function | `str` | `:memory:` SQLite path |
| `mockDatabaseWrapper` | function | `Mock` | Mocked `Database` |
| `testDatabase` | function | `Database` | Real in-memory DB |
| `mockBot` | function | `AsyncMock` | Mocked `ExtBot` |
| `mockUpdate` | function | `Mock` | Mocked Telegram `Update` |
| `mockMessage` | function | `Mock` | Mocked Telegram `Message` |
| `mockUser` | function | `Mock` | Mocked Telegram `User` |
| `mockChat` | function | `Mock` | Mocked Telegram `Chat` |
| `mockCallbackQuery` | function | `Mock` | Mocked callback query |
| `mockConfigManager` | function | `Mock` | Mocked `ConfigManager` |
| `mockQueueService` | function | `Mock` | Mocked `QueueService` |
| `mockLlmService` | function | `Mock` | Mocked `LLMService` (pre-stubs `generateText` as AsyncMock, `registerTool` and `getTool` as Mock) |
| `mockCacheService` | function | `Mock` | Mocked `CacheService` |
| `mockLlmManager` | function | `Mock` | Mocked `LLMManager` (use via `mockLlmService.getLLMManager`) |
| `resetLlmServiceSingleton` | function (autouse) | `None` | Resets LLMService singleton |
| `resetProxyServiceSingleton` | function (autouse) | `None` | Resets ProxyService singleton |
| `resetProxyHelperSingleton` | function (autouse) | `None` | Resets ProxyHelper singleton + global proxy config (disabled) |
| `sampleChatSettings` | function | `dict` | Sample chat settings |
| `sampleUserData` | function | `dict` | Sample user data |
| `sampleMessages` | function | `list` | Sample message list |
| `asyncMockFactory` | function | callable | Factory for `AsyncMock` |

---

## 3. Pytest Configuration

**Config:** `[tool.pytest.ini_options]` in [`pyproject.toml`](../../pyproject.toml)

```toml
[tool.pytest.ini_options]
testpaths = ["tests", "lib", "internal"]  # only tests/ has test files now
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*", "test*"]
asyncio_mode = "auto"  # All async tests run automatically
```

**Warnings policy:** `filterwarnings = ["error::ResourceWarning"]` — any `ResourceWarning` (unclosed file/socket/client, in test or production code) is a hard test failure repo-wide. Fix leaks with deterministic close (try/finally, context manager, fixture teardown); suppress only with the narrowest per-test `@pytest.mark.filterwarnings` and a comment naming the third-party cause.

**Test markers** (registered in `pyproject.toml` under `markers = [...]`; none are auto-skipped):
- `@pytest.mark.slow` — slow tests (deselect with `-m "not slow"`)
- `@pytest.mark.performance` — performance tests
- `@pytest.mark.benchmark` — benchmark tests
- `@pytest.mark.memory` — memory profiling tests
- `@pytest.mark.stress` — stress tests
- `@pytest.mark.profile` — profiling tests

**Running tests** (`make test` wraps `pytest` in `time timeout 5m`; pass `V=1` to add `-v`):
```bash
# Run all tests (5-minute hard timeout via the Makefile; V=1 enables -v)
make test

# Re-run only the tests that failed on the last run
make test-failed

# Run single test file
./venv/bin/pytest tests/database/test_db_wrapper.py -v

# Run a specific test class / test function
./venv/bin/pytest tests/bot/common/handlers/test_some_handler.py::TestSomeHandler -v
./venv/bin/pytest tests/bot/common/handlers/test_some_handler.py::TestSomeHandler::testFn -v

# Deselect slow / benchmark markers
./venv/bin/pytest -m "not slow"

# Run with coverage
./venv/bin/pytest --cov=internal --cov-report=html
```

---

## 4. Writing Handler Tests

```python
"""Tests for SomeHandler"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from internal.bot.common.handlers.some_handler import SomeHandler
from internal.bot.common.handlers.base import HandlerResultStatus
from internal.bot.models import BotProvider, EnsuredMessage, MessageRecipient, MessageSender


class TestSomeHandler:
    """Tests for SomeHandler"""

    @pytest.fixture
    def handler(self, mockConfigManager, mockDatabaseWrapper, mockLlmService):
        """Create handler instance

        Args:
            mockConfigManager: Mocked configuration manager
            mockDatabaseWrapper: Mocked database wrapper
            mockLlmService: Mocked LLM service

        Returns:
            Configured SomeHandler instance for testing
        """
        handler = SomeHandler(
            configManager=mockConfigManager,
            database=mockDatabaseWrapper,
            botProvider=BotProvider.TELEGRAM,
        )
        # Inject mock bot
        mockBot = Mock()
        mockBot.sendMessage = AsyncMock(return_value=[])
        handler.injectBot(mockBot)
        return handler

    async def testSkipsNonApplicableMessages(self, handler):
        """Should skip messages it cannot handle

        Args:
            handler: The handler fixture
        """
        ensuredMessage = Mock(spec=EnsuredMessage)
        result = await handler.newMessageHandler(ensuredMessage, Mock())
        assert result == HandlerResultStatus.SKIPPED

    async def testHandlesApplicableMessages(self, handler):
        """Should process applicable messages correctly

        Args:
            handler: The handler fixture
        """
        ensuredMessage = Mock(spec=EnsuredMessage)
        # Configure message to be applicable
        ensuredMessage.messageText = "/mycommand some args"

        result = await handler.newMessageHandler(ensuredMessage, Mock())
        assert result == HandlerResultStatus.FINAL
```

**Handler test checklist:**
- [ ] Fixture creates handler with all three constructor args
- [ ] Fixture injects mock bot with `AsyncMock` sendMessage
- [ ] Tests skip cases return `SKIPPED`
- [ ] Tests processing cases return correct `HandlerResultStatus`
- [ ] Async tests use `async def` — no `@pytest.mark.asyncio` needed (auto mode)

---

## 5. Writing Database Tests

```python
"""Tests for Database operations"""

import pytest


class TestMyDbOperation:
    """Tests for my DB operation"""

    async def testSaveAndRetrieve(self, testDatabase):
        """Should save and retrieve data correctly

        Args:
            testDatabase: Real in-memory Database fixture
        """
        # Save
        testDatabase.saveSomething(chatId=123, value="test")

        # Retrieve
        result = testDatabase.getSomething(chatId=123)
        assert result is not None
        assert result["value"] == "test"

    async def testReturnsNoneForMissing(self, testDatabase):
        """Should return None when record not found

        Args:
            testDatabase: Real in-memory Database fixture
        """
        result = testDatabase.getSomething(chatId=999999)
        assert result is None
```

**Database test checklist:**
- [ ] Uses `testDatabase` fixture for real in-memory DB (NOT `mockDatabaseWrapper`)
- [ ] Tests both present and absent cases
- [ ] Tests migration if schema changed
- [ ] Tests both `up()` and `down()` migrations

---

## 6. Golden Data Tests

Golden data tests use the lib/aurumentation framework with transport-level httpx patching. This system captures actual HTTP traffic and replays it during tests without making real API calls.

> **httpx2 alias note:** the repo runs on `httpx2` (aliased as `httpx` process-wide via `httpx2.alias_httpx()` at the top of `tests/conftest.py` and `main.py` — see [`architecture.md`](architecture.md) ADR-021). References below to "patches httpx" / `httpx.AsyncClient` are literally what the source reads; at runtime those are `httpx2` symbols, and the patching mechanism is unaffected by the alias. See [`aurumentation.md`](aurumentation.md) for the full internals.

### Golden Data Locations

Per-service golden data directories (all under `tests/lib/`):
- `tests/lib/ai/golden` - AI provider golden data
- `tests/lib/openweathermap/golden` - Weather client golden data
- `tests/lib/yandex_search/golden` - Search client golden data
- `tests/lib/geocode_maps/golden` - Geocoding golden data
- `tests/lib/divination/golden` - Divination service golden data

### How Golden Data Works

1. **Collection Phase (one-time setup):**
   - Create scenario definitions (JSON) describing test cases
   - Run collector script with real API credentials
   - GoldenDataRecorder patches httpx at transport level to capture ALL HTTP traffic
   - SecretMasker automatically masks API keys, tokens, and sensitive data
   - Captured data saved as JSON files with metadata

2. **Testing Phase (every test run):**
   - GoldenDataReplayer loads golden data files
   - Patches httpx.AsyncClient globally with ReplayTransport
   - Test code makes HTTP calls as normal
   - ReplayTransport returns recorded responses instead of real network calls
   - Tests are deterministic, fast, and work offline

### Example Golden Data Test Pattern

```python
"""Weather client tests with golden data"""

import pytest
from lib.aurumentation import GoldenDataReplayer
from pathlib import Path
import json


class TestOpenWeatherMapClient:
    """Tests for OpenWeatherMapClient with golden data"""

    @pytest.fixture
    async def goldenWeatherMinsk(self):
        """Load and replay golden data for Minsk weather"""
        scenario_file = Path("tests/lib/openweathermap/golden/Get_weather_for_Minsk_Belarus.json")
        with open(scenario_file) as f:
            scenario = json.load(f)

        # Create replayer that patches httpx
        replayer = GoldenDataReplayer(scenario)
        async with replayer:
            yield

    async def testGetCurrentWeather(self, goldenWeatherMinsk):
        """Should parse weather response correctly using golden data

        Args:
            goldenWeatherMinsk: Fixture providing golden data replay
        """
        # Create client - will use golden data, no real API call
        client = OpenWeatherMapClient(apiKey="test_key", cache=None)

        # Make request - replayed from golden data
        weatherData = await client.getWeather(lat=53.9, lon=27.57)

        # Validate response
        assert weatherData is not None
        assert weatherData["location"]["name"] == "Minsk"
        assert weatherData["location"]["country"] == "BY"
        assert "weather" in weatherData
```

### Key Differences from Old System

1. **Transport-level patching:** Patches httpx itself, not individual client methods
2. **Generic collector:** Single collector script works for any httpx-based client
3. **Complete capture:** Gets method, URL, headers, body, status code, response content
4. **Automatic secret masking:** Masks API keys, tokens, folder_id via patterns and explicit lists
5. **Per-service directories:** Golden data organized by service rather than all in tests/fixtures/

### Collecting New Golden Data

```bash
# 1. Create scenario JSON file
cat > tests/lib/openweathermap/scenarios.json << EOF
[
  {
    "description": "Get weather for Minsk, Belarus",
    "module": "lib.openweathermap.client",
    "class": "OpenWeatherMapClient",
    "init_kwargs": {
      "apiKey": "${OPENWEATHERMAP_API_KEY}",
      "cache": null,
      "geocodingTTL": 0,
      "weatherTTL": 0
    },
    "method": "getWeatherByCity",
    "kwargs": {
      "city": "Minsk",
      "country": "BY"
    }
  }
]
EOF

# 2. Run collector (requires real API key in environment)
export OPENWEATHERMAP_API_KEY=your_real_api_key
./venv/bin/python3 -m lib.aurumentation.collector \
  --input tests/lib/openweathermap/scenarios.json \
  --output tests/lib/openweathermap/golden/ \
  --secrets OPENWEATHERMAP_API_KEY

# 3. Verify no secrets in generated files
grep -r "sk-" tests/lib/openweathermap/golden/  # Should return nothing
```

---

## 7. Writing a New Test File Template

```python
"""
Tests for MyFeature
"""

import pytest
from unittest.mock import Mock, AsyncMock


class TestMyFeature:
    """Tests for MyFeature class"""

    def testBasicBehavior(self, mockDatabaseWrapper, mockConfigManager):
        """Test basic behavior

        Args:
            mockDatabaseWrapper: Mocked database wrapper fixture
            mockConfigManager: Mocked config manager fixture
        """
        # Arrange
        expectedResult: str = "expected"

        # Act
        result = doSomething()

        # Assert
        assert result == expectedResult

    async def testAsyncBehavior(self, mockBot):
        """Test async behavior

        Args:
            mockBot: Mocked bot instance fixture
        """
        result = await someAsyncMethod()
        assert result is not None

    def testSingletonReset(self):
        """Test singleton reset"""
        # The autouse `resetLlmServiceSingleton` fixture in conftest.py
        # handles `LLMService` automatically. Other leaky singletons —
        # `CacheService`, `QueueService`, `StorageService`,
        # `RateLimiterManager` — must be reset manually in the fixture
        # (or test body) by setting `_instance = None` before/after:
        from internal.services.cache import CacheService
        CacheService._instance = None
        try:
            service = CacheService.getInstance()
            assert service is not None
        finally:
            CacheService._instance = None
```

**Test file checklist:**
- [ ] Module docstring
- [ ] Class docstring
- [ ] Method docstrings with `Args:` sections
- [ ] Type hints on local variables when not obvious
- [ ] Uses camelCase for all local variables
- [ ] Async tests use `async def` (pytest-asyncio auto mode)
- [ ] Ran `make format lint` and `make test`

---

## See Also

- [`index.md`](index.md) — Project overview, mandatory rules
- [`handlers.md`](handlers.md) — Handler patterns tested in `tests/bot/`
- [`database.md`](database.md) — Using `testDatabase` fixture for DB tests
- [`services.md`](services.md) — Singleton reset pattern in tests
- [`tasks.md`](tasks.md) — Step-by-step: "fix a bug in a handler" (write regression test first)

---

*This guide is auto-maintained and should be updated whenever testing patterns change*  
*Last updated: 2026-07-18*
