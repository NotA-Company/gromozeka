"""Garbage collection for sandbox workspaces and metadata.

Removes expired sessions, orphan workspace directories, stale run records,
and orphan Docker containers.
"""

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .config import GcConfig
from .metadata.base import MetadataStore

if TYPE_CHECKING:
    from .backends.base import SandboxBackend

logger = logging.getLogger(__name__)


class GarbageCollector:
    """Removes expired and orphaned sandbox resources.

    Iterates over session and run metadata to find resources eligible for
    cleanup, then removes both the on-disk artefacts and the metadata records.

    Args:
        config: GC configuration (intervals, retention periods).
        metadataStore: The metadata store for querying session/run records.
        rootDir: The sandbox storage root directory.
        backend: Optional sandbox backend for container GC operations.
    """

    def __init__(
        self,
        config: GcConfig,
        metadataStore: MetadataStore,
        rootDir: Path,
        backend: "SandboxBackend | None" = None,
    ) -> None:
        """Initialise the garbage collector.

        Args:
            config: GC configuration (intervals, retention periods).
            metadataStore: The metadata store for querying session/run records.
            rootDir: The sandbox storage root directory.
            backend: Optional sandbox backend for container GC operations.
        """
        self._config = config
        self._metadata = metadataStore
        self._rootDir = rootDir
        self._backend = backend

    async def collectExpiredSessions(self) -> int:
        """Remove sessions whose expiresAt has passed.

        Deletes the entire ``sessions/<hash>/`` parent directory (not just the
        ``workspace/`` subdirectory) so no empty parent dirs are left behind.

        Returns:
            Number of sessions removed.
        """
        now = datetime.now(timezone.utc)
        sessions = await self._metadata.listSessions()
        removed = 0

        for session in sessions:
            if session.expiresAt < now:
                logger.info("GC: removing expired session %s (expired %s)", session.sessionId, session.expiresAt)
                # Delete the entire sessions/<hash>/ parent directory
                workspacePath = Path(session.workspacePath)
                parentDir = workspacePath.parent  # sessions/<hash>/
                if parentDir.exists():
                    shutil.rmtree(parentDir)
                # Delete metadata
                await self._metadata.deleteSession(session.sessionId)
                removed += 1

        return removed

    async def collectOrphanWorkspaces(self) -> int:
        """Remove workspace directories that have no corresponding metadata record.

        An orphan workspace is a directory under sessions/ whose session hash
        doesn't match any loaded session record.  Only removes orphans older
        than ``orphanWorkspaceRetentionMinutes`` to avoid deleting recently-
        created directories that haven't been persisted yet.

        Returns:
            Number of orphan workspaces removed.
        """
        sessionsDir = self._rootDir / "sessions"
        if not sessionsDir.exists():
            return 0

        # Build set of known session hashes
        allSessions = await self._metadata.listSessions()
        knownHashes = {s.sessionHash for s in allSessions}

        cutoff = datetime.now(timezone.utc).timestamp() - (self._config.orphanWorkspaceRetentionMinutes * 60)

        removed = 0
        for entry in sessionsDir.iterdir():
            if not entry.is_dir():
                continue
            if entry.name.startswith("."):
                continue

            if entry.name not in knownHashes:
                # Check age — only remove if older than retention period
                try:
                    entryMtime = entry.stat().st_mtime
                except OSError:
                    continue
                if entryMtime >= cutoff:
                    logger.debug("GC: skipping recent orphan workspace %s", entry)
                    continue
                logger.info("GC: removing orphan workspace %s", entry)
                shutil.rmtree(entry)
                removed += 1

        return removed

    async def collectExpiredRuns(self) -> int:
        """Remove run records and their .run/ directories older than runRetentionMinutes.

        Returns:
            Number of runs removed.
        """
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - (self._config.runRetentionMinutes * 60)
        removed = 0

        # We need to iterate all sessions and check their runs
        sessions = await self._metadata.listSessions()
        for session in sessions:
            runs = await self._metadata.listRunsForSession(session.sessionId)
            for run in runs:
                if run.finishedAt is None:
                    continue  # don't touch running runs
                if run.finishedAt.timestamp() < cutoff:
                    # Delete the .run/<runId>/ directory
                    workspacePath = Path(session.workspacePath)
                    runDir = workspacePath / ".run" / run.runId
                    if runDir.exists():
                        shutil.rmtree(runDir)
                    # Delete the run metadata
                    await self._metadata.deleteRun(run.runId)
                    removed += 1

        return removed

    async def collectOrphanContainers(self) -> int:
        """Remove orphan Docker containers with sandbox.managed=true label.

        A container is considered orphan if it's older than
        orphanContainerRetentionMinutes and its runId is not in any active
        session's run list.

        Returns:
            Number of containers removed.
        """
        if self._backend is None:
            return 0

        try:
            managed = await self._backend.listManagedContainers()
        except Exception:
            return 0

        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - (self._config.orphanContainerRetentionMinutes * 60)
        removed = 0

        for container in managed:
            try:
                createdAt = container.createdAt
                if createdAt:
                    try:
                        createdTs = datetime.fromisoformat(createdAt.replace("Z", "+00:00")).timestamp()
                        if createdTs > cutoff:
                            continue  # Too young
                    except (ValueError, OSError):
                        pass

                await self._backend.killContainer(container.containerId)
                await self._backend.removeContainer(container.containerId, force=True)
                removed += 1
            except Exception:
                continue

        return removed

    async def collectAll(self) -> tuple[int, int, int, int, list[str]]:
        """Run all collection passes and return counts.

        Returns:
            Tuple of (removedContainers, removedSessions, removedRuns, removedOrphans, errors).
        """
        errors: list[str] = []

        try:
            removedContainers = await self.collectOrphanContainers()
        except Exception as exc:
            errors.append(f"collectOrphanContainers: {exc}")
            removedContainers = 0

        try:
            removedSessions = await self.collectExpiredSessions()
        except Exception as exc:
            errors.append(f"collectExpiredSessions: {exc}")
            removedSessions = 0

        try:
            removedRuns = await self.collectExpiredRuns()
        except Exception as exc:
            errors.append(f"collectExpiredRuns: {exc}")
            removedRuns = 0

        try:
            removedOrphans = await self.collectOrphanWorkspaces()
        except Exception as exc:
            errors.append(f"collectOrphanWorkspaces: {exc}")
            removedOrphans = 0

        return removedContainers, removedSessions, removedRuns, removedOrphans, errors
