"""TypingManager
TODO: write docstring
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
    """
    TODO: rewrite docstrings
    Helper class to manage continuous typing actions during long-running operations, dood!

    This class provides a way to continuously send typing actions (like TYPING, UPLOAD_PHOTO, etc.)
    to Telegram chats while time-consuming operations are in progress. It implements the
    async context manager protocol for easy integration with async operations.

    The manager handles timing control, state tracking, and automatic cleanup when operations
    complete or timeout. It's particularly useful for commands that involve LLM processing,
    media handling, or other operations that might take several seconds.

    Usage:
        ```python
        async with await self.startTyping(message, action=ChatAction.TYPING) as typingManager:
            # Long-running operation here
            result = await someLongOperation()
        ```

    Attributes:
        running: Boolean flag indicating if typing is currently active
        action: The ChatAction to send (e.g., TYPING, UPLOAD_PHOTO, RECORD_VIDEO)
        maxTimeout: Maximum duration in seconds to keep typing active
        repeatInterval: Interval in seconds between typing actions
        _task: Internal async task managing the typing loop
        _sendActionFn: Function to call for sending typing actions
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
        """
        Initialize the TypingManager with specified parameters, dood!

        Sets up the typing manager with the action to perform, timeout limits,
        and internal state for managing the typing loop.

        Args:
            action: The ChatAction to send (e.g., TYPING, UPLOAD_PHOTO)
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
        """
        Set the asyncio task and action function for this TypingManager, dood!

        Configures the typing manager with the task to execute and the function
        to call for sending typing actions. Resets the running state and start time.

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
        """
        Stop the typing task and wait for it to complete, dood!

        Sets the running flag to False and optionally awaits the completion of the typing task.
        If the task is not awaitable, logs a warning message. Clears the task reference
        to prevent multiple stops.

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
        """
        Check if typing is still active and within timeout limits, dood!

        Determines if typing should continue based on the running flag and
        whether the maximum timeout has been exceeded.

        Returns:
            True if typing is active and within timeout, False otherwise
        """
        if not self.running:
            return False

        return not self.isTimeout()

    def isTimeout(self) -> bool:
        """
        Check if the typing manager has exceeded its maximum timeout duration, dood!

        Determines whether the typing manager has exceeded its timeout limit based on
        the elapsed time since it started. Returns True if the manager has exceeded
        its timeout limit, False if it is still within the limit.

        Returns:
            bool: True if timeout exceeded, False if still within timeout limits
        """
        return self.startTime + self.maxTimeout <= time.time()

    async def tick(self) -> int:
        """
        Advance the iteration counter for timing control, dood!

        Sleeps for 1 second and increments the iteration counter, wrapping around
        based on the repeatInterval. This method is used to control the timing
        of typing actions in the continuous typing loop.

        Returns:
            The new iteration counter value
        """
        await asyncio.sleep(1)

        self.iteration = (self.iteration + 1) % self.repeatInterval
        return self.iteration

    async def sendTypingAction(self) -> None:
        """
        Send a typing action and reset the iteration counter, dood!

        This method is called to send a typing action and reset the iteration
        counter to 0. This is used to control the timing of subsequent typing
        actions in the continuous typing loop. Only sends if the manager is running.
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
        """
        Enter the context manager, dood!

        Returns:
            TypingManager: The TypingManager instance
        """
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """
        Exit the context manager, dood!

        Stops the typing task and waits for it to complete.
        """
        await self.stopTask()
