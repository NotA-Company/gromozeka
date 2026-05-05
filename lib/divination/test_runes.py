"""Tests for :class:`lib.divination.runes.RunesSystem`, dood!"""

import random
from typing import List

from lib.ai import ModelMessage

from .base import Reading
from .decks.runes_elder_futhark import RUNES_ELDER_FUTHARK_DECK
from .layouts import RUNE_LAYOUTS, Layout
from .runes import RunesSystem


def _findLayout(layoutId: str) -> Layout:
    """Locate a rune layout by id.

    Args:
        layoutId: The layout id to find.

    Returns:
        The matching :class:`Layout`.
    """
    for layout in RUNE_LAYOUTS:
        if layout.id == layoutId:
            return layout
    raise AssertionError(f"layout {layoutId!r} not found, dood!")


def testDeckIntegrity() -> None:
    """The Elder Futhark set must have exactly 24 runes."""
    assert len(RUNES_ELDER_FUTHARK_DECK) == 24
    aetts = {s.metadata.get("aett") for s in RUNES_ELDER_FUTHARK_DECK}
    assert aetts == {"freyr", "hagal", "tyr"}
    numbers = sorted(int(s.metadata.get("number", 0)) for s in RUNES_ELDER_FUTHARK_DECK)
    assert numbers == list(range(1, 25))


def testRunesHaveNoReversedMeaning() -> None:
    """Runes must not carry reversed meanings in this library, dood!"""
    for rune in RUNES_ELDER_FUTHARK_DECK:
        assert rune.meaningReversed is None


def testSystemAttributes() -> None:
    """Class-level attributes on :class:`RunesSystem` must match the spec."""
    assert RunesSystem.systemId == "runes"
    assert RunesSystem.deckId == "elder_futhark"
    assert RunesSystem.supportsReversed is False
    assert RunesSystem.deck is RUNES_ELDER_FUTHARK_DECK


def testDrawNeverProducesReversed() -> None:
    """Runic draws are always upright."""
    layout: Layout = _findLayout("nine_runes")
    rng: random.Random = random.Random(2026)
    for _ in range(50):
        draws = RunesSystem.draw(layout, rng=rng)
        assert all(not d.reversed for d in draws)


def testBuildInterpretationMessagesRendersPlaceholders() -> None:
    """Rune readings render the same placeholders tarot does, dood!"""
    layout: Layout = _findLayout("three_runes")
    draws = RunesSystem.draw(layout, rng=random.Random(7))
    reading: Reading = Reading(
        systemId=RunesSystem.systemId,
        deckId=RunesSystem.deckId,
        layout=layout,
        draws=draws,
        question="What awaits me?",
        seed=7,
    )
    template: str = (
        "User: {userName}\n"
        "Q: {question}\n"
        "Layout: {layoutName}\n"
        "Positions:\n{positionsBlock}\n"
        "Runes:\n{cardsBlock}\n"
    )
    messages: List[ModelMessage] = RunesSystem.buildInterpretationMessages(
        reading,
        userName="Bob",
        systemPromptTemplate="sys",
        userPromptTemplate=template,
        lang="ru",
    )
    rendered: str = messages[1].content
    assert "Bob" in rendered
    assert "What awaits me?" in rendered
    assert "Три норны" in rendered
    assert "Прошлое" in rendered and "Настоящее" in rendered and "Будущее" in rendered
    # No "(reversed)" markers should appear for runes.
    assert "(reversed)" not in rendered


def testBuildImagePromptUsesEnglishRuneNames() -> None:
    """Image prompts must keep English rune names and English layout name."""
    layout: Layout = _findLayout("five_runes")
    draws = RunesSystem.draw(layout, rng=random.Random(101))
    reading: Reading = Reading(
        systemId=RunesSystem.systemId,
        deckId=RunesSystem.deckId,
        layout=layout,
        draws=draws,
        question="",
        seed=101,
    )
    template: str = "{layoutName}\n{spreadDescription}\nStyle: {styleHint}"
    prompt: str = RunesSystem.buildImagePrompt(reading, imagePromptTemplate=template, styleHint="nordic stone")
    assert "Five-Rune Cross" in prompt
    for draw in draws:
        assert draw.symbol.name in prompt
    assert "nordic stone" in prompt
