# Max Bot Client Library

A comprehensive async Python client for the Max Messenger Bot API with proper authentication, error handling, retry logic, and advanced features including state management, file operations, and interactive keyboards.

## Features

- **🚀 Async/Await Support**: Built on `httpx` for efficient async operations
- **🔒 Type Safety**: Full type hints and dataclass models throughout the library
- **🛡️ Error Handling**: Comprehensive exception hierarchy for different error types
- **🔄 Retry Logic**: Automatic retries with exponential backoff for transient failures
- **🔐 Authentication**: Secure token-based authentication with proper header handling
- **📦 Context Manager**: Support for async context managers for proper resource cleanup
- **📝 Logging**: Detailed logging for debugging and monitoring
- **🎯 State Management**: Built-in finite state machine for conversation flows
- **📁 File Operations**: Complete file upload/download support with streaming
- **⌨️ Interactive Keyboards**: Inline and reply keyboards with callback handling
- **📡 Webhook Support**: Both polling and webhook-based update handling
- **🎨 Prinny Personality**: Because every bot library needs some personality, dood!

## Installation

This library is part of the Gromozeka project. Ensure you have the required dependencies:

```bash
pip install httpx>=0.24.0
```

## Quick Start

### Basic Echo Bot

```python
import asyncio
import os
from lib.max_bot import MaxBotClient, UpdateType

async def echo_bot():
    token = os.getenv("MAX_BOT_TOKEN")
    async with MaxBotClient(token) as client:
        # Get bot information
        bot_info = await client.getMyInfo()
        print(f"Bot started: {bot_info.first_name}")
        
        # Start polling for updates
        async for update in client.startPolling():
            if update.updateType == UpdateType.MESSAGE_CREATED:
                message = update.message
                if message.body.text:
                    # Echo the message back
                    await client.sendMessage(
                        chatId=message.recipient.chat_id,
                        text=f"You said: {message.body.text}"
                    )

if __name__ == "__main__":
    asyncio.run(echo_bot())
```

### Manual Resource Management

```python
import asyncio
from lib.max_bot import MaxBotClient

async def main():
    client = MaxBotClient("your_access_token")
    try:
        bot_info = await client.getMyInfo()
        print(f"Bot: {bot_info.first_name}")
    finally:
        await client.aclose()  # Don't forget to cleanup!

asyncio.run(main())
```

## Installation & Setup

### Prerequisites

- Python 3.12+ (required for StrEnum and modern features)
- Max Messenger Bot API access token
- `httpx>=0.24.0` for HTTP operations

### Environment Setup

```bash
# Set your bot token as environment variable
export MAX_BOT_TOKEN="your_access_token_here"

# Or create a .env file
echo "MAX_BOT_TOKEN=your_access_token_here" > .env
```

## Authentication

The Max Bot API uses token-based authentication. You need to provide your bot's access token when creating the client:

```python
from lib.max_bot import MaxBotClient
import os

# Token from environment variable (recommended)
token = os.getenv("MAX_BOT_TOKEN")
client = MaxBotClient(token)

# Token passed directly
client = MaxBotClient("your_access_token_here")
```

### Security Best Practices

- ✅ Use environment variables or secure configuration management
- ✅ Never hardcode tokens in your source code
- ✅ Rotate tokens regularly
- ✅ Monitor token usage for suspicious activity
- ✅ Use different tokens for development and production

## Configuration

The client supports various configuration options:

```python
from lib.max_bot import MaxBotClient

client = MaxBotClient(
    accessToken="your_token",
    baseUrl="https://platform-api.max.ru",  # Custom base URL
    timeout=30,                              # Request timeout in seconds
    maxRetries=3,                            # Maximum retry attempts
    retryBackoffFactor=1.0                   # Exponential backoff factor
)
```

### Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `accessToken` | `str` | Required | Bot access token for authentication |
| `baseUrl` | `str` | `https://platform-api.max.ru` | API base URL |
| `timeout` | `int` | `30` | Request timeout in seconds |
| `maxRetries` | `int` | `3` | Maximum number of retry attempts |
| `retryBackoffFactor` | `float` | `1.0` | Backoff factor for retry delays |

## Core API Methods

### Bot Information

```python
# Get bot information
bot_info = await client.getMyInfo()
print(f"Bot ID: {bot_info.user_id}")
print(f"Bot name: {bot_info.first_name}")

# Health check
if await client.healthCheck():
    print("API is healthy!")
```

### Chat Management

```python
# Get list of chats
chats = await client.getChats(count=20)
for chat in chats.chats:
    print(f"Chat: {chat.title}")

# Get specific chat info
chat = await client.getChat(chat_id=12345)

# Edit chat information
await client.editChatInfo(
    chatId=12345,
    title="New Chat Title",
    description="Updated description"
)

# Send chat actions
await client.sendAction(chatId=12345, action=SenderAction.TYPING)

# Pin/unpin messages
await client.pinMessage(chatId=12345, messageId="msg_67890")
await client.unpinMessage(chatId=12345)
```

### Member Management

```python
# Get chat members
members = await client.getMembers(chatId=12345, count=10)
for member in members.members:
    print(f"Member: {member.first_name}")

# Add members to chat
await client.addMembers(chatId=12345, userIds=[67890, 98765])

# Remove member from chat
await client.removeMember(chatId=12345, userId=67890)

# Get chat administrators
admins = await client.getAdmins(chatId=12345)
```

### Messaging System

```python
# Send text message
result = await client.sendMessage(
    chatId=12345,
    text="Hello, World!",
    format=TextFormat.MARKDOWN
)

# Send message with reply
await client.sendMessage(
    chatId=12345,
    text="This is a reply",
    replyTo="msg_67890"
)

# Edit message
await client.editMessage(
    messageId="msg_67890",
    text="Updated message text"
)

# Delete messages
await client.deleteMessages(["msg_67890", "msg_12345"])

# Get messages
messages = await client.getMessages(chatId=12345, count=20)
for message in messages.messages:
    print(f"Message: {message.body.text}")
```

## File Operations

### Uploading Files

```python
# Upload photo
photo_result = await client.uploadPhoto("path/to/photo.jpg")
await client.sendMessage(
    chatId=12345,
    attachments=[photo_result.attachment]
)

# Upload video
video_result = await client.uploadVideo("path/to/video.mp4")

# Upload document
doc_result = await client.uploadDocument("path/to/document.pdf")

# Upload from stream
with open("large_file.zip", "rb") as f:
    file_result = await client.uploadFileStream(f, "large_file.zip")
```

### Downloading Files

```python
# Get file URL
file_url = await client.getFileUrl("file_12345")

# Download file to disk
await client.downloadFile("file_12345", "downloaded_file.jpg")

# Download file as bytes
file_bytes = await client.downloadFileBytes("file_12345")

# Stream download
async for chunk in client.downloadFileStream("file_12345"):
    # Process file chunks
    pass
```

## Interactive Keyboards

### Inline Keyboards

```python
# Create inline keyboard
keyboard = client.createInlineKeyboard([
    [
        {"type": ButtonType.CALLBACK, "text": "Option 1", "payload": "opt1"},
        {"type": ButtonType.CALLBACK, "text": "Option 2", "payload": "opt2"}
    ],
    [
        {"type": ButtonType.LINK, "text": "Visit Website", "url": "https://example.com"}
    ]
])

# Send message with inline keyboard
await client.sendMessage(
    chatId=12345,
    text="Choose an option:",
    inlineKeyboard=keyboard
)

# Handle callback queries
async for update in client.startPolling():
    if update.updateType == UpdateType.MESSAGE_CALLBACK:
        callback = update.callbackQuery
        await client.answerCallbackQuery(
            queryId=callback.query_id,
            text=f"You selected: {callback.payload}"
        )
```

### Reply Keyboards

```python
# Create reply keyboard
keyboard = client.createReplyKeyboard([
    ["📍 Share Location", "📞 Share Contact"],
    ["❌ Cancel"]
], resize_keyboard=True, one_time_keyboard=True)

# Send message with reply keyboard
await client.sendMessage(
    chatId=12345,
    text="Please choose an action:",
    keyboard=keyboard
)

# Remove keyboard
await client.sendMessage(
    chatId=12345,
    text="Keyboard removed",
    keyboard=client.removeKeyboard()
)
```

## State Management

The library includes a comprehensive state management system for building conversational bots:

```python
from lib.max_bot.state import StateManager, State, MemoryStateStorage

# Create state manager
storage = MemoryStateStorage()
state_manager = StateManager(storage)

# Define states
idle_state = State("idle")
waiting_for_name_state = State("waiting_for_name")
waiting_for_age_state = State("waiting_for_age")

# Add transitions
idle_state.add_transition("start", waiting_for_name_state)
waiting_for_name_state.add_transition("name_received", waiting_for_age_state)
waiting_for_age_state.add_transition("age_received", idle_state)

# Register states
state_manager.add_state(idle_state)
state_manager.add_state(waiting_for_name_state)
state_manager.add_state(waiting_for_age_state)
state_manager.set_default_state(idle_state)

# Use in bot
async for update in client.startPolling():
    if update.updateType == UpdateType.MESSAGE_CREATED:
        user_id = update.message.sender.user_id
        chat_id = update.message.recipient.chat_id
        
        # Get or create context
        context = await state_manager.get_context(user_id, chat_id)
        if not context:
            context = await state_manager.create_context(user_id, chat_id)
        
        # Handle based on current state
        if context.currentState.name == "idle":
            if "start" in update.message.body.text.lower():
                await state_manager.transition_state("start", user_id, chat_id)
                await client.sendMessage(chatId=chat_id, text="What's your name?")
        
        elif context.currentState.name == "waiting_for_name":
            name = update.message.body.text
            await state_manager.transition_state("name_received", user_id, chat_id, {"name": name})
            await client.sendMessage(chatId=chat_id, text=f"Nice to meet you, {name}! How old are you?")
        
        elif context.currentState.name == "waiting_for_age":
            age = update.message.body.text
            await state_manager.transition_state("age_received", user_id, chat_id, {"age": age})
            name = await state_manager.get_state_data("name", user_id=user_id, chatId=chat_id)
            await client.sendMessage(chatId=chatId, text=f"Thank you {name}, age {age} registered!")
```

## Webhook Support

### Setting Up Webhooks

```python
# Set webhook
await client.setWebhook(
    url="https://your-domain.com/webhook",
    events=[UpdateType.MESSAGE_CREATED, UpdateType.MESSAGE_CALLBACK]
)

# Get webhook info
webhook_info = await client.getWebhookInfo()
print(f"Webhook URL: {webhook_info.url}")

# Delete webhook
await client.deleteWebhook("https://your-domain.com/webhook")
```

### Webhook Handler Example

```python
from fastapi import FastAPI, Request
from lib.max_bot import MaxBotClient

app = FastAPI()
client = MaxBotClient("your_token")

@app.post("/webhook")
async def webhook_handler(request: Request):
    update_data = await request.json()
    update = Update.from_dict(update_data)
    
    if update.updateType == UpdateType.MESSAGE_CREATED:
        message = update.message
        if message.body.text:
            await client.sendMessage(
                chatId=message.recipient.chat_id,
                text=f"Webhook received: {message.body.text}"
            )
    
    return {"status": "ok"}
```

## Error Handling

The library provides a comprehensive exception hierarchy:

```python
from lib.max_bot import (
    MaxBotClient, AuthenticationError, RateLimitError,
    NetworkError, ValidationError, NotFoundError
)

async def handle_errors():
    async with MaxBotClient("token") as client:
        try:
            bot_info = await client.getMyInfo()
        except AuthenticationError:
            print("❌ Invalid or expired token!")
        except RateLimitError:
            print("⏰ Too many requests. Please wait.")
        except NetworkError:
            print("🌐 Network connection failed.")
        except ValidationError:
            print("⚠️ Invalid request parameters.")
        except NotFoundError:
            print("🔍 Resource not found.")
        except Exception as e:
            print(f"❓ Unexpected error: {e}")
```

### Exception Types

- `MaxBotError`: Base exception for all Max Bot API errors
- `AuthenticationError`: Invalid or missing access token
- `RateLimitError`: API rate limit exceeded
- `ValidationError`: Invalid request parameters
- `NotFoundError`: Requested resource not found
- `MethodNotAllowedError`: HTTP method not allowed for endpoint
- `ServiceUnavailableError`: API service temporarily unavailable
- `NetworkError`: Network-related errors
- `ConfigurationError`: Client configuration errors

## Constants and Enums

The library provides useful constants and enums:

```python
from lib.max_bot import (
    ChatType, ChatStatus, UpdateType,
    SenderAction, UploadType, TextFormat,
    ButtonType, AttachmentType,
    HTTP_GET, HTTP_POST, API_BASE_URL
)

# Use enums for type safety
chat_type = ChatType.DIALOG
action = SenderAction.TYPING
format_type = TextFormat.MARKDOWN
button_type = ButtonType.CALLBACK
```

## Logging

Configure logging to see detailed information:

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("lib.max_bot")
logger.setLevel(logging.DEBUG)

# Custom logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

## Rate Limiting

The API has rate limits (default: 100 requests per second). The client automatically handles rate limit errors with exponential backoff:

```python
# The client will automatically retry on rate limit errors
async with MaxBotClient("token") as client:
    for i in range(150):  # More than the rate limit
        try:
            result = await client.getMyInfo()
            print(f"Request {i+1}: Success")
        except RateLimitError:
            print("Rate limited - client will retry automatically")
```

## Advanced Examples

### Media Bot

```python
async def media_bot():
    async with MaxBotClient("token") as client:
        async for update in client.startPolling():
            if update.updateType == UpdateType.MESSAGE_CREATED:
                message = update.message
                
                # Handle photo uploads
                if message.body.attachments:
                    for attachment in message.body.attachments:
                        if attachment.type == AttachmentType.PHOTO:
                            await client.sendMessage(
                                chatId=message.recipient.chat_id,
                                text="Nice photo! 📸"
                            )
                
                # Handle location requests
                elif "location" in message.body.text.lower():
                    await client.sendLocation(
                        chatId=message.recipient.chat_id,
                        latitude=55.7558,
                        longitude=37.6173,
                        title="Moscow"
                    )
```

### Admin Bot

```python
async def admin_bot():
    async with MaxBotClient("token") as client:
        async for update in client.startPolling():
            if update.updateType == UpdateType.MESSAGE_CREATED:
                message = update.message
                chat_id = message.recipient.chat_id
                
                # Admin commands
                if message.body.text.startswith("/admin"):
                    # Check if user is admin
                    admins = await client.getAdmins(chat_id)
                    admin_ids = [admin.user_id for admin in admins.members]
                    
                    if message.sender.user_id in admin_ids:
                        await client.sendMessage(
                            chatId=chat_id,
                            text="Admin commands available:\n/pin - Pin message\n/kick - Kick user"
                        )
                    else:
                        await client.sendMessage(
                            chatId=chat_id,
                            text="You're not an admin! 🚫"
                        )
```

## Testing

### Running Tests

```bash
# Run all tests
make test

# Run with coverage
make coverage

# Format code
make format

# Check linting
make lint
```

### Test Structure

```
lib/max_bot/
├── test_client.py      # Client tests
├── test_dispatcher.py  # Dispatcher tests
├── test_handlers.py    # Handler tests
├── test_models.py      # Model tests
├── test_state.py       # State management tests
└── test_file_utils.py  # File operation tests
```

## Project Structure

```
lib/max_bot/
├── __init__.py          # Package exports and metadata
├── client.py            # Main MaxBotClient class
├── constants.py         # API constants and enums
├── exceptions.py        # Custom exception classes
├── state.py            # State management system
├── file_utils.py       # File operation utilities
├── formatting.py       # Text formatting utilities
├── filters.py          # Message filters
├── handlers.py         # Update handlers
├── dispatcher.py       # Update dispatcher
├── models/             # Data models
│   ├── __init__.py
│   ├── user.py         # User models
│   ├── chat.py         # Chat models
│   ├── message.py      # Message models
│   ├── attachment.py   # Attachment models
│   ├── keyboard.py     # Keyboard models
│   └── update.py       # Update models
├── examples/           # Usage examples
│   ├── basic_bot.py
│   ├── keyboard_bot.py
│   ├── file_bot.py
│   ├── conversation_bot.py
│   ├── webhook_bot.py
│   └── advanced_bot.py
├── docs/               # Documentation
│   ├── api_reference.md
│   ├── getting_started.md
│   ├── advanced_usage.md
│   └── migration_guide.md
└── README.md           # This file
```

## Examples Directory

Check out the [`examples/`](examples/) directory for comprehensive, runnable examples:

- **[`basic_bot.py`](examples/basic_bot.py)** - Simple echo bot
- **[`keyboard_bot.py`](examples/keyboard_bot.py)** - Interactive keyboards
- **[`file_bot.py`](examples/file_bot.py)** - File upload/download
- **[`conversation_bot.py`](examples/conversation_bot.py)** - Stateful conversations
- **[`webhook_bot.py`](examples/webhook_bot.py)** - Webhook-based bot
- **[`advanced_bot.py`](examples/advanced_bot.py)** - Advanced features

## Documentation

- **[API Reference](docs/api_reference.md)** - Complete API documentation
- **[Getting Started](docs/getting_started.md)** - Beginner's guide
- **[Advanced Usage](docs/advanced_usage.md)** - Advanced features and patterns
- **[Migration Guide](docs/migration_guide.md)** - Migrating from other libraries

## Contributing

1. Follow the existing code style (camelCase for variables/methods)
2. Add comprehensive docstrings with examples
3. Include type hints for all functions
4. Write tests for new functionality
5. Run `make format` and `make lint` before committing
6. Update documentation for new features

## Performance Considerations

- **Connection Pooling**: The client uses httpx's connection pooling
- **Memory Efficiency**: Models use `__slots__` for reduced memory usage
- **Async Operations**: All I/O operations are non-blocking
- **State Storage**: Choose appropriate storage (memory vs file) based on needs
- **File Streaming**: Large files are streamed to avoid memory issues

## Troubleshooting

### Common Issues

**"Authentication failed"**
- Check your access token is correct
- Ensure the token hasn't expired
- Verify the token has required permissions

**"Rate limit exceeded"**
- Implement proper backoff in your code
- Consider caching responses
- Use batch operations where possible

**"Network error"**
- Check your internet connection
- Verify the API base URL is correct
- Consider increasing timeout values

**"File upload failed"**
- Ensure file size is within limits (4GB max)
- Check file format is supported
- Verify file path is accessible

### Debug Mode

Enable debug logging for detailed troubleshooting:

```python
import logging
logging.getLogger("lib.max_bot").setLevel(logging.DEBUG)
```

## License

This library is part of the Gromozeka project. See the main project license for details.

## Support

For issues and questions:
- 📖 Check the [examples](examples/) directory
- 🔍 Review the [API Documentation](https://dev.max.ru/docs-api)
- 🐛 Report issues on [GitHub Issues](https://github.com/your-org/gromozeka/issues)
- 💬 Contact support at [@support](https://max.ru/support)

---

*Remember: Every bot client needs a little personality, dood! 🎯*