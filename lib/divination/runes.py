"""Elder Futhark runic divination system, dood!

Reversals are not used for runes in this library: runic readings interpret
each rune in its upright meaning regardless of orientation.
"""

from typing import Sequence, Tuple

from .base import BaseDivinationSystem, Symbol
from .decks.runes_elder_futhark import RUNES_ELDER_FUTHARK_DECK
from .layouts import RUNE_LAYOUTS, Layout


class RunesSystem(BaseDivinationSystem):
    """Elder Futhark runic divination system.

    Attributes:
        systemId: ``"runes"`` — used by the handler to dispatch commands.
        deckId: ``"elder_futhark"`` — identifies the 24-rune Elder Futhark set.
        supportsReversed: ``False`` — runes are always drawn upright.
        deck: The 24-rune Elder Futhark set.
    """

    systemId = "runes"
    deckId = "elder_futhark"
    supportsReversed = False
    deck: Tuple[Symbol, ...] = RUNES_ELDER_FUTHARK_DECK

    @classmethod
    def availableLayouts(cls) -> Sequence[Layout]:
        """Return the predefined rune layouts.

        Returns:
            The module-level :data:`RUNE_LAYOUTS` tuple.
        """
        return RUNE_LAYOUTS
