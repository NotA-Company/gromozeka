"""Enumeration classes for Max Bot library models.

This module defines string-based enumerations used throughout the Max Bot library
for representing various types, statuses, and permissions. All enums inherit from
StrEnum to ensure string representation and comparison capabilities.

Enums are organized by domain:
- Button types for interactive elements
- Message formatting and linking types
- Chat types, statuses, and permissions
- Sender actions for chat activity indicators
"""

from enum import StrEnum


# Button Enums
class ButtonType(StrEnum):
    """Button type enumeration for interactive elements.

    Defines the various types of buttons that can be used in Max Bot messages,
    including callback buttons, links, and action buttons.

    Attributes:
        UNSPECIFIED: Unspecified button type.
        CALLBACK: Button that triggers a callback query.
        LINK: Button that opens a URL.
        REQUEST_GEO_LOCATION: Button that requests user's geolocation.
        REQUEST_CONTACT: Button that requests user's contact information.
        OPEN_APP: Button that opens an application.
        MESSAGE: Button that sends a message.
        CHAT: Button that opens a chat.
        REPLY: Button that replies to a message.
    """

    UNSPECIFIED = "UNSPECIFIED"

    CALLBACK = "callback"
    LINK = "link"
    REQUEST_GEO_LOCATION = "request_geo_location"
    REQUEST_CONTACT = "request_contact"
    OPEN_APP = "open_app"
    MESSAGE = "message"
    CHAT = "chat"
    REPLY = "reply"


# Message Enums
class TextFormat(StrEnum):
    """Text format enumeration for message content.

    Defines the supported text formatting options for messages in Max Bot.

    Attributes:
        MARKDOWN: Markdown formatting.
        HTML: HTML formatting.
    """

    MARKDOWN = "markdown"
    HTML = "html"


class MessageLinkType(StrEnum):
    """Message link type enumeration for related messages.

    Defines the types of relationships between messages, such as forwards or replies.

    Attributes:
        UNSPECIFIED: Unspecified link type.
        FORWARD: Message is a forward of another message.
        REPLY: Message is a reply to another message.
    """

    UNSPECIFIED = "UNSPECIFIED"

    FORWARD = "forward"
    REPLY = "reply"


# Chat Enums
class ChatType(StrEnum):
    """Chat type enumeration for different chat categories.

    Defines the various types of chats in the Max Bot platform.

    Attributes:
        CHAT: Group chat.
        DIALOG: Private/direct message chat. Note: Not present in swagger but returned by Max API.
        CHANNEL: Channel chat.
    """

    CHAT = "chat"
    DIALOG = "dialog"  # NOTE: `dialog` isn't present in swagger, however returned by Max API
    CHANNEL = "channel"


class ChatStatus(StrEnum):
    """Chat status enumeration for bot participation.

    Defines the status of a bot's participation in a chat.

    Attributes:
        ACTIVE: Bot is an active participant in the chat.
        REMOVED: Bot was removed from the chat.
        LEFT: Bot left the chat.
        CLOSED: Chat was closed.
    """

    ACTIVE = "active"
    REMOVED = "removed"
    LEFT = "left"
    CLOSED = "closed"


class SenderAction(StrEnum):
    """Sender action enumeration for chat activity indicators.

    Defines the actions that can be sent to chat participants to indicate
    the bot's current activity or state.

    Attributes:
        TYPING: Bot is typing a message.
        UPLOAD_PHOTO: Bot is sending a photo.
        UPLOAD_VIDEO: Bot is sending a video.
        UPLOAD_AUDIO: Bot is sending an audio file.
        UPLOAD_FILE: Bot is sending a file.
        MARK_SEEN: Bot is marking messages as read.
    """

    TYPING = "typing_on"
    """Бот набирает сообщение."""
    UPLOAD_PHOTO = "sending_photo"
    """Бот отправляет фото."""
    UPLOAD_VIDEO = "sending_video"
    """Бот отправляет видео."""
    UPLOAD_AUDIO = "sending_audio"
    """Бот отправляет аудиофайл."""
    UPLOAD_FILE = "sending_file"
    """Бот отправляет файл."""
    MARK_SEEN = "mark_seen"
    """Бот помечает сообщения как прочитанные."""


class ChatAdminPermission(StrEnum):
    """Chat admin permission enumeration for administrative rights.

    Defines the various permissions that can be granted to chat administrators.

    Attributes:
        READ_ALL_MESSAGES: Permission to read all messages.
        ADD_REMOVE_MEMBERS: Permission to add/remove participants.
        ADD_ADMINS: Permission to add administrators.
        CHANGE_CHAT_INFO: Permission to change chat information.
        PIN_MESSAGE: Permission to pin messages.
        WRITE: Permission to write messages.
        EDIT_LINK: Permission to edit chat link.
        CAN_CALL: Permission for audio calls.
        EDIT: Permission to edit messages.
        VIEW_STATS: Permission to view message statistics.
        DELETE: Permission to delete messages.
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
    CAN_CALL = "can_call"
    """Audio Call?"""
    EDIT = "edit"
    """Edit messages?"""
    VIEW_STATS = "view_stats"
    """View message stats?"""
    DELETE = "delete"
    """Delete messages?"""
