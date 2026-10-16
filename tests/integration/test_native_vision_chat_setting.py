"""Tests for the ``native-vision`` chat setting (native-vision Phase 1b).

Verifies that the ``NATIVE_VISION`` chat-settings key exists in the
``ChatSettingsKey`` enum, is registered in the ``_chatSettingsInfo`` metadata
dict with type BOOL on the BOT_OWNER page, and that its default value shipped
in ``configs/00-defaults/bot-defaults.toml`` flows into ``[bot.defaults]`` and
survives the exact ``ChatSettingsKey`` filter (``if k in ChatSettingsKey``)
``HandlersManager`` uses at startup.

The end-to-end propagation test additionally drives the REAL wiring: a real
``HandlersManager`` materializes the shipped default into the real
``CacheService``, a real ``LLMMessageHandler`` resolves the setting through
``getChatSettings``/``_nativeVisionEnabled``, and a real ``EnsuredMessage``
constructs its model message with the resulting ``nativeImages`` flag —
asserting no attachment under the shipped default and a real attachment
under a per-chat override.
"""

import contextlib
import datetime
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Generator, Tuple
from unittest.mock import Mock, patch

import pytest

from internal.bot.common.handlers.chat_search import ChatSearchHandler
from internal.bot.common.handlers.common import CommonHandler
from internal.bot.common.handlers.configure import ConfigureCommandHandler
from internal.bot.common.handlers.delete_from_user import DeleteFromUserMessageHandler
from internal.bot.common.handlers.dev_commands import DevCommandsHandler
from internal.bot.common.handlers.divination import DivinationHandler
from internal.bot.common.handlers.help_command import HelpHandler
from internal.bot.common.handlers.llm_messages import LLMMessageHandler
from internal.bot.common.handlers.manager import HandlersManager
from internal.bot.common.handlers.media import MediaHandler
from internal.bot.common.handlers.message_preprocessor import MessagePreprocessorHandler
from internal.bot.common.handlers.react_on_user import ReactOnUserMessageHandler
from internal.bot.common.handlers.resender import ResenderHandler
from internal.bot.common.handlers.sandbox import SandboxHandler
from internal.bot.common.handlers.spam import SpamHandler
from internal.bot.common.handlers.stats import StatsHandler
from internal.bot.common.handlers.summarization import SummarizationHandler
from internal.bot.common.handlers.topic_manager import TopicManagerHandler
from internal.bot.common.handlers.user_memories import UserMemoriesHandler
from internal.bot.common.handlers.weather import WeatherHandler
from internal.bot.common.handlers.yandex_search import YandexSearchHandler
from internal.bot.models import (
    BotProvider,
    ChatType,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
)
from internal.bot.models.chat_settings import (
    ChatSettingsKey,
    ChatSettingsPage,
    ChatSettingsType,
    ChatSettingsValue,
    getChatSettingsInfo,
)
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.models import MediaStatus
from internal.services.cache import CacheService
from internal.services.queue_service import QueueService
from internal.services.storage import StorageScope, StorageService
from lib.ai import ModelImagesMessage, ModelMessage
from lib.db.utils import DEFAULT_THREAD_ID


def _repoRoot() -> Path:
    """Resolve the repository root from this test file's location.

    Returns:
        Path: Absolute path of the repository root (two parents up from this file).
    """
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def defaultsConfigManager() -> Generator[ConfigManager, None, None]:
    """Build a real ``ConfigManager`` over ``configs/00-defaults`` only.

    Uses a non-existent ``configPath`` so only the directory-based merge runs.
    The default config sets ``application.root-dir = "storage"``, which causes
    ``ConfigManager.__init__`` to ``os.chdir`` into that subdirectory, so we
    first ``os.chdir`` into a temporary directory containing a ``storage``
    subdirectory; the original cwd is restored afterwards.

    Yields:
        ConfigManager: A manager loaded with the project default configs.
    """
    repoRoot: Path = _repoRoot()
    configsDir: Path = repoRoot / "configs" / "00-defaults"
    assert configsDir.is_dir(), f"Expected default configs at {configsDir}"

    originalCwd: str = os.getcwd()
    with tempfile.TemporaryDirectory() as tmpDir:
        storageDir: Path = Path(tmpDir) / "storage"
        storageDir.mkdir()
        os.chdir(tmpDir)
        try:
            manager = ConfigManager(
                configPath=str(configsDir / "__no_such_main_config__.toml"),
                configDirs=[str(configsDir)],
                dotEnvFile=str(configsDir / "__no_such_dotenv__"),
            )
            yield manager
        finally:
            os.chdir(originalCwd)


def testNativeVisionKeyIsInEnum() -> None:
    """``NATIVE_VISION`` must exist and round-trip through ``ChatSettingsKey(value)``.

    Returns:
        None
    """
    key = ChatSettingsKey.NATIVE_VISION
    assert key in ChatSettingsKey
    assert ChatSettingsKey(key.value) is key
    assert key.value == "native-vision"


def testNativeVisionHasInfoEntry() -> None:
    """``NATIVE_VISION`` must be BOOL on the BOT_OWNER page with descriptive texts.

    Returns:
        None
    """
    info = getChatSettingsInfo()
    assert ChatSettingsKey.NATIVE_VISION in info, "Missing _chatSettingsInfo entry for native-vision"

    entry = info[ChatSettingsKey.NATIVE_VISION]
    assert entry["type"] is ChatSettingsType.BOOL
    assert entry["page"] is ChatSettingsPage.BOT_OWNER
    assert isinstance(entry["short"], str) and entry["short"]
    longText: str = entry["long"]
    assert isinstance(longText, str) and longText
    # The long description must document the surviving load-bearing facts:
    # images go straight to the chat's vision models instead of a textual
    # description, and BOTH chat models (primary and fallback) must support
    # image input.
    assert "vision-модели" in longText.lower()
    assert "обе модели" in longText.lower()


def testDefaultFromTomlIsFalse(defaultsConfigManager: ConfigManager) -> None:
    """``[bot.defaults]`` must ship ``native-vision = false`` wired as a Bool setting.

    Walks the same path ``HandlersManager.__init__`` walks: read
    ``bot.defaults``, filter by ``if k in ChatSettingsKey``, wrap values in
    ``ChatSettingsValue``.

    Args:
        defaultsConfigManager: Real ``ConfigManager`` over the project defaults.

    Returns:
        None
    """
    botConfig = defaultsConfigManager.getBotConfig()
    rawDefaults: Dict[str, object] = botConfig.get("defaults", {})

    assert ChatSettingsKey.NATIVE_VISION.value in rawDefaults, "Missing native-vision default in bot.defaults"
    rawValue = rawDefaults[ChatSettingsKey.NATIVE_VISION.value]
    assert rawValue is False, f"native-vision default must be false, got {rawValue!r}"

    # Mirror HandlersManager: build the ChatSettingsValue dict the same way.
    materialised: Dict[ChatSettingsKey, ChatSettingsValue] = {
        ChatSettingsKey(k): ChatSettingsValue(v) for k, v in rawDefaults.items() if k in ChatSettingsKey
    }
    assert ChatSettingsKey.NATIVE_VISION in materialised, "native-vision dropped during ChatSettingsKey filtering"
    assert materialised[ChatSettingsKey.NATIVE_VISION].toBool() is False


# ---------------------------------------------------------------------------
# End-to-end propagation: shipped TOML default → real HandlersManager/Cache
# → real LLMMessageHandler consumer → real EnsuredMessage attach
# ---------------------------------------------------------------------------


def _buildManagerOverShippedDefaults(configManager: ConfigManager, database: Database) -> HandlersManager:
    """Construct a real ``HandlersManager`` over the shipped defaults config.

    Mirrors the established construction pattern from
    ``tests/bot/common/handlers/test_stats.py`` / ``test_base.py``: only the
    pipeline handlers' ``__init__``s, the custom-handler loader, and the
    ``QueueService`` singleton are stubbed — every other line of
    ``HandlersManager.__init__`` runs for real, including the production
    default-settings materialization into the REAL ``CacheService`` singleton
    (which must be reset by the caller beforehand).

    Args:
        configManager: Real ``ConfigManager`` loaded from ``configs/00-defaults``.
        database: Database wrapper the manager should hold.

    Returns:
        The constructed ``HandlersManager`` with the real cache populated
        from the shipped defaults.
    """
    _stubbedHandlerClasses: Tuple[type, ...] = (
        MessagePreprocessorHandler,
        SpamHandler,
        ConfigureCommandHandler,
        SummarizationHandler,
        UserMemoriesHandler,
        DevCommandsHandler,
        MediaHandler,
        CommonHandler,
        HelpHandler,
        DeleteFromUserMessageHandler,
        ReactOnUserMessageHandler,
        TopicManagerHandler,
        WeatherHandler,
        YandexSearchHandler,
        ResenderHandler,
        DivinationHandler,
        SandboxHandler,
        ChatSearchHandler,
        StatsHandler,
        LLMMessageHandler,
    )
    with contextlib.ExitStack() as stack:
        for handlerClass in _stubbedHandlerClasses:
            stack.enter_context(patch.object(handlerClass, "__init__", lambda self, **kwargs: None))
        mockLoader = stack.enter_context(patch("internal.bot.common.handlers.module_loader.CustomHandlerLoader"))
        stack.enter_context(patch.object(QueueService, "getInstance", return_value=Mock()))
        mockLoader.return_value.loadAll.return_value = []
        return HandlersManager(configManager=configManager, database=database, botProvider=BotProvider.TELEGRAM)


def _visionCapableModel() -> Mock:
    """Build a model double reporting vision capability.

    Returns:
        A ``Mock`` whose ``getInfo()`` carries ``support_image_input: True``.
    """
    model = Mock()
    model.getInfo.return_value = {"support_image_input": True}
    return model


def _makeMediaEnsuredMessage() -> EnsuredMessage:
    """Build a real :class:`EnsuredMessage` carrying one described image.

    Returns:
        A freshly constructed :class:`EnsuredMessage` with media ``media-1``
        attached (primary) and pre-filled description ``a red square``.
    """
    ensuredMessage = EnsuredMessage(
        sender=MessageSender(id=7, name="Alice", username="@alice"),
        recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
        messageId=42,
        date=datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
        messageText="look at this",
    )
    ensuredMessage.threadId = DEFAULT_THREAD_ID
    ensuredMessage.addMedia(mediaId="media-1", mediaContent="a red square", setMediaId=True)
    return ensuredMessage


async def testShippedDefaultFlowsToRealConsumer(
    defaultsConfigManager: ConfigManager,
    testDatabase: Database,
    tmp_path: Path,
) -> None:
    """The shipped ``native-vision = false`` default reaches the REAL consumer.

    Closes the four-site wiring end-to-end (enum ↔ ``_chatSettingsInfo`` ↔
    TOML default ↔ consumer): a real ``HandlersManager`` materializes the
    shipped default into the real ``CacheService`` (the production
    ``__init__`` block, not a test-owned copy), a real ``LLMMessageHandler``
    resolves the setting through ``getChatSettings`` + ``_nativeVisionEnabled``,
    and a real ``EnsuredMessage`` constructs its model message with the
    resulting ``nativeImages`` flag. Asserts (a) the shipped default yields NO
    image attachment (and never even consults model capability), and (b) a
    per-chat ``NATIVE_VISION = true`` override written through the real
    ``setChatSetting`` path — with vision-capable primary + fallback models —
    yields a real attachment.

    Args:
        defaultsConfigManager: Real ``ConfigManager`` over the project defaults.
        testDatabase: Fresh in-memory Database with migrations applied.
        tmp_path: pytest tmp dir for the real fs vision store.

    Returns:
        None
    """
    CacheService._instance = None
    QueueService._instance = None
    StorageService._instances.clear()
    try:
        # Real HandlersManager.__init__ → real default-settings materialization
        # into the real CacheService singleton.
        manager = _buildManagerOverShippedDefaults(defaultsConfigManager, testDatabase)
        # The DB injection HandlersManager.initialize performs at startup.
        await manager.cache.injectDatabase(testDatabase)

        # Real fs vision store so the attach path loads real bytes.
        storageConfigManager = Mock()
        storageConfigManager.getStorageConfig = Mock(
            return_value={
                "type": "null",
                "storages": {"vision": {"type": "fs", "fs": {"base-dir": str(tmp_path / "vision")}}},
            }
        )
        visionStorage = StorageService.getInstance(StorageScope.VISION)
        visionStorage.injectConfig(storageConfigManager, scope=StorageScope.VISION)

        # Real consumer handler (real BaseBotHandler + LLMMessageHandler inits);
        # only the queue singleton is stubbed and the LLM model catalog is a
        # mock via the service's real injection API — model capability is not
        # the wiring under test (unit-covered in test_llm_messages.py).
        with patch.object(QueueService, "getInstance", return_value=Mock()):
            handler = LLMMessageHandler(
                configManager=defaultsConfigManager,
                database=testDatabase,
                botProvider=BotProvider.TELEGRAM,
            )
        handler.llmService.injectLLMManager(Mock())
        resolveModelMock = Mock(return_value=_visionCapableModel())
        handler.llmService.resolveModel = resolveModelMock  # type: ignore[method-assign]

        # Seed the message's media row (DONE) + real bytes in the vision store.
        repo = testDatabase.mediaAttachments
        assert (
            await repo.addMediaAttachment(fileUniqueId="media-1", fileId="fid-media-1", status=MediaStatus.DONE) is True
        )
        assert await repo.updateMediaAttachment("media-1", visionUrl="media-1.jpeg") is True
        visionStorage.store("media-1.jpeg", b"IMG")

        ensuredMessage = _makeMediaEnsuredMessage()

        # (a) Shipped default: the REAL merged settings path yields False and
        # the consumer attaches nothing (capability resolution never runs —
        # the flag gates before it). The "False" string pins that the value
        # CAME from the shipped TOML bool (not from the empty-string
        # placeholder the manager seeds for keys missing from [bot.defaults]).
        chatSettings = await handler.getChatSettings(100)
        assert chatSettings[ChatSettingsKey.NATIVE_VISION].toStr() == "False"
        assert chatSettings[ChatSettingsKey.NATIVE_VISION].toBool() is False
        nativeVision = handler._nativeVisionEnabled(chatSettings)
        assert nativeVision is False
        resolveModelMock.assert_not_called()
        plainResult = await ensuredMessage.toModelMessage(testDatabase, cache=None, nativeImages=nativeVision)
        assert type(plainResult) is ModelMessage
        assert json.loads(plainResult.content)["mediaDescription"] == "a red square"

        # (b) Per-chat override through the REAL write path (updatedBy=0 →
        # bot-owner authorship, so the tier gate keeps the override), then the
        # real re-merge → attach.
        await handler.setChatSetting(
            100,
            ChatSettingsKey.NATIVE_VISION,
            ChatSettingsValue(True),
            user=MessageSender(id=0, name="Owner", username="@owner"),
        )
        chatSettings = await handler.getChatSettings(100)
        assert chatSettings[ChatSettingsKey.NATIVE_VISION].toBool() is True
        nativeVision = handler._nativeVisionEnabled(chatSettings)
        assert nativeVision is True
        imagesResult = await ensuredMessage.toModelMessage(testDatabase, cache=None, nativeImages=nativeVision)
        assert type(imagesResult) is ModelImagesMessage
        assert imagesResult.images == [bytearray(b"IMG")]
    finally:
        StorageService._instances.clear()
        CacheService._instance = None
        QueueService._instance = None
