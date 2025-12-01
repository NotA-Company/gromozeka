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
from typing import Dict, List, Optional

import lib.utils as utils
from internal.bot import constants
from internal.bot.common.models import CallbackButton, UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    ButtonDataKey,
    ButtonSummarizationAction,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    LLMMessageFormat,
    MessageSender,
    commandHandlerV2,
)
from internal.database.models import (
    ChatInfoDict,
    ChatMessageDict,
    MessageCategory,
)
from internal.models import MessageIdType
from internal.services.cache import UserActiveActionEnum, UserActiveConfigurationDict
from lib.ai import (
    ModelMessage,
    ModelRunResult,
)

from .base import BaseBotHandler, HandlerResultStatus

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

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
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
        if ensuredMessage.recipient.chatType != ChatType.PRIVATE:
            return HandlerResultStatus.SKIPPED

        user = ensuredMessage.sender
        messageText = ensuredMessage.getParsedMessageText()

        activeSummarization = self.cache.getUserState(userId=user.id, stateKey=UserActiveActionEnum.Summarization)
        if activeSummarization is None:
            return HandlerResultStatus.SKIPPED

        data = activeSummarization["data"]
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
                logger.error(f"Wrong K in data {activeSummarization}")
        await self._handle_summarization(
            data=data,
            messageId=activeSummarization["messageId"],
            messageChatId=activeSummarization["messageChatId"],
            user=user,
        )
        return HandlerResultStatus.FINAL

    async def _doSummarization(
        self,
        ensuredMessage: EnsuredMessage,
        *,
        chatId: int,
        threadId: Optional[int],
        chatSettings: Dict[ChatSettingsKey, ChatSettingsValue],
        sinceDT: Optional[datetime.datetime] = None,
        tillDT: Optional[datetime.datetime] = None,
        maxMessages: Optional[int] = None,
        summarizationPrompt: Optional[str] = None,
        useCache: bool = True,
        typingManager: Optional[TypingManager] = None,
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

        if typingManager is None:
            # summarization is long process, let's set timeout to 10 minutes
            typingManager = await self.startTyping(ensuredMessage, maxTimeout=600)
        else:
            typingManager.maxTimeout = typingManager.maxTimeout + 600

        messages = self.db.getChatMessagesSince(
            chatId=chatId,
            sinceDateTime=sinceDT if maxMessages is None else None,
            tillDateTime=tillDT if maxMessages is None else None,
            threadId=threadId,
            limit=maxMessages,
            messageCategory=[MessageCategory.USER, MessageCategory.BOT, MessageCategory.CHANNEL],
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
                maxIdx = len(resMessages) - 1
                for idx, msg in enumerate(resMessages):
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=msg,
                        messageCategory=MessageCategory.BOT_SUMMARY,
                        typingManager=typingManager if idx >= maxIdx else None,
                    )
                    time.sleep(0.5)
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

        maxIdx = len(resMessages) - 1
        for idx, msg in enumerate(resMessages):
            await self.sendMessage(
                ensuredMessage,
                messageText=msg,
                messageCategory=MessageCategory.BOT_SUMMARY,
                typingManager=typingManager if idx >= maxIdx else None,
            )
            time.sleep(0.5)

    async def _handle_summarization(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageIdType,
        messageChatId: int,
        user: MessageSender,
    ):
        """
        Handle the summarization process for messages, dood!

        Processes the summarization request based on user action and generates
        a summary of the specified messages or chat history.

        Args:
            data: Dictionary containing summarization parameters and options
            messageId: ID of the message that triggered the summarization
            user: User who requested the summarization
            bot: Telegram bot instance for sending messages
        """

        chatSettings = self.getChatSettings(messageChatId)
        self.cache.clearUserState(userId=user.id, stateKey=UserActiveActionEnum.Summarization)

        exitButton = CallbackButton(
            "Отмена",
            {ButtonDataKey.SummarizationAction: ButtonSummarizationAction.Cancel},
        )
        action: Optional[str] = str(data.get(ButtonDataKey.SummarizationAction, None))
        if action is None or action not in ButtonSummarizationAction.all():
            raise ValueError(f"Wrong action in {data}")

        if action == ButtonSummarizationAction.Cancel:
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Суммаризация отменена",
            )
            return

        isToticSummary = action.startswith("t")

        maxMessages = data.get(ButtonDataKey.MaxMessages, None)
        if not isinstance(maxMessages, int):
            maxMessages = 0

        userChats = self.db.getUserChats(user.id)

        chatId = data.get(ButtonDataKey.ChatId, None)
        # Choose chatID
        if not isinstance(chatId, int):
            keyboard: List[List[CallbackButton]] = []
            # chatSettings = self.getChatSettings(ensuredMessage.chat.id)
            for chat in userChats:
                chatTitle = self.getChatTitle(chat, useMarkdown=False, addChatId=False)
                keyboard.append(
                    [
                        CallbackButton(
                            chatTitle,
                            {
                                ButtonDataKey.ChatId: chat["chat_id"],
                                ButtonDataKey.SummarizationAction: action,
                                ButtonDataKey.MaxMessages: maxMessages,
                            },
                        )
                    ]
                )

            if not keyboard:
                await self.editMessage(
                    messageId=messageId,
                    chatId=messageChatId,
                    text="Вы не найдены ни в одном чате.",
                )
                return

            keyboard.append([exitButton])
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Выберите чат для суммаризации:",
                inlineKeyboard=keyboard,
            )
            return

        # BotOwner cat summarize any chat
        chatFound = await self.isAdmin(user, None, True)
        chatInfo: Optional[ChatInfoDict] = None
        for chat in userChats:
            if chat["chat_id"] == chatId:
                chatFound = True
                chatInfo = chat
                break

        if not chatFound or chatInfo is None:
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Указан неверный чат",
            )
            return

        # ChatID Choosen
        chatTitle = self.getChatTitle(chatInfo)

        topicId = data.get(ButtonDataKey.TopicId, None)
        if not isinstance(topicId, int):
            topicId = None
        # Choose TopicID if needed
        if isToticSummary and topicId is None:
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

            keyboard: List[List[CallbackButton]] = []

            for topic in topics:
                keyboard.append(
                    [
                        CallbackButton(
                            str(topic["name"]),
                            {
                                ButtonDataKey.ChatId: chatId,
                                ButtonDataKey.SummarizationAction: action,
                                ButtonDataKey.MaxMessages: maxMessages,
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
                            ButtonDataKey.SummarizationAction: action,
                            ButtonDataKey.MaxMessages: maxMessages,
                        },
                    )
                ]
            )

            keyboard.append([exitButton])

            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text=f"Выбран чат {chatTitle}, выберите нужный топик:",
                inlineKeyboard=keyboard,
            )
            return

        # TopicID Choosen or not needed
        topicTitle = ""
        if topicId is not None and isToticSummary:
            topics = self.cache.getChatTopicsInfo(chatId=chatId)
            if topicId in topics:
                topicTitle = f", топик **{topics[int(topicId)]["name"]}**"
            else:
                logger.error(f"Topic with id #{topicId} is not found for chat #{chatId}. Found: ({topics.keys()})")

        dataTemplate: Dict[ButtonDataKey, str | int | float | None] = {
            ButtonDataKey.SummarizationAction: action,
            ButtonDataKey.ChatId: chatId,
            ButtonDataKey.MaxMessages: maxMessages,
        }
        if topicId is not None:
            dataTemplate[ButtonDataKey.TopicId] = topicId

        # Check If User need to Enter Messages/Prompt:
        userActionK = data.get(ButtonDataKey.UserAction, None)
        if userActionK is not None:
            userState: UserActiveConfigurationDict = {
                "data": {
                    **dataTemplate,
                    ButtonDataKey.UserAction: userActionK,
                },
                "messageId": messageId,
                "messageChatId": messageChatId,
            }
            self.cache.setUserState(
                userId=user.id,
                stateKey=UserActiveActionEnum.Summarization,
                value=userState,
            )

            keyboard: List[List[CallbackButton]] = [
                [
                    CallbackButton(
                        "Начать суммаризацию с текущими настройками",
                        {**dataTemplate, ButtonDataKey.SummarizationAction: action + "+"},
                    )
                ],
                [
                    CallbackButton(
                        "<< Назад",
                        {**dataTemplate},
                    )
                ],
                [exitButton],
            ]

            match userActionK:
                case 1:
                    # Set messages count
                    await self.editMessage(
                        messageId=messageId,
                        chatId=messageChatId,
                        text=f"Выбран чат {chatTitle}{topicTitle}\n"
                        f"Укажите количество сообщений для суммаризации или нажмите нужную кнопку:",
                        inlineKeyboard=keyboard,
                    )
                case 2:
                    # Set summarization prompt
                    currentPrompt = chatSettings[ChatSettingsKey.SUMMARY_PROMPT].toStr()
                    userState["data"][ButtonDataKey.SummarizationAction] = action + "+"
                    self.cache.setUserState(
                        userId=user.id,
                        stateKey=UserActiveActionEnum.Summarization,
                        value=userState,
                    )

                    await self.editMessage(
                        messageId=messageId,
                        chatId=messageChatId,
                        text=f"Выбран чат {chatTitle}{topicTitle}\n"
                        f"Текущий промпт для суммаризации:\n```\n{currentPrompt}\n```\n"
                        f"Укажите новый промпт или нажмите нужную кнопку:",
                        inlineKeyboard=keyboard,
                    )
                case _:
                    logger.error(f"Wrong summarisation user action {userActionK} in data {data}")
                    self.cache.clearUserState(userId=user.id, stateKey=UserActiveActionEnum.Summarization)
                    await self.editMessage(
                        messageId=messageId,
                        chatId=messageChatId,
                        text="Что-то пошло не так",
                    )
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

            keyboard: List[List[CallbackButton]] = [
                [
                    CallbackButton(
                        "Начать суммаризацию",
                        {**dataTemplate, ButtonDataKey.SummarizationAction: action + "+"},
                    )
                ],
                [
                    CallbackButton(
                        "Суммаризация за сегодня",
                        {**dataTemplate, ButtonDataKey.MaxMessages: 0},
                    )
                ],
                [
                    CallbackButton(
                        "Суммаризация за вчера",
                        {**dataTemplate, ButtonDataKey.MaxMessages: -1},
                    )
                ],
                [
                    CallbackButton(
                        "Установить количество сообщений для суммаризации",
                        {**dataTemplate, ButtonDataKey.UserAction: 1},
                    )
                ],
                [
                    CallbackButton(
                        "Установить промпт",
                        {**dataTemplate, ButtonDataKey.UserAction: 2},
                    )
                ],
                [exitButton],
            ]

            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text=f"Выбран чат {chatTitle}{topicTitle}\n"
                f"Границы суммаризации: {durationDescription}\n"
                "Вы можете поменять границы суммаризации или поменять промпт:",
                inlineKeyboard=keyboard,
            )
            return

        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text="Суммаризирую сообщения...",
        )

        today = datetime.datetime.now(datetime.timezone.utc)
        today = today.replace(hour=0, minute=0, second=0, microsecond=0)
        sinceDT = today
        tillDT: Optional[datetime.datetime] = None
        if maxMessages < 1:
            # if maxMessages == 0: # Summarisation for today, no special actions needed
            if maxMessages < 0:
                # Summarization for -X days (-1 - yesterday, -2 - two days ago, etc...)
                tillDT = today - datetime.timedelta(days=(-maxMessages) - 1)
                sinceDT = today - datetime.timedelta(days=-maxMessages)
            maxMessages = None

        # We need to Make Message object manually here
        #  as only messageId could be properly preserver across bot restarts
        dbMessage = self.db.getChatMessageByMessageId(chatId=messageChatId, messageId=messageId)
        if dbMessage is None:
            logger.error(f"summarization: Message #{messageChatId}:{messageId} not found in Database")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text=f"Товарищ {user.name}, произошла чудовищная ошибка!",
            )
            return

        dbRepliedMessage: Optional[ChatMessageDict] = None
        ensuredMessage: Optional[EnsuredMessage] = None
        if dbMessage["reply_id"]:
            dbRepliedMessage = self.db.getChatMessageByMessageId(chatId=messageChatId, messageId=dbMessage["reply_id"])
            if dbRepliedMessage is not None:
                ensuredMessage = EnsuredMessage.fromDBChatMessage(dbRepliedMessage)

        if ensuredMessage is None:
            ensuredMessage = EnsuredMessage.fromDBChatMessage(dbMessage)

        await self._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=chatId,
            threadId=topicId,
            chatSettings=chatSettings,
            sinceDT=sinceDT,
            tillDT=tillDT,
            summarizationPrompt=str(data.get(ButtonDataKey.Prompt, "")) if ButtonDataKey.Prompt in data else None,
            maxMessages=maxMessages,
        )

        if dbRepliedMessage is not None:
            await self.deleteMessagesById(chatId=messageChatId, messageIds=[messageId])
        else:
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Суммаризация готова:",
            )

    @commandHandlerV2(
        commands=("summary", "topic_summary"),
        shortDescription="[<maxMessages>] - Start summarization wizard",
        helpMessage=" `[<maxMessages>]`: В Личке - открыть мастер суммаризации, "
        "в групповом чате - провести суммаризацию за сегодня (или на основе переданного количества сообщений).",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def summary_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
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

            Group/Supergroup:
                /summary - Summarize today's messages
                /summary <maxMessages> - Summarize last N messages
                /topic_summary - Summarize current topic today
                /topic_summary <maxMessages> - Summarize last N messages in topic

        Note:
            Bot owner can bypass this restriction in private chats.
        """

        isTopicSummary = command.lower().startswith("topic_summary")

        maxMessages: Optional[int] = utils.extractInt(args.split(maxsplit=1))

        match ensuredMessage.recipient.chatType:
            case ChatType.PRIVATE:
                # In private chat - start summarization wizard
                if maxMessages is None:
                    maxMessages = 0

                msg = await self.sendMessage(
                    ensuredMessage,
                    messageText="Загружаю список чатов....",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )
                if msg:
                    await self._handle_summarization(
                        {
                            ButtonDataKey.SummarizationAction: (
                                ButtonSummarizationAction.TopicSummarization
                                if isTopicSummary
                                else ButtonSummarizationAction.Summarization
                            ),
                            ButtonDataKey.MaxMessages: maxMessages,
                        },
                        # {"s": jsonAction, "c": chatId, "m": maxMessages},
                        messageId=msg[0].messageId,
                        messageChatId=msg[0].recipient.id,
                        user=ensuredMessage.sender,
                    )
                else:
                    logger.error("Message undefined")

                return

            case ChatType.GROUP:
                # Summary command print summary for whole chat.
                # Topic-summary prints summary for current topic, we threat default topic as 0
                today = datetime.datetime.now(datetime.timezone.utc)
                today = today.replace(hour=0, minute=0, second=0, microsecond=0)

                threadId: Optional[int] = None
                if isTopicSummary:
                    threadId = ensuredMessage.threadId if ensuredMessage.threadId else 0

                chatSettings = self.getChatSettings(chatId=ensuredMessage.recipient.id)
                return await self._doSummarization(
                    ensuredMessage=ensuredMessage,
                    chatId=ensuredMessage.recipient.id,
                    threadId=threadId,
                    chatSettings=chatSettings,
                    maxMessages=maxMessages,
                    sinceDT=today,
                    typingManager=typingManager,
                )

            case _:
                logger.error(f"Unsupported chat type for Summarization: {ensuredMessage.recipient.chatType}")

    async def callbackHandler(
        self,
        ensuredMessage: EnsuredMessage,
        data: utils.PayloadDict,
        user: MessageSender,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        """
        TODO
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

        summaryAction = data.get(ButtonDataKey.SummarizationAction, None)
        # Used keys:
        # s: Action
        # c: ChatId
        # t: topicId
        # m: MaxMessages/time
        if summaryAction is not None:
            await self._handle_summarization(
                data,
                messageId=ensuredMessage.messageId,
                messageChatId=ensuredMessage.recipient.id,
                user=user,
            )
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.SKIPPED
