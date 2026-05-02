# DatabaseWrapper Method Categorization Analysis

> **⚠️ HISTORICAL DOCUMENT**
>
> This document analyzes the **historical `DatabaseWrapper` class** that has been **replaced** by the current `Database` class with repository pattern.
>
> **Current Architecture:** The project now uses `internal/database/database.py` with a repository pattern where data access is organized through specialized repository classes in `internal/database/repositories/`.
>
> **Migration Date:** The `DatabaseWrapper` class was deprecated and replaced as part of the database architecture refactoring.
>
> **Purpose of This Document:** This analysis is preserved for historical reference and to understand the evolution of the database architecture. The method categorization insights remain valuable for understanding the data access patterns that informed the current repository design.

**Date Created:** 2025-11-30
**Status:** Historical Reference
**Author:** Architect Mode
**Original Purpose:** Categorize DatabaseWrapper methods by their chatId usage to support multi-source database architecture

## Executive Summary

This document analyzes all methods in the **historical** `internal/database/wrapper.py` (DatabaseWrapper class) and categorizes them based on their chatId usage patterns. This analysis was essential for implementing multi-source database support where different chats can use different data sources.

**Note:** The current `Database` class implements these patterns through a repository pattern with specialized repositories for different data domains.

## Method Categories

> **Historical Context:** The following categories describe methods from the `DatabaseWrapper` class. In the current architecture, these operations are handled by specialized repository classes in `internal/database/repositories/`.

### Category 1: ChatId-Specific Methods (Require Single ChatId)

These methods operated on a specific chat and required a chatId parameter in the historical `DatabaseWrapper` class:

#### Chat Message Operations
- `getChatMessageByMessageId(chatId, messageId)` - Retrieves specific message from a chat
- `getChatMessagesByUser(chatId, userId, limit)` - Gets all messages by a user in a chat

#### Chat User Management
- `updateChatUser(chatId, userId, username, fullName)` - Updates user information in a chat
- `getChatUser(chatId, userId)` - Gets user information from a chat
- `markUserIsSpammer(chatId, userId, isSpammer)` - Marks user as spammer in a chat
- `updateUserMetadata(chatId, userId, metadata)` - Updates user metadata in a chat
- `getChatUserByUsername(chatId, username)` - Gets user by username in a chat

#### User Data Management
- `addUserData(userId, chatId, key, data)` - Adds user-specific data in a chat context
- `getUserData(userId, chatId)` - Gets user-specific data in a chat context
- `deleteUserData(userId, chatId, key)` - Deletes specific user data in a chat
- `clearUserData(userId, chatId)` - Clears all user data in a chat

#### Chat Settings
- `setChatSetting(chatId, key, value)` - Sets a setting for a specific chat
- `unsetChatSetting(chatId, key)` - Removes a setting for a specific chat
- `clearChatSettings(chatId)` - Clears all settings for a specific chat
- `getChatSetting(chatId, setting)` - Gets a specific setting for a chat
- `getChatSettings(chatId)` - Gets all settings for a chat

#### Chat Information
- `getChatInfo(chatId)` - Gets chat information
- `getChatTopics(chatId)` - Gets chat topics/threads

#### Spam Management
- `deleteSpamMessagesByUserId(chatId, userId)` - Deletes spam messages by user in a chat
- `getSpamMessagesByUserId(chatId, userId)` - Gets spam messages by user in a chat

### Category 2: Cross-Chat Methods (Use Multiple or No ChatId)

These methods operated across chats or didn't require chatId in the historical `DatabaseWrapper` class:

#### User-Centric Operations
- `getUserChats(userId)` - Gets all chats a user has participated in
- `getAllGroupChats()` - Gets all group chats in the system

#### System-Wide Settings
- `setSetting(key, value)` - Sets system-wide configuration
- `getSetting(key, default)` - Gets system-wide configuration
- `getSettings()` - Gets all system-wide settings

#### Media Management
- `getMediaAttachment(mediaId)` - Gets media by ID (media is shared across chats)

#### Delayed Tasks
- `addDelayedTask(taskId, function, kwargs, delayedTS)` - Adds system-wide delayed task
- `updateDelayedTask(id, isDone)` - Updates delayed task status
- `getPendingDelayedTasks()` - Gets all pending tasks

#### Spam Detection (Global)
- `getSpamMessagesByText(text)` - Searches spam messages by text globally
- `getSpamMessages(limit)` - Gets all spam messages system-wide

#### Cache Management
- `getCacheStorage()` - Gets all cache storage entries
- `setCacheStorage(namespace, key, value)` - Sets cache storage entry
- `unsetCacheStorage(namespace, key)` - Removes cache storage entry
- `getCacheEntry(key, cacheType, ttl)` - Gets cache entry by type
- `setCacheEntry(key, data, cacheType)` - Sets cache entry
- `clearCache(cacheType)` - Clears cache by type

### Category 3: Internal/Helper Methods

These were internal methods in the `DatabaseWrapper` class not directly related to chat operations:

#### Database Management
- `__init__(dbPath, maxConnections, timeout)` - Constructor
- `_getConnection()` - Gets thread-local database connection
- `getCursor()` - Context manager for database operations
- `close()` - Closes database connections
- `_initDatabase()` - Initializes database with required tables

#### Validation Methods
- `_validateDictIsChatMessageDict(row_dict)` - Validates ChatMessageDict
- `_validateDictIsChatUserDict(row_dict)` - Validates ChatUserDict
- `_validateDictIsChatInfoDict(row_dict)` - Validates ChatInfoDict
- `_validateDictIsChatTopicDict(row_dict)` - Validates ChatTopicInfoDict
- `_validateDictIsMediaAttachmentDict(row_dict)` - Validates MediaAttachmentDict
- `_validateDictIsDelayedTaskDict(row_dict)` - Validates DelayedTaskDict
- `_validateDictIsSpamMessageDict(row_dict)` - Validates SpamMessageDict
- `_validateDictIsChatSummarizationCacheDict(row_dict)` - Validates ChatSummarizationCacheDict
- `_validateDictIsCacheDict(row_dict)` - Validates CacheDict
- `_validateDictIsCacheStorageDict(row_dict)` - Validates CacheStorageDict

## Key Insights

### 1. Clear Separation of Concerns
- **19 methods** were strictly chat-specific (Category 1)
- **14 methods** operated across chats or system-wide (Category 2)
- **15 methods** were internal/helper methods (Category 3)

### 2. Data Isolation Patterns
- Chat messages, users, and settings were strongly isolated by chatId
- Media, cache, and delayed tasks were shared resources
- System settings were global

**Current Implementation:** These patterns are now enforced through the repository pattern, where each repository handles a specific domain with clear boundaries.

### 3. Implementation Considerations (Historical)
- Chat-specific methods (Category 1) needed routing to appropriate data source
- Cross-chat methods (Category 2) may have needed to query multiple data sources or use a central source
- Internal methods (Category 3) needed to be aware of the active data source context

**Current Implementation:** The `Database` class with repository pattern provides a cleaner separation of concerns, with each repository managing its own data access logic and connection handling.

## Recommendations for Multi-Source Implementation

> **Historical Note:** These recommendations were made for the `DatabaseWrapper` class architecture. The current `Database` class with repository pattern has implemented multi-source support through a different approach.

1. **Router Pattern**: Implement a router that maps chatId to data source
2. **Connection Pool**: Maintain separate connection pools per data source
3. **Fallback Mechanism**: Default to primary data source when chatId mapping not found
4. **Cross-Source Queries**: Special handling for methods that need to query multiple sources
5. **Transaction Management**: Ensure transactions are properly scoped to single data source

**Current Implementation:** See [`internal/database/database.py`](../internal/database/database.py) for the current multi-source database implementation using provider-based architecture.

## Next Steps (Historical)

These were the planned next steps for the `DatabaseWrapper` class refactoring:

1. Design the data source routing architecture
2. Define configuration schema for chatId-to-source mapping
3. Implement connection management for multiple sources
4. Create abstraction layer for data source operations
5. Update each category of methods to support multi-source

**Status:** These steps have been completed through the migration to the `Database` class with repository pattern.

## Related Documentation

### Current Architecture
- **Database Class:** [`internal/database/database.py`](../internal/database/database.py) - Current database implementation with multi-source support
- **Repository Pattern:** [`internal/database/repositories/`](../internal/database/repositories/) - Specialized repository classes for data access
- **Database Providers:** [`internal/database/providers/`](../internal/database/providers/) - Provider abstraction for different database backends

### Historical Documentation
- **Multi-Source Configuration:** [`docs/plans/database-multi-source-configuration.md`](../plans/database-multi-source-configuration.md) - Configuration documentation for multi-source database
- **Archive Reports:** [`docs/archive/reports/`](../archive/reports/) - Various implementation reports from the migration period

### Developer Guide
- **Database Documentation:** [`docs/developer-guide.md`](../developer-guide.md) - Current database usage and best practices

---

**Note:** This analysis is based on the historical implementation in `internal/database/wrapper.py` (DatabaseWrapper class) as of 2025-11-30. The class has been replaced by the current `Database` class with repository pattern.