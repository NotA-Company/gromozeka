"""
Telegram bot chat settings.
"""

from enum import StrEnum
import logging
from typing import Any, List

from lib.ai.abstract import AbstractModel
from lib.ai.manager import LLMManager

logger = logging.getLogger(__name__)


class ChatSettingsKey(StrEnum):
    """Enum for chat settings."""

    CHAT_MODEL = "chat-model"
    FALLBACK_MODEL = "fallback-model"
    SUMMARY_MODEL = "summary-model"
    SUMMARY_FALLBACK_MODEL = "summary-fallback-model"
    IMAGE_PARSING_MODEL = "image-parsing-model"
    IMAGE_GENERATION_MODEL = "image-generation-model"

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

    ALLOW_DRAW = "allow-draw"
    ALLOW_ANALYZE = "allow-analyze"
    ALLOW_SUMMARY = "allow-summary"

    ALLOW_MENTION = "allow-mention"
    ALLOW_REPLY = "allow-reply"
    ALLOW_PRIVATE = "allow-private"
    RANDOM_ANSWER_PROBABILITY = "random-answer-probability"
    RANDOM_ANSWER_TO_ADMIN = "random-answer-to-admin"

    TOOLS_USED_PREFIX = "tools-used-prefix"
    FALLBACK_HAPPENED_PREFIX = "fallback-happened-prefix"


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
        return self.value.lower() == "true"

    def toList(self, separator: str = ",", dropEmpty: bool = True) -> List[str]:
        return [x.strip() for x in self.value.split(separator) if x.strip() or not dropEmpty]

    def toModel(self, modelManager: LLMManager) -> AbstractModel:
        ret = modelManager.getModel(self.value)
        if ret is None:
            logger.error(f"Model {self.value} not found")
            raise ValueError(f"Model {self.value} not found")
        return ret
