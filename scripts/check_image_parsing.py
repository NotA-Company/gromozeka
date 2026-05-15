#!/usr/bin/env ./venv/bin/python3
"""Iterate configured LLM models and probe image-understanding support.

Loads the project configuration the same way ``main.py`` does, initialises
``LLMManager``, then calls ``generateText`` on each text-capable model with a
user-supplied image and an optional text prompt.  Prints a summary table
showing which models can successfully describe the image and whether their
``support_text`` config flag agrees with observed behaviour.

This emulates the ``_parseImage`` flow in
``internal/bot/common/handlers/base.py`` but without the chat-settings model
resolution — instead, every configured text model is probed directly so you
can see which ones actually handle multimodal input.

Usage:
    ./venv/bin/python3 scripts/check_image_parsing.py [flags] IMAGE_FILE

Flags:
    IMAGE_FILE              Path to the image file to analyse (required).
    --message TEXT         Text prompt to accompany the image.  Defaults to the
                           Russian prompt from bot-defaults.toml:
                           "Подробно опиши, что изображено на изображении.
                            Если есть текст — приведи его."
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
    --verbose             Print full response details for each model probe:
                           raw result text, token usage, and error messages.

Exit codes:
    0  All tested models succeeded (or --dry-run).
    1  At least one model failed to produce a description.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Suppress gRPC C-core (glog) info-level messages like
# "I0514 21:02:59 ... fork_posix.cc:71] Other threads are currently
# calling into gRPC, skipping fork() handlers".  Must be set before
# grpcio is imported; the C extension reads it at module-init time.
# ---------------------------------------------------------------------------
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")

import magic  # noqa: E402 (needed after os.environ.setdefault)

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
    LLMManager,
    ModelImageMessage,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default prompt — matches configs/00-defaults/bot-defaults.toml
# ---------------------------------------------------------------------------
_DEFAULT_PARSE_IMAGE_PROMPT: str = "Подробно опиши, что изображено на изображении. Если есть текст — приведи его."

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
# Classification strings
# ---------------------------------------------------------------------------
CLS_PASS = "PASS"
CLS_NO_TEXT = "NO_TEXT"
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
        flagNow: Current value of ``support_text`` from model config.
        classification: One of the CLS_* constants above.
        details: Short human-readable detail for non-PASS results (<=120 chars).
        elapsed: Wall-clock seconds for the probe call (``None`` for dry-run).
        rawResult: The ``ModelRunResult`` returned by the model (``None`` for
            dry-run / timeout / exception).
        responseText: The text description returned by the model, truncated.
    """

    provider: str
    modelName: str
    flagNow: bool
    classification: str
    details: str
    elapsed: Optional[float] = None
    rawResult: Optional[ModelRunResult] = None
    responseText: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
# Probe logic
# ---------------------------------------------------------------------------

_PROBE_TIMEOUT_SECONDS: float = 60.0 * 5


async def probeModel(
    modelName: str,
    model: AbstractModel,
    providerName: str,
    messages: List[ModelMessage],
) -> ProbeResult:
    """Run the image-parsing probe against a single model.

    Sends the pre-built messages (system prompt + image) to the model and
    checks whether a non-empty text description is returned.

    Temporarily force-enables the ``support_text`` flag so that the check
    runs even on models currently flagged ``false`` in config.
    Restores the original flag afterwards via ``try/finally``.

    Args:
        modelName: The registered model key used for display.
        model: The ``AbstractModel`` instance to probe.
        providerName: The provider name (e.g. ``openrouter``).
        messages: Pre-built list of ModelMessage / ModelImageMessage.

    Returns:
        A populated ``ProbeResult`` dataclass.
    """
    import time

    originalFlag: bool = bool(model._config.get("support_text", True))

    classification: str = CLS_EXCEPTION
    details: str = ""
    elapsed: Optional[float] = None
    rawResult: Optional[ModelRunResult] = None
    responseText: str = ""

    model._config["support_text"] = True
    try:
        start = time.monotonic()
        result: ModelRunResult = await asyncio.wait_for(
            model.generateText(messages=messages),
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
        elapsed = time.monotonic() - start
        rawResult = result
        classification, details = _classifyResult(result)

        if result.resultText:
            responseText = result.resultText

    except asyncio.TimeoutError:
        classification = CLS_TIMEOUT
        details = f"{int(_PROBE_TIMEOUT_SECONDS)}s timeout"

    except Exception as exc:
        errType = type(exc).__name__
        errMsg = str(exc)
        lowerMsg = errMsg.lower()
        if any(kw in lowerMsg for kw in ("image", "vision", "multimodal", "content_type", "400")):
            classification = CLS_API_REJECT
        else:
            classification = CLS_EXCEPTION
        details = _truncate(f"{errType}: {errMsg}", 120)

    finally:
        model._config["support_text"] = originalFlag

    return ProbeResult(
        provider=providerName,
        modelName=modelName,
        flagNow=originalFlag,
        classification=classification,
        details=details,
        elapsed=elapsed,
        rawResult=rawResult,
        responseText=responseText,
    )


def _classifyResult(result: ModelRunResult) -> tuple[str, str]:
    """Map a ``ModelRunResult`` to a (classification, details) pair.

    Args:
        result: The result returned by ``generateText`` with the image prompt.

    Returns:
        A 2-tuple ``(classification, details)`` where *classification* is one
        of the ``CLS_*`` module-level constants and *details* is a short
        human-readable explanation (empty string for PASS).
    """
    if result.status == ModelResultStatus.CONTENT_FILTER:
        return CLS_CONTENT_FILTER, "Content filter triggered"

    if result.status == ModelResultStatus.FINAL:
        if result.resultText and result.resultText.strip():
            return CLS_PASS, ""
        return CLS_NO_TEXT, "Model returned empty or whitespace-only text"

    if result.status == ModelResultStatus.TRUNCATED_FINAL:
        if result.resultText and result.resultText.strip():
            return CLS_PASS, ""
        return CLS_NO_TEXT, "Truncated response with empty text"

    if result.status == ModelResultStatus.ERROR:
        if result.error is None:
            return CLS_EXCEPTION, "status=ERROR but error is None"
        errType = type(result.error).__name__
        errMsg = str(result.error)
        lowerMsg = errMsg.lower()
        if any(kw in lowerMsg for kw in ("image", "vision", "multimodal", "content_type", "400")):
            return CLS_API_REJECT, _truncate(f"{errType}: {errMsg}", 120)
        return CLS_EXCEPTION, _truncate(f"{errType}: {errMsg}", 120)

    if result.status in (ModelResultStatus.UNSPECIFIED, ModelResultStatus.PARTIAL, ModelResultStatus.UNKNOWN):
        return CLS_EXCEPTION, _truncate(f"Unexpected status: {result.status.name}", 120)

    return CLS_EXCEPTION, _truncate(f"Unhandled status: {result.status.name}", 120)


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------
_HDR_PROVIDER = "provider"
_HDR_MODEL = "model"
_HDR_FLAG = "text"
_HDR_RESULT = "result"
_HDR_TIME = "time"
_HDR_MATCH = "match"
_HDR_DETAILS = "details"


def _matchMarker(flagNow: bool, classification: str) -> str:
    """Return the ``match`` column string for a result row.

    Args:
        flagNow: Current ``support_text`` config value.
        classification: The probe classification string.

    Returns:
        A unicode marker string indicating success or failure.
    """
    isPassing = classification == CLS_PASS
    if classification == CLS_DRY_RUN:
        return ""
    if isPassing:
        return _col("✓", _ANSI_GREEN)
    return _col("✗", _ANSI_RED)


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

    for r in results:
        flagStr = str(r.flagNow).lower()
        marker = _matchMarker(r.flagNow, r.classification)
        lines.append(
            row(r.provider, r.modelName, flagStr, r.classification, elapsedStrs[results.index(r)], marker, r.details)
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Exit-code helper
# ---------------------------------------------------------------------------


def computeExitCode(results: List[ProbeResult]) -> int:
    """Compute the process exit code from the list of probe results.

    Args:
        results: Completed ``ProbeResult`` objects.

    Returns:
        0 if all models passed (or ``--dry-run`` was used).
        1 if at least one model failed to produce an image description.
    """
    if any(r.classification == CLS_DRY_RUN for r in results):
        return 0
    if any(r.classification != CLS_PASS for r in results):
        return 1
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
    1. ``support_text == True`` (skip image-generation-only models).
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
        prog="check_image_parsing.py",
        description=(
            "Probe each configured LLM model for image-understanding support "
            "by sending a user-supplied image.  Prints a summary table showing "
            "which models can successfully describe the image content."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit codes:\n"
            "  0  All tested models succeeded (or --dry-run).\n"
            "  1  At least one model failed to produce an image description.\n"
        ),
    )
    parser.add_argument(
        "image_file",
        metavar="IMAGE_FILE",
        help="Path to the image file to analyse (JPEG, PNG, GIF, WebP, etc.).",
    )
    parser.add_argument(
        "--message",
        default="",
        help=("Text prompt to accompany the image."),
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
        help="Print full response details for each probe: response text, token usage, and errors.",
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
    """Print full response details for a single probe result.

    Shows the model's response text, token usage, and any errors.

    Args:
        probeResult: The completed ``ProbeResult`` whose details to dump.
    """
    print("  --- verbose ---")
    print(f"  status: {probeResult.classification}")
    print(f"  elapsed: {_formatElapsed(probeResult.elapsed)}")

    if probeResult.responseText:
        print(f"  response ({len(probeResult.responseText)} chars):")
        print(f"    {probeResult.responseText[:2000]}")

    result = probeResult.rawResult
    if result is None:
        print("  (no raw result — timeout or exception)")
        print("  --- end verbose ---")
        return

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
    """Run the image-parsing probe and return the process exit code.

    Returns:
        Integer exit code (0 or 1 — see module docstring).
    """
    args = _parseArgs()

    imageFilePath = Path(args.image_file)
    if not imageFilePath.is_file():
        print(f"Error: image file not found: {imageFilePath}", file=sys.stderr)
        return 1

    imageData: bytes = imageFilePath.read_bytes()
    mimeType: str = magic.from_buffer(imageData, mime=True)

    if not mimeType.lower().startswith("image/"):
        print(f"Error: file does not appear to be an image (detected MIME: {mimeType})", file=sys.stderr)
        return 1

    print(f"Image: {imageFilePath.name} ({mimeType}, {len(imageData):,} bytes)")
    print(f"Extra prompt: {args.message!r}")

    messages: List[ModelMessage] = [
        ModelMessage(
            role="system",
            content=_DEFAULT_PARSE_IMAGE_PROMPT,
        ),
        ModelImageMessage(
            role="user",
            content=args.message,
            image=bytearray(imageData),
        ),
    ]

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
        flagNow: bool = bool(model._config.get("support_text", True))

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

        probeResult = await probeModel(modelName, model, providerName, messages)
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

    passCount = sum(1 for r in results if r.classification == CLS_PASS)
    failCount = sum(1 for r in results if r.classification != CLS_PASS and r.classification != CLS_DRY_RUN)

    exitCode = computeExitCode(results)

    if args.dryRun:
        print(f"Dry-run complete. {len(results)} model(s) would be tested. Exit code: 0.")
    elif exitCode == 0:
        print(f"Result: all {passCount} model(s) produced a description. Exit code: 0.")
    else:
        print(f"Result: {failCount} model(s) failed out of {len(results)} tested. Exit code: 1.")

    return exitCode


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
