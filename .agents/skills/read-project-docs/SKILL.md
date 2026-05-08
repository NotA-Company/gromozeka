---
name: read-project-docs
description: >
  Instructs the agent to read Gromozeka project documentation and build context
  before making non-trivial changes or answering non-trivial questions. Use this
  skill when onboarding to the project, starting a new task, or when the agent
  needs to understand project architecture, conventions, patterns, and current
  state. Triggers: read docs, understand project, build context, onboarding,
  project overview, learn codebase, project structure, how does this work, what
  patterns, get familiar.
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

### Step 1 — Hard rules: root `AGENTS.md`

**Read:** [`AGENTS.md`](../../../AGENTS.md) at the repo root.

This is the compact agent guide. It is authoritative for: naming conventions, no-pydantic rule, docstring/type-hint requirements, SQL portability rules (the single highest-risk area in this repo), handler ordering, run commands (`./venv/bin/python3`, `make format lint`, `make test`), and known gotchas.

Do not skip this. Everything downstream assumes you've seen it.

### Step 2 — LLM index: `docs/llm/index.md`

**Read:** [`docs/llm/index.md`](../../../docs/llm/index.md).

Gives you the project map (directories, key files with line counts), singleton access table, entry points, and a navigation matrix pointing to focused docs.

### Step 3 — Task-relevant focused docs (selective)

`docs/llm/` contains 9 focused docs. **Read only those that match your task** — do not read them all.

| Your task involves… | Read |
|---|---|
| Creating/modifying a handler or bot command | [`docs/llm/handlers.md`](../../../docs/llm/handlers.md) |
| Database schema, migrations, queries | [`docs/llm/database.md`](../../../docs/llm/database.md) **and** [`docs/sql-portability-guide.md`](../../../docs/sql-portability-guide.md) |
| Schema documentation updates | [`docs/database-schema.md`](../../../docs/database-schema.md) **and** [`docs/database-schema-llm.md`](../../../docs/database-schema-llm.md) (dual docs, keep in sync) |
| Singleton services (Cache/Queue/LLM/Storage/RateLimiter) | [`docs/llm/services.md`](../../../docs/llm/services.md) |
| `lib/` libraries, LLM providers, Max client, markdown, bayes, etc. | [`docs/llm/libraries.md`](../../../docs/llm/libraries.md) |
| TOML configuration, `ConfigManager`, `.env*` | [`docs/llm/configuration.md`](../../../docs/llm/configuration.md) |
| Writing or modifying tests | [`docs/llm/testing.md`](../../../docs/llm/testing.md) |
| Architectural decisions, ADRs, component dependencies | [`docs/llm/architecture.md`](../../../docs/llm/architecture.md) |
| Step-by-step task recipes, anti-patterns, gotchas | [`docs/llm/tasks.md`](../../../docs/llm/tasks.md) |

Multiple rows may apply (e.g. handler + DB → both `handlers.md` and `database.md` + `sql-portability-guide.md`).

### Step 4 — Human-oriented guide (optional)

[`docs/developer-guide.md`](../../../docs/developer-guide.md) is human-oriented and partially redundant with the LLM docs. Consult only when the LLM docs leave a gap you can't close otherwise. Do not trust hardcoded section numbers — find content by heading.

## Rules of engagement

- **Code wins on conflict.** If docs contradict the source, the source is authoritative; flag the drift in your response so docs can be corrected later.
- **Be selective.** Reading all nine `docs/llm/*.md` wastes context. The navigation matrix above is the budget.
- **`lib/ext_modules/*`** subpackages (e.g. `grabliarium`) have their own `pyproject.toml` and are formatted separately by `make format`. If you're editing there, note it.

## Verification

Before acting on the task, you should be able to state — in task-specific terms — the answers to:

1. Which hard rules from `AGENTS.md` constrain this change (naming, no-pydantic, SQL portability, handler ordering, secrets)?
2. Which file(s) you'll touch, by concrete path.
3. Which docs will need updating after the change (if any). If the change is structural, load the `update-project-docs` skill afterward.
4. Which command(s) you'll run to verify the change (`make format lint`, `make test`, targeted pytest).

If any answer is fuzzy, re-read the relevant doc from Steps 1–3.
