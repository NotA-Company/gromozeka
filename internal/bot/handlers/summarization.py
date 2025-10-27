"""
Telegram bot summarization handlers for Gromozeka, dood!

This module provides handlers for chat message summarization functionality,
including interactive wizards for selecting chats, topics, and time ranges,
as well as direct command-based summarization.
"""

import datetime
import json
import logging

import time
from typing import Any, Dict, List, Optional

from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Update, Message, User
from telegram.constants import MessageEntityType
from telegram.ext import ContextTypes

from internal.bot.handlers.base import HandlerResultStatus

from .base import BaseBotHandler
from internal.services.cache.types import UserActiveActionEnum
from lib.ai.models import (
    ModelMessage,
    ModelRunResult,
)
from lib.markdown import markdown_to_markdownv2
import lib.utils as utils

from internal.database.models import (
    ChatInfoDict,
    MessageCategory,
)

from ..models import (
    ButtonDataKey,
    ButtonSummarizationAction,
    ChatSettingsKey,
    ChatSettingsValue,
    CommandCategory,
    CommandHandlerOrder,
    EnsuredMessage,
    LLMMessageFormat,
    commandHandler,
)
from .. import constants

logger = logging.getLogger(__name__)


class SummarizationHandler(BaseBotHandler):
    """
    Handler for chat summarization functionality, dood!
    
    This handler provides comprehensive chat summarization features including:
    - Interactive wizard for selecting chats and topics
    - Configurable time ranges and message counts
    - Custom prompts for summarization
    - Batch processing for large message sets
    - Caching of summarization results
    """

    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
        """
        Handle incoming messages for active summarization sessions, dood!
        
        Processes user input when they're in an active summarization workflow,
        such as entering custom message counts or prompts.
        
        Args:
            update: Telegram update object containing the message
            context: Telegram context for the handler
            ensuredMessage: Validated message object with user and chat info
            
        Returns:
            HandlerResultStatus indicating if the message was handled:
            - FINAL: Message was processed as part of summarization workflow
            - SKIPPED: Not a private chat or no active summarization session
            - ERROR: Missing required data
        """
        chat = update.effective_chat
        if not chat:
            logger.error("Chat undefined")
            return HandlerResultStatus.ERROR
        chatType = chat.type

        if chatType != Chat.PRIVATE:
            return HandlerResultStatus.SKIPPED

        if ensuredMessage is None:
            logger.error("Ensured message undefined")
            return HandlerResultStatus.ERROR

        message = update.message
        if not message or not message.text:
            logger.error("message.text is udefined")
            return HandlerResultStatus.ERROR

        user = ensuredMessage.user
        userId = user.id
        messageText = message.text

        activeSummarizationId = self.cache.getUserState(userId=userId, stateKey=UserActiveActionEnum.Summarization)
        if activeSummarizationId is None:
            return HandlerResultStatus.SKIPPED
        data = activeSummarizationId.copy()
        data.pop("message", None)
        # TODO: Make user action enum
        userAction = data.pop(ButtonDataKey.UserAction, None)
        match userAction:
            case 1:
                try:
                    data[ButtonDataKey.MaxMessages] = int(messageText.strip())
                except Exception as e:
                    logger.error(f"Not int: {messageText}")
                    logger.exception(e)
            case 2:
                data[ButtonDataKey.Prompt] = messageText
            case _:
                logger.error(f"Wrong K in data {activeSummarizationId}")
        await self._handle_summarization(
            data=data,  # pyright: ignore[reportArgumentType]
            message=activeSummarizationId["message"],
            user=user,
        )
        return HandlerResultStatus.FINAL

    async def _doSummarization(
        self,
        ensuredMessage: EnsuredMessage,
        chatId: int,
        threadId: Optional[int],
        chatSettings: Dict[ChatSettingsKey, ChatSettingsValue],
        sinceDT: Optional[datetime.datetime] = None,
        tillDT: Optional[datetime.datetime] = None,
        maxMessages: Optional[int] = None,
        summarizationPrompt: Optional[str] = None,
        useCache: bool = True,
    ) -> None:
        """
        Perform chat summarization and send results, dood!
        
        Retrieves messages from the database, processes them in batches through
        an LLM, and sends the summarized results. Handles token limits by
        splitting large message sets into manageable batches.
        
        Args:
            ensuredMessage: Message to reply to with the summary
            chatId: ID of the chat to summarize
            threadId: Optional topic/thread ID for topic-specific summaries
            chatSettings: Chat configuration including model and prompt settings
            sinceDT: Start datetime for message range (mutually exclusive with maxMessages)
            tillDT: End datetime for message range (optional, used with sinceDT)
            maxMessages: Maximum number of recent messages to summarize
            summarizationPrompt: Custom prompt for the LLM (uses chat setting if None)
            useCache: Whether to check for and store cached summaries
            
        Raises:
            ValueError: If neither sinceDT nor maxMessages is provided
            
        Note:
            Either sinceDT or maxMessages must be provided, but not both.
            Messages are processed in batches to respect token limits.
            Results are cached for reuse if useCache is True.
        """

        if sinceDT is None and maxMessages is None:
            raise ValueError("one of sinceDT or maxMessages MUST be not None")

        messages = self.db.getChatMessagesSince(
            chatId=chatId,
            sinceDateTime=sinceDT if maxMessages is None else None,
            tillDateTime=tillDT if maxMessages is None else None,
            threadId=threadId,
            limit=maxMessages,
            messageCategory=[MessageCategory.USER, MessageCategory.BOT],
        )

        logger.debug(f"Messages: {messages}")

        if summarizationPrompt is None:
            summarizationPrompt = chatSettings[ChatSettingsKey.SUMMARY_PROMPT].toStr()

        if useCache and len(messages) > 1:
            cache = self.db.getChatSummarization(
                chatId=chatId,
                topicId=None,
                firstMessageId=messages[-1]["message_id"],
                lastMessageId=messages[0]["message_id"],
                prompt=summarizationPrompt,
            )
            if cache is not None:
                resMessages = json.loads(cache["summary"])
                for msg in resMessages:
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=msg,
                        messageCategory=MessageCategory.BOT_SUMMARY,
                    )
                    time.sleep(1)
                return

        systemMessage = {
            "role": "system",
            "content": summarizationPrompt,
        }
        parsedMessages = []

        for msg in reversed(messages):
            parsedMessages.append(
                {
                    "role": "user",
                    "content": await EnsuredMessage.fromDBChatMessage(msg).formatForLLM(
                        self.db, LLMMessageFormat.JSON, stripAtsign=True
                    ),
                }
            )

        reqMessages = [systemMessage] + parsedMessages

        llmModel = chatSettings[ChatSettingsKey.SUMMARY_MODEL].toModel(self.llmManager)
        maxTokens = llmModel.getInfo()["context_size"]
        tokensCount = llmModel.getEstimateTokensCount(reqMessages)

        # -256 or *0.9 to ensure everything will be ok
        batchesCount = tokensCount // max(maxTokens - 256, maxTokens * 0.9) + 1
        batchLength = len(parsedMessages) // batchesCount

        if batchLength > constants.SUMMARIZATION_MAX_BATCH_LENGTH:
            batchLenCoeff = batchLength // constants.SUMMARIZATION_MAX_BATCH_LENGTH + 1
            batchesCount = batchesCount * batchLenCoeff
            batchLength = len(parsedMessages) // batchesCount

        logger.debug(
            f"Summarization: estimated total/max tokens: {tokensCount}/{maxTokens}. "
            f"Messages count: {len(parsedMessages)}, batches count/length: "
            f"{batchesCount}/{batchLength}"
        )

        resMessages = []
        if not parsedMessages:
            resMessages.append("No messages to summarize")
        startPos: int = 0

        fallbackPrefix = chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr()

        # Summarise each chunk of messages
        while startPos < len(parsedMessages):
            currentBatchLen = int(min(batchLength, len(parsedMessages) - startPos))
            batchSummarized = False
            while not batchSummarized:
                tryMessages = parsedMessages[startPos : startPos + currentBatchLen]
                reqMessages = [systemMessage] + tryMessages
                tokensCount = llmModel.getEstimateTokensCount(reqMessages)
                if tokensCount > maxTokens:
                    if currentBatchLen == 1:
                        resMessages.append(
                            f"Error while running LLM for batch {startPos}:{startPos + currentBatchLen}: "
                            f"Batch has too many tokens ({tokensCount})"
                        )
                        break
                    currentBatchLen = int(currentBatchLen // (tokensCount / maxTokens))
                    currentBatchLen -= 2
                    if currentBatchLen < 1:
                        currentBatchLen = 1
                    continue
                batchSummarized = True

                mlRet: Optional[ModelRunResult] = None
                try:
                    logger.debug(f"LLM Request messages: {reqMessages}")
                    mlRet = await llmModel.generateTextWithFallBack(
                        ModelMessage.fromDictList(reqMessages),
                        chatSettings[ChatSettingsKey.SUMMARY_FALLBACK_MODEL].toModel(self.llmManager),
                    )
                    logger.debug(f"LLM Response: {mlRet}")
                except Exception as e:
                    logger.error(  # type: ignore
                        f"Error while running LLM for batch {startPos}:{startPos + currentBatchLen}: "
                        f"{type(e).__name__}#{e}"
                    )
                    resMessages.append(
                        f"Error while running LLM for batch {startPos}:{startPos + currentBatchLen}: {type(e).__name__}"
                    )
                    break

                respText = mlRet.resultText
                if mlRet.isFallback:
                    respText = f"{fallbackPrefix} {respText}"
                resMessages.append(mlRet.resultText)

            startPos += currentBatchLen

        # If any message is too long, just split it into multiple messages
        tmpResMessages = []
        for msg in resMessages:
            while len(msg) > constants.TELEGRAM_MAX_MESSAGE_LENGTH:
                head = msg[: constants.TELEGRAM_MAX_MESSAGE_LENGTH]
                msg = msg[constants.TELEGRAM_MAX_MESSAGE_LENGTH :]
                tmpResMessages.append(head)
            if msg:
                tmpResMessages.append(msg)

        resMessages = tmpResMessages

        if useCache and len(messages) > 1:
            self.db.addChatSummarization(
                chatId=chatId,
                topicId=threadId,
                firstMessageId=messages[-1]["message_id"],
                lastMessageId=messages[0]["message_id"],
                prompt=summarizationPrompt,
                summary=utils.jsonDumps(resMessages),
            )

        for msg in resMessages:
            await self.sendMessage(
                ensuredMessage,
                messageText=msg,
                messageCategory=MessageCategory.BOT_SUMMARY,
            )
            time.sleep(1)

    async def _handle_summarization(self, data: Dict[str | int, Any], message: Message, user: User):
        """
        Handle summarization wizard interactions, dood!
        
        Manages the multi-step interactive wizard for configuring and executing
        chat summarization. Handles chat selection, topic selection, time range
        configuration, and custom prompt input.
        
        Args:
            data: Dictionary containing wizard state and user selections:
                - ButtonDataKey.SummarizationAction: Current wizard action/step
                - ButtonDataKey.ChatId: Selected chat ID (optional)
                - ButtonDataKey.TopicId: Selected topic ID (optional)
                - ButtonDataKey.MaxMessages: Message count or time range indicator
                - ButtonDataKey.UserAction: Type of user input expected (1=count, 2=prompt)
                - ButtonDataKey.Prompt: Custom summarization prompt (optional)
            message: Telegram message to edit with wizard UI
            user: User initiating the summarization
            
        Note:
            The wizard progresses through these steps:
            1. Select chat (if not in group/supergroup)
            2. Select topic (if topic summary requested)
            3. Configure time range or message count
            4. Optionally set custom prompt
            5. Execute summarization
            
            User state is tracked in cache during multi-message interactions.
        """

        # Used keys:
        # s: Action
        # c: ChatId
        # t: topicId
        # m: MaxMessages/time
        # ua: user action (1 - set max messages, 2 - set prompt)

        chatSettings = self.getChatSettings(message.chat_id)
        userId = user.id
        self.cache.clearUserState(userId=userId, stateKey=UserActiveActionEnum.Summarization)

        exitButton = InlineKeyboardButton(
            "Отмена",
            callback_data=utils.packDict({ButtonDataKey.SummarizationAction: ButtonSummarizationAction.Cancel}),
        )
        action: Optional[str] = data.get(ButtonDataKey.SummarizationAction, None)
        if action is None or action not in ButtonSummarizationAction.all():
            ValueError(f"Wrong action in {data}")
            return  # Useless, used for fixing typechecking issues

        isToticSummary = action.startswith("t")

        if action == ButtonSummarizationAction.Cancel:
            await message.edit_text(text="Суммаризация отменена")
            return

        maxMessages = data.get(ButtonDataKey.MaxMessages, None)
        if maxMessages is None:
            maxMessages = 0

        userChats = self.db.getUserChats(user.id)

        chatId = data.get(ButtonDataKey.ChatId, None)
        # Choose chatID
        if not isinstance(chatId, int):
            keyboard: List[List[InlineKeyboardButton]] = []
            # chatSettings = self.getChatSettings(ensuredMessage.chat.id)
            for chat in userChats:
                chatTitle: str = f"#{chat['chat_id']}"
                if chat["title"]:
                    chatTitle = f"{constants.CHAT_ICON} {chat['title']} ({chat["type"]})"
                elif chat["username"]:
                    chatTitle = f"{constants.PRIVATE_ICON} {chat['username']} ({chat["type"]})"

                keyboard.append(
                    [
                        InlineKeyboardButton(
                            chatTitle,
                            callback_data=utils.packDict(
                                {
                                    ButtonDataKey.ChatId: chat["chat_id"],
                                    ButtonDataKey.SummarizationAction: action,
                                    ButtonDataKey.MaxMessages: maxMessages,
                                }
                            ),
                        )
                    ]
                )

            if not keyboard:
                await message.edit_text("Вы не найдены ни в одном чате.")
                return

            keyboard.append([exitButton])
            await message.edit_text(text="Выберите чат для суммаризации:", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        chatFound = await self.isAdmin(user, None, True)
        chatInfo: Optional[ChatInfoDict] = None
        for chat in userChats:
            if chat["chat_id"] == chatId:
                chatFound = True
                chatInfo = chat
                break

        if not chatFound or chatInfo is None:
            await message.edit_text("Указан неверный чат")
            return

        # ChatID Choosen
        chatTitle: str = f"#{chatInfo['chat_id']}"
        if chatInfo["title"]:
            chatTitle = f"{constants.CHAT_ICON} {chatInfo['title']} ({chatInfo['type']})"
        elif chatInfo["username"]:
            chatTitle = f"{constants.PRIVATE_ICON} {chatInfo['username']} ({chatInfo['type']})"

        topicId = data.get(ButtonDataKey.TopicId, None)
        # Choose TopicID if needed
        if isToticSummary and topicId is None:
            # await message.edit_text("Список топиков пока не поддержан")
            topics = list(self.cache.getChatTopicsInfo(chatId=chatId).values())
            if not topics:
                topics.append(
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

            keyboard: List[List[InlineKeyboardButton]] = []

            for topic in topics:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            str(topic["name"]),
                            callback_data=utils.packDict(
                                {
                                    ButtonDataKey.ChatId: chatId,
                                    ButtonDataKey.SummarizationAction: action,
                                    ButtonDataKey.MaxMessages: maxMessages,
                                    ButtonDataKey.TopicId: topic["topic_id"],
                                }
                            ),
                        )
                    ]
                )

            keyboard.append(
                [
                    InlineKeyboardButton(
                        "<< Назад к списку чатов",
                        callback_data=utils.packDict(
                            {
                                ButtonDataKey.SummarizationAction: action,
                                ButtonDataKey.MaxMessages: maxMessages,
                            }
                        ),
                    )
                ]
            )

            keyboard.append([exitButton])

            await message.edit_text(
                text=f"Выбран чат {chatTitle}, выберите нужный топик:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        # TopicID Choosen
        topicTitle = ""
        if topicId is not None and isToticSummary:
            topics = self.cache.getChatTopicsInfo(chatId=chatId)
            if topicId in topics:
                topicTitle = f", топик **{topics[topicId]["name"]}**"
            else:
                logger.error(f"Topic with id #{topicId} is not found for chat #{chatId}. Found: ({topics.keys()})")

        dataTemplate: Dict[ButtonDataKey, str | int | None] = {
            ButtonDataKey.SummarizationAction: action,
            ButtonDataKey.ChatId: chatId,
            ButtonDataKey.MaxMessages: maxMessages,
        }
        if topicId is not None:
            dataTemplate[ButtonDataKey.TopicId] = topicId

        # Check If User need to Enter Messages/Prompt:
        userActionK = data.get(ButtonDataKey.UserAction, None)
        if userActionK is not None:
            userState = {
                **dataTemplate,
                ButtonDataKey.UserAction: userActionK,
                "message": message,
            }
            self.cache.setUserState(
                userId=userId,
                stateKey=UserActiveActionEnum.Summarization,
                value=userState,
            )

            keyboard: List[List[InlineKeyboardButton]] = [
                [
                    InlineKeyboardButton(
                        "Начать суммаризацию с текущими настройками",
                        callback_data=utils.packDict({**dataTemplate, ButtonDataKey.SummarizationAction: action + "+"}),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "<< Назад",
                        callback_data=utils.packDict(dataTemplate),  # pyright: ignore[reportArgumentType]
                    )
                ],
                [exitButton],
            ]

            match userActionK:
                case 1:
                    await message.edit_text(
                        text=markdown_to_markdownv2(
                            f"Выбран чат {chatTitle}{topicTitle}\n"
                            f"Укажите количество сообщений для суммаризации или нажмите нужную кнопку:"
                        ),
                        parse_mode="MarkdownV2",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
                case 2:
                    currentPrompt = chatSettings[ChatSettingsKey.SUMMARY_PROMPT].toStr()
                    userState[ButtonDataKey.SummarizationAction] = action + "+"
                    self.cache.setUserState(
                        userId=userId,
                        stateKey=UserActiveActionEnum.Summarization,
                        value=userState,
                    )

                    await message.edit_text(
                        text=markdown_to_markdownv2(
                            f"Выбран чат {chatTitle}{topicTitle}\n"
                            f"Текущий промпт для суммаризации:\n```\n{currentPrompt}\n```\n"
                            f"Укажите новый промпт или нажмите нужную кнопку:"
                        ),
                        parse_mode="MarkdownV2",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
                case _:
                    logger.error(f"Wrong summarisation user action {userActionK} in data {data}")
                    self.cache.clearUserState(userId=userId, stateKey=UserActiveActionEnum.Summarization)
                    await message.edit_text("Что-то пошло не так")
            return

        # Choose MaxMessages/Duration/Prompt
        if not action.endswith("+"):
            durationDescription = ""
            match maxMessages:
                case 0:
                    durationDescription = "За сегодня"
                case -1:
                    durationDescription = "За вчера"
                case _:
                    durationDescription = f"Последние {maxMessages} сообщений"

            keyboard: List[List[InlineKeyboardButton]] = [
                [
                    InlineKeyboardButton(
                        "Начать суммаризацию",
                        callback_data=utils.packDict({**dataTemplate, ButtonDataKey.SummarizationAction: action + "+"}),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Суммаризация за сегодня",
                        callback_data=utils.packDict({**dataTemplate, ButtonDataKey.MaxMessages: 0}),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Суммаризация за вчера",
                        callback_data=utils.packDict({**dataTemplate, ButtonDataKey.MaxMessages: -1}),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Установить количество сообщений для суммаризации",
                        callback_data=utils.packDict({**dataTemplate, ButtonDataKey.UserAction: 1}),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Установить промпт",
                        callback_data=utils.packDict({**dataTemplate, ButtonDataKey.UserAction: 2}),
                    )
                ],
                [exitButton],
            ]

            await message.edit_text(
                text=markdown_to_markdownv2(
                    f"Выбран чат {chatTitle}{topicTitle}\n"
                    f"Границы суммаризации: {durationDescription}\n"
                    "Вы можете поменять границы суммаризации или поменять промпт:"
                ),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        await message.edit_text("Суммаризирую сообщения...")

        today = datetime.datetime.now(datetime.timezone.utc)
        today = today.replace(hour=0, minute=0, second=0, microsecond=0)
        sinceDT = today
        tillDT: Optional[datetime.datetime] = None
        if maxMessages < 1:
            # if maxMessages == 0: # Summarisation for today, no special actions needed
            if maxMessages == -1:
                # Summarization for yesterday
                tillDT = today
                sinceDT = today - datetime.timedelta(days=1)
            maxMessages = None

        repliedMessage = message.reply_to_message

        ensuredMessage: Optional[EnsuredMessage] = None

        try:
            if repliedMessage is not None:
                ensuredMessage = EnsuredMessage.fromMessage(repliedMessage)
            else:
                ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"summarization: Error ensuring message: {type(e).__name__}{e}")
            logger.exception(e)
            await message.edit_text(str(e))
            return

        if ensuredMessage is None:
            await message.edit_text("ensuredMessage is None")
            return

        await self._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=chatId,
            threadId=topicId,
            chatSettings=chatSettings,
            sinceDT=sinceDT,
            tillDT=tillDT,
            summarizationPrompt=data.get(ButtonDataKey.Prompt, None),
            maxMessages=maxMessages,
        )

        if repliedMessage is not None:
            await message.delete()
        else:
            await message.edit_text("Суммаризация готова:")

    @commandHandler(
        commands=("summary", "topic_summary"),
        shortDescription="[<maxMessages>] [<chatId>] [<topicId>] - Summarise given chat "
        "(call without arguments to start wizard)",
        helpMessage=" `[<maxMessages>]` `[<chatId>]` `[<topicId>]`: Сделать суммаризацию чата "
        "(запускайте без аргументов для запуска мастера).",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.NORMAL,
    )
    async def summary_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /summary and /topic_summary commands, dood!
        
        Provides chat summarization functionality with two modes:
        - /summary: Summarizes entire chat or specified message range
        - /topic_summary: Summarizes specific topic/thread in supergroups
        
        In private chats, launches an interactive wizard if no arguments provided.
        In group chats, directly summarizes based on provided arguments.
        
        Args:
            update: Telegram update containing the command message
            context: Telegram context with command arguments:
                - args[0]: maxMessages (optional) - number of messages to summarize
                - args[1]: chatId (optional, private only) - target chat ID
                - args[2]: topicId (optional, private only) - target topic ID
                
        Command Formats:
            Private chat:
                /summary - Start wizard
                /summary <maxMessages> - Summarize with wizard for chat selection
                /summary <maxMessages> <chatId> - Summarize specific chat
                /summary <maxMessages> <chatId> <topicId> - Summarize specific topic
                
            Group/Supergroup:
                /summary - Summarize today's messages
                /summary <maxMessages> - Summarize last N messages
                /topic_summary - Summarize current topic today
                /topic_summary <maxMessages> - Summarize last N messages in topic
                
        Note:
            Requires ALLOW_SUMMARY setting to be enabled in chat settings.
            Bot owner can bypass this restriction in private chats.
        """
        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Failed to ensure message: {type(e).__name__}#{e}")
            return

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        commandStr = ""
        for entity in message.entities:
            if entity.type == MessageEntityType.BOT_COMMAND:
                commandStr = ensuredMessage.messageText[entity.offset : entity.offset + entity.length]
                break

        logger.debug(f"Command string: {commandStr}")
        isTopicSummary = commandStr.lower().startswith("/topic_summary")

        chatType = ensuredMessage.chat.type
        chatSettings = self.getChatSettings(chatId=ensuredMessage.chat.id)

        today = datetime.datetime.now(datetime.timezone.utc)
        today = today.replace(hour=0, minute=0, second=0, microsecond=0)
        maxMessages: Optional[int] = None
        chatId: Optional[int] = None
        threadId: Optional[int] = None

        match chatType:
            case Chat.PRIVATE:
                isBotOwner = await self.isAdmin(ensuredMessage.user, None, True)
                if not chatSettings[ChatSettingsKey.ALLOW_SUMMARY].toBool() and not isBotOwner:
                    logger.info(
                        f"Unauthorized /{commandStr} command from {ensuredMessage.user} "
                        f"in chat {ensuredMessage.chat}"
                    )
                    # await self.handle_message(update=update, context=context)
                    return

                maxMessages = 0
                intArgs: List[Optional[int]] = [None, None, None]
                if context.args:
                    for i in range(3):
                        if len(context.args) > i:
                            try:
                                intArgs[i] = int(context.args[i])
                            except ValueError:
                                logger.error(f"Invalid arguments: '{context.args[i]}' is not a valid number.")

                maxMessages = intArgs[0]
                chatId = intArgs[1]
                threadId = intArgs[2]
                jsonAction = "t" if isTopicSummary else "s"

                if maxMessages is None or maxMessages < 1:
                    maxMessages = 0

                if chatId is None:
                    msg = await self.sendMessage(
                        ensuredMessage,
                        messageText="Загружаю список чатов....",
                        messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    )

                    if msg is not None:
                        await self._handle_summarization(
                            {"s": jsonAction, "m": maxMessages}, message=msg, user=ensuredMessage.user
                        )
                    else:
                        logger.error("Message undefined")

                    return

                if threadId is None and isTopicSummary:
                    msg = await self.sendMessage(
                        ensuredMessage,
                        messageText="Загружаю список топиков....",
                        messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    )

                    if msg is not None:
                        await self._handle_summarization(
                            {"s": jsonAction, "c": chatId, "m": maxMessages}, message=msg, user=ensuredMessage.user
                        )
                    else:
                        logger.error("Message undefined")

                    return

                userChats = self.db.getUserChats(ensuredMessage.user.id)
                chatFound = isBotOwner
                for uChat in userChats:
                    if uChat["chat_id"] == chatId:
                        chatFound = True
                        break

                if not chatFound:
                    await self.sendMessage(
                        ensuredMessage, "Передан неверный ID чата", messageCategory=MessageCategory.BOT_ERROR
                    )
                    return

                if maxMessages == 0:
                    maxMessages = None

                return await self._doSummarization(
                    ensuredMessage,
                    chatId=chatId,
                    threadId=threadId,
                    chatSettings=chatSettings,  # TODO: Think: Should we get chat settings or user settings?
                    sinceDT=today,
                    maxMessages=maxMessages,
                )

            case Chat.GROUP | Chat.SUPERGROUP:
                if not chatSettings[ChatSettingsKey.ALLOW_SUMMARY].toBool():
                    logger.info(
                        f"Unauthorized /{commandStr} command from {ensuredMessage.user} "
                        f"in chat {ensuredMessage.chat}"
                    )
                    # await self.handle_message(update=update, context=context)
                    return

                if context.args and len(context.args) > 0:
                    try:
                        maxMessages = int(context.args[0])
                        if maxMessages < 1:
                            maxMessages = None
                    except ValueError:
                        logger.error(f"Invalid arguments: '{context.args[0]}' is not a valid number.")

                # Summary command print summary for whole chat.
                # Topic-summary prints summary for current topic, we threat default topic as 0
                if isTopicSummary:
                    threadId = ensuredMessage.threadId if ensuredMessage.threadId else 0

                return await self._doSummarization(
                    ensuredMessage=ensuredMessage,
                    chatId=ensuredMessage.chat.id,
                    threadId=threadId,
                    chatSettings=chatSettings,
                    maxMessages=maxMessages,
                    sinceDT=today,
                )

            case _:
                logger.error(f"Unsupported chat type for Summarization: {chatType}")

    async def buttonHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: Dict[str | int, str | int | float | bool | None]
    ) -> HandlerResultStatus:
        """
        Handle button callbacks for summarization wizard, dood!
        
        Processes inline keyboard button presses during the summarization
        wizard workflow, delegating to _handle_summarization for state management.
        
        Args:
            update: Telegram update containing the callback query
            context: Telegram context for the handler
            data: Parsed callback data dictionary containing wizard state
            
        Returns:
            HandlerResultStatus indicating handling result:
            - FINAL: Button was for summarization and was processed
            - SKIPPED: Button was not for summarization
            - FATAL: Missing required data in callback
            
        Note:
            Checks for ButtonDataKey.SummarizationAction in data to determine
            if this button is part of the summarization workflow.
        """

        query = update.callback_query
        if query is None:
            logger.error("handle_button: query is None")
            return HandlerResultStatus.FATAL

        user = query.from_user

        if query.message is None:
            logger.error(f"handle_button: message is None in {query}")
            return HandlerResultStatus.FATAL

        if not isinstance(query.message, Message):
            logger.error(f"handle_button: message is not a Message in {query}")
            return HandlerResultStatus.FATAL

        summaryAction = data.get(ButtonDataKey.SummarizationAction, None)
        # Used keys:
        # s: Action
        # c: ChatId
        # t: topicId
        # m: MaxMessages/time
        if summaryAction is not None:
            await self._handle_summarization(data, query.message, user)
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.SKIPPED
