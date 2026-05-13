"""LLM Manager module for coordinating multiple LLM providers and models.

This module provides the LLMManager class which serves as a central coordinator
for managing multiple LLM providers (Yandex Cloud, OpenRouter, custom OpenAI, etc.)
and their associated models. It handles provider initialization, model registration,
and provides a unified interface for accessing models and providers.

The manager supports:
- Multiple provider types (YC OpenAI, OpenRouter, YC SDK, Custom OpenAI)
- Dynamic model registration from configuration
- JSON logging for model interactions
- Provider and model discovery and retrieval

Example:
    config = {
        "providers": {
            "yc-provider": {
                "type": "yc-openai",
                "api_key": "your-api-key"
            }
        },
        "models": {
            "gpt-4": {
                "provider": "yc-provider",
                "model_id": "gpt-4",
                "temperature": 0.7
            }
        }
    }
    manager = LLMManager(config)
    model = manager.getModel("gpt-4")
"""

import logging
from typing import Any, Dict, List, Optional

from lib.stats import NullStatsStorage, StatsStorage

from .abstract import AbstractLLMProvider, AbstractModel
from .providers.custom_openai_provider import CustomOpenAIProvider
from .providers.openrouter_provider import OpenrouterProvider
from .providers.yc_openai_provider import YcOpenaiProvider
from .providers.yc_sdk_provider import YcAIProvider

logger = logging.getLogger(__name__)


class LLMManager:
    """Manager for coordinating multiple LLM providers and their models.

    The LLMManager serves as a central point for managing LLM providers and models.
    It initializes providers from configuration, registers models, and provides
    methods to retrieve models and providers by name.

    Attributes:
        config: Configuration dictionary containing providers and models settings.
        providers: Dictionary mapping provider names to AbstractLLMProvider instances.
        modelRegistry: Dictionary mapping model names to their provider names.

    Example:
        manager = LLMManager(config)
        model = manager.getModel("gpt-4")
        if model:
            response = model.generate("Hello, world!")
    """

    def __init__(self, config: Dict[str, Any], *, statsStorage: Optional[StatsStorage] = None) -> None:
        """Initialize the LLM manager with configuration.

        Args:
            config: Configuration dictionary with the following structure:
                - providers: Dict of provider configurations
                - models: Dict of model configurations
                - json-logging: Optional JSON logging settings
            statsStorage: Optional stats storage for recording LLM usage statistics.
                When provided, will be set on every model via model.statsStorage.

        Raises:
            ValueError: If provider configuration is invalid.
        """
        self.config: Dict[str, Any] = config
        self.statsStorage: StatsStorage = statsStorage if statsStorage is not None else NullStatsStorage()
        self.providers: Dict[str, AbstractLLMProvider] = {}
        self.modelRegistry: Dict[str, str] = {}  # model_name -> provider_name

        # Initialize providers
        self._initProviders()

        # Add models from config
        self._initModels()

    def _initProviders(self) -> None:
        """Initialize all configured LLM providers.

        Reads provider configurations from self.config and instantiates the
        appropriate provider classes. Supported provider types:
        - yc-openai: Yandex Cloud OpenAI-compatible API
        - openrouter: OpenRouter API
        - yc-sdk: Yandex Cloud SDK provider
        - custom-openai: Custom OpenAI-compatible endpoint

        Logs errors for failed provider initializations but continues with
        successfully initialized providers.

        Raises:
            ValueError: If provider type is not specified or unknown.
        """
        providers_config: Dict[str, Dict[str, Any]] = self.config.get("providers", {})

        providerTypes: Dict[str, type[AbstractLLMProvider]] = {
            "yc-openai": YcOpenaiProvider,
            "openrouter": OpenrouterProvider,
            "yc-sdk": YcAIProvider,
            "custom-openai": CustomOpenAIProvider,
        }

        for provider_name, provider_config in providers_config.items():
            try:
                providerType = provider_config.get("type", None)
                if providerType is None:
                    raise ValueError(f"Provider type is not specified for provider {provider_name}")
                if providerType not in providerTypes:
                    raise ValueError(f"Unknown provider type {providerType} for provider {provider_name}")

                self.providers[provider_name] = providerTypes[providerType](provider_config)
                logger.info(f"Initialized {provider_name} provider with type {providerType}")
            except Exception as e:
                logger.error(f"Failed to initialize {provider_name} provider: {e}")

    def _initModels(self) -> None:
        """Initialize all configured models from the configuration.

        Reads model configurations from self.config and registers them with
        their respective providers. Supports optional JSON logging for model
        interactions. Skips disabled models and logs errors for failed
        initializations.

        Model configuration structure:
        - provider: Name of the provider to use
        - model_id: Model identifier for the provider
        - model_version: Optional model version (default: "latest")
        - temperature: Optional temperature setting (default: 0.5)
        - context: Optional context size (default: 32768)
        - enabled: Whether the model is enabled (default: True)
        """
        modelsConfig: Dict[str, Dict[str, Any]] = self.config.get("models", {})

        jsonLogSettings: Dict[str, Any] = self.config.get("json-logging", {})
        enableJsonLog: bool = bool(jsonLogSettings.get("enabled", False))
        jsonLogFile: str = jsonLogSettings.get("file", "")
        jsonLogAddDateSuffix: bool = bool(jsonLogSettings.get("add-date-suffix", True))

        for modelName, modelConfig in modelsConfig.items():
            try:
                if modelConfig.get("enabled", True) is False:
                    logger.info(f"Model {modelName} is disabled")
                    continue

                providerName: str = modelConfig["provider"]
                modelId: str = modelConfig["model_id"]
                modelVersion: str = modelConfig.get("model_version", "latest")
                temperature: float = modelConfig.get("temperature", 0.5)
                contextSize: int = modelConfig.get("context", 32768)

                if providerName not in self.providers:
                    logger.warning(f"Provider {providerName} not available for model {modelName}")
                    continue

                provider: AbstractLLMProvider = self.providers[providerName]
                model: AbstractModel = provider.addModel(
                    name=modelName,
                    modelId=modelId,
                    modelVersion=modelVersion,
                    temperature=temperature,
                    contextSize=contextSize,
                    statsStorage=self.statsStorage,
                    extraConfig=modelConfig,
                )

                if enableJsonLog:
                    model.setupJSONLogging(jsonLogFile, jsonLogAddDateSuffix)

                self.modelRegistry[modelName] = providerName
                logger.info(f"Added model {modelName} to provider {providerName}")

            except Exception as e:
                logger.error(f"Failed to initialize model {modelConfig.get('name', 'unknown')}: {e}")

    def listModels(self) -> List[str]:
        """List all available models across all providers.

        Returns:
            List of model names that have been successfully registered.
        """
        return list(self.modelRegistry.keys())

    def getModel(self, name: str) -> Optional[AbstractModel]:
        """Get a model instance by its name.

        Args:
            name: The name of the model to retrieve.

        Returns:
            The AbstractModel instance if found, None otherwise.
        """
        providerName: Optional[str] = self.modelRegistry.get(name)
        if not providerName:
            return None

        provider: Optional[AbstractLLMProvider] = self.providers.get(providerName)
        if not provider:
            return None

        return provider.getModel(name)

    def getModelInfo(self, name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific model.

        Args:
            name: The name of the model to query.

        Returns:
            Dictionary containing model information if found, None otherwise.
            The information structure depends on the provider implementation.
        """
        model: Optional[AbstractModel] = self.getModel(name)
        return model.getInfo() if model else None

    def getProvider(self, name: str) -> Optional[AbstractLLMProvider]:
        """Get a provider instance by its name.

        Args:
            name: The name of the provider to retrieve.

        Returns:
            The AbstractLLMProvider instance if found, None otherwise.
        """
        return self.providers.get(name)

    def listProviders(self) -> List[str]:
        """List all available providers.

        Returns:
            List of provider names that have been successfully initialized.
        """
        return list(self.providers.keys())
