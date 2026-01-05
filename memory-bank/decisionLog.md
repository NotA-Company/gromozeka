# Decision Log

[2025-11-21 22:50:10] - Condensed from archive to focus on current architectural decisions

## Current Architecture Decisions

### Core Technology Stack
* **Database**: SQLite with migration system and TypedDict validation
* **Configuration**: TOML-based hierarchical configuration with environment overrides
* **Testing**: pytest with golden data framework for API testing
* **Bot Framework**: Multi-platform support (Telegram & Max Messenger) with modular handlers
* **Python Version**: 3.12+ required for StrEnum and modern Python features

### Service Architecture
* **Cache Service**: Singleton pattern with namespace-based organization
* **Queue Service**: Delayed task execution with message scheduling
* **LLM Management**: Multi-provider support (YC SDK, OpenAI-compatible, OpenRouter)
* **Rate Limiting**: Sliding window algorithm with singleton manager pattern

### Key Patterns & Best Practices
* **Naming**: camelCase for variables/methods, PascalCase for classes, UPPER_CASE for constants
* **Documentation**: Comprehensive docstrings with Args/Returns sections
* **Code Quality**: Always run `make format lint` before commits
* **Testing**: Golden data approach for deterministic API testing
* **Memory Optimization**: Use `__slots__` for data classes and models
* **Error Handling**: Proper validation at boundaries with comprehensive logging

### Database & Migration Strategy
* **TypedDict Models**: Runtime validation for all database operations
* **Migration Auto-Discovery**: Dynamic loading from versions/ directory
* **Version Tracking**: Uses settings table with migration metadata
* **Transaction Safety**: Automatic rollback on migration failures

### API Integration Standards
* **Caching Strategy**: Namespace-based with TTL and persistence options
* **Rate Limiting**: Per-service rate limiting with queue management
* **Golden Data Testing**: Record/replay for quota protection and consistency
* **Error Handling**: Proper timeout handling and retry mechanisms

### Current Best Practices
* Use TypedDict for all database row representations
* Validate all external data at boundaries
* Implement proper error handling and logging
* Create migrations using the generator script
* Document all architectural decisions
* Use golden data framework for API testing
* Follow service-oriented architecture with clean separation

[2025-11-30 16:40:00] - Multi-Source Database Architecture Decision

### Decision: Implement Router Pattern for Multi-Source Database Support

* **Architecture Choice**: Router Pattern with ConnectionManager and DataSourceRouter components
* **Initial Implementation**: Multiple SQLite database files with future extensibility for other database types
* **Routing Strategy**: Decorator-based routing for minimal code changes

### Rationale

* **Simplicity**: Keep implementation straightforward and maintainable while avoiding over-engineering
* **Backward Compatibility**: Existing single-database functionality continues working without modifications
* **Extensibility**: Clean abstraction allows easy addition of PostgreSQL, MySQL, Redis in future
* **Performance**: Connection pooling and routing cache ensure <1ms overhead per operation

### Implementation Details

* **ConnectionManager**: Manages connection pools per data source with thread-safe access
* **DataSourceRouter**: Maps chatId to appropriate data source with fallback to default
* **Method Categories**: 
  - 19 chat-specific methods use routing
  - 14 cross-chat methods handle multiple sources or use default
  - 15 internal helper methods remain unchanged
* **Configuration**: TOML-based configuration with chatId-to-source mapping
* **Feature Flag**: Gradual rollout capability with easy rollback if needed

[2025-11-30 17:01:00] - Architecture Revision: Simplified Multi-Source Database Design

### Decision: Revised to Simpler Internal Routing Architecture

* **Key Changes from Original Design**:
  - Eliminated circular dependency by keeping everything in single DatabaseWrapper class
  - Removed complex decorator pattern in favor of simple internal routing logic  
  - Added readonly data source support with write protection
  - Added optional dataSource parameter to all read methods for explicit source selection

### New Architecture Principles

* **Single Class Design**: All routing logic internal to DatabaseWrapper
* **Simple Priority Routing**: dataSource param → chatId mapping → default source
* **Readonly Protection**: Sources marked readonly reject write operations
* **Cross-Bot Communication**: Can read from external bot databases via dataSource param

### Implementation Approach

* **No External Classes**: No ConnectionManager or Router as separate classes
* **Internal Methods Only**: _getConnection() handles all routing internally
* **Backward Compatible**: Works with legacy single database mode
* **Reduced Complexity**: Estimated implementation time reduced from 3-5 days to 2-3 days

### Benefits

* No circular dependencies possible
* Simpler to understand and maintain
* Enables cross-bot data sharing
* Maintains 100% backward compatibility
* Reduces implementation complexity significantly

[2025-11-30 17:47:00] - Phase 3 Multi-Source Database Implementation Decisions

### Decision: Cross-Source Aggregation with Intelligent Deduplication

* **Deduplication Keys Strategy**: Each cross-chat method uses appropriate keys based on data semantics:
  - getUserChats(): (userId, chat_id) - User-chat relationship uniqueness
  - getAllGroupChats(): chat_id - Chat uniqueness
  - getSpamMessages(): (chat_id, message_id) - Message uniqueness within chat
  - getCacheStorage(): (namespace, key) - Cache entry uniqueness
  - getCacheEntry(): First match (no deduplication) - Performance optimization

* **Error Handling**: Continue aggregation on individual source failures with warning logs
* **Backward Compatibility**: Optional parameter design ensures zero breaking changes
* **Performance**: Set-based deduplication provides O(n) complexity for result merging

### Rationale

* **Data Integrity**: Proper deduplication prevents duplicate entries in cross-source queries
* **Resilience**: Partial failures don't break entire operations
* **Maintainability**: Clear deduplication strategy documented for future reference
* **Performance**: Efficient algorithms ensure minimal overhead for multi-source operations

[2026-01-05 23:32:00] - Media Group Completion Detection Implementation

### Decision: Time-Based Completion Detection for Telegram Media Groups

* **Problem**: Telegram sends media groups (albums) as separate messages with the same media_group_id, but doesn't indicate when all items have arrived
* **Solution**: Wait a configurable delay after the last media item is received before considering a media group complete

### Architecture Choice

* **Per-Job Configuration**: Each ResendJob has its own `mediaGroupDelaySecs` parameter (default: 5.0 seconds)
* **Database Method**: New `getMediaGroupLastUpdatedAt()` returns MAX(created_at) from media_groups table
* **Processing Logic**: _dtCronJob checks media group age before processing using utils.getAgeInSecs()

### Implementation Details

* **Files Modified**:
  - `internal/database/wrapper.py`: Added getMediaGroupLastUpdatedAt() method
  - `internal/bot/common/handlers/resender.py`: Added mediaGroupDelaySecs to ResendJob, updated _dtCronJob logic

* **Processing Flow**:
  1. For each message with media_group_id, check if already processed
  2. Get last updated timestamp using getMediaGroupLastUpdatedAt()
  3. If age < job.mediaGroupDelaySecs, mark as pending and skip
  4. If age >= job.mediaGroupDelaySecs, mark as processed and resend all media together

* **Configuration Example**:
  ```toml
  [[resender.jobs]]
  id = "telegram-to-max"
  sourceChatId = -1001234567890
  targetChatId = 9876543210
  mediaGroupDelaySecs = 5.0  # Optional, defaults to 5.0
  ```

### Rationale

* **Flexibility**: Per-job configuration allows different delays for different source chats
* **Reliability**: Time-based approach handles both fast album uploads and slow sequential uploads
* **Simplicity**: Uses existing media_groups.created_at timestamps, no new tables needed
* **Backward Compatible**: Default delay preserves existing behavior for single-media messages

### Edge Cases Handled

* **Slow uploads**: Each new media item updates the timestamp, extending the wait time
* **Fast uploads**: All media arrive quickly, processed together after delay
* **Network delays**: Late-arriving media updates timestamp, group waits appropriately
* **Single media**: Processed immediately if no media_group_id

### Testing Results

* All 1185 tests pass
* Code quality checks: make format lint passed (0 errors, 0 warnings)
* No breaking changes to existing functionality