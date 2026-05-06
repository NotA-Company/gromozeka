"""Schema/integrity tests for the deck modules under :mod:`lib.divination.decks`."""

from collections import Counter
from typing import Set

from .runes_elder_futhark import RUNES_ELDER_FUTHARK_DECK
from .tarot_rws import TAROT_RWS_DECK


def testTarotDeckHas78UniqueIds() -> None:
    """The RWS deck must contain exactly 78 cards with unique ids, dood!"""
    assert len(TAROT_RWS_DECK) == 78
    ids: Set[str] = {symbol.id for symbol in TAROT_RWS_DECK}
    assert len(ids) == 78


def testTarotMajorMinorCounts() -> None:
    """22 majors + 4 suits × 14 minors must be present in the deck."""
    arcanaCounts: Counter[str] = Counter(str(symbol.metadata.get("arcana", "")) for symbol in TAROT_RWS_DECK)
    assert arcanaCounts["major"] == 22
    assert arcanaCounts["minor"] == 56

    suitCounts: Counter[str] = Counter(
        str(symbol.metadata.get("suit", "")) for symbol in TAROT_RWS_DECK if symbol.metadata.get("arcana") == "minor"
    )
    assert suitCounts["wands"] == 14
    assert suitCounts["cups"] == 14
    assert suitCounts["swords"] == 14
    assert suitCounts["pentacles"] == 14


def testTarotNamesAreUnique() -> None:
    """No two cards may share an English name."""
    names: list[str] = [symbol.name for symbol in TAROT_RWS_DECK]
    assert len(set(names)) == len(names)


def testTarotReversedMeaningsArePresent() -> None:
    """Every RWS card must carry a non-empty reversed meaning, dood!"""
    for symbol in TAROT_RWS_DECK:
        assert symbol.meaningReversed is not None
        assert symbol.meaningReversed.strip() != ""


def testTarotSymbolFieldsNonEmpty() -> None:
    """Mandatory string fields must be non-empty for every tarot card."""
    for symbol in TAROT_RWS_DECK:
        assert symbol.id.strip() != ""
        assert symbol.name.strip() != ""
        assert symbol.meaningUpright.strip() != ""
        assert symbol.imagePromptFragment.strip() != ""


def testRuneDeckHas24UniqueIds() -> None:
    """The Elder Futhark set must contain exactly 24 runes with unique ids."""
    assert len(RUNES_ELDER_FUTHARK_DECK) == 24
    ids: Set[str] = {rune.id for rune in RUNES_ELDER_FUTHARK_DECK}
    assert len(ids) == 24


def testRuneNamesAreUnique() -> None:
    """No two runes may share an English name."""
    names: list[str] = [rune.name for rune in RUNES_ELDER_FUTHARK_DECK]
    assert len(set(names)) == len(names)


def testRuneReversedMeaningsAreNone() -> None:
    """Runes do not use reversals — every reversed meaning must be ``None``."""
    for rune in RUNES_ELDER_FUTHARK_DECK:
        assert rune.meaningReversed is None


def testRuneSymbolFieldsNonEmpty() -> None:
    """Mandatory string fields must be non-empty for every rune."""
    for rune in RUNES_ELDER_FUTHARK_DECK:
        assert rune.id.strip() != ""
        assert rune.name.strip() != ""
        assert rune.meaningUpright.strip() != ""
        assert rune.imagePromptFragment.strip() != ""


def testRuneAettAndNumbersAreContinuous() -> None:
    """Aett labels must cover all three aetts and numbers must be 1..24."""
    aetts: Counter[str] = Counter(str(rune.metadata.get("aett", "")) for rune in RUNES_ELDER_FUTHARK_DECK)
    assert aetts["freyr"] == 8
    assert aetts["hagal"] == 8
    assert aetts["tyr"] == 8
    numbers: list[int] = sorted(int(rune.metadata.get("number", 0)) for rune in RUNES_ELDER_FUTHARK_DECK)
    assert numbers == list(range(1, 25))


def testRuneGlyphsArePresent() -> None:
    """All 24 runes must carry a non-None, non-empty ``glyph`` field, dood!"""
    for rune in RUNES_ELDER_FUTHARK_DECK:
        assert rune.glyph is not None, f"Rune {rune.name!r} has no glyph"
        assert rune.glyph != "", f"Rune {rune.name!r} has an empty glyph"


def testRuneGlyphsAreSingleRunicCharacter() -> None:
    """Each rune glyph must be a single character in the Runic Unicode block (U+16A0–U+16F8), dood!"""
    for rune in RUNES_ELDER_FUTHARK_DECK:
        assert rune.glyph is not None
        assert len(rune.glyph) == 1, f"Rune {rune.name!r} glyph {rune.glyph!r} is not a single character"
        codepoint: int = ord(rune.glyph)
        assert (
            0x16A0 <= codepoint <= 0x16F8
        ), f"Rune {rune.name!r} glyph {rune.glyph!r} (U+{codepoint:04X}) is outside the Runic Unicode block"


def testRuneGlyphsAreUnique() -> None:
    """The 24 runes must all have distinct glyphs — no duplicates, dood!"""
    glyphs: list[str] = [rune.glyph for rune in RUNES_ELDER_FUTHARK_DECK if rune.glyph is not None]
    assert len(glyphs) == 24
    assert len(set(glyphs)) == 24, f"Duplicate glyphs found: {Counter(glyphs).most_common()}"


def testTarotGlyphsAreNone() -> None:
    """All 78 tarot cards must have ``glyph=None`` (no canonical single character), dood!"""
    for card in TAROT_RWS_DECK:
        assert card.glyph is None, f"Tarot card {card.name!r} unexpectedly has glyph {card.glyph!r}"
