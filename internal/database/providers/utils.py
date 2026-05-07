"""Utility functions for database providers.

This module provides helper functions for converting Python data types to
SQL-compatible formats, suitable for SQLite, MySQL, PostgreSQL, and similar
database backends. These utilities are used by database provider implementations
to ensure consistent data type handling across different database systems.

The module focuses on:
- Converting Python native types to SQL-compatible formats
- Handling complex data structures (mappings, sequences) for database storage
- Providing type-safe conversion with appropriate logging for unsupported types

Example:
    >>> convertToSQLite({"key": "value"})
    '{"key": "value"}'
    >>> convertToSQLite([1, 2, 3])
    '[1, 2, 3]'
    >>> convertContainerElementsToSQLite({"a": 1, "b": True})
    {'a': 1, 'b': 1}
"""

import datetime
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Union

import lib.utils as libUtils

logger = logging.getLogger(__name__)
"""Module logger instance for database provider utilities."""


def convertToSQLite(data: Any) -> Union[str, int, float, None]:
    """Convert data to a SQL-compatible type.

    Converts various Python data types to formats suitable for SQL storage across
    multiple RDBMS (SQLite, MySQL, PostgreSQL). This function ensures that data
    can be properly stored in database columns without type errors.

    Type conversion rules:
    - str, int, float: returned as-is (already SQL-compatible)
    - dict, list, Mapping, Sequence: converted to JSON string using libUtils.jsonDumps
    - bool: converted to int (0 for False, 1 for True)
    - datetime.datetime: converted to ISO format string (YYYY-MM-DDTHH:MM:SS.ffffff)
    - None: returned as None (SQL NULL)
    - Other types: converted to string with a warning logged

    Args:
        data: The data to convert to SQL-compatible format. Can be any Python type.

    Returns:
        Union[str, int, float, None]: The converted data in SQL-compatible format.
        Returns None if input data is None. Returns JSON string for complex types.

    Example:
        >>> convertToSQLite("hello")
        'hello'
        >>> convertToSQLite(42)
        42
        >>> convertToSQLite(True)
        1
        >>> convertToSQLite({"key": "value"})
        '{"key": "value"}'
        >>> convertToSQLite([1, 2, 3])
        '[1, 2, 3]'
        >>> convertToSQLite(None)
        None
    """
    if data is None:
        return None
    elif isinstance(data, (str, int, float)):
        return data
    elif isinstance(data, (dict, list, tuple, Mapping, Sequence)):
        return libUtils.jsonDumps(data)
    elif isinstance(data, bool):
        return int(data)
    elif isinstance(data, datetime.datetime):
        return data.isoformat()
    else:
        logger.warning(f"Unsupported type {type(data)} for proper SQL conversion, using str()")
        return str(data)


def convertContainerElementsToSQLite(data: Union[Mapping, Sequence, None]) -> Union[Mapping, Sequence]:
    """Convert each element of a container to SQL-compatible types.

    Recursively converts all elements in a mapping or sequence to SQL-compatible
    formats using convertToSQLite. This is particularly useful for preparing
    nested data structures for database storage, ensuring that all nested values
    are properly converted regardless of their depth.

    The function creates a new container with converted elements, leaving the
    original data unchanged. For mappings, both keys and values are processed.
    For sequences, only the elements are converted.

    Args:
        data: The container (Mapping or Sequence) to convert, or None. If None,
            returns an empty list.

    Returns:
        Union[Mapping, Sequence]: A new container with all elements converted
        to SQL-compatible types. Returns an empty list if data is None.
        For Mapping inputs, returns a dict with converted values. For Sequence
        inputs, returns a list with converted elements.

    Raises:
        TypeError: If data is not a Mapping, Sequence, or None.

    Example:
        >>> convertContainerElementsToSQLite({"a": 1, "b": True, "c": {"nested": "value"}})
        {'a': 1, 'b': 1, 'c': '{"nested": "value"}'}
        >>> convertContainerElementsToSQLite([1, "hello", True, [1, 2]])
        [1, 'hello', 1, '[1, 2]']
        >>> convertContainerElementsToSQLite(None)
        []
    """
    if data is None:
        return []
    if isinstance(data, Mapping):
        return {key: convertToSQLite(value) for key, value in data.items()}
    elif isinstance(data, Sequence):
        return [convertToSQLite(value) for value in data]
    else:
        raise TypeError(f"Unsupported type {type(data)} for SQL converting")
