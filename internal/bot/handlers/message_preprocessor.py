"""
Message preprocessing handler for Telegram bot, dood!

This module contains the MessagePreprocessorHandler class which processes
incoming messages before they are handled by other handlers. It validates
chat settings, processes different media types (images, stickers), and
saves messages to the database, dood!
"""

import logging
from typing import Optional

from telegram import Chat, Update
from telegram.ext import ContextTypes

from internal.database.models import MessageCategory

from .base import BaseBotHandler, HandlerResultStatus
from ..models import (
    ChatSettingsKey,
    EnsuredMessage,
    MessageType,
)

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

    async def messageHandler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, ensuredMessage: Optional[EnsuredMessage]
    ) -> HandlerResultStatus:
        """
        Process and validate incoming Telegram messages, dood!

        This method performs the following operations, dood:
        1. Validates that ensuredMessage is provided
        2. Checks if private chat messages are allowed (for private chats)
        3. Processes media content based on message type (IMAGE, STICKER)
        4. Saves the processed message to the database

        Args:
            update: The Telegram update object containing the message, dood
            context: The context object for the handler, dood
            ensuredMessage: Optional validated message object with chat and user info, dood

        Returns:
            HandlerResultStatus: Status indicating the result of processing, dood:
                - SKIPPED: If ensuredMessage is None or private chats are disabled
                - ERROR: If message saving fails
                - NEXT: If processing completed successfully

        Note:
            Unsupported message types are logged but still processed (caption as text), dood!
        """

        if not ensuredMessage:
            # Not new message, Skip
            return HandlerResultStatus.SKIPPED

        chat = ensuredMessage.chat

        if chat.type == Chat.PRIVATE:
            chatSettings = self.getChatSettings(chat.id)
            if not chatSettings[ChatSettingsKey.ALLOW_PRIVATE].toBool():
                return HandlerResultStatus.SKIPPED

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
