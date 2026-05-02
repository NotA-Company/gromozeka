"""
Migration manager for handling database migrations.

This module provides functionality to manage database schema migrations,
including tracking current version, discovering available migrations,
executing migrations in order, handling failures, and supporting rollback operations.
"""

import logging
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
    """Exception raised when migration fails."""

    pass


class MigrationManager:
    """
    Manages database migrations.

    Responsibilities:
    - Track current migration version in settings table
    - Discover available migrations
    - Execute migrations in order
    - Handle migration failures
    - Support rollback operations
    """

    __slots__ = ("migrations",)

    def __init__(self):
        """Initialize migration manager."""
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
        """
        Load migrations automatically from versions package.

        This replaces the need for manual registration by discovering
        all migration classes from the versions module.
        """
        from .versions import DISCOVERED_MIGRATIONS

        self.registerMigrations(DISCOVERED_MIGRATIONS)
        logger.info(f"Auto-loaded {len(DISCOVERED_MIGRATIONS)} migrations")

    async def setSetting(self, key: str, value: str, *, sqlProvider: BaseSQLProvider) -> None:
        """
        Store a key-value pair in the settings table.

        Args:
            key: Setting key to store
            value: Setting value to store
            sqlProvider: SQL provider instance for database operations
        """
        currentTimestamp = getCurrentTimestamp()
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
        """
        Retrieve a value from the settings table.

        Args:
            key: Setting key to retrieve
            default: Default value to return if key not found
            sqlProvider: SQL provider instance for database operations

        Returns:
            Setting value if found, otherwise the default value
        """
        result = await sqlProvider.executeFetchOne(
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
        """
        Get current migration version from settings table.

        Args:
            sqlProvider: SQL provider instance for database operations

        Returns:
            Current migration version (0 if no migrations have been run)
        """
        try:
            versionStr = await self.getSetting(MIGRATION_VERSION_KEY, "0", sqlProvider=sqlProvider)
            return int(versionStr) if versionStr else 0
        except Exception as e:
            logger.error(f"Failed to get current migration version for {sqlProvider}: {e}")
            return 0

    async def _setVersion(self, version: int, *, sqlProvider: BaseSQLProvider) -> None:
        """
        Update migration version in settings table.

        Args:
            version: New migration version number
            sqlProvider: SQL provider instance for database operations
        """
        await self.setSetting(MIGRATION_VERSION_KEY, str(version), sqlProvider=sqlProvider)
        await self.setSetting(MIGRATION_LAST_RUN_KEY, getCurrentTimestamp().isoformat(), sqlProvider=sqlProvider)
        logger.info(f"Updated migration in {sqlProvider} version to {version}")

    def getAvailableMigrations(self) -> List[Type[BaseMigration]]:
        """
        Get list of all available migrations.

        Returns:
            List of migration classes sorted by version
        """
        return self.migrations

    async def getPendingMigrations(self, *, sqlProvider: BaseSQLProvider) -> List[Type[BaseMigration]]:
        """
        Get list of pending migrations.

        Args:
            sqlProvider: SQL provider instance for database operations

        Returns:
            List of migration classes that haven't been applied yet
        """
        currentVersion = await self.getCurrentVersion(sqlProvider=sqlProvider)
        return [m for m in self.migrations if m.version > currentVersion]

    async def migrate(self, targetVersion: Optional[int] = None, *, sqlProvider: BaseSQLProvider) -> None:
        """
        Run migrations up to target version.

        Args:
            targetVersion: Target version to migrate to (None = latest available)
            sqlProvider: SQL provider instance for database operations

        Raises:
            MigrationError: If migration fails or target version is invalid
        """
        currentVersion = await self.getCurrentVersion(sqlProvider=sqlProvider)
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
        pendingMigrations = [m for m in self.migrations if currentVersion < m.version <= targetVersion]

        if not pendingMigrations:
            logger.info("No pending migrations")
            return

        logger.info(f"Running {len(pendingMigrations)} migrations")

        # Run each migration
        for migrationClass in pendingMigrations:
            migration = migrationClass()
            logger.info(f"Applying migration {migration.version}: {migration.description}")

            try:
                startTime = getCurrentTimestamp()
                await migration.up(sqlProvider)
                duration = (getCurrentTimestamp() - startTime).total_seconds()

                await self._setVersion(migration.version, sqlProvider=sqlProvider)
                logger.info(f"Migration {migration.version} completed in {duration:.2f}s")
            except Exception as e:
                logger.error(f"Migration {migration.version} failed: {e}")
                logger.exception(e)
                raise MigrationError(f"Failed to apply migration {migration.version}") from e

        logger.info("All migrations completed successfully")

    async def rollback(self, steps: int = 1, *, sqlProvider: BaseSQLProvider) -> None:
        """
        Rollback N migrations.

        Args:
            steps: Number of migrations to rollback
            sqlProvider: SQL provider instance for database operations

        Raises:
            MigrationError: If rollback fails
        """
        currentVersion = await self.getCurrentVersion(sqlProvider=sqlProvider)

        if currentVersion == 0:
            logger.info("No migrations to rollback")
            return

        # Get migrations to rollback
        migrationsToRollback = [m for m in reversed(self.migrations) if m.version <= currentVersion][:steps]

        if not migrationsToRollback:
            logger.info("No migrations to rollback")
            return

        logger.info(f"Rolling back {len(migrationsToRollback)} migrations")

        # Rollback each migration
        for migrationClass in migrationsToRollback:
            migration = migrationClass()
            logger.info(f"Rolling back migration {migration.version}: {migration.description}")

            try:
                startTime = getCurrentTimestamp()
                await migration.down(sqlProvider)
                duration = (getCurrentTimestamp() - startTime).total_seconds()

                # Set version to previous migration
                newVersion = migration.version - 1
                await self._setVersion(newVersion, sqlProvider=sqlProvider)
                logger.info(f"Migration {migration.version} rolled back in {duration:.2f}s")
            except Exception as e:
                logger.error(f"Rollback of migration {migration.version} failed: {e}")
                logger.exception(e)
                raise MigrationError(f"Failed to rollback migration {migration.version}") from e

        logger.info("Rollback completed successfully")

    async def getStatus(self, *, sqlProvider: BaseSQLProvider) -> dict:
        """
        Get migration status information.

        Args:
            sqlProvider: SQL provider instance for database operations

        Returns:
            Dictionary containing:
                - current_version: Current migration version
                - latest_version: Latest available migration version
                - pending_count: Number of pending migrations
                - total_migrations: Total number of registered migrations
                - last_run: Timestamp of last migration run
        """
        currentVersion = await self.getCurrentVersion(sqlProvider=sqlProvider)
        pendingMigrations = await self.getPendingMigrations(sqlProvider=sqlProvider)

        return {
            "current_version": currentVersion,
            "latest_version": self.migrations[-1].version if self.migrations else 0,
            "pending_count": len(pendingMigrations),
            "total_migrations": len(self.migrations),
            "last_run": await self.getSetting("db_migration_last_run", sqlProvider=sqlProvider),
        }
