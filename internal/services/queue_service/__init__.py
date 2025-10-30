"""Queue service package.

This package provides a singleton QueueService class that manages asynchronous task execution
through two primary queues:
1. Background tasks queue - for immediate async task execution with age-based processing
2. Delayed tasks queue - for scheduled task execution at specific timestamps

The service supports task persistence through database integration and provides handlers
for different types of delayed tasks.

Example:
    >>> from internal.services.queue_service import QueueService, DelayedTaskFunction
    >>> queueService = QueueService.getInstance()
    >>> await queueService.addBackgroundTask(asyncio.create_task(some_coroutine()))
    >>> await queueService.addDelayedTask(
    ...     delayedUntil=time.time() + 3600,
    ...     function=DelayedTaskFunction.SEND_MESSAGE,
    ...     kwargs={"chat_id": 123, "text": "Hello"}
    ... )
"""

from .constants import MAX_QUEUE_AGE, MAX_QUEUE_LENGTH
from .service import QueueService, makeEmptyAsyncTask
from .types import DelayedTask, DelayedTaskFunction, DelayedTaskHandler

__all__ = [
    # Service
    "QueueService",
    "makeEmptyAsyncTask",
    # Types
    "DelayedTask",
    "DelayedTaskFunction",
    "DelayedTaskHandler",
    # Constants
    "MAX_QUEUE_LENGTH",
    "MAX_QUEUE_AGE",
]
