"""
Database management for Gromozeka bot.
"""

import logging
import sys
from typing import Dict, Any

from .wrapper import DatabaseWrapper

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database initialization and configuration for Gromozeka bot."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize DatabaseManager with database configuration."""
        self.config = config
        self.db = self._init_database()

    def _init_database(self) -> DatabaseWrapper:
        """Initialize database connection."""
        db_path = self.config.get("path", "bot_data.db")
        max_connections = self.config.get("max_connections", 5)
        timeout = self.config.get("timeout", 30)

        try:
            db = DatabaseWrapper(db_path, max_connections, timeout)
            logger.info(f"Database initialized: {db_path}")
            return db
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            sys.exit(1)

    def get_database(self) -> DatabaseWrapper:
        """Get the database wrapper instance."""
        return self.db
