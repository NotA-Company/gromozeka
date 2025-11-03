# AI Aurumentation System Design Document

## 1. Overview

### 1.1 Purpose and Goals

The AI Aurumentation system extends the existing golden data testing framework to support AI provider testing. Its primary goals are:

- **Deterministic Testing**: Enable repeatable tests for AI provider integrations without making real API calls
- **Cost Reduction**: Eliminate API costs during development and CI/CD testing
- **Offline Development**: Allow development and testing without internet connectivity
- **Regression Prevention**: Detect breaking changes in provider integrations through golden data comparison
- **Multi-Provider Support**: Provide unified testing approach across different AI providers

### 1.2 Integration with Existing Framework

The AI Aurumentation system builds upon the existing [`lib/aurumentation/`](lib/aurumentation/) framework, which provides:

- **HTTP Traffic Recording**: Captures HTTP requests/responses via httpx transport patching
- **Secret Masking**: Automatically masks sensitive data (API keys, tokens, etc.)
- **Scenario Management**: JSON-based scenario definitions for test cases
- **Replay Mechanism**: Replays recorded traffic without real network calls

The system follows the proven pattern established by the OpenWeatherMap golden tests (see [`docs/reports/OpenWeatherMap-testing-golden.md`](docs/reports/OpenWeatherMap-testing-golden.md)).

### 1.3 Benefits for Testing and Development

**For Developers:**
- Fast test execution (no network latency)
- Predictable test results
- Easy debugging with captured request/response data
- No API key management in CI/CD

**For Testing:**
- Comprehensive scenario coverage
- Edge case testing (errors, timeouts, rate limits)
- Provider-specific behavior validation
- Integration test stability

**For CI/CD:**
- No external dependencies
- No API costs
- Faster pipeline execution
- Consistent test results

## 2. Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     AI Provider Tests                        │
│  (test_basic_openai_provider.py, test_yc_openai_provider.py)│
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ Uses
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  GoldenDataProvider                          │
│  - Loads golden data scenarios                               │
│  - Patches httpx.AsyncClient globally                        │
│  - Returns ReplayTransport for recorded traffic              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ Reads
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              Golden Data Files (JSON)                        │
│  tests/golden_data/ai_providers/{provider}/                  │
│  - scenario_name.json                                        │
│    * metadata (provider, model, method, params)              │
│    * recordings (HTTP request/response pairs)                │
└─────────────────────────────────────────────────────────────┘
                     ▲
                     │
                     │ Created by
                     │
┌─────────────────────────────────────────────────────────────┐
│                  GoldenDataCollector                         │
│  - Reads scenario definitions (JSON)                         │
│  - Executes real API calls                                   │
│  - Records HTTP traffic via RecordingTransport               │
│  - Masks secrets                                             │
│  - Saves golden data files                                   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ Uses
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                Core Aurumentation Components                 │
│  - GoldenDataRecorder: Patches httpx, captures traffic       │
│  - RecordingTransport: Wraps httpx transport, records calls  │
│  - ReplayTransport: Returns recorded responses               │
│  - SecretMasker: Masks API keys, tokens, sensitive data      │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Component Interactions

#### Collection Phase (One-time setup)

```
Developer → Collector CLI → GoldenDataCollector
                                    ↓
                          Reads scenarios.json
                                    ↓
                          Creates GoldenDataRecorder
                                    ↓
                          Patches httpx.AsyncClient
                                    ↓
                          Instantiates AI Provider
                                    ↓
                          Calls provider methods
                                    ↓
                          RecordingTransport captures HTTP
                                    ↓
                          SecretMasker masks secrets
                                    ↓
                          Saves golden data files
```

#### Replay Phase (During tests)

```
Test Suite → GoldenDataProvider.patchClient()
                        ↓
              Loads golden data file
                        ↓
              Creates ReplayTransport
                        ↓
              Patches httpx.AsyncClient
                        ↓
              Test creates AI Provider
                        ↓
              Provider makes "HTTP" calls
                        ↓
              ReplayTransport returns recorded responses
                        ↓
              Test validates results
```

### 2.3 Data Flow

**Collection Flow:**
1. Collector reads scenario definition (provider, model, method, parameters)
2. Recorder patches httpx globally with RecordingTransport
3. Real AI provider instance is created with actual API credentials
4. Provider method is called (e.g., `generateText()`)
5. Provider makes HTTP requests via httpx
6. RecordingTransport intercepts and records all HTTP traffic
7. Masker processes recordings to remove secrets
8. Golden data file is saved with metadata and masked recordings

**Replay Flow:**
1. Test loads golden data file for specific scenario
2. Provider patches httpx with ReplayTransport containing recordings
3. Test creates AI provider instance (no real credentials needed)
4. Provider method is called
5. Provider makes HTTP requests via httpx
6. ReplayTransport matches request and returns recorded response
7. Test validates provider behavior against expected results

## 3. Provider-Specific Considerations

### 3.1 BasicOpenAIProvider

**Characteristics:**
- Standard OpenAI API compatibility
- Uses [`openai.AsyncOpenAI`](lib/ai/providers/basic_openai_provider.py) client
- Base URL: `https://api.openai.com/v1`
- Authentication: Bearer token in Authorization header

**Testing Considerations:**
- Baseline for OpenAI-compatible providers
- Test standard chat completions
- Test streaming responses (if supported)
- Test error handling (rate limits, invalid requests)

**Configuration:**
```json
{
  "module": "lib.ai.providers.basic_openai_provider",
  "class": "BasicOpenAIProvider",
  "init_kwargs": {
    "api_key": "${OPENAI_API_KEY}",
    "models": {...}
  }
}
```

### 3.2 YcOpenaiProvider

**Characteristics:**
- Yandex Cloud OpenAI-compatible API
- Requires `folder_id` parameter
- Special URL format: `gpt://{folder_id}/{model_id}/{model_version}`
- Base URL: `https://llm.api.cloud.yandex.net/v1`
- Authentication: API key in Authorization header

**Testing Considerations:**
- Must mask `folder_id` in URLs (appears in model identifier)
- Test folder_id validation
- Test YC-specific error responses
- Verify URL format transformation

**Configuration:**
```json
{
  "module": "lib.ai.providers.yc_openai_provider",
  "class": "YcOpenaiProvider",
  "init_kwargs": {
    "api_key": "${YC_API_KEY}",
    "folder_id": "${YC_FOLDER_ID}",
    "models": {...}
  }
}
```

**Masking Strategy:**
- Add `folder_id` to secrets list
- Mask in URL: `gpt://***MASKED***/yandexgpt/latest`
- Mask in request bodies if present

### 3.3 OpenrouterProvider

**Characteristics:**
- OpenRouter aggregation service
- Base URL: `https://openrouter.ai/api/v1`
- Custom headers: `HTTP-Referer`, `X-Title` for site rankings
- Authentication: Bearer token in Authorization header

**Testing Considerations:**
- Test custom header inclusion
- Test multiple model providers through OpenRouter
- Test OpenRouter-specific error responses
- Verify site header values

**Configuration:**
```json
{
  "module": "lib.ai.providers.openrouter_provider",
  "class": "OpenrouterProvider",
  "init_kwargs": {
    "api_key": "${OPENROUTER_API_KEY}",
    "models": {...}
  }
}
```

**Special Headers:**
```python
{
  "HTTP-Referer": "https://sourcecraft.dev/notacompany/gromozeka",
  "X-Title": "Gromozeka AI Bot"
}
```

### 3.4 YcSdkProvider - Special Challenge

**Characteristics:**
- Uses Yandex Cloud ML SDK directly (NOT HTTP-based)
- SDK: `yandex_cloud_ml_sdk.YCloudML`
- Authentication: YandexCloudCLIAuth or API key
- Supports text generation and image generation
- No direct HTTP calls visible to httpx

**Challenge:**
The YcSdkProvider does NOT use httpx for HTTP communication. It uses the Yandex Cloud SDK which has its own internal HTTP client. This means:
- Standard httpx patching won't capture SDK traffic
- RecordingTransport won't see SDK requests
- ReplayTransport can't intercept SDK calls

**Proposed Solutions:**

#### Option 1: SDK-Level Mocking (Recommended)
Mock the SDK's response objects directly without HTTP interception:

```python
# In test
from unittest.mock import AsyncMock, patch

async def test_yc_sdk_text_generation():
    # Load golden data
    golden_data = load_golden_data("yc_sdk_text_generation.json")
    
    # Mock SDK response
    mock_result = create_mock_sdk_result(golden_data["sdk_response"])
    
    with patch.object(YCloudML, 'models') as mock_models:
        mock_models.completions.return_value.configure.return_value.run = AsyncMock(
            return_value=mock_result
        )
        
        # Test provider
        provider = YcSdkProvider(config)
        result = await provider.generateText(messages)
        
        assert result.text == golden_data["expected_text"]
```

**Golden Data Format for SDK:**
```json
{
  "metadata": {
    "name": "yc_sdk_text_generation",
    "provider": "YcSdkProvider",
    "model": "yandexgpt",
    "method": "generateText"
  },
  "sdk_response": {
    "alternatives": [
      {
        "message": {
          "role": "assistant",
          "text": "Response text here"
        },
        "status": "ALTERNATIVE_STATUS_FINAL"
      }
    ],
    "usage": {
      "inputTextTokens": "50",
      "completionTokens": "100",
      "totalTokens": "150"
    }
  },
  "expected_result": {
    "text": "Response text here",
    "status": 0
  }
}
```

#### Option 2: SDK HTTP Client Patching (Complex)
Patch the SDK's internal HTTP client (requires SDK internals knowledge):

```python
# Requires understanding SDK's internal HTTP client
# May break with SDK updates
# Not recommended unless necessary
```

#### Option 3: Hybrid Approach
Use real SDK for collection, mock for replay:

```python
# Collection: Use real SDK, capture responses
async def collect_yc_sdk_scenario():
    provider = YcSdkProvider(real_config)
    result = await provider.generateText(messages)
    
    # Save SDK response structure
    save_golden_data({
        "sdk_response": result._raw_response,  # SDK internal structure
        "expected_result": {
            "text": result.text,
            "status": result.status
        }
    })

# Replay: Mock SDK responses
async def test_with_golden_data():
    golden = load_golden_data()
    # Use Option 1 approach
```

**Recommendation:**
Use **Option 1 (SDK-Level Mocking)** because:
- Most maintainable (no SDK internals dependency)
- Clear separation between HTTP-based and SDK-based providers
- Easier to update when SDK changes
- Follows standard Python mocking patterns

**Implementation Notes:**
- Create separate collection script for YcSdkProvider
- Store SDK response structures in golden data
- Create helper functions to convert golden data to mock objects
- Document SDK version used for collection

## 4. Data Collection Strategy

### 4.1 Scenario Definition Format

Scenarios are defined in JSON files following this structure:

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
          "context_size": 4096
        }
      }
    },
    "kwargs": {
      "model_name": "gpt-3.5-turbo",
      "messages": [
        {
          "role": "user",
          "content": "What is the capital of France?"
        }
      ]
    }
  }
]
```

### 4.2 Environment Variables

**Required Environment Variables:**

```bash
# OpenAI
OPENAI_API_KEY=sk-...

# Yandex Cloud OpenAI
YC_API_KEY=AQVN...
YC_FOLDER_ID=b1g...

# OpenRouter
OPENROUTER_API_KEY=sk-or-v1-...

# Yandex Cloud SDK (for YcSdkProvider)
YC_SDK_API_KEY=AQVN...
# OR use CLI auth (no env var needed)
```

**Loading Strategy:**
- Use [`lib.utils.load_dotenv()`](lib/utils.py) to load from `.env` file
- Collector substitutes `${VAR_NAME}` patterns in scenario definitions
- Original placeholders preserved in golden data metadata
- Actual values masked in recordings

### 4.3 Collection Process

**Step 1: Prepare Scenarios**
```bash
# Create scenario definition file
vim tests/golden_data/ai_providers/scenarios/basic_openai_scenarios.json
```

**Step 2: Set Environment Variables**
```bash
# Create .env file with API keys
cat > .env << EOF
OPENAI_API_KEY=sk-...
YC_API_KEY=AQVN...
YC_FOLDER_ID=b1g...
OPENROUTER_API_KEY=sk-or-v1-...
EOF
```

**Step 3: Run Collector**
```bash
# Collect golden data
./venv/bin/python3 -m lib.aurumentation.collector \
  --input tests/golden_data/ai_providers/scenarios/basic_openai_scenarios.json \
  --output tests/golden_data/ai_providers/basic_openai/ \
  --secrets OPENAI_API_KEY,YC_API_KEY,YC_FOLDER_ID,OPENROUTER_API_KEY
```

**Step 4: Verify Golden Data**
```bash
# Check generated files
ls -la tests/golden_data/ai_providers/basic_openai/
# basic_text_generation.json
# error_handling_invalid_model.json
# ...

# Verify masking
grep -r "sk-" tests/golden_data/ai_providers/basic_openai/
# Should return no results (all masked)
```

### 4.4 Secret Masking Strategy

**Automatic Masking:**
The [`SecretMasker`](lib/aurumentation/masker.py) automatically masks:

1. **API Keys in Headers:**
   ```json
   "Authorization": "Bearer ***MASKED***"
   ```

2. **API Keys in URLs:**
   ```
   https://api.example.com/v1/chat?api_key=***MASKED***
   ```

3. **Folder IDs (YC-specific):**
   ```
   gpt://***MASKED***/yandexgpt/latest
   ```

4. **Pattern-Based Masking:**
   - Keys matching: `api_key`, `token`, `auth`, `password`, `secret`
   - Case-insensitive matching
   - Recursive dict/list processing

**Manual Secret Addition:**
```python
# In collector script
secrets = [
    os.getenv("OPENAI_API_KEY"),
    os.getenv("YC_API_KEY"),
    os.getenv("YC_FOLDER_ID"),  # Important for YC!
    os.getenv("OPENROUTER_API_KEY"),
]
```

**Response Content Considerations:**
- AI responses are NOT masked (they're the test data)
- User messages are NOT masked (they're test inputs)
- Only authentication/authorization data is masked
- Consider masking PII if present in test scenarios

## 5. Testing Scenarios

### 5.1 Common Scenarios (All Providers)

#### Text Generation
```json
{
  "name": "basic_text_generation",
  "description": "Generate text from single user message",
  "method": "generateText",
  "kwargs": {
    "messages": [
      {"role": "user", "content": "What is 2+2?"}
    ]
  }
}
```

#### Multi-Turn Conversation
```json
{
  "name": "multi_turn_conversation",
  "description": "Multi-turn conversation with context",
  "method": "generateText",
  "kwargs": {
    "messages": [
      {"role": "user", "content": "My name is Alice"},
      {"role": "assistant", "content": "Hello Alice!"},
      {"role": "user", "content": "What's my name?"}
    ]
  }
}
```

#### Error Handling - Invalid Model
```json
{
  "name": "error_invalid_model",
  "description": "Handle invalid model name error",
  "method": "generateText",
  "kwargs": {
    "model_name": "nonexistent-model",
    "messages": [
      {"role": "user", "content": "Hello"}
    ]
  }
}
```

#### Error Handling - Rate Limit
```json
{
  "name": "error_rate_limit",
  "description": "Handle rate limit error (429)",
  "method": "generateText",
  "kwargs": {
    "messages": [
      {"role": "user", "content": "Test rate limit"}
    ]
  }
}
```

#### Empty Response
```json
{
  "name": "empty_response",
  "description": "Handle empty or null response",
  "method": "generateText",
  "kwargs": {
    "messages": [
      {"role": "user", "content": ""}
    ]
  }
}
```

### 5.2 Provider-Specific Scenarios

#### BasicOpenAIProvider

**Tool Calling:**
```json
{
  "name": "tool_calling_weather",
  "description": "Use function calling to get weather",
  "method": "generateText",
  "kwargs": {
    "messages": [
      {"role": "user", "content": "What's the weather in Paris?"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "Get weather for a location",
          "parameters": {
            "type": "object",
            "properties": {
              "location": {"type": "string"}
            }
          }
        }
      }
    ]
  }
}
```

**Streaming Response:**
```json
{
  "name": "streaming_response",
  "description": "Test streaming text generation",
  "method": "generateTextStream",
  "kwargs": {
    "messages": [
      {"role": "user", "content": "Count from 1 to 10"}
    ]
  }
}
```

#### YcOpenaiProvider

**Folder ID Validation:**
```json
{
  "name": "folder_id_validation",
  "description": "Verify folder_id is included in requests",
  "method": "generateText",
  "kwargs": {
    "messages": [
      {"role": "user", "content": "Hello"}
    ]
  }
}
```

**YC-Specific Model Format:**
```json
{
  "name": "yc_model_format",
  "description": "Test gpt:// URL format",
  "method": "generateText",
  "kwargs": {
    "model_name": "yandexgpt",
    "messages": [
      {"role": "user", "content": "Test"}
    ]
  }
}
```

#### OpenrouterProvider

**Custom Headers:**
```json
{
  "name": "custom_headers",
  "description": "Verify HTTP-Referer and X-Title headers",
  "method": "generateText",
  "kwargs": {
    "messages": [
      {"role": "user", "content": "Hello"}
    ]
  }
}
```

**Multiple Model Providers:**
```json
{
  "name": "anthropic_via_openrouter",
  "description": "Test Anthropic model through OpenRouter",
  "method": "generateText",
  "kwargs": {
    "model_name": "anthropic/claude-3-sonnet",
    "messages": [
      {"role": "user", "content": "Hello"}
    ]
  }
}
```

#### YcSdkProvider

**Text Generation:**
```json
{
  "name": "sdk_text_generation",
  "description": "Generate text using YC SDK",
  "method": "generateText",
  "kwargs": {
    "messages": [
      {"role": "user", "content": "Hello"}
    ]
  }
}
```

**Image Generation:**
```json
{
  "name": "sdk_image_generation",
  "description": "Generate image using YC SDK",
  "method": "generateImage",
  "kwargs": {
    "prompt": "A beautiful sunset over mountains",
    "width_ratio": 1,
    "height_ratio": 1
  }
}
```

### 5.3 Edge Cases and Error Conditions

#### Network Errors
```json
{
  "name": "network_timeout",
  "description": "Handle network timeout",
  "method": "generateText",
  "kwargs": {
    "messages": [{"role": "user", "content": "Test"}],
    "timeout": 0.001
  }
}
```

#### Invalid JSON Response
```json
{
  "name": "invalid_json_response",
  "description": "Handle malformed JSON in response",
  "method": "generateText",
  "kwargs": {
    "messages": [{"role": "user", "content": "Test"}]
  }
}
```

#### Authentication Failure
```json
{
  "name": "auth_failure",
  "description": "Handle 401 authentication error",
  "method": "generateText",
  "kwargs": {
    "messages": [{"role": "user", "content": "Test"}]
  }
}
```

#### Large Context
```json
{
  "name": "large_context",
  "description": "Handle context size limits",
  "method": "generateText",
  "kwargs": {
    "messages": [
      {"role": "user", "content": "Very long message..."}
    ]
  }
}
```

## 6. Sensitive Data Handling

### 6.1 API Keys Masking

**In Headers:**
```json
{
  "request": {
    "headers": {
      "Authorization": "Bearer ***MASKED***",
      "X-API-Key": "***MASKED***"
    }
  }
}
```

**In URL Parameters:**
```json
{
  "request": {
    "url": "https://api.example.com/v1/chat?api_key=***MASKED***"
  }
}
```

### 6.2 Folder IDs Masking (YC-specific)

**In Model Identifier:**
```json
{
  "request": {
    "body": {
      "model": "gpt://***MASKED***/yandexgpt/latest"
    }
  }
}
```

**In URLs:**
```json
{
  "request": {
    "url": "https://llm.api.cloud.yandex.net/v1/completions?folder_id=***MASKED***"
  }
}
```

### 6.3 Response Content Considerations

**What to Mask:**
- Server trace IDs: `x-server-trace-id: ***MASKED***`
- Internal IPs or hostnames in error messages
- Session tokens in responses

**What NOT to Mask:**
- AI-generated text (it's the test data)
- User messages (they're test inputs)
- Model names and versions
- Token counts and usage statistics
- Error messages (needed for debugging)

### 6.4 Environment Variable Substitution

**In Scenario Definitions:**
```json
{
  "init_kwargs": {
    "api_key": "${OPENAI_API_KEY}",
    "folder_id": "${YC_FOLDER_ID}"
  }
}
```

**In Golden Data Metadata:**
```json
{
  "metadata": {
    "init_kwargs": {
      "api_key": "${OPENAI_API_KEY}",
      "folder_id": "${YC_FOLDER_ID}"
    }
  }
}
```

**Substitution Process:**
1. Collector reads scenario with `${VAR}` placeholders
2. Substitutes actual values from environment
3. Uses actual values for API calls
4. Masks actual values in recordings
5. Preserves placeholders in metadata

## 7. File Structure

### 7.1 Directory Organization

```
tests/
└── golden_data/
    └── ai_providers/
        ├── scenarios/
        │   ├── basic_openai_scenarios.json
        │   ├── yc_openai_scenarios.json
        │   ├── openrouter_scenarios.json
        │   └── yc_sdk_scenarios.json
        │
        ├── basic_openai/
        │   ├── basic_text_generation.json
        │   ├── multi_turn_conversation.json
        │   ├── tool_calling_weather.json
        │   ├── error_invalid_model.json
        │   └── error_rate_limit.json
        │
        ├── yc_openai/
        │   ├── basic_text_generation.json
        │   ├── folder_id_validation.json
        │   ├── yc_model_format.json
        │   └── error_handling.json
        │
        ├── openrouter/
        │   ├── basic_text_generation.json
        │   ├── custom_headers.json
        │   ├── anthropic_via_openrouter.json
        │   └── error_handling.json
        │
        ├── yc_sdk/
        │   ├── sdk_text_generation.json
        │   ├── sdk_image_generation.json
        │   └── error_handling.json
        │
        └── provider.py  # GoldenDataProvider implementation
```

### 7.2 Naming Conventions

**Scenario Files:**
- Format: `{provider}_scenarios.json`
- Examples: `basic_openai_scenarios.json`, `yc_openai_scenarios.json`

**Golden Data Files:**
- Format: `{scenario_name}.json`
- Use snake_case
- Be descriptive but concise
- Examples:
  - `basic_text_generation.json`
  - `multi_turn_conversation.json`
  - `tool_calling_weather.json`
  - `error_invalid_model.json`

**Provider Directories:**
- Format: `{provider_name}/`
- Match provider class names (snake_case)
- Examples:
  - `basic_openai/`
  - `yc_openai/`
  - `openrouter/`
  - `yc_sdk/`

### 7.3 Golden Data File Format

```json
{
  "metadata": {
    "name": "basic_text_generation",
    "description": "Basic text generation with single user message",
    "module": "lib.ai.providers.basic_openai_provider",
    "class": "BasicOpenAIProvider",
    "method": "generateText",
    "init_kwargs": {
      "api_key": "${OPENAI_API_KEY}",
      "models": {...}
    },
    "kwargs": {
      "messages": [...]
    },
    "createdAt": "2025-11-03T00:00:00.000Z",
    "result_type": "ModelRunResult"
  },
  "recordings": [
    {
      "request": {
        "method": "POST",
        "url": "https://api.openai.com/v1/chat/completions",
        "headers": {
          "Authorization": "Bearer ***MASKED***",
          "Content-Type": "application/json"
        },
        "body": "{\"model\":\"gpt-3.5-turbo\",\"messages\":[...]}"
      },
      "response": {
        "status_code": 200,
        "headers": {
          "Content-Type": "application/json"
        },
        "content": "{\"id\":\"chatcmpl-...\",\"choices\":[...]}"
      },
      "timestamp": "2025-11-03T00:00:00.000Z"
    }
  ]
}
```

## 8. Integration Points

### 8.1 Test Suite Integration

**Test File Structure:**
```python
# tests/ai_providers/test_basic_openai_provider.py

import pytest
from tests.golden_data.ai_providers.provider import GoldenDataProvider

@pytest.mark.asyncio
async def test_basic_text_generation():
    """Test basic text generation using golden data."""
    # Load golden data
    provider = GoldenDataProvider("basic_openai/basic_text_generation.json")
    
    # Patch httpx with golden data
    async with provider.patchClient():
        # Create provider instance
        from lib.ai.providers.basic_openai_provider import BasicOpenAIProvider
        
        ai_provider = BasicOpenAIProvider({
            "api_key": "fake-key",  # Not used, golden data is replayed
            "models": {
                "gpt-3.5-turbo": {
                    "model_id": "gpt-3.5-turbo",
                    "model_version": "latest",
                    "temperature": 0.7,
                    "context_size": 4096
                }
            }
        })
        
        # Call method - uses golden data
        result = await ai_provider.generateText(
            model_name="gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": "What is 2+2?"}
            ]
        )
        
        # Validate result
        assert result.status == ModelResultStatus.SUCCESS
        assert "4" in result.text.lower()
```

**Provider Implementation:**
```python
# tests/golden_data/ai_providers/provider.py

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
import json
import httpx

from lib.aurumentation.replayer import GoldenDataReplayer
types import GoldenDataScenarioDict


class GoldenDataProvider:
    """Provider for AI golden data testing."""
    
    def __init__(self, scenario_file: str):
        """Initialize provider with golden data file.
        
        Args:
            scenario_file: Relative path to golden data file from ai_providers directory
        """
        self.scenario_file = scenario_file
        self.scenario: Optional[GoldenDataScenarioDict] = None
        self.replayer: Optional[GoldenDataReplayer] = None
    
    def _loadScenario(self) -> GoldenDataScenarioDict:
        """Load golden data scenario from file."""
        base_path = Path(__file__).parent
        file_path = base_path / self.scenario_file
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Convert to GoldenDataScenarioDict format
        scenario: GoldenDataScenarioDict = {
            "name": data["metadata"]["name"],
            "description": data["metadata"]["description"],
            "functionName": f"{data['metadata']['class']}.{data['metadata']['method']}",
            "metadata": data["metadata"],
            "recordings": data["recordings"],
            "createdAt": data["metadata"].get("createdAt", ""),
        }
        return scenario
    
    @asynccontextmanager
    async def patchClient(self):
        """Patch httpx.AsyncClient to use golden data.
        
        Usage:
            async with provider.patchClient():
                # Create and use AI provider
                result = await provider.generateText(...)
        """
        # Load scenario
        self.scenario = self._loadScenario()
        
        # Create replayer
        self.replayer = GoldenDataReplayer(self.scenario)
        
        # Patch httpx globally
        async with self.replayer:
            yield self
```

### 8.2 CI/CD Considerations

**GitHub Actions Integration:**
```yaml
# .github/workflows/test.yml

name: Tests

on: [push, pull_request]

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
      
      - name: Run AI provider tests with golden data
        run: |
          # No API keys needed - uses golden data
          pytest tests/ai_providers/ -v
        env:
          # Optional: Set fake values to satisfy provider initialization
          OPENAI_API_KEY: "fake-key-for-testing"
          YC_API_KEY: "fake-key-for-testing"
          YC_FOLDER_ID: "fake-folder-for-testing"
          OPENROUTER_API_KEY: "fake-key-for-testing"
```

**Benefits:**
- No secrets management in CI/CD
- Fast test execution (no network calls)
- Deterministic results
- No API costs
- Works in offline environments

### 8.3 Development Workflow

**Initial Setup:**
```bash
# 1. Create scenario definitions
vim tests/golden_data/ai_providers/scenarios/basic_openai_scenarios.json

# 2. Set up environment variables
cp .env.example .env
vim .env  # Add real API keys

# 3. Collect golden data (one-time)
./venv/bin/python3 -m lib.aurumentation.collector \
  --input tests/golden_data/ai_providers/scenarios/basic_openai_scenarios.json \
  --output tests/golden_data/ai_providers/basic_openai/ \
  --secrets OPENAI_API_KEY

# 4. Commit golden data to repository
git add tests/golden_data/ai_providers/basic_openai/
git commit -m "Add golden data for BasicOpenAIProvider"
```

**Running Tests:**
```bash
# Run all AI provider tests
pytest tests/ai_providers/ -v

# Run specific provider tests
pytest tests/ai_providers/test_basic_openai_provider.py -v

# Run specific test
pytest tests/ai_providers/test_basic_openai_provider.py::test_basic_text_generation -v
```

**Updating Golden Data:**
```bash
# When provider behavior changes or new scenarios are added:

# 1. Update scenario definitions
vim tests/golden_data/ai_providers/scenarios/basic_openai_scenarios.json

# 2. Re-collect golden data
./venv/bin/python3 -m lib.aurumentation.collector \
  --input tests/golden_data/ai_providers/scenarios/basic_openai_scenarios.json \
  --output tests/golden_data/ai_providers/basic_openai/ \
  --secrets OPENAI_API_KEY

# 3. Review changes
git diff tests/golden_data/ai_providers/basic_openai/

# 4. Commit updates
git add tests/golden_data/ai_providers/basic_openai/
git commit -m "Update golden data for BasicOpenAIProvider"
```

### 8.4 Debugging Failed Tests

**When a test fails:**

1. **Check golden data file:**
   ```bash
   cat tests/golden_data/ai_providers/basic_openai/basic_text_generation.json | jq
   ```

2. **Verify request matching:**
   - Check if provider is making expected HTTP requests
   - Verify URL, method, headers match golden data
   - Check request body format

3. **Compare responses:**
   - Check if response parsing is correct
   - Verify status codes
   - Check response body structure

4. **Re-collect if needed:**
   - If provider API changed, re-collect golden data
   - If test expectations changed, update test assertions

## 9. Implementation Roadmap

### Phase 1: Foundation (Week 1)
- [ ] Create directory structure for AI golden data
- [ ] Implement `GoldenDataProvider` for AI providers
- [ ] Create scenario definition templates
- [ ] Document collection process

### Phase 2: BasicOpenAIProvider (Week 2)
- [ ] Define scenarios for BasicOpenAIProvider
- [ ] Collect golden data
- [ ] Implement tests using golden data
- [ ] Verify all tests pass

### Phase 3: YcOpenaiProvider (Week 3)
- [ ] Define scenarios for YcOpenaiProvider
- [ ] Handle folder_id masking
- [ ] Collect golden data
- [ ] Implement tests
- [ ] Verify folder_id is properly masked

### Phase 4: OpenrouterProvider (Week 4)
- [ ] Define scenarios for OpenrouterProvider
- [ ] Handle custom headers
- [ ] Collect golden data
- [ ] Implement tests
- [ ] Verify custom headers are included

### Phase 5: YcSdkProvider (Week 5)
- [ ] Design SDK mocking approach
- [ ] Create SDK response collection script
- [ ] Define scenarios for YcSdkProvider
- [ ] Implement SDK-level mocking
- [ ] Implement tests
- [ ] Document SDK-specific approach

### Phase 6: Integration & Documentation (Week 6)
- [ ] Integrate all provider tests into CI/CD
- [ ] Create developer documentation
- [ ] Add troubleshooting guide
- [ ] Review and optimize golden data size
- [ ] Final testing and validation

## 10. Best Practices

### 10.1 Scenario Design

**DO:**
- Create focused scenarios testing one thing
- Use realistic test data
- Include both success and error cases
- Document expected behavior in descriptions
- Keep scenarios independent

**DON'T:**
- Create overly complex scenarios
- Use production data
- Make scenarios depend on each other
- Include PII in test data
- Create duplicate scenarios

### 10.2 Golden Data Management

**DO:**
- Commit golden data to version control
- Review golden data changes in PRs
- Keep golden data files small (< 100KB)
- Update golden data when APIs change
- Document when golden data was collected

**DON'T:**
- Manually edit golden data files
- Include unmasked secrets
- Create golden data for every edge case
- Keep outdated golden data
- Ignore golden data in code reviews

### 10.3 Test Writing

**DO:**
- Use descriptive test names
- Assert on specific behavior
- Test error handling
- Use golden data provider consistently
- Document test purpose

**DON'T:**
- Make tests depend on external state
- Skip error case testing
- Use real API keys in tests
- Create flaky tests
- Test implementation details

### 10.4 Maintenance

**DO:**
- Re-collect golden data when APIs change
- Update scenarios when adding features
- Review golden data size periodically
- Keep documentation up to date
- Monitor test execution time

**DON'T:**
- Let golden data become stale
- Ignore failing tests
- Accumulate unused scenarios
- Skip golden data updates
- Ignore performance issues

## 11. Troubleshooting

### 11.1 Common Issues

**Issue: Test fails with "No matching recording found"**
- **Cause:** Request doesn't match any recording in golden data
- **Solution:** 
  1. Check request URL, method, headers
  2. Verify golden data has matching recording
  3. Re-collect golden data if API changed

**Issue: Secrets not masked in golden data**
- **Cause:** Secret not in masking list
- **Solution:**
  1. Add secret to `--secrets` parameter
  2. Re-collect golden data
  3. Verify masking with `grep`

**Issue: YcSdkProvider tests fail**
- **Cause:** SDK not properly mocked
- **Solution:**
  1. Verify mock setup
  2. Check SDK response structure
  3. Update golden data format if needed

**Issue: Golden data file too large**
- **Cause:** Response contains large content
- **Solution:**
  1. Truncate large responses in golden data
  2. Use smaller test inputs
  3. Split into multiple scenarios

### 11.2 Debugging Tips

**Enable verbose logging:**
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

**Inspect HTTP traffic:**
```python
# In test
async with provider.patchClient() as p:
    print(f"Loaded {len(p.scenario['recordings'])} recordings")
    for i, rec in enumerate(p.scenario['recordings']):
        print(f"Recording {i}: {rec['request']['method']} {rec['request']['url']}")
```

**Compare requests:**
```python
# Add to test
from lib.aurumentation.transports import ReplayTransport

# After test fails
print("Expected request:", golden_data['recordings'][0]['request'])
print("Actual request:", actual_request)
```

## 12. Future Enhancements

### 12.1 Potential Improvements

1. **Automatic Golden Data Updates:**
   - Detect API changes automatically
   - Suggest golden data updates
   - Validate golden data freshness

2. **Smart Request Matching:**
   - Fuzzy matching for similar requests
   - Ignore non-deterministic fields
   - Match by semantic content

3. **Performance Optimization:**
   - Compress golden data files
   - Lazy load recordings
   - Cache parsed golden data

4. **Enhanced Debugging:**
   - Visual diff for failed matches
   - Request/response inspector
   - Golden data validation tools

5. **Multi-Provider Scenarios:**
   - Test provider switching
   - Compare provider responses
   - Benchmark provider performance

### 12.2 SDK Provider Support

**Generalize SDK Mocking:**
- Create framework for non-HTTP providers
- Support other SDKs (Anthropic, Google, etc.)
- Document SDK mocking patterns

**SDK Response Validation:**
- Validate SDK response structures
- Detect SDK version changes
- Auto-update mocks on SDK updates

## 13. Conclusion

The AI Aurumentation system provides a robust foundation for testing AI provider integrations without external dependencies. By following this design:

- **Developers** can work offline with fast, deterministic tests
- **CI/CD** runs without API keys or costs
- **Quality** is maintained through comprehensive scenario coverage
- **Maintenance** is simplified with clear patterns and documentation

The system is designed to be extensible, supporting new providers and scenarios as the project evolves. The special handling for YcSdkProvider demonstrates the flexibility to accommodate different integration patterns beyond HTTP-based APIs.

**Next Steps:**
1. Review this design document with the team
2. Begin Phase 1 implementation (foundation)
3. Iterate on the design based on implementation feedback
4. Expand to all AI providers systematically

---

**Document Version:** 1.0  
**Last Updated:** 2025-11-03  
**Author:** SourceCraft Code Assistant  
**Status:** Draft for Review
from lib.aurumentation.