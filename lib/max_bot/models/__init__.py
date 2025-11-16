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
    AttachmentList,
    AttachmentType,
    InteractiveAttachment,
    KeyboardAttachment,
    MediaAttachment,
    UploadRequest,
    UploadResult,
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
)

# Common models
from .common import (
    AudioToken,
    FileInfo,
    FileToken,
    Image,
    PaginationInfo,
    PhotoToken,
    TokenInfo,
    UploadEndpoint,
    VideoToken,
)

# Interactive models
from .interactive import (
    Contact,
    ContactRequest,
    Location,
    LocationRequest,
    Share,
    ShareRequest,
    Sticker,
    StickerRequest,
)

# Keyboard models
from .keyboard import (
    Button,
    ButtonType,
    CallbackButton,
    ChatButton,
    InlineKeyboardAttachment,
    Keyboard,
    LinkButton,
    MessageButton,
    OpenAppButton,
    ReplyButton,
    ReplyKeyboardAttachment,
    RequestContactButton,
    RequestGeoLocationButton,
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

# Media models
from .media import (
    Audio,
    AudioUploadRequest,
    File,
    FileUploadRequest,
    Photo,
    PhotoUploadRequest,
    Video,
    VideoUploadRequest,
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
    # Attachment models (8)
    "Attachment",
    "AttachmentType",
    "MediaAttachment",
    "InteractiveAttachment",
    "KeyboardAttachment",
    "AttachmentList",
    "UploadRequest",
    "UploadResult",
    # Media models (8)
    "Photo",
    "Video",
    "Audio",
    "File",
    "PhotoUploadRequest",
    "VideoUploadRequest",
    "AudioUploadRequest",
    "FileUploadRequest",
    # Interactive models (8)
    "Contact",
    "Location",
    "Share",
    "Sticker",
    "ContactRequest",
    "LocationRequest",
    "ShareRequest",
    "StickerRequest",
    # Keyboard models (13)
    "Button",
    "ButtonType",
    "CallbackButton",
    "LinkButton",
    "RequestContactButton",
    "RequestGeoLocationButton",
    "ChatButton",
    "OpenAppButton",
    "MessageButton",
    "ReplyButton",
    "Keyboard",
    "InlineKeyboardAttachment",
    "ReplyKeyboardAttachment",
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
    # Common models (9)
    "Image",
    "PhotoToken",
    "VideoToken",
    "AudioToken",
    "FileToken",
    "UploadEndpoint",
    "TokenInfo",
    "FileInfo",
    "PaginationInfo",
    # Response models (13)
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
]
