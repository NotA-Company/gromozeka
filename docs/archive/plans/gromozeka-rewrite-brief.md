---
title: "gromozeka docs rewrite brief"
description: "One-time agent briefing to clean up the gromozeka docs tree for markdown-mcp"
tags: [playbook, gromozeka]
category: guide
---

# gromozeka docs rewrite brief

You are the agent working in the gromozeka repository
(`/Users/vgoshev/Development/NotA/gromozeka`). This is a one-time plan to
clean up its `docs/` tree so markdown-mcp (already wired in) indexes a
coherent, searchable, deduplicated corpus. Work phase by phase.

## Ground rules

- Work in the gromozeka repo. Read gromozeka's `AGENTS.md` first and let it win
  on any conflict with this brief.
- Archive, do not delete. The policy lives in `docs/archive/README.md`
  (Archiving Criteria section): files move to `archive/` when any criterion
  applies — criterion 1 is "**Feature completed** and the plan/history is
  no longer needed for active work"; the others cover architecture
  superseded, proposal abandoned, historical report, and status stale.
  Completion alone is not sufficient for criterion 1. `archive/` has
  subdirectories `design/`, `llm-sessions/`, `plans/`, `reports/`,
  `review/` — pick the matching one.
- Moving a file breaks inbound relative links. In the same commit, grep for
  links to the moved path, fix them, and run `make check-docs` (it runs
  `scripts/check_docs.py` and exits 1 on broken local links).
- Small batches: one commit per phase (or per file group), following the
  repo's observed style — short imperative summaries like `Archive completed
  sandbox plans`; AGENTS.md defines no formal commit convention.
- gromozeka's own quality gates are mandatory for every change, docs-only
  included (AGENTS.md "Run / dev commands", `docs/llm/index.md` §3.5):
  run `make format lint` BEFORE edits, and after edits run `make format
  lint`, then `make test` (mandatory after any change), then `make
  check-docs`, plus `markdown-mcp lint` — findings should go down, never
  up.
- markdown-mcp is already wired in: `doc_lint()` / `markdown-mcp lint` parse
  the tree directly and need no index, and the write tools are enabled
  (`[docs].writable = true`). Always `doc_read` before any write — every
  modification is compare-and-swap gated.
- Items marked DECISION need the owner: implement only the stated default if
  unavailable, and record the choice in gromozeka's `AGENTS.md` or
  `docs/README.md` (Phase 2 creates it).

## Current state (verified 2026-09-06 — re-verify at start; facts drift)

- 277 `.md` files under `docs/`; 167 in `docs/archive/` (excluded from the
  index by `.markdown-mcp.toml` `exclude = ["archive/"]`). Live corpus: 110
  files.
- Live trees: `docs/` root flat with 9 files (`developer-guide.md` 2814 lines,
  `sql-portability-guide.md` 1934, `database-schema-llm.md` 1483,
  `database-schema.md` 1096, `database-multi-source.md` 883,
  `database-README.md` 774, `documentation-review-process.md` 770,
  `max-webhook-setup.md` 584, `product-page.md` 131); `docs/llm/` with 14
  agent guides plus `memories/` (48 files including `index.md`);
  `docs/design/` 18; `docs/plans/` 5; `docs/suggestions/` 3;
  `docs/templates/` 3; `docs/examples/` 4; `docs/other/` third-party API
  dumps (9 md files — 8 under `yc-ai-sdk/` plus
  `geocode-maps/Geocode-Maps-API.md` — alongside swagger/OpenAPI
  JSON/YAML, geocoder JSON samples, and a txt).
- Front matter: 0 of 277 files. Existing metadata is ad-hoc blockquote
  headers (`> **Purpose:**`, `> **Status:**`) and italic `*Last updated:*`
  footers — inconsistent shapes, nothing indexable.
- No docs-tree index: neither `docs/README.md` nor `docs/index.md` exists.
  Entry points are root `README.md`, root `AGENTS.md` ("Existing instruction
  sources" section), and `docs/llm/index.md`.
- markdown-mcp lint baseline (2026-09-06): 118 findings — 42 `duplicate-slug`
  across 13 files, 76 `oversized-section` across 30 files; zero
  `duplicate-h1`, zero `missing-title`, zero `malformed-frontmatter`.
- Pitfall when recounting: `grep -c '^# '` overcounts H1s because Python/SQL
  comments inside fenced code blocks match. `docs/sql-portability-guide.md`
  shows 67 such lines but has exactly one real H1. Count headings only with a
  fence-aware parser or `markdown-mcp lint`; never with plain grep.

## Decided — `docs/other/` treatment (owner, 2026-09-06)

`docs/other/` holds third-party API dumps. The owner decided: exclude the
whole subtree, keep it byte-stable, and add a hand-written index file.

1. Add `"other/"` to `[docs].exclude` in gromozeka's `.markdown-mcp.toml`.
   The subtree stays byte-for-byte unchanged. Exclusion affects indexing
   and search only — direct file reads still work — and lint follows the
   same exclusion rules, so `docs/other/` leaves both scopes. Changing
   `.markdown-mcp.toml` is a config change in gromozeka; their changelog
   policy may require an entry — the agent must check `AGENTS.md` /
   `docs/llm/changelog.md` and follow it.
2. NEW SUBTASK (do it in Phase 2): create `docs/other/README.md`, an index
   of the subtree with one line per item saying what it is and when an
   agent would consult it: `yc-ai-sdk/` (8 md files),
   `geocode-maps/Geocode-Maps-API.md` plus its JSON samples, the
   Max-Messenger swagger JSON and OpenAPI YAML, and
   `telegram-markdown-v2.txt`. State the access rule explicitly:
   everything under `docs/other/` is excluded from markdown-mcp indexing
   and search and is reachable ONLY via direct file access or links —
   never via `doc_search`. The README itself sits inside the excluded
   prefix, so it is unindexed too; link it from `docs/README.md` (which IS
   indexed) so a search for e.g. "yc-ai-sdk" surfaces the entry point that
   points there. This README is the ONLY new file allowed inside
   `docs/other/`.

Every later mention of `docs/other/` in this brief follows this decision.

## Phase 0 — Orient

1. Read gromozeka's `AGENTS.md`, `docs/llm/index.md`, and
   `docs/archive/README.md`.
2. Record the lint baseline: `markdown-mcp lint --json` (or `doc_lint()`).
   Expect roughly the numbers above; if they differ, the tree drifted — work
   from what you observe.
3. Confirm the index opens and is current: `markdown-mcp stats`, then
   `markdown-mcp index` (incremental; harmless if already current).
4. Keep the baseline findings list in your working notes; it is the score you
   drive to zero in Phase 7.

## Phase 1 — Archive sweep

Verify each completion signal in `docs/llm/teamlead-memory.md` and
`docs/llm/memories/` before moving; then `git mv` and fix inbound links in
the same commit. Move nothing whose status you could not confirm.

1. `docs/plans/` candidates:
   - `python-sandboxing-v1.md` — Decided (owner, 2026-09-06): KEEP it live
     for now; do not archive. The header self-identifies the doc as the
     retained design reference for the live `lib/sandbox/` package, and
     `docs/llm/sandbox.md` links it as its design source — it is a live
     reference even though teamlead-memory marks the arc COMPLETE
     2026-09-05. The owner may revisit archiving once pending validation
     resolves; if it later moves to `docs/archive/plans/`, fix the inbound
     links then (`docs/llm/sandbox.md` at minimum).
   - `sandbox-update-simplification-v1.md` — "approved 2026-09-05,
     implemented 2026-09-05". Move to `docs/archive/plans/`.
   - `sandbox-update-v1.md` — design ratified 2026-09-04; teamlead-memory
     records the staged-install arc and all three follow-ups COMPLETE
     2026-09-06. Move to `docs/archive/plans/` once you have confirmed that in
     teamlead-memory.
   - `embedding-model-lookup-refactor-v1.md` — plan header says "APPROVED",
     but `docs/llm/memories/embedding-model-lookup-refactor.md` says COMPLETE
     2026-07-21, all phases. Move to `docs/archive/plans/`.
   - KEEP `docs/plans/llm-empty-truncated-final-handling-v1.md` — status
     "PARTIALLY IMPLEMENTED (re-verified 2026-07-18)". Still active.
2. httpx2 docs — Decided (owner, 2026-09-06): KEEP both live for now; do
   not archive. `docs/design/httpx2-migration-v1.md` (status
   "IMPLEMENTED, all phases landed") and `docs/design/httpx2-migration-research.md`
   (verdict ADOPTED) are still live references: ADR-021 in
   `docs/llm/architecture.md` links both as its canonical rationale, and
   the operator-only manual smoke gates remain PENDING. The owner may
   revisit archiving once the pending validation resolves; if the docs
   then move to `docs/archive/design/`, fix the inbound links
   (`docs/llm/architecture.md`, `docs/llm/teamlead-memory.md`,
   `docs/llm/memories/index.md`, and two `docs/design/` files) and record
   the pending-gates caveat in the commit message.
3. Triage `docs/suggestions/` (`improvements.md`, `refactoring.md`,
   `simplification.md`): all three self-declare staleness ("Last updated:
   2026-04-18", "Status review: 2026-05-02 — statuses may be stale", plus a
   2026-07-18 audit note). Decided (owner, 2026-09-06): archive all three
   to `docs/archive/reports/` (they are point-in-time audit lists, not
   living guidance) and note in `docs/README.md` how to regenerate fresh
   suggestion lists.
4. Fix `docs/llm/teamlead-memory.md`:
   - The stale claim that `.markdown-mcp.toml` is "deliberately uncommitted"
     (it appears inside the long sequencing line and again at the end of it).
     The file is committed; delete or correct both statements.
   - Reflow the monster run-on line (line ~52, over 6,600 characters) into
     structured bullet notes in place: one thought per bullet; keep dates
     and commit hashes; never store secrets or raw logs.
   - Optionally, when gromozeka's memory rules
     (`docs/llm/memories/index.md`) demand it, move clearly archival
     subsystem-scoped detail into `docs/llm/memories/` files — updating
     `docs/llm/memories/index.md` in the same commit. Permitted, not
     required.

## Phase 2 — Entry points

Create `docs/README.md` as the docs-tree index, organized by audience:

- Humans: root `README.md`, `docs/developer-guide.md`,
  `docs/product-page.md`, `docs/database-README.md` (landing page for the
  database docs), `docs/max-webhook-setup.md`.
- Agents: `AGENTS.md`, the `docs/llm/` guide tree (link `docs/llm/index.md`
  as its entry), `docs/documentation-review-process.md`, the skills under
  `.agents/skills/`.
- Reference and supporting material: `docs/database-schema.md`,
  `docs/database-schema-llm.md`, `docs/database-multi-source.md`,
  `docs/sql-portability-guide.md`, `docs/design/`, `docs/plans/`,
  `docs/templates/`, `docs/examples/`, and `docs/other/` entered via its
  `docs/other/README.md` index.
- Create `docs/other/README.md` here, per the decided `docs/other/`
  treatment above, and link it from this file.
- State explicitly that `docs/archive/` is historical only, that
  `docs/archive/` and `docs/other/` are excluded from the markdown-mcp
  index, and that `docs/other/` is reachable only via direct file access
  through its README.

Then point the existing entry points at it: add a docs-tree link to root
`README.md` and to `AGENTS.md`'s "Existing instruction sources" section.
Follow their "do not duplicate, prefer linking" rule — link, do not copy
content.

## Phase 3 — Structure

Re-run `markdown-mcp lint --json` after Phase 1 (archiving removes findings)
and work the remainder:

1. `duplicate-slug` (expect ~42 across 13 files; heaviest: suggestions/* 5-6
   each, `database-README.md` 6, `sql-portability-guide.md` 5, plus
   `developer-guide.md`, `database-multi-source.md`, `database-schema.md`;
   `docs/other/` dumps are excluded and out of scope). Fix by making the
   repeated headings specific
   (e.g. two "Configuration" H2s become "Configuration file layout" and
   "Config reload behavior"). If a file was archived in Phase 1, skip it.
2. `oversized-section` (flat body over the 5000-character read cap; expect
   ~76 across 30 files; heaviest: `llm/architecture.md` 9,
   `llm/libraries.md` 6, `llm/configuration.md` 5). Break each offender by
   introducing H3 subsections, or split content into sibling documents when
   a section is really two topics. Oversized sections are user-visible
   today: markdown-mcp truncates their reads and refuses section edits on
   them.
3. Monolith evaluation: `docs/developer-guide.md` (2814 lines) is the
   largest live file. DECISION, default: keep it single-file for now but
   break its oversized sections; propose a topic split
   (getting-started / handlers / database / services) to the owner and
   implement only on approval.
4. Do NOT hunt duplicate H1s: the 2026-09-06 baseline has zero
   `duplicate-h1` findings. Earlier surveys that flagged
   `sql-portability-guide.md` (67 "H1s") counted fenced code comments — see
   the pitfall note above.

## Phase 4 — Front matter rollout (live docs only)

`docs/archive/` is excluded from the index — do not add front matter there.
markdown-mcp itself treats all four fields (`title`, `description`, `tags`,
`category`) as optional: unknown fields are ignored and invalid front
matter never blocks indexing. How much of that shape gromozeka adopts is
project policy, not tool contract.

Decided (owner, 2026-09-06) — metadata policy. Implement the following and
record it in gromozeka's `AGENTS.md` or `docs/README.md`:

- `category`: required on every live doc, from a closed five-value set —
  `design` (docs/design/), `plan` (docs/plans/), `process` (docs/llm/
  tree and documentation-review-process.md), `guide` (developer-guide.md,
  max-webhook-setup.md, product-page.md, database-README.md), `reference`
  (database-schema.md, database-schema-llm.md, database-multi-source.md,
  sql-portability-guide.md, docs/templates/, docs/examples/). Per-file
  overrides are fine where the tree default is clearly wrong; keep the
  set itself at five values.
- `title`: only where the first H1 or the filename stem is inadequate.
  Title precedence is: front-matter title, then first H1, then filename
  stem.
- `description`: recommended for entry-point and landing docs
  (`docs/README.md`, `database-README.md`, `docs/llm/index.md`) — one
  line written for scanning, since `doc_list` surfaces it.
- `tags`: optional and sparse, kebab-case, vocabulary
  seeded organically — add a tag when the facet actually recurs, check
  `doc_tags()` first, and record new values where the vocabulary is
  defined.

Work tree by tree and lint after each batch (`doc_lint` catches
non-kebab-case tags/categories and malformed front matter immediately).
`docs/other/` is excluded per the decision above: no front matter there at
all — it is out of index and lint scope; leave the subtree byte-stable.

## Phase 5 — Dedup

1. gromozeka `AGENTS.md` duplicates `docs/llm/index.md` section 3 rules
   (naming, docstrings, type hints) while each file points at the other as
   the source. Their own rule: do not duplicate, prefer linking. Decided
   (owner, 2026-09-06): keep the normative text in `docs/llm/index.md`
   section 3 (the canonical deeper guide per AGENTS.md's own header) and
   reduce AGENTS.md to a one-line summary plus link.
2. Four root database docs: `database-README.md` (self-described landing
   page), `database-schema.md`, `database-schema-llm.md` (AGENTS.md requires
   keeping the two schema docs in sync manually), `database-multi-source.md`.
   Decided (owner, 2026-09-06): evaluate whether the LLM-facing schema doc
   can be generated from the human-facing one (or both from migrations) so
   the manual sync rule can retire. Implement only what is safe — e.g.
   cross-links and a sync-state marker carrying the current ISO date at
   rewrite time on both schema docs — and deliver the consolidation or
   generation strategy in writing. Do not merge or delete any of the four
   unilaterally.

## Phase 6 — Normalize

Two policy gaps are genuinely undecided in gromozeka — its `AGENTS.md` and
`docs/llm/index.md` state no docs language and no emoji policy. Decided
(owner, 2026-09-06): adopt the defaults below. Check those files for any
statement — if one exists, it wins and you skip the corresponding item.

1. Mixed language: Cyrillic fragments appear in ~18 live docs (including six
   `docs/llm/` guides and memories). Decided (owner, 2026-09-06): unify
   docs to English (the language of README, AGENTS.md, and nearly all live
   docs) and keep Russian only where it quotes primary sources (Max API
   material, operator quotes).
2. Emoji: present in ~30 live files (suggestions, templates, memories, parts
   of the root guides, and the third-party API dumps). Decided (owner,
   2026-09-06): strip emoji from first-party live docs; leave `docs/other/`
   content unchanged (byte-stable under the decided exclude option) and
   leave `docs/archive/` untouched.
3. Root `TODO.md` also mixes Russian and emoji, but it sits outside `docs/`
   (not indexed, not linted by markdown-mcp). Fixing it is a normal repo edit
   with plain file tools — include it under the same decided policy.

## Phase 7 — Verify

1. `markdown-mcp lint` — zero findings on the live non-excluded tree
   (advisory tool; the CLI exits 1 while findings remain). `docs/other/`
   is excluded, so it is out of lint scope.
2. `markdown-mcp index --force` — a deliberate full rebuild (it replaces
   the existing index, whatever its schema) so the index reflects the new
   front matter and structure atomically.
3. Search smoke tests via `doc_search` (or CLI `markdown-mcp search`), each
   expected to rank the right file first:
   - "max messenger webhook setup" → `docs/max-webhook-setup.md`
   - "database schema repositories" → the database schema docs
   - "sql upsert portability across databases" → `docs/sql-portability-guide.md`
   - "sandbox staged install pool" → `docs/llm/sandbox.md` (the archived
     plan must not outrank live docs; confirm archive exclusion works)
4. gromozeka's gates: `make format lint`, `make test`, and `make check-docs`
   all pass on the final state.
5. CHANGELOG: gromozeka's policy skips doc-only tweaks unless they document a
   new feature — check `AGENTS.md` / `docs/llm/changelog.md` and follow it;
   the `.markdown-mcp.toml` change (`docs/other/` exclusion) may require
   an entry.
6. Summarize before/after lint counts and the implemented policies
   (metadata, `docs/other/`, language, emoji, dedup) in the final report
   to the owner.

## Explicit out of scope

- Repo-root clutter (`htmlcov/`, `logs/`, `bak/`, `.coverage`,
  `test-video.mp4`) — separate cleanup, not this brief.
- `docs/llm/memories/` rewrites — memory files are historical records.
  Exceptions: the Phase 1 `teamlead-memory.md` fixes, and the permitted
  (not required) archival move into `docs/llm/memories/` with its
  `index.md` update.
- Any production code, configs under `configs/`, tests, or dependencies.
- `docs/other/` contents beyond the decided treatment (byte-stable; the
  only permitted new file is the `docs/other/README.md` index).
- `docs/archive/` contents — archived files are never updated for drift.

## Acceptance checklist

- [ ] gromozeka's gates ran around every edit: `make format lint` BEFORE
      edits and again after, then `make test` (mandatory after any change),
      then `make check-docs` (zero broken links); plus zero markdown-mcp
      lint findings (item below).
- [ ] Completed plans moved per the Phase 1 dispositions;
      `python-sandboxing-v1.md` and the two httpx2 docs kept live per the
      owner decision of 2026-09-06; inbound links fixed for everything
      moved.
- [ ] `llm-empty-truncated-final-handling-v1.md` still live in
      `docs/plans/`.
- [ ] `docs/suggestions/` archived to `docs/archive/reports/` per the
      owner decision of 2026-09-06.
- [ ] `docs/other/` excluded via `.markdown-mcp.toml`, subtree byte-stable,
      `docs/other/README.md` index created and linked from
      `docs/README.md`, changelog policy checked.
- [ ] `teamlead-memory.md`: stale `.markdown-mcp.toml` claim gone; the
      6,600+ character line split into structured notes.
- [ ] `docs/README.md` exists, is audience-organized, and is linked from
      root `README.md` and `AGENTS.md`.
- [ ] `markdown-mcp lint` reports zero findings on the live non-excluded
      tree.
- [ ] Front matter follows the decided metadata policy (category required
      from the five-value set; title only where H1/filename stem is
      inadequate; description recommended on entry-point docs; sparse
      kebab-case tags), recorded in `AGENTS.md` or `docs/README.md`.
- [ ] AGENTS.md / `docs/llm/index.md` rule duplication resolved (normative
      text in `docs/llm/index.md` section 3, AGENTS.md a one-line summary
      plus link); database-docs strategy written up.
- [ ] Language and emoji normalization applied per the owner decisions of
      2026-09-06.
- [ ] `markdown-mcp index --force` (deliberate full rebuild) succeeded; all
      four search smoke tests rank the expected file first.
- [ ] The decided policies (metadata policy; `docs/other/` exclusion with
      its README index) recorded in gromozeka's `AGENTS.md` or
      `docs/README.md`.
