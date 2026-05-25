# Sandboxed Code Execution — Implementation Plan

Status: **ready for execution**
Owner: teamlead (delegates, coordinates, integrates)
Design source: [`python-sandboxing-v1.md`](python-sandboxing-v1.md), [`python-sandboxing-v1-integration.md`](python-sandboxing-v1-integration.md)
Project rules: [`AGENTS.md`](../../AGENTS.md), [`docs/llm/index.md`](../llm/index.md)

This document decomposes the sandbox feature into **work packages (WP)** the teamlead can hand to specialist agents one at a time. Each WP is self-contained: clear inputs, files touched, specialist to dispatch, acceptance criteria, and how to verify before signing it off. Dependencies and parallelism opportunities are called out explicitly.

The design docs are the source of truth for shapes, names, and semantics. This plan is the **build order**, not a redefinition of the design.

---

## 0. Cross-cutting rules (brief every specialist with these)

Every dispatch must include these in the brief, regardless of WP:

1. **Code style** (non-negotiable per [`AGENTS.md`](../../AGENTS.md)):
   - `camelCase` for variables, args, fields, functions, methods.
   - `PascalCase` for classes. `UPPER_CASE` for constants.
   - Docstrings required on every module/class/method/function with `Args:` / `Returns:` blocks.
   - Type hints on all params and returns; locals when type isn't obvious.
   - Imports at top of file (no per-method imports unless cyclic-import bug forces it).
   - **No pydantic.** Use `@dataclass(slots=True)` and `TypedDict`.
   - Use `./venv/bin/python3` — never bare `python` / `python3`.
   - Run commands from repo root; never `cd` into subdirectories.

2. **Quality gates** (per [`run-quality-gates`](../../.agents/skills/run-quality-gates/SKILL.md) skill):
   - `make format lint` before AND after edits.
   - `make test` after every change. Mandatory.
   - For anything under `lib/ext_modules/*`: `make format` handles those subpackages.

3. **Testing rules** (per [`docs/llm/testing.md`](../llm/testing.md)):
   - `testpaths = ["tests", "lib", "internal"]` — collocated tests under `tests/lib/sandbox/` are real and run automatically.
   - `asyncio_mode = "auto"` — write `async def test_…` with no decorator.
   - Reuse fixtures from [`tests/conftest.py`](../../tests/conftest.py) where they fit.
   - Regression test on every bug fix (failing-then-passing).
   - Singletons leak state — reset `_instance = None` in fixtures (the existing autouse `resetLlmServiceSingleton` is a template).

4. **Singleton pattern** (matches the existing codebase):
   - Access via `Service.getInstance()`, never construct directly.
   - Init guards with `hasattr(self, 'initialized')`.

5. **SQL portability**: no SQL in this feature. If a specialist proposes any (e.g., reaches for `DatabaseMetadataStore` early), reject and route back to the design — v0 is filesystem-only.

6. **Documentation sync** (per [`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md) skill): at the end of each phase, run the documentation pass listed in §10.

7. **Subagent routing**:
   - `software-developer` for build/refactor work.
   - `debugger` for investigations of failures.
   - `code-reviewer` after each WP — read-only review pass before sign-off.
   - `code-analyst` if a WP needs grounding in existing code patterns (e.g., how `ConfigManager` works) before implementation.
   - `explore` for broad pattern searches in unfamiliar areas.
   - `architect` for design questions that arise mid-implementation — escalate rather than improvise.

---

## 1. Phase overview & dependency graph

```text
            ┌────────────────┐
            │ Phase 1: skel  │      M1
            └──────┬─────────┘
                   │
            ┌──────▼─────────┐
            │ Phase 2: store │      M2  (no Docker)
            └──────┬─────────┘
                   │
            ┌──────▼─────────┐
            │ Phase 3: dock  │      M3  (Docker + Python)
            └──────┬─────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
  ┌─────▼──────┐       ┌──────▼─────┐
  │ Phase 4:   │       │ Phase 5:   │      M4 + M5 in parallel after M3
  │ tooling    │       │ integration│
  └─────┬──────┘       └──────┬─────┘
        │                     │
        └──────────┬──────────┘
                   │
            ┌──────▼─────────┐
            │ Phase 6: docs  │      M5.4
            └────────────────┘
```

Phases 1, 2, 3 are strictly sequential. Phase 4 (bootstrap script + default config) and Phase 5 (Gromozeka integration) can run in parallel once Phase 3 lands.

---

## 2. Phase 1 — Library skeleton

**Goal**: every module exists, every type is defined, every Protocol is sketched, every `SandboxManager` method exists and raises `NotImplementedError`. Tests verify the skeleton compiles, types round-trip, and the public surface matches the design.

### WP-1.1 — Enums

- **Specialist**: `software-developer`
- **Dependencies**: none
- **Files**: `lib/sandbox/enums.py` (new), `lib/sandbox/__init__.py` (new)
- **Tasks**:
  - Define `RuntimeName(StrEnum)` with `PYTHON = "python"`.
  - Define `BackendName(StrEnum)` with `DOCKER = "docker"`.
  - Re-export both from `lib/sandbox/__init__.py`.
- **Acceptance**:
  - `from lib.sandbox import RuntimeName, BackendName` works.
  - `RuntimeName("python")` returns the member.
- **Tests**: `tests/lib/sandbox/test_enums.py` — value coverage, string compat.
- **Verify**: `make format lint && make test`.

### WP-1.2 — Public dataclasses

- **Specialist**: `software-developer`
- **Dependencies**: WP-1.1
- **Files**: `lib/sandbox/types.py` (new)
- **Tasks**: Define every `@dataclass(slots=True)` listed in [§6 of the library design](python-sandboxing-v1.md#6-data-model): `NetworkPolicy`, `ResourceLimits`, `InputFile`, `SessionInfo`, `SessionUsage`, `RunInfo`, `RunResult`, `ArtifactInfo`, `FileInfo`, `FileContent`, `PackageInfo`, `LibraryInstallResult`, `LibraryRemoveResult`, `DropSessionResult`, `HealthcheckResult`, `GcResult`, `RecoveryResult`, `RuntimeInfo`.
- **Acceptance**: Each dataclass importable; field names and types match the design doc exactly.
- **Tests**: round-trip construction with default and explicit values; verify `slots=True` (`assert not hasattr(obj, '__dict__')`).

### WP-1.3 — Error hierarchy

- **Specialist**: `software-developer`
- **Dependencies**: none (parallel with WP-1.1, WP-1.2)
- **Files**: `lib/sandbox/errors.py` (new)
- **Tasks**: Implement the exception tree from [§6.4](python-sandboxing-v1.md#6-data-model). `MissingDependenciesError` carries `missing: list[str]`; `InvalidPackageSpec` carries `spec: str` and `reason: str`.
- **Acceptance**: All errors inherit from `SandboxError`; specific errors expose their structured fields.
- **Tests**: `raise` / `except` chain for each class.

### WP-1.4 — Config dataclasses

- **Specialist**: `software-developer`
- **Dependencies**: WP-1.1, WP-1.2
- **Files**: `lib/sandbox/config.py` (new)
- **Tasks**: Implement all config dataclasses from [§13 of library design](python-sandboxing-v1.md#13-configuration): `StorageConfig`, `DockerBackendConfig`, `BackendConfig`, `SessionDefaults`, `SecurityConfig`, `ConcurrencyConfig`, `GcConfig`, `PythonRuntimeConfig`, `InstallContainerConfig`, `SandboxConfig`.
- **Acceptance**: All dataclasses constructible with documented defaults; `SandboxConfig.runtimes` keyed by `RuntimeName`.
- **Tests**: defaults match design doc; nested config construction works.

### WP-1.5 — Protocols

- **Specialist**: `software-developer`
- **Dependencies**: WP-1.2
- **Files**:
  - `lib/sandbox/backends/__init__.py` (new)
  - `lib/sandbox/backends/base.py` (new) — `SandboxBackend` Protocol
  - `lib/sandbox/runtimes/__init__.py` (new)
  - `lib/sandbox/runtimes/base.py` (new) — `Runtime` Protocol
  - `lib/sandbox/metadata/__init__.py` (new)
  - `lib/sandbox/metadata/base.py` (new) — `MetadataStore` Protocol + `SessionRecord`, `RunRecord`, `RuntimeRecord` dataclasses
- **Tasks**: Define Protocols matching [§11](python-sandboxing-v1.md#11-metadata-store), [§14](python-sandboxing-v1.md#14-python-runtime-details), [§15](python-sandboxing-v1.md#15-backend-interface) of the library design. Also define `ContainerSpec` and `ContainerOutcome` dataclasses used by `SandboxBackend.runOneshot`.
- **Acceptance**: A class with the required methods passes a runtime `isinstance(x, SandboxBackend)` check (the Protocol must be `@runtime_checkable` only if needed; the design uses structural typing — leave it static-only unless a use case demands otherwise).
- **Tests**: Define a trivial stub class for each Protocol; verify it type-checks (smoke test via pyright in `make lint`).

### WP-1.6 — `SandboxManager` skeleton

- **Specialist**: `software-developer`
- **Dependencies**: WP-1.1 … WP-1.5
- **Files**: `lib/sandbox/manager.py` (new)
- **Tasks**:
  - Implement `getInstance()` singleton with the `hasattr(self, 'initialized')` guard.
  - Define **every** public method from [§5 of library design](python-sandboxing-v1.md#5-public-api) with full signatures, docstrings, and `raise NotImplementedError`.
  - `__init__(config: SandboxConfig)` stores the config; nothing else yet.
- **Acceptance**: `SandboxManager.getInstance(config)` returns a working singleton; calling any method raises `NotImplementedError` with a descriptive message naming the method.
- **Tests**: singleton identity; every public method present and async.

### WP-1.7 — Phase 1 review

- **Specialist**: `code-reviewer`
- **Dependencies**: WP-1.1 … WP-1.6
- **Tasks**: Read every file produced in Phase 1; verify name parity with the design doc, camelCase/docstring/type-hint compliance, no pydantic, no per-method imports.
- **Output**: a written review. Fixes applied by `software-developer` if needed.
- **Verify**: `make format lint && make test` clean.

---

## 3. Phase 2 — Storage & lifecycle (no Docker)

**Goal**: sessions, files, GC, locks all work against the host filesystem. No Docker calls anywhere yet. The `SandboxManager` can create, list, touch, drop sessions, manage files in the workspace, and GC expired ones — all without containers.

### WP-2.1 — Storage primitives

- **Specialist**: `software-developer`
- **Dependencies**: Phase 1 complete
- **Files**: `lib/sandbox/storage.py` (new)
- **Tasks**:
  - `sessionHash(sessionId: str) -> str` — full `sha256(sessionId).hexdigest()`.
  - `resolveWorkspacePath(workspaceRoot: Path, requested: str) -> Path` — reject absolute paths, `..` traversal, symlinks escaping the workspace. Raise `PathOutsideWorkspace`.
  - `atomicWriteJson(path: Path, payload: dict, *, tmpDir: Path) -> None` — write to temp file under `tmpDir`, `fsync`, rename. Use the configured `fileMode` / `dirMode`.
  - `ensureDirectoryLayout(config: StorageConfig) -> None` — create the directory tree from [§7](python-sandboxing-v1.md#7-storage-layout) with correct modes and ownership (best-effort if not root; warn if chown fails).
- **Acceptance**: All helpers pure / side-effect-only-where-marked; full path-traversal coverage in tests.
- **Tests**: `tests/lib/sandbox/test_storage.py` — extensive `resolveWorkspacePath` cases (absolute, `..`, symlink, null byte, unicode); atomic write survives simulated crash (temp file left behind); hash determinism.

### WP-2.2 — `FilesystemMetadataStore`

- **Specialist**: `software-developer`
- **Dependencies**: WP-2.1
- **Files**: `lib/sandbox/metadata/filesystem.py` (new)
- **Tasks**: Implement every method of the `MetadataStore` Protocol against JSON files under `${rootDir}/meta/`. Uses `atomicWriteJson` for all writes. Records carry a `schemaVersion` field (start at `1`).
- **Acceptance**: Round-trip every record type; concurrent writes to the same key serialise correctly (`asyncio.Lock` keyed by id); `listSessions(runtime=...)` filtering works.
- **Tests**: `tests/lib/sandbox/test_metadata_filesystem.py` — CRUD per record type, concurrent writes via `asyncio.gather`, malformed JSON recovery, schema-version mismatch behaviour (raise `ConfigError`).

### WP-2.3 — Lock registry

- **Specialist**: `software-developer`
- **Dependencies**: Phase 1
- **Files**: `lib/sandbox/locks.py` (new)
- **Tasks**:
  - `SessionLockRegistry` — per-`sessionId` `asyncio.Lock` with bounded waiters (`maxQueuedRunsPerSession`). Overflow → `SessionBusy`. `forceCancel(sessionId)` notifies all waiters with `SessionDropped`.
  - Global run semaphore (`asyncio.Semaphore`) with `globalQueueWaitSeconds` timeout → `SandboxBusy`.
  - `acquirePoolLock(runtime: RuntimeName, poolDir: Path)` — sync `fcntl.flock` wrapped in `asyncio.to_thread`. Non-blocking; on failure → `LibraryPoolLocked`.
- **Acceptance**: FIFO ordering provable in tests; force-cancel wakes waiters without breaking other sessions' locks.
- **Tests**: `tests/lib/sandbox/test_locks.py` — submit N coroutines concurrently, assert completion order; overflow path; force-cancel path; flock test using a real temp file.

### WP-2.4 — Session lifecycle on `SandboxManager`

- **Specialist**: `software-developer`
- **Dependencies**: WP-2.1, WP-2.2, WP-2.3
- **Files**: `lib/sandbox/manager.py` (extend)
- **Tasks**: Implement `createSession`, `getSessionInfo`, `getSessionUsage`, `listSessions`, `touchSession`, `dropSession`. `runCode` still `NotImplementedError`. Auto-creation in `runCode` is *not* yet exercised in this phase.
- **Acceptance**:
  - `createSession` idempotent unless `forceRecreate=True`.
  - `getSessionUsage` walks workspace, returns size + file count.
  - `dropSession(force=False)` waits for session lock; `force=True` cancels waiters.
- **Tests**: `tests/lib/sandbox/test_manager_sessions.py` — idempotency, TTL bump on touch, drop+recreate cycle, usage math, force-drop semantics.

### WP-2.5 — File API on `SandboxManager`

- **Specialist**: `software-developer`
- **Dependencies**: WP-2.4
- **Files**: `lib/sandbox/manager.py` (extend)
- **Tasks**: Implement `listFiles`, `readFile`, `writeFile`, `deleteFile`. All paths through `resolveWorkspacePath`. `readFile(maxBytes=...)` enforces the read-time cap and reports `truncated`.
- **Acceptance**: Path traversal attempts raise `PathOutsideWorkspace`; binary vs text reads honour `encoding`; large file truncation correct to the byte.
- **Tests**: `tests/lib/sandbox/test_manager_files.py` — write/read/list/delete round-trips, path safety, encoding handling, truncation boundary cases.

### WP-2.6 — Garbage collector (filesystem only)

- **Specialist**: `software-developer`
- **Dependencies**: WP-2.4, WP-2.5
- **Files**: `lib/sandbox/gc.py` (new), `lib/sandbox/manager.py` (extend with `collectGarbage`)
- **Tasks**: Implement the workspace-side GC from [§12.1](python-sandboxing-v1.md#121-collectgarbage): expired sessions, orphan workspace dirs, expired run records (records + `.run/<runId>/` removed as a unit). Container GC stub in place — implemented in Phase 3.
- **Acceptance**: GC removes expected items; refuses to touch the library pool; returns accurate `GcResult` counts.
- **Tests**: `tests/lib/sandbox/test_gc.py` — synthetic directory trees, expired vs unexpired, orphan detection, retention boundaries.

### WP-2.7 — Phase 2 review

- **Specialist**: `code-reviewer`
- **Dependencies**: WP-2.1 … WP-2.6
- **Tasks**: Cross-check storage paths against [§7](python-sandboxing-v1.md#7-storage-layout); verify no Docker imports; verify lock semantics; ensure `getSessionInfo` does **not** trigger workspace traversal (cost separation).
- **Verify**: `make format lint && make test` clean. Coverage on `lib/sandbox/` should be substantial by end of Phase 2.

---

## 4. Phase 3 — Docker backend + Python runtime

**Goal**: real container execution, real package installs, real OOM/timeout detection, real recovery. End-to-end `runCode("print(2+2)")` works.

### WP-3.1 — Dockerfiles

- **Specialist**: `software-developer`
- **Dependencies**: Phase 2 complete
- **Files**:
  - `lib/sandbox/runtimes/python/Dockerfile` (new) — run image, exact contents from [§14.1](python-sandboxing-v1.md#141-run-image-dockerfile).
  - `lib/sandbox/runtimes/python/Dockerfile.install` (new) — install image, exact contents from [§14.2](python-sandboxing-v1.md#142-install-image-dockerfilenstall).
- **Acceptance**:
  - `docker build` succeeds for both on a host with Docker.
  - Run image is significantly smaller than install image.
  - Inside the run image, `id` reports uid=1000, `coreutils` provides `timeout`.
- **Verify**: build both images locally (this WP requires Docker on the developer's host). The build is *not* run by `make test`; document the manual step in the WP completion note.

### WP-3.2 — `PythonRuntime`

- **Specialist**: `software-developer`
- **Dependencies**: WP-3.1
- **Files**: `lib/sandbox/runtimes/python/runtime.py` (new), `lib/sandbox/runtimes/python/__init__.py` (new)
- **Tasks**: Implement `PythonRuntime` per [§14.3](python-sandboxing-v1.md#143-pythonruntime-class). `runCommand` emits the `timeout -s TERM -k <grace> <secs> sh -c '…'` wrapper with stdin/stdout/stderr redirections. `detectArtifacts` walks the workspace excluding `.run/`.
- **Acceptance**: Generated commands match the design exactly; artifact detection finds new/modified files.
- **Tests**: `tests/lib/sandbox/runtimes/test_python_runtime.py` — command shape (string comparison), artifact detection against synthetic file trees with mtime manipulation.

### WP-3.3 — `DockerBackend`

- **Specialist**: `software-developer`
- **Dependencies**: WP-3.1, Phase 1 Protocols
- **Files**: `lib/sandbox/backends/docker.py` (new)
- **Tasks**: Implement every method of `SandboxBackend` against `aiodocker`. Add `aiodocker` to `requirements.txt`. `runOneshot` returns a `ContainerOutcome` carrying exit code, signal, OOM flag (from `inspect.State.OOMKilled`), and the container id (caller removes it after artifact collection). `ensureImage` builds from the Dockerfile path if not present.
- **Acceptance**:
  - Smoke test: build the Python run image, launch `docker run alpine echo hi` equivalent through `runOneshot`, get `exitCode=0`.
  - OOM detection works: a container killed by the OOM killer returns `oomKilled=True`.
  - `listManagedContainers` filters by the `sandbox.managed=true` label.
- **Tests**: `tests/lib/sandbox/backends/test_docker.py` marked `@pytest.mark.slow`, gated on `DOCKER_AVAILABLE` (define this as a top-level pytest skip in `conftest.py`).

### WP-3.4 — `runCode` end-to-end

- **Specialist**: `software-developer`
- **Dependencies**: WP-3.2, WP-3.3
- **Files**: `lib/sandbox/manager.py` (extend)
- **Tasks**: Implement `runCode` per [§8.2](python-sandboxing-v1.md#82-run-lifecycle). Include auto-creation of the session when missing. Verify `requiredPackages ⊆ pool` via `MetadataStore.loadRuntime`. Set up the `.run/<runId>/` directory, write `main.py`, optional stdin file, optional input files. Construct `ContainerSpec`, call `backend.runOneshot`, detect outcome (exit 124 → `timedOut`; `OOMKilled` → `oomKilled`), populate `RunResult`, persist `RunInfo` + `result.json`, remove container, return.
- **Acceptance**: Every field on `RunResult` is populated correctly across the matrix: success, non-zero exit, timeout, OOM, missing package, invalid stdin path.
- **Tests** (`@pytest.mark.slow`, `DOCKER_AVAILABLE`):
  - `print(2 + 2)` → exit 0, stdout file contains `4\n`.
  - `import sys; sys.exit(7)` → `exitCode=7`.
  - `while True: pass` with `timeoutSeconds=2` → `timedOut=True`, `exitCode=124`.
  - Allocate >memory limit → `oomKilled=True`.
  - Network off: `socket.create_connection(("8.8.8.8", 53))` raises inside.
  - Network on: same call succeeds (skip if CI has no internet).
  - `requiredPackages=["definitely-not-installed"]` → `MissingDependenciesError`, no container started.
  - Two runs in one session: file written in run 1 is readable in run 2.
  - `/sandbox/libs` write attempt from user code → `PermissionError` propagated.

### WP-3.5 — Library pool install/remove/list

- **Specialist**: `software-developer`
- **Dependencies**: WP-3.3
- **Files**: `lib/sandbox/manager.py` (extend), `lib/sandbox/runtimes/python/runtime.py` (extend if needed for `installCommand` / `listCommand`)
- **Tasks**:
  - Implement `installRuntimeLibraries` per [§8.3](python-sandboxing-v1.md#83-library-install-lifecycle): flock, PEP 508 validation, shell-metachar pre-screen, install container, refresh `requirements.txt`, update runtime record + `poolVersion`.
  - Implement `removeRuntimeLibraries` symmetrically.
  - Implement `listRuntimeLibraries` from the runtime record.
- **Acceptance**:
  - Install `numpy` → appears in `listRuntimeLibraries`, usable in next `runCode`.
  - Install `"numpy; rm -rf /"` → `InvalidPackageSpec` before any container starts.
  - Install concurrent calls: second raises `LibraryPoolLocked`.
  - Remove a package not present → `notFound` populated, no error.
  - `poolVersion` changes on every successful install/remove.
- **Tests** (`@pytest.mark.slow`, `DOCKER_AVAILABLE`):
  - Spec validation table (valid PEP 508, malicious strings, edge cases).
  - End-to-end install + usage cycle.
  - Concurrent install attempt path.
  - Failure mode: pip exits non-zero → `LibraryInstallFailed`, pool reverts (no partial state).

### WP-3.6 — Health, recovery, container GC

- **Specialist**: `software-developer`
- **Dependencies**: WP-3.3, WP-3.4, WP-3.5
- **Files**: `lib/sandbox/manager.py` (extend), `lib/sandbox/gc.py` (extend)
- **Tasks**:
  - `healthcheck`: ping Docker, list runtimes, check storage dir writability, return structured result.
  - `recover`: kill+remove all containers with `sandbox.managed=true`, reconcile metadata with on-disk state, refresh `poolVersion` for each runtime.
  - Extend `collectGarbage` to remove orphan containers older than `gc.orphanContainerRetentionMinutes`.
  - `shutdown(cleanVolumes=False)`: stop background GC task; if `cleanVolumes=True`, drop every session.
  - `cancelRun(runId)`: look up the container via labels, SIGKILL it.
  - `getRunInfo`, `listRunsForSession`: read from `MetadataStore`.
- **Acceptance**: Each method returns the correct dataclass; `recover` is idempotent.
- **Tests** (`@pytest.mark.slow`, `DOCKER_AVAILABLE`):
  - Leak a labelled container manually, run `recover`, verify it's reaped.
  - Run a long script, call `cancelRun`, verify it exits.
  - `healthcheck` returns `ok=False` when Docker daemon is unreachable (skip if Docker is healthy).

### WP-3.7 — Phase 3 review

- **Specialist**: `code-reviewer`
- **Dependencies**: WP-3.1 … WP-3.6
- **Tasks**: Verify every Docker security setting from [§10](python-sandboxing-v1.md#10-security-model) is applied in `runOneshot` and the install container. Verify no host env leaks into containers. Verify path resolution is applied on every API boundary. Verify the `LLMMessageHandler`-last rule isn't violated (no handler work in this phase — sanity-check only).
- **Verify**: `make format lint && make test`. Slow tests pass when run with `DOCKER_AVAILABLE=1`.

---

## 5. Phase 4 — Tooling

Can run in parallel with Phase 5 after Phase 3 is signed off.

### WP-4.1 — Default config

- **Specialist**: `software-developer`
- **Dependencies**: Phase 3
- **Files**: `configs/00-defaults/sandbox.toml` (new)
- **Tasks**: Ship the TOML file from [§3.1 of integration doc](python-sandboxing-v1-integration.md#31-defaults-toml). Verify it merges cleanly with `./venv/bin/python3 main.py --print-config --config-dir configs/00-defaults`.
- **Acceptance**: Print-config output includes every `[sandbox.*]` key with the documented default.
- **Tests**: None new — visual diff of merged config output is sufficient. Note manually verified in WP completion.

### WP-4.2 — Bootstrap script

- **Specialist**: `software-developer`
- **Dependencies**: Phase 3, WP-4.1
- **Files**: `scripts/sandbox-bootstrap.py` (new)
- **Tasks**: Implement per [§6 of integration doc](python-sandboxing-v1-integration.md#6-bootstrap-script). CLI flags: `--config-dir` (repeatable), `--runtime`, `--upgrade`, `--init-storage`. Reads `sandbox.bootstrap.starter-packages`. Calls `prepareRuntime` then `installRuntimeLibraries`. Prints a summary table.
- **Acceptance**:
  - Running on a clean install installs the starter pack.
  - Re-running with `--upgrade` upgrades to latest.
  - `--init-storage` creates `storage.root_dir` if missing (warns if it can't chown).
- **Tests**: `tests/scripts/test_sandbox_bootstrap.py` — drive the script with a fake `SandboxService` injected via the standard config mechanism; verify exit codes and stdout.
- **Verify**: manual smoke run on the dev machine documented in the completion note.

---

## 6. Phase 5 — Gromozeka integration

Can run in parallel with Phase 4 after Phase 3 is signed off. Internally sequential.

### WP-5.1 — `SandboxService` singleton

- **Specialist**: `software-developer`
- **Dependencies**: Phase 3 complete
- **Files**:
  - `internal/services/sandbox/__init__.py` (new)
  - `internal/services/sandbox/service.py` (new)
- **Tasks**: Implement per [§2 of integration doc](python-sandboxing-v1-integration.md#2-sandboxservice-singleton):
  - Singleton with `hasattr(self, 'initialized')` guard.
  - `_buildSessionId(chatId, threadId)` → `f"chat-{chatId}-thread-{threadId}"`.
  - `_ensureOwner(userId)` — integer-only check against `bot_owners`.
  - `_buildSandboxConfigFromConfigManager` — pure mapping from TOML keys to `SandboxConfig`.
  - Public methods: `runCodeForChat`, `readArtifact`, `listArtifacts`, `installLibrariesAdmin`, `removeLibrariesAdmin`, `listLibraries`, `healthcheck`.
  - Schedule `manager.recover()` once on init via `asyncio.create_task`.
- **Acceptance**: Service initialises cleanly; all public methods dispatch to `SandboxManager`; admin methods enforce owner check.
- **Tests**: `tests/services/sandbox/test_service.py` — inject a fake `SandboxManager`, verify dispatch and admin gating. Cover the `bot_owners` username-vs-int gotcha explicitly.

### WP-5.2 — `RunPythonHandler`

- **Specialist**: `software-developer`
- **Dependencies**: WP-5.1
- **Files**: `internal/bot/common/handlers/run_python_handler.py` (new)
- **Tasks**: Implement per [§4.1 of integration doc](python-sandboxing-v1-integration.md#41-runpythonhandler-llm-tool--command). Reads `stdoutPath` / `stderrPath` via `SandboxService.readArtifact(maxBytes=4096)`. On larger output: upload through the existing storage service (consult the existing handlers for the pattern via `code-analyst` if uncertain). Conditional registration: only register if `bot.handlers.run_python.enabled` is `true`.
- **Acceptance**: `/python print(1+1)` returns `2`; `/python` with no code returns the prompt; missing-deps and busy errors handled gracefully.
- **Tests**: per the [`add-handler`](../../.agents/skills/add-handler/SKILL.md) skill — real `EnsuredMessage` objects, fake `SandboxService` injected. Run via `make test`.

### WP-5.3 — `SandboxAdminHandler`

- **Specialist**: `software-developer`
- **Dependencies**: WP-5.1
- **Files**: `internal/bot/common/handlers/sandbox_admin_handler.py` (new)
- **Tasks**: Implement per [§4.2 of integration doc](python-sandboxing-v1-integration.md#42-sandboxadminhandler-operator-commands). Dispatch on `/sandbox_install`, `/sandbox_remove`, `/sandbox_list`, `/sandbox_health`. Resolve usernames in `bot_owners` to numeric ids here (the service layer is numeric-only). Reject non-owners with a clear message.
- **Acceptance**: All four subcommands work end-to-end against a fake service; non-owner attempts are rejected and logged.
- **Tests**: Same pattern as WP-5.2.

### WP-5.4 — Handler registration

- **Specialist**: `software-developer`
- **Dependencies**: WP-5.2, WP-5.3
- **Files**: `internal/bot/common/handlers/manager.py` (modify)
- **Tasks**: Register `SandboxAdminHandler` (gated on a config flag) and `RunPythonHandler` (gated on `bot.handlers.run_python.enabled`) **before** `LLMMessageHandler` in the ordered list.
- **CRITICAL**: `LLMMessageHandler` must remain the last entry. Verify by reading the file after editing.
- **Acceptance**: Bot starts up; new handlers visible in startup logs; `LLMMessageHandler` still last.
- **Tests**: Existing manager tests must still pass. Add a new test asserting the registration order invariant.

### WP-5.5 — Optional LLM tool wiring

- **Specialist**: `software-developer`
- **Dependencies**: WP-5.1
- **Files**: under `internal/services/llm/` — exact location depends on existing tool-registration pattern. Use `code-analyst` to map the LLM tool surface before implementing.
- **Tasks**: Wire `SandboxService.runCodeForChat` as an LLM-callable tool. Tool description per [§5 of integration doc](python-sandboxing-v1-integration.md#5-llm-tool-integration). Gate on `llm.tools.sandbox.enabled` config flag.
- **Acceptance**: LLM tool call → execution → formatted reply with at most the first 4 KB of each stream inline + file upload for the rest.
- **Tests**: Mock LLM round-trip with the existing test patterns; verify the tool is correctly registered and dispatchable.
- **Note**: this WP is optional for the initial cut. If skipped, document the deferral and re-open later.

### WP-5.6 — Phase 5 review

- **Specialist**: `code-reviewer`
- **Dependencies**: WP-5.1 … WP-5.5
- **Tasks**: Verify the `lib/`-no-bot-deps rule (no `internal/` imports from `lib/sandbox/`). Verify `LLMMessageHandler` is still last. Verify admin gating is bullet-proof.
- **Verify**: `make format lint && make test` clean.

---

## 7. Phase 6 — Documentation sync

Run after every code phase that lands in `main`; the major sync happens at the end.

### WP-6.1 — Phase 3 doc sync

- **Specialist**: `software-developer` (load the [`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md) skill)
- **Dependencies**: Phase 3 complete
- **Files**:
  - [`docs/llm/libraries.md`](../llm/libraries.md): new section for `lib/sandbox/`.
  - [`AGENTS.md`](../../AGENTS.md): add `lib/sandbox/` to the layout cheatsheet.
- **Acceptance**: New library is discoverable from the canonical agent docs.

### WP-6.2 — Phase 4 doc sync

- **Specialist**: `software-developer`
- **Dependencies**: Phase 4 complete
- **Files**:
  - [`docs/llm/configuration.md`](../llm/configuration.md): document `[sandbox.*]` keys.
  - [`docs/developer-guide.md`](../developer-guide.md): "Bootstrapping the sandbox" section — Docker prereq, storage-dir creation, script usage.
- **Acceptance**: A new operator can follow the guide and reach a working install.

### WP-6.3 — Phase 5 doc sync

- **Specialist**: `software-developer`
- **Dependencies**: Phase 5 complete
- **Files**:
  - [`docs/llm/services.md`](../llm/services.md): add `SandboxService`.
  - [`docs/llm/handlers.md`](../llm/handlers.md): add `RunPythonHandler`, `SandboxAdminHandler`, registration-order invariant.
  - [`docs/llm/architecture.md`](../llm/architecture.md): one paragraph + diagram update.
  - [`docs/llm/tasks.md`](../llm/tasks.md): new gotcha — "stdout/stderr live in workspace files, not `RunResult` bytes; use `readFile` to fetch".
  - [`AGENTS.md`](../../AGENTS.md): add `internal/services/sandbox/` to the layout cheatsheet; mention the LLMMessageHandler-last invariant where the sandbox handlers register.
- **Acceptance**: Cross-references between docs (services ↔ handlers ↔ libraries ↔ tasks) all resolve.

### WP-6.4 — Final review

- **Specialist**: `code-reviewer`
- **Dependencies**: WP-6.1 … WP-6.3
- **Tasks**: Read every changed doc top-to-bottom; verify references resolve; verify no stale "TODO" / "v0" mentions; verify the doc style matches the existing canon.

---

## 8. Risk register & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| musllinux wheels missing for a desired package → source build fails | Medium | Medium | Install image carries full build toolchain. Document the pattern of "if install fails, check the package's wheel availability on PyPI" in the bootstrap script's error output. |
| Docker daemon unreachable on host | Low | High | `healthcheck` covers this; `SandboxService` returns a structured error; handlers reply gracefully rather than crashing. |
| File-path traversal bug → workspace escape | Low | Critical | `resolveWorkspacePath` is the single chokepoint; property-tested with hypothesis. Reviewed in WP-2.7. |
| Run container escapes despite all Docker settings | Very low | Critical | Defense in depth: non-root, read-only rootfs, drop-all caps, no-new-privileges, no swap, pids limit, no devices, no socket mount. All set in `runOneshot` and verified by integration test that confirms a privileged operation fails. |
| Library pool corruption mid-install | Low | Medium | `pool.lock` flock; `recover` reconciles `poolVersion` against `pip list --path` on startup; install container's `--target` is hard-coded. |
| `make test` runtime explodes when slow tests are added | Medium | Low | All Docker-touching tests marked `@pytest.mark.slow` + gated on `DOCKER_AVAILABLE`. CI runs them only when Docker is available. `make test` default behaviour unaffected. |
| Handler registration order breaks (LLMMessageHandler not last) | Medium | High | Dedicated test in WP-5.4 asserts the invariant. Reviewer checks in WP-5.6. The `add-handler` skill also reinforces this. |
| Config defaults drift between design doc and `00-defaults/sandbox.toml` | Medium | Low | WP-4.1 produces the TOML against [§3.1 of integration doc](python-sandboxing-v1-integration.md#31-defaults-toml) directly; reviewer cross-checks. |
| `bot_owners` admin check bypassed via username | Low | High | Service layer is integer-only; usernames resolved in the handler layer before the call. Tested in both WP-5.1 and WP-5.3. |

---

## 9. Verification gates per phase

The teamlead should NOT mark a phase complete without all of these green:

| Phase | Gate |
|---|---|
| 1 | `make format lint && make test` clean. Code-reviewer signed off. Every method on `SandboxManager` raises `NotImplementedError`. |
| 2 | Same as above, plus: filesystem session round-trip works in tests; path-traversal cases all rejected; lock FIFO ordering proven. |
| 3 | Same, plus: slow-marked integration tests pass with `DOCKER_AVAILABLE=1`; both Dockerfiles build cleanly; OOM/timeout detection confirmed on real Docker. |
| 4 | Default config merges cleanly via `--print-config`; bootstrap script installs the starter pack on a freshly created storage dir. |
| 5 | Bot starts with sandbox handlers registered; `/python print(1+1)` works in a test chat; admin `/sandbox_install` works for owner, rejected for non-owner. `LLMMessageHandler` still last. |
| 6 | All listed docs updated; cross-references resolve; `make format lint && make test` clean one final time. |

---

## 10. Notes for the teamlead

- **Brief every specialist with §0** (cross-cutting rules) on every dispatch, even if obvious. The naming-convention slip is the most common review finding.
- **Always dispatch `code-reviewer` between phases.** The reviewer is read-only; treat its findings as work items for the next `software-developer` dispatch.
- **Don't let any specialist invent SQL.** v0 is filesystem-only. If a sub-agent proposes `DatabaseMetadataStore`, route it back to the design doc.
- **Watch for `LLMMessageHandler` displacement.** Every handler registration change touches `manager.py`. Re-read the file after every such change.
- **Watch for `lib/`-no-bot-deps violations.** No `internal/` imports inside `lib/sandbox/`. If a specialist needs a Gromozeka type, that means the work belongs in `internal/services/sandbox/` instead.
- **Slow tests live behind `@pytest.mark.slow` + `DOCKER_AVAILABLE`.** Don't merge work that puts Docker calls into the default `make test` path.
- **Parallelism opportunities**: WP-1.1, WP-1.2, WP-1.3 can run in parallel; same for WP-2.1, WP-2.3; Phase 4 and Phase 5 entirely parallelisable after Phase 3.
- **Escalate to `architect`** if any specialist hits a design ambiguity that isn't covered by the design docs. Don't let them improvise — the design is intentionally constrained.
- **Final `make test` must pass before any merge.** Per [`AGENTS.md`](../../AGENTS.md), this is non-negotiable.

---

## 11. Out-of-scope reminders

These are deliberately deferred. If a specialist proposes any, route back to the design docs:

- TypeScript runtime
- gVisor / Firecracker backend
- Network proxy / allowlist
- `DatabaseMetadataStore`
- Persistent (long-lived) execution containers
- Per-chat `ChatSettingsKey` overrides for sandbox limits
- Package deny-lists
- Disk / output / artifact size enforcement

Any of these can be a follow-up project after v1 lands and gets real-world use.
