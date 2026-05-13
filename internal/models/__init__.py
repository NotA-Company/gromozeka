"""Internal Models Package.

This package contains shared models and enums used across multiple modules
to avoid circular dependencies. It serves as a central location for common
data structures that are needed by different parts of the application.

The package includes:
- Shared enums: Common enumeration types used across the application
- Type definitions: Common type aliases for type hints
"""

from .shared_enums import MessageType
from .types import MessageId

__all__ = [
    # Shared enums
    "MessageType",
    # Types
    "MessageId",
]
