import telegram

import lib.max_bot.models as maxModels
from lib import utils


class CallbackButton:
    """TODO"""

    __slots__ = ("text", "payload")

    def __init__(self, text: str, payload: utils.PayloadDict):
        self.text: str = text
        """Button text"""
        self.payload: utils.PayloadDict = payload
        """Button payload"""

    def toTelegram(self) -> telegram.InlineKeyboardButton:
        return telegram.InlineKeyboardButton(text=self.text, callback_data=utils.packDict(self.payload))

    def toMax(self) -> maxModels.CallbackButton:
        return maxModels.CallbackButton(text=self.text, payload=utils.packDict(self.payload))
