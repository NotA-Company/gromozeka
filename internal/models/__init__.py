"""
Internal Models Package

This package contains shared models and enums used across multiple modules
to avoid circular dependencies.
"""

from .shared_enums import MessageType

__all__ = [
    "MessageType",
]
