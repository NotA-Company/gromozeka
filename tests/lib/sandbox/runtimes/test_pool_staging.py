"""Tests for the host-side pool staging helpers (pool_staging.py).

Covers the ratified contract (docs/plans/sandbox-update-v1.md §12): dist-info
enumeration name extraction (METADATA ``Name:`` preferred, dir-stem fallback,
hyphenated names), RECORD parsing with normpath equivalence, PEP 503
canonicalization and the name-grammar gate, merge correctness (old-only files
deleted, shared paths re-created from the delta, other packages and shared
namespace dirs untouched, multiple old dist-infos all removed, directory
RECORD entries refused, unreadable old RECORD skips the package's deletion),
jail rejection (traversal, absolute, symlink-out), symlink entries unlinking
the link never the target, the staged-symlink links-as-links policy (absolute
/ directory / dangling links are copied as links, never dereferenced in the
host process; symlinked dist-info entries are skipped; symlinked or
non-directory delta/pool-copy roots are rejected), the two-rename pool swap
(same-filesystem guard via mocked ``st_dev``, inline rollback on
second-rename failure, ``PoolSwapRollbackFailed`` when the rollback fails
too), fail-safe pip report parsing, and the container-controlled leaf-file
guards (METADATA, RECORD and report.json are never opened through a
symlink/FIFO — no-follow lstat check before any open — and non-UTF-8
METADATA hits the documented per-entry skip instead of crashing
enumeration). No containers, no pip.
"""

import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.sandbox.errors import ConfigError, LibraryInstallFailed, PoolSwapRollbackFailed
from lib.sandbox.runtimes.python import pool_staging

# ============================================================================
# Helpers
# ============================================================================


def _makeDistInfo(
    poolDir: Path,
    dirName: str,
    *,
    name: str,
    version: str,
    recordPaths: list[str],
    fileContents: dict[str, str] | None = None,
    withMetadata: bool = True,
) -> Path:
    """Create a fake dist-info directory (METADATA + RECORD + payload files).

    Args:
        poolDir: Pool root; RECORD paths are created relative to it.
        dirName: dist-info directory name (should end with ``.dist-info``).
        name: Value for the METADATA ``Name:`` header.
        version: Value for the METADATA ``Version:`` header.
        recordPaths: Paths listed in RECORD (relative to the pool root).
        fileContents: Optional exact bodies for payload files (keys relative
            to the pool root); defaults to a placeholder body per path.
        withMetadata: Whether to write a METADATA file.

    Returns:
        The created dist-info directory path.
    """
    distInfoDir = poolDir / dirName
    distInfoDir.mkdir(parents=True)
    if withMetadata:
        (distInfoDir / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
            encoding="utf-8",
        )
    lines = [f"{p},sha256={'0' * 8},{11 + len(p)}" for p in recordPaths]
    lines.append(f"{dirName}/RECORD,,")
    (distInfoDir / "RECORD").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for recordPath in recordPaths:
        if recordPath.endswith("RECORD"):
            continue
        target = poolDir / recordPath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((fileContents or {}).get(recordPath, f"body of {recordPath}"), encoding="utf-8")
    return distInfoDir


def _makeStagedDistInfo(
    deltaDir: Path,
    dirName: str,
    *,
    name: str,
    version: str,
    recordPaths: list[str],
    fileContents: dict[str, str] | None = None,
) -> Path:
    """Create a fake dist-info directory inside a staged delta.

    Identical to :func:`_makeDistInfo` (same on-disk shape pip produces under
    ``--target``); separate name for test readability.

    Args:
        deltaDir: The staged delta root; RECORD paths are created relative
            to it.
        dirName: dist-info directory name (should end with ``.dist-info``).
        name: Value for the METADATA ``Name:`` header.
        version: Value for the METADATA ``Version:`` header.
        recordPaths: Paths listed in RECORD (relative to the delta root).
        fileContents: Optional exact bodies for payload files.

    Returns:
        The created dist-info directory path.
    """
    return _makeDistInfo(
        deltaDir,
        dirName,
        name=name,
        version=version,
        recordPaths=recordPaths,
        fileContents=fileContents,
    )


# ============================================================================
# Enumeration — name extraction
# ============================================================================


class TestEnumeration:
    """Tests for enumerateDistInfos name extraction."""

    def testMetadataNamePreferredOverDirName(self, tmp_path: Path) -> None:
        """The METADATA ``Name:`` header wins over the directory name.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolDir = tmp_path / "libs"
        poolDir.mkdir()
        _makeDistInfo(
            poolDir,
            "weird-dirname-9.9.dist-info",
            name="real-pkg",
            version="9.9",
            recordPaths=["real/mod.py"],
        )

        inventory = pool_staging.enumerateDistInfos(poolDir)

        assert set(inventory.keys()) == {"real-pkg"}
        assert inventory["real-pkg"][0].version == "9.9"

    def testStemFallbackWithoutMetadata(self, tmp_path: Path) -> None:
        """A dist-info dir without METADATA still parses via its directory name.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolDir = tmp_path / "libs"
        poolDir.mkdir()
        _makeDistInfo(
            poolDir,
            "some_pkg-1.0.dist-info",
            name="ignored",
            version="1.0",
            recordPaths=[],
            withMetadata=False,
        )

        inventory = pool_staging.enumerateDistInfos(poolDir)

        assert set(inventory.keys()) == {"some-pkg"}

    def testHyphenatedNameFromMetadata(self, tmp_path: Path) -> None:
        """Hyphenated distribution names (e.g. scikit-learn) extract cleanly.

        The dir-stem hyphen-split is never applied when METADATA carries the
        name — no fragile name/version splitting.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolDir = tmp_path / "libs"
        poolDir.mkdir()
        _makeDistInfo(
            poolDir,
            "scikit_learn-1.4.2.dist-info",
            name="scikit-learn",
            version="1.4.2",
            recordPaths=["skl/mod.py"],
        )

        inventory = pool_staging.enumerateDistInfos(poolDir)

        assert set(inventory.keys()) == {"scikit-learn"}
        assert inventory["scikit-learn"][0].version == "1.4.2"

    def testMissingPoolRaisesOSError(self, tmp_path: Path) -> None:
        """A non-enumerable pool root raises OSError (caller decides).

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        with pytest.raises(OSError):
            pool_staging.enumerateDistInfos(tmp_path / "missing-pool")


# ============================================================================
# RECORD parsing
# ============================================================================


class TestRecordParsing:
    """Tests for readRecordPaths."""

    def testParsesHashSizeBlankAndTrailingCommaLines(self, tmp_path: Path) -> None:
        """RECORD rows with hash/size columns parse; blank and trailing-comma
        lines are tolerated and skipped.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        distInfoDir = tmp_path / "pkg-1.0.dist-info"
        distInfoDir.mkdir()
        record = distInfoDir / "RECORD"
        record.write_text(
            "pkg/__init__.py,sha256=abc123,42\n"
            "\n"
            "pkg/mod.py,sha256=def456,100\n"
            "pkg/data.py,\n"
            ",\n"
            "pkg-1.0.dist-info/RECORD,,\n",
            encoding="utf-8",
        )

        paths = pool_staging.readRecordPaths(distInfoDir)

        assert paths == {
            "pkg/__init__.py",
            "pkg/mod.py",
            "pkg/data.py",
            "pkg-1.0.dist-info/RECORD",
        }

    def testNormpathEquivalence(self, tmp_path: Path) -> None:
        """Equivalent RECORD spellings normalize to one path.

        ``./pkg/mod.py``, ``pkg//mod.py`` and ``pkg/./mod.py`` must compare
        equal so the full-RECORD deletion hits the same file exactly once.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        distInfoDir = tmp_path / "pkg-1.0.dist-info"
        distInfoDir.mkdir()
        record = distInfoDir / "RECORD"
        record.write_text(
            "./pkg/mod.py,sha256=abc123,42\n"
            "pkg//mod.py,sha256=abc123,42\n"
            "pkg/./mod.py,sha256=abc123,42\n"
            "pkg-1.0.dist-info/RECORD,,\n",
            encoding="utf-8",
        )

        paths = pool_staging.readRecordPaths(distInfoDir)

        assert paths == {"pkg/mod.py", "pkg-1.0.dist-info/RECORD"}

    def testMissingRecordRaisesOSError(self, tmp_path: Path) -> None:
        """A dist-info dir without RECORD raises OSError (caller skips the package).

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        distInfoDir = tmp_path / "pkg-1.0.dist-info"
        distInfoDir.mkdir()
        with pytest.raises(OSError):
            pool_staging.readRecordPaths(distInfoDir)


# ============================================================================
# Name grammar
# ============================================================================


class TestGrammar:
    """Tests for canonicalizeName / isValidCanonicalName / extractSpecName."""

    def testCanonicalizeMatchesVariants(self) -> None:
        """Separator runs collapse and casing folds per PEP 503.

        Args:
            None

        Returns:
            None
        """
        assert pool_staging.canonicalizeName("Foo_Bar") == "foo-bar"
        assert pool_staging.canonicalizeName("foo-bar") == "foo-bar"
        assert pool_staging.canonicalizeName("Foo...Bar__baz") == "foo-bar-baz"

    def testIsValidCanonicalNameGrammar(self) -> None:
        """The validator accepts plain PEP 508 names and rejects hostile strings.

        Args:
            None

        Returns:
            None
        """
        assert pool_staging.isValidCanonicalName("numpy")
        assert pool_staging.isValidCanonicalName("scikit-learn")
        assert pool_staging.isValidCanonicalName("a1-b2")
        assert not pool_staging.isValidCanonicalName("-r")
        assert not pool_staging.isValidCanonicalName("--requirement")
        assert not pool_staging.isValidCanonicalName("foo-")  # trailing separator
        assert not pool_staging.isValidCanonicalName("/tmp/evil")  # absolute path
        assert not pool_staging.isValidCanonicalName("../escape")  # relative path
        assert not pool_staging.isValidCanonicalName("has space")
        assert not pool_staging.isValidCanonicalName("")

    def testExtractSpecName(self) -> None:
        """The name portion is extracted from specs with version/extras parts.

        Args:
            None

        Returns:
            None
        """
        assert pool_staging.extractSpecName("numpy>=2.0") == "numpy"
        assert pool_staging.extractSpecName("Foo_Bar[extra]==1.0") == "Foo_Bar"
        assert pool_staging.extractSpecName("plain") == "plain"
        assert pool_staging.extractSpecName("=1.0") == ""


# ============================================================================
# mergeStagedDelta — merge correctness
# ============================================================================


class TestMergeStagedDelta:
    """Tests for mergeStagedDelta (full-RECORD deletion + copytree overlay)."""

    def testOldOnlyDeletedAndStagedLands(self, tmp_path: Path) -> None:
        """Old-only files and the old dist-info are deleted; the staged tree lands.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        _makeDistInfo(
            poolCopy,
            "pkg-1.0.dist-info",
            name="pkg",
            version="1.0",
            recordPaths=["pkg/old_only.py", "pkg/kept.py"],
        )
        deltaDir = tmp_path / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "pkg-2.0.dist-info",
            name="pkg",
            version="2.0",
            recordPaths=["pkg/new_only.py", "pkg/kept.py"],
            fileContents={"pkg/kept.py": "new body"},
        )

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        assert not (poolCopy / "pkg-1.0.dist-info").exists()
        assert not (poolCopy / "pkg" / "old_only.py").exists()
        assert (poolCopy / "pkg" / "kept.py").read_text(encoding="utf-8") == "new body"
        assert (poolCopy / "pkg" / "new_only.py").exists()
        assert (poolCopy / "pkg-2.0.dist-info").is_dir()

    def testSharedPathDeletedThenRecreatedFromDelta(self, tmp_path: Path) -> None:
        """A file shipped by both versions carries the new body after the merge.

        The new version lives in a separate staged tree, so deleting the old
        copy first (full-RECORD deletion) and letting the overlay re-create
        the path is safe by construction (plan §9).

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        _makeDistInfo(
            poolCopy,
            "numpy-1.0.dist-info",
            name="numpy",
            version="1.0",
            recordPaths=["numpy/__init__.py"],
            fileContents={"numpy/__init__.py": "old body"},
        )
        deltaDir = tmp_path / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "numpy-2.0.dist-info",
            name="numpy",
            version="2.0",
            recordPaths=["numpy/__init__.py"],
            fileContents={"numpy/__init__.py": "new body"},
        )

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        assert (poolCopy / "numpy" / "__init__.py").read_text(encoding="utf-8") == "new body"
        assert not (poolCopy / "numpy-1.0.dist-info").exists()
        assert (poolCopy / "numpy-2.0.dist-info").is_dir()

    def testOtherPackagesUntouched(self, tmp_path: Path) -> None:
        """Packages absent from the delta keep their files and dist-infos.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        _makeDistInfo(
            poolCopy,
            "other-1.0.dist-info",
            name="other",
            version="1.0",
            recordPaths=["other/mod.py"],
            fileContents={"other/mod.py": "other body"},
        )
        _makeDistInfo(
            poolCopy,
            "pkg-1.0.dist-info",
            name="pkg",
            version="1.0",
            recordPaths=["pkg/old.py"],
        )
        deltaDir = tmp_path / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "pkg-2.0.dist-info",
            name="pkg",
            version="2.0",
            recordPaths=["pkg/new.py"],
        )

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        assert (poolCopy / "other" / "mod.py").read_text(encoding="utf-8") == "other body"
        assert (poolCopy / "other-1.0.dist-info").is_dir()

    def testNamespaceDirsSharedAcrossPackagesSurvive(self, tmp_path: Path) -> None:
        """A namespace dir shared with an unstaged package survives the merge.

        Deletion only removes files listed in the old RECORD — never
        directories — so ``ns/__init__.py`` owned by another package survives
        while the staged package's old file inside ``ns/`` is removed.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        _makeDistInfo(
            poolCopy,
            "other-1.0.dist-info",
            name="other",
            version="1.0",
            recordPaths=["ns/__init__.py"],
            fileContents={"ns/__init__.py": "namespace init"},
        )
        _makeDistInfo(
            poolCopy,
            "pkg-1.0.dist-info",
            name="pkg",
            version="1.0",
            recordPaths=["ns/old.py"],
        )
        deltaDir = tmp_path / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "pkg-2.0.dist-info",
            name="pkg",
            version="2.0",
            recordPaths=["ns/new.py"],
        )

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        assert (poolCopy / "ns").is_dir()
        assert (poolCopy / "ns" / "__init__.py").read_text(encoding="utf-8") == "namespace init"
        assert not (poolCopy / "ns" / "old.py").exists()
        assert (poolCopy / "ns" / "new.py").exists()

    def testMultipleOldDistInfosAllRemoved(self, tmp_path: Path) -> None:
        """Pre-existing duplicate dist-infos of a staged name are all removed.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        _makeDistInfo(
            poolCopy,
            "dup-1.0.dist-info",
            name="dup",
            version="1.0",
            recordPaths=["dup/one.py"],
        )
        _makeDistInfo(
            poolCopy,
            "dup-1.1.dist-info",
            name="dup",
            version="1.1",
            recordPaths=["dup/two.py"],
        )
        deltaDir = tmp_path / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "dup-2.0.dist-info",
            name="dup",
            version="2.0",
            recordPaths=["dup/fresh.py"],
        )

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        assert not (poolCopy / "dup-1.0.dist-info").exists()
        assert not (poolCopy / "dup-1.1.dist-info").exists()
        assert not (poolCopy / "dup" / "one.py").exists()
        assert not (poolCopy / "dup" / "two.py").exists()
        assert (poolCopy / "dup-2.0.dist-info").is_dir()
        assert (poolCopy / "dup" / "fresh.py").exists()

    def testDirectoryRecordEntryRefused(self, tmp_path: Path) -> None:
        """A RECORD entry pointing at a real directory is refused, not deleted.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        _makeDistInfo(
            poolCopy,
            "pkg-1.0.dist-info",
            name="pkg",
            version="1.0",
            recordPaths=["pkg/keep.py"],
        )
        dataDir = poolCopy / "pkg" / "data"
        dataDir.mkdir()
        (dataDir / "inside.txt").write_text("dir payload", encoding="utf-8")
        record = poolCopy / "pkg-1.0.dist-info" / "RECORD"
        record.write_text(
            f"pkg/data,sha256=xx,1\n{record.read_text(encoding='utf-8')}",
            encoding="utf-8",
        )
        deltaDir = tmp_path / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "pkg-2.0.dist-info",
            name="pkg",
            version="2.0",
            recordPaths=["pkg/new.py"],
        )

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        assert (poolCopy / "pkg" / "data" / "inside.txt").read_text(encoding="utf-8") == "dir payload"
        assert not (poolCopy / "pkg-1.0.dist-info").exists()

    def testUnreadableOldRecordSkipsDeletionButStagedStillLands(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unreadable old RECORD skips the whole name's deletions; the staged
        copy still lands beside it.

        The old RECORD is replaced by a directory so the read fails
        deterministically regardless of the effective uid.

        Args:
            tmp_path: pytest-provided temporary directory.
            caplog: pytest log capture fixture.

        Returns:
            None
        """
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        _makeDistInfo(
            poolCopy,
            "guard-1.0.dist-info",
            name="guard",
            version="1.0",
            recordPaths=["guard/old_only.py"],
        )
        recordPath = poolCopy / "guard-1.0.dist-info" / "RECORD"
        recordPath.unlink()
        recordPath.mkdir()
        deltaDir = tmp_path / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "guard-2.0.dist-info",
            name="guard",
            version="2.0",
            recordPaths=["guard/new.py"],
        )

        with caplog.at_level(logging.WARNING, logger="lib.sandbox.runtimes.python.pool_staging"):
            pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        # Nothing deleted for the unreadable name...
        assert (poolCopy / "guard-1.0.dist-info").is_dir()
        assert (poolCopy / "guard" / "old_only.py").exists()
        # ...but the staged copy still landed beside it.
        assert (poolCopy / "guard-2.0.dist-info").is_dir()
        assert (poolCopy / "guard" / "new.py").exists()
        assert any("unreadable" in message for message in caplog.messages)

    def testEmptyDeltaLeavesPoolCopyIntact(self, tmp_path: Path) -> None:
        """A delta with no dist-infos performs no deletions.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        _makeDistInfo(
            poolCopy,
            "pkg-1.0.dist-info",
            name="pkg",
            version="1.0",
            recordPaths=["pkg/mod.py"],
        )
        deltaDir = tmp_path / "delta"
        deltaDir.mkdir()

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        assert (poolCopy / "pkg-1.0.dist-info").is_dir()
        assert (poolCopy / "pkg" / "mod.py").exists()


# ============================================================================
# Jail checks (exercised through mergeStagedDelta)
# ============================================================================


class TestJail:
    """Deletion targets escaping the pool copy root must be skipped."""

    def testTraversalEscapeRejected(self, tmp_path: Path) -> None:
        """A ``../..`` RECORD entry is skipped and the outside file survives.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        root = tmp_path / "run"
        poolCopy = root / "newpool"
        poolCopy.mkdir(parents=True)
        outsideFile = root / "outside.txt"
        _makeDistInfo(
            poolCopy,
            "evil-1.0.dist-info",
            name="evil",
            version="1.0",
            recordPaths=["../outside.txt", "evil/kept.py"],
            fileContents={"../outside.txt": "victim"},
        )
        deltaDir = root / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "evil-2.0.dist-info",
            name="evil",
            version="2.0",
            recordPaths=["evil/new.py"],
        )

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        assert outsideFile.read_text(encoding="utf-8") == "victim"
        # The old dist-info dir itself is jailed-safe and still removed.
        assert not (poolCopy / "evil-1.0.dist-info").exists()

    def testAbsoluteRecordPathRejected(self, tmp_path: Path) -> None:
        """An absolute RECORD entry is skipped, never deleted.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        root = tmp_path / "run"
        poolCopy = root / "newpool"
        poolCopy.mkdir(parents=True)
        absoluteVictim = root / "abs_victim.txt"
        absoluteVictim.write_text("victim", encoding="utf-8")
        _makeDistInfo(
            poolCopy,
            "abs-1.0.dist-info",
            name="abs",
            version="1.0",
            recordPaths=["abs/kept.py"],
        )
        # Inject an absolute entry pointing outside the pool.
        record = poolCopy / "abs-1.0.dist-info" / "RECORD"
        record.write_text(
            f"{absoluteVictim},sha256=xx,1\n{record.read_text(encoding='utf-8')}",
            encoding="utf-8",
        )
        deltaDir = root / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "abs-2.0.dist-info",
            name="abs",
            version="2.0",
            recordPaths=["abs/new.py"],
        )

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        assert absoluteVictim.read_text(encoding="utf-8") == "victim"
        assert not (poolCopy / "abs-1.0.dist-info").exists()

    def testSymlinkEscapeRejected(self, tmp_path: Path) -> None:
        """A symlinked RECORD entry resolving outside the pool is never followed.

        The whole entry is skipped: the symlink stays in place and its
        target survives.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        root = tmp_path / "run"
        poolCopy = root / "newpool"
        poolCopy.mkdir(parents=True)
        outsideDir = root / "outside"
        outsideDir.mkdir()
        victim = outsideDir / "victim.txt"
        victim.write_text("victim", encoding="utf-8")
        _makeDistInfo(
            poolCopy,
            "linky-1.0.dist-info",
            name="linky",
            version="1.0",
            recordPaths=["linky/kept.py"],
        )
        linkPath = poolCopy / "linky" / "escape_link.txt"
        linkPath.symlink_to(victim)
        # List the symlink in the old RECORD.
        record = poolCopy / "linky-1.0.dist-info" / "RECORD"
        record.write_text(
            f"linky/escape_link.txt,sha256=xx,1\n{record.read_text(encoding='utf-8')}",
            encoding="utf-8",
        )
        deltaDir = root / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "linky-2.0.dist-info",
            name="linky",
            version="2.0",
            recordPaths=["linky/new.py"],
        )

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        assert victim.read_text(encoding="utf-8") == "victim"
        assert linkPath.is_symlink()  # entry skipped entirely, symlink untouched

    def testInPoolSymlinkEntryUnlinksLinkNotTarget(self, tmp_path: Path) -> None:
        """An in-pool RECORD symlink is removed as a link; its target survives.

        The target here is a file the staged installation now owns — deleting
        the resolved path would corrupt the new install.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        _makeDistInfo(
            poolCopy,
            "linky-1.0.dist-info",
            name="linky",
            version="1.0",
            recordPaths=["linky/alias.py"],
        )
        sharedFile = poolCopy / "linky" / "shared.py"
        sharedFile.write_text("new body", encoding="utf-8")
        aliasPath = poolCopy / "linky" / "alias.py"
        aliasPath.unlink()
        aliasPath.symlink_to(sharedFile)
        deltaDir = tmp_path / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "linky-2.0.dist-info",
            name="linky",
            version="2.0",
            recordPaths=["linky/shared.py"],
            fileContents={"linky/shared.py": "new body"},
        )

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        # The link is gone; the target file (owned by the staged install) survives.
        assert not aliasPath.is_symlink()
        assert not aliasPath.exists()
        assert sharedFile.read_text(encoding="utf-8") == "new body"
        assert not (poolCopy / "linky-1.0.dist-info").exists()
        assert (poolCopy / "linky-2.0.dist-info").is_dir()


# ============================================================================
# Staged-symlink policy (links-as-links)
# ============================================================================


class TestStagedSymlinkPolicy:
    """The host never dereferences container-controlled links during a merge.

    Policy: links-as-links. The delta is written by pip, including arbitrary
    PEP 517 build code, so its symlinks are copied as links
    (``copytree(..., symlinks=True)``) and every host-side validation skips
    links instead of following them. Host targets must NOT be read; links are
    preserved verbatim for in-container consumers; the merge still succeeds.
    """

    def testStagedAbsoluteSymlinkCopiedAsLinkNotDereferenced(self, tmp_path: Path) -> None:
        """An absolute link in the delta lands as a link; the host target is not read.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        secretFile = tmp_path / "host_secret.txt"
        secretFile.write_text("TOP SECRET", encoding="utf-8")
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        deltaDir = tmp_path / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "pkg-2.0.dist-info",
            name="pkg",
            version="2.0",
            recordPaths=["pkg/new.py"],
        )
        (deltaDir / "leak").symlink_to(secretFile)  # absolute symlink

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        # Copied as a link, never dereferenced into a host-read regular file.
        copiedPath = poolCopy / "leak"
        assert copiedPath.is_symlink()
        assert copiedPath.readlink() == secretFile
        # The host target was not read, moved or modified.
        assert secretFile.read_text(encoding="utf-8") == "TOP SECRET"
        # The merge itself still succeeded.
        assert (poolCopy / "pkg-2.0.dist-info").is_dir()
        assert (poolCopy / "pkg" / "new.py").exists()

    def testStagedDirectorySymlinkCopiedAsLinkTargetNotRead(self, tmp_path: Path) -> None:
        """A directory link in the delta is not recursed into by the host.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        outsideDir = tmp_path / "outside_pkg"
        outsideDir.mkdir()
        (outsideDir / "payload.txt").write_text("outside payload", encoding="utf-8")
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        deltaDir = tmp_path / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "pkg-2.0.dist-info",
            name="pkg",
            version="2.0",
            recordPaths=["pkg/new.py"],
        )
        (deltaDir / "pkgdata").symlink_to(outsideDir)  # absolute directory symlink

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        # The link landed as a link; the outside tree was NOT walked/copied
        # into the pool as real files (the only new entry is the link).
        assert (poolCopy / "pkgdata").is_symlink()
        assert not (poolCopy / "outside_pkg").exists()
        assert (outsideDir / "payload.txt").read_text(encoding="utf-8") == "outside payload"
        assert set(pool_staging.enumerateDistInfos(deltaDir).keys()) == {"pkg"}

    def testStagedDanglingSymlinkCopiedAsLinkAndMergeSucceeds(self, tmp_path: Path) -> None:
        """A dangling link in the delta neither breaks the merge nor dereferences.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        deltaDir = tmp_path / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "pkg-2.0.dist-info",
            name="pkg",
            version="2.0",
            recordPaths=["pkg/new.py"],
        )
        (deltaDir / "ghost").symlink_to(deltaDir / "nowhere")  # dangling

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        assert (poolCopy / "ghost").is_symlink()
        assert not (poolCopy / "ghost").exists()  # dangling stays dangling
        assert (poolCopy / "pkg-2.0.dist-info").is_dir()

    def testSymlinkedDeltaRootRejected(self, tmp_path: Path) -> None:
        """A symlinked delta root is rejected before any host-side work.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        realDelta = tmp_path / "real-delta"
        realDelta.mkdir()
        _makeStagedDistInfo(
            realDelta,
            "pkg-2.0.dist-info",
            name="pkg",
            version="2.0",
            recordPaths=["pkg/new.py"],
        )
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        _makeDistInfo(
            poolCopy,
            "pkg-1.0.dist-info",
            name="pkg",
            version="1.0",
            recordPaths=["pkg/old.py"],
        )
        deltaLink = tmp_path / "delta"
        deltaLink.symlink_to(realDelta)

        with pytest.raises(LibraryInstallFailed):
            pool_staging.mergeStagedDelta(poolCopy, deltaLink)

        # Nothing was deleted or copied through the link.
        assert (poolCopy / "pkg-1.0.dist-info").is_dir()
        assert (poolCopy / "pkg" / "old.py").exists()

    def testNonDirectoryDeltaRootRejected(self, tmp_path: Path) -> None:
        """A non-directory delta root is rejected before any host-side work.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        deltaDir = tmp_path / "delta"
        deltaDir.write_text("not a directory", encoding="utf-8")

        with pytest.raises(LibraryInstallFailed):
            pool_staging.mergeStagedDelta(poolCopy, deltaDir)

    def testSymlinkedPoolCopyRejected(self, tmp_path: Path) -> None:
        """A symlinked pool copy is rejected (defense in depth).

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        realCopy = tmp_path / "real-copy"
        realCopy.mkdir()
        _makeDistInfo(
            realCopy,
            "pkg-1.0.dist-info",
            name="pkg",
            version="1.0",
            recordPaths=["pkg/old.py"],
        )
        poolCopyLink = tmp_path / "newpool"
        poolCopyLink.symlink_to(realCopy)
        deltaDir = tmp_path / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir,
            "pkg-2.0.dist-info",
            name="pkg",
            version="2.0",
            recordPaths=["pkg/new.py"],
        )

        with pytest.raises(LibraryInstallFailed):
            pool_staging.mergeStagedDelta(poolCopyLink, deltaDir)

        # The dereferenced target was never mutated.
        assert (realCopy / "pkg-1.0.dist-info").is_dir()
        assert (realCopy / "pkg" / "old.py").exists()
        assert not (realCopy / "pkg-2.0.dist-info").exists()

    def testSymlinkedDistInfoInDeltaSkippedNotFollowed(self, tmp_path: Path) -> None:
        """A symlinked *.dist-info entry is skipped by enumeration, not followed.

        The link points at an outside directory whose METADATA claims the
        same package name as a live pool package: following it would make
        the host delete pool content based on files the container never
        staged (and read host-side paths on the way).

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        outsideDistInfo = tmp_path / "outside.dist-info"
        outsideDistInfo.mkdir()
        (outsideDistInfo / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: evil\nVersion: 9.9\n",
            encoding="utf-8",
        )
        poolCopy = tmp_path / "newpool"
        poolCopy.mkdir()
        _makeDistInfo(
            poolCopy,
            "evil-1.0.dist-info",
            name="evil",
            version="1.0",
            recordPaths=["evil/old.py"],
        )
        deltaDir = tmp_path / "delta"
        deltaDir.mkdir()
        (deltaDir / "evil-9.9.dist-info").symlink_to(outsideDistInfo)

        # Enumeration skips the symlinked entry entirely.
        assert pool_staging.enumerateDistInfos(deltaDir) == {}

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        # No deletion was driven by the followed link; the link lands as a link.
        assert (poolCopy / "evil-1.0.dist-info").is_dir()
        assert (poolCopy / "evil" / "old.py").exists()
        assert (poolCopy / "evil-9.9.dist-info").is_symlink()
        assert (outsideDistInfo / "METADATA").read_text(encoding="utf-8").startswith("Metadata-Version: 2.1")


# ============================================================================
# swapPools
# ============================================================================


class TestSwapPools:
    """Tests for swapPools (same-FS guard, rename pair, inline rollback)."""

    def testSwapReplacesPool(self, tmp_path: Path) -> None:
        """On success the merged copy sits at the pool path; the old pool parks.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        pool = tmp_path / "libs"
        pool.mkdir()
        (pool / "a.txt").write_text("old", encoding="utf-8")
        newPool = tmp_path / "newpool"
        newPool.mkdir()
        (newPool / "b.txt").write_text("new", encoding="utf-8")
        oldPoolParking = tmp_path / "oldpool"

        pool_staging.swapPools(pool, newPool, oldPoolParking)

        assert (pool / "b.txt").read_text(encoding="utf-8") == "new"
        assert not (pool / "a.txt").exists()
        assert (oldPoolParking / "a.txt").read_text(encoding="utf-8") == "old"
        assert not newPool.exists()

    def testSameFsGuardFiresOnStDevMismatch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A mocked st_dev mismatch raises ConfigError before any rename.

        Args:
            tmp_path: pytest-provided temporary directory.
            monkeypatch: pytest monkeypatch fixture.

        Returns:
            None
        """
        pool = tmp_path / "libs"
        pool.mkdir()
        (pool / "a.txt").write_text("old", encoding="utf-8")
        newPool = tmp_path / "newpool"
        newPool.mkdir()
        (newPool / "b.txt").write_text("new", encoding="utf-8")
        oldPoolParking = tmp_path / "oldpool"

        realStat = os.stat

        def fakeStat(path: object, **kwargs: object) -> SimpleNamespace:
            """Return a fake stat result with distinct st_dev per directory.

            Args:
                path: The path being stat-ed.
                **kwargs: Keyword arguments from the caller (ignored).

            Returns:
                A SimpleNamespace whose st_dev differs between the pool and
                the staging directory.
            """
            if Path(str(path)) == newPool:
                return SimpleNamespace(st_dev=999999)
            return SimpleNamespace(st_dev=realStat(path).st_dev)  # type: ignore[arg-type]

        monkeypatch.setattr(pool_staging.os, "stat", fakeStat)

        with pytest.raises(ConfigError):
            pool_staging.swapPools(pool, newPool, oldPoolParking)

        # Nothing was renamed — the live pool is untouched.
        assert (pool / "a.txt").read_text(encoding="utf-8") == "old"
        assert (newPool / "b.txt").exists()
        assert not oldPoolParking.exists()

    def testRollbackRestoresPoolWhenSecondRenameFails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A failing second rename rolls the original pool back inline.

        Args:
            tmp_path: pytest-provided temporary directory.
            monkeypatch: pytest monkeypatch fixture.

        Returns:
            None
        """
        pool = tmp_path / "libs"
        pool.mkdir()
        (pool / "a.txt").write_text("old", encoding="utf-8")
        newPool = tmp_path / "newpool"
        newPool.mkdir()
        (newPool / "b.txt").write_text("new", encoding="utf-8")
        oldPoolParking = tmp_path / "oldpool"

        realRename = Path.rename
        renameCalls = {"count": 0}

        def flakyRename(path: Path, target: Path) -> Path:
            """Fail exactly the second rename of the swap pair.

            Args:
                path: The path being renamed.
                target: The rename destination.

            Returns:
                The real rename result for the first and third calls.

            Raises:
                OSError: On the second call, simulating a mid-swap failure.
            """
            renameCalls["count"] += 1
            if renameCalls["count"] == 2:
                raise OSError(28, "No space left on device")
            return realRename(path, target)

        monkeypatch.setattr(Path, "rename", flakyRename)

        with pytest.raises(OSError):
            pool_staging.swapPools(pool, newPool, oldPoolParking)

        # Inline rollback restored the original pool at its path.
        assert (pool / "a.txt").read_text(encoding="utf-8") == "old"
        assert not oldPoolParking.exists()
        # The staged copy is still at its own path (staging garbage, GC reaps it).
        assert (newPool / "b.txt").read_text(encoding="utf-8") == "new"

    def testRollbackFailureRaisesPoolSwapRollbackFailed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the swap AND the rollback both fail, PoolSwapRollbackFailed is raised.

        The dedicated signal lets the caller preserve the run dir: the old
        pool stays parked, the new pool stays staged, the live pool is
        absent — every remaining copy lives in the staging dir.

        Args:
            tmp_path: pytest-provided temporary directory.
            monkeypatch: pytest monkeypatch fixture.

        Returns:
            None
        """
        pool = tmp_path / "libs"
        pool.mkdir()
        (pool / "a.txt").write_text("old", encoding="utf-8")
        newPool = tmp_path / "newpool"
        newPool.mkdir()
        (newPool / "b.txt").write_text("new", encoding="utf-8")
        oldPoolParking = tmp_path / "oldpool"

        realRename = Path.rename

        def failingSwapAndRollback(path: Path, target: Path) -> Path:
            """Fail exactly the swap rename and its rollback rename.

            Args:
                path: The path being renamed.
                target: The rename destination.

            Returns:
                The real rename result for the first call (pool → parking).

            Raises:
                OSError: For newpool→libs (swap) and oldpool→libs (rollback).
            """
            if path.name in {"newpool", "oldpool"} and target.name == "libs":
                raise OSError(28, "No space left on device")
            return realRename(path, target)

        monkeypatch.setattr(Path, "rename", failingSwapAndRollback)

        with pytest.raises(PoolSwapRollbackFailed) as excInfo:
            pool_staging.swapPools(pool, newPool, oldPoolParking)

        # Recoverable state: old pool parked, new pool staged, live pool absent.
        assert (oldPoolParking / "a.txt").read_text(encoding="utf-8") == "old"
        assert (newPool / "b.txt").read_text(encoding="utf-8") == "new"
        assert not pool.exists()
        # Both errors preserved: the original swap failure as __cause__, the
        # rollback failure as an attribute.
        assert excInfo.value.pool == pool
        assert excInfo.value.oldPoolParking == oldPoolParking
        assert isinstance(excInfo.value.swapError, OSError)
        assert isinstance(excInfo.value.rollbackError, OSError)
        assert isinstance(excInfo.value.__cause__, OSError)


# ============================================================================
# parsePipReport
# ============================================================================


class TestParsePipReport:
    """Tests for the fail-safe pip report parser."""

    def testGoodReport(self, tmp_path: Path) -> None:
        """Resolved name/version pairs extract, canonicalized per PEP 503.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        reportPath = tmp_path / "report.json"
        reportPath.write_text(
            json.dumps(
                {
                    "install": [
                        {"metadata": {"name": "Foo_Bar", "version": "2.1.0"}},
                        {"metadata": {"name": "requests", "version": "2.32.3"}},
                    ]
                }
            ),
            encoding="utf-8",
        )

        parsed = pool_staging.parsePipReport(reportPath)

        assert parsed == {"foo-bar": "2.1.0", "requests": "2.32.3"}

    def testBadJsonReturnsNone(self, tmp_path: Path) -> None:
        """Malformed JSON parses fail-safe to None (treat every spec as outdated).

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        reportPath = tmp_path / "report.json"
        reportPath.write_text("{not json", encoding="utf-8")

        assert pool_staging.parsePipReport(reportPath) is None

    def testMissingFileReturnsNone(self, tmp_path: Path) -> None:
        """A missing report file parses fail-safe to None.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        assert pool_staging.parsePipReport(tmp_path / "missing.json") is None

    @pytest.mark.parametrize(
        "report",
        [
            "[]",  # root is not an object
            "{}",  # no install[] array
            '{"install": "nope"}',  # install[] is not a list
        ],
    )
    def testMalformedStructuresReturnNone(self, tmp_path: Path, report: str) -> None:
        """Unexpected report root structures parse fail-safe to None.

        Args:
            tmp_path: pytest-provided temporary directory.
            report: Raw JSON body of the fake report.

        Returns:
            None
        """
        reportPath = tmp_path / "report.json"
        reportPath.write_text(report, encoding="utf-8")

        assert pool_staging.parsePipReport(reportPath) is None

    def testGarbageEntriesSkippedValidKept(self, tmp_path: Path) -> None:
        """Entries with missing/non-dict metadata are skipped; valid ones kept.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        reportPath = tmp_path / "report.json"
        reportPath.write_text(
            json.dumps(
                {
                    "install": [
                        42,
                        {"no_metadata": True},
                        {"metadata": "nope"},
                        {"metadata": {"name": "no-version"}},
                        {"metadata": {"name": "good-pkg", "version": "3.0"}},
                    ]
                }
            ),
            encoding="utf-8",
        )

        parsed = pool_staging.parsePipReport(reportPath)

        assert parsed == {"good-pkg": "3.0"}

    def testEmptyInstallArrayReturnsEmptyDict(self, tmp_path: Path) -> None:
        """An empty install[] is a valid report resolving nothing.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        reportPath = tmp_path / "report.json"
        reportPath.write_text('{"install": []}', encoding="utf-8")

        assert pool_staging.parsePipReport(reportPath) == {}


# ============================================================================
# Container-controlled leaf files (no-follow guards)
# ============================================================================


class TestContainerControlledLeafFiles:
    """Container-controlled leaf files are never opened through a link/FIFO.

    METADATA, RECORD and the pip report are written by pip (arbitrary PEP
    517 build code), so every host-side open is gated by a NO-FOLLOW
    regular-file check (``is_symlink()`` + ``lstat`` + ``S_ISREG`` — never
    ``Path.is_file()``, which follows links): a planted symlink must not
    cross the container/host trust boundary, a FIFO would block the host on
    open, a device stream could exhaust memory, and non-UTF-8 METADATA must
    hit the documented per-entry skip instead of crashing enumeration.
    """

    def testSymlinkedMetadataSkipsEntrySiblingStillProcessed(self, tmp_path: Path) -> None:
        """A symlinked METADATA is never read; its entry is skipped, siblings process.

        The link targets a host-side file claiming a package name: following
        it would let container-controlled content drive host-side pool
        deletions.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        root = tmp_path / "run"
        poolCopy = root / "newpool"
        poolCopy.mkdir(parents=True)
        outsideFile = root / "outside_metadata.txt"
        outsideFile.write_text("Metadata-Version: 2.1\nName: evil\nVersion: 9.9\n", encoding="utf-8")
        _makeDistInfo(poolCopy, "evil-1.0.dist-info", name="evil", version="1.0", recordPaths=["evil/old.py"])
        metadataPath = poolCopy / "evil-1.0.dist-info" / "METADATA"
        metadataPath.unlink()
        metadataPath.symlink_to(outsideFile)
        _makeDistInfo(poolCopy, "sibling-1.0.dist-info", name="sibling", version="1.0", recordPaths=["sib/old.py"])
        deltaDir = root / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(
            deltaDir, "sibling-2.0.dist-info", name="sibling", version="2.0", recordPaths=["sib/new.py"]
        )

        # Enumeration skips the link-bearing entry entirely.
        assert set(pool_staging.enumerateDistInfos(poolCopy).keys()) == {"sibling"}

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        # The host target was never read or modified; the entry is left alone.
        assert outsideFile.read_text(encoding="utf-8").startswith("Metadata-Version: 2.1")
        assert metadataPath.is_symlink()
        assert (poolCopy / "evil-1.0.dist-info").is_dir()
        assert (poolCopy / "evil" / "old.py").exists()
        # The sibling processed normally.
        assert not (poolCopy / "sibling-1.0.dist-info").exists()
        assert (poolCopy / "sibling-2.0.dist-info").is_dir()
        assert (poolCopy / "sib" / "new.py").exists()

    def testSymlinkedRecordSkipsDeletionSiblingStillProcessed(self, tmp_path: Path) -> None:
        """A symlinked RECORD is never opened; the package's deletion is skipped.

        Mirrors the unreadable-RECORD skip: nothing is deleted for the
        protected name (its staged copy still lands beside it), the link and
        its host-side target survive, and the sibling package processes.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        root = tmp_path / "run"
        poolCopy = root / "newpool"
        poolCopy.mkdir(parents=True)
        outsideRecord = root / "outside_record.csv"
        outsideRecord.write_text("host/secret.txt,sha256=xx,1\n", encoding="utf-8")
        _makeDistInfo(poolCopy, "evil-1.0.dist-info", name="evil", version="1.0", recordPaths=["evil/old.py"])
        recordPath = poolCopy / "evil-1.0.dist-info" / "RECORD"
        recordPath.unlink()
        recordPath.symlink_to(outsideRecord)
        _makeDistInfo(poolCopy, "sibling-1.0.dist-info", name="sibling", version="1.0", recordPaths=["sib/old.py"])
        deltaDir = root / "delta"
        deltaDir.mkdir()
        _makeStagedDistInfo(deltaDir, "evil-2.0.dist-info", name="evil", version="2.0", recordPaths=["evil/new.py"])
        _makeStagedDistInfo(
            deltaDir, "sibling-2.0.dist-info", name="sibling", version="2.0", recordPaths=["sib/new.py"]
        )

        pool_staging.mergeStagedDelta(poolCopy, deltaDir)

        # The link target was never opened for deletion guidance.
        assert outsideRecord.read_text(encoding="utf-8").startswith("host/secret.txt")
        assert recordPath.is_symlink()
        assert (poolCopy / "evil-1.0.dist-info").is_dir()
        assert (poolCopy / "evil" / "old.py").exists()
        # The staged evil copy still lands beside the skipped old install...
        assert (poolCopy / "evil-2.0.dist-info").is_dir()
        # ...and the sibling processed normally.
        assert not (poolCopy / "sibling-1.0.dist-info").exists()
        assert (poolCopy / "sibling-2.0.dist-info").is_dir()

    def testSymlinkedReportReturnsNoneTargetUntouched(self, tmp_path: Path) -> None:
        """A symlinked pip report is never opened; parsing fails safe to None.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        target = tmp_path / "host_secret.json"
        target.write_text('{"install": [{"metadata": {"name": "evil", "version": "9.9"}}]}', encoding="utf-8")
        reportPath = tmp_path / "report.json"
        reportPath.symlink_to(target)

        assert pool_staging.parsePipReport(reportPath) is None
        assert target.read_text(encoding="utf-8").startswith('{"install"')

    def testFifoRecordRejectedWithoutOpening(self, tmp_path: Path) -> None:
        """A FIFO RECORD is rejected by the no-follow guard BEFORE any open.

        An open() on a FIFO blocks the host until a writer appears; the
        lstat guard must reject it first, so this test never blocks.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        distInfoDir = tmp_path / "pkg-1.0.dist-info"
        distInfoDir.mkdir()
        os.mkfifo(str(distInfoDir / "RECORD"))

        with pytest.raises(OSError):
            pool_staging.readRecordPaths(distInfoDir)

    def testBinaryMetadataDecodeFailureSkipsEntryNotCrash(self, tmp_path: Path) -> None:
        """Non-UTF-8 METADATA hits the per-entry skip; enumeration must not crash.

        Args:
            tmp_path: pytest-provided temporary directory.

        Returns:
            None
        """
        poolDir = tmp_path / "libs"
        poolDir.mkdir()
        binaryDir = poolDir / "bin-1.0.dist-info"
        binaryDir.mkdir()
        (binaryDir / "METADATA").write_bytes(b"\xff\xfe\x00\x01binary garbage")
        (binaryDir / "RECORD").write_text("bin-1.0.dist-info/RECORD,,\n", encoding="utf-8")
        _makeDistInfo(poolDir, "sibling-1.0.dist-info", name="sibling", version="1.0", recordPaths=["sib/mod.py"])

        inventory = pool_staging.enumerateDistInfos(poolDir)

        assert set(inventory.keys()) == {"sibling"}
