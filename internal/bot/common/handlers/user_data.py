"""
User data management handlers for Gromozeka bot.

Provides handlers for user-specific data storage: viewing, deleting, clearing data,
and LLM tool integration for AI-assisted data management. All data is scoped to
specific chat and user combinations.
"""

import asyncio
import datetime
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser as dateutilParser

import lib.utils as utils
from internal.bot.common.models import CallbackButton, UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.constants import ToolName
from internal.bot.models import (
    BotProvider,
    ButtonDataKey,
    ButtonUserDataConfigAction,
    ChatSettingsKey,
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
from internal.database.models import ChatMessageDict, MessageCategory
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

# Memory-refinement tuning constants.
# Refinement fires when ``newMessagesCount >= MEMORY_COUNT_THRESHOLD`` OR
# ``elapsed since lastRefinedTS >= MEMORY_TIME_THRESHOLD_SECONDS``.
MEMORY_COUNT_THRESHOLD = 5
"""Per-(chat, user, thread) new-message count that triggers a refinement run."""

MEMORY_TIME_THRESHOLD_SECONDS = 6 * 60 * 60
"""Max seconds since the last refinement run before another is forced (6 hours)."""

MEMORY_MIN_MESSAGES_TO_REFINE = 5
"""Don't refine if fewer than this many new messages are available."""

MEMORY_MAX_MESSAGES_PER_RUN = 128
"""Cap on messages fed to a single refinement LLM call."""

MEMORY_MAX_REFINES_PER_TICK = 3
"""Upper bound on refinement LLM calls per 60s cron tick."""


class UserDataHandler(BaseBotHandler):
    """
    Handler for user data management with LLM tool integration.

    Attributes:
        llmService (LLMService): Service for LLM tool registration and management.
    """

    def __init__(self, *, configManager: ConfigManager, database: Database, botProvider: BotProvider) -> None:
        """
        Initialize handler and register 'add_user_data' LLM tool.

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

        # Register the memory-refinement CRON_JOB. Multiple handlers can
        # subscribe to the same `DelayedTaskFunction.CRON_JOB` (they run in
        # registration order), so the existing cleanup tick and the
        # `ChatSearchHandler` backfill keep running unaffected.
        self.queueService.registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB, self._dtCronJob)

        self.llmService.registerTool(
            name=ToolName.ADD_USER_DATA,
            description=(
                "Remember **durable, long-lived** facts about the user who sent the last message — "
                "things that will still be true weeks from now. "
                "Use it for: real name, birthday, profession, stable preferences "
                "(language, formatting, communication style), long-term goals, important relationships.\n"
                "\n"
                "Do NOT use it for: transient states (current mood, what they are doing today), "
                "one-off requests, conversation-specific context, things likely to change soon. "
                "When in doubt, skip.\n"
                "\n"
                "Will return new data for given key."
            ),
            parameters=[
                LLMFunctionParameter(
                    name="key",
                    description="Key for data (for structured data usage)",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
                LLMFunctionParameter(
                    name="data",
                    description="Data/knowledge you want to remember",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
            ],
            handler=self._llmToolSetUserData,
        )

        self.llmService.registerTool(
            name=ToolName.DELETE_USER_DATA,
            description=(
                "Delete a previously-remembered fact about the user who sent the last message, by key. "
                "Use it to remove stale, incorrect, or no-longer-relevant persistent knowledge."
            ),
            parameters=[
                LLMFunctionParameter(
                    name="key",
                    description="Key of the data to delete",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
            ],
            handler=self._llmToolDeleteUserData,
        )

    ###
    # LLM Tool-Calling handlers
    ###

    async def _llmToolSetUserData(
        self,
        extraData: Optional[Dict[str, Any]],
        key: str,
        data: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        LLM tool handler for storing user data.

        Args:
            extraData (Optional[Dict[str, Any]]): Context with ensuredMessage object.
            key (str): Storage key.
            data (str): Data to store.
            **kwargs: Additional arguments (ignored).

        Returns:
            Dict[str, Any]: ``{"done": bool, "key": str, "data": str}``.

        Raises:
            RuntimeError: If extraData is invalid or missing ensuredMessage.
        """
        if extraData is None:
            raise RuntimeError("extraData should be provided")
        if "ensuredMessage" not in extraData:
            raise RuntimeError("extraData['ensuredMessage'] should be provided")
        ensuredMessage = extraData["ensuredMessage"]
        if not isinstance(ensuredMessage, EnsuredMessage):
            raise RuntimeError("ensuredMessage should be instance of EnsuredMessage")

        await self.cache.setChatUserData(
            chatId=ensuredMessage.recipient.id,
            userId=ensuredMessage.sender.id,
            key=key,
            value=data,
        )

        return {"done": True, "key": key, "data": data}

    async def _llmToolDeleteUserData(
        self,
        extraData: Optional[Dict[str, Any]],
        key: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        LLM tool handler for deleting user data.

        Args:
            extraData (Optional[Dict[str, Any]]): Context with ensuredMessage object.
            key (str): Storage key to remove.
            **kwargs: Additional arguments (ignored).

        Returns:
            Dict[str, Any]: ``{"done": bool, "key": str}``.

        Raises:
            RuntimeError: If extraData is invalid or missing ensuredMessage.
        """
        if extraData is None:
            raise RuntimeError("extraData should be provided")
        if "ensuredMessage" not in extraData:
            raise RuntimeError("extraData['ensuredMessage'] should be provided")
        ensuredMessage = extraData["ensuredMessage"]
        if not isinstance(ensuredMessage, EnsuredMessage):
            raise RuntimeError("ensuredMessage should be instance of EnsuredMessage")

        await self.cache.unsetChatUserData(
            chatId=ensuredMessage.recipient.id,
            userId=ensuredMessage.sender.id,
            key=key,
        )

        return {"done": True, "key": key}

    ###
    # Memory refinement (background CRON_JOB)
    ###
    #
    # Flow (see docs/plans/memory-refine-plan-v1.md §5/§6):
    #   newMessageHandler increments _accounting  ->  _dtCronJob (every 60s)
    #   scans the counter, builds a due list, runs _runRefinement for each
    #   under a single global _refineLock  ->  _runRefinement fetches recent
    #   messages, asks the LLM to update persistent facts (via the tools
    #   above) and emit a new short summary, then persists summary + cursors
    #   to chat_users.metadata.memoryRefinement[threadId].

    async def _dtCronJob(self, task: DelayedTask) -> None:
        """Periodic entry point for memory refinement. Runs every 60s via the CRON_JOB delayed task.

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
            for (chatId, userId, threadId), newMessagesCount in candidates:
                # Guard the ENTIRE per-candidate body so a transient DB error
                # (chat settings OR memory-entry read) skips just this one
                # candidate instead of aborting the whole scan.
                try:
                    # Per-chat enable gate (runtime-disable safe).
                    chatSettings = await self.getChatSettings(chatId)
                    if not chatSettings[ChatSettingsKey.MEMORY_REFINEMENT_ENABLED].toBool():
                        continue

                    lastRefinedTS = 0
                    async with self._accountingLock:
                        lastRefinedTS = self._lastRefinedTS.get((chatId, userId, threadId), 0)
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
                            self._lastRefinedTS[(chatId, userId, threadId)] = int(time.time())

    async def _runRefinement(self, chatId: int, userId: int, threadId: int) -> None:
        """Run one memory-refinement LLM pass for a (chat, user, thread).

        Fetches recent messages since the last processed date, asks the LLM to update persistent
        facts (via add_user_data / delete_user_data tools) and produce a new short summary, then
        persists the summary + cursors to chat_users.metadata.memoryRefinement[threadId].

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
        existingSummary = memoryRefinement.get("summary", "")
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

        # Existing persistent knowledge (key/value facts from the user_data table).
        existingUserData = await self.cache.getChatUserData(chatId=chatId, userId=userId)

        # Synthesize a minimal EnsuredMessage so the add/delete user-data tools
        # can resolve chatId/userId (they read recipient.id / sender.id).
        synthEnsuredMessage = self._makeSyntheticEnsuredMessage(chatId=chatId, userId=userId, threadId=threadId)

        systemPrompt = chatSettings[ChatSettingsKey.MEMORY_REFINE_SYSTEM_PROMPT].toStr()
        userPromptTemplate = chatSettings[ChatSettingsKey.MEMORY_REFINE_USER_PROMPT_TEMPLATE].toStr()

        userPrompt = userPromptTemplate.format(
            existingUserData=utils.jsonDumps(existingUserData, indent=2) if existingUserData else "(none)",
            existingSummary=existingSummary or "(none)",
            messages=rendered,
        )

        async def intermediateCallback(res: ModelRunResult, extraData: ExtraDataDict) -> None:
            logger.debug(f"IM# Refining memory of {chatId}:{userId}, thread:{threadId}. Result: {res}")

        logger.debug(
            f"Refining memory for {chatId}:{userId}, thread:{threadId} "
            f"with {len(messages)} messages ({messages[0]['message_id']}..{messages[-1]['message_id']}). "
            f"Previous summary: {existingSummary}"
        )
        newSummary = ""
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
                    ToolName.ADD_USER_DATA: True,
                    ToolName.DELETE_USER_DATA: True,
                    ToolName.SEARCH_MESSAGES: True,
                    ToolName.GET_CURRENT_DATETIME: True,
                },
                extraData={"ensuredMessage": synthEnsuredMessage, "typingManager": None},
            )

            logger.debug(f"Result of refining memory for {chatId}:{userId}, thread:{threadId}: {result}")
            newSummary = (result.resultText or "").strip()
        except Exception as e:
            logger.error(f"Error during refininm gemory of {chatId}:{userId}##{threadId}: {e}")
            logger.exception(e)
            return

        if not newSummary:
            logger.warning("Memory refinement produced empty summary for chatId=%s userId=%s", chatId, userId)
            return

        # Newest processed message is the FIRST entry in the DESC-ordered list.
        newest = messages[0]
        await self._persistMemoryEntry(
            chatId=chatId,
            userId=userId,
            threadId=threadId,
            summary=newSummary,
            lastProcessedMessageId=newest["message_id"].asStr(),
            lastProcessedMessageDate=newest["date"].isoformat(),
        )
        # Record the refinement timestamp in-memory only (not persisted to DB).
        async with self._accountingLock:
            self._lastRefinedTS[(chatId, userId, threadId)] = int(time.time())

    async def _persistMemoryEntry(
        self,
        *,
        chatId: int,
        userId: int,
        threadId: int,
        summary: str,
        lastProcessedMessageId: str,
        lastProcessedMessageDate: str,
    ) -> None:
        """Persist an updated per-thread memory entry via read-modify-write of chat_users.metadata.

        CRITICAL: neither ``setUserMetadata(isUpdate=True)`` (shallow top-level merge
        ``{**old, **new}``) nor ``cache.updateUserMetadata`` (full-dict replace, NO merge)
        can accept a partial ``memoryRefinement`` — both would wipe every other thread's
        summary. Instead we read the full metadata via ``cache.getUserMetadata``, mutate
        only the single ``memoryRefinement[str(threadId)]`` entry, and write the whole
        merged dict back via ``cache.updateUserMetadata`` — bypassing ``setUserMetadata``
        entirely.

        The persisted entry contains ONLY ``summary``/``lastProcessedMessageId``/
        ``lastProcessedMessageDate``. The in-memory-only ``lastRefinedTS`` is set
        separately in ``_runRefinement`` after this method returns and MUST NOT be
        added to the persisted dict.

        The full read-modify-write is serialized via ``cache.chatUserMetadataLock()``
        to avoid lost-update races with concurrent metadata writers (e.g.
        ``setUserMetadata(isUpdate=True)``). The caller ``_runRefinement`` already
        holds ``_refineLock``; the lock ordering is ``_refineLock`` (outer) →
        ``chatUserMetadataLock`` (inner), so this method must NOT be called from a
        context that already holds ``chatUserMetadataLock``.

        Args:
            chatId (int): Chat id.
            userId (int): User id.
            threadId (int): Thread id.
            summary (str): New short summary.
            lastProcessedMessageId (str): MessageId.asStr() of the newest ingested message.
            lastProcessedMessageDate (str): ISO datetime of the newest ingested message.
        """
        async with self.cache.chatUserMetadataLock():
            metadata = await self.cache.getUserMetadata(chatId=chatId, userId=userId)
            refinement = metadata.get("memoryRefinement", {})
            refinement[str(threadId)] = {
                "summary": summary,
                "lastProcessedMessageId": lastProcessedMessageId,
                "lastProcessedMessageDate": lastProcessedMessageDate,
            }
            metadata["memoryRefinement"] = refinement
            await self.cache.updateUserMetadata(chatId=chatId, userId=userId, metadata=metadata)

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
            eMsg = await EnsuredMessage.fromDBChatMessage(msg, self.db)
            renderedParts.append(await eMsg.formatForLLM(self.db, format=LLMMessageFormat.JSON, stripAtsign=True))
        return "\n".join(renderedParts)

    def _makeSyntheticEnsuredMessage(self, *, chatId: int, userId: int, threadId: int) -> EnsuredMessage:
        """Build a minimal EnsuredMessage for background LLM tool calls (add/delete user-data).

        Only ``recipient.id`` and ``sender.id`` are read by the two tool handlers, so the other
        fields are minimal placeholders. ``threadId`` is set on the message for completeness
        though the tools do not currently read it.

        Args:
            chatId (int): Chat id (becomes recipient.id).
            userId (int): User id (becomes sender.id).
            threadId (int): Thread id (set on the synthetic message; unused by the tools).

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
        """
        Handle messages for user data configuration wizard in private chats.

        Always increments the memory-refinement counter for the message's
        (chatId, userId, threadId) when refinement is enabled for the chat,
        regardless of chat type or wizard state, before any early-return.

        Args:
            ensuredMessage (EnsuredMessage): Ensured message object.
            updateObj (UpdateObjectType): Telegram update object.

        Returns:
            HandlerResultStatus: FINAL if the wizard handled the message,
            NEXT otherwise (the increment is work done for every message).
        """

        # Memory-refinement accounting: count this message if refinement is enabled for this chat.
        chatSettings = await self.getChatSettings(ensuredMessage.recipient.id)
        if chatSettings[ChatSettingsKey.MEMORY_REFINEMENT_ENABLED].toBool():
            threadId = ensuredMessage.threadId or DEFAULT_THREAD_ID
            key = (ensuredMessage.recipient.id, ensuredMessage.sender.id, threadId)
            async with self._accountingLock:
                self._accounting[key] = self._accounting.get(key, 0) + 1

        if ensuredMessage.recipient.chatType != ChatType.PRIVATE:
            return HandlerResultStatus.NEXT

        user = ensuredMessage.sender
        userDataConfig = self.cache.getUserState(userId=user.id, stateKey=UserActiveActionEnum.UserDataConfig)
        if userDataConfig is None:
            return HandlerResultStatus.NEXT

        await self.db.chatMessages.updateChatMessageCategory(
            chatId=ensuredMessage.recipient.id,
            messageId=ensuredMessage.messageId,
            messageCategory=MessageCategory.USER_CONFIG_ANSWER,
        )

        await self._handleUserDataConfiguration(
            data={
                **userDataConfig["data"],
                ButtonDataKey.Value: ensuredMessage.formatMessageText(),
            },
            messageId=MessageId(userDataConfig["messageId"]),
            messageChatId=userDataConfig["messageChatId"],
            user=user,
        )
        return HandlerResultStatus.FINAL

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
        """
        Display user data for selected chat with edit options.

        Args:
            data (utils.PayloadDict): Callback data with chat ID.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): Telegram user.
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
        # TODO: Check if user is present in given chat

        logger.debug(f"ChatSelected: chatInfo: {chatInfo}")
        resp = f"Выбран чат {self.getChatTitle(chatInfo)}:\n\n"
        keyboard: List[List[CallbackButton]] = [
            [
                CallbackButton(
                    "Добавить новый ключ",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.KeySelected,
                        ButtonDataKey.ChatId: chatId,
                    },
                )
            ]
        ]

        userData = await self.cache.getChatUserData(chatId=chatId, userId=user.id)
        for k, v in userData.items():
            resp += f"**Ключ**: `{k}`:\n```{k}\n{v}\n```\n\n"
            keyboard.append(
                [
                    CallbackButton(
                        k,
                        {
                            ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.KeySelected,
                            ButtonDataKey.ChatId: chatId,
                            ButtonDataKey.Key: k,
                        },
                    )
                ]
            )

        resp += "Выберите нужное действие:"
        keyboard.append(
            [
                CallbackButton(
                    "Очистить все данные",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ClearChatData,
                        ButtonDataKey.ChatId: chatId,
                    },
                )
            ]
        )
        keyboard.append(
            [
                CallbackButton(
                    "<< Назад",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Init,
                    },
                )
            ]
        )
        keyboard.append([exitButton])
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=resp,
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_ClearChatData(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """
        Clear all user data for selected chat.

        Args:
            data (utils.PayloadDict): Callback data with chat ID.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): Telegram user.
        """
        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )
        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"ClearChatData: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return

        # TODO: Check if user is present in given chat
        await self.cache.clearChatUserData(chatId=chatId, userId=user.id)
        keyboard: List[List[CallbackButton]] = [
            [
                CallbackButton(
                    "<< Назад",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                        ButtonDataKey.ChatId: chatId,
                    },
                )
            ],
            [exitButton],
        ]
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text="Все данные очищены",
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_DeleteKey(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """
        Delete specific user data key from selected chat.

        Args:
            data (utils.PayloadDict): Callback data with chat ID and key.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): Telegram user.
        """
        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )
        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"DeleteKey: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return
        # TODO: Check if user is present in given chat

        # We need to check if key is passed, actually.
        # But I don't care
        key = str(data.get(ButtonDataKey.Key, None))

        await self.cache.unsetChatUserData(chatId=chatId, userId=user.id, key=key)
        keyboard: List[List[CallbackButton]] = [
            [
                CallbackButton(
                    "<< Назад",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                        ButtonDataKey.ChatId: chatId,
                    },
                )
            ],
            [exitButton],
        ]
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=f"Данные по ключу {key} удалены",
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_KeySelected(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """
        Prompt user to enter value for key (new or existing).

        Args:
            data (utils.PayloadDict): Callback data with chat ID and optional key.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): Telegram user.
        """
        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )
        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"KeySelected: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return
        # TODO: Check if user is present in given chat

        key = data.get(ButtonDataKey.Key, None)

        self.cache.setUserState(
            userId=user.id,
            stateKey=UserActiveActionEnum.UserDataConfig,
            value={
                "data": {
                    ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.SetValue,
                    ButtonDataKey.ChatId: chatId,
                    ButtonDataKey.Key: key,
                },
                "messageId": messageId,
                "messageChatId": messageChatId,
            },
        )

        userData = await self.cache.getChatUserData(chatId=chatId, userId=user.id)
        if userData is None:
            userData = {}

        resp = (
            (
                "Введите новый ключ и его значение.\n"
                "Первое слово будет использовано как ключ, остальной текст "
                "будет использован как значение:"
            )
            if key is None
            else f"Введите новое значение для ключа {key}.\n"
            f"Текущее значение:\n```{key}\n{userData.get(str(key), '')}\n```"
        )

        keyboard: List[List[CallbackButton]] = [
            [
                CallbackButton(
                    "Удалить выбраный ключ",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.DeleteKey,
                        ButtonDataKey.ChatId: chatId,
                        ButtonDataKey.Key: key,
                    },
                )
            ],
            [
                CallbackButton(
                    "<< Назад",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                        ButtonDataKey.ChatId: chatId,
                    },
                )
            ],
            [exitButton],
        ]
        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=resp,
            inlineKeyboard=keyboard,
        )

    async def _handleConfigAction_SetValue(
        self,
        data: utils.PayloadDict,
        *,
        messageId: MessageId,
        messageChatId: int,
        user: MessageSender,
    ) -> None:
        """
        Set or update user data value, extracting key from message if needed.

        Args:
            data (utils.PayloadDict): Callback data with chat ID, optional key, and value.
            messageId (MessageId): Message ID to edit.
            messageChatId (int): Chat ID where the message is located.
            user (MessageSender): Telegram user.
        """
        exitButton = CallbackButton(
            "Закончить настройку",
            {ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.Cancel},
        )
        chatId = data.get(ButtonDataKey.ChatId, None)

        if not isinstance(chatId, int):
            logger.error(f"SetValue: wrong chatId: {type(chatId).__name__}#{chatId}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Ошибка: некорректный идентификатор чата",
            )
            return
        # TODO: Check if user is present in given chat

        key = data.get(ButtonDataKey.Key, None)
        value = data.get(ButtonDataKey.Value, None)

        if not value:
            logger.error(f"SetValue: Value is empty in {data}")
            await self.editMessage(
                messageId=messageId,
                chatId=messageChatId,
                text="Произошла ошибка",
            )
            return

        if key is None:
            key, value = str(value).split(" ", 1)

        await self.cache.setChatUserData(chatId=chatId, userId=user.id, key=str(key), value=str(value))

        keyboard: List[List[CallbackButton]] = [
            [
                CallbackButton(
                    "<< Назад",
                    {
                        ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                        ButtonDataKey.ChatId: chatId,
                    },
                )
            ],
            [exitButton],
        ]

        await self.editMessage(
            messageId=messageId,
            chatId=messageChatId,
            text=f"Готово, теперь ключ {key} установлен в \n```{key}\n{value}\n```",
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
            case ButtonUserDataConfigAction.ClearChatData:
                await self._handleConfigAction_ClearChatData(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.DeleteKey:
                await self._handleConfigAction_DeleteKey(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.KeySelected:
                await self._handleConfigAction_KeySelected(
                    data, messageId=messageId, messageChatId=messageChatId, user=user
                )
            case ButtonUserDataConfigAction.SetValue:
                await self._handleConfigAction_SetValue(
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
        """
        Display stored user data as JSON.

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

        userData = await self.cache.getChatUserData(chatId=targetChatId, userId=ensuredMessage.sender.id)

        await self.sendMessage(
            ensuredMessage,
            messageText=(f"```json\n{utils.jsonDumps(userData, indent=2)}\n```"),
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )

    @commandHandlerV2(
        commands=("knowledge_config",),
        shortDescription="Start wisard for user-data manaagement",
        helpMessage=": Запустить мастер управления знаниями бота о вас.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.PRIVATE},
        helpOrder=CommandHandlerOrder.WIZARDS,
        category=CommandCategory.PRIVATE,
    )
    async def knowledge_config_command(
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
            messageText="Запускаю мастер управления знаниями бота о вас...",
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
