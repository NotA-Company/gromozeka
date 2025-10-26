"""
Cache: TypedDict models for handlers cache
"""

from enum import StrEnum
from typing import Any, Dict, NotRequired, TypedDict, TYPE_CHECKING

from internal.database.models import ChatInfoDict

if TYPE_CHECKING:
    from internal.bot.models.chat_settings import ChatSettingsKey, ChatSettingsValue


class HCChatCacheDict(TypedDict):
    settings: NotRequired[Dict["ChatSettingsKey", "ChatSettingsValue"]]
    info: NotRequired[ChatInfoDict]
    topics: NotRequired[Dict[int, Any]]


class HCChatUserCacheDict(TypedDict):
    data: NotRequired[Dict[str, str | list[str] | dict[str, str]]]


class UserActiveActionEnum(StrEnum):
    configure = "activeConfigureId"
    summarize = "activeSummarizationId"


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
