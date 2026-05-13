# Gromozeka - Multi-Platform AI Bot

Gromozeka is a powerful production-ready, AI-powered bot supporting both Telegram and Max Messenger platforms. Built with Python 3.12+, it features natural language processing, multi-provider LLM support, image generation and analysis, spam filtering, weather integration, web search, and comprehensive chat management capabilities, dood!

## 🚀 Features

### Core AI Capabilities
- **🤖 Multi-Provider LLM Support**: OpenRouter, Yandex Cloud (SDK & OpenAI-compatible), OpenAI
- **🧠 Context-Aware Conversations**: Natural language interactions with conversation history
- **🛠️ AI Tool Calling**: Function calling support for extended capabilities
- **🔄 Provider Fallback**: Automatic failover between AI providers
- **🖼️ Image Generation**: Generate images from text prompts using various AI models
- **🔍 Image Analysis**: Analyze and describe images, stickers, and visual content

### Platform Support
- **📱 Telegram**: Full support including forums/topics, inline keyboards, media handling
- **💬 Max Messenger**: Complete OpenAPI-compliant client implementation
- **🔌 Extensible Architecture**: Abstract base classes for easy platform additions

### Advanced Features
- **🛡️ ML-Powered Spam Detection**: Naive Bayes classifier with learning capabilities
- **☀️ Weather Integration**: Real-time weather via OpenWeatherMap with geocoding
- **🔍 Web Search**: Yandex Search integration with caching and rate limiting
- **📝 Chat Summarization**: Summarize conversations and topics
- **💾 User Data Management**: Persistent user preferences and context storage
- **⚙️ Interactive Configuration**: Wizard-based chat settings with 30+ options
- **📊 Topic/Thread Management**: Telegram forum support with per-topic settings

### Infrastructure
- **🎛️ Flexible Configuration**: TOML-based with hierarchical overrides
- **📊 Database Management**: SQLite with migration system (15+ tables)
- **⚡ Rate Limiting**: Sliding window algorithm with multiple queues
- **💾 Multi-Layer Caching**: Generic cache interface with TTL support
- **🔄 Queue Service**: Background task processing with delayed actions
- **📝 Comprehensive Logging**: Structured logging with rotation

## 🏗️ Architecture

### High-Level Overview
```
┌─────────────────────────────────────────────────────────────┐
│                     GromozekBot (main.py)                    │
│                    Orchestrator & Entry Point                │
└─────────────────────────────────────────────────────────────┘
                              │
                ┌─────────────┴─────────────┐
                │                           │
        ┌───────▼────────┐         ┌───────▼────────┐
        │  TelegramApp   │         │    MaxApp      │
        │  (Platform)    │         │  (Platform)    │
        └───────┬────────┘         └───────┬────────┘
                │                           │
                └─────────────┬─────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Handler Manager   │
                    │  (Route & Execute) │
                    └─────────┬──────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
┌───────▼────────┐   ┌────────▼────────┐   ┌──────▼──────┐
│  LLM Service   │   │  Cache Service  │   │Queue Service│
│ (AI Provider)  │   │  (Multi-Layer)  │   │(Background) │
└───────┬────────┘   └────────┬────────┘   └──────┬──────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Database Layer    │
                    │  (SQLite + ORM)    │
                    └────────────────────┘
```

### Key Components

**Entry Point**: [`main.py`](main.py:1)
- [`GromozekBot`](main.py:31) orchestrator class
- Platform initialization and lifecycle management
- Configuration loading and validation

**Platform Layer**: [`internal/bot/`](internal/bot/)
- [`TelegramApplication`](internal/bot/telegram/application.py:1) - Telegram bot implementation
- [`MaxApplication`](internal/bot/max/application.py:1) - Max Messenger bot implementation
- [`CommonBot`](internal/bot/common/bot.py:1) - Abstract base class for platforms

**Handler System**: [`internal/bot/common/handlers/`](internal/bot/common/handlers/)
- [`HandlerManager`](internal/bot/common/handlers/manager.py:1) - Route and execute handlers
- Permission-based access control
- Command and message routing

**Service Layer**: [`internal/services/`](internal/services/)
- [`LLMService`](internal/services/llm/service.py:1) - AI provider management
- [`CacheService`](internal/services/cache/service.py:1) - Multi-layer caching
- [`QueueService`](internal/services/queue_service/service.py:1) - Background tasks

**Database Layer**: [`internal/database/`](internal/database/)
- [`DatabaseWrapper`](internal/database/wrapper.py:1) - SQLite abstraction
- [`DatabaseManager`](internal/database/manager.py:1) - High-level operations
- Migration system with 15+ tables

**Library Components**: [`lib/`](lib/)
- [`AIManager`](lib/ai/manager.py:1) - Multi-provider LLM with tool calling
- [`RateLimiter`](lib/rate_limiter/manager.py:1) - Sliding window rate limiting
- [`MaxBotClient`](lib/max_bot/client.py:1) - Max Messenger API client
- [`OpenWeatherMapClient`](lib/openweathermap/client.py:1) - Weather API client
- [`YandexSearchClient`](lib/yandex_search/client.py:1) - Search API client
- [`BayesFilter`](lib/bayes_filter/bayes_filter.py:1) - Spam detection

## 📋 Requirements

- **Python**: 3.12 or higher
- **SQLite3**: Database engine
- **libmagic**: File type detection (tested on 5.46+)
- **Platform Tokens**:
  - Telegram Bot Token (from [@BotFather](https://t.me/botfather))
  - Max Messenger Bot Token (from Max platform)
- **Optional API Keys**:
  - OpenWeatherMap API key (weather features)
  - Yandex Search API key (web search)
  - AI provider keys (OpenRouter, Yandex Cloud, OpenAI)

## 🛠️ Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd gromozeka
   ```

2. **Create virtual environment:**
   ```bash
   python3.12 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Create configuration file:**
   ```bash
   cp configs/00-defaults/00-config.toml config.toml
   # Edit config.toml with your settings
   ```

5. **Configure bot tokens and API keys:**
   Edit [`config.toml`](config.toml:1) and add your credentials:
   ```toml
   [bot]
   bot_token = "YOUR_TELEGRAM_BOT_TOKEN"
   bot_owners = ["your_username"]
   
   [max]
   enabled = true
   bot_token = "YOUR_MAX_BOT_TOKEN"
   
   [openweathermap]
   enabled = true
   api-key = "YOUR_OPENWEATHERMAP_KEY"
   
   # Add your AI provider configuration
   ```

## ⚙️ Configuration

### Configuration System

Gromozeka uses a hierarchical TOML-based configuration system:

1. **Default configs**: [`configs/00-defaults/`](configs/00-defaults/)
2. **Main config**: [`config.toml`](config.toml:1) (user-created)
3. **Additional config directories**: Via `--config-dir` flag
4. **Per-chat settings**: Stored in database, configurable via `/configure`

### Main Configuration Structure

```toml
[bot]
bot_token = "YOUR_TELEGRAM_TOKEN"
bot_owners = ["username1", "username2"]
defaults = {
    chat-model = "gpt-4o-mini",
    parse-images = true,
    detect-spam = true,
    random-answer-probability = 0.01,
    enable-yandex-search = true
}

[max]
enabled = true
bot_token = "YOUR_MAX_TOKEN"

[database]
database_path = "gromozeka.db"

[logging]
log_level = "INFO"
log_file = "logs/bot.log"

[openweathermap]
enabled = true
api-key = "YOUR_API_KEY"
default-language = "en"

[yandex-search]
enabled = true
api-key = "YOUR_YANDEX_KEY"
user-id = "YOUR_USER_ID"
```

### AI Provider Configuration

Configure AI providers in [`configs/00-defaults/providers.toml`](configs/00-defaults/providers.toml:1):

```toml
[[models]]
name = "gpt-4o-mini"
type = "openai"
model_id = "gpt-4o-mini"
temperature = 0.7
context_size = 128000
supports_tools = true
supports_vision = true
```

### Per-Chat Settings

Each chat can have 30+ configurable settings accessible via `/configure`:
- AI model selection
- Response behavior (random replies, mention detection)
- Feature toggles (spam detection, image parsing, search)
- Spam thresholds and actions
- Topic-specific settings (Telegram forums)

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

### Using Makefile
```bash
make run          # Run the bot
make format       # Format code with ruff
make lint         # Lint code
make test         # Run all tests (976+ tests)
```

## 📝 Bot Commands

### General Commands
- `/start` - Start interaction with the bot
- `/help` - Show available commands and usage
- `/echo <message>` - Echo back the message

### AI & Conversation
- **Natural conversation** - Just talk to the bot (mention it or reply to its messages)
- `/analyze <prompt>` - Analyze media with custom prompt (reply to image/sticker)
- `/draw [prompt]` - Generate image from text prompt
- `/summary [messages] [chatId] [topicId]` - Summarize chat messages
- `/topic_summary [messages]` - Summarize current topic (Telegram forums)

### Utilities
- `/weather <city> [country]` - Get weather information with forecast
- `/search <query>` - Search the web using Yandex Search
- `/remind <time> [message]` - Set a delayed reminder
- `/configure` - Interactive chat configuration wizard
- `/list_chats [all]` - List available chats

### Divination (optional, off by default — set `[divination] enabled = true`)
- `/taro <layout> <question>` (aliases: `/tarot`, `/таро`) - Tarot reading; layouts: `one_card`, `three_card`, `celtic_cross`, `relationship`, `yes_no`
- `/runes <layout> <question>` (aliases: `/rune`, `/руны`) - Rune reading; layouts: `one_rune`, `three_runes`, `five_runes`, `nine_runes`

### User Data Management
- `/get_my_data` - Display all stored user data
- `/delete_my_data <key>` - Delete specific user data entry
- `/clear_my_data` - Clear all user data (requires confirmation)

### Spam Management (Admin Only)
- `/spam` - Mark replied message as spam and ban user
- `/pretrain_bayes [chatId]` - Train Bayes filter on chat history
- `/learn_spam [chatId]` - Teach filter that message is spam
- `/learn_ham [chatId]` - Teach filter that message is not spam
- `/get_spam_score [chatId]` - Check spam probability of message
- `/unban [@username]` - Unban user from chat

### Bot Owner Commands
- `/models` - List all available AI models
- `/settings [debug]` - Show current chat settings
- `/set <key> <value>` - Set chat configuration value
- `/unset <key>` - Reset setting to default
- `/test <suite> [args]` - Run test suites

## 🔧 Development

### Code Style

- **Variables/Functions/Methods**: camelCase (e.g., `getUserData()`)
- **Classes**: PascalCase (e.g., `DatabaseManager`)
- **Constants**: UPPER_CASE (e.g., `MAX_RETRIES`)
- **Docstrings**: Concise but complete (all args and return types)

### Development Workflow

```bash
# Format and lint before committing
make format lint

# Run tests
make test

# Run specific test file
./venv/bin/python3 -m pytest tests/test_specific.py -v

# Check test coverage
./venv/bin/python3 -m pytest --cov=internal --cov=lib --cov-report=html
```

### Testing

- **976+ tests** with pytest and async support
- **Golden data framework** for API testing
- **Mock fixtures** for external services
- **Integration tests** for end-to-end flows

Test structure:
```
tests/
├── conftest.py              # Shared fixtures
├── fixtures/                # Test fixtures
│   ├── database_fixtures.py
│   ├── service_mocks.py
│   └── telegram_mocks.py
└── openweathermap/golden/   # Golden data tests
```

### Database Migrations

Create new migration:
```bash
python internal/database/migrations/create_migration.py "description_of_changes"
```

Migrations run automatically on startup. See [`internal/database/migrations/`](internal/database/migrations/) for details.

### Adding New Handlers

1. Create handler in [`internal/bot/common/handlers/`](internal/bot/common/handlers/)
2. Inherit from appropriate base class
3. Register in [`HandlerManager`](internal/bot/common/handlers/manager.py:1)
4. Add tests in `tests/`

### Adding New Platforms

1. Create platform directory in [`internal/bot/`](internal/bot/)
2. Implement [`CommonBot`](internal/bot/common/bot.py:1) abstract class
3. Add platform initialization in [`main.py`](main.py:1)
4. Update configuration schema

## 📁 Project Structure

```
gromozeka/
├── main.py                      # Entry point with GromozekBot orchestrator
├── config.toml                  # Main configuration (user-created)
├── requirements.txt             # Python dependencies
├── Makefile                     # Build and run commands
├── pyproject.toml              # Python project configuration
│
├── configs/                     # Configuration templates
│   └── 00-defaults/            # Default configuration files
│       ├── 00-config.toml      # Base configuration
│       ├── bot-defaults.toml   # Bot default settings
│       ├── providers.toml      # AI provider configs
│       └── *-models.toml       # Model definitions
│
├── internal/                    # Core bot implementation
│   ├── bot/                    # Bot application layer
│   │   ├── common/             # Shared bot components
│   │   │   ├── bot.py          # Abstract base class
│   │   │   └── handlers/       # Command and message handlers
│   │   ├── telegram/           # Telegram platform
│   │   │   └── application.py
│   │   ├── max/                # Max Messenger platform
│   │   │   └── application.py
│   │   └── models/             # Data models and enums
│   │
│   ├── config/                 # Configuration management
│   │   └── manager.py          # TOML config loader
│   │
│   ├── database/               # Database layer
│   │   ├── wrapper.py          # SQLite abstraction
│   │   ├── manager.py          # High-level operations
│   │   ├── models.py           # ORM models
│   │   └── migrations/         # Schema migrations
│   │
│   ├── services/               # Service layer
│   │   ├── llm/                # LLM service
│   │   ├── cache/              # Cache service
│   │   └── queue_service/      # Background queue
│   │
│   └── models/                 # Shared models
│
├── lib/                        # Reusable library components
│   ├── ai/                     # AI/LLM management
│   │   ├── manager.py          # Multi-provider manager
│   │   ├── abstract.py         # Provider interface
│   │   └── providers/          # Provider implementations
│   │
│   ├── rate_limiter/           # Rate limiting
│   │   ├── manager.py          # Rate limiter manager
│   │   └── sliding_window.py  # Algorithm implementation
│   │
│   ├── max_bot/                # Max Messenger client
│   │   └── client.py           # OpenAPI-compliant client
│   │
│   ├── openweathermap/         # Weather API client
│   ├── geocode_maps/           # Geocoding client
│   ├── yandex_search/          # Search API client
│   ├── bayes_filter/           # Spam detection
│   └── utils.py                # Shared utilities
│
├── tests/                      # Test suite (976+ tests)
│   ├── conftest.py             # Pytest configuration
│   ├── fixtures/               # Test fixtures
│   └── */golden/               # Golden data tests
│
├── docs/                       # Documentation
│   ├── reports/                # Implementation reports
│   └── templates/              # Document templates
│
└── memory-bank/                # Project context (optional)
    ├── productContext.md       # Project overview
    ├── activeContext.md        # Current work
    ├── progress.md             # Progress tracking
    ├── decisionLog.md          # Architecture decisions
    └── systemPatterns.md       # Design patterns
```

## 🐛 Troubleshooting

### Bot Not Responding
1. Check bot token is correct in [`config.toml`](config.toml:1)
2. Verify bot is not already running: `ps aux | grep main.py`
3. Check logs in `logs/` directory
4. Ensure database has proper permissions
5. Verify platform is enabled in configuration

### Missing Features
1. Verify API keys are configured for optional services
2. Check feature flags in configuration
3. Review chat-specific settings with `/settings`
4. Ensure required dependencies are installed

### Database Issues
1. Check migration status in logs
2. Ensure SQLite3 is properly installed
3. Verify database file permissions
4. Review migrations in [`internal/database/migrations/versions/`](internal/database/migrations/versions/)

### Rate Limiting Issues
1. Check rate limiter configuration
2. Review queue service logs
3. Adjust rate limits in configuration
4. Monitor API quota usage

## 🔒 Security Considerations

- Store sensitive configuration in environment variables or secure files
- Never commit `config.toml` or `config.prod.toml` to version control
- Regularly update dependencies: `pip install --upgrade -r requirements.txt`
- Use bot owner restrictions for administrative commands
- Configure spam thresholds appropriate for your community
- Review and audit chat permissions regularly
- Enable spam detection in public groups
- Use rate limiting to prevent abuse

## 📊 Monitoring

### Logs
- Application logs: `logs/bot.log`
- Error tracking with full stack traces
- Debug mode available via configuration
- Structured logging with context

### Database
- SQLite database at configured path (default: `gromozeka.db`)
- Automatic backups recommended
- Migration history tracked in database
- 15+ tables for comprehensive data storage

### Performance
- Background task queue monitoring
- Delayed action queue for scheduled tasks
- Async processing for long-running operations
- Rate limiter metrics
- Cache hit/miss tracking

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Follow code style guidelines (camelCase, PascalCase, UPPER_CASE)
4. Write tests for new features
5. Run `make format lint test` before committing
6. Commit changes: `git commit -m 'Add amazing feature'`
7. Push to branch: `git push origin feature/amazing-feature`
8. Open Pull Request with detailed description

### Pull Request Guidelines
- Include tests for new functionality
- Update documentation as needed
- Follow existing code patterns
- Ensure all tests pass
- Add entry to appropriate docs/reports/ file

## 📄 License

This project is licensed under the MIT License - see the [`LICENSE`](LICENSE:1) file for details.

## 🙏 Acknowledgments

- Built with [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- AI capabilities powered by OpenAI, Yandex Cloud, and OpenRouter
- Weather data from OpenWeatherMap
- Search powered by Yandex Search API
- Spam filtering using Naive Bayes algorithm
- Max Messenger platform support

## 📮 Support

For issues, questions, or suggestions:
- Create an issue in the repository
- Review documentation in [`docs/`](docs/) directory
- Check Memory Bank files for project context and decisions
- Consult [`TODO.md`](TODO.md:1) for planned enhancements

---

**Note**: This bot is actively developed with new features being added regularly. The project maintains 976+ passing tests and follows production-ready practices including comprehensive error handling, rate limiting, caching, and database migrations, dood!