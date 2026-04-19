"""
Migration manager for handling database migrations, dood!
"""

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import List, Optional, Type

from ..providers import BaseSQLProvider, FetchType
from .base import BaseMigration

logger = logging.getLogger(__name__)

MIGRATION_VERSION_KEY = "db-migration-version"
MIGRATION_LAST_RUN_KEY = "db-migration-last-run"
SETTINGS_TABLE = "settings"


class MigrationError(Exception):
    """Exception raised when migration fails, dood!"""

    pass


class MigrationManager:
    """
    Manages database migrations, dood!

    Responsibilities:
    - Track current migration version in settings table
    - Discover available migrations
    - Execute migrations in order
    - Handle migration failures
    - Support rollback operations
    """

    # TODO: Add slots

    def __init__(self):
        """
        Initialize migration manager, dood!

        Args:
            db: DatabaseWrapper instance
        """
        self.migrations: List[Type[BaseMigration]] = []

    def registerMigrations(self, migrations: List[Type[BaseMigration]]) -> None:
        """
        Register available migrations, dood!

        Args:
            migrations: List of migration classes
        """
        # Validate no duplicate versions
        versions = [m.version for m in migrations]
        if len(versions) != len(set(versions)):
            raise MigrationError("Duplicate migration versions detected, dood!")

        # Sort by version
        self.migrations = sorted(migrations, key=lambda m: m.version)
        logger.debug(f"Registered {len(self.migrations)} migrations, dood!")

    def loadMigrationsFromVersions(self) -> None:
        """
        Load migrations automatically from versions package, dood!

        This replaces the need for manual registration.
        """
        from .versions import DISCOVERED_MIGRATIONS

        self.registerMigrations(DISCOVERED_MIGRATIONS)
        logger.info(f"Auto-loaded {len(DISCOVERED_MIGRATIONS)} migrations, dood!")

    async def setSetting(self, key: str, value: str, *, sqlProvider: BaseSQLProvider) -> None:
        await sqlProvider.execute(
            f"""
                    INSERT OR REPLACE INTO {SETTINGS_TABLE}
                    (key, value, updated_at)
                    VALUES (:key, :value, CURRENT_TIMESTAMP)
                """,
            {
                "key": key,
                "value": value,
            },
        )

    async def getSetting(
        self, key: str, default: Optional[str] = None, *, sqlProvider: BaseSQLProvider
    ) -> Optional[str]:
        result = await sqlProvider.execute(
            f"""
                    SELECT value FROM {SETTINGS_TABLE}
                    WHERE key = :key
                """,
            {
                "key": key,
            },
            fetchType=FetchType.FETCH_ONE,
        )
        if isinstance(result, Sequence):
            result = result[0]
        if not isinstance(result, Mapping):
            return default

        return result["value"] if result else default

    async def getCurrentVersion(self, *, sqlProvider: BaseSQLProvider) -> int:
        """
        Get current migration version from settings table, dood!

        Returns:
            Current version (0 if no migrations run)
        """
        try:
            versionStr = await self.getSetting(MIGRATION_VERSION_KEY, "0", sqlProvider=sqlProvider)
            return int(versionStr) if versionStr else 0
        except Exception as e:
            logger.error(f"Failed to get current migration version for {sqlProvider}: {e}")
            return 0

    async def _setVersion(self, version: int, *, sqlProvider: BaseSQLProvider) -> None:
        """
        Update migration version in settings table, dood!

        Args:
            version: New version number
        """
        await self.setSetting(MIGRATION_VERSION_KEY, str(version), sqlProvider=sqlProvider)
        await self.setSetting(MIGRATION_LAST_RUN_KEY, datetime.now().isoformat(), sqlProvider=sqlProvider)
        logger.info(f"Updated migration in {sqlProvider} version to {version}, dood!")

    def getAvailableMigrations(self) -> List[Type[BaseMigration]]:
        """
        Get list of all available migrations, dood!

        Returns:
            List of migration classes sorted by version
        """
        return self.migrations

    async def getPendingMigrations(self, *, sqlProvider: BaseSQLProvider) -> List[Type[BaseMigration]]:
        """
        Get list of pending migrations, dood!

        Returns:
            List of migration classes that haven't been applied yet
        """
        currentVersion = await self.getCurrentVersion(sqlProvider=sqlProvider)
        return [m for m in self.migrations if m.version > currentVersion]

    async def migrate(self, targetVersion: Optional[int] = None, *, sqlProvider: BaseSQLProvider) -> None:
        """
        Run migrations up to target version, dood!

        Args:
            targetVersion: Target version to migrate to (None = latest)

        Raises:
            MigrationError: If migration fails
        """
        currentVersion = await self.getCurrentVersion(sqlProvider=sqlProvider)
        logger.info(f"Current migration version: {currentVersion}, dood!")

        # Determine target version
        if targetVersion is None:
            if not self.migrations:
                logger.info("No migrations to run, dood!")
                return
            targetVersion = self.migrations[-1].version

        logger.info(f"Target migration version: {targetVersion}, dood!")

        # Validate target version
        if targetVersion == currentVersion:
            logger.info("Already at target version, dood!")
            return

        # Validate target version
        if targetVersion > self.migrations[-1].version:
            raise MigrationError(f"Target version {targetVersion} is higher than latest version, dood!")

        # Get migrations to run
        pendingMigrations = [m for m in self.migrations if currentVersion < m.version <= targetVersion]

        if not pendingMigrations:
            logger.info("No pending migrations, dood!")
            return

        logger.info(f"Running {len(pendingMigrations)} migrations, dood!")

        # Run each migration
        for migrationClass in pendingMigrations:
            migration = migrationClass()
            logger.info(f"Applying migration {migration.version}: {migration.description}, dood!")

            try:
                startTime = datetime.now()
                await migration.up(sqlProvider)
                duration = (datetime.now() - startTime).total_seconds()

                await self._setVersion(migration.version, sqlProvider=sqlProvider)
                logger.info(f"Migration {migration.version} completed in {duration:.2f}s, dood!")
            except Exception as e:
                logger.error(f"Migration {migration.version} failed: {e}, dood!")
                logger.exception(e)
                raise MigrationError(f"Failed to apply migration {migration.version}, dood!") from e

        logger.info("All migrations completed successfully, dood!")

    async def rollback(self, steps: int = 1, *, sqlProvider: BaseSQLProvider) -> None:
        """
        Rollback N migrations, dood!

        Args:
            steps: Number of migrations to rollback

        Raises:
            MigrationError: If rollback fails
        """
        currentVersion = await self.getCurrentVersion(sqlProvider=sqlProvider)

        if currentVersion == 0:
            logger.info("No migrations to rollback, dood!")
            return

        # Get migrations to rollback
        migrationsToRollback = [m for m in reversed(self.migrations) if m.version <= currentVersion][:steps]

        if not migrationsToRollback:
            logger.info("No migrations to rollback, dood!")
            return

        logger.info(f"Rolling back {len(migrationsToRollback)} migrations, dood!")

        # Rollback each migration
        for migrationClass in migrationsToRollback:
            migration = migrationClass()
            logger.info(f"Rolling back migration {migration.version}: {migration.description}, dood!")

            try:
                startTime = datetime.now()
                await migration.down(sqlProvider)
                duration = (datetime.now() - startTime).total_seconds()

                # Set version to previous migration
                newVersion = migration.version - 1
                await self._setVersion(newVersion, sqlProvider=sqlProvider)
                logger.info(f"Migration {migration.version} rolled back in {duration:.2f}s, dood!")
            except Exception as e:
                logger.error(f"Rollback of migration {migration.version} failed: {e}, dood!")
                logger.exception(e)
                raise MigrationError(f"Failed to rollback migration {migration.version}, dood!") from e

        logger.info("Rollback completed successfully, dood!")

    async def getStatus(self, *, sqlProvider: BaseSQLProvider) -> dict:
        """
        Get migration status information, dood!

        Returns:
            Dictionary with migration status
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
