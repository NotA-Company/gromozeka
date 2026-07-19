"""LLM Service module for managing language model interactions and tool execution.

This module provides a singleton service for interacting with Large Language Models (LLMs),
managing tool registration and execution, and handling multi-turn conversations with tool calls.
The service supports fallback models and provides a unified interface for LLM operations.
"""

import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, MutableSequence, MutableSet, Sequence
from threading import RLock
from typing import Any, Dict, List, Optional, Set, Tuple, TypeAlias, Union

from internal.bot.models.chat_settings import ChatSettingsDict, ChatSettingsKey
from internal.bot.models.ensured_message import EnsuredMessage
from internal.bot.models.message_metadata import CondensingDict, renderCondensedSummary
from internal.models.types import MessageId
from lib import utils
from lib.ai.abstract import AbstractModel
from lib.ai.manager import LLMManager
from lib.ai.models import (
    LLMAbstractTool,
    LLMFunctionParameter,
    LLMToolCall,
    LLMToolFunction,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
    ModelStructuredResult,
)
from lib.rate_limiter.manager import RateLimiterManager

from .constants import DEFAULT_MAX_ROUNDS, TOOLS_DEFAULT_DICT_KEY
from .models import ExtraDataDict

logger = logging.getLogger(__name__)


LLMToolHandler: TypeAlias = Callable[..., Awaitable[Union[str, Dict[str, Any], None]]]
"""Type alias for async tool handler functions.

Handlers are async callables that take tool parameters and extra data,
and return a string, a JSON-serializable dict, or None (serialized as \"null\").
The function signature is flexible: parameters are passed as keyword arguments
matching the tool's schema.

Example:
    async def my_tool(param1: str, param2: int, **extra: Any) -> Union[str, Dict[str, Any], None]:
        return f"processed {param1} with {param2}"
"""

UseToolsType: TypeAlias = Union[bool, Dict[str, bool]]
"""Type alias for the useTools parameter in generateTextViaLLM.

Accepts:
- ``True``: all registered tools are enabled.
- ``False``: no tools are enabled.
- ``dict[str, bool]``: per-tool enable/disable map. The :data:`TOOLS_DEFAULT_DICT_KEY`
  key (``"default"``) controls all tools not explicitly listed (defaults to
  ``False`` if absent). Unknown keys (tool names not in the registry) are
  logged as warnings and ignored.
"""


def generateCondensingDict(text: str, messages: Sequence[ModelMessage]) -> CondensingDict:
    """Build a CondensingDict from summary text and the covered ModelMessages.

    Walks ``messages`` and reads each ``message.source`` to derive the
    coverage metadata:

    - ``EnsuredMessage`` source → extract ``messageId``, ``sender.username``,
      and ``date.timestamp()`` (a raw source message).
    - ``dict`` source (a pre-existing ``CondensingDict`` being re-condensed)
      → union the existing ``messageIds`` / ``participants`` / ``dateRange``
      / ``messageCount`` fields (re-condense cascade).
    - ``None`` source → log a warning and still increment ``messageCount``
      (the running total is bumped unconditionally); only metadata extraction
      (``messageId`` / ``sender.username`` / ``date``) is skipped, since this
      is an auxiliary tool-history emission, not an original message.

    The returned dict always carries ``text``; ``messageIds``,
    ``dateRange``, ``participants``, and ``messageCount`` are populated
    only when the corresponding coverage data is non-empty.

    Does NOT set ``tillMessageId`` / ``tillTS`` — those legacy boundary
    markers are left to the caller if needed.

    Args:
        text: The summary text produced by the condensing model.
        messages: The covered ModelMessages — each must have ``.source``
            set: an :class:`EnsuredMessage` for raw messages, or a
            ``dict`` / :class:`CondensingDict` for re-condensed summaries.

    Returns:
        A :class:`CondensingDict` with ``text`` plus conditionally-populated
        ``messageIds`` / ``participants`` / ``dateRange`` / ``messageCount``.
    """
    ret = CondensingDict(
        text=text,
    )
    messageIdList: List[MessageId] = []
    dateList: List[float] = []
    participants: MutableSet[str] = set()
    messageCount = 0
    for message in messages:
        if message.source is None:
            messageCount += 1
            logger.warning(f"Message {message} has no source, skipping")
        elif isinstance(message.source, EnsuredMessage):
            messageCount += 1
            messageIdList.append(message.source.messageId)
            if message.source.sender.username:
                participants.add(message.source.sender.username)
            dateList.append(message.source.date.timestamp())
        elif isinstance(message.source, dict):
            # The only available dict here is CondensingDict
            if "messageIds" in message.source:
                messageIdList.extend(message.source["messageIds"])
            if "participants" in message.source:
                participants.update(message.source["participants"])
            if "dateRange" in message.source:
                dateList.append(message.source["dateRange"]["from"])
                dateList.append(message.source["dateRange"]["to"])
            if "messageCount" in message.source:
                messageCount += message.source["messageCount"]
            else:
                messageCount += 1
        else:
            logger.warning(f"Message {message} has unknown source type: {type(message.source)}, skipping")
            messageCount += 1

    if messageIdList:
        ret["messageIds"] = messageIdList
    if dateList:
        ret["dateRange"] = {"from": min(dateList), "to": max(dateList)}
    if participants:
        ret["participants"] = list(participants)
    if messageCount:
        ret["messageCount"] = messageCount
    return ret


class LLMService:
    """Singleton service for managing LLM interactions and tool execution.

    This service provides a centralized interface for:
    - Registering and managing LLM tools (functions that the LLM can call)
    - Generating text responses using LLMs with automatic tool execution
    - Handling multi-turn conversations with tool calls
    - Supporting fallback models for reliability

    The service implements the singleton pattern with thread-safe initialization
    to ensure only one instance exists throughout the application lifecycle.

    Attributes:
        toolsHandlers: Dictionary mapping tool names to their LLMToolFunction definitions
        rateLimiterManager: Manager for applying rate limits to LLM calls
        initialized: Flag indicating whether the instance has been initialized
    """

    _instance: Optional["LLMService"] = None
    """Singleton instance of LLMService, stored at class level for pattern enforcement."""
    _lock = RLock()
    """Reentrant lock used for thread-safe singleton initialization."""

    def __new__(cls) -> "LLMService":
        """Create or return singleton instance with thread safety.

        This method implements the singleton pattern and ensures that only
        one instance of LLMService exists throughout the application lifecycle.
        Uses a reentrant lock to guarantee thread-safe initialization.

        Returns:
            The singleton LLMService instance
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        """Initialize the LLMService instance with default values.

        Sets up the tools handlers dictionary and marks the instance as initialized.
        This method uses a guard to prevent re-initialization of the singleton instance.
        Only runs initialization logic once per singleton lifecycle.
        """
        if not hasattr(self, "initialized"):
            self.toolsHandlers: Dict[str, LLMToolFunction] = {}
            self.rateLimiterManager = RateLimiterManager()
            self.llmManager: Optional[LLMManager] = None

            self.initialized = True
            logger.info("LLMService initialized")

    @classmethod
    def getInstance(cls) -> "LLMService":
        """Get the singleton instance of LLMService.

        Returns:
            The singleton LLMService instance
        """
        return cls()

    def injectLLMManager(self, llmManager: LLMManager) -> None:
        """Inject an LLMManager instance into the LLMService.

        Args:
            llmManager: The LLMManager instance to inject

        Returns:
            None
        """
        self.llmManager = llmManager

    def registerTool(
        self, name: str, description: str, parameters: Sequence[LLMFunctionParameter], handler: LLMToolHandler
    ) -> None:
        """Register a new tool for the LLM service.

        Registers a tool that the LLM can call during text generation. Tools are
        stored in the toolsHandlers dictionary and can be invoked when the LLM
        makes tool calls. Each tool has a name, description, parameter schema,
        and an async handler function.

        Args:
            name: The unique name identifier for the tool
            description: The description of what the tool does
            parameters: The parameter schema for the tool function
            handler: The async handler function that executes the tool logic

        Returns:
            None
        """
        self.toolsHandlers[name] = LLMToolFunction(
            name=name,
            description=description,
            parameters=parameters,
            function=handler,
        )
        logger.info(f"Tool {name} registered")

    def _resolveTools(self, useTools: UseToolsType) -> List[LLMToolFunction]:
        """Resolve the useTools parameter into the list of tools to send to the LLM.

        Converts the ``useTools`` parameter (bool or dict) into the concrete list
        of :class:`LLMToolFunction` objects that should be offered to the LLM.
        When a dict is supplied, the :data:`TOOLS_DEFAULT_DICT_KEY` key controls every
        tool not explicitly listed (defaulting to ``False`` when absent). Tool
        names in the dict that are not present in :attr:`toolsHandlers` are
        logged as warnings and silently ignored.

        Args:
            useTools: Boolean or dict controlling tool enablement. ``True``
                enables all registered tools, ``False`` disables all, and a
                dict enables/disables tools per-name with
                :data:`TOOLS_DEFAULT_DICT_KEY` as the fallback for unspecified
                tools.

        Returns:
            The filtered list of LLMToolFunction objects to send to the LLM.
        """
        if isinstance(useTools, dict):
            defaultEnabled = useTools.get(TOOLS_DEFAULT_DICT_KEY, False)
            filteredTools: List[LLMToolFunction] = []
            for toolName, tool in self.toolsHandlers.items():
                if useTools.get(toolName, defaultEnabled):
                    filteredTools.append(tool)

            knownNames: Set[str] = set(self.toolsHandlers.keys())
            for key in useTools:
                if key != TOOLS_DEFAULT_DICT_KEY and key not in knownNames:
                    logger.warning(f"Unknown tool name '{key}' in useTools dict, ignoring")

            return filteredTools
        elif useTools:
            return list(self.toolsHandlers.values())
        return []

    def _tryApplyToolCallMatch(
        self,
        mlRunResult: ModelRunResult,
        *,
        toolName: str,
        parameters: Optional[Dict[str, Any]],
        toolCallId: Optional[str],
        prefixStr: str,
        suffixStr: str,
    ) -> bool:
        """Validate extracted tool-call fields and, if they pass, mutate *mlRunResult* in-place.

        This is the shared tail of :meth:`_matchTextForJSONToolCall`,
        :meth:`_matchTextForToolCallStart`, and
        :meth:`_matchTextForToolCallSquareBracketsAndJson`.  The match is
        accepted only when the tool call appears at the **beginning or end**
        of the response (i.e. *prefixStr* or *suffixStr* is empty) **and**
        *toolName* is registered in :attr:`toolsHandlers` and *parameters*
        is a dict.

        Args:
            mlRunResult: The model run result to mutate on success.
            toolName: The tool name extracted from the response.
            parameters: The argument dict extracted from the response (may be
                ``None`` or non-dict, which will cause the match to fail).
            toolCallId: The call ID from the response, or ``None`` to
                auto-generate one via ``uuid4``.
            prefixStr: Non-tool-call text before the matched block.
            suffixStr: Non-tool-call text after the matched block.

        Returns:
            True if the match was applied (``mlRunResult`` mutated to
            ``TOOL_CALLS`` status); False otherwise.
        """
        if (
            (not prefixStr or not suffixStr)
            and toolName
            and isinstance(parameters, dict)
            and toolName in self.toolsHandlers
        ):
            logger.debug("It looks like tool call, converting...")
            mlRunResult.status = ModelResultStatus.TOOL_CALLS
            mlRunResult.resultText = (prefixStr + suffixStr).strip()
            if toolCallId is None:
                toolCallId = str(uuid.uuid4())
            mlRunResult.toolCalls = [LLMToolCall(id=toolCallId, name=toolName, parameters=parameters)]
            return True
        return False

    def _tryParseJson(self, data: str) -> Tuple[Any, int]:
        """Parse JSON string with fallback for common formatting issues.

        Attempts to parse a JSON string using the standard JSON decoder. If that
        fails, tries to fix a common issue where single quotes are incorrectly
        escaped (e.g., `\'` inside a double‑quoted string) before retrying.
        The method returns both the parsed Python object and the index where
        parsing stopped, matching the signature of `json.JSONDecoder.raw_decode`.

        Args:
            data: The JSON string to parse.

        Returns:
            A tuple (parsed_object, end_index) where `parsed_object` is the
            decoded Python object (dict, list, etc.) and `end_index` is the
            position in `data` immediately after the parsed JSON.

        Raises:
            json.JSONDecodeError: If the input cannot be parsed even after the
                fallback attempt. The original error is re‑raised.
        """
        try:
            return json.JSONDecoder().raw_decode(data)
        except json.JSONDecodeError:
            # Try to fix common issues
            try:
                return json.JSONDecoder().raw_decode(re.sub(r"(?<=[^\\])\\'", r"'", data))
            except json.JSONDecodeError as e2:
                logger.warning(f"JSON fix attempt failed: {e2}")
            # If nothing helps, just reraise original error
            raise

    def _matchTextForJSONToolCall(self, mlRunResult: ModelRunResult) -> bool:
        """Detect a tool call embedded in a JSON code block within the model response text.

        Some LLMs wrap tool-call JSON in markdown code fences (```json ... ```)
        instead of using native tool-call APIs. This method extracts that JSON,
        checks whether it contains a recognised tool name with dict-typed
        arguments/parameters, and — if so — mutates *mlRunResult* in-place to
        reflect a ``TOOL_CALLS`` status.

        The match is only accepted when the JSON block appears at the **beginning
        or end** of the response (i.e. the non-JSON prefix or suffix is empty), to
        avoid false positives on responses that merely happen to contain a JSON
        snippet.

        Args:
            mlRunResult: The model run result to inspect and potentially mutate.

        Returns:
            True if a valid tool call was detected and *mlRunResult* was converted;
            False otherwise.
        """
        resultText = mlRunResult.resultText.strip()
        match = re.match(r"^(.*?)```(?:json\s*)?\s*({.*})\s*```(.*)$", resultText, re.DOTALL | re.IGNORECASE)
        if match is not None:
            logger.debug(f"JSON found: {match.groups()}")
            try:
                jsonStr = match.group(2)
                jsonData, endPos = self._tryParseJson(jsonStr)
                suffixStr = jsonStr[endPos:] + match.group(3)
                logger.debug(f"JSON result: {jsonData}")
                parameters = None
                if "arguments" in jsonData:
                    parameters = jsonData.get("arguments", None)
                elif "parameters" in jsonData:
                    parameters = jsonData.get("parameters", None)
                return self._tryApplyToolCallMatch(
                    mlRunResult,
                    toolName=jsonData.get("name", ""),
                    parameters=parameters,
                    toolCallId=jsonData.get("callId", None),
                    prefixStr=match.group(1),
                    suffixStr=suffixStr,
                )
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to decode JSON: {e}")
        return False

    def _matchTextForToolCallTags(self, mlRunResult: ModelRunResult) -> bool:
        """Detect a tool call embedded in ``<tool_call>...</tool_call>`` tags.

        Some LLMs (notably certain chat models) wrap a tool-call JSON object in
        ``<tool_call>`` / ``</tool_call>`` tags instead of using native tool-call
        APIs or markdown code fences. This method extracts that JSON, checks
        whether it contains a recognised tool name with dict-typed
        arguments/parameters, and — if so — mutates *mlRunResult* in-place to
        reflect a ``TOOL_CALLS`` status.

        The match is only accepted when the ``<tool_call>`` block appears at
        the **beginning or end** of the response (i.e. the non-tag prefix or
        suffix is empty), to avoid false positives on responses that merely
        happen to contain a tagged snippet. This begin/end-edge rule is
        enforced by the shared :meth:`_tryApplyToolCallMatch` helper, not in
        this method itself.

        Args:
            mlRunResult: The model run result to inspect and potentially mutate.

        Returns:
            True if a valid tool call was detected and *mlRunResult* was converted;
            False otherwise.
        """
        resultText = mlRunResult.resultText.strip()
        match = re.match(r"^(.*?)<tool_call>\s*({.*})\s*</tool_call>(.*)$", resultText, re.DOTALL | re.IGNORECASE)
        if match is not None:
            logger.debug(f"<tool_call> tags found: {match.groups()}")
            try:
                jsonStr = match.group(2)
                jsonData, endPos = self._tryParseJson(jsonStr)
                suffixStr = jsonStr[endPos:] + match.group(3)
                logger.debug(f"<tool_call> JSON result: {jsonData}")
                parameters = None
                if "arguments" in jsonData:
                    parameters = jsonData.get("arguments", None)
                elif "parameters" in jsonData:
                    parameters = jsonData.get("parameters", None)
                return self._tryApplyToolCallMatch(
                    mlRunResult,
                    toolName=jsonData.get("name", ""),
                    parameters=parameters,
                    toolCallId=jsonData.get("callId", None),
                    prefixStr=match.group(1),
                    suffixStr=suffixStr,
                )
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to decode <tool_call> JSON: {e}")
        return False

    def _matchTextForToolCallStart(self, mlRunResult: ModelRunResult) -> bool:
        """Detect a tool call using the ``[TOOL_CALL_START]`` marker format.

        Some models emit a proprietary ``[TOOL_CALL_START] <name>{json}`` pattern
        instead of native tool-call responses. This method matches that pattern,
        validates the tool name and argument dict, and converts *mlRunResult* to
        ``TOOL_CALLS`` status when the marker appears at the beginning or end of
        the response text.

        Args:
            mlRunResult: The model run result to inspect and potentially mutate.

        Returns:
            True if a valid tool call was detected and *mlRunResult* was converted;
            False otherwise.
        """
        resultText = mlRunResult.resultText.strip()
        match = re.match(
            r"^(.*?)\[TOOL_CALL_START\]\s*(\S+?)\s*({.*})\s*(.*?)\s*$",
            resultText,
            re.DOTALL,
        )
        if match is not None:
            try:
                logger.debug(f"TOOL_CALL_START found: {match.groups()}")
                toolArgsStr = match.group(3)
                toolArgs, endPos = self._tryParseJson(toolArgsStr)
                suffixStr = toolArgsStr[endPos:].strip() + match.group(4)
                return self._tryApplyToolCallMatch(
                    mlRunResult,
                    toolName=match.group(2),
                    parameters=toolArgs,
                    toolCallId=None,
                    prefixStr=match.group(1),
                    suffixStr=suffixStr,
                )
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to decode JSON: {e!r}")
        return False

    def _matchTextForToolCallSquareBracketsAndJson(self, mlRunResult: ModelRunResult) -> bool:
        """Detect a tool call in the ``[tool_name]\\n{json}`` bracket-and-JSON format.

        Certain models represent tool calls as a bracketed tool name on one line
        followed by a JSON argument object, e.g.::

            [web_search]
            {"query": "example", "max_results": 3}

        This method matches that pattern, validates the tool name against
        registered handlers, and converts *mlRunResult* to ``TOOL_CALLS``
        status when the pattern appears at the beginning or end of the response.

        Args:
            mlRunResult: The model run result to inspect and potentially mutate.

        Returns:
            True if a valid tool call was detected and *mlRunResult* was converted;
            False otherwise.
        """
        resultText = mlRunResult.resultText.strip()
        match = re.match(
            r"^(.*?)\s*\[(\S+?)\]\s*({.*})\s*(.*?)\s*$",
            resultText,
            re.DOTALL,
        )
        if match is not None:
            try:
                logger.debug(f"[tool_name]+{{json}} found: {match.groups()}")
                toolArgsStr = match.group(3)
                toolArgs, endPos = self._tryParseJson(toolArgsStr)
                suffixStr = toolArgsStr[endPos:].strip() + match.group(4)
                return self._tryApplyToolCallMatch(
                    mlRunResult,
                    toolName=match.group(2),
                    parameters=toolArgs,
                    toolCallId=None,
                    prefixStr=match.group(1),
                    suffixStr=suffixStr,
                )
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to decode JSON: {e}")
        return False

    def _matchTextForBrokenKnownToolCall(self, mlRunResult: ModelRunResult) -> bool:
        """Detect a broken-but-recognised tool call as a last-resort fallback.

        This is the final healing strategy, run only after every proper matcher
        (:meth:`_matchTextForJSONToolCall`, :meth:`_matchTextForToolCallTags`,
        :meth:`_matchTextForToolCallStart`,
        :meth:`_matchTextForToolCallSquareBracketsAndJson`) has failed. It
        detects a **registered** tool name referenced inside a bracket-like
        block at the **beginning or end** of the message that could not be
        parsed as a real tool call (e.g. an unparseable pseudo-call such as
        ``[Вызов функции `generate_and_send_image` с промтом: «...»]``).

        Instead of healing the call into a real execution, it synthesises a
        tool call carrying an ``errorMessage`` that asks the model to retry
        with a proper tool call. The execution loop never invokes the handler
        for such a call — it feeds the error back to the model.

        The begin/end-edge constraint avoids firing on mid-prose mentions of a
        tool name: the bracket block must be at the message start or end.

        Args:
            mlRunResult: The model run result to inspect and mutate.

        Returns:
            True if a registered tool name was found inside an edge bracket
            block and *mlRunResult* was converted to ``TOOL_CALLS`` with a
            retry ``errorMessage``; False otherwise.
        """
        resultText = mlRunResult.resultText.strip()
        # A bracketed block (content may contain spaces) optionally followed by a
        # {...} block, optionally wrapped in code fences — at the BEGINNING or
        # END of the text.
        match = re.match(
            r"^(.*?)(?:```)?\s*\[(.+?)\]\s*(\{.*\})?\s*(?:```)?\s*(.*)$",
            resultText,
            re.DOTALL,
        )
        if match is None:
            return False
        prefixStr = match.group(1)
        bracketContent = match.group(2)
        bracesContent = match.group(3) or ""
        suffixStr = match.group(4)
        # Only accept when the bracket block is at an edge (prefix or suffix
        # empty), consistent with the other matchers' begin/end rule.
        if prefixStr.strip() and suffixStr.strip():
            return False
        # Accepted trade-off of this "bracket-at-edge + known name" heuristic: a
        # bracket block at the message edge whose content word-boundary-matches a
        # registered tool name is treated as a broken-call candidate, so a bare
        # markdown link like ``[generate_and_send_image](url)`` as the
        # whole/trailing response would also match. Tightening to require
        # call-like markers (backticks / "function" / "вызов") would risk
        # under-matching the real broken-call failures this exists to recover.
        haystack = bracketContent + " " + bracesContent
        knownToolName: Optional[str] = None
        # If the bracket block contains more than one registered tool name, the
        # first one found (toolsHandlers dict-iteration order) wins. This is
        # acceptable by design: the handler is never executed for a broken call
        # — only a generic "retry" error is emitted, naming whichever tool matched.
        for toolName in self.toolsHandlers:
            if re.search(rf"(?<![\w]){re.escape(toolName)}(?![\w])", haystack):
                knownToolName = toolName
                break
        if knownToolName is None:
            return False
        # Synthesise a tool call that signals "broken, retry" WITHOUT executing
        # the handler.
        mlRunResult.status = ModelResultStatus.TOOL_CALLS
        mlRunResult.resultText = (prefixStr + suffixStr).strip()
        mlRunResult.toolCalls = [
            LLMToolCall(
                id=str(uuid.uuid4()),
                name=knownToolName,
                parameters={},
                errorMessage=f"Found broken call of tool '{knownToolName}', retry with proper tool call",
            )
        ]
        return True

    def _tryHealToolCall(self, mlRunResult: ModelRunResult) -> bool:
        """Try every known tool-call healing/recovery strategy on a FINAL model response, in priority order.

        Each strategy (in order) inspects *mlRunResult* and, on success,
        mutates it in-place (to ``TOOL_CALLS`` status) and short-circuits the
        chain. The priority order is:

        1. :meth:`_matchTextForJSONToolCall` — JSON inside markdown code fences.
        2. :meth:`_matchTextForToolCallTags` — JSON inside ``<tool_call>`` tags.
        3. :meth:`_matchTextForToolCallStart` — ``[TOOL_CALL_START]`` marker.
        4. :meth:`_matchTextForToolCallSquareBracketsAndJson` — ``[name]\\n{json}``.
        5. :meth:`_matchTextForBrokenKnownToolCall` — broken call of a known
           tool, converted to a retry-error instead of an execution.

        Args:
            mlRunResult: The model run result to inspect and potentially mutate.

        Returns:
            True if any strategy was applied (``mlRunResult`` mutated to
            ``TOOL_CALLS``); False if the response contains no recognisable
            tool-call-like content.
        """
        if self._matchTextForJSONToolCall(mlRunResult):
            return True
        if self._matchTextForToolCallTags(mlRunResult):
            return True
        if self._matchTextForToolCallStart(mlRunResult):
            return True
        if self._matchTextForToolCallSquareBracketsAndJson(mlRunResult):
            return True
        if self._matchTextForBrokenKnownToolCall(mlRunResult):
            return True
        return False

    async def generateTextViaLLM(
        self,
        messages: Sequence[ModelMessage],
        *,
        chatId: Optional[int],
        chatSettings: ChatSettingsDict,
        modelKey: Optional[Union[AbstractModel, ChatSettingsKey]],
        fallbackModelKey: Optional[Union[AbstractModel, ChatSettingsKey]],
        useTools: UseToolsType = False,
        callId: Optional[str] = None,
        callback: Optional[Callable[[ModelRunResult, ExtraDataDict], Awaitable[None]]] = None,
        extraData: ExtraDataDict,
        keepFirstN: int = 0,
        keepLastN: int = 1,
        maxTokensCoeff: float = 0.8,
        condensingPromptKey: Optional[Union[str, ChatSettingsKey]] = None,
        condensingSystemPromptKey: Optional[Union[str, ChatSettingsKey]] = None,
        condensingModelKey: Optional[Union[AbstractModel, ChatSettingsKey]] = None,
        maxRounds: Optional[int] = DEFAULT_MAX_ROUNDS,
    ) -> ModelRunResult:
        """Generate text using an LLM with automatic tool execution support.

        This method handles the complete LLM interaction flow including:
        - Sending messages to the primary model with fallback support
        - Detecting and executing tool calls requested by the LLM
        - Managing multi-turn conversations when tools are used
        - Invoking callbacks for tool call events
        - Condensing context when it exceeds token limits

        The method runs in a loop, executing tool calls and feeding results back
        to the LLM until a final text response is generated or an error occurs.

        Args:
            messages: List of conversation messages to send to the LLM
            chatId: The Telegram/Max chat identifier used for rate-limiting
            chatSettings: Chat-level settings dict used to resolve models and the rate limiter name
            modelKey: Primary model selector - an AbstractModel instance, a ChatSettingsKey,
                or None to fall back to ChatSettingsKey.CHAT_MODEL
            fallbackModelKey: Fallback model selector - same semantics as modelKey,
                defaults to ChatSettingsKey.FALLBACK_MODEL when None
            useTools: Controls tool calling. ``True`` enables all registered
                tools, ``False`` disables all, and a ``dict[str, bool]`` enables
                or disables individual tools by name. The :data:`TOOLS_DEFAULT_DICT_KEY`
                key (``"default"``) controls any tool not explicitly listed
                (defaults to ``False`` when absent); unknown tool names are
                logged as warnings.
            callId: Optional unique identifier for this LLM call (auto-generated if None)
            callback: Optional async callback invoked when tool calls are made,
                receives the ModelRunResult and extraData
            extraData: Optional dictionary of extra data passed to tool handlers and callbacks
            keepFirstN: Number of messages to keep from the beginning when condensing context
            keepLastN: Number of messages to keep from the end when condensing context
            maxTokensCoeff: Multiplier for context size token limit (0.8 = 80% of context size)
            condensingPromptKey: Optional key for the condensing prompt text
            condensingSystemPromptKey: Optional key for the condensing system prompt
            condensingModelKey: Optional model to use for summarizing messages
            maxRounds: Maximum number of rounds the model is allowed to call
                tools before the tool budget is considered exhausted. Defaults
                to :data:`DEFAULT_MAX_ROUNDS` (32). Must be a non-negative
                integer or ``None``. Once exhausted: tool schemas are dropped
                (``tools=[]``), the ``filteredToolNames`` execution allowlist
                is cleared (so even healed tool calls are blocked), tool-call
                healing is disabled, a steering directive is injected, the loop
                is forced to terminate within one additional round, and
                ``ret.roundLimitHit`` is set to ``True``. A fallback answer is
                synthesized only when the model produced no usable text AND the
                status isn't a genuine error (empty FINAL, or post-budget
                TOOL_CALLS); genuine error statuses (ERROR / CONTENT_FILTER /
                UNKNOWN) propagate untouched so callers can detect the failure.
                Pass ``None`` to disable the limit (unlimited rounds); ``0``
                drops tools on the very first call.

        Returns:
            ModelRunResult containing the final LLM response, with toolsUsed flag set
            if any tools were executed during the conversation
        """
        if callId is None:
            callId = str(uuid.uuid4())

        # Fail fast on an invalid budget: a negative maxRounds would otherwise
        # behave like 0 by accident (the ``>=`` guard fires immediately).
        if maxRounds is not None and maxRounds < 0:
            raise ValueError("maxRounds must be a non-negative integer or None")

        model = self.resolveModel(
            modelKey,
            chatSettings=chatSettings,
            defaultKey=ChatSettingsKey.CHAT_MODEL,
        )
        fallbackModel = self.resolveModel(
            fallbackModelKey,
            chatSettings=chatSettings,
            defaultKey=ChatSettingsKey.FALLBACK_MODEL,
        )
        condensingModel = self.resolveModel(
            condensingModelKey,
            chatSettings=chatSettings,
            defaultKey=ChatSettingsKey.CONDENSING_MODEL,
        )
        condensingPrompt = None
        if isinstance(condensingPromptKey, ChatSettingsKey):
            condensingPrompt = chatSettings[condensingPromptKey].toStr()
        elif isinstance(condensingPromptKey, str):
            condensingPrompt = condensingPromptKey
        else:
            condensingPrompt = chatSettings[ChatSettingsKey.CONDENSING_PROMPT].toStr()

        condensingSystemPrompt = None
        if isinstance(condensingSystemPromptKey, ChatSettingsKey):
            condensingSystemPrompt = chatSettings[condensingSystemPromptKey].toStr()
        elif isinstance(condensingSystemPromptKey, str):
            condensingSystemPrompt = condensingSystemPromptKey
        else:
            condensingSystemPrompt = chatSettings[ChatSettingsKey.CONDENSING_SYSTEM_PROMPT].toStr()

        ret: Optional[ModelRunResult] = None
        toolsUsed = False
        tools: Sequence[LLMToolFunction] = self._resolveTools(useTools)
        filteredToolNames: Set[str] = {tool.name for tool in tools}
        _keepLastN = keepLastN

        _messages: Sequence[ModelMessage] = messages
        toolsHistory: MutableSequence[ModelMessage] = []

        roundN: int = 0
        while True:
            # Once the tool-calling round budget is exhausted, force a final
            # answer: stop offering tool schemas, clear the filteredToolNames
            # allowlist so tool execution (including healed tool calls) is
            # blocked, and steer the model toward answering now.
            budgetExhausted: bool = maxRounds is not None and roundN >= maxRounds
            if budgetExhausted:
                tools = []
                filteredToolNames = set()

            # First - condense context if needed
            maxTokens = int(model.contextSize * maxTokensCoeff)
            _messages, _ = await self.condenseContext(
                _messages,
                model,
                keepFirstN=keepFirstN,
                keepLastN=_keepLastN,
                maxTokens=maxTokens,
                condensingModel=condensingModel,
                condensingPrompt=condensingPrompt,
                condensingSystemPrompt=condensingSystemPrompt,
            )

            # Inject the steering directive AFTER condense (which returns a
            # fresh sequence each iteration) and BEFORE generateText, so it
            # actually reaches the model. Built as a fresh list to avoid
            # mutating the caller's / condensed structures.
            #
            # Role choice (provider-safety): a mid-conversation ``role="system"``
            # is accepted by the OpenAI-compatible providers (basic/custom/
            # yc-openai/openrouter serialise ``{"role":..,"content":..}`` to
            # /chat/completions, which permits system messages anywhere), but
            # the YC SDK provider (``YcSdkProvider._convertMessages``) emits
            # ``{"role":"system","text":..}`` straight to the SDK, which
            # historically expects system only as the leading message and may
            # ignore or mishandle a mid-stream one. To stay universally safe we
            # fold the directive into the existing LEADING system message when
            # one is present (condenseContext guarantees it stays at index 0);
            # otherwise we fall back to ``role="user"``, which every provider
            # accepts.
            if budgetExhausted:
                # Assumes a single post-budget iteration (loop is hard-bounded above);
                # reintroducing multiple post-budget iterations would compound this
                # steering text via condenseContext — re-evaluate.
                steeringText = (
                    "You have reached the maximum number of tool-use rounds."
                    " Stop calling tools and provide your final answer to the"
                    " user now, using only the information you have already gathered."
                )
                messagesList: List[ModelMessage] = [*_messages]
                if messagesList and messagesList[0].role == "system":
                    leadingSystem = messagesList[0]
                    messagesList[0] = ModelMessage(
                        role="system",
                        content=f"{leadingSystem.content}\n\n{steeringText}",
                    )
                    _messages = messagesList
                else:
                    _messages = [*messagesList, ModelMessage(role="user", content=steeringText)]

            ret = await self.generateText(
                _messages,
                chatId=chatId,
                chatSettings=chatSettings,
                modelKey=model,
                fallbackKey=fallbackModel,
                tools=tools,
                doDebugLogging=False,
            )
            roundN += 1
            logger.debug(f"LLM returned: {ret} for callId #{callId}")
            # Healing converts a FINAL text shaped like a tool call back into
            # TOOL_CALLS. Post-budget that would re-arm the very execution we
            # just disabled (filteredToolNames is empty, tools is []), so gate
            # healing on a non-exhausted budget: post-budget FINAL text is
            # treated as truly final.
            if ret.status == ModelResultStatus.FINAL and ret.resultText and not budgetExhausted:
                # Try to heal/recover tool calls embedded in the text response.
                self._tryHealToolCall(ret)

            # Execute tool calls only while the budget allows. Post-budget we
            # must NOT enter this branch even on a native TOOL_CALLS: a
            # glitching/loose provider may keep emitting TOOL_CALLS despite the
            # empty ``tools=[]``, and entering here would append "tool not
            # available" results and re-iterate forever. Requiring
            # ``not budgetExhausted`` makes a post-budget TOOL_CALLS fall
            # through to ``else: break``, bounding the loop to a single extra
            # round regardless of provider behaviour.
            if ret.status == ModelResultStatus.TOOL_CALLS and not budgetExhausted:
                if callback:
                    await callback(ret, extraData)

                if ret.isFallback:
                    # If fallback happened, use fallback model for the rest iterations
                    model = fallbackModel

                toolsUsed = True
                newMessages = [ret.toModelMessage()]

                for toolCall in ret.toolCalls:
                    toolRet: Union[str, Dict[str, Any]] = ""
                    if toolCall.errorMessage is not None:
                        # Synthesised from a broken-but-recognised tool call
                        # (_matchTextForBrokenKnownToolCall): do NOT execute the
                        # handler; tell the model to retry with a proper tool call.
                        toolRet = {"done": False, "error": toolCall.errorMessage}
                    elif toolCall.name in filteredToolNames:
                        toolRet = await self.toolsHandlers[toolCall.name].call(extraData, **toolCall.parameters)
                    else:
                        # If wrong tool called, return error about it.
                        # Report only the actually-available (filtered) names so the LLM
                        # doesn't get told a disabled tool is available and retry it.
                        toolRet = {
                            "done": False,
                            "error": f"Tool {toolCall.name} not available, available tools are "
                            + str(sorted(filteredToolNames)),
                        }

                    # Content of ModelMessage should be string, so if tool result is not string,
                    # convert it to string via utils.jsonDumps()
                    if not isinstance(toolRet, str):
                        toolRet = utils.jsonDumps(toolRet)

                    newMessages.append(
                        ModelMessage(
                            role="tool",
                            content=toolRet,
                            toolCallId=toolCall.id,
                        )
                    )

                if not isinstance(_messages, MutableSequence):
                    # If somehow _messages is not mutable, make it list (i.e. mutable)
                    _messages = list(_messages)
                toolsHistory.extend(newMessages)
                _messages.extend(newMessages)
                _keepLastN = keepLastN + len(newMessages)
                logger.debug(f"Tools used: {newMessages} for callId #{callId}")
            else:
                # Loop terminates here for any non-(pre-budget TOOL_CALLS)
                # status. When the round budget is exhausted the cap was hit:
                # surface a programmatic signal (roundLimitHit) and log a
                # service-level warning so the cap-hit is visible to operators
                # for ALL callers, not just the memory-refinement loop.
                if budgetExhausted:
                    ret.roundLimitHit = True
                    logger.warning(
                        f"generateTextViaLLM hit maxRounds cap ({maxRounds}) for callId #{callId}; forcing termination"
                    )
                    # Synthesize a fallback ONLY when the model produced no
                    # usable text AND the status is one where handing the
                    # caller a fallback answer is appropriate: an empty FINAL
                    # (model returned nothing useful) or a post-budget
                    # TOOL_CALLS (a glitching model that ignored the empty
                    # tools=[] and has no other useful answer). Genuine error
                    # statuses (ERROR / CONTENT_FILTER / UNKNOWN / others) are
                    # left untouched so the original status + empty text
                    # propagate and callers can detect the failure.
                    if not ret.resultText and ret.status in (ModelResultStatus.FINAL, ModelResultStatus.TOOL_CALLS):
                        ret.resultText = (
                            "I've reached the limit of tool-use steps for this"
                            " request; here is my best answer with the information"
                            " gathered so far."
                        )
                        ret.status = ModelResultStatus.FINAL
                        # The synthesized FINAL must not carry stale unexecuted
                        # tool calls (e.g. a native TOOL_CALLS the model
                        # returned despite the empty tools=[]); a FINAL result
                        # is text-only.
                        ret.toolCalls = []
                break

        if toolsUsed:
            ret.setToolsUsed(True)
            ret.toolUsageHistory = toolsHistory

        return ret

    async def condenseContext(
        self,
        messages: Sequence[ModelMessage],
        model: AbstractModel,
        *,
        keepFirstN: int = 0,
        keepLastN: int = 1,
        condensingModel: Optional[AbstractModel] = None,
        condensingPrompt: Optional[str] = None,
        condensingSystemPrompt: Optional[str] = None,
        maxTokens: Optional[int] = None,
        force: bool = False,
    ) -> Tuple[Sequence[ModelMessage], Dict[int, CondensingDict]]:
        """Condense a sequence of messages to fit within a token limit.

        This method reduces the length of a conversation history by either:
        - Using a condensing model to summarize parts of the conversation
        - Simply truncating messages from the middle of the conversation

        The method preserves the first N messages and the last N messages,
        condensing or removing only the middle portion of the conversation.

        Args:
            messages: The sequence of messages to condense
            model: The model used for token counting and as fallback if no condensingModel provided
            keepFirstN: Number of messages to keep from the beginning (in addition to system message)
            keepLastN: Number of messages to keep from the end
            condensingModel: Optional model to use for summarizing messages
            condensingPrompt: Optional custom prompt for the condensing model
            condensingSystemPrompt: Optional system prompt defining the condensing model's identity.
                When provided, replaces the chat personality system prompt during condensing.
            maxTokens: Maximum number of tokens allowed in the condensed result
            force: Whether to force condensing even if the result would fit within the token limit

        Returns:
            A ``(messages, coverage)`` tuple. The first element is the
            condensed message list (head + summary ModelMessages + tail).
            The second element is a ``Dict[int, CondensingDict]`` keyed by
            body-index → fully-populated ``CondensingDict`` (the summary
            text plus coverage metadata computed via
            :func:`generateCondensingDict` reading
            ``ModelMessage.source``). When no condensing occurs the first
            element is the original message sequence unchanged and the
            second element is ``{}``. Path C callers (``generateTextViaLLM``)
            ignore the second element.
        """
        coverage: Dict[int, CondensingDict] = {}
        if not messages:
            return (messages, coverage)

        if maxTokens is None:
            maxTokens = model.contextSize

        # If first message is system prompt, we need to keep it
        systemPrompt: Optional[ModelMessage] = None
        if messages[0].role == "system":
            keepFirstN += 1
            systemPrompt = messages[0]

        # We can't use messages[:keepFirstN] here as messages not always list,
        # but sometimes other sequences, which does not support slice as index.
        # So we have to make slice manualy
        messagesCount = len(messages)

        retHead = [messages[i] for i in range(0, keepFirstN)]
        retTail = [messages[i] for i in range(messagesCount - keepLastN, messagesCount)]
        body = [messages[i] for i in range(keepFirstN, messagesCount - keepLastN)]

        retHTokens = model.getEstimateTokensCount([v.toDict() for v in retHead])
        retTTokens = model.getEstimateTokensCount([v.toDict() for v in retTail])
        bodyTokens = model.getEstimateTokensCount([v.toDict() for v in body])

        if not force and (retHTokens + retTTokens + bodyTokens < maxTokens):
            return (messages, coverage)

        logger.debug(
            f"Condensing context for {messages} to {maxTokens} tokens "
            f"(current: {retHTokens} + {bodyTokens} + {retTTokens} = "
            f"{retHTokens + bodyTokens + retTTokens})"
        )

        if condensingModel is None:
            # No condensing model provided, just truncate beginning of body
            # TODO: should we truncate from middle instead?
            while body and retHTokens + retTTokens + bodyTokens > maxTokens:
                body = body[1:]
                bodyTokens = model.getEstimateTokensCount([v.toDict() for v in body])

            ret = []
            ret.extend(retHead)
            ret.extend(body)
            ret.extend(retTail)

            logger.debug(f"Condensed context: {ret}")
            return (ret, coverage)

        if condensingPrompt is None:
            condensingPrompt = (
                "Your task is to create a detailed summary of the conversation so far."
                " Output only the summary of the conversation so far, without any"
                " additional commentary or explanation."
                " Answer using language of conversation, not language of this message."
            )
        newBody: List[ModelMessage] = []
        summaryMaxTokens = condensingModel.contextSize
        logger.debug(f"Condensing model: {condensingModel}, prompt: {condensingPrompt}")

        # Prefer the dedicated condensing system prompt over the chat persona.
        if condensingSystemPrompt is not None:
            systemMessage = ModelMessage(role="system", content=condensingSystemPrompt)
        elif systemPrompt is not None:
            systemMessage = systemPrompt
        else:
            systemMessage = ModelMessage(
                role="system",
                content=(
                    "You condense conversation history for another LLM context."
                    " Preserve maximum facts: topics, numbers, dates, names,"
                    " decisions, attribution, open questions."
                    " Write in the language of the conversation."
                ),
            )
        condensingMessage = ModelMessage(role="user", content=condensingPrompt)

        # -256 or *0.85 to ensure everything will be ok
        tokensCount = condensingModel.getEstimateTokensCount([v.toDict() for v in body])
        batchesCount = tokensCount // max(summaryMaxTokens - 256, summaryMaxTokens * 0.85) + 1
        batchLength = len(body) // batchesCount
        # Floor at 1: when batchesCount > len(body) (a few token-heavy messages
        # against a small condensing context) the division rounds to 0, which
        # yields an empty batch, a zero-advance startPos, and an infinite loop.
        if batchLength < 1:
            batchLength = 1

        startPos = 0
        currentBatchLen = int(min(batchLength, len(body) - startPos))
        while startPos < len(body):
            currentBatchLen = int(min(currentBatchLen, len(body) - startPos))

            tryMessages = body[startPos : startPos + currentBatchLen]
            reqMessages = [systemMessage]
            reqMessages.extend(tryMessages)
            reqMessages.append(condensingMessage)
            tokensCount = condensingModel.getEstimateTokensCount([v.toDict() for v in reqMessages])
            if tokensCount > summaryMaxTokens:
                if currentBatchLen == 1:
                    logger.error(f"Error while running LLM for message {body[startPos]}")
                    startPos += 1
                    continue
                currentBatchLen = int(currentBatchLen // (tokensCount / summaryMaxTokens))
                currentBatchLen -= 2
                if currentBatchLen < 1:
                    currentBatchLen = 1
                continue

            mlRet: Optional[ModelRunResult] = None
            try:
                logger.debug(f"LLM Request messages: {reqMessages}")
                mlRet = await condensingModel.generateText(reqMessages)
                logger.debug(f"LLM Response: {mlRet}")
            except Exception as e:
                logger.error(
                    f"Error while running LLM for batch {startPos}:{startPos + currentBatchLen}: "
                    f"{type(e).__name__}#{e}"
                )
                startPos += currentBatchLen
                continue

            respText = mlRet.resultText
            resDict = generateCondensingDict(text=respText, messages=tryMessages)
            newBody.append(ModelMessage(role="user", content=renderCondensedSummary(resDict), source=resDict))
            coverage[len(newBody) - 1] = resDict
            startPos += currentBatchLen
            currentBatchLen = int(min(batchLength, len(body) - startPos))

        ret = []
        ret.extend(retHead)
        ret.extend(newBody)
        ret.extend(retTail)
        logger.debug(f"Condensed context: {ret}")
        return (ret, coverage)

    async def generateText(
        self,
        prompt: Sequence[ModelMessage],
        *,
        chatId: Optional[int],
        chatSettings: ChatSettingsDict,
        modelKey: Union[ChatSettingsKey, AbstractModel, None],
        fallbackKey: Union[ChatSettingsKey, AbstractModel, None],
        tools: Optional[Sequence[LLMAbstractTool]] = None,
        doDebugLogging: bool = True,
    ) -> ModelRunResult:
        """Generate text via the configured chat model with fallback support.

        Resolves the primary and fallback models from chatSettings, applies rate limiting,
        then delegates to AbstractModel.generateText with fallbackModels parameter and
        optional tool support.

        Args:
            prompt: Sequence of ModelMessage objects representing the conversation history
            chatId: The Telegram/Max chat identifier used for rate-limiting. Pass None
                to skip rate-limiting (e.g. internal/background calls)
            chatSettings: Chat-level settings dict used to resolve models and the rate
                limiter name
            modelKey: Primary model selector - an AbstractModel instance, a
                ChatSettingsKey pointing to a chat setting that resolves to a model, or
                None to fall back to ChatSettingsKey.CHAT_MODEL
            fallbackKey: Fallback model selector - same semantics as modelKey, defaults
                to ChatSettingsKey.FALLBACK_MODEL when None
            tools: Optional sequence of tools that the LLM can call during generation
            doDebugLogging: When True, emit DEBUG log entries before and after the
                model call. Set to False for tight loops to reduce log noise

        Returns:
            ModelRunResult containing the generated text response, status, and any tool
            calls made during generation
        """
        llmModel = self.resolveModel(modelKey, chatSettings=chatSettings, defaultKey=ChatSettingsKey.CHAT_MODEL)
        fallbackModel = self.resolveModel(
            fallbackKey, chatSettings=chatSettings, defaultKey=ChatSettingsKey.FALLBACK_MODEL
        )

        if chatId is not None:
            await self.rateLimit(chatId, chatSettings)
        if doDebugLogging:
            logger.debug(
                f"Generating Text for chat#{chatId}, LLMs: {llmModel}, {fallbackModel}, "
                f"tools: {len(tools) if tools is not None else False}"
            )
            messageHistoryStr = ""
            for msg in prompt:
                messageHistoryStr += f"\t{msg.toLogMessage()}\n"
            logger.debug(f"LLM Request messages: List[\n{messageHistoryStr}]")

        ret = await llmModel.generateText(
            prompt,
            tools=tools,
            fallbackModels=[fallbackModel],
            consumerId=str(chatId) if chatId is not None else None,
        )

        if doDebugLogging:
            logger.debug(f"LLM returned: {ret}")
        return ret

    async def generateStructured(
        self,
        prompt: Sequence[ModelMessage],
        schema: Dict[str, Any],
        *,
        chatId: Optional[int],
        chatSettings: ChatSettingsDict,
        modelKey: Union[ChatSettingsKey, AbstractModel, None],
        fallbackKey: Union[ChatSettingsKey, AbstractModel, None],
        schemaName: str = "response",
        strict: bool = True,
        doDebugLogging: bool = True,
    ) -> ModelStructuredResult:
        """Generate structured (JSON) output via the configured chat model.

        Resolves the primary and fallback models from chatSettings, applies rate limiting,
        then delegates to AbstractModel.generateStructured with fallbackModels parameter
        and fallback support. Raises if neither resolved model supports structured output.

        NOTE: callers should include a system message hinting at JSON output; this wrapper
        will not inject one.

        If the primary model lacks support_structured_output but the fallback does, the
        models are swapped before the call so that we do not waste a round-trip on a
        guaranteed NotImplementedError.

        Args:
            prompt: Sequence of ModelMessage objects representing the conversation history
            schema: A JSON Schema dict describing the expected response shape
            chatId: The Telegram/Max chat identifier used for rate-limiting. Pass None
                to skip rate-limiting (e.g. internal/background calls)
            chatSettings: Chat-level settings dict used to resolve models and the rate
                limiter name
            modelKey: Primary model selector - an AbstractModel instance, a
                ChatSettingsKey pointing to a chat setting that resolves to a model, or
                None to fall back to ChatSettingsKey.CHAT_MODEL
            fallbackKey: Fallback model selector - same semantics as modelKey, defaults
                to ChatSettingsKey.FALLBACK_MODEL when None
            schemaName: An identifier for the schema sent alongside it to the provider
                (e.g. OpenAI requires a name field). Defaults to "response"
            strict: When True, ask the provider to enforce the schema strictly (OpenAI
                strict: true). Some providers silently ignore this flag
            doDebugLogging: When True, emit DEBUG log entries before and after the
                model call. Set to False for tight loops to reduce log noise

        Returns:
            ModelStructuredResult with data populated on success, or status=ERROR
            and error set on failure

        Raises:
            NotImplementedError: If neither the resolved primary model nor the fallback
                model has support_structured_output=True. No model call is made in
                this case
        """
        llmModel = self.resolveModel(modelKey, chatSettings=chatSettings, defaultKey=ChatSettingsKey.CHAT_MODEL)
        fallbackModel = self.resolveModel(
            fallbackKey, chatSettings=chatSettings, defaultKey=ChatSettingsKey.FALLBACK_MODEL
        )

        primarySupports: bool = llmModel.getInfo().get("support_structured_output", False)
        fallbackSupports: bool = fallbackModel.getInfo().get("support_structured_output", False)
        if not primarySupports and not fallbackSupports:
            raise NotImplementedError(f"Neither {llmModel} nor {fallbackModel} supports structured output")

        # If primary doesn't support but fallback does, swap so we don't waste a
        # round-trip on a guaranteed NotImplementedError from the primary.
        if not primarySupports and fallbackSupports:
            logger.warning(
                f"Model {llmModel} does not support structured output, "
                f"but fallback {fallbackModel} does, swapping them"
            )
            llmModel, fallbackModel = fallbackModel, llmModel

        if chatId is not None:
            await self.rateLimit(chatId, chatSettings)

        if doDebugLogging:
            logger.debug(
                f"Generating Structured for chat#{chatId}, LLMs: {llmModel}, "
                f"{fallbackModel}, schema_keys={list(schema.keys())}"
            )

        ret: ModelStructuredResult = await llmModel.generateStructured(
            prompt,
            schema,
            schemaName=schemaName,
            strict=strict,
            fallbackModels=[fallbackModel],
            consumerId=str(chatId) if chatId is not None else None,
        )

        if doDebugLogging:
            logger.debug(f"LLM (structured) returned: {ret}")
        return ret

    async def generateImage(
        self,
        prompt: str,
        *,
        chatId: Optional[int],
        chatSettings: ChatSettingsDict,
    ) -> ModelRunResult:
        """Generate image with given prompt and chat settings.

        Generates an image using the configured image generation model with
        fallback support. Applies rate limiting before making the generation
        request.

        Args:
            prompt: The text prompt describing the image to generate
            chatId: The Telegram/Max chat identifier used for rate-limiting
            chatSettings: Chat-level settings dict containing the image generation model
                configuration

        Returns:
            ModelRunResult containing the generated image response and metadata
        """
        imageGenerationModel = self.resolveModel(
            ChatSettingsKey.IMAGE_GENERATION_MODEL,
            chatSettings=chatSettings,
            defaultKey=ChatSettingsKey.IMAGE_GENERATION_MODEL,
        )
        fallbackImageLLM = self.resolveModel(
            ChatSettingsKey.IMAGE_GENERATION_FALLBACK_MODEL,
            chatSettings=chatSettings,
            defaultKey=ChatSettingsKey.IMAGE_GENERATION_FALLBACK_MODEL,
        )

        if chatId is not None:
            await self.rateLimit(chatId, chatSettings)
        return await imageGenerationModel.generateImage(
            [ModelMessage(content=prompt)],
            fallbackModels=[fallbackImageLLM],
            consumerId=str(chatId) if chatId is not None else None,
        )

    async def generateEmbedding(
        self,
        text: str,
        *,
        chatId: Optional[int],
        chatSettings: ChatSettingsDict,
    ) -> Optional[Tuple[str, List[float]]]:
        """Generate an embedding vector for ``text`` using the chat's embedding model.

        Resolves the embedding model from ``EMBEDDING_MODEL`` in chat settings,
        applies the chat's rate limit when ``chatId`` is not ``None``, and asks
        the model to embed the text. The returned model name is read back from
        the resolved chat setting (not the model instance) so callers can
        persist it alongside the vector for later stale-detection. Any failure
        (bad model, rate-limit, provider error) is caught, logged, and surfaced
        as ``None`` so the cron/tool path can skip the row without raising.

        Args:
            text: The text to embed.
            chatId: Chat identifier used for rate limiting; pass ``None`` to
                skip rate limiting (e.g. for a background regen tick).
            chatSettings: Chat-level settings dict — must contain a resolved
                ``EMBEDDING_MODEL`` value.

        Returns:
            A ``(modelName, embeddingVector)`` tuple on success, or ``None``
            when embedding failed (the exception is logged).
        """

        try:
            embeddingModel = self.resolveModel(
                ChatSettingsKey.EMBEDDING_MODEL, chatSettings=chatSettings, defaultKey=ChatSettingsKey.EMBEDDING_MODEL
            )

            if chatId is not None:
                await self.rateLimit(chatId, chatSettings)
            embeddingVector = await embeddingModel.generateEmbeddings(text)
            return (chatSettings[ChatSettingsKey.EMBEDDING_MODEL].toStr(), embeddingVector)
        except Exception:
            logger.exception("Failed to generate embeddings:")
            return None

    async def rateLimit(self, chatId: int, chatSettings: ChatSettingsDict) -> None:
        """Apply rate limiting to a chat based on its settings.

        Retrieves the rate limiter name from chat settings and applies the
        rate limit using the configured rate limiter manager for the specific
        chat identifier.

        Args:
            chatId: The Telegram/Max chat identifier to rate limit
            chatSettings: Chat-level settings dict containing the rate limiter configuration

        Returns:
            None
        """
        rateLimiterName = chatSettings[ChatSettingsKey.LLM_RATELIMITER].toStr()
        await self.rateLimiterManager.applyLimit(rateLimiterName, self.getRateLimiterKey(chatId))

    def getRateLimiterKey(self, chatId: int) -> str:
        """Generate a rate limiter key for a given chat ID.

        Creates a unique key string used by the rate limiter manager to track
        rate limits per chat. The key format is "chatLLM#<chatId>".

        Args:
            chatId: The Telegram/Max chat identifier

        Returns:
            A unique rate limiter key string
        """
        return f"chatLLM#{chatId}"

    def getLLMManager(self) -> LLMManager:
        """Return the LLMManager instance.

        Returns:
            The LLMManager instance used by the LLMService
        """
        if self.llmManager is None:
            raise RuntimeError("LLMManager not initialized, call llmService.getInstance().injectLLMManager(...)")
        return self.llmManager

    def resolveModel(
        self,
        modelKey: Optional[Union[AbstractModel, ChatSettingsKey]],
        *,
        chatSettings: ChatSettingsDict,
        defaultKey: ChatSettingsKey,
    ) -> AbstractModel:
        """Resolve a model key to an actual AbstractModel instance.

        This method provides flexible model resolution, accepting either:
        - An AbstractModel instance (returned directly)
        - A ChatSettingsKey (resolved to a model via chatSettings)
        - None (resolved to the defaultKey model via chatSettings)

        Args:
            modelKey: The model to resolve - an AbstractModel instance, a ChatSettingsKey,
                or None to fall back to defaultKey
            chatSettings: Chat-level settings dict used to resolve model keys to instances
            defaultKey: The fallback ChatSettingsKey to use if modelKey is None

        Returns:
            The resolved AbstractModel instance
        """
        if isinstance(modelKey, AbstractModel):
            return modelKey

        if isinstance(modelKey, ChatSettingsKey):
            return chatSettings[modelKey].toModel()

        return chatSettings[defaultKey].toModel()
