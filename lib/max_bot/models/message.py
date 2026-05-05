"""
Message models for Max Messenger Bot API.

This module contains message-related dataclasses including Message, MessageBody,
Recipient, MessageStat, MessageList, NewMessageBody, NewMessageLink,
LinkedMessage, and SendMessageResult models.
"""

from typing import Any, Dict, List, Optional, Sequence

from .attachment import Attachment, attachmentFromDict
from .base import BaseMaxBotModel
from .enums import ChatType, MessageLinkType, TextFormat
from .markup import MarkupElement, markupListFromList
from .user import UserWithPhoto


class Recipient(BaseMaxBotModel):
    """Message recipient model for Max Messenger Bot API.

    Represents a message recipient which can be either a user or a chat.
    """

    __slots__ = ("chat_id", "chat_type", "user_id")

    def __init__(
        self,
        *,
        chat_id: Optional[int] = None,
        chat_type: ChatType,
        user_id: Optional[int] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize Recipient instance.

        Args:
            chat_id: Chat ID. Optional, defaults to None.
            chat_type: Type of chat (user, chat, channel, etc.).
            user_id: User ID if message was sent to a user. Optional, defaults to None.
            api_kwargs: Additional API keyword arguments. Optional, defaults to None.

        Attributes:
            chat_id: Chat ID.
            chat_type: Type of chat.
            user_id: User ID if message was sent to a user.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.chat_id: Optional[int] = chat_id
        """ID чата"""
        self.chat_type: ChatType = chat_type
        """Тип чата"""
        self.user_id: Optional[int] = user_id
        """ID пользователя, если сообщение было отправлено пользователю"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Recipient":
        """Create Recipient instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            Recipient: New Recipient instance
        """
        return cls(
            chat_id=data.get("chat_id"),
            chat_type=ChatType(data.get("chat_type", "chat")),
            user_id=data.get("user_id"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MessageStat(BaseMaxBotModel):
    """Message statistics model for Max Messenger Bot API.

    Contains view count statistics for a message.
    """

    __slots__ = ("views",)

    def __init__(self, *, views: int, api_kwargs: Dict[str, Any] | None = None):
        """Initialize MessageStat instance.

        Args:
            views: Number of views for the message.
            api_kwargs: Additional API keyword arguments. Optional, defaults to None.

        Attributes:
            views: Number of views for the message.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.views = views
        """Количество просмотров"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageStat":
        """Create MessageStat instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            MessageStat: New MessageStat instance
        """
        return cls(
            views=data.get("views", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MessageBody(BaseMaxBotModel):
    """Message body model for Max Messenger Bot API.

    Represents the content of a message including text, attachments, and markup.
    """

    __slots__ = ("mid", "seq", "text", "attachments", "markup")

    def __init__(
        self,
        *,
        mid: str,
        seq: int,
        text: Optional[str] = None,
        attachments: Optional[List[Attachment]] = None,
        markup: Optional[List[MarkupElement]] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize MessageBody instance.

        Args:
            mid: Unique message ID.
            seq: Message sequence ID in the chat.
            text: Message text. Optional, defaults to None.
            attachments: Message attachments. Can be any Attachment type. Optional, defaults to None.
            markup: Text markup elements. See formatting documentation for details. Optional, defaults to None.
            api_kwargs: Additional API keyword arguments. Optional, defaults to None.

        Attributes:
            mid: Unique message ID.
            seq: Message sequence ID in the chat.
            text: Message text.
            attachments: Message attachments. Can be any Attachment type.
            markup: Text markup elements.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.mid: str = mid
        """Уникальный ID сообщения"""
        self.seq: int = seq
        """ID последовательности сообщения в чате"""
        self.text: Optional[str] = text
        """Новый текст сообщения"""
        self.attachments: Optional[List[Attachment]] = attachments
        """
        Вложения сообщения. Могут быть одним из типов `Attachment`.
        Смотрите описание схемы
        """
        self.markup: Optional[List[MarkupElement]] = markup
        """
        Разметка текста сообщения. Для подробной информации загляните в раздел
        #[Форматирование](/docs-api#Форматирование%20текста)
        """

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageBody":
        """Create MessageBody instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            MessageBody: New MessageBody instance
        """
        attachments = None
        attachmentsData = data.get("attachments", None)
        if isinstance(attachmentsData, list):
            attachments = [attachmentFromDict(v) for v in attachmentsData]

        markup: Optional[List[MarkupElement]] = None
        markupData = data.get("markup", None)
        if isinstance(markupData, list):
            markup = markupListFromList(markupData)

        return cls(
            mid=data.get("mid", ""),
            seq=data.get("seq", 0),
            text=data.get("text", None),
            attachments=attachments,
            markup=markup,
            api_kwargs=cls._getExtraKwargs(data),
        )


class LinkedMessage(BaseMaxBotModel):
    """Linked message model for forwards and replies in Max Messenger Bot API.

    Represents a message that is linked to another message, such as a forward or reply.
    """

    __slots__ = ("type", "sender", "chat_id", "message")

    def __init__(
        self,
        *,
        type: MessageLinkType,
        sender: Optional[UserWithPhoto] = None,
        chat_id: Optional[int] = None,
        message: MessageBody,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize LinkedMessage instance.

        Args:
            type: Type of linked message (forward, reply, etc.).
            sender: User who sent the original message. Optional, defaults to None.
            chat_id: Chat where the message was originally published. Only for forwarded
                messages. Optional, defaults to None.
            message: The linked message content.
            api_kwargs: Additional API keyword arguments. Optional, defaults to None.

        Attributes:
            type: Type of linked message.
            sender: User who sent the original message.
            chat_id: Chat where the message was originally published. Only for forwarded messages.
            message: The linked message content.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.type: MessageLinkType = type
        """Тип связанного сообщения"""
        self.sender: Optional[UserWithPhoto] = sender
        """Пользователь, отправивший сообщение."""
        self.chat_id: Optional[int] = chat_id
        """
        Чат, в котором сообщение было изначально опубликовано.
        Только для пересланных сообщений
        """
        self.message: MessageBody = message
        """Сообщение"""

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
    """Message model for Max Messenger Bot API.

    Represents a complete message in a chat with sender, recipient, content, and metadata.
    """

    __slots__ = ("sender", "recipient", "timestamp", "link", "body", "stat", "url")

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
        """Initialize Message instance.

        Args:
            sender: User who sent the message.
            recipient: Message recipient (user or chat).
            timestamp: Message creation time in Unix timestamp format.
            link: Forwarded or replied message. Optional, defaults to None.
            body: Message content (text + attachments). Can be None if message only contains a linked message.
            stat: Message statistics. Optional, defaults to None.
            url: Public URL for the message. Can be None for private chats. Optional, defaults to None.
            api_kwargs: Additional API keyword arguments. Optional, defaults to None.

        Attributes:
            sender: User who sent the message.
            recipient: Message recipient (user or chat).
            timestamp: Message creation time in Unix timestamp format.
            link: Forwarded or replied message.
            body: Message content (text + attachments).
            stat: Message statistics.
            url: Public URL for the message.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.sender: UserWithPhoto = sender
        """Пользователь, отправивший сообщение"""
        self.recipient: Recipient = recipient
        """Получатель сообщения. Может быть пользователем или чатом"""
        self.timestamp: int = timestamp
        """Время создания сообщения в формате Unix-time"""
        self.link: Optional[LinkedMessage] = link
        """Пересланное или ответное сообщение"""
        self.body: MessageBody = body
        """
        Содержимое сообщения. Текст + вложения.
        Может быть `null`, если сообщение содержит только пересланное сообщение
        """
        self.stat: Optional[MessageStat] = stat
        """Статистика сообщения."""
        self.url: Optional[str] = url
        """
        Публичная ссылка на сообщение.
        Может быть null для диалогов или не публичных чатов
        """

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Create Message instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            Message: New Message instance
        """

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
    """Paginated message list model for Max Messenger Bot API.

    Represents a paginated list of messages returned from the API.
    """

    __slots__ = ("messages",)

    def __init__(self, *, messages: List[Message], api_kwargs: Dict[str, Any] | None = None):
        """Initialize MessageList instance.

        Args:
            messages: List of messages.
            api_kwargs: Additional API keyword arguments. Optional, defaults to None.

        Attributes:
            messages: List of messages.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.messages: List[Message] = messages
        """Массив сообщений"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageList":
        """Create MessageList instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            MessageList: New MessageList instance
        """

        return cls(
            messages=[Message.from_dict(msg) for msg in data.get("messages", [])],
            api_kwargs=cls._getExtraKwargs(data),
        )


class NewMessageLink(BaseMaxBotModel):
    """Link model for new messages in Max Messenger Bot API.

    Used to create forward or reply links when sending new messages.
    """

    __slots__ = ("type", "mid")

    def __init__(
        self,
        *,
        type: MessageLinkType,
        mid: str,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize NewMessageLink instance.

        Args:
            type: Type of message link (forward, reply, etc.).
            mid: ID of the source message to link to.
            api_kwargs: Additional API keyword arguments. Optional, defaults to None.

        Attributes:
            type: Type of message link.
            mid: ID of the source message to link to.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.type: MessageLinkType = type
        """Тип ссылки сообщения"""
        self.mid: str = mid
        """ID сообщения исходного сообщения"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NewMessageLink":
        """Create NewMessageLink instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            NewMessageLink: New NewMessageLink instance
        """
        return cls(
            type=MessageLinkType(data.get("type", MessageLinkType.UNSPECIFIED)),
            mid=data.get("mid", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class NewMessageBody(BaseMaxBotModel):
    """New message body model for sending messages in Max Messenger Bot API.

    Used to construct the content of a new message to be sent.
    """

    __slots__ = ("text", "attachments", "link", "notify", "format")

    def __init__(
        self,
        *,
        text: Optional[str] = None,
        attachments: Optional[Sequence[Attachment]] = None,
        link: Optional[NewMessageLink] = None,
        notify: Optional[bool] = None,
        format: Optional[TextFormat] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize NewMessageBody instance.

        Args:
            text: Message text. Optional, defaults to None.
            attachments: Message attachments. If empty, all attachments will be removed. Optional, defaults to None.
            link: Link to another message (forward/reply). Optional, defaults to None.
            notify: If False, chat participants will not be notified. Defaults to True. Optional, defaults to None.
            format: Text format to use. See formatting documentation for details. Optional, defaults to None.
            api_kwargs: Additional API keyword arguments. Optional, defaults to None.

        Attributes:
            text: Message text.
            attachments: Message attachments. If empty, all attachments will be removed.
            link: Link to another message (forward/reply).
            notify: If False, chat participants will not be notified. Defaults to True.
            format: Text format to use.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.text: Optional[str] = text
        """Новый текст сообщения"""
        self.attachments: Optional[List[Attachment]] = None
        """
        Вложения сообщения.
        Если пусто, все вложения будут удалены
        """
        if attachments:
            self.attachments = list(attachments)
        self.link: Optional[NewMessageLink] = link
        """Ссылка на сообщение"""
        self.notify: Optional[bool] = notify
        """Если false, участники чата не будут уведомлены (по умолчанию `true`)"""
        self.format: Optional[TextFormat] = format
        """
        Если установлен, текст сообщения будет форматирован данным способом.
        Для подробной информации загляните в раздел
        [Форматирование](/docs-api#Форматирование%20текста)
        """

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NewMessageBody":
        """Create NewMessageBody instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            NewMessageBody: New NewMessageBody instance
        """
        link_data = data.get("link", None)
        link = None
        if link_data:
            link = NewMessageLink.from_dict(link_data)

        format_data = data.get("format", None)
        format_enum = None
        if format_data:
            format_enum = TextFormat(format_data)

        attachments = None
        attachmentsData = data.get("attachments", None)
        if isinstance(attachmentsData, list):
            attachments = [attachmentFromDict(v) for v in attachmentsData]

        return cls(
            text=data.get("text", None),
            attachments=attachments,
            link=link,
            notify=data.get("notify"),
            format=format_enum,
            api_kwargs=cls._getExtraKwargs(data),
        )


class SendMessageResult(BaseMaxBotModel):
    """Send message result model for Max Messenger Bot API.

    Represents the result of sending a message operation.
    """

    __slots__ = ("message",)

    def __init__(self, *, message: Message, api_kwargs: Dict[str, Any] | None = None):
        """Initialize SendMessageResult instance.

        Args:
            message: The sent message.
            api_kwargs: Additional API keyword arguments. Optional, defaults to None.

        Attributes:
            message: The sent message.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.message: Message = message
        """Sent message"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SendMessageResult":
        """Create SendMessageResult instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            SendMessageResult: New SendMessageResult instance
        """

        return cls(
            message=Message.from_dict(data.get("message", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )
