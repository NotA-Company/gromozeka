"""
Handlers package - Different command/message handlers.

This package provides the handler management system for the Telegram bot,
organizing various command and message handlers into a cohesive structure.

The main entry point is the HandlersManager class, which coordinates
registration and execution of different handler types including:
- Spam detection handlers (SpamHandlers)
- Configuration command handlers (ConfigureCommandHandler)
- Summarization handlers (SummarizationHandler)
- Message preprocessors (MessagePreprocessorHandler)
- User data handlers (UserDataHandler)
- Development command handlers (DevCommandsHandler)
- Help command handlers (HelpHandler)
- Weather handlers (WeatherHandler, conditional)
- Main bot handlers (BotHandlers)
- Etc...

Exports:
    HandlersManager: Central manager for coordinating all bot handlers.

Example:
    >>> from internal.bot.handlers import HandlersManager
    >>> from internal.config.manager import ConfigManager
    >>> from internal.database.wrapper import DatabaseWrapper
    >>> from lib.ai.manager import LLMManager
    >>>
    >>> configManager = ConfigManager()
    >>> database = DatabaseWrapper(configManager)
    >>> llmManager = LLMManager(configManager)
    >>>
    >>> manager = HandlersManager(configManager, database, llmManager)
    >>> manager.injectBot(bot)
    >>>
    >>> # Use manager methods to handle updates
    >>> await manager.handle_message(update, context)
    >>> await manager.handle_button(update, context)
"""

from .manager import HandlersManager

__all__ = [
    "HandlersManager",
]
