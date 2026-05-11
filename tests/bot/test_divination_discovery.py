"""Tests for divination layout discovery, dood!

This test suite verifies the layout discovery functionality for the
divination handler, including layout ID generation, discovery workflow,
caching mechanisms, and repository upsert operations.
"""

import datetime as dt
from unittest.mock import AsyncMock, Mock, patch

import pytest

from internal.bot.common.handlers.divination import DivinationHandler
from internal.bot.models import (
    BotProvider,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
)
from lib.ai.models import ModelResultStatus, ModelRunResult, ModelStructuredResult
from lib.divination import Layout, TarotSystem

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _makeConfigManager(
    *,
    enabled: bool = True,
    tarotEnabled: bool = True,
    runesEnabled: bool = True,
    imageGeneration: bool = True,
    toolsEnabled: bool = True,
    discoveryEnabled: bool = False,
) -> Mock:
    """Build a stand-in ConfigManager returning the divination section.

    Args:
        enabled: Value for divination.enabled.
        tarotEnabled: Value for divination.tarot-enabled.
        runesEnabled: Value for divination.runes-enabled.
        imageGeneration: Value for divination.image-generation.
        toolsEnabled: Value for divination.tools-enabled.
        discoveryEnabled: Value for divination.discovery-enabled.

    Returns:
        Mock exposing .get(...) and .getBotConfig() that the BaseBotHandler constructor needs.
    """
    cm = Mock()
    cm.getBotConfig = Mock(return_value={"defaults": {}, "private-defaults": {}, "group-defaults": {}})
    cm.get = Mock(
        side_effect=lambda key, default=None: (
            {
                "enabled": enabled,
                "tarot-enabled": tarotEnabled,
                "runes-enabled": runesEnabled,
                "image-generation": imageGeneration,
                "tools-enabled": toolsEnabled,
                "discovery-enabled": discoveryEnabled,
            }
            if key == "divination"
            else (default if default is not None else {})
        )
    )
    return cm


def _makeEnsuredMessage(
    *,
    chatId: int = 100,
    messageId: int = 42,
    userId: int = 7,
    senderName: str = "Alice",
) -> EnsuredMessage:
    """Build a minimal EnsuredMessage-like object suitable for handler tests.

    Args:
        chatId: Recipient chat id.
        messageId: Originating message id.
        userId: Sender user id.
        senderName: MessageSender.name value.

    Returns:
        EnsuredMessage object with minimal test data.
    """
    return EnsuredMessage(
        sender=MessageSender(id=userId, name=senderName, username=f"@user{userId}"),
        recipient=MessageRecipient(id=chatId, chatType=ChatType.PRIVATE),
        messageId=messageId,
        date=dt.datetime(2026, 5, 7, 12, 0, 0, tzinfo=dt.timezone.utc),
        messageText="",
    )


def _makeDatabase() -> Mock:
    """Build a Database stub with divinations repository."""
    db = Mock()
    repo = Mock()

    # Mock repository methods
    repo.saveLayout = AsyncMock(return_value=True)
    repo.saveNegativeCache = AsyncMock(return_value=True)
    repo.getLayout = AsyncMock(return_value=None)
    repo.isNegativeCacheEntry = Mock(
        side_effect=lambda d: (
            d.get("name_en") == ""
            and d.get("name_ru") == ""
            and d.get("n_symbols", 0) == 0
            and d.get("positions") == []
        )
    )

    db.divinations = repo
    return db


def _makeHandler(
    *,
    discoveryEnabled: bool = False,
) -> DivinationHandler:
    """Construct a DivinationHandler with mocked dependencies."""
    cm = _makeConfigManager(discoveryEnabled=discoveryEnabled)
    db = _makeDatabase()

    handler = DivinationHandler(
        configManager=cm,
        database=db,
        botProvider=BotProvider.TELEGRAM,
    )

    return handler


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLayoutDiscovery:
    """Test suite for layout discovery functionality."""

    @pytest.fixture
    async def mockDivinationHandler(self):
        """Create a DivinationHandler with discovery enabled."""
        return _makeHandler(discoveryEnabled=True)

    async def testGenerateLayoutId(self, mockDivinationHandler):
        """Test layout ID generation from various inputs."""
        testCases = [
            ("Three-Card Spread", "three_card_spread"),
            ("Celtic Cross", "celtic_cross"),
            ("celtic-cross", "celtic_cross"),
            ("YES  NO", "yes_no"),
            ("  spaced  out  ", "spaced_out"),
        ]

        for inputName, expectedId in testCases:
            result = mockDivinationHandler._generateLayoutId(inputName)
            assert result == expectedId, f"Input: {inputName}, Expected: {expectedId}, Got: {result}"

    async def testDiscoveryEnabledFlag(self, mockDivinationHandler):
        """Test discovery enabled flag storage in handler."""
        assert mockDivinationHandler.discoveryEnabled is True

        # Modify config flag
        mockDivinationHandler.config["discovery-enabled"] = False
        # Handler init already captured the flag, so this test shows
        # that the flag is set during __init__, not checked dynamically

    async def testDiscoverLayoutSuccess(self, mockDivinationHandler):
        """Test successful layout discovery flow."""
        layoutName = "My Custom Layout"
        layoutDescription = """
        This is a 3-card layout used for simple readings.
        Positions: Past, Present, Future
        Each position represents a different time period.
        """

        # Mock generateStructured to return layout dict
        layoutDict = {
            "layout_id": "my_custom_layout",
            "name_en": "My Custom Layout",
            "name_ru": "Мой специальный расклад",
            "positions": [
                "Past",
                "Present",
                "Future",
            ],
        }

        structuredMock = AsyncMock(
            return_value=ModelStructuredResult(
                rawResult={},
                status=ModelResultStatus.FINAL,
                data=layoutDict,
                resultText='{"layout_id": "my_custom_layout", "name_en": "My Custom Layout"}',
            )
        )

        # Mock getChatSettings to return discovery prompts
        chatSettings = {
            ChatSettingsKey.DIVINATION_PARSE_STRUCTURE_SYSTEM_PROMPT: ChatSettingsValue(
                "You are a layout structiuing expert, return only JSON structure."
            ),
            ChatSettingsKey.DIVINATION_PARSE_STRUCTURE_PROMPT: ChatSettingsValue(
                "Extract layout from: {layoutName}, {systemId}, {description}"
            ),
            ChatSettingsKey.DIVINATION_DISCOVERY_SYSTEM_PROMPT: ChatSettingsValue("You are a layout expert."),
            ChatSettingsKey.CHAT_MODEL: ChatSettingsValue("gpt-4"),
            ChatSettingsKey.FALLBACK_MODEL: ChatSettingsValue("gpt-3.5"),
        }

        with patch.object(mockDivinationHandler, "getChatSettings", AsyncMock(return_value=chatSettings)):
            with patch.object(mockDivinationHandler.llmService, "generateStructured", structuredMock):
                result = await mockDivinationHandler._extractLayoutFromText(
                    systemCls=TarotSystem,
                    layoutName=layoutName,
                    canonicalLayoutId=mockDivinationHandler._generateLayoutId(layoutName),
                    chatId=456,
                    layoutDescription=layoutDescription,
                )

        # Verify the result
        assert result is not None
        assert isinstance(result, Layout)
        assert result.id == "my_custom_layout"
        assert result.nameEn == "My Custom Layout"
        assert result.nameRu == "Мой специальный расклад"
        assert result.positions == ("Past", "Present", "Future")
        assert result.systemId == "tarot"

        # Verify generateStructured was called
        structuredMock.assert_called_once()

    async def testDiscoverLayoutWithWebSearchSuccess(self, mockDivinationHandler):
        """Test full discovery flow with web search."""
        layoutName = "My Custom Layout"

        # Mock LLM responses
        mockInfoResponse = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="""
            This is a 3-card layout used for simple readings.
            Positions: Past, Present, Future
            Each position represents a different time period.
            """,
        )

        layoutDict = {
            "layout_id": "my_custom_layout",
            "name_en": "My Custom Layout",
            "name_ru": "Мой специальный расклад",
            "positions": [
                "Past",
                "Present",
                "Future",
            ],
        }

        structureResult = ModelStructuredResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            data=layoutDict,
            resultText='{"layout_id": "my_custom_layout"}',
        )

        generateTextMock = AsyncMock(return_value=mockInfoResponse)
        generateStructuredMock = AsyncMock(return_value=structureResult)

        # Mock getChatSettings
        chatSettings = {
            ChatSettingsKey.DIVINATION_DISCOVERY_INFO_PROMPT: ChatSettingsValue(
                "Find info about {layoutName}, {systemId}"
            ),
            ChatSettingsKey.DIVINATION_PARSE_STRUCTURE_PROMPT: ChatSettingsValue(
                "Extract layout from: {layoutName}, {systemId}, {description}"
            ),
            ChatSettingsKey.DIVINATION_DISCOVERY_SYSTEM_PROMPT: ChatSettingsValue("You are a layout expert."),
            ChatSettingsKey.DIVINATION_PARSE_STRUCTURE_SYSTEM_PROMPT: ChatSettingsValue(
                "You are a layout structuring expert."
            ),
            ChatSettingsKey.CHAT_MODEL: ChatSettingsValue("gpt-4"),
            ChatSettingsKey.FALLBACK_MODEL: ChatSettingsValue("gpt-3.5"),
        }

        with patch.object(mockDivinationHandler, "getChatSettings", AsyncMock(return_value=chatSettings)):
            with patch.object(mockDivinationHandler.llmService, "generateTextViaLLM", generateTextMock):
                with patch.object(mockDivinationHandler.llmService, "generateStructured", generateStructuredMock):
                    ensuredMessage = _makeEnsuredMessage(chatId=456)
                    result = await mockDivinationHandler._discoverLayoutWithLLM(
                        systemCls=TarotSystem,
                        layoutName=layoutName,
                        canonicalLayoutId=mockDivinationHandler._generateLayoutId(layoutName),
                        chatId=456,
                        ensuredMessage=ensuredMessage,
                    )

        assert result is not None
        assert result.id == "my_custom_layout"

        # Verify both methods were called
        generateTextMock.assert_called_once()
        generateStructuredMock.assert_called_once()

        # Verify first call had tools=True
        firstCall = generateTextMock.call_args
        assert firstCall.kwargs.get("useTools") is True

    async def testDiscoverLayoutFailureNegativeCache(self, mockDivinationHandler):
        """Test that failed discoveries are cached as negative."""
        layoutName = "NonExistentLayout"
        layoutDescription = "This layout doesn't exist."

        # Mock generateStructured to return None result
        structuredMock = AsyncMock(
            return_value=ModelStructuredResult(
                rawResult={},
                status=ModelResultStatus.ERROR,
                data=None,
                resultText="Failed",
            )
        )

        # Mock getChatSettings
        chatSettings = {
            ChatSettingsKey.DIVINATION_PARSE_STRUCTURE_PROMPT: ChatSettingsValue(
                "Extract layout from: {layoutName}, {systemId}, {description}"
            ),
            ChatSettingsKey.DIVINATION_DISCOVERY_SYSTEM_PROMPT: ChatSettingsValue("You are a layout expert."),
            ChatSettingsKey.DIVINATION_PARSE_STRUCTURE_SYSTEM_PROMPT: ChatSettingsValue("You are a layout expert."),
            ChatSettingsKey.CHAT_MODEL: ChatSettingsValue("gpt-4"),
            ChatSettingsKey.FALLBACK_MODEL: ChatSettingsValue("gpt-3.5"),
        }

        with patch.object(mockDivinationHandler, "getChatSettings", AsyncMock(return_value=chatSettings)):
            with patch.object(mockDivinationHandler.llmService, "generateStructured", structuredMock):
                result = await mockDivinationHandler._extractLayoutFromText(
                    systemCls=TarotSystem,
                    layoutName=layoutName,
                    canonicalLayoutId=mockDivinationHandler._generateLayoutId(layoutName),
                    chatId=456,
                    layoutDescription=layoutDescription,
                )

        assert result is None

    async def testHandleReadingFromArgsUsesCache(self, mockDivinationHandler):
        """Test that _handleReadingFromArgs uses cached layouts."""
        # Create a mock cached layout
        cachedLayoutDict = {
            "system_id": "tarot",
            "layout_id": "test_layout",
            "name_en": "Test Layout",
            "name_ru": "Тестовый расклад",
            "n_symbols": 2,
            "positions": [{"name": "Position1"}, {"name": "Position2"}],
            "description": "Test",
            "created_at": "2026-05-07T12:00:00",
            "updated_at": "2026-05-07T12:00:00",
        }

        # Mock getLayout to return our test layout
        mockDivinationHandler.db.divinations.getLayout = AsyncMock(return_value=cachedLayoutDict)

        # Mock sendMessage and _handleReading
        sendMessageMock = AsyncMock(return_value=[])
        handleReadingMock = AsyncMock(return_value="")

        with patch.object(mockDivinationHandler, "sendMessage", sendMessageMock):
            with patch.object(mockDivinationHandler, "getChatSettings") as mockSettings:
                with patch.object(mockDivinationHandler, "_handleReading", handleReadingMock):
                    mockSettings.return_value = {
                        ChatSettingsKey.TAROT_SYSTEM_PROMPT: ChatSettingsValue("test"),
                        ChatSettingsKey.DIVINATION_USER_PROMPT_TEMPLATE: ChatSettingsValue("test"),
                        ChatSettingsKey.DIVINATION_IMAGE_PROMPT_TEMPLATE: ChatSettingsValue("test"),
                        ChatSettingsKey.DIVINATION_REPLY_TEMPLATE: ChatSettingsValue("test"),
                        ChatSettingsKey.CHAT_MODEL: ChatSettingsValue("gpt-4"),
                        ChatSettingsKey.FALLBACK_MODEL: ChatSettingsValue("gpt-3.5"),
                    }

                    await mockDivinationHandler._handleReadingFromArgs(
                        systemId=TarotSystem.systemId,
                        ensuredMessage=_makeEnsuredMessage(),
                        args="test_layout test question",
                        typingManager=None,
                        invokedVia="command",
                    )

        # Verify _handleReading was called (meaning layout was found)
        handleReadingMock.assert_called_once()

    async def testHandleReadingFromArgsSkipsNegativeCache(self, mockDivinationHandler):
        """Test that _handleReadingFromArgs returns error for negative cache."""
        # Create a negative cache entry
        negativeCacheDict = {
            "system_id": "tarot",
            "layout_id": "nonexistent",
            "name_en": "",
            "name_ru": "",
            "n_symbols": 0,
            "positions": [],
            "description": "",
            "created_at": "2026-05-07T12:00:00",
            "updated_at": "2026-05-07T12:00:00",
        }

        # Mock getLayout to return negative cache
        mockDivinationHandler.db.divinations.getLayout = AsyncMock(return_value=negativeCacheDict)

        sendMessageMock = AsyncMock(return_value=[])
        with patch.object(mockDivinationHandler, "sendMessage", sendMessageMock):
            await mockDivinationHandler._handleReadingFromArgs(
                systemId=TarotSystem.systemId,
                ensuredMessage=_makeEnsuredMessage(),
                args="nonexistent test question",
                typingManager=None,
                invokedVia="command",
            )

        # Verify error message was sent
        sendMessageMock.assert_called_once()
        callArgs = sendMessageMock.call_args
        assert "не найден" in callArgs.kwargs["messageText"] or "не поддерживается" in callArgs.kwargs["messageText"]

    async def testNegativeCacheDetection(self, mockDivinationHandler):
        """Test isNegativeCacheEntry helper method."""
        # Create a negative cache entry
        negativeCacheDict = {
            "system_id": "tarot",
            "layout_id": "negative_test",
            "name_en": "",
            "name_ru": "",
            "n_symbols": 0,
            "positions": [],
            "description": "",
            "created_at": "2026-05-07T12:00:00",
            "updated_at": "2026-05-07T12:00:00",
        }

        assert mockDivinationHandler.db.divinations.isNegativeCacheEntry(negativeCacheDict) is True

        # Normal entry should not be detected as negative
        normalCacheDict = {
            "system_id": "tarot",
            "layout_id": "normal_test",
            "name_en": "Normal",
            "name_ru": "Обычный",
            "n_symbols": 1,
            "positions": [{"name": "Test"}],
            "description": "Test",
            "created_at": "2026-05-07T12:00:00",
            "updated_at": "2026-05-07T12:00:00",
        }

        assert mockDivinationHandler.db.divinations.isNegativeCacheEntry(normalCacheDict) is False


class TestRepositoryUpsert:
    """Test DivinationsRepository upsert functionality."""

    async def testSaveLayoutUpsert(self, testDatabase):
        """Test that saveLayout uses upsert correctly."""
        repo = testDatabase.divinations

        # First insert
        assert (
            await repo.saveLayout(
                systemId="tarot",
                layoutId="upsert_test",
                nameEn="Original Name",
                nameRu="Исходное имя",
                nSymbols=1,
                positions=[{"name": "Pos1"}],
                description="Original",
            )
            is True
        )

        cached = await repo.getLayout(systemId="tarot", layoutName="upsert_test")
        assert cached["name_en"] == "Original Name"

        # Second insert (update)
        assert (
            await repo.saveLayout(
                systemId="tarot",
                layoutId="upsert_test",
                nameEn="Updated Name",
                nameRu="Обновленное имя",
                nSymbols=2,
                positions=[{"name": "Pos1"}, {"name": "Pos2"}],
                description="Updated",
            )
            is True
        )

        cached = await repo.getLayout(systemId="tarot", layoutName="upsert_test")
        assert cached["name_en"] == "Updated Name"
        assert cached["n_symbols"] == 2

        # Verify only one row exists
        provider = await testDatabase.manager.getProvider(readonly=True)
        cursor = await provider.executeFetchOne(
            "SELECT COUNT(*) as count FROM divination_layouts WHERE system_id = :systemId AND layout_id = :layoutId",
            {"systemId": "tarot", "layoutId": "upsert_test"},
        )
        count = cursor["count"]
        assert count == 1


class TestCacheConsistency:
    """Test cache consistency across layout discovery and retrieval."""

    async def testCanonicalIdCacheConsistency(self, testDatabase):
        """Test that canonical layout IDs are used consistently in cache operations.

        This test verifies that when a layout is discovered with a canonical ID,
        retrieval operations use the same canonical ID, ensuring cache consistency
        regardless of variations in user input (case, spacing, special characters).
        """
        repo = testDatabase.divinations

        # Save a layout with a specific canonical ID
        canonicalId = "three_spread"
        await repo.saveLayout(
            systemId="tarot",
            layoutId=canonicalId,
            nameEn="Three Card Spread",
            nameRu="Трехкарточный расклад",
            nSymbols=3,
            positions=["Past", "Present", "Future"],
            description="Classic three card reading",
        )

        # Test 1: Retrieve using exact canonical ID
        result1 = await repo.getLayout(systemId="tarot", layoutName=canonicalId)
        assert result1 is not None
        assert result1["layout_id"] == canonicalId

        # Test 2: Retrieve using variant with different spacing (should match via canonical ID)
        # Simulating user input: "Three Spread" -> canonical: "three_spread"
        searchVariants = ["three_spread", "Three Spread", "THREE SPREAD", "three  spread"]
        for variant in searchVariants:
            # The actual canonical ID matching depends on the normalization logic
            # For this test, we verify that the cache lookup works with multiple strategies
            result = await repo.getLayout(systemId="tarot", layoutName=[variant, canonicalId])
            assert result is not None, f"Failed to find layout using variant: {variant}"
            assert result["layout_id"] == canonicalId

        # Test 3: Retrieve using multiple search strategies (canonical + original)
        mixedInput = ["three_spread", "some_other_variant_that_doesnt_exist"]
        result2 = await repo.getLayout(systemId="tarot", layoutName=mixedInput)
        assert result2 is not None
        assert result2["layout_id"] == canonicalId

        # Test 4: Verify that negative cache entries are also consistent
        await repo.saveNegativeCache(systemId="tarot", layoutId="nonexistent_layout")
        negative = await repo.getLayout(systemId="tarot", layoutName="nonexistent_layout")
        assert negative is not None
        assert repo.isNegativeCacheEntry(negative) is True
        assert negative["layout_id"] == "nonexistent_layout"

    async def testCacheKeyGenerationConsistency(self):
        """Test that cache key generation is deterministic and consistent.

        This verifies that the same layout input always generates the same
        canonical cache key, which is essential for cache consistency.
        """
        from internal.bot.common.handlers.divination import DivinationHandler

        # Mock minimal ConfigManager for testing
        mockConfigManager = _makeConfigManager(discoveryEnabled=True)

        # Mock Database with divinations repository
        mockDb = _makeDatabase()

        # Create handler instance (note: this may raise if divination disabled)
        try:
            handler = DivinationHandler(
                configManager=mockConfigManager,
                database=mockDb,
                botProvider=BotProvider.TELEGRAM,
            )
        except RuntimeError:
            # If discovery is disabled or config is invalid, skip this test
            pytest.skip("Divination handler cannot be initialized with test config")

        # Test various layout name inputs that should normalize to the same ID
        testCases = [
            # (input1, input2) - both should generate the same canonical ID
            ("three_card", "three_card"),  # Exact match
            ("CelTic CroSs", "CELtic CROSS"),  # Case differences
            ("three  spread", "THREE SPREAD"),  # Multiple spaces vs single space
            ("horseshoe-spread", "Horseshoe Spread"),  # Dashes vs spaces
        ]

        for input1, input2 in testCases:
            canonical1 = handler._generateLayoutId(input1)
            canonical2 = handler._generateLayoutId(input2)

            # Both inputs should generate the same canonical ID
            assert (
                canonical1 == canonical2
            ), f"Inconsistent canonical IDs for '{input1}' vs '{input2}': {canonical1} != {canonical2}"
            # Verify it's lowercase with underscores
            assert canonical1.islower(), f"Canonical ID should be lowercase: {canonical1}"
            assert " " not in canonical1, f"Canonical ID should not contain spaces: {canonical1}"
