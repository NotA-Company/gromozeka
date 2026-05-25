"""
Utilities module for Gromozeka bot.

This module provides common utility functions used throughout the Gromozeka bot.
Includes time utilities, JSON handling, dictionary packing/unpacking, environment
variable loading, TTL-enabled dictionary, and other helper functions.

Example:
    >>> from lib.utils import getAgeInSecs, parseDelay, jsonDumps, TTLDict
    >>> from datetime import datetime, timezone
    >>> dt = datetime(2025, 1, 1, tzinfo=timezone.utc)
    >>> age = getAgeInSecs(dt)
    >>> delay = parseDelay("1d2h30m")
    >>> json = jsonDumps({"key": "value"}, indent=2)
    >>> d = TTLDict[str, int]()
    >>> d.setDefaultTTL(60)
    >>> d["key"] = 42
"""

from .ttl_dict import TTLDict
from .utils import (
    PayloadDict,
    checkIfProperCommandName,
    dumpTelegramMessage,
    extractInt,
    getAgeInSecs,
    jsonDumps,
    load_dotenv,
    now,
    packDict,
    parseDelay,
    slottedObjectToDict,
    unpackDict,
)

__all__ = [
    # utils
    "PayloadDict",
    "checkIfProperCommandName",
    "dumpTelegramMessage",
    "extractInt",
    "getAgeInSecs",
    "jsonDumps",
    "load_dotenv",
    "now",
    "packDict",
    "parseDelay",
    "slottedObjectToDict",
    "unpackDict",
    # ttl_dict
    "TTLDict",
]
