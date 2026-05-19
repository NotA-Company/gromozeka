"""Tests for :class:`SandboxHandler`.

These tests exercise the sandbox handler in isolation by:

* Constructing a real :class:`SandboxHandler` with mocked dependencies.
* Mocking ``SandboxManager`` singleton entirely (no real Docker).
* Reusing shared fixtures from ``tests/conftest.py`` for database,
  config, and bot mocking.
* Building real :class:`EnsuredMessage` instances.

No real Docker calls. No real database calls for sandbox operations.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest

from internal.bot.common.handlers.sandbox import SandboxHandler
from internal.bot.models import (
    BotProvider,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
)
from lib.sandbox import (
    FileContent,
    FileInfo,
    RunInfo,
    RunResult,
    RuntimeName,
    SessionBusy,
    SessionNotFound,
)
from lib.sandbox.enums import RunStatus

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _makeConfigManager(*, sandboxEnabled: bool = True) -> Mock:
    """Build a stand-in ConfigManager returning the sandbox section.

    Args:
        sandboxEnabled: Value for sandbox config presence.

    Returns:
        Mock with .get() and .getBotConfig() methods configured.
    """
    from lib.sandbox import SandboxConfig

    cm = Mock()
    cm.getBotConfig = Mock(return_value={"token": "test_token", "owners": [123456]})
    if sandboxEnabled:
        # Create a mock SandboxConfig directly
        mockConfig = Mock(spec=SandboxConfig)
        cm.get = Mock(return_value=mockConfig)
    else:
        cm.get = Mock(return_value=None)
    return cm


def _makeChatSettings(*, allowSandbox: bool = True) -> Dict[ChatSettingsKey, ChatSettingsValue]:
    """Build a chat-settings dict with allow-sandbox key.

    Args:
        allowSandbox: Whether sandbox is allowed for this chat.

    Returns:
        Mapping of relevant ChatSettingsKey to ChatSettingsValue.
    """
    return {ChatSettingsKey.ALLOW_SANDBOX: ChatSettingsValue("true" if allowSandbox else "false")}


def _makeEnsuredMessage(
    *,
    chatId: int = 100,
    messageId: int = 42,
    userId: int = 7,
    senderName: str = "Alice",
    replyText: Optional[str] = None,
) -> EnsuredMessage:
    """Build a minimal EnsuredMessage suitable for handler tests.

    Args:
        chatId: Recipient chat id.
        messageId: Originating message id.
        userId: Sender user id.
        senderName: MessageSender.name value.
        replyText: Optional text from a replied-to message.

    Returns:
        Fully constructed EnsuredMessage.
    """
    em = EnsuredMessage(
        sender=MessageSender(id=userId, name=senderName, username=f"@user{userId}"),
        recipient=MessageRecipient(id=chatId, chatType=ChatType.PRIVATE),
        messageId=messageId,
        date=datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc),
        messageText="",
    )
    # Set replyText attribute manually
    em.replyText = replyText
    return em


def _makeRunResult(
    *,
    exitCode: int = 0,
    stdoutPath: str = "stdout.txt",
    stderrPath: str = "stderr.txt",
    stdoutBytes: int = 0,
    stderrBytes: int = 0,
    error: Optional[str] = None,
) -> RunResult:
    """Build a RunResult for mocking sandbox execution.

    Args:
        exitCode: Process exit code.
        stdoutPath: Path to stdout file.
        stderrPath: Path to stderr file.
        stdoutBytes: Size of stdout.
        stderrBytes: Size of stderr.
        error: Optional error message.

    Returns:
        Configured RunResult instance.
    """
    now = datetime.now(timezone.utc)
    return RunResult(
        runId="test-run-123",
        sessionId="100",
        runtime=RuntimeName.PYTHON,
        stdoutPath=stdoutPath,
        stderrPath=stderrPath,
        stdoutBytes=stdoutBytes,
        stderrBytes=stderrBytes,
        exitCode=exitCode,
        signal=None,
        timedOut=False,
        oomKilled=False,
        startedAt=now,
        finishedAt=now,
        elapsedMs=100,
        networkEnabled=False,
        error=error,
    )


def _makeFileInfo(path: str, sizeBytes: int, isDirectory: bool = False) -> FileInfo:
    """Build a FileInfo for mocking file listings.

    Args:
        path: File path.
        sizeBytes: File size.
        isDirectory: Whether entry is a directory.

    Returns:
        Configured FileInfo instance.
    """
    return FileInfo(path=path, sizeBytes=sizeBytes, modifiedAt=datetime.now(timezone.utc), isDirectory=isDirectory)


def _makeHandler(
    *,
    configManager: Optional[Mock] = None,
    chatSettings: Optional[Dict[ChatSettingsKey, ChatSettingsValue]] = None,
    mockSandboxManager: Optional[AsyncMock] = None,
    sandboxEnabled: bool = True,
) -> tuple:
    """Construct a SandboxHandler with stubs ready for tests.

    Args:
        configManager: Optional preconfigured config-manager stub.
        chatSettings: Optional override for the chat-settings dict.
        mockSandboxManager: Optional preconfigured sandbox manager mock.
        sandboxEnabled: Whether sandbox is enabled at the handler level.

    Returns:
        Tuple (handler, mocks) where mocks is a dict of injected mocks.
    """
    cm = configManager if configManager is not None else _makeConfigManager(sandboxEnabled=sandboxEnabled)

    # Mock database with minimal setup
    db = Mock()
    db.getChatSettings = AsyncMock(return_value={})
    db.getUserData = AsyncMock(return_value={})
    db.getChatMessages = AsyncMock(return_value=[])

    # Create handler
    handler = SandboxHandler(
        configManager=cm,
        database=db,
        botProvider=BotProvider.TELEGRAM,
    )

    # Set sandboxEnabled if config has sandbox section
    if sandboxEnabled and (configManager is not None or cm.get("sandbox") is not None):
        handler.sandboxEnabled = True
    else:
        handler.sandboxEnabled = False

    # Stub getChatSettings and sendMessage
    cs = chatSettings if chatSettings is not None else _makeChatSettings()
    getChatSettingsMock = AsyncMock(return_value=cs)
    cast(Any, handler).getChatSettings = getChatSettingsMock

    sendMessageMock = AsyncMock(return_value=[])
    cast(Any, handler).sendMessage = sendMessageMock

    # Set up sandbox manager mock if not provided
    if mockSandboxManager is None:
        mockSandboxManager = AsyncMock()
        mockSandboxManager.runCode = AsyncMock(return_value=_makeRunResult())
        mockSandboxManager.listFiles = AsyncMock(return_value=[])
        mockSandboxManager.readFile = AsyncMock(
            return_value=FileContent(path="test.txt", sizeBytes=10, bytesRead=10, truncated=False, content="hello")
        )
        mockSandboxManager.listRunsForSession = AsyncMock(return_value=[])
        mockSandboxManager.installRuntimeLibraries = AsyncMock(return_value=True)
        mockSandboxManager.listSessions = AsyncMock(return_value=[])

    mocks: Dict[str, Any] = {
        "getChatSettings": getChatSettingsMock,
        "sendMessage": sendMessageMock,
        "sandboxManager": mockSandboxManager,
    }
    return handler, mocks


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mockSandboxManager():
    """Mock SandboxManager singleton with all required async methods.

    This fixture provides a fresh mock for each test, ensuring no state
    leaks between tests. The mock is automatically patched into the
    SandboxManager singleton.

    Yields:
        AsyncMock: Configured sandbox manager mock.
    """
    from lib.sandbox import SandboxConfig, SandboxManager

    mock = AsyncMock()

    # Configure all async methods used by the handler
    mock.runCode = AsyncMock(return_value=_makeRunResult())
    mock.listFiles = AsyncMock(return_value=[])
    mock.readFile = AsyncMock(
        return_value=FileContent(path="test.txt", sizeBytes=10, bytesRead=10, truncated=False, content="")
    )
    mock.listRunsForSession = AsyncMock(return_value=[])
    mock.installRuntimeLibraries = AsyncMock(return_value=True)
    mock.listSessions = AsyncMock(return_value=[])

    # Reset singleton before patching
    SandboxManager._instance = None
    SandboxManager._configInstance = None

    with (
        patch("lib.sandbox.SandboxConfig.fromDict") as mockFromDict,
        patch("lib.sandbox.SandboxManager.getInstance", return_value=mock),
    ):
        # Make fromDict return a mock SandboxConfig
        mockConfig = Mock(spec=SandboxConfig)
        mockFromDict.return_value = mockConfig
        yield mock

    # Reset singleton after test
    SandboxManager._instance = None
    SandboxManager._configInstance = None


# ---------------------------------------------------------------------------
# Test Suite
# ---------------------------------------------------------------------------


# 1. Command access gating tests


async def test_run_command_gated_when_sandbox_not_configured(mockSandboxManager: AsyncMock) -> None:
    """Test /run command is blocked when sandbox is not configured globally."""
    handler, mocks = _makeHandler(sandboxEnabled=False, chatSettings=_makeChatSettings(allowSandbox=True))
    em = _makeEnsuredMessage()

    await cast(Any, handler).run_command(em, "run", 'print("hello")', Mock(), None)

    # Verify no sandbox execution
    mockSandboxManager.runCode.assert_not_called()

    # Verify error message sent
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "not configured" in sendKwargs["messageText"]


async def test_run_command_gated_when_allow_sandbox_false(mockSandboxManager: AsyncMock) -> None:
    """Test /run command is blocked when allow-sandbox setting is False."""
    handler, mocks = _makeHandler(chatSettings=_makeChatSettings(allowSandbox=False))
    em = _makeEnsuredMessage()

    await cast(Any, handler).run_command(em, "run", 'print("hello")', Mock(), None)

    # Verify no sandbox execution
    mockSandboxManager.runCode.assert_not_called()

    # Verify error message sent
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "not enabled for this chat" in sendKwargs["messageText"]


async def test_run_command_allowed_when_allow_sandbox_true(mockSandboxManager: AsyncMock) -> None:
    """Test /run command proceeds when allow-sandbox setting is True."""
    handler, mocks = _makeHandler(chatSettings=_makeChatSettings(allowSandbox=True))
    em = _makeEnsuredMessage()

    # Mock successful execution with stdout
    mockResult = _makeRunResult(exitCode=0, stdoutBytes=5, stderrBytes=0)
    mockSandboxManager.runCode = AsyncMock(return_value=mockResult)
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(path="stdout.txt", sizeBytes=5, bytesRead=5, truncated=False, content="hello")
    )

    await cast(Any, handler).run_command(em, "run", 'print("hello")', Mock(), None)

    # Verify sandbox execution occurred
    mockSandboxManager.runCode.assert_called_once()

    # Verify result message sent
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "hello" in sendKwargs["messageText"]


async def test_sandbox_command_gated_when_allow_sandbox_false(mockSandboxManager: AsyncMock) -> None:
    """Test /sandbox files command is blocked when allow-sandbox setting is False."""
    handler, mocks = _makeHandler(chatSettings=_makeChatSettings(allowSandbox=False))
    em = _makeEnsuredMessage()

    await cast(Any, handler).sandbox_command(em, "sandbox", "files", Mock(), None)

    # Verify no sandbox operation
    mockSandboxManager.listFiles.assert_not_called()

    # Verify error message sent
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "not enabled for this chat" in sendKwargs["messageText"]


async def test_sandbox_command_allowed_when_allow_sandbox_true(mockSandboxManager: AsyncMock) -> None:
    """Test /sandbox files command proceeds when allow-sandbox setting is True."""
    handler, mocks = _makeHandler(chatSettings=_makeChatSettings(allowSandbox=True))
    em = _makeEnsuredMessage()

    # Mock file listing
    mockSandboxManager.listFiles = AsyncMock(
        return_value=[
            _makeFileInfo("main.py", 1024, isDirectory=False),
        ]
    )

    await cast(Any, handler).sandbox_command(em, "sandbox", "files", Mock(), None)

    # Verify sandbox operation occurred
    mockSandboxManager.listFiles.assert_called_once()

    # Verify result message sent
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "main.py" in sendKwargs["messageText"]


# 2. /run command tests


async def test_run_with_code_arg(mockSandboxManager: AsyncMock) -> None:
    """Test /run with code argument executes and displays output."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    # Mock successful execution with stdout
    mockResult = _makeRunResult(exitCode=0, stdoutBytes=5, stderrBytes=0)
    mockSandboxManager.runCode = AsyncMock(return_value=mockResult)
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(path="stdout.txt", sizeBytes=5, bytesRead=5, truncated=False, content="hello")
    )

    await cast(Any, handler).run_command(em, "run", 'print("hello")', Mock(), None)

    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "hello" in sendKwargs["messageText"]
    assert "Exit code: 0" in sendKwargs["messageText"]


async def test_run_with_replied_message(mockSandboxManager: AsyncMock) -> None:
    """Test /run with no args but replied message extracts code."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage(replyText='print("world")')

    # Mock successful execution
    mockResult = _makeRunResult(exitCode=0, stdoutBytes=5, stderrBytes=0)
    mockSandboxManager.runCode = AsyncMock(return_value=mockResult)
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(path="stdout.txt", sizeBytes=5, bytesRead=5, truncated=False, content="world")
    )

    await cast(Any, handler).run_command(em, "run", "", Mock(), None)

    # Verify code was extracted from reply
    mockSandboxManager.runCode.assert_called_once()
    callArgs = mockSandboxManager.runCode.call_args
    assert callArgs[1]["code"] == 'print("world")'


async def test_run_no_code(mockSandboxManager: AsyncMock) -> None:
    """Test /run with no args and no reply shows usage hint."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    await cast(Any, handler).run_command(em, "run", "", Mock(), None)

    # Verify no runCode call
    mockSandboxManager.runCode.assert_not_called()

    # Verify error message
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "Usage" in sendKwargs["messageText"]


async def test_run_session_busy(mockSandboxManager: AsyncMock) -> None:
    """Test /run when session busy shows error."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    # Mock SessionBusy error
    mockSandboxManager.runCode = AsyncMock(side_effect=SessionBusy("Session busy"))

    await cast(Any, handler).run_command(em, "run", 'print("test")', Mock(), None)

    # Verify error message
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "busy" in sendKwargs["messageText"].lower()


# 3. /sandbox files tests


async def test_sandbox_files_lists_files(mockSandboxManager: AsyncMock) -> None:
    """Test /sandbox files displays file list."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    # Mock file listing
    mockSandboxManager.listFiles = AsyncMock(
        return_value=[
            _makeFileInfo("main.py", 1024, isDirectory=False),
            _makeFileInfo("data.txt", 512, isDirectory=False),
            _makeFileInfo("src", sizeBytes=0, isDirectory=True),
        ]
    )

    await cast(Any, handler).sandbox_command(em, "sandbox", "files", Mock(), None)

    # Verify formatted output
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    msgText = sendKwargs["messageText"]
    assert "main.py" in msgText
    assert "[FILE]" in msgText
    assert "[DIR]" in msgText


async def test_sandbox_files_empty(mockSandboxManager: AsyncMock) -> None:
    """Test /sandbox files with empty directory shows message."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    # Mock empty listing
    mockSandboxManager.listFiles = AsyncMock(return_value=[])

    await cast(Any, handler).sandbox_command(em, "sandbox", "files", Mock(), None)

    # Verify empty message
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "No files" in sendKwargs["messageText"]


# 4. /sandbox read tests


async def test_sandbox_read_file(mockSandboxManager: AsyncMock) -> None:
    """Test /sandbox read displays file content."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    # Mock file read - FileContent needs to be structured properly
    fileContentText = "print('hello')"
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(
            path="test.py",
            sizeBytes=len(fileContentText),
            bytesRead=len(fileContentText),
            truncated=False,
            content=fileContentText,
        )
    )

    await cast(Any, handler).sandbox_command(em, "sandbox", "read test.py", Mock(), None)

    # Verify formatted output
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    msgText = sendKwargs["messageText"]
    assert "test.py" in msgText
    assert "hello" in msgText


async def test_sandbox_read_not_found(mockSandboxManager: AsyncMock) -> None:
    """Test /sandbox read with non-existent file shows error."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    # Mock FileNotFoundError
    mockSandboxManager.readFile = AsyncMock(side_effect=FileNotFoundError("File not found"))

    await cast(Any, handler).sandbox_command(em, "sandbox", "read missing.py", Mock(), None)

    # Verify error message
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "not found" in sendKwargs["messageText"].lower()


# 5. /sandbox status tests


async def test_sandbox_status_with_session(mockSandboxManager: AsyncMock) -> None:
    """Test /sandbox status shows session info."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    # Mock run history
    now = datetime.now(timezone.utc)
    mockRun = RunInfo(
        runId="run-123",
        sessionId="100",
        runtime=RuntimeName.PYTHON,
        startedAt=now,
        finishedAt=now,
        status=RunStatus.COMPLETED,
        exitCode=0,
    )
    mockSandboxManager.listRunsForSession = AsyncMock(return_value=[mockRun])

    await cast(Any, handler).sandbox_command(em, "sandbox", "status", Mock(), None)

    # Verify session info displayed
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    msgText = sendKwargs["messageText"]
    assert "Total runs: 1" in msgText


async def test_sandbox_status_no_session(mockSandboxManager: AsyncMock) -> None:
    """Test /sandbox status with no session shows message."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    # Mock SessionNotFound
    mockSandboxManager.listRunsForSession = AsyncMock(side_effect=SessionNotFound("No session"))

    await cast(Any, handler).sandbox_command(em, "sandbox", "status", Mock(), None)

    # Verify no session message
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "No active" in sendKwargs["messageText"]


# 6. /sandbox install tests


async def test_sandbox_install_admin(mockSandboxManager: AsyncMock) -> None:
    """Test /sandbox install as admin succeeds."""
    # Create handler with bot owner as sender
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage(userId=123456)  # Bot owner ID from config

    # Mock bot instance for isBotOwner check
    from telegram.ext import ExtBot

    handler._bot = Mock(spec=ExtBot)
    handler._bot.id = 123456  # Bot ID
    handler.isBotOwner = Mock(return_value=True)

    # Mock successful install
    mockSandboxManager.installRuntimeLibraries = AsyncMock(return_value=True)

    await cast(Any, handler).sandbox_command(em, "sandbox", "install numpy pandas", Mock(), None)

    # Verify install called with packages
    mockSandboxManager.installRuntimeLibraries.assert_called_once()
    callArgs = mockSandboxManager.installRuntimeLibraries.call_args
    assert callArgs[1]["packages"] == ["numpy", "pandas"]


async def test_sandbox_install_not_admin(mockSandboxManager: AsyncMock) -> None:
    """Test /sandbox install as non-admin shows error."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage(userId=999)  # Not a bot owner

    # Mock bot instance for isBotOwner check
    from telegram.ext import ExtBot

    handler._bot = Mock(spec=ExtBot)
    handler._bot.id = 123456  # Bot ID
    handler.isBotOwner = Mock(return_value=False)

    await cast(Any, handler).sandbox_command(em, "sandbox", "install numpy", Mock(), None)

    # Verify install not called
    mockSandboxManager.installRuntimeLibraries.assert_not_called()

    # Verify authorization error
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "not authorized" in sendKwargs["messageText"].lower() or "restricted" in sendKwargs["messageText"].lower()
