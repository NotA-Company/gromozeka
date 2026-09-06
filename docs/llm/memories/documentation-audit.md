---
category: reference
---

# Documentation Audit Lessons (2026-06-28)

Archived durable notes from [`../teamlead-memory.md`](../teamlead-memory.md) (extracted 2026-07-18; re-verified 2026-07-18 during the second docs audit, with inline as-of stamps on re-checked claims). See the live compact memory there for cross-cutting rules and workflow lessons.

- **Three index.md files** in the repo (as of 2026-07-18): `docs/llm/index.md` (main agent entry), `docs/llm/memories/index.md` (archived memory index), `docs/other/yc-ai-sdk/index.md` (YC SDK API reference, pinned to SDK v0.20.2). The first two must be kept in sync with the file tree; the YC SDK index is a version-pinned API reference that needs full revision on SDK upgrades, not tree-sync maintenance.
- **Highest-drift docs** (age fastest, most claims become stale): `database-README.md`, `database-schema.md`, `database-schema-llm.md`, `developer-guide.md`. These contain migration counts, repository lists, line numbers, method signatures, enum values, and table counts — all of which drift with every code change.
- **Medium-drift docs**: `docs/llm/architecture.md` (handler chain, ADR counts), `docs/llm/handlers.md` (handler list, registration order), `docs/llm/index.md` (line counts, test count, entry point lines).
- **Low-drift docs**: `docs/llm/memories/` files, `sql-portability-guide.md`, `docs/llm/sandbox.md`, `docs/llm/tasks.md` (gotchas/anti-patterns are stable), `docs/llm/testing.md`.
- **Common drift patterns across all docs**: (1) line number references rot within weeks, (2) counts (repository, migration, table, handler, test) always lag, (3) method names change in code but not in doc examples (e.g., `setUserData` → `addUserData`), (4) enum values grow but docs aren't updated, (5) DDL in docs can have phantom columns not in actual migrations.
- **database-README.md** is the worst offender — it's a 723-line (as of 2026-07-18; this count itself drifts) marketing-style doc full of hard counts, method signatures, and provider examples that are almost all stale. Consider whether it's worth maintaining at all vs. just linking to the more-focused schema docs.
- **developer-guide.md** is human-oriented and partially redundant with `docs/llm/`; its handler list and repository list are frequently out of date.
- **`docs/reports/`** directory doesn't exist (as of 2026-07-18). `database-README.md` previously linked to it; those links have since been removed (this specific instance is now fixed — 0 `docs/reports` references remain in that file). The general pattern — referencing files that were never created or were moved — still applies. Note: many files under `docs/archive/reports/` still self-reference the old `docs/reports/` paths in their own bodies, but that's expected for archived content and should not be rewritten.
- **`docs/TODO.md`** was extensively referenced by `documentation-review-process.md` but didn't exist. All references have been removed from that document (2026-06-28 fix).
- **`.roo/rules/`** directory doesn't exist but `docs/llm/index.md` used to reference it — the rules now live in `AGENTS.md`.
- **When the same stale value appears in multiple docs** (e.g., 12 repos, manager.py:249, RateLimiterManager:12), fix ALL files at once — partial fixes create cross-file inconsistencies that confuse agents and users.
