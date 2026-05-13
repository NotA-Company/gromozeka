"""Bot models module.

This module exports all bot-related models, types, and enums used throughout
the Gromozeka bot system. It serves as a central import point for bot
components, providing access to:

- Command handlers and their metadata
- Chat settings and configuration types
- Message handling models (EnsuredMessage, MessageSender, etc.)
- Bot-specific enums (BotProvider, Button actions, etc.)
- Media processing types
- User metadata structures
- Text formatting utilities

All exported items are re-exported from their respective submodules to avoid
circular dependencies and provide a clean import interface.
"""

# Re-export MessageType from shared_enums to avoid circular dependency
from ...models import MessageType

# Chat Settings (already exists)
from .chat_settings import (
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsPage,
    ChatSettingsType,
    ChatSettingsValue,
    ChatTier,
    getChatSettingsInfo,
)

# Command Handlers
from .command_handlers import (
    CommandCategory,
    CommandHandlerInfoV2,
    CommandHandlerMixin,
    CommandHandlerOrder,
    CommandPermission,
    commandHandlerV2,
)

# Ensured Message (already exists)
from .ensured_message import ChatType, EnsuredMessage, MentionCheckResult, MessageRecipient, MessageSender

# Enums
from .enums import (
    BotProvider,
    ButtonConfigureAction,
    ButtonDataKey,
    ButtonSummarizationAction,
    ButtonTopicManagementAction,
    ButtonUserDataConfigAction,
    LLMMessageFormat,
)

# Media
from .media import MediaProcessingInfo
from .text_formatter import FormatEntity, FormatType, OutputFormat

# User Metadata
from .user_metadata import UserMetadataDict

__all__ = [
    # Enums
    "BotProvider",
    "ButtonConfigureAction",
    "ButtonDataKey",
    "ButtonSummarizationAction",
    "LLMMessageFormat",
    "MessageType",
    "ButtonUserDataConfigAction",
    "ButtonTopicManagementAction",
    # Media
    "MediaProcessingInfo",
    # User Metadata
    "UserMetadataDict",
    # Command Handlers
    "CommandCategory",
    "CommandHandlerMixin",
    "commandHandlerV2",
    "CommandHandlerInfoV2",
    "CommandPermission",
    "CommandHandlerOrder",
    # Chat Settings
    "ChatTier",
    "ChatSettingsKey",
    "ChatSettingsType",
    "ChatSettingsValue",
    "getChatSettingsInfo",
    "ChatSettingsPage",
    "ChatSettingsDict",
    # Ensured Message
    "EnsuredMessage",
    "MentionCheckResult",
    "MessageSender",
    "MessageRecipient",
    "ChatType",
    "FormatType",
    "OutputFormat",
    "FormatEntity",
]
