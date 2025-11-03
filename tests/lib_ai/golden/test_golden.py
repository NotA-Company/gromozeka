"""Golden data tests for AI providers.

These tests use recorded HTTP traffic to test AI providers
without making actual API calls. Each provider has its own
set of test scenarios covering various functionality.

The tests follow the pattern established in the OpenWeatherMap
golden data tests but are adapted for AI provider testing.
"""

from typing import Any

import pytest

from lib.ai.models import ModelMessage

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
            name="meta-llama/llama-3.2-1b-instruct",
            modelId="meta-llama/llama-3.2-1b-instruct",
            modelVersion="latest",
            temperature=0.3,
            contextSize=64000,
            extraConfig={
                "support_text": True,
                "support_tools": True,
                "support_images": False,
            },
        )

        # Get model
        model = provider.getModel("meta-llama/llama-3.2-1b-instruct")

        # Verify model was added successfully
        assert model is not None, "Model 'meta-llama/llama-3.2-1b-instruct' should be available"

        # Prepare messages
        messages = [ModelMessage(role="user", content="Hello, how are you?")]

        # Make a request - this will be replayed from the golden data
        result = await model.generateText(messages)

        # Verify the result
        assert result is not None
        assert result.resultText is not None
        assert len(result.resultText) > 0
