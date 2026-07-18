# DB Maintenance Scripts

Durable conventions and precedents for standalone maintenance scripts under `/scripts/` that perform direct DB maintenance (open a SQLite DB by path, mutate rows, drop tables). Read this when adding or editing a script in `/scripts/` that touches the DB directly. Underlying rules (camelCase, `./venv/bin/python3`) live in `AGENTS.md`; this file captures the established script-class patterns.

## First precedent for direct `sqlite3.connect()` in `scripts/`

`/scripts/clear_memory_refinement.py` (added 2026-07-06) is the first standalone maintenance script that opens a SQLite DB directly by path. Prior DB-accessing scripts (`/scripts/list_models.py`, `/scripts/sandbox_bootstrap.py`) go through `ConfigManager` + provider layer. The established pattern:

- Standalone stdlib-only script (no `lib/`/`internal/` imports).
- DB path as positional arg; `argparse` for flags.
- Direct `sqlite3` with hand-driven transactions: `isolation_level=None` + explicit `BEGIN`/`COMMIT`/`ROLLBACK`.
- This script removes the top-level `memoryRefinement` key from every `chat_users.metadata` row.
- Smoke-tested with `mktemp` fixture DBs covering empty / malformed / no-key / with-key+siblings states.
- Dry-run verified byte-identical via MD5.

## Production JSON serializer for `chat_users.metadata`

`lib/utils/utils.py:jsonDumps` = `json.dumps(ensure_ascii=False, default=str, sort_keys=True, separators=(",", ":"))` (compact, sorted). This is the canonical on-disk shape, called from `CacheService.updateUserMetadata` (`internal/services/cache/service.py`).

Any direct-DB maintenance script that rewrites `metadata` should match:

```python
json.dumps(x, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
```

Omit `default=str` for fresh `json.loads` results — they are always JSON-safe by construction. Matching this avoids format drift on the column.

## `/scripts/` conventions

Verified 2026-07-06:

- `/scripts/__init__.py` exists — `/scripts/` is a package.
- Universal `argparse`.
- Module docstring with a `Usage::` block showing `./venv/bin/python3 scripts/<name>.py [flags]`.
- Shebang forms vary across existing scripts — three seen:
  - `#!/usr/bin/env python3`
  - `#!/usr/bin/env ./venv/bin/python3` (matches `AGENTS.md` canonical Python; **preferred for new scripts**)
  - `#!../venv/bin/python3` (relative — avoid)
- Standalone scripts with no `lib/`/`internal/` imports are an accepted pattern (`/scripts/dedoodize.py`, `/scripts/convert_llm_log_to_readable.py`).

## `dest="dryRun"` convention for `--dry-run`

`argparse` auto-converts `--dry-run` to `args.dry_run` (snake_case — violates the repo camelCase rule). Add `dest="dryRun"` explicitly:

```python
parser.add_argument("--dry-run", dest="dryRun", action="store_true", ...)
```

Established precedents: `/scripts/check_image_parsing.py`, `/scripts/check_structured_output.py`, `/scripts/check_tool_calling.py`. Apply the same `dest=` pattern for any other kebab-case CLI flag.

## `StrEnum` over loose string literals

When two functions share a set of action/status string literals, hoist them into a `class X(StrEnum)` at module level (per `AGENTS.md`):

```python
class _MetadataAction(StrEnum):
    UPDATE = "update"
    CLEAR = "clear"
```

- Pyright narrows types on `_MetadataAction.UPDATE`-style comparisons; bare strings do not narrow.
- Do **not** use `assert x is not None` for type narrowing — it is stripped under `python -O`. Use `typing.cast(...)` instead.

## `/scripts/clear_memory_embeddings.py`

Added 2026-07-11. Drops all `vec_user_memories_{N}` virtual tables and nulls `embedding_model`/`embedding_dimensions` in `user_memories` to trigger a full re-embedding.

- Same standalone stdlib-only pattern as `/scripts/clear_memory_refinement.py`.
- Regex `^vec_user_memories_\d+$` (matches the production `internal/database/repositories/user_memories.py` regex used in `deleteMemoryEmbedding` and the memory-delete path) filters real vec0 tables from shadow tables.
- Single transaction wraps all DROPs + UPDATE atomically.
- 9 tests under `tests/scripts/test_clear_memory_embeddings.py`.

## `/scripts/delete_stopwords.py`

Added 2026-07-15. Deletes `bayes_tokens` rows whose `token` matches one of the tokenizer's default stopwords (`TokenizerConfig().getStopwords()` in [`lib/bayes_filter/tokenizer.py`](../../../lib/bayes_filter/tokenizer.py)). Purpose: after new stopwords are added to that default list, previously-learned tokens that are now stopwords keep lingering with their old `spam_count`/`ham_count` totals — this script purges them.

- **Follows the `scripts/prune_unknown_chat_settings.py` precedent** (referenced in `docs/llm/configuration.md` and `docs/llm/memories/user-memories.md`): standalone script, positional `dbPath` arg, `--dry-run` / `-n` flag with `dest="dryRun"`.
- **NOT pure-stdlib** — unlike `/scripts/clear_memory_refinement.py` and `/scripts/clear_memory_embeddings.py`, it imports `TokenizerConfig` from `lib.bayes_filter.tokenizer` so the stopword list is read live from the canonical source (no hardcoded words). Adds the repo root to `sys.path` first so `./venv/bin/python3 scripts/delete_stopwords.py` resolves the import.
- Direct `sqlite3` access (raw `sqlite3.connect(..., isolation_level=None)` + hand-driven `BEGIN`/`COMMIT`/`ROLLBACK`), matching the established script-class pattern.
- Guards against a missing `bayes_tokens` table (hard error, exit 1).
- Builds `IN (?, ?, ...)` placeholders for the stopword set (well under SQLite's 999-variable cap).
- **TOCTOU warning in the module docstring:** stop the bot before running — the `SELECT COUNT(*)` and the later `DELETE` are not atomic, so a concurrent bot write to a stopword row can desync the reported count. Read-then-act window by design.
- Tokens in `bayes_tokens` are already lowercase (tokenizer lowercases before the stopword check), so an exact string match is sufficient.

## See also

- `AGENTS.md` — camelCase, `./venv/bin/python3`, `StrEnum`, no-`Any`, docstring/type-hint rules.
- [`teamlead-memory.md`](../teamlead-memory.md) — source of this extracted memory (provenance).
