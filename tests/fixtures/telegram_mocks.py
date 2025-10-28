"""
Mock Telegram API objects for testing.

This module provides factory functions to create mock Telegram objects
with realistic default values. All mocks use unittest.mock.Mock with
proper spec to ensure type safety.
"""

from datetime import datetime
from typing import List, Optional
from unittest.mock import AsyncMock, Mock


def createMockUser(
    userId: int = 456,
    username: str = "testuser",
    firstName: str = "Test",
    lastName: Optional[str] = "User",
    isBot: bool = False,
    languageCode: str = "en",
) -> Mock:
    """
    Create a mock Telegram User object.

    Args:
        userId: User ID (default: 456)
        username: Username without @ (default: "testuser")
        firstName: User's first name (default: "Test")
        lastName: User's last name (default: "User")
        isBot: Whether user is a bot (default: False)
        languageCode: User's language code (default: "en")

    Returns:
        Mock: Mocked User instance

    Example:
        user = createMockUser(userId=123, username="john")
        assert user.id == 123
        assert user.username == "john"
    """
    from telegram import User

    user = Mock(spec=User)
    user.id = userId
    user.username = username
    user.first_name = firstName
    user.last_name = lastName
    user.is_bot = isBot
    user.language_code = languageCode
    user.full_name = f"{firstName} {lastName}" if lastName else firstName

    return user


def createMockChat(
    chatId: int = 123,
    chatType: str = "private",
    title: Optional[str] = None,
    username: Optional[str] = None,
    firstName: Optional[str] = None,
    lastName: Optional[str] = None,
) -> Mock:
    """
    Create a mock Telegram Chat object.

    Args:
        chatId: Chat ID (default: 123)
        chatType: Chat type: "private", "group", "supergroup", "channel" (default: "private")
        title: Chat title for groups (default: None)
        username: Chat username (default: None)
        firstName: First name for private chats (default: None)
        lastName: Last name for private chats (default: None)

    Returns:
        Mock: Mocked Chat instance

    Example:
        chat = createMockChat(chatId=123, chatType="group", title="Test Group")
        assert chat.type == "group"
        assert chat.title == "Test Group"
    """
    from telegram import Chat

    chat = Mock(spec=Chat)
    chat.id = chatId
    chat.type = chatType
    chat.title = title
    chat.username = username
    chat.first_name = firstName
    chat.last_name = lastName

    return chat


def createMockMessage(
    messageId: int = 1,
    chatId: int = 123,
    userId: int = 456,
    text: Optional[str] = "test message",
    date: Optional[datetime] = None,
    replyToMessage: Optional[Mock] = None,
    entities: Optional[List] = None,
    photo: Optional[List] = None,
    document: Optional[Mock] = None,
    sticker: Optional[Mock] = None,
    caption: Optional[str] = None,
) -> Mock:
    """
    Create a mock Telegram Message object.

    Args:
        messageId: Message ID (default: 1)
        chatId: Chat ID (default: 123)
        userId: User ID (default: 456)
        text: Message text (default: "test message")
        date: Message date (default: current time)
        replyToMessage: Replied message (default: None)
        entities: Message entities (default: None)
        photo: List of PhotoSize objects (default: None)
        document: Document object (default: None)
        sticker: Sticker object (default: None)
        caption: Media caption (default: None)

    Returns:
        Mock: Mocked Message instance

    Example:
        msg = createMockMessage(text="Hello", chatId=123)
        assert msg.text == "Hello"
        assert msg.chat.id == 123
    """
    from telegram import Message

    message = Mock(spec=Message)
    message.message_id = messageId
    message.chat = createMockChat(chatId=chatId)
    message.chat_id = chatId  # Add chat_id as direct attribute
    message.from_user = createMockUser(userId=userId)
    message.sender_chat = None  # Add sender_chat attribute for channel messages
    message.text = text
    message.text_markdown_v2 = text  # Add markdown version for reply text extraction
    message.date = date or datetime.now()
    message.reply_to_message = replyToMessage
    message.entities = entities or []
    message.photo = photo
    message.document = document
    message.sticker = sticker
    message.caption = caption
    message.caption_markdown_v2 = caption  # Add markdown version for caption
    message.quote = None  # Add quote attribute
    message.forum_topic_created = None  # Add forum topic created attribute

    # Add media type attributes that EnsuredMessage checks
    message.animation = None
    message.video = None
    message.video_note = None
    message.audio = None
    message.voice = None
    message.message_thread_id = None  # Add thread ID
    message.is_topic_message = False  # Add topic message flag
    message.is_automatic_forward = False  # Add automatic forward flag

    # Add async methods
    message.reply_text = AsyncMock(return_value=message)
    message.reply_photo = AsyncMock(return_value=message)
    message.delete = AsyncMock(return_value=True)
    message.edit_text = AsyncMock(return_value=message)

    # Add get_bot method - will be overridden by tests that need specific bot
    message.get_bot = Mock(return_value=None)

    return message


def createMockUpdate(
    updateId: int = 1,
    message: Optional[Mock] = None,
    callbackQuery: Optional[Mock] = None,
    text: Optional[str] = None,
    chatId: Optional[int] = None,
    userId: Optional[int] = None,
) -> Mock:
    """
    Create a mock Telegram Update object.

    Args:
        updateId: Update ID (default: 1)
        message: Message object (default: auto-created)
        callbackQuery: CallbackQuery object (default: None)
        text: Message text for auto-created message (default: None)
        chatId: Chat ID for auto-created message (default: None)
        userId: User ID for auto-created message (default: None)

    Returns:
        Mock: Mocked Update instance

    Example:
        update = createMockUpdate(text="Hello", chatId=123)
        assert update.message.text == "Hello"
        assert update.effective_chat.id == 123
    """
    from telegram import Update

    update = Mock(spec=Update)
    update.update_id = updateId

    # Create message if not provided
    if message is None and callbackQuery is None:
        message = createMockMessage(
            text=text or "test message",
            chatId=chatId or 123,
            userId=userId or 456,
        )

    update.message = message
    update.callback_query = callbackQuery
    update.effective_message = message or (callbackQuery.message if callbackQuery else None)
    update.effective_chat = message.chat if message else (callbackQuery.message.chat if callbackQuery else None)
    update.effective_user = message.from_user if message else (callbackQuery.from_user if callbackQuery else None)

    return update


def createMockCallbackQuery(
    queryId: str = "callback_123",
    data: str = "test_callback",
    message: Optional[Mock] = None,
    userId: int = 456,
) -> Mock:
    """
    Create a mock Telegram CallbackQuery object.

    Args:
        queryId: Query ID (default: "callback_123")
        data: Callback data (default: "test_callback")
        message: Associated message (default: auto-created)
        userId: User ID (default: 456)

    Returns:
        Mock: Mocked CallbackQuery instance

    Example:
        query = createMockCallbackQuery(data="button_clicked")
        assert query.data == "button_clicked"
        await query.answer()
    """
    from telegram import CallbackQuery

    query = Mock(spec=CallbackQuery)
    query.id = queryId
    query.data = data
    query.message = message or createMockMessage()
    query.from_user = createMockUser(userId=userId)

    # Add async methods
    query.answer = AsyncMock(return_value=True)
    query.edit_message_text = AsyncMock(return_value=query.message)
    query.edit_message_reply_markup = AsyncMock(return_value=query.message)

    return query


def createMockPhoto(
    fileId: str = "photo_123",
    fileUniqueId: str = "unique_photo_123",
    width: int = 1280,
    height: int = 720,
    fileSize: int = 102400,
) -> Mock:
    """
    Create a mock Telegram PhotoSize object.

    Args:
        fileId: File ID (default: "photo_123")
        fileUniqueId: Unique file ID (default: "unique_photo_123")
        width: Photo width (default: 1280)
        height: Photo height (default: 720)
        fileSize: File size in bytes (default: 102400)

    Returns:
        Mock: Mocked PhotoSize instance

    Example:
        photo = createMockPhoto(width=1920, height=1080)
        assert photo.width == 1920
    """
    from telegram import PhotoSize

    photo = Mock(spec=PhotoSize)
    photo.file_id = fileId
    photo.file_unique_id = fileUniqueId
    photo.width = width
    photo.height = height
    photo.file_size = fileSize

    return photo


def createMockDocument(
    fileId: str = "doc_123",
    fileUniqueId: str = "unique_doc_123",
    fileName: str = "test.pdf",
    mimeType: str = "application/pdf",
    fileSize: int = 204800,
) -> Mock:
    """
    Create a mock Telegram Document object.

    Args:
        fileId: File ID (default: "doc_123")
        fileUniqueId: Unique file ID (default: "unique_doc_123")
        fileName: File name (default: "test.pdf")
        mimeType: MIME type (default: "application/pdf")
        fileSize: File size in bytes (default: 204800)

    Returns:
        Mock: Mocked Document instance

    Example:
        doc = createMockDocument(fileName="report.docx")
        assert doc.file_name == "report.docx"
    """
    from telegram import Document

    document = Mock(spec=Document)
    document.file_id = fileId
    document.file_unique_id = fileUniqueId
    document.file_name = fileName
    document.mime_type = mimeType
    document.file_size = fileSize

    return document


def createMockSticker(
    fileId: str = "sticker_123",
    fileUniqueId: str = "unique_sticker_123",
    width: int = 512,
    height: int = 512,
    isAnimated: bool = False,
    isVideo: bool = False,
    emoji: Optional[str] = "😀",
) -> Mock:
    """
    Create a mock Telegram Sticker object.

    Args:
        fileId: File ID (default: "sticker_123")
        fileUniqueId: Unique file ID (default: "unique_sticker_123")
        width: Sticker width (default: 512)
        height: Sticker height (default: 512)
        isAnimated: Whether sticker is animated (default: False)
        isVideo: Whether sticker is video (default: False)
        emoji: Associated emoji (default: "😀")

    Returns:
        Mock: Mocked Sticker instance

    Example:
        sticker = createMockSticker(isAnimated=True)
        assert sticker.is_animated == True
    """
    from telegram import Sticker

    sticker = Mock(spec=Sticker)
    sticker.file_id = fileId
    sticker.file_unique_id = fileUniqueId
    sticker.width = width
    sticker.height = height
    sticker.is_animated = isAnimated
    sticker.is_video = isVideo
    sticker.emoji = emoji

    return sticker


def createMockContext(bot: Optional[Mock] = None) -> Mock:
    """
    Create a mock CallbackContext for handlers.

    Args:
        bot: Bot instance (default: auto-created)

    Returns:
        Mock: Mocked CallbackContext instance

    Example:
        context = createMockContext()
        await context.bot.sendMessage(chat_id=123, text="test")
    """
    from telegram.ext import CallbackContext

    context = Mock(spec=CallbackContext)
    context.bot = bot or createMockBot()
    context.user_data = {}
    context.chat_data = {}
    context.bot_data = {}
    context.args = []
    context.error = None

    return context


def createMockBot(
    botId: int = 123456789,
    username: str = "test_bot",
    firstName: str = "Test Bot",
) -> AsyncMock:
    """
    Create a mock Telegram Bot instance.

    Args:
        botId: Bot ID (default: 123456789)
        username: Bot username (default: "test_bot")
        firstName: Bot first name (default: "Test Bot")

    Returns:
        AsyncMock: Mocked ExtBot instance

    Example:
        bot = createMockBot()
        await bot.sendMessage(chat_id=123, text="test")
        bot.sendMessage.assert_called_once()
    """
    from telegram.ext import ExtBot

    bot = AsyncMock(spec=ExtBot)
    bot.id = botId
    bot.username = username
    bot.first_name = firstName

    # Configure common async methods
    bot.sendMessage = AsyncMock(return_value=createMockMessage())
    bot.sendPhoto = AsyncMock(return_value=createMockMessage())
    bot.sendDocument = AsyncMock(return_value=createMockMessage())
    bot.deleteMessage = AsyncMock(return_value=True)
    bot.editMessageText = AsyncMock(return_value=createMockMessage())
    bot.getChatAdministrators = AsyncMock(return_value=[])
    bot.getChatMember = AsyncMock(return_value=Mock())
    bot.banChatMember = AsyncMock(return_value=True)
    bot.unbanChatMember = AsyncMock(return_value=True)
    bot.getFile = AsyncMock(return_value=Mock())

    return bot
