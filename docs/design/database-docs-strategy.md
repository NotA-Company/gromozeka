---
category: design
---

# Database documentation strategy

Status: Draft — awaiting owner decision, 2026-09-06. Analysis and proposal only: no merge, deletion, or content move has been performed. Scope is the six database-related documents below, in response to the docs-rewrite brief decision that a strategy write-up must precede any consolidation ("no unilateral merge").

## Current landscape

Six documents currently share the database-layer topic. Together they carry roughly 7,200 lines, with four distinct maintenance triggers fanning most schema-touching changes across three or more files at once.

### Per-document summary

| Document | Category | Lines (approx.) | Audience | Scope in one line | What forces an edit |
|---|---|---|---|---|---|
| [database-README.md](../database-README.md) | reference | 788 | Humans and LLMs landing on the DB topic | Index and overview: doc map, table-category nav, portability overview, repository inventory, usage examples, statistics | Any schema / migration / repository / provider change (lists and counts) |
| [database-multi-source.md](../database-multi-source.md) | guide | 888 | Operators configuring multi-database setups | 3-tier routing narrative, provider parameters, readonly behavior, troubleshooting, use cases | Provider parameter, routing, or DatabaseManager API change |
| [database-schema.md](../database-schema.md) | reference | 1132 | Developers, DBAs, architects | Human-facing schema: column tables, migration catalog 001-029, enums, TypedDicts, repository index, best practices | Every schema change (dual-doc mandate with the LLM doc) |
| [database-schema-llm.md](../database-schema-llm.md) | reference | 1494 | LLM agents and code generation | LLM-facing schema: CREATE TABLE per table, method signatures, enums, query patterns, routing | Every schema change (dual-doc mandate) plus any repository signature change |
| [sql-portability-guide.md](../sql-portability-guide.md) | reference | 1952 | Developers writing SQL or migrations | 13-issue cross-RDBMS analysis, provider-hook contracts, vector-search portability, best practices, phased plan | Provider API change or a new portability rule |
| [docs/llm/database.md](../llm/database.md) | guide | 929 | LLM agents doing DB work | Repository method tables, chat-settings gotchas, dataSource convention, migration recipe, models lookup, migration catalog | Any repository method, migration, model, or provider change |

### Landscape observations

- Three documents claim LLM readership: the README ("For LLM-Based Development"), the LLM schema reference, and the agent guide (which opens with "Self-contained: Everything needed for database work is here").
- The README has grown beyond a landing page: its "SQL Portability" section (~250 lines) is a mid-length duplicate of the portability guide, and its statistics block self-describes as drift-prone ("These counts drift easily").
- The multi-source guide is the oldest artifact (v1.0, dated 2025-11-30) and predates current conventions: it leads with a Python-dict constructor config and calls repository methods without `await`.
- The portability guide is half live contract (provider hooks, vector search, best practices) and half historical project plan (phased implementation strategy, migration checklist, "Next Steps" with a 6-week estimate) whose phases are long completed.
- The agent guide ([docs/llm/database.md](../llm/database.md)) is wired into [docs/llm/index.md](../llm/index.md) navigation and [AGENTS.md](../../AGENTS.md), making it the de-facto entry point for agents, while the dual schema docs are the de-facto reference.

## Overlap matrix

### Content appearing in two or more documents

| # | Content | README | Multi-source | Schema | Schema-LLM | Portability | llm/database | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | Per-table definitions (columns / DDL) | nav links | - | full (tables) | full (CREATE) | - | partial (models table in 5.5) | Pair is deliberate; 5.5 is an accidental third copy |
| 2 | Provider config TOML shape | yes | yes | yes | - | stale variant | yes | Four matching copies plus one stale variant (Issue #12) |
| 3 | 3-tier routing (dataSource, chatMapping, default) | yes | yes (dedicated) | yes | yes | - | yes | Five copies; agent guide adds the MUST-level dataSource convention |
| 4 | Provider hooks (upsert, ExcludedValue, pagination, comparisons, text type) | yes | - | - | - | yes (deep) | yes | Three copies at three depths |
| 5 | Migration recipe (create migration_XXX, BaseMigration shape) | brief | - | yes | - | - | yes (richest) | Plus AGENTS.md and the add-database-migration skill |
| 6 | Migration catalog 001-029 | version only | - | yes (tables) | count only | - | yes (second full catalog) | Two full catalogs to keep aligned |
| 7 | Enums (MessageCategory, MediaStatus, SpamReason, CacheType, etc.) | - | - | 4 members | 5 members | - | 6 members | Three sections with three different coverage sets |
| 8 | Repository inventory and methods | yes (16, with method lists) | partial | yes (15-row table) | yes (full signatures) | - | yes (16) | Four copies; counts disagree (see drift) |
| 9 | vec0 virtual tables (DDL + lifecycle) | - | - | yes | yes | API contracts | yes | Identical 5-line DDL appears three times |
| 10 | Timestamp rule (no DEFAULT CURRENT_TIMESTAMP) | yes | - | per-column notes | - | yes (Issue #3) | yes | Four copies, currently consistent |

### Which copy is normative today

- Code is ground truth: migrations under [internal/database/migrations/versions/](../../internal/database/migrations/versions/), the wrapper at [database.py](../../internal/database/database.py), and providers under [lib/db/providers/](../../lib/db/providers/) win over every document.
- Schema facts: [database-schema.md](../database-schema.md) and [database-schema-llm.md](../database-schema-llm.md) are co-canonical by the AGENTS.md dual-doc mandate; nothing else may contradict them.
- Portability rules: AGENTS.md carries the operational summary; [sql-portability-guide.md](../sql-portability-guide.md) is the canonical deep dive. The README's portability section is derivative and non-authoritative.
- Agent workflow and the migration recipe: [docs/llm/database.md](../llm/database.md) is canonical for agents (per the docs/llm navigation); the add-database-migration skill restates the recipe operationally.
- Config shape: [00-config.toml](../../configs/00-defaults/00-config.toml) and [docs/llm/configuration.md](../llm/configuration.md) define the live `[database.providers.<name>]` dialect; the multi-source guide is narrative around it.
- Only the schema pair (and, informally, the agent guide) have a mandated sync today. Rows 2-8 of the matrix above have no assigned owner, which is the root cause of the drift below.

## Drift evidence

### Divergence confirmed against code

1. Repository count. [database.py](../../internal/database/database.py) wires 15 repositories (lines 231-250). The agent guide says "16 total"; the README says "16 specialized repositories" in two places while its own statistics block says "Total Repositories: 15"; the schema doc says 15. The stale 16 counted `webhookUpdates`, which left the wrapper with ADR-025.
2. UserMemoriesRepository method count. The repository at [user_memories.py](../../internal/database/repositories/user_memories.py) has 12 public async methods. The LLM schema doc and the agent guide say 12; the human schema doc says "10 public methods" in its UserMemoriesRepository section.
3. MySQL case-insensitive comparison. [mysql.py](../../lib/db/providers/mysql.py) line 323 emits `column COLLATE utf8mb4_general_ci = :param`. The README and the portability guide document the COLLATE shape (correct); the agent guide section 7 claims LOWER() is returned "on every concrete provider today" (wrong for MySQL).
4. Bayes tables origin. [migration_001_initial_schema.py](../../internal/database/migrations/versions/migration_001_initial_schema.py) creates `bayes_tokens` (line 258) and `bayes_classes`; the LLM schema doc's Bayes Statistics section credits `migration_006`, which per the schema-doc catalog is the Geocode Maps cache migration.
5. enableForeignKeys default and dialect. [sqlite3.py](../../lib/db/providers/sqlite3.py) line 115 defaults `enableForeignKeys=True` (camelCase kwarg). Portability guide Issue #12 recommends a snake-case `enable_foreign_keys` defaulting to False, inside a `[[sources]]` / `connection_string` config dialect that matches no current code or config file.

### Divergence between documents

6. Multi-source guide contradicts itself: its API Reference says "All repository methods accept an optional dataSource parameter", while its own later Write Methods correction says repository write methods do not forward `dataSource`.
7. Dangling anchor plus enum coverage split: the schema doc's `chat_info.bot_status` row links to an in-page `ChatBotStatus` section that does not exist in that file (it exists only in the LLM schema doc). The three enum sections carry 4, 5, and 6 members respectively; no single doc lists all enums.
8. Agent guide migration-catalog labels: a heading says "Known migrations 001-015" while the list beneath it runs through migration_029; the migration recipe's worked example still says "the example below uses 025" now that the tree is at 029.
9. Config style age: the multi-source guide (2025-11-30) presents the Python-dict constructor as the primary configuration path and shows synchronous repository calls; current convention is TOML `[database]` plus await, per the agent guide and the configuration doc.
10. README statistics block disagrees with the README's own body (16 vs 15 repositories, see item 1) — the block itself warns "These counts drift easily".

## Strategy options

### Option A — status quo plus tightened sync checklist

Keep all six documents unchanged; extend the existing documentation-sync matrix (AGENTS.md, update-project-docs skill) with an explicit per-change fan-out list: schema change to both schema docs plus the agent guide's catalog; repository change to the agent guide plus README stats; provider change to the portability guide plus the README portability section.

- Pros: zero restructuring; all inbound links and audience entry points untouched; cheapest immediately.
- Cons: duplication is policed, not removed; a schema-touching change still fans out across three to six files; the drift items above show checklist-only sync has already leaked (counts, enum coverage, catalog labels).
- Migration cost: trivial (one checklist edit).
- Drift resistance: low — human discipline only.

### Option B — single source of truth with generated derivatives

Give each duplicated topic one authoritative source and generate the rest: schema facts (tables, enums, TypedDict index, migration catalog) owned by one schema doc or an extracted data file, with the other view rendered by a script under `scripts/` wired into the Makefile (the repo already has [check_docs.py](../../scripts/check_docs.py) and markdown-mcp as precedent); counts generated from code; CI fails on stale output.

- Pros: highest drift resistance for the highest-churn facts (exactly the class that drifted: counts, catalogs, enum members); retires the manual dual-doc mandate for mechanical content.
- Cons: highest upfront cost (generator, templates, CI wiring); loses hand-written nuance in long explanatory cells (for example the `chat_info.bot_status` self-heal narrative, which is not mechanical); adds a tool that itself needs maintenance; the two schema audiences need different renderings, so the generator must be genuinely multi-target.
- Migration cost: high (several sessions; new script plus Makefile target plus partial doc restructure).
- Drift resistance: high for generated slices; narrative sections remain manual.

### Option C — full merge into fewer documents

Merge the README into the schema doc as a short header; fold the multi-source guide into the schema doc or the configuration doc as a section; keep the portability guide and the agent guide but strip their duplicated schema and catalog content to links. Net result: about three documents.

- Pros: exactly one physical copy per topic without new tooling; sync burden drops structurally.
- Cons: large one-time edit with repo-wide link surgery (the link checker finds inbound links, but externally held references still break); produces files well beyond 2,000 lines in a tree that caps section bodies; removes the multi-source guide from its deliberate "docs/ root for easy access" placement; conflicts with the AGENTS.md dual-doc mandate unless the mandate itself is rewritten — an owner decision.
- Migration cost: high (merge plus link fixing plus mandate change).
- Drift resistance: medium-high — duplication removed, but manual edits can still contradict code.

### Option D — role sharpening without merge

Keep all six files and their locations; assign each duplicated topic exactly one owner and reduce every other copy to a short summary plus link. Proposed ownership map: schema facts (rows 1, 6, 7, 9) owned by the schema pair per the existing mandate, with the agent guide's section 5.5 and section 9 shrinking to links and the missing enum entries added to the schema doc; portability rules (rows 4, 10) owned by the portability guide plus the AGENTS.md summary, with the README portability section reduced to a provider list and link; multi-source narrative (rows 2, 3) owned by the multi-source guide for operators and by the agent guide section 3 for the agent-facing MUST-rule, with the README and schema doc keeping one paragraph plus link; migration recipe (row 5) owned by the agent guide section 4 (matching the skill), with the README and schema doc reduced to three-line summaries; repository inventory (row 8) owned by the LLM schema doc for signatures with the schema doc table as the human index, and the README statistics block deleted in favor of a link. Items 6 and 9 in the drift list (the multi-source guide's internal contradiction and its Python-dict-first config) get fixed in the same pass.

- Pros: preserves every entry point and inbound link (the docs link check stays trivially green); each fact gains one authoritative home; per-change fan-out drops to one or two documents for most changes; cheap to reverse or escalate to Option B later.
- Cons: the schema pair remains manually dual-maintained (the one duplication that is audience-driven and mandated); readers pay link-hopping cost; summaries can silently regrow into copies, which lint cannot catch.
- Migration cost: low to medium (one or two documentation sessions, no code).
- Drift resistance: medium-high — accidental duplication eliminated; only the mandated pair stays dual.

## Recommendation

Adopt Option D now, fix drift items 1-10 in the same pass, and record Option B as the designated successor for the schema pair if dual-doc drift recurs after the next two or three schema changes. Rationale:

- The only deliberate duplication is the schema pair (two audiences, mandated). Everything else is accidental and can be de-duplicated by linking without touching the mandate.
- Generation pays off only for high-churn mechanical facts, and the worst observed drift (counts, catalog labels, enum coverage) is exactly that class — but building a generator before roles are sharp risks automating the wrong split. Option D produces the ownership map Option B would need anyway.
- Option C buys nothing Option D does not, while breaking links and requiring a mandate change; both the link checker's existence and the multi-source guide's "retained at docs/ root" note argue against removal.
- Option A is strictly dominated by D: same near-zero restructuring cost, strictly worse drift resistance.

Suggested sequencing for approval: first fix the ten drift items in place; second, apply the D ownership map document by document; third, re-audit after the next two or three schema changes and, if the pair drifted again, commission the Option B generator for schema tables, enums, and the migration catalog only.

## Open questions for the owner

1. Is the AGENTS.md dual-doc mandate for the schema pair fixed, or is generating one view from the other (Option B) acceptable if the pair drifts again?
2. Should the README keep any statistics block, or is a link to the schema doc enough given the block's own drift warning?
3. Should the multi-source guide (2025-11-30 vintage) remain the owner of multi-source narrative, or should the agent guide absorb the topic and the guide shrink to operator examples (TOML, troubleshooting, use cases)?
4. Should the portability guide's completed phases (implementation strategy, migration checklist, next steps) be trimmed to a short history note, keeping only the live contracts (provider hooks, vector search, best practices)?
5. Should the agent guide's provider-method section defer entirely to the portability guide, eliminating the third copy of hook behavior?
6. Independently of Option B, should CI gain a small drift guard for mechanical facts (table count, migration count, enum members) that compares the docs against code?
