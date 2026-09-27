"""Add vision_url column to media_attachments for native-vision storage.

This migration adds a nullable ``vision_url`` column to the
``media_attachments`` table. The column stores the StorageService key of the
NORMALIZED image bytes (long-edge capped, re-encoded, EXIF-stripped — see
``lib.ai.imaging.normalizeVisionImage``) used by the native-vision feature to
attach raw images to chat LLM requests, distinct from ``local_url`` which
keeps serving the ORIGINAL bytes (e.g. to resender).

Migration Details:
- Version: 30
- Table: media_attachments
- Column: vision_url (TEXT, nullable, no default)
- Purpose: Metadata pointer to the content-addressed normalized image
  (``vision/{sha512}.{ext}``); NULL until the native-vision store step runs.

The column is intentionally nullable with no default: pre-feature rows have
no vision bytes, and "has vision bytes" stays a cheap NULL predicate that a
future GC cron can clear with a single UPDATE.

**Reversible:** ``down()`` drops the column (SQLite >= 3.35.0 supports
``DROP COLUMN``; same constraint as migration_026's rollback).
"""

from typing import Type

from lib.db.providers import BaseSQLProvider, ParametrizedQuery

from ..base import BaseMigration


class Migration030AddVisionUrl(BaseMigration):
    """Add vision_url column to media_attachments for native-vision storage.

    This migration adds the nullable ``vision_url`` TEXT column, the metadata
    pointer to normalized vision image bytes held in the StorageService.

    Attributes:
        version: The migration version number (30).
        description: Human-readable description of the migration.
    """

    version: int = 30
    description: str = "Add vision_url column to media_attachments"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply the migration to add the vision_url column.

        Adds ``vision_url`` to ``media_attachments`` as a nullable TEXT
        column with no default, portable across SQLite/PostgreSQL/MySQL.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    ALTER TABLE media_attachments
                    ADD COLUMN vision_url TEXT
                """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback the migration to remove the vision_url column.

        Removes the ``vision_url`` column from the ``media_attachments``
        table, reverting the schema to its previous state. Note that
        SQLite 3.35.0+ supports the DROP COLUMN operation.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None

        Note:
            This rollback operation requires SQLite 3.35.0 or later. For older
            versions, this will fail and require manual table recreation.
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("ALTER TABLE media_attachments DROP COLUMN vision_url"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration030AddVisionUrl
