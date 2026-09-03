# Design: consumerId gaps in llm_request stats — issue parking lot

**Status: IMPLEMENTED (2026-08-23).** Originally a DRAFT issue parking lot
documenting places where stats events were recorded WITHOUT the proper chat
consumerId. All three gaps are now fixed; see [Resolution](#resolution) below.
The gap descriptions are kept as the historical record — file:line citations
refer to the pre-fix code (verified 2026-08-18).

## Resolution

`chatId` on `LLMService` generation methods is now a **mandatory `int`**, and
the "skip rate limiting" escape hatch moved to a dedicated keyword-only
`doRateLimit: bool = True` flag, decoupling rate-limit skipping from stats
attribution:

- `generateText` / `generateStructured` / `generateImage` / `generateEmbedding`
  / `generateTextViaLLM` all take `chatId: int` + `doRateLimit` and always
  thread `consumerId=str(chatId)` into the model call.
- **Gap 1 (embeddings):** `generateEmbedding` passes
  `consumerId=str(chatId)` to `AbstractModel.generateEmbeddings`.
- **Gap 2 (background callers):** `chat_search.embedAndSaveMessage` and the
  `user_memories` background refinement now pass the real chat id with
  `doRateLimit=False` — the limiter is skipped, attribution is kept.
- **Gap 3 (condensing):** `condenseContext` accepts keyword-only
  `consumerId: Optional[str]` (stats-only; the condensing path never
  rate-limits) and threads it into `condensingModel.generateText`.
  `generateTextViaLLM` passes `consumerId=str(chatId)` for every per-round
  condense.

Regression tests: `TestConsumerIdAttribution` in
[`tests/services/llm/test_llm_service.py`](../../tests/services/llm/test_llm_service.py),
plus handler-level assertions in `TestEmbedAndSaveMessage`
(`tests/bot/common/handlers/test_chat_search.py`) and
`TestCronJobAndRefinement` (`tests/bot/common/handlers/test_user_memories.py`).

## Context

`consumerId` (= chat id) is how per-chat stats scoping works: it is merged into
`labels["consumer"]` at
[lib/stats/sql_storage.py:112](../../lib/stats/sql_storage.py)
(`None` → `__global__`). The `message`, `command`, and `llm_tool_call` event types
carry it correctly. All known gaps are in `llm_request`.

## Gap 1 — Embeddings omit consumerId entirely

- `generateEmbeddings` accepts a `consumerId` parameter
  ([lib/ai/abstract.py:503-509](../../lib/ai/abstract.py), param at :508), but the
  service call site does not pass it
  ([internal/services/llm/service.py:1499](../../internal/services/llm/service.py) —
  `chatId` is used there only for rate limiting at :1497-1498, then dropped).
- Effect: ALL embedding requests land under `__global__` regardless of chat →
  per-chat LLM views undercount.

## Gap 2 — Background callers pass chatId=None

- Chat-search background embedding:
  [internal/bot/common/handlers/chat_search.py:552-556](../../internal/bot/common/handlers/chat_search.py)
  calls `LLMService.generateEmbedding(..., chatId=None, ...)` (deliberate — skips the
  per-chat hot-path rate budget, per the docstring at :532-534).
- Background memory refinement:
  [internal/bot/common/handlers/user_memories.py:1296-1301](../../internal/bot/common/handlers/user_memories.py)
  calls `generateTextViaLLM(..., chatId=None, ...)` — and this call site KNOWS the
  chat id (in scope since :1271); it passes `None` only to skip rate limiting
  (comment at :1301).
- Effect: those `llm_request` rows lose chat attribution. Contrast: the
  `llm_tool_call` events from the SAME user_memories background call DO get correct
  chat attribution, via the synthetic ensuredMessage's `recipient.id`
  (built at :1271, passed as `extraData["ensuredMessage"]` at :1314).

## Gap 3 — Context-condensing bypasses the consumerId-threading wrapper

- [internal/services/llm/service.py:1239](../../internal/services/llm/service.py)
  calls the condensing path (`condensingModel.generateText(reqMessages)`) with no
  `consumerId`, outside the wrapper layer that threads it. The wrappers that DO
  thread it: `generateText` at :1316-1321, `generateStructured` at :1409-1416,
  `generateImage` at :1457-1461.
- Effect: condense requests unattributed (`__global__`).

## Verified-correct (for contrast)

- STT passes consumerId:
  [internal/services/stt/service.py:311-314](../../internal/services/stt/service.py)
  (`consumerId=str(chatId) if chatId is not None else None`).
- Interactive text / structured / image generation thread it (see wrapper sites
  above).

## Impact summary

Per-chat `llm_request` sections undercount (embeddings, background generation,
condensing land in `__global__`); global totals unaffected. Registered as risk R3
with follow-up O2 in [stats-display-v1.md](stats-display-v1.md) §8/§9; the
per-event-type detail is in its §2.3.

## Fix directions (historical — executed per the Resolution above)

The "accept `__global__` for system-initiated work" alternative was rejected:
`llm_tool_call` events from the same background refinement call were already
correctly attributed via the synthetic ensuredMessage, and consistency within
one logical operation matters more. The implemented bullets:

- Thread `consumerId` at the embeddings call site (`generateEmbedding` in
  `LLMService` already has `chatId`; pass it through).
- Route condensing through the consumerId-threading wrapper (or pass `consumerId`
  at the :1239 call site).
- For background callers, decide policy per call site:
  - pass the real chat id where known (user_memories refinement knows it — the
    `chatId` param is used to build the synthetic ensuredMessage at :1271);
  - or accept `__global__` for system-initiated work as a deliberate semantic
    (requires decoupling "rate-limit skip" from "attribution" — today the same
    `chatId=None` flag does both).

## Related

- [stats-display-v1.md](stats-display-v1.md) §2.3 — the original consumerId
  verification pass; §8 R3 / §9 O2 — risk + follow-up.
- [stats-collecting-v1.md](stats-collecting-v1.md) — collection-side contracts.
- [stats-display-v2-draft.md](stats-display-v2-draft.md) — per-chat-per-model views
  inherit these gaps.
