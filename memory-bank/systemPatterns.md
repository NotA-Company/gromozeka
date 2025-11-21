# System Patterns

[2025-11-21 22:50:40] - Condensed from archive to focus on essential development patterns

## Core Development Patterns

### Code Quality Workflow
* **Required Pipeline**: `make format lint test` before all commits
* **Formatting**: Automatic code formatting with configured tools
* **Linting**: Style and quality checks with issue reporting
* **Testing**: Comprehensive test suite with coverage reporting

### Naming Conventions
* **Variables/Methods**: camelCase (`getUserData`, `processMessage`)
* **Classes**: PascalCase (`BotHandler`, `MessageProcessor`)
* **Constants**: UPPER_CASE (`API_TIMEOUT`, `MAX_RETRIES`)

### Documentation Standards
* **Docstrings**: Concise with complete Args/Returns sections
* **Task Completion**: Always create completion reports in [`docs/reports/`](docs/reports/)
* **Architecture**: Document all significant decisions

## Architectural Patterns

### Service-Oriented Architecture
* **Service Layer**: [`internal/services/`](internal/services/) - Cache, queue, and core services
* **Library Layer**: [`lib/`](lib/) - Reusable components and integrations
* **Bot Layer**: [`internal/bot/`](internal/bot/) - Multi-platform handlers

### Database Patterns
* **Migration System**: Auto-discovery with version tracking
* **TypedDict Models**: Runtime validation for all database operations
* **Transaction Safety**: Automatic rollback on failures

### Testing Patterns
* **Golden Data**: Record/replay for API testing with quota protection
* **pytest Integration**: Unified test execution across all components
* **Coverage Requirements**: High coverage with comprehensive reporting

## Memory Optimization
* **__slots__**: Use for all data classes and models
* **Singleton Services**: Cache and queue services use singleton pattern
* **Namespace Organization**: Logical separation with persistence options

## Configuration Management
* **TOML Format**: Human-readable hierarchical configuration
* **Environment Overrides**: Base defaults with specific overrides
* **Multi-Source Merging**: Automatic configuration composition

## API Integration Standards
* **Rate Limiting**: Sliding window algorithm with per-service limits
* **Caching Strategy**: TTL-based with namespace organization
* **Error Handling**: Proper timeout and retry mechanisms
* **Golden Testing**: Deterministic testing without API quotas