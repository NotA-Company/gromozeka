# Plan: Handling Empty TRUNCATED_FINAL LLM Responses

Status: PARTIALLY IMPLEMENTED (re-verified 2026-07-18). Shipped:
- Item 1 — observability-only WARNING dump in `BasicOpenAIModel._executeChatCompletion` (commit `bd9025a`, 2026-07-05).
- Option B handler-half — `_sendLLMChatMessage` treats bare-empty `resultText` as `LLMReplyOutcome.SKIPPED_BY_MODEL` at `internal/bot/common/handlers/llm_messages.py:394` (commit `7e2b5501`, 2026-07-05). Silent-drop UX.

Still pending:
- Option A — provider-side empty-output downgrade in `_generateText` (text path still has no empty-text check; the structured path does — see "Central Inconsistency").
- Option B `bot.py` half — `_sendTelegramMessage` empty-string safety net (guard at `bot.py:668` still rejects `None` only, NOT `""`).
- Test Plan regressions — NONE of the 4 listed tests exist; the existing `tests/bot/common/handlers/test_llm_messages.py::TestRandomAnswerPromptAndSkipSentinel` covers `<skip>` and JSON-wrapped `<skip>` but NOT the bare-empty `""` branch. This is an AGENTS.md "Regression tests on every bug fix" violation against the shipped handler-half; see "Test Plan".

Sibling mitigation (does NOT cover the original bug surface):
- Service-layer post-budget synthesizer at `internal/services/llm/service.py:926-951` (commit `10e99c3`) substitutes a fallback answer for empty `FINAL` / post-budget `TOOL_CALLS` when the round budget is exhausted — but explicitly EXCLUDES `TRUNCATED_FINAL` (status guard is `ret.status in (FINAL, TOOL_CALLS)`), so single-shot empty `TRUNCATED_FINAL` from a no-tools call still propagates untouched. See "Already Implemented".

Date: 2026-07-05
Last updated: 2026-07-18
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
9. [`internal/bot/common/handlers/llm_messages.py:326`](../../internal/bot/common/handlers/llm_messages.py)
   — `lmRetText = mlRet.resultText.strip()` → `""`. **A guard now exists at
   line ~394** (commit `7e2b5501`, 2026-07-05):
   `if imagePrompt is None and lmRetText.strip().strip("`").strip() in ("<skip>", ""): return LLMReplyOutcome.SKIPPED_BY_MODEL`.
   This is the handler-level half of Option B — see "Already Implemented".
   It runs BEFORE the `sendMessage(messageText=lmRetText)` call, so the
   empty-string `sendMessage` invocation never fires in the normal LLM-reply
   path.
10. [`internal/bot/common/bot.py:668-670`](../../internal/bot/common/bot.py) —
    guard only rejects `None` text, NOT the empty string `""`
    (`if photoData is None and messageText is None and attachmentList is None:`).
    So `send_message(text="")` still reaches python-telegram-bot from any
    caller that bypasses the handler guard. The handler guard above (#9)
    covers the LLM-reply path, but other `sendMessage` callers remain
    exposed — the `bot.py` tightening called for in Option B is still
    pending.

Line-number caveat: line numbers in this plan come from the original
2026-07-05 investigation; the tree has drifted significantly since.
Re-locate every reference by **symbol**, not by line number. Re-verified
2026-07-18 against the working tree — current approximate locations:

- `lib/ai/models.py`: `ModelResultStatus` at line ~923 (was 796-823);
  `ERROR_STATUSES` at line ~955 (was 828-835).
- `lib/ai/providers/basic_openai_provider.py`: `_executeChatCompletion` at
  line ~276; the Item 1 observability block at lines ~374-423 (was 364-406);
  `_generateText` at line ~436, text-path return at lines ~515-523 (was
  453-461); `_generateStructured` at line ~525, empty-content guard at
  lines ~611-615 (was 548-551).
- `lib/ai/abstract.py`: `_runWithFallback` at line ~596, success test at
  line ~658 (was 658 — stable); `printJSONLog` at line ~784, empty-result
  skip at lines ~812-814 (was 812-814 — stable).
- `internal/services/llm/service.py`: `generateTextViaLLM` at line ~657
  (was 539); post-budget synthesizer at lines ~926-951 (added by commit
  `10e99c3` after the original investigation — see "Already Implemented").
- `internal/bot/common/handlers/llm_messages.py`: `lmRetText =
  mlRet.resultText.strip()` at line ~326 (was 264); Option B handler-half
  guard at line ~394 (added by commit `7e2b5501` — see "Already
  Implemented").
- `internal/bot/common/bot.py`: `_sendTelegramMessage` None-only guard at
  line ~668 (stable).

## Central Inconsistency (re-verified 2026-07-18)

The structured-output path at
[`basic_openai_provider.py:611-615`](../../lib/ai/providers/basic_openai_provider.py)
(`_generateStructured`) already treats empty content as a hard error:

```python
if outcome.status in (ModelResultStatus.FINAL, ModelResultStatus.TRUNCATED_FINAL):
    ...
    if not outcome.resText:
        raise ValueError("Structured output: model returned empty content")
```

The text-output path at
[`basic_openai_provider.py:515-523`](../../lib/ai/providers/basic_openai_provider.py)
(`_generateText`'s `return ModelRunResult(resultText=outcome.resText, ...)`)
has no equivalent check — empty `resultText` passes through silently. Any fix
should make the two paths consistent in their treatment of empty content
(whether by downgrade, raise, or explicit fallback).

## Already Implemented

### Item 1 — observability-only WARNING dump (SHIPPED, commit `bd9025a`, 2026-07-05)

Present in `BasicOpenAIModel._executeChatCompletion`
([`basic_openai_provider.py`](../../lib/ai/providers/basic_openai_provider.py),
trigger at lines ~374-382, dump at lines ~411-423). Fires when the API call
succeeded but produced no usable text on a status that should have content:

```python
if (
    status in (
        ModelResultStatus.TRUNCATED_FINAL,
        ModelResultStatus.CONTENT_FILTER,
        ModelResultStatus.UNKNOWN,
    )
    and not resText.strip()
):
    ...
    logger.warning(f"Anomalous empty LLM response from {self.provider}/{self.modelId}: ...")
```

The dump includes `finishReason`, `status`, `resText`, `inputTokens`,
`outputTokens`, `totalTokens`, `completion_tokens_details` (exposes
`reasoning_tokens`, the key signal for the budget-exhaustion hypothesis),
`prompt_tokens_details`, and the full `response.model_dump_json(indent=2)`
(with a `str()` fallback for non-pydantic vendors).

Scope is strictly observability: `status`, `resText`, and the returned
`_OpenAICallOutcome` are NOT modified, so the empty content still flows
through every downstream layer unchanged. This change makes the bug
diagnosable but does NOT fix it on the provider path — Option A is still
required there. The handler path is now covered separately (see Item 2).

Note: this diagnostic exists only in the OpenAI-compatible provider. The YC SDK
provider ([`yc_sdk_provider.py`](../../lib/ai/providers/yc_sdk_provider.py),
~line 487) has no equivalent, so empty content from that provider remains
silent.

### Item 2 — handler-level empty-text guard, Option B handler-half (SHIPPED, commit `7e2b5501`, 2026-07-05)

A guard now exists in `_sendLLMChatMessage`
([`llm_messages.py:394`](../../internal/bot/common/handlers/llm_messages.py)):

```python
if imagePrompt is None and lmRetText.strip().strip("`").strip() in ("<skip>", ""):
    logger.debug("Model abstained (<skip>) or returned empty, not sending a reply")
    return LLMReplyOutcome.SKIPPED_BY_MODEL
```

The `""` clause is the empty-`TRUNCATED_FINAL` mitigation. The inline comment
at lines 379-393 explicitly references the reasoning-budget-exhaustion case
and documents the silent-drop UX as intentional. Runs BEFORE the image-gen
branch (so a tag-only `<media-description>` request that legitimately leaves
`lmRetText=""` does NOT trip it — `imagePrompt is None` gates it out). This
is the handler-level half of Option B; the `bot.py` empty-string safety net
(Option B's other half) is still pending.

The shipped version uses the silent-drop UX (variant (b) from the original
"Open Decisions" #1 list): debug-level log, no user-visible fallback message,
no WARNING. Decision #1 is therefore resolved by implementation choice — no
fallback notice is sent.

### Item 3 — service-layer post-budget synthesizer, SIBLING MITIGATION (SHIPPED, commit `10e99c3`, 2026-07-16)

NOT a fix for this bug — covers a different failure mode (round-budget
exhaustion in the tool-call loop, not single-shot reasoning-budget
exhaustion). Documented here because it sits on the same call path and
callers may conflate the two.

In `generateTextViaLLM`
([`service.py:926-951`](../../internal/services/llm/service.py)), when the
tool-call round cap is hit, sets `ret.roundLimitHit = True`, logs a WARNING,
and synthesizes a fallback answer:

```python
if budgetExhausted:
    ret.roundLimitHit = True
    logger.warning(f"generateTextViaLLM hit maxRounds cap ({maxRounds}) for callId #{callId}; forcing termination")
    if not ret.resultText and ret.status in (ModelResultStatus.FINAL, ModelResultStatus.TOOL_CALLS):
        ret.resultText = ("I've reached the limit of tool-use steps for this request; "
                          "here is my best answer with the information gathered so far.")
        ret.status = ModelResultStatus.FINAL
        ret.toolCalls = []
```

Status guard is `ret.status in (FINAL, TOOL_CALLS)`, so empty
`TRUNCATED_FINAL` is **explicitly excluded** — the original bug (single-shot
empty `TRUNCATED_FINAL` from a no-tools call) propagates through this code
untouched. Genuine error statuses (`ERROR` / `CONTENT_FILTER` / `UNKNOWN`)
also propagate untouched by design.

## Options

### Option A — Provider-side empty-output downgrade (RECOMMENDED for next pass)

- Location: [`lib/ai/providers/basic_openai_provider.py`](../../lib/ai/providers/basic_openai_provider.py),
  `_generateText` text-path return around lines 515-523 (re-locate by symbol).
- Mechanism: if `outcome.status in (FINAL, TRUNCATED_FINAL)` and
  `not outcome.resText.strip()`, downgrade `status` to `ERROR` with an
  explanatory `error`. The existing `_runWithFallback` then naturally tries the
  fallback model.
- Pros: smallest change; mirrors the existing structured-output guard
  (lines 611-615 in `_generateStructured`); reuses the existing fallback
  machinery; no abstract-layer semantic change.
- Cons: provider-specific — would need to be repeated in
  [`lib/ai/providers/yc_sdk_provider.py`](../../lib/ai/providers/yc_sdk_provider.py),
  which at line 487 returns `result.alternatives[0].text` with no emptiness
  check.
- Risks: if a model legitimately returns empty content as a valid response
  (rare for chat), this forces an unnecessary fallback. Mitigation: limit the
  downgrade to `TRUNCATED_FINAL` / `UNKNOWN` / `CONTENT_FILTER`, not bare
  `FINAL`.
- Complexity: ~5 lines per provider.

### Option B — Graceful bot-side fallback (handler-half SHIPPED; bot.py-half PENDING)

- Handler location (DONE): [`internal/bot/common/handlers/llm_messages.py:394`](../../internal/bot/common/handlers/llm_messages.py).
  The shipped guard treats bare-empty `lmRetText` as `LLMReplyOutcome.SKIPPED_BY_MODEL`
  (silent-drop UX, debug-level log). Implemented in commit `7e2b5501`; see
  "Already Implemented" Item 2.
- `bot.py` location (PENDING): tighten
  [`internal/bot/common/bot.py:668-670`](../../internal/bot/common/bot.py) so the
  guard rejects the empty-string `messageText` the same way it rejects `None` —
  a pure safety net for any `sendMessage` caller that bypasses the handler
  guard (other handlers, future code paths).
- Open Decision #1 (UX choice) was resolved by the shipped handler guard: it
  uses variant (b) silent-drop + warn-log. If a per-chat configurable message
  is later wanted, that becomes a follow-up enhancement, not a re-decision.
- Pros: defense in depth; correct UX even when both primary and fallback models
  fail; the `bot.py` guard prevents the `BadRequest` from ever reaching the API
  again from non-LLM-reply callers.
- Cons: the silent-drop variant could hide future regressions (mitigate with a
  WARNING log — currently only debug-level).
- Risks: minimal.
- Complexity: ~2 lines for the `bot.py` half (handler half is done).

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

1. Option A — provider-side empty-output downgrade in `_generateText`
   (Observability / Item 1 is already done — see "Already Implemented" — so
   the reasoning-budget hypothesis can be confirmed from logs before this
   change lands.)
2. Option B `bot.py` half — tighten `_sendTelegramMessage` to reject the
   empty-string `messageText` (the handler-half of Option B already shipped —
   see "Already Implemented" Item 2).
3. Regression tests per the Test Plan below — including the missing test for
   the already-shipped handler-half (AGENTS.md violation; see Test Plan note).

Options C, D, and E are deferred.

## Open Decisions (require user input)

1. ~~Bot-side empty-response UX: (a) send a fallback notice, (b) silent drop +
   warn-log, (c) per-chat configurable message.~~ **RESOLVED by
   implementation** (commit `7e2b5501`) — the shipped handler guard uses
   variant (b) silent-drop + debug-level log. If (a) or (c) is later wanted,
   it becomes a follow-up enhancement on top of the shipped guard.
2. Should the provider-side downgrade (Option A) also cover bare `FINAL` with
   empty text, or only `TRUNCATED_FINAL` / `UNKNOWN` / `CONTENT_FILTER`?
3. Whether to extend Option A to
   [`lib/ai/providers/yc_sdk_provider.py`](../../lib/ai/providers/yc_sdk_provider.py)
   in the same pass (the YC provider has no emptiness check at line 487).

## Test Plan (for next pass)

**AGENTS.md violation against the shipped handler-half** (rule: "Regression
tests on every bug fix"): commit `7e2b5501` shipped the handler-level empty-text
guard (Option B handler-half) AND added
[`tests/bot/common/handlers/test_llm_messages.py::TestRandomAnswerPromptAndSkipSentinel`](../../tests/bot/common/handlers/test_llm_messages.py),
but those tests assert `LLMReplyOutcome.SKIPPED_BY_MODEL` only on the `<skip>`
sentinel (plain and JSON-wrapped) — NOT on the bare-empty `""` branch of the
same `in ("<skip>", "")` check. The empty-text branch is therefore uncovered
by a passing test today. Test 3 below must be added to close the gap.

Tests:

- Test 1 (PENDING, Option A): provider downgrades empty `TRUNCATED_FINAL` to
  `ERROR`. Not implemented — Option A is unshipped.
- Test 2 (PENDING, Option A): fallback fires on the downgraded result. Not
  implemented — Option A is unshipped.
- Test 3 (PENDING — regression for shipped handler-half): bot-side guard
  catches empty `resultText` even when status is `FINAL`. The handler-half
  shipped (commit `7e2b5501`) but no test feeds `_modelRunResult("")` directly
  to assert the `SKIPPED_BY_MODEL` outcome; existing tests cover only
  `<skip>` and the JSON-wrapped `<skip>` variant. Must be added.
- Test 4 (PENDING, Option B bot.py half): `_sendTelegramMessage` rejects
  empty-string `messageText`. Not implemented — bot.py tightening is unshipped.
- Test 5 (PENDING, Option A): no-regression — a legitimate tool-call-only turn
  (empty `resultText`, populated `toolCalls`) is NOT downgraded. Not
  implemented — Option A is unshipped.

## References

- [`lib/ai/abstract.py`](../../lib/ai/abstract.py) — model run loop, fallback orchestrator
- [`lib/ai/models.py`](../../lib/ai/models.py) — `ModelResultStatus`, `ERROR_STATUSES`, `ModelRunResult`
- [`lib/ai/providers/basic_openai_provider.py`](../../lib/ai/providers/basic_openai_provider.py) — OpenAI-compatible provider
- [`lib/ai/providers/yc_sdk_provider.py`](../../lib/ai/providers/yc_sdk_provider.py) — YC SDK provider (no emptiness check)
- [`internal/services/llm/service.py`](../../internal/services/llm/service.py) — `LLMService.generateTextViaLLM`
- [`internal/bot/common/handlers/llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py) — `_sendLLMChatMessage`
- [`internal/bot/common/bot.py`](../../internal/bot/common/bot.py) — `_sendTelegramMessage`
- [`tests/bot/common/handlers/test_llm_messages.py`](../../tests/bot/common/handlers/test_llm_messages.py) — handler tests including `TestRandomAnswerPromptAndSkipSentinel` (covers `<skip>`; missing bare-empty branch — see Test Plan)
- [`../llm/memories/llm-empty-truncated-final.md`](../llm/memories/llm-empty-truncated-final.md) — companion durable memory (re-verified 2026-07-18; canonical post-implementation status)

Commits:
- `bd9025a` — Item 1 observability WARNING dump (2026-07-05).
- `7e2b5501` — Option B handler-half: empty-text abstention guard at `llm_messages.py:394` + `<skip>` tests (2026-07-05).
- `10e99c3` — sibling mitigation: post-budget synthesizer at `service.py:926-951` (2026-07-16); explicitly excludes `TRUNCATED_FINAL`.
