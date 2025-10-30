"""
AI module for Gromozeka bot - LLM management system, dood!
"""

from .abstract import AbstractLLMProvider, AbstractModel
from .manager import LLMManager
from .models import (
    LLMAbstractTool,
    LLMParameterType,
    LLMFunctionParameter,
    LLMToolFunction,
    LLMToolCall,
    ModelMessage,
    ModelImageMessage,
    ModelResultStatus,
    ModelRunResult,
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
]
