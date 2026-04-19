"""
Tests for internal/database/utils.py — covering convertSqlResponseToType,
_checkType, sqlToDatetime, sqlToBoolean, and datetimeToSql, dood!
"""

import datetime
from typing import Optional, Union

import pytest

from internal.database.utils import (
    _checkType,
    datetimeToSql,
    sqlToBoolean,
    sqlToCustomType,
    sqlToDatetime,
)


class TestCheckType:
    """Tests for _checkType helper, dood!"""

    def testPlainTypeMatch(self) -> None:
        """Should return True when value matches plain type, dood!

        Returns:
            None
        """
        assert _checkType(42, int) is True
        assert _checkType("hello", str) is True
        assert _checkType(3.14, float) is True
        assert _checkType(True, bool) is True
        assert _checkType([], list) is True
        assert _checkType({}, dict) is True

    def testPlainTypeMismatch(self) -> None:
        """Should return False when value does not match plain type, dood!

        Returns:
            None
        """
        assert _checkType("hello", int) is False
        assert _checkType(42, str) is False
        assert _checkType(3.14, int) is False

    def testNoneTypeMatch(self) -> None:
        """Should return True only for None against NoneType, dood!

        Returns:
            None
        """
        assert _checkType(None, type(None)) is True

    def testNoneTypeMismatch(self) -> None:
        """Should return False for non-None value against NoneType, dood!

        Returns:
            None
        """
        assert _checkType(0, type(None)) is False
        assert _checkType("", type(None)) is False

    def testBoolIsNotInt(self) -> None:
        """Bool must NOT pass int check — they are distinct types, dood!

        Returns:
            None
        """
        assert _checkType(True, int) is False
        assert _checkType(False, int) is False

    def testIntIsNotBool(self) -> None:
        """Int must NOT pass bool check — they are distinct types, dood!

        Returns:
            None
        """
        assert _checkType(0, bool) is False
        assert _checkType(1, bool) is False

    def testOptionalMatch(self) -> None:
        """Should return True for None or T in Optional[T], dood!

        Returns:
            None
        """

        assert _checkType(None, Optional[int]) is True  # pyright: ignore[reportArgumentType]
        assert _checkType(42, Optional[int]) is True  # pyright: ignore[reportArgumentType]
        assert _checkType("str", Optional[int]) is False  # pyright: ignore[reportArgumentType]

    def testUnionMatch(self) -> None:
        """Should return True when value matches any Union branch, dood!

        Returns:
            None
        """

        assert _checkType(42, Union[int, str]) is True  # pyright: ignore[reportArgumentType]
        assert _checkType("hello", Union[int, str]) is True  # pyright: ignore[reportArgumentType]
        assert _checkType(3.14, Union[int, str]) is False  # pyright: ignore[reportArgumentType]

    def testGenericListMatch(self) -> None:
        """Should match on origin container type for generics, dood!

        Returns:
            None
        """
        assert _checkType([1, 2, 3], list[int]) is True
        assert _checkType({"a": 1}, dict[str, int]) is True

    def testGenericListMismatch(self) -> None:
        """Should return False when container origin does not match, dood!

        Returns:
            None
        """
        assert _checkType([1, 2], dict[str, int]) is False
        assert _checkType({"a": 1}, list[str]) is False


class TestConvertSqlResponseToTypeAlreadyCorrectType:
    """Tests for convertSqlResponseToType when data is already the correct type, dood!"""

    def testIntPassthrough(self) -> None:
        """Should return int as-is when already int and not bool, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(42, int)
        assert success is True
        assert value == 42

    def testStrPassthrough(self) -> None:
        """Should return str as-is when already str, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType("hello", str)
        assert success is True
        assert value == "hello"

    def testBoolPassthrough(self) -> None:
        """Should return bool as-is when already bool, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(True, bool)
        assert success is True
        assert value is True

    def testNonePassthrough(self) -> None:
        """Should return None for Optional[int] when data is None, dood!

        Returns:
            None
        """

        success, value = sqlToCustomType(None, Optional[int])  # pyright: ignore[reportArgumentType]
        assert success is True
        assert value is None

    def testFloatPassthrough(self) -> None:
        """Should return float as-is when already float, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(3.14, float)
        assert success is True
        assert value == pytest.approx(3.14)


class TestConvertSqlResponseToTypeBytesInput:
    """Tests for convertSqlResponseToType with bytes input, dood!"""

    def testBytesIntToInt(self) -> None:
        """Should decode bytes and convert to int, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(b"123", int)
        assert success is True
        assert value == 123

    def testBytesFloatToFloat(self) -> None:
        """Should decode bytes and convert to float, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(b"3.14", float)
        assert success is True
        assert value == pytest.approx(3.14)

    def testBytesTrueBool(self) -> None:
        """Should decode bytes 'true' and convert to bool True, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(b"true", bool)
        assert success is True
        assert value is True

    def testBytesFalseBool(self) -> None:
        """Should decode bytes 'false' and convert to bool False, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(b"false", bool)
        assert success is True
        assert value is False

    def testBytesOneBool(self) -> None:
        """Should decode bytes '1' and convert to bool True, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(b"1", bool)
        assert success is True
        assert value is True

    def testBytesZeroBool(self) -> None:
        """Should decode bytes '0' and convert to bool False, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(b"0", bool)
        assert success is True
        assert value is False

    def testBytesDictToDict(self) -> None:
        """Should decode bytes JSON and parse to dict, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(b'{"key": "value"}', dict)
        assert success is True
        assert value == {"key": "value"}

    def testBytesListToList(self) -> None:
        """Should decode bytes JSON and parse to list, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(b"[1, 2, 3]", list)
        assert success is True
        assert value == [1, 2, 3]

    def testBytesDatetime(self) -> None:
        """Should decode bytes and parse to datetime, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(b"2024-01-15 10:30:00", datetime.datetime)
        assert success is True
        assert isinstance(value, datetime.datetime)
        assert value.year == 2024
        assert value.month == 1
        assert value.day == 15


class TestConvertSqlResponseToTypeStrInput:
    """Tests for convertSqlResponseToType with str input, dood!"""

    def testStrIntToInt(self) -> None:
        """Should convert string integer to int, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType("456", int)
        assert success is True
        assert value == 456

    def testStrNegativeIntToInt(self) -> None:
        """Should convert negative string integer to int, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType("-10", int)
        assert success is True
        assert value == -10

    def testStrFloatToFloat(self) -> None:
        """Should convert string float to float, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType("2.718", float)
        assert success is True
        assert value == pytest.approx(2.718)

    def testStrTrueBool(self) -> None:
        """Should convert 'true' string to bool True, dood!

        Returns:
            None
        """
        for trueVal in ["true", "True", "TRUE", "1", "yes", "y"]:
            success, value = sqlToCustomType(trueVal, bool)
            assert success is True, f"Expected success for {trueVal!r}"
            assert value is True, f"Expected True for {trueVal!r}"

    def testStrFalseBool(self) -> None:
        """Should convert 'false' string to bool False, dood!

        Returns:
            None
        """
        for falseVal in ["false", "False", "FALSE", "0", "no", "n"]:
            success, value = sqlToCustomType(falseVal, bool)
            assert success is True, f"Expected success for {falseVal!r}"
            assert value is False, f"Expected False for {falseVal!r}"

    def testStrInvalidBoolReturnsFailure(self) -> None:
        """Should return (False, None) for unrecognized boolean string, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType("maybe", bool)
        assert success is False
        assert value is None

    def testStrDictToDict(self) -> None:
        """Should parse JSON string to dict, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType('{"a": 1}', dict)
        assert success is True
        assert value == {"a": 1}

    def testStrListToList(self) -> None:
        """Should parse JSON string to list, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType("[1, 2]", list)
        assert success is True
        assert value == [1, 2]

    def testStrInvalidJsonReturnsFailure(self) -> None:
        """Should return (False, None) for invalid JSON string, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType("not-json", dict)
        assert success is False
        assert value is None

    def testStrDatetime(self) -> None:
        """Should parse ISO datetime string to datetime, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType("2024-06-01T12:00:00", datetime.datetime)
        assert success is True
        assert isinstance(value, datetime.datetime)
        assert value.year == 2024

    def testStrGenericDictType(self) -> None:
        """Should parse JSON string to dict for generic dict[str, int], dood!

        Returns:
            None
        """
        success, value = sqlToCustomType('{"x": 10}', dict[str, int])
        assert success is True
        assert value == {"x": 10}

    def testStrGenericListType(self) -> None:
        """Should parse JSON string to list for generic list[str], dood!

        Returns:
            None
        """
        success, value = sqlToCustomType('["a", "b"]', list[str])
        assert success is True
        assert value == ["a", "b"]


class TestConvertSqlResponseToTypeIntInput:
    """Tests for convertSqlResponseToType when data is a raw int (SQLite boolean/number), dood!"""

    def testIntOneToBool(self) -> None:
        """Should convert int 1 to bool True, dood! (Critical fix)

        Returns:
            None
        """
        success, value = sqlToCustomType(1, bool)
        assert success is True
        assert value is True

    def testIntZeroToBool(self) -> None:
        """Should convert int 0 to bool False, dood! (Critical fix)

        Returns:
            None
        """
        success, value = sqlToCustomType(0, bool)
        assert success is True
        assert value is False

    def testIntToFloat(self) -> None:
        """Should convert raw int to float, dood! (Critical fix)

        Returns:
            None
        """
        success, value = sqlToCustomType(5, float)
        assert success is True
        assert value == pytest.approx(5.0)

    def testIntToStr(self) -> None:
        """Should convert raw int to str, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(42, str)
        assert success is True
        assert value == "42"

    def testIntToUnsupportedTypeReturnsFailure(self) -> None:
        """Should return (False, None) when int cannot be converted to target type, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(42, datetime.datetime)
        assert success is False
        assert value is None


class TestConvertSqlResponseToTypeBoolInput:
    """Tests for convertSqlResponseToType when data is a raw bool, dood!"""

    def testBoolTrueToInt(self) -> None:
        """Should convert bool True to int 1, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(True, int)
        assert success is True
        assert value == 1

    def testBoolFalseToInt(self) -> None:
        """Should convert bool False to int 0, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(False, int)
        assert success is True
        assert value == 0

    def testBoolTrueToStr(self) -> None:
        """Should convert bool True to lowercase 'true' string, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(True, str)
        assert success is True
        assert value == "True"

    def testBoolFalseToStr(self) -> None:
        """Should convert bool False to lowercase 'false' string, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType(False, str)
        assert success is True
        assert value == "False"


class TestConvertSqlResponseToTypeEdgeCases:
    """Edge case tests for convertSqlResponseToType, dood!"""

    def testUnsupportedTypeReturnsFailure(self) -> None:
        """Should return (False, None) for unsupported type conversions, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType([], int)
        assert success is False
        assert value is None

    def testEmptyStringToIntFails(self) -> None:
        """Should return (False, None) when empty string cannot become int, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType("", int)
        assert success is False
        assert value is None

    def testEmptyStringToFloatFails(self) -> None:
        """Should return (False, None) when empty string cannot become float, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType("", float)
        assert success is False
        assert value is None

    def testFloatStringToInt(self) -> None:
        """Should fail when float string '3.14' is converted to int, dood!

        Returns:
            None
        """
        success, value = sqlToCustomType("3.14", int)
        # int("3.14") raises ValueError — expected failure
        assert success is False
        assert value is None

    def testAlreadyCorrectTypeDictReturnsAsIs(self) -> None:
        """Should return dict as-is when already correct type, dood!

        Returns:
            None
        """
        inputData: dict = {"key": "value"}
        success, value = sqlToCustomType(inputData, dict)
        assert success is True
        assert value == {"key": "value"}


class TestSqlToDatetime:
    """Tests for sqlToDatetime, dood!"""

    def testBytesInput(self) -> None:
        """Should convert bytes datetime to datetime object, dood!

        Returns:
            None
        """
        result = sqlToDatetime(b"2024-01-15 10:30:00")
        assert isinstance(result, datetime.datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def testStrInput(self) -> None:
        """Should convert str datetime to datetime object, dood!

        Returns:
            None
        """
        result = sqlToDatetime("2024-06-20T08:00:00")
        assert isinstance(result, datetime.datetime)
        assert result.year == 2024
        assert result.month == 6


class TestSqlToBoolean:
    """Tests for sqlToBoolean, dood!"""

    def testEmptyBytesReturnsFalse(self) -> None:
        """Should return False for empty bytes, dood!

        Returns:
            None
        """
        result = sqlToBoolean(b"")
        assert result is False

    def testSingleByteOne(self) -> None:
        """Should return True for single byte '1', dood!

        Returns:
            None
        """
        result = sqlToBoolean(b"1")
        assert result is True

    def testSingleByteZero(self) -> None:
        """Should return False for single byte '0', dood!

        Returns:
            None
        """
        result = sqlToBoolean(b"0")
        assert result is False

    def testMultiBytesRaisesValueError(self) -> None:
        """Should raise ValueError for multi-byte input, dood!

        Returns:
            None
        """
        with pytest.raises(ValueError):
            sqlToBoolean(b"12")


class TestDatetimeToSql:
    """Tests for datetimeToSql, dood!"""

    def testDefaultStripTimezone(self) -> None:
        """Should return SQLite-compatible datetime string without timezone, dood!

        Returns:
            None
        """
        dt = datetime.datetime(2024, 3, 10, 14, 30, 45, 123456)
        result = datetimeToSql(dt)
        assert result == "2024-03-10 14:30:45"

    def testStripTimezoneAlsoStripsMicroseconds(self) -> None:
        """Should strip microseconds when stripTimezone=True, dood!

        Returns:
            None
        """
        dt = datetime.datetime(2024, 3, 10, 14, 30, 45, 999999)
        result = datetimeToSql(dt, stripTimezone=True)
        assert "999999" not in result
        assert result == "2024-03-10 14:30:45"

    def testNoStripTimezoneReturnsIso(self) -> None:
        """Should return ISO format without microseconds when stripTimezone=False, dood!

        Returns:
            None
        """
        dt = datetime.datetime(2024, 3, 10, 14, 30, 45, 123456)
        result = datetimeToSql(dt, stripTimezone=False)
        assert result == "2024-03-10T14:30:45"
