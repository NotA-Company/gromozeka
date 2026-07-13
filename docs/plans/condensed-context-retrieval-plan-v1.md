# Condensed-Context Retrieval — Design Plan v1

- **Status:** IMPLEMENTED (2026-07-12) — all 6 phases shipped (P1 additive foundation → P2 `condenseContext` `returnCoverage` → P3 caller wiring → P4 shared render helper + both injection sites + chat-prompt-suffix → P5 `get_messages_by_ids` tool → P6 docs). 3210 tests green; Gate-2 review passed. Branch `user-memory-v2`, baseline `b73c256`. Architecture decision: ADR-019 in [`docs/llm/architecture.md`](../llm/architecture.md).
- **SIMPLIFIED (2026-07-13):** The `returnCoverage` / index-range / parallel-list (`indexToEntry`/`indexToEntry2`) approach described in §3.3 below was **REPLACED** by `ModelMessage.source`-based coverage computed *inside* `condenseContext` via the `generateCondencingDict` helper. `condenseContext` now **always** returns `Tuple[Sequence[ModelMessage], Dict[int, CondensingDict]]` (no `returnCoverage` kwarg); callers consume `condencingDictMap.values()` directly. The deleted symbols include: `CondenseBatchCoverage`, `_condensingDictFromCoverage`, `buildRandomContextDict`, `buildCondensingFields`, the `indexToEntry`/`indexToEntry2` parallel lists, and the `returnCoverage` kwarg + `@overload` stubs. `CondensingDict` was further relaxed: only `text` is required now; `tillMessageId`/`tillTS` are `NotRequired` and NOT set by `generateCondencingDict`. `renderCondensedSummary` was narrowed to `CondensingDict`-only (no `str` branch — the read site pre-wraps legacy `str` rows). **See ADR-019 in [`docs/llm/architecture.md`](../llm/architecture.md) for the actual current design.** The plan body below is preserved as a historical design document; do not follow its §3.3 caller-side index-range approach for new work.
- **Date:** 2026-07-11
- **Author:** architect
- **Scope:** Paths A (`condensedThread`) and B (`randomContext`). Path C (transient service-level auto-condense) is **out of scope**.
- **Precedent / structural model:** ADR-018 (Memories Context Dedup) — additive-first, store-IDs-render-lazily, 6 independently-green phases. This plan mirrors that shape.
- **Companion dev tool:** [`scripts/check_condensing.py`](../../scripts/check_condensing.py) (added 2026-07-11) — A/B-tests condensing-prompt changes; prerequisite for the optional prompt tweak (§9).

---

## 1. Background & Motivation

When the LLM's conversation context is condensed (older messages summarized to fit the context window), the **original messages are always retained** in `chat_messages` (condensing only adds summary metadata; it never deletes source rows — verified: `internal/services/llm/service.py:606` `condenseContext` returns a *new* list, never mutates input; both persistent write sites persist metadata only). But three problems exist today:

1. **Lost detail, no recovery path.** Once condensed, the LLM sees only the summary text. There is no tool to fetch the originals — the summary is the ceiling of detail for those messages for the rest of the conversation.

2. **Unidentifiable coverage.** The persisted `CondensingDict` (`internal/bot/models/message_metadata.py:76`) records only a *boundary* marker (`tillMessageId`/`tillTS`) — not *which* messages a summary actually covers. Re-condense cascades and multi-batch summaries lose precision.

3. **Latent render asymmetry.** Real user messages are rendered as **JSON** (`EnsuredMessage.formatForLLM` JSON branch, `internal/bot/models/ensured_message.py:1158-1177`, documented to the LLM in `configs/00-defaults/bot-defaults.toml:199-215`). Condensed summaries are injected as **raw text** `role="user"` at two sites — `internal/bot/common/handlers/base.py:812` (Path A) and `internal/bot/models/ensured_message.py:1229-1231` (Path B). This is an undocumented asymmetry the LLM has to silently accommodate.

This feature resolves all three:

1. Records the full covered-message-ID list (+ participants, date range, count) on each summary.
2. Renders summaries as JSON (consistent with real user messages), carrying the coverage metadata.
3. Adds an LLM tool `get_messages_by_ids` so the model can fetch condensed originals on demand when a summary is insufficient.

All new metadata fields are **derivable from the messages being condensed at zero extra LLM cost** (sender logins, timestamps, count — all already on the source rows). The condensing model's output text stays as-is.

---

## 2. Locked Decisions Summary (agreed with user — do not re-litigate)

| # | Decision | Detail |
|---|----------|--------|
| 1 | Scope = Path A + Path B | Path A `condensedThread` (handler-level, `chat_messages.metadata.condensedThread`); Path B `randomContext` (handler-level, `chat_messages.metadata.randomContext`). Path C (transient `generateTextViaLLM` loop) OUT OF SCOPE. |
| 2 | Extend `CondensingDict`, store fields, render lazily | Add `messageIds`/`participants`/`dateRange`/`messageCount`. KEEP `tillMessageId`/`tillTS` for backwards-compat reads. Renderer falls back gracefully when new fields absent. |
| 3 | Path B reshape `str → single CondensingDict` | NOT a list (only one summarization possible for random context). Legacy `str` read defensively. |
| 4 | Render as JSON (not text prefix) | Resolves the latent asymmetry. Shared helper called from both injection sites. |
| 5 | `chat-prompt-suffix` documents new shape + tool | Russian, matching existing suffix style. `BOT_OWNER_SYSTEM`-gated; ships in `00-defaults`. |
| 6 | `get_messages_by_ids` tool, separate from `search_messages` | In `ChatSearchHandler`. Registration rides the handler's existing conditional gate (`[search-history].enabled` at `manager.py:540`) — **no handler restructuring**. Three-layer gating (see §3.7): (1) `[search-history].enabled` via handler registration, (2) `ALLOW_TOOLS_COMMANDS` per-chat master toggle, (3) NOT gated on `EMBEDDINGS_ENABLED`/any search-specific flag (pure DB lookup). List param (batch fetch; `items: string` in the emitted schema). Never-raise. Chat-scoped via `extraData["ensuredMessage"]`. |
| 7 | Optional prompt tweak = follow-up | Feeding `participants`/`dateRange` into the condensing prompt is a post-implementation experiment (via `scripts/check_condensing.py`), NOT a launch blocker. |

> **Note:** Decision #6's earlier "UNCONDITIONAL registration" wording is **superseded** (resolved with user 2026-07-11 — see §3.7 + §11 #1). The tool registers via a normal `self.llmService.registerTool(...)` call in `ChatSearchHandler.__init__` and rides the handler's existing `[search-history].enabled` gate (`manager.py:540`). **No handler-registration restructuring** is needed: no dropping the manager-level gate, no sub-gating inside `__init__`, no moving the tool elsewhere.

---

## 3. Detailed Design

### 3.1 `CondensingDict` TypedDict evolution

**File:** `internal/bot/models/message_metadata.py:76`

Current shape (all required):

```python
class CondensingDict(TypedDict):
    text: str
    tillMessageId: MessageId
    tillTS: float
```

New shape (new fields `NotRequired` for backwards-compat reads):

```python
CondensedDateRangeDict = TypedDict(
    "CondensedDateRangeDict",
    {"from": float, "to": float},
)
"""Storage shape for the date range covered by a condensed summary.

Two unix-timestamp floats keyed ``from``/``to``. The JSON key ``from`` is a
Python reserved keyword, so this TypedDict uses functional syntax (class-body
syntax cannot express a field named ``from``). This is the *storage* form
persisted on :class:`CondensingDict.dateRange`; the render helper converts
these floats to ISO strings at call-time — ISO strings are NOT pre-baked into
storage.
"""


class CondensingDict(TypedDict):
    """Condensed-summary record persisted under ``metadata.condensedThread``
    (Path A, a list of these) or ``metadata.randomContext`` (Path B, a single
    one).

    Legacy rows (pre-feature) carry only ``text``/``tillMessageId``/``tillTS``
    and are read defensively — readers fall back gracefully when the new fields
    are absent (§3.5). New writes populate ``messageIds`` as the authoritative
    coverage list; ``tillMessageId``/``tillTS`` are kept for backwards-compat
    reading by older code paths and as a cheap boundary marker.

    Required fields (present on ALL rows, legacy and new):
        text: The condensing model's summary text (unchanged).
        tillMessageId: Legacy boundary marker — last covered message ID.
        tillTS: Legacy boundary marker — unix timestamp of last covered msg.

    Optional fields (NotRequired — absent on legacy rows, present on new):
        messageIds: Authoritative list of covered message IDs (new).
        participants: Sorted unique sender logins of covered messages (new).
        dateRange: CondensedDateRangeDict — ``from``/``to`` unix-timestamp
            floats covering the summarized messages (new).
        messageCount: Number of original messages this summary covers (new).
    """
    text: str
    tillMessageId: MessageId
    tillTS: float
    messageIds: NotRequired[List[MessageId]]
    participants: NotRequired[List[str]]
    dateRange: NotRequired[CondensedDateRangeDict]
    messageCount: NotRequired[int]
```

**Design notes:**

- The original 3 fields (`text`/`tillMessageId`/`tillTS`) remain **required** on `CondensingDict` (they exist on all legacy rows); the 4 new fields are `NotRequired`, so legacy rows that lack them are read defensively without type errors. The renderer (§3.5) is the single place that knows which combination is valid.
- `CondensedDateRangeDict` uses **functional TypedDict syntax** (an assignment, not `class`) because `from` is a Python reserved keyword and cannot appear as an attribute name in class-body syntax. It is the **storage shape**: two unix-timestamp floats keyed `from`/`to`. The render helper (§3.4, added in P4) converts these to ISO strings at call-time (`datetime.fromtimestamp(ts, UTC).isoformat()`) — ISO strings are NOT pre-baked into storage, matching how real messages render `date` (`self.date.isoformat()` at `ensured_message.py:1164`).
- `participants` = sorted unique sender logins (`username` column, already JOIN'd in every chat-message query — see `getChatMessageByMessageId` SQL at `internal/database/repositories/chat_messages.py:314`). No extra DB cost.
- `messageIds` is `List[MessageId]` (wraps `int|str`, Telegram=int/Max=str — see `internal/models/types.py:16`). Serialized to JSON as strings via `MessageId.asMessageId()` at render-time, matching real messages' `messageId` field (`ensured_message.py:1165`).

**Backwards-compat read strategy** — see §8 (matrix). Summary: `.get(field)` everywhere; absent new fields → renderer emits empty/null equivalents (§3.5).

### 3.2 Path B reshape: `randomContext` `str → CondensingDict`

**File:** `internal/bot/models/message_metadata.py:111` (`MetadataDict.randomContext`)

```python
class MetadataDict(TypedDict, total=False):
    ...
    # Was: randomContext: str
    # Now: single CondensingDict (new writes) OR legacy str (old rows).
    # The reader (EnsuredMessage.toModelMessageList) handles both via the
    # shared renderer (§3.5).
    randomContext: Union[str, CondensingDict]
    ...
```

**Write site** (`internal/bot/common/handlers/llm_messages.py:941-947`): currently joins summary texts into a flat `str`. New behavior: build a single `CondensingDict` with coverage metadata (how the coverage is obtained — see §3.3; the caller maintains a parallel id list as it walks `getChatMessagesSince` rows at `llm_messages.py:888-914`).

```python
# NEW (illustrative — exact field population in P3):
condensedRet, coverage = await self.llmService.condenseContext(
    contextMessages,
    chatSettings[ChatSettingsKey.CHAT_MODEL].toModel(),
    keepFirstN=0,
    keepLastN=0,
    condensingModel=...,
    condensingPrompt=...,
    condensingSystemPrompt=...,
    force=True,
    returnCoverage=True,
)
# Path B joins all batches into ONE summary (only one randomContext possible).
# Union the coverage of all batches into a single CondensingDict.
ensuredMessage.metadata["randomContext"] = _buildCondensingDictFromCoverage(
    summaryText="\n".join(m.content for m in condensedRet),
    coverage=coverage,
    indexToMessageId=contextMessageIds,   # parallel list, §3.3
    rows=contextRows,                      # parallel ChatMessageDict rows
)
```

**Read site** (`internal/bot/models/ensured_message.py:1229-1231`): defensive — see §3.5.

### 3.3 `condenseContext` signature evolution — THE key decision

**Current** (`internal/services/llm/service.py:606-618`):

```python
async def condenseContext(
    self, messages, model, *,
    keepFirstN=0, keepLastN=1, condensingModel=None,
    condensingPrompt=None, condensingSystemPrompt=None,
    maxTokens=None, force=False,
) -> Sequence[ModelMessage]:
```

**The problem.** The caller (`getThreadByMessageForLLM` at `base.py:855,880-901`) has no way to know which input messages each output summary batch covered, so it cannot populate `messageIds`/`participants`/`dateRange`/`messageCount`.

**Constraint.** `condenseContext` operates on `ModelMessage` objects (`lib/ai/models.py:442`), which carry ONLY `role`/`content`/`contentKey`/`toolCalls`/`toolCallId`/`weight` — **no message IDs, no sender logins, no timestamps, no metadata field**. So coverage *metadata* (IDs/participants/dates) cannot come from `condenseContext` alone; it lives on the caller's source `EnsuredMessage`/`ChatMessageDict` rows.

#### Options evaluated

| Option | Verdict |
|--------|---------|
| **(a)** Return richer result `Tuple[Sequence[ModelMessage], List[Coverage]]` | **RECOMMENDED** (refined below) |
| **(b)** Annotate `ModelMessage` directly with a metadata field | **REJECTED.** `ModelMessage` has no metadata field; adding one invades a core `lib/ai/` class touched by every provider, its `toDict`/`fromDict` serialization (`models.py:487-509`), and token-counting. Too invasive for this feature. |
| **(c)** Caller computes coverage by position (knows keepFirstN/keepLastN) | **REJECTED.** The batching is NOT deterministically reconstructible: the inner loop (`service.py:734-743`) dynamically shrinks batches when a batch exceeds `summaryMaxTokens` *and* skips single oversized messages (`:735-738`). The caller would have to re-implement the batching. Brittle. |
| **(d)** Hybrid | Subsumed by the refined (a). |

#### Recommendation: (a), refined — `condenseContext` returns per-batch **index ranges**; the **caller** enriches with metadata

Rationale for the refinement: `condenseContext` only *has* ModelMessages and their indices. The coverage *metadata* (messageIds/participants/dateRange) is the caller's domain (it owns the source rows). So `condenseContext` reports **which input indices each summary covers** (its own internal state — `startPos`/`currentBatchLen` at `service.py:725-760`), and the caller maps those indices to source rows it already holds. Clean separation: service layer reports indices; bot layer owns the index→metadata mapping.

**New keyword-only param** (additive — default preserves Path C unchanged):

```python
async def condenseContext(
    self, messages, model, *,
    keepFirstN=0, keepLastN=1, condensingModel=None,
    condensingPrompt=None, condensingSystemPrompt=None,
    maxTokens=None, force=False,
    returnCoverage: bool = False,              # NEW (additive, default False)
) -> Union[Sequence[ModelMessage], Tuple[Sequence[ModelMessage], List[CondenseBatchCoverage]]]:
    """...
    Args:
        ...
        returnCoverage: When True, return ``(messages, coverage)`` where
            ``coverage`` is one :class:`CondenseBatchCoverage` per summary
            batch emitted, each recording the index range of the input
            ``messages`` sequence it covers. Indices are relative to the
            FULL input ``messages`` list (head offset applied internally).
            When False (default), return only the condensed messages
            (unchanged behaviour — Path C ``generateTextViaLLM`` unaffected).
            Only meaningful when ``condensingModel`` is provided (pure
            truncation mode produces no summaries; coverage list is empty).
    """
```

**New TypedDict** (service-layer — lives in `internal/services/llm/service.py` or a sibling; NOT in the bot-layer `message_metadata.py`, to keep the condense contract decoupled from bot types):

```python
class CondenseBatchCoverage(TypedDict):
    """Coverage descriptor for ONE condensed summary batch.

    Emitted by :meth:`LLMService.condenseContext` when called with
    ``returnCoverage=True``. Indices are relative to the FULL input
    ``messages`` sequence the caller passed in (the head/system-prompt offset
    is applied internally before reporting), so the caller can slice its own
    parallel metadata list (aligned 1:1 to the input ``messages``) directly.

    Attributes:
        summaryText: The condensing model's output text for this batch
            (identical to the ``content`` of the corresponding
            ``ModelMessage(role="user")`` in the returned messages list).
        coveredFromIndex: Inclusive start index into the input ``messages``.
        coveredToIndex: Exclusive end index into the input ``messages``.
    """
    summaryText: str
    coveredFromIndex: int
    coveredToIndex: int
```

**Implementation in `condenseContext`** (service.py, body-summarization loop at `:725-760`): record `(startPos, startPos + currentBatchLen)` per successful `newBody.append` (`:759`), then map each to full-input indices by adding the head offset (`keepFirstN` after the system-prompt bump at `:652`). Accumulate into a `coverage: List[CondenseBatchCoverage]`; return `(ret, coverage)` when `returnCoverage=True`, else `ret` (unchanged).

**Caller responsibility (Path A — `getThreadByMessageForLLM`, base.py):** maintain a parallel list `indexToMessageId: List[MessageId]` and `indexToRow: List[ChatMessageDict]` aligned 1:1 to the `ret` list it builds (each `toModelMessageList` call may emit multiple ModelMessages — tag every emitted ModelMessage with the source row's messageId). After condensing with `returnCoverage=True`, for each `CondenseBatchCoverage` slice `indexToRow[coveredFromIndex:coveredToIndex]` → compute `messageIds`/`participants`/`dateRange`/`messageCount`. Build the `CondensingDict` from that.

**Re-condense cascade** (`base.py:880-901`): the second `condenseContext` call re-summarizes existing summaries. Each new merged summary covers the UNION of the original batches' coverage. The caller unions the `messageIds`/`participants`/`dateRange`/`messageCount` of the batches that got merged. (P3 implements this; the union is straightforward set/list merge over the coverage descriptors.)

**Why this is safe for Path C:** `generateTextViaLLM` (`service.py:519`) calls `condenseContext` without `returnCoverage` → default `False` → identical return type and behaviour. Zero changes to Path C.

#### Caller-side helper (bot layer)

A small pure helper computes the `CondensingDict` fields from a coverage slice. Lives in `internal/bot/common/handlers/base.py` (or `message_metadata.py`) — P3 decides the final home; recommend `message_metadata.py` since it owns `CondensingDict`:

```python
def buildCondensingFields(
    rows: Sequence[ChatMessageDict],
) -> Dict[str, Any]:
    """Compute messageIds/participants/dateRange/messageCount from covered rows.

    Pure function over the ChatMessageDict rows a summary covers. All fields
    are already on the rows (message_id, username, date) — zero extra cost.

    Args:
        rows: The covered ChatMessageDict rows (post-slice).

    Returns:
        Dict with keys ``messageIds``/``participants``/``dateRange``/
        ``messageCount`` ready to merge into a CondensingDict.
    """
```

### 3.4 Shared JSON render helper

**Location recommendation:** module-level function in `internal/bot/models/message_metadata.py` (where `CondensingDict` lives — keeps the shape and its renderer together; both injection sites import from there already or trivially can).

```python
class CondensedSummaryKind(StrEnum):
    """Render-side discriminator for the condensed-summary JSON shape.

    Deliberately separate from :class:`MessageType` (which classifies real
    message media: text/image/sticker). ``condensed`` is a render-only
    construct for injected summaries — see §3.6 for the discriminator
    resolution.
    """
    CONDENSED = "condensed"


def renderCondensedSummary(
    data: Union[CondensingDict, str],
) -> str:
    """Render a condensed-summary record as a JSON string for the LLM.

    Produces a JSON object shape consistent with real user messages
    (``EnsuredMessage.formatForLLM`` JSON branch,
    ``ensured_message.py:1158-1177``) so the LLM sees a uniform format.
    Legacy ``str`` input (old ``randomContext`` rows) is rendered as the new
    shape with empty/null metadata fields — graceful degradation, consistent
    output shape, and the LLM simply does not call ``get_messages_by_ids``
    for summaries with empty ``coveredMessageIds``.

    Args:
        data: A :class:`CondensingDict` (new writes) or a legacy ``str``
            (old ``randomContext`` rows).

    Returns:
        JSON string of shape::

            {
              "type": "condensed",
              "coveredMessageIds": ["100", "101", ...],
              "participants": ["alice", "bob"],
              "dateRange": {"from": "<ISO>", "to": "<ISO>"} | null,
              "messageCount": 42,
              "summary": "<condensing model text>"
            }

        Falsy/absent fields are omitted consistent with the real-message
        renderer (``if v`` drop at ``ensured_message.py:1173``).
    """
```

**Render contract details:**

- `coveredMessageIds`: each `MessageId` serialized via `.asMessageId()` (matches real messages' `messageId` at `ensured_message.py:1165`). Empty list / absent → key omitted.
- `dateRange`: `(fromTs, toTs)` → `{"from": datetime.fromtimestamp(ts, UTC).isoformat(), "to": ...}`. Absent/legacy → key omitted (or `null`; recommend **omit** to match the falsy-drop convention).
- `participants`: sorted unique logins; omitted if empty.
- `messageCount`: int; omitted if 0/absent.
- `summary`: the `text` field (always present on both legacy and new).
- Serialization: `utils.jsonDumps(ret, compact=False)` (matches `formatForLLM` at `ensured_message.py:1177`).
- Range-string field (`"100–102, 105"`): **NOT included** in the render output — see §3.6 resolution.

**Both injection sites call this helper:**

- Path A — `internal/bot/common/handlers/base.py:812`:
  ```python
  # Was: cacheEntry = ModelMessage(role="user", content=condensedMessage["text"])
  # NEW:
  cacheEntry = ModelMessage(role="user", content=renderCondensedSummary(condensedMessage))
  ```
- Path B — `internal/bot/models/ensured_message.py:1229-1231`:
  ```python
  randomContext = self.metadata.get("randomContext", None)
  if randomContext:
      ret.append(ModelMessage(role="user", content=renderCondensedSummary(randomContext)))
  ```
  (The helper handles both the new `CondensingDict` and legacy `str` shapes.)

### 3.5 `chat-prompt-suffix` draft (Russian, matching existing style)

**File:** `configs/00-defaults/bot-defaults.toml:199-215`. Insert AFTER the existing `userMemories` bullet (line 212) and BEFORE the "Отвечай простым текстом" line (214). Style matches the existing bullet list. Language: Russian (matches). The suffix is on the `BOT_OWNER_SYSTEM` page, so it ships safely in `00-defaults` (chat admins cannot clobber it).

**Draft addition (to be inserted into the `chat-prompt-suffix` value string):**

```
* Свёрнутые (конденсированные) суммы переписки указаны в JSON-формате со ключом `type: "condensed"`, где:
  * `coveredMessageIds` - Список ID сообщений, которые охвачены этой выжимкой.
  * `participants` - Участники обсуждения (логины).
  * `dateRange` - Период `{"from": ..., "to": ...}` (UTC).
  * `messageCount` - Сколько сообщений охвачено.
  * `summary` - Текст выжимки.
  Если детали конкретного сообщения из выжимки нужны для ответа, вызови инструмент `get_messages_by_ids`, передав нужные ID из `coveredMessageIds`. Оригиналы сообщений всегда сохранены и доступны по их ID.
```

(The exact wording/phrasing is a P4 detail; this draft establishes the content + the tool-reference contract.)

### 3.6 `type: "condensed"` discriminator — RESOLUTION

**Decision: use `"type": "condensed"` in the render output, backed by a dedicated `CondensedSummaryKind(StrEnum)` render-side constant (§3.4). Do NOT add `"condensed"` to `MessageType`.**

Rationale:

1. **Matches the user-agreed example JSON shape** (decision #4).
2. **The condensed JSON shape is structurally disjoint from real user messages** — it never carries `login`/`name`/`messageId`/`text`/`replyId`/`quote`/`mediaDescription`/`userMemories`; instead it carries `coveredMessageIds`/`participants`/`dateRange`/`messageCount`/`summary`. So `type` carrying a different vocabulary in a different object shape is unambiguous to the LLM — there is no collision with the `MessageType`-meaning of `type` on real messages.
3. **Avoids polluting `MessageType`** (the media-classification enum: text/image/sticker). Condensed is a render-only construct, not a media type.
4. **Self-documenting via the suffix** (§3.5): the LLM is explicitly told that `type: "condensed"` marks a summary and that originals are retrievable.
5. **`StrEnum`** (per AGENTS.md "use StrEnum for named constants") over a bare string literal — pyright-narrowable, self-documenting. A single-member enum is acceptable here because it documents the vocabulary and leaves room for future summary kinds.

**Range-string field — RESOLUTION:** NOT included. `coveredMessageIds` is an explicit flat list (the exact param shape `get_messages_by_ids` consumes — the LLM passes them straight through, no parse step). Range-rendering (`"100–102, 105"`) is a Telegram-display concern, not an LLM-consumption concern; if ever needed, compute it at Telegram-render time, never store it. Explicit list is unambiguous (no gap-parsing); canonical storage stays a list.

### 3.7 `get_messages_by_ids` tool spec

**Handler method:** `ChatSearchHandler._llmToolGetMessagesByIds` (mirrors `_llmToolGetThread` at `internal/bot/common/handlers/chat_search.py:712-781`).

**Registration site:** `ChatSearchHandler.__init__` (`chat_search.py:134`), as a normal `self.llmService.registerTool(...)` call alongside the other search tools. The tool rides the handler's existing conditional registration — `ChatSearchHandler` is only instantiated when `[search-history].enabled` is True (`manager.py:540`), so the tool is gated at the handler (registration) level. **No handler-registration restructuring is needed** (the earlier "unconditional registration" tension is resolved — see §11 #1). Note that "not gated on search-specific flags" below (layer 3) means `EMBEDDINGS_ENABLED` etc.; it does NOT mean the tool bypasses the `[search-history].enabled` handler gate (layer 1).

```python
self.llmService.registerTool(
    name=ToolName.GET_MESSAGES_BY_IDS,   # NEW constant, internal/bot/constants.py
    description=(
        "Retrieve the full content of one or more chat messages by their IDs. "
        "Use this to read the original messages underlying a condensed summary "
        "(summaries carry coveredMessageIds). Returns each message in the same "
        "JSON shape as regular user messages, plus a notFound list for IDs that "
        "did not resolve. Messages are scoped to the current chat."
    ),
    parameters=[
        LLMFunctionParameter(
            name="message_ids",
            description="List of message ID strings to retrieve (e.g. [\"100\", \"101\"]).",
            type=LLMParameterType.ARRAY,
            required=True,
            extra={"items": {"type": "string"}},   # ACCEPTED (user 2026-07-11) — precise schema
        ),
    ],
    handler=self._llmToolGetMessagesByIds,
)
```

> **ARRAY param items type — ACCEPTED (user, 2026-07-11; see §11 #5):** the existing `LLMFunctionParameter.toJson()` (`lib/ai/models.py:218-240`) spreads `extra` into the JSON. Include `extra={"items": {"type": "string"}}` (shown in the spec above) so the JSON-Schema emitted to the LLM is precise — the LLM MUST pass strings (`MessageId` is `int|str`). The loose-array precedent (`tags` in `user_memories.py:290`) is deliberately not followed here. P5 tests the model actually passes a list of strings.

**Handler signature + never-raise + chat-scoping:**

```python
async def _llmToolGetMessagesByIds(
    self,
    extraData: Optional[Dict[str, Any]],
    message_ids: Optional[List[str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """LLM tool: fetch full content of messages by ID. Never raises.

    Args:
        extraData: Context dict with ``ensuredMessage`` key (chat scoping).
        message_ids: List of message ID strings to retrieve.
        **kwargs: Ignored.

    Returns:
        ``{"done": True, "messages": [...], "notFound": [...], "count": N}``
        on success, or ``{"done": False, "error": "..."}`` on any failure.
        Each message dict matches :meth:`EnsuredMessage.formatForLLM` JSON
        output (login/name/date/messageId/type/text/replyId/quote/
        mediaDescription — falsy dropped), via :meth:`_formatMessageDict`.
    """
```

**Gating — three layers (resolved with user 2026-07-11; see §11 #1/#5/#6):**

1. **`[search-history].enabled` (handler / registration level).** `ChatSearchHandler` is only instantiated when this config flag is True (`manager.py:540`), so `get_messages_by_ids` exists only when chat-search is enabled. No handler restructuring — the tool registers in `__init__` like the other search tools.
2. **`ALLOW_TOOLS_COMMANDS` (per-chat master tools toggle, applied at tool-resolution time).** The same gate every other LLM tool passes; enforced in handler-body gate #2 below.
3. **NOT gated on `EMBEDDINGS_ENABLED` or any embeddings/search-specific flag.** This is a pure DB lookup; it is available whenever chat-search is on, even when semantic search / embeddings are disabled.

**Runtime gates in the handler body (mirror `_llmToolGetThread`):**

1. `extraData` + `ensuredMessage` present → `chatId = extraData["ensuredMessage"].recipient.id`. Else `{"done": False, "error": "Missing chat context"}`.
2. `ALLOW_TOOLS_COMMANDS` chat setting must be True — the global per-chat master tools toggle, applied at tool-resolution time, identical to every other LLM tool (layer 2 above). Else `{"done": False, "error": "Tools disabled for this chat"}`. **Do NOT** gate on `EMBEDDINGS_ENABLED` (layer 3 — the feature is independent of embeddings).
3. Validate + clamp input: dedup `message_ids`, drop blanks, clamp to `MAX_GET_MESSAGES_BATCH` (new constant, e.g. `50` — see §6.6). Wrap `MessageId(mid)` per id in try/except; invalid ones go to `notFound`.
4. Batch fetch via `self.db.chatMessages.getChatMessagesByMessageIds(chatId, ids)` (§3.8).
5. Format each via `self._formatMessageDict(row)` (reuse existing helper, `chat_search.py:688-710`) — parallel `asyncio.gather(..., return_exceptions=True)` like `_llmToolSearchMessages` (`:591-594`).
6. Compute `notFound` = requested ids − found ids.
7. **Entire body wrapped in try/except** → `{"done": False, "error": "..."}` on any exception (never-raise contract per AGENTS.md / teamlead-memory).

**Exact return dict:**

```python
{
    "done": True,
    "messages": [
        # each = json.loads(await eMessage.formatForLLM(JSON, cache=None))
        # i.e. {login, name, date, messageId, type, text, replyId, quote, mediaDescription}
        # falsy keys dropped — IDENTICAL shape to real user messages the LLM sees
        ...
    ],
    "notFound": ["unresolvedId1", "unresolvedId2"],
    "count": <len(messages)>,
}
```

NO context expansion (no replied-to fetch, no surrounding window) — just the bare messages requested.

### 3.8 Batch repo method `getChatMessagesByMessageIds`

**File:** `internal/database/repositories/chat_messages.py` (alongside `getChatMessageByMessageId` at `:290`).

```python
MAX_GET_MESSAGES_BATCH: int = 50  # module-level constant (cap tool abuse)

async def getChatMessagesByMessageIds(
    self,
    chatId: int,
    messageIds: Sequence[MessageId],
    *,
    dataSource: Optional[str] = None,
) -> List[ChatMessageDict]:
    """Fetch multiple chat messages by ID in one query.

    Uses a portable ``IN (...)`` expansion with named placeholders
    (``:id0, :id1, ...``) — see docs/sql-portability-guide.md. Same user
    JOIN as :meth:`getChatMessageByMessageId`. Order: ascending by date
    (matches :meth:`getChatMessagesByRootId`). Dedup of input ids is the
    caller's responsibility (the tool handler dedups before calling).

    Args:
        chatId: Chat identifier (scoping — never cross-chat).
        messageIds: Message IDs to fetch. Empty -> returns [].
        dataSource: Optional data-source routing.

    Returns:
        List of matching ChatMessageDict rows (may be shorter than input if
        some ids do not exist in this chat; caller computes notFound).
    """
```

**SQL portability approach:**

- Build `placeholders = ", ".join(f":id{i}" for i in range(len(messageIds)))` and `params = {"chatId": chatId, **{f"id{i}": mid for i, mid in enumerate(messageIds)}}`.
- Query: `SELECT c.*, u.username, u.full_name FROM chat_messages c JOIN chat_users u ON c.user_id = u.user_id AND c.chat_id = u.chat_id WHERE c.chat_id = :chatId AND c.message_id IN ({placeholders}) ORDER BY c.date ASC`.
- `IN (...)` with named placeholders is portable across SQLite/PostgreSQL/MySQL (per `docs/sql-portability-guide.md` — the guide forbids `COLLATE NOCASE`/`AUTOINCREMENT`/dialect `LIMIT/OFFSET`, not `IN`).
- Empty `messageIds` → early-return `[]` (avoid generating `IN ()` which is invalid SQL).
- Use `executeFetchAll` + `dbUtils.sqlToTypedDict` (same as `getChatMessagesByRootId` at `:356-369`).

---

## 4. Files Touched

| File | Change |
|------|--------|
| `internal/bot/models/message_metadata.py` | Extend `CondensingDict` (new `NotRequired` fields); add `CondensedDateRangeDict`; add `CondensedSummaryKind(StrEnum)`; add `renderCondensedSummary()` helper; add `buildCondensingFields()` helper; widen `MetadataDict.randomContext` to `Union[str, CondensingDict]`. |
| `internal/services/llm/service.py` | `condenseContext` gains additive `returnCoverage: bool = False`; new `CondenseBatchCoverage` TypedDict; emit coverage per batch when requested. |
| `internal/bot/common/handlers/base.py` | `getThreadByMessageForLLM` (`:712-911`): maintain parallel `indexToRow`/`indexToMessageId`; call `condenseContext(..., returnCoverage=True)`; map coverage → `CondensingDict` fields (incl. re-condense cascade union); Path A injection site (`:812`) calls `renderCondensedSummary`. |
| `internal/bot/common/handlers/llm_messages.py` | `handleRandomAnswer` (`:888-947`): maintain parallel id/row lists; build single `CondensingDict` for `randomContext`; persist. |
| `internal/bot/models/ensured_message.py` | `toModelMessageList` (`:1229-1231`): Path B injection site calls `renderCondensedSummary` (handles legacy `str` + new `dict`). |
| `internal/bot/common/handlers/chat_search.py` | Add `_llmToolGetMessagesByIds` handler method; register `get_messages_by_ids` tool in `__init__` as usual (rides the handler's existing `[search-history].enabled` gate — no restructuring). |
| `internal/bot/common/handlers/manager.py` | **No change.** The existing `[search-history].enabled` conditional gate at `:540` stays — it IS layer-1 of the tool's gating (handler/tools register only when chat-search is enabled). |
| `internal/bot/constants.py` | Add `ToolName.GET_MESSAGES_BY_IDS = "get_messages_by_ids"`; add `MAX_GET_MESSAGES_BATCH = 50` (or place in `chat_messages.py`). |
| `internal/database/repositories/chat_messages.py` | Add `getChatMessagesByMessageIds` batch repo method (§3.8). |
| `configs/00-defaults/bot-defaults.toml` | Add condensed-summary shape + `get_messages_by_ids` reference to `chat-prompt-suffix` (`:199-215`). |
| `tests/` | New tests per phase (§7): renderer, repo batch method, condenseContext coverage, tool handler (mocked repo, never-raise, chat-scoping, ALLOW_TOOLS_COMMANDS gate, batch cap), backwards-compat read matrix, both injection sites. |
| `scripts/check_condensing.py` | (Optional, follow-up) extend to surface new metadata fields for A/B evaluation of the optional prompt tweak (§9). |

**Docs to update** (P6, via `update-project-docs` skill):

- `docs/llm/architecture.md` — new ADR (condensed-context retrieval; render-as-JSON; coverage tracking; `get_messages_by_ids` tool).
- `docs/llm/handlers.md` — `ChatSearchHandler` row: add `get_messages_by_ids` tool; note registration rides the handler's `[search-history].enabled` gate (three-layer gating per §3.7).
- `docs/llm/services.md` — `condenseContext` signature change (`returnCoverage`).
- `docs/llm/database.md` — new `getChatMessagesByMessageIds` method.
- `docs/database-schema.md` + `docs/database-schema-llm.md` — `CondensingDict`/`MetadataDict.randomContext` shape evolution (dual docs in sync).
- `internal/bot/models/message_metadata.py` docstrings (the TypedDicts).
- `docs/llm/index.md` — only if the ADR count / handler list line shifts.

---

## 5. Phased Implementation Plan

Each phase is **independently green** (`make test` passes after each). Sizes target a single `software-developer` invocation (~60 steps). Additive-first (ADR-018 model).

### Phase 1 — Additive foundation (TypedDict + repo method)

- Extend `CondensingDict` with `NotRequired` new fields; add `CondensedDateRangeDict`; widen `MetadataDict.randomContext` type.
- Add `CondenseBatchCoverage` TypedDict in `service.py`.
- Add batch repo method `getChatMessagesByMessageIds` in `chat_messages.py` + `MAX_GET_MESSAGES_BATCH`.
- **No production behavior change** (new fields optional/unused; new method uncalled).
- **Tests:** repo batch method (found subset, empty input → [], not-found subset, ordering, dedup responsibility, batch cap honored by caller), TypedDict shape smoke.
- **Acceptance gate:** `make test` green; `make lint` clean.

### Phase 2 — `condenseContext` signature evolution

- Add `returnCoverage: bool = False` keyword-only param; emit `List[CondenseBatchCoverage]` per summary batch (index ranges into full input `messages`).
- Path C (`generateTextViaLLM`) **unchanged** (default `False` → identical return).
- **Tests:** `returnCoverage=False` path byte-identical to today (regression); `returnCoverage=True` coverage alignment with known batch sizes (single batch, multi-batch, dynamic-shrink case, single-skip case at the `:735-738` branch); pure-truncation mode (`condensingModel=None`) → empty coverage; `force=True` under-budget → no summaries → empty coverage.
- **Acceptance gate:** green; lint clean.

### Phase 3 — Caller wiring (Path A + Path B metadata population; storage only)

- `getThreadByMessageForLLM` (`base.py`): build parallel `indexToRow`/`indexToMessageId` aligned to `ret`; call `condenseContext(..., returnCoverage=True)`; `buildCondensingFields()` from coverage slices; populate new `CondensingDict` fields on write (incl. re-condense cascade union of coverage). **Render sites unchanged** (still read `text` only) → green.
- `handleRandomAnswer` (`llm_messages.py`): build single `CondensingDict` for `randomContext` with coverage (union of all batches); persist.
- **Tests:** new metadata fields present on persisted dicts (mocked `condenseContext` returning deterministic coverage); re-condense cascade unions coverage correctly; `tillMessageId`/`tillTS` still written (backwards-compat).
- **Acceptance gate:** green; lint clean.

### Phase 4 — Shared render helper + both injection sites + chat-prompt-suffix

- Add `CondensedSummaryKind` + `renderCondensedSummary()` + `buildCondensingFields()` in `message_metadata.py`.
- Path A injection (`base.py:812`) → `renderCondensedSummary(condensedMessage)`.
- Path B injection (`ensured_message.py:1229-1231`) → `renderCondensedSummary(randomContext)`.
- `chat-prompt-suffix` TOML addition (Russian, §3.5).
- **Tests:** renderer unit tests (full new shape; legacy `str` randomContext → graceful; `dateRange` absent → omitted; all-falsy-metadata → minimal shape); both injection sites emit JSON (integration via `getThreadByMessageForLLM` + `toModelMessageList` with crafted metadata).
- **Acceptance gate:** green; lint clean.

### Phase 5 — `get_messages_by_ids` tool

- Add `ToolName.GET_MESSAGES_BY_IDS` + `MAX_GET_MESSAGES_BATCH` constants.
- Implement `_llmToolGetMessagesByIds` (gates, batch fetch, `_formatMessageDict` reuse, never-raise, `notFound` computation).
- Register in `ChatSearchHandler.__init__` as a normal `registerTool(...)` call — the tool rides the handler's existing `[search-history].enabled` gate (no handler-registration restructuring; §11 #1 resolved).
- **Tests:** tool handler with mocked repo (all-found, all-not-found, mixed, empty input, invalid ids → notFound, never-raise on repo exception, chat-scoping via `extraData`, `ALLOW_TOOLS_COMMANDS=False` → blocked, batch cap clamping, tool present when `[search-history].enabled=true` / absent when `false`, NOT gated on `EMBEDDINGS_ENABLED`, `items: string` present in the emitted tool schema).
- **Acceptance gate:** green; lint clean.

### Phase 6 — Docs

- New ADR in `docs/llm/architecture.md`; update `handlers.md`, `services.md`, `database.md`, dual `database-schema*.md`, `message_metadata.py` docstrings.
- Update this plan's status line on completion.
- **Acceptance gate:** green; lint clean; doc drift check via `update-project-docs` skill.

---

## 6. Test Strategy

### 6.1 Renderer unit tests (P4)
- New `CondensingDict` → full JSON shape; field ordering/falsy-drop matches real-message renderer.
- Legacy `str` randomContext → graceful (summary present, metadata omitted).
- `dateRange` absent → omitted (not `null`) — matches falsy-drop convention.
- `messageIds` as `MessageId` objects → serialized via `.asMessageId()`.
- Round-trip: `renderCondensedSummary` output is valid JSON.

### 6.2 Repo batch method tests (P1)
- `tests/database/repositories/test_chat_messages.py`: found subset, not-found subset, empty input → `[]`, ordering (date ASC), cross-chat isolation (other chat's id not returned), dedup = caller's job (pass dup → returns one row, caller computes notFound).

### 6.3 `condenseContext` coverage tests (P2)
- `tests/services/llm/test_llm_service.py`: `returnCoverage=False` regression (byte-identical); `returnCoverage=True` alignment (single/multi batch, dynamic shrink, single-skip branch); pure-truncation → empty coverage; `force=True` under-budget → empty coverage.

### 6.4 Tool handler tests (P5)
- `tests/bot/common/handlers/test_chat_search.py`: mock `db.chatMessages.getChatMessagesByMessageIds`; assert return shape (`messages`/`notFound`/`count`); never-raise (repo raises → `{"done": False, "error": ...}`); chat-scoping (`extraData` missing → error); `ALLOW_TOOLS_COMMANDS` gate; batch-cap clamping; registration follows the handler gate (tool present when `[search-history].enabled=true`; absent when `false`); NOT gated on `EMBEDDINGS_ENABLED`.

### 6.5 Backwards-compat read tests (P4)
- See §8 matrix. Craft old-shape `metadata` dicts; assert renderer + injection sites handle each.

### 6.6 D3-style gating
- N/A here. `get_messages_by_ids` is read-only (no D3 delete-at-chat-time hazard). Registration is gated normally via the handler's `[search-history].enabled` flag (it is not "unconditional"); there is no per-message tool-dict gating to test (unlike `delete_memory`'s D3 invariant). Document this in P5 test notes.

---

## 7. Backwards-Compatibility Matrix

| Row shape | `condensedThread` (Path A) | `randomContext` (Path B) | How read |
|-----------|----------------------------|--------------------------|----------|
| **Old** (`CondensingDict` = `{text, tillMessageId, tillTS}`, no new fields) | list of old dicts | N/A | `renderCondensedSummary` → JSON with `summary=text`, all metadata omitted (graceful). `get_messages_by_ids` not callable (no `coveredMessageIds`). |
| **Old** (`randomContext` = flat `str`) | N/A | `str` | `renderCondensedSummary(str)` → JSON with `summary=str`, metadata omitted. |
| **New** (`CondensingDict` with all fields) | list of new dicts | single new dict | `renderCondensedSummary(dict)` → full JSON shape. |
| **Mixed** (some old, some new entries in `condensedThread` list) | mixed list | N/A | Per-entry: renderer handles each entry independently (old entry → minimal shape; new entry → full shape). |

**Key invariants:**
- `tillMessageId`/`tillTS` retained on ALL new writes (backwards-compat for any older code path that reads them; cheap boundary marker).
- Reader never assumes new fields present — always `.get(field)` / falsy-drop.
- No migration needed: old rows render correctly (degraded, no retrieval); new rows are richer. The feature degrades gracefully on legacy data.

---

## 8. Out of Scope

- **Path C** (transient `generateTextViaLLM` auto-condense): not persisted, not meaningfully retrievable. `condenseContext` signature change is additive (`returnCoverage=False` default) so Path C is untouched.
- **Optional condensing-prompt tweak** (feeding `participants`/`dateRange` into the condensing prompt): **post-implementation experiment** via `scripts/check_condensing.py`, NOT a launch blocker. Tracked as follow-up (§9).
- **TEXT-branch rendering** of summaries: TEXT format is used for assistant messages (`ensured_message.py:1290-1294`); summaries are always `role="user"` → always JSON branch. No TEXT-branch summary rendering needed.
- **Range-string storage** (`"100–102"`): display-only; not stored (§3.6).
- **Surrounding-context expansion** in `get_messages_by_ids` (replied-to fetch, message window): explicitly excluded — bare messages only.

---

## 9. Optional Prompt Tweak (follow-up, not launch-blocking)

Hypothesis: feeding `participants`/`dateRange` into the condensing prompt (e.g. `"Summarize the discussion between {participants} from {from} to {to}"`) focuses the condensing model and improves summary quality.

- `scripts/check_condensing.py` (added 2026-07-11) is the A/B harness: resolves a thread, builds the ModelMessage list mirroring `getThreadByMessageForLLM`, calls `condenseContext(force=True)`, prints before/after token counts. Use it to compare baseline vs participant/date-enriched prompts on real threads.
- This is a **post-P6 experiment**: implement the feature first (P1–P6), then iterate on the condensing prompt separately. Do NOT block launch on this.
- If adopted, it touches only `chatSettings[CONDENSING_PROMPT]` template content (no code change) — or a small templating step in `getThreadByMessageForLLM` before the `condenseContext` call.

---

## 10. SQL Portability Notes

- `getChatMessagesByMessageIds` uses `IN (:id0, :id1, ...)` named-placeholder expansion — portable across SQLite/PostgreSQL/MySQL (per `docs/sql-portability-guide.md`).
- No `AUTOINCREMENT`, no `DEFAULT CURRENT_TIMESTAMP`, no `COLLATE NOCASE`, no dialect `LIMIT/OFFSET` in the new query.
- Same JOIN shape as the existing `getChatMessageByMessageId` (`chat_messages.py:314`) and `getChatMessagesByRootId` (`:358`) — proven portable.
- Goes through `BaseSQLProvider.executeFetchAll` (provider abstraction) — never raw `sqlite3`.

---

## 11. Open Questions / Risks

**Design-decision items — all RESOLVED with user (2026-07-11):** items #1, #5, #6 below are locked (see each). The remaining items (#2, #3, #4) are **implementation-phase risks** to verify during P3/P4 — they need no further user input before dispatch.

1. **`ChatSearchHandler` registration tension — RESOLVED (user, 2026-07-11).** The earlier conflict (decision #6's "Placement: `ChatSearchHandler`" + "Registration: UNCONDITIONAL" vs. the handler's conditional registration at `manager.py:540`) is **DISSOLVED**. User decision: `get_messages_by_ids` is gated on `[search-history].enabled` along with the rest of `ChatSearchHandler` — *"it is fine; if some day we want to disable search for messages, we'll want to disable this tool as well."* **No handler restructuring is needed** — no dropping the manager-level gate, no moving the tool to another handler, no sub-gating inside `__init__`. The tool is a normal `registerTool(...)` call in `ChatSearchHandler.__init__` and rides the handler's existing conditional registration. (The earlier `/search`/`/users` always-registered side-effect concern is moot.) See §3.7 layer-1 gating.

2. **`indexToRow` alignment in `getThreadByMessageForLLM`.** `toModelMessageList` can emit multiple `ModelMessage`s per source row (randomContext + toolHistory + main). The parallel `indexToRow` list must tag *every emitted ModelMessage* with its source row. P3 must verify the alignment is exact against the actual `ret` list built at `base.py:751-841`. Risk: off-by-one in the parallel list → wrong coverage. Mitigation: P3 tests assert `len(indexToRow) == len(ret)` and that condense coverage slices map to the expected messageIds.

3. **Re-condense cascade coverage union.** The second `condenseContext` (`base.py:880`) re-summarizes existing summaries; each merged summary's coverage = union of the original batches'. P3 must verify the union logic against the cascade's actual batch grouping (which itself depends on `condenseContext`'s internal batching of `condenseCacheMessages`). Edge case: a re-condense batch that spans original-batch boundaries. Tests must cover this.

4. **`dateRange` ISO format consistency.** `EnsuredMessage.formatForLLM` uses `self.date.isoformat()` (`:1164`) — a `datetime` with tz info. The condensed `dateRange` timestamps are unix floats; render via `datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()`. Verify the suffix's `{"from":..., "to":...}` description matches the actual emitted format (with `+00:00` offset). Minor; P4 verifies.

5. **`items` spec on the ARRAY param — RESOLVED (user, 2026-07-11).** **ACCEPTED (architect-recommended, user-confirmed): include `extra={"items": {"type": "string"}}`** on the `message_ids` param. The `LLMFunctionParameter` in §3.7 carries it; P5 tests the model actually passes a list of strings.

6. **`ALLOW_TOOLS_COMMANDS` gating — RESOLVED (user, 2026-07-11).** **YES — `get_messages_by_ids` IS gated on the global `ALLOW_TOOLS_COMMANDS` toggle**, consistent with every other LLM tool. The earlier "unconditional" wording meant *not gated on embeddings/search-specific flags* — NOT truly ungated. The tool's full gating is three layers (see §3.7): (1) `[search-history].enabled` via handler registration, (2) `ALLOW_TOOLS_COMMANDS` at tool-resolution time, (3) NOT gated on `EMBEDDINGS_ENABLED` or any embeddings/search-specific flag (pure DB lookup, available whenever chat-search is on).

---

*End of plan.*
