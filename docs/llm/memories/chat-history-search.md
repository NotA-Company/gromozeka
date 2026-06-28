# Chat History Search — Durable Memory

Durable task-specific memory for the completed chat history search feature (Steps 1 & 2 completed
2026-06-21 / 2026-06-25, reviewed 2026-06-28).

How to use this file:
- Read it when touching `ChatSearchHandler`, `ChatEmbeddingsRepository`, `ChatSearchRepository`,
  embedding pipeline (`fastembed` provider, `embedAndSaveMessage`), search-related config, or
  `/search` / `/users` commands and LLM tools (`search_messages`, `list_users`, `get_thread`).
- Keep only chat-search-scoped discoveries here; move repo-wide lessons back to
  [`../teamlead-memory.md`](../teamlead-memory.md).
- Never store secrets, tokens, `.env` values, or raw logs.

## Overview

- **Implementation plan**: `docs/plans/chat-history-search-plan.md`
- **Step 2 plan**: `docs/plans/chat-history-search-step2.md` — adds `/users` command +
  `search_messages`, `list_users`, `get_thread` LLM tools
- **Default embedding model**:
  `local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384d, ~0.22 GB, ~50
  languages, 512 token context) via `FastembedProvider`, set as `embedding-model` in
  `bot-defaults.toml` under `[bot.defaults]`
- **Alternative model**: `local/jinaai/jina-embeddings-v3` (1024d, ~2.24 GB, ~100 languages, 1024
  token context) in `fastembed-models.toml`
- **Version**: `fastembed==0.8.0` pinned in `requirements.direct.txt`; `numpy==2.4.6` in
  requirements
- **Key repositories**:
  - `ChatEmbeddingsRepository` — embedding CRUD (all embedding methods + semantic search moved
    here from `ChatMessagesRepository`)
  - `ChatSearchRepository` — search dispatcher
  - `ChatUsersRepository.getChatUsers` — activity filters (exposes `limit` / `minMessages` /
    `lastActiveDays` / `seenSince` on a single method)
  - `ChatMessagesRepository.getMessageThread` — thread retrieval
- **Backfill**: `_dtCronJob` in `ChatSearchHandler` — round-robin per-chat, discovers chats via
  `EMBEDDINGS_ENABLED` (which defaults to false, so enabled chats always have a DB row), then gates
  per-chat by checking `REGENERATE_EMBEDDINGS` (which defaults to true, so it's rarely persisted and
  can't be queried directly). No auto-reset — manual only via `/settings`.
- **Shared helper**: `embedAndSaveMessage` in `internal/bot/common/embedding_utils.py` — takes
  `EnsuredMessage`, resolves `LLMService` via `getInstance()`
- **Config cached**: `_searchEnabled`, `_reindexBatchSize` in handler `__init__`
- **`DO_EXIT` registration is OPTIONAL** — not required by `QueueService`.
  `QueueService.startDelayedScheduler` already registers its own built-in `DO_EXIT` handler
  (`_doExitHandler`) that performs the actual graceful-shutdown bookkeeping. `ChatSearchHandler`
  only registers `CRON_JOB`, not `DO_EXIT`, because it owns no resources that need coordinated
  teardown.
- **Anti-patterns**: See the dedicated section below — 20 mistakes made and fixed during Step 1.

### Embedding Model Resolution

Single-tier resolution chain in both `ChatSearchHandler._dtCronJob` (backfill) and
`MessagePreprocessorHandler` embedding dispatch:

1. Read the per-chat `EMBEDDING_MODEL` chat setting (default
   `"local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"` from `bot-defaults.toml`
   `[bot.defaults].embedding-model`).
2. If the resolved model name is empty / unresolvable / unsupported → silent no-op for that chat
   on that tick.

The server-wide `[search-history.embeddings].model` and `[search-history.embeddings].on-save`
config keys were removed — the per-chat default already provides the model name, and the on-save
dispatch is unconditional whenever `[search-history].enabled` (cached in `_searchEnabled` at
construction time) and `EMBEDDINGS_ENABLED` are both on.

### Step 2 Items Implemented

| Item | Type | File |
|------|------|------|
| `/users` command | User command | `chat_search.py` |
| `search_messages` | LLM tool | `chat_search.py` |
| `list_users` | LLM tool | `chat_search.py` |
| `get_thread` | LLM tool | `chat_search.py` |

## Implementation Decisions (2026-06-20 / 2026-06-21)

### Architecture & Design Decisions

- **`MAX_MESSAGES_FOR_SEMANTIC_SEARCH` page**: `BOT_OWNER` (resolved from plan inconsistency).
- **Backfill chat discovery**: Query DB for chats with `EMBEDDINGS_ENABLED = true`, then gate
  per-chat by checking `REGENERATE_EMBEDDINGS`. Process N chats per CRON_JOB tick with configurable
  batch size.
- **Plan gaps fixed**: `ChatSettingsPage.BOT_OWNER` reconciled; backfill discovery specified.
- **Parser merge semantics in `_parseSearchArgs`**: bare words merge with `keywords:`, first
  occurrence wins for other keys, values span tokens until next known key.
- **Lazy import of `ChatSettingsValue` in `internal/database/repositories/chat_settings.py`**:
  `listChatsBySetting` imports `ChatSettingsValue` inside the method body to break a
  package-initialization cycle (`internal.database → internal.bot.models → internal.database`).
- **Backfill as CRON_JOB handler**: Backfill lives in `ChatSearchHandler._dtCronJob`, not a
  separate `BackfillWorker` class. The previous
  `internal/bot/common/workers/backfill_worker.py` module was removed. `HandlersManager.__init__`
  simply appends `ChatSearchHandler` to the handler list when `[search-history].enabled` is true.
- **`DO_EXIT` registration optional**: `ChatSearchHandler` does NOT register a `DO_EXIT` handler
  — it only registers `CRON_JOB`. The `QueueService` has its own built-in `_doExitHandler`.
  Handlers that own resources (sandbox runs, pending sends, periodic cleanups) register one;
  `ChatSearchHandler` does not.
- **Semantic search wired into `/search`**: keywords → `generateEmbeddings` → `queryEmbedding`
  passed to `searchChatMessages` (falls back to filter-only on failure).
- **No cache in DB layer**: Embedding cache was initially inside `ChatMessagesRepository` and was
  removed entirely. Caching is a handler-layer concern.

### Model & Config Decisions

- **Embedding model history**: Switched from English-only `bge-small-en-v1.5` (384d) → multilingual
  `intfloat/multilingual-e5-large` (1024d) for Russian support → current default
  `local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384d).
- **Model resolution simplified**: 2-tier (chat setting → default model name in
  `bot-defaults.toml`), not 3-tier. The `[search-history.embeddings].model` server-wide fallback
  was removed as redundant.
- **`on-save` config dropped**: Always embed if enabled; no toggle needed.
- **`_searchEnabled` cached** in `MessagePreprocessorHandler.__init__`.

### Repository Decisions

- **`ChatEmbeddingsRepository` created**: All embedding methods + semantic search moved here from
  `ChatMessagesRepository`.
- **`listChatUsers` → merged into `getChatUsers`**: The separate `listChatUsers` method was
  merged into `getChatUsers`, which now exposes `limit` / `minMessages` / `lastActiveDays` /
  `seenSince` on a single method.
- **`listChatsBySetting` simplified**: Returns `List[Dict]` with `chat_id`/`value`; callers filter
  via `ChatSettingsValue.toBool()`.

### Production Bugs Found & Fixed

- `convertToSQLite` didn't handle `bytes`.
- `TTLDict(defaultTtl=...)` kwarg was silently swallowed.
- `_filterMessageIds` AND → OR logic error.
- `_parseSearchArgs` couldn't handle `key: value` with space.
- Keyword filter applied after SQL LIMIT (see anti-pattern #13).
- IN() portability issue.

### Gate 2 Review Outcome (2026-06-20)

- **3 critical issues**: all fixed.
- **6 important issues**: 2 fixed, 4 deferred.

## Anti-Patterns Learned (20 items)

These mistakes were made during Step 1 implementation and fixed. Don't repeat them.

### Architecture & Layering (#1-5)

1. **Don't put caching in repositories.** The DB layer is for data access only. Caches (TTLDict,
   CacheService) belong in handlers. The embedding cache was initially inside
   `ChatMessagesRepository` and had to be removed entirely.

2. **Don't create separate classes for features that fit in existing handlers.** `BackfillWorker`
   was a standalone class with lazy imports — user rejected it. A CRON_JOB handler directly in
   `ChatSearchHandler` is simpler and doesn't need a new file.

3. **Don't put code that needs `internal/` types into `lib/`.** The summarization module used
   `llmService: Any` because `lib/` can't import `internal/`. It was moved to
   `internal/bot/common/`, then deleted entirely. If a module needs types from `internal/`, it
   belongs in `internal/`.

4. **Extend existing methods, don't create near-duplicates.** `listChatUsers` was a separate method
   alongside `getChatUsers`. Merged: `getChatUsers` now accepts optional `minMessages`,
   `lastActiveDays`, `limit`.

5. **One domain per repository.** Embedding methods were scattered across `ChatMessagesRepository`.
   They were split into `ChatEmbeddingsRepository` (embedding CRUD) and `ChatSearchRepository`
   (search dispatcher). Each repo owns one domain.

### Repository Design (#6-8)

6. **Always return TypedDicts from repository methods.** Never return raw `dict` or `tuple` — too
   hard to track what fields exist. Every method that queries the DB should return a TypedDict
   (`ChatMessageDict`, `MessageEmbeddingDict`, `ThreadResultDict`, etc.).

7. **All repo methods that return the same entity should return the same TypedDict with ALL
   fields.** `getMessageEmbedding` and `getMessagesWithoutEmbeddings` initially returned different
   subsets of fields. Both now return full `MessageEmbeddingDict` (one has NULL embedding, the
   other has the vector).

8. **Use `dbUtils.sqlToTypedDict` for row conversion.** Don't build dicts manually in repository
   methods. The project has standard converters — use them. Only handle special cases (BLOB →
   list[float]) manually before passing to the converter.

### Config & State (#9-11)

9. **Cache config values in `__init__`, don't re-read on every invocation.**
   `configManager.getSearchHistoryConfig()` was called on every message and every CRON_JOB tick.
   Cache `_searchEnabled`, `_reindexBatchSize` etc. once.

10. **Don't add config options without a real use case.** `on-save` toggle was added but served no
    purpose: "If embeddings are enabled + enabled for chat, then they are saved on save." Removed.

11. **Model resolution: if a chat setting has a default, don't add a server-wide fallback.**
    `EMBEDDING_MODEL` now has a default in `bot-defaults.toml`
    (`"local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"`), so the
    `[search-history.embeddings].model` server-wide fallback was redundant. Two-tier, not
    three-tier.

### Feature Design (#12-15)

12. **If you build semantic search infrastructure, wire it in.** Embeddings were generated and
    stored but `/search` only used filter-only mode. The entire point of the feature is semantic
    search — the query embedding path must be wired.

13. **Filters must apply before result truncation.** The keyword filter was applied client-side
    AFTER the SQL LIMIT, silently dropping matching results outside the limit window. Always
    filter first, then truncate.

14. **Backfill discovery uses `EMBEDDINGS_ENABLED`, not `REGENERATE_EMBEDDINGS`.**
    `REGENERATE_EMBEDDINGS` defaults to true so it's rarely in the DB and `listChatsBySetting`
    would miss most chats. Instead, query `EMBEDDINGS_ENABLED` (which defaults to false, so
    enabled chats always have a DB row), then filter per-chat by checking `REGENERATE_EMBEDDINGS`
    after discovery.

15. **Don't list all rows to find one.** `_resolveUserId` called `listChatUsers(limit=None)` to
    find one user by username. Use targeted queries: `getChatUserByUsername(chatId, username)`.

### Code Quality (#16-20)

16. **Extract duplicated logic into shared helpers.** `_dtCronJob` and `_embedMessage` had
    identical embed+save code. Extracted to `embedAndSaveMessage` in
    `internal/bot/common/embedding_utils.py`.

17. **No redundant guard checks.** `supportsEmbedding` was checked in both `abstract.py` (public
    method) and `basic_openai_provider.py` (private method). The provider check is redundant —
    the public method already guards.

18. **No lazy imports inside methods.** `AGENTS.md` forbids this. Initial `BackfillWorker` import
    was lazy — removed when the worker was deleted.

19. **Parser must handle documented syntax.** `/search` DSL uses `key: value` with space. The
    initial token-by-token parser broke on this. Parser must consume multi-token values until the
    next known key.

20. **Keywords are optional if other filters exist.** The parser required keywords even when
    `user:` or `days:` were provided. Check that at least one argument is given, not that keywords
    specifically is present.

## Post-Review Fixes — Round 1 (2026-06-21)

11 review issues fixed across 9 files (one excluded: `EnsuredMessage` reconstruction
optimization). Key changes:

- **`MAX_MESSAGES_FOR_SEMANTIC_SEARCH` wired**: Previously dead config — setting existed but was
  never passed to `searchChatMessages`, causing silent failures on large chats (>32k messages).
  Now read from `targetChatSettings[ChatSettingsKey.MAX_MESSAGES_FOR_SEMANTIC_SEARCH].toInt() or
  None` and passed as `maxMessages=`.
- **`_searchEnabled` removed from `_dtCronJob`**: Dead code — the handler is only constructed
  when `[search-history].enabled=true`. Removed the field assignment from `__init__` too.
- **`REGENERATE_EMBEDDINGS` self-reset attempted then reverted (2026-06-28)**: Self-reset was
  implemented briefly but reverted per user decision — the flag must be manually reset via
  `/settings`. The cron job's docstring now explicitly states "no self-resetting". The auto-reset
  code was removed from `_dtCronJob`.
- **Rate-limit gate moved**: `self.llmService.rateLimit()` now inside `if keywords:` block only
  — filter-only `/search` queries don't consume LLM budget.
- **`embedAndSaveMessage` signature preserved**: The function MUST accept `EnsuredMessage` — the
  user needs access to attachment data for embedding content. The signature remains
  `(ensuredMessage: EnsuredMessage, modelName: str, db: Database) -> bool`. The background-task
  race condition (review recommendation #6) is accepted: the risk of a downstream handler mutating
  `ensuredMessage.messageText` before the task reads it is theoretical and low. Do NOT change this
  signature in the future without explicit approval.
- **`saveMessageEmbedding` exception propagation**: Removed try/except — exceptions propagate to
  `embedAndSaveMessage` which already has its own error boundary.
- **Zero-vector warning**: `logger.warning` in `chat_search.py` repo when
  `np.linalg.norm(queryVec) < 1e-8`.
- **Help text**: `chat: <chat_id|@username>` → `chat: <chat_id>` (username resolution not
  implemented).
- **`_backfillIndex` bounded**: `%= len(enabledChats)` after increment.
- **Lambda → `_embedSync` helper** in `fastembed_provider.py`.
- **`bytearray` added** to `convertToSQLite` return type.
- **Test**: `test_cron_disabled_by_kill_switch` → `test_cron_proceeds_after_construction`.

## Step 2 Implementation (2026-06-25)

### Key Implementation Details

- **`minMessages` on `getChatUsers`**: The repo method (`chat_users.py`) was extended with
  `minMessages: Optional[int] = None` parameter plus
  `AND (:minMessages IS NULL OR messages_count >= :minMessages)` WHERE clause. Follows the
  existing `seenSince` pattern.
- **`_listUsersInternal` shared helper**: Both `/users` command and `list_users` LLM tool call the
  same private method that delegates to `getChatUsers()`. `/users` formats as Markdown;
  `list_users` returns JSON dict.
- **`_formatMessageDict` helper**: Async instance method on `ChatSearchHandler`. Converts
  `ChatMessageDict` rows to JSON-safe dicts with documented snake_case keys: `message_id`,
  `message_text`, `username`, `full_name`, `date`, `reply_id`, `thread_id`. Does NOT use
  `formatForLLM(JSON)` — returns its own dict shape. Handles `None` `reply_id` correctly (returns
  `None`, not `"None"`). Used by `get_thread` LLM tool.
- **`_llmToolSearchMessages` bug (fixed 2026-06-27)**: Missing `formatted.append(retMsg)` — loop
  computed results but never appended them. Output was always `[]` and `count` 0. Now fixed.
  Results use `formatForLLM(JSON)` keys (camelCase: `text`, `messageId`) — different from
  `_formatMessageDict` snake_case contract.
- **`_relativeTime` static method**: Formats a `datetime` to short relative strings (`<1m ago`,
  `5m ago`, `1h ago`, `yesterday`, `5d ago`, `>1w ago`).
- **LLM tool registrations in `__init__`**: All 3 tools (`search_messages`, `list_users`,
  `get_thread`) registered after `CRON_JOB` registration, using
  `self.llmService.registerTool(name, description, [LLMFunctionParameter(...)], handler=self._llmTool*)`.
- **Imports**: `from lib.ai import LLMFunctionParameter, LLMParameterType` added to
  `chat_search.py`.
- **Tests**: 31 new tests across 5 classes in `test_chat_search.py` (103 total for the file).
  `_makeChatSettings` helper extended with `allowTools` and `embeddingsEnabled` params.

### Step 2 Gotchas & Lessons

- **`_resolveUserId` must prepend `@` before DB lookup**: The `chat_users` table ALWAYS stores
  usernames with `@` prefix (confirmed by `updateChatUser` docstring, all three `MessageSender`
  factories, and `saveChatMessage`). `getChatUserByUsername` does exact case-insensitive match
  with no prefix handling. But `_resolveUserId` strips `@` with `lstrip("@")` before querying —
  `LOWER("@cthulho") != LOWER("cthulho")`. Fix: after stripping `@` for normalisation, always
  prepend `@` before the DB call: `clean = f"@{clean}"`. Regression test
  `test_resolve_without_at_prefix` encodes this.
- **LLM tool `int(limit)` guard**: `limit: int` params can arrive as `None` (LLM passes `null`) or
  `float` (NUMBER type). Always guard:
  `effectiveLimit = int(limit) if limit is not None else DEFAULT`. Same in `/users` command where
  user input parsing yields arbitrary ints.
- **LLM tool `rateLimit` must be wrapped in try/except**: `LLMService.rateLimit()` can raise
  `RuntimeError`/`ValueError`. The LLM tool dispatcher does NOT catch exceptions, so an uncaught
  raise aborts the entire LLM generation. All LLM tool handlers that call `rateLimit` must wrap
  it.
- **Don't duplicate `_resolveUserId`**: The existing `_resolveUserId(chatId=, username=)` helper
  already strips `@`, calls `getChatUserByUsername`, handles try/except, and returns
  `Optional[int]`. No need to re-implement inline.
- **`last_active` None handling**: When `updated_at` is `None` in a `ChatUserDict`,
  `.get("updated_at", "")` returns `None` (default only for missing keys), and `str(None)`
  produces `"None"`. Must check `is None` explicitly before `str()`.
- **`MessageRecipient` has no `name` field**: Only `id` and `chatType` slots. The `/users` command
  uses `str(recipient.id)` as chat name.
- **`getChatUserByUsername` can raise**: Even though it catches DB errors internally, it's an
  awaitable from a different module — always wrap in try/except in LLM tool handlers that must
  never raise.
- **Clamp limits on both ends**: User commands and LLM tools must clamp with
  `max(1, min(limit, CAP))`. Missing lower bound lets negative/zero values through to
  `applyPagination`.
- **Truncate message_text in LLM tool output**: `_formatMessageDict` must truncate to
  `SEARCH_TOOL_MAX_MESSAGE_LENGTH` (500) to prevent context-window blowup. Same pattern in both
  `search_messages` and `get_thread`.
- **Gate-2 review step-budget**: The `code-reviewer` agent can hit the 60-step limit on large
  reviews. For cross-cutting whole-work reviews, keep the brief focused on integration concerns
  only (skip per-file details already covered by Gate 1). If it hits the limit, extract findings
  from the partial output and dispatch fixes.

## Test Mocking: Chat Settings Must Be Complete Dicts

- Production code accesses `chatSettings[KEY].toBool()` via direct subscript, never `.get()` with
  a default. Test mocks that return sparse `ChatSettingsDict` cause `KeyError` for any key the
  production path reads.
- `_makeChatSettings()` helpers must include every `ChatSettingsKey` that the production path
  accesses. When adding a new gate check in production (e.g., `REGENERATE_EMBEDDINGS`), the test
  helper must be updated to include it.
- `test_cron_no_enabled_chats` had a second-order bug: the assertion used a stale key
  (`REGENERATE_EMBEDDINGS`) that didn't match the current production query
  (`EMBEDDINGS_ENABLED`). When production queries change, test assertions must follow.

## Post-Review Fixes — Round 2 (2026-06-28, updated same day)

Five review findings addressed, then two further user decisions applied:

| # | Finding | File | Fix | Status |
|---|---------|------|-----|--------|
| 1 | SQL parameter limit (>999 IN params) | `repos/chat_search.py` | Batch IDs in groups of 500 with dynamic per-batch count accounting for non-mid params | **Kept** |
| 2 | Unbounded filter-only search load | `handlers/chat_search.py` | Initially: `dbLimit` conditional. Then: dropped client-side keywords entirely, always pass `limit=self._maxResults` | **Simplified** |
| 3 | REGENERATE_EMBEDDINGS self-reset | `handlers/chat_search.py` | Initially implemented, then **reverted** per user decision — manual reset only | **Reverted** |
| 4 | `_dtCronJob` docstring drift | `handlers/chat_search.py` | Updated docstrings to match two-step discovery | **Kept** |
| 5 | Empty EMBEDDING_MODEL dispatched | `message_preprocessor.py` | Added `if embeddingModelName:` guard | **Kept** |

### User Decisions (2026-06-28)

- **No auto-reset of REGENERATE_EMBEDDINGS**: The flag must be manually reset via `/settings`.
  Docstrings and config descriptions updated accordingly.
- **Drop client-side keyword matching**: Vector search (via `queryEmbedding`) is sufficient.
  Removed the post-search substring filter that required `limit=None`. Now always pass
  `limit=self._maxResults`.
- **Fix recommendations #7-#9**: `_loadEmbeddingsFromDb` type annotation fixed
  (`tuple[List[List[float]], List[MessageId]]`), `_formatMessageDict` docstring completed,
  `_llmToolGetThread` uses `asyncio.gather`.

### Key Lessons

- **Self-reset placement bug** (historical): The initial fix placed the reset AFTER
  `if not pendingMessagesList: return`, making it unreachable. Lesson: place cleanup logic BEFORE
  early-return guards. (Moot after revert but the pattern is general.)
- **Dynamic batch size**: The `_MESSAGE_ID_FILTER_BATCH_SIZE = 500` constant must account for
  non-mid params. Use `perBatchCount = min(BATCH_SIZE, 990 - baseParamCount)` to stay under
  SQLite's 999 limit.
- **Stale anti-patterns in memory**: Anti-pattern #14 was written when the plan said "discover by
  REGENERATE_EMBEDDINGS". The implementation switched to EMBEDDINGS_ENABLED because the former
  defaults to true and is rarely in the DB. When implementation contradicts a recorded "lesson",
  update the lesson.
- **Gate 2 step budget**: The whole-work review agent hit its 60-step limit. Keep Gate 2 briefs
  tightly scoped to cross-cutting concerns only.
- **Accidental `git checkout`**: A software-developer ran `git checkout HEAD --` on a file it
  wasn't supposed to touch, wiping pre-existing working-tree changes. When briefs touch multiple
  files, be explicit about which files to NOT touch.
- **`code-reviewer` subagent may return empty results** in some sessions. If it does twice, fall
  back to `general` agent for the review — use the same prompt structure, just route through
  `general`.
