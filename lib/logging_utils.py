"""
Logging utilities for Gromozeka bot.
"""
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def getLogLevelByStr(levelStr: str, default: Optional[int] = None) -> Optional[int]:
    """Get log level by string."""
    try:
        return getattr(logging, levelStr.upper())
    except AttributeError:
        logger.error(f"Invalid log level '{levelStr}'")
        return default


def configureLogger(localLogger: logging.Logger, config: Dict[str, Any]) -> None:
    """Configure individual logger from config file settings."""

    if "propagate" in config:
        localLogger.propagate = bool(config["propagate"])

    # Configure log level
    if "level" in config:
        logLevel = getLogLevelByStr(config["level"])
        if logLevel is not None:
            localLogger.setLevel(logLevel)

    logLevel = localLogger.getEffectiveLevel()

    # Create formatter
    logFormat = config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    formatter = logging.Formatter(logFormat)

    # Clear existing handlers to avoid duplicates
    for handler in localLogger.handlers[:]:
        localLogger.removeHandler(handler)

    # Add console handler
    if config.get("console", False):
        consoleLogLevel = logLevel
        if "console-level" in config:
            consoleLogLevel = getLogLevelByStr(config["console-level"], logLevel)
        if consoleLogLevel is None:
            consoleLogLevel = logLevel
        consoleHandler = logging.StreamHandler()
        consoleHandler.setLevel(consoleLogLevel)
        consoleHandler.setFormatter(formatter)
        localLogger.addHandler(consoleHandler)
        logger.info(f"Logging {localLogger.name} to console, logLevel: {consoleLogLevel}")

    # Add file handler if specified
    if "file" in config:
        logFile = config["file"]
        try:
            # Create log directory if it doesn't exist
            logPath = Path(logFile)
            logPath.parent.mkdir(parents=True, exist_ok=True)

            fileLogLevel = logLevel
            if "file-level" in config:
                fileLogLevel = getLogLevelByStr(config["file-level"], logLevel)
            if fileLogLevel is None:
                fileLogLevel = logLevel

            fileHandler: Optional[logging.Handler] = None
            if config.get("rotate", False):
                fileHandler = TimedRotatingFileHandler(
                    filename=logFile,
                    when="midnight",
                    interval=1,
                    backupCount=7,
                    encoding="utf-8",
                )
            else:
                fileHandler = logging.FileHandler(logFile)

            fileHandler.setLevel(fileLogLevel)
            fileHandler.setFormatter(formatter)
            localLogger.addHandler(fileHandler)
            logger.info(f"Logging {localLogger.name} to file: {logFile}, logLevel: {fileLogLevel}")
        except Exception as e:
            logger.error(f"Failed to setup file logging for {localLogger.name}: {e}")


def initLogging(config: Dict[str, Any]) -> None:
    """Configure logging from config file settings."""
    # Configure root logger
    rootLogger = logging.getLogger()
    rootLogger.setLevel(logging.INFO)

    configureLogger(rootLogger, config)
    logLevel = rootLogger.getEffectiveLevel()

    # Set some defaults to prevent spamming in logs
    # Set higher logging level for httpx to avoid all GET and POST requests being logged
    if logLevel < logging.WARNING:
        logging.getLogger("httpx").setLevel(logging.WARNING)

    # Set higher logging level for external components
    if logLevel < logging.WARNING:
        logging.getLogger("httpcore").setLevel(logging.WARNING)
    if logLevel < logging.INFO:
        logging.getLogger("telegram").setLevel(logging.INFO)

    logConfigs = config.get("logger", {})
    for loggerName, loggerConfig in logConfigs.items():
        logger.debug(f"Configuring logger '{loggerName}' with config {loggerConfig}")
        localLogger = logging.getLogger(loggerName)
        configureLogger(localLogger, loggerConfig)

    logger.info(f"Logging configured: root level={logLevel}")