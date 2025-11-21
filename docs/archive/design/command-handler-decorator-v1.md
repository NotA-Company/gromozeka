# Command Handler Decorator Design v1

## Overview

This document describes the design and implementation of a decorator-based system for automatically registering Telegram bot command handlers using instance-level handler collection, dood!

## Changes from v0

**Key Improvement**: Replaced global singleton registry with instance-level handler collection. This allows:
- Multiple handler classes to coexist independently
- Each class instance manages its own handlers
- Better scalability and separation of concerns
- No global state to manage

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

## Proposed Solution: Instance-Level Decorator Registration

### Design Goals

1. **Automatic Registration**: Handlers register themselves via decorator
2. **Co-location**: Metadata lives with the handler implementation
3. **Instance-Level**: Each class instance manages its own handlers
4. **Scalable**: Support multiple handler classes
5. **Type Safety**: Leverage Python type hints
6. **Backward Compatible**: Existing code continues to work
7. **No Global State**: Avoid singleton patterns

### Architecture

```mermaid
graph TD
    A[Command Handler Method] --> B[@commandHandler Decorator]
    B --> C[Attaches Metadata to Method]
    D[Class __init__] --> E[Discovers Decorated Methods]
    E --> F[Stores in _commandHandlers]
    F --> G[getCommandHandlers Method]
    G --> H[Application Setup]
    I[Multiple Handler Classes] --> G
```

## Implementation Design

### 1. Decorator Implementation

The decorator attaches metadata to methods without using global state:

```python
# Attribute name for storing handler metadata
_HANDLER_METADATA_ATTR = "_command_handler_info"

def commandHandler(
    commands: Sequence[str],
    shortDescription: str,
    helpMessage: str,
    categories: Optional[Set[CommandCategory]] = None,
) -> Callable:
    """
    Decorator to mark a method as a command handler, dood!
    
    This decorator attaches metadata to the method without registering it globally.
    The class instance will discover and collect decorated methods during initialization.
    
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
        # Store metadata as an attribute on the function
        metadata = {
            'commands': commands,
            'shortDescription': shortDescription,
            'helpMessage': helpMessage,
            'categories': categories,
        }
        setattr(func, _HANDLER_METADATA_ATTR, metadata)
        
        # Return the original function unchanged
        return func
    
    return decorator
```

### 2. Base Handler Class with Auto-Discovery

A base class that automatically discovers decorated methods:

```python
class CommandHandlerMixin:
    """
    Mixin class that provides automatic command handler discovery, dood!
    
    Any class that inherits from this mixin will automatically discover
    all methods decorated with @commandHandler during initialization.
    """
    
    def __init__(self):
        """Initialize and discover command handlers."""
        self._commandHandlers: List[CommandHandlerInfo] = []
        self._discoverCommandHandlers()
    
    def _discoverCommandHandlers(self) -> None:
        """
        Discover all decorated command handler methods in this instance, dood!
        
        This method inspects all methods of the class and collects those
        that have been decorated with @commandHandler.
        """
        import inspect
        
        # Get all methods of this instance
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            # Check if the method has handler metadata
            if hasattr(method, _HANDLER_METADATA_ATTR):
                metadata = getattr(method, _HANDLER_METADATA_ATTR)
                
                # Create CommandHandlerInfo with the bound method
                handlerInfo = CommandHandlerInfo(
                    commands=metadata['commands'],
                    shortDescription=metadata['shortDescription'],
                    helpMessage=metadata['helpMessage'],
                    categories=metadata['categories'],
                    handler=method,  # Already bound to self
                )
                
                self._commandHandlers.append(handlerInfo)
    
    def getCommandHandlers(self) -> Sequence[CommandHandlerInfo]:
        """
        Get all command handlers for this instance, dood!
        
        Returns:
            Sequence of CommandHandlerInfo objects
        """
        return self._commandHandlers.copy()
```

### 3. Integration with BotHandlers Class

Update the [`BotHandlers`](internal/bot/handlers.py:88) class to use the mixin:

```python
class BotHandlers(CommandHandlerMixin):
    """Contains all bot command and message handlers, dood!"""
    
    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        # Initialize the mixin (discovers handlers)
        super().__init__()
        
        # Existing initialization code
        self.configManager = configManager
        self.database = database
        self.llmManager = llmManager
        # ... rest of initialization ...
    
    # getCommandHandlers() is inherited from CommandHandlerMixin
    # No need to override unless you want to add additional logic
```

### 4. Supporting Multiple Handler Classes

With this design, you can easily have multiple handler classes:

```python
class AdminHandlers(CommandHandlerMixin):
    """Admin-specific command handlers, dood!"""
    
    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper):
        super().__init__()
        self.configManager = configManager
        self.database = database
    
    @commandHandler(
        commands=("admin_stats",),
        shortDescription="Show admin statistics",
        helpMessage=": Показать статистику администратора.",
        categories={CommandCategory.BOT_OWNER}
    )
    async def admin_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /admin_stats command."""
        # Implementation here
        pass

class UserHandlers(CommandHandlerMixin):
    """User-specific command handlers, dood!"""
    
    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper):
        super().__init__()
        self.configManager = configManager
        self.database = database
    
    @commandHandler(
        commands=("profile",),
        shortDescription="Show user profile",
        helpMessage=": Показать профиль пользователя.",
        categories={CommandCategory.PRIVATE}
    )
    async def profile_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /profile command."""
        # Implementation here
        pass

# In application setup
adminHandlers = AdminHandlers(config_manager, database)
userHandlers = UserHandlers(config_manager, database)

# Collect all handlers
allHandlers = []
allHandlers.extend(adminHandlers.getCommandHandlers())
allHandlers.extend(userHandlers.getCommandHandlers())
```

### 5. Usage Examples

#### Basic Command Handler

```python
class BotHandlers(CommandHandlerMixin):
    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        super().__init__()
        self.configManager = configManager
        self.database = database
        self.llmManager = llmManager
    
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

1. Add `_HANDLER_METADATA_ATTR` constant to [`internal/bot/models.py`](internal/bot/models.py:1)
2. Add [`commandHandler`](internal/bot/handlers.py:159) decorator function
3. Add [`CommandHandlerMixin`](internal/bot/handlers.py:88) class
4. Keep existing [`getCommandHandlers()`](internal/bot/handlers.py:159) method working
5. Both systems work in parallel

### Phase 2: Update BotHandlers Class

1. Make [`BotHandlers`](internal/bot/handlers.py:88) inherit from [`CommandHandlerMixin`](internal/bot/handlers.py:88)
2. Call `super().__init__()` in [`BotHandlers.__init__()`](internal/bot/handlers.py:88)
3. Keep manual registration as fallback during transition

### Phase 3: Gradual Migration

1. Add decorators to existing handlers one by one
2. Test each handler after decoration
3. Verify handlers appear in `getCommandHandlers()` output

### Phase 4: Complete Migration

1. Remove manual registration from [`getCommandHandlers()`](internal/bot/handlers.py:159)
2. Rely entirely on auto-discovery
3. Remove old code

### Example Migration

**Before:**
```python
class BotHandlers:
    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        self.configManager = configManager
        self.database = database
        self.llmManager = llmManager
    
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
class BotHandlers(CommandHandlerMixin):
    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        super().__init__()  # Discovers handlers
        self.configManager = configManager
        self.database = database
        self.llmManager = llmManager
    
    # getCommandHandlers() inherited from mixin
    
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
    """Decorator with conditional registration, dood!"""
    
    if categories is None:
        categories = {CommandCategory.DEFAULT}
    
    def decorator(func: Callable) -> Callable:
        if enabled:
            metadata = {
                'commands': commands,
                'shortDescription': shortDescription,
                'helpMessage': helpMessage,
                'categories': categories,
            }
            setattr(func, _HANDLER_METADATA_ATTR, metadata)
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
    """Decorator with validation, dood!"""
    
    if categories is None:
        categories = {CommandCategory.DEFAULT}
    
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
        
        # Attach metadata
        metadata = {
            'commands': commands,
            'shortDescription': shortDescription,
            'helpMessage': helpMessage,
            'categories': categories,
        }
        setattr(func, _HANDLER_METADATA_ATTR, metadata)
        
        return func
    
    return decorator
```

### 3. Handler Metadata Access

```python
def getHandlerMetadata(method: Callable) -> Optional[Dict[str, Any]]:
    """
    Get metadata for a decorated handler method, dood!
    
    Args:
        method: The method to check
    
    Returns:
        Dictionary with handler metadata, or None if not decorated
    """
    if hasattr(method, _HANDLER_METADATA_ATTR):
        return getattr(method, _HANDLER_METADATA_ATTR)
    return None
```

### 4. Custom Handler Discovery

You can override `_discoverCommandHandlers()` for custom behavior:

```python
class CustomBotHandlers(CommandHandlerMixin):
    def _discoverCommandHandlers(self) -> None:
        """Custom handler discovery with filtering, dood!"""
        super()._discoverCommandHandlers()
        
        # Filter handlers based on configuration
        if not self.configManager.get('enable_admin_commands'):
            self._commandHandlers = [
                h for h in self._commandHandlers
                if CommandCategory.BOT_OWNER not in h.categories
            ]
```

## Benefits

1. **No Global State**: Each instance manages its own handlers
2. **Scalable**: Easy to split handlers across multiple classes
3. **Reduced Boilerplate**: No need to manually maintain handler list
4. **Better Organization**: Handler metadata lives with implementation
5. **Type Safety**: Decorator provides compile-time checking
6. **Easier Testing**: Can test individual handler classes independently
7. **Discoverability**: Easy to find all handlers (just search for decorator)
8. **Flexibility**: Easy to add conditional registration or validation
9. **Independence**: Handler classes don't interfere with each other

## Considerations

1. **Import Order**: Not an issue since discovery happens at instance creation
2. **Testing**: Each handler class can be tested independently
3. **Debugging**: Stack traces are clean (no global registry)
4. **Performance**: Minimal overhead (discovery happens once per instance)
5. **Memory**: Each instance stores its own handler list (negligible overhead)

## Testing Strategy

### Unit Tests

```python
def test_command_handler_decorator():
    """Test that decorator attaches metadata correctly, dood!"""
    
    @commandHandler(
        commands=("test",),
        shortDescription="Test command",
        helpMessage="Test help",
        categories={CommandCategory.PRIVATE}
    )
    async def test_handler(self, update, context):
        pass
    
    # Verify metadata is attached
    assert hasattr(test_handler, _HANDLER_METADATA_ATTR)
    metadata = getattr(test_handler, _HANDLER_METADATA_ATTR)
    assert metadata['commands'] == ("test",)
    assert metadata['shortDescription'] == "Test command"

def test_handler_discovery():
    """Test that CommandHandlerMixin discovers handlers correctly, dood!"""
    
    class TestHandlers(CommandHandlerMixin):
        def __init__(self):
            super().__init__()
        
        @commandHandler(
            commands=("test1",),
            shortDescription="Test 1",
            helpMessage="Help 1",
            categories={CommandCategory.PRIVATE}
        )
        async def test1_handler(self, update, context):
            pass
        
        @commandHandler(
            commands=("test2",),
            shortDescription="Test 2",
            helpMessage="Help 2",
            categories={CommandCategory.PRIVATE}
        )
        async def test2_handler(self, update, context):
            pass
    
    handlers = TestHandlers()
    commandHandlers = handlers.getCommandHandlers()
    
    assert len(commandHandlers) == 2
    commandNames = {cmd for h in commandHandlers for cmd in h.commands}
    assert "test1" in commandNames
    assert "test2" in commandNames
```

### Integration Tests

```python
def test_bot_handlers_integration():
    """Test that BotHandlers correctly discovers handlers, dood!"""
    bot_handlers = BotHandlers(config_manager, database, llm_manager)
    handlers = bot_handlers.getCommandHandlers()
    
    # Verify all expected handlers are present
    command_names = {cmd for h in handlers for cmd in h.commands}
    assert "start" in command_names
    assert "help" in command_names
    # ... etc

def test_multiple_handler_classes():
    """Test that multiple handler classes work independently, dood!"""
    admin_handlers = AdminHandlers(config_manager, database)
    user_handlers = UserHandlers(config_manager, database)
    
    admin_commands = {cmd for h in admin_handlers.getCommandHandlers() for cmd in h.commands}
    user_commands = {cmd for h in user_handlers.getCommandHandlers() for cmd in h.commands}
    
    # Verify independence
    assert "admin_stats" in admin_commands
    assert "admin_stats" not in user_commands
    assert "profile" in user_commands
    assert "profile" not in admin_commands
```

## Implementation Checklist

- [ ] Add `_HANDLER_METADATA_ATTR` constant to [`internal/bot/models.py`](internal/bot/models.py:1)
- [ ] Implement [`commandHandler`](internal/bot/handlers.py:159) decorator
- [ ] Implement [`CommandHandlerMixin`](internal/bot/handlers.py:88) class
- [ ] Update [`BotHandlers`](internal/bot/handlers.py:88) to inherit from mixin
- [ ] Update [`BotHandlers.__init__()`](internal/bot/handlers.py:88) to call `super().__init__()`
- [ ] Write unit tests for decorator
- [ ] Write unit tests for mixin
- [ ] Write integration tests
- [ ] Migrate one handler as proof of concept
- [ ] Document usage in README
- [ ] Migrate remaining handlers
- [ ] Remove old manual registration code
- [ ] (Optional) Create additional handler classes for better organization

## Comparison with v0

| Aspect | v0 (Global Registry) | v1 (Instance-Level) |
|--------|---------------------|---------------------|
| State Management | Global singleton | Instance-level |
| Scalability | Limited to one class | Multiple classes supported |
| Testing | Need to clear global state | Independent testing |
| Memory | Single shared list | Per-instance lists |
| Complexity | Binding methods later | Methods already bound |
| Flexibility | All handlers in one place | Distributed across classes |

## Conclusion

The instance-level decorator approach provides a cleaner, more maintainable, and more scalable way to register command handlers. It eliminates global state, supports multiple handler classes, and makes the codebase easier to understand and extend, dood!

This design naturally supports the future goal of splitting handlers across multiple classes while maintaining clean separation of concerns and independent testability.

## References

- Current implementation: [`internal/bot/handlers.py:159`](internal/bot/handlers.py:159)
- Command models: [`internal/bot/models.py:150`](internal/bot/models.py:150)
- Python decorators: https://docs.python-telegram-bot.org/
- Python descriptors: https://docs.python.org/3/howto/descriptor.html
- Mixin pattern: https://en.wikipedia.org/wiki/Mixin