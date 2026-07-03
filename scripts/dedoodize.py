#!/usr/bin/env python3
"""Strip the stylistic marker "dood" from non-user-facing Python source.

Walks every ``.py`` file in the repository (excluding ``./venv``,
``__pycache__``, ``.git`` and this script itself) and removes the trailing
stylistic exclamation "dood" from:

  * log messages        — ``logger.<level>(...)`` / ``self.logger.<level>(...)``
  * raised errors       — ``raise <Error>(...)``
  * docstrings / multi-line strings (any triple-quoted block)
  * comments            — full-line and trailing ``# ...``
  * assert failure messages — ``assert cond, "msg"`` (the *message* only)

Statements that span several physical lines (an open parenthesis whose keyword
sits on an earlier line) are handled by tracking bracket depth and the active
statement category across lines, so a ``dood`` on a continuation line of a
``raise``/``logger``/``assert`` is still stripped.

It deliberately KEEPS "dood" inside user-facing strings: ``print()`` console
output, ``messageText=`` / ``helpMessage=`` bot replies, argparse
``description=`` / ``help=``, ``__author__`` metadata, and any other plain
string literal (assignments, return values, call arguments, assert
*comparands* such as mock LLM response text used as test fixtures).

Usage::

    ./venv/bin/python3 scripts/dedoodize.py            # apply in place
    ./venv/bin/python3 scripts/dedoodize.py --dry-run  # preview only
    ./venv/bin/python3 scripts/dedoodize.py -v         # per-file detail

Args:
    --dry-run: Report what would change without writing files.
    -v, --verbose: Print every modified file with its change count.

Returns:
    Exit code 0. Files are rewritten in place when not in dry-run mode.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Optional

# Locates a bare "dood" token (word boundaries) for *classification* only.
_DOOD_WORD: re.Pattern[str] = re.compile(r"\bdood\b", re.IGNORECASE)

# The *removal* pattern: dood plus its preceding separator (spaces/tabs/commas)
# and its own trailing punctuation (. ! ?). Leading separator excludes "." so we
# never consume a period that belongs to the preceding sentence; trailing excludes
# "," so a comma after dood (mid-sentence, not present in this repo) is untouched.
_DOOD_PATTERN: re.Pattern[str] = re.compile(r"[ \t,]*\bdood\b[.!?]*", re.IGNORECASE)

# A line whose entire payload is just the dood token (a multi-line docstring
# continuation line such as "    dood!"). These are dropped entirely and the
# dangling comma stripped from the previous line to leave a clean docstring.
_STANDALONE_DOOD: re.Pattern[str] = re.compile(r"[ \t]*dood[ \t.!?]*", re.IGNORECASE)

# Code-prefix substrings that mark a line as user-facing -> always keep dood.
_SKIP_KEYWORDS: tuple[str, ...] = (
    "print(",
    "messageText",
    "helpMessage",
    "description=",
    "help=",
    "__author__",
)

# Directory names to skip while walking the tree.
_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {"venv", "__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
)


def scanLine(line: str, inTriple: Optional[str]) -> tuple[list[str], Optional[str]]:
    """Classify every character of ``line`` and track triple-quote state.

    Args:
        line: One source line without its trailing newline.
        inTriple: The active triple-quote delimiter (three double or three single
            quote characters) carried from the previous line, or ``None`` when
            not inside a triple string.

    Returns:
        A ``(classes, outTriple)`` pair. ``classes`` has one entry per character
        of ``line``, each one of ``"code"``, ``"triple"``, ``"string"``,
        ``"comment"``. ``outTriple`` is the delimiter carried to the next line
        (``None`` once the triple string has closed).
    """
    classes: list[str] = []
    i = 0
    n = len(line)
    mode = "triple" if inTriple else "code"
    delim = inTriple
    quote = ""
    while i < n:
        ch = line[i]
        if mode == "triple":
            # delim is guaranteed non-None whenever mode == "triple".
            if delim is not None and line.startswith(delim, i):
                classes.extend(["triple", "triple", "triple"])
                i += 3
                mode = "code"
                delim = None
            else:
                classes.append("triple")
                i += 1
        elif mode == "string":
            if ch == "\\" and i + 1 < n:
                classes.extend(["string", "string"])
                i += 2
            elif ch == quote:
                classes.append("string")
                i += 1
                mode = "code"
            else:
                classes.append("string")
                i += 1
        else:  # code
            if ch == "#":
                classes.extend(["comment"] * (n - i))
                i = n
            elif line.startswith('"""', i) or line.startswith("'''", i):
                delim = line[i : i + 3]
                classes.extend(["triple", "triple", "triple"])
                i += 3
                mode = "triple"
            elif ch in ('"', "'"):
                quote = ch
                classes.append("string")
                i += 1
                mode = "string"
            else:
                classes.append("code")
                i += 1
    outTriple = delim if mode == "triple" else None
    return classes, outTriple


def _codePrefix(line: str, classes: list[str]) -> str:
    """Return the leading run of ``code``-classified characters of ``line``.

    The statement keyword / call name always lives in this prefix (it ends at
    the first string, comment or triple-quote), so keyword checks against it are
    immune to the same words appearing inside a message string.

    Args:
        line: The source line.
        classes: Per-character classification produced by :func:`scanLine`.

    Returns:
        The prefix substring composed entirely of ``code`` characters.
    """
    end = 0
    while end < len(classes) and classes[end] == "code":
        end += 1
    return line[:end]


def _isLogger(prefix: str) -> bool:
    """Whether ``prefix`` denotes a logger call (``logger.x(`` / ``self.logger.x(``)."""
    return "logger." in prefix


def _isSkip(prefix: str) -> bool:
    """Whether ``prefix`` marks a user-facing string that must keep dood."""
    return any(keyword in prefix for keyword in _SKIP_KEYWORDS)


def _detectKeyword(line: str, classes: list[str]) -> Optional[str]:
    """Identify the statement category of a line that starts a new statement.

    Inspects only the leading code-classified prefix so keywords appearing inside
    a message string never cause a misclassification.

    Args:
        line: The source line.
        classes: Per-character classification from :func:`scanLine`.

    Returns:
        One of ``"skip"``, ``"logger"``, ``"raise"``, ``"assert"`` or ``None``.
    """
    prefix = _codePrefix(line, classes)
    if _isSkip(prefix):
        return "skip"
    if _isLogger(prefix):
        return "logger"
    if prefix.strip().startswith("raise "):
        return "raise"
    if prefix.strip().startswith("assert"):
        return "assert"
    return None


def _scanCodeDepth(line: str, classes: list[str], startDepth: int, baseDepth: int) -> tuple[int, int]:
    """Walk code-level brackets and locate the first base-depth comma.

    Brackets inside strings, comments or triple-quotes are ignored. A comma is
    only "base-level" when it sits at ``baseDepth`` (used to spot the separator
    between an assert condition and its failure message).

    Args:
        line: Source line.
        classes: Per-character classification from :func:`scanLine`.
        startDepth: Bracket depth carried into the line.
        baseDepth: Depth at which a comma counts as a separator.

    Returns:
        A ``(finalDepth, baseCommaIndex)`` pair. ``baseCommaIndex`` is the index
        of the first code comma seen at ``baseDepth``, or ``-1`` when none.
    """
    depth = startDepth
    baseComma = -1
    for idx, ch in enumerate(line):
        if classes[idx] != "code":
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == baseDepth and baseComma == -1:
            baseComma = idx
    return depth, baseComma


def evaluateLine(
    line: str,
    classes: list[str],
    effectiveCategory: Optional[str],
    assertInMessage: bool,
    baseCommaIndex: int,
) -> str:
    """Decide how to treat ``line`` given its statement category.

    Args:
        line: The source line.
        classes: Per-character classification from :func:`scanLine`.
        effectiveCategory: Statement category active for this line (``None`` for a
            plain literal / non-keyword line).
        assertInMessage: Whether the active assert has already crossed its
            condition/message separator comma on a previous line.
        baseCommaIndex: Index of the first base-level code comma on this line
            (``-1`` if none); used to place a same-line dood relative to the
            assert separator.

    Returns:
        One of ``"keep"``, ``"remove"`` (strip the dood token in place) or
        ``"remove-standalone"`` (the line is only the dood token: drop it and
        trim the dangling comma from the previous line).
    """
    matches = list(_DOOD_WORD.finditer(line))
    if not matches:
        return "keep"
    regions = {classes[m.start()] for m in matches}

    # Inside a triple-quoted block (docstring or multi-line string).
    if "triple" in regions:
        if effectiveCategory == "skip":
            return "keep"
        if _STANDALONE_DOOD.fullmatch(line):
            return "remove-standalone"
        return "remove"

    # Inside a # comment.
    if "comment" in regions:
        return "remove"

    # dood inside a single-line string literal in code.
    if effectiveCategory == "skip":
        return "keep"
    if effectiveCategory in ("logger", "raise"):
        return "remove"
    if effectiveCategory == "assert":
        firstStart = matches[0].start()
        inMessage = assertInMessage or (baseCommaIndex != -1 and baseCommaIndex < firstStart)
        return "remove" if inMessage else "keep"

    # Plain literal: assignment, return value, call argument, comparand, etc.
    return "keep"


def processFile(path: Path, dryRun: bool, verbose: bool) -> tuple[int, int, int]:
    """Strip stylistic dood from a single file.

    Args:
        path: File to process.
        dryRun: When True, report changes without writing.
        verbose: When True, print per-file detail.

    Returns:
        A ``(linesChanged, doodRemoved, standaloneDropped)`` tuple for this file.
    """
    original = path.read_text(encoding="utf-8")
    # Normalise on "\n" line endings for processing; restore exactly on write.
    usedCrLf = "\r\n" in original
    source = original.replace("\r\n", "\n") if usedCrLf else original
    lines = source.split("\n")

    outLines: list[str] = []
    # Cross-line state.
    inTriple: Optional[str] = None
    parenDepth = 0
    stmtCategory: Optional[str] = None
    assertBaseDepth = 0
    assertInMessage = False

    linesChanged = 0
    doodRemoved = 0
    standaloneDropped = 0

    for line in lines:
        classes, outTriple = scanLine(line, inTriple)

        # Effective statement category for this physical line.
        if stmtCategory is not None:
            effectiveCategory: Optional[str] = stmtCategory
        elif parenDepth == 0:
            effectiveCategory = _detectKeyword(line, classes)
        else:
            effectiveCategory = None

        # Bracket depth after this line + (for assert) the base-level comma.
        if effectiveCategory == "assert":
            curBase = parenDepth if stmtCategory is None else assertBaseDepth
        else:
            curBase = 0
        finalDepth, baseCommaIndex = _scanCodeDepth(line, classes, parenDepth, curBase)

        decision = evaluateLine(line, classes, effectiveCategory, assertInMessage, baseCommaIndex)

        if decision == "keep":
            outLines.append(line)
        elif decision == "remove-standalone":
            standaloneDropped += 1
            doodRemoved += len(_DOOD_WORD.findall(line))
            # Drop this line; trim a dangling comma from the previous kept line.
            if outLines:
                prev = outLines[-1].rstrip()
                if prev.endswith(","):
                    prev = prev[:-1].rstrip()
                outLines[-1] = prev
        else:  # remove
            newLine = _DOOD_PATTERN.sub("", line)
            if newLine != line:
                outLines.append(newLine)
                linesChanged += 1
                doodRemoved += len(_DOOD_WORD.findall(line))
            else:
                outLines.append(line)

        # ---- Update carried state for the next line. ----
        newAssertInMessage = assertInMessage
        if effectiveCategory == "assert":
            if stmtCategory is None:
                # A freshly started assert resets message tracking.
                newAssertInMessage = baseCommaIndex != -1
            elif baseCommaIndex != -1:
                newAssertInMessage = True

        if finalDepth > 0:
            if stmtCategory is not None:
                # Still inside the same multi-line statement.
                newStmtCategory: Optional[str] = stmtCategory
            else:
                # A statement opened on this line and is still open.
                newStmtCategory = effectiveCategory
                if effectiveCategory == "assert":
                    assertBaseDepth = parenDepth
        else:
            newStmtCategory = None

        inTriple = outTriple
        parenDepth = finalDepth
        stmtCategory = newStmtCategory
        assertInMessage = newAssertInMessage if newStmtCategory == "assert" else False

    newSource = "\n".join(outLines)
    if usedCrLf:
        newSource = newSource.replace("\n", "\r\n")

    if newSource == original:
        return (0, 0, 0)

    if not dryRun:
        path.write_text(newSource, encoding="utf-8")
    if verbose or dryRun:
        print(f"  {path}: {linesChanged} line(s), {doodRemoved} dood(s)")
    return (linesChanged, doodRemoved, standaloneDropped)


def main() -> int:
    """Entry point: walk the repo, strip dood from non-user-facing source.

    Returns:
        ``0`` on completion.
    """
    parser = argparse.ArgumentParser(description="Strip stylistic 'dood' from non-user-facing Python source.")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing files.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print every modified file with its count.")
    args = parser.parse_args()

    repoRoot = Path(__file__).resolve().parent.parent
    selfPath = Path(__file__).resolve()

    pyFiles: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repoRoot):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                p = Path(dirpath) / name
                if p.resolve() != selfPath:
                    pyFiles.append(p)

    totalFiles = 0
    totalLines = 0
    totalDood = 0
    totalStandalone = 0
    for p in sorted(pyFiles):
        linesChanged, doodRemoved, standaloneDropped = processFile(p, args.dry_run, args.verbose)
        if linesChanged or standaloneDropped:
            totalFiles += 1
            totalLines += linesChanged
            totalDood += doodRemoved
            totalStandalone += standaloneDropped

    mode = "DRY RUN — " if args.dry_run else ""
    print(f"{mode}Files modified: {totalFiles}")
    print(f"{mode}Lines changed:  {totalLines}")
    print(f"{mode}Standalone dood lines dropped: {totalStandalone}")
    print(f"{mode}'dood' tokens removed:        {totalDood}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
