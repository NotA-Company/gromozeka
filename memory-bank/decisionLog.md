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