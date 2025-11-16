# Advanced Usage Guide

This guide covers advanced features and patterns for building sophisticated Max Messenger bots with the Max Bot client library.

## Table of Contents

- [Interactive Keyboards](#interactive-keyboards)
- [File Operations](#file-operations)
- [State Management](#state-management)
- [Webhooks](#webhooks)
- [Error Handling](#error-handling)
- [Performance Optimization](#performance-optimization)
- [Security Best Practices](#security-best-practices)
- [Testing Your Bot](#testing-your-bot)
- [Deployment Strategies](#deployment-strategies)

## Interactive Keyboards

Interactive keyboards provide rich user interfaces for your bots. Max Bot supports both inline and reply keyboards.

### Inline Keyboards

Inline keyboards appear directly in messages and support callback handling.

#### Creating Inline Keyboards

```python
from lib.max_bot import MaxBotClient

async def send_inline_keyboard(client, chat_id):
    """Send a message with inline keyboard."""
    
    # Create keyboard layout
    keyboard = client.createInlineKeyboard([
        [
            {"type": "callback", "text": "👍 Like", "payload": "like"},
            {"type": "callback", "text": "👎 Dislike", "payload": "dislike"}
        ],
        [
            {"type": "callback", "text": "🔄 Refresh", "payload": "refresh"},
            {"type": "callback", "text": "❌ Close", "payload": "close"}
        ]
    ])
    
    await client.sendMessage(
        chatId=chat_id,
        text="How do you like this feature?",
        inlineKeyboard=keyboard
    )
```

#### Handling Callback Queries

```python
async def handle_callback_query(client, update):
    """Handle inline keyboard callbacks."""
    callback = update.callbackQuery
    chat_id = callback.message.recipient.chat_id
    payload = callback.payload
    
    if payload == "like":
        await client.answerCallbackQuery(
            queryId=callback.queryId,
            text="Thanks for your feedback! 👍"
        )
        await client.editMessage(
            messageId=callback.message.body.mid,
            text="You liked this feature! 👍"
        )
    elif payload == "dislike":
        await client.answerCallbackQuery(
            queryId=callback.queryId,
            text="Thanks for your feedback! We'll improve 👎"
        )
        await client.editMessage(
            messageId=callback.message.body.mid,
            text="You disliked this feature. We'll work on it! 👎"
        )
    elif payload == "refresh":
        await client.answerCallbackQuery(
            queryId=callback.queryId,
            text="Content refreshed! 🔄"
        )
        # Refresh content logic here
    elif payload == "close":
        await client.editMessage(
            messageId=callback.message.body.mid,
            text="Menu closed. Type /start to show it again."
        )
```

#### URL Buttons

```python
async def send_url_keyboard(client, chat_id):
    """Send keyboard with URL buttons."""
    
    keyboard = client.createInlineKeyboard([
        [
            {"type": "url", "text": "🌐 Visit Website", "url": "https://example.com"},
            {"type": "callback", "text": "📊 Stats", "payload": "stats"}
        ]
    ])
    
    await client.sendMessage(
        chatId=chat_id,
        text="Choose an option:",
        inlineKeyboard=keyboard
    )
```

### Reply Keyboards

Reply keyboards replace the user's keyboard and are useful for structured input.

#### Creating Reply Keyboards

```python
async def send_reply_keyboard(client, chat_id):
    """Send a message with reply keyboard."""
    
    keyboard = client.createReplyKeyboard(
        buttons=[
            [
                {"text": "📊 Get Stats"},
                {"text": "⚙️ Settings"}
            ],
            [
                {"text": "❓ Help"},
                {"text": "🔍 Search"}
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    
    await client.sendMessage(
        chatId=chat_id,
        text="Choose an option from the keyboard:",
        replyKeyboard=keyboard
    )
```

#### Requesting Special Input

```python
async def request_contact(client, chat_id):
    """Request user's contact information."""
    
    keyboard = client.createReplyKeyboard(
        buttons=[
            [
                {"text": "📱 Share Contact", "request_contact": True}
            ],
            [
                {"text": "📍 Share Location", "request_location": True}
            ]
        ]
    )
    
    await client.sendMessage(
        chatId=chat_id,
        text="Please share your contact information:",
        replyKeyboard=keyboard
    )
```

#### Hiding Reply Keyboard

```python
async def hide_keyboard(client, chat_id):
    """Hide the reply keyboard."""
    
    await client.sendMessage(
        chatId=chat_id,
        text="Keyboard hidden. Use /menu to show it again.",
        replyKeyboard={"remove_keyboard": True}
    )
```

## File Operations

Max Bot supports comprehensive file operations including upload, download, and streaming.

### Uploading Files

#### Upload from Local Path

```python
async def upload_local_file(client, chat_id, file_path):
    """Upload a file from local path."""
    
    try:
        message = await client.sendDocument(
            chatId=chat_id,
            document=file_path,
            caption="Here's your document!"
        )
        print(f"File uploaded successfully: {message.mid}")
        return message
    except Exception as e:
        print(f"Error uploading file: {e}")
        raise
```

#### Upload with File-like Object

```python
import io

async def upload_from_memory(client, chat_id, content, filename):
    """Upload file from memory."""
    
    # Create file-like object
    file_obj = io.BytesIO(content.encode('utf-8'))
    
    message = await client.sendDocument(
        chatId=chat_id,
        document=file_obj,
        caption=f"Generated file: {filename}"
    )
    
    return message
```

#### Upload Photos and Videos

```python
async def upload_media(client, chat_id, photo_path, video_path):
    """Upload photos and videos."""
    
    # Upload photo
    photo_message = await client.sendPhoto(
        chatId=chat_id,
        photo=photo_path,
        caption="Check out this photo! 📸"
    )
    
    # Upload video
    video_message = await client.sendVideo(
        chatId=chat_id,
        video=video_path,
        caption="And here's a video! 🎥",
        duration=60,  # Optional: video duration
        width=1280,   # Optional: video width
        height=720    # Optional: video height
    )
    
    return photo_message, video_message
```

### Downloading Files

#### Download by File ID

```python
async def download_file(client, file_id, save_path):
    """Download a file by its ID."""
    
    try:
        # Get file information
        file_info = await client.getFile(file_id)
        
        # Download the file
        success = await client.downloadFile(file_id, save_path)
        
        if success:
            print(f"File downloaded to: {save_path}")
            return True
        else:
            print("Failed to download file")
            return False
            
    except Exception as e:
        print(f"Error downloading file: {e}")
        return False
```

#### Download from Message

```python
async def download_message_attachment(client, message, download_dir):
    """Download attachment from a message."""
    
    if not message.body.attachments:
        print("No attachments in message")
        return
    
    for attachment in message.body.attachments:
        file_id = attachment.fileId
        filename = attachment.fileName or f"file_{file_id}"
        save_path = f"{download_dir}/{filename}"
        
        await download_file(client, file_id, save_path)
```

### Streaming Operations

#### Stream Large Files

```python
import aiofiles

async def stream_large_file(client, chat_id, file_path, chunk_size=1024*1024):
    """Stream large files in chunks."""
    
    async with aiofiles.open(file_path, 'rb') as file:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            
            # Process chunk (e.g., upload, transform, etc.)
            # This is a simplified example
            print(f"Processing chunk of size: {len(chunk)}")
    
    # After streaming, send the file
    await client.sendDocument(
        chatId=chat_id,
        document=file_path,
        caption="Large file processed and uploaded!"
    )
```

## State Management

State management allows you to create complex, multi-step conversations.

### Using StateManager

```python
from lib.max_bot import StateManager

class ConversationBot:
    def __init__(self, client):
        self.client = client
        self.state_manager = StateManager()
    
    async def handle_message(self, update):
        """Handle messages with state management."""
        message = update.message
        user_id = message.sender.user_id
        text = message.body.text or ""
        
        # Get current state
        state = await self.state_manager.getState(user_id)
        
        if state:
            # User is in a conversation
            await self.handle_conversation_step(user_id, state, text)
        else:
            # Start new conversation
            await self.start_conversation(user_id, text)
    
    async def start_conversation(self, user_id, message):
        """Start a new conversation."""
        if message.lower() == "/survey":
            await self.state_manager.setState(user_id, "survey", {"step": 1})
            await self.client.sendMessage(
                chatId=str(user_id),
                text="📋 Survey Started!\n\nQuestion 1: What's your name?"
            )
    
    async def handle_conversation_step(self, user_id, state, message):
        """Handle conversation steps."""
        step = state.data.get("step", 1)
        
        if state.state == "survey":
            if step == 1:
                # Save name and ask next question
                await self.state_manager.updateStateData(user_id, {
                    "step": 2,
                    "name": message
                })
                await self.client.sendMessage(
                    chatId=str(user_id),
                    text=f"Nice to meet you, {message}!\n\nQuestion 2: What's your email?"
                )
            elif step == 2:
                # Save email and finish survey
                await self.state_manager.updateStateData(user_id, {
                    "step": 3,
                    "email": message
                })
                await self.finish_survey(user_id)
    
    async def finish_survey(self, user_id):
        """Finish the survey and clean up state."""
        state = await self.state_manager.getState(user_id)
        data = state.data
        
        await self.client.sendMessage(
            chatId=str(user_id),
            text=f"✅ Survey completed!\n\n"
                 f"Name: {data.get('name')}\n"
                 f"Email: {data.get('email')}\n\n"
                 f"Thank you for participating!"
        )
        
        # Clean up state
        await self.state_manager.deleteState(user_id)
```

### Finite State Machine

```python
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Callable

class SurveyState(Enum):
    START = "start"
    NAME = "name"
    EMAIL = "email"
    AGE = "age"
    COMPLETE = "complete"

@dataclass
class StateTransition:
    from_state: SurveyState
    input_pattern: str
    to_state: SurveyState
    action: Callable

class SurveyBot:
    def __init__(self, client):
        self.client = client
        self.state_manager = StateManager()
        self.transitions = self.setup_transitions()
    
    def setup_transitions(self):
        """Set up state transitions."""
        return {
            SurveyState.START: [
                StateTransition(
                    from_state=SurveyState.START,
                    input_pattern=r"/survey",
                    to_state=SurveyState.NAME,
                    action=self.ask_name
                )
            ],
            SurveyState.NAME: [
                StateTransition(
                    from_state=SurveyState.NAME,
                    input_pattern=r".+",  # Any text
                    to_state=SurveyState.EMAIL,
                    action=self.save_name_ask_email
                )
            ],
            SurveyState.EMAIL: [
                StateTransition(
                    from_state=SurveyState.EMAIL,
                    input_pattern=r"[^@]+@[^@]+\.[^@]+",  # Email pattern
                    to_state=SurveyState.AGE,
                    action=self.save_email_ask_age
                )
            ],
            SurveyState.AGE: [
                StateTransition(
                    from_state=SurveyState.AGE,
                    input_pattern=r"\d+",  # Numbers only
                    to_state=SurveyState.COMPLETE,
                    action=self.finish_survey
                )
            ]
        }
    
    async def handle_message(self, update):
        """Handle messages with FSM."""
        message = update.message
        user_id = message.sender.user_id
        text = message.body.text or ""
        
        # Get or initialize state
        state = await self.state_manager.getState(user_id)
        if not state:
            current_state = SurveyState.START
        else:
            current_state = SurveyState(state.state)
        
        # Find matching transition
        for transition in self.transitions.get(current_state, []):
            import re
            if re.match(transition.input_pattern, text):
                await transition.action(user_id, text)
                await self.state_manager.setState(
                    user_id, 
                    transition.to_state.value,
                    state.data if state else {}
                )
                break
        else:
            await self.client.sendMessage(
                chatId=str(user_id),
                text="I didn't understand that. Please try again."
            )
    
    async def ask_name(self, user_id, message):
        """Ask for user's name."""
        await self.client.sendMessage(
            chatId=str(user_id),
            text="📋 Survey Started!\n\nWhat's your name?"
        )
    
    async def save_name_ask_email(self, user_id, message):
        """Save name and ask for email."""
        await self.state_manager.updateStateData(user_id, {"name": message})
        await self.client.sendMessage(
            chatId=str(user_id),
            text=f"Nice to meet you, {message}!\n\nWhat's your email address?"
        )
    
    async def save_email_ask_age(self, user_id, message):
        """Save email and ask for age."""
        await self.state_manager.updateStateData(user_id, {"email": message})
        await self.client.sendMessage(
            chatId=str(user_id),
            text="Great! One last question:\n\nHow old are you?"
        )
    
    async def finish_survey(self, user_id, message):
        """Finish the survey."""
        state = await self.state_manager.getState(user_id)
        data = state.data
        
        await self.client.sendMessage(
            chatId=str(user_id),
            text=f"✅ Survey completed!\n\n"
                 f"Name: {data.get('name')}\n"
                 f"Email: {data.get('email')}\n"
                 f"Age: {message}\n\n"
                 f"Thank you for participating!"
        )
        
        await self.state_manager.deleteState(user_id)
```

## Webhooks

Webhooks provide a more efficient way to receive updates compared to polling.

### Setting Up Webhooks

```python
async def setup_webhook(client, webhook_url, secret_token=None):
    """Set up webhook for receiving updates."""
    
    try:
        success = await client.setWebhook(
            url=webhook_url,
            secret_token=secret_token
        )
        
        if success:
            print("✅ Webhook set up successfully")
            return True
        else:
            print("❌ Failed to set up webhook")
            return False
            
    except Exception as e:
        print(f"Error setting up webhook: {e}")
        return False
```

### Webhook Server with FastAPI

```python
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import Response
import hmac
import hashlib
import uvicorn

app = FastAPI()

# Store your bot client and secret token
bot_client = None
WEBHOOK_SECRET = "your_webhook_secret_here"

@app.on_event("startup")
async def startup_event():
    """Initialize bot client on startup."""
    global bot_client
    token = os.getenv("MAX_BOT_TOKEN")
    bot_client = MaxBotClient(token)
    
    # Set up webhook
    webhook_url = "https://your-domain.com/webhook"
    await setup_webhook(bot_client, webhook_url, WEBHOOK_SECRET)

def verify_webhook_signature(body: bytes, signature: str):
    """Verify webhook signature."""
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_signature)

@app.post("/webhook")
async def webhook_handler(
    request: Request,
    x_max_bot_signature: str = Header(None)
):
    """Handle incoming webhook updates."""
    
    # Verify signature
    body = await request.body()
    if x_max_bot_signature and not verify_webhook_signature(body, x_max_bot_signature):
        raise HTTPException(status_code=403, detail="Invalid signature")
    
    # Parse update
    try:
        update_data = await request.json()
        update = Update.from_dict(update_data)  # Assuming Update has from_dict method
        
        # Process update
        await process_webhook_update(bot_client, update)
        
        return Response(status_code=200)
        
    except Exception as e:
        print(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

async def process_webhook_update(client, update):
    """Process webhook update."""
    if update.updateType == UpdateType.MESSAGE_CREATED:
        await handle_message(client, update)
    elif update.updateType == UpdateType.MESSAGE_CALLBACK:
        await handle_callback(client, update)

# Run the server
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Webhook Management

```python
async def manage_webhooks(client):
    """Manage webhook lifecycle."""
    
    # Get current webhook info
    webhook_info = await client.getWebhookInfo()
    print(f"Current webhook: {webhook_info}")
    
    # Delete webhook (switch back to polling)
    await client.deleteWebhook()
    print("Webhook deleted, switching to polling mode")
    
    # Set new webhook
    new_webhook_url = "https://new-domain.com/webhook"
    await client.setWebhook(url=new_webhook_url)
    print(f"New webhook set: {new_webhook_url}")
```

## Error Handling

Robust error handling is crucial for production bots.

### Comprehensive Error Handling

```python
import logging
from lib.max_bot import MaxBotError, AuthenticationError, RateLimitError, NetworkError

class RobustBot:
    def __init__(self, client):
        self.client = client
        self.logger = logging.getLogger(__name__)
        self.retry_count = 3
        self.retry_delay = 5  # seconds
    
    async def safe_send_message(self, chat_id, text, **kwargs):
        """Send message with comprehensive error handling."""
        
        for attempt in range(self.retry_count):
            try:
                return await self.client.sendMessage(
                    chatId=chat_id,
                    text=text,
                    **kwargs
                )
                
            except AuthenticationError as e:
                self.logger.error(f"Authentication failed: {e}")
                # Don't retry auth errors
                raise
                
            except RateLimitError as e:
                self.logger.warning(f"Rate limit hit: {e}")
                if e.retry_after:
                    await asyncio.sleep(e.retry_after)
                else:
                    await asyncio.sleep(self.retry_delay)
                continue
                
            except NetworkError as e:
                self.logger.error(f"Network error: {e}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                else:
                    raise
                    
            except MaxBotError as e:
                self.logger.error(f"Bot error: {e}")
                # Don't retry other bot errors
                raise
                
            except Exception as e:
                self.logger.error(f"Unexpected error: {e}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                else:
                    raise MaxBotError(f"Failed to send message after {self.retry_count} attempts: {e}")
    
    async def handle_update_with_recovery(self, update):
        """Handle update with recovery mechanisms."""
        
        try:
            await self.process_update(update)
            
        except Exception as e:
            self.logger.error(f"Error processing update {update.updateId}: {e}")
            
            # Try to notify user
            try:
                chat_id = self.get_chat_id_from_update(update)
                await self.safe_send_message(
                    chat_id=chat_id,
                    text="❌ Sorry, something went wrong. Please try again later."
                )
            except Exception as notify_error:
                self.logger.error(f"Failed to notify user: {notify_error}")
            
            # Log full error for debugging
            self.logger.debug(f"Full error details: {traceback.format_exc()}")
```

### Error Recovery Strategies

```python
class ErrorRecoveryBot:
    def __init__(self, client):
        self.client = client
        self.error_counts = {}
        self.max_errors_per_user = 5
        self.error_reset_time = 3600  # 1 hour
    
    async def handle_with_circuit_breaker(self, user_id, handler_func):
        """Handle updates with circuit breaker pattern."""
        
        # Check error count for user
        error_count = self.error_counts.get(user_id, {"count": 0, "last_error": 0})
        current_time = time.time()
        
        # Reset error count if enough time has passed
        if current_time - error_count["last_error"] > self.error_reset_time:
            error_count = {"count": 0, "last_error": 0}
        
        # Check if circuit is open
        if error_count["count"] >= self.max_errors_per_user:
            self.logger.warning(f"Circuit breaker open for user {user_id}")
            await self.client.sendMessage(
                chatId=str(user_id),
                text="⚠️ Too many errors occurred. Please try again later."
            )
            return
        
        try:
            await handler_func()
            # Reset error count on success
            self.error_counts[user_id] = {"count": 0, "last_error": 0}
            
        except Exception as e:
            # Increment error count
            error_count["count"] += 1
            error_count["last_error"] = current_time
            self.error_counts[user_id] = error_count
            
            self.logger.error(f"Error for user {user_id} (count: {error_count['count']}): {e}")
            raise
```

## Performance Optimization

Optimize your bot for better performance and scalability.

### Connection Pooling

```python
import aiohttp

class OptimizedBotClient(MaxBotClient):
    """Optimized client with connection pooling."""
    
    def __init__(self, token, base_url=None, pool_size=10):
        self.pool_size = pool_size
        super().__init__(token, base_url)
    
    async def __aenter__(self):
        """Create session with connection pooling."""
        connector = aiohttp.TCPConnector(
            limit=self.pool_size,
            limit_per_host=self.pool_size,
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
        
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout
        )
        
        return self
```

### Batch Operations

```python
class BatchBot:
    """Bot that supports batch operations."""
    
    def __init__(self, client):
        self.client = client
        self.message_queue = []
        self.batch_size = 10
        self.batch_timeout = 5  # seconds
    
    async def queue_message(self, chat_id, text, **kwargs):
        """Queue a message for batch sending."""
        self.message_queue.append({
            "chat_id": chat_id,
            "text": text,
            **kwargs
        })
        
        if len(self.message_queue) >= self.batch_size:
            await self.flush_message_queue()
    
    async def flush_message_queue(self):
        """Send all queued messages."""
        if not self.message_queue:
            return
        
        tasks = []
        for msg in self.message_queue:
            task = self.client.sendMessage(
                chatId=msg["chat_id"],
                text=msg["text"],
                **{k: v for k, v in msg.items() if k not in ["chat_id", "text"]}
            )
            tasks.append(task)
        
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
            self.message_queue.clear()
        except Exception as e:
            self.logger.error(f"Error in batch send: {e}")
    
    async def periodic_flush(self):
        """Periodically flush message queue."""
        while True:
            await asyncio.sleep(self.batch_timeout)
            await self.flush_message_queue()
```

### Caching

```python
import functools
import time
from typing import Dict, Any

class CacheBot:
    """Bot with caching capabilities."""
    
    def __init__(self, client):
        self.client = client
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = 300  # 5 minutes
    
    def cached(self, ttl=None):
        """Decorator for caching method results."""
        def decorator(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                # Generate cache key
                cache_key = f"{func.__name__}:{hash(str(args) + str(kwargs))}"
                
                # Check cache
                if cache_key in self.cache:
                    cached_item = self.cache[cache_key]
                    if time.time() - cached_item["timestamp"] < (ttl or self.cache_ttl):
                        return cached_item["value"]
                
                # Execute function
                result = await func(*args, **kwargs)
                
                # Cache result
                self.cache[cache_key] = {
                    "value": result,
                    "timestamp": time.time()
                }
                
                return result
            return wrapper
        return decorator
    
    @cached(ttl=600)  # Cache for 10 minutes
    async def get_user_info(self, user_id):
        """Get user info with caching."""
        return await self.client.getChatInfo(str(user_id))
    
    def clean_expired_cache(self):
        """Clean expired cache entries."""
        current_time = time.time()
        expired_keys = [
            key for key, item in self.cache.items()
            if current_time - item["timestamp"] > self.cache_ttl
        ]
        
        for key in expired_keys:
            del self.cache[key]
```

## Security Best Practices

Implement security measures to protect your bot and users.

### Token Security

```python
import os
from cryptography.fernet import Fernet

class SecureBot:
    """Bot with enhanced security features."""
    
    def __init__(self, token_encrypted=None):
        self.token_encrypted = token_encrypted
        self.cipher_suite = Fernet(os.getenv("ENCRYPTION_KEY", Fernet.generate_key()))
    
    def get_token(self):
        """Get decrypted token."""
        if self.token_encrypted:
            return self.cipher_suite.decrypt(self.token_encrypted.encode()).decode()
        else:
            # Fallback to environment variable
            token = os.getenv("MAX_BOT_TOKEN")
            if not token:
                raise ValueError("No bot token provided")
            return token
    
    @staticmethod
    def encrypt_token(token: str, key: str) -> str:
        """Encrypt a token for storage."""
        cipher_suite = Fernet(key)
        return cipher_suite.encrypt(token.encode()).decode()
```

### Input Validation

```python
import re
from html import escape

class SecureMessageHandler:
    """Handler with input validation."""
    
    @staticmethod
    def sanitize_text(text: str, max_length: int = 1000) -> str:
        """Sanitize user input text."""
        if not text:
            return ""
        
        # Limit length
        text = text[:max_length]
        
        # Escape HTML entities
        text = escape(text)
        
        # Remove potentially dangerous patterns
        dangerous_patterns = [
            r'<script.*?>.*?</script>',
            r'javascript:',
            r'on\w+\s*=',
        ]
        
        for pattern in dangerous_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        return text
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email format."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    @staticmethod
    def validate_phone(phone: str) -> bool:
        """Validate phone number format."""
        # Remove all non-digit characters
        digits = re.sub(r'\D', '', phone)
        # Check if it has reasonable length (10-15 digits)
        return 10 <= len(digits) <= 15
```

### Rate Limiting

```python
import time
from collections import defaultdict, deque

class RateLimiter:
    """Rate limiter for bot operations."""
    
    def __init__(self, max_requests=10, time_window=60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.user_requests: Dict[int, deque] = defaultdict(deque)
    
    def is_allowed(self, user_id: int) -> bool:
        """Check if user is allowed to make a request."""
        current_time = time.time()
        requests = self.user_requests[user_id]
        
        # Remove old requests
        while requests and requests[0] <= current_time - self.time_window:
            requests.popleft()
        
        # Check if under limit
        if len(requests) < self.max_requests:
            requests.append(current_time)
            return True
        
        return False
    
    def get_retry_after(self, user_id: int) -> int:
        """Get seconds until user can make next request."""
        requests = self.user_requests[user_id]
        if not requests:
            return 0
        
        oldest_request = requests[0]
        retry_after = int(oldest_request + self.time_window - time.time())
        return max(0, retry_after)

class RateLimitedBot:
    """Bot with rate limiting."""
    
    def __init__(self, client):
        self.client = client
        self.rate_limiter = RateLimiter(max_requests=5, time_window=60)
    
    async def handle_message(self, update):
        """Handle message with rate limiting."""
        user_id = update.message.sender.user_id
        
        if not self.rate_limiter.is_allowed(user_id):
            retry_after = self.rate_limiter.get_retry_after(user_id)
            await self.client.sendMessage(
                chatId=update.message.recipient.chat_id,
                text=f"⚠️ Rate limit exceeded. Please wait {retry_after} seconds."
            )
            return
        
        # Process message normally
        await self.process_message(update)
```

## Testing Your Bot

Comprehensive testing ensures your bot works correctly.

### Unit Testing

```python
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

class TestBot(unittest.TestCase):
    """Unit tests for bot functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_client = AsyncMock()
        self.bot = MyBot(self.mock_client)
    
    async def test_handle_start_command(self):
        """Test handling of /start command."""
        # Create mock update
        mock_update = MagicMock()
        mock_update.updateType = UpdateType.MESSAGE_CREATED
        mock_update.message.sender.user_id = 123
        mock_update.message.sender.first_name = "Test User"
        mock_update.message.recipient.chat_id = "123"
        mock_update.message.body.text = "/start"
        
        # Handle the update
        await self.bot.handle_message(mock_update)
        
        # Verify the response
        self.mock_client.sendMessage.assert_called_once()
        call_args = self.mock_client.sendMessage.call_args
        self.assertEqual(call_args[1]["chatId"], "123")
        self.assertIn("Hello", call_args[1]["text"])
    
    def test_sanitize_text(self):
        """Test text sanitization."""
        dangerous_text = "<script>alert('xss')</script>Hello"
        safe_text = SecureMessageHandler.sanitize_text(dangerous_text)
        self.assertNotIn("<script>", safe_text)
        self.assertIn("Hello", safe_text)
    
    def test_validate_email(self):
        """Test email validation."""
        self.assertTrue(SecureMessageHandler.validate_email("test@example.com"))
        self.assertFalse(SecureMessageHandler.validate_email("invalid-email"))
        self.assertFalse(SecureMessageHandler.validate_email(""))

# Run async tests
def run_async_test(test_func):
    """Helper to run async tests."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(test_func())
    finally:
        loop.close()

# Example usage
if __name__ == "__main__":
    test = TestBot()
    test.setUp()
    run_async_test(test.test_handle_start_command)
    test.test_sanitize_text()
    test.test_validate_email()
```

### Integration Testing

```python
class IntegrationTest:
    """Integration tests for bot."""
    
    async def test_full_conversation(self):
        """Test a complete conversation flow."""
        # Set up test bot with real client (use test token)
        token = os.getenv("TEST_BOT_TOKEN")
        async with MaxBotClient(token) as client:
            bot = ConversationBot(client)
            test_chat_id = os.getenv("TEST_CHAT_ID")
            
            # Start survey
            await client.sendMessage(
                chatId=test_chat_id,
                text="/survey"
            )
            
            # Wait for response
            await asyncio.sleep(2)
            
            # Send name
            await client.sendMessage(
                chatId=test_chat_id,
                text="Test User"
            )
            
            # Wait for response
            await asyncio.sleep(2)
            
            # Send email
            await client.sendMessage(
                chatId=test_chat_id,
                text="test@example.com"
            )
            
            # Verify survey completion
            # (This would require checking the final message)
```

## Deployment Strategies

Deploy your bot for production use.

### Docker Deployment

```dockerfile
# Dockerfile
FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app
RUN chown -R app:app /app
USER app

# Expose port for webhooks
EXPOSE 8000

# Run the application
CMD ["python", "webhook_bot.py"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  bot:
    build: .
    environment:
      - MAX_BOT_TOKEN=${MAX_BOT_TOKEN}
      - WEBHOOK_SECRET=${WEBHOOK_SECRET}
      - LOG_LEVEL=INFO
    ports:
      - "8000:8000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### Environment Configuration

```python
# config.py
import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class BotConfig:
    """Bot configuration from environment variables."""
    
    # Required
    token: str
    
    # Optional
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    log_level: str = "INFO"
    admin_users: list = None
    
    # Rate limiting
    max_requests_per_minute: int = 30
    
    # Database (if needed)
    database_url: Optional[str] = None
    
    # Redis (if needed for caching)
    redis_url: Optional[str] = None
    
    @classmethod
    def from_env(cls) -> 'BotConfig':
        """Create config from environment variables."""
        token = os.getenv("MAX_BOT_TOKEN")
        if not token:
            raise ValueError("MAX_BOT_TOKEN environment variable is required")
        
        admin_users_str = os.getenv("ADMIN_USERS", "")
        admin_users = [int(uid.strip()) for uid in admin_users_str.split(",") if uid.strip()]
        
        return cls(
            token=token,
            webhook_url=os.getenv("WEBHOOK_URL"),
            webhook_secret=os.getenv("WEBHOOK_SECRET"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            admin_users=admin_users,
            max_requests_per_minute=int(os.getenv("MAX_REQUESTS_PER_MINUTE", "30")),
            database_url=os.getenv("DATABASE_URL"),
            redis_url=os.getenv("REDIS_URL")
        )
```

### Monitoring and Logging

```python
import logging
import sys
from pythonjsonlogger import jsonlogger

def setup_production_logging():
    """Set up structured logging for production."""
    
    # Create logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Create JSON formatter
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(name)s %(levelname)s %(message)s'
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (optional)
    file_handler = logging.FileHandler('/app/logs/bot.log')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

class MonitoringBot:
    """Bot with monitoring capabilities."""
    
    def __init__(self, client):
        self.client = client
        self.logger = logging.getLogger(__name__)
        self.metrics = {
            "messages_processed": 0,
            "errors": 0,
            "start_time": time.time()
        }
    
    async def handle_update(self, update):
        """Handle update with monitoring."""
        start_time = time.time()
        
        try:
            await self.process_update(update)
            self.metrics["messages_processed"] += 1
            
            # Log processing time
            processing_time = time.time() - start_time
            self.logger.info("Update processed", extra={
                "update_type": update.updateType,
                "processing_time": processing_time,
                "messages_processed": self.metrics["messages_processed"]
            })
            
        except Exception as e:
            self.metrics["errors"] += 1
            self.logger.error("Update processing failed", extra={
                "update_type": update.updateType,
                "error": str(e),
                "errors": self.metrics["errors"]
            }, exc_info=True)
            raise
    
    def get_health_status(self):
        """Get bot health status."""
        uptime = time.time() - self.metrics["start_time"]
        error_rate = self.metrics["errors"] / max(self.metrics["messages_processed"], 1)
        
        return {
            "status": "healthy" if error_rate < 0.05 else "degraded",
            "uptime": uptime,
            "messages_processed": self.metrics["messages_processed"],
            "errors": self.metrics["errors"],
            "error_rate": error_rate
        }
```

---

This advanced usage guide covers the most sophisticated features and patterns for building production-ready Max Messenger bots. For more specific examples, see the [examples directory](../examples/) and refer to the [API reference](api_reference.md) for detailed method documentation.