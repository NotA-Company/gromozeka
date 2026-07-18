# Completions -- Text Generation

Text generation via the gRPC-based `models.completions` domain. This is the
primary interface for YandexGPT family models.

> **Version drift — 2026-07-18 audit:** Captured against SDK **v0.20.2**;
> [`requirements.direct.txt`](../../../requirements.direct.txt) now pins
> `yandex-ai-studio-sdk==0.22.0`. The gRPC completions surface was
> **re-verified against the 0.22.0 install** during this audit. Drift items
> resolved: `TextMessage` is **not** a top-level export (corrected import
> path); the `FunctionResultMessageDict` example used OpenAI-compat
> `{"name", "content"}` shape instead of the SDK's `{"role", "tool_results":
> [...]}` shape; `ReasoningMode` integer values were off-by-one
> (`DISABLED=1`, `ENABLED_HIDDEN=2`, plus the missing `REASONING_MODE_UNSPECIFIED=0`);
> `AlternativeStatus.UNKNOWN` / `USAGE` are SDK-only sentinels with ids
> `-1` / `-2` (not `6` / `7`); `tune_deferred()` / `tune()` gained
> `description`, `labels`, `tuning_type`, `scheduler`, `optimizer` and
> `tune_deferred()` does **not** take `poll_*` args; and `.configure()` is
> **immutable** in 0.22.0 (returns a new instance via `_config._replace`).
>
> Production consumer:
> [`lib/ai/providers/yc_sdk_provider.py`](../../../lib/ai/providers/yc_sdk_provider.py)
> (`YcAIModel._getModel` / `_generateText` / `_generateStructured` /
> `_convertTools` / `_convertMessages`); orchestration loop in
> [`internal/services/llm/service.py`](../../../internal/services/llm/service.py)
> `generateTextViaLLM`. The exercised subset is `models.completions(...)`,
> `.configure(...)`, `run_deferred()`, `operation.wait()`, and `tokenize()`.

See also: [Chat (OpenAI Compat)](chat-openai-compat.md) for the HTTP-based
alternative.

## Creating a Model

```python
from yandex_ai_studio_sdk import AsyncAIStudio

sdk = AsyncAIStudio(folder_id="b1g...", auth=APIKeyAuth("..."))

# Basic
model = sdk.models.completions("yandexgpt")

# With version
model = sdk.models.completions("yandexgpt", model_version="latest")

# Full URI passthrough (skips prefix construction)
model = sdk.models.completions("gpt://b1g.../yandexgpt/latest")
```

### URI Format

The SDK constructs model URIs as: `gpt://<folder_id>/<model_name>/<model_version>`

If the `model_name` already contains `://`, it is used verbatim (no prefix
construction).

### Available Models

#### YandexGPT Family (gRPC and Chat)

| Model Name | URI Pattern | Context Size | Notes |
|---|---|---|---|
| `yandexgpt` | `gpt://<fid>/yandexgpt/latest` | 8k (v3), 32k (v4/5) | Flagship model, versioned |
| `yandexgpt-lite` | `gpt://<fid>/yandexgpt-lite/latest` | 8k | Lightweight, fast |
| `yandexgpt-pro` | `gpt://<fid>/yandexgpt-pro/latest` | 32k | Pro variant |

#### YandexGPT v5 Family (gRPC and Chat)

| Model Name | URI Pattern | Context Size | Notes |
|---|---|---|---|
| `yandexgpt-5.1` | `gpt://<fid>/yandexgpt-5.1/latest` | 32k | Current flagship |
| `yandexgpt-5-pro` | `gpt://<fid>/yandexgpt-5-pro/latest` | 32k | Pro variant with reasoning |
| `yandexgpt-5-lite` | `gpt://<fid>/yandexgpt-5-lite/latest` | 32k | Lite variant |

#### Open-Source Models (Chat/OpenAI-compatible only)

| Model Name | Context Size | Notes |
|---|---|---|
| `deepseek-v32` | 128k | DeepSeek model |
| `qwen3-235b-a22b-fp8` | 256k | Qwen3 MoE |
| `qwen3.5-35b-a3b-fp8` | 256k | Qwen3.5 MoE |
| `gpt-oss-120b` | 128k | Open-source 120B |
| `gpt-oss-20b` | 128k | Open-source 20B |
| `gemma-3-27b-it` | 128k | Vision support, expires May 2026 |

#### Other Models

| Model Name | Context Size | Notes |
|---|---|---|
| `aliceai-llm` | 32k | Alice AI model |
| `speech-realtime-250923` | 32k | Realtime API model |

#### Fine-Tuned Models

Fine-tuned models use a suffix-based URI:

```python
# Fine-tuned model
model = sdk.models.completions("yandexgpt-lite/latest@<tuning-suffix>")
```

## Model Configuration

Call `.configure()` on a model instance to set generation parameters. Returns
`Self` for chaining.

```python
model = sdk.models.completions("yandexgpt").configure(
    temperature=0.7,
    max_tokens=2000,
    reasoning_mode="ENABLED_HIDDEN",
    response_format="json",
    tools=[...],
    parallel_tool_calls=True,
    tool_choice="auto",
)
```

### GPTModelConfig Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `temperature` | `float \| None` | UNDEFINED | Sampling randomness. Range [0, 1]. Higher = more random. |
| `max_tokens` | `int \| None` | UNDEFINED | Maximum output tokens. |
| `reasoning_mode` | `ReasoningModeType` | UNDEFINED | Chain-of-thought reasoning. See below. |
| `response_format` | `ResponseType` | UNDEFINED | Output format control. See [Tools & Structured Output](tools-and-structured-output.md). |
| `tools` | `Sequence[CompletionTool] \| CompletionTool` | UNDEFINED | Function tools for tool calling. See [Tools & Structured Output](tools-and-structured-output.md). |
| `parallel_tool_calls` | `bool \| None` | UNDEFINED | Allow parallel tool calls. Default `True` when tools present. |
| `tool_choice` | `ToolChoiceType \| None` | UNDEFINED | Tool selection policy. See [Tools & Structured Output](tools-and-structured-output.md). |

### Reasoning Mode

Defined on `yandex_ai_studio_sdk._models.completions.config.ReasoningMode`
(a `ProtoEnumBase, Enum`). Integer values come from the upstream protobuf
`ReasoningOptions.ReasoningMode`:

| Value | Int | Description |
|---|---|---|
| `ReasoningMode.REASONING_MODE_UNSPECIFIED` (or `0`) | 0 | Mode not set (treated as no reasoning) |
| `ReasoningMode.DISABLED` (or `1`) | 1 | No chain-of-thought |
| `ReasoningMode.ENABLED_HIDDEN` (or `2`) | 2 | Chain-of-thought enabled but hidden from output |

`reasoning_mode` accepts `int | str | ReasoningMode` (the `ReasoningModeType`
alias); the SDK coerces strings by name, so
`.configure(reasoning_mode="ENABLED_HIDDEN")` works equivalently to passing
the enum member.

On the chat domain, reasoning is expressed as effort levels: `"low"`,
`"medium"`, `"high"` -- see [Chat (OpenAI Compat)](chat-openai-compat.md).

### Note: `.configure()` Is Immutable in 0.22.0

`.configure()` does **not** mutate the receiver: it calls
`self._config._replace(**kwargs)` (frozen dataclass `_replace`, which returns a
new config) and constructs a **new** model instance via `self.__class__(...)`
(see `_types/model.py::BaseModel.configure`). The original model is left
untouched.

The "`.configure()` mutates the shared object" hazard described in earlier
versions of this doc applied to pre-0.22 SDK behavior and is what originally
drove our provider's per-request `_getModel()` pattern. The mutation risk is
gone, but the production pattern (`lib/ai/providers/yc_sdk_provider.py`) is
retained defensively: every `_generateText` / `_generateStructured` /
`_generateImage` call still builds a fresh model, so per-call overrides never
leak across requests even if the SDK regresses. See [Gap Analysis](gap-analysis.md).

## Execution Methods

All methods below are available on `AsyncGPTModel` (async variant). The sync
`GPTModel` has the same methods without `await`.

### `run()` -- Synchronous Generation

```python
result: GPTModelResult = await model.run(messages, *, timeout=180)
```

Blocks until the model finishes generating. Returns a `GPTModelResult`.

### `run_stream()` -- Streaming Generation

```python
async for chunk in await model.run_stream(messages, *, timeout=180):
    # chunk: GPTModelResult (partial)
    print(chunk.text, end="", flush=True)
```

Returns an `AsyncIterator[GPTModelResult]`. Each chunk contains a partial
alternative with `status=PARTIAL`, except the final chunk which has
`status=FINAL`.

### `run_deferred()` -- Deferred (Background) Generation

```python
operation: AsyncOperation[GPTModelResult] = await model.run_deferred(messages, *, timeout=60)
# Later:
result = await operation  # waits for completion
# Or with explicit polling:
result = await operation.wait(poll_interval=10, poll_timeout=3600)
```

Returns an `AsyncOperation[GPTModelResult]`. Useful for long-running requests.
See [AsyncOperation Pattern](#asyncoperation-pattern) below.

### `attach_deferred()` -- Attach to Existing Operation

```python
operation = model.attach_deferred(operation_id="...", timeout=60)
result = await operation
```

Re-attach to a previously started deferred operation by its ID.

### `tokenize()` -- Count Tokens

```python
tokens: tuple[Token, ...] = await model.tokenize(messages, *, timeout=60)
token_count = len(tokens)
```

Returns a tuple of `Token` dataclass instances. Each token has:

| Field | Type | Description |
|---|---|---|
| `id` | `int` | Token ID in the model vocabulary |
| `special` | `bool` | Whether this is a special token |
| `text` | `str` | The text this token represents |

### `tune_deferred()` and `tune()` -- Fine-Tuning

`tune_deferred()` returns an `AsyncTuningTask[AsyncGPTModel]` immediately and
does **not** poll -- it has no `poll_timeout` / `poll_interval` arguments
(those belong to the blocking `tune()` variant). Both methods gained
`description`, `labels`, `tuning_type`, `scheduler`, `optimizer` parameters
in SDK 0.22.0.

```python
# Async tuning -- returns immediately, caller polls/awaits the task
tuningTask: AsyncTuningTask = await model.tune_deferred(
    train_datasets,
    validation_datasets=UNDEFINED,
    name=UNDEFINED,
    description=UNDEFINED,
    labels=UNDEFINED,
    seed=UNDEFINED,
    lr=UNDEFINED,
    n_samples=UNDEFINED,
    additional_arguments=UNDEFINED,
    tuning_type=UNDEFINED,
    scheduler=UNDEFINED,
    optimizer=UNDEFINED,
    timeout=60,
)

# Blocking tuning (polls until complete, then returns a fresh tuned model)
tuned_model = await model.tune(
    train_datasets,
    validation_datasets=UNDEFINED,
    name=UNDEFINED,
    description=UNDEFINED,
    labels=UNDEFINED,
    seed=UNDEFINED,
    lr=UNDEFINED,
    n_samples=UNDEFINED,
    additional_arguments=UNDEFINED,
    tuning_type=UNDEFINED,
    scheduler=UNDEFINED,
    optimizer=UNDEFINED,
    timeout=60,
    poll_timeout=259200,   # 72h; class default is 72 * 60 * 60
    poll_interval=60,
)
```

Sentinel defaults are `UNDEFINED` (from `yandex_ai_studio_sdk._types.misc`),
not `None` -- `None` would clear an existing value, `UNDEFINED` means "not
passed". Omitting the kwarg is equivalent to passing `UNDEFINED`.

See [Embeddings & Other](embeddings-and-other.md) for dataset preparation.

### `langchain()` -- LangChain Wrapper

```python
lc_model = model.langchain(model_type="chat", timeout=60)
# Returns a ChatYandexGPT instance compatible with LangChain
```

### Method Availability Matrix

| Method | Async | Sync | Timeout (default) |
|---|---|---|---|
| `run()` | `await` | blocking | 180s |
| `run_stream()` | `async for` | `for` | 180s |
| `run_deferred()` | `await` | blocking | 60s |
| `attach_deferred()` | `await` | blocking | 60s |
| `tokenize()` | `await` | blocking | 60s |
| `tune_deferred()` | `await` | blocking | 60s (no `poll_*` args; returns `AsyncTuningTask`) |
| `tune()` | `await` | blocking | 60s request, `poll_timeout=259200s`, `poll_interval=60s` |
| `langchain()` | -- | -- | 60s |

## Message Format

Messages can be provided in multiple formats:

### String

```python
result = await model.run("Tell me a joke")
```

### TextMessage Object

`TextMessage` lives at `yandex_ai_studio_sdk._types.message.TextMessage` -- it
is **not** re-exported from the top-level package.

```python
from yandex_ai_studio_sdk._types.message import TextMessage

result = await model.run([
    TextMessage(role="system", text="You are a helpful assistant"),
    TextMessage(role="user", text="Hello!"),
])
```

### Dict

```python
result = await model.run([
    {"role": "system", "text": "You are a helpful assistant"},
    {"role": "user", "text": "Hello!"},
])
```

### FunctionResultMessageDict (Tool Results)

The gRPC completions domain expects tool results bundled under a `tool_results`
key on a single user-role message (the YC SDK awaits all tool calls in one
message, unlike the OpenAI-compat API where each result is its own message).
Each entry is a `ToolResultDictType` = `{"name": str, "content": str,
"type"?: str}`. This is the shape the production provider builds in
`YcAIModel._convertMessages()`.

```python
result = await model.run([
    {"role": "user", "text": "What is the weather?"},
    # ... assistant response with tool_calls (TextMessageWithToolCallsProtocol) ...
    {
        "role": "user",
        "tool_results": [
            {"name": "get_weather", "content": "22C, sunny"},
        ],
    },
])
```

The `FunctionResultMessageDict` TypedDict itself is
`{role: NotRequired[str], tool_results: Required[Iterable[ToolResultDictType]]}`
(see `_models/completions/message.py`).

## GPTModelResult

```python
@dataclass(frozen=True)
class GPTModelResult:
    alternatives: tuple[Alternative, ...]
    usage: CompletionUsage
    model_version: str
```

### Convenience Properties

All of the following delegate to `self.alternatives[0]`:

| Property | Type | Description |
|---|---|---|
| `.role` | `str` | Role of the first alternative |
| `.text` | `str` | Text of the first alternative |
| `.status` | `AlternativeStatus` | Status of the first alternative |
| `.tool_calls` | `ToolCallList \| None` | Tool calls from the first alternative |

### Alternative

Each alternative in `.alternatives` has:

| Field | Type | Description |
|---|---|---|
| `.role` | `str` | Message role (typically `"assistant"`) |
| `.text` | `str` | Generated text |
| `.status` | `AlternativeStatus` | Completion status (see below) |
| `.tool_calls` | `ToolCallList \| None` | Tool calls, if any |

### AlternativeStatus

Defined on `_models/completions/result.py`. Values `UNSPECIFIED`..`TOOL_CALLS`
mirror the protobuf `Alternative.ALTERNATIVE_STATUS_*` enum (ints 0-5).
`UNKNOWN` and `USAGE` are **SDK-only sentinels** with negative ids -- they do
**not** come from the proto and must not be used as wire values.

| Value | Int | Description |
|---|---|---|
| `UNSPECIFIED` | 0 | Status not set |
| `PARTIAL` | 1 | Partial (streaming) result |
| `TRUNCATED_FINAL` | 2 | Final but truncated by max_tokens |
| `FINAL` | 3 | Complete final result |
| `CONTENT_FILTER` | 4 | Content policy violation |
| `TOOL_CALLS` | 5 | Model is requesting tool calls |
| `UNKNOWN` | -1 | SDK sentinel: status code did not match any known proto value |
| `USAGE` | -2 | SDK sentinel: message carries only usage data (no alternative) |

### CompletionUsage

```python
@dataclass(frozen=True)
class CompletionUsage:
    input_text_tokens: int       # Tokens in the prompt
    completion_tokens: int       # Tokens in the completion
    total_tokens: int            # Total tokens (prompt + completion)
    reasoning_tokens: int        # Tokens used for reasoning (if reasoning_mode enabled)
```

## AsyncOperation Pattern

Deferred operations return `AsyncOperation[T]`. The pattern:

```python
# Start the operation
operation = await model.run_deferred(messages)

# Option 1: await directly
result = await operation

# Option 2: explicit wait with polling control
result = await operation.wait(poll_interval=10, poll_timeout=3600)

# Check status without waiting
status = await operation.get_status(timeout=60)

# Get result (if completed)
result = await operation.get_result(timeout=60)

# Cancel
await operation.cancel(timeout=60)
```

| Method | Description |
|---|---|
| `await operation` | Wait for completion (default `timeout=60`, `poll_interval=10s`, `poll_timeout=3600s`) |
| `operation.wait(*, timeout=60, poll_timeout=, poll_interval=)` | Explicit wait with polling control |
| `operation.get_status(*, timeout=60)` | Get current operation status |
| `operation.get_result(*, timeout=60)` | Get result (if completed); raises `RunError` if failed, `WrongAsyncOperationStatusError` if still running |
| `operation.cancel(*, timeout=60)` | Cancel the operation |

## Gaps vs OpenAI API

The YandexGPT completions API does **not** support these OpenAI parameters:

| OpenAI Parameter | YandexGPT Equivalent | Status |
|---|---|---|
| `stop` | None | Not available |
| `top_p` | None | Not available |
| `frequency_penalty` | None | Not available |
| `presence_penalty` | None | Not available |
| `logprobs` | None | Not available |
| `seed` | None (text gen) | Available for image gen only |
| `n` | None | Single alternative only |
| `user` | None | Not available |

The `reasoning_mode` parameter is YandexGPT-specific (no direct OpenAI
equivalent, though `reasoning_effort` in the chat domain is comparable to
OpenAI's o1/o3 reasoning levels).
