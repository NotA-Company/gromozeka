"""Repository for chat message search (filter-only and semantic).

This module provides the :class:`ChatSearchRepository` class which
unifies the two chat-message search modes:

- **Filter-only mode** (``queryEmbedding is None``): the SQL filter
  path that applies ``userFilter`` / ``categoryFilter`` / ``maxAgeDays``
  / ``rootMessageId`` directly against ``chat_messages`` joined to
  ``chat_users``, ordered by ``date`` descending.
- **Semantic mode** (``queryEmbedding is not None``): delegates cosine
  ranking to the provider's native vec0 virtual table
  (``vec_message_embeddings_{N}``). There is NO in-process fallback
  anymore — the legacy ``message_embeddings`` BLOB side table and the
  numpy cosine block were dropped in ``migration_025`` (plan §4.5 /
  Decision D8 — numpy fully retired from this file). When vec0 is
  unavailable, raises, or yields no matches, semantic search returns
  ``[]``.

The public :meth:`ChatSearchRepository.searchChatMessages` dispatcher
selects the mode at runtime. Decision D6 (extended) keeps the
handler-facing signature stable — callers keep passing
``modelName=...``; resolution to ``model_id`` happens internally via
the injected resolver (Decision D10 — see
:meth:`ChatSearchRepository.__init__`).
"""

import array
import datetime
import logging
import math
from collections.abc import Sequence
from typing import Awaitable, Callable, List, Optional

from internal.models import MessageId
from lib.db.manager import DatabaseManager
from lib.db.providers.base import BaseSQLProvider, VectorDistanceMetric

from .. import utils as dbUtils
from ..models import ChatMessageDict, MessageCategory
from .base import BaseRepository

logger = logging.getLogger(__name__)

#: Number of message ID filter parameters per SQL batch.
#: On modern SQLite (3.32+, shipped with Python 3.12), ``SQLITE_MAX_VARIABLE_NUMBER`` is 32766.
#: The dynamic reduction (32766 - baseParamCount) handles older builds.
#: 1024 is a safe default batch size that keeps queries under the limit.
_MESSAGE_ID_FILTER_BATCH_SIZE: int = 1024


class ChatSearchRepository(BaseRepository):
    """Unified chat-message search across ``chat_messages`` and vec0.

    The repository owns both the filter-only SQL path and the semantic
    (vec0-backed) path, plus the private helpers
    (``_filterMessageIds``, ``_fetchSearchResultRows``) that the
    semantic path composes. Post-``migration_025``:

    - The legacy ``message_embeddings`` BLOB side table is gone; vec0
      (``vec_message_embeddings_{N}``) is the sole vector store on the
      message side.
    - The numpy cosine fallback block is gone (Decision D8). When vec0
      is unavailable, raises, or returns no matches, semantic search
      returns ``[]``.
    - Provenance is keyed by ``model_id`` (the small integer from
      :class:`EmbeddingModelsRepository`); the ``(modelName, dimensions)``
      handler-facing argument is resolved internally via the injected
      ``modelIdResolver`` (Decision D10).

    Embedding CRUD itself (``saveMessageEmbedding``,
    ``getMessagesWithoutEmbeddings``, ``deleteObsoleteModelEmbeddings``)
    lives in :class:`ChatEmbeddingsRepository` — this repository only
    consumes the stored vectors for ranking.

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
        """Initialize the chat search repository.

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
    # Public dispatcher
    ###
    async def searchChatMessages(
        self,
        chatId: int,
        queryEmbedding: Optional[List[float]] = None,
        *,
        limit: Optional[int] = 10,
        topK: int = 100,
        userFilter: Optional[int] = None,
        categoryFilter: Optional[Sequence[MessageCategory]] = None,
        maxAgeDays: Optional[int] = None,
        rootMessageId: Optional[MessageId] = None,
        modelName: Optional[str] = None,
        maxMessages: Optional[int] = None,
        dataSource: Optional[str] = None,
        threadId: Optional[int] = None,
        substring: Optional[str] = None,
    ) -> List[ChatMessageDict]:
        """Search chat messages, with optional semantic ranking.

        Two modes:

        - **Semantic mode** (``queryEmbedding`` provided): delegates
          cosine ranking to the provider's native vec0 virtual table.
          ``modelName`` is resolved to ``model_id`` internally via the
          injected resolver (Decision D6 extended + Decision D10) —
          handler call sites keep passing the model name string
          unchanged. When vec0 is unavailable, raises, or yields no
          matches, an empty list is returned (there is no in-process
          fallback post-``migration_025``).
        - **Filter-only mode** (``queryEmbedding is None``): the SQL
          filters (``userFilter``, ``categoryFilter``, ``maxAgeDays``,
          ``rootMessageId``) are applied directly against
          ``chat_messages`` joined to ``chat_users`` and results are
          returned sorted by ``date`` descending with ``score=0.0``.

        Args:
            chatId: Chat to search in.
            queryEmbedding: Query vector from the embedding model. When
                ``None``, the search runs in filter-only mode (no
                ranking, sorted by date).
            limit: Max results to return. ``None`` means "no cap" — no
                ``LIMIT`` clause is appended so callers that need to
                filter the result-set further (e.g. a client-side
                keyword match applied after retrieval) do not lose
                matches to early pagination. In semantic mode this is
                a soft cap on the post-ranking slice (see ``topK``).
            topK: In semantic mode, how many candidates to consider
                before the final result-set trim. Ignored in filter-only
                mode.
            userFilter: Optional user ID to narrow search.
            categoryFilter: Optional message category filter. Sequence
                of :class:`MessageCategory`; messages matching any of
                the listed categories are kept.
            maxAgeDays: Only consider messages newer than N days.
            rootMessageId: Optional thread root. When set, results are
                restricted to messages with
                ``root_message_id == rootMessageId`` (i.e. replies
                within the same thread).
            modelName: Embedding model name (the resolved value of the
                ``EMBEDDING_MODEL`` chat setting). Required for
                semantic mode — when ``None``, semantic search returns
                an empty list. The repo resolves
                ``(modelName, len(queryEmbedding))`` to a ``model_id``
                internally; the handler-facing signature is unchanged
                per Decision D6 (extended).
            maxMessages: Cap on how many embedding rows to consider for
                this chat. Defaults to ``None`` (no cap). Honours the
                ``MAX_MESSAGES_FOR_SEMANTIC_SEARCH`` chat setting when
                passed through by the caller.
            dataSource: Optional explicit data source.
            threadId: Optional thread/topic id to restrict the search
                to (``0`` = main thread). When ``None``, no thread
                scoping is applied.
            substring: Optional case-insensitive substring to match in
                ``message_text``. When ``None``, no text filter is
                applied. The repository wraps the raw value into
                ``%...%`` and binds it via a portable ``LIKE``
                comparison (see ``getLikeComparison``).

        Returns:
            List of :class:`ChatMessageDict` with message content,
            user info, and the optional ``score`` field populated.
            In filter-only mode the ``score`` field is ``0.0`` (no
            ranking applied); in semantic mode it is the cosine
            similarity against ``queryEmbedding``. Returns ``[]`` when
            vec0 is unavailable, raises, yields no matches, or when
            ``modelName`` is ``None``.

        Raises:
            Exception: Database errors are caught and logged; an empty
                list is returned on failure. Callers that need a
                different failure mode should check the logs.
        """
        logger.debug(
            f"Searching messages for chat {chatId}: limit={limit}, topK={topK}, "
            f"userFilter={userFilter}, categoryFilter={categoryFilter}, "
            f"maxAgeDays={maxAgeDays}, rootMessageId={rootMessageId}, "
            f"modelName={modelName}, maxMessages={maxMessages}, "
            f"dataSource={dataSource}, threadId={threadId}, substring={substring}, "
            f"hasQueryEmbedding={queryEmbedding is not None}"
        )
        if queryEmbedding is None:
            return await self._filterOnlySearch(
                chatId=chatId,
                limit=limit,
                userFilter=userFilter,
                categoryFilter=categoryFilter,
                maxAgeDays=maxAgeDays,
                rootMessageId=rootMessageId,
                dataSource=dataSource,
                threadId=threadId,
                substring=substring,
            )
        return await self._semanticSearch(
            chatId=chatId,
            queryEmbedding=queryEmbedding,
            limit=limit,
            topK=topK,
            userFilter=userFilter,
            categoryFilter=categoryFilter,
            maxAgeDays=maxAgeDays,
            rootMessageId=rootMessageId,
            modelName=modelName,
            maxMessages=maxMessages,
            dataSource=dataSource,
            threadId=threadId,
            substring=substring,
        )

    ###
    # Filter-only mode
    ###
    async def _filterOnlySearch(
        self,
        chatId: int,
        *,
        limit: Optional[int],
        userFilter: Optional[int],
        categoryFilter: Optional[Sequence[MessageCategory]],
        maxAgeDays: Optional[int],
        rootMessageId: Optional[MessageId],
        dataSource: Optional[str],
        threadId: Optional[int] = None,
        substring: Optional[str] = None,
    ) -> List[ChatMessageDict]:
        """Filter-only search path used by :meth:`searchChatMessages`.

        Applies the supplied SQL filters directly against
        ``chat_messages`` joined to ``chat_users``, ordered by ``date``
        descending. No vector ranking. The ``score`` field is always
        ``0.0``.

        ``limit`` follows the cross-RDBMS ``applyPagination`` contract:
        ``None`` means "no cap" (no ``LIMIT`` clause is appended), and
        an ``int`` means "cap to N rows".

        Args:
            chatId: Chat to search in.
            limit: Max results to return. ``None`` means no cap.
            userFilter: Optional user ID to narrow search.
            categoryFilter: Optional message category filter.
            maxAgeDays: Only consider messages newer than N days.
            rootMessageId: Optional thread root to filter by.
            dataSource: Optional explicit data source.
            threadId: Optional thread/topic id filter (``0`` = main).
            substring: Optional case-insensitive substring; bound as
                ``%...%`` via ``getLikeComparison``.

        Returns:
            List of :class:`ChatMessageDict` with ``score=0.0``. Empty
            list on failure.
        """
        try:
            cutoffTs: Optional[datetime.datetime] = None
            if maxAgeDays is not None:
                cutoffTs = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=maxAgeDays)

            params: dict = {
                "chatId": chatId,
                "userFilter": userFilter,
                "rootMessageId": rootMessageId.asStr() if rootMessageId is not None else None,
                "cutoffTs": cutoffTs,
                "categoryFilter": None if categoryFilter is None else True,
                "threadId": threadId,
                "substring": f"%{substring}%" if substring else None,
            }
            categoryPlaceholders: list = []
            if categoryFilter:
                for i, category in enumerate(categoryFilter):
                    categoryPlaceholders.append(f":categoryFilter{i}")
                    params[f"categoryFilter{i}"] = str(category)

            categoryClause = ""
            if categoryFilter:
                categoryClause = f"OR c.message_category IN ({', '.join(categoryPlaceholders)})"

            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            query = f"""
                SELECT c.*, u.username, u.full_name FROM chat_messages c
                JOIN chat_users u ON c.user_id = u.user_id AND c.chat_id = u.chat_id
                WHERE
                    c.chat_id = :chatId
                    AND (:userFilter     IS NULL OR c.user_id = :userFilter)
                    AND (:rootMessageId  IS NULL OR c.root_message_id = :rootMessageId)
                    AND (:threadId       IS NULL OR c.thread_id = :threadId)
                    AND (:substring      IS NULL OR {sqlProvider.getLikeComparison("c.message_text", "substring")})
                    AND (:cutoffTs       IS NULL OR c.date > :cutoffTs)
                    AND (:categoryFilter IS NULL {categoryClause})
                ORDER BY c.date DESC, c.message_id DESC
            """
            query = sqlProvider.applyPagination(query=query, limit=limit)
            rows = await sqlProvider.executeFetchAll(query, params)
            results: list = []
            for row in rows:
                rowDict = dbUtils.sqlToTypedDict(row, ChatMessageDict)
                # Filter-only mode never ranks, so score is fixed at 0.0.
                rowDict["score"] = 0.0
                results.append(rowDict)
            return results
        except Exception as e:
            logger.error(f"Failed filter-only search for chat {chatId}: {e}")
            return []

    ###
    # Semantic mode
    ###
    async def _semanticSearch(
        self,
        chatId: int,
        queryEmbedding: List[float],
        *,
        limit: Optional[int],
        topK: int,
        userFilter: Optional[int],
        categoryFilter: Optional[Sequence[MessageCategory]],
        maxAgeDays: Optional[int],
        rootMessageId: Optional[MessageId],
        modelName: Optional[str],
        maxMessages: Optional[int],
        dataSource: Optional[str],
        threadId: Optional[int] = None,
        substring: Optional[str] = None,
    ) -> List[ChatMessageDict]:
        """Semantic search path used by :meth:`searchChatMessages`.

        Post-``migration_025`` contract (Decision D8 — numpy fully
        retired): vec0 (``vec_message_embeddings_{N}``) is the sole
        vector store on the message side. The legacy numpy fallback
        block is gone. Returns ``[]`` when vec0 is unavailable, raises,
        or yields no matches. There is no in-process fallback.

        The vec0 path resolves ``modelName`` to ``model_id`` internally
        via :meth:`_nativeVectorSearch` + the injected resolver.

        Args:
            chatId: Chat to search in.
            queryEmbedding: Query vector from the embedding model.
            limit: Max results to return after ranking. ``None`` means
                no cap.
            topK: How many candidates to consider before the final
                result-set trim.
            userFilter: Optional user ID to narrow search.
            categoryFilter: Optional message category filter.
            maxAgeDays: Only consider messages newer than N days.
            rootMessageId: Optional thread root to filter by.
            modelName: Embedding model name. When ``None``, semantic
                search returns ``[]`` (no resolution possible).
            maxMessages: Cap on how many embedding rows to consider.
            dataSource: Optional explicit data source.
            threadId: Optional thread/topic id filter (``0`` = main).
            substring: Optional case-insensitive substring; bound as
                ``%...%`` via ``getLikeComparison``.

        Returns:
            List of :class:`ChatMessageDict` with message content,
            user info, and ``score`` set to the cosine similarity.
            Empty list when vec0 is unavailable, raises, yields no
            matches, or when ``modelName`` is ``None``.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)

            # --- Native vector search (sole path post-migration_025) ---
            # vec0 is the only vector store on the message side. When
            # the provider does not support native vector search, the
            # vec0 lookup raises, or the result is empty, we return []
            # — there is no in-process fallback anymore (the numpy
            # cosine block was dropped with the ``message_embeddings``
            # BLOB side table; Decision D8).
            if not await sqlProvider.isVectorSearchSupported():
                logger.error(
                    "Semantic search for chat %s returning [] — vec0 not supported by provider",
                    chatId,
                )
                return []

            try:
                # Dimension is inferred from the query vector length,
                # avoiding dependency on model introspection APIs that
                # vary across embedding providers.
                dimension = len(queryEmbedding)
                nativeResults = await self._nativeVectorSearch(
                    sqlProvider=sqlProvider,
                    chatId=chatId,
                    queryEmbedding=queryEmbedding,
                    limit=limit,
                    topK=topK,
                    userFilter=userFilter,
                    categoryFilter=categoryFilter,
                    maxAgeDays=maxAgeDays,
                    rootMessageId=rootMessageId,
                    modelName=modelName,
                    maxMessages=maxMessages,
                    dimension=dimension,
                    dataSource=dataSource,
                    threadId=threadId,
                    substring=substring,
                )
            except Exception:
                logger.warning(
                    "Native vector search failed for chat %s; returning [] (no in-process fallback)",
                    chatId,
                    exc_info=True,
                )
                return []

            if not nativeResults:
                # Empty result — vec0 table empty / not yet created for
                # this dimension (pre-backfill). No fallback; just [].
                logger.debug(
                    "Native vector search returned no results for chat %s; returning []",
                    chatId,
                )
                return []

            return nativeResults
        except Exception as e:
            logger.error(f"Failed semantic search for chat {chatId}: {e}")
            return []

    async def _filterMessageIds(
        self,
        sqlProvider: BaseSQLProvider,
        chatId: int,
        candidateMessageIds: Sequence[MessageId],
        *,
        userFilter: Optional[int],
        categoryFilter: Optional[Sequence[MessageCategory]],
        maxAgeDays: Optional[int],
        rootMessageId: Optional[MessageId],
        threadId: Optional[int] = None,
        substring: Optional[str] = None,
    ) -> List[MessageId]:
        """Apply SQL filters to the candidate message-ID set.

        Returns the subset of ``candidateMessageIds`` that satisfy all
        supplied filters. An empty input produces an empty result
        without a round-trip to the DB.

        Args:
            sqlProvider: SQL provider to use.
            chatId: Chat identifier.
            candidateMessageIds: Candidate message ids to narrow.
            userFilter: Optional user id filter.
            categoryFilter: Optional message category filter.
            maxAgeDays: Optional age-in-days filter.
            rootMessageId: Optional thread root filter.
            threadId: Optional thread/topic id filter (``0`` = main).
            substring: Optional case-insensitive substring; bound as
                ``%...%`` via ``getLikeComparison``.

        Returns:
            Subset of ``candidateMessageIds`` passing all filters, in
            unspecified order.

        Note:
            Results are returned in unspecified order (deduplicated via
            set); callers must not rely on ordering.
        """
        if not candidateMessageIds:
            return []

        cutoffTs: Optional[datetime.datetime] = None
        if maxAgeDays is not None:
            cutoffTs = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=maxAgeDays)

        # Build static filter params once (reused by every batch)
        baseParams: dict = {
            "chatId": chatId,
            "userFilter": userFilter,
            "rootMessageId": rootMessageId.asStr() if rootMessageId is not None else None,
            "cutoffTs": cutoffTs,
            "threadId": threadId,
            "substring": f"%{substring}%" if substring else None,
        }
        if categoryFilter:
            for i, cat in enumerate(categoryFilter):
                baseParams[f"categoryFilter{i}"] = cat
            categoryPlaceholders = ", ".join(f":categoryFilter{i}" for i in range(len(categoryFilter)))
        else:
            categoryPlaceholders = ""

        # Compute safe per-batch ID count, leaving room for static + category params
        baseParamCount: int = len(baseParams.keys())
        perBatchCount: int = min(_MESSAGE_ID_FILTER_BATCH_SIZE, 32766 - baseParamCount)

        resultSet: set = set()
        for batchStart in range(0, len(candidateMessageIds), perBatchCount):
            batchIds = candidateMessageIds[batchStart : batchStart + perBatchCount]

            params: dict = dict(baseParams)
            placeholders: list = []
            for i, mid in enumerate(batchIds):
                key = f":mid{i}"
                placeholders.append(key)
                params[f"mid{i}"] = mid.asStr()

            midPlaceholders: str = ", ".join(placeholders)

            query: str = f"""
                SELECT c.message_id
                FROM chat_messages c
                WHERE c.chat_id = :chatId
                  AND c.message_id IN ({midPlaceholders})
                  AND (:userFilter IS NULL OR c.user_id = :userFilter)
                  AND (:rootMessageId IS NULL OR c.root_message_id = :rootMessageId)
                  AND (:threadId IS NULL OR c.thread_id = :threadId)
                  AND (:substring IS NULL OR {sqlProvider.getLikeComparison("c.message_text", "substring")})
                  AND (:cutoffTs IS NULL OR c.date > :cutoffTs)
            """
            if categoryFilter:
                query += f" AND (:categoryFilter0 IS NULL OR c.message_category IN ({categoryPlaceholders}))"

            rows = await sqlProvider.executeFetchAll(query, params)
            for row in rows:
                resultSet.add(MessageId(row["message_id"]))

        return list(resultSet)

    async def _fetchSearchResultRows(
        self,
        sqlProvider: BaseSQLProvider,
        chatId: int,
        topIds: Sequence[MessageId],
        topScores: Sequence[float],
        *,
        limit: Optional[int] = None,
    ) -> List[ChatMessageDict]:
        """Fetch full message+user rows for the top-K IDs and assemble results.

        The ``score`` list is expected to be in the same order as
        ``topIds``. When ``limit`` is provided, the result set is
        truncated to the first ``limit`` rows **after** the
        similarity-descending order has been re-established, so the
        user still gets the highest-scoring matches.
        """
        if not topIds:
            return []

        params: dict = {"chatId": chatId}
        placeholders: list = []
        for i, mid in enumerate(topIds):
            key = f":mid{i}"
            placeholders.append(key)
            params[f"mid{i}"] = mid.asStr()

        query = f"""
            SELECT c.*, u.username, u.full_name FROM chat_messages c
            JOIN chat_users u ON c.user_id = u.user_id AND c.chat_id = u.chat_id
            WHERE
                c.chat_id = :chatId
                AND c.message_id IN ({", ".join(placeholders)})
        """
        rows = await sqlProvider.executeFetchAll(query, params)

        scoreByMessageId: dict = {mid.asStr(): float(score) for mid, score in zip(topIds, topScores)}
        results: list = []
        for row in rows:
            rowDict = dbUtils.sqlToTypedDict(row, ChatMessageDict)
            mid = rowDict["message_id"]
            rowDict["score"] = scoreByMessageId.get(mid.asStr(), 0.0)
            results.append(rowDict)
        # Preserve the similarity-descending order from the caller.
        orderIndex = {mid.asStr(): i for i, mid in enumerate(topIds)}
        results.sort(key=lambda r: orderIndex.get(r["message_id"].asStr(), 0))
        if limit is not None:
            results = results[: int(limit)]
        return results

    ###
    # Native vector search path
    ###
    async def _nativeVectorSearch(
        self,
        sqlProvider: BaseSQLProvider,
        chatId: int,
        queryEmbedding: List[float],
        *,
        limit: Optional[int],
        topK: int,
        userFilter: Optional[int],
        categoryFilter: Optional[Sequence[MessageCategory]],
        maxAgeDays: Optional[int],
        rootMessageId: Optional[MessageId],
        modelName: Optional[str],
        maxMessages: Optional[int],
        dimension: int,
        dataSource: Optional[str] = None,
        threadId: Optional[int] = None,
        substring: Optional[str] = None,
    ) -> List[ChatMessageDict]:
        """Semantic search using the provider's native vec0 vector search.

        Pushes the cosine distance computation into the database engine,
        avoiding loading all embeddings into Python memory. The vec0
        partition-key filter is ``(chat_id, model_id)`` — the
        ``model_id`` integer is resolved from ``modelName`` (and the
        query vector's dimension) via the injected resolver (Decision
        D10 + Decision D6 extended).

        When ``modelName`` is ``None`` the method short-circuits to
        ``[]`` (no resolution possible). When vec0 raises or returns
        ``[]`` (table missing or empty), the result is ``[]`` and the
        :meth:`_semanticSearch` caller logs + returns ``[]`` (there is
        no in-process fallback post-``migration_025``).

        The approach:
         1. Resolve ``modelId`` from ``(modelName, dimension)`` via the
            injected resolver.
         2. If ``maxMessages`` is set, compute ``minDate`` by querying
            the date of the Nth most recent ``chat_messages`` row
            carrying that ``model_id`` (single-table query — the legacy
            ``message_embeddings`` JOIN is gone post-``migration_025``).
         3. Call ``sqlProvider.vectorSearch()`` with the partition-key
            filter (chatId, modelId) and optionally
            ``date >= :minDate`` to cap the candidate pool to the
            ``maxMessages`` most recent messages.
         4. Apply user/category/age/thread post-filters via
            :meth:`_filterMessageIds`.
         5. Convert distances to similarity scores and re-rank
            descending.
         6. Fetch full message rows via :meth:`_fetchSearchResultRows`.

        Args:
            sqlProvider: The SQL provider (must have
                ``isVectorSearchSupported() == True``).
            chatId: Chat to search in.
            queryEmbedding: Query vector as ``list[float]``.
            limit: Max results after ranking. ``None`` means no cap.
            topK: How many nearest neighbours to retrieve.
            userFilter: Optional user ID filter.
            categoryFilter: Optional category filter.
            maxAgeDays: Only messages newer than N days.
            rootMessageId: Optional thread root filter.
            modelName: Embedding model name. When ``None``, returns
                ``[]`` immediately (no resolution possible).
            maxMessages: If set, limit candidates to the N most recent
                messages by date. Applied as a pre-filter via
                ``date >= :minDate`` in the vec0 MATCH query.
            dimension: Embedding dimension (e.g. 384, 1024). Used to
                construct the vec0 table name
                ``f"vec_message_embeddings_{dimension}"`` and to resolve
                the ``model_id`` via the injected resolver.
            dataSource: Optional explicit data source forwarded to the
                injected resolver for multi-source routing on the
                ``model_id`` lookup.
            threadId: Optional thread/topic id filter (``0`` = main).
            substring: Optional case-insensitive substring; bound as
                ``%...%`` via ``getLikeComparison``.

        Returns:
            List of :class:`ChatMessageDict` with ``score`` set to the
            cosine similarity (``1.0 - distance``). Returns ``[]`` when
            ``modelName`` is ``None``, the query vector has near-zero
            norm, vec0 returns no matches, or post-filters remove every
            candidate.
        """
        if modelName is None:
            return []

        # Resolve ``model_id`` via the injected resolver (Decisions
        # D6 extended + D10). Handler callers keep passing the model
        # name string; resolution to ``model_id`` is the repo's job.
        modelId = await self._resolveModelId(modelName, dimension, dataSource=dataSource)

        # Guard against zero or near-zero query vectors — cosine distance
        # is undefined and the results would be arbitrary noise. Uses
        # ``math.sqrt`` (pure Python) instead of ``numpy.linalg.norm``
        # — numpy is fully retired from this file (Decision D8).
        queryNorm = math.sqrt(sum(x * x for x in queryEmbedding))
        if queryNorm < 1e-8:
            logger.warning(
                "Query embedding has near-zero norm (%s) for chat %s; " "semantic search results will be arbitrary",
                queryNorm,
                chatId,
            )
            return []

        queryVectorBytes: bytes = array.array("f", queryEmbedding).tobytes()

        # Build the vec0 MATCH filter. The partition-key filter
        # (chat_id, model_id) is always present so the engine only
        # scans rows belonging to the active chat / model pair. The
        # ``model_id`` integer is the partition key post-migration_025
        # (it replaced the legacy ``model TEXT`` partition key).
        filterParts: list[str] = ["chat_id = :chatId AND model_id = :modelId"]
        filterParams: dict[str, str | int | float | None] = {
            "chatId": chatId,
            "modelId": modelId,
        }

        # Option B pre-filter: enforce the ``maxMessages`` cap by
        # pushing a ``date >= :minDate`` constraint into the vec0 query.
        # The cutoff is the date of the Nth most recent message in
        # ``chat_messages`` filtered by ``model_id`` — a single-table
        # query (the legacy ``message_embeddings`` JOIN was dropped in
        # ``migration_025``).
        if maxMessages is not None:
            cutoffQuery = (
                "SELECT message_id, date FROM chat_messages "
                "WHERE chat_id = :chatId AND model_id = :modelId "
                "ORDER BY date DESC, message_id DESC"
            )
            cutoffQuery = sqlProvider.applyPagination(cutoffQuery, limit=1, offset=maxMessages - 1)
            cutoffRow = await sqlProvider.executeFetchOne(cutoffQuery, {"chatId": chatId, "modelId": modelId})
            if cutoffRow is not None:
                # Compound filter: exclude messages strictly before the
                # cutoff, and messages equal to the cutoff but with
                # earlier message_id. Mirrors ``ORDER BY date DESC,
                # message_id DESC`` semantics so messages sharing the
                # cutoff timestamp do not leak into / out of the pool.
                filterParts.append("(date > :minDate OR (date = :minDate AND message_id >= :minMessageId))")
                filterParams["minDate"] = cutoffRow["date"]
                filterParams["minMessageId"] = cutoffRow["message_id"]

        vecTable = f"vec_message_embeddings_{dimension}"

        vecResults = await sqlProvider.vectorSearch(
            table=vecTable,
            vectorColumn="embedding",
            returnColumns=["message_id", "date"],
            queryVector=queryVectorBytes,
            k=topK,
            filterClause=" AND ".join(filterParts),
            filterParams=filterParams,
            distanceMetric=VectorDistanceMetric.COSINE,
        )

        if not vecResults:
            return []

        # Convert to MessageId + similarity score. sqlite-vec cosine
        # distance = 1.0 - cosine_similarity, so similarity = 1.0 - distance.
        candidateIds: list[MessageId] = []
        scoreByMessageId: dict[str, float] = {}
        for vr in vecResults:
            mid = MessageId(vr["rowKey"]["message_id"])
            candidateIds.append(mid)
            scoreByMessageId[mid.asStr()] = 1.0 - vr["distance"]

        # Apply post-filters (user, category, age, thread). These span
        # ``chat_messages`` (not the vec0 table), so they are applied as
        # a post-filter reusing the existing battle-tested batch logic.
        needsPostFilter: bool = (
            userFilter is not None
            or categoryFilter is not None
            or maxAgeDays is not None
            or rootMessageId is not None
            or threadId is not None
            or substring is not None
        )
        if needsPostFilter:
            candidateIds = await self._filterMessageIds(
                sqlProvider=sqlProvider,
                chatId=chatId,
                candidateMessageIds=candidateIds,
                userFilter=userFilter,
                categoryFilter=categoryFilter,
                maxAgeDays=maxAgeDays,
                rootMessageId=rootMessageId,
                threadId=threadId,
                substring=substring,
            )
            if not candidateIds:
                return []

        # Re-order by similarity descending (best match first).
        candidateIds.sort(
            key=lambda mid: scoreByMessageId.get(mid.asStr(), 0.0),
            reverse=True,
        )

        # Trim to top-K after filtering. Typically a no-op because
        # vectorSearch was called with k=topK and post-filters can only
        # remove elements; kept for defensive consistency.
        topIds = candidateIds[:topK]
        topScores = [scoreByMessageId.get(mid.asStr(), 0.0) for mid in topIds]

        return await self._fetchSearchResultRows(
            sqlProvider=sqlProvider,
            chatId=chatId,
            topIds=topIds,
            topScores=topScores,
            limit=limit,
        )
