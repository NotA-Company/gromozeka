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
    workDir: str = "",
    error: Optional[str] = None,
) -> RunResult:
    """Build a RunResult for mocking sandbox execution.

    Args:
        exitCode: Process exit code.
        stdoutPath: Path to stdout file.
        stderrPath: Path to stderr file.
        stdoutBytes: Size of stdout.
        stderrBytes: Size of stderr.
        workDir: Per-run working directory path.
        error: Optional error message.

    Returns:
        Configured RunResult instance.
    """
    now = datetime.now(timezone.utc)
    return RunResult(
        runId="test-run-123",
        sessionId="100",
        workDir=workDir,
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


# ---------------------------------------------------------------------------
# 7. run_command file scanning tests
# ---------------------------------------------------------------------------


async def test_run_command_shows_created_files(mockSandboxManager: AsyncMock) -> None:
    """Test /run command includes 'Created files:' section when workDir has files."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    mockResult = _makeRunResult(exitCode=0, stdoutBytes=5, stderrBytes=0, workDir=".run/test-run-123/work")
    mockSandboxManager.runCode = AsyncMock(return_value=mockResult)
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(path="stdout.txt", sizeBytes=5, bytesRead=5, truncated=False, content="hello")
    )
    mockSandboxManager.listFiles = AsyncMock(
        return_value=[
            _makeFileInfo("output.csv", 2048, isDirectory=False),
            _makeFileInfo("plots", 0, isDirectory=True),
        ]
    )

    await cast(Any, handler).run_command(em, "run", 'print("hello")', Mock(), None)

    # Verify sendMessage was called with "Created files:" section
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    msgText = sendKwargs["messageText"]
    assert "Created files:" in msgText
    assert "output.csv" in msgText
    assert "plots" in msgText


async def test_run_command_no_files_section_when_workdir_empty(mockSandboxManager: AsyncMock) -> None:
    """Test /run command does not add 'Created files:' when workDir is empty string."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    mockResult = _makeRunResult(exitCode=0, stdoutBytes=5, stderrBytes=0, workDir="")
    mockSandboxManager.runCode = AsyncMock(return_value=mockResult)
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(path="stdout.txt", sizeBytes=5, bytesRead=5, truncated=False, content="hello")
    )

    await cast(Any, handler).run_command(em, "run", 'print("hello")', Mock(), None)

    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "Created files:" not in sendKwargs["messageText"]


async def test_run_command_no_files_section_when_list_empty(mockSandboxManager: AsyncMock) -> None:
    """Test /run command does not add 'Created files:' when listFiles returns empty list."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    mockResult = _makeRunResult(exitCode=0, stdoutBytes=5, stderrBytes=0, workDir=".run/test-run-123/work")
    mockSandboxManager.runCode = AsyncMock(return_value=mockResult)
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(path="stdout.txt", sizeBytes=5, bytesRead=5, truncated=False, content="hello")
    )
    mockSandboxManager.listFiles = AsyncMock(return_value=[])

    await cast(Any, handler).run_command(em, "run", 'print("hello")', Mock(), None)

    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "Created files:" not in sendKwargs["messageText"]


# ---------------------------------------------------------------------------
# 8. _llmToolRunSandboxCode files key tests
# ---------------------------------------------------------------------------


async def test_llm_tool_run_includes_files_key(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolRunSandboxCode includes 'files' key in response when workDir has files."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    mockResult = _makeRunResult(exitCode=0, stdoutBytes=0, stderrBytes=0, workDir=".run/test-run-123/work")
    mockSandboxManager.runCode = AsyncMock(return_value=mockResult)
    mockSandboxManager.listFiles = AsyncMock(
        return_value=[
            _makeFileInfo("data.json", 256, isDirectory=False),
        ]
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolRunSandboxCode(extraData, code="import json; print('hi')")

    assert result["done"] is True
    assert "files" in result
    assert len(result["files"]) == 1
    assert result["files"][0]["path"] == "data.json"
    assert result["files"][0]["sizeBytes"] == 256
    assert result["files"][0]["isDirectory"] is False


async def test_llm_tool_run_no_files_key_when_workdir_empty(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolRunSandboxCode omits 'files' key when workDir is empty."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    mockResult = _makeRunResult(exitCode=0, stdoutBytes=0, stderrBytes=0, workDir="")
    mockSandboxManager.runCode = AsyncMock(return_value=mockResult)

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolRunSandboxCode(extraData, code="print('hi')")

    assert result["done"] is True
    assert "files" not in result


# ---------------------------------------------------------------------------
# 9. _llmToolSandboxListFiles LLM tool tests
# ---------------------------------------------------------------------------


async def test_sandbox_list_files_returns_dict(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxListFiles returns correct dict with file list."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    mockSandboxManager.listFiles = AsyncMock(
        return_value=[
            _makeFileInfo("main.py", 1024, isDirectory=False),
            _makeFileInfo("src", 0, isDirectory=True),
        ]
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxListFiles(extraData, path=".", recursive=True)

    parsed = result
    assert parsed["done"] is True
    assert parsed["path"] == "."
    assert parsed["recursive"] is True
    assert len(parsed["files"]) == 2
    assert parsed["files"][0]["path"] == "main.py"
    assert parsed["files"][0]["sizeBytes"] == 1024
    assert parsed["files"][0]["isDirectory"] is False
    assert parsed["files"][1]["isDirectory"] is True


async def test_sandbox_list_files_missing_context(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxListFiles returns error when extraData is None."""

    handler, mocks = _makeHandler()

    result = await handler._llmToolSandboxListFiles(None, path=".", recursive=False)

    parsed = result
    assert parsed["done"] is False
    assert "Missing chat context" in parsed["error"]


async def test_sandbox_list_files_gated_when_sandbox_not_configured(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxListFiles returns error when sandbox is not configured globally."""

    handler, mocks = _makeHandler(sandboxEnabled=False, chatSettings=_makeChatSettings(allowSandbox=True))
    em = _makeEnsuredMessage()

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxListFiles(extraData, path=".", recursive=False)

    parsed = result
    assert parsed["done"] is False
    assert "not configured" in parsed["error"]
    mockSandboxManager.listFiles.assert_not_called()


async def test_sandbox_list_files_gated_when_allow_sandbox_false(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxListFiles returns error when allow-sandbox setting is False."""

    handler, mocks = _makeHandler(chatSettings=_makeChatSettings(allowSandbox=False))
    em = _makeEnsuredMessage()

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxListFiles(extraData, path=".", recursive=False)

    parsed = result
    assert parsed["done"] is False
    assert "not enabled" in parsed["error"]
    mockSandboxManager.listFiles.assert_not_called()


# ---------------------------------------------------------------------------
# 10. _llmToolSandboxReadFile LLM tool tests
# ---------------------------------------------------------------------------


async def test_sandbox_read_file_returns_dict(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxReadFile returns correct dict with file content."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    fileContentText = "line1\nline2\nline3\n"
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(
            path="test.py",
            sizeBytes=len(fileContentText),
            bytesRead=len(fileContentText),
            truncated=False,
            content=fileContentText,
        )
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxReadFile(extraData, path="test.py")

    parsed = result
    assert parsed["done"] is True
    assert parsed["path"] == "test.py"
    assert parsed["totalLines"] == 3
    assert parsed["offset"] == 0
    assert parsed["limit"] is None
    assert parsed["returnedLines"] == 3
    assert parsed["truncated"] is False
    assert parsed["content"] == "line1\nline2\nline3\n"


async def test_sandbox_read_file_with_offset_and_limit(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxReadFile applies offset and limit slicing correctly."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    fileContentText = "line0\nline1\nline2\nline3\nline4\n"
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(
            path="data.txt",
            sizeBytes=len(fileContentText),
            bytesRead=len(fileContentText),
            truncated=False,
            content=fileContentText,
        )
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxReadFile(extraData, path="data.txt", offset=1, limit=2)

    parsed = result
    assert parsed["done"] is True
    assert parsed["totalLines"] == 5
    assert parsed["offset"] == 1
    assert parsed["limit"] == 2
    assert parsed["returnedLines"] == 2
    assert parsed["truncated"] is True  # offset > 0 and offset+limit < totalLines
    assert parsed["content"] == "line1\nline2\n"


async def test_sandbox_read_file_offset_past_end(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxReadFile with offset > totalLines returns empty content."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    fileContentText = "line0\nline1\n"
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(
            path="short.txt",
            sizeBytes=len(fileContentText),
            bytesRead=len(fileContentText),
            truncated=False,
            content=fileContentText,
        )
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxReadFile(extraData, path="short.txt", offset=10)

    parsed = result
    assert parsed["done"] is True
    assert parsed["totalLines"] == 2
    assert parsed["returnedLines"] == 0
    assert parsed["content"] == ""


async def test_sandbox_read_file_limit_zero(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxReadFile with limit=0 returns empty content."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    fileContentText = "line0\nline1\n"
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(
            path="data.txt",
            sizeBytes=len(fileContentText),
            bytesRead=len(fileContentText),
            truncated=False,
            content=fileContentText,
        )
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxReadFile(extraData, path="data.txt", offset=0, limit=0)

    parsed = result
    assert parsed["done"] is True
    assert parsed["returnedLines"] == 0
    assert parsed["content"] == ""


async def test_sandbox_read_file_empty_file(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxReadFile with an empty file."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(path="empty.txt", sizeBytes=0, bytesRead=0, truncated=False, content="")
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxReadFile(extraData, path="empty.txt")

    parsed = result
    assert parsed["done"] is True
    assert parsed["totalLines"] == 0
    assert parsed["content"] == ""


async def test_sandbox_read_file_not_found(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxReadFile with non-existent file returns error dict."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    mockSandboxManager.readFile = AsyncMock(side_effect=FileNotFoundError("not found"))

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxReadFile(extraData, path="missing.txt")

    parsed = result
    assert parsed["done"] is False
    assert "not found" in parsed["error"].lower()


async def test_sandbox_read_file_bytes_content(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxReadFile handles bytes content from readFile (encoding=None case)."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    rawContent = b"hello world\n"
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(
            path="binary.dat", sizeBytes=len(rawContent), bytesRead=len(rawContent), truncated=False, content=rawContent
        )
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxReadFile(extraData, path="binary.dat")

    parsed = result
    assert parsed["done"] is True
    assert "hello world" in parsed["content"]
    # Verify readFile was called with encoding=None
    mockSandboxManager.readFile.assert_called_once()
    callKwargs = mockSandboxManager.readFile.call_args.kwargs
    assert callKwargs["encoding"] is None


async def test_sandbox_read_file_gated_when_sandbox_not_configured(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxReadFile returns error when sandbox is not configured globally."""

    handler, mocks = _makeHandler(sandboxEnabled=False, chatSettings=_makeChatSettings(allowSandbox=True))
    em = _makeEnsuredMessage()

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxReadFile(extraData, path="test.txt")

    parsed = result
    assert parsed["done"] is False
    assert "not configured" in parsed["error"]
    mockSandboxManager.readFile.assert_not_called()


async def test_sandbox_read_file_gated_when_allow_sandbox_false(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxReadFile returns error when allow-sandbox setting is False."""

    handler, mocks = _makeHandler(chatSettings=_makeChatSettings(allowSandbox=False))
    em = _makeEnsuredMessage()

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxReadFile(extraData, path="test.txt")

    parsed = result
    assert parsed["done"] is False
    assert "not enabled" in parsed["error"]
    mockSandboxManager.readFile.assert_not_called()


async def test_sandbox_read_file_negative_offset(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxReadFile rejects negative offset values."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxReadFile(extraData, path="test.txt", offset=-1)

    parsed = result
    assert parsed["done"] is False
    assert "offset must be >= 0" in parsed["error"]
    mockSandboxManager.readFile.assert_not_called()


async def test_sandbox_read_file_negative_limit(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxReadFile rejects negative limit values."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxReadFile(extraData, path="test.txt", limit=-5)

    parsed = result
    assert parsed["done"] is False
    assert "limit must be >= 0" in parsed["error"]
    mockSandboxManager.readFile.assert_not_called()


async def test_sandbox_read_file_truncated_from_readfile(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxReadFile reflects byte-level truncation from readFile in response."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    fileContentText = "line0\nline1\n"
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(
            path="big.txt",
            sizeBytes=100000,
            bytesRead=65536,
            truncated=True,
            content=fileContentText,
        )
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxReadFile(extraData, path="big.txt")

    parsed = result
    assert parsed["done"] is True
    assert parsed["truncated"] is True
    assert parsed["bytesRead"] == 65536


async def test_sandbox_read_file_non_utf8_content(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxReadFile handles non-UTF-8 bytes with replacement characters."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    rawContent = b"hello \xff\xfe world\n"
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(
            path="binary.dat", sizeBytes=len(rawContent), bytesRead=len(rawContent), truncated=False, content=rawContent
        )
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxReadFile(extraData, path="binary.dat")

    parsed = result
    assert parsed["done"] is True
    assert "hello" in parsed["content"]
    assert "world" in parsed["content"]
    # Verify readFile was called with encoding=None
    callKwargs = mockSandboxManager.readFile.call_args.kwargs
    assert callKwargs["encoding"] is None


# ---------------------------------------------------------------------------
# 11. _llmToolSandboxSendFile LLM tool tests
# ---------------------------------------------------------------------------


async def test_sandbox_send_file_mime_detection(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxSendFile detects MIME type and routes to correct MessageType."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    # Create a minimal valid PNG that python-magic can detect
    # 8-byte PNG signature + IHDR chunk header
    pngSignature = b"\x89PNG\r\n\x1a\n"
    ihdrChunk = b"\x00\x00\x00\rIHDR" + b"\x00" * 13 + b"\x00" * 4  # IHDR data + CRC placeholder
    imageData = pngSignature + ihdrChunk + b"\x00" * 100
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(
            path="chart.png", sizeBytes=len(imageData), bytesRead=len(imageData), truncated=False, content=imageData
        )
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxSendFile(extraData, path="chart.png", caption="Here is the chart")

    parsed = result
    assert parsed["done"] is True
    assert parsed["path"] == "chart.png"
    assert parsed["mimeType"] == "image/png"
    assert parsed["messageType"] == "image"
    assert parsed["captionSent"] is True

    # Verify sendMessage called with attachment
    mocks["sendMessage"].assert_called_once()
    callKwargs = mocks["sendMessage"].call_args.kwargs
    assert callKwargs["attachmentList"] is not None
    assert len(callKwargs["attachmentList"]) == 1
    attachmentData, attachmentType, attachmentName = callKwargs["attachmentList"][0]
    assert attachmentName == "chart.png"
    assert callKwargs["messageText"] == "Here is the chart"

    # Verify readFile was called with encoding=None
    mockSandboxManager.readFile.assert_called_once()
    readFileKwargs = mockSandboxManager.readFile.call_args.kwargs
    assert readFileKwargs["encoding"] is None


async def test_sandbox_send_file_size_limit(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxSendFile rejects files exceeding MAX_SANDBOX_SEND_BYTES."""

    from internal.bot.common.handlers.sandbox import MAX_SANDBOX_SEND_BYTES

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    largeSize = MAX_SANDBOX_SEND_BYTES + 1
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(
            path="big.zip",
            sizeBytes=largeSize,
            bytesRead=MAX_SANDBOX_SEND_BYTES + 1,
            truncated=True,
            content=b"\x00" * 100,
        )
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxSendFile(extraData, path="big.zip")

    parsed = result
    assert parsed["done"] is False
    assert "too large" in parsed["error"].lower()

    # Verify sendMessage was NOT called
    mocks["sendMessage"].assert_not_called()


async def test_sandbox_send_file_not_found(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxSendFile with non-existent file returns error dict."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    mockSandboxManager.readFile = AsyncMock(side_effect=FileNotFoundError("not found"))

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxSendFile(extraData, path="missing.png")

    parsed = result
    assert parsed["done"] is False
    assert "not found" in parsed["error"].lower()


async def test_sandbox_send_file_document_fallback(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxSendFile falls back to DOCUMENT for unknown MIME types."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    csvData = b"a,b,c\n1,2,3\n"
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(
            path="data.csv", sizeBytes=len(csvData), bytesRead=len(csvData), truncated=False, content=csvData
        )
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxSendFile(extraData, path="data.csv")

    parsed = result
    assert parsed["done"] is True
    assert parsed["messageType"] == "document"


async def test_sandbox_send_file_no_caption(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxSendFile without caption passes None as messageText."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    pdfData = b"%PDF-1.4" + b"\x00" * 100
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(
            path="report.pdf", sizeBytes=len(pdfData), bytesRead=len(pdfData), truncated=False, content=pdfData
        )
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxSendFile(extraData, path="report.pdf")

    parsed = result
    assert parsed["done"] is True
    assert parsed["captionSent"] is False

    # Verify sendMessage called with no message text
    callKwargs = mocks["sendMessage"].call_args.kwargs
    assert callKwargs["messageText"] is None


async def test_sandbox_send_file_str_content(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxSendFile encodes str content to bytes before MIME detection."""

    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    textContent = "hello world"
    mockSandboxManager.readFile = AsyncMock(
        return_value=FileContent(
            path="hello.txt",
            sizeBytes=len(textContent),
            bytesRead=len(textContent),
            truncated=False,
            content=textContent,
        )
    )

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxSendFile(extraData, path="hello.txt")

    parsed = result
    assert parsed["done"] is True

    # Verify sendMessage was called and attachment data is bytes
    mocks["sendMessage"].assert_called_once()
    callKwargs = mocks["sendMessage"].call_args.kwargs
    attachmentData, _, _ = callKwargs["attachmentList"][0]
    assert isinstance(attachmentData, bytes)


async def test_sandbox_send_file_gated_when_sandbox_not_configured(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxSendFile returns error when sandbox is not configured globally."""

    handler, mocks = _makeHandler(sandboxEnabled=False, chatSettings=_makeChatSettings(allowSandbox=True))
    em = _makeEnsuredMessage()

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxSendFile(extraData, path="test.txt")

    parsed = result
    assert parsed["done"] is False
    assert "not configured" in parsed["error"]
    mockSandboxManager.readFile.assert_not_called()


async def test_sandbox_send_file_gated_when_allow_sandbox_false(mockSandboxManager: AsyncMock) -> None:
    """Test _llmToolSandboxSendFile returns error when allow-sandbox setting is False."""

    handler, mocks = _makeHandler(chatSettings=_makeChatSettings(allowSandbox=False))
    em = _makeEnsuredMessage()

    extraData: Dict[str, Any] = {"ensuredMessage": em}
    result = await handler._llmToolSandboxSendFile(extraData, path="test.txt")

    parsed = result
    assert parsed["done"] is False
    assert "not enabled" in parsed["error"]
    mockSandboxManager.readFile.assert_not_called()


# ---------------------------------------------------------------------------
# 12. _mimeToMessageType static helper tests
# ---------------------------------------------------------------------------


def test_mime_to_message_type_image() -> None:
    """Test _mimeToMessageType maps image MIME types correctly."""
    from internal.models.shared_enums import MessageType

    assert SandboxHandler._mimeToMessageType("image/png") == MessageType.IMAGE
    assert SandboxHandler._mimeToMessageType("image/jpeg") == MessageType.IMAGE
    assert SandboxHandler._mimeToMessageType("image/gif") == MessageType.IMAGE


def test_mime_to_message_type_video() -> None:
    """Test _mimeToMessageType maps video MIME types correctly."""
    from internal.models.shared_enums import MessageType

    assert SandboxHandler._mimeToMessageType("video/mp4") == MessageType.VIDEO
    assert SandboxHandler._mimeToMessageType("video/webm") == MessageType.VIDEO


def test_mime_to_message_type_audio() -> None:
    """Test _mimeToMessageType maps audio MIME types correctly."""
    from internal.models.shared_enums import MessageType

    assert SandboxHandler._mimeToMessageType("audio/mpeg") == MessageType.AUDIO
    assert SandboxHandler._mimeToMessageType("audio/wav") == MessageType.AUDIO


def test_mime_to_message_type_document_fallback() -> None:
    """Test _mimeToMessageType defaults to DOCUMENT for unknown types."""
    from internal.models.shared_enums import MessageType

    assert SandboxHandler._mimeToMessageType("application/pdf") == MessageType.DOCUMENT
    assert SandboxHandler._mimeToMessageType("text/csv") == MessageType.DOCUMENT
    assert SandboxHandler._mimeToMessageType("application/octet-stream") == MessageType.DOCUMENT
