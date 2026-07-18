# Test Suite Performance Profile & Speedup (2026-07-12)

Archived durable notes from [`../teamlead-memory.md`](../teamlead-memory.md) (extracted 2026-07-18). See the live compact memory there for cross-cutting rules and workflow lessons.

## Test Suite Performance Profile (2026-07-12, measured)

Profiled run: **3202 tests, ~107s wall-clock** (Python 3.14.6 venv, macOS arm64). Setup only 7s; the rest is `call`. Dominant finding: **~68% of wall-clock is real `time.sleep`/`asyncio.sleep` blocking in tests**, not CPU or DB.

- **Top 3 slowest test FILES = 54% of wall-clock:** `tests/lib/utils/ttl_dict_test.py` (24.5s/12 items), `tests/lib/rate_limiter/test_sliding_window.py` (21.1s/9), `tests/lib/rate_limiter/test_integration.py` (12.0s/7). All ~2.0s/test due to real sleeps waiting on TTL/window expiry.
- **Single slowest test:** `test_sliding_window.py::testLargeNumberOfRequests` (6.0s) — production `sliding_window.py:208` does `await asyncio.sleep(waitTime)` inside `applyLimit`; unmocked.
- **Cron backfill test:** `test_chat_search.py::test_cron_self_reset_does_not_fire_on_full_batch` (5.0s) — `ChatSearchHandler._dtCronJob` sleeps `BACKFILL_INTER_MESSAGE_DELAY_SECS` (0.1s, `constants.py:251`) per msg × `BACKFILL_DEFAULT_BATCH_SIZE` (50, `constants.py:243`) = 5.0s real sleep. The sibling `test_user_memories_memory_regen.py:676` DOES mock `asyncio.sleep` correctly — the inconsistency is the bug.
- **Marker system is mis-targeted (0% savings today):** `slow`=15 (Docker integration + bayes performance — NOT actually slow); `performance`/`benchmark`/`memory`/`stress`/`profile` = 0 tests each. The genuinely slow tests carry NO marker. `-m "not slow and not ..."` saves 0s.
- **Already optimal:** in-memory SQLite in use; LLM/embedding providers already mocked in handler tests.

---

## Test Speedup IMPLEMENTED (2026-07-12): A+B applied, result 107s → 38.17s (−64.3%)

User decisions: production sleeps are intentional (rate-limiting) → ALL changes test-side only; ALL tests always run (no skipping/markers — "if skipped, nobody runs them"); xdist deferred.

**Outcome:** full suite 3210 passed / 0 failed / 11 skipped in **38.17s** (was ~107s). None of the previously-slow targets remain in the top-20; new ceiling ~1s/test, all genuine work (bayes algo, real SQLite I/O, migration setup). Touched 10 test files (8 modified + 2 new local conftest), 0 production files.

**Per-area before→after:** ttl_dict 25.2s→0.6s; rate_limiter (3 files) 36.6s→0.7s; cache 5.8s→1.0s; chat_search 6.4s→1.0s (the 5s cron test→<5ms); resender 2.9s→0.8s.

**Two reusable patterns (durable):**
1. **Fake clock** for *timing-assertion* tests (assert on expiry/ordering/concurrency): patch `time.time`/`time.sleep` (and `asyncio.sleep` where production blocks via it). Real waits become clock advances. Use `time.perf_counter()` (NOT patched) for any REAL performance-duration measurement inside a faked test — `time.time()` deltas freeze to 0 under the patch (this was a real Gate-2 finding in `test_dict_cache.py::test_cleanup_performance`).
2. **No-op asyncio.sleep** for *pacing* tests (sleep is inter-message delay, NOT asserted on): `patch("internal.bot.common.handlers.<module>.asyncio.sleep", new=AsyncMock())` as a class-scoped autouse fixture. Precedent: `test_user_memories_memory_regen.py:676`.

**Gotchas learned:**
- The slow test files use `unittest.TestCase` / `unittest.IsolatedAsyncioTestCase`, where pytest CANNOT inject fixture return values via test-function params (param silently dropped → TypeError). Workarounds that DO work: (a) `@contextmanager fakeClock()` for unittest methods, (b) a helper in a local `conftest.py` called from `asyncSetUp` with `testCase.addCleanup(patcher.stop)`, (c) class-scoped `@pytest.fixture(autouse=True)` (autouse works even on unittest classes). Three patterns in the repo now; divergence is justified by file structure.
- For concurrent `asyncio.sleep` under a fake clock (rate_limiter `asyncio.gather` tests): use `now[0] = max(now[0], deadline)` semantics so concurrent sleeps started together OVERLAP like real wall-clock (not stack additively); seed the clock at `0.0` (not real epoch) to avoid float-precision drift at exact window boundaries; still `await realAsyncSleep(0)` once for cooperative scheduling.
- Tests that use STRICT `assertGreater(elapsed, boundary)` fail under an exact fake clock (real runs overshoot via scheduling); prefer `assertGreaterEqual` to model the boundary as a floor.
- **Pacing-sleep safety:** before no-op'ing a production `asyncio.sleep`, check it's NOT inside a `while condition:` loop where the condition advances via real time (e.g. resender.py:389 media-group wait loop) — no-op'ing those causes infinite loops. Only safe if the loop variable advances independently OR the branch is unreachable in the test.

**Flagged but NOT fixed (out of scope):**
- `test_dict_cache.py::test_cleanup_performance` has a pre-existing bug: `defaultTtl=int(0.1)` evaluates to `0` = always-expired (the `int()` truncates). Real fix likely widens `DictCache`'s `defaultTtl: int` → `float` in production (`lib/cache/dict_cache.py:63`) — separate decision.
- `weather.py:634`, `yandex_search.py:634`, `spam.py:1143` (pacing `asyncio.sleep(0.5)`), `summarization.py:204/333` (blocking `time.sleep`) — NO tests exercise them, nothing to patch.
- Pre-existing uncommitted WIP in the working tree: production changes under `internal/` (new `_llmToolGetMessagesByIds`, `ToolName.GET_MESSAGES_BY_IDS`, `MAX_GET_MESSAGES_BATCH`) + a new `TestGetMessagesByIdsLLMTool` class (~18 tests) in `test_chat_search.py`. This is the user's WIP, NOT part of the speedup work; our changes are independent of it but live in the same file. Commit carefully.
- Optional future cleanup: extract the ~20-line fake-clock CM (shared between `tests/lib/utils/ttl_dict_test.py` and `tests/lib/cache/conftest.py`) into a `tests/lib/conftest.py` to avoid drift. Low priority.
