"""
Internal Models Package

This package contains shared models and enums used across multiple modules
to avoid circular dependencies.
"""

from .shared_enums import MessageType
from .types import MessageIdType

__all__ = [
    # Shared enums
    "MessageType",
    # Types
    "MessageIdType",
]
