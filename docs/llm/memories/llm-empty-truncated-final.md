# Empty TRUNCATED_FINAL LLM Bug

Durable notes on the recurring production failure where an OpenAI-compatible API returns `finish_reason="length"` with empty `message.content`. Suspected root cause: reasoning-token budget exhaustion on Qwen3-class models — failing logs show `outputTokens=32768` matching `max_tokens`. The empty content flows unchecked through every layer (provider → abstract fallback → service → handler → bot send path) and reaches python-telegram-bot as `send_message(text="")`, raising `telegram.BadRequest: Message text is empty`. Item 1 (observability-only WARNING dump) shipped 2026-07-05 in the OpenAI-compatible provider. A partial behavior fix landed the same day: the LLM-message handler now treats bare-empty `resultText` as `SKIPPED_BY_MODEL` (`llm_messages.py:394`, silent-drop variant of plan Option B). The remainder of the plan — provider-side downgrade (Option A), the `bot.py` empty-string safety net (Option B's second half), and the regression tests from the plan's Test Plan — is still pending.

## Bug summary

OpenAI-compatible API returns `finish_reason="length"` with empty `message.content`. Suspected driver: reasoning-token budget exhaustion on Qwen3-class models — failing logs show `outputTokens=32768` matching `max_tokens`, with zero visible content. Empty content flows unchecked through every layer (provider → abstract fallback → service → handler → bot send path) → `send_message(text="")` → `telegram.BadRequest: Message text is empty`. The `"Message text is empty"` string does NOT exist in the repo — it is python-telegram-bot's `BadRequest` message text.

## Plan

[`/docs/plans/llm-empty-truncated-final-handling-v1.md`](/docs/plans/llm-empty-truncated-final-handling-v1.md) — Options A–E. Recommended next: Option A (provider-side empty-output downgrade) + Option B (graceful bot-side fallback + tightened `bot.py` empty-string guard). Options C/D/E deferred.

## Durable code-path facts

Verified 2026-07-05; re-verified 2026-07-18; line numbers are approximate — re-locate by symbol when editing.

- [`/lib/ai/models.py`](/lib/ai/models.py) `ModelResultStatus`: NO bare `TRUNCATED`, NO `SUCCESS`. "Success" is named `FINAL = 3`. `TRUNCATED_FINAL = 2`.
- [`/lib/ai/models.py`](/lib/ai/models.py) `ERROR_STATUSES` frozenset does NOT include `TRUNCATED_FINAL` or `PARTIAL` → both treated as success by `_runWithFallback` ([`/lib/ai/abstract.py`](/lib/ai/abstract.py)).
- [`/lib/ai/providers/basic_openai_provider.py`](/lib/ai/providers/basic_openai_provider.py) `_executeChatCompletion`: `finish_reason="length"` → `TRUNCATED_FINAL`; `resText = retMessage.content if retMessage.content else ""`. The STRUCTURED path (`_generateStructured`) has `if not outcome.resText: raise ValueError(...)` — the TEXT path (`_generateText`) does NOT. Central inconsistency.
- [`/lib/ai/abstract.py`](/lib/ai/abstract.py) `printJSONLog` skips empty results (`if not result.resultText: return`) — so file JSON log also misses this case.
- [`/internal/services/llm/service.py`](/internal/services/llm/service.py) `generateTextViaLLM`: the loop special-cases `FINAL` (line ~858) and `TOOL_CALLS` (line ~870); `TRUNCATED_FINAL` still falls through to `break` (line ~952). Sibling mitigation (commit `10e99c3`, post-round-budget synthesizer at lines ~926-951) substitutes a fallback answer for empty `FINAL` / post-budget `TOOL_CALLS` — but **explicitly excludes `TRUNCATED_FINAL`** (the synthesizer's status guard is `ret.status in (FINAL, TOOL_CALLS)`), so empty `TRUNCATED_FINAL` from a single-shot (no-tools) call still propagates untouched. Genuine error statuses (`ERROR` / `CONTENT_FILTER` / `UNKNOWN`) also propagate untouched by design.
- [`/internal/bot/common/handlers/llm_messages.py`](/internal/bot/common/handlers/llm_messages.py): `lmRetText = mlRet.resultText.strip()` at line ~326. **A guard now exists** at line ~394 (commit `7e2b5501`, 2026-07-05): `if imagePrompt is None and lmRetText.strip().strip("\`").strip() in ("<skip>", ""): return LLMReplyOutcome.SKIPPED_BY_MODEL`. The `""` clause is explicitly documented in the inline comment as the empty-TRUNCATED_FINAL mitigation (silent-drop UX; debug-level log, no user-visible message, no WARNING). This is the handler-level portion of plan Option B; the `bot.py` safety-net half of Option B is still missing.
- [`/internal/bot/common/bot.py`](/internal/bot/common/bot.py) `_sendTelegramMessage`: guard at line ~668 rejects `None` text only (`if photoData is None and messageText is None and attachmentList is None:`), NOT empty string `""`. The handler-level `SKIPPED_BY_MODEL` guard above prevents the empty string from ever reaching here in the normal LLM-reply path, but other callers of `sendMessage` are still exposed — the `bot.py` tightening called for in plan Option B is still pending.
- The `"Message text is empty"` string does NOT exist in repo — it's python-telegram-bot's `BadRequest` message text.
- YC SDK provider ([`/lib/ai/providers/yc_sdk_provider.py`](/lib/ai/providers/yc_sdk_provider.py), ~line 487) returns `result.alternatives[0].text` with no emptiness check — same hazard.

## Item 1 — observability-only WARNING dump (IMPLEMENTED 2026-07-05)

Observability-only WARNING dump added in `BasicOpenAIModel._executeChatCompletion` ([`/lib/ai/providers/basic_openai_provider.py`](/lib/ai/providers/basic_openai_provider.py)). Trigger: `not resText.strip() and status in (TRUNCATED_FINAL, CONTENT_FILTER, UNKNOWN)`. The dump includes `finishReason`, `status`, `resText`, token counts (`inputTokens` / `outputTokens` / `totalTokens`), `completion_tokens_details` (exposes `reasoning_tokens` — the diagnostic for the budget-exhaustion hypothesis), `prompt_tokens_details`, and the full `response.model_dump_json(indent=2)`. All vendor-object serialization is wrapped in try/except with a `str()` fallback, so the observability probe can never mask the original outcome. No behavior change — `status`, `resText`, and the returned `_OpenAICallOutcome` are unmodified; empty `TRUNCATED_FINAL` still flows downstream. The fix is Options A+B in the plan. Note: this diagnostic exists only in the OpenAI-compatible provider; the YC SDK provider has no equivalent, so empty content from it remains silent.

## Sibling mitigations landed after Item 1

Two related-but-distinct safety nets shipped after Item 1; **neither covers the original empty-TRUNCATED_FINAL bug surface**, so the plan is still relevant:

- Handler-level empty-string guard ([`/internal/bot/common/handlers/llm_messages.py`](/internal/bot/common/handlers/llm_messages.py) ~line 394, commit `7e2b5501`, 2026-07-05) — treats bare-empty `resultText` (after `<skip>` and image-prompt checks) as `LLMReplyOutcome.SKIPPED_BY_MODEL`. Silent-drop UX (debug-level log, no user-visible fallback message). This is the handler half of plan Option B; the `bot.py` empty-string safety net (Option B's other half) is still missing.
- Service-layer post-budget synthesizer ([`/internal/services/llm/service.py`](/internal/services/llm/service.py) ~lines 926-951, commit `10e99c3`) — when the tool-call round budget is exhausted, substitutes a fallback answer for empty `FINAL` / post-budget `TOOL_CALLS` and sets `roundLimitHit = True`. **Status guard is `ret.status in (FINAL, TOOL_CALLS)`, so empty `TRUNCATED_FINAL` is excluded**; genuine error statuses also propagate untouched. Covers a different failure mode (round-cap hit) than the original bug (single-shot reasoning-budget exhaustion).

Open follow-ups against the plan: Option A (provider downgrade in `basic_openai_provider.py._generateText` and the YC SDK provider), the `bot.py` empty-string guard, and all of the plan's Test Plan regressions (no regression tests for the empty-output path exist yet — `tests/services/llm/test_llm_service.py` and `tests/lib/ai/providers/test_basic_openai_provider.py` exercise `TRUNCATED_FINAL` only with populated content).

## Cross-references

- Plan: [`/docs/plans/llm-empty-truncated-final-handling-v1.md`](/docs/plans/llm-empty-truncated-final-handling-v1.md)
- [`/lib/ai/models.py`](/lib/ai/models.py) — `ModelResultStatus`, `ERROR_STATUSES`, `ModelRunResult`
- [`/lib/ai/abstract.py`](/lib/ai/abstract.py) — `_runWithFallback`, `printJSONLog`
- [`/lib/ai/providers/basic_openai_provider.py`](/lib/ai/providers/basic_openai_provider.py) — `_executeChatCompletion`, `_generateText`, `_generateStructured`
- [`/lib/ai/providers/yc_sdk_provider.py`](/lib/ai/providers/yc_sdk_provider.py) — YC SDK provider (no emptiness check)
- [`/internal/services/llm/service.py`](/internal/services/llm/service.py) — `generateTextViaLLM`
- [`/internal/bot/common/handlers/llm_messages.py`](/internal/bot/common/handlers/llm_messages.py) — `_sendLLMChatMessage`
- [`/internal/bot/common/bot.py`](/internal/bot/common/bot.py) — `_sendTelegramMessage`
