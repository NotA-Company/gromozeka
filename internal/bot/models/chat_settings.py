"""
Telegram bot chat settings.
"""

import logging
from enum import IntEnum, StrEnum, auto
from typing import Any, Dict, List, TypedDict

from lib.ai.abstract import AbstractModel
from lib.ai.manager import LLMManager

logger = logging.getLogger(__name__)


class ChatSettingsPage(IntEnum):
    """Page, where Setting is located"""

    STANDART = auto()
    EXTENDED = auto()

    def getName(self) -> str:
        match self:
            case ChatSettingsPage.STANDART:
                return "Стандартные настройки"
            case ChatSettingsPage.EXTENDED:
                return "Расширенные настройки"
            case _:
                return f"{self.name}"


class ChatSettingsType(StrEnum):
    """Enum for chat settings."""

    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    MODEL = "model"  # Model Name, can be choosen from list of choosable models


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
    ChatSettingsKey.CHAT_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Системный промпт для чата",
        "long": 'Влияет на "личность" бота.',
        "page": ChatSettingsPage.STANDART,
    },
    ChatSettingsKey.CHAT_MODEL: {
        "type": ChatSettingsType.MODEL,
        "short": "LLM-Модель для общения в чате",
        "long": "Какую LLM модель использовать для общения в чате",
        "page": ChatSettingsPage.STANDART,
    },
    ChatSettingsKey.SUMMARY_MODEL: {
        "type": ChatSettingsType.MODEL,
        "short": "LLM-Модель для суммаризации",
        "long": "Какую LLM модель использовать для суммаризации сообщений",
        "page": ChatSettingsPage.STANDART,
    },
    ChatSettingsKey.BOT_NICKNAMES: {
        "type": ChatSettingsType.STRING,
        "short": "Список никнеймов бота",
        "long": "Бот будет отзываться на эти имена, если оно стоит первым в сообщении пользователя",
        "page": ChatSettingsPage.EXTENDED,
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
        "page": ChatSettingsPage.EXTENDED,
    },
    ChatSettingsKey.PARSE_ATTACHMENTS: {
        "type": ChatSettingsType.BOOL,
        "short": "Обрабатывать изображения",
        "long": "Должен ли бот анализировать изображения используя LLM для дальнейшего использования в разговоре",
        "page": ChatSettingsPage.STANDART,
    },
    ChatSettingsKey.DELETE_DENIED_COMMANDS: {
        "type": ChatSettingsType.BOOL,
        "short": "Удалять запрещенные команды",
        "long": "Должен ли бот удалять сообщения с командами, которые не разрешены в настройках чата "
        "(полезно для предотвращения флуда нечайными кликами на команду)",
        "page": ChatSettingsPage.STANDART,
    },
    ChatSettingsKey.ALLOW_TOOLS_COMMANDS: {
        "type": ChatSettingsType.BOOL,
        "short": "Разрешить команды использования инструментов (`/draw`, ...)",
        "long": "Разрешить команды использования различных инструментов (Например `/draw`, `/analyze` и т.д.)",
        "page": ChatSettingsPage.STANDART,
    },
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
    ChatSettingsKey.ALLOW_USER_SPAM_COMMAND: {
        "type": ChatSettingsType.BOOL,
        "short": "Разрешить не админам использовать команду spam",
        "long": (
            "Разрешить не админам использовать команду `/spam` "
            "для удаления всех сообщений пользователя и его блокировки"
        ),
        "page": ChatSettingsPage.STANDART,
    },
    ChatSettingsKey.DETECT_SPAM: {
        "type": ChatSettingsType.BOOL,
        "short": "Автоматически проверять на спам",
        "long": "Автоматически проверять сообщения новых пользователей на спам",
        "page": ChatSettingsPage.STANDART,
    },
    ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: {
        "type": ChatSettingsType.INT,
        "short": "Максимальное количество сообщений для спам-проверки",
        "long": (
            "Пользователи, у которых в чате больше указанного количества "
            "сообщений не будут проверяться на спам (0 - всегда проверять)"
        ),
        "page": ChatSettingsPage.EXTENDED,
    },
    ChatSettingsKey.SPAM_DELETE_ALL_USER_MESSAGES: {
        "type": ChatSettingsType.BOOL,
        "short": "Удалять все сообщения пользователя при помечании спаммером",
        "long": (
            "Удалять все сообщения пользователя, когда пользователь признан "
            "спаммером (автоматически или при помощи команды `/spam`)"
        ),
        "page": ChatSettingsPage.EXTENDED,
    },
    ChatSettingsKey.ALLOW_MARK_SPAM_OLD_USERS: {
        "type": ChatSettingsType.BOOL,
        "short": "Разрешить помечать старых пользователей спаммером",
        "long": (
            "Разрешить помечать пользователей, (у которых больше устеновленного количества "
            "сообщений в чате), как спаммеров при помощи команды `/spam` \n"
            "(Используется для того, что бы исклюить ошибки и очепятки)"
        ),
        "page": ChatSettingsPage.EXTENDED,
    },
    ChatSettingsKey.SPAM_WARN_TRESHOLD: {
        "type": ChatSettingsType.FLOAT,
        "short": "SPAM-Порог для предупреждения пользователя",
        "long": ("Порог для предупреждения пользователя при автоматической проверке на спам" "(0-100)"),
        "page": ChatSettingsPage.EXTENDED,
    },
    ChatSettingsKey.SPAM_BAN_TRESHOLD: {
        "type": ChatSettingsType.FLOAT,
        "short": "SPAM-Порог для блокировки пользователя",
        "long": ("Порог для блокировки пользователя при автоматической проверке на спам" "(0-100)"),
        "page": ChatSettingsPage.EXTENDED,
    },
    # Bayes filter settings, dood!
    ChatSettingsKey.BAYES_ENABLED: {
        "type": ChatSettingsType.BOOL,
        "short": "Включить Bayes фильтр спама",
        "long": (
            "Включить использование Bayes фильтра для более точного определения спама. "
            "Фильтр обучается на основе помеченных спам сообщений и обычных сообщений пользователей."
        ),
        "page": ChatSettingsPage.STANDART,
    },
    ChatSettingsKey.BAYES_MIN_CONFIDENCE: {
        "type": ChatSettingsType.FLOAT,
        "short": "Минимальная уверенность Bayes фильтра",
        "long": (
            "Минимальная уверенность Bayes фильтра для принятия решения (0.0-1.0). "
            "Если уверенность ниже, результат Bayes фильтра игнорируется."
        ),
        "page": ChatSettingsPage.EXTENDED,
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
        "page": ChatSettingsPage.EXTENDED,
    },
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
}


def getChatSettingsInfo() -> Dict[ChatSettingsKey, ChatSettingsInfoValue]:
    # TODO: Add ability to return different settings for diffenet chats in future
    return _chatSettingsInfo.copy()
