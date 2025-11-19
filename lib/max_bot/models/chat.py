"""
Chat models for Max Messenger Bot API.

This module contains chat-related dataclasses including Chat, ChatMember,
ChatAdmin, ChatAdminPermission, ChatList, and ChatPatch models.
"""

from typing import Any, Dict, List, Optional

from .base import BaseMaxBotModel
from .enums import ChatAdminPermission, ChatStatus, ChatType
from .message import Message
from .user import UserWithPhoto


class Chat(BaseMaxBotModel):
    """
    Chat model representing a Max Messenger chat
    """

    __slots__ = (
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
    )

    def __init__(
        self,
        *,
        chat_id: int,
        type: ChatType,
        status: ChatStatus,
        title: Optional[str] = None,
        icon: Optional[Dict[str, Any]] = None,
        last_event_time: int = 0,
        participants_count: int = 0,
        owner_id: Optional[int] = None,
        participants: Optional[Dict[str, int]] = None,
        is_public: bool = False,
        link: Optional[str] = None,
        description: Optional[str] = None,
        dialog_with_user: Optional[UserWithPhoto] = None,
        chat_message_id: Optional[str] = None,
        pinned_message: Optional[Message] = None,
        api_kwargs: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        """ID чата"""
        self.type: ChatType = type
        """Тип чата"""
        self.status: ChatStatus = status
        """Статус чата"""
        self.title: Optional[str] = title
        """Отображаемое название чата. Может быть `null` для диалогов"""
        self.icon: Optional[Dict[str, Any]] = icon
        """Иконка чата {url: ...}"""
        self.last_event_time: int = last_event_time
        """Время последнего события в чате"""
        self.participants_count: int = participants_count
        """Количество участников чата. Для диалогов всегда `2`"""
        self.owner_id: Optional[int] = owner_id
        """ID владельца чата"""
        self.participants: Optional[Dict[str, int]] = participants
        """
        Участники чата с временем последней активности. Может быть `null`, если запрашивается список чатов

        userId -> lastActive
        """
        self.is_public: bool = is_public
        """Доступен ли чат публично (для диалогов всегда `false`)"""
        self.link: Optional[str] = link
        """Ссылка на чат"""
        self.description: Optional[str] = description
        """Описание чата"""
        self.dialog_with_user: Optional[UserWithPhoto] = dialog_with_user
        """Данные о пользователе в диалоге (только для чатов типа `"dialog"`)"""
        self.chat_message_id: Optional[str] = chat_message_id
        """ID сообщения, содержащего кнопку, через которую был инициирован чат"""
        self.pinned_message: Optional[Message] = pinned_message
        """Закреплённое сообщение в чате (возвращается только при запросе конкретного чата)"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Chat":
        """Create Chat instance from API response dictionary."""
        dialog_with_user_data = data.get("dialog_with_user", None)
        dialog_with_user = None
        if dialog_with_user_data:
            dialog_with_user = UserWithPhoto.from_dict(dialog_with_user_data)

        message_data = data.get("pinned_message", None)
        pinned_message = None
        if message_data:
            pinned_message = Message.from_dict(message_data)

        return cls(
            chat_id=data.get("chat_id", 0),
            type=ChatType(data.get("type", ChatType.CHAT)),
            status=ChatStatus(data.get("status", ChatStatus.ACTIVE)),
            title=data.get("title", None),
            icon=data.get("icon", None),
            last_event_time=data.get("last_event_time", 0),
            participants_count=data.get("participants_count", 0),
            owner_id=data.get("owner_id", None),
            participants=data.get("participants", None),
            is_public=data.get("is_public", False),
            link=data.get("link", None),
            description=data.get("description", None),
            dialog_with_user=dialog_with_user,
            chat_message_id=data.get("chat_message_id", None),
            pinned_message=pinned_message,
            api_kwargs=cls._getExtraKwargs(data),
        )


class ChatMember(UserWithPhoto):
    """
    Объект, описывающий участника чата
    """

    __slots__ = ("last_access_time", "is_owner", "is_admin", "join_time", "permissions", "alias")

    def __init__(
        self,
        *,
        last_access_time: int,
        is_owner: bool,
        is_admin: bool,
        join_time: int,
        permissions: Optional[List[ChatAdminPermission]] = None,
        alias: Optional[str] = None,
        description: str | None = None,
        avatar_url: str | None = None,
        full_avatar_url: str | None = None,
        user_id: int,
        first_name: str,
        last_name: str | None = None,
        username: str | None = None,
        is_bot: bool = False,
        last_activity_time: int = 0,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(
            description=description,
            avatar_url=avatar_url,
            full_avatar_url=full_avatar_url,
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            is_bot=is_bot,
            last_activity_time=last_activity_time,
            api_kwargs=api_kwargs,
        )
        self.last_access_time: int = last_access_time
        """
        Время последней активности пользователя в чате.
        Может быть устаревшим для суперчатов (равно времени вступления)
        """
        self.is_owner: bool = is_owner
        """Является ли пользователь владельцем чата"""
        self.is_admin: bool = is_admin
        """Является ли пользователь администратором чата"""
        self.join_time: int = join_time
        """Дата присоединения к чату в формате Unix time"""
        self.permissions: Optional[List[ChatAdminPermission]] = permissions
        """Перечень прав пользователя."""
        self.alias: Optional[str] = alias
        """
        Заголовок, который будет показан на клиенте
        Если пользователь администратор или владелец и ему не установлено это название,
        то поле не передается, клиенты на своей стороне подменят на "владелец" или "админ".
        """

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMember":
        """Create ChatMember instance from API response dictionary."""
        permissions_data = data.get("permissions")
        permissions = None
        if permissions_data is not None:
            permissions = [ChatAdminPermission(perm) for perm in permissions_data]

        return cls(
            last_access_time=data.get("last_access_time", 0),
            is_owner=data.get("is_owner", False),
            is_admin=data.get("is_admin", False),
            join_time=data.get("join_time", 0),
            permissions=permissions,
            alias=data.get("alias"),
            description=data.get("description"),
            avatar_url=data.get("avatar_url"),
            full_avatar_url=data.get("full_avatar_url"),
            user_id=data.get("user_id", 0),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name"),
            username=data.get("username"),
            is_bot=data.get("is_bot", False),
            last_activity_time=data.get("last_activity_time", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ChatAdmin(BaseMaxBotModel):
    """
    Chat admin model with permissions
    """

    __slots__ = ("user_id", "permissions", "alias")

    def __init__(
        self,
        *,
        user_id: int,
        permissions: List[ChatAdminPermission],
        alias: Optional[str] = None,
        api_kwargs: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.user_id: int = user_id
        """Идентификатор администратора с правами доступа"""
        self.permissions: List[ChatAdminPermission] = permissions
        """Перечень прав пользователя. Возможные значения:
        - `"read_all_messages"` — Читать все сообщения.
        - `"add_remove_members"` — Добавлять/удалять участников.
        - `"add_admins"` — Добавлять администраторов.
        - `"change_chat_info"` — Изменять информацию о чате.
        - `"pin_message"` — Закреплять сообщения.
        - `"write"` — Писать сообщения.
        """
        self.alias: Optional[str] = alias
        """Заголовок, который будет показан на клиенте

        Если пользователь администратор или владелец и ему не установлено это название, то поле не передается, клиенты на своей стороне подменят на "владелец" или "админ"."""  # noqa: E501

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatAdmin":
        """Create ChatAdmin instance from API response dictionary."""
        permissions_data = data.get("permissions", [])
        permissions = [ChatAdminPermission(perm) for perm in permissions_data]

        return cls(
            user_id=data.get("user_id", 0),
            permissions=permissions,
            alias=data.get("alias"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ChatList(BaseMaxBotModel):
    """
    Paginated list of chats
    """

    __slots__ = ("chats", "marker")

    def __init__(
        self,
        *,
        chats: List[Chat],
        marker: Optional[int] = None,
        api_kwargs: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.chats: List[Chat] = chats
        """Список запрашиваемых чатов"""
        self.marker: Optional[int] = marker
        """Указатель на следующую страницу запрашиваемых чатов"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatList":
        """Create ChatList instance from API response dictionary."""
        chats_data = data.get("chats", [])
        chats = [Chat.from_dict(chat) for chat in chats_data]

        return cls(
            chats=chats,
            marker=data.get("marker"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ChatPatch(BaseMaxBotModel):
    """
    Chat patch model for updating chat information
    """

    __slots__ = ("icon", "title", "pin", "notify")

    def __init__(
        self,
        *,
        icon: Optional[Dict[str, Any]] = None,
        title: Optional[str] = None,
        pin: Optional[str] = None,
        notify: Optional[bool] = None,
        api_kwargs: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.icon: Optional[Dict[str, Any]] = icon
        """Иконка чата"""
        self.title: Optional[str] = title
        """Название чата"""
        self.pin: Optional[str] = pin
        """ID сообщения для закрепления в чате. Чтобы удалить закреплённое сообщение, используйте метод [unpin](/docs-api/methods/DELETE/chats/%7BchatId%7D/pin)"""  # noqa: E501
        self.notify: Optional[bool] = notify
        """Если `true`, участники получат системное уведомление об изменении"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatPatch":
        """Create ChatPatch instance from API response dictionary."""
        return cls(
            icon=data.get("icon"),
            title=data.get("title"),
            pin=data.get("pin"),
            notify=data.get("notify"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ChatMembersList(BaseMaxBotModel):
    """
    List of chat members
    """

    __slots__ = ("members", "marker")

    def __init__(
        self, *, members: List[ChatMember], marker: Optional[int] = None, api_kwargs: Dict[str, Any] | None = None
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.members: List[ChatMember] = members
        """Список участников чата с информацией о времени последней активности"""
        self.marker: Optional[int] = marker
        """Указатель на следующую страницу данных"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMembersList":
        """Create ChatMembersList instance from API response dictionary."""

        return cls(
            members=[ChatMember.from_dict(member) for member in data.get("members", [])],
            marker=data.get("marker", None),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ChatAdminsList(BaseMaxBotModel):
    """
    List of chat admins
    """

    __slots__ = ("admins", "marker")

    def __init__(
        self, *, admins: List[ChatAdmin], marker: Optional[int] = None, api_kwargs: Dict[str, Any] | None = None
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.admins: List[ChatAdmin] = admins
        """Массив администраторов чата"""
        self.marker: Optional[int] = marker
        """Указатель на следующую страницу данных"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatAdminsList":
        """Create ChatAdminsList instance from API response dictionary."""
        admins_data = data.get("admins", [])
        admins = [ChatAdmin.from_dict(admin) for admin in admins_data]

        return cls(
            admins=admins,
            marker=data.get("marker", None),
            api_kwargs=cls._getExtraKwargs(data),
        )
