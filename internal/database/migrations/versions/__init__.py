"""
Migration versions package for database schema migrations.

This package provides automatic migration discovery functionality for the Gromozeka
database layer. It scans the versions directory for migration files, imports them,
and validates that they conform to the BaseMigration interface.

Migration files must follow the naming convention: migration_<version>_<description>.py
where <version> is a numeric identifier and <description> is a brief description.

Each migration module must provide a getMigration() function that returns a class
inheriting from BaseMigration with a version attribute and description attribute.

Attributes:
    DISCOVERED_MIGRATIONS: List of all discovered migration classes sorted by version
        number, automatically populated on module import.
"""

import logging
import os
import re
from pathlib import Path
from typing import List, Optional, Type

from ..base import BaseMigration

logger = logging.getLogger(__name__)


def discoverMigrations() -> List[Type[BaseMigration]]:
    """Discover all migrations in the versions directory.

    Scans the versions directory for migration files matching the pattern
    migration_<version>_<description>.py, imports them, and returns a sorted
    list of valid migration classes.

    Returns:
        List[Type[BaseMigration]]: List of migration classes sorted by version
            number in ascending order.
    """
    migrations: List[Type[BaseMigration]] = []
    versionsDir: Path = Path(__file__).parent

    # Find all migration files
    migrationFiles: List[str] = [
        f for f in os.listdir(versionsDir) if re.match(r"migration_\d+_.+\.py", f) and f != "__init__.py"
    ]

    # Sort by version number
    migrationFiles.sort(
        key=lambda f: int(re.match(r"migration_(\d+)_", f).group(1))  # pyright: ignore[reportOptionalMemberAccess]
    )

    for filename in migrationFiles:
        migrationClass: Optional[Type[BaseMigration]] = _importMigrationModule(filename)
        if migrationClass:
            migrations.append(migrationClass)

    logger.info(f"Discovered {len(migrations)} migrations, dood!")
    return migrations


def _importMigrationModule(filename: str) -> Optional[Type[BaseMigration]]:
    """Import a single migration module and return its class.

    Dynamically imports a migration module by filename, validates that it
    provides a getMigration() function returning a valid BaseMigration subclass,
    and returns the migration class.

    Args:
        filename: Migration filename (e.g., "migration_001_initial_schema.py").

    Returns:
        Optional[Type[BaseMigration]]: The migration class if import and validation
            succeed, None otherwise.
    """
    try:
        # Remove .py extension
        moduleName: str = filename[:-3]

        # Import the module
        import importlib

        module = importlib.import_module(f".{moduleName}", package=__name__)

        # Check if getMigration function exists
        if not hasattr(module, "getMigration"):
            logger.warning(f"Migration {filename} missing getMigration() function, dood!")
            return None

        # Get the migration class
        migrationClass: Type[BaseMigration] = module.getMigration()

        # Validate it's a proper migration class
        if not issubclass(migrationClass, BaseMigration):
            logger.error(f"Migration {filename} getMigration() didn't return BaseMigration subclass, dood!")
            return None

        # Validate version number
        if not hasattr(migrationClass, "version") or not isinstance(migrationClass.version, int):
            logger.error(f"Migration {filename} missing valid version attribute, dood!")
            return None

        logger.debug(f"Loaded migration {migrationClass.version}: {migrationClass.description}, dood!")
        return migrationClass

    except Exception as e:
        logger.error(f"Failed to import migration {filename}: {e}, dood!")
        logger.exception(e)
        return None


# Auto-discover migrations on import
DISCOVERED_MIGRATIONS = discoverMigrations()

__all__ = ["DISCOVERED_MIGRATIONS", "discoverMigrations", "_importMigrationModule"]
