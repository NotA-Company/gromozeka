"""Custom OpenAI-compatible provider for LLM models.

This module provides a provider implementation for custom OpenAI-compatible APIs.
It extends the BasicOpenAIProvider to support custom base URLs, enabling integration
with OpenAI-compatible services that are not the official OpenAI API.

The CustomOpenAIProvider allows users to configure a custom base URL for their
OpenAI-compatible API endpoint, making it suitable for:
- Self-hosted OpenAI-compatible services
- Third-party OpenAI-compatible APIs
- Custom proxy or gateway services
- Local LLM inference servers with OpenAI-compatible endpoints

Classes:
    CustomOpenAIProvider: Provider for custom OpenAI-compatible APIs.

Example:
    To use a custom OpenAI-compatible provider:

    ```python
    from lib.ai.providers.custom_openai_provider import CustomOpenAIProvider

    config = {
        "base_url": "https://api.custom-llm.com/v1",
        "api_key": "your-api-key",
    }

    provider = CustomOpenAIProvider(config)
    provider.addModel(
        name="custom-model",
        modelId="custom-llm-v1",
        modelVersion="latest",
        contextSize=4096,
        customParams={"temperature": 0.7},
    )

    model = provider.getModel("custom-model")
    result = await model.generateText(messages)
    ```
"""

import logging
from typing import Any, Dict, Optional

from lib.stats import StatsStorage

from ..abstract import AbstractModel
from .basic_openai_provider import BasicOpenAIModel, BasicOpenAIProvider

logger = logging.getLogger(__name__)


class CustomOpenAIProvider(BasicOpenAIProvider):
    """Provider for custom OpenAI-compatible APIs.

    This class extends BasicOpenAIProvider to support custom base URLs for
    OpenAI-compatible APIs. It enables integration with any service that
    implements the OpenAI API specification, including self-hosted models,
    third-party services, and custom gateways.

    The provider inherits all functionality from BasicOpenAIProvider, including:
    - Text generation with configurable parameters
    - Image generation for compatible models
    - Tool/function calling capabilities
    - Token usage tracking
    - Error handling and validation

    Attributes:
        config: Configuration dictionary containing provider settings.
            Must include "base_url" key with the API endpoint URL.
        _client: The OpenAI async client instance for API communication.

    Example:
        ```python
        config = {
            "base_url": "https://api.custom-llm.com/v1",
            "api_key": "your-api-key",
        }

        provider = CustomOpenAIProvider(config)
        provider.addModel(
            name="custom-model",
            modelId="custom-llm-v1",
            modelVersion="latest",
            contextSize=4096,
            customParams={"temperature": 0.7},
        )
        ```
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize a custom OpenAI provider.

        Sets up the provider with the given configuration and validates that
        a base URL is provided. The base URL is required to specify the
        custom OpenAI-compatible API endpoint.

        Args:
            config: Configuration dictionary containing provider settings.
                Must include:
                - base_url (str): The base URL of the custom OpenAI-compatible API.
                May include:
                - api_key (str): API key for authentication.
                - timeout (int): Request timeout in seconds.
                - max_retries (int): Maximum number of retry attempts.

        Raises:
            ValueError: If the "base_url" key is not present in the config.

        Example:
            ```python
            config = {
                "base_url": "https://api.custom-llm.com/v1",
                "api_key": "your-api-key",
                "timeout": 30,
            }

            provider = CustomOpenAIProvider(config)
            ```
        """
        super().__init__(config)
        if "base_url" not in config:
            raise ValueError("Base URL not provided")

    def _getBaseUrl(self) -> str:
        """Get the custom OpenAI-compatible API base URL.

        Returns the base URL configured for this provider, which points to
        the custom OpenAI-compatible API endpoint.

        Returns:
            The base URL string for the custom OpenAI-compatible API.

        Example:
            ```python
            provider = CustomOpenAIProvider({"base_url": "https://api.custom.com/v1"})
            base_url = provider._getBaseUrl()
            # Returns: "https://api.custom.com/v1"
            ```
        """
        return self.config["base_url"]

    def _createModelInstance(
        self,
        name: str,
        *,
        modelId: str,
        modelVersion: str,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Optional[Dict[str, Any]] = None,
        customParams: Optional[Dict[str, Any]] = None,
    ) -> AbstractModel:
        """Create a custom OpenAI model instance.

        Creates and returns a BasicOpenAIModel instance configured for the
        custom OpenAI-compatible API. The model will use the provider's
        OpenAI client to communicate with the custom API endpoint.

        Args:
            name: The name identifier for the model instance.
            modelId: The model identifier to use in API calls (e.g., "custom-llm-v1").
            modelVersion: The version string of the model (e.g., "latest", "v1").
            contextSize: The maximum context window size in tokens.
            extraConfig: Additional configuration options for the model.
                May include provider-specific settings or custom parameters.
            customParams: Per-model custom parameters passed through to the
                underlying OpenAI-compatible API call (temperature, top_p,
                max_tokens, etc.). See :attr:`AbstractModel._customParams`.

        Returns:
            A BasicOpenAIModel instance configured for the custom OpenAI-compatible API.

        Raises:
            RuntimeError: If the OpenAI client has not been initialized.

        Example:
            ```python
            model = provider._createModelInstance(
                name="custom-model",
                modelId="custom-llm-v1",
                modelVersion="latest",
                contextSize=4096,
                extraConfig={"custom_param": "value"},
                customParams={"temperature": 0.7},
            )
            ```
        """
        if not self._client:
            raise RuntimeError("OpenAI client not initialized")

        return BasicOpenAIModel(
            provider=self,
            modelId=modelId,
            modelVersion=modelVersion,
            contextSize=contextSize,
            statsStorage=statsStorage,
            extraConfig=extraConfig,
            customParams=customParams,
            openAiClient=self._client,
        )
