# Sandbox Task Memory

Durable task-specific memory for the completed `lib/sandbox` / sandbox bot integration work.

How to use this file:
- Read it when touching `lib/sandbox/`, sandbox-related configuration, or sandbox bot-handler/docs work.
- Keep only sandbox-scoped discoveries here; move repo-wide lessons back to [`../teamlead-memory.md`](../teamlead-memory.md).
- Never store secrets, tokens, `.env` values, or raw logs.

## Repo Facts And Gotchas

- `lib/sandbox/bootstrap.py` does NOT exist. The actual bootstrap script is at `scripts/sandbox_bootstrap.py` (`TASK_STATE.md` had the wrong location).
- `lib/sandbox/` has 19 non-test Python files total (across main dir, `backends/`, `runtimes/`, `metadata/`).
- Returns sections in `lib/sandbox/` use plain descriptions without type prefixes (e.g., `The resolved Path.` not `Path: The resolved path.`).
- `runtimes/__init__.py` now has `from .base import Runtime` + `__all__ = ["Runtime"]` for consistency with `backends/` and `metadata/` subpackages.
- Pre-existing import issue: `from lib.sandbox.storage import sessionHash` reported in `filesystem.py` was investigated and NOT reproducible. Likely stale `.pyc` cache.
- Docker `MemorySwap` is the TOTAL memory+swap limit (not just swap). Setting it equal to `Memory` disables swap.
- `SandboxBackend` protocol gained a `removeImage()` method to support rollback on partial `prepareRuntime()` failure.
- SandboxManager for bot integration: inject config in handler `__init__` before any `getInstance()` call. Check the config section exists first — an empty section crashes `fromDict()`. Session model: `sessionId = str(chatId)`, auto-created by `runCode()`.

## Review Fix Session (2026-05-20)

### Sandbox-Specific Gotchas

- Sandbox error class is `SandboxRuntimeError` (not `RuntimeError`). Subclasses: `UnknownRuntime`, `MissingDependenciesError`.
- `RunResult.timedOut` checks BOTH `exitCode == 124` AND `signal == "SIGKILL"` — not just exit code.
- `ResourceLimits.fromDict()` clamps `timeoutSeconds` to minimum 30, logging a warning if the configured value is below 30.
- `SessionLockRegistry` now uses `asyncio.Lock` + waiter counter (`_SessionState`), not `asyncio.Semaphore`.
- Docker `hasImage()` now uses targeted `client.images.inspect(imageTag)` in try/except `DockerError` — not `client.images.list()` with list comprehension.
- `MetadataStore.loadAllSessions()` exists (abstract + `FilesystemMetadataStore` impl via `asyncio.gather`). Use it instead of N+1 `listSessions()` + per-session `loadSession()`.
- Container names MUST use full UUIDs (`uuid.uuid4().hex`), never truncated.
- `removeContainer()` in finally blocks must be wrapped in try/except so cleanup failures do not mask the original exception.

### Sandbox Config Conventions

- Sandbox TOML keys use kebab-case for multi-word keys. `starter-packages` replaced `starter_packages` everywhere (TOML, code, tests, docs).
- `StorageConfig.fromDict()` octal defaults use `0o` prefix (`"0o700"`, `"0o600"`) for consistency with TOML.

### SessionLockRegistry Design Lessons

- The `asyncio.Semaphore` → `asyncio.Lock` + waiter counter rewrite is the right model for `1 active + N queued` semantics. Key shape: `_SessionState` dataclass with `lock`, `waiters`, `cancelled`.
- `forceCancel()` cascade: release the lock once; the woken callback checks `cancelled`, releases the lock, and raises `SessionDropped`. This cascades through all waiters.
- `dropSession(force=True)` lock interaction is tricky: `forceCancel()` sets `cancelled=True`, then `acquire()` raises `SessionDropped` before incrementing `waiters`. Track with a `lockAcquired` flag to avoid an unpaired `release()` that corrupts the counter.
- `except BaseException` is needed in Docker container cleanup (not just `except Exception`) because `asyncio.CancelledError` inherits from `BaseException` in Python 3.12+.
- Defensive `waiters <= 0` guard in `release()` helps diagnose unpaired-release bugs at runtime.
