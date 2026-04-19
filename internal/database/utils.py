"""
Database wrapper for the Telegram bot.
This wrapper provides an abstraction layer that can be easily replaced
with other database backends in the future.
"""

import datetime
import logging

import dateutil

logger = logging.getLogger(__name__)

DEFAULT_THREAD_ID: int = 0


def sqlToDatetime(val: bytes | str) -> datetime.datetime:
    if isinstance(val, bytes):
        valStr = val.decode("utf-8")
    else:
        valStr = val
    ret = dateutil.parser.parse(valStr)
    # logger.debug(f"Converted {valStr} to {repr(ret)}")
    return ret
    # return datetime.datetime.strptime(valStr, '%Y-%m-%d %H:%M:%S')


def sqlToBoolean(val: bytes) -> bool:
    # logger.debug(f"Converting {val} (int: {int(val)}, {int(val[0])}) to {bool(int(val[0]))}")
    if len(val) == 0:
        return False
    elif len(val) == 1:
        return bool(int(val))
    else:
        raise ValueError(f"Invalid boolean value: {val}")


def datetimeToSql(val: datetime.datetime, stripTimezone: bool = True) -> str:
    """Adapt datetime.datetime to SQLite format string for sqlite3, dood!"""
    if stripTimezone:
        # Use SQLite's datetime format (YYYY-MM-DD HH:MM:SS) for consistency with CURRENT_TIMESTAMP
        # Strip microseconds to match SQLite's CURRENT_TIMESTAMP format exactly
        return val.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    else:
        return val.replace(microsecond=0).isoformat(timespec="seconds")


# # Register converters for reading from database
# sqlite3.register_converter("timestamp", convert_timestamp)
# sqlite3.register_converter("boolean", convert_boolean)

# # Register adapters for writing to database (Python 3.12+ requirement)
# sqlite3.register_adapter(datetime.datetime, adapt_datetime)
