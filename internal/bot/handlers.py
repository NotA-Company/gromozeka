"""
Telegram bot command handlers for Gromozeka.
"""
import asyncio
import datetime
import json
import logging

import random
import time
from typing import Any, Callable, Dict, List, Optional

import requests
import magic

from telegram import Chat, Update, Message
from telegram.constants import MessageEntityType
from telegram.ext import ContextTypes

from lib.ai.abstract import AbstractModel, LLMAbstractTool
from lib.ai.models import LLMFunctionParameter, LLMParameterType, LLMToolFunction, ModelImageMessage, ModelMessage, ModelRunResult, ModelResultStatus
from lib.ai.manager import LLMManager

from internal.database.wrapper import DatabaseWrapper
from internal.database.models import MediaStatus

from lib.markdown import markdown_to_markdownv2
import lib.utils as utils
from .ensured_message import EnsuredMessage
from .models import LLMMessageFormat, MessageType, MediaProcessingInfo
from .chat_settings import ChatSettingsKey, ChatSettingsValue

logger = logging.getLogger(__name__)

ROBOT_EMOJI = "🤖"
DUNNO_EMOJI = "🤷‍♂️"
TELEGRAM_MAX_MESSAGE_LENGTH = 4096
MAX_QUEUE_LENGTH = 10
MAX_QUEUE_AGE = 30 * 60 # 30 minutes
PROCESSING_TIMEOUT = 30 * 60 # 30 minutes
PRIVATE_CHAT_CONTEXT_LENGTH = 50

def makeEmptyAsyncTask() -> asyncio.Task:
    """Create an empty async task."""
    return asyncio.create_task(asyncio.sleep(0))

class BotHandlers:
    """Contains all bot command and message handlers."""

    def __init__(self, config: Dict[str, Any], database: DatabaseWrapper, llmManager: LLMManager):
        """Initialize handlers with database and LLM model."""
        self.config = config
        self.db = database
        self.llmManager = llmManager

        # Init different defaults
        self.botOwners = [username.lower() for username in self.config.get("bot_owners", [])]

        botDefaults: Dict[ChatSettingsKey, ChatSettingsValue] = {
            k: ChatSettingsValue(v) for k, v in self.config.get("defaults", {}).items() if k in ChatSettingsKey
        }

        self.chatDefaults: Dict[ChatSettingsKey, ChatSettingsValue] = {
            k: ChatSettingsValue('') for k in ChatSettingsKey
        }

        self.chatDefaults.update({
            k: v for k, v in botDefaults.items() if k in ChatSettingsKey
        })

        # Init cache
        # TODO: Should I use something thread-safe?
        self.cache: Dict[str, Dict[Any, Any]] = {
            "chats": {},
        }

        self.delayedQueue = asyncio.Queue()
        self.queueLastUpdated = time.time()

    ###
    # Helpers for getting needed Models or Prompts
    ###
    def updateDefaults(self) -> None:
        pass

    ###
    # Chat settings Managenent
    ###

    def getChatSettings(self, chatId: int, returnDefault: bool = True) -> Dict[ChatSettingsKey, ChatSettingsValue]:
        """Get the chat settings for the given chat."""
        if chatId not in self.cache["chats"]:
            self.cache["chats"][chatId] = {}

        if 'settings' not in self.cache["chats"][chatId]:
            self.cache["chats"][chatId]['settings'] = {
                k: ChatSettingsValue(v) for k, v in self.db.getChatSettings(chatId).items()
            }

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

    async def addQueueTask(self, task: asyncio.Task) -> None:
        """Add a task to the queue."""
        if self.delayedQueue.qsize() > MAX_QUEUE_LENGTH:
            logger.info(f"Queue is full, processing oldest task")
            oldTask = await self.delayedQueue.get()
            if not isinstance(oldTask, asyncio.Task):
                logger.error(f"Task {oldTask} is not a task, but a {type(oldTask)}")
            else:
                await oldTask
            self.delayedQueue.task_done()

        await self.delayedQueue.put(task)
        self.queueLastUpdated = time.time()

    async def _processBackgroundTasks(self) -> None:
        """Process background tasks."""

        if self.delayedQueue.empty():
            return

        if self.queueLastUpdated + MAX_QUEUE_AGE > time.time():
            return

        logger.info(f"Processing queue due to age ({MAX_QUEUE_AGE})")
        # TODO: Do it properly
        # Little hack to avoid concurency in processing queue
        self.queueLastUpdated = time.time()

        try:
            while True:
                task = await self.delayedQueue.get_nowait()
                if not isinstance(task, asyncio.Task):
                    logger.error(f"Task {task} is not a task, but a {type(task)}")
                else:
                    await task
                self.delayedQueue.task_done()
        except asyncio.QueueEmpty:
            pass
        except Exception as e:
            logger.error(f"Error in background task: {e}")
            logger.exception(e)

    async def awaitMedia(self, fileUniqueId: str) -> Dict[str, Any]:
        raise NotImplemented

    async def _sendMessage(
        self,
        replyToMessage: EnsuredMessage,
        context: ContextTypes.DEFAULT_TYPE,
        messageText: Optional[str] = None,
        addMessagePrefix: str = "",
        photoData: Optional[bytes] = None,
        photoCaption: Optional[str] = None,
        sendMessageKWargs: Optional[Dict[str, Any]] = None,
        tryMarkdownV2: bool = True,
        tryParseInputJSON: bool = True,
        saveMessage: bool = True,
        sendErrorIfAny: bool = True,
        skipLogs: bool = False,
        mediaPrompt: Optional[str] = None,
    ) -> bool:
        """Send a message to the chat or user."""

        if photoData is None and messageText is None:
            logger.error("No message text or photo data provided")
            raise ValueError("No message text or photo data provided")

        replyMessage: Optional[Message] = None
        message = replyToMessage.getBaseMessage()
        chatType = replyToMessage.chat.type
        isPrivate = chatType == Chat.PRIVATE
        isGroupChat = chatType in [Chat.GROUP, Chat.SUPERGROUP]

        if not isPrivate and not isGroupChat:
            logger.error("Cannot send message to chat type {}".format(chatType))
            raise ValueError("Cannot send message to chat type {}".format(chatType))

        if sendMessageKWargs is None:
            sendMessageKWargs = {}

        try:
            if photoData is not None:
                # Send photo
                replyMessage = await message.reply_photo(
                    photo=photoData,
                    caption=photoCaption,
                    reply_to_message_id=replyToMessage.messageId,
                    message_thread_id=replyToMessage.threadId,
                    **sendMessageKWargs,
                )
                # TODO: Save media info somehow
            elif messageText is not None:
                # Send text

                # If response is json, parse it
                if tryParseInputJSON:
                    try:
                        jsonReply = json.loads(messageText.strip("`"))
                        if "text" in jsonReply:
                            messageText = str(jsonReply["text"]).strip()
                        elif "media_description" in jsonReply:
                            messageText = str(jsonReply["media_description"]).strip()
                        else:
                            logger.warning(
                                f"No text field found in json reply, fallback to text: {jsonReply}"
                            )
                            raise ValueError("No text field found in json reply")
                    except Exception as e:
                        logger.debug(
                            f"Error while parsing LLM reply, assume it's text: {type(e).__name__}#{e}"
                        )

                replyKwargs = sendMessageKWargs.copy()
                replyKwargs.update(
                    {
                        "reply_to_message_id": replyToMessage.messageId,
                        "message_thread_id": replyToMessage.threadId,
                    }
                )

                if not skipLogs:
                    logger.debug(f"Sending reply to {replyToMessage}")
                # Try to send Message as MarkdownV2 first
                if tryMarkdownV2:
                    try:
                        messageTextParsed = markdown_to_markdownv2(addMessagePrefix + messageText)
                        # logger.debug(f"Sending MarkdownV2: {replyText}")
                        replyMessage = await message.reply_text(
                            text=messageTextParsed,
                            parse_mode="MarkdownV2",
                            **replyKwargs,
                        )
                    except Exception as e:
                        logger.error(
                            f"Error while sending MarkdownV2 reply to message: {type(e).__name__}#{e}"
                        )
                        # Probably error in markdown formatting, fallback to raw text

                if replyMessage is None:
                    replyMessage = await message.reply_text(
                        text=addMessagePrefix + messageText, **replyKwargs
                    )

            try:
                if replyMessage is None:
                    raise ValueError("No reply message")

                if not skipLogs:
                    logger.debug(f"Sent message: {replyMessage}")

                # Save message if needed
                if saveMessage:
                    ensuredReplyMessage = EnsuredMessage.fromMessage(replyMessage)
                    if addMessagePrefix:
                        replyText = ensuredReplyMessage.messageText
                        if replyText.startswith(addMessagePrefix):
                            replyText = replyText[len(addMessagePrefix) :]
                            ensuredReplyMessage.messageText = replyText
                    if replyMessage.photo:
                        media = await self.processImage(ensuredReplyMessage, context, mediaPrompt)
                        ensuredReplyMessage.setMediaProcessingInfo(media)

                    if isGroupChat or isPrivate:
                        self._saveChatMessage(
                            ensuredReplyMessage, messageCategory="bot"
                        )
                    else:
                        raise ValueError("Unknown chat type")

            except Exception as e:
                logger.error(f"Error while saving chat message: {type(e).__name__}#{e}")
                logger.exception(e)
                # Message was sent, so return True anyway
                return True

        except Exception as e:
            logger.error(f"Error while sending message: {type(e).__name__}#{e}")
            logger.exception(e)
            if sendErrorIfAny:
                await message.reply_text(
                    f"Error while sending message: {type(e).__name__}#{e}",
                    reply_to_message_id=replyToMessage.messageId,
                )
            return False

        return True

    async def _generateTextViaLLM(
        self,
        model: AbstractModel,
        messages: List[ModelMessage],
        fallbackModel: AbstractModel,
        ensuredMessage: EnsuredMessage,
        context: ContextTypes.DEFAULT_TYPE,
        useTools: bool = False,
    ) -> ModelRunResult:
        """Call the LLM with the given messages."""
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)

        async def generateAndSendImage(image_prompt: str, image_description:Optional[str] = None, **kwargs) -> str:
            logger.debug(f"Generating image: {image_prompt}. Image description: {image_description}, mcID: {ensuredMessage.chat.id}:{ensuredMessage.messageId}")
            model = chatSettings[ChatSettingsKey.IMAGE_GENERATION_MODEL].toModel(self.llmManager)

            mlRet = await model.generateImage([ModelMessage(content=image_prompt)])
            logger.debug(f"Generated image Data: {mlRet} for mcID: {ensuredMessage.chat.id}:{ensuredMessage.messageId}")
            if mlRet.status != ModelResultStatus.FINAL:
                ret = await self._sendMessage(
                    ensuredMessage,
                    context,
                    messageText=f"Не удалось сгенерировать изображение.\n```\n{mlRet.status}\n{str(mlRet.resultText)}\n```\nPrompt:\n```\n{image_prompt}\n```"
                )
                return json.dumps({"done": False, 'errorMessage': mlRet.resultText})

            if mlRet.mediaData is None:
                logger.error(f"No image generated for {image_prompt}")
                return '{"done": false}'

            ret = await self._sendMessage(
                ensuredMessage,
                context,
                photoData=mlRet.mediaData,
                photoCaption=image_description,
                mediaPrompt=image_prompt,
            )

            return json.dumps({"done": ret})

        async def getUrlContent(url: str, **kwargs) -> str:
            # TODO: Check if content is text content
            return str(requests.get(url).content)

        tools: Dict[str, LLMAbstractTool] = {}
        functions: Dict[str, Callable] = {
            "get_url_content": getUrlContent,
            "generate_and_send_image": generateAndSendImage,
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
                function=functions["get_url_content"],
            )
            tools["generate_and_send_image"] = LLMToolFunction(
                name="generate_and_send_image",
                description="Generate and send an image. ALWAYS use it if user ask to generate/paint/draw an image/picture/photo",
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
                function=functions["generate_and_send_image"],
            )

        ret : Optional[ModelRunResult] = None
        toolsUsed = False
        while True:
            ret = await model.generateTextWithFallBack(messages, fallbackModel=fallbackModel, tools=list(tools.values()))
            logger.debug(f"LLM returned: {ret} for mcID: {ensuredMessage.chat.id}:{ensuredMessage.messageId}")
            if ret.status == ModelResultStatus.TOOL_CALLS:
                toolsUsed = True
                newMessages = [ret.toModelMessage()]

                for toolCall in ret.toolCalls:
                    newMessages.append(
                        ModelMessage(
                            role="tool",
                            content=json.dumps(
                                await functions[toolCall.name](**toolCall.parameters),
                                ensure_ascii=False,
                                default=str,
                            ),
                            toolCallId=toolCall.id,
                        )
                    )
                messages = messages + newMessages
                logger.debug(f"Tools used: {newMessages} for mcID: {ensuredMessage.chat.id}:{ensuredMessage.messageId}")
            else:
                break

        if toolsUsed:
            ret.setToolsUsed(True)

        return ret

    def _saveChatMessage(self, message: EnsuredMessage, messageCategory: str = 'user') -> bool:
        """Save a chat message to the database."""
        user = message.user
        chat = message.chat

        if message.messageType == MessageType.UNKNOWN:
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
            messageType=message.messageType,
            messageCategory=messageCategory,
            rootMessageId=rootMessageId,
            quoteText=message.quoteText,
            mediaId=message.mediaId,
        )

        return True

    async def _sendLLMChatMessage(
        self,
        ensuredMessage: EnsuredMessage,
        messagesHistory: List[Dict[str, str]],
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        """Send a chat message to the LLM model."""
        logger.debug(f"LLM Request messages: {messagesHistory}")
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        llmModel = chatSettings[ChatSettingsKey.CHAT_MODEL].toModel(self.llmManager)
        mlRet: Optional[ModelRunResult] = None

        try:
            # mlRet = llmModel.runWithFallBack(ModelMessage.fromDictList(messagesHistory), self.getFallbackModel())
            mlRet = await self._generateTextViaLLM(
                model=llmModel,
                messages=ModelMessage.fromDictList(messagesHistory),
                fallbackModel=chatSettings[ChatSettingsKey.FALLBACK_MODEL].toModel(self.llmManager),
                ensuredMessage=ensuredMessage,
                context=context,
                useTools=chatSettings[ChatSettingsKey.USE_TOOLS].toBool(),
            )
            #logger.debug(f"LLM Response: {mlRet}")
        except Exception as e:
            logger.error(f"Error while sending LLM request: {type(e).__name__}#{e}")
            logger.exception(e)
            await self._sendMessage(
                ensuredMessage,
                context,
                messageText=f"Error while sending LLM request: {type(e).__name__}",
                saveMessage=False,
            )
            return False

        addPrefix = ""
        if mlRet.isFallback:
            addPrefix += chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr()
        if mlRet.isToolsUsed:
            addPrefix += chatSettings[ChatSettingsKey.TOOLS_USED_PREFIX].toStr()

        return await self._sendMessage(
            ensuredMessage,
            context,
            messageText=mlRet.resultText,
            addMessagePrefix=addPrefix,
        )

    ###
    # Handling messages
    ###

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle regular text messages."""
        # logger.debug(f"Handling SOME message: {update}")

        # process background tasks if any
        await self._processBackgroundTasks()

        chat = update.effective_chat
        if not chat:
            logger.error("Chat undefined")
            return
        chatType = chat.type

        match chatType:
            case Chat.PRIVATE:
                return await self.handle_chat_message(update, context)
            case Chat.GROUP:
                return await self.handle_chat_message(update, context)
            case Chat.SUPERGROUP:
                return await self.handle_chat_message(update, context)
            case Chat.CHANNEL:
                logger.error(f"Unsupported chat type: {chatType}")
            case _:
                logger.error(f"Unsupported chat type: {chatType}")

    async def handle_chat_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.debug(f"Handling group message: {update}")
        message = update.message
        if not message:
            # Not new message, ignore
            # logger.error("Message undefined")
            return

        ensuredMessage : Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        user = ensuredMessage.user
        # chat = ensuredMessage.chat

        media = {}

        match ensuredMessage.messageType:
            case MessageType.TEXT:
                # No special handling for text messages needed
                pass
            case MessageType.IMAGE:
                media = await self.processImage(ensuredMessage, context)
                ensuredMessage.setMediaProcessingInfo(media)
            case MessageType.STICKER:
                media = await self.processSticker(update, context, ensuredMessage)
                ensuredMessage.setMediaProcessingInfo(media)

            case _:
                logger.error(f"Unsupported message type: {ensuredMessage.messageType}")
                return

        messageText = ensuredMessage.messageText

        if not self._saveChatMessage(ensuredMessage, messageCategory='user'):
            logger.error("Failed to save chat message")

        # Check if message is a reply to our message
        if await self.handleReply(update, context, ensuredMessage):
            return

        # Check if we was mentioned
        if await self.handleMention(update, context, ensuredMessage):
            return

        if ensuredMessage.chat.type == Chat.PRIVATE:
            await self.handlePrivateMessage(update, context, ensuredMessage)

        logger.info(f"Handled message from {user.id}: {messageText[:50]}...")

    async def handleReply(self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: EnsuredMessage) -> bool:
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

        # As it's resporse to our message, we need to wait for media to be processed if any
        await ensuredMessage.updateMediaContent(self.db)

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())

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
            ensuredReply = EnsuredMessage.fromMessage(message.reply_to_message)
            storedMessages.append({
                "role": "assistant",
                "content": await ensuredReply.formatForLLM(self.db, format=llmMessageFormat)
            })
            storedMessages.append({
                "role": "user",
                "content": await ensuredMessage.formatForLLM(self.db, format=llmMessageFormat)
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
                    "content": await EnsuredMessage.formatDBChatMessageToLLM(self.db, storedMsg, format=llmMessageFormat),
                }
                for storedMsg in _storedMessages
            ]

        reqMessages = [
            {
                "role": "system",
                "content": chatSettings[ChatSettingsKey.CHAT_PROMPT].toStr(),
            },
        ] + storedMessages

        if not await self._sendLLMChatMessage(ensuredMessage, reqMessages, context):
            logger.error("Failed to send LLM reply")

        return True

    async def handleMention(self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: EnsuredMessage) -> bool:
        """
        Check if bot has been mentioned in the message
        """

        message = ensuredMessage.getBaseMessage()
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())
        customMentions = chatSettings[ChatSettingsKey.BOT_NICKNAMES].toList()
        customMentions = [v.lower() for v in customMentions if v]
        if not customMentions:
            return False
        myUserName = "@" + context.bot.username.lower()
        messageText = ensuredMessage.messageText
        mentionedAtBegin = False
        mentionedMe = False
        mentionedByNick = False

        for entity in message.entities:
            if entity.type == MessageEntityType.MENTION:
                mentionText = messageText[entity.offset:entity.offset + entity.length]

                # Проверяем, совпадает ли упоминание с именем бота
                if mentionText.lower() == f"{myUserName}":
                    mentionedMe = True
                    break

        # Remove leading @username from messageText if any
        if messageText.lower().startswith(myUserName):
            messageText = messageText[len(myUserName):].lstrip()
            mentionedAtBegin = True

        messageTextLower = messageText.lower()
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
                mentionedByNick = True
                break

        if not mentionedByNick and not mentionedAtBegin and not mentionedMe:
            return False

        messageTextLower = messageText.lower()

        ###
        # Random choose from users who were active today
        ###
        # TODO: Save to DB
        whoToday = "кто сегодня "
        if messageTextLower.startswith(whoToday):
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
            return await self._sendMessage(
                ensuredMessage,
                context,
                messageText=f"{user['username']} сегодня {userTitle}",
                tryParseInputJSON=False,
            )

        # End of Who Today

        ###
        # what there? Return parsed media content of replied message (if any)
        ###
        whatThereList = ["что там"]

        isWhatThere = False
        for whatThere in whatThereList:
            if messageTextLower.startswith(whatThere):
                tail = messageText[len(whatThere):].strip()

                # Match only whole message
                if not tail.rstrip('?.').strip():
                    isWhatThere = True
                    break

        if isWhatThere and ensuredMessage.isReply and message.reply_to_message:
            # TODO: Move getting parent message to separate function
            ensuredReply = EnsuredMessage.fromMessage(message.reply_to_message)
            response = DUNNO_EMOJI
            if ensuredReply.messageType != MessageType.TEXT:
                # Not text message, try to get it content from DB
                storedReply = self.db.getChatMessageByMessageId(
                    chatId=ensuredReply.chat.id,
                    messageId=ensuredReply.messageId,
                )
                if storedReply is None:
                    logger.error(f"Failed to get parent message (ChatId: {ensuredReply.chat.id}, MessageId: {ensuredReply.messageId})")
                else:
                    response = storedReply.get('media_description', None)
                    if response is None or response == "":
                        response = DUNNO_EMOJI

                return await self._sendMessage(
                    ensuredMessage,
                    context,
                    messageText=response,
                    tryParseInputJSON=False,
                )

        # End of What There

        # Handle LLM Action
        reqMessages = [
            {
                "role": "system",
                "content": chatSettings[ChatSettingsKey.CHAT_PROMPT].toStr(),
            },
        ]

        # Add Parent message if any
        if ensuredMessage.isReply and message.reply_to_message:
            ensuredReply = EnsuredMessage.fromMessage(message.reply_to_message)
            if ensuredReply.messageType == MessageType.TEXT:
                reqMessages.append(
                    {
                        "role": "assistant" if ensuredReply.user.id == context.bot.id else "user",
                        "content": await ensuredReply.formatForLLM(self.db, format=llmMessageFormat),
                    }
                )
            else:
                # Not text message, try to get it content from DB
                storedReply = self.db.getChatMessageByMessageId(
                    chatId=ensuredReply.chat.id,
                    messageId=ensuredReply.messageId,
                )
                if storedReply is None:
                    logger.error(f"Failed to get parent message (ChatId: {ensuredReply.chat.id}, MessageId: {ensuredReply.messageId})")
                else:
                    reqMessages.append(
                        {
                            "role": "assistant" if ensuredReply.user.id == context.bot.id else "user",
                            "content": await EnsuredMessage.formatDBChatMessageToLLM(self.db, storedReply, llmMessageFormat),
                        }
                    )

        # Add user message
        reqMessages.append(
            {
                "role": "user",
                "content": await ensuredMessage.formatForLLM(
                    self.db, format=llmMessageFormat, replaceMessageText=messageText
                ),
            }
        )

        if not await self._sendLLMChatMessage(ensuredMessage, reqMessages, context):
            logger.error("Failed to send LLM reply")
            return False

        return True

    async def handlePrivateMessage(self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: EnsuredMessage) -> bool:
        """ Process message in private chat """
        # If it message in private chat and no other methods catched message,
        # then just do LLM answer with context of last PRIVATE_CHAT_CONTEXT_LENGTH messages

        messages = self.db.getChatMessagesSince(ensuredMessage.chat.id, limit=PRIVATE_CHAT_CONTEXT_LENGTH)
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())

        # Handle LLM Action
        reqMessages = [
            {
                "role": "system",
                "content": chatSettings[ChatSettingsKey.CHAT_PROMPT].toStr(),
            },
        ]
        for message in reversed(messages):
            reqMessages.append(
                {
                    "role": "assistant" if message["message_category"] == "bot" else "user",
                    "content": await EnsuredMessage.formatDBChatMessageToLLM(self.db, message, llmMessageFormat),
                }
            )

        if not await self._sendLLMChatMessage(ensuredMessage, reqMessages, context):
            logger.error("Failed to send LLM reply")
            return False

        return True

    ###
    # Processing media
    ###

    async def _parseImage(self, ensuredMessage: EnsuredMessage, fileUniqueId: str, messages: List[ModelMessage]) -> Any:
        """
        Parse image content using LLM
        """

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)

        try:
            llmModel = chatSettings[ChatSettingsKey.IMAGE_PARSING_MODEL].toModel(self.llmManager)
            logger.debug(f"Prompting Image {ensuredMessage.mediaId} LLM for image with prompt: {messages[:1]}")
            llmRet = await llmModel.generateText(messages)
            logger.debug(f"Image LLM Response: {llmRet}")

            if llmRet.status != ModelResultStatus.FINAL:
                raise RuntimeError(f"Image LLM Response status is not FINAL: {llmRet.status}")

            description = llmRet.resultText
            self.db.updateMediaAttachment(
                fileUniqueId=fileUniqueId,
                status=MediaStatus.DONE,
                description=description,
            )
            return True

        except Exception as e:
            logger.error(f"Failed to parse image: {e}")
            self.db.updateMediaAttachment(
                fileUniqueId=fileUniqueId,
                status=MediaStatus.FAILED,
            )
            return False

        # ret['content'] = llmRet.resultText

    async def processSticker(self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: EnsuredMessage) -> MediaProcessingInfo:
        """
        Process a sticker from message if needed
        """
        # TODO: Very similar to processPhoto method. think about merging into one

        mimeType: Optional[str] = None
        localUrl: Optional[str] = None

        sticker = ensuredMessage.getBaseMessage().sticker
        if sticker is None:
            raise ValueError("Sticker not found")

        logger.debug(f"Processing sticker: {sticker}")
        ret = MediaProcessingInfo(
            id = sticker.file_unique_id,
            task = None,
            type = MessageType.STICKER,
        )
        # Sticker(..., emoji='😨', file_id='C...E', file_size=51444, file_unique_id='A...Q',
        # height=512, is_animated=True, is_video=False, set_name='SharkBoss',
        # thumbnail=PhotoSize(...), type=<StickerType.REGULAR>, width=512)

        # First check if we have the photo in the database already
        mediaAttachment = self.db.getMediaAttachment(ret.id)
        hasMediaAttachment = mediaAttachment is not None
        if mediaAttachment is not None:
            logger.debug(f"Sticker {ret.id} already in database: {mediaAttachment}")
            # logger.debug(repr(mediaAttachment))
            if mediaAttachment["media_type"] != MessageType.STICKER:
                raise RuntimeError(f"Media#{ret.id} already present in database and it is not an sticker but {mediaAttachment['media_type']}")

            # Only skip processing if Media in DB is in right status
            match MediaStatus(mediaAttachment["status"]):
                case MediaStatus.DONE:
                    ret.task = makeEmptyAsyncTask()
                    return ret

                case MediaStatus.PENDING:
                    try:
                        stickerDate = mediaAttachment["updated_at"]
                        if not isinstance(stickerDate, datetime.datetime):
                            logger.error(f"Sticker#{ret.id} updated_at is not a datetime: {type(stickerDate).__name__}({stickerDate})")
                            stickerDate = datetime.datetime.fromisoformat(stickerDate)
                        if utils.getAgeInSecs(stickerDate) > PROCESSING_TIMEOUT:
                            logger.warning(f"Sticker#{ret.id} already in database but in status {mediaAttachment['status']} and is too old ({stickerDate}), reprocessing it")
                        else:
                            ret.task = makeEmptyAsyncTask()
                            return ret
                    except Exception as e:
                        logger.error("Error during checking sticker age:")
                        logger.exception(e)

                case MediaStatus.NEW:
                    # We do not support processing non-image stickers for now
                    if mediaAttachment["mime_type"] is not None and not mediaAttachment["mime_type"].lower().startswith("image/"):
                        ret.task = makeEmptyAsyncTask()
                        return ret

                case _:
                    logger.debug(f"Sticker {ret.id} already in database but in wrong status: {mediaAttachment['status']}. Reprocessing it")
                    pass

        metadata = {
            "width": sticker.width,
            "height": sticker.height,
            "emoji": sticker.emoji,
            "set_name": sticker.set_name,
            "is_animated": sticker.is_animated,
            "is_video": sticker.is_video,
            "is_premium": sticker.premium_animation is not None,
        }

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        stickerData: Optional[bytes] = None

        if chatSettings[ChatSettingsKey.SAVE_IMAGES].toBool():
            # TODO do
            pass

        if chatSettings[ChatSettingsKey.PARSE_IMAGES].toBool():
            mediaStatus = MediaStatus.NEW
        else:
            mediaStatus = MediaStatus.DONE

        if hasMediaAttachment:
            self.db.updateMediaAttachment(
                fileUniqueId=ret.id,
                status=mediaStatus,
                metadata=json.dumps(metadata, ensure_ascii=False, default=str),
                mimeType=mimeType,
                localUrl=localUrl,
            )
        else:
            self.db.addMediaAttachment(
                fileUniqueId=ret.id,
                fileId=sticker.file_id,
                fileSize=sticker.file_size,
                mediaType=MessageType.STICKER,
                mimeType=mimeType,
                metadata=json.dumps(metadata, ensure_ascii=False, default=str),
                status=mediaStatus,
                localUrl=localUrl,
                prompt=None,
                description=None,
            )

        # Need to parse image content with LLM
        if chatSettings[ChatSettingsKey.PARSE_IMAGES].toBool():
            # Do not redownload file if it was downloaded already
            if stickerData is None:
                file = await context.bot.get_file(sticker)
                logger.debug(f"Sticker File info: {file}")
                stickerData = await file.download_as_bytearray()

            mimeType = magic.from_buffer(bytes(stickerData), mime=True)
            logger.debug(f"Sticker Mimetype: {mimeType}")

            self.db.updateMediaAttachment(
                fileUniqueId=ret.id,
                mimeType=mimeType,
            )

            if mimeType.lower().startswith("image/"):
                self.db.updateMediaAttachment(
                    fileUniqueId=ret.id,
                    status=MediaStatus.PENDING,
                )
                imagePrompt = chatSettings[ChatSettingsKey.PARSE_IMAGE_PROMPT].toStr()
                messages = [
                    ModelMessage(
                        role="system",
                        content=imagePrompt,
                    ),
                    ModelImageMessage(
                        role="user",
                        content=ensuredMessage.messageText,
                        image=stickerData,
                    )
                ]
                logger.debug(f"Asynchronously parsing sticker: {ret.id}")
                parseTask = asyncio.create_task(self._parseImage(ensuredMessage, ret.id, messages))
                # logger.debug(f"{ret.id} After Start")
                ret.task = parseTask
                await self.addQueueTask(parseTask)
                # logger.debug(f"{ret.id} After Queued")
            else:
                logger.debug(f"Sticker {ret.id} is not an image, skip parsing")

        if ret.task is None:
            ret.task = makeEmptyAsyncTask()

        return ret

    async def processImage(self, ensuredMessage: EnsuredMessage, context: ContextTypes.DEFAULT_TYPE, prompt: Optional[str] = None) -> MediaProcessingInfo:
        """
        Process a photo from message if needed
        """

        bestPhotoSize = ensuredMessage.getBaseMessage().photo[-1]
        mediaStatus = MediaStatus.NEW
        localUrl: Optional[str] = None
        mimeType: Optional[str] = None
        mediaType = MessageType.IMAGE

        logger.debug(f"Processing photo: {bestPhotoSize}")
        ret = MediaProcessingInfo(
            id = bestPhotoSize.file_unique_id,
            task = None,
            type = MessageType.IMAGE,
        )

        # First check if we have the photo in the database already
        mediaAttachment = self.db.getMediaAttachment(ret.id)
        hasMediaAttachment = mediaAttachment is not None
        if mediaAttachment is not None:
            logger.debug(f"Photo {ret.id} already in database")
            if mediaAttachment["media_type"] != MessageType.IMAGE:
                raise RuntimeError(f"Media attachment with id {ret.id} already present in database and it is not an image but {mediaAttachment['media_type']}")

            # Only skip processing if Media in DB is in right status
            match MediaStatus(mediaAttachment["status"]):
                case MediaStatus.DONE:
                    ret.task = makeEmptyAsyncTask()
                    return ret

                case MediaStatus.PENDING:
                    try:
                        mediaDate = mediaAttachment["updated_at"]
                        if not isinstance(mediaDate, datetime.datetime):
                            logger.error(f"Photo#{ret.id} attachment `updated_at` is not a datetime: {type(mediaDate).__name__}({mediaDate})")
                            mediaDate = datetime.datetime.fromisoformat(mediaDate)

                        if utils.getAgeInSecs(mediaDate) > PROCESSING_TIMEOUT:
                            logger.warning(f"Photo#{ret.id} already in database but in status {mediaAttachment['status']} and is too old ({mediaDate}), reprocessing it")
                        else:
                            ret.task = makeEmptyAsyncTask()
                            return ret
                    except Exception as e:
                        logger.error("Error during checking sticker age:")
                        logger.exception(e)

                case _:
                    logger.debug(f"Image {ret.id} already in database but in wrong status: {mediaAttachment['status']}. Reprocessing it")
                    pass

        metadata = {
            # Store metadata for best size
            "width": bestPhotoSize.width,
            "height": bestPhotoSize.height,
        }

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        photoData: Optional[bytes] = None

        if chatSettings[ChatSettingsKey.SAVE_IMAGES].toBool():
            # TODO do
            pass

        if chatSettings[ChatSettingsKey.PARSE_IMAGES].toBool():
            mediaStatus = MediaStatus.PENDING
        else:
            mediaStatus = MediaStatus.DONE

        if hasMediaAttachment:
            self.db.updateMediaAttachment(
                fileUniqueId=ret.id,
                status=mediaStatus,
                metadata=json.dumps(metadata, ensure_ascii=False, default=str),
                mimeType=mimeType,
                localUrl=localUrl,
                prompt=prompt,
            )
        else:
            self.db.addMediaAttachment(
                fileUniqueId=ret.id,
                fileId=bestPhotoSize.file_id,
                fileSize=bestPhotoSize.file_size,
                mediaType=mediaType,
                mimeType=mimeType,
                metadata=json.dumps(metadata, ensure_ascii=False, default=str),
                status=mediaStatus,
                localUrl=localUrl,
                prompt=prompt,
                description=None,
            )

        # Need to parse image content with LLM
        if chatSettings[ChatSettingsKey.PARSE_IMAGES].toBool():
            photoSize = bestPhotoSize
            optimalImageSize = chatSettings[ChatSettingsKey.OPTIMAL_IMAGE_SIZE].toInt()
            if optimalImageSize > 0:
                # Iterate over all photo sizes and find the best one (i.e. smallest, but, larger than optimalImageSize)
                for pSize in ensuredMessage.getBaseMessage().photo:
                    if pSize.width > optimalImageSize or pSize.height > optimalImageSize:
                        photoSize = pSize
                        break

            # Do not redownload file if it was downloaded already
            if photoData is None or photoSize != bestPhotoSize:
                file = await context.bot.get_file(photoSize)
                logger.debug(f"Photo File info: {file}")
                photoData = await file.download_as_bytearray()

            mimeType = magic.from_buffer(bytes(photoData), mime=True)
            logger.debug(f"Photo Mimetype: {mimeType}")

            self.db.updateMediaAttachment(
                fileUniqueId=ret.id,
                mimeType=mimeType,
            )

            imagePrompt = chatSettings[ChatSettingsKey.PARSE_IMAGE_PROMPT].toStr()
            messages = [
                ModelMessage(
                    role="system",
                    content=imagePrompt,
                ),
                ModelImageMessage(
                    role="user",
                    content=ensuredMessage.messageText,
                    image=photoData,
                )
            ]

            logger.debug(f"Asynchronously parsing image: {ret.id}")
            parseTask = asyncio.create_task(self._parseImage(ensuredMessage, ret.id, messages))
            logger.debug(f"{ret.id} After Start")
            ret.task = parseTask
            await self.addQueueTask(parseTask)
            logger.debug(f"{ret.id} After Queued")

        if ret.task is None:
            ret.task = makeEmptyAsyncTask()

        return ret

    ###
    # COMMANDS Handlers
    ###

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command."""
        user = update.effective_user
        if not user or not update.message:
            logger.error("User or message undefined")
            return

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

        ensuredMessage = EnsuredMessage.fromMessage(update.message)

        help_text = (
            "🤖 **Gromozeka Bot Help**\n\n"
            "**Commands:**\n"
            "/start - Welcome message and bot introduction\n"
            "/help - Show this help message\n"
            "/echo <message> - Echo your message back\n\n"
            "**Features:**\n"
            "• Message logging and statistics\n"
            "• Simple conversation handling\n\n"
            "Just send me any text message and I'll respond, dood!"
        )

        await self._sendMessage(
            ensuredMessage,
            context,
            messageText=help_text,
            saveMessage=False,
            tryParseInputJSON=False,
        )

    async def echo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /echo command."""
        if not update.message:
            logger.error("Message undefined")
            return
        ensuredMessage = EnsuredMessage.fromMessage(update.message)

        if context.args:
            echo_text = " ".join(context.args)
            await self._sendMessage(
                ensuredMessage,
                context,
                messageText=f"🔄 Echo: {echo_text}",
                saveMessage=False,
                tryParseInputJSON=False,
            )
        else:
            await self._sendMessage(
                ensuredMessage,
                context,
                messageText="Please provide a message to echo!\nUsage: /echo <your message>",
                saveMessage=False,
                tryParseInputJSON=False,
            )

    async def summary_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /[topic-]summary [<messages> <chunks> <chatId> <threadId>]command."""
        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        maxBatches: Optional[int] = None
        maxMessages: Optional[int] = None
        if context.args and len(context.args) > 0:
            try:
                maxMessages = int(context.args[0])
                if maxMessages < 1:
                    maxMessages = None

                maxBatches = int(context.args[1])
                if maxBatches < 1:
                    maxBatches = None
            except ValueError:
                logger.error(f"Invalid arguments: '{context.args[0:2]}' are not a valid number.")
            except IndexError:
                pass

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Failed to ensure message: {type(e).__name__}#{e}")
            return

        commandStr = ""
        for entity in message.entities:
            if entity.type == MessageEntityType.BOT_COMMAND:
                commandStr = ensuredMessage.messageText[entity.offset:entity.offset+entity.length]
                break

        logger.debug(f"Command string: {commandStr}")
        isTopicSummary = commandStr.startswith("/topic_summary")

        # Summary command print summary for whole chat.
        # Topic-summary prints summary for current topic, we threat default topic as 0
        threadId = None
        if isTopicSummary:
            threadId = ensuredMessage.threadId if ensuredMessage.threadId else 0

        chat = ensuredMessage.chat
        targetChatId = chat.id

        userName = ensuredMessage.user.username
        # Allow bot owners to ask for summarisation of any chat
        if userName and userName.lower() in self.botOwners and context.args and len(context.args) >= 3:
            try:
                targetChatId = int(context.args[2])
                threadId = int(context.args[3])
            except ValueError:
                logger.error(f"Invalid arguments: '{context.args[2:4]}' are not a valid number.")
            except IndexError:
                pass

        logger.debug(f"Getting summary for chat {targetChatId}, thread {threadId}, maxBatches {maxBatches}, maxMessages {maxMessages}")
        today = datetime.datetime.now(datetime.timezone.utc)
        today = today.replace(hour=0, minute=0, second=0, microsecond=0)

        messages = self.db.getChatMessagesSince(
            chatId=targetChatId,
            sinceDateTime=today if maxMessages is None else None,
            threadId=threadId,
            limit=maxMessages,
        )

        logger.debug(f"Messages: {messages}")
        chatSettings = self.getChatSettings(chatId=targetChatId)

        systemMessage = {
            "role": "system",
            "content": chatSettings[ChatSettingsKey.SUMMARY_PROMPT].toStr(),
        }
        parsedMessages = []

        for msg in reversed(messages):
            parsedMessages.append(
                {
                    "role": "user",
                    "content": await EnsuredMessage.formatDBChatMessageToLLM(self.db, msg, LLMMessageFormat.JSON),
                }
            )

        reqMessages = [systemMessage] + parsedMessages

        llmModel = chatSettings[ChatSettingsKey.SUMMARY_MODEL].toModel(self.llmManager)
        # TODO: Move to config or ask from model somehow
        maxTokens = llmModel.getInfo()["context_size"]
        tokensCount = llmModel.getEstimateTokensCount(reqMessages)

        # -256 or *0.9 to ensure everything will be ok
        batchesCount = tokensCount // max(maxTokens - 256, maxTokens * 0.9) + 1
        batchLength = len(parsedMessages) // batchesCount

        logger.debug(f"Summarisation: estimated total tokens: {tokensCount}, max tokens: {maxTokens}, messages count: {len(parsedMessages)}, batches count: {batchesCount}, batch length: {batchLength}")

        resMessages = []
        if not parsedMessages:
            resMessages.append("No messages to summarize")
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
                        resMessages.append(f"Error while running LLM for batch {startPos}:{startPos+currentBatchLen}: Batch has too many tokens ({tokensCount})")
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
                    mlRet = await llmModel.generateTextWithFallBack(
                        ModelMessage.fromDictList(reqMessages),
                        chatSettings[ChatSettingsKey.SUMMARY_FALLBACK_MODEL].toModel(
                            self.llmManager
                        ),
                    )
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
            await self._sendMessage(
                ensuredMessage,
                context,
                messageText=msg,
                tryParseInputJSON=False,
            )
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
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

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
            }
            replyText += f"**Модель: {modelName}**\n```{modelName}\n"
            for k, v in modelData.items():
                replyText += f"{modelKeyI18n.get(k, k)}: {v}\n"

            replyText += "```\n\n"

            if i % modelsPerMessage == (modelsPerMessage - 1):
                await self._sendMessage(
                    ensuredMessage,
                    context,
                    messageText=replyText,
                    saveMessage=False,
                    tryParseInputJSON=False,
                )
                replyText = ""
                time.sleep(0.5)

        if replyText:
            await self._sendMessage(
                ensuredMessage,
                context,
                messageText=replyText,
                saveMessage=False,
                tryParseInputJSON=False,
            )

    async def chat_settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /settings command."""
        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        ensuredMessage : Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
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
            await self._sendMessage(
                ensuredMessage,
                context,
                messageText="This command is only available in groups and supergroups for now.",
                saveMessage=False,
                tryParseInputJSON=False,
            )
            return

        resp = f"Настройки чата **#{chat.id}**:\n\n"
        chatSettings = self.getChatSettings(chat.id)
        for k, v in chatSettings.items():
            resp += f"`{k}`: ```{k}\n{v}\n```\n"

        await self._sendMessage(
            ensuredMessage,
            context,
            messageText=resp,
            saveMessage=False,
            tryParseInputJSON=False,
        )

    async def set_or_unset_chat_setting_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /set <key> <value> command."""
        logger.debug(f"Got set or unset command: {update}")

        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        ensuredMessage : Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        commandStr = ""
        for entity in message.entities:
            if entity.type == MessageEntityType.BOT_COMMAND:
                commandStr = ensuredMessage.messageText[entity.offset:entity.offset+entity.length]
                break

        logger.debug(f"Command string: {commandStr}")
        isSet = commandStr.startswith("/set")

        user = ensuredMessage.user
        chat = ensuredMessage.chat
        chatType = chat.type

        if chatType not in [Chat.GROUP, Chat.SUPERGROUP]:
            await self._sendMessage(
                    ensuredMessage,
                    context,
                    messageText="This command is only available in groups and supergroups for now.",
                    saveMessage=False,
                    tryParseInputJSON=False,
                )
            return

        if not user.username:
            await self._sendMessage(
                    ensuredMessage,
                    context,
                    messageText="You need to have a username to change chat settings.",
                    saveMessage=False,
                    tryParseInputJSON=False,
                )
            return

        if isSet and (not context.args or len(context.args) < 2):
            await self._sendMessage(
                    ensuredMessage,
                    context,
                    messageText="You need to specify a key and a value to change chat setting.",
                    saveMessage=False,
                    tryParseInputJSON=False,
                )
            return
        if not isSet and (not context.args or len(context.args) < 1):
            await self._sendMessage(
                    ensuredMessage,
                    context,
                    messageText="You need to specify a key to clear chat setting.",
                    saveMessage=False,
                    tryParseInputJSON=False,
                )
            return

        if not context.args:
            # It is impossible, actually as we have checked it before, but we do it to make linters happy
            raise ValueError("No args provided")

        chatSettings = self.getChatSettings(chat.id)
        adminAllowedChangeSettings = chatSettings[ChatSettingsKey.ADMIN_CAN_CHANGE_SETTINGS].toBool()

        allowedUsers = self.botOwners[:]
        if adminAllowedChangeSettings:
            for admin in await chat.get_administrators():
                logger.debug(f"Got admin for chat {chat.id}: {admin}")
                username = admin.user.username
                if username:
                    allowedUsers.append(username.lower())

        if user.username.lower() not in allowedUsers:
            await self._sendMessage(
                    ensuredMessage,
                    context,
                    messageText="You are not allowed to change chat settings.",
                    saveMessage=False,
                    tryParseInputJSON=False,
                )
            return

        key = context.args[0]
        if isSet:
            value = " ".join(context.args[1:])
            self.setChatSettings(chat.id, {key: value})
            await self._sendMessage(
                    ensuredMessage,
                    context,
                    messageText=f"Готово, теперь `{key}` = `{value}`",
                    saveMessage=False,
                    tryParseInputJSON=False,
                )
        else:
            self.unsetChatSetting(chat.id, key)
            await self._sendMessage(
                    ensuredMessage,
                    context,
                    messageText=f"Готово, теперь `{key}` сброшено в значение по умолчанию",
                    saveMessage=False,
                    tryParseInputJSON=False,
                )

    async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /test <suite> [<args>] command."""
        logger.debug(f"Got test command: {update}")

        message = update.message
        if not message:
            logger.error("Message undefined")
            return

        ensuredMessage : Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        user = ensuredMessage.user
        chat = ensuredMessage.chat

        if not context.args or len(context.args) < 1:
            await self._sendMessage(
                    ensuredMessage,
                    context,
                    messageText="You need to specify test suite.",
                    saveMessage=False,
                    tryParseInputJSON=False,
                )
            return

        if not user.username:
            await self._sendMessage(
                    ensuredMessage,
                    context,
                    messageText="You need to have a username to run tests.",
                    saveMessage=False,
                    tryParseInputJSON=False,
                )
            return

        allowedUsers = self.botOwners[:]

        if user.username.lower() not in allowedUsers:
            await self._sendMessage(
                    ensuredMessage,
                    context,
                    messageText="You are not allowed to run tests.",
                    saveMessage=False,
                    tryParseInputJSON=False,
                )
            return

        suite = context.args[0]

        match suite:
            case "long":
                iterationsCount = 10
                delay = 10
                if len(context.args) > 1:
                    try:
                        iterationsCount = int(context.args[1])
                    except ValueError as e:
                        await self._sendMessage(
                            ensuredMessage,
                            context,
                            messageText=f"Invalid iterations count. {e}",
                            saveMessage=False,
                            tryParseInputJSON=False,
                        )
                        pass
                if len(context.args) > 2:
                    try:
                        delay = int(context.args[2])
                    except ValueError as e:
                        await self._sendMessage(
                            ensuredMessage,
                            context,
                            messageText=f"Invalid delay. {e}",
                            saveMessage=False,
                            tryParseInputJSON=False,
                        )
                        pass

                for i in range(iterationsCount):
                    logger.debug(
                        f"Iteration {i} of {iterationsCount} (delay is {delay}) {context.args[3:]}"
                    )
                    await self._sendMessage(
                        ensuredMessage,
                        context,
                        messageText=f"Iteration {i}",
                        saveMessage=False,
                        tryParseInputJSON=False,
                        skipLogs=True,
                    )
                    await asyncio.sleep(delay)

            case _:
                await self._sendMessage(
                    ensuredMessage,
                    context,
                    messageText=f"Unknown test suite: {suite}.",
                    saveMessage=False,
                    tryParseInputJSON=False,
                )

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors."""
        logger.error(f"Unhandled exception while handling an update: {type(context.error).__name__}#{context.error}")
        logger.exception(context.error)

    async def handle_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle bot commands."""
        logger.debug(f"Handling bot command: {update}")
