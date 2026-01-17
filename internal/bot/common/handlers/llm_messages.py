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
from collections.abc import Sequence
from typing import Any, Dict, Optional

import telegram

import lib.max_bot.models as maxModels
from internal.bot import constants
from internal.bot.common.models import TypingAction, UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatType,
    EnsuredMessage,
    LLMMessageFormat,
    MessageType,
)
from internal.config.manager import ConfigManager
from internal.database.models import MessageCategory
from internal.database.wrapper import DatabaseWrapper
from internal.services.llm import LLMService
from lib.ai import (
    LLMManager,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
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

    def __init__(
        self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager, botProvider: BotProvider
    ):
        """
        Initialize the LLM message handler, dood!

        Args:
            configManager (ConfigManager): Configuration manager for bot settings
            database (DatabaseWrapper): Database wrapper for message storage and retrieval
            llmManager (LLMManager): Manager for LLM model instances and operations
        """
        super().__init__(configManager=configManager, database=database, llmManager=llmManager, botProvider=botProvider)

        self.llmService = LLMService.getInstance()

    ###
    # Some LLM helpers
    ###

    async def _generateTextViaLLM(
        self,
        messages: Sequence[ModelMessage],
        ensuredMessage: EnsuredMessage,
        *,
        chatSettings: ChatSettingsDict,
        typingManager: TypingManager,
        useTools: bool = False,
        sendIntermediateMessages: bool = True,
        keepFirstN: int = 0,
        keepLastN: int = 1,
        maxTokensCoeff: float = 0.8,
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
                    # Add more timeout + pint typing manager
                    typingManager.maxTimeout = typingManager.maxTimeout + 120
                    await typingManager.sendTypingAction()
                except Exception as e:
                    logger.error(f"Failed to send intermediate message: {e}")

        # TODO: Make extraData typedDict (or dataclass?)
        ret = await self.llmService.generateTextViaLLM(
            messages,
            chatId=ensuredMessage.recipient.id,
            chatSettings=chatSettings,
            llmManager=self.llmManager,
            modelKey=ChatSettingsKey.CHAT_MODEL,
            fallbackModelKey=ChatSettingsKey.FALLBACK_MODEL,
            useTools=useTools,
            callId=f"{ensuredMessage.recipient.id}:{ensuredMessage.messageId}",
            callback=processIntermediateMessages,
            extraData={
                "ensuredMessage": ensuredMessage,
                "typingManager": typingManager,
            },
            keepFirstN=keepFirstN,
            keepLastN=keepLastN,
            maxTokensCoeff=maxTokensCoeff,
        )
        return ret

    async def _sendLLMChatMessage(
        self,
        ensuredMessage: EnsuredMessage,
        messagesHistory: Sequence[ModelMessage],
        *,
        typingManager: TypingManager,
        stopTypingOnSend: bool = True,
        keepFirstN: int = 0,
        keepLastN: int = 1,
        maxTokensCoeff: float = 0.8,
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

        chatSettings = self.getChatSettings(ensuredMessage.recipient.id)
        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())
        mlRet: Optional[ModelRunResult] = None

        try:
            mlRet = await self._generateTextViaLLM(
                messages=messagesHistory,
                ensuredMessage=ensuredMessage,
                chatSettings=chatSettings,
                useTools=chatSettings[ChatSettingsKey.USE_TOOLS].toBool(),
                typingManager=typingManager,
                keepFirstN=keepFirstN,
                keepLastN=keepLastN,
                maxTokensCoeff=maxTokensCoeff,
            )
            # logger.debug(f"LLM Response: {mlRet}")
        except Exception as e:
            logger.error(f"Error while sending LLM request: {type(e).__name__}#{e}")
            logger.exception(e)
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Error while sending LLM request: {type(e).__name__}",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager if stopTypingOnSend else None,
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
                        # TODO: Add logging of this thing Also process tool_calls here
                    logger.debug(f"Extracted text is: {lmRetText}")
                except ValueError as e:
                    logger.debug("It wasn't JSON...")
                    logger.exception(e)

            if lmRetText.strip().strip("`").strip().startswith("<media-description>"):
                # Extract content in <media-description> tag to imagePrompt variable and strip from lmRetText
                lmRetText = lmRetText.strip().strip("`").strip()
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
            typingManager.action = TypingAction.UPLOAD_PHOTO
            await typingManager.sendTypingAction()
            imgMLRet = await self.llmService.generateImage(
                imagePrompt,
                chatId=ensuredMessage.recipient.id,
                chatSettings=chatSettings,
                llmManager=self.llmManager,
            )
            logger.debug(
                f"Generated image Data: {imgMLRet} for mcID: "
                f"{ensuredMessage.recipient.id}:{ensuredMessage.messageId}"
            )

            if imgMLRet.status == ModelResultStatus.FINAL and imgMLRet.mediaData is not None:
                imgAddPrefix = ""
                if imgMLRet.isFallback:
                    imgAddPrefix = chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr()
                return (
                    await self.sendMessage(
                        ensuredMessage,
                        photoData=imgMLRet.mediaData,
                        messageText=lmRetText,
                        mediaPrompt=imagePrompt,
                        addMessagePrefix=imgAddPrefix,
                        typingManager=typingManager if stopTypingOnSend else None,
                        toolsHistory=mlRet.toolUsageHistory,
                    )
                    is not None
                )

            # Something went wrong, log and fallback to ordinary message
            logger.error(f"Failed to generate Image by prompt '{imagePrompt}': {imgMLRet}")

        return (
            await self.sendMessage(
                ensuredMessage,
                messageText=lmRetText,
                addMessagePrefix=addPrefix,
                tryParseInputJSON=llmMessageFormat == LLMMessageFormat.JSON,
                typingManager=typingManager if stopTypingOnSend else None,
                toolsHistory=mlRet.toolUsageHistory,
            )
            is not None
        )

    ###
    # Handling messages
    ###

    async def newMessageHandler(
        self,
        ensuredMessage: EnsuredMessage,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        """
        Handle new messages and route them to appropriate handlers, dood!

        This method processes incoming messages from private chats and groups,
        checking for replies, mentions, and randomly responding to messages.
        For Telegram, it also handles automatic forwards from linked channels.

        Args:
            ensuredMessage: The validated message object containing all message data
            updateObj: The raw update object from the bot platform

        Returns:
            HandlerResultStatus: FINAL if message was handled, SKIPPED for unsupported
                                chat types, NEXT to continue processing chain
        """

        chat = ensuredMessage.recipient
        if chat.chatType not in [ChatType.PRIVATE, ChatType.GROUP]:
            logger.error(f"Unsupported chat type: {chat.chatType}")
            return HandlerResultStatus.SKIPPED

        if self.botProvider == BotProvider.TELEGRAM:
            message = ensuredMessage.getBaseMessage()
            if not isinstance(message, telegram.Message):
                raise ValueError("Message is not a Telegram message")

            if message.is_automatic_forward:
                # Automatic forward from linked Channel
                # TODO: Somehow process automatic forwards
                # TODO: Think about handleRandomMessage here
                # return HandlerResultStatus.FINAL
                return HandlerResultStatus.NEXT

        # Check if message is a reply to our message
        # TODO: Move to separate handler?
        if await self.handleReply(ensuredMessage, updateObj):
            return HandlerResultStatus.FINAL

        # Check if bot was mentioned
        # TODO: Move to separate handler?
        if await self.handleMention(ensuredMessage, updateObj):
            return HandlerResultStatus.FINAL

        # Randomly answer message
        # TODO: Move to separate handler?
        if await self.handleRandomMessage(ensuredMessage, updateObj):
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.NEXT

    async def handleReply(
        self,
        ensuredMessage: EnsuredMessage,
        updateObj: UpdateObjectType,
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

        chatSettings = self.getChatSettings(chatId=ensuredMessage.recipient.id)
        if not chatSettings[ChatSettingsKey.ALLOW_REPLY].toBool():
            return False

        message = ensuredMessage.getBaseMessage()
        isReplyToMyMessage = False
        if (
            self.botProvider == BotProvider.TELEGRAM
            and isinstance(message, telegram.Message)
            and message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.id == await self.getBotId()
        ):
            isReplyToMyMessage = True

        elif (
            self.botProvider == BotProvider.MAX
            and isinstance(message, maxModels.Message)
            and message.link
            and message.link.type == maxModels.MessageLinkType.REPLY
            and message.link.sender
            and message.link.sender.user_id == await self.getBotId()
        ):
            isReplyToMyMessage = True

        if not isReplyToMyMessage:
            return False

        logger.debug("It is reply to our message, processing reply...")
        async with await self.startTyping(ensuredMessage) as typingManager:
            # As it's resporse to our message, we need to wait for media to be processed if any
            await ensuredMessage.updateMediaContent(self.db)

            llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())

            reqMessages = await self.getThreadByMessageForLLM(ensuredMessage=ensuredMessage)

            if not reqMessages:
                logger.error("Failed to get parent message")
                ensuredReply: Optional[EnsuredMessage] = ensuredMessage.getEnsuredRepliedToMessage()

                if ensuredReply is None:
                    logger.error("ensuredReply is None, but should be EnsuredMessage()")
                    return False

                reqMessages = [
                    ModelMessage(
                        role="system",
                        content=chatSettings[ChatSettingsKey.CHAT_PROMPT].toStr()
                        + "\n"
                        + chatSettings[ChatSettingsKey.CHAT_PROMPT_SUFFIX].toStr(),
                    ),
                    await ensuredReply.toModelMessage(self.db, format=llmMessageFormat, role="assistant"),
                    await ensuredMessage.toModelMessage(self.db, format=llmMessageFormat, role="user"),
                ]

            if not await self._sendLLMChatMessage(
                ensuredMessage,
                reqMessages,
                typingManager=typingManager,
                keepFirstN=1,
                keepLastN=1,
                maxTokensCoeff=0.8,
            ):
                logger.error("Failed to send LLM reply")

        return True

    async def handleMention(
        self,
        ensuredMessage: EnsuredMessage,
        updateObj: UpdateObjectType,
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

        chatSettings = self.getChatSettings(ensuredMessage.recipient.id)
        if not chatSettings[ChatSettingsKey.ALLOW_MENTION].toBool():
            return False

        mentionedMe = await self.checkEMMentionsMe(ensuredMessage)
        if mentionedMe.byName is None and mentionedMe.byNick is None:
            return False

        messageText = mentionedMe.restText or ""
        messageTextLower = messageText.lower()
        async with await self.startTyping(ensuredMessage) as typingManager:

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
                    chatId=ensuredMessage.recipient.id,
                    limit=100,
                    seenSince=today,
                )

                user = users[random.randint(0, len(users) - 1)]
                while user["user_id"] == await self.getBotId():
                    # Do not allow bot to choose itself
                    user = users[random.randint(0, len(users) - 1)]

                logger.debug(f"Found user for candidate of being '{userTitle}': {user}")
                return (
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=f"{user['username']} сегодня {userTitle}",
                        typingManager=typingManager,
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
            if ensuredMessage.isReply:
                # TODO: Shoiuld we add whole discussion?
                ensuredReply: Optional[EnsuredMessage] = ensuredMessage.getEnsuredRepliedToMessage()
                if ensuredReply is not None:
                    self._updateEMessageUserData(ensuredReply)
                    if ensuredReply.messageType == MessageType.TEXT:
                        reqMessages.append(
                            await ensuredReply.toModelMessage(
                                self.db,
                                format=llmMessageFormat,
                                role=("assistant" if ensuredReply.sender.id == await self.getBotId() else "user"),
                            ),
                        )
                    else:
                        # Not text message, try to get it's content from DB
                        storedReply = self.db.getChatMessageByMessageId(
                            chatId=ensuredReply.recipient.id,
                            messageId=ensuredReply.messageId,
                        )
                        if storedReply is None:
                            logger.error(
                                f"Failed to get parent message (ChatId: {ensuredReply.recipient.id}, "
                                f"MessageId: {ensuredReply.messageId})"
                            )
                        else:
                            eStoredReply = EnsuredMessage.fromDBChatMessage(storedReply, self.db)
                            self._updateEMessageUserData(eStoredReply)
                            reqMessages.append(
                                await eStoredReply.toModelMessage(
                                    self.db,
                                    format=llmMessageFormat,
                                    role=("assistant" if ensuredReply.sender.id == await self.getBotId() else "user"),
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

            if not await self._sendLLMChatMessage(ensuredMessage, reqMessages, typingManager=typingManager):
                logger.error("Failed to send LLM reply")
                return False

            return True

    async def handleRandomMessage(
        self,
        ensuredMessage: EnsuredMessage,
        updateObj: UpdateObjectType,
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

        chatSettings = self.getChatSettings(ensuredMessage.recipient.id)
        answerProbability = chatSettings[ChatSettingsKey.RANDOM_ANSWER_PROBABILITY].toFloat()
        if answerProbability <= 0.0:
            # logger.debug(
            #    f"answerProbability is {answerProbability} "
            #    f"({chatSettings[ChatSettingsKey.RANDOM_ANSWER_PROBABILITY].toStr()})"
            # )
            return False

        answerToAdmin = chatSettings[ChatSettingsKey.RANDOM_ANSWER_TO_ADMIN].toBool()
        if (not answerToAdmin) and await self.isAdmin(ensuredMessage.sender, ensuredMessage.recipient, False):
            # logger.debug(f"answerToAdmin is {answerToAdmin}, skipping")
            return False

        randomFloat = random.random()
        treshold = chatSettings[ChatSettingsKey.RANDOM_ANSWER_PROBABILITY].toFloat()
        if treshold < randomFloat:
            # logger.debug(f"Random float: {randomFloat}, need: {treshold}")
            return False

        logger.debug(f"Random float: {randomFloat} < {treshold}, answering to message")
        async with await self.startTyping(ensuredMessage) as typingManager:
            llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())

            # Handle LLM Action
            parentId = ensuredMessage.replyId
            chatId = ensuredMessage.recipient.id

            storedMessages: Sequence[ModelMessage] = []

            keepFirstMessagesN: int = 0
            keepLastMessagesN: int = 1
            maxTokensCoeff: float = 0.8

            # TODO: Add method for getting whole discussion
            if parentId is not None:
                storedMessages = await self.getThreadByMessageForLLM(ensuredMessage=ensuredMessage)
                # In case of condensing, keep thread-start message
                keepFirstMessagesN = 1

            if not storedMessages:
                storedMessages = [
                    ModelMessage(
                        role="system",
                        content=chatSettings[ChatSettingsKey.CHAT_PROMPT].toStr()
                        + "\n"
                        + chatSettings[ChatSettingsKey.CHAT_PROMPT_SUFFIX].toStr(),
                    ),
                ]
                for storedMsg in reversed(
                    self.db.getChatMessagesSince(
                        chatId=chatId,
                        threadId=ensuredMessage.threadId if ensuredMessage.threadId is not None else 0,
                        limit=constants.RANDOM_ANSWER_CONTEXT_LENGTH,
                        # messageCategory=[MessageCategory.USER, MessageCategory.BOT, MessageCategory.CHANNEL],
                    )
                ):
                    eMsg = EnsuredMessage.fromDBChatMessage(storedMsg, self.db)
                    self._updateEMessageUserData(eMsg)

                    storedMessages.extend(
                        await eMsg.toModelMessageList(
                            self.db,
                            format=llmMessageFormat,
                            role="user" if storedMsg["message_category"] == "user" else "assistant",
                        )
                    )
                # In case of getting last allow less context
                maxTokensCoeff = 0.4

            if not await self._sendLLMChatMessage(
                ensuredMessage,
                storedMessages,
                typingManager=typingManager,
                keepFirstN=keepFirstMessagesN,
                keepLastN=keepLastMessagesN,
                maxTokensCoeff=maxTokensCoeff,
            ):
                logger.error("Failed to send LLM reply")
                return False

            return True
