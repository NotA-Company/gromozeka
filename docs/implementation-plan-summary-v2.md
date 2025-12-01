# Multi-Source Database Implementation Plan v2 - Simplified

**Date:** 2025-11-30  
**Estimated Duration:** 2-3 days (reduced due to simpler architecture)

## Key Changes from v1
- ✅ No circular dependencies - single DatabaseWrapper class
- ✅ No decorators - simple internal routing logic
- ✅ Readonly source support
- ✅ Optional dataSource parameter on all read methods

## Implementation Steps (5 Steps Total)

### Day 1: Core Implementation (5 hours)

#### Step 1: Update DatabaseWrapper Constructor (2h)
```python
# Add to __init__ method:
- Multiple source configuration support
- Connection pool dictionary
- Chat mapping dictionary  
- Readonly flag handling
- Backward compatibility mode
```

#### Step 2: Implement Internal Routing Logic (3h)
```python
# Add _getConnection method:
def _getConnection(self, chatId=None, dataSource=None, requireWrite=False)
```
- Priority: dataSource → chatId mapping → default
- Readonly validation for write operations
- Connection pooling per source

### Day 2: Method Updates (5 hours)

#### Step 3: Update Read Methods (3h)
Add optional `dataSource` parameter to all read methods:
```python
# Example for each read method:
def getChatMessageByMessageId(self, chatId, messageId, dataSource=None):
    conn = self._getConnection(chatId=chatId, dataSource=dataSource)
```

**Methods to update (Category 1 - Chat-specific reads):**
- getChatMessageByMessageId
- getChatMessagesByUser
- getChatUser
- getChatUserByUsername
- getChatInfo
- getChatTopics
- getChatSetting(s)
- getUserData
- getSpamMessagesByUserId

**Methods to update (Category 2 - Cross-chat reads):**
- getUserChats (aggregate from sources)
- getAllGroupChats (aggregate from sources)
- getSpamMessages
- getCacheStorage
- getCacheEntry

#### Step 4: Protect Write Methods (2h)
Ensure write methods check readonly flag:
```python
# No dataSource parameter for writes!
def updateChatUser(self, chatId, userId, username, fullName):
    conn = self._getConnection(chatId=chatId, requireWrite=True)
    # Throws error if source is readonly
```

### Day 3: Configuration & Testing (4 hours)

#### Step 5: Configuration & Testing (4h)
- Create TOML configuration schema
- Add configuration loader
- Unit tests for routing logic
- Integration tests for multi-source
- Readonly enforcement tests
- Backward compatibility tests

## Configuration Format

```toml
[database]
default_source = "primary"

[database.sources.primary]
type = "sqlite"
path = "bot.db"
readonly = false
timeout = 30.0
max_connections = 5

[database.sources.archive]
type = "sqlite"  
path = "archive.db"
readonly = true  # Can only read
timeout = 30.0
max_connections = 3

[database.sources.external_bot]
type = "sqlite"
path = "/shared/other_bot.db"
readonly = true  # External source, readonly
timeout = 10.0
max_connections = 2

[database.chat_mapping]
123456 = "archive"
789012 = "archive"
```

## Implementation Order for Code Mode

### Phase 1: Core Changes
1. Update DatabaseWrapper.__init__ to support config parameter
2. Add _getConnection internal routing method
3. Add connection pool management
4. Test with single source (backward compatibility)

### Phase 2: Method Updates  
1. Add dataSource parameter to read methods
2. Update method bodies to use _getConnection
3. Add requireWrite flag for write methods
4. Test readonly enforcement

### Phase 3: Advanced Features
1. Implement cross-source aggregation for getUserChats/getAllGroupChats
2. Add result deduplication logic
3. Test cross-bot communication scenario

## Testing Checklist

### Unit Tests
- [ ] _getConnection routing logic
- [ ] Readonly enforcement
- [ ] Configuration loading
- [ ] Backward compatibility

### Integration Tests  
- [ ] Multi-source queries
- [ ] Cross-source aggregation
- [ ] Fallback mechanism
- [ ] Cross-bot data sharing

## Success Criteria
✓ No circular dependencies  
✓ Simple implementation (no decorators)
✓ Readonly sources work correctly
✓ dataSource parameter functional
✓ 100% backward compatible
✓ <0.5ms routing overhead

## Example Usage After Implementation

```python
# Initialize with multi-source config
db = DatabaseWrapper(config=load_config())

# Read from default source
messages = db.getChatMessagesByUser(chatId=123, userId=456)

# Read from specific source
archived = db.getChatMessagesByUser(
    chatId=123, 
    userId=456,
    dataSource="archive"  # Explicit source
)

# Cross-bot communication
external = db.getUserData(
    userId=789,
    chatId=012,
    dataSource="external_bot"  # Read from another bot's DB
)

# Write operation (no dataSource param)
db.updateChatUser(chatId=123, userId=456, 
                  username="user", fullName="User Name")
# Automatically routes to correct source and checks readonly
```

## Notes for Code Mode
- Keep it simple - no over-engineering
- Internal routing only, no external classes
- Focus on backward compatibility
- Test thoroughly before enabling multi-source

---

**Ready for implementation! Total effort reduced from 3-5 days to 2-3 days due to simpler architecture.**