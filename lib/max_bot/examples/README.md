# Max Bot Examples

This directory contains practical examples demonstrating various features and use cases of the Max Bot client library. Each example is a complete, runnable bot that showcases specific functionality.

## 📋 Table of Contents

- [Prerequisites](#prerequisites)
- [Running the Examples](#running-the-examples)
- [Examples Overview](#examples-overview)
- [Example Details](#example-details)
- [Common Patterns](#common-patterns)
- [Troubleshooting](#troubleshooting)

## 🚀 Prerequisites

Before running any example, make sure you have:

1. **Python 3.7+** installed
2. **Bot Access Token** from Max Messenger
3. **Required dependencies** installed:
   ```bash
   pip install -r requirements.txt
   ```

### Setting up your Bot Token

All examples require a bot access token. Set it as an environment variable:

```bash
export MAX_BOT_TOKEN="your_access_token_here"
```

For advanced examples, you may also want to set:

```bash
# Optional: Set log level (DEBUG, INFO, WARNING, ERROR)
export LOG_LEVEL="INFO"

# Optional: Set admin user IDs (comma-separated)
export ADMIN_USERS="12345678,87654321"
```

## 🏃 Running the Examples

### Basic Usage

```bash
# Run any example
python example_name.py

# Example with debug logging
LOG_LEVEL=DEBUG python example_name.py
```

### Using Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run example
python example_name.py
```

### Stopping the Bot

All examples use long-polling and will run until you stop them:

- **Linux/macOS**: Press `Ctrl+C`
- **Windows**: Press `Ctrl+C` or close the terminal

## 📚 Examples Overview

| Example | Description | Features Demonstrated | Complexity |
|---------|-------------|----------------------|------------|
| [`basic_bot.py`](basic_bot.py) | Simple echo bot | Basic messaging, commands, error handling | ⭐ Beginner |
| [`keyboard_bot.py`](keyboard_bot.py) | Interactive keyboards | Inline keyboards, reply keyboards, callbacks | ⭐⭐ Intermediate |
| [`file_bot.py`](file_bot.py) | File operations | Upload, download, streaming, attachments | ⭐⭐ Intermediate |
| [`conversation_bot.py`](conversation_bot.py) | Stateful conversations | State management, FSM, multi-step flows | ⭐⭐⭐ Advanced |
| [`webhook_bot.py`](webhook_bot.py) | Webhook integration | HTTP endpoints, FastAPI, webhook handling | ⭐⭐⭐ Advanced |
| [`advanced_bot.py`](advanced_bot.py) | Advanced features | Filters, middleware, monitoring, rate limiting | ⭐⭐⭐⭐ Expert |

## 📖 Example Details

### 1. Basic Bot (`basic_bot.py`)

**Purpose**: Demonstrates fundamental bot functionality with a simple echo bot.

**Features**:
- Message handling and echoing
- Command processing (`/start`, `/help`, `/echo`)
- Basic error handling
- Logging configuration
- Graceful shutdown

**Use Case**: Perfect for beginners learning the basics of bot development.

**Key Concepts**:
- Client initialization
- Update polling
- Message sending
- Command handling

### 2. Keyboard Bot (`keyboard_bot.py`)

**Purpose**: Shows how to create interactive user interfaces with keyboards.

**Features**:
- Inline keyboards with callback handling
- Reply keyboards for user input
- Dynamic keyboard updates
- Interactive games and settings
- Keyboard state management

**Use Case**: Building bots with rich user interactions and menus.

**Key Concepts**:
- Inline keyboards
- Reply keyboards
- Callback queries
- Keyboard layouts

### 3. File Bot (`file_bot.py`)

**Purpose**: Demonstrates file operations including upload, download, and streaming.

**Features**:
- File upload from local system
- File download with progress tracking
- Streaming file operations
- Multiple file type support
- File metadata handling

**Use Case**: Bots that need to handle file sharing, document processing, or media management.

**Key Concepts**:
- File attachments
- Upload/download operations
- Streaming
- File metadata

### 4. Conversation Bot (`conversation_bot.py`)

**Purpose**: Shows how to build stateful, multi-step conversations.

**Features**:
- Finite state machine (FSM)
- Conversation state management
- Multi-step user interactions
- Context preservation
- State transitions

**Use Case**: Building bots for surveys, forms, booking systems, or any multi-step process.

**Key Concepts**:
- State management
- Finite state machines
- Conversation flows
- Context handling

### 5. Webhook Bot (`webhook_bot.py`)

**Purpose**: Demonstrates webhook-based bot integration with FastAPI.

**Features**:
- HTTP webhook endpoint
- FastAPI integration
- Webhook security
- Asynchronous request handling
- Production-ready setup

**Use Case**: Production deployments where webhooks are preferred over polling.

**Key Concepts**:
- Webhooks
- FastAPI
- HTTP endpoints
- Asynchronous handling

### 6. Advanced Bot (`advanced_bot.py`)

**Purpose**: Showcases advanced features and production-ready patterns.

**Features**:
- Custom message filters
- Middleware processing chain
- Performance monitoring
- Rate limiting
- Comprehensive error handling
- Detailed logging
- Admin functionality

**Use Case**: Production bots requiring advanced features, monitoring, and control.

**Key Concepts**:
- Custom filters
- Middleware
- Performance monitoring
- Rate limiting
- Error handling

## 🔧 Common Patterns

### Error Handling

All examples demonstrate proper error handling:

```python
try:
    await client.sendMessage(chatId=chat_id, text="Hello!")
except MaxBotError as e:
    logging.error(f"Bot error: {e}")
except Exception as e:
    logging.error(f"Unexpected error: {e}")
```

### Logging Configuration

Most examples include logging setup:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### Graceful Shutdown

All examples handle shutdown gracefully:

```python
try:
    async with MaxBotClient(token) as client:
        # Bot logic here
        pass
except KeyboardInterrupt:
    logging.info("Bot stopped by user")
```

### Environment Variables

Examples use environment variables for configuration:

```python
import os

token = os.getenv("MAX_BOT_TOKEN")
if not token:
    print("Error: MAX_BOT_TOKEN not set!")
    sys.exit(1)
```

## 🛠️ Customization Tips

### Modifying Examples

1. **Change Bot Behavior**: Edit the message handling functions
2. **Add New Commands**: Add new command handlers in the appropriate sections
3. **Customize Keyboards**: Modify keyboard layouts and callbacks
4. **Adjust Logging**: Change log levels and formats
5. **Add Features**: Combine features from different examples

### Testing Your Bot

1. **Start the bot**: `python example_name.py`
2. **Send messages**: Use Max Messenger to interact with your bot
3. **Test features**: Try all demonstrated features
4. **Check logs**: Monitor terminal output for debugging

### Production Deployment

For production use:

1. **Use Webhooks**: Prefer `webhook_bot.py` over polling
2. **Add Monitoring**: Implement features from `advanced_bot.py`
3. **Secure Tokens**: Use secure token management
4. **Scale Up**: Consider load balancing for high traffic
5. **Error Recovery**: Implement robust error handling

## 🔍 Troubleshooting

### Common Issues

#### 1. Authentication Error
```
❌ Error: Authentication failed! Please check your bot token.
```

**Solution**: Verify your `MAX_BOT_TOKEN` is correct and properly set.

#### 2. Import Errors
```
ModuleNotFoundError: No module named 'lib.max_bot'
```

**Solution**: Ensure you're running the script from the project root directory.

#### 3. Permission Errors
```
PermissionError: [Errno 13] Permission denied: 'file.txt'
```

**Solution**: Check file permissions and ensure the bot has access to required files.

#### 4. Network Issues
```
ConnectionError: Failed to establish connection
```

**Solution**: Check your internet connection and firewall settings.

#### 5. Rate Limiting
```
RateLimitError: Too many requests
```

**Solution**: Implement rate limiting (see `advanced_bot.py`) or reduce request frequency.

### Debug Mode

Enable debug logging for more detailed information:

```bash
LOG_LEVEL=DEBUG python example_name.py
```

### Getting Help

1. **Check Logs**: Look for error messages in the terminal output
2. **Review Code**: Compare with working examples
3. **Test API**: Use the health check to verify API connectivity
4. **Check Documentation**: Refer to the main README.md for API details

## 📚 Next Steps

After running these examples:

1. **Combine Features**: Mix and match features from different examples
2. **Build Your Bot**: Create a bot for your specific use case
3. **Add Persistence**: Implement database storage for user data
4. **Add Testing**: Write unit tests for your bot logic
5. **Deploy**: Deploy your bot to a production environment

## 🤝 Contributing

Found a bug or want to improve an example?

1. **Report Issues**: Open an issue describing the problem
2. **Submit PRs**: Fork the repository and submit a pull request
3. **Share Ideas**: Suggest new examples or improvements

## 📄 License

These examples are part of the Max Bot client library and follow the same license terms.