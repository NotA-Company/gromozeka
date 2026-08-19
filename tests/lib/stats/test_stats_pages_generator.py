"""Tests for the statistics page generator.

Tests the HTML generation from raw aggregate rows, file writing, and
payload parsing. All tests use tmp_path for temporary output directories.
"""

import io
import json
import re
import sys
from datetime import datetime, timezone

import pytest

from lib.stats.stats_pages import ChatListEntry, StatsPageGenerator, StatsPayload
from lib.stats.stats_pages.generator import readPayload
from lib.stats.types import StatsAggregateDict


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
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
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

    def test_generate_with_base_url_constructs_full_url(self, tmp_path) -> None:
        """Test that baseUrl parameter constructs full URLs."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
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

        baseUrl = "https://example.com/pages"
        pageId, url = generator.generate(payload, baseUrl=baseUrl)

        # Check URL is full URL
        assert url == f"{baseUrl}/{pageId}.html"
        assert "https://example.com/pages" in url
        assert url.endswith(".html")

    def test_generate_with_base_url_trailing_slash(self, tmp_path) -> None:
        """Test that baseUrl with trailing slash is handled correctly."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
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

        baseUrl = "https://example.com/pages/"
        pageId, url = generator.generate(payload, baseUrl=baseUrl)

        # Should not have double slashes
        assert url == f"https://example.com/pages/{pageId}.html"
        assert "//pages" not in url  # No double slash before pages

    def test_generate_without_base_url_returns_filename(self, tmp_path) -> None:
        """Test that without baseUrl, only the filename is returned."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
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

        pageId, url = generator.generate(payload, baseUrl=None)

        # URL should just be the filename
        assert url == f"{pageId}.html"
        assert "/" not in url

    def test_user_filter_annotation_in_llm_section(self, tmp_path) -> None:
        """Test that user filter annotation appears in LLM section when userFilterApplied is true."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        # Create sample LLM rows
        llmRows: list[StatsAggregateDict] = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"modelName": "gpt-4o"},
                "metricKey": "request_count",
                "metricValue": 10.0,
            },
        ]

        # Test with userFilterApplied = True
        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"llm_request": llmRows},
            "userFilterApplied": True,
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check that the annotation is present
        assert "на уровне чата, не пользователя" in htmlContent

        # Test with userFilterApplied = False (or absent)
        payload2: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"llm_request": llmRows},
            "userFilterApplied": False,
        }

        pageId2, url2 = generator.generate(payload2)
        htmlContent2 = (tmp_path / url2).read_text()

        # Check that the annotation is NOT present
        assert "на уровне чата, не пользователя" not in htmlContent2

    def test_generate_html_contains_required_sections(self, tmp_path) -> None:
        """Test that generated HTML contains all required meta information."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        # Create sample message rows
        messageRows: list[StatsAggregateDict] = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"sent": "True", "user_id": "alice"},
                "metricKey": "message_count",
                "metricValue": 30.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"sent": "True", "user_id": "bob"},
                "metricKey": "message_count",
                "metricValue": 25.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"sent": "False"},
                "metricKey": "message_count",
                "metricValue": 20.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"message_type": "text"},
                "metricKey": "message_count",
                "metricValue": 75.0,
            },
        ]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "-1001234567890",
            "chatTitle": "Test Group",
            "chatType": "group",
            "platform": "telegram",
            "period": "30d",
            "periodType": "daily",
            "generatedAt": "2026-08-18T10:30:00+00:00",
            "rows": {"message": messageRows},
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check meta information is present
        assert "Test Group" in htmlContent
        assert "#-1001234567890" in htmlContent
        assert "user123" in htmlContent
        assert "telegram" in htmlContent
        assert "30d" in htmlContent
        assert "daily" in htmlContent
        assert "UTC" in htmlContent
        assert "2026-08-18" in htmlContent

        # Check messages section
        assert "💬 Messages" in htmlContent
        assert "75" in htmlContent  # total messages

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
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
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
            "periodType": "daily",
            "generatedAt": hostileGeneratedAt,
            "rows": {},
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

        # Create sample rows for each event type
        messageRows: list[StatsAggregateDict] = [
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

        commandRows: list[StatsAggregateDict] = [
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

        toolRows: list[StatsAggregateDict] = [
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

        llmRows: list[StatsAggregateDict] = [
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
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {},
                "metricKey": "elapsed_time",
                "metricValue": 10.0,
            },
        ]

        sttRows: list[StatsAggregateDict] = [
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
                "metricValue": 120000.0,  # 120 seconds
            },
        ]

        payload: StatsPayload = {
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
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
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
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
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
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
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
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
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

    def test_empty_rows_render_empty_sections(self, tmp_path) -> None:
        """Test that empty rows render sections with zeros."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {
                "message": [],
                "command": [],
                "llm_tool_call": [],
                "llm_request": [],
                "stt_request": [],
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
        chatList: list[ChatListEntry] = [
            {"chatId": -1000000000000 + i, "title": f"Chat {i}", "messagesCount": i * 10} for i in range(15)
        ]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "123456789",
            "chatTitle": "Private Chat",
            "chatType": "private",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {},
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

        messageRows: list[StatsAggregateDict] = [
            {
                "periodType": "total",
                "periodStart": "1970-01-01T00:00:00+00:00",
                "labels": {},
                "metricKey": "message_count",
                "metricValue": 1234567.0,
            },
            {
                "periodType": "total",
                "periodStart": "1970-01-01T00:00:00+00:00",
                "labels": {},
                "metricKey": "text_length",
                "metricValue": 9876543210.0,
            },
        ]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "total",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"message": messageRows},
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check that large numbers are formatted with commas
        assert "1,234,567" in htmlContent  # totalMessages
        assert "9,876,543,210" in htmlContent  # totalLength


class TestGroupingCorrectness:
    """Test server-side grouping correctness from raw rows."""

    def test_message_section_grouping_by_sent(self, tmp_path) -> None:
        """Test message section correctly groups by sent label."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        messageRows: list[StatsAggregateDict] = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"sent": "False", "user_id": "alice"},
                "metricKey": "message_count",
                "metricValue": 30.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"sent": "False", "user_id": "bob"},
                "metricKey": "message_count",
                "metricValue": 25.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"sent": "True", "user_id": "bot"},
                "metricKey": "message_count",
                "metricValue": 20.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {},  # Backfill - no sent label
                "metricKey": "message_count",
                "metricValue": 5.0,
            },
        ]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"message": messageRows},
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Total messages: 30 + 25 + 20 + 5 = 80
        assert re.search(r"Total Messages</td>\s*<td[^>]*>80<", htmlContent)

        # User messages (sent=False): 30 + 25 = 55
        assert re.search(r"User Messages</td>\s*<td[^>]*>55<", htmlContent)

        # Bot messages (sent=True): 20
        assert re.search(r"Bot Messages</td>\s*<td[^>]*>20<", htmlContent)

        # History (no sent label): 5
        assert re.search(r"History \(before stats enabled\)</td>\s*<td[^>]*>5<", htmlContent)

    def test_message_section_average_length_calculation(self, tmp_path) -> None:
        """Test message section correctly calculates average length."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        messageRows: list[StatsAggregateDict] = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {},
                "metricKey": "message_count",
                "metricValue": 100.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {},
                "metricKey": "text_length",
                "metricValue": 5000.0,
            },
        ]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"message": messageRows},
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Average length: 5000 / 100 = 50.0
        assert "50.00" in htmlContent

    def test_message_section_top_users(self, tmp_path) -> None:
        """Test message section correctly identifies top users."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        messageRows: list[StatsAggregateDict] = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"user_id": "alice", "sent": "False"},
                "metricKey": "message_count",
                "metricValue": 50.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"user_id": "bob", "sent": "False"},
                "metricKey": "message_count",
                "metricValue": 40.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"user_id": "carol", "sent": "False"},
                "metricKey": "message_count",
                "metricValue": 30.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"user_id": "bot", "sent": "True"},
                "metricKey": "message_count",
                "metricValue": 1000.0,  # Bot with many messages, should be excluded
            },
        ]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"message": messageRows},
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check top users table exists
        assert "Top Users by Messages" in htmlContent

        # Check all users are present
        assert "alice" in htmlContent
        assert "bob" in htmlContent
        assert "carol" in htmlContent

        # Bot has the highest count but must be absent from the Top Users table
        topUsersMatch = re.search(r"Top Users by Messages.*?</table>", htmlContent, re.DOTALL)
        assert topUsersMatch is not None
        assert "<td>bot</td>" not in topUsersMatch.group(0)
        assert "1,000" not in topUsersMatch.group(0)

    def test_command_section_grouping(self, tmp_path) -> None:
        """Test command section correctly groups metrics."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        commandRows: list[StatsAggregateDict] = [
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
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"commandName": "/help"},
                "metricKey": "is_error",
                "metricValue": 1.0,
            },
        ]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"command": commandRows},
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Total commands: 20 + 15 = 35
        assert "35" in htmlContent

        # Errors: 1
        assert "1" in htmlContent

        # Successful: 35 - 1 = 34
        assert "34" in htmlContent

    def test_tools_section_average_time(self, tmp_path) -> None:
        """Test tools section correctly calculates average time."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        toolRows: list[StatsAggregateDict] = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {},
                "metricKey": "tool_call_count",
                "metricValue": 10.0,
            },
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {},
                "metricKey": "elapsed_time",
                "metricValue": 5.0,
            },
        ]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"llm_tool_call": toolRows},
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Average time: 5.0 / 10 = 0.5
        assert "0.50s" in htmlContent

    def test_llm_section_token_totals(self, tmp_path) -> None:
        """Test LLM section correctly totals input and output tokens."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        llmRows: list[StatsAggregateDict] = [
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

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"llm_request": llmRows},
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check token counts
        assert "10,000" in htmlContent  # input tokens
        assert "5,000" in htmlContent  # output tokens
        assert "15,000" in htmlContent  # total tokens


class TestSvgCharts:
    """Test inline SVG chart rendering."""

    def test_svg_chart_rendered_for_hourly_data(self, tmp_path) -> None:
        """Test that SVG chart is rendered for hourly time series."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        messageRows: list[StatsAggregateDict] = [
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
            {
                "periodType": "hourly",
                "periodStart": "2026-08-18T12:00:00+00:00",
                "labels": {},
                "metricKey": "message_count",
                "metricValue": 15.0,
            },
        ]

        payload: StatsPayload = {
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

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check SVG element is present
        assert "<svg" in htmlContent
        assert "</svg>" in htmlContent

        # Check for bar elements
        assert "<rect" in htmlContent

    def test_no_svg_chart_for_total_granularity(self, tmp_path) -> None:
        """Test that no SVG chart is rendered for total granularity."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        messageRows: list[StatsAggregateDict] = [
            {
                "periodType": "total",
                "periodStart": "1970-01-01T00:00:00+00:00",
                "labels": {},
                "metricKey": "message_count",
                "metricValue": 100.0,
            },
        ]

        payload: StatsPayload = {
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

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check NO SVG element is present
        assert "<svg" not in htmlContent

    def test_svg_chart_with_empty_time_series(self, tmp_path) -> None:
        """Test that empty time series doesn't render chart."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"message": []},
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check NO SVG element is present (empty data)
        assert "<svg" not in htmlContent


class TestHonestyLine:
    """Test honesty line rendering for 10000-row limit."""

    def test_honesty_line_for_10000_rows(self, tmp_path) -> None:
        """Test that honesty line appears when rows == 10000."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        # Create exactly 10000 dummy rows
        messageRows: list[StatsAggregateDict] = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"user_id": f"user_{i}"},
                "metricKey": "message_count",
                "metricValue": 1.0,
            }
            for i in range(10000)
        ]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"message": messageRows},
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check honesty line is present
        assert "⚠ Результаты могут быть неполными (достигнут лимит запроса)" in htmlContent

    def test_no_honesty_line_for_less_than_10000_rows(self, tmp_path) -> None:
        """Test that honesty line does NOT appear when rows < 10000."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        # Create only 9999 rows
        messageRows: list[StatsAggregateDict] = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"user_id": f"user_{i}"},
                "metricKey": "message_count",
                "metricValue": 1.0,
            }
            for i in range(9999)
        ]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"message": messageRows},
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check honesty line is NOT present
        assert "⚠ Результаты могут быть неполными (достигнут лимит запроса)" not in htmlContent

    def test_honesty_line_from_truncatedEventTypes_with_sub_10000_rows(self, tmp_path) -> None:
        """Test that honesty line appears from truncatedEventTypes flag with sub-10000 rows.

        This tests the NEW path (not the len==10000 fallback) - proves the flag works
        independently of row count.
        """
        generator = StatsPageGenerator(outputDir=tmp_path)

        # Create only 50 rows (well below 10000)
        messageRows: list[StatsAggregateDict] = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"user_id": f"user_{i}"},
                "metricKey": "message_count",
                "metricValue": 1.0,
            }
            for i in range(50)
        ]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"message": messageRows},
            "truncatedEventTypes": ["message"],  # Flag triggers honesty line despite sub-10000 rows
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check honesty line IS present (from flag, not from row count)
        assert "⚠ Результаты могут быть неполными (достигнут лимит запроса)" in htmlContent

    def test_honesty_line_for_multiple_sections_from_truncatedEventTypes(self, tmp_path) -> None:
        """Test that honesty line appears for multiple sections from truncatedEventTypes."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        # Create sub-10000 rows for each section
        commandRows: list[StatsAggregateDict] = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {"commandName": "/test"},
                "metricKey": "command_count",
                "metricValue": 1.0,
            }
            for _ in range(10)
        ]

        sttRows: list[StatsAggregateDict] = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {},
                "metricKey": "request_count",
                "metricValue": 1.0,
            }
            for _ in range(5)
        ]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {
                "command": commandRows,
                "llm_request": [],
                "stt_request": sttRows,
            },
            "truncatedEventTypes": ["command", "stt_request"],  # Multiple sections truncated
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Both sections should have honesty lines (verify no duplication)
        # Count occurrences - should be exactly 2
        count = htmlContent.count("⚠ Результаты могут быть неполными (достигнут лимит запроса)")
        assert count == 2


class TestLabelEscaping:
    """Test that labels are properly escaped to prevent XSS."""

    def test_hostile_labels_escaped_in_html(self, tmp_path) -> None:
        """Test that hostile label values are properly escaped."""
        generator = StatsPageGenerator(outputDir=tmp_path)

        messageRows: list[StatsAggregateDict] = [
            {
                "periodType": "daily",
                "periodStart": "2026-08-18T00:00:00+00:00",
                "labels": {
                    "user_id": '<script>alert("xss")</script>',
                    "sent": "False",
                },
                "metricKey": "message_count",
                "metricValue": 10.0,
            },
        ]

        payload: StatsPayload = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": {"message": messageRows},
        }

        pageId, url = generator.generate(payload)
        htmlContent = (tmp_path / url).read_text()

        # Check that the hostile string is NOT present
        assert '<script>alert("xss")</script>' not in htmlContent

        # Check that it's escaped
        assert "&lt;script&gt;" in htmlContent


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
            "periodType": "daily",
            "generatedAt": "2026-08-18T10:30:00+00:00",
            "rows": {},
        }

        mockStdin = json.dumps(payloadDict)

        fakeStdin = io.StringIO(mockStdin)
        originalStdin = sys.stdin
        sys.stdin = fakeStdin

        try:
            payload = readPayload()

            assert payload["userId"] == "user123"
            assert payload["chatId"] == "chat456"
            assert payload["chatTitle"] == "Test Chat"
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
        # Missing required field "rows"
        payloadDict = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
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

    def test_read_missing_period_type_raises_error(self) -> None:
        """Test that missing periodType raises a ValueError."""
        payloadDict = {
            "userId": "user123",
            "chatId": "chat456",
            "chatTitle": "Test Chat",
            "chatType": "group",
            "platform": "telegram",
            "period": "7d",
            # periodType missing
            "generatedAt": "2026-08-18T10:30:00+00:00",
            "rows": {},
        }

        fakeStdin = io.StringIO(json.dumps(payloadDict))
        originalStdin = sys.stdin
        sys.stdin = fakeStdin

        try:
            with pytest.raises(ValueError, match="Missing required field"):
                readPayload()
        finally:
            sys.stdin = originalStdin
