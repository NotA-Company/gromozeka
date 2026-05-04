"""Value converter implementations for cache storage.

This module provides concrete implementations of the ValueConverter interface
for different data types that need to be stored in cache systems. It includes
converters for string values and JSON-serializable objects.

Classes:
    StringValueConverter: Pass-through converter for string values.
    JsonValueConverter: JSON converter for serializable objects.
"""

import json

import lib.utils as utils

from .types import V, ValueConverter


class StringValueConverter(ValueConverter[str]):
    """Pass-through converter for string values.

    This converter handles string values without any transformation,
    making it ideal for cache keys or values that are already strings.
    """

    def encode(self, obj: str) -> str:
        """Encode a string object for cache storage.

        Args:
            obj: The string object to encode.

        Returns:
            The same string object (pass-through conversion).

        Raises:
            TypeError: If obj is not a string.
        """
        if not isinstance(obj, str):
            raise TypeError(f"StringValueConverter expects string input, got {type(obj).__name__}")

        return obj

    def decode(self, value: str) -> str:
        """Decode a string value from cache storage.

        Args:
            value: The string value from cache.

        Returns:
            The same string value (pass-through conversion).
        """
        return value


class JsonValueConverter(ValueConverter[V]):
    """JSON converter for serializable objects.

    This converter handles JSON serialization and deserialization for
    any JSON-serializable objects, allowing complex data structures to be
    stored in cache systems that only accept string values.
    """

    def __init__(self) -> None:
        """Initialize the JSON value converter.

        Creates a new JsonValueConverter instance with default settings
        for JSON serialization and deserialization.
        """

    def encode(self, obj: V) -> str:
        """Encode an object to JSON string for cache storage.

        Args:
            obj: The JSON-serializable object to encode.

        Returns:
            JSON string representation of the object.

        Raises:
            TypeError: If the object is not JSON-serializable.
        """
        return utils.jsonDumps(obj, sort_keys=False)

    def decode(self, value: str) -> V:
        """Decode a JSON string from cache storage.

        Args:
            value: The JSON string from cache.

        Returns:
            The deserialized object.

        Raises:
            json.JSONDecodeError: If the value is not valid JSON.
        """
        return json.loads(value)
