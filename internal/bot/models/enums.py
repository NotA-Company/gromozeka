"""
Enums: Different enum types for bot models.
"""

from enum import StrEnum


class BotProvider(StrEnum):
    """Supported bot messaging providers.

    This enum defines the available messaging platforms that the bot can
    integrate with for sending and receiving messages.

    Attributes:
        TELEGRAM: Telegram messaging platform.
        MAX: Max messaging platform.
    """

    TELEGRAM = "telegram"
    MAX = "max"


class LLMMessageFormat(StrEnum):
    """Message format options for LLM interactions.

    This enum defines the format in which messages are sent to and received
    from the Language Model (LLM) service.

    Attributes:
        JSON: Messages are formatted as JSON objects.
        TEXT: Messages are formatted as plain text.
        SMART: Hybrid format using JSON for user messages and text for bot messages.
    """

    JSON = "json"
    """Messages are formatted as JSON objects."""
    TEXT = "text"
    """Messages are formatted as plain text."""
    SMART = "smart"
    """Hybrid format using JSON for user messages and text for bot messages."""


class ButtonDataKey(StrEnum):
    """Keys used in button callback data.

    This enum defines the keys used to encode data in button callbacks.
    Keys are kept short to minimize data size in callback payloads.

    Action Keys:
        ConfigureAction: Key for configuration-related actions.
        SummarizationAction: Key for summarization-related actions.
        SpamAction: Key for spam-related actions.
        UserDataConfigAction: Key for user data configuration actions.
        TopicManagementAction: Key for topic management actions.

    Parameter Keys:
        ChatId: Chat identifier.
        TopicId: Topic identifier.
        MaxMessages: Maximum number of messages.
        Prompt: Prompt text.
        Page: Page number.
        Tag: Freeform tag string (knowledge-config wizard tag filter).

    Generic Keys:
        Key: Generic key identifier.
        Value: Generic value identifier.
        UserAction: User action identifier.
        ActionHash: Action hash for verification.
    """

    # Action keys
    ConfigureAction = "a"
    """`a` - Action"""
    SummarizationAction = "s"
    """`s` - Summarization"""
    SpamAction = "spam"
    """`spam` - spam messages don't use to much arguments"""
    UserDataConfigAction = "d"
    """`d` - Data"""
    TopicManagementAction = "tm"
    """`tm` Topic Management"""

    # Parameter keys
    ChatId = "c"
    TopicId = "t"
    MaxMessages = "m"
    Prompt = "prompt"
    Page = "p"
    Tag = "tg"
    """`tg` - freeform tag string (carried in knowledge-config payloads)."""

    # Generic keys
    Key = "k"
    Value = "v"
    UserAction = "ua"
    ActionHash = "h"


class ButtonConfigureAction(StrEnum):
    """Configuration action types for button callbacks.

    This enum defines the specific actions available in the configuration
    workflow, used as values for ButtonDataKey.ConfigureAction.

    Attributes:
        Init: Initialize configuration workflow.
        Cancel: Cancel current configuration.
        ConfigureChat: Configure chat settings.
        ConfigureKey: Configure a specific key.
        SetTrue: Set a boolean value to true.
        SetFalse: Set a boolean value to false.
        ResetValue: Reset a value to default.
        SetValue: Set a specific value.
    """

    Init = "init"
    Cancel = "cancel"

    ConfigureChat = "chat"
    ConfigureKey = "sk"
    SetTrue = "st"
    SetFalse = "sf"
    ResetValue = "s-"
    SetValue = "sv"


class ButtonSummarizationAction(StrEnum):
    """Summarization action types for button callbacks.

    This enum defines the specific actions available in the summarization
    workflow, used as values for ButtonDataKey.SummarizationAction.

    Attributes:
        Summarization: Perform general summarization.
        TopicSummarization: Perform topic-specific summarization.
        SummarizationStart: Start general summarization process.
        TopicSummarizationStart: Start topic-specific summarization process.
        Cancel: Cancel current summarization operation.
    """

    Summarization = "s"
    TopicSummarization = "t"
    SummarizationStart = "s+"
    TopicSummarizationStart = "t+"

    Cancel = "cancel"

    @classmethod
    def all(cls) -> list[str]:
        """Get all enumeration values as strings.

        Returns:
            List of all enum values as strings.
        """
        return [v.value for v in cls]


class ButtonUserDataConfigAction(StrEnum):
    """User data configuration action types for button callbacks.

    This enum defines the specific actions available in the user-memories
    configuration wizard (``/knowledge_config``), used as values for
    ButtonDataKey.UserDataConfigAction. The wizard browses a user's own
    ``user_memories`` rows by type and lets them view/delete individual ones.

    Attributes:
        Init: Initialize wizard (chat picker).
        Cancel: Cancel current configuration.
        ChatSelected: Chat has been selected; render the MemoryType picker.
        TopicSelected: A MemoryType (or ``"all"``) was picked; render the
            paginated memory list. May also carry an optional ``Tag`` filter
            (Phase 5b) that narrows the list to memories carrying that tag.
        MemorySelected: A specific ``memory_id`` was picked; render the
            per-memory detail view.
        DeleteMemory: Delete the selected memory by id (unrestricted).
        NextPage: Advance the memory list to the next page (offset +PAGE_SIZE).
        PrevPage: Step the memory list back one page (offset -PAGE_SIZE,
            clamped at 0).
        TagFilter: Render the tag picker for tag-based filtering of the
            memory list (Phase 5b). Selecting a tag returns to
            ``TopicSelected`` with the tag applied.
    """

    Init = "init"
    Cancel = "cancel"

    ChatSelected = "c"
    TopicSelected = "ts"
    MemorySelected = "ms"
    DeleteMemory = "dm"
    NextPage = "np"
    PrevPage = "pp"
    TagFilter = "tf"

    @classmethod
    def all(cls) -> list[str]:
        """Get all enumeration values as strings.

        Returns:
            List of all enum values as strings.
        """
        return [v.value for v in cls]


class ButtonTopicManagementAction(StrEnum):
    """Topic management action types for button callbacks.

    This enum defines the specific actions available in the topic management
    workflow, used as values for ButtonDataKey.TopicManagementAction.

    Attributes:
        Init: Initialize topic management workflow.
        Cancel: Cancel current operation.
        ChatSelected: Chat has been selected.
        TopicSelected: Topic has been selected.
    """

    Init = "init"
    Cancel = "cancel"

    ChatSelected = "c"
    TopicSelected = "t"

    @classmethod
    def all(cls) -> list[str]:
        """Get all enumeration values as strings.

        Returns:
            List of all enum values as strings.
        """
        return [v.value for v in cls]
