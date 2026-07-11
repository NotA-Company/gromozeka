# Memories Context Deduplication Plan v1

- Status: **IMPLEMENTED** (2026-07-11) — shipped via the 6-phase plan (P1–P6, 3087 tests green). See ADR-018 in `docs/llm/architecture.md` for the decision record; `docs/llm/memories/user-memories.md` "Render-time resolution (lazy + dedup)" for the canonical summary. The decisions below are the historical plan; note `setUserMemories` was removed outright (not repurposed) and `cache`/`excludeMemoryIds` ended up REQUIRED keyword-only (no defaults).
- Date: 2026-07-11
- Related: `docs/llm/architecture.md` (memory-duplication ADR), `docs/llm/memories/user-memories.md`

## Goal

Eliminate per-message duplication of user-memories JSON in the LLM context. Today each
`EnsuredMessage` in a thread renders its full `{permanent, shortTerm}` memory block verbatim
in `formatForLLM`, causing ~N× repetition of permanent memories across a thread (documented
as ~75 KB of duplicated JSON for a 50-message thread). Storage was already compacted to IDs
in `metadata["memories"]`, but the *rendered* output still repeats full content per message.

Target: each memory appears exactly once in the rendered context.

## Locked decisions

1. **Drop the `EnsuredMessage.userMemories` field** (attribute + `__slots__` entry). Canonical
   ID source = `metadata["memories"]` (`CompactMemoryIdsDict`: `{permanentIds, shortTermIds}`).
2. **Remove `resolveMemories`** — memory resolution moves from load-time into `formatForLLM`.
3. **Dedup direction: newest → oldest.** The newest (current) message renders its FULL memory
   set; each older message renders only memories not already shown by any newer message. Each
   memory appears once, at its latest occurrence.
4. **`formatForLLM` gains `cache` and `excludeMemoryIds` params.**
5. TEXT branch is a documented no-op (memories are not rendered in TEXT; TEXT is used for bot
   messages, which carry no user memory).

## Design

### `EnsuredMessage` changes (`internal/bot/models/ensured_message.py`)

- Remove the `userMemories` attribute and its `__slots__` entry.
- Remove the `resolveMemories` method (resolution moves to `formatForLLM`).
- `setUserMemories` is repurposed to write only IDs into `metadata["memories"]` (consider
  renaming to `setMemoryIds`, or folding the write into the caller). Sole caller today:
  `MessagePreprocessorHandler.injectMemories`.
- New helper:
  ```python
  def getMemoryIds(self) -> Set[str]:
      """Return the set of all memory IDs (permanent + shortTerm) carried by this message.
      Reads from ``metadata["memories"]``. Empty set when no memories are attached.
      """
  ```
  Returns the union of `metadata["memories"]["permanentIds"]` and `["shortTermIds"]`.

### `formatForLLM` and wrappers

New signature (existing kwargs preserved):
```python
async def formatForLLM(
    self,
    db,
    *,
    format: LLMMessageFormat = LLMMessageFormat.JSON,
    replaceMessageText: Optional[str] = None,
    stripAtsign: bool = False,
    outputFormat: OutputFormat = OutputFormat.MARKDOWN,
    useSingleMedia: bool = True,
    cache: Optional["CacheService"] = None,
    excludeMemoryIds: Optional[Set[str]] = None,
) -> str:
```

JSON-branch memory rendering:
1. Read this message's IDs from `metadata["memories"]` (both cohorts).
2. Subtract `excludeMemoryIds` (if provided).
3. Resolve survivors via `cache.getMemoriesByIds(...)` — only when `cache is not None`.
4. Render into the existing `"userMemories"` JSON key; omit the key entirely when no memories
   survive. IDs are never emitted to the LLM (the `id` field stays stripped from output, as
   today).
5. `cache is None` → omit memories (safe default; non-chat paths).

`toModelMessage` and `toModelMessageList` thread `cache` and `excludeMemoryIds` through to
`formatForLLM`.

TEXT branch: no-op for memories (unchanged).

### Dedup loop in `BaseBotHandler.getThreadByMessageForLLM`

After building the list of `EnsuredMessage`s for the thread (before formatting):
```python
seen: Set[str] = set()
excludes: List[Set[str]] = [set() for _ in range(len(msgs))]
for i in range(len(msgs) - 1, -1, -1):   # newest -> oldest
    ids = msgs[i].getMemoryIds()
    excludes[i] = ids & seen
    seen |= ids
# format each message with excludeMemoryIds=excludes[i]; assemble oldest -> newest for the LLM
```
- Newest message (last index): `seen` is empty → `excludes` empty → renders ALL its memories.
- Each older message: renders only IDs not present in any newer message.
- Standalone (no-root) single-message branch: format with `excludeMemoryIds=None` (no dedup).
- Condense (`keepFirstN`) branch: dedup runs only over messages that are individually rendered;
  condensed/summarized messages neither contribute to `seen` nor get formatted individually
  (consistent with today — their memory blocks are already dropped in condense). Verify the
  condense flow concretely during implementation.

### `MessagePreprocessorHandler.injectMemories`

Still fetches memories to determine WHICH apply (`getChatUserPermanentMemories` cache hit +
`getLatestMemories` / `searchMemories`). Now stores only the IDs into `metadata["memories"]`;
the fetched content is discarded (resolution is deferred to `formatForLLM`).

## Consideration: current-message DB cost

`injectMemories` fetches full rows (with content) to discover applicable memories, then stores
only IDs. At format time `formatForLLM` re-resolves those IDs via `cache.getMemoriesByIds`.

- **Historical messages:** net-zero. `resolveMemories` used to run at load; now the equivalent
  resolution runs at format. Same number of lookups, just relocated.
- **Current inbound message:** potential second fetch of data `injectMemories` just loaded.

Options (pick at implementation):
- Warm the by-id cache inside `injectMemories` so format-time resolution is a cache hit (optimal).
- Accept one extra indexed-PK lookup per inbound message (cheap).

Verify whether `cache.getMemoriesByIds` is backed by a write-through cache.

## Out of scope

- TEXT-branch memory rendering (bot messages have no user memory).
- D3 `delete_memory` tool gating (unaffected — this is read-side formatting, not tool registration).
- Storage compaction (already done — `metadata["memories"]` already stores compact IDs).

## Tests to add / update

- `formatForLLM` renders all memories when `excludeMemoryIds=None`.
- `formatForLLM` omits IDs present in `excludeMemoryIds`; omits the key entirely when all excluded.
- `formatForLLM` omits memories when `cache=None`.
- `getMemoryIds` returns the merged permanent+shortTerm set; empty when metadata has no memories.
- `getThreadByMessageForLLM`: newest message renders full set; older messages render only
  not-already-seen IDs; each memory appears exactly once across the whole rendered thread.
- Regression: `resolveMemories` removed — update/remove tests referencing it; `fromDBChatMessage`
  no longer eagerly resolves memories.
- `setUserMemories`/`setMemoryIds` writes IDs into `metadata["memories"]` only.

## Doc surfaces to sync (post-implementation, via the `update-project-docs` skill)

- `docs/llm/architecture.md` — the memory-duplication ADR (~75 KB figure): update to reflect
  once-per-context rendering.
- `internal/bot/models/message_metadata.py` — docstrings for the memories shape / `getMemoryIds`.
- `docs/llm/memories/user-memories.md` — injection/render section.
- `docs/database-schema-llm.md` — only if the metadata shape is described there (no shape change
  expected; IDs already persisted).
