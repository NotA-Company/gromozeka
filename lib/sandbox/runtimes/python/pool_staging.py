"""Host-side staging helpers for the Python sandbox library-pool updates.

All pool-structural logic of the staged-install + atomic-swap update flow
(docs/plans/sandbox-update-v1.md §4.1) lives here — importable and
unit-testable on the host without containers, stdlib only. pip never writes
the live pool: it stages into a private delta directory (in-container, via
``pool_pip_runner.py``), and this module performs every mutation of the pool
copy host-side:

- ``canonicalizeName`` / ``extractSpecName`` / ``isValidCanonicalName``:
  PEP 503 name canonicalization, spec-name extraction, and the grammar gate
  applied to pool-derived names before they reach any argv.
- ``enumerateDistInfos``: dist-info inventory of a pool directory
  (METADATA ``Name:``-first, dir-stem fallback; symlinked entries are
  skipped, never followed).
- ``readRecordPaths``: RECORD CSV parsing with normalization.
- ``mergeStagedDelta``: full-RECORD deletion of the old dist-infos of every
  staged name, then a links-as-links ``copytree`` overlay of the delta onto
  the pool copy (staged symlinks are copied as links, never dereferenced
  host-side).
- ``swapPools``: same-filesystem-guarded two-rename atomic swap with inline
  rollback; a failed rollback raises ``PoolSwapRollbackFailed`` so callers
  can preserve the staging run dir for recovery.
- ``parsePipReport``: fail-safe extraction of resolved name→version pairs
  from a pip ``--dry-run --report`` JSON file.

Functions:
    canonicalizeName: PEP 503 name canonicalization.
    extractSpecName: Extract the bare distribution name from a PEP 508 spec.
    isValidCanonicalName: Grammar gate for pool-derived names.
     enumerateDistInfos: Snapshot ``*.dist-info`` dirs into a name inventory.
     readRecordPaths: Parse a dist-info RECORD file into a normalized path set.
     mergeStagedDelta: Delete old dist-infos per full RECORD, overlay the delta.
     swapPools: Atomically replace the live pool with the merged copy.
     parsePipReport: Extract resolved name→version pairs from a pip report.
"""

import csv
import json
import logging
import os
import posixpath
import re
import shutil
import stat
from pathlib import Path
from typing import NamedTuple

from ...errors import ConfigError, LibraryInstallFailed, PoolSwapRollbackFailed

logger = logging.getLogger(__name__)

DIST_INFO_SUFFIX = ".dist-info"
"""Suffix of package metadata directories inside the pool."""

RECORD_FILENAME = "RECORD"
"""Name of the CSV manifest file inside a dist-info directory."""

METADATA_FILENAME = "METADATA"
"""Name of the core-metadata file inside a dist-info directory."""

SPEC_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
"""Leading distribution-name portion of a PEP 508 spec (docs/plans/sandbox-update-v1.md §6)."""

CANONICAL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")
"""Full PEP 508 distribution-name grammar.

Pool-derived names feed pip's argv during update-all; names failing this
grammar (flag-like, path-like, whitespace) are never safe to pass as
positional requirements and are skipped with a warning.
"""

CANONICAL_SEPARATOR_PATTERN = re.compile(r"[-_.]+")
"""Runs of these characters collapse to a single ``-`` during PEP 503 canonicalization."""


class DistInfoEntry(NamedTuple):
    """One ``*.dist-info`` directory discovered in a pool.

    Attributes:
        path: Path of the dist-info directory.
        version: Version parsed from the directory name.
    """

    path: Path
    version: str


def canonicalizeName(name: str) -> str:
    """Canonicalize a distribution name per PEP 503.

    Lowercases the name and collapses runs of ``-``, ``_`` and ``.`` into a
    single ``-``, so ``Foo_Bar`` matches ``foo-bar``.

    Args:
        name: Raw distribution name.

    Returns:
        The canonical (normalized) name.
    """
    return CANONICAL_SEPARATOR_PATTERN.sub("-", name).lower()


def isValidCanonicalName(name: str) -> bool:
    """Check a pool-derived name against the full PEP 508 name grammar.

    Defense against package-planted or corrupted METADATA: values beginning
    with ``-`` would parse as pip options, and absolute/local-path strings
    would make pip install from the filesystem. The ``--`` separator alone
    cannot guard against those, so such names are rejected outright.

    Args:
        name: Candidate canonical distribution name.

    Returns:
        True when the name is a plain PEP 508 distribution name safe to pass
        to pip as a positional requirement.
    """
    return CANONICAL_NAME_PATTERN.fullmatch(name) is not None


def extractSpecName(spec: str) -> str:
    """Extract the bare distribution-name portion of a PEP 508 spec.

    Args:
        spec: Package spec such as ``numpy>=2.0`` or ``Foo_Bar[extra]``.

    Returns:
        The leading name portion (``numpy``, ``Foo_Bar``), or an empty string
        when the spec does not start with a valid name character.
    """
    match = SPEC_NAME_PATTERN.match(spec)
    return match.group(0) if match is not None else ""


def _isRegularLeaf(path: Path) -> bool:
    """Check a container-controlled leaf path is a regular, non-symlink file.

    NO-FOLLOW semantics: ``Path.is_file()`` would follow links, so this
    combines ``Path.is_symlink()`` with ``os.lstat`` + ``stat.S_ISREG``.
    Guards every host-side open of container-controlled leaf files (dist-info
    METADATA and RECORD, the pip report): a planted symlink must not cross
    the container/host trust boundary, a FIFO would block the host event
    loop on open, and device-like streams could exhaust memory.

    Args:
        path: Candidate leaf path.

    Returns:
        True only when the path is a regular file and not a symlink; False
        for symlinks, FIFOs, devices, directories, and missing paths.
    """
    if path.is_symlink():
        return False
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _parseDistInfoDir(distInfoDir: Path) -> tuple[str, str] | None:
    """Determine the (raw name, version) of a dist-info directory.

    Prefers the ``Name:`` header of the embedded METADATA file (robust against
    directory-name escaping); falls back to splitting the directory stem on
    its last ``-`` (versions never contain ``-``). The METADATA file is a
    container-controlled leaf: it is only opened after the no-follow
    regular-file check (:func:`_isRegularLeaf`), and a present but
    non-regular METADATA (symlink/FIFO/device) or a non-UTF-8 one skips the
    whole entry (the caller warns and leaves it alone).

    Args:
        distInfoDir: Path of the dist-info directory.

    Returns:
        Tuple of (raw distribution name, version), or None when the entry
        must be skipped (non-regular or undecodable METADATA, or neither
        source yields a name — the entry cannot participate in matching and
        is skipped by the caller).
    """
    stem = distInfoDir.name[: -len(DIST_INFO_SUFFIX)]
    version = stem.rpartition("-")[2]
    metadataPath = distInfoDir / METADATA_FILENAME
    if not _isRegularLeaf(metadataPath) and (metadataPath.exists() or metadataPath.is_symlink()):
        # Present but hostile-shaped leaf: never open it, and do not let the
        # entry participate in matching on the directory name alone.
        logger.warning(
            "pool_staging: dist-info %s carries a non-regular METADATA file (symlink/FIFO/device); skipping the entry",
            distInfoDir.name,
        )
        return None
    try:
        with metadataPath.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    break  # headers end at the first blank line
                namePart, sep, value = line.partition(":")
                if sep and namePart.strip().lower() == "name":
                    return (value.strip(), version)
    except UnicodeDecodeError:
        # Binary/garbage METADATA is planted content: the documented
        # per-entry skip applies — the decode failure must not escape
        # enumeration.
        logger.warning(
            "pool_staging: dist-info %s has a non-UTF-8 METADATA file; skipping the entry",
            distInfoDir.name,
        )
        return None
    except OSError:
        pass  # fall through to directory-name parsing
    fallbackName = stem.rpartition("-")[0]
    if not fallbackName or not version:
        return None
    return (fallbackName, version)


def enumerateDistInfos(poolRoot: Path) -> dict[str, list[DistInfoEntry]]:
    """Snapshot a pool into a canonical-name → dist-info inventory.

    Args:
        poolRoot: A pip ``--target`` style install root (the live pool, the
            private pool copy, or the staged delta).

    Returns:
        Mapping from canonical package name (PEP 503) to the dist-info
        entries currently present. Multiple entries under one name indicate
        duplicate installs. Symlinked ``*.dist-info`` entries are skipped,
        never followed: enumeration must not make the host read through any
        staged or planted link (links-as-links policy).

    Raises:
        OSError: If the pool directory cannot be enumerated (missing or
            unreadable). Individual dist-info dirs that cannot be parsed are
            warned about and skipped instead.
    """
    if not poolRoot.is_dir():
        raise OSError(f"Pool directory does not exist or is not a directory: {poolRoot}")
    result: dict[str, list[DistInfoEntry]] = {}
    for entry in poolRoot.iterdir():
        if not entry.name.endswith(DIST_INFO_SUFFIX):
            continue
        if entry.is_symlink() or not entry.is_dir():
            continue  # a symlinked or non-dir *.dist-info entry is not trusted metadata
        parsed = _parseDistInfoDir(entry)
        if parsed is None:
            logger.warning("pool_staging: cannot determine package name of %s; leaving it alone", entry.name)
            continue
        rawName, version = parsed
        result.setdefault(canonicalizeName(rawName), []).append(DistInfoEntry(path=entry, version=version))
    return result


def readRecordPaths(distInfoDir: Path) -> set[str]:
    """Read the set of file paths listed in a dist-info RECORD file.

    RECORD is CSV with ``path,hash,size`` rows; blank and trailing-comma
    lines are tolerated and skipped. Paths are relative to the pool root and
    are normalized with ``posixpath.normpath`` so that equivalent spellings
    (``./pkg/file.py``, ``pkg//file.py``, ``pkg/./file.py``) compare equal —
    deletion still re-applies the pool jail.

    RECORD is a container-controlled leaf: it is never opened unless the
    no-follow regular-file check (:func:`_isRegularLeaf`) passes.

    Args:
        distInfoDir: Path of the dist-info directory.

    Returns:
        Set of normalized relative file paths listed in RECORD.

    Raises:
        OSError: If the RECORD file is missing, is a symlink or another
            non-regular file (rejected before any open — the caller's
            documented skip path applies), or is unreadable.
        UnicodeDecodeError: If RECORD is not valid UTF-8.
        csv.Error: If RECORD is not parseable CSV.
    """
    recordPath = distInfoDir / RECORD_FILENAME
    if not _isRegularLeaf(recordPath):
        # Same OSError shape as a missing/unreadable RECORD so the caller's
        # documented per-package skip (warn + keep the old install) applies.
        raise OSError(f"RECORD file is missing, symlinked, or not a regular file: {recordPath}")
    paths: set[str] = set()
    with recordPath.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if not row:
                continue  # blank line
            first = row[0].strip()
            if not first:
                continue  # trailing-comma-only line
            paths.add(posixpath.normpath(first))
    return paths


def _resolveJailed(poolRootResolved: Path, target: Path) -> Path | None:
    """Resolve *target* and jail-check it against the pool root.

    Mirrors the ``resolveWorkspacePath`` idiom: resolution follows symlinks,
    and the ``relative_to`` check rejects any path that escapes the pool —
    traversal (``../..``), absolute entries, and symlinked escapes alike.

    Args:
        poolRootResolved: Pre-resolved pool root path.
        target: Candidate deletion target.

    Returns:
        The resolved path when it is inside the pool, or None when it
        escapes or cannot be resolved (including symlink loops, which raise
        RuntimeError on Python ≤ 3.12).
    """
    try:
        resolved = target.resolve()
        resolved.relative_to(poolRootResolved)
    except (OSError, ValueError, RuntimeError):
        return None
    return resolved


def _removeOldDistInfo(poolRootResolved: Path, distInfoDir: Path, recordPaths: set[str]) -> None:
    """Delete one old dist-info dir plus every file its RECORD lists (full deletion).

    The set-subtraction of the previous design is gone: the new version lives
    in a separate staged tree, so deleting a path the new install also ships
    is safe — the overlay re-creates it (docs/plans/sandbox-update-v1.md
    §4.1 step 5). Every deletion target is resolved and jailed to the pool
    root first; the resolved path is used ONLY for jail validation — when the
    candidate is itself a symlink, the link is unlinked, never its target.
    Entries that escape (or point at real directories) are skipped with a
    warning.

    Args:
        poolRootResolved: Pre-resolved pool root path.
        distInfoDir: The old dist-info directory to remove.
        recordPaths: Full set of RECORD paths owned by this install.
    """
    for relPath in sorted(recordPaths):
        candidate = distInfoDir.parent / relPath
        resolved = _resolveJailed(poolRootResolved, candidate)
        if resolved is None:
            logger.warning("pool_staging: skipping RECORD entry escaping the pool: %s", relPath)
            continue
        if candidate.is_symlink():
            # Delete the link itself; the resolved path is only the
            # jail-checked identity — unlinking it would delete the target
            # file, which the staged overlay may re-create or another
            # package may own.
            candidate.unlink(missing_ok=True)
            continue
        if resolved.is_dir():
            logger.warning("pool_staging: refusing to delete a directory from RECORD: %s", relPath)
            continue
        resolved.unlink(missing_ok=True)
    resolvedDir = _resolveJailed(poolRootResolved, distInfoDir)
    if resolvedDir is None:
        logger.warning("pool_staging: skipping dist-info dir escaping the pool: %s", distInfoDir)
        return
    if distInfoDir.is_symlink():
        distInfoDir.unlink()
    else:
        shutil.rmtree(distInfoDir)


def mergeStagedDelta(poolCopy: Path, deltaDir: Path) -> None:
    """Merge the staged delta into the pool copy (docs/plans/sandbox-update-v1.md §4.1 step 5).

    For every canonical package name present in the delta: delete the copy's
    old dist-info files per the old RECORD, in full, then remove the old
    dist-info dir. All old dist-infos of a staged name are removed, healing
    pre-existing duplicate installs. Finally the whole delta is copied over
    the copy (``copytree(..., dirs_exist_ok=True, symlinks=True)``).
    Deletion never removes directories not owned by an old RECORD —
    namespace dirs shared with other packages survive. A package whose old
    RECORD is unreadable is skipped entirely (warn) — its staged copy still
    lands beside it; never delete what we cannot account for.

    Symlink policy — links-as-links: the delta is written by pip, including
    arbitrary PEP 517 build code, so anything inside it is container-
    controlled. The overlay therefore copies symlinks as links and every
    host-side validation skips staged links instead of following them; the
    HOST process never reads through a planted link (an absolute or
    directory symlink must not cross the container/host trust boundary),
    while the link itself is preserved verbatim for in-container consumers.

    Args:
        poolCopy: The private pool copy to mutate (never the live pool).
            Must be a real directory, not a symlink.
        deltaDir: The staged pip output directory. Must be a real directory,
            not a symlink.

    Raises:
        LibraryInstallFailed: If poolCopy or deltaDir is a symlink, or
            deltaDir is not a directory — container-controlled paths are
            never dereferenced or merged host-side.
    """
    if poolCopy.is_symlink():
        raise LibraryInstallFailed(f"Pool copy {poolCopy} is a symlink; refusing to merge into it")
    if deltaDir.is_symlink() or not deltaDir.is_dir():
        raise LibraryInstallFailed(f"Staged delta {deltaDir} is a symlink or not a directory; refusing to merge")
    poolCopyResolved = poolCopy.resolve()
    stagedNames = set(enumerateDistInfos(deltaDir).keys())
    poolInventory = enumerateDistInfos(poolCopy)
    for canonicalName in sorted(stagedNames):
        oldDirs = [entry.path for entry in poolInventory.get(canonicalName, [])]
        if not oldDirs:
            continue
        # Read every old RECORD before deleting anything: one unreadable
        # RECORD skips the whole name's deletions.
        pathsByDir: list[tuple[Path, set[str]]] = []
        skipped = False
        for oldDir in oldDirs:
            try:
                pathsByDir.append((oldDir, readRecordPaths(oldDir)))
            except (OSError, UnicodeDecodeError, csv.Error) as exc:
                logger.warning(
                    "pool_staging: old RECORD for '%s' unreadable (%s); skipping the package's deletion entirely",
                    canonicalName,
                    exc,
                )
                skipped = True
                break
        if skipped:
            continue
        for oldDir, recordPaths in pathsByDir:
            _removeOldDistInfo(poolCopyResolved, oldDir, recordPaths)
    # symlinks=True is the links-as-links policy: links land as links, the
    # host never dereferences them (see docstring).
    shutil.copytree(deltaDir, poolCopy, dirs_exist_ok=True, symlinks=True)


def swapPools(pool: Path, newPool: Path, oldPoolParking: Path) -> None:
    """Atomically replace the live pool with the merged copy (docs/plans/sandbox-update-v1.md §4.1 step 6).

    Two renames: pool → oldPoolParking, then newPool → pool. If the second
    rename fails, the original pool is restored inline before the error
    propagates. If the rollback rename ALSO fails, ``PoolSwapRollbackFailed``
    is raised instead: the live pool is absent and both complete copies
    (``oldpool`` + ``newpool``) survive only in the staging run dir, so the
    caller must preserve that dir for startup recovery (plan §4.5) instead
    of cleaning it up. A pre-swap ``st_dev`` guard rejects a staging
    directory on a different filesystem than the pool (rename(2) would fail
    with EXDEV mid-swap) by raising ConfigError instead.

    Args:
        pool: The live pool directory (only this directory is swapped; the
            pool lock file lives OUTSIDE it — plan §4.4).
        newPool: The merged copy that becomes the new pool.
        oldPoolParking: Parking path for the old pool during the swap.

    Raises:
        ConfigError: If pool and newPool live on different filesystems, or a
            directory cannot be stat-ed before the swap.
        PoolSwapRollbackFailed: If the second rename AND the rollback rename
            both fail; carries both errors (the swap error is also chained
            as ``__cause__``).
        OSError: If the second rename fails but the inline rollback
            succeeded (the original pool is back at ``pool``).
    """
    try:
        poolDev = os.stat(pool).st_dev
        newPoolDev = os.stat(newPool).st_dev
    except OSError as exc:
        raise ConfigError(f"Cannot stat pool directories before swap: {exc}") from exc
    if poolDev != newPoolDev:
        raise ConfigError(
            f"Staging directory {newPool} is on a different filesystem than the pool {pool}; the atomic "
            "swap would fail mid-way. Keep the sandbox storage root-dir (staging included) on one mount."
        )
    pool.rename(oldPoolParking)
    try:
        newPool.rename(pool)
    except OSError as swapExc:
        # Inline rollback: restore the original pool before reporting failure.
        try:
            oldPoolParking.rename(pool)
        except OSError as rollbackExc:
            raise PoolSwapRollbackFailed(
                pool=pool,
                oldPoolParking=oldPoolParking,
                swapError=swapExc,
                rollbackError=rollbackExc,
            ) from swapExc
        raise


def parsePipReport(reportPath: Path) -> dict[str, str] | None:
    """Extract resolved name→version pairs from a pip ``--dry-run --report`` JSON file.

    The report's ``install[]`` array carries one entry per resolved
    requirement with its ``metadata`` (name/version). The parse is fail-safe:
    a missing file, a symlinked or otherwise non-regular file (never opened —
    no-follow leaf guard), malformed JSON, or unexpected root structure
    returns None so callers treat EVERY spec as outdated (full stage) — a
    wrong skip would silently leave packages outdated, while a full stage
    merely re-installs (docs/plans/sandbox-update-v1.md §4.2). Individual
    entries with missing or non-string metadata fields are skipped.

    Args:
        reportPath: Host-side path of the fetched pip report JSON.

    Returns:
        Mapping from canonical package name (PEP 503) to the resolved
        version, or None when the report cannot be parsed.
    """
    if not _isRegularLeaf(reportPath):
        logger.warning(
            "pool_staging: pip report %s is missing, symlinked, or not a regular file; treating every spec as outdated",
            reportPath,
        )
        return None
    try:
        with reportPath.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning(
            "pool_staging: cannot parse pip report %s (%s); treating every spec as outdated", reportPath, exc
        )
        return None
    if not isinstance(data, dict):
        logger.warning("pool_staging: pip report root is not an object; treating every spec as outdated")
        return None
    installList = data.get("install")
    if not isinstance(installList, list):
        logger.warning("pool_staging: pip report has no install[] array; treating every spec as outdated")
        return None
    result: dict[str, str] = {}
    for entry in installList:
        if not isinstance(entry, dict):
            continue
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict):
            continue
        name = metadata.get("name")
        version = metadata.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            continue
        result[canonicalizeName(name)] = version
    return result
