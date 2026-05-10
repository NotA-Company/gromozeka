"""Abstract base classes for LLM models and providers.

This module defines the core abstractions for the AI library, providing interfaces
for LLM model implementations and their providers. It includes:

- AbstractModel: Base class for all LLM model implementations
- AbstractLLMProvider: Base class for all LLM provider implementations

These abstractions enable consistent interaction with different LLM providers
(OpenAI, Yandex Cloud, OpenRouter, etc.) while allowing provider-specific
customizations.

    Example:
        To create a custom provider, inherit from AbstractLLMProvider and implement
        the addModel method. To create a custom model, inherit from AbstractModel
        and implement the _generateText, generateImage, and optionally
        _generateStructured methods.
"""

import datetime
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type, TypeVar

from lib import utils
from lib.stats import StatsStorage

from .models import (
    ERROR_STATUSES,
    LLMAbstractTool,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
    ModelStructuredResult,
)

logger = logging.getLogger(__name__)

_R = TypeVar("_R", ModelRunResult, ModelStructuredResult)


class AbstractModel(ABC):
    """Abstract base class for all LLM model implementations.

    This class provides the core interface for LLM models, including text and
    image generation capabilities, token estimation, and JSON logging support.
    Concrete implementations must inherit from this class and implement the
    abstract methods.

    Attributes:
        provider: The LLM provider instance that created this model.
        modelId: Unique identifier for the model.
        modelVersion: Version string for the model.
        temperature: Temperature setting for text generation (0.0 to 2.0).
        contextSize: Maximum context size in tokens.
        tiktokenEncoding: The tiktoken encoding name used for tokenization.
        tokensCountCoeff: Coefficient for token count estimation (default: 1.1).
        enableJSONLog: Whether JSON logging is enabled.
        jsonLogFile: Path to the JSON log file.
        jsonLogAddDateSuffix: Whether to append date suffix to log filename.

    Example:
        class CustomModel(AbstractModel):
            async def _generateText(self, messages, tools=None):
                # Implementation here
                pass

            async def generateImage(self, messages):
                # Implementation here
                pass
    """

    def __init__(
        self,
        provider: "AbstractLLMProvider",
        modelId: str,
        *,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Dict[str, Any] = {},
    ):
        """Initialize model with provider and configuration.

        Args:
            provider: The LLM provider instance that manages this model.
            modelId: Unique identifier for the model (e.g., "gpt-4", "yandexgpt").
            modelVersion: Version string for the model (e.g., "latest", "v1").
            temperature: Temperature setting for generation (0.0 = deterministic,
                2.0 = very creative).
            contextSize: Maximum context size in tokens.
            statsStorage: StatsStorage instance for recording LLM usage statistics.
            extraConfig: Additional configuration options for the model.

        Raises:
            ValueError: If temperature is not between 0.0 and 2.0.
            ValueError: If contextSize is negative.
        """
        self._config = extraConfig

        self.provider = provider
        self.modelId = modelId
        self.modelVersion = modelVersion
        self.temperature = temperature
        self.contextSize = contextSize

        self.tiktokenEncoding = "o200k_base"
        self.tokensCountCoeff = 1.1

        # JSON-logging is off by default
        self.enableJSONLog = False
        self.jsonLogFile = ""
        self.jsonLogAddDateSuffix = True

        # Stats storage for recording LLM usage statistics
        self.statsStorage: StatsStorage = statsStorage

    @abstractmethod
    async def _generateText(
        self, messages: Sequence[ModelMessage], tools: Optional[Sequence[LLMAbstractTool]] = None
    ) -> ModelRunResult:
        """Generate text using the model implementation.

        This is the internal method that must be implemented by concrete model
        classes. It handles the actual API call to the LLM provider.

        Args:
            messages: Sequence of message objects containing role and content.
            tools: Optional sequence of tools available to the model for function
                calling.

        Returns:
            ModelRunResult containing the generated text, status, and metadata.

        Raises:
            NotImplementedError: If not implemented by subclass.
            Exception: Provider-specific exceptions during generation.
        """
        raise NotImplementedError

    async def generateText(
        self,
        messages: Sequence[ModelMessage],
        tools: Optional[Sequence[LLMAbstractTool]] = None,
        *,
        fallbackModels: Optional[Sequence["AbstractModel"]] = None,
        consumerId: Optional[str] = None,
    ) -> ModelRunResult:
        """Generate text using the model with optional tools and fallback models.

        This is the public method for text generation. It performs token count
        estimation, context size validation, calls the internal _generateText
        method, and optionally logs the request/response in JSON format. When
        fallback models are provided, it delegates to _runWithFallback for
        automatic fallback logic.

        Args:
            messages: Sequence of message objects containing role and content.
            tools: Optional sequence of tools available to the model for function
                calling.
            fallbackModels: Optional list of alternative models to try if the
                primary model fails. The first model in the list is the primary,
                subsequent models are fallbacks. When provided, this method
                delegates to _runWithFallback for automatic fallback logic.
            consumerId: Optional consumer identifier for stats recording (e.g., chat ID).

        Returns:
            ModelRunResult containing the generated text, status, and metadata.
            Returns an error result if estimated tokens exceed twice the context size.

        Raises:
            Exception: If the model returns an error status (UNSPECIFIED,
                CONTENT_FILTER, UNKNOWN, or ERROR) and no fallback models are provided,
                or if all models (primary + fallbacks) fail.
        """
        if fallbackModels:
            # Use fallback mechanism when fallback models are provided
            return await self._runWithFallback(
                [self, *fallbackModels],
                lambda model: model.generateText(
                    messages=messages,
                    tools=tools,
                    fallbackModels=None,
                    consumerId=consumerId,
                ),
                ModelRunResult,
            )

        # Original logic when no fallbacks
        tokensCount = self.getEstimateTokensCount(messages)
        logger.debug(
            f"generateText(messages={len(messages)}, tools={len(tools) if tools else None}), "
            f"estimateTokens={tokensCount}, model: {self.provider}/{self.modelId}"
        )

        if self.contextSize and tokensCount > self.contextSize * 2:
            # If estimated tokens twice exceed model context, return error immediately
            return ModelRunResult(
                rawResult=None,
                status=ModelResultStatus.ERROR,
                error=Exception(
                    f"Context too large: Estimated tokens: {tokensCount} model context: {self.contextSize}"
                ),
            )

        try:
            ret = await self._generateText(messages=messages, tools=tools)
        except Exception as e:
            await self._recordAttemptStats(
                consumerId,
                ModelRunResult(rawResult=None, status=ModelResultStatus.ERROR, error=e),
                "text",
            )
            raise

        await self._recordAttemptStats(consumerId, ret, "text")

        if self.enableJSONLog:
            self.printJSONLog(messages, ret)
        return ret

    @abstractmethod
    async def _generateImage(self, messages: Sequence[ModelMessage]) -> ModelRunResult:
        """Generate an image using the model implementation.

        This is the internal method that must be implemented by concrete model
        classes that support image generation. It handles the actual API call
        to the LLM provider.

        Args:
            messages: Sequence of message objects containing the image generation
                prompt and context.

        Returns:
            ModelRunResult containing the generated image URL or data, status,
            and metadata.

        Raises:
            NotImplementedError: If not implemented by subclass.
            Exception: Provider-specific exceptions during image generation.
        """
        raise NotImplementedError

    async def generateImage(
        self,
        messages: Sequence[ModelMessage],
        *,
        fallbackModels: Optional[Sequence["AbstractModel"]] = None,
        consumerId: Optional[str] = None,
    ) -> ModelRunResult:
        """Generate an image using the model with optional fallback models.

        This is the public method for image generation. It supports automatic
        fallback to alternative models when the primary model fails. No token
        count estimation is performed for image generation (unlike text
        generation).

        Args:
            messages: Sequence of message objects containing the image generation
                prompt and context.
            fallbackModels: Optional list of alternative models to try if the
                primary model fails. The first model in the list is the primary,
                subsequent models are fallbacks. When provided, this method
                delegates to _runWithFallback for automatic fallback logic.
            consumerId: Optional consumer identifier for stats recording (e.g., chat ID).

        Returns:
            ModelRunResult containing the generated image URL or data, status,
            and metadata.

        Raises:
            Exception: If the model returns an error status and no fallback models
                are provided, or if all models (primary + fallbacks) fail.

        Note:
            Unlike generateText, this method does NOT perform token count
            estimation or context size validation before calling the provider.
            This preserves existing behavior for image generation.
        """
        if fallbackModels:
            return await self._runWithFallback(
                [self, *fallbackModels],
                lambda model: model.generateImage(
                    messages=messages,
                    fallbackModels=None,
                    consumerId=consumerId,
                ),
                ModelRunResult,
            )

        # Direct call with no fallbacks - invoke _generateImage and handle JSON logging
        try:
            ret = await self._generateImage(messages=messages)
        except Exception as e:
            await self._recordAttemptStats(
                consumerId,
                ModelRunResult(rawResult=None, status=ModelResultStatus.ERROR, error=e),
                "image",
            )
            raise

        await self._recordAttemptStats(consumerId, ret, "image")

        if self.enableJSONLog:
            self.printJSONLog(messages, ret)
        return ret

    async def _generateStructured(
        self,
        messages: Sequence[ModelMessage],
        schema: Dict[str, Any],
        *,
        schemaName: str = "response",
        strict: bool = True,
    ) -> ModelStructuredResult:
        """Provider-specific structured-output implementation.

        Concrete subclasses that support structured output must override this
        method. The default implementation raises NotImplementedError so that
        providers which have not opted in fail loudly.

        Schemas should follow OpenAI strict-mode rules (every property
        required, no extras); see ``generateStructured`` docstring for
        details.

        Args:
            messages: Conversation history.
            schema: A JSON Schema dict describing the desired response shape.
                Provider implementations pass this to the underlying API in
                whatever format the API expects (e.g. OpenAI wraps it in
                ``response_format = {"type": "json_schema", ...}``).
            schemaName: Identifier sent alongside the schema (OpenAI requires
                a ``name`` field; ignored where unused).
            strict: When True, ask the provider to enforce the schema strictly
                (OpenAI ``strict: true``). Some providers ignore this.

        Returns:
            ModelStructuredResult — see class docstring for status semantics.

        Raises:
            NotImplementedError: If structured output is not supported by this
                model (capability flag ``support_structured_output`` is False
                or the provider has not implemented it).
        """
        raise NotImplementedError(f"Structured output isn't implemented by {self.modelId}, dood!")

    async def generateStructured(
        self,
        messages: Sequence[ModelMessage],
        schema: Dict[str, Any],
        *,
        schemaName: str = "response",
        strict: bool = True,
        fallbackModels: Optional[Sequence["AbstractModel"]] = None,
        consumerId: Optional[str] = None,
    ) -> ModelStructuredResult:
        """Generate structured output with automatic fallback to another model.

        Attempts to generate structured output using the current model. If the
        generation fails or returns an error status (UNSPECIFIED, CONTENT_FILTER,
        UNKNOWN, or ERROR), it automatically retries using the next fallback model
        in the list.

        Args:
            messages: Conversation history.
            schema: JSON Schema dict describing the desired response shape.
            schemaName: Schema identifier (provider-dependent).
            strict: Strict-mode flag (provider-dependent).
            fallbackModels: Optional list of alternative models to try if the
                primary model fails. The first model in the list is the primary,
                subsequent models are fallbacks. When provided, this method
                delegates to _runWithFallback for automatic fallback logic.
            consumerId: Optional consumer identifier for stats recording (e.g., chat ID).

        Returns:
            ModelStructuredResult with status, parsed data, token usage, etc.
            The result will have ``isFallback`` set to True if a fallback model
            was used.

        Raises:
            NotImplementedError: If this model does not support structured
                output (capability flag ``support_structured_output`` is False).
        """
        if not self._config.get("support_structured_output", False):
            raise NotImplementedError(f"Structured output isn't supported by {self.modelId}, dood!")

        # If fallback models provided, use the fallback mechanism
        if fallbackModels:
            return await self._runWithFallback(
                [self, *fallbackModels],
                lambda model: model.generateStructured(
                    messages=messages,
                    schema=schema,
                    schemaName=schemaName,
                    strict=strict,
                    fallbackModels=None,
                    consumerId=consumerId,
                ),
                ModelStructuredResult,
            )

        # Original logic when no fallbacks
        tokensCount = self.getEstimateTokensCount(messages) + self.getEstimateTokensCount(schema)
        logger.debug(
            f"generateStructured(messages={len(messages)}, schema_keys={list(schema.keys())}), "
            f"estimateTokens={tokensCount}, model: {self.provider}/{self.modelId}"
        )

        if self.contextSize and tokensCount > self.contextSize * 2:
            return ModelStructuredResult(
                rawResult=None,
                status=ModelResultStatus.ERROR,
                error=Exception(
                    f"Context too large: estimated tokens {tokensCount} " f"vs model context {self.contextSize}"
                ),
            )

        try:
            ret = await self._generateStructured(
                messages=messages,
                schema=schema,
                schemaName=schemaName,
                strict=strict,
            )
        except Exception as e:
            await self._recordAttemptStats(
                consumerId,
                ModelRunResult(rawResult=None, status=ModelResultStatus.ERROR, error=e),
                "structured",
            )
            raise

        await self._recordAttemptStats(consumerId, ret, "structured")

        if self.enableJSONLog:
            self.printJSONLog(messages, ret)
        return ret

    async def _runWithFallback(
        self,
        models: Sequence["AbstractModel"],
        call: Callable[["AbstractModel"], Awaitable[_R]],
        retType: Type[_R],
    ) -> _R:
        """Run `call(model)` over `models` until one succeeds.

        Iterates the list in order. For each model, invokes the callable and
        inspects the result's status. A result whose status is in ERROR_STATUSES
        (or a raised exception) is treated as failure and the next model is tried.

        If all models fail, the last attempted model's result is returned —
        matching the pre-refactor generate*WithFallBack behavior.

        isFallback is set to True on the returned result iff it came from any
        model other than models[0].

        Each model's generate* method records stats when invoked (the lambda
        passes fallbackModels=None, hitting the no-fallback path).

        Args:
            models: Non-empty ordered list. models[0] is the primary, the rest
                are fallbacks in preference order.
            call: Callable that takes a model and returns an awaitable result
                (ModelRunResult or ModelStructuredResult). Must invoke the
                PUBLIC generate* method with fallbackModels=None so each attempt
                gets the full pipeline (context check + JSON log + stats recording)
                without recursing into this helper.

        Returns:
            The result of the first successful model, or the last attempted
            model's result on total failure.

        Raises:
            ValueError: If models is empty.
        """
        if not models:
            raise ValueError("models list cannot be empty")

        # Track the last result from each model attempt
        lastResult: _R = retType(rawResult=None, status=ModelResultStatus.UNSPECIFIED)

        for i, model in enumerate(models):
            result: _R
            try:
                result = await call(model)
            except Exception as e:
                # Exception from model is treated as failure - create error result
                logger.error(f"Exception from model {model.modelId}: {e}")
                result = retType(
                    rawResult=None,
                    status=ModelResultStatus.ERROR,
                    error=e,
                )
            lastResult = result

            # Mark as fallback if this is not the primary model
            if i > 0:
                result.setFallback(True)

            # Check if this model succeeded
            if result.status not in ERROR_STATUSES:
                logger.debug(f"Model {model.modelId} succeeded on attempt {i + 1}")
                return result

            # Model failed - log and continue to next
            logger.debug(f"Model {model.modelId} returned error status {result.status.name}")

        # All models failed - return the last result
        # This is safe because models is guaranteed to be non-empty,
        # so lastResult is definitely assigned by this point
        return lastResult

    def getEstimateTokensCount(self, data: Any) -> int:
        """Get estimated number of tokens in given data.

        This method estimates the token count by converting the data to a string
        and using a heuristic: average token length is 3.5 characters. The result
        is multiplied by a coefficient (default 1.1) to ensure we don't underestimate.

        Args:
            data: Data to estimate token count for. Can be a string or any object
                convertible to JSON.

        Returns:
            Estimated number of tokens in the data.

        Example:
            >>> model.getEstimateTokensCount("Hello world")
            4
            >>> model.getEstimateTokensCount({"key": "value"})
            3
        """
        text = ""
        if isinstance(data, str):
            text = data
        else:
            text = json.dumps(data, ensure_ascii=False, default=str)
        # According my experience, average, each token is 3-4 characters long, so use 3.5
        # For being conservative
        tokensCount = len(text) / 3.5
        # As we use estimated token count, it won't count tokens properly,
        # so we need to multiply by some coefficient to be sure
        return int(tokensCount * self.tokensCountCoeff)

    def getInfo(self) -> Dict[str, Any]:
        """Get model information and configuration.

        Returns a dictionary containing the model's metadata including provider,
        model ID, version, temperature, context size, and capabilities.

        Returns:
            Dictionary with model metadata containing:
                - provider: Provider class name
                - model_id: Model identifier
                - model_version: Model version
                - temperature: Temperature setting
                - context_size: Maximum context size
                - support_tools: Whether the model supports tools
                - support_text: Whether the model supports text generation
                - support_images: Whether the model supports image generation
                - tier: Model tier (e.g., "bot_owner")
                - extra: Additional configuration options

        Example:
            >>> model.getInfo()
            {
                'provider': 'OpenAIProvider',
                'model_id': 'gpt-4',
                'model_version': 'latest',
                'temperature': 0.7,
                'context_size': 8192,
                'support_tools': True,
                'support_text': True,
                'support_images': False,
                'tier': 'bot_owner',
                'extra': {}
            }
        """
        return {
            "provider": self.provider.__class__.__name__,
            "model_id": self.modelId,
            "model_version": self.modelVersion,
            "temperature": self.temperature,
            "context_size": self.contextSize,
            "support_tools": self._config.get("support_tools", False),
            "support_text": self._config.get("support_text", True),
            "support_images": self._config.get("support_images", False),
            "support_structured_output": self._config.get("support_structured_output", False),
            "tier": self._config.get("tier", "bot_owner"),
            "extra": self._config.copy(),
        }

    def __str__(self) -> str:
        """Return string representation of the model.

        Returns:
            String in format "modelId@modelVersion (provider: ProviderName)".
        """
        return f"{self.modelId}@{self.modelVersion} (provider: {self.provider.__class__.__name__})"

    def setupJSONLogging(self, file: str, addDateSuffix: bool) -> None:
        """Setup JSON logging of request-response pairs.

        Configure the model to log requests and responses in JSON format to a file.
        When enabled, each request-response pair will be written as a JSON object
        to the specified log file. This is useful for debugging, analysis, and
        auditing model interactions.

        Args:
            file: Path to the log file where JSON entries will be written.
            addDateSuffix: If True, append the current date (YYYY-MM-DD) to the
                filename, creating a new log file each day.

        Example:
            >>> model.setupJSONLogging("/tmp/model_logs.jsonl", True)
            >>> # Logs will be written to /tmp/model_logs.jsonl.2025-01-15
        """
        self.enableJSONLog = True
        self.jsonLogFile = file
        self.jsonLogAddDateSuffix = addDateSuffix

    def printJSONLog(self, messages: Sequence[ModelMessage], result: ModelRunResult) -> None:
        """Write a request-response pair to the JSON log file.

        This method writes the conversation history (messages) and model response
        to a JSON log file. Each entry contains the timestamp, status, request,
        and response. Empty responses are not logged.

        Args:
            messages: List of message objects that were sent to the model.
            result: The model's response result containing status, text, and metadata.

        Raises:
            IOError: If unable to write to the log file.

        Note:
            The log file is opened in append mode, so multiple sessions can write
            to the same file. Each entry is written as a single line of JSON.
        """
        if not result.resultText:
            # Do not log empty results
            return

        now = datetime.datetime.now(tz=datetime.timezone.utc)

        filename = self.jsonLogFile
        if self.jsonLogAddDateSuffix:
            todayStr = now.strftime("%Y-%m-%d")
            filename = filename + "." + todayStr

        data = {
            "date": now.isoformat(),
            "status": result.status,
            "request": [message.toDict("content") for message in messages],
            "response": result.resultText,
            "model": self.modelId,
            "provider": type(self.provider).__name__,
            "raw": str(result.result),
        }
        with open(filename, "a") as f:
            f.write(utils.jsonDumps(data) + "\n")

    async def _recordAttemptStats(
        self,
        consumerId: Optional[str],
        result: ModelRunResult,
        generationType: str,
    ) -> None:
        """Record stats for a single model attempt. Best-effort — never raises.

        Args:
            consumerId: Consumer identifier (e.g. chat ID).
            result: The model result with tokens and status.
            generationType: 'text', 'structured', or 'image'.
        """
        try:
            info = self.getInfo()
            await self.statsStorage.record(
                stats={
                    f"generation_{generationType}": 1,
                    "request_count": 1,
                    "input_tokens": result.inputTokens or 0,
                    "output_tokens": result.outputTokens or 0,
                    "total_tokens": result.totalTokens or 0,
                    "is_error": 1 if result.status in ERROR_STATUSES else 0,
                    f"status_{result.status.name}": 1,
                },
                consumerId=consumerId,
                labels={
                    "modelName": info.get("model_id", "unknown"),
                    "modelId": info.get("model_id", "unknown"),
                    "provider": info.get("provider", "unknown"),
                    "generationType": generationType,
                    "status": result.status.name,
                },
            )
        except Exception as e:
            logger.error("Failed to record attempt stats")
            logger.exception(e)


class AbstractLLMProvider(ABC):
    """Abstract base class for all LLM provider implementations.

    This class provides the core interface for LLM providers, which manage
    multiple model instances. Concrete implementations must inherit from this
    class and implement the addModel method.

    Attributes:
        config: Provider-specific configuration dictionary.
        models: Dictionary mapping model names to AbstractModel instances.

    Example:
        class CustomProvider(AbstractLLMProvider):
            def addModel(self, name, modelId, modelVersion, temperature,
                        contextSize, extraConfig={}):
                model = CustomModel(self, modelId, modelVersion, temperature,
                                   contextSize, extraConfig)
                self.models[name] = model
                return model
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize provider with configuration.

        Args:
            config: Provider-specific configuration dictionary. May include API
                keys, endpoints, default settings, and other provider-specific
                options.

        Example:
            >>> config = {"api_key": "sk-...", "endpoint": "https://api.example.com"}
            >>> provider = CustomProvider(config)
        """
        self.config = config
        self.models: Dict[str, AbstractModel] = {}

    @abstractmethod
    def addModel(
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
        """Add a model to this provider.

        This method must be implemented by concrete provider classes to create
        and register a model instance with the provider.

        Args:
            name: Human-readable name for the model (used as key in models dict).
            modelId: Provider-specific model identifier (e.g., "gpt-4", "yandexgpt").
            modelVersion: Version string for the model (e.g., "latest", "v1").
            temperature: Temperature setting for generation (0.0 to 2.0).
            contextSize: Maximum context size in tokens.
            statsStorage: StatsStorage instance for recording LLM usage statistics.
            extraConfig: Additional configuration options for the model.

        Returns:
            The created AbstractModel instance.

        Raises:
            NotImplementedError: If not implemented by subclass.
            ValueError: If a model with the same name already exists.
        """
        pass

    def getModel(self, name: str) -> Optional[AbstractModel]:
        """Get a model by name.

        Retrieve a model instance from the provider's model registry.

        Args:
            name: The name of the model to retrieve.

        Returns:
            The AbstractModel instance if found, None otherwise.

        Example:
            >>> model = provider.getModel("gpt4")
            >>> if model:
            ...     result = await model.generateText(messages)
        """
        return self.models.get(name)

    def listModels(self) -> List[str]:
        """List all available model names.

        Returns a list of all model names registered with this provider.

        Returns:
            List of model names (keys from the models dictionary).

        Example:
            >>> provider.listModels()
            ['gpt4', 'gpt35', 'claude3']
        """
        return list(self.models.keys())

    def getModelInfo(self, name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific model.

        Retrieve detailed information about a model including its configuration
        and capabilities.

        Args:
            name: The name of the model to get information for.

        Returns:
            Dictionary with model information if the model exists, None otherwise.
            See AbstractModel.getInfo() for the structure of the returned dict.

        Example:
            >>> info = provider.getModelInfo("gpt4")
            >>> print(info['model_id'])
            gpt-4
        """
        model = self.getModel(name)
        return model.getInfo() if model else None

    def deleteModel(self, name: str) -> bool:
        """Delete a model from this provider.

        Remove a model from the provider's model registry.

        Args:
            name: The name of the model to delete.

        Returns:
            True if the model was found and deleted, False if the model was not
            found.

        Example:
            >>> if provider.deleteModel("old_model"):
            ...     print("Model deleted successfully")
        """
        if name in self.models:
            del self.models[name]
            return True
        return False

    def __str__(self) -> str:
        """Return string representation of the provider.

        Returns:
            String in format "ProviderName (N models)" where N is the number of
            registered models.
        """
        return f"{self.__class__.__name__} ({len(self.models)} models)"
