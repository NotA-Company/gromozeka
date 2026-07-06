# User Memories v1

**Status:** DRAFT (planning)
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

### Non-code deliverable shape

The implementing agent will touch, at minimum:

- 1 migration (`internal/database/migrations/versions/migration_020_*.py`)
- 1 new model module (`MemoryType`) + 1 `TypedDict` (`UserMemoryDict`)
- 1 new repository (`internal/database/repositories/user_memories.py`)
- 1 new helper (`internal/bot/common/memory_embedding_utils.py`)
- 2 new `ToolName` entries + 3 tool handlers + retire 2 old ones
- 2 new chat settings (4 sites each — §11)
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
- **Vector regeneration on embedding-model drift.** If a chat's
  `EMBEDDING_MODEL` changes, existing `user_memory_embeddings` rows are stale.
  v1 relevant-mode silently returns `[]` and falls back to latest-mode. A
  regeneration worker is future work (mirrors the same open issue on
  `message_embeddings`).
- **PostgreSQL / MySQL vec0 portability.** The vec0 virtual-table DDL and
  partition-key syntax are sqlite-vec-specific (see the TODO at
  `internal/database/repositories/chat_embeddings.py:201`). v1 is SQLite-only;
  PG/MySQL porting is tracked in §15.
- **GUI / admin tooling for memories.** No new bot commands to list/delete
  memories interactively; `delete_memory` is LLM-only in v1.
- **Dropping the `user_data` table.** Kept for rollback. A future migration
  can drop it once confidence is high.
- **Numpy fallback for `searchMemories`.** v1 returns `[]` when vec0 is
  unavailable (chat-history search has a numpy fallback at
  `internal/database/repositories/chat_search.py:266-436`; we do not port it
  for memories in v1).

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
`description: str = "Add user_memories + user_memory_embeddings tables"`,
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

CREATE TABLE IF NOT EXISTS user_memory_embeddings (
    chat_id    INTEGER   NOT NULL,
    user_id    INTEGER   NOT NULL,
    memory_id  TEXT      NOT NULL,
    embedding  BLOB      NOT NULL,
    dimensions INTEGER   NOT NULL,
    model      TEXT      NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (chat_id, user_id, memory_id)
);
```

**`down()`:**

```sql
DROP TABLE IF EXISTS user_memory_embeddings;
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
`:227-256`): try `DELETE ... WHERE chat_id=:c AND user_id=:u AND memory_id=:m
AND model=:model`; on failure fall back to rowid-based delete; then
`INSERT INTO {table} (memory_id, chat_id, user_id, thread_id, permanent,
type, embedding) VALUES (...)`. Write failures are **logged at WARNING and
swallowed** — the authoritative row is in `user_memory_embeddings`.

`[DESIGN CHOICE]` — `model` is stored in the BLOB table but **not** as a vec0
partition key (unlike `message_embeddings`, which partitions on `model`).
Memory volume per chat is tiny relative to messages, so a single vec0 table
per dimension without a model partition is simpler and still correct; the
`model` is checked post-search by joining back to `user_memory_embeddings`.
If a profiler later shows cross-model contamination hurting results, add
`model` as a partition key + a vec0 `model` column.

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
class UserMemoryDict(TypedDict):
    """Row shape returned by UserMemoriesRepository read methods.

    Attributes:
        chatId: Chat the memory belongs to.
        userId: User the memory is about.
        threadId: Thread scope, or None for permanent (cross-thread) memories.
        memoryId: App-generated ULID; unique within (chatId, userId).
        type: MemoryType string value.
        content: Free-text memory body.
        tags: Decoded list of tag strings (stored as JSON TEXT in the row).
        permanent: True if the memory is always injected (§9).
        source: Provenance — refinement | chat | migration | user.
        createdAt: ISO-8601 creation timestamp.
        updatedAt: ISO-8601 last-update timestamp.
    """

    chatId: int
    userId: int
    threadId: Optional[int]
    memoryId: str
    type: str
    content: str
    tags: List[str]
    permanent: bool
    source: str
    createdAt: str
    updatedAt: str
```

Row-decoding helper (`_rowToDict(row) -> UserMemoryDict`) handles:
`tags` JSON-decode (`json.loads(row["tags"])`, default `[]`),
`permanent` int→bool (`bool(row["permanent"])`),
column-name snake_case→camelCase mapping (the DB row uses `snake_case`; the
dict uses the project's `camelCase` convention for field names).

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
        created_at=row.created_at, updated_at=row.updated_at
    )
```

- `permanent=1`, `type='fact'`, `source='migration'`, `tags=[]`,
  `thread_id=NULL`.
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
        memoryId = ULID()
        INSERT INTO user_memories (
            chat_id, user_id, thread_id=NULL,    # [DESIGN CHOICE] bio is permanent → cross-thread
            memory_id, type='bio', content=summary,
            tags='["migrated_bio"]', permanent=1, source='migration',
            created_at=now, updated_at=now
        )
```

`[DESIGN CHOICE]` — **bio is permanent and cross-thread (`thread_id=NULL`)**
because the rolling bio is a high-level user summary, not thread-specific
chatter. The alternative (one bio per thread) fragments the always-in block
and contradicts D1's "one source of truth". The tag `"migrated_bio"` marks
the row as migration-sourced for later curation.

> The rolling-bio JSON is **not** deleted from `chat_users.metadata` by the
> migration — the refinement rewrite (§10) stops writing it, and stale reads
> are masked by the `userSummary` deprecation (§9). A cleanup pass is future
> work.

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

All methods `async`. All SQL uses `:named` placeholders. All decode via
`_rowToDict`.

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
    """DELETE memories matching the scope + filters (used by delete_memory tool + cleanup)."""

async def getPermanentMemories(
    self, chatId: int, userId: int, *,
    limit: int = PERMANENT_INJECTION_CAP,
) -> List[UserMemoryDict]:
    """Return permanent (thread_id IS NULL) memories, newest-updated-first, capped."""

async def getLatestMemories(
    self, chatId: int, userId: int, threadId: int, *,
    limit: int = EPHEMERAL_RETRIEVAL_LIMIT,
) -> List[UserMemoryDict]:
    """Return newest-updated memories scoped to (chatId, userId, threadId), capped."""

async def searchMemories(
    self, chatId: int, userId: int, queryEmbedding: bytes, *,
    threadId: Optional[int] = None, permanent: Optional[bool] = None,
    type: Optional[str] = None, tags: Optional[List[str]] = None,
    limit: int = EPHEMERAL_RETRIEVAL_LIMIT,
    modelName: Optional[str] = None, dimensions: Optional[int] = None,
) -> List[UserMemoryDict]:
    """Native vec0 search over vec_user_memories_{dim}, JOIN back to user_memories.
    Returns [] when vector search is unsupported or the vec0 table is absent."""

async def findSimilarMemories(
    self, chatId: int, userId: int, queryEmbedding: bytes, *,
    threadId: Optional[int] = None, limit: int = 3,
    modelName: Optional[str] = None, dimensions: Optional[int] = None,
) -> List[Tuple[UserMemoryDict, float]]:
    """Top-N similar memories with similarity score (1.0 - cosine_distance).
    Drives the add_memory dedup state machine (§8)."""

async def saveMemoryEmbedding(
    self, chatId: int, userId: int, memoryId: str, *,
    embedding: List[float], model: str, dimensions: int,
) -> bool:
    """Persist BLOB to user_memory_embeddings + lazy-upsert vec_user_memories_{dim}.
    Never raises (mirrors ChatEmbeddingsRepository.saveMessageEmbedding)."""

async def deleteMemoryEmbedding(
    self, chatId: int, userId: int, memoryId: str,
) -> bool:
    """DELETE from user_memory_embeddings + best-effort DELETE from vec0. Never raises."""
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
AND thread_id IS NULL ORDER BY updated_at DESC` with
`provider.applyPagination(query, limit, offset=0)` (AGENTS.md: "never
append `LIMIT … OFFSET …` yourself"). The `thread_id IS NULL` predicate is
redundant under the invariant "permanent ⟹ thread_id IS NULL" but makes
the scope explicit and defends against a future non-NULL permanent row.

**searchMemories** — mirror `_nativeVectorSearch`
(`chat_search.py:638-823`). Two-step:

1. Build vec0 filter: always `chat_id = :chatId AND user_id = :userId`;
   append `AND permanent = :perm` / `AND type = :type` when those filters
   are set. (For permanent-scope search pass `thread_id IS NULL` via the
   post-filter, since vec0 `thread_id` is an INTEGER column that also holds
   NULLs — filter at the JOIN step, not in vec0.)
2. `vectorSearch(table=f"vec_user_memories_{dim}", vectorColumn="embedding",
   returnColumns=["memory_id"], queryVector=queryEmbeddingBytes, k=limit *
   MEMORY_SEARCH_TOPK_MULTIPLIER, filterClause=..., filterParams=...,
   distanceMetric=COSINE)`.
3. JOIN `vecResults` back to `user_memories` on `memory_id` (single
   `SELECT ... WHERE chat_id=:c AND user_id=:u AND memory_id IN (...)`),
   apply remaining post-filters (`tags` membership via Python set
   intersection — JSON-in-SQL is non-portable), convert
   `1.0 - distance` → similarity, re-rank desc, trim to `limit`.

**findSimilarMemories** — `searchMemories(..., limit=limit,
returnScore=True)` shape, but returns `(dict, score)` tuples. The dedup
caller in §8 only inspects `results[0]` score against the two thresholds.

**searchMemories guard:** if `not await
provider.isVectorSearchSupported()` or the vec0 table is absent (check via
`listTables`), return `[]`. Do **not** raise; the caller falls back to
`getLatestMemories` (§9).

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
and the migration backfill hooks (if a future worker re-embeds stale rows):

1. Resolve the model via LLMService.getLLMManager().getModel(modelName).
2. Generate the vector via model.generateEmbeddings(text).
3. Persist via db.userMemories.saveMemoryEmbedding(...).

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
    """Delete a memory's embedding (BLOB + best-effort vec0 row). Never raises.

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
     similar = await db.userMemories.findSimilarMemories(
         chatId, userId, embed, threadId=threadId, limit=1,
         modelName=modelName, dimensions=dimensions)
     if similar and similar[0][1] >= MEMORY_DEDUP_DUPLICATE_THRESHOLD:
         return {"done": True, "action": "duplicate", "existing": similar[0][0]}
     # Grey zone: behaviour depends on call-time context (see D5):
     isRefinement = extraData.get("isRefinement", False)   # set by _runRefinement
     if similar and similar[0][1] > MEMORY_DEDUP_SIMILAR_THRESHOLD:
         if isRefinement:
             return {"done": True, "action": "similar_exists", "existing": similar[0][0]}
         # chat-time: treat grey zone as duplicate to avoid mid-turn curation
         return {"done": True, "action": "duplicate", "existing": similar[0][0]}
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
     hits = await db.userMemories.findSimilarMemories(chatId, userId, embed, limit=5, ...)
     toDelete = [h for h, score in hits if score >= MEMORY_DEDUP_SIMILAR_THRESHOLD]
     n = 0
     for m in toDelete:
         if await db.userMemories.deleteMemory(chatId, userId, m["memoryId"]):
             await deleteMemoryEmbedding(chatId, userId, m["memoryId"], self.db)
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
    query: str,
    limit: int = 5,
    type: str,            # optional
    tags: Array[str],     # optional
    permanent: bool,      # optional — restrict to permanent only
) -> { done: bool, results: [...], count: int, error?: str }
```

**Handler logic** (`_llmToolSearchMemories`):

```
1. Resolve chatId/userId from extraData["ensuredMessage"].
2. embed = await model.generateEmbeddings(query)
3. results = await db.userMemories.searchMemories(
       chatId, userId, embed, threadId=ensuredMessage.threadId or DEFAULT_THREAD_ID,
       permanent=permanent, type=type, tags=tags, limit=limit, modelName=..., dimensions=...)
   # NOTE: searchMemories returns [] when vec0 unsupported — caller (LLM) sees an empty result.
4. return {"done": True, "results": results, "count": len(results)}
```

`[DESIGN CHOICE]` — `search_memories` searches the **caller's own** scope
only (`chatId, userId, threadId`). It does not search other users' memories
even in a group chat; this matches D1's per-(chat,user) scoping and avoids
leaking one user's memories to another. If a future "what does the group
know about X" feature is wanted, it gets a separate tool.

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
    chatId, userId, limit=PERMANENT_INJECTION_CAP)

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

### 9.3 Deprecate `EnsuredMessage.applyUserMetadata` `userSummary` path

`internal/bot/models/ensured_message.py:917-948` currently reads
`metadata.memoryRefinement[threadId].summary` into `self.userSummary`, which
`formatForLLM` (`:1170`) serialises into each message JSON under key
`userSummary`.

**v1 change:**

- **Stop populating `userSummary`** — the refinement rewrite (§10) no longer
  writes the rolling-bio blob, so this read returns nothing for fresh data.
- **Keep the method + the `userSummary` field** for backward-compat (a stale
  blob for a since-not-refined chat would otherwise throw). Add a
  `# DEPRECATED v1 user memories — kept for rollback; remove with the
  user_data table` comment on both.
- The chat-prompt-suffix docs the `userSummary` JSON field at
  `bot-defaults.toml:207`; leave that line (harmless when empty) and note
  the deprecation in the §13 doc-sync phase.
- `[DESIGN CHOICE]` — alternative is to repoint `applyUserMetadata` to load
  the permanent `type=bio` memory on the fly. Rejected for v1: it adds a DB
  round-trip per message and duplicates `_buildMemoriesBlock`'s permanent
  load. The unified block fully replaces `userSummary`.

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
  — tables + both backfills (§5.1, §5.5).
- `internal/bot/models/memory_type.py` (new) — `MemoryType` StrEnum (§5.3).
- `internal/database/repositories/user_memories.py` (new) —
  `UserMemoryDict` (§5.4), `UserMemoriesRepository` with all methods
  including the `vec_user_memories_{dim}` lazy creator + `vectorSearch`
  wiring (§6).
- `internal/bot/common/memory_embedding_utils.py` (new) —
  `embedAndSaveMemory` / `deleteMemoryEmbedding` (§7).
- `internal/database/database.py` — wire `db.userMemories` (4 edits, §6.3).
- `tests/database/repositories/test_user_memories.py` (new) — CRUD, latest,
  permanent, `searchMemories` (skip with a marker when vec0 unavailable in
  CI), `findSimilarMemories` (§14).

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

### Phase 3 — Retrieval + injection + chat settings

**Files:**

- `internal/bot/models/chat_settings.py` — add `MEMORY_INJECTION_ENABLED`
  and `MEMORY_RETRIEVAL_MODE` to the enum + `_chatSettingsInfo` (§11.1,
  §11.2).
- `configs/00-defaults/bot-defaults.toml` — add the two defaults.
- `internal/bot/common/handlers/base.py` — add `_buildMemoriesBlock` +
  `_injectMemoriesBlock`; call at site 1 (`:701-708`) (§9.1, §9.2).
- `internal/bot/common/handlers/llm_messages.py` — call at sites 2
  (`:688-695`) and 3 (`:838-847`); in `_sendLLMChatMessage`'s `useTools`
  block (`:274-288`), add the `MEMORY_INJECTION_ENABLED` gate for
  `ADD_MEMORY`/`SEARCH_MEMORIES` (on when true, off when false). The
  Phase-2 `DELETE_MEMORY: False` exclusion stays.
- `internal/bot/models/ensured_message.py` — deprecate the `userSummary`
  path (`:917-948`, `:1170`) per §9.3 (comment + stop populating; keep
  field).
- `tests/bot/common/handlers/test_base.py` and/or
  `tests/bot/common/handlers/test_llm_messages.py` — `_buildMemoriesBlock`
  for latest / relevant / disabled / empty; assert the block lands in the
  system message at each of the three sites (§14).

**Exit criteria:** with `MEMORY_INJECTION_ENABLED=true`, a chat turn's
system message contains the `<user-memories>` block; with it false, no
block; relevant-mode falls back to latest when embeddings are off.

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
  - `docs/llm/configuration.md` — document the two new settings + the
    rewritten prompt defaults.
  - `docs/database-schema.md` + `docs/database-schema-llm.md` — confirm the
    Phase-1 table docs are complete; add the vec0 runtime table note.
  - New durable memory `docs/llm/memories/user-memories.md` capturing the
    unified system (this plan becomes provenance).

**Exit criteria:** whole-repo `make format lint && make test` green;
`code-reviewer` pass on the full diff; docs in sync.

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
- `updateMemory` partial update (`content` only, `tags` only, `type` only).
- `deleteMemory` + `deleteMemoriesByQuery` (by `type`, by `olderThanDays`).
- `saveMemoryEmbedding` writes the BLOB row; the vec0 table
  `vec_user_memories_{dim}` appears after the first write (assert via
  `db.userMemories` introspection or a direct `listTables` call).
- `searchMemories` returns ranked results; **skip with a `pytest.mark.skipif`
  when vec0 is unavailable in CI** (mirror how `test_chat_search.py` handles
  it — confirm the exact guard during execution).
- `findSimilarMemories` returns `(dict, score)` tuples with similarity in
  `[0, 1]`.

### 14.2 Tool tests — extend `tests/bot/common/handlers/test_user_data.py`

Cover each tool with the dedup matrix. Mock `generateEmbeddings` on the
LLM-service mock (return a fixed deterministic vector per content string so
similarities are controllable):

- `add_memory`: `action == "added"` when no similar; `action == "duplicate"`
  when similarity ≥ 0.95; `action == "similar_exists"` when 0.85 < s < 0.95
  AND `isRefinement=True`; `action == "duplicate"` in the grey zone when
  `isRefinement` is unset (chat-time).
- `delete_memory`: by `memory_id` (deleted=1, missing→0); by `query`
  (deletes only hits ≥ 0.85).
- `search_memories`: returns ranked results; returns `count == 0` when vec0
  unsupported (mock `isVectorSearchSupported → False`).
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
    `content` shape, `tags=[]`.
  - rolling-bio → permanent `type=bio`, `thread_id=NULL`,
    `tags=["migrated_bio"]`, summary preserved in `content`.
- Idempotency: re-running `up()` (if the framework allows) must not double
  the rows; otherwise assert the framework refuses a second run.
- `down()`: both new tables dropped; `user_data` intact.

## 15. Risks & open questions

- **Embedding model drift.** If a chat's `EMBEDDING_MODEL` changes,
  `user_memory_embeddings` rows are stale (model/dimensions mismatch with
  the vec0 table for the new dimension). v1: `_buildMemoriesBlock`
  relevant-mode returns `[]` from `searchMemories` (the dim-specific vec0
  table is absent for the new model) and falls back to latest-mode
  silently. **Future work:** a regeneration worker mirroring the
  `REGENERATE_EMBEDDINGS` chat setting's message-embeddings path
  (`internal/bot/common/handlers/chat_search.py` backfill).

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

### Related docs

- [`docs/plans/memory-refine-plan-v1.md`](memory-refine-plan-v1.md) — predecessor (rolling bio), IMPLEMENTED.
- [`docs/llm/architecture.md`](../llm/architecture.md) — ADR-014 (memory refinement), ADR-015 (chat-history semantic search).
- [`docs/llm/memories/user-memory-refinement.md`](../llm/memories/user-memory-refinement.md) — durable notes for the system being replaced.
- [`docs/sql-portability-guide.md`](../sql-portability-guide.md) — cross-RDBMS SQL rules.
- [`docs/llm/index.md`](../llm/index.md) §3 — Gromozeka gotchas (`MessageId`, `DEFAULT_THREAD_ID = 0`, `getChatSettings` tuple returns, singleton `getInstance()`).

### Quoted AGENTS.md rules this plan depends on

- "camelCase for variables, args, fields, functions, methods. PascalCase for classes. UPPER_CASE for constants."
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
