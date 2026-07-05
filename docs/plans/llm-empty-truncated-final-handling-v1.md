# Plan: Handling Empty TRUNCATED_FINAL LLM Responses

Status: PLANNED — the fix is not yet implemented. Item 1 (observability) IS
implemented in the working tree (uncommitted); see "Already Implemented". The
actual fix — provider downgrade (Option A) and bot-side guard (Option B) — is
still to be done.

Date: 2026-07-05
Owner: TBD

## Problem

Recurring production failure with this signature in the logs:

```
WARNING - internal.bot.common.typing_manager:169 - TypingManager::sendTypingAction(): not running
ERROR - internal.bot.common.bot:830 - Error while sending MarkdownV2 reply to message: BadRequest#Message text is empty
ERROR - internal.bot.common.bot:860 - Error while sending message: BadRequest#Message text is empty
```

Root cause (verified by code investigation): an OpenAI-compatible API returns
`finish_reason="length"` with an empty `message.content`. The strongly suspected
driver is reasoning-token budget exhaustion on Qwen3-class models — the failing
log shows `outputTokens=32768` matching the configured `max_tokens` cap, with
zero visible content. That empty content then flows unchecked through every
layer (provider → abstract fallback → service → handler → bot send path) and
reaches python-telegram-bot as `send_message(text="")`, which raises
`BadRequest: Message text is empty`.

## Verified Code-Path Map

The failure chain, top to bottom, with file:line references:

1. [`lib/ai/models.py:796-823`](../../lib/ai/models.py) — `ModelResultStatus`
   enum. There is NO bare `TRUNCATED` and NO `SUCCESS`; the success status is
   named `FINAL = 3`. `TRUNCATED_FINAL = 2`.
2. [`lib/ai/models.py:828-835`](../../lib/ai/models.py) — `ERROR_STATUSES`
   frozenset. CRITICAL: `TRUNCATED_FINAL` and `PARTIAL` are NOT in
   `ERROR_STATUSES`, so the fallback machinery treats them as success.
3. [`lib/ai/providers/basic_openai_provider.py:346-362`](../../lib/ai/providers/basic_openai_provider.py)
   — `finish_reason="length"` → `status=TRUNCATED_FINAL`;
   `resText = retMessage.content if retMessage.content else ""` (empty → `""`).
4. [`lib/ai/providers/basic_openai_provider.py:453-461`](../../lib/ai/providers/basic_openai_provider.py)
   — `_generateText` returns `ModelRunResult(resultText="", status=TRUNCATED_FINAL,
   rawResult=<full ChatCompletion>)`. No empty-text check on the text path.
5. [`lib/ai/providers/basic_openai_provider.py:548-551`](../../lib/ai/providers/basic_openai_provider.py)
   — the STRUCTURED-output path ALREADY guards:
   `if not outcome.resText: raise ValueError("Structured output: model returned
   empty content")`. This asymmetry between the text and structured paths is the
   central inconsistency (see below).
6. [`lib/ai/abstract.py:596-668`](../../lib/ai/abstract.py) — `_runWithFallback`.
   The decision at line 658 is `result.status not in ERROR_STATUSES` → it returns
   immediately for `TRUNCATED_FINAL`, with no fallback attempted. It never
   inspects `result.resultText`.
7. [`lib/ai/abstract.py:812-814`](../../lib/ai/abstract.py) — `printJSONLog`
   skips empty results (`if not result.resultText:`), so file-based logging also
   misses this case.
8. [`internal/services/llm/service.py:539-604`](../../internal/services/llm/service.py)
   — `generateTextViaLLM`. Only special-cases `FINAL` (line 540) and `TOOL_CALLS`
   (line 551). `TRUNCATED_FINAL` falls through to `break` at line 598 and is
   returned as-is.
9. [`internal/bot/common/handlers/llm_messages.py:264`](../../internal/bot/common/handlers/llm_messages.py)
   — `lmRetText = mlRet.resultText.strip()` → `""`. No guard before
   `sendMessage(messageText=lmRetText)` at line 342.
10. [`internal/bot/common/bot.py:668-670`](../../internal/bot/common/bot.py) —
    guard only rejects `None` text, NOT the empty string `""`
    (`if photoData is None and messageText is None and attachmentList is None:`).
    So `send_message(text="")` reaches python-telegram-bot and raises
    `BadRequest: Message text is empty`.

Line-number caveat for `basic_openai_provider.py`: items 4 and 5 (and the
references in "Central Inconsistency" / Option A) use the committed-baseline
line numbers from the original investigation — i.e. before the "Already
Implemented" observability block was inserted. That block (shown as lines
364-406 above) adds ~44 lines before `_generateText`'s text return and the
structured-output guard, so in the current working tree they sit near line 500
and line 596 respectively. The provider file is under concurrent edit; when
implementing, re-locate these by symbol (`_generateText`, `_generateStructured`)
rather than by line number. References in all other files (models.py,
abstract.py, service.py, llm_messages.py, bot.py) are stable and verified
against the working tree.

## Central Inconsistency

The structured-output path at
[`basic_openai_provider.py:548-551`](../../lib/ai/providers/basic_openai_provider.py)
already treats empty content as a hard error:

```python
if outcome.status in (ModelResultStatus.FINAL, ModelResultStatus.TRUNCATED_FINAL):
    ...
    if not outcome.resText:
        raise ValueError("Structured output: model returned empty content")
```

The text-output path at
[`basic_openai_provider.py:453-461`](../../lib/ai/providers/basic_openai_provider.py)
has no equivalent check — empty `resultText` passes through silently. Any fix
should make the two paths consistent in their treatment of empty content
(whether by downgrade, raise, or explicit fallback).

## Already Implemented

Item 1 (observability-only diagnostics) is present in the working tree,
currently uncommitted, in
[`basic_openai_provider.py::_executeChatCompletion`](../../lib/ai/providers/basic_openai_provider.py)
at lines 364-406. It fires when the API call succeeded but produced no usable
text on a status that should have content:

```python
if not resText.strip() and status in (
    ModelResultStatus.TRUNCATED_FINAL,
    ModelResultStatus.CONTENT_FILTER,
    ModelResultStatus.UNKNOWN,
):
    ...
    logger.warning(f"Anomalous empty LLM response from {self.provider}/{self.modelId}: ...")
```

The dump includes `finishReason`, `status`, `resText`, `inputTokens`,
`outputTokens`, `totalTokens`, `completion_tokens_details` (exposes
`reasoning_tokens`, the key signal for the budget-exhaustion hypothesis),
`prompt_tokens_details`, and the full `response.model_dump_json()` (with a
`str()` fallback for non-pydantic vendors).

Scope is strictly observability: `status`, `resText`, and the returned
`_OpenAICallOutcome` are NOT modified, so the empty content still flows through
every downstream layer unchanged. This change makes the bug diagnosable but
does NOT fix it — Options A and B below are still required.

Note: this diagnostic exists only in the OpenAI-compatible provider. The YC SDK
provider ([`yc_sdk_provider.py:487`](../../lib/ai/providers/yc_sdk_provider.py))
has no equivalent, so empty content from that provider remains silent.

Nothing else for this bug is implemented yet.

## Options

### Option A — Provider-side empty-output downgrade (RECOMMENDED for next pass)

- Location: [`lib/ai/providers/basic_openai_provider.py`](../../lib/ai/providers/basic_openai_provider.py),
  `_generateText` around line 453.
- Mechanism: if `outcome.status in (FINAL, TRUNCATED_FINAL)` and
  `not outcome.resText.strip()`, downgrade `status` to `ERROR` with an
  explanatory `error`. The existing `_runWithFallback` then naturally tries the
  fallback model.
- Pros: smallest change; mirrors the existing structured-output guard
  (lines 548-551); reuses the existing fallback machinery; no abstract-layer
  semantic change.
- Cons: provider-specific — would need to be repeated in
  [`lib/ai/providers/yc_sdk_provider.py`](../../lib/ai/providers/yc_sdk_provider.py),
  which at line 487 returns `result.alternatives[0].text` with no emptiness
  check.
- Risks: if a model legitimately returns empty content as a valid response
  (rare for chat), this forces an unnecessary fallback. Mitigation: limit the
  downgrade to `TRUNCATED_FINAL` / `UNKNOWN` / `CONTENT_FILTER`, not bare
  `FINAL`.
- Complexity: ~5 lines per provider.

### Option B — Graceful bot-side fallback (RECOMMENDED for next pass)

- Location: [`internal/bot/common/handlers/llm_messages.py:264`](../../internal/bot/common/handlers/llm_messages.py)
  (after `lmRetText = mlRet.resultText.strip()`), plus a tightening of
  [`internal/bot/common/bot.py:668-670`](../../internal/bot/common/bot.py).
- Mechanism: if `lmRetText` is empty AND no tool calls AND no media were
  produced, either (a) send a configured fallback message, (b) silently drop +
  warn-log, or (c) send a per-chat configurable message. User decision required
  on which UX (see Open Decisions). Additionally, tighten the `bot.py` guard so
  it rejects the empty-string `messageText` the same way it rejects `None` — a
  pure safety net.
- Pros: defense in depth; correct UX even when both primary and fallback models
  fail; the `bot.py` guard prevents the `BadRequest` from ever reaching the API
  again.
- Cons: the silent-drop variant could hide future regressions (mitigate with a
  WARNING log).
- Risks: minimal.
- Complexity: ~10 lines across two files.

### Option C — Abstract-layer empty-text success test

- Location: [`lib/ai/abstract.py:658`](../../lib/ai/abstract.py).
- Mechanism: extend the success test from `result.status not in ERROR_STATUSES`
  to also require `(result.resultText or result.toolCalls or result.mediaData)`.
- Pros: centralizes the rule for all providers.
- Cons: the abstract layer does not distinguish text vs structured vs tool-only
  turns; a tool-call-only turn legitimately has empty `resultText`. The guard
  must account for that.
- Risks: changing abstract semantics affects all providers and all call types —
  wider blast radius.
- Complexity: ~3 lines, but needs careful test coverage. DEFER unless Option A
  proves insufficient.

### Option D — Prompt / param tuning for reasoning-heavy models

- Mechanism: per-model config to raise `max_tokens` / `max_completion_tokens`,
  or pass `reasoning_effort="low"`, or for Qwen3 set `enable_thinking=False`
  via `extra_body`.
- Pros: addresses the suspected root cause (reasoning-budget exhaustion)
  directly.
- Cons: model-specific; trades quality (reasoning) for reliability; requires a
  per-model config surface.
- Risks: tuning drift; different models expose different parameter names.
- Complexity: config-schema work plus per-model validation. DEFER — treat as a
  separate model-tuning decision after Options A and B land.

### Option E — Retry-with-conciser-prompt on empty TRUNCATED_FINAL

- Mechanism: on empty `TRUNCATED_FINAL`, retry the SAME model with a rewritten
  prompt asking for brevity (e.g. append "Answer in 2-3 sentences").
- Pros: recovers from reasoning-budget exhaustion without changing model
  parameters.
- Cons: heavier — a real second LLM call, added latency and cost; overlaps with
  the fallback-model mechanism; prompt rewriting is fragile.
- Risks: the same model family may exhibit the same bug.
- Complexity: medium. DEFER unless Option A proves insufficient in practice.

## Recommended Scope for Next Implementation Pass

1. Option A — provider-side empty-output downgrade. (Observability / "Item 1"
   is already done — see "Already Implemented" — so the reasoning-budget
   hypothesis can now be confirmed from logs before this change lands.)
2. Option B — graceful bot-side fallback + tightened `bot.py` empty-string guard.
3. Regression tests per the Test Plan below.

Options C, D, and E are deferred.

## Open Decisions (require user input)

1. Bot-side empty-response UX: (a) send a fallback notice, (b) silent drop +
   warn-log, (c) per-chat configurable message.
2. Should the provider-side downgrade (Option A) also cover bare `FINAL` with
   empty text, or only `TRUNCATED_FINAL` / `UNKNOWN` / `CONTENT_FILTER`?
3. Whether to extend Option A to
   [`lib/ai/providers/yc_sdk_provider.py`](../../lib/ai/providers/yc_sdk_provider.py)
   in the same pass (the YC provider has no emptiness check at line 487).

## Test Plan (for next pass)

- Regression: provider downgrades empty `TRUNCATED_FINAL` to `ERROR`.
- Regression: fallback fires on the downgraded result.
- Regression: bot-side guard catches empty `resultText` even when status is
  `FINAL`.
- Regression: `_sendTelegramMessage` rejects empty-string `messageText`.
- No regression: a legitimate tool-call-only turn (empty `resultText`, populated
  `toolCalls`) is NOT downgraded.

## References

- [`lib/ai/abstract.py`](../../lib/ai/abstract.py) — model run loop, fallback orchestrator
- [`lib/ai/models.py`](../../lib/ai/models.py) — `ModelResultStatus`, `ERROR_STATUSES`, `ModelRunResult`
- [`lib/ai/providers/basic_openai_provider.py`](../../lib/ai/providers/basic_openai_provider.py) — OpenAI-compatible provider
- [`lib/ai/providers/yc_sdk_provider.py`](../../lib/ai/providers/yc_sdk_provider.py) — YC SDK provider (no emptiness check)
- [`internal/services/llm/service.py`](../../internal/services/llm/service.py) — `LLMService.generateTextViaLLM`
- [`internal/bot/common/handlers/llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py) — `_sendLLMChatMessage`
- [`internal/bot/common/bot.py`](../../internal/bot/common/bot.py) — `_sendTelegramMessage`
