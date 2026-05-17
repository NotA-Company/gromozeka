"""Tests for SandboxManager file API methods (lib.sandbox.manager).

Covers:
- write + read round-trip (text and binary).
- listFiles (flat and recursive).
- deleteFile (existing and nonexistent).
- Path traversal and absolute path rejection.
- Truncation (maxBytes) — truncated, exact, and None.
- overwrite=False raises FileExistsError.
- Encoding handling (UTF-8 text and raw bytes).
- SessionNotFound on nonexistent sessions.
- Empty directory listing returns [].
"""

from pathlib import Path

import pytest

from lib.sandbox.config import ConcurrencyConfig, SandboxConfig, StorageConfig
from lib.sandbox.errors import PathOutsideWorkspace, SessionNotFound
from lib.sandbox.manager import SandboxManager
from lib.sandbox.types import FileContent

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _resetSingleton():
    """Reset the SandboxManager singleton before and after each test."""
    SandboxManager._instance = None
    SandboxManager._configInstance = None
    yield
    SandboxManager._instance = None
    SandboxManager._configInstance = None


def _makeConfig(tmp_path: Path) -> SandboxConfig:
    """Create a SandboxConfig pointing at a temp directory.

    Args:
        tmp_path: Temporary directory path for storage.

    Returns:
        A SandboxConfig with storage rooted at tmp_path.
    """
    return SandboxConfig(
        storage=StorageConfig(rootDir=str(tmp_path)),
        concurrency=ConcurrencyConfig(
            maxQueuedRunsPerSession=4,
            maxConcurrentRunsGlobal=8,
            globalQueueWaitSeconds=60,
        ),
    )


@pytest.fixture
def manager(tmp_path: Path) -> SandboxManager:
    """Create a fresh SandboxManager with a temp storage directory.

    Args:
        tmp_path: Pytest-provided temporary directory.

    Returns:
        A SandboxManager instance.
    """
    config = _makeConfig(tmp_path)
    SandboxManager.injectConfig(config)
    return SandboxManager.getInstance()


async def _createSession(manager: SandboxManager, sessionId: str = "test-session") -> str:
    """Create a session and return its workspace path.

    Args:
        manager: The SandboxManager instance.
        sessionId: The session ID to create.

    Returns:
        The workspace path string.
    """
    info = await manager.createSession(sessionId)
    return info.workspacePath


# ---------------------------------------------------------------------------
# write + read round-trip tests
# ---------------------------------------------------------------------------


class TestWriteReadRoundTrip:
    """Tests for write-then-read text round-trip."""

    async def test_writeReadTextRoundTrip(self, manager: SandboxManager) -> None:
        """Write text content, read it back, verify content matches."""
        await _createSession(manager)
        await manager.writeFile("test-session", "hello.txt", "hello world")
        content = await manager.readFile("test-session", "hello.txt")
        assert isinstance(content, FileContent)
        assert content.content == "hello world"
        assert content.sizeBytes == len("hello world".encode("utf-8"))
        assert content.truncated is False

    async def test_writeReadBytesRoundTrip(self, manager: SandboxManager) -> None:
        """Write binary content, read it back without encoding, verify bytes match."""
        await _createSession(manager)
        raw = b"\x00\xff\x01\x02"
        await manager.writeFile("test-session", "binary.bin", raw)
        content = await manager.readFile("test-session", "binary.bin", encoding=None)
        assert isinstance(content, FileContent)
        assert content.content == raw
        assert content.sizeBytes == 4
        assert content.bytesRead == 4


# ---------------------------------------------------------------------------
# listFiles tests
# ---------------------------------------------------------------------------


class TestListFiles:
    """Tests for SandboxManager.listFiles."""

    async def test_listFilesReturnsCreatedFiles(self, manager: SandboxManager) -> None:
        """listFiles returns FileInfo entries for files in the workspace."""
        await _createSession(manager)
        await manager.writeFile("test-session", "a.txt", "aaa")
        await manager.writeFile("test-session", "b.txt", "bbb")

        files = await manager.listFiles("test-session")
        assert len(files) == 2
        paths = {f.path for f in files}
        assert "a.txt" in paths
        assert "b.txt" in paths

    async def test_listFilesRecursive(self, manager: SandboxManager) -> None:
        """listFiles with recursive=True lists nested entries."""
        await _createSession(manager)
        await manager.writeFile("test-session", "top.txt", "top")
        await manager.writeFile("test-session", "sub/nested.txt", "nested")

        files = await manager.listFiles("test-session", recursive=True)
        paths = {f.path for f in files}
        assert "top.txt" in paths
        assert any("nested.txt" in p for p in paths)

    async def test_listFilesEmptyDirectory(self, manager: SandboxManager) -> None:
        """listFiles on an empty workspace returns an empty list."""
        await _createSession(manager)
        files = await manager.listFiles("test-session")
        assert files == []

    async def test_listFilesNonexistentPath(self, manager: SandboxManager) -> None:
        """listFiles on a nonexistent subdirectory returns an empty list."""
        await _createSession(manager)
        files = await manager.listFiles("test-session", path="nonexistent_dir")
        assert files == []


# ---------------------------------------------------------------------------
# deleteFile tests
# ---------------------------------------------------------------------------


class TestDeleteFile:
    """Tests for SandboxManager.deleteFile."""

    async def test_deleteFileRemovesFile(self, manager: SandboxManager) -> None:
        """deleteFile removes a file so readFile raises FileNotFoundError."""
        await _createSession(manager)
        await manager.writeFile("test-session", "gone.txt", "bye")
        result = await manager.deleteFile("test-session", "gone.txt")
        assert result is True

        with pytest.raises(FileNotFoundError):
            await manager.readFile("test-session", "gone.txt")

    async def test_deleteFileNonexistentReturnsFalse(self, manager: SandboxManager) -> None:
        """deleteFile returns False when the file doesn't exist."""
        await _createSession(manager)
        result = await manager.deleteFile("test-session", "nope.txt")
        assert result is False


# ---------------------------------------------------------------------------
# path security tests
# ---------------------------------------------------------------------------


class TestPathSecurity:
    """Tests for path traversal and absolute path rejection."""

    async def test_pathTraversalRejected(self, manager: SandboxManager) -> None:
        """readFile with a traversal path raises PathOutsideWorkspace."""
        await _createSession(manager)
        with pytest.raises(PathOutsideWorkspace):
            await manager.readFile("test-session", "../../../etc/passwd")

    async def test_absolutePathRejected(self, manager: SandboxManager) -> None:
        """readFile with an absolute path raises PathOutsideWorkspace."""
        await _createSession(manager)
        with pytest.raises(PathOutsideWorkspace):
            await manager.readFile("test-session", "/etc/passwd")

    async def test_writePathTraversalRejected(self, manager: SandboxManager) -> None:
        """writeFile with a traversal path raises PathOutsideWorkspace."""
        await _createSession(manager)
        with pytest.raises(PathOutsideWorkspace):
            await manager.writeFile("test-session", "../../etc/evil", "data")

    async def test_deletePathTraversalRejected(self, manager: SandboxManager) -> None:
        """deleteFile with a traversal path raises PathOutsideWorkspace."""
        await _createSession(manager)
        with pytest.raises(PathOutsideWorkspace):
            await manager.deleteFile("test-session", "../../../etc/passwd")

    async def test_listPathTraversalRejected(self, manager: SandboxManager) -> None:
        """listFiles with a traversal path raises PathOutsideWorkspace."""
        await _createSession(manager)
        with pytest.raises(PathOutsideWorkspace):
            await manager.listFiles("test-session", path="../../etc")


# ---------------------------------------------------------------------------
# truncation tests
# ---------------------------------------------------------------------------


class TestTruncation:
    """Tests for maxBytes truncation in readFile."""

    async def test_truncatedRead(self, manager: SandboxManager) -> None:
        """readFile with maxBytes smaller than file returns truncated content."""
        await _createSession(manager)
        data = "x" * 100
        await manager.writeFile("test-session", "big.txt", data)

        content = await manager.readFile("test-session", "big.txt", maxBytes=10)
        assert content.truncated is True
        assert content.bytesRead == 10
        assert content.sizeBytes == 100

    async def test_truncationExact(self, manager: SandboxManager) -> None:
        """readFile with maxBytes equal to file size returns truncated=False."""
        await _createSession(manager)
        data = "x" * 10
        await manager.writeFile("test-session", "exact.txt", data)

        content = await manager.readFile("test-session", "exact.txt", maxBytes=10)
        assert content.truncated is False
        assert content.bytesRead == 10
        assert content.sizeBytes == 10

    async def test_maxBytesNone(self, manager: SandboxManager) -> None:
        """readFile with maxBytes=None reads the entire file."""
        await _createSession(manager)
        data = "x" * 100
        await manager.writeFile("test-session", "full.txt", data)

        content = await manager.readFile("test-session", "full.txt", maxBytes=None)
        assert content.truncated is False
        assert content.bytesRead == 100
        assert content.sizeBytes == 100


# ---------------------------------------------------------------------------
# overwrite tests
# ---------------------------------------------------------------------------


class TestOverwrite:
    """Tests for writeFile overwrite behavior."""

    async def test_writeOverwriteFalseRaises(self, manager: SandboxManager) -> None:
        """writeFile with overwrite=False raises FileExistsError if file exists."""
        await _createSession(manager)
        await manager.writeFile("test-session", "exists.txt", "first")
        with pytest.raises(FileExistsError):
            await manager.writeFile("test-session", "exists.txt", "second", overwrite=False)

    async def test_writeOverwriteTrueSucceeds(self, manager: SandboxManager) -> None:
        """writeFile with overwrite=True (default) replaces existing content."""
        await _createSession(manager)
        await manager.writeFile("test-session", "replace.txt", "first")
        await manager.writeFile("test-session", "replace.txt", "second")
        content = await manager.readFile("test-session", "replace.txt")
        assert content.content == "second"


# ---------------------------------------------------------------------------
# encoding tests
# ---------------------------------------------------------------------------


class TestEncoding:
    """Tests for encoding handling in readFile."""

    async def test_utf8TextRoundTrip(self, manager: SandboxManager) -> None:
        """Write and read UTF-8 text (e.g. 'café') preserves content."""
        await _createSession(manager)
        await manager.writeFile("test-session", "cafe.txt", "café")
        content = await manager.readFile("test-session", "cafe.txt")
        assert content.content == "café"

    async def test_readWithEncodingNone(self, manager: SandboxManager) -> None:
        """readFile with encoding=None returns raw bytes."""
        await _createSession(manager)
        raw = b"\x00\xff"
        await manager.writeFile("test-session", "raw.bin", raw)
        content = await manager.readFile("test-session", "raw.bin", encoding=None)
        assert isinstance(content.content, bytes)
        assert content.content == raw


# ---------------------------------------------------------------------------
# SessionNotFound tests
# ---------------------------------------------------------------------------


class TestSessionNotFound:
    """Tests that file APIs raise SessionNotFound for nonexistent sessions."""

    async def test_listFilesSessionNotFound(self, manager: SandboxManager) -> None:
        """listFiles raises SessionNotFound for a nonexistent session."""
        with pytest.raises(SessionNotFound):
            await manager.listFiles("nonexistent-session")

    async def test_readFileSessionNotFound(self, manager: SandboxManager) -> None:
        """readFile raises SessionNotFound for a nonexistent session."""
        with pytest.raises(SessionNotFound):
            await manager.readFile("nonexistent-session", "file.txt")

    async def test_writeFileSessionNotFound(self, manager: SandboxManager) -> None:
        """writeFile raises SessionNotFound for a nonexistent session."""
        with pytest.raises(SessionNotFound):
            await manager.writeFile("nonexistent-session", "file.txt", "data")

    async def test_deleteFileSessionNotFound(self, manager: SandboxManager) -> None:
        """deleteFile raises SessionNotFound for a nonexistent session."""
        with pytest.raises(SessionNotFound):
            await manager.deleteFile("nonexistent-session", "file.txt")


# ---------------------------------------------------------------------------
# read directory error test
# ---------------------------------------------------------------------------


class TestReadDirectory:
    """Tests for readFile on a directory path."""

    async def test_readDirectoryRaisesIsADirectoryError(self, manager: SandboxManager) -> None:
        """readFile on a directory path raises IsADirectoryError."""
        await _createSession(manager)
        # Create a subdirectory by writing a file inside it
        await manager.writeFile("test-session", "subdir/file.txt", "data")
        with pytest.raises(IsADirectoryError):
            await manager.readFile("test-session", "subdir")
