"""
Test fixtures package for gromozeka bot tests.

This package organizes test fixtures into logical modules:
- telegram_mocks: Mock Telegram API objects (Update, Message, User, etc.)
- database_fixtures: Database-related fixtures and test data
- service_mocks: Mock service instances (LLM, Queue, Cache)

All fixtures are also available through the main conftest.py file.
"""

from tests.fixtures.database_fixtures import (
    createSampleChatMessage,
    createSampleChatSettings,
    createSampleChatUser,
    createSampleDelayedTask,
    createSampleUserData,
)
from tests.fixtures.service_mocks import (
    createMockCacheService,
    createMockConfigManager,
    createMockLlmManager,
    createMockLlmService,
    createMockQueueService,
)
from tests.fixtures.telegram_mocks import (
    createMockBot,
    createMockCallbackQuery,
    createMockChat,
    createMockContext,
    createMockDocument,
    createMockMessage,
    createMockPhoto,
    createMockSticker,
    createMockUpdate,
    createMockUser,
)

__all__ = [
    # Telegram mocks
    "createMockBot",
    "createMockUpdate",
    "createMockMessage",
    "createMockUser",
    "createMockChat",
    "createMockContext",
    "createMockCallbackQuery",
    "createMockPhoto",
    "createMockDocument",
    "createMockSticker",
    # Database fixtures
    "createSampleChatMessage",
    "createSampleChatUser",
    "createSampleDelayedTask",
    "createSampleChatSettings",
    "createSampleUserData",
    # Service mocks
    "createMockLlmService",
    "createMockQueueService",
    "createMockCacheService",
    "createMockConfigManager",
    "createMockLlmManager",
]
