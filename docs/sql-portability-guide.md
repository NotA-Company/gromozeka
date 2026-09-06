---
category: reference
---

# SQL Portability Guide: Cross-RDBMS Compatibility Analysis

## Executive Summary

This document provides a comprehensive analysis of SQL query portability issues identified in the Gromozeka project's database layer (`internal/database/**`). The analysis focuses on ensuring code compatibility between SQLite (current implementation) and target RDBMS systems (MySQL and PostgreSQL) to enable future deployment flexibility.

### Key Statistics

- **Total Files Analyzed**: 12 repository files
- **Total SQL Queries Examined**: 85+ queries
- **Compatibility Issues Identified**: 13 issues (see Issues #1–#13 below)
- **Affected Tables**: 15+ database tables
- **Target RDBMS**: MySQL 8.0+, PostgreSQL 14+

### Risk Assessment

| Severity | Count | Description |
|----------|-------|-------------|
| **Critical** | 1 | Requires immediate attention - will cause runtime errors |
| **High** | 3 | Significant functionality impact - requires modification |
| **Medium** | 6 | Minor compatibility issues - should be addressed |
| **Low** | 3 | Negligible impact - documented for completeness |

### Current State

The database layer currently uses SQLite-specific syntax that is not directly compatible with MySQL and PostgreSQL. The primary areas of concern are:

1. **Upsert Operations**: SQLite's `ON CONFLICT` syntax differs from MySQL's `ON DUPLICATE KEY UPDATE` and PostgreSQL's `ON CONFLICT`
2. **Parameter Binding**: Mixed use of positional (`?`) and named (`:name`) parameters
3. **Date/Time Functions**: SQLite's `CURRENT_TIMESTAMP` behavior differs from other RDBMS
4. **String Functions**: Case sensitivity and function name variations
5. **LIMIT Clauses**: Placement and syntax differences

---

## Detailed Compatibility Issues

### Issue #1: ON CONFLICT Syntax Incompatibility

**Severity**: Critical  
**Files Affected**: 8 files  
**Impact**: All upsert operations will fail  
**Status**: ✅ **RESOLVED** - Portable `upsert()` method implemented on `BaseSQLProvider` (and every concrete provider). All repositories route through `provider.upsert(...)` instead of hand-written `ON CONFLICT`.

#### Problem Description: ON CONFLICT Syntax Incompatibility

SQLite uses `ON CONFLICT` for upsert operations, but the syntax differs significantly between RDBMS:

- **SQLite**: `ON CONFLICT(column) DO UPDATE SET ...`
- **MySQL**: `ON DUPLICATE KEY UPDATE ...` (requires UNIQUE/PRIMARY key)
- **PostgreSQL**: `ON CONFLICT(column) DO UPDATE SET ...` (similar to SQLite but with different conflict target syntax)

#### Affected Locations: ON CONFLICT Upserts

| File | Line | Query Type |
|------|------|------------|
| [`internal/database/repositories/cache.py`](/internal/database/repositories/cache.py:85) | 85 | Cache storage upsert |
| [`internal/database/repositories/cache.py`](/internal/database/repositories/cache.py:213) | 213 | Cache entry upsert |
| [`internal/database/repositories/chat_messages.py`](/internal/database/repositories/chat_messages.py:149) | 149 | Chat stats upsert |
| [`internal/database/repositories/chat_messages.py`](/internal/database/repositories/chat_messages.py:160) | 160 | Chat user stats upsert |
| [`internal/database/repositories/chat_users.py`](/internal/database/repositories/chat_users.py:74) | 74 | Chat user upsert |
| [`internal/database/repositories/chat_settings.py`](/internal/database/repositories/chat_settings.py:65) | 65 | Chat settings upsert |
| [`internal/database/repositories/chat_info.py`](/internal/database/repositories/chat_info.py:71) | 71 | Chat info upsert |
| [`internal/database/repositories/media_attachments.py`](/internal/database/repositories/media_attachments.py:61) | 61 | Media group upsert |

#### Example Code: ON CONFLICT Upserts

##### Current Upsert Syntax and the ExcludedValue Marker

**Current (SQLite)**:
```sql
INSERT INTO cache_storage (namespace, key, value, updated_at)
VALUES (:namespace, :key, :value, CURRENT_TIMESTAMP)
ON CONFLICT(namespace, key) DO UPDATE SET
    value = :value,
    updated_at = CURRENT_TIMESTAMP
```

**Recommended Solution**:

Add an `upsert` method to each provider implementation that receives table, dict of values, and on-conflict expressions. This approach allows handling complex expressions like `messages_count = messages_count + 1`.

**Special Value for Excluded Values**:

To handle the DB-specific syntax for referencing excluded values (e.g., `excluded.column` in PostgreSQL/SQLite, `VALUES(column)` in MySQL), introduce a special constant that providers can recognize and translate appropriately:

```python
# lib/db/providers/base.py
class ExcludedValue:
    """Special marker to indicate a column should be set to the excluded value.
    
    This allows provider-specific translation:
    - SQLite/PostgreSQL: excluded.column
    - MySQL: VALUES(column)
    
    Usage:
        update_expressions = {
            "value": ExcludedValue(),  # Will be translated to excluded.value or VALUES(value)
            "count": "count + 1"  # Custom expression
        }
    """
    def __init__(self, column: Optional[str] = None):
        """Initialize excluded value marker.
        
        Args:
            column: Optional column name. If None, uses the key from update_expressions dict.
        """
        self.column = column
    
    def __repr__(self) -> str:
        return f"ExcludedValue({self.column})"
```

##### Provider Implementation: SQLite

**Provider Implementations** (illustrative — see
[`lib/db/providers/`](/lib/db/providers/) for the real
code; parameter names match the `BaseSQLProvider.upsert` camelCase signature):

```python
# lib/db/providers/sqlite3.py
async def upsert(
    self,
    table: str,
    values: Dict[str, Any],
    conflictColumns: List[str],
    updateExpressions: Optional[Dict[str, Any]] = None,
) -> bool:
    """Execute SQLite-specific upsert operation.
    
    Args:
        table: Table name
        values: Dictionary of column names and values to insert
        conflictColumns: List of columns that define the conflict target
        updateExpressions: Optional dict of column -> expression for UPDATE clause.
                          If None, all non-conflict columns are updated with their values.
                          Supports complex expressions like "messages_count = messages_count + 1"
                          or ExcludedValue() to set to excluded value.
    
    Returns:
        True if successful
    """
    if updateExpressions is None:
        updateExpressions = {col: ExcludedValue() for col in values.keys() if col not in conflictColumns}
    
    # Translate ExcludedValue to SQLite syntax
    translatedExpressions = {}
    for col, expr in updateExpressions.items():
        if isinstance(expr, ExcludedValue):
            columnName = expr.column if expr.column else col
            translatedExpressions[col] = f"excluded.{columnName}"
        else:
            translatedExpressions[col] = expr
    
    colsStr = ", ".join(values.keys())
    placeholders = ", ".join([f":{col}" for col in values.keys()])
    conflictStr = ", ".join(conflictColumns)
    updateStr = ", ".join([f"{col} = {expr}" for col, expr in translatedExpressions.items()])
    
    query = f"""
        INSERT INTO {table} ({colsStr})
        VALUES ({placeholders})
        ON CONFLICT({conflictStr}) DO UPDATE SET
            {updateStr}
    """
    
    return await self.execute(query, values)
```

##### Provider Implementation: MySQL

```python
# lib/db/providers/mysql.py
async def upsert(
    self,
    table: str,
    values: Dict[str, Any],
    conflictColumns: List[str],
    updateExpressions: Optional[Dict[str, Any]] = None,
) -> bool:
    """Execute MySQL-specific upsert operation.
    
    Args:
        table: Table name
        values: Dictionary of column names and values to insert
        conflictColumns: List of columns that define the conflict target (must be UNIQUE/PRIMARY key)
        updateExpressions: Optional dict of column -> expression for UPDATE clause.
                          If None, all non-conflict columns are updated with their values.
                          Supports complex expressions like "messages_count = messages_count + 1"
                          or ExcludedValue() to set to excluded value.
    
    Returns:
        True if successful
    """
    if updateExpressions is None:
        updateExpressions = {col: ExcludedValue() for col in values.keys() if col not in conflictColumns}
    
    # Translate ExcludedValue to MySQL syntax
    translatedExpressions = {}
    for col, expr in updateExpressions.items():
        if isinstance(expr, ExcludedValue):
            columnName = expr.column if expr.column else col
            translatedExpressions[col] = f"VALUES({columnName})"
        else:
            translatedExpressions[col] = expr
    
    colsStr = ", ".join(values.keys())
    placeholders = ", ".join([f":{col}" for col in values.keys()])
    updateStr = ", ".join([f"{col} = {expr}" for col, expr in translatedExpressions.items()])
    
    query = f"""
        INSERT INTO {table} ({colsStr})
        VALUES ({placeholders})
        ON DUPLICATE KEY UPDATE
            {updateStr}
    """
    
    return await self.execute(query, values)
```

##### Provider Implementation: PostgreSQL

```python
# lib/db/providers/postgresql.py
async def upsert(
    self,
    table: str,
    values: Dict[str, Any],
    conflictColumns: List[str],
    updateExpressions: Optional[Dict[str, Any]] = None,
) -> bool:
    """Execute PostgreSQL-specific upsert operation.
    
    Args:
        table: Table name
        values: Dictionary of column names and values to insert
        conflictColumns: List of columns that define the conflict target
        updateExpressions: Optional dict of column -> expression for UPDATE clause.
                          If None, all non-conflict columns are updated with their values.
                          Supports complex expressions like "messages_count = messages_count + 1"
                          or ExcludedValue() to set to excluded value.
    
    Returns:
        True if successful
    """
    if updateExpressions is None:
        updateExpressions = {col: ExcludedValue() for col in values.keys() if col not in conflictColumns}
    
    # Translate ExcludedValue to PostgreSQL syntax
    translatedExpressions = {}
    for col, expr in updateExpressions.items():
        if isinstance(expr, ExcludedValue):
            columnName = expr.column if expr.column else col
            translatedExpressions[col] = f"EXCLUDED.{columnName}"
        else:
            translatedExpressions[col] = expr
    
    colsStr = ", ".join(values.keys())
    placeholders = ", ".join([f":{col}" for col in values.keys()])
    conflictStr = ", ".join(conflictColumns)
    updateStr = ", ".join([f"{col} = {expr}" for col, expr in translatedExpressions.items()])
    
    query = f"""
        INSERT INTO {table} ({colsStr})
        VALUES ({placeholders})
        ON CONFLICT({conflictStr}) DO UPDATE SET
            {updateStr}
    """
    
    return await self.execute(query, values)
```

##### Usage Examples and Benefits

**Usage Examples**:

```python
from lib.db.providers.base import ExcludedValue

# Simple upsert - update all non-conflict columns with excluded values
# NOTE: kwargs are camelCase (conflictColumns / updateExpressions) to match
# the BaseSQLProvider.upsert signature. Snake_case will raise TypeError.
await sqlProvider.upsert(
    table="cache_storage",
    values={
        "namespace": namespace,
        "key": key,
        "value": value,
        "updated_at": datetime.datetime.now(datetime.UTC),
    },
    conflictColumns=["namespace", "key"],
)

# Complex upsert with custom expressions and ExcludedValue
await sqlProvider.upsert(
    table="chat_users",
    values={
        "chat_id": chatId,
        "user_id": userId,
        "username": username,
        "full_name": fullName,
        "updated_at": datetime.datetime.now(datetime.UTC),
    },
    conflictColumns=["chat_id", "user_id"],
    updateExpressions={
        "messages_count": "messages_count + 1",  # Custom expression
        "updated_at": ExcludedValue(),  # Use excluded value for this column
        "username": ExcludedValue("username"),  # Explicit column name
    },
)

# Mix of excluded values and custom expressions
await sqlProvider.upsert(
    table="cache_storage",
    values={
        "namespace": namespace,
        "key": key,
        "value": value,
        "updated_at": datetime.datetime.now(datetime.UTC),
        "access_count": 0,
    },
    conflictColumns=["namespace", "key"],
    updateExpressions={
        "value": ExcludedValue(),  # Update with new value
        "updated_at": ExcludedValue(),  # Update with new timestamp
        "access_count": "access_count + 1",  # Increment counter
    },
)
```

**Benefits of ExcludedValue Approach**:

1. **Database-agnostic**: Developers use `ExcludedValue()` without worrying about DB-specific syntax
2. **Type-safe**: Clear distinction between custom expressions and excluded value references
3. **Flexible**: Supports both implicit (column from dict key) and explicit (specified column name) usage
4. **Maintainable**: Changes to DB-specific syntax only require updating provider implementations
5. **Consistent**: Same API across all providers, reducing cognitive load

---

### Issue #2: Mixed Parameter Binding Styles

**Severity**: High  
**Files Affected**: 10 files  
**Impact**: Query execution failures, parameter binding errors

#### Problem Description: Mixed Parameter Binding

The codebase inconsistently uses both positional (`?`) and named (`:name`) parameter binding:

- **Positional**: `WHERE chat_id = ? AND user_id = ?`
- **Named**: `WHERE chat_id = :chatId AND user_id = :userId`

While both styles work in SQLite, MySQL and PostgreSQL have different preferences and limitations.

#### Affected Locations: Mixed Parameter Binding

| File | Line | Binding Style |
|------|------|---------------|
| [`internal/database/repositories/chat_messages.py`](/internal/database/repositories/chat_messages.py:140) | 140 | Positional (`?`) |
| [`internal/database/repositories/chat_messages.py`](/internal/database/repositories/chat_messages.py:148) | 148 | Positional (`?`) |
| [`internal/database/repositories/chat_messages.py`](/internal/database/repositories/chat_messages.py:152) | 152 | Positional (`?`) |
| [`internal/database/repositories/chat_users.py`](/internal/database/repositories/chat_users.py:110) | 110 | Positional (`?`) |
| [`internal/database/repositories/chat_settings.py`](/internal/database/repositories/chat_settings.py:64) | 64 | Positional (`?`) |
| [`internal/database/repositories/media_attachments.py`](/internal/database/repositories/media_attachments.py:233) | 233 | Positional (`?`) |
| [`internal/database/repositories/cache.py`](/internal/database/repositories/cache.py:84) | 84 | Named (`:name`) |
| [`internal/database/repositories/cache.py`](/internal/database/repositories/cache.py:174) | 174 | Named (`:name`) |

#### Example Code: Mixed Parameter Binding

**Current (Mixed)**:
```python
# Positional parameters
await sqlProvider.execute(
    """
    UPDATE chat_users
    SET messages_count = messages_count + 1,
        updated_at = CURRENT_TIMESTAMP
    WHERE chat_id = ? AND user_id = ?
    """,
    (chatId, userId),
)

# Named parameters
await sqlProvider.execute(
    """
    INSERT INTO cache_storage
        (namespace, key, value, updated_at)
    VALUES
        (:namespace, :key, :value, CURRENT_TIMESTAMP)
    """,
    {
        "namespace": namespace,
        "key": key,
        "value": value,
    },
)
```

**Recommended Solution**:

Standardize on named parameters throughout the codebase for better readability and cross-RDBMS compatibility:

```python
# Standardized approach using named parameters
await sqlProvider.execute(
    """
    UPDATE chat_users
    SET messages_count = messages_count + 1,
        updated_at = CURRENT_TIMESTAMP
    WHERE chat_id = :chatId AND user_id = :userId
    """,
    {
        "chatId": chatId,
        "userId": userId,
    },
)
```

**Migration Strategy**:

1. Update all positional parameter queries to use named parameters
2. Update parameter tuples to dictionaries
3. Ensure parameter names match column names for consistency
4. Add linting rules to enforce named parameter usage

---

### Issue #3: CURRENT_TIMESTAMP Behavior Differences

**Severity**: Medium
**Files Affected**: 12 files
**Impact**: Incorrect timestamp values, timezone issues

**Status**: ✅ **RESOLVED** - Portable SQL patterns implemented in migration_013 and all repository code

#### Problem Description: CURRENT_TIMESTAMP Behavior

`CURRENT_TIMESTAMP` behaves differently across RDBMS:

- **SQLite**: Returns UTC time as string without timezone info
- **MySQL**: Returns session timezone (configurable, often local time)
- **PostgreSQL**: Returns transaction start time with timezone info

This can cause inconsistencies in timestamp comparisons and data integrity issues.

#### Solution Implemented: CURRENT_TIMESTAMP Removal

**Migration 013**: Removed all `DEFAULT CURRENT_TIMESTAMP` from schema definitions
- All timestamp columns are now `TIMESTAMP NOT NULL` without defaults
- Applications must explicitly provide `created_at` and `updated_at` values
- Ensures consistent timestamp handling across all RDBMS

**Repository Code**: All timestamp generation moved to Python application code
- Uses `datetime.datetime.now(datetime.UTC)` for consistent UTC timestamps
- No RDBMS-specific timestamp functions in application queries
- Portable across all supported providers

#### Affected Locations (Historical)

| File | Line | Context |
|------|------|---------|
| [`internal/database/repositories/cache.py`](/internal/database/repositories/cache.py:84) | 84 | Cache storage insert |
| [`internal/database/repositories/cache.py`](/internal/database/repositories/cache.py:212) | 212 | Cache entry insert |
| [`internal/database/repositories/chat_messages.py`](/internal/database/repositories/chat_messages.py:139) | 139 | Chat user update |
| [`internal/database/repositories/chat_users.py`](/internal/database/repositories/chat_users.py:73) | 73 | Chat user insert |
| [`internal/database/repositories/chat_settings.py`](/internal/database/repositories/chat_settings.py:64) | 64 | Chat settings insert |

#### Example Code: CURRENT_TIMESTAMP Handling

**Before (Problematic)**:
```sql
INSERT INTO cache_storage (namespace, key, value, updated_at)
VALUES (:namespace, :key, :value, CURRENT_TIMESTAMP)
```

**After (Resolved)**:
```python
import datetime

# Generate timestamp in Python (cross-RDBMS compatible)
current_time = datetime.datetime.now(datetime.UTC)

# Use in queries
await sqlProvider.execute(
    """
    INSERT INTO cache_storage
        (namespace, key, value, updated_at)
    VALUES
        (:namespace, :key, :value, :updatedAt)
    """,
    {
        "namespace": namespace,
        "key": key,
        "value": value,
        "updatedAt": current_time,
    },
)
```

#### Implementation Details

**Migration**: [`migration_013_remove_timestamp_defaults.py`](../internal/database/migrations/versions/migration_013_remove_timestamp_defaults.py:1)
- Removes `DEFAULT CURRENT_TIMESTAMP` from all timestamp columns
- Updates schema to require explicit timestamp values
- Ensures cross-RDBMS compatibility

**Repository Pattern**: All repositories now use `datetime.datetime.now(datetime.UTC)` for timestamps
- Consistent UTC timestamp generation
- Cross-RDBMS portable
- No RDBMS-specific SQL functions needed

---

### Issue #4: String Case Sensitivity in WHERE Clauses

**Severity**: Medium
**Files Affected**: 3 files
**Impact**: Case-sensitive comparisons may fail unexpectedly
**Status**: ✅ **RESOLVED** - Portable `getCaseInsensitiveComparison()` and `getLikeComparison()` methods implemented

#### Problem Description: Case Sensitivity in WHERE Clauses

String comparisons behave differently across RDBMS:

- **SQLite**: Case-insensitive by default for ASCII, case-sensitive for Unicode
- **MySQL**: Case-insensitive by default (depends on collation)
- **PostgreSQL**: Case-sensitive by default

This affects username lookups and other string-based queries.

#### Affected Locations: Case-Sensitive Lookups

| File | Line | Query |
|------|------|-------|
| [`internal/database/repositories/chat_users.py`](/internal/database/repositories/chat_users.py:182) | 182 | Username lookup |
| [`internal/database/repositories/spam.py`](/internal/database/repositories/spam.py:149) | 149 | Spam text search |

#### Example Code: Case-Insensitive Comparison

**Current**:
```sql
SELECT * FROM chat_users
WHERE
    chat_id = :chatId
    AND username = :username
```

**Recommended Solution**:

**Status**: ✅ Implemented — Use `getCaseInsensitiveComparison()` from provider

Use the provider's `getCaseInsensitiveComparison()` method for explicit case-insensitive equality comparisons:

```python
# Usage in repository code
comparison = sqlProvider.getCaseInsensitiveComparison("username", "username")
query = f"""
    SELECT * FROM chat_users
    WHERE
        chat_id = :chatId
        AND {comparison}
"""

# Example from actual implementation (divinations repository)
layoutNameComparison = sqlProvider.getCaseInsensitiveComparison("name_en", "layoutName")
query = f"""
    SELECT * FROM divination_layouts
    WHERE system_id = :systemId
        AND {layoutNameComparison}
"""
```

**Provider Implementations**:

- **SQLite**: `LOWER({column}) = LOWER(:{param})` — portable, works for both ASCII and Unicode
- **MySQL**: `{column} COLLATE utf8mb4_general_ci = :{param}` — efficient, uses collation for case-insensitive matching
- **PostgreSQL**: `LOWER({column}) = LOWER(:{param})` — portable, standard approach

**For Pattern Matching**: Use `getLikeComparison()` instead (see below section).

---

### Case-Insensitive LIKE Pattern Matching

**Severity**: Medium
**Files Affected**: Base provider abstract method, MySQL/PostgreSQL implementations
**Impact**: Pattern matching queries may fail to match across cases
**Status**: ✅ **RESOLVED** - Portable `getLikeComparison()` method implemented

#### Problem Description: LIKE Case Sensitivity

LIKE pattern matching with case-insensitive matching behaves differently across RDBMS:
- **SQLite**: `LIKE` is case-insensitive for ASCII by default, case-sensitive for Unicode
- **MySQL**: `LIKE` case-sensitivity depends on column collation (can vary by configuration)
- **PostgreSQL**: `LIKE` is case-sensitive by default

This affects text search queries where you want to match patterns regardless of case (e.g., searching for layout names).

#### Solution Implemented: LIKE Case-Insensitive Matching

**Base Provider Abstract Method**: Added `getLikeComparison()` to `BaseSQLProvider` to abstract RDBMS-specific syntax:

```python
# lib/db/providers/base.py
@abstractmethod
def getLikeComparison(self, column: str, param: str) -> str:
    """Get RDBMS-specific case-insensitive LIKE comparison.

    Args:
        column: The column name to compare.
        param: The parameter name to use in the comparison.

    Returns:
        A SQL expression string for case-insensitive LIKE comparison.

    Raises:
        NotImplementedError: Must be overridden by subclasses.
    """
    raise NotImplementedError
```

**Provider Implementations**:

```python
# lib/db/providers/mysql.py
def getLikeComparison(self, column: str, param: str) -> str:
    """Get MySQL-specific case-insensitive LIKE comparison expression.

    Generates a SQL expression that performs a case-insensitive pattern
    match using the ``LIKE`` operator. Uses ``LOWER()`` on both sides
    for reliable case-insensitive matching across MySQL configurations.

    Args:
        column: The column name to compare against.
        param: The parameter name to use in the comparison (with ``:`` prefix).

    Returns:
        A SQL expression string for case-insensitive LIKE comparison, formatted as
        ``"LOWER({column}) LIKE LOWER(:{param})"``.

    Note:
        Using ``LOWER()`` on both sides prevents index usage on most MySQL
        configurations. For high-performance queries on large datasets,
        consider adding a functional index on ``LOWER(column)`` or using a
        case-insensitive collation column with a direct ``LIKE`` comparison.
    """
    return f"LOWER({column}) LIKE LOWER(:{param})"

# lib/db/providers/postgresql.py
def getLikeComparison(self, column: str, param: str) -> str:
    """Get PostgreSQL-specific case-insensitive LIKE comparison expression.

    Uses ``LOWER()`` on both sides of the LIKE operator for case-insensitive
    pattern matching.

    Args:
        column: The column name to compare against.
        param: The parameter name to use in the comparison (with ``:`` prefix).

    Returns:
        A SQL expression string for case-insensitive LIKE comparison, formatted as
        ``"LOWER({column}) LIKE LOWER(:{param})"``.
    """
    return f"LOWER({column}) LIKE LOWER(:{param})"

# lib/db/providers/sqlink.py (SQLite)
def getLikeComparison(self, column: str, param: str) -> str:
    """Get SQLite-specific case-insensitive LIKE comparison expression.

    Uses ``LOWER()`` on both sides of the LIKE operator to ensure
    case-insensitive matching for Unicode (SQLite's default behavior varies).

    Args:
        column: The column name to compare against.
        param: The parameter name to use in the comparison (with ``:`` prefix).

    Returns:
        A SQL expression string for case-insensitive LIKE comparison, formatted as
        ``"LOWER({column}) LIKE LOWER(:{param})"``.
    """
    return f"LOWER({column}) LIKE LOWER(:{param})"
```

**Usage Example**:

```python
# Pattern matching with wildcards
layoutNameComparison = sqlProvider.getLikeComparison("name_en", "layoutName")
query = f"""
    SELECT * FROM divination_layouts
    WHERE system_id = :systemId
        AND {layoutNameComparison}
"""
params = {
    "systemId": "tarot",
    "layoutName": "%celtic%"
}

async with sqlProvider.cursor() as cursor:
    await cursor.execute(query, params)
    results = await cursor.fetchall()
```

**Performance Considerations**:

- **MySQL**: The `LOWER() LIKE LOWER()` pattern cannot use standard indexes. For high-performance queries on large tables, consider:
  1. Adding a functional index: `CREATE INDEX idx_name_en_lower ON divination_layouts(LOWER(name_en))`
  2. Using a column with case-insensitive collation and direct `LIKE` comparison
- **PostgreSQL**: Functional indexes on `LOWER(column)` are supported and recommended for performance
- **SQLite**: Performance impact is minimal; no index optimization needed for most use cases

**Trade-off**:
The portable implementation prioritizes consistency across RDBMS and configurability over optimal performance. If you encounter performance issues with LIKE queries on large MySQL tables, create a functional index on `LOWER(column)` or switch to a case-insensitive collation column for that specific query.

---

### Issue #5: LIMIT Clause Placement

**Severity**: Low  
**Files Affected**: 5 files  
**Impact**: Query syntax errors in some RDBMS

#### Problem Description: LIMIT Clause Placement

While all three RDBMS support `LIMIT`, the placement and combination with `OFFSET` can vary:

- **SQLite/PostgreSQL**: `LIMIT n OFFSET m` or `LIMIT n, m` (SQLite only)
- **MySQL**: `LIMIT n OFFSET m` or `LIMIT n, m`

The current code uses `LIMIT n` which is compatible, but future pagination may need attention.

#### Affected Locations: LIMIT Clause Placement

| File | Line | Context |
|------|------|---------|
| [`internal/database/repositories/chat_users.py`](/internal/database/repositories/chat_users.py:225) | 225 | User list limit |
| [`internal/database/repositories/chat_messages.py`](/internal/database/repositories/chat_messages.py:233) | 233 | Message list limit |

#### Example Code: LIMIT Pagination

**Current**:
```python
query = f"""
    SELECT * FROM chat_users
    WHERE chat_id = :chatId
    ORDER BY updated_at DESC
    LIMIT :limit
"""
```

**Recommended Solution**:

Create a pagination helper for consistent LIMIT/OFFSET handling:

```python
# lib/db/providers/base.py
def applyPagination(self, query: str, limit: Optional[int], 
                    offset: Optional[int] = 0) -> str:
    """Apply RDBMS-specific pagination to query."""
    if limit is None:
        return query
    
    provider_type = self.getProviderType()
    
    if provider_type == "sqlite":
        return f"{query} LIMIT {limit} OFFSET {offset}"
    elif provider_type in ["mysql", "postgresql"]:
        return f"{query} LIMIT {limit} OFFSET {offset}"
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")

# Usage
query = """
    SELECT * FROM chat_users
    WHERE chat_id = :chatId
    ORDER BY updated_at DESC
"""
query = sqlProvider.applyPagination(query, limit=10, offset=0)
```

---

### Issue #6: Boolean Type Handling

**Severity**: Medium  
**Files Affected**: 4 files  
**Impact**: Type conversion errors, incorrect boolean comparisons

#### Problem Description: Boolean Type Handling

Boolean types are handled differently:

- **SQLite**: No native boolean type, uses INTEGER (0/1)
- **MySQL**: Uses TINYINT(1) for boolean
- **PostgreSQL**: Native BOOLEAN type

This affects queries that use boolean literals or comparisons.

#### Affected Locations: Boolean Type Handling

| File | Line | Context |
|------|------|---------|
| [`internal/database/repositories/chat_messages.py`](/internal/database/repositories/chat_messages.py:211) | 211 | Message category filter |
| [`internal/database/repositories/cache.py`](/internal/database/repositories/cache.py:287) | 287 | Cache type filter |

#### Example Code: Boolean Type Handling

**Current**:
```python
params = {
    "messageCategory": None if messageCategory is None else True,
}
```

**Recommended Solution**:

Use explicit integer values for boolean compatibility:

```python
# Convert boolean to integer for cross-RDBMS compatibility
params = {
    "messageCategory": None if messageCategory is None else 1,
}

# Or use a helper function
def toDbBoolean(value: Optional[bool]) -> Optional[int]:
    """Convert Python boolean to database-compatible integer."""
    if value is None:
        return None
    return 1 if value else 0
```

---

### Issue #7: JSON Data Type Support

**Severity**: Low  
**Files Affected**: 3 files  
**Impact**: Limited JSON functionality, performance degradation

#### Problem Description: JSON Data Type Support

JSON handling varies significantly:

- **SQLite**: No native JSON type, stores as TEXT
- **MySQL**: JSON type with JSON functions
- **PostgreSQL**: JSONB type with advanced indexing

Current implementation stores JSON as TEXT strings.

#### Affected Locations: JSON Data Type Support

| File | Line | Context |
|------|------|---------|
| [`internal/database/repositories/chat_messages.py`](/internal/database/repositories/chat_messages.py:60) | 60 | Message metadata |
| [`internal/database/repositories/media_attachments.py`](/internal/database/repositories/media_attachments.py:81) | 81 | Media metadata |

#### Example Code: JSON Storage

**Current**:
```python
metadata: str = ""  # JSON as string
```

**Recommended Solution**:

Create a JSON abstraction layer:

```python
# lib/db/providers/base.py
import json

def serializeJson(self, data: Any) -> str:
    """Serialize Python object to JSON string."""
    return json.dumps(data)

def deserializeJson(self, json_str: str) -> Any:
    """Deserialize JSON string to Python object."""
    return json.loads(json_str)

def getJsonExtractFunction(self, column: str, path: str) -> str:
    """Get RDBMS-specific JSON extraction function."""
    provider_type = self.getProviderType()
    
    if provider_type == "sqlite":
        return f"json_extract({column}, '{path}')"
    elif provider_type == "mysql":
        return f"JSON_EXTRACT({column}, '{path}')"
    elif provider_type == "postgresql":
        return f"{column}->>'{path}'"
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")
```

---

### Issue #8: AUTO_INCREMENT vs SERIAL

**Severity**: High  
**Files Affected**: Migration files  
**Impact**: Schema creation failures  
**Status**: ✅ **RESOLVED** - No migration in the current tree uses `AUTOINCREMENT` / `AUTO_INCREMENT` / `SERIAL`. Every primary key is either a composite natural key, a single natural key, or an app-generated UUID/ULID stored as `TEXT PRIMARY KEY NOT NULL`.

#### Problem Description: AUTO_INCREMENT vs SERIAL

Auto-incrementing primary keys use different syntax:

- **SQLite**: `INTEGER PRIMARY KEY AUTOINCREMENT`
- **MySQL**: `INT AUTO_INCREMENT`
- **PostgreSQL**: `SERIAL` or `BIGSERIAL`

Because all three dialects spell it differently, `AUTOINCREMENT` is **forbidden** in Gromozeka migrations.

#### Affected Locations: AUTO_INCREMENT vs SERIAL

All migration files under [`internal/database/migrations/versions/`](/internal/database/migrations/versions/) were audited. The current `migration_001_initial_schema.py` defines every table with one of the portable PK shapes below — no `AUTOINCREMENT` appears anywhere in the migration tree.

#### Example Code: Primary Key Strategies

**Forbidden (SQLite-only, breaks MySQL/PostgreSQL)**:
```sql
CREATE TABLE chat_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    ...
)
```

**Current portable shape (composite natural key)** — actual `migration_001_initial_schema.py`:
```sql
CREATE TABLE chat_users (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    ...
    PRIMARY KEY (chat_id, user_id)
)
```

#### Recommended Solution: Portable Primary Keys

No `getAutoIncrementType()` helper is provided on `BaseSQLProvider` — by design. Pick a portable PK strategy instead (in order of preference):

1. **Composite natural key** from columns the app already has — e.g.
   `PRIMARY KEY (chat_id, message_id)`, `PRIMARY KEY (namespace, key)`,
   `PRIMARY KEY (chat_id, user_id)`. This is the dominant pattern.
2. **Single natural key** when the row is identified by one external ID
   (e.g. `file_unique_id TEXT PRIMARY KEY`, `chat_id INTEGER PRIMARY KEY`).
3. **Application-generated UUID / ULID** stored as
   `TEXT PRIMARY KEY NOT NULL` (see `delayed_tasks.id` in `migration_001`
   / `migration_013`). Generate the value in Python before insert; never
   delegate ID generation to the database.

---

### Issue #9: TEXT Type Length Limits

**Severity**: Low  
**Files Affected**: Migration files  
**Impact**: Data truncation in some RDBMS

#### Problem Description: TEXT Type Length Limits

TEXT type behavior differs:

- **SQLite**: Unlimited TEXT length
- **MySQL**: TEXT (65,535 bytes), MEDIUMTEXT (16MB), LONGTEXT (4GB)
- **PostgreSQL**: TEXT unlimited

#### Recommended Solution: TEXT Type Selection

Use appropriate TEXT types based on expected data size:

```python
# lib/db/providers/base.py
def getTextType(self, max_length: Optional[int] = None) -> str:
    """Get RDBMS-specific TEXT type."""
    provider_type = self.getProviderType()
    
    if provider_type == "sqlite":
        return "TEXT"
    elif provider_type == "mysql":
        if max_length is None or max_length <= 65535:
            return "TEXT"
        elif max_length <= 16777215:
            return "MEDIUMTEXT"
        else:
            return "LONGTEXT"
    elif provider_type == "postgresql":
        return "TEXT"
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")
```

---

### Issue #10: Index Creation Syntax

**Severity**: Medium  
**Files Affected**: Migration files  
**Impact**: Index creation failures

#### Problem Description: Index Creation Syntax

Index creation syntax varies slightly:

- **SQLite/PostgreSQL**: `CREATE INDEX idx_name ON table(column)`
- **MySQL**: Same syntax, but index name length limited to 64 characters

#### Recommended Solution: Standard Index Syntax

Skip index creation syntax handling for now.

**Rationale**:
- Index creation syntax is similar across SQLite, MySQL, and PostgreSQL
- The standard `CREATE INDEX idx_name ON table(column)` syntax works on all three
- MySQL's 64-character index name limit is rarely an issue in practice
- Can be addressed later if specific issues arise

**Current Approach**:
Continue using standard SQL index creation syntax:
```sql
CREATE INDEX idx_table_column ON table(column)
CREATE UNIQUE INDEX idx_table_column ON table(column)
```

---

### Issue #11: Transaction Isolation Levels

**Severity**: Medium  
**Files Affected**: Database manager  
**Impact**: Concurrency issues, data inconsistency

#### Problem Description: Transaction Isolation Levels

Transaction isolation levels differ:

- **SQLite**: SERIALIZABLE only
- **MySQL**: READ UNCOMMITTED, READ COMMITTED, REPEATABLE READ, SERIALIZABLE
- **PostgreSQL**: READ COMMITTED, REPEATABLE READ, SERIALIZABLE

#### Recommended Solution: Transaction Isolation Levels

Skip transaction isolation level handling for now.

**Rationale**:
- Current application doesn't require specific isolation levels
- SQLite's SERIALIZABLE default is sufficient for most use cases
- MySQL and PostgreSQL defaults are adequate
- Can be implemented later if specific isolation requirements emerge

**Current Approach**:
Use default transaction isolation levels provided by each RDBMS:
- SQLite: SERIALIZABLE (only option)
- MySQL: REPEATABLE READ (default)
- PostgreSQL: READ COMMITTED (default)

---

### Issue #12: Foreign Key Constraint Enforcement

**Severity**: High  
**Files Affected**: Database initialization  
**Impact**: Data integrity issues

#### Problem Description: Foreign Key Enforcement

Foreign key enforcement differs:

- **SQLite**: Disabled by default, must be enabled with PRAGMA
- **MySQL**: Enabled by default
- **PostgreSQL**: Enabled by default

#### Recommended Solution: Foreign Key Enforcement

Add a parameter to all SQLite-based providers to enable foreign key constraints, off by default for backward compatibility.

```python
# lib/db/providers/sqlite3.py
class SQLite3Provider(BaseSQLProvider):
    def __init__(self, connection_string: str, enable_foreign_keys: bool = False):
        """Initialize SQLite3 provider.
        
        Args:
            connection_string: Database connection string
            enable_foreign_keys: Enable foreign key constraints (default: False for backward compatibility)
        """
        super().__init__(connection_string)
        self.enableForeignKeys = enable_foreign_keys
    
    async def initialize(self) -> None:
        """Initialize database connection and settings."""
        await super().initialize()
        
        if self.enableForeignKeys:
            await self.execute("PRAGMA foreign_keys = ON")

# lib/db/providers/sqlink.py
class SqlinkProvider(BaseSQLProvider):
    def __init__(self, connection_string: str, enable_foreign_keys: bool = False):
        """Initialize Sqlink provider.
        
        Args:
            connection_string: Database connection string
            enable_foreign_keys: Enable foreign key constraints (default: False for backward compatibility)
        """
        super().__init__(connection_string)
        self.enableForeignKeys = enable_foreign_keys
    
    async def initialize(self) -> None:
        """Initialize database connection and settings."""
        await super().initialize()
        
        if self.enableForeignKeys:
            await self.execute("PRAGMA foreign_keys = ON")

# Usage in configuration
# configs/00-defaults/providers.toml
[[sources]]
name = "source1"
type = "sqlite3"
connection_string = "file:./storage/source1.db"
enable_foreign_keys = true  # Enable foreign keys for this source
```

**Benefits**:
- Backward compatible (disabled by default)
- Explicit opt-in for foreign key enforcement
- Consistent behavior across SQLite-based providers
- MySQL and PostgreSQL already have foreign keys enabled by default

---

### Issue #13: Connection Management Strategy

**Severity**: Medium
**Files Affected**: All database providers
**Impact**: Resource usage, performance, data integrity

#### Problem Description: Connection Management Strategy

Different database providers have different optimal connection management strategies:

- **SQLite (file-based)**: Can connect on demand, but in-memory databases need immediate connection
- **MySQL**: Connection pooling is built-in, but establishing connections has overhead
- **PostgreSQL**: Connection pooling is built-in, but establishing connections has overhead
- **SQLink**: Lightweight async client, can connect on demand

#### Recommended Solution: Connection Management Strategy

Add a `keepConnection` parameter to all database providers to control when connections are established.

**Parameter values:**
- `true` — Connect immediately when provider is created
- `false` — Connect on first query (lazy connection)
- `null` — Auto-detect based on provider type and configuration

**Provider-specific defaults:**
- **SQLite3**: `null` → Auto-detect: `true` for in-memory (`:memory:`), `false` for file-based
- **SQLink**: `null` → Defaults to `false` (connect on demand)
- **MySQL**: `null` → Defaults to `false` (connect on demand)
- **PostgreSQL**: `null` → Defaults to `false` (connect on demand)

**Implementation:**

```python
# lib/db/providers/sqlite3.py
class SQLite3Provider(BaseSQLProvider):
    def __init__(self, dbPath: str, keepConnection: Optional[bool] = None, ...):
        """Initialize SQLite3 provider.
        
        Args:
            dbPath: Database file path or ":memory:" for in-memory database
            keepConnection: Connect immediately (true), on demand (false), or auto-detect (null)
        """
        # Special handling for in-memory databases to prevent data loss
        self.keepConnection: bool = dbPath == ":memory:" if keepConnection is None else keepConnection

# lib/db/providers/sqlink.py
class SQLinkProvider(BaseSQLProvider):
    def __init__(self, dbPath: str, keepConnection: Optional[bool] = None, ...):
        """Initialize SQLink provider.
        
        Args:
            dbPath: Database file path
            keepConnection: Connect immediately (true), on demand (false), or auto-detect (null)
        """
        self.keepConnection: bool = keepConnection if keepConnection is not None else False

# lib/db/providers/mysql.py
class MySQLProvider(BaseSQLProvider):
    def __init__(self, host: str, port: int, user: str, password: str, database: str,
                 keepConnection: Optional[bool] = None, ...):
        """Initialize MySQL provider.
        
        Args:
            host: Database host
            port: Database port
            user: Database user
            password: Database password
            database: Database name
            keepConnection: Connect immediately (true), on demand (false), or auto-detect (null)
        """
        self.keepConnection: bool = keepConnection if keepConnection is not None else False

# lib/db/providers/postgresql.py
class PostgreSQLProvider(BaseSQLProvider):
    def __init__(self, host: str, port: int, user: str, password: str, database: str,
                 keepConnection: Optional[bool] = None, ...):
        """Initialize PostgreSQL provider.
        
        Args:
            host: Database host
            port: Database port
            user: Database user
            password: Database password
            database: Database name
            keepConnection: Connect immediately (true), on demand (false), or auto-detect (null)
        """
        self.keepConnection: bool = keepConnection if keepConnection is not None else False
```

**Configuration example:**

```toml
[database.providers.default.parameters]
keepConnection = false  # Connect on demand (default for file-based DBs)

[database.providers.readonly.parameters]
keepConnection = true  # Connect immediately (good for readonly replicas)

[database.providers.inmemory.parameters]
dbPath = ":memory:"
keepConnection = true  # Required for in-memory databases
```

**Migration connection management:**

The migration system now relies on the provider's `keepConnection` parameter for connection management. No explicit `await sqlProvider.connect()` call is made during migration. Providers with `keepConnection=true` connect immediately before migrations run, while providers with `keepConnection=false` connect on first query during migration.

**Benefits:**
- Flexible connection management based on use case
- Optimal resource usage for file-based databases (connect on demand)
- Prevents data loss for in-memory databases (connect immediately)
- Better performance for readonly replicas (connect immediately)
- Consistent behavior across all providers

**Use cases:**
- **File-based SQLite**: Use `keepConnection=false` to save resources
- **In-memory SQLite**: Use `keepConnection=true` to prevent data loss
- **Readonly replicas**: Use `keepConnection=true` for faster query response
- **Production MySQL/PostgreSQL**: Use `keepConnection=false` to avoid unnecessary connections
- **Development/testing**: Use `keepConnection=true` for immediate feedback

---

## Native Vector Search Portability

**Status**: ✅ Implemented on `BaseSQLProvider` (default implementations raise `NotImplementedError`; providers with vector extensions override)

Native vector similarity search is exposed through four hooks on
[`BaseSQLProvider`](/lib/db/providers/base.py) plus a small type
surface. Providers that load a vector extension (e.g. sqlite-vec, pgvector)
override these; providers without vector support inherit the default
`NotImplementedError`-raising implementations.

### API Surface

All of the following live in `lib/db/providers/base.py`:

| Member | Kind | Notes |
|--------|------|-------|
| `isVectorSearchSupported()` | `async` method | Default returns `False`. Override to return `True` after confirming the extension is operational. |
| `vectorSearch(*, table, vectorColumn, returnColumns, queryVector, k, filterClause="", filterParams=None, distanceMetric=COSINE)` | `async` method | Provider-specific KNN query. Returns `list[VectorSearchResult]` ordered by distance ascending. |
| `listTables(likePattern="%")` | `async` method | Native introspection. Used to discover vec0 tables for cleanup and to check dimension-specific tables. |
| `createVectorTable(tableName, columns)` | `async` method | Maps `VectorColumnDef` list to native DDL. At least one column must have `columnType=VECTOR`. |
| `VectorSearchResult` | `TypedDict` | `{rowKey: dict[str, Any], distance: float}`. |
| `VectorDistanceMetric` | `StrEnum` | `COSINE`, `L2`. |
| `VectorColumnType` | `StrEnum` | `TEXT`, `INTEGER`, `FLOAT`, `BLOB`, `VECTOR`. |
| `VectorColumnDef` | `TypedDict` | `{name, columnType, isPartitionKey?, vectorDimension?, distanceMetric?}`. |

### Portability Contracts

1. **Capability check first.** Always gate calls with
   `await sqlProvider.isVectorSearchSupported()` — never assume a provider
   supports vector search.
2. **`queryVector` is raw bytes**, pre-serialised to the provider's expected
   binary format (e.g. `array.array("f", floats).tobytes()` for sqlite-vec
   float32). This avoids an extra copy/conversion inside the provider.
3. **`filterClause` must use `:named` placeholders** referencing keys in
   `filterParams` — same portability rule as every other query in this guide.
   Example: `"chat_id = :chatId AND model = :modelName"`.
4. **`distanceMetric` is validated at call time**; unsupported metrics raise
   `ValueError`, not `NotImplementedError`.
5. **`returnColumns` populate `VectorSearchResult.rowKey`**, not raw row data
   — the dict maps each requested return column to its string value. For
   composite primary keys, all key columns are present.

### Usage Example

```python
from lib.db.providers.base import VectorDistanceMetric

if not await sqlProvider.isVectorSearchSupported():
    raise RuntimeError("Provider does not support native vector search")

import array
queryVec = array.array("f", embeddingFloats).tobytes()

results = await sqlProvider.vectorSearch(
    table="vec_message_embeddings_384",
    vectorColumn="embedding",
    returnColumns=["chat_id", "message_id"],
    queryVector=queryVec,
    k=10,
    filterClause="chat_id = :chatId AND model = :modelName",
    filterParams={"chatId": chatId, "modelName": modelName},
    distanceMetric=VectorDistanceMetric.COSINE,
)

for hit in results:
    # hit["rowKey"] == {"chat_id": "42", "message_id": "abc"}
    # hit["distance"]  == raw cosine distance (lower = more similar)
    similarity = 1.0 - hit["distance"]
    ...
```

### What This Means for MySQL / PostgreSQL

- **PostgreSQL**: when the `postgresql` provider is wired up, it should
  delegate to `pgvector` (`<=>` operator for cosine, `<->` for L2).
- **MySQL**: MySQL 9.0+ adds a native `VECTOR` type; until then MySQL
  remains `isVectorSearchSupported() == False`.
- **SQLite**: the only backend wired up in production today; the sqlite-vec
  extension provides the vec0 virtual table.

See [`docs/llm/architecture.md`](llm/architecture.md) (vector search ADR) for
the higher-level design and the chat-embeddings consumer that drives this API.

---

## Implementation Strategy

### Phase 1: Foundation (Week 1-2)

**Objective**: Create provider-specific implementations for database operations

1. **Add Provider-Specific Methods**
   - Add `upsert()` method to each provider (sqlite3, sqlink, mysql, postgresql)
   - Add `applyPagination()` method to each provider
   - Add `getTextType()` method to each provider
   - Add `enable_foreign_keys` parameter to SQLite-based providers

2. **Create Utility Functions**
   - Add `getCurrentTimestamp()` helper in [`lib/db/utils.py`](../lib/db/utils.py)
   - Review and update `convertToSQLite()` function for cross-RDBMS compatibility

3. **Update Provider Implementations**
  - Extend [`lib/db/providers/sqlite3.py`](/lib/db/providers/sqlite3.py)
  - Extend [`lib/db/providers/sqlink.py`](/lib/db/providers/sqlink.py)
  - Create [`lib/db/providers/mysql.py`](/lib/db/providers/mysql.py)
  - Create [`lib/db/providers/postgresql.py`](/lib/db/providers/postgresql.py)

### Phase 2: Migration (Week 3-4)

**Objective**: Update existing queries to use provider-specific methods

1. **Update Upsert Operations**
   - Replace all `ON CONFLICT` with provider `upsert()` method
   - Update 8 affected files
   - Test each upsert operation including complex expressions

2. **Standardize Parameter Binding**
   - Convert all positional parameters to named parameters
   - Update 10 affected files
   - Update parameter tuples to dictionaries

3. **Fix Timestamp Handling**
   - Replace `CURRENT_TIMESTAMP` with `getCurrentTimestamp()` helper
   - Update 12 affected files
   - Ensure timezone consistency

 4. **Address String Comparisons** ✅ **DONE**
    - ✅ Add case-insensitive comparison helpers (`getCaseInsensitiveComparison()`)
    - ✅ Add case-insensitive LIKE helpers (`getLikeComparison()`)
    - ℹ️ Implementation in base provider, MySQL, PostgreSQL, SQLite providers
    - ℹ️ Used in divinations repository for layout name searches

### Phase 3: Schema Migration (Week 5-6)

**Objective**: Review and document database schema for cross-RDBMS compatibility

1. **Review Migration Files**
   - Check for AUTO_INCREMENT usage across all migration files
   - Document any auto-increment specific syntax found
   - Assess portability of current schema definitions

2. **Create Documentation**
   - Document findings about AUTO_INCREMENT usage
   - Create recommendations for future schema changes
   - Note any RDBMS-specific schema elements that may need attention

3. **No Migration Scripts Required**
   - SQLite-to-anything migration scripts are not needed at this time
   - Focus on documentation and assessment rather than implementation
   - Defer actual schema changes until specific migration requirements are identified

### Phase 4: Testing (Week 7-8)

**Objective**: Comprehensive testing with SQLite

1. **Unit Tests**
   - Test each repository method
   - Test with SQLite
   - Mock database connections

2. **Integration Tests**
   - Test full application workflows
   - Test multi-source database routing
   - Test transaction handling

3. **Schema Documentation**
   - Document AUTO_INCREMENT usage findings
   - Create recommendations for future schema changes
   - Note any RDBMS-specific schema elements
   - Review and finalize schema documentation

### Skipped Items (Deferred to Future)

The following items have been intentionally skipped for now:
- **Issue #7: JSON Data Type Support** - Use TEXT for JSON everywhere (portable)
- **Issue #10: Index Creation Syntax** - Standard SQL syntax works across all RDBMS
- **Issue #11: Transaction Isolation Levels** - Default levels are sufficient

---

## Migration Checklist

### Pre-Migration Preparation

- [ ] **Backup existing databases**
  - [ ] Create full backup of SQLite databases
  - [ ] Test backup restoration
  - [ ] Store backup in secure location

- [ ] **Review migration files**
  - [ ] Check for AUTO_INCREMENT usage in all migration files
  - [ ] Document any auto-increment specific syntax found
  - [ ] Assess portability of current schema definitions
  - [ ] Create documentation with findings and recommendations

### Code Changes

- [ ] **Add utility functions**
  - [ ] Add `getCurrentTimestamp()` in [`lib/db/utils.py`](../lib/db/utils.py)
  - [ ] Review and update `convertToSQLite()` for cross-RDBMS compatibility

- [ ] **Update SQLite providers**
  - [ ] Add `upsert()` method to [`lib/db/providers/sqlite3.py`](/lib/db/providers/sqlite3.py)
  - [ ] Add `applyPagination()` method to [`lib/db/providers/sqlite3.py`](/lib/db/providers/sqlite3.py)
  - [ ] Add `getTextType()` method to [`lib/db/providers/sqlite3.py`](/lib/db/providers/sqlite3.py)
  - [ ] Add `enable_foreign_keys` parameter to [`lib/db/providers/sqlite3.py`](/lib/db/providers/sqlite3.py)
  - [ ] Add `upsert()` method to [`lib/db/providers/sqlink.py`](/lib/db/providers/sqlink.py)
  - [ ] Add `applyPagination()` method to [`lib/db/providers/sqlink.py`](/lib/db/providers/sqlink.py)
  - [ ] Add `getTextType()` method to [`lib/db/providers/sqlink.py`](/lib/db/providers/sqlink.py)
  - [ ] Add `enable_foreign_keys` parameter to [`lib/db/providers/sqlink.py`](/lib/db/providers/sqlink.py)

- [ ] **Implement MySQL provider**
  - [ ] Create `lib/db/providers/mysql.py`
  - [ ] Implement `upsert()` method
  - [ ] Implement `applyPagination()` method
  - [ ] Implement `getTextType()` method
  - [ ] Implement `getCaseInsensitiveComparison()` method
  - [ ] Implement `getLikeComparison()` method
  - [ ] Implement all abstract methods
  - [ ] Add MySQL-specific optimizations

- [ ] **Implement PostgreSQL provider**
  - [ ] Create `lib/db/providers/postgresql.py`
  - [ ] Implement `upsert()` method
  - [ ] Implement `applyPagination()` method
  - [ ] Implement `getTextType()` method
  - [ ] Implement `getCaseInsensitiveComparison()` method
  - [ ] Implement `getLikeComparison()` method
  - [ ] Implement all abstract methods
  - [ ] Add PostgreSQL-specific optimizations

- [ ] **Update repository files**
  - [ ] Update [`internal/database/repositories/cache.py`](/internal/database/repositories/cache.py)
  - [ ] Update [`internal/database/repositories/chat_messages.py`](/internal/database/repositories/chat_messages.py)
  - [ ] Update [`internal/database/repositories/chat_users.py`](/internal/database/repositories/chat_users.py)
  - [ ] Update [`internal/database/repositories/chat_settings.py`](/internal/database/repositories/chat_settings.py)
  - [ ] Update [`internal/database/repositories/media_attachments.py`](/internal/database/repositories/media_attachments.py)
  - [ ] Update [`internal/database/repositories/spam.py`](/internal/database/repositories/spam.py)
  - [ ] Update [`internal/database/repositories/chat_info.py`](/internal/database/repositories/chat_info.py)

- [ ] **Review migration files**
  - [ ] Check for AUTO_INCREMENT usage
  - [ ] Remove auto-increment specific syntax if not needed
  - [ ] Use simple INTEGER PRIMARY KEY for portability
  - [ ] Test schema creation

### Testing

- [ ] **Unit tests**
  - [ ] Test all repository methods with SQLite
  - [ ] Achieve 90%+ code coverage

- [ ] **Integration tests**
  - [ ] Test full application workflows
  - [ ] Test multi-source database routing
  - [ ] Test transaction handling
  - [ ] Test error handling

### Documentation

- [ ] **Update documentation**
  - [ ] Document provider-specific implementations
  - [ ] Update [`docs/database-README.md`](/docs/database-README.md) with portability notes
  - [ ] Document any RDBMS-specific considerations
  - [ ] Create examples for MySQL and PostgreSQL configuration

- [ ] **Code review**
  - [ ] Review all code changes for portability
  - [ ] Ensure consistent use of provider methods
  - [ ] Verify no RDBMS-specific syntax in repository layer
  - [ ] Update inline documentation

---

## Testing Recommendations

### Unit Testing Strategy

#### Repository Layer Tests

```python
# tests/database/repositories/test_cache_repository.py
import pytest
from datetime import datetime, timedelta
from internal.database.repositories.cache import CacheRepository
from internal.database.models import CacheType

@pytest.mark.asyncio
async def test_set_cache_storage(db_manager):
    """Test cache storage upsert."""
    repo = CacheRepository(db_manager)
    result = await repo.setCacheStorage("test", "key1", "value1")
    assert result is True

@pytest.mark.asyncio
async def test_cache_entry_ttl(db_manager):
    """Test cache entry with TTL."""
    from lib.cache import GenericDatabaseCache
    from internal.database.models import CacheType

    cache = GenericDatabaseCache(db_manager, namespace=CacheType.WEATHER)
    await cache.set("key1", "data1")

    # Should return entry
    entry = await cache.get("key1", ttl=3600)
    assert entry is not None

    # Should not return entry (TTL expired)
    entry = await cache.get("key1", ttl=-1)
    assert entry is None
```

#### Provider Layer Tests

```python
# tests/database/providers/test_sqlite3_provider.py
# NOTE: asyncio_mode = "auto" in pyproject.toml — no @pytest.mark.asyncio needed.
from lib.db.providers.base import BaseSQLProvider, ExcludedValue
from lib.db.providers.sqlite3 import SQLite3Provider


async def test_execute_upsert(testDatabase):
    """Test upsert operation via the provider's portable upsert() method."""
    provider = SQLite3Provider(database=":memory:")
    await provider.connect()
    try:
        # kwargs are camelCase to match BaseSQLProvider.upsert signature
        result = await provider.upsert(
            table="test_table",
            values={"id": 1, "name": "test", "value": "data"},
            conflictColumns=["id"],
            updateExpressions={
                "name": ExcludedValue(),
                "value": ExcludedValue(),
            },
        )
        assert result is True
    finally:
        await provider.disconnect()


async def test_case_insensitive_comparison(testDatabase):
    """Test case-insensitive comparison."""
    provider = SQLite3Provider(database=":memory:")
    await provider.connect()
    try:
        comparison = provider.getCaseInsensitiveComparison("username", "username")
        assert "LOWER(username)" in comparison
    finally:
        await provider.disconnect()
```

**Note on `getCurrentTimestamp()`**: it is a **module-level function** in
[`lib/db/utils.py`](../lib/db/utils.py), not a method on
the provider, and returns a `datetime.datetime` (UTC) — not a SQL expression.
Use it to populate bind parameters, never to inline into a query string:

```python
from internal.database import utils as dbUtils

# ✅ Correct: bind a Python timestamp
now = dbUtils.getCurrentTimestamp()  # -> datetime.datetime in UTC
await sqlProvider.execute(
    "INSERT INTO events (ts) VALUES (:ts)",
    {"ts": now},
)

# ❌ Wrong: there is no provider.getCurrentTimestamp() method, and it does
#          not return a SQL fragment like "datetime('now')".
```

### Integration Testing Strategy

#### Multi-Source Database Routing Tests

```python
# tests/database/integration/test_multi_source_routing.py
import pytest
from lib.db.manager import DatabaseManager

@pytest.mark.asyncio
async def test_chat_routing(db_manager):
    """Test that chat data is routed to correct source."""
    # Chat 100 should go to source1
    await db_manager.chatUsers.updateChatUser(100, 1, "@user1", "User One")
    
    # Chat 200 should go to source2
    await db_manager.chatUsers.updateChatUser(200, 2, "@user2", "User Two")
    
    # Verify routing
    user1 = await db_manager.chatUsers.getChatUser(100, 1, dataSource="source1")
    assert user1 is not None
    assert user1["username"] == "@user1"
    
    user2 = await db_manager.chatUsers.getChatUser(200, 2, dataSource="source2")
    assert user2 is not None
    assert user2["username"] == "@user2"

@pytest.mark.asyncio
async def test_aggregation_across_sources(db_manager):
    """Test data aggregation across multiple sources."""
    # Add users to different sources
    await db_manager.chatUsers.updateChatUser(100, 1, "@user1", "User One")
    await db_manager.chatUsers.updateChatUser(200, 1, "@user2", "User Two")
    
    # Get all chats for user 1 (should aggregate from both sources)
    chats = await db_manager.chatUsers.getUserChats(1)
    assert len(chats) == 2
    chat_ids = {chat["chat_id"] for chat in chats}
    assert chat_ids == {100, 200}
```

### Performance Testing Strategy

#### Query Performance Benchmarks

```python
# tests/database/performance/benchmark_queries.py
import pytest
import time
from lib.db.manager import DatabaseManager

@pytest.mark.asyncio
async def test_cache_performance(db_manager):
    """Test cache query performance."""
    from lib.cache import GenericDatabaseCache
    from internal.database.models import CacheType

    cache = GenericDatabaseCache(db_manager, namespace=CacheType.WEATHER)

    # Insert 1000 cache entries
    start = time.time()
    for i in range(1000):
        await cache.set(f"key{i}", f"data{i}")
    insert_time = time.time() - start

    # Query 1000 cache entries
    start = time.time()
    for i in range(1000):
        await cache.get(f"key{i}")
    query_time = time.time() - start

    print(f"Insert: {insert_time:.3f}s, Query: {query_time:.3f}s")
    assert insert_time < 10.0  # Should complete in under 10 seconds
    assert query_time < 5.0    # Should complete in under 5 seconds
```

---

## Best Practices for Portable SQL

### 1. Use Named Parameters

**❌ Avoid**:
```python
await sqlProvider.execute(
    "SELECT * FROM users WHERE id = ? AND name = ?",
    (user_id, user_name)
)
```

**✅ Prefer**:
```python
await sqlProvider.execute(
    "SELECT * FROM users WHERE id = :userId AND name = :userName",
    {"userId": user_id, "userName": user_name}
)
```

### 2. Avoid RDBMS-Specific Functions

**❌ Avoid**:
```python
# SQLite-specific
"SELECT datetime('now') as current_time"

# MySQL-specific
"SELECT NOW() as current_time"

# PostgreSQL-specific
"SELECT CURRENT_TIMESTAMP as current_time"
```

**✅ Prefer**:
```python
# Use helper function for consistent timestamps
from lib.db.utils import getCurrentTimestamp

current_time = getCurrentTimestamp()
await sqlProvider.execute(
    "SELECT :currentTime as current_time",
    {"currentTime": current_time}
)
```

### 3. Use Provider-Specific Methods for Complex Operations

**❌ Avoid**:
```python
# Direct upsert with RDBMS-specific syntax
await sqlProvider.execute(
    """
    INSERT INTO users (id, name) VALUES (:id, :name)
    ON CONFLICT(id) DO UPDATE SET name = :name
    """,
    {"id": user_id, "name": user_name}
)
```

**✅ Prefer**:
```python
# Use provider-specific upsert method. Kwargs are camelCase.
from lib.db.providers.base import ExcludedValue

await sqlProvider.upsert(
    table="users",
    values={"id": userId, "name": userName},
    conflictColumns=["id"],
)

# With complex expressions — use ExcludedValue(), not raw "excluded.col" strings
await sqlProvider.upsert(
    table="chat_users",
    values={
        "chat_id": chatId,
        "user_id": userId,
        "username": username,
        "updated_at": datetime.datetime.now(datetime.UTC),
    },
    conflictColumns=["chat_id", "user_id"],
    updateExpressions={
        "messages_count": "messages_count + 1",   # custom SQL expression
        "updated_at": ExcludedValue(),              # translated to excluded.updated_at / VALUES(updated_at) per provider
    },
)
```

### 4. Handle Timezones Consistently

**❌ Avoid**:
```python
# Rely on database timezone settings
"SELECT CURRENT_TIMESTAMP"
```

**✅ Prefer**:
```python
# Use explicit UTC timestamps
current_time = datetime.datetime.now(datetime.UTC)
await sqlProvider.execute(
    "INSERT INTO events (timestamp) VALUES (:timestamp)",
    {"timestamp": current_time}
)
```

### 5. Use Portable SQL Types

**❌ Avoid**:
```python
# RDBMS-specific types
"TINYINT", "MEDIUMTEXT", "JSONB"
```

**✅ Prefer**:
```python
# Portable types
"INTEGER", "TEXT"

# Use provider-specific methods for type selection
text_type = sqlProvider.getTextType(max_length=100000)
```

**Note**: Use TEXT for JSON data across all RDBMS for portability.

### 6. Avoid Implicit Type Conversions

**❌ Avoid**:
```python
# Implicit boolean conversion
"SELECT * FROM users WHERE is_active = 1"
```

**✅ Prefer**:
```python
# Explicit type conversion
is_active = 1 if user_is_active else 0
await sqlProvider.execute(
    "SELECT * FROM users WHERE is_active = :isActive",
    {"isActive": is_active}
)
```

### 7. Use Explicit Column Lists

**❌ Avoid**:
```python
# Implicit column list
"INSERT INTO users VALUES (:id, :name, :email)"
```

**✅ Prefer**:
```python
# Explicit column list
"INSERT INTO users (id, name, email) VALUES (:id, :name, :email)"
```

### 8. Limit String Lengths

**❌ Avoid**:
```python
# Unlimited string length
username = user_input  # Could be very long
```

**✅ Prefer**:
```python
# Explicit length limits
username = user_input[:255]  # Limit to 255 characters
```

### 9. Use Transactions for Multi-Step Operations

**❌ Avoid**:
```python
# Multiple operations without transaction
await sqlProvider.execute("INSERT INTO orders ...")
await sqlProvider.execute("UPDATE inventory ...")
await sqlProvider.execute("UPDATE users ...")
```

**✅ Prefer**:
```python
# Use transaction
async with sqlProvider:
    await sqlProvider.execute("INSERT INTO orders ...")
    await sqlProvider.execute("UPDATE inventory ...")
    await sqlProvider.execute("UPDATE users ...")
```

### 10. Test with SQLite

**❌ Avoid**:
```python
# Skip testing entirely
# No tests written
```

**✅ Prefer**:
```python
# Test with SQLite to ensure code portability
@pytest.mark.asyncio
async def test_user_creation(db_manager):
    # Test implementation
    pass
```

**Note**: While MySQL and PostgreSQL providers will be implemented for code portability, actual testing with these RDBMS is deferred until deployment is planned.

---

## Conclusion

This SQL portability guide provides a comprehensive analysis of compatibility issues and actionable solutions for making the Gromozeka database layer code portable across SQLite, MySQL, and PostgreSQL. By following the implementation strategy, migration checklist, and best practices outlined in this document, the development team can ensure the codebase is ready for future deployment to MySQL or PostgreSQL while maintaining data integrity and application performance with SQLite.

### Key Takeaways

1. **13 compatibility issues** have been identified and documented (Issues #1–#13), plus the native vector search portability section
2. **Abstraction layer** is essential for handling RDBMS-specific operations
3. **Standardized approach** to SQL queries ensures cross-RDBMS compatibility
4. **Code portability** enables future deployment flexibility without immediate migration
5. **Focus on code changes** defers actual MySQL/PostgreSQL deployment until needed

### Next Steps

1. Review and approve this portability guide
2. Allocate resources for implementation (6 weeks estimated)
3. Begin Phase 1: Foundation work
4. Regular progress reviews and updates
5. Defer MySQL/PostgreSQL deployment until code portability is complete

### Contact Information

For questions or clarifications regarding this portability guide, please contact the database team or refer to the project documentation in [`docs/database-README.md`](/docs/database-README.md).

---

**Document Version**: 1.1  
**Last Updated**: 2026-07-11  
**Author**: Database Team  
**Status**: Audited — provider API claims re-verified against `lib/db/providers/base.py`; vector search section added; upsert examples corrected to actual camelCase signature.
