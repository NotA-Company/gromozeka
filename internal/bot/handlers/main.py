"""
Telegram bot command handlers for Gromozeka.
"""

import datetime
import logging
import re

import random
import time
from typing import Any, Dict, List, Optional

import requests

from telegram import Chat, Update, Message, User
from telegram.ext import ContextTypes

from internal.services.llm.service import LLMService

from lib.ai.abstract import AbstractModel
from lib.ai.models import (
    LLMFunctionParameter,
    LLMParameterType,
    ModelMessage,
    ModelRunResult,
    ModelResultStatus,
)
from lib.ai.manager import LLMManager
import lib.utils as utils

from internal.config.manager import ConfigManager

from internal.database.wrapper import DatabaseWrapper
from internal.database.models import ChatMessageDict, MessageCategory

from ..models import (
    ChatSettingsKey,
    CommandCategory,
    CommandHandlerOrder,
    DelayedTask,
    DelayedTaskFunction,
    EnsuredMessage,
    LLMMessageFormat,
    MessageType,
    commandHandler,
)
from .. import constants
from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class BotHandlers(BaseBotHandler):
    """Contains all bot command and message handlers, dood!"""

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        """Initialize handlers with database and LLM model."""
        # Initialize the mixin (discovers handlers)
        super().__init__(configManager=configManager, database=database, llmManager=llmManager)

        self.llmService = LLMService.getInstance()

        self.llmService.registerTool(
            name="get_url_content",
            description="Get the content of a URL",
            parameters=[
                LLMFunctionParameter(
                    name="url",
                    description="The URL to get the content from",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
            ],
            handler=self._llmToolGetUrlContent,
        )

        self.llmService.registerTool(
            name="get_current_datetime",
            description="Get current date and time",
            parameters=[],
            handler=self._llmToolGetCurrentDateTime,
        )

        self.queueService.registerDelayedTaskHandler(
            DelayedTaskFunction.SEND_MESSAGE,
            self._dqSendMessageHandler,
        )
        self.queueService.registerDelayedTaskHandler(
            DelayedTaskFunction.DELETE_MESSAGE,
            self._dqDeleteMessageHandler,
        )

    ###
    # Delayed Queue Handlers
    ###
    async def _dqSendMessageHandler(self, delayedTask: DelayedTask) -> None:
        kwargs = delayedTask.kwargs
        message = Message(
            message_id=kwargs["messageId"],
            date=datetime.datetime.now(),
            chat=Chat(id=kwargs["chatId"], type=kwargs["chatType"]),
            from_user=User(id=kwargs["userId"], first_name="", is_bot=False),
            text=kwargs["messageText"],
            message_thread_id=kwargs["threadId"],
        )
        message.set_bot(self._bot)
        ensuredMessage = EnsuredMessage.fromMessage(message)
        await self.sendMessage(
            replyToMessage=ensuredMessage,
            messageText=kwargs["messageText"],
            messageCategory=kwargs["messageCategory"],
        )

    async def _dqDeleteMessageHandler(self, delayedTask: DelayedTask) -> None:
        kwargs = delayedTask.kwargs
        if self._bot is not None:
            await self._bot.delete_message(chat_id=kwargs["chatId"], message_id=kwargs["messageId"])
        else:
            logger.error(
                "Bot is not initialized, can't delete message " f"{kwargs['messageId']} in chat {kwargs['chatId']}"
            )

    ###
    # LLM Tool-Calling handlers
    ###

    async def _llmToolGetUrlContent(self, extraData: Optional[Dict[str, Any]], url: str, **kwargs) -> str:
        # TODO: Check if content is text content
        try:
            return str(requests.get(url).content)
        except Exception as e:
            logger.error(f"Error getting content from {url}: {e}")
            return utils.jsonDumps({"done": False, "errorMessage": str(e)})

    async def _llmToolGetCurrentDateTime(self, extraData: Optional[Dict[str, Any]], **kwargs) -> str:
        now = datetime.datetime.now(datetime.timezone.utc)
        return utils.jsonDumps({"datetime": now.isoformat(), "timestamp": now.timestamp(), "timezone": "UTC"})

    ###
    # Some message helpers
    ###

    async def _generateTextViaLLM(
        self,
        model: AbstractModel,
        messages: List[ModelMessage],
        fallbackModel: AbstractModel,
        ensuredMessage: EnsuredMessage,
        context: ContextTypes.DEFAULT_TYPE,
        useTools: bool = False,
        sendIntermediateMessages: bool = True,
    ) -> ModelRunResult:
        """Call the LLM with the given messages."""

        async def processIntermediateMessages(mRet: ModelRunResult, extraData: Optional[Dict[str, Any]]) -> None:
            if mRet.resultText and sendIntermediateMessages:
                try:
                    await self.sendMessage(ensuredMessage, mRet.resultText, messageCategory=MessageCategory.BOT)
                except Exception as e:
                    logger.error(f"Failed to send intermediate message: {e}")

        ret = await self.llmService.generateTextViaLLM(
            model=model,
            fallbackModel=fallbackModel,
            messages=messages,
            useTools=useTools,
            callId=f"{ensuredMessage.chat.id}:{ensuredMessage.messageId}",
            callback=processIntermediateMessages,
            extraData={"ensuredMessage": ensuredMessage},
        )
        return ret

    async def _sendLLMChatMessage(
        self,
        ensuredMessage: EnsuredMessage,
        messagesHistory: List[ModelMessage],
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        """Send a chat message to the LLM model."""
        # For logging purposes
        messageHistoryStr = ""
        for msg in messagesHistory:
            messageHistoryStr += f"\t{repr(msg)}\n"
        logger.debug(f"LLM Request messages: List[\n{messageHistoryStr}]")
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        llmModel = chatSettings[ChatSettingsKey.CHAT_MODEL].toModel(self.llmManager)
        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())
        mlRet: Optional[ModelRunResult] = None

        try:
            mlRet = await self._generateTextViaLLM(
                model=llmModel,
                messages=messagesHistory,
                fallbackModel=chatSettings[ChatSettingsKey.FALLBACK_MODEL].toModel(self.llmManager),
                ensuredMessage=ensuredMessage,
                context=context,
                useTools=chatSettings[ChatSettingsKey.USE_TOOLS].toBool(),
            )
            # logger.debug(f"LLM Response: {mlRet}")
        except Exception as e:
            logger.error(f"Error while sending LLM request: {type(e).__name__}#{e}")
            logger.exception(e)
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Error while sending LLM request: {type(e).__name__}",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return False

        addPrefix = ""
        if mlRet.isFallback:
            addPrefix += chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr()
        if mlRet.isToolsUsed:
            addPrefix += chatSettings[ChatSettingsKey.TOOLS_USED_PREFIX].toStr()

        lmRetText = mlRet.resultText.strip()
        imagePrompt: Optional[str] = None
        # Check if <media-description> is in the message
        if llmMessageFormat != LLMMessageFormat.JSON:
            if lmRetText.startswith("<media-description>"):
                # Extract content in <media-description> tag to imagePrompt variable and strip from lmRetText
                match = re.search(r"^<media-description>(.*?)</media-description>(.*?)", lmRetText, re.DOTALL)
                if match:
                    imagePrompt = match.group(1).strip()
                    lmRetText = match.group(2).strip()
                    logger.debug(
                        f"Found <media-description> in answer, generating image ('{imagePrompt}' + '{lmRetText}')"
                    )

        # TODO: Treat JSON format as well

        # TODO: Add separate method for generating+sending photo
        if imagePrompt is not None:
            imageGenerationModel = chatSettings[ChatSettingsKey.IMAGE_GENERATION_MODEL].toModel(self.llmManager)
            fallbackImageLLM = chatSettings[ChatSettingsKey.IMAGE_GENERATION_FALLBACK_MODEL].toModel(self.llmManager)

            imgMLRet = await imageGenerationModel.generateImageWithFallBack(
                [ModelMessage(content=imagePrompt)], fallbackImageLLM
            )
            logger.debug(
                f"Generated image Data: {imgMLRet} for mcID: " f"{ensuredMessage.chat.id}:{ensuredMessage.messageId}"
            )

            if imgMLRet.status == ModelResultStatus.FINAL and imgMLRet.mediaData is not None:
                imgAddPrefix = ""
                if imgMLRet.isFallback:
                    imgAddPrefix = chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr()
                return (
                    await self.sendMessage(
                        ensuredMessage,
                        photoData=imgMLRet.mediaData,
                        photoCaption=lmRetText,
                        mediaPrompt=imagePrompt,
                        addMessagePrefix=imgAddPrefix,
                    )
                    is not None
                )

            # Something went wrong, log and fallback to ordinary message
            logger.error(f"Failed generating Image by prompt '{imagePrompt}': {imgMLRet}")

        return (
            await self.sendMessage(
                ensuredMessage,
                messageText=lmRetText,
                addMessagePrefix=addPrefix,
                tryParseInputJSON=llmMessageFormat == LLMMessageFormat.JSON,
            )
            is not None
        )

    async def _delayedSendMessage(
        self,
        ensuredMessage: EnsuredMessage,
        delayedUntil: float,
        messageText: str,
        messageCategory: MessageCategory = MessageCategory.BOT,
    ) -> None:
        """Send a message after a delay."""

        functionName = DelayedTaskFunction.SEND_MESSAGE
        kwargs = {
            "messageText": messageText,
            "messageCategory": messageCategory,
            "messageId": ensuredMessage.messageId,
            "threadId": ensuredMessage.threadId,
            "chatId": ensuredMessage.chat.id,
            "userId": ensuredMessage.user.id,
            "chatType": ensuredMessage.chat.type,
        }

        return await self.queueService.addDelayedTask(delayedUntil=delayedUntil, function=functionName, kwargs=kwargs)

    ###
    # Handling messages
    ###

    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
        if ensuredMessage is None:
            # Not new message, Skip
            return HandlerResultStatus.SKIPPED

        chat = ensuredMessage.chat
        chatType = chat.type

        match chatType:
            case Chat.PRIVATE:
                chatSettings = self.getChatSettings(chat.id)
                if not chatSettings[ChatSettingsKey.ALLOW_PRIVATE].toBool():
                    return HandlerResultStatus.SKIPPED
            case Chat.GROUP:
                pass
            case Chat.SUPERGROUP:
                pass
            case Chat.CHANNEL:
                logger.error(f"Unsupported chat type: {chatType}")
                return HandlerResultStatus.SKIPPED
            case _:
                logger.error(f"Unsupported chat type: {chatType}")
                return HandlerResultStatus.ERROR

        message = ensuredMessage.getBaseMessage()

        if message.is_automatic_forward:
            # Automatic forward from licked Channel
            # TODO: Somehow process automatic forwards
            # TODO: Think about handleRandomMessage here
            # return HandlerResultStatus.SKIPPED
            return HandlerResultStatus.FINAL

        # Check if message is a reply to our message
        # TODO: Move to separate handler?
        if await self.handleReply(update, context, ensuredMessage):
            return HandlerResultStatus.FINAL

        # Check if bot was mentioned
        # TODO: Move to separate handler?
        if await self.handleMention(update, context, ensuredMessage):
            return HandlerResultStatus.FINAL

        if ensuredMessage.chat.type == Chat.PRIVATE:
            # TODO: Move to separate handler?
            if await self.handlePrivateMessage(update, context, ensuredMessage):
                return HandlerResultStatus.FINAL
        else:
            # TODO: Move to separate handler?
            if await self.handleRandomMessage(update, context, ensuredMessage):
                return HandlerResultStatus.FINAL

        # return HandlerResultStatus.NEXT
        return HandlerResultStatus.FINAL

    async def handleReply(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        ensuredMessage: EnsuredMessage,
    ) -> bool:
        """
        Check if message is a reply to our message and handle it
        """
        if not ensuredMessage.isReply or ensuredMessage.replyId is None:
            return False

        chatSettings = self.getChatSettings(chatId=ensuredMessage.chat.id)
        if not chatSettings[ChatSettingsKey.ALLOW_REPLY].toBool():
            return False

        message = ensuredMessage.getBaseMessage()
        isReplyToMyMessage = False
        if (
            message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.id == context.bot.id
        ):
            isReplyToMyMessage = True

        if not isReplyToMyMessage:
            return False

        logger.debug("It is reply to our message, processing reply...")

        # As it's resporse to our message, we need to wait for media to be processed if any
        await ensuredMessage.updateMediaContent(self.db)

        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())

        parentId = ensuredMessage.replyId
        chat = ensuredMessage.chat

        storedMessages: List[ModelMessage] = []

        storedMsg = self.db.getChatMessageByMessageId(
            chatId=chat.id,
            messageId=parentId,
        )
        if storedMsg is None:
            logger.error("Failed to get parent message")
            if not message.reply_to_message:
                logger.error("message.reply_to_message is None, but should be Message()")
                return False
            ensuredReply = EnsuredMessage.fromMessage(message.reply_to_message)
            storedMessages.append(await ensuredReply.toModelMessage(self.db, format=llmMessageFormat, role="assistant"))
            storedMessages.append(await ensuredMessage.toModelMessage(self.db, format=llmMessageFormat, role="user"))

        else:
            if storedMsg["user_id"] != context.bot.id:
                logger.error(f"Parent message is not from us: {storedMsg}")
                return False

            if storedMsg["root_message_id"] is None:
                logger.error(f"root_message_id in {storedMsg}")
                return False

            _storedMessages = self.db.getChatMessagesByRootId(
                chatId=chat.id,
                rootMessageId=storedMsg["root_message_id"],
                threadId=ensuredMessage.threadId,
            )
            storedMessages = []
            # lastMessageId = len(_storedMessages) - 1

            for storedMsg in _storedMessages:
                eMsg = EnsuredMessage.fromDBChatMessage(storedMsg)
                self._updateEMessageUserData(eMsg)

                storedMessages.append(
                    await eMsg.toModelMessage(
                        self.db,
                        format=llmMessageFormat,
                        role="user" if storedMsg["message_category"] == "user" else "assistant",
                    )
                )

        reqMessages = [
            ModelMessage(
                role="system",
                content=chatSettings[ChatSettingsKey.CHAT_PROMPT].toStr()
                + "\n"
                + chatSettings[ChatSettingsKey.CHAT_PROMPT_SUFFIX].toStr(),
            ),
        ] + storedMessages

        if not await self._sendLLMChatMessage(ensuredMessage, reqMessages, context):
            logger.error("Failed to send LLM reply")

        return True

    async def handleMention(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        ensuredMessage: EnsuredMessage,
    ) -> bool:
        """
        Check if bot has been mentioned in the message
        """

        message = ensuredMessage.getBaseMessage()
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())

        if not chatSettings[ChatSettingsKey.ALLOW_MENTION].toBool():
            return False

        _mentionedMe = self.checkEMMentionsMe(ensuredMessage)
        messageText = _mentionedMe.restText or ""
        mentionedAtBegin = _mentionedMe.byName is not None and _mentionedMe.byName[0] == 0
        mentionedMe = _mentionedMe.byName is not None
        mentionedByNick = _mentionedMe.byNick is not None

        messageTextLower = messageText.lower()

        if not mentionedByNick and not mentionedAtBegin and not mentionedMe:
            return False

        logger.debug(
            f"Mention found, processing... (mentionByNick={mentionedByNick}, "
            f"mentionAtBegin={mentionedAtBegin}, mentionedMe={mentionedMe})"
        )

        messageTextLower = messageText.lower()

        ###
        # Who today: Random choose from users who were active today
        ###
        whoToday = "кто сегодня "
        if messageTextLower.startswith(whoToday):
            userTitle = messageText[len(whoToday) :].strip()
            if userTitle[-1] == "?":
                userTitle = userTitle[:-1]

            today = datetime.datetime.now(datetime.timezone.utc)
            today = today.replace(hour=0, minute=0, second=0, microsecond=0)
            users = self.db.getChatUsers(
                chatId=ensuredMessage.chat.id,
                limit=100,
                seenSince=today,
            )

            user = users[random.randint(0, len(users) - 1)]
            while user["user_id"] == context.bot.id:
                # Do not allow bot to choose itself
                user = users[random.randint(0, len(users) - 1)]

            logger.debug(f"Found user for candidate of being '{userTitle}': {user}")
            return (
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"{user['username']} сегодня {userTitle}",
                )
                is not None
            )

        # End of Who Today

        # Handle LLM Action
        reqMessages = [
            ModelMessage(
                role="system",
                content=chatSettings[ChatSettingsKey.CHAT_PROMPT].toStr()
                + "\n"
                + chatSettings[ChatSettingsKey.CHAT_PROMPT_SUFFIX].toStr(),
            ),
        ]

        # Add Parent message if any
        if ensuredMessage.isReply and message.reply_to_message:
            ensuredReply = EnsuredMessage.fromMessage(message.reply_to_message)
            self._updateEMessageUserData(ensuredReply)
            if ensuredReply.messageType == MessageType.TEXT:
                reqMessages.append(
                    await ensuredReply.toModelMessage(
                        self.db,
                        format=llmMessageFormat,
                        role=("assistant" if ensuredReply.user.id == context.bot.id else "user"),
                    ),
                )
            else:
                # Not text message, try to get it content from DB
                storedReply = self.db.getChatMessageByMessageId(
                    chatId=ensuredReply.chat.id,
                    messageId=ensuredReply.messageId,
                )
                if storedReply is None:
                    logger.error(
                        f"Failed to get parent message (ChatId: {ensuredReply.chat.id}, "
                        f"MessageId: {ensuredReply.messageId})"
                    )
                else:
                    eStoredReply = EnsuredMessage.fromDBChatMessage(storedReply)
                    self._updateEMessageUserData(eStoredReply)
                    reqMessages.append(
                        await eStoredReply.toModelMessage(
                            self.db,
                            format=llmMessageFormat,
                            role=("assistant" if ensuredReply.user.id == context.bot.id else "user"),
                        ),
                    )

        # Add user message
        reqMessages.append(
            await ensuredMessage.toModelMessage(
                self.db,
                format=llmMessageFormat,
                role="user",
            ),
        )

        if not await self._sendLLMChatMessage(ensuredMessage, reqMessages, context):
            logger.error("Failed to send LLM reply")
            return False

        return True

    async def handlePrivateMessage(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        ensuredMessage: EnsuredMessage,
    ) -> bool:
        """Process message in private chat"""
        # If it message in private chat and no other methods catched message,
        # then just do LLM answer with context of last constants.PRIVATE_CHAT_CONTEXT_LENGTH messages

        messages = self.db.getChatMessagesSince(ensuredMessage.chat.id, limit=constants.PRIVATE_CHAT_CONTEXT_LENGTH)
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())

        # Handle LLM Action
        reqMessages = [
            ModelMessage(
                role="system",
                content=chatSettings[ChatSettingsKey.CHAT_PROMPT].toStr()
                + "\n"
                + chatSettings[ChatSettingsKey.CHAT_PROMPT_SUFFIX].toStr(),
            ),
        ]

        for message in reversed(messages):
            eMessage = EnsuredMessage.fromDBChatMessage(message)
            self._updateEMessageUserData(eMessage)

            reqMessages.append(
                await eMessage.toModelMessage(
                    self.db,
                    format=llmMessageFormat,
                    role=("user" if message["message_category"] == "user" else "assistant"),
                )
            )

        if not await self._sendLLMChatMessage(ensuredMessage, reqMessages, context):
            logger.error("Failed to send LLM reply")
            return False

        return True

    async def handleRandomMessage(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        ensuredMessage: EnsuredMessage,
    ) -> bool:
        """Randomly answer message with probability RANDOM_ANSWER_PROBABILITY"""

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        answerProbability = chatSettings[ChatSettingsKey.RANDOM_ANSWER_PROBABILITY].toFloat()
        if answerProbability <= 0.0:
            # logger.debug(
            #    f"answerProbability is {answerProbability} "
            #    f"({chatSettings[ChatSettingsKey.RANDOM_ANSWER_PROBABILITY].toStr()})"
            # )
            return False

        answerToAdmin = chatSettings[ChatSettingsKey.RANDOM_ANSWER_TO_ADMIN].toBool()
        if (not answerToAdmin) and await self.isAdmin(ensuredMessage.user, ensuredMessage.chat, False):
            # logger.debug(f"answerToAdmin is {answerToAdmin}, skipping")
            return False

        randomFloat = random.random()
        treshold = chatSettings[ChatSettingsKey.RANDOM_ANSWER_PROBABILITY].toFloat()
        # logger.debug(f"Random float: {randomFloat}, need: {treshold}")
        if treshold < randomFloat:
            return False
        logger.debug(f"Random float: {randomFloat} < {treshold}, answering to message")

        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())

        # Handle LLM Action
        parentId = ensuredMessage.replyId
        chat = ensuredMessage.chat

        storedMessages: List[ModelMessage] = []
        _storedMessages: List[ChatMessageDict] = []

        # TODO: Add method for getting whole discussion
        if parentId is not None:
            storedMsg = self.db.getChatMessageByMessageId(
                chatId=chat.id,
                messageId=parentId,
            )
            if storedMsg is None or storedMsg["root_message_id"] is None:
                logger.error(f"Failed to get parent message by id#{parentId}")
                return False

            _storedMessages = self.db.getChatMessagesByRootId(
                chatId=chat.id,
                rootMessageId=storedMsg["root_message_id"],
                threadId=ensuredMessage.threadId,
            )

        else:  # replyId is None, getting last X messages for context
            _storedMessages = list(
                reversed(
                    self.db.getChatMessagesSince(
                        chatId=ensuredMessage.chat.id,
                        threadId=ensuredMessage.threadId if ensuredMessage.threadId is not None else 0,
                        limit=constants.PRIVATE_CHAT_CONTEXT_LENGTH,
                    )
                )
            )

        for storedMsg in _storedMessages:
            eMsg = EnsuredMessage.fromDBChatMessage(storedMsg)
            self._updateEMessageUserData(eMsg)

            storedMessages.append(
                await eMsg.toModelMessage(
                    self.db,
                    format=llmMessageFormat,
                    role="user" if storedMsg["message_category"] == "user" else "assistant",
                )
            )

        if not storedMessages:
            logger.error("Somehow storedMessages are empty, fallback to single message")
            storedMessages.append(await ensuredMessage.toModelMessage(self.db, format=llmMessageFormat, role="user"))

        reqMessages = [
            ModelMessage(
                role="system",
                content=chatSettings[ChatSettingsKey.CHAT_PROMPT].toStr()
                + "\n"
                + chatSettings[ChatSettingsKey.CHAT_PROMPT_SUFFIX].toStr(),
            ),
        ] + storedMessages

        if not await self._sendLLMChatMessage(ensuredMessage, reqMessages, context):
            logger.error("Failed to send LLM reply")
            return False

        return True

    ###
    # COMMANDS Handlers
    ###

    @commandHandler(
        commands=("start",),
        shortDescription="Start bot interaction",
        helpMessage=": Начать работу с ботом.",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.FIRST,
    )
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command."""
        user = update.effective_user
        if not user or not update.message:
            logger.error("User or message undefined")
            return

        welcome_message = (
            f"Привет! {user.first_name}! 👋\n\n"
            "Я Громозека: лучший бот для Телеграма, что когда либо был, есть или будет.\n\n"
            "Что бы узнать, что я умею, можешь отправить команду /help"
        )

        await update.message.reply_text(welcome_message)
        logger.info(f"User {user.id} ({user.username}) started the bot")

    @commandHandler(
        commands=("remind",),
        shortDescription="<delay> [<message>] - Remind me after given delay with message or replied message/quote",
        helpMessage=" `<DDdHHhMMmSSs|HH:MM[:SS]>`: напомнить указанный текст через указанное время "
        "(можно использовать цитирование или ответ на сообщение).",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.NORMAL,
    )
    async def remind_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /remind <time> [<message>] command."""
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

        delaySecs: int = 0
        try:
            if not context.args:
                raise ValueError("No time specified")
            delayStr = context.args[0]
            delaySecs = utils.parseDelay(delayStr)
        except Exception as e:
            await self.sendMessage(
                ensuredMessage,
                messageText=(
                    "Для команды `/remind` нужно указать время, через которое отправить "
                    "напоминание в одном из форматов:\n"
                    "1. `DDdHHhMMmSSs`\n"
                    "2. `HH:MM[:SS]`\n"
                ),
                messageCategory=MessageCategory.BOT_ERROR,
            )
            logger.error(f"Error while handling /remind command: {type(e).__name__}{e}")
            # TODO: comment later after debug
            logger.exception(e)
            return

        reminderText: Optional[str] = None
        if len(context.args) > 1:
            reminderText = " ".join(context.args[1:])

        if reminderText is None and ensuredMessage.quoteText:
            reminderText = ensuredMessage.quoteText

        if reminderText is None and ensuredMessage.replyText:
            reminderText = ensuredMessage.replyText

        if reminderText is None:
            reminderText = "⏰ Напоминание"

        delayedTime = time.time() + delaySecs
        await self._delayedSendMessage(
            ensuredMessage,
            delayedUntil=delayedTime,
            messageText=reminderText,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

        delayedDT = datetime.datetime.fromtimestamp(delayedTime, tz=datetime.timezone.utc)

        await self.sendMessage(
            ensuredMessage,
            messageText=f"Напомню в {delayedDT.strftime('%Y-%m-%d %H:%M:%S%z')}",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandler(
        commands=("list_chats",),
        shortDescription="[all] - List chats, where bot seen you",
        helpMessage=": Вывести список чатов, где бот вас видел.",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.TECHNICAL,
    )
    async def list_chats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /list_chats [all] command."""
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

        listAll = context.args and context.args[0].strip().lower() == "all"

        chatType = ensuredMessage.chat.type
        if chatType != Chat.PRIVATE:
            logger.error(f"Unsupported chat type for /list_chats command: {chatType}")
            return

        if listAll:
            listAll = await self.isAdmin(ensuredMessage.user, None, True)

        knownChats = self.db.getAllGroupChats() if listAll else self.db.getUserChats(ensuredMessage.user.id)

        resp = "Список доступных чатов:\n\n"

        for chat in knownChats:
            chatTitle: str = f"#{chat['chat_id']}"
            if chat["title"]:
                chatTitle = f"{constants.CHAT_ICON} {chat['title']} ({chat["type"]})"
            elif chat["username"]:
                chatTitle = f"{constants.PRIVATE_ICON} {chat['username']} ({chat["type"]})"
            resp += f"* ID: #`{chat['chat_id']}`, Name: `{chatTitle}`\n"

        await self.sendMessage(ensuredMessage, resp, messageCategory=MessageCategory.BOT_COMMAND_REPLY)
