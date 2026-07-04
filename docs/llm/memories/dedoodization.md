# Dedoodization

Durable notes from the repo-wide removal of "dood" from comments, docstrings, log messages, and error messages (2026-07-02).

- Repo-wide removal of "dood" — 1231 of 1294 occurrences removed across 90 `.py` files.
- Script: `scripts/dedoodize.py` — line-based state machine with triple-quote tracking and bracket-depth awareness. Handles multi-line raise/logger/assert, standalone-dood docstring lines, assert condition-vs-message classification. Idempotent (re-run produces 0 changes). Excludes itself. Covers `lib/ext_modules/grabliarium` too.
- Kept "dood" in: `print()`, `messageText=`/`helpMessage=`, argparse `description=`/`help=`, `__author__`, test fixture data, mock strings — 53 occurrences preserved.
- Found and fixed 4 mid-sentence comma-loss cases in `collect.py` / `scenario_runner.py` where `, dood! ` was between clauses.
- Tests: `make test` 2802 pass, 1 pre-existing failure (`test_forwardOriginAuthorMatching[originUser-matchByUsername]` — unrelated).
- `scripts/dedoodize.py` is untracked; user should decide keep vs delete.
