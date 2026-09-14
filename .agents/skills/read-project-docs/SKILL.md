---
name: read-project-docs
description: >
  Instructs the agent to read Gromozeka project documentation and build context
  before making non-trivial changes or answering non-trivial questions. Use this
  skill when onboarding to the project, starting a new task, or when the agent
  needs to understand project architecture, conventions, patterns, and current
  state, including durable memory files under `docs/llm/`. Triggers: read docs,
  understand project, build context, onboarding, project overview, learn
  codebase, project structure, how does this work, what patterns, get familiar,
  teamlead memory, task memory.
---

# Read Gromozeka Project Documentation

## When to use

- First non-trivial action in a new session on this repo.
- Before designing or implementing a feature, refactor, migration, or integration.
- When answering architectural or "how does X work" questions that require grounded references.

## When NOT to use

- You already read the relevant docs in this session and retained the context.
- The task is a trivial, self-contained edit (typo fix, comment tweak, one-line rename with no semantic impact).
- The work is unrelated to this repo.

## Inputs

None — this skill only reads documentation.

## Read order (strict)

The repo enforces a specific order of authority. Follow it.

**Mechanism (conditional preference, never exclusive):** when the markdown-mcp MCP tools (`doc_list`, `doc_search`, `doc_outline`, `doc_read`) are available, prefer them for everything under `./docs`, using docs-root-relative paths (e.g. `doc_read(file_path="llm/index.md", section_slug=…)`). Resolve `section_slug` values from `doc_outline` at use time — never hard-code them. When the MCP server is not available, plain `read` on the linked relative paths is an exact substitute; every step below remains satisfiable without MCP. Files outside `./docs` (root `AGENTS.md`, `.agents/**`, `.opencode/**`, repo-root markdown) are always accessed with the normal `read` tool.

### Step 1 — Hard rules: root `AGENTS.md`

**Read:** [`AGENTS.md`](../../../AGENTS.md) at the repo root.

Manual `read` only — `AGENTS.md` sits at the repo root, outside the markdown-mcp docs root, so no `doc_*` tool reaches it.

This is the compact agent guide. It is authoritative for: naming conventions, no-pydantic rule, docstring/type-hint requirements, SQL portability rules (the single highest-risk area in this repo), handler ordering, run commands (`./venv/bin/python3`, `make format lint`, `make test`), and known gotchas.

Do not skip this. Everything downstream assumes you've seen it.

### Step 2 — LLM index: `docs/llm/index.md`

**Read:** [`docs/llm/index.md`](../../../docs/llm/index.md) (docs-root-relative MCP path: `llm/index.md`).

With MCP: `doc_outline("llm/index.md")` first, then targeted `doc_read(file_path="llm/index.md", section_slug=…)` of the navigation matrix and §3 (Mandatory Rules) — pick the slugs from the returned outline. A full disk `read` of the file is the fallback.

Gives you the project map (directories, key files with line counts), singleton access table, entry points, and a navigation matrix pointing to focused docs and memory companions.

### Step 3 — Durable memory companions

Read the lightweight memory surfaces that capture reusable discoveries from prior work:

- [`docs/llm/teamlead-memory.md`](../../../docs/llm/teamlead-memory.md) — cross-task memory, repo gotchas, workflow lessons. It is large (265+ lines), so with MCP the win is `doc_outline("llm/teamlead-memory.md")` + targeted section reads of only what applies, not a full read.
- [`docs/llm/memories/index.md`](../../../docs/llm/memories/index.md) — index of archived task/subsystem-specific memories.

With MCP, discovery goes through the index instead of the directory walk: `doc_search(query, file_glob="llm/memories/*.md")` finds the relevant archived memories directly, and `doc_list(file_glob="llm/memories/*.md")` enumerates what exists. Without MCP, browse `memories/index.md` manually.

Then read only the specific memory file(s) (or sections, via `doc_read(section_slug=…)`) relevant to your task. Example: if you are touching `lib/sandbox/`, sandbox config, or sandbox bot integration, also read [`docs/llm/memories/sandbox.md`](../../../docs/llm/memories/sandbox.md).

Important: memory docs are **companions**, not the primary canon. Their authority is lower than `AGENTS.md`, the focused `docs/llm/*.md` references, and the code itself.

### Step 4 — Task-relevant focused docs (selective)

`docs/llm/` contains canonical focused docs plus memory companions. **Read only the focused docs that match your task** — do not read them all. With MCP, every "Read" below means `doc_outline("llm/<doc>.md")` + targeted `doc_read(section_slug=…)` rather than a whole-file read; if you instead need to find *which* doc covers X, `doc_search(query, category=…)` answers it directly (run `doc_categories()` first to see the indexed category values).

| Your task involves… | Read (MCP: `doc_outline` + targeted `doc_read`; manual: `read`) |
|---|---|
| Cross-task durable gotchas / prior agent discoveries | [`docs/llm/teamlead-memory.md`](../../../docs/llm/teamlead-memory.md) |
| Archived subsystem/task-specific history | [`docs/llm/memories/index.md`](../../../docs/llm/memories/index.md) and the relevant file under `docs/llm/memories/` |
| Creating/modifying a handler or bot command | [`docs/llm/handlers.md`](../../../docs/llm/handlers.md) |
| Database schema, migrations, queries | [`docs/llm/database.md`](../../../docs/llm/database.md) **and** [`docs/sql-portability-guide.md`](../../../docs/sql-portability-guide.md) |
| Schema documentation updates | [`docs/database-schema.md`](../../../docs/database-schema.md) **and** [`docs/database-schema-llm.md`](../../../docs/database-schema-llm.md) (dual docs, keep in sync) |
| Singleton services (Cache/Queue/LLM/Storage/RateLimiter) | [`docs/llm/services.md`](../../../docs/llm/services.md) |
| `lib/` libraries, LLM providers, Max client, markdown, bayes, etc. | [`docs/llm/libraries.md`](../../../docs/llm/libraries.md) |
| Sandbox library / runtime / Docker-backed code execution | [`docs/llm/sandbox.md`](../../../docs/llm/sandbox.md) **and** [`docs/llm/memories/sandbox.md`](../../../docs/llm/memories/sandbox.md) |
| TOML configuration, `ConfigManager`, `.env*` | [`docs/llm/configuration.md`](../../../docs/llm/configuration.md) |
| Writing or modifying tests | [`docs/llm/testing.md`](../../../docs/llm/testing.md) |
| Architectural decisions, ADRs, component dependencies | [`docs/llm/architecture.md`](../../../docs/llm/architecture.md) |
| Step-by-step task recipes, anti-patterns, gotchas | [`docs/llm/tasks.md`](../../../docs/llm/tasks.md) |

Multiple rows may apply (e.g. handler + DB → both `handlers.md` and `database.md` + `sql-portability-guide.md`).

### Step 5 — Human-oriented guide (optional)

[`docs/developer-guide.md`](../../../docs/developer-guide.md) is human-oriented and partially redundant with the LLM docs. Consult only when the LLM docs leave a gap you can't close otherwise. Do not trust hardcoded section numbers — find content by heading. With MCP that advice maps directly to `doc_outline("developer-guide.md")` — the outline is the heading index; then `doc_read` the section you need.

## Rules of engagement

- **Code wins on conflict.** If docs contradict the source, the source is authoritative; flag the drift in your response so docs can be corrected later.
- **Canonical docs outrank memory docs.** Treat `teamlead-memory.md` and `docs/llm/memories/*.md` as reusable hints and historical context, not as stronger authority than the focused docs or the code.
- **Be selective.** Blanket-reading all `docs/llm/**/*.md` wastes context. Use the navigation matrix above and read only the relevant focused docs plus the memory file(s) that actually apply. With MCP, selectivity gets cheaper still: `doc_outline` + section-scoped `doc_read` (and `doc_search` when you know the question but not the doc) mean a whole-file read is rarely needed.
- **`lib/ext_modules/*`** subpackages (e.g. `grabliarium`) have their own `pyproject.toml` and are formatted separately by `make format`. If you're editing there, note it.

## Verification

Before acting on the task, you should be able to state — in task-specific terms — the answers to:

1. Which hard rules from `AGENTS.md` constrain this change (naming, no-pydantic, SQL portability, handler ordering, secrets)?
2. Which file(s) you'll touch, by concrete path.
3. Which memory file(s), if any, are relevant to this task (`teamlead-memory.md` and/or a file under `docs/llm/memories/`).
4. Which docs will need updating after the change (if any). If the change is structural, load the `update-project-docs` skill afterward.
5. Which command(s) you'll run to verify the change (`make format lint`, `make test`, targeted pytest).

If any answer is fuzzy, re-read the relevant material from Steps 1–4.
