"""Filesystem storage primitives for sandboxed code execution.

Provides pure utility functions for session hashing, workspace path
resolution, atomic JSON writes, and directory-layout initialisation.
No classes or singletons — all functions are stateless and side-effect-free
except where noted (``atomicWriteJson`` and ``ensureDirectoryLayout`` touch
the filesystem).

Functions:
    sessionHash: Compute a stable SHA-256 hex digest for a session ID.
    resolveWorkspacePath: Resolve a user-supplied path against a workspace root.
    atomicWriteJson: Atomically write a JSON dict to a file.
    ensureDirectoryLayout: Create the sandbox storage directory tree.
"""

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

from .config import StorageConfig
from .errors import PathOutsideWorkspace

logger = logging.getLogger(__name__)

# Subdirectory tree relative to rootDir that ensureDirectoryLayout creates.
# Each string represents a path component relative to the sandbox root directory.
_DIRECTORY_LAYOUT: list[str] = [
    "runtimes",
    "sessions",
    "meta",
    "meta/sessions",
    "meta/runs",
    "meta/runtimes",
    "tmp",
]


def sessionHash(sessionId: str) -> str:
    """Compute the SHA-256 hash of a session ID for stable filesystem naming.

    Args:
        sessionId: The opaque session identifier.

    Returns:
        The full 64-character lowercase hex digest.
    """
    return hashlib.sha256(sessionId.encode("utf-8")).hexdigest()


def resolveWorkspacePath(workspaceRoot: Path, requested: str) -> Path:
    """Resolve a user-supplied path against the session workspace root.

    Rejects paths that attempt to escape the workspace via absolute paths,
    parent-directory traversal, or symlink-based escapes.

    Args:
        workspaceRoot: The absolute workspace directory for the session.
        requested: The user-supplied relative path.

    Returns:
        The resolved absolute path within the workspace.

    Raises:
        PathOutsideWorkspace: If the path attempts to escape the workspace.
    """
    # 1. Reject null bytes — they can confuse path operations and are never
    #    legitimate in filenames.
    if "\0" in requested:
        raise PathOutsideWorkspace(f"path contains null byte: {requested!r}")

    # 2. Reject absolute paths.
    if requested.startswith("/"):
        raise PathOutsideWorkspace(f"absolute paths are not allowed: {requested!r}")

    # 3. Join with workspace root and resolve.
    #    We resolve workspaceRoot first so that symlinks in the root itself
    #    are accounted for.
    resolvedRoot = workspaceRoot.absolute().resolve()
    candidate = (resolvedRoot / requested).resolve()

    # 4. Verify the resolved path is still within the workspace root.
    #    Use pathlib's relative_to which is robust across platforms
    #    and handles symlinks/trailing slashes correctly.
    try:
        candidate.relative_to(resolvedRoot)
    except ValueError:
        raise PathOutsideWorkspace(f"path {requested!r} resolves outside workspace root {resolvedRoot}")

    return candidate


def atomicWriteJson(
    path: Path,
    payload: dict | list,
    *,
    tmpDir: Path,
    fileMode: int = 0o600,
    dirMode: int = 0o700,
) -> None:
    """Atomically write a JSON payload to a file.

    Writes to a temp file under *tmpDir*, fsyncs, then renames to the target
    path.  This guarantees the target file is never observed in a partial
    state.

    Args:
        path: The target file path.
        payload: The JSON-serializable dict to write.
        tmpDir: Directory for the temporary file (must exist).
        fileMode: Octal permissions for the file (default 0o600).
        dirMode: Octal permissions for any intermediate directories.
    """
    # 1. Ensure parent directory exists.
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(dirMode)
    except OSError:
        # chmod can fail if the directory already existed with different
        # ownership; best-effort.
        logger.debug("Could not chmod %s to %o", path.parent, dirMode)

    # 2. Create a named temp file under tmpDir (text mode for JSON).
    tmpFile = tempfile.NamedTemporaryFile(
        mode="w",
        dir=str(tmpDir),
        prefix=".tmp-",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    )
    tmpFilePath = Path(tmpFile.name)

    try:
        # 3. Write JSON payload.
        json.dump(payload, tmpFile, indent=2, default=str)
        # 4. Flush and fsync to ensure data hits disk before rename.
        tmpFile.flush()
        os.fsync(tmpFile.fileno())
        tmpFile.close()

        # 5. Set file permissions.
        os.chmod(tmpFilePath, fileMode)

        # 6. Atomic rename (os.replace is atomic on POSIX).
        os.replace(tmpFilePath, path)
    except BaseException:
        # 7. Clean up the temp file on any failure.
        if tmpFilePath.exists():
            try:
                tmpFilePath.unlink()
            except OSError:
                pass
        raise


def ensureDirectoryLayout(config: StorageConfig) -> None:
    """Create the sandbox storage directory tree.

    Creates all directories with the configured *dirMode*.  Attempts to
    chown to the configured UID/GID (best-effort; warns if it fails).

    The directory layout created under ``config.rootDir``::

        runtimes/
        sessions/
        meta/
          sessions/
          runs/
          runtimes/
        tmp/

    Args:
        config: The storage configuration with rootDir, dirMode, fileMode.
    """
    rootDir = Path(config.rootDir)

    # 1. Create root directory first.
    rootDir.mkdir(parents=True, exist_ok=True)

    # 2. Create each subdirectory and set permissions.
    for subdir in _DIRECTORY_LAYOUT:
        dirPath = rootDir / subdir
        dirPath.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(dirPath, config.dirMode)
        except OSError:
            logger.debug("Could not chmod %s to %o", dirPath, config.dirMode)

    # 3. Set permissions on root directory itself.
    try:
        os.chmod(rootDir, config.dirMode)
    except OSError:
        logger.debug("Could not chmod %s to %o", rootDir, config.dirMode)

    # 4. Best-effort chown — skip if not running as root.
    if os.getuid() != 0:
        logger.debug(
            "Not running as root; skipping chown for sandbox directories under %s",
            rootDir,
        )
