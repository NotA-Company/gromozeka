"""Repository for divination layouts cache.

This module exposes DivinationsLayoutsRepository, which caches layout
definitions for divination systems (tarot, runes, etc.) keyed by the
composite (system_id, layout_name) primary key.
"""

import logging
import re
from collections.abc import Sequence
from typing import Optional

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import DivinationLayoutDict
from ..providers import ExcludedValue, QueryResultFetchOne
from .base import BaseRepository

logger = logging.getLogger(__name__)


class DivinationLayoutsRepository(BaseRepository):
    """Repository for divination layouts cache.

    Caches layout definitions from external divination APIs to avoid
    repeated API calls. Each layout is keyed by (system_id, layout_name).

    Attributes:
        manager: Database manager instance.
    """

    __slots__ = ()

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialize the divination layouts repository.

        Args:
            manager: DatabaseManager for provider access.

        Returns:
            None
        """
        super().__init__(manager)

    async def getLayout(self, systemId: str, layoutName: str) -> Optional[DivinationLayoutDict]:
        """Retrieve a cached layout definition.

        Args:
            systemId: The divination system ID (e.g., 'tarot', 'runes').
            layoutName: The layout name within the system.

        Returns:
            Dictionary with layout definition if found, None otherwise.

        Note:
            Returns None if the layout is not in cache or an error occurs.
        """
        try:
            sqlProvider = await self.manager.getProvider(readonly=True)

            searchFor = [layoutName.strip()]
            # Try to drop everything between parentheses
            noParentheses = re.sub(r"\(.*\)", "", layoutName)
            if noParentheses != layoutName:
                searchFor.append(noParentheses.strip())

            selectPrefix = """
                    SELECT
                        *
                    FROM divination_layouts
                    WHERE system_id = :systemId AND (
                    """
            row: QueryResultFetchOne = None
            for s in searchFor:
                logger.debug(f"Searching for {s}")

                row = await sqlProvider.executeFetchOne(
                    selectPrefix
                    + sqlProvider.getCaseInsensitiveComparison("layout_id", "layoutName")
                    + " OR \n"
                    + sqlProvider.getCaseInsensitiveComparison("name_en", "layoutName")
                    + " OR \n"
                    + sqlProvider.getCaseInsensitiveComparison("name_ru", "layoutName")
                    + ")",
                    {
                        "systemId": systemId,
                        "layoutName": layoutName,
                    },
                )
                if row:
                    break

                row = await sqlProvider.executeFetchOne(
                    selectPrefix
                    + sqlProvider.getLikeComparison("layout_id", "layoutName")
                    + " OR \n"
                    + sqlProvider.getLikeComparison("name_en", "layoutName")
                    + " OR \n"
                    + sqlProvider.getLikeComparison("name_ru", "layoutName")
                    + ")",
                    {
                        "systemId": systemId,
                        "layoutName": f"%{layoutName}%",
                    },
                )
                if row:
                    break

            if row:
                return dbUtils.sqlToTypedDict(row, DivinationLayoutDict)
            return None
        except Exception as e:
            logger.error(f"Failed to get layout {systemId}/{layoutName}: {e}")
            return None

    def isNegativeCacheEntry(self, layoutDict: Optional[DivinationLayoutDict]) -> bool:
        """Check if a layout dictionary represents a negative cache entry.

        Negative cache entries have empty names, n_symbols=0, and empty positions.

        Args:
            layoutDict: Layout dictionary from cache, or None.

        Returns:
            True if this is a negative cache entry, False otherwise.
        """
        if layoutDict is None:
            return False
        return (
            layoutDict.get("name_en") == ""
            and layoutDict.get("name_ru") == ""
            and layoutDict.get("n_symbols", 0) == 0
            and layoutDict.get("positions") == []
        )

    async def saveLayout(
        self,
        systemId: str,
        layoutId: str,
        nameEn: str,
        nameRu: str,
        nSymbols: int,
        positions: Sequence[str],
        description: str,
    ) -> bool:
        """Save or update a layout definition in cache using provider.upsert().

        Args:
            systemId: The divination system ID (e.g., 'tarot', 'runes').
            layoutId: Machine-readable layout identifier.
            nameEn: English layout name (source of truth).
            nameRu: Russian layout name.
            nSymbols: Number of symbols/positions in the layout.
            positions: List of position definitions (JSON-serializable).
            description: Optional layout description.

        Returns:
            True on success, False otherwise (failure is logged).
        """
        try:
            sqlProvider = await self.manager.getProvider(readonly=False)
            now = dbUtils.getCurrentTimestamp()

            await sqlProvider.upsert(
                table="divination_layouts",
                values={
                    "system_id": systemId,
                    "layout_id": layoutId,
                    "name_en": nameEn,
                    "name_ru": nameRu,
                    "n_symbols": nSymbols,
                    "positions": positions,
                    "description": description,
                    "created_at": now,
                    "updated_at": now,
                },
                conflictColumns=["system_id", "layout_id"],
                updateExpressions={
                    "name_en": ExcludedValue(),
                    "name_ru": ExcludedValue(),
                    "n_symbols": ExcludedValue(),
                    "positions": ExcludedValue(),
                    "description": ExcludedValue(),
                    "updated_at": ":updated_at",  # Use parameter placeholder
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save layout {systemId}/{layoutId}: {e}")
            return False

    async def saveNegativeCache(self, systemId: str, layoutId: str) -> bool:
        """Save a negative cache entry for a non-existent layout.

        This prevents repeated API calls for layouts that don't exist.

        Args:
            systemId: The divination system ID.
            layoutId: The layout ID that doesn't exist.

        Returns:
            True on success, False otherwise (failure is logged).
        """
        try:
            sqlProvider = await self.manager.getProvider(readonly=False)
            now = dbUtils.getCurrentTimestamp()

            await sqlProvider.upsert(
                table="divination_layouts",
                values={
                    "system_id": systemId,
                    "layout_id": layoutId,
                    "name_en": "",
                    "name_ru": "",
                    "n_symbols": 0,
                    "positions": [],
                    "description": "",
                    "created_at": now,
                    "updated_at": now,
                },
                conflictColumns=["system_id", "layout_id"],
                updateExpressions={
                    "updated_at": now,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save negative cache {systemId}/{layoutId}: {e}")
            return False
