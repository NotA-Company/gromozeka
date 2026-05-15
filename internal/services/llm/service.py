"""LLM Service module for managing language model interactions and tool execution.

This module provides a singleton service for interacting with Large Language Models (LLMs),
managing tool registration and execution, and handling multi-turn conversations with tool calls.
The service supports fallback models and provides a unified interface for LLM operations.
"""

import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, MutableSequence, Sequence
from threading import RLock
from typing import Any, Dict, List, Optional, TypeAlias, Union

from internal.bot.models.chat_settings import ChatSettingsDict, ChatSettingsKey
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

from .models import ExtraDataDict

logger = logging.getLogger(__name__)


LLMToolHandler: TypeAlias = Callable[..., Awaitable[str]]
"""Type alias for async tool handler functions.

Handlers are async callables that take tool parameters and extra data,
and return a string result. The function signature is flexible: parameters
are passed as keyword arguments matching the tool's schema.

Example:
    LLMToolHandler my_tool = lambda param1, param2, **kwargs: "result"

Attributes:
    ExtraDataDict: Optional dictionary of extra data passed from the calling context
"""


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

    def _tryApplyToolCallMatch(
        self,
        mlRunResult: ModelRunResult,
        *,
        toolName: str,
        parameters: Optional[Dict[Any, Any]],
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
                jsonData, endPos = json.JSONDecoder().raw_decode(jsonStr)
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
            r"^(.*?)(?:\[TOOL_CALL_START\]\s*)(\S+?)({.*})\s*(.*?)\s*$",
            resultText,
            re.DOTALL,
        )
        if match is not None:
            try:
                logger.debug(f"TOOL_CALL_START found: {match.groups()}")
                toolArgsStr = match.group(3)
                toolArgs, endPos = json.JSONDecoder().raw_decode(toolArgsStr)
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
                toolArgs, endPos = json.JSONDecoder().raw_decode(toolArgsStr)
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

    async def generateTextViaLLM(
        self,
        messages: Sequence[ModelMessage],
        *,
        chatId: Optional[int],
        chatSettings: ChatSettingsDict,
        modelKey: Optional[Union[AbstractModel, ChatSettingsKey]],
        fallbackModelKey: Optional[Union[AbstractModel, ChatSettingsKey]],
        useTools: bool = False,
        callId: Optional[str] = None,
        callback: Optional[Callable[[ModelRunResult, ExtraDataDict], Awaitable[None]]] = None,
        extraData: ExtraDataDict,
        keepFirstN: int = 0,
        keepLastN: int = 1,
        maxTokensCoeff: float = 0.8,
        condensingPromptKey: Optional[Union[str, ChatSettingsKey]] = None,
        condensingSystemPromptKey: Optional[Union[str, ChatSettingsKey]] = None,
        condensingModelKey: Optional[Union[AbstractModel, ChatSettingsKey]] = None,
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
            useTools: Whether to enable tool calling functionality
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

        Returns:
            ModelRunResult containing the final LLM response, with toolsUsed flag set
            if any tools were executed during the conversation
        """
        if callId is None:
            callId = str(uuid.uuid4())

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
        tools: Sequence[LLMToolFunction] = list(self.toolsHandlers.values()) if useTools else []
        _keepLastN = keepLastN

        _messages: Sequence[ModelMessage] = messages
        toolsHistory: MutableSequence[ModelMessage] = []

        while True:
            # First - condense context if needed
            maxTokens = int(model.contextSize * maxTokensCoeff)
            _messages = await self.condenseContext(
                _messages,
                model,
                keepFirstN=keepFirstN,
                keepLastN=_keepLastN,
                maxTokens=maxTokens,
                condensingModel=condensingModel,
                condensingPrompt=condensingPrompt,
                condensingSystemPrompt=condensingSystemPrompt,
            )

            ret = await self.generateText(
                _messages,
                chatId=chatId,
                chatSettings=chatSettings,
                modelKey=model,
                fallbackKey=fallbackModel,
                tools=tools,
                doDebugLogging=False,
            )
            logger.debug(f"LLM returned: {ret} for callId #{callId}")
            if ret.status == ModelResultStatus.FINAL and ret.resultText:
                # First - check if it was really tool call
                hasMatch = self._matchTextForJSONToolCall(ret)

                if not hasMatch:
                    hasMatch = self._matchTextForToolCallStart(ret)
                if not hasMatch:
                    hasMatch = self._matchTextForToolCallSquareBracketsAndJson(ret)

                # TODO: In other cases do some conversion as well

            if ret.status == ModelResultStatus.TOOL_CALLS:
                if callback:
                    await callback(ret, extraData)

                if ret.isFallback:
                    # If fallback happened, use fallback model for the rest iterations
                    model = fallbackModel

                toolsUsed = True
                newMessages = [ret.toModelMessage()]

                for toolCall in ret.toolCalls:
                    toolRet = ""
                    # Check if tool is available
                    if toolCall.name in self.toolsHandlers:
                        toolRet = await self.toolsHandlers[toolCall.name].call(extraData, **toolCall.parameters)
                    else:
                        # If wrong tool called, return error about it
                        toolRet = {
                            "done": False,
                            "error": f"Tool {toolCall.name} not found, available tools are "
                            + str(list(self.toolsHandlers.keys())),
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
    ) -> Sequence[ModelMessage]:
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
            A new sequence of messages condensed to fit within the token limit
        """
        if not messages:
            return messages

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
            return messages

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
            return ret

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

        startPos = 0
        while startPos < len(body):
            currentBatchLen = int(min(batchLength, len(body) - startPos))

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
            newBody.append(ModelMessage(role="user", content=respText))
            startPos += currentBatchLen

        ret = []
        ret.extend(retHead)
        ret.extend(newBody)
        ret.extend(retTail)
        logger.debug(f"Condensed context: {ret}")
        return ret

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
