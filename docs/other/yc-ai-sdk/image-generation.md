# Yandex Cloud AI Studio SDK Reference — Image Generation (verified against pinned v0.22.0, 2026-07-18)

> **Verified against pinned SDK v0.22.0** (re-captured 2026-07-18 from
> `venv/lib/python3.14/site-packages/yandex_ai_studio_sdk/`). Production
> consumers: `lib/ai/providers/yc_sdk_provider.py::_generateImage` (YC SDK
> direct -- no configured model since the 2026-09-25 `yandex-art` removal);
> `lib/ai/providers/basic_openai_provider.py::_generateImageViaImagesApi`
> (OpenAI-compat Images API, `aliceai-image-art`). Claims marked with ⚠ are
> server-side facts not checkable from the SDK source.

Image generation via the `models.image_generation` domain (the
`AsyncImageGeneration` factory exposed on `AsyncAIStudio.models`) using the
YandexART model family ⚠ (model roster is server-side).

## Creating a Model

```python
from yandex_ai_studio_sdk import AsyncAIStudio
from yandex_ai_studio_sdk.auth import APIKeyAuth

sdk = AsyncAIStudio(folder_id="b1g...", auth=APIKeyAuth("..."))

model = sdk.models.image_generation("yandex-art", model_version="latest")
# URI: art://<folder_id>/yandex-art/latest
```

`AsyncImageGeneration.__call__(model_name, *, model_version="latest")` is the
exact factory signature: `model_version` is keyword-only and defaults to
`"latest"`. The factory returns an `AsyncImageGenerationModel`.

### URI Format

`art://<folder_id>/<model_name>/<model_version>`

Constructed by `BaseSDK._get_model_uri("art", model_name, model_version)`. If
the model name already contains `://`, it is returned verbatim (so a full
`art://...` URI can be passed as the "name").

### Available Models

The model-name → URI mapping is constructed client-side, but **which names the
server actually accepts is a server-side fact** ⚠ — the SDK does not ship a
well-known-names table for image generation (`BaseImageGeneration.__call__`
passes `well_known_names=None`).

| Model Name | URI Pattern | Notes |
|---|---|---|
| `yandex-art` | `art://<fid>/yandex-art/latest` | Original YandexART ⚠ |
| `yandex-art-2.0` | `art://<fid>/yandex-art-2.0/latest` | YandexART 2.0 ⚠ |

## Model Configuration

```python
model = sdk.models.image_generation("yandex-art").configure(
    seed=42,           # Random seed for reproducibility
    width_ratio=1,     # Width ratio
    height_ratio=1,    # Height ratio
    mime_type="image/jpeg",  # Output format
)
```

`configure()` is keyword-only and returns a **new** model instance with a
frozen-replaced config (it does not mutate the receiver).

### `ImageGenerationModelConfig` Parameters

The config object lives at
`yandex_ai_studio_sdk._models.image_generation.config.ImageGenerationModelConfig`
(`@dataclass(frozen=True)`, subclass of `BaseModelConfig`). The `configure()`
method's parameters wrap each field in `UndefinedOr[...] = UNDEFINED` so that
omitted keys leave the existing value untouched; the underlying dataclass field
defaults to `None`.

| Parameter | `configure()` signature | Stored field type | Field default | Description |
|---|---|---|---|---|
| `seed` | `UndefinedOr[int] = UNDEFINED` | `int \| None` | `None` | Random seed for reproducible generation |
| `width_ratio` | `UndefinedOr[int] = UNDEFINED` | `int \| None` | `None` | Width ratio for the output image |
| `height_ratio` | `UndefinedOr[int] = UNDEFINED` | `int \| None` | `None` | Height ratio for the output image |
| `mime_type` | `UndefinedOr[str] = UNDEFINED` | `str \| None` | `None` | Output MIME type (e.g. `"image/jpeg"`) |

**Wire-level coercion:** when building the gRPC `ImageGenerationOptions`, the
SDK substitutes empty values for `None`:

- `mime_type = self.config.mime_type or ''`
- `seed = self.config.seed or 0`
- `width_ratio = self.config.width_ratio or 0`
- `height_ratio = self.config.height_ratio or 0`

So a config of `{seed: None, width_ratio: 1, height_ratio: 1}` reaches the
server as `seed=0, width_ratio=1, height_ratio=1`.

## Execution Methods

### `run_deferred()` -- Asynchronous Image Generation

Image generation is **only available as a deferred operation**. There is no
sync `run()` or `run_stream()` on `AsyncImageGenerationModel` (verified: only
`run_deferred` and the inherited `attach_deferred`/`configure` are exposed).

```python
# Signature (model.py):
#   async def run_deferred(
#       self,
#       messages: ImageMessageInputType,
#       *,
#       timeout: float = 60,
#   ) -> AsyncOperation[ImageGenerationModelResult]

operation: AsyncOperation[ImageGenerationModelResult] = await model.run_deferred(
    messages,
    timeout=60,
)

# Wait for completion (uses wait() defaults: poll_interval=10s, poll_timeout=3600s)
result: ImageGenerationModelResult = await operation

# Or with explicit polling
result = await operation.wait(poll_interval=5, poll_timeout=300)
```

### `attach_deferred()` -- Attach to Existing Operation

Defined on `ModelAsyncAttachMixin` (`_types/model.py`), mixed into
`AsyncImageGenerationModel`. Both parameters are keyword-or-positional.

```python
# Signature (_types/model.py):
#   async def attach_deferred(
#       self, operation_id: str, timeout: float = 60,
#   ) -> AsyncOperation[ImageGenerationModelResult]

operation = await model.attach_deferred(operation_id="...", timeout=60)
result = await operation
```

### Method Availability

| Method | Available | Default timeout |
|---|---|---|
| `run()` | No | -- |
| `run_stream()` | No | -- |
| `run_deferred()` | Yes | 60s |
| `attach_deferred()` | Yes | 60s |

### `AsyncOperation[ImageGenerationModelResult]` API

The object returned by `run_deferred()` / `attach_deferred()`
(`yandex_ai_studio_sdk._types.operation.AsyncOperation`) exposes:

| Member | Signature | Notes |
|---|---|---|
| `id` | `-> str` property | Operation ID |
| `__await__` | -- | `await operation` is equivalent to `await operation.wait()` with defaults |
| `wait()` | `*, timeout=60, poll_timeout=None, poll_interval=None` | Blocks until done; returns the result. `poll_timeout=None` falls back to class default `_default_poll_timeout = 3600` (1 hour); `poll_interval=None` falls back to `_default_poll_interval = 10` (seconds) |
| `get_status()` | `*, timeout=60` | Returns `OperationStatus` (`done`, `error`, `response`, `metadata`) with `.is_running`/`.is_succeeded`/`.is_failed`/`.is_finished` |
| `get_result()` | `*, timeout=60` | Returns `ImageGenerationModelResult`; raises `RunError` if failed, `WrongAsyncOperationStatusError` if still running |
| `cancel()` | `*, timeout=60` | Cancels the operation server-side |

## `ImageGenerationModelResult`

Defined at
`yandex_ai_studio_sdk._models.image_generation.result.ImageGenerationModelResult`,
a frozen dataclass subclass of `BaseProtoResult[ImageGenerationResponse]`:

```python
@dataclass(frozen=True, repr=False)
class ImageGenerationModelResult(BaseProtoResult[ImageGenerationResponse]):
    """This class represents the result of an image generation model inference."""
    image_bytes: bytes      # the generated image (JPEG by default)
    model_version: str      # the model version that produced the image
```

`repr=False` is set because a custom `__repr__` is provided that summarises
size (`ImageGenerationModelResult(model_version='...', image_bytes=<N bytes>)`)
rather than dumping raw bytes. A `_repr_jpeg_()` helper returns the bytes when
they begin with `FFD8` and end with `FFD9` (JPEG SOI/EOI markers), enabling
rich display in notebooks.

The image bytes can be written directly to a file:

```python
result = await operation
with open("output.jpg", "wb") as f:
    f.write(result.image_bytes)
```

## Message Format

Messages for image generation differ from text generation: **roles are
skipped**. The proto conversion (`messages_to_proto` in
`_models/image_generation/message.py`) accepts these input shapes:

- `str` → `{"text": <str>}`
- `TextMessage` (the completions message type, which has `text` + `role`) →
  `{"text": message.text}` -- the `role` is dropped
- any object satisfying the `AnyMessage` protocol (has a `.text` attribute) →
  `{"text": ...}`, plus `weight` if the object exposes a truthy `.weight`
  attribute
- `dict` with a `"text"` key → used as-is (must match `ImageMessageDict`)
- `ImageMessage` dataclass (`text: str`, `weight: float | None = None`)

A heterogeneous list of any of the above is accepted.

### `ImageMessageDict`

Declared as a `TypedDict` in `_models/image_generation/message.py`:

```python
class ImageMessageDict(TypedDict):
    text: str
    weight: NotRequired[float]
```

`weight` is typed **`float`**; passing a Python `int` is accepted at runtime
but is technically the wrong type for static checkers.

### Simple Text

```python
operation = await model.run_deferred("A sunset over a mountain lake")
```

### Multiple Messages (with Optional Weight)

```python
operation = await model.run_deferred([
    {"text": "A sunset over a mountain lake", "weight": 5},
    {"text": "in the style of Claude Monet"},  # plain dict is fine; str would also work
])
```

### Message Conversion

When converting from our internal `ModelMessage` format, the production
provider calls `ModelMessage.toDict(content_key="text", skipRole=True)`
(see `lib/ai/models.py::ModelMessage.toDict`), producing a `{"text": "..."}`
dict that satisfies `ImageMessageDict` (`weight` is `NotRequired`):

```python
# Our provider uses (lib/ai/providers/yc_sdk_provider.py::_generateImage):
messages = [message.toDict("text", skipRole=True) for message in messages]
```

`skipRole=True` strips the `role` field, which is correct for image generation
(the YandexART model does not use roles).

## Context Limit

The maximum prompt length for image generation is **500 characters** ⚠
(server-side limit, not enforced or documented in the SDK wheel; the SDK will
forward any prompt and the server will reject or truncate it).

## Required Scope

To use image generation, the API key or IAM token must have the following
scope ⚠ (server-side; not represented in the SDK):

```
yc.ai.imageGeneration.execute
```

## Content Filter Detection

Image generation can fail due to content-policy violations. The SDK surfaces
these as `AioRpcError` (subclass of `grpc.aio.AioRpcError`, exported from
`yandex_ai_studio_sdk.exceptions`). The production provider detects them by
calling `error.details()` and matching against the hard-coded `ETHIC_DETAILS`
list at `lib/ai/providers/yc_sdk_provider.py:90-92`:

```python
ETHIC_DETAILS: List[str] = [
    "it is not possible to generate an image from this request "
    "because it may violate the terms of use",
]
```

Producer-side sketch (mirrors `_handleSDKError` at
`lib/ai/providers/yc_sdk_provider.py:390-425`):

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

This snippet is runnable against the pinned SDK (v0.22.0) modulo valid
`folder_id` / API-key credentials and server-side availability of the
`yandex-art` model ⚠.

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

There are **two parallel image-generation paths** in production; this document
describes the SDK surface consumed by the first one only.

| Path | Provider class | Configured model(s) | Transport |
|---|---|---|---|
| **YC SDK direct** | `YcAIModel` ([`yc_sdk_provider.py`](../../../lib/ai/providers/yc_sdk_provider.py)) | none since 2026-09-25 -- `yandex-art` was removed from [`yc-sdk-models.toml`](../../../configs/00-defaults/yc-sdk-models.toml) after its 2026-09-07 EOL (its URI now returns 400); the gRPC SDK path itself stays wired in `yc_sdk_provider.py` for re-enablement | gRPC `ImageGenerationAsyncServiceStub` via this SDK |
| **OpenAI-compat Images API** | `BasicOpenAIModel._generateImageViaImagesApi` ([`basic_openai_provider.py`](../../../lib/ai/providers/basic_openai_provider.py)) | `aliceai-image-art` ([`yc-openai-models.toml`](../../../configs/00-defaults/yc-openai-models.toml): `[models.models."aliceai-image-art"]`, `model_id = "aliceai-image-art-3.0"`, `image_generation_api = "openai-images"`) | `client.images.generate(...)` -- does **not** use this SDK at all |

### YC SDK direct path (`YcAIModel._generateImage`, `yc_sdk_provider.py:507`)

Already correctly uses (verified against the v0.22.0 source):

- `run_deferred()` for async image generation (line 538), called with
  `messages` only -- the `timeout=60` default applies.
- `await operation.wait()` for the deferred result (line 541), again with
  defaults -- `poll_interval=10s`, `poll_timeout=3600s`.
- `isinstance(result, ImageGenerationModelResult)` guard (line 542) before
  reading fields.
- `message.toDict("text", skipRole=True)` for role-stripped messages
  (line 539), producing `{"text": ...}` dicts that match `ImageMessageDict`.
- `AioRpcError` detection via `_handleSDKError()` (line 545 → 399-430),
  matching `str(error.details())` against the `ETHIC_DETAILS` list
  (lines 90-92) and returning `ModelResultStatus.CONTENT_FILTER` on a match.
- `mediaMimeType=IMAGE_MIME_TYPE` (= `"image/jpeg"`, line 84) and
  `mediaData=result.image_bytes` (line 552) on success.

Not yet used but available in the SDK:

- **`attach_deferred()`** -- not called anywhere in production. Could resume
  an interrupted generation if we ever chose to persist operation IDs.
- **Message `weight` field** -- not supported by the provider path; the
  `_generateImage` docstring at line 525 explicitly notes
  *"Message weights are not currently supported but may be added in the
  future."* `ModelMessage.toDict("text", skipRole=True)` does not emit
  `weight`.
- **`result.model_version`** -- not read by the provider. Lines 548-553
  consume only `result.image_bytes` (for `mediaData`) and the truthiness of
  `result.image_bytes` (for the `FINAL` vs `UNKNOWN` status). The model
  version that produced the image is discarded.
