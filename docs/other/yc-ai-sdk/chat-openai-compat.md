# Chat -- OpenAI-Compatible HTTP API

The `sdk.chat` domain provides an OpenAI-compatible HTTP API for text
generation and embeddings. This is an alternative to the gRPC-based
`sdk.models.completions` domain.

## Why Use the Chat Domain?

| Feature | gRPC (`models.completions`) | HTTP (`chat.completions`) |
|---|---|---|
| Protocol | gRPC (binary) | HTTP/SSE (text) |
| Streaming | gRPC streams | SSE (Server-Sent Events) |
| OpenAI compatibility | No | Yes |
| `extra_query` params | No | Yes |
| Reasoning mode | `DISABLED` / `ENABLED_HIDDEN` | `"low"` / `"medium"` / `"high"` |
| `run_deferred()` | Yes | No |
| `tokenize()` | Yes | No |
| `tune()` / `tune_deferred()` | Yes | No |
| OpenAI SDK interop | No | Yes (use `openai` Python library) |
| Models | All YandexGPT | All + open-source only models |

## Chat Completions

### Creating a Chat Model

```python
from yandex_ai_studio_sdk import AsyncAIStudio

sdk = AsyncAIStudio(folder_id="b1g...", auth=APIKeyAuth("..."))

model = sdk.chat.completions("yandexgpt", model_version="latest")
```

### Configuration

```python
model = sdk.chat.completions("yandexgpt-5.1").configure(
    temperature=0.7,
    max_tokens=2000,
    reasoning_mode="medium",       # Chat-specific: "low" | "medium" | "high"
    response_format="json",
    tools=[...],
    parallel_tool_calls=True,
    tool_choice="auto",
    extra_query={                   # Chat-specific: arbitrary additional params
        "top_p": 0.9,
    },
)
```

### ChatModelConfig Parameters

Inherits all `GPTModelConfig` parameters plus chat-specific ones:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `temperature` | `float \| None` | UNDEFINED | Sampling temperature [0, 1] |
| `max_tokens` | `int \| None` | UNDEFINED | Max output tokens |
| `reasoning_mode` | `ChatReasoningModeType \| None` | UNDEFINED | `"low"`, `"medium"`, `"high"` |
| `response_format` | `ResponseType \| None` | UNDEFINED | Same as gRPC: `"json"`, schema dict, pydantic model |
| `tools` | `Sequence[CompletionTool] \| CompletionTool` | UNDEFINED | Same function tools as gRPC |
| `parallel_tool_calls` | `bool \| None` | UNDEFINED | Allow parallel tool calls |
| `tool_choice` | `ToolChoiceType \| None` | UNDEFINED | Same as gRPC |
| `extra_query` | `QueryType \| None` | UNDEFINED | **Chat-specific**: arbitrary dict merged into the JSON body |

### ChatReasoningMode

```python
class ChatReasoningMode(str, Enum):
    LOW = "low"        # Minimal reasoning
    MEDIUM = "medium"  # Moderate reasoning
    HIGH = "high"      # Maximum reasoning
```

The `ChatReasoningModeType` accepts these values in any casing:
`"low"`, `"medium"`, `"high"`, `"LOW"`, `"MEDIUM"`, `"HIGH"`, or
`ChatReasoningMode` enum members.

This maps to `reasoning_effort` in the JSON body sent to the API.

### `extra_query` Parameter

Arbitrary additional query parameters merged directly into the request JSON
body. This is useful for passing parameters not exposed in the SDK's
type-safe interface:

```python
model = sdk.chat.completions("yandexgpt-5.1").configure(
    temperature=0.7,
    extra_query={
        "top_p": 0.9,
        "custom_param": "value",
    },
)
```

### Execution Methods

```python
# Synchronous generation
result: ChatModelResult = await model.run(messages, timeout=180)

# Streaming generation
async for chunk in await model.run_stream(messages, timeout=180):
    print(chunk.text, end="", flush=True)
```

### Listing Available Models

```python
models = await model.list(timeout=60, filters=None)
# Returns tuple of available model info
```

### Message Format

Chat messages use a slightly different dict format (with `"content"` instead of
`"text"`):

```python
# Chat-style messages
result = await model.run([
    {"role": "system", "content": "You are a helpful assistant"},
    {"role": "user", "content": "Hello!"},
])

# Or with TextMessage objects
result = await model.run([
    TextMessage(role="system", text="You are a helpful assistant"),
    TextMessage(role="user", text="Hello!"),
])
```

### ChatModelResult

Same structure as `GPTModelResult`:

```python
@dataclass(frozen=True)
class ChatModelResult:
    alternatives: tuple[Alternative, ...]
    usage: CompletionUsage
    model_version: str
```

With the same convenience properties (`.text`, `.role`, `.status`,
`.tool_calls`).

## Chat Text Embeddings

```python
model = sdk.chat.text_embeddings("doc")
result = await model.run("Hello, world!", timeout=60)
# Same result as gRPC embeddings
```

## OpenAI-Compatible Endpoint

The chat domain uses the following endpoint:

```
https://ai.api.cloud.yandex.net/v1
```

This endpoint is compatible with the OpenAI Python SDK and other
OpenAI-compatible tools:

### Using the OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://ai.api.cloud.yandex.net/v1",
    api_key="your-yc-api-key",  # Yandex Cloud API key
)

response = client.chat.completions.create(
    model="gpt://b1g.../yandexgpt/latest",
    messages=[
        {"role": "user", "content": "Hello!"},
    ],
)
```

### Compatible Tools

| Tool | Compatibility |
|---|---|
| OpenAI Python SDK | Full chat completions, streaming, tool calling |
| SourceCraft | Supported |
| Roo Code | Supported |
| Any OpenAI-compatible client | Should work with `base_url` override |

## Models Available Only via Chat

These open-source models are **only** accessible through the chat domain (or
OpenAI-compatible endpoint), not through gRPC completions:

| Model | Context Size | Notes |
|---|---|---|
| `deepseek-v32` | 128k | DeepSeek model |
| `qwen3-235b-a22b-fp8` | 256k | Qwen3 MoE |
| `qwen3.5-35b-a3b-fp8` | 256k | Qwen3.5 MoE |
| `gpt-oss-120b` | 128k | Open-source 120B |
| `gpt-oss-20b` | 128k | Open-source 20B |
| `gemma-3-27b-it` | 128k | Vision support, expires May 2026 |

## Complete Example

```python
from yandex_ai_studio_sdk import AsyncAIStudio
from yandex_ai_studio_sdk.auth import APIKeyAuth
from pydantic import BaseModel

sdk = AsyncAIStudio(folder_id="b1g...", auth=APIKeyAuth("..."))

# Define structured output
class Summary(BaseModel):
    """A summary of a text."""
    title: str
    key_points: list[str]
    word_count: int

# Create chat model with structured output and reasoning
model = sdk.chat.completions("yandexgpt-5.1").configure(
    temperature=0.3,
    reasoning_mode="high",
    response_format=Summary,
    max_tokens=4000,
)

# Generate
result = await model.run([
    {"role": "user", "content": "Summarize the following text: ..."},
])

# Parse result
summary = Summary.model_validate_json(result.text)
print(f"Title: {summary.title}")
print(f"Key points: {summary.key_points}")
print(f"Word count: {summary.word_count}")

# Streaming
async for chunk in await model.run_stream([
    {"role": "user", "content": "Tell me about YandexGPT"},
]):
    print(chunk.text, end="", flush=True)
```

## Comparison: gRPC vs Chat

| Aspect | gRPC (`models.completions`) | HTTP (`chat.completions`) |
|---|---|---|
| Protocol overhead | Lower (binary) | Higher (HTTP/JSON) |
| Streaming | gRPC streams | SSE |
| Latency | Typically lower | Slightly higher |
| Ecosystem | YC SDK only | OpenAI-compatible |
| `extra_query` | No | Yes |
| Reasoning mode | `DISABLED`/`ENABLED_HIDDEN` | `"low"`/`"medium"`/`"high"` |
| Deferred ops | Yes | No |
| Tokenization | Yes | No |
| Fine-tuning | Yes | No |
| Open-source models | No | Yes |
| `.configure()` mutation | Same issue | Same issue |
