"""
TODO: write docstring
"""

import datetime
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Union

import lib.utils as libUtils

logger = logging.getLogger(__name__)


def convertToSQLite(data: Any) -> Union[str, int, float, None]:
    """
    Convert *data* to a SQL-compatible type.

    Args:
        data: The data to convert.

    Returns:
        The converted data, or ``None`` if *data* is ``None``.
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
        logger.warning(f"Unsupported type {type(data)} for proper SQL conversion, use str()")
        return str(data)


def convertContainerElementsToSQLite(data: Union[Mapping, Sequence, None]) -> Union[Mapping, Sequence]:
    """
    Convert each element of *data* to a SQL-compatible type.

    Args:
        data: The data to convert.

    Returns:
        The converted data, or ``None`` if *data* is ``None``.
    """
    if data is None:
        return []
    if isinstance(data, Mapping):
        return {key: convertToSQLite(value) for key, value in data.items()}
    elif isinstance(data, Sequence):
        return [convertToSQLite(value) for value in data]
    else:
        raise TypeError(f"Unsupported type {type(data)} for SQL converting")
