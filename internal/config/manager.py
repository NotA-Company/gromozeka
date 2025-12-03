"""
Configuration management for Gromozeka bot.
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
    """Manages configuration loading and validation for Gromozeka bot."""

    def __init__(
        self, configPath: str = "config.toml", configDirs: Optional[List[str]] = None, dotEnvFile: str = ".env"
    ):
        """Initialize ConfigManager with config file path and optional config directories."""
        self.config_path = configPath
        self.config_dirs = configDirs or []
        utils.load_dotenv(path=dotEnvFile)
        self.config = substituteEnvVars(self._loadConfig())

        rootDir = self.config.get("application", {}).get("root-dir", None)
        if rootDir is not None:
            os.chdir(rootDir)
            logger.info(f"Changed root directory to {rootDir}")

    def _findTomlFilesRecursive(self, directory: str) -> List[Path]:
        """Recursively find all .toml files in a directory, dood!"""
        toml_files = []
        dir_path = Path(directory)

        if not dir_path.exists():
            logger.warning(f"Config directory {directory} does not exist, skipping, dood!")
            return toml_files

        if not dir_path.is_dir():
            logger.warning(f"Config path {directory} is not a directory, skipping, dood!")
            return toml_files

        try:
            # Use rglob to recursively find all .toml files
            for toml_file in dir_path.rglob("*.toml"):
                if toml_file.is_file():
                    toml_files.append(toml_file)
                    logger.debug(f"Found config file: {toml_file}")
        except Exception as e:
            logger.error(f"Error scanning directory {directory}: {e}")

        return sorted(toml_files)  # Sort for consistent ordering

    def _mergeConfigs(self, base_config: Dict[str, Any], new_config: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge two configuration dictionaries, dood!"""
        merged = base_config.copy()

        for key, value in new_config.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                # Recursively merge nested dictionaries
                merged[key] = self._mergeConfigs(merged[key], value)
            else:
                # Override with new value
                merged[key] = value

        return merged

    """
    Load configuration from a TOML file and optional configuration directories.

    This method loads the main configuration from a TOML file specified by `self.config_path`.
    If additional configuration directories are provided via `self.config_dirs`, it recursively
    scans those directories for `.toml` files and merges their contents into the main configuration.
    The method ensures that a bot token is present in the final configuration; otherwise, it exits.

    Returns:
        Dict[str, Any]: The loaded and merged configuration dictionary.

    Raises:
        SystemExit: If the main configuration file is not found and no config directories are provided,
                    or if the bot token is missing in the configuration,
                    or if an unexpected error occurs during configuration loading.
    """

    def _loadConfig(self) -> Dict[str, Any]:
        """Load configuration from TOML file and optional config directories."""
        # Start with main config file
        config_file = Path(self.config_path)
        hasConfigFile = config_file.exists()
        if not hasConfigFile and not self.config_dirs:
            logger.error(f"Configuration file {self.config_path} not found!")
            sys.exit(1)

        try:
            config: Dict[str, Any] = {}
            if hasConfigFile:
                with open(config_file, "rb") as f:
                    config = tomli.load(f)
                logger.info(f"Loaded main config from {self.config_path}")

            # Load and merge configs from directories
            if self.config_dirs:
                logger.info(f"Scanning {len(self.config_dirs)} config directories for .toml files, dood!")

                for config_dir in self.config_dirs:
                    toml_files = self._findTomlFilesRecursive(config_dir)
                    logger.info(f"Found {len(toml_files)} .toml files in {config_dir}")

                    for toml_file in toml_files:
                        try:
                            with open(toml_file, "rb") as f:
                                dir_config = tomli.load(f)

                            # Merge this config into the main config
                            config = self._mergeConfigs(config, dir_config)
                            logger.info(f"Merged config from {toml_file}")

                        except Exception as e:
                            logger.error(f"Failed to load config file {toml_file}: {e}")
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

    def get(self, key: str, default=None) -> Any:
        """Get configuration value by key."""
        return self.config.get(key, default)

    def getBotConfig(self) -> Dict[str, Any]:
        """Get bot-specific configuration."""
        return self.get("bot", {})

    def getDatabaseConfig(self) -> Dict[str, Any]:
        """Get database-specific configuration."""
        return self.get("database", {})

    def getLoggingConfig(self) -> Dict[str, Any]:
        """Get logging-specific configuration."""
        return self.get("logging", {})

    def getRateLimiterConfig(self) -> RateLimiterManagerConfig:
        """Get ratelimiter-specific configuration."""
        return self.get("ratelimiter", {})

    def getGeocodeMapsConfig(self) -> Dict[str, Any]:
        """Get geocode maps configuration."""
        return self.get("geocode-maps", {})

    def getModelsConfig(self) -> Dict[str, Any]:
        """Get models configuration for LLM manager, dood!"""
        return self.get("models", {})

    def getBotToken(self) -> str:
        """Get bot token from configuration."""
        token = self.getBotConfig().get("token", "")
        if token in ["", "YOUR_BOT_TOKEN_HERE"]:
            logger.error("Please set your bot token in config.toml!")
            sys.exit(1)
        return token

    def getOpenWeatherMapConfig(self) -> Dict[str, Any]:
        """
        Get OpenWeatherMap configuration

        Returns:
            Dict with OpenWeatherMap settings (api_key, ttls, etc.)
        """
        return self.get("openweathermap", {})

    def getYandexSearchConfig(self) -> Dict[str, Any]:
        """
        Get Yandex Search configuration

        Returns:
            Dict with Yandex Search settings (api-key, cache settings, etc.)
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
