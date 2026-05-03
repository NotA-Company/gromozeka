"""Configuration management module for Gromozeka bot.

This module provides centralized configuration management for the Gromozeka bot system.
It handles loading, merging, and accessing configuration from TOML files with support for
environment variable substitution and multiple configuration directories.

Key features:
- Load configuration from TOML files
- Support for environment variable substitution using ${VAR_NAME} syntax
- Merge configurations from multiple directories
- Type-safe access to configuration sections
- Validation of required configuration values

Main exports:
    ConfigManager: Main class for managing bot configuration
    substituteEnvVars: Function to substitute environment variables in config values

Example:
    >>> from internal.config import ConfigManager
    >>> config = ConfigManager(configPath="config.toml", configDirs=["configs/"])
    >>> bot_token = config.getBotToken()
    >>> db_config = config.getDatabaseConfig()
"""

from internal.config.manager import ConfigManager

__all__ = ["ConfigManager"]
