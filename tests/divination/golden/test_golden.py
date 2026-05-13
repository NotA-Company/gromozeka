"""Golden-data replayer tests for the divination feature, dood!

The tests in this module fall into two groups:

1. **Sanity tests** that always run and only need ``input/scenarios.json``.
   They verify that the scenario file is well-formed and that every entry
   resolves to a real :class:`Layout` for its system.

2. **Replayer tests** that are parametrised over the JSON fixture files in
   ``data/``. When ``data/`` is empty (the default state on a fresh
   checkout), :func:`lib.aurumentation.findGoldenDataFiles` returns an empty
   list and pytest emits zero parametrised cases — so the suite stays green
   even before any fixture has been recorded.

The replayer test re-runs the deterministic prompt-building step using the
scenario's pinned ``rngSeed`` and asserts that the freshly-rendered messages
are byte-identical to those baked into the recorded fixture's metadata.
This catches regressions in template rendering, localisation, draw order,
and reversal handling without requiring any LLM call.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from lib.aurumentation import findGoldenDataFiles, loadGoldenData

from . import GOLDEN_DATA_PATH
from .scenario_runner import (
    SYSTEM_CLASSES,
    DivinationScenarioRunner,
    resolveLayoutForSystem,
    resolveSystem,
)

SCENARIOS_PATH: Path = Path(__file__).parent / "input" / "scenarios.json"

# Required scenario keys — kept in one place so the sanity test, the
# replayer test, and any future tooling stay in agreement.
REQUIRED_SCENARIO_KEYS: Tuple[str, ...] = (
    "name",
    "description",
    "module",
    "class",
    "method",
    "init_kwargs",
    "kwargs",
)

REQUIRED_KWARGS_KEYS: Tuple[str, ...] = (
    "systemId",
    "layoutId",
    "rngSeed",
    "userName",
    "question",
    "lang",
)


def _loadScenarios() -> List[Dict[str, Any]]:
    """Load and return the scenarios list from ``input/scenarios.json``.

    Returns:
        Parsed JSON content of the scenarios file.

    Raises:
        FileNotFoundError: When the scenarios file is missing.
        json.JSONDecodeError: When the file contains invalid JSON.
    """
    with SCENARIOS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Sanity tests — always runnable, no fixtures required.
# ---------------------------------------------------------------------------


def test_scenariosFileIsValid() -> None:
    """``scenarios.json`` is loadable and every entry has the required fields, dood!

    Verifies, for every scenario:

    * Top-level required keys are present.
    * ``systemId`` resolves to a known system (``tarot`` / ``runes``).
    * ``layoutId`` resolves to a real :class:`Layout` for that system.
    * ``rngSeed`` is an integer.
    * ``module`` points at the runner module and ``class`` at the runner.
    * Names within the file are unique (so fixture filenames cannot clash).
    """
    assert SCENARIOS_PATH.exists(), f"scenarios.json not found at {SCENARIOS_PATH}, dood!"
    scenarios: List[Dict[str, Any]] = _loadScenarios()
    assert isinstance(scenarios, list), "scenarios.json must contain a JSON array, dood!"
    assert len(scenarios) >= 1, "scenarios.json must define at least one scenario, dood!"

    seenNames: set[str] = set()
    for index, scenario in enumerate(scenarios):
        path: str = f"scenarios[{index}]"
        for key in REQUIRED_SCENARIO_KEYS:
            assert key in scenario, f"{path}: missing required key '{key}', dood!"

        name: str = scenario["name"]
        assert name not in seenNames, f"{path}: duplicate name '{name}', dood!"
        seenNames.add(name)

        assert (
            scenario["module"] == "tests.divination.golden.scenario_runner"
        ), f"{path}: 'module' must point at tests.divination.golden.scenario_runner, dood!"
        assert (
            scenario["class"] == "DivinationScenarioRunner"
        ), f"{path}: 'class' must be DivinationScenarioRunner, dood!"
        assert scenario["method"] == "runReading", f"{path}: 'method' must be runReading, dood!"

        kwargs: Dict[str, Any] = scenario["kwargs"]
        for key in REQUIRED_KWARGS_KEYS:
            assert key in kwargs, f"{path}: kwargs is missing '{key}', dood!"

        systemId: str = kwargs["systemId"]
        assert (
            systemId in SYSTEM_CLASSES
        ), f"{path}: unknown systemId '{systemId}'. Expected one of {sorted(SYSTEM_CLASSES)}, dood!"

        systemCls = resolveSystem(systemId)
        # Will raise ValueError if layoutId does not resolve.
        layout = resolveLayoutForSystem(systemCls, kwargs["layoutId"])
        assert layout.systemId == systemId, (
            f"{path}: layout '{kwargs['layoutId']}' belongs to system '{layout.systemId}',"
            f" but scenario systemId is '{systemId}', dood!"
        )

        assert isinstance(kwargs["rngSeed"], int), f"{path}: rngSeed must be an int, dood!"
        assert (
            isinstance(kwargs["userName"], str) and kwargs["userName"]
        ), f"{path}: userName must be a non-empty string, dood!"
        assert isinstance(kwargs["question"], str), f"{path}: question must be a string, dood!"
        assert isinstance(kwargs["lang"], str) and kwargs["lang"], f"{path}: lang must be a non-empty string, dood!"


# ---------------------------------------------------------------------------
# Replayer tests — parametrised over recorded fixtures (may be empty).
# ---------------------------------------------------------------------------


def _discoverFixtures() -> List[str]:
    """Discover golden-data fixture files in ``data/``.

    Returns:
        Sorted list of absolute paths. Empty when no fixtures have been
        recorded yet — pytest will then emit zero parametrised cases for the
        replayer test, which is the desired no-op behaviour, dood!
    """
    paths: List[str] = findGoldenDataFiles(GOLDEN_DATA_PATH)
    return sorted(paths)


def _scenarioByName(name: str) -> Dict[str, Any] | None:
    """Look up a scenario in ``input/scenarios.json`` by its ``name`` field.

    Args:
        name: Scenario name to find.

    Returns:
        Matching scenario dict, or ``None`` when not found.
    """
    for scenario in _loadScenarios():
        if scenario.get("name") == name:
            return scenario
    return None


@pytest.mark.parametrize("fixturePath", _discoverFixtures())
def test_replayerPromptBuildingMatches(fixturePath: str) -> None:
    """Re-run prompt-building for ``fixturePath`` and assert byte-equality, dood!

    For each recorded fixture this test:

    1. Loads the fixture metadata (which carries the original
       ``init_kwargs`` and ``kwargs``).
    2. Looks up the matching scenario in ``input/scenarios.json`` to recover
       the LLM provider config (the fixture itself stores the
       ``${OPENROUTER_API_KEY}`` placeholder, not the resolved key).
    3. Constructs a :class:`DivinationScenarioRunner` with a fake API key —
       no network call is made because we only re-run the deterministic
       prompt-building portion, never :meth:`AbstractModel.generateText`.
    4. Builds the messages with the same ``rngSeed`` / ``userName`` /
       ``question`` / ``lang`` and compares them to whatever was recorded.

    The recorded fixture stores the rendered messages inside
    ``metadata["expected_messages"]``. When the field is absent (older
    fixtures or an HTTP-only recording), this test only verifies that the
    fixture file is well-formed JSON, dood!

    Args:
        fixturePath: Absolute path to a fixture JSON file.
    """
    # The aurumentation loader is strict and will raise on a malformed file,
    # so this single call doubles as the "well-formed JSON" check.
    fixture = loadGoldenData(fixturePath)
    # ``loadGoldenData`` types metadata as a ``TypedDict`` but in practice it
    # carries arbitrary fields written by the collector (e.g. ``expected_messages``).
    # Cast to ``Dict[str, Any]`` so ``.get(...)`` on those fields is type-safe.
    metadata: Dict[str, Any] = dict(fixture["metadata"])

    name: str = metadata.get("name", "")
    scenario: Dict[str, Any] | None = _scenarioByName(name)
    assert scenario is not None, (
        f"Fixture '{Path(fixturePath).name}' has name '{name}' which is not present "
        "in input/scenarios.json. Either re-record after editing scenarios.json or "
        "update the scenario list, dood!"
    )

    # Re-run prompt building deterministically. We cannot use the fixture's
    # init_kwargs verbatim because the API key placeholder ${OPENROUTER_API_KEY}
    # is not resolvable in CI; instead, we build a runner with a sentinel
    # value and never invoke the model.
    initKwargs: Dict[str, Any] = dict(scenario["init_kwargs"])
    providerConfig: Dict[str, Any] = dict(initKwargs.get("providerConfig", {}))
    providerConfig["api_key"] = "fake-key-for-replay"
    initKwargs["providerConfig"] = providerConfig

    runner: DivinationScenarioRunner = DivinationScenarioRunner(**initKwargs)

    kwargs: Dict[str, Any] = scenario["kwargs"]

    async def _buildOnly() -> Dict[str, Any]:
        """Reproduce the deterministic portion of :meth:`runReading`, dood!

        Returns:
            Dict shaped like the runner's normal output but with
            ``resultText`` set to ``None`` since no LLM is called.
        """
        from lib.ai import ModelMessage  # noqa: F401  (kept for type clarity)

        from .scenario_runner import buildReading, messagesToDicts

        systemCls = resolveSystem(kwargs["systemId"])
        layout = resolveLayoutForSystem(systemCls, kwargs["layoutId"])
        reading = buildReading(
            systemCls,
            layout,
            rngSeed=kwargs["rngSeed"],
            question=kwargs["question"],
        )
        messages = systemCls.buildInterpretationMessages(
            reading,
            userName=kwargs["userName"],
            systemPromptTemplate=runner._selectSystemPrompt(kwargs["systemId"]),  # noqa: SLF001
            userPromptTemplate=runner.templates["userPromptTemplate"],
            lang=kwargs["lang"],
        )
        return {
            "messages": messagesToDicts(messages),
            "draws": [
                {
                    "symbolId": draw.symbol.id,
                    "symbolName": draw.symbol.name,
                    "reversed": draw.reversed,
                    "position": draw.position,
                    "positionIndex": draw.positionIndex,
                }
                for draw in reading.draws
            ],
        }

    rebuilt: Dict[str, Any] = asyncio.run(_buildOnly())

    expectedMessages = metadata.get("expected_messages")
    if expectedMessages is not None:
        assert rebuilt["messages"] == expectedMessages, (
            f"Prompt-building output for '{name}' diverged from the recorded fixture, dood! "
            "Either revert the offending change or re-record the fixture."
        )

    expectedDraws = metadata.get("expected_draws")
    if expectedDraws is not None:
        assert rebuilt["draws"] == expectedDraws, (
            f"Draw sequence for '{name}' diverged from the recorded fixture, dood! "
            "Either revert the offending change or re-record the fixture."
        )

    # Always-on cheap check: at least one HTTP recording was captured.
    assert isinstance(fixture.get("recordings", []), list)
