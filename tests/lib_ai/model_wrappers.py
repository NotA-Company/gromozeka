"""
Wrapper classes for AI model instantiation to support the collector script.

These wrapper classes simplify the process of creating AI models for golden data collection
by using the `__new__` method to return AbstractModel instances directly on instantiation.
This allows the collector script to instantiate the wrapper class and get back a model
instance that it can call methods on directly.
"""

import logging
from typing import Any, Dict

from lib.ai.abstract import AbstractLLMProvider, AbstractModel
from lib.ai.providers.openrouter_provider import OpenrouterProvider
from lib.ai.providers.yc_openai_provider import YcOpenaiProvider
from lib.ai.providers.yc_sdk_provider import YcSdkProvider

logger = logging.getLogger(__name__)


class AbstractModelWrapper:
    """
    Abstract wrapper for AI model instantiation to support the collector script.

    This wrapper uses `__new__` to return an AbstractModel instance directly
    when instantiated, allowing the collector script to work with it seamlessly.
    Instead of creating a wrapper object, the `__new__` method creates and returns
    an actual model instance, making it transparent to the collector script.
    """

    def __new__(cls, providerConfig: Dict[str, Any], modelArgs: Dict[str, Any]) -> AbstractModel:
        """
        Create and return an AbstractModel instance directly.

        This method overrides the default object creation process to return
        an AbstractModel instance instead of an AbstractModelWrapper instance.
        It creates a provider using the getProvider class method, extracts
        model parameters from modelArgs, and creates a model using the provider.

        Args:
            providerConfig: Configuration dictionary for the AI provider
            modelArgs: Arguments for model creation including model_id, model_version,
                      temperature, context_size, and any extra configuration

        Returns:
            AbstractModel: An instance of a concrete model implementation
        """
        try:
            # Create provider
            provider = cls.getProvider(providerConfig)

            # Extract model parameters
            modelId = modelArgs.get("model_id", "inknown")
            modelVersion = modelArgs.get("model_version", "latest")

            # Create and return model
            model = provider.addModel(
                name=f"{type(provider).__name__}/{modelId}:{modelVersion}",
                modelId=modelId,
                modelVersion=modelVersion,
                temperature=float(modelArgs.get("temperature", 0.5)),
                contextSize=int(modelArgs.get("context_size", 8192)),
                extraConfig=modelArgs,
            )
            return model

        except Exception as e:
            logger.error(f"Failed to create YC OpenAI model: {e}")
            raise

    @classmethod
    def getProvider(cls, config: Dict[str, Any]) -> AbstractLLMProvider:
        """Get the AI provider instance for this wrapper.

        This abstract method must be implemented by subclasses to return
        the appropriate AI provider instance based on the provided configuration.

        Args:
            config: Configuration dictionary for the AI provider

        Returns:
            AbstractLLMProvider: An instance of a concrete provider implementation
        """
        raise NotImplementedError


class YcOpenaiModelWrapper(AbstractModelWrapper):
    """Wrapper for Yandex Cloud OpenAI provider.

    This wrapper specifically handles the YC OpenAI provider, which is
    compatible with the OpenAI API but uses Yandex Cloud authentication
    and endpoints. It returns a YcOpenaiProvider instance when instantiated.
    """

    @classmethod
    def getProvider(cls, config: Dict[str, Any]) -> AbstractLLMProvider:
        return YcOpenaiProvider(config)


class OpenrouterModelWrapper(AbstractModelWrapper):
    """Wrapper for OpenRouter provider.

    This wrapper handles the OpenRouter provider, which is an aggregation
    service that provides access to multiple AI models from different
    providers through a unified API. It returns an OpenrouterProvider
    instance when instantiated.
    """

    @classmethod
    def getProvider(cls, config: Dict[str, Any]) -> AbstractLLMProvider:
        return OpenrouterProvider(config)


class YcSdkModelWrapper(AbstractModelWrapper):
    """Wrapper for Yandex Cloud SDK provider.

    This wrapper handles the YC SDK provider, which uses the official
    Yandex Cloud SDK for interacting with AI services. It returns a
    YcSdkProvider instance when instantiated.
    """

    @classmethod
    def getProvider(cls, config: Dict[str, Any]) -> AbstractLLMProvider:
        return YcSdkProvider(config)
