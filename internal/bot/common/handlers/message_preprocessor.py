"""Message preprocessing handler for bot messages.

This module contains the MessagePreprocessorHandler class which processes
incoming messages before they are handled by other handlers. It validates
chat settings, processes different media types (images, stickers), and
saves messages to the database. This handler acts as the first stage in
the message processing pipeline, ensuring all messages are properly
normalized and persisted before being passed to other handlers.
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
    """Preprocesses incoming bot messages before further handling.

    This handler validates chat settings, processes media content (images and
    stickers), and persists messages to the database. It acts as the first
    stage in the message processing pipeline, ensuring all messages are
    properly normalized and persisted before being passed to other handlers.

    Attributes:
        botProvider: The bot platform provider (Telegram or Max).
        db: Database manager instance for persistence operations.
        logger: Logger instance for this handler.
    """

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """Preprocess incoming messages by processing media and saving to database.

        This method handles the first stage of message processing. It processes
        media attachments (images, stickers, documents) differently based on the
        bot platform (Telegram or Max), determines the message category (user
        or channel), and persists the message to the database.

        Args:
            ensuredMessage: Normalized message object to preprocess.
            updateObj: Original update object from the platform.

        Returns:
            HandlerResultStatus.NEXT if preprocessing successful, ERROR if save failed.

        Raises:
            Exception: If media processing or database operations fail.
        """
        messageCategory: MessageCategory = MessageCategory.USER
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
        """Handle new chat member events and optionally delete join messages.

        This method updates the chat user information in the database, marks
        the user as having joined (not left), and optionally deletes the join
        notification message based on chat settings.

        Args:
            targetChat: Chat where the new member joined.
            messageId: Optional message ID of the join notification.
            newMember: User who joined the chat.
            updateObj: Original update object from the platform.

        Returns:
            HandlerResultStatus.FINAL if join message deleted, NEXT otherwise.

        Raises:
            Exception: If database operations or message deletion fails.
        """
        await self.db.chatUsers.updateChatUser(
            chatId=targetChat.id,
            userId=newMember.id,
            username=newMember.username,
            fullName=newMember.name,
        )
        await self.setUserMetadata(
            chatId=targetChat.id,
            userId=newMember.id,
            metadata={
                "leftChat": False,
            },
            isUpdate=True,
        )

        chatSettings = await self.getChatSettings(targetChat.id)
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
        """Handle left chat member events and optionally delete left messages.

        This method updates the chat user information in the database, marks
        the user as having left the chat, and optionally deletes the leave
        notification message based on chat settings.

        Args:
            targetChat: The chat where the member left.
            messageId: Optional message ID associated with the leave event.
            leftMember: The member who left the chat.
            updateObj: The raw update object from the bot platform.

        Returns:
            HandlerResultStatus.FINAL if left message deleted, NEXT otherwise.

        Raises:
            Exception: If database operations or message deletion fails.
        """
        await self.db.chatUsers.updateChatUser(
            chatId=targetChat.id,
            userId=leftMember.id,
            username=leftMember.username,
            fullName=leftMember.name,
        )
        await self.setUserMetadata(
            chatId=targetChat.id,
            userId=leftMember.id,
            metadata={
                "leftChat": True,
            },
            isUpdate=True,
        )

        chatSettings = await self.getChatSettings(targetChat.id)
        if messageId is not None and chatSettings[ChatSettingsKey.DELETE_LEFT_MESSAGES].toBool():
            logger.info(f"Deleting left message#{messageId} of {leftMember} in chat {targetChat.id}")
            await self.deleteMessagesById(targetChat.id, [messageId])
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.NEXT
