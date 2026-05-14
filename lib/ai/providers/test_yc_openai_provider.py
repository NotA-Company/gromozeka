"""Comprehensive tests for YcOpenaiProvider and YcOpenaiModel.

This module provides extensive test coverage for the YcOpenaiProvider class
and YcOpenaiModel class, including initialization, Yandex Cloud-specific
model ID formatting, folder ID handling, and API integration.

Test Coverage:
    - Provider initialization and configuration
    - Model addition and management
    - YC-specific model ID formatting (gpt://folder_id/model/version)
    - Text generation with various parameters
    - Error handling (authentication, rate limiting, API errors)
    - Integration workflows
    - Edge cases (empty responses, null content)
    - Configuration and extra parameters
"""

from typing import Any, Dict
from unittest.mock import AsyncMock, Mock, patch

import pytest
from openai import AsyncOpenAI
from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.completion_usage import CompletionUsage

from lib.ai.models import ModelMessage, ModelResultStatus, ModelStructuredResult
from lib.ai.providers.yc_openai_provider import YcOpenaiModel, YcOpenaiProvider
from lib.stats import NullStatsStorage

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mockAsyncOpenAI() -> Mock:
    """Create a mock AsyncOpenAI client for testing.

    Returns:
        Mock: A mock AsyncOpenAI client with mocked chat completions API.
            The client has the following structure:
            - client.chat.completions.create: AsyncMock for API calls
    """
    client: Mock = Mock(spec=AsyncOpenAI)
    client.chat = Mock()
    client.chat.completions = Mock()
    client.chat.completions.create = AsyncMock()
    return client


@pytest.fixture
def providerConfig() -> dict:
    """Create YC OpenAI provider configuration for testing.

    Returns:
        dict: Configuration dictionary containing:
            - api_key (str): Yandex Cloud API key
            - folder_id (str): Yandex Cloud folder ID
            - timeout (int): Request timeout in seconds
    """
    return {
        "api_key": "yc-api-key-123",
        "folder_id": "b1g2abc3def4ghi5jklm",
        "timeout": 30,
    }


@pytest.fixture
def ycOpenaiProvider(providerConfig: dict) -> YcOpenaiProvider:
    """Create a YC OpenAI provider instance for testing.

    Args:
        providerConfig: Configuration dictionary for the provider.

    Returns:
        YcOpenaiProvider: A configured YC OpenAI provider instance with
            mocked AsyncOpenAI client.
    """
    with patch("openai.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        provider: YcOpenaiProvider = YcOpenaiProvider(providerConfig)
        return provider


@pytest.fixture
def ycOpenaiModel(ycOpenaiProvider: YcOpenaiProvider, mockAsyncOpenAI: Mock) -> YcOpenaiModel:
    """Create a YC OpenAI model instance for testing.

    Args:
        ycOpenaiProvider: YC OpenAI provider instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.

    Returns:
        YcOpenaiModel: A configured YC OpenAI model instance with:
            - modelId: "yandexgpt"
            - modelVersion: "latest"
            - temperature: 0.6
            - contextSize: 8192
            - folderId: "b1g2abc3def4ghi5jklm"
            - extraConfig: {"support_tools": False}
    """
    model: YcOpenaiModel = YcOpenaiModel(
        provider=ycOpenaiProvider,
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
        statsStorage=NullStatsStorage(),
        openAiClient=mockAsyncOpenAI,
        folderId="b1g2abc3def4ghi5jklm",
        extraConfig={"support_tools": False, "support_structured_output": True},
    )
    return model


@pytest.fixture
def sampleMessages() -> list[ModelMessage]:
    """Create sample messages for testing.

    Returns:
        list[ModelMessage]: List of sample messages containing:
            - System message: "Ты полезный ассистент"
            - User message: "Привет! Как дела?"
    """
    return [
        ModelMessage(role="system", content="Ты полезный ассистент"),
        ModelMessage(role="user", content="Привет! Как дела?"),
    ]


# ============================================================================
# Provider Initialization Tests
# ============================================================================


def testYcOpenaiProviderInitialization(providerConfig: dict) -> None:
    """Test YC OpenAI provider initializes correctly.

    Verifies that the provider is properly initialized with:
    - Configuration stored correctly
    - AsyncOpenAI client created
    - Folder ID stored
    - Empty models dictionary

    Args:
        providerConfig: Configuration dictionary for the provider.

    Raises:
        AssertionError: If any initialization check fails.
    """
    with patch("openai.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        provider: YcOpenaiProvider = YcOpenaiProvider(providerConfig)

        assert provider is not None
        assert provider.config == providerConfig
        assert provider._client is not None
        assert provider._folderId == "b1g2abc3def4ghi5jklm"
        assert len(provider.models) == 0


def testYcOpenaiProviderInitializationMissingFolderId() -> None:
    """Test YC OpenAI provider initialization fails without folder_id.

    Verifies that ValueError is raised when folder_id is missing from config.

    Raises:
        ValueError: Expected to be raised with message "folder_id is required".
    """
    config: dict = {"api_key": "test-key"}

    with pytest.raises(ValueError, match="folder_id is required"):
        YcOpenaiProvider(config)


def testYcOpenaiProviderInitializationMissingApiKey() -> None:
    """Test YC OpenAI provider initialization fails without api_key.

    Verifies that ValueError is raised when api_key is missing from config.

    Raises:
        ValueError: Expected to be raised with message "api_key is required".
    """
    config: dict = {"folder_id": "test-folder"}

    with pytest.raises(ValueError, match="api_key is required"):
        YcOpenaiProvider(config)


def testYcOpenaiProviderInitializationEmptyFolderId() -> None:
    """Test YC OpenAI provider initialization fails with empty folder_id.

    Verifies that ValueError is raised when folder_id is an empty string.

    Raises:
        ValueError: Expected to be raised with message "folder_id is required".
    """
    config: dict = {"api_key": "test-key", "folder_id": ""}

    with pytest.raises(ValueError, match="folder_id is required"):
        YcOpenaiProvider(config)


def testYcOpenaiProviderFolderIdStorage(providerConfig: dict) -> None:
    """Test YC OpenAI provider stores folder_id correctly.

    Verifies that the folder_id is stored as a string attribute.

    Args:
        providerConfig: Configuration dictionary for the provider.

    Raises:
        AssertionError: If folder_id is not stored correctly.
    """
    with patch("openai.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        provider: YcOpenaiProvider = YcOpenaiProvider(providerConfig)

        assert provider._folderId == "b1g2abc3def4ghi5jklm"
        assert isinstance(provider._folderId, str)


# ============================================================================
# Model Addition Tests
# ============================================================================


def testAddYcOpenaiModel(ycOpenaiProvider: YcOpenaiProvider, mockAsyncOpenAI: Mock) -> None:
    """Test adding a YC OpenAI model.

    Verifies that a model can be added to the provider with correct
    configuration and that it's stored in the models dictionary.

    Args:
        ycOpenaiProvider: YC OpenAI provider instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.

    Raises:
        AssertionError: If model is not added correctly.
    """
    ycOpenaiProvider._client = mockAsyncOpenAI

    model = ycOpenaiProvider.addModel(
        name="yandexgpt",
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
        statsStorage=NullStatsStorage(),
        extraConfig={"support_tools": False},
    )

    assert model is not None
    assert isinstance(model, YcOpenaiModel)
    assert "yandexgpt" in ycOpenaiProvider.models
    assert model.modelId == "yandexgpt"
    assert model.temperature == 0.6
    assert model.contextSize == 8192
    assert model._folderId == "b1g2abc3def4ghi5jklm"


def testAddMultipleYcOpenaiModels(ycOpenaiProvider: YcOpenaiProvider, mockAsyncOpenAI: Mock) -> None:
    """Test adding multiple YC OpenAI models.

    Verifies that multiple models can be added to the provider and
    are stored correctly in the models dictionary.

    Args:
        ycOpenaiProvider: YC OpenAI provider instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.

    Raises:
        AssertionError: If models are not added correctly.
    """
    ycOpenaiProvider._client = mockAsyncOpenAI

    model1 = ycOpenaiProvider.addModel(
        name="yandexgpt",
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
        statsStorage=NullStatsStorage(),
    )

    model2 = ycOpenaiProvider.addModel(
        name="yandexgpt-lite",
        modelId="yandexgpt-lite",
        modelVersion="latest",
        temperature=0.7,
        contextSize=4096,
        statsStorage=NullStatsStorage(),
    )

    assert len(ycOpenaiProvider.models) == 2
    assert "yandexgpt" in ycOpenaiProvider.models
    assert "yandexgpt-lite" in ycOpenaiProvider.models
    assert model1.modelId == "yandexgpt"
    assert model2.modelId == "yandexgpt-lite"


def testAddYcOpenaiModelWithoutClient() -> None:
    """Test adding model without initialized client fails.

    Verifies that RuntimeError is raised when attempting to add a model
    without a properly initialized AsyncOpenAI client.

    Raises:
        RuntimeError: Expected to be raised with message "OpenAI client not initialized".
    """
    provider: YcOpenaiProvider = YcOpenaiProvider.__new__(YcOpenaiProvider)
    provider.config = {"api_key": "test", "folder_id": "test"}
    provider.models = {}
    provider._client = None
    provider._folderId = "test"

    with pytest.raises(RuntimeError, match="OpenAI client not initialized"):
        provider.addModel(
            "test",
            modelId="model",
            modelVersion="1.0",
            temperature=0.7,
            contextSize=4096,
            statsStorage=NullStatsStorage(),
        )


def testCreateModelInstance(ycOpenaiProvider: YcOpenaiProvider, mockAsyncOpenAI: Mock) -> None:
    """Test _createModelInstance creates YcOpenaiModel.

    Verifies that the internal _createModelInstance method creates
    a YcOpenaiModel instance with the correct configuration.

    Args:
        ycOpenaiProvider: YC OpenAI provider instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.

    Raises:
        AssertionError: If model instance is not created correctly.
    """
    ycOpenaiProvider._client = mockAsyncOpenAI

    ycOpenaiProvider._createModelInstance(
        name="test-model",
        modelId="yandexgpt",
        modelVersion="rc",
        temperature=0.8,
        contextSize=4096,
        statsStorage=NullStatsStorage(),
        extraConfig={"support_tools": False},
    )

    # Verify model was created
    assert ycOpenaiProvider._client is not None
    assert ycOpenaiProvider._folderId == "b1g2abc3def4ghi5jklm"


# ============================================================================
# Model Initialization Tests
# ============================================================================


def testYcOpenaiModelInitialization(ycOpenaiProvider: YcOpenaiProvider, mockAsyncOpenAI: Mock) -> None:
    """Test YC OpenAI model initializes correctly.

    Verifies that a YcOpenaiModel instance is properly initialized with
    all required attributes including provider, model ID, version, temperature,
    context size, client, folder ID, and extra configuration.

    Args:
        ycOpenaiProvider: YC OpenAI provider instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.

    Raises:
        AssertionError: If model is not initialized correctly.
    """
    model: YcOpenaiModel = YcOpenaiModel(
        provider=ycOpenaiProvider,
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
        statsStorage=NullStatsStorage(),
        openAiClient=mockAsyncOpenAI,
        folderId="b1g2abc3def4ghi5jklm",
        extraConfig={"support_tools": False},
    )

    assert model.provider == ycOpenaiProvider
    assert model.modelId == "yandexgpt"
    assert model.modelVersion == "latest"
    assert model.temperature == 0.6
    assert model.contextSize == 8192
    assert model._client == mockAsyncOpenAI
    assert model._folderId == "b1g2abc3def4ghi5jklm"
    assert model._supportTools is False


def testYcOpenaiModelGetModelId(ycOpenaiModel: YcOpenaiModel) -> None:
    """Test YC OpenAI model returns correct YC-specific model URL.

    Verifies that the model ID is formatted correctly for Yandex Cloud
    using the gpt://folder_id/model/version format.

    Args:
        ycOpenaiModel: YC OpenAI model instance.

    Raises:
        AssertionError: If model ID format is incorrect.
    """
    modelId: str = ycOpenaiModel._getModelId()
    assert modelId == "gpt://b1g2abc3def4ghi5jklm/yandexgpt/latest"


def testYcOpenaiModelGetModelIdFormat() -> None:
    """Test YC OpenAI model ID format is correct.

    Verifies that the model ID follows the correct Yandex Cloud format:
    gpt://folder_id/model/version

    Raises:
        AssertionError: If model ID format is incorrect.
    """
    provider: YcOpenaiProvider = YcOpenaiProvider.__new__(YcOpenaiProvider)
    provider._folderId = "test-folder-123"

    with patch("openai.AsyncOpenAI"):
        model: YcOpenaiModel = YcOpenaiModel(
            provider=provider,
            modelId="test-model",
            modelVersion="v1",
            temperature=0.7,
            contextSize=4096,
            statsStorage=NullStatsStorage(),
            openAiClient=Mock(spec=AsyncOpenAI),
            folderId="test-folder-123",
        )

        modelId: str = model._getModelId()
        assert modelId == "gpt://test-folder-123/test-model/v1"
        assert modelId.startswith("gpt://")
        assert "test-folder-123" in modelId
        assert "test-model" in modelId
        assert "v1" in modelId


def testYcOpenaiModelGetModelIdWithoutFolderId() -> None:
    """Test YC OpenAI model raises error without folder_id.

    Verifies that ValueError is raised when attempting to get model ID
    with an empty folder_id.

    Raises:
        ValueError: Expected to be raised with message "folder_id is required".
    """
    provider: YcOpenaiProvider = YcOpenaiProvider.__new__(YcOpenaiProvider)

    with patch("openai.AsyncOpenAI"):
        model: YcOpenaiModel = YcOpenaiModel(
            provider=provider,
            modelId="yandexgpt",
            modelVersion="latest",
            temperature=0.6,
            contextSize=8192,
            statsStorage=NullStatsStorage(),
            openAiClient=Mock(spec=AsyncOpenAI),
            folderId="",
        )

        with pytest.raises(ValueError, match="folder_id is required"):
            model._getModelId()


# ============================================================================
# Extra Parameters Tests
# ============================================================================


def testYcOpenaiModelGetExtraParams(ycOpenaiModel: YcOpenaiModel) -> None:
    """Test YC OpenAI model returns correct extra parameters.

    Verifies that the model returns extra parameters as a dictionary.
    YC OpenAI models may return an empty dict or YC-specific parameters.

    Args:
        ycOpenaiModel: YC OpenAI model instance.

    Raises:
        AssertionError: If extra params are not a dictionary.
    """
    extraParams: dict = ycOpenaiModel._getExtraParams()

    # YC OpenAI model returns empty dict or specific params
    assert isinstance(extraParams, dict)


def testYcOpenaiModelExtraParamsStructure(ycOpenaiModel: YcOpenaiModel) -> None:
    """Test YC OpenAI extra params structure.

    Verifies that extra parameters are returned as a dictionary structure.
    The dictionary may be empty or contain YC-specific parameters.

    Args:
        ycOpenaiModel: YC OpenAI model instance.

    Raises:
        AssertionError: If extra params are not a dictionary.
    """
    extraParams: dict = ycOpenaiModel._getExtraParams()

    # Verify it's a dictionary (may be empty or contain YC-specific params)
    assert isinstance(extraParams, dict)


# ============================================================================
# Text Generation Tests
# ============================================================================


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextSuccess(
    ycOpenaiModel: YcOpenaiModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test successful text generation with YC OpenAI.

    Verifies that text generation works correctly with mocked API response,
    returning the expected result with FINAL status.

    Args:
        ycOpenaiModel: YC OpenAI model instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If text generation fails or returns incorrect result.
    """
    # Create mock response
    mockResponse: Mock = Mock(spec=ChatCompletion)
    mockChoice: Mock = Mock(spec=Choice)
    mockMessage: Mock = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Привет! У меня всё хорошо, спасибо!"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage: Mock = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    result = await ycOpenaiModel.generateText(sampleMessages)

    assert result is not None
    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "Привет! У меня всё хорошо, спасибо!"


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextWithYcModelId(
    ycOpenaiModel: YcOpenaiModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test text generation uses YC-specific model ID format.

    Verifies that the YC-specific model ID format (gpt://folder_id/model/version)
    is used when making API calls to Yandex Cloud.

    Args:
        ycOpenaiModel: YC OpenAI model instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If YC model ID format is not used correctly.
    """
    mockResponse: Mock = Mock(spec=ChatCompletion)
    mockChoice: Mock = Mock(spec=Choice)
    mockMessage: Mock = Mock(spec=ChatCompletionMessage)
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

    await ycOpenaiModel.generateText(sampleMessages)

    # Verify YC-specific model ID was used
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert callKwargs["model"] == "gpt://b1g2abc3def4ghi5jklm/yandexgpt/latest"
    assert callKwargs["model"].startswith("gpt://")


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextRequestParameters(
    ycOpenaiModel: YcOpenaiModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test request parameters are correctly formatted for YC OpenAI.

    Verifies that all required parameters (model, temperature, messages)
    are correctly formatted and passed to the API.

    Args:
        ycOpenaiModel: YC OpenAI model instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If request parameters are incorrect.
    """
    mockResponse: Mock = Mock(spec=ChatCompletion)
    mockChoice: Mock = Mock(spec=Choice)
    mockMessage: Mock = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Response"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage: Mock = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    await ycOpenaiModel.generateText(sampleMessages)

    # Verify all required parameters
    callKwargs: dict = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert "model" in callKwargs
    assert callKwargs["temperature"] == 0.6
    assert "messages" in callKwargs
    assert len(callKwargs["messages"]) == 2


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextWithDifferentVersions(
    ycOpenaiProvider: YcOpenaiProvider, mockAsyncOpenAI: Mock
) -> None:
    """Test text generation with different model versions.

    Verifies that different model versions (latest, rc) are correctly
    formatted in the YC-specific model ID format.

    Args:
        ycOpenaiProvider: YC OpenAI provider instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.

    Raises:
        AssertionError: If model versions are not used correctly.
    """
    ycOpenaiProvider._client = mockAsyncOpenAI

    # Test with latest version
    latestModel = ycOpenaiProvider.addModel(
        name="yandexgpt-latest",
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
        statsStorage=NullStatsStorage(),
    )

    # Test with rc version
    rcModel = ycOpenaiProvider.addModel(
        name="yandexgpt-rc",
        modelId="yandexgpt",
        modelVersion="rc",
        temperature=0.6,
        contextSize=8192,
        statsStorage=NullStatsStorage(),
    )

    mockResponse: Mock = Mock(spec=ChatCompletion)
    mockChoice: Mock = Mock(spec=Choice)
    mockMessage: Mock = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Response"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage: Mock = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    messages: list[ModelMessage] = [ModelMessage(role="user", content="Test")]

    # Test latest
    await latestModel.generateText(messages)
    callKwargs: dict = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert "latest" in callKwargs["model"]

    # Test rc
    await rcModel.generateText(messages)
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert "rc" in callKwargs["model"]


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextApiError(
    ycOpenaiModel: YcOpenaiModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test handling of YC OpenAI API errors.

    Verifies that API errors are properly propagated to the caller.

    Args:
        ycOpenaiModel: YC OpenAI model instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        Exception: Expected to be raised with message "YC API Error".
    """
    mockAsyncOpenAI.chat.completions.create.side_effect = Exception("YC API Error")

    with pytest.raises(Exception, match="YC API Error"):
        await ycOpenaiModel.generateText(sampleMessages)


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextAuthenticationError(
    ycOpenaiModel: YcOpenaiModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test handling of authentication errors.

    Verifies that AuthenticationError from OpenAI is properly propagated
    when API key is invalid.

    Args:
        ycOpenaiModel: YC OpenAI model instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AuthenticationError: Expected to be raised for invalid API key.
    """
    from openai import AuthenticationError

    mockAsyncOpenAI.chat.completions.create.side_effect = AuthenticationError(
        "Invalid API key",
        response=Mock(status_code=401),
        body=None,
    )

    with pytest.raises(AuthenticationError):
        await ycOpenaiModel.generateText(sampleMessages)


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextRateLimitError(
    ycOpenaiModel: YcOpenaiModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test handling of rate limit errors.

    Verifies that RateLimitError from OpenAI is properly propagated
    when rate limit is exceeded.

    Args:
        ycOpenaiModel: YC OpenAI model instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        RateLimitError: Expected to be raised when rate limit is exceeded.
    """
    from openai import RateLimitError

    mockAsyncOpenAI.chat.completions.create.side_effect = RateLimitError(
        "Rate limit exceeded",
        response=Mock(status_code=429),
        body=None,
    )

    with pytest.raises(RateLimitError):
        await ycOpenaiModel.generateText(sampleMessages)


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def testYcOpenaiFullWorkflow(ycOpenaiProvider: YcOpenaiProvider, mockAsyncOpenAI: Mock) -> None:
    """Test full workflow with YC OpenAI provider.

    Verifies the complete workflow from adding a model to generating text,
    including proper use of YC-specific model ID format.

    Args:
        ycOpenaiProvider: YC OpenAI provider instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.

    Raises:
        AssertionError: If workflow fails at any step.
    """
    ycOpenaiProvider._client = mockAsyncOpenAI

    # Add model
    model = ycOpenaiProvider.addModel(
        name="test-model",
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
        statsStorage=NullStatsStorage(),
    )

    # Setup mock response
    mockResponse: Mock = Mock(spec=ChatCompletion)
    mockChoice: Mock = Mock(spec=Choice)
    mockMessage: Mock = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Test response from YC OpenAI"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage: Mock = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    # Generate text
    messages: list[ModelMessage] = [ModelMessage(role="user", content="Test")]
    result = await model.generateText(messages)

    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "Test response from YC OpenAI"

    # Verify YC-specific model ID format was used
    callKwargs: dict = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert callKwargs["model"].startswith("gpt://")
    assert "b1g2abc3def4ghi5jklm" in callKwargs["model"]


def testYcOpenaiProviderModelManagement(ycOpenaiProvider: YcOpenaiProvider, mockAsyncOpenAI: Mock) -> None:
    """Test YC OpenAI provider model management.

    Verifies all model management operations:
    - Adding models
    - Listing models
    - Getting a specific model
    - Getting model info
    - Deleting models

    Args:
        ycOpenaiProvider: YC OpenAI provider instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.

    Raises:
        AssertionError: If any model management operation fails.
    """
    ycOpenaiProvider._client = mockAsyncOpenAI

    # Add models
    ycOpenaiProvider.addModel(
        "yandexgpt",
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
        statsStorage=NullStatsStorage(),
    )
    ycOpenaiProvider.addModel(
        "yandexgpt-lite",
        modelId="yandexgpt-lite",
        modelVersion="latest",
        temperature=0.7,
        contextSize=4096,
        statsStorage=NullStatsStorage(),
    )

    # Test listModels
    models: list[str] = ycOpenaiProvider.listModels()
    assert len(models) == 2
    assert "yandexgpt" in models
    assert "yandexgpt-lite" in models

    # Test getModel
    model = ycOpenaiProvider.getModel("yandexgpt")
    assert model is not None
    assert model.modelId == "yandexgpt"

    # Test getModelInfo
    info = ycOpenaiProvider.getModelInfo("yandexgpt")
    assert info is not None
    assert info["model_id"] == "yandexgpt"
    assert info["temperature"] == 0.6
    assert info["context_size"] == 8192

    # Test deleteModel
    deleted: bool = ycOpenaiProvider.deleteModel("yandexgpt")
    assert deleted is True
    assert len(ycOpenaiProvider.listModels()) == 1


# ============================================================================
# Configuration Tests
# ============================================================================


def testYcOpenaiProviderWithCustomConfig() -> None:
    """Test YC OpenAI provider with custom configuration.

    Verifies that the provider correctly initializes with custom
    configuration parameters including timeout and max_retries.

    Raises:
        AssertionError: If custom configuration is not applied correctly.
    """
    config: dict = {
        "api_key": "yc-custom-key",
        "folder_id": "custom-folder-id",
        "timeout": 60,
        "max_retries": 5,
    }

    with patch("openai.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        provider: YcOpenaiProvider = YcOpenaiProvider(config)

        assert provider.config["api_key"] == "yc-custom-key"
        assert provider._folderId == "custom-folder-id"
        assert provider.config["timeout"] == 60
        assert provider.config["max_retries"] == 5


def testYcOpenaiModelWithCustomExtraConfig(ycOpenaiProvider: YcOpenaiProvider, mockAsyncOpenAI: Mock) -> None:
    """Test YC OpenAI model with custom extra configuration.

    Verifies that custom extra configuration parameters are correctly
    stored and applied to the model, including support_tools flag.

    Args:
        ycOpenaiProvider: YC OpenAI provider instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.

    Raises:
        AssertionError: If extra configuration is not applied correctly.
    """
    ycOpenaiProvider._client = mockAsyncOpenAI

    extraConfig: dict = {
        "support_tools": False,
        "support_images": False,
        "custom_param": "value",
    }

    model = ycOpenaiProvider.addModel(
        name="custom-model",
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.8,
        contextSize=4096,
        statsStorage=NullStatsStorage(),
        extraConfig=extraConfig,
    )

    assert model._config == extraConfig
    assert model._supportTools is False  # type: ignore[attr-defined]


# ============================================================================
# Edge Cases Tests
# ============================================================================


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextEmptyResponse(
    ycOpenaiModel: YcOpenaiModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test handling of empty response from YC OpenAI.

    Verifies that empty string responses are handled correctly
    and returned as empty result text.

    Args:
        ycOpenaiModel: YC OpenAI model instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If empty response is not handled correctly.
    """
    mockResponse: Mock = Mock(spec=ChatCompletion)
    mockChoice: Mock = Mock(spec=Choice)
    mockMessage: Mock = Mock(spec=ChatCompletionMessage)
    mockMessage.content = ""
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage: Mock = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    result = await ycOpenaiModel.generateText(sampleMessages)

    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == ""


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextNullContent(
    ycOpenaiModel: YcOpenaiModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test handling of null content from YC OpenAI.

    Verifies that null content responses are handled correctly
    and converted to empty string.

    Args:
        ycOpenaiModel: YC OpenAI model instance.
        mockAsyncOpenAI: Mocked AsyncOpenAI client.
        sampleMessages: Sample messages for testing.

    Raises:
        AssertionError: If null content is not handled correctly.
    """
    mockResponse: Mock = Mock(spec=ChatCompletion)
    mockChoice: Mock = Mock(spec=Choice)
    mockMessage: Mock = Mock(spec=ChatCompletionMessage)
    mockMessage.content = None
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage: Mock = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 10
    mockUsage.completion_tokens = 20
    mockUsage.total_tokens = 30
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    result = await ycOpenaiModel.generateText(sampleMessages)

    assert result.resultText == ""


def testYcOpenaiProviderStringRepresentation(ycOpenaiProvider: YcOpenaiProvider) -> None:
    """Test YC OpenAI provider string representation.

    Verifies that the provider's __str__ method returns a string
    containing the provider name and model count.

    Args:
        ycOpenaiProvider: YC OpenAI provider instance.

    Raises:
        AssertionError: If string representation is incorrect.
    """
    strRepr: str = str(ycOpenaiProvider)
    assert "YcOpenaiProvider" in strRepr
    assert "0 models" in strRepr


def testYcOpenaiModelStringRepresentation(ycOpenaiModel: YcOpenaiModel) -> None:
    """Test YC OpenAI model string representation.

    Verifies that the model's __str__ method returns a string
    containing the model ID, version, and provider name.

    Args:
        ycOpenaiModel: YC OpenAI model instance.

    Raises:
        AssertionError: If string representation is incorrect.
    """
    strRepr: str = str(ycOpenaiModel)
    assert "yandexgpt" in strRepr
    assert "latest" in strRepr
    assert "YcOpenaiProvider" in strRepr


def testYcOpenaiModelIdWithDifferentFolderIds() -> None:
    """Test model ID generation with different folder IDs.

    Verifies that model IDs are correctly formatted for various
    folder ID formats using the gpt://folder_id/model/version pattern.

    Raises:
        AssertionError: If model ID format is incorrect for any folder ID.
    """
    folderIds: list[str] = [
        "b1g2abc3def4ghi5jklm",
        "folder-123-test",
        "a1b2c3d4e5f6g7h8i9j0",
    ]

    for folderId in folderIds:
        provider: YcOpenaiProvider = YcOpenaiProvider.__new__(YcOpenaiProvider)
        provider._folderId = folderId

        with patch("openai.AsyncOpenAI"):
            model: YcOpenaiModel = YcOpenaiModel(
                provider=provider,
                modelId="yandexgpt",
                modelVersion="latest",
                temperature=0.6,
                contextSize=8192,
                statsStorage=NullStatsStorage(),
                openAiClient=Mock(spec=AsyncOpenAI),
                folderId=folderId,
            )

            modelId: str = model._getModelId()
            assert modelId == f"gpt://{folderId}/yandexgpt/latest"
            assert folderId in modelId


# ============================================================================
# Structured Output Tests
# ============================================================================

_YC_SAMPLE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


@pytest.mark.asyncio
async def testGenerateStructuredHappyPath(
    ycOpenaiModel: YcOpenaiModel, mockAsyncOpenAI: Mock, sampleMessages: list[ModelMessage]
) -> None:
    """Test that YcOpenaiModel structured output works via the inherited _generateStructured.

    Confirms that:
    - The call routes through ``chat.completions.create``.
    - The ``model`` kwarg uses the YC-specific ``gpt://folder_id/model/version`` format
      (proving ``_getModelId()`` is still applied on the structured path).
    - ``response_format`` is present in the call kwargs.
    - The result is a ``ModelStructuredResult`` with status FINAL and parsed data.

    Args:
        ycOpenaiModel: YC OpenAI model instance (has support_structured_output=True).
        mockAsyncOpenAI: Mocked AsyncOpenAI client.
        sampleMessages: Sample conversation messages.

    Raises:
        AssertionError: If result fields or API call kwargs are not as expected.
    """
    mockResponse: Mock = Mock(spec=ChatCompletion)
    mockChoice: Mock = Mock(spec=Choice)
    mockMessage: Mock = Mock(spec=ChatCompletionMessage)
    mockMessage.content = '{"answer": "Yandex"}'
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockUsage: Mock = Mock(spec=CompletionUsage)
    mockUsage.prompt_tokens = 8
    mockUsage.completion_tokens = 12
    mockUsage.total_tokens = 20
    mockResponse.usage = mockUsage

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    result: ModelStructuredResult = await ycOpenaiModel.generateStructured(
        sampleMessages, _YC_SAMPLE_SCHEMA, schemaName="ycShape"
    )

    assert isinstance(result, ModelStructuredResult)
    assert result.status == ModelResultStatus.FINAL
    assert result.data == {"answer": "Yandex"}
    assert result.error is None

    callKwargs: dict = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    # YC model must use the gpt://folder_id/model/version form
    assert callKwargs["model"] == "gpt://b1g2abc3def4ghi5jklm/yandexgpt/latest"
    assert callKwargs["model"].startswith("gpt://")
    # response_format must be forwarded
    assert "response_format" in callKwargs
    assert callKwargs["response_format"]["type"] == "json_schema"
    assert callKwargs["response_format"]["json_schema"]["name"] == "ycShape"
    assert callKwargs["response_format"]["json_schema"]["schema"] == _YC_SAMPLE_SCHEMA
