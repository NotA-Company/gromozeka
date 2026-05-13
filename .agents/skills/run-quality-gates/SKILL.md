---
name: run-quality-gates
description: >
  Encodes the exact commands Gromozeka requires for running Python, formatting,
  linting, and testing. Use this skill before committing, after any code change,
  or whenever you need to verify the repo is green. Covers `./venv/bin/python3`
  vs `python`, `make format lint`, `make test` with its mandatory timeout,
  `make test-failed` for iteration, single-test invocation, marker deselection,
  and the special-case formatting of `lib/ext_modules/*`. Triggers: run tests,
  verify changes, lint, format, check code quality, before commit, quality gates.
---

# Run Gromozeka Quality Gates

## When to use

- Before and after any code change (both sides are mandatory per `AGENTS.md`).
- Before claiming a task is complete.
- When diagnosing a CI failure locally.
- When re-running only failed tests during iteration.

## When NOT to use

- You're only editing Markdown/docs with no code examples that need verification.
- You've already run the gates in this session and haven't touched code since.

## The hard rules

These come from [`AGENTS.md`](../../../AGENTS.md) and are non-negotiable:

1. **Use `./venv/bin/python3`** — never `python`, never `python3`. The venv must exist at `./venv`; if it doesn't, run `make install`.
2. **Never `cd` into subdirectories.** Run everything from the repo root. Commands assume that working directory.
3. **Never `python -c '...'`** for ad-hoc tests — write a script file instead (under `scripts/` if it's worth keeping, or a throwaway file you delete after).
4. **`make test` is mandatory** as the final verification after any change. Wrapped in `timeout 5m` by the Makefile; do not bypass it.
5. **All imports at top of file.** Adding imports inside functions is an anti-pattern except for genuine cyclic-dependency cases that refactoring can't fix. After adding imports, run `make format` to reorder.

## The workflow

### Before making changes

```bash
make format lint
```

Starts you from a clean, green baseline so any new failures are attributable to your change.

### While iterating

Single test file:

```bash
./venv/bin/pytest tests/path/to/test_file.py -v
```

Single test function:

```bash
./venv/bin/pytest tests/path/to/test_file.py::TestClass::testFn -v
```

Skip slow markers while iterating:

```bash
./venv/bin/pytest -m "not slow" -v
```

Custom markers available: `slow`, `performance`, `benchmark`, `memory`, `stress`, `profile`. None are auto-skipped — deselect explicitly with `-m "not <marker>"`.

### After making changes (mandatory order)

```bash
make format   # isort + black on tree, then iterates each lib/ext_modules/*/
make lint     # flake8 + isort --check-only + pyright
make test     # full suite, timeout-wrapped at 5m
```

Or run the first two as one step: `make format lint`.

Pass `V=1` for verbose test output:

```bash
make test V=1
```

### Re-running failures

After a failed `make test`, iterate quickly with:

```bash
make test-failed          # pytest --last-failed
make test-failed V=1      # verbose variant
```

Fix, then re-run `make test` (full suite) before declaring done — `--last-failed` won't catch regressions elsewhere.

## `lib/ext_modules/*` — the formatter footgun

`make format` handles `lib/ext_modules/*/` **separately** by iterating each subdirectory and running isort + black on it. If you edit files under e.g. `lib/ext_modules/grabliarium/` and run `black`/`isort` manually on just the root, those changes won't be formatted.

**Rule:** if you touched anything under `lib/ext_modules/`, run `make format` — don't run black/isort by hand.

## Pyright and the venv

`pyright` runs in `typeCheckingMode = "basic"` and **excludes `ext/`**. It needs `./venv` to exist to resolve imports. If pyright can't find imports, verify `./venv` is present and `make install` has been run.

## What "green" means

All three must succeed with no errors:

- `make format` — no complaints from isort or black on any tree (root + each `lib/ext_modules/*`).
- `make lint` — flake8 clean, isort `--check-only` passes, pyright reports 0 errors.
- `make test` — full suite passes within the 5m timeout, including the collocated tests under `lib/` and `internal/` that `pyproject.toml` wires into `testpaths`.

If anything fails, fix it or explain why it's pre-existing and unrelated to your change. Do not silently ignore failures.

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `./venv/bin/python3: No such file` | venv not created | `make install` |
| pyright "Import … could not be resolved" | venv missing or stale | `make install`; if still broken, `rm -rf venv && make install` |
| isort/black disagreement on `lib/ext_modules/*` | Ran formatter manually on root only | `make format` (iterates subpackages) |
| Test passes alone but fails in suite | Singleton state leak across tests | See `docs/llm/testing.md` — reset `_instance = None` in a fixture |
| `make test` hits 5m timeout | Probably an async hang or a new slow test | Bisect with targeted pytest invocations; mark genuinely slow tests with `@pytest.mark.slow` |
| flake8 complains about line length | Black target is **120** chars, not 88 or 100 | Don't lower the limit; rewrite the line |

## What this skill does NOT cover

- Running the bot itself (`./run.sh` or `./venv/bin/python3 main.py --config-dir configs/...`) — that's a separate concern; quality gates come first.
- `make coverage` — useful but not mandatory; run when you specifically need a coverage report.
- `git commit` — commit hooks, if any, are downstream of these gates.
