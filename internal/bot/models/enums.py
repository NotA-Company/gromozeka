"""
Enums: Different enum types for bot models
"""

from enum import StrEnum


class LLMMessageFormat(StrEnum):
    JSON = "json"
    TEXT = "text"
    SMART = "smart"  # JSON for user messages and text for bot messages



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