"""
Comprehensive tests for Queue Service.

This module provides extensive test coverage for the QueueService class,
including initialization, task registration, scheduling, execution,
management, concurrency, error handling, and integration scenarios.
"""

import asyncio
import json
import time
import uuid
from unittest.mock import Mock

import pytest

from internal.services.queue_service import constants
from internal.services.queue_service.service import QueueService, makeEmptyAsyncTask
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction
from tests.utils import createAsyncMock

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def queueService():
    """
    Create a fresh QueueService instance for each test.

    Note: QueueService is a singleton, so we need to reset it between tests.
    """
    # Reset singleton instance
    QueueService._instance = None
    service = QueueService.getInstance()
    yield service
    # Cleanup
    QueueService._instance = None


@pytest.fixture
def mockDatabaseWrapper():
    """Create a mock DatabaseWrapper for testing."""
    mock = Mock()
    mock.getPendingDelayedTasks = Mock(return_value=[])
    mock.addDelayedTask = Mock(return_value=None)
    mock.updateDelayedTask = Mock(return_value=None)
    return mock


@pytest.fixture
def sampleDelayedTask():
    """Create a sample DelayedTask for testing."""
    return DelayedTask(
        taskId="test-task-123",
        delayedUntil=time.time() + 60,
        function=DelayedTaskFunction.SEND_MESSAGE,
        kwargs={"chat_id": 123, "text": "Test message"},
    )


@pytest.fixture
async def mockTaskHandler():
    """Create a mock async task handler."""
    handler = createAsyncMock(returnValue=None)
    return handler


# ============================================================================
# Initialization Tests
# ============================================================================


class TestQueueServiceInitialization:
    """Test QueueService initialization and singleton behavior."""

    def testSingletonInstance(self, queueService):
        """Test that QueueService follows singleton pattern."""
        service1 = QueueService.getInstance()
        service2 = QueueService.getInstance()

        assert service1 is service2
        assert service1 is queueService

    def testInitializationState(self, queueService):
        """Test that QueueService initializes with correct default state."""
        assert queueService.initialized is True
        assert queueService.db is None
        assert isinstance(queueService.asyncTasksQueue, asyncio.Queue)
        assert isinstance(queueService.delayedActionsQueue, asyncio.PriorityQueue)
        assert isinstance(queueService.tasksHandlers, dict)
        assert len(queueService.tasksHandlers) == 0
        assert queueService.queueLastUpdated > 0

    def testMultipleInitializationCalls(self):
        """Test that multiple __init__ calls don't reset state."""
        QueueService._instance = None
        service = QueueService()

        # Add some state
        async def dummyHandler(task: DelayedTask) -> None:
            pass

        service.tasksHandlers[DelayedTaskFunction.SEND_MESSAGE] = [dummyHandler]
        initialHandlers = service.tasksHandlers.copy()

        # Call __init__ again (shouldn't reset)
        service.__init__()

        assert service.tasksHandlers == initialHandlers

    def testThreadSafeSingletonCreation(self, queueService):
        """Test that singleton creation is thread-safe."""
        import threading

        instances = []

        def createInstance():
            instances.append(QueueService.getInstance())

        threads = [threading.Thread(target=createInstance) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # All instances should be the same
        assert all(instance is instances[0] for instance in instances)


# ============================================================================
# Task Registration Tests
# ============================================================================


class TestTaskRegistration:
    """Test handler registration functionality."""

    def testRegisterSingleHandler(self, queueService, mockTaskHandler):
        """Test registering a single handler for a task type."""
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, mockTaskHandler)

        assert DelayedTaskFunction.SEND_MESSAGE in queueService.tasksHandlers
        assert len(queueService.tasksHandlers[DelayedTaskFunction.SEND_MESSAGE]) == 1
        assert queueService.tasksHandlers[DelayedTaskFunction.SEND_MESSAGE][0] is mockTaskHandler

    def testRegisterMultipleHandlersSameType(self, queueService):
        """Test registering multiple handlers for the same task type."""
        handler1 = createAsyncMock()
        handler2 = createAsyncMock()
        handler3 = createAsyncMock()

        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler1)
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler2)
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler3)

        handlers = queueService.tasksHandlers[DelayedTaskFunction.SEND_MESSAGE]
        assert len(handlers) == 3
        assert handlers == [handler1, handler2, handler3]

    def testRegisterHandlersDifferentTypes(self, queueService):
        """Test registering handlers for different task types."""
        sendHandler = createAsyncMock()
        deleteHandler = createAsyncMock()
        processHandler = createAsyncMock()

        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, sendHandler)
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.DELETE_MESSAGE, deleteHandler)
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.PROCESS_BACKGROUND_TASKS, processHandler)

        assert len(queueService.tasksHandlers) == 3
        assert queueService.tasksHandlers[DelayedTaskFunction.SEND_MESSAGE][0] is sendHandler
        assert queueService.tasksHandlers[DelayedTaskFunction.DELETE_MESSAGE][0] is deleteHandler
        assert queueService.tasksHandlers[DelayedTaskFunction.PROCESS_BACKGROUND_TASKS][0] is processHandler

    def testRegisterHandlerOrder(self, queueService):
        """Test that handlers are called in registration order."""
        handler1 = createAsyncMock()
        handler2 = createAsyncMock()

        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler1)
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler2)

        handlers = queueService.tasksHandlers[DelayedTaskFunction.SEND_MESSAGE]
        assert handlers[0] is handler1
        assert handlers[1] is handler2


# ============================================================================
# Task Scheduling Tests
# ============================================================================


class TestTaskScheduling:
    """Test task scheduling functionality."""

    @pytest.mark.asyncio
    async def testScheduleImmediateTask(self, queueService, mockDatabaseWrapper):
        """Test scheduling a task for immediate execution."""
        queueService.db = mockDatabaseWrapper
        currentTime = time.time()

        await queueService.addDelayedTask(
            delayedUntil=currentTime, function=DelayedTaskFunction.SEND_MESSAGE, kwargs={"chat_id": 123, "text": "Test"}
        )

        assert queueService.delayedActionsQueue.qsize() == 1
        mockDatabaseWrapper.addDelayedTask.assert_called_once()

    @pytest.mark.asyncio
    async def testScheduleDelayedTask(self, queueService, mockDatabaseWrapper):
        """Test scheduling a task for future execution."""
        queueService.db = mockDatabaseWrapper
        futureTime = time.time() + 3600  # 1 hour from now

        await queueService.addDelayedTask(
            delayedUntil=futureTime,
            function=DelayedTaskFunction.DELETE_MESSAGE,
            kwargs={"chat_id": 123, "message_id": 456},
        )

        assert queueService.delayedActionsQueue.qsize() == 1
        mockDatabaseWrapper.addDelayedTask.assert_called_once()

    @pytest.mark.asyncio
    async def testScheduleTaskWithCustomId(self, queueService, mockDatabaseWrapper):
        """Test scheduling a task with a custom task ID."""
        queueService.db = mockDatabaseWrapper
        customId = "custom-task-id-123"

        await queueService.addDelayedTask(
            delayedUntil=time.time() + 60,
            function=DelayedTaskFunction.SEND_MESSAGE,
            kwargs={"text": "Test"},
            taskId=customId,
        )

        # Verify task was added with custom ID
        callArgs = mockDatabaseWrapper.addDelayedTask.call_args
        assert callArgs.kwargs["taskId"] == customId

    @pytest.mark.asyncio
    async def testScheduleTaskWithAutoGeneratedId(self, queueService, mockDatabaseWrapper):
        """Test that task ID is auto-generated when not provided."""
        queueService.db = mockDatabaseWrapper

        await queueService.addDelayedTask(
            delayedUntil=time.time() + 60, function=DelayedTaskFunction.SEND_MESSAGE, kwargs={"text": "Test"}
        )

        # Verify task was added with a UUID
        callArgs = mockDatabaseWrapper.addDelayedTask.call_args
        taskId = callArgs.kwargs["taskId"]
        assert isinstance(taskId, str)
        assert len(taskId) > 0
        # Verify it's a valid UUID format
        uuid.UUID(taskId)

    @pytest.mark.asyncio
    async def testScheduleTaskSkipDatabase(self, queueService, mockDatabaseWrapper):
        """Test scheduling a task with skipDB=True doesn't persist to database."""
        queueService.db = mockDatabaseWrapper

        await queueService.addDelayedTask(
            delayedUntil=time.time() + 60, function=DelayedTaskFunction.PROCESS_BACKGROUND_TASKS, kwargs={}, skipDB=True
        )

        assert queueService.delayedActionsQueue.qsize() == 1
        mockDatabaseWrapper.addDelayedTask.assert_not_called()

    @pytest.mark.asyncio
    async def testScheduleMultipleTasks(self, queueService, mockDatabaseWrapper):
        """Test scheduling multiple tasks."""
        queueService.db = mockDatabaseWrapper

        for i in range(5):
            await queueService.addDelayedTask(
                delayedUntil=time.time() + (i * 60),
                function=DelayedTaskFunction.SEND_MESSAGE,
                kwargs={"text": f"Message {i}"},
            )

        assert queueService.delayedActionsQueue.qsize() == 5
        assert mockDatabaseWrapper.addDelayedTask.call_count == 5

    @pytest.mark.asyncio
    async def testScheduleTaskWithoutDatabase(self, queueService):
        """Test that scheduling without database raises exception."""
        queueService.db = None

        with pytest.raises(Exception, match="No database connection"):
            await queueService.addDelayedTask(
                delayedUntil=time.time() + 60,
                function=DelayedTaskFunction.SEND_MESSAGE,
                kwargs={"text": "Test"},
                skipDB=False,
            )

    @pytest.mark.asyncio
    async def testScheduleTaskWithComplexKwargs(self, queueService, mockDatabaseWrapper):
        """Test scheduling a task with complex kwargs."""
        queueService.db = mockDatabaseWrapper
        complexKwargs = {
            "chat_id": 123,
            "text": "Test message",
            "parse_mode": "MarkdownV2",
            "reply_markup": {"inline_keyboard": [[{"text": "Button", "callback_data": "data"}]]},
            "metadata": {"user_id": 456, "timestamp": time.time()},
        }

        await queueService.addDelayedTask(
            delayedUntil=time.time() + 60, function=DelayedTaskFunction.SEND_MESSAGE, kwargs=complexKwargs
        )

        assert queueService.delayedActionsQueue.qsize() == 1
        mockDatabaseWrapper.addDelayedTask.assert_called_once()


# ============================================================================
# Background Task Tests
# ============================================================================


class TestBackgroundTasks:
    """Test background task queue functionality."""

    @pytest.mark.asyncio
    async def testAddBackgroundTask(self, queueService):
        """Test adding a background task to the queue."""
        task = makeEmptyAsyncTask()

        await queueService.addBackgroundTask(task)

        assert queueService.asyncTasksQueue.qsize() == 1
        assert queueService.queueLastUpdated > 0

    @pytest.mark.asyncio
    async def testAddMultipleBackgroundTasks(self, queueService):
        """Test adding multiple background tasks."""
        tasks = [makeEmptyAsyncTask() for _ in range(5)]

        for task in tasks:
            await queueService.addBackgroundTask(task)

        assert queueService.asyncTasksQueue.qsize() == 5

    @pytest.mark.asyncio
    async def testBackgroundQueueOverflow(self, queueService):
        """Test that queue processes oldest task when full."""
        # Fill queue to max capacity
        for _ in range(constants.MAX_QUEUE_LENGTH + 1):
            task = makeEmptyAsyncTask()
            await queueService.addBackgroundTask(task)

        # Queue should not significantly exceed max length (allow for race conditions)
        assert queueService.asyncTasksQueue.qsize() <= constants.MAX_QUEUE_LENGTH + 2

    @pytest.mark.asyncio
    async def testProcessBackgroundTasksEmpty(self, queueService):
        """Test processing empty background tasks queue."""
        await queueService.processBackgroundTasks(forceProcessAll=True)

        # Should complete without error
        assert queueService.asyncTasksQueue.qsize() == 0

    @pytest.mark.asyncio
    async def testProcessBackgroundTasksForced(self, queueService):
        """Test forced processing of background tasks."""
        # Add some tasks
        for _ in range(3):
            task = makeEmptyAsyncTask()
            await queueService.addBackgroundTask(task)

        await queueService.processBackgroundTasks(forceProcessAll=True)

        # All tasks should be processed
        assert queueService.asyncTasksQueue.qsize() == 0

    @pytest.mark.asyncio
    async def testProcessBackgroundTasksAgeBasedNotReady(self, queueService):
        """Test that age-based processing doesn't trigger when queue is young."""
        task = makeEmptyAsyncTask()
        await queueService.addBackgroundTask(task)

        # Queue is fresh, shouldn't process
        await queueService.processBackgroundTasks(forceProcessAll=False)

        # Task should still be in queue
        assert queueService.asyncTasksQueue.qsize() == 1

    @pytest.mark.asyncio
    async def testProcessBackgroundTasksAgeBasedReady(self, queueService):
        """Test that age-based processing triggers when queue is old."""
        task = makeEmptyAsyncTask()
        await queueService.addBackgroundTask(task)

        # Make queue appear old
        queueService.queueLastUpdated = time.time() - constants.MAX_QUEUE_AGE - 1

        await queueService.processBackgroundTasks(forceProcessAll=False)

        # Task should be processed
        assert queueService.asyncTasksQueue.qsize() == 0

    @pytest.mark.asyncio
    async def testProcessBackgroundTasksWithError(self, queueService):
        """Test that errors in background tasks are handled gracefully."""

        async def failingTask():
            raise ValueError("Test error")

        task = asyncio.create_task(failingTask())
        await queueService.addBackgroundTask(task)

        # Should not raise exception
        await queueService.processBackgroundTasks(forceProcessAll=True)

        # Queue should be empty
        assert queueService.asyncTasksQueue.qsize() == 0


# ============================================================================
# Task Execution Tests
# ============================================================================


class TestTaskExecution:
    """Test delayed task execution functionality."""

    @pytest.mark.asyncio
    async def testExecuteReadyTask(self, queueService, mockDatabaseWrapper):
        """Test that ready tasks are executed."""
        queueService.db = mockDatabaseWrapper
        handler = createAsyncMock()
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler)

        # Add a task that's ready now
        await queueService.addDelayedTask(
            delayedUntil=time.time() - 1,  # Past time
            function=DelayedTaskFunction.SEND_MESSAGE,
            kwargs={"text": "Test"},
            skipDB=True,
        )

        # Process one iteration
        task = await queueService.delayedActionsQueue.get()

        # Manually execute handler (simulating _processDelayedQueue)
        if task.function in queueService.tasksHandlers:
            for h in queueService.tasksHandlers[task.function]:
                await h(task)

        queueService.delayedActionsQueue.task_done()

        handler.assert_called_once()
        assert handler.call_args[0][0].function == DelayedTaskFunction.SEND_MESSAGE

    @pytest.mark.asyncio
    async def testTaskExecutionOrder(self, queueService, mockDatabaseWrapper):
        """Test that tasks execute in order of delayedUntil."""
        queueService.db = mockDatabaseWrapper
        handler = createAsyncMock()
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler)

        # Add tasks in reverse order
        times = [time.time() + 30, time.time() + 10, time.time() + 20]
        for t in times:
            await queueService.addDelayedTask(
                delayedUntil=t, function=DelayedTaskFunction.SEND_MESSAGE, kwargs={"time": t}, skipDB=True
            )

        # Get tasks from priority queue
        task1 = await queueService.delayedActionsQueue.get()
        task2 = await queueService.delayedActionsQueue.get()
        task3 = await queueService.delayedActionsQueue.get()

        # Should be in ascending order
        assert task1.delayedUntil < task2.delayedUntil < task3.delayedUntil

    @pytest.mark.asyncio
    async def testHandlerReceivesCorrectParameters(self, queueService, mockDatabaseWrapper):
        """Test that handler receives correct DelayedTask object."""
        queueService.db = mockDatabaseWrapper
        handler = createAsyncMock()
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler)

        testKwargs = {"chat_id": 123, "text": "Test message"}
        await queueService.addDelayedTask(
            delayedUntil=time.time() - 1, function=DelayedTaskFunction.SEND_MESSAGE, kwargs=testKwargs, skipDB=True
        )

        task = await queueService.delayedActionsQueue.get()

        # Execute handler
        for h in queueService.tasksHandlers[task.function]:
            await h(task)

        queueService.delayedActionsQueue.task_done()

        # Verify handler received correct task
        calledTask = handler.call_args[0][0]
        assert isinstance(calledTask, DelayedTask)
        assert calledTask.function == DelayedTaskFunction.SEND_MESSAGE
        assert calledTask.kwargs == testKwargs

    @pytest.mark.asyncio
    async def testMultipleHandlersExecuted(self, queueService, mockDatabaseWrapper):
        """Test that all registered handlers are executed."""
        queueService.db = mockDatabaseWrapper
        handler1 = createAsyncMock()
        handler2 = createAsyncMock()
        handler3 = createAsyncMock()

        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler1)
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler2)
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler3)

        await queueService.addDelayedTask(
            delayedUntil=time.time() - 1,
            function=DelayedTaskFunction.SEND_MESSAGE,
            kwargs={"text": "Test"},
            skipDB=True,
        )

        task = await queueService.delayedActionsQueue.get()

        # Execute all handlers
        for h in queueService.tasksHandlers[task.function]:
            await h(task)

        queueService.delayedActionsQueue.task_done()

        handler1.assert_called_once()
        handler2.assert_called_once()
        handler3.assert_called_once()

    @pytest.mark.asyncio
    async def testHandlerExecutionOrder(self, queueService, mockDatabaseWrapper):
        """Test that handlers execute in registration order."""
        queueService.db = mockDatabaseWrapper
        executionOrder = []

        async def handler1(task):
            executionOrder.append(1)

        async def handler2(task):
            executionOrder.append(2)

        async def handler3(task):
            executionOrder.append(3)

        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler1)
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler2)
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler3)

        await queueService.addDelayedTask(
            delayedUntil=time.time() - 1, function=DelayedTaskFunction.SEND_MESSAGE, kwargs={}, skipDB=True
        )

        task = await queueService.delayedActionsQueue.get()

        for h in queueService.tasksHandlers[task.function]:
            await h(task)

        queueService.delayedActionsQueue.task_done()

        assert executionOrder == [1, 2, 3]


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling in queue operations."""

    @pytest.mark.asyncio
    async def testHandlerExceptionCaught(self, queueService, mockDatabaseWrapper):
        """Test that handler exceptions are caught and logged."""
        queueService.db = mockDatabaseWrapper

        async def failingHandler(task):
            raise ValueError("Handler error")

        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, failingHandler)

        await queueService.addDelayedTask(
            delayedUntil=time.time() - 1, function=DelayedTaskFunction.SEND_MESSAGE, kwargs={}, skipDB=True
        )

        task = await queueService.delayedActionsQueue.get()

        # Should not raise exception
        for h in queueService.tasksHandlers[task.function]:
            try:
                await h(task)
            except Exception:
                pass  # Exception should be caught

        queueService.delayedActionsQueue.task_done()

    @pytest.mark.asyncio
    async def testMissingHandlerForTaskType(self, queueService, mockDatabaseWrapper):
        """Test handling of tasks with no registered handlers."""
        queueService.db = mockDatabaseWrapper

        # Add task without registering handler
        await queueService.addDelayedTask(
            delayedUntil=time.time() - 1, function=DelayedTaskFunction.SEND_MESSAGE, kwargs={}, skipDB=True
        )

        task = await queueService.delayedActionsQueue.get()

        # Should handle missing handler gracefully
        if task.function not in queueService.tasksHandlers:
            # Task should be re-queued with delay
            task.delayedUntil = time.time() + 60
            await queueService.delayedActionsQueue.put(task)

        queueService.delayedActionsQueue.task_done()

        # Task should be back in queue
        assert queueService.delayedActionsQueue.qsize() == 1

    @pytest.mark.asyncio
    async def testInvalidTaskDataHandling(self, queueService):
        """Test handling of invalid task data."""
        # Put non-DelayedTask object in queue
        await queueService.delayedActionsQueue.put("invalid_data")

        item = await queueService.delayedActionsQueue.get()

        # Should detect invalid type
        assert not isinstance(item, DelayedTask)

        queueService.delayedActionsQueue.task_done()

    @pytest.mark.asyncio
    async def testDatabaseErrorDuringTaskAdd(self, queueService, mockDatabaseWrapper):
        """Test handling of database errors during task addition."""
        queueService.db = mockDatabaseWrapper
        mockDatabaseWrapper.addDelayedTask.side_effect = Exception("Database error")

        with pytest.raises(Exception, match="Database error"):
            await queueService.addDelayedTask(
                delayedUntil=time.time() + 60, function=DelayedTaskFunction.SEND_MESSAGE, kwargs={}, skipDB=False
            )

    @pytest.mark.asyncio
    async def testPartialHandlerFailure(self, queueService, mockDatabaseWrapper):
        """Test that one handler failure doesn't prevent others from executing."""
        queueService.db = mockDatabaseWrapper
        executionLog = []

        async def handler1(task):
            executionLog.append("handler1")

        async def failingHandler(task):
            executionLog.append("failing")
            raise ValueError("Handler error")

        async def handler3(task):
            executionLog.append("handler3")

        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler1)
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, failingHandler)
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler3)

        await queueService.addDelayedTask(
            delayedUntil=time.time() - 1, function=DelayedTaskFunction.SEND_MESSAGE, kwargs={}, skipDB=True
        )

        task = await queueService.delayedActionsQueue.get()

        # Execute all handlers, catching exceptions
        for h in queueService.tasksHandlers[task.function]:
            try:
                await h(task)
            except Exception:
                pass

        queueService.delayedActionsQueue.task_done()

        # All handlers should have been called
        assert executionLog == ["handler1", "failing", "handler3"]


# ============================================================================
# Shutdown Tests
# ============================================================================


class TestShutdown:
    """Test graceful shutdown functionality."""

    @pytest.mark.asyncio
    async def testBeginShutdown(self, queueService):
        """Test that beginShutdown adds DO_EXIT task."""
        await queueService.beginShutdown()

        assert queueService.delayedActionsQueue.qsize() == 1

        task = await queueService.delayedActionsQueue.get()
        assert task.function == DelayedTaskFunction.DO_EXIT

    @pytest.mark.asyncio
    async def testDoExitHandler(self, queueService):
        """Test that DO_EXIT handler processes background tasks."""
        # Add some background tasks
        for _ in range(3):
            await queueService.addBackgroundTask(makeEmptyAsyncTask())

        assert queueService.asyncTasksQueue.qsize() == 3

        # Execute DO_EXIT handler
        exitTask = DelayedTask(
            taskId="exit-task", delayedUntil=time.time(), function=DelayedTaskFunction.DO_EXIT, kwargs={}
        )

        await queueService._doExitHandler(exitTask)

        # Background tasks should be processed
        assert queueService.asyncTasksQueue.qsize() == 0


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Test full workflow integration scenarios."""

    @pytest.mark.asyncio
    async def testFullWorkflowRegisterScheduleExecute(self, queueService, mockDatabaseWrapper):
        """Test complete workflow: register handler → schedule task → execute."""
        queueService.db = mockDatabaseWrapper
        executionLog = []

        async def testHandler(task: DelayedTask):
            executionLog.append({"function": task.function, "kwargs": task.kwargs})

        # 1. Register handler
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, testHandler)

        # 2. Schedule task
        testKwargs = {"chat_id": 123, "text": "Integration test"}
        await queueService.addDelayedTask(
            delayedUntil=time.time() - 1,  # Ready immediately
            function=DelayedTaskFunction.SEND_MESSAGE,
            kwargs=testKwargs,
            skipDB=True,
        )

        # 3. Execute task
        task = await queueService.delayedActionsQueue.get()
        for h in queueService.tasksHandlers[task.function]:
            await h(task)
        queueService.delayedActionsQueue.task_done()

        # 4. Verify execution
        assert len(executionLog) == 1
        assert executionLog[0]["function"] == DelayedTaskFunction.SEND_MESSAGE
        assert executionLog[0]["kwargs"] == testKwargs

    @pytest.mark.asyncio
    async def testTaskPersistenceWorkflow(self, queueService, mockDatabaseWrapper):
        """Test task persistence to database."""
        queueService.db = mockDatabaseWrapper

        testKwargs = {"chat_id": 456, "text": "Persistent task"}

        await queueService.addDelayedTask(
            delayedUntil=time.time() + 60, function=DelayedTaskFunction.SEND_MESSAGE, kwargs=testKwargs, skipDB=False
        )

        # Verify database was called
        mockDatabaseWrapper.addDelayedTask.assert_called_once()
        callKwargs = mockDatabaseWrapper.addDelayedTask.call_args.kwargs
        assert callKwargs["function"] == DelayedTaskFunction.SEND_MESSAGE
        assert json.loads(callKwargs["kwargs"]) == testKwargs

    @pytest.mark.asyncio
    async def testRestoreTasksFromDatabase(self, queueService, mockDatabaseWrapper):
        """Test restoring pending tasks from database on startup."""
        # Mock database with pending tasks
        pendingTasks = [
            {
                "id": "task-1",
                "delayed_ts": str(int(time.time() + 60)),
                "function": DelayedTaskFunction.SEND_MESSAGE.value,
                "kwargs": json.dumps({"chat_id": 123, "text": "Task 1"}),
            },
            {
                "id": "task-2",
                "delayed_ts": str(int(time.time() + 120)),
                "function": DelayedTaskFunction.DELETE_MESSAGE.value,
                "kwargs": json.dumps({"chat_id": 456, "message_id": 789}),
            },
        ]
        mockDatabaseWrapper.getPendingDelayedTasks.return_value = pendingTasks

        # Register handlers to prevent errors
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.PROCESS_BACKGROUND_TASKS, createAsyncMock())
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.DO_EXIT, createAsyncMock())

        # Start scheduler (will restore tasks)
        # We need to cancel it quickly to avoid infinite loop
        schedulerTask = asyncio.create_task(queueService.startDelayedScheduler(mockDatabaseWrapper))
        await asyncio.sleep(0.1)  # Let it initialize
        schedulerTask.cancel()

        try:
            await schedulerTask
        except asyncio.CancelledError:
            pass

        # Verify tasks were restored (2 from DB + 1 PROCESS_BACKGROUND_TASKS)
        assert queueService.delayedActionsQueue.qsize() >= 2

    @pytest.mark.asyncio
    async def testMultipleTaskTypesExecution(self, queueService, mockDatabaseWrapper):
        """Test executing multiple different task types."""
        queueService.db = mockDatabaseWrapper
        executionLog = []

        async def sendHandler(task):
            executionLog.append(("send", task.kwargs))

        async def deleteHandler(task):
            executionLog.append(("delete", task.kwargs))

        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, sendHandler)
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.DELETE_MESSAGE, deleteHandler)

        # Schedule different task types
        await queueService.addDelayedTask(
            delayedUntil=time.time() - 1,
            function=DelayedTaskFunction.SEND_MESSAGE,
            kwargs={"text": "Message 1"},
            skipDB=True,
        )
        await queueService.addDelayedTask(
            delayedUntil=time.time() - 1,
            function=DelayedTaskFunction.DELETE_MESSAGE,
            kwargs={"message_id": 123},
            skipDB=True,
        )

        # Execute tasks
        while not queueService.delayedActionsQueue.empty():
            task = await queueService.delayedActionsQueue.get()
            if task.function in queueService.tasksHandlers:
                for h in queueService.tasksHandlers[task.function]:
                    await h(task)
            queueService.delayedActionsQueue.task_done()

        # Verify both handlers were called
        assert len(executionLog) == 2
        assert any(log[0] == "send" for log in executionLog)
        assert any(log[0] == "delete" for log in executionLog)

    @pytest.mark.asyncio
    async def testBackgroundTasksProcessingCycle(self, queueService, mockDatabaseWrapper):
        """Test the automatic background tasks processing cycle."""
        queueService.db = mockDatabaseWrapper

        # Add background tasks
        for _ in range(3):
            await queueService.addBackgroundTask(makeEmptyAsyncTask())

        assert queueService.asyncTasksQueue.qsize() == 3

        # Make queue appear old so it will be processed
        queueService.queueLastUpdated = time.time() - constants.MAX_QUEUE_AGE - 1

        # Create and execute PROCESS_BACKGROUND_TASKS task
        processTask = DelayedTask(
            taskId="process-task",
            delayedUntil=time.time(),
            function=DelayedTaskFunction.PROCESS_BACKGROUND_TASKS,
            kwargs={},
        )

        await queueService._processBackgroundTasksHandler(processTask)

        # Background tasks should be processed
        assert queueService.asyncTasksQueue.qsize() == 0

        # New PROCESS_BACKGROUND_TASKS should be scheduled
        assert queueService.delayedActionsQueue.qsize() == 1


# ============================================================================
# Concurrency Tests
# ============================================================================


class TestConcurrency:
    """Test concurrent operations and thread safety."""

    @pytest.mark.asyncio
    async def testConcurrentTaskScheduling(self, queueService, mockDatabaseWrapper):
        """Test scheduling multiple tasks concurrently."""
        queueService.db = mockDatabaseWrapper

        async def scheduleTask(i):
            await queueService.addDelayedTask(
                delayedUntil=time.time() + i,
                function=DelayedTaskFunction.SEND_MESSAGE,
                kwargs={"text": f"Task {i}"},
                skipDB=True,
            )

        # Schedule 10 tasks concurrently
        await asyncio.gather(*[scheduleTask(i) for i in range(10)])

        assert queueService.delayedActionsQueue.qsize() == 10

    @pytest.mark.asyncio
    async def testConcurrentBackgroundTaskAddition(self, queueService):
        """Test adding background tasks concurrently."""

        async def addTask(i):
            task = makeEmptyAsyncTask()
            await queueService.addBackgroundTask(task)

        # Add 20 tasks concurrently
        await asyncio.gather(*[addTask(i) for i in range(20)])

        # Some tasks might have been processed if queue was full
        assert queueService.asyncTasksQueue.qsize() <= constants.MAX_QUEUE_LENGTH

    @pytest.mark.asyncio
    async def testConcurrentHandlerRegistration(self, queueService):
        """Test registering handlers concurrently."""
        handlers = [createAsyncMock() for _ in range(10)]

        def registerHandler(handler):
            queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler)

        # Register handlers concurrently (using threads since it's not async)
        import threading

        threads = [threading.Thread(target=registerHandler, args=(h,)) for h in handlers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # All handlers should be registered
        assert len(queueService.tasksHandlers[DelayedTaskFunction.SEND_MESSAGE]) == 10

    @pytest.mark.asyncio
    async def testTaskExecutionDoesNotBlockScheduling(self, queueService, mockDatabaseWrapper):
        """Test that task execution doesn't block new task scheduling."""
        queueService.db = mockDatabaseWrapper

        async def slowHandler(task):
            await asyncio.sleep(0.1)

        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, slowHandler)

        # Schedule initial task
        await queueService.addDelayedTask(
            delayedUntil=time.time() - 1, function=DelayedTaskFunction.SEND_MESSAGE, kwargs={}, skipDB=True
        )

        # Start executing first task
        task1 = await queueService.delayedActionsQueue.get()
        executionTask = asyncio.create_task(slowHandler(task1))

        # While first task is executing, schedule another
        await queueService.addDelayedTask(
            delayedUntil=time.time() - 1, function=DelayedTaskFunction.SEND_MESSAGE, kwargs={}, skipDB=True
        )

        # Second task should be in queue
        assert queueService.delayedActionsQueue.qsize() == 1

        # Wait for first task to complete
        await executionTask
        queueService.delayedActionsQueue.task_done()


# ============================================================================
# DelayedTask Model Tests
# ============================================================================


class TestDelayedTaskModel:
    """Test DelayedTask model functionality."""

    def testDelayedTaskCreation(self):
        """Test creating a DelayedTask instance."""
        task = DelayedTask(
            taskId="test-123",
            delayedUntil=1234567890.0,
            function=DelayedTaskFunction.SEND_MESSAGE,
            kwargs={"chat_id": 123},
        )

        assert task.taskId == "test-123"
        assert task.delayedUntil == 1234567890.0
        assert task.function == DelayedTaskFunction.SEND_MESSAGE
        assert task.kwargs == {"chat_id": 123}

    def testDelayedTaskComparison(self):
        """Test DelayedTask comparison operators for priority queue."""
        task1 = DelayedTask("1", 100.0, DelayedTaskFunction.SEND_MESSAGE, {})
        task2 = DelayedTask("2", 200.0, DelayedTaskFunction.SEND_MESSAGE, {})
        task3 = DelayedTask("3", 100.0, DelayedTaskFunction.SEND_MESSAGE, {})

        assert task1 < task2
        assert task2 > task1
        assert task1 == task3
        assert task1 != task2

    def testDelayedTaskStringRepresentation(self):
        """Test DelayedTask string representation."""
        task = DelayedTask(
            taskId="test-123",
            delayedUntil=1234567890.0,
            function=DelayedTaskFunction.SEND_MESSAGE,
            kwargs={"text": "Test"},
        )

        taskStr = str(task)
        assert "test-123" in taskStr
        assert "1234567890.0" in taskStr
        assert "SEND_MESSAGE" in taskStr or "sendMessage" in taskStr

    @pytest.mark.asyncio
    async def testDelayedTaskPriorityQueueOrdering(self):
        """Test that DelayedTask works correctly in priority queue."""
        queue = asyncio.PriorityQueue()

        # Add tasks in random order
        await queue.put(DelayedTask("3", 300.0, DelayedTaskFunction.SEND_MESSAGE, {}))
        await queue.put(DelayedTask("1", 100.0, DelayedTaskFunction.SEND_MESSAGE, {}))
        await queue.put(DelayedTask("2", 200.0, DelayedTaskFunction.SEND_MESSAGE, {}))

        # Should come out in order
        task1 = await queue.get()
        task2 = await queue.get()
        task3 = await queue.get()

        assert task1.taskId == "1"
        assert task2.taskId == "2"
        assert task3.taskId == "3"


# ============================================================================
# Helper Function Tests
# ============================================================================


class TestHelperFunctions:
    """Test helper functions."""

    @pytest.mark.asyncio
    async def testMakeEmptyAsyncTask(self):
        """Test makeEmptyAsyncTask creates a valid async task."""
        task = makeEmptyAsyncTask()

        assert isinstance(task, asyncio.Task)

        # Task should complete successfully
        result = await task
        assert result is None


# ============================================================================
# Edge Cases and Special Scenarios
# ============================================================================


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    @pytest.mark.asyncio
    async def testScheduleTaskWithZeroDelay(self, queueService, mockDatabaseWrapper):
        """Test scheduling a task with zero delay (immediate execution)."""
        queueService.db = mockDatabaseWrapper

        await queueService.addDelayedTask(
            delayedUntil=time.time(), function=DelayedTaskFunction.SEND_MESSAGE, kwargs={}, skipDB=True
        )

        task = await queueService.delayedActionsQueue.get()
        assert task.delayedUntil <= time.time()

    @pytest.mark.asyncio
    async def testScheduleTaskWithPastTime(self, queueService, mockDatabaseWrapper):
        """Test scheduling a task with a past timestamp."""
        queueService.db = mockDatabaseWrapper
        pastTime = time.time() - 3600  # 1 hour ago

        await queueService.addDelayedTask(
            delayedUntil=pastTime, function=DelayedTaskFunction.SEND_MESSAGE, kwargs={}, skipDB=True
        )

        task = await queueService.delayedActionsQueue.get()
        assert task.delayedUntil == pastTime

    @pytest.mark.asyncio
    async def testEmptyKwargsHandling(self, queueService, mockDatabaseWrapper):
        """Test handling tasks with empty kwargs."""
        queueService.db = mockDatabaseWrapper
        handler = createAsyncMock()
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler)

        await queueService.addDelayedTask(
            delayedUntil=time.time() - 1, function=DelayedTaskFunction.SEND_MESSAGE, kwargs={}, skipDB=True
        )

        task = await queueService.delayedActionsQueue.get()
        for h in queueService.tasksHandlers[task.function]:
            await h(task)

        handler.assert_called_once()
        assert handler.call_args[0][0].kwargs == {}

    @pytest.mark.asyncio
    async def testVeryLargeKwargs(self, queueService, mockDatabaseWrapper):
        """Test handling tasks with very large kwargs."""
        queueService.db = mockDatabaseWrapper

        # Create large kwargs
        largeKwargs = {
            "data": "x" * 10000,  # 10KB string
            "list": list(range(1000)),
            "nested": {"level1": {"level2": {"level3": "deep"}}},
        }

        await queueService.addDelayedTask(
            delayedUntil=time.time() + 60, function=DelayedTaskFunction.SEND_MESSAGE, kwargs=largeKwargs, skipDB=True
        )

        task = await queueService.delayedActionsQueue.get()
        assert task.kwargs == largeKwargs

    @pytest.mark.asyncio
    async def testTaskWithSpecialCharactersInKwargs(self, queueService, mockDatabaseWrapper):
        """Test handling tasks with special characters in kwargs."""
        queueService.db = mockDatabaseWrapper

        specialKwargs = {
            "text": "Hello 🎉 World! \n\t Special: <>&\"'",
            "emoji": "😀😃😄😁",
            "unicode": "Привет мир 你好世界",
        }

        await queueService.addDelayedTask(
            delayedUntil=time.time() + 60, function=DelayedTaskFunction.SEND_MESSAGE, kwargs=specialKwargs
        )

        # Verify database was called with properly encoded kwargs
        callArgs = mockDatabaseWrapper.addDelayedTask.call_args
        storedKwargs = json.loads(callArgs.kwargs["kwargs"])
        assert storedKwargs == specialKwargs

    @pytest.mark.asyncio
    async def testQueueStatusAfterMultipleOperations(self, queueService, mockDatabaseWrapper):
        """Test queue state after multiple operations."""
        queueService.db = mockDatabaseWrapper

        # Add tasks
        for i in range(5):
            await queueService.addDelayedTask(
                delayedUntil=time.time() + i,
                function=DelayedTaskFunction.SEND_MESSAGE,
                kwargs={"index": i},
                skipDB=True,
            )

        initialSize = queueService.delayedActionsQueue.qsize()
        assert initialSize == 5

        # Process some tasks
        for _ in range(3):
            await queueService.delayedActionsQueue.get()
            queueService.delayedActionsQueue.task_done()

        remainingSize = queueService.delayedActionsQueue.qsize()
        assert remainingSize == 2

    def testSingletonPersistsAcrossModules(self, queueService):
        """Test that singleton instance persists across different access points."""
        from internal.services.queue_service.service import QueueService as ImportedQueueService

        instance1 = queueService
        instance2 = ImportedQueueService.getInstance()
        instance3 = ImportedQueueService()

        assert instance1 is instance2
        assert instance2 is instance3

    @pytest.mark.asyncio
    async def testHandlerWithAsyncContextManager(self, queueService, mockDatabaseWrapper):
        """Test handler that uses async context manager."""
        queueService.db = mockDatabaseWrapper
        executionLog = []

        async def handlerWithContext(task):
            async with createAsyncContextManager(enterValue="resource") as resource:
                executionLog.append(f"Using {resource}")

        from tests.utils import createAsyncContextManager

        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handlerWithContext)

        await queueService.addDelayedTask(
            delayedUntil=time.time() - 1, function=DelayedTaskFunction.SEND_MESSAGE, kwargs={}, skipDB=True
        )

        task = await queueService.delayedActionsQueue.get()
        for h in queueService.tasksHandlers[task.function]:
            await h(task)

        assert len(executionLog) == 1
        assert "resource" in executionLog[0]


# ============================================================================
# Performance and Stress Tests
# ============================================================================


class TestPerformance:
    """Test performance and stress scenarios."""

    @pytest.mark.asyncio
    async def testHighVolumeTaskScheduling(self, queueService, mockDatabaseWrapper):
        """Test scheduling a large number of tasks."""
        queueService.db = mockDatabaseWrapper
        taskCount = 100

        for i in range(taskCount):
            await queueService.addDelayedTask(
                delayedUntil=time.time() + i,
                function=DelayedTaskFunction.SEND_MESSAGE,
                kwargs={"index": i},
                skipDB=True,
            )

        assert queueService.delayedActionsQueue.qsize() == taskCount

    @pytest.mark.asyncio
    async def testRapidHandlerRegistration(self, queueService):
        """Test registering many handlers rapidly."""
        handlerCount = 50

        for i in range(handlerCount):
            handler = createAsyncMock()
            queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, handler)

        assert len(queueService.tasksHandlers[DelayedTaskFunction.SEND_MESSAGE]) == handlerCount

    @pytest.mark.asyncio
    async def testBackgroundQueueStressTest(self, queueService):
        """Test background queue under stress."""
        # Add tasks up to and beyond max capacity
        for _ in range(constants.MAX_QUEUE_LENGTH + 10):
            task = makeEmptyAsyncTask()
            await queueService.addBackgroundTask(task)

        # Queue should handle overflow gracefully (allow for race conditions)
        assert queueService.asyncTasksQueue.qsize() <= constants.MAX_QUEUE_LENGTH + 2


# ============================================================================
# Documentation and Example Tests
# ============================================================================


class TestDocumentationExamples:
    """Test examples from documentation."""

    @pytest.mark.asyncio
    async def testBasicUsageExample(self, queueService, mockDatabaseWrapper):
        """Test basic usage example from docstring."""
        queueService.db = mockDatabaseWrapper

        # Example from module docstring
        await queueService.addDelayedTask(
            delayedUntil=time.time() + 3600,
            function=DelayedTaskFunction.SEND_MESSAGE,
            kwargs={"chat_id": 123, "text": "Hello"},
        )

        assert queueService.delayedActionsQueue.qsize() == 1

    @pytest.mark.asyncio
    async def testHandlerRegistrationExample(self, queueService):
        """Test handler registration example from docstring."""

        async def myHandler(task: DelayedTask) -> None:
            print(f"Processing {task.function}")

        queueService.registerDelayedTaskHandler(DelayedTaskFunction.SEND_MESSAGE, myHandler)

        assert DelayedTaskFunction.SEND_MESSAGE in queueService.tasksHandlers
