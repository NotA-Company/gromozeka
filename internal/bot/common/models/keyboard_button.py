import telegram

import lib.max_bot.models as maxModels
from lib import utils


class CallbackButton:
    """Represents a callback button for keyboard interactions.

    This class provides a unified interface for creating callback buttons that can be
    converted to both Telegram and Max Messenger formats.
    """

    __slots__ = ("text", "payload")

    def __init__(self, text: str, payload: utils.PayloadDict) -> None:
        """Initialize a callback button.

        Args:
            text: The display text for the button.
            payload: A dictionary containing the callback payload data.
        """
        self.text: str = text
        """Button text"""
        self.payload: utils.PayloadDict = payload
        """Button payload"""

    def toTelegram(self) -> telegram.InlineKeyboardButton:
        """Convert the button to Telegram InlineKeyboardButton format.

        Returns:
            A Telegram InlineKeyboardButton instance with the button text and packed callback data.
        """
        return telegram.InlineKeyboardButton(text=self.text, callback_data=utils.packDict(self.payload))

    def toMax(self) -> maxModels.CallbackButton:
        """Convert the button to Max Messenger CallbackButton format.

        Returns:
            A Max Messenger CallbackButton instance with the button text and packed payload.
        """
        return maxModels.CallbackButton(text=self.text, payload=utils.packDict(self.payload))
