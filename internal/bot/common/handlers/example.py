"""
Gromozeka Example Handler Module, dood!

This module contains the ExampleHandler class which demonstrates basic bot handler functionality
including message handling, button callbacks, command processing, and integration with
queue services and LLM tools.
"""

import logging
from typing import Any, Dict, Optional

import lib.utils as utils
from internal.bot.common.models import UpdateObjectType
from internal.bot.models import (
    BotProvider,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    DelayedTaskFunction,
    EnsuredMessage,
    MessageSender,
    commandHandlerV2,
)
from internal.config.manager import ConfigManager
from internal.database.models import MessageCategory
from internal.database.wrapper import DatabaseWrapper
from internal.services.llm.service import LLMService
from internal.services.queue_service.service import QueueService
from internal.services.queue_service.types import DelayedTask
from lib.ai import LLMFunctionParameter, LLMManager, LLMParameterType

from .base import BaseBotHandler, HandlerResultStatus, TypingManager

logger = logging.getLogger(__name__)


class ExampleHandler(BaseBotHandler):
    """
    Example bot handler demonstrating basic functionality, dood!

    This handler showcases message processing, button callbacks, command handling,
    and integration with queue services and LLM tools. It serves as a reference
    implementation for other bot handlers.
    """

    def __init__(
        self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager, botProvider: BotProvider
    ):
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
        super().__init__(configManager=configManager, database=database, llmManager=llmManager, botProvider=botProvider)

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

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """
        TODO
        """

        # Do something with the message
        return HandlerResultStatus.SKIPPED

    ###
    # Handling Click on buttons
    ###
    async def callbackHandler(
        self,
        ensuredMessage: EnsuredMessage,
        data: utils.PayloadDict,
        user: MessageSender,
        updateObj: UpdateObjectType,
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

        return HandlerResultStatus.SKIPPED

    ###
    # Command Handlers
    ###

    @commandHandlerV2(
        commands=("example",),
        shortDescription="- example command",
        helpMessage=" Пример команды.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE},
        helpOrder=CommandHandlerOrder.TEST,
        category=CommandCategory.TECHNICAL,
    )
    async def example_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """
        TODO
        """

        # Send message to user (also save it to db, try to parse as Markdown2 and so on)
        await self.sendMessage(
            ensuredMessage,
            messageText="Hello, **dood**!",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
