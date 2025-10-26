# Gromozeka Telegram Bot

A minimal Telegram bot built with Python using the `python-telegram-bot` library, TOML configuration, and SQLite database with an abstraction layer.

## Features

- 🤖 **Minimal Telegram Bot**: Built with `python-telegram-bot` library
- ⚙️ **TOML Configuration**: Easy-to-edit configuration file
- 🗄️ **Database Abstraction**: SQLite wrapper that can be easily replaced
- 📝 **Message Logging**: Stores user messages and statistics
- 🎮 **Prinny Personality**: Responds with "dood!" like a Prinny from Disgaea

## Requirements

- Python 3.12 or higher (required for StrEnum and other modern features)

## Quick Start

### 1. Install Dependencies

```bash
./venv/bin/pip install -r requirements.direct.txt
```

### 2. Configure the Bot

Edit `config.toml` and add your bot token from [@BotFather](https://t.me/BotFather):

```toml
[bot]
token = "YOUR_ACTUAL_BOT_TOKEN_HERE"

[database]
path = "bot_data.db"
max_connections = 5
timeout = 30

[logging]
level = "INFO"
format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

### 3. Test the Setup

```bash
./venv/bin/python test_bot.py
```

### 4. Run the Bot

```bash
./venv/bin/python main.py
```

## Bot Commands

- `/start` - Welcome message and introduction
- `/help` - Show help information
- `/stats` - Display user statistics
- `/echo <message>` - Echo your message back

## Project Structure

```
├── main.py           # Main bot application
├── database.py       # Database wrapper (easily replaceable)
├── config.toml       # Configuration file
├── test_bot.py       # Test script
├── requirements.direct.txt  # Direct dependencies
└── README_BOT.md     # This file
```

## Database Schema

The bot creates three tables:

- **users**: Store user information (ID, username, names, timestamps)
- **settings**: Key-value pairs for bot configuration
- **messages**: Message history for each user

## Customization

### Changing Database Backend

The `DatabaseWrapper` class in `database.py` provides an abstraction layer. To switch to a different database:

1. Implement the same interface in a new wrapper class
2. Replace the import in `main.py`
3. Update configuration as needed

### Adding New Commands

Add new command handlers in the `GromozekBot.setup_handlers()` method:

```python
self.application.add_handler(CommandHandler("newcommand", self.new_command_handler))
```

### Modifying Responses

Edit the response logic in the `handle_message()` method to customize how the bot responds to messages.

## Development

### Running Tests

```bash
./venv/bin/python test_bot.py
```

### Adding Dependencies

Add new dependencies to `requirements.direct.txt` and regenerate `requirements.txt`:

```bash
./venv/bin/pip install new-package
./venv/bin/pip freeze > requirements.txt
```

## Troubleshooting

### Common Issues

1. **Import errors**: Make sure all dependencies are installed with `./venv/bin/pip install -r requirements.direct.txt`
2. **Token errors**: Verify your bot token in `config.toml` is correct
3. **Database errors**: Check file permissions for the database file location

### Getting Help

- Check the logs for detailed error messages
- Run the test script to verify component functionality
- Ensure your bot token is valid and the bot is not already running elsewhere

## License

This project is open source. Feel free to modify and distribute, dood! 🎮