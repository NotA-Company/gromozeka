"""Bot handlers manager for coordinating message processing across multiple handlers.

This module provides the core orchestration layer for the Gromozeka bot's message
processing pipeline. It manages a collection of handlers that process incoming
messages, commands, callbacks, and chat member events in a controlled order with
support for both sequential and parallel execution.

Key components:
    - HandlerParallelism: Enum defining execution modes (SEQUENTIAL/PARALLEL)
    - MessageQueueRecord: Represents a queued message with synchronization primitives
    - ChatProcessingState: Manages message queue and processing state for a chat
    - HandlersManager: Main coordinator that routes messages through handlers

The manager implements a sophisticated queuing system that:
    - Maintains per-chat message queues to ensure ordered processing
    - Supports sequential handlers that wait for previous messages to complete
    - Supports parallel handlers that can process messages concurrently
    - Handles command parsing, permission checking, and routing
    - Manages handler lifecycle and background task execution
    - Provides cleanup of stale chat states and old data

Example:
    manager = HandlersManager(configManager, database, BotProvider.TELEGRAM)
    await manager.initialize(bot)
    await manager.handleNewMessage(ensuredMessage, updateObj)
    await manager.shutdown()
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Coroutine, MutableSet
from enum import IntEnum, auto
from typing import Dict, List, Optional, Set, Tuple

from telegram.ext import ExtBot

import lib.max_bot as libMax
from internal.bot.common.bot import TheBot

# import lib.max_bot.models as maxModels
from internal.bot.common.models import UpdateObjectType
from internal.bot.models import (
    BotProvider,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatTier,
    ChatType,
    CommandCategory,
    CommandHandlerInfoV2,
    CommandPermission,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
)
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.models import MessageCategory
from internal.models import MessageIdType
from internal.services.cache import CacheService
from internal.services.queue_service import DelayedTask, DelayedTaskFunction, QueueService
from internal.services.storage import StorageService
from lib import utils

from .base import BaseBotHandler, HandlerResultStatus
from .common import CommonHandler
from .configure import ConfigureCommandHandler
from .dev_commands import DevCommandsHandler
from .divination import DivinationHandler
from .help_command import CommandHandlerGetterInterface, HelpHandler
from .llm_messages import LLMMessageHandler
from .media import MediaHandler
from .message_preprocessor import MessagePreprocessorHandler
from .react_on_user import ReactOnUserMessageHandler
from .resender import ResenderHandler
from .spam import SpamHandler
from .summarization import SummarizationHandler
from .topic_manager import TopicManagerHandler
from .user_data import UserDataHandler
from .weather import WeatherHandler
from .yandex_search import YandexSearchHandler

logger = logging.getLogger(__name__)


class HandlerParallelism(IntEnum):
    """Enum for handler parallelism options.

    Defines how handlers should be executed relative to other handlers:
    - SEQUENTIAL: Handlers wait for the same step of previous messages to complete
    - PARALLEL: Handlers execute independently without waiting for previous messages
    """

    SEQUENTIAL = auto()
    """Handler waits for the same step of previous messages to complete."""

    PARALLEL = auto()
    """Handler executes independently without waiting for previous messages."""


HandlerTuple = Tuple[BaseBotHandler, HandlerParallelism]


class MessageQueueRecord:
    """Represents a message queue record with synchronization primitives.

    This class encapsulates a message being processed along with the original
    update object and synchronization primitives for coordinating handler
    execution across multiple messages in the same chat.

    Attributes:
        message: The normalized message object to be processed
        updateObj: The original update object from the platform
        lock: Async lock for thread-safe operations on this record
        handled: Event that is set when the message has been fully processed
        step: Current processing step index (which handler is processing)
        _id: Cached unique identifier for this message record
        _stateId: Cached state identifier for the chat/thread
    """

    __slots__ = ("message", "updateObj", "lock", "handled", "step", "_id", "_stateId")

    def __init__(self, message: EnsuredMessage, updateObj: UpdateObjectType, stateId: Optional[str] = None) -> None:
        """Initialize a message queue record.

        Args:
            message: The normalized message object to be processed
            updateObj: The original update object from the platform
            stateId: Optional pre-computed state identifier for the chat/thread
        """
        self.message = message
        self.updateObj = updateObj
        self.lock: asyncio.Lock = asyncio.Lock()
        self.handled: asyncio.Event = asyncio.Event()
        self.step: int = -1
        self._id: Optional[str] = None
        self._stateId = stateId

    def getId(self, forceRecalc: bool = False) -> str:
        """Get unique identifier for this message record.

        The ID is composed of the recipient chat ID and message ID.

        Args:
            forceRecalc: If True, recalculate the ID even if already cached

        Returns:
            Unique identifier string in format "chatId:messageId"
        """
        if self._id is None or forceRecalc:
            self._id = f"{self.message.recipient.id}:{self.message.messageId}"

        return self._id

    def getStateId(self, forceRecalc: bool = False) -> str:
        """Get state identifier for the chat/thread this message belongs to.

        The state ID is composed of the recipient chat ID and thread ID.

        Args:
            forceRecalc: If True, recalculate the state ID even if already cached

        Returns:
            State identifier string in format "chatId:threadId"
        """
        if self._stateId is None or forceRecalc:
            self._stateId = f"{self.message.recipient.id}:{self.message.threadId}"

        return self._stateId

    def __str__(self) -> str:
        """Return string representation of the message queue record.

        Returns:
            String representation showing message, update object, and state
        """
        return (
            f"MessageQueueRecord({self.message}, {self.updateObj}, <lock>, "
            f"{self.handled}, {self.step}, {self._id}, {self._stateId})"
        )

    async def awaitStepDone(self, step: int) -> None:
        """Wait until a specific processing step is completed.

        This method blocks until either the message is fully handled or
        the processing reaches the specified step index.

        Args:
            step: The step index to wait for (0-based handler index)
        """
        while not self.handled.is_set() and self.step < step:
            await asyncio.sleep(0.1)


class ChatProcessingState:
    """Represents the processing state for a single chat or thread.

    This class manages the message queue and processing state for a specific
    chat or thread. It ensures messages are processed in order and provides
    synchronization primitives for coordinating handler execution.

    Attributes:
        chatId: The unique identifier for the chat
        threadId: Optional thread identifier for threaded conversations
        queue: Deque of MessageQueueRecord objects awaiting processing
        lock: Async lock for thread-safe queue operations
        shutdownEvent: Event that is set when the chat state is shutting down
        _queueKey: Cached unique key for this chat/thread state
        _updateAt: Timestamp of the last state update (for cleanup)
    """

    __slots__ = ("chatId", "threadId", "queue", "lock", "shutdownEvent", "_queueKey", "_updateAt")

    def __init__(self, chatId: int, threadId: Optional[int] = None, queueKey: Optional[str] = None) -> None:
        """Initialize a chat processing state.

        Args:
            chatId: The unique identifier for the chat
            threadId: Optional thread identifier for threaded conversations
            queueKey: Optional pre-computed queue key for this state
        """
        self.chatId: int = chatId
        self.threadId: Optional[int] = threadId
        self.queue = deque[MessageQueueRecord]()
        self.lock = asyncio.Lock()
        self.shutdownEvent = asyncio.Event()
        self._queueKey: Optional[str] = queueKey
        self._updateAt: float = time.time()

    def getUpdatedAt(self) -> float:
        """Get the timestamp of the last state update.

        Returns:
            Unix timestamp of the last update
        """
        return self._updateAt

    def getQueueKey(self, forceRecalc: bool = False) -> str:
        """Get the unique queue key for this chat/thread state.

        Args:
            forceRecalc: If True, recalculate the key even if already cached

        Returns:
            Queue key string in format "chatId:threadId"
        """
        if self._queueKey is None or forceRecalc:
            self._queueKey = f"{self.chatId}:{self.threadId}"

        return self._queueKey

    async def addMessage(self, message: EnsuredMessage, updateObj: UpdateObjectType) -> MessageQueueRecord:
        """Add a message to the processing queue.

        Creates a new MessageQueueRecord and appends it to the queue.
        Updates the last update timestamp.

        Args:
            message: The normalized message to add to the queue
            updateObj: The original update object from the platform

        Returns:
            The created MessageQueueRecord

        Raises:
            RuntimeError: If the chat state has been shut down
        """
        if self.shutdownEvent.is_set():
            raise RuntimeError("Chat processing is shut down")
        record = MessageQueueRecord(message, updateObj, stateId=self.getQueueKey())
        async with self.lock:
            self._updateAt = time.time()
            self.queue.append(record)
        return record

    async def messageProcessed(self, message: MessageQueueRecord) -> None:
        """Mark a message as processed and remove it from the queue.

        Waits for all previous messages to be processed first, then removes
        the specified message from the front of the queue. Updates the last
        update timestamp.

        Args:
            message: The message record to mark as processed

        Raises:
            ValueError: If the message is not found in the queue
            RuntimeError: If a race condition is detected
        """
        if message not in self.queue:
            raise ValueError(f"Record {message} not found in queue {self.getQueueKey()}")

        messageId = message.getId()

        while self.queue and self.queue[0].getId() != messageId:
            # Wait for previous messages to be processed and removed
            await asyncio.sleep(0.1)

        async with self.lock:
            self._updateAt = time.time()
            if self.queue[0].getId() != messageId:
                raise RuntimeError(f"Race detected: record {message} not found in queue {self.getQueueKey()}")
            self.queue.popleft()

    async def getPreviousMessage(self, message: MessageQueueRecord) -> Optional[MessageQueueRecord]:
        """Get the previous message in the queue before the specified message.

        Args:
            message: The message to find the predecessor of

        Returns:
            The previous MessageQueueRecord, or None if the message is first

        Raises:
            ValueError: If the message is not found in the queue
        """
        messageId = message.getId()
        previousMessage: Optional[MessageQueueRecord] = None
        async with self.lock:
            for record in self.queue:
                if record.getId() == messageId:
                    return previousMessage
                previousMessage = record

        raise ValueError(f"Record {message} not found in queue {self.getQueueKey()}")


class HandlersManager(CommandHandlerGetterInterface):
    """Manages and coordinates multiple bot handlers for message processing.

    This class is the central orchestrator for the Gromozeka bot's message
    processing pipeline. It manages a collection of handlers that process
    incoming messages, commands, callbacks, and chat member events in a
    controlled order with support for both sequential and parallel execution.

    The manager implements a sophisticated queuing system that:
        - Maintains per-chat message queues to ensure ordered processing
        - Supports sequential handlers that wait for previous messages to complete
        - Supports parallel handlers that can process messages concurrently
        - Handles command parsing, permission checking, and routing
        - Manages handler lifecycle and background task execution
        - Provides cleanup of stale chat states and old data

    Attributes:
        configManager: Configuration manager instance for accessing bot settings
        db: Database wrapper for data persistence operations
        botProvider: Bot provider type (TELEGRAM or MAX)
        handlerTimeout: Default timeout for handler execution in seconds
        _commands: Cached dictionary mapping command names to handler info
        cache: Cache service for storing chat settings and user data
        storage: Storage service for file operations
        queueService: Queue service for delayed task execution
        maxTasks: Maximum number of concurrent handler tasks
        maxTasksPerChat: Maximum number of queued messages per chat
        handlers: List of (handler, parallelism) tuples in execution order
        chatStates: Dictionary mapping queue keys to ChatProcessingState objects
        handlerTasks: Set of active handler tasks for tracking
        stateLock: Global lock for queue management operations
        _shutdownEvent: Event set when the manager is shutting down
    """

    def __init__(self, *, configManager: ConfigManager, database: Database, botProvider: BotProvider) -> None:
        """Initialize the handlers manager with required services.

        Initializes all core services, sets up default chat settings, configures
        handler limits, and builds the handler pipeline. Handlers are registered
        in a specific order to ensure proper message processing flow.

        Args:
            configManager: Configuration manager instance
            database: Database wrapper for data persistence
            botProvider: Bot provider type (TELEGRAM or MAX)
        """
        self.configManager = configManager
        self.db = database
        self.botProvider: BotProvider = botProvider
        self.handlerTimeout = 60 * 30

        # Map of command name -> CommandHandlerInfo
        self._commands: Dict[str, CommandHandlerInfoV2] = {}

        self.cache = CacheService.getInstance()
        self.storage = StorageService.getInstance()
        self.storage.injectConfig(self.configManager)

        self.queueService = QueueService.getInstance()
        # Initialize default Chat Settings
        botConfig = configManager.getBotConfig()
        defaultSettings: ChatSettingsDict = {k: ChatSettingsValue("") for k in ChatSettingsKey}
        defaultSettings.update(
            {
                ChatSettingsKey(k): ChatSettingsValue(v)
                for k, v in botConfig.get("defaults", {}).items()
                if k in ChatSettingsKey
            }
        )
        self.cache.setDefaultChatSettings(None, defaultSettings)

        for chatType in ChatType:
            self.cache.setDefaultChatSettings(
                chatType,
                {
                    ChatSettingsKey(k): ChatSettingsValue(v)
                    for k, v in botConfig.get(f"{chatType.value}-defaults", {}).items()
                    if k in ChatSettingsKey
                },
            )

        tierDefaultsDict = botConfig.get("tier-defaults", {})
        for chatTier in ChatTier:
            self.cache.setDefaultChatSettings(
                f"tier-{chatTier}",
                {
                    ChatSettingsKey(k): ChatSettingsValue(v)
                    for k, v in tierDefaultsDict.get(chatTier, {}).items()
                    if k in ChatSettingsKey
                },
            )

        self.maxTasks = botConfig.get("max-tasks", 1024)
        self.maxTasksPerChat = botConfig.get("max-tasks-per-chat", 512)

        # Initialize handlers
        self.handlers: List[HandlerTuple] = [
            # # Should be first to save message to history + process media.
            # Should be before other handlers to ensure message saving + media processing
            (
                MessagePreprocessorHandler(configManager=configManager, database=database, botProvider=botProvider),
                HandlerParallelism.SEQUENTIAL,
            ),
            # Should be first (but after Preprocessor) to check for spam before other handlers
            # and do not allow SPAM to be processed by other handlers
            (
                SpamHandler(configManager=configManager, database=database, botProvider=botProvider),
                HandlerParallelism.SEQUENTIAL,
            ),
            # # Next - Handlers, which uses `newMessageHandler` for setting settings
            # Should be before MessagePreprocessorHandler to not save configuration answers
            (
                ConfigureCommandHandler(configManager=configManager, database=database, botProvider=botProvider),
                HandlerParallelism.PARALLEL,
            ),
            (
                SummarizationHandler(configManager=configManager, database=database, botProvider=botProvider),
                HandlerParallelism.PARALLEL,
            ),
            (
                UserDataHandler(configManager=configManager, database=database, botProvider=botProvider),
                HandlerParallelism.PARALLEL,
            ),
            # # Fourth - all other handlers
            (
                DevCommandsHandler(configManager=configManager, database=database, botProvider=botProvider),
                HandlerParallelism.PARALLEL,
            ),
            (
                MediaHandler(configManager=configManager, database=database, botProvider=botProvider),
                HandlerParallelism.PARALLEL,
            ),
            (
                CommonHandler(configManager=configManager, database=database, botProvider=botProvider),
                HandlerParallelism.PARALLEL,
            ),
            # Special case - help command require all command handlers information
            (
                HelpHandler(
                    configManager=configManager, database=database, botProvider=botProvider, commandsGetter=self
                ),
                HandlerParallelism.PARALLEL,
            ),
        ]

        if self.botProvider == BotProvider.TELEGRAM:
            self.handlers.extend(
                [
                    (
                        ReactOnUserMessageHandler(
                            configManager=configManager, database=database, botProvider=botProvider
                        ),
                        HandlerParallelism.PARALLEL,
                    ),
                    (
                        TopicManagerHandler(configManager=configManager, database=database, botProvider=botProvider),
                        HandlerParallelism.PARALLEL,
                    ),
                ]
            )

        # Add WeatherHandler only if OpenWeatherMap integration is enabled
        if self.configManager.getOpenWeatherMapConfig().get("enabled", False):
            self.handlers.append(
                (
                    WeatherHandler(configManager=configManager, database=database, botProvider=botProvider),
                    HandlerParallelism.PARALLEL,
                )
            )
        if self.configManager.getYandexSearchConfig().get("enabled", False):
            self.handlers.append(
                (
                    YandexSearchHandler(configManager=configManager, database=database, botProvider=botProvider),
                    HandlerParallelism.PARALLEL,
                )
            )
        if self.configManager.get("resender", {}).get("enabled", False):
            self.handlers.append(
                (
                    ResenderHandler(configManager=configManager, database=database, botProvider=botProvider),
                    HandlerParallelism.PARALLEL,
                )
            )
        if self.configManager.get("divination", {}).get("enabled", False):
            self.handlers.append(
                (
                    DivinationHandler(configManager=configManager, database=database, botProvider=botProvider),
                    HandlerParallelism.PARALLEL,
                )
            )

        # Load custom handlers from config
        # We have to import module_loader here to avoid circular imports
        from .module_loader import CustomHandlerLoader

        customLoader = CustomHandlerLoader(configManager=configManager, database=database, botProvider=botProvider)
        customHandlers = customLoader.loadAll()
        if customHandlers:
            logger.info(f"Loaded {len(customHandlers)} custom handler(s)")
            self.handlers.extend(customHandlers)

        self.handlers.append(
            # Should be last messageHandler as it can handle any message
            (
                LLMMessageHandler(configManager=configManager, database=database, botProvider=botProvider),
                HandlerParallelism.SEQUENTIAL,
            )
        )

        self.chatStates: Dict[str, ChatProcessingState] = {}
        self.handlerTasks: MutableSet[asyncio.Task] = set[asyncio.Task]()
        self.stateLock = asyncio.Lock()
        """Global Lock for Queue management (checking, creating, deleting)"""

        self.queueService.registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB, self._dtCronJob)
        self.queueService.registerDelayedTaskHandler(DelayedTaskFunction.DO_EXIT, self._dtOnExit)
        self._shutdownEvent = asyncio.Event()

    async def _dtOnExit(self, task: DelayedTask) -> None:
        """Handle application exit by cleaning up old database cache entries.

        Removes cache entries older than 90 days from the database.

        Args:
            task: DelayedTask instance containing task execution context

        Returns:
            None
        """

        await self._cleanupOldData()

    async def _dtCronJob(self, task: DelayedTask) -> None:
        """Periodic cron job to clean up stalled chat states.

        Runs every 30 minutes to identify and remove chat states that have been
        inactive for more than 1 hour with empty message queues. This prevents
        memory leaks from abandoned chat sessions.

        Args:
            task: DelayedTask instance containing task execution context

        Returns:
            None
        """

        nowTime = time.time()
        nowTimeStruct = time.gmtime(nowTime)
        nowMinutes = nowTimeStruct.tm_min
        nowHour = nowTimeStruct.tm_hour
        nowWDay = nowTimeStruct.tm_wday

        if nowMinutes == 0 and nowHour == 0 and nowWDay == 0:
            # Once a week, cleanup old data
            await self._cleanupOldData()

        # Every 30 minutes drop unused chat states
        if nowMinutes % 30 != 0:
            return

        logger.debug("Running cleanup for obsolete chat states...")
        async with self.stateLock:
            stalledStateNames: List[str] = []
            for k, v in self.chatStates.items():
                if len(v.queue) == 0 and v.getUpdatedAt() < nowTime - 60 * 60:
                    logger.debug(f"Found stalled chat state: {k}")
                    stalledStateNames.append(k)
                    v.shutdownEvent.set()

            for stateName in stalledStateNames:
                self.chatStates.pop(stateName)

    async def _cleanupOldData(self) -> None:
        """Clean up old data from the database.

        Removes cache entries older than 90 days and completed delayed tasks
        older than 30 days to prevent database bloat.

        Returns:
            None
        """
        # Drop cache entries, that more than 3 month old
        await self.db.cache.clearOldCacheEntries(ttl=60 * 60 * 24 * 90)
        # Also drop completed tasks older than a month
        await self.db.delayedTasks.cleanupOldCompletedDelayedTasks(ttl=60 * 60 * 24 * 30)

    async def initialize(self, bot: ExtBot | libMax.MaxBotClient) -> None:
        """Initialize the handlers manager by injecting bot instance into all registered handlers.

        Creates a TheBot wrapper with the provided bot client, validates that the bot type
        matches the configured bot provider, enriches bot owner information with user IDs
        from the database, and injects the bot instance into all registered handlers.

        Args:
            bot: Bot client instance (ExtBot for Telegram or MaxBotClient for Max Messenger)

        Returns:
            None

        Raises:
            ValueError: If bot type doesn't match the configured bot provider
        """
        await self.cache.injectDatabase(self.db)

        theBot: Optional[TheBot] = None
        if self.botProvider == BotProvider.TELEGRAM and isinstance(bot, ExtBot):
            theBot = TheBot(botProvider=self.botProvider, config=self.configManager.getBotConfig(), tgBot=bot)
        elif self.botProvider == BotProvider.MAX and isinstance(bot, libMax.MaxBotClient):
            theBot = TheBot(botProvider=self.botProvider, config=self.configManager.getBotConfig(), maxBot=bot)

        if theBot is None:
            raise ValueError("Unexpected bot class")

        # For each botOwner username try to add it's userId as well
        for botOwner in theBot.botOwnersUsername:
            for userId in await self.db.chatUsers.getUserIdByUserName(botOwner.lower()):
                theBot.botOwnersId.add(userId)

        for handler, _ in self.handlers:
            handler.injectBot(theBot)

    async def shutdown(self) -> None:
        """Shutdown the HandlersManager.

        This method will await for all running tasks and drop queues.
        """
        logger.info("Shutting down HandlersManager...")
        self._shutdownEvent.set()
        logger.info("Awaiting for queue handlers...")
        for chatState in self.chatStates.values():
            async with chatState.lock:
                chatState.shutdownEvent.set()

        await asyncio.gather(*self.handlerTasks)

    async def runAsync(self, func: Coroutine, timeout: Optional[float] = None) -> asyncio.Task:
        """Run background tasks with optional timeout.

        Args:
            func: Coroutine to run as a background task
            timeout: Optional timeout in seconds for the coroutine

        Returns:
            asyncio.Task: The created task

        Raises:
            asyncio.TimeoutError: If the coroutine execution exceeds the timeout
        """
        while len(self.handlerTasks) >= self.maxTasks:
            await asyncio.sleep(0.5)
        if timeout is not None and timeout > 0:
            func = asyncio.wait_for(func, timeout=timeout)
        task = asyncio.create_task(func)
        self.handlerTasks.add(task)
        task.add_done_callback(self.handlerTasks.discard)
        return task

    async def addMessageToChatQueue(
        self, message: EnsuredMessage, updateObj: UpdateObjectType
    ) -> Optional[MessageQueueRecord]:
        """Add a message to the chat's processing queue.

        Creates a new chat state if one doesn't exist, checks if the queue is full,
        and adds the message to the queue for processing.

        Args:
            message: The ensured message to add to the queue
            updateObj: The original update object from the platform

        Returns:
            MessageQueueRecord if the message was successfully added to the queue,
            None if the queue is full
        """
        chatId = message.recipient.id
        threadId = message.threadId
        key = f"{chatId}:{threadId}"
        async with self.stateLock:
            # We have to do everything inside of lock to ensure, that nobody will delete\create queue in process
            # I.e. to avoid race
            isNewQueue = key not in self.chatStates

            if isNewQueue:
                self.chatStates[key] = ChatProcessingState(chatId=chatId, threadId=threadId, queueKey=key)

            async with self.chatStates[key].lock:
                if len(self.chatStates[key].queue) >= self.maxTasksPerChat:
                    logger.warning(f"Queue for chat {key} is full, skipping message {message}")
                    return None

            return await self.chatStates[key].addMessage(message, updateObj)

    def getCommandHandlersDict(self, useCache: bool = True) -> Dict[str, CommandHandlerInfoV2]:
        """Get dictionary of all available command handlers.

        Args:
            useCache: If True, return cached commands; if False, rebuild cache

        Returns:
            Dictionary mapping command names to CommandHandlerInfo objects
        """
        # logger.debug(f"gCHD(),p1, commands: {self._commands}")
        if useCache and self._commands:
            return self._commands

        ret: Dict[str, CommandHandlerInfoV2] = {}
        for handler, _ in self.handlers:
            for cmdHandlerInfo in handler.getCommandHandlersV2():
                ret.update({cmd.lower(): cmdHandlerInfo for cmd in cmdHandlerInfo.commands})

        self._commands = ret

        logger.debug(f"Found commands: {self._commands.keys()}")
        return self._commands

    async def parseCommand(self, ensuredMessage: EnsuredMessage) -> Optional[Tuple[str, str]]:
        """Parse message to extract command name and arguments.

        Args:
            ensuredMessage: Message to parse for commands

        Returns:
            Tuple of (command, args) if message contains command, None otherwise
        """
        if not self.handlers:
            # No handlers, no command
            logger.error("No handlers initialized, cannot parse command")
            return None

        messageText = ensuredMessage.messageText
        if not messageText:
            return None
        messageText = messageText.strip()
        if messageText.startswith("/"):
            splittedText = messageText[1:].split(" ", 1)
            command = splittedText[0]
            args = splittedText[1] if len(splittedText) > 1 else ""

            # Check if bot username provided in command and check if it is our username
            splittedCommand = command.split("@")
            command = splittedCommand[0]
            if len(splittedCommand) > 1:
                myUsername = await self.handlers[0][0].getBotUserName()
                if not myUsername or myUsername.lower() != splittedCommand[1].lower():
                    # TODO: Should we somehow indicate, that it is command but for someone else?
                    logger.debug(
                        f"Received command for someone else: {command}, bot: {splittedCommand[1]}, args: {args}"
                    )
                    return None

            logger.debug(f"Received command: {command}, args: {args}")
            return command, args

        return None

    async def handleCommand(self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType) -> Optional[bool]:
        """Handle command execution with permission checking.

        Args:
            ensuredMessage: Message containing the command
            updateObj: Original update object from the platform

        Returns:
            None: Not a command
            True: Command handled successfully
            False: Command not handled due to permissions or errors
        """

        commandTuple = await self.parseCommand(ensuredMessage)
        if commandTuple is None:
            return None

        command, args = commandTuple
        commands = self.getCommandHandlersDict()
        commandLower = command.lower()
        if commandLower not in commands:
            logger.debug(f"Unknown command: {command}")
            # TODO: Check if we need to delete unknown commands
            return None

        handlerInfo = commands[commandLower]
        if handlerInfo.boundHandler is None:
            raise ValueError(f"boundHandler is undefined for {handlerInfo}")

        handlerObj = handlerInfo.boundHandler.__self__
        if not isinstance(handlerObj, BaseBotHandler):
            raise RuntimeError(f"Command handler type is {type(handlerObj)} instead of BaseBotHandler")

        logger.debug(f"Got {command}:{args} command: {updateObj}")

        # Check permissions if needed

        isBotOwner = await handlerObj.isAdmin(ensuredMessage.sender, None, allowBotOwners=True)
        chatSettings = await handlerObj.getChatSettings(ensuredMessage.recipient.id)
        chatType = ensuredMessage.recipient.chatType

        canProcess = (
            CommandPermission.DEFAULT in handlerInfo.availableFor
            or (CommandPermission.PRIVATE in handlerInfo.availableFor and chatType == ChatType.PRIVATE)
            or (CommandPermission.GROUP in handlerInfo.availableFor and chatType == ChatType.GROUP)
            or (CommandPermission.BOT_OWNER in handlerInfo.availableFor and isBotOwner)
            or (
                CommandPermission.ADMIN in handlerInfo.availableFor
                and chatType == ChatType.GROUP
                and await handlerObj.isAdmin(ensuredMessage.sender, ensuredMessage.recipient)
            )
        )

        if not canProcess:
            logger.warning(
                f"Command `{command}` is not allowed in "
                f"chat {ensuredMessage.recipient} for "
                f"user {ensuredMessage.sender}. Needed permissions: {handlerInfo.availableFor}"
            )
            if chatSettings[ChatSettingsKey.DELETE_DENIED_COMMANDS].toBool():
                try:
                    await handlerObj.deleteMessage(ensuredMessage)
                except Exception as e:
                    logger.error(f"Error while deleting message: {e}")
            return False

        isAdmin = await handlerObj.isAdmin(ensuredMessage.sender, ensuredMessage.recipient)
        match handlerInfo.category:
            case CommandCategory.UNSPECIFIED:
                # No category specified, deny by default
                canProcess = False
            case CommandCategory.PRIVATE:
                canProcess = chatType == ChatType.PRIVATE
            case CommandCategory.ADMIN | CommandCategory.SPAM_ADMIN:
                canProcess = isAdmin
            case CommandCategory.TOOLS:
                # BotOwners could bypass TollsAllowed check
                canProcess = chatSettings[ChatSettingsKey.ALLOW_TOOLS_COMMANDS].toBool() or isBotOwner
            case CommandCategory.SPAM:
                canProcess = isAdmin or chatSettings[ChatSettingsKey.ALLOW_USER_SPAM_COMMAND].toBool()
            case CommandCategory.TECHNICAL:
                # Actually technical command shouldn't present in group chats except of debug purposes, but whatever
                canProcess = isAdmin
            case _:
                logger.error(f"Unhandled command category: {handlerInfo.category}, deny")
                canProcess = False
                pass

        if not canProcess:
            logger.warning(
                f"Command `{str(command)}` is not allowed in "
                f"chat {ensuredMessage.recipient} for "
                f"user {ensuredMessage.sender}. Command category: {handlerInfo.category}."
            )
            if chatSettings[ChatSettingsKey.DELETE_DENIED_COMMANDS].toBool():
                try:
                    await handlerObj.deleteMessage(ensuredMessage)
                except Exception as e:
                    logger.error(f"Error while deleting message: {e}")
            return False

        # Store command message in database
        await handlerObj.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        # Actually handle command
        try:
            if handlerInfo.typingAction is not None:
                async with await handlerObj.startTyping(
                    ensuredMessage, action=handlerInfo.typingAction
                ) as typingManager:
                    await handlerInfo.boundHandler(ensuredMessage, command, args, updateObj, typingManager)
            else:
                await handlerInfo.boundHandler(ensuredMessage, command, args, updateObj, None)

            return True
        except Exception as e:
            logger.error(f"Error while handling command {command}: {e}")
            logger.exception(e)
            if handlerInfo.replyErrorOnException:
                await handlerObj.sendMessage(
                    ensuredMessage,
                    messageText=f"Error while handling command:\n```\n{e}\n```",
                    messageCategory=MessageCategory.BOT_ERROR,
                )
            return False

    async def handleNewMessage(self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType) -> None:
        """Handle new message by routing through handlers in order.

        Args:
            ensuredMessage: Normalized message object
            updateObj: Original update object from the platform
        """
        messageRec = await self.addMessageToChatQueue(ensuredMessage, updateObj)
        if messageRec is not None:
            # Run message processing asynchronously; task is tracked by runAsync
            await self.runAsync(self._processMessageRec(messageRec))

    async def _processMessageRec(self, messageRec: MessageQueueRecord) -> None:
        """Process a queued message record through command and handler pipelines.

        Retrieves the chat state for the record, attempts to handle the message as
        a command first, and if no command matches, iterates through all registered
        handlers in order. Sequential handlers wait for the same step of the
        previous message to finish before proceeding. Stops early when a handler
        returns a final status. Always marks the record as handled and notifies the
        chat state upon completion, even if an exception occurs.

        Args:
            messageRec: The queued message record containing the normalized message,
                update object, and synchronization primitives for step tracking.

        Returns:
            None
        """
        async with self.stateLock:
            chatState = self.chatStates.get(messageRec.getStateId(), None)
            if chatState is None:
                logger.error(f"Chat state not found for message {messageRec}")
                return

        resultSet: Set[HandlerResultStatus] = set[HandlerResultStatus]()

        try:
            ensuredMessage = messageRec.message
            updateObj = messageRec.updateObj
            previousRec = await chatState.getPreviousMessage(messageRec)
            ensuredMessage.setUserData(
                await self.cache.getChatUserData(chatId=ensuredMessage.recipient.id, userId=ensuredMessage.sender.id)
            )

            commandRet = await asyncio.wait_for(
                self.handleCommand(ensuredMessage, updateObj),
                timeout=self.handlerTimeout,
            )
            if commandRet is not None:
                logger.debug(f"Handled as command with result: {commandRet}")
                return

            ret: HandlerResultStatus = HandlerResultStatus.SKIPPED
            for stepIndex, (handler, parallelism) in enumerate(self.handlers):
                match parallelism:
                    case HandlerParallelism.PARALLEL:
                        pass
                    case HandlerParallelism.SEQUENTIAL:
                        if previousRec is not None:
                            await previousRec.awaitStepDone(stepIndex)
                    case _:
                        raise ValueError(f"Unknown parallelism: {parallelism}")

                ret = await asyncio.wait_for(
                    handler.newMessageHandler(ensuredMessage, updateObj),
                    timeout=self.handlerTimeout,
                )
                messageRec.step = stepIndex
                resultSet.add(ret)
                if ret.needLogs():
                    logger.debug(f"Handler {type(handler).__name__} returned {ret.value}")
                if ret.isFinalState():
                    break

        except Exception as e:
            logger.error(
                f"Error while processing message {messageRec.message.sender}#{messageRec.message.recipient}: {e}"
            )
            logger.exception(e)

        finally:
            logger.debug(
                f"Handled message {messageRec.message.sender}#{messageRec.message.recipient}: "
                f"{messageRec.message.messageText[:50]}... "
                f"(resultSet: {resultSet})"
            )

            messageRec.handled.set()
            await chatState.messageProcessed(messageRec)

    async def handleCallback(
        self,
        ensuredMessage: EnsuredMessage,
        data: utils.PayloadDict,
        user: MessageSender,
        updateObj: UpdateObjectType,
    ) -> None:
        """Handle callback query from inline keyboard buttons.

        This is a public wrapper that runs the callback handler asynchronously
        with a timeout. The actual processing is delegated to _handleCallback.

        Args:
            ensuredMessage: Message associated with the callback
            data: Callback data payload
            user: User who triggered the callback
            updateObj: Original update object from the platform

        Returns:
            None
        """
        await self.runAsync(
            self._handleCallback(ensuredMessage, data, user, updateObj),
            timeout=self.handlerTimeout,
        )

    async def _handleCallback(
        self,
        ensuredMessage: EnsuredMessage,
        data: utils.PayloadDict,
        user: MessageSender,
        updateObj: UpdateObjectType,
    ) -> None:
        """Handle callback query from inline keyboard buttons.

        Args:
            ensuredMessage: Message associated with the callback
            data: Callback data payload
            user: User who triggered the callback
            updateObj: Original update object from the platform
        """

        retSet: Set[HandlerResultStatus] = set()
        for handler, _ in self.handlers:
            ret = await handler.callbackHandler(
                ensuredMessage=ensuredMessage, data=data, user=user, updateObj=updateObj
            )
            retSet.add(ret)
            if ret.needLogs():
                logger.debug(f"Handler {type(handler).__name__} returned {ret.value}")
            if ret.isFinalState():
                break

        logger.debug(f"Handled CallbackQuery, resultsSet: {retSet}")

    async def handleNewChatMember(
        self,
        targetChat: MessageRecipient,
        messageId: Optional[MessageIdType],
        newMember: MessageSender,
        updateObj: UpdateObjectType,
    ) -> None:
        """Handle new chat member events.

        This is a public wrapper that runs the new chat member handler asynchronously
        with a timeout. The actual processing is delegated to _handleNewChatMember.

        Args:
            targetChat: Chat where the new member joined
            messageId: Message ID associated with the join event, if available
            newMember: User who joined the chat
            updateObj: Original update object from the platform

        Returns:
            None
        """
        await self.runAsync(
            self._handleNewChatMember(targetChat, messageId, newMember, updateObj),
            timeout=self.handlerTimeout,
        )

    async def _handleNewChatMember(
        self,
        targetChat: MessageRecipient,
        messageId: Optional[MessageIdType],
        newMember: MessageSender,
        updateObj: UpdateObjectType,
    ) -> None:
        """Handle new chat member events.

        Iterates through all registered handlers and calls their newChatMemberHandler
        method. Stops early if a handler returns a final status.

        Args:
            targetChat: Chat where the new member joined
            messageId: Message ID associated with the join event, if available
            newMember: User who joined the chat
            updateObj: Original update object from the platform

        Returns:
            None
        """
        retSet: Set[HandlerResultStatus] = set()
        for handler, _ in self.handlers:
            ret = await handler.newChatMemberHandler(
                targetChat=targetChat,
                messageId=messageId,
                newMember=newMember,
                updateObj=updateObj,
            )
            retSet.add(ret)
            if ret.needLogs():
                logger.debug(f"Handler {type(handler).__name__} returned {ret.value}")
            if ret.isFinalState():
                break

        logger.debug(f"Handled New Chat Member {newMember} -> {targetChat}, resultsSet: {retSet}")

    async def handleLeftChatMember(
        self,
        targetChat: MessageRecipient,
        messageId: Optional[MessageIdType],
        leftMember: MessageSender,
        updateObj: UpdateObjectType,
    ) -> None:
        """Handle left chat member events.

        This is a public wrapper that runs the left chat member handler asynchronously
        with a timeout. The actual processing is delegated to _handleLeftChatMember.

        Args:
            targetChat: Chat where the member left
            messageId: Message ID associated with the leave event, if available
            leftMember: User who left the chat
            updateObj: Original update object from the platform

        Returns:
            None
        """
        await self.runAsync(
            self._handleLeftChatMember(targetChat, messageId, leftMember, updateObj),
            timeout=self.handlerTimeout,
        )

    async def _handleLeftChatMember(
        self,
        targetChat: MessageRecipient,
        messageId: Optional[MessageIdType],
        leftMember: MessageSender,
        updateObj: UpdateObjectType,
    ) -> None:
        """Handle left chat member events.

        Iterates through all registered handlers and calls their leftChatMemberHandler
        method. Stops early if a handler returns a final status.

        Args:
            targetChat: Chat where the member left
            messageId: Message ID associated with the leave event, if available
            leftMember: User who left the chat
            updateObj: Original update object from the platform

        Returns:
            None
        """
        retSet: Set[HandlerResultStatus] = set()
        for handler, _ in self.handlers:
            ret = await handler.leftChatMemberHandler(
                targetChat=targetChat,
                messageId=messageId,
                leftMember=leftMember,
                updateObj=updateObj,
            )
            retSet.add(ret)
            if ret.needLogs():
                logger.debug(f"Handler {type(handler).__name__} returned {ret.value}")
            if ret.isFinalState():
                break

        logger.debug(f"Handled Left Chat Member {leftMember} -> {targetChat}, resultsSet: {retSet}")
