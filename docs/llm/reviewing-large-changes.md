# Gromozeka — Reviewing Large Changes

> **Audience:** `code-reviewer` agent (read-only, structured reports), `teamlead` agent (orchestrates review campaigns)
> **Purpose:** Methodology for reviewing changes exceeding the single-pass budget of the `code-reviewer` agent
> **Extends:** Standard review flow described in AGENTS.md (Gate 1 per-subtask + Gate 2 whole-work)

---

## Table of Contents

1. [Purpose & When to Use](#1-purpose--when-to-use)
2. [Pre-Review: Characterize the Diff](#2-pre-review-characterize-the-diff)
3. [Batching by Feature Domain](#3-batching-by-feature-domain)
4. [Per-Batch Review Execution](#4-per-batch-review-execution)
5. [Integration Pass (Whole-Work Review)](#5-integration-pass-whole-work-review)
6. [Remediation Workflow (for teamlead)](#6-remediation-workflow-for-teamlead)
7. [Appendix: Example -- Current Batch (20 commits, 77 files, master..HEAD)](#7-appendix-example----current-batch-20-commits-77-files-masterhead)

---

## 1. Purpose & When to Use

### 1.1 Threshold

The standard Gromozeka review flow (AGENTS.md) defines two gates:

- **Gate 1 (per-subtask):** Review each logical subtask as it is completed, before moving to the next.
- **Gate 2 (whole-work):** Final integration review of the complete change.

This methodology extends the standard flow for cases where a single "subtask" -- or the accumulated whole-work diff -- exceeds the comfortable capacity of one `code-reviewer` invocation.

The `code-reviewer` agent (defined in `.opencode/agents/code-reviewer.md`) operates with a ~60 step budget. Empirical observation shows it handles approximately **15-20 changed files per batch** comfortably. When a changeset exceeds **~24 files**, the reviewer may:
- Return shallow or empty results because its step budget was exhausted on file-level I/O.
- Miss cross-file patterns because it could not load all affected files.
- Fail to perform multi-pass analysis (architectural fit, security, correctness, etc.) across the full scope.

Therefore, this methodology **triggers automatically** when the diff contains **more than 24 files**, or when any single feature domain within the diff exceeds 20 files.

### 1.2 Relationship to Standard Gates

| Standard gate | Equivalent in this methodology |
|---|---|
| Gate 1 (per-subtask) | Per-batch review (Section 4) -- each batch is the largest self-contained subtask the reviewer can ingest |
| Gate 2 (whole-work) | Integration pass (Section 5) -- after all per-batch reviews are clean |

The key addition is an explicit **batching phase** (Sections 2-3) that sits between the subagent finishing its work and dispatching reviews.

---

## 2. Pre-Review: Characterize the Diff

Before any review can begin, the orchestrator must understand what is in the diff. This phase is the responsibility of the `teamlead` agent or the human orchestrator.

### 2.1 Inventory Phase

1. Obtain a list of every changed file: `git diff <base>..HEAD --name-only` (or `git diff --staged --name-only` for staged changes).
2. For each file, determine the **feature domain** it belongs to. A feature domain is a logical feature or concern (e.g., "chat history search", "proxy lifecycle management", "config changes", "documentation updates").
3. Tally the files per domain.

### 2.2 Risk Triage

Flag each file with one or more risk tags. The following risk categories are recognised:

| Tag | Meaning | Examples |
|---|---|---|
| `DB-MIGRATION` | Database schema change | `internal/database/migrations/versions/NNN_*.py` |
| `NEW-HANDLER` | New bot command handler | `internal/bot/common/handlers/*.py` |
| `SINGLETON-LIFECYCLE` | Singleton service lifecycle changes | `internal/services/*/service.py` |
| `EXTERNAL-DEP` | New direct dependency or dependency version change | `requirements.direct.txt` |
| `SECURITY` | Auth, secrets, input validation, subprocess execution | `internal/bot/common/bot.py`, `lib/sandbox/` |
| `PROCESS-MGMT` | Subprocess lifecycle, fire-and-forget, timeouts | `internal/services/proxy/lifecycle.py` |
| `CONFIG-CHANGE` | TOML config structure or keys | `configs/**/*.toml` |
| `HIGH-RISK` | Compose of multiple risk factors | Any file with 2+ other risk tags |

### 2.3 Dependency Mapping

Identify which features share infrastructure. Shared files include:

- `internal/database/models.py` -- multiple features may add DB models
- `tests/conftest.py` -- fixture changes affect all test batches
- `configs/**/*.toml` -- config changes are cross-cutting
- `requirements.direct.txt` -- deps added for one feature may be needed by another
- `docs/llm/*.md` -- documentation updates

### 2.4 Output of This Phase

The output is a **classification table** with columns: feature batch slug, file list, risk tags, dependency notes. Example:

| Batch | Feature | Files | Risk Tags |
|---|---|---|---|
| chat-history-search | Chat history search handler + embeddings + migration | ~22 files | DB-MIGRATION, NEW-HANDLER, EXTERNAL-DEP |
| proxy-lifecycle | Proxy process management | ~7 files | SINGLETON-LIFECYCLE, PROCESS-MGMT |
| shared-config-docs | Config defaults + docs updates | ~37 files | CONFIG-CHANGE |

---

## 3. Batching by Feature Domain

### 3.1 Core Principle

**One batch = one self-contained feature or change domain.** Independent features belong in separate batches; they can be reviewed in parallel. Batches must be disjoint in their file lists -- no file should appear in multiple batches.

### 3.2 Batch Size Guardrails

- **Target:** 15-20 files per batch. This fits within the `code-reviewer` agent's typical ~60 step budget.
- **Upper bound:** 24 files. Above this, split the feature into sub-batches (e.g., data layer vs. handler layer within the same feature).
- **Lower bound:** No strict lower limit. A 3-file batch is fine; a single-file batch is also valid if it represents an independent concern (e.g., a standalone migration).

For features that naturally exceed 20 files, split along architectural boundaries:

- **Data layer:** migrations, repository changes, model changes.
- **Handler layer:** handler class, tool registrations, message sending logic.
- **Config layer:** TOML defaults, config manager changes.
- **Test layer:** test files for the feature (can form their own batch or be included with production files).

### 3.3 Cross-Cutting Files

Files touched by multiple features present a challenge. They should be handled by one of two strategies:

**Strategy A -- Owner assignment:** Assign the cross-cutting file to the batch that "owns" it -- the feature that caused the majority of changes to that file. The owning batch is reviewed first; the cross-cutting file is then stable for subsequent batches.

**Strategy B -- Dedicated infrastructure batch:** Collect all cross-cutting files into a single "shared infrastructure" batch that is reviewed at the end, after per-feature reviews are complete. This avoids blocking feature batches on shared-file changes.

Preferred strategy for common cross-cutting files:

| File | Strategy | Rationale |
|---|---|---|
| `internal/database/models.py` | Owner assignment | Assign to batch with most model changes |
| `tests/conftest.py` | Owner assignment | Assign to batch with most fixture changes |
| `configs/**/*.toml` | Dedicated batch | Config changes are additive and rarely conflict |
| `docs/llm/*.md` | Dedicated batch | Docs benefit from the full picture |
| `requirements.direct.txt` | Owner assignment | Assign to batch adding the dep; other batches pin verify |

### 3.4 Naming Convention

Each batch receives a descriptive slug used as its identifier throughout the process:

- Use kebab-case: `chat-history-search`, `proxy-lifecycle`, `fastembed-provider`, `shared-config-docs`.
- The slug is used in task descriptions and as a label in review reports.
- Avoid generic names like `batch-1`, `misc` -- they obscure what the batch contains.

---

## 4. Per-Batch Review Execution

### 4.1 Delegation to `code-reviewer`

Each batch is reviewed by dispatching one `code-reviewer` invocation. The brief must contain:

1. **Exact file paths** in the batch. List them explicitly (do not say "all files in the chat-search directory" -- the reviewer needs concrete paths to load).
2. **Feature summary:** One paragraph describing what the feature does and why it exists. This helps the reviewer's "Understand Intent" pass (see `code-reviewer.md` step 2).
3. **Risk tags** for files that need extra attention, especially those matching the special-attention tags defined below (Section 4.4).
4. **Reference to AGENTS.md conventions** the reviewer should verify against -- especially relevant when the batch adds new files (camelCase check, docstring presence, type hints, no pydantic, no snake_case).

### 4.2 Parallel Execution

Independent batches (those whose file lists are disjoint and have no data dependency) can and should be reviewed **in parallel**. The `code-reviewer` agent is read-only (no `edit`, `write`, or `task` permissions), so parallel reviews cannot conflict.

### 4.2.1 Real-World Example

In a review of 78 files across 6 batches, all batches were dispatched in a single message with 6 parallel `Task` tool calls — each to a separate `code-reviewer` agent. Since the agent is read-only, there are no file conflicts. All 6 reviews completed independently and were collected by the orchestrator.

Execution order:
1. **Parallel:** Batches A1 (chat-search-repos, 15 files), A2 (chat-search-handler, 15 files), B (proxy-lifecycle, 17 files), C (fastembed-provider, 4 files), D (llm-abstraction, 7 files), E (shared-config-docs, 20 files) — all dispatched simultaneously.
2. **Sequential after all per-batch reviews:** Integration pass (full 78-file diff).

6 parallel reviews completed with zero critical issues found across the entire diff.

Only sequence batches when one has a genuine data dependency on another:

- Batch B references a class or function defined in Batch A.
- Batch B changes a file that Batch A already modified (cross-cutting file, Strategy A case).
- Batch B's correctness depends on a design decision made during Batch A's review (e.g., a schema choice that Batch B's queries depend on).

### 4.3 Review Depth by File Type

The `code-reviewer` agent's multi-pass analysis (architectural fit, correctness, security, error handling, maintainability) should be calibrated by file type:

| File type | Expected depth | Specific checks |
|---|---|---|
| Production logic (handlers, services, repos, providers) | Full review: all 5 passes | Correctness, security, error handling, conventions, concurrency |
| Tests | Focused: correctness + coverage | Test logic correctness, edge case coverage, async patterns, fixture usage, no mocks that mask bugs |
| Config TOML files | Light: consistency | Keys match code expectations, no broken references, correct TOML syntax, defaults present for new settings |
| Documentation (markdown) | Light: consistency | Descriptions match code changes, no stale references, no broken links, examples use correct commands |

### 4.4 Special Attention Tags

When certain risk tags appear in a batch, the orchestrator must append domain-specific checklist items to the review brief:

#### `[DB-MIGRATION]`

- SQL portability: no `AUTOINCREMENT`, no `DEFAULT CURRENT_TIMESTAMP`, no `SERIAL`, no `COLLATE NOCASE`, no `ON CONFLICT` written by hand (use `provider.upsert` with `ExcludedValue`).
- Column types are portable: `TEXT`, `INTEGER`, `REAL`, `TIMESTAMP`, `BOOLEAN` (stored as int). JSON stored as `TEXT`.
- Primary key strategy: composite natural key preferred, then single natural key, then app-generated UUID/ULID as `TEXT`.
- `:named` placeholders used (not `?`, `%s`, or f-strings).
- Migration version number is sequential (no gaps, no conflicts). Check with `ls -1 internal/database/migrations/versions/ | grep migration_ | sort -V | tail -1`.
- Dual-schema docs updated: `docs/database-schema.md` and `docs/database-schema-llm.md`.

#### `[NEW-HANDLER]`

- `LLMMessageHandler` ordering invariant: new handler is registered **before** `LLMMessageHandler` in `HandlersManager` (line ~534 in `manager.py`).
- camelCase naming on all methods and variables in the handler.
- `BaseBotHandler` pattern compliance: extends `BaseBotHandler`, calls `super().__init__()`, implements `newMessageHandler()` returning `HandlerResultStatus`.
- Config-gating: if feature is optional, registered conditionally via `configManager.get(...)` check.
- Platform-agnostic message sending: uses `self.sendMessage()`, not platform-specific API calls.
- Docstrings and type hints present on all methods.
- LLM tool handler naming uses `_llmTool*` prefix if tools are registered.

#### `[SINGLETON-LIFECYCLE]`

- `getInstance()` pattern used (not direct `Service()` constructor).
- Initialisation guard: `if not hasattr(self, 'initialized')` pattern preserved.
- Thread safety: `_lock` attribute present, used in `__new__` or `__init__`.
- Test fixture reset: `_instance = None` is restored in tests (autouse fixture or explicit cleanup).
- Existing callers checked for breakage (grep for `Service.getInstance()` usage).

#### `[EXTERNAL-DEP]`

- Dependency added to `requirements.direct.txt` (not `requirements.txt` directly).
- Version is pinned to exact version.
- If optional: uses `try/except ImportError` guard with `_AVAILABLE` boolean flag and no `None`/stub assignment in the except branch.
- If mandatory: imported at top level with no guard.

### 4.5 Output Format

The `code-reviewer` agent produces a structured report per the format defined in `.opencode/agents/code-reviewer.md`:

- **Summary** -- scope, baseline, overall quality.
- **[CRITICAL]** -- Tier 1 issues (must fix).
- **[IMPORTANT]** -- Tier 2 issues (should fix).
- **[RECOMMEND]** -- Tier 3 issues (worth addressing).
- **[NIT]** -- Tier 4 issues (optional polish).
- **[STRENGTHS]** -- things done well.
- **[QUESTIONS]** -- clarifications needed.
- **Next Steps** -- how to proceed.

Each report must have the batch slug in the Summary or as a label so results can be traced back to the batch.

---

## 5. Integration Pass (Whole-Work Review)

### 5.1 When to Run

After all per-batch reviews are clean -- meaning no unresolved [CRITICAL] or [IMPORTANT] issues remain across any batch.

### 5.2 What It Checks

One final `code-reviewer` pass on the **full diff** (all files since the base commit). This pass is intentionally lighter than per-batch reviews -- it trusts the per-batch depth and focuses exclusively on cross-batch concerns:

1. **Cross-batch inconsistencies:** Duplicate logic, conflicting config keys, incompatible style choices between batches.
2. **Orphaned references:** A class or function imported in one batch's file but only referenced in another batch's file. An import added in Batch A and used in Batch B should have been visible during Batch B's review, but if neither review caught the full import chain, the integration pass will.
3. **Stale documentation:** Docs that reference pre-change state, config keys that were renamed in one batch but not updated in docs, code examples in docs that no longer compile.
4. **Conflicting styles:** Two batches that chose different patterns for the same problem (e.g., one batch uses `Optional[Type]` and another uses `Type | None`) -- inconsistencies like these should be normalised.
5. **Missed quality gates:** Files that bypassed a specific convention check because each per-batch reviewer assumed another batch would handle it.

### 5.3 If It Finds Issues

- Fix the issues, then re-run **only the integration pass** (not individual per-batch reviews).
- If the complaints trace back to a specific batch, mark that batch for re-review as well.

---

## 6. Remediation Workflow (for teamlead)

After all reviews complete (per-batch + integration), the `teamlead` agent executes this workflow:

### Step 1: Present Results to User

Collect all review reports into a single consolidated view:

- **CRITICAL and IMPORTANT issues** — presented as a table with file paths and one-line descriptions.
- **RECOMMEND and NIT issues** — presented separately for user triage.

The user decides which RECOMMEND and NIT items to fix. Exception: obviously-needed fixes (typos, stale comments that contradict code, broken doc links, dead code) should be fixed without waiting for user approval — they are low-risk and unambiguous.

### Step 2: Fix Critical and Important Issues

All CRITICAL and IMPORTANT issues MUST be fixed before merge. No exceptions.

1. **Group findings by file** to minimise edit conflicts during fix dispatch.
2. **Dispatch fixes** to `software-developer` agents:
   - Parallel dispatch for files that do not overlap.
   - Sequential dispatch for files that do overlap (fix the foundational file first).
3. **Targeted re-review**: after fixes land, dispatch `code-reviewer` re-reviews on the fixed files only. The brief must include the specific issues addressed.
4. **Quality gates**: run `make format lint && make test` after fixes.

### Step 3: Process User-Approved Recommendations and Nits

After the user triages the RECOMMEND and NIT lists:

1. Fix all user-approved items (plus the auto-approved obvious fixes).
2. Same fix → re-review → quality gates cycle as Step 2.

### Step 4: Final Integration Pass

One more `code-reviewer` pass on the full post-fix diff (`git diff <base>..HEAD`) to catch fix-induced regressions. This is the final clearance gate before merge.

### 6.1 Consolidated Results Format

When presenting results to the user, use this format:

```
## Review of N files across M commits

**Result: X Critical, Y Important, Z Recommendations, W Nitpicks.**

### Critical & Important (must fix)
| # | Issue | File |
|---|---|---|
| 1 | Description | path/to/file.py |
| ... | ... | ... |

### Recommendations (user decides)
| # | Issue | File |
|---|---|---|
| 1 | Description | path/to/file.py |
| ... | ... | ... |

### Nitpicks (user decides)
| # | Issue | File |
|---|---|---|
| 1 | Description | path/to/file.py |
| ... | ... | ... |
```

The table format lets the user quickly scan and triage without reading full review reports.

---

## 7. Appendix: Example -- Current Batch (20 commits, 77 files, master..HEAD)

This section demonstrates a concrete application of the methodology to a real diff: 20 commits, 77 files changed, 13,349 insertions, 172 deletions against `master`.

### 7.1 Pre-Review Characterization

The files were grouped into 5 feature domains:

| Batch slug | Feature | Files | Risk Tags |
|---|---|---|---|
| A: `chat-history-search` | Chat history search: `/search` handler, embedding pipeline, vector search tools, migration 017, relevant repos, embedding utility files | ~22 files | DB-MIGRATION, NEW-HANDLER, EXTERNAL-DEP (fastembed) |
| B: `proxy-lifecycle` | Proxy lifecycle: `ProxyService`, `ProxyLifecycle`, subprocess management, proxy config updates | ~7 files | SINGLETON-LIFECYCLE, EXTERNAL-DEP, PROCESS-MGMT |
| C: `fastembed-provider` | FastEmbed LLM provider: provider class, abstract layer changes, model config | ~5 files | EXTERNAL-DEP |
| D: `llm-abstraction` | LLM abstraction changes: `lib/ai/abstract.py`, basic OpenAI provider changes, YC SDK changes, test updates | ~6 files | (medium risk) |
| E: `shared-config-docs` | Cross-cutting: config TOML files, `docs/llm/*` updates, plans, memory files, `tests/conftest.py`, `internal/database/models.py`, `requirements.direct.txt` | ~37 files | CONFIG-CHANGE (low risk, cross-cutting) |

### 7.2 Batch Size Analysis

**Batch A (~22 files)** is at the upper bound of the 15-20 range. If the `code-reviewer` struggles with this batch, it could be split into:

- `chat-history-search-data` (migration 017 + repo changes + model changes: ~10 files)
- `chat-history-search-handler` (handler + embedding pipeline + tools: ~12 files)

**Batch E (~37 files)** is far above the 24-file threshold. However, most of its files are low-risk (config defaults, markdown docs, memory files). If the reviewer returns empty or shallow results, split into:

- `shared-config` (TOML configs + conftest + models.py + requirements: ~10 files)
- `shared-docs` (docs/llm/* + plans + memories: ~27 files)

### 7.3 Dependency Mapping

| Dependency | Affected batches |
|---|---|
| `internal/database/models.py` (new enums for search + proxy) | A, B, E |
| `docs/llm/tasks.md` (gotcha table additions for search + proxy) | A, B, E |
| `configs/**/*.toml` (new sections for search + proxy + fastembed) | A, B, C, E |
| `lib/ai/abstract.py` (abstract provider changes for fastembed) | C, D |
| `tests/conftest.py` (new fixtures for search tests) | A, E |

### 7.4 Execution Order

```
         ┌──────────────────────────────────┐
         │   B: proxy-lifecycle  (7 files)  │  ─┐
         │   C: fastembed-provider (5)      │  ─┤  Parallel
         │   D: llm-abstraction   (6 files) │  ─┘
         └──────────────────────────────────┘
                        │
                        ▼
         ┌─────────────────────────────────┐
         │   A: chat-history-search (22)   │  May reference LLM
         └─────────────────────────────────┘  abstraction (Batch D)
                        │
                        ▼
         ┌─────────────────────────────────┐
         │   E: shared-config-docs  (37)   │  Needs full picture
         └─────────────────────────────────┘
```

**Rationale:**

1. **Parallel: Batch B, C, D** -- all independent. No file overlaps. Proxy lifecycle, FastEmbed provider, and LLM abstraction changes touch entirely different areas.
2. **Batch A after D** -- chat-history-search may reference the abstract LLM layer modified in Batch D (e.g., new provider methods used by the embedding pipeline). Review D first so A's reviewer sees the final shape of the interface.
3. **Batch E last** -- shared config and docs benefit from knowing the full picture. Config key names, documentation cross-references, and memory file summaries should reflect all feature batches.

### 7.5 Remediation After Integration

Given the volume (77 files across 5 batches), remediation will likely involve multiple files with overlapping edits. The teamlead should:

1. Merge all [CRITICAL] and [IMPORTANT] findings from 5 per-batch reports + 1 integration report.
2. Group by file path. Files modified by multiple batches (models.py, conftest.py, tasks.md) will have the most clustered issues.
3. Dispatch fixes in parallel for non-overlapping files, sequentially for overlapping ones.
4. Run `make format lint && make test` after all fixes land.
5. One final integration pass to confirm the full 77-file diff is clean.

---

## See Also

- [`.opencode/agents/code-reviewer.md`](../../.opencode/agents/code-reviewer.md) -- code-reviewer agent definition, methodology, and output format
- [`../../AGENTS.md`](../../AGENTS.md) -- standard review gates (Gate 1 per-subtask, Gate 2 whole-work)
- [`teamlead-memory.md`](teamlead-memory.md) -- teamlead workflow lessons (parallel batching, conflict resolution, subagent reliability notes)
- [`index.md`](index.md) -- project overview, conventions, commands
- [`tasks.md`](tasks.md) -- step-by-step task workflows, anti-patterns, and gotchas
- [`handlers.md`](handlers.md) -- handler creation and registration guide
- [`database.md`](database.md) -- database operations and migration guide
- [`services.md`](services.md) -- service singleton patterns
- [`libraries.md`](libraries.md) -- library API reference
- [`testing.md`](testing.md) -- testing patterns and fixtures

---

*This guide should be consulted whenever a diff exceeds ~24 files, or when a single feature domain within a diff exceeds ~20 files.*
*Last updated: 2026-06-28*
