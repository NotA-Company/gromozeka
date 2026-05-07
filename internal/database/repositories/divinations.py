"""Repository for divination readings and cached layout definitions, dood!

This module provides the DivinationsRepository class which handles all database
operations related to divination readings (tarot and runes), including persisting
readings keyed by the originating user-command message, caching layout definitions
to avoid repeated API calls, and managing negative cache entries for non-existent
layouts.
"""

import logging
import re
from collections.abc import Sequence
from typing import Optional

from internal.models import MessageIdType

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import DivinationLayoutDict
from ..providers import ExcludedValue, QueryResultFetchOne
from .base import BaseRepository

logger = logging.getLogger(__name__)


class DivinationsRepository(BaseRepository):
    """Repository for divination readings and layout definitions.

    Manages persistence of tarot/runes reading rows linked to the originating
    user-command message via the composite PK (chat_id, message_id). Also provides
    caching for layout definitions to reduce external API calls and supports
    negative caching for non-existent layouts.

    All public methods swallow exceptions and return boolean status to prevent
    database failures from blocking user replies. Failures are logged for debugging.

    Attributes:
        manager: DatabaseManager instance for accessing database providers
                and executing database operations across multiple sources.
    """

    __slots__ = ()  # No additional slots needed beyond base class, dood!

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialize the divinations repository, dood!

        Args:
            manager (DatabaseManager): DatabaseManager instance for provider access

        Returns:
            None
        """
        super().__init__(manager)

    async def insertReading(
        self,
        *,
        chatId: int,
        messageId: MessageIdType,
        userId: int,
        systemId: str,
        deckId: str,
        layoutId: str,
        question: str,
        drawsJson: str | Sequence[dict],
        interpretation: str,
        imagePrompt: Optional[str],
        invokedVia: str,
    ) -> bool:
        """Insert a single divination reading row, dood!

        Persists a tarot or runes reading to the database, including all draw
        data, LLM interpretation, and image generation prompt. The reading is
        linked to the originating command message via composite primary key.

        Args:
            chatId (int): Originating chat identifier
            messageId (MessageIdType): Originating message identifier (str-coerced for
                    cross-platform compatibility)
            userId (int): User ID of whoever requested the reading
            systemId (str): Divination system identifier ('tarot' or 'runes')
            deckId (str): Deck identifier ('rws', 'elder_futhark', etc.)
            layoutId (str): Layout identifier (e.g., 'three_card', 'celtic_cross')
            question (str): Free-form user question (may be empty string)
            drawsJson (str | Sequence[dict]): Drawn symbols as either an already-serialized
                    JSON string or a Sequence[dict]. If a Sequence is provided, the SQL
                    provider serializes it via convertContainerElementsToSQLite before binding.
                    Stored in TEXT column as JSON document.
            interpretation (str): LLM-generated interpretation text
            imagePrompt (Optional[str]): Final rendered image prompt, or None if not generated
            invokedVia (str): How the reading was triggered ('command' or 'llm_tool')

        Returns:
            bool: True if insertion succeeded, False otherwise

        Raises:
            Exception: If database operation fails (caught and logged)

        Note:
            Writes to the default source based on chatId routing. Cannot write to
            readonly sources. Failures are logged but do not raise exceptions.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.execute(
                """
                INSERT INTO divinations
                    (chat_id, message_id, user_id, system_id, deck_id,
                     layout_id, question, draws_json, interpretation,
                     image_prompt, invoked_via, created_at)
                VALUES
                    (:chatId, :messageId, :userId, :systemId, :deckId,
                     :layoutId, :question, :drawsJson, :interpretation,
                     :imagePrompt, :invokedVia, :createdAt)
                """,
                {
                    "chatId": chatId,
                    "messageId": str(messageId),
                    "userId": userId,
                    "systemId": systemId,
                    "deckId": deckId,
                    "layoutId": layoutId,
                    "question": question,
                    "drawsJson": drawsJson,
                    "interpretation": interpretation,
                    "imagePrompt": imagePrompt,
                    "invokedVia": invokedVia,
                    "createdAt": dbUtils.getCurrentTimestamp(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to insert divination row chat={chatId} msg={messageId}: {e}")
            return False

    async def getLayout(self, systemId: str, layoutName: str) -> Optional[DivinationLayoutDict]:
        """Retrieve a cached layout definition, dood!

        Searches for a layout by trying multiple matching strategies: exact case-insensitive
        match on layout_id/name_en/name_ru, partial match using LIKE operator, and
        fallback to stripping content in parentheses from the layout name.

        Args:
            systemId (str): The divination system ID (e.g., 'tarot', 'runes')
            layoutName (str): The layout name or identifier to search for

        Returns:
            Optional[DivinationLayoutDict]: Dictionary with layout definition if found,
                    None if not found or on error

        Raises:
            Exception: If database operation fails (caught and logged)

        Note:
            Returns None if layout is not in cache or an error occurs. Search is
            performed in this order: exact match, suffix match (after stripping
            parentheses), partial match with wildcards.
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
        """Check if a layout dictionary represents a negative cache entry, dood!

        Negative cache entries are used to prevent repeated API calls for layouts
        that do not exist. They are identified by empty names, n_symbols=0, and
        empty positions list.

        Args:
            layoutDict (Optional[DivinationLayoutDict]): Layout dictionary from cache,
                    or None

        Returns:
            bool: True if this is a negative cache entry, False otherwise
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
        """Save or update a layout definition in cache, dood!

        Uses provider.upsert() to insert new layouts or update existing ones,
        ensuring idempotent cache updates. Updated_at timestamp is refreshed
        on every insert or update.

        Args:
            systemId (str): The divination system ID (e.g., 'tarot', 'runes')
            layoutId (str): Machine-readable layout identifier
            nameEn (str): English layout name (source of truth)
            nameRu (str): Russian layout name
            nSymbols (int): Number of symbols/positions in the layout
            positions (Sequence[str]): List of position definitions (JSON-serializable)
            description (str): Optional layout description

        Returns:
            bool: True if save/update succeeded, False otherwise

        Raises:
            Exception: If database operation fails (caught and logged)
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
        """Save a negative cache entry for a non-existent layout, dood!

        Prevents repeated external API calls for layouts that do not exist.
        Negative cache entries are identified by empty names and n_symbols=0.

        Args:
            systemId (str): The divination system ID
            layoutId (str): The layout ID that doesn't exist

        Returns:
            bool: True if save succeeded, False otherwise

        Raises:
            Exception: If database operation fails (caught and logged)
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
