"""Repository for chat message search (filter-only and semantic).

This module provides the :class:`ChatSearchRepository` class which
unifies the two chat-message search modes that previously lived across
:mod:`chat_messages` and :mod:`chat_embeddings`:

- **Filter-only mode** (``queryEmbedding is None``): the SQL filter
  path that applies ``userFilter`` / ``categoryFilter`` / ``maxAgeDays``
  / ``rootMessageId`` directly against ``chat_messages`` joined to
  ``chat_users``, ordered by ``date`` descending.
- **Semantic mode** (``queryEmbedding is not None``): loads
  ``message_embeddings`` rows for the chat, applies the same SQL
  pre-filters to the candidate set, computes cosine similarity against
  ``queryEmbedding`` via ``numpy``, and returns the top-K messages
  ranked by similarity descending.

The public :meth:`ChatSearchRepository.searchChatMessages` dispatcher
selects the mode at runtime. This replaces the prior
cross-repository back-reference between ``ChatMessagesRepository`` and
``ChatEmbeddingsRepository`` (``ChatMessagesRepository._embeddingsRepo``,
wired by ``Database.__init__``) and consolidates the search surface
into a single, cohesive repository that has all the methods it needs
in-process.
"""

import array
import datetime
import logging
from collections.abc import Sequence
from typing import Any, List, Optional

import numpy as np

from internal.models import MessageId

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import ChatMessageDict, MessageCategory
from .base import BaseRepository

logger = logging.getLogger(__name__)


class ChatSearchRepository(BaseRepository):
    """Unified chat-message search across ``chat_messages`` and ``message_embeddings``.

    The repository owns both the filter-only SQL path and the semantic
    (embedding-based cosine-similarity) path, plus the private helpers
    (``_loadEmbeddingsFromDb``, ``_filterMessageIds``,
    ``_fetchSearchResultRows``) that the semantic path composes. The
    embedding CRUD itself (``saveMessageEmbedding``,
    ``getMessageEmbedding``, ``deleteChatEmbeddings``,
    ``getMessagesWithoutEmbeddings``) lives in
    :class:`ChatEmbeddingsRepository` — this repository only consumes
    embeddings, it does not own their lifecycle.

    Caching of decoded embeddings belongs in the handler layer
    (via :class:`CacheService`). The repository always re-reads
    ``message_embeddings`` BLOB rows on every semantic-mode call,
    pre-filtered by ``modelName`` to keep the result set bounded by the
    active model.
    """

    __slots__ = ()

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialize the chat search repository.

        Args:
            manager: Database manager instance for provider access.
        """
        super().__init__(manager)

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
    ) -> List[ChatMessageDict]:
        """Search chat messages, with optional semantic ranking.

        Two modes:

        - **Semantic mode** (``queryEmbedding`` provided): loads
          ``message_embeddings`` rows for the chat (filtered by
          ``modelName``), applies the SQL pre-filters over the
          candidate set, computes cosine similarity against
          ``queryEmbedding`` via ``numpy``, and returns the top-K
          messages ranked by similarity descending.
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
            modelName: Embedding model name to filter by when loading
                from ``message_embeddings``. Required for semantic mode
                (the caller resolves the active model via the
                ``EMBEDDING_MODEL`` chat setting).
            maxMessages: Cap on how many embedding rows to load for
                this chat. Defaults to ``None`` (no cap). Honours the
                ``MAX_MESSAGES_FOR_SEMANTIC_SEARCH`` chat setting when
                passed through by the caller.
            dataSource: Optional explicit data source.

        Returns:
            List of :class:`ChatMessageDict` with message content,
            user info, and the optional ``score`` field populated.
            In filter-only mode the ``score`` field is ``0.0`` (no
            ranking applied); in semantic mode it is the cosine
            similarity against ``queryEmbedding``.

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
            f"dataSource={dataSource}, hasQueryEmbedding={queryEmbedding is not None}"
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
    ) -> List[ChatMessageDict]:
        """Filter-only search path used by :meth:`searchChatMessages`.

        Applies the supplied SQL filters directly against
        ``chat_messages`` joined to ``chat_users``, ordered by ``date``
        descending. No vector ranking. The ``score`` field is always
        ``0.0``.

        ``limit`` follows the cross-RDBMS ``applyPagination`` contract:
        ``None`` means "no cap" (no ``LIMIT`` clause is appended), and
        an ``int`` means "cap to N rows".
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
            }
            categoryPlaceholders: list = []
            if categoryFilter is not None:
                for i, category in enumerate(categoryFilter):
                    categoryPlaceholders.append(f":categoryFilter{i}")
                    params[f"categoryFilter{i}"] = str(category)

            categoryClause = ""
            if categoryFilter is not None:
                categoryClause = f"OR c.message_category IN ({', '.join(categoryPlaceholders)})"

            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            query = f"""
                SELECT c.*, u.username, u.full_name FROM chat_messages c
                JOIN chat_users u ON c.user_id = u.user_id AND c.chat_id = u.chat_id
                WHERE
                    c.chat_id = :chatId
                    AND (:userFilter     IS NULL OR c.user_id = :userFilter)
                    AND (:rootMessageId  IS NULL OR c.root_message_id = :rootMessageId)
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
    ) -> List[ChatMessageDict]:
        """Semantic search path used by :meth:`searchChatMessages`.

        1. Load all embeddings for the chat from ``message_embeddings``
           (filtered by the active model).
        2. Apply pre-filters (``userFilter``, ``categoryFilter``,
           ``maxAgeDays``, ``rootMessageId``) over the loaded
           ``messageIds`` to produce a small candidate set.
        3. Compute cosine similarity using ``numpy`` over the candidate
           matrix, take the top-K.
        4. Fetch full message data for the top-K and return as
           :class:`ChatMessageDict` (with the ``score`` field populated)
           sorted by similarity descending.

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
            modelName: Embedding model name to filter by when loading
                from ``message_embeddings``. Required for semantic mode.
            maxMessages: Cap on how many embedding rows to load.
            dataSource: Optional explicit data source.

        Returns:
            List of :class:`ChatMessageDict` with message content,
            user info, and ``score`` set to the cosine similarity.
            Empty list on failure.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)

            # 1. Always load embeddings fresh from the DB. The repository
            #    no longer maintains an in-memory cache — callers (e.g.
            #    ChatSearchHandler) own the caching layer via CacheService.
            embeddingList, messageIds = await self._loadEmbeddingsFromDb(
                sqlProvider=sqlProvider,
                chatId=chatId,
                modelName=modelName,
                maxMessages=maxMessages,
            )

            if not embeddingList or not messageIds:
                return []

            # 2. Build the candidate set via SQL pre-filter on message_id.
            candidateMessageIds = await self._filterMessageIds(
                sqlProvider=sqlProvider,
                chatId=chatId,
                candidateMessageIds=messageIds,
                userFilter=userFilter,
                categoryFilter=categoryFilter,
                maxAgeDays=maxAgeDays,
                rootMessageId=rootMessageId,
            )
            if not candidateMessageIds:
                return []

            # Map candidate MessageId -> row index in the cached embedding list.
            idToIndex: dict = {mid.asStr(): i for i, mid in enumerate(messageIds)}
            candidateIndices: list = []
            candidateIdsOrdered: list = []
            for mid in candidateMessageIds:
                idx = idToIndex.get(mid.asStr())
                if idx is not None:
                    candidateIndices.append(idx)
                    candidateIdsOrdered.append(mid)
            if not candidateIndices:
                return []

            # 3. Cosine similarity over the candidate rows.
            queryVec = np.asarray(queryEmbedding, dtype=np.float32)
            candidateMatrix = np.asarray([embeddingList[i] for i in candidateIndices], dtype=np.float32)
            queryVecNorm = np.linalg.norm(queryVec)
            if queryVecNorm < 1e-8:
                logger.warning(
                    f"Query embedding has near-zero norm ({queryVecNorm}) for chat {chatId}; "
                    f"semantic search results will be arbitrary"
                )
            queryNorm = queryVec / (queryVecNorm or 1.0)
            rowNorms = np.linalg.norm(candidateMatrix, axis=1, keepdims=True)
            rowNorms[rowNorms == 0.0] = 1.0  # avoid div-by-zero for zero-vectors
            normalizedMatrix = candidateMatrix / rowNorms
            similarities = normalizedMatrix @ queryNorm

            # Pick top-K by similarity (argpartition is O(N), faster than full sort).
            k = min(int(topK), similarities.shape[0])
            topPartition = np.argpartition(-similarities, k - 1)[:k] if k > 0 else np.array([], dtype=np.int64)
            # Order the partition by similarity descending for stable results.
            topPartition = topPartition[np.argsort(-similarities[topPartition])]
            topIds = [candidateIdsOrdered[int(i)] for i in topPartition]
            topScores = [float(similarities[int(i)]) for i in topPartition]

            # 4. Fetch full message data for the top-K and assemble results.
            return await self._fetchSearchResultRows(
                sqlProvider=sqlProvider,
                chatId=chatId,
                topIds=topIds,
                topScores=topScores,
                limit=limit,
            )
        except Exception as e:
            logger.error(f"Failed semantic search for chat {chatId}: {e}")
            return []

    async def _loadEmbeddingsFromDb(
        self,
        sqlProvider: Any,
        chatId: int,
        modelName: Optional[str],
        maxMessages: Optional[int],
    ) -> tuple:
        """Load all embeddings for ``chatId`` filtered by ``modelName``.

        Args:
            sqlProvider: SQL provider to use.
            chatId: Chat identifier.
            modelName: Model name to filter by. When ``None``, returns
                immediately with empty lists (semantic search requires
                a resolved model).
            maxMessages: Optional cap on rows loaded. ``None`` means no
                cap.

        Returns:
            Tuple ``(embeddingList, messageIds)`` where ``embeddingList``
            is a list of ``list[float]`` vectors and ``messageIds`` is
            a list of :class:`MessageId` aligned 1:1 with
            ``embeddingList``. Both are empty on failure or when
            ``modelName`` is ``None``.
        """
        if modelName is None:
            return [], []

        query = """
            SELECT me.message_id, me.embedding, me.dimensions
            FROM message_embeddings me
            WHERE me.chat_id = :chatId AND me.model = :modelName
            ORDER BY me.message_id DESC
        """
        params: dict = {"chatId": chatId, "modelName": modelName}
        if maxMessages is not None:
            query = sqlProvider.applyPagination(query=query, limit=int(maxMessages))

        rows = await sqlProvider.executeFetchAll(query, params)
        embeddingList: list = []
        messageIds: list = []
        for row in rows:
            try:
                vec = list(array.array("f", row["embedding"]))
            except Exception as e:  # malformed BLOB - log and skip
                logger.warning(
                    f"Skipping malformed embedding BLOB for message {row['message_id']} " f"in chat {chatId}: {e}"
                )
                continue
            if len(vec) != row["dimensions"]:
                logger.warning(
                    f"Skipping embedding with mismatched dimensions for message "
                    f"{row['message_id']} in chat {chatId}: "
                    f"expected {row['dimensions']}, got {len(vec)}"
                )
                continue
            embeddingList.append(vec)
            messageIds.append(MessageId(row["message_id"]))
        return embeddingList, messageIds

    async def _filterMessageIds(
        self,
        sqlProvider: Any,
        chatId: int,
        candidateMessageIds: Sequence[MessageId],
        *,
        userFilter: Optional[int],
        categoryFilter: Optional[Sequence[MessageCategory]],
        maxAgeDays: Optional[int],
        rootMessageId: Optional[MessageId],
    ) -> List[MessageId]:
        """Apply SQL filters to the candidate message-ID set.

        Returns the subset of ``candidateMessageIds`` that satisfy all
        supplied filters. An empty input produces an empty result
        without a round-trip to the DB.
        """
        if not candidateMessageIds:
            return []

        cutoffTs: Optional[datetime.datetime] = None
        if maxAgeDays is not None:
            cutoffTs = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=maxAgeDays)

        params: dict = {
            "chatId": chatId,
            "userFilter": userFilter,
            "rootMessageId": rootMessageId.asStr() if rootMessageId is not None else None,
            "cutoffTs": cutoffTs,
            "categoryFilter": None if categoryFilter is None else True,
        }
        placeholders: list = []
        for i, mid in enumerate(candidateMessageIds):
            key = f":mid{i}"
            placeholders.append(key)
            params[f"mid{i}"] = mid.asStr()
        if categoryFilter is not None:
            for i, category in enumerate(categoryFilter):
                params[f"categoryFilter{i}"] = str(category)

        categoryClause = ""
        if categoryFilter is not None:
            categoryPlaceholders = [f":categoryFilter{i}" for i in range(len(categoryFilter))]
            categoryClause = f"OR c.message_category IN ({', '.join(categoryPlaceholders)})"

        query = f"""
            SELECT c.message_id FROM chat_messages c
            WHERE
                c.chat_id = :chatId
                AND c.message_id IN ({", ".join(placeholders)})
                AND (:userFilter    IS NULL OR c.user_id = :userFilter)
                AND (:rootMessageId IS NULL OR c.root_message_id = :rootMessageId)
                AND (:cutoffTs      IS NULL OR c.date > :cutoffTs)
                AND (:categoryFilter IS NULL {categoryClause})
        """
        rows = await sqlProvider.executeFetchAll(query, params)
        return [MessageId(row["message_id"]) for row in rows]

    async def _fetchSearchResultRows(
        self,
        sqlProvider: Any,
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
