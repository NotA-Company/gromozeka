"""Tarot and runes divination handler for the Gromozeka bot.

This module wires :class:`lib.divination.TarotSystem` and
:class:`lib.divination.RunesSystem` to two slash commands (``/taro`` and
``/runes``) and, when ``divination.tools-enabled`` is on, to two LLM tools
(``do_tarot_reading`` and ``do_runes_reading``).

The handler owns the bot/LLM/DB orchestration: parsing user input, drawing
symbols via the divination library, calling :class:`LLMService` for
interpretation and (optionally) image generation, sending the reply, and
persisting the reading via :class:`DivinationsRepository`. It is the only
seam between :mod:`lib.divination` (pure logic) and the bot internals.
"""

import logging
import re
from typing import Any, Dict, Optional, Tuple, Type

import lib.divination.localization as divinationLocalization
import lib.utils as utils
from internal.bot.common.models import TypingAction, UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    ChatSettingsKey,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    commandHandlerV2,
)
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.models import DivinationLayoutDict, MessageCategory
from lib.ai import (
    LLMFunctionParameter,
    LLMParameterType,
    ModelMessage,
    ModelResultStatus,
)
from lib.divination import (
    BaseDivinationSystem,
    Layout,
    Reading,
    RunesSystem,
    TarotSystem,
)

from .base import BaseBotHandler

logger = logging.getLogger(__name__)


# Default layout names used when an LLM tool omits / blanks out the layout
# argument. Slash commands REQUIRE an explicit layout — these defaults only
# apply on the LLM-tool path.
_DEFAULT_TAROT_LAYOUT_ID: str = "three_card"
_DEFAULT_RUNES_LAYOUT_ID: str = "three_runes"


def _formatLayoutsForHelp(system: Type[BaseDivinationSystem]) -> str:
    """Render the system's layouts as a comma-separated, backticked list.

    Args:
        system: Concrete divination system class.

    Returns:
        Comma-separated string of layout ids, each wrapped in backticks.
    """
    return ", ".join(f"`{layout.id}`" for layout in system.availableLayouts())


def _buildTaroHelp() -> str:
    """Build the ``/taro`` command help message.

    The list of available layouts is generated from
    :meth:`TarotSystem.availableLayouts` so adding a new layout
    automatically extends the help text.

    Returns:
        Russian help message for the ``/taro`` command.
    """
    layoutsList: str = _formatLayoutsForHelp(TarotSystem)
    return (
        " `<layout>` `[question]`: Раскинуть карты Таро.\n"
        f"Доступные расклады: {layoutsList}.\n"
        "Расклад указывать ОБЯЗАТЕЛЬНО."
    )


def _buildRunesHelp() -> str:
    """Build the ``/runes`` command help message.

    The list of available layouts is generated from
    :meth:`RunesSystem.availableLayouts` so adding a new layout
    automatically extends the help text.

    Returns:
        Russian help message for the ``/runes`` command.
    """
    layoutsList: str = _formatLayoutsForHelp(RunesSystem)
    return (
        " `<layout>` `[question]`: Раскинуть руны.\n"
        f"Доступные расклады: {layoutsList}.\n"
        "Расклад указывать ОБЯЗАТЕЛЬНО."
    )


class DivinationHandler(BaseBotHandler):
    """Tarot and runes divination handler.

    Registers ``/taro`` and ``/runes`` slash commands, plus the
    ``do_tarot_reading`` / ``do_runes_reading`` LLM tools when
    ``divination.tools-enabled`` is set. All deck / layout / drawing logic
    is delegated to :mod:`lib.divination`; this handler only orchestrates
    the bot, LLM service, and database.

    Attributes:
        config: Resolved ``[divination]`` section from the config.
        systems: Mapping of ``systemId`` → divination system class. Built
            from ``divination.tarot-enabled`` / ``divination.runes-enabled``.
        imageGenerationDefault: Default value used for the image step when
            invoked via slash command (``divination.image-generation``).
        discoveryEnabled: Whether layout discovery via web search is enabled
            (``divination.discovery-enabled``).
    """

    def __init__(
        self,
        *,
        configManager: ConfigManager,
        database: Database,
        botProvider: BotProvider,
    ) -> None:
        """Initialise the divination handler.

        Args:
            configManager: Configuration manager providing the ``divination``
                section.
            database: Database wrapper used to persist readings.
            botProvider: Bot provider type (Telegram / Max).

        Raises:
            RuntimeError: If ``divination.enabled`` is False — the handler
                must not be constructed in that case (the registration site
                in :class:`HandlersManager` is the gate).
        """
        super().__init__(
            configManager=configManager,
            database=database,
            botProvider=botProvider,
        )

        self.config: Dict[str, Any] = self.configManager.get("divination", {}) or {}
        if not self.config.get("enabled", False):
            logger.error("Divination is not enabled, can not load DivinationHandler!")
            raise RuntimeError("Divination is not enabled, can not load DivinationHandler")

        self.systems: Dict[str, Type[BaseDivinationSystem]] = {}
        if self.config.get("tarot-enabled", True):
            self.systems[TarotSystem.systemId] = TarotSystem
        if self.config.get("runes-enabled", True):
            self.systems[RunesSystem.systemId] = RunesSystem

        self.imageGenerationDefault: bool = bool(self.config.get("image-generation", True))
        self.discoveryEnabled: bool = bool(self.config.get("discovery-enabled", False))

        if self.config.get("tools-enabled", False):
            self._registerLlmTools()

    ###
    # LLM tool registration
    ###

    def _registerLlmTools(self) -> None:
        """Register ``do_tarot_reading`` and ``do_runes_reading`` LLM tools.

        Each tool is registered only if the corresponding system is enabled
        (i.e. present in :attr:`systems`). Tool handlers default to
        text-only output to save quota; the LLM may opt in to images via
        the ``generate_image`` argument.

        Returns:
            None
        """
        if TarotSystem.systemId in self.systems:
            tarotLayoutsList: str = ", ".join(
                ", ".join([layout.nameEn, layout.id, layout.nameRu]) for layout in TarotSystem.availableLayouts()
            )
            layoutParameterDescription = (
                (
                    "Layout name in English or Russian."
                    # f"Any custom layout name or one of predefined: {tarotLayoutsList}. "
                    # f"Default: {_DEFAULT_TAROT_LAYOUT_ID}"
                )
                if self.discoveryEnabled
                else (
                    f"Layout ID, One of: {tarotLayoutsList}. "
                    # f"Default: {_DEFAULT_TAROT_LAYOUT_ID}"
                )
            )
            self.llmService.registerTool(
                name="do_tarot_reading",
                description=(
                    "Perform a tarot reading using the Rider-Waite-Smith deck for the user. "
                    "Use this when the user asks for a tarot reading or to draw cards."
                ),
                parameters=[
                    LLMFunctionParameter(
                        name="question",
                        description="The user's question to interpret with the tarot reading.",
                        type=LLMParameterType.STRING,
                        required=True,
                    ),
                    LLMFunctionParameter(
                        name="layout",
                        description=layoutParameterDescription,
                        type=LLMParameterType.STRING,
                        required=True,
                    ),
                    LLMFunctionParameter(
                        name="generate_image",
                        description=(
                            "Whether to also generate and send to user a layout illustration. " "Default: false."
                        ),
                        type=LLMParameterType.BOOLEAN,
                        required=False,
                    ),
                ],
                handler=self._llmToolDoTarotReading,
            )

        if RunesSystem.systemId in self.systems:
            runesLayoutsList: str = ", ".join(
                ", ".join([layout.nameEn, layout.id, layout.nameRu]) for layout in RunesSystem.availableLayouts()
            )
            layoutParameterDescription = (
                (
                    "Layout name in English or Russian."
                    # f"Default: {_DEFAULT_RUNES_LAYOUT_ID}"
                )
                if self.discoveryEnabled
                else (
                    f"Layout ID, One of: {runesLayoutsList}. "
                    # f"Default: {_DEFAULT_RUNES_LAYOUT_ID}"
                )
            )
            self.llmService.registerTool(
                name="do_runes_reading",
                description=(
                    "Perform an Elder Futhark runic reading for the user. "
                    "Use this when the user asks for a runic reading, fortune, divination, or to cast runes."
                ),
                parameters=[
                    LLMFunctionParameter(
                        name="question",
                        description="The user's question to interpret with the runic reading.",
                        type=LLMParameterType.STRING,
                        required=True,
                    ),
                    LLMFunctionParameter(
                        name="layout",
                        description=layoutParameterDescription,
                        type=LLMParameterType.STRING,
                        required=True,
                    ),
                    LLMFunctionParameter(
                        name="generate_image",
                        description=(
                            "Whether to also generate and send to user a layout illustration. " "Default: false."
                        ),
                        type=LLMParameterType.BOOLEAN,
                        required=False,
                    ),
                ],
                handler=self._llmToolDoRunesReading,
            )

    ###
    # Slash commands
    ###

    @commandHandlerV2(
        commands=("taro", "tarot", "таро"),
        shortDescription="<layout> [question] - Tarot reading",
        helpMessage=_buildTaroHelp(),
        visibility={CommandPermission.DEFAULT},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def taroCommand(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        updateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the ``/taro`` slash command.

        Args:
            ensuredMessage: The originating user message.
            command: The command name that triggered this handler.
            args: Raw arguments string (everything after the command).
            updateObj: Raw update object from the platform.
            typingManager: Typing indicator manager passed in by the
                dispatcher.

        Returns:
            None
        """
        await self._handleReadingFromArgs(
            systemId=TarotSystem.systemId,
            ensuredMessage=ensuredMessage,
            args=args,
            typingManager=typingManager,
            invokedVia="command",
        )

    @commandHandlerV2(
        commands=("runes", "rune", "руны"),
        shortDescription="<layout> [question] - Runic reading",
        helpMessage=_buildRunesHelp(),
        visibility={CommandPermission.DEFAULT},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def runesCommand(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        updateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the ``/runes`` slash command.

        Args:
            ensuredMessage: The originating user message.
            command: The command name that triggered this handler.
            args: Raw arguments string (everything after the command).
            updateObj: Raw update object from the platform.
            typingManager: Typing indicator manager passed in by the
                dispatcher.

        Returns:
            None
        """
        await self._handleReadingFromArgs(
            systemId=RunesSystem.systemId,
            ensuredMessage=ensuredMessage,
            args=args,
            typingManager=typingManager,
            invokedVia="command",
        )

    ###
    # LLM tool handlers
    ###

    async def _llmToolDoTarotReading(
        self,
        extraData: Dict[str, Any],
        question: str,
        layout: Optional[str] = None,
        generate_image: bool = False,
        **kwargs: Any,
    ) -> str:
        """LLM tool handler that performs a tarot reading.

        Args:
            extraData: Tool-call context dict; must contain ``ensuredMessage``
                and ``typingManager`` (same convention as
                :class:`MediaHandler`).
            question: User question to interpret with the reading.
            layout: Optional layout id; defaults to ``three_card`` when
                omitted/empty.
            generate_image: Whether to also generate a spread illustration.
            **kwargs: Additional keyword arguments (ignored).

        Returns:
            JSON-encoded string with ``{"done": bool, ...}`` so the host
            LLM can incorporate the result naturally.
        """
        return await self._runReadingForTool(
            systemId=TarotSystem.systemId,
            extraData=extraData,
            question=question,
            layout=layout,
            generateImage=generate_image,
            defaultLayoutId=_DEFAULT_TAROT_LAYOUT_ID,
        )

    async def _llmToolDoRunesReading(
        self,
        extraData: Dict[str, Any],
        question: str,
        layout: Optional[str] = None,
        generate_image: bool = False,
        **kwargs: Any,
    ) -> str:
        """LLM tool handler that performs a runic reading.

        Args:
            extraData: Tool-call context dict; must contain ``ensuredMessage``
                and ``typingManager``.
            question: User question to interpret with the reading.
            layout: Optional layout id; defaults to ``three_runes`` when
                omitted/empty.
            generate_image: Whether to also generate a spread illustration.
            **kwargs: Additional keyword arguments (ignored).

        Returns:
            JSON-encoded string with ``{"done": bool, ...}`` so the host
            LLM can incorporate the result naturally.
        """
        return await self._runReadingForTool(
            systemId=RunesSystem.systemId,
            extraData=extraData,
            question=question,
            layout=layout,
            generateImage=generate_image,
            defaultLayoutId=_DEFAULT_RUNES_LAYOUT_ID,
        )

    async def _runReadingForTool(
        self,
        *,
        systemId: str,
        extraData: Dict[str, Any],
        question: str,
        layout: Optional[str],
        generateImage: bool,
        defaultLayoutId: str,
    ) -> str:
        """Common tool entry point that validates context and bridges to :meth:`_handleReading`.

        Resolves the layout (with default fallback), validates the
        ``extraData`` context dict, then delegates to :meth:`_handleReading`
        with ``returnToolJson=True``.

        Args:
            systemId: Divination system to use (``"tarot"`` / ``"runes"``).
            extraData: Tool context dict; must contain ``ensuredMessage`` and
                ``typingManager``.
            question: User question.
            layout: Layout id. Empty/None falls back to ``defaultLayoutId``.
            generateImage: Whether to generate a spread illustration.
            defaultLayoutId: Layout id used when ``layout`` is missing.

        Returns:
            JSON-encoded result for the LLM to consume.
        """
        logger.debug(
            f"Entering _runReadingForTool with systemId={systemId}, question={question}, "
            f"layout={layout}, generateImage={generateImage}"
        )
        if extraData is None:
            return utils.jsonDumps({"done": False, "errorMessage": "Missing tool context!"})

        ensuredMessage = extraData.get("ensuredMessage")
        if not isinstance(ensuredMessage, EnsuredMessage):
            return utils.jsonDumps(
                {"done": False, "errorMessage": "Missing or invalid ensuredMessage in tool context!"}
            )

        typingManager = extraData.get("typingManager")
        if typingManager is not None and not isinstance(typingManager, TypingManager):
            return utils.jsonDumps({"done": False, "errorMessage": "Invalid typingManager in tool context!"})

        systemCls: Optional[Type[BaseDivinationSystem]] = self.systems.get(systemId)
        if systemCls is None:
            return utils.jsonDumps({"done": False, "errorMessage": f"Система '{systemId}' не доступна."})

        layoutName: str = (layout or "").strip() or defaultLayoutId

        ret = await self._handleReading(
            systemId=systemId,
            ensuredMessage=ensuredMessage,
            layoutName=layoutName,
            question=question,
            typingManager=typingManager,
            invokedVia="llm_tool",
            generateImage=generateImage,
            isLLMCall=True,
        )
        if ret is not None:
            return ret
        return utils.jsonDumps({"done": False, "errorMessage": "Unknown error"})

    ###
    # Core engine
    ###

    @staticmethod
    def _parseArgs(args: str) -> Tuple[str, str]:
        """Split the raw command args into ``(layoutName, question)``.

        Args:
            args: Raw arguments string after the command.

        Returns:
            ``(layoutName, question)``. Both elements are stripped; either
            may be empty.
        """
        text: str = (args or "").strip()
        if not text:
            return "", ""
        parts = text.split(maxsplit=1)
        layoutName: str = parts[0].strip()
        question: str = parts[1].strip() if len(parts) > 1 else ""
        return layoutName, question

    async def _handleReadingFromArgs(
        self,
        systemId: str,
        ensuredMessage: EnsuredMessage,
        args: str,
        typingManager: Optional[TypingManager],
        *,
        invokedVia: str,
    ) -> None:
        """Parse args, validate inputs, and delegate to :meth:`_handleReading`.

        This thin wrapper encapsulates the parse → resolve → error-reply flow
        shared by :meth:`taroCommand` and :meth:`runesCommand`, keeping those
        methods trivially small.

        Args:
            systemId: Divination system id (``"tarot"`` / ``"runes"``).
            ensuredMessage: The originating user message.
            args: Raw command arguments string (layout + optional question).
            typingManager: Typing indicator manager (may be ``None``).
            invokedVia: Provenance tag for the DB row (e.g. ``"command"``).

        Returns:
            Always ``""`` (slash commands ignore the return value).
        """
        systemCls: Optional[Type[BaseDivinationSystem]] = self.systems.get(systemId)
        if systemCls is None:
            await self.sendMessage(
                ensuredMessage,
                messageText=f"Система '{systemId}' не доступна.",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        layoutName, question = self._parseArgs(args)

        if not layoutName:
            await self.sendMessage(
                ensuredMessage,
                messageText="Необходимо указать расклад.\n" f"Доступные расклады: {_formatLayoutsForHelp(systemCls)}.",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        await self._handleReading(
            systemId=systemId,
            ensuredMessage=ensuredMessage,
            layoutName=layoutName,
            question=question,
            typingManager=typingManager,
            invokedVia=invokedVia,
            generateImage=None,
            isLLMCall=False,
        )

    async def _handleReading(
        self,
        *,
        systemId: str,
        ensuredMessage: EnsuredMessage,
        layoutName: str,
        question: str,
        typingManager: Optional[TypingManager],
        invokedVia: str,
        generateImage: Optional[bool] = None,
        isLLMCall: bool = False,
    ) -> Optional[str]:
        """Run the full reading pipeline for one user request.

        All input validation (system existence, layout resolution) is done by
        the caller (:meth:`_handleReadingFromArgs` for slash commands,
        :meth:`_runReadingForTool` for LLM tools). This method assumes a
        valid, resolved ``layout`` is passed in.

        Pipeline:
            1. Rate-limit check.
            2. Draw symbols and build :class:`Reading`.
            3. Build interpretation prompt and call ``LLMService.generateText``.
            4. Optionally generate a spread image.
            5. Send reply:
               - ``returnToolJson=False``: send text or photo+full-caption.
               - ``returnToolJson=True``: send photo (no caption) if image
                 succeeded; send nothing otherwise.
            6. Persist the divination row (best-effort; failure is logged).
            7. Return JSON summary when ``returnToolJson=True``, else ``""``.

        Args:
            systemId: Divination system id (``"tarot"`` / ``"runes"``).
            ensuredMessage: The originating user message.
            layoutName: Layout name to use for drawing.
            question: User question (may be ``""``).
            typingManager: Typing indicator manager (may be ``None``).
            invokedVia: Provenance for the DB row (``"command"`` or
                ``"llm_tool"``).
            generateImage: Explicit override for the image step. ``None``
                means "use the config default".
            isLLMCall: Whether this request originated from an LLM tool call.
                When ``True``, modifies reply sending behavior.

        Returns:
            ``None`` for slash-command path; JSON-encoded summary when
            ``isLLMCall`` is ``True``.
        """
        systemCls = self.systems.get(systemId)
        assert systemCls is not None, f"systemCls for '{systemId}' missing — caller must validate!"

        layout: Optional[Layout] = await self._getLayout(
            systemCls=systemCls,
            layoutName=layoutName,
            chatId=ensuredMessage.recipient.id,
            ensuredMessage=ensuredMessage,
            typingManager=typingManager,
        )
        if layout is None:
            if isLLMCall:
                return utils.jsonDumps({"done": False, "errorMessage": f"Unknown layout '{layoutName}'."})
            else:
                availableLayoutsStr = _formatLayoutsForHelp(systemCls)
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"Расклад '{layoutName}' не поддерживается.\n"
                    f"Доступные расклады: {availableLayoutsStr}.",
                    messageCategory=MessageCategory.BOT_ERROR,
                    typingManager=typingManager,
                )
                return None

        chatId: int = ensuredMessage.recipient.id

        # The wrappers guarantee systemCls is present; assert for safety.
        systemCls: Optional[Type[BaseDivinationSystem]] = self.systems.get(systemId)
        assert systemCls is not None, f"systemCls for '{systemId}' missing — caller must validate!"

        chatSettings = await self.getChatSettings(chatId=chatId)

        await self.llmService.rateLimit(chatId, chatSettings)

        # Resolve the image-generation flag: explicit override first,
        # otherwise the config default. Tool-callers always pass an explicit
        # value (True/False); slash commands pass None.
        wantImage: bool = self.imageGenerationDefault if generateImage is None else bool(generateImage)

        # Step 1 — draw symbols.
        draws = systemCls.draw(layout)
        logger.debug(f"Drew {draws} symbols for {layout}")

        reading: Reading = Reading(
            systemId=systemCls.systemId,
            deckId=systemCls.deckId,
            layout=layout,
            draws=draws,
            question=question,
            seed=None,
        )

        # Step 2 — build interpretation prompt and call the LLM.
        systemPromptKey: ChatSettingsKey = ChatSettingsKey.RUNES_SYSTEM_PROMPT
        match systemId:
            case TarotSystem.systemId:
                systemPromptKey = ChatSettingsKey.TAROT_SYSTEM_PROMPT
            case RunesSystem.systemId:
                systemPromptKey = ChatSettingsKey.RUNES_SYSTEM_PROMPT
            case _:
                raise ValueError(f"Unknown systemId '{systemId}'")

        messages = systemCls.buildInterpretationMessages(
            reading,
            userName=ensuredMessage.sender.name,
            systemPromptTemplate=chatSettings[systemPromptKey].toStr(),
            userPromptTemplate=chatSettings[ChatSettingsKey.DIVINATION_USER_PROMPT_TEMPLATE].toStr(),
            lang="ru",
        )

        if typingManager is not None:
            typingManager.action = TypingAction.TYPING
            await typingManager.sendTypingAction()

        llmRet = await self.llmService.generateText(
            messages,
            chatId=chatId,
            chatSettings=chatSettings,
            modelKey=ChatSettingsKey.CHAT_MODEL,
            fallbackKey=ChatSettingsKey.FALLBACK_MODEL,
        )
        if llmRet.status != ModelResultStatus.FINAL:
            if isLLMCall:
                return utils.jsonDumps(
                    {"done": False, "errorMessage": f"LLM interpretation failed: {llmRet.status.name}"}
                )
            await self.sendMessage(
                ensuredMessage,
                messageText="Не удалось получить интерпретацию расклада\n"
                f"```\n{llmRet.status}\n{llmRet.resultText}\n```",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return None

        interpretationText: str = llmRet.resultText or ""

        # Step 3 — image generation (optional).
        imagePromptForDb: Optional[str] = None
        imageBytes: Optional[bytes] = None
        imageFallback: bool = False

        originalAction: Optional[TypingAction] = None

        if wantImage:
            imagePrompt: str = systemCls.buildImagePrompt(
                reading, imagePromptTemplate=chatSettings[ChatSettingsKey.DIVINATION_IMAGE_PROMPT_TEMPLATE].toStr()
            )

            if typingManager is not None:
                originalAction = typingManager.action
                typingManager.action = TypingAction.UPLOAD_PHOTO
                # Image generation can take a while; bump the typing timeout
                # the same way MediaHandler does to keep the indicator alive.
                typingManager.addTimeout(300)
                await typingManager.sendTypingAction()

            try:
                imgRet = await self.llmService.generateImage(
                    imagePrompt,
                    chatId=chatId,
                    chatSettings=chatSettings,
                )
            except Exception as e:
                logger.error(f"Image generation raised: {e}")
                imgRet = None  # type: ignore[assignment]

            if imgRet is not None and imgRet.status == ModelResultStatus.FINAL and imgRet.mediaData is not None:
                imageBytes = bytes(imgRet.mediaData)
                imageFallback = bool(imgRet.isFallback)
                imagePromptForDb = imagePrompt
            else:
                logger.warning(
                    "Image generation failed (status=%s); falling back to text-only reply.",
                    None if imgRet is None else imgRet.status,
                )

        # Step 4 — send reply.
        if imageBytes is not None:
            # In case of image present, send it as separate message
            imgAddPrefix: str = chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr() if imageFallback else ""
            await self.sendMessage(
                ensuredMessage,
                photoData=imageBytes,
                mediaPrompt=imagePromptForDb,
                messageCategory=MessageCategory.BOT if isLLMCall else MessageCategory.BOT_COMMAND_REPLY,
                addMessagePrefix=imgAddPrefix,
                # typingManager=typingManager,
            )

        if typingManager is not None:
            typingManager.action = originalAction if originalAction is not None else TypingAction.TYPING
            await typingManager.sendTypingAction()

        if not isLLMCall:
            # Slash-command path: text part.
            await self.sendMessage(
                ensuredMessage,
                messageText=systemCls.renderReplyTemplate(
                    chatSettings[ChatSettingsKey.DIVINATION_REPLY_TEMPLATE].toStr(),
                    layoutName=layout.nameRu,
                    drawnSymbolsBlock=systemCls.renderDrawnSymbolsBlock(reading, lang="ru"),
                    interpretation=interpretationText,
                ),
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
        # Step 5 — persist (best-effort; failure must not block the reply).
        try:
            await self.db.divinations.insertReading(
                chatId=chatId,
                messageId=ensuredMessage.messageId,
                userId=ensuredMessage.sender.id,
                systemId=systemCls.systemId,
                deckId=systemCls.deckId,
                layoutId=layout.id,
                question=question,
                drawsJson=[
                    {
                        "symbolId": d.symbol.id,
                        "symbolName": d.symbol.name,
                        "reversed": d.reversed,
                        "position": d.position,
                        "positionIndex": d.positionIndex,
                    }
                    for d in reading.draws
                ],
                interpretation=interpretationText,
                imagePrompt=imagePromptForDb,
                invokedVia=invokedVia,
            )
        except Exception as e:
            logger.error(f"Failed to persist divination row: {e}")

        if isLLMCall:
            return utils.jsonDumps(
                {
                    "done": True,
                    "layout": {
                        "id": layout.id,
                        "en": layout.nameEn,
                        "ru": layout.nameRu,
                        "positions": layout.positions,
                    },
                    "draws": [
                        {
                            "nameEn": d.symbol.name,
                            "nameRu": divinationLocalization.tr(
                                divinationLocalization.SYMBOL_NAMES, d.symbol.name, "ru"
                            ),
                            "glyph": d.symbol.glyph,
                            "reversed": d.reversed,
                            "position": d.position,
                            "meaning": d.symbol.meaningUpright if not d.reversed else d.symbol.meaningReversed,
                        }
                        for d in reading.draws
                    ],
                    "interpretation": interpretationText,
                    "image_sent": imageBytes is not None,
                }
            )
        return None

    def _generateLayoutId(self, layoutName: str) -> str:
        """Generate a machine-readable layout ID from user input.

        Normalizes the layout name: lowercase, replaces spaces/dashes
        with underscores, removes special characters.

        Args:
            layoutName: User-provided layout name.

        Returns:
            Normalized layout ID suitable for database storage.
        """
        # Lowercase, normalize separators, remove special chars
        normalized = layoutName.lower().strip()
        normalized = re.sub(r"[\s\-_]+", "_", normalized)  # Various separators → "_"
        normalized = re.sub(r"[^a-z0-9_]", "", normalized)  # Remove other chars
        return normalized or "unknown"

    async def _getLayout(
        self,
        systemCls: Type[BaseDivinationSystem],
        layoutName: str,
        chatId: int,
        *,
        ensuredMessage: EnsuredMessage,
        typingManager: Optional[TypingManager] = None,
    ) -> Optional[Layout]:
        """Resolve a layout from predefined layouts, cache, or discover via web search.

        This method consolidates the layout resolution and discovery logic into a
        single helper. It first tries to resolve from predefined layouts, then checks
        the database cache (if discovery is enabled), and finally attempts to
        discover the layout via web search if no cache entry exists.

        Args:
            systemCls: Concrete divination system class (e.g. TarotSystem, RunesSystem).
            layoutName: User-provided layout name to resolve.
            chatId: Chat ID for rate limiting and settings.
            ensuredMessage: The originating user message for error replies.
            typingManager: Typing indicator manager (may be ``None``).

        Returns:
            Resolved Layout object if found, None otherwise (caller handles error).

        Note:
            The canonical layout ID for caching is generated from the user's
            original input (after normalization) and is used consistently for
            both cache lookups and storage. This ensures cache consistency.
        """
        # Step 1: Try to resolve from predefined layouts
        resolvedLayout: Optional[Layout] = systemCls.resolveLayout(layoutName)
        if resolvedLayout is not None:
            return resolvedLayout

        # Step 2: If discovery is disabled, layout not found
        if not self.discoveryEnabled:
            logger.debug(f"Layout '{layoutName}' not found and discovery disabled for {systemCls.systemId}")
            return None

        # Step 3: Generate canonical cache key from user input
        # This key will be used for both lookup and storage to ensure consistency
        canonicalLayoutId: str = self._generateLayoutId(layoutName)

        # Step 4: Check database cache using multiple search strategies
        # Pass both canonical ID and original user input for best match chances
        cachedLayout: Optional[DivinationLayoutDict] = await self.db.divinations.getLayout(
            systemId=systemCls.systemId, layoutName=[canonicalLayoutId, layoutName]
        )

        # Step 5: If negative cache entry found, return None
        if cachedLayout is not None and self.db.divinations.isNegativeCacheEntry(cachedLayout):
            logger.debug(
                f"Layout discovery blocked: negative cache entry for '{layoutName}' "
                f"(canonical key: '{canonicalLayoutId}', found key: '{cachedLayout.get('layout_id')}') "
                f"in {systemCls.systemId}"
            )
            return None

        # Step 6: If valid cache entry found, reconstruct Layout object
        if cachedLayout is not None:
            positions = tuple(cachedLayout["positions"])
            discoveredLayout = Layout(
                id=cachedLayout["layout_id"],
                nameEn=cachedLayout["name_en"],
                nameRu=cachedLayout["name_ru"],
                positions=positions,
                aliases=(),  # No aliases for discovered layouts
                systemId=cachedLayout["system_id"],
            )
            logger.debug(
                f"Cache hit for layout '{layoutName}' "
                f"(canonical key: '{canonicalLayoutId}', matched key: '{cachedLayout.get('layout_id')}', "
                f"name: '{cachedLayout.get('name_en')}') in {systemCls.systemId}"
            )
            return discoveredLayout

        # Step 7: No cache entry - try to discover layout via web search
        logger.debug(
            f"Cache miss: attempting web search discovery for '{layoutName}' "
            f"(canonical key: '{canonicalLayoutId}') in {systemCls.systemId}"
        )
        discoveredLayout: Optional[Layout] = await self._discoverLayoutWithLLM(
            systemCls=systemCls,
            layoutName=layoutName,
            canonicalLayoutId=canonicalLayoutId,
            chatId=chatId,
            ensuredMessage=ensuredMessage,
            typingManager=typingManager,
        )

        if discoveredLayout is not None:
            logger.info(
                f"Discovery success: found layout '{layoutName}' "
                f"(canonical key: '{canonicalLayoutId}', system: {systemCls.systemId})"
            )
            # Save to database using the canonical layout ID
            await self.db.divinations.saveLayout(
                systemId=discoveredLayout.systemId,
                layoutId=canonicalLayoutId,
                nameEn=discoveredLayout.nameEn,
                nameRu=discoveredLayout.nameRu,
                nSymbols=len(discoveredLayout.positions),
                positions=discoveredLayout.positions,
                description=discoveredLayout.description or "",
            )
        else:
            logger.info(
                f"Discovery failed: unable to find layout '{layoutName}' "
                f"(canonical key: '{canonicalLayoutId}', system: {systemCls.systemId}) "
                f"- saving negative cache entry (24h TTL)"
            )
            await self.db.divinations.saveNegativeCache(
                systemId=systemCls.systemId,
                layoutId=canonicalLayoutId,
            )

        return discoveredLayout

    async def _discoverLayoutWithLLM(
        self,
        systemCls: Type[BaseDivinationSystem],
        layoutName: str,
        canonicalLayoutId: str,
        chatId: int,
        *,
        ensuredMessage: EnsuredMessage,
        typingManager: Optional[TypingManager] = None,
    ) -> Optional[Layout]:
        """Discover layout using web search, then call _extractLayoutFromText.

        This is a convenience wrapper that:
        1. Calls LLM with tools enabled to get layout description via web search
        2. Delegates to _extractLayoutFromText with the description

        Args:
            systemCls: The divination system class.
            layoutName: Raw user-provided layout name.
            canonicalLayoutId: Normalized layout ID for cache consistency.
            chatId: Chat ID for rate limiting and settings.
            ensuredMessage: The originating user message for error replies.
            typingManager: Typing indicator manager (may be ``None``).

        Returns:
            Discovered Layout if successful, None otherwise.
        """
        # Get prompts from chat settings
        chatSettings = await self.getChatSettings(chatId=chatId)

        # Build messages for info discovery with tools
        infoMessages = [
            ModelMessage(
                role="system",
                content=chatSettings[ChatSettingsKey.DIVINATION_DISCOVERY_SYSTEM_PROMPT].toStr(),
            ),
            ModelMessage(
                role="user",
                content=chatSettings[ChatSettingsKey.DIVINATION_DISCOVERY_INFO_PROMPT]
                .toStr()
                .format(
                    layoutName=layoutName,
                    systemId=systemCls.systemId,
                ),
            ),
        ]

        try:
            # Call LLM with tools enabled (web_search)
            logger.debug(
                f"Starting discovery LLM call 1/2 (web search) for '{layoutName}' "
                f"(key: '{canonicalLayoutId}', system: {systemCls.systemId})"
            )
            infoRet = await self.llmService.generateTextViaLLM(
                messages=infoMessages,
                chatId=chatId,
                chatSettings=chatSettings,
                modelKey=ChatSettingsKey.CHAT_MODEL,
                fallbackModelKey=ChatSettingsKey.FALLBACK_MODEL,
                useTools=True,  # Enable tools for web search
                extraData={
                    "ensuredMessage": ensuredMessage,
                    "typingManager": typingManager,
                },
            )
        except Exception as e:
            logger.error(
                f"Discovery LLM call 1/2 (web search) failed for '{layoutName}' "
                f"(key: '{canonicalLayoutId}', system: {systemCls.systemId}): {e}"
            )
            return None

        if infoRet.status != ModelResultStatus.FINAL or not infoRet.resultText:
            logger.warning(
                f"Discovery LLM call 1/2 (web search) returned non-final for '{layoutName}' "
                f"(key: '{canonicalLayoutId}', status: {infoRet.status})"
            )
            return None

        # Now call _extractLayoutFromText with the description
        return await self._extractLayoutFromText(
            systemCls=systemCls,
            layoutName=layoutName,
            canonicalLayoutId=canonicalLayoutId,
            chatId=chatId,
            layoutDescription=infoRet.resultText,
        )

    async def _extractLayoutFromText(
        self,
        systemCls: Type[BaseDivinationSystem],
        layoutName: str,
        canonicalLayoutId: str,
        chatId: int,
        layoutDescription: str,
    ) -> Optional[Layout]:
        """Discover an unknown layout using LLM with web search.

        Discovery process:
        1. Call LLM with web_search tool enabled to find layout information (already have layoutDescription)
        2. Call LLM.generateStructured() to parse description into Layout object
        3. Validate and return Layout object with canonical layout ID

        Args:
            systemCls: The divination system class (TarotSystem or RunesSystem).
            layoutName: Raw user-provided layout name.
            canonicalLayoutId: Normalized layout ID for cache consistency.
            chatId: Chat ID for rate limiting and settings.
            layoutDescription: Description from first LLM call with web search.

        Returns:
            Discovered Layout if successful, None otherwise.

        Note:
            The Layout object's id field is set to canonicalLayoutId to ensure
            cache consistency. The LLM-provided layout_id is discarded in favor
            of the canonical ID derived from user input.
        """
        # Get prompts from chat settings
        chatSettings = await self.getChatSettings(chatId=chatId)

        # Build messages for structured output call
        structureMessages = [
            ModelMessage(
                role="system",
                content=chatSettings[ChatSettingsKey.DIVINATION_PARSE_STRUCTURE_SYSTEM_PROMPT].toStr(),
            ),
            ModelMessage(
                role="user",
                content=chatSettings[ChatSettingsKey.DIVINATION_PARSE_STRUCTURE_PROMPT]
                .toStr()
                .format(
                    layoutName=layoutName,
                    systemId=systemCls.systemId,
                    description=layoutDescription,
                ),
            ),
        ]

        try:
            # Call LLM with structured output
            logger.debug(
                f"Starting discovery LLM call 2/2 (structured parse) for '{layoutName}' "
                f"(key: '{canonicalLayoutId}', system: {systemCls.systemId})"
            )
            structuredRet = await self.llmService.generateStructured(
                prompt=structureMessages,
                schema={
                    "type": "object",
                    "properties": {
                        "layout_id": {"type": "string"},
                        "name_en": {"type": "string"},
                        "name_ru": {"type": "string"},
                        "positions": {
                            "type": "array",
                            "items": {
                                "type": "string",
                            },
                        },
                        "description": {"type": "string"},
                    },
                    "required": ["layout_id", "name_en", "name_ru", "positions", "description"],
                    "additionalProperties": False,
                },
                chatId=chatId,
                chatSettings=chatSettings,
                modelKey=ChatSettingsKey.CHAT_MODEL,
                fallbackKey=ChatSettingsKey.FALLBACK_MODEL,
            )
            jsonRet: Optional[Dict[str, Any]] = structuredRet.data
        except Exception as e:
            logger.error(
                f"Discovery LLM call 2/2 (structured parse) failed for '{layoutName}' "
                f"(key: '{canonicalLayoutId}', system: {systemCls.systemId}): {e}"
            )
            return None

        # Check if we got a valid structured result
        if structuredRet.status != ModelResultStatus.FINAL or jsonRet is None:
            logger.warning(
                f"Discovery LLM call 2/2 (structured parse) returned non-final or missing data "
                f"for '{layoutName}' (key: '{canonicalLayoutId}', status: {structuredRet.status})"
            )
            return None

        if not isinstance(jsonRet, dict):
            logger.warning(f"LLM generateStructured.data returned unexpected type: {type(structuredRet.data)}")
            return None

        # Validate required fields
        requiredFields = ["layout_id", "name_en", "name_ru", "positions"]
        for field in requiredFields:
            if field not in jsonRet:
                logger.error(f"Discovered layout missing field: {field}")
                return None

        if not isinstance(jsonRet["positions"], list) or len(jsonRet["positions"]) == 0:
            logger.error("Discovered layout has invalid positions list")
            return None

        # Construct Layout object using the canonical layout ID for cache consistency
        discoveredLayout = Layout(
            id=canonicalLayoutId,
            nameEn=jsonRet["name_en"],
            nameRu=jsonRet["name_ru"],
            positions=tuple(jsonRet["positions"]),
            aliases=(),
            systemId=systemCls.systemId,
            description=utils.jsonDumps({"full": layoutDescription, "short": jsonRet.get("description")}),
        )

        logger.info(f"Successfully discovered layout: {systemCls.systemId}/{canonicalLayoutId}")

        return discoveredLayout
