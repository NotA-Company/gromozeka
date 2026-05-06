"""Repository for divination readings, dood!

This module exposes :class:`DivinationsRepository`, which persists tarot/runes
readings keyed by the originating user-command message via the composite
``(chat_id, message_id)`` primary key.
"""

import logging
from collections.abc import Sequence
from typing import Optional

from internal.models import MessageIdType

from .. import utils as dbUtils
from ..manager import DatabaseManager
from .base import BaseRepository

logger = logging.getLogger(__name__)


class DivinationsRepository(BaseRepository):
    """Repository for divination readings, dood.

    Stores tarot/runes reading rows linked to the originating user-command
    message via the composite PK ``(chat_id, message_id)``. Failure to
    persist must NOT block the user reply — every public method swallows
    exceptions and returns a boolean status, logging on failure.
    """

    __slots__ = ()

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialize the divinations repository, dood.

        Args:
            manager: DatabaseManager for provider access.

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
        """Insert a single divination reading row, dood.

        Args:
            chatId: Originating chat id.
            messageId: Originating message id (str-coerced for cross-platform).
            userId: User who requested the reading.
            systemId: ``'tarot'`` | ``'runes'``.
            deckId: ``'rws'`` | ``'elder_futhark'``.
            layoutId: Layout id (e.g. ``'three_card'``).
            question: Free-form user question (may be ``''``).
            drawsJson: Drawn symbols. Either an already-serialized JSON
                ``str`` or a ``Sequence[dict]``; in the latter case the
                underlying SQL provider serializes it to a JSON string via
                ``convertContainerElementsToSQLite`` before binding. The DB
                column is ``TEXT`` and is expected to hold a JSON document.
            interpretation: LLM-generated interpretation text.
            imagePrompt: Final rendered image prompt, or ``None``.
            invokedVia: How the reading was triggered
                (``'command'`` | ``'llm_tool'``).

        Returns:
            ``True`` on success, ``False`` otherwise (failure is logged).

        Note:
            Writes to default source. Cannot write to readonly sources.
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
