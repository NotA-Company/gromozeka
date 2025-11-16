"""
Filter system for Max Messenger Bot API.

This module provides a comprehensive filtering system that allows creating
complex filters for updates and messages. Filters can be combined using
logical operators (AND, OR, NOT) to create sophisticated filtering logic.
"""

import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional, Union

from .models.chat import ChatType
from .models.update import Update, UpdateType

if TYPE_CHECKING:
    from .models.chat import Chat
    from .models.message import Message
    from .models.user import User


class FilterHelper:
    """Helper class with common methods for accessing update data."""

    @staticmethod
    def get_message_text(update: Update) -> Optional[str]:
        """Extract text from update."""
        message = FilterHelper.get_message(update)
        if message and hasattr(message, "body") and message.message:
            return getattr(message.message, "text", None)
        return None

    @staticmethod
    def get_message(update: Update) -> Optional["Message"]:
        """Get message from update if it exists."""
        return getattr(update, "message", None)

    @staticmethod
    def get_chat(update: Update) -> Optional["Chat"]:
        """Get chat from update if it exists."""
        message = FilterHelper.get_message(update)
        if message:
            return getattr(message, "chat", None)
        return None

    @staticmethod
    def get_user(update: Update) -> Optional["User"]:
        """Get user from update if it exists."""
        # Try to get user from message
        message = FilterHelper.get_message(update)
        if message:
            user = getattr(message, "fromUser", None)
            if user:
                return user

        # Try to get user from update directly (for callback queries)
        user = getattr(update, "from_user", None)
        if user:
            return user

        # Try to get user from update directly (for member updates)
        user = getattr(update, "user", None)
        if user:
            return user

        return None


class Filter(ABC):
    """Base class for all filters.

    Provides the foundation for creating specific filters for different types of updates.
    All filters should inherit from this class and implement the check method.
    """

    @abstractmethod
    def check(self, update: Update) -> bool:
        """Check if the update passes this filter.

        Args:
            update: The update to check

        Returns:
            True if the update passes the filter
        """
        pass

    def __and__(self, other: "Filter") -> "AndFilter":
        """Create an AND filter with another filter."""
        return AndFilter(self, other)

    def __or__(self, other: "Filter") -> "OrFilter":
        """Create an OR filter with another filter."""
        return OrFilter(self, other)

    def __invert__(self) -> "NotFilter":
        """Create a NOT filter."""
        return NotFilter(self)


class TextFilter(Filter):
    """Filter for text content in messages.

    Filters messages based on their text content using exact match,
    case-insensitive match, or regex patterns.
    """

    def __init__(
        self,
        text: Optional[str] = None,
        ignore_case: bool = True,
        regex: Optional[str] = None,
        contains: Optional[str] = None,
        startswith: Optional[str] = None,
        endswith: Optional[str] = None,
    ):
        """Initialize the text filter.

        Args:
            text: Exact text to match (optional)
            ignore_case: Whether to ignore case when matching (default: True)
            regex: Regex pattern to match (optional)
            contains: Text that should be contained in the message (optional)
            startswith: Text that the message should start with (optional)
            endswith: Text that the message should end with (optional)
        """
        self.text = text
        self.ignoreCase = ignore_case
        self.regex = re.compile(regex) if regex else None
        self.contains = contains
        self.startswith = startswith
        self.endswith = endswith

    def check(self, update: Update) -> bool:
        """Check if the update passes the text filter."""
        # Get message text from update
        message_text = FilterHelper.get_message_text(update)
        if message_text is None:
            return False

        # Apply case transformation if needed
        check_text = message_text.lower() if self.ignoreCase else message_text

        # Check exact match
        if self.text is not None:
            compare_text = self.text.lower() if self.ignoreCase else self.text
            if check_text != compare_text:
                return False

        # Check regex match
        if self.regex is not None:
            if not self.regex.search(message_text):
                return False

        # Check contains
        if self.contains is not None:
            compare_contains = self.contains.lower() if self.ignoreCase else self.contains
            if compare_contains not in check_text:
                return False

        # Check startswith
        if self.startswith is not None:
            compare_start = self.startswith.lower() if self.ignoreCase else self.startswith
            if not check_text.startswith(compare_start):
                return False

        # Check endswith
        if self.endswith is not None:
            compare_end = self.endswith.lower() if self.ignoreCase else self.endswith
            if not check_text.endswith(compare_end):
                return False

        return True

    def _get_message_text(self, update: Update) -> Optional[str]:
        """Extract text from update."""
        message = getattr(update, "message", None)
        if message and hasattr(message, "body") and message.message:
            return getattr(message.message, "text", None)
        return None

    def _get_message(self, update: Update) -> Optional["Message"]:
        """Get message from update if it exists."""
        return getattr(update, "message", None)

    def _get_chat(self, update: Update) -> Optional["Chat"]:
        """Get chat from update if it exists."""
        message = self._get_message(update)
        if message:
            return getattr(message, "chat", None)
        return None

    def _get_user(self, update: Update) -> Optional["User"]:
        """Get user from update if it exists."""
        # Try to get user from message
        message = self._get_message(update)
        if message:
            user = getattr(message, "fromUser", None)
            if user:
                return user

        # Try to get user from update directly (for callback queries)
        user = getattr(update, "from_user", None)
        if user:
            return user

        # Try to get user from update directly (for member updates)
        user = getattr(update, "user", None)
        if user:
            return user

        return None


class CommandFilter(Filter):
    """Filter for bot commands.

    Filters messages that contain bot commands (e.g., /start, /help).
    """

    def __init__(
        self,
        commands: Optional[Union[str, List[str]]] = None,
        prefix: str = "/",
        ignore_case: bool = True,
    ):
        """Initialize the command filter.

        Args:
            commands: Command(s) to match (optional, matches any command if None)
            prefix: Command prefix (default: "/")
            ignore_case: Whether to ignore case when matching (default: True)
        """
        if isinstance(commands, str):
            commands = [commands]
        self.commands = commands
        self.prefix = prefix
        self.ignoreCase = ignore_case

    def check(self, update: Update) -> bool:
        """Check if the update passes the command filter."""
        message_text = FilterHelper.get_message_text(update)
        if not message_text:
            return False

        # Check if message starts with command prefix
        if not message_text.startswith(self.prefix):
            return False

        # Extract command (remove prefix and split at first space)
        command_part = message_text[len(self.prefix) :].split()[0]

        # Remove @username if present
        if "@" in command_part:
            command_part = command_part.split("@")[0]

        # Check if specific commands are specified
        if self.commands:
            check_command = command_part.lower() if self.ignoreCase else command_part
            for cmd in self.commands:
                compare_cmd = cmd.lower() if self.ignoreCase else cmd
                if check_command == compare_cmd:
                    return True
            return False

        # Any command matches
        return True


class RegexFilter(Filter):
    """Filter for regex pattern matching.

    Filters messages using regular expression patterns.
    """

    def __init__(self, pattern: str, flags: int = 0):
        """Initialize the regex filter.

        Args:
            pattern: Regex pattern to match
            flags: Regex flags (default: 0)
        """
        self.pattern = re.compile(pattern, flags)

    def check(self, update: Update) -> bool:
        """Check if the update passes the regex filter."""
        message_text = FilterHelper.get_message_text(update)
        if message_text is None:
            return False

        return bool(self.pattern.search(message_text))

    def _get_message_text(self, update: Update) -> Optional[str]:
        """Extract text from update."""
        message = FilterHelper.get_message(update)
        if message and hasattr(message, "body") and message.message:
            return getattr(message.message, "text", None)
        return None


class ChatTypeFilter(Filter):
    """Filter for chat types.

    Filters updates based on the type of chat (dialog, chat, channel).
    """

    def __init__(self, chat_types: Union[ChatType, List[ChatType]]):
        """Initialize the chat type filter.

        Args:
            chat_types: Chat type(s) to match
        """
        if isinstance(chat_types, ChatType):
            chat_types = [chat_types]
        self.chatTypes = chat_types

    def check(self, update: Update) -> bool:
        """Check if the update passes the chat type filter."""
        chat_type = self._get_chat_type(update)
        if chat_type is None:
            return False

        return chat_type in self.chatTypes

    def _get_chat_type(self, update: Update) -> Optional[ChatType]:
        """Extract chat type from update."""
        # Try to get chat type from message recipient
        message = FilterHelper.get_message(update)
        if message and hasattr(message, "recipient") and message.recipient:
            return getattr(message.recipient, "chat_type", None)

        # Try to get chat type from chat object
        chat = FilterHelper.get_chat(update)
        if chat:
            return getattr(chat, "type", None)

        # Try to get chat type from chat_id in update
        if hasattr(update, "chat_id"):
            # For now, assume it's a chat if we have a chat_id
            # This could be enhanced with additional logic
            return ChatType.CHAT

        return None


class UserFilter(Filter):
    """Filter for specific users.

    Filters updates based on user IDs or usernames.
    """

    def __init__(
        self,
        user_ids: Optional[Union[int, List[int]]] = None,
        usernames: Optional[Union[str, List[str]]] = None,
        exclude: bool = False,
    ):
        """Initialize the user filter.

        Args:
            user_ids: User ID(s) to match (optional)
            usernames: Username(s) to match (optional)
            exclude: If True, exclude specified users instead of including them
        """
        if isinstance(user_ids, int):
            user_ids = [user_ids]
        if isinstance(usernames, str):
            usernames = [usernames]

        self.userIds = user_ids or []
        self.usernames = usernames or []
        self.exclude = exclude

    def check(self, update: Update) -> bool:
        """Check if the update passes the user filter."""
        user_id = self._get_user_id(update)
        username = self._get_username(update)

        # Check user ID
        if self.userIds and user_id is not None:
            user_matches = user_id in self.userIds
            if user_matches:
                return not self.exclude

        # Check username
        if self.usernames and username is not None:
            username_matches = username in self.usernames
            if username_matches:
                return not self.exclude

        # If we have filters but no match
        if self.userIds or self.usernames:
            return self.exclude

        # No filters specified, match all
        return True

    def _get_user_id(self, update: Update) -> Optional[int]:
        """Extract user ID from update."""
        # Try to get from message sender
        message = FilterHelper.get_message(update)
        if message and hasattr(message, "sender") and message.sender:
            return getattr(message.sender, "user_id", None)

        # Try to get from user object
        user = FilterHelper.get_user(update)
        if user:
            return getattr(user, "user_id", None)

        return None

    def _get_username(self, update: Update) -> Optional[str]:
        """Extract username from update."""
        # Try to get from message sender
        message = FilterHelper.get_message(update)
        if message and hasattr(message, "sender") and message.sender:
            return getattr(message.sender, "username", None)

        # Try to get from user object
        user = FilterHelper.get_user(update)
        if user:
            return getattr(user, "username", None)

        return None


class UpdateTypeFilter(Filter):
    """Filter for update types.

    Filters updates based on their type.
    """

    def __init__(self, update_types: Union[UpdateType, List[UpdateType]]):
        """Initialize the update type filter.

        Args:
            update_types: Update type(s) to match
        """
        if isinstance(update_types, UpdateType):
            update_types = [update_types]
        self.updateTypes = update_types

    def check(self, update: Update) -> bool:
        """Check if the update passes the update type filter."""
        return update.update_type in self.updateTypes


# Combinable filters


class AndFilter(Filter):
    """Filter that combines multiple filters with AND logic."""

    def __init__(self, *filters: Filter):
        """Initialize the AND filter.

        Args:
            *filters: Filters to combine with AND logic
        """
        self.filters = list(filters)

    def check(self, update: Update) -> bool:
        """Check if the update passes all filters."""
        return all(f.check(update) for f in self.filters)


class OrFilter(Filter):
    """Filter that combines multiple filters with OR logic."""

    def __init__(self, *filters: Filter):
        """Initialize the OR filter.

        Args:
            *filters: Filters to combine with OR logic
        """
        self.filters = list(filters)

    def check(self, update: Update) -> bool:
        """Check if the update passes any filter."""
        return any(f.check(update) for f in self.filters)


class NotFilter(Filter):
    """Filter that inverts the result of another filter."""

    def __init__(self, filter_obj: Filter):
        """Initialize the NOT filter.

        Args:
            filter_obj: Filter to invert
        """
        self.filter = filter_obj

    def check(self, update: Update) -> bool:
        """Check if the update does NOT pass the inner filter."""
        return not self.filter.check(update)


# Convenience functions for creating common filters


def text(
    text: Optional[str] = None,
    ignore_case: bool = True,
    regex: Optional[str] = None,
    contains: Optional[str] = None,
    startswith: Optional[str] = None,
    endswith: Optional[str] = None,
) -> TextFilter:
    """Create a text filter."""
    return TextFilter(text, ignore_case, regex, contains, startswith, endswith)


def command(
    commands: Optional[Union[str, List[str]]] = None,
    prefix: str = "/",
    ignore_case: bool = True,
) -> CommandFilter:
    """Create a command filter."""
    return CommandFilter(commands, prefix, ignore_case)


def regex_filter(pattern: str, flags: int = 0) -> RegexFilter:
    """Create a regex filter."""
    return RegexFilter(pattern, flags)


def chat_type(chat_types: Union[ChatType, List[ChatType]]) -> ChatTypeFilter:
    """Create a chat type filter."""
    return ChatTypeFilter(chat_types)


def user(
    user_ids: Optional[Union[int, List[int]]] = None,
    usernames: Optional[Union[str, List[str]]] = None,
    exclude: bool = False,
) -> UserFilter:
    """Create a user filter."""
    return UserFilter(user_ids, usernames, exclude)


def update_type(update_types: Union[UpdateType, List[UpdateType]]) -> UpdateTypeFilter:
    """Create an update type filter."""
    return UpdateTypeFilter(update_types)


def all_(*filters: Filter) -> AndFilter:
    """Create an AND filter."""
    return AndFilter(*filters)


def any_(*filters: Filter) -> OrFilter:
    """Create an OR filter."""
    return OrFilter(*filters)


def not_(filter_obj: Filter) -> NotFilter:
    """Create a NOT filter."""
    return NotFilter(filter_obj)
