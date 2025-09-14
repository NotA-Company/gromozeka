"""
Configuration management for Gromozeka bot.
"""
import logging
import sys
from pathlib import Path
from typing import Dict, Any
import tomli

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages configuration loading and validation for Gromozeka bot."""

    def __init__(self, config_path: str = "config.toml"):
        """Initialize ConfigManager with config file path."""
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from TOML file."""
        config_file = Path(self.config_path)
        if not config_file.exists():
            logger.error(f"Configuration file {self.config_path} not found!")
            sys.exit(1)

        try:
            with open(config_file, "rb") as f:
                config = tomli.load(f)

            # Validate required configuration
            if not config.get("bot", {}).get("token"):
                logger.error("Bot token not found in configuration!")
                sys.exit(1)

            logger.info("Configuration loaded successfully")
            return config

        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            sys.exit(1)

    def get(self, key: str, default=None) -> Any:
        """Get configuration value by key."""
        return self.config.get(key, default)

    def get_bot_config(self) -> Dict[str, Any]:
        """Get bot-specific configuration."""
        return self.get("bot", {})

    def get_database_config(self) -> Dict[str, Any]:
        """Get database-specific configuration."""
        return self.get("database", {})

    def get_logging_config(self) -> Dict[str, Any]:
        """Get logging-specific configuration."""
        return self.get("logging", {})

    def get_models_config(self) -> Dict[str, Any]:
        """Get models configuration for LLM manager, dood!"""
        return self.get("models", {})

    def get_bot_token(self) -> str:
        """Get bot token from configuration."""
        token = self.get_bot_config().get("token", "")
        if token in ["", "YOUR_BOT_TOKEN_HERE"]:
            logger.error("Please set your bot token in config.toml!")
            sys.exit(1)
        return token