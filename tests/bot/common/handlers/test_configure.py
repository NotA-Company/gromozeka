"""Regression tests for model-tier visibility in the configure handler.

Pins the fix for silently-invisible models: a model whose ``tier`` config
value is missing or invalid (e.g. ``"bot_owner"`` with an underscore, which
``ChatTier.fromStr`` rejects) used to be dropped from the model picker
(``chatConfiguration_ConfigureKey``) and silently reverted on selection
(``chatConfiguration_SetValue``) with no diagnostic. Such models must now be
treated as ``bot-owner`` tier: visible to owner-tier chats only, and an
invalid tier value must produce a logged warning naming the model and the raw
value.
"""

import logging
from typing import Dict, List, Optional, Tuple, TypedDict
from unittest.mock import AsyncMock, Mock, patch

import pytest

import lib.utils as utils
from internal.bot.common.handlers.configure import ConfigureCommandHandler
from internal.bot.constants import EYE_EMOJI
from internal.bot.models import (
    BotProvider,
    ButtonConfigureAction,
    ButtonDataKey,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsValue,
    MessageSender,
)
from internal.database import Database
from internal.models import MessageId
from internal.services.cache.service import CacheService
from internal.services.llm.service import LLMService
from internal.services.queue_service.service import QueueService
from internal.services.storage.service import StorageService

_OWNER_CHAT_ID = 100
_MESSAGE_ID = 42
_OWNER_USER_ID = 123456
_REGULAR_USER_ID = 7
_ALL_SELECTABLE_MODELS = ["free-model", "paid-model", "invalid-tier-model", "no-tier-model"]


class _ModelInfoDict(TypedDict, total=False):
    """``getModelInfo`` payload for one mocked model-catalog entry.

    Keys mirror the fields the configure paths actually read; all optional so
    a tier-less model is expressed by omitting ``tier``.
    """

    tier: str
    support_text: bool
    support_images: bool
    support_image_input: bool


def _modelInfos(*, includeInvalid: bool = True, includeNoTier: bool = True) -> Dict[str, _ModelInfoDict]:
    """Build the mock model catalog served by the mock LLM manager.

    Args:
        includeInvalid: When False the catalog has no invalid-tier model
            (used by tests that assert no warning is ever logged).
        includeNoTier: When False the catalog has no tier-less model.

    Returns:
        Mapping of model name to ``getModelInfo`` payload.
    """
    infos: Dict[str, _ModelInfoDict] = {
        "free-model": {"tier": "free", "support_text": True, "support_images": False},
        "paid-model": {"tier": "paid", "support_text": True, "support_images": False},
    }
    if includeNoTier:
        infos["no-tier-model"] = {"support_text": True, "support_images": False}
    if includeInvalid:
        infos["invalid-tier-model"] = {"tier": "bot_owner", "support_text": True, "support_images": False}
    return infos


def _makeConfigManager() -> Mock:
    """Build a minimal ConfigManager stub for the handler constructor.

    Returns:
        Mock exposing ``getBotConfig()`` with token/owners and empty model config.
    """
    cm = Mock()
    cm.getBotConfig = Mock(return_value={"token": "test_token", "owners": [_OWNER_USER_ID]})
    cm.getModelsConfig = Mock(return_value={})
    cm.get = Mock(return_value={})
    return cm


def _makeHandler(
    *, isOwnerUser: bool, modelInfos: Optional[Dict[str, _ModelInfoDict]] = None
) -> Tuple[ConfigureCommandHandler, Mock, AsyncMock]:
    """Construct a ``ConfigureCommandHandler`` with all service deps mocked.

    Args:
        isOwnerUser: What ``bot.isBotOwner`` reports for the callback user.
        modelInfos: Mock model catalog; defaults to ``_modelInfos()``.

    Returns:
        Tuple of (handler, cacheMock, editMessageMock). The handler is wired
        to mocked cache/queue/storage/LLM services and a mock bot;
        ``cacheMock`` is the ``Mock`` used as the handler's cache service
        (``setChatSetting`` is an ``AsyncMock`` capturing applied values);
        ``editMessageMock`` captures every ``editMessage`` call.
    """
    infos = _modelInfos() if modelInfos is None else modelInfos
    llmManager = Mock()
    llmManager.listModels = Mock(return_value=list(infos.keys()))
    llmManager.getModelInfo = Mock(side_effect=lambda name: infos.get(name))
    llmService = Mock()
    llmService.getLLMManager = Mock(return_value=llmManager)
    cache = Mock()
    cache.setChatSetting = AsyncMock(return_value=None)
    with (
        patch.object(CacheService, "getInstance", return_value=cache),
        patch.object(QueueService, "getInstance", return_value=Mock()),
        patch.object(StorageService, "getInstance", return_value=Mock()),
        patch.object(LLMService, "getInstance", return_value=llmService),
    ):
        handler = ConfigureCommandHandler(
            configManager=_makeConfigManager(),
            database=Mock(spec=Database),
            botProvider=BotProvider.TELEGRAM,
        )

    bot = Mock()
    bot.isBotOwner = Mock(return_value=isOwnerUser)
    bot.getBotUserName = AsyncMock(return_value="testbot")
    handler.injectBot(bot)
    editMessageMock = AsyncMock(return_value=True)
    handler.editMessage = editMessageMock  # type: ignore[method-assign]
    handler.getChatInfo = AsyncMock(return_value={"chat_id": 1, "type": "private"})  # type: ignore[method-assign]
    handler.getChatTitle = Mock(return_value="Test Chat")  # type: ignore[method-assign]
    return handler, cache, editMessageMock


def _chatSettings(
    baseTier: str, *, currentModel: str = "free-model", currentImageModel: str = "free-model"
) -> ChatSettingsDict:
    """Build a complete chat-settings dict for the configure paths.

    Covers every ``ChatSettingsKey`` the picker/SetValue paths subscript
    (production reads settings via direct subscript, never ``.get()``);
    ``IMAGE_GENERATION_MODEL`` is required by the ConfigureKey path for both
    picker types (``wasChanged`` / current-value rendering subscript it).

    Args:
        baseTier: Value for ``BASE_TIER`` ("free", "paid", "bot-owner", ...).
        currentModel: Current ``CHAT_MODEL`` value (the revert target).
        currentImageModel: Current ``IMAGE_GENERATION_MODEL`` value.

    Returns:
        ChatSettingsDict for the mocked ``getChatSettings``.
    """
    return {
        ChatSettingsKey.BASE_TIER: ChatSettingsValue(baseTier),
        ChatSettingsKey.CHAT_MODEL: ChatSettingsValue(currentModel),
        ChatSettingsKey.IMAGE_GENERATION_MODEL: ChatSettingsValue(currentImageModel),
    }


def _buttonTexts(editMessageMock: AsyncMock) -> List[str]:
    """Collect all inline-button texts captured by the mocked ``editMessage``.

    Args:
        editMessageMock: The ``AsyncMock`` substituted for ``editMessage``.

    Returns:
        Flat list of button texts across every captured edit call.
    """
    texts: List[str] = []
    for call in editMessageMock.await_args_list:
        keyboard = call.kwargs.get("inlineKeyboard") or []
        for row in keyboard:
            for button in row:
                texts.append(button.text)
    return texts


class TestConfigureKeyModelPickerRegression:
    """Pins owner-only picker visibility for missing/invalid-tier models."""

    async def _collectButtonTexts(
        self,
        caplog: pytest.LogCaptureFixture,
        *,
        baseTier: str,
        selectableModels: List[str],
        modelInfos: Dict[str, _ModelInfoDict],
    ) -> List[str]:
        """Render the CHAT_MODEL picker for a chat with the given tier.

        Args:
            caplog: pytest log-capture fixture (WARNING level is enabled).
            baseTier: BASE_TIER of the configuring chat.
            selectableModels: Value for ``handler.selectableModels``.
            modelInfos: Mock model catalog for the LLM manager.

        Returns:
            Button texts the picker produced.
        """
        handler, _cache, editMessageMock = _makeHandler(isOwnerUser=False, modelInfos=modelInfos)
        handler.getChatSettings = AsyncMock(return_value=_chatSettings(baseTier))  # type: ignore[method-assign]
        handler.selectableModels = selectableModels
        # The constructor already logs the invalid-tier startup warning; drop
        # it so the asserted warning provably comes from the picker path below.
        caplog.clear()

        data: utils.PayloadDict = {ButtonDataKey.Key: ChatSettingsKey.CHAT_MODEL.getId()}
        with caplog.at_level(logging.WARNING):
            await handler.chatConfiguration_ConfigureKey(
                data,
                messageId=MessageId(_MESSAGE_ID),
                messageChatId=_OWNER_CHAT_ID,
                user=MessageSender(id=_REGULAR_USER_ID, name="User", username="user"),
                chatId=_OWNER_CHAT_ID,
            )
        return _buttonTexts(editMessageMock)

    async def test_ownerTierChatSeesInvalidTierModel_withWarning(self, caplog: pytest.LogCaptureFixture) -> None:
        """A ``tier = "bot_owner"`` model is now offered to an owner-tier chat,
        and the invalid raw value is logged.

        Before the fix the model was silently absent from the picker.

        Args:
            caplog: pytest log-capture fixture.

        Returns:
            None
        """
        texts = await self._collectButtonTexts(
            caplog,
            baseTier="bot-owner",
            selectableModels=_ALL_SELECTABLE_MODELS,
            modelInfos=_modelInfos(),
        )

        assert any("invalid-tier-model" in text for text in texts)
        assert "invalid-tier-model" in caplog.text
        assert "has invalid tier 'bot_owner'" in caplog.text

    async def test_ownerTierChatSeesNoTierModel_withoutWarning(self, caplog: pytest.LogCaptureFixture) -> None:
        """A model with NO ``tier`` key is offered to an owner-tier chat and
        produces no warning (documented default).

        Args:
            caplog: pytest log-capture fixture.

        Returns:
            None
        """
        texts = await self._collectButtonTexts(
            caplog,
            baseTier="bot-owner",
            selectableModels=["free-model", "no-tier-model"],
            modelInfos=_modelInfos(includeInvalid=False),
        )

        assert any("no-tier-model" in text for text in texts)
        assert any("free-model" in text for text in texts)
        assert "has invalid tier" not in caplog.text

    async def test_lowerTierChatsDoNotSeeInvalidOrMissingTierModels(self, caplog: pytest.LogCaptureFixture) -> None:
        """Invalid/missing-tier models stay hidden from a free-tier chat.

        Args:
            caplog: pytest log-capture fixture.

        Returns:
            None
        """
        texts = await self._collectButtonTexts(
            caplog,
            baseTier="free",
            selectableModels=_ALL_SELECTABLE_MODELS,
            modelInfos=_modelInfos(),
        )

        assert any("free-model" in text for text in texts)
        assert not any("invalid-tier-model" in text for text in texts)
        assert not any("no-tier-model" in text for text in texts)
        assert not any("paid-model" in text for text in texts)

    async def test_paidTierChatStillSeesPaidModel(self, caplog: pytest.LogCaptureFixture) -> None:
        """A valid ``"paid"`` tier model keeps its existing visibility.

        Args:
            caplog: pytest log-capture fixture.

        Returns:
            None
        """
        texts = await self._collectButtonTexts(
            caplog,
            baseTier="paid",
            selectableModels=_ALL_SELECTABLE_MODELS,
            modelInfos=_modelInfos(),
        )

        assert any("paid-model" in text for text in texts)
        assert any("free-model" in text for text in texts)
        assert not any("invalid-tier-model" in text for text in texts)

    async def test_constructorSelectableModels_includeMissingAndInvalidTierModels(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Constructor-built ``selectableModels`` keeps tier-less and
        invalid-tier models; the picker then gates only their visibility.

        Integration-style guard for the startup filter itself: the handlers
        below are used exactly as ``__init__`` built them (the
        ``selectableModels`` attribute is never replaced post-construction,
        so reverting the constructor to the old truthiness-only gate fails
        this test). An owner-tier chat is offered both rescued models; a
        free-tier chat is offered neither.

        Args:
            caplog: pytest log-capture fixture.

        Returns:
            None
        """
        modelInfos = _modelInfos()
        ownerHandler, _ownerCache, ownerEditMock = _makeHandler(isOwnerUser=False, modelInfos=modelInfos)
        freeHandler, _freeCache, freeEditMock = _makeHandler(isOwnerUser=False, modelInfos=modelInfos)

        # Exactly the lists __init__ built — no post-construction replacement.
        assert "no-tier-model" in ownerHandler.selectableModels
        assert "invalid-tier-model" in ownerHandler.selectableModels

        data: utils.PayloadDict = {ButtonDataKey.Key: ChatSettingsKey.CHAT_MODEL.getId()}

        ownerHandler.getChatSettings = AsyncMock(return_value=_chatSettings("bot-owner"))  # type: ignore[method-assign]
        # Drop the constructor's startup warning so the asserted warning
        # provably comes from the picker path below.
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            await ownerHandler.chatConfiguration_ConfigureKey(
                data,
                messageId=MessageId(_MESSAGE_ID),
                messageChatId=_OWNER_CHAT_ID,
                user=MessageSender(id=_REGULAR_USER_ID, name="User", username="user"),
                chatId=_OWNER_CHAT_ID,
            )
        ownerTexts = _buttonTexts(ownerEditMock)
        assert any("no-tier-model" in text for text in ownerTexts)
        assert any("invalid-tier-model" in text for text in ownerTexts)
        assert "has invalid tier 'bot_owner'" in caplog.text

        freeHandler.getChatSettings = AsyncMock(return_value=_chatSettings("free"))  # type: ignore[method-assign]
        with caplog.at_level(logging.WARNING):
            await freeHandler.chatConfiguration_ConfigureKey(
                data,
                messageId=MessageId(_MESSAGE_ID),
                messageChatId=_OWNER_CHAT_ID,
                user=MessageSender(id=_REGULAR_USER_ID, name="User", username="user"),
                chatId=_OWNER_CHAT_ID,
            )
        freeTexts = _buttonTexts(freeEditMock)
        assert any("free-model" in text for text in freeTexts)
        assert not any("no-tier-model" in text for text in freeTexts)
        assert not any("invalid-tier-model" in text for text in freeTexts)


class TestConfigureKeyModelPickerVisionMarker:
    """Pins the 👁️ vision marker on /configure model-picker buttons.

    Models whose ``modelInfo`` carries a truthy ``support_image_input`` get an
    ``EYE_EMOJI`` suffix appended to their button label, BEFORE the ``" (*)"``
    selection marker. The render site is shared by the MODEL and IMAGE_MODEL
    pickers, so an image-generation model that also accepts image input is
    marked in the IMAGE_MODEL picker too.
    """

    _VISION_MODEL_INFOS: Dict[str, _ModelInfoDict] = {
        "gpt-oculus": {"tier": "free", "support_text": True, "support_images": False, "support_image_input": True},
        "gpt-plain": {"tier": "free", "support_text": True, "support_images": False},
        "dall-e-oculus": {"tier": "free", "support_text": False, "support_images": True, "support_image_input": True},
        "dall-e-plain": {"tier": "free", "support_text": False, "support_images": True, "support_image_input": False},
    }

    async def _collectButtonTexts(self, *, key: ChatSettingsKey, currentModel: str = "no-model-selected") -> List[str]:
        """Render the picker for *key* against the shared vision-model catalog.

        Args:
            key: ``ChatSettingsKey`` whose picker is rendered
                (``CHAT_MODEL`` or ``IMAGE_GENERATION_MODEL``).
            currentModel: Current ``CHAT_MODEL`` value; anything absent from
                the catalog keeps the ``" (*)"`` selection marker off every
                button.

        Returns:
            Button texts the picker produced.
        """
        handler, _cache, editMessageMock = _makeHandler(isOwnerUser=False, modelInfos=dict(self._VISION_MODEL_INFOS))
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value=_chatSettings("paid", currentModel=currentModel)
        )
        handler.selectableModels = list(self._VISION_MODEL_INFOS.keys())

        data: utils.PayloadDict = {ButtonDataKey.Key: key.getId()}
        await handler.chatConfiguration_ConfigureKey(
            data,
            messageId=MessageId(_MESSAGE_ID),
            messageChatId=_OWNER_CHAT_ID,
            user=MessageSender(id=_REGULAR_USER_ID, name="User", username="user"),
            chatId=_OWNER_CHAT_ID,
        )
        return _buttonTexts(editMessageMock)

    async def test_eyeEmojiConstant_hasExactCodepointSequence(self) -> None:
        """``EYE_EMOJI`` is exactly U+1F441 + U+FE0F: VS16 forces emoji
        presentation, so silently stripping it (plain monochrome glyph) must
        fail this pin, not just the behavior tests above that reuse the
        constant itself.

        Returns:
            None
        """
        assert [ord(character) for character in EYE_EMOJI] == [0x1F441, 0xFE0F]

    async def test_visionModelButtonShowsEyeMarker(self) -> None:
        """A ``support_image_input`` model's button label contains the eye.

        Returns:
            None
        """
        texts = await self._collectButtonTexts(key=ChatSettingsKey.CHAT_MODEL)

        visionButtons = [text for text in texts if "gpt-oculus" in text]
        assert visionButtons, "vision model button missing from picker"
        assert all(EYE_EMOJI in text for text in visionButtons)

    async def test_nonVisionModelButtonHasNoEyeMarker(self) -> None:
        """A model without ``support_image_input`` gets no eye — including the
        absent-key default (``gpt-plain`` omits the field entirely).

        Returns:
            None
        """
        texts = await self._collectButtonTexts(key=ChatSettingsKey.CHAT_MODEL)

        plainButtons = [text for text in texts if "gpt-plain" in text]
        assert plainButtons, "plain model button missing from picker"
        assert all(EYE_EMOJI not in text for text in plainButtons)

    async def test_selectedVisionModel_eyeAppearsBeforeSelectionMarker(self) -> None:
        """A selected vision model reads ``<emoji> <name> <eye> (*)``.

        The eye is appended before the ``" (*)"`` selection marker.

        Returns:
            None
        """
        texts = await self._collectButtonTexts(key=ChatSettingsKey.CHAT_MODEL, currentModel="gpt-oculus")

        selectedButtons = [text for text in texts if "gpt-oculus" in text]
        assert selectedButtons, "selected vision model button missing from picker"
        for text in selectedButtons:
            assert text.endswith(f"{EYE_EMOJI} (*)")
            assert text.index(EYE_EMOJI) < text.index("(*)")

    async def test_imageModelPicker_visionImageModelGetsEyeMarker(self) -> None:
        """The shared render site marks vision-capable image-generation models.

        Both ``support_images`` models are listed in the IMAGE_MODEL picker;
        only the one with ``support_image_input`` carries the eye.

        Returns:
            None
        """
        texts = await self._collectButtonTexts(key=ChatSettingsKey.IMAGE_GENERATION_MODEL)

        visionButtons = [text for text in texts if "dall-e-oculus" in text]
        plainButtons = [text for text in texts if "dall-e-plain" in text]
        assert visionButtons, "vision image model missing from IMAGE_MODEL picker"
        assert plainButtons, "non-vision image model missing from IMAGE_MODEL picker"
        assert all(EYE_EMOJI in text for text in visionButtons)
        assert all(EYE_EMOJI not in text for text in plainButtons)


class TestSetValueTierValidationRegression:
    """Pins selection-time tier validation for missing/invalid-tier models."""

    async def _selectModel(
        self,
        caplog: pytest.LogCaptureFixture,
        *,
        isOwnerUser: bool,
        baseTier: str,
        valueIndex: int,
        modelInfos: Optional[Dict[str, _ModelInfoDict]] = None,
    ) -> Mock:
        """Select a model by picker index via ``chatConfiguration_SetValue``.

        Args:
            caplog: pytest log-capture fixture (WARNING level is enabled).
            isOwnerUser: Whether the selecting user is a bot owner.
            baseTier: BASE_TIER of the configuring chat.
            valueIndex: Index into ``_ALL_SELECTABLE_MODELS`` to select.
            modelInfos: Mock model catalog; defaults to ``_modelInfos()``.

        Returns:
            The cache mock after the callback; ``setChatSetting`` is an
            ``AsyncMock`` capturing the applied value.
        """
        handler, cache, _editMessageMock = _makeHandler(isOwnerUser=isOwnerUser, modelInfos=modelInfos)
        handler.getChatSettings = AsyncMock(return_value=_chatSettings(baseTier))  # type: ignore[method-assign]
        handler.selectableModels = _ALL_SELECTABLE_MODELS
        # The constructor already logs the invalid-tier startup warning; drop
        # it so the asserted warning provably comes from the set-value path.
        caplog.clear()

        data: utils.PayloadDict = {
            ButtonDataKey.ConfigureAction: ButtonConfigureAction.SetValue,
            ButtonDataKey.ChatId: _OWNER_CHAT_ID,
            ButtonDataKey.Key: ChatSettingsKey.CHAT_MODEL.getId(),
            ButtonDataKey.Value: valueIndex,
        }
        with caplog.at_level(logging.WARNING):
            await handler.chatConfiguration_SetValue(
                data,
                messageId=MessageId(_MESSAGE_ID),
                messageChatId=_OWNER_CHAT_ID,
                user=MessageSender(id=_REGULAR_USER_ID, name="User", username="user"),
                chatId=_OWNER_CHAT_ID,
            )
        return cache

    async def test_ownerCanSelectInvalidTierModel_withWarning(self, caplog: pytest.LogCaptureFixture) -> None:
        """An owner selecting a ``tier = "bot_owner"`` model succeeds now.

        Before the fix the selection was silently reverted to the previous
        value.

        Args:
            caplog: pytest log-capture fixture.

        Returns:
            None
        """
        cache = await self._selectModel(
            caplog,
            isOwnerUser=True,
            baseTier="free",
            valueIndex=_ALL_SELECTABLE_MODELS.index("invalid-tier-model"),
        )

        appliedValue = cache.setChatSetting.await_args.args[2]
        assert appliedValue.value == "invalid-tier-model"
        assert "invalid-tier-model" in caplog.text
        assert "has invalid tier 'bot_owner'" in caplog.text

    async def test_nonOwnerSelectingInvalidTierModel_revertsWithWarning(self, caplog: pytest.LogCaptureFixture) -> None:
        """A free-tier (non-owner) user selecting an invalid-tier model gets
        the old value back, and the invalid tier is logged.

        Args:
            caplog: pytest log-capture fixture.

        Returns:
            None
        """
        cache = await self._selectModel(
            caplog,
            isOwnerUser=False,
            baseTier="free",
            valueIndex=_ALL_SELECTABLE_MODELS.index("invalid-tier-model"),
        )

        appliedValue = cache.setChatSetting.await_args.args[2]
        assert appliedValue.value == "free-model"
        assert "has invalid tier 'bot_owner'" in caplog.text

    async def test_ownerSelectingNoTierModel_succeedsSilently(self, caplog: pytest.LogCaptureFixture) -> None:
        """An owner selecting a model with NO tier key succeeds without a
        warning (documented default).

        Args:
            caplog: pytest log-capture fixture.

        Returns:
            None
        """
        cache = await self._selectModel(
            caplog,
            isOwnerUser=True,
            baseTier="free",
            valueIndex=_ALL_SELECTABLE_MODELS.index("no-tier-model"),
            modelInfos=_modelInfos(includeInvalid=False),
        )

        appliedValue = cache.setChatSetting.await_args.args[2]
        assert appliedValue.value == "no-tier-model"
        assert "has invalid tier" not in caplog.text
