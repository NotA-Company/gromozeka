"""TODO"""

from typing import Union

import telegram

import lib.max_bot.models as maxModels

UpdateObjectType = Union[telegram.Update | maxModels.Update]
