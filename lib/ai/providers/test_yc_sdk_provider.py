"""Comprehensive tests for YcSdkProvider and YcSdkModel, dood!

This module provides extensive test coverage for the YcSdkProvider class
and YcSdkModel class, including initialization, Yandex Cloud SDK integration,
text generation, image generation, error handling, and configuration.
"""

from typing import Any
from unittest.mock import Mock, patch

import pytest

from lib.ai.models import ModelMessage, ModelResultStatus
from lib.ai.providers.yc_sdk_provider import YcSdkModel, YcSdkProvider

# ============================================================================
# Mock YC SDK Classes
# ============================================================================


class MockYcSdkResult:
    """Mock YC SDK result, dood!"""

    def __init__(self, text: str = "", status: int = 3, imageBytes: bytes = None):  # type: ignore[assignment]
        self.status = status
        self.alternatives = [Mock(text=text)]
        self.image_bytes = imageBytes


class MockYcSdkOperation:
    """Mock YC SDK operation, dood!"""

    def __init__(self, result: MockYcSdkResult):
        self._result = result

    def wait(self):
        return self._result


class MockYcSdkModel:
    """Mock YC SDK model, dood!"""

    def __init__(self):
        self.run = Mock(return_value=MockYcSdkResult())
        self.run_deferred = Mock(return_value=MockYcSdkOperation(MockYcSdkResult()))


class MockYcSdkCompletions:
    """Mock YC SDK completions, dood!"""

    def __init__(self, modelId: str, model_version: str):
        self.modelId = modelId
        self.modelVersion = model_version
        self._model = MockYcSdkModel()

    def configure(self, **kwargs):
        return self._model


class MockYcSdkImageGeneration:
    """Mock YC SDK image generation, dood!"""

    def __init__(self, modelId: str, model_version: str):
        self.modelId = modelId
        self.modelVersion = model_version
        self._model = MockYcSdkModel()

    def configure(self, **kwargs):
        return self._model


class MockYcSdkModels:
    """Mock YC SDK models, dood!"""

    def completions(self, modelId: str, model_version: str):
        return MockYcSdkCompletions(modelId, model_version)

    def image_generation(self, modelId: str, model_version: str):
        return MockYcSdkImageGeneration(modelId, model_version)


class MockYCloudML:
    """Mock YCloudML SDK, dood!"""

    def __init__(self, folder_id: str, auth: Any = None, yc_profile: str = None):  # type: ignore[assignment]
        self.folder_id = folder_id
        self.auth = auth
        self.yc_profile = yc_profile
        self.models = MockYcSdkModels()


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mockYCloudML():
    """Create a mock YCloudML SDK, dood!"""
    return MockYCloudML(folder_id="test-folder-123")


@pytest.fixture
def providerConfig():
    """Create YC SDK provider configuration, dood!"""
    return {
        "folder_id": "b1g2abc3def4ghi5jklm",
        "yc_profile": "default",
    }


@pytest.fixture
def ycSdkProvider(providerConfig):
    """Create a YC SDK provider instance, dood!"""
    with patch("lib.ai.providers.yc_sdk_provider.YCloudML", return_value=MockYCloudML("b1g2abc3def4ghi5jklm")):
        with patch("lib.ai.providers.yc_sdk_provider.YandexCloudCLIAuth"):
            provider = YcSdkProvider(providerConfig)
            return provider


@pytest.fixture
def ycSdkTextModel(ycSdkProvider, mockYCloudML):
    """Create a YC SDK text model instance, dood!"""
    model = YcSdkModel(
        provider=ycSdkProvider,
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
        ycSDK=mockYCloudML,
        extraConfig={"support_text": True, "support_images": False},
    )
    return model


@pytest.fixture
def ycSdkImageModel(ycSdkProvider, mockYCloudML):
    """Create a YC SDK image model instance, dood!"""
    model = YcSdkModel(
        provider=ycSdkProvider,
        modelId="yandex-art",
        modelVersion="latest",
        temperature=0.0,
        contextSize=1024,
        ycSDK=mockYCloudML,
        extraConfig={"support_text": False, "support_images": True, "width_ratio": 1, "height_ratio": 1},
    )
    return model


@pytest.fixture
def sampleMessages():
    """Create sample messages for testing, dood!"""
    return [
        ModelMessage(role="system", content="Ты полезный ассистент"),
        ModelMessage(role="user", content="Привет!"),
    ]


# ============================================================================
# Provider Initialization Tests
# ============================================================================


def testYcSdkProviderInitialization(providerConfig):
    """Test YC SDK provider initializes correctly, dood!"""
    with patch("lib.ai.providers.yc_sdk_provider.YCloudML", return_value=MockYCloudML("b1g2abc3def4ghi5jklm")):
        with patch("lib.ai.providers.yc_sdk_provider.YandexCloudCLIAuth"):
            provider = YcSdkProvider(providerConfig)

            assert provider is not None
            assert provider.config == providerConfig
            assert provider._ycMlSDK is not None
            assert len(provider.models) == 0


def testYcSdkProviderInitializationMissingFolderId():
    """Test YC SDK provider initialization fails without folder_id, dood!"""
    config = {"yc_profile": "default"}

    with pytest.raises(ValueError, match="folder_id is required"):
        YcSdkProvider(config)


def testYcSdkProviderInitializationWithProfile(providerConfig):
    """Test YC SDK provider initialization with yc_profile, dood!"""
    with patch("lib.ai.providers.yc_sdk_provider.YCloudML") as mockYCloudML:
        with patch("lib.ai.providers.yc_sdk_provider.YandexCloudCLIAuth"):
            mockYCloudML.return_value = MockYCloudML("b1g2abc3def4ghi5jklm")
            YcSdkProvider(providerConfig)

            # Verify YCloudML was called with correct parameters
            mockYCloudML.assert_called_once()
            callKwargs = mockYCloudML.call_args.kwargs
            assert callKwargs["folder_id"] == "b1g2abc3def4ghi5jklm"
            assert callKwargs["yc_profile"] == "default"


def testYcSdkProviderInitializationWithoutProfile():
    """Test YC SDK provider initialization without yc_profile, dood!"""
    config = {"folder_id": "test-folder"}

    with patch("lib.ai.providers.yc_sdk_provider.YCloudML") as mockYCloudML:
        with patch("lib.ai.providers.yc_sdk_provider.YandexCloudCLIAuth"):
            mockYCloudML.return_value = MockYCloudML("test-folder")
            YcSdkProvider(config)

            # Verify yc_profile defaults to None
            callKwargs = mockYCloudML.call_args.kwargs
            assert callKwargs["yc_profile"] is None


# ============================================================================
# Model Addition Tests
# ============================================================================


def testAddYcSdkTextModel(ycSdkProvider):
    """Test adding a YC SDK text model, dood!"""
    model = ycSdkProvider.addModel(
        name="yandexgpt",
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
        extraConfig={"support_text": True, "support_images": False},
    )

    assert model is not None
    assert isinstance(model, YcSdkModel)
    assert "yandexgpt" in ycSdkProvider.models
    assert model.modelId == "yandexgpt"
    assert model.temperature == 0.6
    assert model.contextSize == 8192
    assert model.supportText is True
    assert model.supportImages is False


def testAddYcSdkImageModel(ycSdkProvider):
    """Test adding a YC SDK image model, dood!"""
    model = ycSdkProvider.addModel(
        name="yandex-art",
        modelId="yandex-art",
        modelVersion="latest",
        temperature=0.0,
        contextSize=1024,
        extraConfig={"support_text": False, "support_images": True},
    )

    assert model is not None
    assert isinstance(model, YcSdkModel)
    assert model.supportText is False
    assert model.supportImages is True


def testAddMultipleYcSdkModels(ycSdkProvider):
    """Test adding multiple YC SDK models, dood!"""
    ycSdkProvider.addModel(
        name="yandexgpt",
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
        extraConfig={"support_text": True, "support_images": False},
    )

    ycSdkProvider.addModel(
        name="yandex-art",
        modelId="yandex-art",
        modelVersion="latest",
        temperature=0.0,
        contextSize=1024,
        extraConfig={"support_text": False, "support_images": True},
    )

    assert len(ycSdkProvider.models) == 2
    assert "yandexgpt" in ycSdkProvider.models
    assert "yandex-art" in ycSdkProvider.models


# ============================================================================
# Model Initialization Tests
# ============================================================================


def testYcSdkTextModelInitialization(ycSdkProvider, mockYCloudML):
    """Test YC SDK text model initializes correctly, dood!"""
    model = YcSdkModel(
        provider=ycSdkProvider,
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
        ycSDK=mockYCloudML,
        extraConfig={"support_text": True, "support_images": False},
    )

    assert model.provider == ycSdkProvider
    assert model.modelId == "yandexgpt"
    assert model.modelVersion == "latest"
    assert model.temperature == 0.6
    assert model.contextSize == 8192
    assert model.ycSDK == mockYCloudML
    assert model.supportText is True
    assert model.supportImages is False
    assert model._ycModel is not None


def testYcSdkImageModelInitialization(ycSdkProvider, mockYCloudML):
    """Test YC SDK image model initializes correctly, dood!"""
    model = YcSdkModel(
        provider=ycSdkProvider,
        modelId="yandex-art",
        modelVersion="latest",
        temperature=0.0,
        contextSize=1024,
        ycSDK=mockYCloudML,
        extraConfig={"support_text": False, "support_images": True},
    )

    assert model.supportText is False
    assert model.supportImages is True
    assert model._ycModel is not None


def testYcSdkModelInitializationBothSupportsError(ycSdkProvider, mockYCloudML):
    """Test model initialization fails with both text and images support, dood!"""
    with pytest.raises(ValueError, match="Only one of support_text and support_images"):
        YcSdkModel(
            provider=ycSdkProvider,
            modelId="invalid",
            modelVersion="latest",
            temperature=0.6,
            contextSize=4096,
            ycSDK=mockYCloudML,
            extraConfig={"support_text": True, "support_images": True},
        )


def testYcSdkModelInitializationNeitherSupportsError(ycSdkProvider, mockYCloudML):
    """Test model initialization fails without any support, dood!"""
    with pytest.raises(ValueError, match="Either support_text or support_images must be True"):
        YcSdkModel(
            provider=ycSdkProvider,
            modelId="invalid",
            modelVersion="latest",
            temperature=0.6,
            contextSize=4096,
            ycSDK=mockYCloudML,
            extraConfig={"support_text": False, "support_images": False},
        )


def testYcSdkImageModelWithExtraConfig(ycSdkProvider, mockYCloudML):
    """Test YC SDK image model with extra configuration, dood!"""
    extraConfig = {
        "support_text": False,
        "support_images": True,
        "width_ratio": 2,
        "height_ratio": 1,
        "seed": 12345,
    }

    model = YcSdkModel(
        provider=ycSdkProvider,
        modelId="yandex-art",
        modelVersion="latest",
        temperature=0.0,
        contextSize=1024,
        ycSDK=mockYCloudML,
        extraConfig=extraConfig,
    )

    assert model._config["width_ratio"] == 2
    assert model._config["height_ratio"] == 1
    assert model._config["seed"] == 12345


# ============================================================================
# Text Generation Tests
# ============================================================================


@pytest.mark.asyncio
async def testYcSdkGenerateTextSuccess(ycSdkTextModel, sampleMessages):
    """Test successful text generation with YC SDK, dood!"""
    # Mock the model's run method
    mockResult = MockYcSdkResult(text="Привет! Как дела?", status=3)
    ycSdkTextModel._ycModel.run = Mock(return_value=mockResult)

    result = await ycSdkTextModel.generateText(sampleMessages)

    assert result is not None
    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "Привет! Как дела?"


@pytest.mark.asyncio
async def testYcSdkGenerateTextWithoutModel(ycSdkTextModel, sampleMessages):
    """Test text generation fails without initialized model, dood!"""
    ycSdkTextModel._ycModel = None

    with pytest.raises(RuntimeError, match="Model not initialized"):
        await ycSdkTextModel.generateText(sampleMessages)


@pytest.mark.asyncio
async def testYcSdkGenerateTextNotSupported(ycSdkImageModel, sampleMessages):
    """Test text generation fails when not supported, dood!"""
    with pytest.raises(NotImplementedError, match="Text generation isn't supported"):
        await ycSdkImageModel.generateText(sampleMessages)


@pytest.mark.asyncio
async def testYcSdkGenerateTextToolsNotSupported(ycSdkTextModel, sampleMessages):
    """Test tools are not supported by YC SDK models, dood!"""
    from lib.ai.models import LLMToolFunction

    tools = [LLMToolFunction(name="test", description="test", parameters=[])]

    with pytest.raises(NotImplementedError, match="Tools not supported"):
        await ycSdkTextModel.generateText(sampleMessages, tools)


@pytest.mark.asyncio
async def testYcSdkGenerateTextMessageConversion(ycSdkTextModel, sampleMessages):
    """Test messages are converted to YC SDK format, dood!"""
    mockResult = MockYcSdkResult(text="Response", status=3)
    ycSdkTextModel._ycModel.run = Mock(return_value=mockResult)

    await ycSdkTextModel.generateText(sampleMessages)

    # Verify run was called with converted messages
    ycSdkTextModel._ycModel.run.assert_called_once()
    callArgs = ycSdkTextModel._ycModel.run.call_args[0][0]

    # Messages should be converted to dict format
    assert isinstance(callArgs, list)
    assert len(callArgs) == 2


# ============================================================================
# Image Generation Tests
# ============================================================================


@pytest.mark.asyncio
async def testYcSdkGenerateImageSuccess(ycSdkImageModel, sampleMessages):
    """Test successful image generation with YC SDK, dood!"""
    # Mock the model's run_deferred method
    imageData = b"fake image data"
    mockResult = MockYcSdkResult(imageBytes=imageData)
    mockOperation = MockYcSdkOperation(mockResult)
    ycSdkImageModel._ycModel.run_deferred = Mock(return_value=mockOperation)

    result = await ycSdkImageModel.generateImage(sampleMessages)

    assert result is not None
    assert result.status == ModelResultStatus.FINAL
    assert result.mediaMimeType == "image/jpeg"
    assert result.mediaData == imageData


@pytest.mark.asyncio
async def testYcSdkGenerateImageWithoutModel(ycSdkImageModel, sampleMessages):
    """Test image generation fails without initialized model, dood!"""
    ycSdkImageModel._ycModel = None

    with pytest.raises(RuntimeError, match="Model not initialized"):
        await ycSdkImageModel.generateImage(sampleMessages)


@pytest.mark.asyncio
async def testYcSdkGenerateImageNotSupported(ycSdkTextModel, sampleMessages):
    """Test image generation fails when not supported, dood!"""
    with pytest.raises(NotImplementedError, match="Image generation isn't supported"):
        await ycSdkTextModel.generateImage(sampleMessages)


@pytest.mark.asyncio
async def testYcSdkGenerateImageContentFilter(ycSdkImageModel, sampleMessages):
    """Test image generation with content filter error, dood!"""
    # Mock error with content filter message
    mockError = Exception("Error")
    mockError.details = Mock(  # type: ignore[attr-defined]
        return_value="it is not possible to generate an image from this request because it may violate the terms of use"
    )

    ycSdkImageModel._ycModel.run_deferred = Mock(side_effect=mockError)

    result = await ycSdkImageModel.generateImage(sampleMessages)

    assert result.status == ModelResultStatus.ERROR
    assert result.error is not None


@pytest.mark.asyncio
async def testYcSdkGenerateImageGenericError(ycSdkImageModel, sampleMessages):
    """Test image generation with generic error, dood!"""
    ycSdkImageModel._ycModel.run_deferred = Mock(side_effect=Exception("Generic error"))

    result = await ycSdkImageModel.generateImage(sampleMessages)

    assert result.status == ModelResultStatus.ERROR
    assert result.error is not None


@pytest.mark.asyncio
async def testYcSdkGenerateImageNoImageBytes(ycSdkImageModel, sampleMessages):
    """Test image generation with no image bytes in result, dood!"""
    mockResult = MockYcSdkResult(imageBytes=None)  # type: ignore[arg-type]
    mockOperation = MockYcSdkOperation(mockResult)
    ycSdkImageModel._ycModel.run_deferred = Mock(return_value=mockOperation)

    result = await ycSdkImageModel.generateImage(sampleMessages)

    assert result.status == ModelResultStatus.UNKNOWN


# ============================================================================
# Status Conversion Tests
# ============================================================================


def testStatusToModelRunResultStatus(ycSdkTextModel):
    """Test status conversion from YC SDK to ModelResultStatus, dood!"""
    # Test various status codes
    assert ycSdkTextModel._statusToModelRunResultStatus(0) == ModelResultStatus.UNSPECIFIED
    assert ycSdkTextModel._statusToModelRunResultStatus(1) == ModelResultStatus.PARTIAL
    assert ycSdkTextModel._statusToModelRunResultStatus(2) == ModelResultStatus.TRUNCATED_FINAL
    assert ycSdkTextModel._statusToModelRunResultStatus(3) == ModelResultStatus.FINAL
    assert ycSdkTextModel._statusToModelRunResultStatus(4) == ModelResultStatus.CONTENT_FILTER
    assert ycSdkTextModel._statusToModelRunResultStatus(5) == ModelResultStatus.TOOL_CALLS


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def testYcSdkGenerateTextApiError(ycSdkTextModel, sampleMessages):
    """Test handling of YC SDK API errors, dood!"""
    ycSdkTextModel._ycModel.run = Mock(side_effect=Exception("YC SDK Error"))

    with pytest.raises(Exception, match="YC SDK Error"):
        await ycSdkTextModel.generateText(sampleMessages)


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def testYcSdkFullTextWorkflow(ycSdkProvider):
    """Test full workflow with YC SDK text model, dood!"""
    # Add model
    model = ycSdkProvider.addModel(
        name="test-model",
        modelId="yandexgpt",
        modelVersion="latest",
        temperature=0.6,
        contextSize=8192,
        extraConfig={"support_text": True},
    )

    # Mock response
    mockResult = MockYcSdkResult(text="Test response from YC SDK", status=3)
    model._ycModel.run = Mock(return_value=mockResult)

    # Generate text
    messages = [ModelMessage(role="user", content="Test")]
    result = await model.generateText(messages)

    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == "Test response from YC SDK"


@pytest.mark.asyncio
async def testYcSdkFullImageWorkflow(ycSdkProvider):
    """Test full workflow with YC SDK image model, dood!"""
    # Add model
    model = ycSdkProvider.addModel(
        name="test-image-model",
        modelId="yandex-art",
        modelVersion="latest",
        temperature=0.0,
        contextSize=1024,
        extraConfig={"support_text": False, "support_images": True},
    )

    # Mock response
    imageData = b"test image data"
    mockResult = MockYcSdkResult(imageBytes=imageData)
    mockOperation = MockYcSdkOperation(mockResult)
    model._ycModel.run_deferred = Mock(return_value=mockOperation)

    # Generate image
    messages = [ModelMessage(role="user", content="Generate image")]
    result = await model.generateImage(messages)

    assert result.status == ModelResultStatus.FINAL
    assert result.mediaData == imageData
    assert result.mediaMimeType == "image/jpeg"


def testYcSdkProviderModelManagement(ycSdkProvider):
    """Test YC SDK provider model management, dood!"""
    # Add models
    ycSdkProvider.addModel(
        "yandexgpt",
        "yandexgpt",
        "latest",
        0.6,
        8192,
        {"support_text": True, "support_images": False},
    )
    ycSdkProvider.addModel(
        "yandex-art",
        "yandex-art",
        "latest",
        0.0,
        1024,
        {"support_text": False, "support_images": True},
    )

    # Test listModels
    models = ycSdkProvider.listModels()
    assert len(models) == 2
    assert "yandexgpt" in models
    assert "yandex-art" in models

    # Test getModel
    model = ycSdkProvider.getModel("yandexgpt")
    assert model is not None
    assert model.modelId == "yandexgpt"

    # Test getModelInfo
    info = ycSdkProvider.getModelInfo("yandexgpt")
    assert info is not None
    assert info["model_id"] == "yandexgpt"
    assert info["temperature"] == 0.6
    assert info["support_text"] is True

    # Test deleteModel
    deleted = ycSdkProvider.deleteModel("yandexgpt")
    assert deleted is True
    assert len(ycSdkProvider.listModels()) == 1


# ============================================================================
# Configuration Tests
# ============================================================================


def testYcSdkProviderWithCustomConfig():
    """Test YC SDK provider with custom configuration, dood!"""
    config = {
        "folder_id": "custom-folder-id",
        "yc_profile": "custom-profile",
    }

    with patch("lib.ai.providers.yc_sdk_provider.YCloudML") as mockYCloudML:
        with patch("lib.ai.providers.yc_sdk_provider.YandexCloudCLIAuth"):
            mockYCloudML.return_value = MockYCloudML("custom-folder-id")
            provider = YcSdkProvider(config)

            assert provider.config["folder_id"] == "custom-folder-id"
            assert provider.config["yc_profile"] == "custom-profile"


def testYcSdkImageModelWithAllExtraParams(ycSdkProvider, mockYCloudML):
    """Test YC SDK image model with all extra parameters, dood!"""
    extraConfig = {
        "support_text": False,
        "support_images": True,
        "width_ratio": 16,
        "height_ratio": 9,
        "seed": 42,
    }

    model = YcSdkModel(
        provider=ycSdkProvider,
        modelId="yandex-art",
        modelVersion="latest",
        temperature=0.0,
        contextSize=1024,
        ycSDK=mockYCloudML,
        extraConfig=extraConfig,
    )

    assert model._config["width_ratio"] == 16
    assert model._config["height_ratio"] == 9
    assert model._config["seed"] == 42


# ============================================================================
# Edge Cases Tests
# ============================================================================


@pytest.mark.asyncio
async def testYcSdkGenerateTextEmptyResult(ycSdkTextModel, sampleMessages):
    """Test handling of empty text result, dood!"""
    mockResult = MockYcSdkResult(text="", status=3)
    ycSdkTextModel._ycModel.run = Mock(return_value=mockResult)

    result = await ycSdkTextModel.generateText(sampleMessages)

    assert result.status == ModelResultStatus.FINAL
    assert result.resultText == ""


def testYcSdkProviderStringRepresentation(ycSdkProvider):
    """Test YC SDK provider string representation, dood!"""
    strRepr = str(ycSdkProvider)
    assert "YcSdkProvider" in strRepr
    assert "0 models" in strRepr


def testYcSdkModelStringRepresentation(ycSdkTextModel):
    """Test YC SDK model string representation, dood!"""
    strRepr = str(ycSdkTextModel)
    assert "yandexgpt" in strRepr
    assert "latest" in strRepr
    assert "YcSdkProvider" in strRepr


def testYcSdkModelGetInfo(ycSdkTextModel):
    """Test YC SDK model getInfo method, dood!"""
    info = ycSdkTextModel.getInfo()

    assert info["model_id"] == "yandexgpt"
    assert info["model_version"] == "latest"
    assert info["temperature"] == 0.6
    assert info["context_size"] == 8192
    assert info["support_text"] is True
    assert info["support_images"] is False
