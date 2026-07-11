#!/usr/bin/env ./venv/bin/python3
"""Check that local markdown links resolve to files on disk.

Documentation drifts: directories get renamed (``docs/reports/`` -> ``docs/archive/reports/``),
source trees are refactored (``lib/markdown/test/`` removed), files are split.
Each of those silently turns previously-valid ``[text](path)`` links into 404s.
This script catches that class of drift mechanically -- no network, no anchor
validation, just "does the referenced local file exist?".

Scope of this first version:

  * Scan every ``*.md`` under the repo root (root ``*.md``, ``docs/**/*.md``,
    ``lib/**/README.md``, ``internal/**/README.md``, ``AGENTS.md``, etc.).
  * Extract inline links ``[text](target)`` and images ``![alt](target)``,
    plus reference-style definitions ``[id]: target``.
  * Ignore external links (``http://``, ``https://``, ``mailto:``, ``ftp://``)
    and same-page anchors (``#section``).
  * Resolve each remaining target relative to the markdown file's directory,
    stripping any ``#anchor`` suffix, ``?query``, and trailing
    ``:lineNumber`` / ``:start-end`` suffix (this repo's file:line reference
    convention, e.g. ``internal/foo.py:215``). A leading ``/`` is treated as
    repo-root-relative (matches the repo's doc-linking convention).
  * A link is **broken** when the resolved path does not exist. Report
    ``file:line`` for each and exit non-zero so ``make check-docs`` fails CI-style.

Deliberately out of scope: HTTP checking of external links, anchor-target
validation within a file, and code-example compilation.

Usage::

    ./venv/bin/python3 scripts/check_docs.py
    ./venv/bin/python3 scripts/check_docs.py --root /path/to/repo

Args:
    --root: Repository root to scan. Defaults to the parent of ``scripts/``
        (i.e. the repo root when run in place).

Returns:
    Exit code ``0`` when every local link resolves, ``1`` when at least one
    broken link is found.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Directory names that are never descended into during the walk. Mix of VCS,
# virtualenv, cache, and tooling directories that either contain generated
# content or are explicitly frozen historical snapshots.
_EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        "htmlcov",
        "__pycache__",
        "node_modules",
        ".tox",
        "build",
        "dist",
        # .opencode/ holds agent working state, not authored docs.
        ".opencode",
    }
)

# Path-precise exclusions given as ``(rootSegment, childSegment)`` pairs --
# directories at the top of the repo whose content is intentionally not
# validated because it is either a frozen historical snapshot
# (``docs/archive``), template placeholder paths (``docs/templates``), or a
# vendored nested git repo (``lib/ext_modules``). Unlike the name-based
# ``_EXCLUDED_DIR_NAMES`` above, these are matched on the directory's position
# in the tree so a common leaf name like ``templates`` is only excluded at the
# intended root.
_EXCLUDED_PATH_PREFIXES: frozenset[tuple[str, str]] = frozenset(
    {("docs", "archive"), ("docs", "templates"), ("lib", "ext_modules")}
)

# External link schemes that are skipped (network checking is out of scope).
_EXTERNAL_SCHEMES: tuple[str, ...] = ("http://", "https://", "mailto:", "ftp://")

# Inline link / image link. Supports one level of nested brackets inside the
# text (``[![alt](img)](page)``), the ``<target with spaces>`` angle form, and
# an optional title suffix (``"title"`` or ``'title'`` per CommonMark). The
# target stops at whitespace, a quote, a backslash, or the closing paren --
# this keeps ``#anchor`` and ``?query`` attached to the target so they can be
# stripped later.
_INLINE_LINK_RE: re.Pattern[str] = re.compile(
    r"!\[(?P<text>(?:[^\[\]]|\[[^\]]*\])*?)\]\((?P<target><[^>]+>|[^)\s\"'\\]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\)"
    r"|\[(?P<text2>(?:[^\[\]]|\[[^\]]*\])*?)\]\((?P<target2><[^>]+>|[^)\s\"'\\]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\)"
)

# Reference-style link definition: ``[id]: target`` at start of line.
_REF_DEF_RE: re.Pattern[str] = re.compile(r"^\s*\[(?P<id>[^\]]+)\]:\s*(?P<target><[^>]+>|\S+)")

# Inline code span, stripped from a line before link extraction so that links
# shown as code examples (`` `[cmd](foo)` ``) are not checked.
_INLINE_CODE_RE: re.Pattern[str] = re.compile(r"`[^`]*`")

# ATX-style fenced code block opening (``` or ~~~), allowing up to three
# leading spaces per CommonMark. Seeing such a line toggles in/out of a block.
_FENCE_RE: re.Pattern[str] = re.compile(r"^[ \t]{0,3}(```|~~~)")


@dataclass
class BrokenLink:
    """A single local link whose target does not exist on disk.

    Attributes:
        mdFile: Absolute path of the markdown file containing the link.
        lineNo: 1-based line number of the link within ``mdFile``.
        text: Link text (the part inside ``[...]``); empty for image alts
            that resolved to nothing.
        target: Raw target string as written in the markdown (pre-resolution;
            may still carry a ``#anchor`` or ``?query``).
    """

    mdFile: Path
    lineNo: int
    text: str
    target: str

    def format(self, root: Path) -> str:
        """Format this finding as a human-readable ``file:line: ...`` line.

        Args:
            root: Repository root, used to render ``mdFile`` as a relative path.

        Returns:
            A single report line such as
            ``docs/foo.md:12: broken link "[bar](missing.md)" -- target not found``.
        """
        try:
            relFile: str = str(self.mdFile.relative_to(root))
        except ValueError:
            relFile = str(self.mdFile)
        return f'{relFile}:{self.lineNo}: broken link "[{self.text}]({self.target})" -- target not found'


@dataclass
class CheckResult:
    """Aggregate outcome of a documentation-link check run.

    Attributes:
        brokenLinks: Ordered list of broken-link findings.
        filesChecked: Number of markdown files scanned.
        linksChecked: Number of local links resolved (excludes skipped
            external / anchor-only links).
    """

    brokenLinks: list[BrokenLink] = field(default_factory=list)
    filesChecked: int = 0
    linksChecked: int = 0

    @property
    def exitCode(self) -> int:
        """Process exit code: ``1`` if any broken link was found, else ``0``."""
        return 1 if self.brokenLinks else 0


def _detectRepoRoot() -> Path:
    """Return the repository root inferred from this script's location.

    The script lives at ``<root>/scripts/check_docs.py``, so the repo root is
    the parent of the ``scripts/`` directory.

    Returns:
        Absolute path of the inferred repository root.
    """
    return Path(__file__).resolve().parent.parent


def _isExcludedDir(relDir: Path) -> bool:
    """Decide whether a directory (given relative to the repo root) is pruned.

    A directory is pruned when its final name is in ``_EXCLUDED_DIR_NAMES``
    (VCS / venv / caches / ``.opencode``) or when its ``(root, child)`` prefix
    is in ``_EXCLUDED_PATH_PREFIXES`` -- the latter covers
    ``docs/archive`` (a frozen historical snapshot tree whose intentionally-stale
    links are documented as not maintained, see ``docs/archive/README.md``),
    ``docs/templates`` (PR/task templates carrying intentional placeholder
    paths that are not real links), and ``lib/ext_modules`` (a vendored nested
    git repo whose docs should not be validated against the main repo tree).

    Args:
        relDir: Directory path relative to the repo root.

    Returns:
        ``True`` when the walk should not descend into ``relDir``.
    """
    parts: tuple[str, ...] = relDir.parts
    if parts and parts[-1] in _EXCLUDED_DIR_NAMES:
        return True
    if len(parts) >= 2 and (parts[0], parts[1]) in _EXCLUDED_PATH_PREFIXES:
        return True
    return False


def _findMarkdownFiles(root: Path) -> list[Path]:
    """Walk ``root`` and return the sorted list of markdown files to check.

    Excluded directories are pruned in-place during the ``os.walk`` descent so
    the walk never recurses into them.

    Args:
        root: Repository root to walk.

    Returns:
        Sorted list of absolute ``*.md`` file paths.
    """
    mdFiles: list[Path] = []
    for dirPathStr, dirNames, fileNames in os.walk(root):
        dirPath: Path = Path(dirPathStr)
        kept: list[str] = []
        for name in dirNames:
            try:
                relDir: Path = dirPath.joinpath(name).relative_to(root)
            except ValueError:
                relDir = dirPath.joinpath(name)
            if _isExcludedDir(relDir):
                continue
            kept.append(name)
        dirNames[:] = kept
        for fileName in fileNames:
            if fileName.endswith(".md"):
                mdFiles.append(dirPath.joinpath(fileName))
    return sorted(mdFiles)


def _isExternal(target: str) -> bool:
    """Return ``True`` when ``target`` is an external URL we should not check.

    The angle-wrapped form ``<https://...>`` (a valid CommonMark link target)
    is unwrapped before the scheme check so it is recognized as external.
    Without this, ``_resolveTarget`` would strip the angle brackets later and
    treat the URL as a local path, producing a false-positive broken link.

    Args:
        target: Raw link target, possibly angle-wrapped.

    Returns:
        ``True`` for ``http://``, ``https://``, ``mailto:``, ``ftp://`` links.
    """
    clean: str = target
    if clean.startswith("<") and clean.endswith(">"):
        clean = clean[1:-1]
    low: str = clean.lower()
    return any(low.startswith(scheme) for scheme in _EXTERNAL_SCHEMES)


def _stripInlineCode(line: str) -> str:
    """Remove inline code spans from ``line`` before link extraction.

    Links that appear inside inline code (`` `[x](foo)` ``) are documentation
    examples, not real references, so they must not be checked. This is a
    best-effort, per-line approximation -- fenced blocks are handled separately
    by :data:`_FENCE_RE`.

    Args:
        line: A single source line.

    Returns:
        ``line`` with `` `...` `` spans removed.
    """
    return _INLINE_CODE_RE.sub("", line)


def _extractLinks(line: str) -> list[tuple[str, str]]:
    """Extract ``(text, target)`` pairs for inline links/images on ``line``.

    Handles both image links ``![alt](target)`` and plain links
    ``[text](target)``, including one level of nested brackets in the text and
    the ``<target>`` angle form.

    Args:
        line: A single source line (already stripped of inline code).

    Returns:
        List of ``(text, target)`` tuples in line order.
    """
    links: list[tuple[str, str]] = []
    for match in _INLINE_LINK_RE.finditer(line):
        text: str = match.group("text") or match.group("text2") or ""
        targetRaw: str = match.group("target") or match.group("target2") or ""
        if targetRaw:
            links.append((text, targetRaw))
    return links


def _resolveTarget(mdFile: Path, target: str, root: Path) -> Optional[Path]:
    """Resolve a link target to an absolute path, or ``None`` to skip it.

    Skips (returns ``None``): external URLs, same-page anchors (``#sec``),
    and targets that are empty after stripping the anchor/query.

    Resolution rules:

      * A leading ``/`` is treated as repo-root-relative (the repo's
        doc-linking convention), not filesystem-root-relative.
      * Otherwise the target is resolved relative to ``mdFile``'s directory.
      * ``#anchor``, ``?query``, and a trailing ``:lineNumber`` /
        ``:start-end`` suffix (this repo's file:line reference convention,
        e.g. ``internal/foo.py:215``) are stripped before resolution.

    Args:
        mdFile: The markdown file containing the link.
        target: Raw link target.
        root: Repository root, used for leading-``/`` targets.

    Returns:
        Absolute resolved path to check for existence, or ``None`` when the
        target should be skipped.
    """
    clean: str = target
    if clean.startswith("<") and clean.endswith(">"):
        clean = clean[1:-1]
    clean = clean.split("#", 1)[0]
    clean = clean.split("?", 1)[0]
    # Strip a trailing file:line / file:line-range suffix used throughout the
    # repo's docs (e.g. ``models.py:215``, ``manager.py:249-318``). The suffix
    # is an anchor into the file, not part of the path.
    clean = re.sub(r":[0-9]+(?:[-,][0-9]+)*$", "", clean)
    if not clean:
        return None
    if clean.startswith("/"):
        return (root / clean.lstrip("/")).resolve()
    return (mdFile.parent / clean).resolve()


def _checkFile(mdFile: Path, root: Path) -> tuple[list[BrokenLink], int]:
    """Check every local link in one markdown file.

    Walks the file line by line, toggling fenced-code-block state, stripping
    inline code, then extracting inline links and reference definitions. Each
    local target is resolved and existence-checked.

    Args:
        mdFile: Absolute path of the markdown file to check.
        root: Repository root, used for leading-``/`` target resolution.

    Returns:
        A ``(brokenLinks, linksChecked)`` tuple where ``linksChecked`` is the
        number of local links actually resolved (skipped external/anchor links
        are not counted).
    """
    broken: list[BrokenLink] = []
    linksChecked: int = 0
    try:
        text: str = mdFile.read_text(encoding="utf-8")
    except OSError as exc:
        # Treat an unreadable file as a single broken finding rather than
        # aborting the whole run; one bad file should not hide the rest.
        broken.append(BrokenLink(mdFile=mdFile, lineNo=0, text="", target=f"<unreadable: {exc}>"))
        return broken, 0

    inCode: bool = False
    for lineNo, rawLine in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(rawLine):
            inCode = not inCode
            continue
        if inCode:
            continue

        strippedLine: str = _stripInlineCode(rawLine)

        for linkText, target in _extractLinks(strippedLine):
            if _isExternal(target):
                continue
            resolved: Optional[Path] = _resolveTarget(mdFile, target, root)
            if resolved is None:
                continue
            linksChecked += 1
            if not resolved.exists():
                broken.append(BrokenLink(mdFile=mdFile, lineNo=lineNo, text=linkText, target=target))

        # Reference-style definitions: check the target too. Usages
        # (``[text][id]``) are not resolved here, but a broken definition target
        # is still drift worth reporting.
        refMatch: Optional[re.Match[str]] = _REF_DEF_RE.match(strippedLine)
        if refMatch is not None:
            refTarget: str = refMatch.group("target")
            if _isExternal(refTarget):
                continue
            resolvedRef: Optional[Path] = _resolveTarget(mdFile, refTarget, root)
            if resolvedRef is None:
                continue
            linksChecked += 1
            if not resolvedRef.exists():
                broken.append(
                    BrokenLink(
                        mdFile=mdFile,
                        lineNo=lineNo,
                        text=refMatch.group("id"),
                        target=refTarget,
                    )
                )

    return broken, linksChecked


def checkDocs(root: Path) -> CheckResult:
    """Check every markdown file under ``root`` for broken local links.

    Args:
        root: Repository root to scan.

    Returns:
        A :class:`CheckResult` carrying the broken-link list, file count, and
        resolved-link count.
    """
    result: CheckResult = CheckResult()
    for mdFile in _findMarkdownFiles(root):
        result.filesChecked += 1
        broken, linksChecked = _checkFile(mdFile, root)
        result.linksChecked += linksChecked
        result.brokenLinks.extend(broken)
    return result


def _printReport(result: CheckResult, root: Path) -> None:
    """Print the broken-link findings and a one-line summary.

    Args:
        result: The check result to report.
        root: Repository root, used for rendering relative file paths.

    Returns:
        None
    """
    for finding in result.brokenLinks:
        print(finding.format(root))
    print(
        f"Checked {result.filesChecked} markdown files, {result.linksChecked} links; "
        f"{len(result.brokenLinks)} broken."
    )


def main() -> int:
    """Entry point: parse CLI args, run the check, print the report.

    Returns:
        ``0`` when no broken links were found, ``1`` otherwise.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=(
            "Check that local markdown links resolve to files on disk. Scans "
            "every *.md under the repo root, resolves [text](target) links "
            "relative to each file, and reports any target that does not exist."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root to scan (default: parent of scripts/, i.e. the repo root).",
    )
    args: argparse.Namespace = parser.parse_args()

    root: Path = args.root if args.root is not None else _detectRepoRoot()
    if not root.is_dir():
        print(f"error: --root is not a directory: {root}", file=sys.stderr)
        return 1

    result: CheckResult = checkDocs(root)
    _printReport(result, root)
    return result.exitCode


if __name__ == "__main__":
    sys.exit(main())
