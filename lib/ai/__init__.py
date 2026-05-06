"""
AI module for Gromozeka bot - LLM management system.

This module provides a comprehensive interface for managing Large Language Model (LLM)
interactions within the Gromozeka bot. It supports multiple LLM providers, tool/function
calling capabilities, and handles both text and image messages.

Features:
    - Multiple LLM provider support (OpenAI-compatible, Yandex Cloud, OpenRouter)
    - Abstract base classes for easy provider extension
    - Tool/function calling with structured parameters
    - Image and text message handling
    - Result status tracking and error handling
    - Extensible model architecture

Example:
    >>> from lib.ai import LLMManager, ModelMessage, ModelImageMessage
    >>>
    >>> # Initialize the manager
    >>> manager = LLMManager()
    >>>
    >>> # Create messages
    >>> messages = [
    ...     ModelMessage(role="user", content="Hello, how are you?")
    ... ]
    >>>
    >>> # Run the model
    >>> result = manager.runModel(
    ...     providerName="openai",
    ...     modelName="gpt-4",
    ...     messages=messages
    ... )
    >>>
    >>> # Check result
    >>> if result.status == ModelResultStatus.SUCCESS:
    ...     print(result.content)

Exports:
    AbstractModel: Abstract base class for LLM model implementations
    AbstractLLMProvider: Abstract base class for LLM provider implementations
    LLMAbstractTool: Abstract base class for tool/function definitions
    LLMManager: Main manager class for LLM operations
    LLMParameterType: Enum for parameter types (string, number, boolean, array, object)
    LLMFunctionParameter: Model for function parameter definitions
    LLMToolFunction: Model for tool/function definitions
    LLMToolCall: Model for tool/function call results
    ModelMessage: Model for text messages
    ModelImageMessage: Model for image messages
    ModelResultStatus: Enum for result status (success, error, timeout)
    ModelRunResult: Model for model run results
"""

from .abstract import AbstractLLMProvider, AbstractModel
from .manager import LLMManager
from .models import (
    LLMAbstractTool,
    LLMFunctionParameter,
    LLMParameterType,
    LLMToolCall,
    LLMToolFunction,
    ModelImageMessage,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
    ModelStructuredResult,
)

__all__ = [
    # Abstract classes
    "AbstractModel",
    "AbstractLLMProvider",
    "LLMAbstractTool",
    # Manager
    "LLMManager",
    # Models and enums
    "LLMParameterType",
    "LLMFunctionParameter",
    "LLMToolFunction",
    "LLMToolCall",
    "ModelMessage",
    "ModelImageMessage",
    "ModelResultStatus",
    "ModelRunResult",
    "ModelStructuredResult",
]
