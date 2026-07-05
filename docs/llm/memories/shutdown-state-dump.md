# Shutdown State Dump

Durable notes from the shutdown diagnostics dump implementation (2026-07-04). Read this when working on `HandlersManager` shutdown logic or rate limiter statistics.

- **HandlersManager** (`internal/bot/common/handlers/manager.py`) emits shutdown diagnostics via `_dumpAllState()` — a **parameterless** method with a **single call site**: `shutdown()` awaits it directly after `_shutdownEvent.set()` and before per-chat queues are drained. No DO_EXIT registration, no `_stateDumped` idempotency guard — both were removed once the design collapsed to one caller.
- `_dumpAllState()` does two things **inline** (no separate `_dumpChatStates` helper):
  1. **Per-chat queue state** — snapshots `chatStates.values()` under `stateLock`, inspects each chat's queue under its own per-chat lock, skips empty queues, and logs `chat_id=%d.%s pending_messages=%d` (the `%s` is `threadId`, so `None` renders as literal `"None"`) for non-empty ones. Per-chat errors isolated via try/except + `logger.warning(..., exc_info=True)`.
  2. **Rate limiter state** — calls `RateLimiterManager.getInstance().dumpAllStats()`, then logs each returned entry via `logger.info(utils.jsonDumps(entry, indent=2))`.
- **RateLimiterManager.dumpAllStats()** (`lib/rate_limiter/manager.py`): sync method, returns `List[RateLimiterStatsEntry]` (a TypedDict with `limiter`, `queue`, `requestsInWindow`, `maxRequests`, `windowSeconds`, `utilizationPercent`). Does NOT log — caller logs. Per-queue try/except isolation.
- **RateLimiterStatsEntry** TypedDict defined in `lib/rate_limiter/manager.py` — no `Any` in the return type.
- **Tests**: `tests/lib/rate_limiter/test_manager.py` (4 `dumpAllStats` tests: multi-limiter/queue, empty registry, per-queue getStats failure, empty-queues), `tests/bot/common/handlers/test_manager.py` (6 tests: 3 chat-state queue logging + 2 combined `_dumpAllState` + 1 `shutdown()` calls `_dumpAllState` before draining). No idempotency test exists — there is no guard to test.
- **Docs updated**: `lib/rate_limiter/README.md`, `docs/llm/services.md`, `docs/llm/handlers.md`.
- **ChatProcessingState key attrs**: `queue: deque[MessageQueueRecord]`, `chatId: int`, `threadId: Optional[int]`, `lock: asyncio.Lock`, `shutdownEvent: asyncio.Event`. No callback queue — callbacks are fire-and-forget tasks in `handlerTasks`.
