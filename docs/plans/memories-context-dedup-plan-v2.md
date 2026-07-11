# Memories Context Deduplication Plan v2

- **Status:** **IMPLEMENTED** (2026-07-11) — shipped via the 6-phase plan (P1–P6, 3087 tests green). Decision record: ADR-018 in `docs/llm/architecture.md`; canonical summary: `docs/llm/memories/user-memories.md` "Render-time resolution (lazy + dedup)". Final-actual deltas from this plan body: `setUserMemories` was removed outright (not repurposed); `cache`/`excludeMemoryIds` are REQUIRED keyword-only (no defaults — pyright-enforced); `computeMemoryExcludes` was later inlined at each call site and the helper removed from `base.py` (see ADR-018).
- **Date:** 2026-07-11
- **Related:**
  - v1 (brief): [`docs/plans/memories-context-dedup-plan-v1.md`](memories-context-dedup-plan-v1.md)
  - Memory-duplication ADR: [`docs/llm/architecture.md`](../llm/architecture.md)
  - Memories doc: [`docs/llm/memories/user-memories.md`](../llm/memories/user-memories.md)

> **Supersedes / extends v1.** This document is a strict superset of v1. It
> preserves every v1 decision and adds: exact file:line anchors, verbatim current
> + new signatures for every changed method, the `handleMention` text-reply bypass
> handling (a second `resolveMemories` caller v1 missed), the
> `fromDBChatMessage.injectMemories` removal, a by-id cache-warm step to avoid a
> redundant DB hit, a pre-scan newest→oldest dedup algorithm, a reusable-helper
> extraction, a phased implementation breakdown, and a full test-update plan.
> Where v1 and this document agree, this document is authoritative on detail.

## 1. Goal

Eliminate per-message duplication of user-memories JSON in the LLM context. Each
`EnsuredMessage` in a thread currently renders its full memory block verbatim in
`formatForLLM`, causing ~N× repetition of permanent memories across a thread
(~75 KB of duplicated JSON for a 50-message thread). Storage was already
compacted to IDs in `metadata["memories"]`, but the *rendered* output still
repeats full content per message.

**Target invariant:** each memory appears exactly once in the rendered context,
at its latest occurrence (newest message renders full set; older messages render
only IDs not already shown by any newer message).

## 2. Verified findings summary (ground truth)

These came from a read-only code investigation. Cite them; do not re-derive.

| ID | Finding | Anchor |
|----|---------|--------|
| **F1** | `EnsuredMessage.userMemories` field declared `:460`, `__slots__` entry `"userMemories"` at `:374`, type `Optional[UserMemoriesDict]`. Prod reads: `formatForLLM` JSON branch `:1202`, `__str__` `:1359`, `resolveMemories` early-return guard `:960`. Prod writes: `setUserMemories` `:917`, `resolveMemories` `:981`. `db.userMemories` (~30 hits) is the Database repo accessor — UNRELATED. `lib/` has zero hits. | `internal/bot/models/ensured_message.py` |
| **F1t** | Test reads of `msg.userMemories`: `tests/bot/models/test_ensured_message.py:181-186,207-210,234-236,255-256,267,276,305-306,323-324,336-338,452,458,568-569,584`; `tests/bot/common/handlers/test_message_preprocessor.py:911-920,985-989,1017-1020`; `tests/bot/common/handlers/test_llm_messages.py:1402-1406`. | tests/ |
| **F2** | `resolveMemories` has **two** callers: (1) `fromDBChatMessage` `:889` (`if injectMemories and cache is not None: await ensuredMessage.resolveMemories(cache)`); (2) `handleMention` text-reply bypass `llm_messages.py:725` (builds `ensuredReply.metadata` directly from DB JSON at `:721`, bypassing `fromDBChatMessage`, then `resolveMemories(self.cache)` before `toModelMessage` at `:728`). | ensured_message / llm_messages |
| **F3** | `setUserMemories` sole production caller: `message_preprocessor.py:133` (`injectMemories`). Test callers in `test_ensured_message.py:170,197,482` are unit tests of the method itself. | message_preprocessor |
| **F4** | `fromDBChatMessage` signature `:789-798` (see §5.1). `injectMemories` gates ONLY the `resolveMemories` call at `:888-889`. When `injectMemories=True` and `cache=None`: `resolveMemories` not called, `userMemories` stays `None`, but `metadata["memories"]` STILL carries compact IDs (loaded from `data["metadata"]` JSON at `:834`). Metadata is ALWAYS loaded regardless of `injectMemories`. Factory inventory: `__init__` `:383`, `fromMaxMessage` `:470`, `fromTelegramMessage` `:567`, `fromDBChatMessage` `:789`. **No** `fromERootMessage` (it's a local var). Only `fromDBChatMessage` takes `injectMemories`/`cache`. | ensured_message |
| **F5** | `CacheService.getMemoriesByIds` (`service.py:973-1046`): LRU namespace `self.memories` (`:376`, `CacheNamespace.MEMORIES`), `MEMORY_ONLY` persistence. On miss → `db.userMemories.getMemoriesByIds(...)`, converts via `convertDBMemoryToSingleMemoryDict` (default `keepId=False`), caches results including `None` (negative caching). `getChatUserPermanentMemories` caches under `self.chatUsers[userKey]["permanentMemories"][threadId]` — a DIFFERENT namespace. `getLatestMemories`/`searchMemories` call the repo DIRECTLY (bypass cache service). So `injectMemories`' fetches do NOT populate the by-id cache. CONSEQUENCE: when `formatForLLM` calls `cache.getMemoriesByIds(...)`, the current inbound message's content is a CACHE MISS → redundant fresh DB batch query. | cache/service.py |
| **F6** | `getThreadByMessageForLLM` (`base.py:710-900`) builds and formats INLINE (each `EnsuredMessage` is `fromDBChatMessage`'d then immediately `toModelMessageList`'d in the same iteration). Assembly OLDEST-FIRST: `dbMessageList` from `getChatMessagesByRootId` (`:769-773`) is chronological oldest-first; loop extends `ret` in order. THREE render sites: `:762` Branch A (standalone, `root_message_id is None`), `:794` condense-replay keepFirstN loop (`keepFirstN=1`, `:780`), `:824` main loop (tail messages). Condense-replay (`:805-817`): each condensed entry → `ModelMessage(role="user", content=...)` (plain text); summarized DB messages sliced off `dbMessageList` (`:817`), never become `EnsuredMessage`s. Fresh condensing (`:836-900`): formatted `ret` → `llmService.condenseContext`; plain-text summary `ModelMessage`s; persisted to `eRootMessage.metadata["condensedThread"]`. `eRootMessage` (`:783`) built via `fromDBChatMessage` but NEVER formatted — only reads/persists condense cache. | base.py |
| **F7** | Condensed/summarized messages have NO memory blocks (dropped). Only keepFirstN + tail messages render memories. Dedup operates only over keepFirstN + tail. | base.py |
| **F8** | All `formatForLLM`/`toModelMessage`/`toModelMessageList` call sites. Chat-context (need cache+excludeMemoryIds): `base.py:762,794,824`. Non-chat / single-message: `llm_messages.py:601,602` (handleReply fallback, 2 single msgs), `:728` (handleMention text-reply bypass — MUST pass `cache=self.cache`), `:750,759` (handleMention single msgs), `:893` (handleRandomMessage non-reply separate loop), `:936` (handleRandomMessage current msg), `media.py:657`, `summarization.py:216`, `chat_search.py:448,707`, `user_memories.py:1499`, `message_preprocessor.py:193` (embedding TEXT). Internal delegation: `ensured_message.py:1315` (`toModelMessage` → `formatForLLM`). Tests: `test_ensured_message.py:87,114,429,430,459,490,491`; `test_memory_resolution_coverage.py:522,540,556,592,612,616,629,631,649`; `test_llm_messages.py:598,657,1376`. `[architect review: NOT all non-chat callers are backward-compatible — those that previously passed injectMemories=True to fromDBChatMessage MUST now pass cache=self.cache at the format call (see corrected §5.6). Only callers that used injectMemories=False or TEXT format are truly unaffected.]` | various |
| **F9** | Handler context-assembly paths. `handleReply` normal `llm_messages.py:584`: `getThreadByMessageForLLM` → dedup applies transitively. `handleReply` fallback `:586-603`: 3 single-msg list, no dedup. `handleMention` all branches: single-msg, no dedup; BUT text-reply bypass (`:728`) must pass `cache=self.cache`. `handleRandomMessage` reply branch `:843`: `getThreadByMessageForLLM` → dedup applies. `handleRandomMessage` NON-reply branch `:874-903`: SEPARATE multi-message loop over `getChatMessagesSince`, calling `fromDBChatMessage`+`toModelMessageList` per message, then current msg at `:936`. NOT via `getThreadByMessageForLLM`. | llm_messages.py |
| **F10** | `metadata["memories"]` declared type `CompactMemoryIdsDict` (`message_metadata.py:114`). Only runtime write site: `setUserMemories:929` → compact ID form. `handleMention:721` does whole-dict replacement from DB JSON. Legacy CONTENT form (`{permanent:[...], shortTerm:[...]}`) NEVER written at runtime but MAY exist in OLD pre-compaction DB rows (`scripts/clear_old_format_memories.py` exists). Current `resolveMemories` defensively checks `permanentIds`/`shortTermIds` keys and early-returns if absent. New `formatForLLM` MUST do the same. | message_metadata.py |
| **F11** | `__slots__` tuple `:356-381`. Remove entry `"userMemories"` at `:374`. Only other memory-related slot is `"metadata"` (`:377`) — keep (canonical ID source). | ensured_message.py |

## 3. Locked decisions

Carried from v1:

1. **Drop the `EnsuredMessage.userMemories` field** (attribute `:460` + `__slots__` entry `:374`). Canonical ID source = `metadata["memories"]` (`CompactMemoryIdsDict`: `{permanentIds, shortTermIds}`).
2. **Remove `resolveMemories`** — memory resolution moves from load-time into `formatForLLM`.
3. **Dedup direction: newest → oldest.** Newest message renders its FULL memory set; each older message renders only memories not already shown by any newer message. Each memory appears once, at its latest occurrence.
4. **`formatForLLM` gains `cache` and `excludeMemoryIds` keyword-only params.**
5. **TEXT branch is a documented no-op** (memories not rendered in TEXT; TEXT is for bot messages which carry no user memory).

New decisions forced by the findings:

6. **`handleMention` text-reply bypass resolves via `formatForLLM`'s new `cache` param** (F2). Remove the `resolveMemories` call at `llm_messages.py:725`; pass `cache=self.cache` to the `toModelMessage` call at `:728`.
7. **Remove `injectMemories` param from `fromDBChatMessage`** (F4). Once `resolveMemories` is gone, `injectMemories` gates nothing meaningful (metadata IDs are always loaded). Update all call sites (see §5.6). Removing (not deprecating) is preferred — see §11(b). `[architect review: Open Question (b) resolved — REMOVE.]`
8. **Warm the by-id cache inside `injectMemories`** to avoid a redundant current-message DB hit (F5 option a). After fetching, call a new `CacheService.warmMemoriesByIds(entries)` method (added by this plan — see §5.3) that writes each resolved memory into `self.memories` (stripping `id` to match the `keepId=False` shape) so `formatForLLM`'s `getMemoriesByIds` is a cache hit. `[architect review: Open Question (c) resolved — dedicated method preferred over reaching into LRU from a handler.]`
9. **Pre-scan raw DB-row metadata to precompute `excludeMemoryIds` per rendered message** (F6). Because the formatting loop is oldest-first and inline, computing `excludeMemoryIds[i]` requires knowing IDs of messages `i+1..N` (not yet visited). `[architect review: Open Question (a) resolved — BUILD-then-DEDUP-then-FORMAT chosen over raw-JSON pre-scan. See §5.4 for the restructure details including condense-replay slicing.]` Build the rendered `EnsuredMessage` sequence (keepFirstN + tail, NOT condensed middle) first, run `computeMemoryExcludes`, then format.
10. **Extract dedup logic as a reusable helper** — module-level function in `base.py` so `handleRandomMessage` non-reply path can adopt it later (F9). `[architect review: Open Question (e) resolved — module-level in base.py, not a staticmethod.]`
11. **Defer `handleRandomMessage` non-reply path DEDUP** — out of scope, documented rationale (F9): random-answer path, small window, lower duplication cost; can adopt the reusable helper later. `[architect review: Open Question (d) resolved — DEFER dedup only. Memory RENDERING (cache=self.cache) at :893 and :936 is in-scope; see §10 clarification and §7 Phase 3.]`
12. **`formatForLLM` defensively skips memories when compact keys absent** (legacy content form or `None`) (F10).

## 4. (intentionally folded into §3)

## 5. Detailed design

> **Convention reminder:** all code shown uses camelCase vars/fields/methods,
> PascalCase classes. Every signature shown must carry full type hints. At
> implementation time, every new/changed method needs a docstring with `Args:` /
> `Returns:` per project rules (the plan shows signatures + algorithm, not full
> docstrings, to stay navigable).

### 5.1 `EnsuredMessage` (`internal/bot/models/ensured_message.py`)

**Remove `userMemories` field + slot.**

- Delete `__slots__` entry `"userMemories"` at line **374**.
- Delete the `self.userMemories: Optional[UserMemoriesDict] = None` assignment + docstring at lines **460-461**.

**Remove `resolveMemories` method** (lines `:934-981`) entirely. Its resolution logic migrates into `formatForLLM` (§5.2).

**Repurpose `setUserMemories`** — now writes IDs into `metadata["memories"]` ONLY (no `userMemories` content to set). Consider renaming to `setMemoryIds`; this plan keeps the name to minimize churn (rename deferred — see §10).

Current signature (`:893`):
```python
def setUserMemories(self, memories: UserMemoriesDict) -> None:
```

New signature (unchanged externally; body changes):
```python
def setUserMemories(self, memories: UserMemoriesDict) -> None:
    # Docstring (Args/Returns required) — note: now writes IDs ONLY into
    # metadata["memories"]; content is discarded (resolution deferred to
    # formatForLLM via cache).
```

New body — replace lines `:911-932` (the `self.userMemories = deepcopy(...)` write at `:917` is removed; the `metadata["memories"]` write at `:929-932` is kept):
```python
permanent = memories.get("permanent", [])
shortTerm = memories.get("shortTerm", [])
# metadata["memories"] accepts the compact ID form. Walrus + ``.get()`` so
# pyright's reportTypedDictNotRequiredAccess is satisfied (``id`` is
# NotRequired on SingleMemoryDict).
self.metadata["memories"] = {
    "permanentIds": [mid for m in permanent if (mid := m.get("id"))],
    "shortTermIds": [mid for m in shortTerm if (mid := m.get("id"))],
}
# NOTE: content (the deepcopy'd dict) is NO LONGER stored on the message —
# the caller (injectMemories) warms the by-id cache separately (§5.3).
```

**Add `getMemoryIds` helper** (new method, place near `setUserMemories`):
```python
def getMemoryIds(self) -> Set[str]:
    """Return the union of all memory IDs (permanent + shortTerm) carried by
    this message, read from ``metadata["memories"]``.

    Returns an empty set when metadata carries no memories, the legacy content
    form (no ``permanentIds``/``shortTermIds`` keys), or a non-dict value.
    Used by the dedup pre-scan to compute per-message exclude-sets.

    Args:
        (none)

    Returns:
        Set of memory UUID hex strings (permanent ∪ shortTerm). Empty when no
        compact IDs are present.
    """
```
Body:
```python
rawMemories = self.metadata.get("memories")
if not isinstance(rawMemories, dict):
    return set()
permanentIds = rawMemories.get("permanentIds", []) or []
shortTermIds = rawMemories.get("shortTermIds", []) or []
return set(permanentIds) | set(shortTermIds)
```
(The defensive compact-key check via `.get(..., [])` mirrors `resolveMemories`' guard at `:962-968`, satisfying F10/F12.)

**`fromDBChatMessage` signature change** — drop `injectMemories`.

Current (`:789-798`):
```python
@classmethod
async def fromDBChatMessage(
    cls,
    data: ChatMessageDict,
    db: Database,
    *,
    forceGetAllMedia: bool = False,
    injectMemories: bool,
    cache: Optional["CacheService"] = None,
) -> "EnsuredMessage":
```

New:
```python
@classmethod
async def fromDBChatMessage(
    cls,
    data: ChatMessageDict,
    db: Database,
    *,
    forceGetAllMedia: bool = False,
) -> "EnsuredMessage":
```
Body change: delete lines `:884-889` (the `# metadata["memories"] is already the stored compact ID dict ...` comment block + the `if injectMemories and cache is not None: await ensuredMessage.resolveMemories(cache)` call). Metadata is still loaded unconditionally at `:832-834`. Update the docstring (`:799-823`) to drop the `injectMemories`/`cache`/`resolveMemories` description.

**`__str__` update** (`:1359`) — remove the `"userMemories"` entry from the debug dict (the field no longer exists). Replace:
```python
"userMemories": "{...}" if self.userMemories else None,
```
with nothing (delete the line; the subsequent `if v` filter loop at `:1361-1364` is unaffected). Optionally add `"memoryIds": len(self.getMemoryIds()) or None` as a non-content debug hint.

### 5.2 `formatForLLM` + `toModelMessage` + `toModelMessageList`

**`formatForLLM`** — current signature (`:1148-1157`):
```python
async def formatForLLM(
    self,
    db: Database,
    format: LLMMessageFormat = LLMMessageFormat.JSON,
    replaceMessageText: Optional[str] = None,
    stripAtsign: bool = False,
    outputFormat: OutputFormat = OutputFormat.MARKDOWN,
    useSingleMedia: bool = True,
) -> str:
```

New signature (keyword-only new params, default `None` → backward-compatible):
```python
async def formatForLLM(
    self,
    db: Database,
    format: LLMMessageFormat = LLMMessageFormat.JSON,
    replaceMessageText: Optional[str] = None,
    stripAtsign: bool = False,
    outputFormat: OutputFormat = OutputFormat.MARKDOWN,
    useSingleMedia: bool = True,
    *,
    cache: Optional["CacheService"] = None,
    excludeMemoryIds: Optional[Set[str]] = None,
) -> str:
```

JSON-branch memory-render algorithm (replaces the `"userMemories": self.userMemories,` entry at `:1202`):
1. **Read IDs:** `allIds = self.getMemoryIds()` (permanent ∪ shortTerm from `metadata["memories"]`).
2. **Defensive legacy check (F10/F12):** `getMemoryIds` already returns `set()` when the compact keys are absent (legacy content form) or metadata is non-dict/None. No separate guard needed in `formatForLLM`; an empty `allIds` short-circuits to "no memory key."
3. **Subtract excludes:** `renderedIds = allIds - (excludeMemoryIds or set())`.
4. **Resolve survivors** — ONLY when `cache is not None` AND `renderedIds` is non-empty:
   ```python
   resolved = await cache.getMemoriesByIds(
       list(renderedIds), chatId=self.recipient.id
   )
   ```
   Then reconstruct the two cohorts by re-reading the permanent/shortTerm ID lists from `metadata["memories"]` and filtering by membership in `renderedIds`:
   ```python
   rawMemories = self.metadata.get("memories", {})
   permanentIds = [mid for mid in (rawMemories.get("permanentIds", []) or []) if mid in renderedIds]
   shortTermIds = [mid for mid in (rawMemories.get("shortTermIds", []) or []) if mid in renderedIds]
   # Walrus narrows the Optional (mirror resolveMemories's pattern at :975-980):
   # ``resolved[mid]`` after a separate ``resolved.get(mid) is not None`` guard
   # does NOT narrow under pyright (different expression).
   permanentEntries: List[SingleMemoryDict] = [
       entry for mid in permanentIds if (entry := resolved.get(mid)) is not None
   ]
   shortTermEntries: List[SingleMemoryDict] = [
       entry for mid in shortTermIds if (entry := resolved.get(mid)) is not None
   ]
   userMemoriesOut: UserMemoriesDict = {"permanent": permanentEntries, "shortTerm": shortTermEntries}
   ```
5. **Render into the `"userMemories"` JSON key** (same key name as today, so LLM prompt shape is unchanged). The existing dict-comprehension at `:1189-1205` drops falsy values: emit `userMemoriesOut` when non-empty (both cohorts empty lists → omit), else omit the key. The `id` field is NEVER emitted — the cache stores entries with `keepId=False` (F5), so no uuid leaks.
6. **`cache is None`** → omit the `"userMemories"` key entirely (safe default; non-chat paths like embeddings, summarization, chat_search).
7. **TEXT branch** (`:1210-1216`): unchanged — no memory rendering (documented no-op, v1 decision 5).

**`toModelMessage`** — current (`:1275-1284`):
```python
async def toModelMessage(
    self,
    db: Database,
    format: LLMMessageFormat = LLMMessageFormat.JSON,
    replaceMessageText: Optional[str] = None,
    stripAtsign: bool = False,
    role: str = "user",
    outputFormat: OutputFormat = OutputFormat.MARKDOWN,
    useSingleMedia: bool = True,
) -> ModelMessage:
```
New (thread `cache` + `excludeMemoryIds` through to `formatForLLM`):
```python
async def toModelMessage(
    self,
    db: Database,
    format: LLMMessageFormat = LLMMessageFormat.JSON,
    replaceMessageText: Optional[str] = None,
    stripAtsign: bool = False,
    role: str = "user",
    outputFormat: OutputFormat = OutputFormat.MARKDOWN,
    useSingleMedia: bool = True,
    *,
    cache: Optional["CacheService"] = None,
    excludeMemoryIds: Optional[Set[str]] = None,
) -> ModelMessage:
```
The internal `formatForLLM(...)` call at `:1315-1322` gains `cache=cache, excludeMemoryIds=excludeMemoryIds`.

**`toModelMessageList`** — current (`:1223-1232`):
```python
async def toModelMessageList(
    self,
    db: Database,
    format: LLMMessageFormat = LLMMessageFormat.JSON,
    replaceMessageText: Optional[str] = None,
    stripAtsign: bool = False,
    role: str = "user",
    outputFormat: OutputFormat = OutputFormat.MARKDOWN,
    useSingleMedia: bool = True,
) -> List[ModelMessage]:
```
New (same two keyword-only params; thread through to the `toModelMessage(...)` call at `:1262-1271`):
```python
async def toModelMessageList(
    self,
    db: Database,
    format: LLMMessageFormat = LLMMessageFormat.JSON,
    replaceMessageText: Optional[str] = None,
    stripAtsign: bool = False,
    role: str = "user",
    outputFormat: OutputFormat = OutputFormat.MARKDOWN,
    useSingleMedia: bool = True,
    *,
    cache: Optional["CacheService"] = None,
    excludeMemoryIds: Optional[Set[str]] = None,
) -> List[ModelMessage]:
```

> The defaults (`cache=None`, `excludeMemoryIds=None`) mean callers that previously passed `injectMemories=False` (or used TEXT format) are unaffected: when `cache is None`, `formatForLLM` omits memories, matching the old `userMemories=None` behavior. `[architect review: BUT callers that previously passed injectMemories=True MUST now pass cache=self.cache — see the corrected §5.6 table. The original draft of this note overgeneralized "unaffected" to ALL non-chat callers, which was incorrect.]`

### 5.3 `MessagePreprocessorHandler.injectMemories` (`message_preprocessor.py:76-133`)

Still fetches (no change to `:103-123`): `permanentMemories` via `cache.getChatUserPermanentMemories(...)`, `shortTermMemories` via `db.userMemories.getLatestMemories(...)` / `searchMemories(...)`.

**Change 1 — store IDs only:** the call at `:133` stays `ensuredMessage.setUserMemories({"permanent": permanentMemories, "shortTerm": shortTermMemories})`, but `setUserMemories` now writes only compact IDs into `metadata["memories"]` (§5.1). The fetched content is no longer hung off the message.

**Change 2 — warm the by-id cache (F5 option a):** after fetching, call a new `CacheService.warmMemoriesByIds` method that writes each resolved memory into the `self.memories` namespace so `formatForLLM`'s `getMemoriesByIds` is a cache hit for the current inbound message.

`[architect review: Open Question (c) resolved — a dedicated CacheService method is preferred over reaching into the LRU from a handler. It encapsulates the keepId=False shape-alignment invariant in the cache layer where it belongs, is independently testable, and avoids exposing `.set()` to callers.]`

**New `CacheService.warmMemoriesByIds` method** — add near `getMemoriesByIds` (`service.py:~1047`):
```python
def warmMemoriesByIds(self, entries: Sequence[SingleMemoryDict]) -> None:
    """Pre-populate the MEMORIES namespace with already-fetched entries.

    Called by ``MessagePreprocessorHandler.injectMemories`` after it fetches
    memories to decide which apply: the fetched content is written into the
    by-id cache so that a subsequent ``getMemoriesByIds`` call (e.g. from
    ``formatForLLM``) is a hit, avoiding a redundant DB batch query for the
    current inbound message.

    Each entry must carry ``id`` (SingleMemoryDict.id, present when the
    converter was called with ``keepId=True`` — both permanentMemories and
    shortTermMemories from injectMemories satisfy this). The ``id`` is
    STRIPPED before writing to match the ``keepId=False`` shape that
    ``getMemoriesByIds`` stores (see its docstring at ``:990-997``): the by-id
    cache key IS the memory id, so storing ``id`` inside the entry would leak
    a uuid into ``formatForLLM`` output, violating the SingleMemoryDict.id
    invariant.

    Args:
        entries: Fetched memory entries (each carrying ``id``). Entries
            without ``id`` are silently skipped (defensive).

    Returns:
        None.
    """
    for entry in entries:
        mid = entry.get("id")
        if mid is None:
            continue
        warmed = cast(SingleMemoryDict, {k: v for k, v in entry.items() if k != "id"})
        self.memories.set(mid, warmed)
```
(`self.memories` is the `LRUCache` property at `service.py:376`; `.set(key, value)` is the namespace setter — same pattern `getMemoriesByIds` itself uses at `:1044`. `cast` mirrors the existing pattern in `setUserMemories:917-921`.)

**injectMemories call-site** (insert immediately after `:133`, before the method returns):
```python
# Warm the by-id cache so formatForLLM's getMemoriesByIds hits instead of
# re-querying the same content injectMemories just fetched.
self.cache.warmMemoriesByIds(permanentMemories + shortTermMemories)
```

> **Why this works:** the by-id cache key is the memory UUID (`mid`), globally unique per DB (`service.py:999-1003`). The same `mid` that `warmMemoriesByIds` writes is what `metadata["memories"]["permanentIds"]`/`["shortTermIds"]` carries, which is what `formatForLLM` passes to `getMemoriesByIds`. The warm makes that lookup a hit. The `self.chatUsers` permanentMemories cache (different namespace, `keepId=True` shape) is not touched — no aliasing risk.

### 5.4 `getThreadByMessageForLLM` dedup (`base.py:710-900`)

**Reusable helper** — add a module-level function in `base.py` (placement decided — see §11(e)). Proposed so `handleRandomMessage` can import it later.

```python
def computeMemoryExcludes(
    messages: Sequence[EnsuredMessage],
) -> List[Set[str]]:
    """Compute per-message memory exclude-sets, newest → oldest.

    For a sequence ordered OLDEST → NEWEST (the natural render order), returns
    a list ``excludes[i]`` such that message ``i`` should omit every memory ID
    that appears in any NEWER message (i.e. any message at index > i). The
    newest message (last index) gets an empty exclude-set (renders its full
    set). Each memory thus appears exactly once, at its latest occurrence.

    Args:
        messages: Rendered EnsuredMessages in oldest-first order.

    Returns:
        List of sets aligned with ``messages`` by index; ``excludes[i]`` is the
        set of IDs message ``i`` must omit. Empty for the newest message.
    """
```
Body:
```python
n = len(messages)
excludes: List[Set[str]] = [set() for _ in range(n)]
seen: Set[str] = set()
for i in range(n - 1, -1, -1):   # newest → oldest
    ids = messages[i].getMemoryIds()
    excludes[i] = ids & seen
    seen |= ids
return excludes
```

**Pre-scan approach over raw DB-row metadata (F6).** Because `getThreadByMessageForLLM` builds+formats inline and oldest-first, the excludes must be computed BEFORE the formatting loop. Two viable strategies; **recommended: build EnsuredMessages first (without formatting), run `computeMemoryExcludes`, then format.** `[architect review: Open Question (a) resolved — BUILD-then-DEDUP-then-FORMAT chosen. Reuses getMemoryIds(), avoids duplicating the metadata-shape logic in a raw-JSON pre-scan. The extra cost of building EnsuredMessages slightly earlier is negligible (they must be built for formatting anyway).]` This avoids re-parsing raw JSON and reuses `getMemoryIds()`. The alternative (parse `json.loads(row["metadata"])["memories"]` for keepFirstN+tail indices only) avoids constructing intermediate objects but duplicates the metadata-shape logic — rejected for maintainability.

`[architect review: condense-replay slicing — the BUILD phase must replicate the slicing logic from the condense-replay loop (:805-817) to determine which DB rows become rendered EnsuredMessages (keepFirstN + sliced tail) vs which are consumed by condensed summaries (dropped, no memory blocks per F7). The slicing is deterministic: iterate `condenseCache`, for each entry count `skippedMessages` in `dbMessageList` until `tillMessageId` matches or `date > tillTS`, then slice. Extract this into a small helper or run it as a pre-pass within the BUILD phase. The current code interleaves slicing with appending condensed summaries to `ret` (:805-810); the restructure separates them: slice first (BUILD), dedup, then append condensed summaries at the correct position during FORMAT. Since keepFirstN messages and condensed summaries are NOT interleaved in the current code (keepFirstN loop at :789-800 runs completely before the summary loop at :805-817), the restructure is straightforward: format keepFirstN → append condensed summaries → format tail, with excludes indexed over the concatenated keepFirstN+tail list.]`

`[architect review: metadata non-mutation invariant — formatForLLM MUST NOT mutate metadata["memories"]. The condense branch persists eRootMessage.metadata to DB (:893-898); if metadata["memories"] were re-pointed from compact IDs to resolved content during rendering, the condense write would persist content over IDs, defeating compaction for condensed threads. The algorithm in §5.2 reads metadata["memories"] via .get() only and writes resolved content into a local userMemoriesOut variable — metadata is never written. getMemoryIds() likewise only reads. This preserves the invariant that resolveMemories documented at :944-952.]`

Concretely, restructure `getThreadByMessageForLLM`'s threaded branch (`:769-830`) into:

1. **Build phase:** construct the list of `EnsuredMessage`s that WILL be rendered (keepFirstN entries from `:790` + tail entries from `:820`), skipping condensed middle entries (which never become `EnsuredMessage`s, per F7). In the condense-replay path, run the slicing logic first to determine the tail boundary (see architect-review note above). Do NOT format yet. In the non-replay path (no `condenseCache`), all `dbMessageList` entries are built.
2. **Dedup phase:** `excludes = computeMemoryExcludes(renderedEnsuredMessages)` over the built list (oldest-first, newest=last).
3. **Format phase:** iterate the built list and call `toModelMessageList(...)` at each index, passing `cache=self.cache, excludeMemoryIds=excludes[i]`. Interleave condensed summaries (plain-text `ModelMessage`s) between the keepFirstN and tail formatted messages, preserving the current ordering: keepFirstN formatted → condensed summaries → tail formatted.

**Three render-site updates:**

- **Branch A (`:762`, standalone, `root_message_id is None`):** single message, no dedup. Pass `cache=self.cache, excludeMemoryIds=None`:
  ```python
  return ret + await eMessage.toModelMessageList(
      self.db,
      format=llmMFormat,
      outputFormat=outputFormat,
      role=MessageCategory.fromStr(dbMessage["message_category"]).toRole(),
      cache=self.cache,
  )
  ```
  (`excludeMemoryIds` defaults `None` — omit or pass explicitly; single message has nothing to dedup against.)

- **Condense-replay keepFirstN loop (`:794`):** after building the keepFirstN `EnsuredMessage`s + tail `EnsuredMessage`s, format with `cache=self.cache, excludeMemoryIds=excludes[renderedIndex]`.

- **Main loop (`:824`):** same — `cache=self.cache, excludeMemoryIds=excludes[renderedIndex]`.

> **Condensed middle entries:** neither contribute to the `seen` set nor get formatted individually (F7) — they are plain-text `ModelMessage`s with no memory blocks. The pre-scan/BUILD only covers keepFirstN + tail.

**`eRootMessage` (`:783`):** untouched — never formatted, only reads/persists condense cache (F6). `[architect review: eRootMessage is built via fromDBChatMessage(dbMessageList[0], self.db, injectMemories=needMemories) — note no cache param today, so resolveMemories is never called on it. After injectMemories removal, it becomes fromDBChatMessage(dbMessageList[0], self.db) — metadata still loaded unconditionally (:832-834). No breakage. In the BUILD phase, dbMessageList[0] is also built as the keepFirstN EnsuredMessage (keepFirstN=1); consider reusing the same instance to avoid double-construction, but this is an optimization, not a correctness requirement.]` No dedup needed.

### 5.5 `handleMention` text-reply bypass (`llm_messages.py:721-728`)

Per F2, this is the second `resolveMemories` caller. Changes:

- **Remove** the `await ensuredReply.resolveMemories(self.cache)` call at `:725` (method deleted in §5.1).
- **Pass** `cache=self.cache` to the `toModelMessage` call at `:728`:
  ```python
  reqMessages.append(
      await ensuredReply.toModelMessage(
          self.db,
          format=llmMessageFormat,
          role=("assistant" if ensuredReply.sender.id == await self.getBotId() else "user"),
          cache=self.cache,
      ),
  )
  ```
  (`excludeMemoryIds=None` — single message, no dedup.) The metadata assignment at `:721` (`ensuredReply.metadata = metadata`) is unchanged; `formatForLLM` reads IDs from it directly.

`[architect review: the handleMention NON-text reply path (:746-755) is a SECOND call site in the same method that also loses memories after the refactor. eStoredReply is built from DB via fromDBChatMessage(:746), so metadata carries compact IDs; when injectMemories=True, memories were resolved. After dropping injectMemories from fromDBChatMessage, the toModelMessage call at :750 MUST also pass cache=self.cache to render memories. See the corrected §5.6 table.]`

### 5.6 Other call-site updates

**`fromDBChatMessage` callers — drop `injectMemories` kwarg (and `cache=` when it was only for `resolveMemories`):**

| File:line | Current call | New call |
|-----------|--------------|----------|
| `base.py:759-761` (Branch A) | `fromDBChatMessage(dbMessage, self.db, injectMemories=needMemories, cache=self.cache)` | `fromDBChatMessage(dbMessage, self.db)` (cache now passed at format time) |
| `base.py:783` (eRootMessage) | `fromDBChatMessage(dbMessageList[0], self.db, injectMemories=needMemories)` | `fromDBChatMessage(dbMessageList[0], self.db)` |
| `base.py:790-792` (keepFirstN) | `..., injectMemories=needMemories, cache=self.cache` | `fromDBChatMessage(...)` |
| `base.py:820-822` (main loop) | `..., injectMemories=needMemories, cache=self.cache` | `fromDBChatMessage(...)` |
| `llm_messages.py:746-748` (handleMention non-text) | `..., injectMemories=injectMemories, cache=self.cache` | `fromDBChatMessage(storedReply, self.db)` |
| `llm_messages.py:883-885` (handleRandomMessage non-reply) | `..., injectMemories=injectMemories, cache=self.cache` | `fromDBChatMessage(storedMsg, self.db)` |
| `chat_search.py:411-412` | `..., injectMemories=False` | `fromDBChatMessage(pendingMessage, self.db)` |
| `chat_search.py:706` | `fromDBChatMessage(msg, self.db, injectMemories=False)` | `fromDBChatMessage(msg, self.db)` |
| `media.py:329` | `fromDBChatMessage(storedReply, self.db, injectMemories=False)` | `fromDBChatMessage(storedReply, self.db)` |
| `media.py:653-654` | `..., injectMemories=memoriesEnabled, cache=self.cache` | `fromDBChatMessage(msg, self.db)` |
| `summarization.py:215` | `..., injectMemories=False` | `fromDBChatMessage(msg, self.db)` |
| `summarization.py:676` | `..., injectMemories=False` | `fromDBChatMessage(dbRepliedMessage, self.db)` |
| `summarization.py:679` | `..., injectMemories=False` | `fromDBChatMessage(dbMessage, self.db)` |
| `user_memories.py:1498` | `fromDBChatMessage(msg, self.db, injectMemories=False)` | `fromDBChatMessage(msg, self.db)` |
| `scripts/reproduce_llm_dialog.py:387` | `..., injectMemories=injectMemories` | `fromDBChatMessage(storedMsg, db)` |

**Non-chat `toModelMessage`/`toModelMessageList`/`formatForLLM` callers that need `cache=self.cache` ADDED** `[architect review: CRITICAL FIX — the original plan marked ALL non-chat callers as "unaffected." This is WRONG for callers that previously passed injectMemories=True (or conditional) to fromDBChatMessage: after the refactor, fromDBChatMessage no longer resolves memories, so the toModelMessage/formatForLLM call must pass cache=self.cache to render memories at all. Without this fix, memories silently disappear from these paths.]`

| File:line | Current | New — add `cache=self.cache` |
|-----------|---------|------|
| `llm_messages.py:602` (handleReply fallback, current msg) | `ensuredMessage.toModelMessage(self.db, format=llmMessageFormat, role="user")` | Add `cache=self.cache` (the `:601` `ensuredReply` is from `getEnsuredRepliedToMessage` — live message, no DB metadata, no IDs → truly unaffected, no cache needed) |
| `llm_messages.py:750` (handleMention non-text stored reply) | `eStoredReply.toModelMessage(self.db, format=llmMessageFormat, role=...)` | Add `cache=self.cache` (built from DB via fromDBChatMessage, carries IDs) |
| `llm_messages.py:759` (handleMention current msg) | `ensuredMessage.toModelMessage(self.db, format=llmMessageFormat, role="user")` | Add `cache=self.cache` (current inbound, IDs set by preprocessor, cache warmed) |
| `llm_messages.py:893` (handleRandomMessage non-reply context) | `eMsg.toModelMessageList(self.db, format=llmMessageFormat, role=...)` | Add `cache=self.cache` (dedup/excludeMemoryIds DEFERRED per §10, but rendering requires cache) |
| `llm_messages.py:936` (handleRandomMessage non-reply current msg) | `ensuredMessage.toModelMessageList(self.db, format=llmMessageFormat)` | Add `cache=self.cache` |
| `media.py:657` (draw handler latest messages) | `eMsg.toModelMessage(self.db, format=...)` | Add `cache=self.cache` (was `injectMemories=memoriesEnabled`; without cache, memories silently dropped) |

**Non-chat `formatForLLM` callers — TRULY UNAFFECTED** (these callers either use TEXT format — no memory rendering — or passed `injectMemories=False` — no memories before or after):
`chat_search.py:448` (TEXT embedding), `chat_search.py:707` (JSON tool, was `injectMemories=False`), `summarization.py:216` (JSON, was `injectMemories=False`), `user_memories.py:1499` (JSON, was `injectMemories=False`), `message_preprocessor.py:193` (TEXT embedding, pre-injection). New `cache=None` default reproduces the old omission exactly for these.

> `[architect review: the rule is simple — if the OLD code passed injectMemories=True (or a conditional that can be True) to fromDBChatMessage AND then called toModelMessage/formatForLLM, the NEW code must pass cache=self.cache at the format call. The fromDBChatMessage change table above handles the fromDBChatMessage side; this table handles the format side. Both tables must be applied together.]`

## 6. Newest → oldest dedup algorithm

**Invariant:** each memory ID appears exactly once across the rendered context, at its latest (newest) occurrence. The newest message renders its full set; each older message renders only IDs not present in any newer message.

**Formal algorithm** (oldest-first input, `computeMemoryExcludes`):
```
seen ← ∅
for i from N-1 down to 0:        # newest → oldest
    ids_i ← messages[i].getMemoryIds()
    excludes[i] ← ids_i ∩ seen
    seen ← seen ∪ ids_i
# render: message i omits excludes[i] (renders ids_i − excludes[i])
```

**Worked example** — 4 messages, oldest-first `[m0, m1, m2, m3]` (m3 = newest = current inbound):

| msg | permanent IDs | shortTerm IDs |
|-----|---------------|---------------|
| m0 | M | — |
| m1 | M | S1 |
| m2 | M | — |
| m3 | M | S2 |

Iteration (newest → oldest):

| step (i) | `ids_i` | `seen` before | `excludes[i]` | `seen` after | rendered by m_i |
|----------|---------|---------------|---------------|--------------|-----------------|
| i=3 (m3) | {M, S2} | ∅ | ∅ | {M, S2} | M, S2 (full set) |
| i=2 (m2) | {M} | {M, S2} | {M} | {M, S2} | ∅ (M already seen) |
| i=1 (m1) | {M, S1} | {M, S2} | {M} | {M, S1, S2} | S1 |
| i=0 (m0) | {M} | {M, S1, S2} | {M} | {M, S1, S2} | ∅ |

Rendered context (oldest-first, as the LLM sees it): m0 (no memories), m1 (S1), m2 (none), m3 (M, S2). **Total:** M appears once (at m3), S1 once (at m1), S2 once (at m3). Pre-refactor: M would appear 4×, S1 once, S2 once.

## 7. Phased implementation breakdown

Each phase sized to a ~60-step software-developer budget. `[architect review: phases REORDERED from original plan. The original Phase 1 removed `injectMemories` (a required param) from `fromDBChatMessage`, breaking 14 callers with "green only after Phase 5" — violating the project's `make test` after-every-change rule. The revised ordering is purely additive first (add new params/methods with defaults), then wires consumers, then removes dead code — each phase is independently green.]`

### Phase 1 — Additive: new params, methods, helper (no removals)
**Files:** `internal/bot/models/ensured_message.py`, `internal/bot/common/handlers/base.py`, `internal/services/cache/service.py`.
**Changes:**
- Add `cache`/`excludeMemoryIds` keyword-only params (default `None`) to `formatForLLM` (`:1148`), `toModelMessage` (`:1275`), `toModelMessageList` (`:1223`); thread through internal calls (`:1262`, `:1315`).
- Implement the JSON-branch memory-render algorithm in `formatForLLM` (§5.2).
- Add `getMemoryIds()` method to `EnsuredMessage` (§5.1).
- Add `computeMemoryExcludes()` module function to `base.py` (§5.4).
- Add `warmMemoriesByIds()` method to `CacheService` (§5.3).
- `setUserMemories` body change: write IDs only into `metadata["memories"]`; KEEP the `self.userMemories = deepcopy(...)` write for now (removed in Phase 4).
**All purely additive.** Old code paths (`resolveMemories`, `userMemories` reads in `formatForLLM`/`__str__`) still work — `formatForLLM` prefers the `cache`+`getMemoryIds()` path when `cache is not None`, falls back to `self.userMemories` when `cache is None` (backward-compatible).
**Verification:** `make format lint`; `make test` — all existing tests pass (no behavior change yet).

### Phase 2 — Wire dedup into `getThreadByMessageForLLM` + cache-warm in `injectMemories`
**Files:** `internal/bot/common/handlers/base.py`, `internal/bot/common/handlers/message_preprocessor.py`.
**Changes:**
- Restructure threaded branch of `getThreadByMessageForLLM` into build→dedup→format (§5.4).
- Wire `cache=self.cache, excludeMemoryIds=excludes[i]` at the 3 threaded render sites (`:794` keepFirstN, `:824` main loop).
- Wire `cache=self.cache` at Branch A (`:762`, single-msg, `excludeMemoryIds=None`).
- Add `warmMemoriesByIds` call in `injectMemories` after `:133`.
- Drop `injectMemories`/`cache` kwargs from `fromDBChatMessage` calls in `base.py` (`:759-761`, `:783`, `:790-792`, `:820-822`) — but KEEP the param in the signature for now (add `injectMemories: bool = False` default so callers that still pass it don't break).
**Verification:** `make format lint`; `./venv/bin/pytest tests/bot/common/handlers/ tests/bot/common/handlers/test_message_preprocessor.py -v`; dedup is now live for threaded + Branch A paths.

### Phase 3 — Wire remaining handler paths (handleMention, handleReply fallback, handleRandomMessage, media)
**Files:** `internal/bot/common/handlers/llm_messages.py`, `internal/bot/common/handlers/media.py`.
**Changes:**
- `handleMention` text-reply bypass (`:725`): remove `resolveMemories` call; pass `cache=self.cache` at `:728`.
- `handleMention` non-text reply (`:746-755`): drop `injectMemories`/`cache` from `fromDBChatMessage`; add `cache=self.cache` at `:750` toModelMessage.
- `handleMention` current msg (`:759`): add `cache=self.cache`.
- `handleReply` fallback (`:602`): add `cache=self.cache` to current-msg toModelMessage.
- `handleRandomMessage` non-reply (`:883-885`): drop `injectMemories`/`cache` from `fromDBChatMessage`; add `cache=self.cache` at `:893` toModelMessageList (dedup deferred, no excludeMemoryIds yet); add `cache=self.cache` at `:936`.
- `media.py` draw (`:653-654`): drop `injectMemories`/`cache` from `fromDBChatMessage`; add `cache=self.cache` at `:657`.
**Verification:** `make format lint`; `./venv/bin/pytest tests/bot/common/handlers/ -v`; full `make test`.

### Phase 4 — Remove dead code (fromDBChatMessage injectMemories param, resolveMemories, userMemories field)
**Files:** `internal/bot/models/ensured_message.py`, all remaining `fromDBChatMessage` callers.
**Changes (all in one phase for atomic green):**
- Remove `injectMemories`/`cache` params from `fromDBChatMessage` signature (`:789-798`); remove the `resolveMemories` call block (`:884-889`); update docstring.
- Update ALL remaining `fromDBChatMessage` callers that still pass `injectMemories`/`cache`: `chat_search.py:411-412`, `chat_search.py:706`, `media.py:329`, `summarization.py:215,676,679`, `user_memories.py:1498`, `scripts/reproduce_llm_dialog.py:387`.
- Remove `resolveMemories` method (`:934-981`).
- Remove `userMemories` field (`:460-461`) + `__slots__` entry (`:374`).
- Remove the `self.userMemories = deepcopy(...)` write from `setUserMemories` (body now IDs-only per §5.1).
- Update `__str__` (`:1359`) — remove `userMemories` entry.
- Remove `formatForLLM`'s backward-compat fallback to `self.userMemories` (the field is gone; `cache is None` → omit memories).
**Verification:** `make format lint`; full `make test`.

### Phase 5 — test updates + new dedup tests
**Files:** `tests/bot/models/test_ensured_message.py`, `tests/bot/common/handlers/test_message_preprocessor.py`, `tests/bot/common/handlers/test_llm_messages.py`, `tests/test_memory_resolution_coverage.py`, new test files as needed.
**Changes:** see §8. (Tests that reference `userMemories`/`resolveMemories` are updated here; some may need earlier touch-up if Phase 1-4 intermediate states break them — interleave as needed.)
**Verification:** `make test` green.

### Phase 6 — doc sync
**Action:** load `update-project-docs` skill; sync `docs/llm/architecture.md` (memory-duplication ADR / ~75 KB figure), `docs/llm/memories/user-memories.md` (injection/render section), `message_metadata.py` docstrings, `docs/llm/services.md` (new `warmMemoriesByIds`), and this plan's Status → IMPLEMENTED.

## 8. Test plan

### Tests to DELETE (resolveMemories / userMemories-field specific)
- Any test whose sole purpose is exercising `resolveMemories` (e.g. `test_ensured_message.py` cases asserting `msg.userMemories` after `resolveMemories`). Audit `tests/bot/models/test_ensured_message.py:170,197,482` (the `setUserMemories` unit tests — keep, but update assertions).
- `tests/test_memory_resolution_coverage.py` — **this is an AST guard** (see its module docstring `:9-18`): it scans production code for `fromDBChatMessage(..., injectMemories=<truthy>)` sites and verifies each rendered message gets memories resolved. Once `injectMemories` is removed from `fromDBChatMessage`, **this entire guard file is obsolete** — its checks 1/2/3 all key off the `injectMemories` kwarg. Either DELETE the file, or repurpose it to verify that chat-context render sites (`base.py:762,794,824`) pass `cache=self.cache`. Recommend DELETE (the dedup tests cover the new contract).

### Tests to UPDATE (F1/F1t blast radius)
Convert assertions from `msg.userMemories[...]` to either (a) `msg.getMemoryIds()` for ID-level checks, or (b) `await msg.formatForLLM(db, cache=cache, ...)` output inspection for content-level checks.

- `tests/bot/models/test_ensured_message.py:181-186,207-210,234-236,255-256,267,276,305-306,323-324,336-338,452,458,568-569,584` — `userMemories` reads → `getMemoryIds()` or `formatForLLM` output.
- `tests/bot/models/test_ensured_message.py:170,197,482` — `setUserMemories` unit tests: now assert `metadata["memories"]` has the compact IDs (not `userMemories` content).
- `tests/bot/common/handlers/test_message_preprocessor.py:911-920,985-989,1017-1020` — assert cache-warm (`self.cache.memories` populated) + `metadata["memories"]` IDs.
- `tests/bot/common/handlers/test_llm_messages.py:1402-1406` — `userMemories` read → `formatForLLM` output.
- `tests/bot/models/test_ensured_message.py:87,114,429,430,459,490,491` and `tests/test_memory_resolution_coverage.py:522,540,556,592,612,616,629,631,649` and `tests/bot/common/handlers/test_llm_messages.py:598,657,1376` — `toModelMessage`/`List`/`formatForLLM` call sites: unaffected by signature change (defaults), but verify they still pass.

### Tests to ADD
1. **`getMemoryIds`** — returns union of permanent+shortTerm; empty when metadata has no memories; empty for legacy content form (`{permanent:[...]}`); empty for non-dict/None.
2. **`formatForLLM` exclude semantics** — `excludeMemoryIds=None` renders all IDs; non-empty `excludeMemoryIds` omits those IDs; all-excluded → `"userMemories"` key omitted entirely.
3. **`formatForLLM` `cache=None`** — omits `"userMemories"` key entirely (safe default).
4. **`formatForLLM` legacy-metadata skip** — metadata with legacy content form (no `permanentIds`/`shortTermIds`) → no memory key (defensive, F10).
5. **`formatForLLM` no `id` leak** — rendered entries carry no `id` field (cache stores `keepId=False`).
6. **`warmMemoriesByIds`** — `[architect review: new test for the new CacheService method.]` entries with `id` are written to `self.memories` without `id`; entries without `id` are skipped; a subsequent `getMemoriesByIds` for the same IDs is a hit (no DB query); the warmed entries match the `keepId=False` shape.
7. **`injectMemories` cache-warm** — after `injectMemories`, `self.cache.memories` contains each fetched memory by `id` (without `id`); a subsequent `getMemoriesByIds` is a hit (no DB query).
8. **`computeMemoryExcludes`** — newest message gets empty exclude-set; older messages get the intersection with newer IDs; the worked example in §6.
9. **`getThreadByMessageForLLM` end-to-end dedup** — fixture thread of N messages sharing a permanent memory + scattered short-terms; assert each memory appears exactly once across the assembled `ModelMessage` list, at its latest occurrence.
10. **`handleMention` text-reply bypass** — memories render via the `cache` param (no `resolveMemories` call).
11. **`handleMention` non-text reply renders memories** — `[architect review: regression test for the §5.6 corrected path.]` `eStoredReply.toModelMessage(..., cache=self.cache)` renders memories when `injectMemories=True` (was silently dropped in original plan).
12. **`handleReply` fallback renders current-msg memories** — `[architect review: regression test.]` `ensuredMessage.toModelMessage(..., cache=self.cache)` at `:602` renders memories.
13. **`handleRandomMessage` non-reply renders memories** — `[architect review: regression test.]` context msgs at `:893` and current msg at `:936` render memories with `cache=self.cache` (no dedup yet — deferred).
14. **`media.py` draw renders memories** — `[architect review: regression test.]` `eMsg.toModelMessage(..., cache=self.cache)` at `:657` renders memories when `memoriesEnabled=True`.
15. **`formatForLLM` does NOT mutate `metadata["memories"]`** — `[architect review: invariant test.]` after formatting with `cache` + `excludeMemoryIds`, `metadata["memories"]` is byte-identical to its pre-format state (preserves the ADR-015 condense-write invariant).

## 9. Edge cases & risks

- **Legacy content-form metadata** (F10): old pre-compaction DB rows may carry `{permanent:[...], shortTerm:[...]}` instead of compact IDs. `getMemoryIds` returns `set()` (no `permanentIds`/`shortTermIds` keys) → `formatForLLM` omits the memory key. Same behavior as the current `resolveMemories` early-return guard. No data loss for NEW messages; legacy messages simply render without memories until the cleanup script (`scripts/clear_old_format_memories.py`) runs.
- **Empty memory sets:** `getMemoryIds()` → `set()` → `formatForLLM` omits key. No special-casing.
- **All-excluded message:** `renderedIds` empty → both cohorts empty → `"userMemories"` key omitted (the dict-comprehension filter at `:1189-1205` drops falsy values). The message still renders its text/media normally.
- **`cache=None` paths:** embeddings (`message_preprocessor.py:193`), summarization, chat_search, media (when `memoriesEnabled=False`) — omit memories. Matches today's `injectMemories=False` behavior. `[architect review: BUT paths that previously passed injectMemories=True (handleMention, handleReply fallback, handleRandomMessage, media draw) MUST pass cache=self.cache — see corrected §5.6. The original plan's "Backward-compat of signature defaults" bullet overstated compatibility.]`
- **Condense interaction:** dedup runs only over keepFirstN + tail (rendered sequence); condensed middle entries have no memory blocks (F7). Fresh condensing receives the already-deduplicated `ret`, so the summarizer sees deduped content. `[architect review: condensed entries MUST NOT contribute to the seen set in computeMemoryExcludes — if they did, a memory appearing only in a condensed (dropped) entry would suppress that memory from an older rendered message, causing it to vanish entirely. The BUILD phase excludes condensed entries from the rendered list, so this is handled.]`
- **Redundant-query risk if cache-warm skipped:** if `injectMemories` does NOT call `warmMemoriesByIds`, then for the current inbound message `formatForLLM`'s `getMemoriesByIds` is a cache miss → one extra batch DB query per inbound message (F5). The cache-warm in §5.3 eliminates this. Risk: if the warm is omitted by mistake, the cost is a single indexed-PK batch query (cheap, but avoidable).
- **Metadata non-mutation invariant:** `[architect review: critical invariant carried over from resolveMemories's documented deviation at :944-952.]` `formatForLLM` and `getMemoryIds` READ `metadata["memories"]` only — they never write to it. The condense branch persists `eRootMessage.metadata` to DB (`:893-898`); if metadata were mutated during rendering, the condense write would corrupt the persisted state (compact IDs overwritten with resolved content, or vice versa). The algorithm writes resolved content into a local `userMemoriesOut` variable, leaving metadata untouched.
- **`eRootMessage` aliasing:** it shares `metadata` with the persisted condense cache. Dedup does NOT touch `eRootMessage` (never formatted), so the condense-write at `:893-898` is unaffected.

## 10. Out of scope

- **TEXT-branch rendering** — bot messages have no user memory; documented no-op (v1 decision 5).
- **D3 `delete_memory` tool gating** — read-side formatting change, not tool registration.
- **Storage compaction** — already done; `metadata["memories"]` already stores compact IDs. No schema/migration change.
- **`handleRandomMessage` non-reply path DEDUP** (`llm_messages.py:874-903`) — deferred. Rationale (F9): random-answer path, small context window (`RANDOM_ANSWER_CONTEXT_LENGTH`), lower duplication cost. The reusable `computeMemoryExcludes` helper (§5.4) lets this path adopt dedup later by building its `deque` of `EnsuredMessage`s first, running the helper, then formatting with `cache=self.cache, excludeMemoryIds=excludes[i]`. `[architect review: CLARIFICATION — only DEDUP (excludeMemoryIds) is deferred. Basic memory RENDERING (cache=self.cache at :893 and :936) is IN-SCOPE — without it, the non-reply path silently drops all memories. Phase 3 adds cache=self.cache; the future dedup adoption adds excludeMemoryIds.]`
- **Any schema/migration change** — none needed; `metadata` shape is unchanged (compact IDs already persisted).
- **`setUserMemories` rename** to `setMemoryIds` — deferred (minimizes churn).

## 11. Resolved decisions (architect review)

`[architect review: all 5 open questions resolved. Section retitled from "Open questions" to "Resolved decisions."]`

- **(a) Pre-scan approach — DECIDED: BUILD-then-DEDUP-then-FORMAT.** Build all rendered `EnsuredMessage`s first (without formatting), run `computeMemoryExcludes`, then format. Rationale: reuses `getMemoryIds()` (single source of truth for the metadata shape), avoids duplicating JSON-parsing logic in a raw-JSON pre-scan. The extra cost of building `EnsuredMessage`s slightly earlier is negligible — they must be built for formatting anyway. The condense-replay slicing complexity is manageable: the keepFirstN loop and summary loop are sequential (not interleaved) in the current code, so the restructure is a clean split (see §5.4 architect-review note for details). `[Updated in §5.4.]`

- **(b) Remove vs deprecate `injectMemories` — DECIDED: REMOVE outright.** The repo is the sole consumer; a deprecated no-op param invites confusion and must be cleaned up later anyway. All 15 call sites are mechanical updates. `scripts/reproduce_llm_dialog.py` is a dev tool, not production code. Removal happens in revised Phase 4 (after all callers are updated in Phases 2-3), keeping the codebase green at each phase boundary. `[Updated in §3 decision 7 and §7 Phase 4.]`

- **(c) Cache-warm mechanism — DECIDED: dedicated `CacheService.warmMemoriesByIds(entries: Sequence[SingleMemoryDict]) -> None` method.** Reaching into `self.cache.memories.set(...)` from a handler is a layering violation and makes the `keepId=False` shape-alignment invariant fragile (it would be enforced at the call site, not in the cache layer). The dedicated method encapsulates the strip-`id`-and-set logic where the invariant lives, is independently testable, and mirrors the encapsulation of `getMemoriesByIds`. The method writes entries with `id` stripped, matching the `keepId=False` shape that `getMemoriesByIds` stores. `[Updated in §3 decision 8 and §5.3.]`

- **(d) `handleRandomMessage` non-reply scope — DECIDED: DEFER dedup only; RENDER is in-scope.** The non-reply path uses a different query (`getChatMessagesSince`) and a small context window (`RANDOM_ANSWER_CONTEXT_LENGTH`), so duplication cost is lower. The reusable `computeMemoryExcludes` helper enables a trivial future adoption. HOWEVER, basic memory rendering (`cache=self.cache` at `:893` and `:936`) is in-scope — without it, the path silently drops all memories (a regression). Phase 3 adds `cache=self.cache`; the future dedup adoption adds `excludeMemoryIds`. `[Updated in §10 and §7 Phase 3.]`

- **(e) Reusable-helper placement — DECIDED: module-level function in `base.py`.** The function is a pure transformation over a sequence of `EnsuredMessage`s — it needs no handler instance or `self`. Placing it on `BaseBotHandler` as a `@staticmethod` would require importing `BaseBotHandler` to use it from `llm_messages.py` (circular-import risk). Placing it on `EnsuredMessage` as a `@staticmethod` would couple the rendering-pipeline dedup algorithm to the model class — the algorithm is a property of the rendering pipeline, not the individual message. Module-level in `base.py` is the lightest coupling and lets `handleRandomMessage` import it without a handler instance. `[Updated in §5.4.]`
