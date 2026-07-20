"""Tests for ``scripts/_lib/bootstrap.py`` and the cross-script invariant it enforces.

Two test groups:

1. **Unit tests for ``bootstrapProxy()``** — verify the helper actually calls
   ``ProxyHelper.getInstance().setGlobalProxyConfig(configManager.getProxyConfig())``
   with the right argument shape. Uses the autouse ``resetProxyHelperSingleton``
   fixture from ``tests/conftest.py`` to ensure a clean singleton before each
   test.

2. **Source-inspection invariant tests** — for every script under ``scripts/``
   that constructs ``ConfigManager`` and then builds any proxy-consuming
   service (``LLMManager``, ``Database`` with sqlink, ``ProviderClass(``
   for direct provider instantiation), assert the script imports
   ``bootstrapProxy`` from ``scripts._lib.bootstrap`` AND calls it AFTER
   ``ConfigManager(...)`` AND BEFORE the first proxy-consuming construct.

   This catches the original regression in ``scripts/check_image_parsing.py``
   (constructed ``LLMManager`` without proxy init → all providers raised
   ``TypeError("need to call setGlobalProxyConfig() first")`` → script
   silently exited with 0 testable models) and the same latent bug that
   was simultaneously present in ``check_structured_output.py``,
   ``check_tool_calling.py``, ``run_llm_debug_query.py``, and
   ``list_models.py``.

   ``scripts/sandbox_bootstrap.py`` is intentionally excluded: it only
   loads ``[sandbox]`` / ``[storage]`` config and never constructs any
   proxy-consuming service.
"""

from __future__ import annotations

import sys
import unittest.mock
from pathlib import Path
from typing import List, Tuple

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from internal.config.manager import ConfigManager  # noqa: E402
from lib.proxy import ProxyHelper, ProxyType  # noqa: E402
from scripts._lib.bootstrap import bootstrapProxy  # noqa: E402

# ---------------------------------------------------------------------------
# Unit tests for bootstrapProxy()
# ---------------------------------------------------------------------------


def _makeFakeConfigManager(proxyConfig: object) -> unittest.mock.MagicMock:
    """Build a ``MagicMock`` standing in for ``ConfigManager``.

    Using ``spec=ConfigManager`` constrains attribute access to the real
    ``ConfigManager`` API and keeps pyright happy (``MagicMock`` is treated
    as ``Any``). Only ``getProxyConfig()`` is exercised by ``bootstrapProxy``;
    we configure it to return the supplied dict.

    Args:
        proxyConfig: The dict the fake should return from ``getProxyConfig()``.

    Returns:
        A configured ``MagicMock`` that quacks like a ``ConfigManager`` for
        the purposes of ``bootstrapProxy``.
    """
    fake = unittest.mock.MagicMock(spec=ConfigManager)
    fake.getProxyConfig.return_value = proxyConfig
    return fake


class TestBootstrapProxyUnit:
    """Unit tests for the ``bootstrapProxy()`` helper itself."""

    def test_setsGlobalProxyConfigFromConfigManager(self) -> None:
        """``bootstrapProxy(cm)`` must seed the singleton from ``cm.getProxyConfig()``.

        After the call, ``ProxyHelper.getInstance().getGlobalProxyConfig()``
        must reflect the dict the fake config manager returned.
        """
        testConfig: dict = {
            "enabled": True,
            "type": "http",
            "address": "http://test.example:8080",
            "user": "u",
            "password": "pw",
        }
        fakeCm = _makeFakeConfigManager(testConfig)

        bootstrapProxy(fakeCm)

        fakeCm.getProxyConfig.assert_called_once()
        stored = ProxyHelper.getInstance().getGlobalProxyConfig()
        assert stored.type == ProxyType.HTTP
        assert stored.address == "http://test.example:8080"
        assert stored.user == "u"
        assert stored.password == "pw"

    def test_isIdempotent_lastCallWins(self) -> None:
        """Calling ``bootstrapProxy`` twice with different configs must keep the last.

        Idempotency here means: no exception, no init-guard refusal, and the
        second call's config is what ``getGlobalProxyConfig()`` returns.
        """
        first = _makeFakeConfigManager({"enabled": True, "type": "http", "address": "http://first:80"})
        second = _makeFakeConfigManager({"enabled": True, "type": ProxyType.SOCKS5, "address": "socks5://second:1080"})

        bootstrapProxy(first)
        bootstrapProxy(second)

        stored = ProxyHelper.getInstance().getGlobalProxyConfig()
        assert stored.type == ProxyType.SOCKS5
        assert stored.address == "socks5://second:1080"
        first.getProxyConfig.assert_called_once()
        second.getProxyConfig.assert_called_once()

    def test_disabledProxyConfig_isHonoured(self) -> None:
        """An ``enabled=False`` config dict must produce a disabled global config.

        Mirrors what ``main.py`` would pass at startup if the user explicitly
        disables proxy in TOML. The kill-switch in ``getCombined()`` later
        resolves per-service configs to NONE regardless of the stored type.
        """
        fakeCm = _makeFakeConfigManager({"enabled": False})

        bootstrapProxy(fakeCm)

        stored = ProxyHelper.getInstance().getGlobalProxyConfig()
        # fromDict({"enabled": False}) → enabled=False, type stays whatever
        # the dict had (None here — the dict did not include a "type" key).
        # The disabling effect kicks in later via getCombined()'s master
        # kill-switch on enabled=False, not by coercion at storage time.
        assert stored.enabled is False
        assert stored.type is None


# ---------------------------------------------------------------------------
# Cross-script source-inspection invariant
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = _REPO_ROOT / "scripts"

# (script relative path, description of the first proxy-consuming construct).
# The first proxy-consuming construct is whatever appears first in main():
#   - LLMManager(...)  → its providers run _initClient() which resolves proxy
#   - Database(...)    → sqlink backend resolves proxy at connect time
#   - ProviderClass(...) → direct provider construction runs _initClient()
#
# Each entry anchors the bootstrapProxy() call to sit strictly between
# ConfigManager(...) (line of last occurrence) and the first proxy consumer.
_PROXY_BOOTSTRAPPING_SCRIPTS: List[Tuple[str, str]] = [
    ("check_image_parsing.py", "LLMManager("),
    ("check_structured_output.py", "LLMManager("),
    ("check_tool_calling.py", "LLMManager("),
    ("check_condensing.py", "Database("),
    ("reproduce_llm_dialog.py", "Database("),
    ("reproduce_layout_extraction.py", "Database("),
    ("run_llm_debug_query.py", "LLMManager("),
    ("list_models.py", "ProviderClass("),
]


def _scriptSource(name: str) -> List[str]:
    """Read a script file and return its lines.

    Args:
        name: Filename relative to ``scripts/`` (e.g. ``check_image_parsing.py``).

    Returns:
        List of source lines (line endings stripped).
    """
    path = _SCRIPTS_DIR / name
    return path.read_text(encoding="utf-8").splitlines()


def _lineNumbersContaining(lines: List[str], needle: str, *, excludeDef: bool = True) -> List[int]:
    """Return zero-based indices of lines containing *needle*.

    Args:
        lines: Source lines to scan.
        needle: Substring to search for.
        excludeDef: When True, skip lines that look like a function/method
            definition (``def foo(``); avoids matching a function named
            e.g. ``def bootstrapProxy`` when searching for ``bootstrapProxy(``.

    Returns:
        Sorted list of zero-based line indices.
    """
    hits: List[int] = []
    for i, ln in enumerate(lines):
        if needle not in ln:
            continue
        if excludeDef and ln.lstrip().startswith("def "):
            continue
        hits.append(i)
    return hits


@pytest.mark.parametrize("scriptName, firstConsumer", _PROXY_BOOTSTRAPPING_SCRIPTS)
def test_scriptImportsBootstrapProxy(scriptName: str, firstConsumer: str) -> None:
    """Every proxy-bootstrapping script must import ``bootstrapProxy`` from ``scripts._lib.bootstrap``.

    Args:
        scriptName: Filename relative to ``scripts/``.
        firstConsumer: Unused here; present so the same parametrize list can
            drive the ordering test. Kept for signature symmetry.
    """
    lines = _scriptSource(scriptName)
    importHits = [i for i, ln in enumerate(lines) if "from scripts._lib.bootstrap import bootstrapProxy" in ln]
    assert importHits, (
        f"{scriptName} must import bootstrapProxy via "
        "'from scripts._lib.bootstrap import bootstrapProxy' — "
        "see scripts/_lib/bootstrap.py for the rationale"
    )


@pytest.mark.parametrize("scriptName, firstConsumer", _PROXY_BOOTSTRAPPING_SCRIPTS)
def test_scriptCallsBootstrapProxy(scriptName: str, firstConsumer: str) -> None:
    """Every proxy-bootstrapping script must actually invoke ``bootstrapProxy(...)``.

    Args:
        scriptName: Filename relative to ``scripts/``.
        firstConsumer: Unused here; present so the same parametrize list can
            drive the ordering test.
    """
    lines = _scriptSource(scriptName)
    callHits = _lineNumbersContaining(lines, "bootstrapProxy(")
    # Filter out the import line itself, which contains "bootstrapProxy(" via "import bootstrapProxy".
    realCallHits = [i for i in callHits if "import" not in lines[i]]
    assert realCallHits, f"{scriptName} must call bootstrapProxy(configManager) somewhere in main()"


@pytest.mark.parametrize("scriptName, firstConsumer", _PROXY_BOOTSTRAPPING_SCRIPTS)
def test_scriptCallsBootstrapProxyBetweenConfigManagerAndFirstConsumer(scriptName: str, firstConsumer: str) -> None:
    """``bootstrapProxy(...)`` must run AFTER ``ConfigManager(...)`` and BEFORE the first proxy consumer.

    This is the exact invariant the helper centralises. If a future change
    moves ``bootstrapProxy(...)`` after ``LLMManager(...)`` (or ``Database(...)``,
    or ``ProviderClass(...)``), every provider / connection fails to init
    with ``TypeError("need to call setGlobalProxyConfig() first")``.

    Args:
        scriptName: Filename relative to ``scripts/``.
        firstConsumer: The substring anchoring the first proxy-consuming
            construct in this script (e.g. ``LLMManager(``).
    """
    lines = _scriptSource(scriptName)

    # Use the LAST ConfigManager( occurrence: that's the real instantiation
    # inside main(), not imports or default-list definitions.
    configManagerHits = [i for i, ln in enumerate(lines) if "ConfigManager(" in ln and "=" in ln and "def " not in ln]
    assert configManagerHits, f"{scriptName}: expected a `configManager = ConfigManager(...)` line"

    configManagerLine = configManagerHits[-1]

    # The first proxy-consumer line strictly AFTER ConfigManager(...).
    consumerHitsAfter = [i for i in _lineNumbersContaining(lines, firstConsumer) if i > configManagerLine]
    assert consumerHitsAfter, (
        f"{scriptName}: expected a `{firstConsumer}` line after ConfigManager(...) at line " f"{configManagerLine + 1}"
    )
    consumerLine = consumerHitsAfter[0]

    # bootstrapProxy(...) must sit strictly between them.
    bootstrapHits = [
        i
        for i in _lineNumbersContaining(lines, "bootstrapProxy(")
        if "import" not in lines[i] and configManagerLine < i < consumerLine
    ]
    assert bootstrapHits, (
        f"{scriptName}: bootstrapProxy(configManager) must be called between "
        f"ConfigManager(...) (line {configManagerLine + 1}) and {firstConsumer} "
        f"(line {consumerLine + 1}); otherwise every provider/connection raises "
        f"TypeError('need to call setGlobalProxyConfig() first')"
    )


# ---------------------------------------------------------------------------
# Cross-script invariant: no script should use the inline setGlobalProxyConfig
# pattern now that the helper exists (ensures full migration).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scriptName, firstConsumer", _PROXY_BOOTSTRAPPING_SCRIPTS)
def test_scriptDoesNotUseInlineSetGlobalProxyConfig(scriptName: str, firstConsumer: str) -> None:
    """No script should reach for ``ProxyHelper`` / ``setGlobalProxyConfig`` directly.

    Once ``bootstrapProxy`` exists, the inline pattern is dead code that
    defeats the helper's centralisation promise. This test fails if a future
    edit reintroduces the inline call (e.g. by reverting an unrelated merge).

    Args:
        scriptName: Filename relative to ``scripts/``.
        firstConsumer: Unused here; present for symmetry with the other
            parametrised tests in this module.
    """
    lines = _scriptSource(scriptName)
    # Allow the word "ProxyHelper" to appear in comments (we leave explanatory
    # comments referencing it). Only flag executable references.
    inlineHits = [
        i
        for i, ln in enumerate(lines)
        if "ProxyHelper" in ln and not ln.lstrip().startswith("#") and "import" not in ln
    ]
    assert not inlineHits, (
        f"{scriptName}: must not reference ProxyHelper directly — use bootstrapProxy() "
        f"from scripts._lib.bootstrap instead. Offending lines: "
        + ", ".join(f"{i + 1}: {lines[i].strip()}" for i in inlineHits)
    )
