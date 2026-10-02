#!/usr/bin/env python3
"""Inspect and migrate MODEL chat-setting ids between config layers and the DB.

Model ids are app-level ids — the ``[models.models]`` table keys in TOML (e.g.
``openrouter/free``) — stored verbatim in the ``chat_settings.value`` column.

Default (report) mode prints two sections:

  A "config layers" — every model setting configured in each merged config
    layer (``[bot.defaults]``, ``[bot.<chat-type>-defaults]``,
    ``[bot.tier-defaults.<tier>]``), with a BINARY availability mark per value:
    ``ok`` when ``LLMManager.getModelInfo()`` finds the model, ``unavailable``
    otherwise. No other availability signal (unknown/disabled/provider-failed,
    the ``[models.models]`` catalog, physical TOML files) is consulted.
  B "db usage" — a table of ``model | setting key | chats using it | status``
    built from grouped counts over the ``chat_settings`` table, same mark.
    When the database cannot be used (unresolvable dbPath, missing file, no
    ``chat_settings`` table) this section is skipped with a printed note and
    the report still succeeds — report-mode DB problems are NONFATAL.

``--migrate OLD NEW`` rewrites ``chat_settings`` rows whose ``value == OLD``
to NEW. DRY-RUN BY DEFAULT: previews the affected rows and prints the
config-reference report. With ``--apply`` it performs the UPDATE inside a
single transaction: re-selects the preview, updates ``value`` and
``updated_at`` (``updated_by`` stays untouched), verifies the affected row
count matches the preview (mismatch → ROLLBACK + exit code 2), and commits.
Config layers are never rewritten by ``--apply`` — the config-reference report
tells the operator which overlay entries to edit manually.

Scope limits: only chat settings of type MODEL / IMAGE_MODEL are inspected
(embedding models are explicitly out of scope), and only the ``chat_settings``
table is ever written — no stats tables, no ``models`` table, nothing else.

The database is accessed with raw sqlite3, NOT the ``Database`` class: the
latter runs pending migrations as a side effect, which is unacceptable for a
maintenance tool. Stop the bot before ``--apply``: concurrent chat-settings
writes can race with the transaction (read-then-act TOCTOU window).

Usage:
    ./venv/bin/python3 scripts/migrate_models.py                      # report
    ./venv/bin/python3 scripts/migrate_models.py --migrate OLD NEW    # dry-run
    ./venv/bin/python3 scripts/migrate_models.py --migrate OLD NEW --apply

Exit codes:
    0  Success (report, dry-run, or migration applied). In report mode an
       unresolvable or missing database (or a missing chat_settings table)
       is NONFATAL: the DB usage section is skipped with a printed note.
    1  Validation / usage error (OLD == NEW, NEW unavailable, --apply without
       --migrate, a missing/unusable database in MIGRATION mode, init
       failure, unexpected runtime errors).
    2  Argument-parsing error OR migration rolled back. argparse itself exits
       2 on malformed arguments (e.g. --migrate with a missing second value,
       or an unknown option) BEFORE application validation runs — no
       transaction is attempted in that case. The other exit-2 case is the
       apply transaction rolled back: UPDATE row count did not match the
       preview.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Ensure the repository root is on sys.path so that project packages
# (internal/, lib/) are importable when the script is run as:
#     ./venv/bin/python3 scripts/migrate_models.py
# In that invocation Python adds scripts/ to sys.path, not the repo root.
# ---------------------------------------------------------------------------
_REPO_ROOT = str(Path(__file__).parent.parent.resolve())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Silence noisy libraries before importing project code.
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.ERROR)
logging.getLogger("openai._base_client").setLevel(logging.ERROR)

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

from internal.bot.models.chat_settings import ChatSettingsType, ChatTier, getChatSettingsInfo  # noqa: E402
from internal.bot.models.ensured_message import ChatType  # noqa: E402
from internal.config.manager import ConfigManager  # noqa: E402
from lib.ai import LLMManager  # noqa: E402
from lib.db.utils import getCurrentTimestamp  # noqa: E402
from scripts._lib.bootstrap import bootstrapProxy  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANSI colour helpers (used only when stdout is a TTY)
# ---------------------------------------------------------------------------
_ANSI_YELLOW = "\033[33m"
_ANSI_GREEN = "\033[32m"
_ANSI_RED = "\033[31m"
_ANSI_RESET = "\033[0m"

_USE_COLOR: bool = sys.stdout.isatty()


def _col(text: str, code: str) -> str:
    """Wrap *text* in ANSI *code* when colour output is enabled.

    Args:
        text: The string to colourise.
        code: An ANSI escape sequence (e.g. ``_ANSI_RED``).

    Returns:
        Colourised string when stdout is a TTY, plain *text* otherwise.
    """
    if _USE_COLOR:
        return f"{code}{text}{_ANSI_RESET}"
    return text


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_DIRS = ["configs/00-defaults", "configs/local"]

_MODEL_SETTING_TYPES = (ChatSettingsType.MODEL, ChatSettingsType.IMAGE_MODEL)
"""Chat-setting types in scope. Embedding models are explicitly out of scope."""

_STATUS_OK = "ok"
"""Availability mark: ``LLMManager.getModelInfo(value)`` found the model."""

_STATUS_UNAVAILABLE = "unavailable"
"""Availability mark: ``LLMManager.getModelInfo(value)`` returned ``None``."""


class MigrationCountMismatchError(Exception):
    """Raised when the UPDATE row count does not match the previewed count.

    The transaction has already been rolled back when this is raised; the
    caller must exit with a non-zero status code (house convention: 2).
    """


# ---------------------------------------------------------------------------
# Pure helpers (no I/O beyond reads on the passed-in objects; importable
# without side effects — Phase 2 tests exercise these directly)
# ---------------------------------------------------------------------------


def collectModelKeys() -> List[str]:
    """Collect the DB key strings of every model-type chat setting.

    Derives the key set programmatically from ``getChatSettingsInfo()`` — the
    single source of truth — never from a hardcoded list. Only settings whose
    metadata type is ``MODEL`` or ``IMAGE_MODEL`` are in scope; embedding
    models are excluded by design.

    Returns:
        List of DB key strings (the ``ChatSettingsKey`` member values, e.g.
        ``"chat-model"``), in enum-declaration order.
    """
    return [key.value for key, meta in getChatSettingsInfo().items() if meta["type"] in _MODEL_SETTING_TYPES]


def collectLayerEntries(botConfig: Dict[str, object], modelKeys: List[str]) -> List[Tuple[str, str, str]]:
    """Collect model-setting entries from the merged bot-config layers.

    Mirrors the default-settings scope loading in
    ``internal/bot/common/handlers/manager.py`` (``[bot.defaults]``,
    ``[bot.<chat-type>-defaults]``, ``[bot.tier-defaults.<tier>]``). Layers are
    sparse overlays: only keys actually present in a layer are reported.

    Args:
        botConfig: The merged ``[bot]`` config dict (``ConfigManager.getBotConfig()``).
        modelKeys: In-scope DB key strings (see :func:`collectModelKeys`).

    Returns:
        List of ``(layerName, key, value)`` triples, e.g.
        ``("bot.tier-defaults.free", "chat-model", "openrouter/free")``.
    """
    modelKeySet = set(modelKeys)
    entries: List[Tuple[str, str, str]] = []

    defaults = botConfig.get("defaults", {})
    if isinstance(defaults, dict):
        entries.extend(("bot.defaults", str(k), str(v)) for k, v in defaults.items() if k in modelKeySet)

    for chatType in ChatType:
        layer = botConfig.get(f"{chatType.value}-defaults", {})
        if isinstance(layer, dict):
            entries.extend(
                (f"bot.{chatType.value}-defaults", str(k), str(v)) for k, v in layer.items() if k in modelKeySet
            )

    tierDefaults = botConfig.get("tier-defaults", {})
    if isinstance(tierDefaults, dict):
        for tier in ChatTier:
            layer = tierDefaults.get(tier, {})
            if isinstance(layer, dict):
                entries.extend(
                    (f"bot.tier-defaults.{tier}", str(k), str(v)) for k, v in layer.items() if k in modelKeySet
                )

    return entries


def modelStatus(llmManager: LLMManager, value: str) -> str:
    """Return the binary availability mark for a model id.

    The ONLY availability check (per spec): ``LLMManager.getModelInfo()``.
    Unknown / disabled / provider-failed causes are deliberately NOT
    distinguished, and the ``[models.models]`` catalog is NOT consulted.

    Args:
        llmManager: Initialised ``LLMManager``.
        value: The model id to check.

    Returns:
        ``_STATUS_OK`` when the model is available, ``_STATUS_UNAVAILABLE``
        otherwise.
    """
    return _STATUS_OK if llmManager.getModelInfo(value) is not None else _STATUS_UNAVAILABLE


def findConfigReferences(botConfig: Dict[str, object], modelKeys: List[str], old: str) -> List[str]:
    """Find merged-config layer entries whose value equals the OLD model id.

    Scans the same merged layers as :func:`collectLayerEntries` — never the
    physical TOML files (by design).

    Args:
        botConfig: The merged ``[bot]`` config dict.
        modelKeys: In-scope DB key strings.
        old: The OLD model id being migrated away from.

    Returns:
        List of human-readable reference strings, e.g.
        ``"[bot.tier-defaults.free] chat-model = openrouter/free"``.
    """
    return [
        f"[{layerName}] {key} = {value}"
        for layerName, key, value in collectLayerEntries(botConfig, modelKeys)
        if value == old
    ]


def resolveDbPath(dbConfig: Dict[str, object]) -> Optional[str]:
    """Resolve the SQLite ``dbPath`` from the merged database config.

    Expected shape (``DatabaseManagerConfig``): ``dbConfig["providers"][
    dbConfig["default"]]["parameters"]["dbPath"]``.

    Args:
        dbConfig: The merged ``[database]`` config dict
            (``ConfigManager.getDatabaseConfig()``).

    Returns:
        The dbPath string, or ``None`` when the config shape is unexpected
        (e.g. a non-SQLite default provider).
    """
    try:
        providers = dbConfig.get("providers")
        default = dbConfig.get("default")
        if not isinstance(providers, dict) or not isinstance(default, str):
            return None
        provider = providers.get(default)
        if not isinstance(provider, dict):
            return None
        parameters = provider.get("parameters")
        if not isinstance(parameters, dict):
            return None
        dbPath = parameters.get("dbPath")
        return dbPath if isinstance(dbPath, str) else None
    except (KeyError, TypeError):
        return None


def _buildKeyFilter(modelKeys: List[str]) -> Tuple[str, Dict[str, str]]:
    """Build a named-placeholder ``IN (...)`` filter for the model keys.

    Uses ``:named`` placeholders (``:k0``, ``:k1``, ...) — values are never
    interpolated into the SQL text.

    Args:
        modelKeys: In-scope DB key strings.

    Returns:
        A ``(placeholders, params)`` pair: the SQL fragment ``":k0, :k1, ..."``
        and the matching parameter dict.
    """
    placeholders = ", ".join(f":k{i}" for i in range(len(modelKeys)))
    params = {f"k{i}": key for i, key in enumerate(modelKeys)}
    return placeholders, params


def collectDbUsage(conn: sqlite3.Connection, modelKeys: List[str]) -> List[Tuple[str, str, int]]:
    """Read grouped model-setting usage counts from ``chat_settings``.

    Args:
        conn: Open sqlite3 connection (autocommit mode; SELECT only).
        modelKeys: In-scope DB key strings.

    Returns:
        List of ``(key, value, chatCount)`` rows ordered by key, value.
    """
    placeholders, keyParams = _buildKeyFilter(modelKeys)
    cursor = conn.execute(
        "SELECT key, value, COUNT(*) FROM chat_settings "
        f"WHERE key IN ({placeholders}) GROUP BY key, value ORDER BY key, value",
        keyParams,
    )
    return [(str(row[0]), "" if row[1] is None else str(row[1]), int(row[2])) for row in cursor.fetchall()]


def previewMigration(conn: sqlite3.Connection, old: str, modelKeys: List[str]) -> List[Tuple[int, str]]:
    """Preview the ``chat_settings`` rows a migration would rewrite.

    Args:
        conn: Open sqlite3 connection.
        old: The OLD model id (rows whose ``value`` equals this are affected).
        modelKeys: In-scope DB key strings.

    Returns:
        List of ``(chatId, key)`` pairs ordered by chatId, key.
    """
    placeholders, keyParams = _buildKeyFilter(modelKeys)
    params: Dict[str, str] = {**keyParams, "old": old}
    cursor = conn.execute(
        f"SELECT chat_id, key FROM chat_settings WHERE key IN ({placeholders}) AND value = :old ORDER BY chat_id, key",
        params,
    )
    return [(int(row[0]), str(row[1])) for row in cursor.fetchall()]


def applyMigration(conn: sqlite3.Connection, old: str, new: str, modelKeys: List[str], nowStr: str) -> Dict[str, int]:
    """Apply the migration in ONE transaction, verifying the row count.

    Inside the transaction: re-selects the preview, runs
    ``UPDATE chat_settings SET value = :new, updated_at = :now WHERE key IN
    (...) AND value = :old``, verifies the affected row count equals the
    re-selected preview count, then commits. ``updated_by`` is intentionally
    left untouched. On any mismatch the transaction is rolled back and
    :class:`MigrationCountMismatchError` is raised.

    Args:
        conn: Open sqlite3 connection in autocommit mode
            (``isolation_level=None``) so BEGIN/COMMIT/ROLLBACK are manual.
        old: The OLD model id to rewrite.
        new: The NEW model id to write.
        modelKeys: In-scope DB key strings.
        nowStr: The ``updated_at`` timestamp string — MUST match the format
            the repositories write (``getCurrentTimestamp().isoformat()``).

    Returns:
        Per-key migrated row counts (key → row count).

    Raises:
        MigrationCountMismatchError: The UPDATE row count did not match the
            preview count (concurrent write race); transaction rolled back.
    """
    placeholders, keyParams = _buildKeyFilter(modelKeys)
    params: Dict[str, str] = {**keyParams, "old": old, "new": new, "now": nowStr}

    conn.execute("BEGIN")
    rolledBack = False
    try:
        previewCursor = conn.execute(
            "SELECT chat_id, key FROM chat_settings "
            f"WHERE key IN ({placeholders}) AND value = :old ORDER BY chat_id, key",
            params,
        )
        previewRows: List[Tuple[int, str]] = [(int(row[0]), str(row[1])) for row in previewCursor.fetchall()]

        updateCursor = conn.execute(
            f"UPDATE chat_settings SET value = :new, updated_at = :now WHERE key IN ({placeholders}) AND value = :old",
            params,
        )
        migrated = updateCursor.rowcount
        if migrated != len(previewRows):
            conn.execute("ROLLBACK")
            rolledBack = True
            raise MigrationCountMismatchError(
                f"UPDATE affected {migrated} row(s) but preview showed {len(previewRows)} — rolled back "
                "(concurrent write race? stop the bot and re-run)."
            )
        conn.execute("COMMIT")
    except Exception:
        if not rolledBack:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        raise

    counts: Dict[str, int] = {}
    for _, key in previewRows:
        counts[key] = counts.get(key, 0) + 1
    return counts


def chatSettingsTableExists(conn: sqlite3.Connection) -> bool:
    """Check that the ``chat_settings`` table exists in the opened database.

    Args:
        conn: Open sqlite3 connection.

    Returns:
        ``True`` when the table exists, ``False`` otherwise.
    """
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'chat_settings'")
    return cursor.fetchone() is not None


# ---------------------------------------------------------------------------
# Rendering / printing (I/O layer)
# ---------------------------------------------------------------------------

_HDR_MODEL = "model"
_HDR_SETTING_KEY = "setting key"
_HDR_CHATS = "chats"
_HDR_STATUS = "status"


def _statusMark(status: str) -> str:
    """Colourise an availability mark for TTY output.

    Args:
        status: Either ``_STATUS_OK`` or ``_STATUS_UNAVAILABLE``.

    Returns:
        The (possibly colourised) status string.
    """
    if status == _STATUS_OK:
        return _col(status, _ANSI_GREEN)
    return _col(status, _ANSI_RED)


def printConfigLayersSection(llmManager: LLMManager, botConfig: Dict[str, object], modelKeys: List[str]) -> None:
    """Print report Section A: model settings per merged config layer.

    Args:
        llmManager: Initialised ``LLMManager`` (for the availability mark).
        botConfig: The merged ``[bot]`` config dict.
        modelKeys: In-scope DB key strings.

    Returns:
        None; output goes to stdout.
    """
    print("== Section A: model settings in merged config layers ==")
    print(
        f"status marks: {_STATUS_OK} = getModelInfo() found the model; "
        f"{_STATUS_UNAVAILABLE} = getModelInfo() returned None"
    )

    grouped: Dict[str, List[Tuple[str, str]]] = {}
    for layerName, key, value in collectLayerEntries(botConfig, modelKeys):
        grouped.setdefault(layerName, []).append((key, value))

    layerNames = ["bot.defaults"]
    layerNames += [f"bot.{chatType.value}-defaults" for chatType in ChatType]
    layerNames += [f"bot.tier-defaults.{tier}" for tier in ChatTier]

    for layerName in layerNames:
        print(f"\n[{layerName}]")
        layerEntries = grouped.get(layerName, [])
        if not layerEntries:
            print("  (no model settings)")
            continue
        for key, value in layerEntries:
            mark = _statusMark(modelStatus(llmManager, value))
            print(f"  {key} = {value}  [{mark}]")
    print()


def printDbUsageSection(conn: sqlite3.Connection, llmManager: LLMManager, modelKeys: List[str], dbPath: str) -> None:
    """Print report Section B: model-setting usage in ``chat_settings``.

    Args:
        conn: Open sqlite3 connection.
        llmManager: Initialised ``LLMManager`` (for the availability mark).
        modelKeys: In-scope DB key strings.
        dbPath: Resolved database path (for the section header).

    Returns:
        None; output goes to stdout.
    """
    print(f"== Section B: model settings usage in chat_settings ({dbPath}) ==")

    rows = collectDbUsage(conn, modelKeys)
    if not rows:
        print("(no model settings rows in chat_settings)")
        print()
        return

    colModel = max(len(_HDR_MODEL), *(len(value) for _, value, _ in rows))
    colKey = max(len(_HDR_SETTING_KEY), *(len(key) for key, _, _ in rows))
    colChats = max(len(_HDR_CHATS), *(len(str(count)) for _, _, count in rows))

    print(f"{_HDR_MODEL:<{colModel}}  {_HDR_SETTING_KEY:<{colKey}}  {_HDR_CHATS:<{colChats}}  {_HDR_STATUS}")
    print(f"{'-' * colModel}  {'-' * colKey}  {'-' * colChats}  {'-' * len(_HDR_STATUS)}")
    for key, value, count in rows:
        print(
            f"{value:<{colModel}}  {key:<{colKey}}  {count:<{colChats}}  {_statusMark(modelStatus(llmManager, value))}"
        )
    print()


def printAffectedRows(rows: List[Tuple[int, str]]) -> Dict[str, int]:
    """Print the rows a migration would affect and return per-key counts.

    Args:
        rows: ``(chatId, key)`` pairs from :func:`previewMigration`.

    Returns:
        Per-key row counts (key → count).
    """
    counts: Dict[str, int] = {}
    for chatId, key in rows:
        print(f"  chat_id={chatId} key={key}")
        counts[key] = counts.get(key, 0) + 1
    return counts


def printPerKeyCounts(counts: Dict[str, int], header: str) -> None:
    """Print per-key row counts.

    Args:
        counts: Mapping of setting key to row count.
        header: Heading line printed before the counts.

    Returns:
        None; output goes to stdout.
    """
    print(header)
    if not counts:
        print("  (none)")
        return
    for key in sorted(counts):
        print(f"  {key}: {counts[key]}")
    print(f"  total: {sum(counts.values())}")


def printConfigReferences(botConfig: Dict[str, object], modelKeys: List[str], old: str) -> None:
    """Print the config-reference report for the OLD model id.

    Lists merged-config layer entries still referencing OLD and advises the
    operator to edit the config overlay manually (``--apply`` never rewrites
    config). Prints a "no references" note when the config does not use OLD.

    Args:
        botConfig: The merged ``[bot]`` config dict.
        modelKeys: In-scope DB key strings.
        old: The OLD model id.

    Returns:
        None; output goes to stdout.
    """
    references = findConfigReferences(botConfig, modelKeys, old)
    print(f"\nConfig references to {old!r}:")
    if not references:
        print("  none — the merged config does not reference this model.")
        return
    for reference in references:
        print(f"  {reference}")
    print("  → edit these entries in your config overlay manually; --apply does NOT rewrite config files.")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def buildParser() -> argparse.ArgumentParser:
    """Construct and return the argument parser for this script.

    Extracted at module level so that tests can exercise the parser without
    triggering ``sys.argv`` parsing.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        prog="migrate_models.py",
        description=(
            "Inspect and migrate MODEL chat-setting ids between the merged config layers and the "
            "chat_settings table (report mode by default; --migrate is a dry-run unless --apply)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Report: config layers + chat_settings usage\n"
            "  ./venv/bin/python3 scripts/migrate_models.py\n\n"
            "  # Preview a migration (dry-run: no writes)\n"
            "  ./venv/bin/python3 scripts/migrate_models.py --migrate openrouter/free openrouter/new\n\n"
            "  # Apply the migration (stop the bot first!)\n"
            "  ./venv/bin/python3 scripts/migrate_models.py --migrate openrouter/free openrouter/new --apply\n\n"
            "Exit codes:\n"
            "  0  Success (report, dry-run, or migration applied). In report mode an unresolvable or\n"
            "     missing database (or a missing chat_settings table) is nonfatal: the DB usage section\n"
            "     is skipped with a printed note.\n"
            "  1  Validation / usage error (OLD == NEW, NEW model unavailable, --apply without --migrate,\n"
            "     a missing/unusable database in migration mode, init failure, unexpected runtime errors).\n"
            "  2  Argument-parsing error OR migration rolled back. argparse itself exits 2 on malformed\n"
            "     arguments (e.g. --migrate with a missing second value, or an unknown option) BEFORE\n"
            "     application validation runs — no transaction is attempted in that case. The other\n"
            "     exit-2 case is the apply transaction rolled back: UPDATE row count did not match\n"
            "     the preview.\n"
        ),
    )
    parser.add_argument(
        "--config-dir",
        action="append",
        dest="configDirs",
        metavar="DIR",
        help=(
            "Directory to load .toml config files from (can be specified multiple times). "
            f"Default: {' '.join('--config-dir ' + d for d in _DEFAULT_CONFIG_DIRS)}"
        ),
    )
    parser.add_argument(
        "--dotenv-file",
        default=".env",
        help="Path to .env file with env variables for substitute in configs",
    )
    parser.add_argument(
        "--migrate",
        nargs=2,
        metavar=("OLD_MODEL", "NEW_MODEL"),
        help="Migrate chat settings from OLD_MODEL to NEW_MODEL (dry-run unless --apply)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the migration (without it: dry-run preview only)",
    )
    return parser


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _openDatabase(dbPath: str) -> sqlite3.Connection:
    """Open the SQLite database in autocommit mode (manual transactions).

    Args:
        dbPath: Filesystem path to the SQLite database file.

    Returns:
        The opened ``sqlite3.Connection``.
    """
    return sqlite3.connect(dbPath, isolation_level=None)


def _runReport(configManager: ConfigManager, llmManager: LLMManager, modelKeys: List[str]) -> int:
    """Run the default report mode (Sections A and B).

    Args:
        configManager: Initialised ``ConfigManager``.
        llmManager: Initialised ``LLMManager``.
        modelKeys: In-scope DB key strings.

    Returns:
        Process exit code (always 0; DB problems degrade to printed notes).
    """
    botConfig: Dict[str, object] = configManager.getBotConfig()
    printConfigLayersSection(llmManager, botConfig, modelKeys)

    dbPath = resolveDbPath(configManager.getDatabaseConfig())
    if dbPath is None:
        print("note: could not resolve a SQLite dbPath from the database config — skipping DB usage section")
        return 0
    if not Path(dbPath).exists():
        print(f"note: database file not found: {dbPath} — skipping DB usage section")
        return 0

    conn = _openDatabase(dbPath)
    try:
        if not chatSettingsTableExists(conn):
            print(f"note: table 'chat_settings' does not exist in {dbPath} — skipping DB usage section")
            return 0
        printDbUsageSection(conn, llmManager, modelKeys, dbPath)
    finally:
        conn.close()
    return 0


def _runMigration(
    args: argparse.Namespace,
    configManager: ConfigManager,
    llmManager: LLMManager,
    modelKeys: List[str],
) -> int:
    """Run the migration flow (validations, then dry-run or apply).

    Args:
        args: Parsed CLI arguments (``migrate`` pair, ``apply`` flag).
        configManager: Initialised ``ConfigManager``.
        llmManager: Initialised ``LLMManager``.
        modelKeys: In-scope DB key strings.

    Returns:
        Process exit code: 0 on success, 1 on validation error, 2 when the
        apply transaction was rolled back due to a row-count mismatch.
    """
    old, new = args.migrate

    # --- Validations (no writes; exit non-zero on failure) -----------------
    if old == new:
        print(f"error: OLD and NEW model ids are identical ({old!r}) — nothing to migrate", file=sys.stderr)
        return 1
    if llmManager.getModelInfo(new) is None:
        print(
            f"error: NEW model {new!r} is not available (getModelInfo() returned None) — "
            "refusing to migrate TO an unavailable model",
            file=sys.stderr,
        )
        return 1
    if llmManager.getModelInfo(old) is None:
        print(f"note: OLD model {old!r} is not available (stale id?) — this is expected and fine for a source model")

    # --- Database -----------------------------------------------------------
    dbPath = resolveDbPath(configManager.getDatabaseConfig())
    if dbPath is None:
        print("error: could not resolve a SQLite dbPath from the database config", file=sys.stderr)
        return 1
    if not Path(dbPath).exists():
        print(f"error: database file not found: {dbPath}", file=sys.stderr)
        return 1

    conn = _openDatabase(dbPath)
    try:
        if not chatSettingsTableExists(conn):
            print(f"error: table 'chat_settings' does not exist in {dbPath}", file=sys.stderr)
            return 1

        if args.apply:
            print(
                "WARNING: --apply writes to the database. Stop the bot first: concurrent chat-settings "
                "writes can race with this transaction."
            )
            # Match the repositories' updated_at format exactly:
            # getCurrentTimestamp().isoformat() (see lib/db/utils.py and the
            # convertToSQLite datetime handling in lib/db/providers/utils.py).
            nowStr = getCurrentTimestamp().isoformat()
            try:
                counts = applyMigration(conn, old, new, modelKeys, nowStr)
            except MigrationCountMismatchError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            print(f"Migrated {sum(counts.values())} row(s) from {old!r} to {new!r} (updated_by untouched).")
            printPerKeyCounts(counts, "Per-key migrated counts:")
        else:
            preview = previewMigration(conn, old, modelKeys)
            print(f"== Migration preview: {old!r} → {new!r} (DRY RUN) ==")
            print("Affected rows (chat_id, key):")
            counts = printAffectedRows(preview)
            printPerKeyCounts(counts, "Per-key counts:")
    finally:
        conn.close()

    # --- Config-reference check (both dry-run and apply) --------------------
    botConfig: Dict[str, object] = configManager.getBotConfig()
    printConfigReferences(botConfig, modelKeys, old)

    if not args.apply:
        print("\nDry run — no changes made. Re-run with --apply to write.")
    return 0


def main() -> int:
    """Entry point: parse CLI args and run report or migration mode.

    Returns:
        Process exit code (0 ok; 1 validation/usage error; 2 apply
        count-mismatch rollback — see the module docstring).
    """
    args = buildParser().parse_args()

    if args.apply and not args.migrate:
        print("error: --apply requires --migrate OLD NEW", file=sys.stderr)
        return 1

    configDirs: List[str] = args.configDirs if args.configDirs else _DEFAULT_CONFIG_DIRS
    print(f"Loading configs from: {', '.join(configDirs)}")

    try:
        configManager = ConfigManager(
            configPath="config.toml",
            configDirs=configDirs,
            dotEnvFile=args.dotenv_file,
        )
        # Mandatory before LLMManager: each provider's _initClient() resolves
        # the proxy via ProxyConfig.getCombined() and raises TypeError when the
        # ProxyHelper singleton has not been initialised. Without this the
        # manager silently ends up with 0 models. See scripts/_lib/bootstrap.py.
        bootstrapProxy(configManager)
        llmManager = LLMManager(configManager.getModelsConfig())
    except Exception as exc:
        print(f"error: failed to initialise ConfigManager/LLMManager: {exc}", file=sys.stderr)
        return 1

    modelKeys = collectModelKeys()
    if not modelKeys:
        print("error: no MODEL/IMAGE_MODEL chat settings found in getChatSettingsInfo()", file=sys.stderr)
        return 1

    try:
        if args.migrate:
            return _runMigration(args, configManager, llmManager, modelKeys)
        return _runReport(configManager, llmManager, modelKeys)
    except Exception as exc:
        # MigrationCountMismatchError is handled inside _runMigration (exit 2);
        # anything else here is an unexpected runtime error.
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
