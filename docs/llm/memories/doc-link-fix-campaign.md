# Doc-Link Fix Campaign + `make check-docs`

Durable record of the 2026-07-11 doc-link fix campaign and the conventions it locked in. Covers [`scripts/check_docs.py`](/scripts/check_docs.py) (the local-link checker), the `check-docs` [`Makefile`](/Makefile) target, the sweep that repaired all 376 broken local markdown links the checker reported on first run, and the durable lessons that apply to ALL future doc edits in this repo. Read this before writing or editing any cross-file markdown link — especially the leading-slash convention and the depth gotcha.

## Headline outcome

Fixed ALL 376 broken local markdown links `make check-docs` reported: **105 files / 1526 links → 97 files / 1423 links, 0 broken** (as of 2026-07-11; counts drift as docs land). `make check-docs` exited 0 at campaign end — later doc work (e.g. the 2026-07-18 Phase 2 docs-audit move) has since reintroduced a handful of breaks, so always re-run before trusting a "clean" verdict. Gate 2 whole-work review PASS (0 critical findings after remediation). The `test_noBrokenLinks_inRealRepo` test (formerly `@pytest.mark.xfail(strict=True)`) is now a normal passing regression guard — the suite in [`tests/scripts/test_check_docs.py`](/tests/scripts/test_check_docs.py) is 22 tests, lint green.

## Repo convention LOCKED: leading-slash `/X`

For repo-root-relative doc links, use the leading-slash form: `[label](/<repo-relative-path>)` (e.g. `[base handler](/internal/bot/common/handlers/base.py)`).

- **Depth-independent** — resolves identically from any depth in the tree, so it survives file moves within the repo. [`scripts/check_docs.py`](/scripts/check_docs.py) (`_resolveTarget`) treats a leading `/` as repo-root-relative, NOT filesystem-root. The `:line`/`:start-end` suffix is preserved (stripped before the leading-slash check).
- The 319 off-by-one breaks the campaign fixed were all "target exists, wrong `../` count" — rewritten to `/X`.
- Surviving *valid* relative links were NOT normalized. Mixed style within a file is acceptable; a normalization pass is optional future cleanup. Do not mass-rewrite valid relative links just to enforce uniformity.

## `check_docs.py` exclusion mechanism

The checker excludes three subtrees via a path-precise constant in [`scripts/check_docs.py`](/scripts/check_docs.py):

```python
_EXCLUDED_PATH_PREFIXES: frozenset[tuple[str, str]] = frozenset(
    {("docs", "archive"), ("docs", "templates"), ("lib", "ext_modules")}
)
```

`_isExcludedDir()` checks `(parts[0], parts[1]) in _EXCLUDED_PATH_PREFIXES` — **first-two-segments only.** This generalized the prior inline `docs/archive` check into a data-driven constant. Consequence: a future `src/templates/` would NOT be excluded (the match is on the leading path pair, not the leaf name). Covered by unit tests `test_skipsArchive`, `test_skipsTemplates`, `test_skipsExtModules` in [`tests/scripts/test_check_docs.py`](/tests/scripts/test_check_docs.py).

## Excluded-directories rationale

- `docs/templates/` — intentional `path/to/…` placeholder paths in PR/task templates (not real references).
- `lib/ext_modules/` — vendored nested git repo, **NOT a submodule.** [`.gitignore`](/.gitignore) line 50 is `lib/ext_modules/*/`; `git ls-files lib/ext_modules/` returns only the `__init__.py` package marker (1 file) — the nested submodule trees (e.g. `grabliarium/`) are untracked, so any fixes in that subtree are invisible to the main-repo PR.
- `docs/archive/` — frozen historical snapshots (already excluded before this campaign).

## DEPTH GOTCHA (load-bearing)

`../../plans/` is **CORRECT** in depth-3 files (`docs/llm/memories/*.md` → `docs/plans/`) but **BROKEN** in depth-2 files (`docs/llm/*.md` → nonexistent repo-root `plans/`).

- **NEVER blanket-replace `../../plans/` repo-wide.** Only fix exact enumerated broken links, per file. The campaign's `replaceAll` did NOT touch `../../plans/` — see the safety proof below for why the off-by-one `replaceAll` was scoped to `](../X` only.
- The hazard generalizes to any `../../X` pattern spanning files at multiple depths: a relative link that is correct at one depth is wrong at another. Verify the source file's depth before "fixing" a relative link that looks off.
- The safe universal form remains `/X` (see "Repo convention LOCKED"), but rewriting valid relative links is NOT required.

## xfail marker lifecycle

`tests/scripts/test_check_docs.py::test_noBrokenLinks_inRealRepo` was decorated `@pytest.mark.xfail(strict=True)`.

- Under `strict=True`, reaching 0 broken links flips the test to XPASS = **HARD failure** (the suite fails, not merely warns). This is the intended enforcement mechanism.
- Therefore the xfail marker MUST be removed as the final step of any campaign that drives the repo to 0 broken links. (Done — the marker is deleted; the test is a normal passing regression guard. `import pytest` is KEPT in the file because `pytest.MonkeyPatch` is still used as a type annotation elsewhere.)
- When updating the function docstring as part of marker removal, ALSO update the MODULE docstring. Gate 2 caught a stale module docstring after the function docstring had already been fixed — easy to miss.

## Missing-target resolution patterns (16 links)

These were genuine missing targets (files moved/renamed/deleted), NOT off-by-one depth bugs.

- **Repoint to the closest existing file.** Examples: `internal/database/wrapper.py` → `/internal/database/database.py` (and DROP the stale `:line` suffix — those line numbers referenced the deleted file); `internal/models.py` → `/internal/models/shared_enums.py` (where `MessageType` actually lives — NOT `types.py`); `max_adapter.py` → `/internal/bot/max/application.py`.
- **DROP the link wrapper entirely for fully-absent targets** (`/docs/reports/`, `CONTRIBUTING.md`, `/docs/design/storage-service-design-v1.md`), keeping the readable label text as plain text or inline code.
- **When dropping or repointing, ensure the label matches the target.** A `[label](otherTarget)` mismatch is misleading. Gate 2 caught one on `max_adapter.py` (the label still named a file that never existed after the target had already been repointed).

## Duplicate-link hazard

Repointing a missing target to a sibling that is ALREADY linked nearby creates a confusing duplicate-with-mismatched-description. Gate 2 caught this on `docs/database-multi-source.md` (a bullet linking the same `advanced.toml` as a nearby bullet, but with a different description). Prefer dropping the bullet entirely if no faithful sibling target exists. This check is separate from target validity — a repoint can produce a syntactically valid but semantically broken duplicate.

## Parallel-dev lesson (REINFORCED)

Concurrent `software-developer` agents each running `make check-docs` see each other's INTERMEDIATE working-tree state, so their TOTAL-broken-count observations are UNRELIABLE. Dev-A's final "0 broken" run was authoritative only because it ran last.

- A fresh **SERIAL** verification pass (`make check-docs` run once, alone) after all parallel agents finish is mandatory before trusting any global count.
- Same lesson as the ChatSettings consolidation: cross-phase pass/fail verdicts are unreliable under concurrency because each observer's working tree is contaminated by the others' in-flight edits.

## `replaceAll` safety proof

For the off-by-one files, `replaceAll` on `](../X` → `](/X` was proven safe via:

```bash
comm -23 <(all-1-up-targets) <(broken-targets)   # returned EMPTY
```

Every 1-up `../` target was broken before the edit, so the replacement could not corrupt a valid link. Additionally, the literal `](../X` **cannot** match inside `](../../X` — the character after the first `../` is `.`, not `X`. This is a stronger safety argument than a post-hoc "0 broken" check alone (which would also pass if both valid and invalid links were silently destroyed).

## `developer-guide.md` over-replacement safety

A depth-1 file (`docs/developer-guide.md`) using bare `](internal/...` ALWAYS resolves to nonexistent `docs/internal/...`. Therefore `replaceAll` on ALL 79 occurrences (not just the 35 reported broken) was correct — there is no such thing as a valid docs-relative `](internal` link from depth 1. Spot-checks confirmed all 79 targets exist at repo root. This is the dual of the depth gotcha: at depth 1, bare repo-root paths are ALWAYS broken, so over-replacement is safe.

## `TODO.md` scope-creep flag

The campaign diff picked up pre-existing uncommitted checkbox toggles in `TODO.md` (pure `[ ]`→`[x]`, no link changes — NOT from the campaign's `replaceAll`). Flagged to the user for commit-hygiene. NOT reverted (it is the user's local pending work). Lesson: when a campaign uses broad `replaceAll`, audit the final diff for unrelated pre-existing edits that rode along, and surface them rather than silently shipping them under the campaign's commit message.

## `.opencode/memory.jsonl` note

`.opencode/memory.jsonl` shows as modified during any session — that is expected OpenCode session state. **NEVER read, edit, or stage it.** Its presence in `git status` is not a campaign artifact and requires no action.

## Cross-references

- [`scripts/check_docs.py`](/scripts/check_docs.py) — the link checker (`_EXCLUDED_PATH_PREFIXES` at line 82, `_resolveTarget` leading-slash semantics, `_INLINE_LINK_RE`).
- [`tests/scripts/test_check_docs.py`](/tests/scripts/test_check_docs.py) — 22-test suite; `test_noBrokenLinks_inRealRepo` is the regression guard (line 304).
- [`Makefile`](/Makefile) — the `check-docs` target at line 111 (depends on `venv`, runs `$(PYTHON) scripts/check_docs.py`).
