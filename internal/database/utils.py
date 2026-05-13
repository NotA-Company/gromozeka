"""
Database utility functions for type conversion and validation.

This module provides utility functions for converting between SQL data types
and Python types, including datetime, boolean, and custom type conversions.
It also includes type checking and TypedDict validation utilities.
"""

import datetime
import json
import logging
import math
import types
from collections.abc import Mapping, MutableMapping, MutableSequence, MutableSet, Sequence, Set
from typing import Any, Optional, Tuple, Type, TypeVar, Union, get_args, get_origin, get_type_hints, is_typeddict

import dateutil

logger = logging.getLogger(__name__)

DEFAULT_THREAD_ID: int = 0
"""Default thread ID for database operations."""
FORCE_SQL_TIMEZONE: Optional[datetime.tzinfo] = datetime.timezone.utc
"""If datetime from SQL have no timezone, force this one"""

LIST_LIKE_TYPES = (list, Sequence, MutableSequence)
TUPLE_LIKE_TYPES = (tuple,)
SET_LIKE_TYPES = (set, Set, MutableSet)
DICT_LIKE_TYPES = (dict, Mapping)
SEQUENCE_LIKE_TYPES = LIST_LIKE_TYPES + TUPLE_LIKE_TYPES + SET_LIKE_TYPES
CONTAINER_TYPES = SEQUENCE_LIKE_TYPES + DICT_LIKE_TYPES


_T = TypeVar("_T")
"""Generic type variable for type conversion functions."""


def _checkType(value: object, expectedType: type) -> bool:
    """Recursively check whether value matches expectedType.

    Handles plain types, Union / X | Y unions, and shallow generic
    containers (e.g. list[str] — only the origin type is checked).

    Note: bool is treated as distinct from int — a bool value will
    NOT satisfy an int check, and an int value will NOT satisfy a
    bool check. This prevents silent type leakage since bool is a
    subclass of int in Python.

    Args:
        value: The value to type-check.
        expectedType: The type annotation to check against.

    Returns:
        True if the value is compatible with the expected type.
    """
    # Any type — accept anything (isinstance() raises TypeError for Any)
    if expectedType is Any:  # type: ignore[comparison-overlap]
        return True

    origin: type | None = get_origin(expectedType)

    # Union[X, Y] or X | Y (Python 3.10+ union syntax)
    if origin is Union or isinstance(expectedType, types.UnionType):
        return any(_checkType(value, arg) for arg in get_args(expectedType))

    # Generic alias like list[str], dict[str, int] — check only the container type
    if origin is not None:
        return isinstance(value, origin)

    # Plain type — NoneType must be matched explicitly
    if expectedType is type(None):
        return value is None

    # Fix: bool is a subclass of int in Python, so isinstance(True, int) == True.
    # We treat bool and int as distinct types to avoid subtle errors.
    if expectedType is int and isinstance(value, bool):
        return False
    if expectedType is bool and not isinstance(value, bool):
        return False

    # TypedDict class — isinstance() raises TypeError for TypedDict, so check
    # that value is a dict-like container instead.
    if is_typeddict(expectedType):
        return isinstance(value, dict)

    return isinstance(value, expectedType)


def sqlToCustomType(data: object, expectedType: Type[_T]) -> Tuple[bool, Optional[_T]]:
    """Recursively Convert SQL response data to the expected Python type.

    This function attempts to convert raw SQL response data (typically strings or bytes)
    to the specified expected type. It handles common type conversions including
    integers, floats, booleans, dictionaries, lists, and datetime objects.

    Args:
        data: The raw data from SQL response (typically str, bytes, or already typed).
        expectedType: The target type to convert to. Can be a plain type or a generic
            type like dict[str, int] or list[str].

    Returns:
        A tuple of (success, convertedValue):
            - success: True if conversion succeeded, False otherwise.
            - convertedValue: The converted value if successful, None otherwise.

    Examples:
        >>> sqlToCustomType(b"123", int)
        (True, 123)
        >>> sqlToCustomType(b"true", bool)
        (True, True)
        >>> sqlToCustomType(b'{"key": "value"}', dict)
        (True, {'key': 'value'})
    """
    # If no conversion needed, just return the data as-is.
    # For types with generic args (list[int], dict[str, int], Optional[X], etc.)
    # and TypedDicts, do NOT pass through — elements/keys/values/members may need conversion.
    expectedTypeArgs = get_args(expectedType)
    if _checkType(data, expectedType) and not expectedTypeArgs and not is_typeddict(expectedType):
        # Little trick fo forcing timezone
        if expectedType is datetime.datetime and isinstance(data, datetime.datetime):
            # logger.debug(f"Got datetime: {repr(data)}")
            if data.tzinfo is None and FORCE_SQL_TIMEZONE is not None:
                data = data.replace(tzinfo=FORCE_SQL_TIMEZONE)
            # logger.debug(f"Converted datetime: {repr(data)}")
        return True, data  # pyright: ignore[reportReturnType]

    expectedOrigin = get_origin(expectedType)
    # Unwrap Optional/Union types to get the inner type for conversion
    if expectedOrigin is Union or isinstance(expectedType, types.UnionType):
        # Try each union member type
        for arg in expectedTypeArgs:
            ok, value = sqlToCustomType(data, arg)
            if ok:
                return ok, value  # pyright: ignore[reportReturnType]
        # If none of the union members worked, return failure
        return False, None

    if isinstance(data, bytes):
        # Assume nobody expect bytes (also we've checked exact types match in _checkType branch)
        data = data.decode(encoding="utf-8", errors="ignore")

    if isinstance(data, float):
        try:
            if expectedType is int:
                return True, int(math.floor(data))  # pyright: ignore[reportReturnType]
            elif expectedType is str:
                return True, str(data)  # pyright: ignore[reportReturnType]
            elif expectedType is datetime.datetime:
                return True, datetime.datetime.fromtimestamp(
                    data, FORCE_SQL_TIMEZONE
                )  # pyright: ignore[reportReturnType]
            else:
                return True, expectedType(data)  # pyright: ignore[reportCallIssue]
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to convert float {data} to {expectedType}: {e}")
            return False, None

    # Fix: SQLite may return raw int values for boolean and float columns.
    # When data is an int (but not bool), attempt numeric conversions before
    # falling through to the str branch.
    if isinstance(data, int) and not isinstance(data, bool):
        try:
            if expectedType is bool:
                return True, bool(data)  # pyright: ignore[reportReturnType]
            elif expectedType is float:
                return True, float(data)  # pyright: ignore[reportReturnType]
            elif expectedType is str:
                return True, str(data)  # pyright: ignore[reportReturnType]
            elif expectedType is datetime.datetime:
                return True, datetime.datetime.fromtimestamp(
                    data, FORCE_SQL_TIMEZONE
                )  # pyright: ignore[reportReturnType]
            else:
                return True, expectedType(data)  # pyright: ignore[reportCallIssue]
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to convert int {data!r} to {expectedType}: {e}")
            return False, None

    # Fix: SQLite may return raw bool (True/False) for some drivers. Handle conversion.
    if isinstance(data, bool):
        try:
            if expectedType is int:
                return True, int(data)  # pyright: ignore[reportReturnType]
            elif expectedType is str:
                return True, str(data)  # pyright: ignore[reportReturnType]
            else:
                return True, expectedType(data)  # pyright: ignore[reportCallIssue]
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to convert bool {data!r} to {expectedType}: {e}")
            return False, None

    if isinstance(data, str):
        try:
            # SQLite in many cases return string, so we can convert it ourselves to the expected type
            if expectedType is bool:
                # checking for bool should be before int as bull is subtype of int

                # Handle both true and false values explicitly
                lowerData = data.lower()
                if lowerData in ["true", "1", "yes", "y"]:
                    return True, True  # pyright: ignore[reportReturnType]
                elif lowerData in ["false", "0", "no", "n"]:
                    return True, False  # pyright: ignore[reportReturnType]
                else:
                    logger.warning(f"Invalid boolean string value: {data!r}")
                    return False, None
            elif expectedType is int:
                return True, int(data)  # pyright: ignore[reportReturnType]
            elif expectedType is float:
                return True, float(data)  # pyright: ignore[reportReturnType]
            elif is_typeddict(expectedType):
                try:
                    return True, sqlToTypedDict(json.loads(data), expectedType)  # pyright: ignore[reportReturnType]
                except (KeyError, ValueError, TypeError) as e:
                    logger.error(f"Failed to convert {data} to {expectedType}: {e}")
                    return False, None
            elif expectedType in CONTAINER_TYPES or expectedOrigin in CONTAINER_TYPES or is_typeddict(expectedType):
                # Not sure if TypedDict (or it's origin) is also one of DICT_LIKE_TYPES, so check it exclusivelly
                # Some container, unwrap JSON first
                data = json.loads(data)
                # We do not need to do recursion here as checks for container types are
                # after checking for str
            elif expectedType is datetime.datetime:
                # logger.debug(f"Str-Datetime: {repr(data)}")
                dtRet = dateutil.parser.parse(data)
                # logger.debug(f"Parsed datetime: {repr(dtRet)}")
                if dtRet.tzinfo is None and FORCE_SQL_TIMEZONE is not None:
                    dtRet = dtRet.replace(tzinfo=FORCE_SQL_TIMEZONE)
                # logger.debug(f"Converted datetime: {repr(dtRet)}")
                return True, dtRet  # pyright: ignore[reportReturnType]
            else:
                # Try to call the type constructor as a fallback
                return True, expectedType(data)  # pyright: ignore[reportCallIssue]

        except (ValueError, json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to convert {data!r} to {expectedType}: {e}")
            return False, None

    # NOTE: str and bytes are subclasses of Sequence, i.e.:
    # >>> isinstance("String", Sequence)
    # True
    # >>> isinstance(b"Bytes", Sequence)
    # True
    # So it should be AFTER bytes and str checking (actually dicts could be before, but whatever).

    # If expectedType is a list/tuple/set (Or it's generic variant), convert each item
    # Actually non-generic types should be processed by _checkType() branch, but whatever
    if isinstance(data, SEQUENCE_LIKE_TYPES) and (
        expectedType in SEQUENCE_LIKE_TYPES or expectedOrigin in SEQUENCE_LIKE_TYPES
    ):
        if not expectedTypeArgs or not expectedTypeArgs[0]:
            if expectedType in LIST_LIKE_TYPES:
                return True, list(data)  # pyright: ignore[reportReturnType]
            elif expectedType in TUPLE_LIKE_TYPES:
                return True, tuple(data)  # pyright: ignore[reportReturnType]
            elif expectedType in SET_LIKE_TYPES:
                return True, set(data)  # pyright: ignore[reportReturnType]
            else:
                logger.error(f"Unexpected conversion {type(data).__name__}({data}) to {expectedType.__name__}")
                return False, None

        ret = []
        argType = expectedTypeArgs[0]
        for item in data:
            ok, value = sqlToCustomType(item, argType)
            if not ok:
                return False, None
            ret.append(value)

        if expectedOrigin in TUPLE_LIKE_TYPES:
            return True, tuple(ret)  # pyright: ignore[reportReturnType]
        elif expectedOrigin in SET_LIKE_TYPES:
            return True, set(ret)  # pyright: ignore[reportReturnType]
        elif expectedOrigin in LIST_LIKE_TYPES:
            return True, ret  # pyright: ignore[reportReturnType]
        else:
            logger.error(f"Unexpected conversion {type(data).__name__}({data}) to {expectedType.__name__}")
            return False, None

    # Convert dict to typed dict if expectedType is a TypedDict
    if isinstance(data, DICT_LIKE_TYPES) and is_typeddict(expectedType):
        try:
            return True, sqlToTypedDict(data, expectedType)  # pyright: ignore[reportReturnType]
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Failed to convert {data} to {expectedType}: {e}")
            return False, None

    # Process dicts and Generic Dicts (Dict[K,V])
    # Actually non-generic types should be processed by _checkType() branch, but whatever
    if isinstance(data, DICT_LIKE_TYPES) and (expectedType in DICT_LIKE_TYPES or expectedOrigin in DICT_LIKE_TYPES):
        if not expectedTypeArgs or len(expectedTypeArgs) != 2:
            return True, dict(data)  # pyright: ignore[reportReturnType]

        ret = {}
        keyType = expectedTypeArgs[0]
        valueType = expectedTypeArgs[1]
        for key, value in data.items():
            ok, key = sqlToCustomType(key, keyType)
            if not ok:
                return False, None
            ok, value = sqlToCustomType(value, valueType)
            if not ok:
                return False, None
            ret[key] = value

        return True, ret  # pyright: ignore[reportReturnType]

    logger.debug(f"Cannot convert data {data!r} to {expectedType}")
    return False, None


def sqlToTypedDict(data: dict | Mapping, typedDictClass: Type[_T], *, keepOriginal: bool = False) -> _T:
    """Validate data against typedDictClass and return it cast to that type.

    Checks that every required key is present and that all provided values
    match the declared type annotations. Optional keys are allowed to be
    absent, but when present their values are still type-checked.

    Args:
        data: The plain dict to validate and cast.
        typedDictClass: The TypedDict class that defines the expected schema.
        keepOriginal: If True, the original data dict should not be modified.

    Returns:
        data cast to typedDictClass (no copy is made unless keepOriginal is True).

    Raises:
        TypeError: If typedDictClass is not a TypedDict subclass, or if any
            value in data does not match its declared annotation.
        KeyError: If a required key declared in typedDictClass is absent
            from data.
    """
    if keepOriginal:
        # Create a copy of data to avoid modifying the original
        data = dict(data)
    elif isinstance(data, Mapping) and not isinstance(data, MutableMapping):
        # We'll need to mutate result dict, so in case of unmutable Mapping, wrap it into dict
        data = dict(data)

    if not is_typeddict(typedDictClass):
        raise TypeError(f"{typedDictClass!r} is not a TypedDict class")

    hints: dict[str, type] = get_type_hints(typedDictClass)
    requiredKeys: frozenset[str] = typedDictClass.__required_keys__  # type: ignore[attr-defined]

    # Ensure every required key is present
    for key in requiredKeys:
        if key not in data:
            raise KeyError(f"Missing required key '{key}' for TypedDict '{typedDictClass.__name__}'")

    # Type-check every key that is present in data
    for key, expectedType in hints.items():
        if key not in data:
            continue

        # Not just check if type is valid, but try to convert it if possible
        #  as SQLite does not really support types like datetime, bool, dicts, lists, etc...
        ok, value = sqlToCustomType(data[key], expectedType)
        if not ok:
            raise TypeError(
                f"Field '{key}' of '{typedDictClass.__name__}' expected "
                f"{expectedType}, got {type(data[key]).__name__}"
            )
        else:
            data[key] = value

    return data  # type: ignore[return-value]


def getCurrentTimestamp() -> datetime.datetime:
    """Get the current UTC timestamp.

    Returns:
        A datetime object representing the current time in UTC.
    """
    return datetime.datetime.now(datetime.timezone.utc)
