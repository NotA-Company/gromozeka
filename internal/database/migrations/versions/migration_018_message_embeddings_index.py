"""Add secondary index on message_embeddings (chat_id, model).

The composite primary key (chat_id, message_id) indexes chat_id as the
leftmost prefix, but the _loadEmbeddingsFromDb query in
``ChatSearchRepository`` filters on both chat_id and model:

.. code-block:: sql

    SELECT me.message_id, me.embedding, me.dimensions
    FROM message_embeddings me
    WHERE me.chat_id = :chatId AND me.model = :modelName

After a chat switches its ``EMBEDDING_MODEL`` chat setting, the old-model
rows remain and get scanned on every semantic search.  The new
``idx_message_embeddings_chat_model`` index lets SQLite (and any future
PostgreSQL/MySQL provider) seek directly to the matching rows, keeping the
scan bounded by the active model's row count rather than the full chat's.

Schema notes (cross-RDBMS portability):
- Index name uses snake_case prefixed with ``idx_`` (project convention).
- ``IF NOT EXISTS`` / ``IF EXISTS`` guards for idempotency.
- No dialect-specific syntax — portable across SQLite/PostgreSQL/MySQL.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration018MessageEmbeddingsIndex(BaseMigration):
    """Add secondary index on message_embeddings (chat_id, model).

    Speeds up the ``_loadEmbeddingsFromDb`` query pattern that filters
    embeddings by chat and model name. Without this index, after a model
    switch the query scans all rows for the chat, discarding stale-model
    rows in the WHERE clause.

    Attributes:
        version: Migration version number (18).
        description: Human-readable description of the migration.
    """

    version: int = 18
    """The version number of this migration."""
    description: str = "Add secondary index on message_embeddings (chat_id, model)"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create the idx_message_embeddings_chat_model index.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_message_embeddings_chat_model
                    ON message_embeddings (chat_id, model)
                """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop the idx_message_embeddings_chat_model index.

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP INDEX IF EXISTS idx_message_embeddings_chat_model"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration018MessageEmbeddingsIndex
