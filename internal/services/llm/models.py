"""Data models for the LLM service.

This module defines type-safe data structures used by the LLM service to pass
additional context between the service and its callers. The primary structure
is a TypedDict that provides optional extra data fields for tool handlers and
callbacks during LLM interactions.
"""

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from typing import Optional

    from internal.bot.common.typing_manager import TypingManager
    from internal.bot.models.ensured_message import EnsuredMessage


class ExtraDataDict(TypedDict, total=False):
    """Optional extra data dictionary for LLM service callbacks and tool handlers.

    This TypedDict defines optional fields that can be passed as `extraData`
    to `LLMService.generateText()` and are forwarded to tool callbacks.
    The dictionary is marked `total=False`, meaning all fields are optional.

    Attributes:
        ensuredMessage: Wrapped message object containing sender, recipient,
            and message metadata. Used by tool handlers that need to send
            responses or access chat context.
        typingManager: Manager for typing indicators, allowing tool handlers
            to show typing status during long operations, or None.
        isRefinement: When True, signals that the call originates from the
            background memory-refinement pass (not a live chat turn). Read by
            ``_llmToolAddMemory`` to decide whether the grey-zone dedup
            threshold returns ``similar_exists`` (refinement) or folds to
            ``duplicate`` (chat-time). See docs/archive/plans/user-memories-v1.md §8.3/D5.
    """

    ensuredMessage: "EnsuredMessage"
    """EnsuredMessage message object from the bot."""
    typingManager: "Optional[TypingManager]"
    """Typing indicator manager, or None."""
    isRefinement: bool
    """True when the call is the background memory-refinement pass (not a chat turn)."""
