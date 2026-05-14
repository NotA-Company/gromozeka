# Yandex Cloud AI Studio SDK Reference (v0.20.2)

Complete documentation of the `yandex-ai-studio-sdk` Python package, version
**0.20.2**. This reference covers every public API surface and is intended to
guide a refactoring of our existing YC SDK provider at
`lib/ai/providers/yc_sdk_provider.py`.

## Installation

```bash
pip install yandex-ai-studio-sdk==0.20.2
```

## Main Entry Points

| Variant | Class | Use case |
|---|---|---|
| Sync | `AIStudio` | Scripts, non-async code |
| Async | `AsyncAIStudio` | Async applications (our use case) |

Both share the same constructor signature (defined in `BaseSDK`):

```python
from yandex_ai_studio_sdk import AsyncAIStudio

sdk = AsyncAIStudio(
    folder_id="b1g...",
    auth=...,                     # str | BaseAuth instance
    endpoint="api.cloud.yandex.net:443",  # gRPC endpoint
    retry_policy=RetryPolicy(),   # retry configuration
    yc_profile="default",         # yc CLI profile name
    service_map={},               # override service endpoints
    interceptors=[],              # gRPC client interceptors
    enable_server_data_logging=False,  # x-data-logging-enabled header
    verify=True,                  # SSL: True | False | PathLike (CA bundle)
)
```

All parameters are keyword-only and accept `UNDEFINED` as a sentinel
(distinguish "not passed" from `None`). Omitted params fall back to
environment variables or sensible defaults.

### Constructor Parameters

| Parameter | Type | Default / Fallback |
|---|---|---|
| `folder_id` | `str \| None` | `YC_FOLDER_ID` env var |
| `auth` | `str \| BaseAuth` | Auto-detected from env (see below) |
| `endpoint` | `str \| None` | `YC_API_ENDPOINT` env, then `api.cloud.yandex.net:443` |
| `retry_policy` | `RetryPolicy` | `RetryPolicy()` (5 attempts, 1s backoff, 10s max, 1.5x multiplier, 1s jitter) |
| `yc_profile` | `str` | `YC_PROFILE` env |
| `service_map` | `dict[str, str]` | None |
| `interceptors` | `Sequence[aio.ClientInterceptor]` | None |
| `enable_server_data_logging` | `bool` | `False` |
| `verify` | `bool \| PathLike` | `True` (system CA bundle) |

## Authentication

### Auto-Detection Order

When `auth` is not explicitly passed, the SDK tries these in order:

| Priority | Env Var | Auth Class | Mechanism |
|---|---|---|---|
| 1 | `YC_API_KEY` | `APIKeyAuth` | Static API key (`Api-Key <key>`) |
| 2 | `YC_IAM_TOKEN` | `IAMTokenAuth` | IAM token (`Bearer <token>`) |
| 3 | `YC_OAUTH_TOKEN` | `OAuthTokenAuth` | OAuth exchange for IAM token |
| 4 | VM metadata | `MetadataAuth` | YC VM metadata service |
| 5 | `YC_TOKEN` | `EnvIAMTokenAuth` | Re-reads IAM token from env on each call |
| 6 | `yc` CLI | `YandexCloudCLIAuth` | Runs `yc iam create-token` |

### Explicit Auth Classes

```python
from yandex_ai_studio_sdk.auth import (
    APIKeyAuth,
    IAMTokenAuth,
    EnvIAMTokenAuth,
    OAuthTokenAuth,
    YandexCloudCLIAuth,
    MetadataAuth,
    NoAuth,
)
```

| Class | Constructor | Header | Notes |
|---|---|---|---|
| `APIKeyAuth(api_key)` | API key string | `Api-Key {key}` | Best for services/long-lived |
| `IAMTokenAuth(token)` | IAM token string | `Bearer {token}` | Short-lived (up to 12h) |
| `EnvIAMTokenAuth(env_var_name=None)` | Env var name (default `YC_TOKEN`) | `Bearer {token}` | Re-reads each call |
| `OAuthTokenAuth(token)` | OAuth token string | `Bearer {iam_token}` | Emits `UserWarning`; exchanges OAuth for IAM |
| `YandexCloudCLIAuth(token=None, endpoint=None, yc_profile=None)` | Uses `yc iam create-token` | `Bearer {iam_token}` | Requires `yc` CLI installed |
| `MetadataAuth(token=None, metadata_url=None)` | VM metadata URL | `Bearer {iam_token}` | Only works inside YC VMs |
| `NoAuth()` | None | None | No authentication header |

## SDK Domains

The SDK exposes these domains on the `AIStudio` / `AsyncAIStudio` instance:

| Domain | Access | Description | Detail |
|---|---|---|---|
| `models` | `sdk.models` | gRPC-based model operations | [Completions](completions.md), [Image Generation](image-generation.md), [Embeddings & Other](embeddings-and-other.md) |
| `chat` | `sdk.chat` | OpenAI-compatible HTTP API | [Chat (OpenAI Compat)](chat-openai-compat.md) |
| `tools` | `sdk.tools` | Function calling, search tools | [Tools & Structured Output](tools-and-structured-output.md) |
| `speechkit` | `sdk.speechkit` | TTS and STT | [Speech](speech.md) |
| `search_api` | `sdk.search_api` | Web/image/generative search | [Embeddings & Other](embeddings-and-other.md) |
| `search_indexes` | `sdk.search_indexes` | Vector/hybrid search indexes | [Embeddings & Other](embeddings-and-other.md) |
| `datasets` | `sdk.datasets` | Dataset management for tuning | [Embeddings & Other](embeddings-and-other.md) |
| `tuning` | `sdk.tuning` | Fine-tuning task management | [Embeddings & Other](embeddings-and-other.md) |
| `batch` | `sdk.batch` | Batch completions operations | [Embeddings & Other](embeddings-and-other.md) |

## Sync vs Async Duality

Every domain provides both sync and async variants. The async variant is
suffixed with `Async` (e.g., `AsyncGPTModel` vs `GPTModel`). All methods that
perform I/O have async counterparts (`run` / `run_stream` / `run_deferred`)
that return coroutines or async iterators.

```python
# Sync
from yandex_ai_studio_sdk import AIStudio
sdk = AIStudio(folder_id="...", auth=APIKeyAuth("..."))
result = sdk.models.completions("yandexgpt").run([...])

# Async
from yandex_ai_studio_sdk import AsyncAIStudio
sdk = AsyncAIStudio(folder_id="...", auth=APIKeyAuth("..."))
result = await sdk.models.completions("yandexgpt").run([...])
```

## UNDEFINED Sentinel

The SDK uses `UNDEFINED` (from `yandex_ai_studio_sdk._types.misc`) throughout
`configure()` and `__call__()` methods to distinguish "not passed" from `None`:

```python
from yandex_ai_studio_sdk._types.misc import UNDEFINED, is_defined

# UNDEFINED means "use whatever is already configured"
# None means "explicitly clear this setting"
model.configure(temperature=None)  # clears temperature
model.configure()                   # no-op, keeps existing config
```

## Exception Hierarchy

```
Exception
  +-- AIStudioError
        +-- UnknownEndpointError
        +-- AioRpcError            (wraps grpc.aio.AioRpcError; adds endpoint, auth, stub_class, client_request_id)
        +-- HttpSseError           (event, message, error dict)
        +-- AIStudioConfigurationError
        +-- RunError               (code, message, details, operation_id)
        |     +-- TuningError
        +-- AsyncOperationError
              +-- WrongAsyncOperationStatusError
              +-- DatasetValidationError  (validation_result)
```

## RetryPolicy

```python
from yandex_ai_studio_sdk import RetryPolicy

# Default: 5 attempts, 1s initial backoff, 10s max, 1.5x multiplier, 1s jitter
retry = RetryPolicy()

# Disable retries
from yandex_ai_studio_sdk import NoRetryPolicy
no_retry = NoRetryPolicy()
```

| Field | Default | Description |
|---|---|---|
| `max_attempts` | `5` | Max retry attempts (-1 = infinite) |
| `initial_backoff` | `1.0` | Initial backoff in seconds |
| `max_backoff` | `10.0` | Max backoff in seconds |
| `backoff_multiplier` | `1.5` | Exponential multiplier |
| `jitter` | `1.0` | Max random jitter in seconds |
| `retriable_codes` | `(UNAVAILABLE, RESOURCE_EXHAUSTED)` | gRPC status codes to retry |

Backoff formula: `min(initial_backoff * multiplier^attempt + uniform(0, jitter), max_backoff, deadline_timeout)`

## Table of Contents

1. [Completions](completions.md) -- Text generation, model configuration, streaming, deferred operations
2. [Tools & Structured Output](tools-and-structured-output.md) -- Tool calling, function calling, search tools, JSON Schema output
3. [Image Generation](image-generation.md) -- YandexART image generation
4. [Speech](speech.md) -- Text-to-Speech and Speech-to-Text via SpeechKit
5. [Embeddings & Other](embeddings-and-other.md) -- Embeddings, classifiers, search API, tuning, datasets, batch
6. [Chat (OpenAI Compat)](chat-openai-compat.md) -- OpenAI-compatible HTTP API
7. [Gap Analysis](gap-analysis.md) -- What our provider uses vs what is available
