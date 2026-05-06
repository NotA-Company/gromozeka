"""Core types for the divination library, dood!

This module defines the building blocks shared by every divination system:

* :class:`Symbol` — a single deck entry (tarot card, rune, …).
* :class:`DrawnSymbol` — a single positioned draw within a reading.
* :class:`Reading` — the full result of one reading.
* :class:`BaseDivinationSystem` — abstract base class systems implement.

Only one cross-tree import is allowed in the divination library, dood!
``from lib.ai import ModelMessage`` for prompt assembly. Everything else
stays inside :mod:`lib.divination`.
"""

import abc
import logging
import random
import string
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, ClassVar, List, Mapping, Optional, Sequence, Tuple

from lib.ai import ModelMessage

from . import localization
from .layouts import Layout, resolveLayout

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Symbol:
    """A single symbol in a deck (tarot card or rune), dood!

    Attributes:
        id: Stable machine identifier (e.g. ``"major_00_fool"``,
            ``"rune_fehu"``). Unique across a single deck.
        name: English name (source of truth, e.g. ``"The Fool"``, ``"Fehu"``).
            Localised forms come from :mod:`lib.divination.localization`.
        meaningUpright: Short English upright meaning, used as a hint in the
            interpretation prompt. The LLM does the actual interpretation in
            the user's language.
        meaningReversed: Short English reversed meaning, or ``None`` when the
            system does not use reversals (e.g. runes).
        imagePromptFragment: Short English visual description that will be
            embedded into the spread's image-generation prompt.
        glyph: The Unicode visual character for this symbol (e.g. ``"ᚠ"`` for
            Fehu). Optional — ``None`` for systems without a single canonical
            glyph (e.g. tarot cards). When present, used as a visual lead-in
            in user-facing reply lines.
        metadata: Free-form extra fields (suit, number, aett, element, …).
    """

    id: str
    name: str
    meaningUpright: str
    meaningReversed: Optional[str]
    imagePromptFragment: str
    glyph: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DrawnSymbol:
    """A single draw result within a reading.

    Attributes:
        symbol: The :class:`Symbol` that was drawn.
        reversed: ``True`` when the symbol was drawn in reversed orientation
            (always ``False`` for systems with ``supportsReversed=False``).
        position: English layout position name, e.g. ``"Past"``.
        positionIndex: Zero-based index of this draw inside the layout.
    """

    symbol: Symbol
    reversed: bool
    position: str
    positionIndex: int


@dataclass(frozen=True, slots=True)
class Reading:
    """A complete reading result, dood!

    Attributes:
        systemId: Identifier of the divination system used (``"tarot"`` /
            ``"runes"`` / …).
        deckId: Identifier of the deck used (``"rws"`` / ``"elder_futhark"`` /
            …).
        layout: The :class:`Layout` used for the reading.
        draws: Ordered tuple of :class:`DrawnSymbol`, length equal to
            ``layout.numSymbols``.
        question: User's question (may be empty).
        seed: Optional RNG seed for reproducibility (stored in DB by callers).
    """

    systemId: str
    deckId: str
    layout: Layout
    draws: Tuple[DrawnSymbol, ...]
    question: str
    seed: Optional[int]


class _SafeFormatDict(defaultdict):
    """A ``defaultdict``-style mapping for :func:`str.format_map`, dood!

    Returns an empty string for any key that has not been explicitly set. Used
    by :func:`_safeFormat` so prompt templates with optional placeholders (or
    typoed placeholders!) render to an empty value instead of raising
    ``KeyError``.
    """

    def __missing__(self, key: str) -> str:
        """Return an empty string for any unknown placeholder.

        Logs a warning so operators notice typos in their configured
        templates instead of silently producing empty sections, dood.

        Args:
            key: Placeholder name that was not provided.

        Returns:
            Empty string.
        """
        logger.warning("Divination template placeholder '{%s}' not provided — substituting empty string, dood!", key)
        return ""


def _safeFormat(template: str, **kwargs: Any) -> str:
    """Format ``template`` while tolerating missing placeholders, dood!

    Uses :class:`string.Formatter` with a defaulting mapping so unknown keys
    become empty strings rather than raising ``KeyError``. This lets operators
    omit optional placeholders such as ``{styleHint}`` from their templates
    without breaking rendering.

    Args:
        template: Format string with ``{name}`` placeholders.
        **kwargs: Values for the named placeholders.

    Returns:
        The rendered string with any unknown placeholders replaced by ``""``.
    """
    mapping: _SafeFormatDict = _SafeFormatDict(str)
    for key, value in kwargs.items():
        mapping[key] = "" if value is None else str(value)
    return string.Formatter().vformat(template, (), mapping)


class BaseDivinationSystem(abc.ABC):
    """Abstract base class for divination systems (tarot, runes, …), dood!

    Subclasses are expected to set :attr:`systemId`, :attr:`deckId`,
    :attr:`supportsReversed` and :attr:`deck` as class variables, and override
    :meth:`availableLayouts` to return the layouts they support.

    Note:
        This class lives in :mod:`lib.divination` and depends only on
        :mod:`lib.ai` (for :class:`ModelMessage`). It MUST NOT import from
        ``internal/`` — see ``test_imports.py``.
    """

    systemId: ClassVar[str]
    deckId: ClassVar[str]
    supportsReversed: ClassVar[bool]
    deck: ClassVar[Tuple[Symbol, ...]]

    @classmethod
    @abc.abstractmethod
    def availableLayouts(cls) -> Sequence[Layout]:
        """Return the layouts this system supports.

        Returns:
            A sequence of :class:`Layout` objects (typically a module-level
            tuple shared across calls).
        """

    @classmethod
    def resolveLayout(cls, name: str) -> Optional[Layout]:
        """Resolve a user-typed layout name to a known :class:`Layout`.

        Matching is case- and separator-insensitive against every alias and
        each layout's ``id`` for this system's :meth:`availableLayouts`.

        Args:
            name: Raw user-supplied layout name.

        Returns:
            Matched :class:`Layout`, or ``None`` if no candidate matched.
        """
        return resolveLayout(name, layouts=cls.availableLayouts())

    @classmethod
    def draw(
        cls,
        layout: Layout,
        *,
        rng: Optional[random.Random] = None,
    ) -> Tuple[DrawnSymbol, ...]:
        """Draw the symbols required by ``layout`` from this system's deck.

        Delegates to :func:`lib.divination.drawing.drawSymbols`.

        Args:
            layout: Layout describing how many symbols to draw.
            rng: Optional injected RNG. Production uses ``random.SystemRandom``
                via the default; tests pin a seeded ``random.Random`` for
                determinism.

        Returns:
            Tuple of :class:`DrawnSymbol` of length ``layout.numSymbols``.
        """
        # Local import to avoid cycles between base.py and drawing.py.
        from .drawing import drawSymbols

        return drawSymbols(
            cls.deck,
            layout,
            supportsReversed=cls.supportsReversed,
            rng=rng,
        )

    @classmethod
    def buildInterpretationMessages(
        cls,
        reading: Reading,
        *,
        userName: str,
        systemPromptTemplate: str,
        userPromptTemplate: str,
        lang: str = "ru",
    ) -> List[ModelMessage]:
        """Build LLM input messages for the reading's interpretation, dood!

        Returns a two-message conversation: one ``"system"`` message holding
        the operator-supplied system prompt verbatim, followed by one
        ``"user"`` message rendered from ``userPromptTemplate`` with
        placeholders filled in.

        Supported placeholders in ``userPromptTemplate``:

        * ``{userName}`` — display name of the requesting user.
        * ``{question}`` — the user's question (may be empty).
        * ``{layoutName}`` — the layout's localised display name.
        * ``{positionsBlock}`` — numbered list of localised position names.
        * ``{cardsBlock}`` — numbered list of
          ``"<position> — <localizedSymbolName>[ (reversed)]: <meaning>"``
          lines, where the meaning is the English upright/reversed text from
          the deck (the LLM translates as needed).

        Symbol names and positions are localised via
        :func:`lib.divination.localization.tr`.

        Args:
            reading: The :class:`Reading` to interpret.
            userName: Display name of the requesting user.
            systemPromptTemplate: System prompt copy (rendered as-is via
                :func:`_safeFormat` to tolerate stray placeholders).
            userPromptTemplate: User-message template with the placeholders
                listed above.
            lang: BCP-47-style language code for localisation. Defaults to
                ``"ru"``.

        Returns:
            A list of two :class:`ModelMessage` objects: ``system`` then
            ``user``.
        """
        layoutName: str = localization.tr(localization.LAYOUT_NAMES, reading.layout.nameEn, lang)

        positionLines: List[str] = []
        for index, position in enumerate(reading.layout.positions, start=1):
            localizedPosition: str = localization.tr(localization.POSITION_NAMES, position, lang)
            positionLines.append(f"{index}. {localizedPosition}")
        positionsBlock: str = "\n".join(positionLines)

        cardLines: List[str] = []
        for index, draw in enumerate(reading.draws, start=1):
            localizedSymbol: str = localization.tr(localization.SYMBOL_NAMES, draw.symbol.name, lang)
            localizedPosition = localization.tr(localization.POSITION_NAMES, draw.position, lang)
            reversedTag: str = " (reversed)" if draw.reversed else ""
            meaning: str
            if draw.reversed and draw.symbol.meaningReversed is not None:
                meaning = draw.symbol.meaningReversed
            else:
                meaning = draw.symbol.meaningUpright
            cardLines.append(f"{index}. {localizedPosition} — {localizedSymbol}{reversedTag}: {meaning}")
        cardsBlock: str = "\n".join(cardLines)

        renderedSystem: str = _safeFormat(
            systemPromptTemplate,
            userName=userName,
            question=reading.question,
            layoutName=layoutName,
            positionsBlock=positionsBlock,
            cardsBlock=cardsBlock,
        )
        renderedUser: str = _safeFormat(
            userPromptTemplate,
            userName=userName,
            question=reading.question,
            layoutName=layoutName,
            positionsBlock=positionsBlock,
            cardsBlock=cardsBlock,
        )

        return [
            ModelMessage(role="system", content=renderedSystem),
            ModelMessage(role="user", content=renderedUser),
        ]

    @classmethod
    def renderDrawnSymbolsBlock(cls, reading: Reading, *, lang: str = "ru") -> str:
        """Render a localized, numbered list of drawn symbols, dood!

        Each line has the shape
        ``"<n>. <localized position> — [<glyph> ]<localized name>[ (перевёрнута)]"``
        where the optional glyph prefix (a Unicode character followed by a
        space) is included when :attr:`Symbol.glyph` is non-empty, and the
        reversal suffix is appended only for symbols whose ``reversed`` flag
        is ``True`` (which only happens for systems with
        ``supportsReversed=True``).

        Note:
            In practice, reversals only occur for tarot cards. The suffix
            ``(перевёрнута)`` uses the feminine form, agreeing with the
            implied Russian noun "карта". Rune systems always have
            ``supportsReversed=False``, so this branch is dead code for runes.

        Args:
            reading: The completed reading.
            lang: BCP-47-ish language code for localisation lookups.
                Defaults to ``"ru"``. Falls back to the English
                source-of-truth string when a translation is missing.

        Returns:
            A newline-joined block, ready to interpolate into the
            user-facing reply template via ``{drawnSymbolsBlock}``.
        """
        lines: List[str] = []
        for idx, draw in enumerate(reading.draws):
            i: int = idx + 1
            posText: str = localization.tr(localization.POSITION_NAMES, draw.position, lang)
            nameText: str = localization.tr(localization.SYMBOL_NAMES, draw.symbol.name, lang)
            reversedSuffix: str = " (перевёрнута)" if draw.reversed else ""
            glyphPrefix: str = f"{draw.symbol.glyph} " if draw.symbol.glyph else ""
            lines.append(f"{i}. {posText} — {glyphPrefix}{nameText}{reversedSuffix}")
        return "\n".join(lines)

    @classmethod
    def renderReplyTemplate(
        cls,
        template: str,
        *,
        layoutName: str,
        drawnSymbolsBlock: str,
        interpretation: str,
    ) -> str:
        """Render the user-facing reply template for a slash-command reading.

        Calls the private :func:`_safeFormat` so unknown or omitted
        placeholders silently become empty strings — operators can trim
        the template without breaking rendering, dood!

        Supported placeholders in ``template``:

        * ``{layoutName}`` — the layout's localised display name.
        * ``{drawnSymbolsBlock}`` — numbered list from
          :meth:`renderDrawnSymbolsBlock`.
        * ``{interpretation}`` — the LLM-generated interpretation text.

        Args:
            template: Operator-supplied reply template string.
            layoutName: Localised layout name (e.g. ``"Расклад на три карты"``).
            drawnSymbolsBlock: Pre-rendered drawn-symbols block from
                :meth:`renderDrawnSymbolsBlock`.
            interpretation: Raw LLM interpretation text.

        Returns:
            The fully rendered user-visible reply string.
        """
        return _safeFormat(
            template,
            layoutName=layoutName,
            drawnSymbolsBlock=drawnSymbolsBlock,
            interpretation=interpretation,
        )

    @classmethod
    def buildImagePrompt(
        cls,
        reading: Reading,
        *,
        imagePromptTemplate: str,
        styleHint: str = "",
    ) -> str:
        """Render a single image-generation prompt for the whole spread.

        Symbol names are emitted in **English** (image models behave better in
        English), and ``{layoutName}`` is filled with the layout's English
        name for the same reason.

        Supported placeholders in ``imagePromptTemplate``:

        * ``{layoutName}`` — the layout's English name.
        * ``{spreadDescription}`` — multi-line description of every drawn
          symbol in its position, including image-prompt fragments.
        * ``{styleHint}`` — caller-provided style hint. When the caller does
          not pass one, the placeholder is substituted with an empty string
          so templates that do or do not reference ``{styleHint}`` both
          render fine, dood!

        Args:
            reading: The :class:`Reading` whose image to describe.
            imagePromptTemplate: Operator-supplied image-prompt template.
            styleHint: Optional style hint substituted into ``{styleHint}``.
                Defaults to an empty string.

        Returns:
            The fully rendered image-generation prompt.
        """
        descriptionLines: List[str] = []
        for draw in reading.draws:
            reversedTag: str = " (reversed)" if draw.reversed else ""
            descriptionLines.append(
                f"{draw.position}: {draw.symbol.name}{reversedTag} — {draw.symbol.imagePromptFragment}"
            )
        spreadDescription: str = "\n".join(descriptionLines)

        return _safeFormat(
            imagePromptTemplate,
            layoutName=reading.layout.nameEn,
            spreadDescription=spreadDescription,
            styleHint=styleHint,
        )
