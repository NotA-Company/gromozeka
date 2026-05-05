"""Internal Models Package.

This package contains shared models and enums used across multiple modules
to avoid circular dependencies. It serves as a central location for common
data structures that are needed by different parts of the application.

The package includes:
- Shared enums: Common enumeration types used across the application
- Type definitions: Common type aliases for type hints

Example:
    >>> from internal.models import MessageType, MessageIdType
    >>> msg_type = MessageType.TEXT
    >>> msg_id: MessageIdType = 123
"""

from .shared_enums import MessageType
from .types import MessageIdType

__all__ = [
    # Shared enums
    "MessageType",
    # Types
    "MessageIdType",
]
