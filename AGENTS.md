# AGENTS.md

Compact agent guide for the Gromozeka repo. The canonical, deeper guide lives in
[`docs/llm/`](docs/llm/index.md) — read it before non-trivial work. When the
markdown-mcp MCP tools are available, prefer `doc_list` + `doc_outline("llm/index.md")`
+ targeted `doc_read` (docs-root-relative paths; slugs resolved via `doc_outline` at
use time) over reading whole files, and `doc_search` for targeted questions; plain
`read` remains fully valid without markdown-mcp (see the fallback policy in
"Existing instruction sources" below). This file captures only what an agent would
likely get wrong without help.

## Stack snapshot

- Python **3.12** or newer (pyright/black target = `py312`, line length **120**).
- Single-process app by default, async, singleton services. **SQLite today** behind a
  provider abstraction; SQL must stay portable across SQLite/PostgreSQL/MySQL
  (see "SQL portability" below). Custom migrations live under
  [`internal/database/migrations/versions/`](internal/database/migrations/versions/).
- Multi-platform bot: Telegram **and** Max Messenger. Mode picked by config
  (`bot.mode`), wired in [`main.py`](main.py).
- **Max webhook mode is two-process.** When `webhook-receiver.enabled = true`,
  a standalone aiohttp receiver ([`lib/max_webhook_receiver/`](lib/max_webhook_receiver/))
  buffers Max webhook POSTs in the `webhook_updates` table and serves them to
  the bot via a local `GET /updates`. The bot's `MaxBotClient` gets a
  `basePollingUrl` override so its existing `_pollingLoop()` polls the receiver
  instead of `platform-api2.max.ru`. See
  [`docs/llm/architecture.md`](docs/llm/architecture.md) ADR-013. Run it with
  `./venv/bin/python3 -m lib.max_webhook_receiver --config webhook-receiver.toml --dotenv-file .env`.
- Entry point: [`main.py`](main.py) → `GromozekBot` → `TelegramBotApplication`
  or `MaxBotApplication`.

## Run / dev commands (use these literally)

```bash
make install            # creates ./venv and installs requirements.txt
make format lint        # ALWAYS before AND after edits
make test               # MANDATORY after any change (wrapped in `timeout 5m`; pass V=1 for -v)
make test-failed        # re-run pytest --last-failed
./venv/bin/pytest path/to/test_x.py::TestClass::testFn -v   # single test
make check-docs         # checks local markdown links resolve (read-only; exit 1 if broken)
make ci                 # run the full CI pipeline locally in the Alpine container (mirrors .sourcecraft/ci.yaml); needs Docker
```

`make check-docs` validates links only. When markdown-mcp is available, `doc_lint` /
CLI `markdown-mcp lint` complement it (structural lint: duplicate slugs, front
matter); on disputes the CLI lint stays authoritative (older MCP `doc_lint` builds
surfaced excluded-path noise; current builds honor the exclude list).

## Hard rules (enforced socially, not by tooling)

**camelCase** naming (PascalCase classes, UPPER_CASE constants), docstrings with
`Args:`/`Returns:` + full type hints, run Python only via `./venv/bin/python3`
from the repo root, `requirements.txt` is frozen (pins go into
`requirements.direct.txt`), no pydantic, no `Any`, imports at file top, `StrEnum`
over `Literal`, regression test on every bug fix. **Normative text:**
[`docs/llm/index.md`](docs/llm/index.md) §3 — read it before editing code. When
markdown-mcp is available, read §3 via `doc_read("llm/index.md", section_slug=…)`
(resolve the slug from `doc_outline` at use time; cite sections by name, not
hard-coded slugs).

## Lint/format pipeline

`make lint` runs `flake8 .`, `isort --check-only --diff .`, an `import main`
check (catches circular imports in the production import graph — added after
the `85aa945` refactor introduced a startup-breaking cycle that flake8/isort
couldn't see), then `pyright`.
`make format` runs `isort` + `black` on the tree, then iterates each
`lib/ext_modules/*/` separately (they are not auto-traversed). If you touch
anything under `lib/ext_modules/`, run `make format` rather than running
black/isort manually so those subpackages get formatted too.

`pyright` is `typeCheckingMode = "basic"` and **excludes `ext/`**. The `venv`
must exist at `./venv` for pyright to resolve imports.

**Final verification**: Always run `make test` after any changes to ensure code examples work and
nothing is broken. This is mandatory - see docs/llm/index.md §3.5.

## Tests

- `pyproject.toml` sets `testpaths = ["tests", "lib", "internal"]`, but all test files now live exclusively under `tests/` — `lib/` and `internal/` have no collocated tests. Test directories mirror source structure:
  - Tests for `lib/X/Y.py` go in `tests/lib/X/test_Y.py`.
  - Tests for `internal/X/Y.py` go in `tests/X/test_Y.py` (strip `internal/`).
  - **No new collocated tests in `lib/` or `internal/`.** All new test files MUST go under `tests/`. **Exception:** `lib/ext_modules/*/tests/` (vendored subpackages with their own `pyproject.toml`) are sanctioned-collocated — see `docs/llm/testing.md` §1.
- `asyncio_mode = "auto"` → write `async def test_…` with no decorator.
- Custom markers exist (`slow`, `performance`, `benchmark`, `memory`,
  `stress`, `profile`); none are auto-skipped, deselect with `-m "not slow"`.
- Rich shared fixtures live in [`tests/conftest.py`](tests/conftest.py)
  (`testDatabase`, `mockBot`, `mockConfigManager`, `resetLlmServiceSingleton`
  is autouse, etc.). Reuse them — see [`docs/llm/testing.md`](docs/llm/testing.md).
- Singletons (`LLMService`, `CacheService`, `QueueService`, `StorageService`,
  `RateLimiterManager`) leak state across tests; reset `_instance = None` in
  fixtures or rely on the existing autouse reset.
- Golden-data API tests live in per-service `golden/` subdirectories under `tests/lib/` — don't hit real APIs.

## Changelog

`CHANGELOG.md` is the user-visible record of what changed and why. After any
feature, behavior change, schema migration, or user-facing bug fix, add a
one-line entry under `## [Unreleased]` in `CHANGELOG.md` (Added / Changed /
Fixed) **as part of the same change**, before committing. For the full format,
entry-style rules, and "when / when-not to update" criteria, see
[`docs/llm/changelog.md`](docs/llm/changelog.md). `CHANGELOG.md` sits outside
the markdown-mcp docs root and is always edited with normal file tools.

- Skip the changelog for style/formatting fixes, internal refactors with no
  user-visible effect, doc-only tweaks (unless documenting a new feature),
  dependency bumps with no behavioral change, and test-only changes.
- The `/changelog` slash-command drafts an entry from the current diff on demand.
- Cutting a release: rename `## [Unreleased]` to a dated version heading and
  add a fresh empty `## [Unreleased]` section above it, then bump
  `[project].version` in `pyproject.toml` to match, commit as a single atomic
  `Release v<X.Y.Z>` commit, and create+push an annotated `v<X.Y.Z>` tag. See
  [`docs/llm/changelog.md`](docs/llm/changelog.md) §Release operations for the
  full sequence (and the `/generate-release` slash-command for automation).

## Architecture cheatsheet

Layout (see [`docs/llm/index.md`](docs/llm/index.md) §4 for line-level map):

- [`internal/bot/common/`](internal/bot/common/) — platform-agnostic bot core.
  `TheBot`, `BaseBotHandler`, `HandlersManager`. Handlers are registered as
  an ordered list with parallelism flags.
- [`internal/bot/{telegram,max}/`](internal/bot/) — platform adapters.
- [`lib/max_webhook_receiver/`](lib/max_webhook_receiver/) — standalone
  Max webhook receiver process (aiohttp). Only deployed in Max webhook mode;
  see ADR-013 above. Not a bot handler — it owns `webhook_updates` in its own
  `webhook_receiver_data.db` and reads its own `webhook-receiver.toml` (only
  `secret` / `get-updates-secret` must match the bot's values; see
  ADR-013/ADR-025).
- [`internal/services/`](internal/services/) — `cache/`, `llm/`, `queue_service/`,
  `storage/`. All singletons; access via `Service.getInstance()`, never
  `Service()` directly.
- [`internal/database/`](internal/database/) — `Database` repo wrapper +
  repositories + versioned migrations under `migrations/versions/NNN_*.py`
  (the SQL provider layer itself lives in `lib/db/` — see the `lib/` bullet).
  Before adding a migration, find the next number with
  `ls -1 internal/database/migrations/versions/ | grep migration_ | sort -V | tail -1`.
- [`lib/`](lib/) — reusable, no bot deps. `lib/ai/` (provider registry in
  [`lib/ai/manager.py`](lib/ai/manager.py)), `lib/db/` (SQL provider
  abstraction + `DatabaseManager` at
  [`lib/db/providers/`](lib/db/providers/); imported by `internal/database/`),
  `lib/rate_limiter/`, `lib/max_bot/`, `lib/markdown/`, `lib/bayes_filter/`,
  `lib/sandbox/` (sandboxed code execution in Docker), etc.
- [`lib/ext_modules/`](lib/ext_modules/) — vendored/extension subpackages
  (e.g. `grabliarium`) with their own `pyproject.toml`/tests. Treated
  separately by the formatter.

Handler ordering rule: `LLMMessageHandler` **must** be the last entry in the
handler list (it's the catch-all). Registration site:
[`internal/bot/common/handlers/manager.py`](internal/bot/common/handlers/manager.py).

## SQL portability

SQLite3 is the only backend wired up in production right now (the factory in
[`lib/db/providers/__init__.py`](lib/db/providers/__init__.py)
registers `sqlite3` + `sqlink`; `mysql.py` / `postgresql.py` providers exist
but are not yet selectable). Even so, **all SQL the app emits must stay
portable across SQLite, PostgreSQL, and MySQL** so the other providers can be
turned on without rewriting queries. See
[`docs/sql-portability-guide.md`](docs/sql-portability-guide.md) for the full
analysis; key rules in practice:

- Go through the provider, not raw `sqlite3` calls. Repositories use
  `BaseSQLProvider` (see [`lib/db/providers/base.py`](lib/db/providers/base.py)) —
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
  [`lib/db/providers/utils.py`](lib/db/providers/utils.py)).
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
- Handler-facing `BaseBotHandler.getChatSettings()` (and `CacheService`)
  return `ChatSettingsDict` = `Dict[ChatSettingsKey, ChatSettingsValue]` —
  values are `ChatSettingsValue` objects; access via `.toBool()`/`.toStr()`/
  `.toInt()`/`.toFloat()`/`.toList()`/`.toModel()` (NOT tuple indexing). The
  `(value, updatedBy)` tuple shape exists ONLY at the DB-repo layer
  (`self.db.chatSettings.getChatSettings()`, returns `Dict[str, tuple[str, int]]`).
  At the handler layer, `setChatSetting(..., *, user: MessageSender)` — the
  keyword-only arg is `user` (pass a `MessageSender`); `updatedBy=` keyword-only
  applies only to the repository's `setChatSetting`.
- `bot_owners` config entries can be either int IDs or usernames; check both.
- Singleton init uses a `hasattr(self, 'initialized')` guard — don't
  re-implement that pattern, just call `getInstance()`.

## Existing instruction sources (do not duplicate, prefer linking)

- [`docs/llm/index.md`](docs/llm/index.md) — canonical agent guide and index
- [`docs/llm/{architecture,handlers,database,services,libraries,configuration,testing,tasks}.md`](docs/llm/)
- [`docs/README.md`](docs/README.md) — docs-tree index organized by audience (humans / agents / reference)
- [`docs/developer-guide.md`](docs/developer-guide.md) — human-oriented
- [`docs/database-schema.md`](docs/database-schema.md) and
  [`docs/database-schema-llm.md`](docs/database-schema-llm.md) — keep both in
  sync when changing schema
- [`docs/documentation-review-process.md`](docs/documentation-review-process.md) — systematic
  process for reviewing and maintaining documentation
- [`docs/docs-playbook/mcp-docs-workflow.md`](docs/docs-playbook/mcp-docs-workflow.md) +
  [`docs/docs-playbook/gromozeka-workflow-brief.md`](docs/docs-playbook/gromozeka-workflow-brief.md) —
  how to work the docs tree via markdown-mcp (prefer over manual reads when the
  MCP server is available)
- [`.agents/skills/`](.agents/skills/) — loadable task-specific skills. Load
  the matching one via the `skill` tool when its trigger applies:
  - [`read-project-docs`](.agents/skills/read-project-docs/SKILL.md) — onboarding / context-building before non-trivial work
  - [`update-project-docs`](.agents/skills/update-project-docs/SKILL.md) — post-change documentation sync with decision matrix
  - [`run-quality-gates`](.agents/skills/run-quality-gates/SKILL.md) — the exact `./venv/bin/python3` / `make format lint` / `make test` workflow
  - [`write-regression-test`](.agents/skills/write-regression-test/SKILL.md) — regression-test recipe for bug fixes: write the test FIRST (must FAIL before the fix), apply the minimal root-cause fix, then add edge-case tests
  - [`add-database-migration`](.agents/skills/add-database-migration/SKILL.md) — new migration scaffolding + SQL portability rules
  - [`add-handler`](.agents/skills/add-handler/SKILL.md) — add a bot handler end-to-end, with the `LLMMessageHandler`-stays-last invariant
  - [`add-llm-tool`](.agents/skills/add-llm-tool/SKILL.md) — add an LLM tool end-to-end, with the never-raise contract and D3 chat-time gating across four coordinated sites
  - [`add-chat-setting`](.agents/skills/add-chat-setting/SKILL.md) — wire a new `ChatSettingsKey` across all four required sites
- [`README.md`](README.md) — user docs

**markdown-mcp fallback policy (canonical):** When the markdown-mcp MCP tools
(`doc_search`/`doc_read`/`doc_outline`/…) are available, use them for everything
under `./docs` (see `docs/docs-playbook/mcp-docs-workflow.md`). Otherwise use the
normal file tools — every instruction in this repo remains satisfiable without
markdown-mcp. Files outside the docs root (`AGENTS.md`, `CHANGELOG.md`, root
`README.md`, `TODO.md`, `.agents/**`, `.opencode/**`, inline `lib/**`/`internal/**`
READMEs) are always edited with normal tools.
