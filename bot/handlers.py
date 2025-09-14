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

from ai.abstract import AbstractModel
from ai.manager import LLMManager
from database.wrapper import DatabaseWrapper
from .ensured_message import EnsuredMessage

logger = logging.getLogger(__name__)

DEFAULT_PRIVATE_SYSTEM_PROMPT = "Ты - Принни: вайбовый, но умный пингвин из Disgaea, мужчина. При ответе ты можешь использовать Markdown форматирование."
DEFAULT_SUMMARISATION_SYSTEM_PROMPT = """Суммаризируй пользовательские сообщения, предоставленные в JSON формате. Указывай время начала и конца обсуждения и пользователей, кто обсуждал."""
DEFAULT_CHAT_SYSTEM_PROMPT = """Ты - Принни: вайбовый, но умный пингвин из Disgaea мужского пола. При ответе ты можешь использовать Markdown форматирование."""

class BotHandlers:
    """Contains all bot command and message handlers."""

    def __init__(self, config: Dict[str, Any], database: DatabaseWrapper, llm_manager: LLMManager):
        """Initialize handlers with database and LLM model."""
        self.config = config
        self.db = database
        self.llm_manager = llm_manager
        self.llm_model = llm_manager.getModel("yandexgpt-lite")

        modelDefaults = self.config.get("models", {})
        self.defaultModels = {
            "private": modelDefaults.get("private", "yandexgpt-lite"),
            "summary": modelDefaults.get("private", "yandexgpt-lite"),
            "chat": modelDefaults.get("private", "yandexgpt-lite"),
        }

    def getSummarySystemPrompt(self, chatId: Optional[int] = None) -> str:
        """Get the system prompt for summarising messages."""
        if not chatId:
            return DEFAULT_SUMMARISATION_SYSTEM_PROMPT
        # TODO: Try to get it from the database
        return DEFAULT_SUMMARISATION_SYSTEM_PROMPT

    def getChatSystemPrompt(self, chatId: Optional[int] = None) -> str:
        """Get the system prompt for chatting."""
        if not chatId:
            return DEFAULT_CHAT_SYSTEM_PROMPT
        # TODO: Try to get it from the database
        return DEFAULT_CHAT_SYSTEM_PROMPT

    def getPrivateSystemPrompt(self, chatId: Optional[int] = None) -> str:
        """Get the system prompt for private messages."""
        if not chatId:
            return DEFAULT_PRIVATE_SYSTEM_PROMPT
        # TODO: Try to get it from the database
        return DEFAULT_PRIVATE_SYSTEM_PROMPT

    def getSummaryModel(self, chatId: Optional[int] = None) -> AbstractModel:
        """Get the model for summarising messages."""

        modelName = self.defaultModels["summary"]
        if chatId:
           # TODO: Try to get it from the database
           pass

        ret = self.llm_manager.getModel(modelName)
        if ret is None:
            logger.error(f"Model {modelName} not found")
            raise ValueError(f"Model {modelName} not found")
        return ret

    def getChatModel(self, chatId: Optional[int] = None) -> AbstractModel:
        """Get the model for chatting."""
        modelName = self.defaultModels["chat"]
        if chatId:
           # TODO: Try to get it from the database
           pass

        ret = self.llm_manager.getModel(modelName)
        if ret is None:
            logger.error(f"Model {modelName} not found")
            raise ValueError(f"Model {modelName} not found")
        return ret

    def getPrivateModel(self, chatId: Optional[int] = None) -> AbstractModel:
        """Get the model for private messages."""
        modelName = self.defaultModels["private"]
        if chatId:
           # TODO: Try to get it from the database
           pass

        ret = self.llm_manager.getModel(modelName)
        if ret is None:
            logger.error(f"Model {modelName} not found")
            raise ValueError(f"Model {modelName} not found")
        return ret

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command."""
        user = update.effective_user
        if not user or not update.message:
            logger.error("User or message undefined")
            return

        # Save user to database
        self.db.saveUser(
            userId=user.id,
            userName=user.username,
            firstName=user.first_name,
            lastName=user.last_name
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
        messages = self.db.getUserMessages(user.id, limit=100)

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

        maxBatches: Optional[int] = None
        if context.args:
            try:
                maxBatches = int(context.args[0])
            except ValueError:
                logger.error(f"Invalid argument: '{context.args[0]}' is not a valid number.")

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage(message)
        except Exception as e:
            logger.error(f"Failed to ensure message: {type(e).__name__}#{e}")
            return

        chat = ensuredMessage.chat
        chatId = chat.id
        threadId = ensuredMessage.threadId
        chatType = chat.type

        if chatType not in [Chat.GROUP, Chat.SUPERGROUP]:
            localChatId = None
            if context.args and len(context.args) >= 2:
                try:
                    localChatId = int(context.args[1])
                except ValueError:
                    logger.error(f"Invalid argument: '{context.args[1]}' is not a valid number.")

            if localChatId is None:
                await message.reply_text(
                    "This command is only available in groups and supergroups for now.",
                    reply_to_message_id=message.message_id,
                )
                return
            else:
                chatId = localChatId
                threadId = None

        today = datetime.datetime.now(datetime.timezone.utc)
        today = today.replace(hour=0, minute=0, second=0, microsecond=0)

        messages = self.db.getChatMessageSince(
            chatId=chatId,
            sinceDateTime=datetime.datetime.combine(today, datetime.time.min),
            threadId=threadId,
        )

        logger.debug(f"Messages: {messages}")

        systemMessage = {
            "role": "system",
            "text": self.getSummarySystemPrompt(chatId=chatId),
        }
        parsedMessages = []

        for msg in messages:
            parsedMessages.append(
                {
                    "role": "user",
                    "text": json.dumps(
                        {
                            # date, chat_id, user_id, user_name, message_id, reply_id, thread_id, message_text, message_type
                            "date": msg["date"],
                            "sender": msg["user_name"],
                            "message_id": msg["message_id"],
                            "reply_id": msg["reply_id"],
                            "text": msg["message_text"],
                        },
                        ensure_ascii=False,
                    ),
                }
            )

        reqMessages = [systemMessage] + parsedMessages

        llmModel = self.getSummaryModel(chatId=chatId)
        # TODO: Move to config or ask from model somehow
        maxTokens = llmModel.getInfo()["context_size"]
        tokensCount = llmModel.getEstimateTokensCount(reqMessages)

        # -256 or *0.9 to ensure everything will be ok
        batchesCount = tokensCount // max(maxTokens - 256, maxTokens * 0.9) + 1
        batchLength = len(parsedMessages) // batchesCount

        logger.debug(f"Summarisation: estimated total tokens: {tokensCount}, max tokens: {maxTokens}, messages count: {len(parsedMessages)}, batches count: {batchesCount}, batch length: {batchLength}")

        resMessages = []
        startPos: int = 0
        batchN = 0
        while startPos < len(parsedMessages):
            currentBatchLen = int(min(batchLength, len(parsedMessages) - startPos))
            batchSummarized = False
            while not batchSummarized:
                tryMessages = parsedMessages[startPos:startPos+currentBatchLen]
                reqMessages = [systemMessage] + tryMessages
                tokensCount = llmModel.getEstimateTokensCount(reqMessages)
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
                    mlRet = llmModel.run(reqMessages)
                    logger.debug(f"LLM Response: {mlRet}")
                except Exception as e:
                    logger.error(f"Error while running LLM for batch {startPos}:{startPos+currentBatchLen}: {type(e).__name__}#{e}")
                    resMessages.append(f"Error while running LLM for batch {startPos}:{startPos+currentBatchLen}: {type(e).__name__}")
                    break

                resMessages.append(mlRet.alternatives[0].text)

            startPos += currentBatchLen
            batchN += 1
            if maxBatches and batchN >= maxBatches:
                break

        for msg in resMessages:
            replyKwargs = {
                "text": msg,
                "reply_to_message_id": ensuredMessage.messageId,
                "message_thread_id": ensuredMessage.threadId,
            }
            replyMessage: Optional[Message] = None
            try:
                replyMessage = await message.reply_text(
                    parse_mode="Markdown",
                    **replyKwargs,
                )
            except Exception as e:
                logger.error(f"Error while replying to message: {type(e).__name__}#{e}")
                replyMessage = await message.reply_text(**replyKwargs)

            if replyMessage:
                try:
                    ensuredReplyMessage = EnsuredMessage(replyMessage)
                    self._saveChatMessage(ensuredReplyMessage, messageCategory='bot')
                except Exception as e:
                    logger.error(f"Error while saving chat message: {type(e).__name__}#{e}")

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

    def _saveChatMessage(self, message: EnsuredMessage, messageCategory: str = 'user') -> bool:
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

    async def _sendLLMChatMessage(self, ensuredMessage: EnsuredMessage, messagesHistory: List[Dict[str, str]]) -> bool:
        """Send a chat message to the LLM model."""
        logger.debug(f"LLM Request messages: {messagesHistory}")
        llmModel = self.getChatModel(ensuredMessage.chat.id)
        mlRet: Any = None
        try:
            mlRet = llmModel.run(messagesHistory)
            logger.debug(f"LLM Response: {mlRet}")
        except Exception as e:
            logger.error(f"Error while sending LLM request: {type(e).__name__}#{e}")
            await ensuredMessage.getBaseMessage().reply_text(
                f"Error while sending LLM request: {type(e).__name__}",
                reply_to_message_id=ensuredMessage.messageId,
                message_thread_id=ensuredMessage.threadId,
            )
            return False
        LLMReply = mlRet.alternatives[0].text

        replyMessage = None
        replyKwargs = {
            "text": LLMReply,
            "reply_to_message_id": ensuredMessage.messageId,
            "message_thread_id": ensuredMessage.threadId,
        }
        try:
            logger.warning(f"Sending LLM reply to {ensuredMessage}")
            replyMessage = await ensuredMessage.getBaseMessage().reply_text(parse_mode='Markdown',**replyKwargs)
        except Exception as e:
            logger.error(f"Error while replying to message: {type(e).__name__}#{e}")
            # Probably error in markdown formatting, fallback to raw text
            replyMessage = await ensuredMessage.getBaseMessage().reply_text(**replyKwargs)
        if replyMessage is None:
            logger.error("Error while sending LLM reply")
            return False

        try:
            ensuredReplyMessage = EnsuredMessage(replyMessage)
            self._saveChatMessage(ensuredReplyMessage, messageCategory='bot')
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

        if not self._saveChatMessage(ensuredMessage, messageCategory='user'):
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
                        "text": self.getChatSystemPrompt(chat.id),
                    },
                ]
                for storedMsg in storedMessages:
                    req_messages.append(
                        {
                            "role": "user" if storedMsg["message_category"] == "user" else "assistant",
                            "text": storedMsg["message_text"],
                        }
                    )

                if not await self._sendLLMChatMessage(ensuredMessage, req_messages):
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
                "text": self.getChatSystemPrompt(chat.id),
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

        if not await self._sendLLMChatMessage(ensuredMessage, req_messages):
            logger.error("Failed to send LLM reply")

        logger.info(f"Handled message from {user.id}: {messageText[:50]}...")

    async def handle_private_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

        # Save user and message to database
        self.db.saveUser(
            userId=user.id,
            userName=user.username,
            firstName=user.first_name,
            lastName=user.last_name
        )

        messages = self.db.getUserMessages(user.id, limit=10)
        reqMessages = [
            {
                "role": "system",
                "text": self.getPrivateSystemPrompt(chatId=user.id),
            },
        ]

        for msg in reversed(messages):
            reqMessages.append({
                "role": "user",
                "text": msg["message_text"],
            })
            if message["reply_text"]:
                reqMessages.append({
                    "role": "assistant",
                    "text": msg["reply_text"],
                })
        reqMessages.append({
            "role": "user",
            "text": ensuredMessage.messageText,
        })

        logger.debug(f"LLM Request messages: {reqMessages}")
        reply = ""
        llmModel = self.getPrivateModel(chatId=user.id)
        try:
            mlRet = llmModel.run(reqMessages)
            logger.debug(f"LLM Response: {mlRet}")
            reply = mlRet.alternatives[0].text
        except Exception as e:
            logger.error(f"Error while running LLM: {type(e).__name__}#{e}")
            reply = f"Error while running LLM: {type(e).__name__}#{e}"

        self.db.savePrivateMessage(user.id, ensuredMessage.messageText, reply_text=reply)

        replyKwargs = {
            "text": reply,
            "reply_to_message_id": ensuredMessage.messageId,
        }
        try:
            await message.reply_text(parse_mode='Markdown', **replyKwargs)
        except Exception as e:
            logger.error(f"Error while replying to message: {type(e).__name__}#{e}")
            # Probably error in markdown formatting, fallback to raw text
            await message.reply_text(**replyKwargs)
        logger.info(f"Handled message from {user.id}: {ensuredMessage.messageText[:50]}...")

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors."""
        logger.error(f"Exception while handling an update: {context.error}")
