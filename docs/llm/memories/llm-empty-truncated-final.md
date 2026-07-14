# Empty TRUNCATED_FINAL LLM Bug

Durable notes on the recurring production failure where an OpenAI-compatible API returns `finish_reason="length"` with empty `message.content`. Suspected root cause: reasoning-token budget exhaustion on Qwen3-class models — failing logs show `outputTokens=32768` matching `max_tokens`. The empty content flows unchecked through every layer (provider → abstract fallback → service → handler → bot send path) and reaches python-telegram-bot as `send_message(text="")`, raising `telegram.BadRequest: Message text is empty`. Item 1 (observability-only WARNING dump) shipped 2026-07-05 in the OpenAI-compatible provider; the behavior fix (Options A+B in the plan) is still pending.

## Bug summary

OpenAI-compatible API returns `finish_reason="length"` with empty `message.content`. Suspected driver: reasoning-token budget exhaustion on Qwen3-class models — failing logs show `outputTokens=32768` matching `max_tokens`, with zero visible content. Empty content flows unchecked through every layer (provider → abstract fallback → service → handler → bot send path) → `send_message(text="")` → `telegram.BadRequest: Message text is empty`. The `"Message text is empty"` string does NOT exist in the repo — it is python-telegram-bot's `BadRequest` message text.

## Plan

[`/docs/plans/llm-empty-truncated-final-handling-v1.md`](/docs/plans/llm-empty-truncated-final-handling-v1.md) — Options A–E. Recommended next: Option A (provider-side empty-output downgrade) + Option B (graceful bot-side fallback + tightened `bot.py` empty-string guard). Options C/D/E deferred.

## Durable code-path facts

Verified 2026-07-05; line numbers are approximate — re-locate by symbol when editing.

- [`/lib/ai/models.py`](/lib/ai/models.py) `ModelResultStatus`: NO bare `TRUNCATED`, NO `SUCCESS`. "Success" is named `FINAL = 3`. `TRUNCATED_FINAL = 2`.
- [`/lib/ai/models.py`](/lib/ai/models.py) `ERROR_STATUSES` frozenset does NOT include `TRUNCATED_FINAL` or `PARTIAL` → both treated as success by `_runWithFallback` ([`/lib/ai/abstract.py`](/lib/ai/abstract.py)).
- [`/lib/ai/providers/basic_openai_provider.py`](/lib/ai/providers/basic_openai_provider.py) `_executeChatCompletion`: `finish_reason="length"` → `TRUNCATED_FINAL`; `resText = retMessage.content if retMessage.content else ""`. The STRUCTURED path (`_generateStructured`) has `if not outcome.resText: raise ValueError(...)` — the TEXT path (`_generateText`) does NOT. Central inconsistency.
- [`/lib/ai/abstract.py`](/lib/ai/abstract.py) `printJSONLog` skips empty results (`if not result.resultText: return`) — so file JSON log also misses this case.
- [`/internal/services/llm/service.py`](/internal/services/llm/service.py) `generateTextViaLLM`: only special-cases `FINAL` and `TOOL_CALLS`; `TRUNCATED_FINAL` falls through to `break`.
- [`/internal/bot/common/handlers/llm_messages.py`](/internal/bot/common/handlers/llm_messages.py): `lmRetText = mlRet.resultText.strip()` → no guard before `sendMessage`.
- [`/internal/bot/common/bot.py`](/internal/bot/common/bot.py) `_sendTelegramMessage`: guard rejects `None` text only, NOT empty string `""`.
- The `"Message text is empty"` string does NOT exist in repo — it's python-telegram-bot's `BadRequest` message text.
- YC SDK provider ([`/lib/ai/providers/yc_sdk_provider.py`](/lib/ai/providers/yc_sdk_provider.py), ~line 487) returns `result.alternatives[0].text` with no emptiness check — same hazard.

## Item 1 — observability-only WARNING dump (IMPLEMENTED 2026-07-05)

Observability-only WARNING dump added in `BasicOpenAIModel._executeChatCompletion` ([`/lib/ai/providers/basic_openai_provider.py`](/lib/ai/providers/basic_openai_provider.py)). Trigger: `not resText.strip() and status in (TRUNCATED_FINAL, CONTENT_FILTER, UNKNOWN)`. The dump includes `finishReason`, `status`, `resText`, token counts (`inputTokens` / `outputTokens` / `totalTokens`), `completion_tokens_details` (exposes `reasoning_tokens` — the diagnostic for the budget-exhaustion hypothesis), `prompt_tokens_details`, and the full `response.model_dump_json(indent=2)`. All vendor-object serialization is wrapped in try/except with a `str()` fallback, so the observability probe can never mask the original outcome. No behavior change — `status`, `resText`, and the returned `_OpenAICallOutcome` are unmodified; empty `TRUNCATED_FINAL` still flows downstream. The fix is Options A+B in the plan. Note: this diagnostic exists only in the OpenAI-compatible provider; the YC SDK provider has no equivalent, so empty content from it remains silent.

## Cross-references

- Plan: [`/docs/plans/llm-empty-truncated-final-handling-v1.md`](/docs/plans/llm-empty-truncated-final-handling-v1.md)
- [`/lib/ai/models.py`](/lib/ai/models.py) — `ModelResultStatus`, `ERROR_STATUSES`, `ModelRunResult`
- [`/lib/ai/abstract.py`](/lib/ai/abstract.py) — `_runWithFallback`, `printJSONLog`
- [`/lib/ai/providers/basic_openai_provider.py`](/lib/ai/providers/basic_openai_provider.py) — `_executeChatCompletion`, `_generateText`, `_generateStructured`
- [`/lib/ai/providers/yc_sdk_provider.py`](/lib/ai/providers/yc_sdk_provider.py) — YC SDK provider (no emptiness check)
- [`/internal/services/llm/service.py`](/internal/services/llm/service.py) — `generateTextViaLLM`
- [`/internal/bot/common/handlers/llm_messages.py`](/internal/bot/common/handlers/llm_messages.py) — `_sendLLMChatMessage`
- [`/internal/bot/common/bot.py`](/internal/bot/common/bot.py) — `_sendTelegramMessage`
