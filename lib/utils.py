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