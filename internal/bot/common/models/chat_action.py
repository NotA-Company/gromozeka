import logging
from enum import StrEnum

import telegram

import lib.max_bot.models as maxModels

logger = logging.getLogger(__name__)


class TypingAction(StrEnum):
    """TODO"""

    TYPING = "typing"
    UPLOAD_PHOTO = "upload_photo"
    UPLOAD_VIDEO = "upload_video"
    UPLOAD_AUDIO = "upload_audio"
    UPLOAD_FILE = "upload_file"

    def toTelegram(self) -> telegram.constants.ChatAction:
        match self:
            case TypingAction.TYPING:
                return telegram.constants.ChatAction.TYPING
            case TypingAction.UPLOAD_PHOTO:
                return telegram.constants.ChatAction.UPLOAD_PHOTO
            case TypingAction.UPLOAD_VIDEO:
                return telegram.constants.ChatAction.UPLOAD_VIDEO
            case TypingAction.UPLOAD_AUDIO:
                return telegram.constants.ChatAction.UPLOAD_VOICE
            case TypingAction.UPLOAD_FILE:
                return telegram.constants.ChatAction.UPLOAD_DOCUMENT

        logger.error(f"Unexpected TypingAction: {self}")
        return telegram.constants.ChatAction.TYPING

    def toMax(self) -> maxModels.SenderAction:
        match self:
            case TypingAction.TYPING:
                return maxModels.SenderAction.TYPING
            case TypingAction.UPLOAD_PHOTO:
                return maxModels.SenderAction.UPLOAD_PHOTO
            case TypingAction.UPLOAD_VIDEO:
                return maxModels.SenderAction.UPLOAD_VIDEO
            case TypingAction.UPLOAD_AUDIO:
                return maxModels.SenderAction.UPLOAD_AUDIO
            case TypingAction.UPLOAD_FILE:
                return maxModels.SenderAction.UPLOAD_FILE

        logger.error(f"Unexpected TypingAction: {self}")
        return maxModels.SenderAction.TYPING
