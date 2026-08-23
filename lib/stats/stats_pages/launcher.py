"""Shared subprocess launcher for stats-pages CLI.

Provides a pure helper for running the stats-pages generator and delete commands.
Config-free, small, and testable. Mirrors the subprocess conventions from
internal/services/proxy/lifecycle.py:105-150.
"""

import asyncio
from enum import StrEnum


class StatsCliErrorReason(StrEnum):
    """Reason codes for StatsCliError failures.

    Attributes:
        timeout: Command timed out (killed after timeout).
        spawn: Failed to spawn the subprocess (OSError).
    """

    TIMEOUT = "timeout"
    SPAWN = "spawn"


class StatsCliError(Exception):
    """Exception raised when stats-pages CLI invocation fails.

    Distinguishes between (timeout, spawn) failures so the caller
    can log appropriately.

    Attributes:
        reason: The specific failure reason (timeout, spawn).
        message: Human-readable description.
    """

    def __init__(self, reason: StatsCliErrorReason, message: str):
        """Initialize the CLI error.

        Args:
            reason: The failure reason.
            message: Human-readable description.
        """
        self.reason = reason
        self.message = message
        super().__init__(f"[{reason.value}] {message}")


async def runCliCommand(
    argv: list[str],
    *,
    stdinPayload: str | None = None,
    timeoutSeconds: float = 30.0,
) -> tuple[int | None, str, str]:
    """Run a CLI command and capture its output.

    Handles subprocess spawning, stdin delivery, stdout/stderr capture,
    timeout enforcement with kill-on-timeout, and error decoding.

    Args:
        argv: Command and arguments as a list of strings. Must be non-empty.
        stdinPayload: Optional string to write to stdin (JSON payloads for
            generate commands).
        timeoutSeconds: Maximum seconds to wait for the command to complete.

    Returns:
        tuple[int | None, str, str]: (returncode, stdout, stderr).
            returncode is None if the process timed out or was killed.

    Raises:
        StatsCliError: If subprocess spawn fails (reason=spawn) or if the
            command times out (reason=timeout).
        ValueError: If argv is empty.
    """
    if not argv:
        raise ValueError("argv must be non-empty")

    stdinPayloadBytes = stdinPayload.encode("utf-8") if stdinPayload is not None else None

    # Spawn the subprocess - handle spawn-time OSError separately
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdinPayloadBytes is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        raise StatsCliError(StatsCliErrorReason.SPAWN, f"Failed to spawn subprocess: {e}")

    # Communicate with the subprocess - these OSErrors are NOT spawn failures
    try:
        stdoutBytes, stderrBytes = await asyncio.wait_for(
            proc.communicate(input=stdinPayloadBytes),
            timeout=timeoutSeconds,
        )
    except asyncio.CancelledError:
        # Task was cancelled during communicate() - kill and reap the child
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        raise
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        raise StatsCliError(
            StatsCliErrorReason.TIMEOUT,
            f"Command timed out after {timeoutSeconds}s: {argv[0] if argv else 'unknown'}",
        )

    # Decode with error replacement (matches lifecycle.py convention)
    stdout = stdoutBytes.decode(errors="replace") if stdoutBytes else ""
    stderr = stderrBytes.decode(errors="replace") if stderrBytes else ""

    return proc.returncode, stdout, stderr
