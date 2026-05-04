"""Common bot utilities and components for multi-platform bot implementation.

This package provides shared functionality used across different bot implementations,
including the main bot client, typing management, handlers, and common models.

Key Components:
    - TheBot: Multi-platform bot client supporting Telegram and Max Messenger
    - TypingManager: Manages continuous typing indicators during long-running operations
    - handlers: Collection of message and command handlers
    - models: Common data structures and enums (TypingAction, CallbackButton, UpdateObjectType)

The package enables unified bot operations across different messaging platforms with
consistent interfaces for message handling, media processing, user management, and
administrative functions.

Example:
    To use the bot client:

    >>> from internal.bot.common.bot import TheBot
    >>> from internal.bot.models import BotProvider
    >>>
    >>> bot = TheBot(
    ...     botProvider=BotProvider.TELEGRAM,
    ...     config=config_dict,
    ...     tgBot=telegram_bot_instance
    ... )

    To use typing manager:

    >>> from internal.bot.common.typing_manager import TypingManager
    >>> from internal.bot.common.models import TypingAction
    >>>
    >>> async with TypingManager(
    ...     action=TypingAction.TYPING,
    ...     maxTimeout=30,
    ...     repeatInterval=5
    ... ) as typing:
    ...     await long_running_operation()
"""
