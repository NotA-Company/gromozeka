"""Type wrappers for multi-platform bot update objects.

Provides unified type definitions for handling update objects from different
bot platforms (Telegram and Max Messenger) in the common bot architecture.
"""

from typing import Union

import telegram

import lib.max_bot.models as maxModels

UpdateObjectType = Union[telegram.Update | maxModels.Update]
