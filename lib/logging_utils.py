"""
Logging utilities for Gromozeka bot.
"""
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


def init_logger(logging_config: Dict[str, Any]) -> None:
    """Configure logging from config file settings."""
    # Get log level from config (default to INFO)
    log_level = logging_config.get("level", "INFO").upper()
    try:
        level = getattr(logging, log_level)
    except AttributeError:
        logger.warning(f"Invalid log level '{log_level}', using INFO")
        level = logging.INFO

    # Get log format from config (use existing default if not specified)
    log_format = logging_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Get log file path from config (optional)
    log_file = logging_config.get("file")

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create formatter
    formatter = logging.Formatter(log_format)

    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Add file handler if specified
    if log_file:
        try:
            # Create log directory if it doesn't exist
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
            logger.info(f"Logging to file: {log_file}")
        except Exception as e:
            logger.error(f"Failed to setup file logging: {e}")

    # Set higher logging level for httpx to avoid all GET and POST requests being logged
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger.info(f"Logging configured: level={log_level}, format='{log_format}'" +
               (f", file={log_file}" if log_file else ""))