"""Typing manager for continuous typing actions during long-running operations.

Provides TypingManager class for managing continuous typing indicators (TYPING, UPLOAD_PHOTO, etc.)
during time-consuming bot operations. Implements async context manager protocol for easy integration.
"""

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Optional

from internal.bot.common.models import TypingAction

logger = logging.getLogger(__name__)


class TypingManager:
    """Manages continuous typing actions during long-running operations.

    Provides continuous typing indicators (TYPING, UPLOAD_PHOTO, etc.) to chat platforms
    while time-consuming operations are in progress. Implements async context manager
    protocol for automatic cleanup and timeout handling.

    Attributes:
        running: Boolean flag indicating if typing is currently active
        action: The TypingAction to send (e.g., TYPING, UPLOAD_PHOTO, RECORD_VIDEO)
        maxTimeout: Maximum duration in seconds to keep typing active
        repeatInterval: Interval in seconds between typing actions
        startTime: Timestamp when typing started (for timeout calculation)
        iteration: Current iteration counter for timing control
    """

    __slots__ = (
        "running",
        "action",
        "maxTimeout",
        "repeatInterval",
        "_task",
        "_sendActionFn",
        "startTime",
        "iteration",
    )

    def __init__(
        self,
        action: TypingAction,
        maxTimeout: int,
        repeatInterval: int,
    ) -> None:
        """Initialize the TypingManager with specified parameters.

        Args:
            action: The TypingAction to send (e.g., TYPING, UPLOAD_PHOTO)
            maxTimeout: Maximum duration in seconds to keep typing active
            repeatInterval: Interval in seconds between typing actions
        """
        self.running: bool = True
        self.action: TypingAction = action
        self.maxTimeout: int = maxTimeout
        self.repeatInterval: int = repeatInterval

        self._task: Optional[asyncio.Task] = None
        self._sendActionFn: Optional[Callable[[], Awaitable]] = None

        self.startTime: float = time.time()
        self.iteration: int = 0

    async def startTask(
        self,
        task: asyncio.Task,
        sendActionFn: Optional[Callable[[], Awaitable]] = None,
        runTaskOnStart: bool = True,
    ) -> None:
        """Configure the typing manager with task and action function.

        Args:
            task: The asyncio task to manage for continuous typing actions
            sendActionFn: Optional function to call for sending typing actions
            runTaskOnStart: If True, immediately send a typing action when starting
        """
        self._task = task
        self._sendActionFn = sendActionFn
        self.running = True
        self.startTime = time.time()

        if runTaskOnStart:
            await self.sendTypingAction()

    async def stopTask(self, wait: bool = True) -> None:
        """Stop the typing task and optionally wait for completion.

        Args:
            wait: If True, wait for the task to complete before returning
        """
        self.running = False
        if self._task is None:
            return
        elif not inspect.isawaitable(self._task):
            logger.warning(f"TypingManager: {type(self._task).__name__}({self._task}) is not awaitable")
        elif wait:
            await self._task
        # it is possible, that we'll stop it several times:
        #  (via sendMessage() and as aexit from contextManager)
        #  it isn't error, so need to clear self.task
        self._task = None

    def isRunning(self) -> bool:
        """Check if typing is still active and within timeout limits.

        Returns:
            True if typing is active and within timeout, False otherwise
        """
        if not self.running:
            return False

        return not self.isTimeout()

    def isTimeout(self) -> bool:
        """Check if the typing manager has exceeded its maximum timeout duration.

        Returns:
            True if timeout exceeded, False if still within timeout limits
        """
        return self.startTime + self.maxTimeout <= time.time()

    async def tick(self) -> int:
        """Advance the iteration counter for timing control.

        Sleeps for 1 second and increments the iteration counter, wrapping around
        based on the repeatInterval.

        Returns:
            The new iteration counter value
        """
        await asyncio.sleep(1)

        self.iteration = (self.iteration + 1) % self.repeatInterval
        return self.iteration

    async def sendTypingAction(self) -> None:
        """Send a typing action and reset the iteration counter.

        Sends the configured typing action and resets the iteration counter to 0.
        Only sends if the manager is currently running.
        """
        if not self.isRunning():
            logger.warning("TypingManager::sendTypingAction(): not running")
            return

        self.iteration = 0
        if self._sendActionFn:
            await self._sendActionFn()
        else:
            logger.warning("TypingManager: sendTypingAction called while action is None")

    async def __aenter__(self) -> "TypingManager":
        """Enter the async context manager.

        Returns:
            The TypingManager instance
        """
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Exit the async context manager.

        Args:
            exc_type: Exception type if an exception occurred
            exc: Exception instance if an exception occurred
            tb: Traceback if an exception occurred
        """
        await self.stopTask()
