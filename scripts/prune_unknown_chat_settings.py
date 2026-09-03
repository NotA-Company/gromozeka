#!/usr/bin/env ./venv/bin/python3
"""Delete orphaned rows from the ``chat_settings`` table.

Over the life of the project, chat-setting keys have been removed and renamed.
Rows for retired keys linger in the ``chat_settings`` table of existing
databases: dead data that nothing reads or writes anymore, plus a little
wasted space. This standalone maintenance script walks ``chat_settings``,
finds every row whose ``key`` is NOT a member of the current
``ChatSettingsKey`` enum (the single source of truth for valid keys), prints
each one, and -- unless ``--dry-run`` is given -- deletes them in a single
transaction.

The valid key set is read live from ``ChatSettingsKey``
([`internal.bot.models.chat_settings`](internal/bot/models/chat_settings.py)),
so it tracks the enum automatically: no key strings are hardcoded here.

Note on the ``memory-injection-enabled`` rename: that key was renamed to
``memory-enabled`` by migration 023. If that migration has NOT yet
been applied to a database, ``memory-injection-enabled`` is not in
``ChatSettingsKey`` and this script will flag it as unknown. The operator
should run the rename migration FIRST (to preserve the old value under the new
key), and only then run this script to prune the genuinely-removed keys
(``regenerate-embeddings``, ``memory-regenerate-embeddings``,
``memory-embeddings-enabled``, ``memory-retrieval-mode``, and any other
historical cruft). Running this script before the rename migration would
delete the not-yet-renamed row, losing that setting's value.

Warning: stop the bot before running this script. Rows are scanned with a
``SELECT`` up front and deleted by condition later inside the transaction; if
the bot writes a new ``chat_settings`` row (or rewrites an existing one) with
an unknown key in between, the ``DELETE`` could remove a row that was not in
the printed list, or the printed list could show a row the bot has already
overwritten (read-then-act TOCTOU window). Stop the bot, run the script,
restart.

Usage::

    ./venv/bin/python3 scripts/prune_unknown_chat_settings.py <dbPath>
    ./venv/bin/python3 scripts/prune_unknown_chat_settings.py <dbPath> --dry-run
    ./venv/bin/python3 scripts/prune_unknown_chat_settings.py <dbPath> -n

Args:
    dbPath: Positional path to a SQLite database file.
    --dry-run, -n: Report what would be deleted without writing to the DB.

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
#     ./venv/bin/python3 scripts/prune_unknown_chat_settings.py
# In that invocation Python adds scripts/ to sys.path, not the repo root.
# ---------------------------------------------------------------------------
_REPO_ROOT = str(Path(__file__).parent.parent.resolve())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import httpx2  # noqa: E402

# Process-wide: make `import httpx` resolve to `httpx2` so third-party clients
# used by project code (sqlink's transport via lib.db.providers, the openai SDK
# via lib.ai providers) share the bot's httpx2 stack. MUST run before the
# first project import below: internal.* / lib.* modules transitively perform
# a real `import httpx`, after which scripts._lib.bootstrap's module-level
# alias_httpx() would raise RuntimeError. The call is idempotent, so
# bootstrap's later repeat invocation is a no-op. House pattern: main.py:16-37;
# background: docs/design/httpx2-migration-v1.md §6.
httpx2.alias_httpx()

from internal.bot.models.chat_settings import ChatSettingsKey  # noqa: E402


def _collectValidKeys() -> set[str]:
    """Build the set of currently-valid chat-setting keys.

    Reads every member value of ``ChatSettingsKey``. The enum stores the TOML
    string form (e.g. ``"memory-enabled"``), which is exactly what the
    ``chat_settings.key`` column holds.

    Returns:
        A set of valid key strings.
    """
    return {member.value for member in ChatSettingsKey}


def processDatabase(dbPath: Path, dryRun: bool) -> int:
    """Find and optionally delete unknown-key rows from ``chat_settings``.

    Args:
        dbPath: Path to the SQLite database file (already validated to exist).
        dryRun: When ``True``, report what would be deleted without writing.

    Returns:
        ``0`` on success, ``1`` if the ``chat_settings`` table is missing.
    """
    validKeys = _collectValidKeys()

    # isolation_level=None puts the connection in autocommit mode so we drive
    # BEGIN / COMMIT / ROLLBACK by hand for the delete.
    conn = sqlite3.connect(str(dbPath), isolation_level=None)
    try:
        # Guard: the table must exist. A brand-new or wrong DB is a hard error.
        tableCursor = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'chat_settings'")
        if tableCursor.fetchone() is None:
            print("error: table 'chat_settings' does not exist in this database", file=sys.stderr)
            return 1

        # Build NOT IN (?, ?, ...) for the valid key set. SQLite's default
        # variable cap (999) is far above the ChatSettingsKey cardinality (~90).
        placeholders = ",".join("?" for _ in validKeys)
        selectSql = (
            f"SELECT chat_id, key, value FROM chat_settings " f"WHERE key NOT IN ({placeholders}) ORDER BY chat_id, key"
        )
        cursor = conn.execute(selectSql, tuple(validKeys))
        unknownRows: list[tuple[int, str, str | None]] = cursor.fetchall()

        if not unknownRows:
            print("No unknown settings found.")
            return 0

        affectedChats: set[int] = {row[0] for row in unknownRows}
        for chatId, key, value in unknownRows:
            print(f"chat_id={chatId} key={key!r} value={value!r}")

        rowCount = len(unknownRows)
        chatCount = len(affectedChats)

        if dryRun:
            print(f"Found {rowCount} unknown setting row(s) across {chatCount} chat(s); " f"would delete {rowCount}.")
            return 0

        conn.execute("BEGIN")
        try:
            deleteSql = f"DELETE FROM chat_settings WHERE key NOT IN ({placeholders})"
            deleteCursor = conn.execute(deleteSql, tuple(validKeys))
            deleted = deleteCursor.rowcount
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    summary = f"Found {rowCount} unknown row(s); deleted {deleted}."
    if rowCount != deleted:
        summary += (
            f" ({abs(rowCount - deleted)} row(s) differ — the bot wrote/removed "
            "unknown-key rows during the scan; see TOCTOU note in the module docstring.)"
        )
    print(summary)
    return 0


def main() -> int:
    """Entry point: parse CLI args, validate the db path, and run the prune.

    Returns:
        ``0`` on success, ``1`` on argument, validation, or runtime error.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Delete rows from the chat_settings table whose key is not a current " "ChatSettingsKey enum value."
        ),
    )
    parser.add_argument("dbPath", type=Path, help="Path to the SQLite database file.")
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        dest="dryRun",
        help="Report what would be deleted without writing to the DB.",
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
