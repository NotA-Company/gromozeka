"""Session-id threading tests for :class:`MediaHandler` lib/ai call sites.

Covers the sessionId wiring for prompt-cache affinity (the opencode-go
``x-opencode-session`` header) across the four ``lib/ai`` call sites in
``internal/bot/common/handlers/media.py``:

* :class:`TestLlmToolGenerateAndSendImage` — the ``generate_and_send_image``
  tool executes mid-conversation, so its ``generateImage`` call shares the
  conversation session (``getLLMRequestSessionId``: chat + thread root).
* :class:`TestAnalyzeCommandSessionId` — ``/analyze`` is a one-shot analysis
  of a content item: keyed by the parent message's stored media id
  (``mediaList[i].id``, file_unique_id-based), with a fallback to the
  analyzing command message id when no stored media id exists (freshly
  downloaded media, e.g. the Telegram ``photo[-1].file_id`` path).
* :class:`TestAnalyzeCommandPartialDownloadAlignment` — regression for the
  multi-attachment analyze path: when a download fails, the stored-id
  lookup stays index-aligned with the *successfully downloaded* items; the
  analysis must still complete deterministically (documented bucket
  shift), never crash.
* :class:`TestDrawCommandSessionId` — one ``/draw`` invocation computes a
  single session id and passes it to BOTH the ``generateText`` (prompt
  synthesis) and ``generateImage`` calls.

All LLM calls are stubbed at the ``LLMService`` boundary and the asserted
``sessionId`` kwargs are computed with the canonical
:func:`lib.ai.session.buildSessionId`. No real network, LLM, or database
I/O occurs; the autouse singleton-reset fixtures from ``tests/conftest.py``
keep the ``LLMService`` singleton fresh per test.
"""

import datetime
import json
import struct
import zlib
from typing import List, cast
from unittest.mock import AsyncMock, Mock, patch

import telegram

import lib.max_bot.models as maxModels
from internal.bot.common.handlers.media import MediaHandler
from internal.bot.common.models import TypingAction
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
    MessageType,
)
from internal.bot.models.ensured_message import MediaContent
from internal.models import MessageId
from internal.services.cache.service import CacheService
from internal.services.queue_service.service import QueueService
from internal.services.storage.service import StorageService
from lib.ai import ModelResultStatus, ModelRunResult
from lib.ai.session import buildSessionId
from lib.max_bot.models import PhotoAttachment, PhotoAttachmentPayload, Recipient, UserWithPhoto

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Chat id used across every test (positive → private chat shape).
CHAT_ID = 100

#: Command/tool message id used across every test.
MESSAGE_ID = 42

#: Parent (replied-to) message id.
PARENT_MESSAGE_ID = 7

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _makeConfigManager() -> Mock:
    """Build a ``ConfigManager`` stub satisfying ``MediaHandler.__init__``.

    ``BaseBotHandler.__init__`` reads ``getBotConfig()``; ``MediaHandler``
    additionally registers the image-generation tool on the (reset)
    ``LLMService`` singleton.

    Returns:
        ``Mock`` exposing ``getBotConfig()`` with deterministic values.
    """
    cm = Mock()
    cm.getBotConfig = Mock(return_value={"token": "test", "owners": []})
    return cm


def _makeDatabase() -> Mock:
    """Build a ``Database`` stub with the repositories the handler touches.

    ``chatMessages.getChatMessageByMessageId`` returns ``None`` so
    ``getLLMRequestSessionId`` falls back to the message's own id as the
    thread root (no stored thread information).

    Returns:
        ``Mock`` whose ``chatMessages`` repository methods are ``AsyncMock`` s.
    """
    db = Mock()
    db.chatMessages.getChatMessageByMessageId = AsyncMock(return_value=None)
    db.chatMessages.getChatMessagesByUser = AsyncMock(return_value=[])
    return db


def _chatSettings() -> ChatSettingsDict:
    """Build a complete chat-settings dict for every path under test.

    Production subscripts ``chatSettings[KEY]`` directly (no ``.get()``), so
    the dict must carry every key the media handler reads: the model keys
    passed to ``generateText`` / ``generateImage``, ``MEMORY_ENABLED`` +
    ``LLM_MESSAGE_FORMAT`` (draw's prompt-synthesis branch), and
    ``FALLBACK_HAPPENED_PREFIX`` (read when a generation used the fallback
    model). Values are real :class:`ChatSettingsValue` objects.

    Returns:
        A :class:`ChatSettingsDict` covering every key the handler reads.
    """
    return {
        ChatSettingsKey.FALLBACK_HAPPENED_PREFIX: ChatSettingsValue("FALLBACK! "),
        ChatSettingsKey.MEMORY_ENABLED: ChatSettingsValue(False),
        ChatSettingsKey.LLM_MESSAGE_FORMAT: ChatSettingsValue("text"),
        ChatSettingsKey.IMAGE_PARSING_MODEL: ChatSettingsValue("dummy-vision-model"),
        ChatSettingsKey.IMAGE_PARSING_FALLBACK_MODEL: ChatSettingsValue("dummy-vision-fallback"),
        ChatSettingsKey.CHAT_MODEL: ChatSettingsValue("dummy-chat-model"),
        ChatSettingsKey.FALLBACK_MODEL: ChatSettingsValue("dummy-fallback-model"),
    }


def _newMediaHandler(*, botProvider: BotProvider = BotProvider.TELEGRAM) -> MediaHandler:
    """Construct a :class:`MediaHandler` with stubbed leaf dependencies.

    ``getChatSettings`` / ``sendMessage`` are overridden at the instance
    level (handler layer returns ``Dict[ChatSettingsKey, ChatSettingsValue]``),
    and ``_bot`` is a ``Mock`` whose ``downloadAttachment`` returns a minimal
    valid PNG so ``magic.from_buffer`` classifies it as ``image/png``. Each
    test then overrides ``llmService.generateText`` / ``generateImage``.

    Args:
        botProvider: Platform the handler runs as (default TELEGRAM). The
            multi-attachment analyze download path is MAX-only, so tests
            exercising it pass ``BotProvider.MAX``.

    Returns:
        A constructed handler ready for stubbing.
    """
    with (
        patch.object(CacheService, "getInstance", return_value=Mock()),
        patch.object(QueueService, "getInstance", return_value=Mock()),
        patch.object(StorageService, "getInstance", return_value=Mock()),
    ):
        handler = MediaHandler(
            configManager=_makeConfigManager(),
            database=_makeDatabase(),
            botProvider=botProvider,
        )

    handler.getChatSettings = AsyncMock(return_value=_chatSettings())  # type: ignore[method-assign]
    handler.sendMessage = AsyncMock(return_value=Mock())  # type: ignore[method-assign]
    handler._bot = Mock(downloadAttachment=AsyncMock(return_value=_minimalPngBytes()))
    return handler


def _makeEnsuredMessage(
    *,
    chatId: int = CHAT_ID,
    messageId: int = MESSAGE_ID,
    messageText: str = "hello",
    messageType: MessageType = MessageType.TEXT,
) -> EnsuredMessage:
    """Build a real :class:`EnsuredMessage` for handler invocation.

    Production reads ``recipient.id``, ``messageId.asStr()`` and (in the
    tool path) validates ``isinstance(ensuredMessage, EnsuredMessage)``, so
    a genuine instance (not a ``Mock``) is required.

    Args:
        chatId: Recipient chat id (default :data:`CHAT_ID`).
        messageId: Message id (default :data:`MESSAGE_ID`).
        messageText: Message text (default ``"hello"``).
        messageType: Message type (default ``MessageType.TEXT``).

    Returns:
        A fully constructed :class:`EnsuredMessage`.
    """
    return EnsuredMessage(
        sender=MessageSender(id=7, name="Alice", username="@alice"),
        recipient=MessageRecipient(id=chatId, chatType=ChatType.PRIVATE),
        messageId=messageId,
        date=datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
        messageText=messageText,
        messageType=messageType,
    )


def _telegramPhotoMessage() -> telegram.Message:
    """Build a real ``telegram.Message`` carrying one photo.

    Used as the replied-to (parent) message: ``analyze_command`` resolves the
    ``file_id`` from ``photo[-1]`` and the parent ``EnsuredMessage`` wraps
    this object as its base message.

    Returns:
        A ``telegram.Message`` with a single ``PhotoSize``.
    """
    return telegram.Message(
        message_id=PARENT_MESSAGE_ID,
        date=datetime.datetime(2026, 5, 5, 11, 0, 0, tzinfo=datetime.timezone.utc),
        chat=telegram.Chat(id=CHAT_ID, type=telegram.Chat.PRIVATE),
        from_user=telegram.User(id=8, first_name="Bob", is_bot=False),
        photo=[
            telegram.PhotoSize(
                file_id="tg-file-1",
                file_unique_id="photo-unique-1",
                width=64,
                height=64,
            )
        ],
    )


def _telegramCommandMessage(replyTo: telegram.Message) -> telegram.Message:
    """Build a real ``telegram.Message`` for the /analyze command itself.

    Args:
        replyTo: The message the command replies to (wired as
            ``reply_to_message`` so ``getEnsuredRepliedToMessage`` resolves
            it through the real production path).

    Returns:
        A ``telegram.Message`` with command text replying to ``replyTo``.
    """
    return telegram.Message(
        message_id=MESSAGE_ID,
        date=datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
        chat=telegram.Chat(id=CHAT_ID, type=telegram.Chat.PRIVATE),
        from_user=telegram.User(id=7, first_name="Alice", is_bot=False),
        text="/analyze what is this",
        reply_to_message=replyTo,
    )


def _maxPhotoMessage(tokens: List[str]) -> maxModels.Message:
    """Build a real MAX ``Message`` carrying one photo attachment per token.

    Used as the replied-to (parent) message on the MAX multi-attachment
    download path: ``analyze_command`` iterates ``body.attachments`` and
    downloads each ``PhotoAttachment`` via its ``payload.token``.

    Args:
        tokens: Attachment tokens, one per photo attachment, in order.

    Returns:
        A ``maxModels.Message`` whose body carries the photo attachments.
    """
    return maxModels.Message(
        sender=UserWithPhoto(user_id=8, first_name="Bob"),
        recipient=Recipient(chat_id=CHAT_ID, chat_type=maxModels.ChatType.CHAT),
        timestamp=int(datetime.datetime(2026, 5, 5, 11, 0, 0, tzinfo=datetime.timezone.utc).timestamp()),
        body=maxModels.MessageBody(
            mid="parent-mid",
            seq=1,
            attachments=[
                PhotoAttachment(
                    payload=PhotoAttachmentPayload(
                        photo_id=index,
                        token=token,
                        url=f"https://example.invalid/{token}",
                    )
                )
                for index, token in enumerate(tokens)
            ],
        ),
    )


def _minimalPngBytes() -> bytes:
    """Build a minimal structurally valid PNG (1x1, one IDAT chunk).

    ``magic.from_buffer`` needs the IHDR chunk present to report
    ``image/png`` for these bytes (a bare ``\\x89PNG\\r\\n\\x1a\\n``
    signature is classified as ``text/plain`` by the installed libmagic),
    and ``analyze_command`` rejects non-image MIME types before reaching
    the LLM call.

    Returns:
        PNG-encoded bytes detectable as ``image/png``.
    """
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)

    def chunk(typ: bytes, data: bytes) -> bytes:
        """Encode one PNG chunk with its length and CRC."""
        return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )


def _modelRunResult(resultText: str) -> ModelRunResult:
    """Build a :class:`ModelRunResult` with ``FINAL`` status and given text.

    Args:
        resultText: The ``resultText`` the mocked LLM "returned".

    Returns:
        A ``ModelRunResult`` with ``isFallback`` False (the
        ``FALLBACK_HAPPENED_PREFIX`` branch is not exercised).
    """
    return ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=resultText)


def _imageRunResult() -> ModelRunResult:
    """Build a :class:`ModelRunResult` simulating successful image generation.

    The image branches require ``status == ModelResultStatus.FINAL`` and
    ``mediaData is not None`` to reach the photo send.

    Returns:
        A ``ModelRunResult`` with ``FINAL`` status and non-empty ``mediaData``.
    """
    return ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText="", mediaData=b"fake_image")


# ---------------------------------------------------------------------------
# 1. LLM tool path: generate_and_send_image
# ---------------------------------------------------------------------------


class TestLlmToolGenerateAndSendImage:
    """Session-id assertions for the ``generate_and_send_image`` tool path.

    The tool fires mid-conversation, so per the D1 rule its image call must
    reuse the conversation session (``getLLMRequestSessionId`` →
    ``gromozeka-<chatId>-<rootMessageId>``), keeping the tool's prompt-cache
    bucket aligned with the chat generator that invoked it.
    """

    async def test_generateImageGetsConversationSessionId(self) -> None:
        """``generateImage`` receives the conversation session of the wrapped message.

        With no stored thread row (``getChatMessageByMessageId`` → ``None``),
        the thread root is the message's own id, yielding
        ``gromozeka-<chatId>-<messageId>``.
        """
        handler = _newMediaHandler()
        handler.llmService.generateImage = AsyncMock(return_value=_imageRunResult())  # type: ignore[method-assign]
        em = _makeEnsuredMessage(chatId=CHAT_ID, messageId=MESSAGE_ID)
        typingManager = TypingManager(action=TypingAction.TYPING, maxTimeout=600, repeatInterval=1)

        result = await handler._llmToolGenerateAndSendImage(
            {"ensuredMessage": em, "typingManager": typingManager},
            "a cat wearing a hat",
        )

        generateImage = cast(AsyncMock, handler.llmService.generateImage)
        generateImage.assert_awaited_once()
        assert generateImage.call_args is not None
        assert generateImage.call_args.kwargs["sessionId"] == buildSessionId(str(CHAT_ID), str(MESSAGE_ID))
        assert json.loads(result)["done"] is True


# ---------------------------------------------------------------------------
# 2. /analyze: stored media id vs fallback session
# ---------------------------------------------------------------------------


class TestAnalyzeCommandSessionId:
    """Session-id assertions for the ``/analyze`` one-shot analysis path.

    Per the D2 rule the bucket is per content item: the parent message's
    stored media id when one exists, else the analyzing command message.
    """

    async def test_analyzeUsesStoredMediaIdSession(self) -> None:
        """Stored ``mediaList[i].id`` (file_unique_id) keys the analysis session.

        The parent ensured message carries a stored media entry, so
        ``buildSessionId("media", <file_unique_id>)`` must reach
        ``generateText`` — repeated analyses of the same item then reuse one
        prompt-cache bucket regardless of which command targeted it.
        """
        handler = _newMediaHandler()
        handler.llmService.generateText = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("analysis")
        )

        parent = _makeEnsuredMessage(
            messageId=PARENT_MESSAGE_ID,
            messageText="",
            messageType=MessageType.IMAGE,
        )
        parent.mediaList = [MediaContent(id="photo-unique-1", content=None, processingInfo=None)]
        parent.setBaseMessage(_telegramPhotoMessage())
        em = _makeEnsuredMessage()
        em.isReply = True
        em.replyId = MessageId(PARENT_MESSAGE_ID)

        with patch.object(EnsuredMessage, "getEnsuredRepliedToMessage", return_value=parent):
            await handler.analyze_command(em, "analyze", "what is this", Mock(), None)

        generateText = cast(AsyncMock, handler.llmService.generateText)
        generateText.assert_awaited_once()
        assert generateText.call_args is not None
        assert generateText.call_args.kwargs["sessionId"] == buildSessionId("media", "photo-unique-1")

    async def test_analyzeFallsBackToCommandMessageSessionWithoutStoredMediaId(self) -> None:
        """No stored media id → ``buildSessionId("analyze", chatId, commandMessageId)``.

        Exercises the fully real reply resolution: the parent built from the
        platform photo message has an empty ``mediaList`` and ``mediaId is
        None`` (freshly downloaded media, the Telegram ``photo[-1].file_id``
        path), so the fallback session keyed by the command message must be
        used.
        """
        handler = _newMediaHandler()
        handler.llmService.generateText = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("analysis")
        )

        em = EnsuredMessage.fromTelegramMessage(_telegramCommandMessage(replyTo=_telegramPhotoMessage()))

        await handler.analyze_command(em, "analyze", "what is this", Mock(), None)

        generateText = cast(AsyncMock, handler.llmService.generateText)
        generateText.assert_awaited_once()
        assert generateText.call_args is not None
        assert generateText.call_args.kwargs["sessionId"] == buildSessionId("analyze", str(CHAT_ID), str(MESSAGE_ID))


# ---------------------------------------------------------------------------
# 2b. /analyze: multi-attachment partial download regression
# ---------------------------------------------------------------------------


class TestAnalyzeCommandPartialDownloadAlignment:
    """Regression: multi-attachment analyze with a failed download.

    ``analyze_command`` resolves the stored media id (``mediaList[i].id``)
    by the index of the *successfully downloaded* item, not by the
    attachment's own identity — so once an earlier download fails, every
    later analyzed item shifts one bucket up. This test pins the actual
    current behaviour precisely: the analysis still completes for the
    surviving item and the resolved bucket stays deterministic for a fixed
    failure pattern, even though the bucket belongs to a different
    attachment (misalignment is cosmetic — prompt-cache affinity only —
    and must never crash or abort the analysis).
    """

    async def test_partialDownloadAnalysisStaysDeterministic(self) -> None:
        """Failed first download → the survivor is analyzed under bucket ``mediaList[0]``.

        Two MAX photo attachments with stored media ids ``photo-unique-1`` /
        ``photo-unique-2``; the first download fails (``None``), the second
        returns a valid PNG. Exactly one ``generateText`` call happens per
        invocation, keyed ``buildSessionId("media", "photo-unique-1")`` — the
        stored id at the downloaded-position index (attachment 2's data under
        attachment 1's bucket: the documented index-alignment behaviour). A
        second identical invocation resolves the SAME bucket, and the analysis
        text is delivered both times — no crash, no abort.
        """
        handler = _newMediaHandler(botProvider=BotProvider.MAX)
        handler.llmService.generateText = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("analysis")
        )
        downloadMock = AsyncMock(
            side_effect=lambda mediaId, fileId: None if mediaId == "token-1" else _minimalPngBytes()
        )
        handler._bot = Mock(downloadAttachment=downloadMock)

        parent = _makeEnsuredMessage(
            messageId=PARENT_MESSAGE_ID,
            messageText="",
            messageType=MessageType.IMAGE,
        )
        parent.mediaList = [
            MediaContent(id="photo-unique-1", content=None, processingInfo=None),
            MediaContent(id="photo-unique-2", content=None, processingInfo=None),
        ]
        parent.setBaseMessage(_maxPhotoMessage(["token-1", "token-2"]))
        em = _makeEnsuredMessage()
        em.isReply = True
        em.replyId = MessageId(PARENT_MESSAGE_ID)

        with patch.object(EnsuredMessage, "getEnsuredRepliedToMessage", return_value=parent):
            await handler.analyze_command(em, "analyze", "what is this", Mock(), None)
            # Same failure pattern → same bucket (deterministic resolution).
            await handler.analyze_command(em, "analyze", "what is this", Mock(), None)

        generateText = cast(AsyncMock, handler.llmService.generateText)
        assert generateText.await_count == 2
        expectedSessionId = buildSessionId("media", "photo-unique-1")
        for call in generateText.await_args_list:
            assert call.kwargs["sessionId"] == expectedSessionId
        # The surviving item's analysis was delivered both times — the failed
        # download degraded the bucket, not the analysis itself.
        sendMessage = cast(AsyncMock, handler.sendMessage)
        assert sendMessage.await_count == 2
        for call in sendMessage.await_args_list:
            assert call.kwargs["messageText"] == "analysis"


# ---------------------------------------------------------------------------
# 3. /draw: one shared session for text + image calls
# ---------------------------------------------------------------------------


class TestDrawCommandSessionId:
    """Session-id assertions for the ``/draw`` invocation path.

    Per the D3 rule a single ``/draw`` computes its session id once and
    passes the same value to both lib/ai calls: the prompt-synthesis
    ``generateText`` (no-prompt branch) and the ``generateImage`` call whose
    prompt is the text call's output.
    """

    async def test_drawSharesOneSessionBetweenTextAndImageCalls(self) -> None:
        """Both ``generateText`` and ``generateImage`` receive the same draw session.

        The no-prompt branch (empty message, no reply/quote/args) triggers
        the prompt-synthesis ``generateText`` first; both calls must carry
        ``buildSessionId("draw", chatId, messageId)``.
        """
        handler = _newMediaHandler()
        handler.llmService.generateText = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("synthesized prompt")
        )
        handler.llmService.generateImage = AsyncMock(return_value=_imageRunResult())  # type: ignore[method-assign]

        # Empty message text + no reply/quote/args → prompt-synthesis branch.
        em = _makeEnsuredMessage(messageText="")

        await handler.draw_command(em, "draw", "", Mock(), None)

        expectedSessionId = buildSessionId("draw", str(CHAT_ID), str(MESSAGE_ID))
        generateText = cast(AsyncMock, handler.llmService.generateText)
        generateImage = cast(AsyncMock, handler.llmService.generateImage)
        generateText.assert_awaited_once()
        generateImage.assert_awaited_once()
        assert generateText.call_args is not None
        assert generateImage.call_args is not None
        assert generateText.call_args.kwargs["sessionId"] == expectedSessionId
        assert generateImage.call_args.kwargs["sessionId"] == expectedSessionId
