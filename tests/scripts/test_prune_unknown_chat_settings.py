"""Tests for scripts/prune_unknown_chat_settings.py.

Covers the ``processDatabase`` prune operation against throwaway SQLite files:
dry-run leaving the DB untouched, the real run deleting only unknown-key rows
while valid (in-enum) keys survive, the missing-table guard, the empty-result
("no unknown settings") path, idempotency on a second run, multi-chat counting,
and the TOCTOU ``rowCount != deleted`` summary branch.

These tests build a throwaway ``chat_settings``-like table on a ``tmp_path``
SQLite file and never touch real bot state. The valid key set is read live from
``ChatSettingsKey`` — the same source the script itself uses — so the tests
track the enum automatically.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from internal.bot.models.chat_settings import ChatSettingsKey  # noqa: E402
from scripts.prune_unknown_chat_settings import processDatabase  # noqa: E402

# Two real ChatSettingsKey values used to build "valid" rows that must survive
# the prune. Read live so the test tracks the enum automatically.
_VALID_KEY_1: str = ChatSettingsKey.MEMORY_ENABLED.value  # "memory-enabled"
_VALID_KEY_2: str = ChatSettingsKey.CHAT_MODEL.value  # "chat-model"

# Keys that are NOT in the ChatSettingsKey enum — simulate retired keys that
# linger as orphan rows.
_UNKNOWN_KEY_1: str = "memory-embeddings-enabled"
_UNKNOWN_KEY_2: str = "regenerate-embeddings"
_UNKNOWN_KEY_3: str = "memory-retrieval-mode"


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


def _makeChatSettingsTable(dbPath: Path) -> None:
    """Create a ``chat_settings`` table matching the production schema subset.

    Only the columns the script touches (``chat_id``, ``key``, ``value``) plus
    the production composite PK are included.

    Args:
        dbPath: Path of the SQLite file to create the table in.
    """
    _exec(
        dbPath,
        "CREATE TABLE chat_settings ("
        "chat_id INTEGER NOT NULL, "
        "key TEXT NOT NULL, "
        "value TEXT, "
        "PRIMARY KEY (chat_id, key)"
        ")",
    )


def _insertSetting(dbPath: Path, chatId: int, key: str, value: str) -> None:
    """Insert one ``chat_settings`` row.

    Args:
        dbPath: Path of the SQLite file.
        chatId: Chat id (PK column).
        key: Setting key string (PK column).
        value: Setting value string.
    """
    _exec(
        dbPath,
        "INSERT INTO chat_settings (chat_id, key, value) VALUES (?, ?, ?)",
        (chatId, key, value),
    )


def _countRows(dbPath: Path) -> int:
    """Count all rows in ``chat_settings``.

    Args:
        dbPath: Path of the SQLite file.

    Returns:
        The total number of rows in the ``chat_settings`` table.
    """
    conn = sqlite3.connect(str(dbPath))
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM chat_settings")
        row: tuple[int] | None = cursor.fetchone()
    finally:
        conn.close()
    return row[0] if row is not None else 0


def _readAllKeys(dbPath: Path) -> list[tuple[int, str]]:
    """Read every ``(chat_id, key)`` pair from ``chat_settings``, sorted.

    Args:
        dbPath: Path of the SQLite file.

    Returns:
        A sorted list of ``(chat_id, key)`` tuples for all rows.
    """
    conn = sqlite3.connect(str(dbPath))
    try:
        cursor = conn.execute("SELECT chat_id, key FROM chat_settings ORDER BY chat_id, key")
        rows: list[tuple[int, str]] = [(r[0], r[1]) for r in cursor.fetchall()]
    finally:
        conn.close()
    return rows


class _RowcountOverrideCursor:
    """Cursor wrapper reporting a fake ``rowcount`` for TOCTOU-branch testing.

    The real cursor delegates everything except ``rowcount``, which returns a
    forced value to simulate a concurrent write between the SELECT and DELETE
    inside :func:`processDatabase`.

    Attributes:
        _real: The underlying real sqlite3 cursor to delegate to.
        _fakeRowCount: The rowcount value this wrapper reports.
    """

    def __init__(self, real: sqlite3.Cursor, fakeRowCount: int) -> None:
        """Store the real cursor and the override rowcount.

        Args:
            real: The underlying cursor to delegate attribute access to.
            fakeRowCount: The rowcount value to report.
        """
        self._real = real
        self._fakeRowCount = fakeRowCount

    @property
    def rowcount(self) -> int:
        """Return the overridden rowcount."""
        return self._fakeRowCount

    def fetchone(self) -> tuple[object, ...] | None:
        """Delegate fetchone to the real cursor.

        Returns:
            The next row tuple, or ``None`` if no more rows.
        """
        return self._real.fetchone()

    def fetchall(self) -> list[tuple[object, ...]]:
        """Delegate fetchall to the real cursor.

        Returns:
            All remaining rows as a list of tuples.
        """
        return self._real.fetchall()

    def __getattr__(self, name: str) -> object:
        """Delegate any other attribute access to the real cursor.

        Args:
            name: The attribute name to look up.

        Returns:
            The attribute value from the real cursor.
        """
        return getattr(self._real, name)


class _ToctouConnection:
    """Connection wrapper that intercepts the DELETE cursor for TOCTOU testing.

    Delegates every call to the underlying real sqlite3 connection, except
    ``execute``: when the SQL is the ``DELETE FROM chat_settings`` statement
    issued by :func:`processDatabase`, the returned cursor is wrapped in a
    :class:`_RowcountOverrideCursor` so its ``rowcount`` differs from the
    SELECT row count. This triggers the TOCTOU summary note in the script's
    output.

    Attributes:
        _real: The underlying real sqlite3 connection to delegate to.
        _fakeDeleteRowCount: The fake rowcount the DELETE cursor reports.
    """

    def __init__(self, real: sqlite3.Connection, fakeDeleteRowCount: int) -> None:
        """Store the real connection and the override rowcount.

        Args:
            real: The underlying connection to delegate to.
            fakeDeleteRowCount: The rowcount value the DELETE cursor reports.
        """
        self._real = real
        self._fakeDeleteRowCount = fakeDeleteRowCount

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> sqlite3.Cursor | _RowcountOverrideCursor:
        """Execute SQL, wrapping the DELETE cursor with a fake rowcount.

        Args:
            sql: The SQL statement to execute.
            parameters: Bind parameters for the statement.

        Returns:
            The cursor for the statement; for the DELETE, a wrapper with an
            overridden rowcount; otherwise the real cursor unchanged.
        """
        cursor = self._real.execute(sql, parameters)
        if "DELETE FROM chat_settings" in sql:
            return _RowcountOverrideCursor(cursor, self._fakeDeleteRowCount)
        return cursor

    def close(self) -> None:
        """Delegate close to the real connection."""
        self._real.close()

    def __getattr__(self, name: str) -> object:
        """Delegate any other attribute access to the real connection.

        Args:
            name: The attribute name to look up.

        Returns:
            The attribute value from the real connection.
        """
        return getattr(self._real, name)


# ---------------------------------------------------------------------------
# processDatabase -- prune operation + DB-level coverage
# ---------------------------------------------------------------------------


class TestProcessDatabase:
    """Cover the ``processDatabase`` prune path against a tmp_path SQLite file."""

    def testDryRunLeavesDbUnmodified(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """``dryRun=True`` reports what would be deleted but changes nothing."""
        dbPath = tmp_path / "bot.db"
        _makeChatSettingsTable(dbPath)
        _insertSetting(dbPath, chatId=1, key=_UNKNOWN_KEY_1, value="true")
        _insertSetting(dbPath, chatId=1, key=_VALID_KEY_1, value="true")

        rc = processDatabase(dbPath, dryRun=True)
        out = capsys.readouterr().out

        assert rc == 0
        assert "would delete 1" in out
        # DB must be untouched under dry-run: both rows still present.
        assert _countRows(dbPath) == 2
        assert (1, _UNKNOWN_KEY_1) in _readAllKeys(dbPath)
        assert (1, _VALID_KEY_1) in _readAllKeys(dbPath)

    def testDeletesOnlyUnknownKeys(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Real run deletes unknown-key rows while valid (in-enum) keys survive."""
        dbPath = tmp_path / "bot.db"
        _makeChatSettingsTable(dbPath)
        _insertSetting(dbPath, chatId=1, key=_UNKNOWN_KEY_1, value="true")
        _insertSetting(dbPath, chatId=1, key=_UNKNOWN_KEY_2, value="false")
        _insertSetting(dbPath, chatId=1, key=_VALID_KEY_1, value="true")
        _insertSetting(dbPath, chatId=2, key=_VALID_KEY_2, value="gpt-4")

        rc = processDatabase(dbPath, dryRun=False)
        out = capsys.readouterr().out

        assert rc == 0
        assert "deleted 2" in out
        remaining = _readAllKeys(dbPath)
        # Only the two valid keys survive.
        assert remaining == [(1, _VALID_KEY_1), (2, _VALID_KEY_2)]
        assert _countRows(dbPath) == 2

    def testMissingTableReturnsNonZero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A DB without the ``chat_settings`` table returns exit code 1 (no crash)."""
        dbPath = tmp_path / "bot.db"
        # Create a DB file with an unrelated table but no chat_settings.
        _exec(dbPath, "CREATE TABLE unrelated (id INTEGER)")

        rc = processDatabase(dbPath, dryRun=False)
        captured = capsys.readouterr()

        assert rc == 1
        assert "chat_settings" in captured.err.lower()

    def testNoUnknownKeysFound(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A DB where every key is in the enum prints the 'no unknown' message and exits 0."""
        dbPath = tmp_path / "bot.db"
        _makeChatSettingsTable(dbPath)
        _insertSetting(dbPath, chatId=1, key=_VALID_KEY_1, value="true")
        _insertSetting(dbPath, chatId=2, key=_VALID_KEY_2, value="gpt-4")

        rc = processDatabase(dbPath, dryRun=False)
        out = capsys.readouterr().out

        assert rc == 0
        assert "No unknown settings found" in out
        # Nothing deleted.
        assert _countRows(dbPath) == 2

    def testIdempotencySecondRunDeletesZero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A second run over an already-pruned DB finds and deletes zero rows."""
        dbPath = tmp_path / "bot.db"
        _makeChatSettingsTable(dbPath)
        _insertSetting(dbPath, chatId=1, key=_UNKNOWN_KEY_1, value="true")
        _insertSetting(dbPath, chatId=1, key=_VALID_KEY_1, value="true")

        firstRc = processDatabase(dbPath, dryRun=False)
        firstOut = capsys.readouterr().out
        assert firstRc == 0
        assert "deleted 1" in firstOut

        snapshot = _readAllKeys(dbPath)

        secondRc = processDatabase(dbPath, dryRun=False)
        secondOut = capsys.readouterr().out
        assert secondRc == 0
        assert "No unknown settings found" in secondOut
        # DB unchanged after second run.
        assert _readAllKeys(dbPath) == snapshot

    def testMultipleChatsCounter(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Unknown rows spread across multiple chats report the correct chat count."""
        dbPath = tmp_path / "bot.db"
        _makeChatSettingsTable(dbPath)
        _insertSetting(dbPath, chatId=1, key=_UNKNOWN_KEY_1, value="true")
        _insertSetting(dbPath, chatId=2, key=_UNKNOWN_KEY_2, value="false")
        _insertSetting(dbPath, chatId=2, key=_UNKNOWN_KEY_3, value="latest")
        _insertSetting(dbPath, chatId=3, key=_VALID_KEY_1, value="true")

        rc = processDatabase(dbPath, dryRun=True)
        out = capsys.readouterr().out

        assert rc == 0
        # 3 unknown rows across 2 chats.
        assert "3 unknown setting row(s) across 2 chat(s)" in out
        assert "would delete 3" in out

    def testRowCountMismatchPrintsToctouNote(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The TOCTOU branch fires when ``deleted != rowCount`` and prints the differ note.

        Simulates a concurrent bot write by monkeypatching ``sqlite3.connect``
        to return a wrapper connection whose DELETE cursor reports a rowcount
        different from the SELECT row count. This exercises the ``rowCount !=
        deleted`` summary branch that is otherwise unreachable in a
        single-connection test.
        """
        dbPath = tmp_path / "bot.db"
        _makeChatSettingsTable(dbPath)
        _insertSetting(dbPath, chatId=1, key=_UNKNOWN_KEY_1, value="true")
        _insertSetting(dbPath, chatId=1, key=_UNKNOWN_KEY_2, value="false")

        realConnect = sqlite3.connect

        def fakeConnect(database: str, *, isolation_level: str | None = None) -> _ToctouConnection:
            """Wrap the real connection so the DELETE cursor lies about rowcount.

            Args:
                database: Path to the SQLite file.
                isolation_level: sqlite3 isolation level (passed through).

            Returns:
                A :class:`_ToctouConnection` whose DELETE reports 999 deleted.
            """
            # The script always passes isolation_level=None; hardcode it here
            # so pyright does not widen the pass-through type.
            realConn = realConnect(database, isolation_level=None)
            return _ToctouConnection(realConn, fakeDeleteRowCount=999)

        monkeypatch.setattr(sqlite3, "connect", fakeConnect)

        rc = processDatabase(dbPath, dryRun=False)
        out = capsys.readouterr().out

        assert rc == 0
        # rowCount=2 (found), deleted=999 (fake) → mismatch note in summary.
        assert "differ" in out
        assert "TOCTOU" in out
