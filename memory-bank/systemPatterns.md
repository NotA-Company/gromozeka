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

#### Migration Documentation Protocol
[2026-01-07 22:56:47] - Critical lesson learned from migration_009 documentation error

**Context**: When creating a revert migration (migration_009), documentation was updated incorrectly:
- migration_003 was omitted from documentation
- migration_003's functionality (adding `metadata` column) was incorrectly attributed to migration_009
- Root cause: Didn't verify existing migrations before updating documentation

**Mandatory Steps for Migration Documentation Updates**:

1. **Read ALL Existing Migrations First**
   - Never assume what migrations do from their names
   - Read the actual migration code for all relevant migrations
   - Build complete mental model of migration history

2. **Verify Migration Functionality**
   - Check what columns/tables each migration actually adds/removes
   - Cross-reference with existing documentation
   - Identify any gaps or inconsistencies in current docs

3. **Document Only Actual Changes**
   - Each migration should only document what IT does
   - Never mix functionality from different migrations
   - Preserve complete migration history timeline

4. **Validate Documentation Changes**
   - Review all migrations mentioned in docs still exist
   - Ensure no migrations are accidentally omitted
   - Verify column attributions match actual migration code

5. **Cross-Check Schema Files**
   - Update both human and LLM documentation consistently
   - Ensure schema descriptions match migration history
   - Validate that all historical migrations are accounted for

**Prevention**: Before modifying migration docs, run:
```bash
ls internal/database/migrations/versions/
# Then read each migration file to understand its purpose
```

#### Migration Versioning Protocol
[2026-01-07 22:59:06] - Critical lesson learned from migration version conflict

**Context**: When creating migration_009, initially attempted to create migration_003 without checking existing migrations first. This caused a duplicate version number conflict because migration_003 already existed.

**The Problem**:
- Attempted to create migration_003 for removing `is_spammer` column
- migration_003 already existed (adds `metadata` column to `chat_users`)
- Result: Version number conflict that would break migration system

**Mandatory Migration Creation Protocol**:

1. **ALWAYS Check Existing Migrations First**
   - Before creating ANY new migration, list all existing migrations
   - Identify the highest migration version number
   - Never assume what the next version should be

2. **Find Highest Version Command**:
   ```bash
   ls -1 internal/database/migrations/versions/ | grep "migration_" | sort -V | tail -1
   # This shows the highest numbered migration file
   ```

3. **Version Calculation Rule**:
   ```
   New Migration Version = Latest Migration Version + 1
   ```
   Example: If highest is migration_008, create migration_009

4. **Verification Before Creation**:
   - Run the ls command above
   - Extract the version number from filename
   - Add 1 to get new version number
   - Create migration with correct version

**Prevention**: Before creating any migration, always run:
```bash
# List all migrations to find the highest version
ls -1 internal/database/migrations/versions/ | grep "migration_" | sort -V | tail -1

# Or check the full directory listing
ls internal/database/migrations/versions/
```

**Key Takeaway**: Migration version numbers are sequential and immutable. Always verify the current highest version before creating a new migration, dood!

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