"""
Command Handlers: Decorator and mixin for command handler registration
"""

import inspect
import logging
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Set
from enum import Enum, IntEnum, auto


logger = logging.getLogger(__name__)

# Attribute name for storing handler metadata, dood!
_HANDLER_METADATA_ATTR = "_command_handler_info"

class CommandCategory(Enum):
    DEFAULT = auto()  # Available everywhere
    PRIVATE = auto()  # Available in private chats
    GROUP = auto()  # Available in group chats
    ADMIN = auto()  # Available in group chats for Admins
    BOT_OWNER = auto()  # Available for Bot Owners
    HIDDEN = auto()  # Hide from command list


class CommandHandlerOrder(IntEnum):
    """Order for command handlers in help and bot commands list, dood!"""

    FIRST = 0
    SECOND = 10
    NORMAL = 50
    SPAM = 70
    TECHNICAL = 80
    TEST = 90
    LAST = 100


@dataclass
class CommandHandlerInfo:
    commands: Sequence[str]
    shortDescription: str
    helpMessage: str
    categories: Set[CommandCategory]
    order: CommandHandlerOrder
    # handler: tgTypes.HandlerCallback[tgUpdate.Update, tgTypes.CCT, tgTypes.RT],
    handler: Callable

    def copy(self) -> "CommandHandlerInfo":
        return CommandHandlerInfo(
            commands=self.commands,
            shortDescription=self.shortDescription,
            helpMessage=self.helpMessage,
            categories=self.categories,
            order=self.order,
            handler=self.handler,
        )


def commandHandler(
    commands: Sequence[str],
    shortDescription: str,
    helpMessage: str,
    categories: Optional[Set[CommandCategory]] = None,
    order: CommandHandlerOrder = CommandHandlerOrder.NORMAL,
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
        order: Order for sorting commands in help and bot commands list (default: CommandHandlerOrder.NORMAL)

    Example:
        @commandHandler(
            commands=("start",),
            shortDescription="Start bot interaction",
            helpMessage=": Начать работу с ботом.",
            categories={CommandCategory.PRIVATE},
            order=CommandHandlerOrder.FIRST
        )
        async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            # Implementation here
            pass
    """
    if categories is None:
        categories = {CommandCategory.DEFAULT}

    def decorator(func: Callable) -> Callable:
        # Store metadata as an attribute on the function
        metadata = CommandHandlerInfo(
            commands=commands,
            shortDescription=shortDescription,
            helpMessage=helpMessage,
            categories=categories,
            order=order,
            handler=func,
        )
        setattr(func, _HANDLER_METADATA_ATTR, metadata)

        # Return the original function unchanged
        return func

    return decorator


class CommandHandlerMixin:
    """
    Mixin class that provides automatic command handler discovery, dood!

    Any class that inherits from this mixin will automatically discover
    all methods decorated with @commandHandler during initialization.
    """

    def __init__(self):
        """Initialize and discover command handlers."""
        self._commandHandlers: list[CommandHandlerInfo] = []
        self._discoverCommandHandlers()

    def _discoverCommandHandlers(self) -> None:
        """
        Discover all decorated command handler methods in this instance, dood!

        This method inspects all methods of the class and collects those
        that have been decorated with @commandHandler.
        """

        # Get all methods of this instance
        for _, method in inspect.getmembers(self, predicate=inspect.ismethod):
            # Check if the method has handler metadata
            if hasattr(method, _HANDLER_METADATA_ATTR):
                metadata = getattr(method, _HANDLER_METADATA_ATTR)
                if not isinstance(metadata, CommandHandlerInfo):
                    raise ValueError(f"Invalid handler metadata for {method.__name__}: {metadata}")

                # Create CommandHandlerInfo with the bound method
                handlerInfo = metadata.copy()
                handlerInfo.handler = method  # Already bound to self

                self._commandHandlers.append(handlerInfo)

    def getCommandHandlers(self) -> Sequence[CommandHandlerInfo]:
        """
        Get all command handlers for this instance, dood!

        Returns:
            Sequence of CommandHandlerInfo objects
        """
        return self._commandHandlers.copy()