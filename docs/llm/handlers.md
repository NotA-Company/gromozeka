# Gromozeka — Handler System

> **Audience:** LLM agents  
> **Purpose:** Complete guide to creating, modifying, and registering bot command handlers  
> **Self-contained:** Everything needed for handler work is here

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
| [`divination.py`](../../internal/bot/common/handlers/divination.py) | `DivinationHandler` | `/taro` & `/runes` readings (if `divination.enabled`) — includes layout discovery via LLM + web search |
| [`llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py) | `LLMMessageHandler` | **LAST** in chain; LLM responses |
| [`example_custom_handler.py`](../../internal/bot/common/handlers/example_custom_handler.py) | `ExampleCustomHandler` | Template for custom handlers |

**`DivinationHandler` — reply behavior by invocation path:**

- **Slash-command path** (`/taro`, `/runes`): the handler renders a **structured reply template** (`DIVINATION_REPLY_TEMPLATE` chat setting) containing the layout name, a numbered drawn-symbols block (with position, localized name, and reversal flag), and the LLM interpretation. This lets users verify the LLM didn't hallucinate any cards. Photo (if image generation succeeded) is sent as caption + image in one `sendMessage` call
- **LLM-tool path** (`do_tarot_reading` / `do_runes_reading`, `invoked_via = 'llm_tool'`): the handler returns the **bare LLM interpretation** in the JSON tool result (fields: `done`, `summary`, `imageGenerated`, `layout`, `draws`, `interpretation`) so the host LLM can incorporate it naturally — no text bot message is sent. Only the generated image (if `image-generation = true` and generation succeeded) is sent directly to the user with an empty caption. The template is NOT applied on this path.

### Layout Discovery (Multi-Tier Resolution)

When `divination discovery-enabled = true`, unknown layouts trigger automatic discovery:

**Resolution tiers (from highest to lowest priority):**

1. **Predefined layouts** in `lib/divination/layouts.py` (`TAROT_LAYOUTS`, `RUNES_LAYOUTS`)
2. **Cached layouts** from `divination_layouts` table (Database cache, includes negative cache for failed discoveries)
3. **LLM + Web Search discovery** (if enabled):
   - Call 1: `LLMService.generateText(tools=True)` with web search to find layout info
   - Call 2: `LLMService.generateStructured()` to parse into structured JSON schema
   - Save: Persist successful layouts to `divination_layouts` cache
   - Negative cache: Failed discoveries stored with `name_en=''`, `n_symbols=0` (24-hour TTL)

**Discovery prompts** (configured via chat settings):
- `divination-discovery-system-prompt` — System instruction for both LLM calls
- `divination-discovery-info-prompt` — Prompt for web search (first call)
- `divination-discovery-structure-prompt` — Prompt for structured JSON parsing (second call)

**Negative cache pattern:** Prevents repeated failed discovery attempts for the same non-existent layout. Stored as a special entry in `divination_layouts` with empty name and zero symbols.

### DevCommandsHandler Commands

Developer/debug commands available only to `BOT_OWNER` users.

#### `/llm_replay <model_name>`

- **Class:** `DevCommandsHandler` (`internal/bot/common/handlers/dev_commands.py`)
- **Permission:** `BOT_OWNER`
- **Description:** Replays an LLM conversation from an attached JSON log file through `LLMService.generateTextViaLLM` with all registered tools available. Useful for debugging prompts and LLM behavior with the same tool context as production.
- **Usage:** Send `/llm_replay <model_name>` with a JSON document attachment (or as a reply to a JSON document message). The model name must be a known model in the LLM configuration (e.g., `gpt-4o`, `openrouter/claude-haiku-4.5`).
- **Flow:**
  1. Validates the model name argument
  2. Downloads and parses the attached JSON file
  3. Reconstructs `ModelMessage` objects from the log's `request` array via `internal.services.llm.utils.reconstructMessages()`
  4. Calls `LLMService.generateTextViaLLM()` with the specified model, chat tool settings, and all registered tools
  5. Streams intermediate results back to chat via callback
  6. Reports final summary: model, status, token counts, tool calls, elapsed time
- **Related scripts:** `scripts/run_llm_debug_query.py` (CLI-based replay without tools), `scripts/convert_readable_to_llm_log.py` (YAML-to-JSON conversion)

---

## 2. Handler Creation Checklist

Step-by-step for adding a new bot command handler

### Step 1: Create handler file

**Path:** `internal/bot/common/handlers/my_handler.py`

Use the skeleton from [Section 3](#3-handler-skeleton-template)

### Step 2: Register handler in `HandlersManager`

**File:** [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py:249)

See [Section 5](#5-registering-handlers-in-handlersmanager) for registration code

### Step 3: Define commands with decorator

Use `@commandHandlerV2` — see [Section 4](#4-command-decorator-pattern)

### Step 4: Implement `newMessageHandler` (if needed)

Only implement if your handler reacts to non-command messages:
```python
async def newMessageHandler(
    self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
) -> HandlerResultStatus:
    """Process incoming messages

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

See [`testing.md`](testing.md) for test patterns

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
Module docstring describing what this handler does
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

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class MyNewHandler(BaseBotHandler):
    """Handler description

    Attributes:
        configManager: Configuration manager instance
        database: Database wrapper for persistence
        botProvider: Bot provider type
    """

    def __init__(
        self,
        *,
        configManager: ConfigManager,
        database: Database,
        botProvider: BotProvider,
    ):
        """Initialize handler

        Args:
            configManager: Configuration manager
            database: Database wrapper
            botProvider: Bot provider type
        """
        super().__init__(
            configManager=configManager,
            database=database,
            botProvider=botProvider,
        )

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """Process incoming messages

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
        helpMessage="Full help message explaining the command",
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
        """Handle /mycommand

        Args:
            ensuredMessage: The command message
            command: Command name (e.g. "mycommand")
            args: Arguments string after command
            updateObj: Raw update object
            typingManager: Optional typing indicator
        """
        await self.sendMessage(
            ensuredMessage,
            messageText="Response here",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
```

**Required imports for handler:** Always include all shown above. Additional imports as needed.

**Required patterns:**
- Inherit from `BaseBotHandler`
- Call `super().__init__()` with all three args
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
    """Handle /mycommand

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
| `UNSPECIFIED` | Default category for commands without specific categorization |
| `PRIVATE` | Commands for private chats only |
| `ADMIN` | Admin/configuration commands |
| `TOOLS` | Utility/tool commands (Web search, draw, weather, etc.) |
| `SPAM` | SPAM-related commands |
| `SPAM_ADMIN` | SPAM-related commands for admins |
| `TECHNICAL` | Technical/debug commands |

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
    (MyNewHandler(configManager=configManager, database=database, botProvider=botProvider), HandlerParallelism.PARALLEL),
    # LLMMessageHandler MUST stay last!
    (LLMMessageHandler(configManager=configManager, database=database, botProvider=botProvider), HandlerParallelism.SEQUENTIAL),
]
```

### Conditional registration (for optional features)

```python
# CORRECT — conditional registration
if self.configManager.getOpenWeatherMapConfig().get("enabled", False):
    self.handlers.append(
        (WeatherHandler(configManager=configManager, database=database, botProvider=botProvider), HandlerParallelism.PARALLEL)
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

*This guide is auto-maintained and should be updated whenever significant handler changes are made*  
*Last updated: 2026-05-15*
