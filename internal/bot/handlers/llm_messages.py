"""
LLM message handlers for the Gromozeka Telegram bot, dood!

This module contains handlers for processing messages that interact with Large Language Models (LLMs).
It handles various message types including replies, mentions, private messages, and random responses
in group chats. The handlers manage conversation context, message history, and integrate with
image generation capabilities when needed, dood!

Key Features:
    - Reply handling with conversation thread tracking
    - Bot mention detection and response
    - Private chat message processing with context
    - Random message responses in group chats
    - Image generation from LLM descriptions
    - Tool usage support for LLM interactions
    - Fallback model support for reliability
"""

import datetime
import json
import logging
import random
import re
from typing import Any, Dict, List, Optional

from telegram import Chat, Update
from telegram.ext import ContextTypes

from internal.config.manager import ConfigManager
from internal.database.models import ChatMessageDict, MessageCategory
from internal.database.wrapper import DatabaseWrapper
from internal.services.llm import LLMService
from lib.ai import (
    AbstractModel,
    LLMManager,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
)

from .. import constants
from ..models import (
    ChatSettingsKey,
    EnsuredMessage,
    LLMMessageFormat,
    MessageType,
)
from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class LLMMessageHandler(BaseBotHandler):
    """
    Handler for LLM-based message processing in Telegram bot, dood!

    This class manages all interactions between user messages and Large Language Models,
    including conversation threading, context management, and response generation.
    It supports multiple chat types (private, group, supergroup) and various response
    triggers (replies, mentions, random responses), dood!

    Attributes:
        llmService (LLMService): Singleton service for LLM operations
    """

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        """
        Initialize the LLM message handler, dood!

        Args:
            configManager (ConfigManager): Configuration manager for bot settings
            database (DatabaseWrapper): Database wrapper for message storage and retrieval
            llmManager (LLMManager): Manager for LLM model instances and operations
        """
        super().__init__(configManager=configManager, database=database, llmManager=llmManager)

        self.llmService = LLMService.getInstance()

    ###
    # Some LLM helpers
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
        """
        Generate text response using LLM with fallback support, dood!

        This method calls the LLM service to generate a text response based on the provided
        messages. It supports tool usage, fallback models, and can send intermediate messages
        during generation. The method handles streaming responses and error recovery, dood!

        Args:
            model (AbstractModel): Primary LLM model to use for generation
            messages (List[ModelMessage]): List of messages forming the conversation context
            fallbackModel (AbstractModel): Fallback model to use if primary fails
            ensuredMessage (EnsuredMessage): The message being responded to
            context (ContextTypes.DEFAULT_TYPE): Telegram bot context
            useTools (bool, optional): Whether to enable tool usage for the LLM. Defaults to False.
            sendIntermediateMessages (bool, optional): Whether to send streaming intermediate
                responses. Defaults to True.

        Returns:
            ModelRunResult: Result containing generated text, status, and metadata
        """

        async def processIntermediateMessages(mRet: ModelRunResult, extraData: Optional[Dict[str, Any]]) -> None:
            if mRet.resultText.strip() and sendIntermediateMessages:
                try:
                    logger.debug(f"Sending intermediate message. LLM Result status is: {mRet.status}")
                    await self.sendMessage(ensuredMessage, mRet.resultText, messageCategory=MessageCategory.BOT)
                    await self.startTyping(ensuredMessage)
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
        """
        Send a chat message to the LLM and handle the response, dood!

        This method orchestrates the complete flow of sending a message to the LLM,
        processing the response, handling image generation if requested, and sending
        the final response to the user. It manages chat settings, message formatting,
        and error handling, dood!

        The method supports:
        - Multiple message formats (text, JSON)
        - Image generation from <media-description> tags
        - Tool usage indicators
        - Fallback model indicators
        - Error recovery and user notification

        Args:
            ensuredMessage (EnsuredMessage): The message to respond to
            messagesHistory (List[ModelMessage]): Complete conversation history including
                system prompt and user messages
            context (ContextTypes.DEFAULT_TYPE): Telegram bot context

        Returns:
            bool: True if message was sent successfully, False otherwise
        """
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
            # first - check if it JSON'ed reply and deJson it
            looksLikeJSON = re.match(r"^\s*`*\s*{", lmRetText) is not None
            if looksLikeJSON:
                logger.debug(
                    f"_sendLLMChatMessage: Looks like LLM answered with JSON: '{lmRetText}' trying to parse it..."
                )
                try:
                    jsonReply = json.loads(lmRetText.strip().strip("`").strip())
                    if "text" in jsonReply:
                        lmRetText = str(jsonReply["text"]).strip()
                    elif "message" in jsonReply:
                        lmRetText = str(jsonReply["message"]).strip()
                    elif "media_description" in jsonReply:
                        lmRetText = str(jsonReply["media_description"]).strip()
                    else:
                        logger.warning(
                            f"No text field found in json reply, fallback to text. Json Reply is: {jsonReply}"
                        )
                    logger.debug(f"Extracted text is: {lmRetText}")
                except ValueError as e:
                    logger.debug("It wasn't JSON...")
                    logger.exception(e)

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

    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
        """
        Main entry point for processing incoming messages, dood!

        This handler routes messages to appropriate sub-handlers based on message type
        and chat context. It handles different chat types (private, group, supergroup)
        and delegates to specific handlers for replies, mentions, private messages,
        and random responses, dood!

        Processing order:
        1. Validate message and chat type
        2. Check for automatic forwards (skip)
        3. Handle replies to bot messages
        4. Handle bot mentions
        5. Handle private chat messages
        6. Handle random responses in groups

        Args:
            update (Update): Telegram update object containing the message
            context (ContextTypes.DEFAULT_TYPE): Telegram bot context
            ensuredMessage (Optional[EnsuredMessage]): Validated and enriched message object,
                None if message should be skipped

        Returns:
            HandlerResultStatus: Status indicating how the message was processed:
                - SKIPPED: Message was not processed
                - FINAL: Message was successfully processed
                - ERROR: An error occurred during processing
        """
        if ensuredMessage is None:
            # Not new message, Skip
            return HandlerResultStatus.SKIPPED

        chat = ensuredMessage.chat
        if chat.type not in [Chat.PRIVATE, Chat.GROUP, Chat.SUPERGROUP]:
            logger.error(f"Unsupported chat type: {chat.type}")
            return HandlerResultStatus.SKIPPED

        message = ensuredMessage.getBaseMessage()

        if message.is_automatic_forward:
            # Automatic forward from licked Channel
            # TODO: Somehow process automatic forwards
            # TODO: Think about handleRandomMessage here
            # return HandlerResultStatus.FINAL
            return HandlerResultStatus.NEXT

        # Check if message is a reply to our message
        # TODO: Move to separate handler?
        if await self.handleReply(update, context, ensuredMessage):
            return HandlerResultStatus.FINAL

        # Check if bot was mentioned
        # TODO: Move to separate handler?
        if await self.handleMention(update, context, ensuredMessage):
            return HandlerResultStatus.FINAL

        # Randomly answer message
        # TODO: Move to separate handler?
        if await self.handleRandomMessage(update, context, ensuredMessage):
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.NEXT

    async def handleReply(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        ensuredMessage: EnsuredMessage,
    ) -> bool:
        """
        Handle messages that are replies to bot's previous messages, dood!

        This method processes replies to the bot's messages by reconstructing the
        conversation thread from the database. It retrieves all messages in the thread
        (using root_message_id) and sends them to the LLM to generate a contextually
        appropriate response, dood!

        The method:
        1. Verifies the reply is to a bot message
        2. Retrieves the complete conversation thread from database
        3. Reconstructs message history with proper roles (user/assistant)
        4. Generates LLM response with full context
        5. Waits for media processing if needed

        Args:
            update (Update): Telegram update object
            context (ContextTypes.DEFAULT_TYPE): Telegram bot context
            ensuredMessage (EnsuredMessage): The reply message to process

        Returns:
            bool: True if reply was handled successfully, False if not a reply to bot
                or if reply handling is disabled in chat settings
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
        await self.startTyping(ensuredMessage)

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
                logger.error(f"No root_message_id in {storedMsg}")
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
        Handle messages where the bot is mentioned by name or username, dood!

        This method processes messages that mention the bot, either by display name
        or username. It includes special handling for "кто сегодня" (who today)
        queries that randomly select an active user, and general LLM responses
        for other mentions, dood!

        Special features:
        - "кто сегодня [role]" - Randomly selects an active user for a role
        - Includes parent message context if replying to another message
        - Handles both text and media messages in context
        - Generates LLM response with appropriate context

        Args:
            update (Update): Telegram update object
            context (ContextTypes.DEFAULT_TYPE): Telegram bot context
            ensuredMessage (EnsuredMessage): The message containing the mention

        Returns:
            bool: True if mention was handled successfully, False if bot was not mentioned
                or if mention handling is disabled in chat settings
        """

        message = ensuredMessage.getBaseMessage()
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        if not chatSettings[ChatSettingsKey.ALLOW_MENTION].toBool():
            return False

        mentionedMe = self.checkEMMentionsMe(ensuredMessage)
        if mentionedMe.byName is None and mentionedMe.byNick is None:
            return False

        messageText = mentionedMe.restText or ""
        messageTextLower = messageText.lower()
        await self.startTyping(ensuredMessage)

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
        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())

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

    async def handleRandomMessage(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        ensuredMessage: EnsuredMessage,
    ) -> bool:
        """
        Randomly respond to messages in group chats based on probability, dood!

        This method implements probabilistic responses in group chats, allowing the bot
        to occasionally participate in conversations without being explicitly mentioned.
        The probability is configurable per chat, and admin messages can be excluded, dood!

        The method:
        1. Checks if random responses are enabled (probability > 0)
        2. Optionally skips admin messages based on settings
        3. Rolls random number against configured probability
        4. Retrieves conversation context (thread or recent messages)
        5. Generates LLM response with full context

        Context retrieval:
        - If message is a reply: Gets entire thread from root message
        - If not a reply: Gets last N messages for context

        Args:
            update (Update): Telegram update object
            context (ContextTypes.DEFAULT_TYPE): Telegram bot context
            ensuredMessage (EnsuredMessage): The message that might trigger a response

        Returns:
            bool: True if bot responded to the message, False if probability check failed,
                random responses are disabled, or message is from admin (when configured
                to skip admins)
        """

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
        await self.startTyping(ensuredMessage)

        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())

        # Handle LLM Action
        parentId = ensuredMessage.replyId
        chat = ensuredMessage.chat

        storedMessages: List[ModelMessage] = []
        _storedMessages: List[ChatMessageDict] = []

        # TODO: Add method for getting whole discussion
        if parentId is not None:
            # It's some thread, get whole thread into context
            # TODO: If thread is too long, compress it somehow
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
                        limit=constants.RANDOM_ANSWER_CONTEXT_LENGTH,
                        # messageCategory=[MessageCategory.USER, MessageCategory.BOT],
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
