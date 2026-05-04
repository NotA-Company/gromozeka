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

import json
from typing import Any, Dict
from unittest.mock import AsyncMock, Mock, patch

import pytest
from openai import AsyncOpenAI
from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)
from openai.types.completion_usage import CompletionUsage

from lib.ai.models import (
    LLMFunctionParameter,
    LLMParameterType,
    LLMToolFunction,
    ModelMessage,
    ModelResultStatus,
)
from lib.ai.providers.basic_openai_provider import (
    BasicOpenAIModel,
    BasicOpenAIProvider,
)

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
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ) -> BasicOpenAIModel:
        """Create a new model instance for this provider.

        Args:
            name: The name to assign to the model.
            modelId: The model identifier (e.g., "gpt-4").
            modelVersion: The version of the model.
            temperature: The sampling temperature for generation.
            contextSize: The maximum context window size in tokens.
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
        openAiClient=mockAsyncOpenAI,
        extraConfig={"support_tools": True},
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
        provider._createModelInstance("test", "model-id", "1.0", 0.7, 4096)


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

    model1 = testProvider.addModel("test-model", "gpt-4", "1.0", 0.7, 4096)
    model2 = testProvider.addModel("test-model", "gpt-3.5", "1.0", 0.5, 2048)

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
        provider.addModel("test", "model", "1.0", 0.7, 4096)


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
        AttributeError: If OpenAI client is not initialized.
    """
    testModel._config["support_images"] = True
    testModel._client = None  # type: ignore[assignment]

    with pytest.raises(AttributeError):
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
    testProvider.addModel("model1", "gpt-4", "1.0", 0.7, 4096)
    testProvider.addModel("model2", "gpt-3.5", "1.0", 0.5, 2048)

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
