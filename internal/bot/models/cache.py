"""
Cache: TypedDict models for handlers cache
"""

from typing import Any, Dict, NotRequired, TypedDict

from internal.database.models import ChatInfoDict

from .chat_settings import ChatSettingsKey, ChatSettingsValue


class HCChatCacheDict(TypedDict):
    settings: NotRequired[Dict[ChatSettingsKey, ChatSettingsValue]]
    info: NotRequired[ChatInfoDict]
    topics: NotRequired[Dict[int, Any]]


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
    chatUsers: Dict[str, Dict[str, Any]]
    # "chatUsers": Dict[str, Any] = {
    #     "<chatId>:<userId>": Dict[str, Any] = {
    #         "data": Dict[str, str|List["str"]] = {...},
    #     },
    # },
    users: Dict[int, Dict[str, Any]]
    # "users": Dict[int, Any] = {
    #     <userId>: Dict[str, Any] = {
    #         "activeConfigureId": Dict[str, Any] = {...},
    #         "activeSummarizationId": Dict[str, Any] = {...},
    #     },
    # },


class UserMetadataDict(TypedDict):
    notSpammer: NotRequired[bool]  # True if user defined as not spammer