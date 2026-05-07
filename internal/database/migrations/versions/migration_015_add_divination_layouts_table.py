"""Create divination_layouts table for caching layout definitions.

This migration creates a table to store divination layout definitions
(e.g., tarot spreads, rune spreads) for different divination systems.
Layouts define how symbols/cards are arranged and interpreted.

The table uses a composite primary key (system_id, layout_id) for efficient
lookups when retrieving layout definitions for divination systems.

This migration is part of the divination feature system that includes:
- migration_014: divinations table (stores reading results)
- migration_015: divination_layouts table (stores layout definitions)
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration015AddDivinationLayoutsTable(BaseMigration):
    """Create divination_layouts table for caching layout definitions.

    This migration establishes a table to store divination layout definitions
    that define how symbols/cards are arranged and interpreted in divination
    readings (e.g., tarot spreads, rune spreads). Each layout belongs to a
    divination system and includes information about the number of symbols
    and the position meanings.

    The table uses a composite primary key (system_id, layout_id) to ensure
    efficient lookups when retrieving layout definitions for specific divination
    systems.

    Attributes:
        version: Migration version number (15).
        description: Human-readable description of the migration.
    """

    version: int = 15
    """The version number of this migration."""
    description: str = "Add divination_layouts table"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create divination_layouts table and supporting index.

        This method creates the divination_layouts table with the following columns:
        - system_id: ID of the divination system (e.g., 'tarot', 'runes')
        - layout_id: Unique identifier for the layout within the system
        - name_en: English name of the layout
        - name_ru: Russian name of the layout
        - n_symbols: Number of symbols/cards in the layout
        - positions: JSON-encoded position definitions and meanings
        - description: Optional text description of the layout
        - created_at: Record creation timestamp
        - updated_at: Last update timestamp

        The composite primary key (system_id, layout_id) ensures each layout is
        unique within its system. An index on system_id enables efficient queries
        for all layouts in a system.

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

        This method removes the divination_layouts table and the supporting
        index on system_id. This is the exact inverse of the up() method.

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
