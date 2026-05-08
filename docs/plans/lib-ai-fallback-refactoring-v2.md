# lib/ai Fallback Mechanism Refactoring — V2

Supersedes [`lib-ai-fallback-refactoring.md`](lib-ai-fallback-refactoring.md).
V2 tightens the scope, fixes gaps found in V1 review, and splits the work into
three clean PRs.

## Goal

Consolidate the three duplicated fallback methods (`generateTextWithFallBack`,
`generateImageWithFallBack`, `generateStructuredWithFallBack`) in
[`lib/ai/abstract.py`](../../lib/ai/abstract.py) into a single reusable helper,
and expose fallback behavior through an optional `fallbackModels` parameter on
the public `generateText` / `generateImage` / `generateStructured` methods.

Secondary goal: generalize "one fallback" to "an ordered list of fallbacks"
while keeping behavior equivalent for current single-fallback callers.

## Non-goals

- Changing return types, status semantics, or rate-limiting behavior.
- Moving any orchestration that currently lives in
  [`internal/services/llm/service.py`](../../internal/services/llm/service.py)
  (the structured-output primary/fallback **swap** based on
  `support_structured_output` stays in `LLMService` — `lib/ai` stays agnostic
  about chat-settings-derived fallback selection).
- Adding any new capability beyond the list-of-fallbacks generalization.

## Guiding decisions (from V1 review)

1. **`generateImage` abstractness split.** Mirror the text path: introduce
   `_generateImage` as the new `@abstractmethod`; turn `generateImage` into a
   concrete wrapper that handles fallback dispatch and JSON logging. Rename
   existing provider implementations from `generateImage` → `_generateImage`.
2. **Helper owns the list.** `_runWithFallback` receives a non-empty list of
   models and a single callable; it iterates the list, stops on first success,
   sets `isFallback=True` on every result from a non-primary model.
3. **On all-fail: return the last result** (mirrors current `generate*WithFallBack`
   semantics — the last fallback's error result bubbles out, no exception
   raised from the helper itself).
4. **Atomic refactor, no permanent aliases.** Split into three sequential PRs
   (see "PR breakdown" below). Temporary aliases live for at most two PRs;
   duplication is eliminated from PR 1 onward.
5. **Error-status set extracted.** Add `ModelResultStatus.isError()` (or
   module-level `ERROR_STATUSES` frozenset) in
   [`lib/ai/models.py`](../../lib/ai/models.py) so the trigger set is defined
   once, not inlined.
6. **Unified fallback flag setter.** Use `result.setFallback(True)` everywhere.
   `ModelStructuredResult` already inherits `setFallback` from `ModelRunResult`
   (see [`lib/ai/models.py:877`](../../lib/ai/models.py) via inheritance from
   line 1039). Fixes the pre-existing inconsistency at
   [`lib/ai/abstract.py:452`](../../lib/ai/abstract.py) which writes
   `ret.isFallback = True` directly.
7. **LLMService orchestration untouched.** The primary/fallback swap for
   structured output at
   [`internal/services/llm/service.py:622-634`](../../internal/services/llm/service.py)
   stays in LLMService. The helper in `lib/ai` receives whatever list the
   caller assembles.
8. **Multi-fallback generalization is a free win, not a feature ask.** No
   current caller passes more than one fallback. The `list[AbstractModel]`
   parameter is added because the helper naturally generalizes; callers
   migrate one-for-one with `fallbackModels=[fallbackModel]`.

## Design

### 1. `ModelResultStatus.isError()` / `ERROR_STATUSES`

Add to [`lib/ai/models.py`](../../lib/ai/models.py) alongside `ModelResultStatus`:

```python
# Module-level constant — a frozenset lets callers use `in` without importing
# a classmethod and is cheap to define once.
ERROR_STATUSES: frozenset[ModelResultStatus] = frozenset(
    {
        ModelResultStatus.UNSPECIFIED,
        ModelResultStatus.CONTENT_FILTER,
        ModelResultStatus.UNKNOWN,
        ModelResultStatus.ERROR,
    }
)
```

Prefer the module-level `ERROR_STATUSES` over a classmethod — it's one import,
one name, and matches the flat-data idiom used elsewhere in `lib/ai`. All
inline `if ret.status in [...]` blocks in `abstract.py` become
`if ret.status in ERROR_STATUSES`.

### 2. `_generateImage` abstractness split

Current state (`lib/ai/abstract.py:172-191`): `generateImage` is
`@abstractmethod`; each provider implements it directly. Call sites in
providers inventoried:

- [`lib/ai/providers/basic_openai_provider.py:484`](../../lib/ai/providers/basic_openai_provider.py)
- [`lib/ai/providers/yc_sdk_provider.py:229`](../../lib/ai/providers/yc_sdk_provider.py)

Target state — mirror the text pattern:

```python
# In AbstractModel:

@abstractmethod
async def _generateImage(self, messages: Sequence[ModelMessage]) -> ModelRunResult:
    """Provider-specific image generation implementation."""
    raise NotImplementedError

async def generateImage(
    self,
    messages: Sequence[ModelMessage],
    *,
    fallbackModels: Optional[list["AbstractModel"]] = None,
) -> ModelRunResult:
    """Generate image with optional fallback chain.

    When fallbackModels is None/empty, behaves exactly like the pre-refactor
    generateImage: delegates to _generateImage and returns. When fallbackModels
    is provided, dispatches through _runWithFallback.

    Args:
        messages: Prompt and context messages for image generation.
        fallbackModels: Ordered list of models to try if this model fails.
            Each will be tried in sequence via its own public generateImage
            (with fallbackModels=None to avoid nested recursion).

    Returns:
        ModelRunResult. isFallback=True if the returned result came from any
        non-primary model.
    """
    if fallbackModels:
        return await self._runWithFallback(
            [self, *fallbackModels],
            lambda model: model.generateImage(messages),
        )
    ret = await self._generateImage(messages)
    if self.enableJSONLog:
        self.printJSONLog(messages, ret)
    return ret
```

Provider-side rename: `generateImage` → `_generateImage` in both providers
listed above. No signature changes beyond the leading underscore.

Note: unlike `generateText`, `generateImage` historically performs no
context-size check or token estimation. The refactor preserves this — we add
JSON logging (to match the text path) but do **not** introduce a token budget
check. Changing that is out of scope.

### 3. `_runWithFallback` helper

Single private method on `AbstractModel`:

```python
async def _runWithFallback(
    self,
    models: list["AbstractModel"],
    call: Callable[["AbstractModel"], Awaitable[_R]],
) -> _R:
    """Run `call(model)` over `models` until one succeeds.

    Iterates the list in order. For each model, invokes the callable and
    inspects the result's status. A result whose status is in ERROR_STATUSES
    (or a raised exception) is treated as failure and the next model is tried.

    The first non-exception success result is returned immediately. If every
    model fails (either by ERROR_STATUSES result or by exception), the LAST
    attempted model's result is returned — matching the pre-refactor
    `generate*WithFallBack` behavior where the fallback result bubbled out
    regardless of its status.

    isFallback is set to True on the returned result iff it came from any
    model other than models[0].

    Args:
        models: Non-empty ordered list. models[0] is the primary, the rest
            are fallbacks in preference order.
        call: Callable that takes a model and returns an awaitable result
            (ModelRunResult or ModelStructuredResult). Must invoke the
            PUBLIC generate* method with fallbackModels=None so each attempt
            gets the full pipeline (context check + JSON log) without
            recursing into this helper.

    Returns:
        The result of the first successful model, or the last attempted
        model's result on total failure.

    Raises:
        ValueError: If models is empty.
    """
```

Key properties:

- **Invokes the public method** (`model.generateText(..., fallbackModels=None)`
  etc.), not `_generateText`, so each attempt runs through its own
  context-size check and JSON logging.
- **Stops on first success** (status not in `ERROR_STATUSES` and no exception).
- **Preserves last result on total failure** — returns the last attempt's
  result as-is (with `setFallback(True)` if it wasn't the primary). No
  exception raised from the helper.
- **Degenerate cases handled explicitly:**
  - Empty list → `ValueError`.
  - Single-element list → calls once; `isFallback` stays False.
  - Duplicate models in list (e.g. `[m, m]`) → called once per slot;
    rate-limiting is the caller's responsibility (see test below).

Exception handling mirrors the current code: a raised exception is logged and
treated as failure; the helper moves on to the next model. The exception is
*not* re-raised — only the last result is returned. This matches
[`abstract.py:235-239`](../../lib/ai/abstract.py).

### 4. Public API changes

Add keyword-only `fallbackModels: Optional[list[AbstractModel]] = None` to:

- `generateText(messages, tools=None, *, fallbackModels=None)`
- `generateImage(messages, *, fallbackModels=None)` — new signature per §2.
- `generateStructured(messages, schema, *, schemaName="response", strict=True, fallbackModels=None)`

Each method, when `fallbackModels` is provided (non-empty), routes through
`_runWithFallback([self, *fallbackModels], lambda m: m.generateText(..., fallbackModels=None))`.
When absent, behavior is byte-identical to pre-refactor (same token check,
same `_generate*` call, same JSON logging).

### 5. `isFallback` flag handling

Inside `_runWithFallback`, after selecting the return result and before
returning, call `result.setFallback(model is not models[0])` (or equivalently
`setFallback(True)` only when the successful index is > 0). This uses the
inherited `ModelRunResult.setFallback` method and works for
`ModelStructuredResult` without modification.

Ancillary fix: the existing bare assignment
`ret.isFallback = True` at
[`lib/ai/abstract.py:452`](../../lib/ai/abstract.py) is removed (that code
path goes away entirely once `generateStructuredWithFallBack` is deleted in
PR 3, so no separate fix needed — it's deleted wholesale).

## PR breakdown

### PR 1 — lib/ai refactor

Scope: introduce the new API **and** deduplicate code in the same PR. The
`generate*WithFallBack` methods are converted to thin aliases calling the new
API, so the duplication is eliminated on day one (this is the whole point of
the refactor — not deferred to PR 3).

Changes:

1. Add `ERROR_STATUSES` frozenset to [`lib/ai/models.py`](../../lib/ai/models.py).
2. Split `generateImage` into `_generateImage` (abstract) + `generateImage`
   (concrete wrapper) in [`lib/ai/abstract.py`](../../lib/ai/abstract.py).
   Rename `generateImage` → `_generateImage` in
   [`lib/ai/providers/basic_openai_provider.py`](../../lib/ai/providers/basic_openai_provider.py)
   and [`lib/ai/providers/yc_sdk_provider.py`](../../lib/ai/providers/yc_sdk_provider.py).
3. Add `_runWithFallback` helper to `AbstractModel`.
4. Add `fallbackModels` keyword-only parameter to `generateText`,
   `generateImage`, `generateStructured`.
5. Rewrite `generateTextWithFallBack`, `generateImageWithFallBack`,
   `generateStructuredWithFallBack` as thin aliases:
   ```python
   async def generateTextWithFallBack(self, messages, fallbackModel, tools=None):
       return await self.generateText(messages, tools, fallbackModels=[fallbackModel])
   ```
   Same shape for the image and structured variants. The aliases preserve
   keyword ordering of the old signatures so existing callers
   (`LLMService` and its tests) continue working unchanged.
6. Update lib/ai tests
   ([`lib/ai/test_abstract.py`](../../lib/ai/test_abstract.py)) to exercise
   both paths — existing `generate*WithFallBack` tests keep passing (they're
   alias tests now), plus new tests for the `fallbackModels` parameter.
7. Run `make format lint && make test` — all green before merge.

**After PR 1, lib/ai has zero duplicated fallback logic.** Aliases forward
to the new helper.

### PR 2 — LLMService migration

Scope: update call sites in `LLMService` and its tests. Pure rename/signature
update; no behavior change.

Changes:

1. Migrate the three call sites in
   [`internal/services/llm/service.py`](../../internal/services/llm/service.py):
   - Line 553: `llmModel.generateTextWithFallBack(prompt, fallbackModel, tools=tools)`
     → `llmModel.generateText(prompt, tools, fallbackModels=[fallbackModel])`
   - Line 645-647: `generateStructuredWithFallBack(prompt, fallbackModel, schema=..., schemaName=..., strict=...)`
     → `generateStructured(prompt, schema, schemaName=..., strict=..., fallbackModels=[fallbackModel])`
   - Line 677: `generateImageWithFallBack([...], fallbackImageLLM)`
     → `generateImage([...], fallbackModels=[fallbackImageLLM])`
2. Update docstring references at `service.py:512, 576` that name
   `generateTextWithFallBack` / `generateStructuredWithFallBack`.
3. Update tests that mock the old methods:
   - [`tests/test_llm_service.py`](../../tests/test_llm_service.py) — ~60
     references to `generateTextWithFallBack` / `generateStructuredWithFallBack`.
   - [`tests/integration/test_llm_integration.py`](../../tests/integration/test_llm_integration.py) — ~17
     references.
   All `mockModel.generateTextWithFallBack = AsyncMock(...)` become
   `mockModel.generateText = AsyncMock(...)`; all
   `.assert_called_once()` / `.call_args` / `.call_count` assertions switch
   correspondingly. The mock arg tuple shape changes too:
   `(messages, tools, fallbackModels=[fallback])` instead of
   `(messages, fallbackModel, tools=tools)` — assertions that inspect
   positional args need adjusting.
4. Run `make format lint && make test`.

### PR 3 — cleanup

Scope: delete the aliases once nothing calls them.

Changes:

1. Delete `generateTextWithFallBack`, `generateImageWithFallBack`,
   `generateStructuredWithFallBack` from
   [`lib/ai/abstract.py`](../../lib/ai/abstract.py).
2. Delete the three alias-specific tests in
   [`lib/ai/test_abstract.py:253-322`](../../lib/ai/test_abstract.py) (the
   `generateStructuredWithFallBack` test block). The new-API equivalents
   landed in PR 1.
3. Update documentation (see "Documentation updates" below).
4. `rg generate.*WithFallBack` across the repo must return zero matches before
   merge.

## Testing plan

PR 1 adds the following tests to
[`lib/ai/test_abstract.py`](../../lib/ai/test_abstract.py):

1. `test_generateText_withFallbackModels_usesFirstOnSuccess` — primary succeeds,
   fallbacks never called, `isFallback == False`.
2. `test_generateText_withFallbackModels_fallsBackOnErrorStatus` — primary
   returns `ERROR`, first fallback succeeds, `isFallback == True`.
3. `test_generateText_withFallbackModels_fallsBackOnException` — primary
   raises, first fallback succeeds, `isFallback == True`.
4. `test_generateText_withFallbackModels_chainExhausted_returnsLastResult` —
   all models fail; helper returns the last fallback's error result,
   `isFallback == True` (since it's not the primary), no exception raised.
5. `test_generateText_withFallbackModels_multipleFallbacks` — list of length
   3 (primary + 2 fallbacks); second fallback succeeds after primary and
   first fallback fail.
6. `test_runWithFallback_emptyList_raisesValueError` — guard-rail test.
7. `test_runWithFallback_duplicateModel_invokedTwice` — degenerate case:
   `fallbackModels=[primary]` or a list containing the same model twice.
   The helper should invoke the callable once per slot (not deduplicate) —
   documents the contract that dedup is the caller's job.
8. Equivalent coverage for `generateImage` and `generateStructured`:
   at minimum, one "success on primary" and one "falls back to second" test
   per method, reusing the existing fixture patterns.
9. Regression: existing `generate*WithFallBack` tests must still pass as-is
   (they now exercise the alias path).

PR 2 adds no new test patterns — it's pure method-name migration in existing
tests.

## Documentation updates

Updated in **PR 3** (after removal, so docs reflect final state):

- [`docs/llm/libraries.md`](../llm/libraries.md) — `lib/ai` section:
  describe `fallbackModels` parameter, remove references to
  `generate*WithFallBack`, note the `_generateImage` split alongside the
  existing `_generateText` / `_generateStructured` documentation.
- [`docs/llm/services.md`](../llm/services.md) — `LLMService` section:
  update example call shapes if any are shown.
- [`docs/developer-guide.md`](../developer-guide.md) — verify no stale
  `generate*WithFallBack` references; update if found.

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| PR 1 alias signature drift breaks LLMService | Aliases preserve the exact keyword ordering of old methods; run full `make test` suite in PR 1 to catch drift. |
| PR 2 mock migration misses a test file | Final check before PR 2 merge: `rg generate.*WithFallBack tests/ internal/` must show only the (still-alive) alias definitions from PR 1. |
| PR 3 removal breaks something that got added between PR 2 and PR 3 | Final check before PR 3 merge: `rg generate.*WithFallBack` across the repo returns zero matches. |
| Provider signature drift from `_generateImage` rename | Only two providers implement it; flake8/pyright catches the mismatch immediately. |
| Nested-fallback accidental recursion | `_runWithFallback` always calls the public method with `fallbackModels=None`; documented in the helper's docstring and covered by the chain-exhausted test. |
| `ERROR_STATUSES` import cycle | `models.py` defines both the enum and the set; `abstract.py` imports from `models.py` as it already does for the enum itself. No cycle. |

## Benefits (reaffirmed, with corrected numbers)

- **Deduplicated**: ~66 lines of near-identical fallback logic (3 methods ×
  ~22 lines each at `abstract.py:193-285, 400-453`) collapse into one
  ~25-line helper.
- **Uniform `isFallback` path**: fixes the current inconsistency where text
  and image paths call `setFallback(True)` and the structured path writes
  `isFallback = True` directly.
- **Extensible**: list-of-fallbacks shape makes adding a third-tier fallback
  (e.g. primary → regional → emergency stub) a one-line caller change.
- **Clearer abstractness**: `_generateImage` / `generateImage` split brings
  image generation in line with the text/structured paths.

## Order-of-ops checklist (for the implementer)

PR 1:
- [ ] `ERROR_STATUSES` frozenset in `models.py`
- [ ] `_generateImage` abstract method added; `generateImage` concrete wrapper written
- [ ] Provider renames in `basic_openai_provider.py` and `yc_sdk_provider.py`
- [ ] `_runWithFallback` helper implemented
- [ ] `fallbackModels` keyword param added to the three public methods
- [ ] `generate*WithFallBack` converted to aliases
- [ ] New tests in `lib/ai/test_abstract.py`
- [ ] `make format lint && make test` green

PR 2:
- [ ] Three call sites in `internal/services/llm/service.py` migrated
- [ ] Docstrings in `service.py` updated (lines 512, 576)
- [ ] `tests/test_llm_service.py` migrated
- [ ] `tests/integration/test_llm_integration.py` migrated
- [ ] `make format lint && make test` green

PR 3:
- [ ] Alias methods deleted from `abstract.py`
- [ ] Alias-specific tests deleted from `lib/ai/test_abstract.py`
- [ ] `docs/llm/libraries.md`, `docs/llm/services.md`,
      `docs/developer-guide.md` reviewed and updated
- [ ] `rg generate.*WithFallBack` returns zero matches
- [ ] `make format lint && make test` green
