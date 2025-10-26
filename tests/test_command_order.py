#!/usr/bin/env python3
"""
Test script to verify command handler ordering functionality, dood!
"""

from internal.bot.models import (
    CommandCategory,
    CommandHandlerOrder,
    commandHandler,
)


class TestHandlers:
    """Test class with command handlers, dood!"""

    @commandHandler(
        commands=("first",),
        shortDescription="First command",
        helpMessage=": Should appear first",
        categories={CommandCategory.DEFAULT},
        order=CommandHandlerOrder.FIRST,
    )
    async def first_command(self):
        pass

    @commandHandler(
        commands=("normal",),
        shortDescription="Normal command",
        helpMessage=": Should appear in middle",
        categories={CommandCategory.DEFAULT},
    )
    async def normal_command(self):
        pass

    @commandHandler(
        commands=("last",),
        shortDescription="Last command",
        helpMessage=": Should appear last",
        categories={CommandCategory.DEFAULT},
        order=CommandHandlerOrder.LAST,
    )
    async def last_command(self):
        pass

    @commandHandler(
        commands=("early",),
        shortDescription="Early command",
        helpMessage=": Should appear early",
        categories={CommandCategory.DEFAULT},
        order=CommandHandlerOrder.SECOND,
    )
    async def early_command(self):
        pass


def test_command_ordering():
    """Test that commands are properly ordered, dood!"""
    print("Testing command handler ordering, dood!")
    print("=" * 60)

    # Get handlers from decorated methods
    handlers = []
    for attr_name in dir(TestHandlers):
        attr = getattr(TestHandlers, attr_name)
        if hasattr(attr, "_command_handler_info"):
            info = getattr(attr, "_command_handler_info")
            handlers.append(info)

    print(f"\nFound {len(handlers)} command handlers")
    print("\nBefore sorting:")
    for h in handlers:
        print(f"  {h.commands[0]:15} - order: {h.order:3} - {h.shortDescription}")

    # Sort by order, then by command name
    sorted_handlers = sorted(handlers, key=lambda h: (h.order, h.commands[0]))

    print("\nAfter sorting:")
    for h in sorted_handlers:
        print(f"  {h.commands[0]:15} - order: {h.order:3} - {h.shortDescription}")

    # Verify order
    expected_order = ["first", "early", "normal", "last"]
    actual_order = [h.commands[0] for h in sorted_handlers]

    print("\n" + "=" * 60)
    print(f"  Expected: {expected_order}")
    print(f"  Actual:   {actual_order}")

    # Use assert instead of return
    assert actual_order == expected_order, (
        f"Commands are NOT in correct order, dood! "
        f"Expected {expected_order}, got {actual_order}"
    )

    print("✓ Test PASSED, dood! Commands are in correct order!")


if __name__ == "__main__":
    try:
        test_command_ordering()
        exit(0)
    except AssertionError as e:
        print(f"\n✗ Test FAILED: {e}")
        exit(1)
