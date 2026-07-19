# Large Review Campaign Lessons (2026-06-28)

Archived durable notes from [`../teamlead-memory.md`](../teamlead-memory.md) (extracted 2026-07-18). See the live compact memory there for cross-cutting rules and workflow lessons.

- Ran a 78-file review across 6 batches. Key learnings:
  - **Parallel dispatch works**: 6 `code-reviewer` agents dispatched in a single message, all completed independently. Read-only agents have zero conflicts.
  - **Batch size 15-20 files is the sweet spot**: batch at 30 files needed splitting; 4-7 file batches were trivial. 20 files is the practical upper bound.
  - **Integration pass caught cross-batch issues**: documentation in one batch was wrong about code in another batch — no per-batch reviewer could catch this.
  - **Per-batch findings must be verified**: several "IMPORTANT" findings from per-batch reviews were still present in the code — the per-batch review loop had never actually landed the fixes.
  - **Documentation drift is the most common cross-batch failure mode**: docs described `get_summary` tool, `asyncio.run()`, and `initialize(queueService, configManager)` — none matching shipped code.
  - **User triage for recs/nits is efficient**: 22 auto-fix items + 16 user-decision items. User approved ~10 rec fixes and skipped ~6.
  - **7 parallel fix groups dispatched**: no file overlaps → zero conflicts. All 2635+ tests green after each pass.
- The `reviewing-large-changes.md` methodology was updated with these lessons (Section 4.2.1, Section 6 restructured, Section 6.1 added).
