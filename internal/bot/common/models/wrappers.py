"""Type wrappers for multi-platform bot update objects.

Provides unified type definitions for handling update objects from different
bot platforms (Telegram and Max Messenger) in the common bot architecture.
"""

from typing import Union

import telegram

import lib.max_bot.models as maxModels

UpdateObjectType = Union[telegram.Update | maxModels.Update]
"""Union type for update objects from supported bot platforms.

This type alias represents the union of update objects from Telegram and Max
Messenger platforms, allowing for unified handling of updates across different
messaging platforms in the common bot architecture.

Examples:
    >>> def handle_update(update: UpdateObjectType) -> None:
    ...     if isinstance(update, telegram.Update):
    ...         # Handle Telegram update
    ...     elif isinstance(update, maxModels.Update):
    ...         # Handle Max Messenger update
"""
