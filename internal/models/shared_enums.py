"""Shared Enums module.

This module provides enumeration types that are shared across multiple modules
to avoid circular dependencies. These enums define common types and categories
used throughout the Gromozeka application, particularly for message handling
and database operations.

The module currently contains:
    - MessageType: Enum defining various types of messages that can be processed

Example:
    >>> from internal.models.shared_enums import MessageType
    >>> msg_type = MessageType.IMAGE
    >>> upload_type = msg_type.toMaxUploadType()
"""

import logging
from enum import StrEnum

import lib.max_bot.models as maxModels

logger = logging.getLogger(__name__)


class MessageType(StrEnum):
    """Enumeration of message types supported by the application.

    This enum defines the various types of messages that can be processed,
    stored, and transmitted through the system. It serves as a shared type
    definition between the database and bot modules to avoid circular
    dependencies.

    The message types correspond to Telegram's message types and include
    text, images, stickers, animations, videos, audio, voice messages,
    and documents.

    Attributes:
        TEXT: Plain text message.
        IMAGE: Photo or image message (corresponds to Telegram PhotoSize).
        STICKER: Sticker message (corresponds to Telegram Sticker).
        ANIMATION: Animated GIF or animation (corresponds to Telegram Animation).
        VIDEO: Video message (corresponds to Telegram Video).
        VIDEO_NOTE: Circular video message (corresponds to Telegram VideoNote).
        AUDIO: Audio file message (corresponds to Telegram Audio).
        VOICE: Voice message (corresponds to Telegram Voice).
        DOCUMENT: Generic document file (corresponds to Telegram Document).
        UNKNOWN: Unknown or unsupported message type.

    Example:
        >>> msg_type = MessageType.IMAGE
        >>> print(msg_type.value)
        'image'
        >>> upload_type = msg_type.toMaxUploadType()
    """

    TEXT = "text"
    """Plain text message type."""

    IMAGE = "image"
    """Photo or image message type (corresponds to Telegram PhotoSize)."""

    STICKER = "sticker"
    """Sticker message type (corresponds to Telegram Sticker)."""

    ANIMATION = "animation"
    """Animated GIF or animation type (corresponds to Telegram Animation)."""

    VIDEO = "video"
    """Video message type (corresponds to Telegram Video)."""

    VIDEO_NOTE = "video-note"
    """Circular video message type (corresponds to Telegram VideoNote)."""

    AUDIO = "audio"
    """Audio file message type (corresponds to Telegram Audio)."""

    VOICE = "voice"
    """Voice message type (corresponds to Telegram Voice)."""

    DOCUMENT = "document"
    """Generic document file type (corresponds to Telegram Document)."""

    UNKNOWN = "unknown"
    """Unknown or unsupported message type."""

    def toMaxUploadType(self) -> maxModels.UploadType:
        """Convert MessageType to maxModels.UploadType.

        This method maps the internal MessageType enum to the corresponding
        UploadType enum used by the MAX bot library. The mapping groups
        related message types into broader upload categories.

        Returns:
            maxModels.UploadType: The corresponding upload type for MAX bot.
                - IMAGE: For IMAGE and STICKER message types
                - VIDEO: For ANIMATION, VIDEO, and VIDEO_NOTE message types
                - AUDIO: For AUDIO and VOICE message types
                - FILE: For DOCUMENT and any unknown/unsupported message types

        Example:
            >>> msg_type = MessageType.IMAGE
            >>> upload_type = msg_type.toMaxUploadType()
            >>> print(upload_type)
            UploadType.IMAGE
        """
        match self:
            case MessageType.IMAGE | MessageType.STICKER:
                return maxModels.UploadType.IMAGE
            case MessageType.ANIMATION | MessageType.VIDEO | MessageType.VIDEO_NOTE:
                return maxModels.UploadType.VIDEO
            case MessageType.AUDIO | MessageType.VOICE:
                return maxModels.UploadType.AUDIO
            case MessageType.DOCUMENT:
                return maxModels.UploadType.FILE
            case _:
                logger.warning(f"Unsupported MessageType for MAX: {self}, fallback to FILE")
                return maxModels.UploadType.FILE
