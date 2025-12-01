# Multi-Source Database Configuration Guide

**Version:** 1.0  
**Date:** 2025-11-30  
**Status:** Production Ready

## Table of Contents

1. [Overview](#overview)
2. [Configuration Structure](#configuration-structure)
3. [Source Configuration](#source-configuration)
4. [Chat Mapping](#chat-mapping)
5. [Connection Pooling](#connection-pooling)
6. [Readonly Sources](#readonly-sources)
7. [Migration Guide](#migration-guide)
8. [Best Practices](#best-practices)
9. [Troubleshooting](#troubleshooting)
10. [Examples](#examples)

## Overview

The multi-source database architecture allows Gromozeka to work with multiple SQLite databases simultaneously, enabling powerful use cases like:

- **Archive Old Chats**: Move inactive chats to readonly archive databases
- **Cross-Bot Communication**: Read from other bot databases (readonly)
- **Data Segregation**: Separate production and test chats
- **Performance Optimization**: Distribute load across multiple databases
- **Backup Access**: Query backup databases without write risk

### Key Features

- **3-Tier Routing**: Intelligent routing with dataSource parameter → chatMapping → defaultSource
- **Readonly Protection**: Sources can be marked readonly to prevent accidental writes
- **Per-Source Connection Pools**: Configurable pool sizes for each database
- **Cross-Source Aggregation**: Read methods can query multiple sources
- **Backward Compatible**: Works with existing single-database configurations

## Configuration Structure

Multi-source configuration is provided via a dictionary passed to [`DatabaseWrapper.__init__()`](../internal/database/wrapper.py:132):

```python
from internal.database import DatabaseWrapper

config = {
    "default": "primary",  # Default source name
    "sources": {
        "primary": {
            "path": "bot.db",
            "readonly": False,
            "pool-size": 5,      # Optional
            "timeout": 30.0      # Optional
        },
        "archive": {
            "path": "archive.db",
            "readonly": True,
            "pool-size": 3,
            "timeout": 30.0
        }
    },
    "chatMapping": {
        -1001234567890: "archive",  # Map specific chats to sources
        -1009876543210: "primary"
    }
}

db = DatabaseWrapper(config=config)
```

### TOML Configuration

In TOML configuration files:

```toml
[database]
default = "primary"

[database.sources.primary]
path = "bot.db"
readonly = false
pool-size = 5
timeout = 30.0

[database.sources.archive]
path = "archive.db"
readonly = true
pool-size = 3
timeout = 30.0

[database.chatMapping]
-1001234567890 = "archive"
-1009876543210 = "primary"
```

## Source Configuration

Each data source requires specific configuration parameters:

### Required Parameters

- **`path`**: Path to the SQLite database file (relative or absolute)
  - Example: `"bot.db"`, `"/shared/archive.db"`, `"../backups/old.db"`

### Optional Parameters

- **`readonly`**: Boolean flag for readonly mode (default: `false`)
  - `true`: Only SELECT queries allowed, writes raise `ValueError`
  - `false`: Full read/write access
  
- **`pool-size`**: Maximum connections for this source (default: 5)
  - Higher values = more concurrent operations
  - Lower values = less memory usage
  
- **`timeout`**: Connection timeout in seconds (default: 30.0)
  - How long to wait for database lock before failing

### Source Configuration Examples

```python
# Minimal configuration (uses defaults)
"primary": {
    "path": "bot.db"
}

# Full configuration
"archive": {
    "path": "archive.db",
    "readonly": True,
    "pool-size": 3,
    "timeout": 10.0
}

# External bot database (readonly)
"other_bot": {
    "path": "/shared/other_bot.db",
    "readonly": True,
    "pool-size": 2,
    "timeout": 5.0
}
```

## Chat Mapping

Chat mapping routes specific chats to specific data sources. This is useful for:

- Moving old/inactive chats to archive databases
- Segregating test chats from production
- Distributing load across multiple databases

### Configuration

```python
"chatMapping": {
    -1001234567890: "archive",  # Old chat in archive
    -1009876543210: "primary",  # Active chat in primary
    -1001111111111: "test_db"   # Test chat in test database
}
```

### Routing Priority

When a method is called with a `chatId`, routing follows this priority:

1. **Explicit `dataSource` parameter** (highest priority)
2. **Chat mapping lookup** (medium priority)
3. **Default source** (lowest priority/fallback)

Example:

```python
# Uses archive source (from chatMapping)
messages = db.getChatMessages(chatId=-1001234567890)

# Overrides mapping, uses primary source explicitly
messages = db.getChatMessages(chatId=-1001234567890, dataSource="primary")

# No chatId, uses default source
settings = db.getSettings()
```

## Connection Pooling

Each data source maintains its own connection pool for thread-safe concurrent access.

### Pool Size Guidelines

- **High-Traffic Sources**: 5-10 connections
- **Medium-Traffic Sources**: 3-5 connections
- **Low-Traffic/Readonly Sources**: 1-3 connections
- **Archive/Backup Sources**: 1-2 connections

### Configuration Example

```python
"sources": {
    "primary": {
        "path": "bot.db",
        "pool-size": 10  # High traffic, many concurrent operations
    },
    "archive": {
        "path": "archive.db",
        "readonly": True,
        "pool-size": 2   # Low traffic, occasional reads
    }
}
```

### Performance Considerations

- **More connections** = Higher memory usage, better concurrency
- **Fewer connections** = Lower memory usage, potential bottlenecks
- **Readonly sources** can use smaller pools (no write contention)

## Readonly Sources

Readonly sources provide safe access to databases that should not be modified.

### Use Cases

1. **Archive Databases**: Old chat data that shouldn't change
2. **External Bot Databases**: Read from other bots without risk
3. **Backup Databases**: Query backups without modification risk
4. **Shared Databases**: Multiple bots reading from same source

### Configuration

```python
"archive": {
    "path": "archive.db",
    "readonly": True  # Enables readonly mode
}
```

### Behavior

- **Read Operations**: Work normally
- **Write Operations**: Raise `ValueError` with clear error message
- **SQLite PRAGMA**: `query_only = ON` is set automatically
- **Connection Pool**: Can use smaller pool sizes

### Example Error

```python
# This will raise ValueError
db.addChatMessage(chatId=-1001234567890, ...)  # If chat mapped to readonly source

# Error message:
# ValueError: Cannot perform write operation on readonly source 'archive', dood!
# This source is configured as readonly.
```

## Migration Guide

### From Single Database to Multi-Source

#### Step 1: Current Single-Database Configuration

```python
# Old way
db = DatabaseWrapper(dbPath="bot.db", maxConnections=5, timeout=30.0)
```

#### Step 2: Create Multi-Source Configuration

```python
# New way - backward compatible
config = {
    "default": "primary",
    "sources": {
        "primary": {
            "path": "bot.db",  # Same database file
            "readonly": False,
            "pool-size": 5,
            "timeout": 30.0
        }
    }
}

db = DatabaseWrapper(config=config)
```

#### Step 3: Add Additional Sources (Optional)

```python
config = {
    "default": "primary",
    "sources": {
        "primary": {
            "path": "bot.db",
            "readonly": False,
            "pool-size": 5,
            "timeout": 30.0
        },
        "archive": {
            "path": "archive.db",
            "readonly": True,
            "pool-size": 3,
            "timeout": 30.0
        }
    },
    "chatMapping": {
        # Map old chats to archive
        -1001234567890: "archive"
    }
}

db = DatabaseWrapper(config=config)
```

### Migration Checklist

- [ ] Backup existing database
- [ ] Create multi-source configuration
- [ ] Test with single source first
- [ ] Add additional sources gradually
- [ ] Update chat mappings as needed
- [ ] Monitor performance and adjust pool sizes
- [ ] Verify readonly protection works

## Best Practices

### 1. Start Simple

Begin with a single source, then add more as needed:

```python
# Start here
config = {
    "default": "primary",
    "sources": {
        "primary": {"path": "bot.db"}
    }
}
```

### 2. Use Readonly for Safety

Mark sources readonly when appropriate:

```python
"archive": {
    "path": "archive.db",
    "readonly": True  # Prevents accidental modifications
}
```

### 3. Optimize Pool Sizes

Adjust based on actual usage:

```python
"primary": {"pool-size": 10},  # High traffic
"archive": {"pool-size": 2}    # Low traffic, readonly
```

### 4. Explicit dataSource for Cross-Source Queries

When querying specific sources, be explicit:

```python
# Query archive explicitly
old_messages = db.getChatMessages(chatId=123, dataSource="archive")

# Query all sources
all_chats = db.getAllGroupChats(dataSource=None)  # Aggregates from all sources
```

### 5. Monitor and Adjust

- Monitor connection pool usage
- Adjust pool sizes based on actual load
- Use readonly sources to reduce write contention
- Consider separate databases for different chat types

## Troubleshooting

### Common Issues and Solutions

#### Issue: "Cannot perform write operation on readonly source"

**Cause**: Attempting to write to a readonly source

**Solution**: 
- Check if chat is mapped to readonly source
- Remove chat from mapping or change source to writable
- Use explicit `dataSource` parameter to write to different source

```python
# Check mapping
if chatId in db._chatMapping:
    print(f"Chat {chatId} mapped to: {db._chatMapping[chatId]}")

# Override mapping
db.addChatMessage(chatId=chatId, dataSource="primary", ...)
```

#### Issue: "Source 'name' not found in configuration"

**Cause**: Referencing non-existent data source

**Solution**:
- Verify source name in configuration
- Check for typos in source names
- Ensure source is defined in `sources` section

```python
# List available sources
print(f"Available sources: {list(db._sources.keys())}")
```

#### Issue: Database locked errors

**Cause**: Insufficient connection pool size or timeout too low

**Solution**:
- Increase `pool-size` for affected source
- Increase `timeout` value
- Check for long-running transactions

```python
"primary": {
    "path": "bot.db",
    "pool-size": 10,  # Increase from 5
    "timeout": 60.0   # Increase from 30.0
}
```

#### Issue: Slow cross-source queries

**Cause**: Querying many sources with large datasets

**Solution**:
- Use explicit `dataSource` when possible
- Optimize database indexes
- Consider denormalizing data
- Use smaller result limits

```python
# Instead of querying all sources
messages = db.getChatMessages(chatId=123)  # Queries mapped source

# Be explicit when needed
messages = db.getChatMessages(chatId=123, dataSource="primary")
```

## Examples

See the [`configs/examples/`](../configs/examples/) directory for complete configuration examples:

- [`multi-source-basic.toml`](../configs/examples/multi-source-basic.toml) - Simple two-source setup
- [`multi-source-advanced.toml`](../configs/examples/multi-source-advanced.toml) - Complex multi-source configuration
- [`multi-source-readonly-only.toml`](../configs/examples/multi-source-readonly-only.toml) - Read-only bot setup
- [`multi-source-migration.toml`](../configs/examples/multi-source-migration.toml) - Migration from single database

### Quick Start Example

```python
from internal.database import DatabaseWrapper

# Simple two-source setup
config = {
    "default": "primary",
    "sources": {
        "primary": {
            "path": "bot.db",
            "readonly": False,
            "pool-size": 5
        },
        "archive": {
            "path": "archive.db",
            "readonly": True,
            "pool-size": 2
        }
    },
    "chatMapping": {
        -1001234567890: "archive"  # Old chat
    }
}

db = DatabaseWrapper(config=config)

# Read from primary (default)
messages = db.getChatMessages(chatId=-1009876543210)

# Read from archive (via mapping)
old_messages = db.getChatMessages(chatId=-1001234567890)

# Read from specific source (explicit)
backup_messages = db.getChatMessages(chatId=123, dataSource="archive")

# Cross-source aggregation
all_chats = db.getAllGroupChats()  # Queries all sources, deduplicates results
```

## API Reference

### DatabaseWrapper Constructor

```python
DatabaseWrapper(
    dbPath: Optional[str] = None,
    maxConnections: int = 5,
    timeout: float = 30.0,
    config: Optional[Dict[str, Any]] = None
)
```

**Parameters:**
- `dbPath`: Single database path (legacy mode, mutually exclusive with config)
- `maxConnections`: Default max connections per source
- `timeout`: Default timeout per source in seconds
- `config`: Multi-source config dict with 'sources', 'chatMapping', 'default'

**Raises:**
- `ValueError`: If neither or both dbPath and config provided

### Read Methods with dataSource Support

All read methods accept an optional `dataSource` parameter:

```python
# Examples
getChatMessages(chatId, dataSource="archive")
getChatInfo(chatId, dataSource="primary")
getUserChats(userId, dataSource=None)  # Queries all sources
getAllGroupChats(dataSource="primary")
getMediaAttachment(mediaId, dataSource="backup")
```

### Write Methods

Write methods use routing but validate against readonly sources:

```python
# Routed based on chatId mapping
addChatMessage(chatId=123, ...)  # Uses mapping or default

# Explicit source (must be writable)
addChatMessage(chatId=123, dataSource="primary", ...)
```

## Security Considerations

### Readonly Source Benefits

1. **Prevents Accidental Modifications**: Archive data stays intact
2. **Safe Cross-Bot Access**: Read from other bots without risk
3. **Backup Protection**: Query backups without modification
4. **Audit Trail**: Readonly sources can't be tampered with

### Recommendations

- Always use `readonly=True` for:
  - Archive databases
  - External bot databases
  - Backup databases
  - Shared databases
  
- Use separate sources for:
  - Production vs test data
  - Different bot instances
  - Different security levels

## Performance Tips

### Connection Pool Sizing

```python
# High-traffic primary database
"primary": {"pool-size": 10}

# Medium-traffic secondary database
"secondary": {"pool-size": 5}

# Low-traffic archive (readonly)
"archive": {"pool-size": 2}
```

### Query Optimization

```python
# Good: Explicit source for known location
messages = db.getChatMessages(chatId=123, dataSource="primary")

# Less efficient: Cross-source aggregation
all_messages = db.getChatMessages(chatId=123)  # Checks mapping, may query multiple sources
```

### Timeout Tuning

```python
# Fast local database
"local": {"timeout": 5.0}

# Network-mounted database
"network": {"timeout": 60.0}

# Archive database (can be slower)
"archive": {"timeout": 30.0}
```

## Advanced Use Cases

### Use Case 1: Archive Old Chats

Move inactive chats to a separate archive database:

```python
config = {
    "default": "primary",
    "sources": {
        "primary": {"path": "bot.db"},
        "archive": {"path": "archive.db", "readonly": True}
    },
    "chatMapping": {
        -1001111111111: "archive",  # Inactive chat 1
        -1002222222222: "archive",  # Inactive chat 2
    }
}
```

### Use Case 2: Cross-Bot Communication

Read from another bot's database:

```python
config = {
    "default": "my_bot",
    "sources": {
        "my_bot": {"path": "my_bot.db"},
        "other_bot": {
            "path": "/shared/other_bot.db",
            "readonly": True  # Never write to other bot's DB
        }
    }
}

# Read from other bot
other_messages = db.getChatMessages(chatId=123, dataSource="other_bot")
```

### Use Case 3: Test/Production Segregation

```python
config = {
    "default": "production",
    "sources": {
        "production": {"path": "prod.db"},
        "test": {"path": "test.db"}
    },
    "chatMapping": {
        -1001111111111: "test",  # Test chat
        -1002222222222: "test",  # Another test chat
    }
}
```

### Use Case 4: Performance Distribution

```python
config = {
    "default": "db1",
    "sources": {
        "db1": {"path": "db1.db", "pool-size": 10},
        "db2": {"path": "db2.db", "pool-size": 10},
        "db3": {"path": "db3.db", "pool-size": 10}
    },
    "chatMapping": {
        # Distribute chats across databases
        -1001111111111: "db1",
        -1002222222222: "db2",
        -1003333333333: "db3",
    }
}
```

## Configuration Validation

The [`DatabaseWrapper`](../internal/database/wrapper.py:94) validates configuration on initialization:

### Validation Rules

1. **At least one source** must be defined
2. **Default source** must exist in sources
3. **Each source** must have a `path` parameter
4. **Chat mappings** reference existing sources (warnings for invalid)
5. **Readonly sources** reject write operations

### Validation Errors

```python
# Error: No sources
config = {"sources": {}}
# ValueError: Multi-source config must contain at least one source, dood!

# Error: Default source doesn't exist
config = {"default": "missing", "sources": {"primary": {"path": "bot.db"}}}
# ValueError: Default source 'missing' not found in sources configuration, dood!

# Error: Source missing path
config = {"sources": {"primary": {"readonly": True}}}
# ValueError: Source 'primary' missing required 'path' field, dood!
```

## See Also

- [Multi-Source Database Architecture Design](design/multi-source-database-architecture-v2.md)
- [DatabaseWrapper Implementation](../internal/database/wrapper.py)
- [Configuration Examples](../configs/examples/)
- [Migration System Documentation](../internal/database/migrations/README.md)

---

**Note**: This documentation covers the multi-source database feature implemented in Phase 1-4 of the multi-source database architecture project. For implementation details, see the design document and source code.