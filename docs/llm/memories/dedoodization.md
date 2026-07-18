# Dedoodization

Durable notes from the repo-wide removal of "dood" from comments, docstrings, log messages, and error messages (2026-07-02).

- Repo-wide removal of "dood" — 1231 of 1294 occurrences removed across 90 `.py` files.
- Script: `scripts/dedoodize.py` — line-based state machine with triple-quote tracking and bracket-depth awareness. Handles multi-line raise/logger/assert, standalone-dood docstring lines, assert condition-vs-message classification. Idempotent (re-run produces 0 changes). Excludes itself. Covers `lib/ext_modules/grabliarium` too.
- Kept "dood" in: `print()`, `messageText=`/`helpMessage=`, argparse `description=`/`help=`, `__author__`, test fixture data, mock strings — 53 occurrences preserved.
- Found and fixed 4 mid-sentence comma-loss cases in `collect.py` / `scenario_runner.py` where `, dood! ` was between clauses.
- Tests at the time of the pass: `make test` 2802 pass, 1 pre-existing failure (`test_forwardOriginAuthorMatching[originUser-matchByUsername]` — test-only mock bug, since fixed 2026-07-04 by setting `sender_user.name` in `_makeOriginUser`).
- `scripts/dedoodize.py` is tracked in the same commit (`81919f8` "Dedoodie the code"); kept as a maintenance tool. Re-run is idempotent (`./venv/bin/python3 scripts/dedoodize.py --dry-run` reports 0 changes on the current tree).
