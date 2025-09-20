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
    DONE = 'done'
    FAILED = 'failed'