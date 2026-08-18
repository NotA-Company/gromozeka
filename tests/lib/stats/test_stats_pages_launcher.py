"""Tests for the stats-pages CLI launcher."""

import pytest

from lib.stats.stats_pages import StatsCliError, StatsCliErrorReason, runCliCommand


class TestRunCliCommand:
    """Tests for runCliCommand."""

    async def test_happy_path_with_stdin(self):
        """Test happy path with stdin payload delivered and stdout returned."""
        # Use a simple echo command to test stdin/stdout
        result = await runCliCommand(["cat"], stdinPayload="test input", timeoutSeconds=1.0)
        returncode, stdout, stderr = result

        assert returncode == 0
        assert stdout == "test input"
        assert stderr == ""

    async def test_timeout_kills_and_raises_timeout_error(self):
        """Test that timeout causes process kill and raises TIMEOUT error."""
        with pytest.raises(StatsCliError) as exc_info:
            await runCliCommand(["sleep", "10"], timeoutSeconds=0.1)

        assert exc_info.value.reason == StatsCliErrorReason.TIMEOUT
        assert "timed out" in exc_info.value.message.lower()

    async def test_nonzero_exit_returns_code(self):
        """Test that nonzero exit code is returned without raising."""
        # Use false command which always exits with code 1
        returncode, stdout, stderr = await runCliCommand(["false"], timeoutSeconds=1.0)

        assert returncode == 1
        assert stdout == ""

    async def test_spawn_failure_raises_spawn_error(self):
        """Test that spawn failure raises SPAWN error."""
        # Use a non-existent command
        with pytest.raises(StatsCliError) as exc_info:
            await runCliCommand(["this_command_does_not_exist_12345"], timeoutSeconds=1.0)

        assert exc_info.value.reason == StatsCliErrorReason.SPAWN
        assert "failed to spawn" in exc_info.value.message.lower()
