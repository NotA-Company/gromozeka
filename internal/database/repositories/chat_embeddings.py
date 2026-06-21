"""Repository for managing chat message embeddings.

This module provides the :class:`ChatEmbeddingsRepository` class which owns
all database operations related to the ``message_embeddings`` table —
the embedding CRUD (save / get / delete) and the backfill helper
``getMessagesWithoutEmbeddings`` used by ``ChatSearchHandler._dtCronJob``.

The semantic-search path itself (loading embeddings, applying
pre-filters, computing cosine similarity via ``numpy``, fetching the
top-K messages) was split out of this repository into the dedicated
:class:`ChatSearchRepository` (``chat_search.py``) so that embeddings
CRUD and chat-message search live in cohesive, focused modules. The
embedding repository now owns the embedding storage lifecycle; the
search repository owns the ranking path that consumes the stored
vectors.

The repository no longer maintains an in-memory embedding cache —
semantic search re-loads embeddings from ``message_embeddings`` on
every call. Caching belongs in the handler layer (via
``CacheService``) and intentionally does not live in the database
layer.
"""

import array
import datetime
import logging
from typing import Any, Dict, List, Optional

from internal.models import MessageId

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import ChatMessageDict, MessageEmbeddingDict
from ..providers.base import ExcludedValue
from .base import BaseRepository

logger = logging.getLogger(__name__)


class ChatEmbeddingsRepository(BaseRepository):
    """Repository for chat message embeddings CRUD and the backfill helper.

    Provides methods to save, retrieve, and delete per-message embedding
    vectors, plus ``getMessagesWithoutEmbeddings`` — the backfill helper
    that finds messages without embeddings (used by
    ``ChatSearchHandler._dtCronJob``).

    The semantic-search path that consumes these embeddings lives in
    :class:`ChatSearchRepository` (``chat_search.py``). Callers that
    need a search hit set go through ``Database.chatSearch.searchChatMessages``.
    """

    __slots__ = ()

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialize the chat embeddings repository.

        Args:
            manager: Database manager instance for provider access.
        """
        super().__init__(manager)

    ###
    # Embedding CRUD
    ###
    async def saveMessageEmbedding(
        self,
        chatId: int,
        messageId: MessageId,
        embedding: List[float],
        model: str,
    ) -> bool:
        """Save or update a message embedding.

        The `dimensions` column is derived from `len(embedding)` rather than
        passed as a separate argument — this avoids mismatch bugs. The
        vector is serialised to a `BLOB` via `array.array('f', vec).tobytes()`
        (cross-RDBMS-portable raw bytes; same float32 representation on
        every supported backend).

        Args:
            chatId: Chat identifier.
            messageId: Message identifier.
            embedding: Float vector (any length, becomes `dimensions` column).
            model: Model name that produced the embedding (e.g. the resolved
                value of the `EMBEDDING_MODEL` chat setting).

        Returns:
            None

        Raises:
            Exception: If the database operation fails (caught and logged).
        """
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            dimensions = len(embedding)
            blob = array.array("f", embedding).tobytes()

            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.upsert(
                table="message_embeddings",
                values={
                    "chat_id": chatId,
                    "message_id": messageId.asStr(),
                    "embedding": blob,
                    "dimensions": dimensions,
                    "model": model,
                    "created_at": now,
                    "updated_at": now,
                },
                conflictColumns=["chat_id", "message_id"],
                updateExpressions={
                    "embedding": ExcludedValue(),
                    "dimensions": ExcludedValue(),
                    "model": ExcludedValue(),
                    "updated_at": ExcludedValue(),
                },
            )

            return True
        except Exception as e:
            logger.error(f"Failed to save embedding for message {messageId} in chat {chatId}: {e}")
            return False

    async def getMessageEmbedding(
        self,
        chatId: int,
        messageId: MessageId,
        *,
        dataSource: Optional[str] = None,
    ) -> Optional[MessageEmbeddingDict]:
        """Get the embedding for a specific message.

        Args:
            chatId: Chat identifier.
            messageId: Message identifier.
            dataSource: Optional explicit data source.

        Returns:
            :class:`MessageEmbeddingDict` with
              * ``message_id`` (``MessageId``),
              * ``embedding`` (``list[float]``, pre-decoded from the BLOB),
              * ``dimensions`` (``int``),
              * ``model`` (``str``),
              * ``created_at`` (``datetime``),
              * ``updated_at`` (``datetime``).
            Returns ``None`` if no embedding found.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            row = await sqlProvider.executeFetchOne(
                """
                SELECT
                    message_id, embedding, dimensions, model, created_at, updated_at
                FROM message_embeddings
                WHERE
                    chat_id = :chatId AND
                    message_id = :messageId
            """,
                {
                    "chatId": chatId,
                    "messageId": messageId.asStr(),
                },
            )
            if row is None:
                return None
            # Pre-decode the embedding BLOB; the converter does not handle
            # bytes -> list[float] on its own (no JSON path for raw float32
            # BLOBs). The WHERE clause guarantees this BLOB is non-null.
            row["embedding"] = list(array.array("f", row["embedding"]))
            return dbUtils.sqlToTypedDict(row, MessageEmbeddingDict)
        except Exception as e:
            logger.error(f"Failed to get embedding for message {messageId} in chat {chatId}: {e}")
            return None

    async def deleteChatEmbeddings(self, chatId: int) -> None:
        """Delete all embeddings for a chat.

        Args:
            chatId: Chat identifier.

        Returns:
            None

        Raises:
            Exception: If the database operation fails (caught and logged).
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.execute(
                "DELETE FROM message_embeddings WHERE chat_id = :chatId",
                {"chatId": chatId},
            )
        except Exception as e:
            logger.error(f"Failed to delete embeddings for chat {chatId}: {e}")

    async def getMessagesWithoutEmbeddings(
        self,
        chatId: int,
        *,
        limit: int = 100,
        modelName: Optional[str] = None,
        dataSource: Optional[str] = None,
    ) -> List[ChatMessageDict]:
        """Return pending messages (without embeddings) as full dicts.

        Used by the embedding backfill worker (§11 of
        ``docs/plans/chat-history-search-plan.md``) to discover which rows in
        ``chat_messages`` still need a vector generated. Returns
        :class:`ChatMessageDict` rows (joined with ``chat_users`` for
        ``username``/``full_name``) so the consumer can read
        ``message_id`` and ``message_text`` directly — the embedding
        table is not selected at all.

        The filter against ``message_embeddings`` is expressed as a
        correlated ``NOT EXISTS`` subquery rather than a ``LEFT JOIN``:
        no embedding-side fields are returned, so the join was only
        dead weight. ``NOT EXISTS`` is also clearer than the equivalent
        ``NOT IN`` and matches the original semantics exactly.

        Args:
            chatId: Chat identifier to scan.
            limit: Maximum number of rows to return. Defaults to 100.
            modelName: When provided, only messages whose ``message_embeddings``
                row is missing **or** has a different ``model`` column are
                returned. This matches the
                ``REGENERATE_EMBEDDINGS``-with-model-change contract from
                §2.7 of the plan: switching the ``EMBEDDING_MODEL`` chat
                setting should re-embed rows produced by the previous model.
                When ``None``, only rows with no ``message_embeddings`` row at
                all are returned.
            dataSource: Optional explicit data source.

        Returns:
            List of :class:`ChatMessageDict` (one per pending message,
            joined against ``chat_users`` for ``username``/``full_name``),
            ordered by date descending (most recent first). Empty list
            on error.
        """
        # logger.debug(
        #     f"Listing messages without embeddings for chat {chatId}: "
        #     f"limit={limit}, modelName={modelName}, dataSource={dataSource}"
        # )
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)

            query = """
                SELECT c.*, u.username, u.full_name
                FROM chat_messages c
                JOIN chat_users u
                    ON u.chat_id = c.chat_id AND u.user_id = c.user_id
                WHERE
                    c.chat_id = :chatId
                    AND c.message_text IS NOT NULL
                    AND c.message_text != ''
                    AND NOT EXISTS (
                        SELECT 1 FROM message_embeddings me
                        WHERE me.chat_id = c.chat_id
                        AND me.message_id = c.message_id
                        AND (:modelName IS NULL OR me.model = :modelName)
                    )
                ORDER BY c.date DESC, c.message_id DESC
            """
            # ``modelName`` is always present in the binding params so
            # the ``:modelName IS NULL`` short-circuit in the subquery
            # has a value to test against. SQL portability note: every
            # driver (SQLite/PostgreSQL/MySQL) raises if a named
            # placeholder is referenced in the query string but not
            # bound, so we cannot omit the key when ``modelName`` is
            # ``None``.
            params: Dict[str, Any] = {
                "chatId": chatId,
                "modelName": modelName,
            }

            query = sqlProvider.applyPagination(query=query, limit=int(limit))
            rows = await sqlProvider.executeFetchAll(query, params)
            return [dbUtils.sqlToTypedDict(row, ChatMessageDict) for row in rows]
        except Exception as e:
            logger.error(f"Failed to list messages without embeddings for chat {chatId}: {e}")
            return []
