"""Tests for the StatsHandler payload data builders (regression tests).

Tests for regressions in payload building logic for the new rows-based contract.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock

from internal.bot.common.handlers.stats import StatsHandler
from internal.bot.models import BotProvider, ChatType, EnsuredMessage
from internal.models.types import MessageId
from internal.services.stats.service import StatsAggregationService
from lib.stats import NullStatsStorage
from lib.stats.stats_pages import StatsPayload
from lib.stats.types import StatsAggregateDict


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

    async def test_payload_rows_contract_and_filters(self):
        """Test regression: payload contains raw rows with proper consumer and user filters.

        This test verifies the new U12-9 rows contract:
        - Payload has all five event types in rows dict
        - Consumer filter drops __global__ and other-chat rows
        - User filter applies to message/command/llm_tool_call only
        - llm_request/stt_request are unfiltered by user (chat-level)
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

        # Mock storage with canned rows including __global__ and other-chat rows
        def mockQueryStorage(eventType: str) -> MagicMock:
            if eventType == "message":
                storage = MagicMock(spec=NullStatsStorage)
                storage.query = AsyncMock(
                    return_value=[
                        # Target chat rows (should be kept)
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "message_count",
                            "metricValue": 10,
                        },
                        # __global__ row (should be dropped)
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "__global__", "user_id": "456"},
                            "metricKey": "message_count",
                            "metricValue": 5,
                        },
                        # Other chat row (should be dropped)
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "999", "user_id": "456"},
                            "metricKey": "message_count",
                            "metricValue": 3,
                        },
                        # Target chat but different user (should be dropped when filterUserId=456)
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "789"},
                            "metricKey": "message_count",
                            "metricValue": 2,
                        },
                    ]
                )
                return storage
            elif eventType == "command":
                storage = MagicMock(spec=NullStatsStorage)
                storage.query = AsyncMock(
                    return_value=[
                        # Target chat rows (should be kept)
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "command_count",
                            "metricValue": 5,
                        },
                        # __global__ row (should be dropped)
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "__global__", "user_id": "456"},
                            "metricKey": "command_count",
                            "metricValue": 2,
                        },
                    ]
                )
                return storage
            elif eventType == "llm_tool_call":
                storage = MagicMock(spec=NullStatsStorage)
                storage.query = AsyncMock(
                    return_value=[
                        # Target chat rows (should be kept)
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "user_id": "456"},
                            "metricKey": "tool_call_count",
                            "metricValue": 3,
                        },
                        # Other chat row (should be dropped)
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "999", "user_id": "456"},
                            "metricKey": "tool_call_count",
                            "metricValue": 1,
                        },
                    ]
                )
                return storage
            elif eventType == "llm_request":
                storage = MagicMock(spec=NullStatsStorage)
                storage.query = AsyncMock(
                    return_value=[
                        # Target chat rows (should be kept, no user filter for llm_request)
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "provider": "test_provider"},
                            "metricKey": "request_count",
                            "metricValue": 2,
                        },
                        # __global__ row (should be dropped)
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "__global__", "provider": "test_provider"},
                            "metricKey": "request_count",
                            "metricValue": 1,
                        },
                        # Other chat row (should be dropped)
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "999", "provider": "test_provider"},
                            "metricKey": "request_count",
                            "metricValue": 1,
                        },
                    ]
                )
                return storage
            elif eventType == "stt_request":
                storage = MagicMock(spec=NullStatsStorage)
                storage.query = AsyncMock(
                    return_value=[
                        # Target chat rows (should be kept, no user filter for stt_request)
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "123", "provider": "test_stt"},
                            "metricKey": "request_count",
                            "metricValue": 1,
                        },
                        # __global__ row (should be dropped)
                        {
                            "periodType": "daily",
                            "periodStart": "2023-08-15T00:00:00Z",
                            "labels": {"consumer": "__global__", "provider": "test_stt"},
                            "metricKey": "request_count",
                            "metricValue": 1,
                        },
                    ]
                )
                return storage
            else:
                storage = MagicMock(spec=NullStatsStorage)
                storage.query = AsyncMock(return_value=[])
                return storage

        handler.statsAggregationService.getQueryStorage = mockQueryStorage

        # Build payload with filterUserId=456
        payload = await handler._buildStatsPayload(
            targetChatId=123,
            chatType=ChatType.PRIVATE,
            userId=456,
            periodArg="7d",
            section="messages",
            periodType="daily",
            periodStartFrom=None,
            periodStartTo=None,
            filterUserId=456,  # User filter applied
            positionalChatIdUsed=False,
        )

        # Verify payload structure has all required meta fields
        assert "userId" in payload
        assert "chatId" in payload
        assert "chatTitle" in payload
        assert "chatType" in payload
        assert "platform" in payload
        assert "period" in payload
        assert "periodType" in payload
        assert "generatedAt" in payload

        # Verify payload has rows dict with all five event types
        assert "rows" in payload
        assert isinstance(payload["rows"], dict)
        assert set(payload["rows"].keys()) == {"message", "command", "llm_tool_call", "llm_request", "stt_request"}

        # Verify message rows: only target chat + user 456, no __global__ or other chat
        messageRows = payload["rows"]["message"]
        assert len(messageRows) == 1
        assert messageRows[0]["labels"]["consumer"] == "123"
        assert messageRows[0]["labels"]["user_id"] == "456"

        # Verify command rows: only target chat + user 456, no __global__
        commandRows = payload["rows"]["command"]
        assert len(commandRows) == 1
        assert commandRows[0]["labels"]["consumer"] == "123"
        assert commandRows[0]["labels"]["user_id"] == "456"

        # Verify llm_tool_call rows: only target chat + user 456, no other chat
        toolRows = payload["rows"]["llm_tool_call"]
        assert len(toolRows) == 1
        assert toolRows[0]["labels"]["consumer"] == "123"
        assert toolRows[0]["labels"]["user_id"] == "456"

        # Verify llm_request rows: only target chat, NO user filter applied, no __global__ or other chat
        llmRows = payload["rows"]["llm_request"]
        assert len(llmRows) == 1
        assert llmRows[0]["labels"]["consumer"] == "123"
        assert "user_id" not in llmRows[0]["labels"]  # llm_request has no user_id label

        # Verify stt_request rows: only target chat, NO user filter applied, no __global__
        sttRows = payload["rows"]["stt_request"]
        assert len(sttRows) == 1
        assert sttRows[0]["labels"]["consumer"] == "123"
        assert "user_id" not in sttRows[0]["labels"]  # stt_request has no user_id label

    async def test_brief_from_payload_reads_rows_by_event_type_keys(self):
        """Test regression: web brief reads payload rows by event-type keys.

        _buildSectionViewFromPayload used to look up payload["rows"] by
        section name ("messages"), but the payload keys rows by event type
        ("message"), so every brief rendered from an empty analyzer and
        showed zeroed counts. The brief must read rows by event type.
        """
        # Reset singleton
        StatsAggregationService._instance = None

        mockConfigManager = MagicMock()
        mockConfigManager.getStatsConfig.return_value = {"enabled": True}
        mockConfigManager.getStatsPagesConfig.return_value = {"enabled": False}
        mockDatabase = MagicMock()
        handler = StatsHandler(configManager=mockConfigManager, database=mockDatabase, botProvider=BotProvider.TELEGRAM)

        handler._resolveUserName = AsyncMock(return_value="@alice")

        payload: StatsPayload = {
            "userId": "456",
            "chatId": "123",
            "chatTitle": "Test User",
            "chatType": "private",
            "platform": "telegram",
            "period": "7d",
            "periodType": "daily",
            "generatedAt": "2026-01-01T00:00:00+00:00",
            "rows": {
                "message": [
                    StatsAggregateDict(
                        periodType="daily",
                        periodStart="2024-01-01T00:00:00+00:00",
                        labels={"consumer": "123", "user_id": "1", "sent": "False"},
                        metricKey="message_count",
                        metricValue=150.0,
                    ),
                ],
                "command": [
                    StatsAggregateDict(
                        periodType="daily",
                        periodStart="2024-01-01T00:00:00+00:00",
                        labels={"consumer": "123", "commandName": "stats"},
                        metricKey="command_count",
                        metricValue=7.0,
                    ),
                ],
                "llm_tool_call": [],
                "llm_request": [],
                "stt_request": [],
            },
        }

        reply = await handler._buildStatsReplyFromPayload(
            payload=payload,
            targetChatId=123,
            chatType=ChatType.PRIVATE,
            userId=456,
            section="messages",
            periodArg="7d",
            filterUserId=None,
            positionalChatIdUsed=False,
        )

        # The messages section must render the payload's real counts,
        # not zeros from a missed rows lookup.
        assert "**Messages:** 150" in reply, f"Expected real message count in brief: {reply}"

        # Section=all variant: the commands section must also read real rows.
        replyAll = await handler._buildStatsReplyFromPayload(
            payload=payload,
            targetChatId=123,
            chatType=ChatType.PRIVATE,
            userId=456,
            section="all",
            periodArg="7d",
            filterUserId=None,
            positionalChatIdUsed=False,
        )
        assert "**Commands:** 7" in replyAll, f"Expected real command count in brief: {replyAll}"

    async def test_payload_chatlist_condition_matches_reply_path(self):
        """Test regression: chatList condition matches reply path exactly.

        FIX N7: The payload condition should be:
        `private ∧ no user filter ∧ no positional chatId ∧ messages section`
        This test verifies chatList is present only when all conditions are met.
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
                {"chat_id": -1001234567890, "title": "Test Group", "username": "", "messages_count": 100},
                {"chat_id": 123456789, "title": "Test Private", "username": "testpriv", "messages_count": 50},
            ]
        )

        # Mock storage with empty results (not testing stats aggregation here)
        def mockQueryStorage(eventType: str) -> MagicMock:
            storage = MagicMock(spec=NullStatsStorage)
            storage.query = AsyncMock(return_value=[])
            return storage

        handler.statsAggregationService.getQueryStorage = mockQueryStorage

        # Test 1: All conditions met → chatList should be present
        payload = await handler._buildStatsPayload(
            targetChatId=123,
            chatType=ChatType.PRIVATE,
            userId=456,
            periodArg="7d",
            section="messages",
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

        # Test 2: User filter set → chatList should be absent
        payload = await handler._buildStatsPayload(
            targetChatId=123,
            chatType=ChatType.PRIVATE,
            userId=456,
            periodArg="7d",
            section="messages",
            periodType="daily",
            periodStartFrom=None,
            periodStartTo=None,
            filterUserId=789,  # Filter by user
            positionalChatIdUsed=False,
        )

        assert "chatList" not in payload

        # Test 3: Positional chatId used → chatList should be absent
        payload = await handler._buildStatsPayload(
            targetChatId=789,  # Positional target
            chatType=ChatType.PRIVATE,
            userId=456,
            periodArg="7d",
            section="messages",
            periodType="daily",
            periodStartFrom=None,
            periodStartTo=None,
            filterUserId=None,
            positionalChatIdUsed=True,  # Positional chatId used
        )

        assert "chatList" not in payload

        # Test 4: Non-messages section → chatList should be absent
        payload = await handler._buildStatsPayload(
            targetChatId=123,
            chatType=ChatType.PRIVATE,
            userId=456,
            periodArg="7d",
            section="commands",  # Non-messages section
            periodType="daily",
            periodStartFrom=None,
            periodStartTo=None,
            filterUserId=None,
            positionalChatIdUsed=False,
        )

        assert "chatList" not in payload

        # Test 5: Group chat → chatList should be absent
        payload = await handler._buildStatsPayload(
            targetChatId=-1001234567890,
            chatType=ChatType.GROUP,  # Group chat
            userId=456,
            periodArg="7d",
            section="messages",
            periodType="daily",
            periodStartFrom=None,
            periodStartTo=None,
            filterUserId=None,
            positionalChatIdUsed=False,
        )

        assert "chatList" not in payload
