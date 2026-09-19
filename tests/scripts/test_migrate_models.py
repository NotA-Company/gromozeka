"""Offline tests for scripts/migrate_models.py.

Covers the pure helpers that form the script's test seam: the CLI parser, the
live-derived MODEL/IMAGE_MODEL key set (drift guard), the merged config-layer
scanner, the config-reference finder, the binary availability mark, the
database-config path resolver, and the ``chat_settings`` read/preview/apply
helpers against throwaway SQLite files on ``tmp_path`` — including the
TOCTOU apply path, where an ``AFTER UPDATE`` trigger deletes a not-yet-visited
matching row mid-UPDATE so the UPDATE rowcount diverges from the preview and
the transaction must roll back with :class:`MigrationCountMismatchError`.

Everything here is offline: no network, no real ``LLMManager`` (a
``Mock(spec=LLMManager)`` serves ``getModelInfo``), no real config load (the
config dicts are synthetic), no bot state. Importing the script module at
collection time is itself the side-effect smoke test: the module only wires
sys.path, logging and the httpx alias — no config load, no ``main()`` run.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple
from unittest.mock import Mock

import pytest

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from internal.bot.models.chat_settings import ChatSettingsKey  # noqa: E402
from lib.ai import LLMManager  # noqa: E402
from scripts.migrate_models import (  # noqa: E402
    MigrationCountMismatchError,
    applyMigration,
    buildParser,
    chatSettingsTableExists,
    collectDbUsage,
    collectLayerEntries,
    collectModelKeys,
    findConfigReferences,
    main,
    modelStatus,
    previewMigration,
    resolveDbPath,
)

# Intentional drift guard: the exact in-scope key set (9 MODEL-type + 2
# IMAGE_MODEL-type). A new MODEL/IMAGE_MODEL chat setting must consciously
# update this literal.
_EXPECTED_MODEL_KEYS: Set[str] = {
    "chat-model",
    "fallback-model",
    "summary-model",
    "summary-fallback-model",
    "image-parsing-model",
    "image-parsing-fallback-model",
    "image-generation-model",
    "image-generation-fallback-model",
    "condensing-model",
    "memory-refine-model",
    "memory-refine-fallback-model",
}

# Live key strings used to build DB fixtures (same source the script uses).
_KEY_CHAT_MODEL: str = ChatSettingsKey.CHAT_MODEL.value
_KEY_FALLBACK_MODEL: str = ChatSettingsKey.FALLBACK_MODEL.value
_KEY_EMBEDDING_MODEL: str = ChatSettingsKey.EMBEDDING_MODEL.value

# A retired key that is NOT in the enum — must never be treated in-scope.
_RETIRED_KEY: str = "memory-retrieval-mode"

_OLD_MODEL: str = "openrouter/old-model"
_NEW_MODEL: str = "openrouter/new-model"
_OTHER_MODEL: str = "openrouter/other-model"

_NOW_STR: str = "2026-09-19T12:00:00+00:00"
_DEFAULT_TS: str = "2026-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _connect(dbPath: Path) -> sqlite3.Connection:
    """Open a SQLite connection in autocommit mode (manual transactions).

    ``applyMigration`` requires ``isolation_level=None`` so its explicit
    BEGIN/COMMIT/ROLLBACK statements are honored verbatim.

    Args:
        dbPath: Path of the SQLite file.

    Returns:
        The opened autocommit ``sqlite3.Connection``.
    """
    return sqlite3.connect(str(dbPath), isolation_level=None)


def _exec(dbPath: Path, sql: str, params: Tuple[object, ...] = ()) -> None:
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
    """Create a ``chat_settings`` table matching the production schema.

    Columns per the production migration (composite-PK columns NOT NULL,
    updated_by defaulted, both timestamps NOT NULL) plus the composite PK.

    Args:
        dbPath: Path of the SQLite file to create the table in.
    """
    _exec(
        dbPath,
        "CREATE TABLE chat_settings ("
        "chat_id INTEGER NOT NULL, "
        "key TEXT NOT NULL, "
        "value TEXT, "
        "updated_by INTEGER NOT NULL DEFAULT 0, "
        "created_at TIMESTAMP NOT NULL, "
        "updated_at TIMESTAMP NOT NULL, "
        "PRIMARY KEY (chat_id, key)"
        ")",
    )


def _insertSetting(
    dbPath: Path,
    chatId: int,
    key: str,
    value: str,
    *,
    updatedBy: int = 0,
    createdAt: str = _DEFAULT_TS,
    updatedAt: str = _DEFAULT_TS,
) -> None:
    """Insert one ``chat_settings`` row.

    Args:
        dbPath: Path of the SQLite file.
        chatId: Chat id (PK column).
        key: Setting key string (PK column).
        value: Setting value string.
        updatedBy: ``updated_by`` value (defaults to 0, the production default).
        createdAt: ``created_at`` timestamp string.
        updatedAt: ``updated_at`` timestamp string.
    """
    _exec(
        dbPath,
        "INSERT INTO chat_settings (chat_id, key, value, updated_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (chatId, key, value, updatedBy, createdAt, updatedAt),
    )


def _readAllRows(dbPath: Path) -> List[Tuple[object, ...]]:
    """Read every full ``chat_settings`` row, ordered by chat_id, key.

    Args:
        dbPath: Path of the SQLite file.

    Returns:
        A list of ``(chat_id, key, value, updated_by, created_at, updated_at)``
        tuples for all rows, sorted by ``(chat_id, key)``.
    """
    conn = sqlite3.connect(str(dbPath))
    try:
        cursor = conn.execute(
            "SELECT chat_id, key, value, updated_by, created_at, updated_at " "FROM chat_settings ORDER BY chat_id, key"
        )
        rows: List[Tuple[object, ...]] = [tuple(row) for row in cursor.fetchall()]
    finally:
        conn.close()
    return rows


def _makeLlmManager(availableModels: Set[str]) -> Mock:
    """Build a mock LLMManager serving a binary availability set.

    Args:
        availableModels: Model ids for which ``getModelInfo`` returns a
            non-None payload; every other id returns ``None``.

    Returns:
        ``Mock(spec=LLMManager)`` with ``getModelInfo`` wired to the set.
    """
    manager = Mock(spec=LLMManager)
    manager.getModelInfo = Mock(side_effect=lambda name: {"name": name} if name in availableModels else None)
    return manager


# ---------------------------------------------------------------------------
# buildParser
# ---------------------------------------------------------------------------


class TestBuildParser:
    """buildParser: CLI flags and defaults without touching sys.argv."""

    def testNoFlagsDefaults(self) -> None:
        """No flags: configDirs None, .env default, no migrate pair, apply False.

        Returns:
            None
        """
        args = buildParser().parse_args([])
        assert args.configDirs is None
        assert args.dotenv_file == ".env"
        assert args.migrate is None
        assert args.apply is False

    def testConfigDirRepeatableAppendsInOrder(self) -> None:
        """--config-dir accumulates values in the order given.

        Returns:
            None
        """
        args = buildParser().parse_args(["--config-dir", "a", "--config-dir", "b"])
        assert args.configDirs == ["a", "b"]

    def testMigrateTakesTwoModels(self) -> None:
        """--migrate consumes exactly two positional model ids.

        Returns:
            None
        """
        args = buildParser().parse_args(["--migrate", "old-model", "new-model"])
        assert args.migrate == ["old-model", "new-model"]

    def testApplyFlag(self) -> None:
        """--apply parses to True (absent case covered by testNoFlagsDefaults).

        Returns:
            None
        """
        args = buildParser().parse_args(["--apply"])
        assert args.apply is True


# ---------------------------------------------------------------------------
# collectModelKeys
# ---------------------------------------------------------------------------


class TestCollectModelKeys:
    """collectModelKeys: live-derived in-scope key set (drift guard)."""

    def testExactKeySetMatchesExpected11(self) -> None:
        """The key set equals the expected 11 keys exactly, with no duplicates.

        Intentional drift guard: adding/removing a MODEL/IMAGE_MODEL setting
        key must consciously update ``_EXPECTED_MODEL_KEYS``.

        Returns:
            None
        """
        keys = collectModelKeys()
        assert set(keys) == _EXPECTED_MODEL_KEYS
        assert len(keys) == len(set(keys))

    def testEmbeddingModelExcluded(self) -> None:
        """``embedding-model`` is deliberately out of scope.

        Returns:
            None
        """
        assert _KEY_EMBEDDING_MODEL == "embedding-model"
        assert _KEY_EMBEDDING_MODEL not in collectModelKeys()


# ---------------------------------------------------------------------------
# collectLayerEntries
# ---------------------------------------------------------------------------


class TestCollectLayerEntries:
    """collectLayerEntries: merged-bot-config layer scanning."""

    def testDefaultsPrivateOverlayAndTwoTiersExactTuples(self) -> None:
        """Scans [bot.defaults], sparse chat-type overlays and tier-defaults.

        Absent layers (group/channel here) contribute nothing; non-model keys,
        unknown chat-type layers and unknown tiers are ignored. Exact output
        order: defaults, chat types in enum order, tiers in enum order.

        Returns:
            None
        """
        botConfig: Dict[str, object] = {
            "defaults": {"chat-model": "model-default", "memory-enabled": "true"},
            "private-defaults": {"fallback-model": "model-private"},
            "tier-defaults": {
                "free": {"chat-model": "model-free"},
                "paid": {"chat-model": "model-paid", "image-generation-model": "model-paid-image"},
                "unknown-tier": {"chat-model": "model-unknown-tier"},
            },
            "unknown-layer-defaults": {"chat-model": "model-unknown-layer"},
        }
        entries = collectLayerEntries(botConfig, collectModelKeys())
        assert entries == [
            ("bot.defaults", "chat-model", "model-default"),
            ("bot.private-defaults", "fallback-model", "model-private"),
            ("bot.tier-defaults.free", "chat-model", "model-free"),
            ("bot.tier-defaults.paid", "chat-model", "model-paid"),
            ("bot.tier-defaults.paid", "image-generation-model", "model-paid-image"),
        ]

    def testNonDictLayerValuesIgnored(self) -> None:
        """A non-dict layer entry is skipped instead of crashing.

        Returns:
            None
        """
        botConfig: Dict[str, object] = {
            "defaults": "not-a-dict",
            "group-defaults": 42,
            "tier-defaults": {"free": "also-not-a-dict"},
        }
        assert collectLayerEntries(botConfig, collectModelKeys()) == []


# ---------------------------------------------------------------------------
# findConfigReferences
# ---------------------------------------------------------------------------


class TestFindConfigReferences:
    """findConfigReferences: merged-layer entries still referencing OLD."""

    def testReferencesInDefaultsAndTierReported(self) -> None:
        """OLD present in defaults and one tier layer → both reported, in order.

        Returns:
            None
        """
        botConfig: Dict[str, object] = {
            "defaults": {"chat-model": _OLD_MODEL},
            "tier-defaults": {"free": {"chat-model": _OLD_MODEL}, "paid": {"chat-model": _OTHER_MODEL}},
        }
        references = findConfigReferences(botConfig, collectModelKeys(), _OLD_MODEL)
        assert references == [
            "[bot.defaults] chat-model = openrouter/old-model",
            "[bot.tier-defaults.free] chat-model = openrouter/old-model",
        ]

    def testAbsentModelReturnsEmptyList(self) -> None:
        """A config that does not reference OLD yields an empty list.

        Returns:
            None
        """
        botConfig: Dict[str, object] = {"defaults": {"chat-model": _OTHER_MODEL}}
        assert findConfigReferences(botConfig, collectModelKeys(), _OLD_MODEL) == []


# ---------------------------------------------------------------------------
# modelStatus
# ---------------------------------------------------------------------------


class TestModelStatus:
    """modelStatus: the binary getModelInfo availability mark."""

    def testKnownModelReturnsOk(self) -> None:
        """A model found by getModelInfo (any non-None payload) marks 'ok'.

        Returns:
            None
        """
        llmManager = _makeLlmManager({_OLD_MODEL})
        assert modelStatus(llmManager, _OLD_MODEL) == "ok"

    def testUnknownModelReturnsUnavailable(self) -> None:
        """A model whose getModelInfo returns None marks 'unavailable'.

        Returns:
            None
        """
        llmManager = _makeLlmManager(set())
        assert modelStatus(llmManager, _OLD_MODEL) == "unavailable"


# ---------------------------------------------------------------------------
# resolveDbPath
# ---------------------------------------------------------------------------


class TestResolveDbPath:
    """resolveDbPath: nested database-config traversal and None on malformed."""

    def testNestedProvidersDictResolvesPath(self) -> None:
        """The documented shape resolves to the dbPath string.

        Returns:
            None
        """
        dbConfig: Dict[str, object] = {
            "default": "sqlite3",
            "providers": {"sqlite3": {"parameters": {"dbPath": "/tmp/bot.db"}}},
        }
        assert resolveDbPath(dbConfig) == "/tmp/bot.db"

    def testMalformedShapesReturnNone(self) -> None:
        """Missing/malformed shape elements all degrade to None.

        Returns:
            None
        """
        assert resolveDbPath({}) is None
        missingProvider: Dict[str, object] = {
            "default": "sqlink",
            "providers": {"sqlite3": {"parameters": {"dbPath": "/tmp/bot.db"}}},
        }
        assert resolveDbPath(missingProvider) is None
        missingDbPath: Dict[str, object] = {"default": "sqlite3", "providers": {"sqlite3": {"parameters": {}}}}
        assert resolveDbPath(missingDbPath) is None
        nonStringDbPath: Dict[str, object] = {
            "default": "sqlite3",
            "providers": {"sqlite3": {"parameters": {"dbPath": 123}}},
        }
        assert resolveDbPath(nonStringDbPath) is None


# ---------------------------------------------------------------------------
# collectDbUsage
# ---------------------------------------------------------------------------


class TestCollectDbUsage:
    """collectDbUsage: grouped per-(key, value) chat counts from chat_settings."""

    def testGroupingCountsOrderAndScopeFiltering(self, tmp_path: Path) -> None:
        """Two chats on one model+key count as 2; out-of-scope keys excluded.

        Rows come back ordered by (key, value): only MODEL/IMAGE_MODEL keys
        are scanned, so ``embedding-model`` and retired keys never appear.

        Args:
            tmp_path: Fixture for the throwaway SQLite file.

        Returns:
            None
        """
        dbPath = tmp_path / "bot.db"
        _makeChatSettingsTable(dbPath)
        _insertSetting(dbPath, chatId=1, key=_KEY_CHAT_MODEL, value="model-a")
        _insertSetting(dbPath, chatId=2, key=_KEY_CHAT_MODEL, value="model-a")
        _insertSetting(dbPath, chatId=3, key=_KEY_FALLBACK_MODEL, value="model-b")
        _insertSetting(dbPath, chatId=4, key=_KEY_EMBEDDING_MODEL, value="model-zz")
        _insertSetting(dbPath, chatId=5, key=_RETIRED_KEY, value="model-a")

        conn = _connect(dbPath)
        try:
            rows = collectDbUsage(conn, collectModelKeys())
        finally:
            conn.close()

        assert rows == [("chat-model", "model-a", 2), ("fallback-model", "model-b", 1)]


# ---------------------------------------------------------------------------
# previewMigration
# ---------------------------------------------------------------------------


class TestPreviewMigration:
    """previewMigration: the exact row set a migration would rewrite."""

    def testSelectsOnlyOldValueInScopeKeysOrdered(self, tmp_path: Path) -> None:
        """Only rows with value == OLD AND key in modelKeys, ordered by chat_id, key.

        A different value or an out-of-scope key (``embedding-model``, retired
        key) excludes the row. Rows are inserted scrambled to prove the
        deterministic ORDER BY.

        Args:
            tmp_path: Fixture for the throwaway SQLite file.

        Returns:
            None
        """
        dbPath = tmp_path / "bot.db"
        _makeChatSettingsTable(dbPath)
        _insertSetting(dbPath, chatId=5, key=_KEY_CHAT_MODEL, value=_OLD_MODEL)
        _insertSetting(dbPath, chatId=2, key=_KEY_FALLBACK_MODEL, value=_OLD_MODEL)
        _insertSetting(dbPath, chatId=2, key=_KEY_CHAT_MODEL, value=_OLD_MODEL)
        _insertSetting(dbPath, chatId=3, key=_KEY_CHAT_MODEL, value=_OTHER_MODEL)
        _insertSetting(dbPath, chatId=4, key=_KEY_EMBEDDING_MODEL, value=_OLD_MODEL)
        _insertSetting(dbPath, chatId=6, key=_RETIRED_KEY, value=_OLD_MODEL)

        conn = _connect(dbPath)
        try:
            preview = previewMigration(conn, _OLD_MODEL, collectModelKeys())
        finally:
            conn.close()

        assert preview == [
            (2, _KEY_CHAT_MODEL),
            (2, _KEY_FALLBACK_MODEL),
            (5, _KEY_CHAT_MODEL),
        ]


# ---------------------------------------------------------------------------
# applyMigration
# ---------------------------------------------------------------------------


class TestApplyMigration:
    """applyMigration: transactional rewrite with count verification."""

    def testRewritesMatchingRowsAndCounts(self, tmp_path: Path) -> None:
        """Matching rows get the NEW value + nowStr; everything else untouched.

        ``updated_by`` and ``created_at`` survive the rewrite on migrated
        rows; non-matching rows are byte-identical to the pre-run snapshot.

        Args:
            tmp_path: Fixture for the throwaway SQLite file.

        Returns:
            None
        """
        dbPath = tmp_path / "bot.db"
        _makeChatSettingsTable(dbPath)
        _insertSetting(dbPath, chatId=1, key=_KEY_CHAT_MODEL, value=_OLD_MODEL, updatedBy=42)
        _insertSetting(dbPath, chatId=2, key=_KEY_CHAT_MODEL, value=_OLD_MODEL, updatedBy=7)
        _insertSetting(dbPath, chatId=3, key=_KEY_FALLBACK_MODEL, value=_OLD_MODEL)
        _insertSetting(dbPath, chatId=4, key=_KEY_CHAT_MODEL, value=_OTHER_MODEL)
        _insertSetting(dbPath, chatId=5, key=_KEY_EMBEDDING_MODEL, value=_OLD_MODEL)
        _insertSetting(dbPath, chatId=6, key=_RETIRED_KEY, value=_OLD_MODEL)
        snapshot = _readAllRows(dbPath)

        conn = _connect(dbPath)
        try:
            counts = applyMigration(conn, _OLD_MODEL, _NEW_MODEL, collectModelKeys(), _NOW_STR)
        finally:
            conn.close()

        assert counts == {_KEY_CHAT_MODEL: 2, _KEY_FALLBACK_MODEL: 1}
        rows = _readAllRows(dbPath)
        # Migrated rows: value rewritten, updated_at = nowStr, updated_by and
        # created_at untouched.
        assert rows[0] == (1, _KEY_CHAT_MODEL, _NEW_MODEL, 42, _DEFAULT_TS, _NOW_STR)
        assert rows[1] == (2, _KEY_CHAT_MODEL, _NEW_MODEL, 7, _DEFAULT_TS, _NOW_STR)
        assert rows[2] == (3, _KEY_FALLBACK_MODEL, _NEW_MODEL, 0, _DEFAULT_TS, _NOW_STR)
        # Non-matching rows byte-identical.
        assert rows[3:] == snapshot[3:]

    def testCountMismatchRaceRollsBack(self, tmp_path: Path) -> None:
        """A mid-UPDATE mutation makes rowcount != preview → error + rollback.

        An ``AFTER UPDATE`` trigger deletes the not-yet-visited matching row
        as soon as the first one is updated (the Phase-1 verified stand-in for
        a concurrent bot write). UPDATE reports 1 affected row against a
        2-row preview; the transaction must roll back so BOTH rows still hold
        the OLD value afterwards.

        Args:
            tmp_path: Fixture for the throwaway SQLite file.

        Returns:
            None
        """
        dbPath = tmp_path / "bot.db"
        _makeChatSettingsTable(dbPath)
        _insertSetting(dbPath, chatId=1, key=_KEY_CHAT_MODEL, value=_OLD_MODEL)
        _insertSetting(dbPath, chatId=2, key=_KEY_CHAT_MODEL, value=_OLD_MODEL)

        conn = _connect(dbPath)
        try:
            conn.execute(
                "CREATE TRIGGER simulate_concurrent_write AFTER UPDATE ON chat_settings "
                f"BEGIN DELETE FROM chat_settings WHERE key = NEW.key AND value = '{_OLD_MODEL}' "
                "AND chat_id <> NEW.chat_id; END"
            )
            preview = previewMigration(conn, _OLD_MODEL, collectModelKeys())
            assert len(preview) == 2

            with pytest.raises(MigrationCountMismatchError, match="rolled back"):
                applyMigration(conn, _OLD_MODEL, _NEW_MODEL, collectModelKeys(), _NOW_STR)

            # Rolled back: both rows still hold the OLD value, nothing changed.
            assert previewMigration(conn, _OLD_MODEL, collectModelKeys()) == preview
            valuesAfter = conn.execute("SELECT chat_id, value FROM chat_settings ORDER BY chat_id").fetchall()
            assert valuesAfter == [(1, _OLD_MODEL), (2, _OLD_MODEL)]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# chatSettingsTableExists
# ---------------------------------------------------------------------------


class TestChatSettingsTableExists:
    """chatSettingsTableExists: sqlite_master probe on the opened database."""

    def testTrueWhenTableExists(self, tmp_path: Path) -> None:
        """A database containing ``chat_settings`` probes True.

        Args:
            tmp_path: Fixture for the throwaway SQLite file.

        Returns:
            None
        """
        dbPath = tmp_path / "bot.db"
        _makeChatSettingsTable(dbPath)
        conn = _connect(dbPath)
        try:
            assert chatSettingsTableExists(conn) is True
        finally:
            conn.close()

    def testFalseWhenTableMissing(self, tmp_path: Path) -> None:
        """A database without ``chat_settings`` probes False (no crash).

        Args:
            tmp_path: Fixture for the throwaway SQLite file.

        Returns:
            None
        """
        dbPath = tmp_path / "bot.db"
        _exec(dbPath, "CREATE TABLE unrelated (id INTEGER)")
        conn = _connect(dbPath)
        try:
            assert chatSettingsTableExists(conn) is False
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Module import smoke
# ---------------------------------------------------------------------------


class TestModuleImportSmoke:
    """Importability/export smoke for scripts.migrate_models."""

    def testModuleImportsAndExportsHelpers(self) -> None:
        """The module is importable and exports the helpers this suite drives.

        Collection already imported the module, so the module-level import is
        itself the smoke check: the script imports cleanly under pytest (its
        module-level wiring is only sys.path/logging/httpx-alias — no config
        load, no bot start, no argparse execution). This test asserts the
        import landed and the seam is callable; it does NOT enforce absence
        of side effects.

        Returns:
            None
        """
        assert "scripts.migrate_models" in sys.modules
        assert callable(main)
        assert callable(buildParser)
        assert issubclass(MigrationCountMismatchError, Exception)
