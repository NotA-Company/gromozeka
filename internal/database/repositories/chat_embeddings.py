"""Repository for chat-message embedding provenance and the backfill helper.

This module provides the :class:`ChatEmbeddingsRepository`, which owns the
post-``migration_025`` embedding lifecycle on the message side:

- :meth:`ChatEmbeddingsRepository.saveMessageEmbedding` updates
  ``chat_messages.model_id`` (the FK-like integer allocated by
  :class:`EmbeddingModelsRepository`) and dual-writes the vector into the
  dimension-sharded vec0 virtual table when the provider supports native
  vector search.
- :meth:`ChatEmbeddingsRepository.deleteObsoleteModelEmbeddings` clears
  ``model_id`` on rows whose provenance no longer matches the chat's
  active embedding model (and mirrors the cleanup into vec0).
- :meth:`ChatEmbeddingsRepository.getMessagesWithoutEmbeddings` is the
  backfill-discovery helper used by ``ChatSearchHandler._dtCronJob``.

The legacy ``message_embeddings`` BLOB side table was dropped by
``migration_025`` (plan §6 Step 5 — ``docs/plans/embedding-model-lookup-
refactor-v1.md``). Provenance now lives in the ``models`` lookup table
keyed by ``model_id``; the ``(model, dimensions)`` text pair is no longer
stored per row.

Decision D10 (plan §5): the repo receives its
:attr:`~ChatEmbeddingsRepository._modelIdResolver` via constructor
injection. The :class:`Database` wrapper constructs :class:`EmbeddingModelsRepository`
first and passes its bound ``getOrCreateModelId`` method to this repo.
Decision D6 (extended): handler-facing signatures stay stable — the repo
resolves ``(modelName, dimensions)`` to ``model_id`` internally.

The semantic-search path that consumes the stored vectors lives in
:class:`ChatSearchRepository` (``chat_search.py``). Callers that need a
search hit set go through ``Database.chatSearch.searchChatMessages``.
"""

import array
import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

import lib.utils as libUtils
from internal.models import MessageId
from lib.db.manager import DatabaseManager
from lib.db.providers.base import (
    BaseSQLProvider,
    VectorColumnType,
    VectorDistanceMetric,
)

from .. import utils as dbUtils
from ..models import ChatMessageDict
from .base import BaseRepository

logger = logging.getLogger(__name__)


class ChatEmbeddingsRepository(BaseRepository):
    """Repository for chat-message embedding provenance and backfill discovery.

    Owns the post-``migration_025`` embedding lifecycle on the message
    side: writing ``chat_messages.model_id`` (the FK-like integer from
    :class:`EmbeddingModelsRepository`), dual-writing the vector into the
    dimension-sharded vec0 virtual table, clearing stale ``model_id``
    values on model drift, and discovering messages that still need
    embedding.

    The repository depends on a single cross-repo callable — the
    injected ``modelIdResolver`` (Decision D10). This keeps the repo
    decoupled from the concrete :class:`EmbeddingModelsRepository` and trivially
    mockable in tests.

    Attributes:
        _modelIdResolver: Async callable resolving ``(modelName,
            dimensions)`` to a ``model_id`` integer. Wired in
            :meth:`Database.__init__` to
            :meth:`EmbeddingModelsRepository.getOrCreateModelId` (bound method).
    """

    # ``manager`` is inherited from ``BaseRepository.__slots__`` and is
    # NOT redeclared here (re-declaring raises
    # ``ValueError: 'manager' in __slots__ conflicts with class variable``).
    __slots__ = ("_modelIdResolver",)

    def __init__(
        self,
        manager: DatabaseManager,
        *,
        modelIdResolver: Callable[..., Awaitable[int]],
    ) -> None:
        """Initialize the chat embeddings repository.

        Args:
            manager: Database manager instance for provider access.
            modelIdResolver: Async callable that resolves
                ``(modelName, dimensions)`` to a ``model_id`` integer.
                Wired in :meth:`Database.__init__` to
                :meth:`EmbeddingModelsRepository.getOrCreateModelId` (the bound
                method). The resolver is called as
                ``resolver(model, dimensions, *, dataSource=...)``; tests
                inject a mock.
        """
        super().__init__(manager)
        self._modelIdResolver = modelIdResolver

    async def _resolveModelId(self, model: str, dimensions: int, *, dataSource: Optional[str] = None) -> int:
        """Resolve ``(model, dimensions)`` to a ``model_id`` via the injected resolver.

        Thin wrapper around :attr:`_modelIdResolver` so call sites within
        this repo read as ``await self._resolveModelId(model, dims)``;
        the underlying caching / probe-then-insert contract lives in
        :class:`EmbeddingModelsRepository`.

        Args:
            model: Embedding model name string.
            dimensions: Vector dimensionality.
            dataSource: Optional explicit data source forwarded to the
                injected resolver for multi-source routing.

        Returns:
            The integer ``model_id``.
        """
        return await self._modelIdResolver(model, dimensions, dataSource=dataSource)

    ###
    # Embedding write
    ###
    async def saveMessageEmbedding(
        self,
        chatId: int,
        messageId: MessageId,
        embedding: List[float],
        model: str,
        *,
        date: Optional[str] = None,
    ) -> bool:
        """Save a message embedding by setting ``chat_messages.model_id``
        and writing vec0.

        Post-``migration_025`` shape: there is no ``message_embeddings``
        side table anymore. The provenance pair ``(model, dimensions)``
        is normalised into the ``models`` lookup table; this method
        resolves it to a single integer ``model_id`` via the injected
        resolver (Decision D10) and UPDATEs ``chat_messages.model_id``.

        The vector is also written into the dimension-specific vec0
        virtual table via :meth:`_upsertVecMessageEmbedding`. Vec0
        write failures are logged and swallowed — the
        ``chat_messages.model_id`` UPDATE remains the authoritative
        write and has already succeeded at that point.

        Handler-facing signature is unchanged (Decision D6 — callers in
        ``message_preprocessor.py`` and ``chat_search.py`` keep passing
        the model name string).

        Args:
            chatId: Chat identifier.
            messageId: Message identifier (Telegram = int, Max = str).
            embedding: Float vector (any length; ``len(embedding)`` is
                the dimensionality).
            model: Model name that produced the embedding (e.g. the
                resolved value of the ``EMBEDDING_MODEL`` chat setting).
            date: Optional ISO-8601 message date string, written to the
                ``date`` column of the vec0 virtual table. When ``None``,
                the current UTC timestamp is used. Passed by
                ``embedAndSaveMessage`` from ``ensuredMessage.date``.

        Returns:
            bool: True if the embedding was saved successfully, False on
            failure. Failures are logged and swallowed — callers that
            need to retry should consult the return value.
        """
        try:
            now = libUtils.now()
            dimensions = len(embedding)
            blob = array.array("f", embedding).tobytes()

            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

            # Resolve model_id via EmbeddingModelsRepository (Decisions D2 / D6 / D10).
            modelId = await self._resolveModelId(model, dimensions)

            # UPDATE chat_messages.model_id. The row already exists
            # (this is NOT an upsert — ``saveChatMessage`` was called
            # earlier in the pipeline); we are only stamping provenance.
            await sqlProvider.execute(
                "UPDATE chat_messages SET model_id = :modelId " "WHERE chat_id = :chatId AND message_id = :messageId",
                {"modelId": modelId, "chatId": chatId, "messageId": messageId.asStr()},
            )

            # Dual-write to vec0 virtual table for native vector search.
            # Failures are logged and swallowed inside the helper — the
            # authoritative UPDATE on ``chat_messages`` above already
            # succeeded.
            if not await sqlProvider.isVectorSearchSupported():
                logger.error(
                    "Vector search not supported for chat %s",
                    chatId,
                )
                return False
            try:
                actualDate = date if date is not None else now.isoformat()
                await self._upsertVecMessageEmbedding(
                    sqlProvider=sqlProvider,
                    chatId=chatId,
                    messageId=messageId.asStr(),
                    modelId=modelId,
                    date=actualDate,
                    embedding=blob,
                    dimensions=dimensions,
                )
            except Exception:
                logger.error(
                    "Failed to write vec0 embedding for chat %s message %s",
                    chatId,
                    messageId,
                    exc_info=True,
                )

            return True
        except Exception as e:
            logger.error(f"Failed to save embedding for message {messageId} in chat {chatId}: {e}")
            return False

    async def _upsertVecMessageEmbedding(
        self,
        sqlProvider: BaseSQLProvider,
        chatId: int,
        messageId: str,
        modelId: int,
        date: str,
        embedding: bytes,
        dimensions: int,
    ) -> None:
        """Upsert a row into the dimension-specific vec0 table.

        Lazily creates the vec0 virtual table on first use via
        :meth:`BaseSQLProvider.createVectorTable`. The DDL carries
        ``model_id INTEGER PARTITION KEY`` (post-``migration_025`` shape
        — the legacy ``model TEXT PARTITION KEY`` is gone). DELETE +
        INSERT is used because vec0 does not support conventional UPSERT
        on metadata columns.

        Write failures are logged at warning level and swallowed — the
        authoritative ``chat_messages.model_id`` UPDATE issued by the
        caller is independent of this best-effort mirror.

        Args:
            sqlProvider: SQL provider abstraction (must be writable and
                support vector search).
            chatId: Chat ID.
            messageId: Message ID as string.
            modelId: Resolved ``model_id`` from the ``models`` lookup
                table.
            date: ISO-8601 message date string.
            embedding: Float32 embedding bytes.
            dimensions: Embedding dimensionality (e.g. 384, 1024).
                Determines both the vec0 table name suffix and the
                ``vectorDimension`` of the lazy-create DDL.

        Returns:
            None. Failures are swallowed.
        """
        tableName = f"vec_message_embeddings_{dimensions}"

        # NOTE: Some sqlite-vec specific code. Need to be reviewed in case of Postgres/MySQL DB used.
        try:
            # Lazy table creation — check the catalog first to avoid
            # re-issuing DDL on every write once the table exists.
            existingTables = await sqlProvider.listTables(tableName)
            if tableName not in existingTables:
                await sqlProvider.createVectorTable(
                    tableName,
                    [
                        {"name": "message_id", "columnType": VectorColumnType.TEXT},
                        {"name": "chat_id", "columnType": VectorColumnType.INTEGER, "isPartitionKey": True},
                        {"name": "model_id", "columnType": VectorColumnType.INTEGER, "isPartitionKey": True},
                        {"name": "date", "columnType": VectorColumnType.TEXT},
                        {
                            "name": "embedding",
                            "columnType": VectorColumnType.VECTOR,
                            "vectorDimension": dimensions,
                            "distanceMetric": VectorDistanceMetric.COSINE,
                        },
                    ],
                )

            # vec0 DELETE-by-metadata is supported by sqlite-vec, but some
            # builds restrict WHERE predicates to partition keys only. Try
            # the metadata DELETE first; on failure, fall back to a
            # rowid-based delete (SELECT rowid then DELETE by rowid).
            try:
                await sqlProvider.execute(
                    f"DELETE FROM {tableName} "
                    f"WHERE chat_id = :chatId AND message_id = :messageId AND model_id = :modelId",
                    {"chatId": chatId, "messageId": messageId, "modelId": modelId},
                )
            except Exception:
                row = await sqlProvider.executeFetchOne(
                    f"SELECT rowid FROM {tableName} "
                    f"WHERE chat_id = :chatId AND message_id = :messageId AND model_id = :modelId",
                    {"chatId": chatId, "messageId": messageId, "modelId": modelId},
                )
                if row is not None:
                    await sqlProvider.execute(
                        f"DELETE FROM {tableName} WHERE rowid = :rowid",
                        {"rowid": row["rowid"]},
                    )

            await sqlProvider.execute(
                f"INSERT INTO {tableName} "
                f"(message_id, chat_id, model_id, date, embedding) "
                f"VALUES (:messageId, :chatId, :modelId, :date, :embedding)",
                {
                    "messageId": messageId,
                    "chatId": chatId,
                    "modelId": modelId,
                    "date": date,
                    "embedding": embedding,
                },
            )
        except Exception:
            logger.warning(
                "Failed to upsert vec0 embedding for chat %s message %s",
                chatId,
                messageId,
                exc_info=True,
            )

    ###
    # Model-drift cleanup
    ###
    async def deleteObsoleteModelEmbeddings(
        self,
        chatId: int,
        currentModel: str,
        currentDimensions: int,
    ) -> bool:
        """Clear ``model_id`` on rows whose provenance no longer matches the active model.

        Called when the embedding model changes for a chat (detected by
        the caller via in-memory tracking). Sets ``chat_messages.model_id
        = NULL`` on every stale row. The backfill worker then
        re-discovers those rows via :meth:`getMessagesWithoutEmbeddings`
        and re-embeds them under the new model.

        Stateless and idempotent: on the common path (model unchanged)
        the UPDATE matches zero rows. Callers should gate this with
        their own change-detection logic to avoid unnecessary work.

        Stale rows are those with ``model_id`` not matching the resolved
        ``(currentModel, currentDimensions)`` id. The repo resolves the
        canonical ``model_id`` via :meth:`_resolveModelId` and uses the
        ``model_id != :currentModelId`` predicate.

        Vec0 cleanup mirrors the SQL UPDATE: every
        ``vec_message_embeddings_{N}`` table for the chat has its
        non-matching rows removed. The dimension-matching vec0 table has
        its non-matching-``model_id`` rows deleted (matching rows
        survive); tables belonging to a different dimensionality are
        cleared entirely for the chat. If the provider rejects a DELETE,
        the failure is logged and swallowed (best-effort mirror).

        Args:
            chatId: Chat identifier.
            currentModel: The currently-active embedding model name.
                Rows whose ``model_id`` does not resolve back to this
                model are cleared.
            currentDimensions: The currently-active embedding
                dimensionality. Combined with *currentModel* to resolve
                the single canonical ``model_id`` used in the stale-row
                predicate.

        Returns:
            bool: True if cleanup completed successfully, False on
            failure. Failures are logged and swallowed — callers should
            consult the return value to decide whether to update their
            own change-tracking state (a failed cleanup should not be
            treated as complete, or it will not be retried until the
            model changes again).
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

            # Resolve the canonical model_id for (currentModel, currentDimensions),
            # then clear stale provenance on chat_messages.
            currentModelId = await self._resolveModelId(currentModel, currentDimensions)
            await sqlProvider.execute(
                "UPDATE chat_messages SET model_id = NULL "
                "WHERE chat_id = :chatId AND model_id IS NOT NULL "
                "AND model_id != :currentModelId",
                {"chatId": chatId, "currentModelId": currentModelId},
            )

            # Mirror the cleanup into vec0 virtual tables (best-effort).
            if not await sqlProvider.isVectorSearchSupported():
                logger.error(
                    "Semantic search for chat %s returning [] — vec0 not supported by provider",
                    chatId,
                )
                return False
            try:
                vecTables = await sqlProvider.listTables("vec_message_embeddings_%")
                # Filter out vec0 shadow tables (vec_message_embeddings_384_info,
                # vec_message_embeddings_384_chunks, etc.) — sqlite-vec uses
                # internal shadow tables that also match the LIKE pattern and
                # appear in sqlite_master with type='table', but they don't have
                # our custom columns (chat_id, model_id, message_id, date).
                vecTables = [t for t in vecTables if re.match(r"^vec_message_embeddings_\d+$", t)]
                for table in vecTables:
                    tableDim: Optional[int] = None
                    try:
                        tableDim = int(table.rsplit("_", 1)[-1])
                    except (ValueError, IndexError):
                        # Defensive: skip tables with non-numeric suffixes
                        # (shouldn't happen after the regex filter above).
                        continue

                    if tableDim == currentDimensions:
                        # Same-dimension table — clear rows whose model_id
                        # does not match the resolved current id.
                        await sqlProvider.execute(
                            f"DELETE FROM {table} WHERE chat_id = :chatId AND model_id != :currentModelId",
                            {"chatId": chatId, "currentModelId": currentModelId},
                        )
                    else:
                        # The table belongs to a different dimensionality
                        # entirely — clear all rows for this chat (the
                        # partitioning itself is stale).
                        await sqlProvider.execute(
                            f"DELETE FROM {table} WHERE chat_id = :chatId",
                            {"chatId": chatId},
                        )
            except NotImplementedError:
                logger.debug(
                    "Backfill: listTables not supported for chat %d; skipping vec0 model change cleanup",
                    chatId,
                )
            return True
        except Exception:
            logger.warning(
                "Failed to delete obsolete embeddings for chat %d (current model %s)",
                chatId,
                currentModel,
                exc_info=True,
            )
            return False

    ###
    # Backfill discovery
    ###
    async def getMessagesWithoutEmbeddings(
        self,
        chatId: int,
        *,
        limit: int = 100,
        modelName: Optional[str] = None,
        dimensions: Optional[int] = None,
        dataSource: Optional[str] = None,
    ) -> List[ChatMessageDict]:
        """Return messages whose stored provenance does not match the active model.

        Used by the embedding backfill worker (``ChatSearchHandler._dtCronJob``)
        to discover which rows in ``chat_messages`` still need a vector
        generated under the chat's active embedding model. Returns
        :class:`ChatMessageDict` rows (joined with ``chat_users`` for
        ``username`` / ``full_name``) so the consumer can read
        ``message_id`` and ``message_text`` directly.

        Post-``migration_025`` shape: the filter is a single-table
        predicate against ``chat_messages.model_id``. Returns messages
        where ``model_id IS NULL`` OR ``model_id != currentModelId``
        (resolved from *modelName* + *dimensions* via
        :meth:`_resolveModelId`). When *modelName* is ``None``, only
        rows with ``model_id IS NULL`` are returned.

        Args:
            chatId: Chat identifier to scan.
            limit: Maximum number of rows to return. Defaults to 100.
            modelName: When provided (with *dimensions*), only messages
                whose ``model_id`` is missing OR does not match the
                resolved ``model_id`` are returned. When ``None``, only
                rows with ``model_id IS NULL`` are returned.
            dimensions: When provided alongside *modelName*, resolves a
                single canonical ``model_id`` for ``(modelName,
                dimensions)`` via :meth:`_resolveModelId`.
            dataSource: Optional explicit data source.

        Returns:
            List of :class:`ChatMessageDict` rows (one per pending
            message, joined against ``chat_users`` for ``username`` /
            ``full_name``), ordered by date descending (most recent
            first). Empty list on error.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            params: Dict[str, Any] = {"chatId": chatId, "currentModelId": None}
            if modelName is not None and dimensions is not None:
                params["currentModelId"] = await self._resolveModelId(modelName, dimensions, dataSource=dataSource)

            query = """
                SELECT c.*, u.username, u.full_name
                FROM chat_messages c
                JOIN chat_users u
                    ON u.chat_id = c.chat_id AND u.user_id = c.user_id
                WHERE
                    c.chat_id = :chatId
                    AND c.message_text IS NOT NULL
                    AND c.message_text != ''
                    AND (c.model_id IS NULL OR
                        (:currentModelId IS NOT NULL AND c.model_id != :currentModelId)
                    )
                ORDER BY c.date DESC, c.message_id DESC
            """
            query = sqlProvider.applyPagination(query=query, limit=int(limit))
            rows = await sqlProvider.executeFetchAll(query, params)
            return [dbUtils.sqlToTypedDict(row, ChatMessageDict) for row in rows]
        except Exception as e:
            logger.error(f"Failed to list messages without embeddings for chat {chatId}: {e}")
            return []
