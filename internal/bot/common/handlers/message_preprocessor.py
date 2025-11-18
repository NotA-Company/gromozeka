"""
Message preprocessing handler for Telegram bot, dood!

This module contains the MessagePreprocessorHandler class which processes
incoming messages before they are handled by other handlers. It validates
chat settings, processes different media types (images, stickers), and
saves messages to the database, dood!
"""

import logging

from internal.bot.common.models import UpdateObjectType
from internal.bot.models import EnsuredMessage, MessageType
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
                # For unsupported message types, just log a warning and process caption like text message
                logger.warning(f"Unsupported message type: {ensuredMessage.messageType}")
                # return

        if not self.saveChatMessage(ensuredMessage, messageCategory=MessageCategory.USER):
            logger.error("Failed to save chat message")
            return HandlerResultStatus.ERROR

        return HandlerResultStatus.NEXT
