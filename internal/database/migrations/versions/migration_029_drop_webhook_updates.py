"""Drop webhook_updates table from the main bot database.

This migration removes the ``webhook_updates`` table and its index from the
bot's database as part of extracting the Max webhook receiver into its own
standalone process with its own database file. The table and index are now
owned exclusively by ``lib/max_webhook_receiver/`` and live in the receiver's
``webhook_receiver_data.db`` file.

The migration is safe to deploy: the bot never read from or wrote to
``webhook_updates`` — only the webhook receiver process did, and it now uses
its own database. The receiver's ``schema.py`` module is the single source
of truth for the DDL; migrations and the receiver's self-heal share it via
``getForwardDDL()``.

**Schema change:**

- Drops ``idx_webhook_updates_unprocessed`` index
- Drops ``webhook_updates`` table

**Backward compatibility:** Safe — the bot has no dependency on this table.
The receiver uses its own database. Rollback recreates both table and index
via the canonical DDL from ``lib.max_webhook_receiver.schema``.

**Reversible:** ``down()`` recreates the table and index using the canonical
DDL from ``lib.max_webhook_receiver.schema.getForwardDDL()``.
"""

from typing import Type

from lib.db.providers import BaseSQLProvider, ParametrizedQuery
from lib.max_webhook_receiver.schema import getForwardDDL

from ..base import BaseMigration


class Migration029DropWebhookUpdates(BaseMigration):
    """Drop the webhook_updates table from the main bot database.

    This migration removes webhook_updates as part of extracting the Max webhook
    receiver into its own standalone process with its own database file. The
    table and index are now owned exclusively by lib/max_webhook_receiver/.

    Attributes:
        version: Migration version number (29).
        description: Human-readable description of the migration.
    """

    version: int = 29
    """The version number of this migration."""
    description: str = "Drop webhook_updates table (moved to the webhook receiver's own database)"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop the webhook_updates index and table from the bot's database.

        The index is dropped before the table, mirroring migration_019's rollback
        and staying valid on providers that require an explicit index drop.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP INDEX IF EXISTS idx_webhook_updates_unprocessed"),
                ParametrizedQuery("DROP TABLE IF EXISTS webhook_updates"),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Recreate the webhook_updates table and index via canonical DDL.

        Consumes ``getForwardDDL()`` from ``lib.max_webhook_receiver.schema``
        to recreate both the table and its index, ensuring the rollback DDL
        matches the receiver's canonical schema exactly.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        ddlStatements = getForwardDDL()
        await sqlProvider.batchExecute(ddlStatements)


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration029DropWebhookUpdates
