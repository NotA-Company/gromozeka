"""
LLM Manager for coordinating multiple LLM providers and models, dood!
"""
import logging
from typing import Dict, List, Any, Optional

from ai.providers.yc_sdk_provider import YcSdkProvider

from .abstract import AbstractModel, AbstractLLMProvider
from .providers.yc_openai_provider import YcOpenaiProvider
from .providers.openrouter_provider import OpenrouterProvider

logger = logging.getLogger(__name__)


class LLMManager:
    """Manager for LLM providers and models, dood!"""

    def __init__(self, config: Dict[str, Any]):
        """Initialize LLM manager with configuration, dood!

        Args:
            config: Configuration dictionary with providers and models
        """
        self.config = config
        self.providers: Dict[str, AbstractLLMProvider] = {}
        self.modelRegistry: Dict[str, str] = {}  # model_name -> provider_name

        # Initialize providers
        self._initProviders()

        # Add models from config
        self._initModels()

    def _initProviders(self):
        """Initialize known providers from config, dood!"""
        providers_config = self.config.get("providers", {})

        providerTypes = {
            "yc-openai": YcOpenaiProvider,
            "openrouter": OpenrouterProvider,
            "yc-sdk": YcSdkProvider,
        }

        for provider_name, provider_config in providers_config.items():
            try:
                providerType = provider_config.get("type", None)
                if providerType is None:
                    raise ValueError(
                        "Provider type is not specified for provider {provider_name}, dood!"
                    )
                if providerType not in providerTypes:
                    raise ValueError(
                        "Unknown provider type {providerType} for provider {provider_name}, dood!"
                    )

                self.providers[provider_name] = providerTypes[providerType](provider_config)
                logger.info(
                    f"Initialized {provider_name} provider with type {providerType}, dood!"
                )
            except Exception as e:
                logger.error(f"Failed to initialize {provider_name} provider: {e}")

    def _initModels(self):
        """Initialize models from config, dood!"""
        modelsConfig: Dict[str, Dict[str, Any]] = self.config.get("models", {})

        for modelName, modelConfig in modelsConfig.items():
            try:
                providerName = modelConfig["provider"]
                modelId = modelConfig["model_id"]
                modelVersion = modelConfig.get("model_version", "latest")
                temperature = modelConfig.get("temperature", 0.5)
                contextSize = modelConfig.get("context", 32768)

                if providerName not in self.providers:
                    logger.warning(f"Provider {providerName} not available for model {modelName}, dood!")
                    continue

                provider = self.providers[providerName]
                provider.addModel(
                    name=modelName,
                    modelId=modelId,
                    modelVersion=modelVersion,
                    temperature=temperature,
                    contextSize=contextSize,
                    extraConfig=modelConfig,
                )

                self.modelRegistry[modelName] = providerName
                logger.info(f"Added model {modelName} to provider {providerName}, dood!")

            except Exception as e:
                logger.error(f"Failed to initialize model {modelConfig.get('name', 'unknown')}: {e}")

    def listModels(self) -> List[str]:
        """List all available models across all providers, dood!

        Returns:
            List of model names
        """
        return list(self.modelRegistry.keys())

    def getModel(self, name: str) -> Optional[AbstractModel]:
        """Get a model by name, dood!

        Args:
            name: Model name

        Returns:
            Model instance or None if not found
        """
        providerName = self.modelRegistry.get(name)
        if not providerName:
            return None

        provider = self.providers.get(providerName)
        if not provider:
            return None

        return provider.getModel(name)

    def getModelInfo(self, name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific model, dood!

        Args:
            name: Model name

        Returns:
            Model information dictionary or None if not found
        """
        model = self.getModel(name)
        return model.getInfo() if model else None

    def getProvider(self, name: str) -> Optional[AbstractLLMProvider]:
        """Get a provider by name, dood!

        Args:
            name: Provider name

        Returns:
            Provider instance or None if not found
        """
        return self.providers.get(name)

    def listProviders(self) -> List[str]:
        """List all available providers, dood!

        Returns:
            List of provider names
        """
        return list(self.providers.keys())
