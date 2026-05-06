"""Single RNG entry-point for divination draws, dood!

Concentrating the drawing logic in one tiny function makes it trivial to
swap the algorithm later (ritualistic shuffle-then-pop, weighted draws,
external entropy sources, …) without touching the systems themselves.
"""

import random
from typing import Optional, Sequence, Tuple

from .base import DrawnSymbol, Symbol
from .layouts import Layout


def drawSymbols(
    deck: Sequence[Symbol],
    layout: Layout,
    *,
    supportsReversed: bool,
    rng: Optional[random.Random] = None,
) -> Tuple[DrawnSymbol, ...]:
    """Draw ``layout.numSymbols`` unique symbols and assign them positions.

    :func:`random.Random.sample` already guarantees uniqueness without
    replacement, which is exactly what we want for tarot/runes.

    The default RNG is :class:`random.SystemRandom`, which is OS-backed
    (``/dev/urandom`` on POSIX, ``CryptGenRandom`` on Windows). It is the
    production default because tarot/runes results feel meaningful to users —
    using a non-deterministic, OS-grade RNG avoids any whiff of "the bot is
    rigged" while still being trivially overridable for tests via the ``rng``
    keyword.

    Args:
        deck: Source deck of symbols. Any :class:`~typing.Sequence` works;
            the function will copy it into a list before sampling.
        layout: Layout describing how many symbols to draw and the position
            label for each draw.
        supportsReversed: When ``True``, each draw has an independent 50%
            chance of being reversed. When ``False`` (e.g. for runes), every
            draw is upright.
        rng: Optional injected RNG. Production uses
            :class:`random.SystemRandom`; tests typically pin a seeded
            :class:`random.Random` for determinism.

    Returns:
        Tuple of :class:`DrawnSymbol` of length ``layout.numSymbols``.
    """
    activeRng: random.Random = rng if rng is not None else random.SystemRandom()
    drawn: list[Symbol] = activeRng.sample(list(deck), k=layout.numSymbols)
    return tuple(
        DrawnSymbol(
            symbol=sym,
            reversed=supportsReversed and activeRng.random() < 0.5,
            position=layout.positions[i],
            positionIndex=i,
        )
        for i, sym in enumerate(drawn)
    )
