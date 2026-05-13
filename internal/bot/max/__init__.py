"""Max Messenger platform integration for Gromozeka bot framework.

This module provides the Max Messenger platform-specific implementation for the Gromozeka
bot framework. It handles the integration with Max Messenger's API, manages bot lifecycle,
and processes incoming updates from the Max platform.

The Max platform integration includes:
- Bot application setup and management
- Message handling and routing
- Callback query processing
- Chat member management (add/remove events)
- Rate limiting and task scheduling
- Integration with the common bot handler system

Key Components:
    - MaxBotApplication: Main application class that manages the Max bot lifecycle,
      including initialization, polling, update handling, and shutdown procedures.

Usage:
    The Max bot integration is typically initialized through the main bot application
    factory, which creates a MaxBotApplication instance with the necessary dependencies
    (configuration, database, LLM manager, etc.) and starts the polling loop.

Example:
    ```python
    from internal.bot.max.application import MaxBotApplication
    from internal.config.manager import ConfigManager
    from internal.database import Database
    from lib.ai import LLMManager

    configManager = ConfigManager()
    database = Database(configManager)
    llmManager = LLMManager(configManager)

    botApp = MaxBotApplication(
        configManager=configManager,
        botToken="your_max_bot_token",
        database=database,
        llmManager=llmManager
    )
    botApp.run()
    ```

Platform-Specific Features:
    - Supports Max Messenger's unique update types (MessageCreated, UserAddedToChat, etc.)
    - Handles Max-specific message formats and attachments
    - Integrates with Max's callback query system
    - Supports both private chats and group/channel conversations

Dependencies:
    - lib.max_bot: Max Messenger client library
    - internal.bot.common.handlers: Common handler management system
    - internal.services.queue_service: Task scheduling and queue management
    - lib.rate_limiter: Rate limiting for API calls

Note:
    This module is part of Stage 4 (Bot Platform) in the Gromozeka docstring processing plan.
    It depends on Stage 3 (Bot Core) components for common bot functionality.
"""
