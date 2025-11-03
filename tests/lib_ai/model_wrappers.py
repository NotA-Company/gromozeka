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

    This wrapper uses `__new__` to return an AbstractModel instance directly
    when instantiated, allowing the collector script to work with it seamlessly.
    TODO: rewrite
    """

    def __new__(cls, providerConfig: Dict[str, Any], modelArgs: Dict[str, Any]) -> AbstractModel:
        """
        TODO
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
        """TODO"""
        raise NotImplementedError


class YcOpenaiModelWrapper(AbstractModelWrapper):
    """TODO"""

    @classmethod
    def getProvider(cls, config: Dict[str, Any]) -> AbstractLLMProvider:
        return YcOpenaiProvider(config)


class OpenrouterModelWrapper(AbstractModelWrapper):
    """TODO"""

    @classmethod
    def getProvider(cls, config: Dict[str, Any]) -> AbstractLLMProvider:
        return OpenrouterProvider(config)


class YcSdkModelWrapper(AbstractModelWrapper):
    """TODO"""

    @classmethod
    def getProvider(cls, config: Dict[str, Any]) -> AbstractLLMProvider:
        return YcSdkProvider(config)
