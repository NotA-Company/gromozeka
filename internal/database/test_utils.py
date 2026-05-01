"""
Test suite for internal/database/utils.py.

Tests the utility functions for type conversion and SQL response handling:
- _checkType: Type checking with support for Optional, Union, and generic types
- sqlToCustomType: Converts SQL responses to specified Python types
- sqlToDatetime: Converts SQL datetime strings to datetime objects
- sqlToBoolean: Converts SQL boolean bytes to Python bool
- datetimeToSql: Converts datetime objects to SQL-compatible strings
"""

import datetime
from typing import Optional, Union

import pytest

from internal.database.utils import (
    _checkType,
    sqlToCustomType,
)


class TestCheckType:
    """Test suite for _checkType helper function.

    Tests type checking functionality including plain types, None handling,
    Optional/Union types, and generic container types.
    """

    def testPlainTypeMatch(self) -> None:
        """Test that _checkType returns True when value matches plain type."""
        assert _checkType(42, int) is True
        assert _checkType("hello", str) is True
        assert _checkType(3.14, float) is True
        assert _checkType(True, bool) is True
        assert _checkType([], list) is True
        assert _checkType({}, dict) is True

    def testPlainTypeMismatch(self) -> None:
        """Test that _checkType returns False when value does not match plain type."""
        assert _checkType("hello", int) is False
        assert _checkType(42, str) is False
        assert _checkType(3.14, int) is False

    def testNoneTypeMatch(self) -> None:
        """Test that _checkType returns True only for None against NoneType."""
        assert _checkType(None, type(None)) is True

    def testNoneTypeMismatch(self) -> None:
        """Test that _checkType returns False for non-None value against NoneType."""
        assert _checkType(0, type(None)) is False
        assert _checkType("", type(None)) is False

    def testBoolIsNotInt(self) -> None:
        """Test that bool values do not pass int type check (distinct types)."""
        assert _checkType(True, int) is False
        assert _checkType(False, int) is False

    def testIntIsNotBool(self) -> None:
        """Test that int values do not pass bool type check (distinct types)."""
        assert _checkType(0, bool) is False
        assert _checkType(1, bool) is False

    def testOptionalMatch(self) -> None:
        """Test that _checkType returns True for None or T in Optional[T]."""

        assert _checkType(None, Optional[int]) is True  # pyright: ignore[reportArgumentType]
        assert _checkType(42, Optional[int]) is True  # pyright: ignore[reportArgumentType]
        assert _checkType("str", Optional[int]) is False  # pyright: ignore[reportArgumentType]

    def testUnionMatch(self) -> None:
        """Test that _checkType returns True when value matches any Union branch."""

        assert _checkType(42, Union[int, str]) is True  # pyright: ignore[reportArgumentType]
        assert _checkType("hello", Union[int, str]) is True  # pyright: ignore[reportArgumentType]
        assert _checkType(3.14, Union[int, str]) is False  # pyright: ignore[reportArgumentType]

    def testGenericListMatch(self) -> None:
        """Test that _checkType matches on origin container type for generics."""
        assert _checkType([1, 2, 3], list[int]) is True
        assert _checkType({"a": 1}, dict[str, int]) is True

    def testGenericListMismatch(self) -> None:
        """Test that _checkType returns False when container origin does not match."""
        assert _checkType([1, 2], dict[str, int]) is False
        assert _checkType({"a": 1}, list[str]) is False


class TestConvertSqlResponseToTypeAlreadyCorrectType:
    """Test suite for sqlToCustomType when data is already the correct type.

    Tests passthrough behavior for correctly typed values.
    """

    def testIntPassthrough(self) -> None:
        """Test that sqlToCustomType returns int as-is when already int and not bool."""
        success, value = sqlToCustomType(42, int)
        assert success is True
        assert value == 42

    def testStrPassthrough(self) -> None:
        """Test that sqlToCustomType returns str as-is when already str."""
        success, value = sqlToCustomType("hello", str)
        assert success is True
        assert value == "hello"

    def testBoolPassthrough(self) -> None:
        """Test that sqlToCustomType returns bool as-is when already bool."""
        success, value = sqlToCustomType(True, bool)
        assert success is True
        assert value is True

    def testNonePassthrough(self) -> None:
        """Test that sqlToCustomType returns None for Optional[int] when data is None."""

        success, value = sqlToCustomType(None, Optional[int])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is None

    def testFloatPassthrough(self) -> None:
        """Test that sqlToCustomType returns float as-is when already float."""
        success, value = sqlToCustomType(3.14, float)
        assert success is True
        assert value == pytest.approx(3.14)


class TestConvertSqlResponseToTypeBytesInput:
    """Test suite for sqlToCustomType with bytes input.

    Tests conversion of bytes to various target types.
    """

    def testBytesIntToInt(self) -> None:
        """Test that sqlToCustomType decodes bytes and converts to int."""
        success, value = sqlToCustomType(b"123", int)
        assert success is True
        assert value == 123

    def testBytesFloatToFloat(self) -> None:
        """Test that sqlToCustomType decodes bytes and converts to float."""
        success, value = sqlToCustomType(b"3.14", float)
        assert success is True
        assert value == pytest.approx(3.14)

    def testBytesTrueBool(self) -> None:
        """Test that sqlToCustomType decodes bytes 'true' and converts to bool True."""
        success, value = sqlToCustomType(b"true", bool)
        assert success is True
        assert value is True

    def testBytesFalseBool(self) -> None:
        """Test that sqlToCustomType decodes bytes 'false' and converts to bool False."""
        success, value = sqlToCustomType(b"false", bool)
        assert success is True
        assert value is False

    def testBytesOneBool(self) -> None:
        """Test that sqlToCustomType decodes bytes '1' and converts to bool True."""
        success, value = sqlToCustomType(b"1", bool)
        assert success is True
        assert value is True

    def testBytesZeroBool(self) -> None:
        """Test that sqlToCustomType decodes bytes '0' and converts to bool False."""
        success, value = sqlToCustomType(b"0", bool)
        assert success is True
        assert value is False

    def testBytesDictToDict(self) -> None:
        """Test that sqlToCustomType decodes bytes JSON and parses to dict."""
        success, value = sqlToCustomType(b'{"key": "value"}', dict)
        assert success is True
        assert value == {"key": "value"}

    def testBytesListToList(self) -> None:
        """Test that sqlToCustomType decodes bytes JSON and parses to list."""
        success, value = sqlToCustomType(b"[1, 2, 3]", list)
        assert success is True
        assert value == [1, 2, 3]

    def testBytesDatetime(self) -> None:
        """Test that sqlToCustomType decodes bytes and parses to datetime."""
        success, value = sqlToCustomType(b"2024-01-15 10:30:00", datetime.datetime)
        assert success is True
        assert isinstance(value, datetime.datetime)
        assert value.year == 2024
        assert value.month == 1
        assert value.day == 15


class TestConvertSqlResponseToTypeStrInput:
    """Test suite for sqlToCustomType with str input.

    Tests conversion of strings to various target types.
    """

    def testStrIntToInt(self) -> None:
        """Test that sqlToCustomType converts string integer to int."""
        success, value = sqlToCustomType("456", int)
        assert success is True
        assert value == 456

    def testStrNegativeIntToInt(self) -> None:
        """Test that sqlToCustomType converts negative string integer to int."""
        success, value = sqlToCustomType("-10", int)
        assert success is True
        assert value == -10

    def testStrFloatToFloat(self) -> None:
        """Test that sqlToCustomType converts string float to float."""
        success, value = sqlToCustomType("2.718", float)
        assert success is True
        assert value == pytest.approx(2.718)

    def testStrTrueBool(self) -> None:
        """Test that sqlToCustomType converts 'true' string to bool True."""
        for trueVal in ["true", "True", "TRUE", "1", "yes", "y"]:
            success, value = sqlToCustomType(trueVal, bool)
            assert success is True, f"Expected success for {trueVal!r}"
            assert value is True, f"Expected True for {trueVal!r}"

    def testStrFalseBool(self) -> None:
        """Test that sqlToCustomType converts 'false' string to bool False."""
        for falseVal in ["false", "False", "FALSE", "0", "no", "n"]:
            success, value = sqlToCustomType(falseVal, bool)
            assert success is True, f"Expected success for {falseVal!r}"
            assert value is False, f"Expected False for {falseVal!r}"

    def testStrInvalidBoolReturnsFailure(self) -> None:
        """Test that sqlToCustomType returns (False, None) for unrecognized boolean string."""
        success, value = sqlToCustomType("maybe", bool)
        assert success is False
        assert value is None

    def testStrDictToDict(self) -> None:
        """Test that sqlToCustomType parses JSON string to dict."""
        success, value = sqlToCustomType('{"a": 1}', dict)
        assert success is True
        assert value == {"a": 1}

    def testStrListToList(self) -> None:
        """Test that sqlToCustomType parses JSON string to list."""
        success, value = sqlToCustomType("[1, 2]", list)
        assert success is True
        assert value == [1, 2]

    def testStrInvalidJsonReturnsFailure(self) -> None:
        """Test that sqlToCustomType returns (False, None) for invalid JSON string."""
        success, value = sqlToCustomType("not-json", dict)
        assert success is False
        assert value is None

    def testStrDatetime(self) -> None:
        """Test that sqlToCustomType parses ISO datetime string to datetime."""
        success, value = sqlToCustomType("2024-06-01T12:00:00", datetime.datetime)
        assert success is True
        assert isinstance(value, datetime.datetime)
        assert value.year == 2024

    def testStrGenericDictType(self) -> None:
        """Test that sqlToCustomType parses JSON string to dict for generic dict[str, int]."""
        success, value = sqlToCustomType('{"x": 10}', dict[str, int])
        assert success is True
        assert value == {"x": 10}

    def testStrGenericListType(self) -> None:
        """Test that sqlToCustomType parses JSON string to list for generic list[str]."""
        success, value = sqlToCustomType('["a", "b"]', list[str])
        assert success is True
        assert value == ["a", "b"]


class TestConvertSqlResponseToTypeIntInput:
    """Test suite for sqlToCustomType when data is a raw int.

    Tests conversion of int values (SQLite boolean/number) to other types.
    """

    def testIntOneToBool(self) -> None:
        """Test that sqlToCustomType converts int 1 to bool True."""
        success, value = sqlToCustomType(1, bool)
        assert success is True
        assert value is True

    def testIntZeroToBool(self) -> None:
        """Test that sqlToCustomType converts int 0 to bool False."""
        success, value = sqlToCustomType(0, bool)
        assert success is True
        assert value is False

    def testIntToFloat(self) -> None:
        """Test that sqlToCustomType converts raw int to float."""
        success, value = sqlToCustomType(5, float)
        assert success is True
        assert value == pytest.approx(5.0)

    def testIntToStr(self) -> None:
        """Test that sqlToCustomType converts raw int to str."""
        success, value = sqlToCustomType(42, str)
        assert success is True
        assert value == "42"

    def testIntToUnsupportedTypeReturnsFailure(self) -> None:
        """Test that sqlToCustomType returns (False, None) when int cannot be converted to target type."""
        success, value = sqlToCustomType(42, datetime.datetime)
        assert success is False
        assert value is None


class TestConvertSqlResponseToTypeBoolInput:
    """Test suite for sqlToCustomType when data is a raw bool.

    Tests conversion of bool values to other types.
    """

    def testBoolTrueToInt(self) -> None:
        """Test that sqlToCustomType converts bool True to int 1."""
        success, value = sqlToCustomType(True, int)
        assert success is True
        assert value == 1

    def testBoolFalseToInt(self) -> None:
        """Test that sqlToCustomType converts bool False to int 0."""
        success, value = sqlToCustomType(False, int)
        assert success is True
        assert value == 0

    def testBoolTrueToStr(self) -> None:
        """Test that sqlToCustomType converts bool True to 'True' string."""
        success, value = sqlToCustomType(True, str)
        assert success is True
        assert value == "True"

    def testBoolFalseToStr(self) -> None:
        """Test that sqlToCustomType converts bool False to 'False' string."""
        success, value = sqlToCustomType(False, str)
        assert success is True
        assert value == "False"


class TestConvertSqlResponseToTypeEdgeCases:
    """Test suite for sqlToCustomType edge cases.

    Tests error handling and boundary conditions.
    """

    def testUnsupportedTypeReturnsFailure(self) -> None:
        """Test that sqlToCustomType returns (False, None) for unsupported type conversions."""
        success, value = sqlToCustomType([], int)
        assert success is False
        assert value is None

    def testEmptyStringToIntFails(self) -> None:
        """Test that sqlToCustomType returns (False, None) when empty string cannot become int."""
        success, value = sqlToCustomType("", int)
        assert success is False
        assert value is None

    def testEmptyStringToFloatFails(self) -> None:
        """Test that sqlToCustomType returns (False, None) when empty string cannot become float."""
        success, value = sqlToCustomType("", float)
        assert success is False
        assert value is None

    def testFloatStringToInt(self) -> None:
        """Test that sqlToCustomType fails when float string '3.14' is converted to int."""
        success, value = sqlToCustomType("3.14", int)
        # int("3.14") raises ValueError — expected failure
        assert success is False
        assert value is None

    def testAlreadyCorrectTypeDictReturnsAsIs(self) -> None:
        """Test that sqlToCustomType returns dict as-is when already correct type."""
        inputData: dict = {"key": "value"}
        success, value = sqlToCustomType(inputData, dict)
        assert success is True
        assert value == {"key": "value"}
