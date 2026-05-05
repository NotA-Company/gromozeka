"""Database migrations module.

This module provides a comprehensive migration system for managing database schema
changes in the Gromozeka project. It enables version-controlled database schema
evolution with support for applying and rolling back migrations.

Key Components:
    BaseMigration: Abstract base class that all migrations must inherit from.
        Defines the interface with up() and down() methods for applying and
        rolling back schema changes.

    MigrationManager: Manages the migration lifecycle including tracking current
        version, discovering available migrations, executing migrations in order,
        handling failures, and supporting rollback operations.

    MigrationError: Exception raised when migration operations fail.

Usage Example:
    .. code-block:: python

        from internal.database.migrations import MigrationManager, BaseMigration
        from internal.database.providers import BaseSQLProvider

        # Create a custom migration
        class CreateUsersTable(BaseMigration):
            version = 1
            description = "Create users table"

            async def up(self, sqlProvider: BaseSQLProvider) -> None:
                await sqlProvider.execute('''
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL
                    )
                ''')

            async def down(self, sqlProvider: BaseSQLProvider) -> None:
                await sqlProvider.execute('DROP TABLE users')

        # Register and run migrations
        manager = MigrationManager()
        manager.registerMigrations([CreateUsersTable])
        await manager.migrate(sqlProvider=provider)

Migration Discovery:
    The system supports automatic migration discovery from the versions package.
    Migrations are automatically loaded and sorted by version number.

Version Tracking:
    Migration state is tracked in the settings table using the following keys:
    - db-migration-version: Current migration version
    - db-migration-last-run: Timestamp of last migration run
"""

from .base import BaseMigration
from .manager import MigrationError, MigrationManager

__all__ = [
    "BaseMigration",
    "MigrationManager",
    "MigrationError",
]
