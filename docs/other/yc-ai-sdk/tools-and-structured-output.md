# Tools & Structured Output

> **Version drift — 2026-07-18 audit:** Captured against SDK **v0.20.2**;
> [`requirements.direct.txt`](../../../requirements.direct.txt) now pins
> `yandex-ai-studio-sdk==0.22.0`. The `sdk.tools.*`, `tool_choice`, and
> `response_format` surfaces described here were **re-verified against the
> 0.22.0 install** during this audit (see "Audit findings" at the bottom).
> Production consumer:
> [`lib/ai/providers/yc_sdk_provider.py`](../../../lib/ai/providers/yc_sdk_provider.py)
> (`_convertTools`, `_convertMessages`, `_generateStructured`); tool-call
> healing loop in
> [`internal/services/llm/service.py`](../../../internal/services/llm/service.py)
> `generateTextViaLLM` + `_tryHealToolCall` (see
> [`docs/llm/memories/llm-tool-call-healing.md`](../../llm/memories/llm-tool-call-healing.md)).

Tool calling and structured output via `response_format`. These features are
available in both the gRPC `models.completions` domain and the HTTP
`sdk.chat.completions` domain.

## Function Tools

### Creating a Function Tool

```python
from yandex_ai_studio_sdk import AsyncAIStudio

sdk = AsyncAIStudio(folder_id="b1g...", auth=APIKeyAuth("..."))

# From a JSON Schema dict
weather_tool = sdk.tools.function(
    {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name"},
            "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
        },
        "required": ["city"],
    },
    name="get_weather",
    description="Get current weather for a city",
)

# From a pydantic BaseModel
from pydantic import BaseModel

class WeatherParams(BaseModel):
    city: str
    unit: str = "celsius"

weather_tool = sdk.tools.function(
    WeatherParams,
    name="get_weather",
    description="Get current weather for a city",
)

# From a pydantic dataclass
from pydantic import dataclasses as pydantic_dataclasses

@pydantic_dataclasses.dataclass
class SearchParams:
    query: str
    max_results: int = 10

search_tool = sdk.tools.function(
    SearchParams,
    name="search",
    description="Search the web",
)
```

### FunctionTool Signature

```python
sdk.tools.function(
    parameters,           # JSON Schema dict | pydantic BaseModel class | pydantic dataclass
    *,
    name=None,            # str | UNDEFINED  -- auto-inferred from JSON Schema "title" (pydantic class name)
    description=None,     # str | UNDEFINED  -- auto-inferred from JSON Schema "description" field if present
    strict=None,          # bool | UNDEFINED  -- strict schema validation
) -> FunctionTool
```

Returns a `FunctionTool(name, description, parameters, strict)` instance.

### Using Tools with a Model

```python
model = sdk.models.completions("yandexgpt").configure(
    temperature=0.7,
    tools=[weather_tool, search_tool],
    parallel_tool_calls=True,   # allow multiple tool calls in one response
    tool_choice="auto",         # "none" | "auto" | "required" | specific tool
)

result = await model.run([
    {"role": "user", "text": "What's the weather in Moscow?"},
])

if result.tool_calls:
    for call in result.tool_calls:
        print(f"Tool: {call.function.name}")
        print(f"Args:  {call.function.arguments}")  # already a dict, not a JSON string
        print(f"ID:    {call.id}")
```

### Tool Choice Options

| Value | Type | Description |
|---|---|---|
| `"none"` | `str` | Never call tools |
| `"auto"` | `str` | Model decides whether to call tools |
| `"required"` | `str` | Model must call at least one tool |
| `{"type": "function", "function": {"name": "get_weather"}}` | `dict` | Force a specific tool |
| `weather_tool` | `FunctionTool` | Force a specific tool (object form) |

### Feeding Tool Results Back

After receiving tool calls, execute the functions locally and feed the results
back as messages. **The two domains differ in the message shape** — pick the
one for the domain you actually call:

**gRPC `models.completions` domain (the production path):** all tool results
for a turn are bundled into a single `{"role": "user", "tool_results": [...]}`
message. Each entry is a `{"name": str, "content": str}` dict. The SDK's
`message_to_proto` rejects dicts without a `text` or `tool_results` key, so
the OpenAI-style "one `tool` message per result" pattern does **not** work
here.

```python
# First call: model requests tools
result = await model.run([
    {"role": "user", "text": "What's the weather in Moscow?"},
])

# Execute tool calls locally. call.function.arguments is already a dict —
# no json.loads() needed (BaseFunctionCall._from_proto / _from_json both
# return a parsed object).
tool_results = []
for call in result.tool_calls:
    if call.function.name == "get_weather":
        weather_data = get_weather_from_api(call.function.arguments)
        tool_results.append({
            "name": call.function.name,
            "content": json.dumps(weather_data),
        })

# Feed results back as a single bundled user message.
final_result = await model.run([
    {"role": "user", "text": "What's the weather in Moscow?"},
    # The assistant turn that requested the tools must be preserved so the
    # model can correlate the request with the results. In production this
    # is `_ModelMessageWToolCalls(...)` (see yc_sdk_provider.py) — a plain
    # dict cannot carry the protobuf tool_call_list, so the SDK's own
    # protocol object is required here.
    assistantTurnWithToolCalls,
    {"role": "user", "tool_results": tool_results},
])
```

**HTTP `sdk.chat.completions` domain (OpenAI-compatible):** one
`{"role": "tool", "tool_call_id": ..., "content": ...}` message per result,
matching the OpenAI Chat Completions wire format.

## Search Index Tool

Provides RAG (Retrieval-Augmented Generation) by querying pre-built search
indexes:

```python
search_tool = sdk.tools.search_index(
    indexes=["index-id-1", "index-id-2"],  # SearchIndex objects or string IDs
    max_num_results=5,                      # Max results to return
    rephraser=None,                         # Optional rephraser for query transformation
    call_strategy=None,                     # Search strategy
)
```

The model will automatically query these indexes when relevant to the user's
question.

## Generative Search Tool

AI-summarized answers with source citations, backed by Yandex Search:

```python
gen_search_tool = sdk.tools.generative_search(
    description="Search the web for current information",
    site=None,          # Restrict to specific site(s)
    host=None,          # Restrict to specific host(s)
    url=None,           # Restrict to specific URL(s)
    enable_nrfm_docs=None,  # Enable NRFM documents
    search_filters=None,    # e.g., [{'date': '<20250101'}, {'lang': 'ru'}]
)
```

Note: `site`, `host`, and `url` are mutually exclusive.

Internally delegates to `sdk.search_api.generative(...).as_tool(description=...)`.

## Structured Output

### `response_format='json'` -- JSON Mode

Sets `json_object=True` in the request. The model will output valid JSON.
You **must** mention JSON in the prompt for best results:

```python
model = sdk.models.completions("yandexgpt").configure(
    response_format="json",
    temperature=0.3,
)

result = await model.run([
    {"role": "user", "text": "List 3 colors as JSON with keys: name, hex"},
])
# result.text will be valid JSON
```

### `response_format` with JSON Schema -- Strict Schema Mode

Pass a dict with `json_schema`, `name`, and optionally `strict`:

```python
model = sdk.models.completions("yandexgpt").configure(
    response_format={
        "json_schema": {
            "type": "object",
            "properties": {
                "colors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "hex": {"type": "string"},
                        },
                        "required": ["name", "hex"],
                    },
                },
            },
            "required": ["colors"],
        },
        "name": "color_list",
        "strict": True,
    },
    temperature=0.3,
)

result = await model.run([
    {"role": "user", "text": "List 3 colors"},
])
# result.text conforms to the specified schema
```

### `response_format` with Pydantic Model

Pass a pydantic `BaseModel` class directly. The SDK auto-extracts the JSON
Schema:

```python
from pydantic import BaseModel

class ColorList(BaseModel):
    colors: list[dict[str, str]]

model = sdk.models.completions("yandexgpt").configure(
    response_format=ColorList,
    temperature=0.3,
)

result = await model.run([
    {"role": "user", "text": "List 3 colors"},
])
# result.text is JSON conforming to ColorList schema
data = ColorList.model_validate_json(result.text)
```

### Structured Output in Chat Domain

All structured output modes are also available via the chat domain:

```python
model = sdk.chat.completions("yandexgpt").configure(
    response_format=ColorList,  # same options: "json", schema dict, pydantic
    temperature=0.3,
)

result = await model.run([
    {"role": "user", "content": "List 3 colors"},
])
```

## Complete Example: Tool Calling with Structured Output

```python
from yandex_ai_studio_sdk import AsyncAIStudio
from yandex_ai_studio_sdk.auth import APIKeyAuth
from pydantic import BaseModel

sdk = AsyncAIStudio(folder_id="b1g...", auth=APIKeyAuth("..."))

# Define a tool
class CalculatorParams(BaseModel):
    """Perform a calculation."""
    expression: str

calculator_tool = sdk.tools.function(CalculatorParams)

# Configure model with tools
model = sdk.models.completions("yandexgpt-5.1").configure(
    temperature=0.3,
    tools=[calculator_tool],
    tool_choice="auto",
    max_tokens=2000,
)

# Step 1: User asks a question that requires the tool
result = await model.run([
    {"role": "user", "text": "What is 15 * 37 + 42?"},
])

# Step 2: Model requests a tool call
if result.tool_calls:
    call = result.tool_calls[0]
    assert call.function.name == "CalculatorParams"

    # Execute the tool locally. call.function.arguments is already a dict.
    args = call.function.arguments
    answer = eval(args["expression"])  # In production, use a safe evaluator

    # Step 3: Feed result back (gRPC completions domain: bundled tool_results)
    final_result = await model.run([
        {"role": "user", "text": "What is 15 * 37 + 42?"},
        assistantTurnWithToolCalls,  # preserve the assistant turn that carried the tool_call
        {"role": "user", "tool_results": [{"name": call.function.name, "content": str(answer)}]},
    ])
    print(final_result.text)  # "The answer is 597"
```

## Note: `.configure()` Concurrency — RESOLVED in production

`.configure()` mutates the shared model instance in place and returns it. If a
single SDK model object were reused across concurrent callers needing different
configurations (e.g. one request wants `response_format='json'`, another wants
`tools=[...]`), the calls would race and clobber each other.

**Resolution (already shipped):** `YcAIModel._getModel(**configOverrides)` in
[`lib/ai/providers/yc_sdk_provider.py`](../../../lib/ai/providers/yc_sdk_provider.py)
creates a **fresh** SDK model per request, configures it for that one call, and
discards it. There is no shared mutable model state between concurrent
requests, so structured output and tool calling are both unblocked. See
[Gap Analysis](gap-analysis.md) §".configure() Mutation — RESOLVED" for the
historical context.

---

## Audit findings (2026-07-18)

Re-verified against the installed `yandex-ai-studio-sdk==0.22.0` source under
`venv/lib/python*/site-packages/yandex_ai_studio_sdk/`. Findings:

**API surfaces confirmed unchanged in 0.22.0** (no edit needed):

- `sdk.tools.function(parameters, *, name, description, strict)` signature —
  `_tools/function.py:22-29`.
- `FunctionTool(name, description, parameters, strict)` shape —
  `_tools/tool.py:83-103`.
- `sdk.tools.search_index(indexes, *, max_num_results, rephraser, call_strategy)`
  — `_tools/domain.py:83-120`.
- `sdk.tools.generative_search(*, description, site, host, url, enable_nrfm_docs,
  search_filters)`; `site`/`host`/`url` mutually exclusive; delegates to
  `sdk.search_api.generative(...).as_tool(description=...)` —
  `_tools/domain.py:122-170`.
- `tool_choice` accepts `"none" | "auto" | "required"` (any casing),
  `{"type": "function", "function": {"name": ...}}` dict, or a `FunctionTool`
  instance — `_types/tools/tool_choice.py`.
- `GPTModelConfig` fields `temperature`, `max_tokens`, `reasoning_mode`,
  `response_format`, `tools`, `parallel_tool_calls`, `tool_choice` —
  `_models/completions/config.py:39-59`.
- `ChatModelConfig` inherits `GPTModelConfig` (so all structured-output and
  tool modes work in the chat domain too) —
  `_chat/completions/config.py:46-61`.
- `result.tool_calls` returns `ToolCallList | None`; iterable; each item has
  `.id`, `.function.name`, `.function.arguments` —
  `_models/completions/result.py:148-149`, `_tools/tool_call.py:28-47`,
  `_tools/function_call.py:21-46`.

**Drift fixed in place:**

1. **`call.function.arguments` was treated as a JSON string.** Both
   `_from_proto` (`MessageToDict(proto.arguments)`) and `_from_json`
   (`json.loads(raw_arguments)`) return a parsed `dict`. Removed the
   `json.loads(call.function.arguments)` calls in the "Using Tools with a
   Model" example, the "Feeding Tool Results Back" example, and the
   "Complete Example". Matches production `yc_sdk_provider.py:480`
   (`parameters=call.function.arguments` assigned directly).
2. **"Feeding Tool Results Back" used the OpenAI-style separate-message
   pattern** (`*tool_results` unpacked as `{"name", "content"}` dicts).
   `_models/completions/message.py:message_to_proto` rejects dicts without a
   `text` or `tool_results` key — the gRPC completions domain requires a
   single bundled `{"role": "user", "tool_results": [...]}` message (the
   production `_convertMessages` path in `yc_sdk_provider.py:330-370`).
   Rewrote the example to show the gRPC shape and added a one-liner for the
   chat-domain wire format.
3. **`description` auto-inference** was documented as "from pydantic class
   docstring". The SDK actually reads it from `schema.get('description')`
   (`_tools/function.py:49-52`), which pydantic does not populate from the
   class docstring by default. Corrected the comment.
4. **Closing "`.configure()` Concurrency Issue" section was stale.** It
   claimed the issue "is the critical issue blocking structured output and
   tool calling in our current provider"; `gap-analysis.md` records this as
   RESOLVED via per-request model creation in `YcAIModel._getModel()`.
   Rewrote to reflect the shipped resolution.
5. **Complete Example's feed-back step** had the same broken
   `{"name", "content"}` shape as #2; fixed to the bundled `tool_results`
   form for internal consistency.

**Surfaces NOT exercised by production** (kept as-is, low verification
priority): `sdk.tools.search_index`, `sdk.tools.generative_search`, and the
chat-domain tool-call wire format are documented but not used by
`yc_sdk_provider.py`. Treat their examples as SDK reference only, not as
battle-tested patterns.
