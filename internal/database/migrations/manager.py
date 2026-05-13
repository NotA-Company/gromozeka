"""
Migration manager for handling database migrations.

This module provides functionality to manage database schema migrations,
including tracking current version, discovering available migrations,
executing migrations in order, handling failures, and supporting rollback operations.

Key Components:
    - MigrationError: Exception raised when migration operations fail
    - MigrationManager: Main class for managing migration lifecycle

Usage Example:
    .. code-block:: python

        from internal.database.migrations.manager import MigrationManager
        from internal.database.providers import PostgreSQLProvider

        # Create migration manager
        manager = MigrationManager()

        # Register migrations manually or auto-load
        manager.loadMigrationsFromVersions()

        # Run migrations
        provider = PostgreSQLProvider(config)
        await manager.migrate(sqlProvider=provider)

        # Check status
        status = await manager.getStatus(sqlProvider=provider)
        print(f"Current version: {status['current_version']}")
"""

import logging
from datetime import datetime
from typing import List, Optional, Type

from ..providers import BaseSQLProvider
from ..providers.base import ExcludedValue
from ..utils import getCurrentTimestamp
from .base import BaseMigration

logger = logging.getLogger(__name__)

MIGRATION_VERSION_KEY = "db-migration-version"
MIGRATION_LAST_RUN_KEY = "db-migration-last-run"
SETTINGS_TABLE = "settings"


class MigrationError(Exception):
    """Exception raised when migration operations fail.

    This exception is raised when a migration cannot be applied or rolled back,
    typically due to database errors, validation failures, or other runtime issues.
    """

    pass


class MigrationManager:
    """Manages database migrations lifecycle.

    This class provides comprehensive migration management including version tracking,
    migration discovery, execution, rollback, and status reporting. It maintains
    migration state in a settings table and ensures migrations are applied in
    the correct order.

    Attributes:
        migrations: List of registered migration classes sorted by version.

    Responsibilities:
        - Track current migration version in settings table
        - Discover available migrations from versions package
        - Execute migrations in order with error handling
        - Support rollback operations for failed migrations
        - Provide migration status and pending migration information
    """

    __slots__ = ("migrations",)

    def __init__(self) -> None:
        """Initialize migration manager with empty migration list."""
        self.migrations: List[Type[BaseMigration]] = []

    def registerMigrations(self, migrations: List[Type[BaseMigration]]) -> None:
        """
        Register available migrations.

        Args:
            migrations: List of migration classes to register

        Raises:
            MigrationError: If duplicate migration versions are detected
        """
        # Validate no duplicate versions
        versions = [m.version for m in migrations]
        if len(versions) != len(set(versions)):
            raise MigrationError("Duplicate migration versions detected")

        # Sort by version
        self.migrations = sorted(migrations, key=lambda m: m.version)
        logger.debug(f"Registered {len(self.migrations)} migrations")

    def loadMigrationsFromVersions(self) -> None:
        """Load migrations automatically from versions package.

        This method discovers and registers all migration classes from the
        versions module, eliminating the need for manual registration.
        Migrations are automatically sorted by version.

        Raises:
            MigrationError: If duplicate migration versions are detected
                during auto-discovery.
        """
        from .versions import DISCOVERED_MIGRATIONS

        self.registerMigrations(DISCOVERED_MIGRATIONS)
        logger.info(f"Auto-loaded {len(DISCOVERED_MIGRATIONS)} migrations")

    async def setSetting(self, key: str, value: str, *, sqlProvider: BaseSQLProvider) -> None:
        """Store a key-value pair in the settings table.

        This method performs an upsert operation, creating a new setting if it
        doesn't exist or updating an existing one. The operation uses the
        settings table with conflict resolution on the key column.

        Args:
            key: Setting key to store.
            value: Setting value to store.
            sqlProvider: SQL provider instance for database operations.

        Raises:
            Exception: If the database operation fails.
        """
        currentTimestamp: datetime = getCurrentTimestamp()
        await sqlProvider.upsert(
            table=SETTINGS_TABLE,
            values={
                "key": key,
                "value": value,
                "created_at": currentTimestamp,
                "updated_at": currentTimestamp,
            },
            conflictColumns=["key"],
            updateExpressions={
                "value": ExcludedValue(),
                "updated_at": ExcludedValue(),
            },
        )

    async def getSetting(
        self, key: str, default: Optional[str] = None, *, sqlProvider: BaseSQLProvider
    ) -> Optional[str]:
        """Retrieve a value from the settings table.

        Args:
            key: Setting key to retrieve.
            default: Default value to return if key not found. Defaults to None.

        Returns:
            Setting value if found, otherwise the default value.

        Raises:
            Exception: If the database query fails.
        """
        result: Optional[dict] = await sqlProvider.executeFetchOne(
            f"""
                    SELECT value FROM {SETTINGS_TABLE}
                    WHERE key = :key
                """,
            {
                "key": key,
            },
        )

        return result["value"] if result else default

    async def getCurrentVersion(self, *, sqlProvider: BaseSQLProvider) -> int:
        """Get current migration version from settings table.

        Args:
            sqlProvider: SQL provider instance for database operations.

        Returns:
            Current migration version. Returns 0 if no migrations have been run
            or if the version cannot be retrieved.

        Raises:
            Exception: Logged but not raised; returns 0 on error.
        """
        try:
            versionStr: Optional[str] = await self.getSetting(MIGRATION_VERSION_KEY, "0", sqlProvider=sqlProvider)
            return int(versionStr) if versionStr else 0
        except Exception as e:
            logger.error(f"Failed to get current migration version for {sqlProvider}: {e}")
            return 0

    async def _setVersion(self, version: int, *, sqlProvider: BaseSQLProvider) -> None:
        """Update migration version in settings table.

        This private method updates both the migration version and the last run
        timestamp in the settings table.

        Args:
            version: New migration version number.
            sqlProvider: SQL provider instance for database operations.

        Raises:
            Exception: If the database operation fails.
        """
        await self.setSetting(MIGRATION_VERSION_KEY, str(version), sqlProvider=sqlProvider)
        await self.setSetting(MIGRATION_LAST_RUN_KEY, getCurrentTimestamp().isoformat(), sqlProvider=sqlProvider)
        logger.info(f"Updated migration in {sqlProvider} version to {version}")

    def getAvailableMigrations(self) -> List[Type[BaseMigration]]:
        """Get list of all available migrations.

        Returns:
            List of migration classes sorted by version in ascending order.
        """
        return self.migrations

    async def getPendingMigrations(self, *, sqlProvider: BaseSQLProvider) -> List[Type[BaseMigration]]:
        """Get list of pending migrations.

        Args:
            sqlProvider: SQL provider instance for database operations.

        Returns:
            List of migration classes that haven't been applied yet, sorted
            by version in ascending order.
        """
        currentVersion: int = await self.getCurrentVersion(sqlProvider=sqlProvider)
        return [m for m in self.migrations if m.version > currentVersion]

    async def migrate(self, targetVersion: Optional[int] = None, *, sqlProvider: BaseSQLProvider) -> None:
        """Run migrations up to target version.

        This method executes all pending migrations up to the specified target version.
        If no target version is provided, it migrates to the latest available version.
        Each migration is executed in order, and the version is updated after each
        successful migration. If a migration fails, the process stops and raises
        an exception.

        Args:
            targetVersion: Target version to migrate to. If None, migrates to the
                latest available version. Defaults to None.
            sqlProvider: SQL provider instance for database operations.

        Raises:
            MigrationError: If migration fails or target version is invalid.
            Exception: If database operations fail during migration execution.
        """
        currentVersion: int = await self.getCurrentVersion(sqlProvider=sqlProvider)
        logger.info(f"Current migration version: {currentVersion}")

        # Determine target version
        if targetVersion is None:
            if not self.migrations:
                logger.info("No migrations to run")
                return
            targetVersion = self.migrations[-1].version

        logger.info(f"Target migration version: {targetVersion}")

        # Validate target version
        if targetVersion == currentVersion:
            logger.info("Already at target version")
            return

        # Validate target version
        if targetVersion > self.migrations[-1].version:
            raise MigrationError(f"Target version {targetVersion} is higher than latest version")

        # Get migrations to run
        pendingMigrations: List[Type[BaseMigration]] = [
            m for m in self.migrations if currentVersion < m.version <= targetVersion
        ]

        if not pendingMigrations:
            logger.info("No pending migrations")
            return

        logger.info(f"Running {len(pendingMigrations)} migrations")

        # Run each migration
        for migrationClass in pendingMigrations:
            migration: BaseMigration = migrationClass()
            logger.info(f"Applying migration {migration.version}: {migration.description}")

            try:
                startTime: datetime = getCurrentTimestamp()
                await migration.up(sqlProvider)
                duration: float = (getCurrentTimestamp() - startTime).total_seconds()

                await self._setVersion(migration.version, sqlProvider=sqlProvider)
                logger.info(f"Migration {migration.version} completed in {duration:.2f}s")
            except Exception as e:
                logger.error(f"Migration {migration.version} failed: {e}")
                logger.exception(e)
                raise MigrationError(f"Failed to apply migration {migration.version}") from e

        logger.info("All migrations completed successfully")

    async def rollback(self, steps: int = 1, *, sqlProvider: BaseSQLProvider) -> None:
        """Rollback N migrations.

        This method rolls back the specified number of migrations in reverse order.
        Each migration's down() method is called to undo the changes, and the
        version is updated after each successful rollback. If a rollback fails,
        the process stops and raises an exception.

        Args:
            steps: Number of migrations to rollback. Defaults to 1.
            sqlProvider: SQL provider instance for database operations.

        Raises:
            MigrationError: If rollback fails.
            Exception: If database operations fail during rollback execution.
        """
        currentVersion: int = await self.getCurrentVersion(sqlProvider=sqlProvider)

        if currentVersion == 0:
            logger.info("No migrations to rollback")
            return

        # Get migrations to rollback
        migrationsToRollback: List[Type[BaseMigration]] = [
            m for m in reversed(self.migrations) if m.version <= currentVersion
        ][:steps]

        if not migrationsToRollback:
            logger.info("No migrations to rollback")
            return

        logger.info(f"Rolling back {len(migrationsToRollback)} migrations")

        # Rollback each migration
        for migrationClass in migrationsToRollback:
            migration: BaseMigration = migrationClass()
            logger.info(f"Rolling back migration {migration.version}: {migration.description}")

            try:
                startTime: datetime = getCurrentTimestamp()
                await migration.down(sqlProvider)
                duration: float = (getCurrentTimestamp() - startTime).total_seconds()

                # Set version to previous migration
                newVersion: int = migration.version - 1
                await self._setVersion(newVersion, sqlProvider=sqlProvider)
                logger.info(f"Migration {migration.version} rolled back in {duration:.2f}s")
            except Exception as e:
                logger.error(f"Rollback of migration {migration.version} failed: {e}")
                logger.exception(e)
                raise MigrationError(f"Failed to rollback migration {migration.version}") from e

        logger.info("Rollback completed successfully")

    async def getStatus(self, *, sqlProvider: BaseSQLProvider) -> dict:
        """Get migration status information.

        This method provides a comprehensive overview of the current migration state,
        including version information, pending migrations, and execution history.

        Args:
            sqlProvider: SQL provider instance for database operations.

        Returns:
            Dictionary containing migration status information with the following keys:
                - current_version (int): Current migration version.
                - latest_version (int): Latest available migration version.
                - pending_count (int): Number of pending migrations.
                - total_migrations (int): Total number of registered migrations.
                - last_run (Optional[str]): Timestamp of last migration run in ISO format,
                    or None if no migrations have been run.

        Raises:
            Exception: If database operations fail during status retrieval.
        """
        currentVersion: int = await self.getCurrentVersion(sqlProvider=sqlProvider)
        pendingMigrations: List[Type[BaseMigration]] = await self.getPendingMigrations(sqlProvider=sqlProvider)

        return {
            "current_version": currentVersion,
            "latest_version": self.migrations[-1].version if self.migrations else 0,
            "pending_count": len(pendingMigrations),
            "total_migrations": len(self.migrations),
            "last_run": await self.getSetting("db_migration_last_run", sqlProvider=sqlProvider),
        }
