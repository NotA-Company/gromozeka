---
category: reference
tags: [markdown-mcp, evidence]
---

# markdown-mcp search-quality evidence — gromozeka dogfood, 2026-09-14

Audience: markdown-mcp maintainers. This handoff is self-contained — it does
not assume access to the session that produced it. All numbers below are
measured values recorded verbatim; nothing is rounded or extrapolated.

## Context

- Consumer: AI coding agents (opencode subagents) using `doc_search` as their
  PRIMARY documentation interface (MCP-first workflow adopted 2026-09-14);
  typical `top_k=3`.
- Corpus: gromozeka repo docs tree — 109 markdown files in the docs-scoped
  index (`./docs`, `exclude = ["archive/", "other/"]`; 148 repo-wide `.md`
  files at check-docs scope), heavily restructured in 2026-09-06 for
  markdown-mcp friendliness (lint-zero, front-matter everywhere, coherent
  sections).
- Tool: markdown-mcp v1.8.0 (editable local checkout), embedding model default
  e5-small; `min_score` default 0.8281339991975838; `SNIPPET_LENGTH=200` chars
  (constant); window constants `WINDOW_CHAR_THRESHOLD=1200`,
  `WINDOW_MIN_CHARS=200`, `WINDOW_OVERLAP_MAX_CHARS=200` (`constants.py:104-111`);
  read caps `section_read_cap=8192`, `disk_read_cap=65536`.
- Method: 10 realistic agent queries, run twice (before/after a docs content
  fix pass), k=3, scores recorded verbatim.

## Issue 1 — duplicate window chunks consume multiple top-k slots (maps to v1.1-backlog §5)

- Q4 "test fixtures conftest mockBot singleton reset": BEFORE — `llm/testing.md`
  §7 appeared TWICE as overlapping windows (lines 413-478 and 446-477) taking
  2 of 3 slots; the canonical answer section `llm/testing.md` §2
  "Available Fixtures" (lines 100-130) was absent. AFTER (post content fix) —
  same crowding persists: §7 twice (0.915 / 0.904, windows 415-480 / 448-479),
  §2 still absent.
- Q10 "SQL portability named parameters provider upsert ExcludedValue":
  AFTER — "Current Upsert Syntax and the ExcludedValue Marker" at #1 (0.908)
  and the SAME slug again at #3 (0.906, overlapping window).
- Q9 "MessageId class asInt asStr Telegram Max platform differences":
  BEFORE — `llm/tasks.md` §3.1 table windows took 2 of 3 slots.
- Parallel from the maintainers' own dogfood log: 2026-09-06 golden-set case —
  a quickstart section crowded out of top-18 by ~23 window hits. Our data
  confirms the same root cause from an external consumer: the 200-char window
  overlap creates distinct near-duplicate rows and the contracted no-dedup
  merge (`commands.py` "No dedup, no score aggregation (contracted, v1.1-backlog.md §5)") lets them consume multiple top-k slots, halving result
  diversity.

## Issue 2 — snippet truncation lands mid-answer (SNIPPET_LENGTH=200)

- Q7 "chat settings getChatSettings return shape toBool gotcha": BEFORE — top
  snippet (a dense table cell) ends "…Dict[Ch…" exactly where the answer
  begins.
- Q9 AFTER — the NEW prose callout ranks #1 (0.916) with richer pre-cut
  context, but the snippet still ends "…pick the acce…" — the `.asInt()` /
  `.asStr()` accessor names the query explicitly asked for sit past the cut in
  ALL THREE returned snippets.
- Q1 — a window chunk surfaces only the LAST steps of a checklist ("write
  tests… run make"), not the section's answer-bearing head.
- Net: 200 chars frequently ends mid-token/mid-cell; agents must spend a
  follow-up `doc_read` that a sentence-boundary-aware or longer top-1 snippet
  would have avoided.

## Issue 3 — score separation is too weak to act on

- All 30 chunks returned across the 10-query re-run scored within 0.88-0.92
  regardless of relevance.
- Examples: Q7 — an irrelevant `llm/index.md` docstrings section scored 0.8907
  vs 0.8966 for the correct answer (Δ 0.006). Q4 — an unrelated design doc
  scored 0.8943.
- Consequence: `min_score` (default 0.828) prunes neither noise nor signal;
  agents cannot use scores to decide whether to stop at snippets or read
  further — they must judge on title/snippet text alone, which makes Issues
  1-2 load-bearing.

## Content-side experiment (what doc authors can and cannot do)

- Two short prose H4 callouts (3-6 lines each) added to `llm/tasks.md` §3.1
  restating the two hottest table-row gotchas in prose: post-fix they became
  the #1 and #2 scoring chunks of the ENTIRE re-run (0.917 chat-settings
  callout, 0.916 MessageId callout), displacing table-window chunks; Q7
  converted partial→win.
- Table-cell content ranks lower and truncates mid-cell; equivalent prose in a
  short dedicated section ranks higher AND survives the snippet cut better.
- NEGATIVE results: an inbound See-also link (`llm/database.md` §4→§9) and a
  query-vocabulary intro sentence (`llm/handlers.md` §2) were verified present
  in the indexed bodies but produced ZERO ranking movement (Q1, Q5 unchanged).
  Retrieval profile appears driven by section content volume + heading match,
  not inbound links or thin intro prose.
- Aggregate: clean 1-call wins 4→5; misses 3→2; residual misses need content
  promotion to dedicated sections, which is authoring overhead a better
  chunker/ranker would remove.

## Reproduction

The 10 queries, verbatim:

1. "how do I add a new bot handler"
2. "primary key rules for database migrations AUTOINCREMENT forbidden"
3. "LLMMessageHandler must be last handler ordering"
4. "test fixtures conftest mockBot singleton reset"
5. "add a database migration update both schema docs"
6. "CAS token doc_section_edit workflow optimistic concurrency"
7. "chat settings getChatSettings return shape toBool gotcha"
8. "singleton reset tests _instance = None leak state between tests"
9. "MessageId class asInt asStr Telegram Max platform differences"
10. "SQL portability named parameters provider upsert ExcludedValue"

Against this repo's index: `markdown-mcp search "<query>" --top-k 3 --json`.

## Suggested levers (respecting the evidence-gated backlog)

1. Per-(file, slug) or near-overlap dedup before the final top-k trim
   (backlog §5 — this report is the requested measured example set).
2. Diversity-aware merge (e.g., MMR-style penalty on same-slug/near-identical
   chunks) as a cheap complement to full reranking (§6).
3. Snippet improvements: sentence-boundary-aware end, or a longer snippet for
   rank-1 only.
4. Any score-normalization or margin signal that lets callers distinguish
   strong from weak hits.

## Provenance

Measured 2026-09-14 in the gromozeka repo during a docs fitness audit + fix
pass + 10-query before/after validation (read-only audit; all edits
gate-reviewed). Companion reports:
[markdown-mcp-benchmark.md](markdown-mcp-benchmark.md) (tool-traffic A/B) and
[markdown-mcp-adoption.md](markdown-mcp-adoption.md) (workflow adoption) in
the same directory.

## Revalidation (2026-09-15 — post-improvement)

**What shipped** (verified in the local checkout, master @ `21722b6`, 10 commits past the v1.8.0 release cut): (1) merge dedup at `(file_path, slug)` — one highest-scoring representative per key, numeric line-range tie-break, W2 windows (null slug) never collapse, lists may return shorter than `top_k` when distinct keys run out (commits `9be17ee`, `f311241`); (2) sentence-boundary-aware snippet ends — the 200-char cut backtracks ≤50 chars to the last sentence/line boundary, else last whitespace, ≥150-char floor, never longer (commits `46c82ec`, `84ea3ab`). Score separation/margin stays parked — the maintainers' disposition cites this report's own flat-band (0.006 margins) evidence. Both fixes are query-time only; the index was not rebuilt.

**Correction to this report:** the original text maps dedup to v1.1-backlog §5; per the maintainers' dogfood log (2026-09-15), §5 closed 2026-09-06 with the no-dedup merge as the shipped contract — the implemented evidence gate was §6. The original body is left verbatim; this section carries the correction.

**Method:** identical 11 queries (the 10 above + the findability query "duplicate window chunks search quality evidence"), `top_k=3`, live `doc_search`.

**Results:**

| Metric | Baseline | Post-content-fix (old tool) | New tool (2026-09-15) |
|---|---|---|---|
| Clean 1-call wins | 4 | 5 | **6** (Q10 converts: duplicate pair gone, three distinct sections) |
| Partials | 2 | 2 | 2 (Q4, Q9 — both improved in mechanism) |
| Misses | 3 | 2 | 2 (Q1, Q5 — unchanged) |
| Duplicate (file,slug) pairs in top-k | ≥4 observed | ≥2 | **0 across all 33 slots** |
| Mid-token snippet cuts | ≥2 ("Dict[Ch…", "pick the acce…") | ≥1 | **0** (6/11 line/list boundaries, 5/11 whitespace fallback) |

**Fix 1 (dedup) — confirmed by three independent effects:** Q4's §7 double-window pair (0.915/0.904, overlapping windows) collapsed to a single representative; Q10's same-section pair is gone (three distinct slugs now); the findability query's same-slug triple sweep (all 3 slots, one slug) dropped to two DISTINCT-section hits plus one foreign file. No list ever returned fewer than 3 (the shorter-list branch was not exercised).

**Fix 2 (boundary snippets) — confirmed:** zero mid-token cuts; the two historically bad cuts now land cleanly ("…Dict[Ch…" → word-boundary "…read via"; "…pick the acce…" → word-boundary "…pick the"). Q9's top snippet ends exactly before "accessor" — the `.asInt()`/`.asStr()` names remain excluded, as contracted (snippets only got shorter; a longer rank-1 snippet is explicitly out of scope upstream).

**Unchanged, exactly as predicted:** raw scores are digit-for-digit identical (e.g. 0.9172651842236519 for the chat-settings callout; 0.9007272273302078 for this report's Issue-1 section) — the band stays flat and scores remain unusable as relevance signals; Q1's canonical `llm/handlers.md` §2 and Q5's `llm/database.md` §9 still do not surface (verified present in the index — ranking is untouched by both fixes); Q4's canonical §2 "Available Fixtures" still absent — the slot freed by dedup went to distinct but unrelated documents.

**Residual levers, with fresh measured cases for the parked MMR/rerank follow-up:** (a) ranking — Q1/Q5 canonical sections exist in the index but never reach top-3 while human-oriented substitutes do; (b) result usefulness after dedup — Q4's freed slot filled with unrelated documents rather than the canonical fixture section; (c) optional file-level diversity — the findability query still returns this report in 2 of 3 slots (distinct slugs are distinct keys; per-FILE representation would be a further, separate change).

**Provenance:** revalidated 2026-09-15 in the gromozeka repo, same corpus (109 docs-scoped index files; content unchanged since the 2026-09-14 fix pass). Original report body unchanged; this section appended as the closing record.
