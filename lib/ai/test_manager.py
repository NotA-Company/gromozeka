"""Comprehensive tests for LLMManager, dood!

This module provides extensive test coverage for the LLMManager class,
including provider registration, model management, configuration loading,
error handling, and multi-provider scenarios.
"""

import logging
from typing import Any, Dict
from unittest.mock import patch

import pytest

from lib.ai.abstract import AbstractLLMProvider, AbstractModel
from lib.ai.manager import LLMManager
from lib.ai.models import ModelResultStatus, ModelRunResult

# ============================================================================
# Mock Provider and Model Classes
# ============================================================================


class MockModel(AbstractModel):
    """Mock model for testing, dood!"""

    async def generateText(self, messages, tools=[]):
        """Mock text generation, dood!"""
        return ModelRunResult(
            rawResult={"mock": "response"},
            status=ModelResultStatus.FINAL,
            resultText="Mock response",
        )

    async def generateImage(self, messages):
        """Mock image generation, dood!"""
        return ModelRunResult(
            rawResult={"mock": "image"},
            status=ModelResultStatus.FINAL,
            mediaMimeType="image/png",
            mediaData=b"fake_image_data",
        )


class MockProvider(AbstractLLMProvider):
    """Mock provider for testing, dood!"""

    def addModel(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ) -> AbstractModel:
        """Add a mock model, dood!"""
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
def emptyConfig():
    """Create empty configuration, dood!"""
    return {"providers": {}, "models": {}}


@pytest.fixture
def singleProviderConfig():
    """Create configuration with single provider, dood!"""
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
def multiProviderConfig():
    """Create configuration with multiple providers, dood!"""
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
def configWithDisabledModel():
    """Create configuration with disabled model, dood!"""
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
def mockProviderClasses():
    """Create mock provider classes for patching, dood!"""
    return {
        "YcOpenaiProvider": MockProvider,
        "OpenrouterProvider": MockProvider,
        "YcSdkProvider": MockProvider,
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
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
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
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
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
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
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
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
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


def testListModelsEmpty(emptyConfig):
    """Test listing models returns empty list, dood!"""
    manager = LLMManager(emptyConfig)
    models = manager.listModels()

    assert models == []


def testListModelsSingle(singleProviderConfig, mockProviderClasses):
    """Test listing models with single model, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
    ):
        manager = LLMManager(singleProviderConfig)
        models = manager.listModels()

        assert len(models) == 1
        assert "test-model" in models


def testListModelsMultiple(multiProviderConfig, mockProviderClasses):
    """Test listing models with multiple models, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
    ):
        manager = LLMManager(multiProviderConfig)
        models = manager.listModels()

        assert len(models) == 3
        assert "model1" in models
        assert "model2" in models
        assert "model3" in models


def testGetModelSuccess(singleProviderConfig, mockProviderClasses):
    """Test getting model by name succeeds, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
    ):
        manager = LLMManager(singleProviderConfig)
        model = manager.getModel("test-model")

        assert model is not None
        assert isinstance(model, MockModel)
        assert model.modelId == "gpt-4"


def testGetModelNotFound(emptyConfig):
    """Test getting non-existent model returns None, dood!"""
    manager = LLMManager(emptyConfig)
    model = manager.getModel("nonexistent-model")

    assert model is None


def testGetModelProviderNotFound(singleProviderConfig, mockProviderClasses):
    """Test getting model when provider is missing returns None, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
    ):
        manager = LLMManager(singleProviderConfig)
        # Manually corrupt the registry
        manager.modelRegistry["orphan-model"] = "nonexistent-provider"

        model = manager.getModel("orphan-model")
        assert model is None


def testGetModelInfoSuccess(singleProviderConfig, mockProviderClasses):
    """Test getting model info succeeds, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
    ):
        manager = LLMManager(singleProviderConfig)
        info = manager.getModelInfo("test-model")

        assert info is not None
        assert "model_id" in info
        assert info["model_id"] == "gpt-4"
        assert "temperature" in info
        assert info["temperature"] == 0.7


def testGetModelInfoNotFound(emptyConfig):
    """Test getting info for non-existent model returns None, dood!"""
    manager = LLMManager(emptyConfig)
    info = manager.getModelInfo("nonexistent-model")

    assert info is None


# ============================================================================
# Provider Management Tests
# ============================================================================


def testListProvidersEmpty(emptyConfig):
    """Test listing providers returns empty list, dood!"""
    manager = LLMManager(emptyConfig)
    providers = manager.listProviders()

    assert providers == []


def testListProvidersSingle(singleProviderConfig, mockProviderClasses):
    """Test listing providers with single provider, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
    ):
        manager = LLMManager(singleProviderConfig)
        providers = manager.listProviders()

        assert len(providers) == 1
        assert "test-provider" in providers


def testListProvidersMultiple(multiProviderConfig, mockProviderClasses):
    """Test listing providers with multiple providers, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
    ):
        manager = LLMManager(multiProviderConfig)
        providers = manager.listProviders()

        assert len(providers) == 3
        assert "provider1" in providers
        assert "provider2" in providers
        assert "provider3" in providers


def testGetProviderSuccess(singleProviderConfig, mockProviderClasses):
    """Test getting provider by name succeeds, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
    ):
        manager = LLMManager(singleProviderConfig)
        provider = manager.getProvider("test-provider")

        assert provider is not None
        assert isinstance(provider, MockProvider)


def testGetProviderNotFound(emptyConfig):
    """Test getting non-existent provider returns None, dood!"""
    manager = LLMManager(emptyConfig)
    provider = manager.getProvider("nonexistent-provider")

    assert provider is None


# ============================================================================
# Model Initialization Tests
# ============================================================================


def testModelInitializationWithMissingProvider(caplog, mockProviderClasses):
    """Test model initialization skips models with missing provider, dood!"""
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
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
    ):
        with caplog.at_level(logging.WARNING):
            manager = LLMManager(config)

            assert "orphan-model" not in manager.modelRegistry
            assert "Provider nonexistent-provider not available" in caplog.text


def testModelInitializationWithException(caplog, mockProviderClasses):
    """Test model initialization handles exceptions, dood!"""

    class FailingProvider(MockProvider):
        def addModel(self, *args, **kwargs):
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


def testModelInitializationWithDefaultValues(mockProviderClasses):
    """Test model initialization uses default values, dood!"""
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
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
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


def testMultiProviderModelSelection(multiProviderConfig, mockProviderClasses):
    """Test selecting models from different providers, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
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


def testDuplicateModelNamesAcrossProviders(mockProviderClasses):
    """Test handling duplicate model names across providers, dood!"""
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
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
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


def testModelAvailabilityChecking(singleProviderConfig, mockProviderClasses):
    """Test checking model availability, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
    ):
        manager = LLMManager(singleProviderConfig)

        # Check available model
        assert manager.getModel("test-model") is not None

        # Check unavailable model
        assert manager.getModel("nonexistent-model") is None


def testFullWorkflowInitializeAndUseModel(singleProviderConfig, mockProviderClasses):
    """Test full workflow: initialize manager and use model, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
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


def testConfigurationPersistence(singleProviderConfig, mockProviderClasses):
    """Test configuration is persisted in manager, dood!"""
    with patch.multiple(
        "lib.ai.manager",
        YcOpenaiProvider=mockProviderClasses["YcOpenaiProvider"],
        OpenrouterProvider=mockProviderClasses["OpenrouterProvider"],
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
    ):
        manager = LLMManager(singleProviderConfig)

        # Verify config is stored
        assert manager.config == singleProviderConfig
        assert "providers" in manager.config
        assert "models" in manager.config


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


def testEmptyProvidersConfig():
    """Test handling empty providers config, dood!"""
    config = {"models": {}}
    manager = LLMManager(config)

    assert len(manager.providers) == 0
    assert len(manager.modelRegistry) == 0


def testEmptyModelsConfig(mockProviderClasses):
    """Test handling empty models config, dood!"""
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
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
    ):
        manager = LLMManager(config)

        assert len(manager.providers) == 1
        assert len(manager.modelRegistry) == 0


def testModelWithExtraConfig(mockProviderClasses):
    """Test model initialization with extra configuration, dood!"""
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
        YcSdkProvider=mockProviderClasses["YcSdkProvider"],
    ):
        manager = LLMManager(config)

        model = manager.getModel("configured-model")
        assert model is not None
        info = model.getInfo()
        assert info["support_tools"] is True
        assert info["support_images"] is False
