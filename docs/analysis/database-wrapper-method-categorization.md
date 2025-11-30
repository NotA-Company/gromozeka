# DatabaseWrapper Method Categorization Analysis

**Date Created:** 2025-11-30
**Author:** Architect Mode
**Purpose:** Categorize DatabaseWrapper methods by their chatId usage to support multi-source database architecture

## Executive Summary

This document analyzes all methods in `internal/database/wrapper.py` and categorizes them based on their chatId usage patterns. This analysis is essential for implementing multi-source database support where different chats can use different data sources.

## Method Categories

### Category 1: ChatId-Specific Methods (Require Single ChatId)

These methods operate on a specific chat and require a chatId parameter:

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

These methods operate across chats or don't require chatId:

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

These are internal methods not directly related to chat operations:

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
- **19 methods** are strictly chat-specific (Category 1)
- **14 methods** operate across chats or system-wide (Category 2)
- **15 methods** are internal/helper methods (Category 3)

### 2. Data Isolation Patterns
- Chat messages, users, and settings are strongly isolated by chatId
- Media, cache, and delayed tasks are shared resources
- System settings are global

### 3. Implementation Considerations
- Chat-specific methods (Category 1) need routing to appropriate data source
- Cross-chat methods (Category 2) may need to query multiple data sources or use a central source
- Internal methods (Category 3) need to be aware of the active data source context

## Recommendations for Multi-Source Implementation

1. **Router Pattern**: Implement a router that maps chatId to data source
2. **Connection Pool**: Maintain separate connection pools per data source
3. **Fallback Mechanism**: Default to primary data source when chatId mapping not found
4. **Cross-Source Queries**: Special handling for methods that need to query multiple sources
5. **Transaction Management**: Ensure transactions are properly scoped to single data source

## Next Steps

1. Design the data source routing architecture
2. Define configuration schema for chatId-to-source mapping
3. Implement connection management for multiple sources
4. Create abstraction layer for data source operations
5. Update each category of methods to support multi-source

---

**Note**: This analysis is based on the current implementation in `internal/database/wrapper.py` as of 2025-11-30.