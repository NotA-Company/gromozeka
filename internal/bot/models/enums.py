"""
Enums: Different enum types for bot models
"""

from enum import StrEnum


class LLMMessageFormat(StrEnum):
    JSON = "json"
    TEXT = "text"
    SMART = "smart"  # JSON for user messages and text for bot messages


class MessageType(StrEnum):
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



class ButtonDataKey(StrEnum):
    ConfigureAction = "a"
    SummarizationAction = "s"

    ChatId = "c"
    TopicId = "t"
    MaxMessages = "m"
    Prompt = "p"

    Key = "k"
    Value = "v"
    UserAction = "ua"


class ButtonConfigureAction(StrEnum):
    Init = "init"
    Cancel = "cancel"

    ConfigureChat = "chat"
    ConfigureKey = "sk"
    SetTrue = "st"
    SetFalse = "sf"
    ResetValue = "s-"
    SetValue = "sv"


class ButtonSummarizationAction(StrEnum):
    Summarization = "s"
    TopicSummarization = "t"
    SummarizationStart = "s+"
    TopicSummarizationStart = "t+"

    Cancel = "cancel"

    @classmethod
    def all(cls) -> list[str]:
        return [v.value for v in cls]