# Gromozeka — Sandbox Code Execution Patterns

> **Audience:** LLM agents
> **Purpose:** Coding patterns, constraints, and anti-patterns for lib/sandbox/
> **Design docs:** [`docs/plans/python-sandboxing-v1.md`](../plans/python-sandboxing-v1.md)

---

## Module Overview

| Module | Purpose |
|--------|---------|
| `manager.py` | `SandboxManager` singleton — sessions, runs, files, libraries, GC, health |
| `types.py` | Public dataclasses (`RunResult`, `SessionInfo`, `ResourceLimits`, etc.) |
| `enums.py` | `RuntimeName`, `BackendName` |
| `config.py` | Configuration dataclasses (`SandboxConfig`, `StorageConfig`, etc.) |
| `errors.py` | Exception hierarchy (`SandboxError` → `SessionError`, `RunError`, etc.) |
| `locks.py` | Per-session FIFO lock registry, global run semaphore, pool flock |
| `storage.py` | Workspace path resolution, atomic JSON writes, directory layout |
| `gc.py` | Garbage collector for expired sessions, orphan workspaces, run records |
| `backends/docker.py` | Docker backend via `aiodocker==0.26.0` |
| `runtimes/python/runtime.py` | Python runtime with `timeout` wrapper and artifact detection |
| `metadata/filesystem.py` | Filesystem-backed metadata store (JSON) |

### Bot Integration

SandboxHandler (`internal/bot/common/handlers/sandbox.py`) provides slash commands and LLM tool integration:

**Slash commands:**
- `/run <code>` (alias: `/python`) — Execute Python code in sandbox
- `/sandbox files [path]` — List files in sandbox workspace
- `/sandbox read <path>` — Read a file from sandbox workspace
- `/sandbox status` — Show sandbox session status
- `/sandbox install <packages...>` — Install Python packages (admin only)

**LLM tool:**
- `run_python(code, packages?)` — Execute Python code in sandbox, returns `{"done": bool, "output": str | None, "exitCode": int | None, "errorMessage": str | None}`

**Chat setting:**
- `allow-sandbox` — Per-chat gate for sandbox functionality (default: false)

See [`handlers.md`](handlers.md) for handler registration and command implementation details.
See [`configuration.md`](configuration.md) for `sandbox.enabled` config key and `allow-sandbox` chat setting.

**Import paths:**
```python
from lib.sandbox import SandboxManager
from lib.sandbox.config import SandboxConfig, StorageConfig
from lib.sandbox.types import RunResult, SessionInfo, ResourceLimits
from lib.sandbox.enums import RuntimeName, BackendName
```

---

## Singleton Pattern (CRITICAL)

The `SandboxManager` uses a two-phase singleton: inject config first, then get the instance.

```python
from lib.sandbox import SandboxManager

# Phase 1: Inject configuration (must be done before any getInstance() call)
SandboxManager.injectConfig(config)

# Phase 2: Get instance (no arguments)
manager = SandboxManager.getInstance()
```

**WRONG (anti-patterns):**
```python
# DO NOT pass config to getInstance()
manager = SandboxManager.getInstance(config)  # WRONG

# DO NOT call getInstance() before injectConfig()
manager = SandboxManager.getInstance()  # Raises RuntimeError if injectConfig not called
```

**Implementation details:**
- `injectConfig(config)` stores config in `_configInstance` class variable. Accepts `SandboxConfig | dict` (dict is converted via `SandboxConfig.fromDict()`). Raises `RuntimeError` if instance already created.
- `getInstance()` (no args) creates instance via `__new__` + `__init__()`. Raises `RuntimeError` if `injectConfig()` hasn't been called.
- `__init__()` takes NO arguments — reads config from `SandboxManager._configInstance`.
- Thread-safe with `RLock` double-checked locking.

---

## Configuration System

### TOML keys MUST be kebab-case

All config keys in TOML use kebab-case. Each config dataclass has a `fromDict()` classmethod that maps kebab-case TOML keys to camelCase Python fields.

| TOML key | Python field |
|----------|-------------|
| `base-url` | `baseUrl` |
| `idle-ttl-minutes` | `idleTtlMinutes` |
| `max-queued-runs-per-session` | `maxQueuedRunsPerSession` |
| `read-only-rootfs` | `readOnlyRootfs` |
| `orphan-container-retention-minutes` | `orphanContainerRetentionMinutes` |

**No snake_case in TOML.** The only exceptions are single-word keys like `name`, `user`, `runtime`, `env`.

### Adding a new config field

1. Add the camelCase field to the dataclass with a default
2. Add the kebab-case key to the `fromDict()` method
3. Add the kebab-case key to `configs/00-defaults/sandbox.toml`
4. NEVER use `**data` unpacking on dict keys — always go through `fromDict()`

### Octal permission values

Storage permission fields (`dirMode`, `fileMode`) use `int(val, 0)` for parsing:
```python
dirMode = int(data.get("dir-mode", "0700"), 0)  # base 0 auto-detects octal
```
**NEVER** use a non-zero base like `int(val, 0o770)` — that's the base, not the mask.

### ResourceLimits — has its own fromDict

`ResourceLimits` is a dataclass in `types.py` (not `config.py`), but has `fromDict()` accepting kebab-case keys. `SandboxConfig.fromDict()` calls `ResourceLimits.fromDict()` — never `ResourceLimits(**data)`.

---

## Critical Coding Constraints

### 1. All imports at top of file

**NEVER** put imports inside functions or methods. The only exception is cyclic dependency avoidance.

```python
# WRONG — inside prepareRuntime():
def prepareRuntime(self, ...):
    from .config import PythonRuntimeConfig  # WRONG

# CORRECT — at top of file:
from .config import PythonRuntimeConfig, SandboxConfig
```

### 2. Never use hasattr/getattr for config objects

Once `SandboxConfig.fromDict()` converts runtime config dicts to dataclass instances, use direct attribute access:

```python
# WRONG:
if hasattr(runtimeConfig, "runImageTag"):
    tag = runtimeConfig.runImageTag

# CORRECT:
tag = runtimeConfig.runImageTag
```

`SandboxConfig.fromDict()` must convert all runtime config dicts to dataclass instances (currently only `PythonRuntimeConfig` is handled; unknown runtimes store raw dicts).

### 3. Never use dict-or-dataclass union types

Every config dataclass must have a `fromDict()` method. Callers use `fromDict()` to convert, then work with the dataclass directly. Never accept `dict | Dataclass` in method signatures.

### 4. Use full UUIDs, never truncate

```python
runId = uuid.uuid4().hex       # CORRECT: full 32-char hex
# NOT: uuid.uuid4().hex[:12]   # WRONG: truncated
```

### 5. Use kwargs-only for methods with complex struct params

```python
# CORRECT:
await backend.runOneshot(spec=containerSpec)

# WRONG:
await backend.runOneshot(containerSpec)
```

### 6. Use async with context managers for locks

```python
# CORRECT:
async with self._lockRegistry.sessionLock(sessionId):
    ...

# WRONG (manual acquire/release):
await self._lockRegistry.acquire(sessionId)
try:
    ...
finally:
    self._lockRegistry.release(sessionId)
```

Exception: `dropSession(force=True)` uses manual acquire/release because it needs special `SessionBusy`/`SessionDropped` exception handling.

### 7. All backends must have close()

The `SandboxBackend` protocol requires a `close()` method. Never use `hasattr(backend, "close")` — call `await backend.close()` directly.

### 8. Docker backend: connector close order

In aiodocker 0.26.0, the `Docker` class stores `aiohttp.ClientSession` as the **public** `self.session` attribute (NOT `self._session`). When closing:
1. Close `self._client.session.connector` FIRST (before `client.close()` nulls the session)
2. Then call `self._client.close()`

```python
async def close(self) -> None:
    if self._client is not None:
        try:
            if hasattr(self._client, "session") and self._client.session is not None:
                if self._client.session.connector is not None:
                    await self._client.session.connector.close()
        except Exception as exc:
            logger.warning("Failed to close connector: %s", exc)
        try:
            await self._client.close()
        except Exception:
            pass
        self._client = None
```

**NEVER** use `self._client._session` — the underscore attribute doesn't exist in aiodocker 0.26.0.

### 9. shutdown() must cancel active runs

`shutdown()` must cancel all active runs via `cancelRun()` before dropping sessions and closing the backend.

### 10. aiodocker version must be pinned

```text
aiodocker==0.26.0
```

Not `>=0.21.0` — version ranges are forbidden.

---

## Security Considerations

### Package installation is admin-only

Package installation in the sandbox is an admin-only operation. End users cannot inject arbitrary package specs (URL-based, editable installs, etc.) — only the bot administrator can install packages via the bootstrap script or admin commands.

The `installRuntimeLibraries` method in `SandboxManager` enforces this security boundary through:

- **Input validation**: The `_validatePackageSpec` method rejects specs containing shell metacharacters (`&`, `|`, `;`, backticks, command substitution) or flag-like specs starting with `-`
- **Controlled execution**: The `pip install` command is constructed from pre-validated package names; spec-level injection is not possible
- **Admin-only access**: The method is only called from admin contexts (bootstrap scripts, admin commands) and never exposed to end-user code execution

This design ensures that package installation remains a privileged operation, protecting against supply chain attacks that would otherwise allow end users to introduce arbitrary Python code via malicious package specs.

---

## Testing

### Fast tests
```bash
make test
```

### Docker integration tests
Docker tests require Colima/Docker running and two env vars:
```bash
DOCKER_HOST="unix:///Users/vgoshev/.colima/default/docker.sock" DOCKER_AVAILABLE=1 \
./venv/bin/pytest lib/sandbox/tests/ -v -m slow
```

- 19 Docker integration tests across `test_docker.py`, `test_manager_runs_integration.py`, `test_manager_libs_integration.py`
- All gated by `@pytest.mark.slow` and `pytestmark = [pytest.mark.slow, pytest.mark.skipif(not DOCKER_AVAILABLE, ...)]`
- Workspace uses `~/.gromozeka-tests/` (not `tmp_path`) because Docker doesn't share macOS temp dirs
- After tests, verify NO "Unclosed connector" warnings in output

### Singleton state in tests
Reset singleton state between tests:
```python
SandboxManager._instance = None
SandboxManager._configInstance = None
```

### Test config construction
When building config dicts in tests, use kebab-case keys:
```python
configDict = {
    "storage": {"root-dir": "/tmp/test", "dir-mode": "0700", "file-mode": "0600"},
    "backend": {"name": "docker", "docker": {"base-url": "unix:///..."}},
    ...
}
SandboxManager.injectConfig(configDict)
manager = SandboxManager.getInstance()
```

---

## Usage Example

```python
from lib.sandbox import SandboxManager, SandboxConfig, StorageConfig, RunResult

# Build config
config = SandboxConfig(storage=StorageConfig(rootDir="/var/lib/gromozeka/sandbox"))

# Inject + get instance
SandboxManager.injectConfig(config)
manager = SandboxManager.getInstance()

# Create session and run code
session = await manager.createSession("my-session")
result: RunResult = await manager.runCode(session.sessionId, "print(2 + 2)")
print(result.exitCode)  # 0

# Clean up
await manager.shutdown()
```

**Configuration file:** [`configs/00-defaults/sandbox.toml`](../../configs/00-defaults/sandbox.toml)

---

## See Also

- [`index.md`](index.md) — Project overview, critical commands
- [`libraries.md`](libraries.md) — All lib/ subsystems
- [`configuration.md`](configuration.md) — Configuring lib integrations via TOML
- [`testing.md`](testing.md) — Test fixtures and patterns
- [`tasks.md`](tasks.md) — Task workflows and anti-patterns
