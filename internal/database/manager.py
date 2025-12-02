"""Database manager for Gromozeka bot with configuration and wrapper initialization."""

import logging
from typing import Any, Dict

from .wrapper import DatabaseWrapper

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database initialization and configuration.

    Initializes DatabaseWrapper with provided configuration and handles database setup.
    """

    __slots__ = ("config", "db")

    def __init__(self, config: Dict[str, Any]):
        """Initialize DatabaseManager with configuration.

        Args:
            config: Database configuration dict
        """
        self.config = config
        self.db = DatabaseWrapper(config=self.config)
        logger.info(f"Database initialized: {self.config}")

    def getDatabase(self) -> DatabaseWrapper:
        """Get the database wrapper instance.

        Returns:
            DatabaseWrapper instance for database operations
        """
        return self.db
