"""
Command Handlers: Decorator and mixin for command handler registration
"""

import inspect
import logging
from collections.abc import Awaitable
from enum import Enum, IntEnum, auto
from typing import Any, Callable, Optional, Sequence, Set

from internal.bot.common.models import TypingAction, UpdateObjectType

from .ensured_message import EnsuredMessage

logger = logging.getLogger(__name__)

# Attribute name for storing handler metadata
_HANDLER_METADATA_ATTR_v2 = "_commandHandlerInfoV2"


class CommandPermission(Enum):
    """Permissions for command handlers.

    Defines where and how commands can be used and displayed.
    """

    DEFAULT = auto()
    """Available everywhere"""
    PRIVATE = auto()
    """Available in private chats"""
    GROUP = auto()
    """Available in group chats"""
    ADMIN = auto()
    """Available in group chats for Admins"""
    BOT_OWNER = auto()
    """Available for Bot Owners"""
    HIDDEN = auto()
    """Hide from command list"""


class CommandCategory(Enum):
    """Categories for command handlers.

    Used for organizing commands and applying fine-grained permissions.
    """

    UNSPECIFIED = auto()
    """Unspecified category"""
    PRIVATE = auto()
    """Command for private chats only"""
    ADMIN = auto()
    """Command for Admin/configuration purposes"""
    TOOLS = auto()
    """Tools usage (Web search, draw, etc...)"""
    SPAM = auto()
    """SPAM-related commands"""
    SPAM_ADMIN = auto()
    """SPAM-related commands for Admins"""
    TECHNICAL = auto()
    """Technical commands"""


class CommandHandlerOrder(IntEnum):
    """Order for command handlers in help and bot commands list.

    Lower values appear first in help messages and command lists.
    """

    FIRST = 0
    """First priority commands"""
    SECOND = 10
    """Second priority commands"""
    WIZARDS = 20
    """Wizard-related commands"""
    NORMAL = 50
    """Normal priority commands"""
    SPAM = 70
    """SPAM-related commands"""
    TECHNICAL = 80
    """Technical commands"""
    TEST = 90
    """Test commands"""
    LAST = 100
    """Last priority commands"""


CommandHandlerFuncUnbound = Callable[[Any, EnsuredMessage, str, str, UpdateObjectType, Optional[Any]], Awaitable[None]]
CommandHandlerFuncBound = Callable[[EnsuredMessage, str, str, UpdateObjectType, Optional[Any]], Awaitable[None]]
# CommandHandlerFunc = CommandHandlerFuncBound | CommandHandlerFuncUnbound


class CommandHandlerInfoV2:
    """Metadata for command handlers.

    Stores information about command handlers including commands, descriptions,
    permissions, categories, and handler functions.
    """

    __slots__ = (
        "commands",
        "shortDescription",
        "helpMessage",
        "visibility",
        "availableFor",
        "category",
        "helpOrder",
        "typingAction",
        "replyErrorOnException",
        "handler",
        "boundHandler",
    )

    def __init__(
        self,
        *,
        commands: Sequence[str],
        shortDescription: str,
        helpMessage: str,
        visibility: Optional[Set[CommandPermission]],
        availableFor: Optional[Set[CommandPermission]] = None,
        category: CommandCategory = CommandCategory.UNSPECIFIED,
        helpOrder: CommandHandlerOrder = CommandHandlerOrder.NORMAL,
        typingAction: Optional[TypingAction] = TypingAction.TYPING,
        replyErrorOnException: bool = True,
        handler: CommandHandlerFuncUnbound,
    ) -> None:
        """Initialize command handler metadata.

        Args:
            commands: Sequence of command strings to handle (e.g., ['/start', '/help']).
            shortDescription: Short description for command suggestions.
            helpMessage: Detailed help message for the command.
            visibility: Set of permissions defining where command should be suggested.
                If None or empty, command is hidden from suggestions.
            availableFor: Set of permissions defining where command is allowed to be used.
                If None or empty, command is available everywhere.
            category: Category for command (for fine-grained permissions handling).
                Defaults to CommandCategory.UNSPECIFIED.
            helpOrder: Order in help message. Lower values appear first.
                Defaults to CommandHandlerOrder.NORMAL.
            typingAction: Typing action to send while processing command.
                None to send nothing. Defaults to TypingAction.TYPING.
            replyErrorOnException: Whether to reply to user with exception message on exception.
                Defaults to True.
            handler: Unbound handler function.
        """
        self.commands: Sequence[str] = commands
        """Sequence of commands to handle"""
        self.shortDescription: str = shortDescription
        """Short description, for suggestions"""
        self.helpMessage: str = helpMessage
        """Long help message"""
        self.visibility: Set[CommandPermission] = visibility.copy() if visibility is not None else set()
        "Where command need to be suggested. Default: Hidden"
        self.availableFor: Set[CommandPermission] = availableFor.copy() if availableFor is not None else set()
        """Where command is allowed to be used. Default: """
        self.category: CommandCategory = category
        """Category for command (for more fine-grained permissions handling)"""
        self.helpOrder: CommandHandlerOrder = helpOrder
        """Order in help message"""
        self.typingAction: Optional[TypingAction] = typingAction
        """Which TypingAction we should send? None - to send nothing"""
        self.replyErrorOnException: bool = replyErrorOnException
        """Should we reply to user with exception message on exception? Default: True"""
        self.handler: CommandHandlerFuncUnbound = handler
        """Handler function"""
        self.boundHandler: Optional[CommandHandlerFuncBound] = None
        """Bound Handler function"""

    def __str__(self) -> str:
        """Return string representation of command handler info.

        Returns:
            String representation containing all slot attributes.
        """
        retList = [f"{k}={getattr(self, k, None)}" for k in self.__slots__]
        return f"CommandHandlerInfo({', '.join(retList)})"

    def copy(self) -> "CommandHandlerInfoV2":
        """Create a copy of this command handler info.

        Returns:
            A new CommandHandlerInfoV2 instance with the same attributes.
        """
        return CommandHandlerInfoV2(
            commands=self.commands,
            shortDescription=self.shortDescription,
            helpMessage=self.helpMessage,
            visibility=self.visibility,
            availableFor=self.availableFor,
            category=self.category,
            helpOrder=self.helpOrder,
            typingAction=self.typingAction,
            replyErrorOnException=self.replyErrorOnException,
            handler=self.handler,
        )


def commandHandlerV2(
    commands: Sequence[str],
    shortDescription: str,
    helpMessage: str,
    visibility: Optional[Set[CommandPermission]],
    availableFor: Optional[Set[CommandPermission]] = None,
    category: CommandCategory = CommandCategory.UNSPECIFIED,
    helpOrder: CommandHandlerOrder = CommandHandlerOrder.NORMAL,
    typingAction: Optional[TypingAction] = TypingAction.TYPING,
    replyErrorOnException: bool = True,
) -> Callable[[CommandHandlerFuncUnbound], CommandHandlerFuncUnbound]:
    """Decorator for registering command handlers.

    Stores metadata about command handlers as an attribute on the decorated function.
    The metadata is later discovered by CommandHandlerMixin.

    Args:
        commands: Sequence of command strings to handle (e.g., ['/start', '/help']).
        shortDescription: Short description for command suggestions.
        helpMessage: Detailed help message for the command.
        visibility: Set of permissions defining where command should be suggested.
            If None or empty, command is hidden from suggestions.
        availableFor: Set of permissions defining where command is allowed to be used.
            If None or empty, command is available everywhere.
        category: Category for command (for fine-grained permissions handling).
            Defaults to CommandCategory.UNSPECIFIED.
        helpOrder: Order in help message. Lower values appear first.
            Defaults to CommandHandlerOrder.NORMAL.
        typingAction: Typing action to send while processing command.
            None to send nothing. Defaults to TypingAction.TYPING.
        replyErrorOnException: Whether to reply to user with exception message on exception.
            Defaults to True.

    Returns:
        Decorator function that accepts a command handler function and returns it unchanged
        with metadata attached.
    """

    def decorator(func: CommandHandlerFuncUnbound) -> CommandHandlerFuncUnbound:
        # Store metadata as an attribute on the function
        metadata = CommandHandlerInfoV2(
            commands=commands,
            shortDescription=shortDescription,
            helpMessage=helpMessage,
            visibility=visibility,
            availableFor=availableFor,
            category=category,
            helpOrder=helpOrder,
            typingAction=typingAction,
            replyErrorOnException=replyErrorOnException,
            handler=func,
        )
        setattr(func, _HANDLER_METADATA_ATTR_v2, metadata)

        # Return the original function unchanged
        return func

    return decorator


class CommandHandlerMixin:
    """Mixin class that provides automatic command handler discovery.

    Any class that inherits from this mixin will automatically discover
    all methods decorated with @commandHandlerV2 during initialization.
    """

    def __init__(self) -> None:
        """Initialize and discover command handlers.

        Initializes the command handlers list and discovers all methods
        decorated with @commandHandlerV2.
        """
        self._commandHandlersV2: list[CommandHandlerInfoV2] = []
        self._discoverCommandHandlersV2()

    def _discoverCommandHandlersV2(self) -> None:
        """Discover all command handlers decorated with @commandHandlerV2.

        Inspects all methods of the instance, checks for handler metadata,
        and creates bound handler info objects.

        Raises:
            ValueError: If invalid handler metadata is found on a method.
        """

        # Get all methods of this instance
        for _, method in inspect.getmembers(self, predicate=inspect.ismethod):
            # Check if the method has handler metadata
            if hasattr(method, _HANDLER_METADATA_ATTR_v2):
                metadata = getattr(method, _HANDLER_METADATA_ATTR_v2)
                if not isinstance(metadata, CommandHandlerInfoV2):
                    raise ValueError(f"Invalid handler metadata for {method.__name__}: {metadata}")

                # Create CommandHandlerInfo with the bound method
                handlerInfo = metadata.copy()
                handlerInfo.boundHandler = method  # Already bound to self

                self._commandHandlersV2.append(handlerInfo)

    def getCommandHandlersV2(self) -> Sequence[CommandHandlerInfoV2]:
        """Get all discovered command handlers.

        Returns:
            A copy of the list of CommandHandlerInfoV2 objects representing
            all discovered command handlers.
        """
        return self._commandHandlersV2.copy()
