"""AST-based coverage guard for the memory-compaction-v1 read-path wiring.

The compact memory format stores IDs in ``metadata["memories"]``
(``{"permanentIds": [...], "shortTermIds": [...]}``); resolution to content
happens lazily in ``formatForLLM`` via ``cache.getMemoriesByIds`` at render
time. The ``injectMemories``/``cache`` parameters on ``fromDBChatMessage``
and the ``setUserMemories``/``resolveMemories`` methods on
:class:`EnsuredMessage` were removed in Phase 4 — the guard that checked them
(Check 1) was removed with them.

One check remains:

* **Check 2:** no production ``setUserMemories(...)`` call whose first
  positional argument is metadata-derived (an ``ast.Call`` like
  ``metadata.get("memories")`` or an ``ast.Subscript`` like
  ``metadata["memories"]``). Such a bypass would render the compact ID dict as
  the ``userMemories`` block (garbage). With ``setUserMemories`` removed from
  :class:`EnsuredMessage`, this check passes vacuously on the current tree —
  it is retained as a regression guard against the method's reintroduction.

The analysis is factored into pure helpers that take parsed AST (or a source
string) and return a list of violations, so the sanity tests prove the guard
actually detects each violation class against synthetic snippets (a guard
that passes trivially protects nothing).

This is a TEST-ONLY structural guard; it never imports production code and never
mutates production source.
"""

import ast
import textwrap
from pathlib import Path
from typing import List, NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent

SETUSERMEMORIES_ATTR = "setUserMemories"

# Check 2 (the setUserMemories bypass ban) is scoped to the read-path + write
# files where the banned bypass shape could plausibly be reintroduced; it stays
# a fixed list.
CHECK2_FILES: List[str] = [
    "internal/bot/common/handlers/base.py",
    "internal/bot/common/handlers/llm_messages.py",
    "internal/bot/common/handlers/media.py",
    "internal/bot/common/handlers/message_preprocessor.py",
]


class Violation(NamedTuple):
    """A single guard violation with a ``file:line`` anchor and message.

    Attributes:
        file: Repository-relative path of the offending file.
        line: 1-based source line of the offending construct.
        message: Human-readable explanation of why the construct violates the guard.
    """

    file: str
    line: int
    message: str


def analyzeCheck2(tree: ast.AST, file: str) -> List[Violation]:
    """Run Check 2 (ban the ``setUserMemories(metadata-derived)`` bypass).

    Finds every ``setUserMemories(...)`` call and flags it when the first
    positional argument is an ``ast.Call`` (e.g. ``metadata.get("memories")``)
    or an ``ast.Subscript`` (e.g. ``metadata["memories"]``) — both bypass
    resolution and would render the compact ID dict verbatim.

    Args:
        tree: A parsed ``ast.Module`` (or any AST root).
        file: Repository-relative path label for messages.

    Returns:
        One :class:`Violation` per offending ``setUserMemories`` call.
    """
    violations: List[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == SETUSERMEMORIES_ATTR):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, (ast.Call, ast.Subscript)):
            violations.append(
                Violation(
                    file=file,
                    line=node.lineno,
                    message=(
                        f"setUserMemories called with a metadata-derived argument "
                        f"({ast.dump(arg)}); resolve compact IDs via cache.getMemoriesByIds "
                        f"in formatForLLM instead of setUserMemories"
                    ),
                )
            )
    return violations


def _readTree(relPath: str) -> tuple[ast.AST, str]:
    """Parse a production file relative to the repo root.

    Args:
        relPath: Repository-relative path (e.g. ``internal/bot/common/handlers/base.py``).

    Returns:
        ``(parsedModule, relPath)`` for labelling violations.
    """
    src = (REPO_ROOT / relPath).read_text()
    return ast.parse(src, filename=relPath), relPath


def _formatViolations(violations: List[Violation]) -> str:
    """Render violations as a ``file:line: message`` newline-joined block.

    Args:
        violations: Violations to format.

    Returns:
        Newline-joined ``file:line: message`` strings.
    """
    return "\n".join(f"{v.file}:{v.line}: {v.message}" for v in violations)


# --- Check 2: no setUserMemories(metadata-derived) bypass in production ------


def test_check2_noSetUserMemoriesBypassInProduction() -> None:
    """Check 2: no ``setUserMemories(...)`` call in the scanned production files
    (read-path consumers + write path) passes a metadata-derived argument.
    With ``setUserMemories`` removed from :class:`EnsuredMessage`, this passes
    vacuously; the guard is retained against reintroduction.
    """
    violations: List[Violation] = []
    for relPath in CHECK2_FILES:
        tree, label = _readTree(relPath)
        violations.extend(analyzeCheck2(tree, label))
    assert not violations, "Check-2 violations (setUserMemories metadata bypass):\n" + _formatViolations(violations)


# --- Sanity tests: prove the guard detects each violation class --------------


def test_sanity_check2_flagsMetadataDerivedSetUserMemories() -> None:
    """A ``setUserMemories(metadata.get("memories"))`` and a
    ``setUserMemories(metadata["memories"])`` call must both be flagged as the
    banned bypass shape.
    """
    src = textwrap.dedent("""
        async def f(self):
            ensuredReply.setUserMemories(metadata.get("memories"))
            other.setUserMemories(metadata["memories"])
        """)
    violations = analyzeCheck2(ast.parse(src), "synthetic.py")
    assert len(violations) == 2, f"expected two violations, got {violations}"
    assert all("getMemoriesByIds" in v.message for v in violations)


def test_sanity_check2_passesNameArgument() -> None:
    """A ``setUserMemories(<Name>)`` call (the legitimate
    ``self.setUserMemories(rawMemories)`` shape) must NOT be flagged.
    """
    src = textwrap.dedent("""
        async def f(self):
            self.setUserMemories(rawMemories)
        """)
    violations = analyzeCheck2(ast.parse(src), "synthetic.py")
    assert violations == []
