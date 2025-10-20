"""
Models: Different data models for our bot
"""

import asyncio
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
import logging

from typing import Any, Callable, Dict, NotRequired, Optional, Sequence, Set, TypedDict

from internal.database.models import ChatInfoDict

from .chat_settings import ChatSettingsKey, ChatSettingsValue


logger = logging.getLogger(__name__)


class LLMMessageFormat(StrEnum):
    JSON = "json"
    TEXT = "text"
    SMART = "smart"  # JSON for user messages and text for bot messages


class MessageType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    # VIDEO = "video"
    # AUDIO = "audio"
    # DOCUMENT = "document"
    STICKER = "sticker"
    UNKNOWN = "unknown"


class MediaProcessingInfo:
    def __init__(self, id: str, type: MessageType, task: Optional[asyncio.Task] = None):
        self.id = id
        self.type = type
        self.task = task

    async def awaitResult(self) -> Any:
        if self.task is not None:
            return await self.task
        else:
            raise ValueError("Task is not set")


class DelayedTaskFunction(StrEnum):
    SEND_MESSAGE = "sendMessage"
    DELETE_MESSAGE = "deleteMessage"
    PROCESS_BACKGROUND_TASKS = "processBackgroundTasks"
    DO_EXIT = "doExit"


class DelayedTask:

    def __init__(self, taskId: str, delayedUntil: float, function: DelayedTaskFunction, kwargs: Dict[str, Any]):
        self.taskId = taskId
        self.delayedUntil = delayedUntil
        self.function = function
        self.kwargs = kwargs

    def __lt__(self, other: "DelayedTask") -> bool:
        return self.delayedUntil < other.delayedUntil

    def __gt__(self, other: "DelayedTask") -> bool:
        return self.delayedUntil > other.delayedUntil

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DelayedTask):
            return False

        return self.delayedUntil == other.delayedUntil

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __repr__(self) -> str:
        return (
            f"DelayedTask(taskId={self.taskId}, delayedUntil={self.delayedUntil}, "
            f"function={self.function}, kwargs={self.kwargs})"
        )

    def __str__(self) -> str:
        return self.__repr__()


# Handlers Cache TypedDict


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


class CommandCategory(Enum):
    DEFAULT = auto()  # Available everywhere
    PRIVATE = auto()  # Available in private chats
    GROUP = auto()  # Available in group chats
    ADMIN = auto()  # Available in group chats for Admins
    BOT_OWNER = auto()  # Available for Bot Owners
    HIDDEN = auto()  # Hide from command list


@dataclass
class CommandHandlerInfo:
    commands: Sequence[str]
    shortDescription: str
    helpMessage: str
    categories: Set[CommandCategory]
    # handler: tgTypes.HandlerCallback[tgUpdate.Update, tgTypes.CCT, tgTypes.RT],
    handler: Callable
