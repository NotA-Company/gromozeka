"""LLM Service module for managing language model interactions and tool execution, dood!

This module provides a singleton service for interacting with Large Language Models (LLMs),
managing tool registration and execution, and handling multi-turn conversations with tool calls.
The service supports fallback models and provides a unified interface for LLM operations.
"""

import logging
from threading import RLock
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, TypeAlias
import uuid

from lib import utils
from lib.ai.abstract import AbstractModel
from lib.ai.models import LLMToolFunction, LLMFunctionParameter, ModelMessage, ModelResultStatus, ModelRunResult


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

            self.initialized = True
            logger.info("LLMService initialized, dood!")

    @classmethod
    def getInstance(cls) -> "LLMService":
        """Get the singleton instance of LLMService, dood!
        
        Returns:
            The singleton LLMService instance
        """
        return cls()

    def registerTool(self, name: str, description: str, parameters: Sequence[LLMFunctionParameter], handler: LLMToolHandler) -> None:
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

    async def generateTextViaLLM(
        self,
        model: AbstractModel,
        fallbackModel: AbstractModel,
        messages: List[ModelMessage],
        useTools: bool = False,
        callId: Optional[str] = None,
        callback: Optional[Callable[[ModelRunResult, Optional[Dict[str, Any]]], Awaitable[None]]] = None,
        extraData: Optional[Dict[str, Any]] = None,
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

        ret: Optional[ModelRunResult] = None
        toolsUsed = False
        tools: Sequence[LLMToolFunction] = list(self.toolsHandlers.values()) if useTools else []
        while True:
            ret = await model.generateTextWithFallBack(
                messages, fallbackModel=fallbackModel, tools=tools,
            )
            logger.debug(f"LLM returned: {ret} for callId #{callId}")
            if ret.status == ModelResultStatus.TOOL_CALLS:
                if callback:
                    await callback(ret, extraData)

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
                messages = messages + newMessages
                logger.debug(f"Tools used: {newMessages} for callId #{callId}")
            else:
                break

        if toolsUsed:
            ret.setToolsUsed(True)

        return ret

