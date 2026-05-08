"""LLM Service module for managing language model interactions and tool execution.

Provides a singleton service for interacting with Large Language Models (LLMs),
managing tool registration and execution, and handling multi-turn conversations
with tool calls. Supports fallback models and provides a unified interface for
LLM operations.
"""

from .models import ExtraDataDict
from .service import LLMService, LLMToolHandler

__all__ = ["LLMService", "LLMToolHandler", "ExtraDataDict"]
