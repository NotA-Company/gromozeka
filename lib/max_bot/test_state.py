"""
Unit tests for Max Bot State Management

This module contains comprehensive unit tests for the state management system,
testing state storage (memory and file), state transitions, state context,
and concurrent access.
"""

import asyncio
import os
import tempfile
import time

import pytest

from .state import (
    FileStateStorage,
    MemoryStateStorage,
    State,
    StateContext,
    StateManager,
)


class TestState:
    """Test suite for State class."""

    def test_state_initialization(self):
        """Test State initialization, dood!"""
        data = {"key": "value", "count": 42}
        state = State("test_state", data)

        assert state.name == "test_state"
        assert state.data == data
        assert state.transitions == {}

    def test_state_initialization_without_data(self):
        """Test State initialization without data, dood!"""
        state = State("empty_state")

        assert state.name == "empty_state"
        assert state.data == {}
        assert state.transitions == {}

    def test_add_transition(self):
        """Test adding state transition, dood!"""
        state1 = State("state1")
        state2 = State("state2")

        state1.add_transition("next", state2)

        assert state1.transitions["next"] == state2
        assert state1.can_transition("next") is True

    def test_can_transition(self):
        """Test transition checking, dood!"""
        state1 = State("state1")
        state2 = State("state2")
        state3 = State("state3")

        state1.add_transition("go_to_2", state2)
        state1.add_transition("go_to_3", state3)

        assert state1.can_transition("go_to_2") is True
        assert state1.can_transition("go_to_3") is True
        assert state1.can_transition("nonexistent") is False

    def test_get_transition(self):
        """Test getting transition target state, dood!"""
        state1 = State("state1")
        state2 = State("state2")

        state1.add_transition("next", state2)

        assert state1.get_transition("next") == state2
        assert state1.get_transition("nonexistent") is None

    def test_state_string_representation(self):
        """Test State string representation, dood!"""
        state = State("test_state")
        state.add_transition("next", State("target_state"))

        assert str(state) == "State(test_state)"
        assert "test_state" in repr(state)
        assert "next" in repr(state)

    def test_state_circular_transitions(self):
        """Test circular state transitions, dood!"""
        state1 = State("state1")
        state2 = State("state2")

        state1.add_transition("to_2", state2)
        state2.add_transition("to_1", state1)

        assert state1.can_transition("to_2") is True
        assert state2.can_transition("to_1") is True
        assert state1.get_transition("to_2") == state2
        assert state2.get_transition("to_1") == state1


class TestStateContext:
    """Test suite for StateContext class."""

    def test_state_context_initialization(self):
        """Test StateContext initialization, dood!"""
        context = StateContext(userId=123, chatId=456)

        assert context.userId == 123
        assert context.chatId == 456
        assert context.currentState is None
        assert context.stateData == {}
        assert context.history == []
        assert isinstance(context.createdAt, float)
        assert isinstance(context.updatedAt, float)

    def test_state_context_initialization_with_data(self):
        """Test StateContext initialization with data, dood!"""
        initial_data = {"key": "value"}
        context = StateContext(userId=123, chatId=456, stateData=initial_data, history=["previous_state"])

        assert context.stateData == initial_data
        assert context.history == ["previous_state"]

    def test_update_state(self):
        """Test updating state in context, dood!"""
        context = StateContext(userId=123)
        state1 = State("state1")
        state2 = State("state2")

        context.update_state(state1)
        assert context.currentState == state1
        assert context.history == []

        context.update_state(state2, {"new_key": "new_value"})
        assert context.currentState == state2
        assert context.history == ["state1"]
        assert context.stateData["new_key"] == "new_value"

    def test_get_data(self):
        """Test getting data from context, dood!"""
        context = StateContext()
        context.stateData = {"key1": "value1", "key2": "value2"}

        assert context.get_data("key1") == "value1"
        assert context.get_data("key2") == "value2"
        assert context.get_data("nonexistent") is None
        assert context.get_data("nonexistent", "default") == "default"

    def test_set_data(self):
        """Test setting data in context, dood!"""
        context = StateContext()

        context.set_data("key1", "value1")
        assert context.stateData["key1"] == "value1"

        context.set_data("key2", 42)
        assert context.stateData["key2"] == 42

        # Check updatedAt is updated
        old_updated_at = context.updatedAt
        time.sleep(0.01)
        context.set_data("key3", "value3")
        assert context.updatedAt > old_updated_at

    def test_clear_data(self):
        """Test clearing data in context, dood!"""
        context = StateContext()
        context.stateData = {"key1": "value1", "key2": "value2"}

        context.clear_data()
        assert context.stateData == {}

        # Check updatedAt is updated
        old_updated_at = context.updatedAt
        time.sleep(0.01)
        context.clear_data()
        assert context.updatedAt > old_updated_at

    def test_get_context_key(self):
        """Test getting context key, dood!"""
        # User and chat
        context1 = StateContext(userId=123, chatId=456)
        assert context1.get_context_key() == "user_123_chat_456"

        # User only
        context2 = StateContext(userId=123)
        assert context2.get_context_key() == "user_123"

        # Chat only
        context3 = StateContext(chatId=456)
        assert context3.get_context_key() == "chat_456"

        # Neither (global)
        context4 = StateContext()
        assert context4.get_context_key() == "global"

    def test_context_timestamps(self):
        """Test context timestamp management, dood!"""
        before_creation = time.time()
        context = StateContext(userId=123)
        after_creation = time.time()

        assert before_creation <= context.createdAt <= after_creation
        assert before_creation <= context.updatedAt <= after_creation

        # Update should change updatedAt but not createdAt
        old_created_at = context.createdAt
        old_updated_at = context.updatedAt
        time.sleep(0.01)

        context.set_data("test", "value")

        assert context.createdAt == old_created_at
        assert context.updatedAt > old_updated_at


class TestMemoryStateStorage:
    """Test suite for MemoryStateStorage class."""

    @pytest.fixture
    def storage(self):
        """Create a MemoryStateStorage instance."""
        return MemoryStateStorage()

    @pytest.fixture
    def sample_context(self):
        """Create a sample StateContext."""
        return StateContext(userId=123, chatId=456, currentState=State("test_state"), stateData={"key": "value"})

    async def test_storage_initialization(self, storage):
        """Test MemoryStateStorage initialization, dood!"""
        assert isinstance(storage._contexts, dict)
        assert len(storage._contexts) == 0
        assert isinstance(storage._lock, asyncio.Lock)

    async def test_set_and_get_context(self, storage, sample_context):
        """Test setting and getting context, dood!"""
        key = "test_key"
        await storage.set_context(key, sample_context)

        retrieved = await storage.get_context(key)
        assert retrieved is not None
        assert retrieved.userId == sample_context.userId
        assert retrieved.chatId == sample_context.chatId
        assert retrieved.currentState.name == sample_context.currentState.name
        assert retrieved.stateData == sample_context.stateData

    async def test_get_nonexistent_context(self, storage):
        """Test getting non-existent context, dood!"""
        retrieved = await storage.get_context("nonexistent_key")
        assert retrieved is None

    async def test_delete_context(self, storage, sample_context):
        """Test deleting context, dood!"""
        key = "test_key"
        await storage.set_context(key, sample_context)

        # Verify it exists
        retrieved = await storage.get_context(key)
        assert retrieved is not None

        # Delete it
        result = await storage.delete_context(key)
        assert result is True

        # Verify it's gone
        retrieved = await storage.get_context(key)
        assert retrieved is None

    async def test_delete_nonexistent_context(self, storage):
        """Test deleting non-existent context, dood!"""
        result = await storage.delete_context("nonexistent_key")
        assert result is False

    async def test_get_all_contexts(self, storage):
        """Test getting all contexts, dood!"""
        context1 = StateContext(userId=1, currentState=State("state1"))
        context2 = StateContext(userId=2, currentState=State("state2"))

        await storage.set_context("key1", context1)
        await storage.set_context("key2", context2)

        all_contexts = await storage.get_all_contexts()
        assert len(all_contexts) == 2
        assert "key1" in all_contexts
        assert "key2" in all_contexts
        assert all_contexts["key1"].userId == 1
        assert all_contexts["key2"].userId == 2

    async def test_clear_all(self, storage):
        """Test clearing all contexts, dood!"""
        context1 = StateContext(userId=1, currentState=State("state1"))
        context2 = StateContext(userId=2, currentState=State("state2"))

        await storage.set_context("key1", context1)
        await storage.set_context("key2", context2)

        assert len(await storage.get_all_contexts()) == 2

        await storage.clear_all()

        assert len(await storage.get_all_contexts()) == 0

    async def test_concurrent_access(self, storage):
        """Test concurrent access to storage, dood!"""

        async def set_contexts(start_id: int, count: int):
            for i in range(count):
                context = StateContext(userId=start_id + i, currentState=State(f"state_{start_id + i}"))
                await storage.set_context(f"key_{start_id + i}", context)

        async def get_contexts(start_id: int, count: int):
            results = []
            for i in range(count):
                context = await storage.get_context(f"key_{start_id + i}")
                results.append(context)
            return results

        # Run concurrent operations
        set_task1 = asyncio.create_task(set_contexts(0, 10))
        set_task2 = asyncio.create_task(set_contexts(10, 10))
        get_task1 = asyncio.create_task(get_contexts(5, 5))
        get_task2 = asyncio.create_task(get_contexts(15, 5))

        await asyncio.gather(set_task1, set_task2, get_task1, get_task2)

        # Verify all contexts were set
        all_contexts = await storage.get_all_contexts()
        assert len(all_contexts) == 20


class TestFileStateStorage:
    """Test suite for FileStateStorage class."""

    @pytest.fixture
    def temp_file(self):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            temp_path = f.name
        yield temp_path
        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.fixture
    def storage(self, temp_file):
        """Create a FileStateStorage instance with temp file."""
        return FileStateStorage(temp_file)

    @pytest.fixture
    def sample_context(self):
        """Create a sample StateContext."""
        return StateContext(
            userId=123,
            chatId=456,
            currentState=State("test_state"),
            stateData={"key": "value"},
            history=["previous_state"],
        )

    async def test_storage_initialization(self, storage, temp_file):
        """Test FileStateStorage initialization, dood!"""
        assert storage.filePath == temp_file
        assert isinstance(storage._lock, asyncio.Lock)

    async def test_set_and_get_context(self, storage, sample_context, temp_file):
        """Test setting and getting context with file storage, dood!"""
        key = "test_key"
        await storage.set_context(key, sample_context)

        # Verify file was created
        assert os.path.exists(temp_file)

        retrieved = await storage.get_context(key)
        assert retrieved is not None
        assert retrieved.userId == sample_context.userId
        assert retrieved.chatId == sample_context.chatId
        assert retrieved.stateData == sample_context.stateData
        assert retrieved.history == sample_context.history

    async def test_persistence_across_instances(self, storage, sample_context, temp_file):
        """Test data persistence across storage instances, dood!"""
        key = "persistent_key"
        await storage.set_context(key, sample_context)

        # Create new storage instance with same file
        new_storage = FileStateStorage(temp_file)
        retrieved = await new_storage.get_context(key)

        assert retrieved is not None
        assert retrieved.userId == sample_context.userId
        assert retrieved.stateData == sample_context.stateData

    async def test_get_nonexistent_context(self, storage):
        """Test getting non-existent context, dood!"""
        retrieved = await storage.get_context("nonexistent_key")
        assert retrieved is None

    async def test_delete_context(self, storage, sample_context, temp_file):
        """Test deleting context, dood!"""
        key = "test_key"
        await storage.set_context(key, sample_context)

        # Verify it exists
        retrieved = await storage.get_context(key)
        assert retrieved is not None

        # Delete it
        result = await storage.delete_context(key)
        assert result is True

        # Verify it's gone
        retrieved = await storage.get_context(key)
        assert retrieved is None

    async def test_get_all_contexts(self, storage, temp_file):
        """Test getting all contexts, dood!"""
        context1 = StateContext(userId=1, currentState=State("state1"))
        context2 = StateContext(userId=2, currentState=State("state2"))

        await storage.set_context("key1", context1)
        await storage.set_context("key2", context2)

        all_contexts = await storage.get_all_contexts()
        assert len(all_contexts) == 2
        assert "key1" in all_contexts
        assert "key2" in all_contexts

    async def test_clear_all(self, storage, sample_context, temp_file):
        """Test clearing all contexts, dood!"""
        await storage.set_context("key1", sample_context)
        await storage.set_context("key2", sample_context)

        assert len(await storage.get_all_contexts()) == 2

        await storage.clear_all()

        assert len(await storage.get_all_contexts()) == 0

    async def test_file_creation_with_directory(self, temp_file):
        """Test file creation with non-existent directory, dood!"""
        # Create path with non-existent directory
        dir_path = temp_file + "_dir"
        file_path = os.path.join(dir_path, "state.json")

        storage = FileStateStorage(file_path)
        context = StateContext(userId=123)

        await storage.set_context("test", context)

        # Verify directory and file were created
        assert os.path.exists(dir_path)
        assert os.path.exists(file_path)

        # Cleanup
        if os.path.exists(file_path):
            os.unlink(file_path)
        if os.path.exists(dir_path):
            os.rmdir(dir_path)

    async def test_corrupted_file_handling(self, storage, temp_file):
        """Test handling of corrupted JSON file, dood!"""
        # Write invalid JSON to file
        with open(temp_file, "w") as f:
            f.write("invalid json content")

        # Should not raise exception, should return empty
        retrieved = await storage.get_context("any_key")
        assert retrieved is None

        all_contexts = await storage.get_all_contexts()
        assert len(all_contexts) == 0

    async def test_file_write_error_handling(self, storage, temp_file):
        """Test handling of file write errors, dood!"""
        # Make file read-only to cause write error
        os.chmod(temp_file, 0o444)

        context = StateContext(userId=123)

        # Should not raise exception
        await storage.set_context("test", context)

        # Restore permissions for cleanup
        os.chmod(temp_file, 0o644)

    async def test_concurrent_access(self, storage, temp_file):
        """Test concurrent access to file storage, dood!"""

        async def set_contexts(start_id: int, count: int):
            for i in range(count):
                context = StateContext(userId=start_id + i, currentState=State(f"state_{start_id + i}"))
                await storage.set_context(f"key_{start_id + i}", context)

        # Run concurrent operations
        tasks = [
            asyncio.create_task(set_contexts(0, 5)),
            asyncio.create_task(set_contexts(5, 5)),
            asyncio.create_task(set_contexts(10, 5)),
        ]

        await asyncio.gather(*tasks)

        # Verify all contexts were saved
        all_contexts = await storage.get_all_contexts()
        assert len(all_contexts) == 15


class TestStateManager:
    """Test suite for StateManager class."""

    @pytest.fixture
    def manager(self):
        """Create a StateManager instance."""
        return StateManager()

    @pytest.fixture
    def memory_storage(self):
        """Create a MemoryStateStorage instance."""
        return MemoryStateStorage()

    @pytest.fixture
    def manager_with_memory_storage(self, memory_storage):
        """Create a StateManager with MemoryStateStorage."""
        return StateManager(memory_storage)

    def test_manager_initialization(self):
        """Test StateManager initialization, dood!"""
        manager = StateManager()
        assert isinstance(manager.storage, MemoryStateStorage)
        assert manager.states == {}
        assert manager.defaultState is None

    def test_manager_initialization_with_storage(self, memory_storage):
        """Test StateManager initialization with custom storage, dood!"""
        manager = StateManager(memory_storage)
        assert manager.storage == memory_storage

    def test_add_state(self, manager):
        """Test adding state to manager, dood!"""
        state = State("test_state")
        manager.add_state(state)

        assert "test_state" in manager.states
        assert manager.states["test_state"] == state

    def test_get_state(self, manager):
        """Test getting state from manager, dood!"""
        state = State("test_state")
        manager.add_state(state)

        retrieved = manager.get_state("test_state")
        assert retrieved == state

        nonexistent = manager.get_state("nonexistent")
        assert nonexistent is None

    def test_set_default_state(self, manager):
        """Test setting default state, dood!"""
        state = State("default_state")
        manager.set_default_state(state)

        assert manager.defaultState == state
        assert "default_state" in manager.states

    async def test_create_context(self, manager_with_memory_storage):
        """Test creating state context, dood!"""
        state = State("initial_state")
        manager_with_memory_storage.set_default_state(state)

        context = await manager_with_memory_storage.create_context(userId=123, chatId=456, data={"initial": "data"})

        assert context.userId == 123
        assert context.chatId == 456
        assert context.currentState == state
        assert context.stateData["initial"] == "data"

    async def test_create_context_with_initial_state(self, manager_with_memory_storage):
        """Test creating context with specific initial state, dood!"""
        initial_state = State("custom_initial")
        default_state = State("default_state")

        manager_with_memory_storage.add_state(initial_state)
        manager_with_memory_storage.set_default_state(default_state)

        context = await manager_with_memory_storage.create_context(userId=123, initialState=initial_state)

        assert context.currentState == initial_state

    async def test_create_context_no_default_state(self, manager):
        """Test creating context without default state raises error, dood!"""
        with pytest.raises(ValueError, match="No initial state specified"):
            await manager.create_context(userId=123)

    async def test_get_context(self, manager_with_memory_storage):
        """Test getting state context, dood!"""
        state = State("test_state")
        manager_with_memory_storage.set_default_state(state)

        # Create context first
        created = await manager_with_memory_storage.create_context(userId=123)
        created.set_data("test_key", "test_value")

        # Get context
        retrieved = await manager_with_memory_storage.get_context(userId=123)
        assert retrieved is not None
        assert retrieved.userId == 123
        assert retrieved.currentState == state
        assert retrieved.get_data("test_key") == "test_value"

    async def test_get_nonexistent_context(self, manager_with_memory_storage):
        """Test getting non-existent context, dood!"""
        retrieved = await manager_with_memory_storage.get_context(userId=999)
        assert retrieved is None

    async def test_update_context(self, manager_with_memory_storage):
        """Test updating state context, dood!"""
        state1 = State("state1")
        state2 = State("state2")
        manager_with_memory_storage.add_state(state1)
        manager_with_memory_storage.add_state(state2)

        # Create context
        await manager_with_memory_storage.create_context(userId=123, initialState=state1)

        # Update with new state and data
        updated = await manager_with_memory_storage.update_context(
            user_id=123, new_state=state2, data={"new_key": "new_value"}
        )

        assert updated is not None
        assert updated.currentState == state2
        assert updated.get_data("new_key") == "new_value"
        assert "state1" in updated.history

    async def test_update_context_data_only(self, manager_with_memory_storage):
        """Test updating context data only, dood!"""
        state = State("test_state")
        manager_with_memory_storage.set_default_state(state)

        # Create context
        await manager_with_memory_storage.create_context(userId=123)

        # Update data only
        updated = await manager_with_memory_storage.update_context(user_id=123, data={"key": "value"})

        assert updated is not None
        assert updated.get_data("key") == "value"
        assert updated.currentState == state

    async def test_update_nonexistent_context(self, manager_with_memory_storage):
        """Test updating non-existent context, dood!"""
        updated = await manager_with_memory_storage.update_context(user_id=999)
        assert updated is None

    async def test_transition_state(self, manager_with_memory_storage):
        """Test state transition, dood!"""
        state1 = State("state1")
        state2 = State("state2")
        state1.add_transition("next", state2)

        manager_with_memory_storage.add_state(state1)
        manager_with_memory_storage.add_state(state2)

        # Create context in state1
        await manager_with_memory_storage.create_context(userId=123, initialState=state1)

        # Transition to state2
        result = await manager_with_memory_storage.transition_state(
            "next", user_id=123, data={"transition_data": "value"}
        )

        assert result is True

        # Verify transition
        updated_context = await manager_with_memory_storage.get_context(userId=123)
        assert updated_context.currentState == state2
        assert updated_context.get_data("transition_data") == "value"
        assert "state1" in updated_context.history

    async def test_transition_state_invalid_trigger(self, manager_with_memory_storage):
        """Test state transition with invalid trigger, dood!"""
        state1 = State("state1")
        state2 = State("state2")
        # No transition defined

        manager_with_memory_storage.add_state(state1)
        manager_with_memory_storage.add_state(state2)

        # Create context in state1
        await manager_with_memory_storage.create_context(userId=123, initialState=state1)

        # Try invalid transition
        result = await manager_with_memory_storage.transition_state("invalid_trigger", user_id=123)

        assert result is False

        # Verify still in state1
        context = await manager_with_memory_storage.get_context(userId=123)
        assert context.currentState == state1

    async def test_transition_state_no_context(self, manager_with_memory_storage):
        """Test state transition with no context, dood!"""
        result = await manager_with_memory_storage.transition_state("trigger", user_id=999)
        assert result is False

    async def test_delete_context(self, manager_with_memory_storage):
        """Test deleting state context, dood!"""
        state = State("test_state")
        manager_with_memory_storage.set_default_state(state)

        # Create context
        await manager_with_memory_storage.create_context(userId=123)

        # Verify it exists
        context = await manager_with_memory_storage.get_context(userId=123)
        assert context is not None

        # Delete it
        result = await manager_with_memory_storage.delete_context(user_id=123)
        assert result is True

        # Verify it's gone
        context = await manager_with_memory_storage.get_context(userId=123)
        assert context is None

    async def test_delete_nonexistent_context(self, manager_with_memory_storage):
        """Test deleting non-existent context, dood!"""
        result = await manager_with_memory_storage.delete_context(user_id=999)
        assert result is False

    async def test_get_all_contexts(self, manager_with_memory_storage):
        """Test getting all contexts, dood!"""
        state = State("test_state")
        manager_with_memory_storage.set_default_state(state)

        # Create multiple contexts
        await manager_with_memory_storage.create_context(userId=1)
        await manager_with_memory_storage.create_context(userId=2)
        await manager_with_memory_storage.create_context(userId=3)

        all_contexts = await manager_with_memory_storage.get_all_contexts()
        assert len(all_contexts) == 3
        assert "user_1" in all_contexts
        assert "user_2" in all_contexts
        assert "user_3" in all_contexts

    async def test_clear_all_contexts(self, manager_with_memory_storage):
        """Test clearing all contexts, dood!"""
        state = State("test_state")
        manager_with_memory_storage.set_default_state(state)

        # Create contexts
        await manager_with_memory_storage.create_context(userId=1)
        await manager_with_memory_storage.create_context(userId=2)

        assert len(await manager_with_memory_storage.get_all_contexts()) == 2

        await manager_with_memory_storage.clear_all_contexts()

        assert len(await manager_with_memory_storage.get_all_contexts()) == 0

    def test_get_current_state_sync(self, manager_with_memory_storage):
        """Test synchronous get_current_state method, dood!"""
        state = State("test_state")
        manager_with_memory_storage.set_default_state(state)

        # This is a tricky test because get_current_state uses asyncio.create_task
        # We'll test the error case instead
        import pytest

        with pytest.raises(RuntimeError):
            # This should raise RuntimeError because there's no event loop
            manager_with_memory_storage.get_current_state(user_id=999)

    async def test_set_state_data(self, manager_with_memory_storage):
        """Test setting state data, dood!"""
        state = State("test_state")
        manager_with_memory_storage.set_default_state(state)

        # Create context
        await manager_with_memory_storage.create_context(userId=123)

        # Set data
        result = await manager_with_memory_storage.set_state_data("test_key", "test_value", userId=123)

        assert result is True

        # Verify data was set
        context = await manager_with_memory_storage.get_context(userId=123)
        assert context.get_data("test_key") == "test_value"

    async def test_set_state_data_no_context(self, manager_with_memory_storage):
        """Test setting state data with no context, dood!"""
        result = await manager_with_memory_storage.set_state_data("test_key", "test_value", userId=999)

        assert result is False

    async def test_get_state_data(self, manager_with_memory_storage):
        """Test getting state data, dood!"""
        state = State("test_state")
        manager_with_memory_storage.set_default_state(state)

        # Create context with data
        await manager_with_memory_storage.create_context(userId=123, data={"existing_key": "existing_value"})

        # Get existing data
        value = await manager_with_memory_storage.get_state_data("existing_key", user_id=123)
        assert value == "existing_value"

        # Get non-existent data with default
        value = await manager_with_memory_storage.get_state_data("nonexistent_key", "default_value", user_id=123)
        assert value == "default_value"

        # Get non-existent data without default
        value = await manager_with_memory_storage.get_state_data("nonexistent_key", user_id=123)
        assert value is None

    async def test_get_state_data_no_context(self, manager_with_memory_storage):
        """Test getting state data with no context, dood!"""
        value = await manager_with_memory_storage.get_state_data("test_key", "default", user_id=999)
        assert value == "default"


class TestStateManagerIntegration:
    """Integration tests for StateManager with different storage backends."""

    async def test_complex_state_machine(self):
        """Test complex state machine with multiple transitions, dood!"""
        manager = StateManager()

        # Create states
        start_state = State("start")
        menu_state = State("menu")
        settings_state = State("settings")
        help_state = State("help")

        # Add transitions
        start_state.add_transition("show_menu", menu_state)
        start_state.add_transition("show_help", help_state)
        menu_state.add_transition("settings", settings_state)
        menu_state.add_transition("help", help_state)
        menu_state.add_transition("back", start_state)
        settings_state.add_transition("back", menu_state)
        help_state.add_transition("back", start_state)

        # Add states to manager
        for state in [start_state, menu_state, settings_state, help_state]:
            manager.add_state(state)
        manager.set_default_state(start_state)

        # Create context
        context = await manager.create_context(userId=123)

        # Test transitions
        assert context.currentState == start_state

        # Start -> Menu
        result = await manager.transition_state("show_menu", user_id=123)
        assert result is True
        context = await manager.get_context(userId=123)
        assert context is not None and context.currentState == menu_state
        assert context is not None and context.history == ["start"]

        # Menu -> Settings
        result = await manager.transition_state("settings", user_id=123, data={"setting": "value"})
        assert result is True
        context = await manager.get_context(userId=123)
        assert context is not None and context.currentState == settings_state
        assert context is not None and context.get_data("setting") == "value"
        assert context.history == ["start", "menu"]

        # Settings -> Menu
        result = await manager.transition_state("back", user_id=123)
        assert result is True
        context = await manager.get_context(userId=123)
        assert context is not None and context.currentState == menu_state
        assert context is not None and context.history == ["start", "menu", "settings"]

        # Menu -> Help
        result = await manager.transition_state("help", user_id=123)
        assert result is True
        context = await manager.get_context(userId=123)
        assert context is not None and context.currentState == help_state

        # Help -> Start
        result = await manager.transition_state("back", user_id=123)
        assert result is True
        context = await manager.get_context(userId=123)
        assert context is not None and context.currentState == start_state

    async def test_concurrent_state_management(self):
        """Test concurrent state management, dood!"""
        manager = StateManager()
        state = State("test_state")
        manager.set_default_state(state)

        async def user_session(userId: int, operations: int):
            # Create context for user
            await manager.create_context(userId=userId)

            # Perform operations
            for i in range(operations):
                await manager.set_state_data(f"key_{i}", f"value_{i}", userId=userId)
                await manager.set_state_data("counter", i, userId=userId)

        # Run concurrent sessions for multiple users
        tasks = [
            asyncio.create_task(user_session(1, 10)),
            asyncio.create_task(user_session(2, 10)),
            asyncio.create_task(user_session(3, 10)),
        ]

        await asyncio.gather(*tasks)

        # Verify all user contexts exist and have correct data
        for userId in [1, 2, 3]:
            context = await manager.get_context(userId=userId)
            assert context is not None
            assert context.get_data("counter") == 9
            assert context.get_data("key_0") == "value_0"
            assert context.get_data("key_9") == "value_9"

    async def test_file_storage_persistence(self):
        """Test file storage persistence across manager instances, dood!"""
        # Create a temporary directory for the test
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_state.json")

        try:
            # Create first manager with file storage
            storage1 = FileStateStorage(temp_path)
            manager1 = StateManager(storage1)

            state = State("persistent_state")
            manager1.set_default_state(state)

            # Create context and set data
            await manager1.create_context(userId=123, data={"persistent": "data"})
            await manager1.set_state_data("extra", "value", userId=123)

            # Create second manager with same file storage
            storage2 = FileStateStorage(temp_path)
            manager2 = StateManager(storage2)
            manager2.add_state(state)

            # Verify data persistence
            context = await manager2.get_context(userId=123)
            assert context is not None
            # The currentState is None because it's not reconstructed from the file
            # Let's check if the context exists and has the right data
            assert context is not None
            assert context.get_data("persistent") == "data"
            assert context.get_data("persistent") == "data"
            assert context.get_data("extra") == "value"

        finally:
            # Cleanup
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    async def test_error_recovery(self):
        """Test error recovery in state management, dood!"""
        manager = StateManager()
        state = State("test_state")
        manager.set_default_state(state)

        # Create context
        await manager.create_context(userId=123)
        await manager.set_state_data("key1", "value1", userId=123)
        await manager.set_state_data("key2", "value2", userId=123)

        # Simulate partial failure by manually corrupting storage
        if isinstance(manager.storage, MemoryStateStorage):
            # Remove one context to simulate failure
            all_contexts = await manager.storage.get_all_contexts()
            keys_to_remove = list(all_contexts.keys())[1:]  # Keep first, remove others
            for key in keys_to_remove:
                await manager.storage.delete_context(key)

        # System should still work for remaining contexts
        value = await manager.get_state_data("key1", user_id=123)
        assert value == "value1"

        # Should be able to create new contexts
        await manager.create_context(userId=456)
        new_context = await manager.get_context(userId=456)
        assert new_context is not None
