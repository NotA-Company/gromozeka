"""
Media: Models for media processing
"""

import asyncio
from typing import Any, Optional

from .enums import MessageType


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