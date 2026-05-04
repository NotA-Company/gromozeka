"""OpenRouter provider for LLM models.

This module provides an implementation of the OpenRouter API, which serves as a unified
interface to access multiple LLM providers through a single API endpoint. OpenRouter
aggregates models from various providers including OpenAI, Anthropic, Google, and others,
allowing applications to switch between models without changing the integration code.

Classes:
    OpenrouterModel: OpenRouter-specific model implementation extending BasicOpenAIModel.
    OpenrouterProvider: OpenRouter provider implementation extending BasicOpenAIProvider.

The module supports:
- Text generation with configurable temperature and context size
- Tool/function calling capabilities for compatible models
- Custom headers for OpenRouter rankings and analytics
- Seamless integration with the existing OpenAI-compatible infrastructure

OpenRouter-specific features:
- Unified API endpoint for multiple model providers
- Model routing and load balancing
- Usage analytics and rankings
- Custom headers for application identification

Example:
    To use the OpenRouter provider:

    ```python
    from lib.ai.providers.openrouter_provider import OpenrouterProvider

    config = {
        "api_key": "your-openrouter-api-key",
    }

    provider = OpenrouterProvider(config)
    model = provider.addModel(
        name="gpt-4",
        modelId="openai/gpt-4",
        modelVersion="latest",
        temperature=0.7,
        contextSize=8192,
    )

    result = await model.generateText(messages)
    ```
"""

import logging
from typing import Any, Dict

from openai import AsyncOpenAI

from ..abstract import AbstractModel
from .basic_openai_provider import BasicOpenAIModel, BasicOpenAIProvider

logger = logging.getLogger(__name__)


class OpenrouterModel(BasicOpenAIModel):
    """OpenRouter model implementation.

    This class extends BasicOpenAIModel to provide OpenRouter-specific functionality
    for LLM model interactions. It adds custom headers for OpenRouter's ranking system
    and analytics, allowing the application to be properly identified in OpenRouter's
    usage statistics.

    The model supports all standard OpenAI-compatible features including text generation,
    tool calling, and token usage tracking, while seamlessly integrating with OpenRouter's
    multi-provider infrastructure.

    Attributes:
        Inherits all attributes from BasicOpenAIModel including:
        - _client: The OpenAI async client instance for API communication.
        - _supportTools: Boolean indicating whether the model supports tool calling.
        - _config: Configuration dictionary for the model.
        - provider: The OpenrouterProvider instance that created this model.
        - modelId: The identifier of the model to use in API calls.
        - modelVersion: The version string of the model.
        - temperature: The sampling temperature for generation.
        - contextSize: The maximum context window size in tokens.

    Args:
        provider: The OpenrouterProvider instance that created this model.
        modelId: The identifier of the model to use in API calls (e.g., "openai/gpt-4").
        modelVersion: The version string of the model (e.g., "latest", "v1").
        temperature: The sampling temperature for generation (0.0 to 2.0).
            Lower values make the output more deterministic, higher values more random.
        contextSize: The maximum context window size in tokens.
        openAiClient: The OpenAI async client instance for API communication.
        extraConfig: Additional configuration options for the model, such as:
            - support_tools: Boolean indicating tool support (default: False)
            - support_images: Boolean indicating image generation support (default: False)
            - Other provider-specific options

    Example:
        ```python
        model = OpenrouterModel(
            provider=provider,
            modelId="openai/gpt-4",
            modelVersion="latest",
            temperature=0.7,
            contextSize=8192,
            openAiClient=client,
            extraConfig={"support_tools": True}
        )

        result = await model.generateText(messages)
        ```
    """

    def __init__(
        self,
        provider: "OpenrouterProvider",
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        openAiClient: AsyncOpenAI,
        extraConfig: Dict[str, Any] = {},
    ) -> None:
        """Initialize an OpenRouter model instance.

        Args:
            provider: The OpenrouterProvider instance that created this model.
            modelId: The identifier of the model to use in API calls.
            modelVersion: The version string of the model.
            temperature: The sampling temperature for generation (0.0 to 2.0).
            contextSize: The maximum context window size in tokens.
            openAiClient: The OpenAI async client instance.
            extraConfig: Additional configuration options for the model.

        Raises:
            ValueError: If required configuration is missing or invalid.
        """
        super().__init__(
            provider,
            modelId,
            modelVersion,
            temperature,
            contextSize,
            openAiClient,
            extraConfig,
        )

    def _getExtraParams(self) -> Dict[str, Any]:
        """Get OpenRouter-specific extra parameters for API calls.

        This method returns custom headers and parameters that are sent with each
        API request to OpenRouter. These headers are used for:
        - Application identification in OpenRouter's analytics
        - Rankings on openrouter.ai
        - Usage tracking and attribution

        The headers include:
        - HTTP-Referer: The URL of the application using OpenRouter
        - X-Title: The title/name of the application

        Returns:
            A dictionary containing extra parameters to include in API calls:
            - extra_headers: Dictionary of custom HTTP headers
            - Additional provider-specific parameters (currently commented out)

        Example:
            ```python
            params = model._getExtraParams()
            # Returns:
            # {
            #     "extra_headers": {
            #         "HTTP-Referer": "https://sourcecraft.dev/notacompany/gromozeka",
            #         "X-Title": "Gromozeka AI Bot"
            #     }
            # }
            ```
        """
        return {
            "extra_headers": {
                # Optional. Site URL for rankings on openrouter.ai.
                "HTTP-Referer": "https://sourcecraft.dev/notacompany/gromozeka",
                # Optional. Site title for rankings on openrouter.ai.
                "X-Title": "Gromozeka AI Bot",
            },
            # "max_tokens": min(4096, self.context_size)  # Reasonable default
        }


class OpenrouterProvider(BasicOpenAIProvider):
    """OpenRouter provider implementation.

    This class extends BasicOpenAIProvider to provide OpenRouter-specific functionality
    for accessing multiple LLM providers through a unified API. OpenRouter acts as an
    aggregator that routes requests to various model providers (OpenAI, Anthropic, Google,
    etc.) while maintaining a consistent interface.

    The provider handles:
    - Client initialization with OpenRouter's API endpoint
    - Model instance creation with OpenRouter-specific configuration
    - Authentication and API key management
    - Integration with the existing OpenAI-compatible infrastructure

    Attributes:
        Inherits all attributes from BasicOpenAIProvider including:
        - _client: The OpenAI async client instance for API communication.
        - config: Configuration dictionary for the provider.
        - models: Dictionary of registered model instances.

    Args:
        config: Configuration dictionary containing provider settings:
            - api_key: The OpenRouter API key for authentication (required)
            - Additional provider-specific configuration options

    Example:
        ```python
        config = {
            "api_key": "your-openrouter-api-key",
        }

        provider = OpenrouterProvider(config)
        model = provider.addModel(
            name="gpt-4",
            modelId="openai/gpt-4",
            modelVersion="latest",
            temperature=0.7,
            contextSize=8192,
        )

        result = await model.generateText(messages)
        ```
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize an OpenRouter provider instance.

        Args:
            config: Configuration dictionary containing provider settings.
                Must include 'api_key' for authentication.

        Raises:
            ValueError: If required configuration (api_key) is missing.
            ImportError: If the openai package is not available.
            Exception: If client initialization fails.
        """
        super().__init__(config)

    def _getBaseUrl(self) -> str:
        """Get the base URL for the OpenRouter API.

        This method returns the base URL for all OpenRouter API endpoints.
        The URL is used by the parent class to initialize the OpenAI client.

        Returns:
            The base URL string for the OpenRouter API endpoint:
            "https://openrouter.ai/api/v1"

        Example:
            ```python
            url = provider._getBaseUrl()
            # Returns: "https://openrouter.ai/api/v1"
            ```
        """
        return "https://openrouter.ai/api/v1"

    def _createModelInstance(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ) -> AbstractModel:
        """Create an OpenRouter model instance.

        This method creates a new OpenrouterModel instance with the specified
        configuration. The model is configured to use the OpenRouter API and
        includes custom headers for application identification.

        Args:
            name: The name to assign to the model instance. This name is used
                to retrieve the model later from the provider.
            modelId: The identifier of the model to use in API calls. This should
                be in the format "provider/model" (e.g., "openai/gpt-4").
            modelVersion: The version string of the model (e.g., "latest", "v1").
            temperature: The sampling temperature for generation (0.0 to 2.0).
            contextSize: The maximum context window size in tokens.
            extraConfig: Additional configuration options for the model, such as:
                - support_tools: Boolean indicating tool support (default: False)
                - support_images: Boolean indicating image generation support (default: False)
                - Other provider-specific options

        Returns:
            An OpenrouterModel instance configured with the provided parameters.

        Raises:
            RuntimeError: If the OpenRouter client is not initialized.

        Example:
            ```python
            model = provider._createModelInstance(
                name="gpt-4",
                modelId="openai/gpt-4",
                modelVersion="latest",
                temperature=0.7,
                contextSize=8192,
                extraConfig={"support_tools": True}
            )
            ```
        """
        if not self._client:
            raise RuntimeError("OpenRouter client not initialized, dood!")

        return OpenrouterModel(
            provider=self,
            modelId=modelId,
            modelVersion=modelVersion,
            temperature=temperature,
            contextSize=contextSize,
            openAiClient=self._client,
            extraConfig=extraConfig,
        )
