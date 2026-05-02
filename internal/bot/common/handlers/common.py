"""
Common bot commands handler module, dood!

This module contains the CommonHandler class which provides base bot functionality including:
- Basic bot commands (/start, /remind, /list_chats)
- LLM tool-calling handlers for URL content fetching and datetime retrieval
- Delayed queue task handlers for message scheduling and deletion
- Message helper utilities for delayed message sending

The handlers in this module are fundamental to the bot's operation and are used
across different chat contexts (private, group, supergroup).
"""

import datetime
import logging
import time
from typing import Any, Dict, Optional

import lib.utils as utils
from internal.bot.common.models import UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    ChatType,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
    commandHandlerV2,
)
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.models import MessageCategory
from internal.services.llm import LLMService
from internal.services.queue_service import DelayedTask, DelayedTaskFunction
from lib.ai import LLMManager

from .base import BaseBotHandler

logger = logging.getLogger(__name__)


class CommonHandler(BaseBotHandler):
    """
    Common bot handler class providing core bot functionality, dood!

    This handler class manages:
    - Basic user commands (/start, /remind, /list_chats)
    - LLM tool integrations (URL content fetching, datetime retrieval)
    - Delayed task queue handlers (message scheduling, message deletion)
    - Message helper utilities for delayed operations

    Attributes:
        llmService: LLM service instance for tool registration and management
    """

    def __init__(
        self, configManager: ConfigManager, database: Database, llmManager: LLMManager, botProvider: BotProvider
    ):
        """
        Initialize the CommonHandler with required services, dood!

        Sets up the handler by:
        1. Initializing the base handler with config, database, and LLM manager
        2. Registering LLM tools (get_url_content, get_current_datetime)
        3. Registering delayed queue task handlers (send_message, delete_message)

        Args:
            configManager: Configuration manager instance for accessing bot settings
            database: Database wrapper instance for data persistence
            llmManager: LLM manager instance for AI model interactions
        """
        # Initialize the mixin (discovers handlers)
        super().__init__(configManager=configManager, database=database, llmManager=llmManager, botProvider=botProvider)

        self.llmService = LLMService.getInstance()

        self.llmService.registerTool(
            name="get_current_datetime",
            description="Get current date and time",
            parameters=[],
            handler=self._llmToolGetCurrentDateTime,
        )

        self.queueService.registerDelayedTaskHandler(
            DelayedTaskFunction.SEND_MESSAGE,
            self._dqSendMessageHandler,
        )
        self.queueService.registerDelayedTaskHandler(
            DelayedTaskFunction.DELETE_MESSAGE,
            self._dqDeleteMessageHandler,
        )

    ###
    # Delayed Queue Handlers
    ###
    async def _dqSendMessageHandler(self, delayedTask: DelayedTask) -> None:
        """
        Handle delayed message sending from the queue, dood!

        This handler is triggered when a delayed SEND_MESSAGE task is ready for execution.
        It reconstructs the message context from the task kwargs and sends the message
        to the specified chat/thread.

        Args:
            delayedTask: The delayed task containing message details in kwargs:
                - messageId: Original message ID
                - chatId: Target chat ID
                - chatType: Type of chat (private, group, supergroup)
                - userId: User ID who initiated the delayed message
                - messageText: Text content to send
                - threadId: Thread ID for topic-based chats (optional)
                - messageCategory: Category of the message for tracking

        Returns:
            None
        """
        kwargs = delayedTask.kwargs

        ensuredMessage = EnsuredMessage(
            sender=MessageSender(id=kwargs["userId"], name="", username=""),
            recipient=MessageRecipient(id=kwargs["chatId"], chatType=ChatType(kwargs["chatType"])),
            messageId=kwargs["messageId"],
            date=datetime.datetime.now(),
            messageText=kwargs["messageText"],
        )
        ensuredMessage.threadId = kwargs["threadId"]

        await self.sendMessage(
            replyToMessage=ensuredMessage,
            messageText=kwargs["messageText"],
            messageCategory=kwargs["messageCategory"],
        )

    async def _dqDeleteMessageHandler(self, delayedTask: DelayedTask) -> None:
        """
        Handle delayed message deletion from the queue, dood!

        This handler is triggered when a delayed DELETE_MESSAGE task is ready for execution.
        It attempts to delete the specified message from the chat using the bot API.

        Args:
            delayedTask: The delayed task containing deletion details in kwargs:
                - chatId: Chat ID where the message is located
                - messageId: ID of the message to delete

        Returns:
            None

        Note:
            If the bot is not initialized, logs an error instead of attempting deletion.
        """
        kwargs = delayedTask.kwargs
        messageCategory = kwargs.get("messageCategory", None)
        try:
            if messageCategory is not None:
                messageCategory = MessageCategory(messageCategory)
        except ValueError:
            messageCategory = None
            logger.error(f"Invalid message category: {messageCategory}")

        await self.deleteMessagesById(
            chatId=kwargs["chatId"], messageIds=[kwargs["messageId"]], setMessageCategory=messageCategory
        )

    ###
    # LLM Tool-Calling handlers
    ###

    async def _llmToolGetCurrentDateTime(self, extraData: Optional[Dict[str, Any]], **kwargs) -> str:
        """
        LLM tool handler to get current date and time, dood!

        This tool is registered with the LLM service and can be called by AI models
        to retrieve the current datetime during conversations. Returns datetime in
        multiple formats for flexibility.

        Args:
            extraData: Optional extra data passed by the LLM service (unused)
            **kwargs: Additional keyword arguments (unused)

        Returns:
            str: JSON string containing:
                - datetime: ISO 8601 formatted datetime string
                - timestamp: Unix timestamp (float)
                - timezone: Timezone identifier (always "UTC")
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        return utils.jsonDumps({"datetime": now.isoformat(), "timestamp": now.timestamp(), "timezone": "UTC"})

    ###
    # Some message helpers
    ###
    async def _sendDelayedMessage(
        self,
        ensuredMessage: EnsuredMessage,
        delayedUntil: float,
        messageText: str,
        messageCategory: MessageCategory = MessageCategory.BOT,
    ) -> None:
        """
        Schedule a message to be sent after a specified delay, dood!

        This helper method creates a delayed task in the queue service that will
        trigger the _dqSendMessageHandler when the delay expires. The message will
        be sent to the same chat/thread as the original message.

        Args:
            ensuredMessage: The original message context (chat, user, thread info)
            delayedUntil: Unix timestamp when the message should be sent
            messageText: The text content to send in the delayed message
            messageCategory: Category for message tracking (default: MessageCategory.BOT)

        Returns:
            None
        """

        functionName = DelayedTaskFunction.SEND_MESSAGE
        kwargs = {
            "messageText": messageText,
            "messageCategory": messageCategory,
            "messageId": ensuredMessage.messageId,
            "threadId": ensuredMessage.threadId,
            "chatId": ensuredMessage.recipient.id,
            "userId": ensuredMessage.sender.id,
            "chatType": ensuredMessage.recipient.chatType,
        }

        return await self.queueService.addDelayedTask(delayedUntil=delayedUntil, function=functionName, kwargs=kwargs)

    ###
    # COMMANDS Handlers
    ###

    @commandHandlerV2(
        commands=("start",),
        shortDescription="Start bot interaction",
        helpMessage=": Начать работу с ботом.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE},
        helpOrder=CommandHandlerOrder.FIRST,
        category=CommandCategory.PRIVATE,
    )
    async def start_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """
        Handle the /start command to welcome new users, dood!

        This command is typically triggered when a user first interacts with the bot
        in a private chat. It sends a welcome message introducing the bot and
        suggesting the /help command for more information.

        Args:
            update: Telegram update object containing the message
            context: Telegram context object with command arguments and bot data

        Returns:
            None

        Note:
            Only works in private chats (enforced by CommandCategory.PRIVATE).
            Logs user interaction for monitoring purposes.
        """
        sender = ensuredMessage.sender
        await self.sendMessage(
            ensuredMessage,
            f"Привет! {sender.name}! 👋\n\n"
            "Я Громозека: лучший бот для Телеграма, что когда либо был, есть или будет.\n\n"
            "Что бы узнать, что я умею, можешь отправить команду /help",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
        logger.info(f"User {sender} started the bot")

    @commandHandlerV2(
        commands=("remind",),
        shortDescription="<delay> [<message>] - Remind me after given delay with message or replied message/quote",
        helpMessage=" `<DDdHHhMMmSSs|HH:MM[:SS]>`: напомнить указанный текст через указанное время "
        "(можно использовать цитирование или ответ на сообщение).",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def remind_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """
        Handle the /remind command to schedule reminder messages, dood!

        This command allows users to schedule a reminder message to be sent after
        a specified delay. The reminder text can be provided as:
        1. Additional arguments after the delay
        2. Quoted text from another message
        3. Replied-to message text
        4. Default reminder text if none provided

        Time format supports:
        - Duration format: DDdHHhMMmSSs (e.g., 1d2h30m for 1 day, 2 hours, 30 minutes)
        - Time format: HH:MM[:SS] (e.g., 14:30 or 14:30:00)

        Args:
            update: Telegram update object containing the message
            context: Telegram context object with command arguments:
                - args[0]: Required delay/time specification
                - args[1:]: Optional reminder text

        Returns:
            None

        Note:
            Saves the command message to database for tracking.
            Sends confirmation message with scheduled time in UTC.
        """

        delaySecs: int = 0
        argList = args.split(maxsplit=1)
        try:
            if not args:
                raise ValueError("No time specified")
            delayStr = argList[0]
            delaySecs = utils.parseDelay(delayStr)
        except Exception as e:
            await self.sendMessage(
                ensuredMessage,
                messageText=(
                    "Для команды `/remind` нужно указать время, через которое отправить "
                    "напоминание в одном из форматов:\n"
                    "1. `DDdHHhMMmSSs`\n"
                    "2. `HH:MM[:SS]`\n"
                ),
                messageCategory=MessageCategory.BOT_ERROR,
            )
            logger.error(f"Error while handling /remind command: {type(e).__name__}{e}")
            logger.exception(e)
            return

        reminderText: Optional[str] = None
        if len(argList) > 1:
            reminderText = argList[1]

        if reminderText is None and ensuredMessage.quoteText:
            reminderText = ensuredMessage.quoteText

        if reminderText is None and ensuredMessage.replyText:
            reminderText = ensuredMessage.replyText

        if reminderText is None:
            reminderText = "⏰ Напоминание"

        delayedTime = time.time() + delaySecs
        await self._sendDelayedMessage(
            ensuredMessage,
            delayedUntil=delayedTime,
            messageText=reminderText,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

        delayedDT = datetime.datetime.fromtimestamp(delayedTime, tz=datetime.timezone.utc)

        await self.sendMessage(
            ensuredMessage,
            messageText=f"Напомню в {delayedDT.strftime('%Y-%m-%d %H:%M:%S%z')}",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandlerV2(
        commands=("list_chats",),
        shortDescription="[all] - List chats, where bot seen you",
        helpMessage=": Вывести список чатов, где бот вас видел.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE},
        helpOrder=CommandHandlerOrder.TECHNICAL,
        category=CommandCategory.PRIVATE,
    )
    async def list_chats_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """
        Handle the /list_chats command to display known chats, dood!

        This command shows a list of chats where the bot has seen the user.
        By default, shows only chats where the requesting user is a member.
        Admin users can use the 'all' parameter to see all chats known to the bot.

        Args:
            update: Telegram update object containing the message
            context: Telegram context object with optional arguments:
                - args[0]: Optional 'all' flag to list all chats (admin only)

        Returns:
            None

        Note:
            Only works in private chats (enforced by CommandCategory.PRIVATE).
            The 'all' parameter requires admin privileges.
            Chat information includes ID, title/username, and type.
        """
        listAll = args.strip().lower().startswith("all")

        if listAll:
            listAll = self.isBotOwner(ensuredMessage.sender)

        knownChats = (
            await self.db.chatUsers.getAllGroupChats() if listAll else await self.getUserChats(ensuredMessage.sender.id)
        )

        resp = "Список доступных чатов:\n\n"

        for chat in knownChats:
            chatTitle = self.getChatTitle(chat)
            resp += f"* {chatTitle}\n"

        await self.sendMessage(ensuredMessage, resp, messageCategory=MessageCategory.BOT_COMMAND_REPLY)
