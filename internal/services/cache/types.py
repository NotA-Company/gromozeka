"""
Cache: TypedDict models for handlers cache
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Dict, List, NotRequired, Optional, TypeAlias, TypedDict

from internal.database.models import ChatInfoDict, ChatTopicInfoDict
from internal.models import MessageIdType

if TYPE_CHECKING:
    from internal.bot.models.chat_settings import ChatSettingsKey, ChatSettingsValue


class HCSpamWarningMessageInfo(TypedDict):
    """Spam warning message metadata, dood."""

    # messageId: MessageIdType
    parentMessageId: NotRequired[Optional[MessageIdType]]
    userId: int
    username: str
    ts: float


class HCChatPersistentCacheDict(TypedDict):
    """Persistent chat cache data, dood."""

    spamWarningMessages: NotRequired[Dict[MessageIdType, HCSpamWarningMessageInfo]]


class HCChatAdminsDict(TypedDict):
    """Chat admins list with update timestamp, dood."""

    # When list was updated last time
    updatedAt: float
    # Dict[userId, username], Actually only iserId is needed, username is used for debug purposes only
    admins: Dict[int, str]


class HCChatCacheDict(TypedDict):
    """Complete chat cache including settings, info, topics, and admins, dood."""

    settings: NotRequired[Dict["ChatSettingsKey", "ChatSettingsValue"]]
    info: NotRequired[ChatInfoDict]
    topicInfo: NotRequired[Dict[int, ChatTopicInfoDict]]
    admins: NotRequired[HCChatAdminsDict]


UserDataValueType: TypeAlias = str | List[str] | Dict[str, Any]
UserDataType: TypeAlias = Dict[str, UserDataValueType]


class HCChatUserCacheDict(TypedDict):
    """Cache data for a specific user within a chat, dood."""

    data: NotRequired[UserDataType]


class UserActiveActionEnum(StrEnum):
    """Active action types for users, dood."""

    Configuration = "activeConfigure"
    Summarization = "activeSummarization"
    UserDataConfig = "activeUserDataConfig"


class UserActiveConfigurationDict(TypedDict):

    data: Dict[str | int, Any]
    messageId: MessageIdType
    messageChatId: int


class HCUserCacheDict(TypedDict):
    """User-level cache for active actions, dood."""

    activeConfigure: NotRequired[UserActiveConfigurationDict]
    activeSummarization: NotRequired[UserActiveConfigurationDict]
    activeUserDataConfig: NotRequired[UserActiveConfigurationDict]


class HandlersCacheDict(TypedDict):
    """Root cache structure for all bot handlers, dood."""

    # Cache structure:
    chats: Dict[int, HCChatCacheDict]
    chatUsers: Dict[str, HCChatUserCacheDict]
    users: Dict[int, HCUserCacheDict]
