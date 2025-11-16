"""
Message models for Max Messenger Bot API.

This module contains message-related dataclasses including Message, MessageBody,
Recipient, MessageStat, MessageList, NewMessageBody, NewMessageLink,
LinkedMessage, and SendMessageResult models.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .chat import ChatType
from .user import User


class TextFormat(str, Enum):
    """
    Формат текста сообщения
    """

    MARKDOWN = "markdown"
    HTML = "html"


class MessageLinkType(str, Enum):
    """
    Тип связанного сообщения
    """

    FORWARD = "forward"
    REPLY = "reply"


@dataclass(slots=True)
class Recipient:
    """
    Новый получатель сообщения. Может быть пользователем или чатом
    """

    chat_id: Optional[int] = None
    """ID чата"""
    chat_type: ChatType = ChatType.CHAT
    """Тип чата"""
    user_id: Optional[int] = None
    """ID пользователя, если сообщение было отправлено пользователю"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Recipient":
        """Create Recipient instance from API response dictionary."""
        return cls(
            chat_id=data.get("chat_id"),
            chat_type=ChatType(data.get("chat_type", "chat")),
            user_id=data.get("user_id"),
            api_kwargs={k: v for k, v in data.items() if k not in {"chat_id", "chat_type", "user_id"}},
        )


@dataclass(slots=True)
class MessageStat:
    """
    Статистика сообщения
    """

    views: int = 0
    """Количество просмотров"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageStat":
        """Create MessageStat instance from API response dictionary."""
        return cls(views=data.get("views", 0), api_kwargs={k: v for k, v in data.items() if k not in {"views"}})


@dataclass(slots=True)
class MessageBody:
    """
    Схема, представляющая тело сообщения
    """

    mid: str
    """Уникальный ID сообщения"""
    seq: int = 0
    """ID последовательности сообщения в чате"""
    text: Optional[str] = None
    """Новый текст сообщения"""
    attachments: Optional[List[Dict[str, Any]]] = None
    """Вложения сообщения. Могут быть одним из типов `Attachment`. Смотрите описание схемы"""
    markup: Optional[List[Dict[str, Any]]] = None
    """Разметка текста сообщения. Для подробной информации загляните в раздел [Форматирование](/docs-api#Форматирование%20текста)"""  # noqa: E501
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageBody":
        """Create MessageBody instance from API response dictionary."""
        return cls(
            mid=data.get("mid", ""),
            seq=data.get("seq", 0),
            text=data.get("text"),
            attachments=data.get("attachments"),
            markup=data.get("markup"),
            api_kwargs={k: v for k, v in data.items() if k not in {"mid", "seq", "text", "attachments", "markup"}},
        )


@dataclass(slots=True)
class LinkedMessage:
    """
    Linked message model for forwards and replies
    """

    type: MessageLinkType
    """Тип связанного сообщения"""
    sender: Optional[User] = None
    """Пользователь, отправивший сообщение."""
    chat_id: Optional[int] = None
    """Чат, в котором сообщение было изначально опубликовано. Только для пересланных сообщений"""
    message: Optional[MessageBody] = None
    """Сообщение"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LinkedMessage":
        """Create LinkedMessage instance from API response dictionary."""
        sender_data = data.get("sender")
        sender = None
        if sender_data:
            sender = User.from_dict(sender_data)

        message_data = data.get("message")
        message = None
        if message_data:
            message = MessageBody.from_dict(message_data)

        return cls(
            type=MessageLinkType(data.get("type", "reply")),
            sender=sender,
            chat_id=data.get("chat_id"),
            message=message,
            api_kwargs={k: v for k, v in data.items() if k not in {"type", "sender", "chat_id", "message"}},
        )


@dataclass(slots=True)
class Message:
    """
    Сообщение в чате
    """

    recipient: Recipient
    """Получатель сообщения. Может быть пользователем или чатом"""
    body: MessageBody
    """Содержимое сообщения. Текст + вложения. Может быть `null`, если сообщение содержит только пересланное сообщение"""  # noqa: E501
    timestamp: int = 0
    """Время создания сообщения в формате Unix-time"""
    sender: Optional[User] = None
    """Пользователь, отправивший сообщение"""
    link: Optional[LinkedMessage] = None
    """Пересланное или ответное сообщение"""
    stat: Optional[MessageStat] = None
    """Статистика сообщения."""
    url: Optional[str] = None
    """Публичная ссылка на сообщение. Может быть null для диалогов или не публичных чатов"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Create Message instance from API response dictionary."""
        recipient_data = data.get("recipient", {})
        recipient = Recipient.from_dict(recipient_data)

        body_data = data.get("body", {})
        body = MessageBody.from_dict(body_data)

        sender_data = data.get("sender")
        sender = None
        if sender_data:
            sender = User.from_dict(sender_data)

        link_data = data.get("link")
        link = None
        if link_data:
            link = LinkedMessage.from_dict(link_data)

        stat_data = data.get("stat")
        stat = None
        if stat_data:
            stat = MessageStat.from_dict(stat_data)

        return cls(
            recipient=recipient,
            body=body,
            timestamp=data.get("timestamp", 0),
            sender=sender,
            link=link,
            stat=stat,
            url=data.get("url"),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k not in {"recipient", "body", "timestamp", "sender", "link", "stat", "url"}
            },
        )


@dataclass(slots=True)
class MessageList:
    """
    Пагинированный список сообщений
    """

    messages: List[Message]
    """Массив сообщений"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageList":
        """Create MessageList instance from API response dictionary."""
        messages_data = data.get("messages", [])
        messages = [Message.from_dict(msg) for msg in messages_data]

        return cls(messages=messages, api_kwargs={k: v for k, v in data.items() if k not in {"messages"}})


@dataclass(slots=True)
class NewMessageLink:
    """
    Link model for new messages (forward/reply)
    """

    type: MessageLinkType
    """Тип ссылки сообщения"""
    mid: str
    """ID сообщения исходного сообщения"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NewMessageLink":
        """Create NewMessageLink instance from API response dictionary."""
        return cls(
            type=MessageLinkType(data.get("type", "reply")),
            mid=data.get("mid", ""),
            api_kwargs={k: v for k, v in data.items() if k not in {"type", "mid"}},
        )


@dataclass(slots=True)
class NewMessageBody:
    """
    New message body for sending messages
    """

    text: Optional[str] = None
    """Новый текст сообщения"""
    attachments: Optional[List[Dict[str, Any]]] = None
    """Вложения сообщения. Если пусто, все вложения будут удалены"""
    link: Optional[NewMessageLink] = None
    """Ссылка на сообщение"""
    notify: bool = True
    """Если false, участники чата не будут уведомлены (по умолчанию `true`)"""
    format: Optional[TextFormat] = None
    """Если установлен, текст сообщения будет форматирован данным способом. Для подробной информации загляните в раздел [Форматирование](/docs-api#Форматирование%20текста)"""  # noqa: E501
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NewMessageBody":
        """Create NewMessageBody instance from API response dictionary."""
        link_data = data.get("link")
        link = None
        if link_data:
            link = NewMessageLink.from_dict(link_data)

        format_data = data.get("format")
        format_enum = None
        if format_data:
            format_enum = TextFormat(format_data)

        return cls(
            text=data.get("text"),
            attachments=data.get("attachments"),
            link=link,
            notify=data.get("notify", True),
            format=format_enum,
            api_kwargs={k: v for k, v in data.items() if k not in {"text", "attachments", "link", "notify", "format"}},
        )


@dataclass(slots=True)
class SendMessageResult:
    """
    Result of sending a message
    """

    message: Message
    """Sent message"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SendMessageResult":
        """Create SendMessageResult instance from API response dictionary."""
        message_data = data.get("message", {})
        message = Message.from_dict(message_data)

        return cls(message=message, api_kwargs={k: v for k, v in data.items() if k not in {"message"}})
