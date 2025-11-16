# Task 3.0.0: Max Bot Client Library - Phase 3: Basic Operations

**Phase:** Phase 3: Basic Operations
**Category:** Library Development
**Priority:** High
**Complexity:** Moderate
**Estimated Duration:** 3-4 days
**Assigned To:** Development Team
**Date Created:** 2024-11-16

## Objective

Implement core API operations for bot information retrieval, chat management, member management, and admin operations. This phase establishes the fundamental bot capabilities for interacting with chats and users.

**Success Definition:** Fully functional API methods for all basic operations with proper pagination, error handling, and comprehensive test coverage.

## Prerequisites

### Dependency Tasks
- [x] **Task 1.0.0:** Phase 1: Core Infrastructure - [Status: Complete]
- [x] **Task 2.0.0:** Phase 2: Models & Data Structures - [Status: Complete]

### Required Artifacts
- [`lib/max_bot/client.py`](lib/max_bot/client.py) - Base client implementation
- [`lib/max_bot/api/base.py`](lib/max_bot/api/base.py) - Base API client
- [`lib/max_bot/models/`](lib/max_bot/models/) - All model implementations
- [`lib/max_bot/constants.py`](lib/max_bot/constants.py) - API constants

## Detailed Steps

### Step 1: Create Bot API Module
**Estimated Time:** 2 hours
**Description:** Implement bot information endpoints

**Actions:**
- [ ] Create `lib/max_bot/api/bot.py`
- [ ] Implement `getMyInfo()` method
- [ ] Implement `editMyInfo()` method (PATCH /me)
- [ ] Add proper return type hints
- [ ] Handle authentication errors
- [ ] Cache bot info optionally

**Completion Criteria:**
- Bot info retrieval works
- Bot info editing works
- Caching is configurable
- Error handling is comprehensive

**Potential Issues:**
- Bot info changes during runtime
- Mitigation: Cache invalidation strategy

### Step 2: Create Chat Management Module
**Estimated Time:** 3 hours
**Description:** Implement chat CRUD operations

**Actions:**
- [ ] Create `lib/max_bot/api/chats.py`
- [ ] Implement `getChats()` with pagination
- [ ] Implement `getChat(chatId)` 
- [ ] Implement `getChatByLink(chatLink)`
- [ ] Implement `editChat(chatId, patch)`
- [ ] Implement `deleteChat(chatId)`
- [ ] Add marker-based pagination handling

**Completion Criteria:**
- All chat operations work
- Pagination is handled correctly
- Link/username resolution works
- Edit operations validated

**Potential Issues:**
- Pagination complexity
- Mitigation: Create pagination helper

### Step 3: Implement Pagination Helper
**Estimated Time:** 2 hours
**Description:** Create reusable pagination utility

**Actions:**
- [ ] Create `lib/max_bot/utils/pagination.py`
- [ ] Implement `PaginationIterator` class
- [ ] Support marker-based pagination
- [ ] Add async iteration support
- [ ] Create convenience methods
- [ ] Add configurable page sizes

**Completion Criteria:**
- Pagination works for all list endpoints
- Async iteration is smooth
- Memory efficient for large datasets
- Well-documented usage

**Potential Issues:**
- Different pagination styles in API
- Mitigation: Flexible iterator design

### Step 4: Create Pin Message Operations
**Estimated Time:** 2 hours
**Description:** Implement message pinning functionality

**Actions:**
- [ ] Add `getPinnedMessage(chatId)` method
- [ ] Add `pinMessage(chatId, messageId, notify)` method
- [ ] Add `unpinMessage(chatId)` method
- [ ] Handle nullable pinned messages
- [ ] Add notification control

**Completion Criteria:**
- Pin operations work correctly
- Null handling is proper
- Notification flags work
- Error cases handled

**Potential Issues:**
- Permission errors
- Mitigation: Clear error messages

### Step 5: Create Chat Actions Module
**Estimated Time:** 1.5 hours
**Description:** Implement chat action notifications

**Actions:**
- [ ] Add `sendAction(chatId, action)` method
- [ ] Support all action types from enum
- [ ] Add typing indicator helper
- [ ] Add file sending indicators
- [ ] Create action context manager

**Completion Criteria:**
- All actions types work
- Context manager works
- Helpers are convenient
- Documentation is clear

**Potential Issues:**
- Action timing complexity
- Mitigation: Clear usage examples

### Step 6: Create Member Management Module
**Estimated Time:** 3 hours
**Description:** Implement chat member operations

**Actions:**
- [ ] Create `lib/max_bot/api/members.py`
- [ ] Implement `getMembers(chatId)` with pagination
- [ ] Implement `getMembersByIds(chatId, userIds)`
- [ ] Implement `addMembers(chatId, userIds)`
- [ ] Implement `removeMember(chatId, userId, block)`
- [ ] Implement `getMembership(chatId)` for bot
- [ ] Implement `leaveChat(chatId)`

**Completion Criteria:**
- All member operations work
- Bulk operations supported
- Block parameter works
- Self operations work

**Potential Issues:**
- Permission restrictions
- Mitigation: Document required permissions

### Step 7: Implement Admin Management
**Estimated Time:** 2 hours
**Description:** Create admin-related operations

**Actions:**
- [ ] Add `getAdmins(chatId)` method
- [ ] Add `setAdmins(chatId, admins)` method
- [ ] Add `deleteAdmin(chatId, userId)` method
- [ ] Handle permission arrays
- [ ] Add permission helper methods

**Completion Criteria:**
- Admin operations work
- Permissions handled correctly
- Helper methods intuitive
- Bulk operations supported

**Potential Issues:**
- Complex permission model
- Mitigation: Permission builder helper

### Step 8: Create Permission Helper
**Estimated Time:** 1.5 hours
**Description:** Build permission management utilities

**Actions:**
- [ ] Create `lib/max_bot/utils/permissions.py`
- [ ] Implement permission builder class
- [ ] Add permission checking methods
- [ ] Create permission presets
- [ ] Document permission model

**Completion Criteria:**
- Permission building is easy
- Common patterns supported
- Validation included
- Well-documented

**Potential Issues:**
- Permission combinations
- Mitigation: Validate against API

### Step 9: Add Method Shortcuts to Client
**Estimated Time:** 2 hours
**Description:** Add convenience methods to main client

**Actions:**
- [ ] Update `lib/max_bot/client.py`
- [ ] Add all basic operation methods
- [ ] Delegate to appropriate modules
- [ ] Maintain consistent interface
- [ ] Add method grouping

**Completion Criteria:**
- All methods accessible from client
- Interface is intuitive
- Delegation works properly
- Backward compatible

**Potential Issues:**
- Method name conflicts
- Mitigation: Clear naming convention

### Step 10: Implement Rate Limiting
**Estimated Time:** 2 hours
**Description:** Add rate limiting for basic operations

**Actions:**
- [ ] Integrate with rate limiter from Phase 1
- [ ] Configure limits per endpoint
- [ ] Add retry logic for rate limits
- [ ] Create rate limit statistics
- [ ] Document rate limits

**Completion Criteria:**
- Rate limiting works
- Retries are automatic
- Statistics available
- Configurable limits

**Potential Issues:**
- Different limits per endpoint
- Mitigation: Per-endpoint configuration

### Step 11: Add Response Caching
**Estimated Time:** 2 hours
**Description:** Implement optional response caching

**Actions:**
- [ ] Create cache configuration
- [ ] Cache chat information
- [ ] Cache member lists
- [ ] Add cache invalidation
- [ ] Make caching optional

**Completion Criteria:**
- Caching improves performance
- Invalidation works correctly
- Memory usage acceptable
- Can be disabled

**Potential Issues:**
- Stale data issues
- Mitigation: Short TTL defaults

### Step 12: Create Integration Tests
**Estimated Time:** 3 hours
**Description:** Write comprehensive integration tests

**Actions:**
- [ ] Create test files for each module
- [ ] Mock API responses
- [ ] Test pagination scenarios
- [ ] Test error handling
- [ ] Test permission errors
- [ ] Add performance tests

**Completion Criteria:**
- Coverage > 85%
- All scenarios tested
- Mocks are realistic
- Tests are maintainable

**Potential Issues:**
- Complex mock scenarios
- Mitigation: Use recorded responses

### Step 13: Add Examples and Documentation
**Estimated Time:** 2 hours
**Description:** Create usage examples and guides

**Actions:**
- [ ] Create example scripts
- [ ] Document common patterns
- [ ] Add troubleshooting guide
- [ ] Create API reference
- [ ] Add migration notes

**Completion Criteria:**
- Examples are runnable
- Documentation is clear
- Common issues addressed
- API reference complete

**Potential Issues:**
- Keeping examples updated
- Mitigation: Automated testing of examples

## Expected Outcome

### Primary Deliverables
- [`lib/max_bot/api/bot.py`](lib/max_bot/api/bot.py) - Bot operations
- [`lib/max_bot/api/chats.py`](lib/max_bot/api/chats.py) - Chat management
- [`lib/max_bot/api/members.py`](lib/max_bot/api/members.py) - Member operations
- [`lib/max_bot/utils/pagination.py`](lib/max_bot/utils/pagination.py) - Pagination helper
- [`lib/max_bot/utils/permissions.py`](lib/max_bot/utils/permissions.py) - Permission utilities

### Secondary Deliverables
- Integration tests for all modules
- Usage examples and documentation
- Performance benchmarks
- Cache configuration

### Quality Standards
- All methods follow camelCase convention
- Comprehensive type hints
- API descriptions in docstrings
- Test coverage > 85%
- Rate limiting implemented
- Passes `make format` and `make lint`

### Integration Points
- Uses models from Phase 2
- Extends base client from Phase 1
- Ready for messaging in Phase 4
- Cache integration with existing patterns

## Testing Criteria

### Unit Testing
- [ ] **Bot Operations:** Test all methods
  - Bot info retrieval
  - Bot info updates
  - Error handling
  
- [ ] **Chat Operations:** Test CRUD
  - Create/Read/Update/Delete
  - Pagination
  - Link resolution

- [ ] **Member Operations:** Test management
  - Add/remove members
  - Permission changes
  - Bulk operations

### Integration Testing
- [ ] **End-to-end Flows:** Complete scenarios
  - Join chat flow
  - Admin promotion flow
  - Chat configuration
  
- [ ] **Pagination:** Large datasets
  - Memory usage
  - Performance
  - Consistency

### Manual Validation
- [ ] **Live API Testing:** Real endpoints
  - Authentication works
  - Operations succeed
  - Error handling

### Performance Testing
- [ ] **Throughput:** Request rates
  - Rate limiting
  - Concurrent operations
  - Cache effectiveness

## Definition of Done

### Functional Completion
- [ ] All 13 steps completed
- [ ] All API methods implemented
- [ ] Pagination works correctly
- [ ] Rate limiting active

### Quality Assurance
- [ ] All tests pass
- [ ] Coverage > 85%
- [ ] No linting errors
- [ ] Type checking passes

### Documentation
- [ ] All methods documented
- [ ] Examples provided
- [ ] API reference complete
- [ ] Troubleshooting guide

### Integration and Deployment
- [ ] Client methods work
- [ ] No breaking changes
- [ ] Ready for Phase 4

### Administrative
- [ ] Report created
- [ ] Time tracked
- [ ] Phase 4 prepared
- [ ] Code reviewed

---

**Related Tasks:**
**Previous:** Phase 2: Models & Data Structures
**Next:** Phase 4: Messaging System
**Parent Phase:** Max Bot Client Library Implementation

---

## Notes

This phase establishes the core bot functionality needed for basic operations. Key focus areas:
- Robust pagination handling for large chat/member lists
- Proper permission management
- Efficient caching strategy
- Clear separation between modules
- Comprehensive error handling for permission-related errors