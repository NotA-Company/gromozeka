# `lib/ai` — Structured (JSON-Schema) Output

> **Status:** ✅ COMPLETED — implemented in current codebase
> **Implementation:** `ModelStructuredResult` class exists in [`lib/ai/models.py`](../../lib/ai/models.py), `generateStructured()` method exists in [`lib/ai/abstract.py`](../../lib/ai/abstract.py:326-404)
> **Scope:** `lib/ai/` (abstract + models + all providers), `internal/services/llm/service.py`, model configs, tests.
> **Out of scope:** wiring into specific handlers (e.g. divination's
> `_llmGetUnknownLayoutShape`), per-chat ChatSettings, schema-builder DSL,
> pydantic adapters.

## 1. Context & Goal (HISTORICAL BACKGROUND)

**Original plan text below — preserved for posterity. This feature is now implemented.**

`lib/ai` today exposes two LLM operations: text generation
([`AbstractModel.generateText`](../../lib/ai/abstract.py:127)) and image
generation ([`AbstractModel.generateImage`](../../lib/ai/abstract.py:172)).
Several call sites already want **structured JSON output** — the most
visible being the existing stub
[`DivinationHandler._llmGetUnknownLayoutShape`](../../internal/bot/common/handlers/divination.py:826),
which deliberately no-ops with a TODO until `lib/ai` supports it.

**Goal:** add a third operation, `generateStructured`, that takes messages
+ a JSON Schema and returns a parsed `dict` plus the usual lib/ai metadata
(status, errors, token usage, raw response). Implement it for the
OpenAI-compatible stack (Custom OpenAI, OpenRouter, YC OpenAI). YC SDK is
explicitly deferred to a later refactor.

**Non-goals (v1):**

- Combining `tools=` and `schema=` in the same call — disallowed.
- Pydantic anything. **The project does not use pydantic and will not start
  using it.** Schemas are raw JSON Schema dicts, period.
- Auto-injecting "respond as JSON" hints into the prompt — that stays the
  caller's responsibility.
- Streaming or partial-JSON delivery.
- Per-chat ChatSettings toggle.

## 2. Current State (relevant excerpts)

```
lib/ai/
├── abstract.py            # AbstractModel (generateText/generateImage),
│                          # AbstractLLMProvider
├── models.py              # ModelMessage, ModelRunResult, ModelResultStatus,
│                          # LLMAbstractTool, LLMToolFunction, LLMParameterType
├── manager.py             # LLMManager — registers providers from config
└── providers/
    ├── basic_openai_provider.py  # BasicOpenAIModel + BasicOpenAIProvider
    │                             # (the OpenAI-compatible base)
    ├── custom_openai_provider.py # uses BasicOpenAIModel directly
    ├── openrouter_provider.py    # OpenrouterModel(BasicOpenAIModel)
    ├── yc_openai_provider.py     # YcOpenaiModel(BasicOpenAIModel)
    └── yc_sdk_provider.py        # YcAIModel — separate stack, gRPC-ish
```

Capability flags already live in `extraConfig` and surface through
`getInfo()`: `support_text`, `support_tools`, `support_images`. We will
add `support_structured_output`.

`ModelRunResult` is the unified return shape today. The structured path
needs an extra `data: Optional[Dict[str, Any]]` field plus the sentinel
that "this was a structured call." We model that as a thin subclass to
keep `ModelRunResult`'s fast-path callers untouched.

Tests:

- Per-provider unit tests with mocked `AsyncOpenAI` clients live under
  `lib/ai/providers/test_*.py`.
- Manager tests in `lib/ai/test_manager.py`.
- Golden-data integration tests in `tests/lib_ai/golden/` powered by
  `lib/aurumentation` (httpx transport patching). This is where the live-
  recorded structured-output scenarios will go.

## 3. Proposed Design

### 3.1 New result type — `ModelStructuredResult`

In [`lib/ai/models.py`](../../lib/ai/models.py).

```python
class ModelStructuredResult(ModelRunResult):
    """Result of a structured-output LLM call.

    Extends ModelRunResult with a parsed JSON object. Inherits all of the
    parent's fields: status, resultText (the raw model text BEFORE parse),
    error, inputTokens/outputTokens/totalTokens, isFallback, etc.

    On success: status == FINAL (or TRUNCATED_FINAL), data is the parsed
    JSON object validated against the requested schema by the provider
    (when the provider supports strict mode), and resultText is the raw
    string the model emitted.

    On JSON parse failure: status == ERROR, data is None, error is the
    underlying json.JSONDecodeError, and resultText still holds the raw
    text so callers can debug.

    On other failures (content filter, API error, schema rejection by the
    provider): status reflects the cause, data is None, error is set if
    relevant.
    """

    __slots__ = ("data",)

    def __init__(
        self,
        rawResult: Any,
        status: ModelResultStatus,
        data: Optional[Dict[str, Any]] = None,
        resultText: str = "",
        error: Optional[Exception] = None,
        inputTokens: Optional[int] = None,
        outputTokens: Optional[int] = None,
        totalTokens: Optional[int] = None,
    ):
        super().__init__(
            rawResult=rawResult,
            status=status,
            resultText=resultText,
            error=error,
            inputTokens=inputTokens,
            outputTokens=outputTokens,
            totalTokens=totalTokens,
        )
        self.data: Optional[Dict[str, Any]] = data
```

Notes:

- We deliberately do **not** populate `toolCalls` / `mediaMimeType` /
  `mediaData` for structured calls — combining tools and structured
  output is rejected at the API surface (§3.3).
- `__str__` in the base class will pick up `data` via a small override —
  see §6 for the touch-up.

### 3.2 New abstract method — `AbstractModel.generateStructured`

In [`lib/ai/abstract.py`](../../lib/ai/abstract.py), parallel to
`_generateText` / `generateText`.

```python
@abstractmethod
async def _generateStructured(
    self,
    messages: Sequence[ModelMessage],
    schema: Dict[str, Any],
    *,
    schemaName: str = "response",
    strict: bool = True,
) -> ModelStructuredResult:
    """Provider-specific structured-output implementation.

    Args:
        messages: Conversation history.
        schema: A JSON Schema dict describing the desired response shape.
            Provider implementations pass this to the underlying API in
            whatever format the API expects (e.g. OpenAI wraps it in
            ``response_format = {"type": "json_schema", ...}``).
        schemaName: Identifier sent alongside the schema (OpenAI requires
            a ``name`` field; ignored where unused).
        strict: When True, ask the provider to enforce the schema strictly
            (OpenAI ``strict: true``). Some providers ignore this.

    Returns:
        ModelStructuredResult — see class docstring for status semantics.

    Raises:
        NotImplementedError: If structured output is not supported by this
            model (capability flag ``support_structured_output`` is False
            or the provider has not implemented it).
    """
    raise NotImplementedError


async def generateStructured(
    self,
    messages: Sequence[ModelMessage],
    schema: Dict[str, Any],
    *,
    schemaName: str = "response",
    strict: bool = True,
) -> ModelStructuredResult:
    """Public structured-output entry point.

    Mirrors generateText: estimates tokens, enforces the context budget,
    then calls _generateStructured. Honours JSON-logging just like the
    text path.

    NOTE for callers: most LLMs perform better when the SYSTEM message
    explicitly says something like "respond with a JSON object matching
    the provided schema." This wrapper does NOT inject that hint — pass
    it in the messages yourself.

    Args:
        messages: Conversation history.
        schema: JSON Schema dict.
        schemaName: Schema identifier (provider-dependent).
        strict: Strict-mode flag (provider-dependent).

    Returns:
        ModelStructuredResult.

    Raises:
        NotImplementedError: If this model does not support structured
            output (capability flag is False).
    """
    if not self._config.get("support_structured_output", False):
        raise NotImplementedError(
            f"Structured output isn't supported by {self.modelId}"
        )

    tokensCount = self.getEstimateTokensCount(messages) + self.getEstimateTokensCount(schema)
    logger.debug(
        f"generateStructured(messages={len(messages)}, schema_keys={list(schema.keys())}), "
        f"estimateTokens={tokensCount}, model: {self.provider}/{self.modelId}"
    )

    if self.contextSize and tokensCount > self.contextSize * 2:
        return ModelStructuredResult(
            rawResult=None,
            status=ModelResultStatus.ERROR,
            error=Exception(
                f"Context too large: estimated tokens {tokensCount} "
                f"vs model context {self.contextSize}"
            ),
        )

    ret = await self._generateStructured(
        messages=messages, schema=schema, schemaName=schemaName, strict=strict
    )

    if self.enableJSONLog:
        # Re-use the existing JSON log path; result.resultText holds the raw
        # text and `result` (rawResult) holds the API response.
        self.printJSONLog(messages, ret)
    return ret
```

A default implementation in `AbstractModel` for `_generateStructured`
raises `NotImplementedError` so providers that do not opt in fail
loudly. (We do **not** mark it `@abstractmethod` to avoid forcing every
existing subclass — including test mocks like
[`MockModel`](../../lib/ai/test_manager.py:43) — to define a stub.
Instead we add a concrete default-raise in `AbstractModel` and let
opting-in providers override.)

> **Decision:** non-abstract default-raise. Yes, this is slightly weaker
> than `@abstractmethod`, but it lets us roll out without touching mock
> classes. The `support_structured_output` flag is the authoritative gate.

### 3.3 Tools / structured output mutual exclusion

Per agreed design: `generateStructured` does **not** accept a `tools=`
parameter. There is no path to combine them in v1. If callers need both,
they orchestrate two calls.

### 3.4 Fallback variant — `generateStructuredWithFallBack`

Mirrors [`generateTextWithFallBack`](../../lib/ai/abstract.py:192). Same
status-codes-trigger-fallback rule. Fallback model also runs through
`generateStructured`, so it must also have `support_structured_output =
True`. If neither claims support, `LLMService` should resolve that at the
service layer (§3.7).

### 3.5 OpenAI-compatible provider implementation

In [`lib/ai/providers/basic_openai_provider.py`](../../lib/ai/providers/basic_openai_provider.py),
add `_generateStructured` to `BasicOpenAIModel`. It mirrors the existing
`_generateText` body, with three deltas:

1. Add `response_format` to `params`:
   ```python
   params["response_format"] = {
       "type": "json_schema",
       "json_schema": {
           "name": schemaName,
           "schema": schema,
           "strict": strict,
       },
   }
   ```
2. Forbid `tools` (none accepted by signature, so nothing to set).
3. After receiving the response and computing `status`, parse
   `retMessage.content` as JSON:
   ```python
   data: Optional[Dict[str, Any]] = None
   if status in (ModelResultStatus.FINAL, ModelResultStatus.TRUNCATED_FINAL):
       try:
           parsed = json.loads(resText) if resText else None
           if parsed is not None and not isinstance(parsed, dict):
               raise ValueError(
                   f"Structured output expected JSON object, got {type(parsed).__name__}"
               )
           data = parsed
       except (json.JSONDecodeError, ValueError) as e:
           logger.warning(
               f"Failed to parse structured output from {self.modelId}: {e}"
           )
           status = ModelResultStatus.ERROR
           return ModelStructuredResult(
               rawResult=response,
               status=status,
               data=None,
               resultText=resText,
               error=e,
               inputTokens=inputTokens,
               outputTokens=outputTokens,
               totalTokens=totalTokens,
           )
   ```
4. The `openai.BadRequestError` branch (e.g. provider rejects schema)
   returns a `ModelStructuredResult(status=ERROR, error=e)`.

The subclasses inherit `_generateStructured` for free:

- `OpenrouterModel` — already adds `extra_headers` via `_getExtraParams`,
  which `_generateStructured` will pick up the same way.
- `YcOpenaiModel` — `_getModelId()` override flows through unchanged.
- Custom OpenAI — `BasicOpenAIModel` is used directly.

No changes needed to `BasicOpenAIProvider` / its subclasses — they don't
participate in the call path beyond model creation.

### 3.6 YC SDK provider — defer

In [`lib/ai/providers/yc_sdk_provider.py`](../../lib/ai/providers/yc_sdk_provider.py),
override `_generateStructured` to raise:

```python
async def _generateStructured(
    self,
    messages: Sequence[ModelMessage],
    schema: Dict[str, Any],
    *,
    schemaName: str = "response",
    strict: bool = True,
) -> ModelStructuredResult:
    # TODO: YC SDK supports response_format via .configure(), but that
    # mutates the shared model object, which collides with concurrent
    # callers. Will be done as part of a YC SDK refactor — see
    # docs/plans/lib-ai-structured-output.md §3.6.
    raise NotImplementedError(
        f"Structured output not supported by YC SDK provider yet"
    )
```

The capability flag will be `False` for all `yc-sdk` models in config, so
the public `generateStructured` raises before ever hitting this — but we
still implement the `_generateStructured` override for safety.

### 3.7 `LLMService.generateStructured`

In [`internal/services/llm/service.py`](../../internal/services/llm/service.py),
add a wrapper analogous to `generateText`:

```python
async def generateStructured(
    self,
    prompt: Union[str, Sequence[ModelMessage]],
    schema: Dict[str, Any],
    *,
    chatId: Optional[int],
    chatSettings: ChatSettingsDict,
    llmManager: LLMManager,
    modelKey: Union[ChatSettingsKey, AbstractModel, None],
    fallbackKey: Union[ChatSettingsKey, AbstractModel, None],
    schemaName: str = "response",
    strict: bool = True,
    doDebugLogging: bool = True,
) -> ModelStructuredResult:
    """Generate structured (JSON) output via the configured chat model.

    Resolves the primary and fallback models from chatSettings, applies
    rate limiting, then delegates to AbstractModel.generateStructured
    with fallback. Raises if neither resolved model supports structured
    output.

    NOTE: callers should include a system message hinting at JSON output;
    this wrapper will not inject one.
    """
    if isinstance(prompt, str):
        prompt = [ModelMessage(content=prompt)]

    llmModel = self.resolveModel(
        modelKey, chatSettings=chatSettings, llmManager=llmManager,
        defaultKey=ChatSettingsKey.CHAT_MODEL,
    )
    fallbackModel = self.resolveModel(
        fallbackKey, chatSettings=chatSettings, llmManager=llmManager,
        defaultKey=ChatSettingsKey.FALLBACK_MODEL,
    )

    primarySupports = llmModel.getInfo().get("support_structured_output", False)
    fallbackSupports = fallbackModel.getInfo().get("support_structured_output", False)
    if not primarySupports and not fallbackSupports:
        raise NotImplementedError(
            f"Neither {llmModel} nor {fallbackModel} supports structured output"
        )

    if chatId is not None:
        await self.rateLimit(chatId, chatSettings)

    if doDebugLogging:
        logger.debug(
            f"Generating Structured for chat#{chatId}, LLMs: {llmModel}, "
            f"{fallbackModel}, schema_keys={list(schema.keys())}"
        )

    # If primary doesn't support but fallback does, swap them so we don't
    # waste a round-trip on a guaranteed NotImplementedError.
    if not primarySupports and fallbackSupports:
        llmModel, fallbackModel = fallbackModel, llmModel

    ret = await llmModel.generateStructuredWithFallBack(
        prompt, fallbackModel, schema=schema,
        schemaName=schemaName, strict=strict,
    )

    if doDebugLogging:
        logger.debug(f"LLM (structured) returned: {ret}")
    return ret
```

`generateStructuredWithFallBack` lives on `AbstractModel`; if the fallback
model lacks the capability, fallback raises `NotImplementedError` and the
primary's error/status is what the caller sees. (We log this case loudly.)

### 3.8 Capability flags & config

Add `support_structured_output` to `extraConfig` defaults handling — same
shape as existing `support_text` / `support_tools`. Update
[`AbstractModel.getInfo`](../../lib/ai/abstract.py:308) to include it:

```python
"support_structured_output": self._config.get("support_structured_output", False),
```

### 3.9 OpenRouter-model audit

Tag known-good models in
[`configs/00-defaults/openrouter-models.toml`](../../configs/00-defaults/openrouter-models.toml)
and [`configs/00-defaults/yc-openai-models.toml`](../../configs/00-defaults/yc-openai-models.toml).
Best-current-knowledge mapping (verify against the OpenRouter model page
during implementation; the URL is already in the TOML comments):

| Config key | `support_structured_output` | Reason |
|---|---|---|
| `openrouter/claude-haiku-4.5` | **true** | Anthropic — solid native support |
| `openrouter/deepseek-chat-v3.1` | **true** | DeepSeek — supported |
| `openrouter/deepseek-v4-flash` | **true** | DeepSeek — supported |
| `openrouter/qwen3-235b-a22b` | **true** | Qwen3 — supported |
| `openrouter/qwen-turbo` | **true** | Qwen — supported |
| `openrouter/qwen3.5-flash` | **true** | Qwen3.5 — supported |
| `openrouter/qwen3-vl-235b-a22b-instruct` | **true** | Qwen3-VL — supported |
| `openrouter/qwen3.6-plus` | **true** | Qwen3.6 — supported |
| `openrouter/gemini-2.5-flash-image` | **false** | image-gen, irrelevant |
| `openrouter/gemini-3-pro-image-preview` | **false** | image-gen, irrelevant |
| `openrouter/gemma-3-27b-it:free` | **false** | Gemma — unreliable JSON-schema |
| `openrouter/mistral-7b-instruct:free` | **false** | weak schema adherence |
| `openrouter/gpt-oss-20b:free` | **false** | inconsistent + already disabled |
| `yc/gpt-oss-120b` | **true** | GPT-OSS family with response_format |
| `yc/deepseek-v32` | **true** | DeepSeek family |
| `yc/qwen3-235b-a22b-fp8` | **true** | Qwen3 |
| `yc/gemma-3-27b-it` | **false** | Gemma |
| `yc/gpt-oss-20b` | **false** | smaller — keep conservative |
| `yandexgpt`, `yandexgpt-lite`, `aliceai-llm` | **false** | YC OpenAI-compatible behaviour for `response_format` not yet validated; flip to `true` per-model after manual smoke + golden recording |

> **Implementation rule:** during implementation, before flipping a model
> to `true`, record at least one structured-output golden-data scenario
> against it (§5.3) and verify the parsed `data` matches the schema. If
> recording fails (provider rejects `response_format`, returns broken
> JSON, etc.), leave it `false` and add a `# unverified` comment.

### 3.10 Public exports

Add to [`lib/ai/__init__.py`](../../lib/ai/__init__.py):

```python
from .models import (
    ...,
    ModelStructuredResult,
)

__all__ = [
    ...,
    "ModelStructuredResult",
]
```

## 4. Alternatives Considered

| Alt | Why rejected |
|---|---|
| Return raw `Dict[str, Any]` from `generateStructured` | Loses status, error, token usage. Inconsistent with the rest of `lib/ai`. |
| Pydantic models as schema input | **Project policy: no pydantic.** Hand-rolled JSON Schema dicts everywhere. (Recorded in `AGENTS.md` per this plan.) |
| Reuse `ModelRunResult` directly with a `data` field | Forces every caller of `generateText` to ignore a never-populated `data` field. The subclass is cleaner and `__slots__`-friendly. |
| Build a custom `LLMSchema`/`LLMSchemaField` DSL like the existing `LLMFunctionParameter` | Adds invented surface area for marginal benefit; users who want a builder can wrap it themselves. Raw JSON Schema is industry-standard and what the OpenAI API consumes verbatim. |
| Allow `tools=` and `schema=` together | OpenAI permits it but semantics are model-dependent and confusing. Defer until a concrete use case shows up. |
| Implement YC SDK now via per-call `.configure()` | Mutates shared SDK model object → unsafe under concurrency. Needs a YC SDK refactor that's out of scope. |

## 5. Implementation Plan

### Phase 1 — Core types & abstract API (no behaviour change)

Files:

- [`lib/ai/models.py`](../../lib/ai/models.py) — add `ModelStructuredResult`.
- [`lib/ai/abstract.py`](../../lib/ai/abstract.py) — add `_generateStructured`
  (default-raise), `generateStructured`, `generateStructuredWithFallBack`.
  Update `getInfo()` to include `support_structured_output`.
- [`lib/ai/__init__.py`](../../lib/ai/__init__.py) — export
  `ModelStructuredResult`.

Verification:

```
make format lint
./venv/bin/pytest lib/ai -v
```

All existing tests must pass unchanged. New abstract method defaults to
`NotImplementedError`, capability flag defaults to `False`, so behaviour
is identical for every existing caller.

### Phase 2 — OpenAI-compatible providers

Files:

- [`lib/ai/providers/basic_openai_provider.py`](../../lib/ai/providers/basic_openai_provider.py)
  — implement `_generateStructured` on `BasicOpenAIModel` (factor the
  shared "build params + call API + parse choices" logic with
  `_generateText` if it stays readable; otherwise duplicate the small
  body — clarity beats cleverness). Subclasses inherit automatically.
- New unit tests in [`lib/ai/providers/test_basic_openai_provider.py`](../../lib/ai/providers/test_basic_openai_provider.py)
  covering:
  - Happy path: model returns valid JSON object → `data` populated, status FINAL.
  - Truncated response with valid JSON → status TRUNCATED_FINAL, `data` populated.
  - Truncated response with invalid JSON → status ERROR, `data=None`,
    `error` is `JSONDecodeError`, `resultText` preserved.
  - Content filter → status CONTENT_FILTER, `data=None`.
  - `BadRequestError` (provider rejects schema) → status ERROR, `error` set.
  - `tools=` not in signature — type-check enforces.
  - `support_structured_output=False` → public `generateStructured` raises
    `NotImplementedError` without ever hitting `_generateStructured`.
  - `response_format` payload formatted correctly: type `json_schema`,
    name, schema dict, strict flag — verified via call-args inspection.
- Add structured-output cases to existing
  [`test_openrouter_provider.py`](../../lib/ai/providers/test_openrouter_provider.py)
  and [`test_yc_openai_provider.py`](../../lib/ai/providers/test_yc_openai_provider.py)
  to confirm the inherited path still works with their `_getExtraParams`
  / `_getModelId` overrides.

Verification:

```
make format lint
./venv/bin/pytest lib/ai/providers -v
```

### Phase 3 — YC SDK no-op + manager pass-through

Files:

- [`lib/ai/providers/yc_sdk_provider.py`](../../lib/ai/providers/yc_sdk_provider.py)
  — override `_generateStructured` to raise with a clear TODO message
  pointing at this plan.
- [`lib/ai/test_manager.py`](../../lib/ai/test_manager.py) —
  `MockModel._generateStructured` returning a fixed
  `ModelStructuredResult` so manager-level tests can exercise the new
  surface without provider plumbing. Add a couple of tests verifying
  `getInfo()["support_structured_output"]` round-trips through
  `LLMManager.getModelInfo`.

Verification:

```
./venv/bin/pytest lib/ai -v
```

### Phase 4 — `LLMService` wrapper

Files:

- [`internal/services/llm/service.py`](../../internal/services/llm/service.py)
  — add `generateStructured` (signature in §3.7).
- [`tests/test_llm_service.py`](../../tests/test_llm_service.py) — new
  cases:
  - Both models support → forwards to
    `model.generateStructuredWithFallBack` with the right kwargs.
  - Primary doesn't support, fallback does → swap happens; fallback gets
    the call.
  - Neither supports → `NotImplementedError` raised before any model call.
  - Rate-limit applied for non-`None` `chatId`.
  - String prompt is wrapped in a single `ModelMessage` (parity with
    `generateText`).

Verification:

```
./venv/bin/pytest tests/test_llm_service.py -v
```

### Phase 5 — Config flips

Files:

- [`configs/00-defaults/openrouter-models.toml`](../../configs/00-defaults/openrouter-models.toml)
- [`configs/00-defaults/openrouter-models-free.toml`](../../configs/00-defaults/openrouter-models-free.toml)
- [`configs/00-defaults/yc-openai-models.toml`](../../configs/00-defaults/yc-openai-models.toml)
- [`configs/00-defaults/yc-sdk-models.toml`](../../configs/00-defaults/yc-sdk-models.toml)
  — explicitly `support_structured_output = false` for clarity.

Apply per the table in §3.9. **Do not flip a model to `true` without a
recorded golden scenario (§5.3) confirming it works.** Every flip should
be a separate commit with the matching golden file in the same diff.

Verification:

```
./venv/bin/python3 main.py --print-config --config-dir configs/00-defaults --config-dir configs/local
```

Spot-check that the flag appears for the expected models.

### Phase 6 — Golden-data tests

Files:

- [`tests/lib_ai/golden/input/openrouter_scenarios.json`](../../tests/lib_ai/golden/input/) —
  add 1–2 structured-output scenarios per supported provider. Schema is a
  toy — e.g. `{type: object, properties: {nCards: {type: integer},
  positions: {type: array, items: {type: string}}}}`. The scenario runner
  needs a tiny extension to call `generateStructured` instead of
  `generateText` when the scenario's `kind` is `"structured"`.
- [`tests/lib_ai/golden/test_golden.py`](../../tests/lib_ai/golden/test_golden.py)
  — add `test_openrouter_structured` and `test_yc_openai_structured`
  mirroring the existing `test_openrouter_basic`. Assert:
  - `result.status == ModelResultStatus.FINAL`
  - `result.data` is a dict matching the schema's required keys
  - `result.resultText` is non-empty (raw JSON string)
- [`tests/lib_ai/golden/collect.py`](../../tests/lib_ai/golden/collect.py)
  — extend to drive a structured-output scenario type. Same env-var
  contract; same masking.

Recording flow (one-off, manual, not in CI):

```bash
export OPENROUTER_API_KEY=...
./venv/bin/python3 tests/lib_ai/golden/collect.py --provider openrouter
```

Replay (in CI, no creds):

```
./venv/bin/pytest tests/lib_ai/golden -v
```

### Phase 7 — Docs

Files:

- [`docs/llm/libraries.md`](../llm/libraries.md) §1 — add
  `generateStructured` to the `AbstractModel` API table, document
  `ModelStructuredResult`, mention the capability flag.
- [`docs/llm/services.md`](../llm/services.md) — `LLMService` section —
  add `generateStructured` to the public API list.
- [`docs/llm/index.md`](../llm/index.md) — last-updated date bump only;
  no architecture change.
- [`AGENTS.md`](../../AGENTS.md) — add a one-liner under "Hard rules":
  > **No pydantic.** The repo deliberately avoids it. Use raw dicts +
  > hand-rolled type-hinted classes. If a library boundary needs JSON
  > Schema, pass dicts.

Verification: re-read the touched docs end-to-end. No code-change tests
needed.

## 6. Touch-ups & Loose Ends

- `ModelRunResult.__str__` ([`lib/ai/models.py:906`](../../lib/ai/models.py:906))
  emits a `retDict` with `resultText`, `toolCalls`, etc. The
  `ModelStructuredResult` should override `__str__` (or, more cleanly,
  the parent should look up `getattr(self, "data", None)` so the subclass
  prints `data` automatically). Pick whichever is cleaner at write time;
  add a unit test asserting `data` shows up in the string form.
- `printJSONLog` ([`lib/ai/abstract.py:384`](../../lib/ai/abstract.py:384))
  early-returns when `result.resultText` is empty. For a structured call
  that succeeded, `resultText` is the raw JSON string (non-empty), so the
  guard is fine. Add a regression test to lock that in.
- The `tokensCountCoeff` heuristic in
  [`AbstractModel.getEstimateTokensCount`](../../lib/ai/abstract.py:276)
  is the same one used by text. Schemas tend to be small, so the existing
  formula is fine; we only add the schema's tokens to the estimate (§3.2).

## 7. Risks & Open Questions

- **OpenRouter-model coverage drift.** Models on OpenRouter come and go;
  a model that supported structured output last week may degrade. The
  `# unverified` convention in §3.9 plus per-model golden recordings is
  our defence. CI replay is deterministic; only the recording step
  (manual) catches regressions, so recordings should be refreshed before
  any release that depends on the feature.
- **YC OpenAI-compatible behaviour for `response_format`.** Yandex's
  OpenAI-compatible endpoint claims compatibility, but we have no live
  evidence it accepts `json_schema` mode. Keep all `yc-openai` models at
  `false` until a golden recording proves otherwise; treat the table in
  §3.9 as conservative.
- **Strict-mode compatibility.** Some OpenRouter providers silently
  ignore `strict: true` and return well-formed-but-non-validated JSON.
  The plan accepts this — strict is an *aspiration*, not a guarantee. If
  a caller needs hard validation, it must validate the returned `data`
  itself (no jsonschema dep planned).
- **YC SDK refactor scheduling.** A separate plan should pick up YC SDK
  structured output. Likely involves either per-call model-clone
  semantics or a connection-pool/SDK-handle-per-call pattern. Out of
  scope here.
- **Token accounting for the schema.** `getEstimateTokensCount(schema)`
  is a rough overestimate (JSON is dense). Acceptable for the
  `contextSize * 2` budget guard; not used for billing.

## 8. Acceptance Criteria

A reviewer should be able to confirm all of the following:

1. `from lib.ai import ModelStructuredResult` works and the type exposes
   `.data: Optional[Dict[str, Any]]`.
2. `AbstractModel.generateStructured` raises `NotImplementedError` when
   `support_structured_output` is False.
3. For an OpenAI-compatible provider with the flag set, the call sends
   `response_format = {"type": "json_schema", ...}` to the API and
   returns a `ModelStructuredResult` with parsed `data` on success.
4. `LLMService.generateStructured` resolves models, applies rate
   limiting, and falls back correctly when the primary fails or lacks
   the capability.
5. `tests/lib_ai/golden/test_golden.py` has at least one passing
   structured-output replay test per opt-in provider (OpenRouter +
   YC OpenAI when verified).
6. All `make format lint` and `make test` checks pass.
7. `AGENTS.md` carries the no-pydantic rule.
8. The divination handler stub
   [`_llmGetUnknownLayoutShape`](../../internal/bot/common/handlers/divination.py:826)
   can now be filled in (separate follow-up; not part of this plan).

---

*Plan author: software-architect agent. Last updated: 2026-05-06*
