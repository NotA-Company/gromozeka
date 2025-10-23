# System Patterns *Optional*

This file documents recurring patterns and standards used in the project.
It is optional, but recommended to be updated as the project evolves.
2025-09-07 14:38:22 - Initial Memory Bank setup and pattern documentation initialization.

## Coding Patterns

* Python-based development for Telegram bot functionality
* Task-based development workflow with structured reporting
* Template-driven documentation approach
* Memory Bank system for context and decision tracking

## Architectural Patterns

* Repository structure with organized directories (docs/, memory-bank/, .roo/)
* Separation of concerns: templates, reports, plans, and memory tracking
* Version control integration with appropriate .gitignore patterns
* Documentation-first approach with README and structured reporting

## Testing Patterns

* To be established as project develops
* Will likely include unit tests for bot functionality
* Integration tests for Telegram API interactions
* Manual validation procedures for bot behavior

## Task Completion Workflow

2025-09-07 14:43:52 - Added mandatory task reporting pattern

* **Task Report Requirement:** After completing any task, dood should create a task report using the template at `docs/templates/task-report-template.md`
* **Report Location:** All task reports should be saved in `docs/reports/` directory with naming pattern `task-[X.Y.Z]-completion-report.md`
* **Report Content:** Must include all sections from template with actual project-specific information, no placeholder text

[2025-10-23 21:59:59] - Database Migration System Pattern

## Database Migration Pattern

* **Migration System:** Implemented comprehensive database migration system in `internal/database/migrations/`
* **Version Tracking:** Uses existing `settings` table with keys `db_migration_version` and `db_migration_last_run`
* **Sequential Execution:** Migrations run automatically on database initialization in order
* **Rollback Support:** Can rollback N migrations using `MigrationManager.rollback(steps=N)`
* **Error Handling:** Automatic transaction rollback on migration failures
* **Migration Generator:** Script at `internal/database/migrations/create_migration.py` for automated template creation

### Migration File Structure

```
internal/database/migrations/
├── __init__.py                        # Migration registry (MIGRATIONS list)
├── base.py                            # BaseMigration abstract class
├── manager.py                         # MigrationManager implementation
├── create_migration.py                # Migration generator script
├── test_migrations.py                 # Test suite
├── README.md                          # Complete documentation
└── versions/                          # Migration files
    ├── __init__.py
    ├── migration_001_initial_schema.py
    └── migration_002_example_migration.py
```

### Migration Naming Convention

* **File:** `migration_{version:03d}_{description}.py`
* **Class:** `Migration{version:03d}{PascalCaseDescription}`
* **Example:** `migration_003_add_user_preferences.py` → `Migration003AddUserPreferences`

### Creating New Migrations

```bash
# Use generator script (recommended)
./venv/bin/python3 internal/database/migrations/create_migration.py "description"

# Manual steps:
# 1. Create migration file in versions/
# 2. Implement up() and down() methods
# 3. Register in versions/__init__.py
# 4. Add to MIGRATIONS list in __init__.py
# 5. Test with test_migrations.py
```

### Migration Best Practices

* ✅ Use `IF NOT EXISTS` for CREATE statements
* ✅ Use `IF EXISTS` for DROP statements
* ✅ Test both up() and down() methods
* ✅ Keep migrations small and focused
* ✅ Version sequentially (no gaps)
* ❌ Never modify existing migrations after deployment
* ❌ Don't skip version numbers
* ❌ Don't make migrations dependent on application code
* **Memory Bank Update:** Task completion should trigger Memory Bank updates to reflect progress and decisions made