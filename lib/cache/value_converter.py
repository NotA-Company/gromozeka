"""
TODO
"""

import json

import lib.utils as utils

from .types import V, ValueConverter


class StringValueConverter(ValueConverter[str]):
    """
    TODO
    """

    def encode(self, obj: str) -> str:
        """
        TODO
        """
        if not isinstance(obj, str):
            raise TypeError(f"StringValueConverter expects string input, got {type(obj).__name__}, dood!")

        return obj

    def decode(self, value: str) -> str:
        """
        TODO
        """
        return value


class JsonValueConverter(ValueConverter[V]):
    """
    TODO
    """

    __slots__ = ("sort_keys", "hash")

    def __init__(self):
        """
        TODO
        """

    def encode(self, obj: V) -> str:
        return utils.jsonDumps(obj, sort_keys=False)

    def decode(self, value: str) -> V:
        return json.loads(value)
