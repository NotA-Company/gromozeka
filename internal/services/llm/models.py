"""Data models for the LLM service.

This module defines type-safe data structures used by the LLM service to pass
additional context between the service and its callers. The primary structure
is a TypedDict that provides optional extra data fields for tool handlers and
callbacks during LLM interactions.
"""

from typing import Any, TypedDict


class ExtraDataDict(TypedDict, total=False):
    """Optional extra data dictionary for LLM service callbacks and tool handlers.

    This TypedDict defines optional fields that can be passed as `extraData`
    to `LLMService.generateText()` and are forwarded to tool callbacks.
    The dictionary is marked `total=False`, meaning all fields are optional.

    Attributes:
        ensuredMessage: Wrapped message object containing sender, recipient,
            and message metadata. Used by tool handlers that need to send
            responses or access chat context. Type is `Any` because the actual
            type is `EnsuredMessage` from `internal.bot.models.ensured_message`.
        typingManager: Manager for typing indicators, allowing tool handlers
            to show typing status during long operations. Type is `Any` because
            the actual type is `TypingManager` from `internal.bot.common.typing_manager`.
    """

    ensuredMessage: Any
    """EnsuredMessage"""
    typingManager: Any
    """Optional[TypingManager]"""
