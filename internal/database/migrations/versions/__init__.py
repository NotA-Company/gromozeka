"""
Migration versions package, dood!

This package provides automatic migration discovery functionality.
"""

import logging
import os
import re
from typing import List, Optional, Type
from pathlib import Path

from ..base import BaseMigration

logger = logging.getLogger(__name__)


def discoverMigrations() -> List[Type[BaseMigration]]:
    """
    Discover all migrations in versions directory, dood!
    
    Returns:
        List of migration classes sorted by version number
    """
    migrations = []
    versionsDir = Path(__file__).parent
    
    # Find all migration files
    migrationFiles = [
        f for f in os.listdir(versionsDir)
        if re.match(r"migration_\d+_.+\.py", f) and f != "__init__.py"
    ]
    
    # Sort by version number
    migrationFiles.sort(key=lambda f: int(re.match(r"migration_(\d+)_", f).group(1)))  # pyright: ignore[reportOptionalMemberAccess]
    
    for filename in migrationFiles:
        migrationClass = _importMigrationModule(filename)
        if migrationClass:
            migrations.append(migrationClass)
    
    logger.info(f"Discovered {len(migrations)} migrations, dood!")
    return migrations


def _importMigrationModule(filename: str) -> Optional[Type[BaseMigration]]:
    """
    Import a single migration module and return its class, dood!
    
    Args:
        filename: Migration filename (e.g., "migration_001_initial_schema.py")
        
    Returns:
        Migration class or None if import failed
    """
    try:
        # Remove .py extension
        moduleName = filename[:-3]
        
        # Import the module
        import importlib
        module = importlib.import_module(f".{moduleName}", package=__name__)
        
        # Check if getMigration function exists
        if not hasattr(module, "getMigration"):
            logger.warning(f"Migration {filename} missing getMigration() function, dood!")
            return None
        
        # Get the migration class
        migrationClass = module.getMigration()
        
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
