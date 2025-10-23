"""
Migration manager for handling database migrations, dood!
"""

import logging
from typing import TYPE_CHECKING, List, Optional, Type
from datetime import datetime

from .base import BaseMigration

if TYPE_CHECKING:
    from ..wrapper import DatabaseWrapper

logger = logging.getLogger(__name__)

MIGRATION_VERSION_KEY = "db-migration-version"
MIGRATION_LAST_RUN_KEY = "db-migration-last-run"


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

    def __init__(self, db: "DatabaseWrapper"):
        """
        Initialize migration manager, dood!
        
        Args:
            db: DatabaseWrapper instance
        """
        self.db = db
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

    def getCurrentVersion(self) -> int:
        """
        Get current migration version from settings table, dood!
        
        Returns:
            Current version (0 if no migrations run)
        """
        try:
            versionStr = self.db.getSetting(MIGRATION_VERSION_KEY, "0")
            return int(versionStr) if versionStr else 0
        except Exception as e:
            logger.error(f"Failed to get current migration version: {e}")
            return 0

    def _setVersion(self, version: int) -> None:
        """
        Update migration version in settings table, dood!
        
        Args:
            version: New version number
        """
        self.db.setSetting(MIGRATION_VERSION_KEY, str(version))
        self.db.setSetting(MIGRATION_LAST_RUN_KEY, datetime.now().isoformat())
        logger.info(f"Updated migration version to {version}, dood!")

    def getAvailableMigrations(self) -> List[Type[BaseMigration]]:
        """
        Get list of all available migrations, dood!
        
        Returns:
            List of migration classes sorted by version
        """
        return self.migrations

    def getPendingMigrations(self) -> List[Type[BaseMigration]]:
        """
        Get list of pending migrations, dood!
        
        Returns:
            List of migration classes that haven't been applied yet
        """
        currentVersion = self.getCurrentVersion()
        return [m for m in self.migrations if m.version > currentVersion]

    def migrate(self, targetVersion: Optional[int] = None) -> None:
        """
        Run migrations up to target version, dood!
        
        Args:
            targetVersion: Target version to migrate to (None = latest)
        
        Raises:
            MigrationError: If migration fails
        """
        currentVersion = self.getCurrentVersion()
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
            raise MigrationError(
                f"Target version {targetVersion} is higher than latest version, dood!"
            )

        # Get migrations to run
        pendingMigrations = [
            m for m in self.migrations 
            if currentVersion < m.version <= targetVersion
        ]

        if not pendingMigrations:
            logger.info("No pending migrations, dood!")
            return

        logger.info(f"Running {len(pendingMigrations)} migrations, dood!")

        # Run each migration
        for migrationClass in pendingMigrations:
            migration = migrationClass()
            logger.info(
                f"Applying migration {migration.version}: {migration.description}, dood!"
            )
            
            try:
                startTime = datetime.now()
                migration.up(self.db)
                duration = (datetime.now() - startTime).total_seconds()
                
                self._setVersion(migration.version)
                logger.info(
                    f"Migration {migration.version} completed in {duration:.2f}s, dood!"
                )
            except Exception as e:
                logger.error(
                    f"Migration {migration.version} failed: {e}, dood!"
                )
                logger.exception(e)
                raise MigrationError(
                    f"Failed to apply migration {migration.version}, dood!"
                ) from e

        logger.info(f"All migrations completed successfully, dood!")

    def rollback(self, steps: int = 1) -> None:
        """
        Rollback N migrations, dood!
        
        Args:
            steps: Number of migrations to rollback
        
        Raises:
            MigrationError: If rollback fails
        """
        currentVersion = self.getCurrentVersion()
        
        if currentVersion == 0:
            logger.info("No migrations to rollback, dood!")
            return

        # Get migrations to rollback
        migrationsToRollback = [
            m for m in reversed(self.migrations)
            if m.version <= currentVersion
        ][:steps]

        if not migrationsToRollback:
            logger.info("No migrations to rollback, dood!")
            return

        logger.info(f"Rolling back {len(migrationsToRollback)} migrations, dood!")

        # Rollback each migration
        for migrationClass in migrationsToRollback:
            migration = migrationClass()
            logger.info(
                f"Rolling back migration {migration.version}: {migration.description}, dood!"
            )
            
            try:
                startTime = datetime.now()
                migration.down(self.db)
                duration = (datetime.now() - startTime).total_seconds()
                
                # Set version to previous migration
                newVersion = migration.version - 1
                self._setVersion(newVersion)
                logger.info(
                    f"Migration {migration.version} rolled back in {duration:.2f}s, dood!"
                )
            except Exception as e:
                logger.error(
                    f"Rollback of migration {migration.version} failed: {e}, dood!"
                )
                logger.exception(e)
                raise MigrationError(
                    f"Failed to rollback migration {migration.version}, dood!"
                ) from e

        logger.info(f"Rollback completed successfully, dood!")

    def getStatus(self) -> dict:
        """
        Get migration status information, dood!
        
        Returns:
            Dictionary with migration status
        """
        currentVersion = self.getCurrentVersion()
        pendingMigrations = self.getPendingMigrations()
        
        return {
            "current_version": currentVersion,
            "latest_version": self.migrations[-1].version if self.migrations else 0,
            "pending_count": len(pendingMigrations),
            "total_migrations": len(self.migrations),
            "last_run": self.db.getSetting("db_migration_last_run"),
        }