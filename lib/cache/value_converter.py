"""
Value converter implementations for cache storage, dood!

This module provides concrete implementations of the ValueConverter interface
for different data types that need to be stored in cache systems. It includes
converters for string values and JSON-serializable objects.
"""

import json

import lib.utils as utils

from .types import V, ValueConverter


class StringValueConverter(ValueConverter[str]):
    """
    Pass-through converter for string values, dood!

    This converter handles string values without any transformation,
    making it ideal for cache keys or values that are already strings.
    """

    def encode(self, obj: str) -> str:
        """
        Encode a string object for cache storage, dood!

        Args:
            obj: The string object to encode

        Returns:
            str: The same string object (pass-through conversion)

        Raises:
            TypeError: If obj is not a string
        """
        if not isinstance(obj, str):
            raise TypeError(f"StringValueConverter expects string input, got {type(obj).__name__}, dood!")

        return obj

    def decode(self, value: str) -> str:
        """
        Decode a string value from cache storage, dood!

        Args:
            value: The string value from cache

        Returns:
            str: The same string value (pass-through conversion)
        """
        return value


class JsonValueConverter(ValueConverter[V]):
    """
    JSON converter for serializable objects, dood!

    This converter handles JSON serialization and deserialization for
    any JSON-serializable objects, allowing complex data structures to be
    stored in cache systems that only accept string values.
    """

    def __init__(self):
        """
        Initialize the JSON value converter, dood!

        Creates a new JsonValueConverter instance with default settings
        for JSON serialization and deserialization.
        """

    def encode(self, obj: V) -> str:
        return utils.jsonDumps(obj, sort_keys=False)

    def decode(self, value: str) -> V:
        return json.loads(value)
