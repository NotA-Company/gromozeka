"""Repository for the ``models`` embedding-provenance lookup table.

Provides :meth:`EmbeddingModelsRepository.getOrCreateModelId` — the app-side
allocation point for the small integer that identifies a distinct
``(model, dimensions)`` pair. Every embedding write resolves its
``model_id`` through this method.

The ``models`` table is created by ``migration_025`` (Phase 2 of the
embedding-model-lookup refactor). The repository is constructed first
in ``Database.__init__`` and its bound ``getOrCreateModelId`` is
injected as the ``modelIdResolver`` keyword argument into
``ChatEmbeddingsRepository``, ``ChatSearchRepository``, and
``UserMemoriesRepository`` (Decision D10).

**Multi-source routing:** every method on this repository accepts an
optional ``dataSource: Optional[str] = None`` keyword argument for
routing on multi-source deployments. The ``models`` table itself is
global (not per-chat), so it must exist on whatever source is pinned —
in single-source deployments this is automatic; in multi-source
deployments global tables must be replicated or pinned to the same
source. The cache in :meth:`getOrCreateModelId` is per-instance and
source-agnostic: a cache hit returns immediately WITHOUT consulting
``dataSource`` (``dataSource`` only matters on a cache miss, where it
routes the provider acquisition).
"""

import logging
from typing import Dict, List, Optional, Tuple

import lib.utils as libUtils
from lib.db.manager import DatabaseManager

from .. import utils as dbUtils
from ..models import ModelDict
from .base import BaseRepository

logger = logging.getLogger(__name__)


class EmbeddingModelsRepository(BaseRepository):
    """Lookup and allocation for the ``models`` table.

    Holds a process-local cache ``{(model, dimensions): model_id}`` so the
    common path (a hot model that's already been allocated) is a single
    dict hit and skips the DB round-trip entirely. The cache is
    per-instance; Gromozeka is a single-process app, so there is no
    cross-writer hazard.

    Every method accepts a keyword-only ``dataSource`` for multi-source
    routing; see the module docstring for the global-table / cache
    interaction.

    Attributes:
        _cache: Process-local ``{(model, dimensions): model_id}`` map.
    """

    # NOTE: ``manager`` is intentionally NOT redeclared here — the base
    # class ``BaseRepository`` already declares it in its ``__slots__``,
    # and re-declaring a slot at the subclass level raises
    # ``ValueError: 'manager' in __slots__ conflicts with class variable``.
    # Only new attributes owned by this subclass go in the tuple. This
    # mirrors the pattern in ``ChatEmbeddingsRepository`` (``__slots__ = ()``
    # — it adds no new slotted attributes).
    __slots__ = ("_cache",)

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialise the repository with an empty cache.

        Args:
            manager: Database manager instance for provider access. Methods
                on this repo forward their keyword-only ``dataSource``
                argument to ``manager.getProvider`` for multi-source
                routing; when ``dataSource`` is ``None`` the default data
                source is used.
        """
        super().__init__(manager)
        self._cache: Dict[Tuple[str, int], int] = {}

    async def getOrCreateModelId(self, model: str, dimensions: int, *, dataSource: Optional[str] = None) -> int:
        """Return the ``model_id`` for *model*/*dimensions*, allocating one if needed.

        Cache-first: a hit returns immediately. On miss, allocate the next
        sequential id (``COALESCE(MAX(model_id), 0) + 1``), call
        ``provider.upsert(..., updateExpressions={})`` (portable
        ``ON CONFLICT DO NOTHING`` — see below), then ``SELECT`` back the
        canonical id (handles the race where another row sneaked in between
        the MAX and the INSERT). Cache and return.

        The allocation contract is **probe-then-insert**, NOT plain
        ``INSERT OR IGNORE``: the app picks the next id via
        ``COALESCE(MAX(model_id), 0) + 1`` and the UNIQUE constraint on
        ``(model, dimensions)`` is the defensive second guard. If a row
        with the same ``(model, dimensions)`` was inserted between the
        MAX query and the upsert, the upsert is short-circuited (DO
        NOTHING) and the subsequent SELECT-back returns the canonical id
        of the row that won the race. The caller therefore never observes
        a duplicate id and never sees an ``IntegrityError`` on the
        UNIQUE constraint. The allocation is idempotent: a repeated call
        for the same ``(model, dimensions)`` pair returns the existing
        id without allocating a new one.

        Args:
            model: Embedding model name string (e.g. the resolved value
                of the ``EMBEDDING_MODEL`` chat setting).
            dimensions: Vector dimensionality (e.g. 384, 1024).
            dataSource: Optional explicit data source for multi-source
                routing. Only consulted on a cache MISS — a cache hit
                returns immediately without acquiring a provider, so
                ``dataSource`` has no effect on the cache-hit path.

        Returns:
            The integer ``model_id``.
        """
        cacheKey = (model, dimensions)
        cached = self._cache.get(cacheKey)
        if cached is not None:
            # Safe because model_id allocation starts at 1 (COALESCE leg of MAX).
            return cached

        sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=False)
        now = libUtils.now()

        # Allocate next id app-side (AGENTS.md: never delegate ID generation
        # to the DB). ``upsert(..., updateExpressions={})`` maps to
        # ``ON CONFLICT(model, dimensions) DO NOTHING`` on every provider
        # (verified in ``SQLite3Provider.upsert`` at
        # lib/db/providers/sqlite3.py:430-443 — empty
        # updateExpressions triggers the DO NOTHING branch). The subsequent
        # SELECT-back returns the canonical id regardless of whether the
        # INSERT actually inserted or was short-circuited by the conflict.
        idRow = await sqlProvider.executeFetchOne("SELECT COALESCE(MAX(model_id), 0) + 1 AS nextId FROM models")
        # Defensive: ``MAX`` over an empty table still returns one row
        # (the COALESCE leg); a None here means the provider violated its
        # ``executeFetchOne`` contract. Surface it loudly rather than
        # crashing on the subsequent subscript.
        if idRow is None:
            raise RuntimeError("SELECT MAX(model_id) returned no rows — provider contract violation")
        nextId = int(idRow["nextId"])
        await sqlProvider.upsert(
            table="models",
            values={
                "model_id": nextId,
                "model": model,
                "dimensions": dimensions,
                "created_at": now,
            },
            conflictColumns=["model", "dimensions"],
            updateExpressions={},  # DO NOTHING on conflict — see sqlite3.py:426-439
        )
        canonical = await sqlProvider.executeFetchOne(
            "SELECT model_id FROM models WHERE model = :model AND dimensions = :dimensions",
            {"model": model, "dimensions": dimensions},
        )
        # The upsert above either inserted our row or short-circuited on a
        # UNIQUE conflict. Either way, the SELECT-back MUST find a row —
        # if it doesn't, the table is in an inconsistent state (e.g. the
        # row was deleted between the upsert and the SELECT). Surface it.
        if canonical is None:
            raise RuntimeError(
                f"models row for ({model!r}, {dimensions}) vanished between upsert and "
                "SELECT-back — provider contract violation or external writer"
            )
        modelId = int(canonical["model_id"])
        self._cache[cacheKey] = modelId
        return modelId

    async def getModelById(self, modelId: int, *, dataSource: Optional[str] = None) -> Optional[ModelDict]:
        """Fetch a single model row by id (diagnostic/admin use).

        Args:
            modelId: The ``model_id`` primary key.
            dataSource: Optional explicit data source for multi-source
                routing — routes this read to a non-default source.

        Returns:
            :class:`ModelDict` with ``model_id`` / ``model`` / ``dimensions``
            / ``created_at``, or ``None`` if no row matches.
        """
        sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)
        row = await sqlProvider.executeFetchOne(
            "SELECT model_id, model, dimensions, created_at FROM models WHERE model_id = :modelId",
            {"modelId": modelId},
        )
        if row is None:
            return None
        # Convert the raw provider row into the typed dict shape — this is
        # the repo convention in this codebase (see
        # ``ChatMessagesRepository.getChatMessageByMessageId`` which calls
        # ``dbUtils.sqlToTypedDict`` on the fetched row). Repositories
        # return typed dicts, not raw rows.
        return dbUtils.sqlToTypedDict(row, ModelDict)

    async def listModels(self, *, dataSource: Optional[str] = None) -> List[ModelDict]:
        """List all known models (diagnostic/admin use).

        Args:
            dataSource: Optional explicit data source for multi-source
                routing — routes this read to a non-default source.

        Returns:
            List of :class:`ModelDict` rows ordered by ``model_id``.
        """
        sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)
        rows = await sqlProvider.executeFetchAll(
            "SELECT model_id, model, dimensions, created_at FROM models ORDER BY model_id"
        )
        return [dbUtils.sqlToTypedDict(row, ModelDict) for row in rows]
