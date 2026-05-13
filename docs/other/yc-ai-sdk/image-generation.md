# Image Generation -- YandexART

Image generation via the `models.image_generation` domain using the YandexART
model family.

## Creating a Model

```python
from yandex_ai_studio_sdk import AsyncAIStudio

sdk = AsyncAIStudio(folder_id="b1g...", auth=APIKeyAuth("..."))

model = sdk.models.image_generation("yandex-art", model_version="latest")
# URI: art://<folder_id>/yandex-art/latest
```

### URI Format

`art://<folder_id>/<model_name>/<model_version>`

As with completions, if the model name contains `://`, it is used verbatim.

### Available Models

| Model Name | URI Pattern | Notes |
|---|---|---|
| `yandex-art` | `art://<fid>/yandex-art/latest` | Original YandexART |
| `yandex-art-2.0` | `art://<fid>/yandex-art-2.0/latest` | YandexART 2.0 |

## Model Configuration

```python
model = sdk.models.image_generation("yandex-art").configure(
    seed=42,           # Random seed for reproducibility
    width_ratio=1,     # Width ratio
    height_ratio=1,    # Height ratio
    mime_type="image/jpeg",  # Output format
)
```

### ImageGenerationModelConfig Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `seed` | `int \| None` | UNDEFINED | Random seed for reproducible generation |
| `width_ratio` | `int \| None` | UNDEFINED | Width ratio for the output image |
| `height_ratio` | `int \| None` | UNDEFINED | Height ratio for the output image |
| `mime_type` | `str \| None` | UNDEFINED | Output MIME type (e.g., `"image/jpeg"`) |

## Execution Methods

### `run_deferred()` -- Asynchronous Image Generation

Image generation is **only available as a deferred operation**. There is no
sync `run()` or `run_stream()`.

```python
# Start generation
operation: AsyncOperation[ImageGenerationModelResult] = await model.run_deferred(
    messages,
    timeout=60,
)

# Wait for completion
result: ImageGenerationModelResult = await operation

# Or with explicit polling
result = await operation.wait(poll_interval=5, poll_timeout=300)
```

### `attach_deferred()` -- Attach to Existing Operation

```python
operation = model.attach_deferred(operation_id="...", timeout=60)
result = await operation
```

### Method Availability

| Method | Available | Timeout (default) |
|---|---|---|
| `run()` | No | -- |
| `run_stream()` | No | -- |
| `run_deferred()` | Yes | 60s |
| `attach_deferred()` | Yes | 60s |

## ImageGenerationModelResult

```python
@dataclass(frozen=True, repr=False)
class ImageGenerationModelResult:
    image_bytes: bytes      # The generated image data
    model_version: str     # Model version that produced the image
```

The image bytes can be written directly to a file:

```python
result = await operation
with open("output.jpg", "wb") as f:
    f.write(result.image_bytes)
```

## Message Format

Messages for image generation differ from text generation: **roles are
skipped**. The model receives only text content.

### Simple Text

```python
operation = await model.run_deferred("A sunset over a mountain lake")
```

### Multiple Messages (with Optional Weight)

Messages can have an optional `weight` field to control influence:

```python
operation = await model.run_deferred([
    {"text": "A sunset over a mountain lake", "weight": 5},
    {"text": "in the style of Claude Monet"},
])
```

### Message Conversion

When converting from our internal `ModelMessage` format:

```python
# Our provider uses: message.toDict("text", skipRole=True)
messages = [message.toDict("text", skipRole=True) for message in messages]
```

The `skipRole=True` flag strips the `role` field, which is correct for image
generation (the YandexART model does not use roles).

## Context Limit

The maximum prompt length for image generation is **500 characters**.
Prompts exceeding this limit will be truncated or rejected.

## Required Scope

To use image generation, the API key or IAM token must have the following
scope:

```
yc.ai.imageGeneration.execute
```

## Content Filter Detection

Image generation can fail due to content policy violations. In our current
provider, this is detected by catching `AioRpcError` and checking the error
details:

```python
from yandex_ai_studio_sdk.exceptions import AioRpcError

try:
    operation = await model.run_deferred(messages)
    result = await operation
except AioRpcError as e:
    error_msg = str(e.details())
    ethic_details = [
        "it is not possible to generate an image from this request "
        "because it may violate the terms of use",
    ]
    if error_msg in ethic_details:
        # Content filter violation
        pass
    else:
        # Other error
        raise
```

## Complete Example

```python
from yandex_ai_studio_sdk import AsyncAIStudio
from yandex_ai_studio_sdk.auth import APIKeyAuth
from yandex_ai_studio_sdk.exceptions import AioRpcError

sdk = AsyncAIStudio(folder_id="b1g...", auth=APIKeyAuth("..."))

# Create and configure model
model = sdk.models.image_generation("yandex-art").configure(
    seed=42,
    width_ratio=1,
    height_ratio=1,
    mime_type="image/jpeg",
)

# Generate image
try:
    operation = await model.run_deferred([
        {"text": "A sunset over a mountain lake", "weight": 5},
        "in the style of Claude Monet",
    ])
    result = await operation

    # Save to file
    with open("output.jpg", "wb") as f:
        f.write(result.image_bytes)

    print(f"Image generated (model version: {result.model_version})")

except AioRpcError as e:
    error_msg = str(e.details())
    if "violate the terms of use" in error_msg:
        print("Content filter: prompt rejected")
    else:
        raise
```

## Comparison with Our Current Implementation

Our `YcAIModel._generateImage()` method already correctly uses:

- `run_deferred()` for async image generation
- `message.toDict("text", skipRole=True)` for role-stripped messages
- `AioRpcError` detection for content filter violations
- `operation.wait()` for waiting on the deferred result

Not yet used but available:

- `attach_deferred()` -- could be useful for resuming interrupted generations
- Message `weight` field -- currently not supported (noted as TODO in our code)
- `model_version` from the result -- not currently tracked
