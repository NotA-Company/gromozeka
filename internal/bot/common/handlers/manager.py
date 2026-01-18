"""
Bot handlers manager for coordinating message processing across multiple handlers.
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
from internal.database.models import MessageCategory
from internal.database.wrapper import DatabaseWrapper
from internal.models import MessageIdType
from internal.services.cache import CacheService
from internal.services.queue_service import DelayedTask, DelayedTaskFunction, QueueService
from internal.services.storage import StorageService
from lib import utils
from lib.ai import LLMManager

from .base import BaseBotHandler, HandlerResultStatus
from .common import CommonHandler
from .configure import ConfigureCommandHandler
from .dev_commands import DevCommandsHandler
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
    """
    Enum for handler parallelism options.
    """

    SEQUENTIAL = auto()
    PARALLEL = auto()


HandlerTuple = Tuple[BaseBotHandler, HandlerParallelism]


class MessageQueueRecord:
    """
    Represents a message queue record with a message and a semaphore.
    """

    __slots__ = ("message", "updateObj", "lock", "handled", "step", "_id", "_stateId")

    def __init__(self, message: EnsuredMessage, updateObj: UpdateObjectType, stateId: Optional[str] = None):
        self.message = message
        self.updateObj = updateObj
        self.lock: asyncio.Lock = asyncio.Lock()
        self.handled: asyncio.Event = asyncio.Event()
        self.step: int = -1
        self._id: Optional[str] = None
        self._stateId = stateId

    def getId(self, forceRecalc: bool = False) -> str:
        if self._id is None or forceRecalc:
            self._id = f"{self.message.recipient.id}:{self.message.messageId}"

        return self._id

    def getStateId(self, forceRecalc: bool = False) -> str:
        if self._stateId is None or forceRecalc:
            self._stateId = f"{self.message.recipient.id}:{self.message.threadId}"

        return self._stateId

    def __str__(self) -> str:
        return (
            f"MessageQueueRecord({self.message}, {self.updateObj}, <lock>, "
            f"{self.handled}, {self.step}, {self._id}, {self._stateId})"
        )

    async def awaitStepDone(self, step: int) -> None:
        while not self.handled.is_set() and self.step < step:
            await asyncio.sleep(0.1)


class ChatProcessingState:
    """
    Represents the state of a chat processing.
    """

    __slots__ = ("chatId", "threadId", "queue", "lock", "shutdownEvent", "_queueKey", "_updateAt")

    def __init__(self, chatId: int, threadId: Optional[int] = None, queueKey: Optional[str] = None) -> None:
        self.chatId: int = chatId
        self.threadId: Optional[int] = threadId
        self.queue = deque[MessageQueueRecord]()
        self.lock = asyncio.Lock()
        self.shutdownEvent = asyncio.Event()
        self._queueKey: Optional[str] = queueKey
        self._updateAt: float = time.time()

    def getUpdatedAt(self) -> float:
        return self._updateAt

    def getQueueKey(self, forceRecalc: bool = False) -> str:
        if self._queueKey is None or forceRecalc:
            self._queueKey = f"{self.chatId}:{self.threadId}"

        return self._queueKey

    async def addMessage(self, message: EnsuredMessage, updateObj: UpdateObjectType) -> MessageQueueRecord:
        if self.shutdownEvent.is_set():
            raise RuntimeError("Chat processing is shut down")
        record = MessageQueueRecord(message, updateObj, stateId=self.getQueueKey())
        async with self.lock:
            self._updateAt = time.time()
            self.queue.append(record)
        return record

    async def messageProcessed(self, message: MessageQueueRecord) -> None:
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
        messageId = message.getId()
        previousMessage: Optional[MessageQueueRecord] = None
        async with self.lock:
            for record in self.queue:
                if record.getId() == messageId:
                    return previousMessage
                previousMessage = record

        raise ValueError(f"Record {message} not found in queue {self.getQueueKey()}")


class HandlersManager(CommandHandlerGetterInterface):
    """
    Manages and coordinates multiple bot handlers for message processing.

    This class orchestrates the execution of various handlers in a specific order,
    handles command parsing and routing, and manages handler lifecycle.
    """

    def __init__(
        self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager, botProvider: BotProvider
    ):
        """Initialize the handlers manager with required services.

        Args:
            configManager: Configuration manager instance
            database: Database wrapper for data persistence
            llmManager: LLM manager for AI model operations
            botProvider: Bot provider type (TELEGRAM or MAX)
        """
        self.configManager = configManager
        self.db = database
        self.llmManager = llmManager
        self.botProvider: BotProvider = botProvider
        self.handlerTimeout = 60 * 30

        # Map of command name -> CommandHandlerInfo
        self._commands: Dict[str, CommandHandlerInfoV2] = {}

        self.cache = CacheService.getInstance()
        self.cache.injectDatabase(self.db)

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

        self.cache.setDefaultChatSettings(
            ChatType.PRIVATE,
            {
                ChatSettingsKey(k): ChatSettingsValue(v)
                for k, v in botConfig.get("private-defaults", {}).items()
                if k in ChatSettingsKey
            },
        )

        self.cache.setDefaultChatSettings(
            ChatType.GROUP,
            {
                ChatSettingsKey(k): ChatSettingsValue(v)
                for k, v in botConfig.get("chat-defaults", {}).items()
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
                MessagePreprocessorHandler(configManager, database, llmManager, botProvider),
                HandlerParallelism.SEQUENTIAL,
            ),
            # Should be first (but after Preprocessor) to check for spam before other handlers
            # and do not allow SPAM to be processed by other handlers
            (SpamHandler(configManager, database, llmManager, botProvider), HandlerParallelism.SEQUENTIAL),
            # # Next - Handlers, which uses `newMessageHandler` for setting settings
            # Should be before MessagePreprocessorHandler to not save configuration answers
            (ConfigureCommandHandler(configManager, database, llmManager, botProvider), HandlerParallelism.PARALLEL),
            (SummarizationHandler(configManager, database, llmManager, botProvider), HandlerParallelism.PARALLEL),
            (UserDataHandler(configManager, database, llmManager, botProvider), HandlerParallelism.PARALLEL),
            # # Fourth - all other handlers
            (DevCommandsHandler(configManager, database, llmManager, botProvider), HandlerParallelism.PARALLEL),
            (MediaHandler(configManager, database, llmManager, botProvider), HandlerParallelism.PARALLEL),
            (CommonHandler(configManager, database, llmManager, botProvider), HandlerParallelism.PARALLEL),
            # Special case - help command require all command handlers information
            (HelpHandler(configManager, database, llmManager, botProvider, self), HandlerParallelism.PARALLEL),
        ]

        if self.botProvider == BotProvider.TELEGRAM:
            self.handlers.extend(
                [
                    (
                        ReactOnUserMessageHandler(configManager, database, llmManager, botProvider),
                        HandlerParallelism.PARALLEL,
                    ),
                    (
                        TopicManagerHandler(
                            configManager=configManager,
                            database=database,
                            llmManager=llmManager,
                            botProvider=botProvider,
                        ),
                        HandlerParallelism.PARALLEL,
                    ),
                ]
            )

        # Add WeatherHandler only if OpenWeatherMap integration is enabled
        if self.configManager.getOpenWeatherMapConfig().get("enabled", False):
            self.handlers.append(
                (WeatherHandler(configManager, database, llmManager, botProvider), HandlerParallelism.PARALLEL)
            )
        if self.configManager.getYandexSearchConfig().get("enabled", False):
            self.handlers.append(
                (YandexSearchHandler(configManager, database, llmManager, botProvider), HandlerParallelism.PARALLEL)
            )
        if self.configManager.get("resender", {}).get("enabled", False):
            self.handlers.append(
                (ResenderHandler(configManager, database, llmManager, botProvider), HandlerParallelism.PARALLEL)
            )

        self.handlers.append(
            # Should be last messageHandler as it can handle any message
            (LLMMessageHandler(configManager, database, llmManager, botProvider), HandlerParallelism.SEQUENTIAL)
        )

        self.chatStates: Dict[str, ChatProcessingState] = {}
        self.handlerTasks: MutableSet[asyncio.Task] = set[asyncio.Task]()
        self.stateLock = asyncio.Lock()
        """Global Lock for Queue management (checking, creating, deleteing)"""

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
        nowTimeStuct = time.gmtime(nowTime)
        nowMinutes = nowTimeStuct.tm_min
        nowHour = nowTimeStuct.tm_hour
        nowWDay = nowTimeStuct.tm_wday

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
        # Drop cache entries, that more than 3 month old
        self.db.clearOldCacheEntries(ttl=60 * 60 * 24 * 90)
        # Also drop completed tasks older than a month
        self.db.cleanupOldCompletedDelayedTasks(ttl=60 * 60 * 24 * 30)

    def injectBot(self, bot: ExtBot | libMax.MaxBotClient) -> None:
        """Inject bot instance into all registered handlers.

        Args:
            bot: Bot client instance (ExtBot for Telegram or MaxBotClient for Max Messenger)

        Returns:
            None

        Raises:
            ValueError: If bot type doesn't match the configured bot provider
        """
        theBot: Optional[TheBot] = None
        if self.botProvider == BotProvider.TELEGRAM and isinstance(bot, ExtBot):
            theBot = TheBot(botProvider=self.botProvider, config=self.configManager.getBotConfig(), tgBot=bot)
        elif self.botProvider == BotProvider.MAX and isinstance(bot, libMax.MaxBotClient):
            theBot = TheBot(botProvider=self.botProvider, config=self.configManager.getBotConfig(), maxBot=bot)

        if theBot is None:
            raise ValueError("Unexpected bot class")

        # For each botOwner username try to add it's userId as well
        for botOwner in theBot.botOwnersUsername:
            for userId in self.db.getUserIdByUserName(botOwner.lower()):
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
        """Run background tasks."""
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
        """
        TODO: Write docstring
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

            # Check if bot username privided in command and check if it is our username
            splittedCommand = command.split("@")
            command = splittedCommand[0]
            if len(splittedCommand) > 1:
                myUsername = await self.handlers[0][0].getBotUserName()
                if not myUsername or myUsername.lower() != splittedCommand[1].lower():
                    # TODO: Should we somehow indicate, that it is command but for someone else?
                    logger.debug(
                        f"Recieved command for someone else: {command}, bot: {splittedCommand[1]}, args: {args}"
                    )
                    return None

            logger.debug(f"Recieved command: {command}, args: {args}")
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

        commandTouple = await self.parseCommand(ensuredMessage)
        if commandTouple is None:
            return None

        command, args = commandTouple
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
        chatSettings = handlerObj.getChatSettings(ensuredMessage.recipient.id)
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
            await self.runAsync(self._processMessageRec(messageRec))

    async def _processMessageRec(self, messageRec: MessageQueueRecord) -> None:
        """
        TODO: write docstring
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
                self.cache.getChatUserData(chatId=ensuredMessage.recipient.id, userId=ensuredMessage.sender.id)
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

        Args:
            targetChat: Chat where the new member joined
            messageId: Message ID associated with the join event, if available
            newMember: User who joined the chat
            updateObj: Original update object from the platform
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

        Args:
            targetChat: Chat where the new member joined
            messageId: Message ID associated with the join event, if available
            newMember: User who joined the chat
            updateObj: Original update object from the platform
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

        Args:
            targetChat: Chat where the new member joined
            messageId: Message ID associated with the join event, if available
            leftMember: User who left the chat
            updateObj: Original update object from the platform
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

        Args:
            targetChat: Chat where the new member joined
            messageId: Message ID associated with the join event, if available
            leftMember: User who left the chat
            updateObj: Original update object from the platform
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
