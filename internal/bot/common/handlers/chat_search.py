"""Chat search handler for Gromozeka bot.

This module provides the `ChatSearchHandler` class which implements the
`/search` user command and the periodic embedding backfill CRON_JOB.
The command relies on the chat-message repository's search path
(filter-only or semantic) to fetch matching messages, then renders them
as a raw, formatted list so the user can see exactly what matched. No
LLM summary is produced — the LLM would only paraphrase the same hits
the user can read themselves.

Commands:
    - ``/search [args]`` - search chat history and display the results

CRON_JOB:
    - `_dtCronJob` - embed a small batch of pending messages for one
      chat (round-robin across chats with embeddings enabled).

The handler follows the conditional-registration pattern: it is only
loaded when ``[search-history].enabled = true`` in the merged TOML
config (see `HandlersManager.__init__` in `manager.py`).
"""

import asyncio
import datetime
import json
import logging
from collections.abc import MutableSet
from enum import StrEnum
from typing import Any, Dict, List, Optional, Tuple, cast

import lib.utils as libUtils
from internal.bot.common.models import UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.constants import (
    BACKFILL_DEFAULT_BATCH_SIZE,
    BACKFILL_INTER_MESSAGE_DELAY_SECS,
    MAX_GET_MESSAGES_BATCH,
    SEARCH_DEFAULT_DAYS,
    SEARCH_DEFAULT_MAX_RESULTS,
    SEARCH_TOOL_MAX_MESSAGE_LENGTH,
    ToolName,
)
from internal.bot.models import (
    BotProvider,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatType,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    MessageRecipient,
    commandHandlerV2,
)
from internal.bot.models.enums import LLMMessageFormat
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.models import ChatMessageDict, ChatUserDict, MessageCategory
from internal.models import MessageId
from internal.services.llm.models import ExtraDataDict
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction
from lib.ai import LLMFunctionParameter, LLMParameterType
from lib.db.utils import DEFAULT_THREAD_ID

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class _CategoryGroup(StrEnum):
    """User-facing category aliases accepted by `/search` `category:` arg.

    Maps to the underlying `MessageCategory` enum members via
    `_CATEGORY_GROUPS` below. The aliases mirror the buckets that
    `SummarizationHandler` uses to pick the message categories it
    summarises over.
    """

    USER = "user"
    BOT = "bot"
    SYSTEM = "system"
    CHANNEL = "channel"


_CATEGORY_GROUPS: Dict[_CategoryGroup, List[MessageCategory]] = {
    _CategoryGroup.USER: [
        MessageCategory.USER,
        MessageCategory.USER_COMMAND,
        MessageCategory.USER_CONFIG_ANSWER,
    ],
    _CategoryGroup.BOT: [
        MessageCategory.BOT,
        MessageCategory.BOT_COMMAND_REPLY,
        MessageCategory.BOT_SUMMARY,
        MessageCategory.BOT_RESENDED,
        MessageCategory.BOT_ERROR,
    ],
    _CategoryGroup.SYSTEM: [
        MessageCategory.USER_SPAM,
        MessageCategory.BOT_SPAM_NOTIFICATION,
        MessageCategory.DELETED,
        MessageCategory.UNSPECIFIED,
    ],
    _CategoryGroup.CHANNEL: [
        MessageCategory.CHANNEL,
    ],
}


def _coerceToolBool(value: Any, default: bool = True) -> bool:
    """Coerce an LLM-provided tool parameter to a real bool.

    The model occasionally sends boolean tool arguments as JSON strings
    (``"true"`` / ``"false"``). A naive ``bool(value)`` would treat any
    non-empty string — including ``"false"`` — as truthy, which silently
    flips the parameter's meaning. This helper normalises the common
    shapes the tool layer can receive.

    An explicit ``None`` / JSON ``null`` is treated as "parameter omitted"
    and resolves to ``True`` — the default for the tool params that use
    this helper (e.g. ``current_thread_only``) — rather than falling
    through to ``bool(None)`` → ``False``.

    Args:
        value: Raw value from the model (bool, int, float, str, or
            ``None`` for an explicit JSON null).

    Returns:
        The coerced boolean. ``None`` yields ``True`` (matches the
        parameter default). Strings are matched case-insensitively
        against ``{"true", "1", "yes", "y", "on"}`` (everything else is
        ``False``), so e.g. ``"false"`` correctly yields ``False`` (unlike
        ``bool("false")``).
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on"}
    return bool(value)


class ChatSearchHandler(BaseBotHandler):
    """Handler for chat history search and embedding backfill.

    Provides two surfaces, both backed by the chat-message repository's
    search path:

    1. The `/search` command: parse a small DSL of ``key: value`` arguments
       (``keywords``, ``user``, ``days``, ``category``, ``thread``), pull
       the matching messages out of the database, filter client-side by
       keyword substring when provided, and return the matching messages
       formatted as a raw, human-readable list. When keywords are
       provided, the query is also embedded (if the chat's
       ``EMBEDDING_MODEL`` supports it) so the repository can do a
       semantic ranking pass on top of the SQL filter.
    2. The `_dtCronJob` background task (registered against
       ``DelayedTaskFunction.CRON_JOB``): every minute, pick one chat
       with ``EMBEDDINGS_ENABLED=true`` in round-robin order and embed
       a small batch of its un-embedded messages. Catches up chats that
       flipped the feature on with pre-existing messages.

    The handler is purely additive — `newMessageHandler` always returns
    `SKIPPED` so other handlers in the chain (notably `LLMMessageHandler`)
    can still process the same message. The work happens in the
    command method (dispatched by `HandlersManager.handleCommand`) and
    in the backfill CRON_JOB (dispatched by `QueueService`).
    """

    def __init__(self, *, configManager: ConfigManager, database: Database, botProvider: BotProvider) -> None:
        """Initialize the chat search handler.

        Caches the `[search-history]` config block (so `/search` can read
        its defaults without touching `ConfigManager` on every call) and
        subscribes to the ``CRON_JOB`` delayed-task channel for the
        backfill tick.

        Args:
            configManager: Configuration manager providing bot settings.
            database: Database wrapper for data persistence.
            botProvider: Bot provider type (Telegram, Max).
        """
        super().__init__(configManager=configManager, database=database, botProvider=botProvider)

        # Cache the `[search-history]` config, the `[search-history.defaults]`
        # sub-section, and the `[search-history.embeddings].reindex-batch-size`
        # sub-sub-section. `ConfigManager.getSearchHistoryConfig()` returns
        # `{}` when the section is missing, so the `.get()` chain stays
        # safe even on mis-configured deployments.
        searchConfig = self.configManager.getSearchHistoryConfig()
        defaultsConfig: Dict[str, Any] = searchConfig.get("defaults", {}) or {}
        self._maxResults: int = int(defaultsConfig.get("max-results", SEARCH_DEFAULT_MAX_RESULTS))
        self._defaultDays: int = int(defaultsConfig.get("default-days", SEARCH_DEFAULT_DAYS))
        # Cache the per-tick batch size for the backfill CRON_JOB so
        # `_dtCronJob` does not have to re-read the config every minute.
        # A config flip therefore requires a bot restart to take effect.
        embeddingsConfig: Dict[str, Any] = searchConfig.get("embeddings", {}) or {}
        self._reindexBatchSize: int = int(embeddingsConfig.get("reindex-batch-size", BACKFILL_DEFAULT_BATCH_SIZE))

        # Round-robin index for the backfill CRON_JOB. Survives across
        # ticks so a long backlog gets drained chat-by-chat in stable
        # order rather than re-shuffling every minute.
        self._backfillIndex: int = 0

        # In-memory tracking of the last embedding model seen per chat
        # (``chatId -> modelKey``). ``modelKey`` is ``modelName`` alone
        # when the model does not expose embedding dimensions, or
        # ``"modelName:dimensions"`` when it does (e.g. ``FastembedModel``).
        # Used by ``_dtCronJob`` to skip redundant cleanup on every tick —
        # obsolete-embedding deletion only fires once per model switch.
        self._embeddingModelTracker: Dict[int, str] = {}

        # In-memory set of chat IDs that have seen at least one inbound
        # message since startup (populated by `newMessageHandler` when
        # ``EMBEDDINGS_ENABLED=true``). The backfill CRON_JOB (`_dtCronJob`)
        # processes ONLY chats in this set.
        #
        # This is INTENTIONAL design, not a limitation: there is deliberately
        # NO startup DB-scan that re-enrolls every chat. Chats that are no
        # longer active (dead/abandoned) are not backfilled — a chat with a
        # pre-existing embedding backlog is picked up only once it receives a
        # new message, which proves it is still active. Eviction is one-way:
        # a chat is removed (`.discard()`) when ``EMBEDDINGS_ENABLED`` flips
        # to false and is not re-added until the next qualifying message.
        self._trackedChats: MutableSet[int] = set()

        # Register backfill CRON_JOB. Multiple handlers can subscribe to
        # the same `DelayedTaskFunction` (they run in registration order
        # — see `QueueService.registerDelayedTaskHandler`), so the
        # HandlersManager's own `CRON_JOB` cleanup tick keeps running
        # unaffected. The `DO_EXIT` task is handled by the queue
        # service's own built-in handler — registering an extra no-op
        # subscriber here would be redundant.
        self.queueService.registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB, self._dtCronJob)

        # Register LLM tool: semantic search over chat history.
        self.llmService.registerTool(
            name=ToolName.SEARCH_MESSAGES,
            description=(
                "Search over chat history. Supports semantic search by query (requires embeddings) "
                "and exact case-insensitive substring filtering. Results can be scoped to the current "
                "thread (default)."
            ),
            parameters=[
                LLMFunctionParameter(
                    name="query",
                    description="Search query text",
                    type=LLMParameterType.STRING,
                ),
                LLMFunctionParameter(
                    name="limit",
                    description="Maximum results to return (default 5, max 100)",
                    type=LLMParameterType.NUMBER,
                    required=False,
                ),
                LLMFunctionParameter(
                    name="max_age_days",
                    description="Only messages newer than this many days",
                    type=LLMParameterType.NUMBER,
                    required=False,
                ),
                LLMFunctionParameter(
                    name="user_name",
                    description="Filter by username (with or without @) or numeric user_id",
                    type=LLMParameterType.STRING,
                    required=False,
                ),
                LLMFunctionParameter(
                    name="thread_message_id",
                    description="Restrict to thread rooted at this message ID",
                    type=LLMParameterType.STRING,
                    required=False,
                ),
                LLMFunctionParameter(
                    name="current_thread_only",
                    description=(
                        "When true (default), restrict the search to the same thread/topic the current "
                        "message belongs to. Set to false to search the whole chat. An explicit "
                        "thread_message_id overrides this."
                    ),
                    type=LLMParameterType.BOOLEAN,
                    required=False,
                ),
                LLMFunctionParameter(
                    name="substring",
                    description=(
                        "Case-insensitive exact substring to match in message text "
                        "(e.g. 'meeting' matches a message containing '...the Meeting was...'). "
                        "When provided without a query, performs a pure text search with no semantic "
                        "ranking and no embeddings required."
                    ),
                    type=LLMParameterType.STRING,
                    required=False,
                ),
            ],
            handler=self._llmToolSearchMessages,
        )

        # Register LLM tool: list users with activity stats.
        self.llmService.registerTool(
            name=ToolName.LIST_USERS,
            description="List chat participants with activity statistics (message count and last active time).",
            parameters=[
                LLMFunctionParameter(
                    name="limit",
                    description="Maximum users to return (default 20)",
                    type=LLMParameterType.NUMBER,
                    required=False,
                ),
                LLMFunctionParameter(
                    name="min_messages",
                    description="Only users with at least this many messages",
                    type=LLMParameterType.NUMBER,
                    required=False,
                ),
            ],
            handler=self._llmToolListUsers,
        )

        # Register LLM tool: get conversation thread for a message.
        self.llmService.registerTool(
            name=ToolName.GET_THREAD,
            description=(
                "Retrieve the full conversation thread for a specific message by its ID. "
                "Returns root message, target message, and all replies in chronological order."
            ),
            parameters=[
                LLMFunctionParameter(
                    name="message_id",
                    description="Message ID to get thread for",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
            ],
            handler=self._llmToolGetThread,
        )

        # Register LLM tool: fetch full content of messages by ID.
        # Used by the model to read the originals underlying a condensed
        # summary (summaries carry ``coveredMessageIds``). Pure DB lookup —
        # NOT gated on EMBEDDINGS_ENABLED or ALLOW_TOOLS_COMMANDS (the latter
        # gates slash commands only). Registered whenever the handler loads
        # (``[search-history].enabled``) and sent to the model only when the
        # chat's ``USE_TOOLS`` setting is true.
        self.llmService.registerTool(
            name=ToolName.GET_MESSAGES_BY_IDS,
            description=(
                "Retrieve the full content of one or more chat messages by their IDs. "
                "Use this to read the original messages underlying a condensed summary "
                "(summaries carry coveredMessageIds). Returns each message in the same "
                "JSON shape as regular user messages, plus a notFound list for IDs that "
                "did not resolve. Messages are scoped to the current chat. "
            ),
            parameters=[
                LLMFunctionParameter(
                    name="message_ids",
                    description='List of message ID strings to retrieve (e.g. ["100", "101"]).',
                    type=LLMParameterType.ARRAY,
                    required=True,
                    # extra={"items": {"type": "string"}},
                ),
            ],
            handler=self._llmToolGetMessagesByIds,
        )

    ###
    # Backfill CRON_JOB
    ###

    async def _dtCronJob(self, task: DelayedTask) -> None:
        """Process one batch of embeddings per CRON_JOB tick.

        Runs every 60 seconds (the ``CRON_JOB`` cadence in
        :class:`QueueService`). Per tick:

        1. **Chat discovery (in-memory)**: round-robin over
           ``self._trackedChats``, a ``MutableSet[int]`` populated by
           :meth:`newMessageHandler` whenever it sees a message in a chat
           with ``EMBEDDINGS_ENABLED=true``. Cold-start tradeoff: the set
           is empty on restart and only grows from live message
           activity, so a quiet chat with a pre-existing backlog is not
           backfilled until a new message arrives (intentional — the old
           DB-scanning discovery path was removed). Eviction is one-way:
           a chat that later disables embeddings (or regen) is removed
           from the set in step 2 and is not re-added until the next
           qualifying message.
        2. **Per-chat gate (runtime re-validation)**: bail — and evict
           from ``_trackedChats`` — when ``EMBEDDINGS_ENABLED`` is now
           explicitly false. Because
           membership is driven by live messages, a chat that flips a
           setting off between messages is dropped here rather than
           re-scanned every tick.
        3. Round-robin: pick the next chat in stable order, advance
           ``_backfillIndex``.
        4. Resolve the chat's embedding model from its ``EMBEDDING_MODEL``
           setting. Bail out if the model is missing, unknown, or does
           not support embeddings.
        5. **Clean up obsolete embeddings on model change**: Call
           ``ChatEmbeddingsRepository.deleteObsoleteModelEmbeddings``
           which removes rows from both ``message_embeddings`` and all
           ``vec_message_embeddings_{N}`` tables where the stored model
           differs from ``modelName``. Gated by an in-memory tracking
           dict (``_embeddingModelTracker``) so cleanup only fires once
           per model switch — subsequent ticks are no-ops until the
           model changes again.
        6. Fetch up to ``[search-history.embeddings].reindex-batch-size``
           (default ``BACKFILL_DEFAULT_BATCH_SIZE``) messages without
           embeddings and embed them one by one, with a small inter-call
           sleep to keep the asyncio loop responsive.
        7. Per-message errors are caught and logged — one bad row never
           aborts the batch.
        8. Backfill runs continuously while ``EMBEDDINGS_ENABLED=true``: the
           per-tick batch is small and the next minute's tick will pick up
           where this one left off.

        Args:
            task: The CRON_JOB delayed task firing this handler. Ignored.

        Returns:
            None
        """
        startTime = libUtils.now()
        # Gate 1: discover chats that explicitly opted in to a backfill
        if not self._trackedChats:
            return

        # Round-robin pick across ``chatList`` sorted by chat ID for
        # stable ordering across CRON_JOB ticks. ``% len`` is safe because
        # ``chatList`` is non-empty (checked above), so a zero-division
        # never lands.
        chatList = sorted(self._trackedChats)
        chatId = chatList[self._backfillIndex % len(chatList)]
        self._backfillIndex += 1
        self._backfillIndex %= len(chatList)

        # Gate 3: resolve the embedding model.
        try:
            chatSettings = await self.getChatSettings(chatId=chatId)
        except Exception as e:
            logger.warning("Backfill: failed to read chat settings for %d: %s", chatId, e)
            return
        if not chatSettings[ChatSettingsKey.EMBEDDINGS_ENABLED].toBool():
            self._trackedChats.discard(chatId)
            return  # embeddings regeneration disabled for this chat

        modelName = chatSettings[ChatSettingsKey.EMBEDDING_MODEL].toStr()
        if not modelName:
            logger.warning("Embedding model isn't configured for chat#%d", chatId)
            return
        model = self.llmService.getLLMManager().getModel(modelName)
        if model is None or not model.supportsEmbedding:
            return

        # Delete obsolete embeddings (both message_embeddings and vec0)
        # when the model changed since the last cleanup for this chat.
        # Tracked per-chat via _embeddingModelTracker to avoid redundant
        # work on every CRON tick — cleanup only fires on model switch.
        # ``modelKey`` is ``modelName`` alone when the model does not
        # expose embedding dimensions, or ``"modelName:dimensions"``
        # when it does (e.g. ``FastembedModel.embeddingDimensions``).
        currentDims = await model.getDimensions()
        modelKey = modelName
        if currentDims is not None:
            modelKey = f"{modelName}:{currentDims}"
        if self._embeddingModelTracker.get(chatId) != modelKey:
            # Pass dimensions when available so the repository can
            # correctly handle same-name/different-dimension switches
            # (a model reconfigured from 384 to 1024 dims keeps the same
            # ``model`` column value but its rows must still be deleted).
            # Only update the tracker when cleanup succeeds — a failed
            # cleanup is retried on the next tick rather than treated as
            # complete.
            if await self.db.chatEmbeddings.deleteObsoleteModelEmbeddings(
                chatId=chatId,
                currentModel=modelName,
                currentDimensions=currentDims,
            ):
                self._embeddingModelTracker[chatId] = modelKey

        # Gate 4: fetch the batch. ``_reindexBatchSize`` is cached in
        # `__init__` so this read costs nothing per tick. ``modelName``
        # is forwarded so rows with a stored embedding under a *different*
        # model (e.g. after a model swap) are re-embedded — the
        # `getMessagesWithoutEmbeddings` repo method matches that
        # contract.
        pendingMessagesList: List[ChatMessageDict] = []
        try:
            pendingMessagesList = await self.db.chatEmbeddings.getMessagesWithoutEmbeddings(
                chatId,
                limit=self._reindexBatchSize,
                modelName=modelName,
                dimensions=currentDims,
            )
        except Exception as e:
            logger.warning("Backfill: failed to list pending messages for chat %d: %s", chatId, e)
            return
        if not pendingMessagesList:
            return

        # Embed each message via the shared helper. The helper has its
        # own try/except boundary and never raises, so a single bad row
        # cannot abort the batch; the small inter-call sleep keeps the
        # asyncio loop responsive between embeddings.
        embedded = 0
        for pendingMessage in pendingMessagesList:
            ensuredMessage = await EnsuredMessage.fromDBChatMessage(data=pendingMessage, db=self.db)

            if await self.embedAndSaveMessage(ensuredMessage=ensuredMessage):
                embedded += 1
            await asyncio.sleep(BACKFILL_INTER_MESSAGE_DELAY_SECS)

        if embedded > 0:
            elapsedTime = libUtils.now() - startTime
            logger.info(
                "Backfill: embedded %d messages in chat %d (elapsed %.2f seconds)",
                embedded,
                chatId,
                elapsedTime.total_seconds(),
            )

    async def embedAndSaveMessage(self, ensuredMessage: EnsuredMessage) -> bool:
        """Embed a single message and persist its vector.

        Background-only helper invoked from the backfill CRON_JOB loop
        (``_dtCronJob``). **Never raises**: any exception is logged and
        surfaced as ``False`` so a single bad row never aborts the batch
        (the caller relies on this never-crash contract).

        Passes ``doRateLimit=False`` to :meth:`LLMService.generateEmbedding`
        so the background backfill does NOT consume the per-chat hot-path
        rate budget, while still passing the real ``chatId`` so the
        ``llm_request`` stats row is attributed to the chat instead of
        landing under ``__global__``.

        Args:
            ensuredMessage: The message to embed + persist.

        Returns:
            ``True`` when an embedding was generated and saved, ``False``
            otherwise (no vector produced, DB write failure, or any exception).
        """
        try:
            messageText: str = await ensuredMessage.formatForLLM(
                self.db,
                format=LLMMessageFormat.TEXT,
                useSingleMedia=False,
                cache=None,
            )
            embeddings: Optional[Tuple[str, List[float]]] = None
            if messageText.strip():
                embeddings = await self.llmService.generateEmbedding(
                    messageText,
                    chatId=ensuredMessage.recipient.id,
                    chatSettings=await self.getChatSettings(ensuredMessage.recipient.id),
                    doRateLimit=False,
                )
            if embeddings is not None:
                return await self.db.chatEmbeddings.saveMessageEmbedding(
                    chatId=ensuredMessage.recipient.id,
                    messageId=ensuredMessage.messageId,
                    embedding=embeddings[1],
                    model=embeddings[0],
                    date=ensuredMessage.date.isoformat() if ensuredMessage.date is not None else None,
                )
            return False
        except Exception:
            logger.exception(
                "embedAndSaveMessage: failed to embed message %s in chat %d",
                ensuredMessage.messageId,
                ensuredMessage.recipient.id,
            )
            return False

    ###
    # LLM tool: semantic search over chat history
    ###

    async def _llmToolSearchMessages(
        self,
        extraData: Optional[ExtraDataDict],
        query: str = "",
        limit: int = 5,
        max_age_days: Optional[int] = None,
        user_name: Optional[str] = None,
        thread_message_id: Optional[str] = None,
        current_thread_only: bool = True,
        substring: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """LLM tool: semantic search over chat history.

        Called by the LLM when it needs to find messages matching a
        natural-language query. Returns structured results as a dict
        so the LLM service can serialise them back into the model
        context. All errors are folded into the return dict — this
        method never raises.

        Two search flavours compose:

        - **Semantic** (``query`` provided): requires
          ``EMBEDDINGS_ENABLED``. The query is embedded via
          :meth:`LLMService.generateEmbedding` (which owns model
          resolution and returns ``None`` on internal failure) and ranked
          against chat history. If no vector is produced (``None``) or the
          boundary itself raises, the tool returns an
          ``Unable to generate query embedding`` error rather than
          degrading to filter-only.
        - **Substring / filter-only** (``query`` empty but
          ``substring``/``user_name``/``max_age_days``/thread scoping
          set): runs WITHOUT embeddings — the ``EMBEDDINGS_ENABLED``
          gate is skipped so the tool stays useful in chats that have
          not turned embeddings on.

        Args:
            extraData: Context dict with ``ensuredMessage`` key.
            query: Search query text. When empty, the search falls
                back to pure text/substring filtering (no embeddings).
            limit: Max results (default 5).
            max_age_days: Only messages newer than this many days.
            user_name: Filter by username (with or without @) or numeric user_id.
            thread_message_id: Restrict to thread rooted at this message
                ID. When provided, it overrides ``current_thread_only``.
            current_thread_only: When ``True`` (default) and no explicit
                ``thread_message_id`` resolves, restrict the search to
                the thread/topic of the current message. Set to ``False``
                to search the whole chat.
            substring: Case-insensitive exact substring to match in
                message text. Normalised (stripped) here; the repository
                wraps it into ``%...%``.
            **kwargs: Additional keyword arguments (ignored).

        Returns:
            ``{"done": True, "results": [...], "count": N}`` on success,
            or ``{"done": False, "error": "..."}`` on failure.
        """
        # Gate 1: validate chat context.
        if extraData is None or "ensuredMessage" not in extraData:
            return {"done": False, "error": "Missing chat context"}
        ensuredMessage = extraData["ensuredMessage"]
        chatId = ensuredMessage.recipient.id

        # Coerce ``current_thread_only`` to a real bool: the LLM may send a
        # JSON string such as "false", which ``bool("false")`` would
        # mis-handle (any non-empty string is truthy). Done before any use.
        current_thread_only = _coerceToolBool(current_thread_only)

        # Clamp limit to prevent abuse (Issue 4).
        effectiveLimit = int(limit) if limit is not None else 5
        limit = max(1, min(effectiveLimit, 100))

        # Gate 2: check per-chat settings (wrapped in try/except — see Issue 1).
        try:
            chatSettings = await self.getChatSettings(chatId=chatId)
        except Exception:
            logger.exception("search_messages: failed to load chat settings for chat %d", chatId)
            return {"done": False, "error": "Unable to get chat settings"}
        # The embeddings gate applies only to semantic search. A pure
        # substring/filter search works without embeddings so the tool
        # stays useful in chats that have not enabled them.
        if query and not chatSettings[ChatSettingsKey.EMBEDDINGS_ENABLED].toBool():
            return {"done": False, "error": "Semantic search disabled for this chat"}

        # Gate 2b: rate-limit before embedding generation.
        try:
            await self.llmService.rateLimit(chatId, chatSettings)
        except Exception:
            logger.exception("search_messages: rate-limit check failed")
            return {"done": False, "error": "Rate limit reached"}

        # Gate 3: resolve optional user filter.
        userId: Optional[int] = None
        if user_name:
            userId = await self._resolveUserId(chatId=chatId, userIdentifier=user_name)

        # Gate 4: resolve optional thread filter.
        threadMessageId: Optional[MessageId] = None
        if thread_message_id is not None:
            try:
                threadMessageId = MessageId(thread_message_id)
            except (ValueError, TypeError):
                pass  # invalid value — skip thread filter

        # Thread scoping: an explicit ``thread_message_id`` overrides
        # ``current_thread_only``. Otherwise, when ``current_thread_only``
        # is set (the default), restrict to the current message's
        # thread/topic (``ensuredMessage.threadId`` falls back to the
        # main thread id ``DEFAULT_THREAD_ID = 0`` when unset).
        effectiveThreadId: Optional[int] = None
        if threadMessageId is None and current_thread_only:
            effectiveThreadId = ensuredMessage.threadId or DEFAULT_THREAD_ID

        # Normalise the substring once: strip whitespace, treat empty as
        # "no filter". The repository wraps the raw value into ``%...%``.
        normalizedSubstring: Optional[str] = (
            substring.strip() if isinstance(substring, str) and substring.strip() else None
        )

        # Gate 5: generate query embedding (semantic mode only).
        # When ``query`` is empty the search runs in filter-only/substring
        # mode and never touches the embedding model, so embedding-related
        # settings and failures do not apply.
        queryEmbedding: Optional[Tuple[str, List[float]]] = None
        if query:
            try:
                queryEmbedding = await self.llmService.generateEmbedding(
                    query,
                    chatId=ensuredMessage.recipient.id,
                    chatSettings=chatSettings,
                )
                if queryEmbedding is None:
                    raise Exception("Embedding generation failed")
            except Exception as e:
                logger.exception(f"search_messages: failed to generate query embedding: {e}")
                return {"done": False, "error": "Unable to generate query embedding"}

        # Gate 6: resolve per-chat message cap.
        maxMessages: Optional[int] = None
        if ChatSettingsKey.MAX_MESSAGES_FOR_SEMANTIC_SEARCH in chatSettings:
            # toInt() returns 0 on parse failure; 0 or None -> unlimited.
            # A value of 0 means "disabled/unlimited" per the config default.
            maxMessages = chatSettings[ChatSettingsKey.MAX_MESSAGES_FOR_SEMANTIC_SEARCH].toInt() or None

        # Execute search.
        try:
            results = await self.db.chatSearch.searchChatMessages(
                chatId=chatId,
                queryEmbedding=queryEmbedding[1] if queryEmbedding else None,
                limit=limit,
                userFilter=userId,
                maxAgeDays=max_age_days,
                rootMessageId=threadMessageId,
                modelName=queryEmbedding[0] if queryEmbedding else None,
                maxMessages=maxMessages,
                threadId=effectiveThreadId,
                substring=normalizedSubstring,
            )
        except Exception as e:
            logger.error("search_messages: search failed")
            logger.exception(e)
            return {"done": False, "error": "Error during history search"}

        # Format results in parallel using the same pattern as
        # ``_llmToolGetThread`` does for thread messages, with
        # ``return_exceptions=True`` so a single bad row never aborts
        # the batch.
        try:
            rawFormatted = await asyncio.gather(
                *[self._formatMessageDict(r) for r in results],
                return_exceptions=True,
            )
        except Exception:
            logger.exception("search_messages: formatting failed")
            return {"done": False, "error": "Error during formatting result"}

        formatted: List[Dict[str, Any]] = []
        for r, retMsg in zip(results, rawFormatted):
            if isinstance(retMsg, Exception):
                logger.warning("search_messages: failed to format result: %s", retMsg)
                continue
            retMsg = cast(Dict[str, Any], retMsg)
            if "text" in retMsg and len(retMsg["text"]) > SEARCH_TOOL_MAX_MESSAGE_LENGTH:
                retMsg["text"] = retMsg["text"][: SEARCH_TOOL_MAX_MESSAGE_LENGTH - 1] + "…"
            retMsg["score"] = r.get("score", 0.0)
            formatted.append(retMsg)

        return {"done": True, "results": formatted, "count": len(formatted)}

    ###
    # LLM tool: list chat participants
    ###

    async def _llmToolListUsers(
        self,
        extraData: Optional[ExtraDataDict],
        limit: int = 20,
        min_messages: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """LLM tool: list chat participants with activity statistics.

        Thin wrapper over :meth:`_listUsersInternal`.

        Args:
            extraData: Context dict with ``ensuredMessage`` key.
            limit: Maximum users to return (default 20).
            min_messages: Only users with at least this many messages.
            **kwargs: Additional keyword arguments (ignored).

        Returns:
            Dict with ``done`` (bool), ``users`` (list of user dicts),
            ``count`` (int), and optionally ``error`` (str).
        """
        # Gate 1: validate chat context.
        if extraData is None or "ensuredMessage" not in extraData:
            return {"done": False, "error": "Missing chat context"}
        chatId = extraData["ensuredMessage"].recipient.id

        # Clamp limit to prevent abuse.
        effectiveLimit = int(limit) if limit is not None else 20
        limit = max(1, min(effectiveLimit, 200))
        # Coerce min_messages to int — LLM NUMBER can arrive as float.
        minMessages: Optional[int] = int(min_messages) if min_messages is not None else None

        # Execute.
        try:
            users = await self._listUsersInternal(chatId=chatId, limit=limit, minMessages=minMessages)
        except Exception:
            logger.exception("list_users: failed to list users")
            return {"done": False, "error": "Не удалось получить список участников"}

        formatted: List[Dict[str, Any]] = []
        for u in users:
            updatedAt = u.get("updated_at")
            if isinstance(updatedAt, datetime.datetime):
                lastActive = updatedAt.isoformat()
            elif updatedAt is None:
                lastActive = ""
            else:
                lastActive = str(updatedAt)
            formatted.append(
                {
                    "user_id": u.get("user_id", 0),
                    "username": u.get("username", ""),
                    "full_name": u.get("full_name", ""),
                    "messages_count": u.get("messages_count", 0),
                    "last_active": lastActive,
                }
            )
        return {"done": True, "users": formatted, "count": len(formatted)}

    ###
    # LLM tool: get conversation thread
    ###

    async def _formatMessageDict(self, msg: ChatMessageDict) -> Dict[str, Any]:
        """Convert a ``ChatMessageDict`` row to a JSON-safe dict for LLM tool output.

        Uses :meth:`EnsuredMessage.formatForLLM` with JSON format so the
        result is directly serialisable back into the model context.

        Args:
            msg: A ``ChatMessageDict`` row from the repository.

        Returns:
            JSON-safe dict with ``message_id``, ``message_text``,
            ``username``, ``full_name``, ``date``, ``reply_id``,
            and ``thread_id``.
        """
        eMessage = await EnsuredMessage.fromDBChatMessage(msg, self.db)
        return json.loads(
            await eMessage.formatForLLM(
                self.db,
                format=LLMMessageFormat.JSON,
                useSingleMedia=False,
                cache=None,
            )
        )

    async def _llmToolGetThread(
        self,
        extraData: Optional[ExtraDataDict],
        message_id: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """LLM tool: retrieve the full conversation thread for a message.

        Calls :meth:`ChatMessagesRepository.getMessageThread`.

        Args:
            extraData: Context dict with ``ensuredMessage`` key.
            message_id: Message ID to get the thread for.
            **kwargs: Additional keyword arguments (ignored).

        Returns:
            Dict with ``done`` (bool), ``root_message`` (optional dict),
            ``target_message`` (dict or None), ``thread_messages`` (list),
            and optionally ``error`` (str).
        """
        # Gate 1: validate chat context.
        if extraData is None or "ensuredMessage" not in extraData:
            return {"done": False, "error": "Missing chat context"}
        chatId = extraData["ensuredMessage"].recipient.id

        # Gate 2: validate message ID.
        try:
            msgId = MessageId(message_id)
        except (ValueError, TypeError):
            return {"done": False, "error": "Неверный идентификатор сообщения"}

        # Gate 3: fetch the thread.
        try:
            thread = await self.db.chatMessages.getMessageThread(chatId=chatId, messageId=msgId)
        except Exception:
            logger.exception("get_thread: failed to get thread for message %s", message_id)
            return {"done": False, "error": "Не удалось получить тред"}
        if thread is None:
            return {"done": False, "error": "Сообщение не найдено в этом чате"}

        rootMsg = thread.get("root_message")
        threadMessages: List[ChatMessageDict] = thread.get("thread_messages", [])
        targetMsg = thread.get("target_message")
        if targetMsg is None:
            return {"done": False, "error": "Целевое сообщение не найдено"}

        try:
            rootFormatted = await self._formatMessageDict(rootMsg) if rootMsg is not None else None
            targetFormatted = await self._formatMessageDict(targetMsg)
            # Format remaining thread messages in parallel since they are
            # independent of each other.
            formattedThreadMessages = await asyncio.gather(*[self._formatMessageDict(m) for m in threadMessages])
        except Exception:
            logger.exception("get_thread: failed to format thread messages")
            return {"done": False, "error": "Не удалось отформатировать тред"}
        return {
            "done": True,
            "root_message": rootFormatted,
            "target_message": targetFormatted,
            "thread_messages": list(formattedThreadMessages),
        }

    ###
    # LLM tool: get messages by ids
    ###

    async def _llmToolGetMessagesByIds(
        self,
        extraData: Optional[ExtraDataDict],
        message_ids: Optional[List] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """LLM tool: fetch the full content of one or more messages by ID.

        Retrieves messages by ID from the current chat (scoped via
        ``extraData["ensuredMessage"]``). Intended for reading the
        original messages underlying a condensed summary — condensed
        summaries carry ``coveredMessageIds``, which the model passes
        straight through here. Pure DB lookup: each returned message dict
        matches the JSON shape of regular user messages (via
        :meth:`_formatMessageDict`).

        Gating: registered when ``[search-history].enabled`` loads this
        handler, and sent to the model only when the chat's ``USE_TOOLS``
        setting is true (the single chat-time LLM-tool gate). NOT gated on
        ``ALLOW_TOOLS_COMMANDS`` (that setting gates slash commands of
        ``CommandCategory.TOOLS`` only) or ``EMBEDDINGS_ENABLED``. Never
        raises — every failure path returns ``{"done": False, "error": ...}``
        (the whole body is wrapped in a top-level ``try/except Exception``).

        Args:
            extraData: Context dict with an ``ensuredMessage`` key used
                for chat scoping (``extraData["ensuredMessage"].recipient.id``).
            message_ids: List of message ID strings to retrieve. ``None``,
                empty, or all-blank → empty result set (no error). Items
                are de-duplicated, blank/``None`` entries are dropped, and
                the list is clamped to :data:`MAX_GET_MESSAGES_BATCH`.
            **kwargs: Additional keyword arguments (ignored).

        Returns:
            ``{"done": True, "messages": [...], "notFound": [...],
            "count": N}`` on success, where each message dict matches
            :meth:`EnsuredMessage.formatForLLM` JSON output (identical
            shape to the real user messages the LLM sees) and
            ``notFound`` lists the requested IDs that did not resolve in
            this chat. Returns ``{"done": False, "error": "..."}`` on any
            failure (missing chat context, bad input, or any unexpected
            exception).
        """
        try:
            # Gate 1: validate chat context.
            if extraData is None or "ensuredMessage" not in extraData:
                return {"done": False, "error": "Missing chat context"}
            chatId = extraData["ensuredMessage"].recipient.id

            # Gate 2: validate + clamp input. Dedup (preserve first-seen
            # order), drop blanks/None, coerce to str (the ``extra=
            # {"items": {"type": "string"}}`` override on the emitted schema
            # is COMMENTED OUT at the tool registration site — see the
            # ``message_ids`` parameter near ``_llmToolGetMessagesByIds``
            # registration — so the model can return non-string items; the
            # ``str(mid).strip()`` + ``MessageId(midStr)`` coercion below is
            # the actual never-raise safety net), and clamp to
            # MAX_GET_MESSAGES_BATCH to cap abuse.
            notFound: List[str] = []
            messageIdList: List[MessageId] = []
            if message_ids:
                seen: set[str] = set()
                for mid in message_ids:
                    if mid is None:
                        continue
                    try:
                        midStr = str(mid).strip()
                    except Exception:
                        continue  # unstringifiable junk — skip, never raise
                    if not midStr or midStr in seen:
                        continue
                    seen.add(midStr)
                    messageIdList.append(MessageId(midStr))
                    if len(messageIdList) >= MAX_GET_MESSAGES_BATCH:
                        break

            if not messageIdList:
                return {"done": True, "messages": [], "notFound": notFound, "count": 0}

            # Batch fetch (chat-scoped by the repository).
            rows: List[ChatMessageDict] = await self.db.chatMessages.getChatMessagesByMessageIds(chatId, messageIdList)

            # Format each row via the shared helper in parallel;
            # return_exceptions=True keeps one bad row from aborting the
            # whole batch (same pattern as _llmToolSearchMessages).
            rawFormatted = await asyncio.gather(
                *[self._formatMessageDict(r) for r in rows],
                return_exceptions=True,
            )

            messages: List[Dict[str, Any]] = []
            foundStrs: set[str] = set()
            for r, ret in zip(rows, rawFormatted):
                # The row was resolved from the DB, so its id counts as
                # "found" regardless of whether formatting succeeded — a
                # format failure is NOT a resolution failure, and the
                # tool contract says notFound = "IDs that did not
                # resolve". Normalise to str so int-keyed (Telegram) and
                # str-keyed (Max) rows both match the requested id strings.
                midVal = r["message_id"]
                foundStrs.add(midVal.asStr())
                if isinstance(ret, Exception):
                    logger.warning("get_messages_by_ids: failed to format row %s: %s", midVal.asStr(), ret)
                    continue
                messages.append(cast(Dict[str, Any], ret))

            # notFound = requested − found.
            for midVal in messageIdList:
                if midVal.asStr() not in foundStrs:
                    notFound.append(midVal.asStr())

            return {"done": True, "messages": messages, "notFound": notFound, "count": len(messages)}
        except Exception as e:
            logger.exception("get_messages_by_ids: unexpected error")
            return {"done": False, "error": str(e)}

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """Track chats that may need embeddings backfill.

        Reads the chat settings and, when ``EMBEDDINGS_ENABLED`` is true,
        adds the message's chat id to the in-memory
        ``self._trackedChats`` set so the
        :meth:`_dtCronJob` backfill pass can round-robin over it on a
        later tick. This is a fire-and-forget tracker — it never
        short-circuits the handler chain.

        Args:
            ensuredMessage: The incoming message (its ``recipient.id``
                is the chat added to the tracking set).
            updateObj: Raw platform update object (unused).

        Returns:
            ``HandlerResultStatus.NEXT`` — always, so downstream handlers
            (notably ``LLMMessageHandler``) still process the message.
        """

        # Track chats needing embeddings backfill.
        chatSettings = await self.getChatSettings(ensuredMessage.recipient.id)
        if chatSettings[ChatSettingsKey.EMBEDDINGS_ENABLED].toBool():
            self._trackedChats.add(ensuredMessage.recipient.id)

        return HandlerResultStatus.NEXT

    ###
    # /users command
    ###

    @commandHandlerV2(
        commands=("users",),
        shortDescription="[limit=N] [min_messages=N] [last_active=N] - List chat users with activity stats",
        helpMessage=(
            " [limit=N] [min_messages=N] [last_active=N]: Список участников чата"
            " с количеством сообщений и информацией об активности.\n"
            "  `limit=N` — максимальное число пользователей (по умолчанию 50);\n"
            "  `min_messages=N` — показывать только пользователей с N+ сообщениями;\n"
            "  `last_active=N` — показывать только активных за последние N дней.\n"
            "Примеры: `/users`, `/users limit=20`, `/users min_messages=100 last_active=7`."
        ),
        visibility={CommandPermission.BOT_OWNER},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def usersCommand(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        updateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the ``/users`` slash command.

        Lists chat members with their message counts and activity
        information. Supports filtering by minimum message count,
        recency of activity, and result limit via the argument syntax
        ``key=value``.

        Args:
            ensuredMessage: The originating user message.
            command: The command name (``"users"``).
            args: Raw argument string after the command.
            updateObj: Raw update object from the platform (unused).
            typingManager: Optional typing indicator manager.
        """
        # Parse optional key=value arguments.
        limit: int = 50
        minMessages: Optional[int] = None
        lastActiveDays: Optional[int] = None
        for token in args.split():
            token = token.strip()
            if token.startswith("limit="):
                try:
                    limit = int(token[len("limit=") :])
                except (ValueError, TypeError):
                    pass  # non-numeric — use default
            elif token.startswith("min_messages="):
                try:
                    minMessages = int(token[len("min_messages=") :])
                except (ValueError, TypeError):
                    pass
            elif token.startswith("last_active="):
                try:
                    lastActiveDays = int(token[len("last_active=") :])
                except (ValueError, TypeError):
                    pass

        limit = max(1, min(limit, 200))  # reasonable cap

        chatUsers = await self._listUsersInternal(
            chatId=ensuredMessage.recipient.id,
            limit=limit,
            minMessages=minMessages,
            lastActiveDays=lastActiveDays,
        )

        if not chatUsers:
            await self.sendMessage(
                ensuredMessage,
                messageText="Участники не найдены.",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        # Build the formatted user list.
        chatName = str(ensuredMessage.recipient.id)
        lines: List[str] = []
        for idx, u in enumerate(chatUsers, start=1):
            username = u.get("username") or ""
            fullName = u.get("full_name") or ""
            msgCount = u.get("messages_count") or 0
            updatedAt = u.get("updated_at")
            relativeTime = self._relativeTime(updatedAt) if isinstance(updatedAt, datetime.datetime) else "?"
            displayName = f" @{username}" if username else ""
            lines.append(f"{idx}. {displayName} — {fullName} — {msgCount:,} сообщ. (посл. активность {relativeTime})")

        replyText = f"👥 Участники в «{chatName}» ({len(chatUsers)}):\n\n" + "\n".join(lines)
        await self.sendMessage(
            ensuredMessage,
            messageText=replyText,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            typingManager=typingManager,
        )

    ###
    # /search command
    ###

    @commandHandlerV2(
        commands=("search",),
        shortDescription="<args> - Semantic search over chat history",
        helpMessage=(
            " [args]: Семантический поиск по истории чата. "
            "Аргументы в формате `key: value` через пробел:\n"
            "  `keywords: ...` — текст для семантического поиска (опционально, если заданы другие фильтры);\n"
            "  `user: @username` — фильтр по пользователю;\n"
            "  `days: N` — окно в днях назад (по умолчанию 30);\n"
            "  `category: user|bot|system|channel` — фильтр по типу сообщений;\n"
            "  `thread: <message_id>` — фильтр по треду (root_message_id);\n"
            "  `chat: <chat_id>` — искать в другом чате (нужны права администратора).\n"
            "Должен быть задан хотя бы один из: `keywords`, `user`, `days`, `thread`.\n"
            "Примеры: `/search keywords: meeting days: 7 user: @alice`; "
            "`/search user: @bob days: 7`; `/search chat: -1001234567890 days: 3`."
        ),
        visibility={CommandPermission.DEFAULT},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def searchCommand(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        updateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle the `/search` command.

        Parses the argument string into a dict, validates that at
        least one of ``keywords``/``user``/``days``/``thread`` is
        provided, resolves an optional ``chat:`` target (numeric id), enforces that the sender is an admin of
        the target chat, runs the search through the
        chat-message repository (filter-only or semantic, with
        ``limit=_maxResults``), truncates the matches
        to `_maxResults`, and finally returns the matching messages
        rendered as a raw, human-readable list. No LLM summary is
        produced.

        Args:
            ensuredMessage: Message that triggered the command.
            command: Command name (`"search"`).
            args: Raw argument string after the command.
            updateObj: Original update object (unused).
            typingManager: Optional typing indicator manager.
        """
        parsed = self._parseSearchArgs(args)
        keywords = parsed["keywords"]

        # Validation: at least one of (keywords, user, days, thread)
        # must be provided. `category` is a refinement on top of the
        # other filters and is therefore not counted on its own.
        if not self._hasAnyFilter(parsed):
            await self.sendMessage(
                ensuredMessage,
                messageText=self._helpText(),
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        currentChatId = ensuredMessage.recipient.id
        currentChatSettings: ChatSettingsDict = await self.getChatSettings(chatId=currentChatId)

        # Resolve target chat. Defaults to the current chat when the
        # `chat:` arg is missing. A different target requires the
        # sender to be an admin of it.
        targetChatId = currentChatId
        if parsed["chat"] is not None:
            resolvedChatId = await self._resolveTargetChatId(
                ensuredMessage=ensuredMessage,
                chatArg=parsed["chat"],
            )
            if resolvedChatId is None:
                await self.sendMessage(
                    ensuredMessage,
                    messageText=(
                        "Не удалось определить указанный чат: проверьте `chat: <chat_id>` "
                        "и убедитесь, что у вас есть права администратора в нём."
                    ),
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
                return
            targetChatId = resolvedChatId

        # Build the SQL filter args. The repository handles keyword
        # matching via vector search (semantic ranking) in the DB,
        # so no client-side substring filter is needed.
        days = self._defaultDays
        if parsed["days"] is not None:
            try:
                days = int(parsed["days"])
            except ValueError:
                await self.sendMessage(
                    ensuredMessage,
                    messageText="Параметр `days` должен быть числом.",
                    messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                    typingManager=typingManager,
                )
                return

        categoryFilter: Optional[List[MessageCategory]] = self._resolveCategoryGroup(parsed["category"])
        userId = await self._resolveUserId(chatId=targetChatId, userIdentifier=parsed["user"])
        rootMessageId: Optional[MessageId] = None
        if parsed["thread"] is not None:
            try:
                rootMessageId = MessageId(parsed["thread"])
            except ValueError:
                logger.warning(f"/search: invalid thread id {parsed['thread']!r}, ignoring")

        # When keywords are provided, rate-limit the request (so
        # abusive semantic searches are gated *before* any embedding
        # call or DB work), then generate a query embedding so the
        # repository can do a semantic ranking pass. Any failure here
        # is non-fatal — we fall back to filter-only mode (the same
        # path used when no keywords are present) so a flaky embedding
        # API never breaks `/search`. `modelName` is also passed to
        # `searchChatMessages` so it knows which model's embeddings to
        # load for cosine-similarity comparison.
        queryEmbedding: Optional[List[float]] = None
        embeddingModelName: Optional[str] = None
        maxMessages: Optional[int] = None
        if keywords:
            # Rate-limit gating: only charge LLM budget for searches
            # that will actually hit the embedding API.
            await self.llmService.rateLimit(currentChatId, currentChatSettings)

            targetChatSettings: ChatSettingsDict = (
                currentChatSettings
                if targetChatId == currentChatId
                else await self.getChatSettings(chatId=targetChatId)
            )

            # Resolve the per-chat cap on how many recent embeddings
            # to load for semantic search. Prevents OOM / SQL
            # parameter-limit errors on large chats.
            if ChatSettingsKey.MAX_MESSAGES_FOR_SEMANTIC_SEARCH in targetChatSettings:
                # toInt() returns 0 on parse failure; 0 or None -> unlimited.
                # A value of 0 means "disabled/unlimited" per the config default.
                maxMessages = targetChatSettings[ChatSettingsKey.MAX_MESSAGES_FOR_SEMANTIC_SEARCH].toInt() or None

            # Route the query-embedding call through LLMService (never
            # raises; returns None on internal failure) instead of
            # resolving the model directly: this keeps model resolution,
            # validation, and consumerId stats attribution unified in one
            # place. doRateLimit=False because the command already
            # rate-limited above — the service must not double-charge the
            # per-chat budget. The embedding model is resolved against
            # the *target* chat's settings — a search in chat A should
            # use A's embedding model.
            try:
                embeddingResult: Optional[Tuple[str, List[float]]] = await self.llmService.generateEmbedding(
                    keywords,
                    chatId=targetChatId,
                    chatSettings=targetChatSettings,
                    doRateLimit=False,
                )
                if embeddingResult is not None:
                    embeddingModelName, queryEmbedding = embeddingResult
            except Exception:
                logger.exception("Failed to generate query embedding, falling back to filter-only")
                embeddingModelName = None
                queryEmbedding = None

        try:
            # `maxMessages` caps the number of recent embeddings loaded
            # for the similarity pass (reads from
            # MAX_MESSAGES_FOR_SEMANTIC_SEARCH chat setting); it is
            # only set when keywords are present and the target chat
            # has that setting configured.
            results = await self.db.chatSearch.searchChatMessages(
                chatId=targetChatId,
                queryEmbedding=queryEmbedding,
                userFilter=userId,
                categoryFilter=categoryFilter,
                maxAgeDays=days,
                rootMessageId=rootMessageId,
                modelName=embeddingModelName,
                limit=self._maxResults,
                maxMessages=maxMessages,
            )
        except Exception as e:
            logger.error(f"/search: repository call failed: {e}")
            logger.exception(e)
            await self.sendMessage(
                ensuredMessage,
                messageText="Ошибка при поиске сообщений.",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        # Cap to `_maxResults` so the response never carries an
        # unbounded result set.
        results = results[: self._maxResults]

        if not results:
            await self.sendMessage(
                ensuredMessage,
                messageText="Сообщения по вашему запросу не найдены.",
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager,
            )
            return

        replyText = f"Найдено {len(results)} сообщений:\n\n{self._formatRawResults(results)}"
        await self.sendMessage(
            ensuredMessage,
            messageText=replyText,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            typingManager=typingManager,
        )

    ###
    # /search helpers
    ###

    @staticmethod
    def _parseSearchArgs(args: str) -> Dict[str, Optional[str]]:
        """Parse the `/search` argument string into a dict.

        Accepts the form ``key: value key2: value2 ...`` where a
        value can span multiple tokens until the next known key is
        encountered. Tokens without a known key prefix are treated as
        keywords. The first occurrence of a key wins (later
        occurrences are ignored, so shell-style quoting accidents
        don't silently re-set a filter).

        Examples:
            - ``keywords:hello world`` → ``keywords="hello world"``
            - ``keywords: hello world`` → ``keywords="hello world"``
            - ``days: 7 keywords: meeting`` → ``days="7"``, ``keywords="meeting"``
            - ``hello keywords: meeting days: 7`` → ``keywords="hello meeting"``, ``days="7"``
            - ``user: @alice`` → ``user="@alice"``
            - ``category: bot`` → ``category="bot"``
            - ``chat: -1001234567890`` → ``chat="-1001234567890"``

        Args:
            args: Raw argument string after the command.

        Returns:
            Dict with keys ``keywords``, ``user``, ``days``, ``category``,
            ``thread``, ``chat``. All values are ``str`` or ``None``.
        """
        knownKeys = ("keywords", "user", "days", "category", "thread", "chat")
        result: Dict[str, Optional[str]] = {
            "keywords": None,
            "user": None,
            "days": None,
            "category": None,
            "thread": None,
            "chat": None,
        }
        if not args or not args.strip():
            return result

        tokens = args.split()
        i = 0
        while i < len(tokens):
            token = tokens[i]
            # Check if this token starts with a known key followed by ":"
            keyMatch: Optional[str] = None
            for knownKey in knownKeys:
                if token.startswith(knownKey + ":"):
                    keyMatch = knownKey
                    break

            if keyMatch is not None:
                # Extract everything after the colon (can be empty)
                _, _, valueStart = token.partition(keyMatch + ":")
                valueStart = valueStart.strip()

                if valueStart:
                    # Value starts in same token: keywords:meeting
                    # But it could continue in following tokens; consume
                    # them until the next known key.
                    parts: List[str] = [valueStart]
                    j = i + 1
                    while j < len(tokens):
                        nextToken = tokens[j]
                        isKnownKey = False
                        for kk in knownKeys:
                            if nextToken.startswith(kk + ":"):
                                isKnownKey = True
                                break
                        if isKnownKey:
                            break
                        parts.append(nextToken)
                        j += 1
                    if keyMatch == "keywords":
                        existing = result["keywords"] or ""
                        merged = (existing + " " + " ".join(parts)).strip() if existing else " ".join(parts)
                        result["keywords"] = merged if merged else None
                    elif result[keyMatch] is None:
                        result[keyMatch] = " ".join(parts)
                    i = j
                    continue
                else:
                    # Value starts in following tokens: "days: 7"
                    j = i + 1
                    parts = []
                    while j < len(tokens):
                        nextToken = tokens[j]
                        isKnownKey = False
                        for kk in knownKeys:
                            if nextToken.startswith(kk + ":"):
                                isKnownKey = True
                                break
                        if isKnownKey:
                            break
                        parts.append(nextToken)
                        j += 1
                    if parts:
                        if keyMatch == "keywords":
                            existing = result["keywords"] or ""
                            merged = (existing + " " + " ".join(parts)).strip() if existing else " ".join(parts)
                            result["keywords"] = merged if merged else None
                        elif result[keyMatch] is None:
                            result[keyMatch] = " ".join(parts)
                    i = j
                    continue
            else:
                # Bare word → append to keywords
                existing = result["keywords"] or ""
                result["keywords"] = (existing + " " + token).strip() if existing else token
                i += 1

        return result

    @staticmethod
    def _hasAnyFilter(parsed: Dict[str, Optional[str]]) -> bool:
        """Return ``True`` if the parsed args contain at least one search filter.

        At least one of ``keywords``, ``user``, ``days``, ``thread``
        must be set. ``category`` and ``chat`` do not count on their
        own: ``category`` is a refinement of the other filters, and
        ``chat`` is a routing arg (without a content filter, a search
        over an entire chat is rarely what the user wants).

        Args:
            parsed: Parsed argument dict from :meth:`_parseSearchArgs`.

        Returns:
            True when the user provided a content-side filter.
        """
        return any(parsed.get(key) is not None for key in ("keywords", "user", "days", "thread"))

    async def _resolveTargetChatId(
        self,
        *,
        ensuredMessage: EnsuredMessage,
        chatArg: Optional[str],
    ) -> Optional[int]:
        """Resolve a `chat:` argument to a chat id the sender is admin of.

        Only numeric chat ids are accepted (Telegram group ids are
        negative; private chat ids are positive). Any other input —
        usernames, free-form text — is treated as unresolvable and
        the method returns ``None``. The resolved chat is then
        admin-gated via :meth:`isAdmin` so a user can only target
        chats they administer (or that they own via the bot-owners
        list).

        Args:
            ensuredMessage: Originating message — its ``sender`` is
                checked against the target chat's admin list.
            chatArg: Raw ``chat:`` value supplied by the user
                (numeric id only).

        Returns:
            The resolved chat id on success, or ``None`` when the
            argument is missing/empty, not a valid integer, or the
            sender is not an admin of the resolved chat. The
            parse-failure and not-admin failure modes are
            intentionally conflated so the response does not leak
            which one occurred.
        """
        if not chatArg:
            return None
        clean = chatArg.strip()
        if not clean:
            return None

        # Numeric-only: Telegram group ids are negative, so the
        # integer check has to be permissive about sign and
        # surrounding whitespace (already stripped above). Anything
        # that does not parse as an integer (usernames, free-form
        # text, etc.) is treated as unresolvable.
        try:
            targetChatId = int(clean)
        except ValueError:
            logger.warning("/search: chat %r is not a numeric id", chatArg)
            return None

        # Private chats are positive ids; everything else is treated
        # as a group for the purposes of the admin gate. The real
        # chat type is irrelevant here — ``isAdmin`` only needs the
        # id to look up the admin list.
        chatType = ChatType.PRIVATE if targetChatId > 0 else ChatType.GROUP

        # Admin gate. The sender must be admin of the target chat;
        # bot owners bypass the check (handled inside ``isAdmin``).
        isUserAdmin = await self.isAdmin(
            user=ensuredMessage.sender,
            chat=MessageRecipient(id=targetChatId, chatType=chatType),
        )
        if not isUserAdmin:
            logger.warning(
                "/search: sender %s is not admin of target chat %d",
                ensuredMessage.sender.id,
                targetChatId,
            )
            return None

        return targetChatId

    @staticmethod
    def _resolveCategoryGroup(name: Optional[str]) -> Optional[List[MessageCategory]]:
        """Map a user-facing `category:` value to a list of `MessageCategory`.

        Args:
            name: User-supplied value (case-insensitive). One of
                ``"user"``, ``"bot"``, ``"system"``, ``"channel"``.

        Returns:
            The corresponding `MessageCategory` list, or ``None`` if
            ``name`` is ``None``/empty/unknown (which means "don't
            filter by category").
        """
        if not name:
            return None
        try:
            group = _CategoryGroup(name.strip().lower())
        except ValueError:
            logger.warning(f"/search: unknown category {name!r}, ignoring")
            return None
        return _CATEGORY_GROUPS[group]

    async def _listUsersInternal(
        self,
        chatId: int,
        limit: Optional[int] = None,
        minMessages: Optional[int] = None,
        lastActiveDays: Optional[int] = None,
    ) -> List[ChatUserDict]:
        """Return raw user list for the given chat.

        Shared between ``/users`` (formats as Markdown) and ``list_users``
        LLM tool (returns as JSON dict).

        Args:
            chatId: Chat to list users for.
            limit: Max users to return (``None`` = no cap).
            minMessages: Only users with at least this many messages.
            lastActiveDays: Only users active within this many days.

        Returns:
            List of ``ChatUserDict`` ordered by ``updated_at DESC``.
            Empty list on error.
        """
        return await self.db.chatUsers.getChatUsers(
            chatId=chatId,
            limit=limit,
            minMessages=minMessages,
            lastActiveDays=lastActiveDays,
        )

    @staticmethod
    def _relativeTime(dt: datetime.datetime) -> str:
        """Format a datetime as a human-readable relative time string.

        Args:
            dt: The datetime to format (must be timezone-aware or naive UTC).

        Returns:
            Short relative string such as ``"<1m ago"``, ``"5m ago"``,
            ``"1h ago"``, ``"yesterday"``, ``"5d ago"``, ``">1w ago"``.
        """
        diff = libUtils.now() - dt
        totalSeconds = int(diff.total_seconds())
        if totalSeconds < 0:
            return "now"
        if totalSeconds < 60:
            return "<1m ago"
        minutes = totalSeconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days == 1:
            return "yesterday"
        if days <= 7:
            return f"{days}d ago"
        return ">1w ago"

    def _formatRawResults(self, results: List[ChatMessageDict]) -> str:
        """Format search hits as a human-readable list.

        Format: one line per result, ``[YYYY-MM-DD HH:MM] @username:
        <truncated message>``. On Telegram, group-chat results include a
        deep-link to the original message.

        Args:
            results: Search hits from `searchChatMessages`.

        Returns:
            Multi-line string ready to send to the chat. The
            per-message slice is hard-capped to keep the response
            within Telegram's 4096-char message limit.
        """
        if not results:
            return ""
        maxLine = 400
        lines: List[str] = []
        for r in results:
            dt = r.get("date")
            if isinstance(dt, datetime.datetime):
                dateStr = dt.strftime("%Y-%m-%d %H:%M")
            else:
                dateStr = str(dt) if dt is not None else "?"
            username = (r.get("username") or "unknown").lstrip("@") or "unknown"
            text = (r.get("message_text") or "").replace("\n", " ").strip()
            if len(text) > maxLine:
                text = text[: maxLine - 1] + "…"
            # TODO: add Max link
            link = ""
            if self.botProvider == BotProvider.TELEGRAM:
                if r["chat_id"] < 0:
                    link = f"(https://t.me/c/{0 - r['chat_id'] - 1000000000000}/{r['message_id']})"
                    if r["thread_id"]:
                        link = f"(https://t.me/c/{0 - r['chat_id'] - 1000000000000}/{r['thread_id']}/{r['message_id']})"

            lines.append(f"[{dateStr}]{link} `@{username}`: {text}")
        return "\n".join(lines)

    @staticmethod
    def _helpText() -> str:
        """Return the help text for `/search` with no/insufficient arguments.

        The command is a semantic search; ``keywords`` is the primary
        input but becomes optional when at least one of ``user``,
        ``days``, ``thread`` is provided. ``category`` and ``chat``
        are routing/refinement args and do not count on their own.

        Returns:
            Multi-line string listing the supported `key: value`
            arguments and a few sample invocations.
        """
        return (
            "Семантический поиск по истории чата. Укажите хотя бы один из: "
            "`keywords`, `user`, `days`, `thread`.\n"
            "Аргументы в формате `key: value` через пробел:\n"
            "  `keywords: ...` — текст для семантического поиска (опционально, если заданы другие фильтры);\n"
            "  `user: @username` — фильтр по пользователю;\n"
            "  `days: N` — окно в днях назад (по умолчанию 30);\n"
            "  `category: user|bot|system|channel` — фильтр по типу сообщений;\n"
            "  `thread: <message_id>` — фильтр по треду (root_message_id);\n"
            "  `chat: <chat_id>` — искать в другом чате (нужны права администратора).\n"
            "Примеры:\n"
            "/search keywords: meeting — поиск по тексту\n"
            "/search user: @alice — только сообщения от @alice\n"
            "/search days: 7 user: @bob — сообщения @bob за последние 7 дней\n"
            "/search keywords: meeting days: 30 user: @bob"
        )
