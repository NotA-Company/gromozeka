"""Tests for the stats-pages CLI contract.

Tests subprocess invocation, stdin/stdout JSON handling, exit codes,
and the delete command.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Compute repo root at module top for portability
# tests/lib/stats/test_stats_pages_cli.py → parents[3] = repo root
repoRoot = Path(__file__).resolve().parents[3]


class TestStatsPagesCli:
    """Test stats-pages CLI contract."""

    def test_generate_help(self) -> None:
        """Test that generate help is accessible."""
        result = subprocess.run(
            [sys.executable, "-m", "lib.stats.stats_pages", "generate", "--help"],
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert result.returncode == 0
        assert "generate" in result.stdout.lower()
        assert "output-dir" in result.stdout

    def test_delete_help(self) -> None:
        """Test that delete help is accessible."""
        result = subprocess.run(
            [sys.executable, "-m", "lib.stats.stats_pages", "delete", "--help"],
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert result.returncode == 0
        assert "delete" in result.stdout.lower()
        assert "pageId" in result.stdout

    def test_main_help(self) -> None:
        """Test that main help is accessible."""
        result = subprocess.run(
            [sys.executable, "-m", "lib.stats.stats_pages", "--help"],
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert result.returncode == 0
        assert "generate" in result.stdout.lower()
        assert "delete" in result.stdout.lower()

    def test_generate_valid_payload_creates_html_and_outputs_json(self, tmp_path) -> None:
        """Test generate with valid payload creates HTML file and outputs JSON."""
        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }

        payloadJson = json.dumps(payload)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--output-dir",
                str(tmp_path),
            ],
            input=payloadJson,
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        # Check exit code
        assert result.returncode == 0, f"stderr: {result.stderr}"

        # Check stdout is single-line JSON (no newlines except trailing strip)
        assert "\n" not in result.stdout.strip()

        # Check stdout is valid JSON
        stdoutData = json.loads(result.stdout)

        # Check JSON structure
        assert "pageId" in stdoutData
        assert "url" in stdoutData
        assert len(stdoutData["pageId"]) == 32  # UUID hex
        assert stdoutData["url"].endswith(".html")
        assert stdoutData["url"].startswith(stdoutData["pageId"])

        # Check HTML file was created
        htmlPath = tmp_path / stdoutData["url"]
        assert htmlPath.exists()

        # Check HTML content
        htmlContent = htmlPath.read_text()
        assert "<!DOCTYPE html>" in htmlContent
        assert "Test Chat" in htmlContent
        assert "<style>" in htmlContent

    def test_generate_with_sections_renders_all_sections(self, tmp_path) -> None:
        """Test that all sections are rendered when provided."""
        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sections": {
                "messages": {
                    "totalMessages": 100,
                    "totalLength": 5000,
                    "userMessages": 80,
                    "botMessages": 20,
                    "historyMessages": 0,
                    "avgLength": 50.0,
                    "topUsers": [("Alice", 30), ("Bob", 25)],
                    "topTypes": [("text", 80)],
                },
                "commands": {
                    "totalCommands": 50,
                    "errorCommands": 5,
                    "topCommands": [("/help", 20), ("/stats", 15)],
                },
                "tools": {
                    "totalCalls": 30,
                    "errorCalls": 2,
                    "totalElapsed": 15.5,
                    "avgElapsed": 0.517,
                    "topTools": [("search", 20)],
                },
                "llm": {
                    "totalRequests": 20,
                    "errorRequests": 1,
                    "inputTokens": 10000,
                    "outputTokens": 5000,
                    "totalTokens": 15000,
                    "totalElapsed": 10.0,
                    "avgElapsed": 0.5,
                    "topModels": [("gpt-4o", 15)],
                    "topProviders": [("openai", 15)],
                    "stt": {
                        "totalRequests": 5,
                        "errorRequests": 0,
                        "totalAudioDuration": 120.0,
                    },
                },
            },
        }

        payloadJson = json.dumps(payload)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--output-dir",
                str(tmp_path),
            ],
            input=payloadJson,
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert result.returncode == 0

        stdoutData = json.loads(result.stdout)
        htmlPath = tmp_path / stdoutData["url"]
        htmlContent = htmlPath.read_text()

        # Check all sections are present
        assert "💬 Messages" in htmlContent
        assert "🔧 Commands" in htmlContent
        assert "🛠️ Tools" in htmlContent
        assert "🧠 LLM" in htmlContent
        assert "🎤 Speech-to-Text" in htmlContent

    def test_generate_with_chat_list_renders_chat_list(self, tmp_path) -> None:
        """Test that chat list is rendered for private chats."""
        payload = {
            "userId": "user123",
            "chatId": "123456789",
            "chatTitle": "Private Chat",
            "chatType": "private",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "chatList": [
                {"chatId": -1001234567890, "title": "Group A", "messagesCount": 300},
                {"chatId": -1009876543210, "title": "Group B", "messagesCount": 210},
            ],
        }

        payloadJson = json.dumps(payload)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--output-dir",
                str(tmp_path),
            ],
            input=payloadJson,
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert result.returncode == 0

        stdoutData = json.loads(result.stdout)
        htmlPath = tmp_path / stdoutData["url"]
        htmlContent = htmlPath.read_text()

        # Check chat list is present
        assert "📋 Your Chats" in htmlContent
        assert "Group A" in htmlContent
        assert "Group B" in htmlContent
        assert "#-1001234567890" in htmlContent
        assert "300" in htmlContent

    def test_generate_invalid_json_returns_nonzero_exit(self) -> None:
        """Test that invalid JSON on stdin causes nonzero exit."""
        result = subprocess.run(
            [sys.executable, "-m", "lib.stats.stats_pages", "generate"],
            input="{ invalid json }",
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert result.returncode != 0
        assert "Error:" in result.stderr

    def test_generate_missing_required_field_returns_nonzero_exit(self) -> None:
        """Test that missing required fields cause nonzero exit."""
        # Missing "period" field
        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }

        payloadJson = json.dumps(payload)

        result = subprocess.run(
            [sys.executable, "-m", "lib.stats.stats_pages", "generate"],
            input=payloadJson,
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert result.returncode != 0
        assert "Missing required field" in result.stderr

    def test_delete_existing_page_outputs_json_deleted_1(self, tmp_path) -> None:
        """Test delete of existing page outputs {"deleted": 1}."""
        # First, create a page
        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }

        payloadJson = json.dumps(payload)

        generateResult = subprocess.run(
            [
                sys.executable,
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--output-dir",
                str(tmp_path),
            ],
            input=payloadJson,
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert generateResult.returncode == 0
        stdoutData = json.loads(generateResult.stdout)
        pageId = stdoutData["pageId"]

        # Now delete it
        deleteResult = subprocess.run(
            [
                sys.executable,
                "-m",
                "lib.stats.stats_pages",
                "delete",
                pageId,
                "--output-dir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert deleteResult.returncode == 0

        # Check output JSON
        deleteData = json.loads(deleteResult.stdout)
        assert deleteData["deleted"] == 1

        # Check file was actually deleted
        htmlPath = tmp_path / f"{pageId}.html"
        assert not htmlPath.exists()

    def test_delete_nonexistent_page_outputs_json_deleted_0(self, tmp_path) -> None:
        """Test delete of non-existent page outputs {"deleted": 0}."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lib.stats.stats_pages",
                "delete",
                "nonexistentpageid1234567890abcdef",
                "--output-dir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert result.returncode == 0

        # Check output JSON
        deleteData = json.loads(result.stdout)
        assert deleteData["deleted"] == 0

    def test_generate_output_dir_created_if_not_exists(self, tmp_path) -> None:
        """Test that output directory is created if it doesn't exist."""
        nestedDir = tmp_path / "nested" / "path"

        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }

        payloadJson = json.dumps(payload)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--output-dir",
                str(nestedDir),
            ],
            input=payloadJson,
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert result.returncode == 0
        assert nestedDir.exists()

        stdoutData = json.loads(result.stdout)
        htmlPath = nestedDir / stdoutData["url"]
        assert htmlPath.exists()

    def test_generate_ignores_user_id_chat_id_platform_args(self, tmp_path) -> None:
        """Test that --user-id, --chat-id, --platform args are ignored (metadata only)."""
        payload = {
            "userId": "real_user_id",
            "chatId": "real_chat_id",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }

        payloadJson = json.dumps(payload)

        # Pass different values as CLI args
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--user-id",
                "cli_user_id",
                "--chat-id",
                "cli_chat_id",
                "--platform",
                "max",
                "--output-dir",
                str(tmp_path),
            ],
            input=payloadJson,
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert result.returncode == 0

        stdoutData = json.loads(result.stdout)
        htmlPath = tmp_path / stdoutData["url"]
        htmlContent = htmlPath.read_text()

        # Should use payload values, not CLI args
        assert "real_user_id" in htmlContent
        assert "real_chat_id" in htmlContent
        # The payload has "telegram" platform
        assert "telegram" in htmlContent
        # CLI args should NOT appear (check for specific values)
        assert "cli_user_id" not in htmlContent
        assert "cli_chat_id" not in htmlContent
        # The payload platform should appear, not the CLI arg
        # Check that we see telegram as the platform, not max
        assert "telegram" in htmlContent.lower()

    def test_generate_multiple_runs_produce_unique_ids(self, tmp_path) -> None:
        """Test that multiple generate calls produce unique IDs."""
        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": "2026-08-18T10:30:00+00:00",  # Fixed timestamp
        }

        payloadJson = json.dumps(payload)

        # Generate 5 pages
        pageIds = []
        for _ in range(5):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lib.stats.stats_pages",
                    "generate",
                    "--output-dir",
                    str(tmp_path),
                ],
                input=payloadJson,
                capture_output=True,
                text=True,
                cwd=str(repoRoot),
            )

            assert result.returncode == 0
            stdoutData = json.loads(result.stdout)
            pageIds.append(stdoutData["pageId"])

        # Check all IDs are unique
        assert len(set(pageIds)) == len(pageIds)

        # Check all files exist
        for pageId in pageIds:
            htmlPath = tmp_path / f"{pageId}.html"
            assert htmlPath.exists()

    def test_no_command_provided_returns_nonzero(self) -> None:
        """Test that no command provided causes nonzero exit."""
        result = subprocess.run(
            [sys.executable, "-m", "lib.stats.stats_pages"],
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert result.returncode != 0

    def test_unknown_command_returns_nonzero(self) -> None:
        """Test that unknown command causes nonzero exit."""
        result = subprocess.run(
            [sys.executable, "-m", "lib.stats.stats_pages", "unknown_command"],
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert result.returncode != 0
