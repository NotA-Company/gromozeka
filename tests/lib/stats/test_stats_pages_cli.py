"""Tests for the stats-pages CLI contract.

Tests subprocess invocation, stdin/stdout JSON handling, exit codes,
and the delete command with the new rows-based payload contract.
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
        assert "base-url" in result.stdout

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
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
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

    def test_generate_with_base_url_outputs_full_url(self, tmp_path) -> None:
        """Test that --base-url outputs full URL in stdout."""
        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
        }

        payloadJson = json.dumps(payload)
        baseUrl = "https://example.com/pages"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--output-dir",
                str(tmp_path),
                "--base-url",
                baseUrl,
            ],
            input=payloadJson,
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert result.returncode == 0

        stdoutData = json.loads(result.stdout)

        # Check URL is full URL
        assert stdoutData["url"].startswith(baseUrl)
        assert "https://example.com/pages" in stdoutData["url"]
        assert stdoutData["url"].endswith(".html")

        # Check that NO warning was printed to stderr when baseUrl is provided
        assert "WARNING: --base-url not provided" not in result.stderr

    def test_generate_with_base_url_trailing_slash(self, tmp_path) -> None:
        """Test that --base-url with trailing slash doesn't create double slashes."""
        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
        }

        payloadJson = json.dumps(payload)
        baseUrl = "https://example.com/pages/"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lib.stats.stats_pages",
                "generate",
                "--output-dir",
                str(tmp_path),
                "--base-url",
                baseUrl,
            ],
            input=payloadJson,
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        assert result.returncode == 0

        stdoutData = json.loads(result.stdout)

        # Should not have double slashes
        assert "//pages" not in stdoutData["url"]
        # Should match exact format: https://example.com/pages/<id>.html
        assert stdoutData["url"].startswith("https://example.com/pages/")
        assert stdoutData["url"].endswith(".html")

    def test_generate_without_base_url_outputs_filename(self, tmp_path) -> None:
        """Test that without --base-url, only filename is output."""
        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
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

        # URL should just be the filename (no slashes)
        assert "/" not in stdoutData["url"]
        assert stdoutData["url"].endswith(".html")
        assert stdoutData["url"] == f'{stdoutData["pageId"]}.html'

        # Check that warning was printed to stderr
        assert "WARNING: --base-url not provided" in result.stderr
        assert "generated URL is a bare filename" in result.stderr

    def test_generate_with_sections_renders_all_sections(self, tmp_path) -> None:
        """Test that all sections are rendered from raw rows."""
        # Create sample rows for each event type
        messageRows = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"user_id": "alice"},
                "metricKey": "message_count",
                "metricValue": 80.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {},
                "metricKey": "text_length",
                "metricValue": 5000.0,
            },
        ]

        commandRows = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"commandName": "/help"},
                "metricKey": "command_count",
                "metricValue": 20.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"commandName": "/stats"},
                "metricKey": "command_count",
                "metricValue": 15.0,
            },
        ]

        toolRows = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"toolName": "search"},
                "metricKey": "tool_call_count",
                "metricValue": 20.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {},
                "metricKey": "elapsed_time",
                "metricValue": 15.5,
            },
        ]

        llmRows = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"modelName": "gpt-4o"},
                "metricKey": "request_count",
                "metricValue": 15.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {},
                "metricKey": "input_tokens",
                "metricValue": 10000.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {},
                "metricKey": "output_tokens",
                "metricValue": 5000.0,
            },
        ]

        sttRows = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {},
                "metricKey": "request_count",
                "metricValue": 5.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {},
                "metricKey": "audio_duration_ms",
                "metricValue": 120000.0,
            },
        ]

        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {
                "message": messageRows,
                "command": commandRows,
                "llm_tool_call": toolRows,
                "llm_request": llmRows,
                "stt_request": sttRows,
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

        # Check values are rendered correctly
        assert "80" in htmlContent  # message count
        assert "35" in htmlContent  # command count (20+15)
        assert "20" in htmlContent  # tool calls
        assert "15,000" in htmlContent  # total tokens

    def test_generate_with_chat_list_renders_chat_list(self, tmp_path) -> None:
        """Test that chat list is rendered for private chats."""
        payload = {
            "userId": "user123",
            "chatId": "123456789",
            "chatTitle": "Private Chat",
            "chatType": "private",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
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
        # Missing "rows" field
        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
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

    def test_generate_missing_period_type_returns_nonzero_exit(self) -> None:
        """Test that missing periodType causes nonzero exit."""
        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            # periodType missing
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
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
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
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

    def test_delete_hostile_pageId_does_not_escape_output_dir(self, tmp_path) -> None:
        """Test that delete with hostile pageId does not escape outputDir.

        Regression test for path traversal vulnerability: CLI delete should only
        accept valid uuid4().hex pageIds and reject path traversal attempts.
        Nothing outside tmp_path should be touched.
        """
        # Create a file that could be targeted by path traversal
        # Using ../evil.html (one level up from tmp_path)
        parentDir = tmp_path.parent
        targetFile = parentDir / "evil.html"
        targetFile.write_text("evil content")

        # Try to delete the file using path traversal
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lib.stats.stats_pages",
                "delete",
                "../evil",
                "--output-dir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            cwd=str(repoRoot),
        )

        # Should succeed with deleted: 0 (not-found semantics)
        assert result.returncode == 0

        # Check output JSON
        deleteData = json.loads(result.stdout)
        assert deleteData["deleted"] == 0

        # The evil file should still exist (not deleted by path traversal)
        assert targetFile.exists(), "Path traversal should not delete files outside outputDir"
        assert targetFile.read_text() == "evil content"

        # Clean up the evil file
        targetFile.unlink()

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
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
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

    def test_generate_svg_chart_present_for_time_series(self, tmp_path) -> None:
        """Test that SVG chart is rendered for time-series data."""
        messageRows = [
            {
                "periodType": "hourly",
                "periodStart": "2026-08-18T10:00:00+00:00",
                "labels": {},
                "metricKey": "message_count",
                "metricValue": 10.0,
            },
            {
                "periodType": "hourly",
                "periodStart": "2026-08-18T11:00:00+00:00",
                "labels": {},
                "metricKey": "message_count",
                "metricValue": 20.0,
            },
        ]

        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "3h",
            "periodType": "hourly",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"message": messageRows},
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

        # Check SVG is present
        assert "<svg" in htmlContent
        assert "</svg>" in htmlContent

    def test_generate_no_svg_chart_for_total_granularity(self, tmp_path) -> None:
        """Test that no SVG chart is rendered for total granularity."""
        messageRows = [
            {
                "periodType": "total",
                "periodStart": "1970-01-01T00:00:00+00:00",
                "labels": {},
                "metricKey": "message_count",
                "metricValue": 100.0,
            },
        ]

        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "all",
            "periodType": "total",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"message": messageRows},
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

        # Check SVG is NOT present
        assert "<svg" not in htmlContent

    def test_generate_multiple_runs_produce_unique_ids(self, tmp_path) -> None:
        """Test that multiple generate calls produce unique IDs."""
        payload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": "2026-08-18T10:30:00+00:00",  # Fixed timestamp
            "rows": {},
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
