# Condensed-Context Retrieval

Durable notes for the conversation-condensing machinery and the ADR-019 "condensed-context retrieval" feature (record which message IDs each summary covers, render summaries as JSON, expose a `get_messages_by_ids` LLM tool). Read this when touching `LLMService.condenseContext()`, `CondensingDict` / `CondensedDateRangeDict`, the `condensedThread` / `randomContext` persistent write paths, the `get_messages_by_ids` tool, or `/scripts/check_condensing.py`.

Companion memory: [`user-memories.md`](user-memories.md) documents `getThreadByMessageForLLM` (which hosts Path A) and the ADR-018 lazy-render discipline this feature mirrors.

## Architecture

**Invariant:** all original messages are ALWAYS retained in `chat_messages`. Condensing only ADDS summary metadata; it never deletes source rows. The originals stay queryable — ADR-019's `get_messages_by_ids` tool relies on this.

There is one core primitive and three condensing pathways (two persistent, one transient):

### `LLMService.condenseContext()` — the core primitive

Location: [`/internal/services/llm/service.py`](/internal/services/llm/service.py). Post-simplification signature:

```
condenseContext(messages, model, *, keepFirstN=0, keepLastN=1,
                condensingModel=None, condensingPrompt=None,
                condensingSystemPrompt=None, maxTokens=None, force=False)
```

- **Always** returns `Tuple[Sequence[ModelMessage], Dict[int, CondensingDict]]`. First element = condensed message list (head + summaries + tail); second = coverage map keyed by body-index → `CondensingDict` (computed inside via `generateCondensingDict` reading `ModelMessage.source`). When no condensing occurs the second element is `{}`. There is NO `returnCoverage` kwarg (deleted in the 2026-07-13 simplification).
- Two modes:
  - (a) **No `condensingModel`** → pure front-truncation.
  - (b) **With `condensingModel`** → body split into batches, each batch summarized via `condensingModel.generateText`; the summary is emitted as `ModelMessage(role="user", content=renderCondensedSummary(resDict), source=resDict)`.
- First message auto-preserved (bumps `keepFirstN += 1`) when its `role == "system"`.
- Returns a NEW list; never mutates input.

### Path A — Handler-level `condensedThread` (PERSISTENT)

`getThreadByMessageForLLM` ([`/internal/bot/common/handlers/base.py`](/internal/bot/common/handlers/base.py)) reads `eRootMessage.metadata["condensedThread"]` = `List[CondensingDict]`, injects each as `role="user"` via `renderCondensedSummary`, and skips the covered raw messages. If the rebuilt context still exceeds 50% of the model context, it re-condenses and writes back via `updateChatMessageMetadata`. The caller unpacks `condensedRet, condensingDictMap = await self.condenseContext(...)` and extends the cache via `condenseCache.extend(condensingDictMap.values())` — no parallel-list machinery.

### Path B — Random-answer `randomContext` (PERSISTENT)

`handleRandomMessage` ([`/internal/bot/common/handlers/llm_messages.py`](/internal/bot/common/handlers/llm_messages.py)), when context exceeds `MAX_RANDOM_CONTEXT_MESSAGES`, calls `condenseContext(force=True)`, unpacks `condensedRet, condensingDictMap = ...`, and — if `condensingDictMap` is non-empty — writes `ensuredMessage.metadata["randomContext"] = mergeCondencingDicts(condensingDictMap.values())`. The write is SKIPPED when the map is empty (nothing meaningful to persist). Subsequent loops stop walking older context when they hit a `randomContext` boundary.

### Path C — Service-level auto-condense (TRANSIENT)

`generateTextViaLLM` ([`/internal/services/llm/service.py`](/internal/services/llm/service.py)) calls `condenseContext` at the top of every loop iteration against `maxTokens = contextSize * maxTokensCoeff` (default `0.8`). NOT persisted — it guards the model window during the current call (including tool-call inflation) and re-runs fresh every call. Path C unpacks `_messages, _ = await self.condenseContext(...)` (byte-identical behaviour; ignores the coverage map).

### "Condensed ≠ raw" visibility (critical)

Both persisted paths inject summaries as `role="user"` messages — there is NO distinct role or tag marking a summary once it is in the `ModelMessage` list. The LLM sees condensed summaries as ordinary user-turn content. The only structural marker is the `CondensingDict` / `randomContext` metadata record, which lives in the DB, not in the `ModelMessage` payload.

### Message-ID retrieval (pre-feature landscape)

- `getChatMessageByMessageId(chatId, messageId, *, dataSource=None) -> Optional[ChatMessageDict]` ([`/internal/database/repositories/chat_messages.py`](/internal/database/repositories/chat_messages.py)) — single-row PK lookup, returns the full row with a user JOIN.
- `getChatMessagesByRootId` — whole-thread retrieval.
- The `/search` command + `searchChatMessages` repo did semantic/filter search but did NOT expose single-ID lookup (the gap ADR-019's `get_messages_by_ids` tool fills).
- The `/search` command itself explicitly does NOT produce an LLM summary (raw human-readable output only). The `search_messages` LLM tool is separate (semantic/filter, returns dicts to the LLM).

## ADR-019 feature (IMPLEMENTED 2026-07-12 → SIMPLIFIED 2026-07-13)

Decision record: [`../architecture.md`](../architecture.md) ADR-019. Spec: [`../../archive/plans/condensed-context-retrieval-plan-v1.md`](../../archive/plans/condensed-context-retrieval-plan-v1.md).

**Feature:** record which message IDs each condensed summary covers + structured metadata (participants / dateRange / messageCount) + render summaries as JSON (fixing the latent raw-text asymmetry) + add `get_messages_by_ids` LLM tool for on-demand retrieval of condensed originals.

**Simplification (2026-07-13):** the original caller-side `returnCoverage` / `indexToEntry` / `CondenseBatchCoverage` machinery was DELETED and replaced by `ModelMessage.source`-based coverage computed inside `condenseContext` via `generateCondensingDict`. The simplified design is what shipped: coverage is produced centrally and the callers (Path A / Path B) just consume `condensingDictMap.values()`.

### What shipped (durable code anchors — line numbers drift, re-locate by symbol)

- **[`/internal/bot/models/message_metadata.py`](/internal/bot/models/message_metadata.py):**
  - `CondensedDateRangeDict = TypedDict("CondensedDateRangeDict", {"from": float, "to": float})` — FUNCTIONAL syntax (`from` is a reserved keyword; class-body syntax is a `SyntaxError`).
  - `CondensingDict` — only `text` required; ALL other fields `NotRequired` (`tillMessageId` / `tillTS` / `messageIds` / `participants` / `dateRange` / `messageCount`).
  - `MetadataDict.randomContext` widened `str → Union[str, CondensingDict]`.
  - `CondensedSummaryKind(StrEnum)` — `CONDENSED = "condensed"`, deliberately separate from `MessageType` (a render-only construct; the JSON shape is structurally disjoint from real user messages, so the shared `"type"` key never collides).
  - `renderCondensedSummary(data: CondensingDict) -> str` — JSON renderer; `CondensingDict`-only signature (legacy `str` rows are pre-wrapped by the read site before calling). Output shape: `{type:"condensed", coveredMessageIds:[...], participants:[...], dateRange:{"from":<ISO>,"to":<ISO>}, messageCount:N, summary:"..."}`; falsy-drop mirrors `formatForLLM` (empty/absent fields omitted, never `null`); `type` + `summary` always present.
  - `mergeCondensingDicts(dictList: Iterable[CondensingDict]) -> CondensingDict` — unions multiple dicts (`text` = `"\n".join`; `messageIds` plain concat — **no de-dup** (the source docstring claims de-dup via `asStr()` first-seen but the code at `message_metadata.py:314-315` just `extend`s); `participants` set-unique but **NOT sorted** (`list(participants)` from a `MutableSet[str]` at `:331`, iteration order unspecified); `dateRange` min/max; `messageCount` sum). Used by Path B. *(Doc-drift note: the source docstring of `mergeCondensingDicts` itself carries the same stale "de-duped" / "sorted-unique" wording; ADR-019 §725 in `architecture.md` repeats it.)*

- **[`/internal/services/llm/service.py`](/internal/services/llm/service.py):**
  - `generateCondensingDict(text, messages) -> CondensingDict` (module fn) — the coverage producer. Walks the batch `ModelMessage`s and reads `.source`: `EnsuredMessage` → extract messageId / username / `date.timestamp()`; `dict` / `CondensingDict` → union (re-condense cascade); `None` → `logger.warning` + skip metadata extraction (but the position IS still counted toward `messageCount` per `service.py:107-108` — `messageCount += 1` runs unconditionally in the `None` branch; the source docstring of `generateCondensingDict` itself claims "NOT counted" — that docstring is stale). Returns `CondensingDict` with `text` + conditionally-populated `messageIds` / `participants` / `dateRange` (`{from:min ts, to:max ts}`, omitted if none) / `messageCount`. Does NOT set `tillMessageId` / `tillTS`. Wrapped in try/except → fallback `CondensingDict(text=respText)` on failure (summary preserved, coverage dropped).
  - `condenseContext` **always** returns `Tuple[Sequence[ModelMessage], Dict[int, CondensingDict]]` (no `returnCoverage` kwarg); coverage computed inside via `generateCondensingDict`; Path C unpacks `_messages, _`.

#### Handlers, repository, and config anchors

- **[`/internal/bot/common/handlers/base.py`](/internal/bot/common/handlers/base.py)** (`getThreadByMessageForLLM`): TWO `condenseContext` call sites (initial condense + re-condense cascade); unpacks `condensedRet, condensingDictMap`; `condenseCache.extend(condensingDictMap.values())` (or `= list(...)` for the cascade); injection site calls `renderCondensedSummary(condensedMessage)`.

- **[`/internal/bot/common/handlers/llm_messages.py`](/internal/bot/common/handlers/llm_messages.py)** (`handleRandomMessage`): unpacks `condensedRet, condensingDictMap`; if non-empty writes `mergeCondensingDicts(condensingDictMap.values())` to `randomContext`. The read site in `ensured_message.py` (`toModelMessageList`) pre-wraps legacy `str` into `CondensingDict(text=...)` → `renderCondensedSummary(...)`.

- **[`/internal/bot/common/handlers/chat_search.py`](/internal/bot/common/handlers/chat_search.py)**: `get_messages_by_ids` tool (registered in `ChatSearchHandler.__init__` as a normal `registerTool(...)` alongside the other search tools; reuses `_formatMessageDict`; never-raise; batch fetch). Constant `ToolName.GET_MESSAGES_BY_IDS` + `MAX_GET_MESSAGES_BATCH = 32` (plan §3.8 proposed 50; implementation chose 32) in [`/internal/bot/constants.py`](/internal/bot/constants.py).

- **[`/internal/database/repositories/chat_messages.py`](/internal/database/repositories/chat_messages.py)**: `getChatMessagesByMessageIds(chatId, messageIds, *, dataSource=None)` — portable `IN (:id0, ...)` named placeholders; `ORDER BY c.date ASC`; early-returns `[]` on empty input; does NOT dedup input IDs (caller's responsibility). Backs the tool.

- **[`/configs/00-defaults/bot-defaults.toml`](/configs/00-defaults/bot-defaults.toml)**: the Russian `chat-prompt-suffix` block documents the condensed-summary JSON shape (`type:"condensed"` + field bullets) + the `get_messages_by_ids` tool, so the model is explicitly told originals are retrievable.

### `get_messages_by_ids` LLM tool

Registered in `ChatSearchHandler.__init__` ([`/internal/bot/common/handlers/chat_search.py`](/internal/bot/common/handlers/chat_search.py)); constant `ToolName.GET_MESSAGES_BY_IDS`, [`/internal/bot/constants.py`](/internal/bot/constants.py). Parameter declared as plain `ARRAY` — the `extra={"items": {"type": "string"}}` schema-forcing line is **commented out** at `chat_search.py:363` (was intended to force strings because `MessageId` is `int|str`, but never landed in the emitted schema). The implementation compensates with `str(mid).strip()` + `MessageId(midStr)` runtime coercion (never-raise when the model violates the implicit schema). Input is de-duped via a `seen: set[str]` (first-seen order), blank/`None` entries dropped, clamped to `MAX_GET_MESSAGES_BATCH = 32`. Returns `{"done": True, "messages": [...EnsuredMessage JSON...], "notFound": [...], "count": N}` on success, or `{"done": False, "error": "..."}` on any failure; reuses `_formatMessageDict`. Whole body wrapped in try/except (never-raise). *(Doc-drift note: ADR-019 §729 in `architecture.md` and the source docstring at `chat_search.py:975-977` still describe `extra={"items": ...}` as live — both stale.)*

**Two-layer gating** (note: NO handler restructuring, NO `manager.py` change):
1. `[search-history].enabled` via `ChatSearchHandler`'s existing conditional registration (the tool rides the handler's gate).
2. At chat time, gated solely by `USE_TOOLS` (the model is never sent the tool when `USE_TOOLS=false`). NOT gated by `ALLOW_TOOLS_COMMANDS` (which gates only slash commands of `CommandCategory.TOOLS`).
3. Additionally **NOT** gated on `EMBEDDINGS_ENABLED` or any search-specific flag — pure DB lookup, available whenever chat-search is on (even with semantic search disabled).

The config section is `[search-history]` (NOT `[chat-search]`), accessed via `configManager.getSearchHistoryConfig()`.

## Durable gotchas / lessons

- **`CondensedDateRangeDict` MUST use functional TypedDict syntax** — `from` is a Python reserved keyword; class-body syntax (`from: float`) is a `SyntaxError`. Functional syntax `TypedDict("...", {"from": float, "to": float})` uses string keys. Field access is subscript-only (`d["from"]`), never attribute.
- **`tillMessageId` / `tillTS` are NOT set by `generateCondensingDict`.** They are legacy boundary markers, `NotRequired` on `CondensingDict`. Readers use `in` / `.get()` checks and fall back to `dateRange["to"]` / `messageIds[-1]` when absent (see the `base.py` injection-site fallback chain).
- **TWO `condenseContext` call sites in `getThreadByMessageForLLM`** (initial condense + re-condense cascade), not one. Both unpack the tuple.
- **Path B skips the `randomContext` write when `condensingDictMap` is empty** — nothing meaningful to persist.
- **Gating detail:** the `get_messages_by_ids` tool rides `[search-history].enabled`. The config section is `[search-history]` NOT `[chat-search]`; accessed via `configManager.getSearchHistoryConfig()`. NO handler restructuring needed. NOT gated on `EMBEDDINGS_ENABLED` (pure DB lookup).
- **PRE-EXISTING infinite-loop bug in `condenseContext` batch-shrink — FIXED by the 2026-07-13 simplification.** Original defect: the `while` loop head recomputed `currentBatchLen = min(batchLength, len(body) - startPos)` from the fixed `batchLength` every iteration, clobbering any shrunk value → a shrunk-but-not-skipped oversized batch never progressed (only escaped via the `currentBatchLen == 1` skip). The fix (`condenseContext` batch loop): the loop head now reads `min(currentBatchLen, ...)` — the shrunk value persists across the `continue`. The loop provably terminates (each iteration either advances `startPos` or strictly decreases `currentBatchLen`, floored at 1).
  - **Regression-test GAP:** no test covers the shrink path. All overflow tests use `batchLength = 1` and hit only the skip-1 branch; the dynamic shrink (`currentBatchLen >= 2` → divide-by-overshoot-ratio → `-2` → floor at 1) is untested. A reversion to `min(batchLength, ...)` would only be caught by a test that would hang (timeout), not fail cleanly.
  - **Doc-drift note:** ADR-019 in [`../architecture.md`](../architecture.md) still carries a pre-fix "known pre-existing bug, tracked separately, do not document a fix" note, reflecting its pre-2026-07-13 authoring. This memory (sourced from `teamlead-memory.md`) is current: the bug is fixed.

## Dev tool

`scripts/check_condensing.py` ([`/scripts/check_condensing.py`](/scripts/check_condensing.py)) — standalone dev tool to A/B-test condensing-prompt changes. Added in the same feature window. Flags: `--chat-id` / `--message-id` (required) + `--config-dir` (repeatable; `00-defaults` implicit) + `--env` + `--dry-run` + `--verbose`. Mirrors `getThreadByMessageForLLM`; calls `condenseContext(..., force=True)`; prints BEFORE/AFTER token counts.

## Cross-references

- [`../architecture.md`](../architecture.md) ADR-019 — decision record (coverage tracking + lazy JSON render + `get_messages_by_ids` tool). Linked to the file, not a deep anchor.
- [`../../archive/plans/condensed-context-retrieval-plan-v1.md`](../../archive/plans/condensed-context-retrieval-plan-v1.md) — authoritative implementation spec.
- [`user-memories.md`](user-memories.md) — `getThreadByMessageForLLM` (Path A host) and the ADR-018 lazy-render discipline this feature mirrors.
- [`chat-history-search.md`](chat-history-search.md) — `ChatSearchHandler`, `/search`, and the `search_messages` / `list_users` / `get_thread` tools alongside which `get_messages_by_ids` is registered.
- [`../handlers.md`](../handlers.md) — `ChatSearchHandler` row; [`../configuration.md`](../configuration.md) §`[search-history]`; [`../database.md`](../database.md) `getChatMessagesByMessageIds` row.
