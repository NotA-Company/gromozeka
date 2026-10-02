---
description: Run the large-changes review methodology on the current diff — characterize, batch by feature domain, parallel per-batch review, integration pass, present consolidated findings (docs/llm/reviewing-large-changes.md)
agent: teamlead
---
Run the methodology in `docs/llm/reviewing-large-changes.md` end-to-end on the
current diff, stopping at the consolidated-findings handoff (Section 6 Step 1).
Do NOT auto-remediate — surface findings; the user decides what to fix.

`docs/llm/reviewing-large-changes.md` is the **authoritative methodology**; this
command is a thin wrapper that fixes the scope (the diff under review) and the
stopping point (Section 6 Step 1). **Read that file first** before dispatching
anything. Section numbers referenced below correspond to it exactly.

When markdown-mcp tools are available, read it via `doc_outline` + `doc_read`
(docs-root-relative path: `llm/reviewing-large-changes.md`; resolve section
slugs from the outline at run time, never hard-code them). Otherwise `read`
the file directly — this step must work either way.

This is a long-running command whose results are surfaced live to the user
(not silently committed). It does NOT pause for clarification mid-flight —
make best-effort decisions and surface assumptions in the final summary.

## Argument handling

Evaluate `$ARGUMENTS` as the base commit of the diff under review.

- If `$ARGUMENTS` is **non-empty**: use it verbatim as the base. Validate it
  resolves via `git rev-parse <base>` (delegate to `explore` — you have no
  `bash`). If it does not resolve, ABORT with a one-line error
  naming the bad base and stop. Do not guess or fall back.
- If `$ARGUMENTS` is **empty** (default): base = the fork-point from `master`,
  computed via `git merge-base master HEAD`. State this in the summary.
- The diff under review is always `<base>..HEAD`, regardless of branch.

Examples the user may invoke: `/review-large master`,
`/review-large HEAD~20`, `/review-large some-tag`, `/review-large origin/main`.

## Trigger threshold (doc §1.1)

The methodology is designed for diffs **>24 files**, OR any single feature
domain within the diff **>20 files**. Delegate a `git diff <base>..HEAD
--name-only` count to `explore`.

If the diff is **smaller** than the threshold, WARN the user in the summary
that the standard Gate 1 / Gate 2 flow from `AGENTS.md` probably suffices — but
**proceed anyway**, since the user invoked the command explicitly. Do not abort
on size.

## Pipeline

Execute the methodology phase by phase. Section numbers cite
`docs/llm/reviewing-large-changes.md`.

### §2 Pre-Review: Characterize the Diff

- §2.1 Inventory: enumerate every changed file via
  `git diff <base>..HEAD --name-only`; group by feature domain; tally per
  domain.
- §2.2 Risk triage: tag each file with one or more of `DB-MIGRATION`,
  `NEW-HANDLER`, `SINGLETON-LIFECYCLE`, `EXTERNAL-DEP`, `SECURITY`,
  `PROCESS-MGMT`, `CONFIG-CHANGE`, `HIGH-RISK` (2+ other tags).
- §2.3 Dependency mapping: identify cross-cutting files
  (`internal/database/models.py`, `tests/conftest.py`, `configs/**/*.toml`,
  `requirements.direct.txt`, `docs/llm/*.md`).
- §2.4 Produce the classification table (batch slug, file list, risk tags,
  dependency notes) and include it in the summary.

### §3 Batch by Feature Domain

- §3.1 One batch = one self-contained feature domain; batches are disjoint in
  file lists.
- §3.2 Size guardrails: target **15-20 files per batch**; **24-file upper
  bound** (split above that along data / handler / config / test layer lines).
- §3.3 Cross-cutting files: apply Strategy A (owner assignment) or Strategy B
  (dedicated infrastructure batch) per the table in §3.3.
- §3.4 Name batches with kebab-case slugs (`chat-history-search`,
  `proxy-lifecycle`, `fastembed-provider`, `shared-config-docs`). Avoid
  generic names like `batch-1` or `misc`.

### §4 Per-Batch Review

Dispatch `code-reviewer` in **parallel** for independent batches (disjoint
file lists, no data dependency) — place multiple `Task` calls in a single
message. Sequence only on genuine data dependencies (per §4.2.1).

Each per-batch brief MUST include:

1. **Exact file paths** in the batch — enumerated, not "all files in X".
2. **One-paragraph feature summary** describing what the feature does and why.
3. **Risk tags** for the files in the batch.
4. **AGENTS.md conventions to verify** (see "Project conventions" below).
5. When `DB-MIGRATION` / `NEW-HANDLER` / `SINGLETON-LIFECYCLE` /
   `EXTERNAL-DEP` tags appear, append the matching special-attention
   checklists from §4.4.

Per §4.3, calibrate review depth by file type (production logic = full 5-pass;
tests = correctness + coverage; config TOML = light consistency; docs = light
consistency).

### §5 Integration Pass

After all per-batch reviews are clean (no unresolved [CRITICAL] or
[IMPORTANT] anywhere — §5.1), dispatch ONE final `code-reviewer` invocation on
the **full diff** (`git diff <base>..HEAD`) to catch cross-batch issues per
§5.2: cross-batch inconsistencies, orphaned references, stale documentation,
conflicting styles, missed quality gates.

When markdown-mcp is available, two more inputs can serve the stale-doc
check: `doc_lint` output (structural drift — duplicate slugs, front-matter
issues) and `doc_search` queries against `docs/llm/` for stale claims
(results are fresh once the incremental index that follows each
`doc_write` / `doc_section_edit` has run). The `code-reviewer` subagent
inherits read-only markdown-mcp tools, so it can run these itself — mention
them in its brief. These are optional inputs, never a gate: without MCP the
integration pass works from the diff alone.

### §6 Step 1: Present Results

Produce the consolidated findings per §6.1, in the exact table format defined
there:

- **Critical & Important** in one table (issue + file path).
- **Recommendations** in a second table.
- **Nitpicks** in a third table.

Lead with the one-line summary: `Review of N files across M commits — Result:
X Critical, Y Important, Z Recommendations, W Nitpicks.`

## Stop point (CRITICAL)

**After §6 Step 1, STOP.** Do NOT execute §6 Steps 2-4 (fix Critical/Important,
process user-approved rec/nit, final integration pass) without explicit user
direction. This command surfaces findings; the user decides what to fix and
typically invokes follow-up work (or `/changelog` for any resulting entries)
separately.

If the integration pass (§5) finds issues, surface them in the consolidated
table — do not dispatch fixes. Remediation is out of scope for this command.

## Project conventions reviewers should verify

In every per-batch brief, instruct the reviewer to verify against `AGENTS.md`
and `docs/llm/`. The commonly-forgotten subset:

- **Naming:** `camelCase` for variables/args/fields/functions/methods;
  `PascalCase` for classes; `UPPER_CASE` for constants. `snake_case` is wrong
  here even though it's idiomatic Python.
- **Docstrings** on every module/class/method/function/field, with `Args:` and
  `Returns:` describing all params and return type.
- **Type hints** on all function/method params and returns; on locals when the
  type isn't obvious.
- **No `Any`** type. **No pydantic** — raw dicts + TypedDict / hand-rolled
  type-hinted classes.
- **Python invocation via `./venv/bin/python3`** — never `python` / `python3`.
- **SQL portability** (see `docs/sql-portability-guide.md`): `:named`
  placeholders, go through `BaseSQLProvider` (`execute` / `executeFetchOne` /
  `executeFetchAll` / `batchExecute` / `upsert` with `ExcludedValue`); no
  `AUTOINCREMENT`, no `DEFAULT CURRENT_TIMESTAMP`, no `SERIAL`, no
  `COLLATE NOCASE`, no hand-written `ON CONFLICT`.
- **Handler ordering invariant:** `LLMMessageHandler` MUST stay last in
  `HandlersManager` (`internal/bot/common/handlers/manager.py`).
- **Singleton access:** `Service.getInstance()`, never `Service()` directly.

## Subagents this command dispatches

- **`code-reviewer`** — read-only; used for per-batch reviews (§4) and the
  integration pass (§5). Cannot edit code, so parallel dispatch is safe.
- **`explore`** — for diff inventory and base-commit resolution (you have no
  `bash` permission; delegate all `git` invocations).
- If the user later approves fixes, those go to **`software-developer`** in
  follow-up work **outside this command's scope**.
