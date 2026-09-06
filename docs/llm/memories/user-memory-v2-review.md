---
category: reference
---

# user-memory-v2 Pre-Merge Review (2026-07-14)

Archived durable notes from [`../teamlead-memory.md`](../teamlead-memory.md) (extracted 2026-07-18). See the live compact memory there for cross-cutting rules and workflow lessons.

## User Memory V2 Pre-Merge Review (2026-07-14, in progress)

Branch `user-memory-v2` (28 commits, base `master` fork-point `6c2c2e9`, fully pushed to origin). **140 files: +29519/−5223** (A=43, M=92, D=5, R=0). One coherent feature: `user_data` → `user_memories` migration + vector search + dedup + condensed-context retrieval + memory compaction + LLM memory tools.
- 4 migrations: 020 (create user_memories), 021 (soft-delete), 022 (drop user_data), 023 (rename memory_injection_enabled → memory_enabled). Tests exist only for 020 + 023.
- Deleted: `internal/bot/common/embedding_utils.py`, `handlers/user_data.py`, `repositories/user_data.py`, `tests/.../test_user_data.py`, `tests/database/repositories/test_chat_settings.py` (confirm coverage relocated, not lost).
- **No requirements*.txt changes** (fastembed used in scripts but no new pinned dep — verify during review).
- `tests/conftest.py` UNCHANGED; two new leaf conftests at `tests/lib/cache/` + `tests/lib/rate_limiter/` (the 2026-07-12 speedup work).
- Cross-cutting present: `internal/database/models.py`, `internal/bot/common/handlers/manager.py` (verify LLMMessageHandler-stays-last invariant), `docs/llm/teamlead-memory.md`. `.opencode/memory.jsonl` is in the diff — EXCLUDE from review (OpenCode's own store, never touch/flag).

Batching plan (10 batches, ≤24 files each): 1 `user-memory-db`(11), 2 `user-memory-handler`(8), 3 `bot-ripple-and-models`(11), 4 `context-and-storage-services`(10), 5 `scripts`(11), 6 `user-memory-and-handler-tests`(17), 7 `db-service-and-speedup-tests`(16), 8 `feature-docs-and-plans`(16), 9 `reference-and-schema-docs`(19), 10 `config-and-agent-tooling`(15). Wave 1 = batches 1-5 (production + scripts, deep/medium); wave 2 = batches 6-10 (tests + docs, light).

---

## user-memory-v2 Pre-Merge Review (2026-07-14)

Large-change review campaign: **140 files / 28 commits** (`user_data`→`user_memories` + vector search + dedup + condensed-context + memory tools). Methodology in [`docs/llm/reviewing-large-changes.md`](../reviewing-large-changes.md) worked end-to-end: 10 batches over 2 parallel waves (5+5 `code-reviewer`), then fix rounds, then Gate 2. All 10 batches returned detailed reports (code-reviewer is reliable at this scale — no empty results). Outcome: 2 Critical + ~15 Important + ~25 Recommend + ~15 Nit found; all Critical/Important/Gate2-blocking fixed + ALL rec/nit (user approved every bucket). Final gates: 3201 passed/0 failed (34s), pyright 0/0/0, 0 broken doc links (1533).

### Durable contracts: condensing, injection, and dedup invariants

**Durable contracts / invariants established:**
- **`CondensingDict.messageCount` counts ALL processed ModelMessage positions** (including `source is None` auxiliary tool-history emissions), NOT just original user/assistant messages. `messageIds` dedupes to unique sources. User decision 2026-07-14 (the test docstring's "after Fix 3 it is 2" was aspirational/wrong; production `generateCondensingDict` counting all is correct).
- **Memory injection is PER-MESSAGE.** Each `EnsuredMessage` resolves its own `metadata["memories"]` compact IDs via `cache.getMemoriesByIds` in `formatForLLM`'s JSON branch (SMART format → JSON for non-assistant). There is NO once-per-context injection and NO `warmMemoriesByIds` (that method was planned in dedup-plan-v2 §5.3 but NEVER shipped — `injectMemories` writes compact IDs to metadata only; the by-id cache populates lazily via cache-aside on the first `formatForLLM` read). The `(50)`/`32` distinction: `MAX_GET_MESSAGES_BATCH=32` (`internal/bot/constants.py`, currently `:253` — line drifts, re-locate by symbol); `memory-reindex-batch-size=50` (regen cron) is a DIFFERENT, correct value — don't conflate.
- **`getThreadByMessageForLLM` dedup invariant (base.py):** the `excludedMemoryIds` accumulator MUST be shared between the first-N (pinned) block and the tail loop. Originally the first-N block passed a throwaway `set()` and never seeded the tail → permanent memories double-injected on condensed threads. Fix (2026-07-14): hoist the declaration before the first-N block, pass it to both, `.update(getMemoryIds())` after each pinned render. The parallel shape in `llm_messages.py` (`handleRandomMessage` tail loop) is clean (seeds up front, no first-N block). Any future refactor that re-splits these paths must re-verify the shared accumulator.
- **`condenseContext` `batchLength` must be floored at 1** (`internal/services/llm/service.py`, currently `:1091-1092` — line drifts, re-locate by symbol): `len(body)//batchesCount` can round to 0 (few token-heavy msgs) → zero-advance infinite loop + unbounded condensing-model spend. `if batchLength < 1: batchLength = 1`; oversized msg then hits the `currentBatchLen==1` skip path.

### Durable contracts: SQL limits, tags, and cold-start design

- **`MAX_SQL_VARIABLES: int = 900`** lives in `internal/database/constants.py` (safe under SQLite's 999). IN()-clause methods (`getMemoriesByIds`, `getChatMessagesByMessageIds`) chunk through it; `getChatMessagesByMessageIds` re-sorts by date across chunks to preserve its ASC contract.
- **`_normalizeTags` (user_memories repo) strips `"` AND `\`** (not `%`/`_` — those are escaped at LIKE-pattern-construction time via `_escapeTagForLike` + `ESCAPE '\'`, NOT in normalization, because `json.dumps` doubles backslashes and would break the JSON round-trip).
- **Chat-embedding backfill cold-start is INTENTIONAL design.** `_trackedChats` (in `ChatSearchHandler`) is an in-memory set populated only by `newMessageHandler`; the backfill cron processes only chats in it. There is deliberately NO startup DB-scan of all chats — this avoids spending backfill work on dead/abandoned chats. A chat with a pre-existing embedding backlog is backfilled only once it receives a new message (proving it's still active). Documented at the `_trackedChats` declaration (`chat_search.py`) and in `docs/llm/memories/chat-history-search.md`. Do NOT re-flag as a limitation or add a startup scan.

### User preferences and process lessons

**User preferences confirmed:**
- **Thorough pre-merge cleanup**: user approved ALL Recommend/Nit buckets (typos, stale comments, defensive hardening, test polish, doc polish, skill refs) — not just Critical/Important. Default to offering the full triage and executing approved buckets.
- Backfill data-loss risk: prod `user_data` is small/already-migrated, so migration backfill crash-mid-flight is low-risk (kept Important, not Critical).

**Process lessons reinforced:**
- **Rename-propagation sweep is ALWAYS needed after a symbol rename.** Renaming `generateCondencingDict`→`generateCondensingDict` (internal-only callers) still left 24 stale docstring/doc/script references across 7 live files + a parallel `condencingDictMap`/`condencedDictMap` variable-name family (23 more refs). Always `rg "<oldSymbol>\b"` excluding `docs/plans/`+`docs/archive/` after any rename, and sweep comments/docstrings/docs (not just code). Leave historical plan/archive docs frozen.
- **Parallel dev agents with disjoint file sets are safe for EDITS**; the contamination is only on `make` verdicts (each agent sees others' intermediate working-tree state). Pattern: dispatch N parallel devs (edits + targeted self-test only, NO `make test/lint/format`), then ONE serial verification agent (`make format && make lint && make test && make check-docs`). Two lint E501s (long inline dict + `# type: ignore` comment that black won't wrap) were the only blockers after an 8-agent round — trivial.
- **`message_metadata.py` etc. need module docstrings** — AGENTS.md hard rule easy to miss on a NEW model file (siblings all have one).
