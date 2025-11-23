"""
Enums: Different enum types for bot models
"""

from enum import StrEnum


class BotProvider(StrEnum):
    """TODO"""

    TELEGRAM = "telegram"
    MAX = "max"


class LLMMessageFormat(StrEnum):
    JSON = "json"
    TEXT = "text"
    SMART = "smart"  # JSON for user messages and text for bot messages


class ButtonDataKey(StrEnum):
    # Which action is this button for, should be unique
    # Use as less symbols as possible to save space in data
    ConfigureAction = "a"  # `a` - Action
    SummarizationAction = "s"  # `s` - Summarization
    SpamAction = "spam"  # `spam` - spam messages don't use to much arguments
    UserDataConfigAction = "d"  # `d` - Data
    TopicManagementAction = "tm"  # `tm` Topic Management

    ChatId = "c"
    TopicId = "t"
    MaxMessages = "m"
    Prompt = "prompt"
    Page = "p"

    Key = "k"
    Value = "v"
    UserAction = "ua"
    ActionHash = "h"


class ButtonConfigureAction(StrEnum):
    """ButtonDataKey.ConfigureAction values"""

    Init = "init"
    Cancel = "cancel"

    ConfigureChat = "chat"
    ConfigureKey = "sk"
    SetTrue = "st"
    SetFalse = "sf"
    ResetValue = "s-"
    SetValue = "sv"


class ButtonSummarizationAction(StrEnum):
    """ButtonDataKey.SummarizationAction values"""

    Summarization = "s"
    TopicSummarization = "t"
    SummarizationStart = "s+"
    TopicSummarizationStart = "t+"

    Cancel = "cancel"

    @classmethod
    def all(cls) -> list[str]:
        return [v.value for v in cls]


class ButtonUserDataConfigAction(StrEnum):
    """ButtonDataKey.UserDataConfigurationAction values"""

    Init = "init"
    Cancel = "cancel"

    ChatSelected = "c"
    KeySelected = "k"
    SetValue = "s"
    DeleteKey = "d"
    ClearChatData = "clear"

    @classmethod
    def all(cls) -> list[str]:
        return [v.value for v in cls]


class ButtonTopicManagementAction(StrEnum):
    """ButtonDataKey.TopicManagementAction values"""

    Init = "init"
    Cancel = "cancel"

    ChatSelected = "c"
    TopicSelected = "t"

    @classmethod
    def all(cls) -> list[str]:
        return [v.value for v in cls]
