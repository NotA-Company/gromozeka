---
name: update-project-docs
description: >
  Guides the agent through updating all relevant Gromozeka project documentation
  after making code changes. Use this skill after implementing a feature, fixing
  a bug, refactoring, adding a handler/service/library, changing database schema,
  or modifying configuration. Provides a decision matrix mapping change types to
  specific doc sections. Triggers: update docs, sync documentation, documentation
  update, doc maintenance, post-implementation docs.
---

# Update Gromozeka Project Documentation

## When to use

- After any non-cosmetic code change — feature, refactor, bug fix affecting behavior, schema change, config change, new library, new handler.
- After discovering a new gotcha or invariant worth recording.
- When explicitly asked to "sync docs" or "update the docs".

## When NOT to use

- Purely cosmetic edits (whitespace, comment typos, formatting-only).
- Read-only exploration with no code changes.
- You haven't made the change yet — use `read-project-docs` first.

## Inputs

- List of files changed and classification of the change. If unsure, run `git status` / `git diff` (or review your tool history) before starting.

## Step 1 — Classify the change

A single change may match multiple rows. Apply all that match.

| Change type | Example |
|---|---|
| New handler | New file under `internal/bot/common/handlers/` |
| New service | New singleton under `internal/services/` |
| Schema change | New migration in `internal/database/migrations/versions/` or altered DDL |
| Config change | New TOML key, new `ConfigManager` getter, new `configs/00-defaults/*` entry |
| New library | New subdir under `lib/` or `lib/ext_modules/` |
| New LLM provider | New file under `lib/ai/providers/` |
| New chat setting | New `ChatSettingsKey` enum value |
| New script | New file under `scripts/` |
| Architecture shift | Changed dependency direction, new ADR, changed invariant |
| New hard rule | Newly enforced convention all agents must follow |
| New gotcha / anti-pattern | Newly discovered task-specific pitfall |
| Refactor | Renamed/moved files or symbols — path references in docs may be stale |
| New test pattern | New fixture, new marker, new golden-data convention |

## Step 2 — Update `docs/llm/` (the LLM-agent canon)

| If you changed… | Update |
|---|---|
| New handler | [`docs/llm/handlers.md`](../../../docs/llm/handlers.md). `docs/llm/index.md` §4.5 lists handlers as an aggregate row — update it only if the aggregate summary is now misleading (e.g. handler count, or calling out a new flagship handler). |
| New service | [`docs/llm/services.md`](../../../docs/llm/services.md) and [`docs/llm/index.md`](../../../docs/llm/index.md) §4.3 singleton table. |
| Schema change | [`docs/llm/database.md`](../../../docs/llm/database.md). If the change touches SQL portability rules, also consider [`docs/sql-portability-guide.md`](../../../docs/sql-portability-guide.md). |
| Config change | [`docs/llm/configuration.md`](../../../docs/llm/configuration.md). |
| New library | [`docs/llm/libraries.md`](../../../docs/llm/libraries.md) and [`docs/llm/index.md`](../../../docs/llm/index.md) §4.6. |
| New LLM provider | [`docs/llm/libraries.md`](../../../docs/llm/libraries.md) (AI subsection). |
| New chat setting | [`docs/llm/tasks.md`](../../../docs/llm/tasks.md) §4.1 if the example reference list there needs updating; verify defaults live in `configs/00-defaults/bot-defaults.toml`. |
| New script | [`docs/llm/tasks.md`](../../../docs/llm/tasks.md) if it supports a documented workflow (e.g. `scripts/check_structured_output.py` is referenced from §4.5). |
| Architecture shift | [`docs/llm/architecture.md`](../../../docs/llm/architecture.md). Add or amend an ADR if the decision is load-bearing. |
| New test pattern | [`docs/llm/testing.md`](../../../docs/llm/testing.md). |
| New gotcha / anti-pattern | [`docs/llm/tasks.md`](../../../docs/llm/tasks.md) — §2 for anti-patterns, §3 for gotchas table, §4 for lessons-learned narratives. |
| Refactor | Search all `docs/llm/*.md` for old paths/symbol names. |

### How to add entries

- **New handler** row to `handlers.md`: describe what messages it handles, what commands it owns, parallelism, any conditional registration predicate.
- **New service** entry in `services.md`: location, `getInstance()` call, key public methods (with signatures), initialization side effects, thread-safety notes.
- **New library** row in `libraries.md` §overview table: path, one-line purpose.

Do **not** write `self.services.<name>` — that attribute does not exist. Handlers access services via direct attributes set in [`BaseBotHandler.__init__`](../../../internal/bot/common/handlers/base.py) (`self.db`, `self.cache`, `self.queueService`, `self.storage`, `self.llmService`, `self.configManager`), all populated via `Service.getInstance()`. For `LLMManager`, access it via `self.llmService.getLLMManager()` — it is not a direct attribute.

## Step 3 — Update root `AGENTS.md` when hard rules or load-bearing gotchas change

Root [`AGENTS.md`](../../../AGENTS.md) is the compact, authoritative agent guide. Update it when:

- A new **hard rule** applies project-wide (naming, forbidden library, new portability constraint, new ordering invariant).
- A new **load-bearing gotcha** rises to the level of "would bite every agent that doesn't know it."

Do **not** put narrow task-specific lessons in `AGENTS.md` — those go in `docs/llm/tasks.md` §4.

If you add a new skill under `.agents/skills/`, also add it to the "available skills" / references list at the bottom of `AGENTS.md` so humans reading it see the surface area.

## Step 4 — Update schema docs (always in pairs when schema changes)

Schema changes must update **all three** of:

- [`docs/database-schema.md`](../../../docs/database-schema.md) (human-oriented)
- [`docs/database-schema-llm.md`](../../../docs/database-schema-llm.md) (LLM-oriented)
- [`docs/llm/database.md`](../../../docs/llm/database.md) (migration pattern + current version list)

These three files go stale together; leaving any of them behind creates contradictory sources of truth.

## Step 5 — Update inline READMEs (scan, don't trust hardcoded lists)

Library/service READMEs drift over time. Instead of trusting a hardcoded list, scan:

```
glob lib/**/README.md
glob internal/**/README.md
glob lib/ext_modules/*/README.md
```

Open any that describe files, APIs, or behavior you touched and update them. Common candidates: `lib/cache/`, `lib/rate_limiter/`, `lib/openweathermap/`, `lib/geocode_maps/`, `lib/markdown/test/`, `internal/services/storage/`, `internal/database/migrations/`.

## Step 6 — Update the human developer guide (only if it covers your change)

[`docs/developer-guide.md`](../../../docs/developer-guide.md) is human-oriented and partially redundant with `docs/llm/`. Find relevant sections **by heading**, not section number (numbers rot). Update when your change invalidates an example or description there.

## Step 7 — Secrets discipline

If your change introduces a new credentialed integration (new API key, new provider token):

- Default the key in `configs/00-defaults/*.toml` with a `${VAR}` substitution reference, never a literal value.
- Reference the env var by name in docs; **never paste the secret, never commit `.env*`, never echo secrets in logs or reports.**
- If you added a new `.env*` key, document the key name (not the value) in the relevant config doc.

## Step 8 — Verification

Before declaring docs complete:

- [ ] All file paths referenced in updated docs exist.
- [ ] All code examples in updated docs reflect current signatures and behavior.
- [ ] Naming conventions in examples are correct (camelCase for variables/functions/methods, PascalCase for classes, UPPER_CASE for constants).
- [ ] Line-number references (if any) match current files — these rot fast; prefer heading-based references when possible.
- [ ] Schema changes updated all three schema docs.
- [ ] New hard rules or load-bearing gotchas reflected in `AGENTS.md`.
- [ ] `.agents/skills/` index updated if you added a skill.
- [ ] `make format lint && make test` still green — this catches code examples that drifted.

If any step fails, fix it before closing the task. Stale docs are worse than verbose docs.

## Quick reference matrix

| Change | `docs/llm/` | Schema docs | `AGENTS.md` | Dev guide | READMEs |
|---|---|---|---|---|---|
| New handler | `handlers.md` (+ maybe `index.md` §4.5) | — | If new ordering invariant | If section covers handlers | Rare |
| New service | `services.md`, `index.md` §4.3 | — | If new singleton discipline | If section covers services | If service has README |
| Schema change | `database.md` (+ maybe `sql-portability-guide.md`) | All three | If new portability rule | If section covers DB | `internal/database/migrations/README.md` |
| Config change | `configuration.md` | — | If new secrets rule | If section covers config | — |
| New library | `libraries.md`, `index.md` §4.6 | — | — | If section covers libs | Library's own README |
| New LLM provider | `libraries.md` | — | — | — | — |
| New chat setting | `tasks.md` §4.1 only if the example list is now stale | — | — | — | — |
| Architecture shift | `architecture.md` | — | If invariant changes | Possibly | — |
| New gotcha | `tasks.md` (§2/§3/§4) | — | Only if load-bearing | — | — |
| New hard rule | Relevant `docs/llm/*.md` | — | Yes | Yes, if covered | — |
| Refactor | Search all `docs/llm/*.md` for old paths | If schema paths moved | If anything it references moved | Same | Same |
| New skill | — | — | Update "available skills" / references list | — | — |

## Reminders

- Code wins on conflict. If you find doc drift unrelated to your change, flag it (or fix it) — don't propagate it.
- When in doubt whether a doc needs updating, update it.
- Use `git diff` to be sure what you actually changed before picking rows from the matrix.
