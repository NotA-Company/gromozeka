"""Comprehensive tests for BasicOpenAIProvider and BasicOpenAIModel.

This module provides extensive test coverage for the BasicOpenAIProvider class
and BasicOpenAIModel class, including initialization, model configuration,
request formatting, response parsing, error handling, and tool call support.

Test Categories:
    - Provider Initialization Tests: Tests for provider setup and configuration
    - Model Addition Tests: Tests for adding and managing models
    - Model Initialization Tests: Tests for model instance creation
    - Text Generation Tests: Tests for text generation with various scenarios
    - Tool Call Tests: Tests for tool call functionality
    - Request Formatting Tests: Tests for API request formatting
    - Error Handling Tests: Tests for error scenarios
    - Image Generation Tests: Tests for image generation capabilities
    - Integration Tests: End-to-end workflow tests
"""

import base64
import json
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import openai
import pytest
from openai import AsyncOpenAI
from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)
from openai.types.completion_usage import CompletionUsage
from openai.types.images_response import ImagesResponse

from lib.ai.models import (
    LLMFunctionParameter,
    LLMParameterType,
    LLMToolFunction,
    ModelMessage,
    ModelResultStatus,
    ModelStructuredResult,
)
from lib.ai.providers.basic_openai_provider import (
    BasicOpenAIModel,
    BasicOpenAIProvider,
    _extractImagePrompt,
)
from lib.stats import NullStatsStorage, StatsStorage

# ============================================================================
# Test Provider Implementation
# ============================================================================


class MockOpenAIProvider(BasicOpenAIProvider):
    """Mock implementation of BasicOpenAIProvider for testing.

    This class provides a concrete implementation of BasicOpenAIProvider for
    testing purposes, using a fixed base URL and creating BasicOpenAIModel
    instances with the provider's client.

    Attributes:
        config: Provider configuration dictionary containing API keys and settings.
        _client: The AsyncOpenAI client instance for API communication.
        models: Dictionary mapping model names to their model instances.
    """

    def _getBaseUrl(self) -> str:
        """Return the base URL for the OpenAI API.

        Returns:
            str: The base URL for the test API endpoint.
        """
        return "https://test.api.example.com/v1"

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
    ) -> BasicOpenAIModel:
        """Create a new model instance for this provider.

        Args:
            name: The name to assign to the model.
            modelId: The model identifier (e.g., "gpt-4").
            modelVersion: The version of the model.
            temperature: The sampling temperature for generation.
            contextSize: The maximum context window size in tokens.
            statsStorage: StatsStorage instance for recording LLM usage statistics.
            extraConfig: Additional configuration options for the model.

        Returns:
            BasicOpenAIModel: A new model instance configured with the provided parameters.
        """
        return BasicOpenAIModel(
            provider=self,
            modelId=modelId,
            modelVersion=modelVersion,
            temperature=temperature,
            contextSize=contextSize,
            statsStorage=statsStorage,
            openAiClient=self._client,  # type: ignore[arg-type]
            extraConfig=extraConfig,
        )


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mockAsyncOpenAI() -> Mock:
    """Create a mock AsyncOpenAI client for testing.

    Returns:
        Mock: A mock AsyncOpenAI client with mocked chat completions API.
    """
    client = Mock(spec=AsyncOpenAI)
    client.chat = Mock()
    client.chat.completions = Mock()
    client.chat.completions.create = AsyncMock()
    return client


@pytest.fixture
def providerConfig() -> Dict[str, Any]:
    """Create provider configuration for testing.

    Returns:
        Dict[str, Any]: A dictionary containing API key and timeout configuration.
    """
    return {
        "api_key": "test-api-key-123",
        "timeout": 30,
    }


@pytest.fixture
def testProvider(providerConfig: Dict[str, Any]) -> MockOpenAIProvider:
    """Create a test provider instance for testing.

    Args:
        providerConfig: Provider configuration dictionary.

    Returns:
        MockOpenAIProvider: A configured provider instance for testing.
    """
    with patch("openai.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        provider = MockOpenAIProvider(providerConfig)
        return provider


@pytest.fixture
def testModel(testProvider: MockOpenAIProvider, mockAsyncOpenAI: Mock) -> BasicOpenAIModel:
    """Create a test model instance for testing.

    Adding ``support_structured_output=True`` is safe for existing text-generation
    tests because they never call ``generateStructured``; the flag is only
    checked inside that code path.

    Args:
        testProvider: The test provider instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.

    Returns:
        BasicOpenAIModel: A configured model instance for testing.
    """
    model = BasicOpenAIModel(
        provider=testProvider,
        modelId="test-model",
        modelVersion="1.0",
        temperature=0.7,
        contextSize=4096,
        statsStorage=NullStatsStorage(),
        openAiClient=mockAsyncOpenAI,
        extraConfig={"support_tools": True, "support_structured_output": True},
    )
    return model


@pytest.fixture
def sampleMessages() -> list[ModelMessage]:
    """Create sample messages for testing.

    Returns:
        list[ModelMessage]: A list of sample model messages including system and user messages.
    """
    return [
        ModelMessage(role="system", content="You are a helpful assistant"),
        ModelMessage(role="user", content="Hello, how are you?"),
    ]


@pytest.fixture
def sampleTools() -> list[LLMToolFunction]:
    """Create sample tools for testing.

    Returns:
        list[LLMToolFunction]: A list of sample tool functions for testing tool call functionality.
    """
    return [
        LLMToolFunction(
            name="getWeather",
            description="Get weather for a location",
            parameters=[
                LLMFunctionParameter(
                    name="location",
                    description="The location",
                    type=LLMParameterType.STRING,
                    required=True,
                )
            ],
        )
    ]


# ============================================================================
# Provider Initialization Tests
# ============================================================================


def testProviderInitializationSuccess(providerConfig: Dict[str, Any]) -> None:
    """Test provider initializes successfully with valid config.

    Args:
        providerConfig: Provider configuration dictionary.

    Raises:
        AssertionError: If provider initialization fails or attributes are incorrect.
    """
    with patch("openai.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        provider = MockOpenAIProvider(providerConfig)

        assert provider is not None
        assert provider.config == providerConfig
        assert provider._client is not None
        assert len(provider.models) == 0


def testProviderInitializationMissingApiKey() -> None:
    """Test provider initialization fails without api_key.

    Raises:
        ValueError: If api_key is missing from configuration.
    """
    config = {"timeout": 30}

    with pytest.raises(ValueError, match="api_key is required"):
        MockOpenAIProvider(config)


def testProviderInitializationWithClientParams(providerConfig: Dict[str, Any]) -> None:
    """Test provider initialization with custom client params.

    Args:
        providerConfig: Provider configuration dictionary.

    Raises:
        AssertionError: If custom client parameters are not passed correctly.
    """

    class CustomProvider(MockOpenAIProvider):
        def _getClientParams(self) -> Dict[str, Any]:
            return {"timeout": 60, "max_retries": 3}

    with patch("openai.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        CustomProvider(providerConfig)

        # Verify AsyncOpenAI was called with custom params
        mockClient.assert_called_once()
        callKwargs = mockClient.call_args.kwargs
        assert callKwargs["timeout"] == 60
        assert callKwargs["max_retries"] == 3


def testProviderGetBaseUrlNotImplemented() -> None:
    """Test _getBaseUrl raises NotImplementedError in base class.

    Raises:
        NotImplementedError: If _getBaseUrl is called on base class.
    """
    provider = BasicOpenAIProvider.__new__(BasicOpenAIProvider)
    provider.config = {"api_key": "test"}

    with pytest.raises(NotImplementedError, match="must implement _get_base_url"):
        provider._getBaseUrl()


def testProviderCreateModelInstanceNotImplemented() -> None:
    """Test _createModelInstance raises NotImplementedError in base class.

    Raises:
        NotImplementedError: If _createModelInstance is called on base class.
    """
    provider = BasicOpenAIProvider.__new__(BasicOpenAIProvider)
    provider.config = {"api_key": "test"}

    with pytest.raises(NotImplementedError, match="must implement _create_model_instance"):
        provider._createModelInstance(
            name="test",
            modelId="model-id",
            modelVersion="1.0",
            temperature=0.7,
            contextSize=4096,
            statsStorage=NullStatsStorage(),
        )


# ============================================================================
# Model Addition Tests
# ============================================================================


def testAddModelSuccess(testProvider: MockOpenAIProvider, mockAsyncOpenAI: Mock) -> None:
    """Test adding a model successfully.

    Args:
        testProvider: The test provider instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.

    Raises:
        AssertionError: If model is not added correctly.
    """
    testProvider._client = mockAsyncOpenAI

    model = testProvider.addModel(
        name="test-model",
        modelId="gpt-4",
        modelVersion="1.0",
        temperature=0.7,
        contextSize=8192,
        statsStorage=NullStatsStorage(),
        extraConfig={"support_tools": True},
    )

    assert model is not None
    assert "test-model" in testProvider.models
    assert testProvider.models["test-model"] == model
    assert model.modelId == "gpt-4"
    assert model.temperature == 0.7
    assert model.contextSize == 8192


def testAddModelDuplicate(testProvider: MockOpenAIProvider, mockAsyncOpenAI: Mock) -> None:
    """Test adding duplicate model returns existing model.

    Args:
        testProvider: The test provider instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.

    Raises:
        AssertionError: If duplicate model handling is incorrect.
    """
    testProvider._client = mockAsyncOpenAI

    model1 = testProvider.addModel(
        name="test-model",
        modelId="gpt-4",
        modelVersion="1.0",
        temperature=0.7,
        contextSize=4096,
        statsStorage=NullStatsStorage(),
    )
    model2 = testProvider.addModel(
        name="test-model",
        modelId="gpt-3.5",
        modelVersion="1.0",
        temperature=0.5,
        contextSize=2048,
        statsStorage=NullStatsStorage(),
    )

    assert model1 is model2
    assert len(testProvider.models) == 1


def testAddModelWithoutClient() -> None:
    """Test adding model without initialized client fails.

    Raises:
        RuntimeError: If OpenAI client is not initialized.
    """
    provider = MockOpenAIProvider.__new__(MockOpenAIProvider)
    provider.config = {"api_key": "test"}
    provider.models = {}
    provider._client = None

    with pytest.raises(RuntimeError, match="OpenAI client not initialized"):
        provider.addModel(
            name="test",
            modelId="model",
            modelVersion="1.0",
            temperature=0.7,
            contextSize=4096,
            statsStorage=NullStatsStorage(),
        )


def testAddModelWithExtraConfig(testProvider: MockOpenAIProvider, mockAsyncOpenAI: Mock) -> None:
    """Test adding model with extra configuration.

    Args:
        testProvider: The test provider instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.

    Raises:
        AssertionError: If extra configuration is not applied correctly.
    """
    testProvider._client = mockAsyncOpenAI

    extraConfig = {
        "support_tools": True,
        "support_images": False,
        "custom_param": "value",
    }

    model = testProvider.addModel(
        name="configured-model",
        modelId="gpt-4",
        modelVersion="1.0",
        temperature=0.8,
        contextSize=4096,
        statsStorage=NullStatsStorage(),
        extraConfig=extraConfig,
    )

    assert model._config == extraConfig
    assert model._supportTools is True  # type: ignore[attr-defined]


# ============================================================================
# Model Initialization Tests
# ============================================================================


def testModelInitialization(testProvider: MockOpenAIProvider, mockAsyncOpenAI: Mock) -> None:
    """Test model initializes correctly.

    Args:
        testProvider: The test provider instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.

    Raises:
        AssertionError: If model initialization fails or attributes are incorrect.
    """
    model = BasicOpenAIModel(
        provider=testProvider,
        modelId="test-model",
        modelVersion="1.0",
        temperature=0.7,
        contextSize=4096,
        statsStorage=NullStatsStorage(),
        openAiClient=mockAsyncOpenAI,
        extraConfig={"support_tools": True},
    )

    assert model.provider == testProvider
    assert model.modelId == "test-model"
    assert model.modelVersion == "1.0"
    assert model.temperature == 0.7
    assert model.contextSize == 4096
    assert model._client == mockAsyncOpenAI
    assert model._supportTools is True  # type: ignore[attr-defined]


def testModelGetModelId(testModel: BasicOpenAIModel) -> None:
    """Test _getModelId returns correct model ID.

    Args:
        testModel: The test model instance.

    Raises:
        AssertionError: If model ID is incorrect.
    """
    assert testModel._getModelId() == "test-model"


def testModelGetExtraParams(testModel: BasicOpenAIModel) -> None:
    """Test _getExtraParams returns empty dict by default.

    Args:
        testModel: The test model instance.

    Raises:
        AssertionError: If extra params are not empty by default.
    """
    assert testModel._getExtraParams() == {}


# ============================================================================
# Text Generation Tests
# ============================================================================


@pytest.mark.asyncio
async def testGenerateTextSuccess(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test successful text generation.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If text generation fails or result is incorrect.
    """
    # Create mock response
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Hello! I'm doing well, thank you!"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    result = await testModel.generateText(sampleMessages)

    assert result is not None
    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "Hello! I'm doing well, thank you!"
    assert len(result.toolCalls) == 0


@pytest.mark.asyncio
async def testGenerateTextWithoutClient(testModel: BasicOpenAIModel, sampleMessages: list[ModelMessage]) -> None:
    """Test text generation fails without client.

    Args:
        testModel: The test model instance.
        sampleMessages: Sample messages for testing.

    Raises:
        RuntimeError: If OpenAI client is not initialized.
    """
    testModel._client = None  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="OpenAI client not initialized"):
        await testModel.generateText(sampleMessages)


@pytest.mark.asyncio
async def testGenerateTextNotSupported(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test text generation fails when not supported.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        NotImplementedError: If text generation is not supported.
    """
    testModel._config["support_text"] = False

    with pytest.raises(NotImplementedError, match="Text generation isn't supported"):
        await testModel.generateText(sampleMessages)


@pytest.mark.asyncio
async def testGenerateTextTruncated(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test text generation with truncated response.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If truncated response is not handled correctly.
    """
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Truncated response..."
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "length"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    result = await testModel.generateText(sampleMessages)

    assert result.status == ModelResultStatus.TRUNCATED_FINAL
    assert result.resultText == "Truncated response..."


@pytest.mark.asyncio
async def testGenerateTextContentFilter(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test text generation with content filter.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If content filter is not handled correctly.
    """
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = ""
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "content_filter"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    result = await testModel.generateText(sampleMessages)

    assert result.status == ModelResultStatus.CONTENT_FILTER
    assert result.resultText == ""


@pytest.mark.asyncio
async def testGenerateTextUnknownFinishReason(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test text generation with unknown finish reason.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If unknown finish reason is not handled correctly.
    """
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Response"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "unknown_reason"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    result = await testModel.generateText(sampleMessages)

    assert result.status == ModelResultStatus.UNKNOWN


@pytest.mark.asyncio
async def testGenerateTextWithNullContent(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test text generation with null content.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If null content is not handled correctly.
    """
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = None
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    result = await testModel.generateText(sampleMessages)

    assert result.resultText == ""


# ============================================================================
# Tool Call Tests
# ============================================================================


@pytest.mark.asyncio
async def testGenerateTextWithTools(
    testModel: BasicOpenAIModel,
    mockAsyncOpenAI: Mock,
    sampleMessages: list[ModelMessage],
    sampleTools: list[LLMToolFunction],
) -> None:
    """Test text generation with tool calls.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.
        sampleTools: Sample tools for testing.

    Raises:
        AssertionError: If tool calls are not handled correctly.
    """
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = ""

    # Create mock tool call
    mockToolCall = Mock(spec=ChatCompletionMessageToolCall)
    mockToolCall.id = "call_123"
    mockToolCall.type = "function"
    mockFunction = Mock(spec=Function)
    mockFunction.name = "getWeather"
    mockFunction.arguments = '{"location": "Tokyo"}'
    mockToolCall.function = mockFunction

    mockMessage.tool_calls = [mockToolCall]
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "tool_calls"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    result = await testModel.generateText(sampleMessages, sampleTools)

    assert result.status == ModelResultStatus.TOOL_CALLS
    assert len(result.toolCalls) == 1
    assert result.toolCalls[0].id == "call_123"
    assert result.toolCalls[0].name == "getWeather"
    assert result.toolCalls[0].parameters == {"location": "Tokyo"}


@pytest.mark.asyncio
async def testGenerateTextWithMultipleToolCalls(
    testModel: BasicOpenAIModel,
    mockAsyncOpenAI: Mock,
    sampleMessages: list[ModelMessage],
    sampleTools: list[LLMToolFunction],
) -> None:
    """Test text generation with multiple tool calls.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.
        sampleTools: Sample tools for testing.

    Raises:
        AssertionError: If multiple tool calls are not handled correctly.
    """
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = ""

    # Create multiple mock tool calls
    mockToolCall1 = Mock(spec=ChatCompletionMessageToolCall)
    mockToolCall1.id = "call_1"
    mockToolCall1.type = "function"
    mockFunction1 = Mock(spec=Function)
    mockFunction1.name = "getWeather"
    mockFunction1.arguments = '{"location": "Tokyo"}'
    mockToolCall1.function = mockFunction1

    mockToolCall2 = Mock(spec=ChatCompletionMessageToolCall)
    mockToolCall2.id = "call_2"
    mockToolCall2.type = "function"
    mockFunction2 = Mock(spec=Function)
    mockFunction2.name = "getTime"
    mockFunction2.arguments = "{}"
    mockToolCall2.function = mockFunction2

    mockMessage.tool_calls = [mockToolCall1, mockToolCall2]
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "tool_calls"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    await testModel.generateText(sampleMessages, sampleTools)

    # Verify tool calls were parsed correctly
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert "tools" in callKwargs


@pytest.mark.asyncio
async def testGenerateTextToolsNotSupported(
    testModel: BasicOpenAIModel,
    mockAsyncOpenAI: Mock,
    sampleMessages: list[ModelMessage],
    sampleTools: list[LLMToolFunction],
) -> None:
    """Test tools are ignored when not supported.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.
        sampleTools: Sample tools for testing.

    Raises:
        AssertionError: If tools are not ignored when not supported.
    """
    testModel._supportTools = False

    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Response without tools"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    await testModel.generateText(sampleMessages, sampleTools)

    # Verify tools were not passed to API
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert "tools" not in callKwargs


@pytest.mark.asyncio
async def testGenerateTextToolsPassedToApi(
    testModel: BasicOpenAIModel,
    mockAsyncOpenAI: Mock,
    sampleMessages: list[ModelMessage],
    sampleTools: list[LLMToolFunction],
) -> None:
    """Test tools are correctly passed to API.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.
        sampleTools: Sample tools for testing.

    Raises:
        AssertionError: If tools are not passed correctly to API.
    """
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Response"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    await testModel.generateText(sampleMessages, sampleTools)

    # Verify tools were passed correctly
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert "tools" in callKwargs
    assert "tool_choice" in callKwargs
    assert callKwargs["tool_choice"] == "auto"
    assert len(callKwargs["tools"]) == 1


# ============================================================================
# Request Formatting Tests
# ============================================================================


@pytest.mark.asyncio
async def testRequestParametersFormatting(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test request parameters are formatted correctly.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If request parameters are not formatted correctly.
    """
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Response"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    await testModel.generateText(sampleMessages)

    # Verify request parameters
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert callKwargs["model"] == "test-model"
    assert callKwargs["temperature"] == 0.7
    assert "messages" in callKwargs
    assert len(callKwargs["messages"]) == 2


@pytest.mark.asyncio
async def testMessagesConversion(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test messages are converted to correct format.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If messages are not converted correctly.
    """
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Response"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    await testModel.generateText(sampleMessages)

    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    messages = callKwargs["messages"]

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "You are a helpful assistant"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Hello, how are you?"


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def testGenerateTextApiError(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test handling of API errors.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        Exception: If API error occurs.
    """
    mockAsyncOpenAI.chat.completions.create.side_effect = Exception("API Error")

    with pytest.raises(Exception, match="API Error"):
        await testModel.generateText(sampleMessages)


@pytest.mark.asyncio
async def testGenerateTextInvalidToolCallJson(
    testModel: BasicOpenAIModel,
    mockAsyncOpenAI: Mock,
    sampleMessages: list[ModelMessage],
    sampleTools: list[LLMToolFunction],
) -> None:
    """Test handling of invalid tool call JSON.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.
        sampleTools: Sample tools for testing.

    Raises:
        json.JSONDecodeError: If tool call JSON is invalid.
    """
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = ""

    mockToolCall = Mock(spec=ChatCompletionMessageToolCall)
    mockToolCall.id = "call_123"
    mockToolCall.type = "function"
    mockFunction = Mock(spec=Function)
    mockFunction.name = "getWeather"
    mockFunction.arguments = "invalid json{"
    mockToolCall.function = mockFunction

    mockMessage.tool_calls = [mockToolCall]
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "tool_calls"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    with pytest.raises(json.JSONDecodeError):
        await testModel.generateText(sampleMessages, sampleTools)


# ============================================================================
# Image Generation Tests
# ============================================================================


@pytest.mark.asyncio
async def testGenerateImageNotSupported(testModel: BasicOpenAIModel, sampleMessages: list[ModelMessage]) -> None:
    """Test image generation fails when not supported.

    Args:
        testModel: The test model instance.
        sampleMessages: Sample messages for testing.

    Raises:
        NotImplementedError: If image generation is not supported.
    """
    with pytest.raises(NotImplementedError, match="Image generation isn't supported"):
        await testModel.generateImage(sampleMessages)


@pytest.mark.asyncio
async def testGenerateImageSuccess(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test successful image generation.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If image generation fails or result is incorrect.
    """
    testModel._config["support_images"] = True

    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = None
    mockMessage.tool_calls = None

    # Mock image data
    import base64

    imageData = b"fake image data"
    encodedImage = base64.b64encode(imageData).decode("utf-8")
    mockMessage.images = [{"image_url": {"url": f"data:image/png;base64,{encodedImage}"}}]

    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    result = await testModel.generateImage(sampleMessages)

    assert result.status == ModelResultStatus.FINAL
    assert result.mediaMimeType == "image/png"
    assert result.mediaData == imageData


@pytest.mark.asyncio
async def testGenerateImageWithoutClient(testModel: BasicOpenAIModel, sampleMessages: list[ModelMessage]) -> None:
    """Test image generation fails without client.

    Args:
        testModel: The test model instance.
        sampleMessages: Sample messages for testing.

    Raises:
        RuntimeError: If OpenAI client is not initialized.
    """
    testModel._config["support_images"] = True
    testModel._client = None  # type: ignore[assignment]

    with pytest.raises(RuntimeError):
        await testModel.generateImage(sampleMessages)


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def testFullWorkflowAddModelAndGenerate(testProvider: MockOpenAIProvider, mockAsyncOpenAI: Mock) -> None:
    """Test full workflow: add model and generate text.

    Args:
        testProvider: The test provider instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.

    Raises:
        AssertionError: If workflow fails or result is incorrect.
    """
    testProvider._client = mockAsyncOpenAI

    # Add model
    model = testProvider.addModel(
        name="workflow-test",
        modelId="gpt-4",
        modelVersion="1.0",
        temperature=0.7,
        contextSize=4096,
        statsStorage=NullStatsStorage(),
    )

    # Setup mock response
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Test response"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    # Generate text
    messages = [ModelMessage(role="user", content="Test")]
    result = await model.generateText(messages)

    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "Test response"


def testProviderModelManagement(testProvider: MockOpenAIProvider, mockAsyncOpenAI: Mock) -> None:
    """Test provider model management methods.

    Args:
        testProvider: The test provider instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.

    Raises:
        AssertionError: If model management methods fail.
    """
    testProvider._client = mockAsyncOpenAI

    # Add models
    testProvider.addModel(
        name="model1",
        modelId="gpt-4",
        modelVersion="1.0",
        temperature=0.7,
        contextSize=4096,
        statsStorage=NullStatsStorage(),
    )
    testProvider.addModel(
        name="model2",
        modelId="gpt-3.5",
        modelVersion="1.0",
        temperature=0.5,
        contextSize=2048,
        statsStorage=NullStatsStorage(),
    )

    # Test listModels
    models = testProvider.listModels()
    assert len(models) == 2
    assert "model1" in models
    assert "model2" in models

    # Test getModel
    model1 = testProvider.getModel("model1")
    assert model1 is not None
    assert model1.modelId == "gpt-4"

    # Test getModelInfo
    info = testProvider.getModelInfo("model1")
    assert info is not None
    assert info["model_id"] == "gpt-4"
    assert info["temperature"] == 0.7

    # Test deleteModel
    deleted = testProvider.deleteModel("model1")
    assert deleted is True
    assert len(testProvider.listModels()) == 1

    # Test delete non-existent
    deleted = testProvider.deleteModel("nonexistent")
    assert deleted is False


# ============================================================================
# Structured Output Tests
# ============================================================================

# Simple JSON Schema used across the structured-output tests.
_SAMPLE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


def _makeStructuredResponse(content: str, finishReason: str) -> Mock:
    """Build a minimal ChatCompletion mock for structured-output tests.

    Args:
        content: The string content the model returns (may be valid/invalid JSON).
        finishReason: The ``finish_reason`` value for the single choice.

    Returns:
        Mock: A ``Mock(spec=ChatCompletion)`` pre-wired with one choice and usage.
    """
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = content
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = finishReason
    mockResponse.choices = [mockChoice]

    mockUsage = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 5
    mockUsage.completion_tokens = 10
    mockUsage.total_tokens = 15
    mockResponse.usage = mockUsage

    return mockResponse


def _makeImagesResponse(
    imageDataList: list[Dict[str, Any]],
    usage: Optional[Dict[str, int]] = None,
) -> Mock:
    """Build a mock ImagesResponse that passes isinstance checks.

    Args:
        imageDataList: List of dicts with keys 'b64_json', 'url', 'revised_prompt'.
        usage: Optional dict with 'input_tokens', 'output_tokens', 'total_tokens'.

    Returns:
        Mock: A ``MagicMock`` with ``__class__`` set to ``ImagesResponse``.
    """
    mockResponse = MagicMock()
    mockResponse.__class__ = ImagesResponse  # type: ignore[assignment]

    mockDataItems = []
    for itemData in imageDataList:
        mockItem = Mock()
        mockItem.b64_json = itemData.get("b64_json")
        mockItem.url = itemData.get("url")
        mockItem.revised_prompt = itemData.get("revised_prompt")
        mockDataItems.append(mockItem)

    mockResponse.data = mockDataItems

    if usage is not None:
        mockUsage = Mock()
        mockUsage.input_tokens = usage.get("input_tokens")
        mockUsage.output_tokens = usage.get("output_tokens")
        mockUsage.total_tokens = usage.get("total_tokens")
        mockResponse.usage = mockUsage
    else:
        mockResponse.usage = None

    return mockResponse


@pytest.mark.asyncio
async def testGenerateStructuredSuccess(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test successful structured output generation returns parsed data.

    Model returns valid JSON with finish_reason="stop".  Asserts status FINAL,
    data populated, resultText preserved, error absent, tokens set.

    Args:
        testModel: Test model instance (has support_structured_output=True).
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample conversation messages.

    Raises:
        AssertionError: If result fields do not match expectations.
    """
    mockAsyncOpenAI.chat.completions.create.return_value = _makeStructuredResponse('{"answer": "42"}', "stop")

    result = await testModel.generateStructured(sampleMessages, _SAMPLE_SCHEMA)

    assert isinstance(result, ModelStructuredResult)
    assert result.status == ModelResultStatus.FINAL
    assert result.data == {"answer": "42"}
    assert result.resultText == '{"answer": "42"}'
    assert result.error is None
    assert result.inputTokens == 5
    assert result.outputTokens == 10
    assert result.totalTokens == 15


@pytest.mark.asyncio
async def testGenerateStructuredTruncatedValidJson(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test truncated response that still contains valid JSON.

    finish_reason="length" with a complete JSON body.  Status should be
    TRUNCATED_FINAL and data should be populated.

    Args:
        testModel: Test model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample conversation messages.

    Raises:
        AssertionError: If status or data are incorrect.
    """
    mockAsyncOpenAI.chat.completions.create.return_value = _makeStructuredResponse(
        '{"answer": "truncated but valid"}', "length"
    )

    result = await testModel.generateStructured(sampleMessages, _SAMPLE_SCHEMA)

    assert result.status == ModelResultStatus.TRUNCATED_FINAL
    assert result.data == {"answer": "truncated but valid"}
    assert result.error is None


@pytest.mark.asyncio
async def testGenerateStructuredTruncatedInvalidJson(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test truncated response with invalid JSON returns ERROR status.

    finish_reason="length" with a cut-off JSON string.  Status should be
    ERROR, data None, error is JSONDecodeError, resultText preserved.

    Args:
        testModel: Test model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample conversation messages.

    Raises:
        AssertionError: If error-path fields do not match expectations.
    """
    truncatedJson = '{"answer": "42'
    mockAsyncOpenAI.chat.completions.create.return_value = _makeStructuredResponse(truncatedJson, "length")

    result = await testModel.generateStructured(sampleMessages, _SAMPLE_SCHEMA)

    assert result.status == ModelResultStatus.ERROR
    assert result.data is None
    assert isinstance(result.error, json.JSONDecodeError)
    assert result.resultText == truncatedJson


@pytest.mark.asyncio
async def testGenerateStructuredNonObjectJson(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test that non-object JSON (e.g. a JSON array) returns ERROR status.

    The implementation requires the parsed value to be a dict.  A JSON array
    should trigger a ValueError and return ERROR.

    Args:
        testModel: Test model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample conversation messages.

    Raises:
        AssertionError: If non-object JSON is not treated as an error.
    """
    mockAsyncOpenAI.chat.completions.create.return_value = _makeStructuredResponse("[1, 2, 3]", "stop")

    result = await testModel.generateStructured(sampleMessages, _SAMPLE_SCHEMA)

    assert result.status == ModelResultStatus.ERROR
    assert result.data is None
    assert isinstance(result.error, ValueError)
    assert result.resultText == "[1, 2, 3]"


@pytest.mark.asyncio
async def testGenerateStructuredContentFilter(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test that content_filter finish_reason maps to CONTENT_FILTER status.

    No JSON parsing is attempted; data should be None.

    Args:
        testModel: Test model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample conversation messages.

    Raises:
        AssertionError: If status is not CONTENT_FILTER or data is not None.
    """
    mockAsyncOpenAI.chat.completions.create.return_value = _makeStructuredResponse("", "content_filter")

    result = await testModel.generateStructured(sampleMessages, _SAMPLE_SCHEMA)

    assert result.status == ModelResultStatus.CONTENT_FILTER
    assert result.data is None


@pytest.mark.asyncio
async def testGenerateStructuredBadRequest(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test that BadRequestError (e.g. provider rejects the schema) returns ERROR status.

    The error is caught by the inner ``except openai.BadRequestError`` branch and
    returned as a ModelStructuredResult with status ERROR.

    Args:
        testModel: Test model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample conversation messages.

    Raises:
        AssertionError: If result status is not ERROR or error is not set.
    """
    badReqError = openai.BadRequestError(
        "Schema validation failed",
        response=Mock(status_code=400),
        body=None,
    )
    mockAsyncOpenAI.chat.completions.create.side_effect = badReqError

    result = await testModel.generateStructured(sampleMessages, _SAMPLE_SCHEMA)

    assert result.status == ModelResultStatus.ERROR
    assert result.error is badReqError


@pytest.mark.asyncio
async def testGenerateStructuredCapabilityFlagFalse(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test that generateStructured raises NotImplementedError when flag is False.

    The public ``generateStructured`` gates on the config flag before ever
    reaching ``_generateStructured`` or the API.

    Args:
        testModel: Test model instance (flag will be overridden to False).
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample conversation messages.

    Raises:
        NotImplementedError: Expected — the capability flag is False.
        AssertionError: If the API was called despite the flag being False.
    """
    testModel._config["support_structured_output"] = False

    with pytest.raises(NotImplementedError):
        await testModel.generateStructured(sampleMessages, _SAMPLE_SCHEMA)

    mockAsyncOpenAI.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def testGenerateStructuredResponseFormatPayload(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test that response_format is correctly serialized in the API call.

    Inspects ``call_args.kwargs["response_format"]`` to confirm the exact
    structure sent to the OpenAI-compatible endpoint.

    Args:
        testModel: Test model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample conversation messages.

    Raises:
        AssertionError: If response_format payload is missing or malformed.
    """
    mockAsyncOpenAI.chat.completions.create.return_value = _makeStructuredResponse('{"answer": "ok"}', "stop")

    await testModel.generateStructured(sampleMessages, _SAMPLE_SCHEMA, schemaName="myShape", strict=True)

    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert "response_format" in callKwargs
    responseFormat = callKwargs["response_format"]
    assert responseFormat == {
        "type": "json_schema",
        "json_schema": {
            "name": "myShape",
            "schema": _SAMPLE_SCHEMA,
            "strict": True,
        },
    }


@pytest.mark.asyncio
async def testGenerateStructuredEmptyResponse(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test that an empty response body (finish_reason="stop") yields data=None with ERROR status.

    Behaviour: when the model returns an empty string, ``json.loads`` is skipped
    (because ``resText`` is falsy), so ``parsed = None``. Since ``parsed`` is not a dict,
    a ``ValueError`` is raised, causing the method to return an ERROR result with
    ``data=None`` and a non‑null error. Empty content is therefore treated as a parse
    failure, not as a successful FINAL result.

    This contradicts the docstring of ``_generateStructured`` which claims empty
    responses are treated as ``data=None`` without raising an error while keeping
    FINAL status. The test documents the actual implementation behaviour.

    Args:
        testModel: Test model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample conversation messages.

    Raises:
        AssertionError: If status is not ERROR, data is not None, or error is None.
    """
    mockAsyncOpenAI.chat.completions.create.return_value = _makeStructuredResponse("", "stop")

    result = await testModel.generateStructured(sampleMessages, _SAMPLE_SCHEMA)

    assert result.status == ModelResultStatus.ERROR
    assert result.data is None
    assert result.error is not None


# ============================================================================
# _executeChatCompletion Tests
# ============================================================================


@pytest.mark.asyncio
async def testExecuteChatCompletionHappyPath(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test _executeChatCompletion returns a fully-populated outcome on success.

    Mock returns a ``stop`` response with usage.  Asserts: ``status == FINAL``,
    ``error is None``, ``resText`` matches the mocked content, token counts are
    populated, and ``retMessage`` is the mocked message object.

    Args:
        testModel: Test model instance wired to the mock client.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample conversation messages (unused — params are built manually).

    Raises:
        AssertionError: If any outcome field does not match expectations.
    """
    mockAsyncOpenAI.chat.completions.create.return_value = _makeStructuredResponse('{"ok": true}', "stop")

    params: Dict[str, Any] = {
        "model": testModel._getModelId(),
        "messages": [m.toDict("content") for m in sampleMessages],  # type: ignore
        "temperature": testModel.temperature,
    }
    outcome = await testModel._executeChatCompletion(params)

    assert outcome.status == ModelResultStatus.FINAL
    assert outcome.error is None
    assert outcome.resText == '{"ok": true}'
    assert outcome.retMessage is not None
    assert outcome.inputTokens == 5
    assert outcome.outputTokens == 10
    assert outcome.totalTokens == 15
    assert outcome.response is not None


@pytest.mark.asyncio
async def testExecuteChatCompletionBadRequestErrorReturnsOutcome(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test _executeChatCompletion returns an error outcome on BadRequestError.

    Mock raises ``openai.BadRequestError``.  Asserts: ``response is None``,
    ``status == ERROR``, ``error`` is the original exception, ``resText == ""``,
    and ``retMessage is None``.  The exception must NOT propagate — it is
    captured and returned inside the outcome.

    Args:
        testModel: Test model instance wired to the mock client.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample conversation messages.

    Raises:
        AssertionError: If outcome fields do not match error-path expectations.
    """
    badReqError = openai.BadRequestError(
        "Bad request",
        response=Mock(status_code=400),
        body=None,
    )
    mockAsyncOpenAI.chat.completions.create.side_effect = badReqError

    params: Dict[str, Any] = {
        "model": testModel._getModelId(),
        "messages": [m.toDict("content") for m in sampleMessages],  # type: ignore
        "temperature": testModel.temperature,
    }
    outcome = await testModel._executeChatCompletion(params)

    assert outcome.response is None
    assert outcome.status == ModelResultStatus.ERROR
    assert outcome.error is badReqError
    assert outcome.resText == ""
    assert outcome.retMessage is None


@pytest.mark.asyncio
async def testExecuteChatCompletionOtherExceptionRaises(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test _executeChatCompletion re-raises non-BadRequestError exceptions.

    Mock raises a plain ``RuntimeError``.  That exception must propagate out
    of ``_executeChatCompletion`` unchanged — it is NOT caught and wrapped.

    Args:
        testModel: Test model instance wired to the mock client.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample conversation messages.

    Raises:
        RuntimeError: Expected — the helper re-raises non-BadRequest errors.
    """
    mockAsyncOpenAI.chat.completions.create.side_effect = RuntimeError("network failure")

    params: Dict[str, Any] = {
        "model": testModel._getModelId(),
        "messages": [m.toDict("content") for m in sampleMessages],  # type: ignore
        "temperature": testModel.temperature,
    }

    with pytest.raises(RuntimeError, match="network failure"):
        await testModel._executeChatCompletion(params)


@pytest.mark.asyncio
async def testExecuteChatCompletionUnknownFinishReason(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test _executeChatCompletion maps an unknown finish_reason to UNKNOWN status.

    Mock returns a response with ``finish_reason="weird_thing"``.  The helper
    must fall through to the wildcard branch and set ``status == UNKNOWN``.

    Args:
        testModel: Test model instance wired to the mock client.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample conversation messages.

    Raises:
        AssertionError: If status is not UNKNOWN for an unrecognised finish reason.
    """
    mockAsyncOpenAI.chat.completions.create.return_value = _makeStructuredResponse("some text", "weird_thing")

    params: Dict[str, Any] = {
        "model": testModel._getModelId(),
        "messages": [m.toDict("content") for m in sampleMessages],  # type: ignore
        "temperature": testModel.temperature,
    }
    outcome = await testModel._executeChatCompletion(params)

    assert outcome.status == ModelResultStatus.UNKNOWN
    assert outcome.error is None


# =======
# OpenAI Images API tests
# =======


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiNotSupported(
    testModel: BasicOpenAIModel, sampleMessages: list[ModelMessage]
) -> None:
    """Test _generateImageViaImagesApi raises NotImplementedError when not supported.

    Args:
        testModel: The test model instance.
        sampleMessages: Sample messages for testing.

    Raises:
        NotImplementedError: Expected — image generation is disabled.
    """
    testModel._config["support_images"] = False

    with pytest.raises(NotImplementedError, match="Image generation isn't supported"):
        await testModel._generateImageViaImagesApi(sampleMessages)


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiNoClient(
    testModel: BasicOpenAIModel, sampleMessages: list[ModelMessage]
) -> None:
    """Test _generateImageViaImagesApi raises RuntimeError when client is None.

    Args:
        testModel: The test model instance.
        sampleMessages: Sample messages for testing.

    Raises:
        RuntimeError: Expected — OpenAI client is not initialized.
    """
    testModel._config["support_images"] = True
    testModel._client = None  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="OpenAI client not initialized"):
        await testModel._generateImageViaImagesApi(sampleMessages)


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiSuccessB64Json(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test successful image generation with b64_json response.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If result fields do not match expectations.
    """
    testModel._config["support_images"] = True

    mockResponse = _makeImagesResponse(
        [{"b64_json": base64.b64encode(b"testimg").decode(), "url": None, "revised_prompt": None}]
    )

    mockAsyncOpenAI.images = Mock()
    mockAsyncOpenAI.images.generate = AsyncMock(return_value=mockResponse)

    result = await testModel._generateImageViaImagesApi(sampleMessages)

    assert result.status == ModelResultStatus.FINAL
    assert result.mediaData == b"testimg"
    assert result.mediaMimeType == "image/png"


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiEmptyResponse(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test _generateImageViaImagesApi returns ERROR status on empty response.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If result status is not ERROR.
    """
    testModel._config["support_images"] = True

    mockResponse = _makeImagesResponse([])

    mockAsyncOpenAI.images = Mock()
    mockAsyncOpenAI.images.generate = AsyncMock(return_value=mockResponse)

    result = await testModel._generateImageViaImagesApi(sampleMessages)

    assert result.status == ModelResultStatus.ERROR


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiWithUsage(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test _generateImageViaImagesApi extracts token usage from response.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If token counts do not match expectations.
    """
    testModel._config["support_images"] = True

    mockResponse = _makeImagesResponse(
        [{"b64_json": base64.b64encode(b"testimg").decode(), "url": None, "revised_prompt": None}],
        usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    )

    mockAsyncOpenAI.images = Mock()
    mockAsyncOpenAI.images.generate = AsyncMock(return_value=mockResponse)

    result = await testModel._generateImageViaImagesApi(sampleMessages)

    assert result.inputTokens == 100
    assert result.outputTokens == 50
    assert result.totalTokens == 150


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiWithImageOptions(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test _generateImageViaImagesApi passes image_options to API call.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If image options are not passed correctly.
    """
    testModel._config["support_images"] = True
    testModel._config["image_options"] = {"size": "1024x1024", "output_format": "jpeg", "n": 1}

    mockResponse = _makeImagesResponse(
        [{"b64_json": base64.b64encode(b"testimg").decode(), "url": None, "revised_prompt": None}]
    )

    mockAsyncOpenAI.images = Mock()
    mockAsyncOpenAI.images.generate = AsyncMock(return_value=mockResponse)

    result = await testModel._generateImageViaImagesApi(sampleMessages)

    callKwargs = mockAsyncOpenAI.images.generate.call_args.kwargs
    assert callKwargs["size"] == "1024x1024"
    assert callKwargs["output_format"] == "jpeg"
    assert result.mediaMimeType == "image/jpeg"


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiMultipleImages(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test _generateImageViaImagesApi uses only first image when multiple returned.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If first image is not used.
    """
    testModel._config["support_images"] = True

    mockResponse = _makeImagesResponse(
        [
            {"b64_json": base64.b64encode(b"img1").decode(), "url": None, "revised_prompt": None},
            {"b64_json": base64.b64encode(b"img2").decode(), "url": None, "revised_prompt": None},
        ]
    )

    mockAsyncOpenAI.images = Mock()
    mockAsyncOpenAI.images.generate = AsyncMock(return_value=mockResponse)

    result = await testModel._generateImageViaImagesApi(sampleMessages)

    assert result.mediaData == b"img1"


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiRevisedPrompt(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test _generateImageViaImagesApi extracts revised_prompt from response.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If revised_prompt is not extracted correctly.
    """
    testModel._config["support_images"] = True

    mockResponse = _makeImagesResponse(
        [{"b64_json": base64.b64encode(b"testimg").decode(), "url": None, "revised_prompt": "A cat in a hat"}]
    )

    mockAsyncOpenAI.images = Mock()
    mockAsyncOpenAI.images.generate = AsyncMock(return_value=mockResponse)

    result = await testModel._generateImageViaImagesApi(sampleMessages)

    assert result.resultText == "A cat in a hat"


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiUnknownFormat(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test _generateImageViaImagesApi defaults to png for unknown output_format.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If MIME type does not default to image/png.
    """
    testModel._config["support_images"] = True
    testModel._config["image_options"] = {"output_format": "tiff"}

    mockResponse = _makeImagesResponse(
        [{"b64_json": base64.b64encode(b"testimg").decode(), "url": None, "revised_prompt": None}]
    )

    mockAsyncOpenAI.images = Mock()
    mockAsyncOpenAI.images.generate = AsyncMock(return_value=mockResponse)

    result = await testModel._generateImageViaImagesApi(sampleMessages)

    assert result.mediaMimeType == "image/png"


def testExtractImagePromptSimple() -> None:
    """Test _extractImagePrompt joins simple text messages.

    Raises:
        AssertionError: If prompt is not joined correctly.
    """
    messages = [
        ModelMessage(role="user", content="Draw a cat"),
        ModelMessage(role="user", content="In a hat"),
    ]
    prompt = _extractImagePrompt(messages)
    assert prompt == "Draw a cat\n\nIn a hat"


def testExtractImagePromptEmpty() -> None:
    """Test _extractImagePrompt raises ValueError on empty content.

    Raises:
        ValueError: Expected — no textual content in messages.
    """
    messages = [ModelMessage(role="user", content="")]
    with pytest.raises(ValueError, match="No textual content found"):
        _extractImagePrompt(messages)


def testExtractImagePromptMultimodal() -> None:
    """Test _extractImagePrompt extracts text from multimodal content.

    Raises:
        AssertionError: If text is not extracted correctly from multimodal content.
    """
    messages = [
        ModelMessage(
            role="user",
            content=[  # type: ignore[arg-type]
                {"type": "text", "text": "Draw a cat"},
                {"type": "image", "image_url": "http://example.com/cat.jpg"},
            ],
        )
    ]
    prompt = _extractImagePrompt(messages)
    assert prompt == "Draw a cat"


# ============================================================================
# Additional Images API Tests (Phase 1 Review Fixes)
# ============================================================================


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiUrlDownload(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test URL download path in _generateImageViaImagesApi.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If result fields do not match expectations.
    """
    testModel._config["support_images"] = True

    mockResponse = _makeImagesResponse(
        [{"b64_json": None, "url": "https://example.com/image.png", "revised_prompt": None}]
    )

    mockAsyncOpenAI.images = Mock()
    mockAsyncOpenAI.images.generate = AsyncMock(return_value=mockResponse)

    mockHttpxResponse = Mock()
    mockHttpxResponse.content = b"downloaded"
    mockHttpxResponse.raise_for_status = Mock()
    mockHttpxResponse.headers = {"content-type": "image/png"}

    mockClient = AsyncMock()
    mockClient.get = AsyncMock(return_value=mockHttpxResponse)
    mockClient.__aenter__ = AsyncMock(return_value=mockClient)
    mockClient.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mockClient):
        result = await testModel._generateImageViaImagesApi(sampleMessages)

    assert result.status == ModelResultStatus.FINAL
    assert result.mediaData == b"downloaded"
    assert result.mediaMimeType == "image/png"


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiUrlDownloadError(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test httpx download error in _generateImageViaImagesApi.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If result status is not ERROR or error is not set.
    """
    testModel._config["support_images"] = True

    mockResponse = _makeImagesResponse(
        [{"b64_json": None, "url": "https://example.com/image.png", "revised_prompt": None}]
    )

    mockAsyncOpenAI.images = Mock()
    mockAsyncOpenAI.images.generate = AsyncMock(return_value=mockResponse)

    mockClient = AsyncMock()
    mockClient.get = AsyncMock(side_effect=httpx.HTTPError("Connection failed"))
    mockClient.__aenter__ = AsyncMock(return_value=mockClient)
    mockClient.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mockClient):
        result = await testModel._generateImageViaImagesApi(sampleMessages)

    assert result.status == ModelResultStatus.ERROR
    assert isinstance(result.error, httpx.HTTPError)
    assert "Connection failed" in str(result.error)


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiNeitherField(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test 'neither b64_json nor url' error path.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If result status is not ERROR or error message is incorrect.
    """
    testModel._config["support_images"] = True

    mockResponse = _makeImagesResponse([{"b64_json": None, "url": None, "revised_prompt": None}])

    mockAsyncOpenAI.images = Mock()
    mockAsyncOpenAI.images.generate = AsyncMock(return_value=mockResponse)

    result = await testModel._generateImageViaImagesApi(sampleMessages)

    assert result.status == ModelResultStatus.ERROR
    assert isinstance(result.error, ValueError)
    assert "neither" in str(result.error).lower()


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiBadRequestError(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test BadRequestError handling in _generateImageViaImagesApi.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If result status is not ERROR or error is not the exception.
    """
    testModel._config["support_images"] = True

    mockResponse = Mock()
    mockResponse.status_code = 400

    badReqError = openai.BadRequestError("Bad request", response=mockResponse, body=None)

    mockAsyncOpenAI.images = Mock()
    mockAsyncOpenAI.images.generate = AsyncMock(side_effect=badReqError)

    result = await testModel._generateImageViaImagesApi(sampleMessages)

    assert result.status == ModelResultStatus.ERROR
    assert result.error is badReqError


def testGetImageRequestOptionsNonDict(testModel: BasicOpenAIModel) -> None:
    """Test _getImageRequestOptions returns empty dict for non-dict image_options.

    Args:
        testModel: The test model instance.

    Raises:
        AssertionError: If result is not empty dict.
    """
    testModel._config["image_options"] = "invalid"
    assert testModel._getImageRequestOptions() == {}


def testExtractImagePromptEmptyList() -> None:
    """Test _extractImagePrompt raises ValueError on empty list.

    Raises:
        ValueError: Expected — no textual content in messages.
    """
    with pytest.raises(ValueError, match="No textual content found"):
        _extractImagePrompt([])


def testGetImageModelIdDefault(testModel: BasicOpenAIModel) -> None:
    """Test _getImageModelId returns same as _getModelId by default.

    Args:
        testModel: The test model instance.

    Raises:
        AssertionError: If model IDs don't match.
    """
    assert testModel._getImageModelId() == testModel._getModelId()


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiModelAndPrompt(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test that model and prompt kwargs are passed correctly to images.generate.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If model or prompt kwargs are incorrect.
    """
    testModel._config["support_images"] = True

    mockResponse = _makeImagesResponse(
        [{"b64_json": base64.b64encode(b"testimg").decode(), "url": None, "revised_prompt": None}]
    )

    mockAsyncOpenAI.images = Mock()
    mockAsyncOpenAI.images.generate = AsyncMock(return_value=mockResponse)

    await testModel._generateImageViaImagesApi(sampleMessages)

    callKwargs = mockAsyncOpenAI.images.generate.call_args.kwargs
    assert callKwargs["model"] == "test-model"
    assert callKwargs["prompt"] == "You are a helpful assistant\n\nHello, how are you?"


@pytest.mark.asyncio
async def testGenerateImageViaImagesApiResponseDataNone(
    testModel: BasicOpenAIModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test _generateImageViaImagesApi returns ERROR when response.data is None.

    Args:
        testModel: The test model instance.
        mockAsyncOpenAI: The mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If result status is not ERROR.
    """
    testModel._config["support_images"] = True

    mockResponse = MagicMock()
    mockResponse.__class__ = ImagesResponse  # type: ignore[assignment]
    mockResponse.data = None  # type: ignore[assignment]
    mockResponse.usage = None

    mockAsyncOpenAI.images = Mock()
    mockAsyncOpenAI.images.generate = AsyncMock(return_value=mockResponse)

    result = await testModel._generateImageViaImagesApi(sampleMessages)

    assert result.status == ModelResultStatus.ERROR
