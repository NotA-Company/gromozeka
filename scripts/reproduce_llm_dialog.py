#!/usr/bin/env ./venv/bin/python3
"""Reproduce the exact ModelMessages the bot builds for dialog compaction.

Fetches chat messages from the database, reconstructs EnsuredMessage objects,
applies user data and chat settings, and builds the same deque of ModelMessages
that the production LLM handler assembles (lines 714-755 of llm_messages.py).
Outputs the result as YAML that can be fed into ``scripts/run_llm_debug_query.py``.

This script does NOT call the LLM — it stops after building the message list,
making it safe for debugging without incurring API costs.

Usage:
    ./venv/bin/python3 scripts/reproduce_llm_dialog.py \\
        --chat-id 135824779 \\
        --since-datetime "2026-05-10T03:12:06" \\
        --config-dir configs/00-defaults \\
        --config-dir configs/local \\
        --dotenv-file .env.local-telegram \\
        --output debug_scenario.yaml

Exit codes:
    0  Success — YAML written to --output path
    1  Error (missing dependency, DB failure, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:
    import yaml
except ImportError:
    print(
        "PyYAML is required. Install it with: ./venv/bin/pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Ensure the repository root is on sys.path so that project packages
# (internal/, lib/) are importable when the script is run as:
#     ./venv/bin/python3 scripts/reproduce_llm_dialog.py
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

from internal.bot import constants  # noqa: E402
from internal.bot.models import (  # noqa: E402
    ChatSettingsKey,
    ChatSettingsValue,
    ChatTier,
    ChatType,
    EnsuredMessage,
    LLMMessageFormat,
)
from internal.config.manager import ConfigManager  # noqa: E402
from internal.database import Database  # noqa: E402
from internal.database.models import MessageCategory  # noqa: E402
from internal.services.cache import CacheService  # noqa: E402
from lib.ai import ModelMessage  # noqa: E402
from lib.ai.manager import LLMManager  # noqa: E402

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# Default config directories (same as main.py and check_structured_output.py)
# ---------------------------------------------------------------------------
_DEFAULT_CONFIG_DIRS = ["configs/00-defaults", "configs/local"]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def buildParser() -> argparse.ArgumentParser:
    """Construct and return the argument parser for this script.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        prog="reproduce_llm_dialog.py",
        description=(
            "Reproduce the exact ModelMessages the bot builds for dialog compaction "
            "and output them as YAML for debugging. Does NOT call the LLM."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Reproduce dialog for a private chat since a specific date\n"
            "  ./venv/bin/python3 scripts/reproduce_llm_dialog.py \\\n"
            "      --chat-id 135824779 \\\n"
            "      --since-datetime '2026-05-10T03:12:06' \\\n"
            "      --config-dir configs/00-defaults \\\n"
            "      --config-dir configs/local \\\n"
            "      --dotenv-file .env.local-telegram \\\n"
            "      --output debug_scenario.yaml\n\n"
            "  # Reproduce dialog for a date range (since and till)\n"
            "  ./venv/bin/python3 scripts/reproduce_llm_dialog.py \\\n"
            "      --chat-id 135824779 \\\n"
            "      --since-datetime '2026-05-10T03:12:06' \\\n"
            "      --till-datetime '2026-05-11T00:00:00' \\\n"
            "      --output date_range.yaml\n\n"
            "  # Reproduce dialog up to a specific date (till only)\n"
            "  ./venv/bin/python3 scripts/reproduce_llm_dialog.py \\\n"
            "      --chat-id -1001234567890 \\\n"
            "      --till-datetime '2026-05-10T12:00:00' \\\n"
            "      --output till_only.yaml\n\n"
            "  # Skip a specific message ID (e.g. the triggering message)\n"
            "  ./venv/bin/python3 scripts/reproduce_llm_dialog.py \\\n"
            "      --chat-id -1001234567890 \\\n"
            "      --since-datetime '2026-05-10T03:12:06' \\\n"
            "      --skip-message-id 42 \\\n"
            "      --output group_chat.yaml\n"
        ),
    )
    parser.add_argument(
        "--chat-id",
        type=int,
        required=True,
        help="Chat ID to fetch messages for (positive for private, negative for group).",
    )
    parser.add_argument(
        "--since-datetime",
        default=None,
        help=(
            "ISO 8601 start datetime for getChatMessagesSince's sinceDateTime parameter. "
            "If no timezone is specified, UTC is assumed. "
            'Example: "2026-05-10T03:12:06" or "2026-05-10T03:12:06+03:00". '
            "At least one of --since-datetime or --till-datetime is required."
        ),
    )
    parser.add_argument(
        "--till-datetime",
        default=None,
        help=(
            "ISO 8601 end datetime for getChatMessagesSince's tillDateTime parameter. "
            "If no timezone is specified, UTC is assumed. "
            'Example: "2026-05-11T00:00:00" or "2026-05-11T00:00:00+03:00". '
            "At least one of --since-datetime or --till-datetime is required."
        ),
    )
    parser.add_argument(
        "--thread-id",
        type=int,
        default=0,
        help="Thread ID for the chat (default: 0, meaning no thread).",
    )
    parser.add_argument(
        "--skip-message-id",
        type=int,
        default=None,
        help=(
            "Message ID to skip from the context (matches the triggering-message "
            "skip logic in llm_messages.py line 721)."
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
        "--output",
        default="reproduced_dialog.yaml",
        help="Path to write the YAML output. Default: reproduced_dialog.yaml",
    )
    return parser


def _parseDatetime(raw: Optional[str], paramName: str) -> Optional[datetime]:
    """Parse an ISO 8601 datetime string, defaulting naive values to UTC.

    Args:
        raw: Raw datetime string from the CLI, or ``None`` if the arg was omitted.
        paramName: Name of the CLI argument (used in error messages).

    Returns:
        Timezone-aware ``datetime`` if *raw* was provided, or ``None`` if *raw*
        was ``None``.

    Raises:
        SystemExit: If *raw* is not a valid ISO 8601 datetime.
    """
    if raw is None:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        print(f"Error: --{paramName} is not a valid ISO 8601 datetime: {raw!r}", file=sys.stderr)
        sys.exit(1)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


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
    """Reproduce the LLM dialog context and write it to YAML.

    Follows the same logic as ``LLMMessageHandler._buildContextMessages``
    (llm_messages.py lines 714-755) but without calling the LLM.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    args = _parseArgs()

    configDirs: List[str] = args.configDirs if args.configDirs else _DEFAULT_CONFIG_DIRS
    # Resolve to absolute before ConfigManager changes the working directory
    outputPath = Path(args.output).resolve()

    # ------------------------------------------------------------------
    # 1. Parse since-datetime and till-datetime
    # ------------------------------------------------------------------
    sinceDatetime: Optional[datetime] = _parseDatetime(args.since_datetime, "since-datetime")
    tillDatetime: Optional[datetime] = _parseDatetime(args.till_datetime, "till-datetime")

    if sinceDatetime is None and tillDatetime is None:
        print("Error: at least one of --since-datetime or --till-datetime is required.", file=sys.stderr)
        sys.exit(1)

    print(f"Reproducing LLM dialog context for chat {args.chat_id}")
    print(f"  since: {sinceDatetime.isoformat() if sinceDatetime else '(not set)'}")
    print(f"  till:  {tillDatetime.isoformat() if tillDatetime else '(not set)'}")
    print(f"  thread: {args.thread_id}")
    if args.skip_message_id is not None:
        print(f"  skip message ID: {args.skip_message_id}")
    print(f"  config dirs: {', '.join(configDirs)}")
    print(f"  output: {outputPath}")
    print()

    # ------------------------------------------------------------------
    # 2. Init ConfigManager, Database, CacheService
    # ------------------------------------------------------------------
    configManager = ConfigManager(
        configPath="config.toml",
        configDirs=configDirs,
        dotEnvFile=args.dotenv_file,
    )

    db = Database(configManager.getDatabaseConfig())  # pyright: ignore[reportArgumentType]
    #  Do not used for now
    _ = LLMManager(configManager.getModelsConfig())
    cache = CacheService.getInstance()
    await cache.injectDatabase(db)

    # ------------------------------------------------------------------
    # 3. Load default chat settings into cache (replicate manager.py 397-426)
    # ------------------------------------------------------------------
    botConfig = configManager.getBotConfig()

    # Global defaults (manager.py line 397-405)
    defaultSettings: Dict[ChatSettingsKey, ChatSettingsValue] = {k: ChatSettingsValue("") for k in ChatSettingsKey}
    defaultSettings.update(
        {
            ChatSettingsKey(k): ChatSettingsValue(v)
            for k, v in botConfig.get("defaults", {}).items()
            if k in ChatSettingsKey
        }
    )
    cache.setDefaultChatSettings(None, defaultSettings)

    # Per-chat-type defaults (manager.py line 407-415)
    for chatType in ChatType:
        cache.setDefaultChatSettings(
            chatType,
            {
                ChatSettingsKey(k): ChatSettingsValue(v)
                for k, v in botConfig.get(f"{chatType.value}-defaults", {}).items()
                if k in ChatSettingsKey
            },
        )

    # Tier defaults (manager.py line 417-426)
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

    # ------------------------------------------------------------------
    # 4. Get chat settings (merge global → per-type → DB overrides)
    # ------------------------------------------------------------------
    chatSettingsFromDb = await cache.getChatSettings(args.chat_id)

    chatSettings: Dict[ChatSettingsKey, ChatSettingsValue] = dict(cache.getDefaultChatSettings(None))
    chatType = ChatType.PRIVATE if args.chat_id > 0 else ChatType.GROUP
    chatSettings.update(cache.getDefaultChatSettings(chatType))

    # Override with DB settings
    chatSettings.update(chatSettingsFromDb)

    # Extract the settings we need
    llmMessageFormat = LLMMessageFormat(
        chatSettings.get(ChatSettingsKey.LLM_MESSAGE_FORMAT, ChatSettingsValue("smart")).toStr()
    )
    condensingPrompt = chatSettings.get(ChatSettingsKey.CONDENSING_PROMPT, ChatSettingsValue("")).toStr()
    condensingModel = chatSettings.get(ChatSettingsKey.CONDENSING_MODEL, ChatSettingsValue("")).toStr()

    print(f"Chat type: {chatType.value}")
    print(f"LLM message format: {llmMessageFormat.value}")
    print(f"Condensing prompt: {condensingPrompt[:80]}{'...' if len(condensingPrompt) > 80 else ''}")
    print(f"Condensing model: {condensingModel or '(not set)'}")
    print()

    # ------------------------------------------------------------------
    # 5. Fetch chat messages (exactly as llm_messages.py line 714-720)
    # ------------------------------------------------------------------
    chatMessages = await db.chatMessages.getChatMessagesSince(
        chatId=args.chat_id,
        threadId=args.thread_id,
        limit=constants.RANDOM_ANSWER_CONTEXT_LENGTH,
        sinceDateTime=sinceDatetime,
        tillDateTime=tillDatetime,
    )

    print(f"Fetched {len(chatMessages)} messages from DB")

    # ------------------------------------------------------------------
    # 6. Build contextMessages deque (exactly as llm_messages.py 721-755)
    # ------------------------------------------------------------------
    contextMessages: deque[ModelMessage] = deque()

    for storedMsg in chatMessages:
        # Skip the triggering message (line 721-723)
        if args.skip_message_id is not None and storedMsg["message_id"] == args.skip_message_id:
            continue

        # Reconstruct EnsuredMessage (line 724)
        eMsg = await EnsuredMessage.fromDBChatMessage(storedMsg, db)

        # _updateEMessageUserData (line 725, replicates base.py lines 366-377)
        userData = await cache.getChatUserData(chatId=args.chat_id, userId=eMsg.sender.id)
        eMsg.setUserData(userData)

        # Drop randomContext to not add it to metadata (for triggering condencing)
        if eMsg.metadata.get("randomContext", None) is not None:
            eMsg.metadata.pop("randomContext", None)
            logger.info(f"Removed randomContext from message {eMsg.messageId}")

        # Convert to ModelMessage (lines 731-738)
        messages = await eMsg.toModelMessageList(
            db,
            format=llmMessageFormat,
            role=MessageCategory.fromStr(storedMsg["message_category"]).toRole(),
        )
        contextMessages.extendleft(reversed(messages))

        # Not needed to ensure proper recondensing
        # # Check for existing randomContext (lines 740-743)
        # if eMsg.metadata.get("randomContext", None) is not None:
        #     break

    # If > MAX_RANDOM_CONTEXT_MESSAGES, prepend CONDENSING_PROMPT (lines 745-756)
    if len(contextMessages) > constants.MAX_RANDOM_CONTEXT_MESSAGES:
        contextMessages.appendleft(
            ModelMessage(
                role="system",
                content=condensingPrompt,
            )
        )

    print(f"Built {len(contextMessages)} ModelMessages")
    if len(contextMessages) > constants.MAX_RANDOM_CONTEXT_MESSAGES:
        print(
            f"  (exceeds MAX_RANDOM_CONTEXT_MESSAGES={constants.MAX_RANDOM_CONTEXT_MESSAGES}, "
            f"condensing prompt prepended)"
        )

    # ------------------------------------------------------------------
    # 7. Output to YAML
    # ------------------------------------------------------------------
    output = {
        "meta": {
            "chat_id": args.chat_id,
            "thread_id": args.thread_id,
            "since_datetime": sinceDatetime.isoformat() if sinceDatetime else None,
            "till_datetime": tillDatetime.isoformat() if tillDatetime else None,
            "skip_message_id": args.skip_message_id,
            "message_count": len(contextMessages),
            "max_random_context_messages": constants.MAX_RANDOM_CONTEXT_MESSAGES,
            "limit": constants.RANDOM_ANSWER_CONTEXT_LENGTH,
            "llm_message_format": llmMessageFormat.value,
        },
        "model": condensingModel,
        "request": [msg.toDict("content") for msg in list(contextMessages)],
    }

    outputPath.parent.mkdir(parents=True, exist_ok=True)

    # Use literal block style (|) for multiline strings — same as convert_llm_log_to_readable.py
    def _representStr(dumper, data):
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    yaml.add_representer(str, _representStr)

    with open(outputPath, "w", encoding="utf-8") as f:
        yaml.dump(output, f, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120)

    print(f"\nYAML written to: {outputPath}")
    print(f"  Messages: {len(contextMessages)}")
    print(f"  Model: {condensingModel or '(not set)'}")

    # ------------------------------------------------------------------
    # 8. Cleanup
    # ------------------------------------------------------------------
    await db.manager.closeAll()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
