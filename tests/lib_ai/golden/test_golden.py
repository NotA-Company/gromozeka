"""Golden data tests for AI providers.

These tests use recorded HTTP traffic to test AI providers
without making actual API calls. Each provider has its own
set of test scenarios covering various functionality.

The tests follow the pattern established in the OpenWeatherMap
golden data tests but are adapted for AI provider testing.
"""

from typing import Any, Dict

import pytest

from lib.ai.models import ModelMessage, ModelResultStatus, ModelStructuredResult

# Import all AI provider classes
from lib.ai.providers.openrouter_provider import OpenrouterProvider
from lib.ai.providers.yc_openai_provider import YcOpenaiProvider
from lib.aurumentation import baseGoldenDataProvider
from lib.aurumentation.replayer import GoldenDataReplayer

from . import GOLDEN_DATA_PATH
from .openai_patcher import OpenAIReplayerPatcher


@pytest.fixture(scope="session")
def goldenDataProvider() -> Any:
    """Fixture that provides a GoldenDataProvider for AI provider tests."""
    return baseGoldenDataProvider(GOLDEN_DATA_PATH)


# ============================================================================
# YcOpenaiProvider Tests
# ============================================================================


@pytest.mark.asyncio
async def test_yc_openai_basic(goldenDataProvider):
    """Test basic text generation with YcOpenaiProvider using golden data.

    This test verifies that the YC OpenAI provider can generate text responses
    using recorded HTTP traffic, including YC-specific URL formatting.
    """
    # Get the scenario with all golden data
    scenario = goldenDataProvider.getScenario("YCOpenAI Basic")

    openAiPatcher = OpenAIReplayerPatcher()

    # Use GoldenDataReplayer as context manager to patch httpx globally
    async with GoldenDataReplayer(scenario, aenterCallback=openAiPatcher.patch, aexitCallback=openAiPatcher.unpatch):
        # Create provider with fake config - actual values don't matter since we're replaying
        # This must be done AFTER entering the replayer context so the OpenAI client uses the replay transport
        provider = YcOpenaiProvider(
            {
                "api_key": "fake-key-for-testing",
                "folder_id": "fake-folder-id",
            }
        )

        # Add the model that's used in the recorded data
        provider.addModel(
            name="yandexgpt",
            modelId="yandexgpt",
            modelVersion="latest",
            temperature=0.7,
            contextSize=8192,
            extraConfig={},
        )

        # Get model
        model = provider.getModel("yandexgpt")

        # Verify model was added successfully
        assert model is not None, "Model 'yandexgpt' should be available"

        # Prepare messages
        messages = [ModelMessage(role="user", content="Hello, how are you?")]

        # Make a request - this will be replayed from the golden data
        result = await model.generateText(messages)

        # Verify the result
        assert result is not None
        assert result.resultText is not None
        assert len(result.resultText) > 0


# ============================================================================
# OpenrouterProvider Tests
# ============================================================================


@pytest.mark.asyncio
async def test_openrouter_basic(goldenDataProvider):
    """Test basic text generation with OpenrouterProvider using golden data.

    This test verifies that the OpenRouter provider can generate text responses
    using recorded HTTP traffic through the OpenRouter aggregation service.
    """
    # Get the scenario with all golden data
    scenario = goldenDataProvider.getScenario("OpenRouter Basic")

    openAiPatcher = OpenAIReplayerPatcher()

    # Use GoldenDataReplayer as context manager to patch httpx globally
    async with GoldenDataReplayer(scenario, aenterCallback=openAiPatcher.patch, aexitCallback=openAiPatcher.unpatch):
        # Create provider with fake config - actual values don't matter since we're replaying
        # This must be done AFTER entering the replayer context so the OpenAI client uses the replay transport
        provider = OpenrouterProvider(
            {
                "api_key": "fake-key-for-testing",
            }
        )

        # Add the model that's used in the recorded data
        provider.addModel(
            name="qwen/qwen-turbo",
            modelId="qwen/qwen-turbo",
            modelVersion="latest",
            temperature=0.3,
            contextSize=131000,
            extraConfig={
                "support_text": True,
                "support_tools": True,
                "support_images": False,
            },
        )

        # Get model
        model = provider.getModel("qwen/qwen-turbo")

        # Verify model was added successfully
        assert model is not None, "Model 'qwen/qwen-turbo' should be available"

        # Prepare messages
        messages = [ModelMessage(role="user", content="Hello, how are you?")]

        # Make a request - this will be replayed from the golden data
        result = await model.generateText(messages)

        # Verify the result
        assert result is not None
        assert result.resultText is not None
        assert len(result.resultText) > 0


# ============================================================================
# Structured Output Tests
# ============================================================================

_STRUCTURED_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "nCards": {"type": "integer"},
        "positions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["nCards", "positions"],
    "additionalProperties": False,
}
"""Toy JSON Schema shared by the structured-output golden scenarios.

Matches the schema embedded in ``openrouter_scenarios.json`` and
``yc_openai_scenarios.json`` so tests can assert required keys without
duplicating the schema definition.
"""


@pytest.mark.asyncio
async def test_openrouter_structured(goldenDataProvider: Any) -> None:
    """Test structured-output generation with OpenrouterProvider using golden data.

    Replays the ``OpenRouter Structured Toy`` scenario recorded by collect.py.
    Verifies that the provider returns a ModelStructuredResult whose ``data``
    dict contains the required keys from the toy schema.

    Args:
        goldenDataProvider: Session-scoped fixture providing loaded golden scenarios.
    """
    scenario = goldenDataProvider.getScenario("OpenRouter Structured Toy")

    openAiPatcher = OpenAIReplayerPatcher()

    async with GoldenDataReplayer(scenario, aenterCallback=openAiPatcher.patch, aexitCallback=openAiPatcher.unpatch):
        provider = OpenrouterProvider(
            {
                "api_key": "fake-key-for-testing",
            }
        )

        provider.addModel(
            name="qwen/qwen-turbo",
            modelId="qwen/qwen-turbo",
            modelVersion="latest",
            temperature=0.3,
            contextSize=131000,
            extraConfig={
                "support_text": True,
                "support_tools": True,
                "support_images": False,
                "support_structured_output": True,
            },
        )

        model = provider.getModel("qwen/qwen-turbo")
        assert model is not None, "Model 'qwen/qwen-turbo' should be available"

        messages = [
            ModelMessage(role="system", content="Respond with a JSON object matching the provided schema, dood."),
            ModelMessage(role="user", content="Give me a divination layout for a love question."),
        ]

        result = await model.generateStructured(
            messages,
            schema=_STRUCTURED_SCHEMA,
            schemaName="divinationLayout",
            strict=True,
        )

        assert result is not None
        assert isinstance(result, ModelStructuredResult), "Result must be a ModelStructuredResult"
        assert result.status == ModelResultStatus.FINAL, f"Expected FINAL status, got {result.status}"
        assert result.data is not None and isinstance(result.data, dict), "result.data must be a non-None dict"
        assert result.resultText is not None and len(result.resultText) > 0, "result.resultText must be non-empty"
        for requiredKey in _STRUCTURED_SCHEMA["required"]:
            assert requiredKey in result.data, f"Required key '{requiredKey}' missing from result.data"


@pytest.mark.asyncio
async def test_yc_openai_structured(goldenDataProvider: Any) -> None:
    """Test structured-output generation with YcOpenaiProvider using golden data.

    Replays the ``YCOpenAI Structured Toy`` scenario recorded by collect.py.
    Verifies that the provider returns a ModelStructuredResult whose ``data``
    dict contains the required keys from the toy schema.

    Args:
        goldenDataProvider: Session-scoped fixture providing loaded golden scenarios.
    """
    scenario = goldenDataProvider.getScenario("YCOpenAI Structured Toy")

    openAiPatcher = OpenAIReplayerPatcher()

    async with GoldenDataReplayer(scenario, aenterCallback=openAiPatcher.patch, aexitCallback=openAiPatcher.unpatch):
        provider = YcOpenaiProvider(
            {
                "api_key": "fake-key-for-testing",
                "folder_id": "fake-folder-id",
            }
        )

        provider.addModel(
            name="yandexgpt",
            modelId="yandexgpt",
            modelVersion="latest",
            temperature=0.7,
            contextSize=8192,
            extraConfig={
                "support_structured_output": True,
            },
        )

        model = provider.getModel("yandexgpt")
        assert model is not None, "Model 'yandexgpt' should be available"

        messages = [
            ModelMessage(role="system", content="Respond with a JSON object matching the provided schema, dood."),
            ModelMessage(role="user", content="Give me a divination layout for a love question."),
        ]

        result = await model.generateStructured(
            messages,
            schema=_STRUCTURED_SCHEMA,
            schemaName="divinationLayout",
            strict=True,
        )

        assert result is not None
        assert isinstance(result, ModelStructuredResult), "Result must be a ModelStructuredResult"
        assert result.status == ModelResultStatus.FINAL, f"Expected FINAL status, got {result.status}"
        assert result.data is not None and isinstance(result.data, dict), "result.data must be a non-None dict"
        assert result.resultText is not None and len(result.resultText) > 0, "result.resultText must be non-empty"
        for requiredKey in _STRUCTURED_SCHEMA["required"]:
            assert requiredKey in result.data, f"Required key '{requiredKey}' missing from result.data"
