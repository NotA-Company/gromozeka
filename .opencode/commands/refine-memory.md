---
description: Refine docs/llm/teamlead-memory.md by extracting task-specific deep-dive sections to docs/llm/memories/ — keeps the main memory file compact and focused on reusable knowledge
agent: teamlead
subtask: true
---
## Goal

Refine `docs/llm/teamlead-memory.md` by relocating task-specific deep-dive
sections to per-topic files under `docs/llm/memories/<slug>.md`, keeping the
main file compact and focused on reusable cross-cutting knowledge.

## Non-Interactive Posture

This is a non-interactive command. NEVER use the `question` tool to ask the
user mid-flow — make best-effort decisions, state every assumption in the
final summary, and let the user review/revert via git. The teamlead receives
this prompt and dispatches the new-file extraction work to `docs-writer`
(see "Extraction Mechanism" for the full edit split); it does not write to
`memories/` itself.

## Mechanism Context

This automates an established archival pattern, not a new one. The file's own
self-description already documents the convention: line 7 instructs reading
archived task memory under `memories/` before working on a subsystem, and the
"Task-Specific Memory Files" paragraph points at the live index. 23
task-specific memory files currently live under `docs/llm/memories/` (do NOT
hard-code the count — derive it at run time via `Glob('docs/llm/memories/*.md')`
and exclude `index.md` before any work), following exactly the shape this
command reproduces.

## Extraction Rule

For each section in `docs/llm/teamlead-memory.md`, decide EXTRACT vs. KEEP
using the signals below. State every borderline judgment call in the summary.

### EXTRACT (relocate to `memories/<slug>.md`)

Sections that are dated AND feature-scoped deep dives. Signals:

- A date in the heading — e.g. "verified 2026-07-15", "implemented
  2026-07-15", "(2026-07-11)".
- A specific subsystem or file path in the heading — e.g.
  "LLM Tool-Call Healing (internal/services/llm/service.py)".
- Content that reads as a post-mortem or implementation log for a single
  feature.

### EXTRACT (worked examples — illustrative, not exhaustive)

- `## DB Cache Cleanup (verified 2026-07-15)` — dated + scoped to one
  subsystem → extract.
- `## Test Suite Performance Profile (2026-07-12, measured)` — dated +
  scoped to test-suite profiling → extract.
- `## Test Speedup IMPLEMENTED (2026-07-12): A+B applied, result 107s → 38.17s (−64.3%)` — dated + scoped to one optimization effort → extract.
- `## LLM Tool-Call Healing (internal/services/llm/service.py) — implemented 2026-07-15` — dated + scoped to one subsystem → extract.
- `## Dependency-Usage Regression Tests (2026-07-15, COMPLETED)` — dated +
  scoped to one test campaign → extract.
- `## user-memory-v2 Pre-Merge Review (2026-07-14)` — dated + scoped to one
  feature branch → extract.

### KEEP in the main file

Cross-cutting rules, repo-wide conventions, workflow lessons, user
preferences, pointers to other files, methodology summaries. Concrete
sections to keep:

- "User Preferences"
- "Repo Facts And Gotchas"
- "Opencode Slash-Command Mechanism"
- "Changelog Process"
- "Config & Tier System"
- "Test Mocking: Chat Settings Must Be Complete Dicts"
- "Teamlead Workflow Lessons"
- "Configs Tracking Gotcha"
- "CI / `make ci`"

### JUDGMENT CALLS (state decision + rationale in the summary)

Borderline sections — apply the rule consistently. When in doubt: prefer
EXTRACTING if the section is scoped to one feature/subsystem and dated;
prefer KEEPING if it generalises across the repo. Examples that need a
judgment call:

- "LLM maxRounds round-limit"
- "Large Review Campaign Lessons" and "Review-Fix Round Lessons"
- "LLM User-Message Format"
- "LLM Messages Handler Structure"
- "User Memory V2 Pre-Merge Review (2026-07-14, in progress)" AND
  "user-memory-v2 Pre-Merge Review (2026-07-14)" — near-duplicate headings
  (capital-U + spaced vs lowercase-u + hyphenated). Decide explicitly
  whether these are duplicates (likely: merge into one archived file) or
  distinct artifacts. State the decision in the summary.
- "Documentation Audit Lessons"
- "Docs Archive Layout"
- "Docs Reorg Lessons"
- "Skills & Agents Landscape Audit"

These lists are illustrative, not exhaustive. Any section matching the
EXTRACT signals above must be extracted, and every decision (extracted vs
kept) must be stated in the summary with a one-line reason.

## Extraction Mechanism

For each section chosen for extraction:

- **Slug.** Kebab-case, descriptive. Mirror the naming style of existing
  slugs like `chat-history-search`, `proxy-lifecycle`, `use-tools-filtering`,
  `db-maintenance-scripts` (verify the current inventory against
  `docs/llm/memories/index.md`). For sections being newly extracted, pick a
  new descriptive kebab-case slug that does not collide with an existing
  one. Reuse an existing slug from `docs/llm/memories/index.md` if one
  already covers the topic; otherwise create a new file.
- **New file.** Create `docs/llm/memories/<slug>.md`. Header is two lines:
  1. `# <Original Section Heading>` (verbatim).
  2. A one-line context note, verbatim:
     `Archived durable notes from [`teamlead-memory.md`](../teamlead-memory.md) (extracted <YYYY-MM-DD>). See the live compact memory there for cross-cutting rules and workflow lessons.`
- **Body.** Paste the section content verbatim. Fix every relative link that
  broke due to the path change — the file moved one directory deeper, so a
  link that was `` [`foo.py`](../../internal/foo.py) `` from
  `docs/llm/teamlead-memory.md` becomes
  `` [`foo.py`](../../../internal/foo.py) `` from
  `docs/llm/memories/<slug>.md` (one extra `../`).
- **Stub in `teamlead-memory.md`.** Keep the original heading; replace the
  section body with a single pointer line:
  `See [`memories/<slug>.md`](memories/<slug>.md) — <one-line summary of what is archived>.`
- **Index entry.** Add a bullet to the "Available Files" list in
  `docs/llm/memories/index.md` in alphabetical position, matching the
  existing format:
  `- [`<slug>.md`](<slug>.md) — <one-line description>.`

**Edit split:** teamlead edits `docs/llm/teamlead-memory.md` in place
directly (scoped allow in `teamlead.md`) — it stubs out extracted sections
and updates the "Task-Specific Memory Files" pointer. `docs-writer` creates
the new files under `docs/llm/memories/`, updates `memories/index.md`, and
runs `make check-docs`. Teamlead coordinates the dispatch — it does not
write to `memories/` itself.

## Index Pointer Update

Update the "Task-Specific Memory Files" paragraph in `teamlead-memory.md`
(the paragraph under that heading, not a line number — those rot) so its
one-line topic list mentions any newly-added memory files, or at least stays
accurate — the list is illustrative, not exhaustive.

## Post-Condition / Verification

Run `make check-docs` after all edits. It is read-only and exits `1` if any
local markdown link is broken. Fix every breakage before declaring done —
the path-depth fix described in "Extraction Mechanism" is the usual culprit.
Do NOT run `make test` (no source changed).

**Executor:** `make check-docs` is run by `docs-writer` (teamlead has
`bash: deny`). Teamlead coordinates the dispatch — it does not invoke `make`
itself.

## Summary Output

The final summary MUST list:

- Every section moved — with its slug and a one-line reason.
- Every section kept — with a one-line reason.
- Every judgment call made — with the decision and rationale.
- The `make check-docs` result (clean pass, or breakages found and fixed).

## Hard Rules

- NEVER read, edit, or stage `.opencode/memory.jsonl` — OpenCode's own
  session memory store. Hands-off.
- NEVER fabricate links, paths, or counts. Verify every internal link
  resolves after the move (this is what "Post-Condition / Verification"
  enforces).
- If a section's content is too short or too cross-cutting to stand alone as
  a memory file, KEEP it in the main file and note the decision in the
  summary.
