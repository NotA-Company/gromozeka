"""
Common utilities for Gromozeka bot.
"""

import datetime
import json
import logging
import os
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from telegram import Message

logger = logging.getLogger(__name__)


def getAgeInSecs(dt: datetime.datetime) -> float:
    """
    Get age in seconds from now.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    nowUtc = datetime.datetime.now(datetime.timezone.utc)

    return (nowUtc - dt).total_seconds()


def parseDelay(delayStr: str) -> int:
    """
    Parse delay string to integer.

    Args:
        delayStr: String in one of formats:
            1. `DDdHHhMMmSSs` (e.g., "1d2h30m15s") - each section is optional but at least one must be present
            2. `HH:MM[:SS]` (e.g., "2:30" or "2:30:15")

    Returns:
        Total delay in seconds as integer.

    Raises:
        ValueError: If the string doesn't match any supported format.
    """
    # Format 1: DDdHHhMMmSSs (e.g., "1d2h30m15s") - each section is optional but at least one must be present
    if any(c in delayStr for c in ["d", "h", "m", "s"]):
        try:
            total_seconds = 0
            remaining = delayStr

            # Extract days
            if "d" in remaining:
                d_index = remaining.index("d")
                days = int(remaining[:d_index])
                total_seconds += days * 24 * 3600
                remaining = remaining[d_index + 1 :]

            # Extract hours
            if "h" in remaining:
                h_index = remaining.index("h")
                hours = int(remaining[:h_index])
                total_seconds += hours * 3600
                remaining = remaining[h_index + 1 :]

            # Extract minutes
            if "m" in remaining:
                m_index = remaining.index("m")
                minutes = int(remaining[:m_index])
                total_seconds += minutes * 60
                remaining = remaining[m_index + 1 :]

            # Extract seconds
            if "s" in remaining:
                s_index = remaining.index("s")
                seconds = int(remaining[:s_index])
                total_seconds += seconds
                remaining = remaining[s_index + 1 :]

            # If we processed the entire string and have at least one component, return the result
            if remaining == "":
                return total_seconds

        except (ValueError, IndexError):
            pass  # Will try next format

    # Format 2: HH:MM[:SS] (e.g., "2:30" or "2:30:15")
    time_parts = delayStr.split(":")
    if 2 <= len(time_parts) <= 3:
        try:
            hours = int(time_parts[0])
            minutes = int(time_parts[1])
            seconds = int(time_parts[2]) if len(time_parts) == 3 else 0

            # Validate ranges
            if 0 <= minutes < 60 and 0 <= seconds < 60:
                return hours * 3600 + minutes * 60 + seconds

        except ValueError:
            pass  # Will raise ValueError at end

    raise ValueError(f"Invalid delay format: {delayStr}. Expected formats: '[DDd][HHh][MMm][SSs]' or 'HH:MM[:SS]'")


def jsonDumps(data: Any, compact: Optional[bool] = None, **kwargs) -> str:
    dumpKwargs = {
        "ensure_ascii": False,
        "default": str,
        "sort_keys": True,
    }

    if compact is None:
        # If indent is passed, then user want pretty-printed JSON,
        #  no need to use compact separators
        compact = "indent" not in kwargs

    if compact:
        dumpKwargs["separators"] = (",", ":")
    dumpKwargs.update(kwargs)
    return json.dumps(data, **dumpKwargs)


def packDict(
    data: Dict[str | int, str | int | float | bool | None],
    kvSeparator: str = ":",
    valuesSeparator: str = ",",
    sortKeys: bool = True,
) -> str:
    """
    Pack dictionary into string representation.

    Args:
        data: Dictionary to pack
        kvSeparator: Separator between key and value (default ":")
        valuesSeparator: Separator between key-value pairs (default ",")
        sortKeys: Whether to sort keys (default True)

    Returns:
        String representation of the dictionary

    Note:
        Type information is lost during packing. When unpacking, the function
        makes a best guess at the original types. Strings that consist only of
        digits will be converted to integers, strings with decimal points will
        be converted to floats, and "true"/"false" (case insensitive) will be
        converted to booleans.
    """
    if not data:
        return ""

    pairs = []
    keys = data.keys()
    if sortKeys:
        keys = sorted(keys)
    for key in keys:
        value = data[key]
        if value is None:
            value = ""
        pairs.append(f"{key}{kvSeparator}{value}")

    return valuesSeparator.join(pairs)


def unpackDict(
    data: str,
    kvSeparator: str = ":",
    valuesSeparator: str = ",",
) -> Dict[str | int, str | int | float | bool | None]:
    """
    Unpack string representation back to dictionary.

    Args:
        data: String representation of dictionary
        kvSeparator: Separator between key and value (default ":")
        valuesSeparator: Separator between key-value pairs (default ",")

    Returns:
        Dictionary reconstructed from string

    Note:
        Type information is lost during packing. This function makes a best guess
        at the original types. Strings that consist only of digits will be converted
        to integers, strings with decimal points will be converted to floats, and
        "true"/"false" (case insensitive) will be converted to booleans.
    """
    if not data:
        return {}

    result = {}
    pairs = data.split(valuesSeparator)

    for pair in pairs:
        if kvSeparator in pair:
            key, value = pair.split(kvSeparator, 1)

            # Try to convert key to int if possible
            if key.isdigit():
                key = int(key)

            # Try to convert value to appropriate type
            # Only convert to boolean if it's exactly "true" or "false" (case insensitive)
            if value == "":
                value = None
            elif value.lower() == "true":
                value = True
            elif value.lower() == "false":
                value = False
            # Only convert to float if it contains a decimal point
            elif "." in value and value.replace(".", "").isdigit():
                value = float(value)
            # Only convert to int if it's all digits and not a float
            # If it has leading zero, then do not convert to int
            elif all(
                [
                    value.isdigit() or (value[0] == "-" and value[1:].isdigit()),
                    value[0] != "0" or len(value) == 1,
                ]
            ):
                value = int(value)
            # Otherwise keep as string

            result[key] = value

    return result


def dumpMessage(message: "Message") -> str:
    """
    Dump a Telegram Message object to string using original __repr__, dood!

    When reply_to_message is present, replaces it with a compact representation
    showing only: message_id, user_id, chat_id, and first 10 chars of text (if any).
    All other fields (entities, files, etc.) are preserved from the original repr.

    Args:
        message: Telegram Message object to dump

    Returns:
        String representation of the message with compact reply_to_message

    Example:
        >>> dumpMessage(message)
        'Message(message_id=123, ..., reply_to_message={message_id=122, user_id=111, chat_id=456, text="Hi there!"})'
    """
    # Get the original repr
    originalRepr = repr(message)

    # If there's no reply_to_message, just return the original
    if not message.reply_to_message:
        return originalRepr

    # Build compact representation of reply_to_message
    replyParts = []
    replyMsg = message.reply_to_message

    replyParts.append(f"message_id={replyMsg.message_id}")

    if replyMsg.from_user:
        replyParts.append(f"from_user={replyMsg.from_user}")

    if replyMsg.chat:
        replyParts.append(f"chatId={replyMsg.chat.id}")

    if replyMsg.text:
        textPreview = replyMsg.text[:10] + "..." if len(replyMsg.text) > 10 else replyMsg.text
        replyParts.append(f"text={textPreview!r}")

    compactReply = f"{{{', '.join(replyParts)}}}"

    # Get the full repr of reply_to_message to find and replace it
    replyRepr = repr(replyMsg)

    # Replace the full reply_to_message repr with compact version
    modifiedRepr = originalRepr.replace(f"reply_to_message={replyRepr}", f"reply_to_message={compactReply}")

    return modifiedRepr


def load_dotenv(path: str = ".env", populateEnv: bool = True) -> Dict[str, str]:
    """
    Simple dotenv file loader.
    Just read file line by line and put key-value pairs into dictionary.

    Args:
        path: Path to .env file (default ".env")
        populateEnv: Whether to populate environment variables (default True)

    Returns:
        Dictionary of key-value pairs from .env file
    """
    ret: Dict[str, str] = {}
    with open(path, "rt") as f:
        for line in f:
            splitted_line = line.split("=")
            if len(splitted_line) == 2:
                key, value = splitted_line
                ret[key.strip()] = value.strip().strip('"')

    if populateEnv:
        for k, v in ret.items():
            os.putenv(k, v)
    return ret
