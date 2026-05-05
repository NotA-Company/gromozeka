"""Elder Futhark rune set — 24 runes in standard order, dood!

The Elder Futhark is split into three *aetts* of eight runes each: Freyr's
aett (1–8), Hagal's aett (9–16) and Tyr's aett (17–24). English is the source
of truth for names and meanings; Russian translations live in
:mod:`lib.divination.localization`.

Reversals are not used for runes in this library, so every
:attr:`Symbol.meaningReversed` is ``None``.
"""

from typing import Any, Dict, Tuple

from ..base import Symbol

# Each row: (name, upright meaning, image-prompt fragment)
_FREYR_AETT: Tuple[Tuple[str, str, str], ...] = (
    (
        "Fehu",
        "Wealth earned through effort, prosperity, and abundance won by hand.",
        "The angular Fehu rune carved into a smooth river stone, two upward-pointing branches.",
    ),
    (
        "Uruz",
        "Raw vitality, primal strength, and untamed life force.",
        "The Uruz rune carved deeply into weathered grey rock, shaped like an inverted U with a sharp angle.",
    ),
    (
        "Thurisaz",
        "Defensive power, sudden challenge, and the thorn that protects.",
        "The Thurisaz rune etched on dark stone, an upright stave with a sharp triangular thorn on its side.",
    ),
    (
        "Ansuz",
        "Divine breath, communication, wisdom, and inspired speech.",
        "The Ansuz rune burned into pale wood, an upright stave with two slanted branches like an F.",
    ),
    (
        "Raidho",
        "Journey, motion, ordered progress, and the rhythm of travel.",
        "The Raidho rune carved on a flat stone, shaped like an angular R with a clean diagonal kick.",
    ),
    (
        "Kenaz",
        "Inner fire, illumination, learned skill, and creative spark.",
        "The Kenaz rune incised in birch wood, an open angle pointing forward like a torch's flame.",
    ),
    (
        "Gebo",
        "Gift, generous exchange, partnership, and balanced giving.",
        "The Gebo rune carved on a square wooden tile, a clean X centred on the surface.",
    ),
    (
        "Wunjo",
        "Joy, harmony, fellowship, and a wish fulfilled.",
        "The Wunjo rune carved on a smooth stone, a vertical stave with a small flag-shaped triangle near the top.",
    ),
)

_HAGAL_AETT: Tuple[Tuple[str, str, str], ...] = (
    (
        "Hagalaz",
        "Disruptive force, hailstorm, sudden upheaval that ultimately clears the way.",
        "The Hagalaz rune chiselled into dark slate, two vertical staves linked by a crossing bar.",
    ),
    (
        "Nauthiz",
        "Need, hardship, constraint, and lessons forged in necessity.",
        "The Nauthiz rune carved on aged wood, a vertical stave crossed by a short slanted line.",
    ),
    (
        "Isa",
        "Stillness, ice, frozen pause, and necessary suspension.",
        "The Isa rune etched on a frosted blue stone, a single straight vertical line.",
    ),
    (
        "Jera",
        "Harvest, cycles completed, just reward, and the turn of the year.",
        "The Jera rune carved on warm-toned wood, two angled hooks meeting around a central axis.",
    ),
    (
        "Eihwaz",
        "Endurance, the world tree, defence against difficulty, and deep rootedness.",
        "The Eihwaz rune incised on yew wood, a vertical stave with branches angled top-right and bottom-left.",
    ),
    (
        "Perthro",
        "Mystery, hidden lots, fate, and what is yet to be revealed.",
        "The Perthro rune carved on a dark stone, an open cup-like shape resting on its side.",
    ),
    (
        "Algiz",
        "Protection, sanctuary, the higher self, and guardian instinct.",
        "The Algiz rune carved on bone-pale stone, an upright stave with two upward-reaching branches.",
    ),
    (
        "Sowilo",
        "The sun, victory, vital energy, and clear guidance.",
        "The Sowilo rune carved on golden stone, two slanted strokes joined like a lightning bolt.",
    ),
)

_TYR_AETT: Tuple[Tuple[str, str, str], ...] = (
    (
        "Tiwaz",
        "Justice, honour, courage in conflict, and the warrior's true word.",
        "The Tiwaz rune carved on grey rock, an upright stave with two short downward-angled branches at the top.",
    ),
    (
        "Berkano",
        "Birth, growth, nurturing, and the renewing energy of the birch.",
        "The Berkano rune incised on pale birch bark, a vertical stave with two stacked outward bumps like a B.",
    ),
    (
        "Ehwaz",
        "Trusted partnership, movement together, and harmonious teamwork.",
        "The Ehwaz rune etched on dark wood, two vertical staves joined at the top by a slanted bridge like an M.",
    ),
    (
        "Mannaz",
        "The self in community, humanity, and shared identity.",
        "The Mannaz rune carved on a square stone, two staves crossed at the top like an angular M.",
    ),
    (
        "Laguz",
        "Flowing water, intuition, the unconscious, and emotional depth.",
        "The Laguz rune carved on a wave-blue stone, a vertical stave with one short branch leaning down-right.",
    ),
    (
        "Ingwaz",
        "Inner seed, gestation, completion, and stored potential ready to spring forth.",
        "The Ingwaz rune carved on warm wood, a small diamond shape centred on the surface.",
    ),
    (
        "Dagaz",
        "Breakthrough, dawn, awakening, and transformative clarity.",
        "The Dagaz rune carved on sun-bleached stone, an hourglass on its side from two triangles meeting at a point.",
    ),
    (
        "Othala",
        "Inheritance, ancestral home, kin, and the wisdom of one's roots.",
        "The Othala rune carved on dark hardwood, a diamond with two short legs angling outward at the bottom.",
    ),
)


def _buildRunes() -> Tuple[Symbol, ...]:
    """Assemble the 24-rune Elder Futhark set as :class:`Symbol` objects.

    Returns:
        Tuple of 24 runes in canonical aett order with metadata recording
        ``aett`` (one of ``"freyr"``, ``"hagal"``, ``"tyr"``) and ``number``
        (1..24).
    """
    runes: list[Symbol] = []
    aetts: Tuple[Tuple[str, Tuple[Tuple[str, str, str], ...]], ...] = (
        ("freyr", _FREYR_AETT),
        ("hagal", _HAGAL_AETT),
        ("tyr", _TYR_AETT),
    )
    runeNumber: int = 0
    for aettName, aett in aetts:
        for name, upright, fragment in aett:
            runeNumber += 1
            metadata: Dict[str, Any] = {"aett": aettName, "number": runeNumber}
            runes.append(
                Symbol(
                    id=f"rune_{name.lower()}",
                    name=name,
                    meaningUpright=upright,
                    meaningReversed=None,
                    imagePromptFragment=fragment,
                    metadata=metadata,
                )
            )
    return tuple(runes)


RUNES_ELDER_FUTHARK_DECK: Tuple[Symbol, ...] = _buildRunes()
