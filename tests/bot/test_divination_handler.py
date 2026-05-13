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


def _makeChatSettings(
    *,
    replyTemplate: Optional[str] = None,
) -> Dict[ChatSettingsKey, ChatSettingsValue]:
    """Build a chat-settings dict pre-populated with all keys the handler reads.

    Args:
        replyTemplate: Optional override for the divination reply template.
            Defaults to a simple template with all three standard placeholders.

    Returns:
        Mapping of every relevant :class:`ChatSettingsKey` to a
        :class:`ChatSettingsValue` carrying a deterministic test value.
    """
    defaultReplyTemplate: str = (
        replyTemplate
        if replyTemplate is not None
        else "Расклад: {layoutName}\nСимволы:\n{drawnSymbolsBlock}\n\n{interpretation}"
    )
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
        ChatSettingsKey.DIVINATION_REPLY_TEMPLATE: ChatSettingsValue(defaultReplyTemplate),
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
    handler = DivinationHandler(
        configManager=cm,
        database=db,
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
        * sends exactly TWO ``sendMessage`` calls: first the photo alone (no
          caption / no ``messageText``), then the template-rendered text alone
          (no ``photoData``), dood!
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

    # Reply: two separate sendMessage calls — first photo-only, then text-only.
    assert mocks["sendMessage"].call_count == 2
    allCalls = mocks["sendMessage"].call_args_list

    # First call: photo alone, no messageText.
    firstKwargs = allCalls[0].kwargs
    assert firstKwargs.get("photoData") == b"PNGDATA"
    assert not firstKwargs.get("messageText")  # no caption on the photo call
    # mediaPrompt must be passed through to the photo sendMessage call.
    assert firstKwargs.get("mediaPrompt") is not None
    assert firstKwargs["mediaPrompt"] != ""

    # Second call: structured text, no photoData.
    secondKwargs = allCalls[1].kwargs
    assert secondKwargs.get("photoData") is None
    messageText: str = secondKwargs.get("messageText", "")
    # The reply template must contain all three components.
    assert "Расклад на три карты" in messageText  # layout Russian name
    assert "1." in messageText  # drawn-symbols block (numbered list)
    assert "Mock interpretation of the spread, dood!" in messageText  # LLM text

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
    # drawsJson is passed as a list directly to the repository.
    drawsList = insertKwargs["drawsJson"]
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

    # Reply: text-only, structured (layout name + symbols block + interpretation).
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert sendKwargs.get("photoData") is None
    runesMessageText: str = sendKwargs["messageText"]
    assert "Расклад на девять рун" in runesMessageText  # layout Russian name
    assert "1." in runesMessageText  # drawn-symbols block
    assert "Mock interpretation of the spread, dood!" in runesMessageText  # LLM text

    # DB row persisted; no mediaId or rngSeed keys.
    mocks["insertReading"].assert_awaited_once()
    insertKwargs = mocks["insertReading"].call_args.kwargs
    assert insertKwargs["systemId"] == "runes"
    assert insertKwargs["layoutId"] == "nine_runes"
    assert "mediaId" not in insertKwargs
    assert "rngSeed" not in insertKwargs
    assert insertKwargs["imagePrompt"] is None
    assert insertKwargs["question"] == ""
    # drawsJson is passed as a list directly to the repository.
    drawsList = insertKwargs["drawsJson"]
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

    # Two calls: photo first, then text (Change A — image and text are separate).
    assert mocks["sendMessage"].call_count == 2
    allCalls = mocks["sendMessage"].call_args_list
    # User still gets the photo in the first call.
    assert allCalls[0].kwargs.get("photoData") == b"PNGDATA"
    # And the text reply in the second call.
    assert allCalls[1].kwargs.get("messageText") is not None
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

    # Reply: plain text, no photo. Must contain all three template components.
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert sendKwargs.get("photoData") is None
    imgFailMessageText: str = sendKwargs["messageText"]
    assert "Расклад на три карты" in imgFailMessageText  # layout Russian name
    assert "1." in imgFailMessageText  # drawn-symbols block
    assert "Mock interpretation of the spread, dood!" in imgFailMessageText  # LLM text

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
            botProvider=BotProvider.TELEGRAM,
        )


async def test_noTruncation_fullInterpretationPassedToSendMessage() -> None:
    """Full interpretation text is embedded in template without truncation.

    The handler must embed the complete LLM text in the reply template
    without slicing. ``sendMessage`` handles any platform-level overflow.
    On the slash-command-with-image path exactly TWO ``sendMessage`` calls
    are made: first the photo alone, then the full-text reply, dood!
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

    # Two sendMessage calls: photo-only first, text-only second (Change A).
    assert mocks["sendMessage"].call_count == 2
    allCalls = mocks["sendMessage"].call_args_list

    # First call: photo with no messageText.
    assert allCalls[0].kwargs.get("photoData") == b"PNGDATA"
    assert not allCalls[0].kwargs.get("messageText")

    # Second call: text with no photoData; full LLM text must be present (no slicing).
    assert allCalls[1].kwargs.get("photoData") is None
    assert longText in allCalls[1].kwargs["messageText"]


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
    """LLM tool + image: photo sent (no caption), interpretation in JSON only.

    When ``returnToolJson=True`` and image generation succeeds:
    - ``sendMessage`` is called exactly once with ``photoData`` set and
      no ``messageText`` (the bot sends the picture; the LLM host handles
      any text reply using the JSON result).
    - The returned JSON contains ``done``, ``layout``, ``draws``, and
      ``interpretation``; it does NOT contain ``imageGenerated`` or
      ``summary`` (removed by the user intentionally), dood!
    - The photo-send uses ``MessageCategory.BOT`` (Change C).
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
    # imageGenerated and summary keys were deliberately removed (Change B).
    assert "imageGenerated" not in parsed
    assert "summary" not in parsed
    assert parsed["interpretation"] == "Mock interpretation of the spread, dood!"
    # Layout and draws are present in the new shape.
    assert "layout" in parsed
    assert "draws" in parsed

    # sendMessage called once: photo only, no messageText (Change A tool path).
    assert mocks["sendMessage"].call_count == 1
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    assert sendKwargs.get("photoData") == b"PNGDATA"
    assert not sendKwargs.get("messageText")  # no caption on the tool-path photo
    # mediaPrompt must still be forwarded.
    assert sendKwargs.get("mediaPrompt") is not None
    assert sendKwargs["mediaPrompt"] != ""
    # Tool-path photo uses MessageCategory.BOT (Change C).
    from internal.database.models import MessageCategory

    assert sendKwargs.get("messageCategory") == MessageCategory.BOT


async def test_llmToolWithoutImageSendsNothing() -> None:
    """LLM tool + no image: sendMessage NOT called; interpretation in JSON only.

    When ``returnToolJson=True`` and image is not generated:
    - ``sendMessage`` is never called.
    - The returned JSON contains ``done``, ``layout``, ``draws``, and
      ``interpretation``; it does NOT contain ``imageGenerated`` or
      ``summary`` (removed by the user intentionally), dood!
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
    # imageGenerated and summary keys were deliberately removed (Change B).
    assert "imageGenerated" not in parsed
    assert "summary" not in parsed
    assert parsed["interpretation"] == "Mock interpretation of the spread, dood!"
    # Layout and draws are present in the new shape.
    assert "layout" in parsed
    assert "draws" in parsed

    # No message sent to the user — interpretation lives only in JSON.
    mocks["sendMessage"].assert_not_called()


async def test_slashCommandPathSendsTextWithPhoto() -> None:
    """Slash-command path sends photo then structured template text as two separate messages.

    Ensures the slash-command flow uses the reply template (not bare LLM
    text) and is not affected by the LLM-tool suppression logic. The image
    and the template-rendered text are sent as two distinct ``sendMessage``
    calls: first photo-only, then text-only, dood!
    """
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    await _callTaro(handler, em, "three_card test question")

    # Two calls: photo-only first, text-only second (Change A).
    assert mocks["sendMessage"].call_count == 2
    allCalls = mocks["sendMessage"].call_args_list

    # First call: photo alone, no messageText.
    firstKwargs = allCalls[0].kwargs
    assert firstKwargs.get("photoData") == b"PNGDATA"
    assert not firstKwargs.get("messageText")

    # Second call: structured text, no photoData.
    secondKwargs = allCalls[1].kwargs
    assert secondKwargs.get("photoData") is None
    slashMsgText: str = secondKwargs.get("messageText", "")
    assert "Расклад на три карты" in slashMsgText
    assert "1." in slashMsgText
    assert "Mock interpretation of the spread, dood!" in slashMsgText


async def test_slashCommandUsesReplyTemplate() -> None:
    """Slash-command reply substitutes all three placeholders from the template.

    Patches the chat setting to a custom template and verifies the rendered
    result (not the raw LLM text) is delivered in the second ``sendMessage``
    call (the text-only one). The first call carries the photo alone, dood!
    """
    customTemplate: str = "LAYOUT={layoutName}|SYMBOLS={drawnSymbolsBlock}|INTERP={interpretation}"
    handler, mocks = _makeHandler(
        chatSettings=_makeChatSettings(replyTemplate=customTemplate),
    )
    em = _makeEnsuredMessage()

    await _callTaro(handler, em, "one_card")

    # Two calls: photo-only first, text-only second (Change A).
    assert mocks["sendMessage"].call_count == 2
    allCalls = mocks["sendMessage"].call_args_list

    # First call: photo alone, no messageText.
    assert allCalls[0].kwargs.get("photoData") == b"PNGDATA"
    assert not allCalls[0].kwargs.get("messageText")

    # Second call: rendered template text, no photoData.
    assert allCalls[1].kwargs.get("photoData") is None
    msgText: str = allCalls[1].kwargs.get("messageText", "")
    # All three placeholders must be filled.
    assert "LAYOUT=Одна карта" in msgText
    assert "SYMBOLS=" in msgText
    assert "1." in msgText  # drawn-symbols block is non-empty
    assert "INTERP=Mock interpretation of the spread, dood!" in msgText


async def test_toolPathJsonContainsBareInterpretation() -> None:
    """LLM-tool JSON result carries the raw LLM text, NOT the templated reply.

    The host LLM must receive the bare interpretation so it can incorporate
    it naturally into its own response — the template wrapper is for users
    only, not for the LLM, dood!
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
    # The interpretation field must be the bare LLM output — no template wrapper.
    assert parsed["interpretation"] == "Mock interpretation of the spread, dood!"
    # It must NOT contain any template decoration from the reply template.
    assert "Расклад:" not in parsed["interpretation"]
    assert "Выпавшие символы:" not in parsed["interpretation"]


# ---------------------------------------------------------------------------
# Regression tests: sendMessage call-count on the slash-command path
# ---------------------------------------------------------------------------


async def test_slashCommandSendsTwoMessages_withImage() -> None:
    """Slash-command path sends exactly TWO messages when image generation succeeds.

    The new behavior sends the image and the template-rendered text as two
    separate ``sendMessage`` calls (Change A):
    - First call: ``photoData`` set, no ``messageText`` (image alone).
    - Second call: ``messageText`` set with the full template-rendered reply,
      no ``photoData`` (text alone).

    Regression guard: any collapse back to a single call (photo+caption) or
    any reduction to zero/one call on this path is a bug, dood!

    Scenario: image generation enabled and returns bytes.
    """
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()

    await _callTaro(handler, em, "three_card что меня ждёт")

    # Exactly TWO calls: photo first, then text.
    assert mocks["sendMessage"].call_count == 2, (
        f"Expected sendMessage to be called exactly twice on the slash-command "
        f"path with image, but it was called {mocks['sendMessage'].call_count} time(s). "
        f"Calls: {mocks['sendMessage'].call_args_list}"
    )
    allCalls = mocks["sendMessage"].call_args_list

    # First call: photo only — no messageText, photoData present.
    firstKwargs = allCalls[0].kwargs
    assert (
        firstKwargs.get("photoData") == b"PNGDATA"
    ), "First sendMessage call must carry photoData (image-only message)."
    assert not firstKwargs.get(
        "messageText"
    ), "First sendMessage call must NOT carry messageText (image alone, no caption)."

    # Second call: text only — messageText present, no photoData.
    secondKwargs = allCalls[1].kwargs
    assert (
        secondKwargs.get("photoData") is None
    ), "Second sendMessage call must NOT carry photoData (text-only message)."
    msgText: str = secondKwargs.get("messageText", "")
    assert "Расклад на три карты" in msgText
    assert "Mock interpretation of the spread, dood!" in msgText


async def test_slashCommandSendsExactlyOneMessage_noImage() -> None:
    """Slash-command path sends exactly ONE message when image generation is disabled.

    Regression guard: ensures that text-only replies also produce a single
    ``sendMessage`` call. The buggy staged version additionally fired a
    second ``sendMessage`` unconditionally after the ``else`` branch, which
    would have sent a duplicate plain-text reply, dood!

    Scenario: image generation disabled in config.
    """
    cm = _makeConfigManager(imageGeneration=False)
    handler, mocks = _makeHandler(configManager=cm)
    em = _makeEnsuredMessage()

    await _callRunes(handler, em, "nine_runes без вопроса")

    # The ONLY acceptable call count is 1 — no duplicate bare-text message.
    assert mocks["sendMessage"].call_count == 1, (
        f"Expected sendMessage to be called exactly once on the slash-command "
        f"path without image, but it was called {mocks['sendMessage'].call_count} time(s). "
        f"Calls: {mocks['sendMessage'].call_args_list}"
    )
    sendKwargs = mocks["sendMessage"].call_args.kwargs
    # Text-only path: no photo.
    assert sendKwargs.get("photoData") is None, "Text-only sendMessage call must not carry photoData."
    # The single call must contain the structured reply text.
    noImgText: str = sendKwargs.get("messageText", "")
    assert "Расклад на девять рун" in noImgText
    assert "Mock interpretation of the spread, dood!" in noImgText


# ---------------------------------------------------------------------------
# Glyph field in tool-path JSON
# ---------------------------------------------------------------------------


async def test_toolPathJsonIncludesRuneGlyphs() -> None:
    """LLM-tool JSON for a runes reading must include non-empty ``glyph`` on every draw entry, dood!

    Each ``draws[i]["glyph"]`` must be a non-empty string containing a single
    character from the Runic Unicode block (U+16A0–U+16F8).
    """
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()
    fakeTyping = MagicMock(spec=TypingManager)
    fakeTyping.action = None
    fakeTyping.maxTimeout = 60
    fakeTyping.sendTypingAction = AsyncMock(return_value=None)

    result = await cast(Any, handler)._llmToolDoRunesReading(
        extraData={"ensuredMessage": em, "typingManager": fakeTyping},
        question="что ждёт?",
        layout="three_runes",
        generate_image=False,
    )

    parsed = json.loads(result)
    assert parsed["done"] is True
    draws: list[Dict[str, Any]] = parsed["draws"]
    assert len(draws) == 3, f"Expected 3 draws, got {len(draws)}"
    for idx, entry in enumerate(draws):
        glyph = entry.get("glyph")
        assert glyph is not None, f"draws[{idx}]['glyph'] is None for a runes reading"
        assert isinstance(glyph, str) and glyph != "", f"draws[{idx}]['glyph'] is empty"
        assert len(glyph) == 1, f"draws[{idx}]['glyph'] {glyph!r} is not a single character"
        codepoint: int = ord(glyph)
        assert (
            0x16A0 <= codepoint <= 0x16F8
        ), f"draws[{idx}]['glyph'] {glyph!r} (U+{codepoint:04X}) is outside the Runic Unicode block"


async def test_toolPathJsonTarotGlyphIsNull() -> None:
    """LLM-tool JSON for a tarot reading must have ``glyph=null`` on every draw entry, dood!

    Tarot cards have no single canonical glyph, so the field must be absent
    (serialised as JSON ``null``) — never a runic character.
    """
    handler, mocks = _makeHandler()
    em = _makeEnsuredMessage()
    fakeTyping = MagicMock(spec=TypingManager)
    fakeTyping.action = None
    fakeTyping.maxTimeout = 60
    fakeTyping.sendTypingAction = AsyncMock(return_value=None)

    result = await cast(Any, handler)._llmToolDoTarotReading(
        extraData={"ensuredMessage": em, "typingManager": fakeTyping},
        question="что ждёт?",
        layout="three_card",
        generate_image=False,
    )

    parsed = json.loads(result)
    assert parsed["done"] is True
    draws: list[Dict[str, Any]] = parsed["draws"]
    assert len(draws) == 3, f"Expected 3 draws, got {len(draws)}"
    for idx, entry in enumerate(draws):
        assert "glyph" in entry, f"draws[{idx}] is missing the 'glyph' key"
        assert entry["glyph"] is None, f"draws[{idx}]['glyph'] must be null for a tarot card, got {entry['glyph']!r}"
