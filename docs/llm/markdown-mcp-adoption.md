---
category: plan
tags: [markdown-mcp, adoption]
---

# markdown-mcp adoption plan (research report)

Status: research-only, 2026-09-14. No files were modified. Every fact below
verified against current file contents; inferences flagged as such.

## 0. Verified ground truth

| Fact | Evidence |
|---|---|
| `docs_root = "./docs"`, `exclude = ["archive/", "other/"]`, `writable = true`, `rescan_interval = 30` | `.markdown-mcp.toml:14-18` |
| Read caps `section_read_cap = 8192`, `disk_read_cap = 65536` (owner-ratified 2026-09-06) | `.markdown-mcp.toml:24-27` |
| MCP server registered in **global** opencode config only, `enabled: true`, `["/Users/vgoshev/bin/markdown-mcp", "--use-global-config", "serve"]` | `~/.config/opencode/opencode.jsonc:41-46` |
| Project `.opencode/opencode.json` has **no** `mcp` block (only `default_agent`, model tiers, `lsp`) | `.opencode/opencode.json:1-29` |
| Probe (2026-09-14): `general` subagent sees all 10 `markdown-mcp_doc_*` tools → subagents inherit MCP tools; `doc_list` (llm/*) → 59 files all indexed ok; `doc_lint` → 0 findings | probe session ses_f60f9b7feffeZUf1QLj21aB3g1 |
| `make check-docs` → `scripts/check_docs.py` (local-link checker; excludes `.opencode/` per `_EXCLUDED_DIR_NAMES`) | `Makefile:110-112`, `scripts/check_docs.py:56-60` |
| CI runs only `sh scripts/ci.sh` → apk deps + `make check` (lint + black check) + `make test` — **no check-docs, no markdown-mcp** | `.sourcecraft/ci.yaml:24-25`, `scripts/ci.sh:17-22` |
| CLI `markdown-mcp lint` respects `[docs].exclude`; MCP `doc_lint` historically did not (2026-09-14 probe: 0 findings, exclude honored) | `docs/llm/teamlead-memory.md` §markdown-mcp ops |
| NEVER `markdown-mcp index --force` (embedding rebuild times out); incremental `markdown-mcp index` repairs | `docs/llm/teamlead-memory.md` §markdown-mcp ops |
| Serve process holds config from process start; 30s rescan; holds SQLite writer lock | `docs/llm/teamlead-memory.md` §markdown-mcp ops |

## 1. Surface inventory

Priority key: **High** = agents hit it on nearly every task; **Medium** = routine but narrower; **Low** = background/reference.

### 1.1 Root `AGENTS.md` — priority: High

| Location | Current instruction (quote) | Proposed change | Risk |
|---|---|---|---|
| `AGENTS.md:3-4` | "The canonical, deeper guide lives in `docs/llm/index.md` — read it before non-trivial work." | Append: "With markdown-mcp available: `doc_list` + `doc_outline("llm/index.md")` + targeted `doc_read(section_slug)` instead of reading the whole file; `doc_search` for targeted questions. Fallback wording for tools without MCP: plain `read` remains valid." | **AGENTS.md is consumed by non-opencode tools (Roo/Cline/Cursor are named as the audience in `docs/llm/index.md:8`) that have no MCP access — wording must be "prefer MCP when available," never exclusive.** |
| `AGENTS.md:35` | "make check-docs # checks local markdown links resolve (read-only; exit 1 if broken)" | Keep as-is; add one line: "markdown-mcp `doc_lint`/CLI `markdown-mcp lint` complement it (structural lint: duplicate slugs, front matter); CLI lint stays authoritative on disputes (older MCP `doc_lint` builds surfaced excluded-path noise; current builds honor the exclude list)." | Low; gates stay additive. |
| `AGENTS.md:45-46` | "**Normative text:** `docs/llm/index.md` §3 — read it before editing code." | Replace "read it" with "read §3 via `doc_read("llm/index.md", section_slug=…)` when markdown-mcp is available (resolve the slug from `doc_outline` at use time; cite sections by name, not hard-coded slugs)." | Slug stability: slugs are derived from headings and re-derived per generation — cite by *section name*, let the agent resolve the slug via `doc_outline`. |
| `AGENTS.md:62-63` | "Always run `make test` … see docs/llm/index.md §3.5." | No change (runtime gate, not a doc operation). | — |
| `AGENTS.md:84-100` (Changelog) | "add a one-line entry under `## [Unreleased]` in `CHANGELOG.md` … see `docs/llm/changelog.md`" | No tooling change — `CHANGELOG.md` is at repo root, **outside `docs_root`**; must stay on manual edit. Optionally note this explicitly so agents don't try MCP. | Low. |
| `AGENTS.md:122-123` | "find the next number with `ls -1 internal/database/migrations/versions/ | grep migration_ | sort -V | tail -1`" | No change — source-tree operation, not docs. | — |
| `AGENTS.md:227-248` ("Existing instruction sources") | Full pointer list: `docs/llm/index.md`, `docs/README.md`, `docs/developer-guide.md`, skills, etc. | Add one bullet: "`docs/docs-playbook/mcp-docs-workflow.md` + `gromozeka-workflow-brief.md` — how to work the docs tree via markdown-mcp (prefer over manual reads when the MCP server is available)." | Low; purely additive, consistent with the section's "do not duplicate, prefer linking" charter. |

### 1.2 Global `~/.config/opencode/AGENTS.md` — priority: Medium

| Location | Current instruction | Proposed change | Risk |
|---|---|---|---|
| `~/.config/opencode/AGENTS.md:9-10` | "1. **`AGENTS.md` at the repo root** … Treat as authoritative. 2. **`README*`, `CONTRIBUTING*`, and any `docs/` tree** — architecture overviews…" | Add a clause: "If the project provides a markdown-mcp config (`.markdown-mcp.toml`) and the MCP server is available, discover the docs tree via `doc_list`/`doc_search` instead of walking directories." | **Global file is repo-agnostic** — most repos have no markdown-mcp; wording must be conditional. Also this file is shared across all projects, so edits affect every session. |
| `~/.config/opencode/AGENTS.md:34-36` | "When behavior…change, update the relevant docs … (`README*`, `docs/`, `AGENTS.md`, schema references) as part of the same change." | Optionally add: "Prefer the project's documented doc-editing workflow (e.g. a docs playbook) over raw file edits." | Low. |

### 1.3 `.agents/skills/` — priority: High (these are the operative recipes)

#### read-project-docs/SKILL.md (103 lines) — the single highest-leverage change

Its entire purpose is manual reading of docs.

| Location | Current instruction | Proposed change | Priority / Risk |
|---|---|---|---|
| `:32-34` | "## Read order (strict) — The repo enforces a specific order of authority. Follow it." | Keep the *authority order*; make the *mechanism* dual: each step gets "MCP: `doc_read(file, section_slug)` / manual: `read`" phrasing. | High. Skills are loaded by subagents that **do** have the tools (probe-verified), so MCP-first is safe here. |
| `:38` | "**Read:** `AGENTS.md` at the repo root." | No MCP path exists (outside docs root) — keep manual `read`. Mark explicitly "manual — outside docs root." | Low. |
| `:46` | "**Read:** `docs/llm/index.md`." | Replace with: `doc_outline("llm/index.md")` → targeted `doc_read` of the navigation matrix and §3; full disk read as fallback. | High. |
| `:54-57` | "Read … `docs/llm/teamlead-memory.md` … `docs/llm/memories/index.md` … then read only the specific memory file(s) relevant" | Replace discovery with `doc_search(query, file_glob="llm/memories/*.md")` + `doc_list`; targeted section reads. Note `teamlead-memory.md` is large (265+ lines) — section reads are the win. | High. |
| `:65-79` (navigation matrix) | "Your task involves… → Read `docs/llm/handlers.md` …" | Keep matrix; reframe "Read" as "`doc_outline` + targeted `doc_read`"; searching "which doc covers X" → `doc_search(query, category=…)`. | High. |
| `:84` | "`docs/developer-guide.md` … Do not trust hardcoded section numbers — find content by heading." | Same advice maps directly to `doc_outline` — one line addition. | Low. |
| `:90` | "**Be selective.** Blanket-reading all `docs/llm/**/*.md` wastes context." | Strengthens under MCP: section reads + search make selectivity cheaper. | Low. |

Note: the skill's relative links (`../../../AGENTS.md`) resolve from `.agents/skills/<name>/` — fine either way; the MCP path form (`llm/index.md`, docs-root-relative) should be introduced alongside, not replacing, so the skill works without MCP.

#### update-project-docs/SKILL.md (211 lines) — the doc-write recipe. Second highest leverage.

| Location | Current instruction | Proposed change | Priority / Risk |
|---|---|---|---|
| `:54-71` (Step 2 matrix) | "If you changed… Update [`docs/llm/handlers.md`]…" | Add a preamble: "When markdown-mcp is available, perform every `docs/`-tree update through `doc_section_edit` (preferred) or `doc_write`, per `docs/docs-playbook/mcp-docs-workflow.md`: `doc_read` first (CAS token), edit, check `reindex.status`." | High. |
| `:71` | "Refactor: Search all `docs/llm/**/*.md` … for old paths/symbol names." | `doc_search("old-symbol")` scoped by `file_glob` is the direct replacement; note search is **semantic + stale-index-sensitive** — run incremental `markdown-mcp index` after bulk out-of-band refactors first, and a raw Grep sweep remains the exhaustive-coverage fallback (search is score-floored, not exhaustive). | **High risk if done naively**: semantic search can miss occurrences below `min_score`; keep Grep as the completion check. |
| `:110-120` (Step 5 inline READMEs) | "scan: `glob lib/**/README.md` … Open any that describe files… and update them." | **Stays manual** — `lib/**` and `internal/**` are outside `docs_root`. Mark explicitly "manual tools — outside docs root." | Low. |
| `:122-148` (Step 6 CHANGELOG + root README) | "Add a one-line entry under `## [Unreleased]` in `CHANGELOG.md`… update `README.md`" | **Stays manual** — repo-root files, outside docs root. | Low. |
| `:150-152` (Step 7 dev guide) | "Find relevant sections **by heading**, not section number." | Directly expressible as `doc_outline` + `doc_section_edit`. | Medium. |
| `:162-181` (Step 9 verification) | "make format lint && make test still green… `make check-docs` run; no broken markdown links" | Add: "`doc_lint()` clean (or CLI `markdown-mcp lint`, which stays authoritative on disputes — older MCP builds surfaced excluded-path noise)"; keep `make check-docs` (it validates **links**, which `doc_lint` does not) and `make test`. | Medium. |
| `:179` | "If you are `docs-writer` … substitute `make lint && make check-docs` as your verification gate." | Extend the substitution: "`make lint && make check-docs` + `doc_lint` clean." | Medium. |

#### run-quality-gates/SKILL.md (131 lines)

No manual doc-workflow instructions found (pure runtime gates). Optional one-line addition under "What this skill does NOT cover" (`:127-131`): docs-tree linting via `doc_lint`/CLI is separate from `make lint`. Priority: Low.

#### write-regression-test/SKILL.md (390 lines)

Prerequisites prescribe manual reads (`:52-57`: "`docs/llm/testing.md` … `docs/llm/tasks.md` §1.6 …, §3 …, §4 … `docs/llm/teamlead-memory.md` … `AGENTS.md`"), and Step 8 (`:361-372`) prescribes doc sync. Proposed change: same dual-mechanism phrasing as read-project-docs for the four read targets; Step 8 delegates to update-project-docs (already covered). Priority: Medium. Risk: low — reads only.

#### add-database-migration/SKILL.md (237 lines)

Prerequisites reads (`:36-40`), Step 7 "Documentation (mandatory, three files)" (`:200-212`: update `docs/database-schema.md`, `docs/database-schema-llm.md`, `docs/llm/database.md`). Proposed change: prerequisite reads via MCP (dual phrasing); Step 7's three doc updates through `doc_section_edit` when available. `internal/database/migrations/README.md` (`:208`) stays manual (outside docs root). Priority: Medium.

#### add-handler/SKILL.md (282 lines)

Prerequisites (`:32-36`), Step 9 Documentation (`:250-256`: update `docs/llm/handlers.md`, `docs/llm/index.md` §4.5). Same treatment. Note `docs/llm/index.md` §4.5 aggregate-row edits are a textbook `doc_section_edit replace`. Priority: Medium.

#### add-llm-tool/SKILL.md (453 lines)

Prerequisites (`:71-77`), Step 6 Documentation (`:396-409`: handlers.md/services.md/configuration.md/index.md §5). Same treatment. Priority: Medium.

#### add-chat-setting/SKILL.md (195 lines)

Reads `AGENTS.md`/`tasks.md` (`:122`), Step 7 Documentation (`:168-174`). Same treatment. Priority: Medium.

### 1.4 `.opencode/agents/*.md` — priority: High (tool/permission plumbing)

| Agent | Relevant facts | Proposed change | Priority / Risk |
|---|---|---|---|
| `docs-writer.md` | **The doc-sync workhorse.** Permissions: `edit/write` allow only `*.md`/`*.txt` with `.opencode/**`+`.agents/**` denies (`:32-43`); Method = manual `git status`/`Glob`/`Grep` + bulk fixes (`:106-112`); verification `make lint` + `make check-docs` (`:111`, `:143-144`). No mention of markdown-mcp anywhere. | (a) Prompt: make the Method's docs-tree reads/edits MCP-first (`doc_search` for stale-value sweeps — with Grep as exhaustive fallback; `doc_read`→`doc_section_edit` for edits; `reindex.status` check; `doc_lint` added to verification). (b) **Permissions: explicitly allow/keep the MCP write tools and decide the policy for agents that must not write docs.** | **High. Key governance risk: MCP tools are not `edit`/`write`, so the `*.md` allow-list and `.opencode/**`/`.agents/**` denies likely do NOT constrain `markdown-mcp_doc_write`.** Structurally the MCP tools can only touch `./docs/**` (paths are docs-root-relative), which matches docs-writer's charter — but whether opencode permission blocks can target MCP tool names (e.g. `markdown-mcp_doc_write: allow`) must be verified before relying on file-type denies. Upside: CAS gating makes concurrent docs-writer/teamlead edits safer than raw edit. |
| `teamlead.md` | Memory protocol: "read `docs/llm/teamlead-memory.md` before delegating" (`:52-53`), "update the memory file immediately" (`:54`) — the only file it may edit (`:16-25` permission block: `edit/write "*": deny` except `docs/llm/teamlead-memory.md`). Gate 1B: `make lint`/`make check-docs` for docs subtasks (`:173`). | (a) Memory reads via `doc_read`/`doc_outline` (file is 265 lines; section reads save context). (b) Memory writes: *if* opencode permission semantics permit restricting `markdown-mcp_doc_*`, teamlead could use `doc_section_edit` on teamlead-memory.md — but **do not enable MCP writes for teamlead until per-tool permissions are verified**, otherwise `edit: "*": deny` is silently bypassable across all of `docs/`. | High (reads) / **High risk** (writes — governance). |
| `software-developer.md` | Full access; workflow = manual read/edit (`:60-66`); "Never create `*.md` docs unless asked" (`:47`); loads update-project-docs after changes (`:52`, `:66`). | Add one line to Workflow step 5: "docs-tree edits via markdown-mcp tools when available (CAS-gated; see docs-playbook), manual edit for root files (AGENTS.md/CHANGELOG.md/README.md) and non-docs markdown." | Medium. |
| `architect.md` | "persist the durable outcome into the project's docs … an ADR entry in `docs/llm/architecture.md`" (`:138`); `edit` limited to `*.md`/`*.txt` (`:16-19`). | ADR insertion into `architecture.md` is the ideal `doc_section_edit insert_after` case (new sibling section with its own heading). Add MCP-first phrasing to Documentation Sync (`:125-138`). Same permission caveat as teamlead: the `*.md` edit allow doesn't automatically map to MCP write tools — verify. | Medium / permission-verification needed. |
| `code-reviewer.md` | Review-only; bash allowlist includes `make lint/test/check-docs` (`:52-57`); docs reviewed as "Light: consistency" batches. | Optional: allow `doc_search`/`doc_read`/`doc_lint` (read-only MCP) for stale-doc checks during integration pass; `doc_lint` findings are a natural review input. Keep all write tools out. | Low / read-only tools are safe. |
| `debugger.md` | Full access; Authoritative Project Context = manual reads (`:50-58`). | Dual-mechanism phrasing on the five context reads. | Low. |
| `code-analyst.md` | Read-only (`bash/edit/task` denied, `:13-21`); "prefer the **Read**, **Grep**, and **Glob** tools" (`:31`). | Add: "For docs questions inside `./docs`, prefer `doc_search`/`doc_read`/`doc_outline` (markdown-mcp) over Read/Grep — index-backed section reads are cheaper; fall back to Read/Grep for excluded paths and everything outside the docs root." No permission change needed (read-only MCP tools are additive). | Medium — this agent runs the exact workflows MCP was built for. |

### 1.5 `.opencode/commands/*.md` — priority: Medium

| Command | Current instruction | Proposed change | Risk |
|---|---|---|---|
| `changelog.md` | Branch 3: "Insert the line under `## [Unreleased]` in `CHANGELOG.md`" (`:55-58`). | **No MCP change possible** — `CHANGELOG.md` is repo-root, outside docs root. Optionally state that explicitly to preclude agent confusion. | Low. |
| `refine-memory.md` | Teamlead edits `teamlead-memory.md` in place; `docs-writer` creates `docs/llm/memories/<slug>.md` + updates `memories/index.md` + runs `make check-docs` (`:131-136`, `:152-154`); section extraction with verbatim body moves + relative-link fix-ups (`:113-129`). | Strong candidate: `doc_write` the destination memory file first (verify), then `doc_section_edit` op=replace to swap the extracted section's body for a stub (heading preserved; delete only if the whole section must go), in-call reindex replaces the freshness dance; `doc_lint` post-check. **But** the front-matter requirement (all live docs carry `category`) must be respected for new files (`category: reference` matches `memories/index.md:2`). The link-fix-up step (`:117-122`) is NOT solved by MCP — `doc_write` writes content verbatim; `make check-docs` remains the gate. | Medium. Permission caveat: teamlead dispatches docs-writer for `memories/` writes — MCP availability for docs-writer must be settled first. |
| `generate-release.md` | "Dispatch docs-writer to perform the cut in `CHANGELOG.md`" (`:66-72`). | No MCP change (repo-root file). | Low. |
| `review-large.md` | "**Read that file first**" (`docs/llm/reviewing-large-changes.md`) (`:11-12`); §2.3 flags `docs/llm/*.md` as cross-cutting (`:58-59`); docs batches get "light consistency" review (`:92-93`). | Read → `doc_read`/`doc_outline`. Integration-pass stale-doc checks (`§5`, `:97-101`) could take `doc_lint` output as an input. Reviewer subagents need read-only MCP (they have it by inheritance). | Low/Medium. |

### 1.6 `.opencode/opencode.json` + MCP config location — priority: High (verified; minimal change)

- `.opencode/opencode.json:4` — `default_agent: teamlead`; `:5-24` model tiers; **no `mcp` block** (`:26-27` is just `"lsp": {}`).
- The server is configured **globally**: `~/.config/opencode/opencode.jsonc:41-46`. Nothing in the project config needs to change for tool availability — the probe confirms inheritance.
- **Required decision, not config:** whether to pin MCP tool permissions per agent in the frontmatter `permission:` blocks (see §1.4). If opencode supports MCP tool entries in `permission:` (unverified), docs-writer/architect get explicit allows; teamlead/code-reviewer get explicit write denies. **This is the one true blocker for flipping write-path defaults.**
- No agent model-tier changes are needed: markdown-mcp is a local MCP server, not a model.

### 1.7 `docs/llm/*.md` normative text — priority: High

| File / location | Current instruction | Proposed change |
|---|---|---|
| `docs/llm/index.md:14-33` (navigation matrix) | "If you need to... Read this doc" table | Add one row: "Work the docs tree itself (read/edit via markdown-mcp) \| `../docs-playbook/mcp-docs-workflow.md`". |
| `docs/llm/index.md:62-77` (§2 Critical Commands) | `make format lint` / `make test` / run commands | Add `markdown-mcp index` (incremental, post-bulk-edits) + `markdown-mcp lint` as docs-tree commands, with the "never `--force`" warning. |
| `docs/llm/index.md:80-270` (§3 Mandatory Rules) | Normative rules; §3.5 quality workflow | §3.5: add docs-tree gate line ("docs changes: additionally `doc_lint`/CLI lint clean"). No other rule changes. |
| `docs/llm/index.md:422` | "*Last updated: 2026-07-18*" | Update when this adoption lands. |
| `docs/llm/tasks.md:124-130` (§1.3 Step 6 "Update documentation (CRITICAL)") | "Update all three schema docs in sync: docs/database-schema.md … docs/database-schema-llm.md … docs/llm/database.md" | All three are inside docs root → MCP-editable. Add: "via `doc_section_edit` (read first for CAS token) when markdown-mcp is available; keep the three-in-sync rule unchanged." |
| `docs/llm/testing.md` | **No manual doc-workflow instructions found** (grep clean; only docstring checklist items at `:469-471`). | No change. |
| `docs/llm/changelog.md:189-216` (§Agent Instructions) | Canonical CHANGELOG editing process | No tooling change (repo-root file); optionally add one sentence: "CHANGELOG.md sits outside the markdown-mcp docs root; edit it with normal file tools." |
| `docs/llm/reviewing-large-changes.md:87,136,189,258` | Docs batches / "stale documentation" checks | Optional: name `doc_search` (fresh after index) as the stale-reference sweep tool in the integration pass; docs-batch reviewers may run `doc_lint`. |

### 1.8 `docs/README.md`, `documentation-review-process.md`, `developer-guide.md`, `docs/guides/*` — priority: Medium

- `docs/README.md` — **already markdown-mcp-aware**: describes the exclusions (`:67-76`) and links both playbooks (`:42-45`). Proposed change: none required; optionally move the playbook links higher in the "For agents" list. Priority: Low.
- `docs/documentation-review-process.md` — the most heavily manual surface:
  - `:75-82` Phase 2: "`find docs -name '*.md' …` / `find docs/llm -name '*.md'`" → replace with `doc_list()` (and note excluded `archive/` needs `find`/Glob still).
  - `:120-128` Phase 4: "1. Read the file first (required by edit tool) 2. Apply targeted edits using the edit tool 3. Run `make format lint test` … 5. Verify links … `make check-docs`" → replace steps 1-2 with the CAS loop (`doc_read` → `doc_section_edit`/`doc_write`, check `reindex.status`); keep 3-5.
  - `:130-139` archival stays a filesystem `mv` + incremental `index` (excluded paths drop out of the index on rescan); reserve `doc_delete` (CAS-gated, removes index rows in-call; "version control is the backup story") for outright deletion of a live indexed doc.
  - `:657-689` "Quick Reference: Review Commands" — mostly `find`/`rg`/`git grep` → add the markdown-mcp equivalents (`doc_search`, `doc_list`, `doc_lint`).
  - `:150-163` Phase 5 quality gates — add lint-clean definition of done per the playbook.
  - Priority: Medium (process doc consumed less often than skills, but it *is* the doc-review canon). Risk: low; its archival/move mechanics must keep the exclude-list caveat.
- `docs/developer-guide.md` — now a 19-line index (verified by full read); **no manual doc-workflow instructions found**. The old monolith's content moved to `docs/guides/*.md` verbatim (`developer-guide.md:8`); grep found no `check-docs`/doc-maintenance workflow text in the guides. Priority: Low → no change.
- `docs/docs-playbook/mcp-docs-workflow.md` + `gromozeka-workflow-brief.md` — **already the target workflow**; they are the destination, not the drift. Two factual corrections needed (see §3).

### 1.9 CI/build — priority: Medium (decide, don't auto-adopt)

- `Makefile:110-112` — `check-docs` target exists; **no markdown-mcp targets exist**.
- `scripts/ci.sh:17-22` — CI = apk deps → `make venv-alpine` → `make install` → `make check` → `make test`. `.sourcecraft/ci.yaml:24-25` runs exactly that. **`make check-docs` is not in CI today; markdown-mcp lint/index is neither.**
- What adoption would require operationally (recommendations):
  1. **Do not** put `markdown-mcp index` in CI: the embedding index is machine-local (gitignored) and rebuilds cost an embedding pass; CI has no need for it.
  2. CLI `markdown-mcp lint` **is** CI-able (parses the tree directly, no index needed), but it needs the binary installed in the Alpine image → new CI dependency + pinning. Recommend: optional follow-up target `make lint-docs` wrapping `markdown-mcp lint`, added to `ci.sh` only after the binary is provisioned in the image.
  3. `make check-docs` arguably *should* join `ci.sh` (venv-Python-only, zero new deps) — independent of markdown-mcp adoption but a natural companion.
  4. Index freshness remains a **local** concern: incremental `markdown-mcp index` after out-of-band bulk edits (rebases, scripted mass edits, branch switches); the running `serve` rescans every 30s.

### 1.10 Memory files — priority: Low

- `docs/llm/teamlead-memory.md` §markdown-mcp ops — already encodes the operational gotchas. No change; this is the reference the adopted wording should cite.
- `docs/llm/memories/index.md:3` — description "read the relevant one before working on a subsystem" → could become "search (`doc_search`, `file_glob='llm/memories/*.md'`) or read". Low.
- `docs/llm/memories/docs-rewrite-2026-09.md` — historical ledger of the rewrite arc. No change (history).

### 1.11 Root `README.md` and `TODO.md` — priority: Low

- `README.md` — only doc links (`:7, :39, :60, :135-136, :157`); **no agent doc-workflow instructions found**. No change.
- `TODO.md` — plain task list; **no agent doc-workflow instructions found**. No change.

## 2. Cross-cutting adoption questions

### 2.1 Fallback policy (agents/contexts without markdown-mcp)

Concrete risks: CI runners (no MCP server), non-opencode AI tools (Roo/Cline/Cursor are explicitly the audience of `docs/llm/index.md:8`), fresh checkouts where `serve` isn't running, and MCP outages.

**Recommended wording strategy — "conditional preference," never exclusivity:**

> "When the markdown-mcp MCP tools (`doc_search`/`doc_read`/`doc_outline`/…) are available, use them for everything under `./docs` (see `docs/docs-playbook/mcp-docs-workflow.md`). Otherwise use the normal file tools — every instruction in this repo remains satisfiable without markdown-mcp. Files outside the docs root (`AGENTS.md`, `CHANGELOG.md`, root `README.md`, `TODO.md`, `.agents/**`, `.opencode/**`, inline `lib/**`/`internal/**` READMEs) are always edited with normal tools."

Place the canonical version in **one** location (`AGENTS.md`, "Existing instruction sources" area) and link it from skills/agents rather than duplicating — consistent with the repo's "do not duplicate, prefer linking" rule (`AGENTS.md:227`).

### 2.2 Division of labor — what stays manual even after adoption

**Permanently manual (outside `docs_root = "./docs"`):**

- `AGENTS.md`, `CHANGELOG.md`, root `README.md`, `TODO.md` (repo root)
- `.agents/skills/**` and `.opencode/**` — also explicitly denied to docs-writer; must be edited by `software-developer`
- Inline `lib/**/README.md`, `internal/**/README.md` (update-project-docs Step 5)
- All source/config/code — docs tools only handle markdown in the tree

**Inside docs root but index-excluded:**

- `docs/archive/**`, `docs/other/**` — searchable never; `doc_read` disk mode still serves them; writes stand but `reindex.status` returns `excluded` (expected only under these prefixes). Archival moves still need filesystem `mv` + incremental `index`.

**Operations that remain better served by manual tools even inside the tree:**

- **Exhaustive stale-value sweeps**: `doc_search` is semantic and score-floored — a Grep sweep is the completion check.
- **Scripted mass rewrites**: a scripted change + one `markdown-mcp index` is the honest shape.
- **`make check-docs` link validation**: `doc_lint` checks structure, not links — both gates stay.
- Reading source code for doc claims — markdown-mcp answers documentation questions only.

### 2.3 Operational prerequisites

1. **CAS discipline** (the core new behavior every agent must learn): `doc_read` before every edit; section edits take `expected_text` = the exact served section body; file ops take `sha256`; on mismatch re-read, never replay a remembered token; chained edits reuse the returned `sha256`; slugs are re-derived from the returned `outline`, never cached.
2. **Index freshness**: normal writes self-reindex in-call (check `reindex.status`); out-of-band bulk edits need incremental `markdown-mcp index`; the serve process rescans every 30s; **never `index --force`**.
3. **Serve process dependency**: config is pinned at process start (exclude-list changes need restart); the server holds the SQLite writer lock (CLI index runs must tolerate/avoid contention).
4. **Gate interaction**: adoption **adds** `doc_lint`/CLI lint to the docs gate; it does not replace `make check-docs` (links) or `make test` (code examples in docs). `make format lint` continues before/after edits per AGENTS.md.
5. **Verify opencode MCP permission semantics** (the one open technical question): can `permission:` blocks in agent frontmatter target `markdown-mcp_doc_write` etc.? Until verified, do not assume `edit:`/`write:` blocks constrain MCP tools.

## 3. Drift found during this research (fix alongside adoption)

1. `docs/docs-playbook/gromozeka-workflow-brief.md:23-24` says the server is "Registered in `.opencode/opencode.json`" — it is actually in **global** `~/.config/opencode/opencode.jsonc:41-46`; the project `opencode.json` has no `mcp` block.
2. Both playbooks state section cap **5000** / disk cap **50000** characters — this repo's owner-ratified config overrides them to **8192 / 65536** (`.markdown-mcp.toml:24-27`).
3. `docs/llm/index.md:422` "Last updated: 2026-07-18" — predates the 2026-09-06 docs rewrite it now coexists with.

## 4. What does NOT need to change

- **All runtime gates**: `make test`, `make format lint`, `make check-docs` — unchanged, still mandatory.
- **`run-quality-gates` skill** — no doc-workflow content (verified).
- **`docs/llm/testing.md`** — no doc-workflow prescriptions (verified).
- **`docs/README.md`** — already markdown-mcp-aware (exclusions + playbook links).
- **Both `docs/docs-playbook/` playbooks** — already the canonical workflow (modulo the drift fixes above); adoption points other surfaces at them rather than rewriting them.
- **Root `README.md`, `TODO.md`** — no agent doc-workflow instructions (verified).
- **`docs/llm/changelog.md` process** — `CHANGELOG.md` stays outside MCP reach by design; process unchanged.
- **MCP tool registration** — global config + proven subagent inheritance; no per-agent wiring needed for *availability*.
- **CI pipeline** — intentionally index-free; at most an optional `lint-docs` target later.

## 5. Caveats

- opencode's permission semantics for MCP tools (whether `permission:` blocks can name `markdown-mcp_doc_*`) could not be verified from repo files — it is the load-bearing unknown behind the §1.4 governance risks and §2.3(5). Verify with a sandboxed probe before flipping any write-path defaults.
- Slug examples in proposed changes were deliberately avoided (slugs rot; derive via `doc_outline` at use time).
- Line numbers for `docs/llm/reviewing-large-changes.md` were taken from grep hits; treat those refs as approximate anchors for the quoted phrases.
