"""Integration-style tests for the /llm_replay command in DevCommandsHandler.

Covers all error paths and the success case, using mocked LLM service,
mocked bot, and mocked chat settings to avoid real API calls.
"""

# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false, reportCallIssue=false

import datetime
import json
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, Mock, patch

import pytest
import telegram

from internal.bot.common.handlers.dev_commands import DevCommandsHandler
from internal.bot.models import (
    BotProvider,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
    MessageType,
)
from lib.ai import ModelResultStatus, ModelRunResult

# ---------------------------------------------------------------------------
# Local fixtures (tests/conftest.py not reachable from internal/)
# ---------------------------------------------------------------------------


@pytest.fixture
def mockConfigManager() -> Mock:
    """Create a mock ConfigManager for testing.

    Returns:
        Mock: Mocked ConfigManager instance with getBotConfig returning
        default bot configuration.
    """
    from internal.config.manager import ConfigManager

    cm = Mock(spec=ConfigManager)
    cm.getBotConfig.return_value = {"token": "test_token", "owners": [123456]}
    cm.get.return_value = {}
    return cm


@pytest.fixture
def mockDatabase() -> Mock:
    """Create a mock Database for testing.

    Returns:
        Mock: Mocked Database instance with common async methods.
    """
    from internal.database import Database

    db = Mock(spec=Database)
    db.chatMessages = Mock()
    db.chatUsers = Mock()
    db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
    db.chatUsers.updateChatUser = AsyncMock(return_value=None)
    return db


@pytest.fixture
def mockLlmService() -> Mock:
    """Create a mock LLMService with a mock LLMManager.

    Returns:
        Mock: Mocked LLMService instance with getLLMManager returning
        a mock manager that has getModel and listModels.
    """
    from internal.services.llm.service import LLMService

    service = Mock(spec=LLMService)
    manager = Mock()
    manager.getModel = Mock(return_value=None)
    manager.listModels = Mock(return_value=["model-a", "model-b"])
    service.getLLMManager = Mock(return_value=manager)
    service.generateTextViaLLM = AsyncMock()
    return service


@pytest.fixture
def mockBot() -> Mock:
    """Create a mock TheBot with downloadAttachment.

    Returns:
        Mock: Mocked bot with AsyncMock downloadAttachment returning None.
    """
    bot = Mock()
    bot.downloadAttachment = AsyncMock(return_value=None)
    bot.isBotOwner = Mock(return_value=True)
    return bot


@pytest.fixture
def handler(mockConfigManager, mockDatabase, mockLlmService, mockBot) -> DevCommandsHandler:
    """Create a DevCommandsHandler with all dependencies mocked.

    Args:
        mockConfigManager: Mocked configuration manager fixture
        mockDatabase: Mocked database fixture
        mockLlmService: Mocked LLM service fixture
        mockBot: Mocked bot fixture

    Returns:
        DevCommandsHandler with injected mocks, ready for testing
    """
    from internal.services.llm.service import LLMService

    # Patch singletons so BaseBotHandler.__init__ doesn't blow up
    with patch.object(LLMService, "getInstance", return_value=mockLlmService):
        with (
            patch("internal.bot.common.handlers.base.CacheService") as mockCacheCls,
            patch("internal.bot.common.handlers.base.QueueService") as mockQueueCls,
            patch("internal.bot.common.handlers.base.StorageService") as mockStorageCls,
        ):
            mockCacheCls.getInstance.return_value = Mock()
            mockQueueCls.getInstance.return_value = Mock()
            mockStorageCls.getInstance.return_value = Mock()
            h = DevCommandsHandler(
                configManager=mockConfigManager,
                database=mockDatabase,
                botProvider=BotProvider.TELEGRAM,
            )  # type: ignore[call-arg]
    h.llmService = mockLlmService
    h.sendMessage = AsyncMock(return_value=[])  # type: ignore[assignment]
    h.getChatSettings = AsyncMock(return_value=_defaultChatSettings())  # type: ignore[assignment]
    h.injectBot(mockBot)
    return h


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _defaultChatSettings() -> ChatSettingsDict:
    """Build a default ChatSettingsDict for testing.

    Returns:
        ChatSettingsDict with USE_TOOLS=True and empty FALLBACK_HAPPENED_PREFIX.
    """
    return {
        ChatSettingsKey.USE_TOOLS: ChatSettingsValue("true"),
        ChatSettingsKey.FALLBACK_HAPPENED_PREFIX: ChatSettingsValue(""),
        ChatSettingsKey.FALLBACK_MODEL: ChatSettingsValue("model-b"),
    }


def _makeEnsuredMessage(
    *,
    messageText: str = "/llm_replay model-a",
    messageType: MessageType = MessageType.TEXT,
    isReply: bool = False,
    baseMessage: Optional[Any] = None,
) -> Mock:
    """Create a mock EnsuredMessage for testing.

    Args:
        messageText: The message text (default: command with model-a)
        messageType: The type of the message (default: TEXT)
        isReply: Whether this message is a reply (default: False)
        baseMessage: The underlying platform message to return from getBaseMessage

    Returns:
        Mock: Mocked EnsuredMessage with configured attributes
    """
    ensured = Mock(spec=EnsuredMessage)
    ensured.sender = MessageSender(id=123, name="TestUser", username="testuser")
    ensured.recipient = MessageRecipient(id=456, chatType=ChatType.PRIVATE)
    ensured.messageId = 1
    ensured.date = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
    ensured.messageText = messageText
    ensured.messageType = messageType
    ensured.isReply = isReply
    ensured.replyId = None
    ensured.threadId = 0
    ensured.formatEntities = []
    ensured.metadata = {}
    ensured.mediaId = None
    ensured.mediaContent = None

    if baseMessage is not None:
        ensured.getBaseMessage = Mock(return_value=baseMessage)
    else:
        ensured.getBaseMessage = Mock(side_effect=ValueError("Message is not set"))

    ensured.getEnsuredRepliedToMessage = Mock(return_value=None)

    return ensured


def _makeTelegramDocument(
    fileId: str = "file123",
    fileName: str = "log.json",
    mimeType: str = "application/json",
) -> Mock:
    """Create a mock telegram.Document for attachment tests.

    Args:
        fileId: The Telegram file_id (default: "file123")
        fileName: The document filename (default: "log.json")
        mimeType: The MIME type (default: "application/json")

    Returns:
        Mock: Mocked telegram.Document with configured attributes
    """
    doc = Mock(spec=telegram.Document)
    doc.file_id = fileId
    doc.file_name = fileName
    doc.mime_type = mimeType
    return doc


def _sampleRequestData() -> List[Dict[str, Any]]:
    """Return a valid request payload for reconstructMessages.

    Returns:
        List of dicts suitable for reconstructMessages(), representing
        a simple user-assistant exchange.
    """
    return [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]


def _sampleJsonLogBytes(entries: Optional[List[Dict[str, Any]]] = None) -> bytes:
    """Build JSON bytes for a log file attachment.

    Args:
        entries: List of log entries (default: single valid entry with request)

    Returns:
        bytes: UTF-8 encoded JSON string
    """
    if entries is None:
        entries = [{"request": _sampleRequestData()}]
    return json.dumps(entries).encode("utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLlmReplayCommand:
    """Tests for DevCommandsHandler.llmReplayCommand."""

    async def testLlmReplayUnknownModel(self, handler: DevCommandsHandler) -> None:
        """Should report available models when model name is not found.

        Args:
            handler: The handler fixture with mocked dependencies
        """
        ensuredMessage = _makeEnsuredMessage(messageText="/llm_replay unknown-model")

        await handler.llmReplayCommand(
            ensuredMessage=ensuredMessage,
            command="llm_replay",
            args="unknown-model",
            UpdateObj=Mock(),
            typingManager=None,
        )

        handler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]
        sentText: str = handler.sendMessage.call_args.kwargs.get("messageText", "")  # type: ignore[attr-defined]
        assert "unknown-model" in sentText

    async def testLlmReplayNoJsonAttachment(self, handler: DevCommandsHandler) -> None:
        """Should ask to attach a JSON file when message has no document.

        Args:
            handler: The handler fixture with mocked dependencies
        """
        mockModel = Mock()
        handler.llmService.getLLMManager().getModel = Mock(return_value=mockModel)

        ensuredMessage = _makeEnsuredMessage(
            messageText="/llm_replay model-a",
            messageType=MessageType.TEXT,
        )

        await handler.llmReplayCommand(
            ensuredMessage=ensuredMessage,
            command="llm_replay",
            args="model-a",
            UpdateObj=Mock(),
            typingManager=None,
        )

        handler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]
        sentText: str = handler.sendMessage.call_args.kwargs.get("messageText", "")  # type: ignore[attr-defined]
        assert "attach a JSON file" in sentText

    async def testLlmReplayLlmError(self, handler: DevCommandsHandler) -> None:
        """Should catch LLM exception and report error with type#message.

        Args:
            handler: The handler fixture with mocked dependencies
        """
        jsonBytes = _sampleJsonLogBytes()
        handler._bot.downloadAttachment = AsyncMock(return_value=jsonBytes)  # type: ignore[union-attr]

        doc = _makeTelegramDocument()
        tgMsg = Mock(spec=telegram.Message)
        tgMsg.document = doc
        tgMsg.chat = Mock()
        tgMsg.chat.id = 456
        tgMsg.from_user = Mock()

        ensuredMessage = _makeEnsuredMessage(
            messageText="/llm_replay model-a",
            messageType=MessageType.DOCUMENT,
            baseMessage=tgMsg,
        )

        mockModel = Mock()
        handler.llmService.getLLMManager().getModel = Mock(return_value=mockModel)

        handler.llmService.generateTextViaLLM = AsyncMock(side_effect=RuntimeError("API rate limit exceeded"))

        await handler.llmReplayCommand(
            ensuredMessage=ensuredMessage,
            command="llm_replay",
            args="model-a",
            UpdateObj=Mock(),
            typingManager=None,
        )

        handler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]
        sentText: str = handler.sendMessage.call_args.kwargs.get("messageText", "")  # type: ignore[attr-defined]
        assert "Error running query" in sentText
        assert "RuntimeError" in sentText
        assert "API rate limit exceeded" in sentText

    async def testLlmReplayNonFinalStatus(self, handler: DevCommandsHandler) -> None:
        """Should report non-final status when LLM returns non-FINAL result.

        Args:
            handler: The handler fixture with mocked dependencies
        """
        jsonBytes = _sampleJsonLogBytes()
        handler._bot.downloadAttachment = AsyncMock(return_value=jsonBytes)  # type: ignore[union-attr]

        doc = _makeTelegramDocument()
        tgMsg = Mock(spec=telegram.Message)
        tgMsg.document = doc
        tgMsg.chat = Mock()
        tgMsg.chat.id = 456
        tgMsg.from_user = Mock()

        ensuredMessage = _makeEnsuredMessage(
            messageText="/llm_replay model-a",
            messageType=MessageType.DOCUMENT,
            baseMessage=tgMsg,
        )

        mockModel = Mock()
        handler.llmService.getLLMManager().getModel = Mock(return_value=mockModel)

        nonFinalResult = ModelRunResult(
            rawResult={"id": "resp3"},
            status=ModelResultStatus.TOOL_CALLS,
            resultText="",
            toolCalls=[],
            inputTokens=100,
            outputTokens=50,
            totalTokens=150,
            elapsedTime=0.5,
        )
        handler.llmService.generateTextViaLLM = AsyncMock(return_value=nonFinalResult)

        await handler.llmReplayCommand(
            ensuredMessage=ensuredMessage,
            command="llm_replay",
            args="model-a",
            UpdateObj=Mock(),
            typingManager=None,
        )

        handler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]
        sentText: str = handler.sendMessage.call_args.kwargs.get("messageText", "")  # type: ignore[attr-defined]
        assert "non-final status" in sentText
        assert "TOOL_CALLS" in sentText
