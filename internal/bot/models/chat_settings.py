"""Telegram bot chat settings models and enums.

This module defines the data structures used for managing chat settings in the Gromozeka bot,
including chat tiers, settings pages, settings keys, and settings values.
"""

import logging
from enum import IntEnum, StrEnum, auto
from typing import Any, Dict, List, Optional, Self, TypedDict

from lib.ai.abstract import AbstractModel
from lib.ai.manager import LLMManager

logger = logging.getLogger(__name__)


class ChatTier(StrEnum):
    """Chat tier levels for determining user access and capabilities.

    Defines different access levels for users and chats, from banned to bot owners.
    Each tier has different permissions and capabilities within the bot system.
    """

    BANNED = "banned"
    """Tier for banned users with no access."""
    FREE = "free"
    """Tier for free chats with basic access."""
    FREE_PERSONAL = "free-personal"
    """Tier for free private chats, allows a bit more capabilities."""
    PAID = "paid"
    """Paid chats of users with premium access."""
    FRIEND = "friend"
    """Friends with maximum abilities."""
    BOT_OWNER = "bot-owner"
    """Bot owners - can do anything."""

    def emoji(self) -> str:
        """Return emoji associated with given tier.

        Returns:
            str: Emoji representing the tier.
        """
        # ⭐️🌟😎🤩💰🚫⛔️✅🆓
        match self:
            case ChatTier.BANNED:
                return "⛔️"
            case ChatTier.FREE:
                return "🆓"
            case ChatTier.FREE_PERSONAL:
                return "✅"
            case ChatTier.PAID:
                return "⭐️"
            case ChatTier.FRIEND:
                return "🌟"
            case ChatTier.BOT_OWNER:
                return "😎"
            case _:
                return "🚫"

    def getId(self) -> int:
        """Return unique numeric ID for the tier.

        WARNING: Do not store this ID anywhere, it can be changed on app reload.

        Returns:
            int: Unique numeric ID for the tier (1-based index).
        """
        # Use element index
        return list(self.__class__).index(self) + 1

    @classmethod
    def fromId(cls, value: int) -> Self:
        """Get ChatTier value by its numeric ID.

        Args:
            value: Numeric ID of the tier (1-based index).

        Returns:
            ChatTier: The tier corresponding to the numeric ID.

        Raises:
            ValueError: If no tier exists with the given numeric value.
        """
        try:
            return list(cls)[value - 1]
        except IndexError:
            raise ValueError(f"No {cls.__name__} with numeric value {value}")

    def isBetterOrEqualThan(self, other: Self) -> bool:
        """Check if this tier is better or equal than another tier.

        Args:
            other: Another ChatTier to compare against.

        Returns:
            bool: True if this tier's ID is greater than or equal to the other's.
        """
        return self.getId() >= other.getId()

    @classmethod
    def best(cls, *args: Self) -> Self:
        """Return the element with the highest ID from the provided arguments.

        Args:
            *args: One or more ChatTier instances to compare.

        Returns:
            ChatTier: The tier with the highest ID.

        Raises:
            ValueError: If no arguments are provided.
        """
        if not args:
            raise ValueError("At least one argument is required")

        return max(args, key=lambda x: x.getId())

    @classmethod
    def fromStr(cls, v: str) -> Optional[Self]:
        """Return chat tier from string.

        Args:
            v: String representation of the tier.

        Returns:
            Optional[ChatTier]: The corresponding ChatTier, or None if invalid string.
        """
        try:
            return cls(v)
        except ValueError:
            return None


class ChatSettingsPage(IntEnum):
    """Pages where chat settings are organized in the UI.

    Defines different pages/categories for organizing chat settings in the bot interface.
    Each page has a minimum tier requirement for access.
    """

    STANDART = auto()
    """Standard settings page for basic chat configuration."""
    EXTENDED = auto()
    """Extended settings page for advanced chat configuration."""
    SPAM = auto()
    """Spam detection and management settings page."""
    LLM_BASE = auto()
    """Base LLM configuration settings page."""
    LLM_PAID = auto()
    """Premium LLM configuration settings page."""
    PAID = auto()
    """Paid features and premium settings page."""
    FRIEND = auto()
    """Friend-only settings page for enhanced features."""
    BOT_OWNER = auto()
    """Bot owner-only settings page for administrative features."""
    BOT_OWNER_SYSTEM = auto()
    """System settings page for bot owner only - do not modify unless necessary."""

    def getName(self) -> str:
        """Get the display name of the settings page.

        Returns:
            str: Human-readable name of the page in Russian.
        """
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
                return "Премиум настройки LLM ⭐️"
            case ChatSettingsPage.PAID:
                return "Премиум настройки ⭐️"
            case ChatSettingsPage.FRIEND:
                return "Настройки для самых важных 🌟"
            case ChatSettingsPage.BOT_OWNER:
                return "Только для владельцев 😎"
            case ChatSettingsPage.BOT_OWNER_SYSTEM:
                return "Системные настройки (не трогать) 😎"
            case _:
                return f"{self.name}"

    def minTier(self) -> ChatTier:
        """Get the minimum tier required to access this settings page.

        Returns:
            ChatTier: The minimum tier required to view/modify settings on this page.

        Raises:
            NotImplementedError: If the page has no minimum tier configured.
        """
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
        """Return next page in enum order.

        Returns:
            Optional[ChatSettingsPage]: Next ChatSettingsPage if it exists,
                None if current page is the last one.
        """
        allPages = list(self.__class__)
        currentIndex = allPages.index(self)
        nextIndex = currentIndex + 1

        if nextIndex < len(allPages):
            return allPages[nextIndex]
        return None


class ChatSettingsType(StrEnum):
    """Data types for chat settings values.

    Defines the valid data types that chat settings can have.
    """

    STRING = "string"
    """Plain text string value type."""
    INT = "int"
    """Integer number value type."""
    FLOAT = "float"
    """Floating point number value type."""
    BOOL = "bool"
    """Boolean value type (true/false)."""
    MODEL = "model"
    """LLM model name, can be chosen from list of choosable models."""
    IMAGE_MODEL = "image-model"
    """Image-generation model name, can be chosen from list of choosable models."""


class ChatSettingsKey(StrEnum):
    """Keys for all available chat settings.

    Defines all possible settings keys that can be configured for a chat.
    Each key has associated metadata including type, description, and page location.
    """

    UNKNOWN = "unknown"
    """Unknown setting key placeholder."""
    # LLM Models
    CHAT_MODEL = "chat-model"
    """Primary LLM model for chat conversations."""
    FALLBACK_MODEL = "fallback-model"
    """Backup LLM model used when primary model fails."""
    SUMMARY_MODEL = "summary-model"
    """LLM model for summarizing messages."""
    SUMMARY_FALLBACK_MODEL = "summary-fallback-model"
    """Backup LLM model for summarizing when primary fails."""
    IMAGE_PARSING_MODEL = "image-parsing-model"
    """LLM model for analyzing and parsing images."""
    IMAGE_PARSING_FALLBACK_MODEL = "image-parsing-fallback-model"
    """Backup LLM model for image parsing when primary fails."""
    IMAGE_GENERATION_MODEL = "image-generation-model"
    """LLM model for generating images."""
    IMAGE_GENERATION_FALLBACK_MODEL = "image-generation-fallback-model"
    """Backup LLM model for image generation when primary fails."""
    CONDENSING_MODEL = "condensing-model"
    """LLM model for condensing large context."""
    # Prompts for different actions
    SUMMARY_PROMPT = "summary-prompt"
    """System prompt for message summarization."""
    PARSE_IMAGE_PROMPT = "parse-image-prompt"
    """System prompt for image analysis and parsing."""
    CHAT_PROMPT = "chat-prompt"
    """Main system prompt defining bot personality."""
    CHAT_PROMPT_SUFFIX = "chat-prompt-suffix"
    """Additional suffix appended to chat system prompt."""
    CONDENSING_SYSTEM_PROMPT = "condensing-system-prompt"
    """System prompt defining the condensing model's identity and rules."""
    CONDENSING_PROMPT = "condensing-prompt"
    """Per-call trigger prompt for context condensing."""
    DOCUMENT_CONDENSING_PROMPT = "document-condensing-prompt"
    """System prompt for condensing long documents like web pages."""
    # Divination prompts (tarot & runes readings)
    TAROT_SYSTEM_PROMPT = "tarot-system-prompt"
    """System prompt for tarot card readings."""
    RUNES_SYSTEM_PROMPT = "runes-system-prompt"
    """System prompt for rune readings."""
    DIVINATION_USER_PROMPT_TEMPLATE = "divination-user-prompt-template"
    """Template for user-facing divination readings."""
    DIVINATION_IMAGE_PROMPT_TEMPLATE = "divination-image-prompt-template"
    """Template for generating divination illustrations."""
    DIVINATION_REPLY_TEMPLATE = "divination-reply-template"
    """Template for final divination response messages."""
    DIVINATION_DISCOVERY_SYSTEM_PROMPT = "divination-discovery-system-prompt"
    """System instruction for layout discovery LLM calls."""
    DIVINATION_DISCOVERY_INFO_PROMPT = "divination-discovery-info-prompt"
    """Prompt template for LLM to discover layout info with web search."""
    DIVINATION_PARSE_STRUCTURE_SYSTEM_PROMPT = "divination-parse-structure-system-prompt"
    """System prompt for structuring discovered layouts as JSON."""
    DIVINATION_PARSE_STRUCTURE_PROMPT = "divination-parse-structure-prompt"
    """Prompt template for LLM to structure discovered layout as JSON."""
    # System settings
    ADMIN_CAN_CHANGE_SETTINGS = "admin-can-change-settings"
    """Whether chat admins can modify chat settings."""
    BOT_NICKNAMES = "bot-nicknames"
    """List of nicknames the bot responds to."""
    LLM_MESSAGE_FORMAT = "llm-message-format"
    """Message format for LLM (text, json, smart)."""
    USE_TOOLS = "use-tools"
    """Whether bot can use tools (web, images, memory, etc.)."""
    PARSE_ATTACHMENTS = "parse-attachments"
    """Whether bot analyzes attachments (images, stickers)."""
    SAVE_ATTACHMENTS = "save-attachments"
    """Whether bot saves attachments for later use."""
    SAVE_PREFIX = "save-prefix"
    """Prefix for saved attachment files."""
    TOOLS_USED_PREFIX = "tools-used-prefix"
    """Prefix when tools were used in response."""
    FALLBACK_HAPPENED_PREFIX = "fallback-happened-prefix"
    """Prefix when backup model was used."""
    INTERMEDIATE_MESSAGE_PREFIX = "intermediate-message-prefix"
    """Prefix for intermediate messages during processing."""
    # Allowing different commands in chat
    ALLOW_TOOLS_COMMANDS = "allow-tools-commands"
    """Whether tool commands (/draw, /analyze, etc.) are allowed."""
    DELETE_DENIED_COMMANDS = "delete-denied-commands"
    """Whether to delete messages with denied commands."""
    # Allowing different reactions in chat (to mention/reply/random)
    ALLOW_MENTION = "allow-mention"
    """Whether bot responds to being mentioned."""
    ALLOW_REPLY = "allow-reply"
    """Whether bot responds to replies to its messages."""
    RANDOM_ANSWER_PROBABILITY = "random-answer-probability"
    """Probability (0-1) of random responses to messages."""
    RANDOM_ANSWER_TO_ADMIN = "random-answer-to-admin"
    """Whether random responses include admin messages."""
    # Spam-related settings
    ALLOW_USER_SPAM_COMMAND = "allow-user-spam-command"
    """Whether non-admins can use /spam command."""
    SPAM_DELETE_ALL_USER_MESSAGES = "spam-delete-all-user-messages"
    """Whether to delete all user messages when marked as spammer."""
    DETECT_SPAM = "detect-spam"
    """Whether to automatically check messages for spam."""
    AUTO_SPAM_MAX_MESSAGES = "auto-spam-max-messages"
    """Max messages before user is exempt from spam checking (0 = always check)."""
    ALLOW_MARK_SPAM_OLD_USERS = "allow-mark-spam-old-users"
    """Whether to allow marking established users as spam."""
    SPAM_BAN_TRESHOLD = "spam-ban-treshold"
    """Spam confidence threshold (0-100) for banning user."""
    SPAM_WARN_TRESHOLD = "spam-warn-treshold"
    """Spam confidence threshold (0-100) for warning user."""
    # Bayes filter settings
    BAYES_ENABLED = "bayes-enabled"
    """Whether Bayesian spam filter is enabled."""
    BAYES_MIN_CONFIDENCE = "bayes-min-confidence"
    """Minimum confidence (0.0-1.0) for Bayes filter decision."""
    BAYES_AUTO_LEARN = "bayes-auto-learn"
    """Whether Bayes filter auto-learns from marked messages."""
    BAYES_USE_TRIGRAMS = "bayes-use-trigrams"
    """Whether Bayes filter uses trigrams for better accuracy."""
    BAYES_MIN_CONFEDENCE_TO_AUTOLEARN_SPAM = "bayes-min-confedence-to-autolearn-spam"
    """Minimum confidence (0.0-1.0) for auto-learning spam messages."""
    BAYES_MIN_CONFEDENCE_TO_AUTOLEARN_HAM = "bayes-min-confedence-to-autolearn-ham"
    """Minimum confidence (0.0-1.0) for auto-learning non-spam messages."""
    # Reaction settings
    REACTION_AUTHOR_TO_EMOJI_MAP = "reaction-author-to-emoji-map"
    """JSON mapping user IDs/usernames to reaction emojis."""
    # Message management
    DELETE_JOIN_MESSAGES = "delete-join-messages"
    """Whether to delete user join messages."""
    DELETE_LEFT_MESSAGES = "delete-left-messages"
    """Whether to delete user left messages."""
    # Tier-related
    BASE_TIER = "base-tier"
    """Default tier level for the chat."""
    PAID_TIER = "paid-tier"
    """Paid tier level for the chat."""
    PAID_TIER_UNTILL_TS = "paid-tier-untill-ts"
    """Timestamp until paid tier is valid."""
    LLM_RATELIMITER = "llm-ratelimiter"
    """Rate limiter configuration for LLM/tool usage."""
    # System settings. Not to be used/configured
    CACHED_TS = "cached-ts"
    """Timestamp when chat settings were cached, to be used in Cache Service only."""

    def getId(self) -> int:
        """Return unique numeric ID for the settings key.

        WARNING: Do not store this ID anywhere, it can be changed on app reload.

        Returns:
            int: Unique numeric ID for the key (1-based index).
        """
        # Используем hash или порядковый номер
        return list(self.__class__).index(self) + 1

    @classmethod
    def fromId(cls, value: int) -> "ChatSettingsKey":
        """Get ChatSettingsKey value by its numeric ID.

        Args:
            value: Numeric ID of the settings key (1-based index).

        Returns:
            ChatSettingsKey: The key corresponding to the numeric ID.

        Raises:
            ValueError: If no key exists with the given numeric value.
        """
        try:
            return list(cls)[value - 1]
        except IndexError:
            raise ValueError(f"No {cls.__name__} with numeric value {value}")


class ChatSettingsValue:
    """Value wrapper for chat settings.

    Provides type conversion methods for converting string values to different types.
    Tracks which user last updated the setting.

    Attributes:
        value: The string value stored for this setting.
        updatedBy: User ID who last updated this setting, or 0 if unknown.
    """

    __slots__ = ("value", "updatedBy")

    def __init__(self, value: Any, updatedBy: Optional[int] = None) -> None:
        """Initialize a chat settings value.

        Args:
            value: The value to store (will be converted to string).
            updatedBy: User ID who last updated this setting, defaults to 0 if None.
        """
        self.value = str(value).strip()
        self.updatedBy = updatedBy if updatedBy is not None else 0

    def __repr__(self) -> str:
        """Return string representation of the settings value.

        Returns:
            str: String representation showing value and updater.
        """
        return f"{type(self).__name__}(value='{self.value}', updatedBy={self.updatedBy})"

    def __str__(self) -> str:
        """Return string representation of the value.

        Returns:
            str: The string value.
        """
        return self.toStr()

    def toStr(self) -> str:
        """Convert value to string.

        Returns:
            str: The string value.
        """
        return str(self.value)

    def toInt(self) -> int:
        """Convert value to integer.

        Returns:
            int: The integer value, or 0 if conversion fails.
        """
        try:
            return int(self.value)
        except ValueError:
            logger.error(f"Failed to convert {self.value} to int")
            return 0

    def toFloat(self) -> float:
        """Convert value to float.

        Returns:
            float: The float value, or 0.0 if conversion fails.
        """
        try:
            return float(self.value)
        except ValueError:
            logger.error(f"Failed to convert {self.value} to float")
            return 0.0

    def toBool(self) -> bool:
        """Convert value to boolean.

        Returns:
            bool: True if value is "true" or "1" (case-insensitive), False otherwise.
        """
        return self.value.lower().strip() in ("true", "1")

    def toList(self, separator: str = ",", dropEmpty: bool = True) -> List[str]:
        """Convert value to list of strings.

        Args:
            separator: String to split the value on. Defaults to ",".
            dropEmpty: Whether to remove empty strings from the result. Defaults to True.

        Returns:
            List[str]: List of string values.
        """
        return [x.strip() for x in self.value.split(separator) if x.strip() or not dropEmpty]

    def toModel(self, modelManager: LLMManager) -> AbstractModel:
        """Convert value to an LLM model instance.

        Args:
            modelManager: The LLM manager to retrieve the model from.

        Returns:
            AbstractModel: The model instance.

        Raises:
            ValueError: If the model is not found in the manager.
        """
        ret = modelManager.getModel(self.value)
        if ret is None:
            logger.error(f"Model {self.value} not found")
            raise ValueError(f"Model {self.value} not found")
        return ret


class ChatSettingsInfoValue(TypedDict):
    """Metadata dictionary for a chat setting.

    Contains type information and descriptions for a single chat setting key.

    Attributes:
        type: The data type of the setting (string, int, float, bool, model, etc.).
        short: Short human-readable description of the setting.
        long: Detailed human-readable description of the setting.
        page: The UI page where this setting can be configured.
    """

    type: ChatSettingsType
    short: str
    long: str
    page: ChatSettingsPage


type ChatSettingsDict = Dict[ChatSettingsKey, ChatSettingsValue]

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
    ChatSettingsKey.CONDENSING_SYSTEM_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Системный промпт для сжатия контекста",
        "long": "Системный промпт, задающий роль и правила модели при сжатии контекста. "
        "Заменяет персональный промпт чата на время компактинга.",
        "page": ChatSettingsPage.LLM_BASE,
    },
    ChatSettingsKey.CONDENSING_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Промпт для сжатия контекста",
        "long": "Промпт, используемый для сжатия контекста.",
        "page": ChatSettingsPage.LLM_BASE,
    },
    ChatSettingsKey.DOCUMENT_CONDENSING_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Промпт для сжатия документов (например веб-страниц)",
        "long": "Промпт, используемый для сжатия различных слишком больших документов (например, веб-страниц).",
        "page": ChatSettingsPage.LLM_BASE,
    },
    # # Divination prompts (tarot & runes readings)
    ChatSettingsKey.TAROT_SYSTEM_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Системный промпт для расклада Таро",
        "long": "Промпт, инструктирующий LLM, как интерпретировать расклад Таро.",
        "page": ChatSettingsPage.LLM_BASE,
    },
    ChatSettingsKey.RUNES_SYSTEM_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Системный промпт для рунического расклада",
        "long": "Промпт, инструктирующий LLM, как интерпретировать рунический расклад.",
        "page": ChatSettingsPage.LLM_BASE,
    },
    ChatSettingsKey.DIVINATION_USER_PROMPT_TEMPLATE: {
        "type": ChatSettingsType.STRING,
        "short": "Шаблон пользовательского сообщения для гадания",
        "long": (
            "Шаблон, в который подставляются {userName}, {question}, {layoutName}, " "{positionsBlock}, {cardsBlock}."
        ),
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
    },
    ChatSettingsKey.DIVINATION_IMAGE_PROMPT_TEMPLATE: {
        "type": ChatSettingsType.STRING,
        "short": "Шаблон промпта для иллюстрации расклада",
        "long": "Шаблон с {layoutName}, {spreadDescription}, {styleHint}.",
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
    },
    ChatSettingsKey.DIVINATION_REPLY_TEMPLATE: {
        "type": ChatSettingsType.STRING,
        "short": "Шаблон ответа пользователю для гадания",
        "long": (
            "Шаблон сообщения, отправляемого пользователю при /taro и /runes. "
            "Плейсхолдеры: {layoutName}, {drawnSymbolsBlock}, {interpretation}."
        ),
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
    },
    ChatSettingsKey.DIVINATION_DISCOVERY_SYSTEM_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Системный промпт для открытия раскладов",
        "long": (
            "Системные инструкции для LLM при открытии новых раскладов. "
            "В этом промпте описывается, как использовать веб-поиск для поиска информации о раскладах."
        ),
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
    },
    ChatSettingsKey.DIVINATION_DISCOVERY_INFO_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Шаблон промпта для поиска информации о раскладе",
        "long": (
            "Промпт для LLM, чтобы найти информацию о раскладе с помощью веб-поиска. "
            "Используется вместе с divination-parse-structure-prompt для автоматического поиска новых раскладов."
        ),
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
    },
    ChatSettingsKey.DIVINATION_PARSE_STRUCTURE_SYSTEM_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Системный для структурирования расклада",
        "long": (
            "Системный промпт для LLM, который превращает описание расклада в структурированный JSON формат. "
            "Используется после получения информации через divination-discovery-info-prompt."
        ),
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
    },
    ChatSettingsKey.DIVINATION_PARSE_STRUCTURE_PROMPT: {
        "type": ChatSettingsType.STRING,
        "short": "Шаблон промпта для структурирования расклада",
        "long": (
            "Промпт для LLM, который превращает описание расклада в структурированный JSON формат. "
            "Используется после получения информации через divination-discovery-info-prompt."
        ),
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
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
    ChatSettingsKey.INTERMEDIATE_MESSAGE_PREFIX: {
        "type": ChatSettingsType.STRING,
        "short": "Префикс для промежуточных сообщений",
        "long": "Префикс у сообщения, которое бот отвечает в процессе ответа на сообщение",
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
    ChatSettingsKey.BAYES_MIN_CONFEDENCE_TO_AUTOLEARN_SPAM: {
        "type": ChatSettingsType.FLOAT,
        "short": "Минимальная уверенность для автоматического обучения на спам",
        "long": (
            "Минимальная уверенность для автоматического обучения Bayes фильтра на спам.\n"
            "Если уверенность выше, сообщение, помеченное как спам добавляется в обучающую выборку.\n"
            "Диапазон значения: 0.0-1.0."
        ),
        "page": ChatSettingsPage.SPAM,
    },
    ChatSettingsKey.BAYES_MIN_CONFEDENCE_TO_AUTOLEARN_HAM: {
        "type": ChatSettingsType.FLOAT,
        "short": "Минимальная уверенность для автоматического обучения на НЕ спам",
        "long": (
            "Минимальная уверенность для автоматического обучения Bayes фильтра на НЕ спам.\n"
            "Если уверенность выше, сообщение, помеченное как НЕ спам добавляется в обучающую выборку.\n"
            "Диапазон значения: 0.0-1.0."
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
    ChatSettingsKey.LLM_RATELIMITER: {
        "type": ChatSettingsType.STRING,
        "short": "Рэйтлимитер использования LLM и Инструментов",
        "long": "Ограничивает частоту запросов к LLM и Инструментам (как то погода, поиск, пр...). "
        "Возможные значения смотри в конфиге.",
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,
    },
}


def getChatSettingsInfo() -> Dict[ChatSettingsKey, ChatSettingsInfoValue]:
    """Get information about all available chat settings.

    Returns a copy of the settings info dictionary containing metadata for all
    chat settings keys, including their types, descriptions, and page locations.

    Returns:
        Dict[ChatSettingsKey, ChatSettingsInfoValue]: Dictionary mapping settings keys
            to their metadata (type, short description, long description, page).
    """
    # TODO: Add ability to return different settings for different chats in future
    return _chatSettingsInfo.copy()
