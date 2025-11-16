"""
Update models for Max Messenger Bot API.

This module contains update-related dataclasses including Update, UpdateList,
and all update event types for handling bot updates.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, Final, Iterator, List, Optional, Self

from .chat import Chat
from .message import Message
from .user import User

logger = logging.getLogger(__name__)


class UpdateType(StrEnum):
    """
    Update type enum
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


class BaseMaxBotModel:
    """
    Base Class for all models from Max Messenger Bot API
    """

    __slots__ = "api_kwargs"

    api_kwargs: Dict[str, Any]
    """Raw API response data"""

    def __init__(self, *, api_kwargs: Optional[Dict[str, Any]] = None):
        if api_kwargs is None:
            api_kwargs = {}
        self.api_kwargs = api_kwargs

    def _getAttrsNames(self, includePrivate: bool) -> Iterator[str]:
        """TODO"""
        all_slots: Iterator[str] = (s for c in self.__class__.__mro__[:-1] for s in c.__slots__)

        if includePrivate:
            return all_slots
        return (attr for attr in all_slots if not attr.startswith("_"))

    def to_dict(
        self,
        includePrivate: bool = False,
        recursive: bool = False,
    ) -> Dict[str, Any]:
        """TODO"""
        data = {}

        for key in self._getAttrsNames(includePrivate=includePrivate):
            value = getattr(self, key, None)
            if value is not None:
                if recursive and hasattr(value, "to_dict"):
                    data[key] = value.to_dict(recursive=True)
                else:
                    data[key] = value
            else:
                data[key] = value

        return data

    def __repr__(self) -> str:
        """TODO"""

        as_dict = self.to_dict(recursive=False, includePrivate=False)

        if not self.api_kwargs:
            # Drop api_kwargs from the representation, if empty
            as_dict.pop("api_kwargs", None)

        contents = ", ".join(f"{k}={as_dict[k]!r}" for k in sorted(as_dict.keys()) if (as_dict[k] is not None))
        return f"{self.__class__.__name__}({contents})"

    def __str__(self) -> str:
        """TODO"""
        return self.__repr__()

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "BaseMaxBotModel":
        """Create BaseMaxBotModel instance from API response dictionary."""
        ret = cls()
        if store_api_kwargs:
            ret.api_kwargs = data.copy()
        return ret

    def copy(self) -> Self:
        return self.__class__.from_dict(
            data=self.to_dict(includePrivate=True, recursive=True),
            store_api_kwargs=bool(self.api_kwargs),
        )  # pyright: ignore[reportReturnType]


class Callback(BaseMaxBotModel):

    __slots__ = ()

    def __init__(self, *, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "Callback":
        return cls(
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class Update(BaseMaxBotModel):
    """
    Объект `Update` представляет различные типы событий, произошедших в чате. См. его наследников
    """

    __slots__ = ("update_type", "timestamp")

    # update_type: UpdateType
    # """Type of the update"""
    # timestamp: int
    # """Unix-время, когда произошло событие"""
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
        self.timestamp: int = timestamp

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "Update":
        """Create Update instance from API response dictionary."""
        ret = cls(
            update_type=UpdateType(data.get("update_type", "unknown")),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )
        return ret


class MessageCreatedUpdate(Update):
    """
    Update for new messages
    """

    __slots__ = ("message", "user_locale")

    # user_locale: Optional[str]
    # """User locale"""
    # message: Message
    # """New message"""
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
        self.user_locale: Optional[str] = user_locale

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "MessageCreatedUpdate":
        """Create MessageNewUpdate instance from API response dictionary."""
        return cls(
            message=Message.from_dict(data.get("message", {})),
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class MessageCallbackUpdate(Update):
    """
    Вы получите этот `update` как только пользователь нажмет кнопку
    """

    __slots__ = ("callback", "message", "user_locale")

    # callback: Callback
    # message: Optional[Message]
    # """
    # Изначальное сообщение, содержащее встроенную клавиатуру.
    # Может быть `null`, если оно было удалено к моменту, когда бот получил это обновление
    # """
    # user_locale: Optional[str]
    # """Текущий язык пользователя в формате IETF BCP 47"""
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
        self.user_locale: Optional[str] = user_locale

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "MessageCallbackUpdate":
        """Create MessageCallbackUpdate instance from API response dictionary."""
        message: Optional[Message] = None
        if data.get("message", None) is not None:
            message = Message.from_dict(data.get("message", {}))

        return cls(
            callback=Callback.from_dict(data.get("callback", {})),
            message=message,
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class MessageEditedUpdate(Update):
    """
    Update for edited messages
    """

    __slots__ = ("message",)

    # message: Message
    # """Edited message"""
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
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "MessageEditedUpdate":
        """Create MessageEditedUpdate instance from API response dictionary."""

        return cls(
            message=Message.from_dict(data.get("message", {})),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class MessageRemovedUpdate(Update):
    """
    Update for deleted messages
    """

    __slots__ = ("message_id", "chat_id", "user_id")

    # message_id: str
    # """ID удаленного сообщения"""
    # chat_id: int
    # """ID чата, где сообщение было удалено"""
    # user_id: int
    # """Пользователь, удаливший сообщение"""
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
        self.chat_id: int = chat_id
        self.user_id: int = user_id

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "MessageRemovedUpdate":
        """Create MessageRemovedUpdate instance from API response dictionary."""
        return cls(
            message_id=data.get("message_id", ""),
            chat_id=data.get("chat_id", 0),
            user_id=data.get("user_id", 0),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class BotAddedUpdate(Update):
    """
    Update for when a bot is added to a chat
    """

    __slots__ = ("chat_id", "user", "is_channel")
    # chat_id: int
    # """ID чата, куда был добавлен бот"""
    # user: User
    # """Пользователь, добавивший бота в чат"""
    # is_channel: bool
    # """Указывает, был ли бот добавлен в канал или нет"""
    UPDATE_TYPE: Final[UpdateType] = UpdateType.BOT_ADDED

    def __init__(
        self,
        *,
        chat_id: int,
        user: User,
        is_channel: bool,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        self.user: User = user
        self.is_channel: bool = is_channel

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "BotAddedUpdate":
        """Create BotAddedUpdate instance from API response dictionary."""
        return cls(
            chat_id=data.get("chat_id", 0),
            user=User.from_dict(data.get("user", {})),
            is_channel=data.get("is_channel", False),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class BotRemovedFromChatUpdate(Update):
    """
    Update for when a bot is removed from a chat
    """

    __slots__ = ("chat_id", "user", "is_channel")
    # chat_id: int
    # """ID чата, откуда был удален бот"""
    # user: User
    # """Пользователь, удаливший бота из чата"""
    # is_channel: bool
    # """Указывает, был ли бот удален из канала или нет"""
    UPDATE_TYPE: Final[UpdateType] = UpdateType.BOT_REMOVED

    def __init__(
        self,
        *,
        chat_id: int,
        user: User,
        is_channel: bool,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        self.user: User = user
        self.is_channel: bool = is_channel

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "BotRemovedFromChatUpdate":
        """Create BotRemovedFromChatUpdate instance from API response dictionary."""
        return cls(
            chat_id=data.get("chat_id", 0),
            user=User.from_dict(data.get("user", {})),
            is_channel=data.get("is_channel", False),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class DialogMutedUpdate(Update):
    """
    Вы получите этот update, когда пользователь заглушит диалог с ботом
    """

    __slots__ = ("chat_id", "user", "muted_until", "user_locale")

    # chat_id: int
    # """ID чата, где произошло событие"""
    # user: User
    # """Пользователь, который отключил уведомления"""
    # muted_until: int
    # """Время в формате Unix, до наступления которого диалог был отключен"""
    # user_locale: Optional[str]
    # """Текущий язык пользователя в формате IETF BCP 47"""
    UPDATE_TYPE: Final[UpdateType] = UpdateType.DIALOG_MUTED

    def __init__(
        self,
        *,
        chat_id: int,
        user: User,
        muted_until: int,
        user_locale: Optional[str] = None,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        self.user: User = user
        self.muted_until: int = muted_until
        self.user_locale: Optional[str] = user_locale

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DialogMutedUpdate":
        """Create DialogMutedUpdate instance from API response dictionary."""
        return cls(
            chat_id=data.get("chat_id", 0),
            user=User.from_dict(data.get("user", {})),
            muted_until=data.get("muted_until", 0),
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy(),
        )


class DialogUnmutedUpdate(Update):
    """
    Вы получите этот update, когда пользователь включит уведомления в диалоге с ботом
    """

    __slots__ = ("chat_id", "user", "user_locale")

    # chat_id: int
    # """ID чата, где произошло событие"""
    # user: User
    # """Пользователь, который включил уведомления"""
    # user_locale: Optional[str]
    # """Текущий язык пользователя в формате IETF BCP 47"""
    UPDATE_TYPE: Final[UpdateType] = UpdateType.DIALOG_UNMUTED

    def __init__(
        self,
        *,
        chat_id: int,
        user: User,
        user_locale: Optional[str] = None,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        self.user: User = user
        self.user_locale: Optional[str] = user_locale

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "DialogUnmutedUpdate":
        """Create DialogUnmutedUpdate instance from API response dictionary."""

        return cls(
            chat_id=data.get("chat_id", 0),
            user=User.from_dict(data.get("user", {})),
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class DialogClearedUpdate(Update):
    """
    Бот получает этот тип обновления сразу после очистки истории диалога.
    """

    __slots__ = ("chat_id", "user", "user_locale")

    # chat_id: int
    # """ID чата, где произошло событие"""
    # user: User
    # """Пользователь, который включил уведомления"""
    # user_locale: Optional[str]
    # """Текущий язык пользователя в формате IETF BCP 47"""
    UPDATE_TYPE: Final[UpdateType] = UpdateType.DIALOG_CLEARED

    def __init__(
        self,
        *,
        chat_id: int,
        user: User,
        user_locale: Optional[str] = None,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        self.user: User = user
        self.user_locale: Optional[str] = user_locale

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "DialogClearedUpdate":
        """Create DialogClearedUpdate instance from API response dictionary."""
        return cls(
            chat_id=data.get("chat_id", 0),
            user=User.from_dict(data.get("user", {})),
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class DialogRemovedUpdate(Update):
    """
    Вы получите этот update, когда пользователь удаляет чат
    """

    __slots__ = ("chat_id", "user", "user_locale")

    # chat_id: int
    # """ID чата, где произошло событие"""
    # user: User
    # """Пользователь, который удалил чат"""
    # user_locale: Optional[str]
    # """Текущий язык пользователя в формате IETF BCP 47"""
    UPDATE_TYPE: Final[UpdateType] = UpdateType.DIALOG_REMOVED

    def __init__(
        self,
        *,
        chat_id: int,
        user: User,
        user_locale: Optional[str] = None,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        self.user: User = user
        self.user_locale: Optional[str] = user_locale

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "DialogRemovedUpdate":
        """Create DialogRemovedUpdate instance from API response dictionary."""

        return cls(
            chat_id=data.get("chat_id", 0),
            user=User.from_dict(data.get("user", {})),
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class UserAddedToChatUpdate(Update):
    """
    Вы получите это обновление, когда пользователь будет добавлен в чат, где бот является администратором
    """

    __slots__ = ("chat_id", "user", "inviter_id", "is_channel")
    # chat_id: int
    # """ID чата, где произошло событие"""
    # user: User
    # """Пользователь, добавленный в чат"""
    # inviter_id: Optional[int],
    # """
    # Пользователь, который добавил пользователя в чат.
    # Может быть `null`, если пользователь присоединился к чату по ссылке
    # """
    # is_channel: bool
    # """Указывает, был ли пользователь добавлен в канал или нет"""
    UPDATE_TYPE: Final[UpdateType] = UpdateType.USER_ADDED

    def __init__(
        self,
        *,
        chat_id: int,
        user: User,
        inviter_id: Optional[int] = None,
        is_channel: bool,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id = chat_id
        self.user = user
        self.inviter_id = inviter_id
        self.is_channel = is_channel

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "UserAddedToChatUpdate":
        """Create UserAddedToChatUpdate instance from API response dictionary."""
        return cls(
            chat_id=data.get("chat_id", 0),
            user=User.from_dict(data.get("user", {})),
            inviter_id=data.get("inviter_id", None),
            is_channel=data.get("is_channel", False),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class UserRemovedFromChatUpdate(Update):
    """
    Вы получите это обновление, когда пользователь будет удален из чата,
    где бот является администратором
    """

    __slots__ = ("chat_id", "user", "admin_id", "is_channel")

    # chat_id: int
    # """ID чата, где произошло событие"""
    # user: User
    # """Пользователь, удаленный из чата"""
    # admin_id: Optional[int]
    # """
    # Администратор, который удалил пользователя из чата.
    # Может быть `null`, если пользователь покинул чат сам
    # """
    # is_channel: bool
    # """Указывает, был ли пользователь удален из канала или нет"""
    UPDATE_TYPE: Final[UpdateType] = UpdateType.USER_REMOVED

    def __init__(
        self,
        *,
        chat_id: int,
        user: User,
        admin_id: Optional[int] = None,
        is_channel: bool,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        self.user: User = user
        self.admin_id: Optional[int] = admin_id
        self.is_channel: bool = is_channel

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "UserRemovedFromChatUpdate":
        """Create UserRemovedFromChatUpdate instance from API response dictionary."""
        return cls(
            chat_id=data.get("chat_id", 0),
            user=User.from_dict(data.get("user", {})),
            admin_id=data.get("admin_id", None),
            is_channel=data.get("is_channel", False),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class BotStartedUpdate(Update):
    """
    Update for new chat members
    """

    __slots__ = ("chat_id", "user", "payload", "user_locale")

    # chat_id: int
    # """ID диалога, где произошло событие"""
    # user: User
    # """Пользователь, который нажал кнопку 'Start'"""
    # payload: Optional[str] # Max 512
    # """Дополнительные данные из дип-линков, переданные при запуске бота"""
    # user_locale: Optional[str]
    # """Текущий язык пользователя в формате IETF BCP 47"""
    UPDATE_TYPE: Final[UpdateType] = UpdateType.BOT_STARTED

    def __init__(
        self,
        *,
        chat_id: int,
        user: User,
        payload: Optional[str] = None,
        user_locale: Optional[str] = None,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        self.user: User = user
        self.payload: Optional[str] = payload
        self.user_locale: Optional[str] = user_locale

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "BotStartedUpdate":
        """Create BotStartedUpdate instance from API response dictionary."""

        return cls(
            chat_id=data.get("chat_id", 0),
            user=User.from_dict(data.get("user", {})),
            payload=data.get("payload", None),
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class BotStoppedUpdate(Update):
    """
    Бот получает этот тип обновления, как только пользователь останавливает бота
    """

    __slots__ = ("chat_id", "user", "user_locale")

    # chat_id: int
    # """ID диалога, где произошло событие"""
    # user: User
    # """Пользователь, который остановил чат"""
    # user_locale: Optional[str]
    # """Текущий язык пользователя в формате IETF BCP 47"""
    UPDATE_TYPE: Final[UpdateType] = UpdateType.BOT_STOPPED

    def __init__(
        self,
        *,
        chat_id: int,
        user: User,
        user_locale: Optional[str] = None,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        self.user: User = user
        self.user_locale: Optional[str] = user_locale

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "BotStoppedUpdate":
        """Create BotStoppedUpdate instance from API response dictionary."""

        return cls(
            chat_id=data.get("chat_id", 0),
            user=User.from_dict(data.get("user", {})),
            user_locale=data.get("user_locale", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class ChatTitleChangedUpdate(Update):
    """
    Бот получит это обновление, когда будет изменено название чата
    """

    __slots__ = ("chat_id", "user", "title")

    # chat_id: int
    # """ID чата, где произошло событие"""
    # user: User
    # """Пользователь, который изменил название"""
    # title: str
    # """Новое название"""
    UPDATE_TYPE: Final[UpdateType] = UpdateType.CHAT_TITLE_CHANGED

    def __init__(
        self,
        *,
        chat_id: int,
        user: User,
        title: str,
        timestamp: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(timestamp=timestamp, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        self.user: User = user
        self.title: str = title

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "ChatTitleChangedUpdate":
        """Create ChatTitleChangedUpdate instance from API response dictionary."""

        return cls(
            chat_id=data.get("chat_id", 0),
            user=User.from_dict(data.get("user", {})),
            title=data.get("title", ""),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class MessageChatCreatedUpdate(Update):
    """
    Бот получит это обновление, когда чат будет создан, как только первый пользователь нажмет кнопку чата
    """

    __slots__ = ("chat", "message_id", "start_payload")

    # chat: Chat
    # """Созданный чат"""
    # message_id: str
    # """ID сообщения, где была нажата кнопка"""
    # start_payload: Optional[str]
    # """Полезная нагрузка от кнопки чата"""
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
        self.message_id: str = message_id
        self.start_payload: Optional[str] = start_payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "MessageChatCreatedUpdate":
        """Create MessageChatCreatedUpdate instance from API response dictionary."""

        return cls(
            chat=Chat.from_dict(data.get("chat", {})),
            message_id=data.get("message_id", ""),
            start_payload=data.get("start_payload", None),
            timestamp=data.get("timestamp", 0),
            api_kwargs=data.copy() if store_api_kwargs else None,
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
            updateTypeStr = update_data.get("update_type", "unknown")
            updateType: UpdateType = UpdateType.UNKNOWN
            try:
                updateType = UpdateType(updateTypeStr)
            except Exception:
                logger.error(f"Unknown UpdateType: {updateTypeStr}")

            # Create appropriate update type based on the type field
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

        return cls(updates=updates, marker=data.get("marker"))
