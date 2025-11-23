"""
TODO: write docstring
"""

import datetime
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
from internal.models import MessageIdType
from internal.services.cache import UserActiveActionEnum

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class TopicManagerHandler(BaseBotHandler):
    """
    TODO: write docstring
    """

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """
        TODO: write compact docstring
        """
        if ensuredMessage.recipient.chatType != ChatType.PRIVATE:
            return HandlerResultStatus.SKIPPED

        user = ensuredMessage.sender
        topicManagement = self.cache.getUserState(userId=user.id, stateKey=UserActiveActionEnum.TopicManagement)
        if topicManagement is None:
            return HandlerResultStatus.SKIPPED

        messageText = ensuredMessage.getParsedMessageText()

        data = topicManagement["data"]
        data[ButtonDataKey.Value] = messageText
        await self._handle_topic_management(
            data=data,
            messageId=topicManagement["messageId"],
            messageChatId=topicManagement["messageChatId"],
            user=user,
        )
        return HandlerResultStatus.FINAL

    async def topicManagenet_Init(
        self,
        data: utils.PayloadDict,
        messageId: MessageIdType,
        messageChatId: int,
        user: MessageSender,
        chatId: Optional[int],
    ) -> None:
        """TODO write docstring"""
        if chatId is not None:
            raise RuntimeError("Init: chatId should be None in Init action")

        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.TopicManagementAction: ButtonTopicManagementAction.Cancel},
        )
        userChats = self.db.getUserChats(user.id)
        keyboard: List[List[CallbackButton]] = []
        isBotOwner = await self.isAdmin(user=user, allowBotOwners=True)

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
        messageId: MessageIdType,
        messageChatId: int,
        user: MessageSender,
        chatId: Optional[int],
    ) -> None:
        """TODO write docstring"""
        if chatId is None:
            logger.error(f"chatId is None in {data}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: Чат не выбран",
            )
            return

        chatInfo = self.getChatInfo(chatId)
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

        topicList = list(self.cache.getChatTopicsInfo(chatId=chatId).values())
        if not topicList:
            topicList.append(
                {
                    "chat_id": chatId,
                    "topic_id": 0,
                    "name": "Default",
                    "icon_color": None,
                    "icon_custom_emoji_id": None,
                    "created_at": datetime.datetime.now(),
                    "updated_at": datetime.datetime.now(),
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
                        ButtonDataKey.SummarizationAction: ButtonTopicManagementAction.Init,
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
        messageId: MessageIdType,
        messageChatId: int,
        user: MessageSender,
        chatId: Optional[int],
    ) -> None:
        """TODO write docstring"""
        if chatId is None:
            logger.error(f"chatId is None in {data}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: Чат не выбран",
            )
            return

        chatInfo = self.getChatInfo(chatId)
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
        topicDict = self.cache.getChatTopicsInfo(chatId=chatId)
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
            self.updateTopicInfo(
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
                "Изменено на **{value}**",
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
        messageId: MessageIdType,
        messageChatId: int,
        user: MessageSender,
    ):
        """
        TODO: write docstring
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
                    text="Суммаризация отменена",
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
        """
        TODO: write docstring
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
        """
        TODO write docstring
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
