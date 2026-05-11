"""Example custom handler for Gromozeka bot.

This module demonstrates how to create a custom handler that extends BaseBotHandler.
It serves as a reference implementation and template for creating new custom handlers
that extend the bot's functionality. The handler includes a simple command and message
processing logic that can be adapted for various use cases.

Key Features:
    - Demonstrates custom handler pattern implementation
    - Shows how to register custom commands
    - Provides example of message processing in handler chain
    - Includes proper integration with bot infrastructure

Usage:
    This handler can be loaded dynamically by the bot's handler loading system
    or used as a template for creating new custom handlers. Copy this file and
    modify the command handlers and message processing logic as needed.
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

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class ExampleCustomHandler(BaseBotHandler):
    """Example custom handler demonstrating the custom handler pattern.

    This handler extends BaseBotHandler to demonstrate how to create custom
    bot handlers that integrate with the Gromozeka bot infrastructure. It
    provides a simple /custom_hello command and logs all messages it processes
    without interfering with the handler chain.

    The handler is designed to be a reference implementation and template for
    creating new custom handlers. It shows proper integration with configuration,
    database, LLM services, and the bot provider system.

    Key Behaviors:
        - Logs all incoming messages for debugging purposes
        - Returns SKIPPED status to allow other handlers to process messages
        - Provides a custom command that demonstrates handler functionality
        - Integrates with the bot's command registration system

    Attributes:
        configManager: Configuration manager providing bot settings and
            configuration values.
        database: Database wrapper for data persistence and repository access.
        botProvider: Bot provider type (Telegram or Max) indicating the
            messaging platform.

    Example:
        To create a new custom handler, copy this file and modify the
        command handlers and message processing logic:

        ```python
        class MyCustomHandler(BaseBotHandler):
            def __init__(self, configManager, database, botProvider):
                super().__init__(configManager, database, botProvider)
                # Your initialization code here

            async def newMessageHandler(self, ensuredMessage, updateObj):
                # Your message processing logic here
                return HandlerResultStatus.SKIPPED
        ```
    """

    def __init__(
        self,
        *,
        configManager: ConfigManager,
        database: Database,
        botProvider: BotProvider,
    ):
        """Initialize the example custom handler.

        Sets up the handler with all required dependencies for bot operation.
        Calls the parent class initialization to ensure proper integration with
        the bot infrastructure.

        Args:
            configManager: Configuration manager providing bot settings and
                configuration values. Used to access bot-specific configuration
                options and feature flags.
            database: Database wrapper for data persistence. Provides access to
                repositories for storing and retrieving chat data, user information,
                and other persistent data.
            botProvider: Bot provider type indicating the messaging platform
                (Telegram or Max). Used to determine platform-specific behavior
                and API interactions.
        """
        super().__init__(
            configManager=configManager,
            database=database,
            botProvider=botProvider,
        )
        logger.info("ExampleCustomHandler initialized, dood!")

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """Process incoming messages in the handler chain.

        This method is called for every incoming message that the bot receives.
        It logs the message details for debugging and monitoring purposes but
        does not perform any actual processing. By returning SKIPPED status,
        it allows other handlers in the chain to process the message.

        This pattern is useful for:
            - Debugging and monitoring message flow
            - Logging message statistics
            - Testing handler chain behavior
            - Observing message patterns without interference

        Args:
            ensuredMessage: The incoming message with guaranteed structure.
                Contains sender information, recipient details, message content,
                and metadata. The message has been validated and normalized by
                the bot infrastructure.
            updateObj: Raw update object from the messaging platform.
                Contains the original platform-specific update data, which may
                include additional metadata not present in the EnsuredMessage.

        Returns:
            HandlerResultStatus.SKIPPED always. This status indicates that
            the handler did not process the message and allows other handlers
            in the chain to process it. The message will continue through the
            handler chain until a handler returns a different status.

        Example:
            The handler logs messages like:
            ```
            ExampleCustomHandler saw message from John Doe in chat 123456789
            ```
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
        """Handle the /custom_hello command.

        This command demonstrates that the custom handler is properly loaded
        and functioning. It sends a friendly greeting message to the user,
        optionally using a custom name provided as an argument.

        The command is registered with the bot's command system and appears
        in the help menu under the TOOLS category. It is available to all
        users with DEFAULT permission level.

        Command Usage:
            /custom_hello [name]

        Examples:
            /custom_hello
            /custom_hello Alice

        Args:
            ensuredMessage: The command message containing the user who
                sent the command, the chat context, and other metadata.
                Used to determine the sender's name for the greeting and
                to send the response message.
            command: The command name that was invoked. For this handler,
                this will always be "custom_hello". This parameter is
                provided by the command registration system.
            args: Command arguments provided by the user. If non-empty,
                this string is used as the name to greet. If empty or
                whitespace-only, the sender's name is used instead.
            updateObj: Raw update object from the messaging platform.
                Contains the original platform-specific update data, which
                may include additional metadata not present in the
                EnsuredMessage.
            typingManager: Optional typing indicator manager. If provided,
                can be used to show a typing indicator while processing the
                command. This handler does not use it as the response is
                generated quickly.

        Returns:
            None. The method sends a response message directly to the chat
            using the sendMessage method.

        Note:
            The response message uses MarkdownV2 formatting for the name
            (bold text) and includes an emoji for a friendly tone.
        """
        name = args.strip() if args.strip() else ensuredMessage.sender.name

        await self.sendMessage(
            ensuredMessage,
            messageText=f"Hello from custom module, **{name}**! 👋\n\nThis is a custom handler, dood!",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
        logger.info(f"ExampleCustomHandler responded to /custom_hello from {ensuredMessage.sender.name}")
