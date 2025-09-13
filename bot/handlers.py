"""
Telegram bot command handlers for Gromozeka.
"""
import datetime
import json
import logging

from typing import Any, Dict, List, Optional

from telegram import Chat, Update, Message
from telegram.constants import MessageEntityType
from telegram.ext import ContextTypes

from database.wrapper import DatabaseWrapper

logger = logging.getLogger(__name__)


class EnsuredMessage:
    
    def __init__(self, message: Message):
        self._message = message

        if not message.from_user:
            raise ValueError("Message User undefined")

        self.user = message.from_user

        if not message.chat:
            raise ValueError("Message Chat undefined")
        self.chat = message.chat

        self.messageId = message.message_id
        self.date = message.date
        self.messageText = ""
        self.messageType = "text"
        if not message.text:
            # Probably not a text message, ignore but log it for now
            logger.error(f"Message text undefined: {message}")
            self.messageType = "unknown"
        else:
            self.messageText = message.text

        self.replyId: Optional[int] = None
        self.replyText: Optional[str] = None
        self.isReply = False
        if message.reply_to_message:
            # If reply_to_message is message about creating topic, then it isn't reply
            if message.reply_to_message.forum_topic_created is None:
                self.replyId = message.reply_to_message.message_id
                self.isReply = True
                if message.reply_to_message.text:
                    self.replyText = message.reply_to_message.text

        self.threadId: Optional[int] = None
        self.isTopicMessage = message.is_topic_message == True if message.is_topic_message is not None else False
        if self.isTopicMessage:
            self.threadId = message.message_thread_id

        logger.debug(f"Ensured Message: {self}")

    def getBaseMessage(self) -> Message:
        return self._message
    
    def __str__(self) -> str:
        return json.dumps({
            "user.id": self.user.id,
            "chat.id": self.chat.id,
            "messageId": self.messageId,
            "date": self.date.isoformat(),
            "messageType": self.messageType,
            "messageText": self.messageText,
            "replyId": self.replyId,
            "isReply": self.isReply,
            "threadId": self.threadId,
            "isTopicMessage": self.isTopicMessage,
        })


class BotHandlers:
    """Contains all bot command and message handlers."""

    def __init__(self, database: DatabaseWrapper, llm_model):
        """Initialize handlers with database and LLM model."""
        self.db = database
        self.llm_model = llm_model

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command."""
        user = update.effective_user
        if not user or not update.message:
            logger.error("User or message undefined")
            return

        # Save user to database
        self.db.save_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )

        welcome_message = (
            f"Hello {user.first_name}! 👋\n\n"
            "I'm Gromozeka, your friendly Telegram bot, dood!\n\n"
            "Available commands:\n"
            "/start - Show this welcome message\n"
            "/help - Get help information\n"
            "/stats - Show your statistics\n"
            "/echo <message> - Echo your message back\n\n"
            "Just send me any message and I'll respond, dood!"
        )

        await update.message.reply_text(welcome_message)
        logger.info(f"User {user.id} ({user.username}) started the bot")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /help command."""
        if not update.message:
            logger.error("Message undefined")
            return

        help_text = (
            "🤖 *Gromozeka Bot Help*\n\n"
            "*Commands:*\n"
            "/start - Welcome message and bot introduction\n"
            "/help - Show this help message\n"
            "/stats - Display your usage statistics\n"
            "/echo <message> - Echo your message back\n\n"
            "*Features:*\n"
            "• Message logging and statistics\n"
            "• User data persistence\n"
            "• Simple conversation handling\n\n"
            "Just send me any text message and I'll respond, dood!"
        )

        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /stats command."""
        user = update.effective_user
        if not user or not update.message:
            logger.error("User or message undefined")
            return

        # Get user data from database
        user_data = self.db.get_user(user.id)
        messages = self.db.get_user_messages(user.id, limit=100)

        if user_data:
            stats_text = (
                f"📊 *Your Statistics*\n\n"
                f"👤 *User:* {user_data['first_name']}\n"
                f"🆔 *ID:* {user_data['user_id']}\n"
                f"📅 *Joined:* {user_data['created_at'][:10]}\n"
                f"💬 *Messages sent:* {len(messages)}\n"
            )
        else:
            stats_text = "No statistics available. Send me a message first!"

        await update.message.reply_text(stats_text, parse_mode='Markdown')

    async def echo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /echo command."""
        if not update.message:
            logger.error("Message undefined")
            return

        if context.args:
            echo_text = " ".join(context.args)
            await update.message.reply_text(f"🔄 Echo: {echo_text}")
        else:
            await update.message.reply_text("Please provide a message to echo!\nUsage: /echo <your message>")

    async def summary_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /summary command."""
        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage(message)
        except Exception as e:
            logger.error(f"Failed to ensure message: {type(e).__name__}#{e}")
            return

        chat = ensuredMessage.chat
        chatType = chat.type

        if chatType not in [Chat.GROUP, Chat.SUPERGROUP]:
            await message.reply_text(
                "This command is only available in groups and supergroups for now.",
                reply_to_message_id=message.message_id,
            )
            return

        today = datetime.datetime.now(datetime.timezone.utc)
        today = today.replace(hour=0, minute=0, second=0, microsecond=0)

        messages = self.db.get_chat_messages_since(
            chatId=chat.id,
            sinceDateTime=datetime.datetime.combine(today, datetime.time.min),
            threadId=ensuredMessage.threadId,
        )

        logger.debug(f"Messages: {messages}")

        systemMessage = {
            "role": "system",
            "text": "Ты - Prinny - вайбовый, но умный пингвин из Disgaea. При ответе ты можешь использовать Markdown форматирование.",
        }
        userMessageText = "Твоя задача - суммаризировать сообщения за день. Далее идёт список сообщений в JSON формате:"

        parsedMessages = []

        for msg in messages:
            parsedMessages.append({
                # date, chat_id, user_id, user_name, message_id, reply_id, thread_id, message_text, message_type
                "date": msg["date"],
                "sender": msg["user_name"],
                "message_id": msg["message_id"],
                "reply_id": msg["reply_id"],
                "text": msg["message_text"]
            })

        reqMessages = [
            systemMessage,
            {
                "role": "user",
                "text": f"{userMessageText} {json.dumps(parsedMessages)}",
            },
        ]

        # TODO: Move to config or ask from model somehow
        maxTokens = 32768
        tokens = self.llm_model.tokenize(reqMessages)
        tokensCount = len(tokens)

        # -256 to ensure everything will be ok
        batchesCount = tokensCount // (maxTokens - 256) + 1
        batchLength = len(parsedMessages) // batchesCount

        resMessages = []
        startPos: int = 0
        while startPos < len(parsedMessages):
            currentBatchLen = int(min(batchLength, len(parsedMessages) - startPos))
            batchSummarized = False
            while not batchSummarized:
                tryMessages = parsedMessages[startPos:startPos+currentBatchLen]
                reqMessages = [
                    systemMessage,
                    {
                        "role": "user",
                        "text": f"{userMessageText} {json.dumps(tryMessages)}",
                    },
                ]
                tokens = self.llm_model.tokenize(reqMessages)
                tokensCount = len(tokens)
                if tokensCount > maxTokens:
                    if currentBatchLen == 1:
                        resMessages.append(f"Error while running LLM for batch {startPos}:{startPos+currentBatchLen}: Bats has too many tokens ({tokensCount})")
                        break
                    currentBatchLen = int(currentBatchLen // (tokensCount / maxTokens))
                    currentBatchLen -= 2
                    if currentBatchLen < 1:
                        currentBatchLen = 1
                    continue
                batchSummarized = True

                mlRet: Any = None
                try:
                    logger.debug(f"LLM Request messages: {reqMessages}")
                    mlRet = self.llm_model.run(reqMessages)
                    logger.debug(f"LLM Response: {mlRet}")
                except Exception as e:
                    logger.error(f"Error while running LLM for batch {startPos}:{startPos+currentBatchLen}: {type(e).__name__}#{e}")
                    resMessages.append(f"Error while running LLM for batch {startPos}:{startPos+currentBatchLen}: {type(e).__name__}")
                    break

                resMessages.append(mlRet.alternatives[0].text)

            startPos += currentBatchLen

        for msg in resMessages:
            try:
                await message.reply_text(
                    msg,
                    parse_mode="Markdown",
                    reply_to_message_id=message.message_id,
                    message_thread_id=ensuredMessage.threadId,
                )
            except Exception as e:
                logger.error(f"Error while replying to message: {type(e).__name__}#{e}")
                await message.reply_text(
                    msg,
                    reply_to_message_id=message.message_id,
                    message_thread_id=ensuredMessage.threadId,
                )

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
                return await self.handle_private_message(update, context)
            case Chat.GROUP:
                return await self.handle_group_message(update, context)
            case Chat.SUPERGROUP:
                return await self.handle_group_message(update, context)
            case Chat.CHANNEL:
                logger.error(f"Unsupported chat type: {chatType}")
            case _:
                logger.error(f"Unsupported chat type: {chatType}")

    def _save_chat_message(self, message: EnsuredMessage, messageCategory: str = 'user') -> bool:
        """Save a chat message to the database."""
        # TODO: messageCategory - make enum

        user = message.user
        chat = message.chat

        if message.messageType != 'text':
            logger.error(f"Unsupported message type: {message.messageType}")
            return False

        messageText = message.messageText

        replyId = message.replyId
        rootMessageId = message.messageId
        if message.isReply and replyId:
            parentMsg = self.db.get_chat_message_by_message_id(
                chat_id=chat.id,
                message_id=replyId,
                thread_id=message.threadId,
            )
            if parentMsg:
                rootMessageId = parentMsg["root_message_id"]

        self.db.save_chat_message(
            date=message.date,
            chatId=chat.id,
            userId=user.id,
            userName=user.username or user.first_name,
            messageId=message.messageId,
            replyId=replyId,
            threadId=message.threadId,
            messageText=messageText,
            messageType='text', # In future we'll support not only text messages, but photos, stickers and something else. Or not
            messageCategory=messageCategory,
            rootMessageId=rootMessageId,
        )

        return True

    async def _send_llm_chat_message(self, ensuredMessage: EnsuredMessage, messagesHistory: List[Dict[str, str]], llmModel) -> bool:
        """Send a chat message to the LLM model."""
        logger.debug(f"LLM Request messages: {messagesHistory}")
        ml_ret: Any = None
        try:
            ml_ret = llmModel.run(messagesHistory)
            logger.debug(f"LLM Response: {ml_ret}")
        except Exception as e:
            logger.error(f"Error while sending LLM request: {type(e).__name__}#{e}")
            await ensuredMessage.getBaseMessage().reply_text(
                f"Error while sending LLM request: {type(e).__name__}",
                reply_to_message_id=ensuredMessage.messageId,
                message_thread_id=ensuredMessage.threadId,
            )
            return False
        LLMReply = ml_ret.alternatives[0].text

        replyMessage = None
        try:
            logger.warning(f"Sending LLM reply to {ensuredMessage}")
            replyMessage = await ensuredMessage.getBaseMessage().reply_markdown(
                LLMReply,
                reply_to_message_id=ensuredMessage.messageId,
                message_thread_id=ensuredMessage.threadId,
            )
        except Exception as e:
            logger.error(f"Error while replying to message: {type(e).__name__}#{e}")
            # Probably error in markdown formatting, fallback to raw text
            replyMessage = await ensuredMessage.getBaseMessage().reply_text(
                LLMReply,
                reply_to_message_id=ensuredMessage.messageId,
                message_thread_id=ensuredMessage.threadId,
            )
        if replyMessage is None:
            logger.error("Error while sending LLM reply")
            return False

        try:
            ensuredReplyMessage = EnsuredMessage(replyMessage)
            self._save_chat_message(ensuredReplyMessage, messageCategory='bot')
            return True
        except Exception as e:
            logger.error(f"Error while saving chat message: {type(e).__name__}#{e}")
            return False

    async def handle_group_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.debug(f"Handling group message: {update}")
        message = update.message
        if not message:
            # Not new message, ignore
            # logger.error("Message undefined")
            return

        ensuredMessage : Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        user = ensuredMessage.user
        chat = ensuredMessage.chat

        if ensuredMessage.messageType != 'text':
            logger.error(f"Unsupported message type: {ensuredMessage.messageType}")
            return

        messageText = ensuredMessage.messageText

        if not self._save_chat_message(ensuredMessage, messageCategory='user'):
            logger.error("Failed to save chat message")

        # Check if message is a reply to our message
        if ensuredMessage.isReply and ensuredMessage.replyId is not None:
            parentId = ensuredMessage.replyId

            storedMsg = self.db.get_chat_message_by_message_id(
                chat_id=chat.id,
                message_id=parentId,
                thread_id=ensuredMessage.threadId,
            )
            if storedMsg is None:
                logger.error("Failed to get parent message")
                return
            if storedMsg["message_category"] == "bot":
                storedMessages = self.db.get_chat_messages_by_root_id(
                    chatId=chat.id, 
                    rootMessageId=storedMsg["root_message_id"],
                    threadId=ensuredMessage.threadId,
                )

                req_messages = [
                    {
                        "role": "system",
                        # TODO: Allow chat admin to configure system prompt. Also move default system prompt to config
                        "text": "Ты - Prinny - вайбовый, но умный пингвин из Disgaea. При ответе ты можешь использовать Markdown форматирование",
                    },
                ]
                for storedMsg in storedMessages:
                    req_messages.append(
                        {
                            "role": "user" if storedMsg["message_category"] == "user" else "assistant",
                            "text": storedMsg["message_text"],
                        }
                    )

                if not await self._send_llm_chat_message(
                    ensuredMessage, req_messages, self.llm_model
                ):
                    logger.error("Failed to send LLM reply")

                logger.info(f"Handled message from {user.id}: {messageText[:50]}...")
                # TODO: Move to separate method
                return

        # TODO: Move this to separate function + handle whole thread if any
        # If our bot has mentioned, answer somehow
        # logger.debug(f"Bot is: {context.bot.bot} {context.bot.username}")
        myUsername = context.bot.username
        mentionedMe = False

        for entity in message.entities:
            if entity.type == MessageEntityType.MENTION:
                mention_text = messageText[entity.offset:entity.offset + entity.length]

                # Проверяем, совпадает ли упоминание с именем бота
                if mention_text == f"@{myUsername}":
                    mentionedMe = True
                    break

        if not mentionedMe:
            return

        req_messages = [
            {
                "role": "system",
                # TODO: Allow chat admin to configure system prompt. Also move default system prompt to config
                "text": "Ты - Prinny - вайбовый, но умный пингвин из Disgaea. При ответе ты можешь использовать Markdown форматирование",
            }
        ]

        if ensuredMessage.replyText:
            req_messages.append(
                {
                    "role": "user",
                    "text": ensuredMessage.replyText,
                }
            )
        req_messages.append(
            {
                "role": "user",
                "text": messageText,
            }
        )

        if not await self._send_llm_chat_message(ensuredMessage, req_messages, self.llm_model):
            logger.error("Failed to send LLM reply")

        logger.info(f"Handled message from {user.id}: {messageText[:50]}...")

    async def handle_private_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        if not message:
            # Not new message, ignore
            # logger.error("Message undefined")
            return

        user = update.effective_user
        if not user:
            logger.error("User undefined")
            return

        message_text = message.text
        if not message_text:
            # Probasbly not a text message, ignore but log it for now
            logger.error(f"Message text undefined: {message}")
            return

        # Save user and message to database
        self.db.save_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )

        messages = self.db.get_user_messages(user.id, limit=10)
        req_messages = [
            {
                "role": "system",
                #TODO: Allow user to configure system prompt. Also move default system prompt to config
                "text": "Ты - Prinny - вайбовый, но умный пингвин из Disgaea. При ответе ты можешь использовать Markdown форматирование",
            },
        ]

        for msg in reversed(messages):
            req_messages.append({
                "role": "user",
                "text": msg["message_text"],
            })
            if message["reply_text"]:
                req_messages.append({
                    "role": "assistant",
                    "text": msg["reply_text"],
                })
        req_messages.append({
            "role": "user",
            "text": message_text,
        })

        logger.debug(f"LLM Request messages: {req_messages}")
        ml_ret = self.llm_model.run(req_messages)
        logger.debug(f"LLM Response: {ml_ret}")
        reply = ml_ret.alternatives[0].text
        self.db.save_message(user.id, message_text, reply_text=reply)

        try:
            await message.reply_markdown(reply, reply_to_message_id=message.message_id)
            logger.info(f"Replied to message from {user.id}: {message_text[:50]}...")
        except Exception as e:
            logger.error(f"Error while replying to message: {type(e).__name__}#{e}")
            # Probably error in markdown formatting, fallback to raw text
            await message.reply_text(reply, reply_to_message_id=message.message_id)
        logger.info(f"Handled message from {user.id}: {message_text[:50]}...")

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors."""
        logger.error(f"Exception while handling an update: {context.error}")
