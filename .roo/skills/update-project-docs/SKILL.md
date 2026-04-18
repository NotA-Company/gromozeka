---
name: update-project-docs
description: >
  Guides the agent through updating all relevant Gromozeka project documentation
  after making code changes. Use this skill after implementing a feature, fixing a bug,
  refactoring, adding a handler/service/library, changing database schema, or modifying
  configuration. Provides a decision matrix mapping change types to specific doc sections.
  Triggers: update docs, sync documentation, documentation update,
  doc maintenance, post-implementation docs.
---

# Update Gromozeka Project Documentation

## When to use

- After making **any** code changes to the Gromozeka codebase
- After adding, removing, or modifying handlers, services, libraries, or database schemas
- After changing configuration structure or adding new config keys
- After discovering new anti-patterns or introducing new architectural patterns
- When explicitly asked to "update the docs" or "sync documentation"

## When NOT to use

- You have not made any code changes yet (use `read-project-docs` instead, dood)
- The change is purely cosmetic (whitespace, comment typos) with zero structural impact
- You are only reading/exploring the codebase without modifications

## Inputs required

- Knowledge of **what files were changed** and **what type of change** was made
- If you don't know, review your recent actions or check `git diff` before proceeding

## Workflow

### Step 1 — Determine What Changed

Identify which files were modified/created/deleted and classify the change type:

| Change Type | Examples |
|---|---|
| **New handler** | Added a new handler class in `internal/bot/` |
| **New service** | Added or modified a service in `internal/services/` |
| **Database change** | New migration, schema change, new queries |
| **Config change** | New config keys, changed config structure |
| **New library** | Added a library under `lib/` |
| **New LLM provider** | Added a provider in `lib/ai/providers/` |
| **Architecture change** | Changed fundamental patterns or dependencies |
| **New anti-pattern** | Discovered a gotcha worth documenting |
| **Bug fix** | Fixed a bug (may affect examples/docs if they showed broken behavior) |
| **Refactoring** | Renamed, moved, or restructured existing code |
| **New feature** | End-user-visible functionality added |
| **New test patterns** | New fixtures, test utilities, or testing conventions |

A single change may match **multiple** types, dood. Apply all that match.

---

### Step 2 — Update LLM Documentation (REQUIRED for structural changes)

Use this decision matrix to determine which `docs/llm/` files to update:

| If you changed… | Update these files |
|---|---|
| **New handler** | `docs/llm/index.md` (project map), `docs/llm/handlers.md` |
| **New service** | `docs/llm/index.md` (project map), `docs/llm/services.md` |
| **Database change** | `docs/llm/database.md` |
| **Config change** | `docs/llm/configuration.md` |
| **New library** | `docs/llm/index.md` (project map), `docs/llm/libraries.md` |
| **New LLM provider** | `docs/llm/libraries.md` (AI subsection) |
| **Architecture change** | `docs/llm/architecture.md` |
| **New anti-pattern** | `docs/llm/tasks.md` |
| **New test patterns** | `docs/llm/testing.md` |
| **Refactoring** | All `docs/llm/` files referencing renamed/moved paths — search and replace old paths |

**Template — Adding a handler entry to project map in `docs/llm/index.md`:**

```markdown
| `internal/bot/<platform>/handlers/<name>.py` | <Brief description of what the handler does> |
```

**Template — Adding a service to `docs/llm/services.md`:**

```markdown
### <ServiceName>
- **Location**: `internal/services/<name>/`
- **Access**: `self.services.<name>` from handlers
- **Key methods**: `methodOne()`, `methodTwo()`
- **Notes**: <Any important usage notes>
```

---

### Step 3 — Update Developer Guide (REQUIRED for structural changes)

**File:** `docs/developer-guide.md`

| If you changed… | Update these sections |
|---|---|
| **New handler** | Section 6 (Handler System), Section 12 (Common Development Tasks) |
| **New service** | Section 7 (Service Layer) |
| **Database change** | Section 5 (Database Layer) |
| **Config change** | Section 4 (Configuration System) |
| **New library** | Section 8 (Libraries Reference) |
| **New test patterns** | Section 9 (Testing Guide) |

---

### Step 4 — Update Inline Documentation (if applicable)

Check whether any of these files need updating based on your changes:

**Library READMEs:**
- `lib/cache/README.md`
- `lib/rate_limiter/README.md`
- `lib/openweathermap/README.md`
- `lib/geocode_maps/README.md`
- `internal/services/storage/README.md`

**Database docs:**
- `docs/database-schema.md`
- `docs/database-schema-llm.md`
- `docs/database-README.md`

**Other docs in `docs/`** — scan for any references to files or APIs you changed.

---

### Step 5 — Verification Checklist

Before considering documentation complete, verify ALL of the following:

- [ ] All file references in docs use correct, current paths
- [ ] All code examples in docs are still accurate after your changes
- [ ] Naming conventions are followed (camelCase for variables/functions, PascalCase for classes, UPPER_CASE for constants)
- [ ] All new public classes, methods, and functions are documented in the relevant `docs/llm/` file
- [ ] No stale information remains in any updated docs
- [ ] Line numbers referenced in docs (if any) are still correct

If any check fails, fix it before declaring documentation complete, dood!

## Quick Reference — Full Decision Matrix

| Change Type | LLM Docs | Dev Guide | Inline Docs |
|---|---|---|---|
| New handler | ✅ `index.md`, `handlers.md` | ✅ Sec 6, 12 | If handler has README |
| New service | ✅ `index.md`, `services.md` | ✅ Sec 7 | If service has README |
| Database change | ✅ `database.md` | ✅ Sec 5 | ✅ DB docs |
| Config change | ✅ `configuration.md` | ✅ Sec 4 | — |
| New library | ✅ `index.md`, `libraries.md` | ✅ Sec 8 | ✅ Library README |
| New LLM provider | ✅ `libraries.md` | — | — |
| Architecture change | ✅ `architecture.md` | — | — |
| New anti-pattern | ✅ `tasks.md` | — | — |
| New test patterns | ✅ `testing.md` | ✅ Sec 9 | — |
| Bug fix | If docs showed broken behavior | — | If applicable |
| Refactoring | ✅ All path refs in `docs/llm/` | ✅ All path refs | ✅ All path refs |
| New feature | ✅ Relevant `docs/llm/` files | ✅ Relevant secs | If applicable |

## Important Reminders

- **Documentation updates are NOT optional**, dood! Every code change must be reflected in docs.
- When in doubt about whether a doc needs updating, **update it**. Stale docs are worse than verbose docs.
- Use `git diff` or review your changes if you're unsure what was modified.
