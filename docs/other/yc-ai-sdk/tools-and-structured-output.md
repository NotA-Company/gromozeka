# Yandex Cloud AI Studio SDK Reference — Tools & Structured Output (verified against pinned v0.22.0, 2026-07-18)

> **Verified against pinned SDK v0.22.0** (re-captured 2026-07-18 from
> `venv/lib/python3.14/site-packages/yandex_ai_studio_sdk/`). Production
> consumers: `lib/ai/providers/yc_sdk_provider.py` (tool-call extraction in
> `_generateText`/`_convertMessages`/`_convertTools`);
> `internal/services/llm/service.py::_tryHealToolCall` (orchestrator-side
> healing loop, see `docs/llm/memories/llm-tool-call-healing.md`). Claims
> marked with ⚠ are server-side facts not checkable from the SDK source.

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
    strict=None,          # bool | UNDEFINED  -- ⚠ strict schema validation (server-side enforcement; the SDK only forwards the flag)
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

⚠ The model will automatically query these indexes when relevant to the user's
question (server-side routing; not checkable from the SDK source).

## Generative Search Tool

⚠ AI-summarized answers with source citations, backed by Yandex Search
(server-side behaviour; not checkable from the SDK source):

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

Sets `json_object=True` in the request. ⚠ The model will output valid JSON
(server-side). You **must** mention JSON in the prompt for best results
(server-side guidance, not enforced by the SDK):

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

The SDK also accepts a pydantic **dataclass** here (handled by the same
code path — see `_types/schemas.py:124-152`). Behaviour is identical to the
`BaseModel` case.

### Structured Output in Chat Domain

All structured output modes are also available via the chat domain:

```python
model = sdk.chat.completions("yandexgpt").configure(
    response_format=ColorList,  # same options: "json", schema dict, pydantic BaseModel, pydantic dataclass
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

## Note: `.configure()` Immutability — historical concern resolved

`.configure()` returns a **new** model instance with the updated config; it does
**not** mutate the receiver. The mechanism (verified at
`_types/model.py::BaseModel.configure`, v0.22.0) is
`self._config._replace(**kwargs)` (frozen dataclass `_replace`, which returns a
new config) followed by construction of a fresh model via
`self.__class__(...)`. The original model is left untouched. See
[Completions §".configure() Is Immutable in 0.22.0"](completions.md#note-configure-is-immutable-in-0220)
for the full mechanism.

The historical "`.configure()` mutates the shared object" hazard described in
earlier versions of this doc applied to pre-0.22 SDK behaviour and is what
originally drove our provider's per-request `_getModel()` pattern. The mutation
risk is gone, but the production pattern (`lib/ai/providers/yc_sdk_provider.py`)
is retained defensively: every `_generateText` / `_generateStructured` /
`_generateImage` call still builds a fresh model, so per-call overrides never
leak across requests even if the SDK regresses. See
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

---

## Re-verification pass (2026-07-18, Wave 12)

Walked through every residual concrete API claim not already touched by the
five Wave-11 fixes above, against the v0.22.0 source. Outcome:

**All previously-listed "API surfaces confirmed unchanged" entries
re-confirmed** — line numbers from the Wave-11 audit match the v0.22.0
install byte-for-byte:

- `sdk.tools.function` signature — `_tools/function.py:22-29`.
- `FunctionTool(name, description, parameters, strict)` dataclass —
  `_tools/tool.py:83-103` (fields at 96-103).
- `sdk.tools.search_index(indexes, *, max_num_results, rephraser,
  call_strategy)` — `_tools/domain.py:83-90` (return at 115-120).
- `sdk.tools.generative_search(*, description, site, host, url,
  enable_nrfm_docs, search_filters)` — `_tools/domain.py:122-131`.
- `site`/`host`/`url` mutual exclusion — docstring at `_tools/domain.py:143`
  **plus** runtime assertion at `_tools/generative_search.py:73`
  (`assert bool(kwargs.get('host')) + bool(kwargs.get('site')) +
  bool(kwargs.get('url')) <= 1`).
- Delegation to `sdk.search_api.generative(...).as_tool(description=...)` —
  `_tools/domain.py:163-170`. `as_tool()` itself lives at
  `_search_api/generative/generative.py:155-174` and returns a
  `GenerativeSearchTool`.
- `tool_choice` — `_types/tools/tool_choice.py:16-22, 28-47`. String form
  accepts any casing of `none`/`auto`/`required`; dict form
  `{"type": "function", "function": {"name": str[, "instruction": str]}}`
  (validated by `_types/tools/function.py:18-29`); `FunctionTool` instance
  form supported.
- `GPTModelConfig` 7 fields — `_models/completions/config.py:39-59`.
- `ChatModelConfig(GPTModelConfig)` inheritance —
  `_chat/completions/config.py:46-61`. Note: it **overrides** `reasoning_mode`
  (chat uses `low`/`medium`/`high`, not the completions enum) and `tools`
  (`tuple[CompletionTool, ...] | None` — narrower than the parent's
  `Sequence | CompletionTool | None`), and adds `extra_query`. Tool/structured-
  output modes still pass through.
- `result.tool_calls` returns `ToolCallList | None`, iterable via
  `TupleSequence`; each item exposes `.id: str | None`, `.function.name: str`,
  `.function.arguments: JsonObject` — `_models/completions/result.py:148-149`,
  `_tools/tool_call.py:28-47` (fields 42-45),
  `_tools/function_call.py:21-46` (fields 29-32).
- `_from_proto` for `BaseToolCall` sets `id=None` unconditionally in 0.22.0
  (`_tools/tool_call.py:60-64`); the gRPC completions wire does not carry a
  server-issued tool-call id in this SDK version. Production
  `yc_sdk_provider.py:478` falls back to `uuid.uuid4()` when `call.id` is
  falsy.
- Chat-domain tool-result wire format
  `{"role": "tool", "tool_call_id": str, "content": str}` (one message per
  result) — `_chat/completions/message.py:119-126`. The chat-domain converter
  also accepts the bundled `tool_results` shape and explodes it into
  per-result `tool` messages, mapping `name` → previously-seen
  `tool_call_id` (`_chat/completions/message.py:142-164`).
- `FunctionResultMessageDict = {role?: str, tool_results: [...]}` —
  `_models/completions/message.py:27-33`.
- Each tool-result entry is `ToolResultDictType = FunctionResultDict =
  {name: str, content: str, type?: str}` — `_tools/tool_result.py:38-48`.
  `tool_result_to_proto` (`_tools/tool_result.py:63-93`) requires both
  `name` and `content`; `type` defaults to `"function"` and is the only
  accepted value in this version.
- `_convertMessages` line range cited in fix #2 above (`yc_sdk_provider.py:
  330-370`) is still accurate.

**Newly added in this pass:**

- `response_format` also accepts a pydantic **dataclass** (same code path as
  `BaseModel`, `_types/schemas.py:124-152`). Previously undocumented;
  added a one-line note in the "Pydantic Model" subsection and updated the
  chat-domain options comment.

**Surfaces marked ⚠ in this pass** (server-side facts not verifiable from
the SDK source):

- "The model will automatically query these indexes when relevant" (search
  index RAG routing).
- "AI-summarized answers with source citations, backed by Yandex Search"
  (generative search output shape).
- "You must mention JSON in the prompt for best results" (json-mode server-
  side guidance; the SDK only sets `json_object=True`).
- "strict schema validation" semantics (the SDK forwards the `strict` flag
  only — `_tools/function.py:46`, `_tools/tool.py:136-147` — actual
  enforcement is server-side; for `sdk.assistants` the flag is not yet
  wired at all and raises `ValueError` if set).

No further code-level drift was found beyond the five Wave-11 fixes.
