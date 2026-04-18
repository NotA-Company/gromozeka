# Gromozeka — Testing Guide

> **Audience:** LLM agents, dood!  
> **Purpose:** Complete guide for writing and running tests, using fixtures, and the golden data framework, dood!  
> **Self-contained:** Everything needed for testing work is here, dood!

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

```
tests/
├── conftest.py              # Global fixtures
├── utils.py                 # Test helper functions
├── test_db_wrapper.py       # DatabaseWrapper tests
├── test_llm_service.py      # LLMService tests
├── test_queue_service.py    # QueueService tests
├── bot/                     # Bot handler tests
├── fixtures/                # Golden data / test fixtures
├── integration/             # Integration tests
├── lib_ai/                  # LLMManager / AI tests
├── lib_ratelimiter/         # Rate limiter tests
├── lib_utils/               # Utility function tests
├── openweathermap/          # Weather client tests
├── services/                # Service tests
└── yandex_search/           # Yandex search tests
```

**Test discovery paths** (from [`pyproject.toml`](../../pyproject.toml:56)):
- `tests/` — main test suite
- `lib/` — library unit tests
- `internal/` — internal unit tests

---

## 2. Available Fixtures

From [`tests/conftest.py`](../../tests/conftest.py):

| Fixture | Scope | Returns | Purpose |
|---|---|---|---|
| `eventLoop` | session | `asyncio.AbstractEventLoop` | Shared event loop |
| `inMemoryDbPath` | function | `str` | `:memory:` SQLite path |
| `mockDatabaseWrapper` | function | `Mock` | Mocked `DatabaseWrapper` |
| `testDatabase` | function | `DatabaseWrapper` | Real in-memory DB |
| `mockBot` | function | `AsyncMock` | Mocked `ExtBot` |
| `mockUpdate` | function | `Mock` | Mocked Telegram `Update` |
| `mockMessage` | function | `Mock` | Mocked Telegram `Message` |
| `mockUser` | function | `Mock` | Mocked Telegram `User` |
| `mockChat` | function | `Mock` | Mocked Telegram `Chat` |
| `mockCallbackQuery` | function | `Mock` | Mocked callback query |
| `mockConfigManager` | function | `Mock` | Mocked `ConfigManager` |
| `mockQueueService` | function | `Mock` | Mocked `QueueService` |
| `mockLlmService` | function | `Mock` | Mocked `LLMService` |
| `mockCacheService` | function | `Mock` | Mocked `CacheService` |
| `mockLlmManager` | function | `Mock` | Mocked `LLMManager` |
| `resetLlmServiceSingleton` | function (autouse) | `None` | Resets LLMService singleton |
| `sampleChatSettings` | function | `dict` | Sample chat settings |
| `sampleUserData` | function | `dict` | Sample user data |
| `sampleMessages` | function | `list` | Sample message list |
| `asyncMockFactory` | function | callable | Factory for `AsyncMock` |

---

## 3. Pytest Configuration

**Config:** [`pyproject.toml:56`](../../pyproject.toml:56)

```toml
[tool.pytest.ini_options]
testpaths = ["tests", "lib", "internal"]
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*", "test*"]
asyncio_mode = "auto"  # All async tests run automatically
```

**Test markers:**
- `@pytest.mark.slow` — slow tests
- `@pytest.mark.performance` — performance tests
- `@pytest.mark.benchmark` — benchmark tests
- `@pytest.mark.memory` — memory profiling tests
- `@pytest.mark.stress` — stress tests
- `@pytest.mark.profile` — profiling tests

**Running tests:**
```bash
# Run all tests
make test

# Run single test file
./venv/bin/pytest tests/test_db_wrapper.py -v

# Run specific test class
./venv/bin/pytest tests/bot/test_some_handler.py::TestSomeHandler -v

# Run with coverage
./venv/bin/pytest --cov=internal --cov-report=html
```

---

## 4. Writing Handler Tests

```python
"""Tests for SomeHandler, dood!"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from internal.bot.common.handlers.some_handler import SomeHandler
from internal.bot.common.handlers.base import HandlerResultStatus
from internal.bot.models import BotProvider, EnsuredMessage, MessageRecipient, MessageSender


class TestSomeHandler:
    """Tests for SomeHandler, dood!"""

    @pytest.fixture
    def handler(self, mockConfigManager, mockDatabaseWrapper, mockLlmManager):
        """Create handler instance, dood!

        Args:
            mockConfigManager: Mocked configuration manager
            mockDatabaseWrapper: Mocked database wrapper
            mockLlmManager: Mocked LLM manager

        Returns:
            Configured SomeHandler instance for testing
        """
        handler = SomeHandler(
            configManager=mockConfigManager,
            database=mockDatabaseWrapper,
            llmManager=mockLlmManager,
            botProvider=BotProvider.TELEGRAM,
        )
        # Inject mock bot
        mockBot = Mock()
        mockBot.sendMessage = AsyncMock(return_value=[])
        handler.injectBot(mockBot)
        return handler

    async def testSkipsNonApplicableMessages(self, handler):
        """Should skip messages it cannot handle, dood!

        Args:
            handler: The handler fixture
        """
        ensuredMessage = Mock(spec=EnsuredMessage)
        result = await handler.newMessageHandler(ensuredMessage, Mock())
        assert result == HandlerResultStatus.SKIPPED

    async def testHandlesApplicableMessages(self, handler):
        """Should process applicable messages correctly, dood!

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
- [ ] Fixture creates handler with all four constructor args
- [ ] Fixture injects mock bot with `AsyncMock` sendMessage
- [ ] Tests skip cases return `SKIPPED`
- [ ] Tests processing cases return correct `HandlerResultStatus`
- [ ] Async tests use `async def` — no `@pytest.mark.asyncio` needed (auto mode)

---

## 5. Writing Database Tests

```python
"""Tests for DatabaseWrapper operations, dood!"""

import pytest


class TestMyDbOperation:
    """Tests for my DB operation, dood!"""

    async def testSaveAndRetrieve(self, testDatabase):
        """Should save and retrieve data correctly, dood!

        Args:
            testDatabase: Real in-memory DatabaseWrapper fixture
        """
        # Save
        testDatabase.saveSomething(chatId=123, value="test")

        # Retrieve
        result = testDatabase.getSomething(chatId=123)
        assert result is not None
        assert result["value"] == "test"

    async def testReturnsNoneForMissing(self, testDatabase):
        """Should return None when record not found, dood!

        Args:
            testDatabase: Real in-memory DatabaseWrapper fixture
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

Golden data files live in `tests/fixtures/`. Used for API testing without hitting real endpoints, dood!

**How golden data works:**
1. First run: records real API responses to `tests/fixtures/my_test_expected.json`
2. Subsequent runs: replays from fixture file — no API calls needed
3. Protects API quotas, makes tests deterministic

**Example golden data test pattern:**
```python
"""Weather client tests with golden data, dood!"""

import json
import pytest
from pathlib import Path


class TestOpenWeatherMapClient:
    """Tests for OpenWeatherMapClient with golden data, dood!"""

    @pytest.fixture
    def goldenData(self) -> dict:
        """Load golden test data, dood!

        Returns:
            Dictionary with golden test responses
        """
        fixtureFile = Path("tests/fixtures/weather_response.json")
        return json.loads(fixtureFile.read_text())

    async def testGetCurrentWeather(self, goldenData):
        """Should parse weather response correctly, dood!

        Args:
            goldenData: Golden test fixture data
        """
        # Parse the golden response
        weatherData = parseWeatherResponse(goldenData["current_weather"])
        assert weatherData.temperature == 20.5
        assert weatherData.city == "Moscow"
```

**Creating golden data:**
1. Create expected output file in `tests/fixtures/my_test_expected.json`
2. In test, load fixture and compare to actual output

---

## 7. Writing a New Test File Template

```python
"""
Tests for MyFeature, dood!
"""

import pytest
from unittest.mock import Mock, AsyncMock


class TestMyFeature:
    """Tests for MyFeature class, dood!"""

    def testBasicBehavior(self, mockDatabaseWrapper, mockConfigManager):
        """Test basic behavior, dood!

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
        """Test async behavior, dood!

        Args:
            mockBot: Mocked bot instance fixture
        """
        result = await someAsyncMethod()
        assert result is not None

    def testSingletonReset(self):
        """Test singleton reset, dood!"""
        # Use the autouse fixture from conftest.py — resetLlmServiceSingleton
        # OR manually reset for non-LLM services:
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

*This guide is auto-maintained and should be updated whenever testing patterns change, dood!*  
*Last updated: 2026-04-18, dood!*
