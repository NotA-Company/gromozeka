"""Rider–Waite–Smith (RWS) tarot deck — 78 cards, dood!

English is the source of truth for card names, meanings, and image-prompt
fragments. Russian translations live in :mod:`lib.divination.localization`.

Each card is a :class:`lib.divination.base.Symbol` with metadata describing its
arcana ("major" or "minor"), and for minors its suit and rank.
"""

from typing import Any, Dict, List, Tuple

from ..base import Symbol

# ---------------------------------------------------------------------------
# Major arcana — 22 cards, numbered 0..21.
# Each row: (number, name, upright, reversed, imagePromptFragment)
# ---------------------------------------------------------------------------

_MAJORS: Tuple[Tuple[int, str, str, str, str], ...] = (
    (
        0,
        "The Fool",
        "New beginnings, innocence, spontaneity, and a leap of faith.",
        "Recklessness, hesitation, and ignoring obvious risks.",
        "A young traveller stepping off a cliff with a small dog at their heels, white rose in hand.",
    ),
    (
        1,
        "The Magician",
        "Manifestation, willpower, skill, and using all available tools.",
        "Manipulation, wasted talent, and trickery.",
        "A robed figure at an altar with cup, sword, pentacle, and wand, infinity sign overhead.",
    ),
    (
        2,
        "The High Priestess",
        "Intuition, hidden knowledge, and quiet inner wisdom.",
        "Secrets withheld, blocked intuition, and surface-level thinking.",
        "A veiled priestess seated between two pillars, crescent moon at her feet, scroll on her lap.",
    ),
    (
        3,
        "The Empress",
        "Abundance, nurturing, fertility, and creative flourishing.",
        "Smothering, dependence, and creative blockage.",
        "A crowned woman on a cushioned throne in a wheat field, surrounded by lush nature.",
    ),
    (
        4,
        "The Emperor",
        "Authority, structure, stability, and disciplined leadership.",
        "Rigidity, domineering control, and abuse of power.",
        "A bearded ruler on a stone throne carved with rams' heads, scepter and orb in hand.",
    ),
    (
        5,
        "The Hierophant",
        "Tradition, spiritual guidance, and conformity to shared values.",
        "Rebellion against convention and dogmatic thinking.",
        "A robed pontiff between two pillars blessing two acolytes, triple crown on his head.",
    ),
    (
        6,
        "The Lovers",
        "Love, deep partnership, alignment of values, and meaningful choice.",
        "Disharmony, misalignment, and avoidance of commitment.",
        "A naked couple beneath a winged angel and a radiant sun, garden of Eden behind them.",
    ),
    (
        7,
        "The Chariot",
        "Determined drive forward, willpower, and victory through focus.",
        "Loss of direction, scattered effort, and aggression.",
        "An armoured charioteer drawn by a black and a white sphinx, starry canopy above.",
    ),
    (
        8,
        "Strength",
        "Inner strength, courage, gentle power, and patient mastery.",
        "Self-doubt, weakness, and uncontrolled emotion.",
        "A woman in a white robe gently closing the jaws of a lion, infinity symbol over her head.",
    ),
    (
        9,
        "The Hermit",
        "Introspection, solitary search for truth, and inner guidance.",
        "Isolation, withdrawal, and refusing wise counsel.",
        "A grey-cloaked old man on a snowy peak holding a glowing lantern and a wooden staff.",
    ),
    (
        10,
        "Wheel of Fortune",
        "Cycles, turning points, fortune, and the unfolding of fate.",
        "Bad luck, resistance to change, and broken cycles.",
        "A great wheel in the clouds with a sphinx, anubis, and snake, four winged creatures in the corners.",
    ),
    (
        11,
        "Justice",
        "Fairness, truth, accountability, and balanced cause and effect.",
        "Unfairness, dishonesty, and avoidance of responsibility.",
        "A robed judge on a throne holding an upright sword and balanced scales.",
    ),
    (
        12,
        "The Hanged Man",
        "Suspension, surrender, new perspective, and willing pause.",
        "Stagnation, useless sacrifice, and stalled progress.",
        "A serene man hanging upside-down by one foot from a living wooden cross, halo around his head.",
    ),
    (
        13,
        "Death",
        "Endings, transformation, and the clearing away of the old.",
        "Resistance to change, lingering on the past, and slow transitions.",
        "A skeletal armoured rider on a white horse carrying a black banner with a white rose.",
    ),
    (
        14,
        "Temperance",
        "Balance, moderation, patient blending, and harmonious flow.",
        "Imbalance, excess, and impatience.",
        "A winged angel pouring water between two cups, one foot on land and one in a stream.",
    ),
    (
        15,
        "The Devil",
        "Bondage, addiction, materialism, and shadow patterns.",
        "Breaking free, releasing limiting beliefs, and reclaiming power.",
        "A horned figure on a black pedestal, two chained naked figures at his feet, inverted pentagram above.",
    ),
    (
        16,
        "The Tower",
        "Sudden upheaval, revelation, collapse of false structures, and shock.",
        "Averted disaster, fear of change, and slow-burning crisis.",
        "A tall stone tower struck by lightning, crown flying off, two figures falling.",
    ),
    (
        17,
        "The Star",
        "Hope, renewal, gentle inspiration, and quiet faith.",
        "Despair, disconnection, and loss of inspiration.",
        "A naked woman kneeling by a pool pouring water from two jugs under a bright eight-pointed star.",
    ),
    (
        18,
        "The Moon",
        "Illusion, dreams, intuition, and navigation through uncertainty.",
        "Confusion lifting, repressed fears returning, and clarity slowly emerging.",
        "A full moon between two towers, a dog and a wolf howling at it, a crayfish emerging from a pool.",
    ),
    (
        19,
        "The Sun",
        "Joy, vitality, success, and warm clarity.",
        "Temporary clouds over success, dimmed enthusiasm, and false optimism.",
        "A radiant sun over a child riding a white horse before a wall of bright sunflowers.",
    ),
    (
        20,
        "Judgement",
        "Awakening, calling, reckoning, and a profound second chance.",
        "Self-doubt, ignored calling, and harsh self-judgement.",
        "An angel with a trumpet above clouds while figures rise from open coffins in the sea below.",
    ),
    (
        21,
        "The World",
        "Completion, integration, fulfilment, and successful closure of a cycle.",
        "Unfinished business, lingering loose ends, and delayed completion.",
        "A dancing figure inside a laurel wreath, a winged creature in each corner of the scene.",
    ),
)


# ---------------------------------------------------------------------------
# Minor arcana — four suits × 14 ranks.
# Each suit row: (suit, suit-symbol-description)
# Each rank row: (rankId, rankDisplay, upright, reversed, fragmentTemplate)
# The fragment template uses ``{suitVisual}`` to splice in the suit's visual.
# ---------------------------------------------------------------------------

_SUITS: Tuple[Tuple[str, str], ...] = (
    ("wands", "wooden flowering wand"),
    ("cups", "ornate golden chalice"),
    ("swords", "upright sword"),
    ("pentacles", "golden coin engraved with a pentacle"),
)


_RANKS: Tuple[Tuple[str, str, str, str, str], ...] = (
    (
        "ace",
        "Ace",
        "A clear new beginning and pure potential of the suit.",
        "Blocked potential and a stalled new start.",
        "A glowing hand emerging from a cloud holding a single {suitVisual}.",
    ),
    (
        "02",
        "Two",
        "A meaningful choice, partnership, or balance of two forces.",
        "Indecision and broken cooperation.",
        "Two {suitVisual}s held in considered balance against a calm landscape.",
    ),
    (
        "03",
        "Three",
        "Early growth, collaboration, and the first results of a venture.",
        "Lack of teamwork and slowed progress.",
        "Three {suitVisual}s arranged together with a figure surveying the horizon.",
    ),
    (
        "04",
        "Four",
        "Stability, rest, and a moment of consolidation.",
        "Restlessness, stagnation, and rejected stability.",
        "Four {suitVisual}s framing a figure pausing in quiet repose.",
    ),
    (
        "05",
        "Five",
        "Conflict, loss, or a difficult turning point in the suit's affairs.",
        "Recovery from conflict and slow rebuilding.",
        "Five {suitVisual}s scattered around figures in tension or disagreement.",
    ),
    (
        "06",
        "Six",
        "Harmony restored, generosity, and progress after struggle.",
        "Imbalance returning and unequal exchanges.",
        "Six {suitVisual}s arranged in graceful order while a figure shares with another.",
    ),
    (
        "07",
        "Seven",
        "Reflection, evaluation, and choosing among several options.",
        "Confusion, scattered focus, and poor evaluation.",
        "Seven {suitVisual}s spread before a thoughtful figure weighing options.",
    ),
    (
        "08",
        "Eight",
        "Movement, mastery, and sustained effort toward a goal.",
        "Misdirected effort and slow progress.",
        "Eight {suitVisual}s aligned in dynamic motion as a figure works steadily.",
    ),
    (
        "09",
        "Nine",
        "Near-completion, resilience, and a strong personal position.",
        "Inner unease and lingering doubts before completion.",
        "Nine {suitVisual}s assembled around a watchful figure standing their ground.",
    ),
    (
        "10",
        "Ten",
        "Completion of a cycle and the full weight of the suit's lessons.",
        "Burden, exhaustion, and unfinished business.",
        "Ten {suitVisual}s gathered as a figure carries or contemplates the full set.",
    ),
    (
        "page",
        "Page",
        "Curiosity, fresh learning, and a youthful approach to the suit.",
        "Immaturity and unfocused enthusiasm.",
        "A young figure in fine clothes holding a single {suitVisual} with eager attention.",
    ),
    (
        "knight",
        "Knight",
        "Action, pursuit, and energetic forward movement.",
        "Recklessness, impulsiveness, or stalled momentum.",
        "An armoured knight on a horse charging forward with a {suitVisual} raised.",
    ),
    (
        "queen",
        "Queen",
        "Mature mastery, nurturing influence, and grounded competence.",
        "Coldness, self-absorption, and misuse of influence.",
        "A regal queen on an ornate throne cradling a {suitVisual} with thoughtful poise.",
    ),
    (
        "king",
        "King",
        "Authoritative mastery, leadership, and seasoned wisdom.",
        "Tyranny, abuse of authority, and rigidity.",
        "A crowned king on a stone throne holding a {suitVisual} with commanding presence.",
    ),
)


def _formatRankName(rankId: str, rankDisplay: str, suit: str) -> str:
    """Format a minor-arcana card's English name from its rank and suit.

    Args:
        rankId: Machine rank identifier (``"ace"``, ``"02"`` … ``"king"``).
        rankDisplay: Human-readable rank (``"Ace"``, ``"Two"``, ``"King"`` …).
        suit: Lowercase suit identifier (``"wands"``, ``"cups"``, …).

    Returns:
        Standard English card name, e.g. ``"Two of Wands"`` or
        ``"King of Cups"``.
    """
    suitTitle: str = suit.capitalize()
    return f"{rankDisplay} of {suitTitle}"


def _buildDeck() -> Tuple[Symbol, ...]:
    """Assemble the full 78-card RWS deck as :class:`Symbol` objects.

    Returns:
        Tuple of 78 symbols: 22 majors followed by 56 minors (4 suits ×
        14 ranks).
    """
    cards: List[Symbol] = []

    for number, name, upright, reversed_, fragment in _MAJORS:
        majorMetadata: Dict[str, Any] = {"arcana": "major", "number": number}
        cardId: str = f"major_{number:02d}_{name.replace('The ', '').replace(' ', '_').lower()}"
        cards.append(
            Symbol(
                id=cardId,
                name=name,
                meaningUpright=upright,
                meaningReversed=reversed_,
                imagePromptFragment=fragment,
                metadata=majorMetadata,
            )
        )

    for suit, suitVisual in _SUITS:
        for rankId, rankDisplay, upright, reversed_, fragmentTemplate in _RANKS:
            minorName: str = _formatRankName(rankId, rankDisplay, suit)
            minorId: str = f"{suit}_{rankId}"
            minorMetadata: Dict[str, Any] = {
                "arcana": "minor",
                "suit": suit,
                "rank": rankId,
            }
            cards.append(
                Symbol(
                    id=minorId,
                    name=minorName,
                    meaningUpright=upright,
                    meaningReversed=reversed_,
                    imagePromptFragment=fragmentTemplate.format(suitVisual=suitVisual),
                    metadata=minorMetadata,
                )
            )

    return tuple(cards)


TAROT_RWS_DECK: Tuple[Symbol, ...] = _buildDeck()
