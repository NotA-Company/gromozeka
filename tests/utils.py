"""
Test utility functions and helpers.

This module provides helper functions for creating test objects,
async utilities, and assertion helpers for testing.
"""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import AsyncMock, Mock

# ============================================================================
# Mock Creation Utilities
# ============================================================================


def createMockUpdate(
    text: Optional[str] = "test message",
    chatId: int = 123,
    userId: int = 456,
    messageId: int = 1,
    isReply: bool = False,
    hasPhoto: bool = False,
    hasDocument: bool = False,
) -> Mock:
    """
    Create a mock Telegram Update with common configurations.

    Args:
        text: Message text (default: "test message")
        chatId: Chat ID (default: 123)
        userId: User ID (default: 456)
        messageId: Message ID (default: 1)
        isReply: Whether message is a reply (default: False)
        hasPhoto: Whether message has photo (default: False)
        hasDocument: Whether message has document (default: False)

    Returns:
        Mock: Configured Update instance

    Example:
        update = createMockUpdate(text="Hello", chatId=123)
        assert update.message.text == "Hello"
    """
    from tests.fixtures.telegram_mocks import (
        createMockDocument,
        createMockMessage,
        createMockPhoto,
    )
    from tests.fixtures.telegram_mocks import createMockUpdate as _createUpdate

    # Create message with optional media
    message = createMockMessage(
        messageId=messageId,
        chatId=chatId,
        userId=userId,
        text=text,
    )

    if isReply:
        message.reply_to_message = createMockMessage(
            messageId=messageId - 1,
            chatId=chatId,
            userId=userId + 1,
            text="Original message",
        )

    if hasPhoto:
        message.photo = [createMockPhoto()]
        message.text = None
        message.caption = text

    if hasDocument:
        message.document = createMockDocument()
        message.text = None
        message.caption = text

    return _createUpdate(message=message)


def createMockMessage(
    text: Optional[str] = "test message",
    chatId: int = 123,
    userId: int = 456,
    messageId: int = 1,
) -> Mock:
    """
    Create a mock Telegram Message.

    Args:
        text: Message text (default: "test message")
        chatId: Chat ID (default: 123)
        userId: User ID (default: 456)
        messageId: Message ID (default: 1)

    Returns:
        Mock: Configured Message instance

    Example:
        msg = createMockMessage(text="Hello")
        assert msg.text == "Hello"
    """
    from tests.fixtures.telegram_mocks import createMockMessage as _createMessage

    return _createMessage(
        messageId=messageId,
        chatId=chatId,
        userId=userId,
        text=text,
    )


def createMockUser(
    userId: int = 456,
    username: str = "testuser",
    firstName: str = "Test",
    isBot: bool = False,
) -> Mock:
    """
    Create a mock Telegram User.

    Args:
        userId: User ID (default: 456)
        username: Username (default: "testuser")
        firstName: First name (default: "Test")
        isBot: Whether user is a bot (default: False)

    Returns:
        Mock: Configured User instance

    Example:
        user = createMockUser(userId=123, username="john")
        assert user.id == 123
    """
    from tests.fixtures.telegram_mocks import createMockUser as _createUser

    return _createUser(
        userId=userId,
        username=username,
        firstName=firstName,
        isBot=isBot,
    )


def createMockChat(
    chatId: int = 123,
    chatType: str = "private",
    title: Optional[str] = None,
) -> Mock:
    """
    Create a mock Telegram Chat.

    Args:
        chatId: Chat ID (default: 123)
        chatType: Chat type (default: "private")
        title: Chat title for groups (default: None)

    Returns:
        Mock: Configured Chat instance

    Example:
        chat = createMockChat(chatId=123, chatType="group", title="Test Group")
        assert chat.type == "group"
    """
    from tests.fixtures.telegram_mocks import createMockChat as _createChat

    return _createChat(
        chatId=chatId,
        chatType=chatType,
        title=title,
    )


# ============================================================================
# Async Mock Utilities
# ============================================================================


def createAsyncMock(
    returnValue: Any = None,
    sideEffect: Optional[Callable] = None,
    spec: Optional[type] = None,
) -> AsyncMock:
    """
    Create an AsyncMock with optional return value or side effect.

    Args:
        returnValue: Value to return when called (default: None)
        sideEffect: Function to call instead of returning value (default: None)
        spec: Class to use as spec (default: None)

    Returns:
        AsyncMock: Configured async mock

    Example:
        mockFunc = createAsyncMock(returnValue="result")
        result = await mockFunc()
        assert result == "result"
    """
    mock = AsyncMock(spec=spec)

    if sideEffect is not None:
        mock.side_effect = sideEffect
    else:
        mock.return_value = returnValue

    return mock


def createAsyncContextManager(
    enterValue: Any = None,
    exitValue: Any = None,
) -> AsyncMock:
    """
    Create an async context manager mock.

    Args:
        enterValue: Value to return from __aenter__ (default: None)
        exitValue: Value to return from __aexit__ (default: None)

    Returns:
        AsyncMock: Configured async context manager

    Example:
        async with createAsyncContextManager(enterValue="resource") as resource:
            assert resource == "resource"
    """
    mock = AsyncMock()
    mock.__aenter__.return_value = enterValue
    mock.__aexit__.return_value = exitValue
    return mock


# ============================================================================
# Assertion Helpers
# ============================================================================


def assertCalledOnceWithPartial(
    mock: Mock,
    **expectedKwargs: Any,
) -> None:
    """
    Assert mock was called once with at least the specified kwargs.

    This is useful when you want to verify specific arguments without
    checking all arguments.

    Args:
        mock: Mock object to check
        **expectedKwargs: Expected keyword arguments

    Raises:
        AssertionError: If mock wasn't called once or kwargs don't match

    Example:
        mockFunc(a=1, b=2, c=3)
        assertCalledOnceWithPartial(mockFunc, a=1, b=2)  # Passes
        assertCalledOnceWithPartial(mockFunc, a=1, b=99)  # Fails
    """
    assert mock.call_count == 1, f"Expected 1 call, got {mock.call_count}"

    actualKwargs = mock.call_args.kwargs

    for key, expectedValue in expectedKwargs.items():
        assert key in actualKwargs, f"Expected kwarg '{key}' not found in call"
        actualValue = actualKwargs[key]
        assert actualValue == expectedValue, f"Expected {key}={expectedValue}, got {key}={actualValue}"


def assertCalledWithPartial(
    mock: Mock,
    callIndex: int = 0,
    **expectedKwargs: Any,
) -> None:
    """
    Assert mock was called with at least the specified kwargs at given index.

    Args:
        mock: Mock object to check
        callIndex: Index of call to check (default: 0)
        **expectedKwargs: Expected keyword arguments

    Raises:
        AssertionError: If call doesn't exist or kwargs don't match

    Example:
        mockFunc(a=1, b=2)
        mockFunc(a=3, b=4)
        assertCalledWithPartial(mockFunc, callIndex=1, a=3)  # Passes
    """
    assert mock.call_count > callIndex, f"Expected at least {callIndex + 1} calls, got {mock.call_count}"

    actualKwargs = mock.call_args_list[callIndex].kwargs

    for key, expectedValue in expectedKwargs.items():
        assert key in actualKwargs, f"Expected kwarg '{key}' not found in call {callIndex}"
        actualValue = actualKwargs[key]
        assert (
            actualValue == expectedValue
        ), f"Call {callIndex}: Expected {key}={expectedValue}, got {key}={actualValue}"


def assertNotCalled(mock: Mock) -> None:
    """
    Assert mock was not called.

    Args:
        mock: Mock object to check

    Raises:
        AssertionError: If mock was called

    Example:
        mockFunc = Mock()
        assertNotCalled(mockFunc)  # Passes
        mockFunc()
        assertNotCalled(mockFunc)  # Fails
    """
    assert mock.call_count == 0, f"Expected 0 calls, got {mock.call_count}"


def assertCalledNTimes(mock: Mock, n: int) -> None:
    """
    Assert mock was called exactly n times.

    Args:
        mock: Mock object to check
        n: Expected number of calls

    Raises:
        AssertionError: If call count doesn't match

    Example:
        mockFunc()
        mockFunc()
        assertCalledNTimes(mockFunc, 2)  # Passes
    """
    assert mock.call_count == n, f"Expected {n} calls, got {mock.call_count}"


# ============================================================================
# Data Generation Helpers
# ============================================================================


def generateTestMessages(
    count: int = 10,
    chatId: int = 123,
    startUserId: int = 456,
) -> List[Mock]:
    """
    Generate a list of test messages.

    Args:
        count: Number of messages to generate (default: 10)
        chatId: Chat ID for all messages (default: 123)
        startUserId: Starting user ID (default: 456)

    Returns:
        list: List of mock Message objects

    Example:
        messages = generateTestMessages(count=5)
        assert len(messages) == 5
    """
    messages = []

    for i in range(count):
        messages.append(
            createMockMessage(
                messageId=i + 1,
                chatId=chatId,
                userId=startUserId + (i % 3),  # Rotate between 3 users
                text=f"Test message {i + 1}",
            )
        )

    return messages


def generateTestUsers(
    count: int = 5,
    startUserId: int = 456,
) -> List[Mock]:
    """
    Generate a list of test users.

    Args:
        count: Number of users to generate (default: 5)
        startUserId: Starting user ID (default: 456)

    Returns:
        list: List of mock User objects

    Example:
        users = generateTestUsers(count=3)
        assert len(users) == 3
    """
    users = []

    for i in range(count):
        users.append(
            createMockUser(
                userId=startUserId + i,
                username=f"user{i + 1}",
                firstName=f"User{i + 1}",
            )
        )

    return users


# ============================================================================
# Time Utilities
# ============================================================================


def getCurrentTimestamp() -> int:
    """
    Get current Unix timestamp.

    Returns:
        int: Current Unix timestamp

    Example:
        timestamp = getCurrentTimestamp()
        assert timestamp > 0
    """
    return int(datetime.now().timestamp())


def getTimestampDaysAgo(days: int) -> int:
    """
    Get Unix timestamp for n days ago.

    Args:
        days: Number of days in the past

    Returns:
        int: Unix timestamp

    Example:
        timestamp = getTimestampDaysAgo(7)  # 7 days ago
    """
    from datetime import timedelta

    return int((datetime.now() - timedelta(days=days)).timestamp())


def getTimestampHoursAgo(hours: int) -> int:
    """
    Get Unix timestamp for n hours ago.

    Args:
        hours: Number of hours in the past

    Returns:
        int: Unix timestamp

    Example:
        timestamp = getTimestampHoursAgo(2)  # 2 hours ago
    """
    from datetime import timedelta

    return int((datetime.now() - timedelta(hours=hours)).timestamp())


# ============================================================================
# Test Data Helpers
# ============================================================================


def createTestChatSettings(
    model: str = "gpt-4",
    temperature: float = 0.7,
    **extraSettings: Any,
) -> Dict[str, Any]:
    """
    Create test chat settings dictionary.

    Args:
        model: Model name (default: "gpt-4")
        temperature: Temperature (default: 0.7)
        **extraSettings: Additional settings

    Returns:
        dict: Chat settings

    Example:
        settings = createTestChatSettings(model="gpt-3.5-turbo", max_tokens=500)
    """
    settings = {
        "model": model,
        "temperature": temperature,
        "max_tokens": 1000,
    }
    settings.update(extraSettings)
    return settings


def createTestUserData(
    preferences: Optional[Dict[str, Any]] = None,
    **extraData: Any,
) -> Dict[str, Any]:
    """
    Create test user data dictionary.

    Args:
        preferences: User preferences (default: empty dict)
        **extraData: Additional data

    Returns:
        dict: User data

    Example:
        data = createTestUserData(preferences={"lang": "en"}, custom_field="value")
    """
    userData = {
        "preferences": preferences or {},
    }
    userData.update(extraData)
    return userData


# ============================================================================
# Mock Verification Helpers
# ============================================================================


def getMockCallArgs(mock: Mock, callIndex: int = 0) -> tuple:
    """
    Get positional arguments from a specific mock call.

    Args:
        mock: Mock object
        callIndex: Index of call (default: 0)

    Returns:
        tuple: Positional arguments

    Example:
        mockFunc(1, 2, 3)
        args = getMockCallArgs(mockFunc)
        assert args == (1, 2, 3)
    """
    return mock.call_args_list[callIndex].args


def getMockCallKwargs(mock: Mock, callIndex: int = 0) -> Dict[str, Any]:
    """
    Get keyword arguments from a specific mock call.

    Args:
        mock: Mock object
        callIndex: Index of call (default: 0)

    Returns:
        dict: Keyword arguments

    Example:
        mockFunc(a=1, b=2)
        kwargs = getMockCallKwargs(mockFunc)
        assert kwargs == {"a": 1, "b": 2}
    """
    return dict(mock.call_args_list[callIndex].kwargs)


def resetMock(mock: Mock) -> None:
    """
    Reset a mock's call history and side effects.

    Args:
        mock: Mock object to reset

    Example:
        mockFunc()
        assert mockFunc.call_count == 1
        resetMock(mockFunc)
        assert mockFunc.call_count == 0
    """
    mock.reset_mock()
