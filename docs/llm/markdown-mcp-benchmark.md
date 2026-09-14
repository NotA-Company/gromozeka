---
category: reference
tags: [markdown-mcp, benchmark]
---

# markdown-mcp Benchmark: Tool-Traffic A/B

Date: 2026-09-14. Method: tool-traffic A/B — identical documentation tasks
executed twice, once through manual native file tools (grep / read / glob /
write / edit / bash) and once through the markdown-mcp MCP tools
(`doc_search` / `doc_read` / `doc_outline` / `doc_list` / `doc_write` /
`doc_section_edit` / `doc_delete` / `doc_lint`). Every doc-workflow call's
arguments and result were recorded to payload files; bytes measured with
`wc -c`; tokens estimated as bytes/4 (`tiktoken` is not installed in the
repo venv — stated heuristic, same estimator on both paths).

**Scope limitation, stated prominently:** this measures CONTEXT CONSUMPTION —
the tool traffic (arguments + results) each path pushes into the agent's
context. It does NOT measure the agent's reasoning tokens, planning effort,
or wall-clock time. Absolute token counts are estimates; relative deltas are
robust because the identical estimator prices both paths.

Companion documents: [markdown-mcp-adoption.md](markdown-mcp-adoption.md)
(adoption-gap research; category: plan) and
[../docs-playbook/mcp-docs-workflow.md](../docs-playbook/mcp-docs-workflow.md)
(the standing docs workflow this benchmark informs).

## Executive summary

| Metric | Manual | MCP | Delta |
|---|---|---|---|
| Phase A (read tasks), est. tok | 9258 | 7340 | MCP −20.7% |
| Phase B (write lifecycle + validation), est. tok | 1311 | 1315 | tie (+0.3%) |
| Combined, est. tok | 10569 | 8655 | MCP −18% |
| Call count (A+B) | 12 | 10 | — |
| Retries / CAS failures | 0 / 0 | 0 / 0 | — |

- MCP dominates FINDING tasks: semantic locate −83% (T1), discovery −72% (T4).
- Manual dominates when the file and lexical anchor are already known:
  targeted section read −80% in manual's favor under the protocol's
  outline-based MCP strategy (T2), heading extraction −40% manual (T3).
- Writes were a statistical tie on the small fixture, but the costs scale
  differently: manual edit cost scales with FILE size (mandatory full read
  before edit), MCP edit cost scales with SECTION size (CAS section read).
  On Phase A's 1939-line file, the edit-stage read alone would have been
  ~19k tok manual vs ~0.7k tok MCP.

## Methodology

Protocol: per task, manual path first (native tools only), then MCP path
(`doc_*` tools only); no cross-path tool leakage; bash used only for
measurement bookkeeping (byte counts, sha checks), never for searching.
Manual-path payloads intentionally include the native tools' rendering
overhead (`N: ` line-number prefixes and the read tool's wrapper/footer) —
that overhead is real model-visible traffic. Payloads were saved per call as
`T{n}-{path}-{seq}-{tool}.{args|result}.txt` files; the appendix tables are
the condensed record. Task numbering follows the benchmark protocol; no T6
appears in the recorded artifacts.

| Task | Goal | DONE criterion | Manual calls | MCP calls |
|---|---|---|---|---|
| T1 semantic locate | Find the "LLMMessageHandler must be last" rule | Ordering-rule text in context | 2 (grep + bounded read) | 1 (`doc_search`; snippet sufficed) |
| T2 targeted section read | PK strategy in `docs/sql-portability-guide.md` (1939 lines) | 3-tier PK preference rules in context | 2 (anchor grep + bounded read) | 2 (protocol: `doc_outline` + `doc_read` section) |
| T3 heading structure | Heading outline of `llm/testing.md` | Full real heading set (H1 + 14 sections) | 1 grep (15 real + 9 false positives) | 1 `doc_outline` (0 false positives) |
| T4 discovery | Which docs cover the database schema | Live schema docs + one-liners identified | 2 (glob + README grep, parallel) | 1 `doc_list` |
| T5a create | Create `docs/benchmark-fixture-TMP.md` (1585 B, 3 sections) | Byte-identical file on both paths | 1 write | 1 `doc_write` |
| T5b section edit | Replace Beta-section body (484 → 505 chars) | Identical old→new edit applied, first try | 2 (mandatory full read + edit) | 2 (CAS section read + `doc_section_edit`) |
| T5c delete | Remove the fixture | File gone | 1 `rm` | 1 `doc_delete` |
| T7 validation | Run the docs validator | Validator output in context | 1 `make check-docs` | 1 `doc_lint` |

Fixture for T5: front-matter `category: reference`, H1, three `##` sections
(bodies 513/484/475 chars). Cross-path byte-identity verified via sha256:
both paths' create produced the identical 1585-B file (sha `0d0eaac0…`).

## Results

### Phase A — read tasks

| Task | Manual (est. tok, bytes) | MCP (est. tok, bytes) | Winner |
|---|---|---|---|
| T1 semantic locate | 6814 (27257 B) | 1172 (4690 B) | MCP −83% |
| T2 targeted section read | 1073 (4297 B) | 5344 (21376 B) | manual −80% |
| T3 heading structure | 318 (1272 B) | 527 (2105 B) | manual −40% |
| T4 discovery | 1053 (4211 B) | 297 (1187 B) | MCP −72% |
| **Phase A total** | **9258 (37037 B)** | **7340 (29358 B)** | **MCP −20.7%** |

Phase A call counts: manual 7, MCP 5. Args traffic was negligible on both
paths (<170 tok). T1 manual: a broad-identifier grep returned 88 hits across
26 files (~5.0k tok of mostly-irrelevant context) before a bounded read
brought the rule text in.

### Phase B — write lifecycle + validation

| Stage | Manual (est. tok, bytes) | MCP (est. tok, bytes) | Winner |
|---|---|---|---|
| T5a create | 445 (1780 B) | 583 (2330 B) | manual −138 tok (−24%) |
| T5b section edit | 780 (3121 B) | 654 (2618 B) | MCP −126 tok (−16%) |
| T5c delete | 29 (116 B) | 64 (254 B) | manual −35 tok (−55%) |
| T7 validate | 57 (227 B) | 14 (58 B) | MCP −43 tok (−74%)* |
| **Phase B total** | **1311 (5244 B)** | **1315 (5260 B)** | **tie (MCP +4 tok, +0.3%)** |

\* NOT equivalent work: `make check-docs` validates LINKS (baseline at
benchmark time: 144 files / 2902 links / 0 broken); `doc_lint` validates
STRUCTURE (seven warning rules) and returned `[]`. Complements, not
substitutes — the comparison measures the cost of "run your validator", not
of equivalent work. Phase B call counts: 5 vs 5.

Token cells are independently rounded from byte counts; bytes are the
authoritative totals, so rounded token cells may not sum exactly to rounded
stage totals.

### Combined

Manual 10569 vs MCP 8655 est. tok → MCP −18%. Calls: 12 vs 10. Zero retries
and zero CAS failures on either path; every first call sufficed.

## Structural cost analysis

Where the tokens actually go, per the payload data:

- Manual read results carry `N: ` line-number prefixes plus the tool's
  wrapper/footer — real overhead, measured at ~5–8% of read payloads. MCP
  section reads return the exact section body with no prefixes or wrapper
  (the cleanest result payload in the trial).
- Manual reads scale with the WINDOW (and the mandatory pre-edit read scales
  with the whole FILE); MCP reads are section-scoped, bounded by this repo's
  owner-ratified `section_read_cap = 8192` (`../.markdown-mcp.toml`).
- `doc_search` snippets can finish a task with no follow-up read (T1: one
  call; the 4th-ranked snippet carried the full rule text).
- `doc_outline` is the expensive MCP primitive: cost scales with STRUCTURE
  size regardless of target-section size — ~5.0k tok for ~100 sections on
  the 1939-line guide (96% of T2's MCP total) vs ~0.5k tok for 14 sections
  (T3).
- Edit-args duplication is symmetric by design: the manual edit carried
  oldString + newString (1163 B); `doc_section_edit` carried expected_text +
  new_text (1187 B).
- MCP write results carry unconditional overhead: an inline outline +
  reindex ack (596 B, ~149 tok per write call) — the entire create-stage
  gap (manual write ack: 25 B). It buys slugs/line-ranges and immediate
  index consistency.
- CAS sha chaining: write → edit → delete required zero extra calls — each
  result carries the next token.
- `doc_section_edit` normalized the blank lines around the replaced body
  (2 × `\n` dropped; content byte-identical; post-edit file 1604 B MCP vs
  1606 B manual; index line-ranges shifted; cross-path shas differ).
  Recorded tool behavior — expect whitespace diffs in mixed-workflow
  reviews.
- Index awareness: `rm` leaves the MCP index stale up to the 30 s rescan;
  `doc_delete` removes index rows in-call.

## Qualitative findings

- Search character: `doc_search` is semantic (finds by meaning, scored
  snippets) — but rank separation was weak (all 8 T1 scores within
  0.883–0.896; rank 1 was an adjacent secondary doc, the answer sat at rank
  4). grep is exact-lexical — needs term guessing, but is exhaustive.
- Index scope: the MCP index excludes `docs/archive/` and `docs/other/`
  (the `.markdown-mcp.toml` exclude list). Manual glob saw 19 database
  files (7 live + 12 archived); `doc_list` returned the 7 live ones. Noise
  reduction for live questions, a blind spot for archive-only questions.
- grep noise: T3's heading grep returned 9 false positives (`# comment`
  lines in shell blocks, ~35% of the result); T4's README grep matched
  archived READMEs and truncated one-liners mid-sentence.
- Data-derived verdict: MCP wins at FINDING (semantic locate, discovery);
  manual wins when the target file and lexical anchor are already known and
  the file is large; writes are near-parity on small files, with the MCP
  edit advantage growing with file size.
- Safety: MCP writes are CAS-guarded end-to-end (expected_text /
  expected_sha256 gates) at a cost that rounded to zero extra calls; manual
  writes are last-writer-wins.

## Threats to validity

1. Single run per task — no variance estimate.
2. bytes/4 undercounts dense JSON slightly (ASCII JSON ≈ 3–3.5 B/tok) — MCP
   is marginally worse in reality than scored.
3. T1's 1-call MCP finish was snippet-luck (protocol-conditional follow-up;
   a truncated snippet would have forced a `doc_read`).
4. T2's MCP path was protocol-prescribed (outline → read). A free-strategy
   `doc_search` would likely land the section in a snippet (~1.1k tok) and
   flip T2 to an MCP win — the outline cost is strategy-dependent, not
   inherent.
5. Fixture-size sensitivity: T5b ran on a 16-line fixture; the read-cost
   asymmetry (file-scaled vs section-scaled) grows with file size.
6. No wire-level proxy — payloads are faithful agent transcriptions (Phase A
   hand-transcribed, one corrected path typo; Phase B content-bearing args
   generated programmatically from the canonical fixture sources).

## Usage guidance

Derived only from the measured data:

- Prefer `doc_search` for semantic locate and discovery tasks.
- Prefer `doc_outline` + section-scoped `doc_read` when navigating large
  unfamiliar docs by section — but avoid `doc_outline` on structurally huge
  files when the slug is already known or searchable.
- Use grep/read when the file and the lexical anchor are already known.
- Use `doc_section_edit` for edits — its advantage grows with file size.
- `doc_write` for creation is fine (slight ack overhead buys navigation
  data and immediate index consistency).
- Keep BOTH validators: `make check-docs` (links) AND `doc_lint`
  (structure) — complements, not substitutes.

## Appendix: per-call traffic

Raw payload files (24 Phase A + 20 Phase B payload files — 12 + 10
argument/result pairs — plus the two canonical fixture sources) lived in
`/tmp/mmcp-benchmark/` — ephemeral, not committed. The condensed tables
below are the durable record. Format: args bytes / est. tok | result
bytes / est. tok.

### Phase A per-call detail

| Call | Args (B / tok) | Result (B / tok) |
|---|---|---|
| T1-manual-01 grep `LLMMessageHandler` in `docs/*.md` | 84 / 21 | 19900 / 4975 |
| T1-manual-02 read `docs/llm/handlers.md` offset=460 limit=95 | 127 / 32 | 7146 / 1786 |
| T1-mcp-01 `doc_search` (query: handler-ordering rule) | 176 / 44 | 4514 / 1128 |
| T2-manual-01 grep `PRIMARY KEY` in `sql-portability-guide.md` | 98 / 24 | 933 / 233 |
| T2-manual-02 read `docs/sql-portability-guide.md` offset=900 limit=70 | 136 / 34 | 3130 / 782 |
| T2-mcp-01 `doc_outline` `sql-portability-guide.md` | 101 / 25 | 20067 / 5017 |
| T2-mcp-02 `doc_read` section `recommended-solution-portable-primary-keys` | 162 / 40 | 1046 / 262 |
| T3-manual-01 grep `^#{1,6} ` on `docs/llm/testing.md` | 85 / 21 | 1187 / 297 |
| T3-mcp-01 `doc_outline` `llm/testing.md` | 91 / 23 | 2014 / 504 |
| T4-manual-01 glob `docs/**/*database*` | 56 / 14 | 1835 / 459 |
| T4-manual-02 grep `database` in `docs/**/README.md` | 80 / 20 | 2240 / 560 |
| T4-mcp-01 `doc_list` file_glob `*database*` | 84 / 21 | 1103 / 276 |

### Phase B per-call detail

| Call | Args (B / tok) | Result (B / tok) |
|---|---|---|
| T5a-manual-01 write (full fixture, 1585 B content) | 1755 / 439 | 25 / 6 |
| T5b-manual-01 read full file (required before edit) | 136 / 34 | 1795 / 449 |
| T5b-manual-02 edit (oldString 484 ch + newString 505 ch) | 1163 / 291 | 27 / 7 |
| T5c-manual-01 bash `rm` | 96 / 24 | 20 / 5 |
| T7-manual-01 bash `make check-docs` | 137 / 34 | 90 / 23 |
| T5a-mcp-01 `doc_write` op=write (same content) | 1734 / 434 | 596 / 149 |
| T5b-mcp-01 `doc_read` section `beta-notes` (CAS read) | 130 / 33 | 705 / 176 |
| T5b-mcp-02 `doc_section_edit` op=replace (expected_text 484 ch + new_text 505 ch) | 1187 / 297 | 596 / 149 |
| T5c-mcp-01 `doc_delete` (expected_sha256 from edit result) | 189 / 47 | 65 / 16 |
| T7-mcp-01 `doc_lint` | 55 / 14 | 3 / 1 |
