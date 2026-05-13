#!/usr/bin/env python3
"""Golden-data collector for the divination feature, dood!

This script drives :func:`lib.aurumentation.collector.collectGoldenData` over
the scenarios defined in ``input/scenarios.json`` and writes the recorded HTTP
traffic plus scenario metadata under ``data/``.

It is meant to be run **locally**, with a real OpenRouter API key in the
environment, by a maintainer who wants to refresh or extend the golden
fixtures. CI never runs this script — replay is handled by
``test_golden.py`` which only reads files under ``data/`` and never makes
network calls.

Usage::

    OPENROUTER_API_KEY=sk-or-... ./venv/bin/python3 tests/divination/golden/collect.py

Optional flags::

    --input <file>   JSON file with scenarios (default: input/scenarios.json)
    --output <dir>   Output directory for fixtures (default: data)
    --secrets <vars> Comma-separated list of env vars whose values should be
                     masked in the recordings (default: OPENROUTER_API_KEY).
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import List

# Add project root to path so ``lib`` and ``tests`` import cleanly when this
# script is run directly (mirrors the pattern in
# ``tests/openweathermap/golden/collect.py``).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from lib import utils  # noqa: E402
from lib.aurumentation.collector import collectGoldenData  # noqa: E402
from lib.aurumentation.types import ScenarioDict  # noqa: E402
from tests.lib_ai.golden.openai_patcher import OpenAIRecorderPatcher  # noqa: E402

# Directory layout — mirrors tests/openweathermap/golden/.
INPUT_DIR: str = "input"
OUTPUT_DIR: str = "data"

# Default scenarios file inside INPUT_DIR.
DEFAULT_SCENARIOS_FILE: str = "scenarios.json"

# Required env var for the default OpenRouter-based scenarios. The collector
# refuses to run if this is missing so we never accidentally hit the LLM with
# a bogus key.
REQUIRED_ENV_VARS: List[str] = ["OPENROUTER_API_KEY"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger: logging.Logger = logging.getLogger("divination_collector")


def checkRequiredEnv() -> bool:
    """Verify that every variable in :data:`REQUIRED_ENV_VARS` is set.

    Returns:
        ``True`` when all required variables are present, ``False`` otherwise.
        On failure, logs a helpful message naming the missing variables.
    """
    missing: List[str] = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        logger.error(
            "Missing required environment variables: %s. "
            "Set them in your shell or in a .env file at the repo root, dood!",
            ", ".join(missing),
        )
        return False
    return True


def collectSecrets(secretsArg: str | None) -> List[str]:
    """Resolve env-var names to their literal secret values for masking.

    Args:
        secretsArg: Comma-separated list of env-var names supplied via the
            ``--secrets`` flag, or ``None`` to fall back to
            :data:`REQUIRED_ENV_VARS`.

    Returns:
        List of literal secret strings to mask in the recordings. Names that
        do not resolve to a value are silently dropped (the env-var existence
        check happens earlier in :func:`checkRequiredEnv`).
    """
    if secretsArg:
        names: List[str] = [name.strip() for name in secretsArg.split(",") if name.strip()]
    else:
        names = list(REQUIRED_ENV_VARS)
    secrets: List[str] = []
    for name in names:
        value: str | None = os.getenv(name)
        if value:
            secrets.append(value)
    return secrets


async def runCollector(scenariosPath: Path, outputPath: Path, secrets: List[str]) -> None:
    """Run :func:`collectGoldenData` over the scenarios in ``scenariosPath``.

    Args:
        scenariosPath: Path to the scenarios JSON file.
        outputPath: Directory to write the recorded fixtures into.
        secrets: List of secret values to mask in the recordings.
    """
    if not scenariosPath.exists():
        raise FileNotFoundError(f"Scenarios file not found: {scenariosPath}, dood!")

    with scenariosPath.open("r", encoding="utf-8") as fh:
        scenarios: List[ScenarioDict] = json.load(fh)

    logger.info("Loaded %d scenarios from %s", len(scenarios), scenariosPath)
    outputPath.mkdir(parents=True, exist_ok=True)

    openAiPatcher: OpenAIRecorderPatcher = OpenAIRecorderPatcher()
    await collectGoldenData(
        scenarios=scenarios,
        outputDir=outputPath,
        secrets=secrets,
        aenterCallback=openAiPatcher.patchOpenAI,
        aexitCallback=openAiPatcher.unpatchOpenAI,
    )


async def main() -> None:
    """Parse CLI arguments and drive :func:`runCollector`.

    Refuses to start when a required env var is missing so we never burn
    quota on accidental runs, dood!
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=(
            "Golden-data collector for the divination feature. "
            "Records the LLM round-trip for every scenario in input/scenarios.json."
        ),
        usage=(
            "\nSet OPENROUTER_API_KEY in your shell or .env file, then:\n"
            "  ./venv/bin/python3 tests/divination/golden/collect.py\n"
            "\n"
            "Recorded fixtures are written to tests/divination/golden/data/."
        ),
    )
    parser.add_argument(
        "--input",
        default=DEFAULT_SCENARIOS_FILE,
        help=f"Scenarios JSON filename inside the {INPUT_DIR}/ directory (default: {DEFAULT_SCENARIOS_FILE})",
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--secrets",
        default=None,
        help=(
            "Comma-separated list of env-var names whose values should be masked "
            "in the recordings (default: " + ",".join(REQUIRED_ENV_VARS) + ")"
        ),
    )
    args: argparse.Namespace = parser.parse_args()

    # Load .env (if any) before checking env vars so .env-only setups work.
    utils.load_dotenv()

    if not checkRequiredEnv():
        sys.exit(1)

    scriptDir: Path = Path(__file__).parent
    scenariosPath: Path = scriptDir / INPUT_DIR / args.input
    outputPath: Path = scriptDir / args.output

    secrets: List[str] = collectSecrets(args.secrets)
    logger.info("Masking %d secret value(s) in recordings", len(secrets))

    await runCollector(scenariosPath, outputPath, secrets)
    logger.info("Golden-data collection complete, dood! Output: %s", outputPath)


if __name__ == "__main__":
    asyncio.run(main())
