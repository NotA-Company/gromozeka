#!/usr/bin/env ./venv/bin/python3
"""Delete stopword tokens from the ``bayes_tokens`` table.

The Bayes tokenizer keeps a default stopword list
(``TokenizerConfig.getStopwords()`` in
[`lib.bayes_filter.tokenizer`](lib/bayes_filter/tokenizer.py)) of common
Russian and English words that carry little spam signal. When new stopwords
are added to that list, tokens that were learned *before* the addition keep
lingering in the ``bayes_tokens`` table with their old ``spam_count`` /
``ham_count`` totals. This standalone maintenance script reads the current
default stopword set and deletes every ``bayes_tokens`` row whose ``token``
matches one of those stopwords.

The stopword set is read live from ``TokenizerConfig().getStopwords()``, so it
tracks the default list automatically: no words are hardcoded here. The
tokenizer lowercases words before checking them against the stopword list, so
tokens stored in ``bayes_tokens`` are already lowercase and an exact string
match is sufficient.

Warning: STOP THE BOT BEFORE RUNNING THIS SCRIPT. Rows are counted with a
``SELECT`` up front and deleted by condition later inside the transaction; if
the bot writes or updates a ``bayes_tokens`` row for a stopword in between, the
``DELETE`` could remove a row whose counts were not reflected in the printed
total (read-then-act TOCTOU window). Stop the bot, run the script, restart.

Usage::

    ./venv/bin/python3 scripts/delete_stopwords.py <dbPath>
    ./venv/bin/python3 scripts/delete_stopwords.py <dbPath> --dry-run
    ./venv/bin/python3 scripts/delete_stopwords.py <dbPath> -n

Args:
    dbPath: Positional path to a SQLite database file.
    --dry-run, -n: Report how many rows would be deleted without writing to the DB.

Returns:
    Exit code 0 on success, non-zero on argument, validation, or runtime error.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the repository root is on sys.path so that project packages
# (internal/, lib/) are importable when the script is run as:
#     ./venv/bin/python3 scripts/delete_stopwords.py
# In that invocation Python adds scripts/ to sys.path, not the repo root.
# ---------------------------------------------------------------------------
_REPO_ROOT = str(Path(__file__).parent.parent.resolve())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lib.bayes_filter.tokenizer import TokenizerConfig  # noqa: E402


def getStopwords() -> set[str]:
    """Return the tokenizer's current default stopword set.

    Delegates to ``TokenizerConfig().getStopwords()``, which yields the default
    set of common Russian and English stopwords. This is the single
    source of truth the script deletes against.

    Returns:
        A set of lowercase stopword strings.
    """
    return TokenizerConfig().getStopwords()


def processDatabase(dbPath: Path, dryRun: bool) -> int:
    """Count and optionally delete stopword rows from ``bayes_tokens``.

    Args:
        dbPath: Path to the SQLite database file (already validated to exist).
        dryRun: When ``True``, report how many rows would be deleted without writing.

    Returns:
        ``0`` on success, ``1`` if the ``bayes_tokens`` table is missing.
    """
    stopwords = getStopwords()

    # isolation_level=None puts the connection in autocommit mode so we drive
    # BEGIN / COMMIT / ROLLBACK by hand for the delete.
    conn = sqlite3.connect(str(dbPath), isolation_level=None)
    try:
        # Guard: the table must exist. A brand-new or wrong DB is a hard error.
        tableCursor = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'bayes_tokens'")
        if tableCursor.fetchone() is None:
            print("error: table 'bayes_tokens' does not exist in this database", file=sys.stderr)
            return 1

        # Build IN (?, ?, ...) for the stopword set. SQLite's default variable
        # cap (999) is far above the default stopword cardinality.
        placeholders = ",".join("?" for _ in stopwords)
        countSql = f"SELECT COUNT(*) FROM bayes_tokens WHERE token IN ({placeholders})"
        countCursor = conn.execute(countSql, tuple(stopwords))
        rowCount: int = countCursor.fetchone()[0]

        if rowCount == 0:
            print("No stopword tokens found in bayes_tokens.")
            return 0

        print(f"Found {rowCount} bayes_tokens row(s) matching a default stopword.")

        if dryRun:
            print("dry-run mode — no changes made")
            return 0

        conn.execute("BEGIN")
        try:
            deleteSql = f"DELETE FROM bayes_tokens WHERE token IN ({placeholders})"
            deleteCursor = conn.execute(deleteSql, tuple(stopwords))
            deleted = deleteCursor.rowcount
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    summary = f"Deleted {deleted} stopword token row(s)."
    if rowCount != deleted:
        summary += (
            f" ({abs(rowCount - deleted)} row(s) differ — the bot wrote/removed "
            "stopword rows during the scan; see TOCTOU note in the module docstring.)"
        )
    print(summary)
    return 0


def main() -> int:
    """Entry point: parse CLI args, validate the db path, and run the delete.

    Returns:
        ``0`` on success, ``1`` on argument, validation, or runtime error.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Delete rows from the bayes_tokens table whose token is a current default "
            "tokenizer stopword (TokenizerConfig.getStopwords())."
        ),
    )
    parser.add_argument("dbPath", type=Path, help="Path to the SQLite database file.")
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        dest="dryRun",
        help="Report how many rows would be deleted without writing to the DB.",
    )
    args = parser.parse_args()

    dbPath: Path = args.dbPath
    if not dbPath.exists() or not dbPath.is_file():
        print(f"error: dbPath does not exist or is not a file: {dbPath}", file=sys.stderr)
        return 1

    try:
        return processDatabase(dbPath, args.dryRun)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
