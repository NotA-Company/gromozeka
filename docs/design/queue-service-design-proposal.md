# Queue Service Design Proposal

## Executive Summary

Extract the queue management functionality from `internal/bot/handlers/main.py` into a standalone, reusable service that handles both async task queuing and delayed task scheduling with persistence support.

## Current State Analysis

### Existing Implementation
The `BotHandlers` class currently manages two queues:

1. **Async Tasks Queue** (`asyncTasksQueue`)
   - Type: `asyncio.Queue`
   - Purpose: Handle background tasks (e.g., image processing)
   - Features:
     - Size limit (`MAX_QUEUE_LENGTH = 32`)
     - Age tracking (`MAX_QUEUE_AGE = 30 minutes`)
     - FIFO processing with overflow handling

2. **Delayed Actions Queue** (`delayedActionsQueue`)
   - Type: `asyncio.PriorityQueue`
   - Purpose: Schedule future actions (e.g., send messages, delete messages)
   - Features:
     - Database persistence
     - Priority based on execution time
     - Support for various task types via `DelayedTaskFunction` enum

### Current Issues
- **Tight Coupling**: Queues are tightly coupled to `BotHandlers` class
- **Callback Hell**: Direct method calls on `self` make extraction difficult
- **Persistence Complexity**: Restoring state requires reconstructing callback context
- **Limited Reusability**: Cannot be used by other services

## Proposed Architecture

### Service Names (Options)

1. **TaskOrchestrator** ⭐ (Recommended)
   - Clear purpose indication
   - Professional sounding
   - Encompasses both queue types

2. **QueueManager**
   - Simple and descriptive
   - Might be too generic

3. **TaskScheduler**
   - Focus on scheduling aspect
   - Might not convey async queue functionality

4. **AsyncTaskService**
   - Emphasizes async nature
   - Less clear about delayed tasks

5. **TaskDispatcher**
   - Good for event-driven architecture
   - Clear action-oriented name

## Detailed Design

### Core Components

```python
# internal/services/task_orchestrator.py

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, Protocol
from dataclasses import dataclass
import asyncio
import time
import uuid
import json

class TaskHandler(Protocol):
    """Protocol for task handlers"""
    async def handle_task(self, task_type: str, **kwargs) -> Any:
        ...

@dataclass
class AsyncTask:
    """Represents an async task"""
    task_id: str
    task: asyncio.Task
    created_at: float
    metadata: Dict[str, Any]

@dataclass
class DelayedTask:
    """Represents a delayed task"""
    task_id: str
    execute_at: float
    task_type: str
    payload: Dict[str, Any]
    persist: bool = True
    
    def __lt__(self, other: "DelayedTask") -> bool:
        return self.execute_at < other.execute_at

class TaskOrchestrator:
    """
    Unified task management service handling both async and delayed tasks
    """
    
    def __init__(
        self,
        database: Optional['DatabaseWrapper'] = None,
        max_queue_size: int = 32,
        max_queue_age: float = 1800,  # 30 minutes
        process_interval: float = 10.0
    ):
        self._async_queue: asyncio.Queue = asyncio.Queue()
        self._delayed_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._handlers: Dict[str, TaskHandler] = {}
        self._db = database
        self._max_queue_size = max_queue_size
        self._max_queue_age = max_queue_age
        self._process_interval = process_interval
        self._queue_last_updated = time.time()
        self._is_running = False
        self._processor_task: Optional[asyncio.Task] = None
    
    def register_handler(self, task_type: str, handler: TaskHandler) -> None:
        """Register a handler for a specific task type"""
        self._handlers[task_type] = handler
    
    async def add_async_task(
        self, 
        task: asyncio.Task,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add an async task to the queue"""
        task_id = str(uuid.uuid4())
        
        # Handle queue overflow
        if self._async_queue.qsize() >= self._max_queue_size:
            old_task = await self._async_queue.get()
            if isinstance(old_task, AsyncTask):
                await old_task.task
            self._async_queue.task_done()
        
        async_task = AsyncTask(
            task_id=task_id,
            task=task,
            created_at=time.time(),
            metadata=metadata or {}
        )
        
        await self._async_queue.put(async_task)
        self._queue_last_updated = time.time()
        return task_id
    
    async def schedule_delayed_task(
        self,
        task_type: str,
        delay_seconds: float,
        payload: Dict[str, Any],
        persist: bool = True,
        task_id: Optional[str] = None
    ) -> str:
        """Schedule a delayed task"""
        if task_id is None:
            task_id = str(uuid.uuid4())
        
        execute_at = time.time() + delay_seconds
        
        delayed_task = DelayedTask(
            task_id=task_id,
            execute_at=execute_at,
            task_type=task_type,
            payload=payload,
            persist=persist
        )
        
        await self._delayed_queue.put(delayed_task)
        
        # Persist if requested
        if persist and self._db:
            self._db.addDelayedTask(
                taskId=task_id,
                function=task_type,
                kwargs=json.dumps(payload),
                delayedTS=int(execute_at)
            )
        
        return task_id
    
    async def restore_from_database(self) -> int:
        """Restore pending tasks from database"""
        if not self._db:
            return 0
        
        tasks = self._db.getPendingDelayedTasks()
        for task_data in tasks:
            delayed_task = DelayedTask(
                task_id=task_data["id"],
                execute_at=float(task_data["delayed_ts"]),
                task_type=task_data["function"],
                payload=json.loads(task_data["kwargs"]),
                persist=False  # Already in DB
            )
            await self._delayed_queue.put(delayed_task)
        
        return len(tasks)
    
    async def start(self) -> None:
        """Start the task processor"""
        if self._is_running:
            return
        
        self._is_running = True
        
        # Restore tasks from DB
        restored_count = await self.restore_from_database()
        if restored_count > 0:
            logger.info(f"Restored {restored_count} delayed tasks from database")
        
        # Start processors
        self._processor_task = asyncio.create_task(self._process_loop())
    
    async def stop(self) -> None:
        """Stop the task processor"""
        self._is_running = False
        
        # Process remaining async tasks
        await self._process_async_tasks(force_all=True)
        
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
    
    async def _process_loop(self) -> None:
        """Main processing loop for both queues"""
        while self._is_running:
            try:
                # Process delayed tasks
                await self._process_delayed_tasks()
                
                # Process async tasks if needed
                await self._process_async_tasks()
                
                # Small delay to prevent busy waiting
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in task processor loop: {e}")
                logger.exception(e)
    
    async def _process_delayed_tasks(self) -> None:
        """Process delayed tasks that are ready"""
        while not self._delayed_queue.empty():
            try:
                # Peek at the next task
                task = await asyncio.wait_for(
                    self._delayed_queue.get(), 
                    timeout=0.01
                )
                
                if not isinstance(task, DelayedTask):
                    self._delayed_queue.task_done()
                    continue
                
                # Check if it's time to execute
                if task.execute_at > time.time():
                    # Put it back and wait
                    self._delayed_queue.task_done()
                    await self._delayed_queue.put(task)
                    break
                
                # Execute the task
                await self._execute_delayed_task(task)
                
                # Mark as done in DB
                if self._db and task.persist:
                    self._db.updateDelayedTask(task.task_id, True)
                
                self._delayed_queue.task_done()
                
            except asyncio.TimeoutError:
                break
            except Exception as e:
                logger.error(f"Error processing delayed task: {e}")
    
    async def _execute_delayed_task(self, task: DelayedTask) -> None:
        """Execute a delayed task using registered handler"""
        handler = self._handlers.get(task.task_type)
        if not handler:
            logger.error(f"No handler registered for task type: {task.task_type}")
            return
        
        try:
            await handler.handle_task(task.task_type, **task.payload)
        except Exception as e:
            logger.error(f"Error executing task {task.task_id}: {e}")
            logger.exception(e)
    
    async def _process_async_tasks(self, force_all: bool = False) -> None:
        """Process async tasks based on age or force flag"""
        if self._async_queue.empty():
            return
        
        should_process = (
            force_all or 
            (time.time() - self._queue_last_updated) > self._max_queue_age
        )
        
        if not should_process:
            return
        
        self._queue_last_updated = time.time()
        
        try:
            while not self._async_queue.empty():
                task = self._async_queue.get_nowait()
                if isinstance(task, AsyncTask):
                    try:
                        await task.task
                    except Exception as e:
                        logger.error(f"Error in async task {task.task_id}: {e}")
                        logger.exception(e)
                
                self._async_queue.task_done()
        except asyncio.QueueEmpty:
            pass
```

### Handler Implementation Pattern

```python
# internal/bot/handlers/task_handlers.py

class BotTaskHandler:
    """Handler for bot-specific tasks"""
    
    def __init__(self, bot: ExtBot, db: DatabaseWrapper):
        self._bot = bot
        self._db = db
    
    async def handle_task(self, task_type: str, **kwargs) -> Any:
        """Route task to appropriate handler method"""
        handlers = {
            "send_message": self._handle_send_message,
            "delete_message": self._handle_delete_message,
            "process_background": self._handle_process_background,
        }
        
        handler = handlers.get(task_type)
        if not handler:
            raise ValueError(f"Unknown task type: {task_type}")
        
        return await handler(**kwargs)
    
    async def _handle_send_message(
        self, 
        chat_id: int,
        message_text: str,
        message_id: int,
        thread_id: Optional[int] = None,
        **kwargs
    ) -> None:
        """Handle send message task"""
        # Implementation here
        await self._bot.send_message(
            chat_id=chat_id,
            text=message_text,
            reply_to_message_id=message_id,
            message_thread_id=thread_id
        )
    
    async def _handle_delete_message(
        self,
        chat_id: int,
        message_id: int,
        **kwargs
    ) -> None:
        """Handle delete message task"""
        await self._bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )
```

### Integration with BotHandlers

```python
# internal/bot/handlers/main.py

class BotHandlers(CommandHandlerMixin):
    def __init__(self, configManager: ConfigManager, database: DatabaseWrapper, llmManager: LLMManager):
        # ... existing init code ...
        
        # Initialize task orchestrator
        self.taskOrchestrator = TaskOrchestrator(
            database=database,
            max_queue_size=constants.MAX_QUEUE_LENGTH,
            max_queue_age=constants.MAX_QUEUE_AGE
        )
        
        # Create and register task handler
        self.taskHandler = BotTaskHandler(bot=self._bot, db=database)
        self.taskOrchestrator.register_handler("send_message", self.taskHandler)
        self.taskOrchestrator.register_handler("delete_message", self.taskHandler)
        self.taskOrchestrator.register_handler("process_background", self.taskHandler)
    
    async def initDelayedScheduler(self, bot: ExtBot) -> None:
        """Initialize the task orchestrator"""
        self._bot = bot
        self.taskHandler._bot = bot  # Update bot reference
        await self.taskOrchestrator.start()
    
    async def initExit(self) -> None:
        """Cleanup on exit"""
        await self.taskOrchestrator.stop()
    
    async def addTaskToAsyncedQueue(self, task: asyncio.Task) -> None:
        """Add async task - now delegates to orchestrator"""
        await self.taskOrchestrator.add_async_task(task)
    
    async def _delayedSendMessage(
        self,
        ensuredMessage: EnsuredMessage,
        delayedUntil: float,
        messageText: str,
        messageCategory: MessageCategory = MessageCategory.BOT
    ) -> None:
        """Schedule a delayed message"""
        delay_seconds = delayedUntil - time.time()
        
        await self.taskOrchestrator.schedule_delayed_task(
            task_type="send_message",
            delay_seconds=delay_seconds,
            payload={
                "chat_id": ensuredMessage.chat.id,
                "message_text": messageText,
                "message_id": ensuredMessage.messageId,
                "thread_id": ensuredMessage.threadId,
                "message_category": messageCategory.value
            }
        )
```

## Benefits

### 1. **Separation of Concerns**
- Queue management logic isolated from bot logic
- Clear boundaries between services

### 2. **Improved Testability**
- Can test queue service independently
- Mock handlers for unit tests

### 3. **Reusability**
- Other services can use the task orchestrator
- Not limited to bot handlers

### 4. **Flexibility**
- Easy to add new task types
- Can swap storage backends

### 5. **Maintainability**
- Cleaner code structure
- Easier to debug and extend

## Migration Strategy

### Phase 1: Create Service
1. Implement `TaskOrchestrator` class
2. Create unit tests for the service
3. Implement `BotTaskHandler` for bot-specific tasks

### Phase 2: Integration
1. Update `BotHandlers` to use `TaskOrchestrator`
2. Create wrapper methods for backward compatibility
3. Test with existing functionality

### Phase 3: Migration
1. Replace direct queue usage with service calls
2. Update all task creation points
3. Remove old queue code

### Phase 4: Enhancement
1. Add metrics collection
2. Implement task priorities
3. Add task retry logic

## Alternative Approaches

### 1. **Event-Driven Architecture**
- Use event bus pattern
- Pros: More decoupled
- Cons: More complex

### 2. **Message Queue Service**
- Use external service (RabbitMQ, Redis)
- Pros: Scalable, persistent
- Cons: External dependency

### 3. **Actor Model**
- Each handler as an actor
- Pros: Highly concurrent
- Cons: Complex for this use case

## Conclusion

The proposed `TaskOrchestrator` service provides a clean separation of queue management from bot logic while maintaining flexibility and ease of use. The handler pattern allows for easy extension and the service can be reused across the application.

## Next Steps

1. Review and approve the design
2. Implement the core service
3. Create comprehensive tests
4. Integrate with existing code
5. Document usage patterns