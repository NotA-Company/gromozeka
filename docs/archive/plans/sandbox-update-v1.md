# Plan: `/sandbox update` — Sandbox Library Pool Updates v1 (revision 2)

Status: **Design — ratified 2026-09-04, revision 2 (staged install + atomic swap; spike-driven)**
Date: 2026-09-04 (revision 2)
Companion: [`python-sandboxing-v1.md`](python-sandboxing-v1.md) — retained design reference for `lib/sandbox/`
Tracking: [`TODO.md`](../../TODO.md) item `- [ ] /sandbox update to update packages`

> Design document only — no production code is changed by this file. Implementation
> runs in four phases (§14) dispatched to `software-developer`; the final
> documentation pass must load the `update-project-docs` skill.

---

## 1. Context

Verified facts this design builds on:

- **Handler.** [`SandboxHandler`](../../internal/bot/common/handlers/sandbox.py) dispatches `/sandbox` subcommands (`files`, `read`, `status`, `packages`, `install`) in `sandbox_command` (sandbox.py:904-913). Access is gated by `_checkSandboxAccess` (`sandbox.enabled` + `allow-sandbox` chat setting); `/sandbox install` additionally requires `isBotOwner` (sandbox.py:1168). The decorator `helpMessage` (sandbox.py:850) omits `packages` (and `update`); the usage text (sandbox.py:886-893) already lists `packages` but lacks `update`; the module docstring (sandbox.py:7-13) gains the update line.
- **Manager.** [`SandboxManager.installRuntimeLibraries`](../../lib/sandbox/manager.py) (manager.py:909-1059) validates specs (`_validatePackageSpec`, manager.py:1499-1522: shell-metacharacter rejection, then PEP 508), takes the cross-process `fcntl` pool lock, and runs a one-shot install container writing pip `--target` **directly into the live pool**. On success the container is removed and `_refreshPackageList` (manager.py:1524-1634) rewrites `meta/runtimes/python/packages.json` via `pip list --format=json --path`; on failure the container is **kept** for `docker logs` post-mortem and reaped by GC.
- **Pool.** Package state is GLOBAL per-runtime: host dir `<sandbox.storage.root-dir>/runtimes/python/libs`, mounted read-only at `/sandbox/libs` (PYTHONPATH) in run containers. `packages.json` is derived metadata, not truth.
- **Phase 1 of revision 1 exists in the working tree**: `pool_update_packages.py` (the in-container upgrade+dedup helper), `Runtime.updateCommand`/`updateHelperHostPath`, `PackageUpdate`/`LibraryUpdateResult`, `updateRuntimeLibraries`, and their tests. No handler wiring yet. §5.6 states exactly what survives.
- **Only `scripts/sandbox_bootstrap.py`** passes `upgrade=True` (sandbox_bootstrap.py:177); the bot never does.

### 1.1 Superseded history

Two pip-writes-into-the-live-pool mechanisms were ratified and superseded before any production use:

1. **Pre-remove** (original D1, rejected in design review): delete old dist-infos, then bare `pip install`. Defects: holes on failure; full re-download of an already-current pool (`--no-cache-dir`); dependency-induced duplicates.
2. **Post-remove** (revision 1, D1-revised; partially implemented as Phase 1): in-container `pip install --target <pool> --upgrade`, then a RECORD **set-subtraction** dedup pass. Correct on paper — but the spike below shows pip's `--target` behavior invalidates its premises: `--upgrade` wholesale-replaces top-level dirs of *other* packages (holes appear **before** any dedup can run), and "already satisfied" never happens under `--target` (§1.2), so the wasteful re-download defect of pre-remove was never actually fixed.

Revision 2's rule: **pip never writes into the live pool.** All pip work happens in a container against a staging directory; every filesystem mutation of the pool happens host-side in `SandboxManager`, where the pool is a plain directory and `rename()` is atomic. The subtraction-based dedup disappears entirely — the staged tree is separate, so old files can be deleted by plain full-RECORD deletion and re-created by copy (no same-path-overwrite hazard).

### 1.2 Spike evidence (empirical; pip 26.2.1, real downloads, temp-dir pools)

1. `pip install --target <pool> --upgrade protobuf==5.29.0` on a pool containing `googleapis-common-protos==1.63.0`: **197 files deleted / 20 added; `google/api/` gone entirely; 196 of the deleted files belonged to googleapis-common-protos** (listed in its RECORD); its dist-info orphaned; stale protobuf-4.25.9 dist-info remained next to 5.29.0. No `Attempting uninstall` — pip's unit of installation under `--target` is the **top-level directory**, wholesale-replaced.
2. No satisfaction check exists under `--target`: "Requirement already satisfied" NEVER appears (no flag / `--upgrade` / exact pin / package present in the running venv — always re-resolves and re-downloads).
3. `--target` WITHOUT `--upgrade` on an existing top-level dir warns "Target directory … already exists. Specify --upgrade to force replacement", **skips code replacement but still writes the new dist-info** → lying metadata + duplicate dist-info + stale code. ⇒ **pre-existing production bug: today's `/sandbox install <already-present-package>` corrupts the pool** (fix ratified into this arc, §5.5).
4. `PYTHONPATH` is ignored for `--target` resolution (staging + PYTHONPATH cannot restore satisfied-skips).
5. `pip install --dry-run --report <file> --target <scratch>` is non-mutating (dry-run targets stay empty) and its `install[]` array carries resolved versions + wheel URLs — usable as a DIY outdated-oracle.

## 2. Goals / Non-goals

### Goals

1. `/sandbox update [packages...]` — update all or selected packages in the Python sandbox pool, owner-only.
2. **No holes, ever, by construction**: any failure (pip error, container timeout/OOM, disk full, crash) before the atomic swap leaves the live pool 100% untouched.
3. Already-current packages are skipped with zero download (the D2-efficiency property, delivered by our pre-filter since pip never will — fact 2).
4. Old→new diff report in the reply, derived from before/after pool enumerations.
5. Fix the pre-existing `/sandbox install` corruption bug (fact 3) by routing install through the same staged core.
6. Reuse the install-container machinery: same image, limits, lock, failure semantics.

### Non-goals

- **LLM tool for update.** Destructive, owner-only — excluded by design (see `docs/llm/sandbox.md` §"Package installation is admin-only").
- User-facing `pip list --outdated` preview round-trip (ratified D2: no-arg updates immediately; the pre-filter below is an internal efficiency device, not a preview).
- Image rebuild changes; per-chat pools; scheduled/auto updates; pinning or rollback.

## 3. Command surface

```text
/sandbox update                 → update ALL packages in the pool, report diff
/sandbox update [packages...]   → update named packages (same spec grammar as install)
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
  usage text gains the `update [packages...] - Update Python packages (admin only)` line;
  the module docstring (sandbox.py:7-13) gains the update line.

## 4. Design overview

### 4.1 Mechanism — staged install + atomic swap

```text
        (1) pre-filter container          (2) lock
  dry-run --report → outdated subset   poolLock held for 3-7
 ┌────────────────────────────────────────────────────────────────────┐
 │ (3) copy pool→newpool   (4) stage container      host / container  │
 │     host fs I/O             pip --target delta                    │
 │ (5) merge delta→newpool   (6) swap pool⇄newpool   host             │
 │ (7) refresh packages.json + diff, release lock                     │
 └────────────────────────────────────────────────────────────────────┘
```

1. **Outdated pre-filter** (before the pool lock; read-only): one container runs `pip install --dry-run --report` (§4.2) for the full spec set — user specs, or the update-all name set (§6). The manager parses the report host-side and compares resolved versions against current pool versions → **outdated subset** + **already-current set** (skipped, zero download, reported in the reply).
2. **Lock**: `locks.poolLock` held for the whole mutation phase (same one-lock-hold D6 semantics). Concurrent installs/updates get `LibraryPoolLocked` → "try later".
3. **Copy**: host-side `shutil.copytree(pool, <root>/tmp/<runId>/newpool, symlinks=True)` — a private copy on the **same filesystem** as the pool (rename(2) constraint; see §4.6). Requires ~2× pool disk headroom briefly.
4. **Stage**: one container run: `pip install --target <staging>/delta <outdated specs>` via the helper (§4.2). The staging dir is mounted rw; **the live pool is not mounted into this container at all**.
5. **Merge** (host-side, on the private copy): for each staged dist-info — delete the copy's old dist-info files **per the old RECORD, in full** (no set-subtraction: the new version lives in a separate tree, so the same-path-overwrite hazard disappears), then remove the old dist-info dir; finally copy the staged package files + dist-infos over the copy (`copytree(..., dirs_exist_ok=True)`). Deletion never removes directories not owned by the old RECORD — namespace dirs shared with other packages are safe. All old dist-infos of a staged name are removed, so legacy duplicate installs are healed for free.
6. **Swap**: two renames — `pool → <tmp>/<runId>/oldpool`, then `newpool → pool`; inline rollback restores `oldpool` if the second rename fails; `oldpool` is discarded afterwards (crash window: §4.5).
7. **Post-swap**: `_refreshPackageList` (best-effort, `metadataRefreshed`), diff computed from before/after host-side pool enumerations, lock released, run dir cleaned up.

Any failure in steps 3-5 leaves the live pool untouched — no holes, by construction. Interrupted runs leave only staging garbage, reaped by GC (§4.6).

### 4.2 Helper CLI and container shapes

The in-container helper shrinks to a thin pip runner (renamed `pool_pip_runner.py`, replacing `pool_update_packages.py` — the old name promised orchestration the helper no longer does). Two mutually exclusive modes; exit code is pip's; no other logic:

```text
python /sandbox/pool_pip_runner.py --report /sandbox/staging/report.json -- <spec...>
python /sandbox/pool_pip_runner.py --install-into /sandbox/staging/delta -- <spec...>
```

- **Report mode** execs `pip install --dry-run --report <file> --target /tmp/pip-dryrun-scratch --no-cache-dir --no-input -- <specs>` (fact 5: non-mutating; the scratch dir is in-container temp and stays empty).
- **Install mode** execs `pip install --target <dir> --no-cache-dir --no-input -- <specs>` into the staging delta.
- The `--` separator blocks pip option injection; pool-derived names are additionally grammar-validated host-side (§6).
- The manager parses the report JSON host-side (`install[].metadata` name/version). Parse failure (missing file, bad JSON) is **fail-safe**: treat every spec as outdated (full stage), log a warning.

Both update containers (pre-filter and stage) mount the run dir `<root>/tmp/<runId>` rw at `/sandbox/staging` and the helper script read-only at `/sandbox/pool_pip_runner.py`. **Neither mounts the pool.** Labels: `sandbox.managed=true`, `sandbox.purpose="update"`, `sandbox.runtime="python"`. Limits/network/user/capDrop identical to the install container. The manager pre-checks the helper file exists on the host (a missing file-bind silently becomes a directory in Docker) and raises `ConfigError` otherwise.

### 4.3 Helper delivery: mounted script, not baked into the image (D5)

Unchanged from revision 1: the helper lives in the repo at `lib/sandbox/runtimes/python/pool_pip_runner.py` next to [`Dockerfile.install`](../../lib/sandbox/runtimes/python/Dockerfile.install); host path derived as `Path(installDockerfile).parent / "pool_pip_runner.py"` — zero new config keys. Rationale: `prepareRuntime` builds images only when missing, so a baked helper silently diverges until someone runs `rebuildImage`; a mounted script is always the version the bot runs, and is a normal versioned, linted, **importable** module (visible to pyright/flake8/black and the `import main` cycle check).

### 4.4 Pool-lock placement (pinned invariant)

The flock file must live OUTSIDE the swapped directory: a waiter holding the OLD inode's lock while the next process locks a NEW `pool.lock` breaks mutual exclusion. **The current code already satisfies this** — [`acquirePoolLock`](../../lib/sandbox/locks.py) derives `lockPath = poolDir / "pool.lock"` (locks.py:294) where `poolDir = <root>/runtimes/python` (manager.py:949, 1098), i.e. the lock is a **sibling** of the swapped `libs/` directory, and the swap renames only `libs`. Revision 2 therefore PINS this as a load-bearing invariant instead of relocating anything:

- a regression test asserts the lock path resolves outside the pool (`libs`) directory;
- `recover()` (§4.5) and any future refactor must never swap the whole `runtimes/python` directory;
- the lock stays `fcntl` host-side (pip work is in containers, but the lock guards host-side mutations).

### 4.5 Crash window between the two renames

The swap is two renames; a hard crash between them leaves NO pool at the `libs` path. Ordering guarantee: renames start only after the merge completed, so a surviving `newpool` is a complete pool. Recovery spec (implemented in `recover()`, manager.py:1364, as a new step before the pool refresh; runs for each runtime):

1. `libs` missing AND a `<root>/tmp/*/newpool` exists → adopt it: rename `newpool → libs`, delete the sibling `oldpool` and run dir (completes the interrupted update).
2. `libs` missing AND only `<root>/tmp/*/oldpool` exists → rename `oldpool → libs` (restores the pre-update pool).
3. Neither → nothing (fresh pool; existing refresh logic handles it).

GC's age threshold (§4.6) is the backstop when adoption never runs (e.g. long downtime). The lock file, living outside the swapped dir, is unaffected by any of this.

### 4.6 Staging GC, disk budget, timeout budget, configuration

- **GC**: new pass reaping `<root>/tmp/*` entries (staging run dirs, crash leftovers, and any stale list-command/stdout litter) older than the existing `orphan-workspace-retention-minutes` (60 min default) — conservative enough that in-flight runs (minutes at most) and milliseconds-lived `.tmp-*` metadata temp files can never be caught. Wired into [`collectAll`](../../lib/sandbox/gc.py) (gc.py:209-241).
- **Disk**: staging lives under `<storage.root-dir>/tmp/<runId>/` — **derived, not configured**; same filesystem as the pool by construction (both under `rootDir`), unless an operator symlinks the layout across mounts. A cheap pre-swap guard (`os.stat(...).st_dev` equality of staging vs pool) raises `ConfigError` with a clear message if violated — reject early rather than fail mid-swap with `EXDEV`. Peak usage ~2× pool (live + copy), plus the delta.
- **Timeout**: two sequential container runs (pre-filter, stage), each bounded by its own `install-container.timeout-seconds` (600 s default) — acceptable: the dry-run only resolves (no wheel downloads, fast); the stage run does the same resolution+download work the single install container already performs; host copy/merge is local fs I/O outside container budgets. `timeoutSeconds` still mirrors install's override parameter, applied to both runs.
- **Config: zero new keys.** No changes to [`configs/00-defaults/sandbox.toml`](../../configs/00-defaults/sandbox.toml); existing `[sandbox.runtimes.python.install-container]` values apply to both update containers.

## 5. Manager / Runtime API changes

### 5.1 `SandboxManager.updateRuntimeLibraries` — dedicated method (D6)

Decision and reasons unchanged from revision 1 (one container phase under one lock hold; install's contract stays "add packages"; update needs its own inputs/label/result). Signature unchanged:

```python
async def updateRuntimeLibraries(
    self,
    packages: Sequence[str] | None,
    *,
    runtime: RuntimeName,
    timeoutSeconds: int | None = None,
) -> LibraryUpdateResult:
    """Update packages in the runtime library pool via staged install + atomic swap.

    Pre-filters outdated specs with a read-only dry-run container, then —
    under the pool lock — copies the pool, stages pip's output in a private
    delta, merges it into the copy, and swaps atomically. A failure at any
    point leaves the live pool untouched. On success the containers are
    removed and the package list refreshed; on failure the stage container
    is kept for ``docker logs`` post-mortem.

    Args:
        self: The SandboxManager instance.
        packages: Specs to update (PEP 508, same grammar as install), or
            None to update every package known to the pool (§6).
        runtime: The runtime whose pool to update.
        timeoutSeconds: Timeout override applied to both container runs;
            None falls back to ``install-container.timeout-seconds``.

    Returns:
        LibraryUpdateResult with the old→new diff, already-current specs,
        and failure details.

    Raises:
        InvalidPackageSpec: If every named spec fails validation.
        LibraryPoolLocked: If another process holds the pool lock.
        UnknownRuntime: If the runtime is not available.
        ConfigError: If the helper script is missing on the host, or the
            staging area is on a different filesystem than the pool.
    """
```

Flow: validate named specs via `_validatePackageSpec` (partial failures proceed, recorded in `failedSpecs`); update-all → build the name set per §6 (empty → early "Nothing installed" return, no container); snapshot pool versions host-side (dist-info enumeration — now also the diff baseline; `packages.json` is kept fresh best-effort but is no longer the diff source); run the pre-filter container → outdated subset + `upToDate` set — **empty outdated subset → return success immediately, zero mutation, no lock taken**; otherwise `async with locks.poolLock(...)` → re-enumerate the baseline (the pre-lock snapshot may be stale — accepted: staging a since-updated package is an idempotent same-version reinstall, and a since-outdated skip merely waits for the next update) → copy → stage container → on failure keep container, clean the run dir, return `success=False` (pool untouched) → merge → swap → post-swap enumeration + `_refreshPackageList` (best-effort) → diff → release lock. The staged core (copy/stage/merge/swap) lives in a private manager helper shared with install (§5.5).

### 5.2 Result types (`lib/sandbox/types.py`)

`PackageUpdate` (types.py:378-392) survives unchanged. `LibraryUpdateResult` (types.py:395-418) gains one field:

```python
@dataclass(slots=True)
class LibraryUpdateResult:
    """Outcome of a SandboxManager.updateRuntimeLibraries call."""

    runtime: RuntimeName
    success: bool                      # staged install completed and was swapped in
    updated: list[PackageUpdate]       # newVersion != oldVersion
    unchanged: list[PackageUpdate]     # identical versions before and after
    upToDate: list[str]                # NEW: names the pre-filter skipped as already current
    failedSpecs: list[tuple[str, str]]  # (spec, reason) rejected at validation
    containerId: str | None            # kept container id on failure (docker logs hint)
    metadataRefreshed: bool | None     # None = refresh not attempted (no-op); False = attempted and failed:
                                       #   diff remains accurate; only packages.json metadata may be stale
```

### 5.3 `Runtime` ABC + `PythonRuntime`

`updateHelperHostPath` survives (path target renamed to `pool_pip_runner.py`); the `UPDATE_HELPER_CONTAINER_PATH` constant becomes `/sandbox/pool_pip_runner.py`. `updateCommand(packages)` is replaced by two argv builders (single argv, no shell, mirroring the two container runs of §4.2):

```python
@abstractmethod
def reportCommand(self, specs: Sequence[str]) -> list[str]:
    """Build the dry-run pre-filter container command (report mode).

    Args:
        specs: Package specs to resolve (already validated host-side).

    Returns:
        Command and arguments as a single argv list (no shell).
    """
    ...


@abstractmethod
def stageInstallCommand(self, specs: Sequence[str]) -> list[str]:
    """Build the staged-install container command (install mode).

    Args:
        specs: Package specs to install into the staging delta.

    Returns:
        Command and arguments as a single argv list (no shell).
    """
    ...
```

`installCommand` (base.py:93-109, runtime.py:93-121) is **deleted** — after install unification (§5.5) nothing invokes it, and its live-pool `--target` is exactly what this revision removes.

### 5.4 Host-side staging module

New module `lib/sandbox/runtimes/python/pool_staging.py` (host-importable, stdlib-only, directly unit-testable without containers) absorbs everything pool-structural from the old helper:

- **Moved as-is** (the tested parser): `canonicalizeName`, `extractSpecName`, `isValidCanonicalName` + its grammar regex, `enumerateDistInfos` + the METADATA `Name:`-first `_parseDistInfoDir` (dir-stem fallback; no fragile hyphen-splitting), `readRecordPaths` (with `posixpath.normpath` normalization), and the `_resolveJailed` jail idiom (`resolve()` + `relative_to`, the [`resolveWorkspacePath`](../../lib/sandbox/storage.py) pattern, storage.py:53-109).
- **Carried over, simplified**: the RECORD-deletion routine — symlink handling (unlink the link, never the target), jail checks, refusal of directory RECORD entries — now deleting the **full** old RECORD (no set-subtraction argument to get wrong).
- **New**: `mergeStagedDelta(poolCopy, deltaDir)` (deletions then `copytree` overlay, per §4.1 step 5), `swapPools(pool, newPool, oldPoolParking)` (same-FS guard, rename pair, inline rollback), and the report-parsing helper (`install[].metadata` name/version extraction with the fail-safe default).

### 5.5 Install-path unification (bug fix)

`installRuntimeLibraries` routes through the SAME staged copy/stage/merge/swap core. Spec validation unchanged; **no pre-filter** — installing is intentional. Consequences:

- **"Install already-present package" becomes a clean re-install**: the merge deletes the old dist-info per its RECORD and copies the staged one — fixing the ratified corruption bug (fact 3: today's path skips code replacement but writes lying metadata next to stale code).
- The install container's spec changes accordingly: staging mount instead of pool mount; command is `stageInstallCommand`; label `sandbox.purpose="install"` stays. Installs no longer write the live pool directly.
- The `upgrade: bool = False` parameter stays in the signature (`scripts/sandbox_bootstrap.py` passes it) but becomes a documented no-op: pip `--target` has no satisfaction check (fact 2), so a staged install always resolves and installs fresh — `--upgrade` has nothing to upgrade in an empty delta. Return type stays `bool`; handler contract unchanged.
- First install into an empty pool works naturally (copy of an empty dir → merge adds the delta → swap).

### 5.6 What survives from the Phase 1 tree — and what is deleted

**Survives** (argv/content adjustments only): `PackageUpdate` + `LibraryUpdateResult` and their exports (+ the new `upToDate` field); the `Runtime` ABC hooks (now `reportCommand`/`stageInstallCommand`/`updateHelperHostPath`); the `updateRuntimeLibraries` signature and lock/diff/refresh skeleton; `_refreshPackageList` outcome checks; the manager/runtime/helper/bot test scaffolding (fixtures rewritten, files renamed where the module renames).

**Deleted as obsolete** (do not preserve): the live-target upgrade invocation (`buildPipCommand` + `PIP_INSTALL_ARGS` and its flag-parity test); the entire snapshot→upgrade→dedup contract and `dedupPool` set-subtraction logic; the helper's `--all` mode (enumeration moves host-side, §6); `installCommand`; `pool_update_packages.py` itself (renamed; only the parser pieces move out per §5.4).

## 6. Update-all name source (D7, re-cut): host-side enumeration ∪ packages.json

The pre-filter needs pool versions host-side anyway, so update-ALL is now driven **host-side**: the union of (a) dist-info enumeration of the pool (ground truth — what runs actually import) and (b) canonical names from `packages.json`. Enumeration reuses the METADATA-based parser from `pool_staging.py` (§5.4) — name from the METADATA `Name:` header with dir-stem fallback, so the fragile hyphen-splitting concern stays avoided. Every name is grammar-validated (`isValidCanonicalName`) before entering any argv — hostile/flag-like pool-planted names are skipped with a warning, never handed to pip. The union self-heals drift in both directions: pool-only packages get updated; `packages.json`-only phantoms have no pool version, fail the already-current comparison, and are reinstalled (healing the metadata lie).

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
Already up to date, skipped (3): scipy, sympy, pillow
Note: sandbox runs started before this update keep seeing their previous pool; new runs see the updated one.
```

- `oldVersion is None` renders as `name → <new> (no prior version recorded)` (new install or stale metadata).
- All current: `All sandbox packages are up to date (python, N packages).` — now reached via the pre-filter with zero download and zero mutation.
- Empty pool (no-arg only): `Nothing installed in the python sandbox pool. Use /sandbox install <packages...> first.`
- Partial validation failures append: `Skipped invalid specs: <spec> (<reason>), ...`
- Container failure: `Update failed (pip error); the pool is untouched — nothing was partially applied. Keeping container <id> for inspection (docker logs <id>).`
- Lock busy: `Another sandbox install/update is in progress, try again later.`

## 9. Edge cases & failure semantics

| Case | Behavior |
|---|---|
| Empty outdated set (pre-filter) | No lock, no mutation container; success reply with the up-to-date/skipped line; zero download |
| Disk full during copy or merge | OSError aborts before the swap; live pool untouched; staging cleaned; failure reply |
| Staging on a different filesystem than the pool | Pre-swap `st_dev` guard raises `ConfigError` (points at the root-dir layout); pool untouched |
| Crash between the two renames | No pool at path; `recover()` adopts `newpool` (merge was complete — renames start only after) or restores `oldpool` (§4.5); GC backstop |
| Crash/failure before the swap | Live pool 100% untouched; only `<root>/tmp/<runId>` garbage remains → GC reaps (§4.6) |
| Dry-run report parse failure | Fail-safe: every spec treated as outdated (full stage), logged |
| Named package not installed | Fresh staged install; reported as updated with `oldVersion=None` |
| `packages.json`-only phantom name | No pool version → outdated → reinstalled (self-heal, §6) |
| Same file path in old and new versions | Trivially safe: old copy deleted per full RECORD, then re-created from the separate staged tree (test-pinned) |
| Pre-existing duplicate dist-infos for a staged name | All old dist-infos removed per their RECORDs; single staged one copied in — legacy duplicates healed |
| Old RECORD missing/unreadable during merge | Skip that package's deletion entirely (warn); staged copy still lands beside it — never delete what we cannot account for |
| RECORD entry escaping the pool (`../..`, absolute, symlink out) | Entry skipped, logged; jail check never deletes outside the pool root; symlinks are unlinked, never their targets |
| `_refreshPackageList` fails after swap | Result `metadataRefreshed=False`; diff still correct (computed from enumerations); logged |
| All named specs invalid | `InvalidPackageSpec` raised before any container starts |
| Container OOM/timeout | Same `success=False` path; pool untouched; container kept; GC reaps per `sandbox.gc.orphan-container-retention-minutes` |
| Concurrent install/update | `LibraryPoolLocked` → lock-busy reply (D6, unchanged) |
| Helper missing on host | Pre-checked; `ConfigError` with the derived path in the message |

## 10. Concurrency & in-flight runs (D3, upgraded)

- The whole mutation phase (copy → stage → merge → swap) holds `locks.poolLock` once; the pre-filter runs before it, read-only. `LibraryPoolLocked` propagates to the lock-busy reply.
- **In-flight runs — hazard largely eliminated:** run containers bind-mount the pool read-only; Linux bind mounts pin the inode, so containers that mounted the pool keep seeing the OLD directory contents after the swap. In-flight runs get a consistent old view; runs started after the swap get the new pool. Residual risk is only the theoretical race of mount-at-container-create vs rename — one cautionary sentence in the reply (§8). No waiting machinery.

## 11. Security review

- **Inputs:** specs are validated host-side (`_validatePackageSpec`: metacharacters, `-` prefix, PEP 508) before reaching containers; pool-derived update-all names are grammar-validated host-side (§6); the `--` separator blocks pip option parsing in the helper.
- **No shell anywhere:** container commands are single argv lists; the helper execs pip via `subprocess.run` argv — no `sh -c`, no interpolation.
- **Jail:** every merge deletion target is `(distInfoDir / recordEntry).resolve()`-d and checked `relative_to(poolRoot.resolve())` — traversal, absolute-entry, and symlink escapes are caught by resolution (`resolveWorkspacePath` idiom). Files are deleted individually (`unlink`); dist-info dirs via `shutil.rmtree` only after their own jail check. Symlinked RECORD entries: the link is unlinked, never its target.
- **The live pool is never mounted into a networked container** — pip (the attack surface touching PyPI) only ever sees a scratch delta.
- **Container hardening** identical to install: non-root user, `capDrop ALL`, `no-new-privileges`, network bridge (pip needs it), helper mounted read-only.

## 12. Testing plan

All new tests under [`tests/`](../../tests/) only (no collocated). Regression framing: tests encoding ratified behaviors must fail without the change. Pip never runs: `subprocess.run` is monkeypatched in helper tests; the backend is mocked in manager tests.

- **`tests/lib/sandbox/runtimes/test_pool_pip_runner.py` (new; replaces `test_pool_update_packages.py`):** argv shape for both modes (dry-run + report + scratch `--target`; install-into `--target`; `--` before specs; no shell); pip exit-code passthrough; report mode mutates nothing; mode flags mutually exclusive / one required.
- **`tests/lib/sandbox/runtimes/test_pool_staging.py` (new):** enumeration name extraction (METADATA `Name:` preferred, stem fallback, hyphenated names); RECORD parsing incl. normpath equivalence; **merge correctness** (old-only files deleted; shared paths deleted-then-recreated from the delta as the new version; other packages untouched; namespace dirs shared across packages survive; multiple old dist-infos all removed); jail rejection (traversal, absolute, symlink-out); symlink entry unlinks the link not the target; unreadable old RECORD → skip; **swap** (same-FS guard fires on mocked `st_dev` mismatch; rollback restores the pool when the second rename fails); report parsing incl. fail-safe on bad JSON.
- **`tests/lib/sandbox/test_locks.py` (extend):** pin the §4.4 invariant — the lock path is a sibling of `libs`, never inside it.
- **`tests/lib/sandbox/test_manager.py` (rewrite update tests; extend install tests):** two ContainerSpecs (report: staging mount, no pool mount; stage: staging mount, no pool mount); pre-filter fail-safe; empty-outdated early success with zero backend calls; diff from enumerations; `LibraryPoolLocked` propagation; stage failure keeps container AND leaves the pool files byte-identical on disk; **install regression: reinstalling an already-present package replaces the old dist-info (fails on the pre-fix code — the ratified bug)**; `upgrade=` accepted and ignored; `recover()` crash-window adoption (§4.5 cases 1-3).
- **`tests/lib/sandbox/runtimes/test_python_runtime.py` (rewrite):** `reportCommand`/`stageInstallCommand` argv; `updateHelperHostPath` → `pool_pip_runner.py`; the `PIP_INSTALL_ARGS` parity test is deleted with its constant.
- **`tests/lib/sandbox/test_gc.py` (extend):** stale `tmp/*` entries reaped by age; fresh ones survive.
- **`tests/bot/test_sandbox.py` (extend):** sandbox disabled / `allow-sandbox` false → denied; non-owner → denied; no-args → manager called with `None`; named → specs passed; reply rendering (updated / unchanged / no-prior / **already-up-to-date skipped line** / softened in-flight note); failure reply contains container id and "pool untouched"; lock-busy reply; empty-pool reply; regression: usage + help list all six subcommands (help is missing `packages` today).

## 13. Documentation-sync plan

| Doc | Change |
|---|---|
| [`docs/llm/sandbox.md`](../llm/sandbox.md) | §Bot Integration: add `/sandbox update`; describe staged install + atomic swap (pip never writes the live pool; install included), the lock-placement invariant, the softened in-flight note, staging GC |
| [`docs/llm/handlers.md`](../llm/handlers.md) | `SandboxHandler` row: add `update` to the `/sandbox` subcommand list (and fix the missing `packages`) |
| [`CHANGELOG.md`](../../CHANGELOG.md) | `## [Unreleased]` → **Added**: `/sandbox update [packages...]` with old→new diff and up-to-date skip; **Fixed**: `/sandbox install <already-present-package>` corrupted the pool (pip `--target` without `--upgrade` skips code replacement but writes new dist-info → lying metadata + duplicates + stale code); installs now go through the staged path |
| [`TODO.md`](../../TODO.md) | Line 3 checkbox → `[x]` |

No changes: `docs/llm/configuration.md` (no new config keys), `docs/llm/architecture.md` / `docs/llm/index.md` (no new subsystem), `docs/llm/libraries.md` (manager behavior documented in `sandbox.md`), database docs (no schema).

## 14. Implementation phases

### Phase 1R — host-side staged core + helper rewrite + lock pin (software-developer)

Files: `lib/sandbox/runtimes/python/pool_pip_runner.py` (new); `lib/sandbox/runtimes/python/pool_staging.py` (new); `lib/sandbox/runtimes/python/pool_update_packages.py` (delete); `lib/sandbox/runtimes/base.py`; `lib/sandbox/runtimes/python/runtime.py`; `lib/sandbox/types.py`; `lib/sandbox/manager.py` (updateRuntimeLibraries rewrite, shared staged core, recover() adoption); `lib/sandbox/gc.py` (tmp/* reap); tests: `tests/lib/sandbox/runtimes/test_pool_pip_runner.py` (new), `tests/lib/sandbox/runtimes/test_pool_staging.py` (new), `tests/lib/sandbox/runtimes/test_pool_update_packages.py` (delete), `tests/lib/sandbox/test_manager.py`, `tests/lib/sandbox/test_locks.py`, `tests/lib/sandbox/test_gc.py`, `tests/lib/sandbox/runtimes/test_python_runtime.py`.

Acceptance: `make format lint` clean; `make test` green; merge/jail/swap/rollback tests red when the checks are removed (mutation check); no handler touched; `installRuntimeLibraries` still live-pool (unified only in 1I).

### Phase 1I — install-path unification

Files: `lib/sandbox/manager.py` (`installRuntimeLibraries` → staged core; `upgrade` no-op docstring); `tests/lib/sandbox/test_manager.py` (install container spec: staging mount, no pool mount; already-present reinstall regression).

Acceptance: lint/test green; `tests/scripts/test_sandbox_bootstrap.py` and `tests/bot/test_sandbox.py` install mocks pass unchanged (same signatures); the reinstall-corruption regression test fails on the pre-fix code path.

### Phase 2 — handler wiring

Files: `internal/bot/common/handlers/sandbox.py` (`_handleUpdateCommand`, dispatcher branch, usage text, `helpMessage`, module docstring, `LibraryPoolLocked` import); `tests/bot/test_sandbox.py`.

Acceptance: lint/test green; usage + help list all six subcommands; owner/access gating, reply variants (incl. up-to-date/skipped and softened in-flight note) covered by tests.

### Phase 3 — docs sync + bookkeeping (load `update-project-docs` skill)

Files: the four docs in §13.

Acceptance: `make check-docs` passes; `CHANGELOG.md` has both the Added and the Fixed entries; `TODO.md` line 3 checked.

---

## 15. Risks & open items

- **Merge/swap correctness is now host-side and fully unit-testable** — the principal risk class of revision 1 (subtle in-container pip interactions) is gone; what remains is ordinary filesystem logic, test-pinned (§12).
- **Crash-window adoption** depends on the "renames start only after merge completes" ordering — enforced by the shared core's structure and pinned by the recover() tests.
- **2× pool disk headroom** during the copy — documented (§4.6); pools are ~hundreds of MB; accepted.
- **Pre-filter staleness** (pool changes between pre-filter and lock) — accepted idempotency (§5.1); worst case a same-version reinstall or a deferred update.
- **Repo checkout required on the host** for the helper mount — already implied by repo-relative `install-dockerfile`; flagged in `sandbox.md` notes.
- **pip report format drift** (unversioned JSON shape) — mitigated by the fail-safe (treat all as outdated; behavior degrades to full stage, never to a wrong skip).
- No open design questions remain; implementation may surface naming/test details, to be resolved in review.
