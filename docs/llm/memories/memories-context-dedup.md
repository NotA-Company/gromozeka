# Memories Context Dedup (ADR-018)

Implementation history and lessons-learned companion for the memories
context-dedup change (ADR-018), shipped 2026-07-11. This eliminated per-message
duplication of user-memories JSON in LLM context by moving resolution from
load-time into `formatForLLM` (lazy) and applying newest→oldest per-context
dedup so each memory renders exactly once per rendered context. The canonical
final-state description lives in [`user-memories.md`](user-memories.md)
§"Render-time resolution (lazy + dedup)" — that doc is spec-style (contract,
call sites, invariants). THIS file captures the planning evolution (v1→v2),
architect-resolved decisions, the 6-phase structure, the go-time user
decisions, the D1 silent-memory-drop lesson, and implementation progress
notes that don't fit in the canonical doc.

## Shipped outcome (DONE 2026-07-11)

Shipped end-to-end via the 6-phase plan below (P1–P6); 3088 tests green at
merge; Gate-2 whole-work review PASSED. Final shape:

- `cache` is a **REQUIRED keyword-only** param on
  `formatForLLM`/`toModelMessage`/`toModelMessageList` (NO default — pyright
  enforces every caller so a forgotten `cache=` is a type error, not a silent
  memory drop). `excludeMemoryIds` is keyword-only with `= None` default
  (body normalises to `set()`) — see the [CORRECTION] below.

  > **[CORRECTION]** The original go-time decision (and several historical
  > sections below: "Final user decisions" §1, "Phase 2 DONE", "CRITICAL
  > lesson — D1") describe BOTH `cache` AND `excludeMemoryIds` as required
  > keyword-only with no defaults. That held at ship time, but
  > `excludeMemoryIds` later regained an `= None` default (current signature:
  `excludeMemoryIds: Optional[Set[str]] = None`, normalised to `set()` in the
  > body). Only `cache` remains truly required. Consequence for the D1 lesson:
  > pyright STILL catches a forgotten `cache=` (the actual silent-memory-drop
  > vector), but does NOT catch a forgotten `excludeMemoryIds=` — the latter
  > just disables dedup for that caller (renders all memories), a much milder
  > failure mode that was apparently deemed acceptable when the default was
  > re-added. The same staleness exists in ADR-018 in
  > [`../architecture.md`](../architecture.md) §"Components" / §"Consequences
  > → Signature enforcement" (out of scope for this memory file).
- `computeMemoryExcludes` shipped as a module-level fn in `base.py` for
  reuse/clarity (later DELETED post-shipping — see "Post-shipping revisions").
- `setUserMemories` was **REMOVED outright** (not repurposed) — `injectMemories`
  writes compact IDs to `metadata["memories"]` directly. (`warmMemoriesByIds`,
  planned in v2 §5.3, was NOT shipped; the by-id cache populates lazily via
  cache-aside on the first `formatForLLM` call.)
- Decision record: ADR-018 in [`../architecture.md`](../architecture.md).

### Gate-2 follow-up corrections (also DONE)

- **BLOCKER doc false-claim:** ADR-018 Consequences + [`../handlers.md`](../handlers.md)
  had claimed a render-method AST guard exists — it does NOT. Check-1 was
  removed, not repurposed. Real enforcement is pyright on the
  required-keyword-only signature.
- `warmMemoriesByIds` now strips `score` too (was leaking cosine-sim into the
  prompt on cache HITs in relevant-retrieval mode — minor behavior change:
  current message's rendered memories no longer include `score`). Signature
  made `*, chatId` keyword-only. Added `cache=None` omission test. Fixed stale
  `resolveMemories` docstrings in
  [`/scripts/clear_old_format_memories.py`](/scripts/clear_old_format_memories.py).

  > **[CORRECTION]** The above Gate-2 follow-up item described
  > `warmMemoriesByIds` as shipped. It was NOT shipped: `warmMemoriesByIds`
  > (v2 §5.3) was planned but never implemented. `injectMemories` writes
  > compact IDs into `metadata["memories"]` only; `formatForLLM`'s first call
  > cache-misses into `getMemoriesByIds` (one indexed-PK batch query per
  > inbound message on a cold cache).

### Post-shipping user revisions (same day)

User hand-rolled the dedup INLINE and dropped the helper:

1. `getThreadByMessageForLLM` **REWRITTEN** — tail deduped newest→oldest inline
   (accumulate exclude-set); `keepFirstN` (root) message **EXEMPT from dedup**
   (`excludeMemoryIds=set()`) by DELIBERATE design choice for code simplicity —
   a memory shared root↔tail may appear twice in condensed threads (accepted
   trade-off; common non-condensed case unaffected).
2. `handleRandomMessage` non-reply dedup **ADDED inline** (history+current,
   newest→oldest; current message seeds `seen`) — verified correct by review.
3. `computeMemoryExcludes` module fn **DELETED** (zero prod callers); its 2
   test classes (`TestComputeMemoryExcludes`, `TestDedupIndexAlignment`)
   DELETED — the dedup algorithm now has NO direct unit test (exercised only
   via handler paths; `getThreadByMessageForLLM` is mocked in handler tests —
   known coverage gap).
4. `cache=` render-call gate **RESTORED** to pre-dedup behavior:
   `cache=self.cache if needMemories else None` (memories render only when
   injection enabled for the chat).
5. `RANDOM_ANSWER_CONTEXT_LENGTH` 50→64 (unrelated tuning).
6. `warmMemoriesByIds` (planned in v2 §5.3) was **NOT shipped**.
   `injectMemories` writes compact IDs only; `formatForLLM`'s first call
   cache-misses into `getMemoriesByIds` (one indexed-PK batch query per
   inbound message on a cold cache). The "Gate-2 follow-up" and "Phase 1/2
   DONE" notes above that treat `warmMemoriesByIds` as shipped are stale and
   corrected in place.

Docs (ADR-018, [`../handlers.md`](../handlers.md),
[`user-memories.md`](user-memories.md)) updated for inline dedup + root
exemption + cache gate. Final: **3087 tests green**, lint clean. NOTE: the
dedup contract is now "each memory once at latest occurrence in the
non-condensed path; condensed-replay root is exempt."

### Follow-up: per-ID relevance scores on the compact form

A later change extended the compact per-message form to OPTIONALLY carry
per-ID semantic-relevance scores. `CompactMemoryIdsDict` gained a
`NotRequired` `shortTermScores: dict[str, float]` (mapping `memory_id ->
score`); `MessagePreprocessorHandler.injectMemories` populates it in
semantic-search mode only, and `EnsuredMessage.formatForLLM` merges the
score into each resolved short-term entry at render time (via a shallow
copy so the shared by-id cache is NOT mutated). Permanent entries and
latest-mode (`getLatestMemories`) ephemeral entries never carry a score.
No new resolution or dedup logic was needed — the score rides the same
compact-metadata → `formatForLLM` path this change established. See
[`user-memories.md`](user-memories.md) §"Semantic-relevance score for
short-term memories" for the canonical contract.

## Historical plan (v1)

Plan to eliminate per-message duplication of user-memories JSON in LLM context
(today each `EnsuredMessage` renders its full `{permanent, shortTerm}` block
verbatim → ~N× repetition of permanent memories across a thread; storage
already compacted to IDs in `metadata["memories"]`, but rendered output still
repeats full content). Plan doc:
[`../../archive/plans/memories-context-dedup-plan-v1.md`](../../archive/plans/memories-context-dedup-plan-v1.md).
Locked design decisions (agreed with user):

- **Drop `EnsuredMessage.userMemories` field** (attribute + `__slots__`).
  Canonical ID source = `metadata["memories"]` (`CompactMemoryIdsDict` =
  `{permanentIds, shortTermIds}`), which is already the persisted truth.
- **Remove `resolveMemories`** — resolution moves from load-time into
  `formatForLLM`. `fromDBChatMessage` no longer eagerly resolves (metadata IDs
  come straight from the DB row).
- **Dedup direction = newest→oldest.** Newest (current) message renders FULL
  set; each older message renders only IDs not covered by any newer message;
  each memory appears once at its latest occurrence. Algorithm in
  `getThreadByMessageForLLM`: walk rendered list newest→oldest,
  `excludes[i] = getMemoryIds(i) & seen; seen |= getMemoryIds(i)`; format each
  with `excludeMemoryIds=excludes[i]`; assemble oldest→newest.
- **`formatForLLM` new params:** `cache: Optional[CacheService] = None`,
  `excludeMemoryIds: Optional[Set[str]] = None`. JSON branch reads IDs from
  metadata, subtracts exclude-set, resolves survivors via
  `cache.getMemoriesByIds`, renders into `"userMemories"` key (omit if none;
  IDs never leak to LLM). `cache=None` → omit memories (non-chat paths).
  `toModelMessage`/`toModelMessageList` thread both params.
- **New helper `getMemoryIds() -> Set[str]`** on `EnsuredMessage`: merged union
  of both cohorts from metadata.
- **`setUserMemories`** repurposed to write IDs to metadata only (rename to
  `setMemoryIds` or fold into caller); sole caller =
  `MessagePreprocessorHandler.injectMemories`.
- **`injectMemories`** still fetches to discover applicable memories, stores
  only IDs (content discarded).
- **TEXT branch** = documented no-op (memories not rendered; TEXT used for bot
  messages, which have no user memory).
- **Condense (`keepFirstN`) branch:** dedup runs only over
  individually-rendered messages; condensed messages neither contribute to
  `seen` nor get formatted (consistent with today).
- **Known wrinkle (non-blocking):** current-message double-fetch —
  `injectMemories` fetches full rows then discards content; `formatForLLM`
  re-resolves. Historical = net-zero (`resolveMemories` moved load→format).
  Current message = potential 2nd fetch. Fix options: warm by-id cache in
  `injectMemories` (optimal) OR accept one cheap indexed-PK lookup. Verify
  whether `cache.getMemoriesByIds` is write-through backed.
- **Out of scope:** TEXT-branch rendering; D3 tool gating (read-side change);
  storage compaction (already done).

## v2 detailed plan + architect review (2026-07-11)

Detailed plan:
[`../../archive/plans/memories-context-dedup-plan-v2.md`](../../archive/plans/memories-context-dedup-plan-v2.md)
— implementation-ready after architect review. Verified findings (code-analyst):
`resolveMemories` has TWO callers (`fromDBChatMessage` + the `handleMention`
text-reply bypass, which sets `metadata` directly then resolves before
`toModelMessage`); `setUserMemories` sole prod caller =
[`/internal/bot/common/handlers/message_preprocessor.py`](/internal/bot/common/handlers/message_preprocessor.py);
`fromDBChatMessage(cls, data, db, *, forceGetAllMedia=False, injectMemories,
cache=None)` — `injectMemories` gates ONLY the `resolveMemories` call (metadata
always loaded from DB JSON); NO `fromERootMessage` method (`eRootMessage` is a
local var); `cache.getMemoriesByIds` is cache-aside under the `self.memories`
namespace, MEMORY_ONLY, NOT populated by `getChatUserPermanentMemories`
(different namespace `self.chatUsers`) nor by `getLatestMemories`/`searchMemories`
(direct repo calls) → current-message resolution at format time IS a redundant
DB batch query (historical = net-zero); `getThreadByMessageForLLM`
builds-and-formats INLINE oldest-first (3 render sites); condense-replay
`keepFirstN=1`+tail are individually formatted, condensed middle dropped (no
memory blocks); `metadata["memories"]` legacy content-form may appear in old DB
rows (cleanup script exists) → `formatForLLM` must defensively skip when
compact keys absent.

### Architect-resolved decisions (v2 §11)

- **(a) BUILD-then-DEDUP-then-FORMAT restructure** of
  `getThreadByMessageForLLM` (reuses `getMemoryIds`, avoids duplicating
  metadata-shape logic — more invasive than v1 implied).
- **(b) REMOVE `injectMemories` param outright** (Phase 4, after callers
  updated).
- **(c) Cache-warm via a NEW `CacheService.warmMemoriesByIds(entries:
  Sequence[SingleMemoryDict]) -> None` method** (encapsulates the
  `keepId=False` shape invariant in the cache layer — do NOT reach into
  `self.cache.memories` LRU directly from a handler).
- **(d) `handleRandomMessage` NON-reply branch:** dedup DEFERRED but basic
  RENDERING in-scope (`cache=self.cache` now).
- **(e) Reusable `computeMemoryExcludes` helper** = module-level fn in
  `base.py` (pure, no circular-import risk).

## CRITICAL lesson — D1 (silent memory drops)

Moving resolution from load-time into `formatForLLM` means EVERY path that
previously relied on `injectMemories=True` resolution must now pass
`cache=self.cache` at the format call — otherwise memories **SILENTLY vanish**.
The v1/v2-draft wrongly assumed all non-chat callers were "unaffected" by the
signature defaults. **6 call sites** actually need `cache=self.cache` wired:

- [`/internal/bot/common/handlers/llm_messages.py`](/internal/bot/common/handlers/llm_messages.py)`:602` (handleReply fallback)
- `llm_messages.py:750` / `:759` (handleMention)
- `llm_messages.py:893` / `:936` (handleRandomMessage non-reply)
- [`/internal/bot/common/handlers/media.py`](/internal/bot/common/handlers/media.py)`:657` (draw)

**Generalizable gotcha for any "move resolution to render-time" refactor:**
audit ALL consumers of the old eager-resolution trigger, not just the thread
path. This is exactly why the final signature made `cache`/`excludeMemoryIds`
REQUIRED keyword-only with no defaults — pyright then catches every missed
call site at type-check time, making the D1 bug class impossible by
construction.

## 6-phase structure

Each phase independently green (architect-fixed; the original 7-phase draft
left the codebase broken mid-way). **Invariants to preserve throughout all
phases:**

- `formatForLLM` must NOT mutate `metadata["memories"]` (condense persists
  `eRootMessage.metadata` to DB — corruption risk).
- `id` never emitted to LLM.
- Condensed entries MUST NOT contribute to the dedup `seen` set.

Phase breakdown:

- **P1** — additive-only (new params w/ defaults, `getMemoryIds`,
  `computeMemoryExcludes`, `warmMemoriesByIds` — no removals).
- **P2** — wire `getThreadByMessageForLLM` dedup + `injectMemories` cache-warm
  (add `injectMemories=False` default for transitional compat).
- **P3** — wire 6 handler/media paths with `cache=self.cache`.
- **P4** — atomically remove dead code (`fromDBChatMessage` sig,
  `resolveMemories`, `userMemories` field+slot) + update remaining callers.
- **P5** — test updates (large blast radius —
  [`/tests/bot/models/test_ensured_message.py`](/tests/bot/models/test_ensured_message.py)/
  [`/tests/bot/common/handlers/test_message_preprocessor.py`](/tests/bot/common/handlers/test_message_preprocessor.py)/
  [`/tests/bot/common/handlers/test_llm_messages.py`](/tests/bot/common/handlers/test_llm_messages.py) all assert on
  `msg.userMemories`; AST guard
  [`/tests/test_memory_resolution_coverage.py`](/tests/test_memory_resolution_coverage.py)).
- **P6** — doc sync.

## Final user decisions (2026-07-11, amend v2 §5.2/§5.4/§7)

Three decisions made at go-time; v2 plan doc still reflects the PRE-decision
state on these points (v2 says params have defaults; v2 uses pre-scan dedup)
and is **SUPERSEDED here**:

1. **`cache` and `excludeMemoryIds` are REQUIRED params (no `=None` defaults)**
   on `formatForLLM`/`toModelMessage`/`toModelMessageList`. Rationale: pyright
   then flags every call site that forgets them, making the D1
   silent-memory-drop class of bug impossible by construction. Consequence:
   the signature change can NOT be purely additive — P2 must update ALL ~16
   callers atomically (linter-guided). Non-chat/TEXT callers pass
   `cache=None, excludeMemoryIds=set()` explicitly.
2. **Dedup = build `EnsuredMessage`s, format newest→oldest with inline
   seen-set, then REVERSE the result to oldest→newest** (reinsert condense
   summaries at their chronological slot). This supersedes v2's separate
   `computeMemoryExcludes` pre-scan helper — the seen-set logic is inline in
   the reversed loop (3 lines); no separate helper unless P3 finds reuse
   value. `getMemoryIds()` still needed.
3. **`handleRandomMessage` non-reply DEDUP deferred** (rendering still
   in-scope, `cache=self.cache`) — confirmed.

## Implementation progress (2026-07-11)

### Phase 1 DONE (green 3110)

- `EnsuredMessage.getMemoryIds()` at
  [`/internal/bot/models/ensured_message.py`](/internal/bot/models/ensured_message.py)`:983`
  — defensive `or []` for None-valued compact keys per Gate-1 fix +
  `TestGetMemoryIds.test_getMemoryIds_noneValuedCompactKeys`.
- `CacheService.warmMemoriesByIds(entries, chatId)` was planned for
  [`/internal/services/cache/service.py`](/internal/services/cache/service.py)
  (~`:1048`, a section comment — not the method), but was **NOT shipped**.
  `injectMemories` writes compact IDs only; render-time resolution pays one
  indexed-PK batch query per inbound message on a cold cache.

### Phase 2 DONE (green 3110, Gate-1 clean no blockers)

- `formatForLLM`/`toModelMessage`/`toModelMessageList` now take REQUIRED
  `cache: Optional["CacheService"]` + `excludeMemoryIds: Set[str]` keyword-only
  (NO defaults — pyright enforces all callers; this immediately caught
  [`/scripts/reproduce_llm_dialog.py`](/scripts/reproduce_llm_dialog.py)`:395`
  which the investigation missed).
- `formatForLLM` resolves on-demand from `metadata["memories"]` via
  `cache.getMemoriesByIds(permanentIds+shortTermIds, chatId=self.recipient.id)`,
  filters each cohort by `excludeMemoryIds` BEFORE resolving, omits
  `userMemories` key when cache is None / no IDs survive / nothing resolves;
  builds LOCAL dict (non-mutation invariant verified); `id` never emitted.
- Both `resolveMemories` CALLS removed (`fromDBChatMessage`, `handleMention`
  `:725`) but METHOD kept (Phase 4).
- `injectMemories` writes compact IDs into `metadata["memories"]` directly
  (no `warmMemoriesByIds` call — that method was never shipped).
- NOTE: `formatForLLM` got `*` after `db` (ALL params keyword-only) but
  `toModelMessage`/`toModelMessageList` got `*` only before the new params —
  INCONSISTENCY, normalize in Phase 4.

### Phase 5 MUST-DO items (deferred from Gate-1 Phase-2 review — ADDRESSED POST-SHIP)

> **[UPDATE 2026-07-18 audit]** All four items below are now DONE or MOOT.
> Verified against current code (see annotations). The original list is
> retained as a historical record of the Gate-1 review backlog.

1. [`/tests/test_memory_resolution_coverage.py`](/tests/test_memory_resolution_coverage.py)
   AST guard Check-1 now checks the DEAD `fromDBChatMessage cache=` invariant
   → gives FALSE CONFIDENCE on the exact silent-memory-drop regression class;
   REPURPOSE it to scan the render methods
   (`toModelMessage`/`toModelMessageList`/`formatForLLM`) for required
   `cache=`/`excludeMemoryIds=` kwargs.
   **[DONE-MOOT]** Check-1 was REMOVED entirely (not repurposed); only
   Check-2 (the `setUserMemories` metadata-bypass ban) remains, kept as a
   vacuous regression guard. The test module's docstring documents this
   explicitly. Note: with `excludeMemoryIds` having regained an `= None`
   default (see [CORRECTION] under "Shipped outcome" above), a Check-1-style
   AST scan for required `excludeMemoryIds=` would no longer be valid; only
   `cache=` is still required-keyword-only.
2. Rename/delete `test_fromDBChatMessage_withCache_resolvesMemoriesInternally`
   (name contradicts its first assertion `msg.userMemories is None`).
   **[DONE]** Test no longer exists in
   `tests/bot/models/test_ensured_message.py` (renamed/removed).
3. Drop vestigial `await newMsg.resolveMemories(cache)` calls in
   `TestFormatForLLMMemoriesResolution` parity tests (now no-ops).
   **[DONE]** `resolveMemories` is gone from the entire codebase (verified
   via repo-wide grep — zero `.py` matches outside docstrings/comments). The
   test class itself was renamed `TestFormatForLLMMemoryResolution`
   ("Memories" → "Memory").
4. Document stale-ID behavioral delta: when all referenced IDs fail to
   resolve, `userMemories` key is now OMITTED (previously emitted empty-cohort
   dict `{"permanent":[],"shortTerm":[]}`).
   **[DONE]** Covered by `TestFormatForLLMMemoryResolution.test_*` in
   `tests/bot/models/test_ensured_message.py` (explicit assertions that
   `"userMemories" not in parsed` when all IDs resolve to `None`); also
   documented in ADR-018 §"Consequences → Stale-ID behavioral delta" in
   [`../architecture.md`](../architecture.md).

## Cross-references

- [`user-memories.md`](user-memories.md) §"Render-time resolution (lazy + dedup)"
  — canonical final-state description (contract, call sites, invariants, the
  by-id `MEMORIES` cache, the root-exemption trade-off).
- [`../architecture.md`](../architecture.md) ADR-018 — architecture decision
  record for the context-deduplication change.
- [`../../archive/plans/memories-context-dedup-plan-v1.md`](../../archive/plans/memories-context-dedup-plan-v1.md)
  — v1 plan doc (historical, pre-architect-review).
- [`../../archive/plans/memories-context-dedup-plan-v2.md`](../../archive/plans/memories-context-dedup-plan-v2.md)
  — v2 detailed plan + architect review (historical; §5.2/§5.4/§7 SUPERSEDED
  by the final user decisions above).
