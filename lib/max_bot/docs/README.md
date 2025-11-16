# Max Bot Documentation

Welcome to the comprehensive documentation for the Max Bot client library. This directory contains detailed guides, API references, and examples to help you build powerful Max Messenger bots.

## 📚 Documentation Structure

### Getting Started
- [`getting_started.md`](getting_started.md) - Beginner's guide to get your first bot running
- [`installation.md`](installation.md) - Installation and setup instructions

### Core Documentation
- [`api_reference.md`](api_reference.md) - Complete API reference documentation
- [`advanced_usage.md`](advanced_usage.md) - Advanced features and patterns

### Guides and Tutorials
- [`migration_guide.md`](migration_guide.md) - Migrating from other bot libraries
- [`best_practices.md`](best_practices.md) - Recommended practices and patterns
- [`troubleshooting.md`](troubleshooting.md) - Common issues and solutions

### Examples
- [`../examples/`](../examples/) - Practical, runnable examples
- [`../examples/README.md`](../examples/README.md) - Examples overview and guide

### Reference
- [`changelog.md`](changelog.md) - Version history and changes
- [`glossary.md`](glossary.md) - Terminology and definitions

## 🚀 Quick Start

1. **Install the library**:
   ```bash
   pip install max-bot
   ```

2. **Create your first bot**:
   ```python
   from lib.max_bot import MaxBotClient
   
   async def main():
       async with MaxBotClient("your_token_here") as client:
           await client.sendMessage(
               chatId="user_chat_id",
               text="Hello, World!"
           )
   
   import asyncio
   asyncio.run(main())
   ```

3. **Run the examples**:
   ```bash
   cd lib/max_bot/examples
   python basic_bot.py
   ```

## 📖 Documentation Navigation

### For Beginners
1. Start with [Getting Started](getting_started.md)
2. Try the [Basic Bot Example](../examples/basic_bot.py)
3. Explore [API Reference](api_reference.md) as needed

### For Intermediate Users
1. Review [Advanced Usage](advanced_usage.md)
2. Try [Keyboard Bot](../examples/keyboard_bot.py) and [File Bot](../examples/file_bot.py)
3. Check [Best Practices](best_practices.md)

### For Advanced Users
1. Study [Conversation Bot](../examples/conversation_bot.py) and [Webhook Bot](../examples/webhook_bot.py)
2. Explore [Advanced Bot](../examples/advanced_bot.py) for production patterns
3. Review [Migration Guide](migration_guide.md) if coming from other libraries

## 🔍 Finding Information

### By Topic
- **Basic Messaging**: [Getting Started](getting_started.md), [API Reference - Messages](api_reference.md#messages)
- **Keyboards**: [Advanced Usage - Keyboards](advanced_usage.md#keyboards), [Keyboard Bot Example](../examples/keyboard_bot.py)
- **File Operations**: [Advanced Usage - Files](advanced_usage.md#files), [File Bot Example](../examples/file_bot.py)
- **State Management**: [Advanced Usage - State](advanced_usage.md#state-management), [Conversation Bot Example](../examples/conversation_bot.py)
- **Webhooks**: [Advanced Usage - Webhooks](advanced_usage.md#webhooks), [Webhook Bot Example](../examples/webhook_bot.py)
- **Error Handling**: [API Reference - Errors](api_reference.md#errors), [Best Practices](best_practices.md#error-handling)

### By Use Case
- **Simple Echo Bot**: [Basic Bot Example](../examples/basic_bot.py)
- **Interactive Menu Bot**: [Keyboard Bot Example](../examples/keyboard_bot.py)
- **File Sharing Bot**: [File Bot Example](../examples/file_bot.py)
- **Survey/Form Bot**: [Conversation Bot Example](../examples/conversation_bot.py)
- **Production Bot**: [Advanced Bot Example](../examples/advanced_bot.py)

## 🛠️ Contributing to Documentation

Found an error or want to improve the documentation?

1. **Report Issues**: Open an issue describing the problem
2. **Submit Changes**: Fork the repository and submit a pull request
3. **Suggest Improvements**: Open an issue with suggestions

### Documentation Guidelines

- **Clear and Concise**: Use simple language and avoid jargon
- **Code Examples**: Include working, tested code examples
- **Consistent Formatting**: Follow the established markdown style
- **Cross-References**: Link to related documentation
- **Up-to-Date**: Keep documentation current with the codebase

## 📝 Documentation Status

| Document | Status | Last Updated |
|----------|--------|--------------|
| [Getting Started](getting_started.md) | ✅ Complete | 2024-01-16 |
| [API Reference](api_reference.md) | ✅ Complete | 2024-01-16 |
| [Advanced Usage](advanced_usage.md) | ✅ Complete | 2024-01-16 |
| [Migration Guide](migration_guide.md) | ✅ Complete | 2024-01-16 |
| [Installation](installation.md) | 📝 Planned | - |
| [Best Practices](best_practices.md) | 📝 Planned | - |
| [Troubleshooting](troubleshooting.md) | 📝 Planned | - |
| [Changelog](changelog.md) | 📝 Planned | - |
| [Glossary](glossary.md) | 📝 Planned | - |

## 🔗 External Resources

- [Max Messenger Bot API](https://max-messenger.com/bot-api) - Official API documentation
- [Max Messenger Developer Portal](https://max-messenger.com/developers) - Developer resources
- [Python Asyncio Documentation](https://docs.python.org/3/library/asyncio.html) - Async programming guide
- [FastAPI Documentation](https://fastapi.tiangolo.com/) - For webhook implementations

## 📞 Support

Need help with the Max Bot library?

1. **Check Documentation**: Search these docs first
2. **Review Examples**: Check the [examples directory](../examples/)
3. **Open an Issue**: Report bugs or request features
4. **Community**: Join our developer community (link coming soon)

---

**Happy Bot Building! 🤖**