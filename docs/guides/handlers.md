---
category: guide
---

# Handler System

How incoming messages flow through the handler pipeline, and how to create, register, and test new handlers.

## 6. Handler System

The handler system is the core of message processing All incoming messages go through a pipeline of handlers managed by [`HandlersManager`](/internal/bot/common/handlers/manager.py:382)

### Handler Lifecycle

```
1. HandlersManager.__init__() is called during bot startup
2. Built-in handlers are registered in order:
   - MessagePreprocessorHandler (always SEQUENTIAL, first)
   - SpamHandler (always SEQUENTIAL, second)
   - ConfigureCommandHandler, SummarizationHandler, UserMemoriesHandler,
     DevCommandsHandler, MediaHandler, CommonHandler, HelpHandler
   - Platform-specific handlers (Telegram-only)
   - Config-gated handlers: WeatherHandler (if enabled),
     YandexSearchHandler (if enabled), ResenderHandler (if enabled),
     DivinationHandler (if divination.enabled), SandboxHandler (if sandbox.enabled),
     ChatSearchHandler (if search-history.enabled)
   - Custom handlers via CustomHandlerLoader.loadAll() (if custom-handlers.enabled)
3. LLMMessageHandler is registered last (always SEQUENTIAL)
4. Messages flow through handlers in the specified order
```

```
Incoming Message
       │
       ▼
  HandlersManager.handleMessage()
       │
       ▼
  [MessagePreprocessorHandler] ← SEQUENTIAL (always runs first)
       │ saves message to DB, preprocesses text
       ▼
  [SpamHandler] ← SEQUENTIAL (runs second)
       │ checks for spam, may block further processing
       ▼
   [All other handlers] ← PARALLEL (run concurrently)
        │
        ├── ConfigureCommandHandler
        ├── SummarizationHandler
        ├── UserMemoriesHandler
        ├── DevCommandsHandler
        ├── MediaHandler
        ├── CommonHandler
         ├── HelpHandler
         ├── DeleteFromUserMessageHandler (Telegram only)
         ├── ReactOnUserMessageHandler (Telegram only)
         ├── TopicManagerHandler (Telegram only)
        ├── WeatherHandler (if enabled)
        ├── YandexSearchHandler (if enabled)
        ├── ResenderHandler (if enabled)
        ├── DivinationHandler (if enabled)
        ├── SandboxHandler (if enabled)
        ├── ChatSearchHandler (if enabled)
        ├── [custom handlers via CustomHandlerLoader]
        │
        ▼
   [LLMMessageHandler] ← SEQUENTIAL (always runs last)
```

### HandlerResultStatus

Each handler returns a [`HandlerResultStatus`](/internal/bot/common/handlers/base.py:82) to signal how processing should continue

```python
class HandlerResultStatus(Enum):
    FINAL = "final"    # Handled, stop processing (e.g., spam deleted)
    SKIPPED = "skipped" # Not applicable, continue to next handler
    NEXT = "next"      # Processed but continue to next handler
    ERROR = "error"    # Error occurred, but continue anyway
    FATAL = "fatal"    # Fatal error, stop all processing immediately
```

### HandlerParallelism

```python
class HandlerParallelism(IntEnum):
    SEQUENTIAL = auto()  # Run one at a time, wait for result
    PARALLEL = auto()    # Run concurrently with other PARALLEL handlers
```

### BaseBotHandler

All handlers inherit from [`BaseBotHandler`](/internal/bot/common/handlers/base.py:110) This base class provides:

- `self.db` — [`Database`](/internal/database/database.py) instance
- `self.llmService` — [`LLMService`](/internal/services/llm/service.py) instance (access LLMManager via `self.llmService.getLLMManager()`)
- `self.cache` — [`CacheService`](/internal/services/cache/service.py:88) instance
- `self.queueService` — [`QueueService`](/internal/services/queue_service/service.py) instance
- `self.storage` — [`StorageService`](/internal/services/storage/service.py) instance
- `self.configManager` — [`ConfigManager`](/internal/config/manager.py:59) instance
- `self.config` — raw bot config dict
- `self.botProvider` — [`BotProvider`](/internal/bot/models/enums.py) enum

Key methods from [`BaseBotHandler`](/internal/bot/common/handlers/base.py:110):

```python
# Get merged chat settings (with defaults)
settings = self.getChatSettings(chatId=123)

# Send a message back to the user
await self.sendMessage(ensuredMessage, messageText="Hello")

# Check if user is a bot admin
isAdmin = await self.isAdmin(ensuredMessage)

# Check if user is a bot owner
isOwner = self.isBotOwner(ensuredMessage.sender)

# Process media with LLM
mediaInfo = await self._processMediaV2(ensuredMessage, prompt="Describe this")
```

### Command Handler Decorator

Use the `@commandHandlerV2` decorator to register a method as a bot command handler

```python
from internal.bot.models import (
    commandHandlerV2,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
)

@commandHandlerV2(
    commands=("mycommand", "mc"),           # Command names (with or without /)
    shortDescription="- short description",  # Shown in /help list
    helpMessage="Full help text for this command",
    visibility={CommandPermission.DEFAULT},   # Who sees it in /help
    availableFor={CommandPermission.DEFAULT}, # Who can use it
    helpOrder=CommandHandlerOrder.NORMAL,
    category=CommandCategory.TOOLS,
)
async def myCommandHandler(
    self,
    ensuredMessage: EnsuredMessage,
    command: str,
    args: str,
    updateObj: UpdateObjectType,
    typingManager: Optional[TypingManager],
) -> None:
    await self.sendMessage(ensuredMessage, messageText="Command result")
```

### Available Handler List

| Handler | File | Description |
|---|---|---|
| `MessagePreprocessorHandler` | [`message_preprocessor.py`](/internal/bot/common/handlers/message_preprocessor.py) | Save message to DB, preprocess text |
| `SpamHandler` | [`spam.py`](/internal/bot/common/handlers/spam.py) | ML spam detection + user management |
| `ConfigureCommandHandler` | [`configure.py`](/internal/bot/common/handlers/configure.py) | `/configure` settings wizard |
| `SummarizationHandler` | [`summarization.py`](/internal/bot/common/handlers/summarization.py) | `/summarize` chat history |
| `UserMemoriesHandler` | [`user_memories.py`](/internal/bot/common/handlers/user_memories.py) | User memories management |
| `DevCommandsHandler` | [`dev_commands.py`](/internal/bot/common/handlers/dev_commands.py) | Developer/admin commands |
| `MediaHandler` | [`media.py`](/internal/bot/common/handlers/media.py) | Image/file/sticker processing |
| `CommonHandler` | [`common.py`](/internal/bot/common/handlers/common.py) | Shared command handling |
| `HelpHandler` | [`help_command.py`](/internal/bot/common/handlers/help_command.py) | `/help` command |
| `DeleteFromUserMessageHandler` | [`delete_from_user.py`](/internal/bot/common/handlers/delete_from_user.py) | Delete messages matching user-triggered criteria (Telegram only; runs before reaction) |
| `ReactOnUserMessageHandler` | [`react_on_user.py`](/internal/bot/common/handlers/react_on_user.py) | User join/leave reactions |
| `TopicManagerHandler` | [`topic_manager.py`](/internal/bot/common/handlers/topic_manager.py) | Forum topic management |
| `WeatherHandler` | [`weather.py`](/internal/bot/common/handlers/weather.py) | Weather query handler |
| `YandexSearchHandler` | [`yandex_search.py`](/internal/bot/common/handlers/yandex_search.py) | Web search handler |
| `ResenderHandler` | [`resender.py`](/internal/bot/common/handlers/resender.py) | Message forwarding |
| `DivinationHandler` | [`divination.py`](/internal/bot/common/handlers/divination.py) | `/taro` and `/runes` divination commands |
| `SandboxHandler` | [`sandbox.py`](/internal/bot/common/handlers/sandbox.py) | Sandboxed code execution (if sandbox.enabled) |
| `ChatSearchHandler` | [`chat_search.py`](/internal/bot/common/handlers/chat_search.py) | `/search` command and message search LLM tools (if search-history.enabled) |
| `LLMMessageHandler` | [`llm_messages.py`](/internal/bot/common/handlers/llm_messages.py) | Main AI conversation handler |

### How to Create a New Handler

See [`example_custom_handler.py`](/internal/bot/common/handlers/example_custom_handler.py) for a complete working example

**Step 1**: Create your handler class in a new file

```python
# internal/bot/common/handlers/my_handler.py
"""My new handler module"""

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
    """My new handler that does cool things"""

    def __init__(
        self,
        *,
        configManager: ConfigManager,
        database: Database,
        botProvider: BotProvider,
    ):
        """Initialize my handler"""
        super().__init__(
            configManager=configManager,
            database=database,
            botProvider=botProvider,
        )

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """Process incoming messages"""
        # Return SKIPPED if this handler doesn't apply to this message
        if not self._shouldHandle(ensuredMessage):
            return HandlerResultStatus.SKIPPED

        # Do your work here...
        await self.sendMessage(ensuredMessage, messageText="I handled it")
        return HandlerResultStatus.FINAL  # Stop further processing

    def _shouldHandle(self, ensuredMessage: EnsuredMessage) -> bool:
        """Check if this handler applies to the message"""
        return True  # Handle everything for now

    @commandHandlerV2(
        commands=("mycmd",),
        shortDescription="- my command",
        helpMessage="Does something cool",
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
        """Handle /mycmd command"""
        await self.sendMessage(
            ensuredMessage,
            messageText="My command result",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
```

**Step 2**: Register the handler in [`HandlersManager`](/internal/bot/common/handlers/manager.py:478)

```python
# In internal/bot/common/handlers/manager.py, add import:
from .my_handler import MyNewHandler

# Then add to self.handlers list in __init__:
(MyNewHandler(configManager=configManager, database=database, botProvider=botProvider), HandlerParallelism.PARALLEL),
```

**Alternatively**, use the **custom handler loader** for out-of-tree handlers Configure in TOML:

```toml
[custom-handlers]
enabled = true

[[custom-handlers.handlers]]
id = "my-handler"
module = "path.to.my_handler"
class = "MyNewHandler"
parallelism = "parallel"
order = 10
enabled = true
```

See [Custom Handler Modules design](../design/custom-modules-design.md) for the complete custom handler loading system design, and `internal/bot/common/handlers/module_loader.py` for the live `CustomHandlerLoader` implementation.

### 6.1 Divination Layout Discovery

The divination handler includes a layout discovery feature that can automatically find and learn new tarot/runes layouts using LLM with web search capability This allows users to request layouts that aren't predefined in the system

#### Enabling Discovery

Enable discovery in your config with the `discovery-enabled` setting

```toml
[divination]
discovery-enabled = true
```

When enabled, unknown layouts in `/taro` or `/runes` commands trigger an automatic discovery process instead of returning an error

#### Discovery Process

The layout discovery follows a 4-step process

**Step 1 - Cache Check**: The handler first checks if the requested layout is already cached in the database (from a previous discovery attempt)

**Step 2 - LLM Discovery (Web Search)**: If not cached, the handler calls `LLMService.generateText(tools=True)` with web search enabled

- The LLM automatically uses the web_search tool to find information about the layout
- Returns a detailed description of the layout including card positions, meanings, and interpretation guidelines
- Uses the `divination-discovery-info-prompt` and `divination-discovery-system-prompt` settings

**Step 3 - LLM Structuring**: The handler then calls `LLMService.generateStructured()` to parse the description into a structured format

- Passes the description and an expected JSON schema
- Returns a validated dictionary with the layout structure
- Uses the `divination-discovery-structure-prompt` setting

**Step 4 - Validation & Save**: The handler validates the structured dictionary and saves it to the database

- On success: Saves the complete layout definition for future reuse
- On failure: Saves a negative cache entry to prevent repeated failed attempts for 24 hours

#### Customizing Discovery Prompts

You can customize the discovery process by editing the discovery prompts in chat settings These can be configured globally in `configs/00-defaults/bot-defaults.toml` or per-chat via the `/configure` command

```toml
[bot.defaults]
# System instruction for both discovery LLM calls
divination-discovery-system-prompt = "You are an expert tarot researcher..."

# Prompt for the first LLM call (with web search enabled)
divination-discovery-info-prompt = "Find complete information about the 'Celtic Cross' tarot reading layout..."

# Prompt for the second LLM call (structured output)
divination-discovery-structure-prompt = "Parse this description into a structured layout JSON..."
```

The system prompt applies to both LLM calls, while the info and structure prompts are specific to each step

#### Testing Discovery

The discovery feature has comprehensive test coverage in:
- [`tests/bot/test_divination_discovery.py`](/tests/bot/test_divination_discovery.py) — Full discovery workflow tests

Tests cover:
- Successful layout discovery with valid web search results
- Failed discovery with invalid/unrecognized layouts
- Cache hit scenarios (reusing previously discovered layouts)
- Negative cache (preventing repeated failures)
- Prompt customization and validation

#### Layout Database Table

Discovered layouts are stored in the `divination_layouts` table (added by migration 015)

```toml
[divination.layouts.celtic-cross]
name = "Celtic Cross"
description = "A classic 10-card spread for detailed readings..."
positions = ["Significator", "Situation", "Challenge", ...]
```

---

### 14.1 Adding a New Handler

1. **Create the handler file** See [Section 6 - Creating a New Handler](#how-to-create-a-new-handler) for the complete template.

2. **Register in [`HandlersManager`](/internal/bot/common/handlers/manager.py:478)**

```python
# In internal/bot/common/handlers/manager.py

# Add import at top
from .my_handler import MyNewHandler

# In HandlersManager.__init__, add to self.handlers list:
(MyNewHandler(configManager=configManager, database=database, botProvider=botProvider), HandlerParallelism.PARALLEL),
```

3. **Write tests** in `tests/bot/` or alongside the handler file

4. **Run the quality pipeline**

```bash
make format lint
make test
```
