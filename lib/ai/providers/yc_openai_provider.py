"""Yandex Cloud OpenAI-compatible provider for LLM models.

This module provides a provider implementation for Yandex Cloud's OpenAI-compatible
API, allowing interaction with Yandex Cloud's foundation models through the standard
OpenAI client interface. It supports text generation, tool calling, and other
capabilities offered by Yandex Cloud's LLM services.

The module implements:
    - YcOpenaiModel: Model implementation for Yandex Cloud OpenAI-compatible models
    - YcOpenaiProvider: Provider implementation for managing Yandex Cloud models

Key Features:
    - OpenAI-compatible API interface for Yandex Cloud models
    - Support for Yandex Cloud folder-based model identification
    - Configurable model parameters (temperature, context size)
    - Tool calling support for compatible models
    - Token usage tracking

Configuration:
    The provider requires the following configuration:
    - folder_id: Yandex Cloud folder identifier (required)
    - api_key: Yandex Cloud API key (inherited from base provider)

Reference:
    https://yandex.cloud/ru/docs/foundation-models/concepts/openai-compatibility

Classes:
    YcOpenaiModel: Yandex Cloud OpenAI-compatible model implementation.
    YcOpenaiProvider: Yandex Cloud OpenAI-compatible provider implementation.
"""

import logging
from typing import Any, Dict

from openai import AsyncOpenAI

from lib.stats import StatsStorage

from ..abstract import AbstractModel
from .basic_openai_provider import BasicOpenAIModel, BasicOpenAIProvider

logger = logging.getLogger(__name__)


class YcOpenaiModel(BasicOpenAIModel):
    """Yandex Cloud OpenAI-compatible model implementation.

    This class extends BasicOpenAIModel to provide Yandex Cloud-specific
    functionality for interacting with Yandex Cloud's foundation models
    through the OpenAI-compatible API. It handles Yandex Cloud's unique
    model identification format using folder IDs.

    Attributes:
        _folderId: Yandex Cloud folder identifier used in model URLs.
        _client: The OpenAI async client instance for API communication.
        _supportTools: Boolean indicating whether the model supports tool calling.
        _config: Configuration dictionary for the model.

    Args:
        provider: The YcOpenaiProvider instance that created this model.
        modelId: The identifier of the model (e.g., "yandexgpt", "summarization").
        modelVersion: The version string of the model (e.g., "latest", "rc").
        temperature: The sampling temperature for generation (0.0 to 2.0).
        contextSize: The maximum context window size in tokens.
        openAiClient: The OpenAI async client instance for API communication.
        folderId: Yandex Cloud folder identifier for model identification.
        extraConfig: Additional configuration options for the model.

    Raises:
        ValueError: If folderId is not provided or is empty.

    Example:
        >>> provider = YcOpenaiProvider({"folder_id": "b1g...", "api_key": "..."})
        >>> model = YcOpenaiModel(
        ...     provider=provider,
        ...     modelId="yandexgpt",
        ...     modelVersion="latest",
        ...     temperature=0.7,
        ...     contextSize=8000,
        ...     openAiClient=provider._client,
        ...     folderId="b1g...",
        ... )
        >>> result = await model.generateText(messages)
    """

    def __init__(
        self,
        provider: "YcOpenaiProvider",
        modelId: str,
        *,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Dict[str, Any] = {},
        openAiClient: AsyncOpenAI,
        folderId: str,
    ) -> None:
        """Initialize a Yandex Cloud OpenAI model instance.

        Args:
            provider: The YcOpenaiProvider instance that created this model.
            modelId: The identifier of the model (e.g., "yandexgpt", "summarization").
            modelVersion: The version string of the model (e.g., "latest", "rc").
            temperature: The sampling temperature for generation (0.0 to 2.0).
            contextSize: The maximum context window size in tokens.
            openAiClient: The OpenAI async client instance for API communication.
            folderId: Yandex Cloud folder identifier for model identification.
            extraConfig: Additional configuration options for the model.

        Raises:
            ValueError: If folderId is not provided or is empty.
        """
        super().__init__(
            provider,
            modelId,
            modelVersion=modelVersion,
            temperature=temperature,
            contextSize=contextSize,
            statsStorage=statsStorage,
            extraConfig=extraConfig,
            openAiClient=openAiClient,
        )
        self._folderId = folderId

    def _getModelId(self) -> str:
        """Get the Yandex Cloud-specific model identifier.

        Constructs the model identifier in Yandex Cloud's format, which includes
        the folder ID, model ID, and version. This format is required for
        Yandex Cloud's OpenAI-compatible API.

        Returns:
            The Yandex Cloud model identifier string in the format
            "gpt://{folderId}/{modelId}/{modelVersion}".

        Raises:
            ValueError: If folderId is not set or is empty.

        Example:
            >>> model._folderId = "b1g..."
            >>> model.modelId = "yandexgpt"
            >>> model.modelVersion = "latest"
            >>> model._getModelId()
            'gpt://b1g.../yandexgpt/latest'
        """
        if not self._folderId:
            raise ValueError("folder_id is required for YC OpenAI provider, dood!")

        return f"gpt://{self._folderId}/{self.modelId}/{self.modelVersion}"

    def _getExtraParams(self) -> Dict[str, Any]:
        """Get Yandex Cloud-specific extra parameters for API calls.

        This method can be extended to include Yandex Cloud-specific parameters
        such as max_tokens, stream, or other provider-specific options.

        Returns:
            A dictionary of extra parameters to include in the API call.
            Currently returns an empty dictionary, but can be extended
            to include parameters like max_tokens or stream.

        Example:
            >>> model._getExtraParams()
            {}
        """
        return {
            # "max_tokens": 2000,
            # "stream": True,  # Commented out for now
        }


class YcOpenaiProvider(BasicOpenAIProvider):
    """Yandex Cloud OpenAI-compatible provider implementation.

    This class extends BasicOpenAIProvider to provide Yandex Cloud-specific
    functionality for managing and creating Yandex Cloud OpenAI-compatible
    model instances. It handles Yandex Cloud's unique configuration requirements,
    including folder ID validation and API endpoint configuration.

    Attributes:
        _folderId: Yandex Cloud folder identifier used for model identification.
        _client: The OpenAI async client instance for API communication.
        config: Configuration dictionary for the provider.
        models: Dictionary of registered model instances.

    Args:
        config: Configuration dictionary containing provider settings:
            - folder_id: Yandex Cloud folder identifier (required)
            - api_key: Yandex Cloud API key (required, inherited from base)
            - Additional provider-specific configuration options

    Raises:
        ValueError: If folder_id is not provided in the configuration.

    Example:
        >>> config = {
        ...     "folder_id": "b1g...",
        ...     "api_key": "your-api-key",
        ... }
        >>> provider = YcOpenaiProvider(config)
        >>> model = provider.addModel(
        ...     name="yandexgpt",
        ...     modelId="yandexgpt",
        ...     modelVersion="latest",
        ...     temperature=0.7,
        ...     contextSize=8000,
        ... )
        >>> result = await model.generateText(messages)
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize a Yandex Cloud OpenAI provider instance.

        Args:
            config: Configuration dictionary containing provider settings:
                - folder_id: Yandex Cloud folder identifier (required)
                - api_key: Yandex Cloud API key (required, inherited from base)
                - Additional provider-specific configuration options

        Raises:
            ValueError: If folder_id is not provided in the configuration.
            ValueError: If api_key is not provided in the configuration.
            Exception: If client initialization fails.
        """
        self._folderId = str(config.get("folder_id", ""))
        if not self._folderId:
            raise ValueError("folder_id is required for YC OpenAI provider, dood!")

        super().__init__(config)

    def _getBaseUrl(self) -> str:
        """Get the Yandex Cloud OpenAI-compatible base URL.

        Returns the base URL for Yandex Cloud's OpenAI-compatible API endpoint.
        This URL is used by the OpenAI client to make API requests.

        Returns:
            The base URL string for Yandex Cloud's OpenAI-compatible API:
            "https://llm.api.cloud.yandex.net/v1"

        Example:
            >>> provider._getBaseUrl()
            'https://llm.api.cloud.yandex.net/v1'
        """
        return "https://llm.api.cloud.yandex.net/v1"

    def _createModelInstance(
        self,
        name: str,
        *,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Dict[str, Any] = {},
    ) -> AbstractModel:
        """Create a Yandex Cloud OpenAI model instance.

        Creates and configures a new YcOpenaiModel instance with the specified
        parameters. The model is configured to use the provider's OpenAI client
        and folder ID for Yandex Cloud API communication.

        Args:
            name: The name to assign to the model instance (not used in YC model).
            modelId: The identifier of the model (e.g., "yandexgpt", "summarization").
            modelVersion: The version string of the model (e.g., "latest", "rc").
            temperature: The sampling temperature for generation (0.0 to 2.0).
            contextSize: The maximum context window size in tokens.
            extraConfig: Additional configuration options for the model.

        Returns:
            A YcOpenaiModel instance configured with the provided parameters.

        Raises:
            ValueError: If the OpenAI client is not initialized.
            Exception: If model creation fails for any other reason.

        Example:
            >>> model = provider._createModelInstance(
            ...     name="yandexgpt",
            ...     modelId="yandexgpt",
            ...     modelVersion="latest",
            ...     temperature=0.7,
            ...     contextSize=8000,
            ... )
            >>> isinstance(model, YcOpenaiModel)
            True
        """
        if not self._client:
            raise ValueError("YC OpenAI client not initialized, dood!")

        return YcOpenaiModel(
            provider=self,
            modelId=modelId,
            modelVersion=modelVersion,
            temperature=temperature,
            contextSize=contextSize,
            folderId=self._folderId,
            statsStorage=statsStorage,
            extraConfig=extraConfig,
            openAiClient=self._client,
        )
