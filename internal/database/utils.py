"""
Database utility functions for type conversion and validation.

This module provides utility functions for converting between SQL data types
and Python types, including datetime, boolean, and custom type conversions.
It also includes type checking and TypedDict validation utilities.
"""

import datetime
import json
import logging
import types
from typing import Optional, Tuple, Type, TypeVar, Union, get_args, get_origin, get_type_hints, is_typeddict

import dateutil

logger = logging.getLogger(__name__)

DEFAULT_THREAD_ID: int = 0
"""Default thread ID for database operations."""
FORCE_SQL_TIMEZONE: Optional[datetime.tzinfo] = datetime.timezone.utc
"""If datetime from SQL have no timezone, force this one"""


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
    # We treat bool and int as distinct types to avoid silent leakage.
    if expectedType is int and isinstance(value, bool):
        return False
    if expectedType is bool and isinstance(value, int) and not isinstance(value, bool):
        return False

    return isinstance(value, expectedType)


def sqlToCustomType(data: object, expectedType: Type[_T]) -> Tuple[bool, Optional[_T]]:
    """Convert SQL response data to the expected Python type.

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
    if _checkType(data, expectedType):
        # Little trick fo forcing timezone
        if expectedType is datetime.datetime and isinstance(data, datetime.datetime):
            if data.tzinfo is None and FORCE_SQL_TIMEZONE is not None:
                data = data.replace(tzinfo=FORCE_SQL_TIMEZONE)
        return True, data  # pyright: ignore[reportReturnType]

    if isinstance(data, bytes):
        data = data.decode(encoding="utf-8", errors="ignore")

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
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to convert bool {data!r} to {expectedType}: {e}")
            return False, None

    if isinstance(data, str):
        try:
            # SQLite in many cases return string, so we can convert it ourselves to the expected type
            if expectedType is int:
                return True, int(data)  # pyright: ignore[reportReturnType]
            elif expectedType is float:
                return True, float(data)  # pyright: ignore[reportReturnType]
            elif expectedType is bool:
                # Handle both true and false values explicitly
                lowerData = data.lower()
                if lowerData in ["true", "1", "yes", "y"]:
                    return True, True  # pyright: ignore[reportReturnType]
                elif lowerData in ["false", "0", "no", "n"]:
                    return True, False  # pyright: ignore[reportReturnType]
                else:
                    logger.warning(f"Invalid boolean string value: {data!r}")
                    return False, None
            elif expectedType in [dict, list]:
                return True, json.loads(data)  # pyright: ignore[reportReturnType]
            elif expectedType is datetime.datetime:
                dtRet = dateutil.parser.parse(data)
                if dtRet.tzinfo is None and FORCE_SQL_TIMEZONE is not None:
                    dtRet = dtRet.replace(tzinfo=FORCE_SQL_TIMEZONE)
                return True, dtRet  # pyright: ignore[reportReturnType]

            # Handle generic types like dict[str, int] or list[str]
            originType = get_origin(expectedType)
            if originType in [dict, list]:
                return True, json.loads(data)  # pyright: ignore[reportReturnType]

            # Try to call the type constructor as a fallback
            return True, expectedType(data)  # pyright: ignore[reportCallIssue]

        except (ValueError, json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to convert {data!r} to {expectedType}: {e}")
            return False, None

    logger.debug(f"Cannot convert non-string/bytes data {data!r} to {expectedType}")
    return False, None


def sqlToTypedDict(data: dict, typedDictClass: Type[_T], *, keepOriginal: bool = False) -> _T:
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
        data = data.copy()

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
