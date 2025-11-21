"""
User data management handlers for Gromozeka bot, dood!

Provides handlers for user-specific data storage: viewing, deleting, clearing data,
and LLM tool integration for AI-assisted data management. All data is scoped to
specific chat and user combinations, dood!
"""

import logging
from typing import Any, Dict, List, Optional

import lib.utils as utils
from internal.bot.common.models import CallbackButton, UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    ButtonDataKey,
    ButtonUserDataConfigAction,
    ChatType,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    MessageSender,
    commandHandlerV2,
)
from internal.config.manager import ConfigManager
from internal.database.models import MessageCategory
from internal.database.wrapper import DatabaseWrapper
from internal.models import MessageIdType
from internal.services.cache import UserActiveActionEnum
from internal.services.llm import LLMService
from lib.ai import (
    LLMFunctionParameter,
    LLMManager,
    LLMParameterType,
)

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class UserDataHandler(BaseBotHandler):
    """
    Handler for user data management with LLM tool integration, dood!

    Attributes:
        llmService (LLMService): Service for LLM tool registration and management.
    """

    def __init__(
        self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager, botProvider: BotProvider
    ):
        """
        Initialize handler and register 'add_user_data' LLM tool, dood!

        Args:
            configManager (ConfigManager): Configuration manager instance.
            database (DatabaseWrapper): Database wrapper for data persistence.
            llmManager (LLMManager): LLM manager for AI model interactions.
        """
        # Initialize the mixin (discovers handlers)
        super().__init__(configManager=configManager, database=database, llmManager=llmManager, botProvider=botProvider)

        self.llmService = LLMService.getInstance()

        self.llmService.registerTool(
            name="add_user_data",
            description=(
                "Remember some data/knowledge about user who, sent last message. "
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
            ],
            handler=self._llmToolSetUserData,
        )

    ###
    # LLM Tool-Calling handlers
    ###

    async def _llmToolSetUserData(self, extraData: Optional[Dict[str, Any]], key: str, data: str, **kwargs) -> str:
        """
        LLM tool handler for storing user data, dood!

        Args:
            extraData (Optional[Dict[str, Any]]): Context with ensuredMessage object.
            key (str): Storage key.
            data (str): Data to store.
            **kwargs: Additional arguments (ignored).

        Returns:
            str: JSON with operation status, key, and data value.

        Raises:
            RuntimeError: If extraData invalid or missing ensuredMessage, dood!
        """
        if extraData is None:
            raise RuntimeError("extraData should be provided")
        if "ensuredMessage" not in extraData:
            raise RuntimeError("extraData['ensuredMessage'] should be provided")
        ensuredMessage = extraData["ensuredMessage"]
        if not isinstance(ensuredMessage, EnsuredMessage):
            raise RuntimeError("ensuredMessage should be instance of EnsuredMessage")

        self.cache.setChatUserData(
            chatId=ensuredMessage.recipient.id,
            userId=ensuredMessage.sender.id,
            key=key,
            value=data,
        )

        return utils.jsonDumps({"done": True, "key": key, "data": data})

    ###
    # Handling user-data configuration wizard
    ###

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """
        Handle messages for user data configuration wizard in private chats, dood!

        Args:
            update (Update): Telegram update object.
            context (ContextTypes.DEFAULT_TYPE): Callback context.
            ensuredMessage (Optional[EnsuredMessage]): Ensured message or None.

        Returns:
            HandlerResultStatus: FINAL if handled, SKIPPED otherwise.
        """

        if ensuredMessage.recipient.chatType != ChatType.PRIVATE:
            return HandlerResultStatus.SKIPPED

        user = ensuredMessage.sender
        messageText = ensuredMessage.getParsedMessageText()
        userDataConfig = self.cache.getUserState(userId=user.id, stateKey=UserActiveActionEnum.UserDataConfig)
        if userDataConfig is None:
            return HandlerResultStatus.SKIPPED

        await self._handleUserDataConfiguration(
            data={
                **userDataConfig["data"],
                ButtonDataKey.Value: messageText,
            },
            messageId=userDataConfig["messageId"],
            messageChatId=userDataConfig["messageChatId"],
            user=user,
        )
        return HandlerResultStatus.FINAL

    async def _handleConfigAction_Init(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageIdType,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """
        Initialize wizard with chat selection interface, dood!

        Args:
            data (CallbackDataDict): Callback data from button press.
            messageId (int): Message ID to edit.
            user (User): Telegram user.
            bot (telegram.Bot): Bot instance.
        """
        # Print list of known chats

        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )
        keyboard: List[List[CallbackButton]] = []

        for chat in self.db.getUserChats(user.id):
            keyboard.append(
                [
                    CallbackButton(
                        self.getChatTitle(chat, useMarkdown=False, addChatId=False),
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                            ButtonDataKey.ChatId: chat["chat_id"],
                        },
                    )
                ]
            )

        if not keyboard:
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Чаты не найдены.",
            )
            return

        keyboard.append([exitButton])
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text="Выберите чат для настройки:",
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_ChatSelected(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageIdType,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """
        Display user data for selected chat with edit options, dood!

        Args:
            data (CallbackDataDict): Callback data with chat ID.
            messageId (int): Message ID to edit.
            user (User): Telegram user.
            bot (telegram.Bot): Bot instance.
        """
        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )

        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"ChatSelected: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return

        chatInfo = self.getChatInfo(chatId)
        if chatInfo is None:
            logger.error(f"ChatSelected: chatInfo is None in {chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: Выбран неизвестный чат",
            )
            return
        # TODO: Check if user is present in given chat

        logger.debug(f"ChatSelected: chatInfo: {chatInfo}")
        resp = f"Выбран чат {self.getChatTitle(chatInfo)}:\n\n"
        keyboard: List[List[CallbackButton]] = [
            [
                CallbackButton(
                    "Добавить новый ключ",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.KeySelected,
                        ButtonDataKey.ChatId: chatId,
                    },
                )
            ]
        ]

        userData = self.cache.getChatUserData(chatId=chatId, userId=user.id)
        for k, v in userData.items():
            resp += f"**Ключ**: `{k}`:\n```{k}\n{v}\n```\n\n"
            keyboard.append(
                [
                    CallbackButton(
                        k,
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.KeySelected,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Key: k,
                        },
                    )
                ]
            )

        resp += "Выберите нужное действие:"
        keyboard.append(
            [
                CallbackButton(
                    "Очистить все данные",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ClearChatData,
                        ButtonDataKey.ChatId: chatId,
                    },
                )
            ]
        )
        keyboard.append(
            [
                CallbackButton(
                    "<< Назад",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Init,
                    },
                )
            ]
        )
        keyboard.append([exitButton])
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=resp,
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_ClearChatData(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageIdType,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """
        Clear all user data for selected chat, dood!

        Args:
            data (CallbackDataDict): Callback data with chat ID.
            messageId (int): Message ID to edit.
            user (User): Telegram user.
            bot (telegram.Bot): Bot instance.
        """
        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )
        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"ClearChatData: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return

        # TODO: Check if user is present in given chat
        self.cache.clearChatUserData(chatId=chatId, userId=user.id)
        keyboard: List[List[CallbackButton]] = [
            [
                CallbackButton(
                    "<< Назад",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                        ButtonDataKey.ChatId: chatId,
                    },
                )
            ],
            [exitButton],
        ]
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text="Все данные очищены",
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_DeleteKey(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageIdType,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """
        Delete specific user data key from selected chat, dood!

        Args:
            data (CallbackDataDict): Callback data with chat ID and key.
            messageId (int): Message ID to edit.
            user (User): Telegram user.
            bot (telegram.Bot): Bot instance.
        """
        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )
        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"DeleteKey: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return
        # TODO: Check if user is present in given chat

        # We need to check if key is passed, actually.
        # But I don't care
        key = str(data.get(ButtonDataKey.Key, None))

        self.cache.unsetChatUserData(chatId=chatId, userId=user.id, key=key)
        keyboard: List[List[CallbackButton]] = [
            [
                CallbackButton(
                    "<< Назад",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                        ButtonDataKey.ChatId: chatId,
                    },
                )
            ],
            [exitButton],
        ]
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=f"Данные по ключу {key} удалены",
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_KeySelected(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageIdType,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """
        Prompt user to enter value for key (new or existing), dood!

        Args:
            data (CallbackDataDict): Callback data with chat ID and optional key.
            messageId (int): Message ID to edit.
            user (User): Telegram user.
            bot (telegram.Bot): Bot instance.
        """
        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )
        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"KeySelected: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return
        # TODO: Check if user is present in given chat

        key = data.get(ButtonDataKey.Key, None)

        self.cache.setUserState(
            userId=user.id,
            stateKey=UserActiveActionEnum.UserDataConfig,
            value={
                "data": {
                    ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.SetValue,
                    ButtonDataKey.ChatId: chatId,
                    ButtonDataKey.Key: key,
                },
                "messageId": messageId,
                "messageChatId": messageChatId,
            },
        )

        userData = self.cache.getChatUserData(chatId=chatId, userId=user.id)
        if userData is None:
            userData = {}

        resp = (
            (
                "Введите новый ключ и его значение.\n"
                "Первое слово будет использовано как ключ, остальной текст "
                "будет использован как значение:"
            )
            if key is None
            else f"Введите новое значение для ключа {key}.\n"
            f"Текущее значение:\n```{key}\n{userData.get(str(key), '')}\n```"
        )

        keyboard: List[List[CallbackButton]] = [
            [
                CallbackButton(
                    "Удалить выбраный ключ",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.DeleteKey,
                        ButtonDataKey.ChatId: chatId,
                        ButtonDataKey.Key: key,
                    },
                )
            ],
            [
                CallbackButton(
                    "<< Назад",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                        ButtonDataKey.ChatId: chatId,
                    },
                )
            ],
            [exitButton],
        ]
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=resp,
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_SetValue(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageIdType,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """
        Set or update user data value, extracting key from message if needed, dood!

        Args:
            data (CallbackDataDict): Callback data with chat ID, optional key, and value.
            messageId (int): Message ID to edit.
            user (User): Telegram user.
            bot (telegram.Bot): Bot instance.
        """
        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )
        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"SetValue: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return
        # TODO: Check if user is present in given chat

        key = data.get(ButtonDataKey.Key, None)
        value = data.get(ButtonDataKey.Value, None)

        if not value:
            logger.error(f"SetValue: Value is empty in {data}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Произошла ошибка",
            )
            return

        if key is None:
            key, value = str(value).split(" ", 1)

        self.cache.setChatUserData(chatId=chatId, userId=user.id, key=str(key), value=str(value))

        keyboard: List[List[CallbackButton]] = [
            [
                CallbackButton(
                    "<< Назад",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                        ButtonDataKey.ChatId: chatId,
                    },
                )
            ],
            [exitButton],
        ]

        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=f"Готово, теперь ключ {key} установлен в \n```{key}\n{value}\n```",
            inlineKeyboard=keyboard,
        )

    async def _handleUserDataConfiguration(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageIdType,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """
        Route configuration actions to appropriate handlers, dood!

        Args:
            data (CallbackDataDict): Callback data with action and parameters.
            messageId (int): Message ID to edit.
            user (User): Telegram user.
            bot (telegram.Bot): Bot instance.
        """

        self.cache.clearUserState(userId=user.id, stateKey=UserActiveActionEnum.UserDataConfig)

        action = data.get(ButtonDataKey.UserDataConfigAction, None)
        if action not in ButtonUserDataConfigAction.all():
            logger.error(f"_handleUserDataConfiguration: Invalid action: {action}")
            return
        action = ButtonUserDataConfigAction(action)

        match action:
            case ButtonUserDataConfigAction.Init:
                await self._handleConfigAction_Init(data, messageId=messageId, messageChatId=messageChatId, user=user)
            case ButtonUserDataConfigAction.Cancel:
                await self.editMessage(
                    messageId=messageId,
                    chatId=messageChatId,
                    text="Настройка закончена, буду ждать вас снова",
                )
            case ButtonUserDataConfigAction.ChatSelected:
                await self._handleConfigAction_ChatSelected(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.ClearChatData:
                await self._handleConfigAction_ClearChatData(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.DeleteKey:
                await self._handleConfigAction_DeleteKey(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.KeySelected:
                await self._handleConfigAction_KeySelected(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.SetValue:
                await self._handleConfigAction_SetValue(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )

            case _:
                logger.error(f"_handleUserDataConfiguration: Invalid action: {action}")
                await self.editMessage(
                    messageId=messageId,
                    chatId=messageChatId,
                    text=f"Unknown action: {action}",
                )
                return

    async def callbackHandler(
        self,
        ensuredMessage: EnsuredMessage,
        data: utils.PayloadDict,
        user: MessageSender,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        """
        Handle button callbacks for user data configuration, dood!

        Args:
            update (Update): Telegram update with callback query.
            context (ContextTypes.DEFAULT_TYPE): Callback context.
            data (CallbackDataDict): Parsed callback data.

        Returns:
            HandlerResultStatus: FINAL if handled, SKIPPED if not, FATAL if data missing.
        """

        userDataAction = data.get(ButtonDataKey.UserDataConfigAction, None)
        if userDataAction is not None:
            await self._handleUserDataConfiguration(
                data,
                messageId=ensuredMessage.messageId,
                messageChatId=ensuredMessage.recipient.id,
                user=user,
            )
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.SKIPPED

    ###
    # COMMANDS Handlers
    ###

    @commandHandlerV2(
        commands=("get_my_data",),
        shortDescription="<chatId> - Dump data, bot knows about you in this chat",
        helpMessage=" [`<chatId>`]: Показать запомненную информацию о Вас в указанном (или текущем) чате.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.GROUP},
        helpOrder=CommandHandlerOrder.TECHNICAL,
        category=CommandCategory.TOOLS,
    )
    async def get_my_data_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """
        Display stored user data as JSON, dood!

        Args:
            ensuredMessage (EnsuredMessage): Ensured message object.
            update (Update): Telegram update object.
            context (ContextTypes.DEFAULT_TYPE): Callback context.
        """

        targetChatId = utils.extractInt(args.split(maxsplit=1))
        if targetChatId is None:
            targetChatId = ensuredMessage.recipient.id

        userData = self.cache.getChatUserData(chatId=targetChatId, userId=ensuredMessage.sender.id)

        await self.sendMessage(
            ensuredMessage,
            messageText=(f"```json\n{utils.jsonDumps(userData, indent=2)}\n```"),
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandlerV2(
        commands=("knowledge_config",),
        shortDescription="Start wisard for user-data manaagement",
        helpMessage=": Запустить мастер управления знаниями бота о вас.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE},
        helpOrder=CommandHandlerOrder.WIZARDS,
        category=CommandCategory.PRIVATE,
    )
    async def knowledge_config_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """
        Start interactive user data configuration wizard (private chats only), dood!

        Args:
            ensuredMessage (EnsuredMessage): Ensured message object.
            update (Update): Telegram update object.
            context (ContextTypes.DEFAULT_TYPE): Callback context.
        """

        msg = await self.sendMessage(
            ensuredMessage,
            messageText="Запускаю мастер управления знаниями бота о вас...",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
        if msg:
            await self._handleUserDataConfiguration(
                {
                    ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Init,
                },
                messageId=msg[0].messageId,
                messageChatId=msg[0].recipient.id,
                user=ensuredMessage.sender,
            )
        else:
            logger.error("Failed to send message")
