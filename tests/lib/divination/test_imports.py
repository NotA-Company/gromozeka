"""Boundary test: ``lib/divination`` must not pull in bot-side modules, dood!

The divination library is intentionally decoupled from the bot's runtime —
it talks to :mod:`lib.ai` only. This test asserts that importing
:mod:`lib.divination` does not, as a side effect, drag in
:mod:`internal.services.llm` or anything under :mod:`internal.bot`.

The check runs in a freshly spawned Python subprocess so that prior tests in
the same pytest session can't pollute ``sys.modules`` and mask a real leak
(or, more commonly, manufacture a false positive), dood!
"""

import subprocess
import sys


def testLibDivinationDoesNotPullBotSideModules() -> None:
    """``lib.divination`` must not transitively import bot-side modules.

    Spawns a fresh Python interpreter, imports :mod:`lib.divination` there,
    and reports back any loaded modules whose names start with
    ``internal.services.llm`` or ``internal.bot``. A clean run yields an
    empty list; anything else is a boundary violation, dood!

    Returns:
        None.
    """
    probeCode: str = (
        "import importlib, json, sys;"
        " importlib.import_module('lib.divination');"
        " forbiddenPrefixes = ('internal.services.llm', 'internal.bot');"
        " leaked = sorted(m for m in sys.modules if m.startswith(forbiddenPrefixes));"
        " print(json.dumps(leaked))"
    )
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-c", probeCode],
        capture_output=True,
        text=True,
        check=True,
    )
    leaked: str = result.stdout.strip()
    assert leaked == "[]", f"lib/divination leaked forbidden imports: {leaked}, dood!"
