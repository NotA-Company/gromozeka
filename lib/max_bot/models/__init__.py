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
    ChatAdminPermission,
    ChatList,
    ChatMember,
    ChatMembersList,
    ChatPatch,
    ChatStatus,
    ChatType,
    SenderAction,
)

# Markup models
from .markup import (
    BoldMarkup,
    BotCommandMarkup,
    CashtagMarkup,
    CodeMarkup,
    EmailMarkup,
    HashtagMarkup,
    ItalicMarkup,
    MarkupElement,
    MarkupList,
    MarkupType,
    MentionMarkup,
    PhoneMarkup,
    PreMarkup,
    StrikethroughMarkup,
    TextLinkMarkup,
    UnderlineMarkup,
    UrlMarkup,
)

# Message models
from .message import (
    LinkedMessage,
    Message,
    MessageBody,
    MessageLinkType,
    MessageList,
    MessageStat,
    NewMessageBody,
    NewMessageLink,
    Recipient,
    SendMessageResult,
    TextFormat,
)

# Response models
from .response import (
    ApiResponse,
    BooleanResponse,
    BotStatus,
    CountResponse,
    Error,
    ErrorCode,
    IdResponse,
    ListResponse,
    PaginationInfo,
    ResponseStatus,
    SimpleQueryResult,
    Subscription,
    SubscriptionList,
    WebhookInfo,
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
    PhotoAttachmentRequest,
    PhotoAttachmentRequestPayload,
    PhotoToken,
    PhotoTokens,
    PhotoUploadResult,
    UploadedAttachment,
    UploadedPhoto,
    UploadEndpoint,
    UploadType,
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
    # Response models (13)
    "PaginationInfo",
    "ResponseStatus",
    "ErrorCode",
    "Error",
    "SimpleQueryResult",
    "Subscription",
    "SubscriptionList",
    "WebhookInfo",
    "BotStatus",
    "ApiResponse",
    "ListResponse",
    "CountResponse",
    "IdResponse",
    "BooleanResponse",
    # Markup models (16)
    "MarkupType",
    "MarkupElement",
    "BoldMarkup",
    "ItalicMarkup",
    "UnderlineMarkup",
    "StrikethroughMarkup",
    "CodeMarkup",
    "PreMarkup",
    "TextLinkMarkup",
    "MentionMarkup",
    "HashtagMarkup",
    "CashtagMarkup",
    "BotCommandMarkup",
    "UrlMarkup",
    "EmailMarkup",
    "PhoneMarkup",
    "MarkupList",
    # Upload Models
    "AttachmentRequest",
    "PhotoAttachmentRequest",
    "PhotoAttachmentRequestPayload",
    "PhotoToken",
    "PhotoTokens",
    "PhotoUploadResult",
    "UploadedAttachment",
    "UploadedPhoto",
    "UploadType",
    "UploadEndpoint",
]
