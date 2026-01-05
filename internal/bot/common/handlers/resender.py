"""
Message resender module for Gromozeka Telegram bot.

This module provides functionality to automatically resend messages from one chat to another
based on configurable rules. It includes the [`ResendJob`](internal/bot/common/handlers/resender.py:27) class for
defining resend rules and the [`ResenderHandler`](internal/bot/common/handlers/resender.py:100) class for managing
and executing the resending process.

The resender can be configured to:
- Resend messages of specific categories (text, images, etc.)
- Add custom prefixes and suffixes to messages
- Filter messages by source chat, thread, and timestamp
"""

import asyncio
import datetime
import json
import logging
from collections.abc import MutableSet, Sequence
from typing import List, Optional, Tuple

from internal.bot.models import (
    BotProvider,
)
from internal.bot.models.text_formatter import FormatEntity, OutputFormat
from internal.config.manager import ConfigManager
from internal.database.models import MessageCategory
from internal.database.wrapper import DatabaseWrapper
from internal.models import MessageType
from internal.services.queue_service import DelayedTask, DelayedTaskFunction, QueueService
from lib.ai import LLMManager

from .base import BaseBotHandler

logger = logging.getLogger(__name__)


class ResendJob:
    """
    Configuration class for defining message resend jobs.

    A resend job specifies the source and target chats, message types to resend,
    and optional formatting to apply to resent messages. Each job maintains its
    own state including the timestamp of the last processed message.
    """

    __slots__ = (
        "id",
        "dataSource",
        "sourceChatId",
        "sourceTheadId",
        "targetChatId",
        "messageTypes",
        "messagePrefix",
        "messageSuffix",
        "lastMessageDate",
        "notification",
        "_lock",
    )

    def __init__(
        self,
        id: str,
        *,
        dataSource: str,
        sourceChatId: int,
        targetChatId: int,
        sourceTheadId: Optional[int] = None,
        messageTypes: Sequence[MessageCategory | str],
        messagePrefix: str = "",
        messageSuffix: str = "",
        lastMessageDate: Optional[datetime.datetime | str] = None,
        notification: Optional[bool] = None,
    ):
        """
        Initialize a resend job with the specified configuration.

        Args:
            id: Unique identifier for the resend job, used for persisting job state
            dataSource: Name of the data source to read messages from
            sourceChatId: Source chat ID to resend messages from
            targetChatId: Target chat ID to resend messages to
            sourceTheadId: Optional source thread ID to filter messages from
            messageTypes: Sequence of message categories to resend
            messagePrefix: Optional prefix to add to resent messages
            messageSuffix: Optional suffix to add to resent messages
            lastMessageDate: Optional last message timestamp processed (datetime or ISO string)
        """
        self.id = id
        """id of the resend job, used for persisting the job state"""
        self.dataSource = dataSource
        """name of the data source"""
        self.sourceChatId = sourceChatId
        """source chat id for resend messages from"""
        self.sourceTheadId = sourceTheadId
        """source thread id for resend messages from"""
        self.targetChatId = targetChatId
        """target chat id for resend messages to"""
        self.messageTypes: List[MessageCategory] = []
        for messageType in messageTypes:
            self.messageTypes.append(MessageCategory(messageType))
        """message types to resend"""
        self.messagePrefix = messagePrefix
        """message prefix for resend messages"""
        self.messageSuffix = messageSuffix
        """message suffix for resend messages"""
        self.notification = notification
        """
        notification flag for resend messages.
        True to enable notifications,
        False to disable,
        None to use system defaults.
        """
        self.lastMessageDate: Optional[datetime.datetime] = None
        """last message timestamp processed"""
        if lastMessageDate:
            self.setLastMessageDate(lastMessageDate)
        self._lock = asyncio.Lock()
        """internal async lock for synchronization"""

    def setLastMessageDate(self, lastMessageDate: datetime.datetime | str) -> None:
        """
        Set the last message timestamp processed for this job.

        Args:
            lastMessageDate: Last message timestamp as datetime object or ISO format string

        Raises:
            ValueError: If lastMessageDate is not a datetime or string
        """
        if isinstance(lastMessageDate, str):
            self.lastMessageDate = datetime.datetime.fromisoformat(lastMessageDate)
        elif isinstance(lastMessageDate, datetime.datetime):
            self.lastMessageDate = lastMessageDate
        else:
            raise ValueError(f"lastMessageDate must be a datetime or a string, but got {type(lastMessageDate)}")

    def getLock(self) -> asyncio.Lock:
        """
        Get the async lock for this resend job as a context manager.

        This method returns the internal lock that can be used with async context
        manager syntax to ensure exclusive access to the job during critical operations.

        Returns:
            asyncio.Lock: The async lock object that can be used with 'async with'

        Example:
            async with job.getLock():
                # Critical section - only one coroutine can execute this at a time
                await process_job(job)
        """
        return self._lock

    def isLocked(self) -> bool:
        """
        Check if the lock is currently acquired by someone.

        Returns:
            bool: True if the lock is currently held by a coroutine, False otherwise
        """
        return self._lock.locked()

    def __str__(self) -> str:
        """
        Return a string representation of the resend job.

        Returns:
            String representation showing all job attributes
        """
        retList = []
        for slot in self.__slots__:
            if slot == "_lock":
                continue
            retList.append(f"{slot}={getattr(self, slot)}")

        return self.__class__.__name__ + "(" + ", ".join(retList) + ")"


class ResenderHandler(BaseBotHandler):
    """
    Handler class for managing and executing message resend operations.

    This handler processes configured resend jobs, periodically checking for new
    messages that match each job's criteria and resending them to the target
    chat with any configured formatting. It integrates with the queue service
    to run periodic checks and maintains job state in the database.
    """

    def __init__(
        self,
        configManager: ConfigManager,
        database: DatabaseWrapper,
        llmManager: LLMManager,
        botProvider: BotProvider,
    ):
        """
        Initialize the resender handler with configuration and services.

        Args:
            configManager: Configuration manager providing bot settings
            database: Database wrapper for data persistence
            llmManager: LLM manager for AI model operations
            botProvider: Bot provider enum indicating which messaging platform to use

        Raises:
            ValueError: If resender config is not a dictionary or jobs config is not a list
        """
        super().__init__(configManager=configManager, database=database, llmManager=llmManager, botProvider=botProvider)

        config = configManager.get("resender", {})

        if not isinstance(config, dict):
            raise ValueError("`resender` config must be a dictionary")

        jobs = config.get("jobs", [])
        if not isinstance(jobs, list):
            raise ValueError("`jobs` config must be a list of dictionaries")

        self.jobs: List[ResendJob] = []
        for job in jobs:
            if not isinstance(job, dict):
                raise ValueError(f"each job must be a dictionary, but got {type(job)}")
            newJob = ResendJob(**job)
            dataKey = f"resender:{newJob.id}:lastMessageDate"
            storedData = self.db.getSetting(dataKey)
            if storedData:
                newJob.setLastMessageDate(storedData)
            logger.info(f"Loaded resender job {newJob}")
            self.jobs.append(newJob)

        self.queueService = QueueService.getInstance()
        self.queueService.registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB, self._dtCronJob)

        logger.debug(f"ResenderHandler initialized with {len(self.jobs)} jobs")

    async def _dtCronJob(self, task: DelayedTask) -> None:
        """
        Execute the periodic resend job check and processing.

        This method is called by the queue service on a schedule to check for new
        messages that match any configured resend job criteria and resend them
        to their target chats.

        Args:
            task: Delayed task object containing job execution context
        """
        logger.debug("Cron job started")
        for job in self.jobs:
            if job.isLocked():
                # If someone alreadu processing this job, skip it
                # Will retry next time if needed
                continue

            async with job.getLock():
                logger.debug(f"Processing job {job}")
                newData = self.db.getChatMessagesSince(
                    chatId=job.sourceChatId,
                    sinceDateTime=job.lastMessageDate,
                    messageCategory=job.messageTypes,
                    threadId=job.sourceTheadId,
                    dataSource=job.dataSource,
                )
                if not newData:
                    continue
                processedMediaGroups: MutableSet[str] = set[str]()
                for message in reversed(newData):
                    try:
                        if message["media_group_id"] is not None:
                            if message["media_group_id"] in processedMediaGroups:
                                continue
                            else:
                                processedMediaGroups.add(message["media_group_id"])

                        attachmentList: List[Tuple[bytes, MessageType]] = []
                        if message["media_group_id"]:
                            logger.debug(f"Processing media group {message['media_group_id']}")
                            for media in self.db.getMediaAttachmentsByGroupId(
                                message["media_group_id"],
                                dataSource=job.dataSource,
                            ):
                                logger.debug(f"Processing media {media}")
                                if not media["local_url"]:
                                    continue
                                mediaData = self.storage.get(media["local_url"])
                                if mediaData is None:
                                    continue

                                mediaType = MessageType(media["media_type"])
                                attachmentList.append((mediaData, mediaType))

                        messageText = message["message_text"]
                        if message["markup"]:
                            markupEntities = FormatEntity.fromDictList(json.loads(message["markup"]))
                            outputFormat: OutputFormat = OutputFormat.MARKDOWN
                            match self.botProvider:
                                case BotProvider.TELEGRAM:
                                    outputFormat = OutputFormat.MARKDOWN_TG
                                case BotProvider.MAX:
                                    outputFormat = OutputFormat.MARKDOWN_MAX
                            messageText = FormatEntity.parseText(messageText, markupEntities, outputFormat=outputFormat)

                        if attachmentList or message["message_text"]:
                            # Send message only if it has text or supported media
                            messagePrefix = job.messagePrefix
                            messageSuffix = job.messageSuffix
                            for k, v in message.items():
                                # logger.debug("Replacing {{" + k + "}} with " + str(v))
                                messagePrefix = messagePrefix.replace("{{" + k + "}}", str(v))
                                messageSuffix = messageSuffix.replace("{{" + k + "}}", str(v))

                            await self.sendMessage(
                                None,
                                messageText=messagePrefix + messageText + messageSuffix,
                                messageCategory=MessageCategory.BOT_RESENDED,
                                chatId=job.targetChatId,
                                notify=job.notification,
                                attachmentList=attachmentList,
                            )

                        if job.lastMessageDate is None or message["date"] > job.lastMessageDate:
                            job.lastMessageDate = message["date"]
                        self.db.setSetting(f"resender:{job.id}:lastMessageDate", job.lastMessageDate.isoformat())
                        await asyncio.sleep(0.25)
                    except Exception as e:
                        logger.error(f"Error processing job {job}: {e}")
                        logger.exception(e)
                        await self.sendMessage(
                            None,
                            messageText=f"Error while resending message: {e}",
                            messageCategory=MessageCategory.BOT_ERROR,
                            chatId=job.targetChatId,
                            notify=job.notification,
                        )
