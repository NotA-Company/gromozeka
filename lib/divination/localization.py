"""Static localisation tables for divination symbol names, layout names and
positions, dood!

English is the source of truth in :mod:`lib.divination`; this module pairs
each English string with localised forms keyed by language code. Only
``"ru"`` is filled in v1 — missing languages fall back to the English
original via :func:`tr`.

Adding a new language is a data-only change: extend the existing dicts.
Adding a new symbol/layout/position requires both the English source-of-truth
(in the deck or layout file) **and** an entry here — the
``test_localization.py`` collocated test enforces full coverage.
"""

from typing import Dict, Mapping

# ---------------------------------------------------------------------------
# Symbol names — both decks combined.
# Each top-level dict is keyed by Symbol.name; values are
# ``{langCode: localised}``.
# ---------------------------------------------------------------------------

# Major arcana (English -> Russian).
_MAJOR_ARCANA_RU: Dict[str, str] = {
    "The Fool": "Шут",
    "The Magician": "Маг",
    "The High Priestess": "Верховная Жрица",
    "The Empress": "Императрица",
    "The Emperor": "Император",
    "The Hierophant": "Иерофант",
    "The Lovers": "Влюблённые",
    "The Chariot": "Колесница",
    "Strength": "Сила",
    "The Hermit": "Отшельник",
    "Wheel of Fortune": "Колесо Фортуны",
    "Justice": "Справедливость",
    "The Hanged Man": "Повешенный",
    "Death": "Смерть",
    "Temperance": "Умеренность",
    "The Devil": "Дьявол",
    "The Tower": "Башня",
    "The Star": "Звезда",
    "The Moon": "Луна",
    "The Sun": "Солнце",
    "Judgement": "Суд",
    "The World": "Мир",
}

# Minor arcana — assembled programmatically from rank × suit Russian forms
# below to keep the table compact and free of typos.
_RANK_RU: Dict[str, str] = {
    "Ace": "Туз",
    "Two": "Двойка",
    "Three": "Тройка",
    "Four": "Четвёрка",
    "Five": "Пятёрка",
    "Six": "Шестёрка",
    "Seven": "Семёрка",
    "Eight": "Восьмёрка",
    "Nine": "Девятка",
    "Ten": "Десятка",
    "Page": "Паж",
    "Knight": "Рыцарь",
    "Queen": "Королева",
    "King": "Король",
}

# Genitive ("of <suit>") forms used in standard Russian tarot terminology.
_SUIT_RU_GENITIVE: Dict[str, str] = {
    "Wands": "Жезлов",
    "Cups": "Кубков",
    "Swords": "Мечей",
    "Pentacles": "Пентаклей",
}


def _buildMinorArcanaRu() -> Dict[str, str]:
    """Build the English→Russian minor-arcana name table.

    Returns:
        Mapping from English card name (e.g. ``"Two of Wands"``) to the
        Russian equivalent (e.g. ``"Двойка Жезлов"``).
    """
    table: Dict[str, str] = {}
    for englishRank, russianRank in _RANK_RU.items():
        for englishSuit, russianSuit in _SUIT_RU_GENITIVE.items():
            table[f"{englishRank} of {englishSuit}"] = f"{russianRank} {russianSuit}"
    return table


# Elder Futhark runes (transliterated to standard Russian forms).
_RUNES_RU: Dict[str, str] = {
    "Fehu": "Феху",
    "Uruz": "Уруз",
    "Thurisaz": "Турисаз",
    "Ansuz": "Ансуз",
    "Raidho": "Райдо",
    "Kenaz": "Кеназ",
    "Gebo": "Гебо",
    "Wunjo": "Вуньо",
    "Hagalaz": "Хагалаз",
    "Nauthiz": "Наутиз",
    "Isa": "Иса",
    "Jera": "Йера",
    "Eihwaz": "Эйваз",
    "Perthro": "Перт",
    "Algiz": "Альгиз",
    "Sowilo": "Соулу",
    "Tiwaz": "Тейваз",
    "Berkano": "Беркана",
    "Ehwaz": "Эваз",
    "Mannaz": "Манназ",
    "Laguz": "Лагуз",
    "Ingwaz": "Ингуз",
    "Dagaz": "Дагаз",
    "Othala": "Отал",
}


def _buildSymbolNames() -> Dict[str, Dict[str, str]]:
    """Combine major + minor arcana + runes into a single localisation table.

    Returns:
        Mapping from English Symbol name to ``{langCode: localised}``.
    """
    combinedRu: Dict[str, str] = {}
    combinedRu.update(_MAJOR_ARCANA_RU)
    combinedRu.update(_buildMinorArcanaRu())
    combinedRu.update(_RUNES_RU)
    return {englishName: {"ru": russianName} for englishName, russianName in combinedRu.items()}


SYMBOL_NAMES: Dict[str, Dict[str, str]] = _buildSymbolNames()
"""Localisation table for every :class:`Symbol.name` shipped in v1."""


POSITION_NAMES: Dict[str, Dict[str, str]] = {
    "Insight": {"ru": "Озарение"},
    "Past": {"ru": "Прошлое"},
    "Present": {"ru": "Настоящее"},
    "Future": {"ru": "Будущее"},
    "Challenge": {"ru": "Препятствие"},
    "Above": {"ru": "Над"},
    "Below": {"ru": "Под"},
    "Advice": {"ru": "Совет"},
    "External Influences": {"ru": "Внешние влияния"},
    "Hopes and Fears": {"ru": "Надежды и страхи"},
    "Outcome": {"ru": "Итог"},
    "You": {"ru": "Вы"},
    "Partner": {"ru": "Партнёр"},
    "Connection": {"ru": "Связь"},
    "Challenges": {"ru": "Препятствия"},
    "Answer": {"ru": "Ответ"},
    "Help": {"ru": "Помощь"},
    "Self": {"ru": "Я"},
    "Path": {"ru": "Путь"},
    "Hindrance": {"ru": "Помеха"},
    "Family": {"ru": "Семья"},
    "Hopes": {"ru": "Надежды"},
}
"""Localisation table for layout position names used in v1 layouts, dood!"""


LAYOUT_NAMES: Dict[str, Dict[str, str]] = {
    "One Card": {"ru": "Одна карта"},
    "Three-Card Spread": {"ru": "Расклад на три карты"},
    "Celtic Cross": {"ru": "Кельтский крест"},
    "Relationship Spread": {"ru": "Расклад на отношения"},
    "Yes/No": {"ru": "Да/Нет"},
    "One Rune": {"ru": "Одна руна"},
    "Three Norns": {"ru": "Три норны"},
    "Five-Rune Cross": {"ru": "Пятирунный крест"},
    "Nine-Rune Cast": {"ru": "Расклад на девять рун"},
}
"""Localisation table for the human-readable English names of every layout."""


def tr(table: Mapping[str, Mapping[str, str]], enKey: str, lang: str) -> str:
    """Translate ``enKey`` to ``lang`` using ``table``, dood!

    Falls back to ``enKey`` if either the key is missing entirely or the key
    is present but has no entry for ``lang``. This way callers can ask for
    any language without crashing — they just get the English original when
    a translation hasn't been added yet.

    Args:
        table: One of :data:`SYMBOL_NAMES`, :data:`POSITION_NAMES`,
            :data:`LAYOUT_NAMES`, or any other ``Mapping[str, Mapping[str, str]]``.
        enKey: English source-of-truth string.
        lang: Target language code (e.g. ``"ru"``).

    Returns:
        The localised string, or ``enKey`` on miss.
    """
    perLang: Mapping[str, str] = table.get(enKey, {})
    return perLang.get(lang, enKey)
