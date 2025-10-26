# Gromozeka - Advanced Telegram Bot

Gromozeka is a powerful, AI-powered Telegram bot with extensive features including natural language processing, image generation, spam filtering, weather integration, and much more, dood!

## 🚀 Features

### Core Capabilities
- **🤖 AI/LLM Integration**: Multiple provider support (OpenRouter, Yandex Cloud, OpenAI)
- **🖼️ Image Generation**: Generate images from text prompts using various AI models
- **🔍 Image Analysis**: Analyze and describe images and stickers
- **🛡️ Spam Protection**: Advanced Bayesian spam filtering with learning capabilities
- **☀️ Weather Integration**: Real-time weather information via OpenWeatherMap
- **📝 Message Summarization**: Summarize chat conversations and topics
- **⏰ Reminder System**: Set delayed reminders
- **💾 User Data Storage**: Persistent user preferences and context
- **🎛️ Flexible Configuration**: TOML-based configuration with per-chat settings
- **📊 Database Management**: SQLite with migration system
- **👹 Daemon Mode**: Run as background service

### Chat Interactions
- Natural conversation support with context awareness
- Reply to bot messages to maintain conversation threads
- Mention detection with custom bot nicknames
- Random message responses (configurable probability)
- Support for private chats and group conversations
- Forum/topic support for Telegram supergroups

## 📋 Prerequisites

- Python 3.12 or higher
- SQLite3
- libmagic (tested on 5.46+)
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- API keys for optional services:
  - OpenWeatherMap API key (for weather features)
  - AI provider API keys (OpenRouter, Yandex Cloud, or OpenAI)

## 🛠️ Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd gromozeka
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Create configuration file:**
   ```bash
   cp configs/00-defaults/config.toml config.toml
   # Edit config.toml with your settings
   ```

5. **Configure bot token and API keys:**
   Edit `config.toml` and add your credentials:
   ```toml
   [bot]
   bot_token = "YOUR_BOT_TOKEN_HERE"
   bot_owners = ["your_username"]

   [openweathermap]
   enabled = true
   api-key = "YOUR_OPENWEATHERMAP_KEY"

   # Add your AI provider configuration
   ```

## 📁 Project Structure

```
gromozeka/
├── main.py                 # Main entry point
├── config.toml            # Main configuration (create from template)
├── requirements.txt       # Python dependencies
├── Makefile              # Build and run commands
├── pyproject.toml        # Python project configuration
│
├── configs/              # Configuration templates
│   └── 00-defaults/     # Default configuration files
│       ├── config.toml
│       ├── openrouter-models.toml
│       ├── providers.toml
│       └── ...
│
├── internal/            # Core bot implementation
│   ├── bot/            # Bot application and handlers
│   │   ├── application.py
│   │   ├── handlers.py
│   │   ├── chat_settings.py
│   │   └── models.py
│   ├── config/         # Configuration management
│   └── database/       # Database layer
│       ├── wrapper.py
│       ├── models.py
│       └── migrations/ # Database migrations
│
├── lib/                # Shared libraries
│   ├── ai/            # AI/LLM providers
│   ├── markdown/      # Markdown processing
│   ├── spam/          # Bayes spam filter
│   ├── openweathermap/# Weather client
│   └── utils.py       # Utility functions
│
├── docs/              # Documentation
│   ├── design/        # Design documents
│   ├── plans/         # Feature plans
│   └── reports/       # Implementation reports
│
└── memory-bank/       # Project context (optional)
    ├── productContext.md
    ├── activeContext.md
    ├── progress.md
    ├── decisionLog.md
    └── systemPatterns.md
```

## 🚀 Usage

### Basic Run
```bash
python main.py
```

### With Custom Configuration
```bash
python main.py -c /path/to/config.toml
```

### With Additional Config Directories
```bash
python main.py --config-dir configs/custom --config-dir configs/local
```

### Daemon Mode (Background Service)
```bash
python main.py --daemon --pid-file gromozeka.pid
```

### Debug Configuration
```bash
python main.py --print-config
```

## 📝 Bot Commands

### General Commands
- `/start` - Start interaction with the bot
- `/help` - Show available commands
- `/echo <message>` - Echo back the message

### AI & Media
- `/analyze <prompt>` - Analyze media with custom prompt (reply to image/sticker)
- `/draw [prompt]` - Generate image from text prompt
- `/summary [messages] [chatId] [topicId]` - Summarize chat messages
- `/topic_summary [messages]` - Summarize current topic

### Utilities
- `/weather <city> [country]` - Get weather information
- `/remind <time> [message]` - Set a reminder
- `/configure` - Interactive chat configuration wizard
- `/list_chats [all]` - List available chats

### User Data
- `/get_my_data` - Display stored user data
- `/delete_my_data <key>` - Delete specific user data
- `/clear_my_data` - Clear all user data

### Spam Management
- `/spam` - Mark replied message as spam (admin only)
- `/pretrain_bayes [chatId]` - Train Bayes filter on chat history
- `/learn_spam [chatId]` - Teach filter that message is spam
- `/learn_ham [chatId]` - Teach filter that message is not spam
- `/get_spam_score [chatId]` - Check spam probability of message
- `/unban [@username]` - Unban user from chat

### Bot Owner Commands
- `/models` - List available AI models
- `/settings [debug]` - Show chat settings
- `/set <key> <value>` - Set chat configuration
- `/unset <key>` - Reset setting to default
- `/test <suite> [args]` - Run test suites

## ⚙️ Configuration

### Main Configuration (`config.toml`)
```toml
[bot]
bot_token = "YOUR_BOT_TOKEN"
bot_owners = ["username1", "username2"]
# Default chat settings
defaults = {
    chat-model = "gpt-4o-mini",
    parse-images = true,
    detect-spam = true,
    random-answer-probability = 0.01
}

[database]
database_path = "gromozeka.db"

[logging]
log_level = "INFO"
log_file = "logs/bot.log"

[openweathermap]
enabled = true
api-key = "YOUR_API_KEY"
default-language = "ru"
```

### AI Provider Configuration
Configure your AI providers in separate TOML files or in the main config:

```toml
[[models]]
name = "gpt-4o-mini"
type = "openai"
model_id = "gpt-4o-mini"
temperature = 0.7
context_size = 128000
```

## 🔧 Development

### Setting Up Development Environment
```bash
# Format code
make format

# Lint code
make lint
```

### Database Migrations
The bot uses a migration system for database schema updates:

```bash
# Create new migration
python internal/database/migrations/create_migration.py "description_of_changes"

# Migrations run automatically on startup
```

## 🐛 Troubleshooting

### Bot Not Responding
1. Check bot token is correct
2. Verify bot is not already running (`ps aux | grep main.py`)
3. Check logs in `logs/` directory
4. Ensure database has proper permissions

### Missing Features
1. Verify API keys are configured for optional services
2. Check feature flags in configuration
3. Review chat-specific settings with `/settings`

### Database Issues
1. Delete `gromozeka.db` to start fresh (WARNING: loses all data)
2. Check migrations in `internal/database/migrations/versions/`
3. Ensure SQLite3 is properly installed

## 🔒 Security Considerations

- Store sensitive configuration in environment variables or secure files
- Regularly update dependencies: `pip install --upgrade -r requirements.txt`
- Use bot owner restrictions for administrative commands
- Configure spam thresholds appropriate for your community
- Review and audit chat permissions regularly

## 📊 Monitoring

### Logs
- Application logs: `logs/bot.log`
- Error tracking in logs with full stack traces
- Debug mode available via configuration

### Database
- SQLite database at configured path (default: `gromozeka.db`)
- Automatic backups recommended
- Migration history tracked in database

### Performance
- Background task queue monitoring
- Delayed action queue for scheduled tasks
- Async processing for long-running operations

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- AI capabilities powered by OpenAI, Yandex Cloud, and OpenRouter
- Weather data from OpenWeatherMap
- Spam filtering using Naive Bayes algorithm
- Markdown processing with custom MarkdownV2 renderer

## 📮 Support

For issues, questions, or suggestions:
- Create an issue in the SourceCraft repository
- Review documentation in `docs/` directory
- Check Memory Bank files for project context and decisions

---

**Note**: This bot is actively developed with new features being added regularly. Check the `TODO.md` file for planned enhancements and the Memory Bank for detailed project context, dood!