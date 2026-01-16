"""
Message preprocessing handler for Telegram bot, dood!

This module contains the MessagePreprocessorHandler class which processes
incoming messages before they are handled by other handlers. It validates
chat settings, processes different media types (images, stickers), and
saves messages to the database, dood!
"""

import logging
from typing import Optional

import telegram

from internal.bot.common.models import UpdateObjectType
from internal.bot.models import BotProvider, EnsuredMessage, MessageRecipient, MessageSender
from internal.bot.models.chat_settings import ChatSettingsKey
from internal.database.models import MessageCategory
from internal.models import MessageIdType

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
        """Preprocess incoming messages by processing media and saving to database.

        Args:
            ensuredMessage: Normalized message object to preprocess
            updateObj: Original update object from the platform

        Returns:
            HandlerResultStatus.NEXT if preprocessing successful, ERROR if save failed
        """

        messageCategory = MessageCategory.USER
        # Telegram has different messages for each media\document
        # While Each Max Message can contain multiple attachments of different types
        match self.botProvider:
            case BotProvider.TELEGRAM:
                media = await self.processTelegramMedia(ensuredMessage)
                if media is not None:
                    ensuredMessage.addMediaProcessingInfo(media, setMediaId=True)
                baseMessage = ensuredMessage.getBaseMessage()
                # If it's an automatic forward from linked channel,
                #  then mark message as channel message, so we can do something in future
                #  (For example forward somewhere)
                if isinstance(baseMessage, telegram.Message) and baseMessage.is_automatic_forward:
                    messageCategory = MessageCategory.CHANNEL
            case BotProvider.MAX:
                for media in await self.processMaxMedia(ensuredMessage):
                    ensuredMessage.addMediaProcessingInfo(media, setMediaId=False)
            case _:
                logger.error(f"Unsupported bot provider: {self.botProvider}")

        if not await self.saveChatMessage(ensuredMessage, messageCategory=messageCategory):
            logger.error("Failed to save chat message")
            return HandlerResultStatus.ERROR

        return HandlerResultStatus.NEXT

    async def newChatMemberHandler(
        self,
        targetChat: MessageRecipient,
        messageId: Optional[MessageIdType],
        newMember: MessageSender,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        """
        Handle new chat member events and optionally delete join messages.

        Args:
            targetChat: Chat where the new member joined
            messageId: Optional message ID of the join notification
            newMember: User who joined the chat
            updateObj: Original update object from the platform

        Returns:
            HandlerResultStatus.FINAL if join message deleted, NEXT otherwise
        """

        self.db.updateChatUser(
            chatId=targetChat.id,
            userId=newMember.id,
            username=newMember.username,
            fullName=newMember.name,
        )
        self.setUserMetadata(
            chatId=targetChat.id,
            userId=newMember.id,
            metadata={
                "leftChat": False,
            },
            isUpdate=True,
        )

        chatSettings = self.getChatSettings(targetChat.id)
        if messageId is not None and chatSettings[ChatSettingsKey.DELETE_JOIN_MESSAGES].toBool():
            logger.info(f"Deleting join message#{messageId} of {newMember} in chat {targetChat.id}")
            await self.deleteMessagesById(targetChat.id, [messageId])
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.NEXT

    async def leftChatMemberHandler(
        self,
        targetChat: MessageRecipient,
        messageId: Optional[MessageIdType],
        leftMember: MessageSender,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        """
        Handle left chat member events and optionally delete left messages.

        Args:
            targetChat: The chat where the member joined
            messageId: Optional message ID associated with the join event
            leftMember: The member who left the chat
            updateObj: The raw update object from the bot platform

        Returns:
            HandlerResultStatus.FINAL if left message deleted, NEXT otherwise
        """
        self.db.updateChatUser(
            chatId=targetChat.id,
            userId=leftMember.id,
            username=leftMember.username,
            fullName=leftMember.name,
        )
        self.setUserMetadata(
            chatId=targetChat.id,
            userId=leftMember.id,
            metadata={
                "leftChat": True,
            },
            isUpdate=True,
        )

        chatSettings = self.getChatSettings(targetChat.id)
        if messageId is not None and chatSettings[ChatSettingsKey.DELETE_LEFT_MESSAGES].toBool():
            logger.info(f"Deleting left message#{messageId} of {leftMember} in chat {targetChat.id}")
            await self.deleteMessagesById(targetChat.id, [messageId])
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.NEXT
