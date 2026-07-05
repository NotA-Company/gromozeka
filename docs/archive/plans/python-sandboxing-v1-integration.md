# Sandboxed Code Execution — Gromozeka Integration

Status: **proposed design, no code yet**
Companion to: [`python-sandboxing-v1.md`](python-sandboxing-v1.md) (the standalone library)
Scope: Gromozeka-specific glue — service singleton, configuration mapping, handlers/tools, admin surface, docs sync.

This document covers everything that depends on Gromozeka internals: how the `lib/sandbox/` library plugs into the bot, where sessionIds come from, how config flows from `ConfigManager`, what the operator-facing commands look like, and which canonical docs need to change when this lands.

---

## 1. Layering

```text
┌──────────────────────────────────────────────────────────────┐
│ internal/bot/common/handlers/                                │
│   run_python_handler.py     ← LLM-callable tool / command    │
│   sandbox_admin_handler.py  ← admin: install/remove libs     │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│ internal/services/sandbox/                                   │
│   service.py                ← SandboxService singleton       │
│                             ← maps chatId+threadId→sessionId │
│                             ← reads ConfigManager → builds   │
│                                 SandboxConfig                │
│                             ← admin authorization checks     │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│ lib/sandbox/                                                 │
│   SandboxManager — bot-agnostic                              │
└──────────────────────────────────────────────────────────────┘
```

The hard rule from [`AGENTS.md`](../../AGENTS.md): `lib/` has no bot deps. Everything Gromozeka-specific (chat IDs, `MessageId`, `bot_owners`, `ConfigManager`, handler base classes, message senders) sits in `internal/services/sandbox/` or `internal/bot/common/handlers/`. The library never imports from `internal/`.

---

## 2. `SandboxService` singleton

`internal/services/sandbox/service.py`:

```python
class SandboxService:
    """Gromozeka-aware adapter on top of lib.sandbox.SandboxManager.

    Owns the chatId+threadId -> sessionId mapping, builds SandboxConfig
    from ConfigManager, and gates admin operations on bot_owners.

    Singleton — access via SandboxService.getInstance().
    """

    @classmethod
    def getInstance(cls) -> "SandboxService": ...

    # ---- LLM-facing surface ----

    async def runCodeForChat(
        self,
        chatId: int,
        threadId: int,
        code: str,
        *,
        requiredPackages: Sequence[str] = (),
        timeoutSeconds: int | None = None,
        allowNetwork: bool = False,
    ) -> RunResult: ...

    async def readArtifact(
        self,
        chatId: int,
        threadId: int,
        path: str,
        *,
        maxBytes: int | None = None,
    ) -> FileContent: ...

    async def listArtifacts(
        self,
        chatId: int,
        threadId: int,
        *,
        recursive: bool = False,
    ) -> list[FileInfo]: ...

    # ---- Admin-facing surface ----

    async def installLibrariesAdmin(
        self,
        requesterUserId: int,
        packages: Sequence[str],
        *,
        runtime: RuntimeName = RuntimeName.PYTHON,
        upgrade: bool = False,
    ) -> LibraryInstallResult: ...

    async def removeLibrariesAdmin(
        self,
        requesterUserId: int,
        packages: Sequence[str],
        *,
        runtime: RuntimeName = RuntimeName.PYTHON,
    ) -> LibraryRemoveResult: ...

    async def listLibraries(
        self,
        *,
        runtime: RuntimeName = RuntimeName.PYTHON,
    ) -> list[PackageInfo]: ...

    async def healthcheck(self) -> HealthcheckResult: ...
```

### 2.1 sessionId mapping

```python
def _buildSessionId(self, chatId: int, threadId: int) -> str:
    return f"chat-{chatId}-thread-{threadId}"
```

Stable, includes no PII, survives bot restarts, fits the opaque-string contract of the library.

`DEFAULT_THREAD_ID = 0` is the legitimate sentinel for "no thread" per the [`AGENTS.md`](../../AGENTS.md) gotchas — it produces a valid sessionId `chat-<id>-thread-0`.

### 2.2 Admin gating

Library mutation (`installLibrariesAdmin`, `removeLibrariesAdmin`) is the only place where Gromozeka's authorization model enters. Implementation:

```python
def _ensureOwner(self, userId: int) -> None:
    owners = ConfigManager.getInstance().get("bot_owners", default=[])
    # bot_owners entries may be int IDs OR usernames (per AGENTS.md gotcha);
    # we always pass int userId here, so only check the int-typed entries
    intOwners = {entry for entry in owners if isinstance(entry, int)}
    if userId not in intOwners:
        raise PermissionError(f"User {userId} is not a bot owner")
```

(Username-based owner entries are resolved upstream by the handler before calling the service — keeps the service's signature numeric and unambiguous.)

### 2.3 Singleton initialisation

Follows the Gromozeka pattern from [`AGENTS.md`](../../AGENTS.md) (the `hasattr(self, 'initialized')` guard):

```python
def __init__(self) -> None:
    if hasattr(self, "initialized"):
        return
    self.initialized = True

    sandboxConfig = self._buildSandboxConfigFromConfigManager()
    self._manager = SandboxManager.getInstance(sandboxConfig)

    # Run startup recovery once.
    asyncio.create_task(self._manager.recover())
```

`_buildSandboxConfigFromConfigManager` is a pure function: reads `ConfigManager`, returns a `SandboxConfig`. Easy to unit-test.

---

## 3. Configuration

The library's `SandboxConfig` is built from a `[sandbox.*]` section of the merged TOML config. Defaults go in [`configs/00-defaults/sandbox.toml`](../../configs/00-defaults/) per the project's config-layering rules.

### 3.1 Defaults TOML

`configs/00-defaults/sandbox.toml`:

```toml
[sandbox]

[sandbox.storage]
root_dir = "/var/lib/gromozeka/sandbox"
dir_mode = "0700"
file_mode = "0600"

[sandbox.backend]
name = "docker"

[sandbox.backend.docker]
base_url           = "unix:///var/run/docker.sock"
image_pull_policy  = "if-not-present"

[sandbox.defaults]
runtime              = "python"
idle_ttl_minutes     = 30
hard_ttl_minutes     = 120
run_timeout_seconds  = 30

[sandbox.limits]
memory_mb              = 512
memory_swap_mb         = 512
cpu_count              = 1.0
pids_limit             = 64
timeout_seconds        = 30
timeout_grace_seconds  = 5

[sandbox.security]
user                = "1000:1000"
read_only_rootfs    = true
no_new_privileges   = true
drop_capabilities   = ["ALL"]
privileged          = false

[sandbox.concurrency]
max_queued_runs_per_session  = 4
max_concurrent_runs_global   = 8
global_queue_wait_seconds    = 60

[sandbox.gc]
enabled                                 = true
interval_seconds                        = 60
orphan_container_retention_minutes      = 10
orphan_workspace_retention_minutes      = 60
run_retention_minutes                   = 1440

[sandbox.runtimes.python]
run_image_tag        = "gromozeka-sandbox-python:run"
install_image_tag    = "gromozeka-sandbox-python:install"
run_dockerfile       = "lib/sandbox/runtimes/python/Dockerfile"
install_dockerfile   = "lib/sandbox/runtimes/python/Dockerfile.install"
lib_mount_path       = "/sandbox/libs"

[sandbox.runtimes.python.env]
PYTHONUNBUFFERED        = "1"
PYTHONDONTWRITEBYTECODE = "1"
MPLBACKEND              = "Agg"
PYTHONPATH              = "/sandbox/libs"

[sandbox.runtimes.python.install_container]
timeout_seconds = 600
memory_mb       = 1024
pids_limit      = 256

# Used by scripts/sandbox-bootstrap.py — not by the library itself.
[sandbox.bootstrap]
starter-packages = [
    "numpy",
    "pandas",
    "matplotlib",
    "scipy",
    "sympy",
    "scikit-learn",
    "pillow",
    "requests",
]
```

### 3.2 Mapping function

`internal/services/sandbox/service.py`:

```python
def _buildSandboxConfigFromConfigManager(self) -> SandboxConfig:
    cm = ConfigManager.getInstance()
    storage = StorageConfig(
        rootDir=cm.get("sandbox.storage.root_dir", required=True),
        dirMode=int(cm.get("sandbox.storage.dir_mode", default="0700"), 8),
        fileMode=int(cm.get("sandbox.storage.file_mode", default="0600"), 8),
    )
    # ... and so on for the rest of the sections
    return SandboxConfig(storage=storage, ...)
```

Keys translate from `snake_case` in TOML to `camelCase` in dataclasses — same pattern used elsewhere in the project.

---

## 4. Handlers

Per [`AGENTS.md`](../../AGENTS.md): platform-agnostic handlers live in `internal/bot/common/handlers/`. `LLMMessageHandler` **must remain the last handler** in `HandlersManager` — the sandbox handlers slot in **before** it.

### 4.1 `RunPythonHandler` (LLM tool / command)

`internal/bot/common/handlers/run_python_handler.py`:

```python
class RunPythonHandler(BaseBotHandler):
    """Handles direct /python <code> commands.

    For LLM-driven runs, a separate tool wires the same logic into the
    LLM tool-call surface — but the actual work goes through
    SandboxService.runCodeForChat() the same way.
    """

    async def newMessageHandler(
        self,
        message: EnsuredMessage,
        ...,
    ) -> HandlerResult:
        if not message.text or not message.text.startswith("/python"):
            return HandlerResult(status=HandlerResultStatus.SKIPPED)

        code = message.text.removeprefix("/python").strip()
        if not code:
            await self._sendMessage(message.chatId, "Provide code after /python")
            return HandlerResult(status=HandlerResultStatus.HANDLED)

        sandbox = SandboxService.getInstance()
        try:
            result = await sandbox.runCodeForChat(
                chatId=message.chatId,
                threadId=message.threadId,
                code=code,
            )
        except MissingDependenciesError as exc:
            await self._sendMessage(
                message.chatId,
                f"Missing packages: {', '.join(exc.missing)}. "
                f"Ask the admin to install them.",
            )
            return HandlerResult(status=HandlerResultStatus.HANDLED)
        except SessionBusy:
            await self._sendMessage(message.chatId, "Sandbox is busy, try again.")
            return HandlerResult(status=HandlerResultStatus.HANDLED)

        await self._formatAndSend(message, result)
        return HandlerResult(status=HandlerResultStatus.HANDLED)
```

`_formatAndSend` reads `stdoutPath` / `stderrPath` via `SandboxService.readArtifact(maxBytes=...)` with a sensible cap (e.g., 4 KB per stream) and formats a reply. Larger output → upload as a file via the existing storage service.

Conditional registration: only register `RunPythonHandler` if `bot.handlers.run_python.enabled` is `true` in the config.

### 4.2 `SandboxAdminHandler` (operator commands)

`internal/bot/common/handlers/sandbox_admin_handler.py`:

```python
class SandboxAdminHandler(BaseBotHandler):
    """Implements operator-only commands:
        /sandbox_install <pkg> [<pkg>...]
        /sandbox_remove  <pkg> [<pkg>...]
        /sandbox_list
        /sandbox_health
    """

    async def newMessageHandler(self, message: EnsuredMessage, ...) -> HandlerResult:
        if not (message.text and message.text.startswith("/sandbox_")):
            return HandlerResult(status=HandlerResultStatus.SKIPPED)

        # Owner check — usernames resolved here, then numeric id passed down.
        userId = await self._resolveOwnerOrReject(message)
        if userId is None:
            return HandlerResult(status=HandlerResultStatus.HANDLED)

        sandbox = SandboxService.getInstance()
        # dispatch on subcommand, call sandbox.installLibrariesAdmin(userId, ...)
        # / sandbox.removeLibrariesAdmin(userId, ...) / sandbox.listLibraries() /
        # sandbox.healthcheck()
        ...
```

This handler must also be registered **before** `LLMMessageHandler`.

### 4.3 Registration order

In `internal/bot/common/handlers/manager.py` (illustrative — actual registration code uses the existing ordered-list mechanism):

```python
handlers = [
    # ... existing handlers ...
    SandboxAdminHandler(),               # gate admin commands first
    RunPythonHandler(),                  # before LLMMessageHandler
    LLMMessageHandler(),                 # MUST stay last
]
```

---

## 5. LLM tool integration

If the LLM is allowed to call Python execution as a tool (separate from the `/python` command), wire it as a new tool in `internal/services/llm/`. The tool's implementation calls `SandboxService.runCodeForChat(...)` exactly like the handler does. The tool description should make clear to the LLM that:

- Required packages must be in the runtime library pool — if missing, the user (operator) must install them.
- Network is off by default; only set `allowNetwork=True` when truly needed.
- Workspace files persist across calls in the same chat/thread; the model can leave intermediate data behind.

Rate-limiting, content moderation, and per-chat allowlists for the tool live in the LLM service layer — **not** in `SandboxService` or `SandboxManager`.

---

## 6. Bootstrap script

`scripts/sandbox-bootstrap.py`:

```python
"""Install the starter Python library set into the sandbox lib pool.

Run once on a fresh deployment, or whenever the starter list changes.

Usage:
    ./venv/bin/python3 scripts/sandbox-bootstrap.py
        [--config-dir configs/00-defaults]
        [--config-dir configs/local]
        [--runtime python]
        [--upgrade]
"""
```

Behaviour:

1. Initialise `ConfigManager` with the supplied config dirs.
2. Build a `SandboxConfig` and `SandboxManager`.
3. Read `sandbox.bootstrap.starter-packages`.
4. Call `manager.prepareRuntime(...)` to ensure images exist.
5. Call `manager.installRuntimeLibraries(packages, upgrade=upgrade)`.
6. Print a summary table (installed / skipped / failed) and the resulting `poolVersion`.

Errors propagate with non-zero exit. No interactive prompts — safe for use in CI / provisioning.

---

## 7. Database impact

None. The library uses `FilesystemMetadataStore` in v0; no schema changes to Gromozeka's SQLite/PostgreSQL/MySQL providers. A future `DatabaseMetadataStore` (out of scope) would introduce its own migration; that migration must follow the [`add-database-migration`](../../.agents/skills/add-database-migration/SKILL.md) skill and respect the SQL portability rules in [`docs/sql-portability-guide.md`](../sql-portability-guide.md).

---

## 8. Per-chat settings (out of scope for v0, noted for later)

If we want per-chat overrides of sandbox behaviour later (e.g., extended timeout per chat, custom resource limits, opt-in to network), we add them via [`ChatSettingsKey`](../../.agents/skills/add-chat-setting/SKILL.md). Candidate keys for the future:

- `sandbox.run_timeout_seconds` (int, default = config default)
- `sandbox.memory_mb` (int)
- `sandbox.allow_network` (bool)
- `sandbox.max_artifact_bytes_per_reply` (int, controls how much stdout/stderr the bot embeds inline before falling back to file upload)

Each would follow the four-site recipe in the [`add-chat-setting`](../../.agents/skills/add-chat-setting/SKILL.md) skill. Not part of M5 unless explicitly requested.

---

## 9. Quality gates

When the integration lands, run the standard pipeline per the [`run-quality-gates`](../../.agents/skills/run-quality-gates/SKILL.md) skill:

```bash
make format lint
make test
```

`make test` includes the new tests under `tests/lib/sandbox/`. Integration tests that require Docker are gated on a `DOCKER_AVAILABLE` env check and skipped by default in CI unless Docker is present.

---

## 10. Documentation sync

When M3 lands (library):

- New section in [`docs/llm/libraries.md`](../llm/libraries.md): `lib/sandbox/` — short description, link to this design doc and the library design doc.

When M5 lands (integration):

- [`docs/llm/services.md`](../llm/services.md): add `SandboxService` to the singleton service list with its public surface.
- [`docs/llm/handlers.md`](../llm/handlers.md): add `RunPythonHandler` and `SandboxAdminHandler`, including the "registered before `LLMMessageHandler`" invariant.
- [`docs/llm/configuration.md`](../llm/configuration.md): document the `[sandbox.*]` config section keys.
- [`docs/llm/architecture.md`](../llm/architecture.md): one paragraph + diagram update showing the sandbox layer.
- [`docs/llm/tasks.md`](../llm/tasks.md): a new gotcha entry — "stdout/stderr live in workspace files, not in `RunResult` bytes; readFile to fetch them".
- [`AGENTS.md`](../../AGENTS.md): add `lib/sandbox/` and `internal/services/sandbox/` to the layout cheatsheet.
- [`docs/developer-guide.md`](../developer-guide.md): "Bootstrapping the sandbox" section — how to run `scripts/sandbox-bootstrap.py`, prerequisites (Docker installed, storage dir writable by the configured UID, etc.).

The [`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md) skill should be loaded by the implementer at the end of M5.

---

## 11. Milestones (Gromozeka-side)

### M5.1 — Service skeleton

- `internal/services/sandbox/service.py` — `SandboxService` singleton, `_buildSessionId`, `_ensureOwner`, config builder
- Unit tests with a fake `SandboxManager` injected
- Wire singleton initialisation into the bot startup path

### M5.2 — Handlers

- `RunPythonHandler` with `/python <code>` command
- `SandboxAdminHandler` with `/sandbox_*` commands
- Conditional registration in `HandlersManager` (config-gated), before `LLMMessageHandler`
- Tests with real `EnsuredMessage` per the [`add-handler`](../../.agents/skills/add-handler/SKILL.md) skill

### M5.3 — LLM tool (optional, depending on direction)

- New tool descriptor in the LLM service
- End-to-end test: LLM tool call → `SandboxService.runCodeForChat` → formatted reply

### M5.4 — Docs sync

- Load the `update-project-docs` skill
- Update every file listed in §10
- Final `make format lint && make test` pass

---

## 12. Open questions for the integration

1. **Default UID for the sandbox containers.** Default `1000:1000` works on most hosts but may collide with an existing user. Should the bootstrap script auto-detect a free UID and stamp it in `configs/local/sandbox.toml`? Or document "edit the config yourself"? Suggested: document for v0.

2. **Storage path on disk.** `/var/lib/gromozeka/sandbox` requires root to create. Either ship a systemd tmpfiles snippet, document the `mkdir + chown` once at install time, or let the bootstrap script create it on first run (requires sudo). Suggested: document at install time + offer a `--init-storage` flag on the bootstrap script.

3. **Whether `/python` is a chat-level toggle from day one.** Some chats may want it on by default, some off. Adding a chat setting at M5.2 vs deferring it to a follow-up. Suggested: defer — config-level gate is enough for v0.

4. **Per-chat resource overrides.** Same — defer until there's demand.

5. **What gets sent back when output exceeds the inline cap.** Embed first N KB + upload full log as a file? Always upload? Suggested: embed first 4 KB of each stream + upload the full files using the existing storage service path.
