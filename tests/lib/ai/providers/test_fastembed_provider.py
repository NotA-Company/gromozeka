"""Tests for FastembedProvider cache_dir configuration.

Covers the provider-level ``cache_dir`` knob introduced to control where
fastembed stores downloaded ONNX models:

- Provider reads ``cache_dir`` from its config and exposes ``cacheDir``.
- The provider-level value is applied to every hosted model as a default.
- A model-level ``cache_dir`` in ``extraConfig`` overrides the provider
  default.
- When neither provider nor model specify ``cache_dir``, fastembed's own
  default applies (no key is injected into the fastembed kwargs).

These tests construct the real :class:`FastembedProvider` /
:class:`FastembedModel` (fastembed is installed in the dev venv) but never
trigger a model download — they only inspect ``_fastembedKwargs`` which is
built at construction time.
"""

from typing import Any, Dict

from lib.ai.providers.fastembed_provider import FastembedModel, FastembedProvider
from lib.stats import NullStatsStorage


def _makeModel(
    provider: FastembedProvider,
    *,
    name: str = "m",
    modelId: str = "sentence-transformers/all-MiniLM-L6-v2",
    extraConfig: Dict[str, Any] | None = None,
) -> FastembedModel:
    """Build a FastembedModel with sane defaults for cache_dir tests.

    Args:
        provider: Owning provider instance.
        name: Model registration name.
        modelId: Fastembed model id.
        extraConfig: Extra config dict.

    Returns:
        The registered FastembedModel instance.
    """
    cfg: Dict[str, Any] = {
        "support_embeddings": True,
        "embedding_dimensions": 384,
    }
    if extraConfig is not None:
        cfg.update(extraConfig)
    model = provider.addModel(
        name=name,
        modelId=modelId,
        modelVersion="latest",
        temperature=0.0,
        contextSize=0,
        statsStorage=NullStatsStorage(),
        extraConfig=cfg,
    )
    assert isinstance(model, FastembedModel)
    return model


def test_providerReadsCacheDirFromConfig() -> None:
    """Provider exposes ``cacheDir`` from its config dict."""
    provider = FastembedProvider({"type": "fastembed", "cache_dir": "/tmp/fe-cache"})
    assert provider.cacheDir == "/tmp/fe-cache"


def test_providerCacheDirDefaultsToNone() -> None:
    """When ``cache_dir`` is absent from config, ``cacheDir`` is None."""
    provider = FastembedProvider({"type": "fastembed"})
    assert provider.cacheDir is None


def test_providerCacheDirAppliedToModel() -> None:
    """Provider-level cache_dir is injected into the model's fastembed kwargs."""
    provider = FastembedProvider({"type": "fastembed", "cache_dir": "/tmp/fe-cache"})
    model = _makeModel(provider)
    assert model._fastembedKwargs["cache_dir"] == "/tmp/fe-cache"


def test_modelCacheDirOverridesProviderDefault() -> None:
    """A model-level cache_dir wins over the provider default."""
    provider = FastembedProvider({"type": "fastembed", "cache_dir": "/tmp/default"})
    model = _makeModel(provider, extraConfig={"cache_dir": "/tmp/per-model"})
    assert model._fastembedKwargs["cache_dir"] == "/tmp/per-model"


def test_noCacheDirWhenNeitherProviderNorModelSpecifyOne() -> None:
    """With no provider and no model cache_dir, fastembed kwargs lack the key."""
    provider = FastembedProvider({"type": "fastembed"})
    model = _makeModel(provider)
    assert "cache_dir" not in model._fastembedKwargs


def test_consumedExtraKeysUnchanged() -> None:
    """cache_dir is NOT a consumed key — it must flow through to fastembed."""
    assert "cache_dir" not in FastembedModel._CONSUMED_EXTRA_KEYS
