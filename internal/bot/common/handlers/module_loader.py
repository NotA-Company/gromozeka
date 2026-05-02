"""
Custom handler module loader for Gromozeka bot, dood!

This module provides dynamic loading of custom handler modules via TOML configuration.
Custom handlers extend BaseBotHandler and are inserted into the handler chain after
built-in handlers but before LLMMessageHandler.
"""

import importlib
import inspect
import logging
import os
import sys
from typing import Any, Dict, List, Tuple

from internal.bot.models import BotProvider
from internal.config.manager import ConfigManager
from internal.database import Database
from lib.ai import LLMManager

from .base import BaseBotHandler
from .manager import HandlerParallelism

logger = logging.getLogger(__name__)

__all__ = ["CustomHandlerLoader", "CustomHandlerLoadError"]

HandlerTuple = Tuple[BaseBotHandler, HandlerParallelism]


class CustomHandlerLoadError(Exception):
    """
    Raised when a custom handler fails to load, dood!

    Attributes:
        handlerId: The id of the handler that failed
        reason: Human-readable description of the failure
    """

    def __init__(self, handlerId: str, reason: str):
        """
        Initialize the custom handler load error, dood!

        Args:
            handlerId: The id of the handler that failed
            reason: Human-readable description of the failure
        """
        self.handlerId = handlerId
        self.reason = reason
        super().__init__(f"Failed to load custom handler '{handlerId}': {reason}")


class CustomHandlerLoader:
    """
    Loader for custom bot handlers from configuration, dood!

    This class reads handler definitions from the TOML config and dynamically loads
    them from either Python import paths or local module files. Each handler is
    validated and instantiated with the standard four dependencies.

    Attributes:
        configManager: Configuration manager instance
        database: Database wrapper for persistence
        llmManager: LLM manager for AI features
        botProvider: Bot provider type
        modulesDir: Directory path for local handler modules
    """

    def __init__(
        self,
        configManager: ConfigManager,
        database: Database,
        llmManager: LLMManager,
        botProvider: BotProvider,
    ):
        """
        Initialize the custom handler loader, dood!

        Args:
            configManager: Configuration manager providing bot settings
            database: Database wrapper for data persistence
            llmManager: LLM manager for AI model operations
            botProvider: Bot provider type (Telegram/Max)
        """
        self.configManager = configManager
        self.database = database
        self.llmManager = llmManager
        self.botProvider = botProvider
        self.modulesDir: str = ""

    def loadAll(self) -> List[HandlerTuple]:
        """
        Load all enabled custom handlers from config, sorted by order, dood!

        Reads the custom-handlers section from config, validates and loads each
        enabled handler, then returns them sorted by the order field. Individual
        handler failures are logged but don't prevent other handlers from loading.

        Returns:
            List of HandlerTuple - handler instances paired with parallelism settings
        """
        # Read config section
        customHandlersConfig = self.configManager.get("custom-handlers", {})

        # Check if enabled
        if not customHandlersConfig.get("enabled", False):
            logger.debug("Custom handlers are disabled in config")
            return []

        # Get modules directory
        self.modulesDir = customHandlersConfig.get("modules-dir", "modules")

        # Add modules directory to sys.path if it exists and not already there
        if os.path.isdir(self.modulesDir):
            absModulesDir = os.path.abspath(self.modulesDir)
            if absModulesDir not in sys.path:
                sys.path.insert(0, absModulesDir)
                logger.debug(f"Added {absModulesDir} to sys.path")
        else:
            logger.warning(f"Modules directory '{self.modulesDir}' does not exist")

        # Get handlers list
        handlerConfigs = customHandlersConfig.get("handlers", [])
        if not handlerConfigs:
            logger.info("No custom handlers configured")
            return []

        # Load each handler
        loadedHandlers: List[Tuple[HandlerTuple, int]] = []
        for idx, handlerConfig in enumerate(handlerConfigs):
            # Skip disabled handlers
            if not handlerConfig.get("enabled", True):
                handlerId = handlerConfig.get("id", f"handler-{idx}")
                logger.debug(f"Skipping disabled custom handler '{handlerId}'")
                continue

            # Try to load single handler
            try:
                handlerTuple = self._loadSingle(handlerConfig, idx)
                order = handlerConfig.get("order", 100)
                loadedHandlers.append((handlerTuple, order))
            except CustomHandlerLoadError as e:
                logger.error(f"{e}", exc_info=False)
            except Exception as e:
                handlerId = handlerConfig.get("id", f"handler-{idx}")
                logger.error(f"Unexpected error loading custom handler '{handlerId}': {e}", exc_info=True)

        # Sort by order field (stable sort)
        loadedHandlers.sort(key=lambda x: x[1])

        # Extract just the handler tuples
        result = [ht for ht, _ in loadedHandlers]

        if result:
            logger.info(f"Successfully loaded {len(result)} custom handler(s)")

        return result

    def _loadSingle(self, handlerConfig: Dict[str, Any], idx: int) -> HandlerTuple:
        """
        Load a single custom handler from its config entry, dood!

        Args:
            handlerConfig: Dict with handler configuration from TOML
            idx: Index of handler in config list (for fallback identification)

        Returns:
            HandlerTuple with instantiated handler and parallelism

        Raises:
            CustomHandlerLoadError: On any loading/validation failure
        """
        # Get handler ID for logging
        handlerId = handlerConfig.get("id", f"handler-{idx}")

        # Validate required fields
        if "id" not in handlerConfig:
            raise CustomHandlerLoadError(handlerId, "Missing required field 'id'")

        importPath = handlerConfig.get("import-path")
        moduleFile = handlerConfig.get("module")

        # Validate exactly one source is set
        if not importPath and not moduleFile:
            raise CustomHandlerLoadError(handlerId, "Must specify either 'import-path' or 'module'")

        if importPath and moduleFile:
            raise CustomHandlerLoadError(handlerId, "Cannot specify both 'import-path' and 'module'")

        # Load the handler class
        try:
            if importPath:
                handlerClass = self._importFromPath(importPath, handlerConfig, handlerId)
            elif moduleFile:
                handlerClass = self._importFromLocalModule(moduleFile, handlerConfig, handlerId)
            else:
                raise CustomHandlerLoadError(handlerId, "No source specified")
        except ImportError as e:
            raise CustomHandlerLoadError(handlerId, f"Import error: {e}")
        except AttributeError as e:
            raise CustomHandlerLoadError(handlerId, f"Class not found: {e}")

        # Validate the class
        self._validateHandlerClass(handlerClass, handlerId)

        # Instantiate the handler
        try:
            handlerInstance = handlerClass(
                self.configManager,
                self.database,
                self.llmManager,
                self.botProvider,
            )
        except Exception as e:
            raise CustomHandlerLoadError(handlerId, f"Instantiation failed: {e}")

        # Resolve parallelism
        parallelismStr = handlerConfig.get("parallelism", "parallel").lower()
        if parallelismStr == "sequential":
            parallelism = HandlerParallelism.SEQUENTIAL
        elif parallelismStr == "parallel":
            parallelism = HandlerParallelism.PARALLEL
        else:
            logger.warning(
                f"Invalid parallelism value '{parallelismStr}' for handler '{handlerId}', defaulting to PARALLEL"
            )
            parallelism = HandlerParallelism.PARALLEL

        logger.info(f"Loaded custom handler '{handlerId}' ({handlerClass.__name__}, {parallelismStr})")

        return (handlerInstance, parallelism)

    def _importFromPath(self, importPath: str, handlerConfig: Dict[str, Any], handlerId: str) -> type:
        """
        Import handler class from a fully qualified Python import path, dood!

        Args:
            importPath: Full dotted path like 'my_package.handlers.MyHandler'
            handlerConfig: Handler configuration dict
            handlerId: Handler identifier for error messages

        Returns:
            Handler class type

        Raises:
            ImportError: If module cannot be imported
            AttributeError: If class cannot be found in module
        """
        # Split into module path and class name
        parts = importPath.rsplit(".", 1)
        if len(parts) == 1:
            # No dots - treat as class name in current module (unlikely but handle it)
            raise ImportError(f"Invalid import path '{importPath}' - must be fully qualified")

        modulePath, defaultClassName = parts

        # Allow explicit class override
        className = handlerConfig.get("class", defaultClassName)

        # Import the module
        module = importlib.import_module(modulePath)

        # Get the class
        handlerClass = getattr(module, className)

        return handlerClass

    def _importFromLocalModule(self, moduleFile: str, handlerConfig: Dict[str, Any], handlerId: str) -> type:
        """
        Import handler class from a local module file, dood!

        Args:
            moduleFile: Module filename without .py extension
            handlerConfig: Handler configuration dict
            handlerId: Handler identifier for error messages

        Returns:
            Handler class type

        Raises:
            ImportError: If module cannot be imported
            AttributeError: If class cannot be found in module
            CustomHandlerLoadError: If class field is missing
        """
        # Require explicit class name for local modules
        if "class" not in handlerConfig:
            raise CustomHandlerLoadError(handlerId, "Field 'class' is required when using 'module'")

        className = handlerConfig["class"]

        # Import the module by name (requires modules-dir in sys.path)
        module = importlib.import_module(moduleFile)

        # Get the class
        handlerClass = getattr(module, className)

        return handlerClass

    def _validateHandlerClass(self, handlerClass: type, handlerId: str) -> None:
        """
        Validate that the loaded class is a proper BaseBotHandler subclass, dood!

        Args:
            handlerClass: The class to validate
            handlerId: Handler identifier for error messages

        Raises:
            CustomHandlerLoadError: If validation fails
        """
        # Check it's a class
        if not inspect.isclass(handlerClass):
            raise CustomHandlerLoadError(handlerId, f"Expected a class, got {type(handlerClass)}")

        # Check it extends BaseBotHandler
        if not issubclass(handlerClass, BaseBotHandler):
            raise CustomHandlerLoadError(handlerId, f"{handlerClass.__name__} does not extend BaseBotHandler")

        # Check constructor signature
        try:
            sig = inspect.signature(handlerClass.__init__)
            params = list(sig.parameters.keys())

            # Should have: self, configManager, database, llmManager, botProvider
            if len(params) < 5:
                expectedSig = "(self, configManager, database, llmManager, botProvider)"
                raise CustomHandlerLoadError(
                    handlerId,
                    f"Constructor signature mismatch - expected {expectedSig}, got {params}",
                )
        except Exception as e:
            logger.warning(f"Could not validate constructor signature for '{handlerId}': {e}")
            # Don't fail on signature check - allow it to fail during instantiation if wrong
