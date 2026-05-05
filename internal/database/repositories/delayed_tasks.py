"""Delayed tasks repository module.

This module provides the DelayedTasksRepository class for managing delayed tasks
in the database. Delayed tasks are scheduled operations that should be executed
at a specific future time, such as sending reminders, processing queued messages,
or performing periodic maintenance tasks.

The repository extends BaseRepository and provides CRUD operations for delayed tasks,
including adding new tasks, updating task status, retrieving pending tasks, and
cleaning up old completed tasks. All operations are performed asynchronously and
support multi-source database access through the DatabaseManager.

Key Classes:
    DelayedTasksRepository: Main repository class for delayed tasks operations.

Example:
    # Create a delayed task
    repo = DelayedTasksRepository(db_manager)
    success = await repo.addDelayedTask(
        taskId="task_123",
        function="send_reminder",
        kwargs='{"user_id": 42, "message": "Hello"}',
        delayedTS=int(time.time()) + 3600
    )

    # Get pending tasks
    pending_tasks = await repo.getPendingDelayedTasks()
    for task in pending_tasks:
        print(f"Task {task['id']} scheduled for {task['delayed_ts']}")

    # Mark task as done
    await repo.updateDelayedTask(id="task_123", isDone=True)

    # Cleanup old completed tasks
    await repo.cleanupOldCompletedDelayedTasks(ttl=86400)  # 24 hours
"""

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
    """Repository for managing delayed tasks in the database.

    Provides methods to add, update, retrieve, and cleanup delayed tasks.
    Delayed tasks are operations scheduled for future execution, identified
    by a unique task ID and associated with a function name and its kwargs.

    This repository extends BaseRepository and leverages the DatabaseManager
    for multi-source database access. All operations are asynchronous and
    support both read and write operations across configured data sources.

    Attributes:
        manager: DatabaseManager instance that provides access to database
                providers and handles multi-source database operations. This
                manager is inherited from BaseRepository and used for all
                database interactions.

    Example:
        repo = DelayedTasksRepository(db_manager)

        # Add a new delayed task
        await repo.addDelayedTask(
            taskId="reminder_123",
            function="send_reminder",
            kwargs='{"user_id": 42}',
            delayedTS=int(time.time()) + 3600
        )

        # Retrieve pending tasks
        tasks = await repo.getPendingDelayedTasks()

        # Mark task as completed
        await repo.updateDelayedTask(id="reminder_123", isDone=True)
    """

    __slots__ = ()
    """Restricts instance attributes to prevent dynamic attribute creation.

    Using __slots__ provides memory optimization by preventing the creation of
    a __dict__ for each instance, which is beneficial for repository classes
    that may be instantiated frequently. It also helps catch typos in attribute
    assignments at runtime.
    """

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialize the delayed tasks repository with a database manager.

        Sets up the repository with access to the DatabaseManager, which provides
        the interface for all database operations. The manager handles connection
        pooling, multi-source routing, and transaction management.

        Args:
            manager: DatabaseManager instance for accessing database providers
                    and executing database operations. This manager should be
                    properly initialized with database connections before being
                    passed to the repository.

        Returns:
            None

        Raises:
            TypeError: If manager is not an instance of DatabaseManager.
        """
        super().__init__(manager)

    ###
    # Delayed Tasks manipulation (see bot/models.py)
    ###

    async def addDelayedTask(self, taskId: str, function: str, kwargs: str, delayedTS: int) -> bool:
        """Add a delayed task to the database.

        Creates a new delayed task record with the specified parameters. The task
        will be scheduled for execution at the specified timestamp. The function
        name and kwargs are stored as strings and can be used to dynamically
        execute the task when it's due.

        Args:
            taskId: Unique task identifier string. This should be a unique value
                    that can be used to reference the task later for updates or
                    queries. Common patterns include UUIDs or composite keys.
            function: Name of the function to execute when the task is due. This
                      should be a string that can be resolved to an actual function
                      in the application code at runtime.
            kwargs: JSON-serialized string containing keyword arguments to pass to
                    the function when executed. Must be valid JSON format.
            delayedTS: Unix timestamp (seconds since epoch) when the task should be
                       executed. Tasks with timestamps in the past may be executed
                       immediately on the next processing cycle.

        Returns:
            bool: True if the task was successfully added to the database, False
                  if an error occurred during insertion.

        Raises:
            Exception: Any database-related exception during insertion is caught
                       and logged, returning False instead of propagating.

        Note:
            Writes to default source. Cannot write to readonly sources.
            The task is created with is_done=False and current timestamps for
            created_at and updated_at fields.
        """
        try:
            sqlProvider = await self.manager.getProvider(readonly=False)
            await sqlProvider.execute(
                """
                INSERT INTO delayed_tasks
                    (id, function, kwargs, delayed_ts, created_at, updated_at)
                VALUES
                    (:id, :function, :kwargs, :delayedTS, :createdAt, :updatedAt)
            """,
                {
                    "id": taskId,
                    "function": function,
                    "kwargs": kwargs,
                    "delayedTS": delayedTS,
                    "createdAt": dbUtils.getCurrentTimestamp(),
                    "updatedAt": dbUtils.getCurrentTimestamp(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add delayed task: {e}")
            return False

    async def updateDelayedTask(self, id: str, isDone: bool) -> bool:
        """Update a delayed task's completion status in the database.

        Marks a delayed task as completed or incomplete by updating the is_done
        flag. This is typically called after a task has been executed to mark
        it as done, or to reset a task's status for re-execution.

        Args:
            id: Unique task identifier string that was used when the task was
                created via addDelayedTask. This identifies which task to update.
            isDone: Boolean flag indicating whether the task has been completed.
                    True marks the task as done, False marks it as pending.

        Returns:
            bool: True if the task was successfully updated in the database, False
                  if an error occurred during the update or if the task ID doesn't
                  exist.

        Raises:
            Exception: Any database-related exception during update is caught
                       and logged, returning False instead of propagating.

        Note:
            Writes to default source. Cannot write to readonly sources.
            The updated_at timestamp is automatically set to the current time.
        """
        try:
            sqlProvider = await self.manager.getProvider(readonly=False)
            await sqlProvider.execute(
                """
                UPDATE delayed_tasks
                SET
                    is_done = :isDone,
                    updated_at = :updatedAt
                WHERE
                    id = :id
            """,
                {
                    "id": id,
                    "isDone": isDone,
                    "updatedAt": dbUtils.getCurrentTimestamp(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update delayed task: {e}")
            return False

    async def getPendingDelayedTasks(self, *, dataSource: Optional[str] = None) -> List[DelayedTaskDict]:
        """Get all pending delayed tasks from the database.

        Retrieves all delayed tasks that have not yet been completed (is_done=False).
        This is typically called by a task scheduler or worker to find tasks that
        need to be executed. The returned tasks can be filtered by their delayed_ts
        to determine which ones are due for execution.

        Args:
            dataSource: Optional data source name to query. If None, uses the default
                        data source configured in the DatabaseManager. This allows
                        querying from specific read replicas or alternative databases.

        Returns:
            List[DelayedTaskDict]: List of DelayedTaskDict containing all pending
                                   tasks (is_done=False). Each dictionary includes
                                   task id, function name, kwargs, delayed timestamp,
                                   and metadata. Returns an empty list on error or if
                                   no pending tasks exist.

        Raises:
            Exception: Any database-related exception during query is caught and
                       logged, returning an empty list instead of propagating.

        Note:
            This is a read-only operation and can be performed on readonly sources.
            Tasks are returned in the order they are stored in the database.
        """
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
        """Delete old completed delayed tasks from the database.

        Removes completed delayed tasks that were updated before the specified
        time-to-live threshold. This helps maintain database performance by
        preventing accumulation of old completed tasks. Only tasks with
        is_done=True are affected.

        Args:
            ttl: Time-to-live in seconds. Tasks that were updated (marked as done)
                 before this time will be deleted. If None or 0, deletes all
                 completed tasks regardless of age. For example, ttl=86400 would
                 delete tasks completed more than 24 hours ago.
            dataSource: Optional data source name to query. If None, uses the default
                        data source configured in the DatabaseManager.

        Returns:
            bool: True if cleanup succeeded (even if no tasks were deleted), False
                  if an error occurred during the deletion operation.

        Raises:
            Exception: Any database-related exception during deletion is caught and
                       logged, returning False instead of propagating.

        Note:
            Writes to default source. Cannot write to readonly sources.
            Only completed tasks (is_done=True) are deleted. Pending tasks are
            never affected by this operation.
        """

        if ttl is None:
            ttl = 0
        maxUpdatedAt: datetime.datetime = dbUtils.getCurrentTimestamp() - datetime.timedelta(seconds=ttl)

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
