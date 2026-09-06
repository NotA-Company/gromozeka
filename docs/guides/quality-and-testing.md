---
category: guide
---

# Quality and Testing

Running the test suite (including the golden-data framework) and the naming, docstring, and linting standards enforced on every change.

## 9. Testing Guide

The test suite has 1185+ tests covering all layers of the application Tests use pytest with `asyncio_mode = auto` so async tests work natively

### Running Tests

```bash
# Run all tests (recommended)
make test

# Run all tests with verbose output
make test V=1

# Re-run only previously failed tests
make test-failed

# Run with coverage report
make coverage
# HTML report at: htmlcov/index.html

# Run specific test file
./venv/bin/pytest tests/database/test_db_wrapper.py -v

# Run specific test function
./venv/bin/pytest tests/database/test_db_wrapper.py::test_my_function -v

# Run only slow tests
./venv/bin/python3 -m pytest -m slow

# Exclude slow tests
./venv/bin/python3 -m pytest -m "not slow"
```

### Test Structure

Test files are discovered from three paths (configured in [`pyproject.toml`](/pyproject.toml:59)), but all test files now live exclusively under `tests/` — there are no collocated test files in `lib/` or `internal/`. Test directories mirror source structure: `internal/X/Y.py` → `tests/X/test_Y.py`; `lib/X/Y.py` → `tests/lib/X/test_Y.py`.

Test files must match `test_*.py` or `*_test.py`. Test classes must start with `Test`, and test functions with `test_`

### Golden Data Framework

For API client tests (weather, geocoding, search), the project uses a **golden data** (record/replay) pattern This avoids hitting real API endpoints during test runs while maintaining realistic test data

**How it works:**

1. **Record mode**: Tests are run with real API calls, and responses are saved as JSON fixtures in `tests/lib/<service>/golden/`
2. **Replay mode**: Tests load the fixture files instead of making real API calls

**Structure:**

```
tests/
└── lib/
    ├── openweathermap/
    │   ├── golden/                    # Golden data for weather client
    │   └── test_weather_client.py     # Tests using golden data
    └── geocode_maps/
        ├── golden/                    # Golden data for geocoding
        └── test_client.py
```

**Example test using fixtures:**

```python
import json
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "weather"


@pytest.fixture
def mockWeatherResponse():
    """Load cached API response"""
    return json.loads((FIXTURES_DIR / "moscow_current.json").read_text())


async def test_getWeatherByCity(mockWeatherResponse, httpx_mock):
    """Test weather client with golden data"""
    httpx_mock.add_response(json=mockWeatherResponse)

    client = OpenWeatherMapClient(apiKey="test-key")
    result = await client.getWeatherByCity("Moscow", "RU")
    assert result.current.temp > -60
```

### Writing New Tests

**Unit test example:**

```python
"""Tests for MyNewHandler"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from internal.bot.common.handlers.my_handler import MyNewHandler
from internal.bot.common.handlers.base import HandlerResultStatus


@pytest.fixture
def myHandler():
    """Create handler with mocked dependencies"""
    configManager = MagicMock()
    configManager.getBotConfig.return_value = {}
    database = MagicMock()
    botProvider = MagicMock()
    return MyNewHandler(configManager=configManager, database=database, botProvider=botProvider)


async def test_skipsIrrelevantMessages(myHandler):
    """Handler should skip messages that don't apply to it"""
    ensuredMessage = MagicMock()
    updateObj = MagicMock()
    myHandler.sendMessage = AsyncMock()

    # Configure message to not be handled
    ensuredMessage.text = "irrelevant"

    result = await myHandler.newMessageHandler(ensuredMessage, updateObj)
    assert result == HandlerResultStatus.SKIPPED
    myHandler.sendMessage.assert_not_called()
```

**Integration test example:**

```python
"""Integration tests for database wrapper"""

import pytest
import tempfile
import os
from internal.database import Database


@pytest.fixture
def tempDb():
    """Create a temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath = f.name

    db = Database(config={
        "default": "default",
        "providers": {"default": {"provider": "sqlite3", "parameters": {"dbPath": dbPath, "readOnly": False}}},
    })
    yield db

    os.unlink(dbPath)


def test_createAndGetChat(tempDb):
    """Test chat creation and retrieval"""
    tempDb.ensureChatExists(chatId=-100123, chatType="group", title="Test Chat")
    chat = tempDb.getChat(chatId=-100123)
    assert chat is not None
    assert chat["title"] == "Test Chat"
```

### Test Markers

Configure special markers in [`pyproject.toml`](/pyproject.toml:66):

```python
@pytest.mark.slow        # Mark slow tests (skipped with -m "not slow")
@pytest.mark.performance # Performance benchmarks
@pytest.mark.benchmark   # Benchmark tests
@pytest.mark.memory      # Memory profiling tests
@pytest.mark.stress      # Stress tests
```

---

## 10. Code Quality

### Naming Conventions

The project enforces strict naming conventions Violating these is grounds for rejection in code review

| Construct | Convention | Example |
|---|---|---|
| Variables | `camelCase` | `chatId`, `userMessage`, `botToken` |
| Function arguments | `camelCase` | `configManager`, `ensuredMessage` |
| Local variables | `camelCase` | `resultText`, `spamScore` |
| Functions/Methods | `camelCase` | `getChatSettings()`, `handleMessage()` |
| Class fields | `camelCase` | `self.dbWrapper`, `self.maxCacheSize` |
| Class names | `PascalCase` | `Database`, `HandlersManager`, `CacheService` |
| Constants | `UPPER_CASE` | `DEFAULT_TIMEOUT`, `API_BASE_URL`, `MAX_RETRIES` |
| Module-level vars | `camelCase` or `UPPER_CASE` | `logger`, `DEFAULT_THREAD_ID` |

### Docstring Requirements

**Every** module, class, method, function, and non-obvious class field **must** have a docstring Be concise but always document all args and the return type

**Module docstring:**

```python
"""
My module providing something useful

This module implements X, Y, and Z functionality for the Gromozeka bot.
"""
```

**Class docstring:**

```python
class MyClass:
    """Short description of the class

    Longer description explaining the purpose, key design decisions,
    and usage context.

    Attributes:
        myField: Description of the field
        anotherField: Description

    Example:
        >>> obj = MyClass(config={...})
        >>> result = obj.doSomething()
    """
```

**Method/function docstring:**

```python
def myFunction(self, chatId: int, value: str) -> Optional[str]:
    """Brief description of what this does

    Longer description if needed for complex logic.

    Args:
        chatId: The chat ID to look up
        value: The value to process

    Returns:
        The processed result, or None if not found

    Raises:
        ValueError: If chatId is negative
    """
```

### Type Hints

**Always** write type hints for:
- All function/method arguments
- Return types
- Local variables when the type is not obvious

```python
# Good
def processMessage(self, chatId: int, message: str, ttl: Optional[int] = None) -> bool:
    result: Optional[str] = None
    processed: bool = False
    return processed

# Bad - no type hints
def processMessage(self, chat_id, message, ttl=None):
    ...
```

### Linting & Formatting

The project uses four code quality tools configured in [`pyproject.toml`](/pyproject.toml)

| Tool | Purpose | Config |
|---|---|---|
| **Black** | Code formatter | 120 char line length, Python 3.12 target |
| **isort** | Import sorter | Black-compatible profile |
| **Flake8** | Style/error linter | 120 char limit, select `B,C,E,F,W,B950` |
| **Pyright** | Static type checker | `basic` mode, venv-aware |

**Import order** (enforced by isort)

```python
# 1. FUTURE imports
from __future__ import annotations

# 2. STDLIB imports
import asyncio
import logging
from typing import Optional

# 3. THIRDPARTY imports
import httpx2 as httpx
import telegram

# 4. FIRSTPARTY imports (internal/, lib/)
from internal.config.manager import ConfigManager

# 5. LOCALFOLDER (relative imports)
from .base import BaseBotHandler
```

### Make Commands

All quality checks and workflows are available via `make`

```bash
# Format code (Black + isort)
make format

# Run linters (Flake8 + isort check + Pyright)
make lint

# Run all tests
make test

# Run tests with verbose output
make test V=1

# Re-run only failing tests
make test-failed

# Run tests with HTML coverage report
make coverage

# Format + lint check (good for CI)
make check

# Run the full CI pipeline locally in the Alpine container (mirrors .sourcecraft/ci.yaml); needs Docker
make ci

# Install dependencies into venv
make install

# Update requirements.txt from current venv
make freeze-requirements

# Show outdated packages
make list-outdated-requirements

# Clean venv and __pycache__
make clean

# Show all available commands
make help
```

**Required workflow before committing** (enforced by code review)

```bash
make format lint    # Fix formatting + check for issues
make test           # Ensure all tests pass
```

**Enum Conventions**

Use :class:`~enum.StrEnum` for all string-based enumerations — do not use
``typing.Literal["a", "b"]`` or bare strings. :class:`StrEnum` (from the
standard library ``enum`` module) provides named constants that are equal
to their string values and are safe to refactor.

.. code-block:: python

   from enum import StrEnum

   class HandlerResultStatus(StrEnum):
       CONTINUE = "continue"
       STOP = "stop"

This is already the project-wide convention (e.g. ``ChatSettingsKey``,
``ProxyType``). New code must follow it.

**Import Placement**

All imports belong at the top of the file. For optional dependencies that
may not be installed (e.g. ``sqlite-vec``), use a module-level
``try/except ImportError`` block:

.. code-block:: python

   try:
       import sqlite_vec
       _SQLITE_VEC_AVAILABLE = True
   except ImportError:
       _SQLITE_VEC_AVAILABLE = False

Never place ``import`` or ``from ... import`` inside a method or function
body unless a cyclic dependency makes it genuinely unavoidable.

---
