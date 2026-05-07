"""Migration: add divination_layouts table - v015!"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration015AddDivinationLayoutsTable(BaseMigration):
    """Add divination_layouts table for caching layout definitions.

    The table uses a composite PK (system_id, layout_name) for efficient
    lookups when retrieving layout definitions for divination systems.

    Attributes:
        version: Migration version number (15).
        description: Human-readable description.
    """

    version: int = 15
    description: str = "Add divination_layouts table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create divination_layouts table and supporting index.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS divination_layouts (
                        system_id     TEXT    NOT NULL,
                        layout_id     TEXT    NOT NULL,
                        name_en       TEXT    NOT NULL,
                        name_ru       TEXT    NOT NULL,
                        n_symbols     INTEGER NOT NULL,
                        positions     TEXT    NOT NULL,
                        description   TEXT,
                        created_at    TIMESTAMP NOT NULL,
                        updated_at    TIMESTAMP NOT NULL,
                        PRIMARY KEY (system_id, layout_id)
                    )
                """),
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_divination_layouts_system
                    ON divination_layouts (system_id)
                """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop divination_layouts table and its index.

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP INDEX IF EXISTS idx_divination_layouts_system"),
                ParametrizedQuery("DROP TABLE IF EXISTS divination_layouts"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration015AddDivinationLayoutsTable
