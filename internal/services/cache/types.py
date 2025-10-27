"""
Cache: TypedDict models for handlers cache
"""

from enum import StrEnum
from typing import Any, Dict, List, NotRequired, TypeAlias, TypedDict, TYPE_CHECKING

from internal.database.models import ChatInfoDict, ChatTopicInfoDict

if TYPE_CHECKING:
    from internal.bot.models.chat_settings import ChatSettingsKey, ChatSettingsValue


class HCChatCacheDict(TypedDict):
    settings: NotRequired[Dict["ChatSettingsKey", "ChatSettingsValue"]]
    info: NotRequired[ChatInfoDict]
    topicInfo: NotRequired[Dict[int, ChatTopicInfoDict]]


UserDataValueType: TypeAlias = str | List[str] | Dict[str, Any]
UserDataType: TypeAlias = Dict[str, UserDataValueType]


class HCChatUserCacheDict(TypedDict):
    data: NotRequired[UserDataType]


class UserActiveActionEnum(StrEnum):
    Configuration = "activeConfigureId"
    Summarization = "activeSummarizationId"


class HCUserCacheDict(TypedDict):
    activeConfigureId: NotRequired[Dict[str, Any]]
    activeSummarizationId: NotRequired[Dict[str, Any]]


class HandlersCacheDict(TypedDict):
    # Cache structure:
    chats: Dict[int, HCChatCacheDict]
    # "chats": Dict[int, Any]= {
    #     "<chatId>": Dict[str, Any] = {
    #         "settings": Dict[ChatSettingsKey, ChatSettingsValue] = {...},
    #         "info": Dict[str, any] = {...},
    #         "topics": Dict[int, Any] = {
    #             "<topicId>": Dict[str, Any] = {
    #                 "iconColor": Optional[int],
    #                 "customEmojiId": Optional[int],
    #                 "name": Optional[str],
    #             },
    #         },
    #     },
    # },
    chatUsers: Dict[str, HCChatUserCacheDict]
    # "chatUsers": Dict[str, Any] = {
    #     "<chatId>:<userId>": Dict[str, Any] = {
    #         "data": Dict[str, str|List["str"]] = {...},
    #     },
    # },
    users: Dict[int, HCUserCacheDict]
    # "users": Dict[int, Any] = {
    #     <userId>: Dict[str, Any] = {
    #         "activeConfigureId": Dict[str, Any] = {...},
    #         "activeSummarizationId": Dict[str, Any] = {...},
    #     },
    # },
