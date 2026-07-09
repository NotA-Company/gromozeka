"""AST-based coverage guard for the memory-compaction-v1 read-path wiring.

Phase 3 of ``docs/plans/memory-compaction-v1.md`` wired
``EnsuredMessage.resolveMemories(self.cache)`` into every read-path consumer that
builds an ``EnsuredMessage`` from stored DB data and renders it for the LLM. The
compact memory format stores IDs in ``metadata["memories"]``
(``{"permanentIds": [...], "shortTermIds": [...]}``); ``resolveMemories`` resolves
those IDs to content via the cache and populates ``userMemories``. **If a future
developer adds a new ``fromDBChatMessage(..., injectMemories=<truthy>)`` render
site WITHOUT a ``resolveMemories`` call, compact-format messages at that site
render with NO ``userMemories`` (silently dropped).** This guard catches that
structurally — a plain grep for ``injectMemories=True`` does NOT work because no
production site uses the literal ``True`` (all pass a bool variable or an inline
``.toBool()``).

Two checks:

* **Check 1 (primary):** every ``fromDBChatMessage(injectMemories=<not literal
  False>)`` render site is followed by ``resolveMemories`` on the SAME target,
  in source order, before that target is rendered via ``toModelMessage`` /
  ``toModelMessageList`` / ``formatForLLM``. A site whose target is never
  rendered (e.g. ``eRootMessage`` in ``getThreadByMessageForLLM``, built for
  metadata read/persist only) is exempt. The scan set is discovered dynamically
  — every production file under ``internal/`` containing a
  ``fromDBChatMessage`` call — so a new read-path consumer is auto-covered
  without editing this guard.
* **Check 2 (secondary):** no production ``setUserMemories(...)`` call whose
  first positional argument is metadata-derived (an ``ast.Call`` like
  ``metadata.get("memories")`` or an ``ast.Subscript`` like
  ``metadata["memories"]``). Such a bypass would render the compact ID dict as
  the ``userMemories`` block (garbage). All memory-setting from stored metadata
  must go through ``loadMemoriesMetadata``.

The analysis is factored into pure helpers that take parsed AST (or a source
string) and return a list of violations/sites, so the sanity tests prove the
guard actually detects each violation class against synthetic snippets (a guard
that passes trivially protects nothing).

This is a TEST-ONLY structural guard; it never imports production code and never
mutates production source.
"""

import ast
import textwrap
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple, Union

REPO_ROOT = Path(__file__).resolve().parent.parent

# Render methods that turn an EnsuredMessage into LLM-facing content. A site is
# "rendered" the first time its target hits one of these after the assignment.
RENDER_ATTRS = frozenset({"toModelMessage", "toModelMessageList", "formatForLLM"})
RESOLVE_ATTR = "resolveMemories"
FROMDB_ATTR = "fromDBChatMessage"
SETUSERMEMORIES_ATTR = "setUserMemories"


def _discoverFromDBFiles() -> List[str]:
    """Discover every production file under ``internal/`` containing a ``fromDBChatMessage`` call.

    Walks ``internal/`` recursively for ``.py`` modules and selects those whose
    AST contains any ``ast.Attribute`` with ``attr == "fromDBChatMessage"``. The
    ``EnsuredMessage.fromDBChatMessage`` method definition in
    ``ensured_message.py`` is an ``ast.AsyncFunctionDef`` (not an
    ``ast.Attribute``), so it is naturally excluded — only call sites match,
    which is exactly the set Check 1 must scan. The dynamic scan means a new
    read-path consumer added under ``internal/`` is covered automatically
    without editing this guard.

    Returns:
        Repository-relative paths of every file containing a
        ``fromDBChatMessage`` attribute access, sorted for stable test output.
    """
    hits: List[str] = []
    for path in sorted((REPO_ROOT / "internal").rglob("*.py")):
        src = path.read_text()
        tree = ast.parse(src, filename=str(path))
        if any(isinstance(node, ast.Attribute) and node.attr == FROMDB_ATTR for node in ast.walk(tree)):
            hits.append(str(path.relative_to(REPO_ROOT)))
    return hits


# Check 1 scans every production file under ``internal/`` that contains a
# ``fromDBChatMessage`` call — discovered dynamically (see _discoverFromDBFiles)
# so a new read-path consumer is auto-covered without touching this guard.
CHECK1_FILES: List[str] = _discoverFromDBFiles()

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


class Check1Site(NamedTuple):
    """One ``fromDBChatMessage`` assignment site and its Check-1 verdict.

    Attributes:
        file: Repository-relative path of the file containing the site.
        line: 1-based source line of the assignment.
        target: Assignment-target variable name (e.g. ``eMessage``).
        included: True when ``injectMemories`` is not the literal ``False``.
        verdict: One of ``"skipped"`` (literal-False), ``"exempt"`` (included but
            never rendered), ``"ok"`` (rendered, resolveMemories present between),
            or ``"violation"`` (rendered, no resolveMemories between).
        detail: Failure message, populated only when ``verdict == "violation"``.
    """

    file: str
    line: int
    target: str
    included: bool
    verdict: str
    detail: str = ""


def _nameAttrCall(node: ast.AST) -> Optional[Tuple[str, str, int]]:
    """Classify a ``name.attr(...)`` call node.

    Args:
        node: Any AST node.

    Returns:
        ``(name, attr, lineno)`` when ``node`` is an ``ast.Call`` whose ``func``
        is an ``ast.Attribute`` on an ``ast.Name`` (e.g.
        ``eMessage.toModelMessage``); ``lineno`` is the call's source line.
        Otherwise ``None``.
    """
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return (func.value.id, func.attr, node.lineno)
    return None


def _fromDBAssignment(node: Union[ast.Assign, ast.AnnAssign]) -> Optional[Tuple[str, int, ast.Call]]:
    """Detect a ``T = [await] X.fromDBChatMessage(...)`` assignment.

    Handles plain assignments (``ast.Assign``: ``T = ...``) and annotated
    assignments (``ast.AnnAssign``: ``T: SomeType = ...``); both
    ``await EnsuredMessage.fromDBChatMessage(...)`` and the non-awaited /
    ``cls.fromDBChatMessage(...)`` shapes (matched by attribute name regardless
    of the receiver). An ``AnnAssign`` with no value (a bare annotation like
    ``T: SomeType``) yields ``None``.

    Args:
        node: An ``ast.Assign`` or ``ast.AnnAssign`` node.

    Returns:
        ``(target, assignmentLineno, callNode)`` when ``node`` binds a single
        ``Name`` target to a (possibly awaited) ``fromDBChatMessage`` call,
        otherwise ``None``.
    """
    if isinstance(node, ast.AnnAssign):
        if node.value is None or not isinstance(node.target, ast.Name):
            return None
        value: ast.expr = node.value
        targetName = node.target.id
    else:
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return None
        value = node.value
        targetName = node.targets[0].id
    if isinstance(value, ast.Await):
        value = value.value
    if not isinstance(value, ast.Call):
        return None
    func = value.func
    if isinstance(func, ast.Attribute) and func.attr == FROMDB_ATTR:
        return (targetName, node.lineno, value)
    return None


def _injectMemoriesIncluded(call: ast.Call) -> bool:
    """Return whether the ``injectMemories`` keyword warrants a resolveMemories.

    The literal ``injectMemories=False`` is the only exempt shape (memory
    injection explicitly off). Any other value (a ``Name`` like
    ``needMemories``, a ``Call`` like ``.toBool()``, or an absent keyword) is
    treated as potentially truthy and therefore requires resolution.

    Args:
        call: A ``fromDBChatMessage`` call node.

    Returns:
        False only when ``injectMemories`` is the literal ``False`` constant;
        True otherwise.
    """
    for kw in call.keywords:
        if kw.arg == "injectMemories":
            v = kw.value
            if isinstance(v, ast.Constant) and v.value is False:
                return False
            return True
    return True


def _walkScopeBody(func: ast.AST) -> List[ast.AST]:
    """Collect descendant nodes of ``func`` without descending into nested scopes.

    Nested ``FunctionDef`` / ``AsyncFunctionDef`` / ``Lambda`` / ``ClassDef``
    bodies are analysed by their own outer-loop iteration (in ``analyzeCheck1``),
    so this walk stops at scope boundaries to avoid double-counting a nested
    function's calls against the enclosing function.

    Args:
        func: A ``FunctionDef`` / ``AsyncFunctionDef`` node.

    Returns:
        Flat list of descendant nodes belonging to ``func``'s own scope only.
    """
    out: List[ast.AST] = []
    stack: List[ast.AST] = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        out.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return out


def analyzeCheck1(tree: ast.AST, file: str) -> List[Check1Site]:
    """Run Check 1 over a parsed module.

    For every ``FunctionDef`` / ``AsyncFunctionDef`` (including nested ones,
    each analysed in its own scope), finds ``fromDBChatMessage`` assignments and
    verifies each included site is followed by a ``resolveMemories`` on the same
    target before the target's first render.

    Args:
        tree: A parsed ``ast.Module`` (or any AST root).
        file: Repository-relative path label used in site/violation messages.

    Returns:
        One :class:`Check1Site` per ``fromDBChatMessage`` assignment, with a
        ``verdict`` of ``"skipped"`` / ``"exempt"`` / ``"ok"`` / ``"violation"``.
    """
    sites: List[Check1Site] = []
    for func in ast.walk(tree):
        if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sites.extend(_analyzeFunctionCheck1(func, file))
    return sites


def _analyzeFunctionCheck1(func: ast.AST, file: str) -> List[Check1Site]:
    """Analyse a single function body for Check-1 sites.

    Collects (target, line) events for ``fromDBChatMessage`` assignments,
    ``resolveMemories`` calls, and render calls, then applies source-order line
    comparison per assignment (see plan §7.3 note on variable reuse: each
    assignment is followed by its own render+resolve before the next
    assignment, so pure line comparison is sufficient — no control-flow
    analysis).

    Args:
        func: A ``FunctionDef`` / ``AsyncFunctionDef`` node.
        file: Repository-relative path label for messages.

    Returns:
        List of :class:`Check1Site` for each ``fromDBChatMessage`` assignment in
        this function's own scope.
    """
    assigns: List[Tuple[str, int, bool]] = []
    renders: List[Tuple[str, int]] = []
    resolves: List[Tuple[str, int]] = []
    for node in _walkScopeBody(func):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            got = _fromDBAssignment(node)
            if got is not None:
                target, lineno, call = got
                assigns.append((target, lineno, _injectMemoriesIncluded(call)))
            continue
        na = _nameAttrCall(node)
        if na is not None:
            name, attr, callLine = na
            if attr == RESOLVE_ATTR:
                resolves.append((name, callLine))
            elif attr in RENDER_ATTRS:
                renders.append((name, callLine))

    out: List[Check1Site] = []
    for target, lineno, included in assigns:
        if not included:
            out.append(Check1Site(file, lineno, target, False, "skipped"))
            continue
        renderLines = sorted(rl for (rn, rl) in renders if rn == target and rl > lineno)
        if not renderLines:
            # Target is built but never rendered in this scope (e.g. eRootMessage,
            # read/persist-only) -> no resolution required.
            out.append(Check1Site(file, lineno, target, True, "exempt"))
            continue
        renderLine = renderLines[0]
        resolveBetween = [ml for (mn, ml) in resolves if mn == target and lineno < ml < renderLine]
        if resolveBetween:
            out.append(Check1Site(file, lineno, target, True, "ok"))
        else:
            out.append(
                Check1Site(
                    file,
                    lineno,
                    target,
                    True,
                    "violation",
                    (
                        f"fromDBChatMessage(injectMemories=<truthy>) assigns {target} "
                        f"which is rendered at {renderLine} but no {target}.resolveMemories(...) "
                        f"call found between — compact-format memories would be silently dropped"
                    ),
                )
            )
    return out


def check1Violations(sites: List[Check1Site]) -> List[Violation]:
    """Extract :class:`Violation` entries from Check-1 sites.

    Args:
        sites: Output of :func:`analyzeCheck1`.

    Returns:
        Only the sites whose verdict is ``"violation"``.
    """
    return [Violation(s.file, s.line, s.detail) for s in sites if s.verdict == "violation"]


def analyzeCheck2(tree: ast.AST, file: str) -> List[Violation]:
    """Run Check 2 (ban the ``setUserMemories(metadata-derived)`` bypass).

    Finds every ``setUserMemories(...)`` call and flags it when the first
    positional argument is an ``ast.Call`` (e.g. ``metadata.get("memories")``)
    or an ``ast.Subscript`` (e.g. ``metadata["memories"]``) — both bypass
    ``loadMemoriesMetadata`` and would render the compact ID dict verbatim.

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
                        f"({ast.dump(arg)}); use loadMemoriesMetadata instead to handle "
                        f"the compact format"
                    ),
                )
            )
    return violations


def _readTree(relPath: str) -> Tuple[ast.AST, str]:
    """Parse a production file relative to the repo root.

    Args:
        relPath: Repository-relative path (e.g. ``internal/bot/common/handlers/base.py``).

    Returns:
        ``(parsedModule, relPath)`` for labelling violations/sites.
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


# --- Check 1: production tree has no missing resolveMemories sites -----------


def test_check1_noViolationsOnProductionTree() -> None:
    """Check 1: every rendered ``fromDBChatMessage(injectMemories=<truthy>)`` site
    in the scanned production files is followed by a ``resolveMemories`` on the
    same target before its first render. Zero violations expected on the current
    Phase-3 tree.
    """
    violations: List[Violation] = []
    for relPath in CHECK1_FILES:
        tree, label = _readTree(relPath)
        violations.extend(check1Violations(analyzeCheck1(tree, label)))
    assert not violations, "Check-1 violations (missing resolveMemories before render):\n" + _formatViolations(
        violations
    )


def test_check1_expectedProductionSites() -> None:
    """Lock the known Check-1 site set so a silently-disappearing or newly-added
    site is surfaced for review. Verifies the dynamically-discovered scan set
    matches the expected production files, the included ``fromDBChatMessage``
    sites match the Phase-3 wiring exactly, and ``eRootMessage`` is the single
    exempt (built-but-not-rendered) site.
    """
    expectedFiles = sorted(
        [
            "internal/bot/common/handlers/base.py",
            "internal/bot/common/handlers/chat_search.py",
            "internal/bot/common/handlers/llm_messages.py",
            "internal/bot/common/handlers/media.py",
            "internal/bot/common/handlers/summarization.py",
            "internal/bot/common/handlers/user_data.py",
        ]
    )
    assert (
        sorted(CHECK1_FILES) == expectedFiles
    ), f"Check-1 discovered file set drifted.\nExpected:\n{expectedFiles}\nActual:\n{sorted(CHECK1_FILES)}"

    allSites: List[Check1Site] = []
    for relPath in CHECK1_FILES:
        tree, label = _readTree(relPath)
        allSites.extend(analyzeCheck1(tree, label))

    includedSites = [s for s in allSites if s.included]
    expected = sorted(
        [
            ("internal/bot/common/handlers/base.py", "eMessage"),
            ("internal/bot/common/handlers/base.py", "eMessage"),
            ("internal/bot/common/handlers/base.py", "eMessage"),
            ("internal/bot/common/handlers/base.py", "eRootMessage"),
            ("internal/bot/common/handlers/llm_messages.py", "eStoredReply"),
            ("internal/bot/common/handlers/llm_messages.py", "eMsg"),
            ("internal/bot/common/handlers/media.py", "eMsg"),
        ]
    )
    actual = sorted((s.file, s.target) for s in includedSites)
    assert actual == expected, f"Check-1 included site set drifted.\nExpected:\n{expected}\nActual:\n{actual}"

    exempt = [s for s in includedSites if s.verdict == "exempt"]
    assert [(s.file, s.target) for s in exempt] == [
        ("internal/bot/common/handlers/base.py", "eRootMessage")
    ], f"Unexpected exempt sites: {[(s.file, s.target, s.line) for s in exempt]}"

    bad = [s for s in allSites if s.verdict == "violation"]
    assert not bad, "Check-1 violations: " + _formatViolations(check1Violations(allSites))


# --- Check 2: no setUserMemories(metadata-derived) bypass in production ------


def test_check2_noSetUserMemoriesBypassInProduction() -> None:
    """Check 2: no ``setUserMemories(...)`` call in the scanned production files
    (read-path consumers + write path) passes a metadata-derived argument.
    All memory-setting from stored metadata must go through ``loadMemoriesMetadata``.
    """
    violations: List[Violation] = []
    for relPath in CHECK2_FILES:
        tree, label = _readTree(relPath)
        violations.extend(analyzeCheck2(tree, label))
    assert not violations, "Check-2 violations (setUserMemories metadata bypass):\n" + _formatViolations(violations)


# --- Sanity tests: prove the guard detects each violation class --------------


def test_sanity_check1_flagsMissingResolveBeforeRender() -> None:
    """A ``fromDBChatMessage(injectMemories=<truthy>)`` site rendered WITHOUT a
    preceding ``resolveMemories`` must be flagged as a violation.
    """
    src = textwrap.dedent("""
        async def f(self):
            eMessage = await EnsuredMessage.fromDBChatMessage(dbMessage, self.db, injectMemories=needMemories)
            ret = await eMessage.toModelMessageList(self.db)
            return ret
        """)
    violations = check1Violations(analyzeCheck1(ast.parse(src), "synthetic.py"))
    assert len(violations) == 1, f"expected one violation, got {violations}"
    assert "resolveMemories" in violations[0].message
    assert violations[0].file == "synthetic.py"


def test_sanity_check1_passesWithResolveBeforeRender() -> None:
    """The same site WITH a ``resolveMemories`` between assignment and render
    must pass cleanly.
    """
    src = textwrap.dedent("""
        async def f(self):
            eMessage = await EnsuredMessage.fromDBChatMessage(dbMessage, self.db, injectMemories=needMemories)
            await eMessage.resolveMemories(self.cache)
            ret = await eMessage.toModelMessageList(self.db)
            return ret
        """)
    violations = check1Violations(analyzeCheck1(ast.parse(src), "synthetic.py"))
    assert violations == []


def test_sanity_check1_exemptsUnrenderedTarget() -> None:
    """A site whose target is built but never rendered (the ``eRootMessage``
    exemption) must pass — no ``resolveMemories`` is required for a message that
    is only read/persisted, never turned into LLM content.
    """
    src = textwrap.dedent("""
        async def f(self):
            eRootMessage = await EnsuredMessage.fromDBChatMessage(
                dbMessageList[0], self.db, injectMemories=needMemories
            )
            condenseCache = eRootMessage.metadata.get("condensedThread", [])
            eRootMessage.metadata["condensedThread"] = condenseCache
            return eRootMessage.metadata
        """)
    sites = analyzeCheck1(ast.parse(src), "synthetic.py")
    assert len(sites) == 1
    assert sites[0].verdict == "exempt"
    assert sites[0].target == "eRootMessage"
    assert check1Violations(sites) == []


def test_sanity_check1_skipsInjectMemoriesFalse() -> None:
    """A site with ``injectMemories=False`` is skipped entirely — memory
    injection is explicitly off, so no resolution is needed even when rendered.
    """
    src = textwrap.dedent("""
        async def f(self):
            eStoredMsg = await EnsuredMessage.fromDBChatMessage(storedReply, self.db, injectMemories=False)
            ret = await eStoredMsg.toModelMessage(self.db)
            return ret
        """)
    sites = analyzeCheck1(ast.parse(src), "synthetic.py")
    assert len(sites) == 1
    assert sites[0].verdict == "skipped"
    assert check1Violations(sites) == []


def test_sanity_check1_handlesReusedTargetName() -> None:
    """A reused target name (e.g. ``eMessage`` assigned by multiple
    ``fromDBChatMessage`` calls in ``getThreadByMessageForLLM``) must be analysed
    per-assignment by source-order line comparison: each assignment is followed
    by its own render+resolve before the next assignment, so all pass.
    """
    src = textwrap.dedent("""
        async def f(self):
            eMessage = await EnsuredMessage.fromDBChatMessage(a, self.db, injectMemories=needMemories)
            await eMessage.resolveMemories(self.cache)
            ret = await eMessage.toModelMessageList(self.db)
            eMessage = await EnsuredMessage.fromDBChatMessage(b, self.db, injectMemories=needMemories)
            await eMessage.resolveMemories(self.cache)
            ret2 = await eMessage.toModelMessageList(self.db)
            return [ret, ret2]
        """)
    violations = check1Violations(analyzeCheck1(ast.parse(src), "synthetic.py"))
    assert violations == []

    # And the same shape with the second block missing its resolveMemories must
    # surface exactly one violation pointing at the second assignment.
    badSrc = textwrap.dedent("""
        async def f(self):
            eMessage = await EnsuredMessage.fromDBChatMessage(a, self.db, injectMemories=needMemories)
            await eMessage.resolveMemories(self.cache)
            ret = await eMessage.toModelMessageList(self.db)
            eMessage = await EnsuredMessage.fromDBChatMessage(b, self.db, injectMemories=needMemories)
            ret2 = await eMessage.toModelMessageList(self.db)
            return [ret, ret2]
        """)
    badViolations = check1Violations(analyzeCheck1(ast.parse(badSrc), "synthetic.py"))
    assert len(badViolations) == 1, f"expected one violation, got {badViolations}"


def test_sanity_check1_flagsAnnAssignMissingResolve() -> None:
    """A typed/annotated ``T: SomeType = ... fromDBChatMessage(injectMemories=<truthy>)``
    site rendered WITHOUT a preceding ``resolveMemories`` must be flagged.
    No current production site uses this ``ast.AnnAssign`` shape, but a future
    one would evade the guard without explicit handling.
    """
    src = textwrap.dedent("""
        async def f(self):
            eMessage: EnsuredMessage = await EnsuredMessage.fromDBChatMessage(
                dbMessage, self.db, injectMemories=needMemories
            )
            ret = await eMessage.toModelMessageList(self.db)
            return ret
        """)
    violations = check1Violations(analyzeCheck1(ast.parse(src), "synthetic.py"))
    assert len(violations) == 1, f"expected one violation, got {violations}"
    assert "eMessage" in violations[0].message
    assert "resolveMemories" in violations[0].message


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
    assert all("loadMemoriesMetadata" in v.message for v in violations)


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
