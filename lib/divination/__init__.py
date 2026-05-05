"""Divination library — tarot and runes spreads for the Gromozeka bot, dood!

This package is intentionally pure: it contains deck data, layout definitions,
drawing logic, prompt assembly, and Russian localisation, but it knows nothing
about the bot, the database, or :mod:`internal.services.llm`. The only
cross-tree import allowed inside :mod:`lib.divination` is ``from lib.ai
import ModelMessage`` for prompt assembly.

Public entry points:

* :class:`TarotSystem` and :class:`RunesSystem` — concrete divination systems.
* :class:`BaseDivinationSystem` — abstract base class for new systems.
* :class:`Symbol`, :class:`DrawnSymbol`, :class:`Reading` — core dataclasses.
* :class:`Layout` plus :data:`TAROT_LAYOUTS` and :data:`RUNE_LAYOUTS` —
  predefined spread shapes.
* :func:`drawSymbols` — single RNG entry point for draws.
* :mod:`lib.divination.localization` — translation tables and the :func:`tr`
  helper.
"""

from .base import BaseDivinationSystem, DrawnSymbol, Reading, Symbol
from .drawing import drawSymbols
from .layouts import RUNE_LAYOUTS, TAROT_LAYOUTS, Layout, resolveLayout
from .runes import RunesSystem
from .tarot import TarotSystem

__all__ = [
    "BaseDivinationSystem",
    "DrawnSymbol",
    "Layout",
    "RUNE_LAYOUTS",
    "Reading",
    "RunesSystem",
    "Symbol",
    "TAROT_LAYOUTS",
    "TarotSystem",
    "drawSymbols",
    "resolveLayout",
]
