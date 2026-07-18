# Dependency-Usage Regression Tests (2026-07-15, COMPLETED)

Archived durable notes from [`../teamlead-memory.md`](../teamlead-memory.md) (extracted 2026-07-18). See the live compact memory there for cross-cutting rules and workflow lessons.

Task: add tests that lock in our *usage* of third-party libs so a dep-version bump can't silently break us. **DONE: 6 files, 79 tests under `tests/dependencies/` (new dir/convention), all gates green (3300 passed/11 skipped, pyright 0/0/0).** Scope was PURE libs + sqlite-vec; EXTERNAL libs deferred to golden follow-up.

**Direct-dep classification (27 in `requirements.direct.txt`):**
- **PURE (6):** `python-dateutil` 2.9.0.post0, `numpy` 2.5.1, `html-to-markdown` 3.8.3, `packaging` 26.2, `python-magic` 0.4.27, `tomli` 2.4.1.
- **EXTERNAL (7, out of scope this round):** `openai`, `yandex-ai-studio-sdk`, `fastembed`, `aiodocker`, `boto3`, `httpx-socks`, `sqlink`.
- **MIXED (5):** `aiosqlite`, `aiohttp`, `httpx`, `python-telegram-bot`, **`sqlite-vec` 0.1.9** (testable in-process — INCLUDED this round).
- **DEV (9):** black/isort/flake8/pyright/pytest stack + `PyYAML` (debug scripts only).

**Hidden transitive-direct imports (silent-break risk):** `google.protobuf.Struct` + `yandex.cloud.ai.foundation_models.v1.text_common_pb2` (`FunctionCall`/`ToolCall`/`ToolCallList`) in `lib/ai/providers/yc_sdk_provider.py:49-52` — protobuf major bumps (5.x→6.x happened) are a known breakage class. `typing_extensions.TypedDict` in `lib/aurumentation/types.py:15` (low-risk, stdlib shim).

**Coverage status (reconciled from source + test exploration):**
- **Already covered:** `packaging` via `TestValidatePackageSpec` (6 tests) — DROP from scope.
- **Partial:** `python-dateutil` (only ISO via `tests/database/test_utils.py::TestConvertSqlResponseToTypeStrInput`; gap = `.tzinfo is None` UTC-forcing branch in `internal/database/utils.py:232-235` + LLM/human formats in `user_memories.py:1224` / `webhook_updates.py:95`); `python-magic` (only PNG via `tests/bot/test_sandbox.py::test_sandbox_send_file_mime_detection`; gap = more formats — libmagic-db output shifts on bump).
- **Zero coverage (real gaps):** `html-to-markdown` (core handler `yandex_search.py:410-426`, `.content` can be None — load-bearing fallback; fast-moving lib); `numpy` cosine top-K (`internal/database/repositories/chat_search.py:404-424` — `np.argpartition` tie-breaking is UNSPECIFIED by numpy, float32 promotion changed across 2.x; affects which message IDs rank where); `sqlite-vec` vec0 (`user_memories.py:1188-1208` has literal `TODO: Test on latest sqlite-vec` on DELETE-by-metadata fallback); `tomli` (trivial, config-critical, low-risk).

**Key convention finding:** NO "direct-lib" regression tests exist in the repo today. All real third-party coverage is INCIDENTAL — production code that happens to call the real lib unmocked (`sqlToCustomType`→dateutil, `validatePackageSpec`→packaging, sandbox→magic, golden replayers→openai SDK). Existing golden infra: `tests/lib/<svc>/golden/` with `input/scenarios.json` + `data/` + `collect.py` + `test_golden.py`; `OpenAIReplayerPatcher`/`GoldenDataReplayer` for httpx-transport replay.

**User decisions (2026-07-15):** (1) Scope = PURE + sqlite-vec (packaging dropped — already covered). (2) Style = **through-production-code** where a clean wrapper exists; direct-lib fallback where prod path too deep (html-to-markdown in handler, tomli in config manager, magic is a one-liner). (3) Defer `yandex-ai-studio-sdk` + `fastembed` to golden-test follow-up (tracked, not actioned this round).

**Deferred follow-ups (tracked):** golden-test coverage for `yandex-ai-studio-sdk` (entirely untested — biggest gap) and `fastembed` real ONNX inference (never run in CI). Both need the record-real-responses-once workflow.

**OUTCOME (2026-07-15):** `tests/dependencies/` created with 6 files (test_dateutil, test_tomli, test_python_magic, test_html_to_markdown, test_numpy, test_sqlite_vec) + `__init__.py`. 79 tests, all passing. Each file pins its lib version via `importlib.metadata.version()` (sqlite-vec via `SELECT vec_version()` → `"v0.1.9"`) so a bump forces a conscious re-verification pass. Convention documented in `docs/llm/testing.md` (mirror-layout carve-out) + `docs/llm/index.md` (count 3300+) + CHANGELOG `[Unreleased]/Added`.

**Key behavioral findings surfaced by the tests (worth remembering):**
- **dateutil:** ambiguous `"01/02/2024"` resolves MONTH-FIRST (Jan 2) under `dayfirst=False` default — high-risk if a bump flips it (would silently change "messages since" queries). Also pinned: production's `except (ValueError, OverflowError, TypeError)` relies on dateutil raising a ValueError subclass (`ParserError`) on garbage.
- **html-to-markdown (3.8.3):** `.content` is NEVER None for string inputs (empty/stripped → `''`, not None). The production fallback branch at `yandex_search.py:419-423` (`else: logger.error("No content returned…")`) is **currently dead code**. Test pins reality; fails loudly if a future bump makes `.content` Optional-in-practice.
- **numpy:** cosine logic in `chat_search.py:403-424` is INLINE (not a discrete method) — test replicates the algorithm. Tie-order pinned as `[200, 300, 100, 400, 500]` under 2.5.1 (argsort tie-breaking is unspecified). Float32 literal pins use TOLERANCE (accumulation order is BLAS-defined, not a contract); dtype preservation is the separately-pinned authority.
- **sqlite-vec (0.1.9):** BOTH DELETE shapes (metadata-WHERE and rowid-fallback) SUCCEED today → production's try/except fallback at `user_memories.py:1188-1208` is currently never triggered, and `memory_id` (NOT a partition key) IS accepted in the DELETE predicate. If a future bump restricts DELETE-WHERE to partition keys (the scenario the production `TODO: Test on latest sqlite-vec` warns of), the tests fail loudly and the fallback becomes load-bearing. vec0 distance is deterministic per version (fixed native C ext), so its exact literal IS pinned (contrast numpy's tolerance).

**New test conventions established:**
- `tests/dependencies/` = sanctioned home for dep-usage regression tests (tests map to LIBRARIES, not source files → deliberate mirror-layout exception; documented in testing.md).
- Each file asserts `importlib.metadata.version("<dist>") == PINNED_VERSION` (or native version probe for loadable extensions) so bumps are a forced checkpoint.
- Philosophy: pin DETERMINISTIC library outputs exactly; use TOLERANCE for outputs with implementation-defined accumulation/ordering.
- Helper-naming: `_` prefix = trivial private wrapper; no prefix = documented production-mirror replica.
