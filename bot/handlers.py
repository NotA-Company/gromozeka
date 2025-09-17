"""
Telegram bot command handlers for Gromozeka.
"""
import datetime
from enum import StrEnum
import json
import logging

import random
import time
from typing import Any, Dict, List, Optional

import requests
from telegram import Chat, Update, Message
from telegram.constants import MessageEntityType
from telegram.ext import ContextTypes

from ai.abstract import AbstractModel, LLMAbstractTool, LLMFunctionParameter, LLMParameterType, LLMToolFunction, ModelMessage, ModelRunResult, ModelResultStatus
from ai.manager import LLMManager
from database.wrapper import DatabaseWrapper
import lib.telegram_markdown as telegramMarkdown
from .ensured_message import EnsuredMessage, LLMMessageFormat

logger = logging.getLogger(__name__)

DEFAULT_SUMMARISATION_SYSTEM_PROMPT = "Суммаризируй пользовательские сообщения, предоставленные в JSON формате. Указывай время начала и конца обсуждения и пользователей, кто обсуждал."
DEFAULT_PRIVATE_PROMPT = "Ты - Принни: вайбовый, но умный пингвин из Disgaea, мужчина. При ответе ты можешь использовать Markdown форматирование."
DEFAULT_CHAT_SYSTEM_PROMPT =  "Ты - Принни: вайбовый, но умный пингвин из Disgaea мужского пола. При ответе ты можешь использовать Markdown форматирование."
ROBOT_EMOJI = "🤖"
TELEGRAM_MAX_MESSAGE_LENGTH = 4096

class ChatSettingsEnum(StrEnum):
    """Enum for chat settings."""
    CHAT_MODEL = "chat-model"
    FALLBACK_MODEL = "fallback-model"
    SUMMARY_MODEL = "summary-model"
    SUMMARY_FALLBACK_MODEL = "summary-fallback-model"
    IMAGE_MODEL = "image-model"

    SUMMARY_PROMPT = "summary-prompt"
    CHAT_PROMPT = "chat-prompt"
    PARSE_IMAGE_PROMPT = "parse-image-prompt"

    ADMIN_CAN_CHANGE_SETTINGS = "admin-can-change-settings"
    BOT_NICKNAMES = "bot-nicknames"
    LLM_MESSAGE_FORMAT = "llm-message-format"
    USE_TOOLS = "use-tools"
    SAVE_IMAGES = "save-images"
    PARSE_IMAGES = "parse-images"
    def __str__(self):
        return str(self.value)

class BotHandlers:
    """Contains all bot command and message handlers."""

    def __init__(self, config: Dict[str, Any], database: DatabaseWrapper, llmManager: LLMManager):
        """Initialize handlers with database and LLM model."""
        self.config = config
        self.db = database
        self.llmManager = llmManager

        # Init different defaults
        self.botOwners = [username.lower() for username in self.config.get("bot_owners", [])]

        botDefaults = config.get("defaults", {})
        
        self.privateModel = str(botDefaults.get("private-model", "yandexgpt-lite"))
        self.fallbackModel = str(botDefaults.get(ChatSettingsEnum.FALLBACK_MODEL, "yandexgpt-lite"))
        self.privatePrompt = str(botDefaults.get("private-prompt", DEFAULT_PRIVATE_PROMPT))

        self.chatDefaults: Dict[ChatSettingsEnum, Any] = {
            k: '' for k in ChatSettingsEnum
        }

        self.chatDefaults.update({
            k: v for k, v in botDefaults.items() if k in ChatSettingsEnum
        })
        
        # Init cache
        self.cache = {
            "chats": {},
        }

    ###
    # Helpers for getting needed Models or Prompts
    ###
    def updateDefaults(self) -> None:
        pass
        
    def getSummaryPrompt(self, chatId: Optional[int] = None) -> str:
        """Get the system prompt for summarising messages."""
        if not chatId:
            return self.chatDefaults[ChatSettingsEnum.SUMMARY_PROMPT]

        chatSettings = self.getChatSettings(chatId)
        return chatSettings[ChatSettingsEnum.SUMMARY_PROMPT]

    def getChatPrompt(self, chatId: Optional[int] = None) -> str:
        """Get the system prompt for chatting."""
        if not chatId:
            return self.chatDefaults[ChatSettingsEnum.CHAT_PROMPT]
        
        chatSettings = self.getChatSettings(chatId)
        return chatSettings[ChatSettingsEnum.CHAT_PROMPT]

    def getPrivatePrompt(self, chatId: Optional[int] = None) -> str:
        """Get the system prompt for private messages."""
        if not chatId:
            return self.privatePrompt
        # TODO: Try to get it from the database
        return self.privatePrompt

    def getSummaryModel(self, chatId: Optional[int] = None) -> AbstractModel:
        """Get the model for summarising messages."""

        modelName = str(self.chatDefaults[ChatSettingsEnum.SUMMARY_MODEL])
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
        modelName = str(self.chatDefaults[ChatSettingsEnum.CHAT_MODEL])
        
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
        modelName = self.privateModel
        if chatId:
            # TODO: Try to get it from the database
            pass

        ret = self.llmManager.getModel(modelName)
        if ret is None:
            logger.error(f"Model {modelName} not found")
            raise ValueError(f"Model {modelName} not found")
        return ret

    def getFallbackModel(self, chatId: Optional[int] = None) -> AbstractModel:
        """Get the model for fallback messages."""
        modelName = str(self.chatDefaults[ChatSettingsEnum.FALLBACK_MODEL])
        if chatId:
            chatSettings = self.getChatSettings(chatId)
            modelName = chatSettings.get(ChatSettingsEnum.FALLBACK_MODEL, modelName)

        ret = self.llmManager.getModel(modelName)
        if ret is None:
            logger.error(f"Model {modelName} not found")
            raise ValueError(f"Model {modelName} not found")
        return ret

    def getFallbackSummaryModel(self, chatId: Optional[int] = None) -> AbstractModel:
        """Get the model for fallback messages."""
        modelName = str(self.chatDefaults[ChatSettingsEnum.SUMMARY_FALLBACK_MODEL])
        if chatId:
            chatSettings = self.getChatSettings(chatId)
            modelName = chatSettings.get(ChatSettingsEnum.SUMMARY_FALLBACK_MODEL, modelName)

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
        if chatId not in self.cache["chats"]:
            self.cache["chats"][chatId] = {}

        if 'settings' not in self.cache["chats"][chatId]:
            self.cache["chats"][chatId]['settings'] = self.db.getChatSettings(chatId)

        if returnDefault:
            return {**self.chatDefaults, **self.cache["chats"][chatId]['settings']}

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

    def _callLLM(self, model: AbstractModel, messages: List[ModelMessage], fallbackModel: AbstractModel, useTools: bool = False) -> ModelRunResult:
        """Call the LLM with the given messages."""

        tools: Dict[str, LLMAbstractTool] = {}
        functions = {
            "get_url_content": lambda **kwargs: str(requests.get(kwargs['url']).content),
        }

        if useTools:
            tools["get_url_content"] = LLMToolFunction(
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
                function=lambda **kwargs: str(requests.get(kwargs['url']).content),
            )

        ret : Optional[ModelRunResult] = None
        while True:
            ret = model.runWithFallBack(messages, fallbackModel=fallbackModel, tools=list(tools.values()))
            logger.debug(f"LLM returned: {ret}")
            if ret.status == ModelResultStatus.TOOL_CALLS:
                messages = messages + [ret.toModelMessage()]
                for toolCall in ret.toolCalls:
                    messages.append(ModelMessage(
                        role="tool",
                        content=json.dumps(functions[toolCall.name](**toolCall.parameters), ensure_ascii=False, default=str),
                        toolCallId=toolCall.id,
                    ))
            else:
                break
                
        return ret

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

        self.db.updateChatUser(
            chatId=chat.id,
            userId=user.id,
            username=user.name,
            fullName=user.full_name,
        )
        self.db.saveChatMessage(
            date=message.date,
            chatId=chat.id,
            userId=user.id,
            messageId=message.messageId,
            replyId=replyId,
            threadId=message.threadId,
            messageText=messageText,
            messageType='text', # In future we'll support not only text messages, but photos, stickers and something else. Or not
            messageCategory=messageCategory,
            rootMessageId=rootMessageId,
            quoteText=message.quoteText,
        )

        return True

    async def _sendLLMChatMessage(self, ensuredMessage: EnsuredMessage, messagesHistory: List[Dict[str, str]]) -> bool:
        """Send a chat message to the LLM model."""
        logger.debug(f"LLM Request messages: {messagesHistory}")
        llmModel = self.getChatModel(ensuredMessage.chat.id)
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        mlRet: Optional[ModelRunResult] = None
        try:
            # mlRet = llmModel.runWithFallBack(ModelMessage.fromDictList(messagesHistory), self.getFallbackModel())
            mlRet = self._callLLM(
                model=llmModel,
                messages=ModelMessage.fromDictList(messagesHistory),
                fallbackModel=self.getFallbackModel(),
                useTools=chatSettings[ChatSettingsEnum.USE_TOOLS].lower() == "true",
            )
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
        # If response is json, parse it
        try:
            jsonReply = json.loads(LLMReply.strip('`'))
            LLMReply = jsonReply["text"].strip()
        except Exception as e:
            logger.debug(f"Error while parsing LLM reply, assume it's text: {type(e).__name__}#{e}")

        prefix = ""
        if mlRet.isFallback:
            prefix = f"{ROBOT_EMOJI} "

        replyMessage = None
        LLMReply = f"{prefix}{LLMReply.strip()}"
        replyKwargs = {
            "reply_to_message_id": ensuredMessage.messageId,
            "message_thread_id": ensuredMessage.threadId,
        }
        try:
            logger.debug(f"Sending LLM reply to {ensuredMessage}")
            replyText = telegramMarkdown.convertMarkdownToV2(LLMReply)
            # logger.debug(f"Sending MarkdownV2: {replyText}")
            replyMessage = await ensuredMessage.getBaseMessage().reply_text(
                text=replyText,
                parse_mode="MarkdownV2",
                **replyKwargs,
            )
        except Exception as e:
            logger.error(f"Error while replying to message: {type(e).__name__}#{e}")
            # Probably error in markdown formatting, fallback to raw text
            replyMessage = await ensuredMessage.getBaseMessage().reply_text(text=LLMReply, **replyKwargs)
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
                "content": self.getPrivatePrompt(chatId=user.id),
            },
        ]

        for msg in reversed(messages):
            reqMessages.append({
                "role": "user",
                "content": msg["message_text"],
            })
            if message["reply_text"]:
                reqMessages.append({
                    "role": "assistant",
                    "content": msg["reply_text"],
                })
        reqMessages.append({
            "role": "user",
            "content": ensuredMessage.messageText,
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

        replyKwargs: Dict[str, Any] = {
            "reply_to_message_id": ensuredMessage.messageId,
        }
        try:
            await message.reply_text(
                text=telegramMarkdown.convertMarkdownToV2(reply),
                parse_mode="MarkdownV2",
                **replyKwargs,
            )
        except Exception as e:
            logger.error(f"Error while replying to message: {type(e).__name__}#{e}")
            # Probably error in markdown formatting, fallback to raw text
            await message.reply_text(
                text=reply,
                **replyKwargs,
            )
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
        # chat = ensuredMessage.chat

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

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsEnum.LLM_MESSAGE_FORMAT])

        parentId = ensuredMessage.replyId
        chat = ensuredMessage.chat

        storedMessages: List[Dict[str, str]] = []

        storedMsg = self.db.getChatMessageByMessageId(
            chatId=chat.id,
            messageId=parentId,
            threadId=ensuredMessage.threadId,
        )
        if storedMsg is None:
            logger.error("Failed to get parent message")
            if not message.reply_to_message:
                logger.error("message.reply_to_message is None, but should be Message()")
                return False
            ensuredReply = EnsuredMessage(message.reply_to_message)
            storedMessages.append({
                "role": "assistant",
                "content": ensuredReply.formatForLLM(format=llmMessageFormat)
            })
            storedMessages.append({
                "role": "user",
                "content": ensuredMessage.formatForLLM(format=llmMessageFormat)
            })
        else:
            if storedMsg["message_category"] != "bot":
                return False

            _storedMessages: List[Dict[str, Any]] = self.db.getChatMessagesByRootId(
                chatId=chat.id,
                rootMessageId=storedMsg["root_message_id"],
                threadId=ensuredMessage.threadId,
            )
            storedMessages = [
                {
                    "role": "user" if storedMsg["message_category"] == "user" else "assistant",
                    "content": EnsuredMessage.formatDBChatMessageToLLM(storedMsg, format=llmMessageFormat),
                }
                for storedMsg in _storedMessages
            ]

        reqMessages = [
            {
                "role": "system",
                "content": self.getChatPrompt(chat.id),
            },
        ] + storedMessages

        if not await self._sendLLMChatMessage(ensuredMessage, reqMessages):
            logger.error("Failed to send LLM reply")

        return True

    async def handleGroupMention(self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: EnsuredMessage) -> bool:
        """
        Check if bot has been mentioned in the message
        """
        # TODO: Should I handle whole thread if any?

        # logger.debug(f"Bot is: {context.bot.bot} {context.bot.username}")
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsEnum.LLM_MESSAGE_FORMAT])
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
                "content": self.getChatPrompt(ensuredMessage.chat.id),
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

        if ensuredMessage.replyText and message.reply_to_message:
            ensuredReply = EnsuredMessage(message.reply_to_message)

            reqMessages.append(
                {
                    "role": "assistant" if isReplyToMyMessage else "user",
                    "content": ensuredReply.formatForLLM(format=llmMessageFormat),
                }
            )

        reqMessages.append(
            {
                "role": "user",
                "content": ensuredMessage.formatForLLM(format=llmMessageFormat),
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
        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsEnum.LLM_MESSAGE_FORMAT])
        customMentions = [v.strip().lower() for v in chatSettings[ChatSettingsEnum.BOT_NICKNAMES].split(",")]
        customMentions = [v for v in customMentions if v]
        if not customMentions:
            return False
        myUserName = "@" + context.bot.username.lower()
        messageText = ensuredMessage.messageText
        matched = False

        # Remove leading @username from messageText if any
        if messageText.lower().startswith(myUserName):
            messageText = messageText[len(myUserName):].lstrip()
            matched = True

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

        if not found and not matched:
            return False

        # TODO: Add custom actions

        whoToday = "кто сегодня "
        if messageText.lower().startswith(whoToday):
            userTitle = messageText[len(whoToday):].strip()
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
            logger.debug(f"Found user for candidate of being '{userTitle}': {user}")
            replyMessage = await ensuredMessage.getBaseMessage().reply_text(
                text=f"{user['username']} сегодня {userTitle}",
                reply_to_message_id=ensuredMessage.messageId,
                message_thread_id=ensuredMessage.threadId,
            )

            try:
                ensuredReplyMessage = EnsuredMessage(replyMessage)
                self._saveChatMessage(ensuredReplyMessage, messageCategory='bot')
                return True
            except Exception as e:
                logger.error(f"Error while saving chat message: {type(e).__name__}#{e}")
                return False

        reqMessages = [
            {
                "role": "system",
                "content": self.getChatPrompt(ensuredMessage.chat.id),
            },
            {
                "role": "user",
                "content": ensuredMessage.formatForLLM(format=llmMessageFormat, replaceMessageText=messageText),
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
        """Handle the /summary [<messages> <chunks> <chat_id>]command."""
        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        maxBatches: Optional[int] = None
        maxMessages: Optional[int] = None
        if context.args:
            try:
                maxMessages = int(context.args[0])
                if maxMessages < 1:
                    maxMessages = None

                if len(context.args) > 1:
                    maxBatches = int(context.args[1])
                    if maxBatches < 1:
                        maxBatches = None
            except ValueError:
                logger.error(f"Invalid argument: '{context.args[0:2]}' is not a valid number.")

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
                if context.args and len(context.args) >= 3:
                    try:
                        localChatId = int(context.args[2])
                    except ValueError:
                        logger.error(f"Invalid argument: '{context.args[2]}' is not a valid number.")
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

        logger.debug(f"Getting summary for chat {chatId}, thread {threadId}, maxBatches {maxBatches}, maxMessages {maxMessages}")
        today = datetime.datetime.now(datetime.timezone.utc)
        today = today.replace(hour=0, minute=0, second=0, microsecond=0)

        messages = self.db.getChatMessageSince(
            chatId=chatId,
            sinceDateTime=today if maxMessages is None else None,
            threadId=threadId,
            limit=maxMessages,
        )

        logger.debug(f"Messages: {messages}")

        systemMessage = {
            "role": "system",
            "content": self.getSummaryPrompt(chatId=chatId),
        }
        parsedMessages = []

        for msg in reversed(messages):
            parsedMessages.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            # date, chat_id, user_id, username, full_name, message_id, reply_id, thread_id, message_text, message_type
                            "date": msg["date"],
                            "sender": msg["username"][1:],
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
                "reply_to_message_id": ensuredMessage.messageId,
                "message_thread_id": ensuredMessage.threadId,
            }
            replyMessage: Optional[Message] = None
            try:
                replyText = telegramMarkdown.convertMarkdownToV2(msg)
                # logger.debug(f"Sending MarkdownV2: {replyText}")
                replyMessage = await message.reply_text(
                    text=replyText,
                    parse_mode="MarkdownV2",
                    **replyKwargs,
                )
            except Exception as e:
                logger.error(f"Error while replying to message: {type(e).__name__}#{e}")
                replyMessage = await message.reply_text(text=msg, **replyKwargs)

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
        adminAllowedChangeSettings = chatSettings[ChatSettingsEnum.ADMIN_CAN_CHANGE_SETTINGS]
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
        adminAllowedChangeSettings = chatSettings[ChatSettingsEnum.ADMIN_CAN_CHANGE_SETTINGS]
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
