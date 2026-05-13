"""Tests for :class:`lib.divination.tarot.TarotSystem`, dood!"""

import random
from typing import List, Tuple

from lib.ai import ModelMessage

from .base import Reading, _safeFormat
from .decks.tarot_rws import TAROT_RWS_DECK
from .layouts import TAROT_LAYOUTS, Layout
from .tarot import TarotSystem


def _findLayout(layoutId: str) -> Layout:
    """Locate a tarot layout by id.

    Args:
        layoutId: The layout id to find.

    Returns:
        The matching :class:`Layout`.
    """
    for layout in TAROT_LAYOUTS:
        if layout.id == layoutId:
            return layout
    raise AssertionError(f"layout {layoutId!r} not found, dood!")


def testDeckIntegrity() -> None:
    """The RWS deck must have 78 cards split 22 majors + 56 minors."""
    assert len(TAROT_RWS_DECK) == 78
    majors: List = [s for s in TAROT_RWS_DECK if s.metadata.get("arcana") == "major"]
    minors: List = [s for s in TAROT_RWS_DECK if s.metadata.get("arcana") == "minor"]
    assert len(majors) == 22
    assert len(minors) == 56


def testSystemAttributes() -> None:
    """Class-level attributes on :class:`TarotSystem` must match the spec."""
    assert TarotSystem.systemId == "tarot"
    assert TarotSystem.deckId == "rws"
    assert TarotSystem.supportsReversed is True
    assert TarotSystem.deck is TAROT_RWS_DECK


def testResolveLayoutDelegatesToLayouts() -> None:
    """``TarotSystem.resolveLayout`` must reuse the alias resolver."""
    layout: Layout | None = TarotSystem.resolveLayout("3card")
    assert layout is not None and layout.id == "three_card"


def testBuildInterpretationMessagesRendersAllPlaceholders() -> None:
    """All template placeholders must be substituted in the user message."""
    layout: Layout = _findLayout("three_card")
    draws = TarotSystem.draw(layout, rng=random.Random(99))
    reading: Reading = Reading(
        systemId=TarotSystem.systemId,
        deckId=TarotSystem.deckId,
        layout=layout,
        draws=draws,
        question="Что меня ждёт на работе?",
        seed=99,
    )
    systemTemplate: str = "You are a friendly tarot reader, dood!"
    userTemplate: str = (
        "User: {userName}\n"
        "Question: {question}\n"
        "Layout: {layoutName}\n"
        "Positions:\n{positionsBlock}\n"
        "Cards:\n{cardsBlock}\n"
    )
    messages: List[ModelMessage] = TarotSystem.buildInterpretationMessages(
        reading,
        userName="Alice",
        systemPromptTemplate=systemTemplate,
        userPromptTemplate=userTemplate,
        lang="ru",
    )
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[0].content == systemTemplate
    assert messages[1].role == "user"

    rendered: str = messages[1].content
    assert "Alice" in rendered
    assert "Что меня ждёт на работе?" in rendered
    # Russian layout name must be present.
    assert "Расклад на три карты" in rendered
    # Russian position names must be present.
    assert "Прошлое" in rendered
    assert "Настоящее" in rendered
    assert "Будущее" in rendered
    # Each drawn symbol's localised name must appear in the cards block.
    from .localization import SYMBOL_NAMES, tr

    for draw in draws:
        localizedName: str = tr(SYMBOL_NAMES, draw.symbol.name, "ru")
        assert localizedName in rendered


def testBuildImagePromptUsesEnglishNames() -> None:
    """Image prompts must keep English symbol names and English layout names."""
    layout: Layout = _findLayout("three_card")
    draws = TarotSystem.draw(layout, rng=random.Random(11))
    reading: Reading = Reading(
        systemId=TarotSystem.systemId,
        deckId=TarotSystem.deckId,
        layout=layout,
        draws=draws,
        question="",
        seed=11,
    )
    template: str = "Render the {layoutName} divination spread:\n" "{spreadDescription}\n" "Style: {styleHint}"
    prompt: str = TarotSystem.buildImagePrompt(reading, imagePromptTemplate=template, styleHint="vintage")
    # English layout name.
    assert "Three-Card Spread" in prompt
    # Each drawn symbol's English name must appear.
    for draw in draws:
        assert draw.symbol.name in prompt
    # Style hint must be substituted.
    assert "vintage" in prompt


def testBuildImagePromptOmittedStyleHintRendersEmpty() -> None:
    """Without ``styleHint`` the placeholder must collapse to an empty string."""
    layout: Layout = _findLayout("one_card")
    draws = TarotSystem.draw(layout, rng=random.Random(0))
    reading: Reading = Reading(
        systemId=TarotSystem.systemId,
        deckId=TarotSystem.deckId,
        layout=layout,
        draws=draws,
        question="",
        seed=0,
    )
    template: str = "{layoutName}::{spreadDescription}::{styleHint}"
    prompt: str = TarotSystem.buildImagePrompt(reading, imagePromptTemplate=template)
    assert prompt.endswith("::")


def testSafeFormatToleratesUnknownPlaceholders() -> None:
    """``_safeFormat`` must not crash on placeholders the caller didn't pass."""
    rendered: str = _safeFormat("Hello {name}, your level is {level}", name="Alice")
    assert rendered == "Hello Alice, your level is "


def testReversedTagAppearsForReversedDraws() -> None:
    """Reversed draws must render the ``(reversed)`` marker in the cards block."""
    layout: Layout = _findLayout("three_card")
    # Force-reverse all draws by using a deterministic RNG and patching reversed
    # via a Reading constructed by hand.
    fromDraws: Tuple = TarotSystem.draw(layout, rng=random.Random(3))
    # Build an artificial reading where every draw is reversed.
    from .base import DrawnSymbol

    forced: Tuple[DrawnSymbol, ...] = tuple(
        DrawnSymbol(symbol=d.symbol, reversed=True, position=d.position, positionIndex=d.positionIndex)
        for d in fromDraws
    )
    reading: Reading = Reading(
        systemId=TarotSystem.systemId,
        deckId=TarotSystem.deckId,
        layout=layout,
        draws=forced,
        question="",
        seed=3,
    )
    messages: List[ModelMessage] = TarotSystem.buildInterpretationMessages(
        reading,
        userName="Alice",
        systemPromptTemplate="sys",
        userPromptTemplate="{cardsBlock}",
        lang="ru",
    )
    assert messages[1].content.count("(reversed)") == len(forced)
