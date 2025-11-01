"""
Initial schema migration - creates all base tables, dood!

This migration extracts all table creation from the original _initDatabase() method.
"""

from typing import TYPE_CHECKING, Type
from ..base import BaseMigration

if TYPE_CHECKING:
    from ...wrapper import DatabaseWrapper


class Migration005YandexSearchCache(BaseMigration):
    """Initial database schema migration, dood!"""

    version = 5
    description = "Add Yandex Search Cache"

    def up(self, db: "DatabaseWrapper") -> None:
        """Create all initial tables, dood!"""
        with db.getCursor() as cursor:
            # Create all Cache Tables
            # Import CacheType here to avoid circular dependency
            from ...models import CacheType
            
            for cacheType in CacheType:
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS cache_{cacheType} (
                        key TEXT PRIMARY KEY,
                        data TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )

    def down(self, db: "DatabaseWrapper") -> None:
        """Drop all tables created by this migration, dood!"""
        with db.getCursor() as cursor:
            # Drop cache tables
            from ...models import CacheType
            
            for cacheType in [CacheType.YANDEX_SEARCH]:
                cursor.execute(f"DROP TABLE IF EXISTS cache_{cacheType}")


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration005YandexSearchCache