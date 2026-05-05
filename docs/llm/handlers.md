# Gromozeka — Handler System

> **Audience:** LLM agents, dood!  
> **Purpose:** Complete guide to creating, modifying, and registering bot command handlers, dood!  
> **Self-contained:** Everything needed for handler work is here, dood!

---

## Table of Contents

1. [Handler Files Reference](#1-handler-files-reference)
2. [Handler Creation Checklist](#2-handler-creation-checklist)
3. [Handler Skeleton Template](#3-handler-skeleton-template)
4. [Command Decorator Pattern](#4-command-decorator-pattern)
5. [Registering Handlers in HandlersManager](#5-registering-handlers-in-handlersmanager)
6. [Handler Chain Order](#6-handler-chain-order)
7. [HandlerResultStatus Reference](#7-handlerresultstatus-reference)

---

## 1. Handler Files Reference

**Directory:** [`internal/bot/common/handlers/`](../../internal/bot/common/handlers/)

| File | Handler Class | Purpose |
|---|---|---|
| [`base.py`](../../internal/bot/common/handlers/base.py) | `BaseBotHandler` | Abstract base for all handlers |
| [`manager.py`](../../internal/bot/common/handlers/manager.py) | `HandlersManager` | Orchestrates all handlers |
| [`message_preprocessor.py`](../../internal/bot/common/handlers/message_preprocessor.py) | `MessagePreprocessorHandler` | First in chain; saves message + processes media |
| [`spam.py`](../../internal/bot/common/handlers/spam.py) | `SpamHandler` | Spam detection (runs after preprocessor) |
| [`configure.py`](../../internal/bot/common/handlers/configure.py) | `ConfigureCommandHandler` | Chat settings configuration |
| [`summarization.py`](../../internal/bot/common/handlers/summarization.py) | `SummarizationHandler` | Chat summarization |
| [`user_data.py`](../../internal/bot/common/handlers/user_data.py) | `UserDataHandler` | User data management |
| [`dev_commands.py`](../../internal/bot/common/handlers/dev_commands.py) | `DevCommandsHandler` | Developer/debug commands |
| [`media.py`](../../internal/bot/common/handlers/media.py) | `MediaHandler` | Media message processing |
| [`common.py`](../../internal/bot/common/handlers/common.py) | `CommonHandler` | Common bot commands |
| [`help_command.py`](../../internal/bot/common/handlers/help_command.py) | `HelpHandler` | `/help` command |
| [`react_on_user.py`](../../internal/bot/common/handlers/react_on_user.py) | `ReactOnUserMessageHandler` | Telegram-only reactions |
| [`topic_manager.py`](../../internal/bot/common/handlers/topic_manager.py) | `TopicManagerHandler` | Telegram forum topics |
| [`weather.py`](../../internal/bot/common/handlers/weather.py) | `WeatherHandler` | Weather commands (if enabled) |
| [`yandex_search.py`](../../internal/bot/common/handlers/yandex_search.py) | `YandexSearchHandler` | Yandex Search (if enabled) |
| [`resender.py`](../../internal/bot/common/handlers/resender.py) | `ResenderHandler` | Message resending (if enabled) |
| [`divination.py`](../../internal/bot/common/handlers/divination.py) | `DivinationHandler` | `/taro` & `/runes` readings (if `divination.enabled`) |
| [`llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py) | `LLMMessageHandler` | **LAST** in chain; LLM responses |
| [`example_custom_handler.py`](../../internal/bot/common/handlers/example_custom_handler.py) | `ExampleCustomHandler` | Template for custom handlers |

**`DivinationHandler` — LLM-tool reply behavior note:**
When invoked via the `do_tarot_reading` / `do_runes_reading` LLM tools (`invoked_via = 'llm_tool'`), the handler returns the full interpretation in the JSON tool result (fields: `done`, `summary`, `interpretation`, `imageGenerated`) so the host LLM can incorporate it into its own reply — no text bot message is sent. Only the generated image (if `image-generation = true` and generation succeeded) is sent directly to the user with an empty caption. Slash-command behavior (`/taro`, `/runes`) is unchanged: text reply (and photo if enabled) are sent directly to the user as before, dood!

---

## 2. Handler Creation Checklist

Step-by-step for adding a new bot command handler, dood!

### Step 1: Create handler file

**Path:** `internal/bot/common/handlers/my_handler.py`

Use the skeleton from [Section 3](#3-handler-skeleton-template), dood!

### Step 2: Register handler in `HandlersManager`

**File:** [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py:249)

See [Section 5](#5-registering-handlers-in-handlersmanager) for registration code, dood!

### Step 3: Define commands with decorator

Use `@commandHandlerV2` — see [Section 4](#4-command-decorator-pattern), dood!

### Step 4: Implement `newMessageHandler` (if needed)

Only implement if your handler reacts to non-command messages:
```python
async def newMessageHandler(
    self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
) -> HandlerResultStatus:
    """Process incoming messages, dood!

    Args:
        ensuredMessage: The incoming message
        updateObj: Raw update object from platform

    Returns:
        HandlerResultStatus indicating processing result
    """
    # Check if this handler should process this message
    if not self._shouldHandle(ensuredMessage):
        return HandlerResultStatus.SKIPPED

    # Process...
    await self.sendMessage(ensuredMessage, messageText="response")
    return HandlerResultStatus.FINAL
```

### Step 5: Write tests

**Path:** `tests/bot/test_my_handler.py`

See [`testing.md`](testing.md) for test patterns, dood!

### Step 6: Run quality checks

```bash
make format lint
make test
```

### Checklist after creating/modifying a handler

- [ ] Docstring on class and all methods
- [ ] Type hints on all method arguments and returns
- [ ] Added handler to `HandlersManager.__init__()` if it's a new built-in handler ([`manager.py:249`](../../internal/bot/common/handlers/manager.py:249))
- [ ] OR configured as custom handler via TOML if it's a plugin
- [ ] Added tests in `tests/bot/` directory
- [ ] Ran `make format lint` and `make test`

---

## 3. Handler Skeleton Template

```python
"""
Module docstring describing what this handler does, dood!
"""

import logging
from typing import Optional

from internal.bot.common.models import UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    commandHandlerV2,
)
from internal.config.manager import ConfigManager
from internal.database.models import MessageCategory
from internal.database import Database
from lib.ai import LLMManager

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class MyNewHandler(BaseBotHandler):
    """Handler description, dood!

    Attributes:
        configManager: Configuration manager instance
        database: Database wrapper for persistence
        llmManager: LLM manager for AI features
        botProvider: Bot provider type
    """

    def __init__(
        self,
        configManager: ConfigManager,
        database: Database,
        llmManager: LLMManager,
        botProvider: BotProvider,
    ):
        """Initialize handler, dood!

        Args:
            configManager: Configuration manager
            database: Database wrapper
            llmManager: LLM manager
            botProvider: Bot provider type
        """
        super().__init__(
            configManager=configManager,
            database=database,
            llmManager=llmManager,
            botProvider=botProvider,
        )

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """Process incoming messages, dood!

        Args:
            ensuredMessage: The incoming message
            updateObj: Raw update object from platform

        Returns:
            HandlerResultStatus indicating processing result
        """
        # Return SKIPPED if this handler doesn't apply
        return HandlerResultStatus.SKIPPED

    @commandHandlerV2(
        commands=("mycommand",),
        shortDescription="- short description for help",
        helpMessage="Full help message explaining the command, dood!",
        visibility={CommandPermission.DEFAULT},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def myCommand(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        updateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle /mycommand, dood!

        Args:
            ensuredMessage: The command message
            command: Command name (e.g. "mycommand")
            args: Arguments string after command
            updateObj: Raw update object
            typingManager: Optional typing indicator
        """
        await self.sendMessage(
            ensuredMessage,
            messageText="Response here, dood!",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
```

**Required imports for handler:** Always include all shown above. Additional imports as needed.

**Required patterns:**
- Inherit from `BaseBotHandler`
- Call `super().__init__()` with all four args
- Use `self.sendMessage()` (NOT direct bot API)
- Return `HandlerResultStatus` from `newMessageHandler()`
- Use `@commandHandlerV2` decorator for commands
- Save bot replies via `messageCategory=MessageCategory.BOT_COMMAND_REPLY`

---

## 4. Command Decorator Pattern

### Full decorator signature

```python
@commandHandlerV2(
    commands=("cmd_name",),           # command without /
    shortDescription="- short desc",  # shown in /help list
    helpMessage="Full help text",     # shown in /help cmd_name
    visibility={CommandPermission.DEFAULT},   # who sees it in /help
    availableFor={CommandPermission.DEFAULT}, # who can run it
    helpOrder=CommandHandlerOrder.NORMAL,
    category=CommandCategory.TOOLS,   # permission category
)
async def myCommandMethod(
    self,
    ensuredMessage: EnsuredMessage,
    command: str,
    args: str,
    updateObj: UpdateObjectType,
    typingManager: Optional[TypingManager],
) -> None:
    """Handle /mycommand, dood!

    Args:
        ensuredMessage: The command message
        command: Command name without slash
        args: Arguments string after command
        updateObj: Raw update object from platform
        typingManager: Optional typing indicator manager
    """
```

### `CommandPermission` values

| Value | Who it is |
|---|---|
| `DEFAULT` | All users |
| `ADMIN` | Chat admins |
| `BOT_OWNER` | Bot owner from config |
| `DEVELOPER` | Dev accounts |

### `CommandCategory` values

| Value | Purpose |
|---|---|
| `TOOLS` | Utility/tool commands |
| `AI` | AI/LLM commands |
| `ADMIN` | Admin management |
| `INFO` | Information commands |

### `CommandHandlerOrder` values

| Value | Purpose |
|---|---|
| `NORMAL` | Standard position in `/help` |
| `FIRST` | Shown at top of `/help` |
| `LAST` | Shown at bottom of `/help` |

---

## 5. Registering Handlers in HandlersManager

**File:** [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py:249)

```python
# At top of file, add import:
from .my_handler import MyNewHandler

# In HandlersManager.__init__(), add to self.handlers list:
self.handlers: List[HandlerTuple] = [
    # ... existing handlers ...
    (MyNewHandler(configManager, database, llmManager, botProvider), HandlerParallelism.PARALLEL),
    # LLMMessageHandler MUST stay last!
    (LLMMessageHandler(configManager, database, llmManager, botProvider), HandlerParallelism.SEQUENTIAL),
]
```

### Conditional registration (for optional features)

```python
# CORRECT — conditional registration, dood!
if self.configManager.getOpenWeatherMapConfig().get("enabled", False):
    self.handlers.append(
        (WeatherHandler(configManager, database, llmManager, botProvider), HandlerParallelism.PARALLEL)
    )
```

---

## 6. Handler Chain Order

**CRITICAL ORDER RULES:**
- `MessagePreprocessorHandler` — **MUST BE FIRST**
- `SpamHandler` — **MUST BE SECOND**
- `LLMMessageHandler` — **MUST BE LAST**

Full chain:
1. `MessagePreprocessorHandler` — SEQUENTIAL — saves message + media
2. `SpamHandler` — SEQUENTIAL — spam check before all others
3. `ConfigureCommandHandler` — PARALLEL — settings config
4. `SummarizationHandler` — PARALLEL — summarization
5. `UserDataHandler` — PARALLEL — user data
6. `DevCommandsHandler` — PARALLEL — debug commands
7. `MediaHandler` — PARALLEL — media processing
8. `CommonHandler` — PARALLEL — standard commands
9. `HelpHandler` — PARALLEL — help command
10. (Telegram only) `ReactOnUserMessageHandler` — PARALLEL
11. (Telegram only) `TopicManagerHandler` — PARALLEL
12. (if enabled) `WeatherHandler`, `YandexSearchHandler`, `ResenderHandler`, `DivinationHandler` — PARALLEL
13. (custom handlers) — PARALLEL
14. `LLMMessageHandler` — SEQUENTIAL — **MUST BE LAST**

---

## 7. HandlerResultStatus Reference

**File:** [`internal/bot/common/handlers/base.py:82`](../../internal/bot/common/handlers/base.py:82)

| Status | Meaning | Chain effect |
|---|---|---|
| `FINAL` | Success, handler fully processed message | **Stops** chain |
| `SKIPPED` | This handler does not apply | Continues |
| `NEXT` | Processed but continue | Continues |
| `ERROR` | Recoverable error occurred | Continues |
| `FATAL` | Unrecoverable error | **Stops** chain |

**Usage guidance:**
- Return `SKIPPED` when message is not relevant to this handler (most common)
- Return `FINAL` when you've fully handled the message and no other handler should run
- Return `NEXT` when you've done some work but want subsequent handlers to also process it
- Return `ERROR` for recoverable errors (logged, chain continues)
- Return `FATAL` only for critical unrecoverable errors

---

## See Also

- [`index.md`](index.md) — Project overview, mandatory rules
- [`architecture.md`](architecture.md) — Handler chain ADR, singleton services
- [`database.md`](database.md) — Using `self.db` in handlers
- [`services.md`](services.md) — Using `CacheService`, `QueueService`, `LLMService` from handlers
- [`testing.md`](testing.md) — Writing handler tests with fixtures
- [`tasks.md`](tasks.md) — Step-by-step: "add a new bot command" decision tree

---

*This guide is auto-maintained and should be updated whenever significant handler changes are made, dood!*  
*Last updated: 2026-04-18, dood!*
