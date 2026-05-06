"""Tarot divination system using the Rider–Waite–Smith deck, dood!

This module wires the abstract :class:`BaseDivinationSystem` to the concrete
RWS deck and the predefined tarot layouts. Tarot cards in this library can
be drawn reversed (50% chance per draw); see
:func:`lib.divination.drawing.drawSymbols`.
"""

from typing import Sequence, Tuple

from .base import BaseDivinationSystem, Symbol
from .decks.tarot_rws import TAROT_RWS_DECK
from .layouts import TAROT_LAYOUTS, Layout


class TarotSystem(BaseDivinationSystem):
    """Rider–Waite–Smith tarot system.

    Attributes:
        systemId: ``"tarot"`` — used by the handler to dispatch commands.
        deckId: ``"rws"`` — identifies the Rider–Waite–Smith deck.
        supportsReversed: ``True`` — RWS cards can be drawn reversed.
        deck: The 78-card RWS deck.
    """

    systemId = "tarot"
    deckId = "rws"
    supportsReversed = True
    deck: Tuple[Symbol, ...] = TAROT_RWS_DECK

    @classmethod
    def availableLayouts(cls) -> Sequence[Layout]:
        """Return the predefined tarot layouts.

        Returns:
            The module-level :data:`TAROT_LAYOUTS` tuple.
        """
        return TAROT_LAYOUTS
