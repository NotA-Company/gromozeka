"""Basic OpenAI provider and model base classes for shared functionality.

This module provides base classes for OpenAI-compatible AI providers and models.
It implements common functionality for interacting with OpenAI-compatible APIs,
including text generation, image generation, and tool calling capabilities.

Classes:
    _OpenAICallOutcome: Decoded envelope of an OpenAI-compatible chat.completions.create call.
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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import openai
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_message import ChatCompletionMessage

from lib.stats import StatsStorage

from ..abstract import AbstractLLMProvider, AbstractModel
from ..models import (
    LLMAbstractTool,
    LLMToolCall,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
    ModelStructuredResult,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class _OpenAICallOutcome:
    """Decoded envelope of an OpenAI-compatible chat.completions.create call.

    Used by ``_executeChatCompletion`` to hand back everything the public
    ``_generateText`` / ``_generateStructured`` methods need without
    forcing them to share final result-construction logic.

    On the BadRequestError path, ``response`` is None, ``status`` is
    ``ERROR``, ``error`` is set, and the textual / token fields are
    placeholders. On the success path, ``error`` is None and the rest is
    populated from the API response.

    Attributes:
        response: The raw ChatCompletion (or None on early-exit error).
        status: Mapped status from finish_reason (or ERROR on exception).
        resText: ``response.choices[0].message.content or ""`` (or "" on error).
        retMessage: ``response.choices[0].message`` (or None on error). Kept
            so callers can pull tool_calls out of it without re-walking the
            response.
        inputTokens: From ``response.usage.prompt_tokens`` (or None on error).
        outputTokens: From ``response.usage.completion_tokens`` (or None on error).
        totalTokens: From ``response.usage.total_tokens`` (or None on error).
        error: The captured exception when an early-exit happened.
    """

    # Decoded envelope of an OpenAI-compatible chat.completions.create call.
    response: Optional[ChatCompletion]
    """The raw ChatCompletion or None on early-exit error."""
    status: ModelResultStatus
    """Mapped status from finish_reason or ERROR on exception."""
    resText: str
    """Response content or empty string on error."""
    retMessage: Optional[ChatCompletionMessage]
    """Response message or None on error."""
    inputTokens: Optional[int]
    """Number of input tokens or None on error."""
    outputTokens: Optional[int]
    """Number of output tokens or None on error."""
    totalTokens: Optional[int]
    """Total number of tokens or None on error."""
    error: Optional[Exception]
    """The captured exception when an early-exit happened."""


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
        *,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Optional[Dict[str, Any]] = None,
        openAiClient: openai.AsyncOpenAI,
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
        super().__init__(
            provider,
            modelId,
            modelVersion=modelVersion,
            temperature=temperature,
            contextSize=contextSize,
            statsStorage=statsStorage,
            extraConfig=extraConfig,
        )
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

    async def _executeChatCompletion(self, params: Dict[str, Any]) -> _OpenAICallOutcome:
        """Call the OpenAI-compatible API and decode the response envelope.

        Caller owns building ``params`` (incl. ``response_format``, ``tools``,
        extras from ``_getExtraParams``) and constructing the final result
        type. This helper handles only the universal mechanical bits:

        * client-not-initialized guard
        * the ``chat.completions.create`` call
        * the ``BadRequestError`` early-exit path
        * other-exception re-raise
        * token extraction from ``response.usage``
        * ``finish_reason`` -> ``ModelResultStatus`` mapping
        * ``resText`` extraction

        Args:
            params: Fully-built kwargs for ``chat.completions.create``.

        Returns:
            _OpenAICallOutcome capturing the decoded envelope or the error
            early-exit. See class docstring for status semantics.

        Raises:
            RuntimeError: If ``self._client`` is not initialised.
            Exception: Any non-BadRequestError exception from the API call is
                re-raised unchanged (matches the prior behaviour of
                ``_generateText`` / ``_generateStructured``).
        """
        if not self._client:
            raise RuntimeError("OpenAI client not initialized, dood!")

        try:
            response: ChatCompletion = await self._client.chat.completions.create(**params)
        except openai.BadRequestError as e:
            logger.exception(e)
            logger.error(f"Error from OpenAI-compatible model: {e}")
            return _OpenAICallOutcome(
                response=None,
                status=ModelResultStatus.ERROR,
                resText="",
                retMessage=None,
                inputTokens=None,
                outputTokens=None,
                totalTokens=None,
                error=e,
            )
        except Exception as e:
            logger.error(f"Error from OpenAI-compatible model: {e}")
            raise

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
            logger.error(f"response.choices is not list, but a {type(response.choices).__name__}({response.choices})")
            raise ValueError(f"Invalid response from OpenAI-compatible model: 2#{response}")
        if not response.choices:
            logger.error(f"response.choices is empty: {type(response.choices).__name__}({response.choices})")
            raise ValueError(f"Invalid response from OpenAI-compatible model: 3#{response}")

        inputTokens: Optional[int] = response.usage.prompt_tokens if response.usage else None
        outputTokens: Optional[int] = response.usage.completion_tokens if response.usage else None
        totalTokens: Optional[int] = response.usage.total_tokens if response.usage else None

        finishReason = response.choices[0].finish_reason
        status = ModelResultStatus.UNSPECIFIED
        match finishReason:
            case "stop":
                status = ModelResultStatus.FINAL
            case "length":
                status = ModelResultStatus.TRUNCATED_FINAL
            case "tool_calls":
                status = ModelResultStatus.TOOL_CALLS
            case "content_filter":
                status = ModelResultStatus.CONTENT_FILTER
            case _:
                logger.warning(f"Unknown LLM finish reason: {finishReason}")
                status = ModelResultStatus.UNKNOWN

        retMessage = response.choices[0].message
        resText = retMessage.content if retMessage.content else ""

        return _OpenAICallOutcome(
            response=response,
            status=status,
            resText=resText,
            retMessage=retMessage,
            inputTokens=inputTokens,
            outputTokens=outputTokens,
            totalTokens=totalTokens,
            error=None,
        )

    async def _generateText(
        self,
        messages: Sequence[ModelMessage],
        tools: Optional[Sequence[LLMAbstractTool]] = None,
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
            Exception: For other API-related errors.
        """
        if not self._config.get("support_text", True):
            raise NotImplementedError(f"Text generation isn't supported by {self.modelId}, dood!")

        # --- build params (text-specific) ---
        kwargs: Dict[str, Any] = {}
        if tools and self._supportTools:
            kwargs["tools"] = [tool.toJson() for tool in tools]
            kwargs["tool_choice"] = "auto"

        params: Dict[str, Any] = {
            "model": self._getModelId(),
            "messages": [message.toDict("content") for message in messages],
            "temperature": self.temperature,
            **kwargs,
        }
        params.update(self._getExtraParams())

        # --- call + decode envelope (shared) ---
        outcome = await self._executeChatCompletion(params)
        if outcome.error is not None:
            return ModelRunResult(
                rawResult=outcome.response,
                status=outcome.status,
                error=outcome.error,
                inputTokens=outcome.inputTokens,
                outputTokens=outcome.outputTokens,
                totalTokens=outcome.totalTokens,
            )

        # --- text-specific tail: tool calls ---
        toolCalls: List[LLMToolCall] = []
        if (
            outcome.status == ModelResultStatus.TOOL_CALLS
            and outcome.retMessage is not None
            and outcome.retMessage.tool_calls
        ):
            logger.debug(f"ToolCalls: {outcome.retMessage.tool_calls}")
            toolCalls = [
                LLMToolCall(
                    id=tool.id,
                    name=tool.function.name,
                    parameters=json.loads(tool.function.arguments),
                )
                for tool in outcome.retMessage.tool_calls
                if tool.type == "function"
            ]

        return ModelRunResult(
            rawResult=outcome.response,
            status=outcome.status,
            resultText=outcome.resText,
            toolCalls=toolCalls,
            inputTokens=outcome.inputTokens,
            outputTokens=outcome.outputTokens,
            totalTokens=outcome.totalTokens,
        )

    async def _generateStructured(
        self,
        messages: Sequence[ModelMessage],
        schema: Dict[str, Any],
        *,
        schemaName: str = "response",
        strict: bool = True,
    ) -> ModelStructuredResult:
        """Generate a structured (JSON) response using the OpenAI-compatible model.

        Mirrors ``_generateText`` with three key differences: no ``tools`` parameter
        is accepted (structured output and tool calls are mutually exclusive),
        a ``response_format`` of type ``json_schema`` is added to the request
        parameters, and the response text is parsed as a JSON object before returning
        a ``ModelStructuredResult``.

        On a successful finish (``stop`` or ``length``) the response content is
        parsed as JSON. If the parsed value is not a dict a ``ValueError`` is raised
        and the method returns an ERROR result with the raw text preserved so callers
        can inspect it. An empty response (empty string from the model) is treated
        as ERROR as well.

        This method assumes the caller has already verified that the model supports
        structured output (via the ``support_structured_output`` config flag). The
        public ``generateStructured`` method performs that check before delegating.

        Args:
            messages: Conversation history as a sequence of ``ModelMessage`` objects.
            schema: A JSON Schema dict describing the desired response shape.
                Passed verbatim in the ``response_format.json_schema.schema`` field.
                For strict‑mode compatibility, see the schema requirements in
                ``AbstractModel.generateStructured``.
            schemaName: Identifier sent alongside the schema in the
                ``response_format.json_schema.name`` field. Defaults to ``"response"``.
            strict: When ``True``, the provider is asked to enforce the schema strictly
                (``response_format.json_schema.strict = True``). Defaults to ``True``.

        Returns:
            A ``ModelStructuredResult`` containing:
            - ``status``: ``FINAL``, ``TRUNCATED_FINAL``, ``CONTENT_FILTER``,
              ``TOOL_CALLS``, ``UNKNOWN``, or ``ERROR``.
            - ``data``: Parsed JSON dict on success; ``None`` on parse failure,
              content filter, or other error.
            - ``resultText``: Raw text emitted by the model (before parsing).
            - ``error``: Set when an error occurred (``BadRequestError``,
              ``JSONDecodeError``, ``ValueError``, etc.).
            - ``inputTokens``, ``outputTokens``, ``totalTokens``: Token usage.

        Raises:
            RuntimeError: If the OpenAI client is not initialized.
            Exception: For unhandled API‑level errors (re‑raised after logging).
        """
        # --- build params (structured-specific) ---
        # No tools — structured and tool calls are mutually exclusive.
        params: Dict[str, Any] = {
            "model": self._getModelId(),
            "messages": [message.toDict("content") for message in messages],
            "temperature": self.temperature,
        }
        # Add any extra parameters from subclasses (e.g. extra_headers for OpenRouter)
        params.update(self._getExtraParams())
        # Add the structured-output response format AFTER extra params so it is never clobbered
        params["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schemaName,
                "schema": schema,
                "strict": strict,
            },
        }

        # --- call + decode envelope (shared) ---
        outcome = await self._executeChatCompletion(params)
        if outcome.error is not None:
            return ModelStructuredResult(
                rawResult=outcome.response,
                status=outcome.status,
                error=outcome.error,
                inputTokens=outcome.inputTokens,
                outputTokens=outcome.outputTokens,
                totalTokens=outcome.totalTokens,
            )

        # --- structured-specific tail: JSON parse ---
        data: Optional[Dict[str, Any]] = None
        if outcome.status in (ModelResultStatus.FINAL, ModelResultStatus.TRUNCATED_FINAL):
            try:
                if not outcome.resText:
                    raise ValueError("Structured output: model returned empty content")
                parsed = json.loads(outcome.resText)
                if not isinstance(parsed, dict):
                    raise ValueError(f"Structured output expected JSON object, got {type(parsed).__name__}")
                data = parsed
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to parse structured output from {self.modelId}: {e}")
                return ModelStructuredResult(
                    rawResult=outcome.response,
                    status=ModelResultStatus.ERROR,
                    data=None,
                    resultText=outcome.resText,
                    error=e,
                    inputTokens=outcome.inputTokens,
                    outputTokens=outcome.outputTokens,
                    totalTokens=outcome.totalTokens,
                )

        return ModelStructuredResult(
            rawResult=outcome.response,
            status=outcome.status,
            data=data,
            resultText=outcome.resText,
            inputTokens=outcome.inputTokens,
            outputTokens=outcome.outputTokens,
            totalTokens=outcome.totalTokens,
        )

    async def _generateImage(self, messages: Sequence[ModelMessage]) -> ModelRunResult:
        """Generate an image using the OpenAI-compatible model.

        Sends a chat completion request with image generation enabled via the
        ``modalities`` parameter. Delegates the API call, response validation,
        finish_reason mapping, and token extraction to
        :meth:`_executeChatCompletion`, then extracts the generated image from
        ``outcome.retMessage.images``.

        Args:
            messages: A sequence of ModelMessage objects representing the
                conversation history. The last message typically contains
                the image generation prompt.

        Returns:
            A ModelRunResult object containing:
            - The generated image as binary data (``mediaData``)
            - The MIME type of the generated image (``mediaMimeType``)
            - Completion status
            - Token usage statistics
            - Any text content generated alongside the image
            - The raw API response

        Raises:
            RuntimeError: If the OpenAI client is not initialized.
            NotImplementedError: If image generation is not supported by the model.
            Exception: For other API-related errors.
        """

        if not self._config.get("support_images", False):
            raise NotImplementedError(f"Image generation isn't supported by {self.modelId}, dood")

        # --- build params (image-specific) ---
        params: Dict[str, Any] = {
            "model": self._getModelId(),
            "messages": [message.toDict("content") for message in messages],
            "temperature": self.temperature,
        }
        params.update(self._getExtraParams())
        # Add modalities AFTER extra params so it is never clobbered
        params["modalities"] = ["image", "text"]

        # --- call + decode envelope (shared) ---
        outcome = await self._executeChatCompletion(params)
        if outcome.error is not None or outcome.retMessage is None:
            return ModelRunResult(
                rawResult=outcome.response,
                status=outcome.status,
                error=outcome.error,
                inputTokens=outcome.inputTokens,
                outputTokens=outcome.outputTokens,
                totalTokens=outcome.totalTokens,
            )

        # --- image-specific tail: extract images from retMessage ---
        if hasattr(outcome.retMessage, "images"):
            images = getattr(outcome.retMessage, "images")
            if len(images) > 1:
                logger.warning(
                    f"Multiple ({len(images)}) images returned by model {self.modelId}: "
                    + repr([f"{repr(image)[:64]}... ({len(repr(image))} bytes)" for image in images])
                )

            for i, image in enumerate(images):
                imageDataURL: str = image["image_url"]["url"]  # data:image/png;base64,...
                header, encoded = imageDataURL.split(",", 1)
                mimeType: str = header.split(";")[0].split(":")[1]

                # Decode the base64 string to binary data
                imageBytes: bytes = base64.b64decode(encoded)

                # Truncate the URL in-place to avoid spamming logs
                images[i]["image_url"]["url"] = f"{header},...({len(encoded)})"

                return ModelRunResult(
                    rawResult=outcome.response,
                    status=outcome.status,
                    resultText=outcome.resText,
                    mediaMimeType=mimeType,
                    mediaData=imageBytes,
                    inputTokens=outcome.inputTokens,
                    outputTokens=outcome.outputTokens,
                    totalTokens=outcome.totalTokens,
                )

        # No images field in response — fall back to text-only result
        logger.error("No images field in model response")
        return ModelRunResult(
            rawResult=outcome.response,
            status=ModelResultStatus.ERROR,
            resultText=outcome.resText,
            inputTokens=outcome.inputTokens,
            outputTokens=outcome.outputTokens,
            totalTokens=outcome.totalTokens,
        )


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
        *,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Optional[Dict[str, Any]] = None,
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

    async def listRemoteModels(self) -> Dict[str, Dict[str, Any]]:
        """List models available from the OpenAI-compatible API.

        Uses the OpenAI SDK's models.list() endpoint.
        Falls back to empty dict if the client is not initialized.

        Returns:
            Dict[str, Dict[str, Any]]: Model ID → settings dict.
        """
        if self._client is None:
            logger.warning("Cannot list remote models: client not initialized")
            return {}

        try:
            result: Dict[str, Dict[str, Any]] = {}
            async for model in await self._client.models.list():
                result[model.id] = model.model_dump()
            return result
        except Exception as e:
            logger.error(f"Failed to list remote models: {e}")
            return {}

    def addModel(
        self,
        name: str,
        *,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Optional[Dict[str, Any]] = None,
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
            model = self._createModelInstance(
                name,
                modelId=modelId,
                modelVersion=modelVersion,
                temperature=temperature,
                contextSize=contextSize,
                statsStorage=statsStorage,
                extraConfig=extraConfig,
            )

            self.models[name] = model
            logger.info(f"Added {self.__class__.__name__} model {name} ({modelId}), dood!")
            return model

        except Exception as e:
            logger.error(f"Failed to add {self.__class__.__name__} model {name}: {e}")
            raise
