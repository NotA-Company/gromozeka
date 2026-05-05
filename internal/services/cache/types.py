"""Cache: TypedDict models for handlers cache.

This module defines the type structures used for caching data in bot handlers.
It provides TypedDict models for various cache levels including chat-level,
user-level, and persistent storage. These types are used throughout the
internal services cache system to maintain state and improve performance.

The cache hierarchy includes:
- HandlersCacheDict: Root cache structure containing all handler data
- HCChatCacheDict: Chat-specific cache including settings, info, topics, and admins
- HCChatUserCacheDict: User-specific data within a chat
- HCUserCacheDict: User-level cache for active actions
- HCChatPersistentCacheDict: Persistent chat data that survives restarts
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Dict, List, NotRequired, Optional, Tuple, TypeAlias, TypedDict

from internal.database.models import ChatInfoDict, ChatTopicInfoDict
from internal.models import MessageIdType
from lib import utils

if TYPE_CHECKING:
    from internal.bot.models.chat_settings import ChatSettingsKey, ChatSettingsValue


class HCSpamWarningMessageInfo(TypedDict):
    """Spam warning message metadata.

    Stores information about spam warning messages sent to users, including
    the parent message ID, user details, and timestamp. This is used to track
    spam warnings and prevent duplicate warnings.

    Attributes:
        parentMessageId: Optional ID of the parent message that triggered the
            spam warning. Can be None if the warning was not triggered by a
            specific message.
        userId: The Telegram user ID of the user who received the warning.
        username: The username of the user who received the warning.
        ts: Unix timestamp when the warning was sent.
    """

    parentMessageId: NotRequired[Optional[MessageIdType]]
    userId: int
    username: str
    ts: float


class HCChatPersistentCacheDict(TypedDict):
    """Persistent chat cache data.

    Contains chat data that should persist across bot restarts. This includes
    spam warning messages and other long-term tracking information that needs
    to survive cache invalidation.

    Attributes:
        spamWarningMessages: Dictionary mapping message IDs to spam warning
            metadata. Used to track which messages have been flagged as spam
            warnings to avoid duplicates.
    """

    spamWarningMessages: NotRequired[Dict[MessageIdType, HCSpamWarningMessageInfo]]


class HCChatAdminsDict(TypedDict):
    """Chat admins list with update timestamp.

    Maintains a cached list of chat administrators with metadata about when
    the list was last updated. This cache helps reduce API calls to fetch
    admin information.

    Attributes:
        updatedAt: Unix timestamp when the admin list was last updated.
            Used to determine if the cache needs refreshing.
        admins: Dictionary mapping user IDs to admin information tuples.
            Each tuple contains (username, displayName). The username is
            primarily used for debug purposes, while the user ID is the
            primary identifier.
    """

    updatedAt: float
    admins: Dict[int, Tuple[str, str]]


class HCChatCacheDict(TypedDict):
    """Complete chat cache including settings, info, topics, and admins.

    Comprehensive cache structure for a single chat, containing all relevant
    data needed by bot handlers. This includes chat settings, metadata,
    topic information, and administrator data.

    Attributes:
        settings: Dictionary of current chat settings. Maps setting keys to
            their current values. These are the active settings being used.
        cachedSettings: Dictionary of cached chat settings. May contain
            settings that are not currently active but are kept for reference
            or rollback purposes.
        info: Chat metadata and information from the database. Includes
            details like chat title, description, and other properties.
        topicInfo: Dictionary mapping topic IDs to topic metadata. Used in
            forum groups to track individual topics and their properties.
        admins: Administrator information for the chat, including the list
            of admins and when it was last updated.
    """

    settings: NotRequired[Dict["ChatSettingsKey", "ChatSettingsValue"]]
    cachedSettings: NotRequired[Dict["ChatSettingsKey", "ChatSettingsValue"]]
    info: NotRequired[ChatInfoDict]
    topicInfo: NotRequired[Dict[int, ChatTopicInfoDict]]
    admins: NotRequired[HCChatAdminsDict]


UserDataValueType: TypeAlias = str | List[str] | Dict[str, Any]
"""Type alias for user data value types.

Defines the allowed types for values stored in user data. User data can be
a simple string, a list of strings, or a dictionary with string keys and
arbitrary values.
"""

UserDataType: TypeAlias = Dict[str, UserDataValueType]
"""Type alias for user data structure.

A dictionary mapping string keys to user data values. Each value can be
a string, list of strings, or dictionary. This structure is used to store
arbitrary user-specific data within the cache.
"""


class HCChatUserCacheDict(TypedDict):
    """Cache data for a specific user within a chat.

    Stores user-specific data that is scoped to a particular chat. This is
    used to maintain per-user state within the context of a chat, such as
    preferences, temporary data, or interaction history.

    Attributes:
        data: Dictionary containing user-specific data. Keys are string
            identifiers and values can be strings, lists of strings, or
            dictionaries with arbitrary data.
    """

    data: NotRequired[UserDataType]


class UserActiveActionEnum(StrEnum):
    """Active action types for users.

    Enumeration of possible active actions that a user can be performing.
    These actions represent ongoing operations or states that require
    tracking across multiple message interactions.

    Attributes:
        Configuration: User is actively configuring bot settings.
        Summarization: User is in the process of generating or viewing
            a summary.
        UserDataConfig: User is configuring their personal data or preferences.
        TopicManagement: User is managing forum topics (in forum groups).
    """

    Configuration = "activeConfigure"
    Summarization = "activeSummarization"
    UserDataConfig = "activeUserDataConfig"
    TopicManagement = "activeTopicManagement"


class UserActiveConfigurationDict(TypedDict):
    """Configuration data for an active user action.

    Stores the context and state information for a user's active action.
    This includes the message ID that initiated the action, the chat ID,
    and any payload data associated with the action.

    Attributes:
        data: Dictionary containing the action-specific payload data.
            The structure depends on the action type defined in
            UserActiveActionEnum.
        messageId: The ID of the message that initiated this active action.
            Used to reference the original interaction.
        messageChatId: The chat ID where the initiating message was sent.
            Used to scope the action to a specific chat.
    """

    data: utils.PayloadDict
    messageId: MessageIdType
    messageChatId: int


HCUserCacheDict = Dict[UserActiveActionEnum, UserActiveConfigurationDict]
"""User-level cache for active actions.

Maps active action types to their configuration data. This structure allows
tracking multiple concurrent active actions for a user, though typically
only one action is active at a time per user.

Type:
    Dict[UserActiveActionEnum, UserActiveConfigurationDict]: A dictionary
    where keys are action types from UserActiveActionEnum and values are
    the corresponding configuration dictionaries.
"""


class HandlersCacheDict(TypedDict):
    """Root cache structure for all bot handlers.

    The top-level cache structure that contains all cached data for the bot's
    handlers. This includes chat-level caches, user-within-chat caches, and
    user-level caches. This structure is the entry point for all cache
    operations in the handlers system.

    Attributes:
        chats: Dictionary mapping chat IDs to their complete cache data.
            Each chat has its own HCChatCacheDict containing settings,
            info, topics, and admins.
        chatUsers: Dictionary mapping composite keys (typically "chatId:userId")
            to user-specific cache data within chats. This allows efficient
            lookup of user data scoped to a particular chat.
        users: Dictionary mapping user IDs to their user-level cache data.
            Contains active actions and other user-specific state that is
            not scoped to a particular chat.
    """

    chats: Dict[int, HCChatCacheDict]
    chatUsers: Dict[str, HCChatUserCacheDict]
    users: Dict[int, HCUserCacheDict]
