"""LLM Service module for managing language model interactions and tool execution, dood!

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
)
from lib.rate_limiter.manager import RateLimiterManager

logger = logging.getLogger(__name__)


LLMToolHandler: TypeAlias = Callable[..., Awaitable[str]]


class LLMService:
    """Singleton service for managing LLM interactions and tool execution, dood!

    This service provides a centralized interface for:
    - Registering and managing LLM tools (functions that the LLM can call)
    - Generating text responses using LLMs with automatic tool execution
    - Handling multi-turn conversations with tool calls
    - Supporting fallback models for reliability

    The service implements the singleton pattern with thread-safe initialization
    to ensure only one instance exists throughout the application lifecycle.

    Attributes:
        toolsHandlers: Dictionary mapping tool names to their LLMToolFunction definitions
        initialized: Flag indicating whether the instance has been initialized
    """

    _instance: Optional["LLMService"] = None
    _lock = RLock()

    def __new__(cls) -> "LLMService":
        """
        Create or return singleton instance with thread safety.

        Returns:
            The singleton LLMService instance
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        """Initialize the LLMService instance with default values, dood!

        Sets up the tools handlers dictionary and marks the instance as initialized.
        This method uses a guard to prevent re-initialization of the singleton instance.
        Only runs initialization logic once per singleton lifecycle.
        """
        if not hasattr(self, "initialized"):
            self.toolsHandlers: Dict[str, LLMToolFunction] = {}
            self.rateLimiterManager = RateLimiterManager()

            self.initialized = True
            logger.info("LLMService initialized, dood!")

    @classmethod
    def getInstance(cls) -> "LLMService":
        """Get the singleton instance of LLMService, dood!

        Returns:
            The singleton LLMService instance
        """
        return cls()

    def registerTool(
        self, name: str, description: str, parameters: Sequence[LLMFunctionParameter], handler: LLMToolHandler
    ) -> None:
        """
        Register a new tool for the LLM service, dood.

        Args:
            name: The name of the tool
            description: The description of the tool
            parameters: The parameters of the tool
            handler: The handler function for the tool
        """
        self.toolsHandlers[name] = LLMToolFunction(
            name=name,
            description=description,
            parameters=parameters,
            function=handler,
        )
        logger.info(f"Tool {name} registered, dood!")

    async def generateTextViaLLM(
        self,
        messages: Sequence[ModelMessage],
        *,
        chatId: Optional[int],
        chatSettings: ChatSettingsDict,
        llmManager: LLMManager,
        modelKey: Optional[Union[AbstractModel, ChatSettingsKey]],
        fallbackModelKey: Optional[Union[AbstractModel, ChatSettingsKey]],
        useTools: bool = False,
        callId: Optional[str] = None,
        callback: Optional[Callable[[ModelRunResult, Optional[Dict[str, Any]]], Awaitable[None]]] = None,
        extraData: Optional[Dict[str, Any]] = None,
        keepFirstN: int = 0,
        keepLastN: int = 1,
        maxTokensCoeff: float = 0.8,
        condensingPromptKey: Optional[Union[str, ChatSettingsKey]] = None,
        condensingModelKey: Optional[Union[AbstractModel, ChatSettingsKey]] = None,
    ) -> ModelRunResult:
        """Generate text using an LLM with automatic tool execution support, dood!

        This method handles the complete LLM interaction flow including:
        - Sending messages to the primary model with fallback support
        - Detecting and executing tool calls requested by the LLM
        - Managing multi-turn conversations when tools are used
        - Invoking callbacks for tool call events

        The method runs in a loop, executing tool calls and feeding results back
        to the LLM until a final text response is generated.

        Args:
            model: The primary LLM model to use for generation
            fallbackModel: The fallback model to use if the primary model fails
            messages: List of conversation messages to send to the LLM
            useTools: Whether to enable tool calling functionality (default: False)
            callId: Optional unique identifier for this LLM call (auto-generated if None)
            callback: Optional async callback invoked when tool calls are made,
                     receives the ModelRunResult and extraData
            extraData: Optional dictionary of extra data passed to tool handlers and callbacks

        Returns:
            ModelRunResult containing the final LLM response, with toolsUsed flag set
            if any tools were executed during the conversation
        """
        if callId is None:
            callId = str(uuid.uuid4())

        model = self.resolveModel(
            modelKey,
            chatSettings=chatSettings,
            llmManager=llmManager,
            defaultKey=ChatSettingsKey.CHAT_MODEL,
        )
        fallbackModel = self.resolveModel(
            fallbackModelKey,
            chatSettings=chatSettings,
            llmManager=llmManager,
            defaultKey=ChatSettingsKey.FALLBACK_MODEL,
        )
        condensingModel = self.resolveModel(
            condensingModelKey,
            chatSettings=chatSettings,
            llmManager=llmManager,
            defaultKey=ChatSettingsKey.CONDENSING_MODEL,
        )
        condensingPrompt = None
        if isinstance(condensingPromptKey, ChatSettingsKey):
            condensingPrompt = chatSettings[condensingPromptKey].toStr()
        elif isinstance(condensingPromptKey, str):
            condensingPrompt = condensingPromptKey
        else:
            condensingPrompt = chatSettings[ChatSettingsKey.CONDENSING_PROMPT].toStr()

        ret: Optional[ModelRunResult] = None
        toolsUsed = False
        tools: Sequence[LLMToolFunction] = list(self.toolsHandlers.values()) if useTools else []
        _keepLastN = keepLastN

        _messages: Sequence[ModelMessage] = messages
        toolsHistory: MutableSequence[ModelMessage] = []

        _condensingModel: Optional[AbstractModel] = None
        while True:
            # First - condense context if needed
            maxTokens = int(model.contextSize * maxTokensCoeff)
            _messages = await self.condenseContext(
                _messages,
                model,
                keepFirstN=keepFirstN,
                keepLastN=_keepLastN,
                maxTokens=maxTokens,
                condensingModel=_condensingModel,
                condensingPrompt=condensingPrompt,
            )
            # First iteration - just strip context, next - properly condense context via LLM
            _condensingModel = condensingModel or model

            ret = await self.generateText(
                _messages,
                chatId=chatId,
                chatSettings=chatSettings,
                llmManager=llmManager,
                modelKey=model,
                fallbackKey=fallbackModel,
                tools=tools,
            )
            logger.debug(f"LLM returned: {ret} for callId #{callId}")
            if ret.status == ModelResultStatus.FINAL and ret.resultText:
                # First - check if it was really tool call
                resultText = ret.resultText.strip()
                match = re.match(r"^(.*?)```(?:json\s*)?\s*({.*?})\s*```(.*)$", resultText, re.DOTALL | re.IGNORECASE)
                if match is not None:
                    logger.debug(f"JSON found: {match.groups()}")
                    prefixStr = match.group(1)
                    suffixStr = match.group(3)
                    try:
                        jsonData = json.loads(match.group(2))
                        logger.debug(f"JSON result: {jsonData}")
                        parameters = None
                        if "arguments" in jsonData:
                            parameters = jsonData.get("arguments", None)
                        elif "parameters" in jsonData:
                            parameters = jsonData.get("parameters", None)
                        # Look fo tool calling only in begin or end of message, so prefix of suffix should be empty
                        if (
                            (not prefixStr or not suffixStr)
                            and "name" in jsonData
                            and isinstance(parameters, dict)
                            and jsonData["name"] in self.toolsHandlers
                        ):
                            # TODO: is "parameters"|"arguments" required?
                            logger.debug("It looks like tool call, converting...")
                            ret.setToolsUsed(True)
                            ret.status = ModelResultStatus.TOOL_CALLS
                            ret.resultText = (prefixStr + suffixStr).strip()
                            toolCallId = jsonData.get("callId", None)
                            if toolCallId is None:
                                toolCallId = str(uuid.uuid4())

                            ret.toolCalls = [LLMToolCall(id=toolCallId, name=jsonData["name"], parameters=parameters)]
                        # TODO: In other cases do some conversion as well
                    except json.JSONDecodeError:
                        pass

            if ret.status == ModelResultStatus.TOOL_CALLS:
                if callback:
                    await callback(ret, extraData)

                if ret.isFallback:
                    # If fallback happened, use fallback model for the rest iterations
                    model = fallbackModel

                toolsUsed = True
                newMessages = [ret.toModelMessage()]

                for toolCall in ret.toolCalls:
                    newMessages.append(
                        ModelMessage(
                            role="tool",
                            content=utils.jsonDumps(
                                await self.toolsHandlers[toolCall.name].call(extraData, **toolCall.parameters),
                            ),
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
        maxTokens: Optional[int] = None,
    ) -> Sequence[ModelMessage]:
        """Condense a sequence of messages to fit within a token limit, dood!

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
            maxTokens: Maximum number of tokens allowed in the condensed result

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

        retHead = messages[:keepFirstN]
        retTail = messages[-keepLastN:]
        body = messages[keepFirstN:-keepLastN]

        retHTokens = model.getEstimateTokensCount([v.toDict() for v in retHead])
        retTTokens = model.getEstimateTokensCount([v.toDict() for v in retTail])
        bodyTokens = model.getEstimateTokensCount([v.toDict() for v in body])

        if retHTokens + retTTokens + bodyTokens < maxTokens:
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

        systemMessage = ModelMessage(role="system", content=condensingPrompt) if systemPrompt is None else systemPrompt
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
            tokensCount = model.getEstimateTokensCount([v.toDict() for v in reqMessages])
            if tokensCount > summaryMaxTokens:
                if currentBatchLen == 1:
                    logger.error(f"Error while running LLM for message {body[startPos]}")
                    startPos += 1
                    continue
                currentBatchLen = int(currentBatchLen // (tokensCount / maxTokens))
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
            # TODO: Should role be "user" or "assistant" or anything else?
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
        prompt: Union[str, Sequence[ModelMessage]],
        *,
        chatId: Optional[int],
        chatSettings: ChatSettingsDict,
        llmManager: LLMManager,
        modelKey: Union[ChatSettingsKey, AbstractModel, None],
        fallbackKey: Union[ChatSettingsKey, AbstractModel, None],
        tools: Optional[Sequence[LLMAbstractTool]] = None,
    ) -> ModelRunResult:
        """Generate text with given prompt and chat settings."""
        if isinstance(prompt, str):
            prompt = [ModelMessage(content=prompt)]
        llmModel = self.resolveModel(
            modelKey, chatSettings=chatSettings, llmManager=llmManager, defaultKey=ChatSettingsKey.CHAT_MODEL
        )
        fallbackModel = self.resolveModel(
            fallbackKey, chatSettings=chatSettings, llmManager=llmManager, defaultKey=ChatSettingsKey.FALLBACK_MODEL
        )

        if chatId is not None:
            await self.rateLimit(chatId, chatSettings)
        return await llmModel.generateTextWithFallBack(prompt, fallbackModel, tools=tools)

    async def generateImage(
        self, prompt: str, chatId: Optional[int], chatSettings: ChatSettingsDict, llmManager: LLMManager
    ) -> ModelRunResult:
        """Generate image with given prompt and chat settings."""
        imageGenerationModel = chatSettings[ChatSettingsKey.IMAGE_GENERATION_MODEL].toModel(llmManager)
        fallbackImageLLM = chatSettings[ChatSettingsKey.IMAGE_GENERATION_FALLBACK_MODEL].toModel(llmManager)

        if chatId is not None:
            await self.rateLimit(chatId, chatSettings)
        return await imageGenerationModel.generateImageWithFallBack([ModelMessage(content=prompt)], fallbackImageLLM)

    async def rateLimit(self, chatId: int, chatSettings: ChatSettingsDict) -> None:
        rateLimiterName = chatSettings[ChatSettingsKey.LLM_RATELIMITER].toStr()
        await self.rateLimiterManager.applyLimit(rateLimiterName, self.getRateLimiterKey(chatId))

    def getRateLimiterKey(self, chatId: int) -> str:
        return f"chatLLM#{chatId}"

    def resolveModel(
        self,
        modelKey: Optional[Union[AbstractModel, ChatSettingsKey]],
        *,
        chatSettings: ChatSettingsDict,
        llmManager: LLMManager,
        defaultKey: ChatSettingsKey,
    ) -> AbstractModel:
        if isinstance(modelKey, AbstractModel):
            return modelKey

        if isinstance(modelKey, ChatSettingsKey):
            return chatSettings[modelKey].toModel(llmManager)

        return chatSettings[defaultKey].toModel(llmManager)
