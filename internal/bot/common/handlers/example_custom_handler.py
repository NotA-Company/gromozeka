"""
Example custom handler for Gromozeka bot, dood!

This module demonstrates how to create a custom handler that extends BaseBotHandler.
It can be used as a template for creating new custom handlers or for testing the
custom handler loading system.
"""

import logging
from typing import Optional

from internal.bot.common.models import UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    commandHandlerV2,
)
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.models import MessageCategory
from lib.ai import LLMManager

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class ExampleCustomHandler(BaseBotHandler):
    """
    Example custom handler demonstrating the custom handler pattern, dood!

    This handler provides a simple /custom_hello command and logs all messages
    it processes. It's intended as a reference implementation for creating
    custom handlers that extend the bot's functionality.

    Attributes:
        configManager: Configuration manager instance
        database: Database wrapper for persistence
        llmManager: LLM manager for AI features
        botProvider: Bot provider type
    """

    def __init__(
        self,
        configManager: ConfigManager,
        database: Database,
        llmManager: LLMManager,
        botProvider: BotProvider,
    ):
        """
        Initialize the example custom handler, dood!

        Args:
            configManager: Configuration manager providing bot settings
            database: Database wrapper for data persistence
            llmManager: LLM manager for AI model operations
            botProvider: Bot provider type (Telegram/Max)
        """
        super().__init__(
            configManager=configManager,
            database=database,
            llmManager=llmManager,
            botProvider=botProvider,
        )
        logger.info("ExampleCustomHandler initialized, dood!")

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """
        Process incoming messages, dood!

        This handler logs all messages it sees but skips processing them,
        allowing other handlers in the chain to process the message.

        Args:
            ensuredMessage: The incoming message
            updateObj: Raw update object from platform

        Returns:
            HandlerResultStatus.SKIPPED always - allows other handlers to process
        """
        logger.debug(
            f"ExampleCustomHandler saw message from {ensuredMessage.sender.name} "
            f"in chat {ensuredMessage.recipient.id}"
        )
        return HandlerResultStatus.SKIPPED

    @commandHandlerV2(
        commands=("custom_hello",),
        shortDescription="- say hello from custom module",
        helpMessage="Sends a friendly greeting from the custom handler module, dood!",
        visibility={CommandPermission.DEFAULT},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def customHelloCommand(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        updateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """
        Handle /custom_hello command, dood!

        Sends a friendly greeting message demonstrating that the custom
        handler is working correctly.

        Args:
            ensuredMessage: The command message
            command: Command name
            args: Command arguments (optional name to greet)
            updateObj: Raw update object
            typingManager: Optional typing indicator manager
        """
        name = args.strip() if args.strip() else ensuredMessage.sender.name

        await self.sendMessage(
            ensuredMessage,
            messageText=f"Hello from custom module, **{name}**! 👋\n\nThis is a custom handler, dood!",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
        logger.info(f"ExampleCustomHandler responded to /custom_hello from {ensuredMessage.sender.name}")
