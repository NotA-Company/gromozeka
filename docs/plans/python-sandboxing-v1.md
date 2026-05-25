# Sandboxed Code Execution — Design v1

Status: **proposed design, no code yet**
Supersedes: [`python-sandboxing-v0.gpt.md`](python-sandboxing-v0.gpt.md), [`python-sandboxing-v0.gemini.md`](python-sandboxing-v0.gemini.md)
Companion: [`python-sandboxing-v1-integration.md`](python-sandboxing-v1-integration.md) (Gromozeka-specific wiring)
Scope: design-only. Implementation will be staged separately.

This document covers the **standalone, language- and bot-agnostic sandbox library** living under [`lib/sandbox/`](../../lib/). Gromozeka integration (adapter service, handlers, config wiring) is split out into the companion doc.

---

## 1. Goals & non-goals

### Goals

1. Safely execute untrusted, LLM-generated Python code on the host running Gromozeka.
2. Preserve workspace files across runs within a logical "session".
3. Allow a curated, shared, mutable set of Python libraries per runtime, controlled by an admin — never by the LLM or end user.
4. Enforce hard CPU / RAM / PID / timeout / network limits on every run.
5. Expose a typed, async, language-agnostic API that can be extended to TypeScript, Bash, etc. without API churn.
6. Be reusable: no Gromozeka-specific types in the library itself ([`lib/` no-bot-deps rule](../../AGENTS.md)).

### Non-goals (v0)

- Non-Docker backends (gVisor, Firecracker, Kubernetes Jobs). `SandboxBackend` Protocol exists; only `DockerBackend` is implemented.
- Non-Python runtimes. `Runtime` Protocol exists; only `PythonRuntime` is implemented.
- Network proxy / domain allowlist. `NetworkPolicy` has only `enabled: bool` today.
- Persistent (long-lived) execution containers. Workspace is persistent; the container is not.
- Per-session library installation. Libraries are runtime-scoped.
- Disk quotas, artifact size caps, in-memory output caps. Dedicated volume + read-time caps.
- Package deny-lists. Operator is trusted not to install dangerous packages.
- LLM policy decisions (which code can run, rate-limiting). Lives in the calling tool, not in the library.

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
| **Workspace** | The session's writable directory mounted RW into every run container at `/workspace`. |
| **Metadata store** | Pluggable persistence for session / run / pool records. v0 = filesystem JSON. Future = database. |

---

## 3. High-level architecture

```text
                  ┌────────────────────────────────────────────────┐
                  │              SandboxManager (public)           │
                  │   sessions • runs • libs • files • GC • health │
                  └──────────────────┬─────────────────────────────┘
                                     │
        ┌──────────────────┬─────────┼──────────────────┬──────────────────┐
        │                  │         │                  │                  │
   ┌────▼─────┐    ┌───────▼──┐    ┌─▼──────────────┐  ┌─▼──────────────┐  ┌─▼─────────┐
   │ Backend  │    │ Runtime  │    │ MetadataStore  │  │ Storage layout │  │ Lock      │
   │(Protocol)│    │(Protocol)│    │  (Protocol)    │  │  (host FS)     │  │ registry  │
   │          │    │          │    │                │  │                │  │           │
   │ Docker   │    │ Python   │    │ Filesystem v0  │  │ workspaces +   │  │ FIFO per  │
   │ Backend  │    │ Runtime  │    │ Database later │  │ run logs       │  │ session   │
   └──────────┘    └──────────┘    └────────────────┘  └────────────────┘  └───────────┘
```

Four orthogonal axes:

1. **Backend** = how to run a container.
2. **Runtime** = which language / image / packaging tool.
3. **Metadata store** = where session/run/pool records live (FS today, DB tomorrow).
4. **Storage** = where workspace files and run logs live on the host.

`SandboxManager` is the singleton entry point, composes one Backend with N Runtimes and one MetadataStore, owns the per-session lock registry and the GC loop.

---

## 4. Repository layout

Following the [`AGENTS.md`](../../AGENTS.md) layering rules:

```text
lib/
  sandbox/
    __init__.py                  # public re-exports
    manager.py                   # SandboxManager (singleton via getInstance())
    types.py                     # dataclasses, enums, TypedDicts for the public API
    enums.py                     # RuntimeName, BackendName StrEnums
    errors.py                    # SandboxError hierarchy
    locks.py                     # per-session FIFO lock + global concurrency semaphore
    storage.py                   # host directory layout, path resolution, hashing
    metadata/
      __init__.py
      base.py                    # MetadataStore Protocol
      filesystem.py              # FilesystemMetadataStore
    gc.py                        # GarbageCollector
    backends/
      __init__.py
      base.py                    # SandboxBackend Protocol
      docker.py                  # DockerBackend (aiodocker)
    runtimes/
      __init__.py
      base.py                    # Runtime Protocol
      python/
        __init__.py
        runtime.py               # PythonRuntime
        Dockerfile               # python:3.12-alpine, run image
        Dockerfile.install       # python:3.12-alpine + build toolchain, install image
    tests/                       # collocated per AGENTS.md tests rule
```

The Gromozeka-specific adapter lives outside this tree — see the [integration doc](python-sandboxing-v1-integration.md).

---

## 5. Public API

All methods are `async`. Naming is **camelCase**, classes **PascalCase** per project rules. No pydantic — `@dataclass(slots=True)` and `StrEnum`.

### 5.1 Manager singleton

```python
class SandboxManager:
    @classmethod
    def getInstance(cls, config: SandboxConfig | None = None) -> "SandboxManager":
        ...

    async def healthcheck(self) -> HealthcheckResult: ...
    async def shutdown(self, *, cleanVolumes: bool = False) -> ShutdownResult: ...
    async def recover(self) -> RecoveryResult: ...
    async def collectGarbage(self) -> GcResult: ...
```

Initialised once at startup with `SandboxConfig`. Subsequent `getInstance()` calls return the same instance — matches Gromozeka's singleton pattern.

### 5.2 Runtime / image management

```python
async def prepareRuntime(
    self,
    runtime: RuntimeName = RuntimeName.PYTHON,
    *,
    rebuildImage: bool = False,
) -> RuntimeInfo: ...

async def listRuntimes(self) -> list[RuntimeInfo]: ...
```

`prepareRuntime` ensures the run image and install image are present (builds if missing or `rebuildImage=True`) and ensures the library pool directory exists.

### 5.3 Sessions

```python
async def createSession(
    self,
    sessionId: str,
    *,
    runtime: RuntimeName = RuntimeName.PYTHON,
    forceRecreate: bool = False,
    ttlMinutes: int | None = None,
    limits: ResourceLimits | None = None,
    metadata: dict[str, str] | None = None,
) -> SessionInfo: ...

async def getSessionInfo(self, sessionId: str) -> SessionInfo | None: ...
async def getSessionUsage(self, sessionId: str) -> SessionUsage: ...
async def listSessions(self, *, runtime: RuntimeName | None = None) -> list[SessionInfo]: ...
async def touchSession(self, sessionId: str, *, ttlMinutes: int | None = None) -> SessionInfo: ...
async def dropSession(self, sessionId: str, *, force: bool = False) -> DropSessionResult: ...
```

- `createSession` is idempotent unless `forceRecreate=True`. It allocates the workspace directory and writes the session record; no container is created here.
- `getSessionUsage` walks the workspace and returns size/file-count. Separate from `getSessionInfo` because it's potentially expensive on large workspaces — callers pay for it explicitly.
- `dropSession(force=False)`: queues behind any in-flight runs (FIFO), drops once they finish.
- `dropSession(force=True)`: SIGKILLs the running container if any, drains the queue (waiters get `SessionDropped`), then drops.

There is no `resetSession`. Caller does `dropSession + createSession` instead.

### 5.4 Runs

```python
async def runCode(
    self,
    sessionId: str,
    code: str,
    *,
    runtime: RuntimeName = RuntimeName.PYTHON,
    timeoutSeconds: int | None = None,
    requiredPackages: Sequence[str] = (),
    network: NetworkPolicy | None = None,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    files: Sequence[InputFile] = (),
    limits: ResourceLimits | None = None,
) -> RunResult: ...

async def cancelRun(self, runId: str) -> bool: ...
async def getRunInfo(self, runId: str) -> RunInfo | None: ...
async def listRunsForSession(self, sessionId: str) -> list[RunInfo]: ...
```

**Auto-creation**: if `sessionId` doesn't exist, `runCode` creates it with config defaults (default runtime, default TTL, default limits). Caller can pre-create with non-default settings via `createSession`.

**Required-package handling**: if any package in `requiredPackages` is missing from the runtime's library pool, `runCode` raises `MissingDependenciesError(missing=[...])` **without starting the container**. The bot tool layer translates that into a user-facing "ask the admin to install" message.

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

`maxBytes` on `readFile` is the **only** place output is bounded. stdout/stderr live as `/workspace/.run/<runId>/stdout.log` and `/workspace/.run/<runId>/stderr.log` (see §8.2).

All paths resolve relative to the session workspace; absolute paths, `..` escapes, and symlinks pointing outside the workspace are rejected with `PathOutsideWorkspace`.

### 5.6 Library pool (admin API)

```python
async def listRuntimeLibraries(
    self,
    runtime: RuntimeName = RuntimeName.PYTHON,
) -> list[PackageInfo]: ...

async def installRuntimeLibraries(
    self,
    packages: Sequence[str],
    *,
    runtime: RuntimeName = RuntimeName.PYTHON,
    upgrade: bool = False,
    timeoutSeconds: int = 600,
) -> LibraryInstallResult: ...

async def removeRuntimeLibraries(
    self,
    packages: Sequence[str],
    *,
    runtime: RuntimeName = RuntimeName.PYTHON,
) -> LibraryRemoveResult: ...
```

These are the **only** APIs that mutate the library pool, protected by a process-wide install lock per runtime (§9). They run a **dedicated install container** (writable target, network enabled). Intended to be called from an admin/operator surface — never from `runCode` or LLM tools.

A `pip freeze` snapshot of the pool is refreshed inside the install container after every successful install/remove and persisted via the metadata store. This serves as the migration/audit format — callers who need a requirements.txt can build it from `listRuntimeLibraries()`.

---

## 6. Data model

All types live in `lib/sandbox/types.py` (and `enums.py`). `@dataclass(slots=True)`, frozen where it makes sense. Python types only.

### 6.1 Enums

```python
class RuntimeName(StrEnum):
    PYTHON = "python"
    # Future: TYPESCRIPT = "typescript", BASH = "bash"

class BackendName(StrEnum):
    DOCKER = "docker"
    # Future: GVISOR = "gvisor", FIRECRACKER = "firecracker"
```

Every public method that takes a runtime/backend selector uses these enums.

### 6.2 Inputs

```python
@dataclass(slots=True, frozen=True)
class NetworkPolicy:
    enabled: bool = False
    # Reserved for future: mode, allowedHosts, proxyUrl

@dataclass(slots=True, frozen=True)
class ResourceLimits:
    memoryMb: int = 512
    memorySwapMb: int | None = 512        # equal to memoryMb disables swap
    cpuCount: float = 1.0
    pidsLimit: int = 64
    timeoutSeconds: int = 30
    timeoutGraceSeconds: int = 5          # SIGTERM grace before SIGKILL

@dataclass(slots=True, frozen=True)
class InputFile:
    path: str                              # relative to /workspace
    content: bytes | str
    overwrite: bool = True
```

### 6.3 Outputs

```python
@dataclass(slots=True)
class SessionInfo:
    sessionId: str
    runtime: RuntimeName
    workspacePath: str                     # host path, for ops/debugging
    createdAt: datetime
    updatedAt: datetime
    expiresAt: datetime
    metadata: dict[str, str]               # opaque caller-controlled

@dataclass(slots=True)
class SessionUsage:
    sessionId: str
    fileCount: int
    totalBytes: int
    runCount: int
    measuredAt: datetime

@dataclass(slots=True)
class RunInfo:
    runId: str
    sessionId: str
    runtime: RuntimeName
    startedAt: datetime
    finishedAt: datetime | None
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    exitCode: int | None

@dataclass(slots=True)
class RunResult:
    runId: str
    sessionId: str
    runtime: RuntimeName
    stdoutPath: str                        # relative workspace path
    stderrPath: str
    stdoutBytes: int                       # full size on disk
    stderrBytes: int
    exitCode: int | None
    signal: str | None
    timedOut: bool
    oomKilled: bool
    startedAt: datetime
    finishedAt: datetime
    elapsedMs: int
    newArtifacts: list[ArtifactInfo]       # files appearing/changing during the run
    limits: ResourceLimits
    networkEnabled: bool                   # what the run actually got
    libPoolVersion: str                    # see §7
    error: str | None

@dataclass(slots=True)
class ArtifactInfo:
    path: str                              # relative to workspace
    sizeBytes: int
    modifiedAt: datetime
    mimeType: str | None
    sha256: str | None

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
    runtime: RuntimeName
    installed: list[PackageInfo]
    skipped: list[str]
    failed: list[tuple[str, str]]          # (package, reason)
    poolVersion: str                       # sha256 of sorted (name, version) tuples

@dataclass(slots=True)
class LibraryRemoveResult:
    runtime: RuntimeName
    removed: list[str]
    notFound: list[str]
    poolVersion: str

@dataclass(slots=True)
class DropSessionResult:
    sessionId: str
    existed: bool
    runsCancelled: int
    errors: list[str]

@dataclass(slots=True)
class HealthcheckResult:
    ok: bool
    backend: dict[str, Any]
    runtimes: dict[str, dict[str, Any]]
    storage: dict[str, Any]
    errors: list[str]

@dataclass(slots=True)
class GcResult:
    removedContainers: int
    removedSessions: int
    removedRuns: int
    removedOrphans: int
    errors: list[str]

@dataclass(slots=True)
class RecoveryResult:
    reapedContainers: int
    releasedLocks: int
    reconciledPools: int
    errors: list[str]

@dataclass(slots=True)
class RuntimeInfo:
    name: RuntimeName
    runImageTag: str
    installImageTag: str
    libPoolPath: str
    libPoolVersion: str
    packageCount: int
```

### 6.4 Errors

```text
SandboxError                                # base
  ConfigError
  BackendError
    DockerUnavailable
    ImageNotFound
    ImageBuildFailed
  SessionError
    SessionNotFound
    SessionBusy                             # FIFO queue cap reached
    SessionDropped                          # raised at waiters during force-drop
  RuntimeError
    UnknownRuntime
    MissingDependenciesError(missing=[...])
  RunError
    RunTimedOut
    RunOomKilled
    RunCancelled
  LibraryError
    LibraryInstallFailed
    LibraryPoolLocked
    InvalidPackageSpec
  FileError
    PathOutsideWorkspace
  SandboxBusy                               # global concurrency cap reached
```

---

## 7. Storage layout

Single configurable `storage.rootDir` (default `/var/lib/gromozeka/sandbox`). Operator points it at a dedicated volume/device of sufficient size. The library has no quota or size enforcement.

```text
${storage.rootDir}/
  runtimes/
    python/
      libs/                                 # the lib pool — RO into sessions
      pool.lock                             # fcntl flock during install
      requirements.txt                      # pip freeze snapshot (refreshed on every install)
      image.tag                             # last built run image tag
      install_image.tag                     # last built install image tag
  sessions/
    <sessionHash>/                          # sha256(sessionId), full 64 hex chars
      workspace/                            # mounted RW into runs as /workspace
        ... user files ...
        .run/
          <runId>/
            main.py                         # the submitted code
            stdin                           # if provided
            stdout.log
            stderr.log
            result.json                     # snapshot of RunResult
  meta/                                     # FilesystemMetadataStore home
    sessions/<sessionHash>.json
    runs/<runId>.json
    runtimes/<runtimeName>.json
  tmp/                                      # scratch for atomic writes
```

UID/GID: every directory is owned by the same non-root user the sandbox containers run as (default `1000:1000`, configurable). The library pool, install image, and run image all use this UID, so the RO mount works trivially.

`sessionHash = sha256(sessionId).hexdigest()` — full 64-char hex. Workspace dir names are filesystem-safe and stable.

`pool.lock` is a real `fcntl.flock` on the file — it survives process restart and protects against a crashed install leaving the pool inconsistent.

`poolVersion = sha256(sorted("{name}=={version}" for each installed package)).hexdigest()`. Returned by every install/remove and stamped on each `RunResult` so callers can detect drift.

---

## 8. Lifecycles

### 8.1 Session lifecycle

```text
createSession(sid)
  └── if record exists and not forceRecreate: load, return reused=true
  └── else: mkdir workspace, write metadata, return reused=false

runCode(sid, ...)
  └── if record doesn't exist: implicit createSession(sid) with config defaults
  └── proceed to run

readFile / writeFile / touchSession / runCode
  └── each updates updatedAt and bumps expiresAt = now + idleTtl

GC loop (every gc.intervalSeconds)
  └── expired sessions → dropSession()
  └── orphan workspace dirs without metadata record → removed after retention

dropSession(sid, force=False)
  └── acquire session lock (waits for in-flight run)
  └── delete workspace, delete metadata, drain (empty) queue

dropSession(sid, force=True)
  └── kill running run container (if any) via label lookup
  └── all waiters in queue receive SessionDropped
  └── delete workspace, delete metadata
```

No container exists between runs. Workspace files survive. In-memory state does not.

### 8.2 Run lifecycle

```text
runCode(sid, code, ...)
  1. async with sessionLock(sid):                          # FIFO queue (§9)
  2.   async with globalRunSemaphore:                      # global concurrency cap
  3.     ensure session exists (autocreate with defaults if missing)
  4.     runId = uuid4().hex
  5.     verify requiredPackages ⊆ runtime pool            # else MissingDependenciesError
  6.     mkdir /workspace/.run/<runId>/
  7.     write main.py, optional stdin, optional input files
  8.     containerSpec = ContainerSpec(
              name           = f"sandbox-{runId}",
              image          = runtime.runImageTag,
              command        = runtime.runCommand(runId, hasStdin, limits),
              mounts         = [
                                workspaceDir : /workspace : rw,
                                libPoolDir   : /sandbox/libs : ro,
                               ],
              env            = runtime.baseEnv | requestEnv,
              limits         = limits or defaults,
              network        = "none" if not network.enabled else "bridge",
              user           = config.security.user,
              readOnlyRoot   = True,
              capDrop        = ["ALL"],
              securityOpt    = ["no-new-privileges"],
              labels         = {
                                sandbox.managed   : "true",
                                sandbox.runId     : runId,
                                sandbox.sessionId : sessionHash,
                                sandbox.runtime   : runtime.value,
                                sandbox.createdAt : iso8601,
                               },
          )
  9.     write RunInfo(status="running") via metadata store
 10.     outcome = await backend.runOneshot(containerSpec)
 11.     if outcome.exitCode == 124: timedOut = True
         if outcome.inspect.State.OOMKilled: oomKilled = True
 12.     read sizes of stdout.log, stderr.log; detect new artifacts
 13.     build RunResult; write result.json + RunInfo(status="completed")
 14.     await backend.removeContainer(containerId)
 15.   bump session expiresAt
 16. return RunResult
```

The container's command line is built by the runtime so all output goes to files **and** the whole pipeline is wrapped in `timeout(1)` for defense in depth:

```bash
# PythonRuntime.runCommand(runId, hasStdin, limits) produces:
timeout -s TERM -k 5 30 sh -c '
  python -u /workspace/.run/<runId>/main.py \
    < /workspace/.run/<runId>/stdin \
    > /workspace/.run/<runId>/stdout.log \
    2> /workspace/.run/<runId>/stderr.log
'
```

(The `< stdin` redirection is omitted when no stdin is provided. The `30` is `limits.timeoutSeconds`; `5` is `limits.timeoutGraceSeconds`.)

The `timeout` wrapper:
- Sends `SIGTERM` after `timeoutSeconds`, then `SIGKILL` after `timeoutGraceSeconds`.
- Exits with code **124** on timeout — we detect that distinctly from a normal non-zero exit.
- Belt-and-braces: the backend also enforces its own wait deadline (Docker `wait` timeout). Both must agree.

Why files instead of `docker logs`:

- Output size bounded only at read-time via `readFile(maxBytes=…)` — never held in memory.
- Works identically on future non-Docker backends (Firecracker has no `docker logs`).
- Output is naturally part of workspace artifacts.
- Survives if the manager process crashes mid-run; `recover()` can still gather it.

### 8.3 Library install lifecycle

```text
installRuntimeLibraries(packages, runtime=PYTHON)
  1. acquire fcntl.flock on runtimes/python/pool.lock (non-blocking → LibraryPoolLocked)
  2. validate each spec: parse as PEP 508 Requirement; reject anything with shell metacharacters or "--" prefix
  3. containerSpec = ContainerSpec(
        name        = f"sandbox-{uuid4().hex}",
        image       = runtime.installImageTag,            # alpine + build toolchain
        command     = ["python", "-m", "pip", "install",
                       "--target", "/sandbox/libs",
                       "--no-cache-dir", "--no-input",
                       *(("--upgrade",) if upgrade else ()),
                       *packages],
        mounts      = libPoolDir : /sandbox/libs : rw,
        network     = "bridge",                            # install needs internet
        user        = config.security.user,
        readOnlyRoot= True,                                # only the lib mount is writable
        capDrop     = ["ALL"],
        securityOpt = ["no-new-privileges"],
        limits      = ResourceLimits(
                        memoryMb = 1024,                   # builds need RAM
                        timeoutSeconds = 600,
                        pidsLimit = 256,
                      ),
        labels      = { sandbox.managed: "true",
                        sandbox.purpose: "install",
                        sandbox.runtime: runtime.value, },
     )
  4. run, wait, collect output
  5. on success:
       run `pip list --format=json --path /sandbox/libs` in another short-lived container
       write requirements.txt snapshot to runtimes/python/requirements.txt
       update runtime metadata record + poolVersion via metadata store
  6. remove container
  7. release flock
```

Validation: package specs are parsed with `packaging.requirements.Requirement`. Failure → `InvalidPackageSpec`. Strings containing `;`, `&&`, `|`, `\``, `$(`, or starting with `-` are rejected before parsing as a belt-and-braces measure.

The install container has the build toolchain (`build-base`, `linux-headers`, `gcc`, `gfortran` for scipy, `openssl-dev`, `libffi-dev`) so source builds work when `musllinux` wheels aren't available for a given package on Alpine. The **run** image stays minimal.

---

## 9. Concurrency model

Two distinct locks/semaphores:

1. **Per-session FIFO lock** (`SessionLockRegistry` in `locks.py`): `asyncio.Lock` keyed by `sessionId`. Calls to `runCode`, `dropSession(force=False)`, `writeFile`, `deleteFile` for the same session serialise in arrival order. A bounded waiter count (`concurrency.maxQueuedRunsPerSession`, default 4) raises `SessionBusy` on overflow.

2. **Global run semaphore** (`concurrency.maxConcurrentRunsGlobal`, default 8): bounds total in-flight runs across all sessions. Overflow raises `SandboxBusy` after `concurrency.globalQueueWaitSeconds`.

3. **Per-runtime library install flock**: `fcntl.flock` on `pool.lock`. Independent of session locks. Survives process restart. Held only during install/remove operations.

Reads (`listFiles`, `readFile`, `getSessionInfo`, `getSessionUsage`, `listSessions`, `listRuntimeLibraries`) are lock-free — they tolerate seeing mid-run state.

`dropSession(force=True)` bypasses the FIFO lock: it cancels in-flight work and notifies waiters via `SessionDropped`.

---

## 10. Security model

The non-negotiables:

| Setting | Run container | Install container |
|---|---|---|
| `user` | `1000:1000` (configurable, never `0`) | same |
| `read_only` rootfs | `True` | `True` |
| `cap_drop` | `["ALL"]` | `["ALL"]` |
| `security_opt` | `["no-new-privileges"]` | `["no-new-privileges"]` |
| `privileged` | `False` | `False` |
| `network` | `none` by default; `bridge` only when `NetworkPolicy.enabled` | `bridge` (required) |
| `mem_limit` | from `ResourceLimits.memoryMb` | install-specific (default 1024 MB) |
| `memswap_limit` | `== mem_limit` (no swap) | same |
| `pids_limit` | from `ResourceLimits.pidsLimit` | install-specific (default 256) |
| `nano_cpus` | from `ResourceLimits.cpuCount` | install-specific |
| `devices` | `[]` | `[]` |
| `auto_remove` | `False` (collect artifacts first) | `False` |
| Docker socket mount | **forbidden** | **forbidden** |
| Host env passthrough | **forbidden** — allowlist + `RunRequest.env` only | **forbidden** |

Path safety:

- Every API taking a `path` resolves it against the session workspace via `storage.resolveWorkspacePath(...)` and rejects anything escaping (absolute paths, `..`, symlinks pointing outside).
- Install `--target` is hard-coded; user-supplied paths never reach `pip`.

Package-spec safety:

- `installRuntimeLibraries` rejects specs that aren't valid PEP 508 `Requirement`s.
- Specs containing shell metacharacters or starting with `-` are rejected pre-parse.

Naming / labels:

- Container name = `sandbox-<runId|installUuid>`. Never raw user input.
- Every container labelled `sandbox.managed=true`, `sandbox.runId=...` (or `sandbox.purpose=install`), `sandbox.sessionId=<hash>`, `sandbox.runtime=<name>`, `sandbox.createdAt=<iso>`. GC and recovery rely on these.

---

## 11. Metadata store

`lib/sandbox/metadata/base.py`:

```python
class MetadataStore(Protocol):
    async def loadSession(self, sessionId: str) -> SessionRecord | None: ...
    async def saveSession(self, record: SessionRecord) -> None: ...
    async def deleteSession(self, sessionId: str) -> None: ...
    async def listSessions(
        self, *, runtime: RuntimeName | None = None
    ) -> list[SessionRecord]: ...

    async def loadRun(self, runId: str) -> RunRecord | None: ...
    async def saveRun(self, record: RunRecord) -> None: ...
    async def deleteRun(self, runId: str) -> None: ...
    async def listRunsForSession(self, sessionId: str) -> list[RunRecord]: ...

    async def loadRuntime(self, runtime: RuntimeName) -> RuntimeRecord | None: ...
    async def saveRuntime(self, record: RuntimeRecord) -> None: ...
```

`SessionRecord` / `RunRecord` / `RuntimeRecord` are the persisted forms of the public dataclasses — they may carry extra bookkeeping (`schemaVersion`, internal flags) not exposed via the public API.

v0 implementation: `FilesystemMetadataStore` writes JSON files atomically under `${rootDir}/meta/`. Atomicity via write-temp-and-rename in `${rootDir}/tmp/`.

Future: `DatabaseMetadataStore` (likely on Gromozeka's existing `Database`) — a new file under `lib/sandbox/metadata/`, no changes to anything else.

The workspace files (`/workspace/...`, `.run/<runId>/...`) stay on disk regardless of metadata backend. Only the metadata layer migrates.

---

## 12. Garbage collection & recovery

### 12.1 `collectGarbage()`

Runs on a timer (default 60s) and on demand. Removes:

1. Docker containers labelled `sandbox.managed=true` whose `runId` is not in the active-runs set and whose age exceeds `gc.orphanContainerRetentionMinutes`.
2. Sessions whose `expiresAt < now` (idle TTL) or whose `createdAt + hardTtl < now`.
3. Run records (metadata + the entire `.run/<runId>/` directory, including stdout/stderr logs) older than `gc.runRetentionMinutes`. Deleted as a unit.
4. Orphan workspace directories (no metadata record) older than `gc.orphanWorkspaceRetentionMinutes`.

GC does **not** touch the library pool. Pool changes go through `removeRuntimeLibraries`.

### 12.2 `recover()`

Runs once at startup:

1. For each `runtimes/*/pool.lock`: stale `fcntl.flock` is auto-released by kernel when the holding process dies — but if a write was in-flight we re-derive `poolVersion` from disk and reconcile against the stored requirements.txt.
2. Enumerate Docker containers with `sandbox.managed=true` → kill+remove. No run is in-flight at startup.
3. Reconcile metadata records against on-disk workspace presence; orphans flagged for GC.
4. For each runtime, run `pip list --format=json --path libs/` in a short-lived container and rewrite `runtimes/<name>/requirements.txt` + the runtime record's `poolVersion`.

---

## 13. Configuration

Loaded by `SandboxManager` from a typed `SandboxConfig` dataclass. The Gromozeka adapter (see [integration doc](python-sandboxing-v1-integration.md)) is responsible for populating it from `ConfigManager`.

```python
@dataclass(slots=True)
class StorageConfig:
    rootDir: str
    dirMode: int = 0o700
    fileMode: int = 0o600

@dataclass(slots=True)
class DockerBackendConfig:
    baseUrl: str = "unix:///var/run/docker.sock"
    imagePullPolicy: Literal["never", "if-not-present", "always"] = "if-not-present"

@dataclass(slots=True)
class BackendConfig:
    name: BackendName = BackendName.DOCKER
    docker: DockerBackendConfig = field(default_factory=DockerBackendConfig)

@dataclass(slots=True)
class SessionDefaults:
    runtime: RuntimeName = RuntimeName.PYTHON
    idleTtlMinutes: int = 30
    hardTtlMinutes: int = 120
    runTimeoutSeconds: int = 30

@dataclass(slots=True)
class SecurityConfig:
    user: str = "1000:1000"
    readOnlyRootfs: bool = True
    noNewPrivileges: bool = True
    dropCapabilities: tuple[str, ...] = ("ALL",)
    privileged: bool = False

@dataclass(slots=True)
class ConcurrencyConfig:
    maxQueuedRunsPerSession: int = 4
    maxConcurrentRunsGlobal: int = 8
    globalQueueWaitSeconds: int = 60

@dataclass(slots=True)
class GcConfig:
    enabled: bool = True
    intervalSeconds: int = 60
    orphanContainerRetentionMinutes: int = 10
    orphanWorkspaceRetentionMinutes: int = 60
    runRetentionMinutes: int = 1440

@dataclass(slots=True)
class PythonRuntimeConfig:
    runImageTag: str = "gromozeka-sandbox-python:run"
    installImageTag: str = "gromozeka-sandbox-python:install"
    runDockerfile: str = "lib/sandbox/runtimes/python/Dockerfile"
    installDockerfile: str = "lib/sandbox/runtimes/python/Dockerfile.install"
    libMountPath: str = "/sandbox/libs"
    env: dict[str, str] = field(default_factory=lambda: {
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "MPLBACKEND": "Agg",
        "PYTHONPATH": "/sandbox/libs",
    })
    installContainer: InstallContainerConfig = field(default_factory=InstallContainerConfig)

@dataclass(slots=True)
class InstallContainerConfig:
    timeoutSeconds: int = 600
    memoryMb: int = 1024
    pidsLimit: int = 256

@dataclass(slots=True)
class SandboxConfig:
    storage: StorageConfig
    backend: BackendConfig = field(default_factory=BackendConfig)
    defaults: SessionDefaults = field(default_factory=SessionDefaults)
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
    gc: GcConfig = field(default_factory=GcConfig)
    runtimes: dict[RuntimeName, Any] = field(default_factory=dict)
                                         # keyed by RuntimeName, value is the
                                         # runtime-specific config dataclass
```

The TOML mapping lives in the integration doc.

---

## 14. Python runtime details

### 14.1 Run image (Dockerfile)

```dockerfile
FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg \
    PATH="/home/sandbox/.local/bin:${PATH}" \
    PYTHONPATH="/sandbox/libs"

# coreutils gives us GNU `timeout` semantics (busybox's also works,
# but coreutils is explicit and supports --kill-after consistently)
RUN apk add --no-cache coreutils \
 && adduser -D -u 1000 sandbox \
 && mkdir -p /workspace /sandbox/libs \
 && chown -R sandbox:sandbox /workspace /sandbox

USER sandbox
WORKDIR /workspace
CMD ["python"]
```

No packages baked in. The lib pool starts empty.

### 14.2 Install image (Dockerfile.install)

```dockerfile
FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Build toolchain so source-only packages compile on musl.
# Keep this list trimmed — every addition increases image size.
RUN apk add --no-cache \
        build-base \
        linux-headers \
        gfortran \
        openblas-dev \
        openssl-dev \
        libffi-dev \
        cargo \
 && adduser -D -u 1000 sandbox \
 && mkdir -p /sandbox/libs \
 && chown -R sandbox:sandbox /sandbox

USER sandbox
WORKDIR /sandbox
CMD ["python", "-m", "pip", "--version"]
```

The build toolchain is **only** in this image; the run image stays slim.

### 14.3 PythonRuntime class

```python
class PythonRuntime:
    name: RuntimeName = RuntimeName.PYTHON

    def __init__(self, config: PythonRuntimeConfig):
        self._config = config

    def runCommand(
        self,
        runId: str,
        *,
        hasStdin: bool,
        limits: ResourceLimits,
    ) -> list[str]:
        stdinPart = f"< /workspace/.run/{runId}/stdin" if hasStdin else ""
        return [
            "timeout",
            "-s", "TERM",
            "-k", str(limits.timeoutGraceSeconds),
            str(limits.timeoutSeconds),
            "sh", "-c",
            (
                f"python -u /workspace/.run/{runId}/main.py "
                f"{stdinPart} "
                f"> /workspace/.run/{runId}/stdout.log "
                f"2> /workspace/.run/{runId}/stderr.log"
            ),
        ]

    def installCommand(
        self,
        packages: Sequence[str],
        *,
        upgrade: bool,
    ) -> list[str]:
        cmd = [
            "python", "-m", "pip", "install",
            "--target", self._config.libMountPath,
            "--no-cache-dir", "--no-input",
        ]
        if upgrade:
            cmd.append("--upgrade")
        cmd.extend(packages)
        return cmd

    def listCommand(self) -> list[str]:
        return [
            "python", "-m", "pip", "list",
            "--format=json",
            "--path", self._config.libMountPath,
        ]

    def detectArtifacts(
        self,
        workspacePath: Path,
        *,
        sinceMtime: float,
    ) -> list[ArtifactInfo]:
        """Walk workspace excluding .run/, return files newer than sinceMtime."""
        ...
```

---

## 15. Backend interface

```python
class SandboxBackend(Protocol):
    name: BackendName

    async def healthcheck(self) -> HealthcheckResult: ...

    async def ensureImage(
        self,
        runtime: RuntimeInfo,
        *,
        rebuild: bool = False,
    ) -> None: ...

    async def runOneshot(self, spec: ContainerSpec) -> ContainerOutcome:
        """Run a container to completion, return the outcome.
        Does NOT remove the container — caller collects artifacts first.
        """

    async def removeContainer(
        self,
        containerId: str,
        *,
        force: bool = True,
    ) -> None: ...

    async def killContainer(
        self,
        containerId: str,
        *,
        signal: str = "SIGKILL",
    ) -> None: ...

    async def inspectContainer(self, containerId: str) -> dict[str, Any]:
        """Used for OOM detection (State.OOMKilled) and similar."""

    async def listManagedContainers(self) -> list[ManagedContainerInfo]: ...
```

`DockerBackend` uses `aiodocker`. `ContainerSpec` stays close to the Docker API to avoid lossy translation. Future non-Docker backends reject unsupported fields explicitly.

---

## 16. Testing strategy

Per [`docs/llm/testing.md`](../llm/testing.md). Tests live at `tests/lib/sandbox/`.

1. **Unit tests** (no Docker required):
   - `storage.resolveWorkspacePath` — path traversal, symlink escapes, absolute paths.
   - Package-spec validation — malicious strings, valid PEP 508, edge cases.
   - `SessionLockRegistry` — FIFO ordering, queue cap, force-drop semantics.
   - `FilesystemMetadataStore` — atomic writes, round-trips, schema versioning.
   - GC decision logic against synthetic file trees + synthetic metadata.
   - Config loading + defaults merge.
   - StrEnum coverage.

2. **Integration tests** marked `@pytest.mark.slow`, gated on `DOCKER_AVAILABLE`:
   - End-to-end `runCode("print(2 + 2)")` returns `exitCode=0`, stdout file contains `4\n`.
   - Timeout enforcement (`while True: pass` → `timedOut=True`, `exitCode=124`).
   - OOM detection (`b"\0" * (1 << 30)` → `oomKilled=True`).
   - Network off: `socket.create_connection(("8.8.8.8", 53))` fails.
   - Required-packages missing: `MissingDependenciesError`, no container starts.
   - Workspace persistence across runs in a session.
   - Library RO: writing to `/sandbox/libs` from user code → `PermissionError`.
   - Per-session FIFO ordering under concurrent submissions.
   - Force-drop while a long run is in flight → run is killed, waiters get `SessionDropped`.
   - GC removes expired sessions but leaves the library pool intact.
   - `recover()` reaps a deliberately leaked container.
   - Install: numpy install succeeds, appears in `listRuntimeLibraries`, becomes usable in next run.
   - Install: invalid spec (`numpy; rm -rf /`) → `InvalidPackageSpec` before any container starts.

3. **Property tests** for path resolution (hypothesis): no UTF-8 oddities allow escape.

`testpaths` already includes `lib/` per [`pyproject.toml`](../../pyproject.toml).

---

## 17. Milestones

### M1 — Skeleton

- Package layout under `lib/sandbox/`
- `enums.py`, `types.py`, `errors.py`
- `SandboxBackend` and `Runtime` Protocols
- `MetadataStore` Protocol
- `SandboxConfig` and all sub-config dataclasses
- Stubs for `SandboxManager` returning `NotImplementedError`
- Unit tests for type round-trips and config defaults

### M2 — Storage + lifecycle (no Docker)

- `storage.py` — directory layout, sessionHash, atomic metadata writes, path resolver
- `locks.py` — per-session FIFO lock, global semaphore
- `FilesystemMetadataStore`
- `SandboxManager`: `createSession` / `getSessionInfo` / `getSessionUsage` / `listSessions` / `touchSession` / `dropSession`
- File API: `listFiles` / `readFile` / `writeFile` / `deleteFile`
- GC for orphan workspaces and expired sessions
- Unit + property tests; **no Docker yet**

### M3 — Docker backend + Python runtime

- `DockerBackend` (`aiodocker`)
- `PythonRuntime` + run/install Dockerfiles
- `prepareRuntime`, `installRuntimeLibraries`, `removeRuntimeLibraries`, `listRuntimeLibraries`
- `runCode` end-to-end (oneshot container, `timeout` wrapper, stdout/stderr to files, artifact detection, OOM detection)
- `cancelRun`, `getRunInfo`, `listRunsForSession`
- `healthcheck`, `recover`, `collectGarbage`, `shutdown`
- Integration tests gated on `DOCKER_AVAILABLE`

### M4 — Tooling and ops

- `scripts/sandbox-bootstrap.py` — admin script to install a starter library set on a fresh deployment. Reads a default package list from config, calls `installRuntimeLibraries`.
- Reference TOML config snippet shipped under `configs/00-defaults/sandbox.toml` (see integration doc for the exact mapping).

### M5 — Gromozeka integration

See [`python-sandboxing-v1-integration.md`](python-sandboxing-v1-integration.md).

### M6 — Future (deliberately out of scope)

- TypeScript runtime
- Firecracker / gVisor backends
- Network proxy / allowlist policy
- `DatabaseMetadataStore`
- Asynchronous submit/poll API (`submitRun` + `awaitRun`)
- Persistent (long-lived) execution mode

---

## 18. Open questions

The original open list has been resolved by design decisions:

- **Bootstrap UX**: `scripts/sandbox-bootstrap.py` ships a starter library set (M4).
- **Library deny-list**: dropped. Admin is trusted not to install dangerous packages.
- **Workspace size monitoring**: exposed via `getSessionUsage(sessionId) -> SessionUsage` (lazy, not auto-computed in `getSessionInfo`).
- **Run history retention**: run record + `.run/<runId>/` deleted as a unit.
- **Global concurrency cap behaviour**: queue, with `globalQueueWaitSeconds` timeout → `SandboxBusy`.
- **Pool reconfiguration mid-session**: acceptable; `RunResult.libPoolVersion` exposes drift.

Any remaining questions will surface during M1–M3 implementation review.
