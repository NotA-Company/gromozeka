"""OpenRouter provider for LLM models.

This module provides an implementation of the OpenRouter API, which serves as a unified
interface to access multiple LLM providers through a single API endpoint. OpenRouter
aggregates models from various providers including OpenAI, Anthropic, Google, and others,
allowing applications to switch between models without changing the integration code.

Classes:
    OpenrouterModel: OpenRouter-specific model implementation extending BasicOpenAIModel.
    OpenrouterProvider: OpenRouter provider implementation extending BasicOpenAIProvider.

The module supports:
- Text generation with configurable custom parameters (including temperature) and context size
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
        contextSize=8192,
        customParams={"temperature": 0.7},
    )

    result = await model.generateText(messages)
    ```
"""

import logging
from typing import Any, Dict, Optional

import httpx2 as httpx
from openai import AsyncOpenAI

from lib.proxy import ProxyConfig
from lib.stats import StatsStorage

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
        - _customParams: Per-model custom parameters passed through to the
            underlying API call (temperature, top_p, max_tokens, etc.).
        - contextSize: The maximum context window size in tokens.

    Args:
        provider: The OpenrouterProvider instance that created this model.
        modelId: The identifier of the model to use in API calls (e.g., "openai/gpt-4").
        modelVersion: The version string of the model (e.g., "latest", "v1").
        contextSize: The maximum context window size in tokens.
        openAiClient: The OpenAI async client instance for API communication.
        extraConfig: Additional configuration options for the model, such as:
            - support_tools: Boolean indicating tool support (default: False)
            - support_images: Boolean indicating image generation support (default: False)
            - Other provider-specific options
        customParams: Per-model custom parameters passed through to the
            underlying OpenRouter API call (temperature, top_p, max_tokens,
            etc.). OpenRouter's default ``extra_headers`` are merged in by
            :meth:`_getExtraParams`; any user-supplied keys here take
            precedence. See :attr:`AbstractModel._customParams`.

    Example:
        ```python
        model = OpenrouterModel(
            provider=provider,
            modelId="openai/gpt-4",
            modelVersion="latest",
            contextSize=8192,
            openAiClient=client,
            extraConfig={"support_tools": True},
            customParams={"temperature": 0.7},
        )

        result = await model.generateText(messages)
        ```
    """

    def __init__(
        self,
        provider: "OpenrouterProvider",
        modelId: str,
        *,
        modelVersion: str,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Optional[Dict[str, Any]] = None,
        customParams: Optional[Dict[str, Any]] = None,
        openAiClient: AsyncOpenAI,
    ) -> None:
        """Initialize an OpenRouter model instance.

        Args:
            provider: The OpenrouterProvider instance that created this model.
            modelId: The identifier of the model to use in API calls.
            modelVersion: The version string of the model.
            contextSize: The maximum context window size in tokens.
            openAiClient: The OpenAI async client instance.
            extraConfig: Additional configuration options for the model.
            customParams: Per-model custom parameters passed through to the
                underlying OpenRouter API call (temperature, top_p, max_tokens,
                etc.). See :attr:`AbstractModel._customParams`.

        Raises:
            ValueError: If required configuration is missing or invalid.
        """
        super().__init__(
            provider,
            modelId,
            modelVersion=modelVersion,
            contextSize=contextSize,
            statsStorage=statsStorage,
            extraConfig=extraConfig,
            customParams=customParams,
            openAiClient=openAiClient,
        )

    def _getExtraParams(self) -> Dict[str, Any]:
        """Get OpenRouter-specific extra parameters merged with customParams.

        Merges OpenRouter's default ``extra_headers`` (used for application
        identification / rankings on openrouter.ai) with the user-supplied
        ``customParams`` from :meth:`BasicOpenAIModel._getExtraParams`.
        ``customParams`` keys take precedence over the provider defaults
        via ``{**providerDefaults, **super()._getExtraParams()}`` ordering
        (last-wins), so a user who sets ``customParams={"extra_headers":
        {...}}`` in TOML overrides the Gromozeka defaults entirely.

        Returns:
            A dict carrying ``extra_headers`` (for OpenRouter analytics)
            plus every key the user put in ``customParams``.
        """
        providerDefaults: Dict[str, Any] = {
            "extra_headers": {
                # Optional. Site URL for rankings on openrouter.ai.
                "HTTP-Referer": "https://notacompany.org/products/gromozeka",
                # Optional. Site title for rankings on openrouter.ai.
                "X-Title": "Gromozeka AI Bot",
            },
        }
        return {**providerDefaults, **super()._getExtraParams()}


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
            contextSize=8192,
            customParams={"temperature": 0.7},
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

    async def listRemoteModels(self) -> Dict[str, Dict[str, Any]]:
        """List models available from OpenRouter's API.

        Uses raw HTTP to capture OpenRouter-specific fields (context_length,
        pricing) that the OpenAI SDK's Model type strips out.

        NOTE: I do not suppose this method to be called frequently (mostly from one-time script)
          But if it will, need to think about persistent httpx client instead of spawning new one
          each call.


        Returns:
            Dict[str, Dict[str, Any]]: Model ID → settings dict.
        """
        try:
            try:
                apiKey = self._getApiKey()
            except ValueError:
                apiKey = None
            headers: Dict[str, str] = {}
            if apiKey:
                headers["Authorization"] = f"Bearer {apiKey}"

            # Resolve proxy for OpenRouter API calls
            proxyKwargs = ProxyConfig.fromServiceConfig(self.config).toKwargs()
            async with httpx.AsyncClient(**proxyKwargs, timeout=30) as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

            result: Dict[str, Dict[str, Any]] = {}
            for model in data.get("data", []):
                modelId = model.get("id", "")
                if modelId:
                    result[modelId] = model
            return result
        except Exception as e:
            logger.error(f"Failed to list remote models from OpenRouter: {e}")
            return {}

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
            contextSize: The maximum context window size in tokens.
            extraConfig: Additional configuration options for the model, such as:
                - support_tools: Boolean indicating tool support (default: False)
                - support_images: Boolean indicating image generation support (default: False)
                - Other provider-specific options
            customParams: Per-model custom parameters passed through to the
                underlying OpenRouter API call (temperature, top_p, max_tokens,
                etc.). See :attr:`AbstractModel._customParams`.

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
                contextSize=8192,
                extraConfig={"support_tools": True},
                customParams={"temperature": 0.7},
            )
            ```
        """
        if not self._client:
            raise RuntimeError("OpenRouter client not initialized")

        return OpenrouterModel(
            provider=self,
            modelId=modelId,
            modelVersion=modelVersion,
            contextSize=contextSize,
            statsStorage=statsStorage,
            extraConfig=extraConfig,
            customParams=customParams,
            openAiClient=self._client,
        )
