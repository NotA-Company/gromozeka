"""
User memories management handlers for Gromozeka bot.

Provides handlers for user memories: viewing, deleting, clearing memories,
and LLM tool integration for AI-assisted memory management. All memories are
scoped to specific chat and user combinations.
"""

import asyncio
import datetime
import logging
import time
import uuid
from collections.abc import Sequence
from typing import Dict, List, Optional, Tuple

from dateutil import parser as dateutilParser

import lib.utils as utils
from internal.bot.common.models import CallbackButton, UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.constants import (
    KNOWLEDGE_CONFIG_PAGE_SIZE,
    KNOWLEDGE_CONFIG_TAG_FILTER_FETCH_LIMIT,
    MEMORY_BACKFILL_DEFAULT_BATCH_SIZE,
    MEMORY_BACKFILL_INTER_MESSAGE_DELAY_SECS,
    MEMORY_COUNT_THRESHOLD,
    MEMORY_DEDUP_DUPLICATE_THRESHOLD,
    MEMORY_DEDUP_SIMILAR_THRESHOLD,
    MEMORY_MAX_MESSAGES_PER_RUN,
    MEMORY_MAX_REFINES_PER_TICK,
    MEMORY_MIN_MESSAGES_TO_REFINE,
    MEMORY_SEARCH_DEFAULT_LIMIT,
    MEMORY_SEARCH_MAX_LIMIT,
    MEMORY_TIME_THRESHOLD_SECONDS,
    ToolName,
)
from internal.bot.models import (
    BotProvider,
    ButtonDataKey,
    ButtonUserDataConfigAction,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    LLMMessageFormat,
    MessageRecipient,
    MessageSender,
    commandHandlerV2,
)
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.models import ChatMessageDict, MemoryType, MessageCategory, UserMemorySource
from internal.database.repositories.user_memories import UserMemoryDict
from internal.database.utils import DEFAULT_THREAD_ID
from internal.models import MessageId
from internal.services.cache import UserActiveActionEnum
from internal.services.llm import LLMService
from internal.services.llm.models import ExtraDataDict
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction
from lib.ai import (
    LLMFunctionParameter,
    LLMParameterType,
    ModelMessage,
)
from lib.ai.models import ModelRunResult

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


def _formatMemoryLine(mem: UserMemoryDict) -> str:
    """Render a single memory dict as one ``[type] content #tag …`` line.

    Tags are appended as ``#tag`` tokens (space-separated) and omitted
    entirely when the memory carries no tags. The ``type`` is rendered in
    square brackets before the content (plan §9.1).

    Args:
        mem: A :class:`UserMemoryDict` row.

    Returns:
        A single formatted line (no trailing newline).
    """
    tags = mem.get("tags") or []
    tagSuffix = ""
    if tags:
        tagSuffix = " " + " ".join(f"#{t}" for t in tags if t)
    return f"[{mem['type']}] {mem['content']}{tagSuffix}"


def _formatMemoriesBlockRaw(
    permanent: Sequence[UserMemoryDict],
    ephemeral: Sequence[UserMemoryDict],
) -> Optional[str]:
    """Render the ``<user-memories>`` block with no soft-cap trimming.

    Shared by :meth:`BaseBotHandler._formatMemoriesBlock` (the staticmethod
    wrapper that may trim the recent slice to a soft char cap) so the trim
    loop can re-render with a smaller recent slice without re-implementing
    the layout. See :meth:`BaseBotHandler._formatMemoriesBlock` for the
    format spec.

    Args:
        permanent: Permanent memories (already capped + ordered).
        ephemeral: Ephemeral memories (already capped + ordered newest-first).

    Returns:
        The formatted block string, or ``None`` when both inputs are empty.
    """
    if not permanent and not ephemeral:
        return None
    lines: List[str] = ["<user-memories>"]
    if permanent:
        lines.append("Permanent:")
        for mem in sorted(
            permanent,
            key=lambda m: (str(m.get("type", "")), str(m.get("updated_at", ""))),
        ):
            lines.append(_formatMemoryLine(mem))
    if ephemeral:
        lines.append("Recent:")
        for mem in ephemeral:
            lines.append(_formatMemoryLine(mem))
    lines.append("</user-memories>")
    return "\n".join(lines)


class UserMemoriesHandler(BaseBotHandler):
    """
    Handler for user memories management with LLM tool integration.

    Attributes:
        llmService (LLMService): Service for LLM tool registration and management.
    """

    def __init__(self, *, configManager: ConfigManager, database: Database, botProvider: BotProvider) -> None:
        """
        Initialize handler, register the user-memory LLM tools
        (add_memory/delete_memory/search_memories, gated on
        [user-memory].enabled), cache [user-memory] config, and register the
        refinement + embedding-regen CRON_JOB handlers.

        Args:
            configManager (ConfigManager): Configuration manager instance.
            database (Database): Database object for data persistence.
            botProvider (BotProvider): Bot provider instance.
        """
        # Initialize the mixin (discovers handlers)
        super().__init__(configManager=configManager, database=database, botProvider=botProvider)

        self.llmService = LLMService.getInstance()

        # In-memory per-(chatId, userId, threadId) new-message counter used by the
        # memory-refinement cron to decide when a user's rolling summary is due.
        # Lost on restart; refinement re-fires after the next threshold crossing.
        self._accounting: Dict[Tuple[int, int, int], int] = {}

        # In-memory per-(chatId, userId, threadId) refinement-timestamp tracker.
        # Replaces the old persisted ``lastRefinedTS`` field so the DB entry only
        # carries durable data (summary + message cursors). Lost on restart: an
        # absent key is treated as 0 (i.e. never refined this session → due by
        # time), which preserves the previous effective behaviour.
        self._lastRefinedTS: Dict[Tuple[int, int, int], int] = {}

        # Lock guarding self._accounting and self._lastRefinedTS reads/writes.
        # _accounting is mutated under this lock in newMessageHandler (increment)
        # and _dtCronJob (credit-consumed subtract/drop); _lastRefinedTS is written
        # under it in _dtCronJob's finally block and _runRefinement, and read under
        # it in the _dtCronJob due-list scan, so the scan never observes a
        # half-updated timestamp. The scan-loop snapshot
        # ``list(self._accounting.items())`` is intentionally taken without the
        # lock — ``dict.items()`` is atomic w.r.t. ``await`` on a single event
        # loop.
        self._accountingLock = asyncio.Lock()

        # Single global lock serializing ALL refinement runs so a slow LLM call
        # (>60s) blocks the next tick instead of spawning a concurrent one and
        # flooding the provider. See docs/plans/memory-refine-plan-v1.md §4/§5.
        self._refineLock = asyncio.Lock()

        # Cache the [user-memory] config ONCE at construction so the cron hot
        # path and _runRefinement never touch configManager. Thresholds fall
        # back to the module constants (which mirror the TOML defaults) when the
        # section is absent or partially specified.
        userMemoryConfig = configManager.get("user-memory", {})
        self._memoryRefineEnabled: bool = userMemoryConfig.get("enabled", False)
        """Global kill switch for the memory-refinement subsystem."""
        thresholds = userMemoryConfig.get("thresholds", {})
        self._memoryCountThreshold: int = thresholds.get("message-count", MEMORY_COUNT_THRESHOLD)
        """Per-(chat, user, thread) new-message count that triggers a refinement run."""
        self._memoryTimeThresholdSeconds: int = thresholds.get("time-seconds", MEMORY_TIME_THRESHOLD_SECONDS)
        """Max seconds since the last refinement run before another is forced."""
        self._memoryMinMessagesToRefine: int = thresholds.get("min-messages-to-refine", MEMORY_MIN_MESSAGES_TO_REFINE)
        """Don't refine if fewer than this many new messages are available."""
        self._memoryMaxMessagesPerRun: int = thresholds.get("max-messages-per-run", MEMORY_MAX_MESSAGES_PER_RUN)
        """Cap on messages fed to a single refinement LLM call."""
        self._memoryMaxRefinesPerTick: int = thresholds.get("max-refines-per-tick", MEMORY_MAX_REFINES_PER_TICK)
        """Upper bound on refinement LLM calls per 60s cron tick."""

        # Memory-embedding regeneration config (Phase 3b — see
        # docs/plans/user-memories-v1.md §5.6). The regen pass shares the
        # 60s CRON_JOB tick with refinement but runs INDEPENDENTLY of the
        # refinement lock: it is read/embed/write on ``user_memories``,
        # not LLM-tool-driven, so the two do not contend. Cached once at
        # construction so the cron hot path never touches configManager.
        self._memoryReindexBatchSize: int = int(
            thresholds.get("memory-reindex-batch-size", MEMORY_BACKFILL_DEFAULT_BATCH_SIZE)
        )
        """Per-tick batch cap for the memory-embedding regeneration loop."""

        # Round-robin index across MEMORY_EMBEDDINGS_ENABLED chats. Survives
        # across ticks so a backlog drains chat-by-chat in stable order
        # rather than re-shuffling every minute. Mirrors ``_backfillIndex``
        # in ``ChatSearchHandler``.
        self._memoryBackfillIndex: int = 0

        # In-memory tracking of the last embedding model seen per chat
        # (``chatId -> modelKey``). ``modelKey`` is ``modelName`` alone when
        # the model does not expose dimensions, or ``"modelName:dimensions"``
        # when it does. Used by ``_runMemoryEmbeddingRegen`` to skip
        # redundant obsolete-embedding cleanup on every tick — cleanup only
        # fires once per model switch. Mirrors ``_embeddingModelTracker`` in
        # ``ChatSearchHandler``.
        self._memoryEmbeddingModelTracker: Dict[int, str] = {}

        # JSONL refinement log config (mirrors [models.json-logging]). Read once
        # at construction; the writer guards on `_refineLogEnabled` and is a
        # best-effort synchronous append so a logging failure never breaks the
        # refinement pipeline. See `_writeRefinementJsonLog`.
        refineLogConfig = userMemoryConfig.get("json-logging", {})
        self._refineLogEnabled: bool = bool(refineLogConfig.get("enabled", False))
        """Kill switch for the per-run JSONL refinement log."""
        self._refineLogFile: str = refineLogConfig.get("file", "")
        """Target JSONL file path (a UTC date suffix may be appended)."""
        self._refineLogAddDateSuffix: bool = bool(refineLogConfig.get("add-date-suffix", True))
        """Whether to append a ``.YYYY-MM-DD`` (UTC) suffix to the log file."""

        # Register the memory-refinement CRON_JOB. Multiple handlers can
        # subscribe to the same `DelayedTaskFunction.CRON_JOB` (they run in
        # registration order), so the existing cleanup tick and the
        # `ChatSearchHandler` backfill keep running unaffected.
        self.queueService.registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB, self._dtCronJob)

        # Register the user-memory LLM tools. Gated on the global
        # ``[user-memory].enabled`` kill switch so the feature is truly off
        # by default (no tools registered → nothing offered via the chat-time
        # ``useTools`` wildcard). Per-chat availability is additionally
        # controlled via ``useTools`` in ``_sendLLMChatMessage``
        # (``DELETE_MEMORY: False`` — D3 enforcement) and, in Phase 3, the
        # ``MEMORY_INJECTION_ENABLED`` setting. See
        # docs/plans/user-memories-v1.md §8.3 / §13 Phase 2.
        if self._memoryRefineEnabled:
            self.llmService.registerTool(
                name=ToolName.ADD_MEMORY,
                description=(
                    "Store a durable fact, preference, event, relationship, or high-level bio note "
                    "about the user who sent the last message. Each memory is discrete and tagged "
                    "with a ``type`` (bio|preference|fact|event|relationship) plus optional freeform "
                    "tags. Use ``permanent=true`` only for durable, always-relevant knowledge (a "
                    "high-level bio summary, a stable preference); use the default ephemeral mode "
                    "for everything else. Near-duplicates above a similarity threshold are "
                    "auto-skipped, so call this freely when you learn something worth remembering "
                    "or when user asks you to remember something."
                ),
                parameters=[
                    LLMFunctionParameter(
                        name="content",
                        description=(
                            "The memory body — a concise, self-contained statement of what you want to remember."
                        ),
                        type=LLMParameterType.STRING,
                        required=True,
                    ),
                    LLMFunctionParameter(
                        name="type",
                        description=f"Memory category. One of: {', '.join([v for v in MemoryType])}",
                        type=LLMParameterType.STRING,
                        required=True,
                    ),
                    LLMFunctionParameter(
                        name="tags",
                        description='Optional list of freeform tag strings (e.g. ["vegan", "timezone"]).',
                        type=LLMParameterType.ARRAY,
                        required=False,
                    ),
                    LLMFunctionParameter(
                        name="permanent",
                        description="When true, the memory is always injected into future replies. Default: false.",
                        type=LLMParameterType.BOOLEAN,
                        required=False,
                    ),
                ],
                handler=self._llmToolAddMemory,
            )

            self.llmService.registerTool(
                name=ToolName.DELETE_MEMORY,
                description=(
                    "Delete one or more memories about the user who sent the last message. "
                    "Pass ``memory_id`` to delete a specific memory by its id (returned by "
                    "``add_memory`` or ``search_memories``), or pass ``query`` to semantically "
                    "find and delete memories matching a description. By-query delete only "
                    "removes clear matches (similarity >= 0.85). Use this to remove stale, "
                    "incorrect, or conflicting memories."
                ),
                parameters=[
                    LLMFunctionParameter(
                        name="memory_id",
                        description="Delete the memory with this exact id (takes precedence over query).",
                        type=LLMParameterType.STRING,
                        required=False,
                    ),
                    LLMFunctionParameter(
                        name="query",
                        description=(
                            "Semantic query — memories matching this description (similarity >= 0.85) are deleted."
                        ),
                        type=LLMParameterType.STRING,
                        required=False,
                    ),
                    LLMFunctionParameter(
                        name="type",
                        description=(
                            "Optional MemoryType filter (only used with query): "
                            f"{'|'.join([v for v in MemoryType])}."
                        ),
                        type=LLMParameterType.STRING,
                        required=False,
                    ),
                ],
                handler=self._llmToolDeleteMemory,
            )

            self.llmService.registerTool(
                name=ToolName.SEARCH_MEMORIES,
                description=(
                    "Search memories. By default searches the calling user's own memories; pass "
                    "``user`` to search a different user's memories. Pass ``query`` for semantic "
                    "search, or omit it to list memories matching a filter (by type/tags)."
                ),
                parameters=[
                    LLMFunctionParameter(
                        name="query",
                        description="Natural-language query. When omitted, runs a filter-only scan (no embedding).",
                        type=LLMParameterType.STRING,
                        required=False,
                    ),
                    LLMFunctionParameter(
                        name="type",
                        description=f"Optional MemoryType filter: {'|'.join([v for v in MemoryType])}.",
                        type=LLMParameterType.STRING,
                        required=False,
                    ),
                    LLMFunctionParameter(
                        name="tags",
                        description="Optional list of tag strings; memories carrying ANY of these tags are returned.",
                        type=LLMParameterType.ARRAY,
                        required=False,
                    ),
                    LLMFunctionParameter(
                        name="limit",
                        description="Max results to return (default 20).",
                        type=LLMParameterType.NUMBER,
                        required=False,
                    ),
                    LLMFunctionParameter(
                        name="permanent",
                        description="Optional permanent-flag filter: true for permanent memories, false for ephemeral.",
                        type=LLMParameterType.BOOLEAN,
                        required=False,
                    ),
                    LLMFunctionParameter(
                        name="user",
                        description=(
                            "Optional: search a different user's memories instead of your own. "
                            "Accepts a login (with or without @) or a numeric user_id."
                        ),
                        type=LLMParameterType.STRING,
                        required=False,
                    ),
                ],
                handler=self._llmToolSearchMemories,
            )

    ###
    # LLM Tool-Calling handlers (User Memories — Phase 2)
    ###
    #
    # See docs/plans/user-memories-v1.md §8.3-8.5 for the authoritative spec.
    # Contract (§3.4): async, never raises (errors → {"done": False, "error": ...}),
    # chat context resolved from extraData["ensuredMessage"].

    async def _llmToolAddMemory(
        self,
        extraData: Optional[Dict[str, object]],
        content: str,
        type: str,
        tags: Optional[List[str]] = None,
        permanent: bool = False,
        **kwargs: object,
    ) -> Dict[str, object]:
        """LLM tool: add a user memory with dedup (see plan §8.3 / D5).

        Resolves the chat/user/thread context, optionally generates an
        embedding for dedup, searches for near-duplicates, and either
        inserts (best-effort embedding), returns ``duplicate``, or — at
        refinement time only — returns ``similar_exists`` so the
        refinement LLM can merge. At chat time the grey zone folds to
        ``duplicate``.

        Never raises — all failures are folded into ``{"done": False,
        "error": ...}``.

        Args:
            extraData: Context dict; must carry ``ensuredMessage``. When
                ``isRefinement`` is truthy, the grey-zone returns
                ``similar_exists`` (D5).
            content: Memory body text.
            type: ``MemoryType`` string value (bio|preference|fact|event|relationship).
            tags: Optional list of freeform tag strings.
            permanent: When true the memory is always-injected.
            **kwargs: Ignored.

        Returns:
            ``{"done": True, "action": "added"|"duplicate"|"similar_exists", ...}``
            on success, ``{"done": False, "error": ...}`` on failure.
        """
        try:
            # --- Context resolution ------------------------------------------------
            ensuredMessage = extraData.get("ensuredMessage") if extraData else None
            if not isinstance(ensuredMessage, EnsuredMessage):
                return {"done": False, "error": "Missing ensuredMessage"}

            chatId = ensuredMessage.recipient.id
            userId = ensuredMessage.sender.id
            # Amendment #7: permanent memories are thread-specific (NOT
            # cross-thread NULL). Only migration-backfilled user_data facts
            # carry thread_id = NULL. So every tool-created memory — permanent
            # or ephemeral — is scoped to the current thread.
            threadId: int = ensuredMessage.threadId or DEFAULT_THREAD_ID
            isRefinement: bool = bool(extraData.get("isRefinement", False)) if extraData else False

            # --- Type validation ---------------------------------------------------
            try:
                type = MemoryType(type)  # validates the value is a known member
            except ValueError:
                return {
                    "done": False,
                    "error": f"Invalid memory type: {type}. Please use one of {[e.value for e in MemoryType]}.",
                }

            # --- Dedup: resolve embedding model + search --------------------------
            chatSettings = await self.getChatSettings(chatId)

            embeddings = await self.llmService.generateEmbedding(
                content,
                chatId=ensuredMessage.recipient.id,
                chatSettings=chatSettings,
            )

            similar = []
            if embeddings is not None:
                # Dedup embedding + search are best-effort: a transient
                # embedding outage must NEVER prevent the memory from being
                # stored (plan §8.3 — "never raise; on failure skip dedup").
                # This mirrors the ``model is None`` fallback below: on any
                # dedup failure ``similar = []`` and the insert proceeds.
                try:
                    similar = await self.db.userMemories.searchMemories(
                        chatId,
                        userId,
                        embeddings[1],
                        threadId=threadId,
                        limit=1,
                        embeddingModel=embeddings[0],
                    )
                except Exception:
                    logger.warning(
                        "_llmToolAddMemory: dedup embedding/search failed; inserting without dedup",
                        exc_info=True,
                    )
                    similar = []

            if similar:
                topScore = float(similar[0].get("score", 0.0))
                existing = similar[0]
                if topScore >= MEMORY_DEDUP_DUPLICATE_THRESHOLD:
                    return {
                        "done": True,
                        "action": "duplicate",
                        "existing_memory_id": existing["memory_id"],
                        "existing_content": existing["content"],
                        "existing_type": existing["type"],
                        "existing_tags": existing["tags"],
                        "score": topScore,
                    }
                if topScore > MEMORY_DEDUP_SIMILAR_THRESHOLD:
                    # Grey zone — D5: refinement sees ``similar_exists``;
                    # chat-time folds to ``duplicate`` to avoid mid-turn curation.
                    if isRefinement:
                        return {
                            "done": True,
                            "action": "similar_exists",
                            "existing_memory_id": existing["memory_id"],
                            "existing_content": existing["content"],
                            "existing_type": existing["type"],
                            "existing_tags": existing["tags"],
                            "score": topScore,
                        }
                    return {
                        "done": True,
                        "action": "duplicate",
                        "existing_memory_id": existing["memory_id"],
                        "existing_content": existing["content"],
                        "existing_type": existing["type"],
                        "existing_tags": existing["tags"],
                        "score": topScore,
                    }

            # --- Insert + best-effort embed ---------------------------------------
            # Normalize tags to lowercase: the system prompt asks for lowercase
            # tags, but an LLM that ignores the instruction must not persist
            # mixed-case tags that would break the case-sensitive
            # set-intersection filtering at injection time.
            memoryId = uuid.uuid4().hex
            await self.db.userMemories.addMemory(
                chatId,
                userId,
                memoryId,
                type=type,
                content=content,
                tags=tags or [],
                permanent=permanent,
                threadId=threadId,
                source=UserMemorySource.REFINEMENT if isRefinement else UserMemorySource.CHAT,
                embeddingModel=embeddings[0] if embeddings else None,
                embedding=embeddings[1] if embeddings else None,
            )
            if permanent:
                await self.cache.invalidateChatUserPermanentMemories(chatId=chatId, userId=userId, threadId=threadId)
            return {"done": True, "action": "added", "memory_id": memoryId}
        except Exception as e:
            logger.exception("_llmToolAddMemory: failed")
            return {"done": False, "error": str(e)}

    async def _llmToolDeleteMemory(
        self,
        extraData: Optional[Dict[str, object]],
        memory_id: Optional[str] = None,
        query: Optional[str] = None,
        type: Optional[str] = None,
        **kwargs: object,
    ) -> Dict[str, object]:
        """LLM tool: delete a user memory by id or by semantic query (plan §8.4).

        By-id delete is unrestricted (can target a permanent memory). By-query
        delete embeds the query, finds matches with similarity >= 0.85, and
        deletes each by id — this path can also reach permanent memories
        because every deletion is an explicit, query-driven action reviewed by
        the refinement LLM (D3: delete is refinement-only at chat-time).

        Never raises.

        Args:
            extraData: Context dict; must carry ``ensuredMessage``.
            memory_id: Delete the memory with this exact id (takes precedence).
            query: Semantic query — memories matching (similarity >= 0.85) are deleted.
            type: Optional MemoryType filter applied to the by-query search.
            **kwargs: Ignored.

        Returns:
            ``{"done": True, "deleted": int, "memory_id": str}`` (both by-id
            and by-query), or ``{"done": False, "error": ...}`` on failure.
            By-id deletes report ``deleted`` as ``1`` or ``0``; by-query
            deletes report the count of memories removed.
        """
        try:
            ensuredMessage = extraData.get("ensuredMessage") if extraData else None
            if not isinstance(ensuredMessage, EnsuredMessage):
                return {"done": False, "error": "Missing ensuredMessage"}

            chatId = ensuredMessage.recipient.id
            userId = ensuredMessage.sender.id
            threadId = ensuredMessage.threadId or DEFAULT_THREAD_ID

            if not memory_id and not query:
                return {"done": False, "error": "Provide either memory_id or query"}

            # --- By-id delete (unrestricted — can target permanent) ---------------
            if memory_id:
                deleted = await self.db.userMemories.deleteMemory(chatId, userId, memory_id)
                # Not necessary permanent one were deleted, but whatever
                await self.cache.invalidateChatUserPermanentMemories(
                    chatId=chatId,
                    userId=userId,
                    threadId=threadId,
                )
                return {"done": True, "deleted": 1 if deleted else 0, "memory_id": memory_id}

            # --- By-query delete (semantic; similarity >= 0.85 threshold) ---------
            assert query is not None  # narrowed by the guard above
            chatSettings = await self.getChatSettings(chatId)

            embeddings = await self.llmService.generateEmbedding(
                query,
                chatId=chatId,
                chatSettings=chatSettings,
            )

            if embeddings is None:
                return {"done": False, "error": "Can not generate embedding for query"}

            hits = await self.db.userMemories.searchMemories(
                chatId,
                userId,
                embeddings[1],
                threadId=threadId,
                type=type,
                embeddingModel=embeddings[0],
                limit=5,
            )
            # Only delete clear matches (similarity >= MEMORY_DEDUP_SIMILAR_THRESHOLD).
            toDelete = [m for m in hits if float(m.get("score", 0.0)) >= MEMORY_DEDUP_SIMILAR_THRESHOLD]
            deletedCount = 0
            for m in toDelete:
                mid = m["memory_id"]
                if await self.db.userMemories.deleteMemory(chatId, userId, mid):
                    deletedCount += 1
            if deletedCount > 0:
                await self.cache.invalidateChatUserPermanentMemories(
                    chatId=chatId,
                    userId=userId,
                    threadId=threadId,
                )
            return {"done": True, "deleted": deletedCount}
        except Exception as e:
            logger.exception("_llmToolDeleteMemory: failed")
            return {"done": False, "error": str(e)}

    async def _llmToolSearchMemories(
        self,
        extraData: Optional[Dict[str, object]],
        query: Optional[str] = None,
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
        permanent: Optional[bool] = None,
        user: Optional[str] = None,
        **kwargs: object,
    ) -> Dict[str, object]:
        """LLM tool: search memories, optionally for a different user (plan §8.5).

        Two modes (mirror ``UserMemoriesRepository.searchMemories``):
        ``query`` provided → semantic vec0 search; ``query`` omitted →
        filter-only scan (lets the LLM ask "all preference memories" with no
        embedding). By default searches the calling user's own memories; when
        ``user`` is provided, resolves it to a userId (login or numeric
        user_id) and searches that user's memories instead. If ``user`` is
        provided but cannot be resolved, returns an error without searching.

        Never raises.

        Args:
            extraData: Context dict; must carry ``ensuredMessage``.
            query: Natural-language query; when omitted/empty, filter-only mode.
            type: Optional MemoryType filter.
            tags: Optional tag list (ANY-match).
            limit: Max results (default ``MEMORY_SEARCH_DEFAULT_LIMIT``,
                clamped to ``MEMORY_SEARCH_MAX_LIMIT``).
            permanent: Optional permanent-flag filter.
            user: Optional identifier for a DIFFERENT user whose memories to
                search instead of the caller's. Accepts a login (with or
                without ``@``) or a numeric ``user_id``. When the login cannot
                be resolved to a known user, the tool returns
                ``{"done": False, "error": ...}`` without searching.
            **kwargs: Ignored.

        Returns:
            ``{"done": True, "results": [...], "count": int}`` on success, or
            ``{"done": False, "error": ...}`` on failure.
        """
        try:
            ensuredMessage = extraData.get("ensuredMessage") if extraData else None
            if not isinstance(ensuredMessage, EnsuredMessage):
                return {"done": False, "error": "Missing ensuredMessage"}

            chatId = ensuredMessage.recipient.id
            threadId: int = ensuredMessage.threadId or DEFAULT_THREAD_ID
            if user:
                resolvedId = await self._resolveUserId(chatId=chatId, userIdentifier=user)
                if resolvedId is None:
                    return {"done": False, "error": f"User not found: {user}"}
                userId = resolvedId
            else:
                userId = ensuredMessage.sender.id
            # Clamp limit to [1, MEMORY_SEARCH_MAX_LIMIT] (mirrors
            # ``_llmToolSearchMessages`` in ``chat_search.py``). A model passing
            # a huge ``limit`` would otherwise trigger an unbounded query and an
            # oversized vec0 ``k``.
            effectiveLimit = (
                max(1, min(int(limit), MEMORY_SEARCH_MAX_LIMIT))
                if (limit is not None and limit > 0)
                else MEMORY_SEARCH_DEFAULT_LIMIT
            )

            chatSettings = await self.getChatSettings(chatId)
            queryEmbedding = None
            trimmedQuery = (query or "").strip()
            if trimmedQuery:
                queryEmbedding = await self.llmService.generateEmbedding(
                    trimmedQuery,
                    chatId=chatId,
                    chatSettings=chatSettings,
                )

            results = await self.db.userMemories.searchMemories(
                chatId,
                userId,
                queryEmbedding[1] if queryEmbedding else None,
                threadId=threadId,
                type=type,
                tags=tags,
                permanent=permanent,
                embeddingModel=queryEmbedding[0] if queryEmbedding else None,
                limit=effectiveLimit,
            )
            return {"done": True, "results": results, "count": len(results)}
        except Exception as e:
            logger.exception("_llmToolSearchMemories: failed")
            return {"done": False, "error": str(e)}

    ###
    # Memory refinement (background CRON_JOB)
    ###
    #
    # Flow (see docs/llm/memories/user-memories.md "Refinement"):
    #   newMessageHandler increments _accounting  ->  _dtCronJob (every 60s)
    #   scans the counter, builds a due list, runs _runRefinement for each
    #   under a single global _refineLock  ->  _runRefinement fetches recent
    #   messages and curates the user_memories store LIVE via the tools
    #   (add_memory / delete_memory / search_memories); it persists ONLY the
    #   message cursor (no summary) to
    #   chat_users.metadata.memoryRefinement[threadId]. The embedding-regen
    #   cron (_runMemoryEmbeddingRegen, outside _refineLock) re-embeds stale
    #   memories whose embedding_model / dimensions drifted.

    async def _runMemoryEmbeddingRegen(self) -> None:
        """Process one batch of memory-embedding regeneration per CRON tick.

        Mirrors ``ChatSearchHandler._dtCronJob``
        (``chat_search.py:284-445``) one-to-one, adapted for the
        ``user_memories`` store. Because there is no BLOB table, model /
        dimension tracking lives on ``user_memories`` itself
        (``embedding_model`` / ``embedding_dimensions``), so stale detection
        is a single-table query (no vec0 JOIN). Per tick:

        1. **Chat discovery**: list chats with
           ``MEMORY_EMBEDDINGS_ENABLED=true`` via
           ``listChatsBySetting``, filtered through
           :meth:`ChatSettingsValue.toBool`.
        2. **Round-robin pick**: one chat per tick, advanced through
           ``_memoryBackfillIndex`` (stable order across ticks).
        3. **Per-chat gate**: bail when
           ``MEMORY_REGENERATE_EMBEDDINGS`` is explicitly false.
        4. **Model resolution**: ``EMBEDDING_MODEL`` from chat settings;
           bail when empty, unknown, or not embedding-capable.
        5. **Stale cleanup (model-drift detection)**: when the in-memory
           per-chat tracker (``_memoryEmbeddingModelTracker``) differs from
           the resolved ``modelKey``, call
           :meth:`UserMemoriesRepository.deleteObsoleteMemoryEmbeddings`
           which resets stale rows' provenance to NULL. The tracker is then
           advanced so cleanup only fires once per model switch.
        6. **Stale detection**:
           :meth:`UserMemoriesRepository.getMemoriesWithoutEmbeddings`
           (also surfaces never-embedded rows for the initial backfill).
        7. **Re-embed loop**: each ``UserMemoryDict`` is re-embedded via
           :meth:`LLMService.generateEmbedding` and persisted through
           :meth:`UserMemoriesRepository.saveMemoryEmbedding`; per-row
           failures are swallowed (``generateEmbedding`` returns ``None`` on
           error and the loop skips the save) with an inter-call sleep between
           rows.

        Almost every failure path logs and returns, but model resolution
        (step 4) is the one unguarded path: ``resolveModel`` →
        ``ChatSettingsValue.toModel`` raises ``ValueError`` when the
        configured ``EMBEDDING_MODEL`` is empty or not registered in the
        model manager. That exception propagates out of this method and is
        caught by the ``_dtCronJob`` caller (which wraps the call in
        try/except), so a regen failure never breaks the refinement body
        sharing the same tick. The two operations share the tick but NOT
        the lock (regen is read/embed/write on ``user_memories``;
        refinement is LLM-tool-driven) — see
        docs/plans/user-memories-v1.md §5.6.

        Args:
            None (uses ``self.db`` / ``self.llmService`` and the cached
            config attributes set in ``__init__``).

        Returns:
            None

        Raises:
            ValueError: from ``resolveModel``/``toModel`` when
                ``EMBEDDING_MODEL`` is empty or unregistered in the model
                manager; caught by the ``_dtCronJob`` caller.
        """
        startTime = utils.now()
        # 1. Chat discovery — MEMORY_EMBEDDINGS_ENABLED defaults to false,
        # so any chat that explicitly enabled it has a DB row (same trick
        # the chat-history cron uses with EMBEDDINGS_ENABLED).
        try:
            chatMap = await self.db.chatSettings.listChatsBySetting(key=ChatSettingsKey.MEMORY_EMBEDDINGS_ENABLED)
        except Exception as e:
            logger.warning("Memory regen: failed to list enabled chats: %s", e)
            return

        enabledChats: List[int] = sorted(
            [chatId for chatId, value in chatMap.items() if ChatSettingsValue(value).toBool()]
        )
        if not enabledChats:
            return

        # 2. Round-robin pick across ``enabledChats`` sorted by chat ID for
        # stable ordering across ticks. ``% len`` is safe because the list
        # is non-empty (checked above).
        chatId = enabledChats[self._memoryBackfillIndex % len(enabledChats)]
        self._memoryBackfillIndex += 1
        self._memoryBackfillIndex %= len(enabledChats)

        # 3-4. Per-chat gate + model resolution.
        try:
            chatSettings = await self.getChatSettings(chatId=chatId)
        except Exception as e:
            logger.warning("Memory regen: failed to read chat settings for %d: %s", chatId, e)
            return
        if not chatSettings[ChatSettingsKey.MEMORY_REGENERATE_EMBEDDINGS].toBool():
            return  # regeneration disabled for this chat

        embeddingModel = self.llmService.resolveModel(
            ChatSettingsKey.EMBEDDING_MODEL, chatSettings=chatSettings, defaultKey=ChatSettingsKey.EMBEDDING_MODEL
        )

        # 5. Stale cleanup (model-drift detection). ``modelKey`` is
        # ``modelName`` alone when the model does not expose dimensions, or
        # ``"modelName:dimensions"`` when it does (e.g. FastembedModel).
        # NOTE: unlike the chat-history analog (which returns bool and only
        # advances the tracker on success), ``deleteObsoleteMemoryEmbeddings``
        # returns an int reset-count and never raises — a caught internal
        # exception yields 0, indistinguishable from "no stale rows". The
        # tracker is therefore advanced unconditionally after the call so
        # cleanup does not re-fire every tick for the same model. A silent
        # cleanup failure leaves stale rows with their old ``embedding_model``,
        # which ``getMemoriesWithoutEmbeddings`` still surfaces for
        # re-embedding below — so the embed path self-heals even when the
        # vec0 cleanup did not (the only residual is orphaned old-dim vec0
        # rows, which do not affect search correctness).
        currentDims = await embeddingModel.getDimensions()
        modelName = chatSettings[ChatSettingsKey.EMBEDDING_MODEL].toStr()
        modelKey = modelName
        if currentDims is not None:
            modelKey = f"{modelName}:{currentDims}"
        if self._memoryEmbeddingModelTracker.get(chatId) != modelKey:
            await self.db.userMemories.deleteObsoleteMemoryEmbeddings(
                chatId=chatId,
                currentModel=modelName,
                currentDimensions=currentDims,
            )
            self._memoryEmbeddingModelTracker[chatId] = modelKey

        # 6. Stale detection. ``modelName`` is forwarded so rows embedded
        # under a different model (e.g. after a model swap) are re-surfaced.
        # A NULL ``embedding_model`` (never-embedded memory) surfaces here
        # too, so this same query serves the initial backfill.
        staleMemories: List[UserMemoryDict] = []
        try:
            staleMemories = await self.db.userMemories.getMemoriesWithoutEmbeddings(
                chatId,
                limit=self._memoryReindexBatchSize,
                modelName=modelName,
                dimensions=currentDims,
            )
        except Exception as e:
            logger.warning("Memory regen: failed to list stale memories for chat %d: %s", chatId, e)
            return
        if not staleMemories:
            return

        # 7. Re-embed loop. ``generateEmbedding`` catches its own exceptions
        # and returns ``None`` on failure, so a single bad row cannot abort
        # the batch; the small inter-call sleep keeps the asyncio loop
        # responsive between embeddings.
        embedded = 0
        for memory in staleMemories:
            # Defensive: skip a degenerate empty-content row so it does not
            # waste an embedding API call. Mirrors the sibling guard in
            # ``ChatSearchHandler._dtCronJob`` (``chat_search.py:427-428``).
            # Memories should never be empty (schema NOT NULL + ``addMemory``
            # passes non-empty content), but the guard matches the precedent.
            if not memory["content"].strip():
                continue

            memoryEmbedding = await self.llmService.generateEmbedding(
                memory["content"],
                chatId=chatId,
                chatSettings=chatSettings,
            )
            if memoryEmbedding is not None:
                if await self.db.userMemories.saveMemoryEmbedding(
                    chatId=chatId,
                    userId=memory["user_id"],
                    memoryId=memory["memory_id"],
                    embedding=memoryEmbedding[1],
                    embeddingModel=memoryEmbedding[0],
                ):
                    embedded += 1
            await asyncio.sleep(MEMORY_BACKFILL_INTER_MESSAGE_DELAY_SECS)

        if embedded > 0:
            elapsedTime = utils.now() - startTime
            logger.info(
                "Memory regen: embedded %d memories in chat %d (elapsed %.2f seconds)",
                embedded,
                chatId,
                elapsedTime.total_seconds(),
            )

    async def _dtCronJob(self, task: DelayedTask) -> None:
        """Periodic entry point for memory refinement + embedding regen. Runs every 60s.

        Two independent concerns share this 60s tick:

        1. **Memory-embedding regeneration** (Phase 3b — see
           :meth:`_runMemoryEmbeddingRegen`): discovers
           ``MEMORY_EMBEDDINGS_ENABLED`` chats round-robin, cleans stale
           embeddings on model drift, and re-embeds a small batch. Runs
           every tick OUTSIDE ``_refineLock`` (read/embed/write on
           ``user_memories``; does not contend with refinement).
        2. **Memory refinement** (the body below): scans ``_accounting``
           to build a due list, runs ``_runRefinement`` for each under the
           single global ``_refineLock``.

        The regen pass runs first (under its own try/except) so a regen
        failure can never block refinement. Both are gated on the global
        ``[user-memory].enabled`` kill switch (early-return above).

        All ``[user-memory]`` config is read ONCE in ``__init__`` and cached as
        instance attributes, so this method performs no ``configManager`` reads.
        Early-returns when the global kill switch is off, or when a previous batch
        is still running (a single LLM call can exceed the 60s tick). Otherwise
        acquires ``_refineLock`` and, under it, scans ``_accounting`` to build a
        due list (per-chat-enabled + count/time thresholds), then runs up to
        ``max-refines-per-tick`` refinements sequentially. The whole
        scan+dispatch happens inside the lock so two ticks can never overlap
        their work (closing the TOCTOU window between the ``locked()`` bail and
        lock acquisition).

        Due-list selection is an online top-K scan: a bounded ``due`` list of
        size <= ``_memoryMaxRefinesPerTick`` is maintained during the iteration,
        keeping the entries with the SMALLEST ``lastRefinedTS`` (oldest-due /
        never-refined, which carry TS=0). When the list is full and a new
        candidate has a smaller ``lastRefinedTS`` than the current max in the
        list, that max is evicted and replaced by the candidate, and the running
        max is recomputed. Never-refined users (TS=0) are deliberately NOT
        skipped: they are refined from their lifetime chat history on the first
        due tick; if too few lifetime messages exist, ``_runRefinement`` bails
        once and advances the in-memory ``_lastRefinedTS`` so the candidate is
        not retried until the count or time threshold fires again.

        Each candidate is processed in its own try/except so a transient error
        (chat settings or memory-entry read) skips just that one instead of
        aborting the whole scan. After each refinement attempt the per-key
        ``_accounting`` counter is decremented by the number of messages
        attempted (credit-consumed), clamped at 0 and dropped when it reaches 0
        so empty keys are not re-iterated.

        Known limitation (accepted risk): when ``_runRefinement`` raises, the
        ``finally`` block still subtracts ``preCount`` and may drop the key. This
        acts as accidental backoff during a provider outage, but means every
        active user pays the cost simultaneously on recovery (their counters are
        all zeroed, so they must re-cross the count/time threshold to be refined
        again). See docs/plans/memory-refine-plan-v1.md.

        Args:
            task (DelayedTask): The delayed-task payload (unused).
        """
        if not self._memoryRefineEnabled:
            return  # global kill switch off

        # Memory-embedding regeneration (Phase 3b — see
        # docs/plans/user-memories-v1.md §5.6). Runs every tick, INDEPENDENT
        # of the refinement body: it shares the 60s CRON_JOB but NOT the
        # ``_refineLock`` (regen is read/embed/write on ``user_memories``,
        # refinement is LLM-tool-driven; they do not contend). The method
        # never raises, but the guard below ensures a bug in regen can never
        # prevent the refinement pass from running on the same tick.
        try:
            await self._runMemoryEmbeddingRegen()
        except Exception:
            logger.exception(
                "Memory embedding regeneration failed; continuing to refinement",
                exc_info=True,
                stack_info=True,
            )

        # Bail this tick if a previous batch is still running (a single LLM call
        # can exceed the 60s cadence). The lock serializes everything so the
        # provider is never flooded with concurrent refinement calls.
        if self._refineLock.locked():
            return

        now = time.time()
        # Whole scan + dispatch under the lock: there is no `await` between the
        # `locked()` bail above and the acquisition here, so from asyncio's
        # point of view acquisition is instantaneous and no second tick can
        # slip past the bail check while this one is mid-scan.
        async with self._refineLock:
            # Snapshot keys to avoid mutation-during-iteration (_accounting may be
            # touched by newMessageHandler on the live event loop).
            candidates = list(self._accounting.items())
            due: List[Tuple[Tuple[int, int, int], int, int]] = []
            maxDueTS = 0
            maxDueLen = self._memoryMaxRefinesPerTick
            # We need at most `maxDueLen` items with the smallest `_lastRefinedTS`.
            # Keep a running maximum of the largest lastRefinedTS in the bounded
            # due list so a new candidate can be compared in O(1); when the list
            # is full, skip the candidate if its `_lastRefinedTS` >= `maxDueTS`,
            # otherwise evict the entry with the largest `_lastRefinedTS` and
            # recompute `maxDueTS`.
            for key, newMessagesCount in candidates:
                # Guard the ENTIRE per-candidate body so a transient DB error
                # (chat settings OR memory-entry read) skips just this one
                # candidate instead of aborting the whole scan.
                try:
                    chatId, userId, threadId = key
                    # Per-chat enable gate (runtime-disable safe).
                    chatSettings = await self.getChatSettings(chatId)
                    if not chatSettings[ChatSettingsKey.MEMORY_REFINEMENT_ENABLED].toBool():
                        # Drop this candidate from future checks
                        async with self._accountingLock:
                            self._accounting.pop(key, None)
                            self._lastRefinedTS.pop(key, None)
                        continue

                    lastRefinedTS = 0
                    async with self._accountingLock:
                        lastRefinedTS = self._lastRefinedTS.get(key, 0)
                    if (len(due) >= maxDueLen) and (lastRefinedTS >= maxDueTS):
                        # If due list is full and our lastRefinedTS >= maxDueTS
                        #  then we definitely don't match this batch
                        continue

                    elapsed = now - lastRefinedTS

                    if (newMessagesCount >= self._memoryCountThreshold) or (
                        elapsed >= self._memoryTimeThresholdSeconds
                    ):
                        newDueElem = (
                            (chatId, userId, threadId),
                            newMessagesCount,
                            lastRefinedTS,
                        )
                        # If `due` is full, replace one with maximum lastRefinedTS
                        if len(due) >= maxDueLen:
                            maxI = None
                            for i, elem in enumerate(due):
                                if elem[2] == maxDueTS:
                                    maxI = i
                                    break

                            if maxI is None:
                                logger.error(
                                    "Memory refinement: due list %s has no element with [2] == %s", due, maxDueTS
                                )
                                continue
                            due[maxI] = newDueElem
                            # recalculate maxDueTS
                            maxDueTS = lastRefinedTS
                            for elem in due:
                                maxDueTS = max(maxDueTS, elem[2])
                        else:
                            due.append(newDueElem)
                            maxDueTS = max(maxDueTS, lastRefinedTS)
                except Exception:
                    logger.exception(
                        "Memory refinement: scan failed for chatId=%s userId=%s threadId=%s",
                        chatId,
                        userId,
                        threadId,
                    )
                    continue

            if not due:
                return

            for dueEntry in due:
                key = dueEntry[0]
                preCount = dueEntry[1]
                chatId, userId, threadId = key
                try:
                    await self._runRefinement(chatId, userId, threadId)
                except Exception:
                    logger.exception(
                        "Memory refinement failed for chatId=%s userId=%s threadId=%s",
                        chatId,
                        userId,
                        threadId,
                    )
                finally:
                    if preCount >= self._memoryMaxMessagesPerRun:
                        logger.warning(
                            "Refinement fetch hit the per-run cap (%d messages) for chatId=%s userId=%s threadId=%s; "
                            "older overflow messages will be skipped. See docs/plans/memory-refine-plan-v1.md.",
                            self._memoryMaxMessagesPerRun,
                            chatId,
                            userId,
                            threadId,
                        )
                    # Credit-consumed: subtract the messages we attempted to
                    # process, preserving any increments that arrived during the
                    # (possibly slow) LLM call. Clamped at 0 so a malformed count
                    # never goes negative. Replaces the unconditional zeroing
                    # that wiped legitimate new arrivals mid-call.
                    async with self._accountingLock:
                        newVal = max(0, self._accounting.get(key, 0) - preCount)
                        if newVal > 0:
                            self._accounting[key] = newVal
                        else:
                            # If zero - drop it to not iterate next time
                            self._accounting.pop(key, None)

                        # If for some reason, there is no _lastRefinedTS for this key, set to current time
                        if key not in self._lastRefinedTS:
                            self._lastRefinedTS[key] = int(time.time())

    async def _runRefinement(self, chatId: int, userId: int, threadId: int) -> None:
        """Run one memory-refinement LLM pass for a (chat, user, thread).

        Fetches recent messages since the last processed date, pre-loads the
        user's current permanent + recent memories, then asks the LLM to curate
        the ``user_memories`` store directly via the add_memory /
        delete_memory / search_memories tools (plan §10 — Phase 4a). After the
        call only the cursor (``lastProcessedMessageId`` /
        ``lastProcessedMessageDate``) is persisted to
        ``chat_users.metadata.memoryRefinement[threadId]``; the rolling-bio
        ``summary`` is no longer written (memories persist live via the tools).

        All ``[user-memory]`` thresholds are read ONCE in ``__init__`` and cached
        as instance attributes; the prompts are read from chat settings (per-chat
        overrides of the TOML defaults).

        Args:
            chatId (int): Chat id.
            userId (int): User id.
            threadId (int): Thread id.
        """
        chatSettings = await self.getChatSettings(chatId)
        if not chatSettings[ChatSettingsKey.MEMORY_REFINEMENT_ENABLED].toBool():
            return  # runtime-disabled since the due list was built

        userMetadata = await self.cache.getUserMetadata(chatId=chatId, userId=userId)
        memoryRefinement = userMetadata.get("memoryRefinement", {}).get(str(threadId or DEFAULT_THREAD_ID), {})
        sinceDateTimeStr = memoryRefinement.get("lastProcessedMessageDate")
        sinceDateTime: Optional[datetime.datetime] = None
        if sinceDateTimeStr:
            try:
                sinceDateTime = dateutilParser.parse(sinceDateTimeStr)
            except (ValueError, OverflowError, TypeError):
                logger.warning("Unparseable lastProcessedMessageDate %r; refining from scratch", sinceDateTimeStr)
                sinceDateTime = None

        messages = await self.db.chatMessages.getChatMessagesSince(
            chatId=chatId,
            sinceDateTime=sinceDateTime,
            threadId=threadId,
            limit=self._memoryMaxMessagesPerRun,
            userId=userId,
        )
        if len(messages) < self._memoryMinMessagesToRefine:
            # Nothing new worth refining — reset the in-memory time threshold so this
            # idle (e.g. post-restart, previously-refined) user isn't re-scanned and
            # re-bailed on every 60s tick until enough new messages accumulate. The
            # count threshold still fires independently once messages pile up.
            async with self._accountingLock:
                self._lastRefinedTS[(chatId, userId, threadId)] = int(time.time())
            return  # not enough new data to refine

        # Render messages for the LLM (same pattern as SummarizationHandler._doSummarization).
        rendered = await self._renderMessagesForLLM(messages)

        # Pre-load the user's current permanent + recent memories so the LLM
        # has prior context without needing to ``search_memories`` for
        # everything (plan §10.2(a)). The old ``{existingUserData}`` /
        # ``{existingSummary}`` placeholders are gone; this snapshot replaces
        # both. Failures are tolerated (empty list) so a transient DB error
        # can't abort the run — the LLM simply has no prior context.
        try:
            # We use directDB access here instead of cache as we need full memory data for the LLM
            permanentMemories = await self.db.userMemories.getPermanentMemories(chatId, userId, threadId)
            latestMemories = await self.db.userMemories.getLatestMemories(chatId, userId, threadId)
        except Exception:
            logger.warning(
                "Failed to pre-load existing memories for %s:%s; refining without prior context",
                chatId,
                userId,
                exc_info=True,
            )
            permanentMemories = []
            latestMemories = []
        existingMemoriesText = _formatMemoriesBlockRaw(permanentMemories, latestMemories) or "(none)"

        # Synthesize a minimal EnsuredMessage so the memory tools can resolve
        # chatId/userId (they read recipient.id / sender.id).
        synthEnsuredMessage = self._makeSyntheticEnsuredMessage(chatId=chatId, userId=userId, threadId=threadId)

        systemPrompt = chatSettings[ChatSettingsKey.MEMORY_REFINE_SYSTEM_PROMPT].toStr()
        userPromptTemplate = chatSettings[ChatSettingsKey.MEMORY_REFINE_USER_PROMPT_TEMPLATE].toStr()

        # The new template uses ``{existingMemories}`` + ``{messages}`` only.
        # Note: templates referencing the old ``{existingUserData}`` /
        # ``{existingSummary}`` placeholders are no longer supported; use
        # ``{existingMemories}``. A deployed per-chat override still carrying
        # the old placeholders would raise ``KeyError`` here, caught by the
        # outer try/except (refinement stops for that user this tick).
        userPrompt = userPromptTemplate.format(
            messages=rendered,
            existingMemories=existingMemoriesText,
        )

        async def intermediateCallback(res: ModelRunResult, extraData: ExtraDataDict) -> None:
            logger.debug(f"IM# Refining memory of {chatId}:{userId}, thread:{threadId}. Result: {res}")

        logger.debug(
            f"Refining memory for {chatId}:{userId}, thread:{threadId} "
            f"with {len(messages)} messages ({messages[-1]['message_id']}..{messages[0]['message_id']}). "
            f"Pre-loaded memories: {len(permanentMemories)} permanent, {len(latestMemories)} recent."
        )
        try:
            result = await self.llmService.generateTextViaLLM(
                messages=[
                    ModelMessage(role="system", content=systemPrompt),
                    ModelMessage(role="user", content=userPrompt),
                ],
                chatId=None,  # skip rate-limiting for the background call
                chatSettings=chatSettings,
                callback=intermediateCallback,
                modelKey=ChatSettingsKey.MEMORY_REFINE_MODEL,
                fallbackModelKey=ChatSettingsKey.MEMORY_REFINE_FALLBACK_MODEL,
                useTools={
                    ToolName.ADD_MEMORY: True,
                    ToolName.DELETE_MEMORY: True,
                    ToolName.SEARCH_MEMORIES: True,
                    ToolName.SEARCH_MESSAGES: True,
                    ToolName.GET_CURRENT_DATETIME: True,
                },
                extraData={
                    "ensuredMessage": synthEnsuredMessage,
                    "typingManager": None,
                    "isRefinement": True,
                },
            )

            logger.debug(f"Result of refining memory for {chatId}:{userId}, thread:{threadId}: {result}")
        except Exception as e:
            logger.error(f"Error during refining memory of {chatId}:{userId}##{threadId}: {e}")
            logger.exception(e)
            return

        # Best-effort JSONL log of this refinement run. Placed AFTER the LLM
        # call and BEFORE the cursor persist so both populated and tool-only
        # (empty-text) runs are logged (success-path-only: an exception above
        # returns before reaching here). Mirrors AbstractModel.printJSONLog.
        # The ``summary`` field is the LLM's text output (often empty now that
        # the model emits tool calls instead of a dossier); the per-tool counts
        # are derived from ``result.toolUsageHistory`` (plan §10.2(d)).
        if self._refineLogEnabled:
            toolCounts = self._countRefinementToolCalls(result)
            self._writeRefinementJsonLog(
                chatId=chatId,
                userId=userId,
                threadId=threadId,
                login=messages[0]["username"],
                messagesCount=len(messages),
                firstMessageId=messages[-1]["message_id"].asStr(),
                lastMessageId=messages[0]["message_id"].asStr(),
                summary=(result.resultText or "").strip(),
                addCount=toolCounts.get(ToolName.ADD_MEMORY.value, 0),
                deleteCount=toolCounts.get(ToolName.DELETE_MEMORY.value, 0),
                searchCount=toolCounts.get(ToolName.SEARCH_MEMORIES.value, 0),
            )

        # Newest processed message is the FIRST entry in the DESC-ordered list.
        # Phase 4a: only the cursor is persisted — the rolling-bio ``summary``
        # is gone (memories live in ``user_memories`` via the tools now).
        newest = messages[0]
        async with self.cache.chatUserMetadataLock():
            metadata = await self.cache.getUserMetadata(chatId=chatId, userId=userId)

            memoryRefinement = metadata.get("memoryRefinement", {})
            memoryRefinement.update(
                {
                    str(threadId): {
                        "lastProcessedMessageId": newest["message_id"].asStr(),
                        "lastProcessedMessageDate": newest["date"].isoformat(),
                    }
                }
            )
            metadata["memoryRefinement"] = memoryRefinement

            await self.cache.updateUserMetadata(chatId=chatId, userId=userId, metadata=metadata)

        # Record the refinement timestamp in-memory only (not persisted to DB).
        async with self._accountingLock:
            self._lastRefinedTS[(chatId, userId, threadId)] = int(time.time())

    def _countRefinementToolCalls(self, result: ModelRunResult) -> Dict[str, int]:
        """Count tool calls by name across the refinement run's message history.

        Walks ``result.toolUsageHistory`` (the full multi-turn assistant/tool
        message sequence from :meth:`generateTextViaLLM`), counting
        ``LLMToolCall.name`` occurrences on every assistant message. Returns a
        ``{tool_name: count}`` mapping keyed by the ``ToolName`` *string value*
        (e.g. ``"add_memory"``), so callers can look up counts without importing
        the enum. Falls back to the final-turn ``result.toolCalls`` when the
        full history is absent (single-turn providers), and to an empty mapping
        when neither is populated (plan §10.2(d)).

        Args:
            result: The :class:`ModelRunResult` returned by the refinement call.

        Returns:
            Mapping of tool-name string → call count across the whole run.
        """
        counts: Dict[str, int] = {}
        history = result.toolUsageHistory
        if history:
            for msg in history:
                for tc in getattr(msg, "toolCalls", None) or []:
                    name = getattr(tc, "name", None)
                    if name:
                        counts[name] = counts.get(name, 0) + 1
        elif result.toolCalls:
            # Single-turn providers populate only the final-turn toolCalls.
            for tc in result.toolCalls:
                counts[tc.name] = counts.get(tc.name, 0) + 1
        return counts

    def _writeRefinementJsonLog(
        self,
        *,
        chatId: int,
        userId: int,
        threadId: int,
        login: str,
        messagesCount: int,
        firstMessageId: str,
        lastMessageId: str,
        summary: str,
        addCount: int = 0,
        deleteCount: int = 0,
        searchCount: int = 0,
    ) -> None:
        """Append a single JSONL line describing one memory-refinement run.

        Mirrors ``AbstractModel.printJSONLog`` (``lib/ai/abstract.py``). Writes
        are synchronous and best-effort: an IO error is logged at debug level
        and swallowed so a logging failure can never break the refinement
        pipeline (slightly safer than ``printJSONLog``, which has no try/except).

        Phase 4a: the ``summary`` field is now the LLM's raw text output
        (often empty, since the model emits tool calls instead of a dossier —
        plan §10.2(d)). The per-tool counts (``addCount`` / ``deleteCount`` /
        ``searchCount``) are the primary observability for the grey-zone dedup
        review (§15). They are derived in :meth:`_countRefinementToolCalls`.

        Args:
            chatId: Chat the refined user belongs to.
            userId: User whose memory was refined.
            threadId: Thread scope (0 = main thread).
            login: The user's username (may be empty string if none set).
            messagesCount: Number of messages analyzed in this run.
            firstMessageId: Oldest analyzed message id (serialized via
                ``MessageId.asStr()``).
            lastMessageId: Newest analyzed message id (serialized via
                ``MessageId.asStr()``).
            summary: The LLM's text output (often empty when it used tools
                instead of producing a summary). Kept for debugging.
            addCount: Number of ``add_memory`` calls in the run.
            deleteCount: Number of ``delete_memory`` calls in the run.
            searchCount: Number of ``search_memories`` calls in the run.

        Returns:
            None.
        """
        if not self._refineLogEnabled:
            return

        now = datetime.datetime.now(tz=datetime.timezone.utc)

        filename = self._refineLogFile
        if self._refineLogAddDateSuffix:
            filename = filename + "." + now.strftime("%Y-%m-%d")

        data = {
            "date": now.isoformat(),
            "chatId": chatId,
            "threadId": threadId,
            "userId": userId,
            "login": login,
            "messagesCount": messagesCount,
            "firstMessageId": firstMessageId,
            "lastMessageId": lastMessageId,
            "summary": summary,
            "addCount": addCount,
            "deleteCount": deleteCount,
            "searchCount": searchCount,
        }

        try:
            with open(filename, "a") as f:
                f.write(utils.jsonDumps(data, sort_keys=False) + "\n")
        except OSError as e:
            logger.debug("Failed to write refinement JSONL log to %s: %s", filename, e)

    async def _renderMessagesForLLM(self, messages: List[ChatMessageDict]) -> str:
        """Render a list of ChatMessageDict into a single text block for the refinement prompt.

        Reuses the canonical renderer from ``SummarizationHandler._doSummarization``:
        ``EnsuredMessage.fromDBChatMessage`` + ``formatForLLM(JSON, stripAtsign=True)``,
        so the prompt shape stays consistent with normal chat context.

        Args:
            messages (List[ChatMessageDict]): Messages (newest-first, as returned by
                ``getChatMessagesSince``).

        Returns:
            str: Rendered messages joined by newlines, oldest-first (chronological).
        """
        renderedParts: List[str] = []
        # reversed() → oldest-first for natural reading order (matches SummarizationHandler).
        for msg in reversed(messages):
            eMsg = await EnsuredMessage.fromDBChatMessage(msg, self.db, injectMemories=False)
            renderedParts.append(await eMsg.formatForLLM(self.db, format=LLMMessageFormat.JSON, stripAtsign=True))
        return "\n".join(renderedParts)

    def _makeSyntheticEnsuredMessage(self, *, chatId: int, userId: int, threadId: int) -> EnsuredMessage:
        """Build a minimal EnsuredMessage for the add_memory/delete_memory/search_memories background tool calls.

        Only ``recipient.id`` and ``sender.id`` are read by the three tool handlers, so the other
        fields are minimal placeholders. ``threadId`` IS read by the memory tools to scope new
        memories to the active thread.

        Args:
            chatId (int): Chat id (becomes recipient.id).
            userId (int): User id (becomes sender.id).
            threadId (int): Thread id (set on the synthetic message; read by the memory tools
                to scope new memories).

        Returns:
            EnsuredMessage: Synthetic message with recipient.id=chatId, sender.id=userId.
        """
        ensuredMessage = EnsuredMessage(
            sender=MessageSender(id=userId, name="", username=""),
            recipient=MessageRecipient(
                id=chatId,
                chatType=ChatType.PRIVATE if chatId > 0 else ChatType.GROUP,
            ),
            messageId=0,
            date=utils.now(),
        )
        ensuredMessage.threadId = threadId or DEFAULT_THREAD_ID
        return ensuredMessage

    ###
    # Handling user-data configuration wizard
    ###

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """Count this message toward memory refinement; consume wizard free-text input.

        Always increments the memory-refinement counter for the message's
        (chatId, userId, threadId) when refinement is enabled for the chat,
        regardless of chat type. Then, if the user has an active
        ``UserActiveActionEnum.UserDataConfig`` state (set by the
        ``_handleConfigAction_AddMemory`` flow), their free-text message is
        captured as the memory content: it is injected as
        ``ButtonDataKey.Value`` and routed through the wizard dispatcher as a
        ``SetMemoryContent`` action, after which the message is consumed
        (``FINAL``). When no wizard state is present the message flows on
        untouched (``NEXT``).

        Args:
            ensuredMessage (EnsuredMessage): Ensured message object.
            updateObj (UpdateObjectType): Telegram update object.

        Returns:
            HandlerResultStatus: ``FINAL`` when the message was consumed by the
            wizard free-text flow, otherwise ``NEXT``.
        """

        # Memory-refinement accounting: count this message if refinement is enabled for this chat.
        chatSettings = await self.getChatSettings(ensuredMessage.recipient.id)
        if chatSettings[ChatSettingsKey.MEMORY_REFINEMENT_ENABLED].toBool():
            threadId = ensuredMessage.threadId or DEFAULT_THREAD_ID
            key = (ensuredMessage.recipient.id, ensuredMessage.sender.id, threadId)
            async with self._accountingLock:
                self._accounting[key] = self._accounting.get(key, 0) + 1

        # Wizard free-text input (memory creation). When the user is mid-wizard
        # "Add memory" flow, their next free-text message IS the memory content.
        # The state is set by ``_handleConfigAction_AddMemory`` and consumed
        # here: the dispatcher (``_handleUserDataConfiguration``) clears the
        # state at its top, then routes to ``SetMemoryContent`` which persists
        # the memory. ``getUserState`` returns ``None`` for users without an
        # active wizard, so normal message flow is unaffected.
        memoryConfigState = self.cache.getUserState(
            userId=ensuredMessage.sender.id, stateKey=UserActiveActionEnum.UserDataConfig
        )
        if memoryConfigState is not None:
            await self._handleUserDataConfiguration(
                data={**memoryConfigState["data"], ButtonDataKey.Value: ensuredMessage.formatMessageText()},
                messageId=memoryConfigState["messageId"],
                messageChatId=memoryConfigState["messageChatId"],
                user=ensuredMessage.sender,
            )
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.NEXT

    async def _handleConfigAction_Init(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """
        Initialize wizard with chat selection interface.

        Args:
            data (utils.PayloadDict): Callback data from button press.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): Telegram user.
        """
        # Print list of known chats

        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )
        keyboard: List[List[CallbackButton]] = []

        for chat in await self.getUserChats(user.id):
            keyboard.append(
                [
                    CallbackButton(
                        self.getChatTitle(chat, useMarkdown=False, addChatId=False),
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                            ButtonDataKey.ChatId: chat["chat_id"],
                        },
                    )
                ]
            )

        if not keyboard:
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Чаты не найдены.",
            )
            return

        keyboard.append([exitButton])
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text="Выберите чат для настройки:",
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_ChatSelected(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """Render the MemoryType picker for the selected chat.

        Replaces the old key-value list. The user picks a ``MemoryType``
        (or "All types") to browse; each button routes to
        :meth:`_handleConfigAction_TopicSelected` carrying the type string
        in :attr:`ButtonDataKey.Key` and ``Page=0``.

        Args:
            data (utils.PayloadDict): Callback data with the selected chat ID.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): The calling user (memories are scoped to their id).
        """
        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )

        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"ChatSelected: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return

        chatInfo = await self.getChatInfo(chatId)
        if chatInfo is None:
            logger.error(f"ChatSelected: chatInfo is None in {chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: Выбран неизвестный чат",
            )
            return

        chatTitle = self.getChatTitle(chatInfo, useMarkdown=False)
        keyboard: List[List[CallbackButton]] = []
        for memType in MemoryType:
            keyboard.append(
                [
                    CallbackButton(
                        memType.value.capitalize(),
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Key: memType.value,
                            ButtonDataKey.Page: 0,
                        },
                    )
                ]
            )
        keyboard.append(
            [
                CallbackButton(
                    "Все типы",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                        ButtonDataKey.ChatId: chatId,
                        ButtonDataKey.Key: "all",
                        ButtonDataKey.Page: 0,
                    },
                )
            ]
        )
        keyboard.append(
            [
                CallbackButton(
                    "<< Назад",
                    {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Init},
                )
            ]
        )
        keyboard.append([exitButton])
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=f"Выберите тип памятей для чата {chatTitle}:",
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_TopicSelected(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """Render the first page of the memory list for the chosen type.

        Reads the type filter from :attr:`ButtonDataKey.Key` (a
        :class:`MemoryType` value or ``"all"``), the offset from
        :attr:`ButtonDataKey.Page`, and the optional tag filter from
        :attr:`ButtonDataKey.Tag` (Phase 5b), then delegates to
        :meth:`_renderMemoryList`.

        Args:
            data (utils.PayloadDict): Callback data with chat ID, type filter,
                offset, and optional tag.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): The calling user.
        """
        chatId = data.get(ButtonDataKey.ChatId, None)
        if not isinstance(chatId, int):
            logger.error(f"TopicSelected: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return

        typeFilterRaw = str(data.get(ButtonDataKey.Key, "all") or "all")
        offset = int(data.get(ButtonDataKey.Page, 0) or 0)
        # Phase 5b: optional tag filter narrows the list to memories carrying
        # the tag. Empty/absent → no tag filter.
        tag = str(data.get(ButtonDataKey.Tag, "") or "")
        await self._renderMemoryList(
            chatId=chatId,
            userId=user.id,
            typeFilterRaw=typeFilterRaw,
            offset=offset,
            messageId=messageId,
            messageChatId=messageChatId,
            tag=tag or None,
        )

    async def _renderMemoryList(
        self,
        chatId: int,
        userId: int,
        typeFilterRaw: str,
        offset: int,
        *,
        messageId: MessageId,
        messageChatId: int,
        tag: Optional[str] = None,
    ) -> None:
        """Render a paginated page of the user's memories for the given filters.

        Fetches ``KNOWLEDGE_CONFIG_PAGE_SIZE + 1`` rows (the +1 detects a
        next page without a separate ``COUNT(*)`` query), then renders one
        button per memory (truncated content preview), the tag-filter row
        (Phase 5b), pagination nav (prev/next) when applicable, a "back to
        types" button, and exit.

        Thread scoping: ``threadId=None`` is passed to ``searchMemories`` so
        memories from ALL threads (including cross-thread ``NULL``) appear —
        the wizard has no thread picker (by design, see plan §11.6).

        Tag filter (Phase 5b): when *tag* is set, ``searchMemories`` is called
        with ``tags=[tag]`` (ANY-match post-filter). Because the tags
        post-filter runs AFTER the SQL offset inside ``searchMemories``, a
        plain SQL-paginated fetch would straddle trimmed rows — so under a tag
        filter we fetch up to ``KNOWLEDGE_CONFIG_TAG_FILTER_FETCH_LIMIT`` rows
        at offset 0 and paginate the filtered result in Python. The tag rides
        on the pagination (Next/Prev) payloads so the filter persists across
        pages; it does NOT ride on the per-memory (``MemorySelected``) buttons
        because those payloads are already near the 64-byte ``callback_data``
        ceiling (32-char UUID + chatId + offset) — viewing a memory and
        returning drops the filter (documented v1 limitation).

        Args:
            chatId: The selected chat whose memories are browsed.
            userId: The calling user's id (memories are scoped to them).
            typeFilterRaw: ``"all"`` for no type filter, else a
                :class:`MemoryType` value.
            offset: Zero-based page offset (number of memories to skip).
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            tag: Optional tag filter; when set, only memories carrying this
                tag are listed.
        """
        # "all" → no type filter; otherwise validate the MemoryType value.
        typeForQuery: Optional[str] = None if typeFilterRaw == "all" else typeFilterRaw
        try:
            if tag:
                # Tag filter active: the tags post-filter inside searchMemories
                # runs after the SQL offset, so fetch a generous batch at
                # offset 0 and paginate the filtered result in Python.
                allFiltered = await self.db.userMemories.searchMemories(
                    chatId,
                    userId,
                    None,
                    type=typeForQuery,
                    tags=[tag],
                    threadId=None,
                    limit=KNOWLEDGE_CONFIG_TAG_FILTER_FETCH_LIMIT,
                    embeddingModel=None,
                    offset=0,
                )
                hasNext = len(allFiltered) > offset + KNOWLEDGE_CONFIG_PAGE_SIZE
                pageMemories = allFiltered[offset : offset + KNOWLEDGE_CONFIG_PAGE_SIZE]
            else:
                memories = await self.db.userMemories.searchMemories(
                    chatId,
                    userId,
                    None,
                    type=typeForQuery,
                    threadId=None,
                    limit=KNOWLEDGE_CONFIG_PAGE_SIZE + 1,
                    embeddingModel=None,
                    offset=offset,
                )
                hasNext = len(memories) > KNOWLEDGE_CONFIG_PAGE_SIZE
                pageMemories = memories[:KNOWLEDGE_CONFIG_PAGE_SIZE]
        except Exception:
            logger.error("TopicSelected: failed to fetch memories for chat %d user %d", chatId, userId, exc_info=True)
            pageMemories = []
            hasNext = False

        typeLabel = "все" if typeFilterRaw == "all" else typeFilterRaw

        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )
        keyboard: List[List[CallbackButton]] = []
        for mem in pageMemories:
            preview = self._truncateForButton(mem.get("content", ""))
            keyboard.append(
                [
                    # Payload ~58-64 bytes for supergroups; 32-char UUID + up to
                    # 16-char chatId + action + offset. Overflows Telegram's
                    # 64-byte callback_data limit at ~1000+ offset for 17-char
                    # chatIds — acceptable v1 limit (no runtime guard; pagination
                    # caps results at KNOWLEDGE_CONFIG_PAGE_SIZE so high offsets
                    # are rare in practice).
                    # NOTE (Phase 5b): the active tag is intentionally NOT
                    # carried here — adding ``tg:<tag>`` would overflow the
                    # 64-byte ceiling. Returning from the detail view therefore
                    # drops the tag filter (documented v1 limitation).
                    CallbackButton(
                        preview,
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.MemorySelected,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Key: mem["memory_id"],
                            ButtonDataKey.Page: offset,
                        },
                    )
                ]
            )

        # "Add memory" button — only offered when a specific MemoryType is
        # selected (NOT for "all"), so the new memory inherits a concrete type.
        # The payload carries the current type filter + offset so the AddMemory
        # handler can route back to the same list position after creation, and
        # so the SetMemoryContent flow knows which type to assign.
        if typeFilterRaw != "all":
            keyboard.append(
                [
                    CallbackButton(
                        "➕ Добавить память",
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.AddMemory,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Key: typeFilterRaw,
                            ButtonDataKey.Page: offset,
                        },
                    )
                ]
            )

        # Tag-filter row (Phase 5b). When a tag is active, show the active tag
        # + a clear button; otherwise show the "filter by tag" entry button.
        # The TagFilter payload carries the type + offset so the picker can
        # return to the same list position.
        if tag:
            keyboard.append(
                [
                    CallbackButton(
                        f"Фильтр: #{tag} (изменить)",
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TagFilter,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Key: typeFilterRaw,
                            ButtonDataKey.Page: offset,
                        },
                    )
                ]
            )
            keyboard.append(
                [
                    CallbackButton(
                        "Сбросить фильтр",
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Key: typeFilterRaw,
                            ButtonDataKey.Page: 0,
                        },
                    )
                ]
            )
        else:
            keyboard.append(
                [
                    CallbackButton(
                        "Фильтр по тегу",
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TagFilter,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Key: typeFilterRaw,
                            ButtonDataKey.Page: offset,
                        },
                    )
                ]
            )

        navRow: List[CallbackButton] = []
        if offset > 0:
            prevPayload: utils.PayloadDict = {
                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.PrevPage,
                ButtonDataKey.ChatId: chatId,
                ButtonDataKey.Key: typeFilterRaw,
                ButtonDataKey.Page: offset,
            }
            if tag:
                # Prev/Next carry the tag so the filter persists across pages.
                prevPayload[ButtonDataKey.Tag] = tag
            navRow.append(CallbackButton("<< Назад", prevPayload))
        if hasNext:
            nextPayload: utils.PayloadDict = {
                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.NextPage,
                ButtonDataKey.ChatId: chatId,
                ButtonDataKey.Key: typeFilterRaw,
                ButtonDataKey.Page: offset,
            }
            if tag:
                nextPayload[ButtonDataKey.Tag] = tag
            navRow.append(CallbackButton("Вперёд >>", nextPayload))
        if navRow:
            keyboard.append(navRow)
        keyboard.append(
            [
                CallbackButton(
                    "<< Назад к типам",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                        ButtonDataKey.ChatId: chatId,
                    },
                )
            ]
        )
        keyboard.append([exitButton])

        if not pageMemories:
            if tag:
                text = f"Памятей с тегом #{tag} не найдено."
            else:
                text = "Памятей не найдено."
        else:
            if tag:
                text = f"Памяти (тип: {typeLabel}, тег: #{tag}):"
            else:
                text = f"Памяти (тип: {typeLabel}):"

        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=text,
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_MemorySelected(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """Render the per-memory detail view with a delete action.

        Fetches the memory by id (:meth:`getMemory`), renders its content,
        type, tags, permanent flag, source, ``updated_at``, and thread
        scope, plus "Delete" (→ DeleteMemory) and "Back" (→ TopicSelected
        carrying the memory's type + the page offset the user came from).

        Args:
            data (utils.PayloadDict): Callback data with chat ID, memory id, and offset.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): The calling user.
        """
        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )
        chatId = data.get(ButtonDataKey.ChatId, None)
        if not isinstance(chatId, int):
            logger.error(f"MemorySelected: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return

        memoryId = str(data.get(ButtonDataKey.Key, "") or "")
        offset = int(data.get(ButtonDataKey.Page, 0) or 0)

        memory = await self.db.userMemories.getMemory(chatId, user.id, memoryId)
        if memory is None:
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Память не найдена (возможно, она была удалена).",
                inlineKeyboard=[
                    [
                        CallbackButton(
                            "<< Назад к списку",
                            {
                                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                                ButtonDataKey.ChatId: chatId,
                                ButtonDataKey.Key: "all",
                                ButtonDataKey.Page: offset,
                            },
                        )
                    ],
                    [exitButton],
                ],
            )
            return

        memType = str(memory.get("type", ""))
        tags = memory.get("tags") or []
        tagSuffix = " ".join(f"#{t}" for t in tags if t)
        permanentLabel = "да" if memory.get("permanent") else "нет"
        threadId = memory.get("thread_id")
        threadLabel = "кросс-поток (постоянная)" if threadId is None else f"поток {threadId}"
        updatedAt = memory.get("updated_at")
        updatedLabel = updatedAt.strftime("%Y-%m-%d %H:%M") if updatedAt else "?"

        content = str(memory.get("content", ""))
        text = (
            f"{_formatMemoryLine(memory)}\n\n"
            f"**Тип**: {memType}\n"
            f"**Теги**: {tagSuffix or '—'}\n"
            f"**Постоянная**: {permanentLabel}\n"
            f"**Источник**: {memory.get('source', '—')}\n"
            f"**Поток**: {threadLabel}\n"
            f"**Обновлена**: {updatedLabel}\n\n"
            f"**Содержание**:\n```\n{content}\n```"
        )

        keyboard: List[List[CallbackButton]] = [
            [
                CallbackButton(
                    "Удалить память",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.DeleteMemory,
                        ButtonDataKey.ChatId: chatId,
                        ButtonDataKey.Key: memoryId,
                        ButtonDataKey.Page: offset,
                    },
                )
            ],
            [
                CallbackButton(
                    "<< Назад к списку",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                        ButtonDataKey.ChatId: chatId,
                        # Carry the memory's own type so Back returns to the same filtered list.
                        ButtonDataKey.Key: memType,
                        ButtonDataKey.Page: offset,
                    },
                )
            ],
            [exitButton],
        ]
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=text,
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_DeleteMemory(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """Delete the selected memory and render a success-or-error confirmation.

        Calls :meth:`deleteMemory` (unrestricted by-id — the wizard is an
        explicit user action) and inspects its ``bool`` return: ``True`` →
        the success confirmation is rendered; ``False`` (no row matched,
        e.g. already deleted) or a raised exception → a distinct error
        message is rendered instead. The delete is a permanent, irreversible
        action, so silently reporting success on failure would be a
        trust/privacy bug — the user must be told when nothing was removed.

        The confirmation's back button returns to the memory list at the same
        offset. Since the memory is now gone its type is unknown, so the back
        button re-lists "all types" (the user can re-pick a type filter if
        desired) — this keeps the callback payload within Telegram's 64-byte
        ``callback_data`` limit (carrying the type alongside the memory id +
        chat id + offset would overflow for large group chat ids).

        Args:
            data (utils.PayloadDict): Callback data with chat ID, memory id, and offset.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): The calling user.
        """
        chatId = data.get(ButtonDataKey.ChatId, None)
        if not isinstance(chatId, int):
            logger.error(f"DeleteMemory: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return

        memoryId = str(data.get(ButtonDataKey.Key, "") or "")
        offset = int(data.get(ButtonDataKey.Page, 0) or 0)

        # Capture the bool return so a no-op delete (row already gone) or a
        # raised exception both surface as a failure to the user — never a
        # false "deleted" confirmation. The try/except keeps the wizard from
        # crashing on a transient DB error.
        deleted = False
        try:
            deleted = await self.db.userMemories.deleteMemory(chatId, user.id, memoryId)
            await self.cache.invalidateChatUserPermanentMemories(chatId=chatId, userId=user.id, threadId=None)
        except Exception:
            logger.error("DeleteMemory: failed to delete memory %s in chat %d", memoryId, chatId, exc_info=True)
            deleted = False

        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )
        keyboard: List[List[CallbackButton]] = [
            [
                CallbackButton(
                    "<< Назад к списку",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                        ButtonDataKey.ChatId: chatId,
                        ButtonDataKey.Key: "all",
                        ButtonDataKey.Page: offset,
                    },
                )
            ],
            [exitButton],
        ]
        if deleted:
            text = "Память удалена"
        else:
            text = "Не удалось удалить памят (возможно, она уже удалена)."
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=text,
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_NextPage(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """Advance the memory list one page forward.

        Carries the optional tag filter (Phase 5b) from the payload through to
        :meth:`_renderMemoryList` so the filter persists across pages.

        Args:
            data (utils.PayloadDict): Callback data with chat ID, type filter, current
                offset, and optional tag.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): The calling user.
        """
        chatId = data.get(ButtonDataKey.ChatId, None)
        if not isinstance(chatId, int):
            logger.error(f"NextPage: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return
        typeFilterRaw = str(data.get(ButtonDataKey.Key, "all") or "all")
        offset = int(data.get(ButtonDataKey.Page, 0) or 0) + KNOWLEDGE_CONFIG_PAGE_SIZE
        tag = str(data.get(ButtonDataKey.Tag, "") or "")
        await self._renderMemoryList(
            chatId=chatId,
            userId=user.id,
            typeFilterRaw=typeFilterRaw,
            offset=offset,
            messageId=messageId,
            messageChatId=messageChatId,
            tag=tag or None,
        )

    async def _handleConfigAction_PrevPage(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """Step the memory list one page backward (clamped at 0).

        Carries the optional tag filter (Phase 5b) from the payload through to
        :meth:`_renderMemoryList` so the filter persists across pages.

        Args:
            data (utils.PayloadDict): Callback data with chat ID, type filter, current
                offset, and optional tag.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): The calling user.
        """
        chatId = data.get(ButtonDataKey.ChatId, None)
        if not isinstance(chatId, int):
            logger.error(f"PrevPage: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return
        typeFilterRaw = str(data.get(ButtonDataKey.Key, "all") or "all")
        offset = max(0, int(data.get(ButtonDataKey.Page, 0) or 0) - KNOWLEDGE_CONFIG_PAGE_SIZE)
        tag = str(data.get(ButtonDataKey.Tag, "") or "")
        await self._renderMemoryList(
            chatId=chatId,
            userId=user.id,
            typeFilterRaw=typeFilterRaw,
            offset=offset,
            messageId=messageId,
            messageChatId=messageChatId,
            tag=tag or None,
        )

    @staticmethod
    def _truncateForButton(text: str, maxLen: int = 50) -> str:
        """Truncate text for an inline-keyboard button label.

        Keeps the keyboard scannable: long memory contents collapse to a
        short preview. Single-line (newlines → spaces) and capped at
        *maxLen* characters with an ellipsis when trimmed.

        Args:
            text: The source string (memory content).
            maxLen: Maximum character count before truncation (default 50).

        Returns:
            The single-line, length-capped preview string.
        """
        oneLine = " ".join(str(text).split())
        if len(oneLine) <= maxLen:
            return oneLine
        return oneLine[: maxLen - 1].rstrip() + "…"

    async def _handleConfigAction_TagFilter(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """Render the tag picker for tag-based filtering (Phase 5b).

        Fetches the distinct set of tags the user actually uses (via
        :meth:`UserMemoriesRepository.getDistinctTags`) for the selected chat
        and type,         then renders one button per tag. Selecting a tag returns to
        :meth:`_handleConfigAction_TopicSelected` with the tag applied
        (``ButtonDataKey.Tag`` set, offset reset to 0). A "clear filter"
        button returns to ``TopicSelected`` with no tag (drops the filter),
        and a back button returns to the list preserving the current filter
        and the caller's page offset.

        Args:
            data (utils.PayloadDict): Callback data with chat ID, type filter
                (``ButtonDataKey.Key``), offset, and optional current tag
                (``ButtonDataKey.Tag``) for the back button.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): The calling user.
        """
        chatId = data.get(ButtonDataKey.ChatId, None)
        if not isinstance(chatId, int):
            logger.error(f"TagFilter: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return

        typeFilterRaw = str(data.get(ButtonDataKey.Key, "all") or "all")
        memoryType: Optional[str] = None if typeFilterRaw == "all" else typeFilterRaw
        currentTag = str(data.get(ButtonDataKey.Tag, "") or "")
        # Preserve the caller's page offset so the back button returns to the
        # same scroll position (the entry button carries the correct offset).
        offset = int(data.get(ButtonDataKey.Page, 0) or 0)

        try:
            tags = await self.db.userMemories.getDistinctTags(chatId, user.id, memoryType)
        except Exception:
            logger.error(
                "TagFilter: failed to fetch distinct tags for chat %d user %d",
                chatId,
                user.id,
                exc_info=True,
            )
            tags = []

        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )

        # Back button returns to the list preserving the current filter state
        # and the caller's page offset (so clicking through the tag picker and
        # back does not reset scroll position).
        backPayload: utils.PayloadDict = {
            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
            ButtonDataKey.ChatId: chatId,
            ButtonDataKey.Key: typeFilterRaw,
            ButtonDataKey.Page: offset,
        }
        if currentTag:
            backPayload[ButtonDataKey.Tag] = currentTag

        keyboard: List[List[CallbackButton]] = []

        if not tags:
            # No tags available in this scope — still offer back + exit.
            keyboard.append([CallbackButton("<< Назад", backPayload)])
            keyboard.append([exitButton])
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="У вас нет тегов в памятях этого типа.",
                inlineKeyboard=keyboard,
            )
            return

        # One button per tag. Selecting a tag applies it as the filter and
        # resets the offset to 0. Payload byte budget for a supergroup chatId
        # (~14 chars) + longest MemoryType (``relationship`` = 11 chars) + a
        # ~10-char tag: ``c:..,d:ts,k:relationship,p:0,tg:<tag>`` ≈ 56 bytes —
        # fits under Telegram's 64-byte callback_data ceiling.
        for tag in tags:
            keyboard.append(
                [
                    CallbackButton(
                        f"#{tag}",
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Key: typeFilterRaw,
                            ButtonDataKey.Tag: tag,
                            ButtonDataKey.Page: 0,
                        },
                    )
                ]
            )

        # Clear-filter button (no Tag → unfiltered TopicSelected).
        keyboard.append(
            [
                CallbackButton(
                    "Сбросить фильтр",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                        ButtonDataKey.ChatId: chatId,
                        ButtonDataKey.Key: typeFilterRaw,
                        ButtonDataKey.Page: 0,
                    },
                )
            ]
        )
        keyboard.append([CallbackButton("<< Назад", backPayload)])
        keyboard.append([exitButton])

        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text="Выберите тег для фильтрации:",
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_AddMemory(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """Prompt the user for free-text memory content (AddMemory flow).

        Sets a :class:`UserActiveActionEnum.UserDataConfig` state so the user's
        next free-text message is captured by :meth:`newMessageHandler` and
        routed back into the wizard as a ``SetMemoryContent`` action carrying
        the typed text on :attr:`ButtonDataKey.Value`. The state payload carries
        the selected chat + ``MemoryType`` (read from ``Key``) so the created
        memory inherits a concrete type — the "Add memory" button is only
        offered for a specific type, never ``"all"``.

        Args:
            data (utils.PayloadDict): Callback data with chat ID, the selected
                ``MemoryType`` value (``Key``), and the current page offset.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): The calling user.
        """
        chatId = data.get(ButtonDataKey.ChatId, None)
        if not isinstance(chatId, int):
            logger.error(f"AddMemory: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return

        typeFilterRaw = str(data.get(ButtonDataKey.Key, "") or "")
        offset = int(data.get(ButtonDataKey.Page, 0) or 0)

        # Validate the type is a known MemoryType (defensive — the button only
        # appears for specific types, but a crafted payload could carry "all").
        try:
            typeLabel = MemoryType(typeFilterRaw).value
        except ValueError:
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: выберите конкретный тип памяти.",
            )
            return

        # Capture the caller's page offset so the back button returns to the
        # same scroll position. The state payload is consumed by
        # ``newMessageHandler`` on the user's next free-text message.
        self.cache.setUserState(
            userId=user.id,
            stateKey=UserActiveActionEnum.UserDataConfig,
            value={
                "data": {
                    ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.SetMemoryContent,
                    ButtonDataKey.ChatId: chatId,
                    ButtonDataKey.Key: typeFilterRaw,
                },
                "messageId": messageId,
                "messageChatId": messageChatId,
            },
        )

        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )
        keyboard: List[List[CallbackButton]] = [
            [
                CallbackButton(
                    "<< Отмена",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                        ButtonDataKey.ChatId: chatId,
                        ButtonDataKey.Key: typeFilterRaw,
                        ButtonDataKey.Page: offset,
                    },
                )
            ],
            [exitButton],
        ]
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=f'Введите текст для новой памят типа "{typeLabel}":',
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_SetMemoryContent(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """Process free-text input from the AddMemory flow and persist a memory.

        Reads the content from :attr:`ButtonDataKey.Value` (injected by
        :meth:`newMessageHandler` from the user's free-text message), validates
        it is non-empty, and inserts a new ephemeral, user-authored memory of
        the type selected in the AddMemory step. The memory is created with no
        embedding (``embedding=None`` / ``embeddingModel=None``) — the embedding
        regen cron re-embeds it later. The user-state set by
        :meth:`_handleConfigAction_AddMemory` is cleared at the top of
        :meth:`_handleUserDataConfiguration` before this handler runs.

        Manual-memory attributes (fixed by design — see plan §memory-creation):
        ``permanent=False`` (ephemeral), ``source=UserMemorySource.USER``,
        ``tags=[]``, ``threadId=DEFAULT_THREAD_ID`` (the wizard is private-chat
        only), ``embedding``/``embeddingModel`` = ``None``.

        Args:
            data (utils.PayloadDict): Callback data with chat ID, the selected
                ``MemoryType`` value (``Key``), and the content (``Value``).
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): The calling user (memories are scoped to id).
        """
        chatId = data.get(ButtonDataKey.ChatId, None)
        if not isinstance(chatId, int):
            logger.error(f"SetMemoryContent: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return

        typeFilterRaw = str(data.get(ButtonDataKey.Key, "") or "")
        content = str(data.get(ButtonDataKey.Value, "") or "").strip()

        # Validate the type is a known MemoryType before attempting the insert.
        try:
            memoryType = MemoryType(typeFilterRaw)
        except ValueError:
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный тип памяти.",
            )
            return

        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )

        if not content:
            keyboard: List[List[CallbackButton]] = [
                [
                    CallbackButton(
                        "<< Назад к списку",
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Key: typeFilterRaw,
                            ButtonDataKey.Page: 0,
                        },
                    )
                ],
                [exitButton],
            ]
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Содержание не может быть пустым.",
                inlineKeyboard=keyboard,
            )
            return

        # Persist the memory. The wizard never crashes — a transient DB error
        # renders a distinct failure message rather than propagating the
        # exception out of the callback handler.
        memoryId = uuid.uuid4().hex
        try:
            await self.db.userMemories.addMemory(
                chatId,
                user.id,
                memoryId,
                type=memoryType,
                content=content,
                tags=[],
                permanent=False,
                threadId=DEFAULT_THREAD_ID,
                source=UserMemorySource.USER,
                embedding=None,
                embeddingModel=None,
            )
        except Exception:
            logger.error(
                "SetMemoryContent: failed to add memory in chat %d user %d",
                chatId,
                user.id,
                exc_info=True,
            )
            keyboard = [
                [
                    CallbackButton(
                        "<< Назад к списку",
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Key: typeFilterRaw,
                            ButtonDataKey.Page: 0,
                        },
                    )
                ],
                [exitButton],
            ]
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Не удалось добавить память.",
                inlineKeyboard=keyboard,
            )
            return

        keyboard = [
            [
                CallbackButton(
                    "<< Назад к списку",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                        ButtonDataKey.ChatId: chatId,
                        ButtonDataKey.Key: typeFilterRaw,
                        ButtonDataKey.Page: 0,
                    },
                )
            ],
            [exitButton],
        ]
        preview = content[:200]
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=f"Память добавлена:\n```\n{preview}\n```",
            inlineKeyboard=keyboard,
        )

    async def _handleUserDataConfiguration(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """
        Route configuration actions to appropriate handlers.

        Args:
            data (utils.PayloadDict): Callback data with action and parameters.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): Telegram user.
        """

        self.cache.clearUserState(userId=user.id, stateKey=UserActiveActionEnum.UserDataConfig)

        action = data.get(ButtonDataKey.UserDataConfigAction, None)
        if action not in ButtonUserDataConfigAction.all():
            logger.error(f"_handleUserDataConfiguration: Invalid action: {action}")
            return
        action = ButtonUserDataConfigAction(action)

        match action:
            case ButtonUserDataConfigAction.Init:
                await self._handleConfigAction_Init(data, messageId=messageId, messageChatId=messageChatId, user=user)
            case ButtonUserDataConfigAction.Cancel:
                await self.editMessage(
                    messageId=messageId,
                    chatId=messageChatId,
                    text="Настройка закончена, буду ждать вас снова",
                )
            case ButtonUserDataConfigAction.ChatSelected:
                await self._handleConfigAction_ChatSelected(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.TopicSelected:
                await self._handleConfigAction_TopicSelected(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.MemorySelected:
                await self._handleConfigAction_MemorySelected(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.DeleteMemory:
                await self._handleConfigAction_DeleteMemory(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.NextPage:
                await self._handleConfigAction_NextPage(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.PrevPage:
                await self._handleConfigAction_PrevPage(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.TagFilter:
                await self._handleConfigAction_TagFilter(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.AddMemory:
                await self._handleConfigAction_AddMemory(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.SetMemoryContent:
                await self._handleConfigAction_SetMemoryContent(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )

            case _:
                logger.error(f"_handleUserDataConfiguration: Invalid action: {action}")
                await self.editMessage(
                    messageId=messageId,
                    chatId=messageChatId,
                    text=f"Unknown action: {action}",
                )
                return

    async def callbackHandler(
        self,
        ensuredMessage: EnsuredMessage,
        data: utils.PayloadDict,
        user: MessageSender,
        updateObj: UpdateObjectType,
    ) -> HandlerResultStatus:
        """
        Handle button callbacks for user data configuration.

        Args:
            ensuredMessage (EnsuredMessage): Ensured message object.
            data (utils.PayloadDict): Parsed callback data.
            user (MessageSender): Telegram user.
            updateObj (UpdateObjectType): Telegram update object.

        Returns:
            HandlerResultStatus: FINAL if handled, SKIPPED if not.
        """

        userDataAction = data.get(ButtonDataKey.UserDataConfigAction, None)
        if userDataAction is not None:
            await self._handleUserDataConfiguration(
                data,
                messageId=ensuredMessage.messageId,
                messageChatId=ensuredMessage.recipient.id,
                user=user,
            )
            return HandlerResultStatus.FINAL

        return HandlerResultStatus.SKIPPED

    ###
    # COMMANDS Handlers
    ###

    @commandHandlerV2(
        commands=("get_my_data",),
        shortDescription="<chatId> - Dump data, bot knows about you in this chat",
        helpMessage=" [`<chatId>`]: Показать запомненную информацию о Вас в указанном (или текущем) чате.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE, CommandPermission.GROUP},
        helpOrder=CommandHandlerOrder.TECHNICAL,
        category=CommandCategory.TOOLS,
    )
    async def get_my_data_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Dump the caller's own memories for a chat as a readable list.

        Repointed at ``user_memories`` (Phase 5a) — the legacy
        ``user_data`` key-value dump is retired. Renders every memory for
        ``(targetChatId, sender)`` across all types and threads (no type /
        thread filter) as ``[type] content #tags`` lines, one per line,
        wrapped in a code block. ``availableFor`` stays
        ``{PRIVATE, GROUP}`` so it works in both contexts.

        Args:
            ensuredMessage (EnsuredMessage): Ensured message object.
            command (str): Command name.
            args (str): Command arguments (optional chat ID).
            UpdateObj (UpdateObjectType): Telegram update object.
            typingManager (Optional[TypingManager]): Typing manager instance.
        """

        targetChatId = utils.extractInt(args.split(maxsplit=1))
        if targetChatId is None:
            targetChatId = ensuredMessage.recipient.id

        memories = await self.db.userMemories.searchMemories(
            targetChatId,
            ensuredMessage.sender.id,
            None,
            threadId=None,
            limit=MEMORY_SEARCH_MAX_LIMIT,
            embeddingModel=None,
        )
        if not memories:
            lines = ["(памятей не найдено)"]
        else:
            lines = [_formatMemoryLine(mem) for mem in memories]

        await self.sendMessage(
            ensuredMessage,
            messageText="```\n" + "\n".join(lines) + "\n```",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandlerV2(
        commands=("memory_config",),
        shortDescription="Start wizard for user-data management",
        helpMessage=": Запустить мастер управления памятью бота о вас.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE},
        helpOrder=CommandHandlerOrder.WIZARDS,
        category=CommandCategory.PRIVATE,
    )
    async def memory_config_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """
        Start interactive user data configuration wizard (private chats only).

        Args:
            ensuredMessage (EnsuredMessage): Ensured message object.
            command (str): Command name.
            args (str): Command arguments.
            UpdateObj (UpdateObjectType): Telegram update object.
            typingManager (Optional[TypingManager]): Typing manager instance.
        """

        msg = await self.sendMessage(
            ensuredMessage,
            messageText="Запускаю мастер управления памятью бота о вас...",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
        if msg:
            await self._handleUserDataConfiguration(
                {
                    ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Init,
                },
                messageId=msg[0].messageId,
                messageChatId=msg[0].recipient.id,
                user=ensuredMessage.sender,
            )
        else:
            logger.error("Failed to send message")
