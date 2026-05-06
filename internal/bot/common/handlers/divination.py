"""Tarot and runes divination handler for the Gromozeka bot, dood!

This module wires :class:`lib.divination.TarotSystem` and
:class:`lib.divination.RunesSystem` to two slash commands (``/taro`` and
``/runes``) and, when ``divination.tools-enabled`` is on, to two LLM tools
(``do_tarot_reading`` and ``do_runes_reading``).

The handler owns the bot/LLM/DB orchestration: parsing user input, drawing
symbols via the divination library, calling :class:`LLMService` for
interpretation and (optionally) image generation, sending the reply, and
persisting the reading via :class:`DivinationsRepository`. It is the only
seam between :mod:`lib.divination` (pure logic) and the bot internals,
dood!
"""

import logging
from typing import Any, Dict, Optional, Tuple, Type

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
from internal.database.models import MessageCategory
from lib.ai import (
    LLMFunctionParameter,
    LLMManager,
    LLMParameterType,
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
        " `<layout>` `[question]`: Раскинуть карты Таро, dood!\n"
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
        " `<layout>` `[question]`: Раскинуть руны, dood!\n"
        f"Доступные расклады: {layoutsList}.\n"
        "Расклад указывать ОБЯЗАТЕЛЬНО."
    )


class DivinationHandler(BaseBotHandler):
    """Tarot and runes divination handler, dood!

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
    """

    def __init__(
        self,
        configManager: ConfigManager,
        database: Database,
        llmManager: LLMManager,
        botProvider: BotProvider,
    ) -> None:
        """Initialise the divination handler, dood!

        Args:
            configManager: Configuration manager providing the ``divination``
                section.
            database: Database wrapper used to persist readings.
            llmManager: LLM manager forwarded to :class:`LLMService` calls.
            botProvider: Bot provider type (Telegram / Max).

        Raises:
            RuntimeError: If ``divination.enabled`` is False — the handler
                must not be constructed in that case (the registration site
                in :class:`HandlersManager` is the gate).
        """
        super().__init__(
            configManager=configManager,
            database=database,
            llmManager=llmManager,
            botProvider=botProvider,
        )

        self.config: Dict[str, Any] = self.configManager.get("divination", {}) or {}
        if not self.config.get("enabled", False):
            logger.error("Divination is not enabled, can not load DivinationHandler, dood!")
            raise RuntimeError("Divination is not enabled, can not load DivinationHandler")

        self.systems: Dict[str, Type[BaseDivinationSystem]] = {}
        if self.config.get("tarot-enabled", True):
            self.systems[TarotSystem.systemId] = TarotSystem
        if self.config.get("runes-enabled", True):
            self.systems[RunesSystem.systemId] = RunesSystem

        self.imageGenerationDefault: bool = bool(self.config.get("image-generation", True))

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
            tarotLayoutsList: str = ", ".join(layout.id for layout in TarotSystem.availableLayouts())
            self.llmService.registerTool(
                name="do_tarot_reading",
                description=(
                    "Perform a tarot reading using the Rider-Waite-Smith deck for the user. "
                    "Use this when the user asks for a tarot reading, fortune, or to draw cards."
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
                        description=(
                            "Layout id. One of: "
                            f"{tarotLayoutsList}. "
                            f"Defaults to {_DEFAULT_TAROT_LAYOUT_ID} if omitted."
                        ),
                        type=LLMParameterType.STRING,
                        required=False,
                    ),
                    LLMFunctionParameter(
                        name="generate_image",
                        description="Whether to also generate a spread illustration. Defaults to false.",
                        type=LLMParameterType.BOOLEAN,
                        required=False,
                    ),
                ],
                handler=self._llmToolDoTarotReading,
            )

        if RunesSystem.systemId in self.systems:
            runesLayoutsList: str = ", ".join(layout.id for layout in RunesSystem.availableLayouts())
            self.llmService.registerTool(
                name="do_runes_reading",
                description=(
                    "Perform an Elder Futhark runic reading for the user. "
                    "Use this when the user asks for a runic reading, fortune, or to cast runes."
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
                        description=(
                            "Layout id. One of: "
                            f"{runesLayoutsList}. "
                            f"Defaults to {_DEFAULT_RUNES_LAYOUT_ID} if omitted."
                        ),
                        type=LLMParameterType.STRING,
                        required=False,
                    ),
                    LLMFunctionParameter(
                        name="generate_image",
                        description="Whether to also generate a spread illustration. Defaults to false.",
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
        """Handle the ``/taro`` slash command, dood!

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
        """Handle the ``/runes`` slash command, dood!

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
        extraData: Optional[Dict[str, Any]],
        question: str,
        layout: Optional[str] = None,
        generate_image: bool = False,
        **kwargs: Any,
    ) -> str:
        """LLM tool handler that performs a tarot reading, dood!

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
        extraData: Optional[Dict[str, Any]],
        question: str,
        layout: Optional[str] = None,
        generate_image: bool = False,
        **kwargs: Any,
    ) -> str:
        """LLM tool handler that performs a runic reading, dood!

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
        extraData: Optional[Dict[str, Any]],
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
        if extraData is None:
            return utils.jsonDumps({"done": False, "errorMessage": "Missing tool context, dood!"})

        ensuredMessage = extraData.get("ensuredMessage")
        if not isinstance(ensuredMessage, EnsuredMessage):
            return utils.jsonDumps(
                {"done": False, "errorMessage": "Missing or invalid ensuredMessage in tool context, dood!"}
            )

        typingManager = extraData.get("typingManager")
        if typingManager is not None and not isinstance(typingManager, TypingManager):
            return utils.jsonDumps({"done": False, "errorMessage": "Invalid typingManager in tool context, dood!"})

        systemCls: Optional[Type[BaseDivinationSystem]] = self.systems.get(systemId)
        if systemCls is None:
            return utils.jsonDumps({"done": False, "errorMessage": f"Система '{systemId}' не доступна, dood!"})

        layoutName: str = (layout or "").strip() or defaultLayoutId

        resolvedLayout: Optional[Layout] = systemCls.resolveLayout(layoutName)
        if resolvedLayout is None:
            return utils.jsonDumps({"done": False, "errorMessage": f"Unknown layout '{layoutName}'."})

        return await self._handleReading(
            systemId=systemId,
            ensuredMessage=ensuredMessage,
            layout=resolvedLayout,
            question=question,
            typingManager=typingManager,
            invokedVia="llm_tool",
            generateImage=generateImage,
            returnToolJson=True,
        )

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
    ) -> str:
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
            errorMessage: str = f"Система '{systemId}' не доступна, dood!"
            await self.sendMessage(
                ensuredMessage,
                messageText=errorMessage,
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return ""

        availableLayoutsStr: str = _formatLayoutsForHelp(systemCls)
        layoutName, question = self._parseArgs(args)

        if not layoutName:
            errorMessage = "Необходимо указать расклад, dood!\n" f"Доступные расклады: {availableLayoutsStr}."
            await self.sendMessage(
                ensuredMessage,
                messageText=errorMessage,
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return ""

        layout: Optional[Layout] = systemCls.resolveLayout(layoutName)
        if layout is None:
            # NOTE: structured-output stub `_llmGetUnknownLayoutShape` is not
            # used in v1; keep the call site here for documentation but do
            # not invoke the stub (it always returns None anyway).
            errorMessage = (
                f"Расклад '{layoutName}' не поддерживается, dood!\n" f"Доступные расклады: {availableLayoutsStr}."
            )
            await self.sendMessage(
                ensuredMessage,
                messageText=errorMessage,
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return ""

        return await self._handleReading(
            systemId=systemId,
            ensuredMessage=ensuredMessage,
            layout=layout,
            question=question,
            typingManager=typingManager,
            invokedVia=invokedVia,
            generateImage=None,
            returnToolJson=False,
        )

    async def _handleReading(
        self,
        *,
        systemId: str,
        ensuredMessage: EnsuredMessage,
        layout: Layout,
        question: str,
        typingManager: Optional[TypingManager],
        invokedVia: str,
        generateImage: Optional[bool] = None,
        returnToolJson: bool = False,
    ) -> str:
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
            layout: Resolved :class:`Layout` object to use for drawing.
            question: User question (may be ``""``).
            typingManager: Typing indicator manager (may be ``None``).
            invokedVia: Provenance for the DB row (``"command"`` or
                ``"llm_tool"``).
            generateImage: Explicit override for the image step. ``None``
                means "use the config default".
            returnToolJson: When ``True``, return a JSON-encoded summary
                string suitable for an LLM tool result and suppress the
                text-interpretation message to the user; otherwise return
                ``""``.

        Returns:
            JSON-encoded summary when ``returnToolJson`` is ``True``, else
            an empty string.
        """
        chatId: int = ensuredMessage.recipient.id

        # The wrappers guarantee systemCls is present; assert for safety.
        systemCls: Optional[Type[BaseDivinationSystem]] = self.systems.get(systemId)
        assert systemCls is not None, f"systemCls for '{systemId}' missing — caller must validate, dood!"

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
        if systemId == TarotSystem.systemId:
            systemPromptKey = ChatSettingsKey.TAROT_SYSTEM_PROMPT
        else:
            systemPromptKey = ChatSettingsKey.RUNES_SYSTEM_PROMPT

        systemPromptTemplate: str = chatSettings[systemPromptKey].toStr()
        userPromptTemplate: str = chatSettings[ChatSettingsKey.DIVINATION_USER_PROMPT_TEMPLATE].toStr()
        imagePromptTemplate: str = chatSettings[ChatSettingsKey.DIVINATION_IMAGE_PROMPT_TEMPLATE].toStr()

        messages = systemCls.buildInterpretationMessages(
            reading,
            userName=ensuredMessage.sender.name,
            systemPromptTemplate=systemPromptTemplate,
            userPromptTemplate=userPromptTemplate,
            lang="ru",
        )

        if typingManager is not None:
            typingManager.action = TypingAction.TYPING
            await typingManager.sendTypingAction()

        llmRet = await self.llmService.generateText(
            messages,
            chatId=chatId,
            chatSettings=chatSettings,
            llmManager=self.llmManager,
            modelKey=ChatSettingsKey.CHAT_MODEL,
            fallbackKey=ChatSettingsKey.FALLBACK_MODEL,
        )
        if llmRet.status != ModelResultStatus.FINAL:
            errorMessage: str = (
                "Не удалось получить интерпретацию расклада, dood!\n" f"```\n{llmRet.status}\n{llmRet.resultText}\n```"
            )
            await self.sendMessage(
                ensuredMessage,
                messageText=errorMessage,
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            if returnToolJson:
                return utils.jsonDumps(
                    {"done": False, "errorMessage": f"LLM interpretation failed: {llmRet.status.name}"}
                )
            return ""

        interpretationText: str = llmRet.resultText or ""

        # Step 2b — assemble user-visible text for the slash-command path.
        # The tool path returns the bare interpretation in JSON; only the
        # slash-command path wraps it in the structured reply template so
        # users can verify the drawn symbols against the LLM output.
        if returnToolJson:
            userVisibleText: str = interpretationText
        else:
            drawnBlock: str = systemCls.renderDrawnSymbolsBlock(reading, lang="ru")
            layoutNameRu: str = layout.nameRu
            replyTemplate: str = chatSettings[ChatSettingsKey.DIVINATION_REPLY_TEMPLATE].toStr()
            userVisibleText = systemCls.renderReplyTemplate(
                replyTemplate,
                layoutName=layoutNameRu,
                drawnSymbolsBlock=drawnBlock,
                interpretation=interpretationText,
            )

        # Step 3 — image generation (optional).
        imagePromptForDb: Optional[str] = None
        imageBytes: Optional[bytes] = None
        imageFallback: bool = False

        if wantImage:
            imagePrompt: str = systemCls.buildImagePrompt(reading, imagePromptTemplate=imagePromptTemplate)

            originalAction: Optional[TypingAction] = None
            if typingManager is not None:
                originalAction = typingManager.action
                typingManager.action = TypingAction.UPLOAD_PHOTO
                # Image generation can take a while; bump the typing timeout
                # the same way MediaHandler does to keep the indicator alive.
                typingManager.maxTimeout = typingManager.maxTimeout + 300
                await typingManager.sendTypingAction()

            try:
                imgRet = await self.llmService.generateImage(
                    imagePrompt,
                    chatId=chatId,
                    chatSettings=chatSettings,
                    llmManager=self.llmManager,
                )
            except Exception as e:
                logger.error(f"Image generation raised, dood: {e}")
                imgRet = None  # type: ignore[assignment]

            if imgRet is not None and imgRet.status == ModelResultStatus.FINAL and imgRet.mediaData is not None:
                imageBytes = bytes(imgRet.mediaData)
                imageFallback = bool(imgRet.isFallback)
                imagePromptForDb = imagePrompt
            else:
                logger.warning(
                    "Image generation failed (status=%s); falling back to text-only reply, dood!",
                    None if imgRet is None else imgRet.status,
                )

            if typingManager is not None:
                typingManager.action = originalAction if originalAction is not None else TypingAction.TYPING
                await typingManager.sendTypingAction()

        # Step 4 — send reply.
        imgAddPrefix = chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr() if imageFallback else ""
        if imageBytes is not None:
            # In case of image present, send it as separate message
            await self.sendMessage(
                ensuredMessage,
                photoData=imageBytes,
                mediaPrompt=imagePromptForDb,
                messageCategory=MessageCategory.BOT if returnToolJson else MessageCategory.BOT_COMMAND_REPLY,
                addMessagePrefix=imgAddPrefix,
                typingManager=typingManager,
            )
        if not returnToolJson:
            # Slash-command path: text part.
            # userVisibleText is the structured reply (template-rendered);
            # interpretationText (bare LLM output) stays in the DB only.
            await self.sendMessage(
                ensuredMessage,
                messageText=userVisibleText,
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
            logger.error(f"Failed to persist divination row: {e}, dood!")

        if returnToolJson:
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
                            "nameRu": d.symbol.name,
                            "reversed": d.reversed,
                            "position": d.position,
                            "meaning": d.symbol.meaningUpright if not d.reversed else d.symbol.meaningReversed,
                        }
                        for d in reading.draws
                    ],
                    "interpretation": interpretationText,
                }
            )
        return ""

    async def _llmGetUnknownLayoutShape(
        self,
        systemCls: Type[BaseDivinationSystem],
        layoutName: str,
    ) -> Optional[Layout]:
        """Stub for the future structured-output unknown-layout flow, dood!

        ``lib/ai`` does not yet support structured/JSON output, so this
        method is intentionally a no-op. It exists so the integration point
        is visible in the codebase: once structured output lands, this
        method will ask the LLM for ``{nCards, positions}`` and synthesise
        an ad-hoc :class:`Layout`.

        Args:
            systemCls: Divination system requesting the layout.
            layoutName: Raw user-supplied layout name.

        Returns:
            Always ``None`` in v1.
        """
        logger.info(
            "Unknown layout '%s' for %s: structured output not supported yet, dood!",
            layoutName,
            systemCls.systemId,
        )
        return None
