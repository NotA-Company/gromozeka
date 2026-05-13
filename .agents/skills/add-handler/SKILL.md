---
name: add-handler
description: >
  End-to-end recipe for adding a new bot handler to Gromozeka. Covers file
  location (always `internal/bot/common/handlers/` for platform-agnostic
  handlers), extending `BaseBotHandler`, implementing `newMessageHandler` with
  the correct `HandlerResultStatus`, registering in `HandlersManager` with the
  critical "LLMMessageHandler must stay last" invariant, conditional
  registration for config-gated features, platform-agnostic message sending,
  test scaffolding with real `EnsuredMessage` objects, and documentation sync.
  Use for new bot commands, new message interceptors, new reactive handlers.
  Triggers: add handler, new handler, add bot command, new /command, intercept
  messages, new bot feature.
---

# Add a Bot Handler

## When to use

- Adding a new `/command` to the bot (whether Telegram, Max, or both).
- Adding a handler that reacts to messages matching some predicate (media type, text pattern, mention, etc.).
- Adding a handler that processes chat-member events, callbacks, or other non-text updates.

## When NOT to use

- The new command logically belongs on an **existing** handler — add a method there instead.
- The feature is purely platform-specific UI (inline keyboards, sticker sets) with no shared logic — platform-specific code may live in `internal/bot/telegram/` or `internal/bot/max/`, but the common path is almost always `internal/bot/common/handlers/`.
- You're loading handlers dynamically via config — see [`docs/custom-modules-design.md`](../../../docs/custom-modules-design.md) instead of writing a built-in.

## Prerequisites

Load `read-project-docs` first; specifically:

- [`docs/llm/handlers.md`](../../../docs/llm/handlers.md) — handler system, command decorator pattern, registration.
- [`docs/llm/services.md`](../../../docs/llm/services.md) — for service access patterns if the handler uses DB/cache/LLM.
- [`AGENTS.md`](../../../AGENTS.md) — naming rules, handler ordering invariant.

## Step 1 — Create the handler file

Path: **`internal/bot/common/handlers/<name>.py`** (always common/ for platform-agnostic handlers).

Skeleton:

```python
"""<Module docstring — what this handler does and when it fires>."""

import logging
from typing import Optional

from internal.bot.common.handlers.base import BaseBotHandler, HandlerResultStatus
from internal.bot.common.models import UpdateObjectType
from internal.bot.models import BotProvider, EnsuredMessage, MessageCategory
from internal.config.manager import ConfigManager
from internal.database import Database

logger = logging.getLogger(__name__)


class MyHandler(BaseBotHandler):
    """<Class docstring — responsibilities and any non-obvious behavior.>

    Attributes:
        configManager: Inherited from BaseBotHandler.
        db: Inherited from BaseBotHandler.
    """

    def __init__(
        self,
        *,
        configManager: ConfigManager,
        database: Database,
        botProvider: BotProvider,
    ):
        """Initialize the handler.

        Args:
            configManager: Configuration manager.
            database: Database wrapper.
            botProvider: Which bot platform this handler runs on.
        """
        super().__init__(configManager=configManager, database=database, botProvider=botProvider)
        # handler-specific state goes here

    async def newMessageHandler(
        self,
        ensuredMessage: EnsuredMessage,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        """Process an incoming message.

        Args:
            ensuredMessage: The validated message.
            updateObj: The raw update object from the platform.

        Returns:
            HandlerResultStatus indicating whether to continue the chain.
        """
        if not self._shouldHandle(ensuredMessage):
            return HandlerResultStatus.SKIPPED

        # ...do work, call self.sendMessage(...), etc.

        return HandlerResultStatus.NEXT  # or FINAL — see Step 3

    def _shouldHandle(self, ensuredMessage: EnsuredMessage) -> bool:
        """Quick predicate to reject messages this handler doesn't care about."""
        return ...
```

## Step 2 — Use the inherited services, not `self.services.*`

[`BaseBotHandler.__init__`](../../../internal/bot/common/handlers/base.py) populates these attributes directly — there is **no** `self.services` dict:

| Attribute | Type | Source |
|---|---|---|
| `self.configManager` | `ConfigManager` | constructor arg |
| `self.config` | `dict` | `configManager.getBotConfig()` |
| `self.db` | `Database` | constructor arg |
| `self.botProvider` | `BotProvider` | constructor arg |
| `self.cache` | `CacheService` | `CacheService.getInstance()` |
| `self.queueService` | `QueueService` | `QueueService.getInstance()` |
| `self.storage` | `StorageService` | `StorageService.getInstance()` |
| `self.llmService` | `LLMService` | `LLMService.getInstance()` |

Access them directly: `await self.llmService.generateText(...)`, `await self.db.getChatSettings(...)`, `await self.cache.get(...)`.

## Step 3 — Return the correct `HandlerResultStatus`

| Status | Meaning | When to return |
|---|---|---|
| `SKIPPED` | Handler didn't match / didn't act | Message isn't for this handler; let others try |
| `NEXT` | Handler acted, keep running the chain | Side-effectful (e.g. preprocess, log, react) but downstream handlers may still apply |
| `FINAL` | Handler fully handled it, stop the chain | Terminal for this message — no downstream handler should run |
| `ERROR` | Handler errored but chain can continue | Non-fatal failure; recoverable |
| `FATAL` | Stop everything | Unrecoverable — rarely correct in application code |

Common footgun: returning `FINAL` for a preprocess-style handler will suppress `LLMMessageHandler` and others. Default to `NEXT` unless you truly own the message end-to-end.

## Step 4 — Command methods (if the handler owns `/commands`)

For Telegram-style slash commands, define decorated methods on the handler per the pattern in [`docs/llm/handlers.md`](../../../docs/llm/handlers.md) (`@commandHandlerV2`). Keep `newMessageHandler` for non-command reactive logic; commands are dispatched separately through `getCommandHandlersV2()`.

Copy the decorator shape from an existing handler (e.g. [`internal/bot/common/handlers/common.py`](../../../internal/bot/common/handlers/common.py) or [`divination.py`](../../../internal/bot/common/handlers/divination.py)) rather than rolling your own.

## Step 5 — Send messages the platform-agnostic way

❌ **Never** call `tgBot.send_message(...)` or `maxBot.sendMessage(...)` directly — that couples the handler to a single platform.

✅ Use `BaseBotHandler.sendMessage()`:

```python
await self.sendMessage(
    ensuredMessage,
    messageText="your reply",
    messageCategory=MessageCategory.BOT,
)
```

Also remember: message IDs are `MessageId` instances wrapping `int | str` (Telegram = int, Max = str). Never assume plain `int` — use `.asInt()` for Telegram API calls, `.asStr()` for Max/SQL.

## Step 6 — Register the handler

Edit [`internal/bot/common/handlers/manager.py`](../../../internal/bot/common/handlers/manager.py) around line 432 (`self.handlers: List[HandlerTuple] = [...]`).

Two invariants:

1. **`LLMMessageHandler` must stay last** — it's the catch-all. Registration is at `manager.py:502` and must remain the final `.append(...)` call.
2. **Gate feature-flagged handlers on a config predicate.** Look at `WeatherHandler` / `YandexSearchHandler` / `ResenderHandler` / `DivinationHandler` around `manager.py:475–490` for the pattern:

```python
if self.configManager.get("my_feature", {}).get("enabled", False):
    self.handlers.append(
        (MyHandler(configManager=configManager, database=database, botProvider=botProvider), HandlerParallelism.PARALLEL)
    )
```

Handlers listed in the initial `self.handlers = [...]` block are always-on (e.g. `MessagePreprocessorHandler`, `SpamHandler`, `CommonHandler`). Decide which bucket your handler belongs in.

Parallelism choice:

- `HandlerParallelism.SEQUENTIAL` — must finish before the next message in the chat is processed. Use only when ordering matters (preprocessing, spam, message persistence, LLM replies).
- `HandlerParallelism.PARALLEL` — can overlap with other parallel handlers on the same chat. Default for most new handlers.

## Step 7 — Tests

Create `tests/bot/test_<handler_name>.py` (the test tree mirrors the production tree loosely).

Key rules from [`docs/llm/testing.md`](../../../docs/llm/testing.md) and [`docs/llm/tasks.md`](../../../docs/llm/tasks.md) §4.4:

- `asyncio_mode = "auto"` — write `async def test_…` with no `@pytest.mark.asyncio`.
- Build real `EnsuredMessage` instances — **never** raw dicts. Import the type from `internal.bot.models`.
- Reuse fixtures from [`tests/conftest.py`](../../../tests/conftest.py): `testDatabase`, `mockBot`, `mockConfigManager`, etc.
- The `resetLlmServiceSingleton` autouse fixture already clears `LLMService`. For `CacheService`, `QueueService`, `StorageService`, `RateLimiterManager` — if your handler pokes them in a stateful way, reset `_instance = None` in a fixture.
- API-touching logic should exercise golden data under `tests/fixtures/`, not live APIs.

## Step 8 — Documentation

Update [`docs/llm/handlers.md`](../../../docs/llm/handlers.md) with your handler's entry: purpose, commands it owns (if any), parallelism, any conditional-registration predicate.

Update [`docs/llm/index.md`](../../../docs/llm/index.md) §4.5 **only** if the aggregate summary there is now misleading (e.g. "21+ handlers" count needs bumping, or you've added a flagship handler worth naming explicitly).

If the handler uses a new config section, load the `update-project-docs` skill for the full matrix — you'll also touch `docs/llm/configuration.md` and `configs/00-defaults/*.toml`.

## Step 9 — Quality gates

Load the `run-quality-gates` skill. Short form:

```bash
make format lint
make test
```

## Checklist

- [ ] Handler file at `internal/bot/common/handlers/<name>.py`.
- [ ] Class extends `BaseBotHandler`, constructor forwards the three standard keyword args to `super().__init__(...)`.
- [ ] Module, class, and every method/function have docstrings with `Args:` / `Returns:`.
- [ ] All params and returns have type hints.
- [ ] camelCase for variables/functions/methods, PascalCase for the class, UPPER_CASE for constants.
- [ ] `newMessageHandler` returns `SKIPPED` when the handler doesn't care, `NEXT` when it acts but others should continue, `FINAL` only when it owns the message.
- [ ] Messages sent via `self.sendMessage(...)`, never via raw `tgBot` / `maxBot`.
- [ ] No assumption that `messageId` is plain `int` — use `MessageId` class with `.asInt()`/`.asStr()` as needed.
- [ ] Registered in `HandlersManager` at the right position; `LLMMessageHandler` remains last.
- [ ] Config-gated handlers check their `enabled` flag via `configManager`.
- [ ] Tests in `tests/bot/` using real `EnsuredMessage` instances and shared fixtures.
- [ ] `docs/llm/handlers.md` updated.
- [ ] `make format lint && make test` green.
