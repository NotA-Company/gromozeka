"""
Update models for Max Messenger Bot API.

This module provides data models for handling various types of bot updates from the
Max Messenger API. It includes the base Update class, specific update event types
for different scenarios (messages, callbacks, chat events, etc.), and the UpdateList
container for managing multiple updates.

Key Classes:
    UpdateType: Enum defining all possible update event types
    Update: Base class for all update events
    MessageCreatedUpdate: Update for new messages
    MessageCallbackUpdate: Update for button callback events
    MessageEditedUpdate: Update for edited messages
    MessageRemovedUpdate: Update for deleted messages
    BotAddedUpdate: Update when bot is added to a chat
    BotRemovedFromChatUpdate: Update when bot is removed from a chat
    DialogMutedUpdate: Update when dialog is muted
    DialogUnmutedUpdate: Update when dialog is unmuted
    DialogClearedUpdate: Update when dialog history is cleared
    DialogRemovedUpdate: Update when dialog is removed
    UserAddedToChatUpdate: Update when user is added to a chat
    UserRemovedFromChatUpdate: Update when user is removed from a chat
    BotStartedUpdate: Update when bot is started
    BotStoppedUpdate: Update when bot is stopped
    ChatTitleChangedUpdate: Update when chat title is changed
    MessageChatCreatedUpdate: Update when a chat is created via message button
    UpdateList: Container for multiple updates with pagination marker

All update classes inherit from BaseMaxBotModel and support deserialization from
API response dictionaries via the from_dict() class method.
"""

import logging
from enum import StrEnum
from typing import Any, Dict, Final, List, Optional

from .base import BaseMaxBotModel
from .callback import Callback
from .chat import Chat
from .message import Message
from .user import UserWithPhoto

logger = logging.getLogger(__name__)


class UpdateType(StrEnum):
    """Enum defining all possible update event types from Max Messenger API.

    This enum categorizes the different types of events that can be received
    by a bot, including message events, chat events, user events, and bot lifecycle events.

    Attributes:
        UNKNOWN: Unknown or unrecognized update type
        MESSAGE_CREATED: A new message was created
        MESSAGE_CALLBACK: A button callback was triggered
        MESSAGE_EDITED: A message was edited
        MESSAGE_REMOVED: A message was deleted
        BOT_ADDED: Bot was added to a chat
        BOT_REMOVED: Bot was removed from a chat
        DIALOG_MUTED: Dialog notifications were muted
        DIALOG_UNMUTED: Dialog notifications were unmuted
        DIALOG_CLEARED: Dialog history was cleared
        DIALOG_REMOVED: Dialog was removed
        USER_ADDED: User was added to a chat
        USER_REMOVED: User was removed from a chat
        BOT_STARTED: Bot was started by a user
        BOT_STOPPED: Bot was stopped by a user
        CHAT_TITLE_CHANGED: Chat title was changed
        MESSAGE_CHAT_CREATED: Chat was created via message button
    """

    UNKNOWN = "unknown"

    MESSAGE_CREATED = "message_created"
    MESSAGE_CALLBACK = "message_callback"
    MESSAGE_EDITED = "message_edited"
    MESSAGE_REMOVED = "message_removed"
    BOT_ADDED = "bot_added"
    BOT_REMOVED = "bot_removed"
    DIALOG_MUTED = "dialog_muted"
    DIALOG_UNMUTED = "dialog_unmuted"
    DIALOG_CLEARED = "dialog_cleared"
    DIALOG_REMOVED = "dialog_removed"
    USER_ADDED = "user_added"
    USER_REMOVED = "user_removed"
    BOT_STARTED = "bot_started"
    BOT_STOPPED = "bot_stopped"
    CHAT_TITLE_CHANGED = "chat_title_changed"
    MESSAGE_CHAT_CREATED = "message_chat_created"


class Update(BaseMaxBotModel):
    """Base class for all update event types from Max Messenger API.

    This class represents various types of events that occur in a chat. It serves as
    the parent class for all specific update types. Each update contains a timestamp
    and an update type identifier.

    Attributes:
        UPDATE_TYPE: Default update type for this class (UNKNOWN for base class)
        update_type: Type of the update event
        timestamp: Unix timestamp when the event occurred

    Args:
        timestamp: Unix timestamp when the event occurred
        update_type: Type of the update event. Defaults to class UPDATE_TYPE
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("update_type", "timestamp")

    UPDATE_TYPE: UpdateType = UpdateType.UNKNOWN

    def __init__(
        self,
        *,
        timestamp: int,
        update_type: Optional[UpdateType] = None,
        api_kwargs: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.update_type: UpdateType = update_type if update_type is not None else self.UPDATE_TYPE
        """Type of the update"""
        self.timestamp: int = timestamp
        """Unix-время, когда произошло событие"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Update":
        """Create Update instance from API response dictionary.

        Deserializes the API response data into an Update object, extracting
        the update_type and timestamp fields. Any extra fields are stored in
        the api_kwargs attribute.

        Args:
            data: Dictionary containing API response data with keys like
                'update_type' and 'timestamp'

        Returns:
            Update: New Update instance with data from the dictionary

        Raises:
            ValueError: If update_type value is not a valid UpdateType enum value
        """
        ret = cls(
            update_type=UpdateType(data.get("update_type", "unknown")),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )
        return ret


class MessageCreatedUpdate(Update):
    """Update event for new messages created in a chat.

    This update is received when a new message is sent to a chat where the bot
    is present. It contains the full message object and optionally the user's locale.

    Attributes:
        UPDATE_TYPE: Update type constant (MESSAGE_CREATED)
        message: The new message that was created
        user_locale: User's locale in IETF BCP 47 format (e.g., 'en-US')

    Args:
        message: The new message object
        user_locale: User's locale in IETF BCP 47 format. Defaults to None
        timestamp: Unix timestamp when the message was created
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("message", "user_locale")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.MESSAGE_CREATED

    def __init__(
        self,
        *,
        message: Message,
        user_locale: Optional[str] = None,
        timestamp: int,
        api_kwargs: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            timestamp=timestamp,
            api_kwargs=api_kwargs,
        )
        self.message: Message = message
        """New message"""
        self.user_locale: Optional[str] = user_locale
        """User locale"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageCreatedUpdate":
        """Create MessageCreatedUpdate instance from API response dictionary.

        Deserializes the API response data into a MessageCreatedUpdate object,
        extracting the message, user_locale, and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'message', 'user_locale', and 'timestamp'

        Returns:
            MessageCreatedUpdate: New MessageCreatedUpdate instance with data from the dictionary
        """
        return cls(
            message=Message.from_dict(data.get("message", {})),
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MessageCallbackUpdate(Update):
    """Update event for button callback interactions.

    This update is received when a user presses a button on an inline keyboard.
    It contains the callback data and optionally the original message that
    contained the keyboard.

    Attributes:
        UPDATE_TYPE: Update type constant (MESSAGE_CALLBACK)
        callback: The callback object containing button data
        message: Original message containing the inline keyboard. May be None
            if the message was deleted before the bot received this update
        user_locale: User's current locale in IETF BCP 47 format (e.g., 'en-US')

    Args:
        callback: The callback object with button interaction data
        message: Original message containing the inline keyboard. Defaults to None
        user_locale: User's current locale in IETF BCP 47 format. Defaults to None
        timestamp: Unix timestamp when the callback was triggered
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("callback", "message", "user_locale")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.MESSAGE_CALLBACK

    def __init__(
        self,
        *,
        callback: Callback,
        message: Optional[Message] = None,
        user_locale: Optional[str] = None,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.callback: Callback = callback
        self.message: Optional[Message] = message
        """
        Изначальное сообщение, содержащее встроенную клавиатуру.
        Может быть `null`, если оно было удалено к моменту, когда бот получил это обновление
        """
        self.user_locale: Optional[str] = user_locale
        """Текущий язык пользователя в формате IETF BCP 47"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageCallbackUpdate":
        """Create MessageCallbackUpdate instance from API response dictionary.

        Deserializes the API response data into a MessageCallbackUpdate object,
        extracting the callback, message, user_locale, and timestamp fields.
        The message field is only populated if present in the data.

        Args:
            data: Dictionary containing API response data with keys like
                'callback', 'message', 'user_locale', and 'timestamp'

        Returns:
            MessageCallbackUpdate: New MessageCallbackUpdate instance with data from the dictionary
        """
        message: Optional[Message] = None
        if data.get("message", None) is not None:
            message = Message.from_dict(data.get("message", {}))

        return cls(
            callback=Callback.from_dict(data.get("callback", {})),
            message=message,
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MessageEditedUpdate(Update):
    """Update event for edited messages.

    This update is received when a message in a chat is edited. It contains
    the updated message object with the new content.

    Attributes:
        UPDATE_TYPE: Update type constant (MESSAGE_EDITED)
        message: The edited message with updated content

    Args:
        message: The edited message object
        timestamp: Unix timestamp when the message was edited
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("message",)

    UPDATE_TYPE: Final[UpdateType] = UpdateType.MESSAGE_EDITED

    def __init__(
        self,
        *,
        message: Message,
        timestamp: int,
        api_kwargs: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            timestamp=timestamp,
            api_kwargs=api_kwargs,
        )
        self.message: Message = message

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageEditedUpdate":
        """Create MessageEditedUpdate instance from API response dictionary.

        Deserializes the API response data into a MessageEditedUpdate object,
        extracting the message and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'message' and 'timestamp'

        Returns:
            MessageEditedUpdate: New MessageEditedUpdate instance with data from the dictionary
        """

        return cls(
            message=Message.from_dict(data.get("message", {})),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MessageRemovedUpdate(Update):
    """Update event for deleted messages.

    This update is received when a message is deleted from a chat. It contains
    the message ID, chat ID, and the ID of the user who deleted the message.

    Attributes:
        UPDATE_TYPE: Update type constant (MESSAGE_REMOVED)
        message_id: ID of the deleted message
        chat_id: ID of the chat where the message was deleted
        user_id: ID of the user who deleted the message

    Args:
        message_id: ID of the deleted message
        chat_id: ID of the chat where the message was deleted
        user_id: ID of the user who deleted the message
        timestamp: Unix timestamp when the message was deleted
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("message_id", "chat_id", "user_id")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.MESSAGE_REMOVED

    def __init__(
        self,
        *,
        message_id: str,
        chat_id: int,
        user_id: int,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.message_id: str = message_id
        """ID удаленного сообщения"""
        self.chat_id: int = chat_id
        """ID чата, где сообщение было удалено"""
        self.user_id: int = user_id
        """Пользователь, удаливший сообщение"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageRemovedUpdate":
        """Create MessageRemovedUpdate instance from API response dictionary.

        Deserializes the API response data into a MessageRemovedUpdate object,
        extracting the message_id, chat_id, user_id, and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'message_id', 'chat_id', 'user_id', and 'timestamp'

        Returns:
            MessageRemovedUpdate: New MessageRemovedUpdate instance with data from the dictionary
        """
        return cls(
            message_id=data.get("message_id", ""),
            chat_id=data.get("chat_id", 0),
            user_id=data.get("user_id", 0),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class BotAddedUpdate(Update):
    """Update event for when a bot is added to a chat.

    This update is received when the bot is added to a chat. It contains the
    chat ID, the user who added the bot, and a flag indicating whether the
    chat is a channel.

    Attributes:
        UPDATE_TYPE: Update type constant (BOT_ADDED)
        chat_id: ID of the chat where the bot was added
        user: User who added the bot to the chat
        is_channel: Whether the bot was added to a channel

    Args:
        chat_id: ID of the chat where the bot was added
        user: User who added the bot to the chat
        is_channel: Whether the bot was added to a channel
        timestamp: Unix timestamp when the bot was added
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("chat_id", "user", "is_channel")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.BOT_ADDED

    def __init__(
        self,
        *,
        chat_id: int,
        user: UserWithPhoto,
        is_channel: bool,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        """ID чата, куда был добавлен бот"""
        self.user: UserWithPhoto = user
        """Пользователь, добавивший бота в чат"""
        self.is_channel: bool = is_channel
        """Указывает, был ли бот добавлен в канал или нет"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotAddedUpdate":
        """Create BotAddedUpdate instance from API response dictionary.

        Deserializes the API response data into a BotAddedUpdate object,
        extracting the chat_id, user, is_channel, and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'chat_id', 'user', 'is_channel', and 'timestamp'

        Returns:
            BotAddedUpdate: New BotAddedUpdate instance with data from the dictionary
        """
        return cls(
            chat_id=data.get("chat_id", 0),
            user=UserWithPhoto.from_dict(data.get("user", {})),
            is_channel=data.get("is_channel", False),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class BotRemovedFromChatUpdate(Update):
    """Update event for when a bot is removed from a chat.

    This update is received when the bot is removed from a chat. It contains
    the chat ID, the user who removed the bot, and a flag indicating whether
    the chat is a channel.

    Attributes:
        UPDATE_TYPE: Update type constant (BOT_REMOVED)
        chat_id: ID of the chat where the bot was removed
        user: User who removed the bot from the chat
        is_channel: Whether the bot was removed from a channel

    Args:
        chat_id: ID of the chat where the bot was removed
        user: User who removed the bot from the chat
        is_channel: Whether the bot was removed from a channel
        timestamp: Unix timestamp when the bot was removed
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("chat_id", "user", "is_channel")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.BOT_REMOVED

    def __init__(
        self,
        *,
        chat_id: int,
        user: UserWithPhoto,
        is_channel: bool,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        """ID чата, откуда был удален бот"""
        self.user: UserWithPhoto = user
        """Пользователь, удаливший бота из чата"""
        self.is_channel: bool = is_channel
        """Указывает, был ли бот удален из канала или нет"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotRemovedFromChatUpdate":
        """Create BotRemovedFromChatUpdate instance from API response dictionary.

        Deserializes the API response data into a BotRemovedFromChatUpdate object,
        extracting the chat_id, user, is_channel, and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'chat_id', 'user', 'is_channel', and 'timestamp'

        Returns:
            BotRemovedFromChatUpdate: New BotRemovedFromChatUpdate instance with data from the dictionary
        """
        return cls(
            chat_id=data.get("chat_id", 0),
            user=UserWithPhoto.from_dict(data.get("user", {})),
            is_channel=data.get("is_channel", False),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class DialogMutedUpdate(Update):
    """Update event for when a user mutes a dialog with the bot.

    This update is received when a user disables notifications for a dialog
    with the bot. It contains the chat ID, user who muted the dialog, the
    time until which the dialog is muted, and the user's locale.

    Attributes:
        UPDATE_TYPE: Update type constant (DIALOG_MUTED)
        chat_id: ID of the chat where the event occurred
        user: User who disabled notifications
        muted_until: Unix timestamp until which the dialog is muted
        user_locale: User's current locale in IETF BCP 47 format (e.g., 'en-US')

    Args:
        chat_id: ID of the chat where the event occurred
        user: User who disabled notifications
        muted_until: Unix timestamp until which the dialog is muted
        user_locale: User's current locale in IETF BCP 47 format. Defaults to None
        timestamp: Unix timestamp when the dialog was muted
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("chat_id", "user", "muted_until", "user_locale")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.DIALOG_MUTED

    def __init__(
        self,
        *,
        chat_id: int,
        user: UserWithPhoto,
        muted_until: int,
        user_locale: Optional[str] = None,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        """ID чата, где произошло событие"""
        self.user: UserWithPhoto = user
        """Пользователь, который отключил уведомления"""
        self.muted_until: int = muted_until
        """Время в формате Unix, до наступления которого диалог был отключен"""
        self.user_locale: Optional[str] = user_locale
        """Текущий язык пользователя в формате IETF BCP 47"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DialogMutedUpdate":
        """Create DialogMutedUpdate instance from API response dictionary.

        Deserializes the API response data into a DialogMutedUpdate object,
        extracting the chat_id, user, muted_until, user_locale, and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'chat_id', 'user', 'muted_until', 'user_locale', and 'timestamp'

        Returns:
            DialogMutedUpdate: New DialogMutedUpdate instance with data from the dictionary
        """
        return cls(
            chat_id=data.get("chat_id", 0),
            user=UserWithPhoto.from_dict(data.get("user", {})),
            muted_until=data.get("muted_until", 0),
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class DialogUnmutedUpdate(Update):
    """Update event for when a user enables notifications in a dialog with the bot.

    This update is received when a user re-enables notifications for a dialog
    with the bot after it was muted. It contains the chat ID, user who enabled
    notifications, and the user's locale.

    Attributes:
        UPDATE_TYPE: Update type constant (DIALOG_UNMUTED)
        chat_id: ID of the chat where the event occurred
        user: User who enabled notifications
        user_locale: User's current locale in IETF BCP 47 format (e.g., 'en-US')

    Args:
        chat_id: ID of the chat where the event occurred
        user: User who enabled notifications
        user_locale: User's current locale in IETF BCP 47 format. Defaults to None
        timestamp: Unix timestamp when notifications were enabled
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("chat_id", "user", "user_locale")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.DIALOG_UNMUTED

    def __init__(
        self,
        *,
        chat_id: int,
        user: UserWithPhoto,
        user_locale: Optional[str] = None,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        """ID чата, где произошло событие"""
        self.user: UserWithPhoto = user
        """Пользователь, который включил уведомления"""
        self.user_locale: Optional[str] = user_locale
        """Текущий язык пользователя в формате IETF BCP 47"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DialogUnmutedUpdate":
        """Create DialogUnmutedUpdate instance from API response dictionary.

        Deserializes the API response data into a DialogUnmutedUpdate object,
        extracting the chat_id, user, user_locale, and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'chat_id', 'user', 'user_locale', and 'timestamp'

        Returns:
            DialogUnmutedUpdate: New DialogUnmutedUpdate instance with data from the dictionary
        """

        return cls(
            chat_id=data.get("chat_id", 0),
            user=UserWithPhoto.from_dict(data.get("user", {})),
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class DialogClearedUpdate(Update):
    """Update event for when a user clears the dialog history.

    This update is received immediately after a user clears the message history
    in a dialog with the bot. It contains the chat ID, user who cleared the
    history, and the user's locale.

    Attributes:
        UPDATE_TYPE: Update type constant (DIALOG_CLEARED)
        chat_id: ID of the chat where the event occurred
        user: User who cleared the dialog history
        user_locale: User's current locale in IETF BCP 47 format (e.g., 'en-US')

    Args:
        chat_id: ID of the chat where the event occurred
        user: User who cleared the dialog history
        user_locale: User's current locale in IETF BCP 47 format. Defaults to None
        timestamp: Unix timestamp when the dialog was cleared
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("chat_id", "user", "user_locale")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.DIALOG_CLEARED

    def __init__(
        self,
        *,
        chat_id: int,
        user: UserWithPhoto,
        user_locale: Optional[str] = None,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        """ID чата, где произошло событие"""
        self.user: UserWithPhoto = user
        """Пользователь, который включил уведомления"""
        self.user_locale: Optional[str] = user_locale
        """Текущий язык пользователя в формате IETF BCP 47"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DialogClearedUpdate":
        """Create DialogClearedUpdate instance from API response dictionary.

        Deserializes the API response data into a DialogClearedUpdate object,
        extracting the chat_id, user, user_locale, and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'chat_id', 'user', 'user_locale', and 'timestamp'

        Returns:
            DialogClearedUpdate: New DialogClearedUpdate instance with data from the dictionary
        """
        return cls(
            chat_id=data.get("chat_id", 0),
            user=UserWithPhoto.from_dict(data.get("user", {})),
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class DialogRemovedUpdate(Update):
    """Update event for when a user removes a chat.

    This update is received when a user deletes or removes a chat with the bot.
    It contains the chat ID, user who removed the chat, and the user's locale.

    Attributes:
        UPDATE_TYPE: Update type constant (DIALOG_REMOVED)
        chat_id: ID of the chat where the event occurred
        user: User who removed the chat
        user_locale: User's current locale in IETF BCP 47 format (e.g., 'en-US')

    Args:
        chat_id: ID of the chat where the event occurred
        user: User who removed the chat
        user_locale: User's current locale in IETF BCP 47 format. Defaults to None
        timestamp: Unix timestamp when the chat was removed
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("chat_id", "user", "user_locale")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.DIALOG_REMOVED

    def __init__(
        self,
        *,
        chat_id: int,
        user: UserWithPhoto,
        user_locale: Optional[str] = None,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        """ID чата, где произошло событие"""
        self.user: UserWithPhoto = user
        """Пользователь, который удалил чат"""
        self.user_locale: Optional[str] = user_locale
        """Текущий язык пользователя в формате IETF BCP 47"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DialogRemovedUpdate":
        """Create DialogRemovedUpdate instance from API response dictionary.

        Deserializes the API response data into a DialogRemovedUpdate object,
        extracting the chat_id, user, user_locale, and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'chat_id', 'user', 'user_locale', and 'timestamp'

        Returns:
            DialogRemovedUpdate: New DialogRemovedUpdate instance with data from the dictionary
        """

        return cls(
            chat_id=data.get("chat_id", 0),
            user=UserWithPhoto.from_dict(data.get("user", {})),
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class UserAddedToChatUpdate(Update):
    """Update event for when a user is added to a chat where the bot is an admin.

    This update is received when a user is added to a chat where the bot has
    administrator privileges. It contains the chat ID, the user who was added,
    the inviter (if applicable), and a flag indicating whether it's a channel.

    Attributes:
        UPDATE_TYPE: Update type constant (USER_ADDED)
        chat_id: ID of the chat where the event occurred
        user: User who was added to the chat
        inviter_id: ID of the user who added the user to the chat. May be None
            if the user joined via a link
        is_channel: Whether the user was added to a channel

    Args:
        chat_id: ID of the chat where the event occurred
        user: User who was added to the chat
        inviter_id: ID of the user who added the user to the chat. Defaults to None
        is_channel: Whether the user was added to a channel
        timestamp: Unix timestamp when the user was added
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("chat_id", "user", "inviter_id", "is_channel")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.USER_ADDED

    def __init__(
        self,
        *,
        chat_id: int,
        user: UserWithPhoto,
        inviter_id: Optional[int] = None,
        is_channel: bool,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        """ID чата, где произошло событие"""
        self.user: UserWithPhoto = user
        """Пользователь, добавленный в чат"""
        self.inviter_id: Optional[int] = inviter_id
        """
        Пользователь, который добавил пользователя в чат.
        Может быть `null`, если пользователь присоединился к чату по ссылке
        """
        self.is_channel: bool = is_channel
        """Указывает, был ли пользователь добавлен в канал или нет"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserAddedToChatUpdate":
        """Create UserAddedToChatUpdate instance from API response dictionary.

        Deserializes the API response data into a UserAddedToChatUpdate object,
        extracting the chat_id, user, inviter_id, is_channel, and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'chat_id', 'user', 'inviter_id', 'is_channel', and 'timestamp'

        Returns:
            UserAddedToChatUpdate: New UserAddedToChatUpdate instance with data from the dictionary
        """
        return cls(
            chat_id=data.get("chat_id", 0),
            user=UserWithPhoto.from_dict(data.get("user", {})),
            inviter_id=data.get("inviter_id", None),
            is_channel=data.get("is_channel", False),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class UserRemovedFromChatUpdate(Update):
    """Update event for when a user is removed from a chat where the bot is an admin.

    This update is received when a user is removed from a chat where the bot has
    administrator privileges. It contains the chat ID, the user who was removed,
    the admin who removed them (if applicable), and a flag indicating whether it's a channel.

    Attributes:
        UPDATE_TYPE: Update type constant (USER_REMOVED)
        chat_id: ID of the chat where the event occurred
        user: User who was removed from the chat
        admin_id: ID of the admin who removed the user. May be None if the
            user left the chat voluntarily
        is_channel: Whether the user was removed from a channel

    Args:
        chat_id: ID of the chat where the event occurred
        user: User who was removed from the chat
        admin_id: ID of the admin who removed the user. Defaults to None
        is_channel: Whether the user was removed from a channel
        timestamp: Unix timestamp when the user was removed
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("chat_id", "user", "admin_id", "is_channel")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.USER_REMOVED

    def __init__(
        self,
        *,
        chat_id: int,
        user: UserWithPhoto,
        admin_id: Optional[int] = None,
        is_channel: bool,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        """ID чата, где произошло событие"""
        self.user: UserWithPhoto = user
        """Пользователь, удаленный из чата"""
        self.admin_id: Optional[int] = admin_id
        """
        Администратор, который удалил пользователя из чата.
        Может быть `null`, если пользователь покинул чат сам
        """
        self.is_channel: bool = is_channel
        """Указывает, был ли пользователь удален из канала или нет"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserRemovedFromChatUpdate":
        """Create UserRemovedFromChatUpdate instance from API response dictionary.

        Deserializes the API response data into a UserRemovedFromChatUpdate object,
        extracting the chat_id, user, admin_id, is_channel, and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'chat_id', 'user', 'admin_id', 'is_channel', and 'timestamp'

        Returns:
            UserRemovedFromChatUpdate: New UserRemovedFromChatUpdate instance with data from the dictionary
        """
        return cls(
            chat_id=data.get("chat_id", 0),
            user=UserWithPhoto.from_dict(data.get("user", {})),
            admin_id=data.get("admin_id", None),
            is_channel=data.get("is_channel", False),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class BotStartedUpdate(Update):
    """Update event for when a user starts a bot.

    This update is received when a user presses the 'Start' button to begin
    interacting with the bot. It contains the chat ID, the user who started
    the bot, an optional payload from deep links, and the user's locale.

    Attributes:
        UPDATE_TYPE: Update type constant (BOT_STARTED)
        chat_id: ID of the dialog where the event occurred
        user: User who pressed the 'Start' button
        payload: Additional data from deep links passed when starting the bot
        user_locale: User's current locale in IETF BCP 47 format (e.g., 'en-US')

    Args:
        chat_id: ID of the dialog where the event occurred
        user: User who pressed the 'Start' button
        payload: Additional data from deep links. Defaults to None
        user_locale: User's current locale in IETF BCP 47 format. Defaults to None
        timestamp: Unix timestamp when the bot was started
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("chat_id", "user", "payload", "user_locale")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.BOT_STARTED

    def __init__(
        self,
        *,
        chat_id: int,
        user: UserWithPhoto,
        payload: Optional[str] = None,
        user_locale: Optional[str] = None,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        """ID диалога, где произошло событие"""
        self.user: UserWithPhoto = user
        """Пользователь, который нажал кнопку 'Start'"""
        self.payload: Optional[str] = payload
        """Дополнительные данные из дип-линков, переданные при запуске бота"""
        self.user_locale: Optional[str] = user_locale
        """Текущий язык пользователя в формате IETF BCP 47"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotStartedUpdate":
        """Create BotStartedUpdate instance from API response dictionary.

        Deserializes the API response data into a BotStartedUpdate object,
        extracting the chat_id, user, payload, user_locale, and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'chat_id', 'user', 'payload', 'user_locale', and 'timestamp'

        Returns:
            BotStartedUpdate: New BotStartedUpdate instance with data from the dictionary
        """

        return cls(
            chat_id=data.get("chat_id", 0),
            user=UserWithPhoto.from_dict(data.get("user", {})),
            payload=data.get("payload", None),
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class BotStoppedUpdate(Update):
    """Update event for when a user stops a bot.

    This update is received when a user stops interacting with the bot. It
    contains the chat ID, the user who stopped the bot, and the user's locale.

    Attributes:
        UPDATE_TYPE: Update type constant (BOT_STOPPED)
        chat_id: ID of the dialog where the event occurred
        user: User who stopped the bot
        user_locale: User's current locale in IETF BCP 47 format (e.g., 'en-US')

    Args:
        chat_id: ID of the dialog where the event occurred
        user: User who stopped the bot
        user_locale: User's current locale in IETF BCP 47 format. Defaults to None
        timestamp: Unix timestamp when the bot was stopped
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("chat_id", "user", "user_locale")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.BOT_STOPPED

    def __init__(
        self,
        *,
        chat_id: int,
        user: UserWithPhoto,
        user_locale: Optional[str] = None,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        """ID диалога, где произошло событие"""
        self.user: UserWithPhoto = user
        """Пользователь, который остановил чат"""
        self.user_locale: Optional[str] = user_locale
        """Текущий язык пользователя в формате IETF BCP 47"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotStoppedUpdate":
        """Create BotStoppedUpdate instance from API response dictionary.

        Deserializes the API response data into a BotStoppedUpdate object,
        extracting the chat_id, user, user_locale, and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'chat_id', 'user', 'user_locale', and 'timestamp'

        Returns:
            BotStoppedUpdate: New BotStoppedUpdate instance with data from the dictionary
        """

        return cls(
            chat_id=data.get("chat_id", 0),
            user=UserWithPhoto.from_dict(data.get("user", {})),
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ChatTitleChangedUpdate(Update):
    """Update event for when a chat title is changed.

    This update is received when the title of a chat is changed. It contains
    the chat ID, the user who changed the title, and the new title.

    Attributes:
        UPDATE_TYPE: Update type constant (CHAT_TITLE_CHANGED)
        chat_id: ID of the chat where the event occurred
        user: User who changed the title
        title: New chat title

    Args:
        chat_id: ID of the chat where the event occurred
        user: User who changed the title
        title: New chat title
        timestamp: Unix timestamp when the title was changed
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("chat_id", "user", "title")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.CHAT_TITLE_CHANGED

    def __init__(
        self,
        *,
        chat_id: int,
        user: UserWithPhoto,
        title: str,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        """ID чата, где произошло событие"""
        self.user: UserWithPhoto = user
        """Пользователь, который изменил название"""
        self.title: str = title
        """Новое название"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatTitleChangedUpdate":
        """Create ChatTitleChangedUpdate instance from API response dictionary.

        Deserializes the API response data into a ChatTitleChangedUpdate object,
        extracting the chat_id, user, title, and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'chat_id', 'user', 'title', and 'timestamp'

        Returns:
            ChatTitleChangedUpdate: New ChatTitleChangedUpdate instance with data from the dictionary
        """

        return cls(
            chat_id=data.get("chat_id", 0),
            user=UserWithPhoto.from_dict(data.get("user", {})),
            title=data.get("title", ""),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MessageChatCreatedUpdate(Update):
    """Update event for when a chat is created via a message button.

    This update is received when a chat is created as soon as the first user
    presses a chat button. It contains the created chat object, the message ID
    where the button was pressed, and an optional payload from the button.

    Attributes:
        UPDATE_TYPE: Update type constant (MESSAGE_CHAT_CREATED)
        chat: The created chat object
        message_id: ID of the message where the button was pressed
        start_payload: Payload from the chat button

    Args:
        chat: The created chat object
        message_id: ID of the message where the button was pressed
        start_payload: Payload from the chat button. Defaults to None
        timestamp: Unix timestamp when the chat was created
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("chat", "message_id", "start_payload")

    UPDATE_TYPE: Final[UpdateType] = UpdateType.MESSAGE_CHAT_CREATED

    def __init__(
        self,
        *,
        chat: Chat,
        message_id: str,
        start_payload: Optional[str] = None,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat: Chat = chat
        """Созданный чат"""
        self.message_id: str = message_id
        """ID сообщения, где была нажата кнопка"""
        self.start_payload: Optional[str] = start_payload
        """Полезная нагрузка от кнопки чата"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageChatCreatedUpdate":
        """Create MessageChatCreatedUpdate instance from API response dictionary.

        Deserializes the API response data into a MessageChatCreatedUpdate object,
        extracting the chat, message_id, start_payload, and timestamp fields.

        Args:
            data: Dictionary containing API response data with keys like
                'chat', 'message_id', 'start_payload', and 'timestamp'

        Returns:
            MessageChatCreatedUpdate: New MessageChatCreatedUpdate instance with data from the dictionary
        """

        return cls(
            chat=Chat.from_dict(data.get("chat", {})),
            message_id=data.get("message_id", ""),
            start_payload=data.get("start_payload", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class UpdateList(BaseMaxBotModel):
    """Container for a list of updates with pagination support.

    This class represents a paginated list of updates from the Max Messenger API.
    It contains an array of update objects and an optional marker for fetching
    the next page of updates.

    Attributes:
        updates: Array of Update objects representing the updates
        marker: Optional marker for the next request to fetch more updates

    Args:
        updates: List of Update objects
        marker: Optional marker for the next request. Defaults to None
        api_kwargs: Additional API keyword arguments not handled by the model
    """

    __slots__ = ("updates", "marker")

    def __init__(
        self, *, updates: List[Update], marker: Optional[int] = None, api_kwargs: Dict[str, Any] | None = None
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.updates: List[Update] = updates
        """Array of updates"""
        self.marker: Optional[int] = marker
        """Marker for next request"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UpdateList":
        """Create UpdateList instance from API response dictionary.

        Deserializes the API response data into an UpdateList object, extracting
        the updates array and marker. Each update in the array is deserialized
        into the appropriate Update subclass based on its update_type field.

        Args:
            data: Dictionary containing API response data with keys like
                'updates' (array of update objects) and 'marker'

        Returns:
            UpdateList: New UpdateList instance with data from the dictionary

        Raises:
            ValueError: If an update_type value is not a valid UpdateType enum value
        """
        updates_data = data.get("updates", [])
        updates = []

        for update_data in updates_data:
            updateTypeStr = update_data.get("update_type", "unknown")
            updateType: UpdateType = UpdateType.UNKNOWN
            try:
                updateType = UpdateType(updateTypeStr)
            except Exception:
                logger.error(f"Unknown UpdateType: {updateTypeStr}")

            # Create appropriate update type based on the type field
            # TODO: Make some map UpdateType -> class
            match updateType:
                case UpdateType.MESSAGE_CREATED:
                    updates.append(MessageCreatedUpdate.from_dict(update_data))
                case UpdateType.MESSAGE_CALLBACK:
                    updates.append(MessageCallbackUpdate.from_dict(update_data))
                case UpdateType.MESSAGE_EDITED:
                    updates.append(MessageEditedUpdate.from_dict(update_data))
                case UpdateType.MESSAGE_REMOVED:
                    updates.append(MessageRemovedUpdate.from_dict(update_data))
                case UpdateType.BOT_ADDED:
                    updates.append(BotAddedUpdate.from_dict(update_data))
                case UpdateType.BOT_REMOVED:
                    updates.append(BotRemovedFromChatUpdate.from_dict(update_data))
                case UpdateType.DIALOG_MUTED:
                    updates.append(DialogMutedUpdate.from_dict(update_data))
                case UpdateType.DIALOG_UNMUTED:
                    updates.append(DialogUnmutedUpdate.from_dict(update_data))
                case UpdateType.DIALOG_CLEARED:
                    updates.append(DialogClearedUpdate.from_dict(update_data))
                case UpdateType.DIALOG_REMOVED:
                    updates.append(DialogRemovedUpdate.from_dict(update_data))
                case UpdateType.USER_ADDED:
                    updates.append(UserAddedToChatUpdate.from_dict(update_data))
                case UpdateType.USER_REMOVED:
                    updates.append(UserRemovedFromChatUpdate.from_dict(update_data))
                case UpdateType.BOT_STARTED:
                    updates.append(BotStartedUpdate.from_dict(update_data))
                case UpdateType.BOT_STOPPED:
                    updates.append(BotStoppedUpdate.from_dict(update_data))
                case UpdateType.CHAT_TITLE_CHANGED:
                    updates.append(ChatTitleChangedUpdate.from_dict(update_data))
                case UpdateType.MESSAGE_CHAT_CREATED:
                    updates.append(MessageChatCreatedUpdate.from_dict(update_data))
                case UpdateType.UNKNOWN:
                    updates.append(Update.from_dict(update_data))
                case _:
                    logger.error("Unreached code reached, it shouldn't happen")
                    updates.append(Update.from_dict(update_data))

        return cls(
            updates=updates,
            marker=data.get("marker"),
            api_kwargs=cls._getExtraKwargs(data),
        )
