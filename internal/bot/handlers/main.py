"""
Telegram bot command handlers for Gromozeka.
"""

import asyncio
import datetime
import logging
import re

import random
import time
from typing import Any, Dict, List, Optional

import requests
import magic

from telegram import Chat, Update, Message, User
from telegram.constants import MessageEntityType, MessageLimit
from telegram.ext import ContextTypes

from internal.services.llm.service import LLMService

from .base import BaseBotHandler, HandlerResultStatus

from lib.ai.abstract import AbstractModel
from lib.ai.models import (
    LLMFunctionParameter,
    LLMParameterType,
    ModelImageMessage,
    ModelMessage,
    ModelRunResult,
    ModelResultStatus,
)
from lib.ai.manager import LLMManager
import lib.utils as utils

from internal.config.manager import ConfigManager

from internal.database.wrapper import DatabaseWrapper
from internal.database.models import (
    ChatMessageDict,
    MessageCategory,
)

from ..models import (
    ChatSettingsKey,
    ChatSettingsValue,
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
            name="generate_and_send_image",
            description=(
                "Generate and send an image. ALWAYS use it if user ask to " "generate/paint/draw an image/picture/photo"
            ),
            parameters=[
                LLMFunctionParameter(
                    name="image_prompt",
                    description="Detailed prompt to generate the image from",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
                LLMFunctionParameter(
                    name="image_description",
                    description="The description of the image if any",
                    type=LLMParameterType.STRING,
                    required=False,
                ),
            ],
            handler=self._llmToolGenerateAndSendImage,
        )
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

    async def _llmToolGenerateAndSendImage(
        self, extraData: Optional[Dict[str, Any]], image_prompt: str, image_description: Optional[str] = None, **kwargs
    ) -> str:
        if extraData is None:
            raise RuntimeError("extraData should be provided")
        if "ensuredMessage" not in extraData:
            raise RuntimeError("ensuredMessage should be provided")
        ensuredMessage = extraData["ensuredMessage"]
        if not isinstance(ensuredMessage, EnsuredMessage):
            raise RuntimeError("ensuredMessage should be EnsuredMessage")

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        logger.debug(
            f"Generating image: {image_prompt}. Image description: {image_description}, "
            f"mcID: {ensuredMessage.chat.id}:{ensuredMessage.messageId}"
        )
        imageLLM = chatSettings[ChatSettingsKey.IMAGE_GENERATION_MODEL].toModel(self.llmManager)
        fallbackImageLLM = chatSettings[ChatSettingsKey.IMAGE_GENERATION_FALLBACK_MODEL].toModel(self.llmManager)

        mlRet = await imageLLM.generateImageWithFallBack([ModelMessage(content=image_prompt)], fallbackImageLLM)
        logger.debug(f"Generated image Data: {mlRet} for mcID: " f"{ensuredMessage.chat.id}:{ensuredMessage.messageId}")
        if mlRet.status != ModelResultStatus.FINAL:
            ret = await self.sendMessage(
                ensuredMessage,
                messageText=(
                    f"Не удалось сгенерировать изображение.\n```\n{mlRet.status}\n{str(mlRet.resultText)}\n```\n"
                    f"Prompt:\n```\n{image_prompt}\n```"
                ),
            )
            return utils.jsonDumps({"done": False, "errorMessage": mlRet.resultText})

        if mlRet.mediaData is None:
            logger.error(f"No image generated for {image_prompt}")
            return '{"done": false}'

        imgAddPrefix = ""
        if mlRet.isFallback:
            imgAddPrefix = chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr()
        ret = await self.sendMessage(
            ensuredMessage,
            photoData=mlRet.mediaData,
            photoCaption=image_description,
            mediaPrompt=image_prompt,
            addMessagePrefix=imgAddPrefix,
        )

        return utils.jsonDumps({"done": ret is not None})

    async def _llmToolGetUrlContent(self, extraData: Optional[Dict[str, Any]], url: str, **kwargs) -> str:
        # TODO: Check if content is text content
        try:
            return str(requests.get(url).content)
        except Exception as e:
            logger.error(f"Error getting content from {url}: {e}")
            return utils.jsonDumps({"done": False, "errorMessage": str(e)})

    async def _llmToolSetUserData(
        self, extraData: Optional[Dict[str, Any]], key: str, data: str, append: bool = False, **kwargs
    ) -> str:
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

    async def _llmToolGetCurrentDateTime(self, extraData: Optional[Dict[str, Any]], **kwargs) -> str:
        now = datetime.datetime.now(datetime.timezone.utc)
        return utils.jsonDumps({"datetime": now.isoformat(), "timestamp": now.timestamp(), "timezone": "UTC"})

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

    ###
    # Handling messages
    ###

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle regular text messages."""
        # logger.debug(f"Handling SOME message: {update}")

        chat = update.effective_chat
        if not chat:
            logger.error("Chat undefined")
            return
        chatType = chat.type

        match chatType:
            case Chat.PRIVATE:
                chatSettings = self.getChatSettings(chat.id)
                if chatSettings[ChatSettingsKey.ALLOW_PRIVATE].toBool():
                    return await self.handle_chat_message(update, context)
                else:
                    return
            case Chat.GROUP:
                return await self.handle_chat_message(update, context)
            case Chat.SUPERGROUP:
                return await self.handle_chat_message(update, context)
            case Chat.CHANNEL:
                logger.error(f"Unsupported chat type: {chatType}")
            case _:
                logger.error(f"Unsupported chat type: {chatType}")

    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
        await self.handle_message(update, context)
        return HandlerResultStatus.FINAL

    async def handle_chat_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.debug(f"Handling group message #{update.update_id}")

        message = update.message
        if not message:
            # Not new message, ignore
            logger.warning(f"Message undefined in {update}")
            return

        # logger.debug(f"Message: {message}")
        logger.debug(f"Message: {utils.dumpMessage(message)}")

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        self._updateEMessageUserData(ensuredMessage)

        user = ensuredMessage.user

        match ensuredMessage.messageType:
            case MessageType.TEXT:
                # No special handling for text messages needed
                pass
            case MessageType.IMAGE:
                media = await self.processImage(ensuredMessage)
                ensuredMessage.setMediaProcessingInfo(media)
            case MessageType.STICKER:
                media = await self.processSticker(ensuredMessage)
                ensuredMessage.setMediaProcessingInfo(media)

            case _:
                # For unsupported message types, just log a warning and process caption like text message
                logger.warning(f"Unsupported message type: {ensuredMessage.messageType}")
                # return

        if not self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER):
            logger.error("Failed to save chat message")

        if message.is_automatic_forward:
            # Automatic forward from licked Channel
            # TODO: Somehow process automatic forwards
            # TODO: Think about handleRandomMessage here
            return

        # Check if message is a reply to our message
        if await self.handleReply(update, context, ensuredMessage):
            return

        # Check if bot was mentioned
        if await self.handleMention(update, context, ensuredMessage):
            return

        if ensuredMessage.chat.type == Chat.PRIVATE:
            await self.handlePrivateMessage(update, context, ensuredMessage)
        else:
            await self.handleRandomMessage(update, context, ensuredMessage)

        logger.info(f"Handled message from {user.id}: {ensuredMessage.messageText[:50]}...")

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
        customMentions = chatSettings[ChatSettingsKey.BOT_NICKNAMES].toList()
        customMentions = [v.lower() for v in customMentions if v]
        if not customMentions:
            logger.error("No custom mentions found")
            return False

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

        ###
        # what there? Return parsed media content of replied message (if any)
        ###
        whatThereList = ["что там"]

        isWhatThere = False
        for whatThere in whatThereList:
            if messageTextLower.startswith(whatThere):
                tail = messageText[len(whatThere) :].strip()

                # Match only whole message
                if not tail.rstrip("?.").strip():
                    isWhatThere = True
                    break

        if isWhatThere and ensuredMessage.isReply and message.reply_to_message:
            # TODO: Move getting parent message to separate function
            ensuredReply = EnsuredMessage.fromMessage(message.reply_to_message)
            response = constants.DUNNO_EMOJI
            if ensuredReply.messageType != MessageType.TEXT:
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
                    eStoredMsg = EnsuredMessage.fromDBChatMessage(storedReply)
                    await eStoredMsg.updateMediaContent(self.db)
                    response = eStoredMsg.mediaContent
                    if response is None or response == "":
                        response = constants.DUNNO_EMOJI

                return (
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=response,
                    )
                    is not None
                )

        # End of What There

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
        commands=("echo",),
        shortDescription="<Message> - Echo message back",
        helpMessage=" `<message>`: Просто ответить переданным сообщением (для тестирования живости бота).",
        categories={CommandCategory.PRIVATE, CommandCategory.HIDDEN},
        order=CommandHandlerOrder.SECOND,
    )
    async def echo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /echo command."""
        if not update.message:
            logger.error("Message undefined")
            return
        ensuredMessage = EnsuredMessage.fromMessage(update.message)

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        if context.args:
            echo_text = " ".join(context.args)
            await self.sendMessage(
                ensuredMessage,
                messageText=f"🔄 Echo: {echo_text}",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )
        else:
            await self.sendMessage(
                ensuredMessage,
                messageText="Please provide a message to echo!\nUsage: /echo <your message>",
                messageCategory=MessageCategory.BOT_ERROR,
            )

    @commandHandler(
        commands=("models",),
        shortDescription="Get list of known LLM models",
        helpMessage=": Вывести список всех известных моделей и их параметров.",
        categories={CommandCategory.BOT_OWNER},
    )
    async def models_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /models command."""
        modelsPerMessage = 4
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

        if not await self.isAdmin(ensuredMessage.user, allowBotOwners=True):
            logger.warning(f"OWNER ONLY command `/models` by not owner {ensuredMessage.user}")
            await self.handle_message(update=update, context=context)
            return

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        replyText = "**Доступные модели:**\n\n"

        for i, modelName in enumerate(self.llmManager.listModels()):
            modelData = self.llmManager.getModelInfo(modelName)
            if modelData is None:
                modelData = {}
            modelKeyI18n = {
                "model_id": "ID Модели",
                "model_version": "Версия",
                "temperature": "Температура",
                "context_size": "Размер контекста",
                "provider": "Провайдер",
                "support_tools": "Поддерживает вызов инструментов?",
                "support_text": "Поддерживает генерацию текста?",
                "support_images": "Поддерживает генерацию изображений?",
            }
            replyText += f"**Модель: {modelName}**\n```{modelName}\n"
            for k, v in modelData.items():
                replyText += f"{modelKeyI18n.get(k, k)}: {v}\n"

            replyText += "```\n\n"

            if i % modelsPerMessage == (modelsPerMessage - 1):
                await self.sendMessage(
                    ensuredMessage,
                    messageText=replyText,
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )
                replyText = ""
                time.sleep(0.5)

        if replyText:
            await self.sendMessage(
                ensuredMessage,
                messageText=replyText,
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )

    @commandHandler(
        commands=("settings",),
        shortDescription="Dump all settings for this chat",
        helpMessage=": Вывести список настроек для данного чата",
        categories={CommandCategory.BOT_OWNER},
    )
    async def chat_settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /settings command."""
        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        moreDebug = True if context.args and context.args[0].lower() == "debug" else False

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        if not await self.isAdmin(ensuredMessage.user, allowBotOwners=True):
            logger.warning(f"OWNER ONLY command `/settings` by not owner {ensuredMessage.user}")
            await self.handle_message(update=update, context=context)
            return

        self.saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)

        # user = ensuredMessage.user
        chat = ensuredMessage.chat

        resp = f"Настройки чата **#{chat.id}**:\n\n"
        chatSettings = self.getChatSettings(chat.id)
        for k, v in chatSettings.items():
            resp += f"`{k}`:```{k}\n{v}\n```\n"

        if moreDebug:
            logger.debug(resp)
            logger.debug(repr(resp))

        await self.sendMessage(
            ensuredMessage,
            messageText=resp,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandler(
        commands=("set", "unset"),
        shortDescription="<key> <value> - Set/Unset given setting for current chat",
        helpMessage=" `<key>` `<value>`: установить/сбросить настройку чата",
        categories={CommandCategory.BOT_OWNER},
    )
    async def set_or_unset_chat_setting_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /[un]set <key> <value> command."""
        logger.debug(f"Got set or unset command: {update}")

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

        if not await self.isAdmin(ensuredMessage.user, allowBotOwners=True):
            logger.warning(f"OWNER ONLY command `/[un]set` by not owner {ensuredMessage.user}")
            await self.handle_message(update=update, context=context)
            return

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        commandStr = ""
        for entity in message.entities:
            if entity.type == MessageEntityType.BOT_COMMAND:
                commandStr = ensuredMessage.messageText[entity.offset : entity.offset + entity.length]
                break

        logger.debug(f"Command string: {commandStr}")
        isSet = commandStr.lower().startswith("/set")

        chat = ensuredMessage.chat

        # user = ensuredMessage.user
        # chatSettings = self.getChatSettings(chat.id)
        # adminAllowedChangeSettings = chatSettings[ChatSettingsKey.ADMIN_CAN_CHANGE_SETTINGS].toBool()
        # isAdmin = await self._isAdmin(user, chat if adminAllowedChangeSettings else None, True)
        # if not isAdmin:
        #     await self._sendMessage(
        #         ensuredMessage,
        #         messageText="You are not allowed to change chat settings.",
        #         messageCategory=MessageCategory.BOT_ERROR,
        #     )
        #     return

        if isSet and (not context.args or len(context.args) < 2):
            await self.sendMessage(
                ensuredMessage,
                messageText="You need to specify a key and a value to change chat setting.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return
        if not isSet and (not context.args or len(context.args) < 1):
            await self.sendMessage(
                ensuredMessage,
                messageText="You need to specify a key to clear chat setting.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        if not context.args:
            # It is impossible, actually as we have checked it before, but we do it to make linters happy
            raise ValueError("No args provided")

        key = context.args[0]
        _key = ChatSettingsKey.UNKNOWN
        try:
            _key = ChatSettingsKey(key)
        except ValueError:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Неизвестный ключ: `{key}`",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        if isSet:
            value = " ".join(context.args[1:])

            self.setChatSetting(chat.id, _key, ChatSettingsValue(value))
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Готово, теперь `{key}` = `{value}`",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )
        else:
            self.unsetChatSetting(chat.id, _key)
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Готово, теперь `{key}` сброшено в значение по умолчанию",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )

    @commandHandler(
        commands=("test",),
        shortDescription="<Test suite> [<args>] - Run some tests",
        helpMessage=" `<test_name>` `[<test_args>]`: Запустить тест (используется для тестирования).",
        categories={CommandCategory.BOT_OWNER, CommandCategory.HIDDEN},
        order=CommandHandlerOrder.TEST,
    )
    async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /test <suite> [<args>] command."""
        logger.debug(f"Got test command: {update}")

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

        if not await self.isAdmin(ensuredMessage.user, allowBotOwners=True):
            logger.warning(f"OWNER ONLY command `/test` by not owner {ensuredMessage.user}")
            await self.handle_message(update=update, context=context)
            return

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        if not context.args or len(context.args) < 1:
            await self.sendMessage(
                ensuredMessage,
                messageText="You need to specify test suite.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        # user = ensuredMessage.user
        # if not user.username:
        #     await self._sendMessage(
        #         ensuredMessage,
        #         messageText="You need to have a username to run tests.",
        #         messageCategory=MessageCategory.BOT_ERROR,
        #     )
        #     return

        # allowedUsers = self.botOwners[:]

        # if user.username.lower() not in allowedUsers:
        #     await self._sendMessage(
        #         ensuredMessage,
        #         messageText="You are not allowed to run tests.",
        #         messageCategory=MessageCategory.BOT_ERROR,
        #     )
        #     return

        suite = context.args[0]

        match suite:
            case "long":
                iterationsCount = 10
                delay = 10
                if len(context.args) > 1:
                    try:
                        iterationsCount = int(context.args[1])
                    except ValueError as e:
                        await self.sendMessage(
                            ensuredMessage,
                            messageText=f"Invalid iterations count. {e}",
                            messageCategory=MessageCategory.BOT_ERROR,
                        )
                        pass
                if len(context.args) > 2:
                    try:
                        delay = int(context.args[2])
                    except ValueError as e:
                        await self.sendMessage(
                            ensuredMessage,
                            messageText=f"Invalid delay. {e}",
                            messageCategory=MessageCategory.BOT_ERROR,
                        )
                        pass

                for i in range(iterationsCount):
                    logger.debug(f"Iteration {i} of {iterationsCount} (delay is {delay}) {context.args[3:]}")
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=f"Iteration {i}",
                        skipLogs=True,  # Do not spam logs
                        messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    )
                    await asyncio.sleep(delay)

            case "delayedQueue":
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"```\n{self.queueService.delayedActionsQueue}\n\n"
                    f"{self.queueService.delayedActionsQueue.qsize()}\n```",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )

            case "cacheStats":
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"```json\n{utils.jsonDumps(self.cache.getStats(), indent=2)}\n```",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )

            case "dumpEntities":
                if message.reply_to_message is None:
                    await self.sendMessage(
                        ensuredMessage,
                        messageText="`dumpEntities` should be retpy to message with entities",
                        messageCategory=MessageCategory.BOT_ERROR,
                    )
                    return
                repliedMessage = message.reply_to_message
                if not repliedMessage.entities:
                    await self.sendMessage(
                        ensuredMessage,
                        messageText="No entities found",
                        messageCategory=MessageCategory.BOT_ERROR,
                    )
                    return
                entities = repliedMessage.entities
                messageText = repliedMessage.text or ""
                ret = ""
                for entity in entities:
                    ret += (
                        f"{entity.type}: {entity.offset} {entity.length}:\n```\n"
                        f"{messageText[entity.offset:entity.offset + entity.length]}\n```\n"
                        f"```\n{entity}\n```\n"
                    )
                await self.sendMessage(
                    ensuredMessage,
                    messageText=ret,
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )

                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"```\n{repliedMessage.parse_entities()}\n```",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )

            case _:
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"Unknown test suite: {suite}.",
                    messageCategory=MessageCategory.BOT_ERROR,
                )

    @commandHandler(
        commands=("analyze",),
        shortDescription="<prompt> - Analyse answered media with given prompt",
        helpMessage=" `<prompt>`: Проанализировать медиа используя указанный промпт "
        "(на данный момент доступен только анализ картинок и статических стикеров).",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.NORMAL,
    )
    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /analyze <prompt> command."""
        # Analyse media with given prompt. Should be reply to message with media.
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

        chatSettings = self.getChatSettings(chatId=ensuredMessage.chat.id)
        if not chatSettings[ChatSettingsKey.ALLOW_ANALYZE].toBool() and not await self.isAdmin(
            ensuredMessage.user, None, True
        ):
            logger.info(f"Unauthorized /analyze command from {ensuredMessage.user} in chat {ensuredMessage.chat}")
            return

        if not ensuredMessage.isReply or not message.reply_to_message:
            await self.sendMessage(
                ensuredMessage,
                messageText="Команда должна быть ответом на сообщение с медиа.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        parentMessage = message.reply_to_message
        parentEnsuredMessage = ensuredMessage.fromMessage(parentMessage)

        commandStr = ""
        prompt = ensuredMessage.messageText
        for entity in message.entities:
            if entity.type == MessageEntityType.BOT_COMMAND:
                commandStr = ensuredMessage.messageText[entity.offset : entity.offset + entity.length]
                prompt = ensuredMessage.messageText[entity.offset + entity.length :].strip()
                break

        logger.debug(f"Command string: '{commandStr}', prompt: '{prompt}'")

        if not prompt:
            await self.sendMessage(
                ensuredMessage,
                messageText="Необходимо указать запрос для анализа медиа.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        parserLLM = chatSettings[ChatSettingsKey.IMAGE_PARSING_MODEL].toModel(self.llmManager)

        mediaData: Optional[bytearray] = None
        fileId: Optional[str] = None

        match parentEnsuredMessage.messageType:
            case MessageType.IMAGE:
                if parentMessage.photo is None:
                    raise ValueError("Photo is None")
                # TODO: Should I try to get optimal image size like in processImage()?
                fileId = parentMessage.photo[-1].file_id
            case MessageType.STICKER:
                if parentMessage.sticker is None:
                    raise ValueError("Sticker is None")
                fileId = parentMessage.sticker.file_id
                # Removed unused variable fileUniqueId
            case _:
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"Неподдерживаемый тип медиа: {parentEnsuredMessage.messageType}",
                    messageCategory=MessageCategory.BOT_ERROR,
                )
                return

        mediaInfo = await context.bot.get_file(fileId)
        logger.debug(f"Media info: {mediaInfo}")
        mediaData = await mediaInfo.download_as_bytearray()

        if not mediaData:
            await self.sendMessage(
                ensuredMessage,
                messageText="Не удалось получить данные медиа.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        mimeType = magic.from_buffer(bytes(mediaData), mime=True)
        logger.debug(f"Mime type: {mimeType}")
        if not mimeType.startswith("image/"):
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Неподдерживаемый MIME-тип медиа: {mimeType}.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        reqMessages = [
            ModelMessage(
                role="system",
                content=prompt,
            ),
            ModelImageMessage(
                role="user",
                # content="",
                image=mediaData,
            ),
        ]

        llmRet = await parserLLM.generateText(reqMessages)
        logger.debug(f"LLM result: {llmRet}")
        if llmRet.status != ModelResultStatus.FINAL:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Не удалось проанализировать медиа:\n```\n{llmRet.status}\n{llmRet.error}\n```",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        await self.sendMessage(
            ensuredMessage,
            messageText=llmRet.resultText,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandler(
        commands=("draw",),
        shortDescription="[<prompt>] - Draw image with given prompt " "(use qoute or replied message as prompt if any)",
        helpMessage=" `[<prompt>]`: Сгенерировать изображение, используя указанный промпт. "
        "Так же может быть ответом на сообщение или цитированием.",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.NORMAL,
    )
    async def draw_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /draw <prompt> command."""
        # Draw picture with given prompt. If this is reply to message, use quote or full message as prompt
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

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        chatSettings = self.getChatSettings(chatId=ensuredMessage.chat.id)
        if not chatSettings[ChatSettingsKey.ALLOW_DRAW].toBool() and not await self.isAdmin(
            ensuredMessage.user, None, True
        ):
            logger.info(f"Unauthorized /analyze command from {ensuredMessage.user} in chat {ensuredMessage.chat}")
            return

        commandStr = ""
        prompt = ensuredMessage.messageText

        if ensuredMessage.isQuote and ensuredMessage.quoteText:
            prompt = ensuredMessage.quoteText

        elif ensuredMessage.isReply and ensuredMessage.replyText:
            prompt = ensuredMessage.replyText

        else:
            for entity in message.entities:
                if entity.type == MessageEntityType.BOT_COMMAND:
                    commandStr = ensuredMessage.messageText[entity.offset : entity.offset + entity.length]
                    prompt = ensuredMessage.messageText[entity.offset + entity.length :].strip()
                    break

        logger.debug(f"Command string: '{commandStr}', prompt: '{prompt}'")

        if not prompt:
            # Fixed f-string missing placeholders
            await self.sendMessage(
                ensuredMessage,
                messageText=(
                    "Необходимо указать запрос для генерации изображение. "
                    "Или послать команду ответом на сообщение с текстом "
                    "(можно цитировать при необходимости)."
                ),
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        imageLLM = chatSettings[ChatSettingsKey.IMAGE_GENERATION_MODEL].toModel(self.llmManager)
        fallbackImageLLM = chatSettings[ChatSettingsKey.IMAGE_GENERATION_FALLBACK_MODEL].toModel(self.llmManager)

        mlRet = await imageLLM.generateImageWithFallBack([ModelMessage(content=prompt)], fallbackImageLLM)
        logger.debug(f"Generated image Data: {mlRet} for mcID: " f"{ensuredMessage.chat.id}:{ensuredMessage.messageId}")
        if mlRet.status != ModelResultStatus.FINAL:
            await self.sendMessage(
                ensuredMessage,
                messageText=(
                    f"Не удалось сгенерировать изображение.\n```\n{mlRet.status}\n"
                    f"{str(mlRet.resultText)}\n```\nPrompt:\n```\n{prompt}\n```"
                ),
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        if mlRet.mediaData is None:
            logger.error(f"No image generated for {prompt}")
            await self.sendMessage(
                ensuredMessage,
                messageText="Ошибка генерации изображения, попробуйте позже.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        logger.debug(f"Media data len: {len(mlRet.mediaData)}")

        imgAddPrefix = ""
        if mlRet.isFallback:
            imgAddPrefix = chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr()
        await self.sendMessage(
            ensuredMessage,
            photoData=mlRet.mediaData,
            photoCaption=(
                "Сгенерировал изображение по Вашему запросу:\n```\n"
                f"{prompt[:MessageLimit.CAPTION_LENGTH - 60]}"
                "\n```"
            ),
            mediaPrompt=prompt,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            addMessagePrefix=imgAddPrefix,
        )

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
        commands=("get_my_data",),
        shortDescription="Dump data, bot knows about you in this chat",
        helpMessage=": Показать запомненную информацию о Вас в текущем чате.",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.TECHNICAL,
    )
    async def get_my_data_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /get_my_data command."""

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
        """Handle /delete_my_data <key> command."""

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
        """Handle /clear_my_data command."""

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
