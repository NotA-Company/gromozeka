# Comprehensive Testing Plan for Gromozeka Bot

**Created:** 2025-10-27  
**Status:** Draft  
**Priority:** High  
**Complexity:** Very Complex  

## Executive Summary

This document provides a comprehensive testing strategy for the Gromozeka Telegram bot project. The plan identifies 45+ testable components across 6 major categories, prioritizes them by criticality and complexity, and defines specific testing strategies for each component.

**Current Test Coverage:**
- ✅ Cache Service (comprehensive unit tests)
- ✅ Bayes Spam Filter (unit and integration tests)
- ✅ OpenWeatherMap Client (unit tests with mocks)
- ✅ Markdown Parser (extensive test suite)
- ✅ Command Handler Decorators (unit tests)
- ⚠️ Database Migrations (basic tests exist)
- ❌ Bot Handlers (minimal coverage)
- ❌ Services (Queue, LLM - no tests)
- ❌ Database Operations (no direct tests)

**Testing Goals:**
1. Achieve 80%+ code coverage across critical components
2. Ensure all bot handlers have integration tests
3. Validate database operations with fixtures
4. Test service layer components in isolation
5. Create end-to-end test scenarios for key workflows

---

## Table of Contents

1. [Testing Categories](#testing-categories)
2. [Priority Matrix](#priority-matrix)
3. [Component Testing Plans](#component-testing-plans)
4. [Testing Infrastructure](#testing-infrastructure)
5. [Implementation Roadmap](#implementation-roadmap)
6. [Dependencies and Prerequisites](#dependencies-and-prerequisites)

---

## Testing Categories

### Category 1: Core Services (Highest Priority)
Critical infrastructure components that other systems depend on.

### Category 2: Bot Handlers (High Priority)
User-facing functionality that directly impacts bot behavior.

### Category 3: Database Layer (High Priority)
Data persistence and retrieval operations.

### Category 4: Library Components (Medium Priority)
Reusable utilities and integrations.

### Category 5: Models and Types (Low Priority)
Data structures and type definitions.

### Category 6: Configuration (Low Priority)
Configuration management and validation.

---

## Priority Matrix

| Priority | Component Count | Estimated Effort | Dependencies |
|----------|----------------|------------------|--------------|
| **Critical** | 8 | 40-60 hours | None |
| **High** | 15 | 60-80 hours | Critical components |
| **Medium** | 12 | 30-40 hours | High priority components |
| **Low** | 10 | 15-20 hours | All above |

**Total Estimated Effort:** 145-200 hours

---

## Component Testing Plans

### 1. Core Services

#### 1.1 Queue Service
**File:** [`internal/services/queue/service.py`](internal/services/queue/service.py:48)  
**Priority:** Critical  
**Complexity:** Complex  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Singleton pattern validation
  - Background task queue operations (add, process, age-based triggering)
  - Delayed task queue operations (priority ordering, scheduling)
  - Task handler registration and execution
  - Graceful shutdown sequence
  
- **Integration Tests:**
  - Database persistence of delayed tasks
  - Task restoration after restart
  - Concurrent task execution
  - Error handling and recovery
  
- **Mocks Needed:**
  - DatabaseWrapper for task persistence
  - asyncio.Task objects for background tasks
  - Time-based operations (use freezegun or similar)

**Test Scenarios:**
1. Add multiple background tasks and verify FIFO processing
2. Add delayed tasks with different timestamps, verify priority execution
3. Test queue overflow handling (MAX_QUEUE_LENGTH)
4. Test age-based processing trigger (MAX_QUEUE_AGE)
5. Test graceful shutdown with pending tasks
6. Test task restoration from database on startup
7. Test handler registration and execution
8. Test error handling in task execution

**Estimated Effort:** 12-16 hours

---

#### 1.2 LLM Service
**File:** [`internal/services/llm/service.py`](internal/services/llm/service.py:23)  
**Priority:** Critical  
**Complexity:** Complex  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Singleton pattern validation
  - Tool registration and retrieval
  - Tool handler execution
  - Multi-turn conversation handling
  
- **Integration Tests:**
  - LLM model interaction with tool calls
  - Fallback model switching
  - Callback invocation during tool calls
  - Error handling in tool execution

- **Mocks Needed:**
  - AbstractModel for LLM interactions
  - Tool handlers (async functions)
  - Callback functions

**Test Scenarios:**
1. Register multiple tools and verify retrieval
2. Generate text without tools
3. Generate text with tool calls (single turn)
4. Generate text with multiple tool calls (multi-turn)
5. Test fallback model activation on primary failure
6. Test callback invocation with tool calls
7. Test error handling in tool execution
8. Test tool parameter validation

**Estimated Effort:** 10-14 hours

---

#### 1.3 Cache Service
**File:** [`internal/services/cache/service.py`](internal/services/cache/service.py)  
**Priority:** Critical  
**Complexity:** Moderate  
**Current Coverage:** ~90% ✅  

**Status:** Comprehensive tests already exist in [`internal/services/cache/test_cache_service.py`](internal/services/cache/test_cache_service.py)

**Additional Testing Needed:**
- Performance tests for large cache sizes
- Stress tests for concurrent access patterns
- Edge cases for TTL expiration
- Memory usage profiling

**Estimated Effort:** 4-6 hours (enhancements only)

---

### 2. Bot Handlers

#### 2.1 Base Handler
**File:** [`internal/bot/handlers/base.py`](internal/bot/handlers/base.py:89)  
**Priority:** Critical  
**Complexity:** Very Complex  
**Current Coverage:** ~5%  

**Testing Strategy:**
- **Unit Tests:**
  - Chat settings management (get, set, unset)
  - User data management (get, set, unset, clear)
  - Admin permission checking
  - Message mention detection
  - Chat/topic info updates
  
- **Integration Tests:**
  - Message sending with MarkdownV2 formatting
  - Photo sending with captions
  - Media processing (images, stickers)
  - Message saving to database
  - LLM image parsing workflow

- **Mocks Needed:**
  - Telegram Update and Message objects
  - ExtBot for bot operations
  - DatabaseWrapper for persistence
  - LLMManager for AI operations
  - ConfigManager for settings

**Test Scenarios:**
1. Get/set/unset chat settings with defaults
2. Get/set/unset user data with append mode
3. Check admin permissions (bot owners, chat admins)
4. Detect bot mentions (username, custom nicknames)
5. Send text message with MarkdownV2
6. Send photo with caption
7. Process image with LLM parsing
8. Process sticker metadata
9. Save message to database with threading
10. Update chat/topic info on changes

**Estimated Effort:** 16-20 hours

---

#### 2.2 Common Handler
**File:** [`internal/bot/handlers/common.py`](internal/bot/handlers/common.py:48)  
**Priority:** High  
**Complexity:** Moderate  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Delayed task handlers (send message, delete message)
  - LLM tool handlers (get URL content, get datetime)
  - Command parsing and validation
  
- **Integration Tests:**
  - `/start` command flow
  - `/remind` command with time parsing
  - `/list_chats` command with database query
  - Delayed message sending workflow

- **Mocks Needed:**
  - QueueService for delayed tasks
  - LLMService for tool registration
  - HTTP client for URL fetching

**Test Scenarios:**
1. Handle `/start` command in private chat
2. Handle `/start` command in group chat
3. Parse remind time (relative and absolute)
4. Schedule delayed message
5. Execute delayed message sending
6. Execute delayed message deletion
7. Fetch URL content via LLM tool
8. Get current datetime via LLM tool
9. List user's chats

**Estimated Effort:** 8-10 hours

---

#### 2.3 LLM Message Handler
**File:** [`internal/bot/handlers/llm_messages.py`](internal/bot/handlers/llm_messages.py:52)  
**Priority:** High  
**Complexity:** Very Complex  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Message context building
  - LLM prompt construction
  - Response formatting
  - Tool call handling
  
- **Integration Tests:**
  - Reply to bot message
  - Mention bot in group
  - Private message to bot
  - Random message probability
  - Multi-turn conversations
  - Tool usage in conversations

- **Mocks Needed:**
  - LLMService for text generation
  - Message history from database
  - Chat settings for model selection

**Test Scenarios:**
1. Handle reply to bot message
2. Handle bot mention in group
3. Handle private message
4. Handle random message (probability-based)
5. Build conversation context from history
6. Generate LLM response with tools
7. Handle intermediate tool call messages
8. Format and send LLM response
9. Handle LLM errors gracefully

**Estimated Effort:** 14-18 hours

---

#### 2.4 Spam Handler
**File:** [`internal/bot/handlers/spam.py`](internal/bot/handlers/spam.py:52)  
**Priority:** High  
**Complexity:** Complex  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Spam detection logic
  - Bayes filter integration
  - User banning/unbanning
  - Spam statistics
  
- **Integration Tests:**
  - Message spam checking workflow
  - Mark message as spam
  - Mark message as ham
  - Train filter from history
  - Reset filter
  - Get filter statistics

- **Mocks Needed:**
  - NaiveBayesFilter for spam detection
  - Telegram bot for user banning
  - Database for spam storage

**Test Scenarios:**
1. Check message for spam (below threshold)
2. Check message for spam (above threshold)
3. Mark message as spam and ban user
4. Mark message as ham
5. Train Bayes filter from chat history
6. Reset Bayes filter for chat
7. Get spam statistics
8. Handle `/spam` command
9. Handle `/pretrain_bayes` command
10. Handle `/learn_spam` and `/learn_ham` commands
11. Handle `/get_spam_score` command
12. Handle `/unban` command

**Estimated Effort:** 12-16 hours

---

#### 2.5 Summarization Handler
**File:** [`internal/bot/handlers/summarization.py`](internal/bot/handlers/summarization.py:49)  
**Priority:** High  
**Complexity:** Very Complex  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Message batch processing
  - Summary generation logic
  - User state management
  - Button callback handling
  
- **Integration Tests:**
  - `/summary` command flow
  - Interactive summarization workflow
  - Message filtering and batching
  - LLM summarization with context
  - Cache integration

- **Mocks Needed:**
  - LLMService for summary generation
  - Database for message retrieval
  - Cache for summary storage
  - User state management

**Test Scenarios:**
1. Handle `/summary` command with default parameters
2. Handle `/summary` with custom time range
3. Handle `/summary` with custom message count
4. Interactive summarization: select time range
5. Interactive summarization: select message count
6. Interactive summarization: confirm and generate
7. Batch message processing
8. Generate summary with LLM
9. Cache summary results
10. Handle button callbacks for summarization

**Estimated Effort:** 16-20 hours

---

#### 2.6 Weather Handler
**File:** [`internal/bot/handlers/weather.py`](internal/bot/handlers/weather.py:55)  
**Priority:** Medium  
**Complexity:** Moderate  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Weather data formatting
  - LLM tool handlers (by city, by coords)
  - Command parsing
  
- **Integration Tests:**
  - `/weather` command with city name
  - `/weather` command with coordinates
  - LLM tool integration
  - Weather client integration
  - Cache integration

- **Mocks Needed:**
  - OpenWeatherMap client
  - Weather cache
  - LLMService for tool registration

**Test Scenarios:**
1. Get weather by city name
2. Get weather by coordinates
3. Format weather data for display
4. Handle `/weather` command with city
5. Handle `/weather` command without arguments
6. LLM tool: get weather by city
7. LLM tool: get weather by coords
8. Handle weather API errors
9. Use cached weather data

**Estimated Effort:** 6-8 hours

---

#### 2.7 Media Handler
**File:** [`internal/bot/handlers/media.py`](internal/bot/handlers/media.py:50)  
**Priority:** Medium  
**Complexity:** Complex  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Image generation tool handler
  - Media message processing
  - Command parsing
  
- **Integration Tests:**
  - `/analyze` command for image analysis
  - `/draw` command for image generation
  - Media processing workflow
  - LLM integration for image tasks

- **Mocks Needed:**
  - LLMService for image generation
  - Image generation API client
  - Media processing from base handler

**Test Scenarios:**
1. Handle `/analyze` command with image
2. Handle `/analyze` command without image
3. Handle `/draw` command with prompt
4. Generate image via LLM tool
5. Send generated image
6. Handle image generation errors
7. Process media messages

**Estimated Effort:** 8-10 hours

---

#### 2.8 Configure Handler
**File:** [`internal/bot/handlers/configure.py`](internal/bot/handlers/configure.py:44)  
**Priority:** Medium  
**Complexity:** Complex  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Configuration state management
  - Button callback parsing
  - Setting validation
  
- **Integration Tests:**
  - `/configure` command flow
  - Interactive configuration workflow
  - Setting updates via buttons
  - Multi-step configuration

- **Mocks Needed:**
  - User state management
  - Chat settings management
  - Button callback handling

**Test Scenarios:**
1. Handle `/configure` command
2. Display configuration menu
3. Handle setting selection
4. Handle value input
5. Validate and save settings
6. Handle button callbacks
7. Multi-step configuration flow
8. Cancel configuration
9. Admin-only settings protection

**Estimated Effort:** 10-12 hours

---

#### 2.9 User Data Handler
**File:** [`internal/bot/handlers/user_data.py`](internal/bot/handlers/user_data.py:45)  
**Priority:** Low  
**Complexity:** Simple  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - LLM tool for setting user data
  - Command handlers
  
- **Integration Tests:**
  - `/get_my_data` command
  - `/delete_my_data` command
  - `/clear_my_data` command
  - LLM tool integration

- **Mocks Needed:**
  - User data storage
  - LLMService for tool registration

**Test Scenarios:**
1. Get user data
2. Delete specific user data key
3. Clear all user data
4. LLM tool: set user data
5. Handle empty user data

**Estimated Effort:** 4-6 hours

---

#### 2.10 Dev Commands Handler
**File:** [`internal/bot/handlers/dev_commands.py`](internal/bot/handlers/dev_commands.py:43)  
**Priority:** Low  
**Complexity:** Simple  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Command handlers
  - Admin permission checks
  
- **Integration Tests:**
  - `/echo` command
  - `/models` command
  - `/settings` command
  - `/set` and `/unset` commands
  - `/test` command

- **Mocks Needed:**
  - Admin permission checks
  - LLM manager for model listing
  - Chat settings

**Test Scenarios:**
1. Echo command with text
2. List available models
3. Display chat settings
4. Set chat setting
5. Unset chat setting
6. Run test command
7. Admin-only command protection

**Estimated Effort:** 4-6 hours

---

#### 2.11 Help Handler
**File:** [`internal/bot/handlers/help_command.py`](internal/bot/handlers/help_command.py:37)  
**Priority:** Low  
**Complexity:** Simple  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Command handler discovery
  - Help message formatting
  
- **Integration Tests:**
  - `/help` command in private chat
  - `/help` command in group chat
  - Category-based command filtering

- **Mocks Needed:**
  - Command handlers from other handlers

**Test Scenarios:**
1. Generate help message for private chat
2. Generate help message for group chat
3. Filter commands by category
4. Format command descriptions

**Estimated Effort:** 2-4 hours

---

#### 2.12 Message Preprocessor Handler
**File:** [`internal/bot/handlers/message_preprocessor.py`](internal/bot/handlers/message_preprocessor.py:28)  
**Priority:** Low  
**Complexity:** Simple  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Message preprocessing logic
  
- **Integration Tests:**
  - Message handler flow

- **Mocks Needed:**
  - Message objects

**Test Scenarios:**
1. Preprocess text message
2. Preprocess media message
3. Skip processing for certain message types

**Estimated Effort:** 2-3 hours

---

#### 2.13 Handlers Manager
**File:** [`internal/bot/handlers/manager.py`](internal/bot/handlers/manager.py:35)  
**Priority:** High  
**Complexity:** Moderate  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Handler registration
  - Command handler discovery
  - Handler chain execution
  
- **Integration Tests:**
  - Message routing to handlers
  - Button callback routing
  - Error handling
  - Handler result status processing

- **Mocks Needed:**
  - All handler classes
  - Telegram Update objects

**Test Scenarios:**
1. Register handlers
2. Discover command handlers
3. Route message to appropriate handler
4. Route button callback to handler
5. Handle errors in handlers
6. Process handler result statuses (FINAL, NEXT, SKIPPED, ERROR)
7. Execute handler chain

**Estimated Effort:** 8-10 hours

---

### 3. Database Layer

#### 3.1 Database Wrapper
**File:** [`internal/database/wrapper.py`](internal/database/wrapper.py:81)  
**Priority:** Critical  
**Complexity:** Very Complex  
**Current Coverage:** ~10% (via integration tests)  

**Testing Strategy:**
- **Unit Tests:**
  - Connection management
  - Cursor context manager
  - Data validation methods
  - CRUD operations for each table
  
- **Integration Tests:**
  - Transaction handling
  - Concurrent access
  - Migration integration
  - Data integrity constraints

- **Test Fixtures:**
  - In-memory SQLite database
  - Sample data for each table
  - Migration test scenarios

**Test Scenarios:**
1. Initialize database with migrations
2. Save and retrieve chat messages
3. Update chat user information
4. Manage chat settings (set, get, unset, clear)
5. Store and retrieve user data
6. Manage media attachments
7. Handle delayed tasks
8. Store spam/ham messages
9. Cache operations (get, set, unset)
10. Transaction rollback on errors
11. Concurrent access handling
12. Data validation for each model type

**Estimated Effort:** 20-24 hours

---

#### 3.2 Bayes Storage
**File:** [`internal/database/bayes_storage.py`](internal/database/bayes_storage.py:18)  
**Priority:** High  
**Complexity:** Moderate  
**Current Coverage:** ~60% (via Bayes filter tests)  

**Testing Strategy:**
- **Unit Tests:**
  - Token statistics operations
  - Class statistics operations
  - Batch operations
  - Cleanup operations
  
- **Integration Tests:**
  - Database integration
  - Per-chat isolation
  - Performance with large datasets

- **Test Fixtures:**
  - Sample token data
  - Sample class statistics

**Test Scenarios:**
1. Get token statistics
2. Update token statistics
3. Get class statistics
4. Update class statistics
5. Batch update tokens
6. Get top spam/ham tokens
7. Cleanup rare tokens
8. Clear statistics
9. Get model statistics
10. Per-chat isolation

**Estimated Effort:** 6-8 hours

---

#### 3.3 OpenWeatherMap Cache
**File:** [`internal/database/openweathermap_cache.py`](internal/database/openweathermap_cache.py:22)  
**Priority:** Medium  
**Complexity:** Simple  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Cache get/set operations
  - TTL expiration
  - Data serialization
  
- **Integration Tests:**
  - Database integration
  - Cache hit/miss scenarios

- **Test Fixtures:**
  - Sample weather data
  - Sample geocoding data

**Test Scenarios:**
1. Set and get weather data
2. Set and get geocoding data
3. Handle expired cache entries
4. Handle missing cache entries
5. Serialize/deserialize weather data

**Estimated Effort:** 3-4 hours

---

#### 3.4 Database Manager
**File:** [`internal/database/manager.py`](internal/database/manager.py:14)  
**Priority:** Low  
**Complexity:** Simple  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Database initialization
  - Configuration handling
  
- **Integration Tests:**
  - Database wrapper creation
  - Migration execution

**Test Scenarios:**
1. Initialize database from config
2. Handle database path configuration
3. Create database wrapper

**Estimated Effort:** 2-3 hours

---

#### 3.5 Database Migrations
**Files:** [`internal/database/migrations/`](internal/database/migrations/)  
**Priority:** High  
**Complexity:** Moderate  
**Current Coverage:** ~40% ✅  

**Status:** Basic tests exist in [`internal/database/migrations/test_migrations.py`](internal/database/migrations/test_migrations.py)

**Additional Testing Needed:**
- Test each migration individually
- Test migration rollback scenarios
- Test migration failure recovery
- Test auto-discovery mechanism
- Test migration ordering
- Test backward compatibility

**Estimated Effort:** 8-10 hours

---

### 4. Library Components

#### 4.1 AI Providers
**Files:** [`lib/ai/providers/`](lib/ai/providers/)  
**Priority:** High  
**Complexity:** Complex  
**Current Coverage:** 0%  

**Components:**
- BasicOpenAIProvider
- OpenRouterProvider
- YCOpenAIProvider
- YCSDKProvider

**Testing Strategy:**
- **Unit Tests:**
  - Provider initialization
  - Model configuration
  - Request formatting
  - Response parsing
  - Error handling
  
- **Integration Tests:**
  - API communication (with mocks)
  - Fallback handling
  - Tool call support
  - Streaming support

- **Mocks Needed:**
  - HTTP client for API calls
  - API responses

**Test Scenarios (per provider):**
1. Initialize provider with config
2. Generate text without tools
3. Generate text with tools
4. Handle tool calls
5. Parse API responses
6. Handle API errors
7. Test fallback mechanism
8. Test streaming responses

**Estimated Effort:** 16-20 hours (all providers)

---

#### 4.2 AI Manager
**File:** [`lib/ai/manager.py`](lib/ai/manager.py)  
**Priority:** High  
**Complexity:** Moderate  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Provider registration
  - Model lookup
  - Configuration management
  
- **Integration Tests:**
  - Provider initialization
  - Model selection
  - Multi-provider scenarios

- **Mocks Needed:**
  - Provider instances
  - Configuration data

**Test Scenarios:**
1. Register providers
2. Get model by name
3. List available models
4. Handle missing models
5. Initialize from configuration

**Estimated Effort:** 6-8 hours

---

#### 4.3 Markdown Parser
**Files:** [`lib/markdown/`](lib/markdown/)  
**Priority:** Medium  
**Complexity:** Complex  
**Current Coverage:** ~85% ✅  

**Status:** Extensive tests exist in [`lib/markdown/test/`](lib/markdown/test/)

**Additional Testing Needed:**
- Edge cases for nested structures
- Performance tests for large documents
- Stress tests for malformed input
- Additional special character combinations

**Estimated Effort:** 4-6 hours (enhancements only)

---

#### 4.4 Spam Filter
**Files:** [`lib/spam/`](lib/spam/)  
**Priority:** High  
**Complexity:** Moderate  
**Current Coverage:** ~70% ✅  

**Status:** Good tests exist in [`lib/spam/test_bayes_filter.py`](lib/spam/test_bayes_filter.py)

**Additional Testing Needed:**
- Edge cases for tokenization
- Performance tests with large datasets
- Accuracy tests with real spam data
- Per-chat isolation validation

**Estimated Effort:** 4-6 hours (enhancements only)

---

#### 4.5 OpenWeatherMap Client
**Files:** [`lib/openweathermap/`](lib/openweathermap/)  
**Priority:** Medium  
**Complexity:** Moderate  
**Current Coverage:** ~60% ✅  

**Status:** Tests exist in [`lib/openweathermap/test_weather_client.py`](lib/openweathermap/test_weather_client.py) and [`lib/openweathermap/test_dict_cache.py`](lib/openweathermap/test_dict_cache.py)

**Additional Testing Needed:**
- Error handling for API failures
- Cache integration tests
- Rate limiting tests
- Data validation tests

**Estimated Effort:** 4-6 hours (enhancements only)

---

#### 4.6 Utilities
**File:** [`lib/utils.py`](lib/utils.py)  
**Priority:** Low  
**Complexity:** Simple  
**Current Coverage:** ~20%  

**Testing Strategy:**
- **Unit Tests:**
  - JSON serialization helpers
  - Time/date utilities
  - String manipulation
  - Data validation

**Test Scenarios:**
1. JSON dumps with custom types
2. Age calculation
3. String utilities
4. Data validation helpers

**Estimated Effort:** 3-4 hours

---

#### 4.7 Logging Utilities
**File:** [`lib/logging_utils.py`](lib/logging_utils.py)  
**Priority:** Low  
**Complexity:** Simple  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Logger configuration
  - Log formatting
  - Log level management

**Test Scenarios:**
1. Configure logger
2. Format log messages
3. Set log levels
4. Handle log rotation

**Estimated Effort:** 2-3 hours

---

### 5. Models and Types

#### 5.1 Bot Models
**Files:** [`internal/bot/models/`](internal/bot/models/)  
**Priority:** Low  
**Complexity:** Simple  
**Current Coverage:** ~30% (via handler tests)  

**Components:**
- ChatSettings
- CommandHandlers
- DelayedTasks
- EnsuredMessage
- Enums
- Media
- UserMetadata

**Testing Strategy:**
- **Unit Tests:**
  - Model creation and validation
  - Type conversions
  - Enum values
  - Data serialization

**Test Scenarios:**
1. Create and validate each model type
2. Test type conversions (ChatSettingsValue)
3. Test enum values
4. Test EnsuredMessage creation from Telegram Message
5. Test media processing info
6. Test user metadata operations

**Estimated Effort:** 6-8 hours

---

#### 5.2 Database Models
**File:** [`internal/database/models.py`](internal/database/models.py)  
**Priority:** Low  
**Complexity:** Simple  
**Current Coverage:** ~40% (via database tests)  

**Testing Strategy:**
- **Unit Tests:**
  - TypedDict validation
  - Enum values
  - Model creation

**Test Scenarios:**
1. Validate each TypedDict structure
2. Test enum values
3. Test model creation and validation

**Estimated Effort:** 3-4 hours

---

#### 5.3 Service Types
**Files:** [`internal/services/*/types.py`](internal/services/)  
**Priority:** Low  
**Complexity:** Simple  
**Current Coverage:** ~20%  

**Testing Strategy:**
- **Unit Tests:**
  - Type definitions
  - Enum values
  - Type aliases

**Test Scenarios:**
1. Validate type definitions
2. Test enum values
3. Test type aliases

**Estimated Effort:** 2-3 hours

---

### 6. Configuration

#### 6.1 Config Manager
**File:** [`internal/config/manager.py`](internal/config/manager.py)  
**Priority:** Medium  
**Complexity:** Moderate  
**Current Coverage:** 0%  

**Testing Strategy:**
- **Unit Tests:**
  - Configuration loading
  - Configuration merging
  - Configuration validation
  - Default values
  
- **Integration Tests:**
  - TOML file parsing
  - Multi-file configuration
  - Environment-specific configs

- **Test Fixtures:**
  - Sample TOML files
  - Invalid configuration files

**Test Scenarios:**
1. Load configuration from TOML
2. Merge multiple configuration files
3. Apply default values
4. Validate configuration structure
5. Handle missing configuration files
6. Handle invalid TOML syntax
7. Get bot configuration
8. Get provider configuration
9. Get model configuration

**Estimated Effort:** 6-8 hours

---

## Testing Infrastructure

### Test Organization

```
tests/
├── unit/                          # Unit tests
│   ├── services/
│   │   ├── test_queue_service.py
│   │   ├── test_llm_service.py
│   │   └── test_cache_service.py (existing)
│   ├── handlers/
│   │   ├── test_base_handler.py
│   │   ├── test_common_handler.py
│   │   ├── test_llm_handler.py
│   │   ├── test_spam_handler.py
│   │   └── ...
│   ├── database/
│   │   ├── test_wrapper.py
│   │   ├── test_bayes_storage.py
│   │   └── test_migrations.py (existing)
│   ├── lib/
│   │   ├── test_ai_providers.py
│   │   ├── test_ai_manager.py
│   │   └── test_utils.py
│   └── config/
│       └── test_config_manager.py
│
├── integration/                   # Integration tests
│   ├── test_bot_workflows.py
│   ├── test_database_operations.py
│   ├── test_llm_integration.py
│   └── test_spam_detection.py
│
├── e2e/                          # End-to-end tests
│   ├── test_message_flow.py
│   ├── test_command_execution.py
│   └── test_summarization_flow.py
│
├── fixtures/                     # Test fixtures
│   ├── database.py
│   ├── messages.py
│   ├── users.py
│   └── config.py
│
└
└── mocks/                        # Mock objects
    ├── telegram_mocks.py
    ├── llm_mocks.py
    └── database_mocks.py
```

### Test Fixtures

**Database Fixtures:**
```python
# tests/fixtures/database.py
@pytest.fixture
def in_memory_db():
    """Provide in-memory SQLite database for testing"""
    db = DatabaseWrapper(":memory:")
    yield db
    db.close()

@pytest.fixture
def populated_db(in_memory_db):
    """Provide database with sample data"""
    # Add sample chats, users, messages
    return in_memory_db
```

**Message Fixtures:**
```python
# tests/fixtures/messages.py
@pytest.fixture
def sample_text_message():
    """Create sample text message"""
    return Mock(spec=Message)

@pytest.fixture
def sample_photo_message():
    """Create sample photo message"""
    return Mock(spec=Message)
```

**Mock Objects:**
```python
# tests/mocks/telegram_mocks.py
class MockBot:
    """Mock Telegram bot for testing"""
    pass

class MockUpdate:
    """Mock Telegram update for testing"""
    pass
```

### Testing Tools and Libraries

**Required Dependencies:**
- `pytest` - Test framework
- `pytest-asyncio` - Async test support
- `pytest-cov` - Coverage reporting
- `pytest-mock` - Mocking utilities
- `freezegun` - Time mocking
- `faker` - Test data generation
- `responses` - HTTP mocking

**Configuration:**
```toml
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
asyncio_mode = "auto"
addopts = [
    "--cov=internal",
    "--cov=lib",
    "--cov-report=html",
    "--cov-report=term-missing",
    "--strict-markers",
    "-v"
]
markers = [
    "unit: Unit tests",
    "integration: Integration tests",
    "e2e: End-to-end tests",
    "slow: Slow running tests",
]
```

---

## Implementation Roadmap

### Phase 1: Critical Infrastructure (Weeks 1-3)
**Goal:** Establish testing foundation and cover critical services

**Tasks:**
1. Set up testing infrastructure
   - Configure pytest and coverage tools
   - Create test fixtures and mocks
   - Set up CI/CD integration
   
2. Test Core Services (40-60 hours)
   - Queue Service (12-16 hours)
   - LLM Service (10-14 hours)
   - Cache Service enhancements (4-6 hours)
   - Database Wrapper (20-24 hours)

**Deliverables:**
- ✅ Testing infrastructure configured
- ✅ Core services at 80%+ coverage
- ✅ Database operations validated
- ✅ CI/CD pipeline running tests

---

### Phase 2: Bot Handlers - Critical Path (Weeks 4-6)
**Goal:** Test user-facing functionality and handler chain

**Tasks:**
1. Test Base Handler (16-20 hours)
   - Chat settings management
   - User data management
   - Message sending
   - Media processing

2. Test Handlers Manager (8-10 hours)
   - Handler registration
   - Message routing
   - Error handling

3. Test LLM Message Handler (14-18 hours)
   - Message context building
   - LLM integration
   - Tool usage

4. Test Spam Handler (12-16 hours)
   - Spam detection
   - Bayes filter integration
   - User management

**Deliverables:**
- ✅ Base handler at 80%+ coverage
- ✅ Handler chain validated
- ✅ LLM integration tested
- ✅ Spam detection verified

---

### Phase 3: Bot Handlers - Extended (Weeks 7-9)
**Goal:** Complete handler coverage

**Tasks:**
1. Test Summarization Handler (16-20 hours)
2. Test Common Handler (8-10 hours)
3. Test Configure Handler (10-12 hours)
4. Test Media Handler (8-10 hours)
5. Test Weather Handler (6-8 hours)
6. Test remaining handlers (12-18 hours)

**Deliverables:**
- ✅ All handlers at 70%+ coverage
- ✅ Command flows validated
- ✅ Interactive workflows tested

---

### Phase 4: Library Components (Weeks 10-11)
**Goal:** Test reusable components and integrations

**Tasks:**
1. Test AI Providers (16-20 hours)
   - All provider implementations
   - Fallback mechanisms
   - Tool support

2. Test AI Manager (6-8 hours)
3. Enhance existing tests (12-18 hours)
   - Markdown parser
   - Spam filter
   - OpenWeatherMap client

4. Test Configuration (6-8 hours)

**Deliverables:**
- ✅ AI providers at 80%+ coverage
- ✅ Library components enhanced
- ✅ Configuration validated

---

### Phase 5: Integration & E2E Tests (Weeks 12-13)
**Goal:** Validate complete workflows

**Tasks:**
1. Create integration tests (20-24 hours)
   - Bot workflows
   - Database operations
   - LLM integration
   - Spam detection

2. Create E2E tests (16-20 hours)
   - Message flow
   - Command execution
   - Summarization flow
   - Configuration flow

3. Performance testing (8-10 hours)
   - Load testing
   - Stress testing
   - Memory profiling

**Deliverables:**
- ✅ Integration tests covering key workflows
- ✅ E2E tests for critical paths
- ✅ Performance benchmarks established

---

### Phase 6: Polish & Documentation (Week 14)
**Goal:** Complete testing suite and documentation

**Tasks:**
1. Fill coverage gaps (12-16 hours)
2. Document testing patterns (4-6 hours)
3. Create testing guidelines (4-6 hours)
4. Set up automated reporting (4-6 hours)

**Deliverables:**
- ✅ 80%+ overall code coverage
- ✅ Testing documentation complete
- ✅ CI/CD fully automated
- ✅ Testing guidelines published

---

## Dependencies and Prerequisites

### Technical Prerequisites

**Development Environment:**
- Python 3.12+
- Virtual environment (venv)
- SQLite3
- libmagic 5.46+

**Testing Tools:**
- pytest 7.0+
- pytest-asyncio
- pytest-cov
- pytest-mock

**Optional Tools:**
- Docker (for isolated testing)
- Coverage.py (for detailed reports)
- Hypothesis (for property-based testing)

### Knowledge Prerequisites

**Required Knowledge:**
- Python async/await patterns
- pytest framework
- Mocking and fixtures
- Telegram Bot API
- SQLite database operations

**Recommended Knowledge:**
- LLM API integration
- Bayes classification
- MarkdownV2 formatting
- CI/CD pipelines

### Component Dependencies

**Testing Order (by dependency):**

1. **No Dependencies:**
   - Models and Types
   - Utilities
   - Configuration Manager

2. **Depends on Level 1:**
   - Database Wrapper
   - Cache Service
   - Markdown Parser

3. **Depends on Level 2:**
   - Queue Service
   - LLM Service
   - AI Providers
   - Bayes Storage

4. **Depends on Level 3:**
   - Base Handler
   - AI Manager
   - Spam Filter

5. **Depends on Level 4:**
   - All specific handlers
   - Handlers Manager

---

## Success Metrics

### Coverage Targets

| Component Category | Target Coverage | Critical Path |
|-------------------|----------------|---------------|
| Core Services | 85%+ | Yes |
| Bot Handlers | 75%+ | Yes |
| Database Layer | 80%+ | Yes |
| Library Components | 70%+ | No |
| Models & Types | 60%+ | No |
| Configuration | 70%+ | No |

**Overall Target:** 80%+ code coverage

### Quality Metrics

**Test Quality:**
- All tests must be deterministic (no flaky tests)
- Test execution time < 5 minutes for full suite
- Integration tests < 30 seconds
- Unit tests < 10 seconds

**Code Quality:**
- All tests follow project style guide
- Clear test names describing what is tested
- Proper use of fixtures and mocks
- Comprehensive docstrings

### Validation Criteria

**Phase Completion:**
- ✅ All planned tests implemented
- ✅ Coverage targets met
- ✅ All tests passing
- ✅ No critical bugs found
- ✅ Documentation updated

**Project Completion:**
- ✅ 80%+ overall coverage achieved
- ✅ All critical paths tested
- ✅ CI/CD pipeline operational
- ✅ Testing guidelines published
- ✅ Team trained on testing practices

---

## Risk Assessment

### High Risk Areas

**1. Async Testing Complexity**
- **Risk:** Async code is harder to test and debug
- **Mitigation:** Use pytest-asyncio, create async test utilities
- **Impact:** High

**2. Telegram API Mocking**
- **Risk:** Complex Telegram objects difficult to mock accurately
- **Mitigation:** Create comprehensive mock library, use real API in integration tests
- **Impact:** Medium

**3. Database State Management**
- **Risk:** Tests may interfere with each other via shared database state
- **Mitigation:** Use in-memory databases, proper fixtures, transaction rollback
- **Impact:** High

**4. LLM API Testing**
- **Risk:** External API calls are slow and may fail
- **Mitigation:** Mock LLM responses, use recorded responses for integration tests
- **Impact:** Medium

**5. Time-Dependent Tests**
- **Risk:** Tests involving time may be flaky
- **Mitigation:** Use freezegun for time mocking
- **Impact:** Low

### Medium Risk Areas

**1. Test Data Management**
- **Risk:** Maintaining realistic test data
- **Mitigation:** Use faker for data generation, maintain sample datasets

**2. Coverage Gaps**
- **Risk:** Missing edge cases
- **Mitigation:** Code review, mutation testing

**3. Performance Testing**
- **Risk:** Performance tests may be environment-dependent
- **Mitigation:** Use relative benchmarks, run in controlled environment

---

## Maintenance Plan

### Ongoing Activities

**Daily:**
- Run full test suite on commits
- Monitor test failures in CI/CD
- Fix failing tests immediately

**Weekly:**
- Review coverage reports
- Identify coverage gaps
- Update tests for new features

**Monthly:**
- Review and update test fixtures
- Refactor test code for maintainability
- Update testing documentation

**Quarterly:**
- Evaluate testing tools and practices
- Update testing guidelines
- Conduct testing retrospective

### Test Maintenance Guidelines

**When Adding New Features:**
1. Write tests before implementation (TDD)
2. Ensure new code has 80%+ coverage
3. Update integration tests if needed
4. Update documentation

**When Fixing Bugs:**
1. Write test reproducing the bug
2. Fix the bug
3. Verify test passes
4. Add regression test

**When Refactoring:**
1. Ensure tests pass before refactoring
2. Refactor code
3. Ensure tests still pass
4. Update tests if behavior changed

---

## Appendix

### A. Test Naming Conventions

**Unit Tests:**
```python
def test_<component>_<method>_<scenario>_<expected_result>():
    """Test that <component>.<method> <expected_result> when <scenario>"""
```

**Integration Tests:**
```python
def test_<workflow>_<scenario>_<expected_result>():
    """Test that <workflow> <expected_result> when <scenario>"""
```

**Examples:**
```python
def test_queue_service_add_task_adds_to_queue_successfully():
    """Test that QueueService.addBackgroundTask adds task to queue successfully"""

def test_spam_detection_workflow_bans_user_when_spam_detected():
    """Test that spam detection workflow bans user when spam is detected"""
```

### B. Mock Object Patterns

**Telegram Mocks:**
```python
from unittest.mock import Mock, AsyncMock

def create_mock_message(text="test", chat_id=123, user_id=456):
    """Create mock Telegram message"""
    message = Mock(spec=Message)
    message.text = text
    message.chat.id = chat_id
    message.from_user.id = user_id
    return message

def create_mock_bot():
    """Create mock Telegram bot"""
    bot = AsyncMock(spec=ExtBot)
    bot.username = "test_bot"
    return bot
```

**Database Mocks:**
```python
@pytest.fixture
def mock_db():
    """Create mock database wrapper"""
    db = Mock(spec=DatabaseWrapper)
    db.getChatSettings.return_value = {}
    db.getUserData.return_value = {}
    return db
```

### C. Common Test Patterns

**Testing Async Functions:**
```python
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result == expected_value
```

**Testing with Fixtures:**
```python
def test_with_database(in_memory_db):
    in_memory_db.saveChatMessage(...)
    messages = in_memory_db.getChatMessages(...)
    assert len(messages) == 1
```

**Testing Exceptions:**
```python
def test_raises_exception():
    with pytest.raises(ValueError, match="Invalid input"):
        function_that_raises()
```

**Parametrized Tests:**
```python
@pytest.mark.parametrize("input,expected", [
    ("spam", True),
    ("ham", False),
])
def test_spam_detection(input, expected):
    result = detect_spam(input)
    assert result == expected
```

### D. Coverage Report Interpretation

**Coverage Metrics:**
- **Line Coverage:** Percentage of code lines executed
- **Branch Coverage:** Percentage of code branches taken
- **Function Coverage:** Percentage of functions called

**Target Interpretation:**
- 90-100%: Excellent coverage
- 80-90%: Good coverage
- 70-80%: Acceptable coverage
- <70%: Needs improvement

**Exclusions:**
- Type checking code (`if TYPE_CHECKING:`)
- Debug code
- Unreachable code (defensive programming)
- Abstract methods

### E. CI/CD Integration

**GitHub Actions Example:**
```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov pytest-asyncio
      - name: Run tests
        run: pytest --cov --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

---

## Summary

This comprehensive testing plan provides a structured approach to achieving high test coverage across the Gromozeka bot project. The plan identifies 45+ components requiring testing, prioritizes them by criticality, and provides detailed testing strategies for each.

**Key Takeaways:**
- **Total Effort:** 145-200 hours over 14 weeks
- **Priority Focus:** Core services and bot handlers first
- **Coverage Goal:** 80%+ overall, 85%+ for critical components
- **Phased Approach:** 6 phases from infrastructure to polish

**Next Steps:**
1. Review and approve this testing plan
2. Set up testing infrastructure (Phase 1)
3. Begin implementation following the roadmap
4. Track progress against success metrics
5. Adjust plan as needed based on findings

**Success Factors:**
- Consistent test writing alongside feature development
- Regular coverage monitoring and gap filling
- Proper use of fixtures and mocks
- Comprehensive CI/CD integration
- Team commitment to testing practices

---

**Document Version:** 1.0  
**Last Updated:** 2025-10-27  
**Status:** Ready for Review  
**Next Review:** After Phase 1 completion