"""Tests for lib.db.providers.utils conversion functions."""

import datetime
from collections.abc import Mapping
from typing import cast

import pytest

from internal.models.types import MessageId
from lib.db.providers.utils import convertContainerElementsToSQLite, convertToSQLite


class _PretendStringifiable:
    """Test double whose asStr() deliberately disagrees with __str__.

    Pins the SQLStringifiable Protocol branch: conversion must use asStr(),
    never the generic str() fallback. This test will FAIL against the pre-extraction
    code (MessageId-only branch) because the double falls through to the str()
    else-branch and yields "WRONG-FALLBACK".
    """

    def asStr(self) -> str:
        """Return the canonical SQL string form."""
        return "42"

    def __str__(self) -> str:
        """Return a deliberately wrong fallback representation."""
        return "WRONG-FALLBACK"


async def test_convertToSQLite_prefersAsStrOverStrFallback() -> None:
    """SQLStringifiable objects convert via asStr(), not str().

    Fails against the pre-extraction code (MessageId-only branch): the
    double falls through to the str() else-branch and yields "WRONG-FALLBACK".
    """
    assert convertToSQLite(_PretendStringifiable()) == "42"


async def test_convertToSQLite_messageIdEquivalence() -> None:
    """MessageId still stores asStr() — pins the D3 cut's safety equivalence."""
    assert convertToSQLite(MessageId(42)) == "42"
    assert convertToSQLite(MessageId("max-abc")) == "max-abc"


async def test_convertToSQLite_primitivesPassthrough() -> None:
    """Primitive types pass through unchanged: str, int, float, bytes, bytearray, None."""
    assert convertToSQLite("hello") == "hello"
    assert convertToSQLite(42) == 42
    assert convertToSQLite(3.14) == 3.14
    assert convertToSQLite(b"bytes") == b"bytes"
    assert convertToSQLite(bytearray(b"ba")) == bytearray(b"ba")
    assert convertToSQLite(None) is None


async def test_convertToSQLite_boolToInt() -> None:
    """Booleans convert to int (0 for False, 1 for True)."""
    assert convertToSQLite(True) == 1
    assert convertToSQLite(False) == 0


async def test_convertToSQLite_datetimeToIsoFormat() -> None:
    """datetime.datetime objects convert to ISO format string."""
    dt = datetime.datetime(2023, 8, 23, 12, 34, 56)
    result = convertToSQLite(dt)
    assert result == "2023-08-23T12:34:56"


async def test_convertToSQLite_containersToJson() -> None:
    """Containers (dict, list, tuple, Mapping, Sequence) convert to JSON string."""
    assert convertToSQLite({"key": "value"}) == '{"key":"value"}'
    assert convertToSQLite([1, 2, 3]) == "[1,2,3]"
    assert convertToSQLite((1, 2, 3)) == "[1,2,3]"


async def test_convertToSQLite_unsupportedTypeWithWarning() -> None:
    """Unsupported types fall back to str() with a warning logged."""

    # This should not raise, just log a warning and return str()
    class NotStringifiable:
        def __init__(self) -> None:
            self.value = 999

        def __str__(self) -> str:
            return f"NotStringifiable({self.value})"

    result = convertToSQLite(NotStringifiable())
    assert result == "NotStringifiable(999)"


async def test_convertContainerElementsToSQLite_mapping() -> None:
    """convertContainerElementsToSQLite converts Mapping values recursively."""

    class NestedStringifiable:
        def asStr(self) -> str:
            return "nested-42"

        def __str__(self) -> str:
            return "WRONG-NESTED"

    data = {
        "key1": "value1",
        "key2": NestedStringifiable(),
        "key3": {"nested": "value"},
    }
    result = convertContainerElementsToSQLite(data)
    # Type assertion: result is a Mapping
    assert isinstance(result, dict)
    assert result["key1"] == "value1"
    assert result["key2"] == "nested-42"  # Must use asStr(), not str()
    assert result["key3"] == '{"nested":"value"}'


async def test_convertContainerElementsToSQLite_sequence() -> None:
    """convertContainerElementsToSQLite converts Sequence elements recursively."""

    class ListStringifiable:
        def asStr(self) -> str:
            return "list-42"

        def __str__(self) -> str:
            return "WRONG-LIST"

    data = ["item1", ListStringifiable(), ["nested", "item"]]
    result = convertContainerElementsToSQLite(data)
    # Type assertion: result is a Sequence
    assert isinstance(result, list)
    assert result[0] == "item1"
    assert result[1] == "list-42"  # Must use asStr(), not str()
    assert result[2] == '["nested","item"]'


async def test_convertContainerElementsToSQLite_noneReturnsEmptyList() -> None:
    """convertContainerElementsToSQLite returns empty list for None input."""
    result = convertContainerElementsToSQLite(None)
    assert result == []


async def test_convertContainerElementsToSQLite_unsupportedTypeRaises() -> None:
    """convertContainerElementsToSQLite raises TypeError for unsupported types."""
    # Cast to satisfy pyright: the type signature only accepts Mapping | Sequence | None,
    # but we're testing the runtime type check that catches invalid values.
    invalidInput = cast("Mapping", 123)
    with pytest.raises(TypeError, match="Unsupported type.*for SQL converting"):
        convertContainerElementsToSQLite(invalidInput)  # int is not Mapping or Sequence
