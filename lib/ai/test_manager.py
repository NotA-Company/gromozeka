"""Comprehensive tests for LLMManager.

This module provides extensive test coverage for the LLMManager class,
including provider registration, model management, configuration loading,
error handling, and multi-provider scenarios.

Test Categories:
    - Initialization Tests: Verify manager initialization with various configurations
    - Provider Registration Tests: Test provider registration and error handling
    - Model Management Tests: Test model listing, retrieval, and info access
    - Provider Management Tests: Test provider listing and retrieval
    - Model Initialization Tests: Test model initialization with edge cases
    - Integration Tests: Test multi-provider scenarios and full workflows
    - Edge Cases and Error Handling: Test boundary conditions and error scenarios

Mock Classes:
    MockModel: Mock implementation of AbstractModel for testing
    MockProvider: Mock implementation of AbstractLLMProvider for testing

Fixtures:
    emptyConfig: Empty configuration dictionary
    singleProviderConfig: Configuration with one provider and model
    multiProviderConfig: Configuration with multiple providers and models
    configWithDisabledModel: Configuration with enabled and disabled models
    mockProviderClasses: Dictionary of mock provider classes for patching
"""

import logging
from collections.abc import Sequence
from typing import Any, Dict
from unittest.mock import patch

import pytest

from lib.ai.abstract import AbstractLLMProvider, AbstractModel
from lib.ai.manager import LLMManager
from lib.ai.models import ModelMessage, ModelResultStatus, ModelRunResult, ModelStructuredResult

# ============================================================================
# Mock Provider and Model Classes
# ============================================================================


class MockModel(AbstractModel):
    """Mock model implementation for testing LLMManager.

    This class provides a mock implementation of AbstractModel that returns
    predefined responses for text and image generation. It is used in tests
    to verify LLMManager functionality without making actual API calls.

    Attributes:
        provider: The parent provider instance
        modelId: The model identifier
        modelVersion: The model version string
        temperature: The temperature parameter for generation
        contextSize: The maximum context window size
        extraConfig: Additional configuration parameters
    """

    async def _generateText(self, messages: list, tools: list = []) -> ModelRunResult:
        """Generate mock text response.

        Args:
            messages: List of message dictionaries for the conversation
            tools: Optional list of tool definitions (default: [])

        Returns:
            ModelRunResult: Mock result with predefined text response
        """
        return ModelRunResult(
            rawResult={"mock": "response"},
            status=ModelResultStatus.FINAL,
            resultText="Mock response",
        )

    async def generateImage(self, messages: list) -> ModelRunResult:
        """Generate mock image response.

        Args:
            messages: List of message dictionaries for the conversation

        Returns:
            ModelRunResult: Mock result with predefined image data
        """
        return ModelRunResult(
            rawResult={"mock": "image"},
            status=ModelResultStatus.FINAL,
            mediaMimeType="image/png",
            mediaData=b"fake_image_data",
        )

    async def _generateStructured(
        self,
        messages: Sequence[ModelMessage],
        schema: Dict[str, Any],
        *,
        schemaName: str = "response",
        strict: bool = True,
    ) -> ModelStructuredResult:
        """Mock structured-output implementation.

        Args:
            messages: Conversation history (unused by mock).
            schema: JSON Schema dict (unused by mock).
            schemaName: Schema identifier (unused by mock).
            strict: Strict-mode flag (unused by mock).

        Returns:
            ModelStructuredResult with a fixed mock payload.
        """
        return ModelStructuredResult(
            rawResult=None,
            status=ModelResultStatus.FINAL,
            data={"mock": True, "schemaName": schemaName},
            resultText='{"mock": true, "schemaName": "response"}',
        )


class MockProvider(AbstractLLMProvider):
    """Mock LLM provider implementation for testing LLMManager.

    This class provides a mock implementation of AbstractLLMProvider that
    creates MockModel instances. It is used in tests to verify provider
    registration and model management without making actual API calls.

    Attributes:
        models: Dictionary mapping model names to MockModel instances
    """

    def addModel(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ) -> AbstractModel:
        """Add a mock model to the provider.

        Args:
            name: The unique name for the model
            modelId: The model identifier
            modelVersion: The model version string
            temperature: The temperature parameter for generation
            contextSize: The maximum context window size
            extraConfig: Additional configuration parameters (default: {})

        Returns:
            AbstractModel: The created or existing MockModel instance
        """
        if name in self.models:
            return self.models[name]

        model = MockModel(
            provider=self,
            modelId=modelId,
            modelVersion=modelVersion,
            temperature=temperature,
            contextSize=contextSize,
            extraConfig=extraConfig,
        )
        self.models[name] = model
        return model


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def emptyConfig() -> Dict[str, Any]:
    """Create empty configuration for testing.

    Returns:
        Dict[str, Any]: Configuration dictionary with empty providers and models
    """
    return {"providers": {}, "models": {}}


@pytest.fixture
def singleProviderConfig() -> Dict[str, Any]:
    """Create configuration with single provider and model for testing.

    Returns:
        Dict[str, Any]: Configuration dictionary with one yc-openai provider
            and one enabled model
    """
    return {
        "providers": {
            "test-provider": {
                "type": "yc-openai",
                "api_key": "test-key",
                "base_url": "https://test.api.com",
            }
        },
        "models": {
            "test-model": {
                "provider": "test-provider",
                "model_id": "gpt-4",
                "model_version": "1.0",
                "temperature": 0.7,
                "context": 4096,
                "enabled": True,
            }
        },
    }


@pytest.fixture
def multiProviderConfig() -> Dict[str, Any]:
    """Create configuration with multiple providers and models for testing.

    Returns:
        Dict[str, Any]: Configuration dictionary with three providers
            (yc-openai, openrouter, yc-sdk) and three models
    """
    return {
        "providers": {
            "provider1": {
                "type": "yc-openai",
                "api_key": "key1",
            },
            "provider2": {
                "type": "openrouter",
                "api_key": "key2",
            },
            "provider3": {
                "type": "yc-sdk",
                "api_key": "key3",
            },
        },
        "models": {
            "model1": {
                "provider": "provider1",
                "model_id": "gpt-4",
                "model_version": "1.0",
                "temperature": 0.7,
                "context": 4096,
            },
            "model2": {
                "provider": "provider2",
                "model_id": "claude-3",
                "model_version": "1.0",
                "temperature": 0.5,
                "context": 8192,
            },
            "model3": {
                "provider": "provider3",
                "model_id": "yandex-gpt",
                "model_version": "latest",
                "temperature": 0.8,
                "context": 2048,
            },
        },
    }


@pytest.fixture
def configWithDisabledModel() -> Dict[str, Any]:
    """Create configuration with both enabled and disabled models for testing.

    Returns:
        Dict[str, Any]: Configuration dictionary with one provider and
            two models (one enabled, one disabled)
    """
    return {
        "providers": {
            "test-provider": {
                "type": "yc-openai",
                "api_key": "test-key",
            }
        },
        "models": {
            "enabled-model": {
                "provider": "test-provider",
                "model_id": "gpt-4",
                "model_version": "1.0",
                "temperature": 0.7,
                "context": 4096,
                "enabled": True,
            },
            "disabled-model": {
                "provider": "test-provider",
                "model_id": "gpt-3.5",
                "model_version": "1.0",
                "temperature": 0.5,
                "context": 2048,
                "enabled": False,
            },
        },
    }


@pytest.fixture
def mockProviderClasses() -> Dict[str, type]:
    """Create mock provider classes for patching in tests.

    Returns:
        Dict[str, type]: Dictionary mapping provider class names to MockProvider
    """
    return {
        "YcOpenaiProvider": MockProvider,
        "OpenrouterProvider": MockProvider,
        "YcAIProvider": MockProvider,
    }


# ============================================================================
# Initialization Tests
# ============================================================================


def testManagerInitializationWithEmptyConfig(emptyConfig):
    """Test manager initializes with empty config, dood!"""
    manager = LLMManager(emptyConfig)

    assert manager is not None
    assert manager.config == emptyConfig
    assert len(manager.providers) == 0
    assert len(manager.modelRegistry) == 0


def testManagerInitializationWithSingleProvider(singleProviderConfig, mockProviderClasses):
    """Test manager initializes with single provider, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(singleProviderConfig)

        assert len(manager.providers) == 1
        assert "test-provider" in manager.providers
        assert len(manager.modelRegistry) == 1
        assert "test-model" in manager.modelRegistry


def testManagerInitializationWithMultipleProviders(multiProviderConfig, mockProviderClasses):
    """Test manager initializes with multiple providers, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(multiProviderConfig)

        assert len(manager.providers) == 3
        assert "provider1" in manager.providers
        assert "provider2" in manager.providers
        assert "provider3" in manager.providers
        assert len(manager.modelRegistry) == 3


def testManagerInitializationSkipsDisabledModels(configWithDisabledModel, mockProviderClasses):
    """Test manager skips disabled models during initialization, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(configWithDisabledModel)

        assert len(manager.modelRegistry) == 1
        assert "enabled-model" in manager.modelRegistry
        assert "disabled-model" not in manager.modelRegistry


# ============================================================================
# Provider Registration Tests
# ============================================================================


def testProviderRegistrationSuccess(mockProviderClasses):
    """Test successful provider registration, dood!"""
    config = {
        "providers": {
            "test-provider": {
                "type": "yc-openai",
                "api_key": "test-key",
            }
        },
        "models": {},
    }

    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(config)

        assert "test-provider" in manager.providers
        assert isinstance(manager.providers["test-provider"], MockProvider)


def testProviderRegistrationMissingType(caplog):
    """Test provider registration fails without type, dood!"""
    config = {
        "providers": {
            "bad-provider": {
                "api_key": "test-key",
            }
        },
        "models": {},
    }

    with caplog.at_level(logging.ERROR):
        manager = LLMManager(config)

        assert "bad-provider" not in manager.providers
        assert "Failed to initialize bad-provider provider" in caplog.text


def testProviderRegistrationUnknownType(caplog):
    """Test provider registration fails with unknown type, dood!"""
    config = {
        "providers": {
            "bad-provider": {
                "type": "unknown-provider-type",
                "api_key": "test-key",
            }
        },
        "models": {},
    }

    with caplog.at_level(logging.ERROR):
        manager = LLMManager(config)

        assert "bad-provider" not in manager.providers
        assert "Failed to initialize bad-provider provider" in caplog.text


def testProviderRegistrationWithException(caplog):
    """Test provider registration handles exceptions, dood!"""

    class FailingProvider:
        def __init__(self, config):
            raise RuntimeError("Provider initialization failed")

    config = {
        "providers": {
            "failing-provider": {
                "type": "yc-openai",
                "api_key": "test-key",
            }
        },
        "models": {},
    }

    with patch("lib.ai.manager.YcOpenaiProvider", FailingProvider):
        with caplog.at_level(logging.ERROR):
            manager = LLMManager(config)

            assert "failing-provider" not in manager.providers
            assert "Failed to initialize failing-provider provider" in caplog.text


# ============================================================================
# Model Management Tests
# ============================================================================


def testListModelsEmpty(emptyConfig: Dict[str, Any]) -> None:
    """Test listing models returns empty list when no models configured.

    Args:
        emptyConfig: Empty configuration dictionary fixture
    """
    manager = LLMManager(emptyConfig)
    models = manager.listModels()

    assert models == []


def testListModelsSingle(singleProviderConfig: Dict[str, Any], mockProviderClasses: Dict[str, type]) -> None:
    """Test listing models with single model configured.

    Args:
        singleProviderConfig: Configuration with one provider and model
        mockProviderClasses: Mock provider classes for patching
    """
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(singleProviderConfig)
        models = manager.listModels()

        assert len(models) == 1
        assert "test-model" in models


def testListModelsMultiple(multiProviderConfig: Dict[str, Any], mockProviderClasses: Dict[str, type]) -> None:
    """Test listing models with multiple models configured.

    Args:
        multiProviderConfig: Configuration with multiple providers and models
        mockProviderClasses: Mock provider classes for patching
    """
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(multiProviderConfig)
        models = manager.listModels()

        assert len(models) == 3
        assert "model1" in models
        assert "model2" in models
        assert "model3" in models


def testGetModelSuccess(singleProviderConfig: Dict[str, Any], mockProviderClasses: Dict[str, type]) -> None:
    """Test getting model by name succeeds.

    Args:
        singleProviderConfig: Configuration with one provider and model
        mockProviderClasses: Mock provider classes for patching
    """
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(singleProviderConfig)
        model = manager.getModel("test-model")

        assert model is not None
        assert isinstance(model, MockModel)
        assert model.modelId == "gpt-4"


def testGetModelNotFound(emptyConfig: Dict[str, Any]) -> None:
    """Test getting non-existent model returns None.

    Args:
        emptyConfig: Empty configuration dictionary fixture
    """
    manager = LLMManager(emptyConfig)
    model = manager.getModel("nonexistent-model")

    assert model is None


def testGetModelProviderNotFound(singleProviderConfig: Dict[str, Any], mockProviderClasses: Dict[str, type]) -> None:
    """Test getting model when provider is missing returns None.

    Args:
        singleProviderConfig: Configuration with one provider and model
        mockProviderClasses: Mock provider classes for patching
    """
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(singleProviderConfig)
        # Manually corrupt the registry
        manager.modelRegistry["orphan-model"] = "nonexistent-provider"

        model = manager.getModel("orphan-model")
        assert model is None


def testGetModelInfoSuccess(singleProviderConfig: Dict[str, Any], mockProviderClasses: Dict[str, type]) -> None:
    """Test getting model info succeeds.

    Args:
        singleProviderConfig: Configuration with one provider and model
        mockProviderClasses: Mock provider classes for patching
    """
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(singleProviderConfig)
        info = manager.getModelInfo("test-model")

        assert info is not None
        assert "model_id" in info
        assert info["model_id"] == "gpt-4"
        assert "temperature" in info
        assert info["temperature"] == 0.7


def testGetModelInfoNotFound(emptyConfig: Dict[str, Any]) -> None:
    """Test getting info for non-existent model returns None.

    Args:
        emptyConfig: Empty configuration dictionary fixture
    """
    manager = LLMManager(emptyConfig)
    info = manager.getModelInfo("nonexistent-model")

    assert info is None


# ============================================================================
# Provider Management Tests
# ============================================================================


def testListProvidersEmpty(emptyConfig: Dict[str, Any]) -> None:
    """Test listing providers returns empty list when no providers configured.

    Args:
        emptyConfig: Empty configuration dictionary fixture
    """
    manager = LLMManager(emptyConfig)
    providers = manager.listProviders()

    assert providers == []


def testListProvidersSingle(singleProviderConfig: Dict[str, Any], mockProviderClasses: Dict[str, type]) -> None:
    """Test listing providers with single provider configured.

    Args:
        singleProviderConfig: Configuration with one provider and model
        mockProviderClasses: Mock provider classes for patching
    """
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(singleProviderConfig)
        providers = manager.listProviders()

        assert len(providers) == 1
        assert "test-provider" in providers


def testListProvidersMultiple(multiProviderConfig: Dict[str, Any], mockProviderClasses: Dict[str, type]) -> None:
    """Test listing providers with multiple providers configured.

    Args:
        multiProviderConfig: Configuration with multiple providers and models
        mockProviderClasses: Mock provider classes for patching
    """
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(multiProviderConfig)
        providers = manager.listProviders()

        assert len(providers) == 3
        assert "provider1" in providers
        assert "provider2" in providers
        assert "provider3" in providers


def testGetProviderSuccess(singleProviderConfig: Dict[str, Any], mockProviderClasses: Dict[str, type]) -> None:
    """Test getting provider by name succeeds.

    Args:
        singleProviderConfig: Configuration with one provider and model
        mockProviderClasses: Mock provider classes for patching
    """
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(singleProviderConfig)
        provider = manager.getProvider("test-provider")

        assert provider is not None
        assert isinstance(provider, MockProvider)


def testGetProviderNotFound(emptyConfig: Dict[str, Any]) -> None:
    """Test getting non-existent provider returns None.

    Args:
        emptyConfig: Empty configuration dictionary fixture
    """
    manager = LLMManager(emptyConfig)
    provider = manager.getProvider("nonexistent-provider")

    assert provider is None


# ============================================================================
# Model Initialization Tests
# ============================================================================


def testModelInitializationWithMissingProvider(
    caplog: pytest.LogCaptureFixture, mockProviderClasses: Dict[str, type]
) -> None:
    """Test model initialization skips models with missing provider.

    Args:
        caplog: Pytest fixture for capturing log output
        mockProviderClasses: Mock provider classes for patching
    """
    config = {
        "providers": {
            "existing-provider": {
                "type": "yc-openai",
                "api_key": "test-key",
            }
        },
        "models": {
            "orphan-model": {
                "provider": "nonexistent-provider",
                "model_id": "gpt-4",
                "model_version": "1.0",
                "temperature": 0.7,
                "context": 4096,
            }
        },
    }

    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        with caplog.at_level(logging.WARNING):
            manager = LLMManager(config)

            assert "orphan-model" not in manager.modelRegistry
            assert "Provider nonexistent-provider not available" in caplog.text


def testModelInitializationWithException(
    caplog: pytest.LogCaptureFixture, mockProviderClasses: Dict[str, type]
) -> None:
    """Test model initialization handles exceptions.

    Args:
        caplog: Pytest fixture for capturing log output
        mockProviderClasses: Mock provider classes for patching
    """

    class FailingProvider(MockProvider):
        def addModel(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("Model addition failed")

    config = {
        "providers": {
            "failing-provider": {
                "type": "yc-openai",
                "api_key": "test-key",
            }
        },
        "models": {
            "failing-model": {
                "provider": "failing-provider",
                "model_id": "gpt-4",
                "model_version": "1.0",
                "temperature": 0.7,
                "context": 4096,
            }
        },
    }

    with patch("lib.ai.manager.YcOpenaiProvider", FailingProvider):
        with caplog.at_level(logging.ERROR):
            manager = LLMManager(config)

            assert "failing-model" not in manager.modelRegistry
            assert "Failed to initialize model" in caplog.text


def testModelInitializationWithDefaultValues(mockProviderClasses: Dict[str, type]) -> None:
    """Test model initialization uses default values for optional fields.

    Args:
        mockProviderClasses: Mock provider classes for patching
    """
    config = {
        "providers": {
            "test-provider": {
                "type": "yc-openai",
                "api_key": "test-key",
            }
        },
        "models": {
            "minimal-model": {
                "provider": "test-provider",
                "model_id": "gpt-4",
                # Missing optional fields
            }
        },
    }

    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(config)

        assert "minimal-model" in manager.modelRegistry
        model = manager.getModel("minimal-model")
        assert model is not None
        assert model.modelVersion == "latest"
        assert model.temperature == 0.5
        assert model.contextSize == 32768


# ============================================================================
# Integration Tests
# ============================================================================


def testMultiProviderModelSelection(multiProviderConfig: Dict[str, Any], mockProviderClasses: Dict[str, type]) -> None:
    """Test selecting models from different providers.

    Args:
        multiProviderConfig: Configuration with multiple providers and models
        mockProviderClasses: Mock provider classes for patching
    """
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(multiProviderConfig)

        # Get models from different providers
        model1 = manager.getModel("model1")
        model2 = manager.getModel("model2")
        model3 = manager.getModel("model3")

        assert model1 is not None
        assert model2 is not None
        assert model3 is not None

        # Verify they come from different providers
        assert manager.modelRegistry["model1"] == "provider1"
        assert manager.modelRegistry["model2"] == "provider2"
        assert manager.modelRegistry["model3"] == "provider3"


def testDuplicateModelNamesAcrossProviders(mockProviderClasses: Dict[str, type]) -> None:
    """Test handling duplicate model names across providers.

    Args:
        mockProviderClasses: Mock provider classes for patching
    """
    config = {
        "providers": {
            "provider1": {
                "type": "yc-openai",
                "api_key": "key1",
            },
            "provider2": {
                "type": "openrouter",
                "api_key": "key2",
            },
        },
        "models": {
            "duplicate-name": {
                "provider": "provider1",
                "model_id": "gpt-4",
                "model_version": "1.0",
                "temperature": 0.7,
                "context": 4096,
            },
            "duplicate-name-2": {
                "provider": "provider2",
                "model_id": "claude-3",
                "model_version": "1.0",
                "temperature": 0.5,
                "context": 8192,
            },
        },
    }

    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(config)

        # Both models should be registered with different names
        assert "duplicate-name" in manager.modelRegistry
        assert "duplicate-name-2" in manager.modelRegistry

        model1 = manager.getModel("duplicate-name")
        model2 = manager.getModel("duplicate-name-2")

        assert model1 is not None
        assert model2 is not None
        assert model1.modelId == "gpt-4"
        assert model2.modelId == "claude-3"


def testModelAvailabilityChecking(singleProviderConfig: Dict[str, Any], mockProviderClasses: Dict[str, type]) -> None:
    """Test checking model availability.

    Args:
        singleProviderConfig: Configuration with one provider and model
        mockProviderClasses: Mock provider classes for patching
    """
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(singleProviderConfig)

        # Check available model
        assert manager.getModel("test-model") is not None

        # Check unavailable model
        assert manager.getModel("nonexistent-model") is None


def testFullWorkflowInitializeAndUseModel(
    singleProviderConfig: Dict[str, Any], mockProviderClasses: Dict[str, type]
) -> None:
    """Test full workflow: initialize manager and use model.

    Args:
        singleProviderConfig: Configuration with one provider and model
        mockProviderClasses: Mock provider classes for patching
    """
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        # Initialize manager
        manager = LLMManager(singleProviderConfig)

        # List available models
        models = manager.listModels()
        assert len(models) == 1

        # Get model
        model = manager.getModel("test-model")
        assert model is not None

        # Get model info
        info = manager.getModelInfo("test-model")
        assert info is not None
        assert info["model_id"] == "gpt-4"

        # Get provider
        provider = manager.getProvider("test-provider")
        assert provider is not None


def testConfigurationPersistence(singleProviderConfig: Dict[str, Any], mockProviderClasses: Dict[str, type]) -> None:
    """Test configuration is persisted in manager.

    Args:
        singleProviderConfig: Configuration with one provider and model
        mockProviderClasses: Mock provider classes for patching
    """
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(singleProviderConfig)

        # Verify config is stored
        assert manager.config == singleProviderConfig
        assert "providers" in manager.config
        assert "models" in manager.config


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


def testEmptyProvidersConfig() -> None:
    """Test handling empty providers configuration.

    Verifies that the manager initializes correctly when no providers are
    configured in the configuration dictionary.
    """
    config = {"models": {}}
    manager = LLMManager(config)

    assert len(manager.providers) == 0
    assert len(manager.modelRegistry) == 0


def testEmptyModelsConfig(mockProviderClasses: Dict[str, type]) -> None:
    """Test handling empty models configuration.

    Args:
        mockProviderClasses: Mock provider classes for patching

    Verifies that the manager initializes correctly when providers are
    configured but no models are defined.
    """
    config = {
        "providers": {
            "test-provider": {
                "type": "yc-openai",
                "api_key": "test-key",
            }
        }
    }

    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(config)

        assert len(manager.providers) == 1
        assert len(manager.modelRegistry) == 0


def testModelWithExtraConfig(mockProviderClasses: Dict[str, type]) -> None:
    """Test model initialization with extra configuration parameters.

    Args:
        mockProviderClasses: Mock provider classes for patching

    Verifies that models can be initialized with additional custom
    configuration parameters beyond the standard fields.
    """
    config = {
        "providers": {
            "test-provider": {
                "type": "yc-openai",
                "api_key": "test-key",
            }
        },
        "models": {
            "configured-model": {
                "provider": "test-provider",
                "model_id": "gpt-4",
                "model_version": "1.0",
                "temperature": 0.7,
                "context": 4096,
                "support_tools": True,
                "support_images": False,
                "custom_param": "value",
            }
        },
    }

    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(config)

        model = manager.getModel("configured-model")
        assert model is not None
        info = model.getInfo()
        assert info["support_tools"] is True
        assert info["support_images"] is False


# ============================================================================
# Structured Output Tests (Phase 3)
# ============================================================================


def testGetModelInfoIncludesStructuredOutputFlag(mockProviderClasses: Dict[str, type]) -> None:
    """Test getModelInfo returns support_structured_output=True when configured.

    Args:
        mockProviderClasses: Mock provider classes for patching
    """
    config = {
        "providers": {
            "test-provider": {
                "type": "yc-openai",
                "api_key": "test-key",
            }
        },
        "models": {
            "structured-model": {
                "provider": "test-provider",
                "model_id": "gpt-4",
                "model_version": "1.0",
                "temperature": 0.7,
                "context": 4096,
                "support_structured_output": True,
            }
        },
    }

    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(config)
        info = manager.getModelInfo("structured-model")

        assert info is not None
        assert info["support_structured_output"] is True


def testGetModelInfoStructuredOutputDefaultsFalse(mockProviderClasses: Dict[str, type]) -> None:
    """Test getModelInfo returns support_structured_output=False when flag is absent.

    Args:
        mockProviderClasses: Mock provider classes for patching
    """
    config = {
        "providers": {
            "test-provider": {
                "type": "yc-openai",
                "api_key": "test-key",
            }
        },
        "models": {
            "plain-model": {
                "provider": "test-provider",
                "model_id": "gpt-4",
                "model_version": "1.0",
                "temperature": 0.7,
                "context": 4096,
            }
        },
    }

    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcAIProvider=mockProviderClasses["YcAIProvider"],
    ):
        manager = LLMManager(config)
        info = manager.getModelInfo("plain-model")

        assert info is not None
        assert info["support_structured_output"] is False


async def testMockModelGenerateStructuredHappyPath() -> None:
    """Test MockModel._generateStructured returns fixed payload via public API.

    Verifies that calling generateStructured on a MockModel with
    support_structured_output=True returns the expected fixed result,
    and that schemaName flows into the data payload.
    """
    provider = MockProvider(config={})
    model = MockModel(
        provider=provider,
        modelId="mock-model",
        modelVersion="latest",
        temperature=0.5,
        contextSize=4096,
        extraConfig={"support_structured_output": True},
    )

    schema: Dict[str, Any] = {"type": "object", "properties": {"answer": {"type": "string"}}}
    messages: list = []

    result = await model.generateStructured(messages, schema)

    assert result.status == ModelResultStatus.FINAL
    assert result.data == {"mock": True, "schemaName": "response"}
    assert result.resultText == '{"mock": true, "schemaName": "response"}'

    # Verify schemaName flows through to data
    resultCustom = await model.generateStructured(messages, schema, schemaName="custom")
    assert resultCustom.data == {"mock": True, "schemaName": "custom"}


async def testMockModelGenerateStructuredFlagFalse() -> None:
    """Test generateStructured raises NotImplementedError when flag is False.

    Verifies that the public generateStructured gate raises NotImplementedError
    when support_structured_output is not set (defaults to False).
    """
    provider = MockProvider(config={})
    model = MockModel(
        provider=provider,
        modelId="mock-model",
        modelVersion="latest",
        temperature=0.5,
        contextSize=4096,
        extraConfig={},
    )

    schema: Dict[str, Any] = {"type": "object"}
    messages: list = []

    with pytest.raises(NotImplementedError):
        await model.generateStructured(messages, schema)
