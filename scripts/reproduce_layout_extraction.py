#!/usr/bin/env ./venv/bin/python3
"""Emulate the ``_extractLayoutFromText`` method from ``DivinationHandler``.

Initialises all needed services (config, DB, cache, LLM manager/service),
loads chat settings, builds the same structured-output prompt that
``DivinationHandler._extractLayoutFromText`` constructs, calls
``LLMService.generateStructured()``, and dumps the resulting JSON to stdout.

This script does NOT persist anything to the database — it is a read-level
debugging / experimentation tool.

Usage:
    echo "A detailed layout description..." | \\
        ./venv/bin/python3 scripts/reproduce_layout_extraction.py \\
        --chat-id 135824779 \\
        --system-id tarot \\
        --layout-name "Celtic Cross" \\
        --model-name openrouter/deepseek-v4-pro \\
        --config-dir configs/00-defaults \\
        --config-dir configs/local \\
        --dotenv-file .env.local-telegram

    # Or pass a model that supports structured output:
    echo "Three cards in a row: past, present, future" | \\
        ./venv/bin/python3 scripts/reproduce_layout_extraction.py \\
        --chat-id 135824779 \\
        --system-id runes \\
        --layout-name "Three Runes" \\
        --model-name openrouter/gemini-2.5-flash \\
        --config-dir configs/00-defaults \\
        --config-dir configs/local \\
        --dotenv-file .env.local-telegram

Exit codes:
    0  Success — JSON written to stdout
    1  Error (missing arguments, service init failure, LLM error)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Ensure the repository root is on sys.path so that project packages
# (internal/, lib/) are importable when the script is run as:
#     ./venv/bin/python3 scripts/reproduce_layout_extraction.py
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

from internal.bot.models import ChatSettingsKey, ChatSettingsValue, ChatTier, ChatType  # noqa: E402
from internal.config.manager import ConfigManager  # noqa: E402
from internal.database import Database  # noqa: E402
from internal.services.cache import CacheService  # noqa: E402
from internal.services.llm.service import LLMService  # noqa: E402
from lib.ai import ModelMessage  # noqa: E402
from lib.ai.manager import LLMManager  # noqa: E402
from lib.rate_limiter import RateLimiterManager  # noqa: E402

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# Default config directories (same as main.py and sibling scripts)
# ---------------------------------------------------------------------------
_DEFAULT_CONFIG_DIRS = ["configs/00-defaults", "configs/local"]

# Valid system IDs
_VALID_SYSTEM_IDS = {"tarot", "runes"}


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def buildParser() -> argparse.ArgumentParser:
    """Construct and return the argument parser for this script.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        prog="reproduce_layout_extraction.py",
        description=(
            "Emulate DivinationHandler._extractLayoutFromText: load chat settings, "
            "build the structured-output prompt, call the LLM, and dump the parsed JSON."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  echo "Description here..." | '
            "./venv/bin/python3 scripts/reproduce_layout_extraction.py \\\n"
            "      --chat-id 135824779 \\\n"
            "      --system-id tarot \\\n"
            '      --layout-name "Celtic Cross" \\\n'
            "      --model-name openrouter/deepseek-v4-pro \\\n"
            "      --config-dir configs/00-defaults \\\n"
            "      --config-dir configs/local \\\n"
            "      --dotenv-file .env.local-telegram\n\n"
            "  # Pass --verbose to see DEBUG output (model details, etc.)\n"
            '  echo "Description here..." | '
            "./venv/bin/python3 scripts/reproduce_layout_extraction.py \\\n"
            "      --chat-id 135824779 \\\n"
            "      --system-id runes \\\n"
            '      --layout-name "Three Runes" \\\n'
            "      --model-name openrouter/gemini-2.5-flash \\\n"
            "      --verbose\n"
        ),
    )
    parser.add_argument(
        "--chat-id",
        type=int,
        required=True,
        help="Chat ID for retrieving chat settings (positive = private, negative = group).",
    )
    parser.add_argument(
        "--system-id",
        required=True,
        choices=sorted(_VALID_SYSTEM_IDS),
        help='Divination system: "tarot" or "runes".',
    )
    parser.add_argument(
        "--layout-name",
        required=True,
        help='Raw layout name as the user would type it (e.g. "Celtic Cross"). Used both in the prompt and logging.',
    )
    parser.add_argument(
        "--model-name",
        required=True,
        help=(
            "Model name to use for the structured output call. "
            "This model MUST support structured output. "
            "Passed directly to LLMService.generateStructured's modelKey parameter."
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
        help="Path to .env file with env variables for config substitution. Default: .env",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging from the script itself.",
    )
    return parser


def _parseArgs() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Populated ``argparse.Namespace``.
    """
    return buildParser().parse_args()


# ---------------------------------------------------------------------------
# Chat settings loading (mirrors HandlersManager._initDefaultChatSettings
# + BaseBotHandler.getChatSettings merge logic)
# ---------------------------------------------------------------------------


async def loadDefaultChatSettings(cache: CacheService, configManager: ConfigManager) -> None:
    """Load global, per-chat-type, and tier defaults into cache.

    Mirrors the logic in ``HandlersManager._initDefaultChatSettings``
    (manager.py lines 391-420).

    Args:
        cache: The CacheService singleton.
        configManager: The ConfigManager instance.
    """
    botConfig = configManager.getBotConfig()

    # Global defaults
    defaultSettings: Dict[ChatSettingsKey, ChatSettingsValue] = {k: ChatSettingsValue("") for k in ChatSettingsKey}
    defaultSettings.update(
        {
            ChatSettingsKey(k): ChatSettingsValue(v)
            for k, v in botConfig.get("defaults", {}).items()
            if k in ChatSettingsKey
        }
    )
    cache.setDefaultChatSettings(None, defaultSettings)

    # Per-chat-type defaults
    for chatType in ChatType:
        cache.setDefaultChatSettings(
            chatType,
            {
                ChatSettingsKey(k): ChatSettingsValue(v)
                for k, v in botConfig.get(f"{chatType.value}-defaults", {}).items()
                if k in ChatSettingsKey
            },
        )

    # Tier defaults
    tierDefaultsDict = botConfig.get("tier-defaults", {})
    for chatTier in ChatTier:
        cache.setDefaultChatSettings(
            f"tier-{chatTier}",
            {
                ChatSettingsKey(k): ChatSettingsValue(v)
                for k, v in tierDefaultsDict.get(chatTier, {}).items()
                if k in ChatSettingsKey
            },
        )


async def getMergedChatSettings(cache: CacheService, chatId: int) -> Dict[ChatSettingsKey, ChatSettingsValue]:
    """Merge global, per-chat-type, and DB-override settings for *chatId*.

    Mirrors the logic in ``reproduce_llm_dialog.py`` lines 332-339.

    Args:
        cache: The CacheService singleton (with defaults already loaded).
        chatId: The chat ID to retrieve settings for.

    Returns:
        Merged ``ChatSettingsDict``.
    """
    chatSettingsFromDb = await cache.getChatSettings(chatId)

    chatSettings: Dict[ChatSettingsKey, ChatSettingsValue] = dict(cache.getDefaultChatSettings(None))
    chatType = ChatType.PRIVATE if chatId > 0 else ChatType.GROUP
    chatSettings.update(cache.getDefaultChatSettings(chatType))
    chatSettings.update(chatSettingsFromDb)

    return chatSettings


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def main() -> int:
    """Emulate ``DivinationHandler._extractLayoutFromText`` and dump the result.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    args = _parseArgs()

    if args.verbose:
        logging.getLogger(__name__).setLevel(logging.DEBUG)

    configDirs: List[str] = args.configDirs if args.configDirs else _DEFAULT_CONFIG_DIRS

    # ------------------------------------------------------------------
    # 1. Read layoutDescription from stdin
    # ------------------------------------------------------------------
    if sys.stdin.isatty():
        print("Error: layout description must be piped via stdin (no interactive input).", file=sys.stderr)
        print("Usage example:", file=sys.stderr)
        print(
            '  echo "Your layout description..." | ./venv/bin/python3 scripts/reproduce_layout_extraction.py ...',
            file=sys.stderr,
        )
        sys.exit(1)

    layoutDescription = sys.stdin.read().strip()
    if not layoutDescription:
        print("Error: layout description from stdin is empty.", file=sys.stderr)
        sys.exit(1)

    logger.debug(f"Read layoutDescription from stdin ({len(layoutDescription)} chars)")

    # ------------------------------------------------------------------
    # 2. Init ConfigManager, Database, CacheService, LLMManager, LLMService
    # ------------------------------------------------------------------
    configManager = ConfigManager(
        configPath="config.toml",
        configDirs=configDirs,
        dotEnvFile=args.dotenv_file,
    )

    db = Database(configManager.getDatabaseConfig())  # pyright: ignore[reportArgumentType]
    llmManager = LLMManager(configManager.getModelsConfig())

    cache = CacheService.getInstance()
    await cache.injectDatabase(db)

    llmService = LLMService.getInstance()
    llmService.injectLLMManager(llmManager)

    # ------------------------------------------------------------------
    # 3. Initialize rate limiter manager (mirrors main.py line 68)
    # ------------------------------------------------------------------
    rateLimiterManager = RateLimiterManager.getInstance()
    await rateLimiterManager.loadConfig(configManager.getRateLimiterConfig())

    # ------------------------------------------------------------------
    # 4. Load default chat settings into cache
    # ------------------------------------------------------------------
    await loadDefaultChatSettings(cache, configManager)

    # ------------------------------------------------------------------
    # 5. Resolve the model object to use as modelKey
    # ------------------------------------------------------------------
    model = llmManager.getModel(args.model_name)
    if model is None:
        availableModels = llmManager.listModels()
        print(f"Error: Model '{args.model_name}' not found in configuration.", file=sys.stderr)
        print(f"Available models: {', '.join(availableModels)}", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # 6. Get merged chat settings
    # ------------------------------------------------------------------
    chatSettings = await getMergedChatSettings(cache, args.chat_id)

    systemPrompt = chatSettings[ChatSettingsKey.DIVINATION_PARSE_STRUCTURE_SYSTEM_PROMPT].toStr()
    userPromptTemplate = chatSettings[ChatSettingsKey.DIVINATION_PARSE_STRUCTURE_PROMPT].toStr()

    if not systemPrompt:
        print("Warning: DIVINATION_PARSE_STRUCTURE_SYSTEM_PROMPT is empty — LLM may not know what to do.")
    if not userPromptTemplate:
        print("Warning: DIVINATION_PARSE_STRUCTURE_PROMPT is empty — cannot format user prompt.")
        return 1

    # ------------------------------------------------------------------
    # 7. Build structureMessages (mirrors _extractLayoutFromText lines 1104-1119)
    # ------------------------------------------------------------------
    structureMessages = [
        ModelMessage(
            role="system",
            content=systemPrompt,
        ),
        ModelMessage(
            role="user",
            content=userPromptTemplate.format(
                layoutName=args.layout_name,
                systemId=args.system_id,
                description=layoutDescription,
            ),
        ),
    ]

    # ------------------------------------------------------------------
    # 8. Call LLMService.generateStructured
    # ------------------------------------------------------------------
    logger.debug(f"Calling generateStructured with model={args.model_name}, systemId={args.system_id}")
    logger.debug(f"System prompt ({len(systemPrompt)} chars): {systemPrompt[:200]}...")
    logger.debug(f"User prompt ({len(structureMessages[1].content)} chars): {structureMessages[1].content[:200]}...")

    schema = {
        "type": "object",
        "properties": {
            "layout_id": {"type": "string"},
            "name_en": {"type": "string"},
            "name_ru": {"type": "string"},
            "positions": {
                "type": "array",
                "items": {
                    "type": "string",
                },
            },
            "description": {"type": "string"},
        },
        "required": ["layout_id", "name_en", "name_ru", "positions", "description"],
        "additionalProperties": False,
    }

    structuredRet = await llmService.generateStructured(
        prompt=structureMessages,
        schema=schema,
        chatId=args.chat_id,
        chatSettings=dict(chatSettings),
        modelKey=model,
        fallbackKey=ChatSettingsKey.FALLBACK_MODEL,
    )

    # ------------------------------------------------------------------
    # 9. Dump result to stdout
    # ------------------------------------------------------------------
    output: Dict[str, Any] = {
        "status": structuredRet.status.name,
        "input_tokens": structuredRet.inputTokens,
        "output_tokens": structuredRet.outputTokens,
        "total_tokens": structuredRet.totalTokens,
        "model": args.model_name,
        "system_id": args.system_id,
        "layout_name": args.layout_name,
        "elapsed_time": structuredRet.elapsedTime,
    }

    if structuredRet.error:
        output["error"] = str(structuredRet.error)
        output["raw_text"] = structuredRet.resultText

    if structuredRet.data is not None:
        output["data"] = structuredRet.data

    # Print only JSON to stdout so it can be piped to jq etc.
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    print()  # trailing newline

    # ------------------------------------------------------------------
    # 10. Cleanup
    # ------------------------------------------------------------------
    await db.manager.closeAll()

    if structuredRet.error or structuredRet.status.name not in ("FINAL",):
        logger.error(f"Structured call failed: status={structuredRet.status.name}, error={structuredRet.error}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
