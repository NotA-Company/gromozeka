"""
Gromozeka SPAM Handlers.
"""

import asyncio
import datetime
import logging

import time
from typing import Any, Dict, List, Optional, Set


from telegram import Chat, Update, Message
from telegram.constants import MessageEntityType
from telegram.ext import ContextTypes
from telegram._utils.entities import parse_message_entity

from internal.bot.handlers.base import HandlerResultStatus

from .base import BaseBotHandler

from lib.ai.manager import LLMManager
from lib.spam import NaiveBayesFilter, BayesConfig
from lib.spam.tokenizer import TokenizerConfig
import lib.utils as utils

from internal.config.manager import ConfigManager

from internal.database.wrapper import DatabaseWrapper
from internal.database.bayes_storage import DatabaseBayesStorage
from internal.database.models import (
    ChatUserDict,
    MessageCategory,
    SpamReason,
)

from ..models import (
    ChatSettingsKey,
    CommandCategory,
    CommandHandlerOrder,
    DelayedTaskFunction,
    EnsuredMessage,
    commandHandler,
)

logger = logging.getLogger(__name__)


class SpamHandlers(BaseBotHandler):
    """
    Handle spam-related commands and events
    """

    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        """Initialize handlers with database and LLM model."""
        # Initialize the mixin (discovers handlers)
        super().__init__(configManager=configManager, database=database, llmManager=llmManager)

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

    async def checkSpam(self, ensuredMessage: EnsuredMessage) -> bool:
        """Check if message is spam."""

        message = ensuredMessage.getBaseMessage()
        if message.is_automatic_forward:
            # https://docs.python-telegram-bot.org/en/stable/telegram.message.html#telegram.Message.is_automatic_forward
            # It's a automatic forward from linked Channel. Its not spam.
            return False

        sender = ensuredMessage.sender
        chatId = ensuredMessage.chat.id

        if sender.id == chatId:
            # If sender ID == chat ID, then it is anonymous admin, so it isn't spam
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
                await self.markAsHam(message=message)
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
                        chatUser = self.db.getChatUserByUsername(chatId=ensuredMessage.chat.id, username=mentionStr)
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
                bayesResult = await self.bayesFilter.classify(
                    messageText=ensuredMessage.messageText,
                    chatId=chatId,
                    threshold=warnTreshold,  # Use existing threshold
                    ignoreTrigrams=True,
                )
                bayesResultWTrigrams = await self.bayesFilter.classify(
                    messageText=ensuredMessage.messageText,
                    chatId=chatId,
                    threshold=warnTreshold,  # Use existing threshold
                    ignoreTrigrams=False,
                )
                logger.debug(f"SPAM Bayes: Check result: {bayesResult}")
                logger.debug(f"SPAM Bayes w3grams: Check result: {bayesResultWTrigrams}")

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

        if spamScore > banTreshold:
            logger.info(f"SPAM: spamScore: {spamScore} > {banTreshold} {ensuredMessage.getBaseMessage()}")
            userName = sender.name or sender.username
            banMessage = await self.sendMessage(
                ensuredMessage,
                messageText=f"Пользователь [{userName}](tg://user?id={sender.id})"
                " заблокирован за спам.\n"
                f"(Вероятность: {spamScore}, порог: {banTreshold})\n"
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
            await self.markAsSpam(message=message, reason=SpamReason.AUTO, score=spamScore)
            return True
        elif spamScore >= warnTreshold:
            logger.info(f"Possible SPAM: spamScore: {spamScore} >= {warnTreshold} {ensuredMessage}")
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Возможно спам (Вероятность: {spamScore}, порог: {warnTreshold})\n"
                "(Когда-нибудь тут будут кнопки спам\\не спам)",
                messageCategory=MessageCategory.BOT_SPAM_NOTIFICATION,
            )
            # TODO: Add SPAM/Not-SPAM buttons
        else:
            logger.debug(f"Not SPAM: spamScore: {spamScore} < {warnTreshold} {ensuredMessage}")

        return False

    async def markAsSpam(self, message: Message, reason: SpamReason, score: Optional[float] = None):
        """Delete spam message, ban user and save message to spamDB"""
        ensuredMessage = EnsuredMessage.fromMessage(message)
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        bot = message.get_bot()

        logger.debug(
            f"Handling spam message: #{ensuredMessage.chat.id}:{ensuredMessage.messageId}"
            f" '{ensuredMessage.messageText}'"
            f" from {ensuredMessage.sender}. Reason: {reason}"
        )

        chatId = ensuredMessage.chat.id
        userId = ensuredMessage.sender.id

        if await self.isAdmin(user=ensuredMessage.user, chat=ensuredMessage.chat):
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
        if ensuredMessage.messageText and chatSettings[ChatSettingsKey.BAYES_AUTO_LEARN].toBool():
            try:
                await self.bayesFilter.learnSpam(messageText=ensuredMessage.messageText, chatId=chatId)
                logger.debug(f"Bayes filter learned spam message: {ensuredMessage.messageId}, dood!")
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

        await bot.delete_message(chat_id=chatId, message_id=ensuredMessage.messageId)
        logger.debug("Deleted spam message")
        if message.sender_chat is not None:
            await bot.ban_chat_sender_chat(chat_id=chatId, sender_chat_id=message.sender_chat.id)
        if message.from_user is not None:
            await bot.ban_chat_member(chat_id=chatId, user_id=userId, revoke_messages=True)
        else:
            logger.error(f"message.from_user is None (sender is {ensuredMessage.sender})")

        self.db.markUserIsSpammer(chatId=chatId, userId=userId, isSpammer=True)
        logger.debug(f"Banned user {ensuredMessage.sender} in chat {ensuredMessage.chat}")
        if chatSettings[ChatSettingsKey.SPAM_DELETE_ALL_USER_MESSAGES].toBool():
            userMessages = self.db.getChatMessagesByUser(
                chatId=chatId,
                userId=userId,
                limit=10,  # Do not delete more that 10 messages
            )
            logger.debug(f"Trying to delete more user messages: {userMessages}")
            messageIds: List[int] = []
            for msg in userMessages:
                if msg["message_id"] != ensuredMessage.messageId:
                    messageIds.append(msg["message_id"])

            try:
                if messageIds:
                    await bot.delete_messages(chat_id=chatId, message_ids=messageIds)
            except Exception as e:
                logger.error("Failed during deleteing spam message:")
                logger.exception(e)

    async def markAsHam(self, message: Message) -> bool:
        """Mark message as ham (not spam) for Bayes filter learning, dood!"""
        if not message.text:
            return False

        try:
            await self.bayesFilter.learnHam(messageText=message.text, chatId=message.chat_id)
            logger.debug(f"Bayes filter learned ham message: {message.message_id}, dood!")
            return True
        except Exception as e:
            logger.error(f"Failed to learn ham message in Bayes filter: {e}, dood!")
            return False

    async def getBayesFilterStats(self, chatId: Optional[int] = None) -> Dict[str, Any]:
        """Get Bayes filter statistics for debugging, dood!"""
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
        """Reset Bayes filter statistics, dood!"""
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
        """Train Bayes filter from existing spam messages and chat history, dood!"""
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
        Check Message in chat for SPAM if needed
        """

        chat = update.effective_chat
        if not chat:
            logger.error("Chat undefined")
            return HandlerResultStatus.ERROR
        chatType = chat.type

        match chatType:
            case Chat.PRIVATE:
                # No need to check spam in private messages
                return HandlerResultStatus.SKIPPED
            case Chat.GROUP | Chat.SUPERGROUP:
                if ensuredMessage is None:
                    logger.error("ensuredMessage undefined")
                    return HandlerResultStatus.ERROR
                try:
                    chatSettings = self.getChatSettings(ensuredMessage.chat.id)

                    if chatSettings[ChatSettingsKey.DETECT_SPAM].toBool():
                        if await self.checkSpam(ensuredMessage):
                            # It's spam, no further processing needed
                            return HandlerResultStatus.FATAL

                    return HandlerResultStatus.NEXT
                except Exception as e:
                    logger.error(f"Error while checking spam: {e}")
                    return HandlerResultStatus.ERROR

            case _:
                logger.warning(f"Unsupported chat type: {chatType}")
                return HandlerResultStatus.SKIPPED

    @commandHandler(
        commands=("test_spam",),
        shortDescription="<Test suite> [<args>] - Run some spam-related tests",
        helpMessage=" `<test_name>` `[<test_args>]`: Запустить тест (используется для тестирования).",
        categories={CommandCategory.BOT_OWNER, CommandCategory.HIDDEN},
        order=CommandHandlerOrder.TEST,
    )
    async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /test_spam <suite> [<args>] command."""
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
            return

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        if not context.args or len(context.args) < 1:
            await self.sendMessage(
                ensuredMessage,
                messageText="You need to specify test suite.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        suite = context.args[0]

        match suite:
            case "bayesStats":
                for chatId in self.cache.chats.keys():
                    stats = await self.getBayesFilterStats(chatId=chatId)
                    chatName = f"#{chatId}"
                    chatInfo = self.cache.getChatInfo(chatId)
                    if chatInfo is not None:
                        chatName = chatInfo["title"] or chatInfo["username"] or chatInfo["chat_id"]
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=f"Chat: **{chatName}**\n```json\n{utils.jsonDumps(stats, indent=2)}\n```\n",
                        messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    )
                    await asyncio.sleep(0.5)
            case _:
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"Unknown test suite: {suite}.",
                    messageCategory=MessageCategory.BOT_ERROR,
                )

    @commandHandler(
        commands=("spam",),
        shortDescription="Mark answered message as spam",
        helpMessage=": Указать боту на сообщение со спамом (должно быть ответом на спам-сообщение).",
        categories={CommandCategory.ADMIN},
        order=CommandHandlerOrder.SPAM,
    )
    async def spam_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /spam command."""

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

        # chatId = ensuredMessage.chat.id
        # userId = ensuredMessage.user.id

        # context.bot.delete_message()
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        allowUserSpamCommand = chatSettings[ChatSettingsKey.ALLOW_USER_SPAM_COMMAND].toBool()
        isAdmin = await self.isAdmin(user=ensuredMessage.user, chat=ensuredMessage.chat)

        logger.debug(
            "Got /spam command \n"
            f"from User({ensuredMessage.user}) "
            f"in Chat({ensuredMessage.chat}) \n"
            f"to Message({message.reply_to_message}) \n"
            f"isAdmin: {isAdmin}, allowUserSpamCommand: {allowUserSpamCommand}"
        )

        if message.reply_to_message is not None and (allowUserSpamCommand or isAdmin):
            replyMessage = message.reply_to_message
            await self.markAsSpam(
                replyMessage,
                reason=SpamReason.ADMIN if isAdmin else SpamReason.USER,
                score=100 if isAdmin else 50,  # TODO: Think about score for user
            )

        # Delete command message to reduce flood
        await message.delete()

    @commandHandler(
        commands=("pretrain_bayes",),
        shortDescription="[<chatId>] - initially train bayes filter with up to 1000 last messages",
        helpMessage=" `[<chatId>]`: Предобучить Баесовский антиспам фильтр на последних 1000 сообщениях.",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.SPAM,
    )
    async def pretrain_bayes_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /pretrain_bayes [<chatId>] command."""
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
        # userId = ensuredMessage.user.id

        if context.args:
            try:
                chatId = int(context.args[0])
            except ValueError:
                logger.error(f"Invalid chatId: {context.args[0]}")

        targetChat = Chat(id=chatId, type=Chat.PRIVATE if chatId > 0 else Chat.SUPERGROUP)
        targetChat.set_bot(message.get_bot())

        if not await self.isAdmin(user=ensuredMessage.user, chat=targetChat):
            await self.sendMessage(
                ensuredMessage,
                messageText="У Вас нет прав для выполнения данной команды.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        await self.trainBayesFromHistory(chatId=chatId)
        stats = await self.getBayesFilterStats(chatId=chatId)

        await self.sendMessage(
            ensuredMessage,
            messageText=f"Готово:\n```json\n{utils.jsonDumps(stats, indent=2)}\n```\n",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandler(
        commands=("learn_spam", "learn_ham"),
        shortDescription="[<chatId>] - learn answered message (or quote) as spam/ham for given chat",
        helpMessage=" `[<chatId>]`: Обучить баесовский фильтр на указанным сообщении (или цитате) как спам/не-спам.",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.SPAM,
    )
    async def learn_spam_ham_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /learn_<spam|ham> [<chatId>] command."""
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
        isLearnSpam = commandStr.lower().startswith("/learn_spam")

        repliedText = ensuredMessage.replyText or ensuredMessage.quoteText
        if not repliedText or len(repliedText) < 3:
            await self.sendMessage(
                ensuredMessage,
                "Команда должна быть ответом на сообщение достаточной длинны",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        chatId = ensuredMessage.chat.id
        # If it's quote from another chat, use it as chatId
        if message.external_reply and message.external_reply.chat:
            chatId = message.external_reply.chat.id
        if context.args:
            try:
                chatId = int(context.args[0])
            except Exception as e:
                logger.error(f"Failed to parse chatId ({context.args[0]}): {e}")

        chatObj = Chat(id=chatId, type=Chat.PRIVATE)
        chatObj.set_bot(context.bot)
        isAdmin = await self.isAdmin(ensuredMessage.user, chatObj, allowBotOwners=True)

        if not isAdmin:
            await self.sendMessage(
                ensuredMessage,
                "Вы не являетесь администратором в указанном чате",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        if isLearnSpam:
            await self.bayesFilter.learnSpam(messageText=repliedText, chatId=chatId)
            self.db.addSpamMessage(
                chatId=chatId,
                userId=0,
                messageId=0,
                messageText=repliedText,
                spamReason=SpamReason.ADMIN,
                score=100,
            )
            await self.sendMessage(
                ensuredMessage,
                f"Сообщение \n```\n{repliedText}\n```\n Запомнено как СПАМ для чата #`{chatId}`",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )
        else:
            await self.bayesFilter.learnHam(messageText=repliedText, chatId=chatId)
            self.db.addHamMessage(
                chatId=chatId,
                userId=0,
                messageId=0,
                messageText=repliedText,
                spamReason=SpamReason.ADMIN,
                score=100,
            )
            await self.sendMessage(
                ensuredMessage,
                f"Сообщение \n```\n{repliedText}\n```\n Запомнено как НЕ СПАМ для чата #`{chatId}`",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )

    @commandHandler(
        commands=("get_spam_score",),
        shortDescription="[<chatId>] - Analyze answered (or qoted) message for spam and print result",
        helpMessage=" `[<chatId>]`: Выдать результат проверки указанного сообщения (или цитаты) на спам.",
        categories={CommandCategory.PRIVATE},
        order=CommandHandlerOrder.SPAM,
    )
    async def get_spam_score_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /get_spam_score [<chatId>] command."""
        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        logger.debug(f"Message for SPAM Check: {utils.dumpMessage(message)}")

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Failed to ensure message: {type(e).__name__}#{e}")
            return

        self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        chatType = ensuredMessage.chat.type
        if chatType != Chat.PRIVATE:
            logger.error(f"Unsupported chat type for /get_spam_score command: {chatType}")
            return

        repliedText = ensuredMessage.replyText or ensuredMessage.quoteText
        if not repliedText or len(repliedText) < 3:
            await self.sendMessage(
                ensuredMessage,
                "Команда должна быть ответом на сообщение достаточной длинны",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        chatId = ensuredMessage.chat.id
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

    @commandHandler(
        commands=("unban",),
        shortDescription="[<username>] - Unban user from current chat",
        helpMessage="[@<username>]: Разбанить пользователя в данном чате. "
        "Так же может быть ответом на сообщение забаненного пользователя.",
        categories={CommandCategory.ADMIN},
        order=CommandHandlerOrder.SPAM,
    )
    async def unban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /unban [<@username>] command."""
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

        user: Optional[ChatUserDict] = None
        if context.args:
            username = context.args[0]
            if not username.startswith("@"):
                username = "@" + username
            user = self.db.getChatUserByUsername(ensuredMessage.chat.id, username)

        if user is None and message.reply_to_message and message.reply_to_message.from_user:
            user = self.db.getChatUser(chatId=ensuredMessage.chat.id, userId=message.reply_to_message.from_user.id)

        if user is None:
            await self.sendMessage(
                ensuredMessage,
                "Пользователь не найден",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        isAdmin = await self.isAdmin(ensuredMessage.user, ensuredMessage.chat, allowBotOwners=True)

        if not isAdmin:
            await self.sendMessage(
                ensuredMessage,
                "Вы не являетесь администратором в этом чате",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        bot = message.get_bot()
        # Unban user from chat
        await bot.unban_chat_member(chat_id=user["chat_id"], user_id=user["user_id"], only_if_banned=True)
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
