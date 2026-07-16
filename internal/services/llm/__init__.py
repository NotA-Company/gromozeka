"""LLM Service module for managing language model interactions and tool execution.

Provides a singleton service for interacting with Large Language Models (LLMs),
managing tool registration and execution, and handling multi-turn conversations
with tool calls. Supports fallback models and provides a unified interface for
LLM operations.
"""

from .constants import DEFAULT_MAX_ROUNDS, TOOLS_DEFAULT_DICT_KEY
from .models import ExtraDataDict
from .service import LLMService, LLMToolHandler, UseToolsType

__all__ = [
    "LLMService",
    "LLMToolHandler",
    "UseToolsType",
    "ExtraDataDict",
    "DEFAULT_MAX_ROUNDS",
    "TOOLS_DEFAULT_DICT_KEY",
]
