"""Create message_embeddings table for chat-history semantic search.

This migration introduces a sidecar table that stores vector embeddings
for chat messages, enabling semantic search via cosine similarity.
Each row binds a (chat_id, message_id) pair — the same composite PK used
by `chat_messages` — to a serialized float32 embedding BLOB plus the
model name and dimensionality used to produce it.

The `model` and `dimensions` columns are stored per row so a chat that
switches its `EMBEDDING_MODEL` chat setting can detect stale rows
without joining against the LLM registry at SQL time. See
`docs/plans/chat-history-search-plan.md` §3.1 for the design rationale.

Schema notes (cross-RDBMS portability):
- Composite PK (chat_id, message_id) — natural key, no AUTOINCREMENT/SERIAL.
- `embedding BLOB` — portable blob type across SQLite/PostgreSQL/MySQL.
- `created_at` / `updated_at` are set by application code; no DB default.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration017MessageEmbeddings(BaseMigration):
    """Add the message_embeddings table backing semantic chat search.

    Stores one float32 vector per (chat_id, message_id), plus the model
    name and dimensionality that produced it. Used by
    `ChatMessagesRepository.searchChatMessages` for cosine-similarity
    ranking of search results.

    Attributes:
        version: Migration version number (17).
        description: Human-readable description of the migration.
    """

    version: int = 17
    """The version number of this migration."""
    description: str = "Add message_embeddings table for semantic search"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create the message_embeddings table.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS message_embeddings (
                        chat_id    INTEGER   NOT NULL,
                        message_id TEXT      NOT NULL,
                        embedding  BLOB      NOT NULL,
                        dimensions INTEGER   NOT NULL,
                        model      TEXT      NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL,
                        PRIMARY KEY (chat_id, message_id)
                    )
                """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop the message_embeddings table.

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP TABLE IF EXISTS message_embeddings"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration017MessageEmbeddings
