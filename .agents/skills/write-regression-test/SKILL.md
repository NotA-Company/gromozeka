---
name: write-regression-test
description: >
  Recipe for writing a regression test that locks in a bug fix for Gromozeka.
  Encodes the AGENTS.md hard rule ("Regression tests on every bug fix"): write
  the test FIRST, confirm it FAILS (reproduces the bug), apply the minimal
  fix, confirm it PASSES, then add edge-case tests for adjacent behavior the
  bug touched. Covers the `tests/` mirror layout (no collocated tests), the
  `async def test_...` no-decorator convention, `conftest.py` fixture reuse,
  singleton `_instance = None` reset, real `EnsuredMessage` construction, and
  the complete-dict `chatSettings` mocking rule (production subscripts
  `chatSettings[KEY]` directly, never `.get()`). Also covers the
  explore-before-fixing lesson and the root-cause minimal-fix discipline.
  Triggers: fix bug, regression test, flaky test, crash, wrong output, bug
  fix, write test for bug, reproduce bug.
---

# Write a Regression Test for a Bug Fix

## When to use

- Fixing a bug in **production code** — a crash, wrong output, a silent no-op, a race, a flaky behavior.
- Fixing a bug in **test code** or **config** (the AGENTS.md rule names these explicitly — a "just a test/config fix" still gets a regression test).
- Before claiming a bug is fixed — the regression test is the proof, not a courtesy.
- Asked to "reproduce then fix" a defect.

## When NOT to use

- **New feature with no existing broken behavior** — that's feature-test territory; load the `add-handler` skill instead (its Step 8 covers feature tests).
- **Pure refactor with no behavior change** — a regression test by definition asserts a bug existed and is gone; for a behavior-preserving refactor, write a *characterization* test (pin current output) but don't force the fail-then-pass framing. Note: characterization tests are still valuable and encouraged, they just aren't "regression" tests in the strict sense here.
- **Doc-only change** — no code path to regress. (Still run `make format lint`.)
- **Investigating an unknown failure you can't yet reproduce** — delegate to the `debugger` agent first; this skill assumes you know what the bug is.

## Why this skill exists

The AGENTS.md hard rule:

> **Regression tests on every bug fix.** When fixing a bug — whether in
> production code, test code, or config — write a regression test that FAILS
> before the fix and PASSES after it. Include tests for edge cases that the
> bug touched (e.g., Optional/Union conversion, None handling, schema column
> mismatches). Do not rely solely on existing test coverage to catch
> regressions.

Two failure modes this skill prevents:

1. **The fix-without-proof** — a bug is "fixed" but the only evidence is the symptom disappearing on one input. The next refactor silently reintroduces it.
2. **The already-fixed re-fix** — a documented lesson (see [`teamlead-memory.md`](../../../docs/llm/teamlead-memory.md) "Teamlead Workflow Lessons"): *"Always verify the exploration phase — several candidate fixes may already be present from prior sessions. Avoid re-fixing fixed issues."* Several "candidate fixes" turned out to be already present; grep/read before patching.

## Prerequisites

Load `read-project-docs` first; specifically:

**Mechanism (conditional preference, never exclusive):** when the markdown-mcp MCP tools (`doc_outline`, `doc_read`, `doc_search`) are available, prefer them for the `./docs` targets below, using docs-root-relative paths — `doc_outline("llm/tasks.md")` first to resolve section slugs, then targeted `doc_read(file_path="llm/tasks.md", section_slug=…)`; `doc_search(query, file_glob="llm/teamlead-memory.md")` locates a section by content. Resolve `section_slug` values at use time — never hard-code them. Without MCP, plain `read` on the linked relative paths is an exact substitute.

- [`docs/llm/testing.md`](../../../docs/llm/testing.md) — directory structure, fixtures, pytest config, handler/DB test templates, singleton-reset patterns. With MCP: `doc_outline("llm/testing.md")` + targeted `doc_read(section_slug=…)` of the sections you need.
- [`docs/llm/tasks.md`](../../../docs/llm/tasks.md) §1.6 (bug-fix decision tree), §3 (gotchas), §4 (lessons) — with MCP, three targeted section reads instead of a whole-file read.
- [`docs/llm/teamlead-memory.md`](../../../docs/llm/teamlead-memory.md) — "Teamlead Workflow Lessons" and "Test Mocking: Chat Settings Must Be Complete Dicts" sections. The file is large (265+ lines); with MCP, targeted section reads are the win.
- [`AGENTS.md`](../../../AGENTS.md) — the regression-test hard rule, naming/typing/docstring rules. Manual `read` only — it sits at the repo root, outside the markdown-mcp docs root, so no `doc_*` tool reaches it.

## Step 0 — Explore before fixing (mandatory)

Before writing a line of test or fix code, verify the bug is real and not already addressed:

1. **Reproduce the symptom.** Construct the minimal input that triggers the wrong behavior. If you cannot reproduce it, delegate to the `debugger` agent — you don't have a fix target yet.
2. **Check the current code.** Grep for the function/branch the bug lives in. Read it. A prior session may have fixed it already — the lesson above is not hypothetical.
3. **Check existing tests.** `rg "<functionName>|<relevant symbol>" tests/` — is there already a test that *should* have caught this? If so, why didn't it? (Often: it mocked too much, or asserted on the wrong layer.)
4. **Identify the root cause**, not the symptom. If the cause is ambiguous ("sometimes None", "race under load"), delegate root-cause investigation to the `debugger` agent. This skill assumes a known root cause.

> If exploration shows the bug is already fixed in code, **stop** — write the regression test anyway (Step 1) to pin the fix, confirm it PASSES on current code, and document why. Do not re-apply a fix.

## Step 1 — Write the regression test FIRST

Path follows the `tests/` mirror layout (see Step 5). The test must **fail on the unfixed code**.

Skeleton (handler example — adapt the imports to your target):

```python
"""Regression test for <bug: one-line description of the defect>.

Pins the fix in <file/function>: before the fix, <what went wrong>. The test
drives <method> with <input> and asserts <correct behavior>; on unfixed code
it raises / returns <wrong value>.
"""

from typing import Generator
from unittest.mock import AsyncMock, Mock

import pytest

from internal.bot.common.handlers.some_handler import SomeHandler
from internal.bot.common.handlers.base import HandlerResultStatus
from internal.bot.models import BotProvider, EnsuredMessage, MessageRecipient, MessageSender


class TestSomeHandlerRegression:
    """Pins <bug short name>: <one-line root cause>."""

    @pytest.fixture(autouse=True)
    def _resetSingletons(self) -> Generator[None, None, None]:
        """Reset singletons this test touches.

        ``conftest.py`` resets ``LLMService`` / ``ProxyService`` / ``ProxyHelper``
        autouse, but NOT ``CacheService`` / ``QueueService`` / ``StorageService``
        / ``RateLimiterManager``. Reset those here if the code path reaches them.

        Yields:
            None.
        """
        # from internal.services.cache import CacheService
        # CacheService._instance = None
        yield
        # CacheService._instance = None

    @pytest.fixture
    def handler(self, mockConfigManager, mockDatabaseWrapper) -> SomeHandler:
        """Build a handler instance wired to mock deps.

        Args:
            mockConfigManager: Shared config-manager mock from conftest.
            mockDatabaseWrapper: Shared DB mock from conftest.

        Returns:
            A configured ``SomeHandler`` for the regression path.
        """
        h = SomeHandler(
            configManager=mockConfigManager,
            database=mockDatabaseWrapper,
            botProvider=BotProvider.TELEGRAM,
        )
        bot = Mock()
        bot.sendMessage = AsyncMock(return_value=[])
        h.injectBot(bot)
        return h

    async def test_regression_<shortBugName>(self, handler: SomeHandler) -> None:
        """<Correct behavior one-liner>.

        Args:
            handler: The handler fixture.
        """
        ensuredMessage = _makeEnsuredMessage(...)  # real EnsuredMessage — see Step 6

        result = await handler.newMessageHandler(ensuredMessage, Mock())

        assert result == HandlerResultStatus.FINAL  # or whatever the correct expectation is
```

Key structural rules (details in Steps 5–6):

- `async def test_…` with **no** `@pytest.mark.asyncio` decorator (`asyncio_mode = "auto"`).
- Reuse fixtures from [`tests/conftest.py`](../../../tests/conftest.py) — don't hand-roll DB/bot/config mocks.
- Build **real `EnsuredMessage`** objects, not raw dicts and not bare `Mock(spec=EnsuredMessage)` when the production path reads real attributes.
- Reset any singleton the code path touches that isn't already reset by conftest's autouse fixtures.

## Step 2 — Confirm the test FAILS (reproduces the bug)

Run the new test against the **unfixed** code:

```bash
./venv/bin/pytest tests/path/to/test_regression.py::TestSomeHandlerRegression::test_regression_xxx -v
```

❌ **A regression test that passes before the fix is worthless** — it doesn't prove the bug existed, so it can't prove the fix works. If it passes:

- The test isn't reaching the buggy branch (mocked too much, wrong input).
- The bug is already fixed (revisit Step 0).
- The assertion is wrong (you're asserting the buggy behavior).

Fix the test until it fails for the *right reason* — i.e., the failure message describes the bug, not a `KeyError` from a missing mock field or a mock wiring error.

## Step 3 — Apply the minimal fix

Fix the **root cause**, not the symptom. Smallest change that closes the bug.

- ❌ Don't refactor adjacent code in the same change — that's a separate concern, a separate review, and a separate (characterization) test.
- ❌ Don't add a defensive guard at the call site if the real defect is in a helper returning the wrong type; fix the helper.
- ❌ Don't "fix" the test by weakening the assertion to match buggy output.
- ✅ If the root cause is unclear after Step 0, delegate to the `debugger` agent for genuine root-cause investigation. Use `software-developer` only when the cause is known and you're applying a defined fix.

After the fix, the test from Step 1 must **pass**:

```bash
./venv/bin/pytest tests/path/to/test_regression.py::TestSomeHandlerRegression::test_regression_xxx -v
```

## Step 4 — Add edge-case tests for adjacent behavior

The AGENTS.md rule: *"Include tests for edge cases that the bug touched."* The bug rarely touches exactly one input. Add tests for the boundaries the fix could have over-corrected:

- `None` / empty-input handling (the classic — many bugs are `Optional`/`Union` conversion errors).
- Boundary values (off-by-one, `>=` vs `>`, empty list vs single element).
- Both chat types (`chatId > 0` private vs `chatId < 0` group — see [`docs/llm/tasks.md`](../../../docs/llm/tasks.md) §3).
- Both platforms if the fix touches platform-agnostic code (Telegram int IDs vs Max str IDs — `MessageId` wrapping).
- Schema column mismatches if the bug touched DB serialization.
- **API-client bug** (LLM/weather/search/geocode provider) → use the **golden-data replay** framework, not live API calls. See [`docs/llm/testing.md`](../../../docs/llm/testing.md) §6: per-service golden dirs live under `tests/lib/<service>/golden/` (`ai/`, `openweathermap/`, `yandex_search/`, `geocode_maps/`, `divination/`), replayed via transport-level httpx patching. Record a new golden fixture for the buggy input, then assert the fix produces the correct parsed output on replay.

Look at the real `TestD3DeleteMemoryGating` in [`tests/bot/common/handlers/test_llm_messages.py`](../../../tests/bot/common/handlers/test_llm_messages.py) for the parametrized four-combo pattern — it pins one fix across every `(useTools, allowSandbox)` combination the buggy branch could have leaked through.

## Step 5 — Put the test in the right place (mirror layout)

> **MANDATORY** — all new test files live under `tests/`. **No collocated tests** in `lib/` or `internal/`.

Mapping (from [`docs/llm/testing.md`](../../../docs/llm/testing.md) §1):

| Production file | Test file |
|---|---|
| `internal/X/Y.py` | `tests/X/test_Y.py` (strip `internal/`) |
| `lib/X/Y.py` | `tests/lib/X/test_Y.py` (keep `lib/`) |
| cross-cutting | `tests/integration/` or `tests/verification/` |

Examples:

- `internal/bot/common/handlers/some_handler.py` → `tests/bot/common/handlers/test_some_handler.py`
- `internal/database/repositories/user_memories.py` → `tests/database/repositories/test_user_memories.py`
- `lib/ai/manager.py` → `tests/lib/ai/test_manager.py`

If a test file already exists for the target module, **add the regression test class to it** rather than creating a sibling file. If the regression is a distinct concern worth its own file, name it `test_<area>_regression.py` (see [`tests/bot/common/handlers/test_user_info_cache_regression.py`](../../../tests/bot/common/handlers/test_user_info_cache_regression.py) for the precedent).

## Step 6 — Follow the test structure conventions

### Async convention

`asyncio_mode = "auto"` is set in [`pyproject.toml`](../../../pyproject.toml). Write:

```python
async def test_doesTheThing(self, handler) -> None:
    ...
```

❌ Never add `@pytest.mark.asyncio`. ❌ Never `asyncio.run(...)` inside a test.

### Reuse `conftest.py` fixtures

From [`tests/conftest.py`](../../../tests/conftest.py) — use these instead of hand-rolling mocks:

| Fixture | Use for |
|---|---|
| `testDatabase` | Real in-memory `Database` (SQLite `:memory:`) — for DB/repository/service-integration regression tests |
| `mockDatabaseWrapper` | Mocked `Database` — for handler tests that don't need real DB round-trips |
| `mockBot` | Mocked `ExtBot` with `AsyncMock` `sendMessage` |
| `mockConfigManager` | Mocked `ConfigManager` |
| `mockLlmService` / `mockCacheService` / `mockQueueService` | Mocked service singletons |
| `mockLlmManager` | Mocked `LLMManager` (AI provider manager — not a service singleton) |

The autouse fixtures `resetLlmServiceSingleton`, `resetProxyServiceSingleton`, `resetProxyHelperSingleton` already run before every test.

### Reset other singletons explicitly

These are **not** reset by conftest's autouse fixtures and **leak state across tests**:

- `CacheService`
- `QueueService`
- `StorageService`
- `RateLimiterManager`

If the regression path touches any of them, reset in an autouse fixture:

```python
@pytest.fixture(autouse=True)
def _resetSingletons(self) -> Generator[None, None, None]:
    """Reset <Service> singleton around the test.

    Yields:
        None.
    """
    from internal.services.cache import CacheService
    CacheService._instance = None
    yield
    CacheService._instance = None
```

For `testDatabase`-backed tests, also re-inject the DB into the reset singleton (see [`tests/bot/common/handlers/test_user_info_cache_regression.py`](../../../tests/bot/common/handlers/test_user_info_cache_regression.py) `_makeHandler` for the `CacheService._instance = None` → `getInstance()` → `await cache.injectDatabase(testDatabase)` sequence).

### Build real `EnsuredMessage` objects

❌ **Never** pass a raw `dict` where production code expects an `EnsuredMessage`. ❌ Prefer real construction over `Mock(spec=EnsuredMessage)` when the production path reads real attributes (`recipient`, `sender`, `messageId`, `threadId`, `metadata`).

```python
import datetime
from internal.bot.models import ChatType, EnsuredMessage, MessageRecipient, MessageSender, MessageType
from lib.db.utils import DEFAULT_THREAD_ID  # 0, NOT None

em = EnsuredMessage(
    sender=MessageSender(id=7, name="Alice", username="alice"),
    recipient=MessageRecipient(id=-100, chatType=ChatType.GROUP),
    messageId=42,
    date=datetime.datetime(2026, 7, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
    messageText="hello",
    messageType=MessageType.TEXT,
)
em.threadId = DEFAULT_THREAD_ID  # 0, not None — DB queries expect 0
```

The `EnsuredMessage` constructor accepts `messageId` as `int | str | MessageId` and wraps it internally, so `messageId=42` and `messageId=MessageId(42)` are equivalent at construction time. The resulting `em.messageId` attribute is **always** a `MessageId` object — access it via `.asInt()` for Telegram API calls, `.asStr()` for Max/SQL, and `.asMessageId()` for JSON serialization.

Recall the gotchas (full list in [`docs/llm/tasks.md`](../../../docs/llm/tasks.md) §3): `messageId` is a `MessageId` wrapping `int|str` (use `.asInt()`/`.asStr()`); chat type from `chatId` sign; `DEFAULT_THREAD_ID = 0` not `None`.

### Mock `chatSettings` as a COMPLETE dict

> Documented in [`docs/llm/teamlead-memory.md`](../../../docs/llm/teamlead-memory.md) "Test Mocking: Chat Settings Must Be Complete Dicts". The return-shape gotcha is documented in [`docs/llm/tasks.md`](../../../docs/llm/tasks.md) §3 ("`getChatSettings()` return shape is layer-dependent") and in the sibling `add-chat-setting` skill's Gotcha A.

Production code reads chat settings via **direct subscript**, never `.get(KEY, default)`. A sparse mock dict raises `KeyError` for every key the production path reads. The shape you mock **depends on the layer** the code path under test uses:

- **Handler / cache layer** (`self.getChatSettings()` → `ChatSettingsDict` = `Dict[ChatSettingsKey, ChatSettingsValue]`): each value is a **`ChatSettingsValue` object**, consumed via the typed converters `.toBool()`/`.toStr()`/`.toInt()`/`.toFloat()`/`.toList()`/`.toModel()`. Most handler tests mock this layer.
- **DB-repository layer** (`self.db.chatSettings.getChatSettings()` → `Dict[str, tuple[str, int]]`): each value is a **`(value, updatedBy)` tuple**, accessed via `[0]` (value) and `[1]` (updater). Mock this shape only if your test reaches the repository directly. Handlers rarely do — prefer mocking the handler-layer shape.

✅ For the handler layer, build a complete settings dict covering **every** `ChatSettingsKey` the production path touches, wrapping each value in `ChatSettingsValue(...)`:

```python
from internal.bot.models import ChatSettingsKey, ChatSettingsValue

def _fullChatSettings(*, useTools: bool = False) -> dict:
    """Build a complete chat-settings dict for the regression path.

    Args:
        useTools: Value for USE_TOOLS.

    Returns:
        A dict covering every ChatSettingsKey the production path reads.
    """
    return {
        ChatSettingsKey.USE_TOOLS: ChatSettingsValue("true" if useTools else "false"),
        ChatSettingsKey.ALLOW_SANDBOX: ChatSettingsValue("false"),
        ChatSettingsKey.LLM_MESSAGE_FORMAT: ChatSettingsValue("text"),
        # ... every other key the code path subscripts ...
    }
```

The reference implementation is `_fullChatSettings` in [`tests/bot/common/handlers/test_llm_messages.py`](../../../tests/bot/common/handlers/test_llm_messages.py) — copy its completeness discipline. When you add a new gate check in production (e.g. a new `ChatSettingsKey`), every `_fullChatSettings`/`_makeChatSettings` helper that feeds that path **must** be updated to include it, or tests silently start raising `KeyError`.

When mocking, match the shape the production code under test actually consumes: `ChatSettingsValue(...)` objects for the handler/cache layer (the common case); `(value, updatedBy)` tuples **only** if the test exercises the repository layer directly. Verify by reading the real consumer before constructing the mock dict.

### Naming and docstrings (the project rules apply to tests too)

- camelCase for locals/fixtures/methods; PascalCase for test classes; UPPER_CASE for module constants.
- Module docstring, class docstring, every test method docstring with `Args:`.
- Type hints on params and returns; on locals when not obvious.

## Step 7 — Verify (quality gates)

Load the `run-quality-gates` skill. Short form:

```bash
make format lint
make test
```

The **regression-proof**: temporarily revert the fix (or `git stash` it), re-run the new test, confirm it **fails**. Re-apply the fix, confirm it **passes**. This is the whole point — if the test passes both with and without the fix, it isn't a regression test.

Targeted re-run while iterating:

```bash
./venv/bin/pytest tests/path/to/test_regression.py -v
```

Then the full suite to confirm no collateral damage:

```bash
make test
```

## Step 8 — Documentation sync

If the bug fix changes **behavior**, **config**, or **schema** that docs describe, load the `update-project-docs` skill.

Surfaces to consider:

- [`docs/llm/tasks.md`](../../../docs/llm/tasks.md) §3 (gotchas) — if the bug revealed a new gotcha, add it (the `MediaStatus`/`MessageType` enum-not-string and "`getChatSettings()` return shape is layer-dependent" entries were all born from bugs).
- [`docs/llm/tasks.md`](../../../docs/llm/tasks.md) §4 (lessons) — if the bug revealed a reusable lesson.
- Handler/service/library docs — if the documented behavior was wrong (doc drift is a common cross-batch failure mode per [`docs/llm/teamlead-memory.md`](../../../docs/llm/teamlead-memory.md) "Large Review Campaign Lessons").
- Docstrings — *"When the same fact appears in a focused doc and in handler/class docstrings, update both surfaces explicitly; one does not propagate to the other."* (teamlead-memory.md "Teamlead Workflow Lessons").

For a pure logic bug with no public-surface change (e.g. an off-by-one in an internal helper), no doc update is needed beyond the test itself.

## Checklist

- [ ] **Explored first** — reproduced the symptom, confirmed the bug is real and not already fixed, identified the root cause.
- [ ] **Wrote the regression test FIRST** at the mirrored `tests/` path (no collocated test in `lib/`/`internal/`).
- [ ] **Confirmed the test FAILS** on unfixed code, failing for the *right reason* (describes the bug, not a mock wiring error).
- [ ] **Applied the minimal root-cause fix** — no adjacent refactor, no symptom-layer guard, no assertion-weakening.
- [ ] **Confirmed the test PASSES** after the fix; ran the regression-proof (revert fix → test fails → re-apply → test passes).
- [ ] **Added edge-case tests** for adjacent behavior the bug touched (None/Optional, boundaries, both chat types, both platforms, schema mismatches).
- [ ] `async def test_…` with **no** `@pytest.mark.asyncio` decorator.
- [ ] Reused `conftest.py` fixtures (`testDatabase`/`mockDatabaseWrapper`/`mockBot`/`mockConfigManager`/service mocks).
- [ ] Reset every singleton the path touches that isn't already autouse-reset (`CacheService`, `QueueService`, `StorageService`, `RateLimiterManager`) — `_instance = None` in an autouse fixture.
- [ ] Built **real `EnsuredMessage`** objects (not raw dicts, not bare spec mocks) — `messageId` via `MessageId`, `threadId = DEFAULT_THREAD_ID` (0, not None).
- [ ] `chatSettings` mock is a **complete dict** — every `ChatSettingsKey` the production path subscripts is present, wrapped in `ChatSettingsValue(...)` (handler/cache layer; use `(value, updatedBy)` tuples only if mocking the DB-repo layer directly).
- [ ] camelCase locals/methods, PascalCase test class, UPPER_CASE module constants; module/class/method docstrings with `Args:`.
- [ ] Type hints on all params/returns.
- [ ] `make format lint && make test` green.
- [ ] Loaded `update-project-docs` and synced any docs/gotchas/docstrings the fix invalidated.
