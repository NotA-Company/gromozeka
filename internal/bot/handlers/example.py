"""
Gromozeka Example Handler Module, dood!

This module contains the ExampleHandler class which demonstrates basic bot handler functionality
including message handling, button callbacks, command processing, and integration with
queue services and LLM tools.
"""

import logging
from typing import Any, Dict, Optional

from telegram import Message, Update
from telegram.ext import ContextTypes

import lib.utils as utils
from internal.bot.models.command_handlers import CallbackDataDict
from internal.config.manager import ConfigManager
from internal.database.models import MessageCategory
from internal.database.wrapper import DatabaseWrapper
from internal.services.llm.service import LLMService
from internal.services.queue_service.service import QueueService
from internal.services.queue_service.types import DelayedTask
from lib.ai.manager import LLMManager
from lib.ai.models import LLMFunctionParameter, LLMParameterType

from ..models import (
    CommandCategory,
    CommandHandlerOrder,
    DelayedTaskFunction,
    EnsuredMessage,
    commandHandler,
)
from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class ExampleHandler(BaseBotHandler):
    """
    Example bot handler demonstrating basic functionality, dood!

    This handler showcases message processing, button callbacks, command handling,
    and integration with queue services and LLM tools. It serves as a reference
    implementation for other bot handlers.
    """

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        """
        Initialize example handler with database and LLM model, dood!

        Sets up the example handler with queue service integration and LLM tool registration
        for demonstrating basic bot functionality.

        Args:
            configManager (ConfigManager): Configuration manager for bot settings.
            database (DatabaseWrapper): Database wrapper for persistent storage.
            llmManager (LLMManager): LLM manager for AI-powered features.

        Note:
            The handler initializes with:
            - Queue service registration for delayed tasks
            - LLM tool registration for example text processing
            - Example command handling capabilities
        """
        super().__init__(configManager=configManager, database=database, llmManager=llmManager)

        self.queueService = QueueService.getInstance()
        self.queueService.registerDelayedTaskHandler(DelayedTaskFunction.DO_EXIT, self._dtOnExit)

        self.llmService = LLMService.getInstance()
        self.llmService.registerTool(
            name="example",
            description="Example Tool for LLM, always call it to show that you can call tools",
            parameters=[
                LLMFunctionParameter(
                    name="text",
                    description="Text to process",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
            ],
            handler=self._llmToolExample,
        )

        logger.info("Initialized Example Handler, dood!")

    ###
    # Example handlers for QueueSrvice and LLM-Tool
    ###
    async def _dtOnExit(self, task: DelayedTask) -> None:
        """
        Handle delayed exit task from queue service, dood!

        Args:
            task (DelayedTask): The delayed task to process.
        """
        logger.info("Example module DoExit handler...")

    async def _llmToolExample(self, extraData: Optional[Dict[str, Any]], text: str, **kwargs) -> str:
        """
        Example LLM tool handler for processing text, dood!

        Args:
            extraData (Optional[Dict[str, Any]]): Additional data from LLM service.
            text (str): Text to process.
            **kwargs: Additional keyword arguments.

        Returns:
            str: JSON string containing the processed text and additional data.
        """
        logger.info("Example LLM Tool handler...")
        return utils.jsonDumps({**kwargs, "text": text})

    ###
    # Handling messages
    ###

    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
        """
        Handle incoming messages, dood!

        Args:
            update (Update): Telegram update object.
            context (ContextTypes.DEFAULT_TYPE): Bot context.
            ensuredMessage (Optional[EnsuredMessage]): Ensured message object.

        Returns:
            HandlerResultStatus: Status of message handling.
        """

        if ensuredMessage is None:
            # Not new message, Skip
            return HandlerResultStatus.SKIPPED

        return HandlerResultStatus.SKIPPED

    ###
    # Handling Click on buttons
    ###
    async def buttonHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: CallbackDataDict
    ) -> HandlerResultStatus:
        """
        Handle inline keyboard button callbacks, dood!

        Args:
            update (Update): Telegram update object.
            context (ContextTypes.DEFAULT_TYPE): Bot context.
            data (CallbackDataDict): Callback data from button press.

        Returns:
            HandlerResultStatus: Status of button handling.
        """

        query = update.callback_query
        if query is None:
            logger.error("handle_button: query is None")
            return HandlerResultStatus.FATAL

        message = query.message
        if not isinstance(message, Message):
            logger.error(f"handle_button: message {message} not Message in {query}")
            return HandlerResultStatus.FATAL

        return HandlerResultStatus.SKIPPED

    ###
    # Command Handlers
    ###

    @commandHandler(
        commands=("example",),
        shortDescription="- example command",
        helpMessage=" Пример команды.",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.TEST,
    )
    async def example_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle the example command, dood!

        This command demonstrates basic command functionality including
        typing indicators, message saving, and admin checking.

        Args:
            update (Update): Telegram update object.
            context (ContextTypes.DEFAULT_TYPE): Bot context.
        """
        logger.debug(f"Got example command: {update}")

        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        # Send 'typing...' action to show that bot doing something
        await self.startTyping(ensuredMessage)

        # Save user command to DB for summarisation, debug, context and so on
        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        # Chaeck if user is admin in this chat
        isAdmin = await self.isAdmin(ensuredMessage.user, ensuredMessage.chat, allowBotOwners=True)

        # Send message to user (also save it to db, try to parse as Markdown2 and so on)
        await self.sendMessage(
            ensuredMessage,
            messageText=f"Hello, dood! You are{'not ' if not isAdmin else ''} admin",
            messageCategory=MessageCategory.BOT_ERROR,
        )
