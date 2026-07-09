"""Repository for the unified ``user_memories`` store.

This module owns all database operations on the ``user_memories`` table
introduced by ``migration_020_user_memories``: durable per-(chat, user,
thread) facts, preferences, events, relationships, and high-level bio
notes about a user — the unified store that retires the legacy
``user_data`` key-value table and the rolling-bio JSON blob.

The repository covers the full lifecycle:
- Relational CRUD (``addMemory`` / ``updateMemory`` / ``deleteMemory`` /
  ``getPermanentMemories`` / ``getLatestMemories``).
- Unified search (``searchMemories``) — filter-only (``queryEmbedding
  is None``) and semantic (vec0 native) modes.
- Embedding persistence (``saveMemoryEmbedding`` /
  ``deleteMemoryEmbedding``) via a lazily-created ``vec_user_memories_{dim}``
  virtual table (mirrors ``chat_embeddings._upsertVecMessageEmbedding``).
- Embedding model-drift regeneration helpers
  (``getMemoriesWithoutEmbeddings`` /
  ``deleteObsoleteMemoryEmbeddings``).

**Key difference from chat-history search:** there is NO BLOB
``user_memory_embeddings`` table. Embeddings live ONLY in the vec0
virtual table; ``embedding_model``/``embedding_dimensions`` are tracked
on ``user_memories`` itself. Semantic search is therefore vec0-only
(no numpy fallback) — when vec0 is unavailable, ``searchMemories``
returns ``[]``.

Repository conventions (mirror ``chat_embeddings.py`` /
``chat_search.py``):
- Method parameters are camelCase (AGENTS.md); the ``UserMemoryDict``
  keys are snake_case to match DB columns so the universal converter
  ``dbUtils.sqlToTypedDict`` maps them directly.
- All SQL goes through ``BaseSQLProvider`` (``execute`` /
  ``executeFetchAll`` / ``applyPagination``); never raw ``sqlite3``.
- Reads decode via ``dbUtils.sqlToTypedDict(row, UserMemoryDict)`` — no
  custom ``_rowToDict`` helper.
- Timestamps are passed as timezone-aware ``datetime`` objects (mirrors
  ``chat_embeddings.saveMessageEmbedding``); the sqlite3 driver
  serialises them consistently so ``ORDER BY updated_at`` and
  ``created_at < :cutoff`` comparisons stay correct.
- ``tags`` is serialised via ``json.dumps`` on write and parsed back by
  the converter on read.
"""

import array
import json
import logging
import re
from typing import List, Optional

import numpy

from internal.database.constants import (
    BACKFILL_DEFAULT_BATCH_SIZE,
    EPHEMERAL_RETRIEVAL_LIMIT,
    MEMORY_SEARCH_DEFAULT_LIMIT,
    MEMORY_SEARCH_TOPK_MULTIPLIER,
    PERMANENT_INJECTION_CAP,
)
from internal.database.models import UserMemoryDict, UserMemorySource

from .. import utils as dbUtils
from ..providers.base import (
    BaseSQLProvider,
    VectorColumnType,
    VectorDistanceMetric,
)
from .base import BaseRepository

logger = logging.getLogger(__name__)

_SELECT_COLUMNS: str = (
    "chat_id, user_id, thread_id, memory_id, type, content, tags, "
    "permanent, source, embedding_model, embedding_dimensions, "
    "created_at, updated_at"
)
"""Column list selected by every read method so ``sqlToTypedDict`` sees all required keys."""


def _normalizeTags(tags: Optional[List[str]]) -> Optional[List[str]]:
    """Normalise tags to lowercase, drop '"' and remove duplicates."""
    if not tags:
        return tags
    return list(set([tag.lower().replace('"', "") for tag in tags]))


class UserMemoriesRepository(BaseRepository):
    """Repository for the unified ``user_memories`` store.

    Provides the full memory lifecycle: relational CRUD, unified search
    (filter-only + semantic vec0), embedding persistence via the lazily
    created ``vec_user_memories_{dim}`` virtual table, and model-drift
    regeneration helpers. Mirrors the ``chat_embeddings`` /
    ``chat_search`` split but adapted for the single-store model
    (no BLOB table — vec0 is the sole embedding store).
    """

    __slots__ = ()
    """Restricts instance attributes to prevent dynamic attribute creation."""

    ###
    # Writes
    ###
    async def addMemory(
        self,
        chatId: int,
        userId: int,
        memoryId: str,
        *,
        threadId: Optional[int] = None,
        type: str,
        content: str,
        tags: List[str],
        permanent: bool,
        source: UserMemorySource,
        embedding: Optional[List[float]],
        embeddingModel: Optional[str],
    ) -> None:
        """INSERT a new memory row.

        Timestamps are set application-side (never via a DB default — see
        AGENTS.md SQL portability). ``tags`` is JSON-serialised;
        ``permanent`` is stored as 0/1 (boolean-as-int).

        Args:
            chatId: Chat the memory belongs to.
            userId: User the memory is about.
            memoryId: App-generated UUID hex; must be unique within
                (chatId, userId). Caller is responsible for generating it.
            threadId: Thread scope; ``None`` for cross-thread permanent memories.
            type: ``MemoryType`` string value (bio|preference|fact|event|relationship).
            content: Free-text memory body.
            tags: List of freeform tag strings (stored as JSON TEXT).
            permanent: True for always-injected memories, False for ephemeral.
            source: Provenance — refinement | chat | migration | user.

        Returns:
            None

        Raises:
            Exception: Re-raised on PK conflict or any DB error (caller
                ensures ULID uniqueness).

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        now = dbUtils.getCurrentTimestamp()
        sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
        # We insert embedding_model and embedding_dimensions as
        # NULL to ensure they are filled ONLY IF vec0 insert were successfull
        # This way we'll be sure, that we have embedding with given model\dimensions
        await sqlProvider.execute(
            """
            INSERT INTO user_memories
                (chat_id, user_id, thread_id, memory_id, type, content, tags,
                 permanent, source, embedding_model, embedding_dimensions,
                 created_at, updated_at)
            VALUES
                (:chatId, :userId, :threadId, :memoryId, :type, :content, :tags,
                 :permanent, :source, NULL, NULL,
                 :createdAt, :updatedAt)
            """,
            {
                "chatId": chatId,
                "userId": userId,
                "threadId": threadId,
                "memoryId": memoryId,
                "type": type,
                "content": content,
                "tags": _normalizeTags(tags),
                "permanent": 1 if permanent else 0,
                "source": source,
                "createdAt": now,
                "updatedAt": now,
            },
        )

        if embedding is not None and embeddingModel is not None:
            await self.saveMemoryEmbedding(
                chatId=chatId,
                userId=userId,
                memoryId=memoryId,
                embedding=embedding,
                embeddingModel=embeddingModel,
            )

    async def updateMemory(
        self,
        chatId: int,
        userId: int,
        memoryId: str,
        *,
        content: Optional[str] = None,
        tags: Optional[List[str]] = None,
        type: Optional[str] = None,
        embedding: Optional[List[float]] = None,
        embeddingModel: Optional[str] = None,
    ) -> bool:
        """PATCH selected columns; bump ``updated_at``.

        Only the columns whose argument is not ``None`` are written. When
        every argument is ``None`` the call is a no-op and returns
        ``False`` (nothing to update). ``updated_at`` is always bumped
        when at least one column changes.

        Content updates invalidate the embedding: the stored vec0 vector
        was derived from the OLD content, so it is stale after a content
        change. When ``content`` is provided, this method resets
        ``embedding_model``/``embedding_dimensions`` to ``NULL`` AND
        drops the stale vec0 row (best-effort, never raises over it), so
        :meth:`getMemoriesWithoutEmbeddings` re-surfaces the memory for
        re-embedding on the new content. Regen only re-embeds on model
        drift, NOT content drift — so the invalidation here is the sole
        trigger that keeps embeddings in sync with content edits.

        Args:
            chatId: Chat the memory belongs to.
            userId: User the memory is about.
            memoryId: Memory identifier to update.
            content: New content body, or ``None`` to leave unchanged.
            tags: New tag list, or ``None`` to leave unchanged.
            type: New ``MemoryType`` value, or ``None`` to leave unchanged.

        Returns:
            True if a matching row existed (and was therefore updated),
            False if no row matched (chatId, userId, memoryId) or if
            nothing was requested.

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        if content is None and tags is None and type is None:
            return False

        sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

        # The provider's execute() returns None, so check existence to
        # report whether a row was actually updated.
        existing = await sqlProvider.executeFetchOne(
            """
            SELECT 1 FROM user_memories
            WHERE
                chat_id = :chatId AND
                user_id = :userId AND
                memory_id = :memoryId
            """,
            {"chatId": chatId, "userId": userId, "memoryId": memoryId},
        )
        if existing is None:
            return False

        setClauses: List[str] = []
        params: dict[str, object] = {
            "chatId": chatId,
            "userId": userId,
            "memoryId": memoryId,
            "updatedAt": dbUtils.getCurrentTimestamp(),
        }
        if content is not None:
            setClauses.append("content = :content")
            # Drop model\dimension as embedding need to be updated in vec0 first
            setClauses.append("embedding_model = NULL")
            setClauses.append("embedding_dimensions = NULL")
            params["content"] = content
        if tags is not None:
            setClauses.append("tags = :tags")
            params["tags"] = _normalizeTags(tags)
        if type is not None:
            setClauses.append("type = :type")
            params["type"] = type
        setClauses.append("updated_at = :updatedAt")

        await sqlProvider.execute(
            f"""
            UPDATE user_memories
            SET {', '.join(setClauses)}
            WHERE chat_id = :chatId AND user_id = :userId AND memory_id = :memoryId
            """,
            params,
        )

        # Content change → embedding is stale.
        # Drop the stale vec0 row so the regen cron
        # (getMemoriesWithoutEmbeddings) re-embeds on the NEW content.
        # Never raise from this cleanup: the content update already
        # succeeded; an embedding-invalidation failure must not undo it
        # (the row will be re-embedded on the next drift pass).
        if content is not None:
            try:
                if not embedding or not embeddingModel:
                    await self.deleteMemoryEmbedding(chatId, userId, memoryId, vecOnly=True)
                else:
                    await self.saveMemoryEmbedding(chatId, userId, memoryId, embedding, embeddingModel)
            except Exception:
                logger.error(
                    "Failed to delete stale vec0 row after content update for memory %s chat %d",
                    memoryId,
                    chatId,
                    exc_info=True,
                )

        return True

    async def deleteMemory(
        self,
        chatId: int,
        userId: int,
        memoryId: str,
    ) -> bool:
        """DELETE one memory row.

        Unrestricted — an explicit by-id delete MAY target a permanent
        memory. The vec0 embedding row cleanup (best-effort) runs via
        :meth:`deleteMemoryEmbedding`.

        An existence pre-check (companion SELECT) drives the return
        value, mirroring :meth:`updateMemory`: a re-delete of an
        already-gone ``memory_id`` returns ``False`` rather than
        ``True``. Never raises — on any DB error the exception is
        logged and ``False`` is returned.

        Args:
            chatId: Chat the memory belongs to.
            userId: User the memory is about.
            memoryId: Memory identifier to delete.

        Returns:
            True if a row was deleted, False if no row matched or on
            error.

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

            # Existence pre-check: the provider's execute() returns None,
            # so a companion SELECT is the only way to tell "deleted one
            # row" from "matched zero rows" (mirrors updateMemory). A
            # re-delete of an already-gone memory_id must return False.
            existing = await sqlProvider.executeFetchOne(
                """
                SELECT 1 FROM user_memories
                WHERE
                    chat_id = :chatId AND
                    user_id = :userId AND
                    memory_id = :memoryId
                """,
                {"chatId": chatId, "userId": userId, "memoryId": memoryId},
            )
            if existing is None:
                return False

            await sqlProvider.execute(
                """
                DELETE FROM user_memories
                WHERE
                    chat_id = :chatId AND
                    user_id = :userId AND
                    memory_id = :memoryId
                """,
                {"chatId": chatId, "userId": userId, "memoryId": memoryId},
            )

            await self.deleteMemoryEmbedding(chatId, userId, memoryId, vecOnly=True)
            return True
        except Exception:
            logger.error(
                "Failed to delete memory %s chat %d",
                memoryId,
                chatId,
                exc_info=True,
            )
            return False

    ###
    # Reads
    ###
    async def getPermanentMemories(
        self,
        chatId: int,
        userId: int,
        threadId: int,
        *,
        limit: int = PERMANENT_INJECTION_CAP,
        dataSource: Optional[str] = None,
    ) -> List[UserMemoryDict]:
        """Return permanent memories for the thread, newest-updated-first, capped.

        Returns BOTH cross-thread permanent (``thread_id IS NULL`` — e.g.
        ``user_data``-migrated facts) AND this-thread permanent
        (``thread_id = :threadId`` — e.g. the thread's bio). Bio memories
        are thread-scoped per Backfill B, so a thread's permanent block
        must include the thread's own bio alongside cross-thread facts.

        Args:
            chatId: Chat the memories belong to.
            userId: User the memories are about.
            threadId: Active thread (the caller passes
                ``DEFAULT_THREAD_ID`` for the main thread).
            limit: Maximum rows to return.
            dataSource: Optional data source name for explicit routing.

        Returns:
            List of :class:`UserMemoryDict` ordered by ``updated_at`` desc.
        """
        sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
        query = f"""
            SELECT {_SELECT_COLUMNS}
            FROM user_memories
            WHERE
                chat_id = :chatId AND
                user_id = :userId AND
                permanent = 1 AND
                (thread_id IS NULL OR thread_id = :threadId)
            ORDER BY updated_at DESC
        """
        query = sqlProvider.applyPagination(query=query, limit=limit, offset=0)
        rows = await sqlProvider.executeFetchAll(
            query,
            {"chatId": chatId, "userId": userId, "threadId": threadId},
        )
        return [dbUtils.sqlToTypedDict(row, UserMemoryDict) for row in rows]

    async def getLatestMemories(
        self,
        chatId: int,
        userId: int,
        threadId: int,
        *,
        limit: int = EPHEMERAL_RETRIEVAL_LIMIT,
        dataSource: Optional[str] = None,
    ) -> List[UserMemoryDict]:
        """Return newest-updated EPHEMERAL memories scoped to (chatId, userId, threadId), capped.

        Ephemeral-only (``permanent = 0``): the sole consumer is the
        "Recent:" injection block (Phase 3). Permanent memories are
        served by their own accessor (:meth:`getPermanentMemories`) and
        must NOT also appear here — otherwise a thread-scoped permanent
        bio would render twice.

        Args:
            chatId: Chat the memories belong to.
            userId: User the memories are about.
            threadId: Active thread (the caller passes
                ``DEFAULT_THREAD_ID`` for the main thread).
            limit: Maximum rows to return.
            dataSource: Optional data source name for explicit routing.

        Returns:
            List of :class:`UserMemoryDict` (``permanent = 0`` only)
            ordered by ``updated_at`` desc.
        """
        sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
        query = f"""
            SELECT {_SELECT_COLUMNS}
            FROM user_memories
            WHERE
                chat_id = :chatId AND
                user_id = :userId AND
                thread_id = :threadId AND
                permanent = 0
            ORDER BY updated_at DESC
        """
        query = sqlProvider.applyPagination(query=query, limit=limit, offset=0)
        rows = await sqlProvider.executeFetchAll(
            query,
            {"chatId": chatId, "userId": userId, "threadId": threadId},
        )
        return [dbUtils.sqlToTypedDict(row, UserMemoryDict) for row in rows]

    async def getMemory(
        self,
        chatId: int,
        userId: int,
        memoryId: str,
        *,
        dataSource: Optional[str] = None,
    ) -> Optional[UserMemoryDict]:
        """Return a single memory row selected by the full primary key.

        Single-row read used by the ``/knowledge_config`` per-memory detail
        view. Unrestricted by ``permanent`` / ``thread_id`` — the caller
        (the wizard) already knows the ``(chatId, userId)`` scope, so this
        only needs the explicit ``memoryId`` to fetch the row.

        Args:
            chatId: Chat the memory belongs to.
            userId: User the memory is about.
            memoryId: Memory identifier to fetch.
            dataSource: Optional data source name for explicit routing.

        Returns:
            The matching :class:`UserMemoryDict`, or ``None`` when no row
            matches the full ``(chatId, userId, memoryId)`` key.
        """
        sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
        row = await sqlProvider.executeFetchOne(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM user_memories
            WHERE
                chat_id = :chatId AND
                user_id = :userId AND
                memory_id = :memoryId
            """,
            {"chatId": chatId, "userId": userId, "memoryId": memoryId},
        )
        if row is None:
            return None
        return dbUtils.sqlToTypedDict(row, UserMemoryDict)

    async def getDistinctTags(
        self,
        chatId: int,
        userId: int,
        memoryType: Optional[str] = None,
        *,
        dataSource: Optional[str] = None,
    ) -> List[str]:
        """Return the sorted set of distinct tag strings across a user's memories.

        Fetches every ``tags`` JSON column for ``(chatId, userId)`` (optionally
        narrowed by ``type``), parses each row's JSON list, and collects unique
        tag strings. Used by the ``/knowledge_config`` wizard's tag-filter
        picker (Phase 5b) so the user can only pick tags they actually use.

        All Tags are lowercased.

        Args:
            chatId: Chat the memories belong to.
            userId: User the memories are about.
            memoryType: Optional ``MemoryType`` value filter. When ``None``,
                tags from memories of ALL types are collected.
            dataSource: Optional data source name for explicit routing.

        Returns:
            Sorted list of distinct tag strings. Empty list on error or when
            no tags exist. Never raises.
        """
        try:
            params: dict[str, object] = {
                "chatId": chatId,
                "userId": userId,
                "memoryType": memoryType,
            }

            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            rows = await sqlProvider.executeFetchAll(
                """
                SELECT tags FROM user_memories
                WHERE
                    chat_id = :chatId AND
                    user_id = :userId AND
                    (:memoryType IS NULL OR type = :memoryType)
                """,
                params,
            )
            distinctTags: set[str] = set()
            for row in rows:
                # Raw fetch (no sqlToTypedDict) → tags is the stored JSON TEXT.
                # Guard against NULL / missing column defensively.
                rawTags = row["tags"] if "tags" in row.keys() else None
                if not rawTags:
                    continue
                try:
                    parsed = json.loads(rawTags)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if isinstance(parsed, list):
                    for tag in parsed:
                        if isinstance(tag, str) and tag:
                            distinctTags.add(tag)
                else:
                    logger.error(f"in Row {row}, tags isn't json list, but a {type(parsed)}")
            return sorted(distinctTags)
        except Exception:
            logger.error(
                "Failed to fetch distinct tags for chat %d user %d",
                chatId,
                userId,
                exc_info=True,
            )
            return []

    async def searchMemories(
        self,
        chatId: int,
        userId: int,
        queryEmbedding: Optional[List[float]] = None,
        *,
        threadId: Optional[int] = None,
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        permanent: Optional[bool] = None,
        limit: int = MEMORY_SEARCH_DEFAULT_LIMIT,
        embeddingModel: Optional[str],  # TODO: Add default = None after fixing all callers
        offset: int = 0,
        dataSource: Optional[str] = None,
    ) -> List[UserMemoryDict]:
        """Unified memory search with filter-only and semantic modes.

        Two modes (mirror ``ChatSearchRepository.searchChatMessages`` at
        ``chat_search.py:167-189``):

        - **Filter-only mode** (``queryEmbedding is None``): a plain SQL
          scan of ``user_memories`` with optional ``threadId`` / ``type``
          / ``tags`` / ``permanent`` filters, ordered by ``updated_at``
          descending. Every result row gets ``score = 0.0`` after
          conversion (mirror ``chat_search.py:256``).
        - **Semantic mode** (``queryEmbedding`` is a ``List[float]``):
          native vec0 search over ``vec_user_memories_{dim}``, JOIN back to
          ``user_memories`` by ``memory_id``; ``score = 1.0 - distance``
          (mirror ``chat_search.py:785``). Returns ``[]`` (never raises)
          when vec0 is unsupported or the vec0 table is absent.

        Scoping: always filters ``chat_id = :chatId AND user_id =
        :userId`` — no cross-user/cross-chat leaks. The ``tags`` filter
        is applied as a Python set-intersection post-fetch (ANY-match)
        because JSON-in-SQL ``LIKE`` is non-portable and breaks on tags
        containing ``"`` / ``%`` / ``_`` (plan §6.2). In semantic mode
        ``threadId`` and ``type`` are applied in the JOIN step on the
        authoritative ``user_memories`` columns (the denormalised vec0
        ``type``/``thread_id`` columns go stale after ``updateMemory``).

        Thread scoping: ``threadId is None`` returns memories from ALL
        threads for ``(chatId, userId)`` (no thread filter) — this is the
        mode the ``/knowledge_config`` wizard uses. When ``threadId`` is
        provided, results are restricted to that thread.

        Pagination: ``offset`` is forwarded to
        :meth:`BaseSQLProvider.applyPagination` in both modes. In
        filter-only mode the SQL scan is paginated directly; in semantic
        mode the offset applies to the final ranked result list (the
        vec0 ``k`` is sized as ``limit * MEMORY_SEARCH_TOPK_MULTIPLIER``
        and the trim happens after ranking, so a large ``offset`` does
        not starve the candidate pool).

        Args:
            chatId: Chat to search in.
            userId: User whose memories are searched.
            queryEmbedding: Pre-computed query vector as a ``List[float]``.
                When ``None``, runs filter-only mode. When a non-empty
                list (and ``embeddingModel`` is set), runs semantic mode.
                Serialised to float32 bytes internally by the vec0 layer.
            threadId: Optional thread scope filter. When ``None``, NO
                thread filter is applied (all threads, including the
                cross-thread ``NULL`` ones, are returned).
            type: Optional ``MemoryType`` value filter.
            tags: Optional list of tag strings; a memory matches when it
                carries ANY of the listed tags.
            permanent: Optional permanent-flag filter.
            limit: Maximum results to return.
            embeddingModel: Name of the embedding model that produced
                ``queryEmbedding``. Required for semantic mode (the vec0
                table is partitioned by model); when ``None``, filter-only
                mode runs regardless of ``queryEmbedding``.
            offset: Number of leading results to skip (pagination).
            dataSource: Optional data source name for explicit routing.

        Returns:
            List of :class:`UserMemoryDict` with the ``score`` field
            populated on every row (``0.0`` in filter-only mode;
            ``1.0 - cosine_distance`` in semantic mode). Empty list on
            failure or when semantic search is unavailable.
        """
        if queryEmbedding is None or embeddingModel is None:
            return await self._filterOnlySearchMemories(
                chatId=chatId,
                userId=userId,
                threadId=threadId,
                type=type,
                tags=tags,
                permanent=permanent,
                limit=limit,
                offset=offset,
                dataSource=dataSource,
            )
        return await self._semanticSearchMemories(
            chatId=chatId,
            userId=userId,
            queryEmbedding=queryEmbedding,
            threadId=threadId,
            type=type,
            tags=tags,
            permanent=permanent,
            limit=limit,
            embeddingModel=embeddingModel,
            offset=offset,
            dataSource=dataSource,
        )

    async def _filterOnlySearchMemories(
        self,
        chatId: int,
        userId: int,
        *,
        threadId: Optional[int],
        type: Optional[str],
        tags: Optional[List[str]],
        permanent: Optional[bool],
        limit: int,
        offset: int = 0,
        dataSource: Optional[str] = None,
    ) -> List[UserMemoryDict]:
        """Filter-only search path (no vector ranking). Every row gets ``score = 0.0``.

        Args:
            chatId: Chat to search in.
            userId: User whose memories are searched.
            threadId: Optional thread scope filter. ``None`` applies NO
                thread filter (all threads, including ``NULL`` cross-thread).
            type: Optional ``MemoryType`` value filter.
            tags: Optional list of tag strings.
            permanent: Optional permanent-flag filter.
            limit: Maximum results to return.
            offset: Number of leading results to skip (pagination).
            dataSource: Optional data source name for explicit routing.

        Returns:
            List of :class:`UserMemoryDict` with ``score = 0.0``.
        """
        try:
            params: dict[str, object] = {
                "chatId": chatId,
                "userId": userId,
                "threadId": threadId,
                "type": type,
                "permanent": permanent,
            }
            tagsWhereList = []

            if tags:
                normalizedTags = _normalizeTags(tags)
                assert normalizedTags is not None
                for i, tag in enumerate(normalizedTags):
                    params[f"tags{i}"] = f'%"{tag}"%'
                    tagsWhereList.append(f"tags LIKE :tags{i}")

            tagsWhereStr = ""
            if tagsWhereList:
                tagsWhereStr = f" AND ( {' OR '.join(tagsWhereList)} )"

            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            query = f"""
                SELECT {_SELECT_COLUMNS}
                FROM user_memories
                WHERE
                    chat_id = :chatId AND
                    user_id = :userId AND
                    (:threadId IS NULL OR thread_id = :threadId) AND
                    (:type IS NULL OR type = :type) AND
                    (:permanent IS NULL OR permanent = :permanent)
                    {tagsWhereStr}
                ORDER BY updated_at DESC
            """
            query = sqlProvider.applyPagination(query=query, limit=limit, offset=offset)
            rows = await sqlProvider.executeFetchAll(query, params)
            results: List[UserMemoryDict] = []
            for row in rows:
                rowDict = dbUtils.sqlToTypedDict(row, UserMemoryDict)
                rowDict["score"] = 0.0
                results.append(rowDict)

            return results
        except Exception:
            logger.error(
                "Failed filter-only memory search for chat %d user %d",
                chatId,
                userId,
                exc_info=True,
            )
            return []

    async def _semanticSearchMemories(
        self,
        chatId: int,
        userId: int,
        queryEmbedding: List[float],
        *,
        threadId: Optional[int],
        type: Optional[str],
        tags: Optional[List[str]],
        permanent: Optional[bool],
        limit: int,
        embeddingModel: str,
        offset: int = 0,
        dataSource: Optional[str] = None,
    ) -> List[UserMemoryDict]:
        """Semantic search path via native vec0 vector search.

        Mirrors ``ChatSearchRepository._nativeVectorSearch``
        (``chat_search.py:638-823``) but adapted for the single-store
        model: vec0 ``returnColumns`` is just ``["memory_id"]``, then a
        JOIN query fetches full ``user_memories`` rows by id with
        post-filters (``threadId``, ``type``, ``tags``).

        Args:
            chatId: Chat to search in.
            userId: User whose memories are searched.
            queryEmbedding: Query vector as a ``List[float]`` (serialised
                to float32 bytes internally).
            threadId: Optional thread scope post-filter (JOIN step).
            type: Optional ``MemoryType`` value filter, applied in the
                JOIN step on the authoritative ``user_memories.type``
                column (NOT pushed into vec0 — the vec0 denormalised
                ``type`` column goes stale after ``updateMemory(type=...)``).
            tags: Optional list of tag strings (ANY-match via Python
                set-intersection post-fetch — see module note on tags).
            permanent: Optional permanent-flag filter (applied in vec0;
                ``permanent`` is immutable post-creation so it is never
                stale in the denormalised vec0 row).
            limit: Maximum results to return after ranking.
            embeddingModel: Name of the embedding model that produced
                ``queryEmbedding`` (selects the model-partitioned vec0
                table).
            offset: Number of leading ranked results to skip
                (pagination; applied AFTER ranking and trimming).
            dataSource: Optional data source name for explicit routing.

        Returns:
            List of :class:`UserMemoryDict` ranked by similarity
            descending with ``score = 1.0 - cosine_distance``. Empty
            list when vec0 is unsupported, the table is absent, or no
            matches are found.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            if not await sqlProvider.isVectorSearchSupported():
                logger.debug(
                    "Semantic memory search requested for chat %d but vec0 is unsupported; returning []",
                    chatId,
                )
                return []

            # Guard against zero or near-zero query vectors — cosine distance
            # is undefined and the results would be arbitrary noise.
            queryNorm = float(numpy.linalg.norm(numpy.asarray(queryEmbedding, dtype=numpy.float32)))
            if queryNorm < 1e-8:
                logger.warning(
                    "Query embedding has near-zero norm (%s) for chat %s; " "semantic search results will be arbitrary",
                    queryNorm,
                    chatId,
                )
                return []

            queryVectorBytes: bytes = array.array("f", queryEmbedding).tobytes()

            dim = len(queryEmbedding)
            if dim <= 0:
                logger.warning(
                    "Invalid embedding dimension %d for chat %d semantic memory search; returning []",
                    dim,
                    chatId,
                )
                return []

            tableName = f"vec_user_memories_{dim}"
            existingTables = await sqlProvider.listTables(tableName)
            if tableName not in existingTables:
                logger.debug(
                    "vec0 table %s does not exist for chat %d; semantic memory search returns []",
                    tableName,
                    chatId,
                )
                return []

            # vec0 filter clause: keep it minimal. Only the mandatory
            # scoping (chat_id, user_id) and ``permanent`` (immutable
            # post-creation → never stale in vec0) are safe to push in.
            # ``type`` is NOT pushed into vec0: the denormalised vec0
            # ``type`` column goes stale after ``updateMemory(type=...)``,
            # so it is applied in the JOIN step on the authoritative
            # ``user_memories.type`` column instead. ``threadId`` is
            # NULL-able and ``tags`` is JSON TEXT; both are also applied
            # in the JOIN / Python step below.
            filterParts: List[str] = [
                "chat_id = :chatId",
                "user_id = :userId",
                "model = :modelName",
            ]
            filterParams: dict[str, str | int | float | None] = {
                "chatId": chatId,
                "userId": userId,
                "modelName": embeddingModel,
            }
            if permanent is not None:
                filterParts.append("permanent = :permanent")
                filterParams["permanent"] = 1 if permanent else 0

            vecResults = await sqlProvider.vectorSearch(
                table=tableName,
                vectorColumn="embedding",
                returnColumns=["memory_id"],
                queryVector=queryVectorBytes,
                k=limit * MEMORY_SEARCH_TOPK_MULTIPLIER,
                filterClause=" AND ".join(filterParts),
                filterParams=filterParams,
                distanceMetric=VectorDistanceMetric.COSINE,
            )
            if not vecResults:
                return []

            # Map memory_id -> similarity score (1.0 - cosine distance).
            scoreByMemoryId: dict[str, float] = {}
            for vr in vecResults:
                mid = vr["rowKey"].get("memory_id")
                if mid is not None:
                    scoreByMemoryId[mid] = 1.0 - vr["distance"]

            if not scoreByMemoryId:
                return []

            # JOIN step: fetch full user_memories rows by memory_id,
            # applying the SQL-safe post-filters (``threadId``, ``type``)
            # on the AUTHORITATIVE user_memories columns. ``tags`` is
            # applied as a Python set-intersection post-fetch (JSON-in-SQL
            # LIKE is non-portable — see plan §6.2). The vec0 over-fetch
            # (``MEMORY_SEARCH_TOPK_MULTIPLIER``) absorbs the trimming.
            placeholders: List[str] = []
            fetchParams: dict[str, object] = {
                "chatId": chatId,
                "userId": userId,
                "threadId": threadId,
                "type": type,
            }

            tagsWhereList: List[str] = []
            if tags:
                normalizedTags = _normalizeTags(tags)
                assert normalizedTags is not None
                for i, tag in enumerate(normalizedTags):
                    filterParams[f"tags{i}"] = f'%"{tag}"%'
                    tagsWhereList.append(f"tags LIKE :tags{i}")

            tagsWhereStr = ""
            if tagsWhereList:
                tagsWhereStr = "AND (" + " OR ".join(tagsWhereList) + ")"

            for i, mid in enumerate(scoreByMemoryId):
                key = f"mid{i}"
                placeholders.append(f":{key}")
                fetchParams[key] = mid
            query = f"""
                SELECT {_SELECT_COLUMNS}
                FROM user_memories
                WHERE
                    chat_id = :chatId AND
                    user_id = :userId AND
                    memory_id IN ({', '.join(placeholders)}) AND
                    (:threadId IS NULL OR thread_id = :threadId) AND
                    (:type IS NULL OR type = :type)
                    {tagsWhereStr}
            """
            rows = await sqlProvider.executeFetchAll(query, fetchParams)

            results: List[UserMemoryDict] = []
            for row in rows:
                rowDict = dbUtils.sqlToTypedDict(row, UserMemoryDict)
                mid = rowDict["memory_id"]
                rowDict["score"] = scoreByMemoryId.get(mid, 0.0)
                results.append(rowDict)

            # Re-rank by similarity descending and trim to limit.
            results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
            return results[offset : offset + limit]
        except Exception:
            logger.error(
                "Failed semantic memory search for chat %d user %d",
                chatId,
                userId,
                exc_info=True,
            )
            return []

    ###
    # Embedding persistence (vec0-only — no BLOB table)
    ###
    async def saveMemoryEmbedding(
        self,
        chatId: int,
        userId: int,
        memoryId: str,
        embedding: List[float],
        embeddingModel: str,
    ) -> bool:
        """Persist a memory embedding: upsert vec0.

        Args:
            chatId: Chat the memory belongs to.
            userId: User the memory is about.
            memoryId: Memory identifier.
            embedding: Float vector (any length; becomes the dimension).
            model: Model name that produced the embedding.

        Returns:
            True on success, False on any failure (never raises).

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

            # Fetch the memory row to populate vec0 metadata columns
            # (thread_id, permanent, type) that the vec0 table carries.
            memoryRow = await sqlProvider.executeFetchOne(
                """
                SELECT thread_id, permanent, type
                FROM user_memories
                WHERE
                    chat_id = :chatId AND
                    user_id = :userId AND
                    memory_id = :memoryId
                """,
                {"chatId": chatId, "userId": userId, "memoryId": memoryId},
            )
            if memoryRow is None:
                logger.warning(
                    "Cannot save embedding: memory %s not found for chat %d user %d",
                    memoryId,
                    chatId,
                    userId,
                )
                return False

            # vec0 write — must succeed BEFORE provenance is set. A
            # failure is already logged inside _upsertVecMemoryEmbedding;
            # here we swallow it and return False WITHOUT running the
            # provenance UPDATE, leaving embedding_model = NULL so the
            # regen cron retries. Vec0 is the sole embedding store.
            try:
                if not await self._upsertVecMemoryEmbedding(
                    sqlProvider=sqlProvider,
                    chatId=chatId,
                    userId=userId,
                    memoryId=memoryId,
                    threadId=memoryRow["thread_id"],
                    permanent=memoryRow["permanent"],
                    memoryType=memoryRow["type"],
                    embedding=embedding,
                    embeddingModel=embeddingModel,
                ):
                    return False
            except Exception:
                return False

            await sqlProvider.execute(
                """
                UPDATE user_memories
                SET
                    embedding_model = :modelName,
                    embedding_dimensions = :dimensions,
                    updated_at = :updatedAt
                WHERE
                    chat_id = :chatId AND
                    user_id = :userId AND
                    memory_id = :memoryId
                """,
                {
                    "chatId": chatId,
                    "userId": userId,
                    "memoryId": memoryId,
                    "modelName": embeddingModel,
                    "dimensions": len(embedding),
                    "updatedAt": dbUtils.getCurrentTimestamp(),
                },
            )

            return True
        except Exception:
            logger.error(
                "Failed to save memory embedding for memory %s in chat %d",
                memoryId,
                chatId,
                exc_info=True,
            )
            return False

    async def _upsertVecMemoryEmbedding(
        self,
        sqlProvider: BaseSQLProvider,
        chatId: int,
        userId: int,
        memoryId: str,
        threadId: Optional[int],
        permanent: bool,
        memoryType: str,
        embeddingModel: str,
        embedding: list[float],
    ) -> bool:
        """Upsert a row into the dimension-specific vec0 memory table.

        Lazily creates ``vec_user_memories_{dimensions}`` on first use
        via :meth:`BaseSQLProvider.createVectorTable`. Uses DELETE +
        INSERT because vec0 does not support conventional UPSERT on
        metadata columns. Write failures are logged and the method
        returns ``False`` so the caller (:meth:`saveMemoryEmbedding`)
        can skip the provenance UPDATE and leave ``embedding_model =
        NULL`` — that keeps the memory visible to
        :meth:`getMemoriesWithoutEmbeddings` for re-embedding (vec0 is
        the sole embedding store; a silent failure would strand the
        memory with no searchable vector).

        Args:
            sqlProvider: SQL provider abstraction (must be writable and
                support vector search).
            chatId: Chat ID.
            userId: User ID.
            memoryId: Memory identifier.
            threadId: Thread scope (may be ``None`` for cross-thread).
            permanent: Permanent flag as int (0/1).
            memoryType: ``MemoryType`` string value.
            embedding: Float vector (``list[float]``; serialised to
                float32 bytes internally).

        Returns:
            ``True`` on success, ``False`` when vec0 is unsupported or
            the vec0 DELETE/INSERT (or lazy table creation) fails. The
            failure is logged at error with ``exc_info`` before
            returning ``False``; the caller must check the return value
            rather than relying on an exception.
        """
        dimensions = len(embedding)
        embeddingBytes = array.array("f", embedding).tobytes()
        tableName = f"vec_user_memories_{dimensions}"

        if not await sqlProvider.isVectorSearchSupported():
            return False

        try:
            # Lazy table creation — check the catalog first.
            existingTables = await sqlProvider.listTables(tableName)
            if tableName not in existingTables:
                await sqlProvider.createVectorTable(
                    tableName,
                    [
                        {"name": "memory_id", "columnType": VectorColumnType.TEXT},
                        {"name": "chat_id", "columnType": VectorColumnType.INTEGER, "isPartitionKey": True},
                        {"name": "user_id", "columnType": VectorColumnType.INTEGER, "isPartitionKey": True},
                        {"name": "model", "columnType": VectorColumnType.TEXT, "isPartitionKey": True},
                        {"name": "thread_id", "columnType": VectorColumnType.INTEGER},
                        {"name": "permanent", "columnType": VectorColumnType.INTEGER},
                        {"name": "type", "columnType": VectorColumnType.TEXT},
                        {
                            "name": "embedding",
                            "columnType": VectorColumnType.VECTOR,
                            "vectorDimension": dimensions,
                            "distanceMetric": VectorDistanceMetric.COSINE,
                        },
                    ],
                )

            # TODO: Test on latest sqlite-vec and leave only one way.
            # vec0 DELETE-by-metadata: try the metadata DELETE first; on
            # failure fall back to a rowid-based delete (some sqlite-vec
            # builds restrict WHERE predicates to partition keys only).
            try:
                await sqlProvider.execute(
                    f"DELETE FROM {tableName} "
                    f"WHERE chat_id = :chatId AND user_id = :userId AND memory_id = :memoryId",
                    {"chatId": chatId, "userId": userId, "memoryId": memoryId},
                )
            except Exception:
                row = await sqlProvider.executeFetchOne(
                    f"SELECT rowid FROM {tableName} "
                    f"WHERE chat_id = :chatId AND user_id = :userId AND memory_id = :memoryId",
                    {"chatId": chatId, "userId": userId, "memoryId": memoryId},
                )
                if row is not None:
                    await sqlProvider.execute(
                        f"DELETE FROM {tableName} WHERE rowid = :rowid",
                        {"rowid": row["rowid"]},
                    )

            await sqlProvider.execute(
                f"INSERT INTO {tableName} "
                f"(memory_id, chat_id, user_id, model, thread_id, permanent, type, embedding) "
                f"VALUES (:memoryId, :chatId, :userId, :modelName, :threadId, :permanent, :type, :embedding)",
                {
                    "memoryId": memoryId,
                    "chatId": chatId,
                    "userId": userId,
                    "modelName": embeddingModel,
                    "threadId": threadId,
                    "permanent": permanent,
                    "type": memoryType,
                    "embedding": embeddingBytes,
                },
            )
        except Exception:
            logger.error(
                "Failed to upsert vec0 memory embedding for chat %s memory %s",
                chatId,
                memoryId,
                exc_info=True,
            )
            return False
        return True

    async def deleteMemoryEmbedding(
        self,
        chatId: int,
        userId: int,
        memoryId: str,
        vecOnly: bool = False,
    ) -> bool:
        """Best-effort DELETE of a memory's vec0 embedding row. Never raises.

        Iterates every ``vec_user_memories_{N}`` table found via
        ``listTables`` and deletes the row matching the memory_id. When
        no vec0 table exists, the call is a no-op and returns ``True``.

        Args:
            chatId: Chat the memory belongs to.
            userId: User the memory is about.
            memoryId: Memory identifier.
            vecOnly: When ``True``, skip the ``user_memories``
                provenance-column reset (``embedding_model`` /
                ``embedding_dimensions``) and only delete vec0 rows.
                Used by :meth:`deleteMemory` /
                :meth:`updateMemory`, which manage the relational row
                themselves. When ``False`` (default), the provenance
                columns are also nulled and ``updated_at`` bumped.

        Returns:
            True if a vec0 row was deleted OR no vec0 table existed
            (nothing to clean). False when tables existed but the
            memory_id was not found in any of them.

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

            if not vecOnly:
                await sqlProvider.execute(
                    """
                    UPDATE user_memories
                    SET
                        embedding_model = NULL,
                        embedding_dimensions = NULL,
                        updated_at = :updatedAt
                    WHERE
                        chat_id = :chatId AND
                        user_id = :userId AND
                        memory_id = :memoryId
                    """,
                    {
                        "chatId": chatId,
                        "userId": userId,
                        "memoryId": memoryId,
                        "updatedAt": dbUtils.getCurrentTimestamp(),
                    },
                )

            if not await sqlProvider.isVectorSearchSupported():
                return True

            vecTables = await sqlProvider.listTables("vec_user_memories_%")
            # Filter out vec0 shadow tables (_info, _chunks, etc.).
            vecTables = [t for t in vecTables if re.match(r"^vec_user_memories_\d+$", t)]
            if not vecTables:
                return True

            # deletedAny drives the bool return: True ONLY when a vec0 row
            # was actually deleted (Phase 1b Gate 1 fix — restored after the
            # refactor regressed it). A vec0 table that exists but holds no
            # row for this memory_id returns False.
            deletedAny = False
            for table in vecTables:
                # Companion SELECT to compute the bool return.
                existing = await sqlProvider.executeFetchOne(
                    f"SELECT 1 FROM {table} "
                    f"WHERE chat_id = :chatId AND user_id = :userId AND memory_id = :memoryId",
                    {"chatId": chatId, "userId": userId, "memoryId": memoryId},
                )
                if existing is not None:
                    try:
                        await sqlProvider.execute(
                            f"DELETE FROM {table} "
                            f"WHERE chat_id = :chatId AND user_id = :userId AND memory_id = :memoryId",
                            {"chatId": chatId, "userId": userId, "memoryId": memoryId},
                        )
                        deletedAny = True
                    except Exception:
                        # Fallback to rowid-based delete for builds that
                        # restrict WHERE predicates to partition keys.
                        row = await sqlProvider.executeFetchOne(
                            f"SELECT rowid FROM {table} "
                            f"WHERE chat_id = :chatId AND user_id = :userId AND memory_id = :memoryId",
                            {"chatId": chatId, "userId": userId, "memoryId": memoryId},
                        )
                        if row is not None:
                            await sqlProvider.execute(
                                f"DELETE FROM {table} WHERE rowid = :rowid",
                                {"rowid": row["rowid"]},
                            )
                            deletedAny = True
            return deletedAny
        except Exception:
            logger.error(
                "Failed to delete memory embedding for memory %s in chat %d",
                memoryId,
                chatId,
                exc_info=True,
            )
            return False

    ###
    # Embedding model-drift regeneration
    ###
    async def getMemoriesWithoutEmbeddings(
        self,
        chatId: int,
        *,
        limit: int = BACKFILL_DEFAULT_BATCH_SIZE,
        modelName: Optional[str] = None,
        dimensions: Optional[int] = None,
        dataSource: Optional[str] = None,
    ) -> List[UserMemoryDict]:
        """Return memories whose embedding is stale or absent.

        Single-table stale-detection (simpler than the chat-history
        analog — no vec0 JOIN): model/dimensions live on the
        ``user_memories`` row. A ``NULL`` ``embedding_model``
        (never-embedded memory) also surfaces here, so this same query
        serves the initial backfill.

        Per-chat, model-only (no ``userId``) and dimension-agnostic:
        dimension-mismatch detection relies on
        :meth:`deleteObsoleteMemoryEmbeddings` running first in the
        regen sequence (it resets ``embedding_model``/``embedding_dimensions``
        to ``NULL`` for stale-dimension rows, which this method then
        surfaces). This matches the ``chat_embeddings`` precedent.

        Args:
            chatId: Chat to scan.
            limit: Maximum number of rows to return.
            modelName: Current embedding model name. Rows whose
                ``embedding_model`` is ``NULL`` OR differs from this
                value are returned. When ``None``, only never-embedded
                rows (``embedding_model IS NULL``) are returned.
            dimensions: Currently-active embedding dimensionality; rows
                whose ``embedding_dimensions`` differs are returned. When
                ``None``, the dimension check is omitted.
            dataSource: Optional data source name for explicit routing.

        Returns:
            List of :class:`UserMemoryDict` ordered by ``updated_at``
            descending. Empty list on error.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            query = f"""
                    SELECT {_SELECT_COLUMNS}
                    FROM user_memories
                    WHERE
                        chat_id = :chatId AND
                        (
                            (embedding_model IS NULL OR
                                (:modelName IS NOT NULL AND embedding_model != :modelName)
                            ) OR
                            (embedding_dimensions IS NULL OR
                                (:dimensions IS NOT NULL AND embedding_dimensions != :dimensions)
                            )
                        )
                    ORDER BY updated_at DESC
                """
            params = {
                "chatId": chatId,
                "modelName": modelName,
                "dimensions": dimensions,
            }
            query = sqlProvider.applyPagination(query=query, limit=limit, offset=0)
            rows = await sqlProvider.executeFetchAll(query, params)
            return [dbUtils.sqlToTypedDict(row, UserMemoryDict) for row in rows]
        except Exception:
            logger.error(
                "Failed to list memories without embeddings for chat %d",
                chatId,
                exc_info=True,
            )
            return []

    async def deleteObsoleteMemoryEmbeddings(
        self,
        chatId: int,
        currentModel: str,
        currentDimensions: Optional[int],
    ) -> int:
        """Reset embedding provenance for memories whose model/dimensions are stale.

        Finds memories where ``embedding_model IS NOT NULL AND
        (embedding_model != currentModel OR embedding_dimensions !=
        currentDimensions)``, deletes their vec0 rows, then sets
        ``embedding_model = NULL`` and ``embedding_dimensions = NULL`` on
        those ``user_memories`` rows so :meth:`getMemoriesWithoutEmbeddings`
        picks them up for re-embedding on the next regeneration tick.

        Mirrors ``deleteObsoleteModelEmbeddings``
        (``chat_embeddings.py:337-464``) but single-store (no BLOB table
        to clean — only vec0 + the provenance columns). The provenance
        column reset is what distinguishes this method from the
        chat-history analog: there is no BLOB table, so the vec0 DELETE
        alone would leave ``embedding_model`` set and the regen cron's
        :meth:`getMemoriesWithoutEmbeddings` would never re-surface the
        stale rows.

        ``currentDimensions`` accepts ``None`` for embedding models that
        do not expose a dimension count (e.g. plain OpenAI-style models
        whose ``getDimensions()`` returns ``None``). In that case the
        stale-row predicate collapses to model-name-only (the dimensions
        clause is omitted rather than relying on SQL three-valued
        ``!= NULL`` semantics — explicit branching mirrors the
        chat-history analog for readability/portability).

        Args:
            chatId: Chat to clean.
            currentModel: The currently-active embedding model name.
            currentDimensions: The currently-active embedding
                dimensionality, or ``None`` when the model does not
                expose dimensions (dim-less cleanup on model name only).

        Returns:
            The count of reset rows. ``0`` when no rows were stale OR
            on any internal error (never raises; the exception is
            logged).

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

            # Delete their vec0 rows from every vec_user_memories_{N} table.
            if await sqlProvider.isVectorSearchSupported():
                try:
                    vecTables = await sqlProvider.listTables("vec_user_memories_%")
                    vecTables = [t for t in vecTables if re.match(r"^vec_user_memories_\d+$", t)]
                    for table in vecTables:
                        tableDim: Optional[int] = None
                        if currentDimensions is not None:
                            try:
                                tableDim = int(table.rsplit("_", 1)[-1])
                            except (ValueError, IndexError):
                                # Defensive: skip tables with non-numeric suffixes
                                # (shouldn't happen after the regex filter above).
                                continue
                        if tableDim == currentDimensions or currentDimensions is None:
                            await sqlProvider.execute(
                                f"DELETE FROM {table} WHERE chat_id = :chatId AND model != :currentModel",
                                {"chatId": chatId, "currentModel": currentModel},
                            )
                        # If the table dimension does not match the current dimension,
                        # delete all rows from the table for given chatId.
                        else:
                            await sqlProvider.execute(
                                f"DELETE FROM {table} WHERE chat_id = :chatId",
                                {"chatId": chatId},
                            )

                except NotImplementedError:
                    logger.debug(
                        "listTables not supported for chat %d; skipping vec0 cleanup",
                        chatId,
                    )

            # Build the stale-row predicate ONCE — used by both the
            # COUNT and the UPDATE so they stay in lockstep. Explicit
            # branching on currentDimensions mirrors chat_embeddings.py
            # (avoids relying on SQL three-valued != NULL semantics).
            # Only rows that HAVE been embedded (embedding_model IS NOT
            # NULL) are candidates — never-embedded rows are already
            # NULL and already surfaced by getMemoriesWithoutEmbeddings.
            if currentDimensions is not None:
                staleWhere = (
                    "chat_id = :chatId AND embedding_model IS NOT NULL "
                    "AND (embedding_model != :currentModel OR embedding_dimensions != :currentDimensions)"
                )
                staleParams: dict[str, object] = {
                    "chatId": chatId,
                    "currentModel": currentModel,
                    "currentDimensions": currentDimensions,
                }
            else:
                staleWhere = "chat_id = :chatId AND embedding_model IS NOT NULL " "AND embedding_model != :currentModel"
                staleParams = {
                    "chatId": chatId,
                    "currentModel": currentModel,
                }

            # Count the stale rows BEFORE cleanup so the caller knows how
            # many were reset (the provider's execute() returns None, so
            # the UPDATE's affected-row count is not directly available).
            countRow = await sqlProvider.executeFetchOne(
                f"SELECT COUNT(*) AS cnt FROM user_memories WHERE {staleWhere}",
                staleParams,
            )
            resetCount = int(countRow["cnt"]) if countRow is not None else 0

            # Reset provenance columns on user_memories. THIS is the step
            # that re-surfaces stale rows for re-embedding: without it,
            # getMemoriesWithoutEmbeddings (which keys on
            # embedding_model IS NULL / != modelName) would never see
            # these rows again — the regen cron's stale-detection loop
            # would be broken.
            await sqlProvider.execute(
                f"UPDATE user_memories SET embedding_model = NULL, embedding_dimensions = NULL WHERE {staleWhere}",
                staleParams,
            )

            return resetCount
        except Exception:
            logger.error(
                "Failed to delete obsolete memory embeddings for chat %d (current model %s)",
                chatId,
                currentModel,
                exc_info=True,
            )
            return 0
