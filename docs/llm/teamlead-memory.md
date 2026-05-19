# Teamlead Memory

Durable working memory for `.opencode/agents/teamlead.md`.

How to use this file:
- Read it at the beginning of every task.
- Re-read it when prior context feels uncertain or incomplete.
- Update it immediately after learning durable new information.
- Consolidate and clean it before finishing a task.
- Store reusable facts, not temporary task chatter.
- Never store secrets, tokens, `.env` values, or raw logs.

## User Preferences

- Uses `TASK_STATE.md` at repo root as a resumable task-state file for multi-session work.
- Prefers parallel batching for independent subtasks (e.g., 6 files at once).
- Docstring improvement passes should follow one-file-per-task pattern with gate reviews between batches.

## Repo Facts And Gotchas

- `lib/sandbox/bootstrap.py` does NOT exist. The actual bootstrap script is at `scripts/sandbox_bootstrap.py` (TASK_STATE.md has the wrong location).
- `lib/sandbox/` has 19 non-test Python files total (across main dir, backends/, runtimes/, metadata/).
- Returns: sections in lib/sandbox/ use plain descriptions WITHOUT type prefixes (e.g., "The resolved Path." not "Path: The resolved path.").
- `runtimes/__init__.py` now has `from .base import Runtime` + `__all__ = ["Runtime"]` for consistency with backends/ and metadata/ subpackages.
- Pre-existing import issue: `from lib.sandbox.storage import sessionHash` reported in filesystem.py — investigated, NOT reproducible. Likely stale .pyc cache.
- `lib/utils/ttl_dict.py` provides a thread-safe TTL dict with GC, lazy expiration, and full dict API. Uses sentinel pattern for unspecified TTL vs ttl=None.
- Docker `MemorySwap` is the TOTAL memory+swap limit (not just swap). Setting it equal to `Memory` disables swap — counterintuitive but correct.
- `pathlib.relative_to()` is preferred over `str.startswith()` for path containment checks (cross-platform, handles symlinks/trailing slashes).
- `dict.setdefault()` is the canonical one-liner fix for check-then-create race conditions in CPython (GIL-protected).
- `@pytest.mark.asyncio` decorator is required on async test methods even though `asyncio_mode = "auto"` is set — this is a project convention.
- `SandboxBackend` protocol gained a `removeImage()` method to support rollback on partial `prepareRuntime` failure.
- Bot handler config-gating pattern: `if self.configManager.get("section", {}).get("enabled", False)` in HandlersManager, register before LLMMessageHandler (line ~534). Use `HandlerParallelism.PARALLEL` for most handlers.
- Chat setting access: `settings[key][0]` returns the value (tuple is `(value, updatedBy)`). Direct indexing preferred, not `.get()`. Writes need keyword-only `updatedBy=`.
- `isBotOwner()` is on `BaseBotHandler` (not `_bot`). Mock it as `handler.isBotOwner = Mock(...)` in tests, not `handler._bot.isBotOwner`.
- SandboxManager for bot: inject config in handler `__init__` (before any `getInstance()`). Check config section exists first — empty section crashes `fromDict`. Session model: `sessionId = str(chatId)`, auto-created by `runCode`.
- Multi-section truncation: update cumulative length after each section or all sections share the same remaining space (overflow risk).
- **`newMessageHandler` does NOT gate commands.** Commands are dispatched via `@commandHandlerV2` decorator and bypass the message handler chain. Per-command access checks must be in each command method (use a shared `_checkAccess()` helper).
- LLM tool registration: `self.llmService.registerTool(name, description, [LLMFunctionParameter(...)], handler=self._method)` in `__init__`. Gate with feature-enabled flag. Imports: `from lib.ai import LLMFunctionParameter, LLMParameterType`.
- LLM tool handler signature: `async def _method(self, extraData: Optional[Dict[str, Any]], param1, ..., **kwargs: Any) -> str`. Must return JSON `{"done": bool, ...}` — NEVER raise. Get chat context from `extraData["ensuredMessage"]`.

## Teamlead Workflow Lessons

- The teamlead prompt grants direct read/edit/write access only for this file; all substantive project work must still be delegated.
- For multi-file docstring passes: batch by complexity (init files + small → medium → large → manager), run Gate 1 per-batch, then Gate 2 whole-work.
- When code reviewers flag a Returns: format inconsistency, propagate the fix to ALL files in that batch (or the entire library) at once to avoid repeat reviews.
- Explicit type prefix format in Returns: sections (e.g., "int: Number of sessions") is WRONG for this project — use plain descriptions.
- Docstring correctness matters: always verify that docstring descriptions match actual implementation (not what the method is "supposed to do"). One review caught a method docstring claiming "filesystem scan" when it actually launches Docker containers.

## Durable Discoveries To Fold In

- Add fresh reusable facts here during a task, then merge them into the sections above before the final response.

## Review Fix Session (2026-05-20) — Sandbox Subsystem

### Sandbox-specific gotchas
- Sandbox error class is `SandboxRuntimeError` (NOT `RuntimeError` — was renamed to stop shadowing the builtin). Subclasses: `UnknownRuntime`, `MissingDependenciesError`.
- `RunResult.timedOut` checks BOTH `exitCode == 124` AND `signal == "SIGKILL"` — not just exit code (Docker backend's `asyncio.wait_for` may SIGKILL before inner `timeout` produces exit 124).
- `ResourceLimits.fromDict()` clamps `timeoutSeconds` to minimum 30, logging a warning if the configured value is below 30.
- `SessionLockRegistry` now uses `asyncio.Lock` + waiter counter (`_SessionState`), NOT `asyncio.Semaphore`. The old `sem._value` private-attr access is gone. See "SessionLockRegistry design lessons" in Teamlead Workflow section.
- Docker `hasImage` now uses targeted `client.images.inspect(imageTag)` in try/except `DockerError` — NOT `client.images.list()` with list comprehension.
- `MetadataStore.loadAllSessions()` exists (abstract + FilesystemMetadataStore impl via `asyncio.gather`). Use it instead of N+1 `listSessions()` + per-session `loadSession()`.
- Container names MUST use full UUIDs (`uuid.uuid4().hex`), never truncated. The docs rule "Use full UUIDs, never truncate" is enforced.
- `removeContainer` in finally blocks must be wrapped in try/except to avoid masking original exceptions.

### Config conventions (re-confirmed)
- `ConfigManager.get()` does NOT support dotted-path traversal — it's plain `dict.get(key, default)`. Always use nested `.get()` calls.
- Sandbox TOML keys: all multi-word keys use kebab-case. `starter-packages` (was `starter_packages`) is now kebab-case everywhere (TOML, code, tests, 7 doc files).
- `StorageConfig.fromDict()` octal defaults use `0o` prefix (`"0o700"`, `"0o600"`) for consistency with TOML.

### Teamlead workflow for review-fix sessions
- When fixing many small, independent issues from review documents: first explore thoroughly to determine which are already fixed, then batch independent fixes into parallel `software-developer` tasks (group by file to avoid conflicts), then single Gate 2 whole-work review. Per-subtask Gate 1 reviews are excessive for single-line fixes — a comprehensive whole-work review catches everything.
- Always verify the exploration phase — several fixes were already applied in a prior session (gc.py loadAllSessions, TTLDict stale expiration, DO_EXIT handler, recovery flow). Avoid re-fixing fixed issues.
- Docstring fixes in one file (sandbox.md) don't automatically propagate to the handler's own docstring — both must be checked separately.
- **When a `software-developer` subagent returns empty twice for the same task**, it likely hit the ~60 step budget. Switch approach: either give the user exact instructions (before/after code) and let them apply it, or try `general` agent. For truly tiny edits (<10 lines), the brief should be absolutely minimal — just the diff, no explanations.
- **Subagents may auto-commit their work** (commit messages like "Fix some issues"). When this happens, `git diff HEAD` won't show those changes. For whole-work reviews, use `git diff <base-commit>..HEAD` to capture everything.

### SessionLockRegistry design lessons
- The `asyncio.Semaphore` → `asyncio.Lock` + waiter counter rewrite is the right model for "1 active + N queued" semantics. Key: `_SessionState` dataclass with `lock`, `waiters`, `cancelled`.
- `forceCancel()` cascade: release the lock once; the woken callback checks `cancelled`, releases the lock (waking next), and raises `SessionDropped`. This cascades through all waiters.
- `dropSession(force=True)` lock interaction is tricky: `forceCancel` sets `cancelled=True`, then `acquire` raises `SessionDropped` before incrementing `waiters`. Must track with `lockAcquired` flag to avoid unpaired `release()` that corrupts the counter.
- `except BaseException` is needed in Docker container cleanup (not just `except Exception`) because `asyncio.CancelledError` inherits from `BaseException` in Python 3.12+. Task cancellation during `container.wait()` would otherwise leak containers.
- Defensive `waiters <= 0` guard in `release()` helps diagnose unpaired release bugs at runtime.
