"""Tests for the stats-pages CLI launcher."""

import asyncio
import subprocess

import pytest

from lib.stats.stats_pages import StatsCliError, StatsCliErrorReason, runCliCommand


class TestRunCliCommand:
    """Tests for runCliCommand."""

    async def test_happy_path_with_stdin(self) -> None:
        """Test happy path with stdin payload delivered and stdout returned."""
        # Use a simple echo command to test stdin/stdout
        result = await runCliCommand(["cat"], stdinPayload="test input", timeoutSeconds=1.0)
        returncode, stdout, stderr = result

        assert returncode == 0
        assert stdout == "test input"
        assert stderr == ""

    async def test_empty_argv_raises_value_error(self) -> None:
        """Test that empty argv raises ValueError."""
        with pytest.raises(ValueError, match="argv must be non-empty"):
            await runCliCommand([])

    async def test_timeout_kills_and_raises_timeout_error(self) -> None:
        """Test that timeout causes process kill and raises timeout error."""
        with pytest.raises(StatsCliError) as exc_info:
            await runCliCommand(["sleep", "10"], timeoutSeconds=0.1)

        assert exc_info.value.reason == StatsCliErrorReason.TIMEOUT
        assert "timed out" in exc_info.value.message.lower()

    async def test_nonzero_exit_returns_code(self) -> None:
        """Test that nonzero exit code is returned without raising."""
        # Use false command which always exits with code 1
        returncode, stdout, stderr = await runCliCommand(["false"], timeoutSeconds=1.0)

        assert returncode == 1
        assert stdout == ""

    async def test_spawn_failure_raises_spawn_error(self) -> None:
        """Test that spawn failure raises spawn error."""
        # Use a non-existent command
        with pytest.raises(StatsCliError) as exc_info:
            await runCliCommand(["this_command_does_not_exist_12345"], timeoutSeconds=1.0)

        assert exc_info.value.reason == StatsCliErrorReason.SPAWN
        assert exc_info.value.reason.value == "spawn"
        assert "failed to spawn" in exc_info.value.message.lower()

    async def test_enum_reason_values_match_strenum_convention(self) -> None:
        """Test that enum reason values follow lowercase StrEnum convention."""
        assert StatsCliErrorReason.TIMEOUT.value == "timeout"
        assert StatsCliErrorReason.SPAWN.value == "spawn"

    async def test_cancellation_during_communicate_kills_child_process(self) -> None:
        """Test that CancelledError during communicate() kills and reaps the child.

        Regression test for process management issue: when the awaiting task
        is cancelled during asyncio.wait_for(proc.communicate(...)), the child
        process must be killed and reaped, not left running.


        This test directly calls runCliCommand (which uses wait_for) and
        verifies that when cancellation occurs during communicate(), the child
        process is properly terminated.
        """

        # Create a task that runs a very long sleep command (100 seconds)
        # We'll cancel it after a short delay
        async def longRunningTask():
            return await runCliCommand(["sleep", "100"], timeoutSeconds=200.0)

        # Find any existing sleep 100 processes before we start
        result = subprocess.run(["pgrep", "-f", "sleep 100"], capture_output=True, text=True)
        existingPids = set(result.stdout.strip().split())

        # Start the task
        task = asyncio.create_task(longRunningTask())

        # Wait a bit to ensure the process spawned
        await asyncio.sleep(0.3)

        # Find our sleep process (not including pre-existing ones)
        result = subprocess.run(["pgrep", "-f", "sleep 100"], capture_output=True, text=True)
        currentPids = set(result.stdout.strip().split())
        ourPids = currentPids - existingPids

        assert ourPids, "Sleep process should have spawned"

        # Cancel the task (this triggers CancelledError during communicate())
        task.cancel()

        # The task should raise CancelledError
        try:
            await task
            assert False, "Task should have raised CancelledError"
        except asyncio.CancelledError:
            pass  # Expected

        # Wait a moment to ensure cleanup completes
        await asyncio.sleep(0.2)

        # Verify the sleep process is gone
        result = subprocess.run(["pgrep", "-f", "sleep 100"], capture_output=True, text=True)
        finalPids = set(result.stdout.strip().split())
        remainingOurPids = finalPids - existingPids

        assert not remainingOurPids, f"Sleep process {remainingOurPids} still running after CancelledError"

        # Clean up any remaining sleep processes (just in case)
        for pid in ourPids:
            try:
                subprocess.run(["kill", "-9", pid], capture_output=True)
            except Exception:
                pass

    # NOTE: A test for communicate-time OSError (e.g., BrokenPipe) is NOT added
    # because it's inherently flaky across platforms. asyncio.communicate() handles
    # BrokenPipeError gracefully by returning partial output, and triggering a
    # genuine OSError during communicate requires timing-dependent conditions that
    # vary by OS, pipe buffer size, and scheduler behavior. The restructure itself
    # (create_subprocess_exec has its own try/except OSError) is the key fix—
    # communicate-time OSErrors now surface as-is (or under their own clear handling)
    # rather than being mislabeled as SPAWN failures.
