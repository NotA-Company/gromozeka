# Migration Auto-Discovery Implementation Plan, Dood!

## Overview
Add automatic migration discovery functionality to the database migration system, eliminating the need for manual registration of migrations in [`internal/database/migrations/__init__.py`](internal/database/migrations/__init__.py:1).

## Current State Analysis

### Existing Structure
- **Base Migration**: [`BaseMigration`](internal/database/migrations/base.py:12) abstract class with `version`, `description`, `up()`, `down()` methods
- **Migration Manager**: [`MigrationManager`](internal/database/migrations/manager.py:25) handles migration execution with [`registerMigrations()`](internal/database/migrations/manager.py:47) method
- **Migration Files**: Located in [`internal/database/migrations/versions/`](internal/database/migrations/versions/__init__.py:1) directory
- **Manual Registration**: Migrations are manually imported and listed in [`MIGRATIONS`](internal/database/migrations/__init__.py:15) list
- **Creation Script**: [`create_migration.py`](internal/database/migrations/create_migration.py:1) generates new migration files

### Current Limitations
1. Manual import statements required for each new migration
2. Manual addition to `MIGRATIONS` list
3. Easy to forget updating the registry
4. No standardized way to retrieve migration class from module

## Proposed Solution

### 1. Migration Module Interface
Add a standardized `getMigration()` function to each migration module that returns the migration class, dood!

**Benefits:**
- Consistent interface for retrieving migration classes
- Enables dynamic discovery
- Simplifies testing and introspection

**Implementation:**
```python
def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration001InitialSchema
```

### 2. Auto-Discovery in versions/__init__.py
Implement migration discovery logic in [`internal/database/migrations/versions/__init__.py`](internal/database/migrations/versions/__init__.py:1), dood!

**Functionality:**
- Scan `versions/` directory for `migration_*.py` files
- Import each module dynamically
- Call `getMigration()` to retrieve migration class
- Sort by version number
- Export as `DISCOVERED_MIGRATIONS` list

**Key Features:**
- Automatic detection of new migrations
- Version-based sorting
- Error handling for malformed migrations
- Validation of migration structure

### 3. Update Migration Creation Script
Modify [`create_migration.py`](internal/database/migrations/create_migration.py:52) to include `getMigration()` function in generated files, dood!

**Changes:**
- Add `getMigration()` function to migration template
- Update instructions to remove manual registration steps
- Simplify workflow for developers

### 4. MigrationManager Enhancement
Add method to [`MigrationManager`](internal/database/migrations/manager.py:25) to use auto-discovered migrations, dood!

**New Method:**
```python
def loadMigrationsFromVersions(self) -> None:
    """
    Load migrations automatically from versions package, dood!
    
    This replaces the need for manual registration.
    """
```

**Integration:**
- Can be called during initialization
- Replaces or supplements `registerMigrations()`
- Maintains backward compatibility

## Implementation Steps

### Phase 1: Add getMigration() to Existing Migrations
- [ ] Add `getMigration()` function to [`migration_001_initial_schema.py`](internal/database/migrations/versions/migration_001_initial_schema.py:1)
- [ ] Add `getMigration()` function to [`migration_002_add_is_spammer_to_chat_users.py`](internal/database/migrations/versions/migration_002_add_is_spammer_to_chat_users.py:1)
- [ ] Add `getMigration()` function to [`migration_003_add_metadata_to_chat_users.py`](internal/database/migrations/versions/migration_003_add_metadata_to_chat_users.py:1)

**Function Template:**
```python
def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return MigrationXXXClassName
```

### Phase 2: Implement Auto-Discovery
- [ ] Implement discovery logic in [`versions/__init__.py`](internal/database/migrations/versions/__init__.py:1)
  - Import necessary modules (`os`, `importlib`, `pathlib`, `re`)
  - Scan directory for `migration_*.py` files
  - Dynamically import each module
  - Call `getMigration()` on each module
  - Sort by version
  - Handle errors gracefully
  - Export `DISCOVERED_MIGRATIONS` list

**Key Functions:**
```python
def discoverMigrations() -> List[Type[BaseMigration]]:
    """Discover all migrations in versions directory, dood!"""
    
def _importMigrationModule(filename: str) -> Optional[Type[BaseMigration]]:
    """Import a single migration module and return its class, dood!"""
```

### Phase 3: Update Creation Script
- [ ] Modify [`create_migration.py`](internal/database/migrations/create_migration.py:52) template
  - Add `getMigration()` function to generated content
  - Update instructions to reflect auto-discovery
  - Remove manual registration steps from output

**Template Addition:**
```python
def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return {class_name}
```

### Phase 4: Enhance MigrationManager
- [ ] Add [`loadMigrationsFromVersions()`](internal/database/migrations/manager.py:25) method to `MigrationManager`
  - Import `DISCOVERED_MIGRATIONS` from versions package
  - Call existing `registerMigrations()` with discovered list
  - Add logging for transparency

**Implementation:**
```python
def loadMigrationsFromVersions(self) -> None:
    """Load migrations from versions package automatically, dood!"""
    from .versions import DISCOVERED_MIGRATIONS
    self.registerMigrations(DISCOVERED_MIGRATIONS)
    logger.info(f"Auto-loaded {len(DISCOVERED_MIGRATIONS)} migrations, dood!")
```

### Phase 5: Update Main Module (Optional)
- [ ] Consider updating [`internal/database/migrations/__init__.py`](internal/database/migrations/__init__.py:1)
  - Option A: Keep manual `MIGRATIONS` for backward compatibility
  - Option B: Replace with `DISCOVERED_MIGRATIONS` import
  - Option C: Provide both with deprecation notice

**Recommendation:** Keep both initially for smooth transition, dood!

## Technical Considerations

### Error Handling
- **Missing getMigration()**: Log warning, skip migration
- **Import Errors**: Log error with details, continue discovery
- **Duplicate Versions**: Raise error immediately
- **Invalid Migration Class**: Validate inheritance from `BaseMigration`

### Performance
- Discovery happens once at import time
- Minimal overhead (< 100ms for typical project)
- Results cached in module-level variable

### Testing Strategy
- [ ] Test discovery with existing migrations
- [ ] Test with missing `getMigration()` function
- [ ] Test with malformed migration files
- [ ] Test version sorting
- [ ] Test duplicate version detection
- [ ] Update [`test_migrations.py`](internal/database/migrations/test_migrations.py:1) with new tests

### Backward Compatibility
- Existing code using `MIGRATIONS` continues to work
- `registerMigrations()` method remains available
- New `loadMigrationsFromVersions()` is optional
- Gradual migration path for existing projects

## File Changes Summary

### Files to Modify
1. [`internal/database/migrations/versions/__init__.py`](internal/database/migrations/versions/__init__.py:1) - Add discovery logic
2. [`internal/database/migrations/versions/migration_001_initial_schema.py`](internal/database/migrations/versions/migration_001_initial_schema.py:1) - Add `getMigration()`
3. [`internal/database/migrations/versions/migration_002_add_is_spammer_to_chat_users.py`](internal/database/migrations/versions/migration_002_add_is_spammer_to_chat_users.py:1) - Add `getMigration()`
4. [`internal/database/migrations/versions/migration_003_add_metadata_to_chat_users.py`](internal/database/migrations/versions/migration_003_add_metadata_to_chat_users.py:1) - Add `getMigration()`
5. [`internal/database/migrations/create_migration.py`](internal/database/migrations/create_migration.py:52) - Update template
6. [`internal/database/migrations/manager.py`](internal/database/migrations/manager.py:25) - Add `loadMigrationsFromVersions()`
7. [`internal/database/migrations/__init__.py`](internal/database/migrations/__init__.py:1) - Optional: Update to use auto-discovery

### Files to Test
- [`internal/database/migrations/test_migrations.py`](internal/database/migrations/test_migrations.py:1) - Add new test cases

## Benefits

### Developer Experience
- ✅ No manual registration required
- ✅ Reduced chance of errors
- ✅ Faster development workflow
- ✅ Self-documenting system

### Maintainability
- ✅ Single source of truth (filesystem)
- ✅ Consistent interface across migrations
- ✅ Easier to audit available migrations
- ✅ Simplified onboarding for new developers

### Reliability
- ✅ Automatic detection prevents missed migrations
- ✅ Version-based sorting ensures correct order
- ✅ Validation catches configuration errors early

## Migration Path for Existing Code

### Step 1: Add getMigration() Functions
Update all existing migration files with the new function, dood!

### Step 2: Implement Discovery
Add auto-discovery logic to versions package, dood!

### Step 3: Update Creation Script
Ensure new migrations include `getMigration()` automatically, dood!

### Step 4: Add Manager Method
Provide convenient method for loading discovered migrations, dood!

### Step 5: Update Documentation
Update README and inline documentation to reflect new approach, dood!

### Step 6: Gradual Adoption
- Keep manual `MIGRATIONS` list initially
- Add deprecation notice
- Remove after transition period

## Future Enhancements

### Potential Improvements
1. **Migration Metadata**: Add tags, dependencies, or categories
2. **Conditional Migrations**: Skip based on environment or conditions
3. **Migration Hooks**: Pre/post migration callbacks
4. **Parallel Execution**: Run independent migrations concurrently
5. **Migration Validation**: Dry-run mode to check migrations
6. **Migration Documentation**: Auto-generate migration history docs

## Conclusion

This implementation provides a robust, maintainable solution for automatic migration discovery while maintaining backward compatibility and following Python best practices, dood! The phased approach allows for incremental adoption and testing at each stage.

---

**Status**: Ready for Implementation  
**Estimated Effort**: 2-3 hours  
**Risk Level**: Low (backward compatible)  
**Priority**: Medium