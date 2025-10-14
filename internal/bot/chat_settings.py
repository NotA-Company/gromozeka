"""
Telegram bot chat settings.
"""

from enum import StrEnum
import logging
from typing import Any, Dict, List, TypedDict

from lib.ai.abstract import AbstractModel
from lib.ai.manager import LLMManager

logger = logging.getLogger(__name__)


class ChatSettingsType(StrEnum):
    """Enum for chat settings."""

    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"


class ChatSettingsKey(StrEnum):
    """Enum for chat settings."""

    CHAT_MODEL = "chat-model"
    FALLBACK_MODEL = "fallback-model"
    SUMMARY_MODEL = "summary-model"
    SUMMARY_FALLBACK_MODEL = "summary-fallback-model"
    IMAGE_PARSING_MODEL = "image-parsing-model"
    IMAGE_GENERATION_MODEL = "image-generation-model"
    IMAGE_GENERATION_FALLBACK_MODEL = "image-generation-fallback-model"

    SUMMARY_PROMPT = "summary-prompt"
    PARSE_IMAGE_PROMPT = "parse-image-prompt"
    CHAT_PROMPT = "chat-prompt"
    CHAT_PROMPT_SUFFIX = "chat-prompt-suffix"

    ADMIN_CAN_CHANGE_SETTINGS = "admin-can-change-settings"
    BOT_NICKNAMES = "bot-nicknames"
    LLM_MESSAGE_FORMAT = "llm-message-format"
    USE_TOOLS = "use-tools"
    SAVE_IMAGES = "save-images"
    PARSE_IMAGES = "parse-images"
    OPTIMAL_IMAGE_SIZE = "optimal-image-size"

    TOOLS_USED_PREFIX = "tools-used-prefix"
    FALLBACK_HAPPENED_PREFIX = "fallback-happened-prefix"

    ALLOW_DRAW = "allow-draw"
    ALLOW_ANALYZE = "allow-analyze"
    ALLOW_SUMMARY = "allow-summary"

    ALLOW_MENTION = "allow-mention"
    ALLOW_REPLY = "allow-reply"
    ALLOW_PRIVATE = "allow-private"
    RANDOM_ANSWER_PROBABILITY = "random-answer-probability"
    RANDOM_ANSWER_TO_ADMIN = "random-answer-to-admin"

    ALLOW_USER_SPAM_COMMAND = "allow-user-spam-command"
    SPAM_DELETE_ALL_USER_MESSAGES = "spam-delete-all-user-messages"
    DETECT_SPAM = "detect-spam"
    AUTO_SPAM_MAX_MESSAGES = "auto-spam-max-messages"
    ALLOW_MARK_SPAM_OLD_USERS = "allow-mark-spam-old-users"
    SPAM_BAN_TRESHOLD = "spam-ban-treshold"
    SPAM_WARN_TRESHOLD = "spam-warn-treshold"

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
        return str(self.value)

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
        return self.value.lower().strip() == "true"

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


_chatSettingsInfo: Dict[ChatSettingsKey, ChatSettingsInfoValue] = {
    ChatSettingsKey.CHAT_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Системный промпт для чата",
        "long": 'Влияет на "личность" бота.',
    },
    ChatSettingsKey.BOT_NICKNAMES: {
        "type": ChatSettingsType.STRING,
        "short": "Список никнеймов бота",
        "long": "Бот будет отзываться на эти имена, если оно стоит первым в сообщении пользователя",
    },
    ChatSettingsKey.USE_TOOLS: {
        "type": ChatSettingsType.BOOL,
        "short": "Использовать ли инструменты",
        "long": (
            "Можно ли использовать боту различные инструменты?\n"
            "В данный момент доступны: \n"
            "1. Получение содержимого веб-страницы\n"
            "2. Генерация изображений\n"
            "3. Запоминение информации о пользователе"
        ),
    },
    ChatSettingsKey.SAVE_IMAGES: {
        "type": ChatSettingsType.BOOL,
        "short": "Сохранять изображения (Unimplemented)",
        "long": "Не реализовано в данный момент",
    },
    ChatSettingsKey.PARSE_IMAGES: {
        "type": ChatSettingsType.BOOL,
        "short": "Обрабатывать изображения",
        "long": "Должен ли бот анализировать изображения используя LLM для дальнейшего использования в разговоре",
    },
    ChatSettingsKey.ALLOW_DRAW: {
        "type": ChatSettingsType.BOOL,
        "short": "Разрешить рисовать (`/draw`)",
        "long": "Разрешить команду `/draw` для генерации изображений",
    },
    ChatSettingsKey.ALLOW_ANALYZE: {
        "type": ChatSettingsType.BOOL,
        "short": "Разрешить анализировать (`/analyze`)",
        "long": "Разрешить команду `/analyze` для анализа изображений указанным запросом",
    },
    ChatSettingsKey.ALLOW_SUMMARY: {
        "type": ChatSettingsType.BOOL,
        "short": "Разрешить сводку (`/summary`)",
        "long": "Разрешить команду `/summary`/`/topic_summary` для суммаризации сообщений за сегодня",
    },
    ChatSettingsKey.ALLOW_MENTION: {
        "type": ChatSettingsType.BOOL,
        "short": "Реагировать на упоминания",
        "long": "Должен ли бот реагировать на его упоминания в чате",
    },
    ChatSettingsKey.ALLOW_REPLY: {
        "type": ChatSettingsType.BOOL,
        "short": "Реагировать на ответы",
        "long": "Должен ли бот реагировать на ответы на его сообщения",
    },
    ChatSettingsKey.RANDOM_ANSWER_PROBABILITY: {
        "type": ChatSettingsType.FLOAT,
        "short": "Вероятность случайного ответа",
        "long": "(0-1) Вероятность, что бот решит ответить на произвольное сообщение в чате",
    },
    ChatSettingsKey.RANDOM_ANSWER_TO_ADMIN: {
        "type": ChatSettingsType.BOOL,
        "short": "Случайный ответ на сообщений админов",
        "long": "Отвечать ли при этом на сообщения администраторов чата",
    },
    ChatSettingsKey.TOOLS_USED_PREFIX: {
        "type": ChatSettingsType.STRING,
        "short": "Префикс для инструментов",
        "long": "Префикс у сообщения, если были использованы какие-либо инструменты",
    },
    ChatSettingsKey.FALLBACK_HAPPENED_PREFIX: {
        "type": ChatSettingsType.STRING,
        "short": "Префикс для ошибок",
        "long": "Префикс у сообщения если по каким либо причинам была использована запасная модель генерации текста",
    },
    ChatSettingsKey.ALLOW_USER_SPAM_COMMAND: {
        "type": ChatSettingsType.BOOL,
        "short": "Разрешить не админам использовать команду spam",
        "long": (
            "Разрешить не админам использовать команду `/spam` "
            "для удаления всех сообщений пользователя и его блокировки"
        ),
    },
    ChatSettingsKey.DETECT_SPAM: {
        "type": ChatSettingsType.BOOL,
        "short": "Автоматически проверять на спам",
        "long": "Автоматически проверять сообщения новых пользователей на спам",
    },
    ChatSettingsKey.AUTO_SPAM_MAX_MESSAGES: {
        "type": ChatSettingsType.INT,
        "short": "Максимальное количество сообщений для спам-проверки",
        "long": (
            "Пользователи, у которых в чате больше указанного количества "
            "сообщений не будут проверяться на спам (0 - всегда проверять)"
        ),
    },
    ChatSettingsKey.SPAM_DELETE_ALL_USER_MESSAGES: {
        "type": ChatSettingsType.BOOL,
        "short": "Удалять все сообщения пользователя при помечании спаммером",
        "long": (
            "Удалять все сообщения пользователя, когда пользователь признан "
            "спаммером (автоматически или при помощи команды `/spam`)"
        ),
    },
    ChatSettingsKey.ALLOW_MARK_SPAM_OLD_USERS: {
        "type": ChatSettingsType.BOOL,
        "short": "Разрешить помечать старых пользователей спаммером",
        "long": (
            "Разрешить помечать пользователей, (у которых больше устеновленного количества "
            "сообщений в чате), как спаммеров при помощи команды `/spam` \n"
            "(Используется для того, что бы исклюить ошибки и очепятки)"
        ),
    },
    ChatSettingsKey.SPAM_WARN_TRESHOLD: {
        "type": ChatSettingsType.FLOAT,
        "short": "SPAM-Порог для предупреждения пользователя",
        "long": ("Порог для предупреждения пользователя при автоматической проверке на спам" "(0-100)"),
    },
    ChatSettingsKey.SPAM_BAN_TRESHOLD: {
        "type": ChatSettingsType.FLOAT,
        "short": "SPAM-Порог для блокировки пользователя",
        "long": ("Порог для блокировки пользователя при автоматической проверке на спам" "(0-100)"),
    },
}


def getChatSettingsInfo() -> Dict[ChatSettingsKey, ChatSettingsInfoValue]:
    return _chatSettingsInfo.copy()
