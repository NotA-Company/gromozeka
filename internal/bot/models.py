"""
Models: Different data models for our bot
"""
import asyncio
from enum import StrEnum
import logging

from typing import Any, Optional

from telegram import Message

logger = logging.getLogger(__name__)


class LLMMessageFormat(StrEnum):
    JSON = "json"
    TEXT = "text"

class MessageType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    #VIDEO = "video"
    #AUDIO = "audio"
    #DOCUMENT = "document"
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

