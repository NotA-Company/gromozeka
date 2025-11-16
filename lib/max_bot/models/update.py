"""
Update models for Max Messenger Bot API.

This module contains update-related dataclasses including Update, UpdateList,
and all update event types for handling bot updates.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from .chat import Chat
from .message import Message
from .user import User


class UpdateType(str, Enum):
    """
    Update type enum
    """

    MESSAGE_NEW = "message_new"
    MESSAGE_EDIT = "message_edit"
    MESSAGE_DELETE = "message_delete"
    MESSAGE_READ = "message_read"
    MESSAGE_PIN = "message_pin"
    MESSAGE_UNPIN = "message_unpin"
    CHAT_NEW = "chat_new"
    CHAT_EDIT = "chat_edit"
    CHAT_DELETE = "chat_delete"
    CHAT_MEMBER_NEW = "chat_member_new"
    CHAT_MEMBER_EDIT = "chat_member_edit"
    CHAT_MEMBER_DELETE = "chat_member_delete"
    BOT_STARTED = "bot_started"
    BOT_ADDED = "bot_added"
    BOT_REMOVED = "bot_removed"
    CALLBACK_QUERY = "callback_query"


@dataclass(slots=True)
class Update:
    """
    Base update class for all update types
    """

    update_id: int
    """Unique identifier for this update"""
    type: UpdateType
    """Type of the update"""
    timestamp: int
    """Time the update was sent in Unix time"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Update":
        """Create Update instance from API response dictionary."""
        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType(data.get("type", "message_new")),
            timestamp=data.get("timestamp", 0),
        )


@dataclass(slots=True)
class MessageNewUpdate(Update):
    """
    Update for new messages
    """

    message: Message
    """New message"""

    def __post_init__(self):
        """Set the update type to message_new."""
        self.type = UpdateType.MESSAGE_NEW

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageNewUpdate":
        """Create MessageNewUpdate instance from API response dictionary."""
        message_data = data.get("message", {})
        message = Message.from_dict(message_data)

        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.MESSAGE_NEW,
            timestamp=data.get("timestamp", 0),
            message=message,
        )


@dataclass(slots=True)
class MessageEditUpdate(Update):
    """
    Update for edited messages
    """

    message: Message
    """Edited message"""

    def __post_init__(self):
        """Set the update type to message_edit."""
        self.type = UpdateType.MESSAGE_EDIT

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageEditUpdate":
        """Create MessageEditUpdate instance from API response dictionary."""
        message_data = data.get("message", {})
        message = Message.from_dict(message_data)

        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.MESSAGE_EDIT,
            timestamp=data.get("timestamp", 0),
            message=message,
        )


@dataclass(slots=True)
class MessageDeleteUpdate(Update):
    """
    Update for deleted messages
    """

    message_id: str
    """ID of the deleted message"""
    chat_id: int
    """ID of the chat where the message was deleted"""

    def __post_init__(self):
        """Set the update type to message_delete."""
        self.type = UpdateType.MESSAGE_DELETE

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageDeleteUpdate":
        """Create MessageDeleteUpdate instance from API response dictionary."""
        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.MESSAGE_DELETE,
            timestamp=data.get("timestamp", 0),
            message_id=data.get("message_id", ""),
            chat_id=data.get("chat_id", 0),
        )


@dataclass(slots=True)
class MessageReadUpdate(Update):
    """
    Update for read messages
    """

    message_id: str
    """ID of the read message"""
    chat_id: int
    """ID of the chat where the message was read"""
    user_id: int
    """ID of the user who read the message"""

    def __post_init__(self):
        """Set the update type to message_read."""
        self.type = UpdateType.MESSAGE_READ

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageReadUpdate":
        """Create MessageReadUpdate instance from API response dictionary."""
        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.MESSAGE_READ,
            timestamp=data.get("timestamp", 0),
            message_id=data.get("message_id", ""),
            chat_id=data.get("chat_id", 0),
            user_id=data.get("user_id", 0),
        )


@dataclass(slots=True)
class MessagePinUpdate(Update):
    """
    Update for pinned messages
    """

    message: Message
    """Pinned message"""

    def __post_init__(self):
        """Set the update type to message_pin."""
        self.type = UpdateType.MESSAGE_PIN

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessagePinUpdate":
        """Create MessagePinUpdate instance from API response dictionary."""
        message_data = data.get("message", {})
        message = Message.from_dict(message_data)

        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.MESSAGE_PIN,
            timestamp=data.get("timestamp", 0),
            message=message,
        )


@dataclass(slots=True)
class MessageUnpinUpdate(Update):
    """
    Update for unpinned messages
    """

    message_id: str
    """ID of the unpinned message"""
    chat_id: int
    """ID of the chat where the message was unpinned"""

    def __post_init__(self):
        """Set the update type to message_unpin."""
        self.type = UpdateType.MESSAGE_UNPIN

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageUnpinUpdate":
        """Create MessageUnpinUpdate instance from API response dictionary."""
        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.MESSAGE_UNPIN,
            timestamp=data.get("timestamp", 0),
            message_id=data.get("message_id", ""),
            chat_id=data.get("chat_id", 0),
        )


@dataclass(slots=True)
class ChatNewUpdate(Update):
    """
    Update for new chats
    """

    chat: Chat
    """New chat"""

    def __post_init__(self):
        """Set the update type to chat_new."""
        self.type = UpdateType.CHAT_NEW

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatNewUpdate":
        """Create ChatNewUpdate instance from API response dictionary."""
        chat_data = data.get("chat", {})
        chat = Chat.from_dict(chat_data)

        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.CHAT_NEW,
            timestamp=data.get("timestamp", 0),
            chat=chat,
        )


@dataclass(slots=True)
class ChatEditUpdate(Update):
    """
    Update for edited chats
    """

    chat: Chat
    """Edited chat"""

    def __post_init__(self):
        """Set the update type to chat_edit."""
        self.type = UpdateType.CHAT_EDIT

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatEditUpdate":
        """Create ChatEditUpdate instance from API response dictionary."""
        chat_data = data.get("chat", {})
        chat = Chat.from_dict(chat_data)

        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.CHAT_EDIT,
            timestamp=data.get("timestamp", 0),
            chat=chat,
        )


@dataclass(slots=True)
class ChatDeleteUpdate(Update):
    """
    Update for deleted chats
    """

    chat_id: int
    """ID of the deleted chat"""

    def __post_init__(self):
        """Set the update type to chat_delete."""
        self.type = UpdateType.CHAT_DELETE

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatDeleteUpdate":
        """Create ChatDeleteUpdate instance from API response dictionary."""
        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.CHAT_DELETE,
            timestamp=data.get("timestamp", 0),
            chat_id=data.get("chat_id", 0),
        )


@dataclass(slots=True)
class ChatMemberNewUpdate(Update):
    """
    Update for new chat members
    """

    chat_id: int
    """ID of the chat"""
    user: User
    """New chat member"""
    inviter: Optional[User] = None
    """User who invited the member"""

    def __post_init__(self):
        """Set the update type to chat_member_new."""
        self.type = UpdateType.CHAT_MEMBER_NEW

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMemberNewUpdate":
        """Create ChatMemberNewUpdate instance from API response dictionary."""
        user_data = data.get("user", {})
        user = User.from_dict(user_data)

        inviter_data = data.get("inviter")
        inviter = None
        if inviter_data:
            inviter = User.from_dict(inviter_data)

        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.CHAT_MEMBER_NEW,
            timestamp=data.get("timestamp", 0),
            chat_id=data.get("chat_id", 0),
            user=user,
            inviter=inviter,
        )


@dataclass(slots=True)
class ChatMemberEditUpdate(Update):
    """
    Update for edited chat members
    """

    chat_id: int
    """ID of the chat"""
    user: User
    """Edited chat member"""

    def __post_init__(self):
        """Set the update type to chat_member_edit."""
        self.type = UpdateType.CHAT_MEMBER_EDIT

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMemberEditUpdate":
        """Create ChatMemberEditUpdate instance from API response dictionary."""
        user_data = data.get("user", {})
        user = User.from_dict(user_data)

        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.CHAT_MEMBER_EDIT,
            timestamp=data.get("timestamp", 0),
            chat_id=data.get("chat_id", 0),
            user=user,
        )


@dataclass(slots=True)
class ChatMemberDeleteUpdate(Update):
    """
    Update for deleted chat members
    """

    chat_id: int
    """ID of the chat"""
    user: User
    """Removed chat member"""

    def __post_init__(self):
        """Set the update type to chat_member_delete."""
        self.type = UpdateType.CHAT_MEMBER_DELETE

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMemberDeleteUpdate":
        """Create ChatMemberDeleteUpdate instance from API response dictionary."""
        user_data = data.get("user", {})
        user = User.from_dict(user_data)

        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.CHAT_MEMBER_DELETE,
            timestamp=data.get("timestamp", 0),
            chat_id=data.get("chat_id", 0),
            user=user,
        )


@dataclass(slots=True)
class BotStartedUpdate(Update):
    """
    Update for when a bot is started
    """

    user: User
    """User who started the bot"""

    def __post_init__(self):
        """Set the update type to bot_started."""
        self.type = UpdateType.BOT_STARTED

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotStartedUpdate":
        """Create BotStartedUpdate instance from API response dictionary."""
        user_data = data.get("user", {})
        user = User.from_dict(user_data)

        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.BOT_STARTED,
            timestamp=data.get("timestamp", 0),
            user=user,
        )


@dataclass(slots=True)
class BotAddedUpdate(Update):
    """
    Update for when a bot is added to a chat
    """

    chat: Chat
    """Chat the bot was added to"""
    user: User
    """User who added the bot"""

    def __post_init__(self):
        """Set the update type to bot_added."""
        self.type = UpdateType.BOT_ADDED

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotAddedUpdate":
        """Create BotAddedUpdate instance from API response dictionary."""
        chat_data = data.get("chat", {})
        chat = Chat.from_dict(chat_data)

        user_data = data.get("user", {})
        user = User.from_dict(user_data)

        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.BOT_ADDED,
            timestamp=data.get("timestamp", 0),
            chat=chat,
            user=user,
        )


@dataclass(slots=True)
class BotRemovedUpdate(Update):
    """
    Update for when a bot is removed from a chat
    """

    chat: Chat
    """Chat the bot was removed from"""
    user: User
    """User who removed the bot"""

    def __post_init__(self):
        """Set the update type to bot_removed."""
        self.type = UpdateType.BOT_REMOVED

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotRemovedUpdate":
        """Create BotRemovedUpdate instance from API response dictionary."""
        chat_data = data.get("chat", {})
        chat = Chat.from_dict(chat_data)

        user_data = data.get("user", {})
        user = User.from_dict(user_data)

        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.BOT_REMOVED,
            timestamp=data.get("timestamp", 0),
            chat=chat,
            user=user,
        )


@dataclass(slots=True)
class CallbackQueryUpdate(Update):
    """
    Update for callback queries
    """

    id: str
    """Unique identifier for this query"""
    from_user: User
    """User who sent the callback query"""
    message: Optional[Message] = None
    """Message with the callback button that originated the query"""
    data: str = ""
    """Data associated with the callback button"""

    def __post_init__(self):
        """Set the update type to callback_query."""
        self.type = UpdateType.CALLBACK_QUERY

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CallbackQueryUpdate":
        """Create CallbackQueryUpdate instance from API response dictionary."""
        from_user_data = data.get("from_user", {})
        from_user = User.from_dict(from_user_data)

        message_data = data.get("message")
        message = None
        if message_data:
            message = Message.from_dict(message_data)

        return cls(
            update_id=data.get("update_id", 0),
            type=UpdateType.CALLBACK_QUERY,
            timestamp=data.get("timestamp", 0),
            id=data.get("id", ""),
            from_user=from_user,
            message=message,
            data=data.get("data", ""),
        )


@dataclass(slots=True)
class UpdateList:
    """
    List of updates
    """

    updates: List[Update]
    """Array of updates"""
    marker: Optional[int] = None
    """Marker for next request"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UpdateList":
        """Create UpdateList instance from API response dictionary."""
        updates_data = data.get("updates", [])
        updates = []

        for update_data in updates_data:
            update_type = update_data.get("type", "message_new")

            # Create appropriate update type based on the type field
            if update_type == "message_new":
                updates.append(MessageNewUpdate.from_dict(update_data))
            elif update_type == "message_edit":
                updates.append(MessageEditUpdate.from_dict(update_data))
            elif update_type == "message_delete":
                updates.append(MessageDeleteUpdate.from_dict(update_data))
            elif update_type == "message_read":
                updates.append(MessageReadUpdate.from_dict(update_data))
            elif update_type == "message_pin":
                updates.append(MessagePinUpdate.from_dict(update_data))
            elif update_type == "message_unpin":
                updates.append(MessageUnpinUpdate.from_dict(update_data))
            elif update_type == "chat_new":
                updates.append(ChatNewUpdate.from_dict(update_data))
            elif update_type == "chat_edit":
                updates.append(ChatEditUpdate.from_dict(update_data))
            elif update_type == "chat_delete":
                updates.append(ChatDeleteUpdate.from_dict(update_data))
            elif update_type == "chat_member_new":
                updates.append(ChatMemberNewUpdate.from_dict(update_data))
            elif update_type == "chat_member_edit":
                updates.append(ChatMemberEditUpdate.from_dict(update_data))
            elif update_type == "chat_member_delete":
                updates.append(ChatMemberDeleteUpdate.from_dict(update_data))
            elif update_type == "bot_started":
                updates.append(BotStartedUpdate.from_dict(update_data))
            elif update_type == "bot_added":
                updates.append(BotAddedUpdate.from_dict(update_data))
            elif update_type == "bot_removed":
                updates.append(BotRemovedUpdate.from_dict(update_data))
            elif update_type == "callback_query":
                updates.append(CallbackQueryUpdate.from_dict(update_data))
            else:
                updates.append(Update.from_dict(update_data))

        return cls(updates=updates, marker=data.get("marker"))
