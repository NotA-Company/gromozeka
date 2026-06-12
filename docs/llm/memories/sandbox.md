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

## Sandbox Improvements (2026-06-09)

### Per-run working directory

- `SandboxManager.runCode()` creates a `work/` subdirectory inside `.run/<runId>/` before execution.
- `RunResult.workDir` carries the workspace-relative path (e.g. `.run/<runId>/work`).
- `PythonRuntime.runCommand()` now starts with `cd /workspace/.run/{runId}/work &&` — scripts run inside the per-run directory, so files written with relative paths land there.
- `main.py` stays in the parent `.run/<runId>/` directory (not inside `work/`), so it doesn't appear in file listings.
- Handler scans workDir via `SandboxManager.listFiles(sessionId, path=result.workDir, recursive=True)` after execution.

### LLM tools

Four tools registered in `SandboxHandler.__init__()` (all gated behind `sandbox.enabled` + `allow-sandbox`):
- `run_python` — execute Python code (existing, unchanged)
- `sandbox_list_files` — list workspace files, params: `path` (STRING), `recursive` (BOOLEAN)
- `sandbox_read_file` — read file content with line-based `offset` (NUMBER) and `limit` (NUMBER), 64 KB maxBytes default, handles non-UTF-8 with `errors="replace"`
- `sandbox_send_file` — send file to user with automatic MIME detection, params: `path` (STRING), `caption` (STRING), 20 MB cap

All tool handlers:
- Return JSON `{"done": bool, ...}` — NEVER raise
- Gate with `extraData` → `sandboxEnabled` → `allow-sandbox` chat setting
- Normalize sandbox exceptions (`SessionNotFound`, `PathOutsideWorkspace`, etc.) into user-safe error messages
- Use `self.getSessionId(ensuredMessage)` for session ID derivation (`chat#<id>` format)

### MIME detection and file sending

- `sandbox_send_file` reads files with `encoding=None` (raw bytes) for binary support.
- MIME detection: `magic.from_buffer(data, mime=True)` in the handler layer (not in `lib/sandbox/`).
- MIME→MessageType mapping: `image/*` → IMAGE, `video/*` → VIDEO, `audio/*` → AUDIO, rest → DOCUMENT.
- Files sent via `self.sendMessage(ensuredMessage, attachmentList=[(data, messageType, filename)])`.
- `MAX_SANDBOX_SEND_BYTES = 20 * 1024 * 1024` (20 MB cap, rejects oversized files).

### Implementation gotchas

- `RunResult.workDir` is workspace-relative (`.run/<runId>/work`), not host-absolute. This matches `stdoutPath`/`stderrPath` convention.
- `workDir` field is at the end of `RunResult` with default `""` for backward compat (dataclass `slots=True` requires defaults at the end).
- `RunResult.fromDict()` was added — defaults missing `workDir` to `""` for old serialized data.
- `_sandboxReadFile()` uses `encoding=None` in `readFile()` call then decodes with `errors="replace"` — the bytes-handling branch is no longer dead code.
- The `/run` command response tracks `codeBlockOpened` boolean to avoid stray ``` fence when no stdout but files created.
- File list in `/run` response is budgeted against `maxLength` to avoid overflow.

### Test locations

- `tests/lib/sandbox/test_types_roundtrip.py` — RunResult roundtrip with workDir
- `tests/lib/sandbox/runtimes/test_python_runtime.py` — cd into workDir prefix test
- `tests/lib/sandbox/test_manager.py` — workDir creation and path format tests
- `tests/bot/test_sandbox.py` — 51 handler tests covering file scanning, all four LLM tools, access control, MIME detection, size limits, and edge cases
