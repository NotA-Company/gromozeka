"""Tests for :mod:`lib.divination.localization`, dood!"""

from typing import Set

from .decks.runes_elder_futhark import RUNES_ELDER_FUTHARK_DECK
from .decks.tarot_rws import TAROT_RWS_DECK
from .layouts import RUNE_LAYOUTS, TAROT_LAYOUTS
from .localization import LAYOUT_NAMES, POSITION_NAMES, SYMBOL_NAMES, tr


def testEverySymbolNameHasRussian() -> None:
    """Every Symbol.name from both decks must have a non-empty ``"ru"`` entry."""
    for symbol in TAROT_RWS_DECK + RUNES_ELDER_FUTHARK_DECK:
        translations = SYMBOL_NAMES.get(symbol.name)
        assert translations is not None, f"missing localisation for {symbol.name!r}, dood!"
        assert "ru" in translations
        assert translations["ru"].strip() != ""


def testEveryPositionHasRussian() -> None:
    """Every position name used by predefined layouts must be translated."""
    usedPositions: Set[str] = set()
    for layout in TAROT_LAYOUTS + RUNE_LAYOUTS:
        usedPositions.update(layout.positions)
    for position in usedPositions:
        translations = POSITION_NAMES.get(position)
        assert translations is not None, f"missing position localisation for {position!r}"
        assert translations.get("ru", "").strip() != ""


def testEveryLayoutEnglishNameHasRussian() -> None:
    """Every ``Layout.nameEn`` must have a non-empty ``"ru"`` entry, dood!"""
    for layout in TAROT_LAYOUTS + RUNE_LAYOUTS:
        translations = LAYOUT_NAMES.get(layout.nameEn)
        assert translations is not None, f"missing layout name localisation for {layout.nameEn!r}"
        assert translations.get("ru", "").strip() != ""


def testTrFallsBackToEnglish() -> None:
    """``tr`` must return the English key when the language is missing."""
    assert tr(SYMBOL_NAMES, "The Fool", "fr") == "The Fool"
    assert tr(SYMBOL_NAMES, "Definitely Not A Card", "ru") == "Definitely Not A Card"


def testTrReturnsRussianWhenAvailable() -> None:
    """``tr`` must return the Russian translation when present."""
    assert tr(SYMBOL_NAMES, "The Fool", "ru") == "Шут"
    assert tr(POSITION_NAMES, "Past", "ru") == "Прошлое"
    assert tr(LAYOUT_NAMES, "Celtic Cross", "ru") == "Кельтский крест"


def testNoEmptyTranslations() -> None:
    """No localisation table may contain blank ``"ru"`` values, dood!"""
    for table in (SYMBOL_NAMES, POSITION_NAMES, LAYOUT_NAMES):
        for englishKey, perLang in table.items():
            for langCode, value in perLang.items():
                assert value.strip() != "", f"empty translation for {englishKey!r}/{langCode!r}"
