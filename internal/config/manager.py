"""Configuration management for Gromozeka bot.

This module provides the ConfigManager class and utility functions for loading,
merging, and accessing configuration from TOML files. It supports environment
variable substitution, recursive configuration merging from multiple directories,
and provides typed accessors for various configuration sections.

Key features:
- Load configuration from TOML files
- Recursively merge configurations from multiple directories
- Substitute environment variables in the format ${VAR_NAME}
- Provide typed accessors for bot, database, logging, and other config sections
- Validate required configuration values (e.g., bot token)

Example:
    >>> config_manager = ConfigManager(
    ...     configPath="config.toml",
    ...     configDirs=["configs/00-defaults"],
    ...     dotEnvFile=".env"
    ... )
    >>> bot_token = config_manager.getBotToken()
    >>> db_config = config_manager.getDatabaseConfig()
"""

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import tomli

import lib.utils as utils
from lib.rate_limiter import RateLimiterManagerConfig

logger = logging.getLogger(__name__)


def replaceMatchToEnv(match: re.Match[str]) -> str:
    """Replace environment variable placeholders with actual values.

    Args:
        match: A regex match object containing the environment variable name.

    Returns:
        str: The value of the environment variable or the original placeholder
             if the variable is not set.
    """
    key = match.group(1)
    return os.getenv(key, match.group(0))


def substituteEnvVars(value: Any) -> Any:
    """Recursively substitute environment variable placeholders in configuration values.

    This function processes strings, dictionaries, and lists to replace placeholders
    in the format ${VAR_NAME} with their corresponding environment variable values.

    Args:
        value: The configuration value to process. Can be a string, dict, list, or other type.

    Returns:
        The processed value with environment variables substituted:
        - For strings: returns the string with placeholders replaced
        - For dictionaries: returns a new dict with substituted values
        - For lists: returns a new list with substituted items
        - For other types: returns the original value unchanged
    """
    if isinstance(value, str):
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_-]*)\}", replaceMatchToEnv, value)
    elif isinstance(value, dict):
        return {k: substituteEnvVars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [substituteEnvVars(item) for item in value]
    return value


class ConfigManager:
    """Manages configuration loading and validation for Gromozeka bot.

    This class handles loading configuration from TOML files, merging configurations
    from multiple directories, substituting environment variables, and providing
    typed accessors for various configuration sections. It ensures that required
    configuration values are present and validates the configuration structure.

    Attributes:
        config_path: Path to the main configuration TOML file.
        config_dirs: List of directories to scan for additional configuration files.
        config: The loaded and merged configuration dictionary with environment
            variables substituted.

    Example:
        >>> config_manager = ConfigManager(
        ...     configPath="config.toml",
        ...     configDirs=["configs/00-defaults"],
        ...     dotEnvFile=".env"
        ... )
        >>> bot_token = config_manager.getBotToken()
        >>> db_config = config_manager.getDatabaseConfig()
    """

    __slots__ = ("configPath", "configDirs", "config")

    def __init__(
        self, configPath: str = "config.toml", configDirs: Optional[List[str]] = None, dotEnvFile: str = ".env"
    ) -> None:
        """Initialize ConfigManager with config file path and optional config directories.

        Args:
            configPath: Path to the main configuration TOML file. Defaults to "config.toml".
            configDirs: Optional list of directories to scan for additional .toml config files.
                Files are loaded in sorted order and merged into the main configuration.
                Defaults to None (no additional directories).
            dotEnvFile: Path to the .env file for loading environment variables.
                Defaults to ".env".

        Raises:
            SystemExit: If the configuration file is not found and no config directories
                are provided, or if the bot token is missing from the configuration.
        """
        self.configPath: str = configPath
        self.configDirs: List[str] = configDirs or []
        utils.load_dotenv(path=dotEnvFile)
        self.config: Dict[str, Any] = substituteEnvVars(self._loadConfig())

        rootDir: Optional[str] = self.config.get("application", {}).get("root-dir", None)
        if rootDir is not None:
            os.chdir(rootDir)
            logger.info(f"Changed root directory to {rootDir}")

    def _findTomlFilesRecursive(self, directory: str) -> List[Path]:
        """Recursively find all .toml files in a directory.

        Args:
            directory: The directory path to scan for .toml files.

        Returns:
            A sorted list of Path objects for all .toml files found in the directory
            and its subdirectories. Returns an empty list if the directory does not
            exist or is not a directory.

        Example:
            >>> config_manager = ConfigManager()
            >>> toml_files = config_manager._findTomlFilesRecursive("configs/00-defaults")
            >>> print([f.name for f in toml_files])
            ['bot-defaults.toml', 'providers.toml']
        """
        tomlFiles: List[Path] = []
        dirPath = Path(directory)

        if not dirPath.exists():
            logger.warning(f"Config directory {directory} does not exist, skipping, dood!")
            return tomlFiles

        if not dirPath.is_dir():
            logger.warning(f"Config path {directory} is not a directory, skipping, dood!")
            return tomlFiles

        try:
            # Use rglob to recursively find all .toml files
            for tomlFile in dirPath.rglob("*.toml"):
                if tomlFile.is_file():
                    tomlFiles.append(tomlFile)
                    logger.debug(f"Found config file: {tomlFile}")
        except Exception as e:
            logger.error(f"Error scanning directory {directory}: {e}")

        return sorted(tomlFiles)  # Sort for consistent ordering

    def _mergeConfigs(self, baseConfig: Dict[str, Any], newConfig: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge two configuration dictionaries.

        This method merges new_config into base_config, with nested dictionaries
        being merged recursively. Values in new_config override values in base_config
        for non-dictionary types.

        Args:
            baseConfig: The base configuration dictionary to merge into.
            newConfig: The new configuration dictionary to merge from.

        Returns:
            A new dictionary containing the merged configuration. The original
            base_config is not modified.

        Example:
            >>> base = {"bot": {"token": "abc"}, "logging": {"level": "INFO"}}
            >>> new = {"bot": {"timeout": 30}, "logging": {"level": "DEBUG"}}
            >>> merged = ConfigManager()._mergeConfigs(base, new)
            >>> merged
            {'bot': {'token': 'abc', 'timeout': 30}, 'logging': {'level': 'DEBUG'}}
        """
        merged = baseConfig.copy()

        for key, value in newConfig.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                # Recursively merge nested dictionaries
                merged[key] = self._mergeConfigs(merged[key], value)
            else:
                # Override with new value
                merged[key] = value

        return merged

    def _loadConfig(self) -> Dict[str, Any]:
        """Load configuration from TOML file and optional config directories.

        This method loads the main configuration from a TOML file specified by `self.config_path`.
        If additional configuration directories are provided via `self.config_dirs`, it recursively
        scans those directories for `.toml` files and merges their contents into the main configuration.
        The method ensures that a bot token is present in the final configuration; otherwise, it exits.

        Returns:
            The loaded and merged configuration dictionary.

        Raises:
            SystemExit: If the main configuration file is not found and no config directories are provided,
                        or if the bot token is missing in the configuration,
                        or if an unexpected error occurs during configuration loading.
        """
        # Start with main config file
        configFile = Path(self.configPath)
        hasConfigFile = configFile.exists()
        if not hasConfigFile and not self.configDirs:
            logger.error(f"Configuration file {self.configPath} not found!")
            sys.exit(1)

        try:
            config: Dict[str, Any] = {}
            if hasConfigFile:
                with open(configFile, "rb") as f:
                    config = tomli.load(f)
                logger.info(f"Loaded main config from {self.configPath}")

            # Load and merge configs from directories
            if self.configDirs:
                logger.info(f"Scanning {len(self.configDirs)} config directories for .toml files, dood!")

                for configDir in self.configDirs:
                    tomlFiles = self._findTomlFilesRecursive(configDir)
                    logger.info(f"Found {len(tomlFiles)} .toml files in {configDir}")

                    for tomlFile in tomlFiles:
                        try:
                            with open(tomlFile, "rb") as f:
                                dir_config = tomli.load(f)

                            # Merge this config into the main config
                            config = self._mergeConfigs(config, dir_config)
                            logger.info(f"Merged config from {tomlFile}")

                        except Exception as e:
                            logger.error(f"Failed to load config file {tomlFile}: {e}")
                            # Continue with other files instead of exiting

            # Validate required configuration
            if not config.get("bot", {}).get("token"):
                logger.error("Bot token not found in configuration!")
                sys.exit(1)

            logger.info("Configuration loaded and merged successfully, dood!")
            return config

        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            sys.exit(1)

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key.

        Args:
            key: The configuration key to retrieve. Supports dot notation for nested keys.
            default: The default value to return if the key is not found. Defaults to None.

        Returns:
            The configuration value associated with the key, or the default value if not found.

        Example:
            >>> config_manager = ConfigManager()
            >>> bot_token = config_manager.get("bot.token")
            >>> db_type = config_manager.get("database.type", "sqlite")
        """
        return self.config.get(key, default)

    def getBotConfig(self) -> Dict[str, Any]:
        """Get bot-specific configuration.

        Returns:
            A dictionary containing bot configuration settings including token, timeout,
            and other bot-specific parameters. Returns an empty dict if not configured.

        Example:
            >>> config_manager = ConfigManager()
            >>> bot_config = config_manager.getBotConfig()
            >>> print(bot_config.get("token"))
            'your-bot-token'
        """
        return self.get("bot", {})

    def getDatabaseConfig(self) -> Dict[str, Any]:
        """Get database-specific configuration.

        Returns:
            A dictionary containing database configuration settings including connection
            parameters, pool settings, and other database-specific options.
            Returns an empty dict if not configured.

        Example:
            >>> config_manager = ConfigManager()
            >>> db_config = config_manager.getDatabaseConfig()
            >>> print(db_config.get("type"))
            'postgresql'
        """
        return self.get("database", {})

    def getLoggingConfig(self) -> Dict[str, Any]:
        """Get logging-specific configuration.

        Returns:
            A dictionary containing logging configuration settings including log level,
            format, handlers, and other logging-specific options.
            Returns an empty dict if not configured.

        Example:
            >>> config_manager = ConfigManager()
            >>> logging_config = config_manager.getLoggingConfig()
            >>> print(logging_config.get("level"))
            'INFO'
        """
        return self.get("logging", {})

    def getRateLimiterConfig(self) -> RateLimiterManagerConfig:
        """Get rate limiter-specific configuration.

        Returns:
            A RateLimiterManagerConfig object containing rate limiter settings including
            limits, window sizes, and other rate limiting parameters.
            Returns an empty dict if not configured.

        Example:
            >>> config_manager = ConfigManager()
            >>> rate_limiter_config = config_manager.getRateLimiterConfig()
            >>> print(rate_limiter_config.get("default_limit"))
            100
        """
        return self.get("ratelimiter", {})

    def getGeocodeMapsConfig(self) -> Dict[str, Any]:
        """Get geocode maps configuration.

        Returns:
            A dictionary containing geocode maps service configuration including API keys,
            endpoints, and other geocoding-specific settings.
            Returns an empty dict if not configured.

        Example:
            >>> config_manager = ConfigManager()
            >>> geo_config = config_manager.getGeocodeMapsConfig()
            >>> print(geo_config.get("api_key"))
            'your-api-key'
        """
        return self.get("geocode-maps", {})

    def getModelsConfig(self) -> Dict[str, Any]:
        """Get models configuration for LLM manager.

        Returns:
            A dictionary containing LLM model configurations including model names,
            providers, parameters, and other model-specific settings.
            Returns an empty dict if not configured.

        Example:
            >>> config_manager = ConfigManager()
            >>> models_config = config_manager.getModelsConfig()
            >>> print(models_config.get("default"))
            'gpt-4'
        """
        return self.get("models", {})

    def getBotToken(self) -> str:
        """Get bot token from configuration.

        Returns:
            The bot token string. This method validates that the token is present and
            not a placeholder value.

        Raises:
            SystemExit: If the bot token is missing or set to a placeholder value
                (empty string or "YOUR_BOT_TOKEN_HERE").

        Example:
            >>> config_manager = ConfigManager()
            >>> token = config_manager.getBotToken()
            >>> print(token)
            '123456789:ABCdefGHIjklMNOpqrsTUVwxyz'
        """
        token: str = self.getBotConfig().get("token", "")
        if token in ["", "YOUR_BOT_TOKEN_HERE"]:
            logger.error("Please set your bot token in config.toml!")
            sys.exit(1)
        return token

    def getOpenWeatherMapConfig(self) -> Dict[str, Any]:
        """Get OpenWeatherMap configuration.

        Returns:
            A dictionary containing OpenWeatherMap API configuration including API key,
            cache TTLs, endpoints, and other weather service settings.
            Returns an empty dict if not configured.

        Example:
            >>> config_manager = ConfigManager()
            >>> owm_config = config_manager.getOpenWeatherMapConfig()
            >>> print(owm_config.get("api_key"))
            'your-api-key'
        """
        return self.get("openweathermap", {})

    def getYandexSearchConfig(self) -> Dict[str, Any]:
        """Get Yandex Search configuration.

        Returns:
            A dictionary containing Yandex Search API configuration including API key,
            folder ID, cache settings, and other search service settings.
            Returns an empty dict if not configured.

        Example:
            >>> config_manager = ConfigManager()
            >>> yandex_config = config_manager.getYandexSearchConfig()
            >>> print(yandex_config.get("api_key"))
            'your-api-key'
        """
        return self.get("yandex-search", {})

    def getStorageConfig(self) -> Dict[str, Any]:
        """
        Get storage service configuration.

        Returns a dictionary containing storage backend configuration with the following structure:
        - type: Backend type ("fs", "s3", or "null")
        - fs: Filesystem backend configuration (if type is "fs")
            - base-dir: Base directory path for storage
        - s3: S3 backend configuration (if type is "s3")
            - endpoint: S3 endpoint URL
            - region: AWS region
            - key-id: Access key ID
            - key-secret: Secret access key
            - bucket: S3 bucket name
            - prefix: Optional prefix for all keys

        Returns:
            Dict[str, Any]: Storage configuration dictionary with backend-specific settings.
                           Returns empty dict if storage section is not configured.

        Example return values:
            Filesystem backend:
            {
                "type": "fs",
                "fs": {"base-dir": "./storage/objects"}
            }

            S3 backend:
            {
                "type": "s3",
                "s3": {
                    "endpoint": "https://s3.amazonaws.com",
                    "region": "us-east-1",
                    "key-id": "...",
                    "key-secret": "...",
                    "bucket": "my-bucket",
                    "prefix": "objects/"
                }
            }

            Null backend:
            {
                "type": "null"
            }
        """
        return self.get("storage", {})

    def getStatsConfig(self) -> Dict[str, Any]:
        """Get stats-specific configuration.

        Returns:
            A dictionary containing stats configuration settings including
            enabled flag and future scheduling/retention parameters.
            Returns an empty dict if not configured.

        Example:
            >>> config_manager = ConfigManager()
            >>> stats_config = config_manager.getStatsConfig()
            >>> print(stats_config.get("enabled"))
            False
        """
        return self.get("stats", {})
