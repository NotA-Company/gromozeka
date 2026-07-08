"""Repository for the unified ``user_memories`` store.

This module owns all database operations on the ``user_memories`` table
introduced by ``migration_020_user_memories``: durable per-(chat, user,
thread) facts, preferences, events, relationships, and high-level bio
notes about a user — the unified store that retires the legacy
``user_data`` key-value table and the rolling-bio JSON blob.

The repository covers the full lifecycle:
- Relational CRUD (``addMemory`` / ``updateMemory`` / ``deleteMemory`` /
  ``deleteMemoriesByQuery`` / ``getPermanentMemories`` /
  ``getLatestMemories``).
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
import datetime
import json
import logging
import re
from typing import List, NotRequired, Optional, TypedDict

import lib.utils as libUtils

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..providers.base import (
    BaseSQLProvider,
    VectorColumnType,
    VectorDistanceMetric,
)
from .base import BaseRepository

logger = logging.getLogger(__name__)

PERMANENT_INJECTION_CAP: int = 10
"""Max permanent memories injected per (chat, user) into a chat turn's system block."""

EPHEMERAL_RETRIEVAL_LIMIT: int = 5
"""Default cap on ephemeral (non-permanent) memories retrieved per chat turn."""

MEMORY_SEARCH_DEFAULT_LIMIT: int = 20
"""Default result cap for :meth:`UserMemoriesRepository.searchMemories`."""

MEMORY_SEARCH_TOPK_MULTIPLIER: int = 3
"""vec0 ``k`` is ``limit * this multiplier`` to absorb post-filter trimming."""

BACKFILL_DEFAULT_BATCH_SIZE: int = 50
"""Default per-tick batch size for the memory embedding regeneration cron."""

_SELECT_COLUMNS: str = (
    "chat_id, user_id, thread_id, memory_id, type, content, tags, "
    "permanent, source, embedding_model, embedding_dimensions, "
    "created_at, updated_at"
)
"""Column list selected by every read method so ``sqlToTypedDict`` sees all required keys."""


class UserMemoryDict(TypedDict):
    """Row shape returned by ``UserMemoriesRepository`` read methods.

    Keys are snake_case to match DB column names (repo convention — see
    ``ChatMessageDict`` / ``MessageEmbeddingDict`` in
    ``internal/database/models.py``). Repository METHOD parameters stay
    camelCase per AGENTS.md; only the dict keys mirror the columns so
    the universal converter ``dbUtils.sqlToTypedDict`` can map them
    directly.

    Attributes:
        chat_id: Chat the memory belongs to.
        user_id: User the memory is about.
        thread_id: Thread scope. ``None`` for cross-thread permanent
            memories (e.g. ``user_data``-migrated facts); set to the
            originating thread for thread-specific permanent bio
            memories (``migration_020`` Backfill B).
        memory_id: App-generated UUID hex; unique within (chat_id, user_id).
        type: ``MemoryType`` string value
            (bio|preference|fact|event|relationship).
        content: Free-text memory body (source of truth for re-embedding).
        tags: Decoded list of tag strings (stored as JSON TEXT in the row).
        permanent: True if the memory is always injected into the system block.
        source: Provenance — refinement | chat | migration | user.
        embedding_model: Name of the model that produced the stored vec0
            embedding, or ``None`` when the memory has not been embedded yet.
        embedding_dimensions: Dimension count of the stored embedding, or
            ``None`` when not yet embedded.
        created_at: Creation timestamp.
        updated_at: Last-update timestamp.
        score: Cosine similarity (0.0–1.0) when returned by semantic
            ``searchMemories`` (Phase 1b); absent on rows from non-search
            methods. Mirrors ``ChatMessageDict.score``.
    """

    chat_id: int
    user_id: int
    thread_id: Optional[int]
    memory_id: str
    type: str
    content: str
    tags: List[str]
    permanent: bool
    source: str
    embedding_model: Optional[str]
    embedding_dimensions: Optional[int]
    created_at: datetime.datetime
    updated_at: datetime.datetime
    score: NotRequired[float]


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

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialize the user memories repository.

        Args:
            manager: Database manager instance for provider access.

        Returns:
            None
        """
        super().__init__(manager)

    ###
    # Writes
    ###
    async def addMemory(
        self,
        chatId: int,
        userId: int,
        memoryId: str,
        *,
        type: str,
        content: str,
        tags: List[str],
        permanent: bool,
        threadId: Optional[int] = None,
        source: str = "refinement",
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
            type: ``MemoryType`` string value (bio|preference|fact|event|relationship).
            content: Free-text memory body.
            tags: List of freeform tag strings (stored as JSON TEXT).
            permanent: True for always-injected memories, False for ephemeral.
            threadId: Thread scope; ``None`` for cross-thread permanent memories.
            source: Provenance — refinement | chat | migration | user.

        Returns:
            None

        Raises:
            Exception: Re-raised on PK conflict or any DB error (caller
                ensures ULID uniqueness).
        """
        now = libUtils.now()
        sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
        await sqlProvider.execute(
            """
            INSERT INTO user_memories
                (chat_id, user_id, thread_id, memory_id, type, content, tags,
                 permanent, source, embedding_model, embedding_dimensions,
                 created_at, updated_at)
            VALUES
                (:chatId, :userId, :threadId, :memoryId, :type, :content, :tags,
                 :permanent, :source, NULL, NULL, :createdAt, :updatedAt)
            """,
            {
                "chatId": chatId,
                "userId": userId,
                "threadId": threadId,
                "memoryId": memoryId,
                "type": type,
                "content": content,
                "tags": json.dumps(tags),
                "permanent": 1 if permanent else 0,
                "source": source,
                "createdAt": now,
                "updatedAt": now,
            },
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
        """
        if content is None and tags is None and type is None:
            return False

        setClauses: List[str] = []
        params: dict[str, object] = {
            "chatId": chatId,
            "userId": userId,
            "memoryId": memoryId,
            "updatedAt": libUtils.now(),
        }
        if content is not None:
            setClauses.append("content = :content")
            params["content"] = content
        if tags is not None:
            setClauses.append("tags = :tags")
            params["tags"] = json.dumps(tags)
        if type is not None:
            setClauses.append("type = :type")
            params["type"] = type
        setClauses.append("updated_at = :updatedAt")

        sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

        # The provider's execute() returns None, so check existence to
        # report whether a row was actually updated.
        existing = await sqlProvider.executeFetchOne(
            "SELECT 1 FROM user_memories " "WHERE chat_id = :chatId AND user_id = :userId AND memory_id = :memoryId",
            {"chatId": chatId, "userId": userId, "memoryId": memoryId},
        )
        if existing is None:
            return False

        await sqlProvider.execute(
            f"""
            UPDATE user_memories
            SET {', '.join(setClauses)}
            WHERE chat_id = :chatId AND user_id = :userId AND memory_id = :memoryId
            """,
            params,
        )

        # Content change → embedding is stale. Reset provenance columns
        # AND drop the stale vec0 row so the regen cron
        # (getMemoriesWithoutEmbeddings) re-embeds on the NEW content.
        # Never raise from this cleanup: the content update already
        # succeeded; an embedding-invalidation failure must not undo it
        # (the row will be re-embedded on the next drift pass).
        if content is not None:
            try:
                await sqlProvider.execute(
                    """
                    UPDATE user_memories
                    SET embedding_model = NULL, embedding_dimensions = NULL
                    WHERE chat_id = :chatId AND user_id = :userId AND memory_id = :memoryId
                    """,
                    {"chatId": chatId, "userId": userId, "memoryId": memoryId},
                )
            except Exception:
                logger.error(
                    "Failed to null embedding provenance after content update for memory %s chat %d",
                    memoryId,
                    chatId,
                    exc_info=True,
                )
            try:
                await self.deleteMemoryEmbedding(chatId, userId, memoryId)
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
        memory (this is the distinction from ``deleteMemoriesByQuery``,
        which is permanently permanent-guarded). The vec0 embedding row
        cleanup is Phase 1b.

        Args:
            chatId: Chat the memory belongs to.
            userId: User the memory is about.
            memoryId: Memory identifier to delete.

        Returns:
            True if a row was deleted, False if no row matched.
        """
        sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
        existing = await sqlProvider.executeFetchOne(
            "SELECT 1 FROM user_memories " "WHERE chat_id = :chatId AND user_id = :userId AND memory_id = :memoryId",
            {"chatId": chatId, "userId": userId, "memoryId": memoryId},
        )
        if existing is None:
            return False
        await sqlProvider.execute(
            "DELETE FROM user_memories " "WHERE chat_id = :chatId AND user_id = :userId AND memory_id = :memoryId",
            {"chatId": chatId, "userId": userId, "memoryId": memoryId},
        )
        return True

    async def deleteMemoriesByQuery(
        self,
        chatId: int,
        userId: int,
        *,
        threadId: Optional[int],
        type: Optional[str] = None,
        olderThanDays: Optional[int] = None,
    ) -> int:
        """DELETE EPHEMERAL memories matching the scope + filters.

        Always adds ``AND permanent = 0`` — bulk query-delete is
        ephemeral-only; a query-based bulk delete must never silently
        remove a permanent memory. Explicit by-id ``deleteMemory`` is
        unrestricted (intentional explicit action can target a permanent
        memory).

        Args:
            chatId: Chat the memories belong to.
            userId: User the memories are about.
            threadId: When not ``None``, restrict to this thread; when
                ``None``, match ephemeral memories across all threads for
                this (chatId, userId).
            type: When not ``None``, restrict to this ``MemoryType`` value.
            olderThanDays: When not ``None``, restrict to memories whose
                ``created_at`` is older than this many days from now.

        Returns:
            The count of deleted rows.

        Note: No production callers as of Phase 5a (the wizard's ClearChatData
            action was removed). Retained for potential future bulk-ephemeral-
            delete use cases.
        """
        conditions: List[str] = [
            "chat_id = :chatId",
            "user_id = :userId",
            "permanent = 0",
        ]
        params: dict[str, object] = {"chatId": chatId, "userId": userId}
        if threadId is not None:
            conditions.append("thread_id = :threadId")
            params["threadId"] = threadId
        if type is not None:
            conditions.append("type = :type")
            params["type"] = type
        if olderThanDays is not None:
            cutoff = libUtils.now() - datetime.timedelta(days=olderThanDays)
            conditions.append("created_at < :cutoff")
            params["cutoff"] = cutoff
        whereClause = " AND ".join(conditions)

        sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

        # The provider's execute() returns None, so count matching rows
        # first to report how many were deleted.
        countRow = await sqlProvider.executeFetchOne(
            f"SELECT COUNT(*) AS cnt FROM user_memories WHERE {whereClause}",
            params,
        )
        count = int(countRow["cnt"]) if countRow is not None else 0
        if count == 0:
            return 0
        await sqlProvider.execute(
            f"DELETE FROM user_memories WHERE {whereClause}",
            params,
        )
        return count

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

        Returns:
            List of :class:`UserMemoryDict` ordered by ``updated_at`` desc.
        """
        sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=True)
        query = f"""
            SELECT {_SELECT_COLUMNS}
            FROM user_memories
            WHERE chat_id = :chatId AND user_id = :userId AND permanent = 1
              AND (thread_id IS NULL OR thread_id = :threadId)
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

        Returns:
            List of :class:`UserMemoryDict` (``permanent = 0`` only)
            ordered by ``updated_at`` desc.
        """
        sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=True)
        query = f"""
            SELECT {_SELECT_COLUMNS}
            FROM user_memories
            WHERE chat_id = :chatId AND user_id = :userId AND thread_id = :threadId
              AND permanent = 0
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

        Returns:
            The matching :class:`UserMemoryDict`, or ``None`` when no row
            matches the full ``(chatId, userId, memoryId)`` key.
        """
        sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=True)
        row = await sqlProvider.executeFetchOne(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM user_memories
            WHERE chat_id = :chatId AND user_id = :userId AND memory_id = :memoryId
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
    ) -> List[str]:
        """Return the sorted set of distinct tag strings across a user's memories.

        Fetches every ``tags`` JSON column for ``(chatId, userId)`` (optionally
        narrowed by ``type``), parses each row's JSON list, and collects unique
        tag strings. Used by the ``/knowledge_config`` wizard's tag-filter
        picker (Phase 5b) so the user can only pick tags they actually use.

        Tags inserted via the ``add_memory`` LLM tool are lowercased (see
        :meth:`UserDataHandler._llmToolAddMemory`); tags inserted via other
        paths (repo :meth:`addMemory`/:meth:`updateMemory`, migration
        backfills) are NOT normalised — callers should not assume lowercase,
        and this method performs no extra normalisation.

        Args:
            chatId: Chat the memories belong to.
            userId: User the memories are about.
            memoryType: Optional ``MemoryType`` value filter. When ``None``,
                tags from memories of ALL types are collected.

        Returns:
            Sorted list of distinct tag strings. Empty list on error or when
            no tags exist. Never raises.
        """
        try:
            conditions: List[str] = ["chat_id = :chatId", "user_id = :userId"]
            params: dict[str, object] = {"chatId": chatId, "userId": userId}
            if memoryType is not None:
                conditions.append("type = :memoryType")
                params["memoryType"] = memoryType
            whereClause = " AND ".join(conditions)
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=True)
            rows = await sqlProvider.executeFetchAll(
                f"SELECT tags FROM user_memories WHERE {whereClause}",
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
        queryEmbedding: Optional[bytes] = None,
        *,
        threadId: Optional[int] = None,
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        permanent: Optional[bool] = None,
        limit: int = MEMORY_SEARCH_DEFAULT_LIMIT,
        dimensions: Optional[int] = None,
        offset: int = 0,
    ) -> List[UserMemoryDict]:
        """Unified memory search with filter-only and semantic modes.

        Two modes (mirror ``ChatSearchRepository.searchChatMessages`` at
        ``chat_search.py:167-189``):

        - **Filter-only mode** (``queryEmbedding is None``): a plain SQL
          scan of ``user_memories`` with optional ``threadId`` / ``type``
          / ``tags`` / ``permanent`` filters, ordered by ``updated_at``
          descending. Every result row gets ``score = 0.0`` after
          conversion (mirror ``chat_search.py:256``).
        - **Semantic mode** (``queryEmbedding`` is ``bytes``): native
          vec0 search over ``vec_user_memories_{dim}``, JOIN back to
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
            queryEmbedding: Pre-serialised query vector bytes
                (``array.array("f", floats).tobytes()``). When ``None``,
                runs filter-only mode. When bytes, runs semantic mode.
            threadId: Optional thread scope filter. When ``None``, NO
                thread filter is applied (all threads, including the
                cross-thread ``NULL`` ones, are returned).
            type: Optional ``MemoryType`` value filter.
            tags: Optional list of tag strings; a memory matches when it
                carries ANY of the listed tags.
            permanent: Optional permanent-flag filter.
            limit: Maximum results to return.
            dimensions: Embedding dimension (overrides inference from
                ``queryEmbedding`` byte length). When ``None``, the
                dimension is inferred as ``len(queryEmbedding) // 4``.
            offset: Number of leading results to skip (pagination).

        Returns:
            List of :class:`UserMemoryDict` with the ``score`` field
            populated on every row (``0.0`` in filter-only mode;
            ``1.0 - cosine_distance`` in semantic mode). Empty list on
            failure or when semantic search is unavailable.
        """
        if queryEmbedding is None:
            return await self._filterOnlySearchMemories(
                chatId=chatId,
                userId=userId,
                threadId=threadId,
                type=type,
                tags=tags,
                permanent=permanent,
                limit=limit,
                offset=offset,
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
            dimensions=dimensions,
            offset=offset,
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
    ) -> List[UserMemoryDict]:
        """Filter-only search path (no vector ranking). Every row gets ``score = 0.0``.

        Args:
            chatId: Chat to search in.
            userId: User whose memories are searched.
            threadId: Optional thread scope filter. ``None`` applies NO
                thread filter (all threads, including ``NULL`` cross-thread).
            type: Optional ``MemoryType`` value filter.
            tags: Optional list of tag strings (ANY-match via Python
                set-intersection post-fetch — see module note on tags).
            permanent: Optional permanent-flag filter.
            limit: Maximum results to return.
            offset: Number of leading results to skip (pagination).

        Returns:
            List of :class:`UserMemoryDict` with ``score = 0.0``.
        """
        try:
            conditions: List[str] = ["chat_id = :chatId", "user_id = :userId"]
            params: dict[str, object] = {"chatId": chatId, "userId": userId}
            if threadId is not None:
                conditions.append("thread_id = :threadId")
                params["threadId"] = threadId
            if type is not None:
                conditions.append("type = :type")
                params["type"] = type
            if permanent is not None:
                conditions.append("permanent = :permanent")
                params["permanent"] = 1 if permanent else 0
            # NOTE: ``tags`` is NOT filtered in SQL. Tags are stored as
            # JSON TEXT; ``LIKE '%"tag"%'`` is non-portable (breaks on
            # tags containing ``"`` / ``%`` / ``_``) — see plan §6.2.
            # Apply tags as a Python set-intersection post-fetch below.

            whereClause = " AND ".join(conditions)
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=True)
            query = f"""
                SELECT {_SELECT_COLUMNS}
                FROM user_memories
                WHERE {whereClause}
                ORDER BY updated_at DESC
            """
            query = sqlProvider.applyPagination(query=query, limit=limit, offset=offset)
            rows = await sqlProvider.executeFetchAll(query, params)
            results: List[UserMemoryDict] = []
            for row in rows:
                rowDict = dbUtils.sqlToTypedDict(row, UserMemoryDict)
                rowDict["score"] = 0.0
                results.append(rowDict)

            # Tags post-filter: ANY-match via Python set-intersection.
            # The fetch is not k-limited by vec0 here, so no over-fetch
            # is needed — the SQL scan already returned all matches.
            # NOTE: pagination (offset) is applied to the SQL result BEFORE
            # the tags post-filter, so when a tags filter is combined with a
            # non-zero offset the page boundary may straddle a trimmed row.
            # This is acceptable for the admin wizard (tags filter is
            # Phase 5b); the LLM ``search_memories`` tool does not paginate.
            if tags:
                requestedTags = set(tags)
                results = [r for r in results if requestedTags & set(r.get("tags") or [])]
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
        queryEmbedding: bytes,
        *,
        threadId: Optional[int],
        type: Optional[str],
        tags: Optional[List[str]],
        permanent: Optional[bool],
        limit: int,
        dimensions: Optional[int],
        offset: int = 0,
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
            queryEmbedding: Pre-serialised float32 query vector bytes.
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
            dimensions: Embedding dimension override. When ``None``,
                inferred as ``len(queryEmbedding) // 4``.
            offset: Number of leading ranked results to skip
                (pagination; applied AFTER ranking and trimming).

        Returns:
            List of :class:`UserMemoryDict` ranked by similarity
            descending with ``score = 1.0 - cosine_distance``. Empty
            list when vec0 is unsupported, the table is absent, or no
            matches are found.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=True)
            if not await sqlProvider.isVectorSearchSupported():
                logger.debug(
                    "Semantic memory search requested for chat %d but vec0 is unsupported; returning []",
                    chatId,
                )
                return []

            dim = dimensions if dimensions is not None else (len(queryEmbedding) // 4)
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
            filterParts: List[str] = ["chat_id = :chatId", "user_id = :userId"]
            filterParams: dict[str, str | int | float | None] = {
                "chatId": chatId,
                "userId": userId,
            }
            if permanent is not None:
                filterParts.append("permanent = :permanent")
                filterParams["permanent"] = 1 if permanent else 0

            k = max(limit * MEMORY_SEARCH_TOPK_MULTIPLIER, limit)
            vecResults = await sqlProvider.vectorSearch(
                table=tableName,
                vectorColumn="embedding",
                returnColumns=["memory_id"],
                queryVector=queryEmbedding,
                k=k,
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
            fetchParams: dict[str, object] = {"chatId": chatId, "userId": userId}
            conditions: List[str] = ["chat_id = :chatId", "user_id = :userId"]
            for i, mid in enumerate(scoreByMemoryId):
                key = f"mid{i}"
                placeholders.append(f":{key}")
                fetchParams[key] = mid
            conditions.append(f"memory_id IN ({', '.join(placeholders)})")
            if threadId is not None:
                conditions.append("thread_id = :threadId")
                fetchParams["threadId"] = threadId
            if type is not None:
                # Read the fresh ``user_memories.type`` (NOT the stale
                # vec0 denormalised column). Plain TEXT equality is
                # cross-RDBMS portable.
                conditions.append("type = :type")
                fetchParams["type"] = type

            whereClause = " AND ".join(conditions)
            query = f"""
                SELECT {_SELECT_COLUMNS}
                FROM user_memories
                WHERE {whereClause}
            """
            rows = await sqlProvider.executeFetchAll(query, fetchParams)

            results: List[UserMemoryDict] = []
            for row in rows:
                rowDict = dbUtils.sqlToTypedDict(row, UserMemoryDict)
                mid = rowDict["memory_id"]
                rowDict["score"] = scoreByMemoryId.get(mid, 0.0)
                results.append(rowDict)

            # Tags post-filter: ANY-match via Python set-intersection.
            if tags:
                requestedTags = set(tags)
                results = [r for r in results if requestedTags & set(r.get("tags") or [])]

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
        model: str,
    ) -> bool:
        """Persist a memory embedding: lazy-upsert vec0 + update ``user_memories`` columns.

        Dimensions are derived from ``len(embedding)``. The float vector
        is serialised to bytes via ``array.array("f", embedding).tobytes()``
        (mirror ``chat_embeddings.py:115``). The dimension-specific vec0
        virtual table ``vec_user_memories_{dim}`` is created lazily on
        first write (mirror ``_upsertVecMessageEmbedding``). After the
        vec0 upsert, the ``user_memories`` row's ``embedding_model`` and
        ``embedding_dimensions`` columns are set so stale-detection
        (``getMemoriesWithoutEmbeddings``) can track provenance.

        No BLOB write — vec0 is the sole embedding store (§5.1 of the
        user-memories plan dropped the BLOB table by design).

        Strand-proofing: the vec0 upsert runs BEFORE the provenance
        UPDATE and re-raises on failure (see
        :meth:`_upsertVecMemoryEmbedding`). On a vec0 write failure this
        method returns ``False`` WITHOUT touching ``embedding_model`` /
        ``embedding_dimensions`` — they stay ``NULL`` so the regen cron
        (:meth:`getMemoriesWithoutEmbeddings`) re-surfaces the memory.
        Setting provenance only on vec0 success prevents a memory from
        being marked embedded while carrying no searchable vector.

        Note: every successful write bumps ``updated_at`` (including
        no-op re-embeds of identical content). This advances
        re-ranked ordering (``ORDER BY updated_at``); accepted for v1.

        Args:
            chatId: Chat the memory belongs to.
            userId: User the memory is about.
            memoryId: Memory identifier.
            embedding: Float vector (any length; becomes the dimension).
            model: Model name that produced the embedding.

        Returns:
            True on success, False on any failure (never raises).
        """
        try:
            dimensions = len(embedding)
            blob = array.array("f", embedding).tobytes()
            now = libUtils.now()

            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

            # Fetch the memory row to populate vec0 metadata columns
            # (thread_id, permanent, type) that the vec0 table carries.
            memoryRow = await sqlProvider.executeFetchOne(
                """
                SELECT thread_id, permanent, type
                FROM user_memories
                WHERE chat_id = :chatId AND user_id = :userId AND memory_id = :memoryId
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
                await self._upsertVecMemoryEmbedding(
                    sqlProvider=sqlProvider,
                    chatId=chatId,
                    userId=userId,
                    memoryId=memoryId,
                    threadId=memoryRow["thread_id"],
                    permanent=int(memoryRow["permanent"]),
                    memoryType=memoryRow["type"],
                    embedding=blob,
                    dimensions=dimensions,
                )
            except Exception:
                return False

            # Set provenance columns on the authoritative row. A stale
            # model switch will surface this row via
            # getMemoriesWithoutEmbeddings for re-embedding.
            await sqlProvider.execute(
                """
                UPDATE user_memories
                SET embedding_model = :model,
                    embedding_dimensions = :dimensions,
                    updated_at = :now
                WHERE chat_id = :chatId AND user_id = :userId AND memory_id = :memoryId
                """,
                {
                    "chatId": chatId,
                    "userId": userId,
                    "memoryId": memoryId,
                    "model": model,
                    "dimensions": dimensions,
                    "now": now,
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
        permanent: int,
        memoryType: str,
        embedding: bytes,
        dimensions: int,
    ) -> None:
        """Upsert a row into the dimension-specific vec0 memory table.

        Lazily creates ``vec_user_memories_{dimensions}`` on first use
        via :meth:`BaseSQLProvider.createVectorTable`. Uses DELETE +
        INSERT because vec0 does not support conventional UPSERT on
        metadata columns. Write failures are logged at warning and then
        RE-RAISED so the caller (:meth:`saveMemoryEmbedding`) can skip
        the provenance UPDATE and leave ``embedding_model = NULL`` —
        that keeps the memory visible to
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
            embedding: Float32 embedding bytes.
            dimensions: Embedding dimension.

        Returns:
            None.

        Raises:
            Exception: Re-raised after logging when the vec0 DELETE or
                INSERT fails (or the lazy table creation fails). The
                caller is responsible for leaving provenance columns
                untouched so the regen cron retries.
        """
        tableName = f"vec_user_memories_{dimensions}"

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
                f"(memory_id, chat_id, user_id, thread_id, permanent, type, embedding) "
                f"VALUES (:memoryId, :chatId, :userId, :threadId, :permanent, :type, :embedding)",
                {
                    "memoryId": memoryId,
                    "chatId": chatId,
                    "userId": userId,
                    "threadId": threadId,
                    "permanent": permanent,
                    "type": memoryType,
                    "embedding": embedding,
                },
            )
        except Exception:
            logger.warning(
                "Failed to upsert vec0 memory embedding for chat %s memory %s",
                chatId,
                memoryId,
                exc_info=True,
            )
            raise

    async def deleteMemoryEmbedding(
        self,
        chatId: int,
        userId: int,
        memoryId: str,
    ) -> bool:
        """Best-effort DELETE of a memory's vec0 embedding row. Never raises.

        Iterates every ``vec_user_memories_{N}`` table found via
        ``listTables`` and deletes the row matching the memory_id. When
        no vec0 table exists, the call is a no-op and returns ``True``.

        Args:
            chatId: Chat the memory belongs to.
            userId: User the memory is about.
            memoryId: Memory identifier.

        Returns:
            True if a vec0 row was deleted OR no vec0 table existed
            (nothing to clean). False when tables existed but the
            memory_id was not found in any of them.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            if not await sqlProvider.isVectorSearchSupported():
                return True

            vecTables = await sqlProvider.listTables("vec_user_memories_%")
            # Filter out vec0 shadow tables (_info, _chunks, etc.).
            vecTables = [t for t in vecTables if re.match(r"^vec_user_memories_\d+$", t)]
            if not vecTables:
                return True

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
                        # Metadata-keyed DELETE succeeded.
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
                            # Rowid-fallback DELETE actually ran.
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

        Returns:
            List of :class:`UserMemoryDict` ordered by ``updated_at``
            descending. Empty list on error.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=True)
            if modelName is None:
                query = f"""
                    SELECT {_SELECT_COLUMNS}
                    FROM user_memories
                    WHERE chat_id = :chatId AND embedding_model IS NULL
                    ORDER BY updated_at DESC
                """
                params: dict[str, object] = {"chatId": chatId}
            else:
                query = f"""
                    SELECT {_SELECT_COLUMNS}
                    FROM user_memories
                    WHERE chat_id = :chatId
                      AND (embedding_model IS NULL OR embedding_model != :modelName)
                    ORDER BY updated_at DESC
                """
                params = {"chatId": chatId, "modelName": modelName}
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
        those ``user_memories`` rows so ``getMemoriesWithoutEmbeddings``
        picks them up for re-embedding on the next regeneration tick.

        Mirrors ``deleteObsoleteModelEmbeddings``
        (``chat_embeddings.py:337-464``) but single-store (no BLOB table
        to clean — only vec0 + the provenance columns).

        ``currentDimensions`` accepts ``None`` for embedding models that
        do not expose a dimension count (e.g. plain OpenAI-style models
        whose ``getDimensions()`` returns ``None``). In that case the SQL
        ``embedding_dimensions != NULL`` predicate evaluates to NULL
        (falsy) in SQLite, so cleanup matches purely on the model name —
        the correct behaviour for dim-less models. Mirrors the
        ``Optional[int]`` contract of the chat-history analog.

        Args:
            chatId: Chat to clean.
            currentModel: The currently-active embedding model name.
            currentDimensions: The currently-active embedding
                dimensionality, or ``None`` when the model does not
                expose dimensions (dim-less cleanup on model name only).

        Returns:
            The count of reset rows. Never raises.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

            # 1. Collect stale memory_ids.
            staleRows = await sqlProvider.executeFetchAll(
                """
                SELECT memory_id
                FROM user_memories
                WHERE chat_id = :chatId
                  AND embedding_model IS NOT NULL
                  AND (embedding_model != :currentModel OR embedding_dimensions != :currentDimensions)
                """,
                {
                    "chatId": chatId,
                    "currentModel": currentModel,
                    "currentDimensions": currentDimensions,
                },
            )
            if not staleRows:
                return 0

            staleIds: List[str] = [row["memory_id"] for row in staleRows]

            # 2. Delete their vec0 rows from every vec_user_memories_{N} table.
            if await sqlProvider.isVectorSearchSupported():
                try:
                    vecTables = await sqlProvider.listTables("vec_user_memories_%")
                    vecTables = [t for t in vecTables if re.match(r"^vec_user_memories_\d+$", t)]
                    for table in vecTables:
                        # Batch-delete by memory_id IN (...). Use named
                        # placeholders to stay portable across RDBMS drivers.
                        placeholders: List[str] = []
                        params: dict[str, object] = {"chatId": chatId}
                        for i, mid in enumerate(staleIds):
                            key = f"mid{i}"
                            placeholders.append(f":{key}")
                            params[key] = mid
                        try:
                            await sqlProvider.execute(
                                f"DELETE FROM {table} "
                                f"WHERE chat_id = :chatId AND memory_id IN ({', '.join(placeholders)})",
                                params,
                            )
                        except Exception:
                            # Some vec0 builds restrict WHERE to partition
                            # keys only; fall back to per-row delete.
                            for mid in staleIds:
                                row = await sqlProvider.executeFetchOne(
                                    f"SELECT rowid FROM {table} WHERE chat_id = :chatId AND memory_id = :memoryId",
                                    {"chatId": chatId, "memoryId": mid},
                                )
                                if row is not None:
                                    await sqlProvider.execute(
                                        f"DELETE FROM {table} WHERE rowid = :rowid",
                                        {"rowid": row["rowid"]},
                                    )
                except NotImplementedError:
                    logger.debug(
                        "listTables not supported for chat %d; skipping vec0 cleanup",
                        chatId,
                    )

            # 3. Reset provenance columns so getMemoriesWithoutEmbeddings
            #    re-surfaces these rows for re-embedding.
            placeholders = []
            params = {"chatId": chatId}
            for i, mid in enumerate(staleIds):
                key = f"mid{i}"
                placeholders.append(f":{key}")
                params[key] = mid
            await sqlProvider.execute(
                f"""
                UPDATE user_memories
                SET embedding_model = NULL, embedding_dimensions = NULL
                WHERE chat_id = :chatId AND memory_id IN ({', '.join(placeholders)})
                """,
                params,
            )
            return len(staleIds)
        except Exception:
            logger.error(
                "Failed to delete obsolete memory embeddings for chat %d",
                chatId,
                exc_info=True,
            )
            return 0
