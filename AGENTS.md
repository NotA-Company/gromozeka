# AGENTS.md

Compact agent guide for the Gromozeka repo. The canonical, deeper guide lives in
[`docs/llm/`](docs/llm/index.md) — read it before non-trivial work. This file
captures only what an agent would likely get wrong without help.

## Stack snapshot

- Python **3.12** only (pyright/black target = `py312`, line length **120**).
- Single-process app, async, singleton services. SQLite + custom migrations.
- Multi-platform bot: Telegram **and** Max Messenger. Mode picked by config
  (`bot.mode`), wired in [`main.py:54`](main.py:54).
- Entry point: [`main.py`](main.py:1) → `GromozekBot` → `TelegramBotApplication`
  or `MaxBotApplication`.

## Run / dev commands (use these literally)

```bash
make install            # creates ./venv and installs requirements.txt
make format lint        # ALWAYS before AND after edits
make test               # full suite, wrapped in `timeout 5m`; pass V=1 for -v
make test-failed        # re-run pytest --last-failed
make check              # what CI runs: lint + black --check (NO tests)
./venv/bin/pytest path/to/test_x.py::TestClass::testFn -v   # single test
```

CI (`.sourcecraft/ci.yaml`) runs `make check && make test` on Alpine; system
deps it installs reveal hidden requirements: `gcc git libmagic make musl-dev
nodejs sqlite`. `libmagic` is a real runtime dep (file-type detection).

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
- Project mascot speech tic: comments and user-facing strings often end with
  ", dood!" (Prinny from Disgaea). Preserve it when editing existing strings;
  don't strip it.

## Lint/format pipeline

`make lint` runs `flake8 .`, `isort --check-only --diff .`, then `pyright`.
`make format` runs `isort` + `black` on the tree, then iterates each
`lib/ext_modules/*/` separately (they are not auto-traversed). If you touch
anything under `lib/ext_modules/`, run `make format` rather than running
black/isort manually so those subpackages get formatted too.

`pyright` is `typeCheckingMode = "basic"` and **excludes `ext/`**. The `venv`
must exist at `./venv` for pyright to resolve imports.

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

- `MessageIdType = Union[int, str]` — Telegram = int, Max = str. Don't
  assume int.
- Chat type is inferred from sign: `chatId > 0` private, else group.
- `DEFAULT_THREAD_ID = 0` (int), not `None`. DB queries expect 0.
- `getChatSettings()` returns `Dict[key, tuple[value, updatedBy]]` — index
  `[0]` for the value. `setChatSetting(..., updatedBy=...)` is required and
  keyword-only.
- `bot_owners` config entries can be either int IDs or usernames; check both.
- Singleton init uses a `hasattr(self, 'initialized')` guard — don't
  re-implement that pattern, just call `getInstance()`.

## Existing instruction sources (do not duplicate, prefer linking)

- [`docs/llm/index.md`](docs/llm/index.md) — canonical agent guide and index
- [`docs/llm/{architecture,handlers,database,services,libraries,configuration,testing,tasks}.md`](docs/llm/)
- [`docs/developer-guide.md`](docs/developer-guide.md) — human-oriented
- [`docs/database-schema.md`](docs/database-schema.md) and
  [`docs/database-schema-llm.md`](docs/database-schema-llm.md) — keep both in
  sync when changing schema
- [`README.md`](README.md), [`README_BOT.md`](README_BOT.md) — user docs
