"""Tests for :func:`lib.divination.drawing.drawSymbols`, dood!"""

import random
from typing import Set, Tuple

from .base import DrawnSymbol
from .drawing import drawSymbols
from .layouts import TAROT_LAYOUTS, Layout
from .tarot import TarotSystem


def _findLayout(layoutId: str) -> Layout:
    """Locate a tarot layout by its machine id.

    Args:
        layoutId: The layout id to find.

    Returns:
        The matching :class:`Layout`.
    """
    for layout in TAROT_LAYOUTS:
        if layout.id == layoutId:
            return layout
    raise AssertionError(f"layout {layoutId!r} not found in TAROT_LAYOUTS, dood!")


def testReturnsExactNumberOfDraws() -> None:
    """``drawSymbols`` must return exactly ``layout.numSymbols`` draws."""
    layout: Layout = _findLayout("celtic_cross")
    draws: Tuple[DrawnSymbol, ...] = drawSymbols(
        TarotSystem.deck,
        layout,
        supportsReversed=True,
        rng=random.Random(0),
    )
    assert len(draws) == layout.numSymbols == 10


def testDrawsAreUnique() -> None:
    """Every draw must reference a distinct symbol (no replacement), dood!"""
    layout: Layout = _findLayout("celtic_cross")
    draws: Tuple[DrawnSymbol, ...] = drawSymbols(
        TarotSystem.deck,
        layout,
        supportsReversed=True,
        rng=random.Random(123),
    )
    seen: Set[str] = {draw.symbol.id for draw in draws}
    assert len(seen) == len(draws)


def testPositionsMatchLayout() -> None:
    """Position labels and indices must mirror the layout, dood!"""
    layout: Layout = _findLayout("three_card")
    draws: Tuple[DrawnSymbol, ...] = drawSymbols(
        TarotSystem.deck,
        layout,
        supportsReversed=True,
        rng=random.Random(7),
    )
    assert tuple(d.position for d in draws) == layout.positions
    assert tuple(d.positionIndex for d in draws) == (0, 1, 2)


def testSeededRngIsDeterministic() -> None:
    """Two seeded runs with the same seed must produce identical results."""
    layout: Layout = _findLayout("celtic_cross")
    first: Tuple[DrawnSymbol, ...] = drawSymbols(
        TarotSystem.deck,
        layout,
        supportsReversed=True,
        rng=random.Random(1234),
    )
    second: Tuple[DrawnSymbol, ...] = drawSymbols(
        TarotSystem.deck,
        layout,
        supportsReversed=True,
        rng=random.Random(1234),
    )
    assert tuple((d.symbol.id, d.reversed) for d in first) == tuple((d.symbol.id, d.reversed) for d in second)


def testSupportsReversedFalseAlwaysUpright() -> None:
    """When ``supportsReversed=False`` no draw may come back reversed."""
    layout: Layout = _findLayout("celtic_cross")
    rng: random.Random = random.Random(42)
    for _ in range(50):
        draws: Tuple[DrawnSymbol, ...] = drawSymbols(
            TarotSystem.deck,
            layout,
            supportsReversed=False,
            rng=rng,
        )
        assert all(not d.reversed for d in draws)


def testReversalProbabilityRoughlyHalf() -> None:
    """Over many one-card draws ~50% should be reversed (±5%), dood!"""
    layout: Layout = _findLayout("one_card")
    rng: random.Random = random.Random(2026)
    iterations: int = 10000
    reversedCount: int = 0
    for _ in range(iterations):
        draws: Tuple[DrawnSymbol, ...] = drawSymbols(
            TarotSystem.deck,
            layout,
            supportsReversed=True,
            rng=rng,
        )
        if draws[0].reversed:
            reversedCount += 1
    ratio: float = reversedCount / iterations
    assert 0.45 <= ratio <= 0.55, f"reversal ratio {ratio:.3f} outside ±5% of 0.5"
