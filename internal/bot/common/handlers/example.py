"""Example handler module for Gromozeka bot.

This module provides the ExampleHandler class which demonstrates basic bot handler functionality
including message handling, button callbacks, command processing, and integration with
queue services and LLM tools. It serves as a reference implementation for creating custom bot handlers.

The module demonstrates:
- Message processing and handling
- Inline keyboard button callback handling
- Command registration and processing
- Queue service integration for delayed tasks
- LLM tool registration and handling
- Integration with bot infrastructure components
"""

import logging
from typing import Any, Dict, Optional

import lib.utils as utils
from internal.bot.common.models import UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    MessageSender,
    commandHandlerV2,
)
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.models import MessageCategory
from internal.services.llm import LLMService
from internal.services.queue_service import DelayedTask, DelayedTaskFunction, QueueService
from lib.ai import LLMFunctionParameter, LLMParameterType

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class ExampleHandler(BaseBotHandler):
    """Example bot handler demonstrating basic functionality.

    This handler showcases message processing, button callbacks, command handling,
    and integration with queue services and LLM tools. It serves as a reference
    implementation for other bot handlers.

    Attributes:
        queueService: Queue service instance for managing delayed tasks.
        llmService: LLM service instance for AI-powered features.
    """

    def __init__(
        self,
        *,
        configManager: ConfigManager,
        database: Database,
        botProvider: BotProvider,
    ) -> None:
        """Initialize example handler with database and LLM model.

        Sets up the example handler with queue service integration and LLM tool registration
        for demonstrating basic bot functionality.

        Args:
            configManager: Configuration manager for bot settings.
            database: Database object for persistent storage.
            botProvider: Bot provider instance for platform-specific operations.

        Note:
            The handler initializes with:
            - Queue service registration for delayed tasks
            - LLM tool registration for example text processing
            - Example command handling capabilities
        """
        super().__init__(configManager=configManager, database=database, botProvider=botProvider)

        self.queueService: QueueService = QueueService.getInstance()
        self.queueService.registerDelayedTaskHandler(DelayedTaskFunction.DO_EXIT, self._dtOnExit)

        self.llmService: LLMService = LLMService.getInstance()
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
        """Handle delayed exit task from queue service.

        This method is called when a delayed task with type DO_EXIT is processed
        by the queue service. It demonstrates how to handle delayed tasks.

        Args:
            task: The delayed task to process.
        """
        logger.info("Example module DoExit handler...")

    async def _llmToolExample(self, extraData: Optional[Dict[str, Any]], text: str, **kwargs: Any) -> str:
        """Example LLM tool handler for processing text.

        This method demonstrates how to create an LLM tool that can be called
        by the AI model. It processes the input text and returns a JSON response.

        Args:
            extraData: Additional data from LLM service (optional).
            text: Text to process.
            **kwargs: Additional keyword arguments from the LLM call.

        Returns:
            JSON string containing the processed text and additional data.
        """
        logger.info("Example LLM Tool handler...")
        return utils.jsonDumps({**kwargs, "text": text})

    ###
    # Handling messages
    ###

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """Handle new incoming messages.

        This method is called for every new message received by the bot.
        Override this method to implement custom message processing logic.

        Args:
            ensuredMessage: The ensured message object containing message data.
            updateObj: The raw update object from the bot platform.

        Returns:
            Status indicating whether the message was processed successfully,
            should be skipped, or requires further processing by other handlers.
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
        """Handle inline keyboard button callbacks.

        This method is called when a user clicks on an inline keyboard button.
        Override this method to implement custom button click handling logic.

        Args:
            ensuredMessage: The ensured message object containing message data.
            data: Callback data from the button press (parsed payload dictionary).
            user: The user who clicked the button.
            updateObj: The raw update object from the bot platform.

        Returns:
            Status indicating whether the callback was processed successfully,
            should be skipped, or requires further processing by other handlers.
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
        updateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the /example command.

        This command demonstrates basic command handling functionality.
        It sends a simple greeting message to the user with MarkdownV2 formatting.

        Args:
            ensuredMessage: The ensured message object containing message data.
            command: The command that was triggered (e.g., "example").
            args: Arguments passed to the command (empty string if none).
            updateObj: The raw update object from the bot platform.
            typingManager: Optional typing manager for showing typing indicators.
        """
        # Send message to user (also save it to db, try to parse as Markdown2 and so on)
        await self.sendMessage(
            ensuredMessage,
            messageText="Hello, **dood**!",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
