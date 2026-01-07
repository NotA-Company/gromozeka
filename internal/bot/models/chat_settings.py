"""
Telegram bot chat settings.
"""

import logging
from enum import IntEnum, StrEnum, auto
from typing import Any, Dict, List, Optional, Self, TypedDict

from lib.ai.abstract import AbstractModel
from lib.ai.manager import LLMManager

logger = logging.getLogger(__name__)


class ChatTier(StrEnum):

    BANNED = "banned"
    """Tier for banned users"""
    FREE = "free"
    """Tier for free chats"""
    FREE_PERSONAL = "free-personal"
    """Tier for free private chats, allow a bit more"""

    PAID = "paid"
    """Paid chats of users"""

    FRIEND = "friend"
    """Friends with maximum abilities"""
    BOT_OWNER = "bot_owner"
    """Bot owners - can do anything"""

    def getId(self) -> int:
        """Return some unique id
        WARNING: Do not store it anywhere, it can be changed on app reload
        """
        # Use element index
        return list(self.__class__).index(self) + 1

    @classmethod
    def fromId(cls, value: int) -> Self:
        """Get value by it's int id"""
        try:
            return list(cls)[value - 1]
        except IndexError:
            raise ValueError(f"No {cls.__name__} with numeric value {value}")

    def isBetterOrEqualThan(self, other: Self) -> bool:
        return self.getId() >= other.getId()

    @classmethod
    def best(cls, *args: Self) -> Self:
        """Return the element with the highest ID from the provided arguments."""
        if not args:
            raise ValueError("At least one argument is required")

        return max(args, key=lambda x: x.getId())

    @classmethod
    def fromStr(cls, v: str) -> Optional[Self]:
        """Return chat tier from string. Or none if wrong sting passed"""
        try:
            return cls(v)
        except ValueError:
            return None


class ChatSettingsPage(IntEnum):
    """Page, where Setting is located"""

    STANDART = auto()
    EXTENDED = auto()
    SPAM = auto()

    LLM_BASE = auto()
    LLM_PAID = auto()

    PAID = auto()
    FRIEND = auto()
    BOT_OWNER = auto()
    BOT_OWNER_SYSTEM = auto()

    def getName(self) -> str:
        match self:
            case ChatSettingsPage.STANDART:
                return "Стандартные настройки"
            case ChatSettingsPage.EXTENDED:
                return "Расширенные настройки"
            case ChatSettingsPage.SPAM:
                return "Настройки работы со СПАМом"
            case ChatSettingsPage.LLM_BASE:
                return "Базовые настройки LLM"
            case ChatSettingsPage.LLM_PAID:
                return "Премиум настройки LLM"
            case ChatSettingsPage.PAID:
                return "Премиум настройки"
            case ChatSettingsPage.FRIEND:
                return "Настройки для самых важных"
            case ChatSettingsPage.BOT_OWNER:
                return "Только для владельцев"
            case ChatSettingsPage.BOT_OWNER_SYSTEM:
                return "Системные настройки (не трогать)"
            case _:
                return f"{self.name}"

    def minTier(self) -> ChatTier:
        match self:
            case ChatSettingsPage.STANDART:
                return ChatTier.FREE
            case ChatSettingsPage.EXTENDED:
                return ChatTier.FREE
            case ChatSettingsPage.SPAM:
                return ChatTier.FREE
            case ChatSettingsPage.LLM_BASE:
                return ChatTier.FREE
            case ChatSettingsPage.LLM_PAID:
                return ChatTier.PAID
            case ChatSettingsPage.PAID:
                return ChatTier.PAID
            case ChatSettingsPage.FRIEND:
                return ChatTier.FRIEND
            case ChatSettingsPage.BOT_OWNER:
                return ChatTier.BOT_OWNER
            case ChatSettingsPage.BOT_OWNER_SYSTEM:
                return ChatTier.BOT_OWNER
            case _:
                raise NotImplementedError(f"Page {self} has no minTier configured")

    def next(self) -> Optional[Self]:
        """
        Return next page in enum order.

        Returns:
            Next ChatSettingsPage if it exists, None if current page is the last one.
        """
        allPages = list(self.__class__)
        currentIndex = allPages.index(self)
        nextIndex = currentIndex + 1

        if nextIndex < len(allPages):
            return allPages[nextIndex]
        return None


class ChatSettingsType(StrEnum):
    """Enum for chat settings."""

    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    MODEL = "model"
    """Model Name, can be choosen from list of choosable models"""
    IMAGE_MODEL = "image-model"
    """Image-generation model name, can be choosen from list of choosable models"""


class ChatSettingsKey(StrEnum):
    """Enum for chat settings."""

    UNKNOWN = "unknown"

    # # LLM Models
    CHAT_MODEL = "chat-model"
    FALLBACK_MODEL = "fallback-model"
    SUMMARY_MODEL = "summary-model"
    SUMMARY_FALLBACK_MODEL = "summary-fallback-model"
    IMAGE_PARSING_MODEL = "image-parsing-model"
    IMAGE_PARSING_FALLBACK_MODEL = "image-parsing-fallback-model"
    IMAGE_GENERATION_MODEL = "image-generation-model"
    IMAGE_GENERATION_FALLBACK_MODEL = "image-generation-fallback-model"
    CONDENSING_MODEL = "condensing-model"

    # # Prompts for different actions
    SUMMARY_PROMPT = "summary-prompt"
    PARSE_IMAGE_PROMPT = "parse-image-prompt"
    CHAT_PROMPT = "chat-prompt"
    CHAT_PROMPT_SUFFIX = "chat-prompt-suffix"
    CONDENSING_PROMPT = "condensing-prompt"

    # # Some system settings
    ADMIN_CAN_CHANGE_SETTINGS = "admin-can-change-settings"
    BOT_NICKNAMES = "bot-nicknames"
    LLM_MESSAGE_FORMAT = "llm-message-format"
    USE_TOOLS = "use-tools"
    PARSE_ATTACHMENTS = "parse-attachments"

    SAVE_ATTACHMENTS = "save-attachments"
    SAVE_PREFIX = "save-prefix"

    TOOLS_USED_PREFIX = "tools-used-prefix"
    FALLBACK_HAPPENED_PREFIX = "fallback-happened-prefix"

    # # Allowing different commands in chat
    ALLOW_TOOLS_COMMANDS = "allow-tools-commands"
    # Should bot delete /command command if command wasn't allowed
    DELETE_DENIED_COMMANDS = "delete-denied-commands"

    # # Allowing different reactions in chat (to mention/reply/random)
    ALLOW_MENTION = "allow-mention"
    ALLOW_REPLY = "allow-reply"
    RANDOM_ANSWER_PROBABILITY = "random-answer-probability"
    RANDOM_ANSWER_TO_ADMIN = "random-answer-to-admin"

    # # Spam-related settings
    ALLOW_USER_SPAM_COMMAND = "allow-user-spam-command"
    SPAM_DELETE_ALL_USER_MESSAGES = "spam-delete-all-user-messages"
    DETECT_SPAM = "detect-spam"
    AUTO_SPAM_MAX_MESSAGES = "auto-spam-max-messages"
    ALLOW_MARK_SPAM_OLD_USERS = "allow-mark-spam-old-users"
    SPAM_BAN_TRESHOLD = "spam-ban-treshold"
    SPAM_WARN_TRESHOLD = "spam-warn-treshold"

    # # Bayes filter settings, dood!
    BAYES_ENABLED = "bayes-enabled"
    BAYES_MIN_CONFIDENCE = "bayes-min-confidence"
    BAYES_AUTO_LEARN = "bayes-auto-learn"
    BAYES_USE_TRIGRAMS = "bayes-use-trigrams"

    # # Reaction settings
    # JSON-serialized Dict(userID|"username" -> "emoji")
    REACTION_AUTHOR_TO_EMOJI_MAP = "reaction-author-to-emoji-map"

    #
    DELETE_JOIN_MESSAGES = "delete-join-messages"
    DELETE_LEFT_MESSAGES = "delete-left-messages"

    # Tier-related
    BASE_TIER = "base-tier"
    PAID_TIER = "paid-tier"
    PAID_TIER_UNTILL_TS = "paid-tier-untill-ts"

    # System settings. Not to be used\configured
    CACHED_TS = "cached-ts"
    """TS when chat settings were cached, to be used in Cache Service only"""

    def getId(self) -> int:
        """Return some unique id
        WARNING: Do not store it anywhere, it can be changed on app reload
        """
        # Используем hash или порядковый номер
        return list(self.__class__).index(self) + 1

    @classmethod
    def fromId(cls, value: int) -> "ChatSettingsKey":
        """Get value by it's int id"""
        try:
            return list(cls)[value - 1]
        except IndexError:
            raise ValueError(f"No {cls.__name__} with numeric value {value}")


class ChatSettingsValue:
    """Value of chat settings."""

    __slots__ = ("value",)

    def __init__(self, value: Any):
        self.value = str(value).strip()

    def __str__(self) -> str:
        return self.toStr()

    def toStr(self) -> str:
        return str(self.value)

    def toInt(self) -> int:
        try:
            return int(self.value)
        except ValueError:
            logger.error(f"Failed to convert {self.value} to int")
            return 0

    def toFloat(self) -> float:
        try:
            return float(self.value)
        except ValueError:
            logger.error(f"Failed to convert {self.value} to float")
            return 0.0

    def toBool(self) -> bool:
        return self.value.lower().strip() in ("true", "1")

    def toList(self, separator: str = ",", dropEmpty: bool = True) -> List[str]:
        return [x.strip() for x in self.value.split(separator) if x.strip() or not dropEmpty]

    def toModel(self, modelManager: LLMManager) -> AbstractModel:
        ret = modelManager.getModel(self.value)
        if ret is None:
            logger.error(f"Model {self.value} not found")
            raise ValueError(f"Model {self.value} not found")
        return ret


class ChatSettingsInfoValue(TypedDict):
    type: ChatSettingsType
    short: str
    long: str
    page: ChatSettingsPage


_chatSettingsInfo: Dict[ChatSettingsKey, ChatSettingsInfoValue] = {
    # # LLM Models
    ChatSettingsKey.CHAT_MODEL: {
        "type": ChatSettingsType.MODEL,
        "short": "LLM-Модель для общения в чате",
        "long": "Какую LLM модель использовать для общения в чате",
        "page": ChatSettingsPage.LLM_BASE,
    },
    ChatSettingsKey.FALLBACK_MODEL: {
        "type": ChatSettingsType.MODEL,
        "short": "Запасная LLM-Модель для общения в чате",
        "long": "Какую LLM модель использовать для общения в чат если основная не справилась",
        "page": ChatSettingsPage.LLM_PAID,
    },
    ChatSettingsKey.SUMMARY_MODEL: {
        "type": ChatSettingsType.MODEL,
        "short": "LLM-Модель для суммаризации",
        "long": "Какую LLM модель использовать для суммаризации сообщений",
        "page": ChatSettingsPage.LLM_BASE,
    },
    ChatSettingsKey.SUMMARY_FALLBACK_MODEL: {
        "type": ChatSettingsType.MODEL,
        "short": "Запасная LLM-Модель для суммаризации",
        "long": "Какую LLM модель использовать для суммаризации сообщений если основная не справилась",
        "page": ChatSettingsPage.LLM_PAID,
    },
    ChatSettingsKey.IMAGE_PARSING_MODEL: {
        "type": ChatSettingsType.MODEL,
        "short": "LLM-Модель для обработки изображений",
        "long": "Какую LLM модель использовать для обработки изображений",
        "page": ChatSettingsPage.LLM_BASE,
    },
    ChatSettingsKey.IMAGE_PARSING_FALLBACK_MODEL: {
        "type": ChatSettingsType.MODEL,
        "short": "Запасная LLM-Модель для обработки изображений",
        "long": "Какую LLM модель использовать для обработки изображений если основная не справилась",
        "page": ChatSettingsPage.LLM_PAID,
    },
    ChatSettingsKey.IMAGE_GENERATION_MODEL: {
        "type": ChatSettingsType.IMAGE_MODEL,
        "short": "LLM-Модель для создания изображений",
        "long": "Какую LLM модель использовать для создания изображений",
        "page": ChatSettingsPage.FRIEND,
    },
    ChatSettingsKey.IMAGE_GENERATION_FALLBACK_MODEL: {
        "type": ChatSettingsType.IMAGE_MODEL,
        "short": "Запасная LLM-Модель для создания изображений",
        "long": "Какую LLM модель использовать для обработки создания если основная не справилась",
        "page": ChatSettingsPage.FRIEND,
    },
    ChatSettingsKey.CONDENSING_MODEL: {
        "type": ChatSettingsType.MODEL,
        "short": "LLM-Модель для сжатия контекста",
        "long": "Какую LLM модель использовать для сжатия слишком большого контекста",
        "page": ChatSettingsPage.LLM_BASE,
    },
    # # Prompts for different actions
    ChatSettingsKey.SUMMARY_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Промпт для суммаризации",
        "long": "Промпт по умолчанию для скммаризации сообщений \n" "(можно изменить во время суммаризации)).",
        "page": ChatSettingsPage.LLM_BASE,
    },
    ChatSettingsKey.PARSE_IMAGE_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Промпт для анализа изображений",
        "long": "Промпт, используемый для анализа изображений.",
        "page": ChatSettingsPage.LLM_BASE,
    },
    ChatSettingsKey.CHAT_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Системный промпт для чата",
        "long": 'Влияет на "личность" бота.',
        "page": ChatSettingsPage.LLM_BASE,
    },
    ChatSettingsKey.CHAT_PROMPT_SUFFIX: {
        "type": ChatSettingsType.STRING,
        "short": "Суффикс системного промпт для чата",
        "long": "Не стоит это изменять кроме как для тестовых целей.",
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
    },
    ChatSettingsKey.CONDENSING_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Промпт для сжатия контекста",
        "long": "Промпт, используемый для сжатия контекста.",
        "page": ChatSettingsPage.LLM_BASE,
    },
    # # Some system settings
    ChatSettingsKey.ADMIN_CAN_CHANGE_SETTINGS: {
        "type": ChatSettingsType.BOOL,
        "short": "Могут ли админы менять настройки чата",
        "long": "Разрешить ли администраторам чата менять его настройки",
        "page": ChatSettingsPage.BOT_OWNER,
    },
    ChatSettingsKey.BOT_NICKNAMES: {
        "type": ChatSettingsType.STRING,
        "short": "Список никнеймов бота",
        "long": "Бот будет отзываться на эти имена, если оно стоит первым в сообщении пользователя",
        "page": ChatSettingsPage.EXTENDED,
    },
    ChatSettingsKey.LLM_MESSAGE_FORMAT: {
        "type": ChatSettingsType.STRING,
        "short": "Формат сообщений для LLM",
        "long": "В каком формате передавать сообщениы в LLM, возможные значения: text, json, smart.\n"
        "Не меняйте это значение кроме как в тестовых целях",
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
    },
    ChatSettingsKey.USE_TOOLS: {
        "type": ChatSettingsType.BOOL,
        "short": "Использовать ли инструменты",
        "long": (
            "Можно ли использовать боту различные инструменты?\n"
            "В данный момент доступны: \n"
            "1. Получение содержимого веб-страницы\n"
            "2. Генерация изображений\n"
            "3. Запоминение информации о пользователе\n"
            "4. Прогноз погоды\n"
            "5. Получение текущего времени\n"
            "6. Поиск по Интернету через Yandex Search API"
        ),
        "page": ChatSettingsPage.PAID,
    },
    ChatSettingsKey.PARSE_ATTACHMENTS: {
        "type": ChatSettingsType.BOOL,
        "short": "Обрабатывать вложения",
        "long": "Должен ли бот анализировать вложения используя LLM для дальнейшего использования в разговоре.\n"
        "В данный момент поддержана только обработка изображений и статичных стикеров.",
        "page": ChatSettingsPage.PAID,
    },
    ChatSettingsKey.SAVE_ATTACHMENTS: {
        "type": ChatSettingsType.BOOL,
        "short": "Сохранять вложения",
        "long": "Должен ли бот созранять вложения для дальнейшего использования.\n"
        "На данный момент полезно только для использования совместно с Resender-модулем.",
        "page": ChatSettingsPage.BOT_OWNER,
    },
    ChatSettingsKey.SAVE_PREFIX: {
        "type": ChatSettingsType.STRING,
        "short": "Префикс сохраненных файлов",
        "long": "Префикс для сохранённых файлов. Тебе оно не надо.",
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
    },
    ChatSettingsKey.TOOLS_USED_PREFIX: {
        "type": ChatSettingsType.STRING,
        "short": "Префикс для инструментов",
        "long": "Префикс у сообщения, если были использованы какие-либо инструменты",
        "page": ChatSettingsPage.EXTENDED,
    },
    ChatSettingsKey.FALLBACK_HAPPENED_PREFIX: {
        "type": ChatSettingsType.STRING,
        "short": "Префикс для ошибок",
        "long": "Префикс у сообщения если по каким либо причинам была использована запасная модель генерации текста",
        "page": ChatSettingsPage.EXTENDED,
    },
    ChatSettingsKey.ALLOW_TOOLS_COMMANDS: {
        "type": ChatSettingsType.BOOL,
        "short": "Разрешить команды использования инструментов (`/draw`, ...)",
        "long": "Разрешить команды использования различных инструментов (Например `/draw`, `/analyze` и т.д.)",
        "page": ChatSettingsPage.PAID,
    },
    ChatSettingsKey.DELETE_DENIED_COMMANDS: {
        "type": ChatSettingsType.BOOL,
        "short": "Удалять запрещенные команды",
        "long": "Должен ли бот удалять сообщения с командами, которые не разрешены в настройках чата "
        "(полезно для предотвращения флуда нечайными кликами на команду)",
        "page": ChatSettingsPage.STANDART,
    },
    # # Allowing different reactions in chat (to mention/reply/random)
    ChatSettingsKey.ALLOW_MENTION: {
        "type": ChatSettingsType.BOOL,
        "short": "Реагировать на упоминания",
        "long": "Должен ли бот реагировать на его упоминания в чате",
        "page": ChatSettingsPage.STANDART,
    },
    ChatSettingsKey.ALLOW_REPLY: {
        "type": ChatSettingsType.BOOL,
        "short": "Реагировать на ответы",
        "long": "Должен ли бот реагировать на ответы на его сообщения",
        "page": ChatSettingsPage.STANDART,
    },
    ChatSettingsKey.RANDOM_ANSWER_PROBABILITY: {
        "type": ChatSettingsType.FLOAT,
        "short": "Вероятность случайного ответа",
        "long": "(0-1) Вероятность, что бот решит ответить на произвольное сообщение в чате",
        "page": ChatSettingsPage.STANDART,
    },
    ChatSettingsKey.RANDOM_ANSWER_TO_ADMIN: {
        "type": ChatSettingsType.BOOL,
        "short": "Случайный ответ на сообщений админов",
        "long": "Отвечать ли при этом на сообщения администраторов чата",
        "page": ChatSettingsPage.EXTENDED,
    },
    # # Spam-related settings
    ChatSettingsKey.ALLOW_USER_SPAM_COMMAND: {
        "type": ChatSettingsType.BOOL,
        "short": "Разрешить не админам использовать команду spam",
        "long": (
            "Разрешить не админам использовать команду `/spam` "
            "для удаления всех сообщений пользователя и его блокировки"
        ),
        "page": ChatSettingsPage.SPAM,
    },
    ChatSettingsKey.SPAM_DELETE_ALL_USER_MESSAGES: {
        "type": ChatSettingsType.BOOL,
        "short": "Удалять все сообщения пользователя при помечании спаммером",
        "long": (
            "Удалять все сообщения пользователя, когда пользователь признан "
            "спаммером (автоматически или при помощи команды `/spam`)"
        ),
        "page": ChatSettingsPage.SPAM,
    },
    ChatSettingsKey.DETECT_SPAM: {
        "type": ChatSettingsType.BOOL,
        "short": "Автоматически проверять на спам",
        "long": "Автоматически проверять сообщения новых пользователей на спам",
        "page": ChatSettingsPage.SPAM,
    },
    ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: {
        "type": ChatSettingsType.INT,
        "short": "Максимальное количество сообщений для спам-проверки",
        "long": (
            "Пользователи, у которых в чате больше указанного количества "
            "сообщений не будут проверяться на спам (0 - всегда проверять)"
        ),
        "page": ChatSettingsPage.SPAM,
    },
    ChatSettingsKey.ALLOW_MARK_SPAM_OLD_USERS: {
        "type": ChatSettingsType.BOOL,
        "short": "Разрешить помечать старых пользователей спаммером",
        "long": (
            "Разрешить помечать пользователей, (у которых больше устеновленного количества "
            "сообщений в чате), как спаммеров при помощи команды `/spam` \n"
            "(Используется для того, что бы исклюить ошибки и очепятки)"
        ),
        "page": ChatSettingsPage.SPAM,
    },
    ChatSettingsKey.SPAM_WARN_TRESHOLD: {
        "type": ChatSettingsType.FLOAT,
        "short": "SPAM-Порог для предупреждения пользователя",
        "long": ("Порог для предупреждения пользователя при автоматической проверке на спам" "(0-100)"),
        "page": ChatSettingsPage.SPAM,
    },
    ChatSettingsKey.SPAM_BAN_TRESHOLD: {
        "type": ChatSettingsType.FLOAT,
        "short": "SPAM-Порог для блокировки пользователя",
        "long": ("Порог для блокировки пользователя при автоматической проверке на спам" "(0-100)"),
        "page": ChatSettingsPage.SPAM,
    },
    # # Bayes filter settings, dood!
    ChatSettingsKey.BAYES_ENABLED: {
        "type": ChatSettingsType.BOOL,
        "short": "Включить Bayes фильтр спама",
        "long": (
            "Включить использование Bayes фильтра для более точного определения спама. "
            "Фильтр обучается на основе помеченных спам сообщений и обычных сообщений пользователей."
        ),
        "page": ChatSettingsPage.SPAM,
    },
    ChatSettingsKey.BAYES_MIN_CONFIDENCE: {
        "type": ChatSettingsType.FLOAT,
        "short": "Минимальная уверенность Bayes фильтра",
        "long": (
            "Минимальная уверенность Bayes фильтра для принятия решения (0.0-1.0). "
            "Если уверенность ниже, результат Bayes фильтра игнорируется."
        ),
        "page": ChatSettingsPage.SPAM,
    },
    ChatSettingsKey.BAYES_AUTO_LEARN: {
        "type": ChatSettingsType.BOOL,
        "short": "Автоматическое обучение Bayes фильтра",
        "long": (
            "Автоматически обучать Bayes фильтр на помеченных спам "
            "сообщениях и обычных сообщениях пользователей. "
            "Рекомендуется включить для улучшения точности "
            "определения спама со временем."
        ),
        "page": ChatSettingsPage.SPAM,
    },
    ChatSettingsKey.BAYES_USE_TRIGRAMS: {
        "type": ChatSettingsType.BOOL,
        "short": "Использовать триграммы в Bayes фильтре",
        "long": (
            "Использование триграмм в Bayes фильтре для более точного определения спама. "
            "Наиболее полезны только когда достаточно много сообщений в баазе данных. "
        ),
        "page": ChatSettingsPage.SPAM,
    },
    # # Reaction settings
    ChatSettingsKey.REACTION_AUTHOR_TO_EMOJI_MAP: {
        "type": ChatSettingsType.STRING,
        "short": "JSON-маппинг автора сообщения к реакции",
        "long": ("Используй команды `/set_reaction`|`/unset_reaction` для управления этой настройкой."),
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
    },
    #
    ChatSettingsKey.DELETE_JOIN_MESSAGES: {
        "type": ChatSettingsType.BOOL,
        "short": "Удалять сообщение о присоединении пользователя",
        "long": "Удалять сообщение о присоединении пользователя к чату.",
        "page": ChatSettingsPage.STANDART,
    },
    ChatSettingsKey.DELETE_LEFT_MESSAGES: {
        "type": ChatSettingsType.BOOL,
        "short": "Удалять сообщение о выходе пользователя",
        "long": "Удалять сообщение о выходе пользователя из чата.",
        "page": ChatSettingsPage.STANDART,
    },
    # Tier-related
    ChatSettingsKey.BASE_TIER: {
        "type": ChatSettingsType.STRING,
        "short": "Tier чата",
        "long": f"Tier чата, Возможные значения: {['`' + v.value + '`' for v in ChatTier]}.",
        "page": ChatSettingsPage.BOT_OWNER,
    },
    ChatSettingsKey.PAID_TIER: {
        "type": ChatSettingsType.STRING,
        "short": "Оплаченный Tier чата",
        "long": "Tier чата на время наличия оплаты. Скорее всего не стоит менять это значение.",
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
    },
    ChatSettingsKey.PAID_TIER_UNTILL_TS: {
        "type": ChatSettingsType.FLOAT,
        "short": "Время действия платного Tier чата",
        "long": "Таймштамп, до которого оплачен Tier чата. Скорее всего не стоит менять это значение.",
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
    },
}


def getChatSettingsInfo() -> Dict[ChatSettingsKey, ChatSettingsInfoValue]:
    # TODO: Add ability to return different settings for diffenet chats in future
    return _chatSettingsInfo.copy()
