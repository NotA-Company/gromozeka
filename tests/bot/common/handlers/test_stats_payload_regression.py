"""Tests for the StatsHandler payload data builders (regression tests).

Tests for regressions in payload building logic.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock

from internal.bot.common.handlers.stats import StatsHandler
from internal.bot.models import BotProvider, ChatType, EnsuredMessage
from internal.models.types import MessageId
from internal.services.stats.service import StatsAggregationService
from lib.stats import NullStatsStorage


def buildEnsuredMessage(
    chatId: int = 123,
    chatType: ChatType = ChatType.PRIVATE,
    userId: int = 456,
    username: str = "testuser",
    fullName: str = "Test User",
    messageId: int = 789,
) -> EnsuredMessage:
    """Build a test EnsuredMessage instance.

    Args:
        chatId: Chat ID.
        chatType: Type of chat.
        userId: User ID.
        username: Username.
        fullName: Full name.
        messageId: Message ID.

    Returns:
        EnsuredMessage instance.
    """
    recipient = MagicMock()
    recipient.id = chatId
    recipient.chatType = chatType

    sender = MagicMock()
    sender.id = userId
    sender.username = username
    sender.fullName = fullName

    message = EnsuredMessage(
        sender=sender,
        recipient=recipient,
        messageId=MessageId(messageId),
        date=datetime.datetime.now(datetime.timezone.utc),
    )
    return message


class TestStatsHandlerPayloadDataRegression:
    """Regression tests for payload data builder bugs."""

    async def test_payload_averages_with_non_empty_rows_fix_self_dividing_bug(
        self,
    ):
        """Test regression: FIX 1 averages should use elapsed/time/length, not count.

        This test uses non-empty canned rows to catch the self-dividing bug:
        - commands section: 2 rows, elapsed 2s + 4s, command_count 1+2=3 → avgElapsed == 2.0
        - messages: 2 rows, lengths 10+20, counts 1+1 → avgLength == 15.0
        - tools: 2 rows, elapsed 1s + 3s, tool_call_count 1+2=3 → avgElapsed == 1.33...
        - llm: 2 rows, elapsed 2s + 4s, request_count 1+1=2 → avgElapsed == 3.0
        """
        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        # Mock getUserChats to return empty list since this is a unit test
        mockDatabase.chatUsers.getUserChats = AsyncMock(return_value=[])
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock storage with non-empty canned rows for each section
        def mockQueryStorage(eventType: str) -> MagicMock:
            if eventType == "command":
                # 2 rows: elapsed 2s + 4s, command_count 1+2=3
                storage = MagicMock(spec=NullStatsStorage)
                storage.query = AsyncMock(
                    return_value=[
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "elapsed_time",
                            "metricValue": 2.0,
                        },
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "command_count",
                            "metricValue": 1,
                        },
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "elapsed_time",
                            "metricValue": 4.0,
                        },
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "command_count",
                            "metricValue": 2,
                        },
                    ]
                )
                return storage
            elif eventType == "message":
                # 2 rows: total_length 10+20, message_count 1+1
                storage = MagicMock(spec=NullStatsStorage)
                storage.query = AsyncMock(
                    return_value=[
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "message_count",
                            "metricValue": 1,
                        },
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "text_length",
                            "metricValue": 10,
                        },
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "message_count",
                            "metricValue": 1,
                        },
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "text_length",
                            "metricValue": 20,
                        },
                    ]
                )
                return storage
            elif eventType == "llm_tool_call":
                # 2 rows: elapsed 1s + 3s, tool_call_count 1+2=3
                storage = MagicMock(spec=NullStatsStorage)
                storage.query = AsyncMock(
                    return_value=[
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "elapsed_time",
                            "metricValue": 1.0,
                        },
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "tool_call_count",
                            "metricValue": 1,
                        },
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "elapsed_time",
                            "metricValue": 3.0,
                        },
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "tool_call_count",
                            "metricValue": 2,
                        },
                    ]
                )
                return storage
            elif eventType == "llm_request":
                # 2 rows: elapsed 2s + 4s, request_count 1+1=2
                storage = MagicMock(spec=NullStatsStorage)
                storage.query = AsyncMock(
                    return_value=[
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456", "provider": "test_provider"},
                            "metricKey": "elapsed_time",
                            "metricValue": 2.0,
                        },
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456", "provider": "test_provider"},
                            "metricKey": "request_count",
                            "metricValue": 1,
                        },
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456", "provider": "test_provider"},
                            "metricKey": "elapsed_time",
                            "metricValue": 4.0,
                        },
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456", "provider": "test_provider"},
                            "metricKey": "request_count",
                            "metricValue": 1,
                        },
                    ]
                )
                return storage
            elif eventType == "stt_request":
                storage = MagicMock(spec=NullStatsStorage)
                storage.query = AsyncMock(return_value=[])
                return storage
            else:
                storage = MagicMock(spec=NullStatsStorage)
                storage.query = AsyncMock(return_value=[])
                return storage

        handler.statsAggregationService.getQueryStorage = mockQueryStorage

        # Build payload and verify averages are correct
        payload = await handler._buildStatsPayload(
            targetChatId=123,
            chatType=ChatType.PRIVATE,
            userId=456,
            periodArg="7d",
            periodType="daily",
            periodStartFrom=None,
            periodStartTo=None,
            filterUserId=None,
            positionalChatIdUsed=False,
        )

        # Messages section: avgLength = totalLength / totalMessageCount = 30 / 2 = 15.0
        assert payload["sections"]["messages"]["totalLength"] == 30
        assert payload["sections"]["messages"]["totalMessages"] == 2
        assert payload["sections"]["messages"]["avgLength"] == 15.0

        # Commands section: avgElapsed = totalElapsed / totalCommands = 6.0 / 3 = 2.0
        assert payload["sections"]["commands"]["totalElapsed"] == 6.0
        assert payload["sections"]["commands"]["totalCommands"] == 3
        assert payload["sections"]["commands"]["avgElapsed"] == 2.0

        # Tools section: avgElapsed = totalElapsed / totalCalls = 4.0 / 3 ≈ 1.33
        assert payload["sections"]["tools"]["totalElapsed"] == 4.0
        assert payload["sections"]["tools"]["totalCalls"] == 3
        assert abs(payload["sections"]["tools"]["avgElapsed"] - (4.0 / 3)) < 0.01

        # LLM section: avgElapsed = totalElapsed / totalRequests = 6.0 / 2 = 3.0
        assert payload["sections"]["llm"]["totalElapsed"] == 6.0
        assert payload["sections"]["llm"]["totalRequests"] == 2
        assert payload["sections"]["llm"]["avgElapsed"] == 3.0

        # C-2: Verify provider label key is used (topProviders should be non-empty)
        assert "topProviders" in payload["sections"]["llm"]
        assert len(payload["sections"]["llm"]["topProviders"]) > 0

        # FIX 5: Verify honesty flags are propagated
        assert "possiblyIncomplete" in payload["sections"]["messages"]
        assert "possiblyIncomplete" in payload["sections"]["commands"]
        assert "possiblyIncomplete" in payload["sections"]["tools"]
        assert "possiblyIncomplete" in payload["sections"]["llm"]
        # All sections have < 10000 rows in this test, so flags should be False
        assert payload["sections"]["messages"]["possiblyIncomplete"] is False
        assert payload["sections"]["commands"]["possiblyIncomplete"] is False
        assert payload["sections"]["tools"]["possiblyIncomplete"] is False
        assert payload["sections"]["llm"]["possiblyIncomplete"] is False

    async def test_payload_chatlist_condition_private_no_filter(self):
        """Test regression: chatList payload condition matches reply path (private ∧ no user filter).

        FIX A: The payload condition should be `chatType == PRIVATE and filterUserId is None`,
        matching the reply path condition. This test verifies chatList is present for default
        private scope and absent when a user filter is set.
        """
        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        # Mock getUserChats to return non-empty list
        handler.getUserChats = AsyncMock(
            return_value=[
                {"chat_id": -1001234567890, "title": "Test Group", "messages_count": 100},
                {"chat_id": 123456789, "title": "Test Private", "messages_count": 50},
            ]
        )

        # Mock storage with empty results (not testing stats aggregation here)
        def mockQueryStorage(eventType: str) -> MagicMock:
            storage = MagicMock(spec=NullStatsStorage)
            storage.query = AsyncMock(return_value=[])
            return storage

        handler.statsAggregationService.getQueryStorage = mockQueryStorage

        # Test 1: Private scope with NO user filter → chatList should be present
        payload = await handler._buildStatsPayload(
            targetChatId=123,
            chatType=ChatType.PRIVATE,
            userId=456,
            periodArg="7d",
            periodType="daily",
            periodStartFrom=None,
            periodStartTo=None,
            filterUserId=None,
            positionalChatIdUsed=False,
        )

        assert "chatList" in payload
        assert len(payload["chatList"]) == 2
        assert payload["chatList"][0]["chatId"] == -1001234567890
        assert payload["chatList"][0]["title"] == "Test Group"
        assert payload["chatList"][0]["messagesCount"] == 100

        # Test 2: Private scope WITH user filter → chatList should be absent
        payload = await handler._buildStatsPayload(
            targetChatId=123,
            chatType=ChatType.PRIVATE,
            userId=456,
            periodArg="7d",
            periodType="daily",
            periodStartFrom=None,
            periodStartTo=None,
            filterUserId=789,  # Filter by user
            positionalChatIdUsed=False,
        )

        assert "chatList" not in payload
