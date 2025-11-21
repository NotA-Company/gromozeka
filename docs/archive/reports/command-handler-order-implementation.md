# Command Handler Order Implementation Report

## Overview
Added ordering functionality to the `commandHandler` decorator to allow organizing commands by groups in help and bot commands list, dood!

## Changes Made

### 1. Created `CommandHandlerOrder` IntEnum (`internal/bot/models.py`)
```python
class CommandHandlerOrder(IntEnum):
    """Order for command handlers in help and bot commands list, dood!"""
    FIRST = 0
    EARLY = 10
    NORMAL = 50
    LATE = 90
    LAST = 100
```

This enum provides named constants for organizing commands into logical groups.

### 2. Updated `CommandHandlerInfo` Dataclass
Added `order: int` field to store the command's order value.

### 3. Updated `commandHandler` Decorator
Added `order` parameter with default value `CommandHandlerOrder.NORMAL`:
```python
def commandHandler(
    commands: Sequence[str],
    shortDescription: str,
    helpMessage: str,
    categories: Optional[Set[CommandCategory]] = None,
    order: int = CommandHandlerOrder.NORMAL,
) -> Callable:
```

### 4. Updated Command Sorting

#### In `help_command` (`internal/bot/handlers.py`)
Added sorting before processing commands:
```python
# Sort command handlers by order, then by command name
sortedHandlers = sorted(
    self.getCommandHandlers(),
    key=lambda h: (h.order, h.commands[0])
)
```

#### In `postInit` (`internal/bot/application.py`)
Added sorting before setting bot commands:
```python
# Sort command handlers by order, then by command name
sortedHandlers = sorted(
    self.handlers.getCommandHandlers(),
    key=lambda h: (h.order, h.commands[0])
)
```

### 5. Updated Imports
Added `CommandHandlerOrder` to imports in `internal/bot/handlers.py`.

## Usage Example

```python
@commandHandler(
    commands=("start",),
    shortDescription="Start bot interaction",
    helpMessage=": Начать работу с ботом.",
    categories={CommandCategory.PRIVATE},
    order=CommandHandlerOrder.FIRST,  # This command will appear first
)
async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Implementation
    pass

@commandHandler(
    commands=("help",),
    shortDescription="Print help",
    helpMessage=": Показать список доступных команд.",
    categories={CommandCategory.PRIVATE},
    # order defaults to CommandHandlerOrder.NORMAL (50)
)
async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Implementation
    pass
```

## Sorting Behavior

Commands are sorted by:
1. **Primary**: `order` value (ascending)
2. **Secondary**: Command name (alphabetically) when orders are equal

This ensures:
- Commands with lower order values appear first
- Commands with the same order are sorted alphabetically
- Default commands (without explicit order) use `NORMAL` (50)

## Benefits

1. **Logical Grouping**: Organize commands by importance or functionality
2. **Flexibility**: Use predefined constants or custom integer values
3. **Backward Compatible**: Existing commands without `order` parameter use default value
4. **Consistent**: Same ordering in both help text and Telegram bot commands menu

## Testing

Created `test_command_order.py` to verify:
- Commands are sorted correctly by order value
- Secondary alphabetical sorting works when orders are equal
- All order constants work as expected

Test result: ✓ PASSED, dood!

## Files Modified

1. `internal/bot/models.py` - Added `CommandHandlerOrder` enum, updated `CommandHandlerInfo` and `commandHandler`
2. `internal/bot/handlers.py` - Added sorting in `help_command`, updated imports, added example usage
3. `internal/bot/application.py` - Added sorting in `postInit` method
4. `test_command_order.py` - Created test file (new)
5. `docs/reports/command-handler-order-implementation.md` - This report (new)

## Future Enhancements

You can now easily organize commands by adding more order constants or using custom values:
- Group admin commands together
- Prioritize frequently used commands
- Organize by feature areas
- Create custom ordering schemes

Dood!