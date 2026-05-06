"""Tests for :meth:`BaseDivinationSystem.renderDrawnSymbolsBlock` and
:meth:`BaseDivinationSystem.renderReplyTemplate`, dood!

Covers:
* Three-card tarot spread renders 3 numbered lines.
* A reversed card produces the ``(перевёрнута)`` suffix.
* Rune readings never produce the reversal suffix.
* Unknown language code falls back to the English symbol/position name.
* An N-symbol reading produces a string with exactly N-1 newlines.
* ``renderReplyTemplate`` substitutes all three placeholders.
"""

import random
from typing import Tuple

from .base import DrawnSymbol, Reading
from .layouts import RUNE_LAYOUTS, TAROT_LAYOUTS, Layout
from .runes import RunesSystem
from .tarot import TarotSystem


def _findTarotLayout(layoutId: str) -> Layout:
    """Return the tarot layout with the given id.

    Args:
        layoutId: Identifier of the layout to locate.

    Returns:
        The matching :class:`Layout`.

    Raises:
        AssertionError: If no layout with the given id exists.
    """
    for layout in TAROT_LAYOUTS:
        if layout.id == layoutId:
            return layout
    raise AssertionError(f"Tarot layout {layoutId!r} not found, dood!")


def _findRuneLayout(layoutId: str) -> Layout:
    """Return the rune layout with the given id.

    Args:
        layoutId: Identifier of the layout to locate.

    Returns:
        The matching :class:`Layout`.

    Raises:
        AssertionError: If no layout with the given id exists.
    """
    for layout in RUNE_LAYOUTS:
        if layout.id == layoutId:
            return layout
    raise AssertionError(f"Rune layout {layoutId!r} not found, dood!")


def _makeThreeCardReading(*, forceAllReversed: bool = False) -> Reading:
    """Build a three-card tarot reading, optionally with all cards reversed.

    Args:
        forceAllReversed: When ``True``, every draw in the reading is
            marked reversed (for testing the reversal suffix).

    Returns:
        A :class:`Reading` using the ``three_card`` layout.
    """
    layout: Layout = _findTarotLayout("three_card")
    draws: Tuple[DrawnSymbol, ...] = TarotSystem.draw(layout, rng=random.Random(42))

    if forceAllReversed:
        draws = tuple(
            DrawnSymbol(symbol=d.symbol, reversed=True, position=d.position, positionIndex=d.positionIndex)
            for d in draws
        )

    return Reading(
        systemId=TarotSystem.systemId,
        deckId=TarotSystem.deckId,
        layout=layout,
        draws=draws,
        question="",
        seed=42,
    )


def _makeOneCardReadingMixedReversed() -> Reading:
    """Build a one-card tarot reading with the card explicitly reversed.

    Returns:
        A :class:`Reading` using the ``one_card`` layout with the drawn
        card marked as reversed.
    """
    layout: Layout = _findTarotLayout("one_card")
    draws: Tuple[DrawnSymbol, ...] = TarotSystem.draw(layout, rng=random.Random(7))
    reversedDraws: Tuple[DrawnSymbol, ...] = tuple(
        DrawnSymbol(symbol=d.symbol, reversed=True, position=d.position, positionIndex=d.positionIndex) for d in draws
    )
    return Reading(
        systemId=TarotSystem.systemId,
        deckId=TarotSystem.deckId,
        layout=layout,
        draws=reversedDraws,
        question="",
        seed=7,
    )


def _makeThreeRunesReading() -> Reading:
    """Build a three-runes reading (no reversals possible).

    Returns:
        A :class:`Reading` using the ``three_runes`` layout.
    """
    layout: Layout = _findRuneLayout("three_runes")
    draws: Tuple[DrawnSymbol, ...] = RunesSystem.draw(layout, rng=random.Random(123))
    return Reading(
        systemId=RunesSystem.systemId,
        deckId=RunesSystem.deckId,
        layout=layout,
        draws=draws,
        question="",
        seed=123,
    )


# ---------------------------------------------------------------------------
# renderDrawnSymbolsBlock tests
# ---------------------------------------------------------------------------


def testThreeCardSpreadRendersThreeLines() -> None:
    """Three-card reading must produce exactly 3 lines indexed 1, 2, 3, dood!"""
    reading: Reading = _makeThreeCardReading()
    block: str = TarotSystem.renderDrawnSymbolsBlock(reading, lang="ru")

    lines = block.split("\n")
    assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}: {block!r}"
    assert lines[0].startswith("1.")
    assert lines[1].startswith("2.")
    assert lines[2].startswith("3.")


def testThreeCardSpreadContainsLocalizedNames() -> None:
    """Each line must contain the localized Russian position and symbol name."""
    reading: Reading = _makeThreeCardReading()
    block: str = TarotSystem.renderDrawnSymbolsBlock(reading, lang="ru")

    # Russian position names for three_card: Прошлое, Настоящее, Будущее.
    assert "Прошлое" in block
    assert "Настоящее" in block
    assert "Будущее" in block


def testReversedCardHasReversedSuffix() -> None:
    """A reversed tarot card must render `` (перевёрнута)`` in its line, dood!"""
    reading: Reading = _makeOneCardReadingMixedReversed()
    block: str = TarotSystem.renderDrawnSymbolsBlock(reading, lang="ru")

    assert "(перевёрнута)" in block, f"Expected reversal suffix, got: {block!r}"


def testAllReversedCardsHaveSuffix() -> None:
    """Every reversed card in the reading must have the reversal suffix, dood!"""
    reading: Reading = _makeThreeCardReading(forceAllReversed=True)
    block: str = TarotSystem.renderDrawnSymbolsBlock(reading, lang="ru")

    lines = block.split("\n")
    assert len(lines) == 3
    for line in lines:
        assert "(перевёрнута)" in line, f"Expected reversal suffix in line: {line!r}"


def testNonReversedCardHasNoSuffix() -> None:
    """Non-reversed draws must NOT produce the reversal suffix, dood!"""
    layout: Layout = _findTarotLayout("three_card")
    draws: Tuple[DrawnSymbol, ...] = tuple(
        DrawnSymbol(symbol=d.symbol, reversed=False, position=d.position, positionIndex=d.positionIndex)
        for d in TarotSystem.draw(layout, rng=random.Random(5))
    )
    reading: Reading = Reading(
        systemId=TarotSystem.systemId,
        deckId=TarotSystem.deckId,
        layout=layout,
        draws=draws,
        question="",
        seed=5,
    )
    block: str = TarotSystem.renderDrawnSymbolsBlock(reading, lang="ru")

    assert "(перевёрнута)" not in block


def testRunesReadingHasNoReversalSuffix() -> None:
    """Rune readings must never render the reversal suffix, dood!

    :attr:`RunesSystem.supportsReversed` is ``False``, so all draws have
    ``reversed=False`` and the branch is never taken.
    """
    reading: Reading = _makeThreeRunesReading()
    block: str = RunesSystem.renderDrawnSymbolsBlock(reading, lang="ru")

    assert "(перевёрнута)" not in block


def testLangFallbackToEnglish() -> None:
    """An unknown language code must fall back to English names, dood!"""
    reading: Reading = _makeThreeCardReading()
    block: str = TarotSystem.renderDrawnSymbolsBlock(reading, lang="zh")  # no Chinese translations

    # English position names must appear as fallback.
    assert "Past" in block
    assert "Present" in block
    assert "Future" in block
    # English symbol names must appear as fallback.
    for draw in reading.draws:
        assert draw.symbol.name in block


def testNewlineCountEqualsDrawsMinusOne() -> None:
    """For N draws, the block must contain exactly N-1 newline characters, dood!"""
    reading: Reading = _makeThreeCardReading()
    block: str = TarotSystem.renderDrawnSymbolsBlock(reading, lang="ru")

    numDraws: int = len(reading.draws)
    numNewlines: int = block.count("\n")
    assert (
        numNewlines == numDraws - 1
    ), f"Expected {numDraws - 1} newlines for {numDraws} draws, got {numNewlines}: {block!r}"


def testSingleDrawHasNoNewlines() -> None:
    """A single-card reading produces a block with no newlines, dood!"""
    layout: Layout = _findTarotLayout("one_card")
    draws: Tuple[DrawnSymbol, ...] = TarotSystem.draw(layout, rng=random.Random(0))
    reading: Reading = Reading(
        systemId=TarotSystem.systemId,
        deckId=TarotSystem.deckId,
        layout=layout,
        draws=draws,
        question="",
        seed=0,
    )
    block: str = TarotSystem.renderDrawnSymbolsBlock(reading, lang="ru")

    assert "\n" not in block
    assert block.startswith("1.")


# ---------------------------------------------------------------------------
# renderReplyTemplate tests
# ---------------------------------------------------------------------------


def testRenderReplyTemplateSubstitutesAllPlaceholders() -> None:
    """All three placeholders must be substituted correctly, dood!"""
    template: str = "Расклад: {layoutName}\nКарты:\n{drawnSymbolsBlock}\n\n{interpretation}"
    result: str = TarotSystem.renderReplyTemplate(
        template,
        layoutName="Расклад на три карты",
        drawnSymbolsBlock="1. Прошлое — Шут",
        interpretation="Всё будет хорошо.",
    )

    assert result == "Расклад: Расклад на три карты\nКарты:\n1. Прошлое — Шут\n\nВсё будет хорошо."


def testRenderReplyTemplateMissingPlaceholderRendersEmpty() -> None:
    """Missing placeholders must silently become empty strings, dood!"""
    template: str = "A={layoutName}|B={drawnSymbolsBlock}|C={interpretation}|D={unknown}"
    result: str = TarotSystem.renderReplyTemplate(
        template,
        layoutName="X",
        drawnSymbolsBlock="Y",
        interpretation="Z",
    )

    assert result == "A=X|B=Y|C=Z|D="


def testRenderReplyTemplateIsStringResult() -> None:
    """``renderReplyTemplate`` must return a ``str``, dood!"""
    result = TarotSystem.renderReplyTemplate(
        "{layoutName} / {drawnSymbolsBlock} / {interpretation}",
        layoutName="L",
        drawnSymbolsBlock="S",
        interpretation="I",
    )
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Glyph prefix tests
# ---------------------------------------------------------------------------


def testRunesReadingPrependsGlyph() -> None:
    """Each line in a runes block must contain the rune's glyph before its name, dood!

    For example, Fehu must produce a substring like ``"ᚠ Феху"`` in the line.
    """
    reading: Reading = _makeThreeRunesReading()
    block: str = RunesSystem.renderDrawnSymbolsBlock(reading, lang="ru")

    lines: list[str] = block.split("\n")
    assert len(lines) == 3
    for idx, draw in enumerate(reading.draws):
        glyph: str = draw.symbol.glyph  # type: ignore[assignment]
        assert glyph, f"Draw {idx} has no glyph — test data is wrong"
        # The glyph must appear in the line, immediately followed by a space
        # and then the localised name (somewhere in the line).
        assert glyph in lines[idx], f"Glyph {glyph!r} not found in line {idx}: {lines[idx]!r}"
        # Confirm glyph sits right before the name (not reversed or floating).
        nameSubstring: str = f"{glyph} "
        assert nameSubstring in lines[idx], f"Expected '{nameSubstring}' (glyph+space) in line {idx}: {lines[idx]!r}"


def testTarotReadingHasNoGlyphPrefix() -> None:
    """Tarot lines must NOT contain any Runic block character and must follow the plain format, dood!

    Confirms that tarot cards (which have ``glyph=None``) produce lines of the
    form ``"<n>. <position> — <name>"`` with no leading space before the name
    and no runic character anywhere.
    """
    reading: Reading = _makeThreeCardReading()
    block: str = TarotSystem.renderDrawnSymbolsBlock(reading, lang="ru")

    lines: list[str] = block.split("\n")
    assert len(lines) == 3
    for line in lines:
        # No character from the Runic Unicode block (U+16A0–U+16F8) must appear.
        for ch in line:
            codepoint: int = ord(ch)
            assert not (
                0x16A0 <= codepoint <= 0x16F8
            ), f"Unexpected runic character {ch!r} (U+{codepoint:04X}) in tarot line: {line!r}"
        # The name must follow the em-dash separator directly (no extra leading space).
        # Pattern: "N. <pos> — <name>" where <name> does not start with a space.
        separator: str = " — "
        assert separator in line, f"Expected ' — ' separator in line: {line!r}"
        afterSeparator: str = line.split(separator, 1)[1]
        assert not afterSeparator.startswith(" "), f"Name part starts with unexpected space in tarot line: {line!r}"
