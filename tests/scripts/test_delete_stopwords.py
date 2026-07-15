"""Tests for scripts/delete_stopwords.py.

Covers the ``processDatabase`` delete operation against throwaway SQLite files:
dry-run leaving the DB untouched, the real run deleting only stopword rows
while non-stopword rows survive, the missing-table guard, the empty-result
("no stopword tokens found") path, idempotency on a second run, and multi-chat
counting.

These tests build a throwaway ``bayes_tokens``-like table on a ``tmp_path``
SQLite file and never touch real bot state. The stopword set is read live from
the script's own ``getStopwords()`` (which delegates to
``TokenizerConfig().getStopwords()``) — the same source the script itself uses
— so the tests track the default list automatically.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.delete_stopwords import getStopwords  # noqa: E402
from scripts.delete_stopwords import processDatabase  # noqa: E402

# The default stopword set, read live so the test tracks the tokenizer's
# list automatically. The script deletes by membership in exactly this set.
_STOPWORDS: set[str] = getStopwords()
assert _STOPWORDS, "default stopword set must be non-empty"

# Two known-default stopwords (Russian "and", English "the"). If the default
# list ever drops them, fail loudly here rather than passing silently on rows
# that were never actually deleted.
_STOPWORD_1: str = "и"
_STOPWORD_2: str = "the"
assert _STOPWORD_1 in _STOPWORDS
assert _STOPWORD_2 in _STOPWORDS

# Non-stopword tokens (classic spam tokens) that must survive the delete.
_NON_STOPWORD_1: str = "purchase"
_NON_STOPWORD_2: str = "discount"
assert _NON_STOPWORD_1 not in _STOPWORDS
assert _NON_STOPWORD_2 not in _STOPWORDS


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


def _makeBayesTokensTable(dbPath: Path) -> None:
    """Create a ``bayes_tokens`` table matching the production schema.

    Mirrors the production composite PK ``(token, chat_id)`` and the columns
    the script's DELETE touches (``token``) plus the rest of the canonical
    shape so the schema is realistic.

    Args:
        dbPath: Path of the SQLite file to create the table in.
    """
    _exec(
        dbPath,
        "CREATE TABLE IF NOT EXISTS bayes_tokens ("
        "token TEXT NOT NULL, "
        "chat_id INTEGER, "
        "spam_count INTEGER DEFAULT 0, "
        "ham_count INTEGER DEFAULT 0, "
        "total_count INTEGER DEFAULT 0, "
        "created_at TIMESTAMP NOT NULL, "
        "updated_at TIMESTAMP NOT NULL, "
        "PRIMARY KEY (token, chat_id)"
        ")",
    )


def _insertToken(dbPath: Path, token: str, chatId: int) -> None:
    """Insert one ``bayes_tokens`` row.

    Args:
        dbPath: Path of the SQLite file.
        token: Token string (PK column).
        chatId: Chat id (PK column).
    """
    _exec(
        dbPath,
        "INSERT INTO bayes_tokens (token, chat_id, spam_count, ham_count, total_count, created_at, updated_at) "
        "VALUES (?, ?, 1, 0, 1, 0, 0)",
        (token, chatId),
    )


def _countRows(dbPath: Path) -> int:
    """Count all rows in ``bayes_tokens``.

    Args:
        dbPath: Path of the SQLite file.

    Returns:
        The total number of rows in the ``bayes_tokens`` table.
    """
    conn = sqlite3.connect(str(dbPath))
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM bayes_tokens")
        row: tuple[int] | None = cursor.fetchone()
    finally:
        conn.close()
    return row[0] if row is not None else 0


def _readAllTokens(dbPath: Path) -> list[str]:
    """Read every ``token`` from ``bayes_tokens``, sorted.

    Args:
        dbPath: Path of the SQLite file.

    Returns:
        A sorted list of token strings for all rows.
    """
    conn = sqlite3.connect(str(dbPath))
    try:
        cursor = conn.execute("SELECT token FROM bayes_tokens ORDER BY token")
        rows: list[str] = [r[0] for r in cursor.fetchall()]
    finally:
        conn.close()
    return rows


# ---------------------------------------------------------------------------
# processDatabase -- delete operation + DB-level coverage
# ---------------------------------------------------------------------------


class TestProcessDatabase:
    """Cover the ``processDatabase`` delete path against a tmp_path SQLite file."""

    def testDryRunLeavesDbUnmodified(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """``dryRun=True`` reports what would be deleted but changes nothing."""
        dbPath = tmp_path / "bot.db"
        _makeBayesTokensTable(dbPath)
        _insertToken(dbPath, token=_STOPWORD_1, chatId=1)
        _insertToken(dbPath, token=_NON_STOPWORD_1, chatId=1)

        rc = processDatabase(dbPath, dryRun=True)
        out = capsys.readouterr().out

        assert rc == 0
        assert "Found 1 bayes_tokens row(s)" in out
        # DB must be untouched under dry-run: both rows still present.
        assert _countRows(dbPath) == 2
        assert _STOPWORD_1 in _readAllTokens(dbPath)
        assert _NON_STOPWORD_1 in _readAllTokens(dbPath)

    def testDeletesOnlyStopwordTokens(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Real run deletes stopword rows while non-stopword rows survive."""
        dbPath = tmp_path / "bot.db"
        _makeBayesTokensTable(dbPath)
        _insertToken(dbPath, token=_STOPWORD_1, chatId=1)
        _insertToken(dbPath, token=_STOPWORD_2, chatId=2)
        _insertToken(dbPath, token=_NON_STOPWORD_1, chatId=1)
        _insertToken(dbPath, token=_NON_STOPWORD_2, chatId=3)

        rc = processDatabase(dbPath, dryRun=False)
        out = capsys.readouterr().out

        assert rc == 0
        assert "Deleted 2 stopword token row(s)" in out
        remaining = _readAllTokens(dbPath)
        # Only the two non-stopword tokens survive.
        assert remaining == sorted([_NON_STOPWORD_1, _NON_STOPWORD_2])
        assert _countRows(dbPath) == 2

    def testMissingTableReturnsNonZero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A DB without the ``bayes_tokens`` table returns exit code 1 (no crash)."""
        dbPath = tmp_path / "bot.db"
        # Create a DB file with an unrelated table but no bayes_tokens.
        _exec(dbPath, "CREATE TABLE unrelated (id INTEGER)")

        rc = processDatabase(dbPath, dryRun=False)
        captured = capsys.readouterr()

        assert rc == 1
        assert "bayes_tokens" in captured.err.lower()

    def testNoStopwordTokensFound(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A DB with only non-stopword tokens prints the 'no stopword' message and exits 0."""
        dbPath = tmp_path / "bot.db"
        _makeBayesTokensTable(dbPath)
        _insertToken(dbPath, token=_NON_STOPWORD_1, chatId=1)
        _insertToken(dbPath, token=_NON_STOPWORD_2, chatId=2)

        rc = processDatabase(dbPath, dryRun=False)
        out = capsys.readouterr().out

        assert rc == 0
        assert "No stopword tokens found" in out
        # Nothing deleted.
        assert _countRows(dbPath) == 2

    def testIdempotencySecondRunDeletesZero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A second run over an already-pruned DB finds and deletes zero rows."""
        dbPath = tmp_path / "bot.db"
        _makeBayesTokensTable(dbPath)
        _insertToken(dbPath, token=_STOPWORD_1, chatId=1)
        _insertToken(dbPath, token=_NON_STOPWORD_1, chatId=1)

        firstRc = processDatabase(dbPath, dryRun=False)
        firstOut = capsys.readouterr().out
        assert firstRc == 0
        assert "Deleted 1 stopword token row(s)" in firstOut

        snapshot = _readAllTokens(dbPath)

        secondRc = processDatabase(dbPath, dryRun=False)
        secondOut = capsys.readouterr().out
        assert secondRc == 0
        assert "No stopword tokens found" in secondOut
        # DB unchanged after second run.
        assert _readAllTokens(dbPath) == snapshot
