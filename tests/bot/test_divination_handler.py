"""Tests for :class:`DivinationHandler`, dood!

These tests exercise the divination handler in isolation by:

* Constructing a real :class:`DivinationHandler` (with the singleton
  ``LLMService`` reset by the autouse fixture in ``tests/conftest.py``).
* Stubbing ``self.getChatSettings``, ``self.sendMessage``,
  ``self.llmService.generateText`` / ``generateImage`` /
  ``rateLimit`` and the database repositories with ``AsyncMock`` /
  ``Mock`` so the test never touches a real bot, LLM provider, or
  database.
* Calling the handler's underlying methods directly (the
  ``@commandHandlerV2`` decorator stores metadata on the function but
  returns it unchanged, so direct invocation is supported).

No real LLM calls. No real database calls. No filesystem.
"""

import datetime as dt
import json
from typing import Any, Dict, Optional, Tuple, cast
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from internal.bot.common.handlers.divination import (
    DivinationHandler,
)
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
)
from internal.services.llm.service import LLMService
from lib.ai import ModelResultStatus
from lib.ai.models import ModelRunResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# A handful of typed aliases keep pyright (basic mode) quiet around mock
# attribute access without sprinkling ``# type: ignore`` everywhere, dood!
HandlerMocks = Dict[str, Any]


def _makeChatSettings() -> Dict[ChatSettingsKey, ChatSettingsValue]:
    """Build a chat-settings dict pre-populated with all keys the handler reads.

    Returns:
        Mapping of every relevant :class:`ChatSettingsKey` to a
        :class:`ChatSettingsValue` carrying a deterministic test value.
    """
    return {
        ChatSettingsKey.TAROT_SYSTEM_PROMPT: ChatSettingsValue("TAROT-SYS"),
        ChatSettingsKey.RUNES_SYSTEM_PROMPT: ChatSettingsValue("RUNES-SYS"),
        ChatSettingsKey.DIVINATION_USER_PROMPT_TEMPLATE: ChatSettingsValue(
            "User: {userName}\nQ: {question}\nLayout: {layoutName}\n"
            "Positions:\n{positionsBlock}\nCards:\n{cardsBlock}"
        ),
        ChatSettingsKey.DIVINATION_IMAGE_PROMPT_TEMPLATE: ChatSettingsValue(
            "Render {layoutName}: {spreadDescription}. {styleHint}"
        ),
        ChatSettingsKey.FALLBACK_HAPPENED_PREFIX: ChatSettingsValue("[fallback] "),
        ChatSettingsKey.LLM_RATELIMITER: ChatSettingsValue(""),
        ChatSettingsKey.CHAT_MODEL: ChatSettingsValue(""),
        ChatSettingsKey.FALLBACK_MODEL: ChatSettingsValue(""),
    }


def _makeEnsuredMessage(
    *,
    chatId: int = 100,
    messageId: int = 42,
    userId: int = 7,
    senderName: str = "Alice",
) -> EnsuredMessage:
    """Build a minimal :class:`EnsuredMessage` suitable for handler tests.

    Args:
        chatId: Recipient chat id.
        messageId: Originating message id (Telegram-flavoured int).
        userId: Sender user id.
        senderName: ``MessageSender.name`` value, used by the ``{userName}``
            template placeholder.

    Returns:
        Fully constructed :class:`EnsuredMessage`.
    """
    return EnsuredMessage(
        sender=MessageSender(id=userId, name=senderName, username=f"@user{userId}"),
        recipient=MessageRecipient(id=chatId, chatType=ChatType.PRIVATE),
        messageId=messageId,
        date=dt.datetime(2026, 5, 5, 12, 0, 0, tzinfo=dt.timezone.utc),
        messageText="",
    )


def _makeConfigManager(
    *,
    enabled: bool = True,
    tarotEnabled: bool = True,
    runesEnabled: bool = True,
    imageGeneration: bool = True,
    toolsEnabled: bool = True,
) -> Mock:
    """Build a stand-in ``ConfigManager`` returning the divination section.

    Args:
        enabled: Value for ``divination.enabled``.
        tarotEnabled: Value for ``divination.tarot-enabled``.
        runesEnabled: Value for ``divination.runes-enabled``.
        imageGeneration: Value for ``divination.image-generation``.
        toolsEnabled: Value for ``divination.tools-enabled``.

    Returns:
        ``Mock`` exposing ``.get(...)`` and ``.getBotConfig()`` that the
        :class:`BaseBotHandler` constructor needs.
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
            }
            if key == "divination"
            else (default if default is not None else {})
        )
    )
    return cm


def _makeDatabase() -> Mock:
    """Build a ``Database`` stub with a ``divinations`` repository.

    Returns:
        Mock exposing the divinations repository the handler writes to.
        ``insertReading`` returns ``True`` by default.
    """
    db = Mock()
    db.divinations = Mock()
    db.divinations.insertReading = AsyncMock(return_value=True)
    return db


def _makeHandler(
    *,
    configManager: Optional[Mock] = None,
    chatSettings: Optional[Dict[ChatSettingsKey, ChatSettingsValue]] = None,
) -> Tuple[DivinationHandler, HandlerMocks]:
    """Construct a :class:`DivinationHandler` with stubs ready for tests.

    The handler's ``llmService`` is replaced wholesale with a Mock that
    has ``rateLimit``, ``generateText``, ``generateImage`` and
    ``registerTool`` configured. ``getChatSettings`` and ``sendMessage``
    are stubbed at the instance level to avoid touching the cache or bot.

    Args:
        configManager: Optional preconfigured config-manager stub.
        chatSettings: Optional override for the chat-settings dict
            returned by ``getChatSettings``. Defaults to
            :func:`_makeChatSettings`.

    Returns:
        Tuple ``(handler, mocks)`` where ``mocks`` is a dict of the
        injected mocks for direct, type-permissive access from tests.
    """
    cm = configManager if configManager is not None else _makeConfigManager()
    db = _makeDatabase()
    llmManager = MagicMock()
    handler = DivinationHandler(
        configManager=cm,
        database=db,
        llmManager=llmManager,
        botProvider=BotProvider.TELEGRAM,
    )

    # Replace the singleton LLMService methods we exercise.
    rateLimitMock = AsyncMock(return_value=None)
    generateTextMock = AsyncMock(
        return_value=ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="Mock interpretation of the spread, dood!",
        )
    )
    generateImageMock = AsyncMock(
        return_value=ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="",
            mediaMimeType="image/png",
            mediaData=b"PNGDATA",
        )
    )
    fakeLlmService = MagicMock()
    fakeLlmService.rateLimit = rateLimitMock
    fakeLlmService.generateText = generateTextMock
    fakeLlmService.generateImage = generateImageMock
    handler.llmService = fakeLlmService

    # Stub chat-settings retrieval and message sending.
    cs = chatSettings if chatSettings is not None else _makeChatSettings()
    getChatSettingsMock = AsyncMock(return_value=cs)
    cast(Any, handler).getChatSettings = getChatSettingsMock

    sendMessageMock = AsyncMock(return_value=[])
    cast(Any, handler).sendMessage = sendMessageMock

    mocks: HandlerMocks = {
        "rateLimit": rateLimitMock,
        "generateText": generateTextMock,
        "generateImage": generateImageMock,
        "getChatSettings": getChatSettingsMock,
        "sendMessage": sendMessageMock,
        "insertReading": db.divinations.insertReading,
        "db": db,
    }
    return handler, mocks


def _callTaro(handler: DivinationHandler, ensuredMessage: EnsuredMessage, args: str) -> Any:
    """Invoke the ``taroCommand`` past pyright's unbound-signature view.

    ``commandHandlerV2`` returns the wrapped function unchanged, so calling
    the bound method through ``cast(Any, ...)`` is safe.

    Args:
        handler: Handler under test.
        ensuredMessage: Originating user message.
        args: Raw arguments string.

    Returns:
        Whatever the underlying coroutine returns (always ``None`` here).
    """
    return cast(Any, handler).taroCommand(
        ensuredMessage,
        "taro",
        args,
        updateObj=Mock(),
        typingManager=None,
    )


def _callRunes(handler: DivinationHandler, ensuredMessage: EnsuredMessage, args: str) -> Any:
    """Invoke ``runesCommand`` past pyright's unbound-signature view.

    Args:
        handler: Handler under test.
        ensuredMessage: Originating user message.
        args: Raw arguments string.

    Returns:
        Whatever the underlying coroutine returns (always ``None`` here).
    """
    return cast(Any, handler).runesCommand(
        ensuredMessage,
        "runes",
        args,
        updateObj=Mock(),
        typingManager=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_taroCommandSuccess() -> None:
    """``/taro three_card что меня ждёт`` triggers a full reading + image.

    Verifies that the handler:
        * calls ``generateText`` exactly once with two messages (system + user);
        * generates an image (config flag is True by default);
        * inserts a ``divinations`` row with no ``mediaId`` / ``rngSeed``;
        * sends exactly one ``sendMessage`` carrying the photo bytes and
          the full interpretation text as caption (no truncation).
    """
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    await _callTaro(handler, em, "three_card что меня ждёт")

    assert mocks["generateText"].call_count == 1
    callArgs = mocks["generateText"].call_args
    assert callArgs.kwargs["modelKey"] == ChatSettingsKey.CHAT_MODEL
    assert callArgs.kwargs["fallbackKey"] == ChatSettingsKey.FALLBACK_MODEL
    sentMessages = callArgs.args[0]
    assert len(sentMessages) == 2
    assert sentMessages[0].role == "system"
    assert sentMessages[1].role == "user"
    # The username placeholder should have been substituted with ensuredMessage.sender.name.
    assert "Alice" in sentMessages[1].content
    # The user question must be present.
    assert "что меня ждёт" in sentMessages[1].content

    # Image step must have run.
    assert mocks["generateImage"].call_count == 1

    # Reply: photo + full caption (no truncation).
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert sendKwargs.get("photoData") == b"PNGDATA"
    assert sendKwargs.get("messageText") == "Mock interpretation of the spread, dood!"
    # mediaPrompt must be passed through to sendMessage (Change 7).
    assert sendKwargs.get("mediaPrompt") is not None
    assert sendKwargs["mediaPrompt"] != ""

    # DB row must be persisted without mediaId / rngSeed.
    mocks["insertReading"].assert_awaited_once()
    insertKwargs = mocks["insertReading"].call_args.kwargs
    assert insertKwargs["systemId"] == "tarot"
    assert insertKwargs["deckId"] == "rws"
    assert insertKwargs["layoutId"] == "three_card"
    assert insertKwargs["question"] == "что меня ждёт"
    assert insertKwargs["invokedVia"] == "command"
    assert "mediaId" not in insertKwargs
    assert "rngSeed" not in insertKwargs
    drawsList = json.loads(insertKwargs["drawsJson"])
    assert len(drawsList) == 3


async def test_runesCommandNoImage() -> None:
    """``/runes nine_runes`` without question and ``image-generation=False``.

    Image generation must be skipped entirely; the reply must be a plain
    text message and the DB row must be persisted without image fields.
    """
    cm = _makeConfigManager(imageGeneration=False)
    handler, mocks = _makeHandler(configManager=cm)
    em = _makeEnsuredMessage(chatId=200, messageId=99, userId=8, senderName="Bob")

    await _callRunes(handler, em, "nine_runes")

    assert mocks["generateText"].call_count == 1
    assert mocks["generateImage"].call_count == 0

    # Reply: text-only.
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert sendKwargs.get("photoData") is None
    assert sendKwargs["messageText"] == "Mock interpretation of the spread, dood!"

    # DB row persisted; no mediaId or rngSeed keys.
    mocks["insertReading"].assert_awaited_once()
    insertKwargs = mocks["insertReading"].call_args.kwargs
    assert insertKwargs["systemId"] == "runes"
    assert insertKwargs["layoutId"] == "nine_runes"
    assert "mediaId" not in insertKwargs
    assert "rngSeed" not in insertKwargs
    assert insertKwargs["imagePrompt"] is None
    assert insertKwargs["question"] == ""
    drawsList = json.loads(insertKwargs["drawsJson"])
    assert len(drawsList) == 9
    # Runes never have reversed=True.
    assert all(entry["reversed"] is False for entry in drawsList)


async def test_taroCommandUnknownLayout() -> None:
    """An unknown layout must fail fast with an error reply."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    await _callTaro(handler, em, "nonexistent question")

    mocks["generateText"].assert_not_called()
    mocks["generateImage"].assert_not_called()
    mocks["insertReading"].assert_not_awaited()

    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "nonexistent" in sendKwargs["messageText"]
    assert "Доступные расклады" in sendKwargs["messageText"]


async def test_taroCommandMissingLayout() -> None:
    """Empty args must produce a help reply listing available layouts."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    await _callTaro(handler, em, "")

    mocks["generateText"].assert_not_called()
    mocks["insertReading"].assert_not_awaited()

    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert "расклад" in sendKwargs["messageText"].lower()
    assert "three_card" in sendKwargs["messageText"]


async def test_dbInsertFailureDoesNotBlockReply() -> None:
    """DB persistence failure must be swallowed; user reply is still sent."""
    handler, mocks = _makeHandler()
    failingInsert = AsyncMock(side_effect=RuntimeError("db down, dood!"))
    handler.db.divinations.insertReading = failingInsert
    mocks["insertReading"] = failingInsert
    em = _makeEnsuredMessage()

    # Should NOT raise.
    await _callTaro(handler, em, "one_card hello?")

    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    # User still gets the interpretation (with image).
    assert sendKwargs.get("photoData") == b"PNGDATA"
    failingInsert.assert_awaited_once()


async def test_llmToolRegistrationGated() -> None:
    """``tools-enabled`` controls registration of both LLM tools."""
    # tools-enabled = True → both tools registered on the singleton.
    LLMService._instance = None  # reset just in case
    cmOn = _makeConfigManager(toolsEnabled=True)
    handlerOn, _mocksOn = _makeHandler(configManager=cmOn)
    assert handlerOn is not None
    registeredOnReal = set(LLMService.getInstance().toolsHandlers.keys())
    assert "do_tarot_reading" in registeredOnReal
    assert "do_runes_reading" in registeredOnReal

    # tools-enabled = False → neither tool registered.
    LLMService._instance = None
    cmOff = _makeConfigManager(toolsEnabled=False)
    handlerOff, _mocksOff = _makeHandler(configManager=cmOff)
    assert handlerOff is not None
    registeredOff = set(LLMService.getInstance().toolsHandlers.keys())
    assert "do_tarot_reading" not in registeredOff
    assert "do_runes_reading" not in registeredOff


async def test_imageGenerationFailureFallsBackToText() -> None:
    """When ``generateImage`` returns a non-FINAL status, reply is text-only."""
    handler, mocks = _makeHandler()
    failingImage = AsyncMock(
        return_value=ModelRunResult(
            rawResult={},
            status=ModelResultStatus.ERROR,
            resultText="oops",
            mediaData=None,
        )
    )
    handler.llmService.generateImage = failingImage
    mocks["generateImage"] = failingImage
    em = _makeEnsuredMessage()

    await _callTaro(handler, em, "three_card test")

    assert failingImage.call_count == 1

    # Reply: plain text, no photo.
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert sendKwargs.get("photoData") is None
    assert sendKwargs["messageText"] == "Mock interpretation of the spread, dood!"

    # DB row written without image fields.
    insertKwargs = mocks["insertReading"].call_args.kwargs
    assert "mediaId" not in insertKwargs
    assert "rngSeed" not in insertKwargs
    assert insertKwargs["imagePrompt"] is None


async def test_handlerDisabledRaisesAtInit() -> None:
    """Constructing the handler with ``divination.enabled = False`` raises."""
    cm = _makeConfigManager(enabled=False)
    db = _makeDatabase()
    with pytest.raises(RuntimeError):
        DivinationHandler(
            configManager=cm,
            database=db,
            llmManager=MagicMock(),
            botProvider=BotProvider.TELEGRAM,
        )


async def test_noTruncation_fullInterpretationPassedToSendMessage() -> None:
    """Full interpretation text is passed directly; ``sendMessage`` handles overflow.

    Previously the handler truncated long text to CAPTION_LIMIT and sent a
    follow-up message. That behavior is gone: one photo+caption call with
    the complete text is made regardless of length, dood!
    """
    handler, mocks = _makeHandler()
    longText = "y" * 2000
    longTextResp = AsyncMock(
        return_value=ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText=longText,
        )
    )
    handler.llmService.generateText = longTextResp
    mocks["generateText"] = longTextResp
    em = _makeEnsuredMessage()

    await _callTaro(handler, em, "one_card")

    # Exactly ONE sendMessage call (no follow-up).
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert sendKwargs.get("photoData") == b"PNGDATA"
    # Full text — no slicing.
    assert sendKwargs["messageText"] == longText


async def test_llmToolFallsBackToDefaultLayout() -> None:
    """Tool path: empty layout → ``three_card`` for tarot."""
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()
    fakeTyping = MagicMock(spec=TypingManager)
    fakeTyping.action = None
    fakeTyping.maxTimeout = 60
    fakeTyping.sendTypingAction = AsyncMock(return_value=None)

    result = await cast(Any, handler)._llmToolDoTarotReading(
        extraData={"ensuredMessage": em, "typingManager": fakeTyping},
        question="как дела?",
        layout=None,
        generate_image=False,
    )

    parsed = json.loads(result)
    assert parsed["done"] is True
    insertKwargs = mocks["insertReading"].call_args.kwargs
    assert insertKwargs["layoutId"] == "three_card"
    assert insertKwargs["invokedVia"] == "llm_tool"
    # generate_image=False on tool path → no image regardless of config.
    mocks["generateImage"].assert_not_called()


async def test_llmToolWithImageSendsPhotoButNotText() -> None:
    """LLM tool + image: photo sent (empty caption), text only in JSON result.

    When ``returnToolJson=True`` and image generation succeeds:
    - ``sendMessage`` is called exactly once with ``photoData`` set and
      ``messageText`` empty (the bot sends the picture; the LLM handles text).
    - The returned JSON contains ``interpretation`` and
      ``imageGenerated=True``.
    """
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()
    fakeTyping = MagicMock(spec=TypingManager)
    fakeTyping.action = None
    fakeTyping.maxTimeout = 60
    fakeTyping.sendTypingAction = AsyncMock(return_value=None)

    result = await cast(Any, handler)._llmToolDoTarotReading(
        extraData={"ensuredMessage": em, "typingManager": fakeTyping},
        question="что меня ждёт?",
        layout="three_card",
        generate_image=True,
    )

    parsed = json.loads(result)
    assert parsed["done"] is True
    assert parsed["imageGenerated"] is True
    assert parsed["interpretation"] == "Mock interpretation of the spread, dood!"
    assert "summary" in parsed  # backwards compat

    # sendMessage called once: photo only, no text.
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert sendKwargs.get("photoData") == b"PNGDATA"
    assert sendKwargs.get("messageText") == ""
    # mediaPrompt must still be forwarded (Change 7).
    assert sendKwargs.get("mediaPrompt") is not None
    assert sendKwargs["mediaPrompt"] != ""


async def test_llmToolWithoutImageSendsNothing() -> None:
    """LLM tool + no image: sendMessage NOT called; interpretation in JSON only.

    When ``returnToolJson=True`` and image is not generated:
    - ``sendMessage`` is never called.
    - The returned JSON contains ``interpretation`` and
      ``imageGenerated=False``.
    """
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()
    fakeTyping = MagicMock(spec=TypingManager)
    fakeTyping.action = None
    fakeTyping.maxTimeout = 60
    fakeTyping.sendTypingAction = AsyncMock(return_value=None)

    result = await cast(Any, handler)._llmToolDoTarotReading(
        extraData={"ensuredMessage": em, "typingManager": fakeTyping},
        question="что меня ждёт?",
        layout="three_card",
        generate_image=False,
    )

    parsed = json.loads(result)
    assert parsed["done"] is True
    assert parsed["imageGenerated"] is False
    assert parsed["interpretation"] == "Mock interpretation of the spread, dood!"
    assert "summary" in parsed  # backwards compat

    # No message sent to the user — interpretation lives only in JSON.
    mocks["sendMessage"].assert_not_called()


async def test_slashCommandPathSendsTextWithPhoto() -> None:
    """Slash-command path always sends text interpretation (with photo as caption).

    Ensures the slash-command flow is not affected by the LLM-tool
    suppression logic from Change 2.
    """
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    await _callTaro(handler, em, "three_card test question")

    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert sendKwargs.get("photoData") == b"PNGDATA"
    assert sendKwargs.get("messageText") == "Mock interpretation of the spread, dood!"
