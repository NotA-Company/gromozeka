# Chat History Search — Implementation Plan

> **Status:** Draft / Discussion  
> **Audience:** Developers & LLM agents  
> **Goal:** Add semantic chat history search, user listing, thread retrieval, and summarization via LLM tools + direct commands

---

## 1. Overview

Add a combined `ChatSearchHandler` that provides four LLM tools and two user commands:

| Interface | Type | Description |
|---|---|---|
| `/search <query>` | User command | Semantic search with optional filters |
| `/users` | User command | List chat users with activity info |
| `search_messages(query, limit, ...)` | LLM tool | Semantic search for the bot's autonomous use |
| `list_users(limit, last_active)` | LLM tool | List chat participants |
| `get_thread(message_id)` | LLM tool | Retrieve full thread by message ID |
| `get_summary(scope, ...)` | LLM tool | Summarise messages (reuses existing summarization) |

---

## 2. Embedding Support in `lib/ai/`

### 2.1 Why extend `lib/ai/` instead of creating `lib/embeddings/`

The existing `lib/ai/` already handles provider selection, model registry, fallback, and configuration. Adding embedding to `AbstractModel` reuses all of that machinery:

- The same providers (OpenAI, OpenRouter) already have embedding endpoints
- Model config in TOML can advertise embedding capability
- Fallback behavior works naturally: if primary model doesn't support embeddings, try the next
- No new configuration system needed

### 2.2 Changes to `lib/ai/abstract.py` — `AbstractModel`

Add to `AbstractModel.__init__()` (note: `extraConfig` is stored as
`self._config` by the existing `AbstractModel.__init__`):

```python
self.supportsEmbedding: bool = self._config.get("support_embeddings", False)
```

Add abstract method:

```python
async def _generateEmbeddings(self, text: str) -> list[float]:
    """Generate embedding vector for the given text.

    Args:
        text: Input text to embed.

    Returns:
        List of floats representing the embedding vector.

    Raises:
        NotImplementedError: If the model does not support embeddings.
    """
    raise NotImplementedError(f"Embeddings aren't supported by {self.modelId}, dood!")
```

Add public method that wraps `_generateEmbeddings` with retry + stats recording
(parallel structure to `generateText` / `generateImage`, but **no model fallback** —
embeddings from different models are incompatible (different dimensions, different
semantic spaces), so a fallback to another model would silently corrupt results):

```python
async def generateEmbeddings(
    self,
    text: str,
    *,
    attempts: int = 3,
) -> list[float]:
    """Generate embedding for the given text, with retry on transient failures.

    Unlike `generateText` / `generateImage`, this method does NOT support a
    fallback model. Embeddings from different models live in incompatible
    vector spaces (different dimensions, different semantics), so swapping to
    a different model mid-stream would silently corrupt downstream cosine
    similarity scores. If a chat needs a different embedding model, the
    caller must explicitly resolve it via the `EMBEDDING_MODEL` chat setting
    and re-embed.

    Args:
        text: Input text to embed.
        attempts: Max retry attempts on transient failures (default: 3).

    Returns:
        Embedding vector as list of floats.

    Raises:
        NotImplementedError: If the model does not support embeddings.
        RuntimeError: If all retry attempts fail.
    """
    # 1. Validate input
    # 2. Retry loop calling _generateEmbeddings(text) up to `attempts` times
    #    with exponential backoff on transient errors
    # 3. Record stats via self.statsStorage (mirroring generateImage pattern)
    # 4. Return the embedding on success; raise RuntimeError after final failure
    # 5. NEVER fall back to a different model — the caller picks the model
    #    via EMBEDDING_MODEL chat setting, not via this method
    pass  # Implementation detail
```

### 2.3 Changes to `lib/ai/models.py`

Add a `support_embeddings` entry to the model's `getInfo()` dict (the
capability summary returned to callers like the LLM tool registry),
mirroring the existing `support_text` / `support_tools` / `support_images`
pattern. The value comes from `self._config.get("support_embeddings", False)`
— same as the `supportsEmbedding` attribute on `AbstractModel` (§2.2) but
exposed in the dict the rest of the system reads. No changes to the model
configuration TypedDicts are required: the field flows through `extraConfig`
just like every other provider-specific knob.

### 2.4 Provider implementations

**OpenAI (`BasicOpenAIModel`)**: Override `_generateEmbeddings` to call the OpenAI embeddings API endpoint via the `openai.AsyncOpenAI` SDK client (`self._client`). The existing `BasicOpenAIModel` already has this client — just needs a new method.

```python
# In BasicOpenAIModel (subclass of AbstractModel, has self._client: openai.AsyncOpenAI)
async def _generateEmbeddings(self, text: str) -> list[float]:
    response = await self._client.embeddings.create(
        model=self._getModelId(),  # e.g. "text-embedding-3-small"
        input=text,
        dimensions=self._config.get("embedding_dimensions", 256),
    )
    return response.data[0].embedding
```

**FastEmbed Provider**: New provider type `fastembed` in `lib/ai/providers/fastembed_provider.py`. Wraps `fastembed` (ONNX-based, no PyTorch dependency).

A single `FastembedProvider` instance hosts **multiple** embedding models
via the same `addModel()` pattern used by every other provider in `lib/ai/`
(e.g. `BasicOpenAIProvider.addModel()` registers any number of OpenAI models
under one provider). From outside `lib/ai`, the local models are
indistinguishable from any other embedding model — callers resolve them via
`LLMManager.getModel("local-minilm")` and invoke `model.generateEmbeddings(text)`.

```python
class FastembedProvider(AbstractLLMProvider):
    """Provider for local embedding models using fastembed.

    Hosts multiple local embedding models (e.g. all-MiniLM-L6-v2,
    all-mpnet-base-v2) under a single provider instance. Each model is
    registered via the standard `addModel()` call, mirroring how
    `BasicOpenAIProvider` hosts multiple OpenAI models.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        # Optional dependency — guarded by try/except ImportError
        # `fastembed` is heavy (downloads ONNX models at first use), so it
        # stays an optional dep. Provider init only validates the config
        # and the import; actual model loading happens lazily in addModel().
        # ...


class FastembedModel(AbstractModel):
    """Local embedding model wrapping a single fastembed TextEmbedding instance.

    Model-specific configuration is read from `extraConfig` (stored as
    `self._config` by `AbstractModel.__init__`), the same way OpenAI-style
    models consume options like `embedding_dimensions` or `support_tools`.
    Anything not consumed by AbstractModel flows through to the underlying
    fastembed call.
    """

    def __init__(
        self,
        provider: "FastembedProvider",
        modelId: str,
        *,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            provider,
            modelId,
            modelVersion=modelVersion,  # fastembed models are versioned by their id
            temperature=temperature,    # embeddings are deterministic; caller passes 0.0
            contextSize=contextSize,    # N/A for embeddings; caller passes 0
            statsStorage=statsStorage,
            extraConfig=extraConfig,
        )
        self._provider = provider

        # Dimensions: prefer explicit config, fall back to fastembed metadata
        configuredDims = (extraConfig or {}).get("embedding_dimensions")
        if configuredDims is not None:
            self._dimensions: int = int(configuredDims)
        else:
            # Auto-detect from fastembed: TextEmbedding returns a list of
            # SupportingDoc objects whose .dimensions field reports the
            # model's native output size. We probe once at init time.
            self._dimensions = self._provider.detectDimensions(modelId)

        # Any remaining keys in extraConfig are passed through to fastembed
        # (e.g. cache_dir, threads, max_length). AbstractModel already
        # consumes the keys it knows about (support_text, support_embeddings,
        # etc.), so anything left is a fastembed kwarg.
        self._fastembedKwargs: Dict[str, Any] = {
            k: v
            for k, v in (extraConfig or {}).items()
            if k not in {"support_text", "support_embeddings", "embedding_dimensions"}
        }

    @property
    def embeddingDimensions(self) -> int:
        """Output dimensionality of this model (e.g. 384, 768)."""
        return self._dimensions

    async def _generateEmbeddings(self, text: str) -> list[float]:
        """Generate an embedding for `text` using the local fastembed model.

        Args:
            text: Input text to embed.

        Returns:
            Float vector of length `self._dimensions`.
        """
        # fastembed exposes both sync and async APIs; use async to keep the
        # bot's event loop unblocked.
        result = await self._provider.embedOne(
            modelId=self.modelId,
            text=text,
            **self._fastembedKwargs,
        )
        # result is a numpy float32 array; convert to plain list[float] for
        # cross-platform / cross-provider uniformity.
        return result.tolist()
```

**Why a single provider, multiple models:**

- Mirrors `BasicOpenAIProvider` (one provider, many `model_id` values).
- Keeps the fastembed runtime (which is process-global and ~50MB) loaded
  once, not once per model.
- The TOML config remains flat: one `[llm.providers.*]` block, many
  `[llm.models.*]` blocks under it. No per-provider `model =` shortcut —
  the provider block is purely structural; every model is registered
  individually under `[llm.models]`.

### 2.5 Changes to `lib/ai/manager.py`

- Add `"fastembed"` to `providerTypes` dict so the manager instantiates
  `FastembedProvider` for providers of that type.
- **No** `getModelsSupportingEmbedding()` helper. The chat setting
  `EMBEDDING_MODEL` (see §2.7) stores a specific model name, and the
  consumer just calls `LLMManager.getModel(chatSettingValue)` directly —
  there is no need for a registry-wide enumeration. If `getModel()` raises
  (e.g. the stored model was removed from the TOML config), the consumer
  falls back to the `[search-history.embeddings].model` default and
  surfaces a one-time warning.

### 2.6 Config — TOML additions

In `configs/00-defaults/`, models can advertise embedding support. The
`support_text = false` flag is mandatory for embedding models so they are
never accidentally selected for text generation:

```toml
[llm.models.text-embedding-3-small]
provider = "yc-provider"   # or whatever OpenAI-compatible provider
model_id = "text-embedding-3-small"
enabled = true
support_text = false        # embedding-only — never picked for chat
support_embeddings = true
embedding_dimensions = 256   # OpenAI supports reduced dimensions
```

For local embeddings, one provider hosts many models — there is **no**
per-provider `model =` shortcut:

```toml
[llm.providers.fastembed]
type = "fastembed"
# No per-provider model default — models are registered individually below
```

```toml
[llm.models.local-minilm]
provider = "fastembed"
model_id = "all-MiniLM-L6-v2"
enabled = true
support_text = false
support_embeddings = true
embedding_dimensions = 384

[llm.models.local-mpnet]
provider = "fastembed"
model_id = "all-mpnet-base-v2"
enabled = true
support_text = false
support_embeddings = true
embedding_dimensions = 768
```

The provider is purely structural; every model is registered individually
under `[llm.models]`. To add another local embedding model, append another
`[llm.models.<name>]` block pointing at the same provider — no provider
changes required.

### 2.7 Chat settings for embeddings

Four new entries in `ChatSettingsKey` (`internal/bot/models/chat_settings.py`)
plus matching rows in the `_chatSettingsInfo` TypedDict. They mirror the
pattern used by `IMAGE_GENERATION_MODEL` / `IMAGE_GENERATION_FALLBACK_MODEL`:
a model name resolved against the LLM registry, an enable/disable flag, a
regeneration trigger, and a safety cap to keep the in-memory embedding
matrix bounded on huge chats.

| Setting | Type | Default (`[bot.defaults]`) | Page | Purpose |
|---|---|---|---|---|
| `EMBEDDING_MODEL` | string (model name) | *(omitted — empty string)* | `ChatSettingsPage.BOT_OWNER` | Which model from `[llm.models]` to use for embedding generation and query embedding. Empty value means "use the server-wide default". Uses `ChatSettingsType.STRING` (not `MODEL`) because the `MODEL` type's UI picker only shows text-generation models; embedding models need `support_embeddings=true` filtering which the existing picker doesn't support. A future `EMBEDDING_MODEL` ChatSettingsType can be added to enable a proper picker. |
| `EMBEDDINGS_ENABLED` | bool | `embeddings-enabled = true` | `ChatSettingsPage.BOT_OWNER` | Per-chat kill-switch for embedding generation on save and for search commands/tools. |
| `REGENERATE_EMBEDDINGS` | bool | `regenerate-embeddings = false` | `ChatSettingsPage.BOT_OWNER` | When set to `true`, the embedding manager regenerates embeddings for messages that have no embedding yet OR an embedding from a different `model` (per the `message_embeddings.model` column). After the backfill completes, the handler resets this flag to `false`. |
| `MAX_MESSAGES_FOR_SEMANTIC_SEARCH` | int | `max-messages-for-semantic-search = 100000` | `ChatSettingsPage.BOT_OWNER_SYSTEM` | Hard cap on how many recent messages to load into the embedding cache for semantic search. Prevents OOM on chats with millions of historical messages. |

> **The `_chatSettingsInfo` TypedDict has no `default` field.** The rows above
> mention defaults for documentation only — the canonical default lives in
> the TOML config described in **Default values and gating** below. The
> TypedDict entries are pure metadata (`type`, `short`, `long`, `page`).

**Why four settings and not one:**

- `EMBEDDING_MODEL` is the per-chat override of the global default. Different
  chats can pick different embedding models (e.g. one paid chat uses
  OpenAI, another uses a local model) without changing server-wide config.
- `EMBEDDINGS_ENABLED` lets a chat admin pause embedding generation (e.g.
  during a reindex or to reduce costs) without unregistering the handler.
- `REGENERATE_EMBEDDINGS` is a one-shot trigger, not a steady-state setting:
  the `EMBEDDINGS_ENABLED` flag stays as it was, but the next pass of the
  embedding worker checks this flag and re-embeds stale or missing rows.
- `MAX_MESSAGES_FOR_SEMANTIC_SEARCH` is a memory-safety cap. Loading every
  embedding ever produced for a megachat (millions of rows) would blow
  process memory. The cap limits the embedding-load query
  (`ORDER BY c.date DESC LIMIT :maxMessages`) so the cache holds at most
  the N most recent messages. Older messages are still searchable by
  non-semantic filters (user, category, date range) — they just don't
  participate in cosine ranking.

**Where they're consumed:**

| Setting | Read by | Used for |
|---|---|---|
| `EMBEDDING_MODEL` | `MessagePreprocessorHandler` (on save), `ChatSearchHandler` (on query) | Resolves the model via `LLMManager.getModel(value)`; if it raises or the value is empty, falls back to `[search-history.embeddings].model` (server-wide) and logs a one-time warning. |
| `EMBEDDINGS_ENABLED` | `MessagePreprocessorHandler` (gates the background-task hook), `ChatSearchHandler` (refuses commands/tools when `false`, replies with a short notice) | Avoids pointless work in chats that have opted out. |
| `REGENERATE_EMBEDDINGS` | The embedding backfill worker (a periodic task that walks messages in the chat) | Triggers one full re-embedding pass, then resets itself to `false`. |
| `MAX_MESSAGES_FOR_SEMANTIC_SEARCH` | `ChatMessagesRepository.searchChatMessages` (the embedding-load query) | Adds `ORDER BY c.date DESC LIMIT :maxMessages` so the cache never grows past N messages. Bot-owner only — set on `ChatSettingsPage.BOT_OWNER`. |

**Default values and gating:**

Chat-setting defaults live under `[bot.defaults]` in
`configs/00-defaults/bot-defaults.toml`, using **kebab-case** keys that
match the `ChatSettingsKey` enum members. The runtime overlay order is:

1. Every key pre-populated to an empty `ChatSettingsValue("")` (cache key
   `"None"`).
2. Overlay `[bot.defaults]` from TOML.
3. Overlay per-chat-type defaults `[bot.{type}-defaults]` (cache keys
   `"private"` / `"group"` / `"channel"`).
4. Overlay per-tier defaults `[bot.tier-defaults.{tier}]` (cache keys
   `"tier-{tier}"`).

The new settings appear in `bot-defaults.toml` as:

```toml
[bot.defaults]
# ... existing keys ...

# Embedding / semantic search (see docs/chat-history-search-plan.md §2.7)
embeddings-enabled = true
regenerate-embeddings = false
max-messages-for-semantic-search = 100000   # bot-owner only at the UI layer (see _chatSettingsInfo.page)

# EMBEDDING_MODEL is intentionally NOT set here. An empty value causes the
# consumer to fall through to the server-wide default below.
```

The server-wide **fallback** for the embedding model is
`[search-history.embeddings].model` in
`configs/00-defaults/search-history.toml`:

```toml
[search-history.embeddings]
model = "text-embedding-3-small"   # resolved against [llm.models]
```

This is **not** a chat setting default — it is the ultimate fallback when
`EMBEDDING_MODEL` is empty or the named model can't be resolved by
`LLMManager.getModel()`. The codebase itself has a final hard-coded
fallback (`text-embedding-3-small`) for cases where even the server-wide
config is missing the key.

Even when `EMBEDDINGS_ENABLED` defaults to `true`, the handler is only
**registered** (in `HandlersManager`) if `[search-history].enabled = true`.
A disabled feature should never start any background work, so the per-chat
flag is a secondary gate, not a primary one. (This matches how
`USE_TOOLS` interacts with `[tools].enabled` — both layers of gating
exist for distinct reasons.)

**Interaction with `message_embeddings.model` column:**

When `REGENERATE_EMBEDDINGS` is set, the worker re-embeds any message
where `message_embeddings.model` differs from the chat's currently
configured `EMBEDDING_MODEL`. Embeddings from different models are
incompatible (see §2.2 — no fallback), so a chat that switches models
must trigger a re-embed. The migration stores `model` and `dimensions`
per row precisely so the worker can detect this case without joining
against `[llm.models]` at SQL time.

---

## 3. Database — Migration 017

### 3.1 New table: `message_embeddings`

```sql
CREATE TABLE IF NOT EXISTS message_embeddings (
    chat_id INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    embedding BLOB NOT NULL,              -- float32 array serialized as raw bytes
    dimensions INTEGER NOT NULL,          -- e.g. 256, 384, 1536
    model TEXT NOT NULL,                  -- e.g. "text-embedding-3-small", "all-MiniLM-L6-v2"
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,        -- set in application code on insert and re-embed
    PRIMARY KEY (chat_id, message_id)
)
```

Composite PK matches `chat_messages` PK — one embedding per message.
Storing `model` + `dimensions` allows:
- Detecting stale embeddings (if model changes)
- Supporting multiple embedding models simultaneously
- Correctly deserializing the BLOB

### 3.2 Table: no changes to existing tables

`chat_messages`, `chat_users` — unchanged. We only add the embeddings table.

---

## 4. Repository Extensions — `ChatMessagesRepository`

### 4.1 `searchChatMessages()`

```python
async def searchChatMessages(
    self,
    chatId: int,
    queryEmbedding: Optional[list[float]] = None,
    *,
    limit: int = 10,
    topK: int = 100,
    userFilter: Optional[int] = None,
    categoryFilter: Optional[list[MessageCategory]] = None,
    maxAgeDays: Optional[int] = None,
    rootMessageId: Optional[MessageId] = None,
    dataSource: Optional[str] = None,
) -> list[SearchResultDict]:
    """Search chat messages, with optional semantic ranking.

    Two modes:
    - **Semantic mode** (default): `queryEmbedding` is provided. Embeddings
      for the chat are loaded (with optional pre-filters), cosine similarity
      is computed against `queryEmbedding`, and the top-K candidates are
      joined with message and user data.
    - **Filter-only mode**: `queryEmbedding` is `None`. No vector ranking
      happens — the SQL filters (`userFilter`, `categoryFilter`, `maxAgeDays`,
      `rootMessageId`) are applied directly and results are returned sorted
      by `date` descending. Useful for paginating through a thread, listing
      recent messages by a user, etc., when no semantic query is needed.

    The embedding cache (§4.1.1) is consulted in semantic mode only. In
    filter-only mode the cache is bypassed entirely; the filter is pushed
    down to SQL.

    Args:
        chatId: Chat to search in.
        queryEmbedding: Query vector from the embedding model. When `None`,
            the search runs in filter-only mode (no ranking, sorted by date).
        limit: Max results to return.
        topK: In semantic mode, how many candidates to consider before the
            final filter (pre-filtering at the cosine-similarity stage).
            Ignored in filter-only mode.
        userFilter: Optional user ID to narrow search.
        categoryFilter: Optional message category filter.
        maxAgeDays: Only consider messages newer than N days.
        rootMessageId: Optional thread root. When set, results are
            restricted to messages with `root_message_id == rootMessageId`
            (i.e. replies within the same thread).
        dataSource: Optional explicit data source.

    Returns:
        List of SearchResultDict with message content, user info, and score.
        In filter-only mode the `score` field is `0.0` (no ranking applied).
    """
```

**Implementation sketch — semantic mode (`queryEmbedding` provided):**

1. Resolve the cache key for this chat (see §4.1.1). The cache is keyed
   by `chatId` alone; the model is stored in the cache value for
   staleness detection.
2. If the cache has an entry for this `chatId` and the entry's
   `modelName` matches the current embedding model, reuse the in-memory
   `embeddingList` / `messageIds` and skip the DB read.
3. Otherwise, query `message_embeddings` for this `chatId` (filtered by
   `model = currentModelName` so the cache stays model-pure), deserialize
   the BLOBs into `list[list[float]]`, and populate the cache. The
   previous entry (if any) is replaced — a model change effectively
   invalidates the old cache for this chat.
4. Apply SQL-side pre-filters (`userFilter`, `categoryFilter`,
   `maxAgeDays`, `rootMessageId`) when reading from the DB. When the cache
   is used, the same filters are applied in Python over the cached
   `messageIds` (the filters resolve to a small set of IDs and a Python
   scan is fine for a few hundred IDs).
5. Compute cosine similarity using `numpy`:

```python
import numpy as np

queryVec = np.array(queryEmbedding, dtype=np.float32)
embeddingMatrix = np.frombuffer(blob, dtype=np.float32).reshape(-1, dimensions)
similarities = embeddingMatrix @ queryVec  # dot product (cosine sim for unit vectors)
topIndices = np.argpartition(-similarities, topK)[:topK]
```

6. Fetch full message data for the top-K message IDs from `chat_messages` + `chat_users`
7. Return sorted by similarity descending

**Implementation sketch — filter-only mode (`queryEmbedding is None`):**

1. Skip the cache entirely.
2. Run a single SQL query against `chat_messages` joined to `chat_users`
   with the requested filters and `ORDER BY date DESC LIMIT :limit`.
3. Return `SearchResultDict` rows with `score = 0.0`.

**Performance note:** With 88k messages × 256-dim embeddings, loading all
embeddings for a single chat takes ~90MB of memory and the dot product
takes ~20ms on modern hardware. The cache (§4.1.1) eliminates the DB read
on subsequent searches of the same chat. For larger scale, add an
optional approximate index (annoy/hnswlib) later.

#### 4.1.1 Embedding Cache

To avoid re-reading `message_embeddings` from SQLite on every search, the
repository keeps a per-`chatId` cache of the in-memory embedding matrix
and corresponding message IDs. The cache uses
[`lib/utils/ttl_dict.py`](lib/utils/ttl_dict.py) (`TTLDict` — a thread-safe
dict with per-entry TTL, automatic GC, and a full dict API) and lives as
an instance attribute on `ChatMessagesRepository`, initialised in
`__init__`. **Implementation note:** `ChatMessagesRepository` currently
declares `__slots__ = ()` — the new `_embeddingCache` and
`_maxCachedChats` attributes must be added to `__slots__` for this to
work without `AttributeError`.

**Why `chatId` alone, not `(chatId, modelName)`:** any chat has at most
one embedding model active at a time (the value of the `EMBEDDING_MODEL`
chat setting, falling back to the server-wide default when unset — see
§2.7). It is therefore impossible for two cache entries to coexist for
the same chat under different models. The model is recorded in the cache
**value** so the consumer can detect a mid-flight `EMBEDDING_MODEL`
change: a cache hit whose stored model no longer matches the chat's
current model is treated as a miss and the entry is rebuilt from the
DB (filtered by the new model). Embeddings from different models are
incompatible (different dimensions, different semantic spaces — see
§2.2), so a chat that switches models must never see a hit from the
previous model's cache.

**Cache shape:**

| Field | Type | Notes |
|---|---|---|
| Key | `int` | `chatId` |
| Value | `tuple[list[list[float]], list[MessageId], float, str]` | `(embeddingList, messageIds, cachedAt, modelName)` — the `embeddingList[i]` corresponds to `messageIds[i]`. `cachedAt` is `time.time()` for diagnostics; `modelName` is the model the embeddings were produced with, stored alongside so a post-cache `EMBEDDING_MODEL` change can be detected without a separate lookup. |
| TTL | seconds | Configurable via `[search-history.embeddings].cache-ttl-seconds` (default 300). Read at cache creation time. Stale entries auto-evicted by `TTLDict.gc()`. |
| Max size | chats | Not enforced by `TTLDict` (unbounded). After every successful `set()`, check `len(cache) > max_chats` (default 20, configurable via `[search-history.embeddings].cache-max-chats`) and evict the oldest entry by `cachedAt`. |

**Read path — `searchChatMessages`:**

```python
async def searchChatMessages(self, chatId, queryEmbedding=None, ...):
    if queryEmbedding is None:
        # Filter-only mode bypasses the cache entirely.
        return await self._filterOnlySearch(chatId, ...)

    modelName = self._currentEmbeddingModelForChat(chatId)
    entry = self._embeddingCache.get(chatId)
    if entry is not None and entry[3] == modelName:
        # Cache hit and model still matches — reuse the in-memory matrix.
        embeddingList, messageIds, cachedAt, _ = entry
    else:
        # Either no entry (cold start), or a model change since the entry
        # was cached. Replace the entry with embeddings produced by the
        # current model.
        embeddingList, messageIds = await self._loadEmbeddingsFromDb(
            chatId, modelName
        )
        self._embeddingCache[chatId] = (
            embeddingList, messageIds, time.time(), modelName
        )
        self._evictIfOverCapacity()
    # ... continue with cosine similarity over embeddingList ...
```

(The `entry[3] == modelName` check is a safety net: if a chat changed its
`EMBEDDING_MODEL` setting after the entry was cached, the cache hit is
treated as a miss and the entry is replaced.)

**Write path — `saveMessageEmbedding`:**

```python
async def saveMessageEmbedding(self, chatId, messageId, embedding, model):
    # 1. Persist to DB (always)
    await self._upsertEmbeddingRow(chatId, messageId, embedding, model)

    # 2. Incremental cache update: if this chat is in the cache AND the
    #    cached model matches, append the new (embedding, messageId) so
    #    the next search sees it without a DB round-trip. If the cached
    #    model is different (the chat just switched EMBEDDING_MODEL),
    #    skip the append — the cache will be rebuilt from the DB on the
    #    next search, which will load embeddings for the new model.
    entry = self._embeddingCache.get(chatId)
    if entry is not None and entry[3] == model:
        embeddingList, messageIds, cachedAt, _ = entry
        embeddingList.append(embedding)
        messageIds.append(messageId)
        # No need to update cachedAt — the entry's TTL window doesn't reset
```

**Eviction policy:**

```python
def _evictIfOverCapacity(self) -> None:
    if len(self._embeddingCache) <= self._maxCachedChats:
        return
    # Find the entry with the smallest cachedAt
    oldestKey = min(
        self._embeddingCache.items(),
        key=lambda kv: kv[1][2],   # cachedAt is the third tuple element
    )[0]
    del self._embeddingCache[oldestKey]
```

**Config:**

```toml
[search-history.embeddings]
cache-ttl-seconds = 300    # default 5 min; set to 0 to disable caching
cache-max-chats = 20       # soft cap on the number of cached chats
```

When `cache-ttl-seconds = 0`, the cache is effectively disabled (entries
expire immediately on the next GC tick) — useful for tests and for
debugging embedding issues without a server restart.

### 4.2 `listChatUsers()`

> **Note:** the separate `listChatUsers` method shown below was later
> merged into `getChatUsers` (see §4.2a) — both methods now share one
> implementation. The signature below is preserved for historical
> reference.

```python
async def listChatUsers(
    self,
    chatId: int,
    *,
    limit: Optional[int] = None,
    minMessages: Optional[int] = None,
    lastActiveDays: Optional[int] = None,
    dataSource: Optional[str] = None,
) -> list[ChatUserDict]:
    """List users in a chat with activity info.

    Args:
        chatId: Chat to list users from.
        limit: Max users to return.
        minMessages: Only return users with at least N messages.
        lastActiveDays: Only return users active in the last N days.
        dataSource: Optional explicit data source.

    Returns:
        List of ChatUserDict with message counts and timestamps.
    """
```

#### 4.2a `getChatUsers()` (merged contract)

```python
async def getChatUsers(
    self,
    chatId: int,
    limit: Optional[int] = None,
    minMessages: Optional[int] = None,
    lastActiveDays: Optional[int] = None,
    seenSince: Optional[datetime.datetime] = None,
    *,
    dataSource: Optional[str] = None,
) -> List[ChatUserDict]:
    """List users in a chat, optionally filtered by activity.

    Two modes, selected by which filters are set:

    - **Default** (no `minMessages`, no `lastActiveDays`): orders by
      `updated_at DESC` (most recently active first). Optional
      `seenSince` further restricts to users seen after that time.
    - **Activity-filtered** (any of `minMessages` / `lastActiveDays`
      set): orders by `messages_count DESC` and applies both filters.
    """
```

### 4.3 `getMessageThread()`

Thin wrapper over the two existing repository methods. No new SQL — both
`getChatMessageByMessageId(chatId, messageId)` and
`getChatMessagesByRootId(chatId, rootMessageId)` already exist in
`internal/database/repositories/chat_messages.py`.

```python
async def getMessageThread(
    self,
    chatId: int,
    messageId: MessageId,
    *,
    dataSource: Optional[str] = None,
) -> Optional[ThreadResultDict]:
    """Get a message and its surrounding thread context.

    Fetches the target message, walks to its thread root (if any), and
    returns the root, the target, and every reply in the thread. The
    implementation is a thin composition of existing repository methods —
    no bespoke SQL.

    Behaviour:
    - If `messageId` does not exist in the chat, returns `None`.
    - If the target message has no `root_message_id` (i.e. it is itself a
      root), `root_message` is `None` and `thread_messages` contains only
      the target message.
    - Otherwise, the thread root is fetched via
      `getChatMessageByMessageId(chatId, target.root_message_id)`, and
      the full reply list (including the target) is fetched via
      `getChatMessagesByRootId(chatId, target.root_message_id)`.

    Args:
        chatId: Chat identifier.
        messageId: Message to get thread for.
        dataSource: Optional explicit data source.

    Returns:
        ThreadResultDict with `root_message`, `target_message`, and
        `thread_messages` (chronological order, includes the target).
        Returns `None` if the target message does not exist.
    """
    # 1. Fetch the target message. Return None if it doesn't exist.
    target = await self.getChatMessageByMessageId(
        chatId=chatId, messageId=messageId, dataSource=dataSource
    )
    if target is None:
        return None

    # 2. If the target has a root, fetch the root and the full thread.
    root: Optional[ChatMessageDict] = None
    if target.get("root_message_id") is not None:
        rootMessageId = MessageId(target["root_message_id"])
        root = await self.getChatMessageByMessageId(
            chatId=chatId, messageId=rootMessageId, dataSource=dataSource
        )
        threadMessages = await self.getChatMessagesByRootId(
            chatId=chatId, rootMessageId=rootMessageId, dataSource=dataSource
        )
    else:
        # Target is itself a root — the "thread" is just this one message.
        threadMessages = [target]

    return {
        "root_message": root,
        "target_message": target,
        "thread_messages": threadMessages,
    }
```

### 4.4 Embedding CRUD

```python
async def saveMessageEmbedding(
    self,
    chatId: int,
    messageId: MessageId,
    embedding: list[float],
    model: str,
) -> None:
    """Save or update a message embedding.

    The `dimensions` column is derived from `len(embedding)` rather than
    passed as a separate argument — this avoids mismatch bugs.
    """

async def getMessageEmbedding(
    self,
    chatId: int,
    messageId: MessageId,
) -> Optional[dict]:
    """Get embedding for a specific message."""

async def deleteChatEmbeddings(
    self,
    chatId: int,
) -> None:
    """Delete all embeddings for a chat (e.g., when reindexing)."""
```

### 4.5 New TypedDicts in `internal/database/models.py`

```python
class SearchResultDict(TypedDict):
    """Result of a semantic search query."""

    chat_id: int
    message_id: MessageId
    message_text: str
    date: datetime.datetime
    user_id: int
    username: str
    full_name: str
    message_category: MessageCategory
    score: float
    """Cosine similarity score (0.0 to 1.0)."""


class ThreadResultDict(TypedDict):
    """Thread context for a message."""

    root_message: Optional[ChatMessageDict]
    target_message: ChatMessageDict
    thread_messages: list[ChatMessageDict]
```

---

## 5. Real-Time Embedding on Message Save

### 5.1 Hook in `MessagePreprocessorHandler`

After `saveChatMessage()` succeeds, fire a non-blocking task using the
project's standard background-task pattern (mirrors how image parsing
hooks into `BaseBotHandler` — see `internal/bot/common/handlers/base.py`
around the `_parseImage` call):

```python
# In MessagePreprocessorHandler, after saving:
if self._embeddingsEnabled:
    task = asyncio.create_task(self._embedMessage(chatId, messageId, messageText))
    await self.queueService.addBackgroundTask(task)
```

The `_embedMessage` method:
1. Gets the configured embedding model from `EmbeddingManager`
2. Calls `model.generateEmbeddings(messageText)`
3. Stores result via `db.chatMessages.saveMessageEmbedding(...)`

**Non-blocking by design:** errors are caught and logged inside
`_embedMessage` and never propagated. The handler `await`s only
`queueService.addBackgroundTask(task)` (which has near-zero cost — it
just registers the task in a set under a concurrency cap of
`constants.MAX_QUEUE_LENGTH` = 32, see
`internal/services/queue_service/service.py:addBackgroundTask`), then
returns. The `asyncio.create_task` call returns control to the handler
immediately; the actual embedding work happens in the background task.

### 5.2 Config gate

```toml
[search-history]
enabled = false

[search-history.embeddings]
model = "text-embedding-3-small"  # model name from [llm.models]
on-save = true                       # generate embeddings on message save
```

### 5.3 Concurrency: real-time embedding vs. backfill worker

Both the real-time hook (§5.1) and the backfill worker (§8 step 11) write
to `message_embeddings` for the same chat. Because the app is
single-process async, there is no true parallelism — only interleaving at
`await` points. The `provider.upsert()` call is atomic (single SQL
statement), so concurrent writes to the same `(chat_id, message_id)` row
are safe: the last writer wins, and both writers produce the same
embedding (same model, same text).

The cache increment in `saveMessageEmbedding` (§4.1.1 write path) is
mutated in-place on a Python list — no lock needed because the event
loop ensures sequential access between `await` points. The only race
scenario is: backfill rebuilds the cache from DB, then real-time hook
appends to the OLD cache reference. Mitigation: the real-time hook
always re-fetches `self._embeddingCache.get(chatId)` before appending,
so if the backfill replaced the cache entry, the real-time hook sees the
new entry and appends to it correctly.

---

## 6. `ChatSearchHandler` — Combined Handler

### 6.1 File

`internal/bot/common/handlers/search_history.py`

### 6.2 Class

```python
class ChatSearchHandler(BaseBotHandler):
    """Handler for chat history search, user listing, thread retrieval, and summarization.

    Provides:
    - /search <query> [--user=] [--days=] [--type=]
    - /users
    - LLM tools: search_messages, list_users, get_thread, get_summary
    """
```

### 6.3 Conditional Registration

In `HandlersManager.__init__()`, matching the existing pattern used by
`divination`, `resender`, and `sandbox` (all use
`self.configManager.get("section", {}).get("enabled", False)` — no
dedicated accessor method):

```python
if self.configManager.get("search-history", {}).get("enabled", False):
    self.handlers.append(
        (ChatSearchHandler(configManager=configManager, database=database, botProvider=botProvider),
         HandlerParallelism.PARALLEL)
    )
```

### 6.4 User Commands

**`/search <query>`**

```python
@commandHandlerV2(
    commands=("search",),
    shortDescription="- Search chat history (semantic)",
    helpMessage="Search chat history semantically. Usage: /search <query> [--user=username] [--days=N] [--type=user|bot|all]",
    visibility={CommandPermission.DEFAULT},
    availableFor={CommandPermission.DEFAULT},
    helpOrder=CommandHandlerOrder.NORMAL,
    category=CommandCategory.TOOLS,
)
async def searchCommand(self, ensuredMessage, command, args, updateObj, typingManager) -> None:
```

Supports filters in args:
- `--user=vitaly` — filter by username
- `--days=30` — only last N days
- `--type=user` — only user messages (default: all)

Returns formatted result list with timestamps, usernames, and similarity scores.

**`/users`**

```python
@commandHandlerV2(
    commands=("users",),
    shortDescription="- List chat users",
    helpMessage="List users in this chat with message counts",
    visibility={CommandPermission.DEFAULT},
    availableFor={CommandPermission.DEFAULT},
    helpOrder=CommandHandlerOrder.NORMAL,
    category=CommandCategory.TOOLS,
)
async def usersCommand(self, ensuredMessage, command, args, updateObj, typingManager) -> None:
```

Returns formatted user list:
```
👥 Users in "General Chat" (12):

1. @vitaly — Vitaly G. — 1,234 messages
2. @alex — Alex K. — 892 messages
3. @maria — Maria S. — 456 messages
...
```

### 6.5 LLM Tools

All four tools registered in `__init__()` via `self.llmService.registerTool()`:

**`search_messages`**

```python
self.llmService.registerTool(
    name="search_messages",
    description=(
        "Semantic search through chat history. "
        "Use this when you need to recall past conversations, "
        "find specific information discussed earlier, or "
        "reference previous messages."
    ),
    parameters=[
        LLMFunctionParameter(name="query", description="Search query", type=LLMParameterType.STRING, required=True),
        LLMFunctionParameter(name="limit", description="Max results (default: 5)", type=LLMParameterType.NUMBER, required=False),
        LLMFunctionParameter(name="max_age_days", description="Only messages newer than N days", type=LLMParameterType.NUMBER, required=False),
        LLMFunctionParameter(name="user_name", description="Filter by username", type=LLMParameterType.STRING, required=False),
        LLMFunctionParameter(name="message_type", description="'user', 'bot', or 'all' (default)", type=LLMParameterType.STRING, required=False),
    ],
    handler=self._llmToolSearchMessages,
)
```

**`list_users`**

```python
self.llmService.registerTool(
    name="list_users",
    description="List users in the current chat with their message count and last active time.",
    parameters=[
        LLMFunctionParameter(name="limit", description="Max users (default: 20)", type=LLMParameterType.NUMBER, required=False),
        LLMFunctionParameter(name="min_messages", description="Only users with at least N messages", type=LLMParameterType.NUMBER, required=False),
    ],
    handler=self._llmToolListUsers,
)
```

**`get_thread`**

```python
self.llmService.registerTool(
    name="get_thread",
    description="Get the full conversation thread for a specific message. Use this to understand context around a message.",
    parameters=[
        LLMFunctionParameter(name="message_id", description="Message ID to get thread for", type=LLMParameterType.STRING, required=True),
    ],
    handler=self._llmToolGetThread,
)
```

**`get_summary`**

```python
self.llmService.registerTool(
    name="get_summary",
    description="Get a summary of recent chat activity. You can specify by time period, message count, thread, or date range.",
    parameters=[
        LLMFunctionParameter(name="scope", description="'last_hours', 'last_days', 'last_messages', 'thread', or 'date_range'", type=LLMParameterType.STRING, required=True),
        LLMFunctionParameter(name="value", description="Number for scope (e.g., 24 for last_hours, 50 for last_messages)", type=LLMParameterType.NUMBER, required=False),
        LLMFunctionParameter(name="thread_message_id", description="Message ID for thread scope", type=LLMParameterType.STRING, required=False),
        LLMFunctionParameter(name="from_date", description="Start date for date_range scope (ISO-8601, e.g. '2024-01-01')", type=LLMParameterType.STRING, required=False),
        LLMFunctionParameter(name="until_date", description="End date for date_range scope (ISO-8601, e.g. '2024-01-31')", type=LLMParameterType.STRING, required=False),
    ],
    handler=self._llmToolGetSummary,
)
```

Reuses the existing `SummarizationHandler` logic — retrieves messages via `getChatMessagesSince()` or `getChatMessagesByRootId()`, then calls `LLMService.generateText()` with a summarization prompt.

---

## 7. Config Section

New section in `configs/00-defaults/search-history.toml`:

```toml
[search-history]
enabled = false

[search-history.embeddings]
model = "text-embedding-3-small"
on-save = true
reindex-batch-size = 100

[search-history.defaults]
max-results = 10
default-days = 30
```

Add `getSearchHistoryConfig()` to `ConfigManager` (optional convenience
accessor — the handler registration in §6.3 uses the lighter
`self.configManager.get("search-history", {})` pattern, matching
`divination`/`sandbox`/`resender`):

```python
def getSearchHistoryConfig(self) -> Dict[str, Any]:
    """Get search history configuration.

    Returns:
        Search history config dict with 'enabled', 'embeddings', and 'defaults' keys.
    """
    return self.config.get("search-history", {})
```

---

## 8. Implementation Order

**Step budget assessment:** With ~60 steps per `software-developer`
invocation, the 15-step plan can be implemented in 3-4 invocations:
- **Invocation 1** (steps 1-4): `lib/ai/` embedding support — Abstract,
  OpenAI, local provider, manager registration. ~40-50 steps (new file +
  edits to 3 existing files + tests).
- **Invocation 2** (steps 5-9): DB layer — TypedDicts, migration,
  repository methods, chat settings, config. ~50-60 steps (heavy
  repository work with cache logic).
- **Invocation 3** (steps 10-13): Handler + integration — preprocessor
  hook, backfill worker, ChatSearchHandler, manager registration.
  ~50-60 steps (largest step; if over budget, split step 12 into
  "commands only" + "LLM tools only").
- **Invocation 4** (steps 14-15): Tests + docs. ~40-50 steps.

Steps 1-4 and 5-9 are independent of each other and can be parallelized.

| # | Step | Files touched | Depends on |
|---|---|---|---|
| 1 | Add `supportsEmbedding` + `_generateEmbeddings` + `generateEmbeddings` (no fallback) to `AbstractModel` | `lib/ai/abstract.py`, `lib/ai/models.py` | — |
| 2 | Implement OpenAI embedding in `BasicOpenAIProvider` | `lib/ai/providers/basic_openai_provider.py` | Step 1 |
| 3 | Create `FastembedProvider` + `FastembedModel` (multi-model, extraConfig-driven) with `fastembed` | `lib/ai/providers/fastembed_provider.py` | Step 1 |
| 4 | Register `fastembed` provider type in `LLMManager` (no `getModelsSupportingEmbedding()` — removed) | `lib/ai/manager.py` | Steps 2, 3 |
| 5 | Add TypedDicts: `SearchResultDict`, `ThreadResultDict` | `internal/database/models.py` | — |
| 6 | Migration `migration_017` — `message_embeddings` table | `internal/database/migrations/versions/migration_017_*.py` | — |
| 7 | Repository methods: `saveMessageEmbedding`, `getMessageEmbedding`, `deleteChatEmbeddings`, `searchChatMessages` (with optional `queryEmbedding`, `rootMessageId`, and `TTLDict` cache), `listChatUsers`, `getMessageThread` (thin wrapper). **Note:** `ChatMessagesRepository` currently declares `__slots__ = ()`, so the new `_embeddingCache` instance attribute requires adding it to `__slots__` (e.g. `__slots__ = ("_embeddingCache", "_maxCachedChats")`) | `internal/database/repositories/chat_messages.py` | Steps 5, 6 |
| 8 | Add 4 new `ChatSettingsKey` values + `_chatSettingsInfo` entries: `EMBEDDING_MODEL`, `EMBEDDINGS_ENABLED`, `REGENERATE_EMBEDDINGS`, `MAX_MESSAGES_FOR_SEMANTIC_SEARCH` (per §2.7; defaults live under `[bot.defaults]` in `configs/00-defaults/bot-defaults.toml`) | `internal/bot/models/chat_settings.py`, `configs/00-defaults/bot-defaults.toml` | — |
| 9 | Add `[search-history]` config section + `getSearchHistoryConfig()` (includes `cache-ttl-seconds`, `cache-max-chats` from §4.1.1) | `configs/00-defaults/`, `internal/config/manager.py` | — |
| 10 | Hook embedding generation into `MessagePreprocessorHandler` (reads `EMBEDDING_MODEL` and `EMBEDDINGS_ENABLED` from chat settings, falls back to `[search-history.embeddings].model`, dispatches via `asyncio.create_task` + `queueService.addBackgroundTask` per §5.1) | `internal/bot/common/handlers/message_preprocessor.py` | Steps 4, 7, 8, 9 |
| 11 | Add embedding backfill worker (consumes `REGENERATE_EMBEDDINGS`, calls `searchChatMessages` filter-only path to find missing/stale rows, re-embeds, resets flag). **Lifecycle:** register as a `CRON_JOB` delayed-task handler in `ChatSearchHandler.__init__()` (matching `SandboxHandler`'s pattern — see `internal/bot/common/handlers/sandbox.py` which registers `CRON_JOB` + `DO_EXIT` handlers), NOT wired directly in `main.py`. The worker logic lives in `ChatSearchHandler._cronEmbeddingBackfill()` or in a helper module under `internal/bot/common/handlers/` (e.g. `embedding_backfill.py`). No new `internal/services/embedding/` directory. | `internal/bot/common/handlers/search_history.py` (or helper module) | Steps 7, 8 |
| 12 | Create `ChatSearchHandler` with `/search`, `/users` commands + 4 LLM tools (`search_messages`, `list_users`, `get_thread`, `get_summary`) | `internal/bot/common/handlers/search_history.py` | Steps 7, 8, 10 |
| 13 | Register handler conditionally in `HandlersManager` (gated by `[search-history].enabled`, per §6.3) | `internal/bot/common/handlers/manager.py` | Steps 9, 12 |
| 14 | Tests for all new code (handlers, repository, provider, backfill worker, cache eviction, chat-settings wiring) | `tests/` | Steps 1–13 |
| 15 | Documentation update | `docs/llm/`, `docs/database-schema*.md` | Steps 1–14 |

### 8.1 Error Handling Summary

| Failure mode | Handling |
|---|---|
| Embedding model unavailable (deleted from TOML, API down) | `LLMManager.getModel()` returns `None`; consumer falls back to `[search-history.embeddings].model`; if that also fails, fall back to hardcoded `"text-embedding-3-small"`. If all three resolve to `None`, log an error and skip embedding generation (on-save hook) or return "embedding model not configured" (search command/tool). |
| `fastembed` not installed | `_FASTEMBED_AVAILABLE = False`; `FastembedProvider` skips initialization, logs a warning. Models under `[llm.providers.fastembed]` are not registered. If the chat's `EMBEDDING_MODEL` points at a local model, the fallback chain kicks in (server-wide default, then hardcoded). |
| `generateEmbeddings()` raises after all retries | On-save hook: the `asyncio.create_task` wrapper catches the exception, logs it, and returns — the message is saved without an embedding. On search: the `/search` command responds with a transient-error notice. |
| TTLDict cache grows unbounded | Enforced by `_evictIfOverCapacity()` after every cache `set()`. The `cache-max-chats` config (default 20) caps the number of cached chats. TTL auto-eviction (default 300s) handles the common case. |
| Backfill encounters a malformed embedding BLOB | The backfill worker wraps `np.frombuffer()` in a try/except; malformed rows are logged and skipped. A future improvement could add a `DELETE` + re-embed for corrupted rows. |
| `REGENERATE_EMBEDDINGS` set while on-save hook is active | Safe: both paths call `provider.upsert()` which is idempotent. See §5.3 for concurrency analysis. |
| `numpy` not available | `numpy` is a required dependency (already in `requirements.txt`). No optional-import guard needed. |

---

## 9. Resolved Decisions

All five open questions from the previous revision are now closed. Recording
them here so the design rationale is preserved alongside the plan.

1. **`fastembed` vs `sentence-transformers` for local embeddings? — RESOLVED**
   - **Decision:** `fastembed` as an optional dependency, guarded by
     `try/except ImportError` with a `_FASTEMBED_AVAILABLE` flag. Local
     embedding support is purely opt-in; a server without `fastembed`
     installed continues to work using only OpenAI-style embedding models.
   - **Rationale:** ~50MB install, no PyTorch dependency, CPU inference is
     fast enough for the bot's scale (a few hundred messages/sec at peak).
     `sentence-transformers`'s broader model zoo isn't needed yet — the
     default `all-MiniLM-L6-v2` (384-dim) and `all-mpnet-base-v2` (768-dim)
     both ship in fastembed.

2. **Backfill existing messages? — RESOLVED**
   - **Decision:** Two mechanisms, no `/search reindex` command:
     - **Steady state:** when `[search-history.embeddings].on-save = true`,
       new messages get embedded automatically as they arrive (see §5).
     - **One-shot backfill:** the `REGENERATE_EMBEDDINGS` chat setting
       (see §2.7) is a boolean trigger. A periodic worker checks this flag
       per chat, re-embeds any message whose `message_embeddings.model`
       differs from the current `EMBEDDING_MODEL` (or has no embedding
       row at all), then resets the flag to `false`.
   - **Rationale:** keeps the surface small (no new command, no new
     admin-only path) and the backfill is naturally model-aware — switching
     embedding models automatically triggers re-embedding of the affected
     chat without an operator running a one-off job.

3. **Embedding model for OpenAI-compatible providers? — RESOLVED**
   - **Decision:** default to 256 dimensions for OpenAI-style models
     (configurable via `embedding_dimensions` in the model TOML block).
   - **Rationale:** OpenAI's own docs show negligible accuracy loss at
     256 vs 1536 on their standard benchmarks; the 6x storage and dot-
     product saving matters when a chat has tens of thousands of
     messages. Power users can override per-model in the TOML config.

4. **Search permission? — RESOLVED**
   - **Decision:** `/search` is available to all chat members by default
     (`CommandPermission.DEFAULT`), matching the existing `/web_search`
     command. The bot owner can flip a chat to `CommandPermission.ADMIN`
     via the per-chat settings UI if needed — no code change required
     to tighten later.
   - **Rationale:** the data being searched is already visible to the
     user in the chat; there is no information-disclosure concern. LLM
     tools (`search_messages`, `list_users`, `get_thread`,
     `get_summary`) inherit the existing `ALLOW_TOOLS_COMMANDS` chat
     setting, which already gates whether the bot can use any LLM tool
     on the user's behalf.

5. **`get_summary` scope combinations? — RESOLVED**
   - **Decision:** support the four scopes from the original list, plus
     a `date_range` scope taking `from` and `until` (ISO-8601 strings):
     - `get_summary(scope="last_hours", value=24)` — last 24 hours
     - `get_summary(scope="last_days", value=7)` — last 7 days
     - `get_summary(scope="last_messages", value=50)` — last 50 messages
      - `get_summary(scope="thread", thread_message_id=123)` — a specific
        thread (resolved via `getMessageThread`)
      - `get_summary(scope="date_range", from_date="2024-01-01", until_date="2024-01-31")`
        — arbitrary date range
   - **Rationale:** the `date_range` form subsumes the `last_days` use
     case for power users and is the natural shape for the LLM tool. All
     four pre-existing scopes are kept for back-compat with prompts that
     already use them. Implementation reuses
     `getChatMessagesSince()` / `getChatMessagesByRootId()` /
     `getMessageThread()` for retrieval and `LLMService.generateText()`
     for the actual summarization — no new SQL.

---

## 10. Documentation Impact

After implementation, update:

| Doc | What changes |
|---|---|
| `docs/llm/architecture.md` | ADR for embedding support in `lib/ai/`, new handler, embedding cache + backfill worker |
| `docs/llm/handlers.md` | Add `ChatSearchHandler` to handler list; note the new `EMBEDDINGS_ENABLED` / `REGENERATE_EMBEDDINGS` / `MAX_MESSAGES_FOR_SEMANTIC_SEARCH` chat settings read by `MessagePreprocessorHandler` and `ChatSearchHandler`; document the `asyncio.create_task` + `queueService.addBackgroundTask` hook pattern used by the embedding save path |
| `docs/llm/database.md` | New `message_embeddings` table, new repository methods (`searchChatMessages` with optional `queryEmbedding` + `rootMessageId` + per-`chatId` TTLDict cache, `getMessageThread` as thin wrapper) |
| `docs/llm/libraries.md` | Embedding support in `lib/ai/` (no model fallback, `support_embeddings` field), new `FastembedProvider` + `FastembedModel` (multi-model, extraConfig-driven) |
| `docs/llm/services.md` | Embedding backfill as a CRON_JOB delayed-task handler in `ChatSearchHandler` (not a separate service singleton) |
| `docs/llm/configuration.md` | New `[search-history]` config section (including `cache-ttl-seconds`, `cache-max-chats`, `on-save`); 4 new chat settings (`EMBEDDING_MODEL`, `EMBEDDINGS_ENABLED`, `REGENERATE_EMBEDDINGS`, `MAX_MESSAGES_FOR_SEMANTIC_SEARCH`) with defaults wired under `[bot.defaults]` in `bot-defaults.toml`; `support_text = false` / `support_embeddings = true` model flags; multi-model `[llm.models.*]` blocks under a single `[llm.providers.fastembed]` |
| `docs/llm/tasks.md` §4.1 (Chat Settings Registration — CRITICAL) | Reference this plan for the 4-site wiring pattern: enum entry → `_chatSettingsInfo` row (metadata only — no `default` field) → default in `[bot.defaults]` in `bot-defaults.toml` → consumer in `MessagePreprocessorHandler` / `ChatSearchHandler` / backfill worker / `searchChatMessages` |
| `docs/database-schema.md` + `docs/database-schema-llm.md` | `message_embeddings` table with composite PK, `model` + `dimensions` columns, `updated_at` for re-embed tracking, and the rationale for the `model` column (stale-embedding detection for `REGENERATE_EMBEDDINGS`) |
| `docs/llm/index.md` | Project map updates: new handler, new provider, new worker, new chat settings |