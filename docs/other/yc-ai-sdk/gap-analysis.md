# Gap Analysis -- Current Provider vs SDK Capabilities

Comparison of what our existing YC SDK provider (`lib/ai/providers/yc_sdk_provider.py`)
uses versus what the SDK (v0.20.2) makes available. Intended to guide the
refactoring effort.

## Capability Matrix

| Capability | Currently Used | Available in SDK | Priority for Refactoring |
|---|---|---|---|
| **Text generation** | `AsyncGPTModel.run()` | `run()`, `run_stream()`, `run_deferred()`, `tokenize()` | **HIGH** -- add streaming, deferred, tokenization |
| **Image generation** | `AsyncImageGenerationModel.run_deferred()` | Same + `attach_deferred()` | **MEDIUM** |
| **Structured output** | `raise NotImplementedError` | `response_format='json'`, JSON Schema, pydantic | **HIGH** -- fully supported, critical feature |
| **Tool/function calling** | `raise NotImplementedError` | `sdk.tools.function()`, tool_choice, parallel_tool_calls | **HIGH** -- fully supported, critical feature |
| **Model config** | `temperature` only | `max_tokens`, `reasoning_mode`, `response_format`, `tools`, `parallel_tool_calls`, `tool_choice` | **HIGH** -- blocks structured output and tools |
| **Chat API (OpenAI-compat)** | Not used | Full `sdk.chat.completions` with `extra_query`, `ChatReasoningMode` | **MEDIUM** |
| **Embeddings** | Not used | `sdk.models.text_embeddings` | LOW (if needed) |
| **TTS (speech synthesis)** | Not used | `sdk.speechkit.tts` with streaming, bidirectional | LOW (if needed) |
| **STT (speech recognition)** | Not used | `sdk.speechkit.stt` with real-time, deferred, streaming | LOW (if needed) |
| **Vision/image analysis** | Not used | Via multimodal models like `gemma-3-27b-it` | LOW (if needed) |
| **Tokenization** | Commented out | `model.tokenize()` -- returns `tuple[Token, ...]` | **MEDIUM** |
| **Deferred operations** | Used only for images | Available for text gen too (`run_deferred`) | **MEDIUM** |
| **Tuning** | Not used | Full tuning pipeline | LOW (if needed) |
| **Auth methods** | `YandexCloudCLIAuth` only | 7 auth methods including API key, IAM, OAuth, metadata | **MEDIUM** -- add API key auth |
| **Error handling** | `AioRpcError` only | Full exception hierarchy | **MEDIUM** |
| **Retry policy** | Not configured | `RetryPolicy(max_attempts, backoff, ...)` | LOW |

## Critical Implementation Constraint: `.configure()` Mutation

The single most important architectural issue for the refactoring.

### The Problem

`.configure()` **mutates the shared model object in place** and returns it. If
the same model instance is shared across concurrent callers (which it is in
our provider -- one `YcAIModel` instance per model name, serving all requests),
re-configuring between requests creates a race condition:

```python
# Thread 1: needs JSON output
model.configure(response_format="json")
result1 = await model.run(messages1)

# Thread 2: needs plain text (concurrently)
model.configure()  # clears response_format
result2 = await model.run(messages2)

# Race: Thread 2's configure() may run between Thread 1's configure() and run()
```

This is exactly why our current provider raises `NotImplementedError` for
structured output and tool calling -- it would require per-request
configuration, which is not safe with a shared mutable model.

### Mitigation Strategies

1. **Create separate model instances per configuration**

   ```python
   # Instead of sharing one model, create a new instance per config
   text_model = sdk.models.completions("yandexgpt").configure(temperature=0.7)
   json_model = sdk.models.completions("yandexgpt").configure(temperature=0.7, response_format="json")
   tool_model = sdk.models.completions("yandexgpt").configure(temperature=0.7, tools=[...])
   ```

   Pros: Simple, no race conditions.
   Cons: More model instances, higher resource usage, need to manage a pool.

2. **Use the chat domain instead of gRPC**

   The chat domain (`sdk.chat.completions`) uses HTTP, which may handle
   per-request configuration differently (each request is an independent HTTP
   POST). Need to verify whether `configure()` on a chat model also mutates
   the shared object or if the HTTP transport serializes the config into each
   request.

   Pros: OpenAI-compatible, access to open-source models, `extra_query`.
   Cons: Different transport, potentially different latency characteristics.

3. **Per-request model cloning**

   If the SDK supports it, clone the model before reconfiguring:
   ```python
   import copy
   model_copy = copy.deepcopy(model)
   model_copy.configure(response_format="json")
   result = await model_copy.run(messages)
   ```

   Need to verify whether `deepcopy` works on SDK model objects.

4. **Lock-based serialization (not recommended)**

   Use an asyncio Lock to serialize configure+run pairs:
   ```python
   async with self._configLock:
       self._ycModel.configure(response_format="json")
       result = await self._ycModel.run(messages)
       self._ycModel.configure()  # restore
   ```

   Pros: Works without extra instances.
   Cons: Serializes all requests to this model, defeats concurrency.

## Auth: Current vs Available

### Current Implementation

```python
# lib/ai/providers/yc_sdk_provider.py line 441
self._ycAISDK = AsyncAIStudio(
    folder_id=folder_id,
    auth=YandexCloudCLIAuth(),
    yc_profile=yc_profile,
)
```

Requires `yc` CLI installed and configured. This is fragile for production
deployments.

### Recommended: API Key Auth

```python
from yandex_ai_studio_sdk.auth import APIKeyAuth

sdk = AsyncAIStudio(
    folder_id="b1g...",
    auth=APIKeyAuth(api_key="AQVN..."),
)
```

API keys are:
- Long-lived (no periodic refresh needed)
- Scoped (can restrict to specific services)
- Not dependent on CLI tools
- The SDK's first auto-detection choice (`YC_API_KEY` env var)

### Other Auth Options

| Method | Use Case | Notes |
|---|---|---|
| `IAMTokenAuth` | Short-lived tokens from auth service | Must refresh every ~12h |
| `EnvIAMTokenAuth` | External token management | Re-reads from env on each call |
| `OAuthTokenAuth` | User-context auth | Emits warning, exchanges for IAM |
| `MetadataAuth` | YC VM deployments | Zero-config inside YC VMs |
| `YandexCloudCLIAuth` | Development only | Requires `yc` CLI installed |

## Error Handling: Current vs Available

### Current Implementation

```python
except AioRpcError as e:
    errorMsg = str(e.details())
    if errorMsg in ethicDetails:
        resultStatus = ModelResultStatus.CONTENT_FILTER
```

Only catches `AioRpcError`. Does not handle other SDK exceptions.

### Full Exception Hierarchy

```
AIStudioError
  +-- UnknownEndpointError        -- Bad endpoint configuration
  +-- AioRpcError                  -- gRPC errors (our current catch)
  +-- HttpSseError                 -- HTTP/SSE errors (chat domain)
  +-- AIStudioConfigurationError   -- SDK misconfiguration
  +-- RunError                     -- Model run failures
  |     +-- TuningError            -- Tuning-specific failures
  +-- AsyncOperationError          -- Deferred operation failures
        +-- WrongAsyncOperationStatusError  -- Operation in wrong state
        +-- DatasetValidationError           -- Invalid dataset for tuning
```

### Recommended Improvements

1. Catch `AIStudioError` as the base exception for all SDK errors
2. Handle `HttpSseError` specifically if using the chat domain
3. Map `RunError` details to our `ModelResultStatus` enum
4. Use `AsyncOperationError` for deferred operation failures
5. Consider `AIStudioConfigurationError` as a fatal initialization error

## Tokenization: Current vs Available

### Current (Commented Out)

```python
# lib/ai/providers/yc_sdk_provider.py lines 346-349
# def getEstimateTokensCount(self, data: Any) -> int:
#    if not self._yc_model:
#        raise RuntimeError("Model not initialized, dood!")
#    tokens = self._yc_model.tokenize(data)
#    return len(tokens)
```

### Available

```python
tokens: tuple[Token, ...] = await model.tokenize(messages, timeout=60)
count = len(tokens)
```

Tokenization is fully functional and returns detailed token information
(`id`, `special`, `text`). This is useful for:

- Pre-checking if a prompt fits within context limits
- Cost estimation before generation
- Token-level analysis of inputs

## Streaming: Not Implemented

Text generation streaming via `run_stream()` is available but not used in our
provider. Adding it would enable:

- Progressive output display (typewriter effect in chat)
- Lower time-to-first-token
- Better UX for long responses

```python
async for chunk in await model.run_stream(messages, timeout=180):
    yield chunk.text  # Stream to client
```

## Deferred Text Generation: Not Implemented

`run_deferred()` is available for text generation (not just images). This
would be useful for:

- Long-running generation requests that exceed gRPC timeout
- Batch processing of multiple prompts
- Offloading to background workers

```python
operation = await model.run_deferred(messages, timeout=60)
result = await operation  # Can poll later
```

## Missing OpenAI-Comparable Features

These SDK features have no equivalent in our provider's `AbstractModel`
interface:

| SDK Feature | OpenAI Equivalent | Our Interface Gap |
|---|---|---|
| `reasoning_mode` | `reasoning_effort` (o1/o3) | Not in `AbstractModel` |
| `tools` / `tool_calls` | `tools` / `tool_choice` | `LLMAbstractTool` exists but not wired for YC |
| `response_format` | `response_format` | `_generateStructured()` raises `NotImplementedError` |
| `run_stream()` | `stream=True` | No streaming in `AbstractModel` |
| `tokenize()` | Token counting API | Commented out |
| `sdk.chat` domain | N/A (this IS the compat layer) | Not exposed |

## Refactoring Priority Roadmap

### Phase 1: Unblock Structured Output and Tool Calling (HIGH)

1. Resolve the `.configure()` mutation problem (separate instances or chat domain)
2. Implement `_generateStructured()` using `response_format`
3. Wire `tools` parameter through `_generateText()`

### Phase 2: Auth and Error Handling (MEDIUM)

1. Add `APIKeyAuth` as the primary auth method
2. Keep `YandexCloudCLIAuth` as fallback for development
3. Catch `AIStudioError` hierarchy instead of just `AioRpcError`
4. Map SDK error types to `ModelResultStatus` values

### Phase 3: Streaming and Tokenization (MEDIUM)

1. Add `run_stream()` support for text generation
2. Uncomment and fix `tokenize()` / `getEstimateTokensCount()`
3. Add deferred text generation support

### Phase 4: Extended Features (LOW)

1. Evaluate chat domain (`sdk.chat.completions`) as alternative transport
2. Add image generation improvements (message weights, `attach_deferred()`)
3. Evaluate embeddings, TTS, STT if product needs arise
