"""Common type definitions used across the bot application."""

from typing import Union

MessageIdType = Union[int, str]
"""
Type of MessageID
(Currently int for Telegram and str for Max)
"""
