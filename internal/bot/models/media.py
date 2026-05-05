"""Media processing models for the bot.

This module provides data structures for tracking and managing asynchronous
media processing operations within the bot system.
"""

import asyncio
from typing import Any, Optional

from internal.models import MessageType


class MediaProcessingInfo:
    """Information about an ongoing media processing operation.

    This class tracks the state of asynchronous media processing tasks,
    including the message ID, media type, and the associated asyncio task.

    Attributes:
        id: The unique identifier of the message being processed.
        type: The type of media message being processed.
        task: The asyncio task handling the media processing, or None if not set.
    """

    __slots__ = ("id", "type", "task")

    def __init__(self, id: str, type: MessageType, task: Optional[asyncio.Task] = None):
        """Initialize media processing information.

        Args:
            id: The unique identifier of the message being processed.
            type: The type of media message being processed.
            task: The asyncio task handling the media processing. Defaults to None.
        """
        self.id = id
        self.type = type
        self.task = task

    async def awaitResult(self) -> Any:
        """Await the completion of the media processing task.

        Returns:
            The result of the completed media processing task.

        Raises:
            ValueError: If no task is set for this media processing operation.
        """
        if self.task is not None:
            return await self.task
        else:
            raise ValueError("Task is not set")

    def __str__(self) -> str:
        """Return a string representation of the media processing info.

        Returns:
            A formatted string containing the id, type, and task status.
        """
        return f"MediaProcessingInfo(id={self.id}, type={self.type}, task={self.task})"
