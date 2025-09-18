"""
Telegram bot chat settings.
"""

from enum import StrEnum
import logging
from typing import Any, List

logger = logging.getLogger(__name__)

class ChatSettingsEnum(StrEnum):
    """Enum for chat settings."""
    CHAT_MODEL = "chat-model"
    FALLBACK_MODEL = "fallback-model"
    SUMMARY_MODEL = "summary-model"
    SUMMARY_FALLBACK_MODEL = "summary-fallback-model"
    IMAGE_MODEL = "image-model"

    SUMMARY_PROMPT = "summary-prompt"
    CHAT_PROMPT = "chat-prompt"
    PARSE_IMAGE_PROMPT = "parse-image-prompt"

    ADMIN_CAN_CHANGE_SETTINGS = "admin-can-change-settings"
    BOT_NICKNAMES = "bot-nicknames"
    LLM_MESSAGE_FORMAT = "llm-message-format"
    USE_TOOLS = "use-tools"
    SAVE_IMAGES = "save-images"
    PARSE_IMAGES = "parse-images"

class ChatSettingsValue:
    """Value of chat settings."""
    def __init__(self, value: Any):
        self.value = str(value)

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
