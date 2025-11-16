# API Reference

This document provides a comprehensive reference for all classes, methods, and types in the Max Bot client library.

## Table of Contents

- [Core Classes](#core-classes)
  - [MaxBotClient](#maxbotclient)
- [Models](#models)
  - [Update](#update)
  - [Message](#message)
  - [User](#user)
  - [Chat](#chat)
  - [Attachment](#attachment)
- [Enums and Types](#enums-and-types)
  - [UpdateType](#updatetype)
  - [TextFormat](#textformat)
  - [AttachmentType](#attachmenttype)
- [Exceptions](#exceptions)
- [State Management](#state-management)
  - [StateManager](#statemanager)
  - [ConversationState](#conversationstate)

## Core Classes

### MaxBotClient

The main client class for interacting with the Max Messenger Bot API.

```python
class MaxBotClient:
    def __init__(self, token: str, base_url: str = "https://api.max-messenger.com/bot")
```

#### Constructor

| Parameter | Type | Description |
|-----------|------|-------------|
| `token` | `str` | Bot access token from Max Messenger |
| `base_url` | `str` | API base URL (optional, defaults to official API) |

#### Context Manager

The client should be used as a context manager:

```python
async with MaxBotClient(token) as client:
    # Use client here
    pass
```

#### Methods

##### sendMessage

Send a text message to a chat.

```python
async def sendMessage(
    self,
    chatId: str,
    text: str,
    format: TextFormat = TextFormat.PLAIN,
    inlineKeyboard: Optional[List[List[Dict]]] = None,
    replyKeyboard: Optional[List[List[Dict]]] = None,
    disableWebPagePreview: bool = False,
    disableNotification: bool = False
) -> Message
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `chatId` | `str` | Target chat ID |
| `text` | `str` | Message text |
| `format` | `TextFormat` | Text formatting (PLAIN, MARKDOWN, HTML) |
| `inlineKeyboard` | `List[List[Dict]]` | Inline keyboard layout |
| `replyKeyboard` | `replyKeyboard` | Reply keyboard layout |
| `disableWebPagePreview` | `bool` | Disable link previews |
| `disableNotification` | `bool` | Send silently |

**Returns:** `Message` - The sent message object

**Example:**
```python
await client.sendMessage(
    chatId="123456789",
    text="Hello, *World*!",
    format=TextFormat.MARKDOWN
)
```

##### sendPhoto

Send a photo to a chat.

```python
async def sendPhoto(
    self,
    chatId: str,
    photo: Union[str, bytes, BinaryIO],
    caption: Optional[str] = None,
    format: TextFormat = TextFormat.PLAIN,
    inlineKeyboard: Optional[List[List[Dict]]] = None,
    disableNotification: bool = False
) -> Message
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `chatId` | `str` | Target chat ID |
| `photo` | `Union[str, bytes, BinaryIO]` | Photo file path, URL, or file-like object |
| `caption` | `str` | Photo caption (optional) |
| `format` | `TextFormat` | Caption text formatting |
| `inlineKeyboard` | `List[List[Dict]]` | Inline keyboard layout |
| `disableNotification` | `bool` | Send silently |

**Returns:** `Message` - The sent message object

##### sendVideo

Send a video to a chat.

```python
async def sendVideo(
    self,
    chatId: str,
    video: Union[str, bytes, BinaryIO],
    caption: Optional[str] = None,
    duration: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    thumbnail: Optional[Union[str, bytes, BinaryIO]] = None,
    format: TextFormat = TextFormat.PLAIN,
    inlineKeyboard: Optional[List[List[Dict]]] = None,
    disableNotification: bool = False
) -> Message
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `chatId` | `str` | Target chat ID |
| `video` | `Union[str, bytes, BinaryIO]` | Video file path, URL, or file-like object |
| `caption` | `str` | Video caption (optional) |
| `duration` | `int` | Video duration in seconds (optional) |
| `width` | `int` | Video width in pixels (optional) |
| `height` | `int` | Video height in pixels (optional) |
| `thumbnail` | `Union[str, bytes, BinaryIO]` | Thumbnail file (optional) |
| `format` | `TextFormat` | Caption text formatting |
| `inlineKeyboard` | `List[List[Dict]]` | Inline keyboard layout |
| `disableNotification` | `bool` | Send silently |

**Returns:** `Message` - The sent message object

##### sendDocument

Send a document to a chat.

```python
async def sendDocument(
    self,
    chatId: str,
    document: Union[str, bytes, BinaryIO],
    caption: Optional[str] = None,
    format: TextFormat = TextFormat.PLAIN,
    inlineKeyboard: Optional[List[List[Dict]]] = None,
    disableNotification: bool = False
) -> Message
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `chatId` | `str` | Target chat ID |
| `document` | `Union[str, bytes, BinaryIO]` | Document file path, URL, or file-like object |
| `caption` | `str` | Document caption (optional) |
| `format` | `TextFormat` | Caption text formatting |
| `inlineKeyboard` | `List[List[Dict]]` | Inline keyboard layout |
| `disableNotification` | `bool` | Send silently |

**Returns:** `Message` - The sent message object

##### editMessage

Edit an existing message.

```python
async def editMessage(
    self,
    messageId: str,
    text: str,
    format: TextFormat = TextFormat.PLAIN,
    inlineKeyboard: Optional[List[List[Dict]]] = None
) -> Message
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `messageId` | `str` | ID of the message to edit |
| `text` | `str` | New message text |
| `format` | `TextFormat` | Text formatting |
| `inlineKeyboard` | `List[List[Dict]]` | New inline keyboard layout |

**Returns:** `Message` - The edited message object

##### deleteMessage

Delete a message.

```python
async def deleteMessage(self, messageId: str) -> bool
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `messageId` | `str` | ID of the message to delete |

**Returns:** `bool` - True if successful

##### answerCallbackQuery

Answer a callback query from an inline keyboard button.

```python
async def answerCallbackQuery(
    self,
    queryId: str,
    text: Optional[str] = None,
    showAlert: bool = False,
    url: Optional[str] = None
) -> bool
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `queryId` | `str` | Callback query ID |
| `text` | `str` | Alert text (optional) |
| `showAlert` | `bool` | Show as alert instead of toast |
| `url` | `str` | URL to open (optional) |

**Returns:** `bool` - True if successful

##### getMyInfo

Get information about the bot.

```python
async def getMyInfo(self) -> User
```

**Returns:** `User` - Bot user information

##### getChatInfo

Get information about a chat.

```python
async def getChatInfo(self, chatId: str) -> Chat
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `chatId` | `str` | Chat ID |

**Returns:** `Chat` - Chat information

##### getFile

Get file information and download URL.

```python
async def getFile(self, fileId: str) -> Dict[str, Any]
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `fileId` | `str` | File ID |

**Returns:** `Dict[str, Any]` - File information with download URL

##### downloadFile

Download a file.

```python
async def downloadFile(self, fileId: str, savePath: str) -> bool
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `fileId` | `str` | File ID |
| `savePath` | `str` | Local path to save the file |

**Returns:** `bool` - True if successful

##### startPolling

Start polling for updates.

```python
async def startPolling(
    self,
    offset: Optional[int] = None,
    limit: int = 100,
    timeout: int = 30,
    allowed_updates: Optional[List[UpdateType]] = None
) -> AsyncIterator[Update]
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `offset` | `int` | Starting offset (optional) |
| `limit` | `int` | Maximum number of updates per request |
| `timeout` | `int` | Polling timeout in seconds |
| `allowed_updates` | `List[UpdateType]` | Allowed update types |

**Returns:** `AsyncIterator[Update]` - Iterator of updates

##### setWebhook

Set a webhook for receiving updates.

```python
async def setWebhook(
    self,
    url: str,
    allowed_updates: Optional[List[UpdateType]] = None,
    secret_token: Optional[str] = None
) -> bool
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `url` | `str` | Webhook URL |
| `allowed_updates` | `List[UpdateType]` | Allowed update types |
| `secret_token` | `str` | Secret token for webhook verification |

**Returns:** `bool` - True if successful

##### deleteWebhook

Delete the webhook.

```python
async def deleteWebhook(self) -> bool
```

**Returns:** `bool` - True if successful

##### getWebhookInfo

Get current webhook information.

```python
async def getWebhookInfo(self) -> Dict[str, Any]
```

**Returns:** `Dict[str, Any]` - Webhook information

##### healthCheck

Check API health and connectivity.

```python
async def healthCheck(self) -> bool
```

**Returns:** `bool` - True if API is healthy

##### createInlineKeyboard

Create an inline keyboard layout.

```python
def createInlineKeyboard(self, buttons: List[List[Dict]]) -> List[List[Dict]]
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `buttons` | `List[List[Dict]]` | Button layout |

**Returns:** `List[List[Dict]]` - Formatted keyboard

##### createReplyKeyboard

Create a reply keyboard layout.

```python
def createReplyKeyboard(
    self,
    buttons: List[List[Dict]],
    resize_keyboard: bool = True,
    one_time_keyboard: bool = False,
    selective: bool = False
) -> Dict[str, Any]
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `buttons` | `List[List[Dict]]` | Button layout |
| `resize_keyboard` | `bool` | Resize keyboard to fit buttons |
| `one_time_keyboard` | `bool` | Hide keyboard after use |
| `selective` | `bool` | Show keyboard to specific users |

**Returns:** `Dict[str, Any]` - Formatted keyboard

## Models

### Update

Represents an incoming update from the bot API.

```python
class Update:
    updateId: int
    updateType: UpdateType
    message: Optional[Message]
    callbackQuery: Optional[CallbackQuery]
    chat: Optional[Chat]
    user: Optional[User]
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `updateId` | `int` | Unique update identifier |
| `updateType` | `UpdateType` | Type of update |
| `message` | `Message` | Message data (if applicable) |
| `callbackQuery` | `CallbackQuery` | Callback query data (if applicable) |
| `chat` | `Chat` | Chat data (if applicable) |
| `user` | `User` | User data (if applicable) |

### Message

Represents a message.

```python
class Message:
    mid: str
    sender: User
    recipient: Union[User, Chat]
    timestamp: int
    body: MessageBody
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `mid` | `str` | Message ID |
| `sender` | `User` | Message sender |
| `recipient` | `Union[User, Chat]` | Message recipient |
| `timestamp` | `int` | Message timestamp |
| `body` | `MessageBody` | Message body content |

### MessageBody

Represents the body of a message.

```python
class MessageBody:
    text: Optional[str]
    attachments: Optional[List[Attachment]]
    inlineKeyboard: Optional[List[List[Dict]]]
    replyKeyboard: Optional[Dict[str, Any]]
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `text` | `str` | Message text |
| `attachments` | `List[Attachment]` | Message attachments |
| `inlineKeyboard` | `List[List[Dict]]` | Inline keyboard |
| `replyKeyboard` | `Dict[str, Any]` | Reply keyboard |

### User

Represents a user or bot.

```python
class User:
    userId: int
    firstName: str
    lastName: Optional[str]
    username: Optional[str]
    languageCode: Optional[str]
    isBot: bool
    description: Optional[str]
    commands: Optional[List[Dict]]
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `userId` | `int` | User ID |
| `firstName` | `str` | First name |
| `lastName` | `str` | Last name (optional) |
| `username` | `str` | Username (optional) |
| `languageCode` | `str` | Language code (optional) |
| `isBot` | `bool` | Whether user is a bot |
| `description` | `str` | Bot description (for bots) |
| `commands` | `List[Dict]` | Bot commands (for bots) |

### Chat

Represents a chat.

```python
class Chat:
    chatId: str
    type: str
    title: Optional[str]
    description: Optional[str]
    photo: Optional[str]
    inviteLink: Optional[str]
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `chatId` | `str` | Chat ID |
| `type` | `str` | Chat type (private, group, channel) |
| `title` | `str` | Chat title (for groups/channels) |
| `description` | `str` | Chat description |
| `photo` | `str` | Chat photo URL |
| `inviteLink` | `str` | Chat invite link |

### Attachment

Represents a file attachment.

```python
class Attachment:
    type: AttachmentType
    fileId: str
    fileName: Optional[str]
    mimeType: Optional[str]
    fileSize: Optional[int]
    url: Optional[str]
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `type` | `AttachmentType` | Attachment type |
| `fileId` | `str` | File ID |
| `fileName` | `str` | File name |
| `mimeType` | `str` | MIME type |
| `fileSize` | `int` | File size in bytes |
| `url` | `str` | File URL (if available) |

### CallbackQuery

Represents a callback query from an inline keyboard.

```python
class CallbackQuery:
    queryId: str
    sender: User
    message: Message
    payload: str
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `queryId` | `str` | Query ID |
| `sender` | `User` | User who sent the query |
| `message` | `Message` | Original message with the button |
| `payload` | `str` | Button payload data |

## Enums and Types

### UpdateType

Enum of possible update types.

```python
class UpdateType(Enum):
    MESSAGE_CREATED = "message_created"
    MESSAGE_CALLBACK = "message_callback"
    MESSAGE_EDITED = "message_edited"
    MESSAGE_DELETED = "message_deleted"
    BOT_ADDED_TO_CHAT = "bot_added_to_chat"
    BOT_REMOVED_FROM_CHAT = "bot_removed_from_chat"
    BOT_STARTED = "bot_started"
    CHAT_CREATED = "chat_created"
    CHAT_DELETED = "chat_deleted"
    CHAT_TITLE_CHANGED = "chat_title_changed"
    CHAT_PHOTO_CHANGED = "chat_photo_changed"
    USER_ADDED_TO_CHAT = "user_added_to_chat"
    USER_REMOVED_FROM_CHAT = "user_removed_from_chat"
    USER_LEFT_CHAT = "user_left_chat"
```

### TextFormat

Enum of text formatting options.

```python
class TextFormat(Enum):
    PLAIN = "plain"
    MARKDOWN = "markdown"
    HTML = "html"
```

### AttachmentType

Enum of attachment types.

```python
class AttachmentType(Enum):
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    STICKER = "sticker"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
```

## Exceptions

### MaxBotError

Base exception for all Max Bot errors.

```python
class MaxBotError(Exception):
    pass
```

### AuthenticationError

Raised when authentication fails.

```python
class AuthenticationError(MaxBotError):
    pass
```

### RateLimitError

Raised when rate limits are exceeded.

```python
class RateLimitError(MaxBotError):
    retry_after: int
    
    def __init__(self, message: str, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after
```

### NetworkError

Raised when network operations fail.

```python
class NetworkError(MaxBotError):
    pass
```

### ValidationError

Raised when request validation fails.

```python
class ValidationError(MaxBotError):
    pass
```

### APIError

Raised when the API returns an error.

```python
class APIError(MaxBotError):
    error_code: int
    error_description: str
    
    def __init__(self, message: str, error_code: int = 0, error_description: str = ""):
        super().__init__(message)
        self.error_code = error_code
        self.error_description = error_description
```

## State Management

### StateManager

Manages conversation states for users.

```python
class StateManager:
    def __init__(self, storage: Optional[Dict[str, Any]] = None)
```

#### Methods

##### setState

Set state for a user.

```python
async def setState(self, user_id: int, state: str, data: Optional[Dict[str, Any]] = None) -> None
```

##### getState

Get state for a user.

```python
async def getState(self, user_id: int) -> Optional[ConversationState]
```

##### deleteState

Delete state for a user.

```python
async def deleteState(self, user_id: int) -> None
```

##### updateStateData

Update state data for a user.

```python
async def updateStateData(self, user_id: int, data: Dict[str, Any]) -> None
```

### ConversationState

Represents a conversation state.

```python
class ConversationState:
    user_id: int
    state: str
    data: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `user_id` | `int` | User ID |
| `state` | `str` | Current state name |
| `data` | `Dict[str, Any]` | State data |
| `created_at` | `datetime` | State creation time |
| `updated_at` | `datetime` | Last update time |

## Utility Functions

### createInlineButton

Create an inline button.

```python
def createInlineButton(
    text: str,
    payload: str,
    url: Optional[str] = None
) -> Dict[str, Any]
```

### createReplyButton

Create a reply button.

```python
def createReplyButton(
    text: str,
    request_contact: bool = False,
    request_location: bool = False
) -> Dict[str, Any]
```

### formatFileSize

Format file size in human-readable format.

```python
def formatFileSize(size_bytes: int) -> str
```

### escapeMarkdown

Escape text for Markdown formatting.

```python
def escapeMarkdown(text: str) -> str
```

### escapeHTML

Escape text for HTML formatting.

```python
def escapeHTML(text: str) -> str
```

---

This API reference covers all public classes, methods, and types in the Max Bot client library. For more examples and usage patterns, see the [examples directory](../examples/) and the [getting started guide](getting_started.md).