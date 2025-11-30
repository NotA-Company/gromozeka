# Task 10.0.0: Multi-Source Database Architecture Implementation

**Phase:** Phase 10: Database Architecture Enhancement
**Category:** Architecture & Infrastructure
**Priority:** High
**Complexity:** Complex
**Estimated Duration:** 2-3 days
**Assigned To:** Code Mode Implementation Team
**Date Created:** 2025-11-30

## Objective

Implement a multi-source database architecture that enables the bot to work with multiple SQLite databases simultaneously, supporting readonly sources, chat-to-source mapping, and maintaining complete backward compatibility with the existing single-database mode.

**Success Definition:** The bot can seamlessly route database operations to appropriate data sources based on configuration, enforce readonly constraints, and support cross-bot data sharing without breaking existing functionality.

## Prerequisites

### Dependency Tasks
- [x] **Database Design v2:** Architecture design document completed and approved - [Status: Complete]
- [x] **User Clarifications:** All design decisions clarified and documented - [Status: Complete]
- [ ] **Backup Current Database:** Create backup of existing bot.db before implementation - [Status: Pending]

### Required Artifacts
- [`docs/design/multi-source-database-architecture-v2.md`](docs/design/multi-source-database-architecture-v2.md) - Architecture design specifications
- [`internal/database/wrapper.py`](internal/database/wrapper.py) - Current DatabaseWrapper implementation
- [`internal/database/models.py`](internal/database/models.py) - Database model definitions
- [`configs/00-defaults/00-config.toml`](configs/00-defaults/00-config.toml) - Configuration template

## Detailed Steps

### Phase 1: Constructor Updates for Multi-Source Support
**Estimated Time:** 4 hours
**Description:** Update DatabaseWrapper constructor to support both legacy single-database mode and new multi-source configuration mode.

**Actions:**
- [ ] Add config parameter to __init__ method alongside existing dbPath parameter
- [ ] Implement _multiSourceMode flag to track operation mode
- [ ] Create _sources dictionary to store source configurations
- [ ] Create _connections dictionary to manage connection pools per source
- [ ] Implement _chatMapping dictionary for chat-to-source routing
- [ ] Add _defaultSource field with fallback to "primary"
- [ ] Ensure backward compatibility with existing single dbPath initialization

**Completion Criteria:**
- DatabaseWrapper can initialize in both legacy and multi-source modes
- No breaking changes to existing code using dbPath parameter
- All internal data structures properly initialized

**Potential Issues:**
- Existing code might break if constructor signature changes incompatibly
- Mitigation: Use optional parameters and maintain backward compatibility

### Phase 2: Internal Routing Logic Implementation
**Estimated Time:** 6 hours
**Description:** Implement the core _getConnection method that routes database operations to appropriate sources based on priority rules.

**Actions:**
- [ ] Create _initializeSources method to set up all data sources from config
- [ ] Implement _createConnectionPool method for per-source connection management
- [ ] Build _getConnection method with 3-tier routing priority:
  - [ ] Priority 1: Explicit dataSource parameter
  - [ ] Priority 2: ChatId mapping lookup
  - [ ] Priority 3: Default source fallback
- [ ] Add readonly validation logic for write operations
- [ ] Implement connection pooling with configurable pool sizes
- [ ] Add error handling for missing sources with fallback behavior
- [ ] Create logging for routing decisions (debug level)

**Completion Criteria:**
- Routing logic correctly selects data source based on priorities
- Readonly sources reject write attempts with clear error messages
- Connection pooling works efficiently for each source
- Fallback to default source works when specified source unavailable

**Potential Issues:**
- Thread safety concerns with multiple connection pools
- Mitigation: Use threading locks for pool management
- Performance overhead from routing decisions
- Mitigation: Cache routing decisions where possible

### Phase 3: Read Methods Updates
**Estimated Time:** 6 hours
**Description:** Update all read methods in DatabaseWrapper to accept optional dataSource parameter and use the new routing logic.

**Actions:**
- [ ] Add dataSource: Optional[str] = None parameter to all read methods:
  - [ ] getChatMessageByMessageId
  - [ ] getChatMessagesByUser
  - [ ] getUserChats
  - [ ] getUserData
  - [ ] getChatSettings
  - [ ] getSystemPrompt
  - [ ] getActiveUsers
  - [ ] getMessageHistory
  - [ ] searchMessages
  - [ ] getStatistics
- [ ] Update each method to call _getConnection with dataSource parameter
- [ ] Implement aggregation logic for cross-source queries (getUserChats, etc.)
- [ ] Add deduplication for cross-source aggregated results (by userId+chatId)
- [ ] Ensure backward compatibility - existing calls without dataSource still work
- [ ] Update method docstrings to document dataSource parameter

**Completion Criteria:**
- All read methods accept optional dataSource parameter
- Methods work correctly with and without dataSource specified
- Cross-source aggregation works with proper deduplication
- No breaking changes to existing method calls

**Potential Issues:**
- Large number of methods to update may introduce errors
- Mitigation: Update incrementally and test each method
- Aggregation performance for cross-source queries
- Mitigation: Implement efficient deduplication algorithm

### Phase 4: Write Methods Protection
**Estimated Time:** 4 hours
**Description:** Update all write methods to use requireWrite flag ensuring they only write to appropriate writable sources.

**Actions:**
- [ ] Update all write methods to use requireWrite=True in _getConnection:
  - [ ] addChatMessage
  - [ ] updateChatUser
  - [ ] setChatSetting
  - [ ] updateUserData
  - [ ] deleteMessages
  - [ ] archiveChat
  - [ ] createBackup
  - [ ] runMigration
- [ ] Ensure write methods DO NOT accept dataSource parameter
- [ ] Add proper error handling for readonly source write attempts
- [ ] Implement transaction support for write operations
- [ ] Add logging for all write operations with source information
- [ ] Document that cross-source transactions are not supported

**Completion Criteria:**
- Write operations correctly routed to writable sources only
- Readonly sources properly protected from write attempts
- Clear error messages when write to readonly attempted
- Existing write operations continue to work unchanged

**Potential Issues:**
- Accidental writes to readonly sources
- Mitigation: Enforce at connection level, not just method level
- Transaction complexity across sources
- Mitigation: Document as unsupported, single-source transactions only

### Phase 5: Configuration Schema and Examples
**Estimated Time:** 3 hours
**Description:** Create configuration schema, TOML examples, and update default configurations for multi-source support.

**Actions:**
- [ ] Define DATA_SOURCES configuration schema in TOML format
- [ ] Create CHAT_SOURCE_MAPPING configuration structure
- [ ] Add DEFAULT_SOURCE and DEFAULT_READONLY_SOURCE settings
- [ ] Create example configurations:
  - [ ] Single database (legacy mode)
  - [ ] Primary + Archive databases
  - [ ] Multiple bots sharing data
  - [ ] External readonly sources
- [ ] Update configs/00-defaults/00-config.toml with new schema
- [ ] Add per-source connection pool configuration options
- [ ] Document all configuration options with comments
- [ ] Create migration guide from single to multi-source configuration

**Completion Criteria:**
- Clear, well-documented configuration schema
- Multiple working example configurations
- Easy migration path from single-database setup
- All configuration options properly documented

**Potential Issues:**
- Complex configuration might confuse users
- Mitigation: Provide clear examples and defaults
- Breaking changes to existing configs
- Mitigation: Maintain backward compatibility, make new options optional

### Phase 6: Testing and Validation
**Estimated Time:** 5 hours
**Description:** Comprehensive testing of all multi-source functionality including backward compatibility, routing, and cross-source operations.

**Actions:**
- [ ] Create unit tests for:
  - [ ] Constructor with legacy and multi-source modes
  - [ ] _getConnection routing logic all three priorities
  - [ ] Readonly enforcement on write operations
  - [ ] Connection pooling per source
  - [ ] Fallback behavior for missing sources
- [ ] Create integration tests for:
  - [ ] Single-database backward compatibility
  - [ ] Multi-source read operations
  - [ ] Cross-source aggregation with deduplication
  - [ ] Chat-to-source mapping
  - [ ] Readonly source protection
- [ ] Performance testing:
  - [ ] Measure routing overhead (<0.5ms target)
  - [ ] Connection pool efficiency
  - [ ] Cross-source query performance
- [ ] Manual validation scenarios:
  - [ ] Bot startup with various configurations
  - [ ] Live chat routing to different sources
  - [ ] Archive database queries
  - [ ] External bot data access

**Completion Criteria:**
- All unit tests passing
- Integration tests confirm backward compatibility
- Performance meets <0.5ms routing overhead target
- Manual testing confirms real-world functionality

**Potential Issues:**
- Test database setup complexity
- Mitigation: Create test fixtures and helper functions
- Performance regression in existing operations
- Mitigation: Benchmark before and after implementation

## Expected Outcome

### Primary Deliverables
- [`internal/database/wrapper.py`](internal/database/wrapper.py) - Updated DatabaseWrapper with multi-source support
- [`configs/00-defaults/00-config.toml`](configs/00-defaults/00-config.toml) - Updated configuration with new schema
- [`docs/configuration/multi-source-setup.md`](docs/configuration/multi-source-setup.md) - Configuration guide for multi-source setup

### Secondary Deliverables
- [`tests/test_multi_source_database.py`](tests/test_multi_source_database.py) - Comprehensive test suite
- [`configs/examples/`](configs/examples/) - Example configuration files
- Updated method docstrings with dataSource parameter documentation
- Migration guide from single to multi-source configuration

### Quality Standards
- Zero breaking changes to existing functionality
- 100% backward compatibility with single-database mode
- All tests passing with >90% code coverage
- Routing overhead <0.5ms per operation
- Clear error messages for all failure scenarios
- Comprehensive documentation for all new features

### Integration Points
- Bot handlers continue to work unchanged
- Configuration system extended but backward compatible
- Database models remain unchanged
- Connection pooling transparent to calling code
- Monitoring and logging enhanced but not required

## Testing Criteria

### Unit Testing
- [ ] **Constructor Tests:** Verify both legacy and multi-source initialization
  - Test with dbPath only (legacy mode)
  - Test with config only (multi-source mode)
  - Test with invalid configurations
  - Pass/fail criteria: All modes initialize correctly

- [ ] **Routing Logic Tests:** Verify _getConnection routing priorities
  - Test explicit dataSource parameter routing
  - Test chatId mapping routing
  - Test default source fallback
  - Test missing source handling
  - Pass/fail criteria: Correct source selected in all scenarios

- [ ] **Readonly Enforcement Tests:** Verify write protection
  - Test write attempt to readonly source
  - Test read from readonly source
  - Test requireWrite flag enforcement
  - Pass/fail criteria: Readonly sources never accept writes

### Integration Testing
- [ ] **Backward Compatibility:** Verify existing code works unchanged
  - Test single database mode operations
  - Test all existing method signatures
  - Test without any configuration changes
  - Pass/fail criteria: Zero breaking changes

- [ ] **Multi-Source Operations:** Verify cross-source functionality
  - Test reading from multiple sources
  - Test aggregation with deduplication
  - Test chat-specific routing
  - Pass/fail criteria: All sources accessible and routable

### Manual Validation
- [ ] **Configuration Validation:** Test various configurations
  - Single database setup
  - Multiple databases with mixed readonly
  - External bot database access
  - Pass/fail criteria: All configurations load and work correctly

- [ ] **Live Testing:** Test with running bot
  - Send messages to different chats
  - Verify routing to correct sources
  - Test archive queries
  - Pass/fail criteria: Bot operates normally with multi-source

### Performance Testing
- [ ] **Routing Overhead:** Measure routing decision time
  - Benchmark 10,000 routing decisions
  - Compare with direct connection baseline
  - Pass/fail criteria: <0.5ms average overhead

- [ ] **Connection Pool Efficiency:** Verify pool performance
  - Test concurrent access patterns
  - Measure connection reuse rate
  - Pass/fail criteria: >95% connection reuse rate

## Definition of Done

### Functional Completion
- [ ] All 6 implementation phases completed
- [ ] DatabaseWrapper supports multi-source configuration
- [ ] Backward compatibility fully maintained
- [ ] All read methods accept optional dataSource parameter
- [ ] All write methods protected with requireWrite flag
- [ ] Configuration schema defined and documented
- [ ] Routing logic working correctly with all three priority levels
- [ ] Readonly enforcement working at connection level

### Quality Assurance
- [ ] All unit tests passing (>90% coverage)
- [ ] All integration tests passing
- [ ] Performance requirements met (<0.5ms routing overhead)
- [ ] No memory leaks or resource issues
- [ ] Thread safety verified for concurrent access
- [ ] Error handling comprehensive and informative
- [ ] Code review completed and approved

### Documentation
- [ ] All methods documented with updated signatures
- [ ] Configuration guide written with examples
- [ ] Migration guide from single to multi-source created
- [ ] API documentation updated for dataSource parameter
- [ ] Architecture diagram updated in design doc
- [ ] README updated with multi-source information

### Integration and Deployment
- [ ] Changes integrated without breaking existing code
- [ ] All bot handlers tested with multi-source
- [ ] Configuration files updated with new schema
- [ ] Deployment procedures updated if needed
- [ ] Rollback plan documented and tested
- [ ] Monitoring updated to track per-source metrics

### Administrative
- [ ] Task status updated to complete
- [ ] Time tracking recorded (target: 2-3 days)
- [ ] Lessons learned documented
- [ ] Any technical debt identified and logged
- [ ] Next steps identified (future database types support)
- [ ] Completion report written in docs/reports/

## Risk Assessment

### Technical Risks
1. **Breaking Existing Functionality**
   - Probability: Medium
   - Impact: High
   - Mitigation: Extensive backward compatibility testing, optional parameters

2. **Performance Degradation**
   - Probability: Low
   - Impact: Medium
   - Mitigation: Caching routing decisions, connection pooling, performance benchmarks

3. **Thread Safety Issues**
   - Probability: Medium
   - Impact: High
   - Mitigation: Proper locking mechanisms, thread-safe connection pools

### Implementation Risks
1. **Scope Creep**
   - Probability: Medium
   - Impact: Medium
   - Mitigation: Stick to defined phases, defer advanced features

2. **Testing Complexity**
   - Probability: High
   - Impact: Low
   - Mitigation: Create comprehensive test fixtures and helpers

### Operational Risks
1. **Configuration Errors**
   - Probability: Medium
   - Impact: Medium
   - Mitigation: Clear documentation, validation, good defaults

2. **Migration Issues**
   - Probability: Low
   - Impact: High
   - Mitigation: Careful migration guide, backup procedures

## Timeline Estimates

### Phase Breakdown
- **Phase 1:** Constructor Updates - 4 hours (Half day)
- **Phase 2:** Routing Logic - 6 hours (Most of day 1)
- **Phase 3:** Read Methods - 6 hours (Day 2 morning)
- **Phase 4:** Write Methods - 4 hours (Day 2 afternoon)
- **Phase 5:** Configuration - 3 hours (Day 2 evening)
- **Phase 6:** Testing - 5 hours (Day 3)

### Total Estimate
- **Development Time:** 23 hours (2.5 days)
- **Buffer for Issues:** 5 hours (0.5 days)
- **Total Duration:** 28 hours (3 days maximum)

### Milestones
- **End of Day 1:** Phases 1-2 complete (routing working)
- **End of Day 2:** Phases 3-5 complete (all methods updated)
- **End of Day 3:** Phase 6 complete (fully tested and documented)

---

**Related Tasks:**
**Previous:** [Task 9.X.X - Database Performance Optimization]
**Next:** [Task 11.X.X - NoSQL Database Support]
**Parent Phase:** [Phase 10 - Database Architecture Enhancement]