# Sandbox Update Simplification v1

Status: **approved 2026-09-05, implemented 2026-09-05.** Companion to
[`docs/plans/sandbox-update-v1.md`](sandbox-update-v1.md) (the feature design
record — read §4.2/§5 for the mechanism being preserved). Out of scope by
design: the staged-swap core, the recovery/reconcile cluster, the
pip-never-touches-live-pool invariant. Nothing here changes ratified mechanism
behavior.

Date: 2026-09-05

> Line references are as of commit `3e81c113`; they will drift as items land.
> Execution plan only — four independent work items, one commit each. Tick the
> checkbox in this file as each commit lands.

---

## 1. Motivation

Post-landing audit of `3e81c113`: container-side layout knowledge split three
ways (constant values on `PythonRuntime`, unenforceable annotation-only
declarations on the Runtime ABC at `lib/sandbox/runtimes/base.py:32-48`, mount
assembly in the manager at `lib/sandbox/manager.py:1923-1954` while the
runtime's own argv builders join the same constants at
`runtime.py:119-143`). Plus: a duplicated helper pre-check, a script-compat
no-op parameter whose script is being deleted, and a double pool walk.

## 2. Ratified decisions

- **D1 (variant B):** runtime-owned `StagingRun` — command + mounts move onto
  the runtime as one cohesive unit. Rejected alternatives: minimal
  `stagingMounts()` method (less cohesive, kept as fallback consideration),
  "dict of named container paths" (stringly-typed, assembly stays in manager).
- **D2:** `scripts/sandbox_bootstrap.py` deleted entirely (owner never used
  it), together with the `upgrade=` no-op parameter it motivated.
- **D3:** four independent commits, each self-verifying (`make format lint` +
  `make test`), each ticking its checkbox here.

## 3. Work item 1 — Runtime-owned StagingRun plans

- [x] Implement

**What:**

- Add to `lib/sandbox/runtimes/base.py`: frozen slots dataclass `StagingRun`
  with fields `command: list[str]` and `mounts: list[dict[str, str]]`
  (docstrings on class + both fields).
- Delete the annotation-only `UPDATE_HELPER_CONTAINER_PATH` (base.py:32-37)
  and `STAGING_CONTAINER_PATH` (base.py:39-48) from the ABC.
- Replace abstract `reportCommand(specs)` (base.py:104) and
  `stageInstallCommand(specs)` (base.py:116) with abstract
  `reportRun(self, hostStagingIoDir: Path, specs: Sequence[str]) -> StagingRun`
  and
  `stageRun(self, hostStagingIoDir: Path, specs: Sequence[str]) -> StagingRun`.
- `updateHelperHostPath()` abstract (base.py:128) STAYS — the manager's
  helper-exists pre-check uses it.
- `PythonRuntime` (`lib/sandbox/runtimes/python/runtime.py`): implement both
  methods; `STAGING_CONTAINER_PATH` (":44") and `UPDATE_HELPER_CONTAINER_PATH`
  (":41") REMAIN as public class attributes used only by the class's own
  methods (tests reference them symbolically); mounts built internally via
  `self.updateHelperHostPath()`.
- Manager (`lib/sandbox/manager.py`): delete `_stagingMounts` (:1923-1954);
  call sites `_runPrefilterContainer` (:1999-2000) and `_runStagedInstall`
  (:2119-2120) build the spec from `runtimeImpl.reportRun(ioDir, specs)` /
  `.stageRun(ioDir, specs)` using `.command` and `.mounts`.

**Tests:**

- `tests/lib/sandbox/runtimes/test_python_runtime.py` argv-shape tests
  (:131-173) reshape to assert `.command`/`.mounts`; constant literal pins
  (:119-128) unchanged.
- `tests/lib/sandbox/test_manager.py` expected UNTOUCHED
  (symbolic-constant insulation — if it breaks, a mount-dict key drifted,
  which is exactly what those tests exist to catch).
  Amended during implementation: five test_manager.py tests called the old
  argv builders directly (self-referential expected values) and were
  mechanically updated to `.command` of the new plan methods; mount
  assertions were untouched and passed unchanged.

**Acceptance:** `make format lint` + `make test` green; no production code
outside `lib/sandbox` references the removed ABC members;
`docs/plans/sandbox-update-v1.md` untouched (frozen design record).

## 4. Work item 2 — Helper pre-check consolidation + StagingPurpose

- [x] Implement

**What:**

- The `updateHelperHostPath().is_file()` → `ConfigError` pre-check exists
  twice: manager.py:1234-1238 (`updateRuntimeLibraries`) and
  manager.py:2087-2091 (`_runStagedInstall`). `_runPrefilterContainer`
  (:1956) has none — the outer copy is its only guard.
- MOVE the check into `_runPrefilterContainer` (before its runOneshot);
  delete the outer block at :1231-1238. Result: every container-runner
  verifies its own file-binds uniformly. Behavior delta (accepted, more
  correct): the check now fires after the update-all empty-pool
  short-circuit but before the pre-filter container — update-all on an
  empty pool succeeds with no containers even when the helper is missing,
  while any request that reaches the pre-filter (including all-current
  pools, since "nothing-outdated" is determined by the pre-filter) still
  raises `ConfigError` when the helper is missing.
- Add `StagingPurpose(StrEnum)` to `lib/sandbox/enums.py`:
  `INSTALL = "install"`, `UPDATE = "update"` (string values MUST stay
  identical — container-name prefix `sandbox-{purpose}-{runId}` at
  manager.py:2117 and the `sandbox.purpose` label at :2130 depend on them).
  Type `_runStagedInstall`'s `purpose: str` param as `StagingPurpose`;
  update callers at :1110 and :1322.

**Tests:** `tests/lib/sandbox/test_manager.py:1793-1811` (`ConfigError` +
backend.runOneshot not awaited) must still hold.

Amended during implementation: deleting the outer pre-check left a gap in
`updateRuntimeLibraries`'s local step-number comments, so they were
renumbered (pre-filter spec set = Step 2, baseline enumeration = Step 3,
pre-filter container = Step 4). The pinned `ConfigError` test passed
unchanged (named-specs requests never hit the short-circuits before the
pre-filter runner). `StagingPurpose` is exported from `lib.sandbox.enums`
only (same treatment as `RunStatus`), not re-exported from the package root.

**Acceptance:** `make format lint` + `make test` green; exactly one pre-check
per container-runner; no free-form purpose strings at call sites.

## 5. Work item 3 — Remove sandbox_bootstrap + upgrade= parameter

- [x] Implement

**What:**

- Delete `scripts/sandbox_bootstrap.py` entirely and its test
  `tests/scripts/test_sandbox_bootstrap.py`.
- Remove the `upgrade: bool` parameter from
  `SandboxManager.installRuntimeLibraries` (manager.py:1026-1040) and the
  docstring paragraphs documenting it as a no-op kept for the script. The
  method itself STAYS (the `/sandbox install` handler calls it at
  `internal/bot/common/handlers/sandbox.py:1206`).
- Grep the whole repo for `sandbox_bootstrap` (Makefile, docs/,
  .sourcecraft/, scripts/, README) and clean every remaining reference.
- Update [`docs/llm/sandbox.md`](../llm/sandbox.md): remove bootstrap-script
  and upgrade-no-op mentions.
- Add [`CHANGELOG.md`](../../CHANGELOG.md) entry under `## [Unreleased]`
  (Removed: the sandbox_bootstrap script; Changed: `installRuntimeLibraries`
  no longer accepts `upgrade=`). Follow
  [`docs/llm/changelog.md`](../llm/changelog.md) entry style: declarative,
  past tense, start with the thing that changed.

Amended during implementation: no `Removed` block existed under
`[Unreleased]`, so one was created (Added → Changed → Removed → Fixed
order); the pre-existing in-Unreleased `Fixed` entry that named
`sandbox_bootstrap.py` alongside `/sandbox install` was reworded to drop
the dead reference (nothing had shipped yet). The now-unread
`[sandbox.bootstrap]` config section was deliberately KEPT (removal out of
scope for this item); its docs rows and the `configs/00-defaults/sandbox.toml`
comment were updated to mark it unused. developer-guide §13 was rewritten
from script-driven setup to the `prepareRuntime()` on-demand image build
(its "starter-packages baked into the install image" claim was already
stale — `Dockerfile.install` is a plain toolchain image).

**Acceptance:** `make format lint` + `make test` green; no live references
to sandbox_bootstrap outside historical records (frozen plans, archive,
teamlead memory) and the removal CHANGELOG entry; CHANGELOG entry present.

## 6. Work item 4 — Single pool walk at update Step 3

- [x] Implement

**What:**

- manager.py:1280-1281 calls `_enumeratePoolVersions(libsDir)` (:1809) and
  `_collectDuplicatePoolNames(libsDir)` (:1833) back-to-back — each performs a
  full `enumerateDistInfos` walk
  (lib/sandbox/runtimes/python/pool_staging.py:217-250); the duplicate set is
  derivable from the same inventory.
- Introduce one helper (e.g.
  `_enumeratePoolWithDuplicates(libsDir) -> tuple[dict[str, str], set[str]]`)
  used at Step 3; `_enumeratePoolVersions` remains available for its other
  callers (:1318 re-enumerate under lock, :1336 after-enumeration).
- Resolve the inconsistent OSError posture deliberately:
  `_collectDuplicatePoolNames` swallows OSError (:1851-1855) while
  `_enumeratePoolVersions` propagates. Preferred: propagate (fail loudly — an
  unreadable pool should abort the update, not silently pass the duplicates
  check). If an existing test pins graceful degradation, keep the swallow but
  document it in the helper docstring.

**Acceptance:** `make format lint` + `make test` green; Step 3 performs
exactly one dist-info walk; OSError posture documented.

Amended during implementation: the OSError posture was resolved as
PROPAGATE — the hypothesis held (the unguarded versions walk ran first at
the Step-3 site, so the duplicates walk's swallow was reachable only in a
becomes-unreadable-between-calls TOCTOU race), and NO test pinned the
swallow (`_collectDuplicatePoolNames` had zero direct test callers). The
merged `_enumeratePoolWithDuplicates` keeps the missing-dir tolerance
(returns empty results, no raise) that `testMissingHelperRaisesConfigError`
silently depends on. The §7 keep-as-is entry for `_collectDuplicatePoolNames`
is superseded by this item's mandated deletion (the other two named helpers
remain kept as registered).

## 7. Keep-as-is register (audited 2026-09-05 — do NOT "simplify" these)

- `metadataRefreshed: bool | None` tri-state in `LibraryUpdateResult`
  (types.py:429) — semantically accurate; no production consumer, 8 tests pin
  it; collapsing would make no-op paths report "refresh failed".
- Single-caller pure helpers `_splitOutdatedSpecs`, `_diffPoolVersions` —
  module-level for direct unit testability.
- `_collectUpdateAllNames` retry-under-lock (manager.py:1252-1259) — ratified
  fail-closed empty-find guard (feature plan §4.5).
- `pool_staging.py` defensive surface — every guard is a test-pinned response
  to a verified threat class (planted symlinks/FIFOs, hostile METADATA,
  phantom RECORD rows).
- Handler render/cap cluster (sandbox.py:1319-1428) — cap machinery is itself
  a prior review fix; nothing shareable with install path.
- Dead `sessionId` dispatch params on subcommand handlers — uniform
  dispatcher signature convention.

## 8. Sequencing & verification

Items 1-4 are independent; land as separate commits in numbered order. Items
1 and 2 both edit the manager.py staging cluster — never in the same commit.
Every commit: `make format lint` + `make test` green, checkbox ticked in this
file, commit message imperative (repo style, cf. "Add /sandbox update command
via staged install and atomic pool swap").

## 9. Follow-ups

- [x] Delete the dead `[sandbox.bootstrap]` config section (`starter-packages` key — unused since work item 3).
- [x] Remove the dead `image-pull-policy` setting.
- [x] Relocate the real-Docker end-to-end install test to `tests/lib/sandbox/`.
  Amendment: the relocated test (`tests/lib/sandbox/test_install_integration.py`)
  is behavior-focused and CLI-independent — it constructs `SandboxManager`
  directly against a per-run `~/.gromozeka-tests/` storage root (desktop Docker
  VMs only share `/Users`) instead of driving the deleted bootstrap script.
  Amendment 2 (Gate-1 review): image tags are per-run too
  (`gromozeka-sandbox-test-install-<run-id>:run`/`:install`) so stale images
  from aborted runs cannot make the build assertion vacuous and concurrent
  runs cannot interfere; cleanup removes only the run's own UUID workspace
  (never the shared parent) and re-verifies container/image removal against
  the daemon, failing the test on residue.
