"""TODO: write docstring"""

import datetime
import logging
from typing import List, Optional

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import (
    DelayedTaskDict,
)
from .base import BaseRepository

logger = logging.getLogger(__name__)


class DelayedTasksRepository(BaseRepository):
    """TODO: write docstring"""

    __slots__ = ()

    def __init__(self, manager: DatabaseManager):
        super().__init__(manager)

    ###
    # Delayed Tasks manipulation (see bot/models.py)
    ###

    async def addDelayedTask(self, taskId: str, function: str, kwargs: str, delayedTS: int) -> bool:
        """
        Add a delayed task to the database.

        Args:
            taskId: Task identifier
            function: Function name
            kwargs: JSON kwargs
            delayedTS: Delayed timestamp

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(readonly=False)
            await sqlProvider.execute(
                """
                INSERT INTO delayed_tasks
                    (id, function, kwargs, delayed_ts)
                VALUES
                    (:id, :function, :kwargs, :delayedTS)
            """,
                {
                    "id": taskId,
                    "function": function,
                    "kwargs": kwargs,
                    "delayedTS": delayedTS,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add delayed task: {e}")
            return False

    async def updateDelayedTask(self, id: str, isDone: bool) -> bool:
        """
        Update a delayed task in the database.

        Args:
            id: Task identifier
            isDone: Whether task is done

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(readonly=False)
            await sqlProvider.execute(
                """
                UPDATE delayed_tasks
                SET
                    is_done = :isDone,
                    updated_at = CURRENT_TIMESTAMP
                WHERE
                    id = :id
            """,
                {
                    "id": id,
                    "isDone": isDone,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update delayed task: {e}")
            return False

    async def getPendingDelayedTasks(self, *, dataSource: Optional[str] = None) -> List[DelayedTaskDict]:
        """Get all pending delayed tasks from the database."""
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)
            rows = await sqlProvider.executeFetchAll(
                """
                SELECT * FROM delayed_tasks
                WHERE
                    is_done = :isDone
            """,
                {
                    "isDone": False,
                },
            )
            return [dbUtils.sqlToTypedDict(row, DelayedTaskDict) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get pending delayed tasks: {e}")
            return []

    async def cleanupOldCompletedDelayedTasks(self, ttl: Optional[int], *, dataSource: Optional[str] = None) -> bool:
        """Cleanup old completed tasks"""

        if ttl is None:
            ttl = 0
        maxUpdatedAt = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=ttl)

        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=False)
            # Clear old entries of specific cache type
            await sqlProvider.execute(
                """
                DELETE FROM delayed_tasks
                WHERE
                    is_done = TRUE AND
                    updated_at < :maxUpdatedAt
                """,
                {
                    "maxUpdatedAt": maxUpdatedAt,
                },
            )

            logger.info(f"Cleared completed delayed tasks (older than {ttl}s).")
            return True
        except Exception as e:
            logger.error(f"Failed to clear old cache entries: {e}")
            return False
