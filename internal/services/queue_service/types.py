"""
Delayed Tasks: Models for delayed task execution
"""

from enum import StrEnum
from typing import Any, Awaitable, Callable, Dict, TypeAlias


class DelayedTaskFunction(StrEnum):
    SEND_MESSAGE = "sendMessage"
    """Send delayed message"""
    DELETE_MESSAGE = "deleteMessage"
    """Delayed message delete"""

    CRON_JOB = "cronJob"
    """Each-minute Cron job"""

    DO_EXIT = "doExit"
    """Actully - it's onExit event"""


class DelayedTask:
    """Represents a delayed task to be executed at a specific time.

    Attributes:
        taskId: Unique identifier for the task
        delayedUntil: Unix timestamp when the task should be executed
        function: The type of function to execute
        kwargs: Arguments to pass to the task handler
    """

    def __init__(self, taskId: str, delayedUntil: float, function: DelayedTaskFunction, kwargs: Dict[str, Any]):
        """Initialize a delayed task.

        Args:
            taskId: Unique identifier for the task
            delayedUntil: Unix timestamp when the task should be executed
            function: The type of function to execute
            kwargs: Arguments to pass to the task handler
        """
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


DelayedTaskHandler: TypeAlias = Callable[[DelayedTask], Awaitable[None]]
