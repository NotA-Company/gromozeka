"""
Chat models for Max Messenger Bot API.

This module contains chat-related dataclasses including Chat, ChatMember,
ChatAdmin, ChatAdminPermission, ChatList, and ChatPatch models.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, List, Optional

from .user import UserWithPhoto


class ChatType(StrEnum):
    """
    Тип чата: диалог, чат
    """

    CHAT = "chat"
    DIALOG = "dialog"


class ChatStatus(StrEnum):
    """
    Статус чата для текущего бота
    """

    ACTIVE = "active"
    """Бот является активным участником чата."""
    REMOVED = "removed"
    """Бот был удалён из чата."""
    LEFT = "left"
    """Бот покинул чат."""
    CLOSED = "closed"
    """Чат был закрыт."""


class ChatAdminPermission(StrEnum):
    """
    Права администратора чата
    """

    READ_ALL_MESSAGES = "read_all_messages"
    """Читать все сообщения."""
    ADD_REMOVE_MEMBERS = "add_remove_members"
    """Добавлять/удалять участников."""
    ADD_ADMINS = "add_admins"
    """Добавлять администраторов."""
    CHANGE_CHAT_INFO = "change_chat_info"
    """Изменять информацию о чате."""
    PIN_MESSAGE = "pin_message"
    """Закреплять сообщения."""
    WRITE = "write"
    """Писать сообщения."""
    EDIT_LINK = "edit_link"
    """Изменять ссылку на чат."""


@dataclass(slots=True)
class Chat:
    """
    Chat model representing a Max Messenger chat
    """

    chat_id: int
    """ID чата"""
    type: ChatType
    """Тип чата:
     - `"chat"` — Групповой чат."""
    status: ChatStatus
    """Статус чата:
    - `"active"` — Бот является активным участником чата.
    - `"removed"` — Бот был удалён из чата.
    - `"left"` — Бот покинул чат.
    - `"closed"` — Чат был закрыт."""
    title: Optional[str] = None
    """Отображаемое название чата. Может быть `null` для диалогов"""
    icon: Optional[Dict[str, Any]] = None
    """Иконка чата"""
    last_event_time: int = 0
    """Время последнего события в чате"""
    participants_count: int = 0
    """Количество участников чата. Для диалогов всегда `2`"""
    owner_id: Optional[int] = None
    """ID владельца чата"""
    participants: Optional[Dict[str, int]] = None
    """Участники чата с временем последней активности. Может быть `null`, если запрашивается список чатов"""
    is_public: bool = False
    """Доступен ли чат публично (для диалогов всегда `false`)"""
    link: Optional[str] = None
    """Ссылка на чат"""
    description: Optional[str] = None
    """Описание чата"""
    dialog_with_user: Optional[UserWithPhoto] = None
    """Данные о пользователе в диалоге (только для чатов типа `"dialog"`)"""
    chat_message_id: Optional[str] = None
    """ID сообщения, содержащего кнопку, через которую был инициирован чат"""
    pinned_message: Optional[Dict[str, Any]] = None
    """Закреплённое сообщение в чате (возвращается только при запросе конкретного чата)"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Chat":
        """Create Chat instance from API response dictionary."""
        dialog_with_user_data = data.get("dialog_with_user")
        dialog_with_user = None
        if dialog_with_user_data:
            dialog_with_user = UserWithPhoto.from_dict(dialog_with_user_data)

        return cls(
            chat_id=data.get("chat_id", 0),
            type=ChatType(data.get("type", "chat")),
            status=ChatStatus(data.get("status", "active")),
            title=data.get("title"),
            icon=data.get("icon"),
            last_event_time=data.get("last_event_time", 0),
            participants_count=data.get("participants_count", 0),
            owner_id=data.get("owner_id"),
            participants=data.get("participants"),
            is_public=data.get("is_public", False),
            link=data.get("link"),
            description=data.get("description"),
            dialog_with_user=dialog_with_user,
            chat_message_id=data.get("chat_message_id"),
            pinned_message=data.get("pinned_message"),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k
                not in {
                    "chat_id",
                    "type",
                    "status",
                    "title",
                    "icon",
                    "last_event_time",
                    "participants_count",
                    "owner_id",
                    "participants",
                    "is_public",
                    "link",
                    "description",
                    "dialog_with_user",
                    "chat_message_id",
                    "pinned_message",
                }
            },
        )


@dataclass(slots=True)
class ChatMember(UserWithPhoto):
    """
    Объект, описывающий участника чата
    """

    last_access_time: int = 0
    """Время последней активности пользователя в чате. Может быть устаревшим для суперчатов (равно времени вступления)"""  # noqa: E501
    is_owner: bool = False
    """Является ли пользователь владельцем чата"""
    is_admin: bool = False
    """Является ли пользователь администратором чата"""
    join_time: int = 0
    """Дата присоединения к чату в формате Unix time"""
    permissions: Optional[List[ChatAdminPermission]] = None
    """Перечень прав пользователя. Возможные значения:
    - `"read_all_messages"` — Читать все сообщения.
    - `"add_remove_members"` — Добавлять/удалять участников.
    - `"add_admins"` — Добавлять администраторов.
    - `"change_chat_info"` — Изменять информацию о чате.
    - `"pin_message"` — Закреплять сообщения.
    - `"write"` — Писать сообщения.
    - `"edit_link"` — Изменять ссылку на чат.
    """
    alias: Optional[str] = None
    """Заголовок, который будет показан на клиенте

    Если пользователь администратор или владелец и ему не установлено это название, то поле не передается, клиенты на своей стороне подменят на "владелец" или "админ"."""  # noqa: E501

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMember":
        """Create ChatMember instance from API response dictionary."""
        permissions_data = data.get("permissions")
        permissions = None
        if permissions_data:
            permissions = [ChatAdminPermission(perm) for perm in permissions_data]

        return cls(
            user_id=data.get("user_id", 0),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name"),
            name=data.get("name"),
            username=data.get("username"),
            is_bot=data.get("is_bot", False),
            last_activity_time=data.get("last_activity_time", 0),
            description=data.get("description"),
            avatar_url=data.get("avatar_url"),
            full_avatar_url=data.get("full_avatar_url"),
            last_access_time=data.get("last_access_time", 0),
            is_owner=data.get("is_owner", False),
            is_admin=data.get("is_admin", False),
            join_time=data.get("join_time", 0),
            permissions=permissions,
            alias=data.get("alias"),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k
                not in {
                    "user_id",
                    "first_name",
                    "last_name",
                    "name",
                    "username",
                    "is_bot",
                    "last_activity_time",
                    "description",
                    "avatar_url",
                    "full_avatar_url",
                    "last_access_time",
                    "is_owner",
                    "is_admin",
                    "join_time",
                    "permissions",
                    "alias",
                }
            },
        )


@dataclass(slots=True)
class ChatAdmin:
    """
    Chat admin model with permissions
    """

    user_id: int
    """Идентификатор администратора с правами доступа"""
    permissions: List[ChatAdminPermission]
    """Перечень прав пользователя. Возможные значения:
    - `"read_all_messages"` — Читать все сообщения.
    - `"add_remove_members"` — Добавлять/удалять участников.
    - `"add_admins"` — Добавлять администраторов.
    - `"change_chat_info"` — Изменять информацию о чате.
    - `"pin_message"` — Закреплять сообщения.
    - `"write"` — Писать сообщения.
    """
    alias: Optional[str] = None
    """Заголовок, который будет показан на клиенте

    Если пользователь администратор или владелец и ему не установлено это название, то поле не передается, клиенты на своей стороне подменят на "владелец" или "админ"."""  # noqa: E501
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatAdmin":
        """Create ChatAdmin instance from API response dictionary."""
        permissions_data = data.get("permissions", [])
        permissions = [ChatAdminPermission(perm) for perm in permissions_data]

        return cls(
            user_id=data.get("user_id", 0),
            permissions=permissions,
            alias=data.get("alias"),
            api_kwargs={k: v for k, v in data.items() if k not in {"user_id", "permissions", "alias"}},
        )


@dataclass(slots=True)
class ChatList:
    """
    Paginated list of chats
    """

    chats: List[Chat]
    """Список запрашиваемых чатов"""
    marker: Optional[int] = None
    """Указатель на следующую страницу запрашиваемых чатов"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatList":
        """Create ChatList instance from API response dictionary."""
        chats_data = data.get("chats", [])
        chats = [Chat.from_dict(chat) for chat in chats_data]

        return cls(
            chats=chats,
            marker=data.get("marker"),
            api_kwargs={k: v for k, v in data.items() if k not in {"chats", "marker"}},
        )


@dataclass(slots=True)
class ChatPatch:
    """
    Chat patch model for updating chat information
    """

    icon: Optional[Dict[str, Any]] = None
    """Иконка чата"""
    title: Optional[str] = None
    """Название чата"""
    pin: Optional[str] = None
    """ID сообщения для закрепления в чате. Чтобы удалить закреплённое сообщение, используйте метод [unpin](/docs-api/methods/DELETE/chats/%7BchatId%7D/pin)"""  # noqa: E501
    notify: Optional[bool] = None
    """Если `true`, участники получат системное уведомление об изменении"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatPatch":
        """Create ChatPatch instance from API response dictionary."""
        return cls(
            icon=data.get("icon"),
            title=data.get("title"),
            pin=data.get("pin"),
            notify=data.get("notify"),
            api_kwargs={k: v for k, v in data.items() if k not in {"icon", "title", "pin", "notify"}},
        )


@dataclass(slots=True)
class ChatMembersList:
    """
    List of chat members
    """

    members: List[ChatMember]
    """Список участников чата с информацией о времени последней активности"""
    marker: Optional[int] = None
    """Указатель на следующую страницу данных"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMembersList":
        """Create ChatMembersList instance from API response dictionary."""
        members_data = data.get("members", [])
        members = [ChatMember.from_dict(member) for member in members_data]

        return cls(
            members=members,
            marker=data.get("marker"),
            api_kwargs={k: v for k, v in data.items() if k not in {"members", "marker"}},
        )


@dataclass(slots=True)
class ChatAdminsList:
    """
    List of chat admins
    """

    admins: List[ChatAdmin]
    """Массив администраторов чата"""
    marker: Optional[int] = None
    """Указатель на следующую страницу данных"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatAdminsList":
        """Create ChatAdminsList instance from API response dictionary."""
        admins_data = data.get("admins", [])
        admins = [ChatAdmin.from_dict(admin) for admin in admins_data]

        return cls(
            admins=admins,
            marker=data.get("marker"),
            api_kwargs={k: v for k, v in data.items() if k not in {"admins", "marker"}},
        )
