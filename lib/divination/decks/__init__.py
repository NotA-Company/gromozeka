"""Static deck data for divination systems, dood!

Each module here exposes a single tuple of :class:`lib.divination.base.Symbol`
objects. English is the source of truth for names, meanings and
image-prompt fragments; Russian translations live in
:mod:`lib.divination.localization`.
"""

from .runes_elder_futhark import RUNES_ELDER_FUTHARK_DECK
from .tarot_rws import TAROT_RWS_DECK

__all__ = [
    "RUNES_ELDER_FUTHARK_DECK",
    "TAROT_RWS_DECK",
]
