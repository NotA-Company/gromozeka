#!/usr/bin/env python3
"""Golden-data collector for the Yandex SpeechKit STT provider.

This script drives :func:`lib.aurumentation.collector.collectGoldenData` over
the scenarios defined in ``input/scenarios.json`` and writes the recorded HTTP
traffic plus scenario metadata under ``data/``.

It is meant to be run **locally**, with real Yandex SpeechKit credentials in
the environment, by a maintainer who wants to record or refresh the golden
fixtures. CI never runs this script — replay is handled by ``test_golden.py``
which only reads files under ``data/`` and never makes network calls.

Recording this data resolves the STT feature's **release gate-1** (capture the
real ``getRecognition`` wire framing — the highest-risk PROVISIONAL
known-unknown, ``docs/plans/lib-stt-v1.md`` §7.3 / §13.3). After recording,
inspect the recorded ``getRecognition`` response bytes in the ``data/*.json``
fixtures vs ``_resolveEnvelope`` in ``lib/stt/providers/yandex_events.py``.
If the real framing differs from the PROVISIONAL assumption (the optional
top-level ``result`` wrapper), adjust the parser + the unit fixtures.

Prerequisites::

    1. Set credentials:
         export YANDEX_API_KEY=<your Api-Key>
         export YANDEX_FOLDER_ID=<your folder ID>
       (or put them in a ``.env`` file at the repo root.)

    2. Provide short voice clips:
         input/sample.ogg      (Russian speech — scenario 1)
         input/sample_en.ogg   (English speech — scenario 2)
       Any supported container is fine (OGG_OPUS, MP3, WAV, or even a
       transcode-triggering one like M4A — the fixture captures the
       post-extraction bytes either way; replay is format-agnostic). Keep them
       short (< 30 s): the audio content is embedded (base64) in the committed
       fixtures, so the recording clip's voice data lives in the repo.

    3. Run:
         ./venv/bin/python3 tests/lib/stt/golden/collect.py

    4. Verify no secrets leaked into the fixtures (the SecretMasker masks the
       API key, but double-check):
         grep -r "$YANDEX_API_KEY" tests/lib/stt/golden/data/

    5. Inspect the ``getRecognition`` response body in each fixture and compare
       its framing to ``_resolveEnvelope`` in yandex_events.py (gate-1).

Optional flags::

    --input <file>   JSON file with scenarios (default: scenarios.json)
    --output <dir>   Output directory for fixtures (default: data)
    --secrets <vars> Comma-separated list of env vars whose values should be
                     masked in the recordings (default: YANDEX_API_KEY,
                     YANDEX_FOLDER_ID).
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import List

# ---------------------------------------------------------------------------
# Ensure the repository root is on sys.path so that project packages (lib/)
# are importable when the script is run as:
#     ./venv/bin/python3 tests/lib/stt/golden/collect.py
# In that invocation Python adds the script's directory to sys.path, not the
# repo root. This mirrors the pattern used by every script in scripts/.
# ---------------------------------------------------------------------------
_REPO_ROOT = str(Path(__file__).resolve().parents[4])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lib import utils  # noqa: E402
from lib.aurumentation.collector import collectGoldenData  # noqa: E402
from lib.aurumentation.types import ScenarioDict  # noqa: E402

# Directory layout — mirrors tests/lib/divination/golden/ and
# tests/lib/yandex_search/golden/.
INPUT_DIR: str = "input"
OUTPUT_DIR: str = "data"

# Default scenarios file inside INPUT_DIR.
DEFAULT_SCENARIOS_FILE: str = "scenarios.json"

# Required env vars for the default Yandex SpeechKit scenarios. The collector
# refuses to run if either is missing so we never accidentally hit the API with
# a bogus key (a billable operation).
REQUIRED_ENV_VARS: List[str] = ["YANDEX_API_KEY", "YANDEX_FOLDER_ID"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger: logging.Logger = logging.getLogger("stt_golden_collector")


def checkRequiredEnv() -> bool:
    """Verify that every variable in :data:`REQUIRED_ENV_VARS` is set.

    Returns:
        ``True`` when all required variables are present, ``False`` otherwise.
        On failure, logs a helpful message naming the missing variables.
    """
    missing: List[str] = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        logger.error(
            "Missing required environment variables: %s. Set them in your shell or in a .env file at the repo root",
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

    Raises:
        FileNotFoundError: When the scenarios file does not exist.
    """
    if not scenariosPath.exists():
        raise FileNotFoundError(f"Scenarios file not found: {scenariosPath}")

    with scenariosPath.open("r", encoding="utf-8") as fh:
        scenarios: List[ScenarioDict] = json.load(fh)

    logger.info("Loaded %d scenarios from %s", len(scenarios), scenariosPath)
    outputPath.mkdir(parents=True, exist_ok=True)

    await collectGoldenData(
        scenarios=scenarios,
        outputDir=outputPath,
        secrets=secrets,
    )


async def main() -> None:
    """Parse CLI arguments and drive :func:`runCollector`.

    Refuses to start when a required env var is missing so we never burn Yandex
    quota on an accidental run with no credentials.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=(
            "Golden-data collector for the Yandex SpeechKit STT provider. "
            "Records the submit -> poll -> getRecognition -> delete lifecycle "
            "for every scenario in input/scenarios.json."
        ),
        usage=(
            "\nSet YANDEX_API_KEY and YANDEX_FOLDER_ID in your shell or .env file, then:\n"
            "  ./venv/bin/python3 tests/lib/stt/golden/collect.py\n"
            "\n"
            "Recorded fixtures are written to tests/lib/stt/golden/data/."
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
    logger.info("Golden-data collection complete. Output: %s", outputPath)

    # LOUD privacy warning: the recorded recognizeFileAsync POST body embeds the
    # FULL audio content as base64 inside each committed data/*.json fixture.
    # Unlike the API key (which the SecretMasker scrubs), the audio bytes are
    # NOT masked — they are what replay needs to recover. This means whatever
    # voice data was in the recording clips is now in the repo, in cleartext
    # base64. The maintainer MUST confirm they used throwaway/synthetic clips
    # (NOT personal voice, NOT identifiable speech) before committing.
    print("\n")
    print("=" * 79)
    print("PRIVACY WARNING — AUDIO EMBEDDED IN COMMITTED FIXTURES")
    print("=" * 79)
    print(
        "Each data/*.json fixture contains the FULL audio content of the recording\n"
        "clip, embedded as base64 in the recognizeFileAsync POST request body. This\n"
        "audio is NOT masked (it cannot be — replay needs it). Before committing:\n"
        "\n"
        "  CONFIRM that every recording clip was throwaway/synthetic — NOT personal\n"
        "  voice, NOT identifiable speech, NOT anything you would not publish.\n"
        "\n"
        "If any clip contained personal/identifiable voice, DELETE the fixtures and\n"
        "re-record with synthetic audio. Committed audio cannot be meaningfully\n"
        "recalled once pushed."
    )
    print("=" * 79)
    print("\n")

    logger.info(
        "Gate-1 follow-up: inspect the getRecognition response body in each "
        "data/*.json fixture vs _resolveEnvelope in lib/stt/providers/yandex_events.py."
    )


if __name__ == "__main__":
    asyncio.run(main())
