"""Topic management handler for bot.

This module provides functionality for managing Telegram forum topics through
an interactive wizard interface. It allows administrators to rename topics
in group chats where they have admin privileges.
"""

import logging
from typing import List, Optional

import lib.utils as utils
from internal.bot.common.models import CallbackButton, UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    ButtonDataKey,
    ChatType,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    MessageSender,
    commandHandlerV2,
)
from internal.bot.models.ensured_message import MessageRecipient
from internal.bot.models.enums import ButtonTopicManagementAction
from internal.database.models import (
    MessageCategory,
)
from internal.models import MessageId
from internal.services.cache import UserActiveActionEnum

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class TopicManagerHandler(BaseBotHandler):
    """Handler for managing Telegram forum topics.

    Provides an interactive wizard interface that allows administrators to
    rename topics in group chats where they have admin privileges. The handler
    supports both command-based and callback-based interactions.
    """

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """Handle new messages during topic management workflow.

        Processes user input when they are in the middle of renaming a topic.
        Only processes messages from private chats where the user has an active
        topic management state.

        Args:
            ensuredMessage: The ensured message object containing message details.
            updateObj: The raw update object from the messaging platform.

        Returns:
            HandlerResultStatus.FINAL if the message was processed and topic
                management workflow should continue, HandlerResultStatus.SKIPPED
                if the message should be handled by other handlers.
        """
        if ensuredMessage.recipient.chatType != ChatType.PRIVATE:
            return HandlerResultStatus.SKIPPED

        user = ensuredMessage.sender
        topicManagement = self.cache.getUserState(userId=user.id, stateKey=UserActiveActionEnum.TopicManagement)
        if topicManagement is None:
            return HandlerResultStatus.SKIPPED

        data = topicManagement["data"]
        data[ButtonDataKey.Value] = ensuredMessage.formatMessageText()
        await self._handle_topic_management(
            data=data,
            messageId=MessageId(topicManagement["messageId"]),
            messageChatId=topicManagement["messageChatId"],
            user=user,
        )
        return HandlerResultStatus.FINAL

    async def topicManagenet_Init(
        self,
        data: utils.PayloadDict,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
        chatId: Optional[int],
    ) -> None:
        """Initialize the topic management wizard.

        Displays a list of chats where the user is an administrator, allowing
        them to select a chat for topic management. Only shows chats where the
        user has admin privileges or if the user is the bot owner.

        Args:
            data: Payload dictionary containing action data.
            messageId: The message ID to edit with the chat selection menu.
            messageChatId: The chat ID where the message was sent.
            user: The user who initiated the topic management.
            chatId: Must be None for the Init action.

        Raises:
            RuntimeError: If chatId is not None (should be None for Init action).
        """
        if chatId is not None:
            raise RuntimeError("Init: chatId should be None in Init action")

        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.TopicManagementAction: ButtonTopicManagementAction.Cancel},
        )
        userChats = await self.getUserChats(user.id)
        keyboard: List[List[CallbackButton]] = []
        isBotOwner = self.isBotOwner(user=user)

        for chat in userChats:
            chatObj = MessageRecipient(id=chat["chat_id"], chatType=ChatType(chat["type"]))

            # Show chat only if:
            # User is Bot Owner (so can do anything)
            # Or user is Admin in chat
            if isBotOwner or await self.isAdmin(user=user, chat=chatObj):
                buttonTitle = self.getChatTitle(chat, useMarkdown=False, addChatId=False)

                keyboard.append(
                    [
                        CallbackButton(
                            buttonTitle,
                            {
                                ButtonDataKey.TopicManagementAction: ButtonTopicManagementAction.ChatSelected,
                                ButtonDataKey.ChatId: chat["chat_id"],
                            },
                        )
                    ]
                )

        if not keyboard:
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Вы не являетесь администратором ни в одном чате.",
            )
            return

        keyboard.append([exitButton])
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text="Выберите чат для настройки:",
            inlineKeyboard=keyboard,
        )

    async def topicManagenet_ChatSelected(
        self,
        data: utils.PayloadDict,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
        chatId: Optional[int],
    ) -> None:
        """Handle chat selection in topic management wizard.

        Displays a list of topics in the selected chat, allowing the user to
        choose a topic to rename. Includes a default topic option if no topics
        exist in the chat.

        Args:
            data: Payload dictionary containing action data including chatId.
            messageId: The message ID to edit with the topic selection menu.
            messageChatId: The chat ID where the message was sent.
            user: The user who selected the chat.
            chatId: The ID of the selected chat.
        """
        if chatId is None:
            logger.error(f"chatId is None in {data}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: Чат не выбран",
            )
            return

        chatInfo = await self.getChatInfo(chatId)
        if chatInfo is None:
            logger.error(f"Unknown chatId in {data} for user {user}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: неверный чат",
            )
            return

        chatTitle = self.getChatTitle(chatInfo)
        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.TopicManagementAction: ButtonTopicManagementAction.Cancel},
        )
        keyboard: List[List[CallbackButton]] = []

        topicList = list((await self.cache.getChatTopicsInfo(chatId=chatId)).values())
        if not topicList:
            topicList.append(
                {
                    "chat_id": chatId,
                    "topic_id": 0,
                    "name": "Default",
                    "icon_color": None,
                    "icon_custom_emoji_id": None,
                    "created_at": utils.now(),
                    "updated_at": utils.now(),
                }
            )

        for topic in topicList:
            keyboard.append(
                [
                    CallbackButton(
                        str(topic["name"]),
                        {
                            ButtonDataKey.TopicManagementAction: ButtonTopicManagementAction.TopicSelected,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.TopicId: topic["topic_id"],
                        },
                    )
                ]
            )

        keyboard.append(
            [
                CallbackButton(
                    "<< Назад к списку чатов",
                    {
                        ButtonDataKey.TopicManagementAction: ButtonTopicManagementAction.Init,
                    },
                )
            ]
        )

        keyboard.append([exitButton])
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=f"Выбран чат\n{chatTitle}\nВыберите топик из списка:",
            inlineKeyboard=keyboard,
        )

    async def topicManagenet_TopicSelected(
        self,
        data: utils.PayloadDict,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
        chatId: Optional[int],
    ) -> None:
        """Handle topic selection in topic management wizard.

        Either applies a new topic name if provided in the data, or prompts
        the user to enter a new name for the selected topic. When prompting,
        sets the user's active state to wait for their text input.

        Args:
            data: Payload dictionary containing action data including chatId,
                topicId, and optionally the new topic name (Value).
            messageId: The message ID to edit with the topic name prompt.
            messageChatId: The chat ID where the message was sent.
            user: The user who selected the topic.
            chatId: The ID of the chat containing the topic.
        """
        if chatId is None:
            logger.error(f"chatId is None in {data}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: Чат не выбран",
            )
            return

        chatInfo = await self.getChatInfo(chatId)
        if chatInfo is None:
            logger.error(f"Unknown chatId in {data} for user {user}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: неверный чат",
            )
            return
        chatTitle = self.getChatTitle(chatInfo)

        topicId = data.get(ButtonDataKey.TopicId, None)
        if not isinstance(topicId, int):
            logger.error(f"TopicId is none in {data}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: топик не выбран",
            )
            return

        topicInfo = None
        topicDict = await self.cache.getChatTopicsInfo(chatId=chatId)
        if topicId in topicDict:
            topicInfo = topicDict[topicId]
        else:
            logger.error(f"WWrong topicId in {data}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: неверный топик",
            )
            return

        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.TopicManagementAction: ButtonTopicManagementAction.Cancel},
        )

        value = data.get(ButtonDataKey.Value, None)

        if isinstance(value, str) and value:
            await self.updateTopicInfo(
                chatId=chatId,
                topicId=topicId,
                iconColor=topicInfo["icon_color"],
                customEmojiId=topicInfo["icon_custom_emoji_id"],
                name=value,
                force=True,
            )

            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text=f"Готово. В чате\n{chatTitle}\n"
                f"Имя топика:\n`{topicInfo['topic_id']}` **{topicInfo['name']}**\n"
                f"Изменено на **{value}**",
                inlineKeyboard=[
                    [
                        CallbackButton(
                            "<< К списку топиков",
                            {
                                ButtonDataKey.TopicManagementAction: ButtonTopicManagementAction.ChatSelected,
                                ButtonDataKey.ChatId: chatId,
                            },
                        )
                    ],
                    [exitButton],
                ],
            )
            return

        self.cache.setUserState(
            userId=user.id,
            stateKey=UserActiveActionEnum.TopicManagement,
            value={
                "data": {
                    ButtonDataKey.TopicManagementAction: ButtonTopicManagementAction.TopicSelected,
                    ButtonDataKey.ChatId: chatId,
                    ButtonDataKey.TopicId: topicId,
                },
                "messageId": messageId,
                "messageChatId": messageChatId,
            },
        )

        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=f"Выбран чат\n{chatTitle}\n"
            f"Топик:\n`{topicInfo['topic_id']}` **{topicInfo['name']}**\n"
            "Введите новаое название топика или нажмите нужную кнопку",
            inlineKeyboard=[
                [
                    CallbackButton(
                        "<< К списку топиков",
                        {
                            ButtonDataKey.TopicManagementAction: ButtonTopicManagementAction.ChatSelected,
                            ButtonDataKey.ChatId: chatId,
                        },
                    )
                ],
                [exitButton],
            ],
        )

    async def _handle_topic_management(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """Handle topic management actions.

        Routes topic management actions to the appropriate handler method based
        on the action type. Validates user permissions before processing actions
        that require admin privileges.

        Args:
            data: Payload dictionary containing action data including the
                TopicManagementAction and optionally chatId.
            messageId: The message ID to edit with responses.
            messageChatId: The chat ID where the message was sent.
            user: The user performing the action.

        Raises:
            ValueError: If the action in the data is not a valid
                ButtonTopicManagementAction.
        """
        self.cache.clearUserState(userId=user.id, stateKey=UserActiveActionEnum.TopicManagement)
        actionStr: Optional[str] = str(data.get(ButtonDataKey.TopicManagementAction, None))
        if actionStr not in ButtonTopicManagementAction.all():
            raise ValueError(f"Wrong action in {data}")
        action = ButtonTopicManagementAction(actionStr)

        chatId = data.get(ButtonDataKey.ChatId, None)
        if not isinstance(chatId, int):
            chatId = None

        if chatId is not None:
            chatObj = MessageRecipient(id=chatId, chatType=ChatType.PRIVATE if chatId > 0 else ChatType.GROUP)

            if not await self.isAdmin(user, chatObj):
                logger.error(f"User {user} is not allowed to manage topics of {chatObj}")
                await self.editMessage(
                    messageId=messageId,
                    chatId=messageChatId,
                    text="Вы не можете настраивать топики в выбраном чате",
                )
                return
        match action:
            case ButtonTopicManagementAction.Init:
                return await self.topicManagenet_Init(data, messageId, messageChatId, user, chatId)
            case ButtonTopicManagementAction.Cancel:
                await self.editMessage(
                    messageId=messageId,
                    chatId=messageChatId,
                    text="Настройка топиков завершена",
                )
                return
            case ButtonTopicManagementAction.ChatSelected:
                return await self.topicManagenet_ChatSelected(data, messageId, messageChatId, user, chatId)
            case ButtonTopicManagementAction.TopicSelected:
                return await self.topicManagenet_TopicSelected(data, messageId, messageChatId, user, chatId)
            case _:
                logger.error(f"Unknown action in {data}")
                await self.editMessage(
                    messageId=messageId,
                    chatId=messageChatId,
                    text=f"Unknown action: {action}",
                )
                return

    @commandHandlerV2(
        commands=("topic_management",),
        shortDescription="Start topic management wizard",
        helpMessage=": Открыть мастер настройки информации о топиках",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TECHNICAL,
    )
    async def topic_management_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the /topic_management command.

        Initiates the topic management wizard by displaying a loading message
        and then showing the list of chats where the user can manage topics.

        Args:
            ensuredMessage: The ensured message object containing command details.
            command: The command that was triggered (e.g., "topic_management").
            args: Additional arguments provided with the command.
            UpdateObj: The raw update object from the messaging platform.
            typingManager: Optional typing manager for showing typing indicators.
        """

        msg = await self.sendMessage(
            ensuredMessage,
            messageText="Загружаю список чатов....",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
        if msg:
            await self._handle_topic_management(
                {
                    ButtonDataKey.TopicManagementAction: (ButtonTopicManagementAction.Init),
                },
                # {"s": jsonAction, "c": chatId, "m": maxMessages},
                messageId=msg[0].messageId,
                messageChatId=msg[0].recipient.id,
                user=ensuredMessage.sender,
            )
        else:
            logger.error("Message undefined")

    async def callbackHandler(
        self,
        ensuredMessage: EnsuredMessage,
        data: utils.PayloadDict,
        user: MessageSender,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        """Handle callback queries for topic management.

        Processes callback button presses related to topic management and routes
        them to the appropriate handler. Skips callbacks that are not related to
        topic management.

        Args:
            ensuredMessage: The ensured message object containing callback details.
            data: Payload dictionary containing callback data.
            user: The user who triggered the callback.
            updateObj: The raw update object from the messaging platform.

        Returns:
            HandlerResultStatus.FINAL if the callback was processed as a topic
                management action, HandlerResultStatus.SKIPPED if the callback
                should be handled by other handlers.
        """

        topicManagementAction = data.get(ButtonDataKey.TopicManagementAction, None)

        if topicManagementAction is not None:
            await self._handle_topic_management(
                data,
                messageId=ensuredMessage.messageId,
                messageChatId=ensuredMessage.recipient.id,
                user=user,
            )
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.SKIPPED
