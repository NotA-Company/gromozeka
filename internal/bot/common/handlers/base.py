"""
Base handler module for Gromozeka Telegram bot, dood!

This module provides the foundational [`BaseBotHandler`](internal/bot/handlers/base.py:66) class that all bot handlers
inherit from. It includes core functionality for message handling, chat settings management,
user data management, media processing, and database operations, dood!

The module defines:
- [`HandlerResultStatus`](internal/bot/handlers/base.py:56): Enum for handler processing results
- [`BaseBotHandler`](internal/bot/handlers/base.py:66): Base class with common handler functionality

Key Features:
- Chat settings and user data management with caching
- Media processing (images, stickers) with LLM integration
- Message sending with MarkdownV2 support
- Database operations for chats, users, and messages
- Admin permission checking
- Command handler discovery via decorators
"""

import asyncio
import datetime
import inspect
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set

import magic
import telegram
import telegram.constants
import telegram.ext as telegramExt
from telegram import Chat, MessageEntity, Update
from telegram.ext import ContextTypes

import lib.max_bot as maxBot
import lib.max_bot.models as maxModels
import lib.utils as utils
from internal.bot import constants
from internal.bot.common.models import CallbackButton, TypingAction, UpdateObjectType
from internal.bot.models import (
    BotProvider,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    CommandCategory,
    CommandHandlerInfo,
    CommandHandlerInfoV2,
    CommandHandlerMixin,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    MediaProcessingInfo,
    MentionCheckResult,
    MessageRecipient,
    MessageSender,
    MessageType,
    UserMetadataDict,
)
from internal.bot.models.command_handlers import _HANDLER_METADATA_ATTR
from internal.config.manager import ConfigManager
from internal.database.models import ChatInfoDict, ChatUserDict, MediaStatus, MessageCategory
from internal.database.wrapper import DatabaseWrapper
from internal.models import MessageIdType
from internal.services.cache import CacheService
from internal.services.queue_service import QueueService, makeEmptyAsyncTask
from lib.ai import (
    LLMManager,
    ModelImageMessage,
    ModelMessage,
    ModelResultStatus,
)
from lib.markdown import markdownToMarkdownV2

logger = logging.getLogger(__name__)


class HandlerResultStatus(Enum):
    """
    Enum representing the result status of handler processing, dood!

    This enum is used to control the flow of message processing through
    multiple handlers in the handler chain.

    Attributes:
        FINAL: Processing completed successfully, no further handlers needed
        SKIPPED: Handler skipped processing (not applicable to this message)
        NEXT: Processing completed, continue to next handler in chain
        ERROR: Processing error occurred but can continue to next handler
        FATAL: Fatal error occurred, stop all processing immediately
    """

    FINAL = "final"  # Processed and no need further processing
    SKIPPED = "skipped"  # Skipped processing
    NEXT = "next"  # Processed, need to process further
    ERROR = "error"  # Processing error (can be processed further)
    FATAL = "fatal"  # Fatal error, need to stop processing


class TypingManager:
    """
    TODO
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


def commandHandlerExtended(
    commands: Sequence[str],  # Sequence of commands to handle
    shortDescription: str,  # Short description, for suggestions
    helpMessage: str,  # Long help message
    *,
    # Where command need to be suggested. Default: nowhere
    suggestCategories: Optional[Set[CommandPermission]] = None,
    # Where command is allowed to be used. Default: everywhere
    # TODO: Think if it really needed or we can use category for it?
    availableFor: Optional[Set[CommandPermission]] = None,
    # Order hor help message
    helpOrder: CommandHandlerOrder = CommandHandlerOrder.NORMAL,
    # Category for command (for more fine-grained permissions handling)
    category: CommandCategory = CommandCategory.UNSPECIFIED,
    # Which ChatAction we should send? None - to send nothing
    typingAction: Optional[TypingAction] = TypingAction.TYPING,
    # Should we reply to user with exception message on exception? Default: True
    replyErrorOnException: bool = True,
) -> Callable[
    [Callable[[Any, EnsuredMessage, Optional[TypingManager], Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]],
    Callable[["BaseBotHandler", Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]],
]:
    """
    Decorator for creating extended command handlers with metadata, permissions, and logging, dood!

    Creates a decorator that wraps command handler functions with additional functionality:
    - Stores command metadata (commands, descriptions, categories)
    - Checks user permissions based on chat type and user roles
    - Logs command usage in the database
    - Ensures message format before passing to handler
    - Manages typing actions during command execution
    - Handles exceptions and error reporting

    The decorator performs comprehensive permission checking based on:
    - Command category (PRIVATE, ADMIN, TOOLS, SPAM, etc.)
    - Chat type (PRIVATE, GROUP, SUPERGROUP)
    - User roles (bot owner, chat admin, regular user)
    - Chat-specific settings

    Args:
        commands: Sequence of command strings this handler responds to
        shortDescription: Brief description for command suggestions
        helpMessage: Detailed help text for the command
        suggestCategories: Where to suggest this command (default: HIDDEN/Nowhere)
        availableFor: Where command is allowed (default: DEFAULT/everyone)
        helpOrder: Order for help message display (default: NORMAL)
        category: Category for command, used for fine-grained permissions handling (default: UNSPECIFIED)
        typingAction: ChatAction to send during command execution (default: TYPING)
        replyErrorOnException: Whether to send error messages to users on exceptions (default: True)

    Returns:
        A decorator function that wraps the command handler with all the above functionality
    """
    if suggestCategories is None:
        suggestCategories = {CommandPermission.HIDDEN}
    if availableFor is None:
        availableFor = {CommandPermission.DEFAULT}

    def decorator(
        func: Callable[
            ["BaseBotHandler", EnsuredMessage, Optional[TypingManager], Update, ContextTypes.DEFAULT_TYPE],
            Awaitable[None],
        ],
    ) -> Callable[["BaseBotHandler", Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]:
        # Store metadata as an attribute on the function
        metadata = CommandHandlerInfo(
            commands=commands,
            shortDescription=shortDescription,
            helpMessage=helpMessage,
            categories=suggestCategories,
            order=helpOrder,
            handler=func,
        )

        async def wrapper(self: "BaseBotHandler", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            logger.debug(f"Got {func.__name__} command: {update}")

            message = update.message
            if not message:
                logger.error("Message undefined")
                return

            ensuredMessage: Optional[EnsuredMessage] = None
            try:
                ensuredMessage = EnsuredMessage.fromTelegramMessage(message)
            except Exception as e:
                logger.error(f"Error while ensuring message: {e}")
                return

            # Check permissions if needed

            canProcess = CommandPermission.DEFAULT in availableFor
            isBotOwner = await self.isAdmin(ensuredMessage.sender, None, allowBotOwners=True)
            chatSettings = self.getChatSettings(ensuredMessage.recipient.id)
            chatType = ensuredMessage.recipient.chatType

            if not canProcess and CommandPermission.PRIVATE in availableFor:
                canProcess = chatType == ChatType.PRIVATE
            if not canProcess and CommandPermission.GROUP in availableFor:
                canProcess = chatType == ChatType.GROUP

            if not canProcess and CommandPermission.BOT_OWNER in availableFor:
                canProcess = isBotOwner

            if not canProcess and CommandPermission.ADMIN:
                canProcess = (chatType in [Chat.GROUP, Chat.SUPERGROUP]) and await self.isAdmin(
                    ensuredMessage.sender, ensuredMessage.recipient
                )

            if not canProcess:
                botCommand = ensuredMessage.messageText.split(" ", 1)[0]
                for entityStr in message.parse_entities([MessageEntity.BOT_COMMAND]).values():
                    botCommand = entityStr
                    break

                logger.warning(
                    f"Command `{botCommand}` is not allowed in "
                    f"chat {ensuredMessage.recipient} for "
                    f"user {ensuredMessage.sender}. Needed permissions: {availableFor}"
                )
                if chatSettings[ChatSettingsKey.DELETE_DENIED_COMMANDS].toBool():
                    try:
                        await message.delete()
                    except Exception as e:
                        logger.error(f"Error while deleting message: {e}")
                return

            isAdmin = await self.isAdmin(ensuredMessage.sender, ensuredMessage.recipient)
            match category:
                case CommandCategory.UNSPECIFIED:
                    # No category specified, deny by default
                    canProcess = False
                case CommandCategory.PRIVATE:
                    canProcess = chatType == Chat.PRIVATE
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
                    logger.error(f"Unhandled command category: {category}, deny")
                    canProcess = False
                    pass

            if not canProcess:
                botCommand = ensuredMessage.messageText.split(" ", 1)[0]
                for entityStr in message.parse_entities([MessageEntity.BOT_COMMAND]).values():
                    botCommand = entityStr
                    break

                logger.warning(
                    f"Command `{str(botCommand)}` is not allowed in "
                    f"chat {ensuredMessage.recipient} for "
                    f"user {ensuredMessage.sender}. Command category: {category}."
                )
                if chatSettings[ChatSettingsKey.DELETE_DENIED_COMMANDS].toBool():
                    try:
                        await message.delete()
                    except Exception as e:
                        logger.error(f"Error while deleting message: {e}")
                return

            # Store command message in database
            await self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

            # Actually handle command
            try:
                # if typingAction is not None:
                #     async with await self.startTyping(ensuredMessage, action=typingAction) as typingManager:
                #         return await func(self, ensuredMessage, typingManager, update, context)
                # else:
                return await func(self, ensuredMessage, None, update, context)
            except Exception as e:
                logger.error(f"Error while handling command {ensuredMessage.messageText.split(" ", 1)[0]}: {e}")
                logger.exception(e)
                if replyErrorOnException:
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=f"Error while handling command:\n```\n{e}\n```",
                        messageCategory=MessageCategory.BOT_ERROR,
                    )

        # setattr(func, _HANDLER_METADATA_ATTR, metadata)
        setattr(wrapper, _HANDLER_METADATA_ATTR, metadata)
        return wrapper

    return decorator


class BaseBotHandler(CommandHandlerMixin):
    """
    Base handler class providing core functionality for all bot handlers, dood!

    This class serves as the foundation for all specialized bot handlers, providing
    common functionality for message handling, chat management, user data storage,
    media processing, and database operations.

    The class integrates with:
    - [`ConfigManager`](internal/config/manager.py): For bot configuration
    - [`DatabaseWrapper`](internal/database/wrapper.py): For data persistence
    - [`LLMManager`](lib/ai/manager.py): For AI model interactions
    - [`CacheService`](internal/services/cache/service.py): For performance optimization
    - [`QueueService`](internal/services/queue/service.py): For background task management

    Attributes:
        configManager: Configuration manager instance
        config: Bot configuration dictionary
        db: Database wrapper for data operations
        llmManager: LLM manager for AI model access
        botOwners: List of bot owner usernames (lowercase)
        chatDefaults: Default settings for all chats
        cache: Cache service instance
        queueService: Queue service for background tasks
    """

    def __init__(
        self,
        configManager: ConfigManager,
        database: DatabaseWrapper,
        llmManager: LLMManager,
        botProvider: BotProvider,
    ):
        """
        Initialize the base handler with required services, dood!

        Args:
            configManager: Configuration manager providing bot settings
            database: Database wrapper for data persistence
            llmManager: LLM manager for AI model operations
        """
        # Initialize the mixin (discovers handlers)
        super().__init__()

        self.configManager = configManager
        self.config = configManager.getBotConfig()
        self.db = database
        self.llmManager = llmManager
        self.botProvider = botProvider

        # TODO: Put all botOwners and chatDefaults to some service to not duplicate it for each handler class
        # Init different defaults
        self.botOwnersUsername = [
            username.lower() for username in self.config.get("bot_owners", []) if isinstance(username, str)
        ]
        self.botOwnersId = [userId for userId in self.config.get("bot_owners", []) if isinstance(userId, int)]

        self.defaultSettings: Dict[ChatSettingsKey, ChatSettingsValue] = {
            k: ChatSettingsValue("") for k in ChatSettingsKey
        }
        self.defaultSettings.update(
            {
                ChatSettingsKey(k): ChatSettingsValue(v)
                for k, v in self.config.get("defaults", {}).items()
                if k in ChatSettingsKey
            }
        )
        self.privateDefaultSettings: Dict[ChatSettingsKey, ChatSettingsValue] = {
            ChatSettingsKey(k): ChatSettingsValue(v)
            for k, v in self.config.get("private-defaults", {}).items()
            if k in ChatSettingsKey
        }
        self.chatDefaultSettings: Dict[ChatSettingsKey, ChatSettingsValue] = {
            ChatSettingsKey(k): ChatSettingsValue(v)
            for k, v in self.config.get("chat-defaults", {}).items()
            if k in ChatSettingsKey
        }

        # Debug purposes
        # logger.debug("Config")
        # logger.debug(utils.jsonDumps(self.config, indent=2))
        # logger.debug("defaults")
        # logger.debug(utils.jsonDumps(self.defaultSettings, indent=2))
        # logger.debug("private-defaults")
        # logger.debug(utils.jsonDumps(self.privateDefaultSettings, indent=2))
        # logger.debug("chat-defaults")
        # logger.debug(utils.jsonDumps(self.chatDefaultSettings, indent=2))

        # Init cache
        self.cache = CacheService.getInstance()

        self.queueService = QueueService.getInstance()

        self._tgBot: Optional[telegramExt.ExtBot] = None
        self._maxBot: Optional[maxBot.MaxBotClient] = None

    def getCommandHandlersV2(self) -> Sequence[CommandHandlerInfoV2]:
        """
        Get all command handlers auto-discovered via decorators, dood!

        Returns:
            Sequence of [`CommandHandlerInfo`](internal/bot/models/command_handlers.py) objects containing
            handler metadata (command names, descriptions, handler functions)
        """
        return super().getCommandHandlersV2()

    def getCommandHandlers(self) -> Sequence[CommandHandlerInfo]:
        """
        Get all command handlers auto-discovered via decorators, dood!

        Returns:
            Sequence of [`CommandHandlerInfo`](internal/bot/models/command_handlers.py) objects containing
            handler metadata (command names, descriptions, handler functions)
        """
        return super().getCommandHandlers()

    def injectTGBot(self, bot: telegramExt.ExtBot) -> None:
        """
        Inject the bot instance for use in handlers, dood!

        This method must be called before handlers can send messages or
        perform bot-specific operations.

        Args:
            bot: Telegram bot instance from python-telegram-bot library
        """
        if self.botProvider != BotProvider.TELEGRAM:
            raise ValueError(f"Bot provider must be {BotProvider.TELEGRAM}")
        self._tgBot = bot

    def injectMaxBot(self, bot: maxBot.MaxBotClient) -> None:
        """
        Inject the bot instance for use in handlers, dood!

        This method must be called before handlers can send messages or
        perform bot-specific operations.

        Args:
            bot: Max bot instance from lib.max_bot library
        """
        if self.botProvider != BotProvider.MAX:
            raise ValueError(f"Bot provider must be {BotProvider.MAX}")
        self._maxBot = bot

    ###
    # Chat settings Managenent
    ###

    def getChatSettings(
        self,
        chatId: Optional[int],
        *,
        returnDefault: bool = True,
        chatType: Optional[ChatType] = None,
    ) -> Dict[ChatSettingsKey, ChatSettingsValue]:
        """
        Get chat settings with optional default fallback, dood!

        Retrieves settings from cache, merging with defaults if requested.
        If chatId is None, returns only default settings.

        Args:
            chatId: Telegram chat ID, or None for defaults only
            returnDefault: If True, merge with default settings; if False, return only custom settings
            chatType: Chat type to get defaults for (usefull only if chatId is None)

        Returns:
            Dictionary mapping [`ChatSettingsKey`](internal/bot/models/chat_settings.py)
                            to [`ChatSettingsValue`](internal/bot/models/chat_settings.py)
        """
        defaultSettings: Dict[ChatSettingsKey, ChatSettingsValue] = {}
        if chatId is None and chatType is None:
            raise ValueError("Either chatId or chatType shoul be not None")

        # TODO: Currently we support only Private and Groups
        # In case of Channels support, we need to think something
        if chatId is not None:
            chatType = ChatType.PRIVATE if chatId > 0 else ChatType.GROUP
        if chatType != ChatType.PRIVATE:
            chatType = ChatType.GROUP

        if returnDefault:
            defaultSettings = self.defaultSettings.copy()
            if chatType == ChatType.PRIVATE:  # it's Private Chat
                defaultSettings.update(self.privateDefaultSettings)
            elif chatType == ChatType.GROUP:  # it's Group Chat
                defaultSettings.update(self.chatDefaultSettings)

        if chatId is None:
            return defaultSettings

        chatSettings = self.cache.getChatSettings(chatId)

        return {**defaultSettings, **chatSettings}

    def setChatSetting(self, chatId: int, key: ChatSettingsKey, value: ChatSettingsValue) -> None:
        """
        Set a specific chat setting, dood!

        Updates the setting in cache, which will be persisted to database.

        Args:
            chatId: Telegram chat ID
            key: Setting key from [`ChatSettingsKey`](internal/bot/models/chat_settings.py) enum
            value: Setting value as [`ChatSettingsValue`](internal/bot/models/chat_settings.py)

        Note:
            This method directly updates the cache. Consider whether this setting
            should be validated before being applied.
        """
        self.cache.setChatSetting(chatId, key, value)

    def unsetChatSetting(self, chatId: int, key: ChatSettingsKey) -> None:
        """
        Remove a specific chat setting, reverting to default, dood!

        Args:
            chatId: Telegram chat ID
            key: Setting key from [`ChatSettingsKey`](internal/bot/models/chat_settings.py) enum to remove
        """
        self.cache.unsetChatSetting(chatId=chatId, key=key)

    ###
    # User Data Management
    ###

    def _updateEMessageUserData(self, ensuredMessage: EnsuredMessage) -> None:
        """
        Update an [`EnsuredMessage`](internal/bot/models/ensured_message.py) with current user data, dood!

        Internal helper method to inject user data into message objects.

        Args:
            ensuredMessage: Message object to update with user data
        """
        ensuredMessage.setUserData(
            self.cache.getChatUserData(chatId=ensuredMessage.recipient.id, userId=ensuredMessage.sender.id)
        )

    async def checkEMMentionsMe(self, ensuredMessage: EnsuredMessage) -> MentionCheckResult:
        """
        Check if a message mentions the bot, dood!

        Checks for bot username mention or custom nicknames configured in chat settings.

        Args:
            ensuredMessage: Message to check for mentions

        Returns:
            [`MentionCheckResult`](internal/bot/models/ensured_message.py) indicating if bot was mentioned
        """
        chatSettings = self.getChatSettings(ensuredMessage.recipient.id)

        username: Optional[str] = await self.getBotUserName()
        if username is not None:
            username = "@" + username.lower().lstrip("@")

        return ensuredMessage.checkHasMention(
            username=username,
            customMentions=chatSettings[ChatSettingsKey.BOT_NICKNAMES].toList(),
        )

    ###
    # Different helpers
    ###

    async def getBotId(self) -> int:
        if self._tgBot:
            return self._tgBot.id
        elif self._maxBot:
            return (await self._maxBot.getMyInfo()).user_id

        raise RuntimeError("No Active bot found")

    async def getBotUserName(self) -> Optional[str]:
        if self._tgBot:
            return self._tgBot.username
        elif self._maxBot:
            return (await self._maxBot.getMyInfo()).username

        raise RuntimeError("No Active bot found")

    async def isAdmin(
        self, user: MessageSender, chat: Optional[MessageRecipient] = None, allowBotOwners: bool = True
    ) -> bool:
        """
        Check if a user is an admin or bot owner, dood!

        If chat is None, only checks bot owner status.
        If chat is provided, checks both bot owners and chat administrators.

        Args:
            user: Telegram user to check
            chat: Optional chat to check admin status in
            allowBotOwners: If True, bot owners are always considered admins

        Returns:
            True if user is admin/owner, False otherwise
        """
        # If chat is None, then we are checking if it's bot owner only

        username = user.username
        if username:
            username = username.lower().lstrip("@")

        # TODO: Add support of bot owners by userId
        if allowBotOwners and (username in self.botOwnersUsername or user.id in self.botOwnersId):
            # User is bot owner and bot owners are allowed
            return True

        if chat is None:
            # No chat - can't be admin
            return False

        if chat.chatType == ChatType.PRIVATE:
            return True

        # If userId is the same as chatID, then it's Private chat or Anonymous Admin
        if self.botProvider == BotProvider.TELEGRAM and user.id == chat.id:
            return True

        # If chat is passed, check if user is admin of given chat
        chatAdmins = self.cache.getChatAdmins(chat.id)
        if chatAdmins is not None:
            return user.id in chatAdmins

        chatAdmins = {}  # userID -> username
        if self.botProvider == BotProvider.TELEGRAM and self._tgBot is not None:
            for admin in await self._tgBot.get_chat_administrators(chat_id=chat.id):
                chatAdmins[admin.user.id] = admin.user.name

        elif self.botProvider == BotProvider.MAX and self._maxBot is not None:
            maxChatAdmins = (await self._maxBot.getAdmins(chatId=chat.id)).members
            for admin in maxChatAdmins:
                adminName = admin.username
                if adminName is None:
                    adminName = admin.first_name
                    if admin.last_name:
                        adminName += " " + admin.last_name
                else:
                    adminName = f"@{adminName}"

                chatAdmins[admin.user_id] = adminName

        else:
            raise RuntimeError(f"Unexpected platform: {self.botProvider}")

        self.cache.setChatAdmins(chat.id, chatAdmins)
        return user.id in chatAdmins

    def _keyboardToTelegram(self, keyboard: Sequence[Sequence[CallbackButton]]) -> telegram.InlineKeyboardMarkup:
        return telegram.InlineKeyboardMarkup([[btn.toTelegram() for btn in row] for row in keyboard])

    def _keyboardToMax(self, keyboard: Sequence[Sequence[CallbackButton]]) -> maxModels.InlineKeyboardAttachmentRequest:
        return maxModels.InlineKeyboardAttachmentRequest(
            payload=maxModels.Keyboard(buttons=[[btn.toMax() for btn in row] for row in keyboard])
        )

    async def editMessage(
        self,
        messageId: MessageIdType,
        chatId: int,
        *,
        text: Optional[str] = None,
        inlineKeyboard: Optional[Sequence[Sequence[CallbackButton]]] = None,
        useMarkdown: bool = True,
    ) -> bool:

        if self.botProvider == BotProvider.TELEGRAM and self._tgBot is not None:
            ret = None
            if text is None:
                ret = await self._tgBot.edit_message_reply_markup(
                    chat_id=chatId,
                    message_id=int(messageId),
                    reply_markup=self._keyboardToTelegram(inlineKeyboard) if inlineKeyboard is not None else None,
                )
            else:
                kwargs = {}
                if useMarkdown:
                    kwargs["parse_mode"] = telegram.constants.ParseMode.MARKDOWN_V2
                    text = markdownToMarkdownV2(text)
                ret = await self._tgBot.edit_message_text(
                    text=text,
                    chat_id=chatId,
                    message_id=int(messageId),
                    reply_markup=self._keyboardToTelegram(inlineKeyboard) if inlineKeyboard is not None else None,
                    **kwargs,
                )
            return bool(ret)
        elif self.botProvider == BotProvider.MAX and self._maxBot is not None:
            await self._maxBot.editMessage(
                messageId=str(messageId),
                text=text,
                attachments=None if inlineKeyboard is not None else [],
                inlineKeyboard=self._keyboardToMax(inlineKeyboard) if inlineKeyboard is not None else None,
                format=maxModels.TextFormat.MARKDOWN if useMarkdown else None,
            )
        else:
            logger.error(f"Can not edit message in platform {self.botProvider}")
        return False

    async def sendMessage(
        self,
        replyToMessage: EnsuredMessage,
        messageText: Optional[str] = None,
        *,
        addMessagePrefix: str = "",
        photoData: Optional[bytes] = None,
        sendMessageKWargs: Optional[Dict[str, Any]] = None,
        tryMarkdownV2: bool = True,
        tryParseInputJSON: Optional[bool] = None,  # False - do not try, True - try, None - try to detect
        sendErrorIfAny: bool = True,
        skipLogs: bool = False,
        mediaPrompt: Optional[str] = None,
        messageCategory: MessageCategory = MessageCategory.BOT,
        inlineKeyboard: Optional[Sequence[Sequence[CallbackButton]]] = None,
        typingManager: Optional[TypingManager] = None,
        splitIfTooLong: bool = True,
    ) -> List[EnsuredMessage]:
        match self.botProvider:
            case BotProvider.TELEGRAM:
                # TODO: Refactoring needed
                inlineKeyboardTg = self._keyboardToTelegram(inlineKeyboard) if inlineKeyboard is not None else None

                return await self._sendTelegramMessage(
                    replyToMessage=replyToMessage,
                    messageText=messageText,
                    addMessagePrefix=addMessagePrefix,
                    photoData=photoData,
                    sendMessageKWargs=sendMessageKWargs,
                    tryMarkdownV2=tryMarkdownV2,
                    tryParseInputJSON=tryParseInputJSON,
                    sendErrorIfAny=sendErrorIfAny,
                    skipLogs=skipLogs,
                    mediaPrompt=mediaPrompt,
                    messageCategory=messageCategory,
                    inlineKeyboard=inlineKeyboardTg,
                    typingManager=typingManager,
                    splitIfTooLong=splitIfTooLong,
                )

            case BotProvider.MAX:
                inlineKeyboardMax = self._keyboardToMax(inlineKeyboard) if inlineKeyboard is not None else None

                return await self._sendMaxMessage(
                    replyToMessage=replyToMessage,
                    messageText=messageText,
                    addMessagePrefix=addMessagePrefix,
                    photoData=photoData,
                    sendMessageKWargs=sendMessageKWargs,
                    tryMarkdownV2=tryMarkdownV2,
                    tryParseInputJSON=tryParseInputJSON,
                    sendErrorIfAny=sendErrorIfAny,
                    skipLogs=skipLogs,
                    mediaPrompt=mediaPrompt,
                    messageCategory=messageCategory,
                    inlineKeyboard=inlineKeyboardMax,
                    typingManager=typingManager,
                    splitIfTooLong=splitIfTooLong,
                )
            case _:
                raise RuntimeError(f"Unexpected bot provider: {self.botProvider}")

    async def _sendMaxMessage(
        self,
        replyToMessage: EnsuredMessage,
        messageText: Optional[str] = None,
        *,
        addMessagePrefix: str = "",
        photoData: Optional[bytes] = None,
        sendMessageKWargs: Optional[Dict[str, Any]] = None,
        tryMarkdownV2: bool = True,
        tryParseInputJSON: Optional[bool] = None,  # False - do not try, True - try, None - try to detect
        sendErrorIfAny: bool = True,
        skipLogs: bool = False,
        mediaPrompt: Optional[str] = None,
        messageCategory: MessageCategory = MessageCategory.BOT,
        inlineKeyboard: Optional[maxModels.InlineKeyboardAttachmentRequest] = None,
        typingManager: Optional[TypingManager] = None,
        splitIfTooLong: bool = True,
    ) -> List[EnsuredMessage]:
        if self._maxBot is None:
            raise RuntimeError("Max bot is Undefined")

        if photoData is None and messageText is None:
            logger.error("No message text or photo data provided")
            raise ValueError("No message text or photo data provided")

        replyMessageList: List[maxModels.Message] = []
        ensuredReplyList: List[EnsuredMessage] = []
        # message = replyToMessage.getBaseMessage()
        # if not isinstance(message, maxModels.Message):
        #     logger.error("Invalid message type")
        #     raise ValueError("Invalid message type")
        chatType = replyToMessage.recipient.chatType

        if typingManager is not None:
            await typingManager.stopTask()

        if chatType not in [ChatType.PRIVATE, ChatType.GROUP]:
            logger.error("Cannot send message to chat type {}".format(chatType))
            raise ValueError("Cannot send message to chat type {}".format(chatType))

        if sendMessageKWargs is None:
            sendMessageKWargs = {}

        replyKwargs = sendMessageKWargs.copy()
        replyKwargs.update(
            {
                "chatId": replyToMessage.recipient.id,
                "replyTo": str(replyToMessage.messageId),
                "format": maxModels.TextFormat.MARKDOWN if tryMarkdownV2 else None,
            }
        )
        attachments: Optional[List[maxModels.AttachmentRequest]] = []

        try:
            if photoData is not None:
                mimeType = magic.from_buffer(photoData, mime=True)
                ext = mimeType.split("/")[1]
                ret = await self._maxBot.uploadFile(
                    filename=f"generated_image.{ext}",
                    data=photoData,
                    mimeType=mimeType,
                    uploadType=maxModels.UploadType.IMAGE,
                )
                if isinstance(ret, maxModels.UploadedPhoto):
                    attachments.append(
                        maxModels.PhotoAttachmentRequest(
                            payload=maxModels.PhotoAttachmentRequestPayload(
                                photos=ret.payload.photos,
                            )
                        )
                    )

            if messageText is not None or attachments:
                # Send Message
                if not attachments:
                    attachments = None
                if messageText is None:
                    messageText = ""

                if not skipLogs:
                    logger.debug(f"Sending reply to {replyToMessage}")

                messageTextList: List[str] = [messageText]
                maxMessageLength = maxBot.MAX_MESSAGE_LENGTH - len(addMessagePrefix)
                if splitIfTooLong and len(messageText) > maxMessageLength:
                    messageTextList = [
                        messageText[i : i + maxMessageLength] for i in range(0, len(messageText), maxMessageLength)
                    ]
                for _messageText in messageTextList:
                    ret = await self._maxBot.sendMessage(
                        text=addMessagePrefix + _messageText,
                        attachments=attachments,
                        inlineKeyboard=inlineKeyboard,
                        **replyKwargs,
                    )
                    attachments = None  # Send attachments with first message only
                    inlineKeyboard = None
                    replyMessageList.append(ret.message)

            try:
                if not replyMessageList:
                    raise ValueError("No reply messages")

                if not skipLogs:
                    logger.debug(f"Sent messages: {[utils.jsonDumps(msg) for msg in replyMessageList]}")

                # Save message
                for replyMessage in replyMessageList:
                    ensuredReplyMessage = EnsuredMessage.fromMaxMessage(replyMessage)
                    ensuredReplyList.append(ensuredReplyMessage)
                    if addMessagePrefix:
                        replyText = ensuredReplyMessage.messageText
                        if replyText.startswith(addMessagePrefix):
                            replyText = replyText[len(addMessagePrefix) :]
                            ensuredReplyMessage.messageText = replyText
                    if replyMessage.body.attachments:
                        # TODO: Process whole list
                        mediaList = await self.processMaxMedia(ensuredReplyMessage, mediaPrompt)
                        ensuredReplyMessage.addMediaProcessingInfo(mediaList[-1])

                    await self.saveChatMessage(ensuredReplyMessage, messageCategory=messageCategory)

            except Exception as e:
                logger.error(f"Error while saving chat message: {type(e).__name__}#{e}")
                logger.exception(e)
                # Message was sent, so return it
                return ensuredReplyList

        except Exception as e:
            logger.error(f"Error while sending message: {type(e).__name__}#{e}")
            logger.exception(e)
            if sendErrorIfAny:
                try:
                    await self._maxBot.sendMessage(
                        text=f"Error while sending message: {type(e).__name__}#{e}",
                        chatId=replyToMessage.recipient.id,
                        replyTo=str(replyToMessage.messageId),
                    )
                except Exception as error_e:
                    logger.error(f"Failed to send error message: {type(error_e).__name__}#{error_e}")
            return ensuredReplyList

        return ensuredReplyList

    async def _sendTelegramMessage(
        self,
        replyToMessage: EnsuredMessage,
        messageText: Optional[str] = None,
        *,
        addMessagePrefix: str = "",
        photoData: Optional[bytes] = None,
        sendMessageKWargs: Optional[Dict[str, Any]] = None,
        tryMarkdownV2: bool = True,
        tryParseInputJSON: Optional[bool] = None,  # False - do not try, True - try, None - try to detect
        sendErrorIfAny: bool = True,
        skipLogs: bool = False,
        mediaPrompt: Optional[str] = None,
        messageCategory: MessageCategory = MessageCategory.BOT,
        inlineKeyboard: Optional[telegram.InlineKeyboardMarkup] = None,
        typingManager: Optional[TypingManager] = None,
        splitIfTooLong: bool = True,
    ) -> List[EnsuredMessage]:
        """
        Send a text or photo message as a reply, dood!

        Handles message formatting (MarkdownV2), JSON parsing, photo sending,
        and automatic message saving to database. Supports both text and photo messages.

        Args:
            replyToMessage: Message to reply to
            messageText: Text content (required if photoData is None)
            addMessagePrefix: Prefix to add before message text
            photoData: Photo bytes (required if messageText is None)
            photoCaption: Caption for photo messages
            sendMessageKWargs: Additional kwargs for telegram send methods
            tryMarkdownV2: If True, attempt to parse and send as MarkdownV2
            tryParseInputJSON: Whether to parse JSON responses (None=auto-detect)
            sendErrorIfAny: If True, send error message on failure
            skipLogs: If True, skip debug logging
            mediaPrompt: Optional prompt for media processing
            messageCategory: Category for database storage (from [`MessageCategory`](internal/database/models.py))
            replyMarkup: Optional reply markup (keyboard/buttons)
            typingManager: Optional `TypingManager` object for managing typing action if any
            splitIfTooLong: If True (default) - will split long messages to smaller ones
        Returns:
            Sent Message object, or None if sending failed

        Raises:
            ValueError: If neither messageText nor photoData provided, or invalid chat type
        """

        if photoData is None and messageText is None:
            logger.error("No message text or photo data provided")
            raise ValueError("No message text or photo data provided")

        replyMessageList: List[telegram.Message] = []
        ensuredReplyList: List[EnsuredMessage] = []
        message = replyToMessage.toTelegramMessage()
        message.set_bot(self._tgBot)
        chatType = replyToMessage.recipient.chatType
        isPrivate = chatType == ChatType.PRIVATE
        isGroupChat = chatType == ChatType.GROUP

        if typingManager is not None:
            await typingManager.stopTask()

        if not isPrivate and not isGroupChat:
            logger.error("Cannot send message to chat type {}".format(chatType))
            raise ValueError("Cannot send message to chat type {}".format(chatType))

        if sendMessageKWargs is None:
            sendMessageKWargs = {}

        replyKwargs = sendMessageKWargs.copy()
        replyKwargs.update(
            {
                "reply_to_message_id": replyToMessage.messageId,
                "message_thread_id": replyToMessage.threadId,
                "reply_markup": inlineKeyboard,
            }
        )

        try:
            if photoData is not None:
                # Send photo
                replyKwargs.update(
                    {
                        "photo": photoData,
                    }
                )

                replyMessage: Optional[telegram.Message] = None
                if tryMarkdownV2 and messageText is not None:
                    try:
                        messageTextParsed = markdownToMarkdownV2(addMessagePrefix + messageText)
                        # logger.debug(f"Sending MarkdownV2: {replyText}")
                        # TODO: One day start using self._tgBot
                        replyMessage = await message.reply_photo(
                            caption=messageTextParsed,
                            parse_mode=telegram.constants.ParseMode.MARKDOWN_V2,
                            **replyKwargs,
                        )
                    except Exception as e:
                        logger.error(f"Error while sending MarkdownV2 reply to message: {type(e).__name__}#{e}")
                        # Probably error in markdown formatting, fallback to raw text

                if replyMessage is None:
                    _messageText = messageText if messageText is not None else ""
                    replyMessage = await message.reply_photo(caption=addMessagePrefix + _messageText, **replyKwargs)
                if replyMessage is not None:
                    replyMessageList.append(replyMessage)

            elif messageText is not None:
                # Send text

                # If response is json, parse it
                # TODO: Not sure if it works properly
                if tryParseInputJSON is None:
                    tryParseInputJSON = re.match(r"^\s*`*\s*{", messageText) is not None
                    if tryParseInputJSON:
                        logger.debug(f"JSONPreParser: message '{messageText}' looks like JSON, tring parse it")

                if tryParseInputJSON:
                    try:
                        jsonReply = json.loads(messageText.strip("` \n\r"))
                        if "text" in jsonReply:
                            messageText = str(jsonReply["text"]).strip()
                        elif "message" in jsonReply:
                            messageText = str(jsonReply["message"]).strip()
                        elif "media_description" in jsonReply:
                            messageText = str(jsonReply["media_description"]).strip()
                        else:
                            logger.warning(f"No text field found in json reply, fallback to text: {jsonReply}")
                            raise ValueError("No text field found in json reply")
                    except Exception as e:
                        logger.debug(f"Error while parsing LLM reply, assume it's text: {type(e).__name__}#{e}")

                if not skipLogs:
                    logger.debug(f"Sending reply to {replyToMessage}")

                messageTextList: List[str] = [messageText]
                maxMessageLength = constants.TELEGRAM_MAX_MESSAGE_LENGTH - len(addMessagePrefix)
                if splitIfTooLong and len(messageText) > maxMessageLength:
                    messageTextList = [
                        messageText[i : i + maxMessageLength] for i in range(0, len(messageText), maxMessageLength)
                    ]
                for _messageText in messageTextList:
                    replyMessage: Optional[telegram.Message] = None
                    # Try to send Message as MarkdownV2 first
                    if tryMarkdownV2:
                        try:
                            messageTextParsed = markdownToMarkdownV2(addMessagePrefix + _messageText)
                            # logger.debug(f"Sending MarkdownV2: {replyText}")
                            replyMessage = await message.reply_text(
                                text=messageTextParsed,
                                parse_mode=telegram.constants.ParseMode.MARKDOWN_V2,
                                **replyKwargs,
                            )
                        except Exception as e:
                            logger.error(f"Error while sending MarkdownV2 reply to message: {type(e).__name__}#{e}")
                            # Probably error in markdown formatting, fallback to raw text

                    if replyMessage is None:
                        replyMessage = await message.reply_text(text=addMessagePrefix + _messageText, **replyKwargs)

                    if replyMessage is not None:
                        replyMessageList.append(replyMessage)

            try:
                if not replyMessageList:
                    raise ValueError("No reply messages")

                if not skipLogs:
                    logger.debug(f"Sent messages: {[utils.dumpTelegramMessage(msg) for msg in replyMessageList]}")

                # Save message
                for replyMessage in replyMessageList:
                    ensuredReplyMessage = EnsuredMessage.fromTelegramMessage(replyMessage)
                    ensuredReplyList.append(ensuredReplyMessage)
                    if addMessagePrefix:
                        replyText = ensuredReplyMessage.messageText
                        if replyText.startswith(addMessagePrefix):
                            replyText = replyText[len(addMessagePrefix) :]
                            ensuredReplyMessage.messageText = replyText
                    if replyMessage.photo:
                        media = await self.processTelegramImage(ensuredReplyMessage, mediaPrompt)
                        ensuredReplyMessage.addMediaProcessingInfo(media)

                    if isGroupChat or isPrivate:
                        await self.saveChatMessage(ensuredReplyMessage, messageCategory=messageCategory)
                    else:
                        raise ValueError("Unknown chat type")

            except Exception as e:
                logger.error(f"Error while saving chat message: {type(e).__name__}#{e}")
                logger.exception(e)
                # Message was sent, so return True anyway
                return ensuredReplyList

        except Exception as e:
            logger.error(f"Error while sending message: {type(e).__name__}#{e}")
            logger.exception(e)
            if sendErrorIfAny:
                try:
                    await message.reply_text(
                        f"Error while sending message: {type(e).__name__}#{e}",
                        reply_to_message_id=int(replyToMessage.messageId),
                    )
                except Exception as error_e:
                    logger.error(f"Failed to send error message: {type(error_e).__name__}#{error_e}")
            return ensuredReplyList

        return ensuredReplyList

    async def deleteMessage(self, ensuredMessage: EnsuredMessage) -> bool:
        """TODO"""
        return await self.deleteMessagesById(ensuredMessage.recipient.id, [ensuredMessage.messageId])

    async def deleteMessagesById(self, chatId: int, messageIds: List[MessageIdType]) -> bool:
        """TODO"""

        if self.botProvider == BotProvider.TELEGRAM and self._tgBot is not None:
            return await self._tgBot.delete_messages(
                chat_id=chatId,
                message_ids=[int(v) for v in messageIds],
            )
        elif self.botProvider == BotProvider.MAX and self._maxBot is not None:
            return await self._maxBot.deleteMessages([str(messageId) for messageId in messageIds])

        logger.error(f"Can not delete {messageIds} in platform {self.botProvider}")
        return False

    def getChatInfo(self, chatId: int) -> Optional[ChatInfoDict]:
        """
        Get chat information from cache or database, dood!

        Args:
            chatId: Telegram chat ID

        Returns:
            Chat info dictionary as [`ChatInfoDict`](internal/database/models.py), or None if not found
        """
        return self.cache.getChatInfo(chatId)

    async def updateChatInfo(self, message: EnsuredMessage) -> None:
        """
        TODO
        """

        if self.botProvider == BotProvider.TELEGRAM:
            try:
                baseMessage = message.getBaseMessage()
                if not isinstance(baseMessage, telegram.Message):
                    raise ValueError("Base message is not a telegram.Message")
                chat = baseMessage.chat
                chatId = chat.id
                storedChatInfo = self.getChatInfo(chatId=chatId)

                isForum = chat.is_forum or False

                if (
                    storedChatInfo is None
                    or chat.title != storedChatInfo["title"]
                    or chat.username != storedChatInfo["username"]
                    or isForum != storedChatInfo["is_forum"]
                    or message.recipient.chatType != storedChatInfo["type"]
                ):
                    self.cache.setChatInfo(
                        chat.id,
                        {
                            "chat_id": chat.id,
                            "title": chat.title,
                            "username": chat.username,
                            "is_forum": isForum,
                            "type": message.recipient.chatType,
                            "created_at": datetime.datetime.now(),
                            "updated_at": datetime.datetime.now(),
                        },
                    )

                # TODO: Actually topic name and emoji could be changed after that
                # but currently we have no way to know it (except of see
                # https://docs.python-telegram-bot.org/en/stable/telegram.forumtopicedited.html )
                # Think about it later
                if message.isTopicMessage:
                    repliedMessage = baseMessage.reply_to_message
                    if repliedMessage and repliedMessage.forum_topic_created:
                        self.updateTopicInfo(
                            chatId=message.recipient.id,
                            topicId=message.threadId,
                            iconColor=repliedMessage.forum_topic_created.icon_color,
                            customEmojiId=repliedMessage.forum_topic_created.icon_custom_emoji_id,
                            name=repliedMessage.forum_topic_created.name,
                        )
                else:
                    self.updateTopicInfo(chatId=message.recipient.id, topicId=message.threadId)
            except Exception as e:
                logger.error(f"Error updating chat info: {e}")
        elif self.botProvider == BotProvider.MAX and self._maxBot is not None:
            # Chat info isn't presend in message, so we need to request it explicitelly,
            # But we do not want to do it often. Looks like we need to check updated_at
            chatId = message.recipient.id
            storedChatInfo = self.getChatInfo(chatId=chatId)
            now = datetime.datetime.now()
            needChange = True
            if storedChatInfo is not None:

                timeDiff = now - storedChatInfo["updated_at"]
                needChange = timeDiff.total_seconds() > 60 * 60 * 12

            if not needChange:
                return

            maxChatInfo = await self._maxBot.getChat(chatId)
            self.cache.setChatInfo(
                chatId,
                {
                    "chat_id": chatId,
                    "title": maxChatInfo.title,
                    "username": maxChatInfo.link,
                    "is_forum": False,
                    "type": message.recipient.chatType,
                    "created_at": now,
                    "updated_at": now,
                },
            )

            self.updateTopicInfo(chatId=message.recipient.id, topicId=message.threadId)

        else:
            logger.error(f"Updating chat info for {self.botProvider} is not implemented yet")

    def updateTopicInfo(
        self,
        chatId: int,
        topicId: Optional[int],
        iconColor: Optional[int] = None,
        customEmojiId: Optional[str] = None,
        name: Optional[str] = None,
        force: bool = False,
    ) -> None:
        """
        Update forum topic information in cache and database, dood!

        Only updates if topic info has changed or force is True.
        Uses cache to avoid unnecessary database writes.

        Args:
            chatId: Telegram chat ID
            topicId: Forum topic ID (None or 0 for general topic)
            iconColor: Topic icon color code
            customEmojiId: Custom emoji ID for topic icon
            name: Topic name
            force: If True, update even if already in cache
        """
        _topicId = topicId if topicId is not None else 0
        storedTopicInfo = self.cache.getChatTopicInfo(chatId=chatId, topicId=_topicId)

        if not force and storedTopicInfo:
            # No need to rewrite topic info
            return

        self.cache.setChatTopicInfo(
            chatId=chatId,
            topicId=_topicId,
            info={
                "chat_id": chatId,
                "topic_id": _topicId,
                "icon_color": iconColor,
                "icon_custom_emoji_id": customEmojiId,
                "name": name,
                "created_at": datetime.datetime.now(),
                "updated_at": datetime.datetime.now(),
            },
        )

    async def saveChatMessage(self, message: EnsuredMessage, messageCategory: MessageCategory) -> bool:
        """
        Save a chat message to the database with full context, dood!

        Handles message threading, reply chains, chat/topic info updates,
        and user information updates. Automatically determines root message
        for reply chains.

        Args:
            message: Message to save as [`EnsuredMessage`](internal/bot/models/ensured_message.py)
            messageCategory: Message category from [`MessageCategory`](internal/database/models.py) enum

        Returns:
            True if saved successfully, False if message type unsupported
        """
        chat = message.recipient
        sender = message.sender

        if message.messageType == MessageType.UNKNOWN:
            logger.error(f"Unsupported message type: {message.messageType}")
            return False

        messageText = message.messageText

        replyId = message.replyId
        rootMessageId = message.messageId
        if message.isReply and replyId:
            parentMsg = self.db.getChatMessageByMessageId(
                chatId=chat.id,
                messageId=replyId,
            )
            if parentMsg:
                rootMessageId = parentMsg["root_message_id"]

        await self.updateChatInfo(message)

        self.db.updateChatUser(
            chatId=chat.id,
            userId=sender.id,
            username=sender.username,
            fullName=sender.name,
        )

        self.db.saveChatMessage(
            date=message.date,
            chatId=chat.id,
            userId=sender.id,
            messageId=message.messageId,
            replyId=replyId,
            threadId=message.threadId,
            messageText=messageText,
            messageType=message.messageType,
            messageCategory=messageCategory,
            rootMessageId=rootMessageId,
            quoteText=message.quoteText,
            mediaId=message.mediaId,
        )

        return True

    def parseUserMetadata(self, userInfo: Optional[ChatUserDict]) -> UserMetadataDict:
        """
        Parse user metadata from database record, dood!

        Args:
            userInfo: User info dictionary from database as [`ChatUserDict`](internal/database/models.py)

        Returns:
            Parsed metadata dictionary as [`UserMetadataDict`](internal/bot/models/user_metadata.py)
        """
        if userInfo is None:
            return {}

        metadataStr = userInfo["metadata"]
        if metadataStr:
            return json.loads(metadataStr)
        return {}

    def setUserMetadata(self, chatId: int, userId: int, metadata: UserMetadataDict, isUpdate: bool = False) -> None:
        """
        Set or update user metadata in database, dood!

        Args:
            chatId: Telegram chat ID
            userId: Telegram user ID
            metadata: Metadata dictionary as [`UserMetadataDict`](internal/bot/models/user_metadata.py)
            isUpdate: If True, merge with existing metadata; if False, replace completely
        """
        if isUpdate:
            userInfo = self.db.getChatUser(chatId=chatId, userId=userId)
            metadata = {**self.parseUserMetadata(userInfo), **metadata}

        metadataStr = utils.jsonDumps(metadata)
        self.db.updateUserMetadata(chatId=chatId, userId=userId, metadata=metadataStr)

    async def startTyping(
        self,
        ensuredMessage: EnsuredMessage,
        *,
        action: TypingAction = TypingAction.TYPING,
        # 5 minutes looks like reasonable default
        maxTimeout: int = 300,
        # If we'll not send typing action for abount 5 seconds, it will wanish, so need to refresh it
        repeatInterval: int = 4,
    ) -> TypingManager:
        """
        Start continuous typing action, dood!

        Creates and configures a TypingManager that sends typing actions at regular
        intervals until stopped. This is useful for long-running operations to show
        the user that the bot is still working.

        Args:
            ensuredMessage: Message object to send typing action for
            action: Chat action to send (default: TYPING)
            maxTimeout: Maximum time in seconds to keep typing (default: 300 seconds)
            repeatInterval: Interval in seconds between typing actions (default: 4 seconds)

        Returns:
            TypingManager instance to control the typing action
        """
        typingManager = TypingManager(
            action=action,
            maxTimeout=maxTimeout,
            repeatInterval=repeatInterval,
        )

        # logger.debug(f"startContinousTyping(,{action},{maxTimeout},{repeatInterval}) started...")

        async def sendTelegramAction():
            if self.botProvider != BotProvider.TELEGRAM or self._tgBot is None:
                raise RuntimeError("Telegram bot is undefined")
            await self._tgBot.send_chat_action(
                chat_id=ensuredMessage.recipient.id,
                action=typingManager.action.toTelegram(),
                message_thread_id=ensuredMessage.threadId,
            )

        async def sendMaxAction():
            if self.botProvider != BotProvider.MAX or self._maxBot is None:
                raise RuntimeError("Max bot is undefined")

            await self._maxBot.sendAction(
                chatId=ensuredMessage.recipient.id,
                action=typingManager.action.toMax(),
            )

        async def _sendTyping() -> None:
            typingManager.iteration = 0

            while typingManager.isRunning():
                # logger.debug(f"_sendTyping(,{action}), iteration: {iteration}...")
                if await typingManager.tick() == 0:
                    await typingManager.sendTypingAction()

            if typingManager.isTimeout():
                logger.warning(
                    f"startTyping({ensuredMessage}) reached timeout ({typingManager.maxTimeout}), exiting..."
                )

        sendAction: Optional[Callable[[], Awaitable]] = None
        match self.botProvider:
            case BotProvider.TELEGRAM:
                sendAction = sendTelegramAction
            case BotProvider.MAX:
                sendAction = sendMaxAction
            case _:
                logger.error(f"Unexpected Platform: {self.botProvider}")
                raise RuntimeError(f"Unexpected Platform: {self.botProvider}")

        await typingManager.startTask(asyncio.create_task(_sendTyping()), sendAction, True)
        return typingManager

    def getChatTitle(
        self,
        chatInfo: ChatInfoDict,
        *,
        useMarkdown: bool = True,
        addChatId: bool = True,
        addChatType: bool = True,
    ) -> str:
        """
        Get chat title for the given chat info, dood!

        Args:
            chatInfo: Chat info object
            useMarkdown: Whether to use markdown markup (Default: True)
            addChatId: Whether to add chat ID (Default: True)
            addChatType: Whether yo add chat type (private, group, etc...) (Default: True)

        Returns:
            Chat title string
        """
        chatTitle: str = f"#{chatInfo['chat_id']}"
        if chatInfo["title"]:
            chatTitle = chatInfo["title"]
        elif chatInfo["username"]:
            chatTitle = chatInfo["username"]
        if useMarkdown:
            chatTitle = f"**{chatTitle}**"

        if chatInfo["type"] == Chat.PRIVATE:
            chatTitle = f"{constants.PRIVATE_ICON} {chatTitle}"
        else:
            chatTitle = f"{constants.CHAT_ICON} {chatTitle}"
            # TODO: Different icons for other types?

        if addChatType:
            chatTitle = f"{chatTitle} ({chatInfo['type']})"

        if addChatId:
            if useMarkdown:
                chatTitle = f"#`{chatInfo['chat_id']}`, {chatTitle}"
            else:
                chatTitle = f"#{chatInfo['chat_id']} {chatTitle}"
        return chatTitle

    ###
    # Processing media
    ###

    async def _parseImage(
        self,
        ensuredMessage: EnsuredMessage,
        fileUniqueId: str,
        messages: List[ModelMessage],
    ) -> bool:
        """
        Parse image content using LLM to generate description, dood!

        Internal method that sends image to configured LLM model for analysis.
        Updates database with generated description or failure status.

        Args:
            ensuredMessage: Message containing the image
            fileUniqueId: Unique file identifier for database lookup
            messages: List of [`ModelMessage`](lib/ai/models.py) objects for LLM (system prompt + image)

        Returns:
            True if parsing succeeded, False if failed
        """

        chatSettings = self.getChatSettings(ensuredMessage.recipient.id)

        try:
            llmModel = chatSettings[ChatSettingsKey.IMAGE_PARSING_MODEL].toModel(self.llmManager)
            logger.debug(f"Prompting Image {ensuredMessage.mediaId} LLM for image with prompt: {messages[:1]}")
            llmRet = await llmModel.generateText(messages)
            logger.debug(f"Image LLM Response: {llmRet}")

            if llmRet.status != ModelResultStatus.FINAL:
                raise RuntimeError(f"Image LLM Response status is not FINAL: {llmRet.status}")

            description = llmRet.resultText
            self.db.updateMediaAttachment(
                mediaId=fileUniqueId,
                status=MediaStatus.DONE,
                description=description,
            )
            return True

        except Exception as e:
            logger.error(f"Failed to parse image: {e}")
            self.db.updateMediaAttachment(
                mediaId=fileUniqueId,
                status=MediaStatus.FAILED,
            )
            return False

        # ret['content'] = llmRet.resultText

    async def processTelegramSticker(self, ensuredMessage: EnsuredMessage) -> MediaProcessingInfo:
        """
        Process a sticker attachment from message, dood!

        Extracts sticker metadata (dimensions, emoji, animation status)
        and processes it through the media pipeline.

        Args:
            ensuredMessage: Message containing the sticker

        Returns:
            [`MediaProcessingInfo`](internal/bot/models/media.py) with processing task and metadata

        Raises:
            ValueError: If message doesn't contain a sticker
        """
        # TODO: Support Max
        if self.botProvider != BotProvider.TELEGRAM:
            raise RuntimeError("Stickers are supported in Telegram only")
        baseMessage = ensuredMessage.getBaseMessage()
        if not isinstance(baseMessage, telegram.Message):
            raise RuntimeError(f"Base message is not Message, but {type(baseMessage)}")

        sticker = baseMessage.sticker
        if sticker is None:
            raise ValueError("Sticker not found")

        # Sticker(..., emoji='😨', file_id='C...E', file_size=51444, file_unique_id='A...Q',
        # height=512, is_animated=True, is_video=False, set_name='SharkBoss',
        # thumbnail=PhotoSize(...), type=<StickerType.REGULAR>, width=512)

        metadata = {
            "type": sticker.type,
            "emoji": sticker.emoji,
            "width": sticker.width,
            "height": sticker.height,
            "set_name": sticker.set_name,
            "is_animated": sticker.is_animated,
            "is_video": sticker.is_video,
            "is_premium": sticker.premium_animation is not None,
            "file_size": sticker.file_size,
        }

        return await self._processMediaV2(
            ensuredMessage=ensuredMessage,
            mediaType=MessageType.IMAGE,
            mediaId=sticker.file_unique_id,
            fileId=sticker.file_id,
            dataGetter=self._telegramFileDownloader,
            metadata=metadata,
        )

    async def processTelegramImage(
        self, ensuredMessage: EnsuredMessage, prompt: Optional[str] = None
    ) -> MediaProcessingInfo:
        """
        Process a photo attachment from message, dood!

        Selects optimal photo size based on chat settings and processes
        through the media pipeline. May use smaller size for LLM to reduce costs.

        Args:
            ensuredMessage: Message containing the photo
            prompt: Optional custom prompt for image parsing

        Returns:
            [`MediaProcessingInfo`](internal/bot/models/media.py) with processing task and metadata
        """
        # TODO: Support Max
        if self.botProvider != BotProvider.TELEGRAM:
            raise RuntimeError("Stickers are supported in Telegram only")
        baseMessage = ensuredMessage.getBaseMessage()
        if not isinstance(baseMessage, telegram.Message):
            raise RuntimeError(f"Base message is not Message, but {type(baseMessage)}")

        bestPhotoSize = baseMessage.photo[-1]

        metadata = {
            # Store metadata for best size
            "width": bestPhotoSize.width,
            "height": bestPhotoSize.height,
            "file_size": bestPhotoSize.file_size,
        }

        return await self._processMediaV2(
            ensuredMessage=ensuredMessage,
            mediaType=MessageType.IMAGE,
            mediaId=bestPhotoSize.file_unique_id,
            fileId=bestPhotoSize.file_id,
            dataGetter=self._telegramFileDownloader,
            metadata=metadata,
            prompt=prompt,
        )

    async def processMaxMedia(
        self, ensuredMessage: EnsuredMessage, prompt: Optional[str] = None
    ) -> List[MediaProcessingInfo]:
        baseMessage = ensuredMessage.getBaseMessage()
        ret: List[MediaProcessingInfo] = []
        if not isinstance(baseMessage, maxModels.Message):
            logger.error(f"Invalid message type: {type(baseMessage)}")
            return ret

        if not baseMessage.body.attachments:
            # No attachments, skip
            return ret

        for attachment in baseMessage.body.attachments:
            if attachment.type == maxModels.AttachmentType.IMAGE and isinstance(attachment, maxModels.PhotoAttachment):
                url = attachment.payload.url
                mediaId = f"{attachment.type}:{attachment.payload.photo_id}"
                ret.append(
                    await self._processMediaV2(
                        ensuredMessage=ensuredMessage,
                        mediaType=MessageType.IMAGE,
                        mediaId=mediaId,
                        fileId=url,
                        dataGetter=self._maxFileDownloader,
                        prompt=prompt,
                        metadata={
                            "token": attachment.payload.token,
                        },
                    )
                )

            elif attachment.type == maxModels.AttachmentType.STICKER and isinstance(
                attachment, maxModels.StickerAttachment
            ):
                url = attachment.payload.url
                mediaId = f"{attachment.type}:{attachment.payload.code}"
                ret.append(
                    await self._processMediaV2(
                        ensuredMessage=ensuredMessage,
                        mediaType=MessageType.STICKER,
                        mediaId=mediaId,
                        fileId=url,
                        dataGetter=self._maxFileDownloader,
                        prompt=prompt,
                        metadata={
                            "wifth": attachment.width,
                            "height": attachment.height,
                        },
                    )
                )
            else:
                logger.warning(f"Unsupported attachment type: {attachment.type}:{type(attachment).__name__}")

        return ret

    async def _maxFileDownloader(self, mediaId: str, fileId: str) -> Optional[bytes]:
        """TODO
        fileId is URL"""

        if self.botProvider != BotProvider.MAX or self._maxBot is None:
            logger.error(f"_maxFileDownloader({mediaId}, {fileId}) called while platform is {self.botProvider}")
            return None

        return await self._maxBot.downloadAttachmentPayload(fileId)

    async def _telegramFileDownloader(self, mediaId: str, fileId: str) -> Optional[bytes]:
        """TODO
        fileId is file_id"""

        if self.botProvider != BotProvider.TELEGRAM or self._tgBot is None:
            logger.error(f"_telegramFileDownloader({mediaId}, {fileId}) called while platform is {self.botProvider}")
            return None

        fileInfo = await self._tgBot.get_file(fileId)
        logger.debug(f"{mediaId}#{fileId} File info: {fileInfo}")
        return bytes(await fileInfo.download_as_bytearray())

    async def _processMediaV2(
        self,
        ensuredMessage: EnsuredMessage,
        mediaType: MessageType,
        mediaId: str,
        fileId: str,
        dataGetter: Callable[[str, str], Awaitable[Optional[bytes]]],  # async fn(mediaId, fileId) -> bytes
        metadata: Optional[Dict[str, Any]] = None,
        prompt: Optional[str] = None,
    ) -> MediaProcessingInfo:
        """TODO"""
        ret = MediaProcessingInfo(
            id=mediaId,
            task=None,
            type=mediaType,
        )
        localUrl: Optional[str] = None  # To be filled with downloaded media URL
        mimeType: Optional[str] = None  # To be filled with downloaded media MIME type

        logger.debug(f"Processing media {ret.type}#{ret.id} with fileId:{fileId}...")
        # First check if we have the photo in the database already
        mediaAttachment = self.db.getMediaAttachment(ret.id)
        hasMediaAttachment = mediaAttachment is not None
        if mediaAttachment is not None:
            logger.debug(f"Media#{ret.id} already in database")
            if mediaAttachment["media_type"] != mediaType:
                raise RuntimeError(
                    f"Media#{ret.id} already present in database and it is not an "
                    f"{mediaType} but {mediaAttachment['media_type']}"
                )

            # Only skip processing if Media in DB is in right status
            match MediaStatus(mediaAttachment["status"]):
                case MediaStatus.DONE:
                    ret.task = makeEmptyAsyncTask()
                    return ret

                case MediaStatus.PENDING:
                    try:
                        mediaDate = mediaAttachment["updated_at"]
                        if not isinstance(mediaDate, datetime.datetime):
                            logger.error(
                                f"{ret.type}#{ret.id} `updated_at` is not a datetime: "
                                f"{type(mediaDate).__name__}({mediaDate})"
                            )
                            mediaDate = datetime.datetime.fromisoformat(mediaDate)

                        if utils.getAgeInSecs(mediaDate) > constants.PROCESSING_TIMEOUT:
                            logger.warning(
                                f"{ret.type}#{ret.id} already in database but in status "
                                f"{mediaAttachment['status']} and is too old ({mediaDate}), reprocessing it"
                            )
                        else:
                            ret.task = makeEmptyAsyncTask()
                            return ret
                    except Exception as e:
                        logger.error("{ret.type}#{ret.id} Error during checking age:")
                        logger.exception(e)

                case _:
                    mimeType = str(mediaAttachment["mime_type"])
                    # NOTE: Currently we can process only images
                    if mimeType.lower().startswith("image/"):
                        logger.debug(
                            f"{ret.type}#{ret.id} in wrong status: {mediaAttachment['status']}. Reprocessing it"
                        )
                    else:
                        logger.debug(f"{ret.type}#{ret.id} is {mimeType}, skipping it")
                        ret.task = makeEmptyAsyncTask()
                        return ret

        chatSettings = self.getChatSettings(ensuredMessage.recipient.id)
        mediaData: Optional[bytes] = None

        if chatSettings[ChatSettingsKey.SAVE_IMAGES].toBool():
            # TODO do someday. Or not
            pass

        if chatSettings[ChatSettingsKey.PARSE_IMAGES].toBool():
            mediaStatus = MediaStatus.PENDING
        else:
            mediaStatus = MediaStatus.DONE

        if hasMediaAttachment:
            self.db.updateMediaAttachment(
                mediaId=ret.id,
                status=mediaStatus,
                metadata=utils.jsonDumps(metadata),
                mimeType=mimeType,
                localUrl=localUrl,
                prompt=prompt,
            )
        else:
            self.db.addMediaAttachment(
                fileUniqueId=ret.id,
                fileId=fileId,
                mediaType=mediaType,
                mimeType=mimeType,
                metadata=utils.jsonDumps(metadata),
                status=mediaStatus,
                localUrl=localUrl,
                prompt=prompt,
                fileSize=None,
                description=None,
            )

        # Need to parse image content with LLM
        if chatSettings[ChatSettingsKey.PARSE_IMAGES].toBool():
            # Do not redownload file if it was downloaded already
            if mediaData is None:
                mediaData = await dataGetter(mediaId, fileId)

            if mediaData is None:
                logger.error(f"{ret.type}#{ret.id} is None, cannot parse it")
                self.db.updateMediaAttachment(
                    mediaId=ret.id,
                    status=MediaStatus.FAILED,
                )
                ret.task = makeEmptyAsyncTask()
                return ret

            mimeType = magic.from_buffer(mediaData, mime=True)
            logger.debug(f"{ret.type}#{ret.id} Mimetype: {mimeType}")

            self.db.updateMediaAttachment(
                mediaId=ret.id,
                mimeType=mimeType,
                fileSize=len(mediaData),
            )

            if mimeType.lower().startswith("image/"):
                logger.debug(f"{ret.type}#{ret.id} is an image")
            else:
                logger.warning(f"{ret.type}#{ret.id} is not an image, skipping parsing")
                ret.task = makeEmptyAsyncTask()
                self.db.updateMediaAttachment(
                    mediaId=ret.id,
                    status=MediaStatus.NEW,
                )
                return ret

            imagePrompt = chatSettings[ChatSettingsKey.PARSE_IMAGE_PROMPT].toStr()
            messages = [
                ModelMessage(
                    role="system",
                    content=imagePrompt,
                ),
                ModelImageMessage(
                    role="user",
                    content=ensuredMessage.messageText,
                    image=bytearray(mediaData),
                ),
            ]

            logger.debug(f"{mediaType}#{ret.id}: Asynchronously parsing image")
            parseTask = asyncio.create_task(self._parseImage(ensuredMessage, ret.id, messages))
            # logger.debug(f"{mediaType}#{ret.id} After Start")
            ret.task = parseTask
            await self.queueService.addBackgroundTask(parseTask)
            # logger.debug(f"{mediaType}#{ret.id} After Queued")

        if ret.task is None:
            ret.task = makeEmptyAsyncTask()

        return ret

    ###
    # Base methods for processing Telegram events
    ###

    async def newMessageHandler(
        self,
        ensuredMessage: EnsuredMessage,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        # By default, skip processing
        return HandlerResultStatus.SKIPPED

    async def callbackHandler(
        self,
        ensuredMessage: EnsuredMessage,
        data: utils.PayloadDict,
        user: MessageSender,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        # By default, skip processing
        return HandlerResultStatus.SKIPPED
