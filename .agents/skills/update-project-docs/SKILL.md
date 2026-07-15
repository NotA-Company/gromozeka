---
name: update-project-docs
description: >
  Guides the agent through updating all relevant Gromozeka project documentation
  after making code changes. Use this skill after implementing a feature, fixing
  a bug, refactoring, adding a handler/service/library, changing database schema,
  or modifying configuration, including durable memory files when needed.
  Provides a decision matrix mapping change types to specific doc sections.
  Triggers: update docs, sync documentation, documentation update, doc
  maintenance, post-implementation docs, teamlead memory, task memory.
---

# Update Gromozeka Project Documentation

## When to use

- After any non-cosmetic code change — feature, refactor, bug fix affecting behavior, schema change, config change, new library, new handler.
- After discovering a new gotcha, invariant, or durable memory worth recording.
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
| New repo-wide durable memory | Reusable discovery that should stay in cross-task memory |
| New subsystem-specific durable memory | Reusable discovery that belongs to one completed subsystem/feature |
| Refactor | Renamed/moved files or symbols — path references in docs may be stale |
| New test pattern | New fixture, new marker, new golden-data convention |
| User-visible change | New feature / capability / config field / command / public API; behavior change; schema/data migration; user-facing bug fix |

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
| New repo-wide durable memory | [`docs/llm/teamlead-memory.md`](../../../docs/llm/teamlead-memory.md). Keep it compact; only store cross-task facts or workflow lessons. |
| New subsystem-specific durable memory | Relevant file under [`docs/llm/memories/`](../../../docs/llm/memories/) **and** [`docs/llm/memories/index.md`](../../../docs/llm/memories/index.md). If you create a new memory file or change discovery flow, also update [`docs/llm/index.md`](../../../docs/llm/index.md) and the pointers in [`docs/llm/teamlead-memory.md`](../../../docs/llm/teamlead-memory.md). |
| Refactor | Search all `docs/llm/**/*.md` (include `docs/llm/memories/`) for old paths/symbol names. |

### How to add entries

- **New handler** row to `handlers.md`: describe what messages it handles, what commands it owns, parallelism, any conditional registration predicate.
- **New service** entry in `services.md`: location, `getInstance()` call, key public methods (with signatures), initialization side effects, thread-safety notes.
- **New library** row in `libraries.md` §overview table: path, one-line purpose.

### Memory routing rules

- Put **canonical behavior, invariants, workflows, and user-facing guidance** in the focused docs such as `handlers.md`, `database.md`, `configuration.md`, `testing.md`, and `tasks.md`.
- Put **cross-task operational memory** in [`docs/llm/teamlead-memory.md`](../../../docs/llm/teamlead-memory.md) when it is reusable across many tasks but too narrow or informal for the canon.
- Put **subsystem- or completed-feature-specific memory** in `docs/llm/memories/<topic>.md` when it would clutter `teamlead-memory.md`; keep [`docs/llm/memories/index.md`](../../../docs/llm/memories/index.md) updated so agents can discover it.
- Keep memory docs lean. If a fact graduates into a real project invariant, move it into the canonical docs and/or `AGENTS.md` instead of only leaving it in memory.
- If memory docs contradict the code or canonical docs, fix or delete the stale memory — do not preserve drift.

Do **not** write `self.services.<name>` — that attribute does not exist. Handlers access services via direct attributes set in [`BaseBotHandler.__init__`](../../../internal/bot/common/handlers/base.py) (`self.db`, `self.cache`, `self.queueService`, `self.storage`, `self.llmService`, `self.configManager`), all populated via `Service.getInstance()`. For `LLMManager`, access it via `self.llmService.getLLMManager()` — it is not a direct attribute.

## Step 3 — Update root `AGENTS.md` when hard rules or load-bearing gotchas change

Root [`AGENTS.md`](../../../AGENTS.md) is the compact, authoritative agent guide. Update it when:

- A new **hard rule** applies project-wide (naming, forbidden library, new portability constraint, new ordering invariant).
- A new **load-bearing gotcha** rises to the level of "would bite every agent that doesn't know it."

Do **not** put narrow task-specific lessons in `AGENTS.md` — those go in `docs/llm/tasks.md` when they are canonical task guidance, or in `docs/llm/memories/` when they are archived subsystem memory.

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

## Step 6 — Update `CHANGELOG.md` and root `README.md` for user-visible changes

User-facing docs at the repo root go stale quietly. After a code change, ask: would a **user or operator** (not just an agent reading `docs/llm/`) notice this change? If yes, add a `CHANGELOG.md` entry (mandatory) and run the root `README.md` staleness check below.

### `CHANGELOG.md` (mandatory for user-visible changes)

[`CHANGELOG.md`](../../../CHANGELOG.md) is the user-facing changelog, formatted per [Keep a Changelog](https://keepachangelog.com/). The **authoritative process and format spec is [`docs/llm/changelog.md`](../../../docs/llm/changelog.md)** — read it whenever you are unsure whether, where, or how to add an entry.

Add a one-line entry under `## [Unreleased]` in the matching subsection:

- `### Added` — new feature, capability, command, config field, public API, or new schema/migration that users will see.
- `### Changed` — behavior change, renamed config key, schema/data migration altering existing semantics.
- `### Fixed` — user-facing bug fix.

Each entry: declarative and past tense per [`docs/llm/changelog.md`](../../../docs/llm/changelog.md) §Entry Style — describe the new state (e.g. "X now does Y"), never imperative. Do **not** start the line with "Added"/"Fixed"/"Changed" since the `### Added` / `### Fixed` / `### Changed` category header already conveys that. Keep entries one line and concrete (name the migration / config key / command so users can grep for it). Match the entry style documented in [`docs/llm/changelog.md`](../../../docs/llm/changelog.md).

**When NOT to update `CHANGELOG.md`** (per `docs/llm/changelog.md`):

- Style / formatting fixes, whitespace, comment typos.
- Internal refactors with no user-visible effect (renames inside `internal/`, dead-code removal, perf tweaks invisible to users).
- Doc-only changes — **unless** the change documents a brand-new user-facing feature.
- Test-only changes.
- Dependency pin bumps with no behavior change.

### Root `README.md` (staleness check — not mandatory on every change)

[`README.md`](../../../README.md) is user docs. Run a **staleness check**: if your change alters user-facing capabilities, commands, or configuration that `README.md` actually documents, update `README.md` so it does not go stale. If `README.md` does not mention the touched area, no update is needed. This is distinct from Step 5, which scans inline `lib/**/README.md` and `internal/**/README.md` — Step 6 concerns only the **repo-root** `README.md`. When in doubt, leave it alone rather than churn it.

## Step 7 — Update the human developer guide (only if it covers your change)

[`docs/developer-guide.md`](../../../docs/developer-guide.md) is human-oriented and partially redundant with `docs/llm/`. Find relevant sections **by heading**, not section number (numbers rot). Update when your change invalidates an example or description there.

## Step 8 — Secrets discipline

If your change introduces a new credentialed integration (new API key, new provider token):

- Default the key in `configs/00-defaults/*.toml` with a `${VAR}` substitution reference, never a literal value.
- Reference the env var by name in docs; **never paste the secret, never commit `.env*`, never echo secrets in logs or reports.**
- If you added a new `.env*` key, document the key name (not the value) in the relevant config doc.

## Step 9 — Verification

Before declaring docs complete:

- [ ] All file paths referenced in updated docs exist.
- [ ] All code examples in updated docs reflect current signatures and behavior.
- [ ] Naming conventions in examples are correct (camelCase for variables/functions/methods, PascalCase for classes, UPPER_CASE for constants).
- [ ] Line-number references (if any) match current files — these rot fast; prefer heading-based references when possible.
- [ ] Schema changes updated all three schema docs.
- [ ] Relevant memory surfaces were considered: `docs/llm/teamlead-memory.md` for cross-task facts, `docs/llm/memories/` for subsystem-specific memory.
- [ ] If you added a new file under `docs/llm/memories/`, both `docs/llm/memories/index.md` and `docs/llm/index.md` were updated.
- [ ] New hard rules or load-bearing gotchas reflected in `AGENTS.md`.
- [ ] `.agents/skills/` index updated if you added a skill.
- [ ] **User-visible change** → `CHANGELOG.md` entry added under the correct `## [Unreleased]` subsection (`### Added` / `### Changed` / `### Fixed`), per `docs/llm/changelog.md`. Internal-only changes correctly skipped.
- [ ] **Root `README.md` staleness check** run; updated only if user-facing capabilities/commands/config it documents actually changed.
- [ ] `make format lint && make test` still green — this catches code examples that drifted.

> **Note:** If you are `docs-writer` (or another agent restricted from running `make format`/`make test`), substitute `make lint && make check-docs` as your verification gate. The full `make format lint && make test` remains the canonical gate for agents that can run it (`software-developer`, `debugger`, etc.).
- [ ] `make check-docs` run; no broken markdown links (read-only; exit 1 if any local link is broken).

If any step fails, fix it before closing the task. Stale docs are worse than verbose docs.

## Quick reference matrix

Columns `READMEs` and `CHANGELOG.md` and root `README.md` overlap in spirit but differ in scope: `READMEs` here means inline `lib/**/README.md` / `internal/**/README.md` (Step 5); `CHANGELOG.md` and root `README.md` are the Step 6 user-facing surfaces. `CHANGELOG.md` is **only** for user-visible changes — write "If user-visible" when the change could be invisible (internal).

| Change | `docs/llm/` | Schema docs | `AGENTS.md` | Dev guide | READMEs (inline) | `CHANGELOG.md` |
|---|---|---|---|---|---|---|
| New handler | `handlers.md` (+ maybe `index.md` §4.5) | — | If new ordering invariant | If section covers handlers | Rare | If user-facing command/feature |
| New service | `services.md`, `index.md` §4.3 | — | If new singleton discipline | If section covers services | If service has README | If user-facing capability |
| Schema change | `database.md` (+ maybe `sql-portability-guide.md`) | All three | If new portability rule | If section covers DB | `internal/database/migrations/README.md` | Yes (name the migration) |
| Config change | `configuration.md` | — | If new secrets rule | If section covers config | — | If new user-facing config field |
| New library | `libraries.md`, `index.md` §4.6 | — | — | If section covers libs | Library's own README | If user-facing capability |
| New LLM provider | `libraries.md` | — | — | — | — | If user-facing |
| New chat setting | `tasks.md` §4.1 only if the example list is now stale | — | — | — | — | Yes (new setting) |
| Architecture shift | `architecture.md` | — | If invariant changes | Possibly | — | If user-visible behavior change |
| New gotcha | `tasks.md` (§2/§3/§4) | — | Only if load-bearing | — | — | No |
| New repo-wide durable memory | `teamlead-memory.md` | — | Only if it becomes a hard rule | — | — | No |
| New subsystem-specific durable memory | `docs/llm/memories/<topic>.md`, `docs/llm/memories/index.md`, maybe `index.md` | — | No | — | — | No |
| New hard rule | Relevant `docs/llm/*.md` | — | Yes | Yes, if covered | — | Usually no (unless it changes user-facing behavior) |
| Refactor | Search all `docs/llm/**/*.md` for old paths | If schema paths moved | If anything it references moved | Same | Same | If user-visible (e.g. renamed command/config) |
| New skill | — | — | Update "available skills" / references list | — | — | No |

For the **repo-root `README.md`** there is no matrix column — apply the Step 6 staleness check to it independently (only when user-facing capabilities/commands/config it documents change).

## Reminders

- Code wins on conflict. If you find doc drift unrelated to your change, flag it (or fix it) — don't propagate it.
- When in doubt whether a doc needs updating, update it.
- Use `git diff` to be sure what you actually changed before picking rows from the matrix.
