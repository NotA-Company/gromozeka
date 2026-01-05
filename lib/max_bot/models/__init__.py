"""
Max Messenger Bot API Models Package.

This package contains all the dataclass models for the Max Messenger Bot API,
organized into logical modules for better maintainability.

The models are organized into the following categories:
- User: User-related models including bots
- Chat: Chat and chat member models
- Message: Message and message-related models
- Attachment: Base attachment models and infrastructure
- Media: Media attachment models (photo, video, audio, file)
- Interactive: Interactive attachment models (contact, location, share, sticker)
- Keyboard: Keyboard and button models
- Update: Update event models
- Common: Common utility models
- Response: API response models
- Markup: Text markup models

All models use dataclass with slots for memory efficiency and include:
- Proper type hints
- from_dict() class methods for parsing API responses
- api_kwargs field for storing raw API response data
- Comprehensive docstrings from the OpenAPI specification
"""

# Attachment models
from .attachment import (
    Attachment,
    AttachmentPayload,
    AttachmentType,
    AudioAttachment,
    ContactAttachment,
    ContactAttachmentPayload,
    DataAttachment,
    FileAttachment,
    FileAttachmentPayload,
    InlineKeyboardAttachment,
    KeyboardAttachment,
    LocationAttachment,
    MediaAttachmentPayload,
    PhotoAttachment,
    PhotoAttachmentPayload,
    ReplyKeyboardAttachment,
    ShareAttachment,
    ShareAttachmentPayload,
    StickerAttachment,
    StickerAttachmentPayload,
    VideoAttachment,
    VideoAttachmentDetails,
    VideoThumbnail,
    VideoUrls,
    attachmentFromDict,
)

# Base model
from .base import BaseMaxBotModel

# Callback model
from .callback import Callback, CallbackAnswer

# Chat models
from .chat import (
    Chat,
    ChatAdmin,
    ChatList,
    ChatMember,
    ChatMembersList,
    ChatPatch,
)
from .enums import (
    ButtonType,
    ChatAdminPermission,
    ChatStatus,
    ChatType,
    MessageLinkType,
    SenderAction,
    TextFormat,
)
from .keyboard import (
    Button,
    CallbackButton,
    ChatButton,
    Keyboard,
    LinkButton,
    MessageButton,
    OpenAppButton,
    ReplyButton,
    RequestContactButton,
    RequestGeoLocationButton,
)

# Markup models
from .markup import (
    EmphasizedMarkup,
    HeadingMarkup,
    HighlightedMarkup,
    LinkMarkup,
    MarkupElement,
    MarkupType,
    MonospacedMarkup,
    StrikethroughMarkup,
    StrongMarkup,
    UnderlineMarkup,
    UserMentionMarkup,
    markupListFromList,
)

# Message models
from .message import (
    LinkedMessage,
    Message,
    MessageBody,
    MessageList,
    MessageStat,
    NewMessageBody,
    NewMessageLink,
    Recipient,
    SendMessageResult,
)

# Update models
from .update import (
    BotAddedUpdate,
    BotRemovedFromChatUpdate,
    BotStartedUpdate,
    BotStoppedUpdate,
    ChatTitleChangedUpdate,
    DialogClearedUpdate,
    DialogMutedUpdate,
    DialogRemovedUpdate,
    DialogUnmutedUpdate,
    MessageCallbackUpdate,
    MessageChatCreatedUpdate,
    MessageCreatedUpdate,
    MessageEditedUpdate,
    MessageRemovedUpdate,
    Update,
    UpdateList,
    UpdateType,
    UserAddedToChatUpdate,
    UserRemovedFromChatUpdate,
)
from .upload import (
    AttachmentRequest,
    AudioAttachmentRequest,
    FileAttachmentRequest,
    FileUploadResult,
    InlineKeyboardAttachmentRequest,
    PhotoAttachmentRequest,
    PhotoAttachmentRequestPayload,
    PhotoToken,
    PhotoTokens,
    PhotoUploadResult,
    UploadedAttachment,
    UploadedAudio,
    UploadedFile,
    UploadedInfo,
    UploadedPhoto,
    UploadedVideo,
    UploadEndpoint,
    UploadType,
    VideoAttachmentRequest,
)

# User models
from .user import (
    BotCommand,
    BotInfo,
    BotPatch,
    User,
    UserWithPhoto,
)

__all__ = [
    # Base models (1)
    "BaseMaxBotModel",
    # Callback models (1)
    "Callback",
    "CallbackAnswer",
    # User models (5)
    "User",
    "UserWithPhoto",
    "BotInfo",
    "BotCommand",
    "BotPatch",
    # Chat models (9)
    "Chat",
    "ChatMember",
    "ChatAdmin",
    "ChatAdminPermission",
    "ChatType",
    "ChatStatus",
    "ChatList",
    "ChatMembersList",
    "ChatPatch",
    "SenderAction",
    # Message models (11)
    "Message",
    "MessageBody",
    "Recipient",
    "MessageStat",
    "MessageList",
    "NewMessageBody",
    "NewMessageLink",
    "LinkedMessage",
    "SendMessageResult",
    "TextFormat",
    "MessageLinkType",
    # Attachment models (25)
    "Attachment",
    "AttachmentType",
    "PhotoAttachment",
    "PhotoAttachmentPayload",
    "AttachmentPayload",
    "MediaAttachmentPayload",
    "FileAttachmentPayload",
    "AudioAttachment",
    "FileAttachment",
    "LocationAttachment",
    "StickerAttachment",
    "StickerAttachmentPayload",
    "ShareAttachment",
    "ShareAttachmentPayload",
    "ContactAttachment",
    "ContactAttachmentPayload",
    "VideoAttachment",
    "VideoThumbnail",
    "VideoUrls",
    "VideoAttachmentDetails",
    "KeyboardAttachment",
    "InlineKeyboardAttachment",
    "ReplyKeyboardAttachment",
    "DataAttachment",
    "attachmentFromDict",
    # Update models (18)
    "Update",
    "UpdateType",
    "UpdateList",
    "MessageCreatedUpdate",
    "MessageEditedUpdate",
    "MessageRemovedUpdate",
    "DialogMutedUpdate",
    "DialogUnmutedUpdate",
    "DialogClearedUpdate",
    "DialogRemovedUpdate",
    "UserAddedToChatUpdate",
    "UserRemovedFromChatUpdate",
    "BotStartedUpdate",
    "BotStoppedUpdate",
    "ChatTitleChangedUpdate",
    "MessageChatCreatedUpdate",
    "BotAddedUpdate",
    "BotRemovedFromChatUpdate",
    "MessageCallbackUpdate",
    # Markup models (12)
    "MarkupType",
    "MarkupElement",
    "StrongMarkup",
    "EmphasizedMarkup",
    "MonospacedMarkup",
    "StrikethroughMarkup",
    "UnderlineMarkup",
    "HeadingMarkup",
    "HighlightedMarkup",
    "LinkMarkup",
    "UserMentionMarkup",
    "markupListFromList",
    # Upload Models
    "AttachmentRequest",
    "InlineKeyboardAttachmentRequest",
    "PhotoAttachmentRequest",
    "PhotoAttachmentRequestPayload",
    "PhotoToken",
    "PhotoTokens",
    "PhotoUploadResult",
    "UploadedAttachment",
    "UploadedPhoto",
    "UploadType",
    "UploadEndpoint",
    "FileAttachmentRequest",
    "FileUploadResult",
    "UploadedFile",
    "VideoAttachmentRequest",
    "UploadedVideo",
    "UploadedInfo",
    "AudioAttachmentRequest",
    "UploadedAudio",
    # Enums
    "ButtonType",
    # Buttons
    "Button",
    "ChatButton",
    "CallbackButton",
    "LinkButton",
    "ReplyButton",
    "MessageButton",
    "OpenAppButton",
    "RequestContactButton",
    "RequestGeoLocationButton",
    "Keyboard",
]
