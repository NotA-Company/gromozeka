"""
State management system for Max Messenger Bot API.

This module provides a comprehensive state management system that allows bots
to maintain conversation state across users and chats. Supports finite state
machine patterns, state transitions, and data persistence.
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class State:
    """Represents a state in a finite state machine.

    States can have transitions to other states and can store data.
    """

    def __init__(self, name: str, data: Optional[Dict[str, Any]] = None):
        """Initialize the state.

        Args:
            name: Name of the state
            data: Optional data associated with the state
        """
        self.name = name
        self.data = data or {}
        self.transitions: Dict[str, "State"] = {}

    def add_transition(self, trigger: str, target_state: "State") -> None:
        """Add a transition to another state.

        Args:
            trigger: Trigger that causes the transition
            target_state: State to transition to
        """
        self.transitions[trigger] = target_state

    def can_transition(self, trigger: str) -> bool:
        """Check if a transition is possible.

        Args:
            trigger: Trigger to check

        Returns:
            True if the transition is possible
        """
        return trigger in self.transitions

    def get_transition(self, trigger: str) -> Optional["State"]:
        """Get the target state for a trigger.

        Args:
            trigger: Trigger to get transition for

        Returns:
            Target state or None if no transition exists
        """
        return self.transitions.get(trigger)

    def __str__(self) -> str:
        """String representation of the state."""
        return f"State({self.name})"

    def __repr__(self) -> str:
        """Detailed string representation of the state."""
        return f"State(name={self.name}, transitions={list(self.transitions.keys())})"


@dataclass(slots=True)
class StateContext:
    """Context for storing state data for a specific user/chat combination."""

    userId: Optional[int] = None
    """User ID for this context"""
    chatId: Optional[int] = None
    """Chat ID for this context"""
    currentState: Optional[State] = None
    """Current state"""
    stateData: Dict[str, Any] = field(default_factory=dict)
    """Data stored in the current state"""
    history: List[str] = field(default_factory=list)
    """History of states visited"""
    createdAt: float = field(default_factory=lambda: __import__("time").time())
    """When this context was created"""
    updatedAt: float = field(default_factory=lambda: __import__("time").time())
    """When this context was last updated"""

    def update_state(self, new_state: State, data: Optional[Dict[str, Any]] = None) -> None:
        """Update the current state.

        Args:
            new_state: New state to transition to
            data: Optional data to store with the new state
        """
        if self.currentState:
            self.history.append(self.currentState.name)

        self.currentState = new_state
        if data:
            self.stateData.update(data)

        import time

        self.updatedAt = time.time()

    def get_data(self, key: str, default: Any = None) -> Any:
        """Get data from the current state.

        Args:
            key: Data key
            default: Default value if key not found

        Returns:
            Data value or default
        """
        return self.stateData.get(key, default)

    def set_data(self, key: str, value: Any) -> None:
        """Set data in the current state.

        Args:
            key: Data key
            value: Data value
        """
        self.stateData[key] = value
        import time

        self.updatedAt = time.time()

    def clear_data(self) -> None:
        """Clear all state data."""
        self.stateData.clear()
        import time

        self.updatedAt = time.time()

    def get_context_key(self) -> str:
        """Get a unique key for this context."""
        if self.userId and self.chatId:
            return f"user_{self.userId}_chat_{self.chatId}"
        elif self.userId:
            return f"user_{self.userId}"
        elif self.chatId:
            return f"chat_{self.chatId}"
        else:
            return "global"


class StateStorage(ABC):
    """Abstract base class for state storage implementations."""

    @abstractmethod
    async def get_context(self, key: str) -> Optional[StateContext]:
        """Get a state context by key.

        Args:
            key: Context key

        Returns:
            State context or None if not found
        """
        pass

    @abstractmethod
    async def set_context(self, key: str, context: StateContext) -> None:
        """Set a state context.

        Args:
            key: Context key
            context: State context to store
        """
        pass

    @abstractmethod
    async def delete_context(self, key: str) -> bool:
        """Delete a state context.

        Args:
            key: Context key

        Returns:
            True if context was deleted
        """
        pass

    @abstractmethod
    async def get_all_contexts(self) -> Dict[str, StateContext]:
        """Get all state contexts.

        Returns:
            Dictionary of all contexts
        """
        pass

    @abstractmethod
    async def clear_all(self) -> None:
        """Clear all state contexts."""
        pass


class MemoryStateStorage(StateStorage):
    """In-memory state storage implementation."""

    def __init__(self):
        """Initialize the memory storage."""
        self._contexts: Dict[str, StateContext] = {}
        self._lock = asyncio.Lock()

    async def get_context(self, key: str) -> Optional[StateContext]:
        """Get a state context by key."""
        async with self._lock:
            return self._contexts.get(key)

    async def set_context(self, key: str, context: StateContext) -> None:
        """Set a state context."""
        async with self._lock:
            self._contexts[key] = context

    async def delete_context(self, key: str) -> bool:
        """Delete a state context."""
        async with self._lock:
            if key in self._contexts:
                del self._contexts[key]
                return True
            return False

    async def get_all_contexts(self) -> Dict[str, StateContext]:
        """Get all state contexts."""
        async with self._lock:
            return self._contexts.copy()

    async def clear_all(self) -> None:
        """Clear all state contexts."""
        async with self._lock:
            self._contexts.clear()


class FileStateStorage(StateStorage):
    """File-based state storage implementation."""

    def __init__(self, file_path: str):
        """Initialize the file storage.

        Args:
            file_path: Path to the state storage file
        """
        self.filePath = file_path
        self._lock = asyncio.Lock()

    async def _load_contexts(self) -> Dict[str, StateContext]:
        """Load contexts from file."""
        try:
            import os

            if not os.path.exists(self.filePath):
                return {}

            with open(self.filePath, "r", encoding="utf-8") as f:
                data = json.load(f)

            contexts = {}
            for key, context_data in data.items():
                # Reconstruct StateContext from dict
                context = StateContext(
                    userId=context_data.get("userId"),
                    chatId=context_data.get("chatId"),
                    currentState=None,  # States need to be reconstructed separately
                    stateData=context_data.get("stateData", {}),
                    history=context_data.get("history", []),
                    createdAt=context_data.get("createdAt", 0),
                    updatedAt=context_data.get("updatedAt", 0),
                )
                contexts[key] = context

            return contexts

        except Exception as e:
            logger.error(f"Error loading state contexts from file: {e}")
            return {}

    async def _save_contexts(self, contexts: Dict[str, StateContext]) -> None:
        """Save contexts to file."""
        try:
            import os

            os.makedirs(os.path.dirname(self.filePath), exist_ok=True)

            # Convert contexts to serializable format
            data = {}
            for key, context in contexts.items():
                data[key] = {
                    "userId": context.userId,
                    "chatId": context.chatId,
                    "currentState": context.currentState.name if context.currentState else None,
                    "stateData": context.stateData,
                    "history": context.history,
                    "createdAt": context.createdAt,
                    "updatedAt": context.updatedAt,
                }

            with open(self.filePath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Error saving state contexts to file: {e}")

    async def get_context(self, key: str) -> Optional[StateContext]:
        """Get a state context by key."""
        async with self._lock:
            contexts = await self._load_contexts()
            return contexts.get(key)

    async def set_context(self, key: str, context: StateContext) -> None:
        """Set a state context."""
        async with self._lock:
            contexts = await self._load_contexts()
            contexts[key] = context
            await self._save_contexts(contexts)

    async def delete_context(self, key: str) -> bool:
        """Delete a state context."""
        async with self._lock:
            contexts = await self._load_contexts()
            if key in contexts:
                del contexts[key]
                await self._save_contexts(contexts)
                return True
            return False

    async def get_all_contexts(self) -> Dict[str, StateContext]:
        """Get all state contexts."""
        async with self._lock:
            return await self._load_contexts()

    async def clear_all(self) -> None:
        """Clear all state contexts."""
        async with self._lock:
            await self._save_contexts({})


class StateManager:
    """Manages state contexts and transitions for users and chats.

    Provides a high-level interface for managing conversation state,
    including state transitions, data storage, and context management.
    """

    def __init__(self, storage: Optional[StateStorage] = None):
        """Initialize the state manager.

        Args:
            storage: State storage implementation (uses MemoryStateStorage if None)
        """
        self.storage = storage or MemoryStateStorage()
        self.states: Dict[str, State] = {}
        self.defaultState: Optional[State] = None

    def add_state(self, state: State) -> None:
        """Add a state to the manager.

        Args:
            state: State to add
        """
        self.states[state.name] = state
        logger.debug(f"Added state: {state.name}")

    def get_state(self, name: str) -> Optional[State]:
        """Get a state by name.

        Args:
            name: State name

        Returns:
            State or None if not found
        """
        return self.states.get(name)

    def set_default_state(self, state: State) -> None:
        """Set the default state.

        Args:
            state: Default state
        """
        self.defaultState = state
        self.add_state(state)
        logger.debug(f"Set default state: {state.name}")

    async def get_context(self, userId: Optional[int] = None, chatId: Optional[int] = None) -> Optional[StateContext]:
        """Get a state context for a user/chat combination.

        Args:
            user_id: User ID (optional)
            chat_id: Chat ID (optional)

        Returns:
            State context or None if not found
        """
        context = StateContext(userId=userId, chatId=chatId)
        key = context.get_context_key()
        return await self.storage.get_context(key)

    async def create_context(
        self,
        userId: Optional[int] = None,
        chatId: Optional[int] = None,
        initialState: Optional[State] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> StateContext:
        """Create a new state context.

        Args:
            user_id: User ID (optional)
            chat_id: Chat ID (optional)
            initial_state: Initial state (uses default if None)
            data: Initial state data (optional)

        Returns:
            Created state context
        """
        state = initialState or self.defaultState
        if not state:
            raise ValueError("No initial state specified and no default state set")

        context = StateContext(
            userId=userId,
            chatId=chatId,
            currentState=state,
            stateData=data or {},
        )

        key = context.get_context_key()
        await self.storage.set_context(key, context)

        logger.debug(f"Created context for {key} in state {state.name}")
        return context

    async def update_context(
        self,
        user_id: Optional[int] = None,
        chat_id: Optional[int] = None,
        new_state: Optional[State] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Optional[StateContext]:
        """Update an existing state context.

        Args:
            user_id: User ID (optional)
            chat_id: Chat ID (optional)
            new_state: New state to transition to (optional)
            data: Data to update (optional)

        Returns:
            Updated context or None if not found
        """
        context = await self.get_context(user_id, chat_id)
        if not context:
            return None

        if new_state:
            context.update_state(new_state, data)
        elif data:
            context.stateData.update(data)

        key = context.get_context_key()
        await self.storage.set_context(key, context)

        logger.debug(f"Updated context for {key}")
        return context

    async def transition_state(
        self,
        trigger: str,
        user_id: Optional[int] = None,
        chat_id: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Transition to a new state based on a trigger.

        Args:
            trigger: Trigger for the transition
            user_id: User ID (optional)
            chat_id: Chat ID (optional)
            data: Data to store with the new state (optional)

        Returns:
            True if transition was successful
        """
        context = await self.get_context(user_id, chat_id)
        if not context or not context.currentState:
            return False

        target_state = context.currentState.get_transition(trigger)
        if not target_state:
            logger.debug(f"No transition found for trigger '{trigger}' from state {context.currentState.name}")
            return False

        await self.update_context(user_id, chat_id, target_state, data)
        logger.debug(f"Transitioned from {context.currentState.name} to {target_state.name}")
        return True

    async def delete_context(self, user_id: Optional[int] = None, chat_id: Optional[int] = None) -> bool:
        """Delete a state context.

        Args:
            user_id: User ID (optional)
            chat_id: Chat ID (optional)

        Returns:
            True if context was deleted
        """
        context = StateContext(userId=user_id, chatId=chat_id)
        key = context.get_context_key()
        result = await self.storage.delete_context(key)

        if result:
            logger.debug(f"Deleted context for {key}")

        return result

    async def get_all_contexts(self) -> Dict[str, StateContext]:
        """Get all state contexts.

        Returns:
            Dictionary of all contexts
        """
        return await self.storage.get_all_contexts()

    async def clear_all_contexts(self) -> None:
        """Clear all state contexts."""
        await self.storage.clear_all()
        logger.debug("Cleared all state contexts")

    def get_current_state(self, user_id: Optional[int] = None, chat_id: Optional[int] = None) -> Optional[State]:
        """Get the current state for a user/chat combination.

        Args:
            user_id: User ID (optional)
            chat_id: Chat ID (optional)

        Returns:
            Current state or None if not found
        """
        # This is a synchronous version for convenience
        # In async context, use get_context instead
        context = asyncio.create_task(self.get_context(user_id, chat_id))
        try:
            result = context.result()
            return result.currentState if result else None
        except Exception as e:
            logger.error(f"Error getting current state: {e}")
            return None

    async def set_state_data(
        self,
        key: str,
        value: Any,
        userId: Optional[int] = None,
        chatId: Optional[int] = None,
    ) -> bool:
        """Set data in the current state.

        Args:
            key: Data key
            value: Data value
            user_id: User ID (optional)
            chat_id: Chat ID (optional)

        Returns:
            True if data was set
        """
        context = await self.get_context(userId, chatId)
        if not context:
            return False

        context.set_data(key, value)
        context_key = context.get_context_key()
        await self.storage.set_context(context_key, context)
        return True

    async def get_state_data(
        self,
        key: str,
        default: Any = None,
        user_id: Optional[int] = None,
        chat_id: Optional[int] = None,
    ) -> Any:
        """Get data from the current state.

        Args:
            key: Data key
            default: Default value if key not found
            user_id: User ID (optional)
            chat_id: Chat ID (optional)

        Returns:
            Data value or default
        """
        context = await self.get_context(user_id, chat_id)
        if not context:
            return default

        return context.get_data(key, default)


# Convenience functions for creating common states


def create_state(name: str, data: Optional[Dict[str, Any]] = None) -> State:
    """Create a new state."""
    return State(name, data)


def create_fsm(states: List[State], transitions: List[tuple]) -> Dict[str, State]:
    """Create a finite state machine.

    Args:
        states: List of states
        transitions: List of (from_state, trigger, to_state) tuples

    Returns:
        Dictionary of states with transitions configured
    """
    state_dict = {state.name: state for state in states}

    for from_name, trigger, to_name in transitions:
        from_state = state_dict.get(from_name)
        to_state = state_dict.get(to_name)

        if from_state and to_state:
            from_state.add_transition(trigger, to_state)

    return state_dict
