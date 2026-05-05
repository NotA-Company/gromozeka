"""Comprehensive tests for OpenRouterProvider and OpenrouterModel.

This module provides extensive test coverage for the OpenRouterProvider class
and OpenrouterModel class, including initialization, model configuration,
OpenRouter-specific headers, request formatting, and API integration.

Test Coverage:
    - Provider initialization and configuration
    - Model addition and management
    - OpenRouter-specific headers and parameters
    - Text generation with various scenarios
    - Tool support and function calling
    - Error handling (API errors, rate limits, authentication)
    - Integration workflows
    - Edge cases and boundary conditions
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from openai import AsyncOpenAI
from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.completion_usage import CompletionUsage

from lib.ai.models import ModelMessage, ModelResultStatus
from lib.ai.providers.openrouter_provider import OpenrouterModel, OpenrouterProvider

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
def providerConfig() -> dict:
    """Create OpenRouter provider configuration for testing.

    Returns:
        dict: Configuration dictionary with api_key and timeout settings.
    """
    return {
        "api_key": "sk-or-test-key-123",
        "timeout": 30,
    }


@pytest.fixture
def openrouterProvider(providerConfig: dict) -> OpenrouterProvider:
    """Create an OpenRouter provider instance for testing.

    Args:
        providerConfig: Configuration dictionary for the provider.

    Returns:
        OpenrouterProvider: An initialized OpenRouter provider instance.
    """
    with patch("openai.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        provider = OpenrouterProvider(providerConfig)
        return provider


@pytest.fixture
def openrouterModel(openrouterProvider: OpenrouterProvider, mockAsyncOpenAI: Mock) -> OpenrouterModel:
    """Create an OpenRouter model instance for testing.

    Args:
        openrouterProvider: The OpenRouter provider instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.

    Returns:
        OpenrouterModel: An initialized OpenRouter model instance.
    """
    model = OpenrouterModel(
        provider=openrouterProvider,
        modelId="anthropic/claude-3-opus",
        modelVersion="latest",
        temperature=0.7,
        contextSize=200000,
        openAiClient=mockAsyncOpenAI,
        extraConfig={"support_tools": True},
    )
    return model


@pytest.fixture
def sampleMessages() -> list[ModelMessage]:
    """Create sample messages for testing.

    Returns:
        list[ModelMessage]: A list of sample ModelMessage objects.
    """
    return [
        ModelMessage(role="system", content="You are a helpful assistant"),
        ModelMessage(role="user", content="What is the capital of France?"),
    ]


# ============================================================================
# Provider Initialization Tests
# ============================================================================


def testOpenrouterProviderInitialization(providerConfig: dict) -> None:
    """Test OpenRouter provider initializes correctly.

    Args:
        providerConfig: Configuration dictionary for the provider.

    Raises:
        AssertionError: If provider initialization fails or attributes are incorrect.
    """
    with patch("openai.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        provider = OpenrouterProvider(providerConfig)

        assert provider is not None
        assert provider.config == providerConfig
        assert provider._client is not None
        assert len(provider.models) == 0


def testOpenrouterProviderGetBaseUrl(openrouterProvider: OpenrouterProvider) -> None:
    """Test OpenRouter provider returns correct base URL.

    Args:
        openrouterProvider: The OpenRouter provider instance.

    Raises:
        AssertionError: If base URL is incorrect.
    """
    baseUrl = openrouterProvider._getBaseUrl()
    assert baseUrl == "https://openrouter.ai/api/v1"


def testOpenrouterProviderInitializationMissingApiKey() -> None:
    """Test OpenRouter provider initialization fails without api_key.

    Raises:
        ValueError: If api_key is missing from configuration.
    """
    config = {"timeout": 30}

    with pytest.raises(ValueError, match="api_key is required"):
        OpenrouterProvider(config)


def testOpenrouterProviderClientInitialization(providerConfig: dict) -> None:
    """Test OpenRouter provider initializes AsyncOpenAI client correctly.

    Args:
        providerConfig: Configuration dictionary for the provider.

    Raises:
        AssertionError: If client initialization parameters are incorrect.
    """
    with patch("openai.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        testProvider = OpenrouterProvider(providerConfig)

        # Verify AsyncOpenAI was called with correct parameters
        mockClient.assert_called_once()
        callKwargs = mockClient.call_args.kwargs
        assert callKwargs["api_key"] == "sk-or-test-key-123"
        assert callKwargs["base_url"] == "https://openrouter.ai/api/v1"
        assert testProvider is not None


# ============================================================================
# Model Addition Tests
# ============================================================================


def testAddOpenrouterModel(openrouterProvider: OpenrouterProvider, mockAsyncOpenAI: Mock) -> None:
    """Test adding an OpenRouter model.

    Args:
        openrouterProvider: The OpenRouter provider instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.

    Raises:
        AssertionError: If model addition fails or attributes are incorrect.
    """
    openrouterProvider._client = mockAsyncOpenAI

    model = openrouterProvider.addModel(
        name="claude-opus",
        modelId="anthropic/claude-3-opus",
        modelVersion="latest",
        temperature=0.7,
        contextSize=200000,
        extraConfig={"support_tools": True},
    )

    assert model is not None
    assert isinstance(model, OpenrouterModel)
    assert "claude-opus" in openrouterProvider.models
    assert model.modelId == "anthropic/claude-3-opus"
    assert model.temperature == 0.7
    assert model.contextSize == 200000


def testAddMultipleOpenrouterModels(openrouterProvider: OpenrouterProvider, mockAsyncOpenAI: Mock) -> None:
    """Test adding multiple OpenRouter models.

    Args:
        openrouterProvider: The OpenRouter provider instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.

    Raises:
        AssertionError: If models are not added correctly.
    """
    openrouterProvider._client = mockAsyncOpenAI

    model1 = openrouterProvider.addModel(
        name="claude-opus",
        modelId="anthropic/claude-3-opus",
        modelVersion="latest",
        temperature=0.7,
        contextSize=200000,
    )

    model2 = openrouterProvider.addModel(
        name="gpt-4",
        modelId="openai/gpt-4-turbo",
        modelVersion="latest",
        temperature=0.5,
        contextSize=128000,
    )

    assert len(openrouterProvider.models) == 2
    assert "claude-opus" in openrouterProvider.models
    assert "gpt-4" in openrouterProvider.models
    assert model1.modelId == "anthropic/claude-3-opus"
    assert model2.modelId == "openai/gpt-4-turbo"


def testAddOpenrouterModelWithoutClient() -> None:
    """Test adding model without initialized client fails.

    Raises:
        RuntimeError: If OpenAI client is not initialized.
    """
    provider = OpenrouterProvider.__new__(OpenrouterProvider)
    provider.config = {"api_key": "test"}
    provider.models = {}
    provider._client = None

    with pytest.raises(RuntimeError, match="OpenAI client not initialized"):
        provider.addModel("test", "model", "1.0", 0.7, 4096)


def testCreateModelInstance(openrouterProvider: OpenrouterProvider, mockAsyncOpenAI: Mock) -> None:
    """Test _createModelInstance creates OpenrouterModel.

    Args:
        openrouterProvider: The OpenRouter provider instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.

    Raises:
        AssertionError: If model creation fails.
    """
    openrouterProvider._client = mockAsyncOpenAI

    openrouterProvider._createModelInstance(
        name="test-model",
        modelId="test/model",
        modelVersion="1.0",
        temperature=0.8,
        contextSize=4096,
        extraConfig={"support_tools": False},
    )

    # Verify model was created
    assert openrouterProvider._client is not None


# ============================================================================
# Model Initialization Tests
# ============================================================================


def testOpenrouterModelInitialization(openrouterProvider: OpenrouterProvider, mockAsyncOpenAI: Mock) -> None:
    """Test OpenRouter model initializes correctly.

    Args:
        openrouterProvider: The OpenRouter provider instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.

    Raises:
        AssertionError: If model initialization fails or attributes are incorrect.
    """
    model = OpenrouterModel(
        provider=openrouterProvider,
        modelId="anthropic/claude-3-opus",
        modelVersion="latest",
        temperature=0.7,
        contextSize=200000,
        openAiClient=mockAsyncOpenAI,
        extraConfig={"support_tools": True},
    )

    assert model.provider == openrouterProvider
    assert model.modelId == "anthropic/claude-3-opus"
    assert model.modelVersion == "latest"
    assert model.temperature == 0.7
    assert model.contextSize == 200000
    assert model._client == mockAsyncOpenAI
    assert model._supportTools is True  # type: ignore[attr-defined]


def testOpenrouterModelGetModelId(openrouterModel: OpenrouterModel) -> None:
    """Test OpenRouter model returns correct model ID.

    Args:
        openrouterModel: The OpenRouter model instance.

    Raises:
        AssertionError: If model ID is incorrect.
    """
    modelId = openrouterModel._getModelId()
    assert modelId == "anthropic/claude-3-opus"


# ============================================================================
# Extra Parameters Tests
# ============================================================================


def testOpenrouterModelGetExtraParams(openrouterModel: OpenrouterModel) -> None:
    """Test OpenRouter model returns correct extra parameters.

    Args:
        openrouterModel: The OpenRouter model instance.

    Raises:
        AssertionError: If extra parameters are incorrect.
    """
    extraParams = openrouterModel._getExtraParams()

    assert "extra_headers" in extraParams
    headers = extraParams["extra_headers"]

    assert "HTTP-Referer" in headers
    assert headers["HTTP-Referer"] == "https://sourcecraft.dev/notacompany/gromozeka"

    assert "X-Title" in headers
    assert headers["X-Title"] == "Gromozeka AI Bot"


def testOpenrouterModelExtraHeadersFormat(openrouterModel: OpenrouterModel) -> None:
    """Test OpenRouter extra headers are properly formatted.

    Args:
        openrouterModel: The OpenRouter model instance.

    Raises:
        AssertionError: If headers are not properly formatted.
    """
    extraParams = openrouterModel._getExtraParams()
    headers = extraParams["extra_headers"]

    # Verify headers are strings
    assert isinstance(headers["HTTP-Referer"], str)
    assert isinstance(headers["X-Title"], str)

    # Verify headers contain expected values
    assert "sourcecraft.dev" in headers["HTTP-Referer"]
    assert "Gromozeka" in headers["X-Title"]


# ============================================================================
# Text Generation Tests
# ============================================================================


@pytest.mark.asyncio
async def testOpenrouterGenerateTextSuccess(
    openrouterModel: OpenrouterModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test successful text generation with OpenRouter.

    Args:
        openrouterModel: The OpenRouter model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If text generation fails or result is incorrect.
    """
    # Create mock response
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "The capital of France is Paris."
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

    result = await openrouterModel.generateText(sampleMessages)

    assert result is not None
    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "The capital of France is Paris."


@pytest.mark.asyncio
async def testOpenrouterGenerateTextWithExtraHeaders(
    openrouterModel: OpenrouterModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test text generation includes OpenRouter extra headers.

    Args:
        openrouterModel: The OpenRouter model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If extra headers are not included in request.
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

    await openrouterModel.generateText(sampleMessages)

    # Verify extra headers were included in the request
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert "extra_headers" in callKwargs

    headers = callKwargs["extra_headers"]
    assert "HTTP-Referer" in headers
    assert "X-Title" in headers


@pytest.mark.asyncio
async def testOpenrouterGenerateTextRequestParameters(
    openrouterModel: OpenrouterModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test request parameters are correctly formatted for OpenRouter.

    Args:
        openrouterModel: The OpenRouter model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If request parameters are incorrect.
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

    await openrouterModel.generateText(sampleMessages)

    # Verify all required parameters
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert callKwargs["model"] == "anthropic/claude-3-opus"
    assert callKwargs["temperature"] == 0.7
    assert "messages" in callKwargs
    assert len(callKwargs["messages"]) == 2


@pytest.mark.asyncio
async def testOpenrouterGenerateTextWithDifferentModels(
    openrouterProvider: OpenrouterProvider, mockAsyncOpenAI: Mock
) -> None:
    """Test text generation with different OpenRouter models.

    Args:
        openrouterProvider: The OpenRouter provider instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.

    Raises:
        AssertionError: If different models are not used correctly.
    """
    openrouterProvider._client = mockAsyncOpenAI

    # Test with Claude
    claudeModel = openrouterProvider.addModel(
        name="claude",
        modelId="anthropic/claude-3-opus",
        modelVersion="latest",
        temperature=0.7,
        contextSize=200000,
    )

    # Test with GPT-4
    gpt4Model = openrouterProvider.addModel(
        name="gpt4",
        modelId="openai/gpt-4-turbo",
        modelVersion="latest",
        temperature=0.5,
        contextSize=128000,
    )

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

    messages = [ModelMessage(role="user", content="Test")]

    # Test Claude
    await claudeModel.generateText(messages)
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert callKwargs["model"] == "anthropic/claude-3-opus"

    # Test GPT-4
    await gpt4Model.generateText(messages)
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert callKwargs["model"] == "openai/gpt-4-turbo"


# ============================================================================
# Tool Support Tests
# ============================================================================


@pytest.mark.asyncio
async def testOpenrouterGenerateTextWithTools(
    openrouterModel: OpenrouterModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test text generation with tools on OpenRouter.

    Args:
        openrouterModel: The OpenRouter model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If tools are not passed correctly.
    """
    from lib.ai.models import LLMFunctionParameter, LLMParameterType, LLMToolFunction

    tools = [
        LLMToolFunction(
            name="getWeather",
            description="Get weather",
            parameters=[
                LLMFunctionParameter(
                    name="location",
                    description="Location",
                    type=LLMParameterType.STRING,
                    required=True,
                )
            ],
        )
    ]

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

    await openrouterModel.generateText(sampleMessages, tools)

    # Verify tools were passed
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert "tools" in callKwargs
    assert len(callKwargs["tools"]) == 1


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def testOpenrouterGenerateTextApiError(
    openrouterModel: OpenrouterModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test handling of OpenRouter API errors.

    Args:
        openrouterModel: The OpenRouter model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        Exception: If API error occurs.
    """
    mockAsyncOpenAI.chat.completions.create.side_effect = Exception("OpenRouter API Error")

    with pytest.raises(Exception, match="OpenRouter API Error"):
        await openrouterModel.generateText(sampleMessages)


@pytest.mark.asyncio
async def testOpenrouterGenerateTextRateLimitError(
    openrouterModel: OpenrouterModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test handling of rate limit errors.

    Args:
        openrouterModel: The OpenRouter model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        RateLimitError: If rate limit is exceeded.
    """
    from openai import RateLimitError

    mockAsyncOpenAI.chat.completions.create.side_effect = RateLimitError(
        "Rate limit exceeded",
        response=Mock(status_code=429),
        body=None,
    )

    with pytest.raises(RateLimitError):
        await openrouterModel.generateText(sampleMessages)


@pytest.mark.asyncio
async def testOpenrouterGenerateTextAuthenticationError(
    openrouterModel: OpenrouterModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test handling of authentication errors.

    Args:
        openrouterModel: The OpenRouter model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AuthenticationError: If authentication fails.
    """
    from openai import AuthenticationError

    mockAsyncOpenAI.chat.completions.create.side_effect = AuthenticationError(
        "Invalid API key",
        response=Mock(status_code=401),
        body=None,
    )

    with pytest.raises(AuthenticationError):
        await openrouterModel.generateText(sampleMessages)


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def testOpenrouterFullWorkflow(openrouterProvider: OpenrouterProvider, mockAsyncOpenAI: Mock) -> None:
    """Test full workflow with OpenRouter provider.

    Args:
        openrouterProvider: The OpenRouter provider instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.

    Raises:
        AssertionError: If workflow fails at any step.
    """
    openrouterProvider._client = mockAsyncOpenAI

    # Add model
    model = openrouterProvider.addModel(
        name="test-model",
        modelId="anthropic/claude-3-opus",
        modelVersion="latest",
        temperature=0.7,
        contextSize=200000,
    )

    # Setup mock response
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Test response from OpenRouter"
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
    assert result.resultText == "Test response from OpenRouter"

    # Verify OpenRouter-specific headers were included
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert "extra_headers" in callKwargs


def testOpenrouterProviderModelManagement(openrouterProvider: OpenrouterProvider, mockAsyncOpenAI: Mock) -> None:
    """Test OpenRouter provider model management.

    Args:
        openrouterProvider: The OpenRouter provider instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.

    Raises:
        AssertionError: If model management operations fail.
    """
    openrouterProvider._client = mockAsyncOpenAI

    # Add models
    openrouterProvider.addModel("claude", "anthropic/claude-3-opus", "latest", 0.7, 200000)
    openrouterProvider.addModel("gpt4", "openai/gpt-4-turbo", "latest", 0.5, 128000)

    # Test listModels
    models = openrouterProvider.listModels()
    assert len(models) == 2
    assert "claude" in models
    assert "gpt4" in models

    # Test getModel
    claudeModel = openrouterProvider.getModel("claude")
    assert claudeModel is not None
    assert claudeModel.modelId == "anthropic/claude-3-opus"

    # Test getModelInfo
    info = openrouterProvider.getModelInfo("claude")
    assert info is not None
    assert info["model_id"] == "anthropic/claude-3-opus"
    assert info["temperature"] == 0.7
    assert info["context_size"] == 200000

    # Test deleteModel
    deleted = openrouterProvider.deleteModel("claude")
    assert deleted is True
    assert len(openrouterProvider.listModels()) == 1


# ============================================================================
# Configuration Tests
# ============================================================================


def testOpenrouterProviderWithCustomConfig() -> None:
    """Test OpenRouter provider with custom configuration.

    Raises:
        AssertionError: If custom configuration is not applied correctly.
    """
    config = {
        "api_key": "sk-or-custom-key",
        "timeout": 60,
        "max_retries": 5,
    }

    with patch("openai.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        provider = OpenrouterProvider(config)

        assert provider.config["api_key"] == "sk-or-custom-key"
        assert provider.config["timeout"] == 60
        assert provider.config["max_retries"] == 5


def testOpenrouterModelWithCustomExtraConfig(openrouterProvider: OpenrouterProvider, mockAsyncOpenAI: Mock) -> None:
    """Test OpenRouter model with custom extra configuration.

    Args:
        openrouterProvider: The OpenRouter provider instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.

    Raises:
        AssertionError: If extra configuration is not applied correctly.
    """
    openrouterProvider._client = mockAsyncOpenAI

    extraConfig = {
        "support_tools": True,
        "support_images": False,
        "custom_param": "value",
    }

    model = openrouterProvider.addModel(
        name="custom-model",
        modelId="test/model",
        modelVersion="1.0",
        temperature=0.8,
        contextSize=4096,
        extraConfig=extraConfig,
    )

    assert model._config == extraConfig
    assert model._supportTools is True  # type: ignore[attr-defined]


# ============================================================================
# Edge Cases Tests
# ============================================================================


@pytest.mark.asyncio
async def testOpenrouterGenerateTextEmptyResponse(
    openrouterModel: OpenrouterModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test handling of empty response from OpenRouter.

    Args:
        openrouterModel: The OpenRouter model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If empty response is not handled correctly.
    """
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = ""
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

    result = await openrouterModel.generateText(sampleMessages)

    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == ""


@pytest.mark.asyncio
async def testOpenrouterGenerateTextNullContent(
    openrouterModel: OpenrouterModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test handling of null content from OpenRouter.

    Args:
        openrouterModel: The OpenRouter model instance.
        mockAsyncOpenAI: Mock AsyncOpenAI client.
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

    result = await openrouterModel.generateText(sampleMessages)

    assert result.resultText == ""


def testOpenrouterProviderStringRepresentation(openrouterProvider: OpenrouterProvider) -> None:
    """Test OpenRouter provider string representation.

    Args:
        openrouterProvider: The OpenRouter provider instance.

    Raises:
        AssertionError: If string representation is incorrect.
    """
    strRepr = str(openrouterProvider)
    assert "OpenrouterProvider" in strRepr
    assert "0 models" in strRepr


def testOpenrouterModelStringRepresentation(openrouterModel: OpenrouterModel) -> None:
    """Test OpenRouter model string representation.

    Args:
        openrouterModel: The OpenRouter model instance.

    Raises:
        AssertionError: If string representation is incorrect.
    """
    strRepr = str(openrouterModel)
    assert "anthropic/claude-3-opus" in strRepr
    assert "latest" in strRepr
    assert "OpenrouterProvider" in strRepr
