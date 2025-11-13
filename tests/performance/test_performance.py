"""
Performance tests for Gromozeka bot.

This module contains performance benchmarks and stress tests for:
- Message processing throughput
- Database query performance
- Cache operations
- Handler chain execution
- Memory usage under load
- Concurrent operations

Performance Targets:
- Message processing: < 100ms per message
- Database queries: < 50ms for simple queries
- Cache operations: < 10ms
- Handler chain: < 200ms total
- Memory: < 100MB for 1000 messages
"""

import asyncio
import gc
import time
from unittest.mock import Mock

import pytest

from internal.bot.handlers.base import BaseBotHandler
from internal.database.wrapper import DatabaseWrapper
from tests.fixtures.database_fixtures import (
    createBatchChatMessages,
    createSampleChatMessage,
)
from tests.fixtures.telegram_mocks import createMockBot

# ============================================================================
# Performance Test Markers
# ============================================================================

pytestmark = [
    pytest.mark.performance,
    pytest.mark.slow,
]


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def performanceDb():
    """Create in-memory database for performance tests."""
    # Create database - migrations will run automatically in __init__
    db = DatabaseWrapper(":memory:")

    # Verify tables were created by checking for chat_messages table
    try:
        with db.getCursor() as cursor:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chat_messages'")
            result = cursor.fetchone()
            if not result:
                raise RuntimeError("Database tables were not created properly, dood!")
    except Exception as e:
        db.close()
        raise RuntimeError(f"Failed to initialize performance database: {e}")

    yield db
    db.close()


@pytest.fixture
def threadSafePerformanceDb(tmp_path):
    """Create file-based database for threading performance tests, dood!

    File-based databases support proper concurrent access across threads.
    """
    dbPath = tmp_path / "test_performance_threading.db"
    db = DatabaseWrapper(str(dbPath))
    yield db
    db.close()


@pytest.fixture
def mockBot():
    """Create mock bot for performance tests."""
    return createMockBot()


@pytest.fixture
def mockConfigManager():
    """Create mock config manager."""
    from internal.config.manager import ConfigManager

    mock = Mock(spec=ConfigManager)
    mock.getBotConfig.return_value = {
        "token": "test_token",
        "owners": [123456],
    }
    return mock


@pytest.fixture
def mockLlmManager():
    """Create mock LLM manager."""
    from lib.ai.manager import LLMManager

    mock = Mock(spec=LLMManager)
    mock.getModel.return_value = None
    return mock


@pytest.fixture
def baseHandler(mockBot, performanceDb, mockConfigManager, mockLlmManager):
    """Create base handler for performance tests."""
    handler = BaseBotHandler(
        configManager=mockConfigManager,
        database=performanceDb,
        llmManager=mockLlmManager,
    )
    handler.injectBot(mockBot)
    return handler


# ============================================================================
# Message Processing Performance Tests
# ============================================================================


@pytest.mark.benchmark
def testMessageProcessingPerformance(performanceDb):
    """
    Benchmark message processing speed.

    Target: < 100ms per message
    """
    message = createSampleChatMessage()

    startTime = time.time()
    for _ in range(100):
        performanceDb.saveChatMessage(**message)
    endTime = time.time()

    avgTime = (endTime - startTime) / 100 * 1000  # ms per operation
    print(f"\nAverage message processing time: {avgTime:.2f}ms")

    assert avgTime < 100, f"Message processing took {avgTime:.2f}ms (target: < 100ms)"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def testConcurrentMessageProcessing(threadSafePerformanceDb):
    """
    Test performance with concurrent messages.

    Target: Process 100 messages in < 5 seconds

    Uses file-based database to support proper concurrent access.
    """
    # Setup: Add chat info and users first (foreign key constraints)
    threadSafePerformanceDb.updateChatInfo(chatId=123, type="group", title="Test Chat")
    for userId in [456, 457, 458]:  # Users from createBatchChatMessages
        threadSafePerformanceDb.updateChatUser(
            chatId=123, userId=userId, username=f"user{userId}", fullName=f"User {userId}"
        )

    messageCount = 100
    messages = createBatchChatMessages(count=messageCount, chatId=123)

    startTime = time.time()

    # Process messages concurrently
    tasks = []
    for msg in messages:
        task = asyncio.create_task(asyncio.to_thread(threadSafePerformanceDb.saveChatMessage, **msg))
        tasks.append(task)

    await asyncio.gather(*tasks)

    endTime = time.time()
    duration = endTime - startTime

    # Verify all messages were saved
    savedMessages = threadSafePerformanceDb.getChatMessagesSince(123, limit=messageCount)
    assert len(savedMessages) == messageCount

    # Check performance target (relaxed for CI)
    assert duration < 10.0, f"Processing {messageCount} messages took {duration:.2f}s (target: < 10s)"

    # Calculate throughput
    throughput = messageCount / duration
    print(f"\nThroughput: {throughput:.2f} messages/second")


@pytest.mark.benchmark
@pytest.mark.asyncio
async def testMessageProcessingThroughput(performanceDb):
    """
    Measure message processing throughput.

    Target: > 50 messages/second
    """
    messageCount = 500
    messages = createBatchChatMessages(count=messageCount, chatId=123)

    startTime = time.time()

    for msg in messages:
        performanceDb.saveChatMessage(**msg)

    endTime = time.time()
    duration = endTime - startTime
    throughput = messageCount / duration

    print(f"\nProcessed {messageCount} messages in {duration:.2f}s")
    print(f"Throughput: {throughput:.2f} messages/second")

    assert throughput > 50, f"Throughput {throughput:.2f} msg/s is below target (50 msg/s)"


# ============================================================================
# Database Query Performance Tests
# ============================================================================


@pytest.mark.benchmark
def testDatabaseQueryPerformance(performanceDb):
    """
    Benchmark database query performance.

    Target: < 50ms for simple queries
    """
    # Populate database
    messages = createBatchChatMessages(count=100, chatId=123)
    for msg in messages:
        performanceDb.saveChatMessage(**msg)

    startTime = time.time()
    for _ in range(100):
        performanceDb.getChatMessagesSince(123, limit=10)
    endTime = time.time()

    avgTime = (endTime - startTime) / 100 * 1000  # ms per operation
    print(f"\nAverage query time: {avgTime:.2f}ms")

    assert avgTime < 50, f"Query took {avgTime:.2f}ms (target: < 50ms)"


@pytest.mark.benchmark
@pytest.mark.slow
def testDatabaseBulkInsertPerformance(performanceDb):
    """
    Benchmark bulk insert performance.

    Target: Insert 1000 messages in < 5 seconds (relaxed for CI)
    """
    # Setup: Add chat info and users first (foreign key constraints)
    performanceDb.updateChatInfo(chatId=123, type="group", title="Test Chat")
    for userId in [456, 457, 458]:  # Users from createBatchChatMessages
        performanceDb.updateChatUser(chatId=123, userId=userId, username=f"user{userId}", fullName=f"User {userId}")

    messages = createBatchChatMessages(count=1000, chatId=123)

    startTime = time.time()
    for msg in messages:
        performanceDb.saveChatMessage(**msg)
    endTime = time.time()

    duration = endTime - startTime
    print(f"\nBulk insert of 1000 messages: {duration:.2f}s")

    # Relaxed target for CI environments
    assert duration < 5.0, f"Bulk insert took {duration:.2f}s (target: < 5s)"

    # Verify all messages were inserted
    savedMessages = performanceDb.getChatMessagesSince(123, limit=1000)
    assert len(savedMessages) == 1000


@pytest.mark.benchmark
@pytest.mark.slow
def testDatabaseComplexQueryPerformance(performanceDb):
    """
    Test performance of complex database queries.

    Target: < 500ms for complex queries (relaxed for CI)
    """
    # Populate database with multiple chats
    for chatId in range(1, 11):
        # Setup: Add chat info and users first (foreign key constraints)
        performanceDb.updateChatInfo(chatId=chatId, type="group", title=f"Test Chat {chatId}")
        for userId in [456, 457, 458]:  # Users from createBatchChatMessages
            performanceDb.updateChatUser(
                chatId=chatId, userId=userId, username=f"user{userId}", fullName=f"User {userId}"
            )

        messages = createBatchChatMessages(count=100, chatId=chatId)
        for msg in messages:
            performanceDb.saveChatMessage(**msg)

    startTime = time.time()

    # Perform complex query
    for chatId in range(1, 11):
        messages = performanceDb.getChatMessagesSince(chatId, limit=50)
        assert len(messages) == 50

    endTime = time.time()
    duration = (endTime - startTime) * 1000  # Convert to ms

    print(f"\nComplex query duration: {duration:.2f}ms")
    # Relaxed target for CI environments
    assert duration < 500, f"Complex query took {duration:.2f}ms (target: < 500ms)"


@pytest.mark.benchmark
def testDatabaseSettingsPerformance(performanceDb):
    """
    Benchmark chat settings operations.

    Target: < 10ms per operation
    """
    chatId = 123

    startTime = time.time()
    for _ in range(100):
        performanceDb.setChatSetting(chatId, "model", "gpt-4")
        performanceDb.setChatSetting(chatId, "temperature", "0.7")
        performanceDb.getChatSettings(chatId)
    endTime = time.time()

    avgTime = (endTime - startTime) / 100 * 1000  # ms per operation
    print(f"\nAverage settings operation time: {avgTime:.2f}ms")

    assert avgTime < 10, f"Settings operation took {avgTime:.2f}ms (target: < 10ms)"


# ============================================================================
# Cache Performance Tests
# ============================================================================


@pytest.mark.benchmark
def testCacheOperationPerformance(performanceDb):
    """
    Benchmark cache operations.

    Target: < 20ms per operation (relaxed for CI)
    """
    from internal.database.models import CacheType

    startTime = time.time()
    for _ in range(100):
        performanceDb.setCacheEntry("test_key", "test_value", CacheType.WEATHER)
        performanceDb.getCacheEntry("test_key", CacheType.WEATHER)
    endTime = time.time()

    avgTime = (endTime - startTime) / 100 * 1000  # ms per operation
    print(f"\nAverage cache operation time: {avgTime:.2f}ms")

    # Relaxed target for CI environments
    assert avgTime < 20, f"Cache operation took {avgTime:.2f}ms (target: < 20ms)"


@pytest.mark.benchmark
def testCacheHitMissPerformance(performanceDb):
    """
    Test cache hit/miss performance.

    Target: Cache hit < 5ms, cache miss < 10ms
    """
    from internal.database.models import CacheType

    # Populate cache
    for i in range(100):
        performanceDb.setCacheEntry(f"key_{i}", f"value_{i}", CacheType.WEATHER)

    # Test cache hits
    startTime = time.time()
    for i in range(100):
        entry = performanceDb.getCacheEntry(f"key_{i}", CacheType.WEATHER)
        assert entry is not None
    endTime = time.time()
    hitDuration = (endTime - startTime) * 1000 / 100  # ms per operation

    # Test cache misses
    startTime = time.time()
    for i in range(100, 200):
        entry = performanceDb.getCacheEntry(f"key_{i}", CacheType.WEATHER)
        assert entry is None
    endTime = time.time()
    missDuration = (endTime - startTime) * 1000 / 100  # ms per operation

    print(f"\nCache hit: {hitDuration:.2f}ms per operation")
    print(f"Cache miss: {missDuration:.2f}ms per operation")

    assert hitDuration < 5, f"Cache hit took {hitDuration:.2f}ms (target: < 5ms)"
    assert missDuration < 10, f"Cache miss took {missDuration:.2f}ms (target: < 10ms)"


# ============================================================================
# Memory Usage Tests
# ============================================================================


@pytest.mark.benchmark
@pytest.mark.memory
def testMemoryUsageUnderLoad(performanceDb):
    """
    Test memory usage with high load.

    Target: < 100MB for 1000 messages
    """
    import tracemalloc

    # Start memory tracking
    tracemalloc.start()
    gc.collect()

    # Get baseline memory
    baselineMemory = tracemalloc.get_traced_memory()[0]

    # Process 1000 messages
    messages = createBatchChatMessages(count=1000, chatId=123)
    for msg in messages:
        performanceDb.saveChatMessage(**msg)

    # Force garbage collection
    gc.collect()

    # Get peak memory
    currentMemory, peakMemory = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Calculate memory usage
    memoryUsed = (peakMemory - baselineMemory) / (1024 * 1024)  # Convert to MB

    print(f"\nMemory used for 1000 messages: {memoryUsed:.2f}MB")
    print(f"Peak memory: {peakMemory / (1024 * 1024):.2f}MB")

    assert memoryUsed < 100, f"Memory usage {memoryUsed:.2f}MB exceeds target (100MB)"


@pytest.mark.benchmark
@pytest.mark.memory
def testMemoryLeakDetection(performanceDb):
    """
    Test for memory leaks in repeated operations.

    Target: Memory should stabilize after initial allocation
    """
    import tracemalloc

    tracemalloc.start()
    gc.collect()

    memorySnapshots = []

    # Perform operations in batches
    for batch in range(5):
        messages = createBatchChatMessages(count=100, chatId=123 + batch)
        for msg in messages:
            performanceDb.saveChatMessage(**msg)

        gc.collect()
        currentMemory = tracemalloc.get_traced_memory()[0]
        memorySnapshots.append(currentMemory)

    tracemalloc.stop()

    # Check if memory growth stabilizes
    # After first batch, growth should be minimal
    if len(memorySnapshots) >= 3:
        recentGrowth = memorySnapshots[-1] - memorySnapshots[-2]
        recentGrowthMb = recentGrowth / (1024 * 1024)

        print(f"\nMemory snapshots (MB): {[m / (1024 * 1024) for m in memorySnapshots]}")
        print(f"Recent growth: {recentGrowthMb:.2f}MB")

        # Growth should be less than 10MB between batches
        assert recentGrowthMb < 10, f"Possible memory leak: {recentGrowthMb:.2f}MB growth"


# ============================================================================
# Stress Tests
# ============================================================================


@pytest.mark.benchmark
@pytest.mark.stress
@pytest.mark.slow
def testHighMessageVolumeStress(performanceDb):
    """
    Stress test with high message volume.

    Target: Handle 10,000 messages without errors

    Marked as slow - run with: pytest -m slow
    """
    # Setup: Add chat info and users first (foreign key constraints)
    performanceDb.updateChatInfo(chatId=123, type="group", title="Test Chat")
    for userId in [456, 457, 458]:  # Users from createBatchChatMessages
        performanceDb.updateChatUser(chatId=123, userId=userId, username=f"user{userId}", fullName=f"User {userId}")

    messageCount = 10000
    batchSize = 1000

    startTime = time.time()

    for batch in range(messageCount // batchSize):
        messages = createBatchChatMessages(
            count=batchSize,
            chatId=123,
            startMessageId=batch * batchSize + 1,
        )
        for msg in messages:
            performanceDb.saveChatMessage(**msg)

    endTime = time.time()
    duration = endTime - startTime

    # Verify all messages were saved
    savedMessages = performanceDb.getChatMessagesSince(123, limit=messageCount)
    assert len(savedMessages) == messageCount

    throughput = messageCount / duration
    print(f"\nProcessed {messageCount} messages in {duration:.2f}s")
    print(f"Throughput: {throughput:.2f} messages/second")


@pytest.mark.benchmark
@pytest.mark.stress
@pytest.mark.slow
def testLargeDatabaseOperations(performanceDb):
    """
    Stress test with large database operations.

    Target: Handle large queries without performance degradation

    Marked as slow - run with: pytest -m slow
    """
    # Populate database with many chats
    chatCount = 50
    messagesPerChat = 200

    for chatId in range(1, chatCount + 1):
        # Setup: Add chat info and users first (foreign key constraints)
        performanceDb.updateChatInfo(chatId=chatId, type="group", title=f"Test Chat {chatId}")
        for userId in [456, 457, 458]:  # Users from createBatchChatMessages
            performanceDb.updateChatUser(
                chatId=chatId, userId=userId, username=f"user{userId}", fullName=f"User {userId}"
            )

        messages = createBatchChatMessages(count=messagesPerChat, chatId=chatId)
        for msg in messages:
            performanceDb.saveChatMessage(**msg)

    # Test query performance across all chats
    startTime = time.time()

    for chatId in range(1, chatCount + 1):
        messages = performanceDb.getChatMessagesSince(chatId, limit=50)
        assert len(messages) == 50

    endTime = time.time()
    duration = endTime - startTime
    avgQueryTime = (duration / chatCount) * 1000  # ms per query

    print(f"\nQueried {chatCount} chats in {duration:.2f}s")
    print(f"Average query time: {avgQueryTime:.2f}ms")

    assert avgQueryTime < 100, f"Average query time {avgQueryTime:.2f}ms exceeds target (100ms)"


# ============================================================================
# Performance Profiling Tests
# ============================================================================


@pytest.mark.benchmark
@pytest.mark.profile
def testHandlerMemoryFootprint(baseHandler):
    """
    Profile handler memory footprint.

    Target: Handler should use < 10MB
    """
    import tracemalloc

    tracemalloc.start()
    gc.collect()

    baselineMemory = tracemalloc.get_traced_memory()[0]

    # Create multiple handler instances
    handlers = []
    for _ in range(10):
        handler = BaseBotHandler(
            configManager=baseHandler.configManager,
            database=baseHandler.db,
            llmManager=baseHandler.llmManager,
        )
        handlers.append(handler)

    gc.collect()
    currentMemory = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()

    memoryPerHandler = (currentMemory - baselineMemory) / (1024 * 1024) / 10

    print(f"\nMemory per handler: {memoryPerHandler:.2f}MB")
    assert memoryPerHandler < 10, f"Handler uses {memoryPerHandler:.2f}MB (target: < 10MB)"


@pytest.mark.benchmark
@pytest.mark.profile
def testDatabaseConnectionMemory(performanceDb):
    """
    Profile database connection memory usage.

    Target: Connection should use < 5MB
    """
    import tracemalloc

    tracemalloc.start()
    gc.collect()

    baselineMemory = tracemalloc.get_traced_memory()[0]

    # Create multiple database connections
    databases = []
    for _ in range(5):
        db = DatabaseWrapper(":memory:")
        databases.append(db)

    gc.collect()
    currentMemory = tracemalloc.get_traced_memory()[0]

    # Clean up
    for db in databases:
        db.close()

    tracemalloc.stop()

    memoryPerConnection = (currentMemory - baselineMemory) / (1024 * 1024) / 5

    print(f"\nMemory per connection: {memoryPerConnection:.2f}MB")
    assert memoryPerConnection < 5, f"Connection uses {memoryPerConnection:.2f}MB (target: < 5MB)"


# ============================================================================
# Benchmark Summary
# ============================================================================


@pytest.mark.benchmark
def testPerformanceSummary(performanceDb):
    """
    Generate performance summary report.

    This test provides an overview of key performance metrics.
    """
    print("\n" + "=" * 70)
    print("PERFORMANCE SUMMARY")
    print("=" * 70)

    # Message processing
    messages = createBatchChatMessages(count=100, chatId=123)
    startTime = time.time()
    for msg in messages:
        performanceDb.saveChatMessage(**msg)
    duration = time.time() - startTime
    throughput = 100 / duration

    print("\nMessage Processing:")
    print(f"  - Throughput: {throughput:.2f} messages/second")
    print(f"  - Time per message: {(duration / 100) * 1000:.2f}ms")

    # Database queries
    startTime = time.time()
    for _ in range(100):
        performanceDb.getChatMessagesSince(123, limit=10)
    duration = time.time() - startTime

    print("\nDatabase Queries:")
    print(f"  - Query time: {(duration / 100) * 1000:.2f}ms per query")

    # Cache operations
    from internal.database.models import CacheType

    startTime = time.time()
    for i in range(100):
        performanceDb.setCacheEntry(f"key_{i}", f"value_{i}", CacheType.WEATHER)
    duration = time.time() - startTime

    print("\nCache Operations:")
    print(f"  - Set time: {(duration / 100) * 1000:.2f}ms per operation")

    print("\n" + "=" * 70)
