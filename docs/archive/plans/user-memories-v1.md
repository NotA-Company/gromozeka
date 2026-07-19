# User Memories v1

**Status:** IMPLEMENTED (all phases complete; Phases 1–5 shipped)
**Date:** 2026-07-06
**Author:** planning pass
**Related:**
- [`docs/plans/memory-refine-plan-v1.md`](memory-refine-plan-v1.md) — predecessor (the rolling-bio system), IMPLEMENTED. This plan unifies and retires its output path.
- [`docs/llm/architecture.md`](../llm/architecture.md) — ADR-014 (memory refinement) and ADR-015 (chat-history semantic search). The vec0 / `createVectorTable` pattern copied here comes from ADR-015.
- [`docs/llm/memories/user-memory-refinement.md`](../llm/memories/user-memory-refinement.md) — durable implementation notes for the system being replaced.

> This is a **planning document**, not a spec the code currently honours. It is
> written so a developer agent can execute it phase-by-phase without further
> design decisions. Every file path and `file:line` anchor was verified against
> the tree at planning time. `[DESIGN CHOICE]` marks a judgement call that goes
> beyond the 5 locked decisions in §4 — the executing agent should flag these in
> its PR description but is not expected to re-litigate them.

---

## 1. Overview & Goals

Gromozeka today carries **two parallel, incompatible "memory" systems** for
per-user knowledge (see §3). They store different shapes, are injected through
different code paths, and cannot be searched or de-duplicated. This plan
unifies them into a single **`user_memories`** store with the following goals:

1. **One table, one source of truth.** Every durable fact, preference, event,
   relationship, or high-level bio note about a user lives as a row in
   `user_memories`, tagged with a `MemoryType` discriminator and a freeform
   `tags` set.
2. **Searchable + de-duplicated.** Each memory carries a vector embedding
   (reusing the existing vec0 / `BaseSQLProvider.vectorSearch` infrastructure
   from chat-history search). `add_memory` cosine-searches the same scope for
   near-duplicates before inserting.
3. **Always-in permanent + toggle-controlled ephemeral.** Permanent memories
   are capped and injected into every chat system message. Ephemeral memories
   are retrieved by latest-vs-relevant mode, gated by a per-chat setting.
4. **LLM-authored at chat time AND at refinement time.** The main chat LLM
   gets `add_memory` + `search_memories`; the background refinement LLM
   additionally gets `delete_memory` so it can curate.
5. **Clean retirement of the old systems.** `add_user_data` / `delete_user_data`
   tools are removed; the rolling-bio JSON blob stops being written. The old
   `user_data` **table** is kept for rollback safety (not dropped).
6. **Vector regeneration on embedding-model drift.** When a chat's
   `EMBEDDING_MODEL` changes, stale `user_memories` rows (whose
   `embedding_model` / `embedding_dimensions` no longer match) are
   re-embedded by a background tick. Mirrors the chat-history regeneration
   path (`chat_search.py` backfill) one-to-one. See §5.6.
7. **Admin UI.** The existing `/memory_config` wizard is repointed at
   `user_memories` so a user can browse, filter (by topic/type/tag), and
   delete their own memories interactively. Private-only, paging added.
   See §11.6.

### Non-code deliverable shape

The implementing agent will touch, at minimum:

- 1 migration (`internal/database/migrations/versions/migration_020_*.py`)
- 1 new model module (`MemoryType`) + 1 `TypedDict` (`UserMemoryDict`)
- 1 new repository (`internal/database/repositories/user_memories.py`)
- 1 new helper (`internal/bot/common/memory_embedding_utils.py`)
- 3 new `ToolName` entries + 3 tool handlers + retire 2 old ones
- 4 new chat settings (4 sites each — §11)
- 1 new injection helper + edits at 3 system-message construction sites
- 1 rewrite of the refinement body (`_runRefinement`)
- Tests mirroring each of the above under `tests/`
- Doc sync via the `update-project-docs` skill (architecture ADR, handlers,
  configuration, `database-schema.md` + `database-schema-llm.md`, durable
  memory under `docs/llm/memories/`)

## 2. Non-Goals (v1)

Explicitly deferred to later work:

- **Cross-chat user memories.** All v1 memories are scoped to
  `(chat_id, user_id[, thread_id])`. A global "user profile" that follows a
  user across chats is out of scope.
- **PostgreSQL / MySQL vec0 portability.** The vec0 virtual-table DDL and
  partition-key syntax are sqlite-vec-specific (see the TODO at
  `internal/database/repositories/chat_embeddings.py:201`). v1 is SQLite-only;
  PG/MySQL porting is tracked in §15.
- **Dropping the `user_data` table.** Kept for rollback. A future migration
  can drop it once confidence is high.
- **Numpy fallback for `searchMemories`.** There is no BLOB embedding table
  to fall back from (§5.1 dropped it by design — vec0 is the sole embedding
  store); v1 returns `[]` when vec0 is unavailable. (Chat-history search has
  a numpy fallback at `internal/database/repositories/chat_search.py:266-436`;
  we do not port one for memories in v1.)

## 3. Background — current state (the two systems being unified)

### 3.1 `user_data` table (durable key-value facts)

- **Schema:** migration_001, table `user_data`, PK `(user_id, chat_id, key)`,
  columns `user_id / chat_id / key / data / created_at / updated_at`.
- **Tools:** `ToolName.ADD_USER_DATA` / `ToolName.DELETE_USER_DATA` —
  `internal/bot/constants.py:60-62`. Handlers `_llmToolSetUserData` /
  `_llmToolDeleteUserData` at `internal/bot/common/handlers/user_data.py:214-287`.
  They are thin wrappers over `cache.setChatUserData` / `unsetChatUserData`
  (which write the `user_data` row).
- **Fate:** rows are **migrated** into `user_memories` (§5.5). The tools are
  **retired** (§12). The table stays.

### 3.2 Rolling bio (per-thread summary JSON blob)

- **Storage:** `chat_users.metadata.memoryRefinement[str(threadId)] = {
  summary, lastProcessedMessageId, lastProcessedMessageDate }`, written by
  `UserDataHandler._runRefinement` under `cache.chatUserMetadataLock()` at
  `internal/bot/common/handlers/user_data.py:472-618` (the persist block is
  `:597-614`).
- **Injection:** read back per-message by
  `EnsuredMessage.applyUserMetadata` (`internal/bot/models/ensured_message.py:917-948`)
  → serialized into each message JSON by `formatForLLM`
  (`ensured_message.py:1170`, key `userSummary`). The chat-prompt-suffix
  documents the `userSummary` field at `configs/00-defaults/bot-defaults.toml:207`.
- **Fate:** the rolling summary **stops being written** (§10) and the
  `userSummary` path is **deprecated** (§9). Existing blobs are **migrated**
  into permanent `type=bio` memories (§5.5).

### 3.3 The vec0 precedent being copied (chat-history search)

This plan reuses the exact runtime-vec0 pattern already shipping for message
search — **do not invent a new vector path**:

- vec0 virtual tables are **NOT created by migrations**. Migration 017
  (`internal/database/migrations/versions/migration_017_message_embeddings.py`)
  created only the authoritative `message_embeddings` BLOB table. The
  dimension-specific `vec_message_embeddings_{N}` table is created lazily on
  first write in
  `ChatEmbeddingsRepository._upsertVecMessageEmbedding`
  (`internal/database/repositories/chat_embeddings.py:166-263`), guarded by a
  `listTables` catalog check. **User memories mirror this**: §5.2.
- Provider abstraction in `internal/database/providers/base.py`:
  - `isVectorSearchSupported()` — `:493`
  - `vectorSearch(table, vectorColumn, returnColumns, queryVector: bytes, k, filterClause, filterParams, distanceMetric=COSINE) -> list[VectorSearchResult]` — `:505-516`
  - `createVectorTable(tableName, columns: list[VectorColumnDef])` — `:578-582`
  - `listTables(likePattern="%") -> list[str]` — `:558`
  - `upsert(table, values, conflictColumns, updateExpressions=...)` — `:390`
  - Supporting types: `VectorColumnDef` TypedDict (`:169`),
    `VectorColumnType` (`:148`), `VectorDistanceMetric.COSINE` (`:135`),
    `VectorSearchResult`, `ParametrizedQuery`.
- The dispatcher precedent is `ChatSearchRepository.searchChatMessages`
  (`internal/database/repositories/chat_search.py:84-189`): native vec0 path
  (`_nativeVectorSearch :638-823`) when `isVectorSearchSupported()`, numpy
  fallback (`_semanticSearch :266-436`). **cosine distance → similarity =
  `1.0 - distance`** (`chat_search.py:785`).
- Embedding model: per-chat `ChatSettingsKey.EMBEDDING_MODEL` (default
  `local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384-dim,
  `configs/00-defaults/bot-defaults.toml:131`).
- `AbstractModel.generateEmbeddings(text)` at `lib/ai/abstract.py:492` is
  **single-string, single-vector** (no batch API — caller loops).
- Shared helper precedent: `embedAndSaveMessage` at
  `internal/bot/common/embedding_utils.py:32-124`.

### 3.4 LLM tool-registration precedent

- `LLMService.registerTool(name, description, [LLMFunctionParameter(...)], handler=self._llmTool*)`
  in a handler's `__init__`, gated by a feature flag.
- `LLMFunctionParameter(name, description, type: LLMParameterType, required=False, extra={})`
  (`lib/ai/models.py:175-216`).
- `LLMParameterType(StrEnum)`: `STRING/NUMBER/BOOLEAN/ARRAY/OBJECT`
  (`lib/ai/models.py:151-172`).
- `ToolName(StrEnum)` at `internal/bot/constants.py:24-72`;
  `TOOLS_DEFAULT_DICT_KEY = "default"` at `:76`.
- Handler signature contract: `async def _llmTool*(self, extraData: Optional[Dict[str, Any]], <typed params>, **kwargs: Any) -> Dict[str, Any]`, returning `{"done": bool, ...}`; **NEVER raises** (errors folded into `{"done": False, "error": ...}`); chat context via `extraData["ensuredMessage"]`.
- Existing refinement LLM call (`user_data.py:549-566`):
  `self.llmService.generateTextViaLLM(messages=[system, user], chatId=None, chatSettings=chatSettings, modelKey=ChatSettingsKey.MEMORY_REFINE_MODEL, fallbackModelKey=ChatSettingsKey.MEMORY_REFINE_FALLBACK_MODEL, useTools={ADD_USER_DATA, DELETE_USER_DATA, SEARCH_MESSAGES, GET_CURRENT_DATETIME}, extraData={"ensuredMessage": synthEnsuredMessage, "typingManager": None})`.
  Synthetic `EnsuredMessage` built by `_makeSyntheticEnsuredMessage`
  (`user_data.py:702-727`).

### 3.5 The chat-settings 4-site pattern

Each new setting must hit **all four** sites (missing any leaves the setting
half-wired and silently non-functional — see the `add-chat-setting` skill):

1. `ChatSettingsKey(StrEnum)` entry — `internal/bot/models/chat_settings.py:281-452`.
2. `_chatSettingsInfo` dict entry (TypedDict `ChatSettingsInfoValue`:
   `type/short/long/page`) — around `chat_settings.py:615`.
3. Default in `configs/00-defaults/bot-defaults.toml` under `[bot.defaults]`.
4. Consumer reads via `chatSettings[KEY].toBool()/.toStr()/.toInt()`
   (`ChatSettingsValue` wrapper at `chat_settings.py:484-592`).

End-to-end simplest boolean example to mirror: **`EMBEDDINGS_ENABLED`**
(enum `chat_settings.py:435-436`, info `:1107-1112`, toml `:128`, consumer
`chat_search.py:498`).

Existing memory-refinement settings (all 5 at `chat_settings.py:309-318`,
info `:884-920`, defaults `bot-defaults.toml:158+`):
`MEMORY_REFINEMENT_ENABLED`, `MEMORY_REFINE_MODEL`,
`MEMORY_REFINE_FALLBACK_MODEL`, `MEMORY_REFINE_SYSTEM_PROMPT`,
`MEMORY_REFINE_USER_PROMPT_TEMPLATE`.

### 3.6 Message-construction injection sites (the three places a memories block lands)

All three assemble a `ModelMessage(role="system", content=...)` from
`CHAT_PROMPT + "\n" + CHAT_PROMPT_SUFFIX` (+ `RANDOM_ANSWER_PROMPT` at the
third):

1. `BaseBotHandler.getThreadByMessageForLLM` —
   `internal/bot/common/handlers/base.py:663-850`; system msg assembled at
   `:701-708`. `ret[0]` is the system message.
2. `LLMMessageHandler.handleMention` —
   `internal/bot/common/handlers/llm_messages.py:612-749`; system msg at
   `:688-695` (`reqMessages[0]`).
3. `LLMMessageHandler.handleRandomMessage` (non-thread branch) —
   `llm_messages.py:836-913`; system msg at `:838-847` (the head of
   `storedMessages`).

## 4. Design decisions (the 5 locked decisions + rationale)

These are **decided**. Do not re-litigate during implementation.

### D1 — Unify now

Single new `user_memories` table with a `permanent` column. Migrate existing
`user_data` rows in. Retire `add_user_data` / `delete_user_data` (replaced by
`add_memory` / `delete_memory`). Rolling bio → permanent memory with
`type=bio`.

> Rationale: two stores with no shared retrieval/dedup is the root cause of
> every current memory bug. Carrying both forward would double the surface
> area forever.

### D2 — Always-in + toggle

Permanent memories (capped, oldest-trimmed if over the cap) injected **every**
message as a system block. Non-permanent memories follow a
latest-vs-relevant toggle (`MEMORY_RETRIEVAL_MODE`).

> Rationale: a durable fact ("the user is vegan") must influence every reply;
> an ephemeral note ("we were just talking about routers") only sometimes
> matters.

### D3 — Search + add at chat-time

The main chat LLM gets `search_memories` **AND** `add_memory`.
`delete_memory` is **refinement-only** (curation happens in the background,
not mid-conversation).

> Rationale: letting the chat LLM delete memories mid-turn risks accidental
> amnesia from a single misjudged turn. Adding and searching are safe and
> high-value; deleting is left to the slower, dedicated refinement pass.

### D4 — Tags + type enum

Freeform `tags` (set of strings) **plus** a `MemoryType` `StrEnum`
discriminator: `bio / preference / fact / event / relationship`.

> Rationale: the enum drives structured retrieval and rendering; tags cover
> the long tail (`#vegan`, `#timezone`, project names) without an enum
> explosion. `StrEnum` is the project's mandated string-enum shape
> (AGENTS.md: "use `StrEnum` (from `enum`), not `Literal[...]`").

### D5 — Similarity + LLM merge dedup

`add_memory` cosine-searches same-scope existing memories:

- top similarity `> 0.95` → **duplicate** (no-op, return the existing memory).
- `0.85 < similarity ≤ 0.95` → **`similar_exists`** signal returned to the
  refinement LLM (it decides: delete-old + re-add-updated, or skip).
- `< 0.85` → **insert**.

At chat-time the chat LLM only sees `added` / `duplicate` back (the grey zone
is folded to `duplicate` from its perspective to avoid mid-turn curation).

> Rationale: hard thresholds keep the common case deterministic; the grey zone
> is the only place an LLM judgement is cheaper than a wrong insert.

## 5. Data model

### 5.1 `migration_020` DDL (full portable SQL)

> AGENTS.md SQL-portability rules honoured: **composite natural PRIMARY KEY**
> (no `AUTOINCREMENT` / `SERIAL`), **no `DEFAULT CURRENT_TIMESTAMP`** (app
> sets timestamps), **`:named` placeholders**, portable column types
> (`TEXT/INTEGER/REAL/TIMESTAMP/BOOLEAN-as-int`), **JSON stored as `TEXT`**.

**File:** `internal/database/migrations/versions/migration_020_user_memories.py`

**Class shape:** mirror `migration_017_message_embeddings.py:26-91` exactly —
class `Migration020UserMemories(BaseMigration)` with `version: int = 20`,
`description: str = "Add user_memories table"`,
`async def up(self, sqlProvider)`, `async def down(self, sqlProvider)`,
`def getMigration() -> Type[BaseMigration]`. DDL via
`sqlProvider.batchExecute([ParametrizedQuery(sql), ...])`.

**`up()` — authoritative tables (created by the migration):**

```sql
CREATE TABLE IF NOT EXISTS user_memories (
    chat_id    INTEGER   NOT NULL,
    user_id    INTEGER   NOT NULL,
    thread_id  INTEGER,            -- NULL = permanent (cross-thread within chat)
    memory_id  TEXT      NOT NULL, -- app-generated ULID
    type       TEXT      NOT NULL, -- MemoryType value: bio|preference|fact|event|relationship
    content    TEXT      NOT NULL,
    tags       TEXT      NOT NULL DEFAULT '[]',  -- JSON array of strings
    permanent  INTEGER   NOT NULL DEFAULT 0,    -- boolean 0/1
    source     TEXT      NOT NULL DEFAULT 'refinement', -- refinement|chat|migration|user
    embedding_model      TEXT,               -- NULL = not yet embedded; set on first embed
    embedding_dimensions INTEGER,           -- NULL = not yet embedded; vector dimension count
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, user_id, memory_id)
);

CREATE INDEX IF NOT EXISTS idx_user_memories_chat_user_thread
    ON user_memories (chat_id, user_id, thread_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_memories_chat_user_permanent
    ON user_memories (chat_id, user_id, permanent, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_memories_type
    ON user_memories (chat_id, user_id, type);
```

> AMENDMENT (user review, change #4): The original draft created a second
> table `user_memory_embeddings (chat_id, user_id, memory_id, embedding BLOB,
> dimensions, model, created_at, updated_at, PRIMARY KEY (chat_id, user_id,
> memory_id))` as a numpy-fallback substrate. **Dropped.** Since v1 has no
> numpy fallback (§2) and re-embedding from `user_memories.content` is always
> possible (that is exactly what the regeneration worker in §5.6 does), the
> BLOB table is redundant. `user_memories.content` is the source of truth;
> the lazy vec0 table (§5.2) is the derived, rebuildable embedding cache; and
> `embedding_model` / `embedding_dimensions` (added to `user_memories` per
> change #2) track provenance on the authoritative row itself.

**`down()`:**

```sql
DROP TABLE IF EXISTS user_memories;
-- NOTE: do NOT touch user_data (kept for rollback safety).
```

`[DESIGN CHOICE]` — three indexes. The `(chat_id, user_id, thread_id,
updated_at DESC)` index backs both `getLatestMemories` and same-thread dedup
search; `(chat_id, user_id, permanent, updated_at DESC)` backs
`getPermanentMemories` and the permanent-only filter path; `(chat_id,
user_id, type)` backs type-filtered scans. If a query profiler later shows
redundancy, the type index is the first candidate to drop.

### 5.2 vec0 runtime table (`vec_user_memories_{dim}`)

**Not in the migration.** Created lazily at runtime on first write, mirroring
`ChatEmbeddingsRepository._upsertVecMessageEmbedding`
(`internal/database/repositories/chat_embeddings.py:166-263`).

Table name: `vec_user_memories_{dimensions}` (e.g. `vec_user_memories_384`).

Column definitions (passed to `provider.createVectorTable(tableName,
list[VectorColumnDef])`):

| name        | columnType                  | isPartitionKey | extra                       |
|-------------|-----------------------------|----------------|-----------------------------|
| `memory_id` | `VectorColumnType.TEXT`     | —              |                             |
| `chat_id`   | `VectorColumnType.INTEGER`  | `True`         |                             |
| `user_id`   | `VectorColumnType.INTEGER`  | `True`         |                             |
| `thread_id` | `VectorColumnType.INTEGER`  | —              |                             |
| `permanent` | `VectorColumnType.INTEGER`  | —              |                             |
| `type`      | `VectorColumnType.TEXT`     | —              |                             |
| `embedding` | `VectorColumnType.VECTOR`   | —              | `vectorDimension=dim`, `distanceMetric=VectorDistanceMetric.COSINE` |

Creation sequence (copy `_upsertVecMessageEmbedding :202-221`):
`listTables(tableName)` → if absent, `createVectorTable(...)`.

Upsert sequence (vec0 has no real UPSERT on metadata columns — copy
`:227-256`): try `DELETE ... WHERE chat_id=:c AND user_id=:u AND
memory_id=:m`; on failure fall back to rowid-based delete; then
`INSERT INTO {table} (memory_id, chat_id, user_id, thread_id, permanent,
type, embedding) VALUES (...)`. Write failures are **logged at WARNING and
swallowed** — re-embedding from `user_memories.content` is always possible
(that is exactly what the regeneration worker in §5.6 does), so a lost vec0
row is recoverable, not catastrophic.

`[DESIGN CHOICE]` — vec0 is the **sole** embedding store for memories; there
is no BLOB `user_memory_embeddings` table (dropped per change #4 in the
review — §5.1). `embedding_model` and `embedding_dimensions` live on the
authoritative `user_memories` row (set when an embedding is written; NULL =
not yet embedded), and the model is **not** a vec0 partition key (unlike
`message_embeddings`, which partitions on `model`). Memory volume per chat is
tiny relative to messages, so a single vec0 table per dimension without a
model partition is simpler and still correct; stale-model rows are surfaced
by the `getMemoriesWithoutEmbeddings` query (§5.6) and re-embedded. If a
profiler later shows cross-model contamination hurting results, add `model`
as a vec0 partition key + column.

> AMENDMENT (user review, change #4): The original draft stored embeddings in
> a separate `user_memory_embeddings` BLOB table as a numpy-fallback
> substrate. Since v1 explicitly has no numpy fallback (§2) and re-embedding
> from content is always possible, the BLOB table is dropped entirely; vec0
> is the sole store, and model/dimensions tracking moves onto `user_memories`.

### 5.3 `MemoryType` StrEnum

> AGENTS.md: "String enums: use `StrEnum` (from `enum`), not
> `Literal["a", "b"]`."

**File:** `internal/bot/models/memory_type.py` (new module — co-locating in
`internal/models/types.py` is the alternative, but a dedicated module keeps
the enum importable without pulling the broader `models` graph; the existing
tree favours small focused modules like `internal/bot/models/llm_message.py`).

```python
"""MemoryType discriminator for the user_memories store.

Defines the closed set of high-level categories a user memory can belong to.
Stored as the TEXT ``type`` column on the ``user_memories`` table. Freeform
categorisation beyond these is handled by the JSON ``tags`` column.
"""

from enum import StrEnum


class MemoryType(StrEnum):
    """Closed set of user-memory categories.

    Members:
        BIO: High-level, evolving summary of who the user is. Exactly ONE
            permanent bio memory is maintained per (chat, user) by the
            refinement pass; rolling-bio migration (§5.5) seeds it.
        PREFERENCE: A stated or inferred preference ("prefers dark mode",
            "vegan").
        FACT: A durable, non-preferential fact ("lives in Berlin",
            "works as a nurse").
        EVENT: A point-in-time happening ("got married 2024-06",
            "travelling to Tokyo in May").
        RELATIONSHIP: A connection to another person/entity ("married to
            Alex", "mentor is Dr. Lee").
    """

    BIO = "bio"
    """High-level user summary; one permanent bio maintained per (chat, user)."""

    PREFERENCE = "preference"
    """A stated or inferred user preference."""

    FACT = "fact"
    """A durable, non-preferential fact about the user."""

    EVENT = "event"
    """A point-in-time happening in the user's life."""

    RELATIONSHIP = "relationship"
    """A connection between the user and another person/entity."""
```

### 5.4 `UserMemoryDict` TypedDict

> AGENTS.md: "No pydantic. … Use raw dicts + hand-rolled type-hinted classes
> of TypedDict."

**File:** `internal/database/repositories/user_memories.py` (co-located with
the repository — mirrors `MessageEmbeddingDict` living in
`internal/database/repositories/chat_embeddings.py`). Export from the
module's public names.

```python
import datetime
from typing import List, NotRequired, Optional, TypedDict


class UserMemoryDict(TypedDict):
    """Row shape returned by UserMemoriesRepository read methods.

    Keys are snake_case to match DB column names (repo convention — see
    ``ChatMessageDict`` / ``MessageEmbeddingDict`` in
    ``internal/database/models.py:108-212``: ``chat_id``, ``created_at``,
    ``message_id``, …). Repository METHOD parameters stay camelCase per
    AGENTS.md; only the dict keys mirror the columns so the universal
    converter ``dbUtils.sqlToTypedDict`` can map them directly. This matches
    how ``chat_search.py`` works (camelCase params, snake_case dict keys).

    Attributes:
        chat_id: Chat the memory belongs to.
        user_id: User the memory is about.
        thread_id: Thread scope. None for cross-thread permanent memories
            (e.g. user_data-migrated facts); set to the originating thread
            for thread-specific permanent bio memories (§5.5).
        memory_id: App-generated ULID; unique within (chat_id, user_id).
        type: MemoryType string value (bio|preference|fact|event|relationship).
        content: Free-text memory body (source of truth for re-embedding).
        tags: Decoded list of tag strings (stored as JSON TEXT in the row).
        permanent: True if the memory is always injected (§9).
        source: Provenance — refinement | chat | migration | user.
        embedding_model: Name of the model that produced the stored vec0
            embedding, or None when the memory has not been embedded yet.
        embedding_dimensions: Dimension count of the stored embedding, or
            None when not yet embedded.
        created_at: Creation timestamp (parsed from ISO string by the
            universal converter — ``utils.py:230-237``).
        updated_at: Last-update timestamp.
        score: Cosine similarity (0.0–1.0) when returned by semantic
            searchMemories; 0.0 in filter-only mode; absent on rows from
            non-search repo methods. Mirrors ``ChatMessageDict.score`` at
            ``internal/database/models.py:157-160`` EXACTLY (same name,
            same type, same semantics). Do NOT use the name ``similarity``.
    """

    chat_id: int
    user_id: int
    thread_id: Optional[int]
    memory_id: str
    type: str
    content: str
    tags: List[str]
    permanent: bool
    source: str
    embedding_model: Optional[str]
    embedding_dimensions: Optional[int]
    created_at: datetime.datetime
    updated_at: datetime.datetime
    score: NotRequired[float]
```

Row-decoding uses the **universal converter**
`dbUtils.sqlToTypedDict(row, UserMemoryDict)` at
`internal/database/utils.py:319-374` (import as
`from internal.database import utils as dbUtils`, seen at
`chat_embeddings.py:32`). It handles snake_case column → TypedDict key
mapping, int→bool, JSON TEXT→list, ISO str→datetime, and nested containers.
There is **no custom `_rowToDict` helper** — all repo read methods return
`[dbUtils.sqlToTypedDict(row, UserMemoryDict) for row in rows]` (mirror
`chat_embeddings.py:547`, `chat_search.py:254/624`). For semantic-search
results, set `rowDict["score"] = ...` AFTER conversion (mirror
`chat_search.py:626`).

> AMENDMENT (user review, corrections A/B/C + changes #5/#6/#10): (A) keys
> are now snake_case matching DB columns, not camelCase — the repo convention
> for TypedDicts that map to rows (``ChatMessageDict`` etc.). AGENTS.md's
> camelCase rule governs Python *identifiers*, not dict string keys that map
> to columns. (B) the similarity field is named ``score`` (matching
> ``ChatMessageDict.score``), never ``similarity``. (C) the converter is
> ``dbUtils.sqlToTypedDict`` (there is no ``convertFromSQLite``; that was a
> misremembering of ``convertToSQLite``, the Python→SQL direction). Plus
> ``created_at``/``updated_at`` are ``datetime.datetime`` not ``str`` (#5).

### 5.5 Backfill / migration of existing data

Both backfills run **inside `migration_020.up()`** as Python loops after the
DDL (ULIDs must be generated app-side — AGENTS.md: "Application-generated
UUID / ULID … Generate it in Python before insert; never delegate ID
generation to the DB").

> AGENTS.md SQL portability: use the provider (`sqlProvider.execute` /
> `executeFetchAll` / `batchExecute`) — never raw `sqlite3`.

**Backfill A — `user_data` rows → permanent `type=fact` memories:**

```
for row in SELECT user_id, chat_id, key, data, created_at, updated_at FROM user_data:
    memoryId = ULID()
    content  = f"{key}: {data}"
    INSERT INTO user_memories (
        chat_id, user_id, thread_id=NULL, memory_id, type='fact',
        content, tags='[]', permanent=1, source='migration',
        embedding_model=NULL, embedding_dimensions=NULL,
        created_at=row.created_at, updated_at=row.updated_at
    )
```

- `permanent=1`, `type='fact'`, `source='migration'`, `tags=[]`,
  `thread_id=NULL` (cross-thread — `user_data` has no thread concept),
  `embedding_model=NULL`, `embedding_dimensions=NULL` (not yet embedded;
  the regeneration worker in §5.6 backfills them on first tick).
- `content` shape `"{key}: {data}"` keeps the original key discoverable in
  free-text search and is human-readable. `[DESIGN CHOICE]` — alternative
  would be to map known keys to `MemoryType` members, but `user_data` keys
  are freeform, so a uniform `fact` is safer.
- Idempotency: `up()` is gated by migration-version tracking (each migration
  runs once), but the INSERTs are additionally safe because each gets a fresh
  ULID — a re-run would just create dupes. Since the migration framework
  guarantees single-execution, no extra idempotency guard is required.
  Reviewer note: confirm the migration framework does not retry `up()` after
  partial failure; if it does, wrap backfills in a "already backfilled"
  sentinel check.

**Backfill B — rolling-bio JSON → permanent `type=bio` memories:**

```
for row in SELECT chat_id, user_id, metadata FROM chat_users
           WHERE metadata LIKE '%"memoryRefinement"%':
    metadata = json.loads(row.metadata)
    ref = metadata.get("memoryRefinement", {})
    for threadIdStr, entry in ref.items():
        summary = (entry or {}).get("summary")
        if not summary:
            continue
        threadId = int(threadIdStr)   # rolling-bio JSON keys are str(threadId)
        memoryId = ULID()
        INSERT INTO user_memories (
            chat_id, user_id, thread_id=threadId,   # [DESIGN CHOICE] bio keeps its thread scope
            memory_id, type='bio', content=summary,
            tags='["migrated_bio"]', permanent=1, source='migration',
            embedding_model=NULL, embedding_dimensions=NULL,
            created_at=now, updated_at=now
        )
```

`[DESIGN CHOICE]` — **bio is permanent and thread-scoped
(`thread_id=<original thread>`)**, preserving the rolling-bio JSON's
per-thread organisation. The current rolling bio is written and retrieved
per-thread (`metadata.memoryRefinement[str(threadId)]` under
`chatUserMetadataLock` at `user_data.py:472-618`), so keeping bio
thread-scoped is consistent with how it was consumed. By contrast the
`user_data`-migrated facts stay cross-thread (`thread_id IS NULL`, since
`user_data` has no thread concept). Consequence for `getPermanentMemories`
(§6): it must return BOTH cross-thread permanent AND this-thread permanent —
`WHERE permanent=1 AND (thread_id IS NULL OR thread_id = :threadId)`. The
tag `"migrated_bio"` marks the row as migration-sourced for later curation.

> AMENDMENT (user review, change #7): The original draft made bio
> cross-thread (`thread_id=NULL`). Reverted: the rolling bio is intrinsically
> per-thread (stored and read under `str(threadId)`), so thread-scoping the
> migrated bio is the faithful mapping. The "one source of truth" rationale
> in D1 still holds — there is still one permanent bio per (chat, user,
> thread); a multi-thread user simply has one bio row per thread, all of type
> `bio`, all permanent.

> The rolling-bio JSON is **not** deleted from `chat_users.metadata` by the
> migration — the refinement rewrite (§10) stops writing it, and stale reads
> are masked by the `userSummary` deprecation (§9). A cleanup pass is future
> work.

### 5.6 Embedding model-drift regeneration

Mirrors the chat-history regeneration mechanism
(`ChatSearchHandler._dtCronJob` at
`internal/bot/common/handlers/chat_search.py:284-445`) one-to-one, adapted
for memories. Because there is no BLOB table (§5.1), the model/dimensions
tracking lives on `user_memories` itself (`embedding_model` /
`embedding_dimensions`, NULL = not yet embedded) — this **simplifies** stale
detection to a single-table query (no vec0 JOIN needed).

**Chat settings (4-site each — §11.5):**

- `MEMORY_EMBEDDINGS_ENABLED` (BOOL) — discovery: which chats to scan for
  regeneration (mirror `EMBEDDINGS_ENABLED` at `chat_settings.py:435-436`,
  info `:1107-1112`, default `bot-defaults.toml:128`).
- `MEMORY_REGENERATE_EMBEDDINGS` (BOOL, default `true`) — per-chat gate
  (mirror `REGENERATE_EMBEDDINGS` at `chat_settings.py:439-440`, info
  `:1118-1124`, default `bot-defaults.toml:131`).
- Reuses the existing `EMBEDDING_MODEL` setting (`chat_settings.py:433-434`,
  default `bot-defaults.toml:130`) — do NOT add a memory-specific model (same
  precedent as chat-history search).

**Repository methods (added to §6):**

- `getMemoriesWithoutEmbeddings(chatId, userId, currentModel,
  currentDimensions, *, limit) -> List[UserMemoryDict]` — memories analog
  of `getMessagesWithoutEmbeddings` (`chat_embeddings.py:516-532`). SIMPLER
  than the chat-history version (no vec0 JOIN): model/dimensions are on the
  `user_memories` row, so the stale-detection query is a single SELECT:

  ```sql
  SELECT chat_id, user_id, thread_id, memory_id, type, content, tags,
         permanent, source, embedding_model, embedding_dimensions,
         created_at, updated_at
    FROM user_memories
   WHERE chat_id = :chatId AND user_id = :userId
     AND (embedding_model IS NULL
          OR embedding_model != :currentModel
          OR embedding_dimensions != :currentDimensions)
   ORDER BY updated_at DESC
  ```
  with `provider.applyPagination(query, limit, offset=0)`. A NULL
  `embedding_model` (never-embedded memory) surfaces here too, so this query
  also serves the **initial backfill** — same single-path trick the
  chat-history cron uses (`chat_search.py:394-413`).

- `deleteObsoleteMemoryEmbeddings(chatId, userId, currentModel,
  currentDimensions) -> int` — memories analog of
  `deleteObsoleteModelEmbeddings` (`chat_embeddings.py:337-464`). Since
  vec0 has no `model` column in this design (§5.2), the implementation is
  "delete vec0 rows whose `memory_id` maps to a stale-model memory":
  1. `SELECT memory_id FROM user_memories WHERE chat_id=:c AND user_id=:u
     AND (embedding_model IS NULL OR embedding_model != :cm OR
     embedding_dimensions != :cd)` — collect stale `memory_id`s.
  2. For every `vec_user_memories_{N}` table found via
     `provider.listTables("vec_user_memories_%")`, `DELETE FROM {table}
     WHERE memory_id IN (...)`.
  Never raises; returns the count of deleted vec0 rows.

**Regeneration loop (added to `UserDataHandler._dtCronJob`, every 60s):**
mirrors `chat_search._dtCronJob`'s embedding section
(`internal/bot/common/handlers/chat_search.py:284-445`). Per tick:

1. Discover chats round-robin (chats where `MEMORY_EMBEDDINGS_ENABLED` is
   true — reuse the existing discovery loop shape at `chat_search.py:354`).
2. Gate: if `MEMORY_REGENERATE_EMBEDDINGS` is false for the picked chat
   (mirror `chat_search.py:364-366`), skip.
3. Resolve `currentModel = chatSettings[EMBEDDING_MODEL].toStr()` and
   `currentDimensions` from the model registry via
   `LLMService.getLLMManager().getModel(currentModel)` (mirror
   `chat_search.py:368-373`).
4. `await db.userMemories.deleteObsoleteMemoryEmbeddings(chatId, userId,
   currentModel, currentDimensions)` (mirror `chat_search.py:394-398`).
5. `stale = await db.userMemories.getMemoriesWithoutEmbeddings(chatId,
   userId, currentModel, currentDimensions, limit=BACKFILL_DEFAULT_BATCH_SIZE)`
   (mirror `chat_search.py:409-413`).
6. For each `mem in stale`: `await embedAndSaveMemory(chatId, userId,
   mem["memory_id"], mem["content"], currentModel, self.db)` (which writes
   vec0 AND sets `embedding_model`/`embedding_dimensions` on the row);
   `await asyncio.sleep(BACKFILL_INTER_MESSAGE_DELAY_SECS)` between rows
   (mirror `chat_search.py:430-434`, constant `BACKFILL_INTER_MESSAGE_DELAY_SECS
   = 0.1` at `chat_search.py:77`).
7. Batch cap `BACKFILL_DEFAULT_BATCH_SIZE = 50` (constant at
   `chat_search.py:69`); the cron revisits the chat on subsequent ticks
   until caught up.

`[DESIGN CHOICE]` — reusing `UserDataHandler._dtCronJob` (the existing 60s
tick at `user_data.py:301-470` that already drives refinement accounting)
rather than a new cron. The regeneration section is independent of the
refinement body (it does not call the LLM for text generation, only for
embeddings via `model.generateEmbeddings`) and is cheap to gate behind
`MEMORY_EMBEDDINGS_ENABLED` / `MEMORY_REGENERATE_EMBEDDINGS`. The two
operations share the tick but not the lock — regeneration is read/embed/write
on `user_memories`, refinement is LLM-tool-driven; they do not contend.

> AMENDMENT (user review, change #2): Promoted from a Non-Goal to a Goal.
> The chat-history regeneration path (`chat_search._dtCronJob`) is the
> verified template; this subsection adapts it for memories. The
> model/dimensions columns move onto `user_memories` (no BLOB table) which
> simplifies stale detection to a single-table query.

## 6. Repository layer (`UserMemoriesRepository`)

**File:** `internal/database/repositories/user_memories.py` (new).

**Constructor:** `def __init__(self, manager: DatabaseManager)` — store
`self.manager = manager`, mirroring every other repository (see
`ChatEmbeddingsRepository.__init__`). Access the provider per-call via
`self.manager.getProvider(chatId, readonly=bool)` (the established pattern;
see `chat_embeddings.py`).

> AGENTS.md: "Repositories use `BaseSQLProvider` … `execute` /
> `executeFetchOne` / `executeFetchAll` / `batchExecute` / `upsert`."

### 6.1 Method signatures

All methods `async`. All SQL uses `:named` placeholders. All read methods
decode via `dbUtils.sqlToTypedDict(row, UserMemoryDict)` (§5.4 — no custom
`_rowToDict` helper).

```python
async def addMemory(
    self, chatId: int, userId: int, memoryId: str, *,
    type: str, content: str, tags: List[str], permanent: bool,
    threadId: Optional[int] = None, source: str = "refinement",
) -> None:
    """INSERT a new memory row. Raises on PK conflict (caller ensures ULID uniqueness)."""

async def updateMemory(
    self, chatId: int, userId: int, memoryId: str, *,
    content: Optional[str] = None, tags: Optional[List[str]] = None,
    type: Optional[str] = None,
) -> bool:
    """PATCH selected columns; bump updated_at. Returns True if a row was updated."""

async def deleteMemory(
    self, chatId: int, userId: int, memoryId: str,
) -> bool:
    """DELETE one memory + its embedding row. Returns True if deleted."""

async def deleteMemoriesByQuery(
    self, chatId: int, userId: int, *,
    threadId: Optional[int], type: Optional[str] = None,
    olderThanDays: Optional[int] = None,
) -> int:
    """DELETE EPHEMERAL memories matching the scope + filters.

    Always adds ``AND permanent = 0`` — bulk query-delete is ephemeral-only;
    a query-based bulk delete must never silently remove a permanent memory.
    Explicit by-id ``deleteMemory`` is unrestricted (intentional explicit
    action can target a permanent memory) — see §8.4 for the distinction.
    """

async def getPermanentMemories(
    self, chatId: int, userId: int, threadId: int, *,
    limit: int = PERMANENT_INJECTION_CAP,
) -> List[UserMemoryDict]:
    """Return permanent memories, newest-updated-first, capped.

    Returns BOTH cross-thread permanent (``thread_id IS NULL``) AND
    this-thread permanent (``thread_id = :threadId``) — bio memories are
    thread-scoped per §5.5, so a thread's permanent block must include the
    thread's own bio alongside cross-thread facts.
    """

async def getLatestMemories(
    self, chatId: int, userId: int, threadId: int, *,
    limit: int = EPHEMERAL_RETRIEVAL_LIMIT,
) -> List[UserMemoryDict]:
    """Return newest-updated memories scoped to (chatId, userId, threadId), capped."""

async def searchMemories(
    self, chatId: int, userId: int, *,
    queryEmbedding: Optional[bytes] = None,
    threadId: Optional[int] = None, permanent: Optional[bool] = None,
    type: Optional[str] = None, tags: Optional[List[str]] = None,
    limit: int = EPHEMERAL_RETRIEVAL_LIMIT,
    modelName: Optional[str] = None, dimensions: Optional[int] = None,
) -> List[UserMemoryDict]:
    """Unified memory search. Two modes (mirror ``ChatSearchRepository.searchChatMessages`` at ``chat_search.py:167-189``):

    - ``queryEmbedding is None`` → filter-only scan (WHERE on type/tags/permanent/
      thread_id); every result row gets ``score = 0.0`` after conversion. Lets
      the refinement LLM call ``search_memories`` with only ``type`` (e.g. "all
      preference memories") without an embedding.
    - ``queryEmbedding is not None`` → native vec0 search over
      ``vec_user_memories_{dim}``, JOIN back to ``user_memories``;
      ``score = 1.0 - cosine_distance``.

    Returns ``[]`` (never raises) when vec0 search is requested but unsupported
    or the vec0 table is absent. Every returned row has ``score`` set (mirror
    ``chat_search.py:626``). The merged method replaces the former
    ``findSimilarMemories`` (the dedup caller in §8.3 now reads
    ``results[0]["score"]``).
    """

async def getMemoriesWithoutEmbeddings(
    self, chatId: int, userId: int, currentModel: str, currentDimensions: int, *,
    limit: int = BACKFILL_DEFAULT_BATCH_SIZE,
) -> List[UserMemoryDict]:
    """Return memories whose embedding_model/embedding_dimensions are stale or absent.

    Memories analog of ``getMessagesWithoutEmbeddings``
    (``chat_embeddings.py:516-532``). SIMPLER (no vec0 JOIN): the model/
    dimensions live on the ``user_memories`` row, so this is a single SELECT
    with a stale predicate on (embedding_model, embedding_dimensions). A NULL
    ``embedding_model`` (never-embedded memory) surfaces here too, so the same
    query serves the initial backfill. Drives the regeneration worker (§5.6).
    """

async def deleteObsoleteMemoryEmbeddings(
    self, chatId: int, userId: int, currentModel: str, currentDimensions: int,
) -> int:
    """Delete vec0 rows for memories whose embedding_model/embedding_dimensions differ.

    Memories analog of ``deleteObsoleteModelEmbeddings``
    (``chat_embeddings.py:337-464``). Since vec0 has no ``model`` column in
    this design (§5.2), this selects stale memory_ids from ``user_memories``
    then deletes them from every ``vec_user_memories_{N}`` table found via
    ``listTables``. Never raises. Returns the count of deleted vec0 rows.
    """

async def saveMemoryEmbedding(
    self, chatId: int, userId: int, memoryId: str, *,
    embedding: List[float], model: str, dimensions: int,
) -> bool:
    """Persist the embedding: lazy-upsert vec_user_memories_{dim} AND set embedding_model/embedding_dimensions on the user_memories row.

    No BLOB write (the BLOB table was dropped — §5.1); vec0 is the sole
    embedding store. Never raises (mirrors
    ``ChatEmbeddingsRepository.saveMessageEmbedding``).
    """

async def deleteMemoryEmbedding(
    self, chatId: int, userId: int, memoryId: str,
) -> bool:
    """Best-effort DELETE from vec_user_memories_{dim}. Never raises.

    No BLOB delete (the BLOB table was dropped — §5.1); vec0 is the sole
    embedding store.
    """
```

### 6.2 SQL sketches

**addMemory** — straight INSERT; `tags` serialised via `json.dumps`;
`permanent` as `1 if permanent else 0`; timestamps via
`utils.now().isoformat()` (app-side, never DB default):

```sql
INSERT INTO user_memories
    (chat_id, user_id, thread_id, memory_id, type, content, tags, permanent, source, created_at, updated_at)
VALUES (:chatId, :userId, :threadId, :memoryId, :type, :content, :tags, :permanent, :source, :now, :now)
```

**getPermanentMemories** — `WHERE chat_id=:c AND user_id=:u AND permanent=1
AND (thread_id IS NULL OR thread_id = :threadId) ORDER BY updated_at DESC`
with `provider.applyPagination(query, limit, offset=0)` (AGENTS.md: "never
append `LIMIT … OFFSET …` yourself"). The `OR thread_id = :threadId` clause
pulls in this-thread permanent bio memories (§5.5) alongside cross-thread
permanent facts; `getPermanentMemories` now takes a `threadId` param to drive
this (caller in §9.1 passes the active thread).

**searchMemories** — two modes (mirror
`ChatSearchRepository.searchChatMessages` at `chat_search.py:167-189`):

- **Filter-only mode** (`queryEmbedding is None`): a plain `SELECT … FROM
  user_memories WHERE chat_id=:c AND user_id=:u` plus any of
  `AND permanent = :perm` / `AND type = :type` / `AND thread_id = :threadId`
  when set, `ORDER BY updated_at DESC`, `provider.applyPagination(query,
  limit, 0)`. Decode via `dbUtils.sqlToTypedDict`; set `rowDict["score"] =
  0.0` on every result AFTER conversion (mirror `chat_search.py:626`). Lets
  the LLM call `search_memories` with only `type` (e.g. "all preference
  memories") without an embedding. `tags` membership is applied in Python
  (set intersection — JSON-in-SQL is non-portable).
- **Semantic mode** (`queryEmbedding is not None`): mirror
  `_nativeVectorSearch` (`chat_search.py:638-823`). Three-step:
  1. Build vec0 filter: always `chat_id = :chatId AND user_id = :userId`;
     append `AND permanent = :perm` / `AND type = :type` when set. (For
     permanent-scope search pass `thread_id IS NULL` via the post-filter,
     since vec0 `thread_id` is an INTEGER column that also holds NULLs —
     filter at the JOIN step, not in vec0.)
  2. `vectorSearch(table=f"vec_user_memories_{dim}", vectorColumn="embedding",
     returnColumns=["memory_id"], queryVector=queryEmbeddingBytes, k=limit *
     MEMORY_SEARCH_TOPK_MULTIPLIER, filterClause=..., filterParams=...,
     distanceMetric=COSINE)`.
  3. JOIN `vecResults` back to `user_memories` on `memory_id` (single
     `SELECT ... WHERE chat_id=:c AND user_id=:u AND memory_id IN (...)`),
     apply remaining post-filters (`tags` via Python set intersection),
     convert `1.0 - distance` → score, re-rank desc, trim to `limit`.
     `rowDict["score"]` is set AFTER `dbUtils.sqlToTypedDict` conversion
     (mirror `chat_search.py:626`).

**searchMemories guard:** if `queryEmbedding is not None` AND (`not await
provider.isVectorSearchSupported()` or the vec0 table is absent — check via
`listTables`), return `[]`. Do **not** raise. Filter-only mode (no embedding)
never hits this guard — it reads `user_memories` directly. The caller
(§9.1) falls back to `getLatestMemories` when semantic search returns `[]`.

### 6.3 Wire `db.userMemories` into the `Database` registry

Four edits in `internal/database/database.py` (mirror how `chatEmbeddings`
and `chatSearch` are wired — verified at `database.py:108-126, 137-175,
205-217`):

1. `__slots__` (`:108-126`) — add `"userMemories",`.
2. Class-level type hint (`:137-175` block) — add
   `userMemories: UserMemoriesRepository` with a docstring field.
3. Import — add `from .repositories.user_memories import UserMemoriesRepository, UserMemoryDict` near the existing repository imports.
4. `__init__` (`:205-217`) — add `self.userMemories = UserMemoriesRepository(self.manager)` near `self.chatEmbeddings`.

## 7. Embedding helper (`memory_embedding_utils`)

**File:** `internal/bot/common/memory_embedding_utils.py` (new) — mirrors
`internal/bot/common/embedding_utils.py:32-124` line-for-line in shape.

> AGENTS.md: imports at file top; the LLMService import inside the function
> body is the established exception for the circular-import case and is
> already used at `embedding_utils.py:67-69` — keep it.

```python
"""Shared embedding generation + persistence for user memories.

Single recipe shared by the add_memory LLM tool (chat-time and refinement-time)
and the regeneration worker (§5.6 — re-embeds stale-model rows):

1. Resolve the model via LLMService.getLLMManager().getModel(modelName).
2. Generate the vector via model.generateEmbeddings(text).
3. Persist via db.userMemories.saveMemoryEmbedding(...) — which lazy-upserts
   the vec0 table AND sets embedding_model/embedding_dimensions on the
   user_memories row. No BLOB table (§5.1); vec0 is the sole embedding store.

Never raises — every failure path returns False so a transient embedding
outage can never break a chat turn or a refinement run. Mirrors
embedding_utils.embedAndSaveMessage.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from internal.database import Database

logger = logging.getLogger(__name__)


async def embedAndSaveMemory(
    chatId: int,
    userId: int,
    memoryId: str,
    content: str,
    modelName: str,
    db: "Database",
) -> bool:
    """Generate an embedding for a memory's content and persist it.

    Resolves the model by name via the LLM service singleton, generates the
    vector, and saves it through db.userMemories. Never raises.

    Args:
        chatId: Chat the memory belongs to.
        userId: User the memory is about.
        memoryId: ULID of the memory row.
        content: Text to embed.
        modelName: Embedding model name (the CALLER resolves this from the
            chat's EMBEDDING_MODEL setting via getChatSettings — mirrors
            embedAndSaveMessage which also takes modelName as a param rather
            than re-reading config inside the helper).
        db: Database wrapper providing userMemories.

    Returns:
        True on success, False on any failure (missing model, embedding
        API error, DB write error).
    """
    # Imported here to avoid the LLMService circular import (see embedding_utils.py:67-69
    # for the established precedent — this is the documented cyclic-dep exception to the
    # "imports at file top" rule in AGENTS.md). No ConfigManager import: modelName is a param.
    from internal.services.llm.service import LLMService

    ...  # resolve model, generate, save — copy the try/except ladder from embedding_utils:75-122


async def deleteMemoryEmbedding(
    chatId: int,
    userId: int,
    memoryId: str,
    db: "Database",
) -> bool:
    """Delete a memory's embedding (vec0-only; no BLOB table per §5.1). Never raises.

    Args:
        chatId: Chat the memory belongs to.
        userId: User the memory is about.
        memoryId: ULID of the memory row.
        db: Database wrapper providing userMemories.

    Returns:
        True on success, False on any failure.
    """
    ...
```

The model-name resolution reuses the existing pattern from
`embedAndSaveMessage` (`embedding_utils.py:32-124`): the **caller** resolves
`ChatSettingsKey.EMBEDDING_MODEL` for the chat (via `getChatSettings`) and
passes `modelName` into the helper — the helper does not read config itself.
Dimensions are derived from the model registry via
`LLMService.getLLMManager().getModel(modelName)` (same logic
`chat_embeddings.py` uses to pick `vec_message_embeddings_{N}`).

## 8. LLM tools (`add_memory` / `delete_memory` / `search_memories`)

### 8.1 New `ToolName` entries

In `internal/bot/constants.py`, replace the `# User Data` block (`:60-62`)
with a `# User Memories` block:

```python
    # User Memories
    ADD_MEMORY = "add_memory"
    DELETE_MEMORY = "delete_memory"
    SEARCH_MEMORIES = "search_memories"
```

### 8.2 Module-level constants

Co-locate in `internal/bot/common/handlers/user_data.py` (the handler that
owns the tools) at module scope, with `UPPER_CASE` and field docstrings
(AGENTS.md: "UPPER_CASE for constants"):

```python
PERMANENT_INJECTION_CAP: int = 10
"""Max permanent memories injected per (chat, user) into the system block (§9)."""

EPHEMERAL_RETRIEVAL_LIMIT: int = 5
"""Default cap on ephemeral memories retrieved per chat turn."""

MEMORY_DEDUP_DUPLICATE_THRESHOLD: float = 0.95
"""Similarity at/above which add_memory treats the new memory as a duplicate (no-op)."""

MEMORY_DEDUP_SIMILAR_THRESHOLD: float = 0.85
"""Similarity above which add_memory returns 'similar_exists' to the refinement LLM."""

MEMORY_SEARCH_TOPK_MULTIPLIER: int = 3
"""vec0 k is limit * this multiplier, to absorb post-filter trimming."""
```

### 8.3 `add_memory` — full spec

**Registration:** in `UserDataHandler.__init__` (same site as the retired
`ADD_USER_DATA`/`DELETE_USER_DATA` registrations at `user_data.py:162-208`),
alongside `DELETE_MEMORY` and `SEARCH_MEMORIES`. Register all three memory
tools here.

> REVIEW FIX (architect): The original draft assumed each handler registers
> its own chat-time tools and proposed a separate "main chat handler" (`LLMMessageHandler`)
> registration site. That is **wrong**. Verified by `grep "registerTool" internal/bot/common/handlers/`:
> `LLMMessageHandler` registers **zero** tools. Tool registration is **global** on the
> `LLMService` singleton — `LLMService._resolveTools` (`internal/services/llm/service.py:164-199`)
> holds one `toolsHandlers` registry and the per-call `useTools` dict selects which
> registered tools are offered. `SEARCH_MESSAGES` is registered by `ChatSearchHandler`
> (`chat_search.py:204`) yet is offered to the refinement LLM (explicit dict at
> `user_data.py:559-564`) and to the chat LLM (the `TOOLS_DEFAULT_DICT_KEY: True` wildcard
> at `llm_messages.py:278`). So a tool registered anywhere is available everywhere it is
> enabled via `useTools`.

**Availability is controlled per-call via `useTools`, NOT by registration
site.** Concretely:

- **Refinement call** (`user_data.py:559-564`): passes an explicit dict
  listing the memory tools → all three available (per §10.2(b)).
- **Chat-time call** (`llm_messages.py:274-288`): resolves
  `useTools = {TOOLS_DEFAULT_DICT_KEY: True}` (all registered tools on)
  then disables sandbox tools. **This wildcard enables every registered
  tool, including `DELETE_MEMORY`.** To honour D3 (delete is
  refinement-only) the chat-time dict MUST explicitly disable it:
  `useTools[ToolName.DELETE_MEMORY] = False` (add to the
  `useTools.update({...})` block at `llm_messages.py:280-288`). Likewise,
  when `MEMORY_INJECTION_ENABLED` is false, explicitly disable
  `ADD_MEMORY` + `SEARCH_MEMORIES` at chat-time so the memory tools don't
  appear before the feature is opted in (Phase 3 wires this gate).

**Tool signature** (LLM-facing):

```
add_memory(
    content: str,            # required, the memory body
    type: str,               # required, one of MemoryType values
    tags: Array[str],        # optional, default []
    permanent: bool,         # optional, default false
) -> {
    done: bool,
    action: "added" | "duplicate" | "similar_exists",  # similar_exists only visible at refinement-time
    memory_id?: str,         # when action == "added"
    existing?: {...},        # when action == "duplicate" | "similar_exists"
    error?: str,             # when done == false
}
```

**Handler logic** (pseudocode for `_llmToolAddMemory(self, extraData,
content, type, tags=None, permanent=False, **kwargs)`):

```
1. Resolve context from extraData["ensuredMessage"]:
     chatId    = ensuredMessage.recipient.id
     userId    = ensuredMessage.sender.id
     threadId  = permanent ? None : (ensuredMessage.threadId or DEFAULT_THREAD_ID)
   (Validate type against MemoryType values; reject unknown -> {"done": False, "error": ...}.)
   Resolve the embedding model name + dimensions for this chat:
     chatSettings = await self.getChatSettings(chatId)
     modelName    = chatSettings[ChatSettingsKey.EMBEDDING_MODEL].toStr()
     dimensions   = <from the model registry via LLMService.getLLMManager().getModel(modelName)>
2. memoryId = ULID()
3. Dedup pre-filter:
     embed = await model.generateEmbeddings(content)  # never raises; on failure skip dedup
     results = await db.userMemories.searchMemories(
         chatId, userId, queryEmbedding=embed, threadId=threadId, limit=1,
         modelName=modelName, dimensions=dimensions)
     topScore = results[0]["score"] if results else 0.0   # score set by searchMemories (§6)
     if topScore >= MEMORY_DEDUP_DUPLICATE_THRESHOLD:
         return {"done": True, "action": "duplicate", "existing": results[0]}
     # Grey zone: behaviour depends on call-time context (see D5):
     isRefinement = extraData.get("isRefinement", False)   # set by _runRefinement
     if topScore > MEMORY_DEDUP_SIMILAR_THRESHOLD:
         if isRefinement:
             return {"done": True, "action": "similar_exists", "existing": results[0]}
         # chat-time: treat grey zone as duplicate to avoid mid-turn curation
         return {"done": True, "action": "duplicate", "existing": results[0]}
4. Insert + embed:
     await db.userMemories.addMemory(chatId, userId, memoryId, type=type, content=content,
                                     tags=tags or [], permanent=permanent, threadId=threadId,
                                     source="chat" if not isRefinement else "refinement")
     await embedAndSaveMemory(chatId, userId, memoryId, content, modelName, self.db)  # best-effort
5. return {"done": True, "action": "added", "memory_id": memoryId}
```

**Never raises:** wrap the whole body in try/except; on any exception return
`{"done": False, "error": str(e)}`. This is the hard contract from §3.4.

### 8.4 `delete_memory` — full spec

**Registration:** `UserDataHandler.__init__` (same block as `ADD_MEMORY`).
Refinement-only availability is enforced at the `useTools` layer — chat-time
explicitly sets `ToolName.DELETE_MEMORY: False` (see §8.3) — NOT by
registration site, because tool registration is global on `LLMService`.

**Tool signature:**

```
delete_memory(
    memory_id: str,   # optional — delete by exact id
    query: str,       # optional — embed, find top-N above threshold, delete
) -> { done: bool, deleted: int, error?: str }
```

Exactly one of `memory_id` / `query` must be provided (else
`{"done": False, "error": "..."}`).

**Handler logic** (`_llmToolDeleteMemory`):

```
1. Resolve chatId/userId from extraData["ensuredMessage"] (same as add_memory).
2. If memory_id:
     ok = await db.userMemories.deleteMemory(chatId, userId, memory_id)
     await deleteMemoryEmbedding(chatId, userId, memory_id, self.db)  # best-effort
     return {"done": True, "deleted": 1 if ok else 0}
3. If query:
     embed = await model.generateEmbeddings(query)
     hits = await db.userMemories.searchMemories(
         chatId, userId, queryEmbedding=embed, limit=5, ...)
     toDelete = [m for m in hits if m["score"] >= MEMORY_DEDUP_SIMILAR_THRESHOLD]
     # NOTE: searchMemories can return permanent memories too. Explicit by-id
     # deleteMemory below is UNRESTRICTED — a permanent memory MAY be deleted
     # here, because this is an explicit, query-driven action reviewed by the
     # refinement LLM. Bulk deleteMemoriesByQuery is the path that is
     # permanent-guarded (§6, always AND permanent = 0).
     n = 0
     for m in toDelete:
         if await db.userMemories.deleteMemory(chatId, userId, m["memory_id"]):
             await deleteMemoryEmbedding(chatId, userId, m["memory_id"], self.db)
             n += 1
     return {"done": True, "deleted": n}
```

`[DESIGN CHOICE]` — query-based delete threshold is
`MEMORY_DEDUP_SIMILAR_THRESHOLD` (0.85), stricter than duplicate. Letting
delete fire at 0.85 means "delete things clearly about the same topic";
lower would be dangerous. Reviewer should sanity-check this against the
refinement prompt's delete instructions (§10).

### 8.5 `search_memories` — full spec

**Registration:** `UserDataHandler.__init__` (same block as `ADD_MEMORY`).
Chat-time availability follows `ADD_MEMORY` (see §8.3): on when
`MEMORY_INJECTION_ENABLED` is true, off otherwise, via the chat-time
`useTools` dict.

**Tool signature:**

```
search_memories(
    query: str,           # OPTIONAL — when absent, filter-only mode (no embedding)
    limit: int = 5,
    type: str,            # optional
    tags: Array[str],     # optional
    permanent: bool,      # optional — restrict to permanent only
) -> { done: bool, results: [...], count: int, error?: str }
```

**Handler logic** (`_llmToolSearchMemories`):

```
1. Resolve chatId/userId from extraData["ensuredMessage"].
2. If query is provided:
     embed = await model.generateEmbeddings(query)   # best-effort; None on failure
   else:
     embed = None    # filter-only mode — lets the LLM ask "all preference memories" with no embedding
3. results = await db.userMemories.searchMemories(
       chatId, userId, queryEmbedding=embed,
       threadId=ensuredMessage.threadId or DEFAULT_THREAD_ID,
       permanent=permanent, type=type, tags=tags, limit=limit, modelName=..., dimensions=...)
   # NOTE: when queryEmbedding is None, searchMemories runs a filter-only scan
   # (score=0.0 on every row); when provided but vec0 is unsupported/absent, returns [].
4. return {"done": True, "results": results, "count": len(results)}
```

`[DESIGN CHOICE]` — `search_memories` searches the **caller's own** scope
only (`chatId, userId, threadId`). It does not search other users' memories
even in a group chat; this matches D1's per-(chat,user) scoping and avoids
leaking one user's memories to another. If a future "what does the group
know about X" feature is wanted, it gets a separate tool.

> **Superseded (2026-07-10):** This design choice was reversed —
> `search_memories` now accepts an optional `user` parameter (a login with
> or without `@`, or a numeric `user_id`) to search a different user's
> memories within the same chat. It was added to the existing tool rather
> than as a separate tool. When the `user` login cannot be resolved, the
> tool returns `{"done": False, "error": ...}` without searching (no
> all-user fallback). See [`memories/user-memories.md`](../llm/memories/user-memories.md)
> §`search_memories`.

## 9. Retrieval + injection

### 9.1 `_buildMemoriesBlock` helper

**Location:** `BaseBotHandler` method (so all three injection sites inherit
it). Added to `internal/bot/common/handlers/base.py` near
`getThreadByMessageForLLM` (`:663-850`).

```python
async def _buildMemoriesBlock(
    self,
    chatId: int,
    userId: int,
    threadId: int,
    currentUserMessageText: Optional[str],
    chatSettings: ChatSettingsDict,
) -> Optional[str]:
    """Build the <user-memories> system-prompt block for a chat turn.

    Loads permanent memories (always-in, capped) plus ephemeral memories
    (latest- or relevant-mode), formats them into a single text block, and
    returns it. Returns None when injection is disabled or no memories exist.

    Args:
        chatId: Chat id.
        userId: User the reply is addressed to / about.
        threadId: Active thread (DEFAULT_THREAD_ID for main).
        currentUserMessageText: The user's incoming message text, used only
            when retrieval mode is "relevant" (to embed for the search).
            May be None; relevant-mode then falls back to latest.
        chatSettings: Resolved chat settings for chatId.

    Returns:
        Formatted memories block string, or None.
    """
```

**Logic:**

```
if not chatSettings[ChatSettingsKey.MEMORY_INJECTION_ENABLED].toBool():
    return None

permanent = await self.db.userMemories.getPermanentMemories(
    chatId, userId, threadId, limit=PERMANENT_INJECTION_CAP)

mode = chatSettings[ChatSettingsKey.MEMORY_RETRIEVAL_MODE].toStr()  # "latest" | "relevant"
ephemeral: List[UserMemoryDict] = []
if mode == "relevant" and currentUserMessageText:
    if chatSettings[ChatSettingsKey.EMBEDDINGS_ENABLED].toBool():
        embed = await _safeEmbed(currentUserMessageText)  # best-effort; None on failure
        if embed is not None:
            ephemeral = await self.db.userMemories.searchMemories(
                chatId, userId, embed, threadId=threadId,
                permanent=False, limit=EPHEMERAL_RETRIEVAL_LIMIT, ...)
if not ephemeral:   # covers: mode == "latest", relevant-but-no-embeddings, relevant-but-search-empty
    ephemeral = await self.db.userMemories.getLatestMemories(
        chatId, userId, threadId, limit=EPHEMERAL_RETRIEVAL_LIMIT)

if not permanent and not ephemeral:
    return None  # genuinely nothing to inject

return _formatMemoriesBlock(permanent, ephemeral)
```

> REVIEW FIX (architect): **Permanent-empty gap (item 5 from the review
> brief) — ruling: option (a).** The original draft returned `None` as soon
> as `permanent` was empty, which silently dropped ephemeral memories for a
> brand-new user who hasn't had a first bio created yet. That makes the
> ephemeral store useless exactly when it has its only content. Fixed: the
> block is built from `(permanent, ephemeral)` and returns `None` only when
> **both** are empty (or injection is disabled). `_formatMemoriesBlock`
> already renders an empty section by omitting its header, so a
> permanent-empty / ephemeral-only block renders as just the `Recent:`
> section with no added complexity. Option (b) was rejected: documenting a
> known-correctness bug as "accepted" is worse than the trivial render tweak
> that removes it. D2 ("always-in permanent + toggle ephemeral") is honoured
> — "always-in" means "every message when present", not "block absent when
> the permanent section happens to be empty".

> REVIEW FIX (architect): **Type-name correction.** The signature used
> `ChatSettingsValueDict`, which does not exist in the codebase. The real
> alias is `ChatSettingsDict = Dict[ChatSettingsKey, ChatSettingsValue]`
> (`internal/bot/models/chat_settings.py:613`). Fixed.

**`_formatMemoriesBlock(permanent, ephemeral) -> str`** (module-level helper
or staticmethod) renders:

```
<user-memories>
Permanent:
[bio] <content>  #<tag> ...
[preference] <content>
Recent:
[fact] <content>
[event] <content>
</user-memories>
```

Each line: `[type] content #tag1 #tag2` (tags omitted when empty). Permanent
section sorted by `MemoryType` then `updated_at`; recent section newest-first.
**Omit the `Permanent:` (or `Recent:`) header and its body entirely when
that list is empty** — this is what lets the permanent-empty / ephemeral-only
case (§9.1) render as just the `Recent:` block. Keep the block under ~2 KB
to avoid bloating the system prompt — if the combined output exceeds a soft
cap (e.g. 2000 chars), trim the recent
section first.

### 9.2 The three injection sites

Insert the block into the system message at each site, **after**
`CHAT_PROMPT_SUFFIX` (and after `RANDOM_ANSWER_PROMPT` at site 3). Provide a
small helper on `BaseBotHandler`:

```python
def _injectMemoriesBlock(
    self,
    messages: List[ModelMessage],
    block: Optional[str],
) -> None:
    """Append the memories block to messages[0].content (the system message) in place.

    Args:
        messages: The message list whose [0] is the system message.
        block: The formatted block (or None to no-op).

    Returns:
        None.
    """
    if block and messages:
        messages[0].content = f"{messages[0].content}\n\n{block}"
```

**Site 1 — `BaseBotHandler.getThreadByMessageForLLM` (`base.py:701-708`).**
After `ret` is built (the system message is `ret[0]`), before the
`if dbMessage["root_message_id"] is None:` branch (`:710`), resolve the
target user and inject:

```
dbMessageUserId = dbMessage["user_id"]  # the user the thread is about
threadId = dbMessage["thread_id"] or DEFAULT_THREAD_ID
block = await self._buildMemoriesBlock(
    chatId, dbMessageUserId, threadId,
    currentUserMessageText=dbMessage.get("text"), chatSettings=chatSettings)
self._injectMemoriesBlock(ret, block)
```

`[DESIGN CHOICE]` — which user the memories are about. In a thread the
"owner" is the root-message sender; `getThreadByMessageForLLM` has the
`dbMessage` row, so `dbMessage["user_id"]` is the right key. **Verified:**
the `chat_messages` schema and every `chat_search.py` JOIN use
`c.user_id` (e.g. `chat_search.py:241, 244, 572, 614`); the field is
`user_id`, not `sender_id`. The original "confirm during execution" hedge
is resolved.

**Site 2 — `LLMMessageHandler.handleMention` (`llm_messages.py:688-695`).**
After `reqMessages` is built (`:688-695`), before the parent-message block
(`:697`):

```
block = await self._buildMemoriesBlock(
    chatId, ensuredMessage.sender.id,
    ensuredMessage.threadId or DEFAULT_THREAD_ID,
    currentUserMessageText=ensuredMessage.formatMessageText(),
    chatSettings=chatSettings)
self._injectMemoriesBlock(reqMessages, block)
```

**Site 3 — `LLMMessageHandler.handleRandomMessage` (`llm_messages.py:836-847`).**
After the `storedMessages` system message is built (`:838-847`):

```
block = await self._buildMemoriesBlock(
    chatId, ensuredMessage.sender.id,
    ensuredMessage.threadId or DEFAULT_THREAD_ID,
    currentUserMessageText=ensuredMessage.formatMessageText(),
    chatSettings=chatSettings)
self._injectMemoriesBlock(storedMessages, block)
```

### 9.3 Retire `EnsuredMessage.applyUserMetadata` / `userSummary` path

> **PHASE 4B UPDATE (2026-07-07) — this overrides the original "keep /
> deprecate" plan below.** Gate 1 review of Phase 4b established that by the
> end of Phase 4b there are **no remaining writers or readers** of the
> rolling-bio `userSummary` field:
>
> - **Writers gone** — the `_runRefinement` rewrite (§10, Phase 4a) stops
>   writing the `summary` blob to `chat_users.metadata.memoryRefinement`
>   (only the message cursor is persisted now). Migration backfill B
>   (§5.4 / `migration_020`) copies legacy blobs into permanent `type=bio`
>   rows and then leaves them unread.
> - **Readers gone** — the structured `<user-memories>` block (§9.1 /
>   `_buildMemoriesBlock`) fully replaces the single-string `userSummary`
>   injection at all four system-message construction sites.
>
> The original `[DESIGN CHOICE]` to keep the path "for rollback safety"
> was therefore retracted: a stub method + field that nothing writes and
> nothing reads is pure surface area. Phase 4b **removed the path
> entirely**: `EnsuredMessage.applyUserMetadata`, the `EnsuredMessage.userSummary`
> field, and the `userSummary` key in `EnsuredMessage.formatForLLM` are all
> gone. The `chat-prompt-suffix` line in `bot-defaults.toml` documenting the
> `userSummary` JSON field was dropped in the same phase. The old
> `_updateEMessageUserData` / `HandlersManager._processMessageRec`
> `applyUserMetadata(...)` call sites were removed with it.
>
> Canonical documentation of the replacement system lives in
> [`docs/llm/memories/user-memories.md`](../llm/memories/user-memories.md).
> The historical "keep / deprecate" rationale is preserved below for the
> audit trail only — it no longer describes the shipped code.

**Original v1 plan (superseded — NOT what shipped):**

`internal/bot/models/ensured_message.py:917-948` reads
`metadata.memoryRefinement[threadId].summary` into `self.userSummary`, which
`formatForLLM` (`:1170`) serialises into each message JSON under key
`userSummary`.

The original plan was to **stop populating `userSummary`** (the refinement
rewrite no longer writes the rolling-bio blob) but **keep the method + the
`userSummary` field** for backward-compat with a stale `# DEPRECATED` comment,
and to leave the `chat-prompt-suffix` `userSummary` docs line in
`bot-defaults.toml`. The alternative considered was repointing
`applyUserMetadata` to load the permanent `type=bio` memory on the fly
(rejected for v1: it adds a DB round-trip per message and duplicates
`_buildMemoriesBlock`'s permanent load). Phase 4b went further than either
option and removed the path outright, for the reasons in the banner above.

## 10. Refinement changes (`_runRefinement` rewrite)

**File:** `internal/bot/common/handlers/user_data.py`, method `_runRefinement`
(body at `:472-618`).

### 10.1 What stays the same

- Accounting / cron / locking: `_dtCronJob` (`:301-470`), `_accounting`,
  `_refineLock`, the message-count / time thresholds from
  `configs/00-defaults/user-memory.toml`. These decide **when** to refine;
  only the **body** of `_runRefinement` changes.
- `_renderMessagesForLLM` (`:681-700`) and `_makeSyntheticEnsuredMessage`
  (`:702-727`) — both reused as-is. The synthetic `EnsuredMessage` is what
  gives the tool handlers a `chatId/userId/threadId` context.

### 10.2 What changes

**(a) System + user prompts** (defaults rewritten — see §11). The new system
prompt instructs the LLM to:

1. Study the rendered recent messages.
2. Call `search_memories` to see what is already known about this user.
3. Extract durable facts / preferences / events as **discrete** memories via
   `add_memory` (each with a `type` and, where useful, `tags`).
4. Maintain **exactly one** permanent `type=bio` memory as the high-level
   summary (call `add_memory` with `permanent=true, type=bio`; the dedup
   state machine handles re-adding — see D1/D5).
5. When `add_memory` returns `action="similar_exists"`, **decide**: delete
   the old memory (`delete_memory`) and re-add an updated one, or skip.
6. Use `delete_memory` to remove stale or conflicting memories.
7. Return only a short confirmation string (not a dossier) — the memories
   themselves are the artefact.

**(b) `useTools` change** at `user_data.py:559-564`:

```python
useTools={
    ToolName.ADD_MEMORY: True,
    ToolName.DELETE_MEMORY: True,
    ToolName.SEARCH_MEMORIES: True,
    ToolName.SEARCH_MESSAGES: True,
    ToolName.GET_CURRENT_DATETIME: True,
},
```

**(c) `extraData` augmentation** at `user_data.py:565` — add
`"isRefinement": True` so `add_memory` returns the `similar_exists` signal
only in this context (D5):

```python
extraData={"ensuredMessage": synthEnsuredMessage, "typingManager": None, "isRefinement": True},
```

**(d) Remove `_persistMemoryEntry` / the rolling-bio write block**
(`user_data.py:597-614`). Memories now persist **live** via the tools during
the LLM call; there is nothing to write back to `chat_users.metadata` after
the call returns. The `newSummary` handling (`:569`, `:593-595`) and the
JSONL log's `summary` field (`:590`, `:672`) become vestigial:

- Drop the `newSummary = result.resultText` block and the empty-summary
  early-return — the confirmation text is not used downstream.
- **Extend the JSONL log** (§15 risk mitigation) to record tool-call counts
  instead of a summary: add fields `addCount`, `deleteCount`, `searchCount`
  to `_writeRefinementJsonLog` (`:620-679`). **Source resolved:**
  `ModelRunResult` (`lib/ai/models.py:838-946`) exposes
  `toolUsageHistory: Optional[Sequence[ModelMessage]]` (the full multi-turn
  message sequence) and `toolCalls: List[LLMToolCall]` (the final assistant
  turn's calls). Derive per-tool counts by walking `result.toolUsageHistory`:
  for each assistant `ModelMessage`, count `tc.name` across `msg.toolCalls`,
  accumulating per name. `LLMToolCall` carries `name`
  (`lib/ai/models.py:552-556`). **Drop `similarExistsCount`** from the log
  schema: it is a *return value* of `add_memory`, not a tool call, and
  recovering it requires parsing tool-result message payloads (role="tool")
  — fragile and not worth the complexity. The `addCount`/`deleteCount`/
  `searchCount` triplet plus the existing fields gives enough observability
  for the grey-zone dedup review (§15).

`[DESIGN CHOICE]` — keeping vs. removing `_writeRefinementJsonLog`. Keep it;
the grey-zone dedup (D5) explicitly relies on LLM judgement and the log is
the only observability for that. The fields change; the log stays.

## 11. New chat settings (4-site spec each)

### 11.1 `MEMORY_INJECTION_ENABLED` (BOOL)

Gates the entire memories block (§9). Default `false` (off by default;
friends/opt-in turn it on).

| Site | File:line | Entry |
|------|-----------|-------|
| 1. enum | `internal/bot/models/chat_settings.py:~318` (after `MEMORY_REFINE_USER_PROMPT_TEMPLATE`) | `MEMORY_INJECTION_ENABLED = "memory-injection-enabled"` + docstring |
| 2. info | `chat_settings.py:~920` (after the `MEMORY_REFINE_USER_PROMPT_TEMPLATE` info entry) | `{type: BOOL, short: "...", long: "...", page: ChatSettingsPage.FRIEND}` |
| 3. default | `configs/00-defaults/bot-defaults.toml` (near `:158`) | `memory-injection-enabled = false` |
| 4. consumer | `base.py` `_buildMemoriesBlock` (§9.1) | `chatSettings[ChatSettingsKey.MEMORY_INJECTION_ENABLED].toBool()` |

Mirror `EMBEDDINGS_ENABLED` exactly for the shape (`chat_settings.py:435-436`
enum, `:1107-1112` info, `bot-defaults.toml:128` default,
`chat_search.py:498` consumer).

### 11.2 `MEMORY_RETRIEVAL_MODE` (STRING)

Latest-vs-relevant toggle for ephemeral memories. Default `"latest"`.

| Site | File:line | Entry |
|------|-----------|-------|
| 1. enum | `chat_settings.py` (next to `MEMORY_INJECTION_ENABLED`) | `MEMORY_RETRIEVAL_MODE = "memory-retrieval-mode"` + docstring |
| 2. info | `chat_settings.py` (next to the above info entry) | `{type: STRING, short: "...", long: "latest или relevant ...", page: ChatSettingsPage.FRIEND}` |
| 3. default | `bot-defaults.toml` | `memory-retrieval-mode = "latest"` |
| 4. consumer | `base.py` `_buildMemoriesBlock` (§9.1) | `chatSettings[ChatSettingsKey.MEMORY_RETRIEVAL_MODE].toStr()` |

`[DESIGN CHOICE]` — `STRING` not an enum-of-values type. The repo's
`ChatSettingsType` (`chat_settings.py:261`) has no enum type, only
`STRING`. Validation that the value is `"latest"` or `"relevant"` happens at
read time in `_buildMemoriesBlock` (treat anything ≠ `"relevant"` as
`"latest"`). A future `ChatSettingsType.ENUM` could formalise this; out of
scope here.

### 11.3 Rewritten defaults for existing refinement settings

- `MEMORY_REFINE_SYSTEM_PROMPT` default (`bot-defaults.toml`, currently a
  rolling-bio instruction) → **rewrite** to the tool-based extraction
  instructions in §10.2(a). Keep the `chat_settings.py:906-913` info entry
  (its `long` text already says "role and rules").
- `MEMORY_REFINE_USER_PROMPT_TEMPLATE` default → **rewrite** to a template
  that supplies `{existingMemories}` (a pre-render of the user's current
  permanent memories, fetched before the call) and `{messages}`. Drop
  `{existingSummary}` and `{existingUserData}` placeholders — the LLM gets
  those via `search_memories`. Update the info `long` text at
  `chat_settings.py:918` to document the new placeholders.

### 11.4 Keep

`MEMORY_REFINEMENT_ENABLED`, `MEMORY_REFINE_MODEL`,
`MEMORY_REFINE_FALLBACK_MODEL` — unchanged.

### 11.5 Embedding model-drift regeneration settings

Two new settings (4-site each) that gate the regeneration worker in §5.6.
They mirror `EMBEDDINGS_ENABLED` / `REGENERATE_EMBEDDINGS` (chat-history
search) exactly for shape. The target model reuses the existing
`EMBEDDING_MODEL` setting (`chat_settings.py:433-434`, default
`bot-defaults.toml:130`) — do NOT add a memory-specific model.

**`MEMORY_EMBEDDINGS_ENABLED` (BOOL)** — discovery: which chats the cron
scans for memory regeneration.

| Site | File:line | Entry |
|------|-----------|-------|
| 1. enum | `chat_settings.py` (next to `MEMORY_INJECTION_ENABLED`) | `MEMORY_EMBEDDINGS_ENABLED = "memory-embeddings-enabled"` + docstring |
| 2. info | `chat_settings.py` (next to the above info entry) | `{type: BOOL, short: "...", long: "...", page: ChatSettingsPage.FRIEND}` |
| 3. default | `configs/00-defaults/bot-defaults.toml` | `memory-embeddings-enabled = false` |
| 4. consumer | `UserDataHandler._dtCronJob` regeneration loop (§5.6) | `chatSettings[ChatSettingsKey.MEMORY_EMBEDDINGS_ENABLED].toBool()` |

Mirror `EMBEDDINGS_ENABLED` for the shape (`chat_settings.py:435-436` enum,
`:1107-1112` info, `bot-defaults.toml:128` default, `chat_search.py:498`
consumer).

**`MEMORY_REGENERATE_EMBEDDINGS` (BOOL, default `true`)** — per-chat gate
once `MEMORY_EMBEDDINGS_ENABLED` is on. Default `true` (when discovery
flags a chat, regeneration is on by default — matches the chat-history
`REGENERATE_EMBEDDINGS` default).

| Site | File:line | Entry |
|------|-----------|-------|
| 1. enum | `chat_settings.py` (next to `MEMORY_EMBEDDINGS_ENABLED`) | `MEMORY_REGENERATE_EMBEDDINGS = "memory-regenerate-embeddings"` + docstring |
| 2. info | `chat_settings.py` | `{type: BOOL, short: "...", long: "...", page: ChatSettingsPage.FRIEND}` |
| 3. default | `configs/00-defaults/bot-defaults.toml` | `memory-regenerate-embeddings = true` |
| 4. consumer | `UserDataHandler._dtCronJob` regeneration loop (§5.6) | `chatSettings[ChatSettingsKey.MEMORY_REGENERATE_EMBEDDINGS].toBool()` |

Mirror `REGENERATE_EMBEDDINGS` (`chat_settings.py:439-440` enum,
`:1118-1124` info, `bot-defaults.toml:131` default).

> AMENDMENT (user review, change #2): These two settings + the §5.6 cron
> turn embedding-model-drift regeneration from a Non-Goal into a shipped
> feature, mirroring the chat-history precedent one-to-one.

### 11.6 Admin UI — extending `/memory_config`

Repoints the existing `/memory_config` wizard at `user_memories` (the
`user_data` key-value store it currently edits is being retired — §12) and
adds browse/filter/delete for the calling user's own memories. **Private-only,
unchanged** (`visibility={CommandPermission.PRIVATE}`). The wizard only ever
shows the calling user's OWN memories (`userId = user.id`).

**Current `/memory_config` state (verified, do not re-explore):**

- Command: `@commandHandlerV2(commands=("memory_config",))` decorates
  `memory_config_command` at `internal/bot/common/handlers/user_data.py:1357-1400`.
  No tier gate.
- Wizard dispatcher: `_handleUserDataConfiguration(data, *, messageId,
  messageChatId, user)` at `user_data.py:1216-1279`, matches on
  `ButtonUserDataConfigAction` (`internal/bot/models/enums.py:155-187`:
  Init / Cancel / ChatSelected / ClearChatData / DeleteKey / KeySelected /
  SetValue).
- Callback router: `callbackHandler` at `user_data.py:1281-1311`.
- Step handlers: `_handleConfigAction_Init` (chat picker) `:785-837`,
  `_handleConfigAction_ChatSelected` (key list) `:839-941`,
  `_handleConfigAction_KeySelected` `:1053-1144`, `_handleConfigAction_SetValue`
  `:1146-1214`, `_handleConfigAction_DeleteKey` `:996-1051`,
  `_handleConfigAction_ClearChatData` `:943-994`. All render via
  `self.editMessage(..., inlineKeyboard=keyboard)`. **No pagination today.**
- CRUD routes through `self.cache.getChatUserData` / `setChatUserData` /
  `unsetChatUserData` / `clearChatUserData` (cache service `:865/:900/:945/:982`),
  flat `key→value`, NO topic/category concept.
- Related: `/get_my_data` at `:1317-1355` (dumps as JSON code block).

**Extension spec:**

1. **Repoint the wizard at `user_memories`** (via `self.db.userMemories`)
   instead of `self.cache` user-data methods. The flat key→value model
   becomes the typed memory model (`content` / `type` / `tags` / `permanent`
   / `thread_id`).
2. **Add a topic/type filter step** = filter by `MemoryType`
   (bio/preference/fact/event/relationship). New flow: **chat picker →
   topic/type picker → list memories of that type (paginated) → per-memory
   view → delete**.
3. **New `ButtonUserDataConfigAction` entries** (extend the enum at
   `internal/bot/models/enums.py:155-187`) for the new wizard steps:
   - `TopicSelected` — user picked a `MemoryType` (or "All types").
   - `MemorySelected` — user picked a specific memory_id from the list.
   - `DeleteMemory` — confirm + delete the selected memory
     (`db.userMemories.deleteMemory`, unrestricted by-id — §8.4).
   - `NextPage` / `PrevPage` — pagination controls (see below).
   - `TagFilter` — enter/choose a freeform tag to filter by (secondary
     dimension, see below).
4. **Add pagination** — the current wizard has none, but a user may have
   many memories of one type. Sub-task: mirror whatever pagination pattern
   exists elsewhere in the bot if one exists; if no precedent, simple
   offset-based prev/next inline buttons carrying `(offset, type, tag)` in
   the callback payload. Flag the chosen pattern in the PR.
5. **Freeform-tag filter as a secondary dimension** — D4 has freeform tags;
   the wizard supports filtering by a chosen tag (enter or pick from the
   user's existing tags) in addition to the type filter.
6. **Per-memory view** renders: `content`, `tags`, `permanent` flag,
   `source`, `updated_at`, `thread_id` (or "cross-thread" when NULL).
7. **Keep `/get_my_data` working** by repointing it at `user_memories` too
   (dump as JSON code block, or a readable list of `[type] content #tags`
   lines).
8. **Access** — private-only (unchanged); the wizard only ever shows the
   calling user's OWN memories (`userId = user.id`).

> AMENDMENT (user review, change #3): Promoted from a Non-Goal ("GUI / admin
> tooling for memories") to a Goal. The `/memory_config` wizard already
> exists and is the natural home for interactive memory management; repointing
> it at `user_memories` (rather than building a new command) keeps the UX
> surface flat. Substantial UI work — sequenced as a new Phase 5 (§13).

## 12. Retirement of `user_data` tools

### Removed

- `ToolName.ADD_USER_DATA`, `ToolName.DELETE_USER_DATA` from
  `internal/bot/constants.py:60-62` (replaced by the `# User Memories` block
  in §8.1).
- `_llmToolSetUserData` (`user_data.py:214-251`) and
  `_llmToolDeleteUserData` (`:253-287`) — delete the methods.
- Their `registerTool(...)` calls in `UserDataHandler.__init__`
  (`:162-208` — `ADD_USER_DATA` at `:162-191`, `DELETE_USER_DATA` at
  `:193-208`).
- The `useTools={ADD_USER_DATA, DELETE_USER_DATA, ...}` entries at
  `user_data.py:559-564` (replaced by §10.2(b)).

### Kept for rollback

- The `user_data` **table** (migration_020 does not drop it; §5.1 down()
  also leaves it).
- `UserDataRepository` + `cache.setChatUserData` / `unsetChatUserData` — the
  tools that called them are gone, but the repo stays in case a rollback
  needs to re-expose the old tools. Note in the PR that a future migration
  can drop both.

## 13. Implementation phases

Each phase is scoped to fit a ~60-step developer budget and ends with
`make format lint && make test` plus a `code-reviewer` pass. Run
`./venv/bin/python3` for any ad-hoc verification (never `python`).

### Phase 1 — Foundation (no behaviour change)

**Files:**

- `internal/database/migrations/versions/migration_020_user_memories.py` (new)
  — `user_memories` table (with `embedding_model` / `embedding_dimensions`
  columns per §5.1; **no BLOB table**) + both backfills (§5.1, §5.5).
- `internal/bot/models/memory_type.py` (new) — `MemoryType` StrEnum (§5.3).
- `internal/database/repositories/user_memories.py` (new) —
  `UserMemoryDict` (§5.4, snake_case keys), `UserMemoriesRepository` with
  all methods including the `vec_user_memories_{dim}` lazy creator +
  `vectorSearch` wiring, the merged `searchMemories` (filter-only + semantic
  modes, §6 — no separate `findSimilarMemories`), and the regeneration
  methods `getMemoriesWithoutEmbeddings` / `deleteObsoleteMemoryEmbeddings`
  (§5.6, §6).
- `internal/bot/common/memory_embedding_utils.py` (new) —
  `embedAndSaveMemory` / `deleteMemoryEmbedding` (§7).
- `internal/database/database.py` — wire `db.userMemories` (4 edits, §6.3).
- `tests/database/repositories/test_user_memories.py` (new) — CRUD, latest,
  permanent (incl. `threadId` cross+thread merge), `searchMemories` (both
  modes; skip semantic with a marker when vec0 unavailable in CI),
  `getMemoriesWithoutEmbeddings` / `deleteObsoleteMemoryEmbeddings` (§14).

**Exit criteria:** `make test` green; migration up/down idempotent on a
populated `user_data` + `chat_users.metadata`; the repository round-trips a
memory through add → embed → search → delete.

**`update-project-docs` trigger:** schema changed — update
`docs/database-schema.md` + `docs/database-schema-llm.md` and
`docs/llm/database.md` within this phase (the migration ships the new
tables; the docs must describe them in the same PR).

### Phase 2 — Tools + dedup + retirement

**Files:**

- `internal/bot/constants.py` — swap the `# User Data` enum block for
  `# User Memories` (§8.1).
- `internal/bot/common/handlers/user_data.py` — add `_llmToolAddMemory`,
  `_llmToolDeleteMemory`, `_llmToolSearchMemories` with the dedup state
  machine (§8.3-8.5); register in `__init__`; retire `_llmToolSetUserData` /
  `_llmToolDeleteUserData` + their registrations (§12); add the module-level
  constants (§8.2).
- `internal/bot/common/handlers/llm_messages.py` (`_sendLLMChatMessage`,
  `:274-288`) — add `ToolName.DELETE_MEMORY: False` to the chat-time
  `useTools` dict so the refinement-only tool is never offered at chat-time
  (D3). Per §8.3, registration is global in `UserDataHandler.__init__`;
  **availability** is gated here via `useTools`. Phase 2 ships
  `DELETE_MEMORY` disabled at chat-time; Phase 3 adds the
  `MEMORY_INJECTION_ENABLED` gate for `ADD_MEMORY`/`SEARCH_MEMORIES` in the
  same `useTools` block (no temporary `MEMORY_REFINEMENT_ENABLED` gate
  needed — the chat-time `useTools` wildcard is the single gate point).

> REVIEW FIX (architect): The original Phase-2 text proposed gating
> "chat-time registration" on `MEMORY_REFINEMENT_ENABLED` temporarily. That
> was based on the misconception that registration site controls
> availability. Registration is global; the gate is the per-call `useTools`
> dict in `_sendLLMChatMessage`. Phase 2 must add `DELETE_MEMORY: False`
> there immediately (otherwise D3 is violated the moment the tool is
> registered). The `ADD_MEMORY`/`SEARCH_MEMORIES` gate moves to Phase 3
> alongside the `MEMORY_INJECTION_ENABLED` setting.
- `tests/bot/common/handlers/test_user_data.py` (extend existing) —
  `add_memory` (added / duplicate / similar_exists), `delete_memory`
  (by-id, by-query), `search_memories`; mock `generateEmbeddings` (§14).

**Exit criteria:** tools never raise; dedup thresholds behave exactly; old
tools are gone; `make test` green.

### Phase 3 — Retrieval + injection + regeneration + chat settings

**Files:**

- `internal/bot/models/chat_settings.py` — add `MEMORY_INJECTION_ENABLED`
  and `MEMORY_RETRIEVAL_MODE` to the enum + `_chatSettingsInfo` (§11.1,
  §11.2); add the two regeneration settings `MEMORY_EMBEDDINGS_ENABLED` and
  `MEMORY_REGENERATE_EMBEDDINGS` (§11.5).
- `configs/00-defaults/bot-defaults.toml` — add the four defaults
  (`memory-injection-enabled`, `memory-retrieval-mode`,
  `memory-embeddings-enabled`, `memory-regenerate-embeddings`).
- `internal/bot/common/handlers/base.py` — add `_buildMemoriesBlock` +
  `_injectMemoriesBlock`; call at site 1 (`:701-708`) (§9.1, §9.2).
- `internal/bot/common/handlers/llm_messages.py` — call at sites 2
  (`:688-695`) and 3 (`:838-847`); in `_sendLLMChatMessage`'s `useTools`
  block (`:274-288`), add the `MEMORY_INJECTION_ENABLED` gate for
  `ADD_MEMORY`/`SEARCH_MEMORIES` (on when true, off when false). The
  Phase-2 `DELETE_MEMORY: False` exclusion stays.
- `internal/bot/common/handlers/user_data.py` — add the embedding-regen
  section to `UserDataHandler._dtCronJob` (`:301-470`) per §5.6: discover
  chats round-robin where `MEMORY_EMBEDDINGS_ENABLED`, gate on
  `MEMORY_REGENERATE_EMBEDDINGS`, resolve `EMBEDDING_MODEL`, call
  `deleteObsoleteMemoryEmbeddings` → `getMemoriesWithoutEmbeddings` →
  re-embed each via `embedAndSaveMemory`. Independent of the refinement
  body (Phase 4); shares the tick, not the lock.
- `internal/bot/models/ensured_message.py` — retire the `userSummary` path
  per §9.3 (Phase 4b removed `applyUserMetadata` + the `userSummary` field +
  the `formatForLLM` key entirely, not just deprecated them).
- `tests/bot/common/handlers/test_base.py` and/or
  `tests/bot/common/handlers/test_llm_messages.py` — `_buildMemoriesBlock`
  for latest / relevant / disabled / empty; assert the block lands in the
  system message at each of the three sites (§14). Add regeneration tests
  (stale-model row is re-embedded; obsolete vec0 rows deleted; gates
  respected) — §14.

**Exit criteria:** with `MEMORY_INJECTION_ENABLED=true`, a chat turn's
system message contains the `<user-memories>` block; with it false, no
block; relevant-mode falls back to latest when embeddings are off; with
`MEMORY_EMBEDDINGS_ENABLED=true` + `MEMORY_REGENERATE_EMBEDDINGS=true`, a
stale-`embedding_model` memory is re-embedded on the next cron tick.

### Phase 4 — Prompt rewrite + docs

**Files:**

- `configs/00-defaults/bot-defaults.toml` — rewrite
  `memory-refine-system-prompt` and `memory-refine-user-prompt-template`
  defaults (§10.2(a), §11.3).
- `internal/bot/common/handlers/user_data.py` — `_runRefinement` body
  changes (§10.2): `useTools`, `extraData` augmentation, remove the
  rolling-bio write block (`:597-614`), extend the JSONL log fields
  (`:620-679`).
- `docs/` sync via the `update-project-docs` skill:
  - New ADR in `docs/llm/architecture.md` (User Memories v1; reference
    ADR-014/015).
  - `docs/llm/handlers.md` — note the new tools + injection helper.
  - `docs/llm/configuration.md` — document the four new settings
    (`MEMORY_INJECTION_ENABLED`, `MEMORY_RETRIEVAL_MODE`,
    `MEMORY_EMBEDDINGS_ENABLED`, `MEMORY_REGENERATE_EMBEDDINGS`) + the
    rewritten prompt defaults.
  - `docs/database-schema.md` + `docs/database-schema-llm.md` — confirm the
    Phase-1 table docs are complete; add the vec0 runtime table note.
  - New durable memory `docs/llm/memories/user-memories.md` capturing the
    unified system (this plan becomes provenance).

**Exit criteria:** whole-repo `make format lint && make test` green;
`code-reviewer` pass on the full diff; docs in sync.

### Phase 5 — Admin UI (extending `/memory_config`)

> AMENDMENT (user review, change #3): New phase. Independent of the LLM
> tools / injection / regeneration (Phases 1–4) and can ship after the core
> system works. Recommended as a separate phase rather than folded into
> Phase 3 because it is substantial UI work with its own test surface.

**Files:**

- `internal/bot/models/enums.py` (`:155-187`) — extend
  `ButtonUserDataConfigAction` with `TopicSelected`, `MemorySelected`,
  `DeleteMemory`, `NextPage`, `PrevPage`, `TagFilter`.
- `internal/bot/common/handlers/user_data.py`:
  - Repoint the `/memory_config` wizard (`memory_config_command`
    `:1357-1400`, dispatcher `_handleUserDataConfiguration` `:1216-1279`,
    callback router `callbackHandler` `:1281-1311`, step handlers
    `:785-1214`) at `self.db.userMemories` instead of the cache user-data
    methods.
  - New flow: chat picker → topic/type picker (`MemoryType` or "All") →
    paginated memory list (with optional freeform-tag filter) → per-memory
    view → delete.
  - Add pagination (offset-based prev/next inline buttons carrying
    `(offset, type, tag)` in the callback payload; mirror any existing
    bot pagination pattern if one exists — flag the chosen pattern in the
    PR).
  - Repoint `/get_my_data` (`:1317-1355`) at `user_memories` (JSON dump or
    readable `[type] content #tags` list).
- `tests/bot/common/handlers/test_user_data.py` — wizard step coverage:
  type-filter list, tag-filter list, pagination, per-memory view, delete;
  private-only enforced; only the calling user's own memories surfaced.

**Exit criteria:** a user can `/memory_config` → pick a chat → pick a
type → page through their memories → view one → delete it; the deleted
memory is gone from `user_memories` and absent from the next injection;
`/get_my_data` dumps the user's memories; all of this is private-only and
scoped to the caller's `userId`.

## 14. Testing strategy

> AGENTS.md testing rules: test files under `tests/` mirroring source
> (`tests/internal/X/Y.py` → `tests/X/test_Y.py`); `asyncio_mode = "auto"`
> (write `async def test_…`, no decorator); reuse `tests/conftest.py`
> fixtures (`testDatabase`, `mockBot`, `mockConfigManager`,
> `resetLlmServiceSingleton` autouse); reset singletons
> (`_instance = None`) in fixtures.

### 14.1 Repository tests — `tests/database/repositories/test_user_memories.py`

Mirror `tests/database/repositories/test_chat_embeddings.py` (confirm path
during execution). Cover:

- `addMemory` → `getPermanentMemories` / `getLatestMemories` round-trip.
  `getPermanentMemories` returns BOTH cross-thread permanent
  (`thread_id IS NULL`) AND this-thread permanent (`thread_id = :threadId`)
  — assert a thread-scoped bio (§5.5) and a cross-thread fact both surface
  for the thread, and that the thread-scoped bio does NOT surface for a
  different thread.
- `updateMemory` partial update (`content` only, `tags` only, `type` only).
- `deleteMemory` + `deleteMemoriesByQuery`. `deleteMemoriesByQuery` MUST add
  `AND permanent = 0` (§8.4) — assert a permanent memory matching the query
  filter is NOT deleted, while a matching ephemeral memory IS.
- `saveMemoryEmbedding` writes the vec0 table (no BLOB — §5.1):
  `vec_user_memories_{dim}` appears after the first write (assert via
  `db.userMemories` introspection or a direct `listTables` call); the
  `user_memories` row's `embedding_model` / `embedding_dimensions` are set.
- `searchMemories` — two modes (merged method, replaces former
  `findSimilarMemories`, §6/§10):
  - **Semantic mode** (`queryEmbedding` provided): returns ranked results
    with `score = 1.0 - distance` populated on every row (assert
    `results[i]["score"]` is in `[0, 1]`, descending). **Skip with a
    `pytest.mark.skipif` when vec0 is unavailable in CI** (mirror
    `test_chat_search.py` — confirm the exact guard during execution).
  - **Filter-only mode** (`queryEmbedding=None`): returns rows matching
    `type`/`tags`/`permanent`/`thread_id` with `score = 0.0` on every row;
    works without vec0 (no skip).
- `getMemoriesWithoutEmbeddings` / `deleteObsoleteMemoryEmbeddings` (§5.6):
  a memory with `embedding_model=NULL` (never embedded) surfaces in
  `getMemoriesWithoutEmbeddings`; after `saveMemoryEmbedding(..., model="A")`,
  calling `getMemoriesWithoutEmbeddings(..., currentModel="B", ...)` resurfaces
  it; `deleteObsoleteMemoryEmbeddings` removes the stale vec0 rows.

### 14.2 Tool tests — extend `tests/bot/common/handlers/test_user_data.py`

Cover each tool with the dedup matrix. Mock `generateEmbeddings` on the
LLM-service mock (return a fixed deterministic vector per content string so
similarities are controllable):

- `add_memory`: `action == "added"` when no similar; `action == "duplicate"`
  when similarity ≥ 0.95; `action == "similar_exists"` when 0.85 < s < 0.95
  AND `isRefinement=True`; `action == "duplicate"` in the grey zone when
  `isRefinement` is unset (chat-time). Dedup reads `results[0]["score"]`
  from `searchMemories` (§8.3, §10 — no separate `findSimilarMemories`).
- `delete_memory`: by `memory_id` (deleted=1, missing→0); by `query`
  (deletes only hits with `score ≥ 0.85`; explicit by-id CAN delete a
  permanent memory — assert this, §8.4).
- `search_memories`: with `query` → returns ranked results with `score` set;
  returns `count == 0` when vec0 unsupported (mock
  `isVectorSearchSupported → False`). WITHOUT `query` (filter-only) →
  returns rows matching `type`/`tags` with `score == 0.0`, works without
  vec0.
- All three return `{"done": False, "error": ...}` (never raise) when the DB
  throws.

### 14.3 Injection tests — `tests/bot/common/handlers/test_base.py` and `test_llm_messages.py`

- `_buildMemoriesBlock`:
  - `MEMORY_INJECTION_ENABLED=false` → returns `None`.
  - No permanent AND no ephemeral memories → returns `None`.
  - No permanent but ephemeral present → returns a block with only the
    `Recent:` section (permanent-empty gap fix, §9.1).
  - `mode="latest"` → recent section populated from `getLatestMemories`.
  - `mode="relevant"` + `EMBEDDINGS_ENABLED=true` → calls `searchMemories`;
    falls back to latest when search returns `[]`.
  - `mode="relevant"` + `EMBEDDINGS_ENABLED=false` → latest (no embedding
    attempt).
- Integration: for each of the three sites, with injection enabled and a
  seeded permanent memory, assert `messages[0].content` contains the
  `<user-memories>` block; with injection disabled, assert it does not.

### 14.4 Migration test — `tests/database/test_migration_020_user_memories.py`

- Seed `user_data` rows + `chat_users.metadata` rolling-bio blobs; run
  `migration_020.up()`; assert the resulting `user_memories` rows:
  - `user_data` → permanent `type=fact`, `source=migration`, correct
    `content` shape, `tags=[]`, `thread_id=NULL` (cross-thread),
    `embedding_model=NULL`, `embedding_dimensions=NULL`.
  - rolling-bio → permanent `type=bio`, `thread_id=<original thread>` (NOT
    NULL — bio is thread-scoped per §5.5), `tags=["migrated_bio"]`, summary
    preserved in `content`, `embedding_model=NULL`.
- Idempotency: re-running `up()` (if the framework allows) must not double
  the rows; otherwise assert the framework refuses a second run.
- `down()`: `user_memories` dropped; `user_data` intact. (No
  `user_memory_embeddings` table to drop — dropped per §5.1.)

## 15. Risks & open questions

- **Embedding model drift.** ~~Future work~~ **Now handled in v1** (Goal #6,
  §5.6). When a chat's `EMBEDDING_MODEL` changes, stale `user_memories` rows
  (whose `embedding_model` / `embedding_dimensions` no longer match) are
  re-embedded by the regeneration section of `UserDataHandler._dtCronJob`,
  gated by `MEMORY_EMBEDDINGS_ENABLED` + `MEMORY_REGENERATE_EMBEDDINGS`
  (§11.5). The model/dimensions live on `user_memories` itself (no BLOB
  table), so stale detection is a single-table query
  (`getMemoriesWithoutEmbeddings`). Residual risk: if both regeneration
  settings are left off on a chat that switched models, relevant-mode
  `searchMemories` returns `[]` (the dim-specific vec0 table is absent for
  the new model) and `_buildMemoriesBlock` falls back to latest-mode
  silently — degraded but not broken.

- **vec0 partition-key portability.** The partition-key syntax is
  sqlite-vec-specific; see the TODO at
  `internal/database/repositories/chat_embeddings.py:201`. v1 is SQLite-only.
  PG/MySQL must not be enabled for memories until the provider abstraction
  gains portable vec0 DDL — track as a separate task.

- **Grey-zone dedup reliance on LLM judgement.** The 0.85–0.95 band
  (§8.3/D5) trusts the refinement LLM to make sensible delete+readd
  decisions. Mitigation: the extended JSONL log (§10.2(d)) exposes
  `addCount` / `deleteCount` / `searchCount` for post-hoc review.
  (`similarExistsCount` was dropped — see §10.2(d).)

- **Backfill cost.** Both backfills (§5.5) are one-shot Python loops. For
  chats with large `user_data` tables or many rolling-bio blobs this is a
  one-time migration cost. Acceptable; runs once. If a deployment has
  unusually large volume, run `up()` inside a transaction per chat batch.

- **Concurrency.** Multiple `add_memory` calls inside one refinement run
  are serialised by the global `_refineLock` (unchanged from §3.2).
  Chat-time `add_memory` is per-message, so there is no contention between
  refinement and chat. Two users in the same chat calling `add_memory`
  concurrently each get distinct ULIDs; the dedup search is read-only and
  the INSERT has a composite PK, so the worst case is two near-duplicate
  inserts that the next refinement pass collapses via `similar_exists`.

- **Resolved: chat-time tool registration site.** Verified by
  `grep "registerTool" internal/bot/common/handlers/`: `LLMMessageHandler`
  (`llm_messages.py`) registers **zero** tools. Tool registration is global
  on the `LLMService` singleton (`service.py:164-199`, `_resolveTools` — one
  `toolsHandlers` registry; the per-call `useTools` dict selects which
  registered tools are offered, with `TOOLS_DEFAULT_DICT_KEY` as the
  fallback for unnamed tools). `SEARCH_MESSAGES` is registered by
  `ChatSearchHandler` (`chat_search.py:204`) yet is offered to the
  refinement LLM (explicit dict at `user_data.py:559-564`) and to the chat
  LLM (the `TOOLS_DEFAULT_DICT_KEY: True` wildcard at
  `llm_messages.py:278`). **Decision:** register
  `ADD_MEMORY`/`DELETE_MEMORY`/`SEARCH_MEMORIES` once in
  `UserDataHandler.__init__` (`:162-208` block); gate chat-time
  availability in `_sendLLMChatMessage`'s `useTools`
  (`llm_messages.py:274-288`) — `DELETE_MEMORY: False` always (D3);
  `ADD_MEMORY`/`SEARCH_MEMORIES` on `MEMORY_INJECTION_ENABLED`. See §8.3
  for the full reasoning.

- **Resolved: JSONL log tool-count source.** `ModelRunResult`
  (`lib/ai/models.py:838-946`) exposes `toolUsageHistory`
  (full `Sequence[ModelMessage]`) and `toolCalls` (final-turn
  `List[LLMToolCall]`). Per-tool counts are derived from
  `toolUsageHistory` by counting `LLMToolCall.name` across assistant
  messages. `similarExistsCount` is dropped (it is a tool *return value*,
  not a call — recovery requires parsing tool-result payloads). See §10.2(d).

## 16. References

### Codebase anchors (verified at planning time)

- Migration template: `internal/database/migrations/versions/migration_017_message_embeddings.py:26-91`.
- Lazy vec0 creation: `internal/database/repositories/chat_embeddings.py:166-263` (esp. `:199-221`).
- Native vector search dispatcher: `internal/database/repositories/chat_search.py:638-823` (cosine `1.0 - distance` at `:785`).
- Provider vector API: `internal/database/providers/base.py:390` (`upsert`), `:493` (`isVectorSearchSupported`), `:505-516` (`vectorSearch`), `:558` (`listTables`), `:578-582` (`createVectorTable`); types at `:135` (`VectorDistanceMetric`), `:148` (`VectorColumnType`), `:169` (`VectorColumnDef`).
- Embedding helper precedent: `internal/bot/common/embedding_utils.py:32-124`.
- Embedding generation: `lib/ai/abstract.py:492` (`generateEmbeddings`, single-string).
- Existing tools being retired: `internal/bot/constants.py:60-62` (`ADD_USER_DATA`/`DELETE_USER_DATA`); handlers `internal/bot/common/handlers/user_data.py:214-287`.
- Refinement LLM call: `internal/bot/common/handlers/user_data.py:549-566`; persist block `:597-614`; synthetic message `:702-727`; JSONL log `:620-679`.
- Chat-settings 4-site: enum `internal/bot/models/chat_settings.py:281-452`; info dict `:~615`; defaults `configs/00-defaults/bot-defaults.toml:158+`; value wrapper `:484-592`. Simplest end-to-end example `EMBEDDINGS_ENABLED` (enum `:435-436`, info `:1107-1112`, toml `:128`).
- Memory-refinement settings: enum `chat_settings.py:309-318`; info `:884-920`; defaults `bot-defaults.toml:158+`.
- Injection sites: `internal/bot/common/handlers/base.py:701-708` (`getThreadByMessageForLLM`); `internal/bot/common/handlers/llm_messages.py:688-695` (`handleMention`); `internal/bot/common/handlers/llm_messages.py:838-847` (`handleRandomMessage`).
- Rolling-bio read path: `internal/bot/models/ensured_message.py:917-948` (`applyUserMetadata`); serialisation `:1170` (`formatForLLM`, key `userSummary`).
- DB repo registry: `internal/database/database.py:108-126` (`__slots__`), `:137-175` (type hints), `:205-217` (`__init__`).
- Tool-registration primitives: `lib/ai/models.py:151-172` (`LLMParameterType`), `:175-216` (`LLMFunctionParameter`); `ToolName`/`TOOLS_DEFAULT_DICT_KEY` at `internal/bot/constants.py:24-76`.
- Config: `configs/00-defaults/user-memory.toml` (thresholds + JSONL log); `configs/00-defaults/bot-defaults.toml:128, 131, 158, 173-174` (embeddings-enabled, embedding-model, memory-refinement-enabled, memory-refine-model/fallback defaults); `:350, 363` (memory-refine system/user-prompt defaults — rewritten per §11.3); `:207` (chat-prompt-suffix documenting `userSummary`).
- Universal row converter: `dbUtils.sqlToTypedDict(data, typedDictClass)` at `internal/database/utils.py:319-374` (import as `from internal.database import utils as dbUtils`, seen at `chat_embeddings.py:32`). Handles snake_case column → TypedDict key mapping, int→bool, JSON TEXT→list, ISO str→datetime. `convertToSQLite` (`utils.py`) is the Python→SQL direction; there is no `convertFromSQLite` (the read direction is `sqlToTypedDict`).
- Regeneration precedent: `ChatSearchHandler._dtCronJob` at `internal/bot/common/handlers/chat_search.py:284-445` (single path for initial backfill + model-drift regeneration); `deleteObsoleteModelEmbeddings` at `internal/database/repositories/chat_embeddings.py:337-464`; stale-detection `NOT EXISTS` subquery at `:516-532`. Constants `BACKFILL_DEFAULT_BATCH_SIZE = 50` (`:69`), `BACKFILL_INTER_MESSAGE_DELAY_SECS = 0.1` (`:77`).
- Admin UI precedent: `/memory_config` command `internal/bot/common/handlers/user_data.py:1357-1400`; wizard dispatcher `:1216-1279`; callback router `:1281-1311`; step handlers `:785-1214`; `ButtonUserDataConfigAction` enum `internal/bot/models/enums.py:155-187`; `/get_my_data` `:1317-1355`.
- TypedDict key convention: `ChatMessageDict` / `ChatUserDict` / `MessageEmbeddingDict` at `internal/database/models.py:108-212` use snake_case keys matching DB columns; `ChatMessageDict.score` at `:157-160` is the exact mirror for `UserMemoryDict.score`.

### Related docs

- [`docs/plans/memory-refine-plan-v1.md`](memory-refine-plan-v1.md) — predecessor (rolling bio), IMPLEMENTED.
- [`docs/llm/architecture.md`](../llm/architecture.md) — ADR-014 (memory refinement), ADR-015 (chat-history semantic search).
- [`docs/llm/memories/user-memory-refinement.md`](../llm/memories/user-memory-refinement.md) — durable notes for the system being replaced.
- [`docs/sql-portability-guide.md`](../sql-portability-guide.md) — cross-RDBMS SQL rules.
- [`docs/llm/index.md`](../llm/index.md) §3 — Gromozeka gotchas (`MessageId`, `DEFAULT_THREAD_ID = 0`, `getChatSettings` tuple returns, singleton `getInstance()`).

### Quoted AGENTS.md rules this plan depends on

- "camelCase for variables, args, fields, functions, methods. PascalCase for classes. UPPER_CASE for constants." — **applies to Python identifiers only; TypedDict string keys that map to DB columns are snake_case** (repo convention, see `ChatMessageDict` etc.). Repository METHOD params stay camelCase; only the dict keys mirror columns.
- "Docstrings required on every module/class/method/function/field, with Args: and Returns:."
- "Type hints required on all function/method params and returns; no `Any` type."
- "No pydantic. … Use raw dicts + hand-rolled type-hinted classes of TypedDict."
- "String enums: use `StrEnum` (from `enum`), not `Literal[...]`."
- "Primary keys: no `AUTOINCREMENT`. … Composite natural key … `PRIMARY KEY (chat_id, user_id, memory_id)`."
- "Timestamps: do not use `DEFAULT CURRENT_TIMESTAMP` in new schemas."
- "Parameter style: use `:named` placeholders consistently."
- "Application-generated UUID / ULID … Generate it in Python before insert; never delegate ID generation to the DB."
- "Run Python via `./venv/bin/python3` — not `python` / `python3`."
- "Regression tests on every bug fix." (Each phase adds tests for the behaviour it introduces.)
