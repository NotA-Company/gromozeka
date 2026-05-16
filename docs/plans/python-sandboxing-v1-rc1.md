# Sandboxed Code Execution — Design v1 RC1

Status: **proposed design, no code yet**
Supersedes: [`python-sandboxing-v0.gpt.md`](python-sandboxing-v0.gpt.md), [`python-sandboxing-v0.gemini.md`](python-sandboxing-v0.gemini.md)
Scope: design-only. Implementation will be staged separately.

This document consolidates the two v0 brainstorms and applies the decisions taken with the project owner:

- **Backend/runtime abstractions** built from day one; v0 ships **Docker + Python** only.
- **Async API** throughout (`aiodocker`); matches Gromozeka's asyncio stack.
- **Opaque `sessionId: str`** passed in by the caller. The library knows nothing about chats or threads.
- **Ephemeral containers, persistent per-session workspace volume.** No long-lived process state.
- **FIFO queue per session**: at most one run executes at a time per `sessionId`; further calls wait.
- **NetworkPolicy** as a structured type with a single `enabled: bool` field today, extensible later.
- **Libraries are runtime-scoped, admin-managed, RO-mounted.** Not per-session, not LLM-extensible.
- **No disk/artifact size limits.** Storage lives on a dedicated volume/device the operator sizes.
- **No stdout/stderr in-memory caps.** Both streams are redirected to files inside the workspace and treated as artifacts; size caps apply only at read time.
- **Storage on host bind-mount** under a configurable `storage.rootDir`.

The remainder of the document is the actual design.

---

## 1. Goals & non-goals

### Goals

1. Safely execute untrusted, LLM-generated Python code on the host running Gromozeka.
2. Preserve workspace files and produced artifacts across runs within a logical "session".
3. Allow a curated, shared, mutable set of Python libraries per runtime, controlled by an admin — never by the LLM or end user.
4. Enforce hard CPU / RAM / PID / timeout / network limits on every run.
5. Expose a typed, async, language-agnostic API that can be extended to TypeScript, Bash, etc. without API churn.
6. Be reusable: the library lives under [`lib/sandbox/`](../../lib/) per the [`AGENTS.md`](../../AGENTS.md) "lib/ has no bot deps" rule. A thin adapter in [`internal/services/`](../../internal/services/) plugs it into the bot.

### Non-goals (v0)

- Non-Docker backends (gVisor, Firecracker, Kubernetes Jobs). The `SandboxBackend` interface exists; only `DockerBackend` is implemented.
- Non-Python runtimes. The `Runtime` interface exists; only `PythonRuntime` is implemented.
- Network proxy / domain allowlist. `NetworkPolicy` only has `enabled: bool` today, but the dataclass shape supports future fields.
- Persistent (long-lived) execution containers. Workspace is persistent; the container is not.
- Per-session library installation. Libraries are runtime-scoped.
- Disk quotas, artifact size caps, output byte caps. Dedicated volume + read-time caps.
- LLM policy decisions (which code can run, rate-limiting). Lives in the calling bot tool, not in the library.

---

## 2. Glossary

| Term | Meaning |
|---|---|
| **Backend** | A concrete sandboxing mechanism. v0 = Docker. Future = gVisor, Firecracker. |
| **Runtime** | A language profile (image, packaging tooling, run command). v0 = Python. |
| **Session** | A logical workspace identified by an opaque `sessionId: str`. Owns a persistent workspace directory and metadata. Has a TTL. |
| **Run** | A single execution of code in a session. Has its own `runId`, ephemeral container, recorded stdout/stderr/exit. |
| **Library pool** | The runtime-scoped, RO-mounted set of installed packages. Per-runtime, not per-session. Mutable only via admin API. |
| **Artifact** | Any file under the session workspace, including the auto-captured `stdout.log` / `stderr.log` of a run. |
| **Workspace** | The session's writable directory mounted RW into every run container at a fixed path (`/workspace`). |

---

## 3. High-level architecture

```text
                  ┌────────────────────────────────────────────────┐
                  │              SandboxManager (public)           │
                  │   sessions • runs • libs • files • GC • health │
                  └──────────────────┬─────────────────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
       ┌──────▼──────┐      ┌────────▼─────────┐    ┌───────▼────────┐
       │  Backend    │      │     Runtime      │    │   Storage      │
       │ (Protocol)  │      │   (Protocol)     │    │   layout +     │
       │             │      │                  │    │   metadata     │
       │ DockerBack  │      │ PythonRuntime    │    │   (host FS)    │
       └─────────────┘      └──────────────────┘    └────────────────┘
```

Three orthogonal axes:

1. **Backend** = how to run a container (Docker today).
2. **Runtime** = which language / which image / which `pip` lives inside.
3. **Storage** = where files persist on the host.

`SandboxManager` is the singleton entry point, composes one Backend with N Runtimes, and owns the Storage layout, per-session locks, and the GC loop.

---

## 4. Repository layout

Following the [`AGENTS.md`](../../AGENTS.md) layering rules:

```text
lib/
  sandbox/
    __init__.py                 # public re-exports
    manager.py                  # SandboxManager (singleton via getInstance())
    types.py                    # TypedDicts + dataclasses for the public API
    errors.py                   # SandboxError hierarchy
    locks.py                    # per-session asyncio FIFO lock
    storage.py                  # host directory layout + metadata helpers
    gc.py                       # GarbageCollector
    backends/
      __init__.py
      base.py                   # SandboxBackend Protocol
      docker.py                 # DockerBackend (aiodocker)
    runtimes/
      __init__.py
      base.py                   # Runtime Protocol
      python/
        __init__.py
        runtime.py              # PythonRuntime
        Dockerfile              # python:3.12-slim base
    tests/                      # collocated, per AGENTS.md tests rule

internal/
  services/
    sandbox/
      __init__.py
      service.py                # SandboxService singleton, gromozeka-aware adapter
                                # builds sessionId from chatId+threadId,
                                # wires config from ConfigManager
```

**Rationale for the `lib/sandbox/` location**: it has no `internal/`, no telegram/max, no bot-specific types. The `internal/services/sandbox/` shim is the only place that knows about Gromozeka, satisfying the lib-has-no-bot-deps rule.

---

## 5. Public API

All methods are `async`. Naming is **camelCase** per project rules. No pydantic — TypedDicts and `@dataclass(slots=True)`.

### 5.1 Manager singleton

```python
class SandboxManager:
    @classmethod
    def getInstance(cls, config: SandboxConfig | None = None) -> "SandboxManager":
        ...

    async def healthcheck(self) -> HealthcheckResult: ...
    async def shutdown(self, cleanVolumes: bool = False) -> ShutdownResult: ...
    async def recover(self) -> RecoveryResult: ...
    async def collectGarbage(self) -> GcResult: ...
```

Initialised once at startup with a `SandboxConfig`. Subsequent `getInstance()` calls return the same instance (matches Gromozeka's singleton pattern, see [`AGENTS.md`](../../AGENTS.md)).

### 5.2 Runtime / image management

```python
async def prepareRuntime(self, runtime: str, *, rebuild: bool = False) -> RuntimeInfo:
    """Build or pull the runtime image; ensure the lib pool directory exists."""

async def listRuntimes(self) -> list[RuntimeInfo]: ...
```

### 5.3 Sessions

```python
async def createSession(
    self,
    sessionId: str,
    *,
    runtime: str = "python",
    forceRecreate: bool = False,
    ttlMinutes: int | None = None,
    network: NetworkPolicy | None = None,
    limits: ResourceLimits | None = None,
) -> SessionInfo: ...

async def getSessionInfo(self, sessionId: str) -> SessionInfo | None: ...
async def listSessions(self, *, runtime: str | None = None) -> list[SessionInfo]: ...
async def touchSession(self, sessionId: str, *, ttlMinutes: int | None = None) -> SessionInfo: ...
async def resetSession(
    self,
    sessionId: str,
    *,
    keepArtifacts: bool = False,
) -> ResetSessionResult: ...
async def dropSession(
    self,
    sessionId: str,
    *,
    force: bool = True,
) -> DropSessionResult: ...
```

`createSession` is idempotent unless `forceRecreate=True`. It creates the workspace directory and a `metadata.json` under the storage root; no container is created here.

### 5.4 Runs

```python
async def runCode(self, request: RunRequest) -> RunResult: ...
async def cancelRun(self, runId: str) -> bool: ...
async def getRunInfo(self, runId: str) -> RunInfo | None: ...
```

`RunRequest` (see §6) carries everything: code, optional stdin, env, files-to-inject, required packages (verified against the pool, *not* installed on demand), timeout, network policy, resource limit overrides.

Required-package handling:

- If any package in `request.requiredPackages` is missing from the runtime's library pool, `runCode` raises `MissingDependenciesError(missing=[...])` **without starting the container**.
- The bot tool layer is responsible for translating that into a user-facing "ask the admin to install these" message.

### 5.5 Files & artifacts

```python
async def listFiles(
    self,
    sessionId: str,
    *,
    path: str = "/",
    recursive: bool = False,
) -> list[FileInfo]: ...

async def readFile(
    self,
    sessionId: str,
    path: str,
    *,
    maxBytes: int | None = None,
    encoding: str | None = "utf-8",
) -> FileContent: ...

async def writeFile(
    self,
    sessionId: str,
    path: str,
    content: bytes | str,
    *,
    overwrite: bool = True,
) -> FileInfo: ...

async def deleteFile(self, sessionId: str, path: str) -> bool: ...
```

`readFile`/`maxBytes` is the **only** place output is bounded — stdout and stderr live as `/workspace/.run/<runId>/stdout.log` and `/workspace/.run/<runId>/stderr.log` (see §8.2), and the caller picks how much to read.

### 5.6 Library pool (admin API)

```python
async def listRuntimeLibraries(self, runtime: str = "python") -> list[PackageInfo]: ...
async def freezeRuntimeLibraries(self, runtime: str = "python") -> str: ...

async def installRuntimeLibraries(
    self,
    packages: Sequence[str],
    *,
    runtime: str = "python",
    upgrade: bool = False,
    timeoutSeconds: int = 600,
) -> LibraryInstallResult: ...

async def removeRuntimeLibraries(
    self,
    packages: Sequence[str],
    *,
    runtime: str = "python",
) -> LibraryRemoveResult: ...
```

These are the **only** APIs that mutate the library pool. They're protected by a process-wide install lock per runtime (§9). They run a **dedicated install container** (writable target, network enabled) and are intended to be called from an admin/operator surface — never from `runCode` or from LLM tools.

---

## 6. Data model

All dataclasses live in `lib/sandbox/types.py` and use `@dataclass(slots=True, frozen=False)` (frozen where it makes sense). Python types only; no pydantic.

### 6.1 Inputs

```python
@dataclass(slots=True)
class NetworkPolicy:
    enabled: bool = False
    # Reserved for future: mode, allowedHosts, proxyUrl

@dataclass(slots=True)
class ResourceLimits:
    memoryMb: int = 512
    memorySwapMb: int | None = 512        # equal to memoryMb disables swap
    cpuCount: float = 1.0
    pidsLimit: int = 64
    timeoutSeconds: int = 30
    tmpfsSizeMb: int = 64

@dataclass(slots=True)
class InputFile:
    path: str                              # relative to /workspace
    content: bytes | str
    overwrite: bool = True

@dataclass(slots=True)
class RunRequest:
    sessionId: str
    code: str
    runtime: str = "python"
    timeoutSeconds: int | None = None
    requiredPackages: list[str] = field(default_factory=list)
    network: NetworkPolicy = field(default_factory=NetworkPolicy)
    stdin: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    files: list[InputFile] = field(default_factory=list)
    limits: ResourceLimits | None = None
```

### 6.2 Outputs

```python
@dataclass(slots=True)
class SessionInfo:
    sessionId: str
    runtime: str
    workspacePath: str                     # host path, for ops/debugging
    createdAt: datetime
    updatedAt: datetime
    expiresAt: datetime
    networkEnabled: bool                   # last requested
    metadata: dict[str, str]               # opaque caller-controlled

@dataclass(slots=True)
class RunResult:
    runId: str
    sessionId: str
    runtime: str
    stdoutPath: str                        # artifact path (read via readFile)
    stderrPath: str
    stdoutBytes: int
    stderrBytes: int
    exitCode: int | None
    signal: str | None
    timedOut: bool
    oomKilled: bool                        # detected from exit code 137 + Docker inspect
    startedAt: datetime
    finishedAt: datetime
    elapsedMs: int
    newArtifacts: list[ArtifactInfo]       # files appearing/changing during the run
    limits: ResourceLimits
    error: str | None

@dataclass(slots=True)
class FileInfo:
    path: str
    sizeBytes: int
    modifiedAt: datetime
    isDirectory: bool

@dataclass(slots=True)
class FileContent:
    path: str
    sizeBytes: int                         # full size on disk
    bytesRead: int                         # may be < sizeBytes if maxBytes hit
    truncated: bool
    content: bytes | str

@dataclass(slots=True)
class PackageInfo:
    name: str
    version: str

@dataclass(slots=True)
class LibraryInstallResult:
    runtime: str
    installed: list[PackageInfo]
    skipped: list[str]
    failed: list[tuple[str, str]]          # (package, reason)
    poolVersion: str                       # see §7
```

(Full list — `ArtifactInfo`, `HealthcheckResult`, `GcResult`, `RecoveryResult`, `ResetSessionResult`, `DropSessionResult` — has the same shape as GPT v0 §17; omitted here for brevity.)

### 6.3 Errors

```text
SandboxError                               # base
  ConfigError
  BackendError
    DockerUnavailable
    ImageNotFound
  SessionError
    SessionNotFound
    SessionBusy                            # FIFO queue exceeded a queue cap
  RuntimeError
    UnknownRuntime
    MissingDependenciesError(missing=[...])
  RunFailed
    RunTimedOut
    RunOomKilled
  LibraryError
    LibraryInstallFailed
    LibraryPoolLocked
  FileError
    PathOutsideWorkspace                   # path traversal attempt
    FileTooLarge
```

---

## 7. Storage layout

A single configurable `storage.rootDir` (default `/var/lib/gromozeka/sandbox`) holds everything. Library pools sit alongside sessions; the operator can put `rootDir` on a dedicated volume/device of any size.

```text
${storage.rootDir}/
  runtimes/
    python/
      libs/                               # the lib pool, RO into sessions
      metadata.json                       # installed packages + versions + installedAt
      pool.lock                           # POSIX flock during install (process-wide guard)
      image.tag                           # last built image tag
  sessions/
    <sessionHash>/                        # sha256(sessionId)[:32]
      workspace/                          # mounted RW into runs as /workspace
        ... user files ...
        .run/
          <runId>/
            stdout.log
            stderr.log
            result.json                   # snapshot of RunResult
      metadata.json                       # SessionInfo + history index
  runs/
    index/<runId>.json                    # pointer to sessionHash + runId
  tmp/                                    # scratch for atomic writes
```

UID/GID: every directory is owned by the same non-root user that the sandbox container runs as (default `1000:1000`, configurable). The library pool and workspace directories are created with mode `0700`; the install container and run container both run as the same UID so the RO mount works trivially.

`sessionHash = sha256(sessionId)[:32]` to avoid any filesystem-unfriendly characters and to keep raw user input out of paths.

`pool.lock` is a real `fcntl.flock` on the file — it survives process restart and protects against a crashed install leaving the pool in an inconsistent state.

`poolVersion` (returned in `LibraryInstallResult`) is the SHA-256 of `metadata.json`'s sorted package list. It lets callers detect "the pool changed since I last verified".

---

## 8. Lifecycles

### 8.1 Session lifecycle

```text
createSession(sid)
  └── if sessionHash dir exists and not forceRecreate: load metadata, return reused=true
  └── else: mkdir workspace, write metadata.json, return reused=false

runCode(request) / readFile(...) / writeFile(...) / touchSession(...)
  └── each updates updatedAt and bumps expiresAt = now + ttl

GC loop (every gc.intervalSeconds)
  └── expired sessions → dropSession()
  └── orphan workspace dirs without metadata.json → removed after retentionMinutes

dropSession(sid)
  └── flock the session
  └── kill any running container labelled with this sessionId
  └── rm -rf workspace
  └── remove metadata.json
```

There is **no container** between runs. Workspace files survive. In-memory state does not.

### 8.2 Run lifecycle

```text
runCode(request)
  1. async with self._sessionLocks[sessionId]:        # FIFO queue (§9)
  2.   verify required packages ⊆ runtime pool       # else MissingDependenciesError
  3.   write request.code to /workspace/.run/<runId>/main.py
  4.   write request.files to /workspace
  5.   mkdir /workspace/.run/<runId>/
  6.   container = backend.runOneshot(ContainerSpec(
           image          = runtime.image,
           command        = runtime.runCommand(runId),    # see below
           workspaceMount = workspaceDir : /workspace : rw,
           libMount       = libPoolDir   : /sandbox/libs : ro,
           env            = runtime.baseEnv | request.env,
           limits         = request.limits or defaults,
           network        = "none" if not request.network.enabled else "bridge",
           user           = "1000:1000",
           readOnlyRoot   = True,
           capDrop        = ["ALL"],
           securityOpt    = ["no-new-privileges"],
           tmpfs          = {"/tmp": "rw,nosuid,nodev,size=64m"},
           labels         = {sandbox.managed, .sessionId, .runId, .runtime, .createdAt},
       ))
  7.   await container.wait(timeoutSeconds=request.timeoutSeconds or default)
  8.   on timeout: kill (SIGKILL), set timedOut=true
       on exit 137: set oomKilled=true (verify via container inspect)
  9.   build RunResult from container state + .run/<runId>/{stdout,stderr}.log sizes
  10.  write result.json next to the logs
  11.  remove container
  12.  bump session expiresAt
  13.  return RunResult
```

The container's command line is wrapped by the runtime so all output goes to files:

```bash
# PythonRuntime.runCommand(runId) produces, conceptually:
sh -c 'python -u /workspace/.run/<runId>/main.py \
       > /workspace/.run/<runId>/stdout.log \
       2> /workspace/.run/<runId>/stderr.log'
```

Why files instead of `docker logs`:

- Output size is bounded only at read-time (`readFile(maxBytes=…)`), not in memory.
- Works identically on future non-Docker backends (Firecracker has no `docker logs`).
- Output is naturally part of the workspace artifacts.
- Survives if the manager process crashes mid-run.

`stdin` is similarly written to a file and redirected via `<`.

### 8.3 Library install lifecycle

```text
installRuntimeLibraries(packages, runtime="python")
  1. acquire fcntl.flock on runtimes/python/pool.lock (non-blocking, raise LibraryPoolLocked)
  2. validate each package spec (PEP 508; deny shell metacharacters, deny --options)
  3. start install container:
       image       = runtime.image
       command     = ["python", "-m", "pip", "install",
                      "--target", "/sandbox/libs",
                      *("--upgrade",) if upgrade else (),
                      *packages]
       mounts      = runtimes/python/libs : /sandbox/libs : rw
       network     = "bridge"               # install needs network
       user        = "1000:1000"
       limits      = stricter timeoutSeconds, otherwise same
  4. on success: refresh metadata.json (pip freeze --path /sandbox/libs), bump poolVersion
  5. release the flock
```

The install container is the **only** place the library pool is writable. Every run container mounts the same directory **read-only**. Crash recovery (§11) re-checks the flock on startup.

Package spec validation is mandatory even for admin calls — `pip install "x; rm -rf /"` is a real attack vector.

---

## 9. Concurrency model

Per-session FIFO queue, implemented as a fair `asyncio.Lock` keyed by `sessionId`:

```python
class SessionLockRegistry:
    async def acquire(self, sessionId: str) -> AsyncContextManager:
        ...
```

- Calls to `runCode`, `resetSession`, `dropSession`, `writeFile`, `deleteFile` for the same `sessionId` serialise.
- Calls for different `sessionId`s run concurrently, bounded only by Docker capacity.
- A bounded queue length (`concurrency.maxQueuedRunsPerSession`, default 4) protects against backlogs; overflow raises `SessionBusy`.

Library pool installs use an independent `flock` per runtime, orthogonal to session locks.

Reads (`listFiles`, `readFile`, `getSessionInfo`, `listSessions`) are lock-free — they tolerate seeing a mid-run state.

---

## 10. Security model

The non-negotiables, distilled from GPT v0 §10 and §23:

| Setting | Value |
|---|---|
| `user` | `1000:1000` (configurable, never `0`) |
| `read_only` rootfs | `True` |
| `cap_drop` | `["ALL"]` |
| `security_opt` | `["no-new-privileges"]` |
| `privileged` | `False` |
| `network` | `none` by default; `bridge` only when `NetworkPolicy.enabled` |
| `mem_limit` | from `ResourceLimits.memoryMb` |
| `memswap_limit` | `== mem_limit` (no swap) |
| `pids_limit` | from `ResourceLimits.pidsLimit` |
| `nano_cpus` | from `ResourceLimits.cpuCount` |
| `devices` | `[]` |
| `tmpfs` | `/tmp` only, sized from `ResourceLimits.tmpfsSizeMb` |
| `auto_remove` | `False` (we collect artifacts before removing) |
| Docker socket mount | **forbidden** |
| Host env passthrough | **forbidden** — only allowlisted env vars + `RunRequest.env` |

Path safety:

- Every API that takes a `path` resolves it against the session workspace and rejects anything that escapes (`..`, absolute paths, symlinks pointing outside, etc.). Implemented once in `storage.py::resolveWorkspacePath`.
- The install container's `--target` is hard-coded; user-supplied paths never reach `pip`.

Package-spec safety:

- `installRuntimeLibraries` rejects specs that aren't valid PEP 508 `Requirement` objects.
- `--`-prefixed pip options in package strings are rejected.
- A `denyList` config entry (e.g., `docker`, `kubernetes`, `paramiko`) can hard-block specific names regardless of caller.

Naming / labels:

- Container name = `sandbox-py-<sessionHash[:8]>-<runId[:8]>`. Never raw user input.
- Every container/volume tagged with labels `sandbox.managed=true`, `sandbox.sessionId=<hash>`, `sandbox.runId=<id>`, `sandbox.runtime=<name>`, `sandbox.createdAt=<iso>`. GC and recovery rely on these.

---

## 11. Garbage collection & recovery

`SandboxManager.collectGarbage()` runs on a timer (default every 60s) and on demand.

GC removes:

1. Docker containers labelled `sandbox.managed=true` whose `runId` is not in the active-runs set and whose age exceeds `gc.orphanContainerRetentionMinutes`.
2. Session directories whose `metadata.expiresAt` is in the past (idle TTL) or whose `createdAt + hardTtl` is in the past.
3. Run records (`runs/index/<runId>.json` and the matching `.run/<runId>/` directories) older than `gc.runRetentionMinutes`.
4. Orphan workspace directories (no `metadata.json`) older than `gc.orphanWorkspaceRetentionMinutes`.

GC does **not** touch the library pool. Pool removal goes through `removeRuntimeLibraries`.

`SandboxManager.recover()` runs once at startup:

1. Force-release any stale `pool.lock` (flock dies with the holding process, but the file remains).
2. Enumerate Docker containers with `sandbox.managed=true` → kill+remove (no run is in-flight at startup).
3. Reconcile `sessions/*/metadata.json` against the on-disk workspace presence; orphans flagged for GC.
4. Reconcile `runtimes/python/metadata.json` against actual contents of `libs/` (`pip freeze --path`).

---

## 12. Configuration

Single typed `SandboxConfig` dataclass + TypedDicts. Loaded from a section of Gromozeka's TOML config (see [`docs/llm/configuration.md`](../llm/configuration.md)):

```toml
[sandbox]
storage_root_dir = "/var/lib/gromozeka/sandbox"
file_dir_mode    = "0700"
file_mode        = "0600"

[sandbox.backend.docker]
base_url             = "unix:///var/run/docker.sock"
image_pull_policy    = "if-not-present"
container_name_prefix = "sandbox"

[sandbox.defaults]
mode                  = "oneshot"
session_idle_ttl_min  = 30
session_hard_ttl_min  = 120
run_timeout_seconds   = 30
allow_network         = false

[sandbox.resources]
memory_mb       = 512
memory_swap_mb  = 512
cpu_count       = 1.0
pids_limit      = 64
tmpfs_size_mb   = 64

[sandbox.security]
user                    = "1000:1000"
read_only_rootfs        = true
no_new_privileges       = true
drop_capabilities       = ["ALL"]
privileged              = false
env_allowlist           = ["PYTHONUNBUFFERED", "MPLBACKEND"]

[sandbox.concurrency]
max_queued_runs_per_session = 4
max_concurrent_runs_global  = 8

[sandbox.gc]
enabled                                 = true
interval_seconds                        = 60
orphan_container_retention_minutes      = 10
orphan_workspace_retention_minutes      = 60
run_retention_minutes                   = 1440

[sandbox.runtimes.python]
image           = "gromozeka-sandbox-python:3.12"
dockerfile      = "lib/sandbox/runtimes/python/Dockerfile"
workdir         = "/workspace"
lib_mount_path  = "/sandbox/libs"
deny_packages   = ["docker", "kubernetes", "paramiko", "scapy"]

[sandbox.runtimes.python.env]
PYTHONUNBUFFERED       = "1"
PYTHONDONTWRITEBYTECODE = "1"
MPLBACKEND             = "Agg"
PYTHONPATH             = "/sandbox/libs"

[sandbox.runtimes.python.install_container]
timeout_seconds = 600
allow_network   = true
```

Defaults live in [`configs/00-defaults/sandbox.toml`](../../configs/00-defaults/) per the project's config layering rules.

---

## 13. Python runtime details

### 13.1 Dockerfile

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MPLBACKEND=Agg

RUN useradd -m -u 1000 sandbox \
 && mkdir -p /workspace /sandbox/libs \
 && chown -R sandbox:sandbox /workspace /sandbox

USER sandbox
WORKDIR /workspace
ENV PATH="/home/sandbox/.local/bin:${PATH}"
ENV PYTHONPATH="/sandbox/libs"
CMD ["python"]
```

No packages baked in. The lib pool starts empty and is populated by `installRuntimeLibraries`. Operators bootstrapping a new install run e.g.:

```python
await manager.installRuntimeLibraries(
    ["numpy", "pandas", "matplotlib", "scipy", "sympy", "scikit-learn", "pillow"],
    runtime="python",
)
```

(Reason for empty default: keeps the image cheap, keeps the pool fully visible/auditable in metadata, avoids divergence between "what's in the image" and "what `freeze` reports".)

### 13.2 PythonRuntime

```python
class PythonRuntime:
    name: str = "python"

    def runCommand(self, runId: str, *, hasStdin: bool) -> list[str]:
        redirects = (
            f"> /workspace/.run/{runId}/stdout.log "
            f"2> /workspace/.run/{runId}/stderr.log"
        )
        stdinPart = f"< /workspace/.run/{runId}/stdin" if hasStdin else ""
        return [
            "sh", "-c",
            f"python -u /workspace/.run/{runId}/main.py {stdinPart} {redirects}",
        ]

    def installCommand(self, packages: Sequence[str], *, upgrade: bool) -> list[str]:
        cmd = ["python", "-m", "pip", "install", "--target", "/sandbox/libs",
               "--no-cache-dir", "--no-input"]
        if upgrade:
            cmd.append("--upgrade")
        cmd.extend(packages)
        return cmd

    def freezeCommand(self) -> list[str]:
        return ["python", "-m", "pip", "list", "--format=json",
                "--path", "/sandbox/libs"]

    def detectArtifacts(self, workspacePath: Path, *, sinceMtime: float) -> list[ArtifactInfo]:
        ...  # walks workspace excluding .run/, returns files newer than sinceMtime
```

---

## 14. Backend interface

```python
class SandboxBackend(Protocol):
    name: str

    async def healthcheck(self) -> HealthcheckResult: ...

    async def ensureImage(self, runtime: RuntimeInfo, *, rebuild: bool) -> ImageInfo: ...

    async def runOneshot(self, spec: ContainerSpec) -> ContainerOutcome:
        """Run a container to completion and return the outcome.
        Does NOT remove the container — caller collects artifacts first.
        """

    async def removeContainer(self, containerId: str, *, force: bool = True) -> None: ...

    async def killContainer(self, containerId: str, *, signal: str = "SIGKILL") -> None: ...

    async def inspectContainer(self, containerId: str) -> dict[str, Any]:
        """For OOM detection (`State.OOMKilled`) and similar."""

    async def listManagedContainers(self) -> list[ManagedContainerInfo]: ...
```

`DockerBackend` uses `aiodocker`. The `ContainerSpec` dataclass is intentionally close to the Docker API to avoid lossy translation; backends that don't map 1:1 (e.g., Firecracker) reject unsupported fields explicitly.

---

## 15. Integration with Gromozeka

### 15.1 The adapter

`internal/services/sandbox/service.py` exposes:

```python
class SandboxService:
    @classmethod
    def getInstance(cls) -> "SandboxService": ...

    async def runCodeForChat(
        self,
        chatId: ChatId,
        threadId: ThreadId,
        code: str,
        *,
        requiredPackages: Sequence[str] = (),
        timeoutSeconds: int | None = None,
        allowNetwork: bool = False,
    ) -> RunResult: ...
```

It owns the `chatId+threadId → sessionId` mapping (`f"chat-{chatId}-thread-{threadId}"`), reads the merged Gromozeka config via `ConfigManager`, and calls the underlying `SandboxManager`.

This is the boundary where the bot-facing concerns (rate-limiting, admin checks for `installRuntimeLibraries`, per-chat allowlists, audit logging) belong — **not** in `lib/sandbox/`.

### 15.2 Handlers (out of scope for v0 implementation but worth noting)

A `RunPythonHandler` (or an LLM tool) calls `SandboxService.runCodeForChat(...)`, formats the `RunResult` (reading `stdoutPath` via `readFile(maxBytes=...)`) into a message, and sends it. Adheres to:

- `LLMMessageHandler` stays last in the handler list ([`AGENTS.md`](../../AGENTS.md)).
- Admin-only library install commands are gated on `bot_owners` checks.

---

## 16. Testing strategy

Per [`docs/llm/testing.md`](../llm/testing.md):

1. **Unit tests** for everything that doesn't touch Docker:
   - `storage.py::resolveWorkspacePath` (path traversal, symlink escapes)
   - Package spec validation
   - `SessionLockRegistry` ordering
   - GC decision logic against synthetic file trees
   - Config loading + defaults merge

2. **Integration tests** marked `@pytest.mark.slow` and gated on `DOCKER_AVAILABLE`:
   - End-to-end `runCode("print(2 + 2)")` returns exit 0, stdout `4\n`.
   - Timeout enforcement (`while True: pass` → `timedOut=True`).
   - OOM detection (`x = b"\0" * (1<<30)` → `oomKilled=True`).
   - Network off: `requests.get(...)` fails.
   - Required-packages missing: `MissingDependenciesError` raised, container never starts.
   - Workspace persistence: write file in run 1, read in run 2.
   - Library RO: attempt to write into `/sandbox/libs` from user code → `PermissionError`.
   - Session FIFO ordering under concurrent submissions.
   - GC removes expired sessions but leaves the library pool intact.
   - `recover()` reaps a deliberately leaked container.

3. **Property tests** for path resolution and session-id hashing (no UTF-8 oddities corrupt the layout).

`testpaths` already includes `lib/` ([`pyproject.toml`](../../pyproject.toml)); tests live at `lib/sandbox/tests/`.

---

## 17. Milestones

### M1 — Skeleton (no behaviour)

- Package layout under `lib/sandbox/`
- All TypedDicts/dataclasses in `types.py`
- `errors.py`
- `SandboxBackend` and `Runtime` Protocols
- Stubs for `SandboxManager` returning `NotImplementedError`
- Initial `configs/00-defaults/sandbox.toml`
- Unit tests for `types.py` round-trips and config loading

### M2 — Storage + lifecycle (no Docker)

- `storage.py`: directory layout, sessionHash, atomic metadata writes, path resolver
- `locks.py`: per-session lock, library pool flock
- `SandboxManager.createSession / getSessionInfo / listSessions / touchSession / resetSession / dropSession`
- File API: `listFiles / readFile / writeFile / deleteFile`
- GC for orphan workspaces
- Unit + property tests; **no Docker yet**

### M3 — Docker backend + Python runtime

- `DockerBackend` (`aiodocker`)
- `PythonRuntime` + Dockerfile
- `prepareRuntime`, `installRuntimeLibraries`, `removeRuntimeLibraries`, `listRuntimeLibraries`, `freezeRuntimeLibraries`
- `runCode` end-to-end (oneshot container, stdout/stderr to files, artifact detection)
- Integration tests gated on `DOCKER_AVAILABLE`
- `healthcheck`, `recover`, `collectGarbage`, `shutdown`

### M4 — Gromozeka integration (separate change set)

- `internal/services/sandbox/service.py` adapter + singleton
- Config wiring through `ConfigManager`
- Admin handler for library installs
- `RunPythonHandler` (or LLM tool integration)
- Docs sync: [`docs/llm/services.md`](../llm/services.md), [`docs/llm/libraries.md`](../llm/libraries.md), [`docs/llm/configuration.md`](../llm/configuration.md), [`docs/llm/handlers.md`](../llm/handlers.md) per the `update-project-docs` skill

### M5 — Future (deliberately out of scope)

- TypeScript runtime
- Firecracker / gVisor backends
- Network proxy / allowlist policy
- `cancelRun` + asynchronous submit/poll API
- Persistent (long-lived) execution mode

---

## 18. Documentation impact

Once M3 lands:

- New: [`docs/llm/libraries.md`](../llm/libraries.md) section "Sandbox" pointing to `lib/sandbox/`.
- New: [`docs/llm/configuration.md`](../llm/configuration.md) section for `[sandbox.*]` keys.
- New: [`docs/developer-guide.md`](../developer-guide.md) entry on how to bootstrap the library pool on a fresh install.

Once M4 lands:

- [`docs/llm/services.md`](../llm/services.md): add `SandboxService`.
- [`docs/llm/handlers.md`](../llm/handlers.md): add the new handler(s).
- [`docs/llm/architecture.md`](../llm/architecture.md): one paragraph + diagram update.
- [`AGENTS.md`](../../AGENTS.md): add `lib/sandbox/` to the layout cheatsheet and a sandbox-specific gotcha (e.g., the "stdout/stderr live in workspace files, not in `RunResult` bytes" surprise).

No database schema changes — the sandbox is filesystem-backed.

---

## 19. Open questions for follow-up

1. **Bootstrap UX.** How does an operator on a fresh deployment install the initial library set? Options:
   - Hard-coded "starter pack" config that runs at first `prepareRuntime`.
   - A `make sandbox-bootstrap` target.
   - Manual `installRuntimeLibraries` admin call.
   Suggested: operator-driven, but ship a starter-pack list in the default config the operator can opt into.

2. **Library deny-list discoverability.** Should `installRuntimeLibraries` validate transitive dependencies against the deny-list, or only direct requests? Suggested: only direct (transitive validation requires resolving the dependency graph before install — expensive and pip-version dependent).

3. **Workspace size monitoring.** No disk quota by user choice, but a non-enforcing "current workspace size" metric on `SessionInfo` is cheap and useful for ops dashboards.

4. **Run history retention semantics.** `gc.runRetentionMinutes` deletes `.run/<runId>/` directories — including their stdout/stderr logs. Is that the desired behaviour, or should logs be retained longer than the directory? Suggested: keep it simple — run record == its directory == deleted together. Operators wanting longer retention bump the config.

5. **Concurrency cap interaction.** `concurrency.maxConcurrentRunsGlobal` is a global semaphore on top of per-session locks. Behaviour when the global cap is full: queue or reject? Suggested: queue with a timeout, raise `SandboxBusy` after.

6. **What happens to a session if its runtime is reconfigured?** E.g., admin upgrades `numpy` from 2.0 → 2.1. Existing sessions immediately see the new version on the next run. Acceptable? Suggested: yes, with `RunResult.libPoolVersion` exposed so callers can detect drift.

These are tractable post-M3 decisions; none of them block the design.
