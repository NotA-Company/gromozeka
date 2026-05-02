"""
Utility functions for database providers.

This module provides helper functions for converting Python data types to
SQL-compatible formats, suitable for SQLite, MySQL, PostgreSQL, and similar database backends.
"""

import datetime
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Union

import lib.utils as libUtils

logger = logging.getLogger(__name__)
"""Module logger instance for database provider utilities."""


def convertToSQLite(data: Any) -> Union[str, int, float, None]:
    """
    Convert data to a SQL-compatible type.

    Converts various Python data types to formats suitable for SQL storage across
    multiple RDBMS (SQLite, MySQL, PostgreSQL):
    - str, int, float: returned as-is
    - dict, list, Mapping, Sequence: converted to JSON string
    - bool: converted to int (0 or 1)
    - datetime.datetime: converted to ISO format string or formatted string for naive datetimes
    - Other types: converted to string with a warning logged

    Args:
        data: The data to convert to SQL-compatible format.

    Returns:
        Union[str, int, float, None]: The converted data in SQL-compatible format,
        or None if data is None.
    """
    if data is None:
        return None
    elif isinstance(data, (str, int, float)):
        return data
    elif isinstance(data, (dict, list, Mapping, Sequence)):
        return libUtils.jsonDumps(data)
    elif isinstance(data, bool):
        return int(data)
    elif isinstance(data, datetime.datetime):
        if data.tzinfo is None:
            return data.strftime("%Y-%m-%d %H:%M:%S")
        return data.isoformat()
    else:
        logger.warning(f"Unsupported type {type(data)} for proper SQL conversion, using str()")
        return str(data)


def convertContainerElementsToSQLite(data: Union[Mapping, Sequence, None]) -> Union[Mapping, Sequence]:
    """
    Convert each element of a container to SQL-compatible types.

    Recursively converts all elements in a mapping or sequence to SQL-compatible
    formats using convertToSQLite. Useful for preparing nested data structures
    for database storage.

    Args:
        data: The container (Mapping or Sequence) to convert, or None.

    Returns:
        Union[Mapping, Sequence]: A new container with all elements converted
        to SQL-compatible types. Returns an empty list if data is None.

    Raises:
        TypeError: If data is not a Mapping, Sequence, or None.
    """
    if data is None:
        return []
    if isinstance(data, Mapping):
        return {key: convertToSQLite(value) for key, value in data.items()}
    elif isinstance(data, Sequence):
        return [convertToSQLite(value) for value in data]
    else:
        raise TypeError(f"Unsupported type {type(data)} for SQL converting")
