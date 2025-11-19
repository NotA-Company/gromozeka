"""
Message preprocessing handler for Telegram bot, dood!

This module contains the MessagePreprocessorHandler class which processes
incoming messages before they are handled by other handlers. It validates
chat settings, processes different media types (images, stickers), and
saves messages to the database, dood!
"""

import logging

from internal.bot.common.models import UpdateObjectType
from internal.bot.models import BotProvider, EnsuredMessage, MessageType
from internal.database.models import MessageCategory

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class MessagePreprocessorHandler(BaseBotHandler):
    """
    Preprocesses incoming Telegram messages before further handling, dood!

    This handler validates chat settings, processes media content (images and
    stickers), and persists messages to the database. It acts as the first
    stage in the message processing pipeline, dood!

    Attributes:
        Inherits all attributes from BaseBotHandler, dood!
    """

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """
        TODO
        """

        # Telegram has different messages for each media\document
        # While Each Max Message can contain multiple attachments of different types
        match self.botProvider:
            case BotProvider.TELEGRAM:
                await self._processTelegramMedia(ensuredMessage)
            case BotProvider.MAX:
                mediaList = await self.processMaxMedia(ensuredMessage)
                if mediaList:
                    # TODO: Allow use all media
                    ensuredMessage.addMediaProcessingInfo(mediaList[0])
            case _:
                logger.error(f"Unsupported bot provider: {self.botProvider}")

        if not await self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER):
            logger.error("Failed to save chat message")
            return HandlerResultStatus.ERROR

        return HandlerResultStatus.NEXT

    async def _processTelegramMedia(self, ensuredMessage: EnsuredMessage) -> None:
        match ensuredMessage.messageType:
            case MessageType.TEXT:
                # No special handling for text messages needed
                pass
            case MessageType.IMAGE:
                media = await self.processTelegramImage(ensuredMessage)
                ensuredMessage.addMediaProcessingInfo(media)
            case MessageType.STICKER:
                media = await self.processTelegramSticker(ensuredMessage)
                ensuredMessage.addMediaProcessingInfo(media)

            case _:
                # For unsupported message types, just log a warning and process caption like text message
                logger.warning(f"Unsupported message type: {ensuredMessage.messageType}")
                # return
