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
      chat with `REGENERATE_EMBEDDINGS=true` (round-robin across chats).

The handler follows the conditional-registration pattern: it is only
loaded when ``[search-history].enabled = true`` in the merged TOML
config (see `HandlersManager.__init__` in `manager.py`).
"""

import asyncio
import datetime
import json
import logging
from enum import StrEnum
from typing import Any, Dict, List, Optional

import lib.utils as libUtils
from internal.bot.common.embedding_utils import embedAndSaveMessage
from internal.bot.common.models import UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsValue,
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
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction
from lib.ai import LLMFunctionParameter, LLMParameterType

from .base import BaseBotHandler

logger = logging.getLogger(__name__)


SEARCH_DEFAULT_MAX_RESULTS: int = 10
"""Default ``max-results`` for `/search` when `[search-history.defaults]` is
unset. Matches the TOML default in `configs/00-defaults/search-history.toml`."""

SEARCH_DEFAULT_DAYS: int = 30
"""Default `days` window for `/search` when `[search-history.defaults]` is unset.
Matches the TOML default in `configs/00-defaults/search-history.toml`."""

BACKFILL_DEFAULT_BATCH_SIZE: int = 50
"""Default per-tick batch size for the backfill CRON_JOB when
``[search-history.embeddings].reindex-batch-size`` is unset."""

SEARCH_TOOL_MAX_MESSAGE_LENGTH: int = 512
"""Max chars per message text in LLM tool search results. Longer texts
are truncated with ``…`` to avoid blowing up the LLM context window."""

BACKFILL_INTER_MESSAGE_DELAY_SECS: float = 0.1
"""Pause inserted between consecutive embedding API calls within a
backfill batch. ``LLMService`` already rate-limits at the provider level,
but a small extra cushion keeps the handler from monopolising the
asyncio loop and leaves headroom for user-facing message traffic."""


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
       with ``REGENERATE_EMBEDDINGS=true`` in round-robin order and embed
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
            name="search_messages",
            description="Semantic search over chat history. Returns messages matching the query with relevance scores.",
            parameters=[
                LLMFunctionParameter(
                    name="query", description="Search query text", type=LLMParameterType.STRING, required=True
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
                    description="Filter by username (with or without @)",
                    type=LLMParameterType.STRING,
                    required=False,
                ),
                LLMFunctionParameter(
                    name="thread_message_id",
                    description="Restrict to thread rooted at this message ID",
                    type=LLMParameterType.STRING,
                    required=False,
                ),
            ],
            handler=self._llmToolSearchMessages,
        )

        # Register LLM tool: list users with activity stats.
        self.llmService.registerTool(
            name="list_users",
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
            name="get_thread",
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

    ###
    # Backfill CRON_JOB
    ###

    async def _dtCronJob(self, task: DelayedTask) -> None:
        """Process one batch of embeddings per CRON_JOB tick.

        Runs every 60 seconds (the ``CRON_JOB`` cadence in
        :class:`QueueService`). Per tick:

        1. List chats with ``REGENERATE_EMBEDDINGS=true`` via the
           cross-source-aggregating ``ChatSettingsRepository.listChatsBySetting``
           helper. ``value`` is filtered through
           :meth:`ChatSettingsValue.toBool` so ``"true"``/``"1"`` (any
           case) match. The ``EMBEDDINGS_ENABLED`` flag is *not* used as
           the backfill trigger: a chat that flips embeddings on for new
           messages has no need for a backfill pass over its history.
         2. Round-robin: pick the next chat in stable order, advance
            ``_backfillIndex``.
         3. Resolve the chat's embedding model from its ``EMBEDDING_MODEL``
            setting. Bail out if the model is missing, unknown, or does
            not support embeddings.
         4. Fetch up to ``[search-history.embeddings].reindex-batch-size``
            (default ``BACKFILL_DEFAULT_BATCH_SIZE``) messages without
            embeddings and embed them one by one, with a small inter-call
            sleep to keep the asyncio loop responsive.
         5. Per-message errors are caught and logged — one bad row never
            aborts the batch.

        No re-entrancy guard, no inter-pass backoff, and no
        self-resetting of ``REGENERATE_EMBEDDINGS``: the per-tick batch
        is small (default 50 messages) and the next minute's tick will
        pick up where this one left off, so a long pass just walks a
        longer backlog. The previous ``BackfillWorker``-style throttling
        was dropped with that class.

        Args:
            task: The CRON_JOB delayed task firing this handler. Ignored.

        Returns:
            None
        """
        startTime = libUtils.now()
        # Gate 1: discover chats that explicitly opted in to a backfill
        # pass via `REGENERATE_EMBEDDINGS = true`.
        try:
            # Search for chats with enabled embeddings and then filter out via REGENERATE_EMBEDDINGS
            # as REGENERATE_EMBEDDINGS is true by default, so it won't be in database for most chats
            # In the same time EMBEDDINGS_ENABLED is false by default, so all chats with enabled will be in DB
            chatMap = await self.db.chatSettings.listChatsBySetting(key=ChatSettingsKey.EMBEDDINGS_ENABLED)
        except Exception as e:
            logger.warning("Backfill: failed to list enabled chats: %s", e)
            return

        enabledChats: List[int] = [chatId for chatId, value in chatMap.items() if ChatSettingsValue(value).toBool()]
        if not enabledChats:
            return

        # Round-robin pick. ``% len`` is safe because ``enabledChats`` is
        # non-empty (checked above), so a zero-division never lands.
        chatId = enabledChats[self._backfillIndex % len(enabledChats)]
        self._backfillIndex += 1
        self._backfillIndex %= len(enabledChats)

        # Gate 3: resolve the embedding model.
        try:
            chatSettings = await self.getChatSettings(chatId=chatId)
        except Exception as e:
            logger.warning("Backfill: failed to read chat settings for %d: %s", chatId, e)
            return
        if not chatSettings[ChatSettingsKey.REGENERATE_EMBEDDINGS].toBool():
            # Regenerating embeddings is disabled for given chat
            return

        modelName = chatSettings[ChatSettingsKey.EMBEDDING_MODEL].toStr()
        if not modelName:
            return
        model = self.llmService.getLLMManager().getModel(modelName)
        if model is None or not model.supportsEmbedding:
            return

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
            if not ensuredMessage.messageText.strip():
                continue

            if await embedAndSaveMessage(
                ensuredMessage=ensuredMessage,
                modelName=modelName,
                db=self.db,
            ):
                embedded += 1
            await asyncio.sleep(BACKFILL_INTER_MESSAGE_DELAY_SECS)

        if embedded > 0:
            elapsedTime = libUtils.now() - startTime
            logger.info(
                "Backfill: embedded %d messages in chat %d (elapsed %f.2 seconds)",
                embedded,
                chatId,
                elapsedTime.total_seconds(),
            )

    ###
    # LLM tool: semantic search over chat history
    ###

    async def _llmToolSearchMessages(
        self,
        extraData: Optional[Dict[str, Any]],
        query: str,
        limit: int = 5,
        max_age_days: Optional[int] = None,
        user_name: Optional[str] = None,
        thread_message_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """LLM tool: semantic search over chat history.

        Called by the LLM when it needs to find messages matching a
        natural-language query. Returns structured results as a dict
        so the LLM service can serialise them back into the model
        context. All errors are folded into the return dict — this
        method never raises.

        Args:
            extraData: Context dict with ``ensuredMessage`` key.
            query: Search query text.
            limit: Max results (default 5).
            max_age_days: Only messages newer than this many days.
            user_name: Filter by username (with or without @).
            thread_message_id: Restrict to thread rooted at this message ID.
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

        # Clamp limit to prevent abuse (Issue 4).
        effectiveLimit = int(limit) if limit is not None else 5
        limit = max(1, min(effectiveLimit, 100))

        # Gate 2: check per-chat settings (wrapped in try/except — see Issue 1).
        try:
            chatSettings = await self.getChatSettings(chatId=chatId)
        except Exception:
            logger.exception("search_messages: failed to load chat settings for chat %d", chatId)
            return {"done": False, "error": "Не удалось получить настройки чата"}
        if not chatSettings[ChatSettingsKey.ALLOW_TOOLS_COMMANDS].toBool():
            return {"done": False, "error": "Инструменты поиска отключены в этом чате"}
        if not chatSettings[ChatSettingsKey.EMBEDDINGS_ENABLED].toBool():
            return {"done": False, "error": "Семантический поиск не включён в этом чате"}

        # Gate 2b: rate-limit before embedding generation.
        try:
            await self.llmService.rateLimit(chatId, chatSettings)
        except Exception:
            logger.exception("search_messages: rate-limit check failed")
            return {"done": False, "error": "Превышен лимит запросов"}

        # Gate 3: resolve optional user filter.
        userId: Optional[int] = None
        if user_name:
            userId = await self._resolveUserId(chatId=chatId, username=user_name)

        # Gate 4: resolve optional thread filter.
        threadMessageId: Optional[MessageId] = None
        if thread_message_id is not None:
            try:
                threadMessageId = MessageId(thread_message_id)
            except (ValueError, TypeError):
                pass  # invalid value — skip thread filter

        # Gate 5: generate query embedding.
        embeddingModelName = chatSettings[ChatSettingsKey.EMBEDDING_MODEL].toStr()
        if not embeddingModelName:
            return {"done": False, "error": "Модель эмбеддингов не настроена"}
        model = self.llmService.getLLMManager().getModel(embeddingModelName)
        if model is None or not model.supportsEmbedding:
            return {"done": False, "error": "Модель эмбеддингов недоступна"}
        try:
            queryEmbedding = await model.generateEmbeddings(query)
        except Exception as e:
            logger.exception(f"search_messages: failed to generate query embedding: {e}")
            return {"done": False, "error": "Не удалось создать поисковый вектор"}

        # Gate 6: resolve per-chat message cap.
        maxMessages: Optional[int] = None
        if ChatSettingsKey.MAX_MESSAGES_FOR_SEMANTIC_SEARCH in chatSettings:
            maxMessages = chatSettings[ChatSettingsKey.MAX_MESSAGES_FOR_SEMANTIC_SEARCH].toInt() or None

        # Execute search.
        try:
            results = await self.db.chatSearch.searchChatMessages(
                chatId=chatId,
                queryEmbedding=queryEmbedding,
                limit=limit,
                userFilter=userId,
                maxAgeDays=max_age_days,
                rootMessageId=threadMessageId,
                modelName=embeddingModelName,
                maxMessages=maxMessages,
            )
        except Exception:
            logger.exception("search_messages: search failed")
            return {"done": False, "error": "Ошибка при поиске сообщений"}

        # Format results with truncation (Issue 5).
        formatted: List[Dict[str, Any]] = []
        for r in results:
            eMsg = await EnsuredMessage.fromDBChatMessage(r, self.db)
            retMsg = json.loads(await eMsg.formatForLLM(self.db, format=LLMMessageFormat.JSON, useSingleMedia=False))
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
        extraData: Optional[Dict[str, Any]],
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

        # Gate 2: check per-chat settings.
        try:
            chatSettings = await self.getChatSettings(chatId=chatId)
        except Exception:
            logger.exception("list_users: failed to load chat settings")
            return {"done": False, "error": "Не удалось получить настройки чата"}
        if not chatSettings[ChatSettingsKey.ALLOW_TOOLS_COMMANDS].toBool():
            return {"done": False, "error": "Инструменты списка участников отключены в этом чате"}

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
        """Convert a ChatMessageDict row to a JSON-safe dict for LLM tool output.
        TODO: Fix docstring
        Args:
            msg: A ``ChatMessageDict`` row from the repository.

        Returns:
            JSON-safe dict with ``message_id``, ``message_text``,
            ``username``, ``full_name``, ``date``, ``reply_id``,
            and ``thread_id``.
        """
        eMessage = await EnsuredMessage.fromDBChatMessage(msg, self.db)
        return json.loads(await eMessage.formatForLLM(self.db, format=LLMMessageFormat.JSON, useSingleMedia=False))

    async def _llmToolGetThread(
        self,
        extraData: Optional[Dict[str, Any]],
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

        # Gate 2: check per-chat settings.
        try:
            chatSettings = await self.getChatSettings(chatId=chatId)
        except Exception:
            logger.exception("get_thread: failed to load chat settings")
            return {"done": False, "error": "Не удалось получить настройки чата"}
        if not chatSettings[ChatSettingsKey.ALLOW_TOOLS_COMMANDS].toBool():
            return {"done": False, "error": "Инструменты работы с тредами отключены в этом чате"}

        # Gate 3: validate message ID.
        try:
            msgId = MessageId(message_id)
        except (ValueError, TypeError):
            return {"done": False, "error": "Неверный идентификатор сообщения"}

        # Gate 4: fetch the thread.
        try:
            thread = await self.db.chatMessages.getMessageThread(chatId=chatId, messageId=msgId)
        except Exception:
            logger.exception("get_thread: failed to get thread for message %s", message_id)
            return {"done": False, "error": "Не удалось получить тред"}
        if thread is None:
            return {"done": False, "error": "Сообщение не найдено в этом чате"}

        rootMsg = thread.get("root_message")
        return {
            "done": True,
            "root_message": await self._formatMessageDict(rootMsg) if rootMsg is not None else None,
            "target_message": await self._formatMessageDict(thread["target_message"]),
            "thread_messages": [await self._formatMessageDict(m) for m in thread.get("thread_messages", [])],
        }

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
    async def users_command(
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
    async def search_command(
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
        the target chat, runs the filter-only search through the
        chat-message repository with `limit=None` (no SQL `LIMIT` —
        see rationale inline), applies a client-side keyword filter
        (only when ``keywords`` is present), truncates the matches
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

        # Build the SQL filter args. The repository has no native keyword
        # operator, so the keyword substring filter is applied
        # client-side below; semantic ranking (when available) only
        # refines the *order* of the SQL-filtered result set.
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
        userId = await self._resolveUserId(chatId=targetChatId, username=parsed["user"])
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
        # load for cosine-similarity comparison. The embedding model
        # is resolved against the *target* chat's settings — a search
        # in chat A should use A's embedding model.
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
                maxMessages = targetChatSettings[ChatSettingsKey.MAX_MESSAGES_FOR_SEMANTIC_SEARCH].toInt() or None

            embeddingModelName = targetChatSettings[ChatSettingsKey.EMBEDDING_MODEL].toStr()
            if embeddingModelName:
                model = self.llmService.getLLMManager().getModel(embeddingModelName)
                if model is not None and model.supportsEmbedding:
                    try:
                        queryEmbedding = await model.generateEmbeddings(keywords)
                    except Exception:
                        logger.exception("Failed to generate query embedding, falling back to filter-only")
                        queryEmbedding = None

        try:
            # `limit=None` is intentional: the SQL search API has no
            # native keyword operator, so the keyword filter has to run
            # client-side. If we capped the SQL at `_maxResults` (the
            # default 10), the keyword filter would see only the 10
            # most-recent matches-by-date and silently drop any older
            # matches. By asking for the full result set here and
            # truncating to `_maxResults` *after* the keyword filter
            # below, we guarantee the user still gets a hit whenever
            # at least one matching message exists in the search
            # window. (See `searchChatMessages`'s `limit` docstring.)
            #
            # When keywords were provided *and* we managed to embed
            # them above, `queryEmbedding` switches the search into
            # semantic-ranking mode (cosine similarity on
            # `message_embeddings`). The keyword substring filter is
            # still applied client-side below — semantic ranking
            # refines the *order* of an already-filtered set, it does
            # not replace keyword matching.
            #
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
                limit=None,
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

        # Apply keyword filter client-side. Substring match (case-insensitive)
        # on message_text. The API limitation is documented in the plan.
        # Skipped entirely when the user did not provide `keywords:` —
        # a filter-only search (`/search user: @alice days: 7`) must
        # not silently drop rows just because they don't contain a
        # particular substring.
        if keywords:
            keywordLower = keywords.lower()
            results = [r for r in results if keywordLower in (r.get("message_text") or "").lower()]
        # Cap to `_maxResults` so the response never carries an
        # unbounded result set, even when the chat contains a huge
        # number of keyword hits. The truncation happens *after* the
        # keyword filter, so the most-recent matching messages win.
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

    async def _resolveUserId(self, *, chatId: int, username: Optional[str]) -> Optional[int]:
        """Resolve a `user:` argument to a numeric user_id.

        Looks the username up in the chat's known users via the
        single-row helper
        :meth:`ChatUsersRepository.getChatUserByUsername` — the
        case-insensitive comparison goes through
        ``provider.getCaseInsensitiveComparison`` so it stays
        portable across SQLite, PostgreSQL, and MySQL. The leading
        ``@`` is stripped from the input for normalisation, then
        always prepended before the query (the ``chat_users`` table
        stores usernames with the ``@`` prefix); both ``"@alice"``
        and ``"alice"`` resolve to the same row.

        Args:
            chatId: Chat the user belongs to.
            username: Username (with or without leading ``@``). The
                lookup is case-insensitive.

        Returns:
            The matching `user_id`, or `None` if the argument was
            missing, empty, or no user matched.
        """
        if not username:
            return None
        clean = username.lstrip("@").strip()
        if not clean:
            return None
        # DB stores usernames with @ prefix. Normalise to that format.
        clean = f"@{clean}"
        try:
            user = await self.db.chatUsers.getChatUserByUsername(chatId=chatId, username=clean)
        except Exception as e:
            logger.error(f"/search: failed to look up user {clean!r} in chat {chatId}: {e}")
            logger.exception(e)
            return None
        if user is None:
            logger.warning(f"/search: user {username!r} not found in chat {chatId}")
            return None
        userId = user.get("user_id")
        if userId is None:
            return None
        return int(userId)

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

    @staticmethod
    def _formatRawResults(results: List[ChatMessageDict]) -> str:
        """Format search hits as a human-readable list.

        Format: one line per result, ``[YYYY-MM-DD HH:MM] @username:
        <truncated message>``.

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
            if r["chat_id"] < 0:
                link = f"(https://t.me/c/{0 - r['chat_id'] - 1000000000000}/{r['message_id']})"
                if r["thread_id"]:
                    link = f"(https://t.me/c/{0 - r['chat_id'] - 1000000000000}/{r['thread_id']}/{r['message_id']})"

            lines.append(f"[{dateStr}]{link} @{username}: {text}")
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
