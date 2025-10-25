"""
Unit tests for command handler decorator implementation, dood!
"""

import unittest
from internal.bot.models import (
    CommandCategory,
    CommandHandlerInfo,
    CommandHandlerMixin,
    commandHandler,
)


class TestCommandHandlerMixin(unittest.TestCase):
    """Test the CommandHandlerMixin class, dood!"""

    def test_mixin_discovers_handlers(self):
        """Test that mixin discovers decorated handlers, dood!"""

        class TestHandlers(CommandHandlerMixin):
            def __init__(self):
                super().__init__()

            @commandHandler(
                commands=("test1",),
                shortDescription="Test 1",
                helpMessage="Help 1",
                categories={CommandCategory.PRIVATE},
            )
            async def test1_handler(self, update, context):
                pass

            @commandHandler(
                commands=("test2",),
                shortDescription="Test 2",
                helpMessage="Help 2",
                categories={CommandCategory.PRIVATE},
            )
            async def test2_handler(self, update, context):
                pass

        handlers = TestHandlers()
        commandHandlers = handlers.getCommandHandlers()

        self.assertEqual(len(commandHandlers), 2)
        commandNames = {cmd for h in commandHandlers for cmd in h.commands}
        self.assertIn("test1", commandNames)
        self.assertIn("test2", commandNames)

    def test_mixin_ignores_undecorated_methods(self):
        """Test that mixin ignores methods without decorator, dood!"""

        class TestHandlers(CommandHandlerMixin):
            def __init__(self):
                super().__init__()

            @commandHandler(
                commands=("decorated",),
                shortDescription="Decorated",
                helpMessage="Help",
                categories={CommandCategory.PRIVATE},
            )
            async def decorated_handler(self, update, context):
                pass

            async def undecorated_handler(self, update, context):
                pass

        handlers = TestHandlers()
        commandHandlers = handlers.getCommandHandlers()

        self.assertEqual(len(commandHandlers), 1)
        self.assertEqual(commandHandlers[0].commands, ("decorated",))

    def test_mixin_handlers_are_bound_methods(self):
        """Test that discovered handlers are bound methods, dood!"""

        class TestHandlers(CommandHandlerMixin):
            def __init__(self):
                super().__init__()
                self.test_value = "test"

            @commandHandler(
                commands=("test",), shortDescription="Test", helpMessage="Help", categories={CommandCategory.PRIVATE}
            )
            async def test_handler(self, update, context):
                return self.test_value

        handlers = TestHandlers()
        commandHandlers = handlers.getCommandHandlers()

        self.assertEqual(len(commandHandlers), 1)
        handler = commandHandlers[0].handler

        # Verify it's a bound method
        self.assertTrue(callable(handler))
        self.assertTrue(hasattr(handler, "__self__"))
        self.assertIs(handler.__self__, handlers)  # pyright: ignore[reportFunctionMemberAccess]

    def test_mixin_returns_copy_of_handlers(self):
        """Test that getCommandHandlers returns a copy, dood!"""

        class TestHandlers(CommandHandlerMixin):
            def __init__(self):
                super().__init__()

            @commandHandler(
                commands=("test",), shortDescription="Test", helpMessage="Help", categories={CommandCategory.PRIVATE}
            )
            async def test_handler(self, update, context):
                pass

        handlers = TestHandlers()
        commandHandlers1 = handlers.getCommandHandlers()
        commandHandlers2 = handlers.getCommandHandlers()

        # Should be equal but not the same object
        self.assertEqual(commandHandlers1, commandHandlers2)
        self.assertIsNot(commandHandlers1, commandHandlers2)

    def test_multiple_instances_independent(self):
        """Test that multiple instances have independent handler lists, dood!"""

        class TestHandlers(CommandHandlerMixin):
            def __init__(self):
                super().__init__()

            @commandHandler(
                commands=("test",), shortDescription="Test", helpMessage="Help", categories={CommandCategory.PRIVATE}
            )
            async def test_handler(self, update, context):
                pass

        handlers1 = TestHandlers()
        handlers2 = TestHandlers()

        # Both should have handlers
        self.assertEqual(len(handlers1.getCommandHandlers()), 1)
        self.assertEqual(len(handlers2.getCommandHandlers()), 1)

        # But they should be different instances
        self.assertIsNot(handlers1._commandHandlers, handlers2._commandHandlers)


class TestCommandHandlerInfo(unittest.TestCase):
    """Test the CommandHandlerInfo dataclass, dood!"""

    def test_command_handler_info_creation(self):
        """Test creating CommandHandlerInfo, dood!"""

        async def dummy_handler(update, context):
            pass

        info = CommandHandlerInfo(
            commands=("test",),
            shortDescription="Test",
            helpMessage="Help",
            categories={CommandCategory.PRIVATE},
            handler=dummy_handler,
        )

        self.assertEqual(info.commands, ("test",))
        self.assertEqual(info.shortDescription, "Test")
        self.assertEqual(info.helpMessage, "Help")
        self.assertEqual(info.categories, {CommandCategory.PRIVATE})
        self.assertIs(info.handler, dummy_handler)


if __name__ == "__main__":
    unittest.main()
