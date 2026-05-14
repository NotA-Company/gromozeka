"""
Test suite for internal/database/utils.py.

Tests the utility functions for type conversion and SQL response handling:
- _checkType: Type checking with support for Optional, Union, and generic types
- sqlToCustomType: Converts SQL responses to specified Python types
- sqlToDatetime: Converts SQL datetime strings to datetime objects
- sqlToBoolean: Converts SQL boolean bytes to Python bool
- datetimeToSql: Converts datetime objects to SQL-compatible strings
"""

# pyright: reportTypedDictNotRequiredAccess=false

import datetime
from typing import Any, Optional, Union

import pytest

from internal.bot.models.ensured_message import CondensingDict, MetadataDict
from internal.database.utils import (
    _checkType,
    sqlToCustomType,
)
from internal.models.types import MessageId


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

    def testIntToDatetime(self) -> None:
        """Test that sqlToCustomType converts raw int to timezone-aware datetime (Unix timestamp)."""
        success, value = sqlToCustomType(42, datetime.datetime)
        assert success is True
        assert isinstance(value, datetime.datetime)
        assert value.tzinfo == datetime.timezone.utc

    def testIntToUnsupportedTypeReturnsFailure(self) -> None:
        """Test that sqlToCustomType returns (False, None) when int cannot be converted to target type."""
        success, value = sqlToCustomType(42, datetime.date)
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


class TestSqlToCustomTypeOptionalUnion:
    """Test suite for sqlToCustomType Optional and Union type handling.

    Tests the recent fixes for proper Optional/Union handling, including:
    - None handling with Optional types
    - None handling with Union types that don't include None
    - Non-None values with Optional types
    - Union type resolution and fallback
    - Edge cases with incompatible data
    """

    # Optional handling (when data is None)
    def testOptionalNoneWithStr(self) -> None:
        """Test Optional[str] with None returns (True, None)."""
        success, value = sqlToCustomType(None, Optional[str])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is None

    def testOptionalNoneWithInt(self) -> None:
        """Test Optional[int] with None returns (True, None)."""
        success, value = sqlToCustomType(None, Optional[int])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is None

    def testOptionalNoneWithDatetime(self) -> None:
        """Test Optional[datetime.datetime] with None returns (True, None).

        This is a real-world scenario that was broken before the fix.
        """
        success, value = sqlToCustomType(None, Optional[datetime.datetime])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is None

    def testUnionNoneWithoutNoneType(self) -> None:
        """Test Union[int, str] with None returns (False, None) since None is not in the union."""
        success, value = sqlToCustomType(None, Union[int, str])  # pyright: ignore[reportArgumentType]
        assert success is False
        assert value is None

    # Optional handling (when data is not None)
    def testOptionalDatetimeStringToDatetime(self) -> None:
        """Test datetime string to Optional[datetime.datetime] converts correctly."""
        success, value = sqlToCustomType(
            "2024-06-15T14:30:00",
            Optional[datetime.datetime],  # pyright: ignore[reportArgumentType]
        )
        assert success is True
        assert isinstance(value, datetime.datetime)
        assert value.year == 2024
        assert value.month == 6
        assert value.day == 15
        assert value.hour == 14
        assert value.minute == 30

    def testOptionalBytesToInt(self) -> None:
        """Test bytes to Optional[int] converts correctly."""
        success, value = sqlToCustomType(b"42", Optional[int])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == 42

    def testOptionalStrToStr(self) -> None:
        """Test str to Optional[str] passes through correctly."""
        success, value = sqlToCustomType("hello", Optional[str])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == "hello"

    # Union handling
    def testUnionNumericStringToIntStr(self) -> None:
        """Test numeric string to Union[int, str] keeps str (do not convert if match any type).
        """
        success, value = sqlToCustomType("123", Union[int, str])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == "123"
        assert isinstance(value, str)

    def testUnionNumerToIntStr(self) -> None:
        """Test numeric string to Union[int, str] keeps int (do not convert if match any type).
        """
        success, value = sqlToCustomType(123, Union[int, str])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == 123
        assert isinstance(value, int)

    def testUnionAlphaStringToStr(self) -> None:
        """Test alphabetic string to Union[int, str] falls back to str when int fails."""
        success, value = sqlToCustomType("abc", Union[int, str])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == "abc"
        assert isinstance(value, str)

    def testUnionIntToUnionStrInt(self) -> None:
        """Test int value with Union[str, int] keep int
        """
        success, value = sqlToCustomType(42, Union[str, int])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == 42
        assert isinstance(value, int)

    def testUnionBytesTrueToBool(self) -> None:
        """Test bytes 'true' to Union[int, bool] matches bool."""
        success, value = sqlToCustomType(b"true", Union[int, bool])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is True
        assert isinstance(value, bool)

    def testUnionBytesNumericToInt(self) -> None:
        """Test bytes '42' to Union[str, int] converts to int after str conversion fails??

        Note: Since b"42" can be converted to str via decode, and str comes first in the union,
        it returns "42" as a string. This test validates the actual behavior.
        """
        success, value = sqlToCustomType(b"42", Union[str, int])  # pyright: ignore[reportArgumentType]
        assert success is True
        # bytes convert to str first since str is first in Union
        assert value == "42"
        assert isinstance(value, str)

    # Edge cases
    def testNoneWithNonOptionalTypeFails(self) -> None:
        """Test None with non-Optional type returns (False, None)."""
        success, value = sqlToCustomType(None, int)
        assert success is False
        assert value is None

    def testIncompatibleDataWithOptionalFails(self) -> None:
        """Test incompatible data type with Optional returns (False, None)."""
        success, value = sqlToCustomType([], Optional[int])  # pyright: ignore[reportArgumentType]
        assert success is False
        assert value is None


class TestSqlToCustomTypeGenericSequences:
    """Test suite for sqlToCustomType with generic sequence types.

    Tests conversion of list, tuple, and set data to their generic variants
    (e.g. list[int], tuple[str, ...], set[float]), including element conversion.
    """

    def testListOfIntFromListOfBytes(self) -> None:
        """Test list of bytes converts to list[int] with element conversion."""
        success, value = sqlToCustomType([b"1", b"2", b"3"], list[int])
        assert success is True
        assert value == [1, 2, 3]

    def testListOfStrFromListOfInt(self) -> None:
        """Test list of int converts to list[str] with element conversion."""
        success, value = sqlToCustomType([1, 2, 3], list[str])
        assert success is True
        assert value == ["1", "2", "3"]

    def testListOfBoolFromListOfInt(self) -> None:
        """Test list[int] to list[bool] converts 0/1 to False/True."""
        success, value = sqlToCustomType([0, 1, 0], list[bool])
        assert success is True
        assert value == [False, True, False]

    def testListOfBoolFromListOfStr(self) -> None:
        """Test list of str true/false/1/0 converts to list[bool]."""
        success, value = sqlToCustomType(["true", "false", "1", "0", "yes", "no"], list[bool])
        assert success is True
        assert value == [True, False, True, False, True, False]

    def testListOfFloatFromMixedElements(self) -> None:
        """Test list of mixed int and bytes converts to list[float]."""
        success, value = sqlToCustomType([1, b"2.5", 3], list[float])
        assert success is True
        assert value == [pytest.approx(1.0), pytest.approx(2.5), pytest.approx(3.0)]

    def testTupleOfIntFromList(self) -> None:
        """Test list of bytes converts to tuple[int, ...]."""
        success, value = sqlToCustomType([b"10", b"20"], tuple[int, ...])
        assert success is True
        assert value == (10, 20)
        assert isinstance(value, tuple)

    def testTupleOfIntFromTuple(self) -> None:
        """Test tuple of bytes stays as tuple[int, ...] with element conversion."""
        success, value = sqlToCustomType((b"10", b"20"), tuple[int, ...])
        assert success is True
        assert value == (10, 20)
        assert isinstance(value, tuple)

    def testSetOfIntFromList(self) -> None:
        """Test list of bytes converts to set[int]."""
        success, value = sqlToCustomType([b"1", b"2", b"2"], set[int])
        assert success is True
        assert value == {1, 2}
        assert isinstance(value, set)

    def testSetOfIntFromSet(self) -> None:
        """Test set of bytes converts to set[int]."""
        success, value = sqlToCustomType({b"1", b"2"}, set[int])
        assert success is True
        assert value == {1, 2}
        assert isinstance(value, set)

    def testSetOfStrFromListOfBytes(self) -> None:
        """Test list of bytes converts to set[str]."""
        success, value = sqlToCustomType([b"a", b"b", b"a"], set[str])
        assert success is True
        assert value == {"a", "b"}

    def testPlainListPassthrough(self) -> None:
        """Test plain list type passes through without element conversion (no generic args)."""
        data = [1, "a", True]
        success, value = sqlToCustomType(data, list)
        assert success is True
        assert value == data

    def testPlainTuplePassthrough(self) -> None:
        """Test plain tuple type passes through without element conversion."""
        data = [1, 2]
        success, value = sqlToCustomType(data, tuple)
        assert success is True
        assert value == (1, 2)
        assert isinstance(value, tuple)

    def testPlainSetPassthrough(self) -> None:
        """Test plain set type converts data to set without element conversion."""
        data = [1, 2, 2]
        success, value = sqlToCustomType(data, set)
        assert success is True
        assert value == {1, 2}
        assert isinstance(value, set)

    def testListOfDatetimeFromListOfStr(self) -> None:
        """Test list[str] to list[datetime] converts ISO strings."""
        success, value = sqlToCustomType(["2024-01-15T10:30:00", "2024-06-01T12:00:00"], list[datetime.datetime])
        assert success is True
        assert value is not None
        assert len(value) == 2
        assert all(isinstance(v, datetime.datetime) for v in value)
        assert value[0].year == 2024
        assert value[0].month == 1
        assert value[1].month == 6

    def testListConversionFailureOnBadElement(self) -> None:
        """Test list[bytes] to list[int] fails when an element cannot be converted."""
        success, value = sqlToCustomType([b"1", b"x", b"3"], list[int])
        assert success is False
        assert value is None

    def testSetConversionFailureOnBadElement(self) -> None:
        """Test set[int] conversion fails when an element cannot be converted."""
        success, value = sqlToCustomType({b"1", b"not-int"}, set[int])
        assert success is False
        assert value is None

    def testTupleConversionFailureOnBadElement(self) -> None:
        """Test tuple[int, ...] conversion fails when an element cannot be converted."""
        success, value = sqlToCustomType((b"1", b"bad"), tuple[int, ...])
        assert success is False
        assert value is None

    def testEmptyListToGenericList(self) -> None:
        """Test empty list to list[int] returns empty list."""
        success, value = sqlToCustomType([], list[int])
        assert success is True
        assert value == []

    def testEmptyTupleToGenericTuple(self) -> None:
        """Test empty list to tuple[int, ...] returns empty tuple."""
        success, value = sqlToCustomType([], tuple[int, ...])
        assert success is True
        assert value == ()

    def testEmptySetToGenericSet(self) -> None:
        """Test empty list to set[int] returns empty set."""
        success, value = sqlToCustomType([], set[int])
        assert success is True
        assert value == set()

    def testSequenceTypeMismatch(self) -> None:
        """Test string (which is a Sequence) does not inadvertently match sequence conversion."""
        success, value = sqlToCustomType("hello", list[str])
        assert success is False
        assert value is None


class TestSqlToCustomTypeGenericDicts:
    """Test suite for sqlToCustomType with generic dict types.

    Tests conversion of dict data to generic dict variants (e.g. dict[str, int]),
    including key and value conversion.
    """

    def testDictStrIntFromRawDict(self) -> None:
        """Test raw dict with bytes keys and str values converts to dict[str, int]."""
        success, value = sqlToCustomType({b"key": b"123", b"other": b"456"}, dict[str, int])
        assert success is True
        assert value == {"key": 123, "other": 456}

    def testDictIntBoolFromRawDict(self) -> None:
        """Test raw dict with str int keys and int values converts to dict[int, bool]."""
        success, value = sqlToCustomType({b"1": 0, b"2": 1}, dict[int, bool])
        assert success is True
        assert value == {1: False, 2: True}

    def testDictStrFloatFromRawDict(self) -> None:
        """Test raw dict with bytes values converts to dict[str, float]."""
        success, value = sqlToCustomType({b"x": b"2.5", b"y": b"3.14"}, dict[str, float])
        assert success is True
        assert value == {"x": pytest.approx(2.5), "y": pytest.approx(3.14)}

    def testDictStrStrFromRawDict(self) -> None:
        """Test raw dict with int values converts to dict[str, str]."""
        success, value = sqlToCustomType({b"a": 1, b"b": 2}, dict[str, str])
        assert success is True
        assert value == {"a": "1", "b": "2"}

    def testPlainDictPassthrough(self) -> None:
        """Test plain dict type passes through without key/value conversion."""
        data = {"a": 1, "b": True}
        success, value = sqlToCustomType(data, dict)
        assert success is True
        assert value == data

    def testDictConversionFailureOnBadValue(self) -> None:
        """Test dict[str, int] fails when a value cannot be converted to int."""
        success, value = sqlToCustomType({b"key": b"not-int"}, dict[str, int])
        assert success is False
        assert value is None

    def testDictConversionFailureOnBadKey(self) -> None:
        """Test dict[int, str] fails when a key cannot be converted to int."""
        success, value = sqlToCustomType({b"not-int": b"value"}, dict[int, str])
        assert success is False
        assert value is None

    def testEmptyDictToGenericDict(self) -> None:
        """Test empty dict to dict[str, int] returns empty dict."""
        success, value = sqlToCustomType({}, dict[str, int])
        assert success is True
        assert value == {}

    def testDictStrDatetimeFromRawDict(self) -> None:
        """Test dict[str, datetime] converts ISO string values to datetime."""
        success, value = sqlToCustomType({b"created": b"2024-06-01T12:00:00"}, dict[str, datetime.datetime])
        assert success is True
        assert value is not None
        assert isinstance(value["created"], datetime.datetime)
        assert value["created"].year == 2024


class TestSqlToCustomTypeNestedContainers:
    """Test suite for sqlToCustomType with nested container types.

    Tests deeply nested type conversions such as list[dict[str, int]],
    dict[str, list[int]], and deeper nesting.
    """

    def testListOfListInt(self) -> None:
        """Test list[list[int]] with nested lists of str/bytes."""
        success, value = sqlToCustomType([[b"1", b"2"], [b"3"]], list[list[int]])
        assert success is True
        assert value == [[1, 2], [3]]

    def testListOfDictStrInt(self) -> None:
        """Test list[dict[str, int]] with nested dicts."""
        success, value = sqlToCustomType([{b"a": b"1"}, {b"b": b"2"}], list[dict[str, int]])
        assert success is True
        assert value == [{"a": 1}, {"b": 2}]

    def testDictStrListInt(self) -> None:
        """Test dict[str, list[int]] with nested lists."""
        success, value = sqlToCustomType({b"x": [b"1", b"2"], b"y": [b"3"]}, dict[str, list[int]])
        assert success is True
        assert value == {"x": [1, 2], "y": [3]}

    def testDictStrDictStrInt(self) -> None:
        """Test dict[str, dict[str, int]] with nested dicts."""
        success, value = sqlToCustomType({b"outer": {b"inner": b"42"}}, dict[str, dict[str, int]])
        assert success is True
        assert value == {"outer": {"inner": 42}}

    def testListOfTupleOfInt(self) -> None:
        """Test list[tuple[int, ...]] with nested tuples."""
        success, value = sqlToCustomType([[b"1", b"2"], [b"3"]], list[tuple[int, ...]])
        assert success is True
        assert value == [(1, 2), (3,)]

    def testTupleOfListOfInt(self) -> None:
        """Test tuple[list[int], ...] with nested lists."""
        data = ([b"1", b"2"], [b"3"])
        success, value = sqlToCustomType(data, tuple[list[int], ...])
        assert success is True
        assert value == ([1, 2], [3])

    def testDictStrSetInt(self) -> None:
        """Test dict[str, set[int]] with nested sets."""
        success, value = sqlToCustomType({b"nums": [b"1", b"2", b"2"]}, dict[str, set[int]])
        assert success is True
        assert value == {"nums": {1, 2}}

    def testDeeplyNestedThreeLevels(self) -> None:
        """Test dict[str, dict[str, dict[str, int]]] three levels deep."""
        success, value = sqlToCustomType(
            {b"a": {b"b": {b"c": b"42"}}},
            dict[str, dict[str, dict[str, int]]],
        )
        assert success is True
        assert value == {"a": {"b": {"c": 42}}}

    def testDeeplyNestedFourLevels(self) -> None:
        """Test deeply nested list[list[dict[str, list[int]]]]."""
        success, value = sqlToCustomType(
            [[{b"x": [b"1", b"2"]}]],
            list[list[dict[str, list[int]]]],
        )
        assert success is True
        assert value == [[{"x": [1, 2]}]]

    def testNestedConversionFailureDeep(self) -> None:
        """Test nested conversion fails when a deep element cannot be converted."""
        success, value = sqlToCustomType([[b"1"], [b"x"]], list[list[int]])
        assert success is False
        assert value is None

    def testNestedConversionFailureInDictValue(self) -> None:
        """Test nested conversion fails when a dict value cannot be converted."""
        success, value = sqlToCustomType([{b"a": b"1"}, {b"b": b"bad"}], list[dict[str, int]])
        assert success is False
        assert value is None

    def testEmptyNestedContainers(self) -> None:
        """Test empty nested containers return empty structures."""
        success, value = sqlToCustomType([], list[dict[str, int]])
        assert success is True
        assert value == []

    def testNestedWithDatetimeConversion(self) -> None:
        """Test list[list[datetime]] converts nested ISO strings to datetimes."""
        success, value = sqlToCustomType(
            [[b"2024-01-15T10:30:00"], [b"2024-06-01T12:00:00"]],
            list[list[datetime.datetime]],
        )
        assert success is True
        assert value is not None
        assert len(value) == 2
        assert isinstance(value[0][0], datetime.datetime)
        assert value[0][0].year == 2024
        assert value[0][0].month == 1
        assert value[1][0].month == 6


class TestSqlToCustomTypeAnyType:
    """Test suite for sqlToCustomType with typing.Any type.

    Tests that Any accepts and passes through all Python values without conversion.
    """

    def testAnyIntPassthrough(self) -> None:
        """Test int passes through as-is for Any type."""
        success, value = sqlToCustomType(42, Any)  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == 42
        assert isinstance(value, int)

    def testAnyStrPassthrough(self) -> None:
        """Test str passes through as-is for Any type."""
        success, value = sqlToCustomType("hello", Any)  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == "hello"
        assert isinstance(value, str)

    def testAnyBoolPassthrough(self) -> None:
        """Test bool passes through as-is for Any type."""
        success, value = sqlToCustomType(True, Any)  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is True
        assert isinstance(value, bool)

    def testAnyNonePassthrough(self) -> None:
        """Test None passes through as-is for Any type."""
        success, value = sqlToCustomType(None, Any)  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is None

    def testAnyFloatPassthrough(self) -> None:
        """Test float passes through as-is for Any type."""
        success, value = sqlToCustomType(3.14, Any)  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == pytest.approx(3.14)
        assert isinstance(value, float)

    def testAnyBytesPassthrough(self) -> None:
        """Test bytes passes through as-is for Any type (Any accepts anything, no decoding)."""
        success, value = sqlToCustomType(b"hello", Any)  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == b"hello"
        assert isinstance(value, bytes)

    def testAnyListPassthrough(self) -> None:
        """Test list passes through as-is for Any type."""
        data = [1, "a", True]
        success, value = sqlToCustomType(data, Any)  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == data

    def testAnyDictPassthrough(self) -> None:
        """Test dict passes through as-is for Any type."""
        data = {"key": "value"}
        success, value = sqlToCustomType(data, Any)  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == data

    def testAnyDatetimePassthrough(self) -> None:
        """Test datetime passes through as-is for Any type (no timezone forcing for Any)."""
        dtNaive = datetime.datetime(2024, 1, 15, 10, 30, 0)
        success, value = sqlToCustomType(dtNaive, Any)  # pyright: ignore[reportArgumentType]
        assert success is True
        assert isinstance(value, datetime.datetime)
        # Any type does not force timezone — only explicit datetime.datetime type does
        assert value.tzinfo is None

    def testAnyWithOptionalAny(self) -> None:
        """Test Optional[Any] with None returns (True, None)."""
        success, value = sqlToCustomType(None, Optional[Any])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is None

    def testAnyWithOptionalAnyValue(self) -> None:
        """Test Optional[Any] with a value returns (True, value)."""
        success, value = sqlToCustomType(42, Optional[Any])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == 42


class TestSqlToCustomTypeAnyInContainers:
    """Test suite for sqlToCustomType when Any is used as a type argument in containers.

    Tests that Any correctly accepts and passes through values in generic
    containers like Dict[str, Any], List[Dict[str, Any]], etc.
    """

    def testDictStrAnyWithMixedValues(self) -> None:
        """Test Dict[str, Any] with bytes, int, str, None — all pass through as-is."""
        data = {b"a": b"val", "b": 42, b"c": None, b"d": "plain"}
        success, value = sqlToCustomType(data, dict[str, Any])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is not None
        assert value == {"a": b"val", "b": 42, "c": None, "d": "plain"}
        # Bytes value stays as bytes (Any does not decode)
        assert isinstance(value["a"], bytes)

    def testDictStrAnyWithBytesValue(self) -> None:
        """Test Dict[str, Any] preserves bytes values without decoding."""
        success, value = sqlToCustomType({b"key": b"123"}, dict[str, Any])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is not None
        assert value == {"key": b"123"}
        assert isinstance(value["key"], bytes)

    def testDictStrAnyFromJsonString(self) -> None:
        """Test Dict[str, Any] parses JSON string and preserves nested types.

        When the data is a JSON string, it's parsed first, then key/value conversion
        is applied. Bytes values that are already parsed from JSON become str.
        """
        success, value = sqlToCustomType('{"x": 1, "y": [1, 2]}', dict[str, Any])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == {"x": 1, "y": [1, 2]}

    def testDictAnyStr(self) -> None:
        """Test Dict[Any, str] — keys pass through as-is, values are converted to str."""
        data = {b"key1": b"val1", 42: b"val2"}
        success, value = sqlToCustomType(data, dict[Any, str])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is not None
        # Keys stay as-is (bytes preserved for Any), values converted to str
        assert value == {b"key1": "val1", 42: "val2"}
        assert isinstance(list(value.keys())[0], bytes)
        assert isinstance(list(value.values())[0], str)

    def testDictAnyAny(self) -> None:
        """Test Dict[Any, Any] — everything passes through as-is."""
        data = {b"key": b"value", 1: True, None: [1, 2]}
        success, value = sqlToCustomType(data, dict[Any, Any])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == data

    def testListAnyWithMixedElements(self) -> None:
        """Test List[Any] with bytes, int, str, None — all pass through."""
        data = [b"1", 2, "three", None, True]
        success, value = sqlToCustomType(data, list[Any])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is not None
        assert value == data
        assert isinstance(value[0], bytes)

    def testListAnyFromJsonString(self) -> None:
        """Test List[Any] parses JSON string and preserves all elements."""
        success, value = sqlToCustomType('[1, "two", null, true]', list[Any])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == [1, "two", None, True]

    def testListDictStrAny(self) -> None:
        """Test List[Dict[str, Any]] — nested dicts with Any values."""
        data = [{b"a": b"1", b"b": 2}]
        success, value = sqlToCustomType(data, list[dict[str, Any]])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is not None
        assert value == [{"a": b"1", "b": 2}]
        assert isinstance(value[0]["a"], bytes)

    def testDictStrListAny(self) -> None:
        """Test Dict[str, List[Any]] — nested lists with Any elements."""
        data = {b"x": [b"1", 2, None]}
        success, value = sqlToCustomType(data, dict[str, list[Any]])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is not None
        assert value == {"x": [b"1", 2, None]}
        assert isinstance(value["x"][0], bytes)

    def testDictStrDictStrAny(self) -> None:
        """Test Dict[str, Dict[str, Any]] — deeply nested with Any leaf."""
        data = {b"outer": {b"inner": b"42"}}
        success, value = sqlToCustomType(data, dict[str, dict[str, Any]])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is not None
        assert value == {"outer": {"inner": b"42"}}
        assert isinstance(value["outer"]["inner"], bytes)

    def testTupleAny(self) -> None:
        """Test tuple[Any, ...] — all elements pass through as-is."""
        data = (b"1", 2, None)
        success, value = sqlToCustomType(data, tuple[Any, ...])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == (b"1", 2, None)
        assert isinstance(value, tuple)
        assert isinstance(value[0], bytes)

    def testSetAny(self) -> None:
        """Test set[Any] — all elements pass through as-is."""
        data = {b"a", b"b"}
        success, value = sqlToCustomType(data, set[Any])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is not None
        assert value == {b"a", b"b"}
        assert isinstance(next(iter(value)), bytes)

    def testUnionIntAny(self) -> None:
        """Test Union[int, Any] — Any is catches everything.
        """
        success, value = sqlToCustomType("hello", Union[int, Any])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == "hello"

        success, value = sqlToCustomType(b"42", Union[int, Any])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == b"42"
        assert isinstance(value, bytes)

    def testUnionAnyStr(self) -> None:
        """Test Union[Any, str] — Any always succeeds first, bytes are not decoded."""
        # Any succeeds first, returning bytes as-is (no str conversion)
        success, value = sqlToCustomType(b"test", Union[Any, str])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == b"test"
        assert isinstance(value, bytes)

        # Already a str — passes through via Any
        success, value = sqlToCustomType("plain", Union[Any, str])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == "plain"
        assert isinstance(value, str)

    def testOptionalDictStrAnyWithNone(self) -> None:
        """Test Optional[Dict[str, Any]] with None — returns None."""
        success, value = sqlToCustomType(None, Optional[dict[str, Any]])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is None

    def testOptionalDictStrAnyWithValue(self) -> None:
        """Test Optional[Dict[str, Any]] with real dict — keys converted, values pass through."""
        data = {b"key": b"val"}
        success, value = sqlToCustomType(data, Optional[dict[str, Any]])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == {"key": b"val"}

    def testDictAnyBool(self) -> None:
        """Test Dict[Any, bool] — keys pass through, values converted to bool."""
        data = {b"enable": 1, b"disable": b"0"}
        success, value = sqlToCustomType(data, dict[Any, bool])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is not None
        assert value == {b"enable": True, b"disable": False}
        assert isinstance(value[b"enable"], bool)

    def testEmptyContainersWithAny(self) -> None:
        """Test empty containers with Any type args return empty structures."""
        success, value = sqlToCustomType([], list[Any])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == []

        success, value = sqlToCustomType({}, dict[str, Any])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == {}

        success, value = sqlToCustomType([], tuple[Any, ...])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == ()


class TestSqlToCustomTypeMessageId:
    """Test suite for sqlToCustomType with MessageId as expected type.

    MessageId is a wrapper class that accepts int | str. Tests cover direct
    conversion, use as dict value, and use in Union/Optional types.
    """

    def testMessageIdFromStr(self) -> None:
        """Test str converts to MessageId via constructor fallback."""
        success, value = sqlToCustomType("abc123", MessageId)
        assert success is True
        assert isinstance(value, MessageId)
        assert value.messageId == "abc123"

    def testMessageIdFromBytes(self) -> None:
        """Test bytes decodes to str then constructs MessageId."""
        success, value = sqlToCustomType(b"42", MessageId)
        assert success is True
        assert isinstance(value, MessageId)
        assert value.messageId == "42"

    def testMessageIdPassthrough(self) -> None:
        """Test existing MessageId instance passes through as-is."""
        msgId = MessageId(42)
        success, value = sqlToCustomType(msgId, MessageId)
        assert success is True
        assert value is msgId

    def testMessageIdFromInt(self) -> None:
        """Test int converts to MessageId via catch-all constructor fallback in int branch."""
        success, value = sqlToCustomType(42, MessageId)
        assert success is True
        assert isinstance(value, MessageId)
        assert value.messageId == 42

    def testOptionalMessageIdWithNone(self) -> None:
        """Test Optional[MessageId] with None returns (True, None)."""
        success, value = sqlToCustomType(None, Optional[MessageId])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is None

    def testOptionalMessageIdWithStr(self) -> None:
        """Test Optional[MessageId] with str constructs MessageId via union member."""
        success, value = sqlToCustomType("hello", Optional[MessageId])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert isinstance(value, MessageId)
        assert value.messageId == "hello"

    def testOptionalMessageIdWithBytes(self) -> None:
        """Test Optional[MessageId] with bytes decodes and constructs MessageId."""
        success, value = sqlToCustomType(b"99", Optional[MessageId])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert isinstance(value, MessageId)
        assert value.messageId == "99"

    def testDictStrMessageId(self) -> None:
        """Test Dict[str, MessageId] with bytes values converts each to MessageId."""
        success, value = sqlToCustomType({b"reply": b"42", b"forward": b"77"}, dict[str, MessageId])
        assert success is True
        assert value is not None
        assert set(value.keys()) == {"reply", "forward"}
        assert isinstance(value["reply"], MessageId)
        assert value["reply"].messageId == "42"
        assert isinstance(value["forward"], MessageId)
        assert value["forward"].messageId == "77"

    def testDictStrMessageIdFromIntValues(self) -> None:
        """Test Dict[str, MessageId] with int values constructs MessageId from each."""
        success, value = sqlToCustomType({b"id": 42}, dict[str, MessageId])
        assert success is True
        assert value is not None
        assert isinstance(value["id"], MessageId)
        assert value["id"].messageId == 42

    def testListMessageId(self) -> None:
        """Test List[MessageId] with bytes elements converts each."""  # pyright: ignore[reportUnknownArgumentType]
        success, value = sqlToCustomType([b"1", b"abc"], list[MessageId])  # pyright: ignore[reportUnknownArgumentType]
        assert success is True
        assert value is not None
        assert len(value) == 2
        assert all(isinstance(v, MessageId) for v in value)
        assert value[0].messageId == "1"
        assert value[1].messageId == "abc"

    def testMessageIdInUnion(self) -> None:
        """Test Union[MessageId, str] — MessageId succeeds first for str data."""
        success, value = sqlToCustomType("test", Union[MessageId, str])  # pyright: ignore[reportArgumentType]
        assert success is True
        # MessageId is tried first since it's listed first in the union
        assert isinstance(value, str)
        assert value == "test"


class TestSqlToCustomTypeMetadataDict:
    """Test suite for sqlToCustomType with real TypedDict classes.

    Uses MetadataDict (total=False, all optional fields) and its nested
    CondensingDict to test TypedDict validation through sqlToCustomType.
    """

    def testMetadataDictEmpty(self) -> None:
        """Test empty dict for MetadataDict passes (all fields optional)."""
        success, value = sqlToCustomType({}, MetadataDict)
        assert success is True
        assert value == {}

    def testMetadataDictWithStringKeys(self) -> None:
        """Test MetadataDict with some optional fields as strings."""
        data = {
            "randomContext": "some context",
            "messagePrefix": "[bot] ",
        }
        success, value = sqlToCustomType(data, MetadataDict)
        assert success is True
        assert value is not None
        assert value["randomContext"] == "some context"
        assert value["messagePrefix"] == "[bot] "

    def testMetadataDictWithBytesKeysAndValues(self) -> None:
        """Test MetadataDict with bytes values (simulating SQL output).

        Keys come from JSON/dict construction and are always strings;
        values from SQL may be bytes and need conversion.
        """
        data = {
            "randomContext": b"context from db",
            "messagePrefix": b"db-prefix",
        }
        success, value = sqlToCustomType(data, MetadataDict)
        assert success is True
        assert value is not None
        assert value["randomContext"] == "context from db"
        assert value["messagePrefix"] == "db-prefix"

    def testMetadataDictForwardedFrom(self) -> None:
        """Test MetadataDict with forwardedFrom field (Dict[str, Any])."""
        data = {
            "forwardedFrom": {
                "date": "2024-01-01T00:00:00",
                "type": "channel",
                "from_title": "Test Channel",
                "from_id": -100123,
            }
        }
        success, value = sqlToCustomType(data, MetadataDict)
        assert success is True
        assert value is not None
        assert value["forwardedFrom"]["type"] == "channel"
        assert value["forwardedFrom"]["from_id"] == -100123

    def testMetadataDictForwardedFromBytes(self) -> None:
        """Test MetadataDict with forwardedFrom values as bytes (SQL output).

        forwardedFrom is Dict[str, Any] so bytes values are preserved as-is.
        """
        data: dict = {
            "forwardedFrom": {
                "date": b"2024-01-01T00:00:00",
                "type": b"channel",
                "from_title": b"Test",
            }
        }
        success, value = sqlToCustomType(data, MetadataDict)
        assert success is True
        assert value is not None
        # Dict[str, Any] preserves bytes as-is for Any values
        assert value["forwardedFrom"]["type"] == b"channel"
        assert isinstance(value["forwardedFrom"]["type"], bytes)

    def testMetadataDictWithUsedTools(self) -> None:
        """Test MetadataDict with usedTools (List[Dict[str, Any]])."""
        data = {
            "usedTools": [
                {"name": "search", "result": "found"},
                {"name": "calc", "result": 42},
            ]
        }
        success, value = sqlToCustomType(data, MetadataDict)
        assert success is True
        assert value is not None
        assert len(value["usedTools"]) == 2
        assert value["usedTools"][0]["name"] == "search"

    def testMetadataDictWithCondensedThread(self) -> None:
        """Test MetadataDict with condensedThread containing CondensingDict entries."""
        data = {
            "condensedThread": [
                {"text": "summary 1", "tillMessageId": "42", "tillTS": 1700.5},
                {"text": "summary 2", "tillMessageId": "99", "tillTS": 1800.0},
                {"text": "summary 3", "tillMessageId": 100, "tillTS": 1800.0},
            ]
        }
        success, value = sqlToCustomType(data, MetadataDict)
        assert success is True
        assert value is not None
        assert len(value["condensedThread"]) == 3
        assert value["condensedThread"][0]["text"] == "summary 1"
        assert isinstance(value["condensedThread"][0]["tillMessageId"], MessageId)
        assert value["condensedThread"][0]["tillMessageId"].messageId == "42"
        assert value["condensedThread"][0]["tillTS"] == pytest.approx(1700.5)
        assert isinstance(value["condensedThread"][2]["tillMessageId"], MessageId)
        assert value["condensedThread"][2]["tillMessageId"].messageId == 100

    def testMetadataDictCondensedThreadBytes(self) -> None:
        """Test MetadataDict with condensedThread values as bytes (SQL output)."""
        data: dict = {
            "condensedThread": [
                {"text": b"summary", "tillMessageId": b"77", "tillTS": 1234.0},
            ]
        }
        success, value = sqlToCustomType(data, MetadataDict)
        assert success is True
        assert value is not None
        assert value["condensedThread"][0]["text"] == "summary"
        assert isinstance(value["condensedThread"][0]["tillMessageId"], MessageId)
        assert value["condensedThread"][0]["tillMessageId"].messageId == "77"

    def testMetadataDictFromJsonString(self) -> None:
        """Test MetadataDict parsed from JSON string."""
        jsonStr = '{"randomContext": "ctx", "messagePrefix": "PREFIX"}'
        success, value = sqlToCustomType(jsonStr, MetadataDict)
        assert success is True
        assert value is not None
        assert value["randomContext"] == "ctx"
        assert value["messagePrefix"] == "PREFIX"

    def testMetadataDictFullFromJsonString(self) -> None:
        """Test MetadataDict with all fields parsed from JSON string."""
        import json

        fullData = {
            "condensedThread": [{"text": "s", "tillMessageId": "1", "tillTS": 100.0}],
            "randomContext": "ctx",
            "forwardedFrom": {"type": "user"},
            "messagePrefix": "P",
            "usedTools": [{"name": "t"}],
        }
        jsonStr = json.dumps(fullData)
        success, value = sqlToCustomType(jsonStr, MetadataDict)
        assert success is True
        assert value is not None
        assert value["condensedThread"][0]["text"] == "s"
        assert value["randomContext"] == "ctx"
        assert value["forwardedFrom"]["type"] == "user"
        assert value["messagePrefix"] == "P"
        assert value["usedTools"][0]["name"] == "t"

    def testMetadataDictInvalidFieldType(self) -> None:
        """Test MetadataDict with unconvertible value for a field returns failure."""
        # randomContext must be str; a list cannot be converted to str
        data = {"randomContext": [1, 2, 3]}
        success, value = sqlToCustomType(data, MetadataDict)
        assert success is False
        assert value is None

    def testMetadataDictCondensedThreadMixedTypes(self) -> None:
        """Test CondensingDict with int tillMessageId — converts to MessageId.

        The int branch has a catch-all using the type constructor, so MessageId(42) works.
        """
        data = {"condensedThread": [{"text": "s", "tillMessageId": 42, "tillTS": 100.0}]}
        success, value = sqlToCustomType(data, MetadataDict)
        assert success is True
        assert value is not None
        assert isinstance(value["condensedThread"][0]["tillMessageId"], MessageId)
        assert value["condensedThread"][0]["tillMessageId"].messageId == 42

    def testCondensingDictDirect(self) -> None:
        """Test CondensingDict directly (not nested in MetadataDict)."""
        data = {"text": "summary text", "tillMessageId": "101", "tillTS": 2000.0}
        success, value = sqlToCustomType(data, CondensingDict)
        assert success is True
        assert value is not None
        assert value["text"] == "summary text"
        assert isinstance(value["tillMessageId"], MessageId)
        assert value["tillMessageId"].messageId == "101"
        assert value["tillTS"] == pytest.approx(2000.0)

    def testCondensingDictBytes(self) -> None:
        """Test CondensingDict with bytes values (SQL output)."""
        data = {"text": b"summary", "tillMessageId": b"202", "tillTS": 3000.0}
        success, value = sqlToCustomType(data, CondensingDict)
        assert success is True
        assert value is not None
        assert value["text"] == "summary"
        assert isinstance(value["tillMessageId"], MessageId)
        assert value["tillTS"] == pytest.approx(3000.0)

    def testCondensingDictMissingRequiredField(self) -> None:
        """Test CondensingDict missing required field returns (False, None)."""
        data = {"text": "only text"}
        success, value = sqlToCustomType(data, CondensingDict)
        assert success is False
        assert value is None

    def testCondensingDictFromJsonString(self) -> None:
        """Test CondensingDict parsed from JSON string."""
        import json

        data = {"text": "s", "tillMessageId": "1", "tillTS": 100.0}
        success, value = sqlToCustomType(json.dumps(data), CondensingDict)
        assert success is True
        assert value is not None
        assert value["text"] == "s"

    def testListCondensingDict(self) -> None:
        """Test List[CondensingDict] with nested TypedDict entries."""
        data = [
            {"text": "first", "tillMessageId": "1", "tillTS": 1.0},
            {"text": "second", "tillMessageId": "2", "tillTS": 2.0},
        ]
        success, value = sqlToCustomType(data, list[CondensingDict])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is not None
        assert len(value) == 2
        assert value[0]["text"] == "first"
        assert isinstance(value[0]["tillMessageId"], MessageId)

    def testListCondensingDictBytes(self) -> None:
        """Test List[CondensingDict] with bytes values (SQL output)."""
        data = [
            {"text": b"first", "tillMessageId": b"1", "tillTS": 1.0},
        ]
        success, value = sqlToCustomType(data, list[CondensingDict])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is not None
        assert value[0]["text"] == "first"
        assert isinstance(value[0]["tillMessageId"], MessageId)

    def testOptionalMetadataDictWithNone(self) -> None:
        """Test Optional[MetadataDict] with None returns (True, None)."""
        success, value = sqlToCustomType(None, Optional[MetadataDict])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is None

    def testOptionalMetadataDictWithDict(self) -> None:
        """Test Optional[MetadataDict] with valid dict returns converted TypedDict."""
        data = {"randomContext": "test"}
        success, value = sqlToCustomType(data, Optional[MetadataDict])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is not None
        assert value["randomContext"] == "test"


class TestSqlToCustomTypeFloatInput:
    """Test suite for sqlToCustomType when data is a float.

    Tests conversion of float values to int (floor), str, and datetime.
    """

    def testFloatToIntFloor(self) -> None:
        """Test float 3.14 converts to int 3 (floor, not round)."""
        success, value = sqlToCustomType(3.14, int)
        assert success is True
        assert value == 3
        assert isinstance(value, int)

    def testFloatToIntFloorNegative(self) -> None:
        """Test negative float -3.14 converts to int -4 (floor)."""
        success, value = sqlToCustomType(-3.14, int)
        assert success is True
        assert value == -4

    def testFloatToStr(self) -> None:
        """Test float converts to str representation."""
        success, value = sqlToCustomType(3.14, str)
        assert success is True
        assert value == "3.14"
        assert isinstance(value, str)

    def testFloatZeroToStr(self) -> None:
        """Test float 0.0 converts to '0.0'."""
        success, value = sqlToCustomType(0.0, str)
        assert success is True
        assert value == "0.0"

    def testFloatToDatetime(self) -> None:
        """Test float Unix timestamp converts to timezone-aware datetime."""
        success, value = sqlToCustomType(1705315800.0, datetime.datetime)
        assert success is True
        assert isinstance(value, datetime.datetime)
        assert value.tzinfo == datetime.timezone.utc


class TestSqlToCustomTypeAdditionalEdgeCases:
    """Test suite for additional sqlToCustomType edge cases and corner cases.

    Covers scenarios not covered by existing test classes: nested conversion
    edge cases, type boundary behavior, and error propagation.
    """

    def testStringIsSequenceButNotContainerTarget(self) -> None:
        """Test that a string (which is a Sequence) does not match list target.

        Strings are Sequence subclasses in Python, but sqlToCustomType must
        not treat 'hello' as a list of characters when target is list[str].
        """
        success, value = sqlToCustomType("hello", list[str])
        assert success is False
        assert value is None

    def testBytesIsSequenceButNotContainerTarget(self) -> None:
        """Test that bytes (which is a Sequence) does not match list target."""
        success, value = sqlToCustomType(b"hello", list[int])
        assert success is False
        assert value is None

    def testSetToPlainList(self) -> None:
        """Test set data converts to plain list type."""
        success, value = sqlToCustomType({1, 2, 3}, list)
        assert success is True
        assert isinstance(value, list)
        assert set(value) == {1, 2, 3}

    def testListToPlainSet(self) -> None:
        """Test list data converts to plain set type."""
        success, value = sqlToCustomType([1, 2, 2], set)
        assert success is True
        assert isinstance(value, set)
        assert value == {1, 2}

    def testListOfOptionalIntFromList(self) -> None:
        """Test list[Optional[int]] with mixed None and int values."""
        success, value = sqlToCustomType([b"1", None, b"3"], list[Optional[int]])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == [1, None, 3]

    def testDictWithOptionalValue(self) -> None:
        """Test dict[str, Optional[int]] with mixed None and int values."""
        success, value = sqlToCustomType(
            {b"a": b"1", b"b": None}, dict[str, Optional[int]]  # pyright: ignore[reportArgumentType]
        )
        assert success is True
        assert value == {"a": 1, "b": None}

    def testFloatToBoolConversion(self) -> None:
        """Test float converts to bool via catch-all constructor (bool(1.0) = True)."""
        success, value = sqlToCustomType(1.0, bool)
        assert success is True
        assert value is True

        success, value = sqlToCustomType(0.0, bool)
        assert success is True
        assert value is False

    def testFloatToDictFails(self) -> None:
        """Test float cannot be converted to dict."""
        success, value = sqlToCustomType(3.14, dict)
        assert success is False
        assert value is None

    def testIntToBoolInList(self) -> None:
        """Test list[bool] correctly converts int 0/1 to False/True (not via bool subclass trick)."""
        success, value = sqlToCustomType([0, 1, 2], list[bool])
        assert success is True
        assert value == [False, True, True]

    def testDictFromDictLikeMapping(self) -> None:
        """Test that a Mapping (not dict) is converted to dict type.

        Uses types.MappingProxyType which is a read-only mapping.
        """
        import types as _types

        proxy = _types.MappingProxyType({"a": 1})
        success, value = sqlToCustomType(proxy, dict[str, int])
        assert success is True
        assert value == {"a": 1}
        assert isinstance(value, dict)

    def testFloatNaNToIntFails(self) -> None:
        """Test that float('nan') to int conversion fails."""
        success, value = sqlToCustomType(float("nan"), int)
        assert success is False
        assert value is None

    def testFloatInfToIntFails(self) -> None:
        """Test that float('inf') to int conversion raises OverflowError.

        math.floor(float('inf')) raises OverflowError which is not caught
        by the current implementation (only ValueError and TypeError are caught).
        """
        with pytest.raises(OverflowError):
            sqlToCustomType(float("inf"), int)

    def testUnionWithNoneViaNewSyntax(self) -> None:
        """Test int | None (Python 3.10+ union syntax) works like Optional[int]."""
        success, value = sqlToCustomType(None, int | None)  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is None

        success, value = sqlToCustomType(b"42", int | None)  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value == 42

    def testDatetimeWithTimezonePreserved(self) -> None:
        """Test datetime with existing timezone is preserved (not overwritten with UTC)."""
        import zoneinfo

        tz = zoneinfo.ZoneInfo("Europe/Moscow")
        dt = datetime.datetime(2024, 1, 15, 10, 30, 0, tzinfo=tz)
        success, value = sqlToCustomType(dt, datetime.datetime)
        assert success is True
        assert value is not None
        assert value.tzinfo == tz

    def testDatetimeNaiveGetsUtc(self) -> None:
        """Test naive datetime gets UTC timezone forced."""
        dt = datetime.datetime(2024, 1, 15, 10, 30, 0)
        success, value = sqlToCustomType(dt, datetime.datetime)
        assert success is True
        assert value is not None
        assert value.tzinfo == datetime.timezone.utc

    def testStrToDatetimeWithTimezone(self) -> None:
        """Test datetime string with timezone information parses correctly."""
        success, value = sqlToCustomType("2024-01-15T10:30:00+03:00", datetime.datetime)
        assert success is True
        assert value is not None
        assert isinstance(value, datetime.datetime)
        assert value.tzinfo is not None

    def testStrToDatetimeNaiveGetsUtc(self) -> None:
        """Test naive datetime string gets UTC timezone forced."""
        success, value = sqlToCustomType("2024-01-15 10:30:00", datetime.datetime)
        assert success is True
        assert value is not None
        assert value.tzinfo == datetime.timezone.utc
