# Multi-Source Database Implementation Plan - Brief Summary

**Date:** 2025-11-30
**Estimated Duration:** 3-5 days

## Quick Overview

Adding support for multiple SQLite database files per chat with simple routing and fallback mechanism.

## Implementation Steps (7 Steps Total)

### Day 1: Core Infrastructure (6 hours)
1. **Create Infrastructure Components** (4h)
   - Build ConnectionManager for connection pooling
   - Build DataSourceRouter for chatId → database routing
   
2. **Add Configuration Support** (2h)
   - TOML configuration for data source mapping
   - Validation and example configs

### Day 2: Refactor DatabaseWrapper (7 hours)
3. **Extract Connection Management** (3h)
   - Move connection logic to ConnectionManager
   - Maintain backward compatibility
   
4. **Implement Routing Decorators** (4h)
   - Create @routeToSource decorator
   - Apply to 19 chat-specific methods

### Day 3: Cross-Chat & Testing (9 hours)
5. **Handle Cross-Chat Methods** (3h)
   - Update getUserChats() and getAllGroupChats()
   - Implement result merging from multiple sources
   
6. **Testing & Validation** (4h)
   - Integration tests for multi-source scenarios
   - Performance testing (<1ms overhead requirement)
   - Fallback mechanism testing
   
7. **Documentation** (2h)
   - User documentation
   - Migration guide
   - Examples and troubleshooting

## Key Files to Create
- `internal/database/connection_manager.py`
- `internal/database/datasource_router.py`
- `configs/database-multi-source.toml.example`
- `tests/test_multi_source.py`

## Key Files to Modify
- `internal/database/wrapper.py` (main refactor)

## Success Criteria
✓ Multiple SQLite files work simultaneously
✓ Transparent routing based on chatId
✓ Fallback to default database
✓ 100% backward compatibility
✓ <1ms routing overhead
✓ Zero downtime migration

## Implementation Order for Code Mode

1. Start with ConnectionManager class
2. Add DataSourceRouter class
3. Refactor DatabaseWrapper constructor
4. Add routing decorator
5. Apply decorator to methods
6. Test thoroughly
7. Document everything

## Configuration Example
```toml
[database.sources.primary]
type = "sqlite"
path = "bot.db"

[database.sources.archive]
type = "sqlite"
path = "archive.db"

[database.chat_mapping]
-1001234567890 = "archive"
```

## Next Steps After This Implementation
- Add PostgreSQL/MySQL support
- Dynamic configuration updates
- Performance monitoring metrics

---

**Ready for implementation in Code mode!**