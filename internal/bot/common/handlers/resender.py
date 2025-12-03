"""
TODO: Write compact docstring
"""

import asyncio
import datetime
import logging
from collections.abc import Sequence
from typing import Optional

from internal.bot.models import (
    BotProvider,
)
from internal.config.manager import ConfigManager
from internal.database.models import MessageCategory
from internal.database.wrapper import DatabaseWrapper
from internal.services.queue_service import DelayedTask, DelayedTaskFunction, QueueService
from lib.ai import LLMManager

from .base import BaseBotHandler

logger = logging.getLogger(__name__)


class ResendJob:
    """
    TODO: write compact docstring
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
    )

    def __init__(
        self,
        id: str,
        *,
        dataSource: str,
        sourceChatId: int,
        targetChatId: int,
        sourceTheadId: Optional[int] = None,
        messageTypes: Sequence[MessageCategory],
        messagePrefix: str = "",
        messageSuffix: str = "",
        lastMessageDate: Optional[datetime.datetime | str] = None,
    ):
        """
        TODO: write compact docstring
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
        self.messageTypes = messageTypes
        """message types to resend"""
        self.messagePrefix = messagePrefix
        """message prefix for resend messages"""
        self.messageSuffix = messageSuffix
        """message suffix for resend messages"""
        self.lastMessageDate: Optional[datetime.datetime] = None
        """last message timestamp processed"""
        if isinstance(lastMessageDate, str):
            self.lastMessageDate = datetime.datetime.fromisoformat(lastMessageDate)
        elif isinstance(lastMessageDate, datetime.datetime):
            self.lastMessageDate = lastMessageDate

    def __str__(self) -> str:
        retList = []
        for slot in self.__slots__:
            retList.append(f"{slot}={getattr(self, slot)}")

        return self.__class__.__name__ + "(" + ", ".join(retList) + ")"


class ResenderHandler(BaseBotHandler):
    """
    TODO: write compact docstring
    """

    def __init__(
        self,
        configManager: ConfigManager,
        database: DatabaseWrapper,
        llmManager: LLMManager,
        botProvider: BotProvider,
    ):
        """
        TODO: docstring
        """
        super().__init__(configManager=configManager, database=database, llmManager=llmManager, botProvider=botProvider)

        config = configManager.get("resender", {})

        if not isinstance(config, dict):
            raise ValueError("`resender` config must be a dictionary")

        jobs = config.get("jobs", [])
        if not isinstance(jobs, list):
            raise ValueError("`jobs` config must be a list of dictionaries")

        self.jobs = [ResendJob(**job) for job in jobs]
        # TODO: load lastMessageDate from DB\Cache if any

        self.queueService = QueueService.getInstance()
        self.queueService.registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB, self._dtCronJob)

        logger.debug(f"ResenderHandler initialized with {len(self.jobs)} jobs")

    async def _dtCronJob(self, task: DelayedTask) -> None:
        """
        TODO: docstring
        """
        logger.debug("Cron job started")
        for job in self.jobs:
            logger.debug(f"Processing job {job}")
            newData = self.db.getChatMessagesSince(
                chatId=job.sourceChatId,
                sinceDateTime=job.lastMessageDate,
                messageCategory=job.messageTypes,
                threadId=job.sourceTheadId,
                limit=10,  # Do not resend too many messages an once
                dataSource=job.dataSource,
            )
            if not newData:
                continue
            for message in newData:
                # TODO: Add media support
                messagePrefix = job.messagePrefix
                messageSuffix = job.messageSuffix
                for k, v in message.items():
                    logger.debug("Replacing {{" + k + "}} with " + str(v))
                    messagePrefix = messagePrefix.replace("{{" + k + "}}", str(v))
                    messageSuffix = messageSuffix.replace("{{" + k + "}}", str(v))

                await self.sendMessage(
                    None,
                    messageText=messagePrefix + message["message_text"] + messageSuffix,
                    messageCategory=MessageCategory.BOT_RESENDED,
                    chatId=job.targetChatId,
                )
                job.lastMessageDate = message["date"]
                # TODO: Store lastMessageDate into DB\Cache
                await asyncio.sleep(0.25)
