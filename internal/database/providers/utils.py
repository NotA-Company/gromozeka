"""Utility functions for database providers.

This module provides helper functions for converting Python data types to
SQL-compatible formats, suitable for SQLite, MySQL, PostgreSQL, and similar
database backends. These utilities are used by database provider implementations
to ensure consistent data type handling across different database systems.
"""

import datetime
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Union

import lib.utils as libUtils
from internal.models import MessageId

logger = logging.getLogger(__name__)


def convertToSQLite(data: Any) -> Union[str, int, float, None]:
    """Convert data to a SQL-compatible type.

    Converts various Python data types to formats suitable for SQL storage across
    multiple RDBMS (SQLite, MySQL, PostgreSQL). Handles primitives, containers,
    booleans, datetimes, and None.

    Type conversion rules:
    - str, int, float: returned as-is
    - dict, list, Mapping, Sequence: converted to JSON string
    - bool: converted to int (0 for False, 1 for True)
    - datetime.datetime: converted to ISO format string
    - None: returned as None (SQL NULL)
    - Other types: converted to string with a warning logged

    Args:
        data: The data to convert to SQL-compatible format

    Returns:
        Union[str, int, float, None]: The converted data in SQL-compatible format
    """
    if data is None:
        return None
    elif isinstance(data, MessageId):
        # Exclusive handling for MessageId isn't needed, actually,
        # but this way we'll suppress warning message
        return data.asStr()
    elif isinstance(data, bool):
        return int(data)
    elif isinstance(data, (str, int, float)):
        return data
    elif isinstance(data, (dict, list, tuple, Mapping, Sequence)):
        return libUtils.jsonDumps(data)
    elif isinstance(data, datetime.datetime):
        return data.isoformat()
    else:
        logger.warning(f"Unsupported type {type(data)} for proper SQL conversion, using str()")
        return str(data)


def convertContainerElementsToSQLite(data: Union[Mapping, Sequence, None]) -> Union[Mapping, Sequence]:
    """Convert each element of a container to SQL-compatible types.

    Recursively converts all elements in a mapping or sequence to SQL-compatible
    formats using convertToSQLite. Creates a new container with converted elements,
    leaving the original data unchanged.

    Args:
        data: The container (Mapping or Sequence) to convert, or None

    Returns:
        Union[Mapping, Sequence]: A new container with all elements converted
        to SQL-compatible types. Returns an empty list if data is None.

    Raises:
        TypeError: If data is not a Mapping, Sequence, or None
    """
    if data is None:
        return []
    if isinstance(data, Mapping):
        return {key: convertToSQLite(value) for key, value in data.items()}
    elif isinstance(data, Sequence):
        return [convertToSQLite(value) for value in data]
    else:
        raise TypeError(f"Unsupported type {type(data)} for SQL converting")
