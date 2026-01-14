"""
Bot handlers manager for coordinating message processing across multiple handlers.
"""

import asyncio
import logging
from collections.abc import MutableSet
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
from internal.services.queue_service import QueueService
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


class MessageQueueRecord:
    """
    Represents a message queue record with a message and a semaphore.
    """

    __slots__ = ("message", "updateObj", "lock", "handled")

    def __init__(self, message: EnsuredMessage, updateObj: UpdateObjectType, lock: asyncio.Lock):
        self.message = message
        self.updateObj = updateObj
        self.lock = lock
        self.handled = False


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

        # Initialize handlers
        # handlersHead - forst bunch of handlers. Can be run in parallel
        self.handlersHead: List[BaseBotHandler] = [
            # Should be first to check for spam before other handlers
            SpamHandler(configManager, database, llmManager, botProvider),
            # # Next - Handlers, which uses `newMessageHandler` for setting settings
            # Should be before MessagePreprocessorHandler to not save configuration answers
            ConfigureCommandHandler(configManager, database, llmManager, botProvider),
            SummarizationHandler(configManager, database, llmManager, botProvider),
            UserDataHandler(configManager, database, llmManager, botProvider),
            # # Last - Preprocessor handler to preprocess message (handle images and so on)
            # Should be before other handlers to ensure message saving + media processing
            MessagePreprocessorHandler(configManager, database, llmManager, botProvider),
        ]

        # handlersTail - second buch of handlers. Should be run in sequence for each ChatId+ThreadId
        self.handlersTail: List[BaseBotHandler] = [
            DevCommandsHandler(configManager, database, llmManager, botProvider),
            MediaHandler(configManager, database, llmManager, botProvider),
            CommonHandler(configManager, database, llmManager, botProvider),
            # Special case - help command require all command handlers information
            HelpHandler(configManager, database, llmManager, botProvider, self),
        ]

        if self.botProvider == BotProvider.TELEGRAM:
            self.handlersTail.extend(
                [
                    ReactOnUserMessageHandler(configManager, database, llmManager, botProvider),
                    TopicManagerHandler(
                        configManager=configManager, database=database, llmManager=llmManager, botProvider=botProvider
                    ),
                ]
            )

        # Add WeatherHandler only if OpenWeatherMap integration is enabled
        if self.configManager.getOpenWeatherMapConfig().get("enabled", False):
            self.handlersTail.append(WeatherHandler(configManager, database, llmManager, botProvider))
        if self.configManager.getYandexSearchConfig().get("enabled", False):
            self.handlersTail.append(YandexSearchHandler(configManager, database, llmManager, botProvider))
        if self.configManager.get("resender", {}).get("enabled", False):
            self.handlersTail.append(ResenderHandler(configManager, database, llmManager, botProvider))

        self.handlersTail.append(
            # Should be last messageHandler as it can handle any message
            LLMMessageHandler(configManager, database, llmManager, botProvider)
        )

        self.handlersCombined = self.handlersHead + self.handlersTail

        self.handlingQueues: Dict[str, asyncio.Queue[MessageQueueRecord]] = {}
        self.queueHandlers: MutableSet[asyncio.Task] = set[asyncio.Task]()
        self.queueLock = asyncio.Lock()
        self._isShuttonDown = asyncio.Event()

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

        for handler in self.handlersCombined:
            handler.injectBot(theBot)

    async def shutdown(self) -> None:
        """Shutdown the HandlersManager.

        This method will await for all running tasks and drop queues.
        """
        logger.info("Shutting down HandlersManager...")
        self._isShuttonDown.set()
        logger.info("Awaiting for queue handlers...")
        await asyncio.gather(*self.queueHandlers)

    async def addMessageToQueue(self, messageRec: MessageQueueRecord) -> None:
        """
        TODO: Write docstring
        """

        key = f"{messageRec.message.recipient.id}:{messageRec.message.threadId}"
        async with self.queueLock:
            # We have to do everything inside of lock to ensure, that nobody will delete\create queue in process
            # I.e. to avoid race
            isNewQueue = key not in self.handlingQueues

            if isNewQueue:
                self.handlingQueues[key] = asyncio.Queue()
                queueHandler = asyncio.create_task(self._processMessageQueue(key))
                self.queueHandlers.add(queueHandler)
                queueHandler.add_done_callback(self.queueHandlers.discard)

            await self.handlingQueues[key].put(messageRec)

    async def _dropQueueIfEmptyNoLock(self, queueKey: str) -> bool:
        """
        TODO: Write docstring
        """
        if queueKey not in self.handlingQueues:
            logger.warning(f"Queue {queueKey} not found, skipping")
            return False
        
        queue = self.handlingQueues[queueKey]
        # Recheck, that queue is empty
        if not queue.empty():
            logger.info(f"Queue {queueKey} is not empty, skipping")
            return False

        logger.debug(f"Queue {queueKey} is empty, dropping")
        self.handlingQueues.pop(queueKey, None)
        # For Python 3.13+
        if hasattr(queue, "shutdown") and callable(queue.shutdown):  # pyright: ignore[reportAttributeAccessIssue]
            queue.shutdown()  # pyright: ignore[reportAttributeAccessIssue]
        return True

    async def dropQueueIfEmpty(self, queueKey: str, skipLock: bool = False) -> bool:
        """
        TODO: Write docstring
        """
        if skipLock:
            return await self._dropQueueIfEmptyNoLock(queueKey)

        async with self.queueLock:
            return await self._dropQueueIfEmptyNoLock(queueKey)

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
        for handler in self.handlersCombined:
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
        if not self.handlersCombined:
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
                myUsername = await self.handlersCombined[0].getBotUserName()
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
        lock = asyncio.Lock()
        async with lock:
            messageRec = MessageQueueRecord(ensuredMessage, updateObj, lock)
            await self.addMessageToQueue(messageRec)
            ensuredMessage.setUserData(
                self.cache.getChatUserData(chatId=ensuredMessage.recipient.id, userId=ensuredMessage.sender.id)
            )

            commandRet = await self.handleCommand(ensuredMessage, updateObj)
            if commandRet is not None:
                logger.debug(f"Handled as command with result: {commandRet}")
                messageRec.handled = True
                return

            # resultSet: Set[HandlerResultStatus] = set()
            ret: HandlerResultStatus = HandlerResultStatus.SKIPPED
            for handler in self.handlersHead:
                ret = await handler.newMessageHandler(ensuredMessage, updateObj)
                # resultSet.add(ret)
                if ret.needLogs():
                    logger.debug(f"Handler {type(handler).__name__} returned {ret.value}")
                if ret.isFinalState():
                    messageRec.handled = True
                    break

            # Do nothing else, message will be processed by _processMessageQueue()

    async def _processMessageRec(self, messageRec: MessageQueueRecord) -> None:
        """
        TODO: write docstring
        """
        async with messageRec.lock:
            if messageRec.handled:
                logger.debug(f"Message {messageRec.message.sender}#{messageRec.message.recipient} already handled")
                return

            for handler in self.handlersTail:
                # TODO: Should I add max wait here?
                ret = await handler.newMessageHandler(messageRec.message, messageRec.updateObj)
                # resultSet.add(ret)
                if ret.needLogs():
                    logger.debug(f"Handler {type(handler).__name__} returned {ret.value}")
                if ret.isFinalState():
                    break

            logger.debug(
                f"Handled message {messageRec.message.sender}#{messageRec.message.recipient}: "
                f"{messageRec.message.messageText[:50]}... "
                # f"(resultSet: {resultSet})"
            )

    async def _processMessageQueue(self, queueKey: str) -> None:
        """Process a message queue.

        Args:
            queueKey: Key of the queue to process
        """

        async with self.queueLock:
            if queueKey not in self.handlingQueues:
                logger.error(f"Queue {queueKey} not found")
                return

            queue = self.handlingQueues[queueKey]

        if queue is None:
            logger.error(f"Queue {queueKey} not found")
            return

        awaitShutdown = asyncio.create_task(self._isShuttonDown.wait())
        while True:
            try:
                # If there is more that 30 minutes of no new message, drop queue
                awaitMessage = asyncio.create_task(queue.get())
                await asyncio.wait(
                    [awaitMessage, awaitShutdown],
                    timeout=60 * 30,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if awaitMessage.cancelled():
                    logger.debug(f"Awaiting of Queue {queueKey} cancelled...")
                elif awaitMessage.done():
                    messageRec: Optional[MessageQueueRecord] = None
                    try:
                        messageRec = awaitMessage.result()
                    except asyncio.CancelledError as e:
                        logger.error(f"Awaiting of Queue {queueKey} cancelled")
                        logger.exception(e)
                        continue
                    except asyncio.InvalidStateError as e:
                        logger.error(f"Awaiting of Queue {queueKey} failed")
                        logger.exception(e)
                        awaitMessage.cancel()
                        continue
                    except Exception as e:
                        logger.exception(e)
                        # continue

                    if messageRec is not None:
                        try:
                            await self._processMessageRec(messageRec)
                        except Exception as e:
                            logger.exception(e)
                        finally:
                            queue.task_done()
                            continue
                else:
                    # Cancel awaiting for new message in queue
                    awaitMessage.cancel()

                if awaitShutdown.done():
                    logger.info(f"Shutdown initiated, we have {queue.qsize()} messages left in queue {queueKey}")
                    async with self.queueLock:
                        logger.debug(f"Queue#{queueKey}: lock acquired")
                        while not queue.empty():
                            messageRec = queue.get_nowait()
                            try:
                                await self._processMessageRec(messageRec)
                            except Exception as e:
                                logger.exception(e)
                            finally:
                                queue.task_done()
                            logger.debug(f"Queue {queueKey}: {queue.qsize()} messages left...")

                        logger.debug(f"Queue#{queueKey}: trying to drop queue")
                        if not await self.dropQueueIfEmpty(queueKey, skipLock=True):
                            logger.error(f"Unable to drop Queue {queueKey}, continue shutdown process...")
                            
                    break

                # Timeout triggered
                if await self.dropQueueIfEmpty(queueKey):
                    awaitShutdown.cancel()
                    break
                else:
                    logger.warning(f"Queue {queueKey}: Timeout triggered, but queue is not empty, cannot drop queue")

            except Exception as e:
                logger.exception(e)

    async def handleCallback(
        self, ensuredMessage: EnsuredMessage, data: utils.PayloadDict, user: MessageSender, updateObj: UpdateObjectType
    ) -> None:
        """Handle callback query from inline keyboard buttons.

        Args:
            ensuredMessage: Message associated with the callback
            data: Callback data payload
            user: User who triggered the callback
            updateObj: Original update object from the platform
        """

        retSet: Set[HandlerResultStatus] = set()
        for handler in self.handlersCombined:
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

        retSet: Set[HandlerResultStatus] = set()
        for handler in self.handlersCombined:
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

        retSet: Set[HandlerResultStatus] = set()
        for handler in self.handlersCombined:
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
