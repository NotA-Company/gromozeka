#!/usr/bin/env ./venv/bin/python3
"""Remove old-format ``memories`` from every ``chat_messages`` row.

The memory-compaction feature stores per-message memories in the ``metadata``
JSON blob of ``chat_messages`` under the top-level key ``memories``. Two shapes
have existed over time:

  * **New (compact) format** -- ``{"permanentIds": ["uuid", ...], "shortTermIds":
    ["uuid", ...]}``. The current bot code only understands this shape (it is
    resolved to content lazily inside ``formatForLLM`` via
    ``cache.getMemoriesByIds``).
  * **Old (content) format** -- ``{"permanent": [SingleMemoryDict, ...],
    "shortTerm": [SingleMemoryDict, ...]}``, written before compaction landed.
    The current code path treats any ``memories`` dict lacking
    ``permanentIds``/``shortTermIds`` as legacy content; such rows render without
    usable memories and just waste space.

This one-off maintenance script walks every row of ``chat_messages`` and, for
rows whose ``memories`` value is the old content format, deletes that single
key, leaving every other metadata key (and all new-format rows) exactly as they
were.

The ``metadata`` column is ``TEXT NOT NULL DEFAULT ''`` so it is never SQL
NULL: an empty string means "no JSON", any other value must be a JSON object
string. Six states are handled per row:

  1. empty string            -> skipped (nothing to parse)
  2. malformed JSON / non-object -> warned to stderr, skipped (never crashes)
  3. JSON without ``memories``    -> skipped
  4. ``memories`` present, new-format (has ``permanentIds``/``shortTermIds``)
     -> skipped and counted separately (left untouched)
  5. ``memories`` present but its value is not a JSON object
     -> warned to stderr, skipped (unexpected shape; not touched)
  6. ``memories`` present and old-format (dict without the compact keys)
     -> key removed, row rewritten (or reported)

Writes are issued in a single transaction (``BEGIN`` ... ``COMMIT``); any
unexpected error during the update batch triggers ``ROLLBACK`` and a non-zero
exit, leaving the database untouched.

Warning: stop the bot before running this script. Rows are read with
``SELECT`` up front and rewritten by primary key later inside the
transaction; if the bot rewrites a row's ``metadata`` in between (a
read-modify-write TOCTOU window), this script's UPDATE would silently
clobber the bot's newer payload (last-writer-wins on the whole column).

Usage::

    ./venv/bin/python3 scripts/clear_old_format_memories.py <dbPath>
    ./venv/bin/python3 scripts/clear_old_format_memories.py <dbPath> --dry-run
    ./venv/bin/python3 scripts/clear_old_format_memories.py <dbPath> -v
    ./venv/bin/python3 scripts/clear_old_format_memories.py <dbPath> -n -v

Args:
    dbPath: Positional path to a SQLite database file.
    --dry-run, -n: Report what would change without writing to the DB.
    -v, --verbose: Print per-row detail (chat_id, message_id, preview).

Returns:
    Exit code 0 on success, non-zero on argument, validation, or runtime error.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from enum import StrEnum
from pathlib import Path
from typing import cast

# The metadata key this script conditionally removes.
_MEMORIES_KEY: str = "memories"

# Compact-format marker keys (presence => new-format, leave untouched).
_COMPACT_KEYS: tuple[str, ...] = ("permanentIds", "shortTermIds")

# Length at which a preview snippet is truncated for verbose output.
_PREVIEW_LIMIT: int = 80


class _MetadataAction(StrEnum):
    """Action decided by ``_classifyMetadata`` for one chat_messages row.

    The members correspond to the per-row states described in the module
    docstring. Verbose-output tags (``[skip-empty]``, ``[WARN]``,
    ``[would-update]``, ...) are emitted separately by the row loop and are
    not derived from these enum values.
    """

    SKIP_EMPTY = "skip-empty"
    SKIP_MALFORMED = "skip-malformed"
    SKIP_NO_KEY = "skip-no-key"
    SKIP_NEW_FORMAT = "skip-new-format"
    UPDATE = "update"


def _previewMemories(value: object) -> str:
    """Build a short, single-line preview of the removed old-format ``memories`` value.

    The old-format value is normally a ``{"permanent": [...], "shortTerm": [...]}``
    mapping of memory-content lists. We surface the list lengths so the operator
    can see how much legacy content each cleared row held; anything structurally
    unexpected falls back to a truncated JSON snippet so the preview is always
    safe to print.

    Args:
        value: The deserialised old-format ``memories`` payload being removed.

    Returns:
        A short, single-line preview string.
    """
    if isinstance(value, dict):
        parts: list[str] = []
        for bucket in ("permanent", "shortTerm"):
            bucketValue = value.get(bucket)
            if isinstance(bucketValue, list):
                parts.append(f"{bucket}={len(bucketValue)}")
        if parts:
            return " ".join(parts)
    snippet = json.dumps(value, ensure_ascii=False)
    if len(snippet) > _PREVIEW_LIMIT:
        snippet = snippet[:_PREVIEW_LIMIT] + "..."
    return snippet


def _classifyMetadata(
    metadata: str,
) -> tuple[_MetadataAction, dict[str, object] | None, str | None]:
    """Classify one row's ``metadata`` value for the clear operation.

    A ``memories`` value is treated as **new-format** iff it is a JSON object
    containing ``permanentIds`` or ``shortTermIds`` (mirroring the compact-ID
    shape that ``formatForLLM`` resolves lazily via ``cache.getMemoriesByIds``).
    Any other JSON-object value under ``memories`` is the legacy content shape
    and is cleared.

    Args:
        metadata: The raw ``metadata`` column value (never SQL NULL; an empty
            string means "no JSON").

    Returns:
        A ``(action, parsedDict, preview)`` tuple. ``action`` is a
        ``_MetadataAction`` member:

        * ``_MetadataAction.SKIP_EMPTY`` -- empty metadata, nothing to parse.
        * ``_MetadataAction.SKIP_MALFORMED`` -- JSON parse failed, the payload
          is not a JSON object, or the ``memories`` value is not a JSON object;
          ``preview`` holds a short reason, ``parsedDict`` is ``None``.
        * ``_MetadataAction.SKIP_NO_KEY`` -- parsed fine but has no
          ``memories`` key.
        * ``_MetadataAction.SKIP_NEW_FORMAT`` -- ``memories`` is the compact
          ID format (has ``permanentIds``/``shortTermIds``); left untouched.
        * ``_MetadataAction.UPDATE`` -- ``memories`` is old-format;
          ``parsedDict`` is the object with the key already removed, and
          ``preview`` describes what was there.
    """
    if not metadata:
        return (_MetadataAction.SKIP_EMPTY, None, None)
    try:
        parsed: object = json.loads(metadata)
    except json.JSONDecodeError as exc:
        return (_MetadataAction.SKIP_MALFORMED, None, str(exc))
    if not isinstance(parsed, dict):
        return (_MetadataAction.SKIP_MALFORMED, None, "metadata JSON is not an object")
    if _MEMORIES_KEY not in parsed:
        return (_MetadataAction.SKIP_NO_KEY, None, None)
    memoriesValue: object = parsed[_MEMORIES_KEY]
    if not isinstance(memoriesValue, dict):
        return (
            _MetadataAction.SKIP_MALFORMED,
            None,
            "memories value is not a JSON object",
        )
    if any(key in memoriesValue for key in _COMPACT_KEYS):
        return (_MetadataAction.SKIP_NEW_FORMAT, None, None)
    preview = _previewMemories(memoriesValue)
    del parsed[_MEMORIES_KEY]
    return (_MetadataAction.UPDATE, parsed, preview)


def processDatabase(dbPath: Path, dryRun: bool, verbose: bool) -> int:
    """Walk ``chat_messages``, drop old-format ``memories`` from each row.

    Reads every row first, classifies it, accumulates the writes, and only then
    opens a single write transaction. This keeps the write lock held for the
    shortest possible window and lets ``--dry-run`` short-circuit before any
    write is attempted.

    Args:
        dbPath: Path to the SQLite database file (already validated to exist).
        dryRun: When ``True``, report changes without writing to the DB.
        verbose: When ``True``, print one line per row with the action and, for
            rows being updated, a preview of the removed value.

    Returns:
        ``0`` on success.
    """
    rowsScanned = 0
    rowsSkipped = 0
    rowsSkippedNewFormat = 0
    rowsUpdated = 0

    # isolation_level=None puts the connection in autocommit mode so we drive
    # BEGIN / COMMIT / ROLLBACK by hand for the write batch.
    conn = sqlite3.connect(str(dbPath), isolation_level=None)
    try:
        # Column order follows the primary-key definition (chat_id, message_id),
        # mirroring the sibling clear_memory_refinement.py script.
        cursor = conn.execute("SELECT chat_id, message_id, metadata FROM chat_messages")
        # Loads the entire chat_messages table into memory. Fine at current scale
        # (single-process SQLite, modest row counts); revisit if it grows large.
        rows: list[tuple[int, str, str]] = cursor.fetchall()

        pendingUpdates: list[tuple[str, int, str]] = []

        for chatId, messageId, metadata in rows:
            rowsScanned += 1
            action, parsed, preview = _classifyMetadata(metadata)

            if action == _MetadataAction.SKIP_EMPTY:
                rowsSkipped += 1
                if verbose:
                    print(f"[skip-empty]    chat_id={chatId} message_id={messageId}")
                continue

            if action == _MetadataAction.SKIP_MALFORMED:
                rowsSkipped += 1
                print(
                    f"[WARN] malformed metadata at chat_id={chatId} message_id={messageId}: {preview}",
                    file=sys.stderr,
                )
                continue

            if action == _MetadataAction.SKIP_NO_KEY:
                rowsSkipped += 1
                if verbose:
                    print(f"[skip-no-key]   chat_id={chatId} message_id={messageId}")
                continue

            if action == _MetadataAction.SKIP_NEW_FORMAT:
                rowsSkippedNewFormat += 1
                if verbose:
                    print(f"[skip-new-fmt]  chat_id={chatId} message_id={messageId}")
                continue

            # action == _MetadataAction.UPDATE -- parsed is non-None with the key removed.
            # Mirror the production jsonDumps serializer shape
            # (lib/utils/utils.py:jsonDumps): sorted keys + compact separators, so the
            # rewritten column stays in its canonical on-disk form and minimises drift
            # against future bot writes. default=str is intentionally omitted: parsed is
            # a fresh json.loads result (dict/list/str/int/float/bool/None), so any
            # unexpected type here is a bug we want surfaced, not silently stringified.
            rowsUpdated += 1
            newMetadata = json.dumps(
                cast(dict[str, object], parsed),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            pendingUpdates.append((newMetadata, chatId, messageId))
            if verbose:
                tag = "would-update" if dryRun else "update"
                print(f"[{tag}] chat_id={chatId} message_id={messageId} removed={preview}")

        if dryRun or not pendingUpdates:
            updateWord = "to update" if dryRun else "updated"
            updatedLabel = f"Rows {updateWord}:"
            # Fixed-width labels (16 chars) keep the numbers column-aligned across
            # both dry-run ("Rows to update:" = 15) and real ("Rows updated:" = 13).
            print(f"{'Rows scanned:':<16}{rowsScanned}")
            print(f"{'Rows skipped:':<16}{rowsSkipped}")
            print(f"{'New-format rows:':<16}{rowsSkippedNewFormat}")
            print(f"{updatedLabel:<16}{rowsUpdated}")
            return 0

        conn.execute("BEGIN")
        try:
            # Same SQL and parameter triple order (newMetadata, chatId, messageId) as
            # the pendingUpdates tuples; executemany is the idiomatic stdlib form for a
            # batch of identical statements inside one transaction. The PK is
            # (chat_id, message_id) per migration_001.
            conn.executemany(
                "UPDATE chat_messages SET metadata = ? WHERE chat_id = ? AND message_id = ?",
                pendingUpdates,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    print(f"{'Rows scanned:':<16}{rowsScanned}")
    print(f"{'Rows skipped:':<16}{rowsSkipped}")
    print(f"{'New-format rows:':<16}{rowsSkippedNewFormat}")
    print(f"{'Rows updated:':<16}{rowsUpdated}")
    return 0


def main() -> int:
    """Entry point: parse CLI args, validate the db path, and run the clear.

    Returns:
        ``0`` on success, ``1`` on argument, validation, or runtime error.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Remove old-format 'memories' from the metadata JSON of every row "
            "in the chat_messages table of a SQLite database. New-format "
            "(compact ID) memories are left untouched."
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
        "-v",
        "--verbose",
        action="store_true",
        help="Print per-row detail (chat_id, message_id, preview).",
    )
    args = parser.parse_args()

    dbPath: Path = args.dbPath
    if not dbPath.exists() or not dbPath.is_file():
        print(f"error: dbPath does not exist or is not a file: {dbPath}", file=sys.stderr)
        return 1

    try:
        return processDatabase(dbPath, args.dryRun, args.verbose)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
