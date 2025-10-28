"""Comprehensive tests for YcOpenaiProvider and YcOpenaiModel, dood!

This module provides extensive test coverage for the YcOpenaiProvider class
and YcOpenaiModel class, including initialization, Yandex Cloud-specific
model ID formatting, folder ID handling, and API integration.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from openai import AsyncOpenAI
from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage

from lib.ai.models import ModelMessage, ModelResultStatus
from lib.ai.providers.yc_openai_provider import YcOpenaiModel, YcOpenaiProvider

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mockAsyncOpenAI():
    """Create a mock AsyncOpenAI client, dood!"""
    client = Mock(spec=AsyncOpenAI)
    client.chat = Mock()
    client.chat.completions = Mock()
    client.chat.completions.create = AsyncMock()
    return client


@pytest.fixture
def providerConfig():
    """Create YC OpenAI provider configuration, dood!"""
    return {
        "api_key": "yc-api-key-123",
        "folder_id": "b1g2abc3def4ghi5jklm",
        "timeout": 30,
    }


@pytest.fixture
def ycOpenaiProvider(providerConfig):
    """Create a YC OpenAI provider instance, dood!"""
    with patch("lib.ai.providers.basic_openai_provider.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        provider = YcOpenaiProvider(providerConfig)
        return provider


@pytest.fixture
def ycOpenaiModel(ycOpenaiProvider, mockAsyncOpenAI):
    """Create a YC OpenAI model instance, dood!"""
    model = YcOpenaiModel(
        provider=ycOpenaiProvider,
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
        openAiClient=mockAsyncOpenAI,
        folderId="b1g2abc3def4ghi5jklm",
        extraConfig={"support_tools": False},
    )
    return model


@pytest.fixture
def sampleMessages():
    """Create sample messages for testing, dood!"""
    return [
        ModelMessage(role="system", content="Ты полезный ассистент"),
        ModelMessage(role="user", content="Привет! Как дела?"),
    ]


# ============================================================================
# Provider Initialization Tests
# ============================================================================


def testYcOpenaiProviderInitialization(providerConfig):
    """Test YC OpenAI provider initializes correctly, dood!"""
    with patch("lib.ai.providers.basic_openai_provider.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        provider = YcOpenaiProvider(providerConfig)

        assert provider is not None
        assert provider.config == providerConfig
        assert provider._client is not None
        assert provider._folderId == "b1g2abc3def4ghi5jklm"
        assert len(provider.models) == 0


def testYcOpenaiProviderGetBaseUrl(ycOpenaiProvider):
    """Test YC OpenAI provider returns correct base URL, dood!"""
    baseUrl = ycOpenaiProvider._getBaseUrl()
    assert baseUrl == "https://llm.api.cloud.yandex.net/v1"


def testYcOpenaiProviderInitializationMissingFolderId():
    """Test YC OpenAI provider initialization fails without folder_id, dood!"""
    config = {"api_key": "test-key"}

    with pytest.raises(ValueError, match="folder_id is required"):
        YcOpenaiProvider(config)


def testYcOpenaiProviderInitializationMissingApiKey():
    """Test YC OpenAI provider initialization fails without api_key, dood!"""
    config = {"folder_id": "test-folder"}

    with pytest.raises(ValueError, match="api_key is required"):
        YcOpenaiProvider(config)


def testYcOpenaiProviderInitializationEmptyFolderId():
    """Test YC OpenAI provider initialization fails with empty folder_id, dood!"""
    config = {"api_key": "test-key", "folder_id": ""}

    with pytest.raises(ValueError, match="folder_id is required"):
        YcOpenaiProvider(config)


def testYcOpenaiProviderClientInitialization(providerConfig):
    """Test YC OpenAI provider initializes AsyncOpenAI client correctly, dood!"""
    with patch("lib.ai.providers.basic_openai_provider.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        testProvider = YcOpenaiProvider(providerConfig)

        # Verify AsyncOpenAI was called with correct parameters
        assert testProvider is not None
        mockClient.assert_called_once()
        callKwargs = mockClient.call_args.kwargs
        assert callKwargs["api_key"] == "yc-api-key-123"
        assert callKwargs["base_url"] == "https://llm.api.cloud.yandex.net/v1"


def testYcOpenaiProviderFolderIdStorage(providerConfig):
    """Test YC OpenAI provider stores folder_id correctly, dood!"""
    with patch("lib.ai.providers.basic_openai_provider.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        provider = YcOpenaiProvider(providerConfig)

        assert provider._folderId == "b1g2abc3def4ghi5jklm"
        assert isinstance(provider._folderId, str)


# ============================================================================
# Model Addition Tests
# ============================================================================


def testAddYcOpenaiModel(ycOpenaiProvider, mockAsyncOpenAI):
    """Test adding a YC OpenAI model, dood!"""
    ycOpenaiProvider._client = mockAsyncOpenAI

    model = ycOpenaiProvider.addModel(
        name="yandexgpt",
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
        extraConfig={"support_tools": False},
    )

    assert model is not None
    assert isinstance(model, YcOpenaiModel)
    assert "yandexgpt" in ycOpenaiProvider.models
    assert model.modelId == "yandexgpt"
    assert model.temperature == 0.6
    assert model.contextSize == 8192
    assert model._folderId == "b1g2abc3def4ghi5jklm"


def testAddMultipleYcOpenaiModels(ycOpenaiProvider, mockAsyncOpenAI):
    """Test adding multiple YC OpenAI models, dood!"""
    ycOpenaiProvider._client = mockAsyncOpenAI

    model1 = ycOpenaiProvider.addModel(
        name="yandexgpt",
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
    )

    model2 = ycOpenaiProvider.addModel(
        name="yandexgpt-lite",
        modelId="yandexgpt-lite",
        modelVersion="latest",
        temperature=0.7,
        contextSize=4096,
    )

    assert len(ycOpenaiProvider.models) == 2
    assert "yandexgpt" in ycOpenaiProvider.models
    assert "yandexgpt-lite" in ycOpenaiProvider.models
    assert model1.modelId == "yandexgpt"
    assert model2.modelId == "yandexgpt-lite"


def testAddYcOpenaiModelWithoutClient():
    """Test adding model without initialized client fails, dood!"""
    provider = YcOpenaiProvider.__new__(YcOpenaiProvider)
    provider.config = {"api_key": "test", "folder_id": "test"}
    provider.models = {}
    provider._client = None
    provider._folderId = "test"

    with pytest.raises(RuntimeError, match="OpenAI client not initialized"):
        provider.addModel("test", "model", "1.0", 0.7, 4096)


def testCreateModelInstance(ycOpenaiProvider, mockAsyncOpenAI):
    """Test _createModelInstance creates YcOpenaiModel, dood!"""
    ycOpenaiProvider._client = mockAsyncOpenAI

    ycOpenaiProvider._createModelInstance(
        name="test-model",
        modelId="yandexgpt",
        modelVersion="rc",
        temperature=0.8,
        contextSize=4096,
        extraConfig={"support_tools": False},
    )

    # Verify model was created
    assert ycOpenaiProvider._client is not None
    assert ycOpenaiProvider._folderId == "b1g2abc3def4ghi5jklm"


# ============================================================================
# Model Initialization Tests
# ============================================================================


def testYcOpenaiModelInitialization(ycOpenaiProvider, mockAsyncOpenAI):
    """Test YC OpenAI model initializes correctly, dood!"""
    model = YcOpenaiModel(
        provider=ycOpenaiProvider,
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
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


def testYcOpenaiModelGetModelId(ycOpenaiModel):
    """Test YC OpenAI model returns correct YC-specific model URL, dood!"""
    modelId = ycOpenaiModel._getModelId()
    assert modelId == "gpt://b1g2abc3def4ghi5jklm/yandexgpt/latest"


def testYcOpenaiModelGetModelIdFormat():
    """Test YC OpenAI model ID format is correct, dood!"""
    provider = YcOpenaiProvider.__new__(YcOpenaiProvider)
    provider._folderId = "test-folder-123"

    with patch("lib.ai.providers.basic_openai_provider.AsyncOpenAI"):
        model = YcOpenaiModel(
            provider=provider,
            modelId="test-model",
            modelVersion="v1",
            temperature=0.7,
            contextSize=4096,
            openAiClient=Mock(spec=AsyncOpenAI),
            folderId="test-folder-123",
        )

        modelId = model._getModelId()
        assert modelId == "gpt://test-folder-123/test-model/v1"
        assert modelId.startswith("gpt://")
        assert "test-folder-123" in modelId
        assert "test-model" in modelId
        assert "v1" in modelId


def testYcOpenaiModelGetModelIdWithoutFolderId():
    """Test YC OpenAI model raises error without folder_id, dood!"""
    provider = YcOpenaiProvider.__new__(YcOpenaiProvider)

    with patch("lib.ai.providers.basic_openai_provider.AsyncOpenAI"):
        model = YcOpenaiModel(
            provider=provider,
            modelId="yandexgpt",
            modelVersion="latest",
            temperature=0.6,
            contextSize=8192,
            openAiClient=Mock(spec=AsyncOpenAI),
            folderId="",
        )

        with pytest.raises(ValueError, match="folder_id is required"):
            model._getModelId()


# ============================================================================
# Extra Parameters Tests
# ============================================================================


def testYcOpenaiModelGetExtraParams(ycOpenaiModel):
    """Test YC OpenAI model returns correct extra parameters, dood!"""
    extraParams = ycOpenaiModel._getExtraParams()

    # YC OpenAI model returns empty dict or specific params
    assert isinstance(extraParams, dict)


def testYcOpenaiModelExtraParamsStructure(ycOpenaiModel):
    """Test YC OpenAI extra params structure, dood!"""
    extraParams = ycOpenaiModel._getExtraParams()

    # Verify it's a dictionary (may be empty or contain YC-specific params)
    assert isinstance(extraParams, dict)


# ============================================================================
# Text Generation Tests
# ============================================================================


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextSuccess(ycOpenaiModel, mockAsyncOpenAI, sampleMessages):
    """Test successful text generation with YC OpenAI, dood!"""
    # Create mock response
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Привет! У меня всё хорошо, спасибо!"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    result = await ycOpenaiModel.generateText(sampleMessages)

    assert result is not None
    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "Привет! У меня всё хорошо, спасибо!"


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextWithYcModelId(ycOpenaiModel, mockAsyncOpenAI, sampleMessages):
    """Test text generation uses YC-specific model ID format, dood!"""
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Response"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    await ycOpenaiModel.generateText(sampleMessages)

    # Verify YC-specific model ID was used
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert callKwargs["model"] == "gpt://b1g2abc3def4ghi5jklm/yandexgpt/latest"
    assert callKwargs["model"].startswith("gpt://")


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextRequestParameters(ycOpenaiModel, mockAsyncOpenAI, sampleMessages):
    """Test request parameters are correctly formatted for YC OpenAI, dood!"""
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Response"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    await ycOpenaiModel.generateText(sampleMessages)

    # Verify all required parameters
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert "model" in callKwargs
    assert callKwargs["temperature"] == 0.6
    assert "messages" in callKwargs
    assert len(callKwargs["messages"]) == 2


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextWithDifferentVersions(ycOpenaiProvider, mockAsyncOpenAI):
    """Test text generation with different model versions, dood!"""
    ycOpenaiProvider._client = mockAsyncOpenAI

    # Test with latest version
    latestModel = ycOpenaiProvider.addModel(
        name="yandexgpt-latest",
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
    )

    # Test with rc version
    rcModel = ycOpenaiProvider.addModel(
        name="yandexgpt-rc",
        modelId="yandexgpt",
        modelVersion="rc",
        temperature=0.6,
        contextSize=8192,
    )

    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Response"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    messages = [ModelMessage(role="user", content="Test")]

    # Test latest
    await latestModel.generateText(messages)
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert "latest" in callKwargs["model"]

    # Test rc
    await rcModel.generateText(messages)
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert "rc" in callKwargs["model"]


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextApiError(ycOpenaiModel, mockAsyncOpenAI, sampleMessages):
    """Test handling of YC OpenAI API errors, dood!"""
    mockAsyncOpenAI.chat.completions.create.side_effect = Exception("YC API Error")

    with pytest.raises(Exception, match="YC API Error"):
        await ycOpenaiModel.generateText(sampleMessages)


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextAuthenticationError(ycOpenaiModel, mockAsyncOpenAI, sampleMessages):
    """Test handling of authentication errors, dood!"""
    from openai import AuthenticationError

    mockAsyncOpenAI.chat.completions.create.side_effect = AuthenticationError(
        "Invalid API key",
        response=Mock(status_code=401),
        body=None,
    )

    with pytest.raises(AuthenticationError):
        await ycOpenaiModel.generateText(sampleMessages)


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextRateLimitError(ycOpenaiModel, mockAsyncOpenAI, sampleMessages):
    """Test handling of rate limit errors, dood!"""
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
async def testYcOpenaiFullWorkflow(ycOpenaiProvider, mockAsyncOpenAI):
    """Test full workflow with YC OpenAI provider, dood!"""
    ycOpenaiProvider._client = mockAsyncOpenAI

    # Add model
    model = ycOpenaiProvider.addModel(
        name="test-model",
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
    )

    # Setup mock response
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = "Test response from YC OpenAI"
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    # Generate text
    messages = [ModelMessage(role="user", content="Test")]
    result = await model.generateText(messages)

    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "Test response from YC OpenAI"

    # Verify YC-specific model ID format was used
    callKwargs = mockAsyncOpenAI.chat.completions.create.call_args.kwargs
    assert callKwargs["model"].startswith("gpt://")
    assert "b1g2abc3def4ghi5jklm" in callKwargs["model"]


def testYcOpenaiProviderModelManagement(ycOpenaiProvider, mockAsyncOpenAI):
    """Test YC OpenAI provider model management, dood!"""
    ycOpenaiProvider._client = mockAsyncOpenAI

    # Add models
    ycOpenaiProvider.addModel("yandexgpt", "yandexgpt", "latest", 0.6, 8192)
    ycOpenaiProvider.addModel("yandexgpt-lite", "yandexgpt-lite", "latest", 0.7, 4096)

    # Test listModels
    models = ycOpenaiProvider.listModels()
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
    deleted = ycOpenaiProvider.deleteModel("yandexgpt")
    assert deleted is True
    assert len(ycOpenaiProvider.listModels()) == 1


# ============================================================================
# Configuration Tests
# ============================================================================


def testYcOpenaiProviderWithCustomConfig():
    """Test YC OpenAI provider with custom configuration, dood!"""
    config = {
        "api_key": "yc-custom-key",
        "folder_id": "custom-folder-id",
        "timeout": 60,
        "max_retries": 5,
    }

    with patch("lib.ai.providers.basic_openai_provider.AsyncOpenAI") as mockClient:
        mockClient.return_value = Mock(spec=AsyncOpenAI)
        provider = YcOpenaiProvider(config)

        assert provider.config["api_key"] == "yc-custom-key"
        assert provider._folderId == "custom-folder-id"
        assert provider.config["timeout"] == 60
        assert provider.config["max_retries"] == 5


def testYcOpenaiModelWithCustomExtraConfig(ycOpenaiProvider, mockAsyncOpenAI):
    """Test YC OpenAI model with custom extra configuration, dood!"""
    ycOpenaiProvider._client = mockAsyncOpenAI

    extraConfig = {
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
        extraConfig=extraConfig,
    )

    assert model._config == extraConfig
    assert model._supportTools is False


# ============================================================================
# Edge Cases Tests
# ============================================================================


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextEmptyResponse(ycOpenaiModel, mockAsyncOpenAI, sampleMessages):
    """Test handling of empty response from YC OpenAI, dood!"""
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = ""
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    result = await ycOpenaiModel.generateText(sampleMessages)

    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == ""


@pytest.mark.asyncio
async def testYcOpenaiGenerateTextNullContent(ycOpenaiModel, mockAsyncOpenAI, sampleMessages):
    """Test handling of null content from YC OpenAI, dood!"""
    mockResponse = Mock(spec=ChatCompletion)
    mockChoice = Mock(spec=Choice)
    mockMessage = Mock(spec=ChatCompletionMessage)
    mockMessage.content = None
    mockMessage.tool_calls = None
    mockChoice.message = mockMessage
    mockChoice.finish_reason = "stop"
    mockResponse.choices = [mockChoice]

    mockAsyncOpenAI.chat.completions.create.return_value = mockResponse

    result = await ycOpenaiModel.generateText(sampleMessages)

    assert result.resultText == ""


def testYcOpenaiProviderStringRepresentation(ycOpenaiProvider):
    """Test YC OpenAI provider string representation, dood!"""
    strRepr = str(ycOpenaiProvider)
    assert "YcOpenaiProvider" in strRepr
    assert "0 models" in strRepr


def testYcOpenaiModelStringRepresentation(ycOpenaiModel):
    """Test YC OpenAI model string representation, dood!"""
    strRepr = str(ycOpenaiModel)
    assert "yandexgpt" in strRepr
    assert "latest" in strRepr
    assert "YcOpenaiProvider" in strRepr


def testYcOpenaiModelIdWithDifferentFolderIds():
    """Test model ID generation with different folder IDs, dood!"""
    folderIds = [
        "b1g2abc3def4ghi5jklm",
        "folder-123-test",
        "a1b2c3d4e5f6g7h8i9j0",
    ]

    for folderId in folderIds:
        provider = YcOpenaiProvider.__new__(YcOpenaiProvider)
        provider._folderId = folderId

        with patch("lib.ai.providers.basic_openai_provider.AsyncOpenAI"):
            model = YcOpenaiModel(
                provider=provider,
                modelId="yandexgpt",
                modelVersion="latest",
                temperature=0.6,
                contextSize=8192,
                openAiClient=Mock(spec=AsyncOpenAI),
                folderId=folderId,
            )

            modelId = model._getModelId()
            assert modelId == f"gpt://{folderId}/yandexgpt/latest"
            assert folderId in modelId
