# Plan: `/sandbox update` — Sandbox Library Pool Updates v1

Status: **Design — ratified 2026-09-04, revised same day (D1 superseded: post-remove adopted after design review)** (D2–D4 user-approved, unchanged; D5–D7 resolved in this doc, unchanged)
Date: 2026-09-04
Companion: [`python-sandboxing-v1.md`](python-sandboxing-v1.md) — retained design reference for `lib/sandbox/`
Tracking: [`TODO.md`](../../TODO.md) item `- [ ] /sandbox update to update packages`

> Design document only — no production code is changed by this file. Implementation
> runs in three phases (§14) dispatched to `software-developer`; the final
> documentation pass must load the `update-project-docs` skill.

---

## 1. Context

Verified facts this design builds on:

- **Handler.** [`SandboxHandler`](../../internal/bot/common/handlers/sandbox.py) dispatches `/sandbox` subcommands (`files`, `read`, `status`, `packages`, `install`) in `sandbox_command` (sandbox.py:898-919). Access is gated by `_checkSandboxAccess` (sandbox.py:629-656: `sandbox.enabled` + `allow-sandbox` chat setting); `/sandbox install` additionally requires `isBotOwner` (sandbox.py:1168). The decorator `helpMessage` (sandbox.py:850) and the usage text (sandbox.py:886-893) **already omit the `packages` subcommand** — this change fixes that drift.
- **Manager.** [`SandboxManager.installRuntimeLibraries`](../../lib/sandbox/manager.py) (manager.py:904-1054) validates specs (`_validatePackageSpec`, manager.py:1264-1287: shell-metacharacter rejection, then PEP 508 via `packaging.requirements.Requirement`), takes the cross-process `fcntl` pool lock ([`locks.poolLock`](../../lib/sandbox/locks.py), raises [`LibraryPoolLocked`](../../lib/sandbox/errors.py) if held), and runs a one-shot install container executing `PythonRuntime.installCommand` (pip `install --target /sandbox/libs --no-cache-dir --no-input [--upgrade]`). On success the container is removed and `_refreshPackageList` (manager.py:1289-1380) rewrites `meta/runtimes/python/packages.json` via `pip list --format=json --path`; on failure the container is **kept** for `docker logs` post-mortem and reaped by GC.
- **Pool.** Package state is GLOBAL per-runtime, shared by all chats: host dir `<sandbox.storage.root-dir>/runtimes/python/libs`, mounted read-only at `/sandbox/libs` (PYTHONPATH) in run containers. No DB. `packages.json` is derived metadata, not truth.
- **Upgrade plumbing exists but is unusable as-is.** `installRuntimeLibraries(upgrade=True)` only adds pip `--upgrade`; with `pip install --target`, `--upgrade` does **not** remove the old version — duplicate `.dist-info` dirs accumulate and import order becomes nondeterministic. Only `scripts/sandbox_bootstrap.py --upgrade` uses the flag; the bot never does. No update-all or outdated logic exists anywhere. (This is why the design carries a dedup pass at all.)
- **Pre-remove (original D1) rejected in design review.** The initially ratified mechanism — delete old dist-infos via RECORD first, then bare `pip install` of the names — has three defects: (1) **holes on failure:** pip failing after pre-remove leaves packages deleted-but-not-reinstalled; (2) **wasteful re-downloads:** a bare install of a pre-removed name reinstalls the SAME version even when nothing newer exists — with `--no-cache-dir`, every update re-downloads the whole pool (~100+ MB for the scientific starter set) even when fully current, while `pip install --upgrade` skips already-satisfied requirements for free; (3) **dependency-induced duplicates (a genuine bug):** pre-remove deletes only the REQUESTED names — upgrading A that pulls dep B 2.0 while B 1.0 is in the pool leaves pip `--target`-installing B 2.0 alongside B 1.0, the exact duplicate-dist-info roulette this design exists to prevent. The revised mechanism (§4.1) removes AFTER pip and reconciles ALL names, avoiding all three.

## 2. Goals / Non-goals

### Goals

1. `/sandbox update [packages...]` — update all or selected packages in the Python sandbox pool, owner-only.
2. Post-upgrade deduplication (snapshot + RECORD set-subtraction) so updates never leave duplicate `.dist-info` dirs AND never leave holes — old versions survive failed updates.
3. Old→new diff report in the reply, derived from `packages.json` snapshots before/after.
4. Reuse the existing install-container machinery: same image, limits, lock, failure semantics.

### Non-goals

- **LLM tool for update.** Destructive, owner-only — excluded by design (same reasoning as install being admin-only; see `docs/llm/sandbox.md` §"Package installation is admin-only").
- `pip list --outdated` preview round-trip (ratified: no-arg updates immediately, D2).
- Image rebuild / `rebuildImage` changes; per-chat pools; scheduled/auto updates; pinning or rollback.
- Changing `/sandbox install` semantics.

## 3. Command surface

```text
/sandbox update                 → update ALL packages in the pool, report diff
/sandbox update <packages...>   → update named packages (same spec grammar as install)
```

- **Access:** `_checkSandboxAccess` (dispatcher-level, unchanged) **and** `isBotOwner` (inside the handler method, mirroring `_handleInstallCommand`). No tier checks.
- **Dispatch:** add to `sandbox_command`'s chain (sandbox.py:910-913):

  ```python
  elif subcommand == "update":
      await self._handleUpdateCommand(ensuredMessage, sessionId, subArgs, manager, typingManager)
  ```

- **Method name:** `_handleUpdateCommand` (follows `_handleInstallCommand` precedent).
- **Help drift fix (same change):** decorator `helpMessage` becomes
  `" <files|read|status|packages|install|update> [args]: Manage sandbox workspace files and packages."`;
  usage text gains `packages` and `update <packages...> - Update Python packages (admin only)` lines;
  the module docstring command list (sandbox.py:7-13) gains the update line.

## 4. Design overview

### 4.1 Mechanism — post-remove: upgrade, then dedup (D1, revised after design review)

pip's `--target` + `--upgrade` never deletes the old version (duplicates remain), while pre-removing before pip opens holes on failure and re-downloads the world (§1). The revised mechanism removes AFTER pip, reconciling observed reality instead of predicting it. Inside a single one-shot **update container** (the `gromozeka-sandbox-python:install` image, pool mounted rw at `/sandbox/libs`), the helper performs, in order:

1. **Snapshot.** Enumerate `*.dist-info` dirs in the pool → set of (canonicalName, version). Names are canonicalized on both sides (PEP 503: lowercase, runs of `-_.` → `-`) — `Foo_Bar` matches `foo-bar`. If the pool cannot be enumerated → exit non-zero BEFORE running pip (no partial state).
2. **Upgrade.** Run **one** pip invocation: `pip install --target <poolDir> --no-cache-dir --no-input --upgrade <specs>`, where specs = user specs (named update) or the bare canonical names enumerated in step 1 (update-all). Pip's default `--upgrade-strategy only-if-needed` is kept — deps churn only when required, and the dedup pass reconciles whatever does change. Already-current packages hit "Requirement already satisfied": untouched, zero download.
3. **Dedup — runs ALWAYS, even when pip exits non-zero.** Re-enumerate dist-infos; `newOnes = current − snapshot`. For every canonical name that now has BOTH old (snapshot) and new dist-infos: delete the files in `old RECORD − union(new RECORDs)` (set subtraction), then `shutil.rmtree` the old dist-info dirs (jail-checked). The subtraction is the load-bearing correctness rule: after an in-place `--target` upgrade, files listed in BOTH versions' RECORDs (e.g. `numpy/__init__.py`) have been overwritten and belong to the NEW install — deleting per old RECORD blindly would corrupt it. Dependency-induced duplicates (upgrading A pulls B 2.0 next to pool B 1.0) present the same old+new shape and are cleaned by the same pass. Names with pre-existing duplicates where NO new dist-info appeared this run are left in place and warned on stderr (no keeper can be picked without version comparison — documented degradation).
4. **Exit code = pip's exit code.** The manager's failure handling (keep container for `docker logs`, GC reap) is unchanged. Dedup warnings go to stderr and never change the exit code.

The helper is defensive: every dedup deletion target is resolved and jailed to the pool root (`resolve()` + `relative_to`, the [`resolveWorkspacePath`](../../lib/sandbox/storage.py) idiom, storage.py:100-109); a package whose old RECORD is missing/unreadable during dedup is **skipped entirely** (never delete what we cannot account for — the duplicate remains, warned; safe degradation); symlinks that resolve outside the pool are never followed.

### 4.2 Update-container command shape

Single argv, **no shell**:

```text
python /sandbox/pool_update_packages.py --pool-dir /sandbox/libs [--all] <spec...>
```

The helper itself invokes pip via `subprocess.run([sys.executable, "-m", "pip", "install", "--target", poolDir, "--no-cache-dir", "--no-input", "--upgrade", *specs])` and propagates pip's exit code (dedup runs regardless; §4.1). Accepted tradeoff: the pip flag set is duplicated between `PythonRuntime.installCommand` and the helper (cross-container boundary makes sharing code awkward); a runtime test asserts both stay in parity — the helper's exported `PIP_INSTALL_ARGS` equals installCommand's base flags plus `--upgrade` — by importing the constant host-side.

Mounts: pool rw at `/sandbox/libs` (as install) **plus** the helper script file read-only at `/sandbox/pool_update_packages.py`. Labels: `sandbox.managed=true`, `sandbox.purpose="update"`, `sandbox.runtime="python"`. Limits/network/user/capDrop: identical to the install container. The manager pre-checks the helper file exists on the host (a missing file-bind silently becomes a directory in Docker) and raises `ConfigError` with a clear message otherwise.

### 4.3 Helper delivery: mounted script, not baked into the image (D5)

**Decision: mount.** The helper lives at `lib/sandbox/runtimes/python/pool_update_packages.py` (new file — named for its orchestrating role, upgrade + dedup, not just removal — next to [`Dockerfile.install`](../../lib/sandbox/runtimes/python/Dockerfile.install)); the manager mounts it read-only into the update container.

Rationale:

- `prepareRuntime` builds images only when missing — a baked helper **silently diverges** from the repo copy until someone runs `rebuildImage`. A mounted script is always the version the bot runs.
- The mounted file is a normal versioned, linted, **importable** module — unit-testable host-side as `lib.sandbox.runtimes.python.pool_update_packages`, visible to pyright/flake8/black and the `import main` cycle check. Image-baked copies are invisible to all of that.
- No image rebuild on helper changes (the install image carries a full build toolchain; rebuilds are slow).

Costs, accepted: the host must have the repo checkout at runtime (already required — `install-dockerfile` is a repo-relative path today) and the mount adds one config-derived host path. Host path is derived, **not** configured: `Path(installDockerfile).parent / "pool_update_packages.py"` — zero new config keys, same directory convention as the Dockerfiles.

### 4.4 No new configuration

Explicitly: **no changes to [`configs/00-defaults/sandbox.toml`](../../configs/00-defaults/sandbox.toml) and no new keys anywhere.** The existing `[sandbox.runtimes.python.install-container]` values apply unchanged — timeout 600 s / 1024 MB / 256 pids — because the update is one pip invocation for the whole batch (bounded by the budget a full starter-set install already consumes, and typically less — already-satisfied specs are skipped) plus fast in-container snapshot/dedup file operations. `timeoutSeconds` mirrors install's override parameter.

## 5. Manager / Runtime API changes

### 5.1 `SandboxManager.updateRuntimeLibraries` — dedicated method (D6)

**Decision: new method** (option a), not an update-mode flag on `installRuntimeLibraries`. Reasons: upgrade+dedup must run in **one** container under **one** `poolLock` hold (composing two `installRuntimeLibraries` calls opens a race window with the pool half-mutated and doubles the failure domains); `install`'s tested contract stays "add packages" — never implicitly destructive; the update flow needs its own inputs (`None` = all), its own label, and a rich diff result.

```python
async def updateRuntimeLibraries(
    self,
    packages: Sequence[str] | None,
    *,
    runtime: RuntimeName,
    timeoutSeconds: int | None = None,
) -> LibraryUpdateResult:
    """Update packages in the runtime library pool.

    Upgrades via a single in-container pip ``--upgrade`` run, then dedups
    (RECORD set-subtraction, inside the update container), so no duplicate
    dist-info dirs remain and a failed run never leaves holes. On success
    the update container is removed and the package list refreshed; on
    failure the container is kept for ``docker logs`` post-mortem (same
    contract as installRuntimeLibraries).

    Args:
        self: The SandboxManager instance.
        packages: Specs to update (PEP 508, same grammar as install), or
            None to update every package enumerated from the pool.
        runtime: The runtime whose pool to update.
        timeoutSeconds: Timeout override; None falls back to the runtime's
            ``install-container.timeout-seconds`` config value.

    Returns:
        LibraryUpdateResult with the old→new diff and failure details.

    Raises:
        InvalidPackageSpec: If every named spec fails validation.
        LibraryPoolLocked: If another process holds the pool lock.
        UnknownRuntime: If the runtime is not available.
        ConfigError: If the update helper script is missing on the host.
    """
```

Flow: validate named specs via `_validatePackageSpec` (partial failures proceed, recorded in `failedSpecs`); snapshot old versions from metadata; early-return "empty" when `packages is None` and the pool has no `*.dist-info`; `async with locks.poolLock(...)` → build one `ContainerSpec` via `runtimeImpl.updateCommand(...)` with the helper mount → `runOneshot` → on success `removeContainer` + `_refreshPackageList` (best-effort), on failure keep the container; compute the diff from before/after metadata reads.

### 5.2 Result types (`lib/sandbox/types.py`)

```python
@dataclass(slots=True)
class PackageUpdate:
    """Version transition of one package across an update run."""

    name: str                    # canonical name (PEP 503)
    oldVersion: str | None       # None = no prior version recorded in packages.json
    newVersion: str | None       # None = absent from the pool after the run


@dataclass(slots=True)
class LibraryUpdateResult:
    """Outcome of a SandboxManager.updateRuntimeLibraries call."""

    runtime: RuntimeName
    success: bool                # update container exited 0
    updated: list[PackageUpdate]     # newVersion != oldVersion
    unchanged: list[PackageUpdate]   # identical versions before and after
    failedSpecs: list[tuple[str, str]]  # (spec, reason) rejected at validation
    containerId: str | None      # kept container id on failure (docker logs hint)
    metadataRefreshed: bool      # False → diff may under-report; stale packages.json
```

### 5.3 `Runtime` ABC + `PythonRuntime`

Two abstract additions to [`Runtime`](../../lib/sandbox/runtimes/base.py) (cohesive: the ABC is "build command for X"; no runtime exists besides Python today, so adding abstracts forces future runtimes to decide explicitly):

```python
@abstractmethod
def updateCommand(self, packages: Sequence[str] | None) -> list[str]:
    """Build the command-line invocation for the update container.

    Args:
        packages: Package specs to update, or None to update every package
            present in the pool (helper-side enumeration).

    Returns:
        Command and arguments as a single argv list (no shell).
    """
    ...

@abstractmethod
def updateHelperHostPath(self) -> Path:
    """Return the host-side path of the update helper script.

    The manager mounts this file read-only into the update container.

    Returns:
        Path derived from the install Dockerfile's directory.
    """
    ...
```

`PythonRuntime` implements both — `UPDATE_HELPER_CONTAINER_PATH = "/sandbox/pool_update_packages.py"` class constant; `updateCommand` builds `["python", UPDATE_HELPER_CONTAINER_PATH, "--pool-dir", libMountPath]` + (`["--all"]` if `packages is None` else the specs); `updateHelperHostPath` returns `Path(self._config.installDockerfile).parent / "pool_update_packages.py"`.

### 5.4 Helper script contract (`pool_update_packages.py`)

Stdlib only (the alpine image has no `packaging`): local PEP 503 canonicalization and a name-extraction regex (`^[A-Za-z0-9][A-Za-z0-9._-]*`) for spec→name. The contract is the four steps of §4.1, in order: (1) snapshot enumeration — exit non-zero before pip if the pool cannot be enumerated; (2) the single pip `install --upgrade` invocation; (3) the set-subtraction dedup pass — always executed, even after pip failure, warnings to stderr only; (4) exit-code passthrough — the process exit code equals pip's. Exports `PIP_INSTALL_ARGS` for the flag-parity test.

## 6. Update-all name source: the pool itself (D7)

**Decision:** update-ALL is driven by dist-info enumeration **inside the container** (helper `--all`); `packages.json` provides only the old-version baseline for the diff and the empty-pool check.

Justification: the pool is ground truth — it is what runs actually import; enumerating in-container reuses the helper's dist-info scanning (no second implementation); host-side dist-info name parsing (splitting name from version on hyphens, e.g. `scikit-learn-1.5.0.dist-info`) is fragile and avoided entirely. This also **self-heals drift in both directions**: pool-only packages get updated and recorded; `packages.json`-only entries vanish from the diff baseline after the refresh rewrites metadata from reality (reported as `newVersion=None` if genuinely gone). The empty-pool early check is a host-side existence glob (`any(libsDir.glob("*.dist-info"))`) — no name parsing. The enumerated names now feed `pip --upgrade` as bare specs, and the snapshot doubles as the old side of the dedup comparison (§4.1) — one enumeration serves both roles.

## 7. Handler changes

`_handleUpdateCommand(ensuredMessage, sessionId, packagesArg, manager, typingManager)` mirrors `_handleInstallCommand`:

1. `isBotOwner(ensuredMessage.sender)` gate (identical reply on failure).
2. `packages = packagesArg.strip().split()`; empty → `None` (update all).
3. Ack message (`"Updating packages..."` / `"Updating all packages..."`), then
   `result = await manager.updateRuntimeLibraries(packages=packages or None, runtime=RuntimeName.PYTHON)`.
4. Render per §8.

Exception handling: `InvalidPackageSpec` (all specs failed), `LibraryPoolLocked` (**new import** from `lib.sandbox` — currently unused in the handler), generic `Exception` with `logger.error` — the install pattern (sandbox.py:1210-1222). Dispatcher, usage text, `helpMessage`, and module docstring updated as §3.

## 8. Reply formats

```text
Sandbox packages updated (python):
  numpy 1.26.4 → 2.1.0
  requests → 2.32.3 (no prior version recorded)
Unchanged (3): scipy, sympy, pillow
Note: in-flight sandbox runs may pick up mixed versions until they finish.
```

- `oldVersion is None` renders as `name → <new> (no prior version recorded)` (new install or stale metadata).
- All current: `All sandbox packages are up to date (python, N packages).`
- Empty pool (no-arg only): `Nothing installed in the python sandbox pool. Use /sandbox install <packages...> first.`
- Partial validation failures append: `Skipped invalid specs: <spec> (<reason>), ...`
- Container failure: `Update failed (pip error); completed upgrades are clean, the rest keep their old versions — re-run /sandbox update. Keeping container <id> for inspection (docker logs <id>).`
- Lock busy: `Another sandbox install/update is in progress, try again later.`

The in-flight note line is the ratified D3 documentation-in-reply.

## 9. Edge cases & failure semantics

| Case | Behavior |
|---|---|
| Pool empty, no-arg | Early return; "Nothing installed" reply; no container started |
| Pool not enumerable (snapshot fails) | Helper exits non-zero BEFORE pip runs — no partial state; container kept like any failure |
| Named package not installed | Absent from the snapshot; pip installs fresh; dedup no-ops for it; reported as updated with `oldVersion=None` |
| pip failure mid-batch | Dedup still runs (§4.1): succeeded packages are clean, failed ones keep their old versions — no holes, no duplicates; container kept (`docker logs`); reply says to re-run |
| Already-satisfied specs | pip skips ("requirement already satisfied"); untouched, zero download |
| Same file path in both old and new RECORDs (e.g. `numpy/__init__.py`) | Subtraction keeps it — the file has been overwritten and belongs to the new install; deleting per old RECORD blindly would corrupt it (test-pinned) |
| Dependency-induced duplicate (upgrading A pulls B 2.0 next to pool B 1.0) | Handled naturally by dedup: B has old+new dist-infos → B 1.0 removed, B 2.0 intact — this was a genuine bug in the pre-remove design |
| Old RECORD missing/unreadable during dedup | Skip that package entirely (warn); duplicate remains — safe degradation, never delete what we cannot account for |
| Pre-existing duplicate not touched this run (no new dist-info for that name) | Left in place, warned on stderr (keeper needs version comparison — documented degradation) |
| RECORD entry escaping pool (`../..`, absolute, symlink out) | Entry skipped, logged; jail check never deletes outside the pool root |
| `_refreshPackageList` fails after success | Result `metadataRefreshed=False`; reply rendered from stale metadata may show "unchanged" — acceptable, logged |
| All named specs invalid | `InvalidPackageSpec` raised before any container starts |
| Update container OOM/timeout | Same `success=False` path as install; GC reaps kept containers per `sandbox.gc.orphan-container-retention-minutes` |
| Docker file-bind footgun (helper missing on host) | Pre-checked; `ConfigError` with the derived path in the message |

## 10. Concurrency notes

- The whole update (snapshot + upgrade + dedup) holds `locks.poolLock` once — mutually exclusive with installs and other updates cross-process. `LibraryPoolLocked` propagates to the lock-busy reply.
- **In-flight runs (ratified D3 — accepted hazard):** run containers mount the pool read-only; mutating it mid-run can break an executing run — modules already imported survive, new imports may fail or resolve to mixed versions. Owner-triggered and rare; documented in the reply text (§8) and `docs/llm/sandbox.md`. No waiting machinery.
- Update-all timeout: one pip invocation for the batch within the existing 600 s install-container budget (§4.4).

## 11. Security review of the helper

- **Inputs:** names from pool dist-info dirs (pool content) and user specs — but user specs are already validated host-side by `_validatePackageSpec` (metacharacters, `-` prefix, PEP 508) before reaching the container.
- **No shell anywhere:** container command is a single argv list; the helper execs pip via `subprocess.run` argv — no `sh -c`, no interpolation, no quoting surface.
- **Jail:** every dedup deletion target is `(distInfoDir / recordEntry).resolve()`-d and checked `relative_to(poolRoot.resolve())` — symlink and traversal escapes are caught by resolution, exactly the `resolveWorkspacePath` idiom. Files are deleted individually (`unlink`); the old dist-info dir via `shutil.rmtree` only after its own jail check.
- **Subtraction is a correctness invariant, not just security hygiene:** files listed in both old and new RECORDs have been overwritten by the new install and must survive the dedup; deleting per old RECORD blindly would corrupt the new version. Test-pinned (§12).
- **Canonicalization** on both sides (PEP 503) prevents both missed matches and wrong-package matches from case/separator variants.
- **Container hardening** identical to install: non-root user, `capDrop ALL`, `no-new-privileges`, network bridge (pip needs it), helper mounted read-only.

## 12. Testing plan

All new tests under [`tests/`](../../tests/) only (no collocated). Regression framing: tests that encode the ratified behaviors must fail without the change.

- **`tests/lib/sandbox/runtimes/test_pool_update_packages.py` (new):** RECORD parsing (hash/size columns, blank lines); canonical-name matching (`Foo_Bar` ↔ `foo-bar`); jail rejection (`../../../escape`, absolute paths, symlink pointing outside pool); **subtraction correctness** (old-only files deleted; files listed in both RECORDs kept); **same-path-overwrite survival** (a file listed in both old and new RECORDs still exists afterwards and is the new install's copy); **dedup runs despite pip non-zero exit, and the process exit code equals pip's** (monkeypatched `subprocess.run` returning 1); **dep-duplicate cleanup** (A's upgrade adds B 2.0 alongside B 1.0 → B 1.0 removed, B 2.0 intact); **already-satisfied no-op** (pip exit 0, nothing deleted); **snapshot failure exits non-zero before pip** (pip never invoked); **pre-existing duplicates warn + keep**; `--all` enumeration (specs = bare canonical names from the snapshot); pip invocation asserted via monkeypatched `subprocess.run` (no network; `--upgrade` present).
- **`tests/lib/sandbox/test_manager.py` (extend):** `updateCommand` shape passed to backend (None → `--all`, named → specs); all-specs-invalid raises `InvalidPackageSpec` with no container; `LibraryPoolLocked` propagates (pre-hold the flock); failure keeps container (`removeContainer` not called, `containerId` set) and success removes + refreshes; diff computed from metadata before/after; empty-pool no-arg early return with no backend call.
- **`tests/lib/sandbox/runtimes/test_python_runtime.py` (extend):** `updateCommand` single-argv no-`sh -c` shape; `--all` vs specs; `updateHelperHostPath` derived from `installDockerfile` parent; helper `PIP_INSTALL_ARGS` parity with `installCommand` flags (shared set identical; `--upgrade` the only addition).
- **`tests/bot/test_sandbox.py` (extend):** sandbox disabled / `allow-sandbox` false → denied; non-owner → denied; no-args → manager called with `None`; named → specs passed; diff rendering (updated / unchanged / no-prior-version lines); failure reply contains container id and the keep-old-versions phrasing; lock-busy reply; empty-pool reply; **regression: usage/help text lists all six subcommands** (fails today — `packages` is missing).

## 13. Documentation-sync plan

| Doc | Change |
|---|---|
| [`docs/llm/sandbox.md`](../llm/sandbox.md) | §Bot Integration: add `/sandbox update`; note update semantics (upgrade-then-dedup post-remove, pool-driven `--all`), kept-container + in-flight hazard notes |
| [`docs/llm/handlers.md`](../llm/handlers.md) | `SandboxHandler` row: add `update` to the `/sandbox` subcommand list (and fix the missing `packages`) |
| [`CHANGELOG.md`](../../CHANGELOG.md) | `## [Unreleased]` → Added: `/sandbox update [packages...]` with old→new diff |
| [`TODO.md`](../../TODO.md) | Line 3 checkbox → `[x]` |

No changes: `docs/llm/configuration.md` (no new config keys), `docs/llm/architecture.md` / `docs/llm/index.md` (no new subsystem), `docs/llm/libraries.md` (manager behavior documented in `sandbox.md`), database docs (no schema).

## 14. Implementation phases

### Phase 1 — `lib/sandbox` core (software-developer, ~8 steps)

Files: `lib/sandbox/runtimes/python/pool_update_packages.py` (new); `lib/sandbox/runtimes/base.py`; `lib/sandbox/runtimes/python/runtime.py`; `lib/sandbox/types.py`; `lib/sandbox/manager.py`; `tests/lib/sandbox/runtimes/test_pool_update_packages.py` (new); `tests/lib/sandbox/runtimes/test_python_runtime.py`; `tests/lib/sandbox/test_manager.py`.

Acceptance: `make format lint` clean; `make test` green; helper jail/canonicalization/subtraction tests red when the checks are removed (mutation check); no handler touched.

### Phase 2 — handler wiring

Files: `internal/bot/common/handlers/sandbox.py` (`_handleUpdateCommand`, dispatcher branch, usage text, `helpMessage`, module docstring, `LibraryPoolLocked` import); `tests/bot/test_sandbox.py`.

Acceptance: lint/test green; usage + help list all six subcommands; owner/access gating covered by tests.

### Phase 3 — docs sync + bookkeeping (load `update-project-docs` skill)

Files: the four docs in §13.

Acceptance: `make check-docs` passes; `CHANGELOG.md` has the Added entry; `TODO.md` line 3 checked.

---

## 15. Risks & open items

- **Subtraction-logic subtlety.** Dedup deletes `old RECORD − union(new RECORDs)`; getting it wrong in either direction corrupts the new install (deleting shared files) or strands old files (never deleting them). Mitigated by test-pinned same-path-survival and subtraction-correctness cases (§12). The pre-remove design's holes-on-failure risk is gone by construction — old versions are only deleted after their replacements exist.
- **Unreadable old RECORD during dedup** leaves a warned duplicate until manual cleanup — accepted degradation (never delete what we cannot account for).
- **pip layout surprises** (unexpected dist-info naming/placement) — mitigated: dedup is snapshot-driven (compares before/after dist-info inventories), not layout-assumed.
- **Helper pip-flag duplication** with `installCommand` — mitigated by the parity test (§12).
- **Repo checkout required on the host** for the helper mount — already implied by repo-relative `install-dockerfile`; flagged in `sandbox.md` notes.
- No open design questions remain; implementation may surface naming/test-details, to be resolved in review.
