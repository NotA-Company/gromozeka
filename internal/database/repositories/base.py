"""Base repository module for database operations.

This module provides the BaseRepository abstract base class that serves as the
foundation for all repository implementations in the Gromozeka bot database layer.
Repositories are responsible for data access operations and provide a consistent
interface for working with different database providers.
"""

from abc import ABC

from ..manager import DatabaseManager


class BaseRepository(ABC):
    """Abstract base class for database repositories.

    Provides the foundation for all repository implementations, ensuring they
    have access to the DatabaseManager for executing database operations across
    multiple data sources. All concrete repositories should inherit from this
    class and implement their specific data access methods.
    """

    __slots__ = ("manager",)
    """Restricts instance attributes to only 'manager' to prevent dynamic attribute creation."""

    def __init__(self, manager: DatabaseManager):
        """Initialize the repository with a database manager.

        Args:
            manager: DatabaseManager instance for accessing database providers
                    and executing database operations
        """
        self.manager = manager
