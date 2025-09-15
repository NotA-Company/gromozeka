"""
Telegram bot command handlers for Gromozeka.
"""
import datetime
from enum import StrEnum
import json
import logging

import time
from typing import Any, Dict, List, Optional

from telegram import Chat, Update, Message
from telegram.constants import MessageEntityType
from telegram.ext import ContextTypes

from ai.abstract import AbstractModel, ModelMessage, ModelRunResult
from ai.manager import LLMManager
from database.wrapper import DatabaseWrapper
from .ensured_message import EnsuredMessage

logger = logging.getLogger(__name__)

DEFAULT_SUMMARISATION_SYSTEM_PROMPT = "Суммаризируй пользовательские сообщения, предоставленные в JSON формате. Указывай время начала и конца обсуждения и пользователей, кто обсуждал."
DEFAULT_PRIVATE_SYSTEM_PROMPT = "Ты - Принни: вайбовый, но умный пингвин из Disgaea, мужчина. При ответе ты можешь использовать Markdown форматирование."
DEFAULT_CHAT_SYSTEM_PROMPT =  "Ты - Принни: вайбовый, но умный пингвин из Disgaea мужского пола. При ответе ты можешь использовать Markdown форматирование."
ROBOT_EMOJI = "🤖"
TELEGRAM_MAX_MESSAGE_LENGTH = 4096

class ChatSettingsEnum(StrEnum):
    """Enum for chat settings."""
    SUMMARY_MODEL = "summary_model"
    CHAT_MODEL = "chat_model"
    SUMMARY_SYSTEM_PROMPT = "summary_system_prompt"
    CHAT_SYSTEM_PROMPT = "chat_system_prompt"
    ALLOW_ADMIN_CHANGE_SETTINGS = "allow_admin_change_settings"
    CUSTOM_MENTIONS = "custom_mentions"

    def __str__(self):
        return str(self.value)

class BotHandlers:
    """Contains all bot command and message handlers."""

    def __init__(self, config: Dict[str, Any], database: DatabaseWrapper, llmManager: LLMManager):
        """Initialize handlers with database and LLM model."""
        self.config = config
        self.db = database
        self.llmManager = llmManager

        modelDefaults: Dict[str, str] = self.config.get("models", {})
        self.defaultModels: Dict[str, str] = {
            "private": modelDefaults.get("private", "yandexgpt-lite"),
            "summary": modelDefaults.get("summary", "yandexgpt-lite"),
            "chat": modelDefaults.get("chat", "yandexgpt-lite"),
            "fallback": modelDefaults.get("fallback", "yandexgpt-lite"),
            "summary-fallback": modelDefaults.get("summary-fallback", "yandexgpt-lite"),
        }
        promptsDefaults: Dict[str, str] = self.config.get("prompts", {})
        self.defaultPrompts: Dict[str, str] = {
            "private": promptsDefaults.get("private", DEFAULT_PRIVATE_SYSTEM_PROMPT),
            "summary": promptsDefaults.get("summary", DEFAULT_SUMMARISATION_SYSTEM_PROMPT),
            "chat": promptsDefaults.get("chat", DEFAULT_CHAT_SYSTEM_PROMPT),
        }
        self.botOwners = [username.lower() for username in self.config.get("bot_owners", [])]
        self.cache = {
            "chats": {},
        }
        self.defaultAdminCanChangeSettings = bool(self.config.get("allow_admin_change_channel_settings", False))
        self.defaultCustomMentions = [str(v).lower() for v in self.config.get("custom_mentions", [])]

    ###
    # Helpers for getting needed Models or Prompts
    ###
    def getSummarySystemPrompt(self, chatId: Optional[int] = None) -> str:
        """Get the system prompt for summarising messages."""
        if not chatId:
            return self.defaultPrompts["summary"]

        chatSettings = self.getChatSettings(chatId)
        return chatSettings.get(ChatSettingsEnum.SUMMARY_SYSTEM_PROMPT, self.defaultPrompts["summary"])

    def getChatSystemPrompt(self, chatId: Optional[int] = None) -> str:
        """Get the system prompt for chatting."""
        if not chatId:
            return self.defaultPrompts["chat"]
        chatSettings = self.getChatSettings(chatId)
        return chatSettings.get(ChatSettingsEnum.CHAT_SYSTEM_PROMPT, self.defaultPrompts["chat"])

    def getPrivateSystemPrompt(self, chatId: Optional[int] = None) -> str:
        """Get the system prompt for private messages."""
        if not chatId:
            return self.defaultPrompts["private"]
        # TODO: Try to get it from the database
        return self.defaultPrompts["private"]

    def getSummaryModel(self, chatId: Optional[int] = None) -> AbstractModel:
        """Get the model for summarising messages."""

        modelName = self.defaultModels["summary"]
        if chatId:
            chatSettings = self.getChatSettings(chatId)
            modelName = chatSettings.get(ChatSettingsEnum.SUMMARY_MODEL, modelName)

        ret = self.llmManager.getModel(modelName)
        if ret is None:
            logger.error(f"Model {modelName} not found")
            raise ValueError(f"Model {modelName} not found")
        return ret

    def getChatModel(self, chatId: Optional[int] = None) -> AbstractModel:
        """Get the model for chatting."""
        modelName = self.defaultModels["chat"]
        if chatId:
            chatSettings = self.getChatSettings(chatId)
            modelName = chatSettings.get(ChatSettingsEnum.CHAT_MODEL, modelName)

        ret = self.llmManager.getModel(modelName)
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

        ret = self.llmManager.getModel(modelName)
        if ret is None:
            logger.error(f"Model {modelName} not found")
            raise ValueError(f"Model {modelName} not found")
        return ret

    def getFallbackModel(self) -> AbstractModel:
        """Get the model for fallback messages."""
        modelName = self.defaultModels["fallback"]
        ret = self.llmManager.getModel(modelName)
        if ret is None:
            logger.error(f"Model {modelName} not found")
            raise ValueError(f"Model {modelName} not found")
        return ret

    def getFallbackSummaryModel(self) -> AbstractModel:
        """Get the model for fallback messages."""
        modelName = self.defaultModels["summary-fallback"]
        ret = self.llmManager.getModel(modelName)
        if ret is None:
            logger.error(f"Model {modelName} not found")
            raise ValueError(f"Model {modelName} not found")
        return ret

    ###
    # Chat settings Managenent
    ###

    def getChatSettings(self, chatId: int, returnDefault: bool = True) -> Dict[ChatSettingsEnum, str]:
        """Get the chat settings for the given chat."""
        defaultChatSettings = {
            ChatSettingsEnum.SUMMARY_MODEL: self.defaultModels["summary"],
            ChatSettingsEnum.CHAT_MODEL: self.defaultModels["chat"],
            ChatSettingsEnum.SUMMARY_SYSTEM_PROMPT: self.defaultPrompts["summary"],
            ChatSettingsEnum.CHAT_SYSTEM_PROMPT: self.defaultPrompts["chat"],
            ChatSettingsEnum.ALLOW_ADMIN_CHANGE_SETTINGS: str(self.defaultAdminCanChangeSettings),
            ChatSettingsEnum.CUSTOM_MENTIONS: ", ".join(self.defaultCustomMentions),
        }
        if chatId not in self.cache["chats"]:
            self.cache["chats"][chatId] = {}

        if 'settings' not in self.cache["chats"][chatId]:
            self.cache["chats"][chatId]['settings'] = self.db.getChatSettings(chatId)

        if returnDefault:
            return {**defaultChatSettings, **self.cache["chats"][chatId]['settings']}

        return self.cache["chats"][chatId]['settings']

    def setChatSettings(self, chatId: int, settings: Dict[str, Any]) -> None:
        """Set the chat settings for the given chat."""
        if chatId not in self.cache["chats"]:
            self.cache["chats"][chatId] = {}

        for key, value in settings.items():
            self.db.setChatSetting(chatId, key, value)

        if 'settings' in self.cache["chats"][chatId]:
            self.cache["chats"][chatId].pop('settings', None)

    def unsetChatSetting(self, chatId: int, key: str) -> None:
        """Set the chat settings for the given chat."""
        if chatId not in self.cache["chats"]:
            self.cache["chats"][chatId] = {}

        self.db.unsetChatSetting(chatId, key)

        if 'settings' in self.cache["chats"][chatId]:
            self.cache["chats"][chatId].pop('settings', None)

    ###
    # Different helpers
    ###

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
            parentMsg = self.db.getChatMessageByMessageId(
                chatId=chat.id,
                messageId=replyId,
                threadId=message.threadId,
            )
            if parentMsg:
                rootMessageId = parentMsg["root_message_id"]

        self.db.updateChatUser(chatId=chat.id, userId=user.id, username=user.username or user.first_name)
        self.db.saveChatMessage(
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
        mlRet: Optional[ModelRunResult] = None
        try:
            mlRet = llmModel.runWithFallBack(ModelMessage.fromDictList(messagesHistory), self.getFallbackModel())
            logger.debug(f"LLM Response: {mlRet}")
        except Exception as e:
            logger.error(f"Error while sending LLM request: {type(e).__name__}#{e}")
            await ensuredMessage.getBaseMessage().reply_text(
                f"Error while sending LLM request: {type(e).__name__}",
                reply_to_message_id=ensuredMessage.messageId,
                message_thread_id=ensuredMessage.threadId,
            )
            return False
        LLMReply = mlRet.resultText
        prefix = ""
        if mlRet.isFallback:
            prefix = f"{ROBOT_EMOJI} "

        replyMessage = None
        replyKwargs = {
            "text": prefix + LLMReply,
            "reply_to_message_id": ensuredMessage.messageId,
            "message_thread_id": ensuredMessage.threadId,
        }
        try:
            logger.debug(f"Sending LLM reply to {ensuredMessage}")
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
                return await self.handle_private_message(update, context)
            case Chat.GROUP:
                return await self.handle_group_message(update, context)
            case Chat.SUPERGROUP:
                return await self.handle_group_message(update, context)
            case Chat.CHANNEL:
                logger.error(f"Unsupported chat type: {chatType}")
            case _:
                logger.error(f"Unsupported chat type: {chatType}")

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
            mlRet = llmModel.runWithFallBack(ModelMessage.fromDictList(reqMessages), self.getFallbackModel())
            logger.debug(f"LLM Response: {mlRet}")
            reply = mlRet.resultText
            if mlRet.isFallback:
                reply = f"{ROBOT_EMOJI} {reply}"
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
        #chat = ensuredMessage.chat

        if ensuredMessage.messageType != 'text':
            logger.error(f"Unsupported message type: {ensuredMessage.messageType}")
            return

        messageText = ensuredMessage.messageText

        if not self._saveChatMessage(ensuredMessage, messageCategory='user'):
            logger.error("Failed to save chat message")

        # Check if message is a reply to our message
        if await self.handleGroupReply(update, context, ensuredMessage):
            return

        # Check if we was custom-mentioned
        if await self.handleGroupCustomMention(update, context, ensuredMessage):
            return

        # If our bot has mentioned, answer somehow
        await self.handleGroupMention(update, context, ensuredMessage)

        logger.info(f"Handled message from {user.id}: {messageText[:50]}...")

    async def handleGroupReply(self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: EnsuredMessage) -> bool:
        """
        Check if message is a reply to our message and handle it
        """
        if not ensuredMessage.isReply or ensuredMessage.replyId is None:
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

        parentId = ensuredMessage.replyId
        chat = ensuredMessage.chat

        storedMessages: List[Dict[str, Any]] = []

        storedMsg = self.db.getChatMessageByMessageId(
            chatId=chat.id,
            messageId=parentId,
            threadId=ensuredMessage.threadId,
        )
        if storedMsg is None:
            logger.error("Failed to get parent message")
            storedMessages.append({
                "message_category": "bot",
                "message_text": ensuredMessage.replyText or ""
            })
            storedMessages.append({
                "message_category": "user",
                "message_text": ensuredMessage.messageText
            })
        else:
            if storedMsg["message_category"] != "bot":
                return False

            storedMessages: List[Dict[str, Any]] = self.db.getChatMessagesByRootId(
                chatId=chat.id,
                rootMessageId=storedMsg["root_message_id"],
                threadId=ensuredMessage.threadId,
            )

        reqMessages = [
            {
                "role": "system",
                "text": self.getChatSystemPrompt(chat.id),
            },
        ]
        for storedMsg in storedMessages:
            reqMessages.append(
                {
                    "role": (
                        "user"
                        if storedMsg["message_category"] == "user"
                        else "assistant"
                    ),
                    "text": storedMsg["message_text"],
                }
            )

        if message.quote and message.quote.text:
            reqMessages[-1]["text"] = f"<quote>{message.quote.text}</quote>\n\n{reqMessages[-1]["text"]}"

        if not await self._sendLLMChatMessage(ensuredMessage, reqMessages):
            logger.error("Failed to send LLM reply")

        return True

    async def handleGroupMention(self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: EnsuredMessage) -> bool:
        """
        Check if bot has been mentioned in the message
        """
        # TODO: Should I handle whole thread if any?

        # logger.debug(f"Bot is: {context.bot.bot} {context.bot.username}")
        myUsername = context.bot.username.lower()
        mentionedMe = False
        message = ensuredMessage.getBaseMessage()
        messageText = ensuredMessage.messageText

        for entity in message.entities:
            if entity.type == MessageEntityType.MENTION:
                mentionText = messageText[entity.offset:entity.offset + entity.length]

                # Проверяем, совпадает ли упоминание с именем бота
                if mentionText.lower() == f"@{myUsername}":
                    mentionedMe = True
                    break

        if not mentionedMe:
            return False

        reqMessages = [
            {
                "role": "system",
                "text": self.getChatSystemPrompt(ensuredMessage.chat.id),
            }
        ]

        isReplyToMyMessage = False
        if (
            ensuredMessage.replyId
            and message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.id == context.bot.id
        ):
            isReplyToMyMessage = True

        if ensuredMessage.replyText:
            reqMessages.append(
                {
                    "role": "assistant" if isReplyToMyMessage else "user",
                    "text": ensuredMessage.replyText,
                }
            )

        if message.quote and message.quote.text:
            reqMessages.append(
                {
                    "role": "user",
                    "text": f"<quote>{message.quote.text}</quote>\n\n{messageText}",
                }
            )
        else:
            reqMessages.append(
                {
                    "role": "user",
                    "text": messageText,
                }
            )

        if not await self._sendLLMChatMessage(ensuredMessage, reqMessages):
            logger.error("Failed to send LLM reply")
            return False

        return True

    async def handleGroupCustomMention(self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: EnsuredMessage) -> bool:
        """
        Check if bot has been mentioned in the message
        """

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        customMentions = [v.strip().lower() for v in chatSettings[ChatSettingsEnum.CUSTOM_MENTIONS].split(",")]
        customMentions = [v for v in customMentions if v]
        if not customMentions:
            return False
        myUserName = "@" + context.bot.username.lower()
        messageText = ensuredMessage.messageText

        # Remove leading @username from messageText if any
        if messageText.lower().startswith(myUserName):
            messageText = messageText[len(myUserName):].lstrip()

        messageTextLower = messageText.lower()
        found = False
        for mention in customMentions:
            if messageTextLower.startswith(mention):
                # If we found a mention, remove it from the messageText
                # also remove leading spaces, and punctiation if any
                logger.debug(f"Found mention: '{mention}' in message {messageText}")
                mentionLen = len(mention)
                if len(messageText) > mentionLen:
                    if messageText[mentionLen] not in "\t\n\r ,.:":
                        # If this mention is just part of word, skip it
                        continue
                messageText = messageText[len(mention):].lstrip("\t\n\r ,.:")
                found = True
                break

        if not found:
            return False

        # TODO: Add custom actions

        reqMessages = [
            {
                "role": "system",
                "text": self.getChatSystemPrompt(ensuredMessage.chat.id),
            },
            {
                "role": "user",
                "text": messageText,
            }
        ]

        if not await self._sendLLMChatMessage(ensuredMessage, reqMessages):
            logger.error("Failed to send LLM reply")
            return False

        return True
    ###
    # COMMANDS Handlers
    ###

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
        user_data = self.db.getUser(user.id)
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
            userName = ensuredMessage.user.username
            logger.debug(f"User {userName} called summarisation in private chat. Bot owners are {self.botOwners}")
            if userName and userName.lower() in self.botOwners:
                if context.args and len(context.args) >= 2:
                    try:
                        localChatId = int(context.args[1])
                    except ValueError:
                        logger.error(f"Invalid argument: '{context.args[1]}' is not a valid number.")
                else:
                    await message.reply_text(
                        "Need to provide <bulk_limit> and <chatId> for summarization in private messages",
                        reply_to_message_id=message.message_id,
                    )
                    return

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
        # Summarise each chunk of messages
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

                mlRet: Optional[ModelRunResult] = None
                try:
                    logger.debug(f"LLM Request messages: {reqMessages}")
                    mlRet = llmModel.runWithFallBack(ModelMessage.fromDictList(reqMessages), self.getFallbackSummaryModel())
                    logger.debug(f"LLM Response: {mlRet}")
                except Exception as e:
                    logger.error(f"Error while running LLM for batch {startPos}:{startPos+currentBatchLen}: {type(e).__name__}#{e}")
                    resMessages.append(f"Error while running LLM for batch {startPos}:{startPos+currentBatchLen}: {type(e).__name__}")
                    break
                respText = mlRet.resultText
                if mlRet.isFallback:
                    respText = f"{ROBOT_EMOJI} {respText}"
                resMessages.append(mlRet.resultText)

            startPos += currentBatchLen
            batchN += 1
            if maxBatches and batchN >= maxBatches:
                break

        # If any message is too long, just split it into multiple messages
        tmpResMessages = []
        for msg in resMessages:
            while len(msg) > TELEGRAM_MAX_MESSAGE_LENGTH:
                head = msg[:TELEGRAM_MAX_MESSAGE_LENGTH]
                msg = msg[TELEGRAM_MAX_MESSAGE_LENGTH:]
                tmpResMessages.append(head)
            if msg:
                tmpResMessages.append(msg)

        resMessages = tmpResMessages

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

            time.sleep(1)

    async def models_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /models command."""
        modelsPerMessage = 4
        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        ensuredMessage : Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        # user = ensuredMessage.user
        # chat = ensuredMessage.chat
        replyKwargs = {
            "reply_to_message_id": ensuredMessage.messageId,
            "message_thread_id": ensuredMessage.threadId,
            "parse_mode": "Markdown",
        }

        replyText = "*Доступные модели:*\n\n"

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
            }
            replyText += f"*Модель: {modelName}*\n```{modelName}\n"
            for k, v in modelData.items():
                replyText += f"{modelKeyI18n.get(k, k)}: {v}\n"

            replyText += "```\n\n"

            if i % modelsPerMessage == (modelsPerMessage - 1):
                await message.reply_text(replyText, **replyKwargs)
                replyText = ""
                time.sleep(0.5)

        if replyText:
            await message.reply_text(replyText, **replyKwargs)

    async def chat_settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /settings command."""
        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        ensuredMessage : Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        replyKwargs = {
            "reply_to_message_id": ensuredMessage.messageId,
            "message_thread_id": ensuredMessage.threadId,
            "parse_mode": "Markdown",
        }

        # user = ensuredMessage.user
        chat = ensuredMessage.chat
        chatType = chat.type

        if chatType not in [Chat.GROUP, Chat.SUPERGROUP]:
            await message.reply_text(
                "This command is only available in groups and supergroups for now.",
                **replyKwargs,
            )
            return

        resp = f"Настройки чата *#{chat.id}*:\n\n"
        chatSettings = self.getChatSettings(chat.id)
        for k, v in chatSettings.items():
            resp += f"`{k}`: ```{k}\n{v}\n```\n"
        await message.reply_text(resp, **replyKwargs)

    async def set_chat_setting_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /set <key> <value> command."""
        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        ensuredMessage : Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        replyKwargs = {
            "reply_to_message_id": ensuredMessage.messageId,
            "message_thread_id": ensuredMessage.threadId,
            "parse_mode": "Markdown",
        }

        user = ensuredMessage.user
        chat = ensuredMessage.chat
        chatType = chat.type

        if chatType not in [Chat.GROUP, Chat.SUPERGROUP]:
            await message.reply_text(
                "This command is only available in groups and supergroups for now.",
                **replyKwargs,
            )
            return

        if not user.username:
            await message.reply_text(
                "You need to have a username to change chat settings.",
                **replyKwargs,
            )
            return

        if not context.args or len(context.args) < 2:
            await message.reply_text(
                "You need to specify a key and a value to change chat settings.",
                **replyKwargs,
            )
            return

        chatSettings = self.getChatSettings(chat.id)
        adminAllowedChangeSettings = chatSettings.get(ChatSettingsEnum.ALLOW_ADMIN_CHANGE_SETTINGS, str(self.defaultAdminCanChangeSettings))
        adminAllowedChangeSettings = adminAllowedChangeSettings.lower() == "true"

        allowedUsers = self.botOwners[:]
        if adminAllowedChangeSettings:
            for admin in await chat.get_administrators():
                logger.debug(f"Got admin for chat {chat.id}: {admin}")
                username = admin.user.username
                if username:
                    allowedUsers.append(username.lower())

        if user.username.lower() not in allowedUsers:
            await message.reply_text(
                "You are not allowed to change chat settings.",
                **replyKwargs,
            )
            return

        key = context.args[0]
        value = " ".join(context.args[1:])
        self.setChatSettings(chat.id, {key: value})

        await message.reply_text(f"Готово, теперь `{key}` = `{value}`", **replyKwargs)

    async def unset_chat_setting_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /unset <key> command."""
        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        ensuredMessage : Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        replyKwargs = {
            "reply_to_message_id": ensuredMessage.messageId,
            "message_thread_id": ensuredMessage.threadId,
            "parse_mode": "Markdown",
        }

        user = ensuredMessage.user
        chat = ensuredMessage.chat
        chatType = chat.type

        if chatType not in [Chat.GROUP, Chat.SUPERGROUP]:
            await message.reply_text(
                "This command is only available in groups and supergroups for now.",
                **replyKwargs,
            )
            return

        if not user.username:
            await message.reply_text(
                "You need to have a username to change chat settings.",
                **replyKwargs,
            )
            return

        if not context.args or len(context.args) < 1:
            await message.reply_text(
                "You need to specify a key and a value to change chat settings.",
                **replyKwargs,
            )
            return

        chatSettings = self.getChatSettings(chat.id)
        adminAllowedChangeSettings = chatSettings.get(ChatSettingsEnum.ALLOW_ADMIN_CHANGE_SETTINGS, str(self.defaultAdminCanChangeSettings))
        adminAllowedChangeSettings = adminAllowedChangeSettings.lower() == "true"

        allowedUsers = self.botOwners[:]
        if adminAllowedChangeSettings:
            for admin in await chat.get_administrators():
                logger.debug(f"Got admin for chat {chat.id}: {admin}")
                username = admin.user.username
                if username:
                    allowedUsers.append(username.lower())

        if user.username.lower() not in allowedUsers:
            await message.reply_text(
                "You are not allowed to change chat settings.",
                **replyKwargs,
            )
            return

        key = context.args[0]
        value = " ".join(context.args[1:])
        self.unsetChatSetting(chat.id, key)

        await message.reply_text(f"Готово, теперь `{key}` сброшено в значение по умолчанию", **replyKwargs)

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors."""
        logger.error(f"Exception while handling an update: {type(context.error).__name__}#{context.error}")
