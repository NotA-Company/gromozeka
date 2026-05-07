# Multi-Source Database Configuration Guide

**Version:** 1.0  
**Date:** 2025-11-30  
**Status:** Production Ready

## Table of Contents

1. [Overview](#overview)
2. [Configuration Structure](#configuration-structure)
3. [Provider Configuration](#provider-configuration)
4. [Chat Mapping](#chat-mapping)
5. [Connection Management](#connection-management)
6. [Readonly Providers](#readonly-providers)
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

- **3-Tier Routing**: Intelligent routing with dataSource parameter → chatMapping → defaultProvider
- **Readonly Protection**: Providers can be marked readonly to prevent accidental writes
- **Provider-Based Architecture**: Flexible provider system supporting sqlite3 and sqlink
- **Cross-Provider Aggregation**: Read methods can query multiple providers
- **Repository Pattern**: Organized access through specialized repositories

## Configuration Structure

Multi-source configuration is provided via a dictionary passed to [`Database.__init__()`](../internal/database/database.py:92):

```python
from internal.database import Database

config = {
    "default": "primary",  # Default provider name
    "providers": {
        "primary": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "bot.db",
                "readOnly": False,
                "timeout": 30.0
            }
        },
        "archive": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "archive.db",
                "readOnly": True,
                "timeout": 30.0
            }
        }
    },
    "chatMapping": {
        -1001234567890: "archive",  # Map specific chats to providers
        -1009876543210: "primary"
    }
}

db = Database(config=config)
```

### TOML Configuration

In TOML configuration files:

```toml
[database]
default = "primary"

[database.providers.primary]
provider = "sqlite3"

[database.providers.primary.parameters]
dbPath = "bot.db"
readOnly = false
timeout = 30.0

[database.providers.archive]
provider = "sqlite3"

[database.providers.archive.parameters]
dbPath = "archive.db"
readOnly = true
timeout = 30.0

[database.chatMapping]
-1001234567890 = "archive"
-1009876543210 = "primary"
```

## Provider Configuration

Each data provider requires specific configuration parameters:

### Required Parameters

- **`provider`**: Provider type identifier (e.g., `"sqlite3"` or `"sqlink"`)
  - Example: `"sqlite3"`, `"sqlink"`

- **`parameters.dbPath`**: Path to the SQLite database file (relative or absolute)
  - Example: `"bot.db"`, `"/shared/archive.db"`, `"../backups/old.db"`

### Optional Parameters

- **`parameters.readOnly`**: Boolean flag for readonly mode (default: `false`)
  - `true`: Only SELECT queries allowed, writes raise `ValueError`
  - `false`: Full read/write access
  
- **`parameters.timeout`**: Connection timeout in seconds (default: 30.0)
  - How long to wait for database lock before failing
  
- **`parameters.useWal`**: Enable WAL mode for better concurrency (default: `true`)
  - `true`: Better concurrent read/write performance
  - `false`: Standard journaling mode

### Provider Configuration Examples

```python
# Minimal configuration (uses defaults)
"primary": {
    "provider": "sqlite3",
    "parameters": {
        "dbPath": "bot.db"
    }
}

# Full configuration
"archive": {
    "provider": "sqlite3",
    "parameters": {
        "dbPath": "archive.db",
        "readOnly": True,
        "timeout": 10.0,
        "useWal": True
    }
}

# External bot database (readonly)
"other_bot": {
    "provider": "sqlite3",
    "parameters": {
        "dbPath": "/shared/other_bot.db",
        "readOnly": True,
        "timeout": 5.0
    }
}
```

## Chat Mapping

Chat mapping routes specific chats to specific data providers. This is useful for:

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
# Uses archive provider (from chatMapping)
messages = db.chatMessages.getMessages(chatId=-1001234567890)

# Overrides mapping, uses primary provider explicitly
messages = db.chatMessages.getMessages(chatId=-1001234567890, dataSource="primary")

# No chatId, uses default provider
settings = db.chatSettings.getSettings()
```

## Connection Management

Each data provider manages its own connections for thread-safe concurrent access. Connection pooling is handled internally by the provider implementation.

### Performance Considerations

- **WAL mode** (`useWal: true`) provides better concurrent read/write performance
- **Timeout settings** control how long to wait for database locks
- **Readonly providers** have no write contention
- **Provider-specific optimizations** are handled by the chosen provider (sqlite3/sqlink)

## Readonly Providers

Readonly providers provide safe access to databases that should not be modified.

### Use Cases

1. **Archive Databases**: Old chat data that shouldn't change
2. **External Bot Databases**: Read from other bots without risk
3. **Backup Databases**: Query backups without modification risk
4. **Shared Databases**: Multiple bots reading from same source

### Configuration

```python
"archive": {
    "provider": "sqlite3",
    "parameters": {
        "dbPath": "archive.db",
        "readOnly": True  # Enables readonly mode
    }
}
```

### Behavior

- **Read Operations**: Work normally
- **Write Operations**: Raise `ValueError` with clear error message
- **Provider-specific**: Each provider implements readonly protection appropriately

### Example Error

```python
# This will raise ValueError
db.chatMessages.addMessage(chatId=-1001234567890, ...)  # If chat mapped to readonly provider

# Error message:
# ValueError: Cannot perform write operation on readonly source 'archive'.
# This source is configured as readonly.
```

## Migration Guide

### From Single Database to Multi-Source

#### Step 1: Current Single-Database Configuration

```python
# Old way
from internal.database import Database

config = {
    "default": "default",
    "providers": {
        "default": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "bot.db",
                "readOnly": False,
                "timeout": 30.0
            }
        }
    }
}

db = Database(config=config)
```

#### Step 2: Create Multi-Source Configuration

```python
# New way - backward compatible
config = {
    "default": "primary",
    "providers": {
        "primary": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "bot.db",  # Same database file
                "readOnly": False,
                "timeout": 30.0
            }
        }
    }
}

db = Database(config=config)
```

#### Step 3: Add Additional Providers (Optional)

```python
config = {
    "default": "primary",
    "providers": {
        "primary": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "bot.db",
                "readOnly": False,
                "timeout": 30.0
            }
        },
        "archive": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "archive.db",
                "readOnly": True,
                "timeout": 30.0
            }
        }
    },
    "chatMapping": {
        # Map old chats to archive
        -1001234567890: "archive"
    }
}

db = Database(config=config)
```

### Migration Checklist

- [ ] Backup existing database
- [ ] Create multi-source configuration
- [ ] Test with single provider first
- [ ] Add additional providers gradually
- [ ] Update chat mappings as needed
- [ ] Monitor performance and adjust timeout settings
- [ ] Verify readonly protection works

## Best Practices

### 1. Start Simple

Begin with a single provider, then add more as needed:

```python
# Start here
config = {
    "default": "primary",
    "providers": {
        "primary": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "bot.db"
            }
        }
    }
}
```

### 2. Use Readonly for Safety

Mark providers readonly when appropriate:

```python
"archive": {
    "provider": "sqlite3",
    "parameters": {
        "dbPath": "archive.db",
        "readOnly": True  # Prevents accidental modifications
    }
}
```

### 3. Choose the Right Provider

Select the appropriate provider for your use case:

```python
# SQLite3 provider (default, stable)
"primary": {
    "provider": "sqlite3",
    "parameters": {
        "dbPath": "bot.db",
        "useWal": True  # Better concurrency
    }
}

# SQLink provider (alternative implementation)
"secondary": {
    "provider": "sqlink",
    "parameters": {
        "dbPath": "secondary.db"
    }
}
```

### 4. Explicit dataSource for Cross-Provider Queries

When querying specific providers, be explicit:

```python
# Query archive explicitly
old_messages = db.chatMessages.getMessages(chatId=123, dataSource="archive")

# Query all providers
all_chats = db.chatInfo.getAllGroupChats(dataSource=None)  # Aggregates from all providers
```

### 5. Monitor and Adjust

- Monitor database performance
- Adjust timeout settings based on actual load
- Use readonly providers to reduce write contention
- Consider separate databases for different chat types

## Troubleshooting

### Common Issues and Solutions

#### Issue: "Cannot perform write operation on readonly source"

**Cause**: Attempting to write to a readonly provider

**Solution**:
- Check if chat is mapped to readonly provider
- Remove chat from mapping or change provider to writable
- Use explicit `dataSource` parameter to write to different provider

```python
# Check mapping
if chatId in db.manager.config["chatMapping"]:
    print(f"Chat {chatId} mapped to: {db.manager.config['chatMapping'][chatId]}")

# Override mapping
db.chatMessages.addMessage(chatId=chatId, dataSource="primary", ...)
```

#### Issue: "Source 'name' not found in configuration"

**Cause**: Referencing non-existent data provider

**Solution**:
- Verify provider name in configuration
- Check for typos in provider names
- Ensure provider is defined in `providers` section

```python
# List available providers
print(f"Available providers: {list(db.manager.config['providers'].keys())}")
```

#### Issue: Database locked errors

**Cause**: Timeout too low or high contention

**Solution**:
- Increase `timeout` value for affected provider
- Enable WAL mode for better concurrency
- Check for long-running transactions

```python
"primary": {
    "provider": "sqlite3",
    "parameters": {
        "dbPath": "bot.db",
        "timeout": 60.0,   # Increase from 30.0
        "useWal": True     # Enable WAL mode
    }
}
```

#### Issue: Slow cross-provider queries

**Cause**: Querying many providers with large datasets

**Solution**:
- Use explicit `dataSource` when possible
- Optimize database indexes
- Consider denormalizing data
- Use smaller result limits

```python
# Instead of querying all providers
messages = db.chatMessages.getMessages(chatId=123)  # Queries mapped provider

# Be explicit when needed
messages = db.chatMessages.getMessages(chatId=123, dataSource="primary")
```

## Examples

See the [`docs/examples/`](../docs/examples/) directory for complete configuration examples:

- [`multi-source-basic.toml`](../docs/examples/multi-source-basic.toml) - Simple two-provider setup
- [`multi-source-advanced.toml`](../docs/examples/multi-source-advanced.toml) - Complex multi-provider configuration
- [`multi-source-readonly-only.toml`](../docs/examples/multi-source-readonly-only.toml) - Read-only bot setup
- [`multi-source-migration.toml`](../docs/examples/multi-source-migration.toml) - Migration from single database

### Quick Start Example

```python
from internal.database import Database

# Simple two-provider setup
config = {
    "default": "primary",
    "providers": {
        "primary": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "bot.db",
                "readOnly": False,
                "timeout": 30.0
            }
        },
        "archive": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "archive.db",
                "readOnly": True,
                "timeout": 30.0
            }
        }
    },
    "chatMapping": {
        -1001234567890: "archive"  # Old chat
    }
}

db = Database(config=config)

# Read from primary (default)
messages = db.chatMessages.getMessages(chatId=-1009876543210)

# Read from archive (via mapping)
old_messages = db.chatMessages.getMessages(chatId=-1001234567890)

# Read from specific provider (explicit)
backup_messages = db.chatMessages.getMessages(chatId=123, dataSource="archive")

# Cross-provider aggregation
all_chats = db.chatInfo.getAllGroupChats()  # Queries all providers, deduplicates results
```

## API Reference

### Database Constructor

```python
Database(
    config: DatabaseManagerConfig
)
```

**Parameters:**
- `config`: DatabaseManagerConfig containing providers configuration, chat mapping, and default provider settings

**Raises:**
- `ValueError`: If no providers, no default source, or default source not found

### DatabaseManager

The [`DatabaseManager`](../internal/database/manager.py:39) handles provider routing and connection management:

```python
async def getProvider(
    *,
    chatId: Optional[int] = None,
    dataSource: Optional[str] = None,
    readonly: bool = False
) -> BaseSQLProvider
```

**Parameters:**
- `chatId`: Optional chat ID for provider mapping lookup
- `dataSource`: Optional explicit data source name to use
- `readonly`: Whether the operation is read-only (default: False)

**Returns:**
- `BaseSQLProvider`: The SQL provider instance for database operations

**Raises:**
- `ValueError`: If write operation attempted on readonly provider

### Repository Methods

All repository methods accept an optional `dataSource` parameter for explicit provider selection:

```python
# Examples using repositories
db.chatMessages.getMessages(chatId, dataSource="archive")
db.chatInfo.getChatInfo(chatId, dataSource="primary")
db.chatUsers.getUserChats(userId, dataSource=None)  # Queries all providers
db.chatInfo.getAllGroupChats(dataSource="primary")
db.mediaAttachments.getAttachment(mediaId, dataSource="backup")
```

### Write Methods

Write methods use routing but validate against readonly providers:

```python
# Routed based on chatId mapping
db.chatMessages.addMessage(chatId=123, ...)  # Uses mapping or default

# Explicit provider (must be writable)
db.chatMessages.addMessage(chatId=123, dataSource="primary", ...)
```

## Security Considerations

### Readonly Provider Benefits

1. **Prevents Accidental Modifications**: Archive data stays intact
2. **Safe Cross-Bot Access**: Read from other bots without risk
3. **Backup Protection**: Query backups without modification
4. **Audit Trail**: Readonly providers can't be tampered with

### Recommendations

- Always use `readOnly=True` for:
  - Archive databases
  - External bot databases
  - Backup databases
  - Shared databases
  
- Use separate providers for:
  - Production vs test data
  - Different bot instances
  - Different security levels

## Performance Tips

### Provider Selection

```python
# SQLite3 with WAL mode for high concurrency
"primary": {
    "provider": "sqlite3",
    "parameters": {
        "dbPath": "bot.db",
        "useWal": True
    }
}

# SQLink for alternative implementation
"secondary": {
    "provider": "sqlink",
    "parameters": {
        "dbPath": "secondary.db"
    }
}
```

### Query Optimization

```python
# Good: Explicit provider for known location
messages = db.chatMessages.getMessages(chatId=123, dataSource="primary")

# Less efficient: Cross-provider aggregation
all_messages = db.chatMessages.getMessages(chatId=123)  # Checks mapping, may query multiple providers
```

### Timeout Tuning

```python
# Fast local database
"local": {
    "provider": "sqlite3",
    "parameters": {
        "dbPath": "local.db",
        "timeout": 5.0
    }
}

# Network-mounted database
"network": {
    "provider": "sqlite3",
    "parameters": {
        "dbPath": "/shared/network.db",
        "timeout": 60.0
    }
}

# Archive database (can be slower)
"archive": {
    "provider": "sqlite3",
    "parameters": {
        "dbPath": "archive.db",
        "timeout": 30.0
    }
}
```

## Advanced Use Cases

### Use Case 1: Archive Old Chats

Move inactive chats to a separate archive database:

```python
config = {
    "default": "primary",
    "providers": {
        "primary": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "bot.db"
            }
        },
        "archive": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "archive.db",
                "readOnly": True
            }
        }
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
    "providers": {
        "my_bot": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "my_bot.db"
            }
        },
        "other_bot": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "/shared/other_bot.db",
                "readOnly": True  # Never write to other bot's DB
            }
        }
    }
}

# Read from other bot
other_messages = db.chatMessages.getMessages(chatId=123, dataSource="other_bot")
```

### Use Case 3: Test/Production Segregation

```python
config = {
    "default": "production",
    "providers": {
        "production": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "prod.db"
            }
        },
        "test": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "test.db"
            }
        }
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
    "providers": {
        "db1": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "db1.db",
                "useWal": True
            }
        },
        "db2": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "db2.db",
                "useWal": True
            }
        },
        "db3": {
            "provider": "sqlink",
            "parameters": {
                "dbPath": "db3.db"
            }
        }
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

The [`DatabaseManager`](../internal/database/manager.py:39) validates configuration on initialization:

### Validation Rules

1. **At least one provider** must be defined
2. **Default provider** must exist in providers
3. **Each provider** must have a `provider` type and `parameters` dict
4. **Chat mappings** reference existing providers (warnings for invalid)
5. **Readonly providers** reject write operations

### Validation Errors

```python
# Error: No providers
config = {"providers": {}}
# ValueError: No providers found in configuration

# Error: Default provider doesn't exist
config = {"default": "missing", "providers": {"primary": {"provider": "sqlite3", "parameters": {"dbPath": "bot.db"}}}}
# ValueError: Default source 'missing' not found in configuration, please check your configuration and try again.

# Error: Provider missing required fields
config = {"providers": {"primary": {"parameters": {"dbPath": "bot.db"}}}}
# ValueError: SQLProviderConfig is missing the required 'provider' key
```

## See Also

- [Multi-Source Database Architecture Design](design/multi-source-database-architecture-v2.md)
- [Database Implementation](../internal/database/database.py)
- [DatabaseManager Implementation](../internal/database/manager.py)
- [Configuration Examples](../docs/examples/)
- [Migration System Documentation](../internal/database/migrations/README.md)

---

**Note**: This documentation covers the multi-source database feature with the new repository pattern architecture. For implementation details, see the design document and source code.