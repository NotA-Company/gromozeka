"""
Common utilities for Gromozeka bot.
"""
import datetime
import logging
from typing import Union

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
    if any(c in delayStr for c in ['d', 'h', 'm', 's']):
        try:
            total_seconds = 0
            remaining = delayStr

            # Extract days
            if 'd' in remaining:
                d_index = remaining.index('d')
                days = int(remaining[:d_index])
                total_seconds += days * 24 * 3600
                remaining = remaining[d_index + 1:]

            # Extract hours
            if 'h' in remaining:
                h_index = remaining.index('h')
                hours = int(remaining[:h_index])
                total_seconds += hours * 3600
                remaining = remaining[h_index + 1:]

            # Extract minutes
            if 'm' in remaining:
                m_index = remaining.index('m')
                minutes = int(remaining[:m_index])
                total_seconds += minutes * 60
                remaining = remaining[m_index + 1:]

            # Extract seconds
            if 's' in remaining:
                s_index = remaining.index('s')
                seconds = int(remaining[:s_index])
                total_seconds += seconds
                remaining = remaining[s_index + 1:]

            # If we processed the entire string and have at least one component, return the result
            if remaining == '':
                return total_seconds

        except (ValueError, IndexError):
            pass  # Will try next format

    # Format 2: HH:MM[:SS] (e.g., "2:30" or "2:30:15")
    time_parts = delayStr.split(':')
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