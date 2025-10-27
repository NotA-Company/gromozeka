"""
User data management handlers for the Gromozeka Telegram bot, dood!

This module provides handlers for managing user-specific data storage within the bot.
It includes command handlers for viewing, deleting, and clearing user data, as well as
LLM tool integration for AI-assisted data management, dood!

The module implements:
- User data retrieval and display
- Selective data deletion by key
- Complete data clearing
- LLM tool for AI-driven data storage

All user data is scoped to specific chat and user combinations, dood!
"""

import logging

from typing import Any, Dict, Optional

from telegram import Update
from telegram.ext import ContextTypes

from internal.services.llm.service import LLMService

from .base import BaseBotHandler

from lib.ai.models import (
    LLMFunctionParameter,
    LLMParameterType,
)
from lib.ai.manager import LLMManager
import lib.utils as utils

from internal.config.manager import ConfigManager

from internal.database.wrapper import DatabaseWrapper
from internal.database.models import MessageCategory

from ..models import (
    CommandCategory,
    CommandHandlerOrder,
    EnsuredMessage,
    commandHandler,
)

logger = logging.getLogger(__name__)


class UserDataHandler(BaseBotHandler):
    """
    Handler class for user data management operations, dood!

    This class provides command handlers and LLM tool integration for managing
    user-specific data within the bot. It allows users to store, retrieve, and
    delete personalized information that the bot can use to improve interactions.

    The handler registers an LLM tool that enables the AI to automatically store
    relevant user information during conversations, dood!

    Attributes:
        llmService (LLMService): Service for LLM tool registration and management.
    """

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        """
        Initialize the user data handler with required services, dood!

        Sets up the handler and registers the 'add_user_data' LLM tool for
        AI-assisted data storage during conversations.

        Args:
            configManager (ConfigManager): Configuration manager instance.
            database (DatabaseWrapper): Database wrapper for data persistence.
            llmManager (LLMManager): LLM manager for AI model interactions.
        """
        # Initialize the mixin (discovers handlers)
        super().__init__(configManager=configManager, database=database, llmManager=llmManager)

        self.llmService = LLMService.getInstance()

        self.llmService.registerTool(
            name="add_user_data",
            description=(
                "Add some data/knowledge about user, sent last message. "
                "Use it in following cases:\n"
                "1. User asked to learn/remember something about him/her.\n"
                "2. You learned new information about user "
                "(e.g., real name, birth dare, what he like, etc).\n"
                "3. You want to remember something relating to user.\n"
                "4. When you needs to store information related to the user "
                "to improve interaction quality (e.g., remembering formatting preferences, "
                "command usage frequency, communication style).\n"
                "\n"
                "Will return new data for given key."
            ),
            parameters=[
                LLMFunctionParameter(
                    name="key",
                    description="Key for data (for structured data usage)",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
                LLMFunctionParameter(
                    name="data",
                    description="Data/knowledbe you want to remember",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
                LLMFunctionParameter(
                    name="append",
                    description=(
                        "True: Append data to existing data, "
                        "False: replace existing data for given key. "
                        "Default: False"
                    ),
                    type=LLMParameterType.BOOLEAN,
                    required=False,
                ),
            ],
            handler=self._llmToolSetUserData,
        )

    ###
    # LLM Tool-Calling handlers
    ###

    async def _llmToolSetUserData(
        self, extraData: Optional[Dict[str, Any]], key: str, data: str, append: bool = False, **kwargs
    ) -> str:
        """
        LLM tool handler for storing user data, dood!

        This method is called by the LLM when it needs to store information about
        a user. It validates the required context and delegates to the base handler's
        setUserData method.

        Args:
            extraData (Optional[Dict[str, Any]]): Extra context data containing the
                ensuredMessage object. Must not be None.
            key (str): The key under which to store the data.
            data (str): The data/knowledge to store.
            append (bool, optional): If True, append to existing data; if False,
                replace existing data. Defaults to False.
            **kwargs: Additional keyword arguments (ignored).

        Returns:
            str: JSON string containing operation status, key, and the new data value.

        Raises:
            RuntimeError: If extraData is None, doesn't contain ensuredMessage,
                or ensuredMessage is not an EnsuredMessage instance, dood!
        """
        if extraData is None:
            raise RuntimeError("extraData should be provided")
        if "ensuredMessage" not in extraData:
            raise RuntimeError("ensuredMessage should be provided")
        ensuredMessage = extraData["ensuredMessage"]
        if not isinstance(ensuredMessage, EnsuredMessage):
            raise RuntimeError("ensuredMessage should be EnsuredMessage")

        newData = self.setUserData(
            chatId=ensuredMessage.chat.id, userId=ensuredMessage.user.id, key=key, value=data, append=append
        )
        return utils.jsonDumps({"done": True, "key": key, "data": newData})

    ###
    # COMMANDS Handlers
    ###

    @commandHandler(
        commands=("get_my_data",),
        shortDescription="Dump data, bot knows about you in this chat",
        helpMessage=": Показать запомненную информацию о Вас в текущем чате.",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.TECHNICAL,
    )
    async def get_my_data_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle the /get_my_data command to display stored user data, dood!

        Retrieves and displays all data the bot has stored about the user in the
        current chat. The data is formatted as JSON for easy reading.

        Args:
            update (Update): The Telegram update object containing the message.
            context (ContextTypes.DEFAULT_TYPE): The callback context from python-telegram-bot.

        Returns:
            None

        Note:
            This command is only available in private chats and is categorized as
            a technical command, dood!
        """

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

        self.saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)
        self._updateEMessageUserData(ensuredMessage)

        await self.sendMessage(
            ensuredMessage,
            messageText=(f"```json\n{utils.jsonDumps(ensuredMessage.userData, indent=2)}\n```"),
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandler(
        commands=("delete_my_data",),
        shortDescription="<key> - Delete user data for given key",
        helpMessage=" `<key>`: Удалить информацию о Вас по указанному ключу.",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.TECHNICAL,
    )
    async def delete_my_data_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle the /delete_my_data command to remove specific user data, dood!

        Deletes a specific piece of user data identified by the provided key.
        Requires a key argument to be provided with the command.

        Args:
            update (Update): The Telegram update object containing the message.
            context (ContextTypes.DEFAULT_TYPE): The callback context from python-telegram-bot.
                context.args[0] should contain the key to delete.

        Returns:
            None

        Note:
            If no key is provided, sends an error message to the user.
            This command is only available in private chats, dood!
        """

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

        self.saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)
        self._updateEMessageUserData(ensuredMessage)

        if not context.args:
            await self.sendMessage(
                ensuredMessage,
                messageText=("Для команды `/delete_my_data` нужно указать ключ, который нужно удалить."),
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        chatId = ensuredMessage.chat.id
        userId = ensuredMessage.user.id
        key = context.args[0]
        self.unsetUserData(chatId=chatId, userId=userId, key=key)

        await self.sendMessage(
            ensuredMessage,
            messageText=f"Готово, ключ {key} успешно удален.",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandler(
        commands=("clear_my_data",),
        shortDescription="Clear all user data",
        helpMessage=": Очистить все сзнания о Вас в этом чате.",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.TECHNICAL,
    )
    async def clear_my_data_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle the /clear_my_data command to remove all user data, dood!

        Completely clears all data the bot has stored about the user in the
        current chat. This operation cannot be undone.

        Args:
            update (Update): The Telegram update object containing the message.
            context (ContextTypes.DEFAULT_TYPE): The callback context from python-telegram-bot.

        Returns:
            None

        Note:
            This command is only available in private chats and is categorized as
            a technical command, dood!
        """

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

        self.saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)
        self._updateEMessageUserData(ensuredMessage)

        chatId = ensuredMessage.chat.id
        userId = ensuredMessage.user.id

        self.clearUserData(userId=userId, chatId=chatId)

        await self.sendMessage(
            ensuredMessage,
            messageText="Готово, память о Вас очищена.",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
