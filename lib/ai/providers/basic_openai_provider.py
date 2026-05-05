"""Basic OpenAI provider and model base classes for shared functionality.

This module provides base classes for OpenAI-compatible AI providers and models.
It implements common functionality for interacting with OpenAI-compatible APIs,
including text generation, image generation, and tool calling capabilities.

Classes:
    OpenAIModelRunResult: Result class for OpenAI model runs.
    BasicOpenAIModel: Base class for OpenAI-compatible model implementations.
    BasicOpenAIProvider: Base class for OpenAI-compatible provider implementations.

The module supports:
- Text generation with configurable temperature and context size
- Image generation for compatible models
- Tool/function calling capabilities
- Token usage tracking
- Error handling and validation
"""

import base64
import json
import logging
from collections.abc import Sequence
from typing import Any, Dict, List, Optional

import openai
from openai.types.chat.chat_completion import ChatCompletion

from ..abstract import AbstractLLMProvider, AbstractModel
from ..models import (
    LLMAbstractTool,
    LLMToolCall,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
)

logger = logging.getLogger(__name__)


class OpenAIModelRunResult(ModelRunResult):
    """Result class for OpenAI model runs.

    This class extends ModelRunResult to provide specific functionality
    for OpenAI-compatible model execution results. It inherits all
    properties from the parent class and can be used to track
    the outcome of model invocations including text generation,
    image generation, and tool calls.

    Attributes:
        Inherits all attributes from ModelRunResult including:
        - rawResult: The raw response from the OpenAI API
        - status: The completion status of the model run
        - resultText: The generated text content
        - toolCalls: List of tool/function calls made by the model
        - inputTokens: Number of tokens in the input
        - outputTokens: Number of tokens in the output
        - totalTokens: Total number of tokens used
        - mediaMimeType: MIME type of generated media (for images)
        - mediaData: Binary data of generated media
        - error: Error information if the run failed
    """


class BasicOpenAIModel(AbstractModel):
    """Base class for OpenAI-compatible model implementations.

    This class provides shared functionality for all OpenAI-compatible models,
    including text generation, image generation, and tool calling capabilities.
    It handles communication with the OpenAI API and processes responses.

    Attributes:
        _client: The OpenAI async client instance for API communication.
        _supportTools: Boolean indicating whether the model supports tool calling.
        _config: Configuration dictionary for the model.

    Args:
        provider: The provider instance that created this model.
        modelId: The identifier of the model to use in API calls.
        modelVersion: The version string of the model.
        temperature: The sampling temperature for generation (0.0 to 2.0).
        contextSize: The maximum context window size in tokens.
        openAiClient: The OpenAI async client instance.
        extraConfig: Additional configuration options for the model.
    """

    def __init__(
        self,
        provider: "BasicOpenAIProvider",
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        openAiClient: openai.AsyncOpenAI,
        extraConfig: Dict[str, Any] = {},
    ) -> None:
        """Initialize a basic OpenAI model instance.

        Args:
            provider: The provider instance that created this model.
            modelId: The identifier of the model to use in API calls.
            modelVersion: The version string of the model.
            temperature: The sampling temperature for generation (0.0 to 2.0).
            contextSize: The maximum context window size in tokens.
            openAiClient: The OpenAI async client instance.
            extraConfig: Additional configuration options for the model.

        Raises:
            ValueError: If required configuration is missing.
        """
        super().__init__(provider, modelId, modelVersion, temperature, contextSize, extraConfig)
        self._client = openAiClient
        self._supportTools = self._config.get("support_tools", False)

    def _getModelId(self) -> str:
        """Get the model identifier to use in API calls.

        This method can be overridden in subclasses to provide custom
        model ID mapping or transformation logic.

        Returns:
            The model identifier string to use in OpenAI API calls.
        """
        return self.modelId

    def _getExtraParams(self) -> Dict[str, Any]:
        """Get extra parameters for the API call.

        This method can be overridden in subclasses to add provider-specific
        parameters to the API request, such as custom headers, special options,
        or provider-specific features.

        Returns:
            A dictionary of extra parameters to include in the API call.
        """
        return {}

    async def _generateText(
        self, messages: Sequence[ModelMessage], tools: Optional[Sequence[LLMAbstractTool]] = None
    ) -> ModelRunResult:
        """Generate text using the OpenAI-compatible model.

        This method sends a chat completion request to the OpenAI API
        with the provided messages and optional tools. It handles response
        validation, token counting, and tool call extraction.

        Args:
            messages: A sequence of ModelMessage objects representing the
                conversation history. Each message should have a role and content.
            tools: An optional sequence of LLMAbstractTool objects that the model
                can call during generation. If provided and the model supports tools,
                they will be included in the API request.

        Returns:
            A ModelRunResult object containing:
            - The generated text content
            - Completion status (FINAL, TRUNCATED_FINAL, TOOL_CALLS, etc.)
            - Token usage statistics (input, output, total)
            - Any tool calls made by the model
            - The raw API response

        Raises:
            RuntimeError: If the OpenAI client is not initialized.
            NotImplementedError: If text generation is not supported by the model.
            ValueError: If the API response is invalid or malformed.
            Exception: For other API-related errors.
        """
        if not self._client:
            raise RuntimeError("OpenAI client not initialized, dood!")

        if not self._config.get("support_text", True):
            raise NotImplementedError(f"Text generation isn't supported by {self.modelId}, dood!")

        kwargs: Dict[str, Any] = {}
        if tools and self._supportTools:
            kwargs["tools"] = [tool.toJson() for tool in tools]
            kwargs["tool_choice"] = "auto"

        try:
            # Prepare base parameters
            params = {
                "model": self._getModelId(),
                "messages": [message.toDict("content") for message in messages],  # type: ignore
                "temperature": self.temperature,
                **kwargs,
            }

            # Add any extra parameters from subclasses
            params.update(self._getExtraParams())

            # Use OpenAI-compatible API
            response: Optional[ChatCompletion] = None
            try:
                response = await self._client.chat.completions.create(**params)
            except openai.BadRequestError as e:
                logger.exception(e)
                logger.error(f"Error generating text with OpenAI-compatible model: {e}")
                return ModelRunResult(
                    rawResult=response,
                    status=ModelResultStatus.ERROR,
                    error=e,
                )
                # raise ValueError(f"Invalid response from OpenAI-compatible model: 4#{response}")
            except Exception as e:
                logger.error(f"Error generating text with OpenAI-compatible model: {e}")
                # return ModelRunResult(
                #     rawResult=response,
                #     status=ModelResultStatus.ERROR,
                #     error=e,
                # )
                raise

            # for chunk in response:
            #   if chunk.choices[0].delta.content is not None:
            #       print(chunk.choices[0].delta.content, end="")

            # Response validation (for better error messages)
            if not isinstance(response, ChatCompletion):
                logger.error(f"response is not ChatCompletion, but {type(response)}: {response}")
                raise ValueError(f"Invalid response from OpenAI-compatible model: 0#{response}")
            if not hasattr(response, "choices"):
                logger.error(
                    f"response does not have field 'choices' {self.modelId}: {type(response).__name__}({response})"
                )
                raise ValueError(f"Invalid response from OpenAI-compatible model: 1#{response}")
            if not isinstance(response.choices, list):
                logger.error(
                    f"response.choices is not list, but a {type(response.choices).__name__}({response.choices})"
                )
                raise ValueError(f"Invalid response from OpenAI-compatible model: 2#{response}")
            if not response.choices:
                logger.error(f"response.choices is empty: {type(response.choices).__name__}({response.choices})")
                raise ValueError(f"Invalid response from OpenAI-compatible model: 3#{response}")

            inputTokens: Optional[int] = None
            outputTokens: Optional[int] = None
            totalTokens: Optional[int] = None

            if response.usage:
                inputTokens = response.usage.prompt_tokens
                outputTokens = response.usage.completion_tokens
                totalTokens = response.usage.total_tokens

            status = ModelResultStatus.UNSPECIFIED
            match response.choices[0].finish_reason:
                case "stop":
                    status = ModelResultStatus.FINAL
                case "length":
                    status = ModelResultStatus.TRUNCATED_FINAL
                case "tool_calls":
                    status = ModelResultStatus.TOOL_CALLS
                case "content_filter":
                    status = ModelResultStatus.CONTENT_FILTER
                case _:
                    logger.warning(f"Unknown LLM finish reason: {response.choices[0].finish_reason}")
                    status = ModelResultStatus.UNKNOWN

            retMessage = response.choices[0].message
            resText = retMessage.content if retMessage.content else ""

            toolCalls: List[LLMToolCall] = []
            if status == ModelResultStatus.TOOL_CALLS and retMessage.tool_calls:
                # ChatCompletionMessageFunctionToolCall(
                #    id='get_url_content',
                #    function=Function(
                #        arguments='{\"url\":\"https://ya.ru/\"}',
                #        name='get_url_content'),
                #        type='function',
                #        index=0,
                #    )
                logger.debug(f"ToolCalls: {retMessage.tool_calls}")
                toolCalls = [
                    LLMToolCall(
                        id=tool.id,
                        name=tool.function.name,
                        parameters=json.loads(tool.function.arguments),
                    )
                    for tool in retMessage.tool_calls
                    if tool.type == "function"
                ]

            return ModelRunResult(
                rawResult=response,
                status=status,
                resultText=resText,
                toolCalls=toolCalls,
                inputTokens=inputTokens,
                outputTokens=outputTokens,
                totalTokens=totalTokens,
            )

        except Exception as e:
            logger.error(f"Error running OpenAI-compatible model {self.modelId}: {e}")
            raise

    async def generateImage(self, messages: Sequence[ModelMessage]) -> ModelRunResult:
        """Generate an image using the OpenAI-compatible model.

        This method sends a chat completion request to the OpenAI API
        with image generation enabled. The model should support image
        generation capabilities.

        Args:
            messages: A sequence of ModelMessage objects representing the
                conversation history. The last message typically contains
                the image generation prompt.

        Returns:
            A ModelRunResult object containing:
            - The generated image as binary data
            - The MIME type of the generated image
            - Completion status
            - Token usage statistics
            - Any text content generated alongside the image
            - The raw API response

        Raises:
            NotImplementedError: If image generation is not supported by the model.
            ValueError: If the API response is invalid or malformed.
            Exception: For other API-related errors.
        """

        if not self._config.get("support_images", False):
            raise NotImplementedError(f"Image generation isn't supported by {self.modelId}, dood")

        kwargs: Dict[str, Any] = {}
        try:
            # Prepare base parameters
            params = {
                "model": self._getModelId(),
                "messages": [message.toDict("content") for message in messages],  # type: ignore
                "temperature": self.temperature,
                "modalities": ["image", "text"],
                **kwargs,
            }

            # Add any extra parameters from subclasses
            params.update(self._getExtraParams())

            # Use OpenAI-compatible API
            response: ChatCompletion = await self._client.chat.completions.create(**params)

            if not isinstance(response, ChatCompletion):
                raise ValueError(f"Invalid response from OpenAI-compatible model: {response}")

            # for chunk in response:
            #   if chunk.choices[0].delta.content is not None:
            #       print(chunk.choices[0].delta.content, end="")

            status = ModelResultStatus.UNSPECIFIED
            match response.choices[0].finish_reason:
                case "stop":
                    status = ModelResultStatus.FINAL
                case "length":
                    status = ModelResultStatus.TRUNCATED_FINAL
                case "tool_calls":
                    status = ModelResultStatus.TOOL_CALLS
                case "content_filter":
                    status = ModelResultStatus.CONTENT_FILTER
                case _:
                    status = ModelResultStatus.UNKNOWN

            # The generated image will be in the assistant message
            retMessage = response.choices[0].message

            inputTokens: Optional[int] = None
            outputTokens: Optional[int] = None
            totalTokens: Optional[int] = None

            if response.usage:
                inputTokens = response.usage.prompt_tokens
                outputTokens = response.usage.completion_tokens
                totalTokens = response.usage.total_tokens

            if hasattr(retMessage, "images"):
                images = getattr(retMessage, "images")
                if len(images) > 1:
                    logger.warning(f"Multiple ({len(images)}) images returned by model {self.modelId}: {images}")

                for i, image in enumerate(images):
                    imageDataURL = image["image_url"]["url"]  # Base64 data URL 'data:image/png;base64,...'
                    # Format is usually: data:[<mediatype>][;base64],<data>
                    header, encoded = imageDataURL.split(",", 1)
                    mimeType = header.split(";")[0].split(":")[1]

                    # Decode the base64 string to binary data
                    imageBytes = base64.b64decode(encoded)

                    # To not spam logs
                    images[i]["image_url"]["url"] = f"{header},...({len(encoded)})"

                    return ModelRunResult(
                        response,
                        status,
                        mediaMimeType=mimeType,
                        mediaData=imageBytes,
                        inputTokens=inputTokens,
                        outputTokens=outputTokens,
                        totalTokens=totalTokens,
                    )
            else:
                logger.error("No images field in model response")
                status = ModelResultStatus.ERROR

            return ModelRunResult(
                response,
                status,
                resultText=retMessage.content if retMessage.content is not None else "",
                inputTokens=inputTokens,
                outputTokens=outputTokens,
                totalTokens=totalTokens,
            )

        except Exception as e:
            logger.error(f"Error running OpenAI-compatible model {self.modelId}: {e}")
            raise


class BasicOpenAIProvider(AbstractLLMProvider):
    """Base class for OpenAI-compatible provider implementations.

    This class provides shared functionality for all OpenAI-compatible providers,
    including client initialization, model management, and configuration handling.
    It serves as a foundation for specific provider implementations like
    OpenRouter, Yandex Cloud OpenAI, and others.

    Attributes:
        _client: The OpenAI async client instance for API communication.
        config: Configuration dictionary for the provider.
        models: Dictionary of registered model instances.

    Args:
        config: Configuration dictionary containing provider settings such as:
            - api_key: The API key for authentication (required)
            - base_url: The base URL for the API endpoint
            - Additional provider-specific configuration options
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize a basic OpenAI provider instance.

        Args:
            config: Configuration dictionary containing provider settings.

        Raises:
            ValueError: If required configuration (e.g., api_key) is missing.
            ImportError: If the openai package is not available.
            Exception: If client initialization fails.
        """
        super().__init__(config)
        self._client: Optional[openai.AsyncOpenAI] = None
        self._initClient()

    def _getBaseUrl(self) -> str:
        """Get the base URL for the OpenAI API.

        This method must be implemented by subclasses to provide the
        appropriate base URL for their specific OpenAI-compatible API.

        Returns:
            The base URL string for the API endpoint.

        Raises:
            NotImplementedError: If not implemented by a subclass.
        """
        raise NotImplementedError("Subclasses must implement _get_base_url, dood!")

    def _getApiKey(self) -> str:
        """Get the API key from configuration.

        This method retrieves the API key from the provider configuration.
        It can be overridden in subclasses to implement custom key retrieval logic.

        Returns:
            The API key string for authentication.

        Raises:
            ValueError: If the api_key is not present in the configuration.
        """
        apiKey = self.config.get("api_key")
        if not apiKey:
            raise ValueError("api_key is required for OpenAI-compatible provider, dood!")
        return apiKey

    def _getClientParams(self) -> Dict[str, Any]:
        """Get additional client parameters for initialization.

        This method can be overridden in subclasses to provide additional
        parameters for the OpenAI client initialization, such as custom
        timeouts, proxies, or other client-specific settings.

        Returns:
            A dictionary of additional parameters to pass to the OpenAI client.
        """
        return {}

    def _initClient(self) -> None:
        """Initialize the OpenAI async client.

        This method creates and configures the OpenAI async client using
        the API key, base URL, and any additional parameters provided by
        subclasses. It handles initialization errors and logs the result.

        Raises:
            ImportError: If the openai package is not available.
            ValueError: If required configuration is missing.
            Exception: If client initialization fails for any other reason.
        """
        try:
            api_key = self._getApiKey()
            base_url = self._getBaseUrl()

            # Prepare client parameters
            client_params: Dict[str, Any] = {
                "api_key": api_key,
                "base_url": base_url,
            }
            client_params.update(self._getClientParams())

            self._client = openai.AsyncOpenAI(**client_params)

            logger.info(f"{self.__class__.__name__} initialized, dood!")

        except ImportError:
            logger.error("openai package not available, dood!")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise

    def _createModelInstance(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ) -> AbstractModel:
        """Create a model instance.

        This method must be implemented by subclasses to create the appropriate
        model instance type for their specific provider implementation.

        Args:
            name: The name to assign to the model instance.
            modelId: The identifier of the model to use.
            modelVersion: The version string of the model.
            temperature: The sampling temperature for generation.
            contextSize: The maximum context window size in tokens.
            extraConfig: Additional configuration options for the model.

        Returns:
            An AbstractModel instance configured with the provided parameters.

        Raises:
            NotImplementedError: If not implemented by a subclass.
        """
        raise NotImplementedError("Subclasses must implement _create_model_instance, dood!")

    def addModel(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ) -> AbstractModel:
        """Add an OpenAI-compatible model to the provider.

        This method creates and registers a new model instance with the provider.
        If a model with the same name already exists, it returns the existing
        instance instead of creating a new one.

        Args:
            name: The name to assign to the model instance. This name is used
                to retrieve the model later from the provider.
            modelId: The identifier of the model to use in API calls.
            modelVersion: The version string of the model.
            temperature: The sampling temperature for generation (0.0 to 2.0).
            contextSize: The maximum context window size in tokens.
            extraConfig: Additional configuration options for the model, such as:
                - support_tools: Boolean indicating tool support
                - support_images: Boolean indicating image generation support
                - Other provider-specific options

        Returns:
            The created or existing AbstractModel instance.

        Raises:
            RuntimeError: If the OpenAI client is not initialized.
            Exception: If model creation fails for any other reason.
        """
        if name in self.models:
            logger.warning(f"Model {name} already exists in {self.__class__.__name__}, dood!")
            return self.models[name]

        if not self._client:
            raise RuntimeError("OpenAI client not initialized, dood!")

        try:
            model = self._createModelInstance(name, modelId, modelVersion, temperature, contextSize, extraConfig)

            self.models[name] = model
            logger.info(f"Added {self.__class__.__name__} model {name} ({modelId}), dood!")
            return model

        except Exception as e:
            logger.error(f"Failed to add {self.__class__.__name__} model {name}: {e}")
            raise
