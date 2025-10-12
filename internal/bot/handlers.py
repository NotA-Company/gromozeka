"""
Telegram bot command handlers for Gromozeka.
"""

import asyncio
import datetime
import json
import logging
import re

import random
import time
from typing import Any, Callable, Dict, List, Optional
import uuid

import requests
import magic

from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Update, Message, User
from telegram.constants import MessageEntityType, MessageLimit
from telegram.ext import ExtBot, ContextTypes
from telegram._files._basemedium import _BaseMedium
from telegram._utils.types import ReplyMarkup

from lib.ai.abstract import AbstractModel, LLMAbstractTool
from lib.ai.models import (
    LLMFunctionParameter,
    LLMParameterType,
    LLMToolFunction,
    ModelImageMessage,
    ModelMessage,
    ModelRunResult,
    ModelResultStatus,
)
from lib.ai.manager import LLMManager

from internal.database.wrapper import DatabaseWrapper
from internal.database.models import ChatInfoDict, ChatMessageDict, MediaStatus, MessageCategory, SpamReason

from lib.markdown import markdown_to_markdownv2
import lib.utils as utils
from .ensured_message import EnsuredMessage
from .models import (
    DelayedTask,
    DelayedTaskFunction,
    LLMMessageFormat,
    MessageType,
    MediaProcessingInfo,
)
from .chat_settings import ChatSettingsKey, ChatSettingsValue
from internal.bot import chat_settings

logger = logging.getLogger(__name__)

DUNNO_EMOJI = "🤷‍♂️"
TELEGRAM_MAX_MESSAGE_LENGTH = 4096
MAX_QUEUE_LENGTH = 32
MAX_QUEUE_AGE = 30 * 60  # 30 minutes
PROCESSING_TIMEOUT = 30 * 60  # 30 minutes
PRIVATE_CHAT_CONTEXT_LENGTH = 50
CHAT_ICON = "👥"
PRIVATE_ICON = "👤"


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

        self._isExiting = False

        # Init different defaults
        self.botOwners = [username.lower() for username in self.config.get("bot_owners", [])]

        botDefaults: Dict[ChatSettingsKey, ChatSettingsValue] = {
            k: ChatSettingsValue(v) for k, v in self.config.get("defaults", {}).items() if k in ChatSettingsKey
        }

        self.chatDefaults: Dict[ChatSettingsKey, ChatSettingsValue] = {
            k: ChatSettingsValue("") for k in ChatSettingsKey
        }

        self.chatDefaults.update({k: v for k, v in botDefaults.items() if k in ChatSettingsKey})

        # Init cache
        # TODO: Should I use something thread-safe? or just better
        self.cache: Dict[str, Dict[Any, Any]] = {
            "chats": {},
            "chatUsers": {},
            "users": {},
        }
        # Cache structure:
        # cache: Dict[str, Dict[str, Any] = {
        #     "chats": Dict[int, Any]= {
        #         "<chatId>": Dict[str, Any] = {
        #             "settings": Dict[ChatSettingsKey, ChatSettingsValue] = {...},
        #             "info": Dict[str, any] = {...},
        #             "topics": Dict[int, Any] = {
        #                 "<topicId>": Dict[str, Any] = {
        #                     "iconColor": Optional[int],
        #                     "customEmojiId": Optional[int],
        #                     "name": Optional[str],
        #                 },
        #             },
        #         },
        #     },
        #     "chatUsers": Dict[str, Any] = {
        #         "<chatId>:<userId>": Dict[str, Any] = {
        #             "data": Dict[str, str|List["str"]] = {...},
        #         },
        #     },
        #     "users": Dict[int, Any] = {
        #         <userId>: Dict[str, Any] = {
        #             "activeConfigureId": Dict[str, Any] = {...},
        #             "activeSummarizationId": Dict[str, Any] = {...},
        #         },
        #     },
        #  }

        self.asyncTasksQueue = asyncio.Queue()
        self.queueLastUpdated = time.time()

        self.delayedActionsQueue = asyncio.PriorityQueue()
        self._bot: Optional[ExtBot] = None

    async def initExit(self) -> None:
        self._isExiting = True
        await self._addDelayedTask(time.time(), DelayedTaskFunction.DO_EXIT, kwargs={}, skipDB=True)

    ###
    # Helpers for getting needed Models or Prompts
    ###
    def updateDefaults(self) -> None:
        pass

    ###
    # Chat settings Managenent
    ###

    def getChatSettings(
        self, chatId: Optional[int], returnDefault: bool = True
    ) -> Dict[ChatSettingsKey, ChatSettingsValue]:
        """Get the chat settings for the given chat."""
        if chatId is None:
            return self.chatDefaults.copy()

        if chatId not in self.cache["chats"]:
            self.cache["chats"][chatId] = {}

        if "settings" not in self.cache["chats"][chatId]:
            self.cache["chats"][chatId]["settings"] = {
                k: ChatSettingsValue(v) for k, v in self.db.getChatSettings(chatId).items()
            }

        if returnDefault:
            return {**self.chatDefaults, **self.cache["chats"][chatId]["settings"]}

        return self.cache["chats"][chatId]["settings"]

    def setChatSettings(self, chatId: int, settings: Dict[str, Any]) -> None:
        """Set the chat settings for the given chat."""
        if chatId not in self.cache["chats"]:
            self.cache["chats"][chatId] = {}

        for key, value in settings.items():
            _value = str(value)
            if isinstance(value, list):
                _value = ",".join(value)

            self.db.setChatSetting(chatId, key, _value)

        if "settings" in self.cache["chats"][chatId]:
            self.cache["chats"][chatId].pop("settings", None)

    def unsetChatSetting(self, chatId: int, key: str) -> None:
        """Set the chat settings for the given chat."""
        if chatId not in self.cache["chats"]:
            self.cache["chats"][chatId] = {}

        self.db.unsetChatSetting(chatId, key)

        if "settings" in self.cache["chats"][chatId]:
            self.cache["chats"][chatId].pop("settings", None)

    ###
    # User Data Management
    ###

    def getUserData(self, chatId: int, userId: int) -> Dict[str, str | List[str]]:
        """Get the user data for the given chat."""
        # TODO: Move to separate function
        userKey = f"{chatId}:{userId}"

        if userKey not in self.cache["chatUsers"]:
            self.cache["chatUsers"][userKey] = {}
        if "data" not in self.cache["chatUsers"][userKey]:
            userData = {k: json.loads(v) for k, v in self.db.getUserData(userId=userId, chatId=chatId).items()}
            self.cache["chatUsers"][userKey]["data"] = userData

        return self.cache["chatUsers"][userKey]["data"]

    def setUserData(
        self, chatId: int, userId: int, key: str, value: str | List[str], append: bool = False
    ) -> str | List[str]:
        """Set specific user data for the given chat."""
        # TODO: Move to separate function
        userKey = f"{chatId}:{userId}"

        userData = self.getUserData(chatId, userId)

        if key in userData and append:
            _data = userData[key]
            if isinstance(value, list):
                value = [str(v).strip() for v in value]
            else:
                value = [str(value).strip()]

            if isinstance(_data, list):
                userData[key] = _data + value
            else:
                userData[key] = [str(_data)] + value
        else:
            userData[key] = value

        self.cache["chatUsers"][userKey]["data"][key] = userData[key]
        self.db.addUserData(userId=userId, chatId=chatId, key=key, data=utils.jsonDumps(userData[key]))
        return userData[key]

    def _updateEMessageUserData(self, ensuredMessage: EnsuredMessage) -> None:
        ensuredMessage.setUserData(self.getUserData(ensuredMessage.chat.id, ensuredMessage.user.id))

    ###
    # Different helpers
    ###

    async def _isAdmin(self, user: User, chat: Optional[Chat] = None, allowBotOwners: bool = True) -> bool:
        """Check if the user is an admin (or bot owner)."""
        # If chat is None, then we are checking if it's bot owner
        username = user.username
        if username is None:
            return False
        username = username.lower()

        if allowBotOwners and username in self.botOwners:
            return True

        if chat is not None:
            for admin in await chat.get_administrators():
                # logger.debug(f"Got admin for chat {chat.id}: {admin}")
                if admin.user.username and username == admin.user.username.lower():
                    return True

        return False

    async def addTaskToAsyncedQueue(self, task: asyncio.Task) -> None:
        """Add a task to the queue."""
        if self.asyncTasksQueue.qsize() > MAX_QUEUE_LENGTH:
            logger.info("Queue is full, processing oldest task")
            oldTask = await self.asyncTasksQueue.get()
            if not isinstance(oldTask, asyncio.Task):
                logger.error(f"Task {oldTask} is not a task, but a {type(oldTask)}")
            else:
                await oldTask
            self.asyncTasksQueue.task_done()

        await self.asyncTasksQueue.put(task)
        self.queueLastUpdated = time.time()

    async def _processBackgroundTasks(self, forceProcessAll: bool = False) -> None:
        """Process background tasks."""

        if self.asyncTasksQueue.empty():
            return

        if (not forceProcessAll) and (self.queueLastUpdated + MAX_QUEUE_AGE > time.time()):
            return

        if forceProcessAll:
            logger.info("Processing background tasks queue due to forceProcessAll=True")
        else:
            logger.info(f"Processing queue due to age ({MAX_QUEUE_AGE})")

        # TODO: Do it properly
        # Little hack to avoid concurency in processing queue
        self.queueLastUpdated = time.time()
        # TODO: Process only existing elements to avoid endless processing new ones

        try:
            while True:
                task = await self.asyncTasksQueue.get_nowait()
                if not isinstance(task, asyncio.Task):
                    logger.error(f"Task {task} is not a task, but a {type(task)}")
                else:
                    try:
                        logger.debug(f"Awaiting task {task}...")
                        await task
                    except Exception as e:
                        logger.error(f"Error in background task: {e}")
                        logger.exception(e)

                self.asyncTasksQueue.task_done()
        except asyncio.QueueEmpty:
            logger.info("All background tasks were processed")
        except Exception as e:
            logger.error(f"Error in background task processing: {e}")
            logger.exception(e)

    async def initDelayedScheduler(self, bot: ExtBot) -> None:
        self._bot = bot

        tasks = self.db.getPendingDelayedTasks()
        for task in tasks:
            await self._addDelayedTask(
                delayedUntil=float(task["delayed_ts"]),
                function=DelayedTaskFunction(task["function"]),
                kwargs=json.loads(task["kwargs"]),
                taskId=task["id"],
                skipDB=True,
            )
            logger.info(f"Restored delayed task: {task}")

        # Add background tasks processing
        await self._addDelayedTask(
            time.time() + 600, DelayedTaskFunction.PROCESS_BACKGROUND_TASKS, kwargs={}, skipDB=True
        )

        await self._processDelayedQueue()

    async def _processDelayedQueue(self) -> None:
        while True:
            try:
                # logger.debug("_pDQ(): Iteration...")
                delayedTask = await self.delayedActionsQueue.get()

                if not isinstance(delayedTask, DelayedTask):
                    self.delayedActionsQueue.task_done()
                    logger.error(
                        f"Got wrong element from delayedActionsQueue: {type(delayedTask).__name__}#{repr(delayedTask)}"
                    )
                    continue

                if delayedTask.delayedUntil > time.time():
                    self.delayedActionsQueue.task_done()
                    await self.delayedActionsQueue.put(delayedTask)
                    # TODO: Add some configured delay, maybe
                    await asyncio.sleep(min(10, delayedTask.delayedUntil - time.time()))
                    continue

                logger.debug(f"_pDQ(): Got {delayedTask}...")

                match delayedTask.function:
                    case DelayedTaskFunction.SEND_MESSAGE:
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
                        await self._sendMessage(
                            replyToMessage=ensuredMessage,
                            messageText=kwargs["messageText"],
                            messageCategory=kwargs["messageCategory"],
                        )
                        pass
                    case DelayedTaskFunction.DELETE_MESSAGE:
                        kwargs = delayedTask.kwargs
                        if self._bot is not None:
                            await self._bot.delete_message(chat_id=kwargs["chatId"], message_id=kwargs["messageId"])
                        else:
                            logger.error(
                                "Bot is not initialized, can't delete message "
                                f"{kwargs['messageId']} in chat {kwargs['chatId']}"
                            )
                    case DelayedTaskFunction.DO_EXIT:
                        logger.info("got doExit function, processing backgroundTask if any...")
                        await self._processBackgroundTasks(True)

                    case DelayedTaskFunction.PROCESS_BACKGROUND_TASKS:
                        await self._processBackgroundTasks()
                        await self._addDelayedTask(
                            time.time() + 600, DelayedTaskFunction.PROCESS_BACKGROUND_TASKS, kwargs={}, skipDB=True
                        )

                    case _:
                        logger.error(f"Unsupported function type: {delayedTask.function} in delayed task {delayedTask}")

                self.db.updateDelayedTask(delayedTask.taskId, True)
                self.delayedActionsQueue.task_done()
                if delayedTask.function == DelayedTaskFunction.DO_EXIT or self._isExiting:
                    logger.debug("doExit(), exiting...")
                    return

            except RuntimeError as e:
                logger.error(f"Error in delayed task processor: {e}")
                if str(e) == "Event loop is closed":
                    break

            except Exception as e:
                logger.error(f"Error in delayed task processor: {e}")
                logger.exception(e)

    async def _addDelayedTask(
        self,
        delayedUntil: float,
        function: DelayedTaskFunction,
        kwargs: Dict[str, Any],
        taskId: Optional[str] = None,
        skipDB: bool = False,
    ) -> None:
        """Add delayed task"""
        if taskId is None:
            taskId = str(uuid.uuid4())

        task = DelayedTask(taskId, delayedUntil, function, kwargs)
        # logger.debug(f"Adding delayed task: {task}")
        await self.delayedActionsQueue.put(task)
        if not skipDB:
            self.db.addDelayedTask(
                taskId=taskId,
                function=function,
                kwargs=utils.jsonDumps(kwargs, ensure_ascii=False, default=str),
                delayedTS=int(delayedUntil),
            )

        logger.debug(f"Added delayed task: {task}, skipDB={skipDB}")

    async def _sendMessage(
        self,
        replyToMessage: EnsuredMessage,
        messageText: Optional[str] = None,
        addMessagePrefix: str = "",
        photoData: Optional[bytes] = None,
        photoCaption: Optional[str] = None,
        sendMessageKWargs: Optional[Dict[str, Any]] = None,
        tryMarkdownV2: bool = True,
        tryParseInputJSON: bool = False,
        sendErrorIfAny: bool = True,
        skipLogs: bool = False,
        mediaPrompt: Optional[str] = None,
        messageCategory: MessageCategory = MessageCategory.BOT,
        replyMarkup: Optional[ReplyMarkup] = None,
    ) -> Optional[Message]:
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

        replyKwargs = sendMessageKWargs.copy()
        replyKwargs.update(
            {
                "reply_to_message_id": replyToMessage.messageId,
                "message_thread_id": replyToMessage.threadId,
                "reply_markup": replyMarkup,
            }
        )

        try:
            if photoData is not None:
                # Send photo
                replyKwargs.update(
                    {
                        "photo": photoData,
                    }
                )

                if tryMarkdownV2 and photoCaption is not None:
                    try:
                        messageTextParsed = markdown_to_markdownv2(addMessagePrefix + photoCaption)
                        # logger.debug(f"Sending MarkdownV2: {replyText}")
                        replyMessage = await message.reply_photo(
                            caption=messageTextParsed,
                            parse_mode="MarkdownV2",
                            **replyKwargs,
                        )
                    except Exception as e:
                        logger.error(f"Error while sending MarkdownV2 reply to message: {type(e).__name__}#{e}")
                        # Probably error in markdown formatting, fallback to raw text

                if replyMessage is None:
                    _photoCaption = photoCaption if photoCaption is not None else ""
                    replyMessage = await message.reply_photo(caption=addMessagePrefix + _photoCaption, **replyKwargs)

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
                            logger.warning(f"No text field found in json reply, fallback to text: {jsonReply}")
                            raise ValueError("No text field found in json reply")
                    except Exception as e:
                        logger.debug(f"Error while parsing LLM reply, assume it's text: {type(e).__name__}#{e}")

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
                        logger.error(f"Error while sending MarkdownV2 reply to message: {type(e).__name__}#{e}")
                        # Probably error in markdown formatting, fallback to raw text

                if replyMessage is None:
                    replyMessage = await message.reply_text(text=addMessagePrefix + messageText, **replyKwargs)

            try:
                if replyMessage is None:
                    raise ValueError("No reply message")

                if not skipLogs:
                    logger.debug(f"Sent message: {replyMessage}")

                # Save message
                ensuredReplyMessage = EnsuredMessage.fromMessage(replyMessage)
                if addMessagePrefix:
                    replyText = ensuredReplyMessage.messageText
                    if replyText.startswith(addMessagePrefix):
                        replyText = replyText[len(addMessagePrefix) :]
                        ensuredReplyMessage.messageText = replyText
                if replyMessage.photo:
                    media = await self.processImage(ensuredReplyMessage, mediaPrompt)
                    ensuredReplyMessage.setMediaProcessingInfo(media)

                if isGroupChat or isPrivate:
                    self._saveChatMessage(ensuredReplyMessage, messageCategory=messageCategory)
                else:
                    raise ValueError("Unknown chat type")

            except Exception as e:
                logger.error(f"Error while saving chat message: {type(e).__name__}#{e}")
                logger.exception(e)
                # Message was sent, so return True anyway
                return replyMessage

        except Exception as e:
            logger.error(f"Error while sending message: {type(e).__name__}#{e}")
            logger.exception(e)
            if sendErrorIfAny:
                await message.reply_text(
                    f"Error while sending message: {type(e).__name__}#{e}",
                    reply_to_message_id=replyToMessage.messageId,
                )
            return None

        return replyMessage

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

        return await self._addDelayedTask(delayedUntil=delayedUntil, function=functionName, kwargs=kwargs)

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

        async def generateAndSendImage(image_prompt: str, image_description: Optional[str] = None, **kwargs) -> str:
            logger.debug(
                f"Generating image: {image_prompt}. Image description: {image_description}, "
                f"mcID: {ensuredMessage.chat.id}:{ensuredMessage.messageId}"
            )
            imageLLM = chatSettings[ChatSettingsKey.IMAGE_GENERATION_MODEL].toModel(self.llmManager)
            fallbackImageLLM = chatSettings[ChatSettingsKey.IMAGE_GENERATION_FALLBACK_MODEL].toModel(self.llmManager)

            mlRet = await imageLLM.generateImageWithFallBack([ModelMessage(content=image_prompt)], fallbackImageLLM)
            logger.debug(
                f"Generated image Data: {mlRet} for mcID: " f"{ensuredMessage.chat.id}:{ensuredMessage.messageId}"
            )
            if mlRet.status != ModelResultStatus.FINAL:
                ret = await self._sendMessage(
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
            ret = await self._sendMessage(
                ensuredMessage,
                photoData=mlRet.mediaData,
                photoCaption=image_description,
                mediaPrompt=image_prompt,
                addMessagePrefix=imgAddPrefix,
            )

            return utils.jsonDumps({"done": ret is not None})

        async def getUrlContent(url: str, **kwargs) -> str:
            # TODO: Check if content is text content
            return str(requests.get(url).content)

        async def setUserData(key: str, data: str, append: bool = False, **kwargs) -> str:
            newData = self.setUserData(
                chatId=ensuredMessage.chat.id, userId=ensuredMessage.user.id, key=key, value=data, append=append
            )
            return utils.jsonDumps({"done": True, "key": key, "data": newData})

        tools: Dict[str, LLMAbstractTool] = {}
        functions: Dict[str, Callable] = {
            "get_url_content": getUrlContent,
            "generate_and_send_image": generateAndSendImage,
            "add_user_data": setUserData,
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
                description=(
                    "Generate and send an image. ALWAYS use it if user ask to "
                    "generate/paint/draw an image/picture/photo"
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
                function=functions["generate_and_send_image"],
            )
            tools["add_user_data"] = LLMToolFunction(
                name="add_user_data",
                description=(
                    "Add some data/knowledge about user, sent last message. "
                    "Use it in following cases:\n"
                    "1. User asked to learn/remember something about him/her.\n"
                    "2. You learned new information about user "
                    "(e.g., real name, birth dare, what he like, etc).\n"
                    "3. You want to remember something relating to user.\n"
                    "4. There is some new information, you didn't know before.\n"
                    "5. When you needs to store information related to the user "
                    "to improve interaction quality (e.g., remembering formatting preferences, "
                    "command usage frequency, communication style).\n"
                    "6. When you receives confirmation of information from the user "
                    "(e.g., the user confirms their email address, phone number, or other contact details)."
                    "7. When you analyzes user behavior and makes conclusions that could be helpful for "
                    "personalization (e.g., determining user's active hours, preferred discussion topics)."
                    "8. When user provides information that could be used to improve the service "
                    "(e.g., feedback, suggestions, feature improvement ideas)."
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
                function=functions["add_user_data"],
            )

        ret: Optional[ModelRunResult] = None
        toolsUsed = False
        while True:
            ret = await model.generateTextWithFallBack(
                messages, fallbackModel=fallbackModel, tools=list(tools.values())
            )
            logger.debug(f"LLM returned: {ret} for mcID: {ensuredMessage.chat.id}:{ensuredMessage.messageId}")
            if ret.status == ModelResultStatus.TOOL_CALLS:
                toolsUsed = True
                newMessages = [ret.toModelMessage()]

                for toolCall in ret.toolCalls:
                    newMessages.append(
                        ModelMessage(
                            role="tool",
                            content=utils.jsonDumps(
                                await functions[toolCall.name](**toolCall.parameters),
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

    def _getChatInfo(self, chatId: int) -> Optional[ChatInfoDict]:
        """Get Chat info from cache or DB"""

        if chatId not in self.cache["chats"]:
            self.cache["chats"][chatId] = {}
        if "info" not in self.cache["chats"][chatId]:
            self.cache["chats"][chatId]["info"] = self.db.getChatInfo(chatId)

        return self.cache["chats"][chatId]["info"]

    def _updateChatInfo(self, chat: Chat) -> None:
        """Update Chat info. Do not save it to DB if it is in cache and wasn't changed"""

        chatId = chat.id

        if chatId not in self.cache["chats"]:
            self.cache["chats"][chatId] = {}
        if "info" not in self.cache["chats"][chatId]:
            self.cache["chats"][chatId]["info"] = {}

        cachedInfo = self.cache["chats"][chatId]["info"]

        if any(
            [
                chat.title != cachedInfo.get("title", None),
                chat.username != cachedInfo.get("username", None),
                chat.is_forum != cachedInfo.get("is_forum", None),
                chat.type != cachedInfo.get("type", None),
            ]
        ):
            cachedInfo = {
                "chat_id": chat.id,
                "title": chat.title,
                "username": chat.username,
                "is_forum": chat.is_forum,
                "type": chat.type,
            }
            self.cache["chats"][chatId]["info"] = cachedInfo
            self.db.addChatInfo(chatId, type=chat.type, title=chat.title, username=chat.username, isForum=chat.is_forum)

    def _updateTopicInfo(
        self,
        chatId: int,
        topicId: Optional[int],
        iconColor: Optional[int] = None,
        customEmojiId: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        """Update Chat info. Do not save it to DB if it is in cache and wasn't changed"""
        # logger.debug(
        #    f"Updating topic info for chatId: {chatId}, "
        #    f"topicId: {topicId}, iconColor: {iconColor}, "
        #    f"customEmojiId: {customEmojiId}, name: {name}"
        # )

        if topicId is None:
            topicId = 0

        if chatId not in self.cache["chats"]:
            self.cache["chats"][chatId] = {}
        if "topics" not in self.cache["chats"][chatId]:
            self.cache["chats"][chatId]["topics"] = {}
        if topicId not in self.cache["chats"][chatId]["topics"]:
            self.cache["chats"][chatId]["topics"][topicId] = {}

        cachedInfo: Dict[str, Any] = self.cache["chats"][chatId]["topics"][topicId]

        if any(
            [
                not cachedInfo,
                iconColor != cachedInfo.get("iconColor", None),
                customEmojiId != cachedInfo.get("customEmojiId", None),
                name != cachedInfo.get("name", None),
            ]
        ):
            cachedInfo = {
                "iconColor": iconColor,
                "customEmojiId": customEmojiId,
                "name": name,
            }
            self.cache["chats"][chatId]["topics"][topicId] = cachedInfo
            logger.debug(
                f"Saving topic info to DB for chatId: {chatId}, "
                f"topicId: {topicId}, iconColor: {iconColor}, "
                f"customEmojiId: {customEmojiId}, name: {name}"
            )
            self.db.updateChatTopicInfo(
                chatId=chatId,
                topicId=topicId,
                iconColor=iconColor,
                customEmojiId=customEmojiId,
                topicName=name,
            )

    def _saveChatMessage(self, message: EnsuredMessage, messageCategory: MessageCategory) -> bool:
        """Save a chat message to the database."""
        chat = message.chat
        sender = message.sender

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
            )
            if parentMsg:
                rootMessageId = parentMsg["root_message_id"]

        self._updateChatInfo(chat)

        # TODO: Actually topic name and emoji could be changed after that
        # but currently we have no way to know it (except of see
        # https://docs.python-telegram-bot.org/en/stable/telegram.forumtopicedited.html )
        # Think about it later
        if message.isTopicMessage:
            repliedMessage = message.getBaseMessage().reply_to_message
            if repliedMessage and repliedMessage.forum_topic_created:
                self._updateTopicInfo(
                    chatId=message.chat.id,
                    topicId=message.threadId,
                    iconColor=repliedMessage.forum_topic_created.icon_color,
                    customEmojiId=repliedMessage.forum_topic_created.icon_custom_emoji_id,
                    name=repliedMessage.forum_topic_created.name,
                )
        else:
            self._updateTopicInfo(chatId=message.chat.id, topicId=message.threadId)

        self.db.updateChatUser(
            chatId=chat.id,
            userId=sender.id,
            username=sender.username,
            fullName=sender.name,
        )

        self.db.saveChatMessage(
            date=message.date,
            chatId=chat.id,
            userId=sender.id,
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
            await self._sendMessage(
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
                    await self._sendMessage(
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
            await self._sendMessage(
                ensuredMessage,
                messageText=lmRetText,
                addMessagePrefix=addPrefix,
                tryParseInputJSON=llmMessageFormat == LLMMessageFormat.JSON,
            )
            is not None
        )

    async def _doSummarization(
        self,
        ensuredMessage: EnsuredMessage,
        chatId: int,
        threadId: Optional[int],
        chatSettings: Dict[ChatSettingsKey, ChatSettingsValue],
        sinceDT: Optional[datetime.datetime] = None,
        tillDT: Optional[datetime.datetime] = None,
        maxMessages: Optional[int] = None,
        summarizationPrompt: Optional[str] = None,
        useCache: bool = True,
    ) -> None:
        """Do summarisation and send as response to provided message"""

        if sinceDT is None and maxMessages is None:
            raise ValueError("one of sinceDT or maxMessages MUST be not None")

        messages = self.db.getChatMessagesSince(
            chatId=chatId,
            sinceDateTime=sinceDT if maxMessages is None else None,
            tillDateTime=tillDT if maxMessages is None else None,
            threadId=threadId,
            limit=maxMessages,
            messageCategory=[MessageCategory.USER, MessageCategory.BOT],
        )

        logger.debug(f"Messages: {messages}")

        if summarizationPrompt is None:
            summarizationPrompt = chatSettings[ChatSettingsKey.SUMMARY_PROMPT].toStr()

        if useCache and len(messages) > 1:
            cache = self.db.getChatSummarization(
                chatId=chatId,
                topicId=None,
                firstMessageId=messages[-1]["message_id"],
                lastMessageId=messages[0]["message_id"],
                prompt=summarizationPrompt,
            )
            if cache is not None:
                resMessages = json.loads(cache["summary"])
                for msg in resMessages:
                    await self._sendMessage(
                        ensuredMessage,
                        messageText=msg,
                        messageCategory=MessageCategory.BOT_SUMMARY,
                    )
                    time.sleep(1)
                return

        systemMessage = {
            "role": "system",
            "content": summarizationPrompt,
        }
        parsedMessages = []

        for msg in reversed(messages):
            parsedMessages.append(
                {
                    "role": "user",
                    "content": await EnsuredMessage.fromDBChatMessage(msg).formatForLLM(
                        self.db, LLMMessageFormat.JSON, stripAtsign=True
                    ),
                }
            )

        reqMessages = [systemMessage] + parsedMessages

        llmModel = chatSettings[ChatSettingsKey.SUMMARY_MODEL].toModel(self.llmManager)
        maxTokens = llmModel.getInfo()["context_size"]
        tokensCount = llmModel.getEstimateTokensCount(reqMessages)

        # -256 or *0.9 to ensure everything will be ok
        batchesCount = tokensCount // max(maxTokens - 256, maxTokens * 0.9) + 1
        batchLength = len(parsedMessages) // batchesCount

        logger.debug(
            f"Summarization: estimated total/max tokens: {tokensCount}/{maxTokens}. "
            f"Messages count: {len(parsedMessages)}, batches count/length: "
            f"{batchesCount}/{batchLength}"
        )

        resMessages = []
        if not parsedMessages:
            resMessages.append("No messages to summarize")
        startPos: int = 0

        fallbackPrefix = chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr()

        # Summarise each chunk of messages
        while startPos < len(parsedMessages):
            currentBatchLen = int(min(batchLength, len(parsedMessages) - startPos))
            batchSummarized = False
            while not batchSummarized:
                tryMessages = parsedMessages[startPos : startPos + currentBatchLen]
                reqMessages = [systemMessage] + tryMessages
                tokensCount = llmModel.getEstimateTokensCount(reqMessages)
                if tokensCount > maxTokens:
                    if currentBatchLen == 1:
                        resMessages.append(
                            f"Error while running LLM for batch {startPos}:{startPos + currentBatchLen}: "
                            f"Batch has too many tokens ({tokensCount})"
                        )
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
                        chatSettings[ChatSettingsKey.SUMMARY_FALLBACK_MODEL].toModel(self.llmManager),
                    )
                    logger.debug(f"LLM Response: {mlRet}")
                except Exception as e:
                    logger.error(  # type: ignore
                        f"Error while running LLM for batch {startPos}:{startPos + currentBatchLen}: "
                        f"{type(e).__name__}#{e}"
                    )
                    resMessages.append(
                        f"Error while running LLM for batch {startPos}:{startPos + currentBatchLen}: {type(e).__name__}"
                    )
                    break

                respText = mlRet.resultText
                if mlRet.isFallback:
                    respText = f"{fallbackPrefix} {respText}"
                resMessages.append(mlRet.resultText)

            startPos += currentBatchLen

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

        if useCache and len(messages) > 1:
            self.db.addChatSummarization(
                chatId=chatId,
                topicId=threadId,
                firstMessageId=messages[-1]["message_id"],
                lastMessageId=messages[0]["message_id"],
                prompt=summarizationPrompt,
                summary=utils.jsonDumps(resMessages),
            )

        for msg in resMessages:
            await self._sendMessage(
                ensuredMessage,
                messageText=msg,
                messageCategory=MessageCategory.BOT_SUMMARY,
            )
            time.sleep(1)

    ###
    # SPAM Handling
    ###

    async def checkSpam(self, ensuredMessage: EnsuredMessage) -> bool:
        """Check if message is spam."""

        if ensuredMessage.getBaseMessage().is_automatic_forward:
            # https://docs.python-telegram-bot.org/en/stable/telegram.message.html#telegram.Message.is_automatic_forward
            # It's a automatic forward from linked Channel. Its not spam.
            return False

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)

        userInfo = self.db.getChatUser(chatId=ensuredMessage.chat.id, userId=ensuredMessage.user.id)
        if not userInfo:
            logger.debug(f"userInfo for {ensuredMessage} is null, assume it's first user message")
            userInfo = {
                "messages_count": 1,
            }

        userMessages = userInfo["messages_count"]
        maxCheckMessages = chatSettings[ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES].toInt()
        if maxCheckMessages != 0 and userMessages > maxCheckMessages:
            # User has more message than limit, assume it isn't spammer
            return False

        logger.debug(f"SPAM CHECK: {userMessages} < {maxCheckMessages}, checking message for spam ({ensuredMessage})")

        spamScore = 0.0

        # Check if for last 10 messages there are more same messages than different ones:
        userMessages = self.db.getChatMessagesByUser(
            chatId=ensuredMessage.chat.id, userId=ensuredMessage.user.id, limit=10
        )
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

        # TODO: Add some Bayes filter

        banTreshold = chatSettings[ChatSettingsKey.SPAM_BAN_TRESHOLD].toFloat()
        warnTreshold = chatSettings[ChatSettingsKey.SPAM_WARN_TRESHOLD].toFloat()

        if spamScore > banTreshold:
            logger.info(f"SPAM: spamScore: {spamScore} > {banTreshold} {ensuredMessage.getBaseMessage()}")
            userName = ensuredMessage.user.full_name or ensuredMessage.user.username
            banMessage = await self._sendMessage(
                ensuredMessage,
                messageText=f"Пользователь [{userName}](tg://user?id={ensuredMessage.user.id})"
                " заблокирован за спам.\n"
                f"(Вероятность: {spamScore}, порог: {banTreshold})\n"
                "(Данное сообщение будет удалено в течение минуты)",
                messageCategory=MessageCategory.BOT_SPAM_NOTIFICATION,
            )
            if banMessage is not None:
                await self._addDelayedTask(
                    time.time() + 60,
                    DelayedTaskFunction.DELETE_MESSAGE,
                    kwargs={"messageId": banMessage.message_id, "chatId": banMessage.chat_id},
                    taskId=f"del-{banMessage.chat_id}-{banMessage.message_id}",
                )
            else:
                logger.error("Wasn't been able to send SPAM notification")
            await self.markAsSpam(message=ensuredMessage.getBaseMessage(), reason=SpamReason.AUTO, score=spamScore)
            return True
        elif spamScore > warnTreshold:
            logger.info(f"Possible SPAM: spamScore: {spamScore} > {warnTreshold} {ensuredMessage.getBaseMessage()}")
            await self._sendMessage(
                ensuredMessage,
                messageText=f"Возможно спам (Вероятность: {spamScore}, порог: {warnTreshold})\n"
                "(Когда-нибудь тут будут кнопки спам\\не спам)",
                messageCategory=MessageCategory.BOT_SPAM_NOTIFICATION,
            )
            # TODO: Add SPAM/Not-SPAM buttons, for non-spam also need to add ham-table for studying
        else:
            logger.debug(f"Not SPAM: spamScore: {spamScore} < {warnTreshold} {ensuredMessage}")

        return False

    async def markAsSpam(self, message: Message, reason: SpamReason, score: Optional[float] = None):
        """Delete spam message, ban user and save message to spamDB"""
        chatSettings = self.getChatSettings(message.chat_id)
        bot = message.get_bot()

        logger.debug(f"handling spam message: {message}. Reason: {reason}")

        chatId = message.chat_id
        userId = message.from_user.id if message.from_user is not None else 0

        if message.from_user is not None:
            if await self._isAdmin(user=message.from_user, chat=message.chat):
                # It is admin, do nothing
                logger.warning(f"Tried to mark Admin {message.from_user} as SPAM")
                await self._sendMessage(
                    EnsuredMessage.fromMessage(message),
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
                    logger.warning(f"Tried to mark old user {message.from_user} as SPAM")
                    await self._sendMessage(
                        EnsuredMessage.fromMessage(message),
                        messageText="Алярм! Попытка представить честного пользователя спаммером",
                        messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    )
                    return

        self.db.addSpamMessage(
            chatId=chatId,
            userId=userId,
            messageId=message.message_id,
            messageText=str(message.text),
            spamReason=reason,
            score=score if score is not None else 0,
        )

        await bot.delete_message(chat_id=chatId, message_id=message.message_id)
        logger.debug("Deleted spam message")
        if message.from_user is not None:
            await bot.ban_chat_member(chat_id=chatId, user_id=userId, revoke_messages=True)
            logger.debug(f"Banned user {message.from_user} in chat {message.chat}")
            if chatSettings[ChatSettingsKey.SPAM_DELETE_ALL_USER_MESSAGES].toBool():
                userMessages = self.db.getChatMessagesByUser(
                    chatId=chatId,
                    userId=userId,
                    limit=10,  # Do not delete more that 10 messages
                )
                logger.debug(f"Trying to delete more user messages: {userMessages}")
                messageIds: List[int] = []
                for msg in userMessages:
                    if msg["message_id"] != message.message_id:
                        messageIds.append(msg["message_id"])

                try:
                    if messageIds:
                        await bot.delete_messages(chat_id=chatId, message_ids=messageIds)
                except Exception as e:
                    logger.error("Failed during deleteing spam message:")
                    logger.exception(e)
        else:
            logger.debug("message.from_user is None")

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
                if update.effective_user is not None and update.message is not None and update.message.text is not None:
                    user = update.effective_user
                    userId = user.id
                    messageText = update.message.text
                    activeConfigureId = self.cache["users"].get(userId, {}).get("activeConfigureId", None)
                    if activeConfigureId is not None:
                        await self._handle_chat_configuration(
                            data={
                                "a": "sv",
                                "c": activeConfigureId["chatId"],
                                "k": ChatSettingsKey(activeConfigureId["key"]).getId(),
                                "v": messageText,
                            },
                            message=activeConfigureId["message"],
                            user=user,
                        )
                        return

                    activeSummarizationId = self.cache["users"].get(userId, {}).get("activeSummarizationId", None)
                    if activeSummarizationId is not None:
                        data = activeSummarizationId.copy()
                        data.pop("message", None)
                        k = data.pop("k", None)
                        match k:
                            case 1:
                                try:
                                    data["m"] = int(messageText.strip())
                                except Exception as e:
                                    logger.error(f"Not int: {messageText}")
                                    logger.exception(e)
                            case 2:
                                data["p"] = messageText
                            case _:
                                logger.error(f"Wrong K in data {activeSummarizationId}")
                        await self._handle_summarization(
                            data=data,
                            message=activeSummarizationId["message"],
                            user=user,
                        )
                        return

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

    async def handle_chat_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.debug(f"Handling group message: {update}")

        message = update.message
        if not message:
            # Not new message, ignore
            logger.warning(f"Message undefined in {update}")
            return

        ensuredMessage: Optional[EnsuredMessage] = None
        try:
            ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"Error while ensuring message: {e}")
            return

        self._updateEMessageUserData(ensuredMessage)

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)

        if chatSettings[ChatSettingsKey.DETECT_SPAM].toBool():
            if await self.checkSpam(ensuredMessage):
                return

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
                logger.error(f"Unsupported message type: {ensuredMessage.messageType}")
                # return

        if not self._saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER):
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

        myUserName = "@" + context.bot.username.lower()
        messageText = ensuredMessage.messageText
        mentionedAtBegin = False
        mentionedMe = False
        mentionedByNick = False

        for entity in message.entities:
            if entity.type == MessageEntityType.MENTION:
                mentionText = messageText[entity.offset : entity.offset + entity.length]

                # Проверяем, совпадает ли упоминание с именем бота
                if mentionText.lower() == f"{myUserName}":
                    mentionedMe = True
                    break

        # Remove leading @username from messageText if any
        if messageText.lower().startswith(myUserName):
            messageText = messageText[len(myUserName) :].lstrip()
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
                messageText = messageText[len(mention) :].lstrip("\t\n\r ,.:")
                mentionedByNick = True
                break

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
                await self._sendMessage(
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
            response = DUNNO_EMOJI
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
                        response = DUNNO_EMOJI

                return (
                    await self._sendMessage(
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
        # then just do LLM answer with context of last PRIVATE_CHAT_CONTEXT_LENGTH messages

        messages = self.db.getChatMessagesSince(ensuredMessage.chat.id, limit=PRIVATE_CHAT_CONTEXT_LENGTH)
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
        if (not answerToAdmin) and await self._isAdmin(ensuredMessage.user, ensuredMessage.chat, False):
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
                        limit=PRIVATE_CHAT_CONTEXT_LENGTH,
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
    # Processing media
    ###

    async def _parseImage(
        self,
        ensuredMessage: EnsuredMessage,
        fileUniqueId: str,
        messages: List[ModelMessage],
    ) -> bool:
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

    async def _processMedia(
        self,
        ensuredMessage: EnsuredMessage,
        media: _BaseMedium,
        metadata: Dict[str, Any],
        mediaForLLM: Optional[_BaseMedium] = None,
        prompt: Optional[str] = None,
    ) -> MediaProcessingInfo:
        """
        Process Media from message
        """
        # Currently we support only image/ media.
        # If we'll want to support other types, then need to
        # find all "image/" entries in this function and fix
        mediaStatus = MediaStatus.NEW
        localUrl: Optional[str] = None
        mimeType: Optional[str] = None
        mediaType = ensuredMessage.messageType
        if mediaForLLM is None:
            mediaForLLM = media

        if mediaType in [MessageType.TEXT, MessageType.UNKNOWN]:
            raise ValueError(f"Media type {mediaType} is not supported")

        logger.debug(f"Processing media: {media}")
        ret = MediaProcessingInfo(
            id=media.file_unique_id,
            task=None,
            type=mediaType,
        )

        # First check if we have the photo in the database already
        mediaAttachment = self.db.getMediaAttachment(ret.id)
        hasMediaAttachment = mediaAttachment is not None
        if mediaAttachment is not None:
            logger.debug(f"Media#{ret.id} already in database")
            if mediaAttachment["media_type"] != mediaType:
                raise RuntimeError(
                    f"Media#{ret.id} already present in database and it is not an "
                    f"{mediaType} but {mediaAttachment['media_type']}"
                )

            # Only skip processing if Media in DB is in right status
            match MediaStatus(mediaAttachment["status"]):
                case MediaStatus.DONE:
                    ret.task = makeEmptyAsyncTask()
                    return ret

                case MediaStatus.PENDING:
                    try:
                        mediaDate = mediaAttachment["updated_at"]
                        if not isinstance(mediaDate, datetime.datetime):
                            logger.error(
                                f"{mediaType}#{ret.id} `updated_at` is not a datetime: "
                                f"{type(mediaDate).__name__}({mediaDate})"
                            )
                            mediaDate = datetime.datetime.fromisoformat(mediaDate)

                        if utils.getAgeInSecs(mediaDate) > PROCESSING_TIMEOUT:
                            logger.warning(
                                f"{mediaType}#{ret.id} already in database but in status "
                                f"{mediaAttachment['status']} and is too old ({mediaDate}), reprocessing it"
                            )
                        else:
                            ret.task = makeEmptyAsyncTask()
                            return ret
                    except Exception as e:
                        logger.error("{mediaType}#{ret.id} Error during checking age:")
                        logger.exception(e)

                case _:
                    mimeType = str(mediaAttachment["mime_type"])
                    if mimeType.lower().startswith("image/"):
                        logger.debug(
                            f"{mediaType}#{ret.id} in wrong status: {mediaAttachment['status']}. Reprocessing it"
                        )
                    else:
                        logger.debug(f"{mediaType}#{ret.id} is {mimeType}, skipping it")
                        ret.task = makeEmptyAsyncTask()
                        return ret

        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        mediaData: Optional[bytes] = None

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
                metadata=utils.jsonDumps(metadata),
                mimeType=mimeType,
                localUrl=localUrl,
                prompt=prompt,
            )
        else:
            self.db.addMediaAttachment(
                fileUniqueId=ret.id,
                fileId=media.file_id,
                fileSize=media.file_size,
                mediaType=mediaType,
                mimeType=mimeType,
                metadata=utils.jsonDumps(metadata),
                status=mediaStatus,
                localUrl=localUrl,
                prompt=prompt,
                description=None,
            )

        # Need to parse image content with LLM
        if chatSettings[ChatSettingsKey.PARSE_IMAGES].toBool():
            # Do not redownload file if it was downloaded already
            if mediaData is None or mediaForLLM != media:
                if self._bot is None:
                    raise RuntimeError("Bot is not initialized")
                file = await self._bot.get_file(mediaForLLM.file_id)
                logger.debug(f"{mediaType}#{ret.id} File info: {file}")
                mediaData = await file.download_as_bytearray()

            mimeType = magic.from_buffer(bytes(mediaData), mime=True)
            logger.debug(f"{mediaType}#{ret.id} Mimetype: {mimeType}")

            self.db.updateMediaAttachment(
                fileUniqueId=ret.id,
                mimeType=mimeType,
            )

            if mimeType.lower().startswith("image/"):
                logger.debug(f"{mediaType}#{ret.id} is an image")
            else:
                logger.warning(f"{mediaType}#{ret.id} is not an image, skipping parsing")
                ret.task = makeEmptyAsyncTask()
                self.db.updateMediaAttachment(
                    fileUniqueId=ret.id,
                    status=MediaStatus.NEW,
                )
                return ret

            imagePrompt = chatSettings[ChatSettingsKey.PARSE_IMAGE_PROMPT].toStr()
            messages = [
                ModelMessage(
                    role="system",
                    content=imagePrompt,
                ),
                ModelImageMessage(
                    role="user",
                    content=ensuredMessage.messageText,
                    image=mediaData,
                ),
            ]

            logger.debug(f"{mediaType}#{ret.id}: Asynchronously parsing image")
            parseTask = asyncio.create_task(self._parseImage(ensuredMessage, ret.id, messages))
            # logger.debug(f"{mediaType}#{ret.id} After Start")
            ret.task = parseTask
            await self.addTaskToAsyncedQueue(parseTask)
            # logger.debug(f"{mediaType}#{ret.id} After Queued")

        if ret.task is None:
            ret.task = makeEmptyAsyncTask()

        return ret

    async def processSticker(self, ensuredMessage: EnsuredMessage) -> MediaProcessingInfo:
        """
        Process a sticker from message if needed
        """
        sticker = ensuredMessage.getBaseMessage().sticker
        if sticker is None:
            raise ValueError("Sticker not found")

        # Sticker(..., emoji='😨', file_id='C...E', file_size=51444, file_unique_id='A...Q',
        # height=512, is_animated=True, is_video=False, set_name='SharkBoss',
        # thumbnail=PhotoSize(...), type=<StickerType.REGULAR>, width=512)

        metadata = {
            "width": sticker.width,
            "height": sticker.height,
            "emoji": sticker.emoji,
            "set_name": sticker.set_name,
            "is_animated": sticker.is_animated,
            "is_video": sticker.is_video,
            "is_premium": sticker.premium_animation is not None,
        }

        return await self._processMedia(ensuredMessage, media=sticker, metadata=metadata)

    async def processImage(self, ensuredMessage: EnsuredMessage, prompt: Optional[str] = None) -> MediaProcessingInfo:
        """
        Process a photo from message if needed
        """

        bestPhotoSize = ensuredMessage.getBaseMessage().photo[-1]
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)

        llmPhotoSize = bestPhotoSize
        optimalImageSize = chatSettings[ChatSettingsKey.OPTIMAL_IMAGE_SIZE].toInt()
        if optimalImageSize > 0:
            # Iterate over all photo sizes and find the best one (i.e. smallest, but, larger than optimalImageSize)
            for pSize in ensuredMessage.getBaseMessage().photo:
                if pSize.width > optimalImageSize or pSize.height > optimalImageSize:
                    llmPhotoSize = pSize
                    break

        metadata = {
            # Store metadata for best size
            "width": bestPhotoSize.width,
            "height": bestPhotoSize.height,
        }

        return await self._processMedia(
            ensuredMessage,
            media=bestPhotoSize,
            mediaForLLM=llmPhotoSize,
            metadata=metadata,
            prompt=prompt,
        )

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
            f"Привет! {user.first_name}! 👋\n\n"
            "Я Громозека: лучший бот для Телеграма, что когда либо был, есть или будет.\n\n"
            "Что бы узнать, что я умею, можешь отправить команду /help"
        )

        await update.message.reply_text(welcome_message)
        logger.info(f"User {user.id} ({user.username}) started the bot")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /help command."""
        if not update.message:
            logger.error("Message undefined")
            return

        ensuredMessage = EnsuredMessage.fromMessage(update.message)
        isBotOwner = await self._isAdmin(ensuredMessage.user, allowBotOwners=True)

        help_text = (
            "🤖 **Gromozeka Bot Help**\n\n"
            "**Поддерживаемые команды:**\n"
            "`/start` - Начать работу с ботом\n"
            "`/help` - Показать список доступных команд\n"
            "`/echo` `<message>` - Просто ответить переданным сообщением "
            "(для тестирования живости бота)\n"
            "\n"
            "`/summary` `[<messages_count>=0] [<chunks_count>=0]` - "
            "Суммаризировать сообщения в чате за сегодня "
            "(при указании количества сообщений - суммаризировать последние N сообщений)\n"
            "`/topic_summary` `[<messages_count>=0] [<chunks_count>=0]` - "
            "Суммаризировать сообщения в топике чата за сегодня "
            "(при указании количества сообщений - суммаризировать последние N сообщений)\n"
            "`/analyze` `<prompt>` Проанализировать медиа "
            "(на данный момент доступен только анализ картинок и статических стикеров), "
            "используя указанный промпт\n"
            "`/draw` `[<prompt>]` Сгенерировать изображение, используя указанный промпт. "
            "Так же может быть ответом на сообщение (или цитированием части сообщения)\n"
            "`/remind` `<DDdHHhMMmSSs|HH:MM[:SS]>` - напомнить указанный текст через "
            "указанное время (можно использовать цитирование или ответ на сообщение)\n"
            "\n"
            "`/get_my_data` - Показать запомненную информацию о Вас в текущем чате\n"
            "`/delete_my_data` `<key>` - Удалить информацию о Вас по указанному ключу\n"
            "`/clear_my_data` - Очистить все сзнания о Вас в этом чате\n"
            "\n"
            "`/configure` - Настроить поведение бота в одном из чатов, где вы админ\n"
            "`/ban`|`/spam`|`/kick` - Указать боту на сообщение со спамом\n"
            "\n"
            "**Так же этот бот может:**\n"
            "* Анализировать картинки и стикеры и отвечать на вопросы по ним\n"
            "* Логировать все сообщения и вести некоторую статистику\n"
            "* Поддерживать беседу, если она затрагивает бота "
            "(ответ на сообщение бота, указание логина бота в любом месте сообщения "
            "или начало сообщения с имени бота или личный чат с ботом)\n"
            '* Специально отвечать на запросы "`Кто сегодня ...`" и "`Что там?`" '
            "(должно быть ответом на сообщение с медиа)\n"
            "* Что-нибудь еше: Мы открыты к фич-реквестам\n"
        )

        if isBotOwner:
            help_text += (
                "\n\n"
                "**Команды, доступные только владельцам бота:**\n"
                "`/test` `<test_name> [<test_args>]` - Запустить тест "
                "(используется для тестирования)\n"
                "`/models` - вывести список доступных моделей и их параметров\n"
                "`/settings` - вывести список настроек чата\n"
                "`/set`|`/unset` `<key> <value>` - установить/удалить настройку чата\n"
            )

        self._saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER)
        await self._sendMessage(
            ensuredMessage,
            messageText=help_text,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    async def echo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /echo command."""
        if not update.message:
            logger.error("Message undefined")
            return
        ensuredMessage = EnsuredMessage.fromMessage(update.message)

        self._saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        if context.args:
            echo_text = " ".join(context.args)
            await self._sendMessage(
                ensuredMessage,
                messageText=f"🔄 Echo: {echo_text}",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )
        else:
            await self._sendMessage(
                ensuredMessage,
                messageText="Please provide a message to echo!\nUsage: /echo <your message>",
                messageCategory=MessageCategory.BOT_ERROR,
            )

    async def _handle_summarization(self, data: Dict[str, Any], message: Message, user: User):
        """Process summarization buttons."""

        # Used keys:
        # s: Action
        # c: ChatId
        # t: topicId
        # m: MaxMessages/time
        # k: user action (1 - set max messages, 2 - set prompt)

        chatSettings = self.getChatSettings(message.chat_id)
        userId = user.id
        if userId not in self.cache["users"]:
            self.cache["users"][userId] = {}
        self.cache["users"][userId].pop("activeSummarizationId", None)

        exitButton = InlineKeyboardButton("Отмена", callback_data=utils.jsonDumps({"s": "s", "e": "cancel"}))
        action: Optional[str] = data.get("s", None)
        if action is None or action not in ["s", "t", "s+", "t+"]:
            ValueError(f"Wrong action in {data}")
            return  # Useless, used for fixing typechecking issues
        isToticSummary = action.startswith("t")

        if data.get("e", None) == "cancel":
            await message.edit_text(text="Суммаризация отменена")
            return

        maxMessages = data.get("m", None)
        if maxMessages is None:
            maxMessages = 0

        userChats = self.db.getUserChats(user.id)

        chatId = data.get("c", None)
        # Choose chatID
        if not isinstance(chatId, int):
            keyboard: List[List[InlineKeyboardButton]] = []
            # chatSettings = self.getChatSettings(ensuredMessage.chat.id)
            for chat in userChats:
                chatTitle: str = f"#{chat['chat_id']}"
                if chat["title"]:
                    chatTitle = f"{CHAT_ICON} {chat['title']} ({chat["type"]})"
                elif chat["username"]:
                    chatTitle = f"{PRIVATE_ICON} {chat['username']} ({chat["type"]})"

                keyboard.append(
                    [
                        InlineKeyboardButton(
                            chatTitle,
                            callback_data=utils.jsonDumps({"c": chat["chat_id"], "s": action, "m": maxMessages}),
                        )
                    ]
                )

            if not keyboard:
                await message.edit_text("Вы не найдены ни в одном чате.")
                return

            keyboard.append([exitButton])
            await message.edit_text(text="Выберите чат для суммаризации:", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        chatFound = await self._isAdmin(user, None, True)
        chatInfo: Optional[ChatInfoDict] = None
        for chat in userChats:
            if chat["chat_id"] == chatId:
                chatFound = True
                chatInfo = chat
                break

        if not chatFound or chatInfo is None:
            await message.edit_text("Указан неверный чат")
            return

        # ChatID Choosen
        chatTitle: str = f"#{chatInfo['chat_id']}"
        if chatInfo["title"]:
            chatTitle = f"{CHAT_ICON} {chatInfo['title']} ({chatInfo['type']})"
        elif chatInfo["username"]:
            chatTitle = f"{PRIVATE_ICON} {chatInfo['username']} ({chatInfo['type']})"

        topicId = data.get("t", None)
        # Choose TopicID if needed
        if isToticSummary and topicId is None:
            # await message.edit_text("Список топиков пока не поддержан")
            topics = self.db.getChatTopics(chatId=chatId)
            if not topics:
                topics.append(
                    {
                        "chat_id": chatId,
                        "topic_id": 0,
                        "name": "Default",
                        "icon_color": None,
                        "icon_custom_emoji_id": None,
                        "created_at": datetime.datetime.now(),
                        "updated_at": datetime.datetime.now(),
                    }
                )

            keyboard: List[List[InlineKeyboardButton]] = []

            for topic in topics:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            str(topic["name"]),
                            callback_data=utils.jsonDumps(
                                {"c": chatId, "s": action, "m": maxMessages, "t": topic["topic_id"]}
                            ),
                        )
                    ]
                )

            keyboard.append(
                [
                    InlineKeyboardButton(
                        "<< Назад к списку чатов",
                        callback_data=utils.jsonDumps({"s": action, "m": maxMessages}),
                    )
                ]
            )

            keyboard.append([exitButton])

            await message.edit_text(
                text=f"Выбран чат {chatTitle}, выберите нужный топик:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        # TopicID Choosen
        topicTitle = ""
        if topicId is not None and isToticSummary:
            topics = self.db.getChatTopics(chatId=chatId)
            for topic in topics:
                if topic["topic_id"] == topicId:
                    topicTitle = f", топик **{topic["name"]}**"
                    break

        dataTemplate: Dict[str, Any] = {
            "s": action,
            "c": chatId,
            "m": maxMessages,
        }
        if topicId is not None:
            dataTemplate["t"] = topicId

        # Check If User need to Enter Messages/Prompt:
        userActionK = data.get("k", None)
        if userActionK is not None:
            self.cache["users"][userId]["activeSummarizationId"] = {
                **dataTemplate,
                "k": userActionK,
                "message": message,
            }

            keyboard: List[List[InlineKeyboardButton]] = [
                [
                    InlineKeyboardButton(
                        "Начать суммаризацию с текущими настройками",
                        callback_data=utils.jsonDumps({**dataTemplate, "s": action + "+"}),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "<< Назад",
                        callback_data=utils.jsonDumps(dataTemplate),
                    )
                ],
                [exitButton],
            ]

            match userActionK:
                case 1:
                    await message.edit_text(
                        text=markdown_to_markdownv2(
                            f"Выбран чат {chatTitle}{topicTitle}\n"
                            f"Укажите количество сообщений для суммаризации или нажмите нужную кнопку:"
                        ),
                        parse_mode="MarkdownV2",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
                case 2:
                    currentPrompt = chatSettings[ChatSettingsKey.SUMMARY_PROMPT].toStr()
                    self.cache["users"][userId]["activeSummarizationId"]["s"] = action + "+"

                    await message.edit_text(
                        text=markdown_to_markdownv2(
                            f"Выбран чат {chatTitle}{topicTitle}\n"
                            f"Текущий промпт для суммаризации:\n```\n{currentPrompt}\n```\n"
                            f"Укажите новый промпт или нажмите нужную кнопку:"
                        ),
                        parse_mode="MarkdownV2",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
                case _:
                    logger.error(f"Wrong summarisation user action {userActionK} in data {data}")
                    self.cache["users"][userId].pop("activeSummarizationId", None)
                    await message.edit_text("Что-то пошло не так")
            return

        # Choose MaxMessages/Duration/Prompt
        if not action.endswith("+"):
            durationDescription = ""
            match maxMessages:
                case 0:
                    durationDescription = "За сегодня"
                case -1:
                    durationDescription = "За вчера"
                case _:
                    durationDescription = f"Последние {maxMessages} сообщений"

            keyboard: List[List[InlineKeyboardButton]] = [
                [
                    InlineKeyboardButton(
                        "Начать суммаризацию",
                        callback_data=utils.jsonDumps({**dataTemplate, "s": action + "+"}),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Суммаризация за сегодня",
                        callback_data=utils.jsonDumps({**dataTemplate, "m": 0}),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Суммаризация за вчера",
                        callback_data=utils.jsonDumps({**dataTemplate, "m": -1}),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Установить количество сообщений для суммаризации",
                        callback_data=utils.jsonDumps({**dataTemplate, "k": 1}),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Установить промпт",
                        callback_data=utils.jsonDumps({**dataTemplate, "k": 2}),
                    )
                ],
                [exitButton],
            ]

            await message.edit_text(
                text=markdown_to_markdownv2(
                    f"Выбран чат {chatTitle}{topicTitle}\n"
                    f"Границы суммаризации: {durationDescription}\n"
                    "Вы можете поменять границы суммаризации или поменять промпт:"
                ),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        await message.edit_text("Суммаризирую сообщения...")

        today = datetime.datetime.now(datetime.timezone.utc)
        today = today.replace(hour=0, minute=0, second=0, microsecond=0)
        sinceDT = today
        tillDT: Optional[datetime.datetime] = None
        if maxMessages < 1:
            # if maxMessages == 0: # Summarisation for today, no special actions needed
            if maxMessages == -1:
                # Summarization for yesterday
                tillDT = today
                sinceDT = today - datetime.timedelta(days=1)
            maxMessages = None

        repliedMessage = message.reply_to_message

        ensuredMessage: Optional[EnsuredMessage] = None

        try:
            if repliedMessage is not None:
                ensuredMessage = EnsuredMessage.fromMessage(repliedMessage)
            else:
                ensuredMessage = EnsuredMessage.fromMessage(message)
        except Exception as e:
            logger.error(f"summarization: Error ensuring message: {type(e).__name__}{e}")
            logger.exception(e)
            await message.edit_text(str(e))
            return

        if ensuredMessage is None:
            await message.edit_text("ensuredMessage is None")
            return

        await self._doSummarization(
            ensuredMessage=ensuredMessage,
            chatId=chatId,
            threadId=topicId,
            chatSettings=chatSettings,
            sinceDT=sinceDT,
            tillDT=tillDT,
            summarizationPrompt=data.get("p", None),
            maxMessages=maxMessages,
        )

        if repliedMessage is not None:
            await message.delete()
        else:
            await message.edit_text("Суммаризация готова:")

    async def summary_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /[topic_]summary [<messages> <chunks> <chatId> <threadId>]command."""
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

        self._saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        commandStr = ""
        for entity in message.entities:
            if entity.type == MessageEntityType.BOT_COMMAND:
                commandStr = ensuredMessage.messageText[entity.offset : entity.offset + entity.length]
                break

        logger.debug(f"Command string: {commandStr}")
        isTopicSummary = commandStr.startswith("/topic_summary")

        chatType = ensuredMessage.chat.type
        chatSettings = self.getChatSettings(chatId=ensuredMessage.chat.id)

        today = datetime.datetime.now(datetime.timezone.utc)
        today = today.replace(hour=0, minute=0, second=0, microsecond=0)
        maxMessages: Optional[int] = None
        chatId: Optional[int] = None
        threadId: Optional[int] = None

        match chatType:
            case Chat.PRIVATE:
                isBotOwner = await self._isAdmin(ensuredMessage.user, None, True)
                if not chatSettings[ChatSettingsKey.ALLOW_SUMMARY].toBool() and not isBotOwner:
                    logger.info(
                        f"Unauthorized /{commandStr} command from {ensuredMessage.user} "
                        f"in chat {ensuredMessage.chat}"
                    )
                    await self.handle_message(update=update, context=context)
                    return

                maxMessages = 0
                intArgs: List[Optional[int]] = [None, None, None]
                if context.args:
                    for i in range(3):
                        if len(context.args) > i:
                            try:
                                intArgs[i] = int(context.args[i])
                            except ValueError:
                                logger.error(f"Invalid arguments: '{context.args[i]}' is not a valid number.")

                maxMessages = intArgs[0]
                chatId = intArgs[1]
                threadId = intArgs[2]
                jsonAction = "t" if isTopicSummary else "s"

                if maxMessages is None or maxMessages < 1:
                    maxMessages = 0

                if chatId is None:
                    msg = await self._sendMessage(
                        ensuredMessage,
                        messageText="Загружаю список чатов....",
                        messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    )

                    if msg is not None:
                        await self._handle_summarization(
                            {"s": jsonAction, "m": maxMessages}, message=msg, user=ensuredMessage.user
                        )
                    else:
                        logger.error("Message undefined")

                    return

                if threadId is None and isTopicSummary:
                    msg = await self._sendMessage(
                        ensuredMessage,
                        messageText="Загружаю список топиков....",
                        messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    )

                    if msg is not None:
                        await self._handle_summarization(
                            {"s": jsonAction, "c": chatId, "m": maxMessages}, message=msg, user=ensuredMessage.user
                        )
                    else:
                        logger.error("Message undefined")

                    return

                userChats = self.db.getUserChats(ensuredMessage.user.id)
                chatFound = isBotOwner
                for uChat in userChats:
                    if uChat["chat_id"] == chatId:
                        chatFound = True
                        break

                if not chatFound:
                    await self._sendMessage(
                        ensuredMessage, "Передан неверный ID чата", messageCategory=MessageCategory.BOT_ERROR
                    )
                    return

                if maxMessages == 0:
                    maxMessages = None

                return await self._doSummarization(
                    ensuredMessage,
                    chatId=chatId,
                    threadId=threadId,
                    chatSettings=chatSettings,  # TODO: Think: Should we get chat settings or user settings?
                    sinceDT=today,
                    maxMessages=maxMessages,
                )

            case Chat.GROUP | Chat.SUPERGROUP:
                if not chatSettings[ChatSettingsKey.ALLOW_SUMMARY].toBool():
                    logger.info(
                        f"Unauthorized /{commandStr} command from {ensuredMessage.user} "
                        f"in chat {ensuredMessage.chat}"
                    )
                    await self.handle_message(update=update, context=context)
                    return

                if context.args and len(context.args) > 0:
                    try:
                        maxMessages = int(context.args[0])
                        if maxMessages < 1:
                            maxMessages = None
                    except ValueError:
                        logger.error(f"Invalid arguments: '{context.args[0]}' is not a valid number.")

                # Summary command print summary for whole chat.
                # Topic-summary prints summary for current topic, we threat default topic as 0
                if isTopicSummary:
                    threadId = ensuredMessage.threadId if ensuredMessage.threadId else 0

                return await self._doSummarization(
                    ensuredMessage=ensuredMessage,
                    chatId=ensuredMessage.chat.id,
                    threadId=threadId,
                    chatSettings=chatSettings,
                    maxMessages=maxMessages,
                    sinceDT=today,
                )

            case _:
                logger.error(f"Unsupported chat type for Summarization: {chatType}")

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

        if not await self._isAdmin(ensuredMessage.user, allowBotOwners=True):
            logger.warning(f"OWNER ONLY command `/models` by not owner {ensuredMessage.user}")
            await self.handle_message(update=update, context=context)
            return

        self._saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

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
                await self._sendMessage(
                    ensuredMessage,
                    messageText=replyText,
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )
                replyText = ""
                time.sleep(0.5)

        if replyText:
            await self._sendMessage(
                ensuredMessage,
                messageText=replyText,
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
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

        if not await self._isAdmin(ensuredMessage.user, allowBotOwners=True):
            logger.warning(f"OWNER ONLY command `/settings` by not owner {ensuredMessage.user}")
            await self.handle_message(update=update, context=context)
            return

        self._saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)

        # user = ensuredMessage.user
        chat = ensuredMessage.chat

        resp = f"Настройки чата **#{chat.id}**:\n\n"
        chatSettings = self.getChatSettings(chat.id)
        for k, v in chatSettings.items():
            resp += f"`{k}`:```{k}\n{v}\n```\n"

        if moreDebug:
            logger.debug(resp)
            logger.debug(repr(resp))

        await self._sendMessage(
            ensuredMessage,
            messageText=resp,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
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

        if not await self._isAdmin(ensuredMessage.user, allowBotOwners=True):
            logger.warning(f"OWNER ONLY command `/[un]set` by not owner {ensuredMessage.user}")
            await self.handle_message(update=update, context=context)
            return

        self._saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        commandStr = ""
        for entity in message.entities:
            if entity.type == MessageEntityType.BOT_COMMAND:
                commandStr = ensuredMessage.messageText[entity.offset : entity.offset + entity.length]
                break

        logger.debug(f"Command string: {commandStr}")
        isSet = commandStr.startswith("/set")

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
            await self._sendMessage(
                ensuredMessage,
                messageText="You need to specify a key and a value to change chat setting.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return
        if not isSet and (not context.args or len(context.args) < 1):
            await self._sendMessage(
                ensuredMessage,
                messageText="You need to specify a key to clear chat setting.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        if not context.args:
            # It is impossible, actually as we have checked it before, but we do it to make linters happy
            raise ValueError("No args provided")

        key = context.args[0]
        if isSet:
            value = " ".join(context.args[1:])
            self.setChatSettings(chat.id, {key: value})
            await self._sendMessage(
                ensuredMessage,
                messageText=f"Готово, теперь `{key}` = `{value}`",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            )
        else:
            self.unsetChatSetting(chat.id, key)
            await self._sendMessage(
                ensuredMessage,
                messageText=f"Готово, теперь `{key}` сброшено в значение по умолчанию",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
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

        if not await self._isAdmin(ensuredMessage.user, allowBotOwners=True):
            logger.warning(f"OWNER ONLY command `/test` by not owner {ensuredMessage.user}")
            await self.handle_message(update=update, context=context)
            return

        self._saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        if not context.args or len(context.args) < 1:
            await self._sendMessage(
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
                        await self._sendMessage(
                            ensuredMessage,
                            messageText=f"Invalid iterations count. {e}",
                            messageCategory=MessageCategory.BOT_ERROR,
                        )
                        pass
                if len(context.args) > 2:
                    try:
                        delay = int(context.args[2])
                    except ValueError as e:
                        await self._sendMessage(
                            ensuredMessage,
                            messageText=f"Invalid delay. {e}",
                            messageCategory=MessageCategory.BOT_ERROR,
                        )
                        pass

                for i in range(iterationsCount):
                    logger.debug(f"Iteration {i} of {iterationsCount} (delay is {delay}) {context.args[3:]}")
                    await self._sendMessage(
                        ensuredMessage,
                        messageText=f"Iteration {i}",
                        skipLogs=True,  # Do not spam logs
                        messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    )
                    await asyncio.sleep(delay)

            case "delayedQueue":
                await self._sendMessage(
                    ensuredMessage,
                    messageText=f"```\n{self.delayedActionsQueue}\n\n{self.delayedActionsQueue.qsize()}\n```",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )

            case "dumpCache":
                await self._sendMessage(
                    ensuredMessage,
                    messageText=f"```json\n{utils.jsonDumps(self.cache, indent=2)}\n```",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                )
            case _:
                await self._sendMessage(
                    ensuredMessage,
                    messageText=f"Unknown test suite: {suite}.",
                    messageCategory=MessageCategory.BOT_ERROR,
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

        self._saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)

        chatSettings = self.getChatSettings(chatId=ensuredMessage.chat.id)
        if not chatSettings[ChatSettingsKey.ALLOW_ANALYZE].toBool() and not await self._isAdmin(
            ensuredMessage.user, None, True
        ):
            logger.info(f"Unauthorized /analyze command from {ensuredMessage.user} in chat {ensuredMessage.chat}")
            return

        if not ensuredMessage.isReply or not message.reply_to_message:
            await self._sendMessage(
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
            await self._sendMessage(
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
                await self._sendMessage(
                    ensuredMessage,
                    messageText=f"Неподдерживаемый тип медиа: {parentEnsuredMessage.messageType}",
                    messageCategory=MessageCategory.BOT_ERROR,
                )
                return

        mediaInfo = await context.bot.get_file(fileId)
        logger.debug(f"Media info: {mediaInfo}")
        mediaData = await mediaInfo.download_as_bytearray()

        if not mediaData:
            await self._sendMessage(
                ensuredMessage,
                messageText="Не удалось получить данные медиа.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        mimeType = magic.from_buffer(bytes(mediaData), mime=True)
        logger.debug(f"Mime type: {mimeType}")
        if not mimeType.startswith("image/"):
            await self._sendMessage(
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
            await self._sendMessage(
                ensuredMessage,
                messageText=f"Не удалось проанализировать медиа:\n```\n{llmRet.status}\n{llmRet.error}\n```",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        await self._sendMessage(
            ensuredMessage,
            messageText=llmRet.resultText,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
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

        self._saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER_COMMAND)

        chatSettings = self.getChatSettings(chatId=ensuredMessage.chat.id)
        if not chatSettings[ChatSettingsKey.ALLOW_DRAW].toBool() and not await self._isAdmin(
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
            await self._sendMessage(
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
            await self._sendMessage(
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
            await self._sendMessage(
                ensuredMessage,
                messageText="Ошибка генерации изображения, попробуйте позже.",
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        logger.debug(f"Media data len: {len(mlRet.mediaData)}")

        imgAddPrefix = ""
        if mlRet.isFallback:
            imgAddPrefix = chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr()
        await self._sendMessage(
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

    async def remind_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /remind <time> command."""
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

        self._saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)

        delaySecs: int = 0
        try:
            if not context.args:
                raise ValueError("No time specified")
            delayStr = context.args[0]
            delaySecs = utils.parseDelay(delayStr)
        except Exception as e:
            await self._sendMessage(
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

        await self._sendMessage(
            ensuredMessage,
            messageText=f"Напомню в {delayedDT.strftime('%Y-%m-%d %H:%M:%S%z')}",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
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

        self._saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)
        self._updateEMessageUserData(ensuredMessage)

        await self._sendMessage(
            ensuredMessage,
            messageText=(f"```json\n{utils.jsonDumps(ensuredMessage.userData, indent=2)}\n```"),
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
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

        self._saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)
        self._updateEMessageUserData(ensuredMessage)

        if not context.args:
            await self._sendMessage(
                ensuredMessage,
                messageText=("Для команды `/delete_my_data` нужно указать ключ, который нужно удалить."),
                messageCategory=MessageCategory.BOT_ERROR,
            )
            return

        chatId = ensuredMessage.chat.id
        userId = ensuredMessage.user.id
        key = context.args[0]
        self.db.deleteUserData(userId=userId, chatId=chatId, key=key)
        # It Do exist due to _updateEMessageUserData()
        # TODO: Maybe move to proper method?
        self.cache["chatUsers"][f"{chatId}:{userId}"].pop("data", None)

        await self._sendMessage(
            ensuredMessage,
            messageText=f"Готово, ключ {key} успешно удален.",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
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

        self._saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)
        self._updateEMessageUserData(ensuredMessage)

        chatId = ensuredMessage.chat.id
        userId = ensuredMessage.user.id

        self.db.clearUserData(userId=userId, chatId=chatId)
        # It Do exist due to _updateEMessageUserData()
        # TODO: Maybe move to proper method?
        self.cache["chatUsers"][f"{chatId}:{userId}"].pop("data", None)

        await self._sendMessage(
            ensuredMessage,
            messageText="Готово, память о Вас очищена.",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
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

        self._saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)
        self._updateEMessageUserData(ensuredMessage)

        # chatId = ensuredMessage.chat.id
        # userId = ensuredMessage.user.id

        # context.bot.delete_message()
        chatSettings = self.getChatSettings(ensuredMessage.chat.id)
        allowUserSpamCommand = chatSettings[ChatSettingsKey.ALLOW_USER_SPAM_COMMAND].toBool()
        isAdmin = await self._isAdmin(user=ensuredMessage.user, chat=ensuredMessage.chat)

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

    async def _handle_chat_configuration(self, data: Dict[str, Any], message: Message, user: User) -> bool:
        """Parses the CallbackQuery and updates the message text."""

        # Used keys:
        # a: Action
        # c: ChatId
        # k: Key
        # v: Value

        exitButton = InlineKeyboardButton("Закончить настройку", callback_data=utils.jsonDumps({"a": "cancel"}))
        action = data.get("a", None)
        # if "k" in data:
        #    action = "set_key"
        match action:
            case "init":
                userChats = self.db.getUserChats(user.id)
                keyboard: List[List[InlineKeyboardButton]] = []
                # chatSettings = self.getChatSettings(ensuredMessage.chat.id)

                for chat in userChats:
                    chatObj = Chat(
                        id=chat["chat_id"],
                        type=chat["type"],
                        title=chat["title"],
                        username=chat["username"],
                        is_forum=chat["is_forum"],
                    )
                    chatObj.set_bot(message.get_bot())

                    if await self._isAdmin(user=user, chat=chatObj, allowBotOwners=True):
                        buttonTitle: str = f"#{chat['chat_id']}"
                        if chat["title"]:
                            buttonTitle = f"{CHAT_ICON} {chat['title']} ({chat["type"]})"
                        elif chat["username"]:
                            buttonTitle = f"{PRIVATE_ICON} {chat['username']} ({chat["type"]})"

                        keyboard.append(
                            [
                                InlineKeyboardButton(
                                    buttonTitle,
                                    callback_data=utils.jsonDumps({"c": chat["chat_id"], "a": "chat"}),
                                )
                            ]
                        )

                if not keyboard:
                    await message.edit_text("Вы не являетесь администратором ни в одном чате.")
                    return False

                keyboard.append([exitButton])
                await message.edit_text(text="Выберите чат для настройки:", reply_markup=InlineKeyboardMarkup(keyboard))
            case "chat":
                chatId = data.get("c", None)
                if chatId is None:
                    logger.error(f"handle_chat_configuration: chatId is None in {data}")
                    return False

                if not isinstance(chatId, int):
                    logger.error(f"handle_chat_configuration: wrong chatId: {type(chatId).__name__}#{chatId}")
                    return False

                chatObj = Chat(id=chatId, type=Chat.PRIVATE if chatId == user.id else Chat.GROUP)
                chatObj.set_bot(message.get_bot())

                if not await self._isAdmin(user=user, chat=chatObj):
                    logger.error(f"handle_chat_configuration: user#{user.id} is not admin in {chatId}")
                    await message.edit_text(text="Вы не являетесь администратором в выбранном чате")
                    return False

                chatInfo = self._getChatInfo(chatId)
                if chatInfo is None:
                    logger.error(f"handle_chat_configuration: chatInfo is None in {chatId}")
                    return False

                logger.debug(f"handle_chat_configuration: chatInfo: {chatInfo}")
                resp = f"Настраиваем чат **{chatInfo['title'] or chatInfo['username']}#{chatId}**:\n"
                chatSettings = self.getChatSettings(chatId)
                defaultChatSettings = self.getChatSettings(None)

                chatOptions = chat_settings.getChatSettingsInfo()
                keyboard: List[List[InlineKeyboardButton]] = []

                for key, option in chatOptions.items():
                    wasChanged = chatSettings[key].toStr() != defaultChatSettings[key].toStr()
                    resp += (
                        "\n\n\n"
                        f"## **{option['short']}** (`{key}`):\n"
                        f" {option['long']}\n"
                        f" Тип: **{option['type']}**\n"
                        f" Изменено: **{'Да' if wasChanged else 'Нет'}**\n"
                        # f" Текущее значение:\n```\n{chatSettings[key].toStr()}\n```\n"
                        # f" Значение по умолчанию:\n```\n{defaultChatSettings[key].toStr()}\n```\n"
                    )
                    keyTitle = option["short"]
                    if wasChanged:
                        keyTitle += " (*)"
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                keyTitle,
                                callback_data=utils.jsonDumps({"c": chatId, "k": key.getId(), "a": "sk"}),
                            )
                        ]
                    )

                keyboard.append([InlineKeyboardButton("<< Назад", callback_data=utils.jsonDumps({"a": "init"}))])
                keyboard.append([exitButton])

                respMD = markdown_to_markdownv2(resp)
                # logger.debug(resp)
                # logger.debug(respMD)
                try:
                    await message.edit_text(
                        text=respMD, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as e:
                    logger.exception(e)
                    await message.edit_text(text=f"Error while editing message: {e}")
                    return False

            case "sk":
                chatId = data.get("c", None)
                _key = data.get("k", None)

                if chatId is None or _key is None:
                    logger.error(f"handle_chat_configuration: chatId or key is None in {data}")
                    return False

                chatInfo = self._getChatInfo(chatId)
                if chatInfo is None:
                    logger.error(f"handle_chat_configuration: chatInfo is None in {chatId}")
                    return False

                chatSettings = self.getChatSettings(chatId)
                defaultChatSettings = self.getChatSettings(None)

                chatOptions = chat_settings.getChatSettingsInfo()

                try:
                    key = ChatSettingsKey.fromId(_key)
                except ValueError:
                    logger.error(f"handle_chat_configuration: wrong key: {_key}")
                    return False

                if key not in chatOptions:
                    logger.error(f"handle_chat_configuration: wrong key: {key}")
                    await message.edit_text(text=f"Unknown key: {key}")
                    return False

                chatObj = Chat(id=chatId, type=Chat.PRIVATE if chatId == user.id else Chat.GROUP)
                chatObj.set_bot(message.get_bot())
                if not await self._isAdmin(user=user, chat=chatObj):
                    logger.error(f"handle_chat_configuration: user#{user.id} is not admin in {chatId} ({data})")
                    await message.edit_text(text="Вы не являетесь администратором в выбранном чате")
                    return False

                userId = user.id
                if userId not in self.cache["users"]:
                    self.cache["users"][userId] = {}
                self.cache["users"][userId]["activeConfigureId"] = {
                    "chatId": chatId,
                    "key": key,
                    "message": message,
                }

                keyboard: List[List[InlineKeyboardButton]] = []
                wasChanged = chatSettings[key].toStr() != defaultChatSettings[key].toStr()

                resp = (
                    f"Настройка ключа **{chatOptions[key]['short']}** (`{key}`) в чате "
                    f"**{chatInfo['title'] or chatInfo['username']}** ({chatId}):\n\n"
                    f"Тип: **{chatOptions[key]['type']}**\n"
                    f"Был ли изменён: **{'Да' if wasChanged else 'Нет'}**\n"
                    f"Текущее значение:\n```\n{chatSettings[key].toStr()}\n```\n"
                    f"Значение по умолчанию:\n```\n{defaultChatSettings[key].toStr()}\n```\n\n"
                    "Введите новое значение или нажмите нужную кнопку под сообщением"
                )

                if chatOptions[key]["type"] == "bool":
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                "Включить (True)",
                                callback_data=utils.jsonDumps({"a": "s+", "c": chatId, "k": _key}),
                            )
                        ]
                    )
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                "Выключить (False)",
                                callback_data=utils.jsonDumps({"a": "s-", "c": chatId, "k": _key}),
                            )
                        ]
                    )

                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "Сбросить в значение по умолчанию",
                            callback_data=utils.jsonDumps({"a": "s#", "c": chatId, "k": _key}),
                        )
                    ]
                )
                keyboard.append(
                    [InlineKeyboardButton("<< Назад", callback_data=utils.jsonDumps({"a": "chat", "c": chatId}))]
                )
                keyboard.append([exitButton])

                respMD = markdown_to_markdownv2(resp)
                # logger.debug(resp)
                # logger.debug(respMD)
                try:
                    await message.edit_text(
                        text=respMD, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as e:
                    logger.exception(e)
                    await message.edit_text(text=f"Error while editing message: {e}")
                    return False

            case "s+" | "s-" | "s#" | "sv":
                chatId = data.get("c", None)
                _key = data.get("k", None)

                userId = user.id
                if userId not in self.cache["users"]:
                    self.cache["users"][userId] = {}

                self.cache["users"][userId].pop("activeConfigureId", None)

                if chatId is None or _key is None:
                    logger.error(f"handle_chat_configuration: chatId or key is None in {data}")
                    return False

                chatInfo = self._getChatInfo(chatId)
                if chatInfo is None:
                    logger.error(f"handle_chat_configuration: chatInfo is None for {chatId}")
                    return False
                chatOptions = chat_settings.getChatSettingsInfo()

                try:
                    key = ChatSettingsKey.fromId(_key)
                except ValueError:
                    logger.error(f"handle_chat_configuration: wrong key: {_key}")
                    return False

                if key not in chatOptions:
                    logger.error(f"handle_chat_configuration: wrong key: {key}")
                    await message.edit_text(text=f"Unknown key: {key}")
                    return False

                chatObj = Chat(id=chatId, type=Chat.PRIVATE if chatId == user.id else Chat.GROUP)
                chatObj.set_bot(message.get_bot())
                if not await self._isAdmin(user=user, chat=chatObj):
                    logger.error(f"handle_chat_configuration: user#{user.id} is not admin in {chatId} ({data})")
                    await message.edit_text(text="Вы не являетесь администратором в выбранном чате")
                    return False

                keyboard: List[List[InlineKeyboardButton]] = []

                resp = ""

                if action == "s+":
                    self.setChatSettings(chatId, {key: True})
                elif action == "s-":
                    self.setChatSettings(chatId, {key: False})
                elif action == "s#":
                    self.unsetChatSetting(chatId, key)
                elif action == "sv":
                    self.setChatSettings(chatId, {key: data.get("v", None)})
                else:
                    logger.error(f"handle_chat_configuration: wrong action: {action}")
                    raise RuntimeError(f"handle_chat_configuration: wrong action: {action}")

                chatSettings = self.getChatSettings(chatId)

                resp = (
                    f"Ключ **{chatOptions[key]['short']}** (`{key}`) в чате "
                    f"**{chatInfo['title'] or chatInfo['username']}** ({chatId}) успешно изменён:\n\n"
                    f"Новое значение:\n```\n{chatSettings[key].toStr()}\n```\n"
                )

                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "<< К настройкам чата", callback_data=utils.jsonDumps({"a": "chat", "c": chatId})
                        )
                    ]
                )
                keyboard.append([exitButton])

                respMD = markdown_to_markdownv2(resp)
                # logger.debug(resp)
                # logger.debug(respMD)
                try:
                    await message.edit_text(
                        text=respMD, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception as e:
                    logger.exception(e)
                    await message.edit_text(text=f"Error while editing message: {e}")
                    return False

            case "cancel":
                await message.edit_text(text="Настройка закончена, буду ждать вас снова")
            case _:
                logger.error(f"handle_chat_configuration: unknown action: {data}")
                await message.edit_text(text=f"Unknown action: {action}")
                return False

        return True

    async def configure_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /configure command."""

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

        self._saveChatMessage(ensuredMessage, MessageCategory.USER_COMMAND)

        msg = await self._sendMessage(
            ensuredMessage,
            messageText="Загружаю настройки....",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

        # TODO: Add support for /configure <chatId>
        if msg is not None:
            await self._handle_chat_configuration({"a": "init"}, message=msg, user=ensuredMessage.user)
        else:
            logger.error("Message undefined")
            return

    async def handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Parses the CallbackQuery and updates the message text."""

        query = update.callback_query
        if query is None:
            logger.error(f"CallbackQuery undefined in {update}")
            return

        # CallbackQueries need to be answered, even if no notification to the user is needed
        # Some clients may have trouble otherwise. See https://core.telegram.org/bots/api#callbackquery
        # await query.answer(text=query.data)
        # TODO: Answer something cool
        await query.answer()

        if query.data is None:
            logger.error(f"CallbackQuery data undefined in {query}")
            return

        user = query.from_user

        data: Optional[Dict[str, Any]] = None
        try:
            data = json.loads(query.data)
        except Exception as e:
            logger.error(f"Error while parsing callback query data: {e}")
            return

        if data is None:
            logger.error("handle_button: data is None")
            return

        if query.message is None:
            logger.error(f"handle_button: message is None in {query}")
            return

        if not isinstance(query.message, Message):
            logger.error(f"handle_button: message is not a Message in {query}")
            return

        configureAction = data.get("a", None)
        # Used keys:
        # a: Action
        # c: ChatId
        # k: Key
        # v: Value
        if configureAction is not None:
            await self._handle_chat_configuration(data, query.message, user)
            return

        summaryAction = data.get("s", None)
        # Used keys:
        # s: Action
        # c: ChatId
        # t: topicId
        # m: MaxMessages/time
        if summaryAction is not None:
            await self._handle_summarization(data, query.message, user)
            return

        logger.error(f"handle_button: No known action in {data} found")
        raise ValueError("No known action found")

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors."""
        logger.error(f"Unhandled exception while handling an update: {type(context.error).__name__}#{context.error}")
        logger.exception(context.error)

    async def handle_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle bot commands."""
        logger.debug(f"Handling bot command: {update}")
