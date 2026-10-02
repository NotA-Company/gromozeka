"""Tests for scripts/clear_memory_embeddings.py.

Covers the drop + clear operation against throwaway SQLite files: vec0 virtual
table discovery (including shadow-table filtering), provenance nulling,
dry-run leaving the DB untouched, missing-table graceful handling, and
multiple-dimension scenarios.

These tests build a throwaway DB on a ``tmp_path`` file and never touch real
bot state. The "virtual tables" are plain ``CREATE TABLE`` tables -- the DROP
logic is identical whether the table is a vec0 virtual table or a plain one;
the point of the test is the discovery regex, the DROP, and the UPDATE.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Mirror the script's optional-import probe so the vec0-virtual-table test can
# skip gracefully when the sqlite-vec package is unavailable or the Python
# build lacks extension-loading support (e.g. some CI Pythons).
try:
    import sqlite_vec as _sqliteVec  # pyright: ignore[reportMissingImports]

    _SQLITE_VEC_AVAILABLE = True
except ImportError:
    _SQLITE_VEC_AVAILABLE = False


def _extensionLoadSupported() -> bool:
    """Return ``True`` if the stdlib sqlite3 supports extension loading.

    Some Python builds (notably Apple's system Python on macOS) compile the
    sqlite3 module without loadable-extension support, or ship a stub where
    ``enable_load_extension`` exists as an attribute but raises when called.
    The vec0-virtual-table test depends on a working load path, so this probes
    with a live call rather than relying on ``hasattr``.

    Returns:
        ``True`` when a live ``enable_load_extension(True)`` call succeeds.
    """
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.enable_load_extension(True)
            return True
        finally:
            conn.close()
    except Exception:
        return False


from scripts.clear_memory_embeddings import processDatabase  # noqa: E402


def _exec(dbPath: Path, sql: str, params: tuple[object, ...] = ()) -> None:
    """Execute one SQL statement against a tmp DB and close immediately.

    Args:
        dbPath: Path of the SQLite file.
        sql: SQL statement to execute.
        params: Bind parameters for the statement.

    Returns:
        None
    """
    conn = sqlite3.connect(str(dbPath))
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _makeUserMemoriesTable(dbPath: Path) -> None:
    """Create a ``user_memories`` table matching the production schema subset.

    Only the column this script touches (``model_id``) plus a minimal PK
    are included.

    Args:
        dbPath: Path of the SQLite file to create the table in.
    """
    _exec(
        dbPath,
        "CREATE TABLE user_memories ("
        "chat_id INTEGER NOT NULL, "
        "user_id INTEGER NOT NULL, "
        "memory_id TEXT NOT NULL, "
        "model_id INTEGER, "
        "PRIMARY KEY (chat_id, user_id, memory_id)"
        ")",
    )


def _insertMemory(
    dbPath: Path,
    chatId: int,
    userId: int,
    memoryId: str,
    modelId: int | None,
) -> None:
    """Insert one ``user_memories`` row with embedding provenance.

    Args:
        dbPath: Path of the SQLite file.
        chatId: Chat id (PK column).
        userId: User id (PK column).
        memoryId: Memory id (PK column).
        modelId: Value for the ``model_id`` column (FK-like integer into
            the ``models`` lookup table, or ``None`` when not yet embedded).
    """
    _exec(
        dbPath,
        "INSERT INTO user_memories " "(chat_id, user_id, memory_id, model_id) " "VALUES (?, ?, ?, ?)",
        (chatId, userId, memoryId, modelId),
    )


def _fetchModelId(
    dbPath: Path,
    chatId: int,
    userId: int,
    memoryId: str,
) -> int | None:
    """Read the ``model_id`` value for one row.

    Args:
        dbPath: Path of the SQLite file.
        chatId: Chat id to select.
        userId: User id to select.
        memoryId: Memory id to select.

    Returns:
        The ``model_id`` value for the row (or ``None`` when NULL).
    """
    conn = sqlite3.connect(str(dbPath))
    try:
        cursor = conn.execute(
            "SELECT model_id " "FROM user_memories WHERE chat_id = ? AND user_id = ? AND memory_id = ?",
            (chatId, userId, memoryId),
        )
        row: tuple[int | None] | None = cursor.fetchone()
    finally:
        conn.close()
    assert row is not None, f"row not found chat_id={chatId} user_id={userId} memory_id={memoryId}"
    return row[0]


def _listVecTables(dbPath: Path) -> list[str]:
    """Return all table names starting with ``vec_user_memories_`` in the DB.

    Args:
        dbPath: Path of the SQLite file.

    Returns:
        A sorted list of table names matching the vec0 prefix.
    """
    conn = sqlite3.connect(str(dbPath))
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'vec_user_memories_%'")
        return sorted(row[0] for row in cursor.fetchall())
    finally:
        conn.close()


def _countMemoriesWithProvenance(dbPath: Path) -> int:
    """Count rows in ``user_memories`` with non-null ``model_id``.

    Args:
        dbPath: Path of the SQLite file.

    Returns:
        The number of rows where ``model_id IS NOT NULL``.
    """
    conn = sqlite3.connect(str(dbPath))
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM user_memories WHERE model_id IS NOT NULL")
        row: tuple[int] | None = cursor.fetchone()
    finally:
        conn.close()
    return row[0] if row is not None else 0


def _parseCounter(stdout: str, label: str) -> int:
    """Parse one fixed-width counter line out of the script's summary output.

    Args:
        stdout: The captured stdout from ``processDatabase``.
        label: The label prefix to find (e.g. ``"Tables dropped:"``).

    Returns:
        The integer following the label.
    """
    for line in stdout.splitlines():
        if line.strip().startswith(label):
            return int(line[len(label) :].strip())
    raise AssertionError(f"label {label!r} not found in output:\n{stdout}")


# ---------------------------------------------------------------------------
# processDatabase -- data operation + DB-level coverage
# ---------------------------------------------------------------------------


class TestProcessDatabase:
    """Cover the ``processDatabase`` write path against a tmp_path SQLite file."""

    def testDropsVecTablesAndClearsProvenance(self, tmp_path: Path) -> None:
        """Vec0 table is dropped and user_memories provenance is nulled."""
        dbPath = tmp_path / "bot.db"
        _exec(dbPath, "CREATE TABLE vec_user_memories_384 (id INTEGER, embedding BLOB)")
        _makeUserMemoriesTable(dbPath)
        _insertMemory(dbPath, 1, 10, "mem-1", 1)
        _insertMemory(dbPath, 1, 10, "mem-2", 1)
        _insertMemory(dbPath, 1, 10, "mem-3", None)

        rc = processDatabase(dbPath, dryRun=False)

        assert rc == 0
        # Vec0 virtual table is gone.
        assert _listVecTables(dbPath) == []
        # All model_id values nulled, including the already-null row.
        for memoryId in ("mem-1", "mem-2", "mem-3"):
            assert (
                _fetchModelId(dbPath, chatId=1, userId=10, memoryId=memoryId) is None
            ), f"model_id not nulled for {memoryId}"

    def testDryRunLeavesDbUnmodified(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """``dryRun=True`` reports what would happen but changes nothing."""
        dbPath = tmp_path / "bot.db"
        _exec(dbPath, "CREATE TABLE vec_user_memories_384 (id INTEGER, embedding BLOB)")
        _makeUserMemoriesTable(dbPath)
        _insertMemory(dbPath, 1, 10, "mem-1", 1)

        rc = processDatabase(dbPath, dryRun=True)
        out = capsys.readouterr().out

        assert rc == 0
        assert _parseCounter(out, "Tables to drop:") == 1
        assert _parseCounter(out, "Rows to clear:") == 1
        # DB must be untouched under dry-run.
        assert _listVecTables(dbPath) == ["vec_user_memories_384"]
        assert _fetchModelId(dbPath, chatId=1, userId=10, memoryId="mem-1") == 1

    def testNoVecTablesRunsClean(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A DB with only user_memories (no vec0 tables) runs without error."""
        dbPath = tmp_path / "bot.db"
        _makeUserMemoriesTable(dbPath)
        _insertMemory(dbPath, 1, 10, "mem-1", 1)

        rc = processDatabase(dbPath, dryRun=False)
        out = capsys.readouterr().out

        assert rc == 0
        assert _parseCounter(out, "Tables dropped:") == 0
        # Provenance still cleared even with no vec tables to drop.
        assert _countMemoriesWithProvenance(dbPath) == 0

    def testNoUserMemoriesTable(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Missing user_memories is reported on stderr, not a crash; vec tables still dropped."""
        dbPath = tmp_path / "bot.db"
        _exec(dbPath, "CREATE TABLE vec_user_memories_384 (id INTEGER, embedding BLOB)")

        rc = processDatabase(dbPath, dryRun=False)
        captured = capsys.readouterr()

        assert rc == 0
        # Vec tables are still dropped.
        assert _listVecTables(dbPath) == []
        # A note about the missing table was emitted to stderr.
        assert "user_memories" in captured.err.lower()
        # No "Rows cleared:" line in stdout when user_memories is missing.
        assert "Rows cleared:" not in captured.out

    def testMultipleDimensionsAllDropped(self, tmp_path: Path) -> None:
        """Both ``vec_user_memories_384`` and ``_768`` are discovered and dropped."""
        dbPath = tmp_path / "bot.db"
        _exec(dbPath, "CREATE TABLE vec_user_memories_384 (id INTEGER, embedding BLOB)")
        _exec(dbPath, "CREATE TABLE vec_user_memories_768 (id INTEGER, embedding BLOB)")
        _makeUserMemoriesTable(dbPath)
        _insertMemory(dbPath, 1, 10, "mem-384", 1)
        _insertMemory(dbPath, 1, 10, "mem-768", 2)

        rc = processDatabase(dbPath, dryRun=False)

        assert rc == 0
        assert _listVecTables(dbPath) == []
        assert _countMemoriesWithProvenance(dbPath) == 0

    def testShadowTablesNotDropped(self, tmp_path: Path) -> None:
        """Shadow tables (``_rowids``, ``_chunks`` suffix) are NOT dropped by the script.

        In production, sqlite-vec auto-drops shadow tables when the parent
        virtual table is dropped. Here we use plain tables to verify the
        script's regex filter leaves shadow tables alone (it must not try to
        drop them manually).
        """
        dbPath = tmp_path / "bot.db"
        _exec(dbPath, "CREATE TABLE vec_user_memories_384 (id INTEGER, embedding BLOB)")
        # Shadow tables created by the vec0 extension alongside the virtual table.
        _exec(dbPath, "CREATE TABLE vec_user_memories_384_rowids (rowid INTEGER, id INTEGER)")
        _exec(dbPath, "CREATE TABLE vec_user_memories_384_chunks (id INTEGER, embedding BLOB)")
        _makeUserMemoriesTable(dbPath)
        _insertMemory(dbPath, 1, 10, "mem-1", 1)

        rc = processDatabase(dbPath, dryRun=False)

        assert rc == 0
        remaining = _listVecTables(dbPath)
        # Only the shadow tables remain; the virtual table was dropped.
        assert "vec_user_memories_384" not in remaining
        assert "vec_user_memories_384_rowids" in remaining
        assert "vec_user_memories_384_chunks" in remaining

    def testIdempotencySecondRunNoTables(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A second run finds zero vec tables and clears already-null provenance."""
        dbPath = tmp_path / "bot.db"
        _exec(dbPath, "CREATE TABLE vec_user_memories_384 (id INTEGER, embedding BLOB)")
        _makeUserMemoriesTable(dbPath)
        _insertMemory(dbPath, 1, 10, "mem-1", 1)

        firstRc = processDatabase(dbPath, dryRun=False)
        firstOut = capsys.readouterr().out
        assert firstRc == 0
        assert _parseCounter(firstOut, "Tables dropped:") == 1

        secondRc = processDatabase(dbPath, dryRun=False)
        secondOut = capsys.readouterr().out
        assert secondRc == 0
        assert _parseCounter(secondOut, "Tables dropped:") == 0
        assert _parseCounter(secondOut, "Rows cleared:") == 1

    @pytest.mark.skipif(
        not (_SQLITE_VEC_AVAILABLE and _extensionLoadSupported()),
        reason="sqlite-vec package unavailable or sqlite3 built without extension-loading support",
    )
    def testDropsRealVec0VirtualTable(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A real ``USING vec0`` virtual table is dropped (the bug this fixes).

        Regression for the ``no such module: vec0`` failure: without loading
        the vec0 extension, SQLite cannot drop a vec0 virtual table. This test
        creates a *real* ``USING vec0`` virtual table (not a plain table),
        runs ``processDatabase``, and asserts the table -- and its shadow
        tables -- are gone.
        """
        dbPath = tmp_path / "bot.db"
        # Create a real vec0 virtual table via the extension.
        conn = sqlite3.connect(str(dbPath))
        try:
            conn.enable_load_extension(True)
            conn.load_extension(_sqliteVec.loadable_path())
            conn.enable_load_extension(False)
            conn.execute("CREATE VIRTUAL TABLE vec_user_memories_384 USING vec0(embedding float[384])")
            # Insert one row so the shadow tables are materialised.
            conn.execute(
                "INSERT INTO vec_user_memories_384(rowid, embedding) VALUES (?, ?)",
                (1, b"\x00" * 1536),
            )
            conn.commit()
        finally:
            conn.close()

        # Sanity: the virtual table + at least one shadow table exist before.
        assert _listVecTables(dbPath) != []

        rc = processDatabase(dbPath, dryRun=False)
        captured = capsys.readouterr()

        assert rc == 0
        # The virtual table and all its shadow tables are gone.
        assert _listVecTables(dbPath) == []
        # The [load] info line confirms the extension was loaded by the script.
        assert "[load] vec0 extension" in captured.out

    def testExplicitBadPathWarnsAndContinues(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Explicit bad extension path warns and continues, still drops plain tables.

        Covers the ``--vec-extension`` explicit-path branch of
        :func:`_loadVecExtension` together with the best-effort warning +
        continuation path in :func:`processDatabase`: a bad path fails to load,
        the script emits a warning to stderr, and plain ``vec_user_memories_{N}``
        tables still DROP (they do not require the vec0 module).
        """
        dbPath = tmp_path / "bot.db"
        _exec(dbPath, "CREATE TABLE vec_user_memories_384 (id INTEGER)")
        rc = processDatabase(dbPath, dryRun=False, vecExtensionPath="/nonexistent/vec0.so")
        captured = capsys.readouterr()
        assert rc == 0
        assert "vec0 extension not loaded" in captured.err
        assert _listVecTables(dbPath) == []
