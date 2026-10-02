"""Repository for the unified ``user_memories`` store.

This module owns all database operations on the ``user_memories`` table
introduced by ``migration_020_user_memories``: durable per-(chat, user,
thread) facts, preferences, events, relationships, and high-level bio
notes about a user — the unified store that retires the legacy
``user_data`` key-value table and the rolling-bio JSON blob.

The repository covers the full lifecycle:
- Relational CRUD (``addMemory`` / ``deleteMemory`` /
  ``getPermanentMemories`` / ``getLatestMemories``). Content changes go
  through ``deleteMemory`` + ``addMemory`` (there is no in-place PATCH).
- Unified search (``searchMemories``) — filter-only (``queryEmbedding
  is None``) and semantic (vec0 native) modes.
- Embedding persistence (``saveMemoryEmbedding`` /
  ``deleteMemoryEmbedding``) via a lazily-created ``vec_user_memories_{dim}``
  virtual table (mirrors ``chat_embeddings._upsertVecMessageEmbedding``).
- Embedding model-drift regeneration helpers
  (``getMemoriesWithoutEmbeddings`` /
  ``deleteObsoleteMemoryEmbeddings``).

**Post-``migration_025`` shape:** the per-row ``(embedding_model,
embedding_dimensions)`` provenance pair was normalised into the
``models`` lookup table keyed by a single integer ``model_id`` (see
Decision D2 of the embedding-model-lookup refactor —
``docs/plans/embedding-model-lookup-refactor-v1.md``). Every
embedding-touching method on this repository resolves the model name
string it receives at its public boundary (Decision D6 extended) to a
``model_id`` via the injected ``modelIdResolver`` (Decision D10) before
emitting SQL. Handler-facing signatures stay stable — the ``modelName``
/ ``currentModel`` string parameters continue to flow in from the bot
layer unchanged.

**Key difference from chat-history search:** there is NO BLOB
``user_memory_embeddings`` table. Embeddings live ONLY in the vec0
virtual table; ``model_id`` is tracked on ``user_memories`` itself.
Semantic search is therefore vec0-only (no numpy fallback) — when vec0
is unavailable, ``searchMemories`` returns ``[]``.

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
import math
import re
from typing import Awaitable, Callable, Dict, List, Optional

from internal.database.constants import (
    BACKFILL_DEFAULT_BATCH_SIZE,
    EPHEMERAL_RETRIEVAL_LIMIT,
    MAX_SQL_VARIABLES,
    MEMORY_SEARCH_DEFAULT_LIMIT,
    MEMORY_SEARCH_TOPK_MULTIPLIER,
    PERMANENT_INJECTION_CAP,
)
from internal.database.models import UserMemoryDict, UserMemorySource
from lib.db import utils as dbUtils
from lib.db.manager import DatabaseManager
from lib.db.providers.base import (
    BaseSQLProvider,
    VectorColumnType,
    VectorDistanceMetric,
)

from .base import BaseRepository

logger = logging.getLogger(__name__)

_SELECT_COLUMNS: str = (
    "chat_id, user_id, thread_id, memory_id, type, content, tags, "
    "permanent, source, model_id, "
    "created_at, updated_at"
)
"""Column list selected by every read method so ``sqlToTypedDict`` sees all required keys."""


def _normalizeTags(tags: Optional[List[str]]) -> Optional[List[str]]:
    """Normalise tags for symmetric storage/query use: lowercase, strip ``"`` and ``\\``, dedup.

    Called at BOTH write time (``addMemory``) and query time (the search
    methods), so it must NOT apply LIKE-specific escaping — that would
    break the JSON round-trip (the backslash introduced by LIKE escaping
    would be double-escaped by ``json.dumps`` at storage time, so the
    stored text would never match the LIKE pattern). LIKE wildcard
    escaping is applied separately, only at pattern-construction time,
    by :func:`_escapeTagForLike`.

    The backslash (``\\``) is stripped here for the same reason ``"`` is
    stripped: tags are stored via ``json.dumps`` (which doubles every
    ``\\`` → ``\\\\``), and the LIKE-escape helper
    :func:`_escapeTagForLike` doubles ``\\`` again for the LIKE pattern.
    A tag containing a literal ``\\`` would therefore never match its
    own stored JSON pattern, so backslash is removed entirely (alongside
    ``"``) to keep storage and query normalisation symmetric.

    Args:
        tags: Raw tag list, or ``None``.

    Returns:
        Deduplicated list of lowercased, quote-and-backslash-stripped
        tags, or the original ``None`` / empty input.
    """
    if not tags:
        return tags
    return list(set([tag.lower().replace('"', "").replace("\\", "") for tag in tags]))


def _escapeTagForLike(value: str) -> str:
    r"""Escape LIKE wildcards (``%``, ``_``) and the escape char ``\``.

    Applied ONLY when constructing a LIKE pattern value (never at storage
    time) so that a tag containing ``%`` or ``_`` matches literally
    rather than being interpreted as a wildcard. The paired ``ESCAPE '\'``
    clause on every ``tags LIKE :tagsN`` expression tells the SQL engine
    to honour the backslash as the escape character.

    Portability note: ``ESCAPE '\'`` is valid on SQLite and PostgreSQL
    (``standard_conforming_strings = on``, the default since PostgreSQL
    9.1). On MySQL, where backslash is an escape character inside string
    literals by default, the clause would need ``ESCAPE '\\'`` — this is
    documented for when the MySQL provider is wired up.

    Args:
        value: A single normalised tag string (output of
            :func:`_normalizeTags`).

    Returns:
        The tag with ``\``, ``%``, and ``_`` escaped for use inside a
        LIKE pattern that carries ``ESCAPE '\'``.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class UserMemoriesRepository(BaseRepository):
    """Repository for the unified ``user_memories`` store.

    Provides the full memory lifecycle: relational CRUD, unified search
    (filter-only + semantic vec0), embedding persistence via the lazily
    created ``vec_user_memories_{dim}`` virtual table, and model-drift
    regeneration helpers. Mirrors the ``chat_embeddings`` /
    ``chat_search`` split but adapted for the single-store model
    (no BLOB table — vec0 is the sole embedding store).

    Attributes:
        _modelIdResolver: Async callable resolving ``(modelName,
            dimensions)`` to a ``model_id`` integer. Wired in
            :meth:`Database.__init__` to
            :meth:`EmbeddingModelsRepository.getOrCreateModelId` (bound method).
            Injected per Decision D10 of the embedding-model-lookup
            refactor.
    """

    # ``manager`` is inherited from ``BaseRepository.__slots__`` and is
    # NOT redeclared here (re-declaring raises
    # ``ValueError: 'manager' in __slots__ conflicts with class variable``).
    __slots__ = ("_modelIdResolver",)
    """Restricts instance attributes to prevent dynamic attribute creation."""

    def __init__(
        self,
        manager: DatabaseManager,
        *,
        modelIdResolver: Callable[..., Awaitable[int]],
    ) -> None:
        """Initialize the user memories repository.

        Args:
            manager: Database manager instance for provider access.
            modelIdResolver: Async callable that resolves ``(modelName,
                dimensions)`` to a ``model_id`` integer. Wired in
                :meth:`Database.__init__` to
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
        # We insert model_id as NULL to ensure it is filled ONLY IF vec0
        # insert were successful. This way we'll be sure, that we have embedding
        # with given model\dimensions. The post-``migration_025`` shape: the
        # legacy ``(embedding_model, embedding_dimensions)`` provenance pair
        # is normalised into the ``models`` lookup table keyed by ``model_id``.
        await sqlProvider.execute(
            """
            INSERT INTO user_memories
                (chat_id, user_id, thread_id, memory_id, type, content, tags,
                 permanent, source, model_id,
                 created_at, updated_at)
            VALUES
                (:chatId, :userId, :threadId, :memoryId, :type, :content, :tags,
                 :permanent, :source, NULL,
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

    async def deleteMemory(
        self,
        chatId: int,
        userId: int,
        memoryId: str,
    ) -> bool:
        """Soft-delete one memory row (sets ``deleted_at``; the row survives).

        Unrestricted — an explicit by-id delete MAY target a permanent
        memory. Instead of hard-``DELETE``-ing the row, this sets
        ``deleted_at`` (and bumps ``updated_at``) so the content row
        survives for historical reconstruction: a message that
        references a now-deleted memory must still resolve its content
        via :meth:`getMemoriesByIds` (which deliberately has no
        ``deleted_at`` filter). The vec0 embedding row is deleted and the
        provenance column (``model_id``) is nulled (via
        :meth:`deleteMemoryEmbedding(..., vecOnly=False)`) so a deleted
        memory is never a semantic-search hit and the regen cron never
        re-embeds it.

        An existence pre-check (companion SELECT scoped to the LIVE row
        via ``AND deleted_at IS NULL``) drives the return value: a
        re-delete of an already-soft-deleted ``memory_id`` returns
        ``False``. Never raises — on any DB error the exception is
        logged and ``False`` is returned.

        Args:
            chatId: Chat the memory belongs to.
            userId: User the memory is about.
            memoryId: Memory identifier to delete.

        Returns:
            True if a live row was soft-deleted, False if no live row
            matched (already soft-deleted or never existed) or on error.

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

            now = dbUtils.getCurrentTimestamp()

            # Existence pre-check: the provider's execute() returns None,
            # so a companion SELECT is the only way to tell "soft-deleted
            # one live row" from "matched zero live rows". Scoped to the
            # LIVE row (deleted_at IS NULL) so a re-delete of an
            # already-soft-deleted memory_id returns False.
            existing = await sqlProvider.executeFetchOne(
                """
                SELECT 1 FROM user_memories
                WHERE
                    chat_id = :chatId AND
                    user_id = :userId AND
                    memory_id = :memoryId AND
                    deleted_at IS NULL
                """,
                {"chatId": chatId, "userId": userId, "memoryId": memoryId},
            )
            if existing is None:
                return False

            await sqlProvider.execute(
                """
                UPDATE user_memories
                SET
                    deleted_at = :deletedAt,
                    updated_at = :updatedAt
                WHERE
                    chat_id = :chatId AND
                    user_id = :userId AND
                    memory_id = :memoryId AND
                    deleted_at IS NULL
                """,
                {
                    "chatId": chatId,
                    "userId": userId,
                    "memoryId": memoryId,
                    "deletedAt": now,
                    "updatedAt": now,
                },
            )

            # vecOnly=False so the provenance columns are also nulled —
            # otherwise getMemoriesWithoutEmbeddings would re-surface the
            # soft-deleted row for re-embedding. The vec0 row is deleted
            # so a deleted memory is never a semantic-search hit.
            await self.deleteMemoryEmbedding(chatId, userId, memoryId, vecOnly=False)
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
                (thread_id IS NULL OR thread_id = :threadId) AND
                deleted_at IS NULL
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
                permanent = 0 AND
                deleted_at IS NULL
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

        Single-row read used by the ``/memory_config`` per-memory detail
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
                memory_id = :memoryId AND
                deleted_at IS NULL
            """,
            {"chatId": chatId, "userId": userId, "memoryId": memoryId},
        )
        if row is None:
            return None
        return dbUtils.sqlToTypedDict(row, UserMemoryDict)

    async def getMemoriesByIds(
        self,
        memoryIds: List[str],
        *,
        chatId: Optional[int] = None,
        dataSource: Optional[str] = None,
    ) -> List[UserMemoryDict]:
        """Fetch memories by UUID list, including soft-deleted rows.

        The single read path that does NOT filter ``deleted_at``: a
        historical message that references a now-deleted memory must
        still resolve its content for LLM context reconstruction. UUIDs
        are globally unique, so no ``chatId``/``userId`` scoping is
        needed in the WHERE clause (internal callers only); the
        ``chatId`` / ``dataSource`` params are routing-only — they tell
        :meth:`DatabaseManager.getProvider` which data source to query
        on a cache miss. When both are ``None`` the default DB is used.

        Large ID lists are auto-chunked into batches of
        :data:`~internal.database.constants.MAX_SQL_VARIABLES` so the
        ``IN (:id0, …)`` expansion never exceeds the engine's bound-
        parameter limit (SQLite's default ``SQLITE_MAX_VARIABLE_COUNT``
        is 999). Per-chunk result sets are unioned; the method has no
        ``ORDER BY`` so chunking does not change the return semantics.

        Args:
            memoryIds: List of memory UUID hex strings.
            chatId: Optional chat ID for data-source routing. ``None``
                routes to the default source.
            dataSource: Optional explicit data-source name for routing.
                Takes precedence over ``chatId`` when both are set.

        Returns:
            List of :class:`UserMemoryDict` (including soft-deleted rows).
            Rows whose ``memory_id`` is not present are simply absent
            from the result (the caller maps request → result by
            ``memory_id``).
        """
        if not memoryIds:
            return []
        sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
        results: List[UserMemoryDict] = []
        # Chunk to stay under SQLITE_MAX_VARIABLE_COUNT (999). Each chunk
        # reuses :id0..:idN placeholders, so the param dict is rebuilt per
        # chunk (no cross-chunk key collision).
        for chunkStart in range(0, len(memoryIds), MAX_SQL_VARIABLES):
            chunk = memoryIds[chunkStart : chunkStart + MAX_SQL_VARIABLES]
            placeholders: List[str] = []
            fetchParams: dict[str, object] = {}
            for i, mid in enumerate(chunk):
                key = f"id{i}"
                placeholders.append(f":{key}")
                fetchParams[key] = mid
            rows = await sqlProvider.executeFetchAll(
                f"""
                SELECT {_SELECT_COLUMNS}
                FROM user_memories
                WHERE memory_id IN ({', '.join(placeholders)})
                """,
                fetchParams,
            )
            results.extend(dbUtils.sqlToTypedDict(row, UserMemoryDict) for row in rows)
        return results

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
        tag strings. Used by the ``/memory_config`` wizard's tag-filter
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
                    (:memoryType IS NULL OR type = :memoryType) AND
                    deleted_at IS NULL
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
        is applied via SQL ``LIKE`` against the JSON-serialised ``tags``
        column (ANY-match — a memory qualifies when it carries ANY of
        the listed tags). LIKE wildcards (``%``, ``_``) and the quote
        character (``"``) inside tag values are escaped so they match
        literally (see :func:`_escapeTagForLike` /
        :func:`_normalizeTags`). In semantic mode ``threadId`` and
        ``type`` are applied in the JOIN step on the authoritative
        ``user_memories`` columns (vec0 carries neither — both live only
        on ``user_memories``).

        Thread scoping: ``threadId is None`` returns memories from ALL
        threads for ``(chatId, userId)`` (no thread filter) — this is the
        mode the ``/memory_config`` wizard uses. When ``threadId`` is
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
                    params[f"tags{i}"] = f'%"{_escapeTagForLike(tag)}"%'
                    tagsWhereList.append(f"tags LIKE :tags{i} ESCAPE '\\'")

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
                    (:permanent IS NULL OR permanent = :permanent) AND
                    deleted_at IS NULL
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

        The model name string received at the public boundary is
        resolved to a ``model_id`` via the injected resolver (Decision
        D6 extended + D10); the vec0 partition key is the integer
        ``model_id`` (post-``migration_025`` shape).

        Args:
            chatId: Chat to search in.
            userId: User whose memories are searched.
            queryEmbedding: Query vector as a ``List[float]`` (serialised
                to float32 bytes internally).
            threadId: Optional thread scope post-filter (JOIN step).
            type: Optional ``MemoryType`` value filter, applied in the
                JOIN step on the authoritative ``user_memories.type``
                column (vec0 carries no ``type`` column — it lives only
                on ``user_memories``).
            tags: Optional list of tag strings (ANY-match via SQL LIKE
                on the JSON-serialised tags column — see module note).
            permanent: Optional permanent-flag filter (applied in vec0;
                ``permanent`` is immutable post-creation so it is never
                stale in the denormalised vec0 row).
            limit: Maximum results to return after ranking.
            embeddingModel: Name of the embedding model that produced
                ``queryEmbedding`` (selects the model-partitioned vec0
                table). Resolved to ``model_id`` internally before the
                vec0 lookup.
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
            # is undefined and the results would be arbitrary noise. Pure-Python
            # norm (Decision D8 — numpy retired from production code).
            queryNorm = math.sqrt(sum(x * x for x in queryEmbedding))
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

            # Resolve model_id via the injected resolver (Decision D6 extended + D10).
            modelId = await self._resolveModelId(embeddingModel, dim, dataSource=dataSource)

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
            # scoping (chat_id, user_id, model_id partition) and ``permanent``
            # (immutable post-creation → never stale in vec0) are pushed
            # into vec0. ``threadId`` and ``type`` are NOT carried as vec0
            # columns (they live only on the authoritative
            # ``user_memories`` row), so they are applied in the JOIN step
            # below on ``user_memories``. ``tags`` is JSON TEXT and is
            # likewise applied via SQL LIKE with wildcard escaping in the
            # JOIN step below.
            filterParts: List[str] = [
                "chat_id = :chatId",
                "user_id = :userId",
                "model_id = :modelId",
            ]
            filterParams: dict[str, str | int | float | None] = {
                "chatId": chatId,
                "userId": userId,
                "modelId": modelId,
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
            # applying the SQL-safe post-filters (``threadId``, ``type``,
            # ``tags``) on the AUTHORITATIVE user_memories columns. The
            # vec0 over-fetch (``MEMORY_SEARCH_TOPK_MULTIPLIER``) absorbs
            # the trimming.
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
                    fetchParams[f"tags{i}"] = f'%"{_escapeTagForLike(tag)}"%'
                    tagsWhereList.append(f"tags LIKE :tags{i} ESCAPE '\\'")

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
                    (:type IS NULL OR type = :type) AND
                    deleted_at IS NULL
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

        Handler-facing signature is unchanged (Decision D6 extended —
        callers keep passing the model name string); the repo resolves
        ``(embeddingModel, len(embedding))`` to a ``model_id`` internally
        via the injected resolver (Decision D10) before writing vec0 and
        ``user_memories.model_id``.

        Args:
            chatId: Chat the memory belongs to.
            userId: User the memory is about.
            memoryId: Memory identifier.
            embedding: Float vector (any length; becomes the dimension).
            embeddingModel: Model name that produced the embedding.

        Returns:
            True on success, False on any failure (never raises).

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

            dimensions = len(embedding)
            # Resolve model_id via the injected resolver (Decision D6 extended + D10).
            modelId = await self._resolveModelId(embeddingModel, dimensions)

            # Fetch the memory row to populate the vec0 ``permanent``
            # metadata column. NOTE: deleted_at IS NULL — a soft-deleted
            # memory must never be re-embedded. Today only the regen-cron
            # gatekeeper (which already filters deleted_at) and addMemory
            # (fresh live rows) reach here, but this guard is
            # defense-in-depth for any future caller.
            memoryRow = await sqlProvider.executeFetchOne(
                """
                SELECT permanent
                FROM user_memories
                WHERE
                    chat_id = :chatId AND
                    user_id = :userId AND
                    memory_id = :memoryId AND
                    deleted_at IS NULL
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
            # provenance UPDATE, leaving model_id = NULL so the regen
            # cron retries. Vec0 is the sole embedding store.
            try:
                if not await self._upsertVecMemoryEmbedding(
                    sqlProvider=sqlProvider,
                    chatId=chatId,
                    userId=userId,
                    memoryId=memoryId,
                    permanent=memoryRow["permanent"],
                    modelId=modelId,
                    embedding=embedding,
                ):
                    return False
            except Exception:
                return False

            await sqlProvider.execute(
                """
                UPDATE user_memories
                SET
                    model_id = :modelId,
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
                    "modelId": modelId,
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
        permanent: bool,
        modelId: int,
        embedding: list[float],
    ) -> bool:
        """Upsert a row into the dimension-specific vec0 memory table.

        Lazily creates ``vec_user_memories_{dimensions}`` on first use
        via :meth:`BaseSQLProvider.createVectorTable`. Uses DELETE +
        INSERT because vec0 does not support conventional UPSERT on
        metadata columns. Write failures are logged and the method
        returns ``False`` so the caller (:meth:`saveMemoryEmbedding`)
        can skip the provenance UPDATE and leave ``model_id = NULL`` —
        that keeps the memory visible to
        :meth:`getMemoriesWithoutEmbeddings` for re-embedding (vec0 is
        the sole embedding store; a silent failure would strand the
        memory with no searchable vector).

        Post-``migration_025`` shape (Decision D9): the vec0 table gains
        a ``model_id INTEGER PARTITION KEY`` (replacing the legacy
        ``model TEXT PARTITION KEY``). The partition key is the integer
        ``model_id`` allocated by :class:`EmbeddingModelsRepository`.

        Args:
            sqlProvider: SQL provider abstraction (must be writable and
                support vector search).
            chatId: Chat ID.
            userId: User ID.
            memoryId: Memory identifier.
            permanent: Permanent flag as int (0/1).
            modelId: Resolved ``model_id`` from the ``models`` lookup
                table; bound to the vec0 ``model_id`` partition key so a
                model swap does not cross-contaminate vector spaces.
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
                        {"name": "model_id", "columnType": VectorColumnType.INTEGER, "isPartitionKey": True},
                        {"name": "permanent", "columnType": VectorColumnType.INTEGER},
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
                f"(memory_id, chat_id, user_id, model_id, permanent, embedding) "
                f"VALUES (:memoryId, :chatId, :userId, :modelId, :permanent, :embedding)",
                {
                    "memoryId": memoryId,
                    "chatId": chatId,
                    "userId": userId,
                    "modelId": modelId,
                    "permanent": permanent,
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
                provenance-column reset (``model_id``) and only delete
                vec0 rows. Used by callers that manage the relational
                row themselves. When ``False`` (default), the provenance
                column is also nulled and ``updated_at`` bumped.

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
                        model_id = NULL,
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
        """Return memories whose stored provenance does not match the active model.

        Used by the regeneration cron to discover which memories still
        need a vector generated (or re-generated) under the chat's
        active embedding model. Post-``migration_025`` shape: the filter
        is a single-table predicate against ``user_memories.model_id``
        (no vec0 JOIN). Returns memories where ``model_id IS NULL`` OR
        ``model_id != currentModelId`` (resolved from *modelName* +
        *dimensions* via :meth:`_resolveModelId`). When *modelName* is
        ``None``, only rows with ``model_id IS NULL`` are returned.

        Args:
            chatId: Chat to scan.
            limit: Maximum number of rows to return.
            modelName: Current embedding model name. When provided (with
                *dimensions*), rows whose ``model_id`` is missing OR
                does not match the resolved ``model_id`` are returned.
                When ``None``, only never-embedded rows (``model_id IS
                NULL``) are returned.
            dimensions: When provided alongside *modelName*, resolves a
                single canonical ``model_id`` for ``(modelName,
                dimensions)`` via :meth:`_resolveModelId`.
            dataSource: Optional data source name for explicit routing.

        Returns:
            List of :class:`UserMemoryDict` ordered by ``updated_at``
            descending. Empty list on error.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            params: Dict[str, object] = {"chatId": chatId, "currentModelId": None}
            if modelName is not None and dimensions is not None:
                params["currentModelId"] = await self._resolveModelId(modelName, dimensions, dataSource=dataSource)

            query = f"""
                    SELECT {_SELECT_COLUMNS}
                    FROM user_memories
                    WHERE
                        chat_id = :chatId AND
                        deleted_at IS NULL AND
                        (model_id IS NULL OR
                            (:currentModelId IS NOT NULL AND model_id != :currentModelId)
                        )
                    ORDER BY updated_at DESC
                """
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
        currentDimensions: int,
    ) -> int:
        """Reset ``model_id`` on memories whose provenance no longer matches the active model.

        Called when the embedding model changes for a chat (detected by the
        caller via in-memory tracking). Resolves the canonical ``model_id``
        from ``(currentModel, currentDimensions)`` via
        :meth:`_resolveModelId`, deletes stale vec0 rows from every
        ``vec_user_memories_{N}`` table, and sets ``user_memories.model_id
        = NULL`` on every live row whose stored ``model_id`` does not match
        the resolved id. The regeneration cron then re-discovers those rows
        via :meth:`getMemoriesWithoutEmbeddings` and re-embeds them under
        the new model.

        Stateless and idempotent: on the common path (model unchanged) the
        UPDATE matches zero rows. Callers should gate this with their own
        change-detection logic to avoid unnecessary work.

        Vec0 cleanup mirrors the SQL UPDATE: every
        ``vec_user_memories_{N}`` table for the chat has its
        non-matching rows removed. The dimension-matching vec0 table has
        its non-matching-``model_id`` rows deleted (matching rows
        survive); tables belonging to a different dimensionality are
        cleared entirely for the chat. If the provider rejects a DELETE,
        the failure is logged and swallowed (best-effort mirror).

        Differences from the chat-history analog
        (:meth:`ChatEmbeddingsRepository.deleteObsoleteModelEmbeddings`):

        - Returns ``int`` (the count of reset rows) rather than ``bool``.
          The count is computed via ``COUNT(*)`` BEFORE the UPDATE
          because the provider's ``execute()`` returns ``None`` and does
          not expose the affected-row count.
        - Includes ``deleted_at IS NULL`` in the stale-row predicate:
          ``user_memories`` is soft-delete-aware, so a soft-deleted row
          must never be touched (it is already excluded from
          :meth:`getMemoriesWithoutEmbeddings`).

        Args:
            chatId: Chat to clean.
            currentModel: The currently-active embedding model name.
                Rows whose ``model_id`` does not resolve back to this
                model are cleared.
            currentDimensions: The currently-active embedding
                dimensionality. Combined with *currentModel* to resolve
                the single canonical ``model_id`` used in the stale-row
                predicate.

        Returns:
            The count of reset rows. ``0`` when no rows were stale OR
            on any internal error (never raises; the exception is
            logged).

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)

            currentModelId = await self._resolveModelId(currentModel, currentDimensions)

            # Delete their vec0 rows from every vec_user_memories_{N} table.
            if await sqlProvider.isVectorSearchSupported():
                try:
                    vecTables = await sqlProvider.listTables("vec_user_memories_%")
                    # Filter out vec0 shadow tables (vec_user_memories_384_info,
                    # vec_user_memories_384_chunks, etc.) — sqlite-vec uses
                    # internal shadow tables that also match the LIKE pattern
                    # and appear in sqlite_master with type='table', but they
                    # don't have our custom columns.
                    vecTables = [t for t in vecTables if re.match(r"^vec_user_memories_\d+$", t)]
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
                        "listTables not supported for chat %d; skipping vec0 memory cleanup",
                        chatId,
                    )
            staleWhere = (
                "chat_id = :chatId AND model_id IS NOT NULL "
                "AND deleted_at IS NULL "
                "AND model_id != :currentModelId"
            )
            staleParams: Dict[str, object] = {
                "chatId": chatId,
                "currentModelId": currentModelId,
            }

            # Count the stale rows BEFORE cleanup so the caller knows how
            # many were reset (the provider's execute() returns None, so
            # the UPDATE's affected-row count is not directly available).
            countRow = await sqlProvider.executeFetchOne(
                f"SELECT COUNT(*) AS cnt FROM user_memories WHERE {staleWhere}",
                staleParams,
            )
            resetCount = int(countRow["cnt"]) if countRow is not None else 0

            # Reset provenance on user_memories. THIS is the step that
            # re-surfaces stale rows for re-embedding: without it,
            # getMemoriesWithoutEmbeddings (which keys on model_id IS NULL
            # / != :currentModelId) would never see these rows again — the
            # regen cron's stale-detection loop would be broken.
            await sqlProvider.execute(
                f"UPDATE user_memories SET model_id = NULL WHERE {staleWhere}",
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
