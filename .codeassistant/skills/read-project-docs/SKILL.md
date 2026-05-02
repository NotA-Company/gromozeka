---
name: read-project-docs
description: >
  Instructs the agent to read Gromozeka project documentation and build context
  before making any changes. Use this skill when onboarding to the project,
  starting a new task, or when the agent needs to understand project architecture,
  conventions, patterns, and current state. Triggers: read docs, understand project,
  build context, onboarding, project overview, learn codebase, project structure,
  how does this work, what patterns, get familiar.
---

# Read Gromozeka Project Documentation

## When to use

- Before making any changes to the Gromozeka codebase for the first time in a session
- When you need to understand project architecture, conventions, or patterns
- When starting a new task and you lack project context
- When explicitly asked to "read the docs" or "understand the project"

## Inputs required

- None — this skill only reads documentation files

## When NOT to use

- You have already read the documentation in this session and have full context
- The task is trivial and self-contained (e.g., fixing a typo in a comment)
- You are asked to do something unrelated to the Gromozeka codebase

## Workflow

### Step 1 — Read the LLM Index (REQUIRED, do this FIRST)

**Read:** `docs/llm/index.md`

This is the entry point to all project documentation, dood. It gives you:
- Project identity and mandatory rules
- Project map (every directory and key file with purpose)
- **Navigation decision matrix** — tells you exactly which other `docs/llm/` files to read based on your task

Do NOT skip this file. Everything else flows from it.

### Step 2 — Read Task-Relevant LLM Docs (REQUIRED)

Based on your task, read **only** the relevant focused docs from `docs/llm/`. Do NOT read all of them — be selective, dood!

| If your task involves… | Read this file |
|---|---|
| Working on handlers | `docs/llm/handlers.md` |
| Working on database / migrations | `docs/llm/database.md` |
| Working on services | `docs/llm/services.md` |
| Working on libraries | `docs/llm/libraries.md` |
| Working on configuration | `docs/llm/configuration.md` |
| Writing or modifying tests | `docs/llm/testing.md` |
| Understanding architecture / ADRs | `docs/llm/architecture.md` |
| Need task guidance / decision trees | `docs/llm/tasks.md` |

Multiple files may apply. For example, adding a new handler with database access would need both `handlers.md` and `database.md`.

### Step 3 — Read Developer Guide (OPTIONAL)

Only if deeper understanding is needed beyond what the LLM docs provide.

**Read:** `docs/developer-guide.md`

Contains detailed coverage of:
- Project overview and architecture overview with diagrams
- Detailed directory structure
- Configuration system details
- Database layer deep dive
- Handler system explanation
- Service layer documentation
- Libraries reference
- Testing guide
- Code quality standards
- Deployment instructions
- Common development task walkthroughs

## Important: Selective Reading

The `docs/llm/` directory contains 9 focused documents. **Do NOT read all of them**, dood! The index file (Step 1) contains a navigation matrix that tells you which files are relevant to your task. Read only what you need — this saves context and keeps you focused.

## Verification

After completing Steps 1–3, you should be able to answer all of the following:

1. **Naming conventions** — What casing is used for variables/functions vs classes vs constants?
2. **Design patterns** — What architectural patterns does Gromozeka use (e.g., handler registration, service layer, config hierarchy)?
3. **Handler structure** — How are handlers created, registered, and organized?
4. **Available services** — What services exist and how are they accessed?
5. **Architecture decisions** — What key ADRs or design choices shape the codebase?

If you cannot answer any of these, re-read the relevant file from Steps 1–3, dood!
