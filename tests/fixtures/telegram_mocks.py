"""
Telegram mock objects for testing.

This module provides factory functions to create mock Telegram objects
for use in tests. All mocks are configured with sensible defaults.
"""

import datetime
from typing import Optional
from unittest.mock import AsyncMock, Mock

from telegram import Chat, Message, MessageEntity, Update, User
from telegram.ext import ExtBot


def createMockUser(
    userId: int = 456,
    username: str = "testuser",
    firstName: str = "Test",
    lastName: Optional[str] = "User",
    isBot: bool = False,
) -> Mock:
    """
    Create a mock Telegram User.

    Args:
        userId: User ID (default: 456)
        username: Username (default: "testuser")
        firstName: First name (default: "Test")
        lastName: Last name (default: "User")
        isBot: Whether user is a bot (default: False)

    Returns:
        Mock: Mocked User instance

    Example:
        user = createMockUser(userId=123, username="john")
        assert user.id == 123
    """
    user = Mock(spec=User)
    user.id = userId
    user.username = username
    user.first_name = firstName
    user.last_name = lastName
    user.is_bot = isBot
    user.full_name = f"{firstName} {lastName}" if lastName else firstName
    user.name = username  # Add name property for compatibility
    return user


def createMockChat(
    chatId: int = 123,
    chatType: str = "private",
    title: Optional[str] = None,
    username: Optional[str] = None,
    isForum: bool = False,
) -> Mock:
    """
    Create a mock Telegram Chat.

    Args:
        chatId: Chat ID (default: 123)
        chatType: Chat type (private, group, supergroup, channel) (default: "private")
        title: Chat title (default: None)
        username: Chat username (default: None)
        isForum: Whether chat is a forum (default: False)

    Returns:
        Mock: Mocked Chat instance

    Example:
        chat = createMockChat(chatId=123, chatType="group", title="Test Group")
        assert chat.type == "group"
    """
    chat = Mock(spec=Chat)
    chat.id = chatId
    chat.chat_id = chatId  # Add chat_id property for compatibility
    chat.type = chatType
    chat.title = title
    chat.username = username
    chat.is_forum = isForum
    chat._bot = None  # Set _bot to None by default (tests can override)
    return chat


def createMockMessage(
    messageId: int = 1,
    chatId: int = 123,
    userId: int = 456,
    text: Optional[str] = "test message",
    chat: Optional[Mock] = None,
    fromUser: Optional[Mock] = None,
    replyToMessage: Optional[Mock] = None,
) -> Mock:
    """
    Create a mock Telegram Message.

    Args:
        messageId: Message ID (default: 1)
        chatId: Chat ID (default: 123)
        userId: User ID (default: 456)
        text: Message text (default: "test message")
        chat: Mock Chat object (default: auto-created)
        fromUser: Mock User object (default: auto-created)
        replyToMessage: Mock Message being replied to (default: None)

    Returns:
        Mock: Mocked Message instance

    Example:
        message = createMockMessage(text="Hello", chatId=123)
        assert message.text == "Hello"
    """
    message = Mock(spec=Message)
    message.message_id = messageId
    message.text = text
    message.text_markdown_v2 = text  # For reply text formatting
    message.chat = chat or createMockChat(chatId=chatId)
    message.chat_id = message.chat.id  # Add chat_id property for compatibility
    message.from_user = fromUser or createMockUser(userId=userId)
    message.reply_to_message = replyToMessage
    message.date = datetime.datetime.now()  # Use real datetime instead of Mock
    message.photo = None
    message.document = None
    message.sticker = None
    message.is_automatic_forward = False

    # Auto-detect commands and add BOT_COMMAND entity
    entities = []
    if text and text.startswith("/"):
        # Extract command (everything before first space or end of string)
        commandEnd = text.find(" ")
        if commandEnd == -1:
            commandEnd = len(text)

        # Create BOT_COMMAND entity
        commandEntity = Mock(spec=MessageEntity)
        commandEntity.type = MessageEntity.BOT_COMMAND
        commandEntity.offset = 0
        commandEntity.length = commandEnd
        entities.append(commandEntity)

    message.entities = entities
    message.caption = None
    message.caption_entities = []
    message.video = None
    message.video_note = None
    message.audio = None
    message.voice = None
    message.animation = None
    message.is_topic_message = False
    message.message_thread_id = None
    message.forum_topic_created = None

    # Use configure_mock to properly set these to None
    # This prevents Mock from auto-generating mocks when accessed
    message.configure_mock(sender_chat=None, quote=None, external_reply=None)

    # Configure reply methods to return properly configured mock messages
    # This ensures that when reply_text() or reply_photo() is called,
    # the returned message has all attributes properly set
    message.reply_text = AsyncMock(
        side_effect=lambda text=None, **kwargs: createMockMessage(
            messageId=kwargs.get("message_id", messageId + 1),
            chatId=message.chat.id,
            userId=message.from_user.id,
            text=text or kwargs.get("text", "reply"),
            chat=message.chat,
            fromUser=message.from_user,
        )
    )
    message.reply_photo = AsyncMock(
        side_effect=lambda photo=None, **kwargs: createMockMessage(
            messageId=kwargs.get("message_id", messageId + 1),
            chatId=message.chat.id,
            userId=message.from_user.id,
            text=kwargs.get("caption", ""),
            chat=message.chat,
            fromUser=message.from_user,
        )
    )

    # Configure edit methods for inline keyboard interactions
    # These are used by configuration handlers and callback queries
    message.edit_text = AsyncMock(return_value=True)
    message.edit_reply_markup = AsyncMock(return_value=True)

    # Configure get_bot method to return a bot instance
    # This is needed for handlers that call message.get_bot()
    # Make get_bot() return the _bot attribute
    message.get_bot = lambda: message._bot

    # Set _bot attribute to None by default (tests can override)
    # This prevents "no bot associated" errors when using shortcuts
    message._bot = None

    return message


def createMockUpdate(
    updateId: int = 1,
    messageId: int = 1,
    chatId: int = 123,
    userId: int = 456,
    text: str = "test message",
    message: Optional[Mock] = None,
    callbackQuery: Optional[Mock] = None,
) -> Mock:
    """
    Create a mock Telegram Update.

    Args:
        updateId: Update ID (default: 1)
        messageId: Message ID (default: 1)
        chatId: Chat ID (default: 123)
        userId: User ID (default: 456)
        text: Message text (default: "test message")
        message: Mock Message object (default: auto-created)
        callbackQuery: Mock CallbackQuery object (default: None)

    Returns:
        Mock: Mocked Update instance

    Example:
        update = createMockUpdate(text="Hello")
        assert update.message.text == "Hello"
    """
    update = Mock(spec=Update)
    update.update_id = updateId
    update.message = message or createMockMessage(
        messageId=messageId,
        chatId=chatId,
        userId=userId,
        text=text,
    )
    update.callback_query = callbackQuery
    update.effective_chat = update.message.chat if update.message else None
    update.effective_user = (
        update.message.from_user if update.message else (callbackQuery.from_user if callbackQuery else None)
    )
    update.effective_message = update.message if update.message else (callbackQuery.message if callbackQuery else None)
    return update


def createMockBot(
    botId: int = 123456789,
    username: str = "test_bot",
    firstName: str = "Test Bot",
) -> AsyncMock:
    """
    Create a mock Telegram Bot.

    Args:
        botId: Bot ID (default: 123456789)
        username: Bot username (default: "test_bot")
        firstName: Bot first name (default: "Test Bot")

    Returns:
        AsyncMock: Mocked ExtBot instance

    Example:
        bot = createMockBot()
        await bot.sendMessage(chat_id=123, text="test")
    """
    bot = AsyncMock(spec=ExtBot)
    bot.id = botId
    bot.username = username
    bot.first_name = firstName

    # Configure common async methods
    # Use lambda to create new mock message each time to avoid shared state
    bot.sendMessage = AsyncMock(
        side_effect=lambda **kwargs: createMockMessage(
            messageId=kwargs.get("message_id", 1),
            chatId=kwargs.get("chat_id", 123),
            text=kwargs.get("text", "mock response"),
        )
    )
    bot.sendPhoto = AsyncMock(
        side_effect=lambda **kwargs: createMockMessage(
            messageId=kwargs.get("message_id", 1), chatId=kwargs.get("chat_id", 123)
        )
    )
    bot.deleteMessage = AsyncMock(return_value=True)
    bot.delete_message = AsyncMock(return_value=True)  # snake_case alias
    bot.delete_messages = AsyncMock(return_value=True)
    bot.getChatAdministrators = AsyncMock(return_value=[])
    bot.get_chat_administrators = AsyncMock(return_value=[])  # snake_case alias
    bot.banChatMember = AsyncMock(return_value=True)
    bot.ban_chat_member = AsyncMock(return_value=True)  # snake_case alias
    bot.ban_chat_sender_chat = AsyncMock(return_value=True)
    bot.unbanChatMember = AsyncMock(return_value=True)
    bot.unban_chat_member = AsyncMock(return_value=True)  # snake_case alias

    # Create mock file with awaitable download_as_bytearray
    mockFile = Mock()
    mockFile.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake_image_data"))
    bot.getFile = AsyncMock(return_value=mockFile)
    bot.get_file = AsyncMock(return_value=mockFile)  # snake_case alias

    return bot


def createMockCallbackQuery(
    queryId: str = "callback_123",
    data: str = "test_callback",
    message: Optional[Mock] = None,
    fromUser: Optional[Mock] = None,
    userId: Optional[int] = None,
) -> Mock:
    """
    Create a mock Telegram CallbackQuery.

    Args:
        queryId: Query ID (default: "callback_123")
        data: Callback data (default: "test_callback")
        message: Mock Message object (default: auto-created)
        fromUser: Mock User object (default: auto-created)
        userId: User ID for auto-created user (default: 456)

    Returns:
        Mock: Mocked CallbackQuery instance

    Example:
        query = createMockCallbackQuery(data="button_clicked")
        assert query.data == "button_clicked"
    """
    from telegram import CallbackQuery

    query = Mock(spec=CallbackQuery)
    query.id = queryId
    query.data = data
    query.message = message or createMockMessage()
    query.from_user = fromUser or createMockUser(userId=userId if userId is not None else 456)
    query.answer = AsyncMock(return_value=True)

    return query


def createMockPhoto(
    fileId: str = "photo_123",
    fileUniqueId: str = "unique_photo_123",
    width: int = 1920,
    height: int = 1080,
    fileSize: int = 102400,
) -> Mock:
    """
    Create a mock Telegram PhotoSize.

    Args:
        fileId: File ID (default: "photo_123")
        fileUniqueId: Unique file ID (default: "unique_photo_123")
        width: Photo width (default: 1920)
        height: Photo height (default: 1080)
        fileSize: File size in bytes (default: 102400)

    Returns:
        Mock: Mocked PhotoSize instance

    Example:
        photo = createMockPhoto(width=800, height=600)
        assert photo.width == 800
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
    fileId: str = "document_123",
    fileUniqueId: str = "unique_document_123",
    fileName: str = "test.pdf",
    mimeType: str = "application/pdf",
    fileSize: int = 204800,
) -> Mock:
    """
    Create a mock Telegram Document.

    Args:
        fileId: File ID (default: "document_123")
        fileUniqueId: Unique file ID (default: "unique_document_123")
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
    fileSize: int = 12345,
) -> Mock:
    """
    Create a mock Telegram Sticker.

    Args:
        fileId: File ID (default: "sticker_123")
        fileUniqueId: Unique file ID (default: "unique_sticker_123")
        width: Sticker width (default: 512)
        height: Sticker height (default: 512)
        isAnimated: Whether sticker is animated (default: False)
        isVideo: Whether sticker is video (default: False)
        emoji: Associated emoji (default: "😀")
        fileSize: File size in bytes (default: 12345)

    Returns:
        Mock: Mocked Sticker instance

    Example:
        sticker = createMockSticker(emoji="👍")
        assert sticker.emoji == "👍"
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
    sticker.file_size = fileSize

    return sticker


def createMockContext(
    bot: Optional[AsyncMock] = None,
    chatData: Optional[dict] = None,
    userData: Optional[dict] = None,
    botData: Optional[dict] = None,
) -> Mock:
    """
    Create a mock Telegram Context (CallbackContext).

    Args:
        bot: Mock bot instance (default: auto-created)
        chatData: Chat data dictionary (default: empty dict)
        userData: User data dictionary (default: empty dict)
        botData: Bot data dictionary (default: empty dict)

    Returns:
        Mock: Mocked CallbackContext instance

    Example:
        context = createMockContext(chatData={"setting": "value"})
        assert context.chat_data["setting"] == "value"
    """
    from telegram.ext import CallbackContext

    context = Mock(spec=CallbackContext)
    context.bot = bot or createMockBot()
    context.chat_data = chatData or {}
    context.user_data = userData or {}
    context.bot_data = botData or {}
    context.args = []
    context.error = None

    return context
