#!/usr/bin/env ./venv/bin/python3
"""Drop all ``vec_user_memories_{N}`` vec0 virtual tables and clear embedding
provenance in ``user_memories`` so the regen cron fully re-embeds from scratch.

The memory-embedding subsystem stores each embedding model's vectors in a
dedicated sqlite-vec ``vec0`` virtual table named ``vec_user_memories_{N}``,
where ``{N}`` is the embedding dimensionality (e.g. ``384``, ``768``). Each
``user_memories`` row carries two provenance columns -- ``embedding_model`` and
``embedding_dimensions`` -- recording which model/dimension produced its stored
vector.

When the vec0 schema changes (e.g. the column layout of the virtual table is
extended), the regen cron needs every memory re-embedded from scratch. This
one-off maintenance script:

  1. Discovers every ``vec_user_memories_{N}`` virtual table via
     ``sqlite_master`` and filters out the internal shadow tables that
     sqlite-vec creates alongside each virtual table
     (``vec_user_memories_384_rowids``, ``vec_user_memories_384_chunks``, ...).
     Dropping the virtual table auto-drops its shadow tables; we must never
     drop shadow tables by hand.
  2. Drops each discovered virtual table (``DROP TABLE IF EXISTS``).
  3. Clears the embedding provenance on every ``user_memories`` row by setting
     ``embedding_model = NULL`` and ``embedding_dimensions = NULL``. The regen
     cron treats a NULL ``embedding_model`` as "needs re-embedding", so the
     next run fully repopulates the new-schema virtual tables.

Writes are issued in a single transaction (``BEGIN`` ... ``COMMIT``); any
unexpected error during the drop/update batch triggers ``ROLLBACK`` and a
non-zero exit, leaving the database untouched.

Warning: stop the bot before running this script. The ``DROP TABLE`` and
``UPDATE`` statements issued inside the transaction race against the bot's own
writes: if the bot inserts a ``user_memories`` row (or creates a vec0 table)
mid-transaction, you get a last-writer-wins clobber or a table-missing error.

Usage::

    ./venv/bin/python3 scripts/clear_memory_embeddings.py <dbPath>
    ./venv/bin/python3 scripts/clear_memory_embeddings.py <dbPath> --dry-run
    ./venv/bin/python3 scripts/clear_memory_embeddings.py <dbPath> -n
    ./venv/bin/python3 scripts/clear_memory_embeddings.py <dbPath> --vec-extension /path/to/vec0

Args:
    dbPath: Positional path to a SQLite database file.
    --dry-run, -n: Report what would change without writing to the DB.
    --vec-extension: Path to the vec0 shared library (overrides auto-detection
        via the sqlite-vec package). Required if the package is not installed.

Returns:
    Exit code 0 on success, non-zero on argument, validation, or runtime error.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path
from typing import Optional

# Optional dependency: the sqlite-vec pip package bundles the loadable vec0
# shared library and exposes its path via loadable_path(). When unavailable
# (e.g. Alpine Linux with no musl wheel), the caller must pass --vec-extension
# with a source-built path. Mirrors the production provider's pattern
# (internal/database/providers/sqlite3.py).
try:
    import sqlite_vec

    _SQLITE_VEC_AVAILABLE = True
except ImportError:
    _SQLITE_VEC_AVAILABLE = False

# Matches only the vec0 virtual tables (``vec_user_memories_384``,
# ``vec_user_memories_768``, ...) and excludes the sqlite-vec shadow tables
# (``vec_user_memories_384_rowids``, ``vec_user_memories_384_chunks``, ...).
# Each table name matching this regex is safe to interpolate into a DROP
# statement; anything else from ``sqlite_master`` is left to be auto-cleaned
# by the vec0 extension when its parent virtual table is dropped. This is the
# same regex used by the production repository code
# (internal/database/repositories/user_memories.py).
_VEC_TABLE_RE: re.Pattern[str] = re.compile(r"^vec_user_memories_\d+$")

# Broad LIKE prefix for the initial ``sqlite_master`` scan; shadow tables share
# this prefix, so the Python regex filter above is what actually selects the
# virtual tables to drop.
_VEC_TABLE_LIKE: str = "vec_user_memories_%"

# Fixed-width label column for the summary output (matches the sibling
# clear_memory_refinement.py / clear_old_format_memories.py scripts).
_LABEL_WIDTH: int = 18


def _discoverVecTables(conn: sqlite3.Connection) -> list[str]:
    """Return the sorted list of ``vec_user_memories_{N}`` virtual tables to drop.

    Queries ``sqlite_master`` for every table whose name starts with the vec0
    prefix, then keeps only those matching ``_VEC_TABLE_RE`` (the virtual
    tables). Internal shadow tables are filtered out: dropping a virtual table
    auto-drops its shadow tables, so we never drop those by hand.

    Args:
        conn: An open SQLite connection (read-only use).

    Returns:
        A sorted list of virtual-table names matching the regex.
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = ? AND name LIKE ?",
        ("table", _VEC_TABLE_LIKE),
    )
    candidates: list[str] = [row[0] for row in cursor.fetchall()]
    return sorted(name for name in candidates if _VEC_TABLE_RE.match(name))


def _userMemoriesExists(conn: sqlite3.Connection) -> bool:
    """Check whether the ``user_memories`` table exists.

    Args:
        conn: An open SQLite connection (read-only use).

    Returns:
        ``True`` if a table named ``user_memories`` exists.
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = ? AND name = ?",
        ("table", "user_memories"),
    )
    return cursor.fetchone() is not None


def _loadVecExtension(conn: sqlite3.Connection, vecExtensionPath: Optional[str]) -> Optional[str]:
    """Load the sqlite-vec (vec0) extension into the connection.

    SQLite cannot DROP a vec0 virtual table unless the vec0 module is
    registered, which only happens once the shared library is loaded. This
    mirrors the production provider's loading sequence
    (internal/database/providers/sqlite3.py) but uses the synchronous
    stdlib ``sqlite3`` API since this script is not async.

    Extension-source resolution, in priority order:
      1. ``vecExtensionPath`` (from ``--vec-extension``) if provided -- takes
         precedence over everything.
      2. ``sqlite_vec.loadable_path()`` when the pip package is importable.
      3. ``None`` -- no source available; the caller should warn and continue.

    Loading is best-effort: on any failure (Python built without extension
    support, missing shared library, permission denied) ``None`` is returned
    so the caller can print a warning and proceed -- plain tables still DROP
    fine without the module, which matters for tests and for users who want
    to force the operation.

    Args:
        conn: An open ``sqlite3.Connection``.
        vecExtensionPath: Explicit path to the vec0 shared library
            (``--vec-extension``), or ``None`` to auto-detect via the
            ``sqlite_vec`` package.

    Returns:
        The vec0 version string (from ``SELECT vec_version()``) on success,
        or ``None`` if no extension source is available or loading failed.

    Note:
        Unlike the production provider (which prefers the pip-package path),
        an explicit ``vecExtensionPath`` takes priority here -- the CLI caller
        is asserting intent.
    """
    if vecExtensionPath is not None:
        extensionSource: Optional[str] = vecExtensionPath
    elif _SQLITE_VEC_AVAILABLE:
        extensionSource = sqlite_vec.loadable_path()
    else:
        return None

    # Two-layer try: the outer catches enable_load_extension(True) failures
    # (e.g. macOS Apple Python compiled without extension support); the inner
    # try/finally guarantees extension loading is always re-disabled, even
    # when load_extension() or vec_version() raises.
    try:
        conn.enable_load_extension(True)
        try:
            conn.load_extension(extensionSource)
            cursor = conn.execute("SELECT vec_version()")
            versionRow: tuple[str] | None = cursor.fetchone()
            if versionRow is None:
                return None
            return versionRow[0]
        finally:
            conn.enable_load_extension(False)
    except Exception:
        return None


def _printSummary(droppedCount: int, rowsCleared: int, userMemoriesExists: bool, dryRun: bool) -> None:
    """Print the fixed-width counter summary.

    Args:
        droppedCount: Number of vec0 virtual tables dropped (or to be dropped).
        rowsCleared: Number of ``user_memories`` rows cleared (or to be cleared).
        userMemoriesExists: Whether ``user_memories`` existed (controls whether
            the rows line is printed at all).
        dryRun: When ``True``, labels read "to drop" / "to clear".

    Returns:
        None
    """
    dropLabel = "Tables to drop:" if dryRun else "Tables dropped:"
    print(f"{dropLabel:<{_LABEL_WIDTH}}{droppedCount}")
    if userMemoriesExists:
        clearLabel = "Rows to clear:" if dryRun else "Rows cleared:"
        print(f"{clearLabel:<{_LABEL_WIDTH}}{rowsCleared}")


def processDatabase(dbPath: Path, dryRun: bool, vecExtensionPath: Optional[str] = None) -> int:
    """Drop vec0 virtual tables and null ``user_memories`` embedding provenance.

    Discovers every ``vec_user_memories_{N}`` virtual table, counts the
    ``user_memories`` rows whose provenance will be cleared, and either prints
    a dry-run summary or issues all ``DROP`` + ``UPDATE`` statements inside a
    single transaction.

    The vec0 extension is loaded right after connecting (see
    :func:`_loadVecExtension`); without it, SQLite raises
    ``no such module: vec0`` when DROP is attempted on a real virtual table.
    Loading is best-effort: plain tables (e.g. in tests) drop fine without
    the module.

    Args:
        dbPath: Path to the SQLite database file (already validated to exist).
        dryRun: When ``True``, report changes without writing to the DB.
        vecExtensionPath: Explicit path to the vec0 shared library
            (``--vec-extension``), or ``None`` to auto-detect via the
            ``sqlite_vec`` package.

    Returns:
        ``0`` on success.
    """
    # isolation_level=None puts the connection in autocommit mode so we drive
    # BEGIN / COMMIT / ROLLBACK by hand for the drop+update batch.
    conn = sqlite3.connect(str(dbPath), isolation_level=None)
    try:
        # Load the vec0 extension before any DROP -- a real vec0 virtual table
        # cannot be dropped without the module registered. Best-effort: if
        # loading fails, warn and continue (plain tables still drop fine).
        vecVersion = _loadVecExtension(conn, vecExtensionPath)
        if vecVersion is not None:
            print(f"[load] vec0 extension v{vecVersion}")
        else:
            sys.stderr.write("warning: vec0 extension not loaded -- DROP will fail on real vec0 virtual tables\n")
        vecTables: list[str] = _discoverVecTables(conn)

        userMemoriesExists = _userMemoriesExists(conn)
        rowsToClear = 0
        if userMemoriesExists:
            cursor = conn.execute("SELECT COUNT(*) FROM user_memories")
            countRow: tuple[int] | None = cursor.fetchone()
            rowsToClear = countRow[0] if countRow is not None else 0
        else:
            print(
                "note: 'user_memories' table not found; skipping provenance clear.",
                file=sys.stderr,
            )

        # Per-table detail: printed in both modes since the table count is
        # small (typically 1-3 virtual tables).
        tag = "would-drop" if dryRun else "drop"
        for tableName in vecTables:
            print(f"[{tag}] {tableName}")

        if dryRun:
            _printSummary(
                droppedCount=len(vecTables),
                rowsCleared=rowsToClear,
                userMemoriesExists=userMemoriesExists,
                dryRun=True,
            )
            return 0

        conn.execute("BEGIN")
        try:
            for tableName in vecTables:
                # Table name is regex-validated against _VEC_TABLE_RE
                # (^vec_user_memories_\d+$) by _discoverVecTables, so string
                # interpolation into DDL is safe here -- no injection surface.
                conn.execute(f"DROP TABLE IF EXISTS {tableName}")
            if userMemoriesExists:
                conn.execute("UPDATE user_memories " "SET embedding_model = NULL, embedding_dimensions = NULL")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    _printSummary(
        droppedCount=len(vecTables),
        rowsCleared=rowsToClear,
        userMemoriesExists=userMemoriesExists,
        dryRun=False,
    )
    return 0


def main() -> int:
    """Entry point: parse CLI args, validate the db path, and run the clear.

    Returns:
        ``0`` on success, ``1`` on argument, validation, or runtime error.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Drop all vec_user_memories_{N} vec0 virtual tables and clear the "
            "embedding_model/embedding_dimensions columns in user_memories of "
            "a SQLite database, so the regen cron re-embeds all memories from "
            "scratch."
        ),
    )
    parser.add_argument("dbPath", type=Path, help="Path to the SQLite database file.")
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        dest="dryRun",
        help="Report what would change without writing to the DB.",
    )
    parser.add_argument(
        "--vec-extension",
        dest="vecExtension",
        default=None,
        help=(
            "Path to the vec0 shared library (.so/.dylib). Overrides "
            "auto-detection via the sqlite-vec package. Required if the "
            "sqlite-vec package is not installed."
        ),
    )
    args = parser.parse_args()

    dbPath: Path = args.dbPath
    if not dbPath.exists() or not dbPath.is_file():
        print(f"error: dbPath does not exist or is not a file: {dbPath}", file=sys.stderr)
        return 1

    try:
        return processDatabase(dbPath, args.dryRun, args.vecExtension)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
