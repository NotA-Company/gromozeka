# YC SDK Provider Refactoring Plan

Refactoring `lib/ai/providers/yc_sdk_provider.py` to add tool calling,
structured output, proper model listing, and configurable authentication --
while staying on the gRPC domain (`sdk.models.completions`) and using
per-request model creation to avoid `.configure()` mutation issues.

---

## 1. Overview

The current `YcAIModel` creates one shared SDK model instance at init time,
calls `.configure(temperature=...)` once, and reuses that object for all
requests. Because `.configure()` mutates the shared model in place, we cannot
safely change `response_format`, `tools`, `tool_choice`, etc. per-request
without introducing race conditions under concurrency. This is why
`_generateStructured` raises `NotImplementedError` and `_generateText` rejects
the `tools` parameter.

The refactoring does four things:

1. **Per-request model creation** -- each `_generate*` call creates and
   configures a fresh `AsyncGPTModel` / `AsyncImageGenerationModel`, eliminating
   shared mutable state.
2. **Structured output** -- implements `_generateStructured` using
   `response_format` with a JSON Schema dict.
3. **Tool calling** -- wires `LLMAbstractTool` through to
   `sdk.tools.function()` and extracts `result.tool_calls` back to
   `LLMToolCall`.
4. **Configurable auth** -- adds `APIKeyAuth` as the primary
    method with `YandexCloudCLIAuth` as fallback.

Key constraint: we stay on the gRPC domain (`sdk.models.completions`) for
generation.

---

## 2. Design Decisions

### 2.1 Per-request model creation vs shared model

| Approach | Concurrency safety | Resource cost | Complexity |
|---|---|---|---|
| **Per-request creation** (chosen) | Safe -- no shared mutable state | Model creation is lightweight (config + gRPC stub) | Low -- just move `configure()` into a factory method |
| Shared model + lock | Safe but serializes all requests | Minimal | Medium -- asyncio Lock around configure+run pairs |
| Model pool keyed by config hash | Safe for repeated configs | Higher memory for pool | High -- pool management, eviction |

**Decision**: Per-request creation. The SDK creates model objects cheaply (just
stores config and creates a gRPC stub). No heavy initialization. This is the
simplest approach that eliminates the `.configure()` race condition entirely.

**Reference**: `docs/other/yc-ai-sdk/gap-analysis.md` section "Critical
Implementation Constraint: `.configure()` Mutation" outlines this problem and
lists per-request creation as the first mitigation strategy.

### 2.2 gRPC domain vs Chat/HTTP domain

| Aspect | gRPC (`sdk.models.completions`) | HTTP (`sdk.chat.completions`) |
|---|---|---|
| Protocol | Binary gRPC | HTTP/SSE |
| Streaming | gRPC streams | SSE |
| Deferred ops | `run_deferred()` | No |
| Tokenization | `tokenize()` | No |
| Fine-tuning | `tune()` | No |
| Model listing | No | `model.list()` |
| Open-source models | No | Yes |
| `.configure()` mutation | Same issue | Same issue |

**Decision**: Stay on gRPC for generation. We need deferred ops and
tokenization. The chat domain's only advantage is model listing, which we
handle via a direct HTTP call (see section 2.4). The OpenAI-compatible
provider (`YcOpenaiProvider`) already covers the chat domain use case.

### 2.3 `run_deferred` vs `run` for text generation

| Method | Blocking | Timeout control | Consistency with image gen |
|---|---|---|---|
| `run()` | Blocks until complete | 180s default | Different pattern from image gen |
| `run_deferred()` + `wait()` | Non-blocking start, then wait | 60s start + configurable wait | Same pattern as image gen |

**Decision**: Use `run_deferred()` + `await operation.wait()` for text
generation. This gives a consistent deferred pattern across all generation
types. The `run_deferred()` call submits the request and returns an
`AsyncOperation`; `wait()` polls until the result is ready. We can control
polling intervals and timeouts per-request.

## 3. Architecture Changes

### 3.1 YcAIModel changes

```
REMOVE:
  - _initModel()
  - self._ycModel

ADD:
  - self.modelId       (str, already exists via AbstractModel)
  - self.modelVersion   (str, already exists via AbstractModel)
  - self.ycSDK          (AsyncAIStudio, already stored)

  - _getModel(**configOverrides) -> AsyncGPTModel | AsyncImageGenerationModel
      Factory method: creates + configures a fresh SDK model per call.

MODIFY:
  - _generateText()    -- use _getModel(), accept tools, use run_deferred
  - _generateImage()   -- use _getModel(), keep run_deferred

IMPLEMENT:
  - _generateStructured() -- use _getModel(response_format=...), parse JSON

UNCOMMENT:
  - getEstimateTokensCount() -- use _getModel().tokenize()
```

#### 3.1.1 `_getModel(**configOverrides)` factory method

```python
def _getModel(
    self,
    **configOverrides: Any,
) -> AsyncGPTModel | AsyncImageGenerationModel:
    """Create and configure a fresh YC SDK model instance.

    Args:
        **configOverrides: Parameters passed to .configure().
            For text models: temperature, max_tokens, tools,
            tool_choice, parallel_tool_calls, response_format, reasoning_mode.
            For image models: seed, width_ratio, height_ratio, mime_type.

    Returns:
        A freshly configured AsyncGPTModel or AsyncImageGenerationModel.
    """
    if self.supportText:
        return self.ycSDK.models.completions(
            self.modelId, model_version=self.modelVersion
        ).configure(
            temperature=self.temperature,
            **configOverrides,
        )
    if self.supportImages:
        return self.ycSDK.models.image_generation(
            self.modelId, model_version=self.modelVersion
        ).configure(**configOverrides)

    raise ValueError(f"Model {self.modelId} has neither text nor image support")
```

Note: image generation kwargs (`width_ratio`, `height_ratio`, `seed`) are
already in `self._config` from `extraConfig`. The factory method should merge
them from `self._config` when creating an image model, just as `_initModel()`
does now.

#### 3.1.2 `_generateText` changes

Current flow (lines 177-235 of `yc_sdk_provider.py`):

```python
async def _generateText(self, messages, tools=None):
    if tools:
        raise NotImplementedError(...)
    result = await self._ycModel.run([m.toDict("text") for m in messages])
    # extract text + tokens from result
    return ModelRunResult(...)
```

New flow:

```python
async def _generateText(
    self,
    messages: Sequence[ModelMessage],
    tools: Optional[Sequence[LLMAbstractTool]] = None,
) -> ModelRunResult:
    if not self.supportText:
        raise NotImplementedError(...)

    configKwargs: Dict[str, Any] = {}

    if tools:
        configKwargs["tools"] = [
            _convertTool(t) for t in tools
        ]
        configKwargs["tool_choice"] = "auto"
        configKwargs["parallel_tool_calls"] = True

    model = self._getModel(**configKwargs)

    try:
        operation = await model.run_deferred(
            [m.toDict("text") for m in messages]
        )
        result = await operation.wait()

        # Extract token usage
        inputTokens = getattr(result.usage, "input_text_tokens", None)
        outputTokens = getattr(result.usage, "completion_tokens", None)
        totalTokens = getattr(result.usage, "total_tokens", None)

        # Extract tool calls
        toolCalls: List[LLMToolCall] = []
        resultStatus = self._statusToModelRunResultStatus(result.status)

        if result.tool_calls:
            resultStatus = ModelResultStatus.TOOL_CALLS
            for call in result.tool_calls:
                toolCalls.append(LLMToolCall(
                    id=call.id,
                    name=call.function.name,
                    parameters=json.loads(call.function.arguments),
                ))

        return ModelRunResult(
            result,
            resultStatus,
            result.alternatives[0].text,
            toolCalls=toolCalls,
            inputTokens=inputTokens,
            outputTokens=outputTokens,
            totalTokens=totalTokens,
        )

    except AIStudioError as e:
        return self._handleSDKError(e)
```

Key changes:
- No `self._ycModel` check (the factory always creates a fresh model).
- `tools` parameter is converted via `_convertTool()`.
- Uses `run_deferred` + `wait()` instead of `run()`.
- Extracts `tool_calls` from the result and maps status to
  `ModelResultStatus.TOOL_CALLS` when present.

#### 3.1.3 `_generateImage` changes

Minimal: replace `self._ycModel.run_deferred(...)` with
`self._getModel(...).run_deferred(...)`. Image config kwargs (`width_ratio`,
`height_ratio`, `seed`) are pulled from `self._config` and passed to
`_getModel()`.

```python
async def _generateImage(self, messages):
    if not self.supportImages:
        raise NotImplementedError(...)

    imageKwargs = {
        k: self._config[k]
        for k in ("width_ratio", "height_ratio", "seed")
        if k in self._config
    }

    try:
        model = self._getModel(**imageKwargs)
        operation = await model.run_deferred(
            [m.toDict("text", skipRole=True) for m in messages]
        )
        result = await operation.wait()
        # ... same result handling as current ...
    except AIStudioError as e:
        return self._handleSDKError(e)
```

#### 3.1.4 `_generateStructured` implementation

```python
async def _generateStructured(
    self,
    messages: Sequence[ModelMessage],
    schema: Dict[str, Any],
    *,
    schemaName: str = "response",
    strict: bool = True,
) -> ModelStructuredResult:
    if not self.supportText:
        raise NotImplementedError(...)

    model = self._getModel(
        response_format={
            "json_schema": schema,
            "name": schemaName,
            "strict": strict,
        },
        temperature=min(self.temperature, 0.3),  # structured output works better at low temp
    )

    try:
        operation = await model.run_deferred(
            [m.toDict("text") for m in messages]
        )
        result = await operation.wait()

        inputTokens = getattr(result.usage, "input_text_tokens", None)
        outputTokens = getattr(result.usage, "completion_tokens", None)
        totalTokens = getattr(result.usage, "total_tokens", None)

        rawText = result.alternatives[0].text
        data: Optional[Dict[str, Any]] = None
        status = ModelResultStatus.FINAL

        try:
            data = json.loads(rawText)
        except json.JSONDecodeError as parseErr:
            status = ModelResultStatus.ERROR
            return ModelStructuredResult(
                rawResult=result,
                status=status,
                resultText=rawText,
                data=None,
                error=parseErr,
                inputTokens=inputTokens,
                outputTokens=outputTokens,
                totalTokens=totalTokens,
            )

        return ModelStructuredResult(
            rawResult=result,
            status=status,
            resultText=rawText,
            data=data,
            inputTokens=inputTokens,
            outputTokens=outputTokens,
            totalTokens=totalTokens,
        )

    except AIStudioError as e:
        return self._handleSDKError(e, retType=ModelStructuredResult)
```

#### 3.1.5 Tokenization fix

Uncomment the existing `getEstimateTokensCount` method and adapt it:

```python
async def getEstimateTokensCount(self, data: Any) -> int:
    """Get estimated token count using the YC SDK tokenizer.

    Args:
        data: Messages or text to tokenize.

    Returns:
        Estimated token count.
    """
    model = self._getModel()
    tokens = await model.tokenize(data)
    return len(tokens)
```

Note: This changes the method from sync to async. Check callers -- if any
call it synchronously, they need updating. Currently, the base class
`AbstractModel.getEstimateTokensCount` is synchronous and uses a heuristic.
We should keep the heuristic as fallback and add a separate async method
(e.g. `getExactTokensCount`) rather than changing the sync method signature.

### 3.2 YcAIProvider changes

#### 3.2.1 Auth configuration

Current (line 441):

```python
self._ycAISDK = AsyncAIStudio(
    folder_id=folder_id,
    auth=YandexCloudCLIAuth(),
    yc_profile=yc_profile,
)
```

New:

```python
def _initSDK(self) -> None:
    folder_id = self.config.get("folder_id")
    if not folder_id:
        raise ValueError("folder_id is required for YC SDK provider")

    authType: str = self.config.get("auth_type", "auto")
    auth = self._resolveAuth(authType)

    ycProfile = self.config.get("yc_profile", None)
    self._ycAISDK = AsyncAIStudio(
        folder_id=folder_id,
        auth=auth,
        yc_profile=ycProfile,
    )

def _resolveAuth(self, authType: str) -> BaseAuth:
    """Resolve authentication method from config.

    Args:
        authType: One of "auto", "api_key", "iam_token", "yc_cli".

    Returns:
        A BaseAuth instance.

    Raises:
        ValueError: If auth_type is unknown or required env vars are missing.
    """
    if authType == "api_key":
        from yandex_ai_studio_sdk.auth import APIKeyAuth
        apiKey = self.config.get("api_key") or os.environ.get("YC_API_KEY")
        if not apiKey:
            raise ValueError("api_key auth_type requires api_key in config or YC_API_KEY env var")
        return APIKeyAuth(apiKey)

    if authType == "iam_token":
        from yandex_ai_studio_sdk.auth import IAMTokenAuth
        iamToken = self.config.get("iam_token") or os.environ.get("YC_IAM_TOKEN")
        if not iamToken:
            raise ValueError("iam_token auth_type requires iam_token in config or YC_IAM_TOKEN env var")
        return IAMTokenAuth(iamToken)

    if authType == "yc_cli":
        return YandexCloudCLIAuth()

    if authType == "auto":
        # Match SDK's auto-detection: YC_API_KEY > YC_IAM_TOKEN > yc CLI
        if os.environ.get("YC_API_KEY"):
            from yandex_ai_studio_sdk.auth import APIKeyAuth
            return APIKeyAuth(os.environ["YC_API_KEY"])
        if os.environ.get("YC_IAM_TOKEN"):
            from yandex_ai_studio_sdk.auth import IAMTokenAuth
            return IAMTokenAuth(os.environ["YC_IAM_TOKEN"])
        return YandexCloudCLIAuth()

    raise ValueError(f"Unknown auth_type: {authType}")
```

Config keys (added to `configs/00-defaults/providers.toml`):

```toml
[models.providers.yc-sdk]
type = "yc-sdk"
folder_id = "${YC_FOLDER_ID}"
# Auth: "auto" (default), "api_key", "iam_token", "yc_cli"
# auth_type = "auto"
# api_key = "${YC_API_KEY}"   # only if auth_type = "api_key"
# yc_profile = "default"      # only if auth_type = "yc_cli"
```

#### 3.2.2 Error handling

Add a unified error handler:

```python
def _handleSDKError(
    self,
    error: AIStudioError,
    *,
    retType: type = ModelRunResult,
) -> ModelRunResult | ModelStructuredResult:
    """Map SDK exceptions to ModelRunResult/ModelStructuredResult.

    Args:
        error: The caught AIStudioError (or subclass).
        retType: The result class to return (ModelRunResult or ModelStructuredResult).

    Returns:
        An error result with appropriate status.
    """
    resultStatus = ModelResultStatus.ERROR
    errorMsg = str(error)

    if isinstance(error, AioRpcError) and hasattr(error, "details"):
        errorMsg = str(error.details())
        ethicDetails = [
            "it is not possible to generate an image from this request "
            "because it may violate the terms of use",
        ]
        if errorMsg in ethicDetails:
            resultStatus = ModelResultStatus.CONTENT_FILTER
            logger.warning(f"Content filter error: '{errorMsg}'")

    if isinstance(error, RunError):
        # Map RunError codes to statuses if possible
        logger.error(f"RunError code={error.code}: {error.message}")

    logger.exception(error)
    return retType(
        rawResult=None,
        status=resultStatus,
        resultText=errorMsg,
        error=error,
    )
```

Import changes needed at top of file:

```python
from yandex_ai_studio_sdk.exceptions import AIStudioError, AioRpcError, RunError
```

### 3.3 AbstractModel base class

No changes needed. The `generateStructured()` method already checks
`self._config.get("support_structured_output", False)` before calling
`_generateStructured()`. We need to set this flag to `True` in the
`extraConfig` for models that support it.

This is a config change, not a code change.

---

## 4. Detailed Implementation Steps

### Phase 1: Per-request model creation (foundation)

This phase must land first and must not break any existing functionality.

1. **Remove `_initModel()` and `self._ycModel`** from `YcAIModel.__init__`.
   Store `self.ycSDK` only.

2. **Add `_getModel(**configOverrides)`** factory method to `YcAIModel`.
   For image models, merge `width_ratio`, `height_ratio`, `seed` from
   `self._config` into the kwargs before calling `.configure()`.

3. **Rewrite `_generateText`** to use `_getModel(temperature=self.temperature)`
   and `run_deferred` + `wait()`. Do NOT add tool handling yet -- keep the
   `raise NotImplementedError` for `tools` parameter temporarily.

4. **Rewrite `_generateImage`** to use `_getModel(**imageKwargs)`.

5. **Update tests**: mock `_getModel()` return value instead of
   `self._ycModel`. Ensure existing golden-data tests still pass.

6. **Benchmark**: compare latency of `run_deferred` + `wait()` vs the
   previous `run()`. If deferred adds >50ms overhead for text gen, consider
   keeping `run()` for the non-tool, non-structured path and using
   `run_deferred()` only when needed.

7. **Run `make format lint test`**.

### Phase 2: Structured output

1. **Update `yc-sdk-models.toml`**: set `support_structured_output = true`
   for text models (yandexgpt, yandexgpt-lite, etc.).

2. **Implement `_generateStructured`** as described in section 3.1.4.

3. **Add unit tests**:
   - Mock `_getModel()` returning a model whose `run_deferred` returns a
     `GPTModelResult` with valid JSON text. Verify `ModelStructuredResult.data`
   is the parsed dict.
   - Test with invalid JSON in the result text. Verify status is `ERROR`,
   `data` is `None`, `error` is a `JSONDecodeError`.

4. **Run `make format lint test`**.

### Phase 3: Tool calling

1. **Update `yc-sdk-models.toml`**: set `support_tools = true` for models
   that support it (yandexgpt, yandexgpt-lite, yandexgpt-pro, etc.).

2. **Implement `_convertTool()`** helper:

   ```python
   def _convertTool(tool: LLMAbstractTool) -> FunctionTool:
       """Convert our LLMAbstractTool to a YC SDK FunctionTool.

       Args:
           tool: An LLMAbstractTool instance (typically LLMToolFunction).

       Returns:
           A FunctionTool instance suitable for sdk.models.completions().configure(tools=...).
       """
       toolJson = tool.toJson()
       funcSpec = toolJson["function"]
       return sdk.tools.function(
           funcSpec["parameters"],  # JSON Schema dict
           name=funcSpec["name"],
           description=funcSpec["description"],
       )
   ```

   The key mapping: `LLMToolFunction.toJson()` produces an OpenAI-format
   dict where `parameters` is already a valid JSON Schema (`{"type":
   "object", "properties": {...}, "required": [...]}`). The SDK's
   `sdk.tools.function()` accepts the same JSON Schema dict as its first
   positional argument. The formats are directly compatible.

3. **Update `_generateText`** to convert `tools` parameter and pass to
   `_getModel()`. Extract `result.tool_calls` and convert to `LLMToolCall`.

4. **Handle tool result messages**: When the caller sends back a
   `ModelMessage` with `toolCallId`, it needs to be serialized in the format
   the YC SDK expects. The SDK uses `{"name": "<func_name>", "content":
   "<result>"}` for function result messages (see
   `docs/other/yc-ai-sdk/tools-and-structured-output.md` section "Feeding
   Tool Results Back"). Our `ModelMessage.toDict()` currently serializes
   `toolCallId` as `tool_call_id`. We may need to remap this at the point
   where we convert messages for the SDK:

   ```python
   def _convertMessages(self, messages: Sequence[ModelMessage]) -> List[Dict[str, Any]]:
       """Convert ModelMessage list to YC SDK format.

       Args:
           messages: Our message sequence.

       Returns:
           List of dicts in YC SDK format.
       """
       result = []
       for m in messages:
           d = m.toDict("text")
           # Remap tool result messages for YC SDK
           if m.toolCallId is not None:
               d = {"name": m.content, "content": m.content}
           result.append(d)
       return result
   ```

   **Note**: The exact mapping for tool result messages needs validation
   against the live SDK. The docs show `{"name": ..., "content": ...}` but
   the role may also need to be included. This is an open question (see
   section 9).

5. **Add unit tests**:
   - Test `_convertTool()` with `LLMToolFunction` instances.
   - Mock `_getModel()` with tools configured. Verify `tool_calls` in result
   are correctly converted to `LLMToolCall`.
   - Test tool result message conversion.

6. **Run `make format lint test`**.

### Phase 4: Auth improvements

1. **Add `auth_type` key** to `configs/00-defaults/providers.toml` under the
   `yc-sdk` provider section.

2. **Implement `_resolveAuth()`** as described in section 3.2.1.

3. **Update `_initSDK()`** to use `_resolveAuth()`.

4. **Add unit tests**:
   - Test each auth type resolution.
   - Test auto-detection order matches SDK's order.
   - Test missing env vars raise `ValueError`.

5. **Run `make format lint test`**.

### Phase 5: Tokenization and error handling

1. **Implement `getExactTokensCount()`** as a new async method (do NOT
   change the sync `getEstimateTokensCount` signature).

   ```python
   async def getExactTokensCount(self, data: Any) -> int:
       """Get exact token count using the YC SDK tokenizer.

       Args:
           data: Messages or text to tokenize.

       Returns:
           Exact token count.
       """
       model = self._getModel()
       tokens = await model.tokenize(data)
       return len(tokens)
   ```

2. **Replace `AioRpcError` catches** with `AIStudioError` catches throughout
   the file. Use `_handleSDKError()` from section 3.2.3.

3. **Add unit tests**:
   - Mock `model.tokenize()` return value.
   - Test `_handleSDKError()` with each exception subclass.

4. **Run `make format lint test`**.

---

## 5. Tool Conversion Details

### 5.1 Our format (from `LLMToolFunction.toJson()`)

```python
{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather for a city",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "description": "City name",
                    "type": "string",
                },
                "unit": {
                    "description": "Temperature unit",
                    "type": "string",
                    "enum": ["celsius", "fahrenheit"],
                },
            },
            "required": ["city"],
        },
    },
}
```

### 5.2 YC SDK format (from `sdk.tools.function()`)

```python
sdk.tools.function(
    parameters={                        # JSON Schema dict (same shape as above "parameters")
        "type": "object",
        "properties": {
            "city": {"description": "City name", "type": "string"},
            "unit": {"description": "Temperature unit", "type": "string", "enum": ["celsius", "fahrenheit"]},
        },
        "required": ["city"],
    },
    name="get_weather",                 # str
    description="Get current weather for a city",  # str
    strict=True,                        # bool | None  (default: UNDEFINED)
)
```

### 5.3 Conversion function

The `parameters` dict from `LLMToolFunction.toJson()["function"]["parameters"]`
is directly compatible with `sdk.tools.function(parameters=...)`. No schema
transformation is needed.

```python
def _convertTool(sdk: AsyncAIStudio, tool: LLMAbstractTool) -> FunctionTool:
    """Convert our LLMAbstractTool to a YC SDK FunctionTool.

    Args:
        sdk: The YC AI Studio SDK instance (needed for sdk.tools.function).
        tool: An LLMAbstractTool instance (typically LLMToolFunction).

    Returns:
        A FunctionTool instance for use with .configure(tools=[...]).
    """
    toolJson = tool.toJson()
    funcSpec = toolJson["function"]
    return sdk.tools.function(
        funcSpec["parameters"],
        name=funcSpec["name"],
        description=funcSpec["description"],
    )
```

The `sdk` instance must be passed in (or accessed via `self.ycSDK`) because
`sdk.tools.function()` is a method on the SDK object, not a standalone
constructor.

### 5.4 Tool call result extraction

The SDK returns `result.tool_calls` as a `ToolCallList` (or `None`). Each
element has:

| Field | Type | Description |
|---|---|---|
| `call.id` | `str` | Unique call identifier |
| `call.function.name` | `str` | Function name |
| `call.function.arguments` | `str` | JSON string of arguments |

Conversion to `LLMToolCall`:

```python
LLMToolCall(
    id=call.id,
    name=call.function.name,
    parameters=json.loads(call.function.arguments),
)
```

---

## 6. Message Format Details

### 6.1 Our format (from `ModelMessage.toDict("text")`)

```python
{"role": "user", "text": "Hello!"}
```

For messages with tool calls:

```python
{
    "role": "assistant",
    "text": "",
    "tool_calls": [
        {
            "id": "call_123",
            "function": {
                "name": "get_weather",
                "arguments": '{"city": "Moscow"}',
            },
            "type": "function",
        }
    ],
}
```

For tool result messages:

```python
{
    "role": "tool",
    "content": "22C, sunny",
    "tool_call_id": "call_123",
}
```

### 6.2 YC SDK format

The SDK accepts messages as dicts with `"role"` and `"text"` keys, or as
`TextMessage` objects:

```python
[
    {"role": "system", "text": "You are a helpful assistant"},
    {"role": "user", "text": "Hello!"},
]
```

Tool results are sent as function result messages (see
`docs/other/yc-ai-sdk/tools-and-structured-output.md` section "Feeding Tool
Results Back"):

```python
[
    {"role": "user", "text": "What's the weather in Moscow?"},
    {"role": "assistant", "text": result.text},  # assistant's response with tool_calls
    {"name": "get_weather", "content": "22C, sunny"},  # tool result
]
```

### 6.3 Conversion requirements

- For normal messages: `ModelMessage.toDict("text")` already produces the
  correct format (`role` + `text` keys).
- For assistant messages with tool calls: the SDK's `result.tool_calls`
  and `result.text` are the authoritative data. We should use
  `result.toModelMessage()` to get the assistant message, then serialize
  it via `toDict("text")`.
- For tool result messages: we store the function name in
  `ModelMessage.toolCallId`. When converting to SDK format, a message
  with `toolCallId` set becomes `{"name": toolCallId, "content": content}`.
  This is a natural mapping -- `toolCallId` identifies which tool's result
  this is, and the YC SDK uses the function name as the key in its
  `{"name": ..., "content": ...}` format.

---

## 7. Testing Strategy

### 7.1 Existing test infrastructure

- `tests/conftest.py` provides shared fixtures: `testDatabase`, `mockBot`,
  `mockConfigManager`, `resetLlmServiceSingleton` (autouse).
- `lib/ai/test_manager.py` uses `MockProvider` classes that mock
  `YcAIProvider`.
- Golden-data tests in `tests/lib_ai/golden/` use the `YcSdkModelWrapper`
  from `tests/lib_ai/model_wrappers.py`.

### 7.2 New test files

Create `lib/ai/providers/test_yc_sdk_provider.py` with:

| Test class | Tests |
|---|---|
| `TestYcSdkModelGetModel` | `_getModel()` creates fresh model each call; config is applied; image model kwargs merged from `self._config` |
| `TestYcSdkGenerateText` | Text gen without tools; text gen with tools (mock tool_calls in result); tool conversion round-trip; error handling |
| `TestYcSdkGenerateStructured` | Valid JSON result; invalid JSON result; `response_format` passed to `_getModel()` |
| `TestYcSdkGenerateImage` | Image gen with per-request model; content filter detection |
| `TestYcSdkAuth` | `auth_type="auto"` picks API key from env; `auth_type="api_key"` from config; `auth_type="yc_cli"`; missing env var raises `ValueError` |
| `TestYcSdkListModels` | Mock HTTP response; parse model list; handle API errors |
| `TestYcSdkTokenization` | `getExactTokensCount()` returns correct count; fallback `getEstimateTokensCount()` still works |
| `TestYcSdkErrorHandling` | `_handleSDKError` with `AioRpcError` + ethic details; `_handleSDKError` with `RunError`; `_handleSDKError` with generic `AIStudioError` |

### 7.3 Mocking strategy

Mock `self.ycSDK.models.completions()` and `self.ycSDK.models.image_generation()`
to return mock model objects with `.configure()` returning self and
`.run_deferred()` returning a mock `AsyncOperation` whose `wait()` returns a
canned `GPTModelResult` or `ImageGenerationModelResult`.

For `listRemoteModels()`, mock `httpx.AsyncClient.get()`.

### 7.4 Regression tests

- All existing golden-data tests must continue to pass unchanged.
- The `YcSdkModelWrapper` in `tests/lib_ai/model_wrappers.py` should work
  without modification (it just calls `YcAIProvider(config)`).

---

## 8. File Changes Summary

| File | Change type | Description |
|---|---|---|
| `lib/ai/providers/yc_sdk_provider.py` | **Major refactor** | Remove `_initModel`/`self._ycModel`, add `_getModel()`, implement `_generateStructured`, add tool conversion, update auth, improve error handling |
| `configs/00-defaults/providers.toml` | **Minor** | Add `auth_type` key under `yc-sdk` provider |
| `configs/00-defaults/yc-sdk-models.toml` | **Minor** | Add text models with `support_tools = true`, `support_structured_output = true` |
| `lib/ai/providers/test_yc_sdk_provider.py` | **New** | Unit tests for all new functionality |
| `docs/llm/libraries.md` | **Update** | Document new YC SDK provider capabilities |
| `docs/other/yc-ai-sdk/gap-analysis.md` | **Update** | Mark completed items in capability matrix |

### Files that may need updates depending on tool result message design

| File | Change type | Description |
|---|---|---|
| `lib/ai/models.py` | **Possible** | Add `toolName` field to `ModelMessage` if needed for SDK serialization |
| `lib/ai/abstract.py` | **Possible** | If `ModelMessage` changes, update any serialization in base class |

---

## 9. Risks and Open Questions

### 9.1 Model creation cost

**Risk**: Creating a new `AsyncGPTModel` per request may be more expensive
than assumed. If model creation involves gRPC channel setup or other heavy
operations, per-request creation could become a bottleneck.

**Mitigation**: The SDK reuses gRPC channels at the `AsyncAIStudio` level.
Model creation just stores config and gets a stub reference.

**Validation**: Profile with `cProfile` to check where time is spent.

### 9.2 Tool result message format

**Risk**: The mapping between our `ModelMessage` with `toolCallId` (which
stores the function name per the design decision) and the SDK's expected
`{"name": ..., "content": ...}` format needs to be tested end-to-end with
a real model call.

**Mitigation**: The mapping is straightforward -- `toolCallId` becomes the
`"name"` field, `content` becomes the `"content"` field. Implement and
validate with a live YC API call.

**Validation**: Write a test that feeds tool results back to the model
through the SDK and verify the model accepts the format.

### 9.3 Concurrent model creation

**Risk**: Multiple concurrent requests creating SDK model objects
simultaneously -- is this safe?

**Assessment**: Should be safe. Each model object is independent; the SDK
shares the underlying gRPC channel at the `AsyncAIStudio` level. No shared
mutable state is introduced by creating multiple models.

**Validation**: Run a concurrency test that creates 50+ models
simultaneously and verifies all produce correct results.

---

## 10. Acceptance Criteria

- [ ] `_generateText` works with tools, converts tool calls to `LLMToolCall`
- [ ] `_generateText` works without tools (backward compatible)
- [ ] `_generateStructured` produces valid `ModelStructuredResult` with parsed JSON
- [ ] `_generateStructured` returns `ERROR` status with `data=None` on JSON parse failure
- [ ] `_generateImage` still works with per-request model creation
- [ ] No shared mutable state -- each request gets its own model object
- [ ] Auth supports `api_key` (primary) and `yc_cli` (fallback) in addition to `auto`
- [ ] `getExactTokensCount()` returns accurate token counts via SDK tokenizer
- [ ] `getEstimateTokensCount()` (existing heuristic) still works as fallback
- [ ] All existing golden-data tests pass unchanged
- [ ] New tests cover: tool calling, structured output, auth resolution, tokenization, error handling
- [ ] `make format lint` passes
- [ ] `make test` passes
- [ ] `docs/other/yc-ai-sdk/gap-analysis.md` updated to reflect completed items
