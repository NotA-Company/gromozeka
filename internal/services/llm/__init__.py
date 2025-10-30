"""LLM Service module for managing language model interactions and tool execution, dood!

This module provides a singleton service for interacting with Large Language Models (LLMs),
managing tool registration and execution, and handling multi-turn conversations with tool calls.
The service supports fallback models and provides a unified interface for LLM operations.
"""

from .service import LLMService, LLMToolHandler

__all__ = ["LLMService", "LLMToolHandler"]
