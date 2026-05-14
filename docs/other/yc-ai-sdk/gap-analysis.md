# Gap Analysis -- Current Provider vs SDK Capabilities

Comparison of what our existing YC SDK provider (`lib/ai/providers/yc_sdk_provider.py`)
uses versus what the SDK (v0.20.2) makes available. Intended to guide the
refactoring effort.

## Capability Matrix

| Capability | Currently Used | Available in SDK | Status | Notes |
|---|---|---|---|---|
| **Text generation** | `run_deferred()` + `await operation.wait()` | `run()`, `run_stream()`, `run_deferred()`, `tokenize()` | **Implemented** | Uses `run_deferred()` consistently; streaming not yet added |
| **Image generation** | `AsyncImageGenerationModel.run_deferred()` | Same + `attach_deferred()` | **Implemented** | Per-request model creation; `attach_deferred()` not used |
| **Structured output** | `_generateStructured()` via `response_format` | `response_format='json'`, JSON Schema, pydantic | **Implemented** | Uses `response_format={"json_schema": schema, "name": ..., "strict": ...}`; lowers temperature to min(configured, 0.3) |
| **Tool/function calling** | `_convertTools()`, `_convertMessages()`, tool_calls extraction | `sdk.tools.function()`, tool_choice, parallel_tool_calls | **Implemented** | `_generateText(tools=[...])` wires `LLMAbstractTool` → `FunctionTool`; extracts `LLMToolCall` from `result.tool_calls`; sets `tool_choice="auto"`, `parallel_tool_calls=True` |
| **Model config** | Per-request `_getModel(**configOverrides)` | `max_tokens`, `reasoning_mode`, `response_format`, `tools`, `parallel_tool_calls`, `tool_choice` | **Implemented** | Per-request model creation avoids `.configure()` mutation; `max_tokens`, `reasoning_mode` not yet exposed in `extraConfig` |
| **Chat API (OpenAI-compat)** | Not used | Full `sdk.chat.completions` with `extra_query`, `ChatReasoningMode` | **Not used** | gRPC domain (`sdk.models.completions`) preferred; chat domain available as fallback |
| **Embeddings** | Not used | `sdk.models.text_embeddings` | Not used | Low priority |
| **TTS (speech synthesis)** | Not used | `sdk.speechkit.tts` with streaming, bidirectional | Not used | Low priority |
| **STT (speech recognition)** | Not used | `sdk.speechkit.stt` with real-time, deferred, streaming | Not used | Low priority |
| **Vision/image analysis** | Not used | Via multimodal models like `gemma-3-27b-it` | Not used | Low priority |
| **Tokenization** | `getExactTokensCount()` via `model.tokenize()` | `model.tokenize()` -- returns `tuple[Token, ...]` | **Implemented** | Uses SDK tokenizer; falls back to heuristic `getEstimateTokensCount()` if unavailable |
| **Deferred operations** | Used for text and image generation | Available for all model types | **Implemented** | `run_deferred()` + `await operation.wait()` for all generation |
| **Tuning** | Not used | Full tuning pipeline | Not used | Low priority |
| **Auth methods** | `auto`, `api_key`, `iam_token`, `yc_cli` | 7 auth methods including API key, IAM, OAuth, metadata | **Implemented** | `_resolveAuth()` supports `auto` (env-var detection), `api_key`, `iam_token`, `yc_cli`; OAuth and metadata auth not yet exposed |
| **Error handling** | `_handleSDKError()` catches `AIStudioError` | Full exception hierarchy | **Implemented** | Catches `AIStudioError`; maps `AioRpcError` details (content filter → `CONTENT_FILTER`); logs `RunError` specifically |
| **Retry policy** | Not configured | `RetryPolicy(max_attempts, backoff, ...)` | Not used | Low priority |

## Critical Implementation Constraint: `.configure()` Mutation — RESOLVED

The single most important architectural issue for the refactoring.

### The Problem (Historical)

`.configure()` **mutates the shared model object in place** and returns it. If
the same model instance is shared across concurrent callers (which it was in
our old provider -- one `YcAIModel` instance per model name, serving all requests),
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

This is exactly why the old provider raised `NotImplementedError` for
structured output and tool calling -- it would require per-request
configuration, which was not safe with a shared mutable model.

### Resolution

**Chosen approach: per-request model creation** (Mitigation Strategy 1).
Each `_generate*` call creates a fresh SDK model via `_getModel(**configOverrides)`,
configures it for that specific request, and discards it after. The SDK
creates model objects cheaply (just stores config and gets a gRPC stub
reference). No shared mutable state exists between concurrent requests.

```python
# Current implementation
def _getModel(self, **configOverrides):
    kwargs = {"temperature": self.temperature}
    kwargs.update(configOverrides)
    return self.ycSDK.models.completions(self.modelId, ...).configure(**kwargs)
```

## Auth: Current vs Available — RESOLVED

### Current Implementation (Updated)

```python
# lib/ai/providers/yc_sdk_provider.py
# _resolveAuth() method supports multiple auth methods via auth_type config:

# auth_type="auto" (default): env-var detection
#   YC_API_KEY → APIKeyAuth
#   YC_IAM_TOKEN → IAMTokenAuth
#   fallback → YandexCloudCLIAuth

# auth_type="api_key": APIKeyAuth from config.api_key or YC_API_KEY env var
# auth_type="iam_token": IAMTokenAuth from config.iam_token or YC_IAM_TOKEN env var
# auth_type="yc_cli": YandexCloudCLIAuth
```

API key auth is now the recommended primary method for production.

### Implemented Auth Methods

| Method | `auth_type` value | Use Case | Notes |
|---|---|---|---|
| `APIKeyAuth` | `"api_key"` or `"auto"` (with `YC_API_KEY` env) | Production | Long-lived, no refresh needed, not CLI-dependent |
| `IAMTokenAuth` | `"iam_token"` or `"auto"` (with `YC_IAM_TOKEN` env) | Short-lived tokens | Must refresh every ~12h |
| `YandexCloudCLIAuth` | `"yc_cli"` or `"auto"` (fallback) | Development | Requires `yc` CLI installed |

### Not Yet Exposed

| Method | Use Case | Notes |
|---|---|---|
| `EnvIAMTokenAuth` | External token management | Re-reads from env on each call |
| `OAuthTokenAuth` | User-context auth | Emits warning, exchanges for IAM |
| `MetadataAuth` | YC VM deployments | Zero-config inside YC VMs |

## Error Handling: Current vs Available — RESOLVED

### Current Implementation (Updated)

```python
# lib/ai/providers/yc_sdk_provider.py
# All generation methods catch AIStudioError and delegate to _handleSDKError():

except AIStudioError as e:
    return self._handleSDKError(e)

# _handleSDKError() maps:
# - AioRpcError with ethic details → ModelResultStatus.CONTENT_FILTER
# - RunError → logs code/message specifically
# - All other AIStudioError → ModelResultStatus.ERROR with error text
```

### Full Exception Hierarchy (Reference)

```
AIStudioError
  +-- UnknownEndpointError        -- Bad endpoint configuration
  +-- AioRpcError                  -- gRPC errors (mapped to CONTENT_FILTER on ethic violations)
  +-- HttpSseError                 -- HTTP/SSE errors (chat domain -- not used yet)
  +-- AIStudioConfigurationError   -- SDK misconfiguration
  +-- RunError                     -- Model run failures (logged with code/message)
  |     +-- TuningError            -- Tuning-specific failures
  +-- AsyncOperationError          -- Deferred operation failures
        +-- WrongAsyncOperationStatusError  -- Operation in wrong state
        +-- DatasetValidationError           -- Invalid dataset for tuning
```

### Remaining Improvements

1. Handle `HttpSseError` specifically when/if the chat domain is adopted
2. Map `RunError.code` to more granular `ModelResultStatus` values
3. Treat `AIStudioConfigurationError` as a fatal initialization error

## Tokenization: Current vs Available — RESOLVED

### Current Implementation (Updated)

```python
# lib/ai/providers/yc_sdk_provider.py
# getExactTokensCount() method:
model = self._getModel()
tokenizeMethod = getattr(model, "tokenize", None)
if tokenizeMethod is None or not inspect.iscoroutinefunction(tokenizeMethod):
    return self.getEstimateTokensCount(data)
tokens = await tokenizeMethod(data)
return len(tokens)
```

Falls back to the heuristic `getEstimateTokensCount()` if `tokenize()` is
unavailable on the model (e.g., image-generation models).

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

## Remaining Interface Gaps

| SDK Feature | OpenAI Equivalent | Our Interface Status |
|---|---|---|
| `reasoning_mode` | `reasoning_effort` (o1/o3) | Not in `AbstractModel` (low priority) |
| `run_stream()` | `stream=True` | No streaming in `AbstractModel` (medium priority) |
| `sdk.chat` domain | N/A (this IS the compat layer) | Not exposed (low priority — gRPC domain works) |
| `max_tokens` | `max_tokens` | Not exposed in `extraConfig` yet |
| `RetryPolicy` | N/A | Not configured (low priority) |

## Refactoring Priority Roadmap

### Phase 1: Unblock Structured Output and Tool Calling — COMPLETED

1. ~~Resolve the `.configure()` mutation problem (separate instances or chat domain)~~ → Per-request model creation via `_getModel()`
2. ~~Implement `_generateStructured()` using `response_format`~~ → Implemented with JSON Schema + temperature lowering
3. ~~Wire `tools` parameter through `_generateText()`~~ → `_convertTools()`, `tool_choice="auto"`, `LLMToolCall` extraction

### Phase 2: Auth and Error Handling — COMPLETED

1. ~~Add `APIKeyAuth` as the primary auth method~~ → `_resolveAuth()` supports `api_key`, `iam_token`, `yc_cli`, `auto`
2. ~~Keep `YandexCloudCLIAuth` as fallback for development~~ → Fallback in `auto` mode
3. ~~Catch `AIStudioError` hierarchy instead of just `AioRpcError`~~ → `_handleSDKError()` catches `AIStudioError`
4. ~~Map SDK error types to `ModelResultStatus` values~~ → Content filter → `CONTENT_FILTER`, `RunError` logged

### Phase 3: Streaming and Tokenization — PARTIALLY COMPLETED

1. ~~Add `run_stream()` support for text generation~~ → Not yet implemented (streaming API)
2. ~~Uncomment and fix `tokenize()` / `getEstimateTokensCount()`~~ → `getExactTokensCount()` implemented with SDK tokenizer
3. ~~Add deferred text generation support~~ → `run_deferred()` + `await operation.wait()` already used for all generation

### Phase 4: Extended Features (LOW priority)

1. Evaluate chat domain (`sdk.chat.completions`) as alternative transport
2. Add image generation improvements (message weights, `attach_deferred()`)
3. Evaluate embeddings, TTS, STT if product needs arise
4. Expose `max_tokens` and `reasoning_mode` in `extraConfig`
