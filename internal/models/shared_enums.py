"""
Shared Enums: Enums that are used across multiple modules to avoid circular dependencies
"""

from enum import StrEnum


class MessageType(StrEnum):
    """Message type enum - shared between database and bot modules"""
    TEXT = "text"
    # PHOTO      - https://docs.python-telegram-bot.org/en/stable/telegram.photosize.html#telegram.PhotoSize
    IMAGE = "image"
    # STICKER    - https://docs.python-telegram-bot.org/en/stable/telegram.sticker.html#telegram.Sticker
    STICKER = "sticker"
    # ANIMATION  - https://docs.python-telegram-bot.org/en/stable/telegram.animation.html#telegram.Animation
    ANIMATION = "animation"
    # VIDEO      - https://docs.python-telegram-bot.org/en/stable/telegram.video.html#telegram.Video
    VIDEO = "video"
    # VideoNote  - https://docs.python-telegram-bot.org/en/stable/telegram.videonote.html#telegram.VideoNote
    VIDEO_NOTE = "video-note"
    # AUDIO      - https://docs.python-telegram-bot.org/en/stable/telegram.audio.html#telegram.Audio
    AUDIO = "audio"
    # VOICE      - https://docs.python-telegram-bot.org/en/stable/telegram.voice.html#telegram.Voice
    VOICE = "voice"
    # DOCUMENT   - https://docs.python-telegram-bot.org/en/stable/telegram.document.html#telegram.Document
    DOCUMENT = "document"
    # CHAT_PHOTO - https://docs.python-telegram-bot.org/en/stable/telegram.chatphoto.html#telegram.ChatPhoto
    UNKNOWN = "unknown"