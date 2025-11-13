# Decision Log

This file records architectural and implementation decisions.
[2025-11-02] - Condensed historical decisions for clarity

## Current Architecture Decisions

### Core Architecture
* **Database**: SQLite with migration system and TypedDict validation
* **Configuration**: TOML-based hierarchical configuration with environment overrides
* **Testing**: pytest with golden data framework for API testing
* **Bot Framework**: python-telegram-bot with modular handler architecture

### Service Architecture
* **Cache Service**: Singleton pattern with namespace-based organization at internal/services/cache/
* **Queue Service**: Delayed task execution at internal/services/queue_service/
* **LLM Management**: Multi-provider support (YC SDK, OpenAI-compatible) at lib/ai/

### Key Technical Decisions
* **Python 3.12+**: Required for StrEnum and modern Python features
* **TypedDict Models**: Runtime validation for all database operations
* **Migration Auto-Discovery**: Dynamic loading of migrations from versions/ directory
* **Bayes Filter**: Per-chat machine learning spam detection at lib/bayes_filter/
* **Markdown Parser**: Custom implementation with MarkdownV2 support at lib/markdown/
* **Golden Data Testing**: Aurumentation framework for deterministic API testing

## Historical Summary

### Early Decisions (Sept 2025)
* Initial bot implementation with minimal features
* Database abstraction layer for future flexibility
* TOML configuration for human-readable settings
* Memory Bank system for project tracking

### Architecture Evolution
* Refactored from monolithic main.py to modular structure
* Implemented manager pattern for component initialization
* Added comprehensive null safety and type checking
* Created abstract interfaces for extensibility

### Testing Strategy
* Consolidated under pytest for consistency
* Golden data approach for external API testing
* Comprehensive coverage reporting
* Separation of unit, integration, and e2e tests

## Current Best Practices

* Use TypedDict for all database row representations
* Validate all external data at boundaries
* Implement proper error handling and logging
* Follow camelCase naming convention for variables/methods
* Use PascalCase for classes, UPPER_CASE for constants
* Always run `make format` and `make lint` before commits
* Create migrations using the generator script
* Document all architectural decisions
[2025-11-12 18:01:00] - Implemented complete rate limiter library with sliding window algorithm and singleton manager pattern. Created lib/rate_limiter/ package with RateLimiterInterface, SlidingWindowRateLimiter, QueueConfig, and RateLimiterManager. All code follows project conventions with camelCase naming, comprehensive docstrings, and Prinny personality logging.
[2025-11-12 19:15:50] - Added __slots__ to YandexSearchClient class for memory optimization