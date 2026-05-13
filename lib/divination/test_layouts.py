"""Tests for :mod:`lib.divination.layouts`, dood!"""

from typing import Optional

from .layouts import RUNE_LAYOUTS, TAROT_LAYOUTS, Layout, resolveLayout


def testNumSymbolsMatchesPositions() -> None:
    """``Layout.numSymbols`` must equal ``len(positions)`` for every layout."""
    for layout in TAROT_LAYOUTS + RUNE_LAYOUTS:
        assert layout.numSymbols == len(layout.positions)


def testResolveByCanonicalId() -> None:
    """A layout must be reachable by its exact ``id``, dood!"""
    resolved: Optional[Layout] = resolveLayout("three_card", layouts=TAROT_LAYOUTS)
    assert resolved is not None
    assert resolved.id == "three_card"


def testResolveCaseAndSeparatorInsensitive() -> None:
    """``three_card`` / ``three-card`` / ``Three Card`` must all match."""
    candidates: list[str] = ["three_card", "three-card", "Three Card", "THREE_CARD", "  three card  "]
    for candidate in candidates:
        resolved: Optional[Layout] = resolveLayout(candidate, layouts=TAROT_LAYOUTS)
        assert resolved is not None and resolved.id == "three_card", candidate


def testResolveByAlias() -> None:
    """Aliases are matched the same way as the canonical id, dood!"""
    resolved: Optional[Layout] = resolveLayout("celtic-cross", layouts=TAROT_LAYOUTS)
    assert resolved is not None and resolved.id == "celtic_cross"
    resolved = resolveLayout("Кельтский Крест", layouts=TAROT_LAYOUTS)
    assert resolved is not None and resolved.id == "celtic_cross"
    resolved = resolveLayout("Norns", layouts=RUNE_LAYOUTS)
    assert resolved is not None and resolved.id == "three_runes"


def testResolveUnknownReturnsNone() -> None:
    """Unknown names must resolve to ``None`` rather than raising."""
    assert resolveLayout("definitely-not-a-thing", layouts=TAROT_LAYOUTS) is None
    assert resolveLayout("", layouts=TAROT_LAYOUTS) is None


def testTarotAndRuneLayoutsDoNotShareIds() -> None:
    """Layout ids must be unique across the two systems, dood!"""
    tarotIds: set[str] = {layout.id for layout in TAROT_LAYOUTS}
    runeIds: set[str] = {layout.id for layout in RUNE_LAYOUTS}
    assert tarotIds.isdisjoint(runeIds)


def testResolveDoesNotCrossSystems() -> None:
    """A tarot-only id must not resolve when only rune layouts are searched."""
    assert resolveLayout("celtic_cross", layouts=RUNE_LAYOUTS) is None
    assert resolveLayout("nine_runes", layouts=TAROT_LAYOUTS) is None
