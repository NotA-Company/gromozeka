"""Tests for lib.max_webhook_receiver.__init__ (package-import side effects).

Covers the httpx→httpx2 alias contract: importing the package must call
``httpx2.alias_httpx()`` BEFORE its own imports, because ``.repository``
transitively reaches sqlink (``lib.db.providers`` imports it eagerly), which
performs a hard module-level ``import httpx``. If the alias did not fire first,
that import would resolve to the real httpx pinned in the dev venv (a shadowed
transitive dep) — so the ``sys.modules`` identity assertion is what must fire.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestHttpxAliasOnImport:
    """The package __init__ must alias httpx→httpx2 before its own imports."""

    def testFreshSubprocessImportAliasesHttpx(self) -> None:
        """A bare-subprocess import of the package must alias httpx to httpx2.

        Spawns a FRESH interpreter without pytest's conftest aliasing
        (tests/conftest.py aliases before any test module), so this proves the
        package __init__ itself installs the alias — e.g. under
        ``python -m lib.max_webhook_receiver`` where the bot's main.py alias
        never ran. The embedded subprocess snippet is a self-contained
        regression assertion, not ad-hoc shell testing (the repo's
        "no ``python -c``" rule targets manual shell experimentation).

        Returns:
            None: Asserts the subprocess exited successfully.
        """
        code = (
            "import sys, httpx2, lib.max_webhook_receiver; "
            "assert sys.modules['httpx'] is httpx2, 'httpx not aliased'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
