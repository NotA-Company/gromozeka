# AGENTS.md

Compact agent guide for the Gromozeka repo. The canonical, deeper guide lives in
[`docs/llm/`](docs/llm/index.md) — read it before non-trivial work. This file
captures only what an agent would likely get wrong without help.

## Stack snapshot

- Python **3.12** or newer (pyright/black target = `py312`, line length **120**).
- Single-process app, async, singleton services. **SQLite today** behind a
  provider abstraction; SQL must stay portable across SQLite/PostgreSQL/MySQL
  (see "SQL portability" below). Custom migrations live under
  [`internal/database/migrations/versions/`](internal/database/migrations/versions/).
- Multi-platform bot: Telegram **and** Max Messenger. Mode picked by config
  (`bot.mode`), wired in [`main.py:54`](main.py:54).
- Entry point: [`main.py`](main.py:1) → `GromozekBot` → `TelegramBotApplication`
  or `MaxBotApplication`.

## Run / dev commands (use these literally)

```bash
make install            # creates ./venv and installs requirements.txt
make format lint        # ALWAYS before AND after edits
make test               # MANDATORY after any change (wrapped in `timeout 5m`; pass V=1 for -v)
make test-failed        # re-run pytest --last-failed
./venv/bin/pytest path/to/test_x.py::TestClass::testFn -v   # single test
```

## Hard rules (enforced socially, not by tooling)

These come from [`docs/llm/index.md`](docs/llm/index.md):

- **camelCase** for variables, args, fields, functions, methods.
  **PascalCase** for classes. **UPPER_CASE** for constants. Snake_case is
  wrong here even though it's idiomatic Python.
- **Docstrings required** on every module/class/method/function/field, with `Args:`
  and `Returns:` describing all params and return type.
- **Type hints required** on all function/method params and returns; on
  locals when type isn't obvious.
- Run Python via `./venv/bin/python3` — not `python` / `python3`.
- Do **not** `cd` into subdirectories; run everything from repo root.
- Do **not** use `python -c '...'` for ad-hoc tests — write a script file.
- Do **not** add imports inside of methods or functions. All imports should be
  at the top of the file. Import inside methods is only acceptable when there's
  a cyclic dependency that makes it unavoidable. When adding imports to the top,
  run `make format` to properly organize them.
- **No pydantic.** The repo deliberately avoids it. Use raw dicts +
  hand-rolled type-hinted classes of TypedDict.
- **Regression tests on every bug fix.** When fixing a bug — whether in production
  code, test code, or config — write a regression test that FAILS before the fix
  and PASSES after it. Include tests for edge cases that the bug touched (e.g.,
  Optional/Union conversion, None handling, schema column mismatches). Do not
  rely solely on existing test coverage to catch regressions.

## Lint/format pipeline

`make lint` runs `flake8 .`, `isort --check-only --diff .`, then `pyright`.
`make format` runs `isort` + `black` on the tree, then iterates each
`lib/ext_modules/*/` separately (they are not auto-traversed). If you touch
anything under `lib/ext_modules/`, run `make format` rather than running
black/isort manually so those subpackages get formatted too.

`pyright` is `typeCheckingMode = "basic"` and **excludes `ext/`**. The `venv`
must exist at `./venv` for pyright to resolve imports.

**Final verification**: Always run `make test` after any changes to ensure code examples work and
nothing is broken. This is mandatory - see docs/llm/index.md §3.5.

## Tests

- `pyproject.toml` sets `testpaths = ["tests", "lib", "internal"]` —
  collocated tests under `lib/` and `internal/` are real and get run.
- `asyncio_mode = "auto"` → write `async def test_…` with no decorator.
- Custom markers exist (`slow`, `performance`, `benchmark`, `memory`,
  `stress`, `profile`); none are auto-skipped, deselect with `-m "not slow"`.
- Rich shared fixtures live in [`tests/conftest.py`](tests/conftest.py)
  (`testDatabase`, `mockBot`, `mockConfigManager`, `resetLlmServiceSingleton`
  is autouse, etc.). Reuse them — see [`docs/llm/testing.md`](docs/llm/testing.md).
- Singletons (`LLMService`, `CacheService`, `QueueService`, `StorageService`,
  `RateLimiterManager`) leak state across tests; reset `_instance = None` in
  fixtures or rely on the existing autouse reset.
- Golden-data API tests in `tests/fixtures/` — don't hit real APIs.

## Architecture cheatsheet

Layout (see [`docs/llm/index.md`](docs/llm/index.md) §4 for line-level map):

- [`internal/bot/common/`](internal/bot/common/) — platform-agnostic bot core.
  `TheBot`, `BaseBotHandler`, `HandlersManager`. Handlers are registered as
  an ordered list with parallelism flags.
- [`internal/bot/{telegram,max}/`](internal/bot/) — platform adapters.
- [`internal/services/`](internal/services/) — `cache/`, `llm/`, `queue_service/`,
  `storage/`. All singletons; access via `Service.getInstance()`, never
  `Service()` directly.
- [`internal/database/`](internal/database/) — `Database` repo wrapper +
  versioned migrations under `migrations/versions/NNN_*.py`. Before adding a
  migration, find the next number with
  `ls -1 internal/database/migrations/versions/ | grep migration_ | sort -V | tail -1`.
- [`lib/`](lib/) — reusable, no bot deps. `lib/ai/` (provider registry in
  [`lib/ai/manager.py`](lib/ai/manager.py)), `lib/rate_limiter/`,
  `lib/max_bot/`, `lib/markdown/`, `lib/bayes_filter/`, etc.
- [`lib/ext_modules/`](lib/ext_modules/) — vendored/extension subpackages
  (e.g. `grabliarium`) with their own `pyproject.toml`/tests. Treated
  separately by the formatter.

Handler ordering rule: `LLMMessageHandler` **must** be the last entry in the
handler list (it's the catch-all). Registration site:
[`internal/bot/common/handlers/manager.py`](internal/bot/common/handlers/manager.py).

## SQL portability

SQLite3 is the only backend wired up in production right now (the factory in
[`internal/database/providers/__init__.py`](internal/database/providers/__init__.py)
registers `sqlite3` + `sqlink`; `mysql.py` / `postgresql.py` providers exist
but are not yet selectable). Even so, **all SQL the app emits must stay
portable across SQLite, PostgreSQL, and MySQL** so the other providers can be
turned on without rewriting queries. See
[`docs/sql-portability-guide.md`](docs/sql-portability-guide.md) for the full
analysis; key rules in practice:

- Go through the provider, not raw `sqlite3` calls. Repositories use
  `BaseSQLProvider` (see [`internal/database/providers/base.py`](internal/database/providers/base.py)) —
  `execute` / `executeFetchOne` / `executeFetchAll` / `batchExecute` / `upsert`.
- For upserts, call `provider.upsert(table, values, conflictColumns, updateExpressions=...)`
  instead of writing `ON CONFLICT … DO UPDATE` by hand. Use the
  `ExcludedValue` marker from `base.py` (translates to `excluded.col` on
  SQLite/PostgreSQL, `VALUES(col)` on MySQL).
- Use the provider hooks for things that differ across RDBMS instead of
  hard-coding dialect:
  - `provider.applyPagination(query, limit, offset)` — never append `LIMIT … OFFSET …` yourself.
  - `provider.getTextType(maxLength=…)` — for migrations / DDL.
  - `provider.getCaseInsensitiveComparison(column, param)` — `LOWER(...) = LOWER(...)` is the portable shape; don't use `COLLATE NOCASE`.
- Timestamps: do **not** use `DEFAULT CURRENT_TIMESTAMP` in new schemas.
  Migration 013 removed it from every table specifically for cross-DB
  compatibility — application code sets `created_at` / `updated_at`
  explicitly (see notes in [`docs/llm/database.md`](docs/llm/database.md) §7).
- Stick to portable column types in migrations: `TEXT`, `INTEGER`, `REAL`,
  `TIMESTAMP`, `BOOLEAN` (stored as int — see `convertToSQLite` in
  [`internal/database/providers/utils.py`](internal/database/providers/utils.py)).
  Store JSON as `TEXT`; don't reach for SQLite's `JSON1` functions.
- **Primary keys: no `AUTOINCREMENT`.** SQLite `AUTOINCREMENT`, MySQL
  `AUTO_INCREMENT`, and PostgreSQL `SERIAL` / `BIGSERIAL` all spell it
  differently, so we sidestep the problem entirely. Pick one of these
  instead, in order of preference:
  1. **Composite natural key** from columns the app already has — e.g.
     `PRIMARY KEY (chat_id, message_id)`, `PRIMARY KEY (namespace, key)`,
     `PRIMARY KEY (chat_id, user_id)`. This is the dominant pattern in
     existing migrations; copy it.
  2. **Single natural key** when the row is identified by one external ID
     (e.g. `file_unique_id TEXT PRIMARY KEY`, `chat_id INTEGER PRIMARY KEY`).
  3. **Application-generated UUID / ULID** stored as `TEXT PRIMARY KEY
     NOT NULL` (see `delayed_tasks.id` in `migration_001`/`013`). Generate
     it in Python before insert; never delegate ID generation to the DB.
- Booleans cross the wire as `0`/`1` (handled by `convertToSQLite`); don't
  compare to `TRUE`/`FALSE` literals in SQL.
- Parameter style: use `:named` placeholders consistently — the provider
  translates them as needed.
- If you genuinely need a dialect-specific feature, add a method to
  `BaseSQLProvider` (abstract) and implement it in every provider, the same
  way `applyPagination` / `getTextType` / `upsert` already are.

## Config system

TOML, hierarchical, merged recursively. Loaded by
[`internal/config/manager.py`](internal/config/manager.py) (`ConfigManager`).

- Defaults live in [`configs/00-defaults/`](configs/00-defaults/) and are
  loaded first by `run.sh` (`--config-dir ./configs/00-defaults`).
- Additional dirs come from the `CONFIGS` env var (space-separated list of
  subdirs of `configs/`, default `local`). `run.sh --env=foo` sources
  `.env.foo` to set `CONFIGS`, tokens, etc.
- `${VAR}` substitution in TOML pulls from the chosen `.env*` file.
- `./venv/bin/python3 main.py --print-config --config-dir configs/00-defaults --config-dir configs/local`
  prints the merged config — the fastest way to debug config issues.

`.env*` files contain secrets — never commit, never echo to stdout.

## Gotchas that bite (full list in [`docs/llm/tasks.md`](docs/llm/tasks.md) §3)

- `MessageId` class (`internal/models/types.py`) wraps `int | str` — Telegram
  = int, Max = str. Don't assume plain int; wrap with `MessageId(...)`, use
  `.asInt()` for Telegram API calls, `.asStr()` for Max/SQL, `.asMessageId()`
  for JSON serialization.
- Chat type is inferred from sign: `chatId > 0` private, else group.
- `DEFAULT_THREAD_ID = 0` (int), not `None`. DB queries expect 0.
- `getChatSettings()` returns `Dict[key, tuple[value, updatedBy]]` — index
  `[0]` for the value. `setChatSetting(..., updatedBy=...)` is required and
  keyword-only.
- `bot_owners` config entries can be either int IDs or usernames; check both.
- Singleton init uses a `hasattr(self, 'initialized')` guard — don't
  re-implement that pattern, just call `getInstance()`.

## Documentation Maintenance

See [`docs/documentation-review-process.md`](docs/documentation-review-process.md) for the systematic
process of reviewing and maintaining documentation.

## Existing instruction sources (do not duplicate, prefer linking)

- [`docs/llm/index.md`](docs/llm/index.md) — canonical agent guide and index
- [`docs/llm/{architecture,handlers,database,services,libraries,configuration,testing,tasks}.md`](docs/llm/)
- [`docs/developer-guide.md`](docs/developer-guide.md) — human-oriented
- [`docs/database-schema.md`](docs/database-schema.md) and
  [`docs/database-schema-llm.md`](docs/database-schema-llm.md) — keep both in
  sync when changing schema
- [`.agents/skills/`](.agents/skills/) — loadable task-specific skills. Load
  the matching one via the `skill` tool when its trigger applies:
  - [`read-project-docs`](.agents/skills/read-project-docs/SKILL.md) — onboarding / context-building before non-trivial work
  - [`update-project-docs`](.agents/skills/update-project-docs/SKILL.md) — post-change documentation sync with decision matrix
  - [`run-quality-gates`](.agents/skills/run-quality-gates/SKILL.md) — the exact `./venv/bin/python3` / `make format lint` / `make test` workflow
  - [`add-database-migration`](.agents/skills/add-database-migration/SKILL.md) — new migration scaffolding + SQL portability rules
  - [`add-handler`](.agents/skills/add-handler/SKILL.md) — add a bot handler end-to-end, with the `LLMMessageHandler`-stays-last invariant
  - [`add-chat-setting`](.agents/skills/add-chat-setting/SKILL.md) — wire a new `ChatSettingsKey` across all four required sites
- [`README.md`](README.md), [`README_BOT.md`](README_BOT.md) — user docs
