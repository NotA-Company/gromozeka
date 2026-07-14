"""Test suite for ``scripts/check_docs.py``, the local markdown-link checker.

Covers the link-extraction + resolution logic against throwaway temp trees
(``tmp_path``): broken-link detection, external-link skipping, anchor/line
suffix stripping, archive skipping, plus one end-to-end run against the real
repository.

The real-repo test is a regression guard: it fails if any future change
introduces a broken local link. The directories ``docs/archive`` (frozen
historical snapshot), ``docs/templates`` (illustrative placeholder paths),
and ``lib/ext_modules`` (vendored nested repo) are excluded from scanning via
``_EXCLUDED_PATH_PREFIXES`` in ``check_docs.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.check_docs import BrokenLink, CheckResult, checkDocs  # noqa: E402


def _write(path: Path, content: str) -> Path:
    """Write ``content`` to ``path``, creating parent dirs, and return it.

    Args:
        path: File path to write (parents created as needed).
        content: Text content to write.

    Returns:
        The ``path`` argument, for chaining.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_detectsBrokenLink(tmp_path: Path) -> None:
    """A local link to a non-existent file is reported and fails the check."""
    _write(tmp_path / "index.md", "see [missing](nope.md) for details.\n")
    result: CheckResult = checkDocs(tmp_path)
    assert result.exitCode == 1
    assert len(result.brokenLinks) == 1
    finding: BrokenLink = result.brokenLinks[0]
    assert finding.target == "nope.md"
    assert finding.lineNo == 1
    assert finding.text == "missing"


def test_ignoresExternalLinks(tmp_path: Path) -> None:
    """http/https/mailto/ftp links are skipped, not counted as local links."""
    _write(
        tmp_path / "index.md",
        "[web](https://example.com) [mail](mailto:a@b.com) " "[ftp](ftp://host/x) [site](http://example.org)\n",
    )
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []
    # External links are skipped before the resolved-link counter increments.
    assert result.linksChecked == 0


def test_ignoresAnchorOnlyLink(tmp_path: Path) -> None:
    """A same-page ``#section`` anchor is skipped (out of scope for v1)."""
    _write(tmp_path / "index.md", "see [intro](#intro) below.\n")
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []


def test_stripsAnchor(tmp_path: Path) -> None:
    """A ``./other.md#section`` link resolves once the anchor is stripped."""
    _write(tmp_path / "other.md", "# Other\n")
    _write(tmp_path / "index.md", "[go](./other.md#section)\n")
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []


def test_stripsQuery(tmp_path: Path) -> None:
    """A ``./other.md?raw=1`` link resolves once the query is stripped."""
    _write(tmp_path / "other.md", "# Other\n")
    _write(tmp_path / "index.md", "[go](./other.md?raw=1)\n")
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []


def test_stripsLineNumberSuffix(tmp_path: Path) -> None:
    """The repo's file:line / file:line-range convention resolves to the file.

    Links like ``foo.py:215`` and ``foo.py:10-20`` are file:line references,
    not separate paths; the line suffix must be stripped before existence
    checking. This is the dominant link style across the repo's docs.
    """
    _write(tmp_path / "foo.py", "x = 1\n")
    _write(
        tmp_path / "index.md",
        "[a](./foo.py:215) [b](./foo.py:10-20) [c](./foo.py:1,2,3)\n",
    )
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []


def test_imageLinksAreChecked(tmp_path: Path) -> None:
    """Broken image references (``![alt](img.png)``) are also reported."""
    _write(tmp_path / "index.md", "![badge](badges/x.png)\n")
    result = checkDocs(tmp_path)
    assert result.exitCode == 1
    assert len(result.brokenLinks) == 1
    assert result.brokenLinks[0].target == "badges/x.png"


def test_linksInCodeBlocksSkipped(tmp_path: Path) -> None:
    """Links inside fenced code blocks are examples, not real references."""
    _write(
        tmp_path / "index.md",
        "Example:\n\n```\n[cmd](nonexistent.md)\n```\n\ntext\n",
    )
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []


def test_linksInInlineCodeSkipped(tmp_path: Path) -> None:
    """Links inside inline code spans are examples, not real references."""
    _write(tmp_path / "index.md", "run `[cmd](nonexistent.md)` now\n")
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []


def test_parentTraversal(tmp_path: Path) -> None:
    """``../`` traversal resolves relative to the markdown file's directory."""
    _write(tmp_path / "pkg" / "sub" / "doc.md", "[up](../../sibling.md)\n")
    _write(tmp_path / "sibling.md", "# Sibling\n")
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []


def test_rootRelativeLeadingSlash(tmp_path: Path) -> None:
    """A leading ``/`` is treated as repo-root-relative."""
    _write(tmp_path / "AGENTS.md", "# Rules\n")
    _write(tmp_path / "docs" / "guide.md", "[rules](/AGENTS.md)\n")
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []


def test_skipsArchive(tmp_path: Path) -> None:
    """``docs/archive/`` is a frozen historical tree and is not checked."""
    _write(tmp_path / "docs" / "archive" / "stale.md", "[dead](gone.md)\n")
    _write(tmp_path / "index.md", "[ok](./docs)\n")  # docs/ exists -> not broken
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []


def test_skipsTemplates(tmp_path: Path) -> None:
    """``docs/templates/`` carries illustrative placeholder paths and is not checked."""
    _write(tmp_path / "docs" / "templates" / "stale.md", "[dead](gone.md)\n")
    _write(tmp_path / "index.md", "[ok](./docs)\n")  # docs/ exists -> not broken
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []


def test_skipsExtModules(tmp_path: Path) -> None:
    """``lib/ext_modules/`` is a vendored nested repo and is not checked."""
    _write(tmp_path / "lib" / "ext_modules" / "stale.md", "[dead](gone.md)\n")
    _write(tmp_path / "index.md", "[ok](./lib)\n")  # lib/ exists -> not broken
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []


def test_skipsExcludedDirs(tmp_path: Path) -> None:
    """Venv / cache / .opencode dirs are never descended into."""
    _write(tmp_path / ".venv" / "pkg" / "readme.md", "[dead](gone.md)\n")
    _write(tmp_path / "__pycache__" / "x.md", "[dead](gone.md)\n")
    _write(tmp_path / ".opencode" / "notes.md", "[dead](gone.md)\n")
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []


def test_referenceDefinitionBroken(tmp_path: Path) -> None:
    """A reference-style definition ``[id]: target`` to a missing file is reported.

    The reference-definition branch (its own regex and resolve/existence path)
    has no prior coverage. A broken definition target is drift worth reporting.
    """
    _write(tmp_path / "index.md", "[missing]: missing.md\n")
    result = checkDocs(tmp_path)
    assert result.exitCode == 1
    assert len(result.brokenLinks) == 1
    finding = result.brokenLinks[0]
    assert finding.target == "missing.md"
    assert finding.text == "missing"


def test_angleFormLocalLinkResolves(tmp_path: Path) -> None:
    """The ``[x](<other.md>)`` angle form to an existing file is not broken.

    The ``<target>`` angle form is a valid CommonMark link shape and was
    previously untested.
    """
    _write(tmp_path / "other.md", "# Other\n")
    _write(tmp_path / "index.md", "[go](<other.md>)\n")
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []


def test_angleFormExternalLinkNotBroken(tmp_path: Path) -> None:
    """An angle-wrapped external URL ``[x](<https://example.com>)`` is external.

    Regression guard: ``_isExternal`` must unwrap ``<>`` before the scheme
    check, otherwise the URL is mis-resolved as a local path and reported
    broken. External links must be skipped, not counted as broken.
    """
    _write(tmp_path / "index.md", "[site](<https://example.com>)\n")
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []
    assert result.linksChecked == 0


def test_linksInTildeFenceSkipped(tmp_path: Path) -> None:
    """Links inside ``~~~`` tilde fences are examples, not real references.

    ``_FENCE_RE`` recognises both backtick and tilde fences; the tilde branch
    had no test coverage even though the repo uses it.
    """
    _write(
        tmp_path / "index.md",
        "Example:\n\n~~~\n[cmd](nonexistent.md)\n~~~\n\ntext\n",
    )
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []


def test_unreadableFileDoesNotAbortRun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An ``OSError`` while reading one file is contained, not fatal.

    Monkeypatches :meth:`pathlib.Path.read_text` to raise ``OSError`` so the
    unreadable-file branch reports 0 resolved links for that file and the
    overall run still completes.
    """
    _write(tmp_path / "index.md", "[ok](sibling.md)\n")
    _write(tmp_path / "sibling.md", "# Sibling\n")

    originalReadText = Path.read_text

    def raisingReadText(self: Path, *args: object, **kwargs: object) -> str:
        """Raise OSError for the index file, defer to the real read otherwise.

        Args:
            self: Path instance whose text is being read.

        Raises:
            OSError: Always, for the ``index.md`` file.

        Returns:
            Never returns normally (always raises for the targeted file); for
            every other path delegates to the original implementation.
        """
        if self.name == "index.md":
            raise OSError("simulated unreadable file")
        return originalReadText(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", raisingReadText)
    result = checkDocs(tmp_path)
    # The unreadable file contributes 0 resolved links but the run finishes.
    assert result.linksChecked == 0
    # The unreadable file is reported as a single broken finding, not a crash.
    assert any("<unreadable:" in b.target for b in result.brokenLinks)


def test_singleQuoteTitleLinkResolves(tmp_path: Path) -> None:
    """A link with a single-quoted title ``[x](y 't')`` parses and resolves.

    CommonMark allows both ``"title"`` and ``'title'``. Previously only the
    double-quoted form matched, so a single-quoted title caused the whole link
    to fail to match (silently skipped).
    """
    _write(tmp_path / "other.md", "# Other\n")
    _write(tmp_path / "index.md", "[go](other.md 'title') [go2](other.md \"title\")\n")
    result = checkDocs(tmp_path)
    assert result.exitCode == 0
    assert result.brokenLinks == []
    assert result.linksChecked == 2


def test_noBrokenLinks_inRealRepo() -> None:
    """The repo's markdown links must all resolve.

    Regression guard: runs the checker end-to-end against the repo root and
    fails if a future change introduces a broken local link. Prints the first
    findings on failure so the drift is visible in the test log.
    """
    repoRoot: Path = Path(__file__).resolve().parent.parent.parent
    result = checkDocs(repoRoot)
    if result.brokenLinks:
        sample = "\n".join(b.format(repoRoot) for b in result.brokenLinks[:30])
        print(f"Known broken links ({len(result.brokenLinks)} total):\n{sample}")
    assert result.exitCode == 0, f"{len(result.brokenLinks)} broken doc links found"
