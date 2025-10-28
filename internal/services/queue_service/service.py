"""
Queue Service Module

This module provides a singleton QueueService class that manages asynchronous task execution
through two primary queues:
1. Background tasks queue - for immediate async task execution with age-based processing
2. Delayed tasks queue - for scheduled task execution at specific timestamps

The service supports task persistence through database integration and provides handlers
for different types of delayed tasks, dood!

Classes:
    QueueService: Singleton service managing async and delayed task queues

Example:
    >>> queueService = QueueService.getInstance()
    >>> await queueService.addBackgroundTask(asyncio.create_task(some_coroutine()))
    >>> await queueService.addDelayedTask(
    ...     delayedUntil=time.time() + 3600,
    ...     function=DelayedTaskFunction.SEND_MESSAGE,
    ...     kwargs={"chat_id": 123, "text": "Hello"}
    ... )
"""

import asyncio
import inspect
import json
import logging
import time
import uuid
from threading import RLock
from typing import Any, Dict, List, Optional

import lib.utils as utils
from internal.database.wrapper import DatabaseWrapper

from . import constants
from .types import DelayedTask, DelayedTaskFunction, DelayedTaskHandler

logger = logging.getLogger(__name__)


def makeEmptyAsyncTask() -> asyncio.Task:
    """Create an empty async task."""
    return asyncio.create_task(asyncio.sleep(0))


class QueueService:
    """
    Singleton service for managing asynchronous and delayed task execution, dood!

    This class implements a thread-safe singleton pattern and manages two types of queues:
    - Background tasks queue: Processes asyncio.Task objects with age-based triggering
    - Delayed tasks queue: Priority queue for scheduled task execution at specific times

    The service persists delayed tasks to database for recovery after restarts and
    supports registering custom handlers for different task types.

    Attributes:
        db (Optional[DatabaseWrapper]): Database connection for task persistence
        asyncTasksQueue (asyncio.Queue): Queue for background async tasks
        queueLastUpdated (float): Timestamp of last queue update
        delayedActionsQueue (asyncio.PriorityQueue): Priority queue for delayed tasks
        tasksHandlers (Dict[DelayedTaskFunction, List[DelayedTaskHandler]]):
            Registered handlers for each task function type
        initialized (bool): Flag indicating if instance is initialized
        _isExiting (bool): Flag indicating shutdown state

    Thread Safety:
        Uses RLock for thread-safe singleton instantiation

    Example:
        >>> service = QueueService.getInstance()
        >>> await service.startDelayedScheduler(db)
        >>> service.registerDelayedTaskHandler(
        ...     DelayedTaskFunction.SEND_MESSAGE,
        ...     my_handler_function
        ... )
    """

    _instance: Optional["QueueService"] = None
    _lock = RLock()

    def __new__(cls) -> "QueueService":
        """
        Create or return singleton instance with thread safety.

        Returns:
            The singleton QueueService instance
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        """
        Initialize the QueueService instance with default values, dood!

        This method is called only once per singleton instance. It sets up:
        - Background tasks queue (asyncio.Queue)
        - Delayed actions priority queue (asyncio.PriorityQueue)
        - Task handlers registry
        - Internal state flags

        Note:
            Uses hasattr check to prevent re-initialization of singleton instance.
            All queue operations are async-safe but initialization itself uses
            thread-safe singleton pattern via __new__.
        """
        if not hasattr(self, "initialized"):
            self.db: Optional["DatabaseWrapper"] = None

            self.asyncTasksQueue = asyncio.Queue()
            self.queueLastUpdated = time.time()

            self.delayedActionsQueue = asyncio.PriorityQueue()
            self.tasksHandlers: Dict[DelayedTaskFunction, List[DelayedTaskHandler]] = {}

            self.initialized = True
            logger.info("QueueService initialized, dood!")

    @classmethod
    def getInstance(cls) -> "QueueService":
        """Get singleton instance"""
        return cls()

    async def beginShutdown(self) -> None:
        """
        Initiate graceful shutdown of the queue service, dood!

        Sets the exit flag and schedules a DO_EXIT delayed task to process
        remaining background tasks before shutdown. The task is added with
        skipDB=True to avoid database operations during shutdown.

        This method should be called when the application is shutting down
        to ensure all pending tasks are processed.

        Note:
            The actual shutdown happens when the DO_EXIT task is processed
            by the delayed queue processor.
        """
        await self.addDelayedTask(time.time(), DelayedTaskFunction.DO_EXIT, kwargs={}, skipDB=True)

    async def addBackgroundTask(self, task: asyncio.Task) -> None:
        """
        Add an asyncio task to the background tasks queue, dood!

        If the queue exceeds MAX_QUEUE_LENGTH, the oldest task is processed
        immediately before adding the new one. Updates the queue timestamp
        for age-based processing.

        Args:
            task (asyncio.Task): The asyncio task to add to the queue

        Raises:
            Logs error if queue contains non-Task objects

        Note:
            Queue size is limited by constants.MAX_QUEUE_LENGTH (default: 32)
            Tasks are processed based on queue age (constants.MAX_QUEUE_AGE)
        """
        if self.asyncTasksQueue.qsize() > constants.MAX_QUEUE_LENGTH:
            logger.info("Queue is full, processing oldest task")
            oldTask = await self.asyncTasksQueue.get()
            if not inspect.isawaitable(oldTask):
                logger.info(f"Task {oldTask} is not awaitable, but a {type(oldTask)}")
            else:
                await oldTask
            self.asyncTasksQueue.task_done()

        # logger.info(f"Adding task {type(task)}({task}) to background tasks queue")
        await self.asyncTasksQueue.put(task)
        self.queueLastUpdated = time.time()

    async def processBackgroundTasks(self, forceProcessAll: bool = False) -> None:
        """
        Process all pending background tasks in the queue, dood!

        Tasks are processed when either:
        - forceProcessAll is True (immediate processing)
        - Queue age exceeds MAX_QUEUE_AGE (30 minutes by default)

        Args:
            forceProcessAll (bool, optional): If True, process all tasks immediately
                regardless of queue age. Defaults to False.

        Note:
            - Updates queueLastUpdated to prevent concurrent processing
            - Processes all tasks currently in queue (not new ones added during processing)
            - Logs errors for individual task failures without stopping processing
            - Empty queue returns immediately without processing

        Raises:
            Logs exceptions for task execution errors but continues processing
        """

        if self.asyncTasksQueue.empty():
            return

        if (not forceProcessAll) and (self.queueLastUpdated + constants.MAX_QUEUE_AGE > time.time()):
            return

        if forceProcessAll:
            logger.info("Processing background tasks queue due to forceProcessAll=True")
        else:
            logger.info(f"Processing queue due to age ({constants.MAX_QUEUE_AGE})")

        # TODO: Do it properly
        # Little hack to avoid concurency in processing queue
        self.queueLastUpdated = time.time()
        # TODO: Process only existing elements to avoid endless processing new ones

        try:
            while True:
                task = await self.asyncTasksQueue.get_nowait()
                if not inspect.isawaitable(task):
                    # By some reason all finished tasks magically converts to it's results
                    logger.warning(f"Task {task} is not awaitable, but a {type(task)}")
                else:
                    try:
                        logger.debug(f"Awaiting task {task}...")
                        ret = await task
                        logger.debug(f"Task {task} returned {ret}")
                    except Exception as e:
                        logger.error(f"Error in background task: {e}")
                        logger.exception(e)

                self.asyncTasksQueue.task_done()
        except asyncio.QueueEmpty:
            logger.info("All background tasks were processed")
        except Exception as e:
            logger.error(f"Error in background task processing: {e}")
            logger.exception(e)

    async def _processBackgroundTasksHandler(self, task: DelayedTask) -> None:
        """
        Handler for PROCESS_BACKGROUND_TASKS delayed task type, dood!

        Processes background tasks queue and schedules the next processing
        cycle in 600 seconds (10 minutes). This creates a recurring task
        that ensures background tasks are processed periodically.

        Args:
            task (DelayedTask): The delayed task triggering this handler

        Note:
            - Calls processBackgroundTasks with forceProcessAll=False
            - Schedules next processing with skipDB=True for efficiency
            - Part of the automatic background task processing cycle
        """

        logger.debug(f"Processing background tasks: {task}")
        await self.processBackgroundTasks(forceProcessAll=False)
        # Add next processing cycle
        await self.addDelayedTask(
            time.time() + 600,
            DelayedTaskFunction.PROCESS_BACKGROUND_TASKS,
            kwargs={},
            skipDB=True,
        )

    async def _doExitHandler(self, task: DelayedTask) -> None:
        """
        Handler for DO_EXIT delayed task type during shutdown, dood!

        Processes all remaining background tasks with forceProcessAll=True
        to ensure clean shutdown without losing pending work.

        Args:
            task (DelayedTask): The delayed task triggering this handler

        Note:
            - Called during graceful shutdown initiated by beginShutdown()
            - Forces processing of all background tasks before exit
            - Part of the shutdown sequence
        """

        logger.info("doExit: processing backgroundTask if any...")
        await self.processBackgroundTasks(forceProcessAll=True)

    def registerDelayedTaskHandler(self, function: DelayedTaskFunction, handler: DelayedTaskHandler) -> None:
        """
        Register a handler function for a specific delayed task type, dood!

        Handlers are async functions that process delayed tasks when they
        become due. Multiple handlers can be registered for the same function
        type and will be executed in registration order.

        Args:
            function (DelayedTaskFunction): The task function type to handle
            handler (DelayedTaskHandler): Async callable that processes the task

        Note:
            - Handler signature: async def handler(task: DelayedTask) -> None
            - If function already has handlers, new handler is appended
            - If function is new, creates new handler list with this handler
            - Handlers are called sequentially when task becomes due

        Example:
            >>> async def myHandler(task: DelayedTask) -> None:
            ...     print(f"Processing {task.function}")
            >>> service.registerDelayedTaskHandler(
            ...     DelayedTaskFunction.SEND_MESSAGE,
            ...     myHandler
            ... )
        """
        if function in self.tasksHandlers:
            self.tasksHandlers[function].append(handler)
        else:
            self.tasksHandlers[function] = [handler]

        logger.info(f"Registered handler for {function}: {handler}")

    async def startDelayedScheduler(self, db: "DatabaseWrapper") -> None:
        """
        Initialize and start the delayed task scheduler, dood!

        This method:
        1. Sets up database connection for task persistence
        2. Registers built-in task handlers (PROCESS_BACKGROUND_TASKS, DO_EXIT)
        3. Restores pending tasks from database
        4. Schedules initial background task processing
        5. Starts the delayed queue processor loop

        Args:
            db (DatabaseWrapper): Database connection for task persistence

        Raises:
            Exception: If scheduler is already initialized (db is not None)

        Note:
            - Must be called before adding delayed tasks
            - Restores all pending tasks from database on startup
            - Starts infinite processing loop (blocks until shutdown)
            - Initial background processing scheduled for 600 seconds (10 minutes)

        Example:
            >>> db = DatabaseWrapper(...)
            >>> await queueService.startDelayedScheduler(db)
        """

        if self.db is not None:
            raise Exception("Delayed scheduler is already initialized")

        self.db = db

        self.registerDelayedTaskHandler(
            DelayedTaskFunction.PROCESS_BACKGROUND_TASKS, self._processBackgroundTasksHandler
        )
        self.registerDelayedTaskHandler(DelayedTaskFunction.DO_EXIT, self._doExitHandler)

        tasks = self.db.getPendingDelayedTasks()
        for task in tasks:
            await self.addDelayedTask(
                delayedUntil=float(task["delayed_ts"]),
                function=DelayedTaskFunction(task["function"]),
                kwargs=json.loads(task["kwargs"]),
                taskId=task["id"],
                skipDB=True,
            )
            logger.info(f"Restored delayed task: {task}")

        # Add background tasks processing
        await self.addDelayedTask(
            time.time() + 600, DelayedTaskFunction.PROCESS_BACKGROUND_TASKS, kwargs={}, skipDB=True
        )

        await self._processDelayedQueue()

    async def _processDelayedQueue(self) -> None:
        """
        Main processing loop for the delayed tasks priority queue, dood!

        This infinite loop:
        1. Retrieves tasks from priority queue (ordered by delayedUntil)
        2. Checks if task is due (delayedUntil <= current time)
        3. If not due, re-queues task and sleeps until it's ready
        4. If due, executes all registered handlers for the task function
        5. Updates task status in database as completed
        6. Handles DO_EXIT task to terminate loop gracefully

        The loop continues until:
        - DO_EXIT task is processed (graceful shutdown)
        - RuntimeError with "Event loop is closed" (forced shutdown)

        Note:
            - Tasks are processed in order of delayedUntil
            - Tasks without handlers are delayed by 60 seconds
            - Handler errors are logged but don't stop processing
            - Database updates are skipped if db is None (shouldn't happen)
            - This is a blocking operation that runs until shutdown

        Raises:
            Logs RuntimeError and Exception but continues processing
            Breaks loop on "Event loop is closed" error
        """
        while True:
            try:
                # logger.debug("_pDQ(): Iteration...")
                delayedTask = await self.delayedActionsQueue.get()

                if not isinstance(delayedTask, DelayedTask):
                    self.delayedActionsQueue.task_done()
                    logger.error(
                        f"Got wrong element from delayedActionsQueue: {type(delayedTask).__name__}#{repr(delayedTask)}"
                    )
                    continue

                if delayedTask.delayedUntil > time.time():
                    self.delayedActionsQueue.task_done()
                    await self.delayedActionsQueue.put(delayedTask)
                    # TODO: Add some configured delay, maybe
                    await asyncio.sleep(min(10, delayedTask.delayedUntil - time.time()))
                    continue

                logger.debug(f"Got {delayedTask}...")

                if delayedTask.function == DelayedTaskFunction.DO_EXIT:
                    logger.info("got doExit, starting shutdown process...")

                if delayedTask.function not in self.tasksHandlers:
                    logger.error(f"No handlers for {delayedTask.function} registered, delaying task for 60 seconds...")
                    delayedTask.delayedUntil = time.time() + 60
                    await self.delayedActionsQueue.put(delayedTask)
                else:
                    for handler in self.tasksHandlers[delayedTask.function]:
                        try:
                            await handler(delayedTask)
                        except Exception as e:
                            logger.error(f"Error in handler {handler.__name__}: {e}")

                if self.db is not None:
                    self.db.updateDelayedTask(delayedTask.taskId, True)
                else:
                    logger.error("No database connection, this shouldn't happen")

                self.delayedActionsQueue.task_done()
                if delayedTask.function == DelayedTaskFunction.DO_EXIT:
                    logger.debug("doExit(), exiting...")
                    return

            except RuntimeError as e:
                logger.error(f"Error in delayed task processor: {e}")
                if str(e) == "Event loop is closed":
                    break

            except Exception as e:
                logger.error(f"Error in delayed task processor: {e}")
                logger.exception(e)

    async def addDelayedTask(
        self,
        delayedUntil: float,
        function: DelayedTaskFunction,
        kwargs: Dict[str, Any],
        taskId: Optional[str] = None,
        skipDB: bool = False,
    ) -> None:
        """
        Add a delayed task to be executed at a specific time, dood!

        Creates a DelayedTask and adds it to the priority queue. Optionally
        persists the task to database for recovery after restarts.

        Args:
            delayedUntil (float): Unix timestamp when task should execute
            function (DelayedTaskFunction): Type of task to execute
            kwargs (Dict[str, Any]): Arguments to pass to task handlers
            taskId (Optional[str], optional): Unique task identifier.
                Auto-generated UUID if None. Defaults to None.
            skipDB (bool, optional): If True, don't persist to database.
                Used for internal tasks and during restoration. Defaults to False.

        Raises:
            Exception: If skipDB is False but database connection is None

        Note:
            - Tasks are ordered by delayedUntil in priority queue
            - Database persistence allows task recovery after restart
            - skipDB=True used for: restored tasks, internal tasks, shutdown tasks
            - kwargs are JSON-serialized when stored in database

        Example:
            >>> await service.addDelayedTask(
            ...     delayedUntil=time.time() + 3600,
            ...     function=DelayedTaskFunction.SEND_MESSAGE,
            ...     kwargs={"chat_id": 123, "text": "Reminder!"}
            ... )
        """
        if taskId is None:
            taskId = str(uuid.uuid4())

        task = DelayedTask(taskId, delayedUntil, function, kwargs)
        # logger.debug(f"Adding delayed task: {task}")
        await self.delayedActionsQueue.put(task)
        if not skipDB:
            if self.db is None:
                raise Exception("No database connection")
            self.db.addDelayedTask(
                taskId=taskId,
                function=function,
                kwargs=utils.jsonDumps(kwargs, ensure_ascii=False, default=str),
                delayedTS=int(delayedUntil),
            )

        logger.debug(f"Added delayed task: {task}, skipDB={skipDB}")
