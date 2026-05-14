# Tools & Structured Output

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
    name=None,            # str | UNDEFINED  -- auto-inferred from pydantic class name
    description=None,     # str | UNDEFINED  -- auto-inferred from pydantic class docstring
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
        print(f"Args:  {call.function.arguments}")
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
back as messages:

```python
# First call: model requests tools
result = await model.run([
    {"role": "user", "text": "What's the weather in Moscow?"},
])

# Execute tool calls locally
tool_results = []
for call in result.tool_calls:
    if call.function.name == "get_weather":
        weather_data = get_weather_from_api(json.loads(call.function.arguments))
        tool_results.append({
            "name": call.function.name,
            "content": json.dumps(weather_data),
        })

# Feed results back
final_result = await model.run([
    {"role": "user", "text": "What's the weather in Moscow?"},
    {"role": "assistant", "text": result.text},
    *tool_results,
])
```

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

    # Execute the tool locally
    import json, ast
    args = json.loads(call.function.arguments)
    answer = eval(args["expression"])  # In production, use a safe evaluator

    # Step 3: Feed result back
    final_result = await model.run([
        {"role": "user", "text": "What is 15 * 37 + 42?"},
        {"name": call.function.name, "content": str(answer)},
    ])
    print(final_result.text)  # "The answer is 597"
```

## Important: `.configure()` Concurrency Issue

Because `.configure()` mutates the shared model instance, you cannot safely
re-configure between requests if the model is shared across concurrent
callers. This is the critical issue blocking structured output and tool
calling in our current provider. See [Gap Analysis](gap-analysis.md) for
mitigation strategies.
