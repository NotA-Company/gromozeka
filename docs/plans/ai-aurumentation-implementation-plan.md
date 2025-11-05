# AI Aurumentation System Implementation Plan

## Document Information

**Version:** 1.0  
**Created:** 2025-11-03  
**Status:** Draft  
**Related Documents:**
- Design Document: [`docs/ai-aurumentation-design.md`](ai-aurumentation-design.md)
- OpenWeatherMap Golden Tests Report: [`docs/reports/OpenWeatherMap-testing-golden.md`](../reports/OpenWeatherMap-testing-golden.md)

---

## 1. Project Overview

### 1.1 What We're Implementing

This plan details the implementation of golden data testing for AI provider integrations in the Gromozeka project. The system will enable deterministic, offline testing of four AI providers:

1. **BasicOpenAIProvider** - Standard OpenAI API
2. **YcOpenaiProvider** - Yandex Cloud OpenAI-compatible API
3. **OpenrouterProvider** - OpenRouter aggregation service
4. **YcSdkProvider** - Yandex Cloud ML SDK (special handling required)

### 1.2 Reference to Design Document

The complete architecture, data flow, and technical approach are documented in [`docs/ai-aurumentation-design.md`](ai-aurumentation-design.md). This implementation plan provides actionable steps to realize that design.

### 1.3 Success Criteria

The implementation will be considered successful when:

- ✅ All HTTP-based providers (BasicOpenAI, YcOpenai, Openrouter) have golden data tests
- ✅ YcSdkProvider has SDK-level mocked tests
- ✅ At least 3 scenarios per provider are implemented and passing
- ✅ Secret masking works correctly for all providers
- ✅ Tests run without real API calls or credentials
- ✅ CI/CD pipeline includes golden data tests
- ✅ Documentation is complete and up-to-date
- ✅ Collection scripts are reusable and well-documented

---

## 2. Prerequisites

### 2.1 Required Environment Variables

Create a `.env` file in the project root with the following variables (only needed for golden data collection, not for running tests):

```bash
# OpenAI
OPENAI_API_KEY=sk-...

# Yandex Cloud OpenAI-compatible API
YC_API_KEY=AQVN...
YC_FOLDER_ID=b1g...

# OpenRouter
OPENROUTER_API_KEY=sk-or-v1-...

# Yandex Cloud SDK (for YcSdkProvider)
YC_SDK_API_KEY=AQVN...
# OR use Yandex Cloud CLI authentication (no env var needed)
```

**Important:** These credentials are ONLY needed when collecting golden data. Tests will run without any credentials using the recorded data.

### 2.2 Configuration Files Needed

No new configuration files are required. The system will use:
- Existing provider configurations in [`configs/00-defaults/providers.toml`](../configs/00-defaults/providers.toml)
- Model configurations in respective TOML files

### 2.3 Dependencies and Tools

All required dependencies are already installed:
- ✅ `httpx` - HTTP client (already used by providers)
- ✅ `openai` - OpenAI SDK (already installed)
- ✅ `yandex-cloud-ml-sdk` - YC SDK (already installed)
- ✅ `pytest` - Testing framework (already installed)

The aurumentation framework is already implemented in [`lib/aurumentation/`](../lib/aurumentation/).

---

## 3. Phase 1: Foundation Setup

**Estimated Time:** 2-3 hours  
**Dependencies:** None  
**Risk Level:** Low

### 3.1 Create Directory Structure

**Task 1.1:** Create golden data directory structure

```bash
mkdir -p tests/golden_data/ai_providers/{scenarios,basic_openai,yc_openai,openrouter,yc_sdk}
```

**Files to create:**
- `tests/golden_data/ai_providers/` - Root directory
- `tests/golden_data/ai_providers/scenarios/` - Scenario definitions
- `tests/golden_data/ai_providers/basic_openai/` - BasicOpenAI golden data
- `tests/golden_data/ai_providers/yc_openai/` - YcOpenai golden data
- `tests/golden_data/ai_providers/openrouter/` - Openrouter golden data
- `tests/golden_data/ai_providers/yc_sdk/` - YcSdk golden data

**Validation:** Run `ls -la tests/golden_data/ai_providers/` and verify all directories exist.

### 3.2 Create Base Scenario Configuration Format

**Task 1.2:** Create scenario template file

Create `tests/golden_data/ai_providers/scenarios/README.md`:

```markdown
# AI Provider Test Scenarios

This directory contains scenario definitions for collecting golden data for AI providers.

## Scenario Format

Each scenario file is a JSON array of scenario objects:

\`\`\`json
[
  {
    "name": "scenario_name",
    "description": "Human-readable description",
    "module": "lib.ai.providers.provider_module",
    "class": "ProviderClassName",
    "method": "generateText",
    "init_kwargs": {
      "api_key": "${API_KEY_ENV_VAR}",
      "models": {...}
    },
    "kwargs": {
      "model_name": "model-id",
      "messages": [...]
    }
  }
]
\`\`\`

## Environment Variable Substitution

Use `${VAR_NAME}` syntax for environment variables. The collector will substitute these with actual values during collection, but they will be masked in the golden data files.

## Files

- `basic_openai_scenarios.json` - BasicOpenAIProvider scenarios
- `yc_openai_scenarios.json` - YcOpenaiProvider scenarios
- `openrouter_scenarios.json` - OpenrouterProvider scenarios
- `yc_sdk_scenarios.json` - YcSdkProvider scenarios (SDK-level mocking)
```

**Validation:** File exists and is readable.

### 3.3 Prepare Secret Masking Configuration

**Task 1.3:** Document secret masking strategy

Create `tests/golden_data/ai_providers/SECRETS.md`:

```markdown
# Secret Masking Strategy

## Automatic Masking

The [`SecretMasker`](../../../lib/aurumentation/masker.py) automatically masks:

1. **API Keys in Headers:**
   - `Authorization: Bearer ***MASKED***`
   - `X-API-Key: ***MASKED***`

2. **API Keys in URLs:**
   - `?api_key=***MASKED***`

3. **Pattern-Based Keys:**
   - Any key matching: `api_key`, `token`, `auth`, `password`, `secret`
   - Case-insensitive matching

## Provider-Specific Secrets

### BasicOpenAIProvider
- `OPENAI_API_KEY` - Masked in Authorization header

### YcOpenaiProvider
- `YC_API_KEY` - Masked in Authorization header
- `YC_FOLDER_ID` - **CRITICAL:** Must be explicitly added to secrets list
  - Appears in URLs: `gpt://***MASKED***/yandexgpt/latest`
  - Appears in request bodies

### OpenrouterProvider
- `OPENROUTER_API_KEY` - Masked in Authorization header

### YcSdkProvider
- `YC_SDK_API_KEY` - Not applicable (SDK-level mocking)
- SDK responses are captured, not HTTP traffic

## What NOT to Mask

- AI-generated text (it's the test data)
- User messages (they're test inputs)
- Model names and versions
- Token counts and usage statistics
- Error messages (needed for debugging)
```

**Validation:** File exists and documents all providers.

### 3.4 Create Provider Base Class

**Task 1.4:** Create `tests/golden_data/ai_providers/provider.py`

This file will provide the `GoldenDataProvider` class for tests to use:

```python
"""Golden Data Provider for AI provider testing.

This module provides a specialized provider for loading and replaying
golden data scenarios for AI provider tests.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from lib.aurumentation.provider import GoldenDataProvider as BaseProvider
from lib.aurumentation.replayer import GoldenDataReplayer


class AIGoldenDataProvider(BaseProvider):
    """Provider for AI provider golden data scenarios.
    
    This class extends the base GoldenDataProvider with AI-specific
    functionality and convenience methods.
    """
    
    def __init__(self, provider_name: str):
        """Initialize the AI golden data provider.
        
        Args:
            provider_name: Name of the provider directory (e.g., 'basic_openai')
        """
        base_path = Path(__file__).parent / provider_name
        super().__init__(str(base_path))
        self.provider_name = provider_name
        
    @asynccontextmanager
    async def patchClient(self, scenario_name: Optional[str] = None):
        """Patch httpx.AsyncClient to replay golden data.
        
        Args:
            scenario_name: Name of the scenario to load (without .json extension).
                          If None, loads all scenarios.
        
        Yields:
            GoldenDataReplayer instance
        """
        # Load scenario(s)
        if scenario_name:
            self.loadScenario(f"{scenario_name}.json", Path(self.goldenDataDirs[0]))
        else:
            self.loadAllScenarios()
        
        # Get scenario
        scenario = self.getScenario(scenario_name)
        
        # Create and use replayer
        replayer = GoldenDataReplayer(scenario)
        async with replayer:
            yield replayer
```

**Validation:** File can be imported without errors.

---

## 4. Phase 2: HTTP-Based Providers

**Estimated Time:** 8-12 hours  
**Dependencies:** Phase 1 complete  
**Risk Level:** Medium

### 4.1 BasicOpenAIProvider Implementation

#### Task 2.1.1: Create Scenario Definitions

Create `tests/golden_data/ai_providers/scenarios/basic_openai_scenarios.json`:

```json
[
  {
    "name": "basic_text_generation",
    "description": "Basic text generation with single user message",
    "module": "lib.ai.providers.basic_openai_provider",
    "class": "BasicOpenAIProvider",
    "method": "generateText",
    "init_kwargs": {
      "api_key": "${OPENAI_API_KEY}",
      "models": {
        "gpt-3.5-turbo": {
          "model_id": "gpt-3.5-turbo",
          "model_version": "latest",
          "temperature": 0.7,
          "context_size": 4096,
          "support_text": true
        }
      }
    },
    "kwargs": {
      "model_name": "gpt-3.5-turbo",
      "messages": [
        {
          "role": "user",
          "content": "What is 2+2? Answer with just the number."
        }
      ]
    }
  },
  {
    "name": "multi_turn_conversation",
    "description": "Multi-turn conversation with context",
    "module": "lib.ai.providers.basic_openai_provider",
    "class": "BasicOpenAIProvider",
    "method": "generateText",
    "init_kwargs": {
      "api_key": "${OPENAI_API_KEY}",
      "models": {
        "gpt-3.5-turbo": {
          "model_id": "gpt-3.5-turbo",
          "model_version": "latest",
          "temperature": 0.7,
          "context_size": 4096,
          "support_text": true
        }
      }
    },
    "kwargs": {
      "model_name": "gpt-3.5-turbo",
      "messages": [
        {
          "role": "user",
          "content": "My name is Alice"
        },
        {
          "role": "assistant",
          "content": "Hello Alice! Nice to meet you."
        },
        {
          "role": "user",
          "content": "What's my name?"
        }
      ]
    }
  },
  {
    "name": "error_invalid_model",
    "description": "Handle invalid model name error",
    "module": "lib.ai.providers.basic_openai_provider",
    "class": "BasicOpenAIProvider",
    "method": "generateText",
    "init_kwargs": {
      "api_key": "${OPENAI_API_KEY}",
      "models": {
        "nonexistent-model": {
          "model_id": "nonexistent-model-xyz-123",
          "model_version": "latest",
          "temperature": 0.7,
          "context_size": 4096,
          "support_text": true
        }
      }
    },
    "kwargs": {
      "model_name": "nonexistent-model",
      "messages": [
        {
          "role": "user",
          "content": "Hello"
        }
      ]
    }
  }
]
```

**Complexity:** Medium  
**Validation:** JSON is valid and can be parsed.

#### Task 2.1.2: Modify Collector Script

The existing [`lib/aurumentation/collector.py`](../lib/aurumentation/collector.py) already supports the scenario format. We just need to use it correctly.

Create a convenience script `tests/golden_data/ai_providers/collect_basic_openai.sh`:

```bash
#!/bin/bash
# Collect golden data for BasicOpenAIProvider

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Run collector
./venv/bin/python3 -m lib.aurumentation.collector \
    --input tests/golden_data/ai_providers/scenarios/basic_openai_scenarios.json \
    --output tests/golden_data/ai_providers/basic_openai/ \
    --secrets "${OPENAI_API_KEY}"

echo "Golden data collection complete for BasicOpenAIProvider"
echo "Files created in: tests/golden_data/ai_providers/basic_openai/"
```

**Complexity:** Low  
**Validation:** Script runs without errors (requires API key).

#### Task 2.1.3: Create Test File

Create `tests/golden_data/ai_providers/test_basic_openai_provider.py`:

```python
"""Golden data tests for BasicOpenAIProvider, dood!"""

import pytest

from lib.ai.models import ModelMessage
from lib.ai.providers.basic_openai_provider import BasicOpenAIProvider
from tests.golden_data.ai_providers.provider import AIGoldenDataProvider


@pytest.mark.asyncio
async def test_basic_text_generation():
    """Test basic text generation using golden data, dood!"""
    provider_data = AIGoldenDataProvider("basic_openai")
    
    async with provider_data.patchClient("basic_text_generation"):
        # Create provider instance (fake API key is fine, we're using golden data)
        provider = BasicOpenAIProvider({
            "api_key": "fake-key-for-testing",
            "models": {
                "gpt-3.5-turbo": {
                    "model_id": "gpt-3.5-turbo",
                    "model_version": "latest",
                    "temperature": 0.7,
                    "context_size": 4096,
                    "support_text": True
                }
            }
        })
        
        # Get model
        model = provider.getModel("gpt-3.5-turbo")
        
        # Generate text
        messages = [ModelMessage(role="user", content="What is 2+2? Answer with just the number.")]
        result = await model.generateText(messages)
        
        # Verify result
        assert result is not None
        assert result.text is not None
        assert "4" in result.text
        assert result.status.value >= 0


@pytest.mark.asyncio
async def test_multi_turn_conversation():
    """Test multi-turn conversation using golden data, dood!"""
    provider_data = AIGoldenDataProvider("basic_openai")
    
    async with provider_data.patchClient("multi_turn_conversation"):
        provider = BasicOpenAIProvider({
            "api_key": "fake-key-for-testing",
            "models": {
                "gpt-3.5-turbo": {
                    "model_id": "gpt-3.5-turbo",
                    "model_version": "latest",
                    "temperature": 0.7,
                    "context_size": 4096,
                    "support_text": True
                }
            }
        })
        
        model = provider.getModel("gpt-3.5-turbo")
        
        messages = [
            ModelMessage(role="user", content="My name is Alice"),
            ModelMessage(role="assistant", content="Hello Alice! Nice to meet you."),
            ModelMessage(role="user", content="What's my name?")
        ]
        result = await model.generateText(messages)
        
        assert result is not None
        assert result.text is not None
        assert "Alice" in result.text


@pytest.mark.asyncio
async def test_error_invalid_model():
    """Test error handling for invalid model, dood!"""
    provider_data = AIGoldenDataProvider("basic_openai")
    
    async with provider_data.patchClient("error_invalid_model"):
        provider = BasicOpenAIProvider({
            "api_key": "fake-key-for-testing",
            "models": {
                "nonexistent-model": {
                    "model_id": "nonexistent-model-xyz-123",
                    "model_version": "latest",
                    "temperature": 0.7,
                    "context_size": 4096,
                    "support_text": True
                }
            }
        })
        
        model = provider.getModel("nonexistent-model")
        
        messages = [ModelMessage(role="user", content="Hello")]
        
        # Should raise an exception
        with pytest.raises(Exception):
            await model.generateText(messages)
```

**Complexity:** Medium  
**Validation:** Tests can be discovered by pytest (may fail until golden data is collected).

### 4.2 YcOpenaiProvider Implementation

#### Task 2.2.1: Create Scenario Definitions

Create `tests/golden_data/ai_providers/scenarios/yc_openai_scenarios.json`:

```json
[
  {
    "name": "basic_text_generation",
    "description": "Basic text generation with YC OpenAI",
    "module": "lib.ai.providers.yc_openai_provider",
    "class": "YcOpenaiProvider",
    "method": "generateText",
    "init_kwargs": {
      "api_key": "${YC_API_KEY}",
      "folder_id": "${YC_FOLDER_ID}",
      "models": {
        "yandexgpt": {
          "model_id": "yandexgpt",
          "model_version": "latest",
          "temperature": 0.6,
          "context_size": 8000,
          "support_text": true
        }
      }
    },
    "kwargs": {
      "model_name": "yandexgpt",
      "messages": [
        {
          "role": "user",
          "content": "Сколько будет 2+2? Ответь только числом."
        }
      ]
    }
  },
  {
    "name": "folder_id_validation",
    "description": "Verify folder_id is included in requests",
    "module": "lib.ai.providers.yc_openai_provider",
    "class": "YcOpenaiProvider",
    "method": "generateText",
    "init_kwargs": {
      "api_key": "${YC_API_KEY}",
      "folder_id": "${YC_FOLDER_ID}",
      "models": {
        "yandexgpt": {
          "model_id": "yandexgpt",
          "model_version": "latest",
          "temperature": 0.6,
          "context_size": 8000,
          "support_text": true
        }
      }
    },
    "kwargs": {
      "model_name": "yandexgpt",
      "messages": [
        {
          "role": "user",
          "content": "Привет"
        }
      ]
    }
  },
  {
    "name": "yc_model_format",
    "description": "Test gpt:// URL format",
    "module": "lib.ai.providers.yc_openai_provider",
    "class": "YcOpenaiProvider",
    "method": "generateText",
    "init_kwargs": {
      "api_key": "${YC_API_KEY}",
      "folder_id": "${YC_FOLDER_ID}",
      "models": {
        "yandexgpt-lite": {
          "model_id": "yandexgpt-lite",
          "model_version": "latest",
          "temperature": 0.6,
          "context_size": 8000,
          "support_text": true
        }
      }
    },
    "kwargs": {
      "model_name": "yandexgpt-lite",
      "messages": [
        {
          "role": "user",
          "content": "Тест"
        }
      ]
    }
  }
]
```

**Complexity:** Medium  
**Validation:** JSON is valid.

#### Task 2.2.2: Create Collection Script

Create `tests/golden_data/ai_providers/collect_yc_openai.sh`:

```bash
#!/bin/bash
# Collect golden data for YcOpenaiProvider

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# IMPORTANT: Include folder_id in secrets list!
./venv/bin/python3 -m lib.aurumentation.collector \
    --input tests/golden_data/ai_providers/scenarios/yc_openai_scenarios.json \
    --output tests/golden_data/ai_providers/yc_openai/ \
    --secrets "${YC_API_KEY},${YC_FOLDER_ID}"

echo "Golden data collection complete for YcOpenaiProvider"
echo "Files created in: tests/golden_data/ai_providers/yc_openai/"
```

**Complexity:** Low  
**Validation:** Script runs without errors.

#### Task 2.2.3: Create Test File

Create `tests/golden_data/ai_providers/test_yc_openai_provider.py`:

```python
"""Golden data tests for YcOpenaiProvider, dood!"""

import pytest

from lib.ai.models import ModelMessage
from lib.ai.providers.yc_openai_provider import YcOpenaiProvider
from tests.golden_data.ai_providers.provider import AIGoldenDataProvider


@pytest.mark.asyncio
async def test_basic_text_generation():
    """Test basic text generation using golden data, dood!"""
    provider_data = AIGoldenDataProvider("yc_openai")
    
    async with provider_data.patchClient("basic_text_generation"):
        provider = YcOpenaiProvider({
            "api_key": "fake-key-for-testing",
            "folder_id": "fake-folder-id",
            "models": {
                "yandexgpt": {
                    "model_id": "yandexgpt",
                    "model_version": "latest",
                    "temperature": 0.6,
                    "context_size": 8000,
                    "support_text": True
                }
            }
        })
        
        model = provider.getModel("yandexgpt")
        
        messages = [ModelMessage(role="user", content="Сколько будет 2+2? Ответь только числом.")]
        result = await model.generateText(messages)
        
        assert result is not None
        assert result.text is not None
        assert "4" in result.text


@pytest.mark.asyncio
async def test_folder_id_validation():
    """Test that folder_id is properly included, dood!"""
    provider_data = AIGoldenDataProvider("yc_openai")
    
    async with provider_data.patchClient("folder_id_validation"):
        provider = YcOpenaiProvider({
            "api_key": "fake-key-for-testing",
            "folder_id": "fake-folder-id",
            "models": {
                "yandexgpt": {
                    "model_id": "yandexgpt",
                    "model_version": "latest",
                    "temperature": 0.6,
                    "context_size": 8000,
                    "support_text": True
                }
            }
        })
        
        model = provider.getModel("yandexgpt")
        
        messages = [ModelMessage(role="user", content="Привет")]
        result = await model.generateText(messages)
        
        assert result is not None
        assert result.text is not None


@pytest.mark.asyncio
async def test_yc_model_format():
    """Test gpt:// URL format, dood!"""
    provider_data = AIGoldenDataProvider("yc_openai")
    
    async with provider_data.patchClient("yc_model_format"):
        provider = YcOpenaiProvider({
            "api_key": "fake-key-for-testing",
            "folder_id": "fake-folder-id",
            "models": {
                "yandexgpt-lite": {
                    "model_id": "yandexgpt-lite",
                    "model_version": "latest",
                    "temperature": 0.6,
                    "context_size": 8000,
                    "support_text": True
                }
            }
        })
        
        model = provider.getModel("yandexgpt-lite")
        
        messages = [ModelMessage(role="user", content="Тест")]
        result = await model.generateText(messages)
        
        assert result is not None
        assert result.text is not None
```

**Complexity:** Medium  
**Validation:** Tests can be discovered by pytest.

### 4.3 OpenrouterProvider Implementation

#### Task 2.3.1: Create Scenario Definitions

Create `tests/golden_data/ai_providers/scenarios/openrouter_scenarios.json`:

```json
[
  {
    "name": "basic_text_generation",
    "description": "Basic text generation via OpenRouter",
    "module": "lib.ai.providers.openrouter_provider",
    "class": "OpenrouterProvider",
    "method": "generateText",
    "init_kwargs": {
      "api_key": "${OPENROUTER_API_KEY}",
      "models": {
        "meta-llama/llama-3.2-3b-instruct:free": {
          "model_id": "meta-llama/llama-3.2-3b-instruct:free",
          "model_version": "latest",
          "temperature": 0.7,
          "context_size": 4096,
          "support_text": true
        }
      }
    },
    "kwargs": {
      "model_name": "meta-llama/llama-3.2-3b-instruct:free",
      "messages": [
        {
          "role": "user",
          "content": "What is 2+2? Answer with just the number."
        }
      ]
    }
  },
  {
    "name": "custom_headers",
    "description": "Verify HTTP-Referer and X-Title headers",
    "module": "lib.ai.providers.openrouter_provider",
    "class": "OpenrouterProvider",
    "method": "generateText",
    "init_kwargs": {
      "api_key": "${OPENROUTER_API_KEY}",
      "models": {
        "meta-llama/llama-3.2-3b-instruct:free": {
          "model_id": "meta-llama/llama-3.2-3b-instruct:free",
          "model_version": "latest",
          "temperature": 0.7,
          "context_size": 4096,
          "support_text": true
        }
      }
    },
    "kwargs": {
      "model_name": "meta-llama/llama-3.2-3b-instruct:free",
      "messages": [
        {
          "role": "user",
          "content": "Hello"
        }
      ]
    }
  },
  {
    "name": "different_model_provider",
    "description": "Test different model through OpenRouter",
    "module": "lib.ai.providers.openrouter_provider",
    "class": "OpenrouterProvider",
    "method": "generateText",
    "init_kwargs": {
      "api_key": "${OPENROUTER_API_KEY}",
      "models": {
        "google/gemini-flash-1.5": {
          "model_id": "google/gemini-flash-1.5",
          "model_version": "latest",
          "temperature": 0.7,
          "context_size": 8000,
          "support_text": true
        }
      }
    },
    "kwargs": {
      "model_name": "google/gemini-flash-1.5",
      "messages": [
        {
          "role": "user",
          "content": "Say hello"
        }
      ]
    }
  }
]
```

**Complexity:** Medium  
**Validation:** JSON is valid.

#### Task 2.3.2: Create Collection Script

Create `tests/golden_data/ai_providers/collect_openrouter.sh`:

```bash
#!/bin/bash
# Collect golden data for OpenrouterProvider

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

./venv/bin/python3 -m lib.aurumentation.collector \
    --input tests/golden_data/ai_providers/scenarios/openrouter_scenarios.json \
    --output tests/golden_data/ai_providers/openrouter/ \
    --secrets "${OPENROUTER_API_KEY}"

echo "Golden data collection complete for OpenrouterProvider"
echo "Files created in: tests/golden_data/ai_providers/openrouter/"
```

**Complexity:** Low  
**Validation:** Script runs without errors.

#### Task 2.3.3: Create Test File

Create `tests/golden_data/ai_providers/test_openrouter_provider.py`:

```python
"""Golden data tests for OpenrouterProvider, dood!"""

import pytest

from lib.ai.models import ModelMessage
from lib.ai.providers.openrouter_provider import OpenrouterProvider
from tests.golden_data.ai_providers.provider import AIGoldenDataProvider


@pytest.mark.asyncio
async def test_basic_text_generation():
    """Test basic text generation using golden data, dood!"""
    provider_data = AIGoldenDataProvider("openrouter")
    
    async with provider_data.patchClient("basic_text_generation"):
        provider = OpenrouterProvider({
            "api_key": "fake-key-for-testing",
            "models": {
                "meta-llama/llama-3.2-3b-instruct:free": {
                    "model_id": "meta-llama/llama-3.2-3b-instruct:free",
                    "model_version": "latest",
                    "temperature": 0.7,
                    "context_size": 4096,
                    "
support_text": True
                }
            }
        })
        
        model = provider.getModel("meta-llama/llama-3.2-3b-instruct:free")
        
        messages = [ModelMessage(role="user", content="What is 2+2? Answer with just the number.")]
        result = await model.generateText(messages)
        
        assert result is not None
        assert result.text is not None
        assert "4" in result.text


@pytest.mark.asyncio
async def test_custom_headers():
    """Test that custom headers are included, dood!"""
    provider_data = AIGoldenDataProvider("openrouter")
    
    async with provider_data.patchClient("custom_headers"):
        provider = OpenrouterProvider({
            "api_key": "fake-key-for-testing",
            "models": {
                "meta-llama/llama-3.2-3b-instruct:free": {
                    "model_id": "meta-llama/llama-3.2-3b-instruct:free",
                    "model_version": "latest",
                    "temperature": 0.7,
                    "context_size": 4096,
                    "support_text": True
                }
            }
        })
        
        model = provider.getModel("meta-llama/llama-3.2-3b-instruct:free")
        
        messages = [ModelMessage(role="user", content="Hello")]
        result = await model.generateText(messages)
        
        assert result is not None
        assert result.text is not None


@pytest.mark.asyncio
async def test_different_model_provider():
    """Test different model through OpenRouter, dood!"""
    provider_data = AIGoldenDataProvider("openrouter")
    
    async with provider_data.patchClient("different_model_provider"):
        provider = OpenrouterProvider({
            "api_key": "fake-key-for-testing",
            "models": {
                "google/gemini-flash-1.5": {
                    "model_id": "google/gemini-flash-1.5",
                    "model_version": "latest",
                    "temperature": 0.7,
                    "context_size": 8000,
                    "support_text": True
                }
            }
        })
        
        model = provider.getModel("google/gemini-flash-1.5")
        
        messages = [ModelMessage(role="user", content="Say hello")]
        result = await model.generateText(messages)
        
        assert result is not None
        assert result.text is not None
```

**Complexity:** Medium  
**Validation:** Tests can be discovered by pytest.

---

## 5. Phase 3: YcSdkProvider Special Handling

**Estimated Time:** 6-8 hours  
**Dependencies:** Phase 1 complete  
**Risk Level:** High (SDK-level mocking is complex)

### 5.1 SDK-Level Mocking Approach

YcSdkProvider uses the Yandex Cloud ML SDK directly, which does NOT use httpx for HTTP communication. Therefore, we cannot use the standard HTTP recording/replay approach. Instead, we'll use SDK-level mocking.

#### Task 3.1.1: Create SDK Response Collector

Create `tests/golden_data/ai_providers/collect_yc_sdk.py`:

```python
"""Collector for YcSdkProvider golden data.

This collector is special because YcSdkProvider uses the Yandex Cloud SDK
directly, not httpx. We collect SDK responses and save them for mocking.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from lib import utils
from lib.ai.models import ModelMessage
from lib.ai.providers.yc_sdk_provider import YcSdkProvider


def serializeSdkResponse(response: Any) -> Dict[str, Any]:
    """Serialize SDK response to JSON-compatible format.
    
    Args:
        response: SDK response object
        
    Returns:
        JSON-compatible dictionary
    """
    # Extract relevant data from SDK response
    # This will vary based on the actual SDK response structure
    result = {
        "alternatives": [],
        "usage": {},
        "model_version": ""
    }
    
    # Handle text generation response
    if hasattr(response, 'alternatives'):
        for alt in response.alternatives:
            result["alternatives"].append({
                "message": {
                    "role": alt.message.role if hasattr(alt.message, 'role') else "assistant",
                    "text": alt.message.text if hasattr(alt.message, 'text') else ""
                },
                "status": str(alt.status) if hasattr(alt, 'status') else "FINAL"
            })
    
    # Handle usage information
    if hasattr(response, 'usage'):
        result["usage"] = {
            "input_text_tokens": str(response.usage.input_text_tokens),
            "completion_tokens": str(response.usage.completion_tokens),
            "total_tokens": str(response.usage.total_tokens)
        }
    
    # Handle model version
    if hasattr(response, 'model_version'):
        result["model_version"] = response.model_version
    
    return result


async def collectScenario(scenario: Dict[str, Any], outputDir: Path) -> None:
    """Collect golden data for a single YcSdk scenario.
    
    Args:
        scenario: Scenario definition
        outputDir: Directory to save golden data
    """
    print(f"Collecting: {scenario['description']}")
    
    # Extract scenario details
    name = scenario["name"]
    method = scenario["method"]
    initKwargs = scenario["init_kwargs"]
    kwargs = scenario["kwargs"]
    
    # Substitute environment variables
    utils.load_dotenv()
    for key, value in initKwargs.items():
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            varName = value[2:-1]
            initKwargs[key] = os.getenv(varName, value)
    
    # Create provider
    provider = YcSdkProvider(initKwargs)
    
    # Get model
    modelName = kwargs.get("model_name", list(initKwargs["models"].keys())[0])
    model = provider.getModel(modelName)
    
    # Execute method
    if method == "generateText":
        messages = [ModelMessage(**msg) for msg in kwargs["messages"]]
        response = await model.generateText(messages)
    elif method == "generateImage":
        response = await model.generateImage(
            prompt=kwargs["prompt"],
            widthRatio=kwargs.get("width_ratio", 1),
            heightRatio=kwargs.get("height_ratio", 1)
        )
    else:
        raise ValueError(f"Unknown method: {method}")
    
    # Serialize response
    sdkResponse = serializeSdkResponse(response._raw_response if hasattr(response, '_raw_response') else response)
    
    # Create golden data
    goldenData = {
        "metadata": {
            "name": name,
            "description": scenario["description"],
            "provider": "YcSdkProvider",
            "model": modelName,
            "method": method,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sdk_version": "yandex-cloud-ml-sdk"
        },
        "sdk_response": sdkResponse,
        "expected_result": {
            "text": response.text if hasattr(response, 'text') else None,
            "status": response.status.value if hasattr(response, 'status') else 0,
            "image_data": response.imageData if hasattr(response, 'imageData') else None
        }
    }
    
    # Save to file
    outputFile = outputDir / f"{name}.json"
    with open(outputFile, 'w') as f:
        json.dump(goldenData, f, indent=2)
    
    print(f"Saved: {outputFile}")


async def main():
    """Main collection function."""
    # Load scenarios
    scenariosFile = Path("tests/golden_data/ai_providers/scenarios/yc_sdk_scenarios.json")
    with open(scenariosFile) as f:
        scenarios = json.load(f)
    
    # Create output directory
    outputDir = Path("tests/golden_data/ai_providers/yc_sdk")
    outputDir.mkdir(parents=True, exist_ok=True)
    
    # Collect each scenario
    for scenario in scenarios:
        try:
            await collectScenario(scenario, outputDir)
        except Exception as e:
            print(f"Error collecting {scenario['name']}: {e}")
            import traceback
            traceback.print_exc()
    
    print("\nCollection complete!")


if __name__ == "__main__":
    asyncio.run(main())
```

**Complexity:** High  
**Validation:** Script runs and creates JSON files.

#### Task 3.1.2: Create Scenario Definitions

Create `tests/golden_data/ai_providers/scenarios/yc_sdk_scenarios.json`:

```json
[
  {
    "name": "sdk_text_generation",
    "description": "Generate text using YC SDK",
    "method": "generateText",
    "init_kwargs": {
      "api_key": "${YC_SDK_API_KEY}",
      "models": {
        "yandexgpt": {
          "model_id": "yandexgpt",
          "model_version": "latest",
          "temperature": 0.6,
          "context_size": 8000,
          "support_text": true
        }
      }
    },
    "kwargs": {
      "model_name": "yandexgpt",
      "messages": [
        {
          "role": "user",
          "content": "Привет! Как дела?"
        }
      ]
    }
  },
  {
    "name": "sdk_text_generation_multi_turn",
    "description": "Multi-turn conversation using YC SDK",
    "method": "generateText",
    "init_kwargs": {
      "api_key": "${YC_SDK_API_KEY}",
      "models": {
        "yandexgpt": {
          "model_id": "yandexgpt",
          "model_version": "latest",
          "temperature": 0.6,
          "context_size": 8000,
          "support_text": true
        }
      }
    },
    "kwargs": {
      "model_name": "yandexgpt",
      "messages": [
        {
          "role": "user",
          "content": "Меня зовут Алиса"
        },
        {
          "role": "assistant",
          "content": "Здравствуйте, Алиса!"
        },
        {
          "role": "user",
          "content": "Как меня зовут?"
        }
      ]
    }
  },
  {
    "name": "sdk_image_generation",
    "description": "Generate image using YC SDK",
    "method": "generateImage",
    "init_kwargs": {
      "api_key": "${YC_SDK_API_KEY}",
      "models": {
        "yandex-art": {
          "model_id": "yandex-art",
          "model_version": "latest",
          "context_size": 0,
          "support_images": true,
          "width_ratio": 1,
          "height_ratio": 1
        }
      }
    },
    "kwargs": {
      "model_name": "yandex-art",
      "prompt": "A beautiful sunset over mountains",
      "width_ratio": 1,
      "height_ratio": 1
    }
  }
]
```

**Complexity:** Medium  
**Validation:** JSON is valid.

#### Task 3.1.3: Create Test File with SDK Mocking

Create `tests/golden_data/ai_providers/test_yc_sdk_provider.py`:

```python
"""Golden data tests for YcSdkProvider using SDK-level mocking, dood!"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.ai.models import ModelMessage, ModelResultStatus
from lib.ai.providers.yc_sdk_provider import YcSdkProvider


def loadGoldenData(scenarioName: str) -> dict:
    """Load golden data for a scenario.
    
    Args:
        scenarioName: Name of the scenario (without .json extension)
        
    Returns:
        Golden data dictionary
    """
    goldenFile = Path(__file__).parent / "yc_sdk" / f"{scenarioName}.json"
    with open(goldenFile) as f:
        return json.load(f)


def createMockSdkResult(goldenData: dict):
    """Create a mock SDK result from golden data.
    
    Args:
        goldenData: Golden data dictionary
        
    Returns:
        Mock SDK result object
    """
    mockResult = MagicMock()
    
    # Mock alternatives
    mockResult.alternatives = []
    for alt in goldenData["sdk_response"]["alternatives"]:
        mockAlt = MagicMock()
        mockAlt.message = MagicMock()
        mockAlt.message.role = alt["message"]["role"]
        mockAlt.message.text = alt["message"]["text"]
        mockAlt.status = alt["status"]
        mockResult.alternatives.append(mockAlt)
    
    # Mock usage
    mockResult.usage = MagicMock()
    usage = goldenData["sdk_response"]["usage"]
    mockResult.usage.input_text_tokens = usage.get("input_text_tokens", "0")
    mockResult.usage.completion_tokens = usage.get("completion_tokens", "0")
    mockResult.usage.total_tokens = usage.get("total_tokens", "0")
    
    # Mock model version
    mockResult.model_version = goldenData["sdk_response"].get("model_version", "")
    
    return mockResult


@pytest.mark.asyncio
async def test_sdk_text_generation():
    """Test text generation using SDK-level mocking, dood!"""
    goldenData = loadGoldenData("sdk_text_generation")
    mockResult = createMockSdkResult(goldenData)
    
    with patch("lib.ai.providers.yc_sdk_provider.YCloudML") as mockSdk:
        # Setup mock
        mockSdk.return_value.models.completions.return_value.configure.return_value.run = AsyncMock(
            return_value=mockResult
        )
        
        # Create provider
        provider = YcSdkProvider({
            "api_key": "fake-key-for-testing",
            "models": {
                "yandexgpt": {
                    "model_id": "yandexgpt",
                    "model_version": "latest",
                    "temperature": 0.6,
                    "context_size": 8000,
                    "support_text": True
                }
            }
        })
        
        model = provider.getModel("yandexgpt")
        
        messages = [ModelMessage(role="user", content="Привет! Как дела?")]
        result = await model.generateText(messages)
        
        # Verify result matches golden data
        expected = goldenData["expected_result"]
        assert result is not None
        assert result.text == expected["text"]
        assert result.status == ModelResultStatus(expected["status"])


@pytest.mark.asyncio
async def test_sdk_text_generation_multi_turn():
    """Test multi-turn conversation using SDK-level mocking, dood!"""
    goldenData = loadGoldenData("sdk_text_generation_multi_turn")
    mockResult = createMockSdkResult(goldenData)
    
    with patch("lib.ai.providers.yc_sdk_provider.YCloudML") as mockSdk:
        mockSdk.return_value.models.completions.return_value.configure.return_value.run = AsyncMock(
            return_value=mockResult
        )
        
        provider = YcSdkProvider({
            "api_key": "fake-key-for-testing",
            "models": {
                "yandexgpt": {
                    "model_id": "yandexgpt",
                    "model_version": "latest",
                    "temperature": 0.6,
                    "context_size": 8000,
                    "support_text": True
                }
            }
        })
        
        model = provider.getModel("yandexgpt")
        
        messages = [
            ModelMessage(role="user", content="Меня зовут Алиса"),
            ModelMessage(role="assistant", content="Здравствуйте, Алиса!"),
            ModelMessage(role="user", content="Как меня зовут?")
        ]
        result = await model.generateText(messages)
        
        expected = goldenData["expected_result"]
        assert result is not None
        assert result.text == expected["text"]
        assert "Алиса" in result.text


@pytest.mark.asyncio
async def test_sdk_image_generation():
    """Test image generation using SDK-level mocking, dood!"""
    goldenData = loadGoldenData("sdk_image_generation")
    
    # Create mock for image generation
    mockResult = MagicMock()
    mockResult.image_data = goldenData["expected_result"]["image_data"]
    
    with patch("lib.ai.providers.yc_sdk_provider.YCloudML") as mockSdk:
        mockSdk.return_value.models.image_generation.return_value.configure.return_value.run = AsyncMock(
            return_value=mockResult
        )
        
        provider = YcSdkProvider({
            "api_key": "fake-key-for-testing",
            "models": {
                "yandex-art": {
                    "model_id": "yandex-art",
                    "model_version": "latest",
                    "context_size": 0,
                    "support_images": True,
                    "width_ratio": 1,
                    "height_ratio": 1
                }
            }
        })
        
        model = provider.getModel("yandex-art")
        
        result = await model.generateImage(
            prompt="A beautiful sunset over mountains",
            widthRatio=1,
            heightRatio=1
        )
        
        expected = goldenData["expected_result"]
        assert result is not None
        assert result.imageData == expected["image_data"]
```

**Complexity:** High  
**Validation:** Tests can be discovered by pytest.

#### Task 3.1.4: Create Collection Script

Create `tests/golden_data/ai_providers/collect_yc_sdk.sh`:

```bash
#!/bin/bash
# Collect golden data for YcSdkProvider

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Run custom collector for SDK
./venv/bin/python3 tests/golden_data/ai_providers/collect_yc_sdk.py

echo "Golden data collection complete for YcSdkProvider"
echo "Files created in: tests/golden_data/ai_providers/yc_sdk/"
```

**Complexity:** Low  
**Validation:** Script runs without errors.

---

## 6. Phase 4: Integration and Validation

**Estimated Time:** 4-6 hours  
**Dependencies:** Phases 2 and 3 complete  
**Risk Level:** Low

### 6.1 Running All Tests

#### Task 4.1.1: Create Master Test Runner

Create `tests/golden_data/ai_providers/run_all_tests.sh`:

```bash
#!/bin/bash
# Run all AI provider golden data tests

set -e

echo "Running AI Provider Golden Data Tests..."
echo "========================================"
echo ""

# Run tests for each provider
echo "Testing BasicOpenAIProvider..."
./venv/bin/python3 -m pytest tests/golden_data/ai_providers/test_basic_openai_provider.py -v

echo ""
echo "Testing YcOpenaiProvider..."
./venv/bin/python3 -m pytest tests/golden_data/ai_providers/test_yc_openai_provider.py -v

echo ""
echo "Testing OpenrouterProvider..."
./venv/bin/python3 -m pytest tests/golden_data/ai_providers/test_openrouter_provider.py -v

echo ""
echo "Testing YcSdkProvider..."
./venv/bin/python3 -m pytest tests/golden_data/ai_providers/test_yc_sdk_provider.py -v

echo ""
echo "========================================"
echo "All tests complete!"
```

**Complexity:** Low  
**Validation:** Script runs all tests.

### 6.2 Validating Golden Data

#### Task 4.2.1: Create Validation Script

Create `tests/golden_data/ai_providers/validate_golden_data.py`:

```python
"""Validate golden data files for completeness and correctness."""

import json
from pathlib import Path
from typing import List


def validateGoldenDataFile(filepath: Path) -> List[str]:
    """Validate a single golden data file.
    
    Args:
        filepath: Path to golden data file
        
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    
    try:
        with open(filepath) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]
    except Exception as e:
        return [f"Error reading file: {e}"]
    
    # Check required fields
    if "metadata" not in data:
        errors.append("Missing 'metadata' field")
    else:
        metadata = data["metadata"]
        required_metadata = ["name", "description", "created_at"]
        for field in required_metadata:
            if field not in metadata:
                errors.append(f"Missing metadata field: {field}")
    
    # Check for recordings or sdk_response
    if "recordings" not in data and "sdk_response" not in data:
        errors.append("Missing 'recordings' or 'sdk_response' field")
    
    # Check for masked secrets
    content = json.dumps(data)
    suspicious_patterns = [
        "sk-",  # OpenAI keys
        "AQVN",  # YC keys
        "sk-or-v1-",  # OpenRouter keys
    ]
    for pattern in suspicious_patterns:
        if pattern in content and "***MASKED***" not in content:
            errors.append(f"Possible unmasked secret: {pattern}")
    
    return errors


def main():
    """Validate all golden data files."""
    baseDir = Path(__file__).parent
    providers = ["basic_openai", "yc_openai", "openrouter", "yc_sdk"]
    
    allValid = True
    
    for provider in providers:
        providerDir = baseDir / provider
        if not providerDir.exists():
            print(f"⚠️  Provider directory not found: {provider}")
            continue
        
        print(f"\nValidating {provider}...")
        print("=" * 50)
        
        jsonFiles = list(providerDir.glob("*.json"))
        if not jsonFiles:
            print(f"⚠️  No golden data files found")
            continue
        
        for filepath in jsonFiles:
            errors = validateGoldenDataFile(filepath)
            if errors:
                allValid = False
                print(f"❌ {filepath.name}")
                for error in errors:
                    print(f"   - {error}")
            else:
                print(f"✅ {filepath.name}")
    
    print("\n" + "=" * 50)
    if allValid:
        print("✅ All golden data files are valid!")
        return 0
    else:
        print("❌ Some golden data files have errors")
        return 1


if __name__ == "__main__":
    exit(main())
```

**Complexity:** Medium  
**Validation:** Script runs and reports validation status.

### 6.3 CI/CD Integration

#### Task 4.3.1: Update GitHub Actions Workflow

Add to `.github/workflows/test.yml` (or create if it doesn't exist):

```yaml
name: Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main, develop ]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.direct.txt
    
    - name: Run unit tests
      run: |
        python -m pytest tests/ -v --ignore=tests/golden_data
    
    - name: Run AI provider golden data tests
      run: |
        python -m pytest tests/golden_data/ai_providers/ -v
    
    - name: Validate golden data
      run: |
        python tests/golden_data/ai_providers/validate_golden_data.py
```

**Complexity:** Low  
**Validation:** Workflow runs successfully in CI.

### 6.4 Documentation Updates

#### Task 4.4.1: Create User Guide

Create `tests/golden_data/ai_providers/README.md`:

```markdown
# AI Provider Golden Data Tests

This directory contains golden data tests for AI provider integrations.

## Overview

Golden data testing allows us to test AI providers without making real API calls. We record HTTP traffic (or SDK responses) once, then replay them during tests.

## Benefits

- ✅ **No API costs** - Tests don't make real API calls
- ✅ **Fast execution** - No network latency
- ✅ **Deterministic** - Same results every time
- ✅ **Offline development** - Work without internet
- ✅ **No credentials needed** - Tests run without API keys

## Directory Structure

```
tests/golden_data/ai_providers/
├── scenarios/              # Scenario definitions for collection
│   ├── basic_openai_scenarios.json
│   ├── yc_openai_scenarios.json
│   ├── openrouter_scenarios.json
│   └── yc_sdk_scenarios.json
├── basic_openai/          # Golden data for BasicOpenAIProvider
├── yc_openai/             # Golden data for YcOpenaiProvider
├── openrouter/            # Golden data for OpenrouterProvider
├── yc_sdk/                # Golden data for YcSdkProvider
├── provider.py            # GoldenDataProvider implementation
├── test_*.py              # Test files
└── collect_*.sh           # Collection scripts
```

## Running Tests

Run all AI provider tests:

```bash
./tests/golden_data/ai_providers/run_all_tests.sh
```

Run tests for a specific provider:

```bash
./venv/bin/python3 -m pytest tests/golden_data/ai_providers/test_basic_openai_provider.py -v
```

## Collecting Golden Data

**⚠️ Only needed when:**
- Adding new test scenarios
- Updating existing scenarios
- Provider API changes

### Prerequisites

1. Create `.env` file with API keys:
```bash
OPENAI_API_KEY=sk-...
YC_API_KEY=AQVN...
YC_FOLDER_ID=b1g...
OPENROUTER_API_KEY=sk-or-v1-...
YC_SDK_API_KEY=AQVN...
```

2. Ensure you have API credits/quota

### Collection Process

Collect for a specific provider:

```bash
# BasicOpenAI
./tests/golden_data/ai_providers/collect_basic_openai.sh

# YcOpenai
./tests/golden_data/ai_providers/collect_yc_openai.sh

# Openrouter
./tests/golden_data/ai_providers/collect_openrouter.sh

# YcSdk (special - uses SDK-level collection)
./tests/golden_data/ai_providers/collect_yc_sdk.sh
```

### After Collection

1. Validate golden data:
```bash
./venv/bin/python3 tests/golden_data/ai_providers/validate_golden_data.py
```

2. Verify secrets are masked:
```bash
grep -r "sk-" tests/golden_data/ai_providers/*/
# Should return no results
```

3. Run tests to ensure they pass:
```bash
./tests/golden_data/ai_providers/run_all_tests.sh
```

4. Commit golden data files:
```bash
git add tests/golden_data/ai_providers/
git commit -m "Update AI provider golden data"
```

## Adding New Scenarios

1. Edit scenario file (e.g., `scenarios/basic_openai_scenarios.json`)
2. Add new scenario object to the array
3. Run collection script
4. Create corresponding test in test file
5. Validate and commit

## Troubleshooting

### Tests fail after collection

- Check that secrets are properly masked
- Verify golden data files are valid JSON
- Ensure test expectations match golden data

### Collection fails

- Verify API keys are correct and have quota
- Check network connectivity
- Review error messages for specific issues

### Secrets not masked

- Ensure secret is in the `--secrets` parameter
- For YC providers, include `YC_FOLDER_ID`
- Re-run collection with correct secrets list

## Provider-Specific Notes

### BasicOpenAIProvider
- Standard OpenAI API
- Uses httpx for HTTP calls
- Secrets: `OPENAI_API_KEY`

### YcOpenaiProvider
- Yandex Cloud OpenAI-compatible API
- Uses httpx for HTTP calls
- Secrets: `YC_API_KEY`, `YC_FOLDER_ID` (important!)
- Folder ID appears in URLs and must be masked

### OpenrouterProvider
- OpenRouter aggregation service
- Uses httpx for HTTP calls
- Secrets: `OPENROUTER_API_KEY`
- Custom headers: `HTTP-Referer`, `X-Title`

### YcSdkProvider
- Yandex Cloud ML SDK (NOT HTTP-based)
- Uses SDK-level mocking
- Special collection script
- Secrets: Not applicable (SDK responses are captured)

## Related Documentation

- Design Document: [`docs/ai-aurumentation-design.md`](../../../docs/ai-aurumentation-design.md)
- Implementation Plan: [`docs/ai-aurumentation-implementation-plan.md`](../../../docs/ai-aurumentation-implementation-plan.md)
- OpenWeatherMap Example: [`docs/reports/OpenWeatherMap-testing-golden.md`](../../../docs/reports/OpenWeatherMap-testing-golden.md)
```

**Complexity:** Low  
**Validation:** Documentation is clear and complete.

---

## 7. Detailed Task Breakdown

### 7.1 Task Summary Table

| Phase | Task | Files Created/Modified | Estimated Time | Complexity | Dependencies |
|-------|------|----------------------|----------------|------------|--------------|
| 1.1 | Create directory structure | 5 directories | 15 min | Low | None |
| 1.2 | Create scenario template | `scenarios/README.md` | 30 min | Low | 1.1 |
| 1.3 | Document secret masking | `SECRETS.md` | 30 min | Low | 1.1 |
| 1.4 | Create provider base class | `provider.py` | 1 hour | Medium | 1.1 |
| 2.1.1 | BasicOpenAI scenarios | `scenarios/basic_open
ai_scenarios.json` | 2 hours | Medium | 1.4 |
| 2.1.2 | BasicOpenAI collection script | `collect_basic_openai.sh` | 30 min | Low | 2.1.1 |
| 2.1.3 | BasicOpenAI tests | `test_basic_openai_provider.py` | 2 hours | Medium | 2.1.1 |
| 2.2.1 | YcOpenai scenarios | `scenarios/yc_openai_scenarios.json` | 2 hours | Medium | 1.4 |
| 2.2.2 | YcOpenai collection script | `collect_yc_openai.sh` | 30 min | Low | 2.2.1 |
| 2.2.3 | YcOpenai tests | `test_yc_openai_provider.py` | 2 hours | Medium | 2.2.1 |
| 2.3.1 | Openrouter scenarios | `scenarios/openrouter_scenarios.json` | 2 hours | Medium | 1.4 |
| 2.3.2 | Openrouter collection script | `collect_openrouter.sh` | 30 min | Low | 2.3.1 |
| 2.3.3 | Openrouter tests | `test_openrouter_provider.py` | 2 hours | Medium | 2.3.1 |
| 3.1.1 | YcSdk collector | `collect_yc_sdk.py` | 3 hours | High | 1.4 |
| 3.1.2 | YcSdk scenarios | `scenarios/yc_sdk_scenarios.json` | 2 hours | Medium | 1.4 |
| 3.1.3 | YcSdk tests | `test_yc_sdk_provider.py` | 3 hours | High | 3.1.1, 3.1.2 |
| 3.1.4 | YcSdk collection script | `collect_yc_sdk.sh` | 30 min | Low | 3.1.1 |
| 4.1.1 | Master test runner | `run_all_tests.sh` | 30 min | Low | 2.*, 3.* |
| 4.2.1 | Validation script | `validate_golden_data.py` | 2 hours | Medium | 2.*, 3.* |
| 4.3.1 | CI/CD workflow | `.github/workflows/test.yml` | 1 hour | Low | 4.1.1, 4.2.1 |
| 4.4.1 | User guide | `README.md` | 2 hours | Low | All |

**Total Estimated Time:** 28-36 hours (3.5-4.5 days)

### 7.2 Critical Path

The critical path for this implementation is:

```
1.1 → 1.4 → 2.1.1 → 2.1.2 → [Collect Data] → 2.1.3 → [Test] → 4.1.1 → 4.4.1
```

This represents the minimum sequence needed to get one provider working end-to-end.

### 7.3 Parallel Work Opportunities

These tasks can be done in parallel after Phase 1:

- **Track A:** BasicOpenAI (2.1.*)
- **Track B:** YcOpenai (2.2.*)
- **Track C:** Openrouter (2.3.*)
- **Track D:** YcSdk (3.1.*)

Each track is independent and can be worked on simultaneously by different developers.

---

## 8. Testing Strategy

### 8.1 Phase Validation Checkpoints

#### After Phase 1:
- ✅ All directories exist
- ✅ `provider.py` can be imported
- ✅ Documentation files are readable

#### After Phase 2 (per provider):
- ✅ Scenario JSON is valid
- ✅ Collection script runs without errors
- ✅ Golden data files are created
- ✅ Secrets are masked in golden data
- ✅ Tests can be discovered by pytest
- ✅ Tests pass using golden data

#### After Phase 3:
- ✅ YcSdk collector runs without errors
- ✅ SDK responses are captured correctly
- ✅ Mock objects match SDK structure
- ✅ Tests pass with mocked SDK

#### After Phase 4:
- ✅ All tests pass together
- ✅ Validation script reports no errors
- ✅ CI/CD pipeline runs successfully
- ✅ Documentation is complete

### 8.2 Test Execution Checklist

Before considering a provider complete:

1. **Collection Phase:**
   - [ ] Scenario file is valid JSON
   - [ ] Environment variables are set
   - [ ] Collection script runs without errors
   - [ ] Golden data files are created
   - [ ] File count matches scenario count

2. **Validation Phase:**
   - [ ] Run validation script
   - [ ] Check for unmasked secrets manually
   - [ ] Verify JSON structure is correct
   - [ ] Confirm metadata is complete

3. **Testing Phase:**
   - [ ] Tests can be discovered
   - [ ] Tests pass without real API calls
   - [ ] Tests pass without credentials
   - [ ] Test coverage is adequate
   - [ ] Error scenarios are tested

4. **Integration Phase:**
   - [ ] Tests pass in CI/CD
   - [ ] Tests pass on clean checkout
   - [ ] Documentation is accurate
   - [ ] Examples work as documented

### 8.3 Rollback Procedures

If a phase fails:

#### Phase 1 Failure:
- Delete created directories
- Review error messages
- Fix issues and restart

#### Phase 2/3 Failure (Collection):
- Delete incomplete golden data files
- Review API credentials
- Check network connectivity
- Review error logs
- Fix issues and re-collect

#### Phase 2/3 Failure (Testing):
- Review golden data structure
- Check test expectations
- Verify provider behavior
- Update tests or re-collect data

#### Phase 4 Failure (Integration):
- Review CI/CD logs
- Check for missing dependencies
- Verify file paths are correct
- Test locally before pushing

---

## 9. Risk Mitigation

### 9.1 Potential Issues and Solutions

#### Issue 1: API Rate Limits During Collection

**Risk Level:** Medium  
**Impact:** Collection fails or is incomplete

**Solutions:**
- Add delays between scenario collections
- Collect in batches
- Use different API keys for different providers
- Implement retry logic with exponential backoff

**Mitigation Code:**
```python
import asyncio

async def collectWithRetry(scenario, maxRetries=3):
    for attempt in range(maxRetries):
        try:
            await collectScenario(scenario)
            return
        except RateLimitError:
            if attempt < maxRetries - 1:
                waitTime = 2 ** attempt  # Exponential backoff
                print(f"Rate limited, waiting {waitTime}s...")
                await asyncio.sleep(waitTime)
            else:
                raise
```

#### Issue 2: YcSdkProvider SDK Structure Changes

**Risk Level:** High  
**Impact:** Mocking breaks when SDK updates

**Solutions:**
- Document SDK version used
- Pin SDK version in requirements
- Create adapter layer for SDK responses
- Add SDK version checks in tests

**Mitigation:**
```python
# In collect_yc_sdk.py
import yandex_cloud_ml_sdk
print(f"Using SDK version: {yandex_cloud_ml_sdk.__version__}")

# In golden data metadata
"sdk_version": yandex_cloud_ml_sdk.__version__
```

#### Issue 3: Secrets Not Properly Masked

**Risk Level:** High  
**Impact:** Credentials leaked in repository

**Solutions:**
- Multiple validation passes
- Automated secret scanning
- Manual review before commit
- Git hooks to prevent commits with secrets

**Mitigation:**
```bash
# Pre-commit hook
#!/bin/bash
if grep -r "sk-" tests/golden_data/ai_providers/*/; then
    echo "ERROR: Possible unmasked secrets found!"
    exit 1
fi
```

#### Issue 4: Golden Data Becomes Stale

**Risk Level:** Low  
**Impact:** Tests don't reflect current API behavior

**Solutions:**
- Document when to re-collect
- Schedule periodic re-collection
- Version golden data files
- Add timestamps to metadata

**Mitigation:**
- Add `created_at` to metadata
- Document re-collection triggers
- Create re-collection schedule

#### Issue 5: httpx Patching Conflicts

**Risk Level:** Medium  
**Impact:** Tests interfere with each other

**Solutions:**
- Use async context managers properly
- Ensure cleanup in test teardown
- Isolate tests with fixtures
- Use separate test files per provider

**Mitigation:**
```python
@pytest.fixture
async def isolatedProvider():
    """Ensure clean httpx state for each test."""
    # Setup
    yield
    # Teardown - restore httpx
    import httpx
    # Reset any global state
```

### 9.2 Fallback Approaches

#### If HTTP Recording Fails:

**Option A:** Manual Response Creation
- Create golden data files manually
- Use actual API responses as templates
- Mask secrets manually

**Option B:** Simplified Scenarios
- Reduce scenario complexity
- Focus on core functionality
- Add complex scenarios later

#### If YcSdk Mocking is Too Complex:

**Option A:** Integration Tests Only
- Skip golden data for YcSdk
- Use real SDK in integration tests
- Mark tests as requiring credentials

**Option B:** Response-Level Mocking
- Mock at response level, not SDK level
- Capture response data structures
- Create simpler mock objects

### 9.3 Known Limitations

1. **Streaming Responses:**
   - Current implementation may not handle streaming well
   - May need special handling for streaming scenarios
   - Consider recording stream chunks separately

2. **Binary Data:**
   - Image generation responses contain binary data
   - May need base64 encoding in golden data
   - File size considerations

3. **Non-Deterministic Responses:**
   - AI responses vary between calls
   - Tests should check structure, not exact content
   - Use flexible assertions

4. **Provider-Specific Features:**
   - Some features may not be testable with golden data
   - Tool calling may need special handling
   - Function calls may need mocking

---

## 10. Timeline Estimate

### 10.1 Detailed Timeline

#### Week 1: Foundation + BasicOpenAI
- **Day 1-2:** Phase 1 (Foundation Setup)
  - Create directory structure
  - Set up base files
  - Create provider base class
  - **Deliverable:** Foundation complete

- **Day 3-4:** Phase 2.1 (BasicOpenAI)
  - Create scenarios
  - Collect golden data
  - Write tests
  - **Deliverable:** BasicOpenAI tests passing

- **Day 5:** Buffer and documentation
  - Fix any issues
  - Document learnings
  - **Deliverable:** Week 1 complete

#### Week 2: YcOpenai + Openrouter
- **Day 1-2:** Phase 2.2 (YcOpenai)
  - Create scenarios
  - Collect golden data (with folder_id masking)
  - Write tests
  - **Deliverable:** YcOpenai tests passing

- **Day 3-4:** Phase 2.3 (Openrouter)
  - Create scenarios
  - Collect golden data
  - Write tests
  - **Deliverable:** Openrouter tests passing

- **Day 5:** Integration testing
  - Run all HTTP-based provider tests
  - Fix any issues
  - **Deliverable:** All HTTP providers working

#### Week 3: YcSdk + Integration
- **Day 1-3:** Phase 3 (YcSdk)
  - Create SDK collector
  - Create scenarios
  - Collect SDK responses
  - Write tests with mocking
  - **Deliverable:** YcSdk tests passing

- **Day 4-5:** Phase 4 (Integration)
  - Create master test runner
  - Create validation script
  - Update CI/CD
  - Write documentation
  - **Deliverable:** Complete system working

### 10.2 Critical Path Timeline

Minimum viable implementation (one provider working):

- **Day 1:** Foundation (4 hours)
- **Day 2:** BasicOpenAI scenarios + collection (4 hours)
- **Day 3:** BasicOpenAI tests (4 hours)
- **Day 4:** Validation + documentation (4 hours)

**Total:** 4 days for MVP

### 10.3 Parallel Work Timeline

With 2 developers working in parallel:

- **Week 1:**
  - Dev A: Foundation + BasicOpenAI
  - Dev B: YcOpenai scenarios (waiting for foundation)

- **Week 2:**
  - Dev A: Openrouter
  - Dev B: YcOpenai completion + YcSdk start

- **Week 3:**
  - Dev A: Integration + CI/CD
  - Dev B: YcSdk completion + documentation

**Total:** 2-3 weeks with parallel work

### 10.4 Milestone Schedule

| Milestone | Target Date | Deliverables |
|-----------|-------------|--------------|
| M1: Foundation | End of Day 2 | Directory structure, base classes, documentation templates |
| M2: First Provider | End of Week 1 | BasicOpenAI fully working with tests |
| M3: HTTP Providers | End of Week 2 | All HTTP-based providers working |
| M4: SDK Provider | Mid Week 3 | YcSdk working with mocking |
| M5: Integration | End of Week 3 | CI/CD, validation, complete documentation |

---

## 11. Success Metrics

### 11.1 Quantitative Metrics

- ✅ **Test Coverage:** At least 3 scenarios per provider (12+ total)
- ✅ **Test Execution Time:** All tests complete in < 30 seconds
- ✅ **Secret Masking:** 100% of secrets masked (0 leaks)
- ✅ **Test Pass Rate:** 100% of tests passing in CI/CD
- ✅ **Documentation:** All sections complete and accurate

### 11.2 Qualitative Metrics

- ✅ **Ease of Use:** New developers can run tests without setup
- ✅ **Maintainability:** Adding new scenarios is straightforward
- ✅ **Reliability:** Tests produce consistent results
- ✅ **Clarity:** Documentation is clear and comprehensive
- ✅ **Reusability:** Framework can be extended to other providers

### 11.3 Acceptance Criteria

The implementation is complete when:

1. **All Providers Tested:**
   - BasicOpenAI: ≥3 scenarios
   - YcOpenai: ≥3 scenarios
   - Openrouter: ≥3 scenarios
   - YcSdk: ≥3 scenarios

2. **Tests Pass Without Credentials:**
   - No API keys needed to run tests
   - Tests work on clean checkout
   - Tests work offline

3. **CI/CD Integration:**
   - Tests run in GitHub Actions
   - Tests pass on every commit
   - Validation runs automatically

4. **Documentation Complete:**
   - User guide exists
   - Collection process documented
   - Troubleshooting guide available
   - Examples provided

5. **Quality Assurance:**
   - No secrets in golden data
   - All golden data validated
   - Code reviewed and approved
   - Tests are maintainable

---

## 12. Post-Implementation

### 12.1 Maintenance Plan

#### Regular Tasks:

**Monthly:**
- Review test pass rates
- Check for stale golden data
- Update documentation if needed

**Quarterly:**
- Re-collect golden data for all providers
- Update scenarios based on new features
- Review and update documentation

**When Provider Updates:**
- Re-collect affected golden data
- Update tests if API changes
- Document breaking changes

#### Ownership:

- **Golden Data:** Team responsibility
- **Tests:** Provider implementer
- **Documentation:** Technical writer + team
- **CI/CD:** DevOps + team

### 12.2 Future Enhancements

#### Short-term (1-3 months):

1. **Add More Scenarios:**
   - Tool calling scenarios
   - Streaming response scenarios
   - Error handling scenarios
   - Edge cases

2. **Improve Validation:**
   - Automated secret detection
   - Schema validation
   - Response structure validation

3. **Better Reporting:**
   - Test coverage reports
   - Golden data freshness reports
   - CI/CD dashboards

#### Long-term (3-6 months):

1. **Automated Re-collection:**
   - Scheduled golden data updates
   - Automatic PR creation
   - Change detection and alerts

2. **Extended Provider Support:**
   - Add new AI providers
   - Support more SDK-based providers
   - Generic provider testing framework

3. **Advanced Features:**
   - Differential testing (compare providers)
   - Performance benchmarking
   - Cost analysis

### 12.3 Knowledge Transfer

#### Documentation to Create:

1. **Developer Guide:**
   - How to add new providers
   - How to add new scenarios
   - How to debug failing tests

2. **Architecture Guide:**
   - System design overview
   - Component interactions
   - Extension points

3. **Troubleshooting Guide:**
   - Common issues and solutions
   - Debug techniques
   - FAQ

#### Training Sessions:

1. **Session 1: Overview** (1 hour)
   - What is golden data testing
   - Why we use it
   - How it works

2. **Session 2: Hands-on** (2 hours)
   - Running tests
   - Collecting golden data
   - Adding scenarios

3. **Session 3: Advanced** (2 hours)
   - SDK-level mocking
   - Debugging techniques
   - Best practices

---

## 13. Conclusion

This implementation plan provides a comprehensive roadmap for implementing golden data testing for AI providers in the Gromozeka project. The plan is structured to:

- **Start Simple:** Begin with foundation and one provider
- **Build Incrementally:** Add providers one at a time
- **Validate Continuously:** Check quality at each phase
- **Document Thoroughly:** Ensure maintainability

### 13.1 Key Takeaways

1. **Foundation First:** Proper setup saves time later
2. **One Provider at a Time:** Validate before moving on
3. **Secret Masking is Critical:** Multiple validation passes needed
4. **YcSdk is Special:** Requires different approach
5. **Documentation Matters:** Future maintainers will thank you

### 13.2 Next Steps

1. **Review this plan** with the team
2. **Get approval** for timeline and approach
3. **Set up environment** (API keys, tools)
4. **Start with Phase 1** (Foundation)
5. **Iterate and improve** based on learnings

### 13.3 Questions to Address

Before starting implementation:

- [ ] Are API keys and quotas available?
- [ ] Is the timeline acceptable?
- [ ] Are there any provider-specific concerns?
- [ ] Who will be responsible for each phase?
- [ ] How will we handle API costs during collection?
- [ ] What is the review process for golden data?

---

## Appendix A: File Checklist

### Files to Create:

#### Phase 1:
- [ ] `tests/golden_data/ai_providers/scenarios/README.md`
- [ ] `tests/golden_data/ai_providers/SECRETS.md`
- [ ] `tests/golden_data/ai_providers/provider.py`

#### Phase 2:
- [ ] `tests/golden_data/ai_providers/scenarios/basic_openai_scenarios.json`
- [ ] `tests/golden_data/ai_providers/collect_basic_openai.sh`
- [ ] `tests/golden_data/ai_providers/test_basic_openai_provider.py`
- [ ] `tests/golden_data/ai_providers/scenarios/yc_openai_scenarios.json`
- [ ] `tests/golden_data/ai_providers/collect_yc_openai.sh`
- [ ] `tests/golden_data/ai_providers/test_yc_openai_provider.py`
- [ ] `tests/golden_data/ai_providers/scenarios/openrouter_scenarios.json`
- [ ] `tests/golden_data/ai_providers/collect_openrouter.sh`
- [ ] `tests/golden_data/ai_providers/test_openrouter_provider.py`

#### Phase 3:
- [ ] `tests/golden_data/ai_providers/collect_yc_sdk.py`
- [ ] `tests/golden_data/ai_providers/scenarios/yc_sdk_scenarios.json`
- [ ] `tests/golden_data/ai_providers/test_yc_sdk_provider.py`
- [ ] `tests/golden_data/ai_providers/collect_yc_sdk.sh`

#### Phase 4:
- [ ] `tests/golden_data/ai_providers/run_all_tests.sh`
- [ ] `tests/golden_data/ai_providers/validate_golden_data.py`
- [ ] `.github/workflows/test.yml` (update)
- [ ] `tests/golden_data/ai_providers/README.md`

### Directories to Create:

- [ ] `tests/golden_data/ai_providers/`
- [ ] `tests/golden_data/ai_providers/scenarios/`
- [ ] `tests/golden_data/ai_providers/basic_openai/`
- [ ] `tests/golden_data/ai_providers/yc_openai/`
- [ ] `tests/golden_data/ai_providers/openrouter/`
- [ ] `tests/golden_data/ai_providers/yc_sdk/`

---

## Appendix B: Command Reference

### Collection Commands:

```bash
# BasicOpenAI
./tests/golden_data/ai_providers/collect_basic_openai.sh

# YcOpenai
./tests/golden_data/ai_providers/collect_yc_openai.sh

# Openrouter
./tests/golden_data/ai_providers/collect_openrouter.sh

# YcSdk
./tests/golden_data/ai_providers/collect_yc_sdk.sh
```

### Test Commands:

```bash
# All tests
./tests/golden_data/ai_providers/run_all_tests.sh

# Specific provider
./venv/bin/python3 -m pytest tests/golden_data/ai_providers/test_basic_openai_provider.py -v

# With coverage
./venv/bin/python3 -m pytest tests/golden_data/ai_providers/ --cov=lib.ai.providers --cov-report=html
```

### Validation Commands:

```bash
# Validate golden data
./venv/bin/python3 tests/golden_data/ai_providers/validate_golden_data.py

# Check for secrets
grep -r "sk-" tests/golden_data/ai_providers/*/
grep -r "AQVN" tests/golden_data/ai_providers/*/

# Validate JSON
find tests/golden_data/ai_providers/ -name "*.json" -exec python3 -m json.tool {} \; > /dev/null
```

---

**End of Implementation Plan**

*This document should be reviewed and updated as implementation progresses. Feedback and improvements are welcome, dood!*