"""Tests for the statistics page generator.

Tests the HTML generation, file writing, and payload parsing.
All tests use tmp_path for temporary output directories.
"""

import io
import json
import sys
from datetime import datetime, timezone

import pytest

from lib.stats.stats_pages import StatsPageGenerator, StatsPayload
from lib.stats.stats_pages.generator import readPayload


class TestStatsPageGenerator:
    """Test StatsPageGenerator functionality."""

    def test_generate_creates_uuid_filename_and_html_file(self, tmp_path) -> None:
        """Test that generate creates a UUID filename with .html extension."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sections": {},
        }

        pageId, url = generator.generate(payload)

        # Check URL has correct format
        assert url.endswith(".html")
        assert pageId == url.replace(".html", "")

        # Check file exists
        filePath = tmp_path / url
        assert filePath.exists()

        # Check file has content
        htmlContent = filePath.read_text()
        assert len(htmlContent) > 1000  # Reasonable minimum for HTML template
        assert "<!DOCTYPE html>" in htmlContent
        assert "</html>" in htmlContent

    def test_generate_html_contains_required_sections(self, tmp_path) -> None:
        """Test that generated HTML contains all required meta information."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "-1001234567890",
            "chatTitle": "Test Group",
            "chatType": "group",
            "platform": "telegram",
            "period": "30d",
            "generatedAt": "2026-08-18T10:30:00+00:00",
            "sections": {
                "messages": {
                    "totalMessages": 100,
                    "totalLength": 5000,
                    "userMessages": 80,
                    "botMessages": 20,
                    "historyMessages": 0,
                    "avgLength": 50.0,
                    "topUsers": [("Alice", 30), ("Bob", 25), ("Carol", 15)],
                    "topTypes": [("text", 80), ("image", 20)],
                },
            },
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check meta information is present
        assert "Test Group" in htmlContent
        assert "#-1001234567890" in htmlContent
        assert "user123" in htmlContent
        assert "telegram" in htmlContent
        assert "30d" in htmlContent
        assert "UTC" in htmlContent
        assert "2026-08-18" in htmlContent

        # Check messages section
        assert "💬 Messages" in htmlContent
        assert "100" in htmlContent
        assert "80" in htmlContent
        assert "20" in htmlContent

    def test_generate_html_has_inline_css_no_external_resources(self, tmp_path) -> None:
        """Test that generated HTML has inline CSS and no external resources."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sections": {},
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check for inline CSS
        assert "<style>" in htmlContent
        assert "</style>" in htmlContent

        # Check for NO external stylesheets
        assert "<link" not in htmlContent
        assert "stylesheet" not in htmlContent

        # Check for NO external scripts
        assert "<script src" not in htmlContent
        assert "http://" not in htmlContent
        assert "https://" not in htmlContent

        # Check for NO CDN links (except for inline CSS code references)
        assert "cdn" not in htmlContent.lower()
        assert "google" not in htmlContent.lower()

    def test_generate_html_escapes_special_characters(self, tmp_path) -> None:
        """Test that special characters in payload are properly escaped."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        # Use special characters that need escaping, including hostile generatedAt
        hostileGeneratedAt = '<script>alert("xss")</script> 2026-08-18 & "quotes"'
        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": 'Chat & "Test" <script>',
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": hostileGeneratedAt,
            "sections": {
                "messages": {
                    "totalMessages": 0,
                    "totalLength": 0,
                    "userMessages": 0,
                    "botMessages": 0,
                    "historyMessages": 0,
                    "avgLength": 0.0,
                    "topUsers": [("User & Bob", 10)],
                    "topTypes": [],
                },
            },
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check that special characters are escaped
        assert "&amp;" in htmlContent  # & escaped
        assert "&quot;" in htmlContent  # " escaped
        assert "&lt;" in htmlContent  # < escaped
        assert "&gt;" in htmlContent  # > escaped

        # Check that unescaped versions are NOT present in text content
        assert 'Chat & "Test" <script>' not in htmlContent

        # Check hostile generatedAt is escaped (in the generated-at meta row)
        assert hostileGeneratedAt not in htmlContent  # Raw hostile string should NOT appear
        assert "&lt;script&gt;alert" in htmlContent  # Escaped version should appear

    def test_generate_with_all_sections(self, tmp_path) -> None:
        """Test generation with all sections present."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
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
                    "topUsers": [("Alice", 30), ("Bob", 25), ("Carol", 15)],
                    "topTypes": [("text", 80), ("image", 20)],
                },
                "commands": {
                    "totalCommands": 50,
                    "errorCommands": 5,
                    "topCommands": [("/help", 20), ("/stats", 15), ("/users", 10)],
                },
                "tools": {
                    "totalCalls": 30,
                    "errorCalls": 2,
                    "totalElapsed": 15.5,
                    "avgElapsed": 0.517,
                    "topTools": [("search", 20), ("python", 10)],
                },
                "llm": {
                    "totalRequests": 20,
                    "errorRequests": 1,
                    "inputTokens": 10000,
                    "outputTokens": 5000,
                    "totalTokens": 15000,
                    "totalElapsed": 10.0,
                    "avgElapsed": 0.5,
                    "topModels": [("gpt-4o", 15), ("claude-3", 5)],
                    "topProviders": [("openai", 15), ("anthropic", 5)],
                    "stt": {
                        "totalRequests": 5,
                        "errorRequests": 0,
                        "totalAudioDuration": 120.0,
                    },
                },
            },
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check all sections are present
        assert "💬 Messages" in htmlContent
        assert "🔧 Commands" in htmlContent
        assert "🛠️ Tools" in htmlContent
        assert "🧠 LLM" in htmlContent

        # Check LLM content
        assert "15,000" in htmlContent  # total tokens (formatted with commas)
        assert "10.00s" in htmlContent  # total time
        assert "gpt-4o" in htmlContent
        assert "openai" in htmlContent

        # Check STT subsection within LLM
        assert "🎤 Speech-to-Text" in htmlContent
        assert "120.00s" in htmlContent  # audio duration

    def test_generate_with_chat_list(self, tmp_path) -> None:
        """Test generation with chat list (private scope)."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "123456789",
            "chatTitle": "Private Chat",
            "chatType": "private",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sections": {},
            "chatList": [
                {"chatId": -1001234567890, "title": "Group A", "messagesCount": 300},
                {"chatId": -1009876543210, "title": "Group B", "messagesCount": 210},
                {"chatId": 123456789, "title": "Private With Bob", "messagesCount": 42},
            ],
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check chat list section
        assert "📋 Your Chats" in htmlContent
        assert "Group A" in htmlContent
        assert "#-1001234567890" in htmlContent
        assert "300" in htmlContent
        assert "Group B" in htmlContent
        assert "Private With Bob" in htmlContent

    def test_delete_existing_page(self, tmp_path) -> None:
        """Test that delete removes an existing page file."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        # Create a page first
        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sections": {},
        }

        pageId, url = generator.generate(payload)
        filePath = tmp_path / url
        assert filePath.exists()

        # Delete the page
        deleted = generator.delete(pageId)

        assert deleted == 1
        assert not filePath.exists()

    def test_delete_nonexistent_page(self, tmp_path) -> None:
        """Test that delete handles non-existent pages gracefully."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        # Try to delete a page that doesn't exist
        deleted = generator.delete("nonexistentpageid1234567890abcdef")

        assert deleted == 0

    def test_generates_unique_ids_for_multiple_pages(self, tmp_path) -> None:
        """Test that multiple generates produce unique page IDs."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sections": {},
        }

        # Generate multiple pages
        pageIds = []
        for _ in range(5):
            pageId, url = generator.generate(payload)
            pageIds.append(pageId)

        # Check all page IDs are unique
        assert len(set(pageIds)) == len(pageIds)

        # Check all files exist
        for pageId in pageIds:
            filePath = tmp_path / f"{pageId}.html"
            assert filePath.exists()

    def test_generates_same_content_for_same_payload(self, tmp_path) -> None:
        """Test that identical payloads produce the same HTML (deterministic)."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sections": {},
        }

        # Generate two pages
        pageId1, url1 = generator.generate(payload)
        pageId2, url2 = generator.generate(payload)

        # IDs should be different (UUID)
        assert pageId1 != pageId2

        # Content should be the same (except for the generatedAt in the HTML
        # which we fixed in the payload, so they should match)
        htmlContent1 = (tmp_path / url1).read_text()
        htmlContent2 = (tmp_path / url2).read_text()

        # The content should be identical
        assert htmlContent1 == htmlContent2

    def test_empty_sections_dont_break_generation(self, tmp_path) -> None:
        """Test that empty sections don't break page generation."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sections": {
                "messages": {
                    "totalMessages": 0,
                    "totalLength": 0,
                    "userMessages": 0,
                    "botMessages": 0,
                    "historyMessages": 0,
                    "avgLength": 0.0,
                    "topUsers": [],
                    "topTypes": [],
                },
                "commands": {"totalCommands": 0, "errorCommands": 0, "topCommands": []},
                "tools": {
                    "totalCalls": 0,
                    "errorCalls": 0,
                    "totalElapsed": 0.0,
                    "avgElapsed": 0.0,
                    "topTools": [],
                },
                "llm": {
                    "totalRequests": 0,
                    "errorRequests": 0,
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "totalTokens": 0,
                    "totalElapsed": 0.0,
                    "avgElapsed": 0.0,
                    "topModels": [],
                    "topProviders": [],
                },
            },
        }

        # Should not raise any exceptions
        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check HTML was generated
        assert "<!DOCTYPE html>" in htmlContent
        assert "0" in htmlContent  # Zero values should be present

    def test_chat_list_renders_all_items(self, tmp_path) -> None:
        """Test that all chat list items are rendered (no truncation)."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        # Create a chat list with more than 10 items
        chatList = [{"chatId": -1000000000000 + i, "title": f"Chat {i}", "messagesCount": i * 10} for i in range(15)]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "123456789",
            "chatTitle": "Private Chat",
            "chatType": "private",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sections": {},
            "chatList": chatList,
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check chat list section exists
        assert "📋 Your Chats" in htmlContent

        # ALL 15 chats should be present (no truncation)
        for i in range(15):
            assert f"Chat {i}" in htmlContent

        # Check a few specific chat IDs are present
        assert "#-1000000000000" in htmlContent
        assert "#-999999999995" in htmlContent  # Chat 14

    def test_large_numbers_formatted_with_commas(self, tmp_path) -> None:
        """Test that large numbers are formatted with commas."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sections": {
                "messages": {
                    "totalMessages": 1234567,
                    "totalLength": 9876543210,
                    "userMessages": 987654,
                    "botMessages": 246913,
                    "historyMessages": 0,
                    "avgLength": 7998.5,
                    "topUsers": [],
                    "topTypes": [],
                },
                "llm": {
                    "totalRequests": 1000000,
                    "errorRequests": 0,
                    "inputTokens": 5000000000,
                    "outputTokens": 2500000000,
                    "totalTokens": 7500000000,
                    "totalElapsed": 1000000.0,
                    "avgElapsed": 1.0,
                    "topModels": [],
                    "topProviders": [],
                },
            },
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check that large numbers are formatted with commas
        assert "1,234,567" in htmlContent  # totalMessages
        assert "9,876,543,210" in htmlContent  # totalLength
        assert "987,654" in htmlContent  # userMessages
        assert "246,913" in htmlContent  # botMessages
        assert "5,000,000,000" in htmlContent  # inputTokens
        assert "2,500,000,000" in htmlContent  # outputTokens
        assert "7,500,000,000" in htmlContent  # totalTokens

    def test_large_top_lists_render_all_items(self, tmp_path) -> None:
        """Test that top lists with >5 items render all items (no truncation)."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        # Create top lists with >5 items
        topUsers = [(f"User {i}", 100 - i) for i in range(10)]
        topCommands = [(f"/command{i}", 50 - i) for i in range(7)]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sections": {
                "messages": {
                    "totalMessages": 1000,
                    "totalLength": 50000,
                    "userMessages": 800,
                    "botMessages": 200,
                    "historyMessages": 0,
                    "avgLength": 50.0,
                    "topUsers": topUsers,
                    "topTypes": [],
                },
                "commands": {
                    "totalCommands": 100,
                    "errorCommands": 0,
                    "topCommands": topCommands,
                },
            },
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check ALL top users are present (10 users)
        for i in range(10):
            assert f"User {i}" in htmlContent

        # Check ALL commands are present (7 commands)
        for i in range(7):
            assert f"/command{i}" in htmlContent


class TestReadPayload:
    """Test payload reading from stdin."""

    def test_read_valid_json_from_stdin(self) -> None:
        """Test reading valid JSON from stdin."""
        payloadDict = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "generatedAt": "2026-08-18T10:30:00+00:00",
        }

        mockStdin = json.dumps(payloadDict)

        fakeStdin = io.StringIO(mockStdin)
        originalStdin = sys.stdin
        sys.stdin = fakeStdin

        try:
            payload = readPayload()

            assert payload.get("userId") == "user123"
            assert payload.get("chatId") == "chat456"
            assert payload.get("chatTitle") == "Test Chat"
        finally:
            sys.stdin = originalStdin

    def test_read_invalid_json_raises_error(self) -> None:
        """Test that invalid JSON raises a ValueError."""
        fakeStdin = io.StringIO("{ invalid json }")
        originalStdin = sys.stdin
        sys.stdin = fakeStdin

        try:
            with pytest.raises(ValueError, match="Invalid JSON"):
                readPayload()
        finally:
            sys.stdin = originalStdin

    def test_read_missing_required_field_raises_error(self) -> None:
        """Test that missing required fields raise a ValueError."""
        # Missing required field "period"
        payloadDict = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "generatedAt": "2026-08-18T10:30:00+00:00",
        }

        fakeStdin = io.StringIO(json.dumps(payloadDict))
        originalStdin = sys.stdin
        sys.stdin = fakeStdin

        try:
            with pytest.raises(ValueError, match="Missing required field"):
                readPayload()
        finally:
            sys.stdin = originalStdin

    def test_rendering_possiblyIncomplete_flag(self, tmp_path) -> None:
        """Test that possiblyIncomplete flag renders honesty line in sections."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
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
                    "topUsers": [],
                    "topTypes": [],
                    "possiblyIncomplete": True,  # Flag set to True
                },
                "commands": {
                    "totalCommands": 50,
                    "errorCommands": 5,
                    "topCommands": [],
                    "possiblyIncomplete": False,  # Flag set to False
                },
                "tools": {
                    "totalCalls": 30,
                    "errorCalls": 2,
                    "totalElapsed": 15.5,
                    "avgElapsed": 0.517,
                    "topTools": [],
                    "possiblyIncomplete": True,  # Flag set to True
                },
                "llm": {
                    "totalRequests": 20,
                    "errorRequests": 1,
                    "inputTokens": 10000,
                    "outputTokens": 5000,
                    "totalTokens": 15000,
                    "totalElapsed": 10.0,
                    "avgElapsed": 0.5,
                    "topModels": [],
                    "topProviders": [],
                    "possiblyIncomplete": False,  # Flag set to False
                },
            },
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check that honesty line appears in sections with flag=True
        assert "⚠ Результаты могут быть неполными (достигнут лимит запроса)" in htmlContent

        # Check that messages section (flag=True) has honesty line
        assert "💬 Messages" in htmlContent
        messagesSectionStart = htmlContent.find("💬 Messages")
        messagesSectionEnd = htmlContent.find("🔧 Commands", messagesSectionStart)
        messagesHtml = htmlContent[messagesSectionStart:messagesSectionEnd]
        assert "⚠ Результаты могут быть неполными (достигнут лимит запроса)" in messagesHtml

        # Check that commands section (flag=False) does NOT have honesty line
        assert "🔧 Commands" in htmlContent
        commandsSectionStart = htmlContent.find("🔧 Commands")
        commandsSectionEnd = htmlContent.find("🛠️ Tools", commandsSectionStart)
        commandsHtml = htmlContent[commandsSectionStart:commandsSectionEnd]
        assert "⚠ Результаты могут быть неполными (достигнут лимит запроса)" not in commandsHtml

        # Check that tools section (flag=True) has honesty line
        assert "🛠️ Tools" in htmlContent
        toolsSectionStart = htmlContent.find("🛠️ Tools")
        toolsSectionEnd = htmlContent.find("🧠 LLM", toolsSectionStart)
        toolsHtml = htmlContent[toolsSectionStart:toolsSectionEnd]
        assert "⚠ Результаты могут быть неполными (достигнут лимит запроса)" in toolsHtml

        # Check that LLM section (flag=False) does NOT have honesty line
        assert "🧠 LLM" in htmlContent
        llmSectionStart = htmlContent.find("🧠 LLM")
        llmHtml = htmlContent[llmSectionStart:]
        assert "⚠ Результаты могут быть неполными (достигнут лимит запроса)" not in llmHtml

        # Test with all flags=False - no honesty lines should appear
        payload2: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat 2",
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
                    "topUsers": [],
                    "topTypes": [],
                    "possiblyIncomplete": False,
                },
                "commands": {
                    "totalCommands": 50,
                    "errorCommands": 5,
                    "topCommands": [],
                    "possiblyIncomplete": False,
                },
            },
        }

        pageId2, url2 = generator.generate(payload2)
        htmlContent2 = (tmp_path / url2).read_text()

        # No honesty lines should appear
        assert "⚠ Результаты могут быть неполными (достигнут лимит запроса)" not in htmlContent2
