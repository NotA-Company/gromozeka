#!/usr/bin/env ./venv/bin/python3
"""Iterate configured LLM models and probe tool/function-calling support.

Loads the project configuration the same way ``main.py`` does, initialises
``LLMManager``, then calls ``generateText`` on each text-capable model with a
simple weather-forecast tool.  Prints a summary table showing which models
invoke the tool correctly and whether their ``support_tools`` config flag
agrees with observed behaviour.

Usage:
    ./venv/bin/python3 scripts/check_tool_calling.py [flags]

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
    --verbose             Print full conversation history for each model probe:
                          system/user messages sent, tool definitions, assistant
                          response text, tool calls returned, and token usage.

Exit codes:
    0  All flag values are consistent with observed behaviour (or --dry-run).
    1  At least one model has support_tools=true but failed the
       probe (regression — fix the config or the provider).
    2  At least one model has support_tools=false but passed the
       probe (candidate to flip to true — no regressions present).
"""

from __future__ import annotations

import json
import os

# Suppress gRPC C-core (glog) info-level messages like
# "I0514 21:02:59 ... fork_posix.cc:71] Other threads are currently
# calling into gRPC, skipping fork() handlers".  Must be set before
# grpcio is imported; the C extension reads it at module-init time.
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")

import argparse  # noqa: E402 (os.environ.setdefault above is intentional)
import asyncio  # noqa: E402
import dataclasses  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Dict, List, Optional  # noqa: E402

_REPO_ROOT = str(Path(__file__).parent.parent.resolve())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

logging.basicConfig(level=logging.WARNING)
logging.getLogger("grpc").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("openai").setLevel(logging.ERROR)
logging.getLogger("openai._base_client").setLevel(logging.ERROR)

from internal.config.manager import ConfigManager  # noqa: E402
from lib.ai import (  # noqa: E402
    AbstractModel,
    LLMAbstractTool,
    LLMFunctionParameter,
    LLMManager,
    LLMParameterType,
    LLMToolCall,
    LLMToolFunction,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANSI colour helpers
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
# Probe tool definition — fake weather forecast
# ---------------------------------------------------------------------------
def _fakeGetWeather(location: str, unit: str = "celsius") -> str:
    """Return a hardcoded weather forecast string.

    Args:
        location: City name.
        unit: Temperature unit ("celsius" or "fahrenheit").

    Returns:
        A human-readable weather description string.
    """
    forecasts: Dict[str, str] = {
        "celsius": "22°C",
        "fahrenheit": "72°F",
    }
    if unit not in forecasts.keys():
        unit = "celsius"
    return json.dumps(
        {
            "location": location,
            "unit": unit,
            "temperature": forecasts[unit],
            "cloudiness": "sunny",
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )


_WEATHER_TOOL: LLMAbstractTool = LLMToolFunction(
    name="get_current_weather",
    description="Get the current weather in a given location",
    parameters=[
        LLMFunctionParameter(
            name="location",
            description="The city and state, e.g. San Francisco, CA",
            type=LLMParameterType.STRING,
            required=True,
        ),
        LLMFunctionParameter(
            name="unit",
            description="The temperature unit to use. Infer this from the user's location.",
            type=LLMParameterType.STRING,
            required=False,
            extra={"enum": ["celsius", "fahrenheit"]},
        ),
    ],
    function=_fakeGetWeather,
)

_PROBE_MESSAGES: List[ModelMessage] = [
    ModelMessage(
        role="system",
        content=(
            "You are a helpful weather assistant. "
            "When the user asks about weather, always use the get_current_weather tool "
            "to get accurate information. Do not make up weather data."
        ),
    ),
    ModelMessage(
        role="user",
        content="What's the weather like in Minsk right now?",
    ),
]

_PROBE_TOOL_TARGET = "get_current_weather"

_MAX_TOOL_TURNS: int = 5

_PROBE_TIMEOUT_SECONDS: float = 60.0 * 5

# ---------------------------------------------------------------------------
# Classification strings
# ---------------------------------------------------------------------------
CLS_PASS = "PASS"
CLS_NO_TOOL_CALL = "NO_TOOL_CALL"
CLS_WRONG_TOOL = "WRONG_TOOL"
CLS_BAD_PARAMS = "BAD_PARAMS"
CLS_CONTENT_FILTER = "CONTENT_FILTER"
CLS_TIMEOUT = "TIMEOUT"
CLS_API_REJECT = "API_REJECT"
CLS_EXCEPTION = "EXCEPTION"
CLS_DRY_RUN = "DRY-RUN"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ProbeResult:
    """One row of the summary table.

    Attributes:
        provider: Provider name (e.g. ``openrouter``, ``yc-openai``).
        modelName: Registered model key (e.g. ``openrouter/claude-haiku-4.5``).
        flagNow: Current value of ``support_tools`` from config.
        classification: One of the CLS_* constants above.
        details: Short human-readable detail for non-PASS results (≤120 chars).
        elapsed: Wall-clock seconds for the probe call (``None`` for dry-run).
        rawResult: The ``ModelRunResult`` returned by the model (``None`` for
            dry-run / timeout / exception).
        conversationHistory: Full multi-turn message history including the
            initial messages, assistant responses with tool calls, and tool
            results.  Empty for dry-run / timeout / exception.
    """

    provider: str
    modelName: str
    flagNow: bool
    classification: str
    details: str
    elapsed: Optional[float] = None
    rawResult: Optional[ModelRunResult] = None
    conversationHistory: List[ModelMessage] = dataclasses.field(default_factory=list)


# ---------------------------------------------------------------------------
# Classification helper
# ---------------------------------------------------------------------------


def classifyResult(result: ModelRunResult) -> tuple[str, str]:
    """Map a ``ModelRunResult`` to a (classification, details) pair.

    Args:
        result: The result returned by ``generateText`` with the weather tool.

    Returns:
        A 2-tuple ``(classification, details)`` where *classification* is one
        of the ``CLS_*`` module-level constants and *details* is a short
        human-readable explanation (empty string for PASS).
    """
    if result.status == ModelResultStatus.CONTENT_FILTER:
        return CLS_CONTENT_FILTER, "Content filter triggered"

    if result.status == ModelResultStatus.TOOL_CALLS:
        if not result.toolCalls:
            return CLS_NO_TOOL_CALL, "status=TOOL_CALLS but toolCalls list is empty"

        toolCall: LLMToolCall = result.toolCalls[0]
        if toolCall.name != _PROBE_TOOL_TARGET:
            return CLS_WRONG_TOOL, _truncate(f"Expected '{_PROBE_TOOL_TARGET}', got '{toolCall.name}'", 120)

        requiredParams = {"location"}
        missingParams = requiredParams - set(toolCall.parameters.keys())
        if missingParams:
            return CLS_BAD_PARAMS, _truncate(f"Missing required params: {missingParams}", 120)

        return CLS_PASS, ""

    if result.status == ModelResultStatus.FINAL:
        if result.toolCalls:
            toolCall = result.toolCalls[0]
            if toolCall.name == _PROBE_TOOL_TARGET:
                return CLS_PASS, ""
            return CLS_WRONG_TOOL, _truncate(f"Expected '{_PROBE_TOOL_TARGET}', got '{toolCall.name}'", 120)
        return CLS_NO_TOOL_CALL, _truncate(f"Model returned text instead of tool call: {result.resultText!r}", 120)

    if result.status == ModelResultStatus.TRUNCATED_FINAL:
        if result.toolCalls:
            toolCall = result.toolCalls[0]
            if toolCall.name == _PROBE_TOOL_TARGET:
                return CLS_PASS, ""
            return CLS_WRONG_TOOL, _truncate(f"Expected '{_PROBE_TOOL_TARGET}', got '{toolCall.name}'", 120)
        return CLS_NO_TOOL_CALL, "Truncated response, no tool call"

    if result.status == ModelResultStatus.ERROR:
        err = result.error
        if err is None:
            return CLS_EXCEPTION, "status=ERROR but error is None"
        errType = type(err).__name__
        errMsg = str(err)
        lowerMsg = errMsg.lower()
        if any(kw in lowerMsg for kw in ("tool", "function", "parallel_tool_calls")) or "400" in errMsg:
            return CLS_API_REJECT, _truncate(f"{errType}: {errMsg}", 120)
        return CLS_EXCEPTION, _truncate(f"{errType}: {errMsg}", 120)

    if result.status in (ModelResultStatus.UNSPECIFIED, ModelResultStatus.PARTIAL, ModelResultStatus.UNKNOWN):
        return CLS_EXCEPTION, _truncate(f"Unexpected status: {result.status.name}", 120)

    return CLS_EXCEPTION, _truncate(f"Unhandled status: {result.status.name}", 120)


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
    """Run the tool-calling probe against a single model, completing the full
    tool-call loop.

    When the model responds with a tool call, the fake weather function is
    invoked, the result is appended as a ``role=tool`` message, and the model
    is called again — up to ``_MAX_TOOL_TURNS`` times.  This mirrors the
    production loop in ``LLMService`` and allows the verbose output to show
    the complete multi-turn conversation.

    Classification is based on whether the model *invoked the correct tool*
    at any point during the loop — not just on the final text response.

    Temporarily force-enables the ``support_tools`` flag so that the check
    runs even on models currently flagged ``false`` in config.
    Restores the original flag afterwards via ``try/finally``.

    Args:
        modelName: The registered model key used for display.
        model: The ``AbstractModel`` instance to probe.
        providerName: The provider name (e.g. ``openrouter``).

    Returns:
        A populated ``ProbeResult`` dataclass.
    """
    import time

    import lib.utils as utils

    originalFlag: bool = bool(model._config.get("support_tools", False))

    classification: str = CLS_EXCEPTION
    details: str = ""
    elapsed: Optional[float] = None
    rawResult: Optional[ModelRunResult] = None
    conversationHistory: List[ModelMessage] = []

    # Track whether the model successfully called the target tool at any turn
    toolCalledCorrectly: bool = False
    wrongToolName: Optional[str] = None
    missingParams: Optional[set] = None

    model._config["support_tools"] = True
    try:
        messages: List[ModelMessage] = list(_PROBE_MESSAGES)
        start = time.monotonic()

        for turn in range(_MAX_TOOL_TURNS + 1):
            result: ModelRunResult = await asyncio.wait_for(
                model.generateText(
                    messages=messages,
                    tools=[_WEATHER_TOOL],
                ),
                timeout=_PROBE_TIMEOUT_SECONDS,
            )

            # Check for tool calls in this turn
            if result.status == ModelResultStatus.TOOL_CALLS or (
                result.status in (ModelResultStatus.FINAL, ModelResultStatus.TRUNCATED_FINAL) and result.toolCalls
            ):
                # Record assistant message in conversation history
                assistantMsg = result.toModelMessage()
                conversationHistory.append(assistantMsg)
                messages.append(assistantMsg)

                for toolCall in result.toolCalls:
                    if toolCall.name == _PROBE_TOOL_TARGET:
                        toolCalledCorrectly = True
                        requiredParams = {"location"}
                        missing = requiredParams - set(toolCall.parameters.keys())
                        if missing:
                            missingParams = missing
                    else:
                        wrongToolName = toolCall.name

                    # Execute the tool
                    if toolCall.name == _PROBE_TOOL_TARGET:
                        toolRet = _fakeGetWeather(**toolCall.parameters)
                    else:
                        toolRet = utils.jsonDumps(
                            {"error": f"Unknown tool '{toolCall.name}', available: [{_PROBE_TOOL_TARGET}]"}
                        )

                    # Tool result must be a string
                    if not isinstance(toolRet, str):
                        toolRet = utils.jsonDumps(toolRet)

                    toolMsg = ModelMessage(
                        role="tool",
                        content=toolRet,
                        toolCallId=toolCall.id,
                    )
                    conversationHistory.append(toolMsg)
                    messages.append(toolMsg)

                # Keep looping — the model needs to see the tool results
                continue

            # Non-tool-call response (final text, error, etc.) — we're done
            rawResult = result
            elapsed = time.monotonic() - start

            # If the model produced a text answer after tool calls, record it
            if result.status in (ModelResultStatus.FINAL, ModelResultStatus.TRUNCATED_FINAL):
                if result.resultText:
                    conversationHistory.append(result.toModelMessage())

            # Determine classification based on the *entire* conversation
            if toolCalledCorrectly:
                if missingParams:
                    classification = CLS_BAD_PARAMS
                    details = _truncate(f"Missing required params: {missingParams}", 120)
                elif wrongToolName and not toolCalledCorrectly:
                    classification = CLS_WRONG_TOOL
                    details = _truncate(f"Expected '{_PROBE_TOOL_TARGET}', got '{wrongToolName}'", 120)
                else:
                    classification = CLS_PASS
                    details = ""
            elif wrongToolName:
                classification = CLS_WRONG_TOOL
                details = _truncate(f"Expected '{_PROBE_TOOL_TARGET}', got '{wrongToolName}'", 120)
            elif result.status == ModelResultStatus.CONTENT_FILTER:
                classification = CLS_CONTENT_FILTER
                details = "Content filter triggered"
            elif result.status in (ModelResultStatus.FINAL, ModelResultStatus.TRUNCATED_FINAL):
                if result.toolCalls:
                    # Already handled above
                    pass
                classification = CLS_NO_TOOL_CALL
                details = _truncate(f"Model returned text instead of tool call: {result.resultText!r}", 120)
            elif result.status == ModelResultStatus.ERROR:
                if result.error is None:
                    classification = CLS_EXCEPTION
                    details = "status=ERROR but error is None"
                else:
                    errType = type(result.error).__name__
                    errMsg = str(result.error)
                    lowerMsg = errMsg.lower()
                    if any(kw in lowerMsg for kw in ("tool", "function", "parallel_tool_calls")) or "400" in errMsg:
                        classification = CLS_API_REJECT
                    else:
                        classification = CLS_EXCEPTION
                    details = _truncate(f"{errType}: {errMsg}", 120)
            else:
                classification, details = classifyResult(result)

            break

        else:
            # Exhausted _MAX_TOOL_TURNS without a final answer
            rawResult = result
            elapsed = time.monotonic() - start
            if toolCalledCorrectly:
                classification = CLS_PASS
                details = ""
            else:
                classification = CLS_EXCEPTION
                details = f"Exceeded {_MAX_TOOL_TURNS} tool-call turns without final answer"

    except asyncio.TimeoutError:
        classification = CLS_TIMEOUT
        details = f"{int(_PROBE_TIMEOUT_SECONDS)}s timeout"

    except NotImplementedError as exc:
        classification = CLS_EXCEPTION
        details = _truncate(f"NotImplementedError: {exc}", 120)

    except Exception as exc:
        errType = type(exc).__name__
        errMsg = str(exc)
        lowerMsg = errMsg.lower()
        if any(kw in lowerMsg for kw in ("tool", "function", "parallel_tool_calls")) or "400" in errMsg:
            classification = CLS_API_REJECT
        else:
            classification = CLS_EXCEPTION
        details = _truncate(f"{errType}: {errMsg}", 120)

    finally:
        model._config["support_tools"] = originalFlag

    return ProbeResult(
        provider=providerName,
        modelName=modelName,
        flagNow=originalFlag,
        classification=classification,
        details=details,
        elapsed=elapsed,
        rawResult=rawResult,
        conversationHistory=conversationHistory,
    )


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------
_HDR_PROVIDER = "provider"
_HDR_MODEL = "model"
_HDR_FLAG = "flag-now"
_HDR_RESULT = "result"
_HDR_TIME = "time"
_HDR_MATCH = "match"
_HDR_DETAILS = "details"


def _matchMarker(flagNow: bool, classification: str) -> str:
    """Return the ``match`` column string for a result row.

    Args:
        flagNow: Current ``support_tools`` config value.
        classification: The probe classification string.

    Returns:
        A unicode marker string indicating consistency or inconsistency.
    """
    isPassing = classification == CLS_PASS
    if classification == CLS_DRY_RUN:
        return ""
    if flagNow and isPassing:
        return _col("✓", _ANSI_GREEN)
    if not flagNow and not isPassing:
        return _col("✓", _ANSI_GREEN)
    if not flagNow and isPassing:
        return _col("⚠ FLIP TO TRUE", _ANSI_YELLOW)
    return _col("⚠ REGRESSION", _ANSI_RED)


def _formatElapsed(elapsed: Optional[float]) -> str:
    """Format elapsed seconds as a short human-readable string.

    Args:
        elapsed: Seconds, or ``None`` for dry-run / exception.

    Returns:
        A string like ``"5.2s"`` or ``"-"`` when None.
    """
    if elapsed is None:
        return "-"
    return f"{elapsed:.1f}s"


def renderTable(results: List[ProbeResult]) -> str:
    """Render *results* as a plain-text, column-aligned summary table.

    Args:
        results: List of ``ProbeResult`` objects to render.

    Returns:
        A multi-line string suitable for printing to stdout.
    """
    if not results:
        return "(no results)\n"

    elapsedStrs = [_formatElapsed(r.elapsed) for r in results]
    colProvider = max(len(_HDR_PROVIDER), *(len(r.provider) for r in results))
    colModel = max(len(_HDR_MODEL), *(len(r.modelName) for r in results))
    colFlag = max(len(_HDR_FLAG), *(len(str(r.flagNow).lower()) for r in results))
    colResult = max(len(_HDR_RESULT), *(len(r.classification) for r in results))
    colTime = max(len(_HDR_TIME), *(len(e) for e in elapsedStrs))
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
        ),
    )
    colDetails = max(len(_HDR_DETAILS), *(len(r.details) for r in results) if results else [0])
    colDetails = max(colDetails, 7)

    def row(provider: str, model: str, flag: str, result: str, timeStr: str, match: str, details: str) -> str:
        """Format one table row with appropriate padding.

        Args:
            provider: Provider column value.
            model: Model column value.
            flag: Flag-now column value.
            result: Result column value.
            timeStr: Elapsed-time column value.
            match: Match column value (may contain ANSI escapes).
            details: Details column value.

        Returns:
            Formatted row string.
        """
        visibleMatch = match
        for code in (_ANSI_YELLOW, _ANSI_GREEN, _ANSI_RED, _ANSI_RESET):
            visibleMatch = visibleMatch.replace(code, "")
        matchPad = colMatch - len(visibleMatch)

        return (
            f"{provider:<{colProvider}}  "
            f"{model:<{colModel}}  "
            f"{flag:<{colFlag}}  "
            f"{result:<{colResult}}  "
            f"{timeStr:<{colTime}}  "
            f"{match}{' ' * matchPad}  "
            f"{details}"
        )

    sep = (
        f"{'-' * colProvider}  "
        f"{'-' * colModel}  "
        f"{'-' * colFlag}  "
        f"{'-' * colResult}  "
        f"{'-' * colTime}  "
        f"{'-' * colMatch}  "
        f"{'-' * colDetails}"
    )

    lines: List[str] = []
    lines.append(row(_HDR_PROVIDER, _HDR_MODEL, _HDR_FLAG, _HDR_RESULT, _HDR_TIME, _HDR_MATCH, _HDR_DETAILS))
    lines.append(sep)

    for idx, r in enumerate(results):
        flagStr = str(r.flagNow).lower()
        marker = _matchMarker(r.flagNow, r.classification)
        lines.append(row(r.provider, r.modelName, flagStr, r.classification, elapsedStrs[idx], marker, r.details))

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
) -> List[tuple]:
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
    candidates: List[tuple] = []

    for modelName in llmManager.listModels():
        model = llmManager.getModel(modelName)
        if model is None:
            continue

        info = model.getInfo()

        if not info.get("support_text", True):
            continue

        providerName = _providerNameForModel(modelName, llmManager)

        if providerFilter is not None and providerName != providerFilter:
            continue

        if modelFilter is not None and modelName != modelFilter:
            continue

        candidates.append((modelName, model, providerName))

    if limit is not None:
        candidates = candidates[:limit]

    return candidates


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
_DEFAULT_CONFIG_DIRS = ["configs/00-defaults", "configs/local"]


def buildParser() -> argparse.ArgumentParser:
    """Construct and return the argument parser for this script.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        prog="check_tool_calling.py",
        description=(
            "Probe each configured LLM model for tool/function-calling support "
            "and report which models should have support_tools flipped to true "
            "in the config files."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit codes:\n"
            "  0  All flag values are consistent with observed behaviour (or --dry-run).\n"
            "  1  At least one model has support_tools=true but failed the\n"
            "     probe (regression — fix the config or the provider).\n"
            "  2  At least one model has support_tools=false but passed the\n"
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
    parser.add_argument(
        "--verbose",
        action="store_true",
        dest="verbose",
        help="Print full conversation details for each probe: messages sent, "
        "tool definitions, assistant response, tool calls, and token usage.",
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


def _printVerbose(probeResult: ProbeResult) -> None:
    """Print full conversation details for a single probe result.

    Shows the complete multi-turn conversation: initial messages, tool
    definitions, each assistant turn with any tool calls, tool results,
    and the final assistant response, plus token usage.

    Args:
        probeResult: The completed ``ProbeResult`` whose conversation to dump.
    """
    print("  --- verbose ---")
    print(f"  status: {probeResult.classification}")
    print(f"  elapsed: {_formatElapsed(probeResult.elapsed)}")

    # --- Input: messages we sent ---
    print("  messages (input):")
    for i, msg in enumerate(_PROBE_MESSAGES):
        print(f"    [{i}] {msg.toLogMessage(contentLengthLimit=512)}")

    # --- Input: tools we offered ---
    print("  tools (input):")
    print(f"    {_WEATHER_TOOL.toJson()}")

    result = probeResult.rawResult
    if result is None and not probeResult.conversationHistory:
        print("  (no raw result — timeout or exception)")
        print("  --- end verbose ---")
        return

    # --- Full conversation (multi-turn) ---
    if probeResult.conversationHistory:
        print("  conversation:")
        for i, msg in enumerate(probeResult.conversationHistory):
            print(f"    [{i}] {msg.toLogMessage(contentLengthLimit=512)}")

    # --- Token usage (from final result, if available) ---
    if result is not None:
        tokenParts: List[str] = []
        if result.inputTokens is not None:
            tokenParts.append(f"in={result.inputTokens}")
        if result.outputTokens is not None:
            tokenParts.append(f"out={result.outputTokens}")
        if result.totalTokens is not None:
            tokenParts.append(f"total={result.totalTokens}")
        if tokenParts:
            print(f"  tokens: {', '.join(tokenParts)}")

        if result.error is not None:
            print(f"  error: {type(result.error).__name__}: {result.error}")

    print("  --- end verbose ---")


async def main() -> int:
    """Run the tool-calling probe and return the process exit code.

    Returns:
        Integer exit code (0, 1, or 2 — see module docstring).
    """
    args = _parseArgs()

    configDirs: List[str] = args.configDirs if args.configDirs else _DEFAULT_CONFIG_DIRS

    print(f"Loading configs from: {', '.join(configDirs)}")

    configManager = ConfigManager(
        configPath="config.toml",
        configDirs=configDirs,
        dotEnvFile=args.dotenv_file,
    )

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
        flagNow: bool = bool(model._config.get("support_tools", False))

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

        label = f"[{idx}/{total}] {modelName} "
        dotWidth = max(0, 64 - len(label))
        print(label + "." * dotWidth, end=" ", flush=True)

        probeResult = await probeModel(modelName, model, providerName)
        results.append(probeResult)

        elapsedStr = _formatElapsed(probeResult.elapsed)
        print(f"{probeResult.classification} [{elapsedStr}]")

        if args.verbose:
            _printVerbose(probeResult)

    print()
    print("Summary")
    print("-------")
    print(renderTable(results))
    print()

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
