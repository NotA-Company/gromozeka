"""
Models: Different data models for our bot
"""

import asyncio
from enum import StrEnum
import logging

from typing import Any, Dict, Optional


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
            "function={self.function}, kwargs={self.kwargs})"
        )

    def __str__(self) -> str:
        return self.__repr__()
