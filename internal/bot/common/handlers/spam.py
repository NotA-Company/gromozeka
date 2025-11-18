"""
Gromozeka SPAM Handlers Module, dood!

This module provides comprehensive spam detection and management functionality for the Gromozeka bot.
It implements multiple spam detection strategies including:
- Rule-based detection (URLs, mentions, duplicate messages)
- Naive Bayes machine learning classification
- User behavior analysis
- Manual spam reporting by admins and users

The module integrates with the bot's database for persistent storage and learning,
and provides commands for training, testing, and managing the spam filter, dood!
"""

import asyncio
import datetime
import logging
import time
import zlib
from typing import Any, Dict, List, Optional, Set

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram._utils.entities import parse_message_entity
from telegram.constants import MessageEntityType
from telegram.ext import ContextTypes

import lib.utils as utils
from internal.bot.models import (
    BotProvider,
    ButtonDataKey,
    CallbackDataDict,
    ChatSettingsKey,
    ChatType,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    DelayedTaskFunction,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
)
from internal.config.manager import ConfigManager
from internal.database.bayes_storage import DatabaseBayesStorage
from internal.database.models import (
    ChatUserDict,
    MessageCategory,
    SpamReason,
)
from internal.database.wrapper import DatabaseWrapper
from internal.models import MessageIdType
from internal.services.cache import HCSpamWarningMessageInfo
from lib.ai import LLMManager
from lib.bayes_filter import BayesConfig, NaiveBayesFilter, TokenizerConfig

from .base import BaseBotHandler, HandlerResultStatus, TypingManager, commandHandlerExtended

logger = logging.getLogger(__name__)


class SpamHandler(BaseBotHandler):
    """
    Comprehensive spam detection and management handler, dood!

    This class provides multi-layered spam protection combining rule-based detection
    with machine learning (Naive Bayes) classification. It handles automatic spam
    detection, user banning, message deletion, and provides administrative commands
    for spam management and filter training.

    Attributes:
        bayesFilter (NaiveBayesFilter): Machine learning spam classifier using Naive Bayes algorithm.

    Features:
        - Automatic spam detection with configurable thresholds
        - Rule-based detection (URLs, mentions, duplicate messages)
        - Naive Bayes machine learning classification
        - Per-chat learning and statistics
        - Manual spam reporting by admins and users
        - Spam filter training from message history
        - User unbanning with automatic ham learning
    """

    def __init__(
        self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager, botProvider: BotProvider
    ):
        """
        Initialize spam handlers with database and LLM model, dood!

        Sets up the Naive Bayes spam filter with per-chat statistics and configurable
        parameters for spam detection and learning.

        Args:
            configManager (ConfigManager): Configuration manager for bot settings.
            database (DatabaseWrapper): Database wrapper for persistent storage.
            llmManager (LLMManager): LLM manager for AI-powered features.

        Note:
            The Bayes filter is initialized with:
            - Per-chat statistics enabled
            - Laplace smoothing (alpha=1.0)
            - Minimum token count of 2
            - Default spam threshold of 50.0
            - Trigram tokenization enabled
        """
        # Initialize the mixin (discovers handlers)
        super().__init__(configManager=configManager, database=database, llmManager=llmManager, botProvider=botProvider)

        self.spamButtonSalt = self.config.get("spam-button-salt", str(self.botOwners))
        # self.config = configManager.getBotConfig()

        # Initialize Bayes spam filter
        bayesStorage = DatabaseBayesStorage(database)
        bayesConfig = BayesConfig(
            perChatStats=True,  # Use per-chat learning
            alpha=1.0,  # Laplace smoothing
            minTokenCount=2,  # Minimum token occurrences
            defaultThreshold=50.0,  # Default spam threshold
            debugLogging=True,  # Set to True for debugging
            defaultSpamProbability=0.5,
            tokenizerConfig=TokenizerConfig(
                use_trigrams=True,
            ),
        )
        self.bayesFilter = NaiveBayesFilter(bayesStorage, bayesConfig)

        logger.info("Initialized Bayes spam filter, dood!")

    def _makeSpamButtonSignature(self, message: EnsuredMessage, extra: Any = None) -> str:
        signatureStr = ":".join(
            [
                str(v)
                for v in [
                    message.messageId,
                    message.recipient.id,
                    message.sender.id,
                    message.messageText,
                    self.spamButtonSalt,
                    extra,
                ]
            ]
        )
        # Adler32 isn't proper function to make hashes, but who cares?
        # We just need some easy protection against users who tried to mark as spam some definetly-not-a-spam messages
        hashed = zlib.adler32(signatureStr.encode("utf-8", "ignore"))
        return hex(hashed)[2:]

    def _rememberSpamWarningMessage(self, message: Message) -> None:
        """
        Remember SpamWarning Message for future manipulations
        """
        userId = 0
        username = ""
        if message.sender_chat:
            userId = message.sender_chat.id
            if message.sender_chat.username is not None:
                username = message.sender_chat.username
        elif message.from_user:
            userId = message.from_user.id
            if message.from_user.username is not None:
                username = message.from_user.username
        else:
            logger.error(f"No sender found in {message.reply_to_message}")

        self.cache.addSpamWarningMessage(
            chatId=message.chat.id,
            messageId=message.message_id,
            data={
                "parentMessageId": message.reply_to_message.message_id if message.reply_to_message else None,
                "userId": userId,
                "username": username,
                "ts": message.date.timestamp(),
            },
        )

    def _getSpamWarningMessageInfo(self, chatId: int, messageId: int) -> Optional[HCSpamWarningMessageInfo]:
        """
        Get SpamWarning Message Info from cache
        """
        return self.cache.getSpamWarningMessageInfo(chatId=chatId, messageId=messageId)

    def _deleteSpamWarningMessageInfo(self, chatId: int, messageId: int) -> None:
        """
        Delete SpamWarning Message Info from cache
        """
        self.cache.removeSpamWarningMessageInfo(chatId=chatId, messageId=messageId)

    async def checkSpam(self, ensuredMessage: EnsuredMessage) -> bool:
        """
        Perform comprehensive spam check on a message, dood!

        This method implements multi-layered spam detection combining:
        1. Automatic forward detection (not spam)
        2. Anonymous admin detection (not spam)
        3. User message count threshold check
        4. Explicit non-spammer marking check
        5. Previous spammer status check
        6. Duplicate message detection
        7. Known spam message matching
        8. URL and mention analysis
        9. Naive Bayes classification (if enabled)

        Args:
            ensuredMessage (EnsuredMessage): The message to check for spam.

        Returns:
            bool: True if message is spam and was handled (banned/deleted), False otherwise.

        Note:
            - Messages without text are currently not checked (TODO)
            - Users with message count >= maxCheckMessages are trusted
            - Spam score is accumulated from multiple detection methods
            - Bayes filter is only used if score is below ban threshold (for performance)
        """

        message = ensuredMessage.getBaseMessage()
        if isinstance(message, telegram.Message) and message.is_automatic_forward:
            # https://docs.python-telegram-bot.org/en/stable/telegram.message.html#telegram.Message.is_automatic_forward
            # It's a automatic forward from linked Channel. Its not spam.
            return False

        sender = ensuredMessage.sender
        chatId = ensuredMessage.recipient.id

        if sender.id == chatId:
            # If sender ID == chat ID, then it is anonymous admin, so it isn't spam
            return False

        if ensuredMessage.recipient.chatType != ChatType.GROUP:
            # There can't be spam in non-Group chat
            return False

        if not ensuredMessage.messageText:
            # TODO: Message without text, think about checking for spam
            return False

        chatSettings = self.getChatSettings(chatId)

        userInfo: Optional[ChatUserDict] = self.db.getChatUser(chatId=chatId, userId=sender.id)
        if not userInfo:
            logger.debug(f"userInfo for {ensuredMessage} is null, assume it's first user message")
            userInfo = {
                "chat_id": chatId,
                "user_id": sender.id,
                "username": sender.username,
                "full_name": sender.name,
                "messages_count": 1,
                "is_spammer": False,
                "created_at": datetime.datetime.now(),
                "updated_at": datetime.datetime.now(),
                "timezone": "",
                "metadata": "",
            }

        userMessages = userInfo["messages_count"]
        maxCheckMessages = chatSettings[ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES].toInt()
        if maxCheckMessages != 0 and userMessages >= maxCheckMessages:
            # User has more message than limit, assume it isn't spammer
            if not userInfo["is_spammer"]:
                await self.markAsHam(message=ensuredMessage)
            return False

        userMetadata = self.parseUserMetadata(userInfo=userInfo)

        if userMetadata.get("notSpammer", False):
            logger.info(f"SPAM: User {sender} explicitely marked as not spammer, skipping spam check")
            return False

        # TODO: Check for admins?

        logger.debug(f"SPAM CHECK: {userMessages} < {maxCheckMessages}, checking message for spam ({ensuredMessage})")

        spamScore = 0.0

        # TODO: Check user full_name for spam

        # If user marked as spammer, ban it again
        if userInfo["is_spammer"]:
            logger.info(f"SPAM: User {sender} is marked as spammer, banning it again")
            logger.info(f"SPAM: {userInfo}")
            spamScore = spamScore + 100

        # Check if for last 10 messages there are more same messages than different ones:
        userMessages = self.db.getChatMessagesByUser(chatId=chatId, userId=sender.id, limit=10)
        spamMessagesCount = 0
        nonSpamMessagesCount = 0
        for msg in userMessages:
            if msg["message_text"] == ensuredMessage.messageText and msg["message_id"] != ensuredMessage.messageId:
                spamMessagesCount = spamMessagesCount + 1
            else:
                nonSpamMessagesCount = nonSpamMessagesCount + 1

        if spamMessagesCount > 0 and spamMessagesCount > nonSpamMessagesCount:
            logger.info(
                f"SPAM: Last user messages: {userMessages}\n"
                f"Spam: {spamMessagesCount}, non-Spam: {nonSpamMessagesCount}"
            )
            _spamScore = ((spamMessagesCount + 1) / (spamMessagesCount + 1 + nonSpamMessagesCount)) * 100
            spamScore = max(spamScore, _spamScore)

        # If we had the same spam messages, then it's also spam
        sameSpamMessages = self.db.getSpamMessagesByText(ensuredMessage.messageText)
        if len(sameSpamMessages) > 0:
            logger.info(f"SPAM: Found {len(sameSpamMessages)} spam messages, so deciding, that it is SPAM")
            spamScore = max(spamScore, 100)

        # TODO: Entities Parsing is supported for TelegramOnly for now
        if isinstance(message, telegram.Message):
            messageText = ensuredMessage.messageText
            entities = message.entities
            if message.text:
                messageText = message.text
                entities = message.entities
            elif message.caption:
                messageText = message.caption
                entities = message.caption_entities
            else:
                logger.error(
                    f"SPAM: {chatId}#{ensuredMessage.messageId}: " "text and caption are empty while messageText isn't/"
                )

            if messageText and entities:
                for entity in entities:
                    match entity.type:
                        case MessageEntityType.URL | MessageEntityType.TEXT_LINK:
                            # Any URL looks like a spam
                            spamScore = spamScore + 60
                            logger.debug(f"SPAM: Found URL ({entity.type}) in message, adding 60 to spam score")
                        case MessageEntityType.MENTION:
                            mentionStr = parse_message_entity(messageText, entity)
                            chatUser = self.db.getChatUserByUsername(
                                chatId=ensuredMessage.recipient.id, username=mentionStr
                            )
                            if chatUser is None:
                                # Mentioning user not from chat looks like spam
                                spamScore = spamScore + 60
                                logger.debug(f"SPAM: Found mention ({mentionStr}) in message, adding 60 to spam score")
                                if mentionStr.endswith("bot"):
                                    spamScore = spamScore + 40
                                    logger.debug(
                                        f"SPAM: Found mention of bot ({mentionStr}) in message, "
                                        "adding 40 more to spam score"
                                    )

        warnTreshold = chatSettings[ChatSettingsKey.SPAM_WARN_TRESHOLD].toFloat()
        banTreshold = chatSettings[ChatSettingsKey.SPAM_BAN_TRESHOLD].toFloat()

        # Add Bayes filter classification, if message wasn't been marked as spam already (for performance purposes)
        if spamScore < banTreshold and chatSettings[ChatSettingsKey.BAYES_ENABLED].toBool():
            try:
                useTrigrams = chatSettings[ChatSettingsKey.BAYES_USE_TRIGRAMS].toBool()
                bayesResult = await self.bayesFilter.classify(
                    messageText=ensuredMessage.messageText,
                    chatId=chatId,
                    threshold=warnTreshold,  # Use existing threshold (We'll ignore it anyway)
                    ignoreTrigrams=not useTrigrams,
                )
                logger.debug(f"SPAM Bayes: Check result: {bayesResult}")

                # Check minimum confidence requirement
                minConfidence = chatSettings[ChatSettingsKey.BAYES_MIN_CONFIDENCE].toFloat()
                if bayesResult.confidence >= minConfidence:
                    logger.debug(
                        f"SPAM Bayes: Rules Score: {spamScore:.2f}, Bayes Score: {bayesResult.score:.2f}, "
                        f"Confidence: {bayesResult.confidence:.3f}"
                    )

                    # Use combined score for final decision
                    spamScore = spamScore + bayesResult.score
                else:
                    logger.debug(
                        f"SPAM Bayes: confidence {bayesResult.confidence:.3f} < {minConfidence}, ignoring result"
                    )

            except Exception as e:
                logger.error(f"SPAM Bayes: Failed to run Bayes filter classification: {e}")
                logger.exception(e)
                # Continue with original spamScore if Bayes filter fails
        else:
            logger.debug(f"SPAM Bayes: Bayes filter disabled or not needed (spamScore: {spamScore})")

        if spamScore >= banTreshold:
            logger.info(f"SPAM: spamScore: {spamScore} > {banTreshold} {ensuredMessage.getBaseMessage()}")
            userName = sender.name or sender.username
            banMessage = await self.sendMessage(
                ensuredMessage,
                messageText=f"Пользователь [{userName}](tg://user?id={sender.id})"
                " заблокирован за спам.\n"
                f"(Вероятность: {spamScore:.3f}, порог: {banTreshold})\n"
                "(Данное сообщение будет удалено в течение минуты)",
                messageCategory=MessageCategory.BOT_SPAM_NOTIFICATION,
            )
            if banMessage is not None:
                await self.queueService.addDelayedTask(
                    time.time() + 60,
                    DelayedTaskFunction.DELETE_MESSAGE,
                    kwargs={"messageId": banMessage.message_id, "chatId": banMessage.chat_id},
                    taskId=f"del-{banMessage.chat_id}-{banMessage.message_id}",
                )
            else:
                logger.error("Wasn't been able to send SPAM notification")
            await self.markAsSpam(ensuredMessage=ensuredMessage, reason=SpamReason.AUTO, score=spamScore)
            return True
        elif spamScore >= warnTreshold:
            logger.info(f"Possible SPAM: spamScore: {spamScore} >= {warnTreshold} {ensuredMessage}")
            sentMessage = await self.sendMessage(
                ensuredMessage,
                messageText=(
                    f"Возможно спам (Вероятность: {spamScore:.3f}, "
                    f"порог: {warnTreshold}, id: {ensuredMessage.messageId})\n"
                ),
                replyMarkup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Да, это Спам",
                                callback_data=utils.packDict(
                                    {
                                        ButtonDataKey.SpamAction: True,
                                        ButtonDataKey.ActionHash: self._makeSpamButtonSignature(ensuredMessage, True),
                                    }
                                ),
                            ),
                            InlineKeyboardButton(
                                "Нет, это НЕ Спам",
                                callback_data=utils.packDict(
                                    {
                                        ButtonDataKey.SpamAction: False,
                                        ButtonDataKey.ActionHash: self._makeSpamButtonSignature(ensuredMessage, False),
                                    }
                                ),
                            ),
                        ],
                    ]
                ),
                messageCategory=MessageCategory.BOT_SPAM_NOTIFICATION,
            )
            if sentMessage is not None:
                self._rememberSpamWarningMessage(sentMessage)
        else:
            logger.debug(f"Not SPAM: spamScore: {spamScore} < {warnTreshold} {ensuredMessage}")

        return False

    async def markAsSpam(self, ensuredMessage: EnsuredMessage, reason: SpamReason, score: Optional[float] = None):
        """
        Mark message as spam, ban user, and delete message, dood!

        This method performs the following actions:
        1. Validates that target is not an admin
        2. Checks if user is old enough to be marked as spam (unless admin override)
        3. Learns the message as spam in Bayes filter (if enabled)
        4. Saves spam message to database
        5. Deletes the spam message
        6. Bans the user (and sender chat if applicable)
        7. Optionally deletes all recent user messages

        Args:
            message (Message): The spam message to handle.
            reason (SpamReason): Reason for marking as spam (AUTO, ADMIN, USER).
            score (Optional[float]): Spam confidence score (0-100+). Defaults to 0.

        Note:
            - Admins cannot be marked as spam
            - Old users (messages_count > maxSpamMessages) cannot be auto-marked
            - Admin-marked spam can override old user protection
            - Bayes filter learns from spam if auto-learning is enabled
            - Up to 10 recent user messages can be deleted if configured
        """
        message = ensuredMessage.getBaseMessage()
        chatSettings = self.getChatSettings(ensuredMessage.recipient.id)

        logger.debug(
            f"Handling spam message: #{ensuredMessage.recipient.id}:{ensuredMessage.messageId}"
            f" '{ensuredMessage.messageText}'"
            f" from {ensuredMessage.sender}. Reason: {reason}"
        )

        chatId = ensuredMessage.recipient.id
        userId = ensuredMessage.sender.id

        if await self.isAdmin(user=ensuredMessage.sender, chat=ensuredMessage.recipient):
            # It is admin, do nothing
            logger.warning(f"Tried to mark Admin {ensuredMessage.sender} as SPAM")
            await self.sendMessage(
                ensuredMessage,
                messageText="Алярм! Попытка представить администратора спаммером",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )
            return

        canMarkOldUsers = chatSettings[ChatSettingsKey.ALLOW_MARK_SPAM_OLD_USERS].toBool()
        if reason != SpamReason.ADMIN or not canMarkOldUsers:
            # Check if we are trying to ban old chat member and it is not from Admin
            userInfo = self.db.getChatUser(chatId=chatId, userId=userId)
            maxSpamMessages = chatSettings[ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES].toInt()
            if maxSpamMessages != 0 and userInfo and userInfo["messages_count"] > maxSpamMessages:
                logger.warning(f"Tried to mark old user {ensuredMessage.sender} as SPAM")
                await self.sendMessage(
                    ensuredMessage,
                    messageText="Алярм! Попытка представить честного пользователя спаммером",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )
                return

        # Learn from spam message using Bayes filter, dood!
        doBayesLearn = chatSettings[ChatSettingsKey.BAYES_AUTO_LEARN].toBool()
        if ensuredMessage.messageText and doBayesLearn:
            try:
                await self.bayesFilter.learnSpam(messageText=ensuredMessage.messageText, chatId=chatId)
                logger.debug(
                    "Bayes filter learned spam message: "
                    f"{ensuredMessage.recipient.id}:{ensuredMessage.messageId}, dood!"
                )
            except Exception as e:
                logger.error(f"Failed to learn spam message in Bayes filter: {e}, dood!")

        if ensuredMessage.messageText:
            self.db.addSpamMessage(
                chatId=chatId,
                userId=userId,
                messageId=ensuredMessage.messageId,
                messageText=str(ensuredMessage.messageText),
                spamReason=reason,
                score=score if score is not None else 0,
            )

        if (
            self.botProvider == BotProvider.TELEGRAM
            and self._tgBot is not None
            and isinstance(message, telegram.Message)
        ):
            bot = self._tgBot
            await bot.delete_message(chat_id=chatId, message_id=int(ensuredMessage.messageId))
            logger.debug("Deleted spam message")
            if message.sender_chat is not None:
                await bot.ban_chat_sender_chat(chat_id=chatId, sender_chat_id=message.sender_chat.id)
            if message.from_user is not None:
                await bot.ban_chat_member(chat_id=chatId, user_id=userId, revoke_messages=True)
            else:
                logger.error(f"message.from_user is None (sender is {ensuredMessage.sender})")
        else:
            # TODO: Support Max
            logger.error(f"Deleteing spam messages is not supported in {self.botProvider}")

        self.db.markUserIsSpammer(chatId=chatId, userId=userId, isSpammer=True)
        logger.debug(f"Banned user {ensuredMessage.sender} in chat {ensuredMessage.recipient}")
        if chatSettings[ChatSettingsKey.SPAM_DELETE_ALL_USER_MESSAGES].toBool():
            maxMessagesToDelete = chatSettings[ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES].toInt()
            # Cap max messages to delete by some saint number
            maxMessagesToDelete = min(max(maxMessagesToDelete, 1), 32)
            userMessages = self.db.getChatMessagesByUser(
                chatId=chatId,
                userId=userId,
                limit=maxMessagesToDelete,
            )
            logger.debug(f"Trying to delete more user messages: {userMessages}")
            messageIds: List[MessageIdType] = []
            for msg in userMessages:
                if msg["message_id"] != ensuredMessage.messageId:
                    messageIds.append(msg["message_id"])

                    # Auto learn user messages as SPAM
                    if msg["message_text"] and doBayesLearn:
                        try:
                            await self.bayesFilter.learnSpam(messageText=msg["message_text"], chatId=msg["chat_id"])
                            logger.debug(
                                f"Bayes filter learned spam message: {msg['chat_id']}{msg['message_id']}, dood!"
                            )
                        except Exception as e:
                            logger.error(f"Failed to learn spam message in Bayes filter: {e}, dood!")
                    # And add message to spam-base
                    if msg["message_text"]:
                        self.db.addSpamMessage(
                            chatId=msg["chat_id"],
                            userId=msg["user_id"],
                            messageId=msg["message_id"],
                            messageText=msg["message_text"],
                            spamReason=reason,
                            score=score if score is not None else 0,
                        )
                # Update message category to USER_SPAM
                # TODO: We can do bulk upgrade, but i don't care, actually
                self.db.updateChatMessageCategory(
                    chatId=msg["chat_id"],
                    messageId=msg["message_id"],
                    messageCategory=MessageCategory.USER_SPAM,
                )

            try:
                if messageIds:
                    if self.botProvider == BotProvider.TELEGRAM and self._tgBot is not None:
                        await self._tgBot.delete_messages(chat_id=chatId, message_ids=[int(mid) for mid in messageIds])
                    elif self.botProvider == BotProvider.MAX and self._maxBot is not None:
                        await self._maxBot.deleteMessages([str(mid) for mid in messageIds])
                    else:
                        # TODO: Support Max
                        logger.error(f"Deleteing spam messages is not supported in {self.botProvider}")

            except Exception as e:
                logger.error("Failed during deleteing spam message:")
                logger.exception(e)

    async def markAsHam(self, message: EnsuredMessage) -> bool:
        """
        Mark message as ham (not spam) for Bayes filter learning, dood!

        Teaches the Bayes filter that this message is legitimate (ham), improving
        future spam detection accuracy.

        Args:
            message (Message): The legitimate message to learn from.

        Returns:
            bool: True if learning succeeded, False otherwise.

        Note:
            - Only messages with text can be learned
            - Failures are logged but don't raise exceptions
        """
        if not message.messageText:
            return False

        try:
            await self.bayesFilter.learnHam(messageText=message.messageText, chatId=message.recipient.id)
            logger.debug(f"Bayes filter learned ham message: {message.recipient.id}:{message.messageId}, dood!")
            return True
        except Exception as e:
            logger.error(f"Failed to learn ham message in Bayes filter: {e}, dood!")
            return False

    async def getBayesFilterStats(self, chatId: Optional[int] = None) -> Dict[str, Any]:
        """
        Get Bayes filter statistics for debugging and monitoring, dood!

        Retrieves comprehensive statistics about the Bayes filter's training state
        and performance for a specific chat or globally.

        Args:
            chatId (Optional[int]): Chat ID to get stats for. None for global stats.

        Returns:
            Dict[str, Any]: Dictionary containing:
                - total_spam_messages: Number of spam messages learned
                - total_ham_messages: Number of ham messages learned
                - total_messages: Total messages in training set
                - vocabulary_size: Number of unique tokens
                - spam_ratio: Proportion of spam messages
                - ham_ratio: Proportion of ham messages
                - chat_id: The chat ID (or None for global)

        Note:
            Returns empty dict on error (logged but not raised).
        """
        try:
            model_stats = await self.bayesFilter.getModelInfo(chatId)
            return {
                "total_spam_messages": model_stats.total_spam_messages,
                "total_ham_messages": model_stats.total_ham_messages,
                "total_messages": model_stats.total_messages,
                "vocabulary_size": model_stats.vocabulary_size,
                "spam_ratio": model_stats.spam_ratio,
                "ham_ratio": model_stats.ham_ratio,
                "chat_id": chatId,
            }
        except Exception as e:
            logger.error(f"Failed to get Bayes filter stats: {e}, dood!")
            return {}

    async def resetBayesFilter(self, chat_id: Optional[int] = None) -> bool:
        """
        Reset Bayes filter statistics and training data, dood!

        Clears all learned spam/ham data for a specific chat or globally.
        Use with caution as this removes all training progress!

        Args:
            chat_id (Optional[int]): Chat ID to reset. None resets global filter.

        Returns:
            bool: True if reset succeeded, False otherwise.

        Warning:
            This operation cannot be undone! All training data will be lost.
        """
        try:
            success = await self.bayesFilter.reset(chat_id)
            if success:
                scope = f"chat {chat_id}" if chat_id else "global"
                logger.info(f"Successfully reset Bayes filter for {scope}, dood!")
            return success
        except Exception as e:
            logger.error(f"Failed to reset Bayes filter: {e}, dood!")
            return False

    async def trainBayesFromHistory(self, chatId: int, limit: int = 1000) -> Dict[str, int]:
        """
        Train Bayes filter from existing spam messages and chat history, dood!

        Performs initial or supplemental training by learning from:
        1. Previously identified spam messages in the database
        2. Regular user messages as ham (excluding spam users)

        This is useful for:
        - Initial filter setup in existing chats
        - Retraining after filter reset
        - Improving accuracy with historical data

        Args:
            chatId (int): Chat ID to train filter for.
            limit (int): Maximum number of messages to process. Defaults to 1000.

        Returns:
            Dict[str, int]: Training statistics containing:
                - spam_learned: Number of spam messages successfully learned
                - ham_learned: Number of ham messages successfully learned
                - failed: Number of messages that failed to process

        Note:
            - Only processes messages from the specified chat
            - Skips messages from users already marked as spammers
            - Processes up to `limit` messages of each type (spam and ham)
        """
        stats = {"spam_learned": 0, "ham_learned": 0, "failed": 0}

        try:
            # Learn from existing spam messages
            spam_messages = self.db.getSpamMessages(limit=limit)  # Get all spam messages
            spamUsersIds: Set[int] = {-1}
            for spamMsg in spam_messages:
                if spamMsg["chat_id"] == chatId and spamMsg["text"]:
                    spamUsersIds.add(spamMsg["user_id"])
                    success = await self.bayesFilter.learnSpam(messageText=spamMsg["text"], chatId=chatId)
                    if success:
                        stats["spam_learned"] += 1
                    else:
                        stats["failed"] += 1

            # Learn from regular user messages as ham
            hamMessages = self.db.getChatMessagesSince(
                chatId=chatId, limit=limit, messageCategory=[MessageCategory.USER]
            )
            for hamMsg in hamMessages:
                # Skip if already marked as spam
                if all(
                    (
                        hamMsg["message_category"] != MessageCategory.USER_SPAM,
                        hamMsg["message_text"],
                        hamMsg["user_id"] not in spamUsersIds,
                    )
                ):
                    success = await self.bayesFilter.learnHam(messageText=hamMsg["message_text"], chatId=chatId)
                    if success:
                        stats["ham_learned"] += 1
                    else:
                        stats["failed"] += 1

            logger.info(f"Bayes training completed for chat {chatId}: {stats}, dood!")
            return stats

        except Exception as e:
            logger.error(f"Failed to train Bayes filter from history: {e}, dood!")
            stats["failed"] += 1
            return stats

    ###
    # Handling messages
    ###

    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
        """
        Main message handler for automatic spam detection, dood!

        This handler is called for every message and performs spam checking
        in group and supergroup chats if spam detection is enabled.

        Args:
            update (Update): Telegram update object containing the message.
            context (ContextTypes.DEFAULT_TYPE): Bot context for the update.
            ensuredMessage (Optional[EnsuredMessage]): Pre-processed message wrapper.

        Returns:
            HandlerResultStatus: Handler execution status:
                - SKIPPED: Private chat (no spam check needed)
                - FATAL: Message was spam and handled (stop processing)
                - NEXT: Message is not spam (continue processing)
                - ERROR: Error occurred during spam check

        Note:
            - Private messages are not checked for spam
            - Spam detection must be enabled in chat settings
            - If spam is detected, message is deleted and user is banned
        """

        if ensuredMessage is None:
            # Not new message, Skip
            return HandlerResultStatus.SKIPPED

        match ensuredMessage.recipient.chatType:
            case ChatType.PRIVATE:
                # No need to check spam in private messages
                return HandlerResultStatus.SKIPPED
            case ChatType.GROUP:
                try:
                    chatSettings = self.getChatSettings(ensuredMessage.recipient.id)

                    if chatSettings[ChatSettingsKey.DETECT_SPAM].toBool():
                        if await self.checkSpam(ensuredMessage):
                            # It's spam, no further processing needed
                            return HandlerResultStatus.FINAL

                    # We can't add cyrilic sumbols as command handler, so doing it manually
                    spamCommands = ["/спам"]
                    rawMessage = ensuredMessage.getRawMessageText()
                    for spamCommand in spamCommands:
                        if rawMessage and rawMessage[0] == "/" and rawMessage.lower().strip().startswith(spamCommand):
                            await self.spam_command(update, context)
                            return HandlerResultStatus.FINAL

                    return HandlerResultStatus.NEXT
                except Exception as e:
                    logger.error(f"Error while checking spam: {e}")
                    return HandlerResultStatus.ERROR

            case _:
                # logger.warning(f"Unsupported chat type: {chatType}")
                return HandlerResultStatus.SKIPPED

    ###
    # Handling Click on SPAM/NotSPAM buttons
    ###

    async def buttonHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: CallbackDataDict
    ) -> HandlerResultStatus:
        """
        Handle inline keyboard button callbacks for possible-spam messages, dood!
        """

        query = update.callback_query
        if query is None:
            logger.error("handle_button: query is None")
            return HandlerResultStatus.FATAL

        spamAction = data.get(ButtonDataKey.SpamAction, None)

        if spamAction is None:
            return HandlerResultStatus.SKIPPED
        if not isinstance(spamAction, bool):
            logger.error(f"Invalid spam action {type(spamAction).__name__}({spamAction}) in {data}")
            return HandlerResultStatus.FATAL

        message = query.message
        if not isinstance(message, Message):
            logger.error(f"handle_button: message {message} not Message in {query}")
            return HandlerResultStatus.FATAL

        user = MessageSender.fromTelegramUser(query.from_user)
        chat = MessageRecipient.fromTelegramChat(message.chat)

        if message.from_user is None or message.from_user.id != context.bot.id:
            logger.error(f"handle_button: Base message from {message.from_user}, not bot (#{context.bot.id})")
            return HandlerResultStatus.FATAL

        messageInfo = self._getSpamWarningMessageInfo(chatId=chat.id, messageId=message.message_id)

        if message.reply_to_message is None:
            if messageInfo is not None:
                self._deleteSpamWarningMessageInfo(chatId=chat.id, messageId=message.message_id)
                logger.info(f"handle_button: repliedMessage is deleted, but messageInfo is {messageInfo}")
                # TODO: We can get message from DB and create Message\EnsuredMessage for it
                try:
                    await message.delete()
                except Exception as e:
                    logger.error(f"handle_button: failed to delete message {message} in {query}: {e}")

                return HandlerResultStatus.FINAL
            else:
                logger.error(f"handle_button: Base message is not reply to message in {query}")
                return HandlerResultStatus.FATAL

        repliedMessage = message.reply_to_message
        eRepliedMessage = EnsuredMessage.fromTelegramMessage(message.reply_to_message)

        passedHash = data.get(ButtonDataKey.ActionHash, None)
        neededHash = self._makeSpamButtonSignature(eRepliedMessage, spamAction)

        if passedHash != neededHash:
            logger.error(f"handle_button: passed hash {passedHash} does not match needed hash {neededHash} in {query}")
            return HandlerResultStatus.FATAL

        isAdmin = await self.isAdmin(user=user, chat=chat)

        chatSettings = self.getChatSettings(chatId=chat.id)
        userCanMarkSpam = chatSettings[ChatSettingsKey.ALLOW_USER_SPAM_COMMAND].toBool()

        if not isAdmin and not userCanMarkSpam:
            logger.info(f"user {user} in chat {chat} tried to click [Not]SPAM button. Denied.")
            return HandlerResultStatus.FINAL

        self._deleteSpamWarningMessageInfo(chatId=chat.id, messageId=message.message_id)
        markReason = SpamReason.ADMIN if isAdmin else SpamReason.USER

        logger.debug(f"SPAM: Message {repliedMessage} tagged as isSpam={spamAction} by {user}")
        reportedUser = repliedMessage.from_user if repliedMessage.from_user else user
        hamPrefix = ""

        if spamAction:
            # Mark As SPAM will doo what we need: mark message, add to db, ban user, delete messages
            await self.markAsSpam(eRepliedMessage, markReason, 100)

        else:
            # Mark As HAM will only learn Bayes as HAM, all other things need to be done manually
            messageText = repliedMessage.text or repliedMessage.caption or ""
            hamUserId = repliedMessage.from_user.id if repliedMessage.from_user is not None else 0
            hamPrefix = "НЕ "
            if messageText:
                await self.markAsHam(eRepliedMessage)

                self.db.addHamMessage(
                    chatId=chat.id,
                    userId=hamUserId,
                    messageId=repliedMessage.message_id,
                    messageText=messageText,
                    spamReason=markReason,
                    score=100,
                )

            if repliedMessage.from_user:
                hamUserDB: Optional[ChatUserDict] = self.db.getChatUser(chatId=chat.id, userId=hamUserId)
                if hamUserDB is not None:
                    userMetadata = self.parseUserMetadata(hamUserDB)
                    userMetadata["notSpammer"] = True
                    self.setUserMetadata(
                        chatId=hamUserDB["chat_id"], userId=hamUserDB["user_id"], metadata=userMetadata
                    )

        # We need to fallback somewhere, let's fallback to called user
        reportedUser = MessageSender.fromTelegramUser(repliedMessage.from_user) if repliedMessage.from_user else user
        await message.edit_text(
            f"[{user.name}](tg://user?id={user.id}) подтвердил, что "
            f"[{reportedUser.name}](tg://user?id={reportedUser.id}) {hamPrefix}Спаммер \n"
            "\\(Данное сообщение будет удалено в течение минуты\\)",
            parse_mode="MarkdownV2",
        )

        await self.queueService.addDelayedTask(
            time.time() + 60,
            DelayedTaskFunction.DELETE_MESSAGE,
            kwargs={"messageId": message.message_id, "chatId": chat.id},
            taskId=f"del-{chat.id}-{message.message_id}",
        )

        return HandlerResultStatus.FINAL

    ###
    # Command Handlers
    ###

    @commandHandlerExtended(
        commands=("bayes_stats",),
        shortDescription="Get bayes stats",
        helpMessage=": Вывести статистику байесовсокго фильтра по чатам.",
        suggestCategories={CommandPermission.BOT_OWNER, CommandPermission.HIDDEN},
        availableFor={CommandPermission.BOT_OWNER},
        helpOrder=CommandHandlerOrder.TEST,
        category=CommandCategory.TECHNICAL,
    )
    async def bayes_stats_command(
        self,
        ensuredMessage: EnsuredMessage,
        typingManager: Optional[TypingManager],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Display Bayesian filter statistics for all group chats, dood!

        This command shows statistics about the Bayesian spam filter for each
        group chat, including the number of spam and ham messages processed,
        filter accuracy, and other relevant metrics.
        """
        for chatInfo in self.db.getAllGroupChats():
            stats = await self.getBayesFilterStats(chatId=chatInfo["chat_id"])
            chatTitle = self.getChatTitle(chatInfo)

            await self.sendMessage(
                ensuredMessage,
                messageText=f"{chatTitle}\n```json\n{utils.jsonDumps(stats, indent=2)}\n```\n",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )
            await asyncio.sleep(0.5)

    @commandHandlerExtended(
        commands=("spam",),
        shortDescription="Mark answered message as spam",
        helpMessage="|`/спам`: Указать боту на сообщение со спамом (должно быть ответом на спам-сообщение).",
        suggestCategories={CommandPermission.ADMIN},
        availableFor={CommandPermission.GROUP},
        helpOrder=CommandHandlerOrder.SPAM,
        category=CommandCategory.SPAM,
    )
    async def spam_command(
        self,
        ensuredMessage: EnsuredMessage,
        typingManager: Optional[TypingManager],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /spam command to manually mark messages as spam, dood!

        Allows admins (and optionally regular users) to report spam messages
        by replying to them with the /spam command.

        Args:
            update (Update): Telegram update object containing the command.
            context (ContextTypes.DEFAULT_TYPE): Bot context for the command.

        Command Format:
            /spam (as reply to spam message)

        Behavior:
            - Must be used as a reply to the spam message
            - Admins can always use this command
            - Regular users can use it if ALLOW_USER_SPAM_COMMAND is enabled
            - Marks message as spam with reason ADMIN or USER
            - Deletes the spam message and bans the user
            - Command message is automatically deleted to reduce clutter

        Note:
            - Admin reports have higher confidence score (100 vs 50)
            - User reports require explicit permission in chat settings
        """

        repliedMessage = ensuredMessage.getEnsuredRepliedToMessage()
        isAdmin = await self.isAdmin(user=ensuredMessage.sender, chat=ensuredMessage.recipient)

        logger.debug(
            "Got /spam command \n"
            f"from User({ensuredMessage.sender}) "
            f"in Chat({ensuredMessage.recipient}) \n"
            f"to Message({repliedMessage}) \n"
            f"isAdmin: {isAdmin}"
        )

        if repliedMessage is not None:
            await self.markAsSpam(
                repliedMessage,
                reason=SpamReason.ADMIN if isAdmin else SpamReason.USER,
                score=100 if isAdmin else 50,  # TODO: Think about score for user
            )

        # Delete command message to reduce flood
        if self.botProvider == BotProvider.TELEGRAM and self._tgBot is not None:
            await self._tgBot.delete_message(
                chat_id=ensuredMessage.recipient.id, message_id=int(ensuredMessage.messageId)
            )
        elif self.botProvider == BotProvider.MAX and self._maxBot is not None:
            await self._maxBot.deleteMessages([str(ensuredMessage.messageId)])
        else:
            logger.error(f"Can't delete message in {self.botProvider} platform")

    @commandHandlerExtended(
        commands=("pretrain_bayes",),
        shortDescription="[<chatId>] - initially train bayes filter with up to 1000 last messages",
        helpMessage=" [`<chatId>`]: Предобучить Баесовский антиспам фильтр на последних 1000 сообщениях.",
        suggestCategories={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.ADMIN},
        helpOrder=CommandHandlerOrder.SPAM,
        category=CommandCategory.SPAM_ADMIN,
    )
    async def pretrain_bayes_command(
        self,
        ensuredMessage: EnsuredMessage,
        typingManager: Optional[TypingManager],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /pretrain_bayes [<chatId>] command for initial filter training, dood!

        Trains the Bayes spam filter using up to 1000 historical messages from
        the specified chat. This is useful for setting up spam detection in
        existing chats with message history.

        Args:
            update (Update): Telegram update object containing the command.
            context (ContextTypes.DEFAULT_TYPE): Bot context with optional chatId argument.

        Command Format:
            /pretrain_bayes [<chatId>]

        Arguments:
            chatId (optional): Target chat ID. Defaults to current chat.

        Returns:
            Sends a message with training statistics including:
            - Number of spam messages learned
            - Number of ham messages learned
            - Total vocabulary size
            - Spam/ham ratios

        Note:
            - Requires admin permissions in target chat
            - Processes up to 1000 messages of each type
            - Can be run multiple times to improve accuracy
            - Only available in private chats with the bot
        """

        targetChatId = utils.extractInt(context.args)
        if targetChatId is None:
            targetChatId = ensuredMessage.recipient.id

        targetChat = MessageRecipient(
            id=targetChatId, chatType=ChatType.PRIVATE if targetChatId > 0 else ChatType.GROUP
        )

        if not await self.isAdmin(user=ensuredMessage.sender, chat=targetChat):
            await self.sendMessage(
                ensuredMessage,
                messageText="У Вас нет прав для выполнения данной команды.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        await self.trainBayesFromHistory(chatId=targetChatId)
        stats = await self.getBayesFilterStats(chatId=targetChatId)

        await self.sendMessage(
            ensuredMessage,
            messageText=f"Готово:\n```json\n{utils.jsonDumps(stats, indent=2)}\n```\n",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandlerExtended(
        commands=("learn_spam", "learn_ham"),
        shortDescription="[<chatId>] - learn answered message (or quote) as spam/ham for given chat",
        helpMessage=" [`<chatId>`]: Обучить баесовский фильтр на указанным сообщении (или цитате) как спам/не-спам.",
        suggestCategories={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.ADMIN},
        helpOrder=CommandHandlerOrder.SPAM,
        category=CommandCategory.SPAM_ADMIN,
    )
    async def learn_spam_ham_command(
        self,
        ensuredMessage: EnsuredMessage,
        typingManager: Optional[TypingManager],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /learn_spam and /learn_ham commands for manual filter training, dood!

        Allows admins to manually teach the Bayes filter by marking specific
        messages as spam or ham (not spam). Useful for correcting filter mistakes
        or training on edge cases.

        Args:
            update (Update): Telegram update object containing the command.
            context (ContextTypes.DEFAULT_TYPE): Bot context with optional chatId argument.

        Command Format:
            /learn_spam [<chatId>] (as reply or quote)
            /learn_ham [<chatId>] (as reply or quote)

        Arguments:
            chatId (optional): Target chat ID. Defaults to current chat or quoted message's chat.

        Behavior:
            - Must be used as reply to a message or with a quote
            - Message text must be at least 3 characters long
            - Learns the message for the specified chat's filter
            - Saves to spam/ham database for future reference
            - Requires admin permissions in target chat

        Note:
            - Works with both replies and external quotes
            - External quotes automatically use the source chat ID
            - Only available in private chats with the bot
            - Useful for training on messages from other chats
        """
        message = ensuredMessage.getBaseMessage()

        if self.botProvider != BotProvider.TELEGRAM or not isinstance(message, telegram.Message):
            await self.sendMessage(
                ensuredMessage,
                messageText="Команда не поддержана на данной платформе",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        commandStr = ""
        for entityStr in message.parse_entities([MessageEntityType.BOT_COMMAND]).values():
            commandStr = entityStr
            break

        logger.debug(f"Command string: {commandStr}")
        isLearnSpam = commandStr.lower().startswith("/learn_spam")

        repliedText = ensuredMessage.replyText or ensuredMessage.quoteText
        if not repliedText or len(repliedText) < 3:
            await self.sendMessage(
                ensuredMessage,
                "Команда должна быть ответом на сообщение достаточной длинны",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        targetChatId = utils.extractInt(context.args)
        if targetChatId is None:
            targetChatId = ensuredMessage.recipient.id
            # If it's quote from another chat, use it as chatId
            if message.external_reply and message.external_reply.chat:
                targetChatId = message.external_reply.chat.id

        chatObj = MessageRecipient(id=targetChatId, chatType=ChatType.PRIVATE if targetChatId > 0 else ChatType.GROUP)

        isAdmin = await self.isAdmin(ensuredMessage.sender, chatObj, allowBotOwners=True)

        if not isAdmin:
            await self.sendMessage(
                ensuredMessage,
                "Вы не являетесь администратором в целевом чате",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        if isLearnSpam:
            await self.bayesFilter.learnSpam(messageText=repliedText, chatId=targetChatId)
            self.db.addSpamMessage(
                chatId=targetChatId,
                userId=0,
                messageId=0,
                messageText=repliedText,
                spamReason=SpamReason.ADMIN,
                score=100,
            )
            await self.sendMessage(
                ensuredMessage,
                f"Сообщение \n```\n{repliedText}\n```\n Запомнено как СПАМ для чата #`{targetChatId}`",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )
        else:
            await self.bayesFilter.learnHam(messageText=repliedText, chatId=targetChatId)
            self.db.addHamMessage(
                chatId=targetChatId,
                userId=0,
                messageId=0,
                messageText=repliedText,
                spamReason=SpamReason.ADMIN,
                score=100,
            )
            await self.sendMessage(
                ensuredMessage,
                f"Сообщение \n```\n{repliedText}\n```\n Запомнено как НЕ СПАМ для чата #`{targetChatId}`",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )

    @commandHandlerExtended(
        commands=("get_spam_score",),
        shortDescription="[<chatId>] - Analyze answered (or qoted) message for spam and print result",
        helpMessage=" `[<chatId>]`: Выдать результат проверки указанного сообщения (или цитаты) на спам.",
        suggestCategories={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.BOT_OWNER},
        helpOrder=CommandHandlerOrder.SPAM,
        category=CommandCategory.TECHNICAL,
    )
    async def get_spam_score_command(
        self,
        ensuredMessage: EnsuredMessage,
        typingManager: Optional[TypingManager],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /get_spam_score command to analyze messages for spam, dood!

        Analyzes a message using the Bayes filter and returns detailed spam
        classification results without taking any action. Useful for testing
        and debugging spam detection.

        Args:
            update (Update): Telegram update object containing the command.
            context (ContextTypes.DEFAULT_TYPE): Bot context with optional chatId argument.

        Command Format:
            /get_spam_score [<chatId>] (as reply or quote)

        Arguments:
            chatId (optional): Target chat ID for classification context.
                             Defaults to current chat or quoted message's chat.

        Returns:
            Sends a message with classification results including:
            - Spam probability score
            - Classification confidence
            - Whether message would be flagged as spam

        Behavior:
            - Must be used as reply to a message or with a quote
            - Message text must be at least 3 characters long
            - Only analyzes, does not mark as spam or take action
            - Uses the specified chat's trained filter

        Note:
            - Only available in private chats with the bot
            - Works with both replies and external quotes
            - Useful for testing filter accuracy before deployment
        """
        message = ensuredMessage.getBaseMessage()
        if self.botProvider != BotProvider.TELEGRAM or not isinstance(message, telegram.Message):
            await self.sendMessage(
                ensuredMessage,
                messageText="Команда не поддержана на данной платформе",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        if ensuredMessage.recipient.chatType != ChatType.PRIVATE:
            logger.error(f"Unsupported chat type for /get_spam_score command: {ensuredMessage.recipient.chatType}")
            return

        repliedText = ensuredMessage.replyText or ensuredMessage.quoteText
        if not repliedText or len(repliedText) < 3:
            await self.sendMessage(
                ensuredMessage,
                "Команда должна быть ответом на сообщение достаточной длинны",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        chatId = ensuredMessage.recipient.id
        # If it's quote from another chat, use it as chatId
        if message.external_reply and message.external_reply.chat:
            chatId = message.external_reply.chat.id
        if context.args:
            try:
                chatId = int(context.args[0])
            except Exception as e:
                logger.error(f"Failed to parse chatId ({context.args[0]}): {e}")

        spamScore = await self.bayesFilter.classify(repliedText, chatId=chatId)
        await self.sendMessage(
            ensuredMessage,
            f"Сообщение \n```\n{repliedText}\n```\n В чате #`{chatId}` воспринимается как: \n"
            f"```json\n{spamScore}\n```\n",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandlerExtended(
        commands=("unban",),
        shortDescription="[<username>] - Unban user from current chat",
        helpMessage=" [`@<username>`]: Разбанить пользователя в данном чате. "
        "Так же может быть ответом на сообщение забаненного пользователя.",
        suggestCategories={CommandPermission.ADMIN},
        availableFor={CommandPermission.ADMIN, CommandPermission.GROUP},
        helpOrder=CommandHandlerOrder.SPAM,
        category=CommandCategory.SPAM,
    )
    async def unban_command(
        self,
        ensuredMessage: EnsuredMessage,
        typingManager: Optional[TypingManager],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /unban command to unban users and correct false positives, dood!

        Unbans a user from the chat and performs cleanup actions:
        1. Unbans user from Telegram chat
        2. Marks user as not spammer in database
        3. Moves user's spam messages to ham database
        4. Sets user metadata to skip future spam checks
        5. Optionally retrains Bayes filter with corrected data

        Args:
            update (Update): Telegram update object containing the command.
            context (ContextTypes.DEFAULT_TYPE): Bot context with optional username argument.

        Command Format:
            /unban [@username] (or as reply to user's message)

        Arguments:
            username (optional): Username of user to unban (with or without @).
                               Can also be used as reply to banned user's message.

        Behavior:
            - Requires admin permissions in the chat
            - User must exist in chat database
            - Removes ban from Telegram
            - Corrects spam/ham classification in database
            - Marks user as trusted (notSpammer=True) to prevent future false positives

        Note:
            - Can be used with username argument or as reply
            - Automatically retrains filter with corrected classifications
            - User will not be checked for spam in future (until metadata is cleared)
            - Useful for correcting false positives and improving filter accuracy
        """
        message = ensuredMessage.getBaseMessage()
        if self.botProvider != BotProvider.TELEGRAM or not isinstance(message, telegram.Message):
            await self.sendMessage(
                ensuredMessage,
                messageText="Команда не поддержана на данной платформе",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        user: Optional[ChatUserDict] = None
        if context.args:
            username = context.args[0]
            if not username.startswith("@"):
                username = "@" + username
            user = self.db.getChatUserByUsername(ensuredMessage.recipient.id, username)

        if user is None and message.reply_to_message and message.reply_to_message.from_user:
            user = self.db.getChatUser(chatId=ensuredMessage.recipient.id, userId=message.reply_to_message.from_user.id)

        if user is None:
            await self.sendMessage(
                ensuredMessage,
                "Пользователь не найден",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        bot = message.get_bot()
        # Unban user from chat
        if user["user_id"] > 0:
            await bot.unban_chat_member(chat_id=user["chat_id"], user_id=user["user_id"], only_if_banned=True)
        else:
            await bot.unban_chat_sender_chat(chat_id=user["chat_id"], sender_chat_id=user["user_id"])
        # Mark user as not spammer
        self.db.markUserIsSpammer(chatId=user["chat_id"], userId=user["user_id"], isSpammer=False)

        # Get user messages, remembered as spam, delete them from spam base and add them to ham base
        userMessages = self.db.getSpamMessagesByUserId(chatId=user["chat_id"], userId=user["user_id"])
        self.db.deleteSpamMessagesByUserId(chatId=user["chat_id"], userId=user["user_id"])
        for userMsg in userMessages:
            self.db.addHamMessage(
                chatId=userMsg["chat_id"],
                userId=userMsg["user_id"],
                messageId=userMsg["message_id"],
                messageText=userMsg["text"],
                spamReason=SpamReason.UNBAN,
                score=userMsg["score"],
            )

        # Set user metadata[notSpammer] = True to skip spam-check for this user in this chat
        userMetadata = self.parseUserMetadata(user)
        userMetadata["notSpammer"] = True
        self.setUserMetadata(chatId=user["chat_id"], userId=user["user_id"], metadata=userMetadata)

        userName = user["full_name"] if user["full_name"] else user["username"]
        await self.sendMessage(
            ensuredMessage,
            f"Пользователь [{userName}](tg://user?id={user['user_id']}) разбанен",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
