---
name: add-database-migration
description: >
  Step-by-step recipe for adding a database migration to Gromozeka while
  respecting the project's cross-RDBMS SQL portability rules (SQLite today,
  PostgreSQL/MySQL providers must work without rewrites). Use this skill when
  creating new tables, altering columns, backfilling data, or changing indexes.
  Covers migration file scaffolding, `BaseSQLProvider` usage, forbidden
  constructs (`AUTOINCREMENT`, `DEFAULT CURRENT_TIMESTAMP`, `SERIAL`, dialect
  LIMIT/OFFSET, `COLLATE NOCASE`), primary key strategy, and the dual-schema
  doc update that must accompany every schema change. Triggers: add migration,
  schema change, new table, new column, alter table, database migration.
---

# Add a Database Migration

## When to use

- Creating a new table, index, or constraint.
- Altering a column, renaming, dropping, or adding a default.
- Backfilling data as part of a schema transition.

## When NOT to use

- You only need a new query against existing tables — that's a repository/service change, not a migration.
- You're debugging a migration that already shipped — load the `debugger` agent instead.

## Inputs

- What the change is (DDL + any data backfill).
- What tables/columns it touches.
- Whether any existing repository code needs updating to use the new schema.

## Prerequisites

Load `read-project-docs` if you haven't already, specifically:

- [`docs/llm/database.md`](../../../docs/llm/database.md) — migration pattern and current version list.
- [`docs/sql-portability-guide.md`](../../../docs/sql-portability-guide.md) — the full portability ruleset.
- [`AGENTS.md`](../../../AGENTS.md) "SQL portability" section — the compact rules.

## Step 1 — Pick the next migration number

Never assume a number. Always check:

```bash
ls -1 internal/database/migrations/versions/ | grep "migration_" | sort -V | tail -1
```

Your migration is `latest + 1`, zero-padded to 3 digits.

## Step 2 — Create the migration file

Path: `internal/database/migrations/versions/NNN_short_description.py`.

Copy the shape from a recent migration, e.g. [`migration_015_add_divination_layouts_table.py`](../../../internal/database/migrations/versions/migration_015_add_divination_layouts_table.py):

```python
"""<Module docstring — what this migration does and why>."""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class MigrationNNNShortDescription(BaseMigration):
    """<Class docstring — describes the migration.>

    Attributes:
        version: Migration version number (NNN).
        description: Human-readable description of the migration.
    """

    version: int = NNN
    """The version number of this migration."""
    description: str = "<one-line description>"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """<Docstring covering what up() creates/changes.>

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS my_table (
                        ...
                    )
                """),
                # more statements...
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """<Docstring covering the exact inverse of up().>

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP TABLE IF EXISTS my_table"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return MigrationNNNShortDescription
```

Signatures that **must** match:

- Methods are `async def up(self, sqlProvider: BaseSQLProvider) -> None` and `async def down(self, sqlProvider: BaseSQLProvider) -> None`.
- Module exports `getMigration() -> Type[BaseMigration]`.
- `version` is an `int`, not a string.

## Step 3 — Follow SQL portability rules (the hard part)

Every SQL statement must run identically on SQLite, PostgreSQL, and MySQL. Violations compile on SQLite today but will break the moment another provider gets wired up.

### Forbidden

- ❌ **`AUTOINCREMENT` / `AUTO_INCREMENT` / `SERIAL` / `BIGSERIAL`** — each dialect spells it differently. Use natural keys or app-generated UUIDs (see Step 4).
- ❌ **`DEFAULT CURRENT_TIMESTAMP`** — migration 013 removed every instance of this repo-wide. Set `created_at` / `updated_at` in application code.
- ❌ **`COLLATE NOCASE`** — SQLite-only. Use `provider.getCaseInsensitiveComparison(column, param)` instead.
- ❌ **`LIMIT … OFFSET …` appended manually** — use `provider.applyPagination(query, limit, offset)`.
- ❌ **Raw `sqlite3` import in migrations or repositories** — go through `BaseSQLProvider`.
- ❌ **Dialect-specific column types** (`VARCHAR(n)` with MySQL semantics, `JSONB`, SQLite `JSON1` function calls). Stick to portable types (see below).
- ❌ **`TRUE` / `FALSE` literals in SQL.** Booleans cross as `0` / `1`; use `= 1` / `= 0`.
- ❌ **Hand-rolled `ON CONFLICT … DO UPDATE`** — use `provider.upsert(...)` with the `ExcludedValue` marker.
- ❌ **Positional `?` placeholders in new code.** Use `:named` placeholders throughout.

### Required

- Portable column types only:
  - `TEXT` for strings (including JSON payloads stored as text).
  - `INTEGER` for integers (including booleans, stored as 0/1).
  - `REAL` for floats.
  - `TIMESTAMP` for timestamps.
  - `BOOLEAN` is accepted but stored as INTEGER under the hood.
- Use `:named` parameter placeholders; `BaseSQLProvider` translates.
- Go through `BaseSQLProvider.execute` / `executeFetchOne` / `executeFetchAll` / `batchExecute` / `upsert`.
- For case-insensitive lookups: `provider.getCaseInsensitiveComparison(column, paramName)` (exact match) or `provider.getLikeComparison(column, paramName)` (LIKE pattern).
- For dialect-dependent DDL in a migration, consult `provider.getTextType(maxLength=…)` rather than hard-coding type strings.

## Step 4 — Primary key strategy (pick one, in order of preference)

1. **Composite natural key** from columns the app already owns:
   ```sql
   PRIMARY KEY (chat_id, message_id)
   PRIMARY KEY (namespace, key)
   PRIMARY KEY (system_id, layout_id)
   ```
   This is the dominant pattern in existing migrations — copy it.

2. **Single natural key** when one external ID identifies the row:
   ```sql
   file_unique_id TEXT PRIMARY KEY
   chat_id INTEGER PRIMARY KEY
   ```

3. **Application-generated UUID/ULID** stored as `TEXT PRIMARY KEY NOT NULL`:
   ```sql
   id TEXT PRIMARY KEY NOT NULL
   ```
   Generate the ID in Python before insert. Never delegate ID generation to the DB.

If you reach for `AUTOINCREMENT` because none of these feel natural, push harder — there's almost always a composite natural key hiding in the rows.

## Step 5 — Update the Database repository layer

If the change adds or modifies tables the app queries, update the relevant module under [`internal/database/`](../../../internal/database/):

- New queries/methods go on `Database` or the relevant repository sub-module.
- Use `BaseSQLProvider` helpers (`execute`, `executeFetchOne`, `executeFetchAll`, `batchExecute`, `upsert`).
- Use `:named` placeholders; portable helpers for pagination / case-insensitive comparison.
- Add or update TypedDicts / enums in [`internal/database/models.py`](../../../internal/database/models.py) if needed.

## Step 6 — Tests

- Migration tests live in [`internal/database/migrations/test_migrations.py`](../../../internal/database/migrations/test_migrations.py). Add a test that exercises `up()` and `down()`.
- Repository-level tests go in [`tests/test_db_wrapper.py`](../../../tests/test_db_wrapper.py) or a collocated `test_*.py` next to the module you changed.
- `asyncio_mode = "auto"` is set — write `async def test_…` without `@pytest.mark.asyncio`.
- Reuse fixtures from [`tests/conftest.py`](../../../tests/conftest.py) (`testDatabase`, etc.).

## Step 7 — Documentation (mandatory, three files)

Every schema change must update **all three** of:

1. [`docs/database-schema.md`](../../../docs/database-schema.md) — human-oriented schema reference.
2. [`docs/database-schema-llm.md`](../../../docs/database-schema-llm.md) — LLM-oriented schema reference.
3. [`docs/llm/database.md`](../../../docs/llm/database.md) — migration pattern + current version list.

Also update [`internal/database/migrations/README.md`](../../../internal/database/migrations/README.md) if the migration introduces a new pattern.

If the change adjusts portability rules themselves, update [`docs/sql-portability-guide.md`](../../../docs/sql-portability-guide.md).

Load the `update-project-docs` skill for the full doc-sync decision matrix.

## Step 8 — Quality gates

Load the `run-quality-gates` skill. In short:

```bash
make format lint
make test
```

Verify that migration tests pass and that nothing else regressed.

## Checklist

- [ ] Next version number verified via `ls | grep migration_ | sort -V | tail -1`.
- [ ] Migration file has module docstring, class docstring, `up()` / `down()` docstrings, and `getMigration()` export.
- [ ] `version: int = NNN` matches the filename.
- [ ] `up()` and `down()` are exact inverses.
- [ ] No `AUTOINCREMENT` / `AUTO_INCREMENT` / `SERIAL`, no `DEFAULT CURRENT_TIMESTAMP`, no `COLLATE NOCASE`, no dialect-specific types.
- [ ] PK is a composite natural key, a single natural key, or an app-generated UUID/ULID.
- [ ] `created_at` / `updated_at` (if present) set from application code, not a default.
- [ ] All SQL uses `BaseSQLProvider` helpers and `:named` placeholders.
- [ ] Migration test added covering `up()` and `down()`.
- [ ] All three schema docs updated (`database-schema.md`, `database-schema-llm.md`, `docs/llm/database.md`).
- [ ] `make format lint && make test` green.
