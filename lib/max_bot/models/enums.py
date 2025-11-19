from enum import StrEnum

# Message Enums


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


# Chat Enums
class ChatType(StrEnum):
    """
    Тип чата: диалог, чат
    """

    CHAT = "chat"
    DIALOG = "dialog"  # NOTE: `dialog` isn't present in swagger, however returned by Max API
    CHANNEL = "channel"


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


class SenderAction(StrEnum):
    """
    Действие, отправляемое участникам чата.
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
    CAN_CALL = "can_call"
    """Audio Call?"""
    EDIT = "edit"
    """Edit messages?"""
    VIEW_STATS = "view_stats"
    """View message stats?"""
    DELETE = "delete"
    """Delete messages?"""
