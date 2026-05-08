"""Layout (spread) definitions for divination systems, dood!

A :class:`Layout` describes a single spread shape: how many symbols are drawn,
the ordered position names, and a set of human-friendly aliases the user can
type. English position names are the source of truth — translations come from
:mod:`lib.divination.localization`.

This module is pure data + a small case/separator-insensitive resolver. It has
no dependencies outside the standard library and is safe to import from any
other ``lib.divination`` module without creating cycles.
"""

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple


@dataclass(frozen=True, slots=True)
class Layout:
    """A divination layout / spread.

    Attributes:
        id: Stable machine identifier (e.g. ``"celtic_cross"``).
        nameEn: Canonical English name (used in image prompts because image
            models behave better in English).
        nameRu: Russian display name.
        positions: Ordered tuple of English position names. ``len(positions)``
            equals the number of symbols drawn for this layout.
        aliases: Tuple of accepted user-facing aliases (matched case- and
            separator-insensitively against the normalised form of the user
            input).
        systemId: Identifier of the divination system this layout belongs to
            (e.g. ``"tarot"`` or ``"runes"``).
        description: Optional layout description.
    """

    id: str
    nameEn: str
    nameRu: str
    positions: Tuple[str, ...]
    aliases: Tuple[str, ...]
    systemId: str
    description: Optional[str] = None

    @property
    def numSymbols(self) -> int:
        """Number of symbols this layout requires.

        Returns:
            The length of :attr:`positions` (the spread's size).
        """
        return len(self.positions)


def _normalize(s: str) -> str:
    """Normalise a user-typed layout name for alias matching, dood!

    Lowercases the input, trims whitespace, and collapses ``_`` / spaces to
    ``-`` so that ``"Three_Card"``, ``"three card"`` and ``"three-card"`` all
    compare equal.

    Args:
        s: Raw user-supplied string.

    Returns:
        Normalised string suitable for alias comparison.
    """
    return s.strip().lower().replace("_", "-").replace(" ", "-")


def resolveLayout(name: str, *, layouts: Sequence[Layout]) -> Optional[Layout]:
    """Resolve a user-typed name to a known :class:`Layout`.

    Matches the normalised input against the normalised form of every alias
    *and* the layout's ``id`` for the layouts in ``layouts``. The first match
    wins, dood!

    Args:
        name: Raw user-supplied layout name.
        layouts: Candidate layouts to match against (typically the layouts of
            a single divination system).

    Returns:
        The matched :class:`Layout`, or ``None`` if nothing matched.
    """
    if not name:
        return None
    needle: str = _normalize(name)
    for layout in layouts:
        candidates: Tuple[str, ...] = (layout.id,) + layout.aliases
        for candidate in candidates:
            if _normalize(candidate) == needle:
                return layout
    return None


# Predefined tarot layouts.
# Position names are English (source of truth); Russian translations live in
# :mod:`lib.divination.localization`.

TAROT_LAYOUTS: Tuple[Layout, ...] = (
    Layout(
        id="one_card",
        nameEn="One Card",
        nameRu="Одна карта",
        positions=("Insight",),
        aliases=("1", "1card", "one", "одна", "карта"),
        systemId="tarot",
    ),
    Layout(
        id="three_card",
        nameEn="Three-Card Spread",
        nameRu="Расклад на три карты",
        positions=("Past", "Present", "Future"),
        aliases=("3", "3card", "three", "три", "прошлое-настоящее-будущее"),
        systemId="tarot",
    ),
    Layout(
        id="celtic_cross",
        nameEn="Celtic Cross",
        nameRu="Кельтский крест",
        positions=(
            "Present",
            "Challenge",
            "Past",
            "Future",
            "Above",
            "Below",
            "Advice",
            "External Influences",
            "Hopes and Fears",
            "Outcome",
        ),
        aliases=(
            "10",
            "celtic",
            "celtic-cross",
            "keltic-cross",
            "кельтский-крест",
            "крест",
        ),
        systemId="tarot",
    ),
    Layout(
        id="relationship",
        nameEn="Relationship Spread",
        nameRu="Расклад на отношения",
        positions=("You", "Partner", "Connection", "Challenges", "Outcome"),
        aliases=("5", "отношения", "relationship"),
        systemId="tarot",
    ),
    Layout(
        id="yes_no",
        nameEn="Yes/No",
        nameRu="Да/Нет",
        positions=("Answer",),
        aliases=("yesno", "да-нет", "yn"),
        systemId="tarot",
    ),
)


# Predefined rune layouts.

RUNE_LAYOUTS: Tuple[Layout, ...] = (
    Layout(
        id="one_rune",
        nameEn="One Rune",
        nameRu="Одна руна",
        positions=("Insight",),
        aliases=("1", "одна", "руна"),
        systemId="runes",
    ),
    Layout(
        id="three_runes",
        nameEn="Three Norns",
        nameRu="Три норны",
        positions=("Past", "Present", "Future"),
        aliases=("3", "norns", "нормы", "три-руны"),
        systemId="runes",
    ),
    Layout(
        id="five_runes",
        nameEn="Five-Rune Cross",
        nameRu="Пятирунный крест",
        positions=("Past", "Present", "Future", "Help", "Outcome"),
        aliases=("5", "cross", "пятирунный-крест"),
        systemId="runes",
    ),
    Layout(
        id="nine_runes",
        nameEn="Nine-Rune Cast",
        nameRu="Расклад на девять рун",
        positions=(
            "Self",
            "Path",
            "Past",
            "Future",
            "Help",
            "Hindrance",
            "Family",
            "Hopes",
            "Outcome",
        ),
        aliases=("9", "grid", "девять"),
        systemId="runes",
    ),
)
