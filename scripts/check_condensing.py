#!/usr/bin/env ./venv/bin/python3
"""Evaluate LLM context-condensing quality on a real chat thread.

Given a chat ID and a message ID belonging to a reply thread, this script
fetches the full thread from the database, builds the same ModelMessage list
that ``BaseBotHandler.getThreadByMessageForLLM`` assembles, and runs
``LLMService.condenseContext`` on it. The BEFORE (raw thread) and AFTER
(condensed) states are printed side-by-side so prompt/model changes to the
condensing flow can be A/B-tested visually.

This is a dev/debug tool — it makes a LIVE LLM call (unless ``--dry-run`` is
given) and reads from the production database. Point it at a dev config with
real credentials.

Usage:
    ./venv/bin/python3 scripts/check_condensing.py [flags] \\
        --chat-id 135824779 \\
        --message-id 42

Flags:
    --config-dir DIR      Config directory to load (repeatable).
                           configs/00-defaults is always included implicitly.
    --env FILE            Path to .env file for ${VAR} substitution in TOML.
                           Default: .env
    --chat-id ID          Chat ID to read (int, required).
    --message-id ID       A message ID in the thread to condense (str, required).
                           Resolved to the thread root automatically.
    --dry-run             Do everything EXCEPT the LLM condensing call.
                           Prints what WOULD be condensed + condensing config.
    --verbose             Dump full message texts (default: counts + summaries).

Exit codes:
    0  Success (or --dry-run completed).
    1  Config/DB/model resolution error.
    2  LLM condensing call raised an exception.

References:
    - getThreadByMessageForLLM: internal/bot/common/handlers/base.py:712
    - condenseContext:          internal/services/llm/service.py:606
    - EnsuredMessage:           internal/bot/models/ensured_message.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Ensure the repository root is on sys.path so that project packages
# (internal/, lib/) are importable when the script is run as:
#     ./venv/bin/python3 scripts/check_condensing.py
# In that invocation Python adds scripts/ to sys.path, not the repo root.
# ---------------------------------------------------------------------------
_REPO_ROOT = str(Path(__file__).parent.parent.resolve())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Silence noisy libraries before importing project code.
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("openai").setLevel(logging.ERROR)
logging.getLogger("openai._base_client").setLevel(logging.ERROR)

from internal.bot.models import (  # noqa: E402
    BotProvider,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatTier,
    ChatType,
    EnsuredMessage,
    LLMMessageFormat,
    OutputFormat,
)
from internal.config.manager import ConfigManager  # noqa: E402
from internal.database import Database  # noqa: E402
from internal.database.models import ChatMessageDict, MessageCategory  # noqa: E402
from internal.models import MessageId  # noqa: E402
from internal.services.cache import CacheService  # noqa: E402
from internal.services.llm import LLMService  # noqa: E402
from lib.ai import ModelMessage  # noqa: E402
from lib.ai.abstract import AbstractModel  # noqa: E402
from lib.ai.manager import LLMManager  # noqa: E402
from lib.proxy import ProxyHelper  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — mirror getThreadByMessageForLLM (base.py:783-784, 849)
# ---------------------------------------------------------------------------
_DEFAULT_CONFIG_DIRS: List[str] = ["configs/00-defaults", "configs/local"]
_IMPLICIT_CONFIG_DIR = "configs/00-defaults"

# keepFirstN / keepLastN for fresh condensing — same as base.py:783-784
_KEEP_FIRST_N: int = 1
_KEEP_LAST_N: int = 1

_SEPARATOR = "=" * 70


def buildParser() -> argparse.ArgumentParser:
    """Construct and return the argument parser for this script.

    Returns:
        Configured ``argparse.ArgumentParser`` instance with camelCase
        ``dest`` names for all kebab-case flags (per AGENTS.md naming rules).
    """
    parser = argparse.ArgumentParser(
        prog="check_condensing.py",
        description=(
            "Evaluate LLM context-condensing quality on a real chat thread. "
            "Fetches the thread, builds ModelMessages, and runs condenseContext."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config-dir",
        action="append",
        dest="configDirs",
        default=[],
        metavar="DIR",
        help=(
            "Config directory to load .toml files from (repeatable). "
            f"{_IMPLICIT_CONFIG_DIR} is always included implicitly. "
            f"If none given, defaults to: {' '.join(_DEFAULT_CONFIG_DIRS)}"
        ),
    )
    parser.add_argument(
        "--env",
        dest="envFile",
        default=".env",
        metavar="FILE",
        help="Path to .env file for ${VAR} substitution in TOML configs. Default: .env",
    )
    parser.add_argument(
        "--chat-id",
        dest="chatId",
        type=int,
        required=True,
        metavar="ID",
        help="Chat ID to read (positive for private, negative for group).",
    )
    parser.add_argument(
        "--message-id",
        dest="messageId",
        type=str,
        required=True,
        metavar="ID",
        help=(
            "A message ID belonging to the thread to condense. "
            "Resolved to the thread root automatically (if this message is a "
            "root, used directly; otherwise its root_message_id is looked up)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        dest="dryRun",
        action="store_true",
        default=False,
        help="Do everything EXCEPT the LLM condensing call. Prints what would be condensed.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Dump full message texts (default: print only counts + summaries).",
    )
    return parser


def resolveConfigDirs(rawDirs: List[str]) -> List[str]:
    """Resolve the final list of config directories, always including the implicit default.

    Mirrors ``run.sh`` semantics: ``configs/00-defaults`` is always passed first,
    then any user-specified dirs. If the user passes no dirs at all, the full
    default list (``configs/00-defaults``, ``configs/local``) is used.

    Args:
        rawDirs: The raw list of ``--config-dir`` values from argparse (may be empty).

    Returns:
        Ordered list of config directory paths with the implicit default guaranteed present.
    """
    if not rawDirs:
        return list(_DEFAULT_CONFIG_DIRS)
    result: List[str] = list(rawDirs)
    if _IMPLICIT_CONFIG_DIR not in result:
        result = [_IMPLICIT_CONFIG_DIR] + result
    return result


def estimateTokens(messages: Sequence[ModelMessage], model: AbstractModel) -> int:
    """Estimate the token count of a message sequence using the model's heuristic.

    Uses ``model.getEstimateTokensCount`` — the same estimation the production
    handler uses (base.py:851). The heuristic is ``len(json) / 3.5 * coeff``.

    Args:
        messages: Sequence of ModelMessage objects to estimate.
        model: The model whose token-count coefficient to use.

    Returns:
        Estimated token count as an integer.
    """
    return model.getEstimateTokensCount([m.toDict() for m in messages])


def resolveChatTier(
    chatSettings: Dict[ChatSettingsKey, ChatSettingsValue],
    defaultSettings: Dict[ChatSettingsKey, ChatSettingsValue],
) -> ChatTier:
    """Resolve a chat's tier, mirroring BaseBotHandler.getChatTier + fallback chain.

    Production tier resolution (base.py:259-266, getChatTier:341-359) checks the
    DB-set paid tier first (only if its expiry is still in the future), then the
    base tier on the DB overrides, then the base tier on the merged defaults,
    finally falling back to ``ChatTier.BANNED``. This bundles that whole chain
    into a single non-Optional return so the merge in :func:`loadChatSettings`
    can fold in the matching tier defaults.

    Args:
        chatSettings: The per-chat DB override settings (may be empty).
        defaultSettings: The merged global → per-type default settings.

    Returns:
        The resolved ChatTier; never None (BANNED is the last-resort fallback).
    """
    if ChatSettingsKey.PAID_TIER in chatSettings and ChatSettingsKey.PAID_TIER_UNTILL_TS in chatSettings:
        paidUntil = chatSettings[ChatSettingsKey.PAID_TIER_UNTILL_TS].toFloat()
        if paidUntil >= time.time():
            paidTier = ChatTier.fromStr(chatSettings[ChatSettingsKey.PAID_TIER].toStr())
            if paidTier is not None:
                return paidTier

    if ChatSettingsKey.BASE_TIER in chatSettings:
        baseTier = ChatTier.fromStr(chatSettings[ChatSettingsKey.BASE_TIER].toStr())
        if baseTier is not None:
            return baseTier

    if ChatSettingsKey.BASE_TIER in defaultSettings:
        baseTier = ChatTier.fromStr(defaultSettings[ChatSettingsKey.BASE_TIER].toStr())
        if baseTier is not None:
            return baseTier

    return ChatTier.BANNED


async def loadChatSettings(
    configManager: ConfigManager,
    cache: CacheService,
    chatId: int,
) -> Dict[ChatSettingsKey, ChatSettingsValue]:
    """Load and merge chat settings for the given chat (global → per-type → tier → DB overrides).

    Replicates the settings-merge cascade from ``BaseBotHandler.getChatSettings``
    (base.py:250-270): global defaults, then per-chat-type defaults, then
    tier-specific defaults (resolved the same way production resolves the tier),
    then actual per-chat DB overrides. The tier-filtering of DB overrides
    (base.py:281-303) is intentionally omitted — this is a dev tool and the dev
    config is assumed to have no tier incompatibilities (same simplification as
    ``reproduce_llm_dialog.py``), but tier *defaults* are folded in so that
    tier-gated model resolution (e.g. CONDENSING_MODEL on a paid tier) matches
    production.

    Args:
        configManager: The initialized ConfigManager instance.
        cache: The CacheService singleton with database injected.
        chatId: The chat ID to load settings for.

    Returns:
        Merged Dict[ChatSettingsKey, ChatSettingsValue] for the chat.
    """
    botConfig = configManager.getBotConfig()

    # Global defaults (manager.py:397-405)
    defaultSettings: Dict[ChatSettingsKey, ChatSettingsValue] = {k: ChatSettingsValue("") for k in ChatSettingsKey}
    defaultSettings.update(
        {
            ChatSettingsKey(k): ChatSettingsValue(v)
            for k, v in botConfig.get("defaults", {}).items()
            if k in ChatSettingsKey
        }
    )
    cache.setDefaultChatSettings(None, defaultSettings)

    # Per-chat-type defaults (manager.py:407-415)
    for chatType in ChatType:
        cache.setDefaultChatSettings(
            chatType,
            {
                ChatSettingsKey(k): ChatSettingsValue(v)
                for k, v in botConfig.get(f"{chatType.value}-defaults", {}).items()
                if k in ChatSettingsKey
            },
        )

    # Tier defaults (manager.py:417-426)
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

    # DB per-chat overrides
    chatSettingsFromDb = await cache.getChatSettings(chatId)

    # Merge: global → per-type → tier → DB (mirrors base.py:250-270, 275-303,
    # minus the tier-filtering of DB overrides which is irrelevant for dev use).
    chatSettings: Dict[ChatSettingsKey, ChatSettingsValue] = dict(cache.getDefaultChatSettings(None))
    chatType = ChatType.PRIVATE if chatId > 0 else ChatType.GROUP
    chatSettings.update(cache.getDefaultChatSettings(chatType))
    chatTier = resolveChatTier(chatSettingsFromDb, chatSettings)
    chatSettings.update(cache.getDefaultChatSettings(f"tier-{chatTier}"))
    chatSettings.update(chatSettingsFromDb)

    return chatSettings


async def buildThreadModelMessages(
    db: Database,
    threadMessages: List[ChatMessageDict],
    llmMessageFormat: LLMMessageFormat,
    chatSettings: Dict[ChatSettingsKey, ChatSettingsValue],
    outputFormat: OutputFormat,
) -> List[ModelMessage]:
    """Build the ModelMessage list for a thread, mirroring getThreadByMessageForLLM.

    Constructs a system-prompt ModelMessage (CHAT_PROMPT + CHAT_PROMPT_SUFFIX)
    followed by each thread message rendered via ``EnsuredMessage.toModelMessageList``.
    This is the same construction as base.py:751-841, minus the condense-cache
    reconstruction and memory deduplication (cache=None means no memory
    resolution, so dedup is moot). The system prompt is prepended so the
    BEFORE/AFTER token counts include the persona — matching what production
    passes to ``condenseContext`` (base.py:751-758, 855-864).

    Args:
        db: The Database singleton for media-content lookups.
        threadMessages: Chronologically-ordered list of ChatMessageDict rows.
        llmMessageFormat: The LLM message format (JSON / TEXT / SMART) from chat settings.
        chatSettings: Merged chat settings; CHAT_PROMPT + CHAT_PROMPT_SUFFIX form the
            system prompt (must be the full merged settings dict, not raw DB overrides).
        outputFormat: The OutputFormat (MARKDOWN_TG / MARKDOWN_MAX / MARKDOWN) to forward
            to ``toModelMessageList``; production selects this from ``botProvider``
            (base.py:744-749).

    Returns:
        List of ModelMessage objects: [systemPrompt, msg1, msg2, ...].
    """
    ret: List[ModelMessage] = [
        ModelMessage(
            role="system",
            content=chatSettings[ChatSettingsKey.CHAT_PROMPT].toStr()
            + "\n"
            + chatSettings[ChatSettingsKey.CHAT_PROMPT_SUFFIX].toStr(),
        ),
    ]

    for dbRow in threadMessages:
        eMessage = await EnsuredMessage.fromDBChatMessage(dbRow, db)
        mMessages = await eMessage.toModelMessageList(
            db,
            format=llmMessageFormat,
            outputFormat=outputFormat,
            role=MessageCategory.fromStr(dbRow["message_category"]).toRole(),
            cache=None,
            excludeMemoryIds=set(),
        )
        ret.extend(mMessages)

    return ret


def printSection(title: str) -> None:
    """Print a visually delineated section header.

    Args:
        title: The section title to print.

    Returns:
        None.
    """
    print(f"\n{_SEPARATOR}")
    print(f"  {title}")
    print(_SEPARATOR)


async def main() -> int:
    """Run the condensing evaluation flow.

    Loads config, inits Database + LLMService, fetches the thread, builds
    ModelMessages, prints BEFORE state, optionally runs condenseContext, and
    prints AFTER state.

    Returns:
        Exit code: 0 on success (incl. --dry-run), 1 on config/DB error,
        2 on LLM condensing failure.
    """
    args = buildParser().parse_args()
    configDirs: List[str] = resolveConfigDirs(args.configDirs)

    print(f"Config dirs: {', '.join(configDirs)}")
    print(f"Env file:    {args.envFile}")

    # ------------------------------------------------------------------
    # 1. Init ConfigManager, Database, LLMService, CacheService
    #    (mirrors main.py:56-95 and reproduce_llm_dialog.py:279-294)
    # ------------------------------------------------------------------
    db: Optional[Database] = None
    try:
        configManager = ConfigManager(
            configPath="config.toml",
            configDirs=configDirs,
            dotEnvFile=args.envFile,
        )

        ProxyHelper.getInstance().setGlobalProxyConfig(configManager.getProxyConfig())

        db = Database(
            configManager.getDatabaseConfig(),  # pyright: ignore[reportArgumentType]
        )

        # LLMManager must be injected into LLMService BEFORE any ChatSettingsValue.toModel()
        # call (chat_settings.py:593 → getLLMManager() → LLMService.getLLMManager()).
        llmManager = LLMManager(configManager.getModelsConfig())
        llmService = LLMService.getInstance()
        llmService.injectLLMManager(llmManager)

        cache = CacheService.getInstance()
        await cache.injectDatabase(db)

        # ------------------------------------------------------------------
        # 2. Load chat settings + resolve outputFormat from the configured bot platform
        # ------------------------------------------------------------------
        chatId: int = args.chatId
        chatSettings = await loadChatSettings(configManager, cache, chatId)

        # Mirror base.py:744-749: production selects MARKDOWN_TG / MARKDOWN_MAX by
        # botProvider, which comes from the [bot].mode config key (main.py:103).
        botProvider = BotProvider(configManager.getBotConfig().get("mode", BotProvider.TELEGRAM))
        outputFormat = OutputFormat.MARKDOWN
        match botProvider:
            case BotProvider.TELEGRAM:
                outputFormat = OutputFormat.MARKDOWN_TG
            case BotProvider.MAX:
                outputFormat = OutputFormat.MARKDOWN_MAX

        llmModel: AbstractModel = chatSettings[ChatSettingsKey.CHAT_MODEL].toModel()
        condensingModel: AbstractModel = chatSettings[ChatSettingsKey.CONDENSING_MODEL].toModel()
        condensingPrompt: str = chatSettings[ChatSettingsKey.CONDENSING_PROMPT].toStr()
        condensingSystemPrompt: str = chatSettings[ChatSettingsKey.CONDENSING_SYSTEM_PROMPT].toStr()
        llmMessageFormat = LLMMessageFormat(chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr())

        # maxTokens: same heuristic as base.py:849 (50% of chat model context)
        maxTokens: int = int(llmModel.contextSize * 0.5)

        # ------------------------------------------------------------------
        # 3. Resolve thread root and fetch the full thread
        # ------------------------------------------------------------------
        messageId = MessageId(args.messageId)
        dbMessage = await db.chatMessages.getChatMessageByMessageId(chatId, messageId)
        if dbMessage is None:
            print(f"\nERROR: Message {messageId} not found in chat {chatId}.", file=sys.stderr)
            await db.manager.closeAll()
            return 1

        rawRootId = dbMessage["root_message_id"]
        # Roots are self-referential (root_message_id == own id) in modern data.
        # Legacy/standalone messages may have root_message_id = None → use own id.
        if rawRootId is not None:
            rootMessageId = MessageId(rawRootId)
        else:
            rootMessageId = MessageId(dbMessage["message_id"])

        threadId: Optional[int] = dbMessage["thread_id"]
        threadMessages: List[ChatMessageDict] = await db.chatMessages.getChatMessagesByRootId(
            chatId,
            rootMessageId=rootMessageId,
            threadId=threadId,
        )

        if not threadMessages:
            # Fallback: the message is a standalone root with no replies
            threadMessages = [dbMessage]

        # ------------------------------------------------------------------
        # 4. Build the ModelMessage list (system + thread)
        # ------------------------------------------------------------------
        messages = await buildThreadModelMessages(db, threadMessages, llmMessageFormat, chatSettings, outputFormat)

        if not messages:
            print(f"\nERROR: No messages to condense for chat {chatId}, root {rootMessageId}.", file=sys.stderr)
            await db.manager.closeAll()
            return 1
    except Exception as e:
        # Setup-phase failure (config/DB/model resolution) — e.g. toModel() raises
        # ValueError on unknown/empty model names (chat_settings.py:593-596). Catch
        # cleanly, close the DB if it was opened, and exit 1 per the docstring contract.
        print(f"\nERROR: Setup phase failed: {e}", file=sys.stderr)
        traceback.print_exc()
        if db is not None:
            await db.manager.closeAll()
        return 1

    beforeTokens = estimateTokens(messages, llmModel)

    # ------------------------------------------------------------------
    # 5. Print BEFORE state
    # ------------------------------------------------------------------
    printSection("BEFORE — Raw Thread")
    print(f"  Chat ID:          {chatId}")
    print(f"  Root message ID:  {rootMessageId}")
    print(f"  Thread ID:        {threadId}")
    print(f"  DB messages:      {len(threadMessages)}")
    print(f"  ModelMessages:    {len(messages)}")
    print(f"  Est. tokens:      {beforeTokens:,}")

    # ------------------------------------------------------------------
    # 6. Print condensing config (always, emphasized in --dry-run)
    # ------------------------------------------------------------------
    printSection("Condensing Config")
    print(f"  Chat model:       {llmModel.modelId}  (context={llmModel.contextSize:,})")
    print(f"  Condensing model: {condensingModel.modelId}  (context={condensingModel.contextSize:,})")
    print(f"  keepFirstN:       {_KEEP_FIRST_N}")
    print(f"  keepLastN:        {_KEEP_LAST_N}")
    print(f"  maxTokens:        {maxTokens:,}  (50% of chat context)")
    print("  force:            True  (evaluation mode — always condense)")
    promptPreview = condensingPrompt.replace("\n", " ")[:120]
    print(f"  Condensing prompt:    {promptPreview}{'...' if len(condensingPrompt) > 120 else ''}")
    sysPromptPreview = condensingSystemPrompt.replace("\n", " ")[:120]
    print(f"  Condensing sys prompt: {sysPromptPreview}" f"{'...' if len(condensingSystemPrompt) > 120 else ''}")

    # ------------------------------------------------------------------
    # 7. Verbose: dump full message texts
    # ------------------------------------------------------------------
    if args.verbose:
        printSection("Input Messages (full text)")
        for idx, msg in enumerate(messages):
            print(f"\n  [{idx}] role={msg.role}")
            print(f"  {'-' * 40}")
            print(f"  {msg.content}")

    # ------------------------------------------------------------------
    # 8. Dry-run: show what would be condensed, then exit
    # ------------------------------------------------------------------
    # condenseContext internally adds +1 to keepFirstN when messages[0] is system
    hasSystemPrompt = messages[0].role == "system"
    effectiveKeepFirstN = _KEEP_FIRST_N + (1 if hasSystemPrompt else 0)
    bodyMessages = (
        messages[effectiveKeepFirstN : len(messages) - _KEEP_LAST_N]
        if _KEEP_LAST_N > 0
        else messages[effectiveKeepFirstN:]
    )

    if args.dryRun:
        printSection("WOULD BE CONDENSED (--dry-run, no LLM call)")
        print(f"  Messages to condense (body): {len(bodyMessages)}")
        print(f"  Kept as-is (head):          {effectiveKeepFirstN}")
        print(f"  Kept as-is (tail):          {_KEEP_LAST_N}")
        print(f"  Body est. tokens:           {estimateTokens(bodyMessages, llmModel):,}")
        if args.verbose and bodyMessages:
            print()
            for idx, msg in enumerate(bodyMessages):
                print(f"  --- Body message {idx + 1}/{len(bodyMessages)} (role={msg.role}) ---")
                print(f"  {msg.content}")
                print()
        print(f"\n{_SEPARATOR}")
        print("  --dry-run complete. No LLM call made.")
        print(_SEPARATOR)
        await db.manager.closeAll()
        return 0

    # ------------------------------------------------------------------
    # 9. Run condenseContext (force=True for evaluation)
    # ------------------------------------------------------------------
    printSection("Running condenseContext ...")
    try:
        condensedMessages = await llmService.condenseContext(
            messages,
            model=llmModel,
            keepFirstN=_KEEP_FIRST_N,
            keepLastN=_KEEP_LAST_N,
            maxTokens=maxTokens,
            condensingModel=condensingModel,
            condensingPrompt=condensingPrompt,
            condensingSystemPrompt=condensingSystemPrompt,
            force=True,
        )
    except Exception:
        print(f"\n{_SEPARATOR}")
        print("  ERROR: condenseContext raised an exception!")
        print(_SEPARATOR)
        traceback.print_exc()
        await db.manager.closeAll()
        return 2

    # ------------------------------------------------------------------
    # 10. Print AFTER state
    # ------------------------------------------------------------------
    afterTokens = estimateTokens(condensedMessages, llmModel)
    tokenSavings = beforeTokens - afterTokens

    printSection("AFTER — Condensed")
    print(f"  ModelMessages:    {len(condensedMessages)}")
    print(f"  Est. tokens:      {afterTokens:,}")
    print(
        f"  Token savings:    {tokenSavings:,}  ({(tokenSavings / beforeTokens * 100):.1f}% of original)"
        if beforeTokens > 0
        else "  Token savings:    N/A"
    )
    print(f"  Condensing model: {condensingModel.modelId}")

    # Identify the condensed summary blocks in the result.
    # Result layout: [head (effectiveKeepFirstN)] [summaries] [tail (_KEEP_LAST_N)]
    summaryStart = effectiveKeepFirstN
    summaryEnd = len(condensedMessages) - _KEEP_LAST_N if _KEEP_LAST_N > 0 else len(condensedMessages)
    summaryMessages = condensedMessages[summaryStart:summaryEnd]

    if summaryMessages and len(condensedMessages) != len(messages):
        printSection("Condensed Summary Blocks")
        for i, msg in enumerate(summaryMessages):
            print(f"\n  --- Condensed block {i + 1}/{len(summaryMessages)} (role={msg.role}) ---")
            print(f"  {msg.content}")
    elif len(condensedMessages) == len(messages):
        printSection("Condensed Summary Blocks")
        print("  (condenseContext returned the original messages unchanged —")
        print("   the body may have fit within maxTokens or condensing produced no summaries.)")
    else:
        printSection("Condensed Summary Blocks")
        print("  (no summary blocks detected in the result.)")

    # ------------------------------------------------------------------
    # 11. Cleanup
    # ------------------------------------------------------------------
    await db.manager.closeAll()
    print(f"\n{_SEPARATOR}")
    print("  Done.")
    print(_SEPARATOR)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
