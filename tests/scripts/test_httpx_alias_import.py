"""Import-order regression tests for the httpx→httpx2 alias in ``scripts/``.

Every script under ``scripts/`` that imports project code (``internal.*`` /
``lib.*``) transitively triggers a real ``import httpx`` at module level
(e.g. ``lib.db.providers`` eagerly imports sqlink, whose ``_transport`` does
``import httpx``; ``lib.ai`` providers pull the openai SDK, which does the
same). ``scripts/_lib/bootstrap`` calls ``httpx2.alias_httpx()`` at module
level, but isort's alphabetical ordering sorts the ``scripts._lib`` import
AFTER every ``internal``/``lib`` import in the same block — so the alias
fired too late and bootstrap raised::

    RuntimeError: httpx was already imported; call `alias_httpx()`
    before any `import httpx`.

The fix follows the ``main.py`` house pattern: each script calls
``httpx2.alias_httpx()`` directly, before its first project import
(bootstrap's later repeat call is idempotent).

These tests spawn a FRESH interpreter per script (subprocess) because the
pytest conftest aliases httpx before any test module runs — an in-process
import would be masked by conftest's alias and could not reproduce the
standalone-invocation failure mode (``./venv/bin/python3 scripts/<x>.py``).
The embedded ``python -c`` snippet is a self-contained regression assertion,
not ad-hoc shell testing — the repo's "no ``python -c``" rule targets manual
shell experimentation (same exemption as
``tests/lib/max_webhook_receiver/test_init.py``).
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Scripts that import project code (internal.*/lib.*) and therefore must
# install the httpx→httpx2 alias BEFORE their first project import. All but
# prune_unknown_chat_settings.py crashed at import time with the RuntimeError
# above before the fix; prune_unknown_chat_settings.py imported cleanly but
# silently ran on real httpx (no alias, no crash) — same assertion covers it.
_ALIASING_SCRIPTS = [
    "check_condensing.py",
    "check_image_parsing.py",
    "check_structured_output.py",
    "check_tool_calling.py",
    "list_models.py",
    "prune_unknown_chat_settings.py",
    "reproduce_layout_extraction.py",
    "reproduce_llm_dialog.py",
    "run_llm_debug_query.py",
    "transcribe.py",
]


class TestScriptHttpxAliasImport:
    """Standalone-script imports must survive and alias httpx to httpx2."""

    @pytest.mark.parametrize("scriptName", _ALIASING_SCRIPTS)
    def test_freshInterpreterImportsScriptAndAliasesHttpx(self, scriptName: str) -> None:
        """A fresh interpreter must import the script without the alias RuntimeError.

        Loads the script module by path (so ``__name__ != "__main__"`` and
        argparse/main() never run — only the module-level imports execute)
        and asserts the httpx→httpx2 alias is active afterwards.

        Args:
            scriptName: Filename relative to ``scripts/``.

        Returns:
            None: Asserts the subprocess exited 0 (stderr surfaced on failure).
        """
        targetPath = REPO_ROOT / "scripts" / scriptName
        childCode = (
            "import importlib.util, sys, httpx2\n"
            "from pathlib import Path\n"
            f"target = Path({str(targetPath)!r})\n"
            "sys.path.insert(0, str(target.parent.parent.resolve()))\n"
            "spec = importlib.util.spec_from_file_location(target.stem, target)\n"
            "assert spec is not None and spec.loader is not None\n"
            "module = importlib.util.module_from_spec(spec)\n"
            # Register before exec: dataclasses._is_type resolves string
            # annotations via sys.modules[cls.__module__] — same reason the
            # house loader in tests/scripts/test_check_structured_output.py
            # uses setdefault before exec_module.
            "sys.modules[target.stem] = module\n"
            "spec.loader.exec_module(module)\n"
            "assert sys.modules['httpx'] is httpx2, 'httpx not aliased to httpx2'\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", childCode],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"{scriptName} failed to import in a fresh interpreter (this is the "
            f"standalone `./venv/bin/python3 scripts/{scriptName}` failure mode):\n"
            f"{result.stderr}"
        )
