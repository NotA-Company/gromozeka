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

import asyncio
import datetime
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type, TypeVar

from lib import utils
from lib.stats import StatsStorage

from .models import (
    ERROR_STATUSES,
    LLMAbstractTool,
    ModelImageMessage,
    ModelImagesMessage,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
    ModelStructuredResult,
)

logger = logging.getLogger(__name__)

_R = TypeVar("_R", ModelRunResult, ModelStructuredResult)

_IMAGE_DATA_URI_PREFIX = "data:image/"
"""Prefix identifying an image-typed base64 data URI (``data:image/<subtype>;base64,...``).

Used by :func:`_isImageDataUrl` to structurally identify inline image payloads.
"""

_IMAGE_DATA_PLACEHOLDER = "<image-data>"
"""Short replacement for an inline base64 image payload (native-vision design v1 §3.4).

Used by :func:`_estimateTokenView` so image tokens are invisible to the
char-based token estimator.
"""


def _isImageDataUrl(url: object) -> bool:
    """Check whether a serialized ``image_url.url`` value is an inline image data URI.

    Only image-typed base64 data URIs qualify: non-image MIME types
    (``data:text/plain;base64,...``), remote URLs (``https://...``), and
    already-placeholder values are estimation-relevant text and stay counted.

    Args:
        url: The ``url`` value extracted from an ``image_url`` block (any
            serialized JSON scalar; narrowed by isinstance).

    Returns:
        bool: True only for ``data:image/...;base64,...`` strings.
    """
    return isinstance(url, str) and url.startswith(_IMAGE_DATA_URI_PREFIX) and ";base64," in url


def _isMessageDict(value: object) -> bool:
    """Check whether a value is a serialized chat message.

    A serialized chat message is a dict with a string ``role`` key plus a
    ``content`` key — the shape ``ModelMessage.toDict()`` and provider
    payloads emit. A JSON Schema describing messages does not qualify: its
    ``role`` value is itself a schema dict, not a string.

    Used only by :func:`_isMessageList` for the trusted-input boundary check
    in :meth:`AbstractModel.getEstimateTokensCount`. It is deliberately NOT
    applied to values discovered during the recursive walk: a message-shaped
    dict nested inside arbitrary structured data (e.g. a JSON Schema
    ``examples`` entry) must never re-arm image normalization.

    Args:
        value: Arbitrary JSON-like value.

    Returns:
        bool: True for ``{"role": "...", "content": ...}`` dicts.
    """
    return isinstance(value, dict) and isinstance(value.get("role"), str) and "content" in value


def _isMessageList(value: object) -> bool:
    """Check whether a whole estimator input is a serialized message LIST.

    This is the trusted input boundary: the image-normalization decision is
    made ONCE, here, from what the input IS — a list whose every element is
    a serialized chat message (:func:`_isMessageDict`). Only
    message-estimation call sites produce this shape
    (``[message.toDict() for message in messages]``), so image payloads
    inside it are provider-interpreted image attachments. Anything else — a
    JSON Schema (even one with message-shaped ``examples`` instances), a
    bare message-shaped dict, a string — fails the predicate and its
    contents are counted verbatim.

    Args:
        value: The top-level estimator input.

    Returns:
        bool: True only for a list of message-shaped dicts.
    """
    return isinstance(value, list) and all(_isMessageDict(v) for v in value)


def _estimateTokenView(value: object, inMessageContent: bool = False) -> object:
    """Build a non-mutating estimation view of TRUSTED MESSAGE data with image payloads stripped.

    The walk itself makes NO context decisions: image payloads are replaced
    only where the caller already armed ``inMessageContent`` —
    :meth:`AbstractModel.getEstimateTokensCount` sets it ONCE at the trusted
    input boundary, for inputs recognized as serialized message lists
    (:func:`_isMessageList`). While armed, the flag propagates through every
    nested list and dict — the message envelopes and their ``content``
    values at any nesting depth. At an armed position, an image block — a
    dict carrying an ``image_url`` key whose value is a dict with an image
    data-URI ``url`` (the OpenAI multimodal shape ``{"type": "image_url",
    "image_url": {"url": "data:...;base64,..."}}``; the ``type``
    discriminator is optional, matching provider payloads) — is replaced by
    :data:`_IMAGE_DATA_PLACEHOLDER`.

    Everything else keeps being counted verbatim: bare JSON Schemas and
    arbitrary structured payloads (e.g. the schema itself, estimated
    alongside the messages by ``generateStructured``), image-block shapes in
    inputs that are not message lists (schemas, schema ``examples`` entries,
    bare dicts), non-image MIME data URIs, ordinary text content, tool
    results, and plain-string inputs. Those characters are really sent, so
    collapsing them would let requests bypass context sizing.

    Args:
        value: Arbitrary JSON-like data (dicts / lists / scalars).
        inMessageContent: Whether ``value`` sits inside a trusted message
            payload; armed only at the API boundary, never discovered during
            the walk (internal recursion state).

    Returns:
        object: A copy of the structure with image payloads replaced by
            :data:`_IMAGE_DATA_PLACEHOLDER` at armed positions; scalars are
            returned as-is and no input container is mutated.
    """
    if isinstance(value, dict):
        imageUrl = value.get("image_url")
        if inMessageContent and isinstance(imageUrl, dict) and _isImageDataUrl(imageUrl.get("url")):
            ret = dict(value)
            ret["image_url"] = {"url": _IMAGE_DATA_PLACEHOLDER}
            return ret
        return {k: _estimateTokenView(v, inMessageContent=inMessageContent) for k, v in value.items()}
    if isinstance(value, list):
        return [_estimateTokenView(v, inMessageContent=inMessageContent) for v in value]
    return value


_requestSessionIdVar: ContextVar[Optional[str]] = ContextVar("llmRequestSessionId", default=None)
"""Task-local session identifier for the in-flight LLM request.

Set by the public ``AbstractModel.generate*`` wrappers for the duration of
a single request so provider code that builds per-request payloads (e.g.
``_getExtraParams`` implementations adding ``extra_headers`` like
``x-opencode-session``) can read the conversation identity without
extending every internal method signature. Each asyncio task gets its own
copy, so concurrent requests never observe each other's session ID.
"""


def getCurrentRequestSessionId() -> Optional[str]:
    """Return the session ID of the in-flight LLM request, if any.

    Reads the task-local ``ContextVar`` populated by the public
    ``AbstractModel.generate*`` wrappers. Provider/model code that needs the
    conversation identity (e.g. to fill the ``x-opencode-session`` header
    used by OpenCode Go for prompt-cache affinity) should call this helper.

    Returns:
        The session ID string for the current request, or ``None`` when
        called outside a ``generate*`` call that received one.
    """
    return _requestSessionIdVar.get()


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
        customParams: Per-model custom parameters passed through to the
            underlying LLM API call. Common keys: ``temperature`` (float,
            default 0.5), ``top_p``, ``max_tokens``, ``frequency_penalty``,
            ``presence_penalty``, ``stop``, etc. Image-API keys (``size``,
            ``quality``, ``n``, ...) are sent as-is when using image
            generation. Provider-specific extensions (e.g. OpenRouter's
            ``extra_headers``) are merged in by provider overrides.
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
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Optional[Dict[str, Any]] = None,
        customParams: Optional[Dict[str, Any]] = None,
    ):
        """Initialize model with provider and configuration.

        Args:
            provider: The LLM provider instance that manages this model.
            modelId: Unique identifier for the model (e.g., "gpt-4", "yandexgpt").
            modelVersion: Version string for the model (e.g., "latest", "v1").
            contextSize: Maximum context size in tokens.
            statsStorage: StatsStorage instance for recording LLM usage statistics.
            extraConfig: Additional configuration options for the model.
            customParams: Per-model custom parameters passed through to the
                underlying LLM API call. Common keys: ``temperature`` (float,
                default 0.5), ``top_p``, ``max_tokens``, ``frequency_penalty``,
                ``presence_penalty``, ``stop``, etc. Image-API keys (``size``,
                ``quality``, ``n``, ...) are sent as-is when using image
                generation. Provider-specific extensions (e.g. OpenRouter's
                ``extra_headers``) are merged in by provider overrides. When
                ``None`` (default), an empty dict is stored.

        Raises:
            ValueError: If contextSize is negative.
        """
        self._config: Dict[str, Any] = extraConfig or {}

        self.provider = provider
        self.modelId = modelId
        self.modelVersion = modelVersion
        self._customParams: Dict[str, Any] = dict(customParams) if customParams is not None else {}
        self.contextSize = contextSize

        self.tiktokenEncoding = "o200k_base"
        self.tokensCountCoeff = 1.1

        # JSON-logging is off by default
        self.enableJSONLog = False
        self.jsonLogFile = ""
        self.jsonLogAddDateSuffix = True

        # Stats storage for recording LLM usage statistics
        self.statsStorage: StatsStorage = statsStorage
        self._dimensions: Optional[int] = None
        if extraConfig:
            configDimensions = extraConfig.get("embedding_dimensions")
            self._dimensions = int(configDimensions) if configDimensions else None

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
        sessionId: Optional[str] = None,
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
            sessionId: Optional conversation identifier exposed to provider code
                via :func:`getCurrentRequestSessionId` for the duration of this
                call (e.g. to fill the ``x-opencode-session`` request header).

        Returns:
            ModelRunResult containing the generated text, status, and metadata.
            Returns an error result if estimated tokens exceed twice the context size.

        Raises:
            Exception: If the model returns an error status (UNSPECIFIED,
                CONTENT_FILTER, UNKNOWN, or ERROR) and no fallback models are provided,
                or if all models (primary + fallbacks) fail.
        """
        token = _requestSessionIdVar.set(sessionId)
        try:
            if fallbackModels:
                # Use fallback mechanism when fallback models are provided
                return await self._runWithFallback(
                    [self, *fallbackModels],
                    lambda model: model.generateText(
                        messages=messages,
                        tools=tools,
                        fallbackModels=None,
                        consumerId=consumerId,
                        sessionId=sessionId,
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

            startTime = time.time()
            try:
                ret = await self._generateText(messages=messages, tools=tools)
                ret.elapsedTime = time.time() - startTime
            except Exception as e:
                await self._recordAttemptStats(
                    consumerId,
                    ModelRunResult(
                        rawResult=None, status=ModelResultStatus.ERROR, error=e, elapsedTime=time.time() - startTime
                    ),
                    "text",
                )
                raise

            await self._recordAttemptStats(consumerId, ret, "text")
            self.printJSONLog(messages, ret, consumerId=consumerId)
            return ret
        finally:
            _requestSessionIdVar.reset(token)

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
        sessionId: Optional[str] = None,
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
            sessionId: Optional conversation identifier exposed to provider code
                via :func:`getCurrentRequestSessionId` for the duration of this
                call (e.g. to fill the ``x-opencode-session`` request header).

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
        token = _requestSessionIdVar.set(sessionId)
        try:
            if fallbackModels:
                return await self._runWithFallback(
                    [self, *fallbackModels],
                    lambda model: model.generateImage(
                        messages=messages,
                        fallbackModels=None,
                        consumerId=consumerId,
                        sessionId=sessionId,
                    ),
                    ModelRunResult,
                )

            # Direct call with no fallbacks - invoke _generateImage and handle JSON logging
            startTime = time.time()
            try:
                ret = await self._generateImage(messages=messages)
                ret.elapsedTime = time.time() - startTime
            except Exception as e:
                await self._recordAttemptStats(
                    consumerId,
                    ModelRunResult(
                        rawResult=None, status=ModelResultStatus.ERROR, error=e, elapsedTime=time.time() - startTime
                    ),
                    "image",
                )
                raise

            await self._recordAttemptStats(consumerId, ret, "image")
            self.printJSONLog(messages, ret, consumerId=consumerId)
            return ret
        finally:
            _requestSessionIdVar.reset(token)

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
        raise NotImplementedError(f"Structured output isn't implemented by {self.modelId}")

    async def generateStructured(
        self,
        messages: Sequence[ModelMessage],
        schema: Dict[str, Any],
        *,
        schemaName: str = "response",
        strict: bool = True,
        fallbackModels: Optional[Sequence["AbstractModel"]] = None,
        consumerId: Optional[str] = None,
        sessionId: Optional[str] = None,
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
            sessionId: Optional conversation identifier exposed to provider code
                via :func:`getCurrentRequestSessionId` for the duration of this
                call (e.g. to fill the ``x-opencode-session`` request header).

        Returns:
            ModelStructuredResult with status, parsed data, token usage, etc.
            The result will have ``isFallback`` set to True if a fallback model
            was used.

        Raises:
            NotImplementedError: If this model does not support structured
                output (capability flag ``support_structured_output`` is False).
        """
        if not self._config.get("support_structured_output", False):
            raise NotImplementedError(f"Structured output isn't supported by {self.modelId}")

        token = _requestSessionIdVar.set(sessionId)
        try:
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
                        sessionId=sessionId,
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

            startTime = time.time()
            try:
                ret = await self._generateStructured(
                    messages=messages,
                    schema=schema,
                    schemaName=schemaName,
                    strict=strict,
                )
                ret.elapsedTime = time.time() - startTime
            except Exception as e:
                await self._recordAttemptStats(
                    consumerId,
                    ModelRunResult(
                        rawResult=None, status=ModelResultStatus.ERROR, error=e, elapsedTime=time.time() - startTime
                    ),
                    "structured",
                )
                raise

            await self._recordAttemptStats(consumerId, ret, "structured")
            self.printJSONLog(messages, ret, consumerId=consumerId)
            return ret
        finally:
            _requestSessionIdVar.reset(token)

    @property
    def supportsEmbedding(self) -> bool:
        """Whether this model supports embedding generation.

        Reads the ``support_embeddings`` flag from ``self._config``
        (which is populated from ``extraConfig`` by ``__init__``).
        Returns False by default. Embedding-only models are typically
        configured with ``support_text = false`` and
        ``support_embeddings = true`` so they are never picked for
        chat completion by mistake.

        Returns:
            True if embedding generation is enabled for this model.
        """
        return bool(self._config.get("support_embeddings", False))

    @abstractmethod
    async def _generateEmbeddings(self, text: str) -> list[float]:
        """Generate embedding vector for the given text.

        This is the internal method that must be implemented by concrete
        model classes that support embedding generation. It performs the
        actual call to the embedding backend (OpenAI embeddings API,
        fastembed, etc.) and returns the raw float vector.

        Args:
            text: Input text to embed.

        Returns:
            List of floats representing the embedding vector.

        Raises:
            NotImplementedError: If the model does not support embeddings.
            Exception: Provider-specific exceptions during generation.
        """
        raise NotImplementedError(f"Embeddings aren't supported by {self.modelId}")

    async def generateEmbeddings(
        self,
        text: str,
        *,
        attempts: int = 3,
        consumerId: Optional[str] = None,
        sessionId: Optional[str] = None,
    ) -> list[float]:
        """Generate an embedding vector for the given text, with retry on transient failures.

        This is the public method for embedding generation. It validates the
        input, then retries the underlying ``_generateEmbeddings`` call up to
        ``attempts`` times with exponential backoff on transient errors,
        records stats, and returns the embedding on success.

        Unlike :meth:`generateText` / :meth:`generateImage`, this method
        does **not** support a fallback model. Embeddings from different
        models live in incompatible vector spaces (different dimensions,
        different semantic spaces), so swapping to a different model
        mid-stream would silently corrupt downstream cosine similarity
        scores. If a chat needs a different embedding model, the caller
        must explicitly resolve it via the ``EMBEDDING_MODEL`` chat
        setting and re-embed.

        Args:
            text: Input text to embed.
            attempts: Max retry attempts on transient failures (default: 3).
            consumerId: Optional consumer identifier for stats recording
                (e.g. chat ID).
            sessionId: Optional conversation identifier exposed to provider code
                via :func:`getCurrentRequestSessionId` for the duration of this
                call (e.g. to fill the ``x-opencode-session`` request header).

        Returns:
            Embedding vector as list of floats.

        Raises:
            NotImplementedError: If the model does not support embeddings
                (capability flag ``support_embeddings`` is False).
            ValueError: If ``text`` is empty or not a string, or
                ``attempts`` is not a positive integer.
            RuntimeError: If all retry attempts fail.
        """
        if not self.supportsEmbedding:
            raise NotImplementedError(f"Embeddings aren't supported by {self.modelId}")

        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        if not isinstance(attempts, int) or attempts < 1:
            raise ValueError("attempts must be a positive integer")

        token = _requestSessionIdVar.set(sessionId)
        try:
            lastError: Optional[Exception] = None
            lastElapsed: float = 0.0
            for attempt in range(1, attempts + 1):
                startTime = time.time()
                try:
                    embedding = await self._generateEmbeddings(text)
                    elapsed = time.time() - startTime
                    await self._recordEmbeddingStats(
                        consumerId,
                        success=True,
                        error=None,
                        elapsed=elapsed,
                        attempts=attempt,
                    )
                    return embedding
                except (NotImplementedError, ValueError, TypeError):
                    # Deterministic failures: never retry.
                    raise
                except Exception as e:
                    lastError = e
                    lastElapsed = time.time() - startTime
                    logger.warning(
                        f"generateEmbeddings attempt {attempt}/{attempts} failed for " f"{self.modelId}: {e}"
                    )
                    if attempt < attempts:
                        # Exponential backoff: 0.5s, 1s, 2s, ...
                        backoff = 0.5 * (2 ** (attempt - 1))
                        await asyncio.sleep(backoff)

            # All attempts failed.
            await self._recordEmbeddingStats(
                consumerId,
                success=False,
                error=lastError,
                elapsed=lastElapsed,
                attempts=attempts,
            )
            raise RuntimeError(
                f"Embedding generation failed for {self.modelId} after {attempts} attempts: {lastError}"
            ) from lastError
        finally:
            _requestSessionIdVar.reset(token)

    async def getDimensions(self, forceDetect: bool = False) -> int:
        """Return the number of dimensions in the embedding vector.

        Args:
            forceDetect: Whether to force the dimensions to be detected.

        Returns:
            The number of dimensions in the embedding vector.
        """
        if not self.supportsEmbedding:
            raise NotImplementedError(f"Embeddings aren't supported by {self.modelId}")

        if forceDetect or self._dimensions is None:
            vec = await self._generateEmbeddings("test")
            self._dimensions = len(vec)

        return self._dimensions

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

        Raw message OBJECT lists are handled here directly: when *data* is a
        list/tuple whose every element is a :class:`ModelMessage` and at least
        one is image-bearing (:class:`ModelImageMessage` /
        :class:`ModelImagesMessage`), it is first serialized with the
        canonical ``[message.toDict() for message in data]`` shape. Without
        that, the object list would fall through the trusted boundary below
        and ``json.dumps(..., default=str)`` would embed every image's FULL
        base64 payload (via ``ModelMessage.__str__``) into the estimate,
        spuriously rejecting valid native-vision requests at the
        ``contextSize * 2`` generation gate. Text-only object lists, mixed
        lists, and every other input keep the EXACT pre-existing estimation
        path — the off-path estimate is an identity that must not drift.

        Before counting, inline base64 payloads are stripped — but only when
        the WHOLE input is recognized as a serialized chat-message list
        (:func:`_isMessageList`, the shape the serialization above and the
        message-estimation call sites produce). Normalization is decided once
        at this trusted API boundary, from what the input IS; message-shaped
        structures found during the recursive walk (e.g. JSON Schema
        ``examples`` entries) never re-arm it (:func:`_estimateTokenView`).
        Bare schemas, arbitrary structured payloads, and plain-string inputs
        are counted verbatim.

        Args:
            data: Data to estimate token count for. Can be a string, any
                object convertible to JSON, or a list/tuple of
                :class:`ModelMessage` objects (image-bearing object lists are
                serialized to the trusted dict shape first; see above). A
                list of role+content message dicts gets image-block
                normalization; everything else (e.g. a JSON Schema passed by
                ``generateStructured``) is counted as-is.

        Returns:
            Estimated number of tokens in the data.

        Example:
            >>> model.getEstimateTokensCount("Hello world")
            4
            >>> model.getEstimateTokensCount({"key": "value"})
            3
        """
        if (
            isinstance(data, (list, tuple))
            and all(isinstance(m, ModelMessage) for m in data)
            and any(isinstance(m, (ModelImageMessage, ModelImagesMessage)) for m in data)
        ):
            # Image-bearing message OBJECT list: serialize to the exact shape
            # the trusted boundary (:func:`_isMessageList`) recognizes, so
            # base64 payloads are placeholder-normalized below. Serialization
            # here never mutates the messages (``toDict`` derives fresh dicts).
            data = [m.toDict() for m in data]
        text = ""
        if isinstance(data, str):
            text = data
        else:
            # Trusted input boundary: image-block normalization is decided ONCE,
            # from what the top-level input IS — a serialized message list from a
            # message-estimation call site. Message-shaped structures discovered
            # later during the walk (schema examples, bare message-shaped dicts)
            # never re-arm it.
            text = json.dumps(
                _estimateTokenView(data, inMessageContent=_isMessageList(data)),
                ensure_ascii=False,
                default=str,
            )
        # Inline base64 image payloads (multimodal ``image_url`` data URIs) are
        # estimation noise: one normalized photo is ~0.5MB of base64 (~150k
        # estimated "tokens" by this heuristic) while the model bills it as
        # ~1-3k image tokens. Counting the raw payload would force context
        # condensing on nearly every image-bearing request. Payloads are
        # stripped ONLY when the whole input is a serialized message list
        # (:func:`_isMessageList` — armed once at this boundary; image blocks
        # inside genuine message payloads, discriminator optional). Schemas,
        # arbitrary structured payloads, message-shaped schema examples, data
        # URIs inside ordinary text or tool results, and plain strings are
        # real sent characters and keep being counted, so text-only requests
        # and schema data cannot bypass context sizing. The
        # max-images-per-request cap is the real guard for image cost.
        # According my experience, average, each token is 3-4 characters long, so use 3.5
        # For being conservative
        tokensCount = len(text) / 3.5
        # As we use estimated token count, it won't count tokens properly,
        # so we need to multiply by some coefficient to be sure
        return int(tokensCount * self.tokensCountCoeff)

    def getInfo(self) -> Dict[str, Any]:
        """Get model information and configuration.

        Returns a dictionary containing the model's metadata including provider,
        model ID, version, custom parameters, context size, and capabilities.

        Returns:
            Dictionary with model metadata containing:
                - provider: Provider class name
                - model_id: Model identifier
                - model_version: Model version
                - customParams: Per-model custom parameters passed through to
                    the underlying LLM API call (temperature, top_p, etc.)
                - context_size: Maximum context size
                - support_tools: Whether the model supports tools
                - support_text: Whether the model supports text generation
                - support_images: Whether the model supports image generation
                - support_image_input: Whether the model supports image input
                    (vision / "can see"); distinct from support_images, which
                    is image generation (output)
                - support_structured_output: Whether the model supports structured output
                - support_embeddings: Whether the model supports text embeddings
                - tier: Model tier (e.g., "bot-owner")
                - extra: Additional configuration options

        Example:
            >>> model.getInfo()
            {
                'provider': 'OpenAIProvider',
                'model_id': 'gpt-4',
                'model_version': 'latest',
                'customParams': {'temperature': 0.7},
                'context_size': 8192,
                'support_tools': True,
                'support_text': True,
                'support_images': False,
                'support_image_input': False,
                'support_structured_output': False,
                'support_embeddings': False,
                'tier': 'bot-owner',
                'extra': {}
            }
        """
        return {
            "provider": self.provider.__class__.__name__,
            "model_id": self.modelId,
            "model_version": self.modelVersion,
            "customParams": dict(self._customParams),
            "context_size": self.contextSize,
            "support_tools": self._config.get("support_tools", False),
            "support_text": self._config.get("support_text", True),
            "support_images": self._config.get("support_images", False),
            "support_image_input": self._config.get("support_image_input", False),
            "support_structured_output": self._config.get("support_structured_output", False),
            "support_embeddings": self._config.get("support_embeddings", False),
            "tier": self._config.get("tier", "bot-owner"),
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

    def printJSONLog(
        self,
        messages: Sequence[ModelMessage],
        result: ModelRunResult,
        *,
        consumerId: Optional[str] = None,
    ) -> None:
        """Write a request-response pair to the JSON log file.

        This method writes the conversation history (messages) and model response
        to a JSON log file. Each entry contains a UUID (for log-line grepping),
        timestamp, status, request, response, and metadata. Empty responses are
        not logged.

        Args:
            messages: List of message objects that were sent to the model.
            result: The model's response result containing status, text, and metadata.
            consumerId: Optional consumer identifier (e.g. chat ID).

        Raises:
            IOError: If unable to write to the log file.

        Note:
            The log file is opened in append mode, so multiple sessions can write
            to the same file. Each entry is written as a single line of JSON.
        """
        if not self.enableJSONLog:
            return
        if not result.resultText:
            # Do not log empty results
            return

        now = datetime.datetime.now(tz=datetime.timezone.utc)

        filename = self.jsonLogFile
        if self.jsonLogAddDateSuffix:
            todayStr = now.strftime("%Y-%m-%d")
            filename = filename + "." + todayStr

        data = {
            "uuid": str(uuid.uuid4()),  # Useful for grep purposes
            "date": now.isoformat(),
            "status": result.status,
            "request": [message.toDict("content") for message in messages],
            "response": result.resultText,
            "model": self.modelId,
            "provider": type(self.provider).__name__,
            "raw": str(result.result),
            "consumer": consumerId,
            "elapsed_time": result.elapsedTime,
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
            stats: dict[str, float | int] = {
                f"generation_{generationType}": 1,
                "request_count": 1,
                "input_tokens": result.inputTokens or 0,
                "output_tokens": result.outputTokens or 0,
                "total_tokens": result.totalTokens or 0,
                "is_error": 1 if result.status in ERROR_STATUSES else 0,
                "tool_calls_count": len(result.toolCalls),
                f"status_{result.status.name}": 1,
                "elapsed_time": result.elapsedTime or 0,
            }
            # Optional provider-reported metrics: recorded only when the
            # provider actually reported them, so aggregates stay truthful
            # (absent metric == not reported, not zero).
            if result.cachedInputTokens is not None:
                stats["cached_input_tokens"] = result.cachedInputTokens
            if result.reasoningTokens is not None:
                stats["reasoning_tokens"] = result.reasoningTokens
            if result.cost is not None:
                stats["cost"] = result.cost
            await self.statsStorage.record(
                stats=stats,
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

    async def _recordEmbeddingStats(
        self,
        consumerId: Optional[str],
        *,
        success: bool,
        error: Optional[Exception],
        elapsed: float,
        attempts: int,
    ) -> None:
        """Record stats for a single embedding attempt. Best-effort — never raises.

        Mirrors the shape of :meth:`_recordAttemptStats` but specialised for
        embedding calls (no token counts, no structured result envelope).

        Args:
            consumerId: Consumer identifier (e.g. chat ID).
            success: True if the embedding was produced successfully.
            error: The captured exception on failure, or None on success.
            elapsed: Wall-clock seconds spent on the successful (or final)
                attempt, used for the ``elapsed_time`` metric.
            attempts: Number of attempts it took (1 on first-try success).
        """
        try:
            info = self.getInfo()
            labels = {
                "modelName": info.get("model_id", "unknown"),
                "modelId": info.get("model_id", "unknown"),
                "provider": info.get("provider", "unknown"),
                "generationType": "embedding",
                "status": "FINAL" if success else "ERROR",
            }
            if error is not None:
                labels["error"] = type(error).__name__
            await self.statsStorage.record(
                stats={
                    "generation_embeddings": 1,
                    "request_count": 1,
                    "embedding_attempts": attempts,
                    "is_error": 0 if success else 1,
                    "elapsed_time": elapsed or 0,
                },
                consumerId=consumerId,
                labels=labels,
            )
        except Exception as e:
            logger.error("Failed to record embedding attempt stats")
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
            def addModel(self, name, modelId, modelVersion, contextSize,
                        extraConfig={}, customParams=None):
                model = CustomModel(self, modelId, modelVersion, contextSize,
                                   extraConfig, customParams=customParams)
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
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Dict[str, Any] = {},
        customParams: Optional[Dict[str, Any]] = None,
    ) -> AbstractModel:
        """Add a model to this provider.

        This method must be implemented by concrete provider classes to create
        and register a model instance with the provider.

        Args:
            name: Human-readable name for the model (used as key in models dict).
            modelId: Provider-specific model identifier (e.g., "gpt-4", "yandexgpt").
            modelVersion: Version string for the model (e.g., "latest", "v1").
            contextSize: Maximum context size in tokens.
            statsStorage: StatsStorage instance for recording LLM usage statistics.
            extraConfig: Additional configuration options for the model.
            customParams: Per-model custom parameters passed through to the
                underlying LLM API call (temperature, top_p, max_tokens,
                etc.). See :attr:`AbstractModel._customParams` for the full
                key inventory.

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

    async def listRemoteModels(self) -> Dict[str, Dict[str, Any]]:
        """List models available from the remote API.

        Returns a dict mapping model IDs to their settings dicts.
        The settings dict contains whatever data the remote API provides
        (e.g., id, owned_by, context_length, pricing).

        The default implementation returns an empty dict — providers
        that support model discovery should override this.

        Returns:
            Dict[str, Dict[str, Any]]: Model ID → settings dict.
            Empty dict if the provider does not support remote listing.
        """
        return {}

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

    async def aclose(self) -> None:
        """Close provider resources (HTTP clients, connections, etc.).

        Subclasses that create resources requiring async cleanup (e.g. proxy
        HTTP clients) should override this method.  The default implementation
        is a no-op so that callers can safely iterate over all providers and
        call ``aclose()`` without ``hasattr`` checks.
        """
        pass

    def __str__(self) -> str:
        """Return string representation of the provider.

        Returns:
            String in format "ProviderName (N models)" where N is the number of
            registered models.
        """
        return f"{self.__class__.__name__} ({len(self.models)} models)"
