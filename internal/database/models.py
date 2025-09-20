"""
Different DB-related models
"""
from enum import StrEnum

class MediaStatus(StrEnum):
    """
    Enum for media status.
    """

    NEW = 'new'
    PENDING = 'pending'
    COMPLETE = 'complete'
    FAILED = 'failed'