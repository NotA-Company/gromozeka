"""
Database test fixtures and sample data.

This module provides factory functions to create sample database records
for testing. All functions return dictionaries matching the TypedDict
definitions in internal.database.models.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


def createSampleChatMessage(
    messageId: int = 1,
    chatId: int = 123,
    userId: int = 456,
    text: Optional[str] = "Test message",
    timestamp: Optional[int] = None,
    replyToMessageId: Optional[int] = None,
    threadId: Optional[int] = None,
    mediaType: Optional[str] = None,
    mediaFileId: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a sample chat message record.

    Args:
        messageId: Message ID (default: 1)
        chatId: Chat ID (default: 123)
        userId: User ID (default: 456)
        text: Message text (default: "Test message")
        timestamp: Unix timestamp (default: current time)
        replyToMessageId: ID of replied message (default: None)
        threadId: Thread/topic ID (default: None)
        mediaType: Type of media (default: None)
        mediaFileId: Telegram file ID (default: None)

    Returns:
        dict: Chat message record

    Example:
        msg = createSampleChatMessage(text="Hello", chatId=123)
        db.saveChatMessage(**msg)
    """
    return {
        "message_id": messageId,
        "chat_id": chatId,
        "user_id": userId,
        "text": text,
        "timestamp": timestamp or int(datetime.now().timestamp()),
        "reply_to_message_id": replyToMessageId,
        "thread_id": threadId,
        "media_type": mediaType,
        "media_file_id": mediaFileId,
    }


def createSampleChatUser(
    chatId: int = 123,
    userId: int = 456,
    username: Optional[str] = "testuser",
    firstName: Optional[str] = "Test",
    lastName: Optional[str] = "User",
    isBot: bool = False,
    isSpammer: bool = False,
    metadata: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a sample chat user record.

    Args:
        chatId: Chat ID (default: 123)
        userId: User ID (default: 456)
        username: Username (default: "testuser")
        firstName: First name (default: "Test")
        lastName: Last name (default: "User")
        isBot: Whether user is a bot (default: False)
        isSpammer: Whether user is marked as spammer (default: False)
        metadata: JSON metadata (default: None)

    Returns:
        dict: Chat user record

    Example:
        user = createSampleChatUser(userId=123, username="john")
        db.updateChatUser(**user)
    """
    return {
        "chat_id": chatId,
        "user_id": userId,
        "username": username,
        "first_name": firstName,
        "last_name": lastName,
        "is_bot": isBot,
        "is_spammer": isSpammer,
        "metadata": metadata,
    }


def createSampleDelayedTask(
    taskId: Optional[int] = None,
    handlerName: str = "test_handler",
    executeAt: Optional[int] = None,
    priority: int = 0,
    args: Optional[str] = None,
    kwargs: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a sample delayed task record.

    Args:
        taskId: Task ID (default: None for auto-increment)
        handlerName: Handler function name (default: "test_handler")
        executeAt: Unix timestamp to execute (default: 1 hour from now)
        priority: Task priority (default: 0)
        args: JSON-encoded args (default: None)
        kwargs: JSON-encoded kwargs (default: None)

    Returns:
        dict: Delayed task record

    Example:
        task = createSampleDelayedTask(handlerName="send_message")
        db.saveDelayedTask(**task)
    """
    if executeAt is None:
        executeAt = int((datetime.now() + timedelta(hours=1)).timestamp())

    return {
        "task_id": taskId,
        "handler_name": handlerName,
        "execute_at": executeAt,
        "priority": priority,
        "args": args or "[]",
        "kwargs": kwargs or "{}",
    }


def createSampleChatSettings(
    model: str = "gpt-4",
    temperature: float = 0.7,
    maxTokens: int = 1000,
    systemPrompt: Optional[str] = None,
    randomReplyProbability: float = 0.0,
) -> Dict[str, Any]:
    """
    Create sample chat settings.

    Args:
        model: LLM model name (default: "gpt-4")
        temperature: Temperature parameter (default: 0.7)
        maxTokens: Max tokens (default: 1000)
        systemPrompt: System prompt (default: None)
        randomReplyProbability: Random reply probability (default: 0.0)

    Returns:
        dict: Chat settings

    Example:
        settings = createSampleChatSettings(model="gpt-3.5-turbo")
        db.setChatSetting(chat_id, "model", settings["model"])
    """
    settings = {
        "model": model,
        "temperature": temperature,
        "max_tokens": maxTokens,
        "random_reply_probability": randomReplyProbability,
    }

    if systemPrompt:
        settings["system_prompt"] = systemPrompt

    return settings


def createSampleUserData(
    preferences: Optional[Dict[str, Any]] = None,
    history: Optional[List[str]] = None,
    customData: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create sample user data.

    Args:
        preferences: User preferences (default: empty dict)
        history: User history (default: empty list)
        customData: Custom user data (default: None)

    Returns:
        dict: User data

    Example:
        data = createSampleUserData(preferences={"lang": "en"})
        db.setUserData(user_id, "preferences", data["preferences"])
    """
    userData = {
        "preferences": preferences or {},
        "history": history or [],
    }

    if customData:
        userData.update(customData)

    return userData


def createSampleMediaAttachment(
    messageId: int = 1,
    chatId: int = 123,
    mediaType: str = "photo",
    fileId: str = "photo_123",
    fileUniqueId: str = "unique_photo_123",
    fileSize: Optional[int] = 102400,
    mimeType: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Create a sample media attachment record.

    Args:
        messageId: Message ID (default: 1)
        chatId: Chat ID (default: 123)
        mediaType: Media type (photo, document, sticker, etc.) (default: "photo")
        fileId: Telegram file ID (default: "photo_123")
        fileUniqueId: Unique file ID (default: "unique_photo_123")
        fileSize: File size in bytes (default: 102400)
        mimeType: MIME type (default: None)
        width: Media width (default: None)
        height: Media height (default: None)

    Returns:
        dict: Media attachment record

    Example:
        media = createSampleMediaAttachment(mediaType="document")
        # Use in tests
    """
    return {
        "message_id": messageId,
        "chat_id": chatId,
        "media_type": mediaType,
        "file_id": fileId,
        "file_unique_id": fileUniqueId,
        "file_size": fileSize,
        "mime_type": mimeType,
        "width": width,
        "height": height,
    }


def createSampleBayesToken(
    chatId: int = 123,
    token: str = "test",
    spamCount: int = 0,
    hamCount: int = 0,
) -> Dict[str, Any]:
    """
    Create a sample Bayes token record.

    Args:
        chatId: Chat ID (default: 123)
        token: Token string (default: "test")
        spamCount: Spam occurrence count (default: 0)
        hamCount: Ham occurrence count (default: 0)

    Returns:
        dict: Bayes token record

    Example:
        token = createSampleBayesToken(token="spam", spamCount=10)
        # Use in Bayes filter tests
    """
    return {
        "chat_id": chatId,
        "token": token,
        "spam_count": spamCount,
        "ham_count": hamCount,
    }


def createSampleCacheEntry(
    key: str = "test_key",
    value: str = "test_value",
    expiresAt: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Create a sample cache entry.

    Args:
        key: Cache key (default: "test_key")
        value: Cache value (default: "test_value")
        expiresAt: Unix timestamp for expiration (default: 1 hour from now)

    Returns:
        dict: Cache entry record

    Example:
        entry = createSampleCacheEntry(key="weather:london")
        db.setCacheValue(**entry)
    """
    if expiresAt is None:
        expiresAt = int((datetime.now() + timedelta(hours=1)).timestamp())

    return {
        "key": key,
        "value": value,
        "expires_at": expiresAt,
    }


def createBatchChatMessages(
    count: int = 10,
    chatId: int = 123,
    startMessageId: int = 1,
    startUserId: int = 456,
) -> List[Dict[str, Any]]:
    """
    Create a batch of sample chat messages.

    Args:
        count: Number of messages to create (default: 10)
        chatId: Chat ID (default: 123)
        startMessageId: Starting message ID (default: 1)
        startUserId: Starting user ID (default: 456)

    Returns:
        list: List of chat message records

    Example:
        messages = createBatchChatMessages(count=50)
        for msg in messages:
            db.saveChatMessage(**msg)
    """
    messages = []
    baseTime = int(datetime.now().timestamp())

    for i in range(count):
        messages.append(
            createSampleChatMessage(
                messageId=startMessageId + i,
                chatId=chatId,
                userId=startUserId + (i % 3),  # Rotate between 3 users
                text=f"Test message {i + 1}",
                timestamp=baseTime + i,
            )
        )

    return messages


def createBatchChatUsers(
    count: int = 5,
    chatId: int = 123,
    startUserId: int = 456,
) -> List[Dict[str, Any]]:
    """
    Create a batch of sample chat users.

    Args:
        count: Number of users to create (default: 5)
        chatId: Chat ID (default: 123)
        startUserId: Starting user ID (default: 456)

    Returns:
        list: List of chat user records

    Example:
        users = createBatchChatUsers(count=10)
        for user in users:
            db.updateChatUser(**user)
    """
    users = []

    for i in range(count):
        users.append(
            createSampleChatUser(
                chatId=chatId,
                userId=startUserId + i,
                username=f"user{i + 1}",
                firstName="User",
                lastName=f"{i + 1}",
            )
        )

    return users


def createConversationHistory(
    messageCount: int = 5,
    chatId: int = 123,
    userIds: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """
    Create a conversation history with alternating users.

    Args:
        messageCount: Number of messages (default: 5)
        chatId: Chat ID (default: 123)
        userIds: List of user IDs to alternate (default: [456, 789])

    Returns:
        list: List of chat message records forming a conversation

    Example:
        history = createConversationHistory(messageCount=10)
        # Use for testing conversation context
    """
    if userIds is None:
        userIds = [456, 789]

    messages = []
    baseTime = int(datetime.now().timestamp())

    for i in range(messageCount):
        userId = userIds[i % len(userIds)]
        messages.append(
            createSampleChatMessage(
                messageId=i + 1,
                chatId=chatId,
                userId=userId,
                text=f"Message {i + 1} from user {userId}",
                timestamp=baseTime + i * 60,  # 1 minute apart
                replyToMessageId=i if i > 0 else None,
            )
        )

    return messages
