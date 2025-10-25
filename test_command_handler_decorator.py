#!/usr/bin/env python3
"""
Test script for command handler decorator implementation, dood!
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from internal.bot.models import CommandCategory, CommandHandlerInfo, CommandHandlerMixin, commandHandler


class TestHandlers(CommandHandlerMixin):
    """Test handler class, dood!"""
    
    def __init__(self):
        super().__init__()
        self.test_value = "test"
    
    @commandHandler(
        commands=("test1",),
        shortDescription="Test command 1",
        helpMessage=": Test help 1",
        categories={CommandCategory.PRIVATE}
    )
    async def test1_handler(self, update, context):
        """Test handler 1"""
        pass
    
    @commandHandler(
        commands=("test2", "test2_alias"),
        shortDescription="Test command 2",
        helpMessage=": Test help 2",
        categories={CommandCategory.PRIVATE, CommandCategory.GROUP}
    )
    async def test2_handler(self, update, context):
        """Test handler 2"""
        pass
    
    async def not_a_handler(self, update, context):
        """This should not be discovered"""
        pass


def test_decorator_discovery():
    """Test that decorator properly discovers handlers, dood!"""
    print("Testing command handler decorator discovery, dood!")
    
    handlers = TestHandlers()
    commandHandlers = handlers.getCommandHandlers()
    
    print(f"\nDiscovered {len(commandHandlers)} handlers, dood!")
    
    # Check we found exactly 2 handlers
    assert len(commandHandlers) == 2, f"Expected 2 handlers, found {len(commandHandlers)}, dood!"
    
    # Collect all command names
    commandNames = {cmd for h in commandHandlers for cmd in h.commands}
    print(f"Command names: {commandNames}")
    
    # Verify expected commands are present
    assert "test1" in commandNames, "test1 command not found, dood!"
    assert "test2" in commandNames, "test2 command not found, dood!"
    assert "test2_alias" in commandNames, "test2_alias command not found, dood!"
    
    # Verify handlers are bound methods
    for handler in commandHandlers:
        print(f"\nHandler: {handler.commands}")
        print(f"  Short: {handler.shortDescription}")
        print(f"  Help: {handler.helpMessage}")
        print(f"  Categories: {handler.categories}")
        print(f"  Handler: {handler.handler}")
        assert callable(handler.handler), f"Handler {handler.commands} is not callable, dood!"
    
    print("\n✅ All tests passed, dood!")


if __name__ == "__main__":
    test_decorator_discovery()