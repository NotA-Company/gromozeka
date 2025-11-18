"""
Message models for Max Messenger Bot API.

This module contains message-related dataclasses including Message, MessageBody,
Recipient, MessageStat, MessageList, NewMessageBody, NewMessageLink,
LinkedMessage, and SendMessageResult models.
"""

from enum import StrEnum
from typing import Any, Dict, List, Optional

from .base import BaseMaxBotModel
from .chat import ChatType
from .user import UserWithPhoto


class TextFormat(StrEnum):
    """
    Формат текста сообщения
    """

    MARKDOWN = "markdown"
    HTML = "html"


class MessageLinkType(StrEnum):
    """
    Тип связанного сообщения
    """

    UNSPECIFIED = "UNSPECIFIED"

    FORWARD = "forward"
    REPLY = "reply"


class Recipient(BaseMaxBotModel):
    """
    Новый получатель сообщения. Может быть пользователем или чатом
    """

    __slots__ = ("chat_id", "chat_type", "user_id")
    # chat_id: Optional[int] = None
    # """ID чата"""
    # chat_type: ChatType = ChatType.CHAT
    # """Тип чата"""
    # user_id: Optional[int] = None
    # """ID пользователя, если сообщение было отправлено пользователю"""

    def __init__(
        self,
        *,
        chat_id: Optional[int] = None,
        chat_type: ChatType,
        user_id: Optional[int] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.chat_id: Optional[int] = chat_id
        self.chat_type: ChatType = chat_type
        self.user_id: Optional[int] = user_id

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Recipient":
        """Create Recipient instance from API response dictionary."""
        return cls(
            chat_id=data.get("chat_id"),
            chat_type=ChatType(data.get("chat_type", "chat")),
            user_id=data.get("user_id"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MessageStat(BaseMaxBotModel):
    """
    Статистика сообщения
    """

    __slots__ = ("views",)
    # views: int
    # """Количество просмотров"""

    def __init__(self, *, views: int, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.views = views

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageStat":
        """Create MessageStat instance from API response dictionary."""
        return cls(
            views=data.get("views", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MessageBody(BaseMaxBotModel):
    """
    Схема, представляющая тело сообщения
    """

    __slots__ = ("mid", "seq", "text", "attachments", "markup")

    # mid: str
    # """Уникальный ID сообщения"""
    # seq: int = 0
    # """ID последовательности сообщения в чате"""
    # text: Optional[str] = None
    # """Новый текст сообщения"""
    # attachments: Optional[List[Dict[str, Any]]] = None
    # """Вложения сообщения. Могут быть одним из типов `Attachment`. Смотрите описание схемы"""
    # markup: Optional[List[Dict[str, Any]]] = None
    # """
    # Разметка текста сообщения. Для подробной информации загляните в раздел
    # [Форматирование](/docs-api#Форматирование%20текста)
    # """

    def __init__(
        self,
        *,
        mid: str,
        seq: int,
        text: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        markup: Optional[List[Dict[str, Any]]] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.mid: str = mid
        self.seq: int = seq
        self.text: Optional[str] = text
        self.attachments: Optional[List[Dict[str, Any]]] = attachments
        self.markup: Optional[List[Dict[str, Any]]] = markup

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageBody":
        """Create MessageBody instance from API response dictionary."""
        return cls(
            mid=data.get("mid", ""),
            seq=data.get("seq", 0),
            text=data.get("text", None),
            attachments=data.get("attachments", None),
            markup=data.get("markup", None),
            api_kwargs=cls._getExtraKwargs(data),
        )


class LinkedMessage(BaseMaxBotModel):
    """
    Linked message model for forwards and replies
    """

    __slots__ = ("type", "sender", "chat_id", "message")

    # type: MessageLinkType
    # """Тип связанного сообщения"""
    # sender: Optional[UserWithPhoto] = None
    # """Пользователь, отправивший сообщение."""
    # chat_id: Optional[int] = None
    # """Чат, в котором сообщение было изначально опубликовано. Только для пересланных сообщений"""
    # message: MessageBody
    # """Сообщение"""

    def __init__(
        self,
        *,
        type: MessageLinkType,
        sender: Optional[UserWithPhoto] = None,
        chat_id: Optional[int] = None,
        message: MessageBody,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.type: MessageLinkType = type
        self.sender: Optional[UserWithPhoto] = sender
        self.chat_id: Optional[int] = chat_id
        self.message: MessageBody = message

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LinkedMessage":
        """Create LinkedMessage instance from API response dictionary."""
        sender_data = data.get("sender", None)
        sender = None
        if sender_data is not None:
            sender = UserWithPhoto.from_dict(sender_data)

        return cls(
            type=MessageLinkType(data.get("type", MessageLinkType.UNSPECIFIED)),
            sender=sender,
            chat_id=data.get("chat_id"),
            message=MessageBody.from_dict(data.get("message", {})),
            api_kwargs={k: v for k, v in data.items() if k not in {"type", "sender", "chat_id", "message"}},
        )


class Message(BaseMaxBotModel):
    """
    Сообщение в чате
    """

    __slots__ = ("sender", "recipient", "timestamp", "link", "body", "stat", "url")

    # sender: UserWithPhoto
    # """Пользователь, отправивший сообщение"""
    # recipient: Recipient
    # """Получатель сообщения. Может быть пользователем или чатом"""
    # timestamp: int
    # """Время создания сообщения в формате Unix-time"""
    # link: Optional[LinkedMessage] = None
    # """Пересланное или ответное сообщение"""
    # message: MessageBody
    # """
    # Содержимое сообщения. Текст + вложения.
    # Может быть `null`, если сообщение содержит только пересланное сообщение
    # """
    # stat: Optional[MessageStat] = None
    # """Статистика сообщения."""
    # url: Optional[str] = None
    # """Публичная ссылка на сообщение. Может быть null для диалогов или не публичных чатов"""

    def __init__(
        self,
        *,
        sender: UserWithPhoto,
        recipient: Recipient,
        timestamp: int,
        link: Optional[LinkedMessage] = None,
        body: MessageBody,
        stat: Optional[MessageStat] = None,
        url: Optional[str] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.sender: UserWithPhoto = sender
        self.recipient: Recipient = recipient
        self.timestamp: int = timestamp
        self.link: Optional[LinkedMessage] = link
        self.body: MessageBody = body
        self.stat: Optional[MessageStat] = stat
        self.url: Optional[str] = url

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Create Message instance from API response dictionary."""

        link_data = data.get("link", None)
        link = None
        if link_data:
            link = LinkedMessage.from_dict(link_data)

        stat_data = data.get("stat", None)
        stat = None
        if stat_data:
            stat = MessageStat.from_dict(stat_data)

        return cls(
            sender=UserWithPhoto.from_dict(data.get("sender", {})),
            recipient=Recipient.from_dict(data.get("recipient", {})),
            timestamp=data.get("timestamp", 0),
            link=link,
            body=MessageBody.from_dict(data.get("body", {})),
            stat=stat,
            url=data.get("url"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MessageList(BaseMaxBotModel):
    """
    Пагинированный список сообщений
    """

    __slots__ = ("messages",)

    # messages: List[Message]
    # """Массив сообщений"""

    def __init__(self, *, messages: List[Message], api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.messages: List[Message] = messages

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageList":
        """Create MessageList instance from API response dictionary."""

        return cls(
            messages=[Message.from_dict(msg) for msg in data.get("messages", [])],
            api_kwargs=cls._getExtraKwargs(data),
        )


class NewMessageLink(BaseMaxBotModel):
    """
    Link model for new messages (forward/reply)
    """

    __slots__ = ("type", "mid")

    # type: MessageLinkType
    # """Тип ссылки сообщения"""
    # mid: str
    # """ID сообщения исходного сообщения"""

    def __init__(
        self,
        *,
        type: MessageLinkType,
        mid: str,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.type: MessageLinkType = type
        self.mid: str = mid

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NewMessageLink":
        """Create NewMessageLink instance from API response dictionary."""
        return cls(
            type=MessageLinkType(data.get("type", MessageLinkType.UNSPECIFIED)),
            mid=data.get("mid", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class NewMessageBody(BaseMaxBotModel):
    """
    New message body for sending messages
    """

    __slots__ = ("text", "attachments", "link", "notify", "format")

    # text: Optional[str] = None
    # """Новый текст сообщения"""
    # attachments: Optional[List[Dict[str, Any]]] = None
    # """Вложения сообщения. Если пусто, все вложения будут удалены"""
    # link: Optional[NewMessageLink] = None
    # """Ссылка на сообщение"""
    # notify: bool = True
    # """Если false, участники чата не будут уведомлены (по умолчанию `true`)"""
    # format: Optional[TextFormat] = None
    # """
    # Если установлен, текст сообщения будет форматирован данным способом.
    # Для подробной информации загляните в раздел
    # [Форматирование](/docs-api#Форматирование%20текста)
    # """

    def __init__(
        self,
        *,
        text: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        link: Optional[NewMessageLink] = None,
        notify: bool = True,
        format: Optional[TextFormat] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.text: Optional[str] = text
        self.attachments: Optional[List[Dict[str, Any]]] = attachments
        self.link: Optional[NewMessageLink] = link
        self.notify: bool = notify
        self.format: Optional[TextFormat] = format

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NewMessageBody":
        """Create NewMessageBody instance from API response dictionary."""
        link_data = data.get("link", None)
        link = None
        if link_data:
            link = NewMessageLink.from_dict(link_data)

        format_data = data.get("format", None)
        format_enum = None
        if format_data:
            format_enum = TextFormat(format_data)

        return cls(
            text=data.get("text", None),
            attachments=data.get("attachments", None),
            link=link,
            notify=data.get("notify", True),
            format=format_enum,
            api_kwargs=cls._getExtraKwargs(data),
        )


class SendMessageResult(BaseMaxBotModel):
    """
    Result of sending a message
    """

    __slots__ = ("message",)

    # message: Message
    # """Sent message"""

    def __init__(self, *, message: Message, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.message: Message = message

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SendMessageResult":
        """Create SendMessageResult instance from API response dictionary."""

        return cls(
            message=Message.from_dict(data.get("message", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )
