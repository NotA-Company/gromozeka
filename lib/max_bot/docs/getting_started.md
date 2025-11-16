# Getting Started with Max Bot

Welcome to the Max Bot client library! This guide will help you get your first Max Messenger bot up and running in minutes.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Getting Your Bot Token](#getting-your-bot-token)
- [Your First Bot](#your-first-bot)
- [Understanding the Basics](#understanding-the-basics)
- [Common Patterns](#common-patterns)
- [Next Steps](#next-steps)
- [Troubleshooting](#troubleshooting)

## Prerequisites

Before you start, make sure you have:

- **Python 3.7 or higher** installed
- **A Max Messenger account** with bot creation permissions
- **Basic knowledge of Python** and async/await patterns
- **A code editor** (VS Code, PyCharm, etc.)

## Installation

### Option 1: Install from PyPI (Recommended)

```bash
pip install max-bot
```

### Option 2: Install from Source

```bash
git clone https://github.com/your-org/max-bot.git
cd max-bot
pip install -e .
```

### Verify Installation

Create a simple test script to verify the installation:

```python
# test_installation.py
from lib.max_bot import MaxBotClient

print("✅ Max Bot library installed successfully!")
print(f"Version: {MaxBotClient.__version__ if hasattr(MaxBotClient, '__version__') else 'unknown'}")
```

Run it:

```bash
python test_installation.py
```

If you see the success message, you're ready to proceed!

## Getting Your Bot Token

Before you can create a bot, you need to get an access token from Max Messenger:

1. **Open Max Messenger** and go to Bot Settings
2. **Create a New Bot**:
   - Click "Create Bot"
   - Enter a name for your bot
   - Add a description and profile picture
   - Set up bot commands (optional)
3. **Get Your Token**:
   - In bot settings, find "Access Token"
   - Copy the token (it looks like: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)
4. **Keep Your Token Secure**:
   - Never share your token publicly
   - Don't commit it to version control
   - Use environment variables in production

### Setting Up Environment Variables

It's best practice to store your token as an environment variable:

**Linux/macOS:**
```bash
export MAX_BOT_TOKEN="your_access_token_here"
```

**Windows:**
```cmd
set MAX_BOT_TOKEN="your_access_token_here"
```

**Or create a `.env` file:**
```bash
# .env
MAX_BOT_TOKEN=your_access_token_here
```

Then load it in Python:
```python
from dotenv import load_dotenv
import os

load_dotenv()
token = os.getenv("MAX_BOT_TOKEN")
```

## Your First Bot

Let's create a simple echo bot that responds to messages and commands.

### Step 1: Create the Bot File

Create a new file called `my_first_bot.py`:

```python
#!/usr/bin/env python3
"""
My First Max Bot

A simple echo bot that demonstrates basic functionality.
"""

import asyncio
import logging
import os
import sys

from lib.max_bot import MaxBotClient, UpdateType, TextFormat, MaxBotError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_token():
    """Get the bot token from environment variables."""
    token = os.getenv("MAX_BOT_TOKEN")
    if not token:
        print("❌ Error: MAX_BOT_TOKEN environment variable is not set!")
        print("Please set your bot token:")
        print("export MAX_BOT_TOKEN='your_access_token_here'")
        sys.exit(1)
    return token

async def handle_message(client, update):
    """Handle incoming messages."""
    message = update.message
    chat_id = message.recipient.chat_id
    user_name = message.sender.first_name or "User"
    text = message.body.text or ""
    
    logger.info(f"💬 Message from {user_name}: {text}")
    
    # Handle commands
    if text.startswith('/'):
        await handle_command(client, chat_id, user_name, text)
    else:
        # Echo the message
        await client.sendMessage(
            chatId=chat_id,
            text=f"You said: {text}"
        )

async def handle_command(client, chat_id, user_name, command):
    """Handle bot commands."""
    if command.lower() == "/start":
        await client.sendMessage(
            chatId=chat_id,
            text=f"👋 Hello, {user_name}!\n\n"
                 "I'm a simple echo bot. Send me any message and I'll echo it back!\n\n"
                 "Available commands:\n"
                 "/start - Show this welcome message\n"
                 "/help - Show help information\n"
                 "/about - Learn about this bot"
        )
    elif command.lower() == "/help":
        await client.sendMessage(
            chatId=chat_id,
            text="🤖 *Bot Help*\n\n"
                 "This is a simple echo bot that demonstrates:\n"
                 "• Message handling\n"
                 "• Command processing\n"
                 "• Basic error handling\n\n"
                 "Try sending me any message!",
            format=TextFormat.MARKDOWN
        )
    elif command.lower() == "/about":
        await client.sendMessage(
            chatId=chat_id,
            text="📝 *About This Bot*\n\n"
                 "This is a demonstration bot built with the Max Bot client library.\n\n"
                 "Features:\n"
                 "• ✅ Message echoing\n"
                 "• ✅ Command handling\n"
                 "• ✅ Markdown formatting\n"
                 "• ✅ Error handling\n"
                 "• ✅ Logging\n\n"
                 "Built with ❤️ using Max Bot Library",
            format=TextFormat.MARKDOWN
        )
    else:
        await client.sendMessage(
            chatId=chat_id,
            text=f"❓ Unknown command: {command}\nType /help for available commands."
        )

async def run_bot():
    """Main bot function."""
    token = get_token()
    
    logger.info("🚀 Starting My First Bot...")
    
    try:
        # Initialize the client
        async with MaxBotClient(token) as client:
            # Get bot information
            bot_info = await client.getMyInfo()
            logger.info(f"✅ Bot started successfully: {bot_info.first_name}")
            logger.info(f"🆔 Bot ID: {bot_info.user_id}")
            
            # Health check
            if await client.healthCheck():
                logger.info("✅ API health check passed")
            else:
                logger.warning("⚠️ API health check failed")
            
            # Start polling for updates
            logger.info("🔄 Starting to poll for updates...")
            logger.info("📱 Send a message to your bot to try it out!")
            logger.info("⏹️ Press Ctrl+C to stop the bot")
            
            # Process updates
            async for update in client.startPolling():
                if update.updateType == UpdateType.MESSAGE_CREATED:
                    await handle_message(client, update)
                elif update.updateType == UpdateType.BOT_STARTED:
                    # Handle bot started event
                    chat_id = update.user.user_id
                    user_name = update.user.first_name or "User"
                    await handle_command(client, chat_id, user_name, "/start")
                
    except MaxBotError as e:
        logger.error(f"❌ Bot error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("⏹️ Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        sys.exit(1)

def main():
    """Entry point for the bot."""
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("👋 Goodbye!")

if __name__ == "__main__":
    main()
```

### Step 2: Run Your Bot

1. **Set your token**:
   ```bash
   export MAX_BOT_TOKEN="your_access_token_here"
   ```

2. **Run the bot**:
   ```bash
   python my_first_bot.py
   ```

3. **Test your bot**:
   - Open Max Messenger
   - Find your bot and start it
   - Send messages and commands

You should see output like:
```
2024-01-16 10:30:00 - __main__ - INFO - 🚀 Starting My First Bot...
2024-01-16 10:30:01 - __main__ - INFO - ✅ Bot started successfully: My First Bot
2024-01-16 10:30:01 - __main__ - INFO - 🆔 Bot ID: 123456789
2024-01-16 10:30:01 - __main__ - INFO - ✅ API health check passed
2024-01-16 10:30:01 - __main__ - INFO - 🔄 Starting to poll for updates...
2024-01-16 10:30:01 - __main__ - INFO - 📱 Send a message to your bot to try it out!
2024-01-16 10:30:01 - __main__ - INFO - ⏹️ Press Ctrl+C to stop the bot
2024-01-16 10:30:15 - __main__ - INFO - 💬 Message from John: Hello!
```

## Understanding the Basics

### The Client

The `MaxBotClient` is the main class for interacting with the Max Messenger API:

```python
from lib.max_bot import MaxBotClient

# Always use as a context manager
async with MaxBotClient(token) as client:
    # Your bot logic here
    pass
```

### Updates

Updates are incoming events from the API:

```python
async for update in client.startPolling():
    if update.updateType == UpdateType.MESSAGE_CREATED:
        # Handle new message
        message = update.message
        print(f"New message: {message.body.text}")
```

### Sending Messages

Send messages using the client methods:

```python
# Simple text message
await client.sendMessage(
    chatId="user_chat_id",
    text="Hello, World!"
)

# Message with formatting
await client.sendMessage(
    chatId="user_chat_id",
    text="*Bold* and _italic_ text",
    format=TextFormat.MARKDOWN
)
```

### Error Handling

Always handle errors properly:

```python
try:
    await client.sendMessage(chatId=chat_id, text="Hello!")
except MaxBotError as e:
    logger.error(f"Bot error: {e}")
except Exception as e:
    logger.error(f"Unexpected error: {e}")
```

## Common Patterns

### Pattern 1: Command Handler

Create a command handler for bot commands:

```python
async def handle_command(client, chat_id, command):
    """Handle bot commands."""
    commands = {
        '/start': handle_start,
        '/help': handle_help,
        '/about': handle_about
    }
    
    handler = commands.get(command.lower())
    if handler:
        await handler(client, chat_id)
    else:
        await client.sendMessage(
            chatId=chat_id,
            text="❓ Unknown command. Type /help for available commands."
        )

async def handle_start(client, chat_id):
    """Handle /start command."""
    await client.sendMessage(
        chatId=chat_id,
        text="👋 Welcome to the bot!"
    )
```

### Pattern 2: Message Router

Route messages based on content:

```python
async def handle_message(client, update):
    """Route messages to appropriate handlers."""
    message = update.message
    text = message.body.text or ""
    
    if text.startswith('/'):
        await handle_command(client, message.recipient.chat_id, text)
    elif 'hello' in text.lower():
        await handle_greeting(client, message)
    elif 'help' in text.lower():
        await handle_help_request(client, message)
    else:
        await handle_default(client, message)
```

### Pattern 3: Configuration Management

Manage bot configuration:

```python
import os
from dataclasses import dataclass

@dataclass
class BotConfig:
    token: str
    log_level: str = "INFO"
    admin_users: list = None
    
    @classmethod
    def from_env(cls):
        return cls(
            token=os.getenv("MAX_BOT_TOKEN"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            admin_users=os.getenv("ADMIN_USERS", "").split(",") if os.getenv("ADMIN_USERS") else []
        )

# Usage
config = BotConfig.from_env()
logging.basicConfig(level=getattr(logging, config.log_level))
```

### Pattern 4: Graceful Shutdown

Handle shutdown gracefully:

```python
import signal

class Bot:
    def __init__(self, client):
        self.client = client
        self.running = True
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info("🛑 Shutdown signal received")
        self.running = False
    
    async def run(self):
        """Run the bot with graceful shutdown."""
        # Set up signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        while self.running:
            try:
                async for update in self.client.startPolling():
                    if not self.running:
                        break
                    await self.handle_update(update)
            except Exception as e:
                logger.error(f"Error in polling loop: {e}")
                await asyncio.sleep(5)  # Wait before retrying
```

## Next Steps

Now that you have a basic bot running, here are some suggested next steps:

### 1. Try More Examples

Check out the [examples directory](../examples/) for more advanced bots:

- [`basic_bot.py`](../examples/basic_bot.py) - Enhanced basic bot
- [`keyboard_bot.py`](../examples/keyboard_bot.py) - Interactive keyboards
- [`file_bot.py`](../examples/file_bot.py) - File operations
- [`conversation_bot.py`](../examples/conversation_bot.py) - Stateful conversations

### 2. Learn Advanced Features

Read the [Advanced Usage Guide](advanced_usage.md) to learn about:

- Interactive keyboards
- File operations
- State management
- Webhooks
- Error handling
- Performance optimization

### 3. Build Your Own Bot

Think about what you want your bot to do:

- **Information bot**: Provide information on demand
- **Game bot**: Create interactive games
- **Utility bot**: Automate tasks
- **Support bot**: Handle customer service
- **Notification bot**: Send alerts and updates

### 4. Deploy Your Bot

Learn how to deploy your bot to production:

- Use webhooks instead of polling
- Set up proper logging and monitoring
- Handle errors and retries
- Scale for multiple users

## Troubleshooting

### Common Issues

#### 1. Authentication Error

```
❌ Error: Authentication failed! Please check your bot token.
```

**Solution**: 
- Verify your token is correct
- Make sure the token is set as an environment variable
- Check that your bot is active in Max Messenger

#### 2. Import Error

```
ModuleNotFoundError: No module named 'lib.max_bot'
```

**Solution**:
- Make sure you're running the script from the project root
- Install the library: `pip install max-bot`
- Check your Python path

#### 3. No Updates Received

Your bot starts but doesn't receive any updates.

**Solution**:
- Make sure you've started a conversation with your bot
- Check that your bot is properly configured
- Verify the bot has necessary permissions

#### 4. Connection Timeout

```
TimeoutError: Connection timed out
```

**Solution**:
- Check your internet connection
- Verify the API endpoint is accessible
- Try increasing the timeout in polling

### Debug Mode

Enable debug logging for more information:

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

Or set the environment variable:

```bash
LOG_LEVEL=DEBUG python my_first_bot.py
```

### Getting Help

If you're still having trouble:

1. **Check the logs** for error messages
2. **Review the examples** for working code
3. **Read the API reference** for detailed documentation
4. **Open an issue** on GitHub with details about your problem

---

Congratulations! You've built your first Max Bot. 🎉

Continue exploring the [examples](../examples/) and [advanced documentation](advanced_usage.md) to learn more about what you can do with the Max Bot client library.