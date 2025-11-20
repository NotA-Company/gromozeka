"""
Command Handlers: Decorator and mixin for command handler registration
"""

import inspect
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from enum import Enum, IntEnum, auto
from typing import Any, Callable, Dict, Optional, Sequence, Set, TypeAlias

from internal.bot.common.models import TypingAction, UpdateObjectType

from .ensured_message import EnsuredMessage

logger = logging.getLogger(__name__)

# Attribute name for storing handler metadata, dood!
_HANDLER_METADATA_ATTR = "_command_handler_info"
_HANDLER_METADATA_ATTR_v2 = "_commandHandlerInfoV2"


class CommandPermission(Enum):
    """Permissions for command"""

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
    """Categories for command"""

    UNSPECIFIED = auto()  # Unspecified category
    PRIVATE = auto()  # Command for private chats only
    ADMIN = auto()  # Command for Admin/configuration purposes
    TOOLS = auto()  # Tools usage (Web search, draw, etc...)
    SPAM = auto()  # SPAM-related commands
    SPAM_ADMIN = auto()  # SPAM-related commands for Admins
    TECHNICAL = auto()  # Technical commands


class CommandHandlerOrder(IntEnum):
    """Order for command handlers in help and bot commands list, dood!"""

    FIRST = 0
    SECOND = 10
    WIZARDS = 20
    NORMAL = 50
    SPAM = 70
    TECHNICAL = 80
    TEST = 90
    LAST = 100


CommandHandlerFuncUnbound = Callable[[Any, EnsuredMessage, str, str, UpdateObjectType, Optional[Any]], Awaitable[None]]
CommandHandlerFuncBound = Callable[[EnsuredMessage, str, str, UpdateObjectType, Optional[Any]], Awaitable[None]]
# CommandHandlerFunc = CommandHandlerFuncBound | CommandHandlerFuncUnbound


class CommandHandlerInfoV2:
    """TODO"""

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
    ):
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
        retList = [f"{k}={getattr(self, k, None)}" for k in self.__slots__]
        return f"CommandHandlerInfo({', '.join(retList)})"

    def copy(self) -> "CommandHandlerInfoV2":
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
    """
    TODO
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


@dataclass
class CommandHandlerInfo:
    commands: Sequence[str]
    shortDescription: str
    helpMessage: str
    categories: Set[CommandPermission]
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
        self._commandHandlersV2: list[CommandHandlerInfoV2] = []
        self._discoverCommandHandlersV2()

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

    def _discoverCommandHandlersV2(self) -> None:
        """
        TODO
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
        """
        TODO
        """
        return self._commandHandlersV2.copy()


CallbackDataDict: TypeAlias = Dict[str | int, str | int | float | bool | None]
"""DEPRECATED, use utils.PayloadDict"""
