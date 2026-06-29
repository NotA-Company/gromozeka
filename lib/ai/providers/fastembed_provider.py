"""Fastembed provider for fastembed-backed embedding models.

This module provides a provider implementation for running embedding
generation locally using the ``fastembed`` library (ONNX-based, no PyTorch
dependency). A single :class:`FastembedProvider` instance hosts any
number of embedding models (e.g. ``all-MiniLM-L6-v2``, ``all-mpnet-base-v2``)
via the standard :meth:`AbstractLLMProvider.addModel` pattern.

``fastembed`` is an **optional** dependency. The provider is only usable
when the library is importable; otherwise initialisation succeeds but every
embed call surfaces a clear error to the caller. Server-wide gating
(``search-history.enabled`` / ``EMBEDDINGS_ENABLED`` chat setting) is
expected to keep the call site dormant when the dependency is missing.

Classes:
    FastembedModel: Single embedding model wrapping one fastembed
        ``TextEmbedding`` instance, exposed via the standard
        ``AbstractModel`` interface (``generateEmbeddings``).
    FastembedProvider: Multi-model FastEmbed provider. Mirrors
        ``BasicOpenAIProvider``'s "one provider, many models" pattern.

Example:
    >>> provider = FastembedProvider({})
    >>> provider.addModel(
    ...     name="local-minilm",
    ...     modelId="sentence-transformers/all-MiniLM-L6-v2",
    ...     modelVersion="latest",
    ...     temperature=0.0,
    ...     contextSize=0,
    ...     statsStorage=stats,
    ...     extraConfig={"support_text": False, "support_embeddings": True, "embedding_dimensions": 384},
    ... )
    >>> model = provider.getModel("local-minilm")
    >>> vector = await model.generateEmbeddings("hello world")  # doctest: +SKIP
"""

import asyncio
import logging
from collections.abc import Sequence
from threading import Lock
from typing import Any, Dict, List, Optional

import numpy as np

from lib.stats import StatsStorage

from ..abstract import AbstractLLMProvider, AbstractModel
from ..models import LLMAbstractTool, ModelMessage, ModelRunResult

try:
    from fastembed import TextEmbedding

    _FASTEMBED_AVAILABLE = True
except ImportError:
    _FASTEMBED_AVAILABLE = False


logger = logging.getLogger(__name__)


def _embedSync(embedding: TextEmbedding, text: str) -> list:
    """Run ``embedding.embed`` synchronously for use with :func:`asyncio.to_thread`.

    Args:
        embedding: A fastembed ``TextEmbedding`` instance whose
            ``embed`` method returns a generator of numpy arrays.
        text: Single text to embed.

    Returns:
        Materialised list of numpy arrays, one per input text.
    """
    return list(embedding.embed([text]))


class FastembedProvider(AbstractLLMProvider):
    """Provider for FastEmbed embedding models using fastembed.

    A single instance hosts any number of embedding models via the same
    :meth:`addModel` pattern used by :class:`BasicOpenAIProvider`. The
    ``fastembed`` library is loaded once per process (the underlying ONNX
    runtime is process-global and ~50MB).

    Model construction and dimension probing are always lazy — the
    underlying ``TextEmbedding`` is built on the first call to
    :meth:`embedOne` (or the first lazy probe in
    :meth:`FastembedModel._generateEmbeddings`), offloaded to a thread
    pool via :func:`asyncio.to_thread`. Providing
    ``embedding_dimensions`` explicitly in ``extraConfig`` avoids the
    one-shot probe embed and is slightly more efficient, but even when
    omitted the event loop is never blocked.

    The provider has no remote endpoint — there is no client to initialise.
    Model-specific configuration is consumed from each model's
    ``extraConfig`` (stored as ``self._config`` on the model) so a single
    provider can host models with different dimensions / cache directories
    / thread counts.

    Attributes:
        config: Provider-level configuration (usually empty — the provider
            is purely structural; all knobs live on the model).
        models: Dict of registered :class:`FastembedModel` instances,
            keyed by model name.
        _modelLocks: Per-model-id ``threading.Lock`` used to serialise
            fastembed model construction under the asyncio event loop.

    Raises:
        ImportError: If ``fastembed`` is not installed. Caught and logged
            by :class:`LLMManager`; the provider is simply not registered.

    Example:
        >>> provider = FastembedProvider({})
        >>> provider.addModel(  # doctest: +SKIP
        ...     name="local-minilm",
        ...     modelId="sentence-transformers/all-MiniLM-L6-v2",
        ...     modelVersion="latest",
        ...     temperature=0.0,
        ...     contextSize=0,
        ...     statsStorage=stats,
        ...     extraConfig={"support_embeddings": True, "embedding_dimensions": 384},
        ... )
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the FastEmbed provider.

        Validates that ``fastembed`` is importable and that the provider
        config is a dict. The provider has no remote client to construct —
        ``TextEmbedding`` instances are created lazily inside
        :meth:`embedOne` on the first call for a given model id.

        Args:
            config: Provider-level configuration. The provider is purely
                structural, so this is typically empty (``{}``); all
                model-specific knobs (``embedding_dimensions``,
                ``cache_dir``, etc.) flow through each model's
                ``extraConfig``.

        Raises:
            ImportError: If the ``fastembed`` package is not installed in
                the current environment.
            TypeError: If ``config`` is not a dict.
        """
        if not _FASTEMBED_AVAILABLE:
            raise ImportError(
                "fastembed package is required for the 'fastembed' provider, dood! "
                "Install it with `pip install fastembed` or remove the provider from config."
            )
        if not isinstance(config, dict):
            raise TypeError("config must be a dict, dood!")

        super().__init__(config)
        # Per-model-id lazy construction cache. Keyed by modelId.
        self._embeddingModels: Dict[str, Any] = {}
        # Serialise lazy construction so two concurrent first-use calls
        # for the same model id don't both download/load the model.
        self._modelLocks: Dict[str, Lock] = {}
        self._locksGuard: Lock = Lock()
        logger.info(f"{self.__class__.__name__} initialized, dood!")

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
        """Register a new FastEmbed embedding model with this provider.

        Mirrors :meth:`BasicOpenAIProvider.addModel`: idempotent on name
        (returns the existing model if one is already registered), and
        stores the new instance in ``self.models[name]``.

        Args:
            name: Human-readable name for the model (key in ``self.models``).
            modelId: Fastembed model identifier (e.g.
                ``"sentence-transformers/all-MiniLM-L6-v2"``).
            modelVersion: Version string (fastembed models are versioned
                by their identifier; pass ``"latest"``).
            temperature: Sampling temperature. Embeddings are deterministic
                so callers pass ``0.0``; stored for protocol consistency.
            contextSize: Maximum context in tokens. Not applicable to
                embedding models; callers pass ``0``.
            statsStorage: StatsStorage instance for recording usage.
            extraConfig: Model-specific configuration. Recognised keys:

                - ``support_embeddings`` (bool): should be ``True`` for
                  embedding models.
                - ``support_text`` (bool): set to ``False`` to prevent
                  accidental use for chat completion.
                - ``embedding_dimensions`` (int): explicit output
                  dimensionality. If absent, detected from fastembed.
                - Any other keys (e.g. ``cache_dir``, ``threads``,
                  ``max_length``) are passed through to
                  ``TextEmbedding(...)`` as keyword arguments.

        Returns:
            The registered :class:`FastembedModel` instance.

        Raises:
            ValueError: If ``extraConfig`` does not declare
                ``support_embeddings=true``.
        """
        if name in self.models:
            logger.warning(f"Model {name} already exists in {self.__class__.__name__}, dood!")
            return self.models[name]

        if extraConfig is None:
            extraConfig = {}
        if not extraConfig.get("support_embeddings", False):
            raise ValueError(f"Model {name} ({modelId}) must declare support_embeddings=true, dood!")

        model = FastembedModel(
            provider=self,
            modelId=modelId,
            modelVersion=modelVersion,
            temperature=temperature,
            contextSize=contextSize,
            statsStorage=statsStorage,
            extraConfig=extraConfig,
        )
        self.models[name] = model
        logger.info(f"Added {self.__class__.__name__} model {name} ({modelId}), " f"dims={model._dimensions}, dood!")
        return model

    def _getOrCreateEmbedding(self, modelId: str, fastembedKwargs: Dict[str, Any]) -> TextEmbedding:
        """Return a cached :class:`TextEmbedding` for ``modelId``, constructing it lazily.

        Construction is serialised per model id by a ``threading.Lock`` so
        two concurrent first-use calls don't both kick off a model
        download/load. The actual constructor call may still take seconds
        (model download on first use); callers run it in a thread via
        :func:`asyncio.to_thread` to keep the event loop unblocked.

        Args:
            modelId: Fastembed model identifier.
            fastembedKwargs: Extra kwargs forwarded to ``TextEmbedding(...)``.

        Returns:
            A ready-to-use :class:`TextEmbedding` instance.
        """
        with self._locksGuard:
            lock = self._modelLocks.setdefault(modelId, Lock())
        with lock:
            cached = self._embeddingModels.get(modelId)
            if cached is not None:
                return cached
            logger.info(f"Loading fastembed model {modelId}, dood!")
            embedding = TextEmbedding(model_name=modelId, **fastembedKwargs)
            self._embeddingModels[modelId] = embedding
            return embedding

    async def embedOne(self, modelId: str, text: str, **kwargs: Any) -> "np.ndarray":
        """Embed a single text using the named FastEmbed model.

        Runs the (sync) fastembed call in a thread pool so the event loop
        stays responsive. Returns the raw numpy array — the caller
        (``FastembedModel._generateEmbeddings``) is responsible for
        the ``tolist()`` conversion to plain ``list[float]``.

        Args:
            modelId: Fastembed model identifier.
            text: Text to embed. fastembed accepts a list internally; we
                wrap the single string in a one-element list.
            **kwargs: Extra kwargs forwarded to ``TextEmbedding(...)`` on
                first use (e.g. ``cache_dir``, ``threads``).

        Returns:
            numpy.ndarray of shape ``(embedding_dimensions,)`` and dtype
            ``float32``.

        Raises:
            Exception: Any exception raised by fastembed (model load
                failure, OOM, etc.) is re-raised unchanged.
        """
        embedding = await asyncio.to_thread(self._getOrCreateEmbedding, modelId, kwargs)
        # ``embed`` returns a generator of numpy arrays. Materialise it
        # inside the thread to keep the asyncio side purely async.
        vectors: List[Any] = await asyncio.to_thread(_embedSync, embedding, text)
        if not vectors:
            raise ValueError(f"fastembed returned no vectors for model {modelId}")
        return vectors[0]


class FastembedModel(AbstractModel):
    """FastEmbed embedding model wrapping a single fastembed ``TextEmbedding`` instance.

    The model advertises itself as embedding-only (``support_text`` should
    be ``False`` in config) so it is never picked for chat completion by
    accident. All fastembed-specific configuration flows through
    ``extraConfig`` (stored as ``self._config`` by
    :meth:`AbstractModel.__init__`); everything not consumed by the base
    class (``support_text``, ``support_embeddings``, ``embedding_dimensions``,
    plus any unrelated provider keys) is passed through to fastembed.

    When ``embedding_dimensions`` is provided in ``extraConfig``, the
    output dimensionality is known at construction time. When it is
    omitted, a lazy dimension probe runs on the first call to
    :meth:`_generateEmbeddings`, offloaded to a thread pool via
    :func:`asyncio.to_thread` so model download never blocks the event
    loop.

    Attributes:
        _provider: The :class:`FastembedProvider` that owns this model.
        _dimensions: Output dimensionality (from config or lazily probed).
        _dimensionsProbed: Whether the lazy probe has already run.
        _fastembedKwargs: Extra kwargs forwarded to ``TextEmbedding(...)``
            on first use.

    Example:
        >>> provider = FastembedProvider({})
        >>> model = FastembedModel(  # doctest: +SKIP
        ...     provider=provider,
        ...     modelId="sentence-transformers/all-MiniLM-L6-v2",
        ...     modelVersion="latest",
        ...     temperature=0.0,
        ...     contextSize=0,
        ...     statsStorage=stats,
        ...     extraConfig={"support_embeddings": True, "embedding_dimensions": 384},
        ... )
        >>> model.embeddingDimensions
        384
    """

    #: Keys consumed by AbstractModel / FastembedModel and stripped
    #: from the kwargs passed through to ``TextEmbedding(...)``. Anything
    #: else in ``extraConfig`` is forwarded verbatim.
    _CONSUMED_EXTRA_KEYS = frozenset(
        {
            # Capability flags consumed by AbstractModel / getInfo
            "support_text",
            "support_tools",
            "support_images",
            "support_structured_output",
            "support_embeddings",
            # FastembedModel-consumed
            "embedding_dimensions",
            "tier",
            # Standard model-config keys passed through by LLMManager._initModels
            # (these are NOT fastembed constructor args and must be stripped)
            "provider",
            "model_id",
            "model_version",
            "temperature",
            "context",
            "enabled",
        }
    )

    def __init__(
        self,
        provider: "FastembedProvider",
        modelId: str,
        *,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize the FastEmbed embedding model.

        Args:
            provider: The :class:`FastembedProvider` that owns this model.
            modelId: Fastembed model identifier (e.g.
                ``"sentence-transformers/all-MiniLM-L6-v2"``).
            modelVersion: Version string (fastembed models are versioned
                by their identifier; pass ``"latest"``).
            temperature: Sampling temperature. Embeddings are deterministic
                so callers pass ``0.0``.
            contextSize: Maximum context in tokens. Not applicable to
                embedding models; callers pass ``0``.
            statsStorage: StatsStorage instance for recording usage.
            extraConfig: Model-specific configuration. Recognised keys:

                - ``support_embeddings`` (bool): must be ``True``.
                - ``support_text`` (bool): should be ``False`` to keep
                  the model out of the chat-completion model pool.
                - ``embedding_dimensions`` (int): explicit output
                  dimensionality. If absent, probed lazily from
                  fastembed on first embed call.
                - Any other keys are forwarded to ``TextEmbedding(...)``
                  (e.g. ``cache_dir``, ``threads``, ``max_length``).
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
        self._provider = provider

        # Anything in extraConfig that AbstractModel / this class doesn't
        # consume is forwarded to fastembed on first use.
        self._fastembedKwargs: Dict[str, Any] = {
            key: value for key, value in (extraConfig or {}).items() if key not in self._CONSUMED_EXTRA_KEYS
        }

    async def _generateEmbeddings(self, text: str) -> list[float]:
        """Generate an embedding for ``text`` using the FastEmbed model.

        Runs the (sync) fastembed call in a thread pool via the provider
        so the event loop stays unblocked. The numpy array returned by
        fastembed is converted to a plain ``list[float]`` for cross-
        platform / cross-provider uniformity — every embedding backend in
        the codebase returns the same shape.

        When ``embedding_dimensions`` was omitted from config the first
        call triggers a lazy dimension probe (also in a thread pool) so
        model download / ONNX initialisation never blocks the event loop.

        Args:
            text: Input text to embed.

        Returns:
            Float vector of length :attr:`embeddingDimensions`.

        Raises:
            Exception: Any exception raised by fastembed (load failure,
                OOM, etc.) is re-raised unchanged.
        """
        vector = await self._provider.embedOne(
            modelId=self.modelId,
            text=text,
            **self._fastembedKwargs,
        )
        # ``vector`` is a numpy.ndarray of dtype float32. ``tolist()`` is
        # the canonical conversion to a Python list of floats; we cast to
        # ``float`` defensively in case fastembed ever switches dtype.
        return [float(x) for x in vector.tolist()]

    async def _generateText(
        self,
        messages: Sequence[ModelMessage],
        tools: Optional[Sequence[LLMAbstractTool]] = None,
    ) -> ModelRunResult:
        """Text generation is not supported by FastEmbed embedding models.

        FastEmbed embedding models are embedding-only: ``support_text = false``
        in the model config keeps them out of the chat-completion pool, but
        the call must still be answered because ``AbstractModel`` declares
        the method abstract. A descriptive :class:`NotImplementedError` is
        the expected outcome for any caller that bypasses the support flag.

        Args:
            messages: Ignored.
            tools: Ignored.

        Returns:
            Never returns; always raises :class:`NotImplementedError`.

        Raises:
            NotImplementedError: Always — this model only generates embeddings.
        """
        raise NotImplementedError(f"Text generation isn't supported by embedding model {self.modelId}, dood!")

    async def _generateImage(
        self,
        messages: Sequence[ModelMessage],
    ) -> ModelRunResult:
        """Image generation is not supported by FastEmbed embedding models.

        FastEmbed embedding models are embedding-only. Raises a descriptive
        :class:`NotImplementedError` for any caller that ignores the
        ``support_images = false`` flag in the model config.

        Args:
            messages: Ignored.

        Returns:
            Never returns; always raises :class:`NotImplementedError`.

        Raises:
            NotImplementedError: Always — this model only generates embeddings.
        """
        raise NotImplementedError(f"Image generation isn't supported by embedding model {self.modelId}, dood!")
