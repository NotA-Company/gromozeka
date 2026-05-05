"""Scenario runner used by the divination golden-data collector, dood!

This module wires together :mod:`lib.divination` and :mod:`lib.ai` so that a
single object exposed through :class:`DivinationScenarioRunner` covers the
full prompt-building + LLM round-trip path that the bot's divination handler
will follow at runtime.

The runner is intentionally configured to match
:mod:`lib.aurumentation`'s rigid scenario shape
(``module / class / method / init_kwargs / kwargs``) so the standard
:func:`lib.aurumentation.collector.collectGoldenData` can drive it without
custom collector code, dood!

Layout used by ``scenarios.json`` per scenario:

* ``init_kwargs``: provider / model configuration, including the API key as
  ``${OPENROUTER_API_KEY}`` so :func:`lib.aurumentation.collector.substituteEnvVars`
  can fill it in at collection time.
* ``kwargs``: divination scenario inputs — ``systemId``, ``layoutId``,
  ``rngSeed``, ``userName``, ``question``, ``lang``.

The class deliberately keeps no state across :meth:`runReading` calls so a
single instance can serve every scenario, mirroring the pattern used by
:class:`lib.openweathermap.client.OpenWeatherMapClient` in
``tests/openweathermap/golden/``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from lib.ai import ModelMessage
from lib.ai.abstract import AbstractLLMProvider, AbstractModel
from lib.ai.providers.custom_openai_provider import CustomOpenAIProvider
from lib.ai.providers.openrouter_provider import OpenrouterProvider
from lib.ai.providers.yc_openai_provider import YcOpenaiProvider
from lib.divination import (
    BaseDivinationSystem,
    Reading,
    RunesSystem,
    TarotSystem,
    drawSymbols,
)
from lib.divination.layouts import Layout

# Path to the shipped default templates. Resolved relative to the repo root,
# which is reliable because the collector inserts the repo root onto
# ``sys.path`` before importing this module.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
BOT_DEFAULTS_PATH: Path = REPO_ROOT / "configs" / "00-defaults" / "bot-defaults.toml"

# Mapping of provider type strings to their concrete classes. We do not pull
# YC SDK in because (a) it's not httpx-based so aurumentation cannot record
# it, and (b) it requires an authenticated YC profile rather than a plain
# API key.
PROVIDER_TYPES: Dict[str, type[AbstractLLMProvider]] = {
    "openrouter": OpenrouterProvider,
    "yc-openai": YcOpenaiProvider,
    "custom-openai": CustomOpenAIProvider,
}

# Mapping of divination system IDs to their concrete classes.
SYSTEM_CLASSES: Dict[str, type[BaseDivinationSystem]] = {
    "tarot": TarotSystem,
    "runes": RunesSystem,
}


def loadBotDefaults() -> Dict[str, Any]:
    """Load the ``[bot.defaults]`` table from ``configs/00-defaults/bot-defaults.toml``.

    The shipped defaults are the source of truth for the prompt templates the
    handler will read from chat settings when no per-chat override is set.

    Returns:
        The parsed ``bot.defaults`` table as a plain dictionary.

    Raises:
        FileNotFoundError: When the defaults file is missing.
        KeyError: When the file does not contain a ``[bot.defaults]`` section.
    """
    if not BOT_DEFAULTS_PATH.exists():
        raise FileNotFoundError(f"bot-defaults.toml not found at {BOT_DEFAULTS_PATH}, dood!")
    with BOT_DEFAULTS_PATH.open("rb") as fh:
        data: Dict[str, Any] = tomllib.load(fh)
    bot: Dict[str, Any] = data.get("bot", {})
    defaults: Dict[str, Any] = bot.get("defaults", {})
    if not defaults:
        raise KeyError("bot-defaults.toml is missing the [bot.defaults] table, dood!")
    return defaults


def getDefaultTemplates() -> Dict[str, str]:
    """Pull the four divination templates from ``[bot.defaults]``.

    Returns:
        Mapping with keys ``taroSystemPrompt``, ``runesSystemPrompt``,
        ``userPromptTemplate`` and ``imagePromptTemplate``.

    Raises:
        KeyError: When any of the required template keys is missing from the
            defaults file.
    """
    defaults: Dict[str, Any] = loadBotDefaults()
    requiredKeys: Tuple[str, ...] = (
        "taro-system-prompt",
        "runes-system-prompt",
        "divination-user-prompt-template",
        "divination-image-prompt-template",
    )
    for key in requiredKeys:
        if key not in defaults:
            raise KeyError(f"bot-defaults.toml [bot.defaults] is missing '{key}', dood!")
    return {
        "taroSystemPrompt": str(defaults["taro-system-prompt"]),
        "runesSystemPrompt": str(defaults["runes-system-prompt"]),
        "userPromptTemplate": str(defaults["divination-user-prompt-template"]),
        "imagePromptTemplate": str(defaults["divination-image-prompt-template"]),
    }


def resolveSystem(systemId: str) -> type[BaseDivinationSystem]:
    """Return the system class for ``systemId``.

    Args:
        systemId: Either ``"tarot"`` or ``"runes"``.

    Returns:
        The concrete :class:`BaseDivinationSystem` subclass.

    Raises:
        ValueError: When ``systemId`` is not a recognised system.
    """
    if systemId not in SYSTEM_CLASSES:
        raise ValueError(f"Unknown systemId '{systemId}', dood! expected one of {sorted(SYSTEM_CLASSES)}.")
    return SYSTEM_CLASSES[systemId]


def resolveLayoutForSystem(systemCls: type[BaseDivinationSystem], layoutId: str) -> Layout:
    """Resolve ``layoutId`` to a :class:`Layout` belonging to ``systemCls``.

    Matches by raw ``Layout.id`` first (the canonical machine name), then
    falls back to the system's case- and separator-insensitive resolver so
    user-friendly aliases also work.

    Args:
        systemCls: The divination system the layout must belong to.
        layoutId: Identifier or alias of the layout.

    Returns:
        The matched :class:`Layout`.

    Raises:
        ValueError: When the layout cannot be found in the system's registry.
    """
    for layout in systemCls.availableLayouts():
        if layout.id == layoutId:
            return layout
    fallback: Optional[Layout] = systemCls.resolveLayout(layoutId)
    if fallback is not None:
        return fallback
    available: str = ", ".join(layout.id for layout in systemCls.availableLayouts())
    raise ValueError(f"Unknown layoutId '{layoutId}' for system '{systemCls.systemId}', dood! Available: {available}.")


def buildReading(
    systemCls: type[BaseDivinationSystem],
    layout: Layout,
    *,
    rngSeed: int,
    question: str,
) -> Reading:
    """Draw symbols deterministically and assemble a :class:`Reading`.

    Args:
        systemCls: The divination system (provides deck + ``supportsReversed``).
        layout: The layout being drawn for.
        rngSeed: Pinned RNG seed for reproducibility.
        question: User-supplied question (recorded into the reading).

    Returns:
        A fully populated :class:`Reading` object.
    """
    import random

    rng: random.Random = random.Random(rngSeed)
    draws = drawSymbols(
        systemCls.deck,
        layout,
        supportsReversed=systemCls.supportsReversed,
        rng=rng,
    )
    return Reading(
        systemId=systemCls.systemId,
        deckId=systemCls.deckId,
        layout=layout,
        draws=draws,
        question=question,
        seed=rngSeed,
    )


def messagesToDicts(messages: List[ModelMessage]) -> List[Dict[str, Any]]:
    """Serialise :class:`ModelMessage` objects to plain dicts.

    The bot stores prompts as ``role + content`` pairs; this is enough for
    byte-equality regression checks during replay.

    Args:
        messages: List of :class:`ModelMessage` produced by
            :meth:`BaseDivinationSystem.buildInterpretationMessages`.

    Returns:
        A list of ``{"role": str, "content": str}`` dictionaries.
    """
    return [{"role": message.role, "content": message.content} for message in messages]


class DivinationScenarioRunner:
    """End-to-end scenario runner for the divination golden-data collector.

    A single instance is constructed per scenario by
    :func:`lib.aurumentation.collector.collectGoldenData`, which forwards the
    scenario's ``init_kwargs`` straight into ``__init__`` and then awaits
    :meth:`runReading` with the scenario's ``kwargs``. The runner spins up a
    one-model :class:`AbstractLLMProvider` from the provided config so the
    LLM round-trip flows through the same code path the bot uses at runtime,
    dood!
    """

    def __init__(
        self,
        *,
        providerType: str,
        providerConfig: Mapping[str, Any],
        modelName: str,
        modelId: str,
        modelVersion: str = "latest",
        temperature: float = 0.3,
        contextSize: int = 64000,
        extraConfig: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Configure the underlying provider + model.

        Args:
            providerType: One of ``"openrouter"``, ``"yc-openai"``,
                ``"custom-openai"``.
            providerConfig: Dict forwarded verbatim to the provider's
                ``__init__`` (typically ``{"api_key": "${OPENROUTER_API_KEY}"}``).
            modelName: Logical name used to fetch the model from the provider
                after it is registered.
            modelId: Model identifier understood by the provider.
            modelVersion: Optional model version (defaults to ``"latest"``).
            temperature: Sampling temperature.
            contextSize: Provider-side context-window size in tokens.
            extraConfig: Optional ``support_*`` flags forwarded to the
                provider's ``addModel`` call.

        Raises:
            ValueError: When ``providerType`` is unknown.
        """
        if providerType not in PROVIDER_TYPES:
            raise ValueError(f"Unknown providerType '{providerType}', dood! expected one of {sorted(PROVIDER_TYPES)}.")
        providerCls: type[AbstractLLMProvider] = PROVIDER_TYPES[providerType]
        # Providers expect plain ``dict`` (mutated internally), so make a copy.
        self.provider: AbstractLLMProvider = providerCls(dict(providerConfig))
        self.modelName: str = modelName
        self.provider.addModel(
            name=modelName,
            modelId=modelId,
            modelVersion=modelVersion,
            temperature=temperature,
            contextSize=contextSize,
            extraConfig=dict(extraConfig) if extraConfig is not None else {},
        )
        self.templates: Dict[str, str] = getDefaultTemplates()

    def _selectSystemPrompt(self, systemId: str) -> str:
        """Return the per-system system-prompt template.

        Args:
            systemId: Either ``"tarot"`` or ``"runes"``.

        Returns:
            The corresponding system-prompt string from ``[bot.defaults]``.
        """
        if systemId == "tarot":
            return self.templates["taroSystemPrompt"]
        if systemId == "runes":
            return self.templates["runesSystemPrompt"]
        raise ValueError(f"Unknown systemId '{systemId}', dood!")

    async def runReading(
        self,
        *,
        systemId: str,
        layoutId: str,
        rngSeed: int,
        userName: str,
        question: str,
        lang: str = "ru",
    ) -> Dict[str, Any]:
        """Run a full scenario: draw, build messages, call the LLM.

        Args:
            systemId: ``"tarot"`` or ``"runes"``.
            layoutId: Layout identifier (e.g. ``"three_card"``,
                ``"celtic_cross"``).
            rngSeed: RNG seed for deterministic draws.
            userName: User-display-name placeholder to render into the prompt.
            question: User's question text.
            lang: BCP-47-style language code for symbol/position localisation.

        Returns:
            Dict containing ``messages`` (the rendered ``ModelMessage`` list as
            plain dicts), ``resultText`` from the LLM, and ``draws`` describing
            the symbols that were drawn (system, deck, layout, drawn symbol
            list). The shape is what the replayer test will inspect.
        """
        systemCls: type[BaseDivinationSystem] = resolveSystem(systemId)
        layout: Layout = resolveLayoutForSystem(systemCls, layoutId)
        reading: Reading = buildReading(
            systemCls,
            layout,
            rngSeed=rngSeed,
            question=question,
        )

        messages: List[ModelMessage] = systemCls.buildInterpretationMessages(
            reading,
            userName=userName,
            systemPromptTemplate=self._selectSystemPrompt(systemId),
            userPromptTemplate=self.templates["userPromptTemplate"],
            lang=lang,
        )

        model: Optional[AbstractModel] = self.provider.getModel(self.modelName)
        if model is None:
            raise RuntimeError(f"Model '{self.modelName}' was not registered, dood!")

        result = await model.generateText(messages)

        return {
            "messages": messagesToDicts(messages),
            "resultText": result.resultText if result is not None else None,
            "draws": [
                {
                    "symbolId": draw.symbol.id,
                    "symbolName": draw.symbol.name,
                    "reversed": draw.reversed,
                    "position": draw.position,
                    "positionIndex": draw.positionIndex,
                }
                for draw in reading.draws
            ],
            "systemId": systemCls.systemId,
            "deckId": systemCls.deckId,
            "layoutId": layout.id,
            "layoutNameEn": layout.nameEn,
        }


# Re-export the OpenAI patcher path used by tests.lib_ai.golden so the
# collector script can call it when recording. We do not import it eagerly to
# keep this module importable in environments where ``openai`` is absent.
__all__ = [
    "BOT_DEFAULTS_PATH",
    "DivinationScenarioRunner",
    "PROVIDER_TYPES",
    "REPO_ROOT",
    "SYSTEM_CLASSES",
    "buildReading",
    "getDefaultTemplates",
    "loadBotDefaults",
    "messagesToDicts",
    "resolveLayoutForSystem",
    "resolveSystem",
]
