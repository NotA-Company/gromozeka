"""
Bot module for Gromozeka providing multi-platform support.

This module contains the core bot architecture with support for both Telegram and Max messenger platforms.
It includes platform-specific applications, shared handlers, models, and utilities.

Architecture:
- telegram/: Telegram bot implementation using python-telegram-bot
- max/: Max messenger bot implementation using lib.max_bot
- common/: Shared components including handlers, models, and utilities
- models/: Bot-specific data models and enums

Key Components:
- BaseBotHandler: Foundation for all bot handlers with common functionality
- HandlersManager: Manages registration and execution of command handlers
- Shared handlers for weather, search, LLM integration, media processing, and more
"""
