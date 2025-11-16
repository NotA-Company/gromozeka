# Max Bot Client Library Design v0

## Overview

The `lib.max_bot` library provides a comprehensive, async Python client for the Max Messenger Bot API. This design document outlines the architecture, components, and implementation strategy for building a production-ready bot client library using `httpx` as the HTTP client and dataclasses for model definitions.

## API Analysis Summary

### Base Configuration
- **Base URL**: `https://platform-api.max.ru`
- **Authentication**: Query parameter `access_token`
- **API Version**: 0.0.1
- **Content Type**: `application/json`

### Core Resource Groups
1. **Bot Management** (`/me`)
2. **Chat Operations** (`/chats`)
3. **Messaging** (`/messages`)
4. **Updates** (`/updates`, `/subscriptions`)
5. **File Uploads** (`/uploads`)

## Architecture Design

### Directory Structure
```
lib/max_bot/
├── __init__.py
├── client.py           # Main MaxBotClient class
├── auth.py            # Authentication handling
├── exceptions.py      # Custom exception classes
├── constants.py       # API constants and enums
├── models/
│   ├── __init__.py
│   ├── base.py       # Base model classes
│   ├── user.py       # User, BotInfo, ChatMember
│   ├── chat.py       # Chat, ChatList, ChatPatch
│   ├── message.py    # Message, MessageBody, NewMessageBody
│   ├── attachment.py # All attachment types
│   ├── keyboard.py   # Keyboard and button models
│   ├── update.py     # Update event models
│   └── response.py   # API response models
├── api/
│   ├── __init__.py
│   ├── base.py       # Base API client with common methods
│   ├── bot.py        # Bot-related endpoints
│   ├── chats.py      # Chat management endpoints
│   ├── messages.py   # Message operations
│   ├── members.py    # Chat member management
│   ├── updates.py    # Updates and subscriptions
│   └── uploads.py    # File upload operations
├── utils/
│   ├── __init__.py
│   ├── formatting.py # Text formatting utilities
│   ├── validators.py # Input validation
│   └── helpers.py    # Helper functions
└── test_client.py    # Unit tests
```

## Implementation Phases

### Phase 1: Core Infrastructure
**Components:**
- Base client with httpx integration
- Authentication mechanism
- Error handling and custom exceptions
- API constants and enums
- Base model classes with `api_kwargs` field

**Key Classes:**
```python
@dataclass(slots=True)
class BaseModel:
    """Base model for all API models"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)

class MaxBotClient:
    """Main client class"""
    def __init__(self, accessToken: str, baseUrl: str = "https://platform-api.max.ru")
```

### Phase 2: Models & Data Structures
**Components:**
- All TypedDict-style dataclasses from the API
- Proper inheritance hierarchy
- Validation methods
- Serialization/deserialization

**Model Categories:**
- User Models: `User`, `UserWithPhoto`, `BotInfo`, `ChatMember`
- Chat Models: `Chat`, `ChatType`, `ChatStatus`, `ChatList`
- Message Models: `Message`, `MessageBody`, `MessageList`
- Attachment Models: 9+ different attachment types
- Button Models: 7+ button types
- Update Models: 16+ update event types

### Phase 3: Basic Operations
**API Endpoints:**
- Bot information: `GET /me`
- Chat management: `GET/PATCH/DELETE /chats`
- Chat members: `GET/POST/DELETE /chats/{chatId}/members`
- Admin management: `GET/POST/DELETE /chats/{chatId}/members/admins`

**Key Features:**
- Paginated responses
- Chat search by link/username
- Member management with permissions

### Phase 4: Messaging System
**API Endpoints:**
- Send message: `POST /messages`
- Get messages: `GET /messages`
- Edit message: `PUT /messages`
- Delete message: `DELETE /messages`
- Message callbacks: `POST /answers`

**Key Features:**
- Text formatting (Markdown/HTML)
- Multiple attachment types
- Message threading (reply/forward)
- Link preview control

### Phase 5: Advanced Features
**Components:**
- Inline keyboards and buttons
- Callback handling
- Updates via long polling
- Webhook subscriptions
- Chat actions (typing indicators)

**Update Types:**
- Message events (created, edited, removed)
- Bot events (started, stopped, added, removed)
- User events (added, removed)
- Chat events (title changed, muted, cleared)

### Phase 6: File Operations
**API Endpoints:**
- Get upload URL: `POST /uploads`
- Video details: `GET /videos/{videoToken}`

**Upload Types:**
- Images (with multiple resolutions)
- Videos (with streaming support)
- Audio files
- Documents

## Design Patterns & Conventions

### Naming Conventions
- **Variables/Methods**: camelCase (e.g., `sendMessage`, `chatId`)
- **Classes**: PascalCase (e.g., `MaxBotClient`, `MessageBody`)
- **Constants**: UPPER_CASE (e.g., `MAX_MESSAGE_LENGTH`)

### Async/Await Pattern
All API methods will be async:
```python
async def sendMessage(self, chatId: int, text: str) -> Message:
    """Send a message to a chat"""
```

### Error Handling
Custom exceptions hierarchy:
```python
class MaxBotError(Exception): pass
class AuthenticationError(MaxBotError): pass
class RateLimitError(MaxBotError): pass
class APIError(MaxBotError): pass
```

### Caching Strategy
Optional caching for:
- Bot information
- Chat metadata
- User profiles

### Rate Limiting
Built-in rate limiter with configurable limits:
- Default: 100 requests/second (as per API docs)
- Customizable per endpoint

## Key Design Decisions

### 1. Dataclasses with Slots
All models use `@dataclass(slots=True)` for memory efficiency and performance.

### 2. Raw API Response Storage
Every model includes `api_kwargs: Dict[str, Any]` to store the raw API response for debugging and forward compatibility.

### 3. Modular API Structure
Separate API modules for different resource types, allowing for easier testing and maintenance.

### 4. Type Safety
Extensive use of type hints and TypedDict patterns for better IDE support and type checking.

### 5. Docstring Preservation
All API descriptions from the OpenAPI spec preserved as docstrings in Python code.

## Integration Examples

### Basic Usage
```python
from lib.max_bot import MaxBotClient

async def main():
    client = MaxBotClient(accessToken="YOUR_TOKEN")
    
    # Get bot info
    bot = await client.getMyInfo()
    
    # Send a message
    message = await client.sendMessage(
        chatId=12345,
        text="Hello, World!",
        attachments=[...]
    )
    
    # Handle updates
    async for update in client.getUpdates():
        await handleUpdate(update)
```

### Webhook Setup
```python
await client.subscribe(
    url="https://your-bot.com/webhook",
    updateTypes=["message_created", "message_callback"]
)
```

## Testing Strategy

### Unit Tests
- Mock httpx responses
- Test all model validations
- Test error handling

### Integration Tests
- Use test bot account
- Test real API endpoints
- Verify rate limiting

### Golden Data Tests
- Record API responses
- Replay for deterministic testing
- Follow existing `lib.aurumentation` patterns

## Performance Considerations

### Connection Pooling
- Reuse httpx client instance
- Configure pool size based on load

### Async Operations
- Concurrent request handling
- Async context managers

### Memory Optimization
- Use slots for all dataclasses
- Lazy loading for large responses
- Stream large file uploads/downloads

## Security Considerations

### Token Management
- Never log access tokens
- Support environment variables
- Token rotation helpers

### Input Validation
- Validate all user inputs
- Sanitize text for formatting
- Check file sizes before upload

### HTTPS Only
- Enforce HTTPS for all requests
- Verify SSL certificates
- Support custom CA bundles

## Documentation Requirements

### API Reference
- Complete method documentation
- Parameter descriptions
- Return type specifications
- Usage examples

### User Guide
- Getting started tutorial
- Common use cases
- Best practices
- Troubleshooting

## Migration Path

For existing bot implementations:
1. Gradual migration support
2. Compatibility layer for common patterns
3. Migration guide documentation

## Future Enhancements

### Planned Features
- WebApp/Mini-app support
- Voice message transcription
- Advanced media processing
- Bot analytics

### Extensibility
- Plugin system for custom handlers
- Middleware support
- Custom serializers

## Dependencies

### Required
- `httpx>=0.24.0` - Async HTTP client
- `python>=3.11` - For modern type hints

### Optional
- `aiofiles` - Async file operations
- `pillow` - Image processing
- `pydantic` - Advanced validation (alternative to dataclasses)

## Conclusion

This design provides a robust, type-safe, and performant client library for the Max Messenger Bot API. The phased implementation approach allows for incremental development while maintaining a clear architecture. The library follows Python best practices and integrates well with the existing project structure.