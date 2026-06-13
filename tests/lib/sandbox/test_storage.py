"""Tests for sandbox storage primitives (lib.sandbox.storage).

Covers:
- sessionHash: determinism, uniqueness, length, hex charset, known-answer.
- resolveWorkspacePath: valid paths, nested paths, normalisation, absolute
  path normalisation, workspace-prefix normalisation, traversal rejection,
  null-byte rejection, symlink escapes, symlink within workspace, empty
  string, unicode paths.
- atomicWriteJson: round-trip, nested structures, temp-file cleanup on
  success, file permissions, directory creation.
- ensureDirectoryLayout: creates expected tree, idempotent, directory modes.
"""

import hashlib
import json
import stat
from pathlib import Path

import pytest

from lib.sandbox.config import StorageConfig
from lib.sandbox.errors import PathOutsideWorkspace
from lib.sandbox.storage import (
    atomicWriteJson,
    ensureDirectoryLayout,
    resolveWorkspacePath,
    sessionHash,
)

# ============================================================================
# sessionHash
# ============================================================================


class TestSessionHash:
    """Tests for the sessionHash function."""

    def testDeterministic(self) -> None:
        """Same input always produces the same output.

        Returns:
            None
        """
        assert sessionHash("abc") == sessionHash("abc")

    def testDifferentInputsProduceDifferentOutputs(self) -> None:
        """Different inputs produce different hashes.

        Returns:
            None
        """
        assert sessionHash("abc") != sessionHash("def")

    def testLengthIs64(self) -> None:
        """Output is always 64 characters (256 bits / 4 bits per hex char).

        Returns:
            None
        """
        assert len(sessionHash("any-input")) == 64

    def testAllHexChars(self) -> None:
        """Output contains only lowercase hex characters.

        Returns:
            None
        """
        result = sessionHash("test")
        assert all(c in "0123456789abcdef" for c in result)

    def testKnownAnswer(self) -> None:
        """Verify against a pre-computed SHA-256 digest.

        Returns:
            None
        """
        expected = hashlib.sha256("test".encode("utf-8")).hexdigest()
        assert sessionHash("test") == expected

    def testEmptyString(self) -> None:
        """Empty string produces the well-known SHA-256 of empty input.

        Returns:
            None
        """
        expected = hashlib.sha256(b"").hexdigest()
        assert sessionHash("") == expected

    def testUnicodeInput(self) -> None:
        """Unicode session IDs are hashed correctly.

        Returns:
            None
        """
        sessionId = "session-日本語"
        expected = hashlib.sha256(sessionId.encode("utf-8")).hexdigest()
        assert sessionHash(sessionId) == expected


# ============================================================================
# resolveWorkspacePath
# ============================================================================


class TestResolveWorkspacePath:
    """Tests for the resolveWorkspacePath function."""

    def testValidRelativePath(self, tmp_path: Path) -> None:
        """A simple relative path resolves inside the workspace.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = resolveWorkspacePath(workspace, "file.txt")
        assert result == workspace / "file.txt"

    def testNestedPath(self, tmp_path: Path) -> None:
        """A nested relative path resolves correctly.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = resolveWorkspacePath(workspace, "subdir/file.txt")
        assert result == workspace / "subdir" / "file.txt"

    def testDotPathNormalisation(self, tmp_path: Path) -> None:
        """Paths with '.' segments that stay within workspace are normalised.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = resolveWorkspacePath(workspace, "./subdir/../file.txt")
        assert result == workspace / "file.txt"

    def testAbsolutePathNormalized(self, tmp_path: Path) -> None:
        """Absolute paths are normalised to relative and resolve within workspace.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # /etc/passwd → etc/passwd (strip leading /)
        result = resolveWorkspacePath(workspace, "/etc/passwd")
        assert result == workspace / "etc" / "passwd"

    def testWorkspacePrefixNormalized(self, tmp_path: Path) -> None:
        """Paths starting with /workspace/ strip that prefix.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = resolveWorkspacePath(workspace, "/workspace/file.txt")
        assert result == workspace / "file.txt"

    def testWorkspacePrefixRoot(self, tmp_path: Path) -> None:
        """/workspace resolves to the workspace root itself.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = resolveWorkspacePath(workspace, "/workspace")
        assert result == workspace.resolve()

    def testAbsoluteWithWorkspacePrefixEscapesRejected(self, tmp_path: Path) -> None:
        """Traversal via /workspace prefix is still rejected.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        with pytest.raises(PathOutsideWorkspace):
            resolveWorkspacePath(workspace, "/workspace/../../etc/passwd")

    def testTraversalEscapeRejected(self, tmp_path: Path) -> None:
        """Paths that escape via '..' are rejected.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        with pytest.raises(PathOutsideWorkspace):
            resolveWorkspacePath(workspace, "../etc/passwd")

    def testDoubleTraversalEscapeRejected(self, tmp_path: Path) -> None:
        """Double '..' traversal is rejected.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        with pytest.raises(PathOutsideWorkspace):
            resolveWorkspacePath(workspace, "../../etc/passwd")

    def testNullByteRejected(self, tmp_path: Path) -> None:
        """Paths containing null bytes are rejected.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        with pytest.raises(PathOutsideWorkspace, match="null byte"):
            resolveWorkspacePath(workspace, "file\0.txt")

    def testSymlinkEscapeRejected(self, tmp_path: Path) -> None:
        """A symlink inside the workspace pointing outside is rejected.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # Create a symlink inside workspace pointing to /tmp (outside).
        linkPath = workspace / "escape"
        linkPath.symlink_to("/tmp")
        with pytest.raises(PathOutsideWorkspace):
            resolveWorkspacePath(workspace, "escape")

    def testSymlinkWithinWorkspaceAllowed(self, tmp_path: Path) -> None:
        """A symlink inside the workspace pointing within the workspace is allowed.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # Create a real directory and a symlink pointing to it.
        realDir = workspace / "real_dir"
        realDir.mkdir()
        linkPath = workspace / "link"
        linkPath.symlink_to(realDir)
        result = resolveWorkspacePath(workspace, "link/file.txt")
        assert str(result).startswith(str(workspace))

    def testEmptyStringPath(self, tmp_path: Path) -> None:
        """An empty string resolves to the workspace root itself.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = resolveWorkspacePath(workspace, "")
        assert result == workspace.resolve()

    def testUnicodePath(self, tmp_path: Path) -> None:
        """Unicode paths resolve correctly within the workspace.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = resolveWorkspacePath(workspace, "данные/file.txt")
        assert str(result).startswith(str(workspace.resolve()))

    def testDeeplyNestedTraversalRejected(self, tmp_path: Path) -> None:
        """Deeply nested traversal attempts are rejected.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        with pytest.raises(PathOutsideWorkspace):
            resolveWorkspacePath(workspace, "a/b/../../../../etc/passwd")

    def testWorkspacePrefixRootTrailingSlash(self, tmp_path: Path) -> None:
        """/workspace/ (trailing slash) resolves to workspace root.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = resolveWorkspacePath(workspace, "/workspace/")
        assert result == workspace.resolve()

    def testAbsolutePathWithTraversalRejected(self, tmp_path: Path) -> None:
        """Absolute path with traversal (no /workspace prefix) is rejected.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        with pytest.raises(PathOutsideWorkspace):
            resolveWorkspacePath(workspace, "/../../../etc/passwd")

    def testWorkspacePrefixDoubleSlashRejected(self, tmp_path: Path) -> None:
        """/workspace//file is rejected (double slash produces absolute remainder).

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        with pytest.raises(PathOutsideWorkspace):
            resolveWorkspacePath(workspace, "/workspace//file")


# ============================================================================
# atomicWriteJson
# ============================================================================


class TestAtomicWriteJson:
    """Tests for the atomicWriteJson function."""

    def testRoundTrip(self, tmp_path: Path) -> None:
        """Write and read back a dict — contents must be identical.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        targetFile = tmp_path / "output.json"
        payload = {"key": "value", "number": 42}
        atomicWriteJson(targetFile, payload, tmpDir=tmp_path)

        with open(targetFile, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == payload

    def testNestedDictsAndLists(self, tmp_path: Path) -> None:
        """Nested dicts and lists survive the round-trip.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        targetFile = tmp_path / "nested.json"
        payload = {
            "nested": {"deep": {"key": "val"}},
            "list": [1, 2, 3],
            "mixed": [{"a": 1}, {"b": 2}],
        }
        atomicWriteJson(targetFile, payload, tmpDir=tmp_path)

        with open(targetFile, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == payload

    def testSpecialTypesDefaultStr(self, tmp_path: Path) -> None:
        """Non-JSON-serialisable types are converted via default=str.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        targetFile = tmp_path / "special.json"
        payload = {"path": Path("/some/path"), "value": 42}
        atomicWriteJson(targetFile, payload, tmpDir=tmp_path)

        with open(targetFile, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["path"] == "/some/path"
        assert loaded["value"] == 42

    def testFilePermissions(self, tmp_path: Path) -> None:
        """File is created with the specified fileMode.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        targetFile = tmp_path / "perms.json"
        atomicWriteJson(targetFile, {"x": 1}, tmpDir=tmp_path, fileMode=0o644)

        fileStat = targetFile.stat()
        # Mask off non-permission bits.
        actualMode = stat.S_IMODE(fileStat.st_mode)
        assert actualMode == 0o644

    def testDirectoryCreation(self, tmp_path: Path) -> None:
        """Parent directories are created if they don't exist.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        targetFile = tmp_path / "deep" / "nested" / "dir" / "file.json"
        atomicWriteJson(targetFile, {"created": True}, tmpDir=tmp_path)

        assert targetFile.exists()
        with open(targetFile, encoding="utf-8") as f:
            assert json.load(f) == {"created": True}

    def testTempFileCleanedUpOnSuccess(self, tmp_path: Path) -> None:
        """After a successful write, no temp files remain in tmpDir.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        targetFile = tmp_path / "clean.json"
        atomicWriteJson(targetFile, {"ok": True}, tmpDir=tmp_path)

        # The only file in tmpDir should be the target (if it's under tmpDir)
        # or no .tmp- files should remain.
        tmpFiles = list(tmp_path.glob(".tmp-*.json"))
        assert len(tmpFiles) == 0

    def testOverwriteExistingFile(self, tmp_path: Path) -> None:
        """Overwriting an existing file replaces its contents atomically.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        targetFile = tmp_path / "overwrite.json"
        atomicWriteJson(targetFile, {"version": 1}, tmpDir=tmp_path)
        atomicWriteJson(targetFile, {"version": 2}, tmpDir=tmp_path)

        with open(targetFile, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == {"version": 2}

    def testExceptionCleansUpTempFile(self, tmp_path: Path) -> None:
        """If json.dump fails, the temp file is cleaned up.

        Uses a circular reference which json.dump cannot serialise even
        with default=str.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        circular: list[object] = []
        circular.append(circular)
        payload: dict = {"bad": circular}

        targetFile = tmp_path / "fail.json"
        with pytest.raises(ValueError):
            atomicWriteJson(targetFile, payload, tmpDir=tmp_path)

        # Target file should not exist.
        assert not targetFile.exists()
        # No temp files should remain.
        tmpFiles = list(tmp_path.glob(".tmp-*.json"))
        assert len(tmpFiles) == 0


# ============================================================================
# ensureDirectoryLayout
# ============================================================================


class TestEnsureDirectoryLayout:
    """Tests for the ensureDirectoryLayout function."""

    def testCreatesAllSubdirectories(self, tmp_path: Path) -> None:
        """All expected subdirectories are created.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        config = StorageConfig(rootDir=str(rootDir))
        ensureDirectoryLayout(config)

        expectedDirs = [
            rootDir / "runtimes",
            rootDir / "sessions",
            rootDir / "meta",
            rootDir / "meta" / "sessions",
            rootDir / "meta" / "runs",
            rootDir / "meta" / "runtimes",
            rootDir / "tmp",
        ]
        for d in expectedDirs:
            assert d.is_dir(), f"Expected directory {d} to exist"

    def testDirectoryModes(self, tmp_path: Path) -> None:
        """Directories are created with the configured dirMode.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        config = StorageConfig(rootDir=str(rootDir), dirMode=0o755)
        ensureDirectoryLayout(config)

        for subdir in ["runtimes", "sessions", "meta", "tmp"]:
            dirPath = rootDir / subdir
            actualMode = stat.S_IMODE(dirPath.stat().st_mode)
            assert actualMode == 0o755, f"Expected {dirPath} mode 0o755, got {oct(actualMode)}"

    def testIdempotent(self, tmp_path: Path) -> None:
        """Running ensureDirectoryLayout twice does not fail.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        config = StorageConfig(rootDir=str(rootDir))
        ensureDirectoryLayout(config)
        ensureDirectoryLayout(config)

        # Verify directories still exist.
        assert (rootDir / "runtimes").is_dir()
        assert (rootDir / "sessions").is_dir()
        assert (rootDir / "meta" / "sessions").is_dir()

    def testRootDirCreatedIfMissing(self, tmp_path: Path) -> None:
        """The root directory is created if it doesn't exist.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "new" / "sandbox"
        assert not rootDir.exists()
        config = StorageConfig(rootDir=str(rootDir))
        ensureDirectoryLayout(config)
        assert rootDir.is_dir()

    def testDefaultDirMode(self, tmp_path: Path) -> None:
        """Default dirMode (0o700) is applied when not explicitly configured.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        rootDir = tmp_path / "sandbox"
        config = StorageConfig(rootDir=str(rootDir))
        ensureDirectoryLayout(config)

        actualMode = stat.S_IMODE((rootDir / "runtimes").stat().st_mode)
        assert actualMode == 0o700
