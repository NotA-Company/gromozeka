#!/usr/bin/env ./venv/bin/python3
"""Iterate configured LLM models and probe structured-output support, dood.

Loads the project configuration the same way ``main.py`` does, initialises
``LLMManager``, then calls ``generateStructured`` on each text-capable model
with a tiny JSON Schema.  Prints a summary table showing which models pass
and whether their ``support_structured_output`` config flag agrees with reality.

Usage:
    ./venv/bin/python3 scripts/check_structured_output.py [flags]

Flags:
    --config-dir DIR      Directory to load .toml config files from (can be
                          specified multiple times, same as main.py).
                          Default: --config-dir configs/00-defaults
                                   --config-dir configs/local
    --dotenv-file FILE    Path to .env file with env variables for substitute
                          in configs.  Default: .env
    --provider NAME       Only test models from this provider (e.g. 'openrouter',
                          'yc-openai').
    --model NAME          Only test this exact model key (e.g.
                          'openrouter/claude-haiku-4.5').  Additive with
                          --provider: if both are given only models that satisfy
                          both filters are included.
    --dry-run             List what *would* be tested without making any API calls.
    --limit N             Cap the number of models tested per run.

Exit codes:
    0  All flag values are consistent with observed behaviour (or --dry-run).
    1  At least one model has support_structured_output=true but failed the
       probe (regression — fix the config or the provider).
    2  At least one model has support_structured_output=false but passed the
       probe (candidate to flip to true — no regressions present).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Ensure the repository root is on sys.path so that project packages
# (internal/, lib/) are importable when the script is run as:
#     ./venv/bin/python3 scripts/check_structured_output.py
# In that invocation Python adds scripts/ to sys.path, not the repo root.
# ---------------------------------------------------------------------------
_REPO_ROOT = str(Path(__file__).parent.parent.resolve())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Silence noisy libraries before importing project code.
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("openai").setLevel(logging.ERROR)
logging.getLogger("openai._base_client").setLevel(logging.ERROR)

from internal.config.manager import ConfigManager  # noqa: E402
from lib.ai import AbstractModel, LLMManager, ModelMessage, ModelResultStatus, ModelStructuredResult  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANSI colour helpers (used only when stdout is a TTY)
# ---------------------------------------------------------------------------
_ANSI_YELLOW = "\033[33m"
_ANSI_GREEN = "\033[32m"
_ANSI_RED = "\033[31m"
_ANSI_RESET = "\033[0m"

_USE_COLOR: bool = sys.stdout.isatty()


def _col(text: str, code: str) -> str:
    """Wrap *text* in ANSI *code* when colour output is enabled.

    Args:
        text: The string to colourise.
        code: An ANSI escape sequence (e.g. ``_ANSI_YELLOW``).

    Returns:
        Colourised string when stdout is a TTY, plain *text* otherwise.
    """
    if _USE_COLOR:
        return f"{code}{text}{_ANSI_RESET}"
    return text


# ---------------------------------------------------------------------------
# Probe schema & messages — tiny and self-contained
# ---------------------------------------------------------------------------
# OpenAI strict-mode JSON Schema requires every property to also be listed
# in `required`, and `additionalProperties` to be False. YC OpenAI's native
# models (yandexgpt, aliceai-llm, deepseek-v32) enforce this strictly and
# return HTTP 400 "Invalid JSON Schema: all fields must be required" when
# violated. To probe every provider portably, this schema lists ALL
# properties as required.
# Reference: https://platform.openai.com/docs/guides/structured-outputs#all-fields-must-be-required
_PROBE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["answer", "confidence"],
    "additionalProperties": False,
}

_PROBE_MESSAGES: List[ModelMessage] = [
    ModelMessage(
        role="system",
        content="Respond with a JSON object matching the provided schema, dood.",
    ),
    ModelMessage(
        role="user",
        content="What is 2+2? Reply with the answer as a string and an optional confidence value.",
    ),
]

_PROBE_TIMEOUT_SECONDS: float = 60.0 * 5

# ---------------------------------------------------------------------------
# Classification strings
# ---------------------------------------------------------------------------
CLS_PASS = "PASS"
CLS_PARSE_FAIL = "PARSE_FAIL"
CLS_API_REJECT = "API_REJECT"
CLS_CONTENT_FILTER = "CONTENT_FILTER"
CLS_TIMEOUT = "TIMEOUT"
CLS_EXCEPTION = "EXCEPTION"
CLS_NO_DATA = "NO_DATA"
CLS_WRONG_SHAPE = "WRONG_SHAPE"
CLS_DRY_RUN = "DRY-RUN"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ProbeResult:
    """One row of the summary table, dood.

    Attributes:
        provider: Provider name (e.g. ``openrouter``, ``yc-openai``).
        modelName: Registered model key (e.g. ``openrouter/claude-haiku-4.5``).
        flagNow: Current value of ``support_structured_output`` from config.
        classification: One of the CLS_* constants above.
        details: Short human-readable detail for non-PASS results (≤60 chars).
    """

    provider: str
    modelName: str
    flagNow: bool
    classification: str
    details: str


# ---------------------------------------------------------------------------
# Classification helper
# ---------------------------------------------------------------------------


def classifyResult(result: ModelStructuredResult) -> tuple[str, str]:
    """Map a ``ModelStructuredResult`` to a (classification, details) pair.

    Args:
        result: The structured-output result returned by the model.

    Returns:
        A 2-tuple ``(classification, details)`` where *classification* is one
        of the ``CLS_*`` module-level constants and *details* is a short
        human-readable explanation (empty string for PASS).
    """
    status = result.status

    if status == ModelResultStatus.CONTENT_FILTER:
        return CLS_CONTENT_FILTER, "Content filter triggered"

    if status in (ModelResultStatus.FINAL, ModelResultStatus.TRUNCATED_FINAL):
        if result.data is None:
            return CLS_NO_DATA, "Status FINAL but data is None (empty response?)"
        if not isinstance(result.data, dict):
            return CLS_WRONG_SHAPE, f"data is {type(result.data).__name__}, expected dict"
        if "answer" not in result.data:
            keys = list(result.data.keys())
            return CLS_WRONG_SHAPE, f"'answer' not in data; keys={keys}"
        return CLS_PASS, ""

    if status == ModelResultStatus.ERROR:
        err = result.error
        if err is None:
            return CLS_EXCEPTION, "status=ERROR but error is None"
        errType = type(err).__name__
        errMsg = str(err)
        # JSON / value decode failure
        if isinstance(err, (json.JSONDecodeError, ValueError)):
            logging.warning(f"Got {result.resultText} instead of JSON")
            return CLS_PARSE_FAIL, _truncate(f"{errType}: {errMsg}", 60)
        # Provider rejected the schema / bad request
        lowerMsg = errMsg.lower()
        if any(kw in lowerMsg for kw in ("response_format", "json_schema", "badrequest")) or "400" in errMsg:
            return CLS_API_REJECT, _truncate(f"{errType}: {errMsg}", 60)
        return CLS_EXCEPTION, _truncate(f"{errType}: {errMsg}", 60)

    # Any other status (UNSPECIFIED, UNKNOWN, PARTIAL, TOOL_CALLS …)
    return CLS_EXCEPTION, _truncate(f"Unexpected status: {status.name}", 60)


def _truncate(text: str, maxLen: int) -> str:
    """Truncate *text* to at most *maxLen* characters, appending '…' if cut.

    Args:
        text: The input string.
        maxLen: Maximum allowed length including the ellipsis character.

    Returns:
        Possibly-truncated string.
    """
    if len(text) <= maxLen:
        return text
    return text[: maxLen - 1] + "…"


# ---------------------------------------------------------------------------
# Model probing
# ---------------------------------------------------------------------------


async def probeModel(modelName: str, model: AbstractModel, providerName: str) -> ProbeResult:
    """Run the structured-output probe against a single model.

    Temporarily force-enables the ``support_structured_output`` flag so that
    the check runs even on models currently flagged ``false`` in config.
    Restores the original flag afterwards via ``try/finally``.

    Args:
        modelName: The registered model key used for display.
        model: The ``AbstractModel`` instance to probe.
        providerName: The provider name (e.g. ``openrouter``).

    Returns:
        A populated ``ProbeResult`` dataclass.
    """
    originalFlag: bool = bool(model._config.get("support_structured_output", False))

    classification: str = CLS_EXCEPTION
    details: str = ""

    model._config["support_structured_output"] = True
    try:
        result: ModelStructuredResult = await asyncio.wait_for(
            model.generateStructured(
                messages=_PROBE_MESSAGES,
                schema=_PROBE_SCHEMA,
                schemaName="checkResponse",
                strict=True,
            ),
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
        classification, details = classifyResult(result)

    except asyncio.TimeoutError:
        classification = CLS_TIMEOUT
        details = f"{int(_PROBE_TIMEOUT_SECONDS)}s timeout"

    except NotImplementedError as exc:
        classification = CLS_EXCEPTION
        details = _truncate(f"NotImplementedError: {exc}", 60)

    except Exception as exc:
        errType = type(exc).__name__
        errMsg = str(exc)
        lowerMsg = errMsg.lower()
        if any(kw in lowerMsg for kw in ("response_format", "json_schema", "badrequest")) or "400" in errMsg:
            classification = CLS_API_REJECT
        else:
            classification = CLS_EXCEPTION
        details = _truncate(f"{errType}: {errMsg}", 60)

    finally:
        model._config["support_structured_output"] = originalFlag

    return ProbeResult(
        provider=providerName,
        modelName=modelName,
        flagNow=originalFlag,
        classification=classification,
        details=details,
    )


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------

# Column header labels
_HDR_PROVIDER = "provider"
_HDR_MODEL = "model"
_HDR_FLAG = "flag-now"
_HDR_RESULT = "result"
_HDR_MATCH = "match"
_HDR_DETAILS = "details"


def _matchMarker(flagNow: bool, classification: str) -> str:
    """Return the ``match`` column string for a result row.

    Args:
        flagNow: Current ``support_structured_output`` config value.
        classification: The probe classification string.

    Returns:
        A unicode marker string indicating consistency or inconsistency.
    """
    isPassing = classification == CLS_PASS
    if classification == CLS_DRY_RUN:
        return ""
    if flagNow and isPassing:
        return _col("✓", _ANSI_GREEN)  # consistent: flag=true, works
    if not flagNow and not isPassing:
        return _col("✓", _ANSI_GREEN)  # consistent: flag=false, fails
    if not flagNow and isPassing:
        return _col("⚠ FLIP TO TRUE", _ANSI_YELLOW)  # flag=false but works!
    # flagNow=true but not passing → regression
    return _col("⚠ REGRESSION", _ANSI_RED)


def renderTable(results: List[ProbeResult]) -> str:
    """Render *results* as a plain-text, column-aligned summary table.

    Column widths are computed from the actual data so that even long model
    names (e.g. ``openrouter/qwen3-vl-235b-a22b-instruct``) are accommodated.

    Args:
        results: List of ``ProbeResult`` objects to render.

    Returns:
        A multi-line string suitable for printing to stdout.
    """
    if not results:
        return "(no results)\n"

    # Compute column widths — minimum = header width, expand to fit data
    colProvider = max(len(_HDR_PROVIDER), *(len(r.provider) for r in results))
    colModel = max(len(_HDR_MODEL), *(len(r.modelName) for r in results))
    colFlag = max(len(_HDR_FLAG), *(len(str(r.flagNow).lower()) for r in results))
    colResult = max(len(_HDR_RESULT), *(len(r.classification) for r in results))
    # match column is variable (ANSI codes inflate length); use plain-text width
    colMatch = max(
        len(_HDR_MATCH),
        *(
            len(
                _matchMarker(r.flagNow, r.classification)
                .replace(_ANSI_YELLOW, "")
                .replace(_ANSI_GREEN, "")
                .replace(_ANSI_RED, "")
                .replace(_ANSI_RESET, "")
            )
            for r in results
        ),  # noqa: E501
    )
    colDetails = max(len(_HDR_DETAILS), *(len(r.details) for r in results) if results else [0])
    colDetails = max(colDetails, 7)  # at least "details" width

    def row(provider: str, model: str, flag: str, result: str, match: str, details: str) -> str:
        """Format one table row with appropriate padding.

        Args:
            provider: Provider column value.
            model: Model column value.
            flag: Flag-now column value.
            result: Result column value.
            match: Match column value (may contain ANSI escapes).
            details: Details column value.

        Returns:
            Formatted row string.
        """
        # For the match column we need to pad based on *visible* length
        # (ANSI codes are zero-width for display purposes).
        visibleMatch = match
        for code in (_ANSI_YELLOW, _ANSI_GREEN, _ANSI_RED, _ANSI_RESET):
            visibleMatch = visibleMatch.replace(code, "")
        matchPad = colMatch - len(visibleMatch)

        return (
            f"{provider:<{colProvider}}  "
            f"{model:<{colModel}}  "
            f"{flag:<{colFlag}}  "
            f"{result:<{colResult}}  "
            f"{match}{' ' * matchPad}  "
            f"{details}"
        )

    sep = (
        f"{'-' * colProvider}  "
        f"{'-' * colModel}  "
        f"{'-' * colFlag}  "
        f"{'-' * colResult}  "
        f"{'-' * colMatch}  "
        f"{'-' * colDetails}"
    )

    lines: List[str] = []
    lines.append(row(_HDR_PROVIDER, _HDR_MODEL, _HDR_FLAG, _HDR_RESULT, _HDR_MATCH, _HDR_DETAILS))
    lines.append(sep)

    for r in results:
        flagStr = str(r.flagNow).lower()
        marker = _matchMarker(r.flagNow, r.classification)
        lines.append(row(r.provider, r.modelName, flagStr, r.classification, marker, r.details))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Exit-code helper
# ---------------------------------------------------------------------------


def computeExitCode(results: List[ProbeResult]) -> int:
    """Compute the process exit code from the list of probe results.

    Args:
        results: Completed ``ProbeResult`` objects.

    Returns:
        0 if everything is consistent or ``--dry-run`` was used.
        1 if any model with ``flag=true`` failed (regression).
        2 if any model with ``flag=false`` passed (candidates to flip), no regressions.
    """
    hasRegression = any(r.flagNow and r.classification != CLS_PASS for r in results)
    hasFlipCandidate = any(not r.flagNow and r.classification == CLS_PASS for r in results)

    if any(r.classification == CLS_DRY_RUN for r in results):
        return 0
    if hasRegression:
        return 1
    if hasFlipCandidate:
        return 2
    return 0


# ---------------------------------------------------------------------------
# Model enumeration helpers
# ---------------------------------------------------------------------------


def _providerNameForModel(modelName: str, llmManager: LLMManager) -> str:
    """Look up the provider name for a registered model key.

    Args:
        modelName: The model's registered key (e.g. ``openrouter/claude-haiku-4.5``).
        llmManager: Initialised ``LLMManager`` instance.

    Returns:
        The provider name string, or ``"unknown"`` if not found.
    """
    return llmManager.modelRegistry.get(modelName, "unknown")


def _filterModels(
    llmManager: LLMManager,
    providerFilter: Optional[str],
    modelFilter: Optional[str],
    limit: Optional[int],
) -> List[tuple[str, AbstractModel, str]]:
    """Build the list of (modelName, model, providerName) triples to test.

    Applies the following filters in order:
    1. ``support_text == True`` (skip image-only models).
    2. ``--provider`` filter (if provided).
    3. ``--model`` filter (if provided).
    4. ``--limit`` cap (if provided).

    Args:
        llmManager: Initialised ``LLMManager``.
        providerFilter: Optional provider name to restrict to.
        modelFilter: Optional exact model key to restrict to.
        limit: Optional maximum number of models to return.

    Returns:
        List of ``(modelName, model, providerName)`` triples, ready for probing.
    """
    candidates: List[tuple[str, AbstractModel, str]] = []

    for modelName in llmManager.listModels():
        model = llmManager.getModel(modelName)
        if model is None:
            continue

        info = model.getInfo()

        # 1. Text-capable only
        if not info.get("support_text", True):
            continue

        providerName = _providerNameForModel(modelName, llmManager)

        # 2. Provider filter
        if providerFilter is not None and providerName != providerFilter:
            continue

        # 3. Model filter
        if modelFilter is not None and modelName != modelFilter:
            continue

        candidates.append((modelName, model, providerName))

    # 4. Limit
    if limit is not None:
        candidates = candidates[:limit]

    return candidates


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_DIRS = ["configs/00-defaults", "configs/local"]


def buildParser() -> argparse.ArgumentParser:
    """Construct and return the argument parser for this script.

    Extracted from ``_parseArgs`` so that tests can exercise the parser
    without triggering ``sys.argv`` parsing.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        prog="check_structured_output.py",
        description=(
            "Probe each configured LLM model for structured-output (JSON Schema) support "
            "and report which models should have support_structured_output flipped to true "
            "in the config files, dood."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit codes:\n"
            "  0  All flag values are consistent with observed behaviour (or --dry-run).\n"
            "  1  At least one model has support_structured_output=true but failed the\n"
            "     probe (regression — fix the config or the provider).\n"
            "  2  At least one model has support_structured_output=false but passed the\n"
            "     probe (candidate to flip to true — no regressions present).\n"
        ),
    )
    parser.add_argument(
        "--config-dir",
        action="append",
        dest="configDirs",
        metavar="DIR",
        help=(
            "Directory to load .toml config files from (can be specified multiple times). "
            f"Default: {' '.join('--config-dir ' + d for d in _DEFAULT_CONFIG_DIRS)}"
        ),
    )
    parser.add_argument(
        "--dotenv-file",
        default=".env",
        help="Path to .env file with env variables for substitute in configs",
    )
    parser.add_argument(
        "--provider",
        metavar="NAME",
        default=None,
        help="Only test models from this provider (e.g. 'openrouter', 'yc-openai').",
    )
    parser.add_argument(
        "--model",
        metavar="NAME",
        default=None,
        help="Only test this exact model key (e.g. 'openrouter/claude-haiku-4.5').",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dryRun",
        help="List what would be tested without making any API calls. Exit 0.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Cap the number of models tested per run.",
    )
    return parser


def _parseArgs() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Populated ``argparse.Namespace``.
    """
    return buildParser().parse_args()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def main() -> int:
    """Run the structured-output probe tool and return the process exit code.

    Returns:
        Integer exit code (0, 1, or 2 — see module docstring).
    """
    args = _parseArgs()

    configDirs: List[str] = args.configDirs if args.configDirs else _DEFAULT_CONFIG_DIRS

    print(f"Loading configs from: {', '.join(configDirs)}")

    # Load config — same pattern as main.py; we pass a non-existent configPath
    # so ConfigManager falls through to the directory-based loading.
    configManager = ConfigManager(
        configPath="config.toml",  # may not exist; dirs take precedence
        configDirs=configDirs,
        dotEnvFile=args.dotenv_file,
    )

    # Initialise LLM manager
    llmManager = LLMManager(configManager.getModelsConfig())

    totalModels = len(llmManager.listModels())
    candidates = _filterModels(
        llmManager,
        providerFilter=args.provider,
        modelFilter=args.model,
        limit=args.limit,
    )
    textCapable = sum(
        1
        for name in llmManager.listModels()
        if (m := llmManager.getModel(name)) and m.getInfo().get("support_text", True)
    )

    # Build filter description
    filters: List[str] = []
    if args.provider:
        filters.append(f"provider={args.provider!r}")
    if args.model:
        filters.append(f"model={args.model!r}")
    if args.limit:
        filters.append(f"limit={args.limit}")
    filterDesc = ", ".join(filters) if filters else "no filters applied"

    print(
        f"Found {totalModels} configured models, {textCapable} text-capable, "
        f"testing {len(candidates)} ({filterDesc}).\n"
    )

    if not candidates:
        print("No models to test. Exiting.")
        return 0

    results: List[ProbeResult] = []

    total = len(candidates)
    for idx, (modelName, model, providerName) in enumerate(candidates, start=1):
        flagNow: bool = bool(model._config.get("support_structured_output", False))

        if args.dryRun:
            print(f"[{idx}/{total}] {modelName} (dry-run — no API call)")
            results.append(
                ProbeResult(
                    provider=providerName,
                    modelName=modelName,
                    flagNow=flagNow,
                    classification=CLS_DRY_RUN,
                    details="",
                )
            )
            continue

        # Pad model name with dots up to a fixed column for readability
        label = f"[{idx}/{total}] {modelName} "
        dotWidth = max(0, 64 - len(label))
        print(label + "." * dotWidth, end=" ", flush=True)

        probeResult = await probeModel(modelName, model, providerName)
        results.append(probeResult)

        print(probeResult.classification)

    print()
    print("Summary")
    print("-------")
    print(renderTable(results))
    print()

    # Final summary line
    flipCount = sum(1 for r in results if not r.flagNow and r.classification == CLS_PASS)
    regressionCount = sum(1 for r in results if r.flagNow and r.classification != CLS_PASS)

    exitCode = computeExitCode(results)

    if args.dryRun:
        print(f"Dry-run complete. {len(results)} model(s) would be tested. Exit code: 0.")
    elif exitCode == 0:
        print("Result: all flags consistent with observed behaviour. Exit code: 0.")
    elif exitCode == 1:
        print(f"Result: {regressionCount} regression(s) detected " f"(flag=true but probe failed). Exit code: 1.")
    elif exitCode == 2:
        print(f"Result: {flipCount} candidate(s) ready to flip to true. Exit code: 2.")

    return exitCode


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
