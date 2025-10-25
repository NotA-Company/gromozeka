# Command Handler Decorator Design

## Overview

This document describes the design and implementation of a decorator-based system for automatically registering Telegram bot command handlers, dood!

## Current Implementation Analysis

### Current Approach

Currently, command handlers are registered manually in the [`getCommandHandlers()`](internal/bot/handlers.py:159) method:

```python
def getCommandHandlers(self) -> Sequence[CommandHandlerInfo]:
    return [
        CommandHandlerInfo(
            commands=("start",),
            shortDescription="Start bot interaction",
            helpMessage=": Начать работу с ботом.",
            categories={CommandCategory.PRIVATE},
            handler=self.start_command,
        ),
        # ... more handlers
    ]
```

### Problems with Current Approach

1. **Manual Registration**: Each handler must be manually added to the list
2. **Duplication**: Handler metadata is separated from the handler implementation
3. **Error-Prone**: Easy to forget to register a new handler
4. **Maintenance**: Changes to handler metadata require editing multiple locations
5. **No Type Safety**: No compile-time checking that handlers are registered

## Proposed Solution: Decorator-Based Registration

### Design Goals

1. **Automatic Registration**: Handlers register themselves via decorator
2. **Co-location**: Metadata lives with the handler implementation
3. **Type Safety**: Leverage Python type hints
4. **Backward Compatible**: Existing code continues to work
5. **Flexible**: Support various handler configurations

### Architecture

```mermaid
graph TD
    A[Command Handler Method] --> B[@command_handler Decorator]
    B --> C[CommandRegistry]
    C --> D[getCommandHandlers Method]
    D --> E[Application Setup]
```

## Implementation Design

### 1. Command Registry Class

A singleton registry to store all registered command handlers:

```python
class CommandRegistry:
    """Registry for command handlers, dood!"""
    
    _instance = None
    _handlers: List[CommandHandlerInfo] = []
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._handlers = []
        return cls._instance
    
    def register(self, handler_info: CommandHandlerInfo) -> None:
        """Register a command handler."""
        self._handlers.append(handler_info)
    
    def getHandlers(self) -> Sequence[CommandHandlerInfo]:
        """Get all registered handlers."""
        return self._handlers.copy()
    
    def clear(self) -> None:
        """Clear all registered handlers (useful for testing)."""
        self._handlers.clear()
```

### 2. Decorator Implementation

```python
def commandHandler(
    commands: Sequence[str],
    shortDescription: str,
    helpMessage: str,
    categories: Optional[Set[CommandCategory]] = None,
) -> Callable:
    """
    Decorator to register a command handler, dood!
    
    Args:
        commands: Tuple of command names (without /)
        shortDescription: Short description for command list
        helpMessage: Detailed help message
        categories: Set of CommandCategory values
    
    Example:
        @commandHandler(
            commands=("start",),
            shortDescription="Start bot interaction",
            helpMessage=": Начать работу с ботом.",
            categories={CommandCategory.PRIVATE}
        )
        async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            # Implementation here
            pass
    """
    if categories is None:
        categories = {CommandCategory.DEFAULT}
    
    def decorator(func: Callable) -> Callable:
        # Register the handler
        registry = CommandRegistry()
        handler_info = CommandHandlerInfo(
            commands=commands,
            shortDescription=shortDescription,
            helpMessage=helpMessage,
            categories=categories,
            handler=func,
        )
        registry.register(handler_info)
        
        # Return the original function unchanged
        return func
    
    return decorator
```

### 3. Integration with BotHandlers Class

Modify the [`BotHandlers`](internal/bot/handlers.py:88) class:

```python
class BotHandlers:
    """Contains all bot command and message handlers."""
    
    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        # ... existing initialization code ...
        
        # Bind registered handlers to this instance
        self._bindHandlers()
    
    def _bindHandlers(self) -> None:
        """Bind registered handlers to this instance, dood!"""
        registry = CommandRegistry()
        for handler_info in registry.getHandlers():
            # Replace the unbound handler with a bound method
            original_handler = handler_info.handler
            if hasattr(original_handler, '__self__'):
                # Already bound, skip
                continue
            # Bind the handler to this instance
            handler_info.handler = original_handler.__get__(self, type(self))
    
    def getCommandHandlers(self) -> Sequence[CommandHandlerInfo]:
        """Get all registered command handlers."""
        return CommandRegistry().getHandlers()
```

### 4. Usage Examples

#### Basic Command Handler

```python
@commandHandler(
    commands=("start",),
    shortDescription="Start bot interaction",
    helpMessage=": Начать работу с ботом.",
    categories={CommandCategory.PRIVATE}
)
async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    user = update.effective_user
    if not user or not update.message:
        logger.error("User or message undefined")
        return
    
    welcome_message = (
        f"Привет! {user.first_name}! 👋\n\n"
        "Я Громозека: лучший бот для Телеграма, что когда либо был, есть или будет.\n\n"
        "Что бы узнать, что я умею, можешь отправить команду /help"
    )
    
    await update.message.reply_text(welcome_message)
    logger.info(f"User {user.id} ({user.username}) started the bot")
```

#### Multiple Commands

```python
@commandHandler(
    commands=("learn_spam", "learn_ham"),
    shortDescription="[<chatId>] - learn answered message (or quote) as spam/ham for given chat",
    helpMessage=" `[<chatId>]`: Обучить баесовский фильтр на указанным сообщении (или цитате) как спам/не-спам.",
    categories={CommandCategory.PRIVATE}
)
async def learn_spam_ham_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /learn_spam and /learn_ham commands."""
    # Implementation here
    pass
```

#### Hidden Command

```python
@commandHandler(
    commands=("test",),
    shortDescription="<Test suite> [<args>] - Run some tests",
    helpMessage=" `<test_name>` `[<test_args>]``: Запустить тест (используется для тестирования).",
    categories={CommandCategory.BOT_OWNER, CommandCategory.HIDDEN}
)
async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /test command."""
    # Implementation here
    pass
```

## Migration Strategy

### Phase 1: Add Decorator Support (Non-Breaking)

1. Add [`CommandRegistry`](internal/bot/handlers.py:88) class to [`internal/bot/models.py`](internal/bot/models.py:1)
2. Add [`commandHandler`](internal/bot/handlers.py:159) decorator function
3. Keep existing [`getCommandHandlers()`](internal/bot/handlers.py:159) method working
4. Both systems work in parallel

### Phase 2: Gradual Migration

1. Add decorators to existing handlers one by one
2. Test each handler after decoration
3. Keep manual registration as fallback

### Phase 3: Complete Migration

1. Remove manual registration from [`getCommandHandlers()`](internal/bot/handlers.py:159)
2. Update [`getCommandHandlers()`](internal/bot/handlers.py:159) to use registry
3. Remove old code

### Example Migration

**Before:**
```python
def getCommandHandlers(self) -> Sequence[CommandHandlerInfo]:
    return [
        CommandHandlerInfo(
            commands=("start",),
            shortDescription="Start bot interaction",
            helpMessage=": Начать работу с ботом.",
            categories={CommandCategory.PRIVATE},
            handler=self.start_command,
        ),
    ]

async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Implementation
    pass
```

**After:**
```python
def getCommandHandlers(self) -> Sequence[CommandHandlerInfo]:
    return CommandRegistry().getHandlers()

@commandHandler(
    commands=("start",),
    shortDescription="Start bot interaction",
    helpMessage=": Начать работу с ботом.",
    categories={CommandCategory.PRIVATE}
)
async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Implementation (unchanged)
    pass
```

## Advanced Features

### 1. Conditional Registration

```python
def commandHandler(
    commands: Sequence[str],
    shortDescription: str,
    helpMessage: str,
    categories: Optional[Set[CommandCategory]] = None,
    enabled: bool = True,  # New parameter
) -> Callable:
    """Decorator with conditional registration."""
    
    def decorator(func: Callable) -> Callable:
        if enabled:
            registry = CommandRegistry()
            handler_info = CommandHandlerInfo(
                commands=commands,
                shortDescription=shortDescription,
                helpMessage=helpMessage,
                categories=categories or {CommandCategory.DEFAULT},
                handler=func,
            )
            registry.register(handler_info)
        return func
    
    return decorator
```

### 2. Handler Validation

```python
def commandHandler(
    commands: Sequence[str],
    shortDescription: str,
    helpMessage: str,
    categories: Optional[Set[CommandCategory]] = None,
) -> Callable:
    """Decorator with validation."""
    
    def decorator(func: Callable) -> Callable:
        # Validate handler signature
        import inspect
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        
        if len(params) < 3:
            raise ValueError(
                f"Handler {func.__name__} must have at least 3 parameters: "
                f"self, update, context"
            )
        
        # Register the handler
        registry = CommandRegistry()
        handler_info = CommandHandlerInfo(
            commands=commands,
            shortDescription=shortDescription,
            helpMessage=helpMessage,
            categories=categories or {CommandCategory.DEFAULT},
            handler=func,
        )
        registry.register(handler_info)
        
        return func
    
    return decorator
```

### 3. Handler Metadata Access

```python
def getHandlerMetadata(func: Callable) -> Optional[CommandHandlerInfo]:
    """Get metadata for a decorated handler."""
    registry = CommandRegistry()
    for handler_info in registry.getHandlers():
        if handler_info.handler == func:
            return handler_info
    return None
```

## Benefits

1. **Reduced Boilerplate**: No need to manually maintain handler list
2. **Better Organization**: Handler metadata lives with implementation
3. **Type Safety**: Decorator provides compile-time checking
4. **Easier Testing**: Can test individual handlers without full setup
5. **Discoverability**: Easy to find all handlers (just search for decorator)
6. **Flexibility**: Easy to add conditional registration or validation

## Considerations

1. **Import Order**: Handlers must be imported for decorators to execute
2. **Testing**: Need to clear registry between tests
3. **Debugging**: Stack traces may be slightly more complex
4. **Performance**: Minimal overhead (registration happens once at import)

## Testing Strategy

### Unit Tests

```python
def test_command_handler_decorator():
    """Test that decorator registers handlers correctly."""
    # Clear registry
    registry = CommandRegistry()
    registry.clear()
    
    # Define a test handler
    @commandHandler(
        commands=("test",),
        shortDescription="Test command",
        helpMessage="Test help",
        categories={CommandCategory.PRIVATE}
    )
    async def test_handler(self, update, context):
        pass
    
    # Verify registration
    handlers = registry.getHandlers()
    assert len(handlers) == 1
    assert handlers[0].commands == ("test",)
    assert handlers[0].shortDescription == "Test command"
```

### Integration Tests

```python
def test_bot_handlers_integration():
    """Test that BotHandlers correctly uses registered handlers."""
    bot_handlers = BotHandlers(config_manager, database, llm_manager)
    handlers = bot_handlers.getCommandHandlers()
    
    # Verify all expected handlers are present
    command_names = {cmd for h in handlers for cmd in h.commands}
    assert "start" in command_names
    assert "help" in command_names
    # ... etc
```

## Implementation Checklist

- [ ] Create [`CommandRegistry`](internal/bot/models.py:1) class in [`internal/bot/models.py`](internal/bot/models.py:1)
- [ ] Implement [`commandHandler`](internal/bot/handlers.py:159) decorator
- [ ] Add [`_bindHandlers()`](internal/bot/handlers.py:88) method to [`BotHandlers`](internal/bot/handlers.py:88)
- [ ] Update [`getCommandHandlers()`](internal/bot/handlers.py:159) to use registry
- [ ] Write unit tests for decorator
- [ ] Write integration tests
- [ ] Migrate one handler as proof of concept
- [ ] Document usage in README
- [ ] Migrate remaining handlers
- [ ] Remove old manual registration code

## Conclusion

The decorator-based approach provides a cleaner, more maintainable way to register command handlers. It reduces boilerplate, improves code organization, and makes the codebase easier to understand and extend, dood!

## References

- Current implementation: [`internal/bot/handlers.py:159`](internal/bot/handlers.py:159)
- Command models: [`internal/bot/models.py:150`](internal/bot/models.py:150)
- Python decorators: https://docs.python.org/3/glossary.html#term-decorator
- Telegram bot handlers: https://docs.python-telegram-bot.org/