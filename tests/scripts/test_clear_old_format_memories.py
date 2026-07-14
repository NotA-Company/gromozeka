"""Regression tests for scripts/clear_old_format_memories.py.

Covers the ``_classifyMetadata`` pure classifier (all six per-row states), the
``processDatabase`` data operation (UPDATE path + sibling-key preservation + the
canonical re-serialization shape), idempotency on a second run, and ``--dry-run``
leaving the DB untouched.

These tests build a throwaway ``chat_messages``-like table on a tmp_path SQLite
file and never touch real bot state.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.clear_old_format_memories import (  # noqa: E402
    _classifyMetadata,
    _MetadataAction,
    processDatabase,
)

# Production serializer shape mirrored by the script itself
# (lib/utils/utils.py:jsonDumps): sorted keys + compact separators, no ASCII
# escaping. UPDATE rows are expected to land back on disk in exactly this form.
_SEPARATORS = (",", ":")


def _canonicalDump(obj: dict[str, object]) -> str:
    """Serialise ``obj`` with the production canonical shape.

    Args:
        obj: The dict to serialise.

    Returns:
        The compact, key-sorted JSON string the script must write for UPDATE rows.
    """
    return json.dumps(obj, ensure_ascii=False, separators=_SEPARATORS, sort_keys=True)


def _makeDb(dbPath: Path) -> None:
    """Create a chat_messages-like table with the production PK and metadata column.

    Args:
        dbPath: Path of the SQLite file to create.
    """
    conn = sqlite3.connect(str(dbPath))
    try:
        conn.execute(
            "CREATE TABLE chat_messages ("
            "chat_id INTEGER NOT NULL, "
            "message_id TEXT NOT NULL, "
            'metadata TEXT NOT NULL DEFAULT "", '
            "PRIMARY KEY (chat_id, message_id)"
            ")"
        )
        conn.commit()
    finally:
        conn.close()


def _insertRow(dbPath: Path, chatId: int, messageId: str, metadata: str) -> None:
    """Insert one chat_messages row.

    Args:
        dbPath: Path of the SQLite file.
        chatId: The chat id (integer, part of the PK).
        messageId: The message id (string, part of the PK).
        metadata: The raw metadata column value.
    """
    conn = sqlite3.connect(str(dbPath))
    try:
        conn.execute(
            "INSERT INTO chat_messages (chat_id, message_id, metadata) VALUES (?, ?, ?)",
            (chatId, messageId, metadata),
        )
        conn.commit()
    finally:
        conn.close()


def _readMetadata(dbPath: Path, chatId: int, messageId: str) -> str:
    """Read one row's metadata column.

    Args:
        dbPath: Path of the SQLite file.
        chatId: The chat id to select.
        messageId: The message id to select.

    Returns:
        The raw ``metadata`` string for the matching row.
    """
    conn = sqlite3.connect(str(dbPath))
    try:
        cursor = conn.execute(
            "SELECT metadata FROM chat_messages WHERE chat_id = ? AND message_id = ?",
            (chatId, messageId),
        )
        row: tuple[str] | None = cursor.fetchone()
    finally:
        conn.close()
    assert row is not None, f"row not found chat_id={chatId} message_id={messageId}"
    return row[0]


def _parseCounter(stdout: str, label: str) -> int:
    """Parse one fixed-width counter line out of processDatabase's summary output.

    Args:
        stdout: The captured stdout from ``processDatabase``.
        label: The label prefix to find (e.g. ``"Rows updated:"``).

    Returns:
        The integer following the label.
    """
    for line in stdout.splitlines():
        if line.startswith(label):
            return int(line[len(label) :].strip())
    raise AssertionError(f"label {label!r} not found in output:\n{stdout}")


# ---------------------------------------------------------------------------
# _classifyMetadata -- pure classifier, all six states
# ---------------------------------------------------------------------------


class TestClassifyMetadata:
    """Cover every branch of ``_classifyMetadata`` against raw metadata strings."""

    def testEmpty(self) -> None:
        """An empty metadata string classifies as SKIP_EMPTY."""
        action, parsed, preview = _classifyMetadata("")
        assert action == _MetadataAction.SKIP_EMPTY
        assert parsed is None
        assert preview is None

    def testMalformedJson(self) -> None:
        """Unparseable JSON classifies as SKIP_MALFORMED with a reason preview."""
        action, parsed, preview = _classifyMetadata("{not valid json")
        assert action == _MetadataAction.SKIP_MALFORMED
        assert parsed is None
        assert preview is not None

    def testNonDictMetadata(self) -> None:
        """A valid JSON value that is not an object classifies as SKIP_MALFORMED."""
        action, parsed, preview = _classifyMetadata("[1, 2, 3]")
        assert action == _MetadataAction.SKIP_MALFORMED
        assert parsed is None
        assert preview is not None

    def testNoMemoriesKey(self) -> None:
        """An object without a ``memories`` key classifies as SKIP_NO_KEY."""
        action, parsed, preview = _classifyMetadata(json.dumps({"otherKey": 1}))
        assert action == _MetadataAction.SKIP_NO_KEY
        assert parsed is None
        assert preview is None

    def testOldFormat(self) -> None:
        """Old-format ``memories`` classifies as UPDATE with the key removed and siblings kept."""
        metadata = json.dumps(
            {
                "condensedThread": "ctx",
                "memories": {"permanent": [{"id": "a"}], "shortTerm": []},
                "other": 2,
            }
        )
        action, parsed, preview = _classifyMetadata(metadata)
        assert action == _MetadataAction.UPDATE
        assert parsed is not None
        assert "memories" not in parsed
        assert parsed["condensedThread"] == "ctx"
        assert parsed["other"] == 2
        assert preview is not None

    def testNewFormatPermanentIds(self) -> None:
        """New-format ``memories`` (``permanentIds``) classifies as SKIP_NEW_FORMAT."""
        metadata = json.dumps({"memories": {"permanentIds": ["uuid-1"], "shortTermIds": []}})
        action, parsed, preview = _classifyMetadata(metadata)
        assert action == _MetadataAction.SKIP_NEW_FORMAT
        assert parsed is None
        assert preview is None

    def testNewFormatShortTermIdsOnly(self) -> None:
        """New-format ``memories`` with only ``shortTermIds`` also classifies as SKIP_NEW_FORMAT."""
        metadata = json.dumps({"memories": {"shortTermIds": ["uuid-2"]}})
        action, _parsed, _preview = _classifyMetadata(metadata)
        assert action == _MetadataAction.SKIP_NEW_FORMAT

    def testMemoriesValueIsList(self) -> None:
        """A non-dict ``memories`` list value classifies as SKIP_MALFORMED."""
        action, parsed, preview = _classifyMetadata(json.dumps({"memories": [1, 2]}))
        assert action == _MetadataAction.SKIP_MALFORMED
        assert parsed is None
        assert preview is not None

    def testMemoriesValueIsNull(self) -> None:
        """A null ``memories`` value classifies as SKIP_MALFORMED."""
        action, parsed, preview = _classifyMetadata(json.dumps({"memories": None}))
        assert action == _MetadataAction.SKIP_MALFORMED
        assert parsed is None
        assert preview is not None


# ---------------------------------------------------------------------------
# processDatabase -- data operation + DB-level coverage
# ---------------------------------------------------------------------------


class TestProcessDatabase:
    """Cover the ``processDatabase`` write path against a tmp_path SQLite file."""

    def testOldFormatRowUpdatedAndSiblingsPreserved(self, tmp_path: Path) -> None:
        """An old-format row is rewritten: ``memories`` gone, siblings kept, canonical shape."""
        dbPath = tmp_path / "bot.db"
        _makeDb(dbPath)
        original = json.dumps(
            {
                "condensedThread": "ctx",
                "memories": {"permanent": [{"id": "a"}], "shortTerm": []},
            },
            ensure_ascii=False,
            separators=_SEPARATORS,
            sort_keys=True,
        )
        _insertRow(dbPath, chatId=1, messageId="m1", metadata=original)

        rc = processDatabase(dbPath, dryRun=False, verbose=False)

        assert rc == 0
        result = _readMetadata(dbPath, chatId=1, messageId="m1")
        expected = _canonicalDump({"condensedThread": "ctx"})
        assert result == expected

    def testEmptyMetadataUntouched(self, tmp_path: Path) -> None:
        """An empty metadata row is skipped and left as the empty string."""
        dbPath = tmp_path / "bot.db"
        _makeDb(dbPath)
        _insertRow(dbPath, chatId=2, messageId="m2", metadata="")
        rc = processDatabase(dbPath, dryRun=False, verbose=False)
        assert rc == 0
        assert _readMetadata(dbPath, chatId=2, messageId="m2") == ""

    def testMalformedMetadataUntouched(self, tmp_path: Path) -> None:
        """Malformed JSON metadata is skipped and left byte-untouched."""
        dbPath = tmp_path / "bot.db"
        _makeDb(dbPath)
        original = "{not json"
        _insertRow(dbPath, chatId=3, messageId="m3", metadata=original)
        rc = processDatabase(dbPath, dryRun=False, verbose=False)
        assert rc == 0
        assert _readMetadata(dbPath, chatId=3, messageId="m3") == original

    def testNoMemoriesKeyUntouched(self, tmp_path: Path) -> None:
        """A row without a ``memories`` key is skipped untouched."""
        dbPath = tmp_path / "bot.db"
        _makeDb(dbPath)
        original = json.dumps({"otherKey": 1})
        _insertRow(dbPath, chatId=4, messageId="m4", metadata=original)
        rc = processDatabase(dbPath, dryRun=False, verbose=False)
        assert rc == 0
        assert _readMetadata(dbPath, chatId=4, messageId="m4") == original

    def testNewFormatByteUntouched(self, tmp_path: Path) -> None:
        """A new-format row is skipped and left byte-for-byte unchanged."""
        dbPath = tmp_path / "bot.db"
        _makeDb(dbPath)
        original = json.dumps({"memories": {"permanentIds": ["uuid-1"], "shortTermIds": ["uuid-2"]}})
        _insertRow(dbPath, chatId=5, messageId="m5", metadata=original)
        rc = processDatabase(dbPath, dryRun=False, verbose=False)
        assert rc == 0
        assert _readMetadata(dbPath, chatId=5, messageId="m5") == original

    def testMemoriesValueListUntouched(self, tmp_path: Path) -> None:
        """A row whose ``memories`` value is a list is skipped (malformed) untouched."""
        dbPath = tmp_path / "bot.db"
        _makeDb(dbPath)
        original = json.dumps({"memories": [1, 2, 3]})
        _insertRow(dbPath, chatId=6, messageId="m6", metadata=original)
        rc = processDatabase(dbPath, dryRun=False, verbose=False)
        assert rc == 0
        assert _readMetadata(dbPath, chatId=6, messageId="m6") == original

    def testMixedBatchCounters(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A mixed batch reports correct scanned/skipped/new-format/updated counters."""
        dbPath = tmp_path / "bot.db"
        _makeDb(dbPath)
        _insertRow(dbPath, 10, "empty", "")
        _insertRow(dbPath, 10, "malformed", "{bad")
        _insertRow(dbPath, 10, "nokey", json.dumps({"x": 1}))
        _insertRow(dbPath, 10, "newfmt", json.dumps({"memories": {"permanentIds": []}}))
        _insertRow(dbPath, 10, "oldfmt", json.dumps({"memories": {"permanent": []}}))

        rc = processDatabase(dbPath, dryRun=False, verbose=False)
        out = capsys.readouterr().out

        assert rc == 0
        assert _parseCounter(out, "Rows scanned:") == 5
        assert _parseCounter(out, "Rows skipped:") == 3
        assert _parseCounter(out, "New-format rows:") == 1
        assert _parseCounter(out, "Rows updated:") == 1

    def testIdempotencySecondRunZeroUpdates(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A second run over already-cleared rows performs zero updates and changes nothing."""
        dbPath = tmp_path / "bot.db"
        _makeDb(dbPath)
        _insertRow(
            dbPath,
            20,
            "m1",
            json.dumps({"memories": {"permanent": [{"id": "a"}], "shortTerm": []}}),
        )

        firstRc = processDatabase(dbPath, dryRun=False, verbose=False)
        firstOut = capsys.readouterr().out
        assert firstRc == 0
        assert _parseCounter(firstOut, "Rows updated:") == 1

        snapshot = _readMetadata(dbPath, chatId=20, messageId="m1")

        secondRc = processDatabase(dbPath, dryRun=False, verbose=False)
        secondOut = capsys.readouterr().out
        assert secondRc == 0
        assert _parseCounter(secondOut, "Rows updated:") == 0
        assert _readMetadata(dbPath, chatId=20, messageId="m1") == snapshot

    def testDryRunLeavesDbUnmodified(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """``dryRun=True`` reports the would-update count without writing to the DB."""
        dbPath = tmp_path / "bot.db"
        _makeDb(dbPath)
        original = json.dumps(
            {
                "condensedThread": "ctx",
                "memories": {"permanent": [], "shortTerm": []},
            }
        )
        _insertRow(dbPath, 30, "m1", metadata=original)

        rc = processDatabase(dbPath, dryRun=True, verbose=False)
        out = capsys.readouterr().out

        assert rc == 0
        assert _parseCounter(out, "Rows to update:") == 1
        # DB must be byte-untouched under dry-run.
        assert _readMetadata(dbPath, chatId=30, messageId="m1") == original
