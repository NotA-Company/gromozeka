# Teamlead Memory

Durable working memory for `.opencode/agents/teamlead.md`.

How to use this file:
- Read it at the beginning of every task.
- If the task touches a subsystem with archived task memory under [`memories/`](memories/index.md), read the relevant file too.
- Re-read it when prior context feels uncertain or incomplete.
- Update it immediately after learning durable new information.
- Consolidate and clean it before finishing a task.
- Store reusable facts, not temporary task chatter.
- Never store secrets, tokens, `.env` values, or raw logs.

## User Preferences

- Uses `TASK_STATE.md` at repo root as a resumable task-state file for multi-session work.
- Prefers parallel batching for independent subtasks (e.g., 6 files at once).
- Docstring improvement passes should follow one-file-per-task pattern with gate reviews between batches.
- Responses must be in English.
- **Anonymize identifiable third-party content in tests**, even for regression tests that reproduce a specific production failure. Keep the STRUCTURAL shape that exercises the bug (bracket positions, character classes, regex-relevant punctuation, JSON block layout) but replace real article text, real site names, and real URLs with placeholders (e.g. `[Новостный сайт](https://news.ru/1/2/3)`). The bot's own prompts/tool-call payloads that don't identify third parties can be inlined verbatim (precedent: `FAILED_0703_TEXT`, `FAILED_0710_TEXT` inline Russian image-generation prompts verbatim). When a brief says "verbatim" for failure-log test data, default to anonymized unless the user explicitly asks for the real text. Do NOT claim "round-trip-verified identical" if you sanitized — say so explicitly so the teamlead can verify the structural shape is preserved.
- **`.opencode/memory.jsonl` is OpenCode's own auto-managed session memory store.** It is auto-appended/modified by OpenCode on every task, is expected to show as modified in `git status` during any session, and IS normally committed as part of regular flow — do NOT exclude it from commits. The rule is HANDS-OFF, not exclude-from-git: NEVER read, edit, or manually touch it (don't `cat`, don't explicitly stage, don't flag as a stray/unrelated change, don't include its contents in reports/diffs). When staging a doc/cleanup commit, just let it ride with whatever else is being committed; don't single it out.

## Task-Specific Memory Files

Full index and one-line descriptions live in [`memories/index.md`](memories/index.md) — read the relevant file before working on a subsystem. Topics covered: proxy config & lifecycle, Max Messenger API migration & webhooks, chat history & vector search, bot handlers (delete-from-user, resender, bot-answer-probability), LLM tooling & internals (use-tools filtering, tool-call healing, maxRounds limit, user-message format, messages-handler structure, shutdown state dump, empty TRUNCATED_FINAL bug), **user memories (+ v2 pre-merge review, refinement, context dedup, compaction)**, **condensed-context retrieval**, **chat-users cache**, **DB cache cleanup & cron**, **DB maintenance scripts**, **dependency-usage regression tests**, **doc-link checking + docs reorg/archive/audit**, **test-suite speedup**, **review-campaign lessons**, **skills & agents landscape audit**, codebase cleanup (Any types, dedoodization), testing & sandbox.

## DB Cache Cleanup (verified 2026-07-15)

See [`memories/db-cache-cleanup.md`](memories/db-cache-cleanup.md) — durable notes for the cache cleanup mechanism: `clearOldCacheEntries`, weekly cron + on-shutdown triggers, per-namespace TTLs, Bayes tokens cleanup, `cache_storage` exemption.

## Repo Facts And Gotchas

- `lib/utils/ttl_dict.py` provides a thread-safe TTL dict with GC, lazy expiration, and full dict API. Uses sentinel pattern for unspecified TTL vs ttl=None.
- `pathlib.relative_to()` is preferred over `str.startswith()` for path containment checks (cross-platform, handles symlinks/trailing slashes).
- `dict.setdefault()` is the canonical one-liner fix for check-then-create race conditions in CPython (GIL-protected).
- Async tests should use `async def test_...` without `@pytest.mark.asyncio`; `asyncio_mode = "auto"` handles them.
- Bot handler config-gating pattern: `if self.configManager.get("section", {}).get("enabled", False)` in HandlersManager, register before LLMMessageHandler (line ~534). Use `HandlerParallelism.PARALLEL` for most handlers.
- Chat setting access: `BaseBotHandler.getChatSettings()` returns `ChatSettingsDict` = `Dict[ChatSettingsKey, ChatSettingsValue]` — values are objects; use `.toBool()`/`.toStr()`/`.toInt()`/`.toFloat()`/`.toList()`/`.toModel()` (NOT tuple indexing). The `(value, updatedBy)` tuple shape exists ONLY at the DB-repo layer (`self.db.chatSettings.getChatSettings()`, returns `Dict[str, tuple[str, int]]`). Writes: handler `setChatSetting(..., *, user: MessageSender)` — keyword-only is `user`; repo `setChatSetting(..., *, updatedBy: int)`.
- `isBotOwner()` is on `BaseBotHandler` (not `_bot`). Mock it as `handler.isBotOwner = Mock(...)` in tests, not `handler._bot.isBotOwner`.
- `ConfigManager.get()` does NOT support dotted-path traversal -- it is plain `dict.get(key, default)`. Always use nested `.get()` calls.
- Multi-section truncation: update cumulative length after each section or all sections share the same remaining space (overflow risk).
- `newMessageHandler` does NOT gate commands. Commands are dispatched via `@commandHandlerV2` decorator and bypass the message handler chain. Per-command access checks must be in each command method (use a shared `_checkAccess()` helper).
- LLM tool registration: `self.llmService.registerTool(name, description, [LLMFunctionParameter(...)], handler=self._method)` in `__init__`. Gate with feature-enabled flag. Imports: `from lib.ai import LLMFunctionParameter, LLMParameterType`.
- LLM tool handler method naming: use `_llmTool*` prefix (e.g., `_llmToolRunSandboxCode`, `_llmToolSandboxListFiles`) so the method's role is clear without reading the registration code.
- LLM tool handler signature: `async def _llmTool*(self, extraData: Optional[Dict[str, Any]], param1, ..., **kwargs: Any) -> Dict[str, Any]`. Return a dict with `{"done": bool, ...}` — the LLM service handles JSON serialization. NEVER raise. Get chat context from `extraData["ensuredMessage"]`.
- LLM tool handlers can return dicts directly (not JSON strings). This is cleaner — no `json.dumps()`/`jsonDumps()` needed. The LLM service serializes the dict.
- `lib/ai/providers/basic_openai_provider.py`: `BasicOpenAIModel` has two image-generation transports: (1) `_generateImage()` using `chat.completions.create` with `modalities=["image", "text"]`, (2) `_generateImageViaImagesApi()` using `client.images.generate()`. Models opt into the second via `image_generation_api = "openai-images"` in `extraConfig`.
- Hook methods available for subclasses: `_getModelId()` (text models), `_getImageModelId()` (image models), `_getExtraParams()` (returns `dict(self._customParams)` — the canonical seam for per-request inference params; subclass overrides merge provider-specific defaults with `customParams`, user `customParams` wins), `_getImageRequestOptions()` (returns `dict(self._customParams)` — NO whitelist since the 2026-07-20 customParams refactor; all keys pass through), `_getClientParams()` (extra AsyncOpenAI constructor kwargs).
- `YcOpenaiModel` uses `gpt://...` URIs for text and `art://...` URIs for images -- two different URI schemes from the same provider.
- `YcOpenaiProvider._folderId` is set **before** `super().__init__()` so `_getClientParams()` (called during `_initClient()`) can access it. This ordering is critical.
- `_getClientParams()` affects ALL requests through the OpenAI client (text, images, tools), not just the API it was added for.
- `image_generation_api = "openai-images"` dispatch in `BasicOpenAIModel._generateImage()` is **generic** -- it works for any `BasicOpenAIModel` subclass, not just `YcOpenaiModel`. Old docs claimed it was YC-only; this was corrected in `docs/llm/configuration.md`.
- When production code has `isinstance(x, SomeType)` guards, mock objects in tests need `MagicMock().__class__ = SomeType` to pass them. Cleaner than constructing real SDK objects and doesn't require knowing all constructor params.
- If the user adds guards to production code and tests break, fix the tests -- don't remove the guards. The user's intent is clear: guards are there by design.
- Bot media sending: all goes through `TheBot.sendMessage()` with `attachmentList: List[Tuple[bytes, MessageType, Optional[str]]]`. No dedicated `sendPhoto/sendVideo/sendAudio/sendDocument` methods. MIME detection uses `magic.from_buffer(data, mime=True)` consistently across 6 call sites. MIME→MessageType mapping: `image/*`→IMAGE, `video/*`→VIDEO, `audio/*`→AUDIO, rest→DOCUMENT.
- `python-magic==0.4.27` is a direct pinned dependency (not optional). All imports use bare `import magic` at top level (no `try/except ImportError` guard).
- No magic numbers — extract numeric constants to module-level `UPPER_CASE` variables with a comment explaining the value (e.g., `MAX_SANDBOX_READ_FILE_BYTES = 65536  # 64 KB`).
- When handling `FileContent.content` (or any `bytes | str` union), decode only if bytes: `if isinstance(data, bytes): text = data.decode(...) else: text = data`. Don't encode str to bytes and back — it's wasteful.
- **Nested `chat_users.metadata` writes:** `setUserMetadata(isUpdate=True)` shallow-merges at the top level — a partial `{"<subKey>": {<threadId>: ...}}` wipes every other thread's entry under that sub-key. Write nested sub-dicts via direct read-modify-write through `cache.updateUserMetadata()` (or hold the `chatUserMetadataLock()` for the full RMW). See [`memories/chat-users-cache.md`](memories/chat-users-cache.md).
- **`str.isdecimal()` NOT `str.isdigit()`** to guard `int()` parsing. `isdigit()` returns True for Unicode "other digit" chars (e.g. superscript `²` U+00B2) that `int()` CANNOT parse → `ValueError`. `isdecimal()` is the precise predicate for the base-10 set `int()` accepts.
- **`mock.patch` string-target rename hazard:** renaming a module requires updating STRING-targeted `mock.patch` paths (e.g. `"internal.bot.common.handlers.user_data.asyncio.sleep"`), not just `import` statements. Grep for string-literal module paths (`"internal.bot.common.handlers.<oldName>`) after any module rename. A stale target raises `AttributeError: module '...' has no attribute '<oldName>'` at runtime.
- **Hardcoded-path assertion tests break on rename:** AST/glob-style coverage tests (e.g. `tests/test_memory_resolution_coverage.py`) with hardcoded `expectedFiles` lists break when a file is renamed — the dynamic-discovery counterpart yields the new name while the list still has the old. Audit them after any rename.
- **Test rollback-step count:** any test that rolls back N migrations to reach a historical baseline MUST bump `steps=` when a new migration is added above it (auto-discovery means no registry edit, but the count is manual). Recurring maintenance point on every new migration.
- **`expectedTables`/`requiredTables` lists:** schema-creation tests (e.g. `testSchemaCreation`, `testAllRequiredTablesExist`) hardcode table names in expected-table lists. When dropping a table, grep tests for its name in these hardcoded assertions, not just in repo usage.
- **`.discard()` over `.remove()` for set eviction:** when a set is populated by one async caller and evicted by another after an `await`, use `.discard()` — `.remove()` can `KeyError` if the element was evicted between pick and remove.
- **`MessageId(str)` accepts ANY string** (`internal/models/types.py`) — Max message IDs are arbitrary strings, so `MessageId("not-a-number")` does NOT raise. Therefore a handler `except (ValueError, TypeError): pass` fallback after `MessageId(x)` is only reachable for **non-str/non-int** types (float/list/bool/None-ish) — no `str` input ever triggers it. A string `thread_message_id` always becomes a valid root and overrides sibling scoping. When writing tests for "invalid message id" fallbacks, pass a float (e.g. `3.14`), not a junk string.
- **Embedding generation — two methods, two return shapes (don't mix):**
  - `LLMService.generateEmbedding(text, chatId=None, chatSettings=None)` **(SINGULAR, the service wrapper)** → `Optional[Tuple[str, List[float]]]` = `(modelName, vector)`. Resolves the model internally from `chatSettings[EMBEDDING_MODEL]`, rate-limits when `chatId is not None`, and SWALLOWS internal failures → returns `None` (does not raise in normal operation). Callers extract vector via `[1]`, model via `[0]`. Used by `_llmToolSearchMessages` (`chat_search.py`), `embedAndSaveMessage`, `message_preprocessor`, `user_memories`.
  - `model.generateEmbeddings(text)` **(PLURAL, the model-level method)** → `List[float]` (bare vector); raises on failure. Callers that use it resolve the model themselves via `self.llmService.getLLMManager().getModel(name)` + `model.supportsEmbedding` and read `chatSettings[EMBEDDING_MODEL]` to get `name`. Still used by the `/search` slash command (`searchCommand`) and the CRON backfill gate (`_dtCronJob`) — NOT migrated.
  - **Migration gotcha (caused a test failure 2026-07-16):** moving a caller from the plural model method to the singular wrapper changes the return shape `List[float]` → `Optional[Tuple[str, List[float]]]` AND makes the caller's explicit `getLLMManager().getModel()`/`supportsEmbedding`/`EMBEDDING_MODEL`-empty checks dead (the wrapper owns them). Tests must swap `mockModel.generateEmbeddings = AsyncMock(return_value=[...])` → `handler.llmService.generateEmbedding = AsyncMock(return_value=("modelName", [...]))`, and tests that asserted the removed model-error paths must be repurposed: `None` return → graceful degrade to filter-only (`done: True`); `side_effect=raise` → defensive `"Unable to generate query embedding"` error. Precedent for the wrapper mock in `tests/bot/common/handlers/test_chat_search.py` (`TestEmbedAndSaveMessage`, CRON tests) — set it on the `handler` fixture so `assert_not_awaited()` stays meaningful.
- **Two distinct tool-gating settings — DO NOT conflate (verified 2026-07-16):**
  - **`USE_TOOLS`** (`internal/bot/models/chat_settings.py:819`, "Можно ли использовать боту различные инструменты?") = the **LLM-tool master switch**. Read at `LLMMessageHandler._sendLLMChatMessage` (`internal/bot/common/handlers/llm_messages.py:275`) to build the chat-time `useTools` dict; when `False`, NO tools are sent to the model and the execution loop's `filteredToolNames` is empty. Per-tool exclusions in the dict: `DELETE_MEMORY` always-off; the 5 sandbox tools off when `ALLOW_SANDBOX=False`; `ADD_MEMORY`+`SEARCH_MEMORIES` off when `MEMORY_ENABLED=False`. This is the D3 chat-time gating (see `.agents/skills/add-llm-tool/SKILL.md` Site 4, `docs/llm/memories/use-tools-filtering.md`).
  - **`ALLOW_TOOLS_COMMANDS`** (`chat_settings.py:872`, "Разрешить команды использования инструментов (`/draw`, `/analyze`, …)") = the **slash-command gate** for `CommandCategory.TOOLS` (`/search`, `/users`, `/draw`, `/tarot`, `/run`, `/weather`, …), enforced ONLY at `internal/bot/common/handlers/manager.py:985` (`canProcess = chatSettings[ALLOW_TOOLS_COMMANDS].toBool() or isBotOwner`). It does NOT participate in the `useTools` dict at all.
  - **Decision 2026-07-16:** the in-tool `ALLOW_TOOLS_COMMANDS` guards in `_llmToolSearchMessages`/`_llmToolListUsers`/`_llmToolGetThread` (`internal/bot/common/handlers/chat_search.py`) were REMOVED — they were a double-gate / semantic mismatch repurposing a slash-command setting for LLM tools that `USE_TOOLS` already gates. `USE_TOOLS` is now the sole LLM-tool gate. Consequence: `USE_TOOLS=True` + `ALLOW_TOOLS_COMMANDS=False` → LLM CAN call search tools (ALLOW_TOOLS_COMMANDS now gates only slash commands). (`_llmToolGetMessagesByIds` never had the guard — pre-existing drift, now consistent.)
  - **Tool-call healing bypass note:** `_tryHealToolCall` (`internal/services/llm/service.py`) accepts on the GLOBAL registry (`toolName in self.toolsHandlers`, line ~319) — it does NOT consult `filteredToolNames` or any per-chat allowlist. But the execution loop (`service.py:806`) re-guards on `filteredToolNames`, so a `useTools`-filtered tool gets healed→"not available" error, never executes. The in-tool `ALLOW_TOOLS_COMMANDS` guard was the ONLY thing that ever stopped an ALLOW_TOOLS_COMMANDS-filtered (but useTools-allowed) tool from executing via healing — now moot since that guard is gone and ALLOW_TOOLS_COMMANDS no longer applies to LLM tools. **Post-budget interaction (`maxRounds` round-limit, added 2026-07-16):** healing and the TOOL_CALLS execution branch are gated on `not budgetExhausted`, `filteredToolNames` is cleared, and the loop terminates within one extra round — see the "LLM maxRounds round-limit" section below for the full mechanism (incl. why `tools=[]` alone is insufficient, the `roundLimitHit` flag, error-status propagation, and the steering fold-in).
- **Portable case-insensitive LIKE: `BaseSQLProvider.getLikeComparison(column, param)`** (`internal/database/providers/base.py:478`) — all 4 providers return `LOWER({column}) LIKE LOWER(:{param})`. Use for substring matching; the caller wraps the bound value as `f"%{value}%"`. Precedent: `internal/database/repositories/divinations.py:207-220` (no ESCAPE). **Caveats:** (1) NO `ESCAPE` clause on any provider → a literal `%`/`_` in user input acts as a wildcard. Portable escaping would require a NEW provider method (`ESCAPE '\'` works on SQLite/PostgreSQL but MySQL needs `ESCAPE '\\'` in the SQL text, so no single string is portable). The `user_memories.py` `tags LIKE ... ESCAPE '\\'` pattern is SQLite/PostgreSQL-only. (2) SQLite's `LOWER()` is **ASCII-only** → no Unicode (Cyrillic) case-insensitivity on SQLite; PostgreSQL/MySQL are full-Unicode. Sibling `getCaseInsensitiveComparison` is for EQUALITY (`LOWER(col)=LOWER(:param)`; MySQL uses `COLLATE utf8mb4_general_ci`). Established repo null-semantics filter idiom: `AND (:param IS NULL OR <comparison>)` so a `None` bound value short-circuits to "no filter".
- **Semantic-search test path selection** (`tests/database/repositories/test_chat_search*.py`): `sqlite-vec` is installed (v0.1.9, `requirements.direct.txt`), so `saveMessageEmbedding` dual-writes the vec0 table and the **native** vector path runs by default — the **numpy** path is skipped. To test the numpy path deterministically, stub `_nativeVectorSearch` to return `[]` (forces the fall-through). To lock in an OR-style `needsPostFilter` guard term-by-term, you need SINGLE-filter tests (a combined-filter test is structurally immune to single-term removal because the other filter keeps the OR `True`).
- **`tests/dependencies/test_sqlite_vec.py` skip-on-missing behavior** (added 2026-07-16): the file uses module-level `sqlite_vec = pytest.importorskip("sqlite_vec")` so the WHOLE module is SKIPPED (not failed) when the `sqlite_vec` package is not importable. Distinct from the separate failure mode where the wheel IS installed but its bundled native binary won't load — that path is caught by the `RuntimeError` raised inside the file's `loadVecConnection()` helper (production load path mirror). So: missing package → skip; broken binary → fail loudly (RuntimeError). Both are intentional. `numpy` is NOT importorskip-guarded (always present as a portable wheel dep) — only sqlite-vec, the genuinely environment-fragile native extension, is.

## Embedding Model-Lookup Refactor (plan APPROVED 2026-07-20)

Plan: [`docs/plans/embedding-model-lookup-refactor-v1.md`](../plans/embedding-model-lookup-refactor-v1.md) — Status **APPROVED**, all design decisions resolved, awaiting Phase 1 implementation dispatch. Decisions D1–D10 ratified.

**Current state captured by 4 parallel exploration agents (pre-refactor snapshot — will be stale once Phase 1 lands):**
- 4 embedding stores: `message_embeddings` (regular BLOB table, `migration_017`, indexed `migration_018`), `user_memories` (regular, no BLOB — provenance cols only, `migration_020`+`021`), `vec_message_embeddings_{N}` (vec0, lazy at `chat_embeddings.py:166-263`), `vec_user_memories_{N}` (vec0, lazy at `user_memories.py:1162-1186`).
- Numpy fallback in `ChatSearchRepository._semanticSearch` (`internal/database/repositories/chat_search.py:303-483`); `import numpy as np` at line 32; body 410-480 (load via `_loadEmbeddingsFromDb` 485-553 + numpy cosine). Triggered by: vec0 unsupported OR raises OR returns `[]`. Always-on safety net.
- Last additional numpy use: `user_memories.py:52` import + `:872` `numpy.linalg.norm` for query-vector norm guard (NOT a fallback).
- No `chat_messages` embedding columns today (PK `(chat_id, message_id)`, 15 cols, last recreation in `migration_013`). `message_embeddings` is a sidecar joined by the same natural key.
- Two different col-naming conventions for the same concept: `message_embeddings.{model,dimensions}` vs `user_memories.{embedding_model,embedding_dimensions}`. Both vec0 tables use `model TEXT PARTITION KEY`.
- Model name sourced from `chatSettings[ChatSettingsKey.EMBEDDING_MODEL].toStr()` (read back from setting, not model instance). Dimensions derived from `len(embedding)` at write time. `AbstractModel.getDimensions()` (`lib/ai/abstract.py:589-605`) seeded from `extraConfig["embedding_dimensions"]` or lazily probed.
- Production callers all in `internal/bot/common/handlers/{message_preprocessor,chat_search,user_memories}.py` — no `lib/` callers. Plus `scripts/clear_memory_embeddings.py` (raw SQL bypass).
- Dead-in-prod methods: `getMessageEmbedding`, `deleteChatEmbeddings` (tests only).

**Target state per the plan:**
- New `models(model_id INTEGER PK NOT NULL, model TEXT, dimensions INTEGER, created_at TIMESTAMP, UNIQUE(model, dimensions))` — **D7 INTEGER PK deviation from AGENTS.md preference #3 (TEXT UUID) is user-ratified** for compactness as vec0 partition key + O(1) cached allocation.
- New `ModelsRepository.getOrCreateModelId(model, dimensions) -> int` with process-local `{(model,dims):id}` cache + `INSERT OR IGNORE` (portability R5: needs `BaseSQLProvider.insertOrIgnore` helper — doesn't exist yet).
- `chat_messages` += `model_id INTEGER NULL` (backfilled via JOIN to `message_embeddings`→`models`).
- `user_memories` drops `embedding_model`/`embedding_dimensions`, += `model_id INTEGER NULL`.
- Drop `message_embeddings` table entirely; drop both vec0 families (lazily recreated with `model_id INTEGER PARTITION KEY`).
- `_semanticSearch` collapses from 3-rung ladder to "vec0 or `[]`".
- numpy fully retired from production code (D8); `numpy==2.5.1` removed from `requirements.direct.txt`; `requirements.txt` regenerated; `tests/dependencies/test_numpy.py` deleted.
- Single migration `migration_025_embedding_model_lookup.py` does it all (temp-table swap pattern from `migration_013`).
- **D6 (handler-layer signature stability):** repos continue to accept model NAME strings at their public boundary; resolution to `model_id` happens inside the repo. Handler call sites change zero lines for the common case. Exception: `/search` slash-command caller (`chat_search.py:~1322`) bypasses `LLMService.generateEmbedding` and must resolve explicitly (Risk R2).
- **D10 (cross-repo access):** constructor-inject `modelIdResolver: Callable[[str, int], Awaitable[int]]` into `ChatEmbeddingsRepository`/`UserMemoriesRepository`. Caveat flagged: `ChatEmbeddingsRepository` has `__slots__ = ()` at line 59 — must add `_modelIdResolver` slot at Phase 3.

**Migration precedent (the ONLY temp-table swap in the repo):** `migration_013_remove_timestamp_defaults.py` — `<name>_new → INSERT...SELECT → DROP → RENAME` in a single `sqlProvider.batchExecute([ParametrizedQuery(...)])` call. Used to remove `DEFAULT CURRENT_TIMESTAMP` from 19 tables (SQLite can't ALTER COLUMN). Migration template: `async def up(self, sqlProvider: BaseSQLProvider)` / `async def down(...)`, `def getMigration() -> Type[BaseMigration]`.

**Implementation phasing (per plan §11):** P1 new `models` repo + tests; P2 migration `025`; P3 slim `chat_embeddings.py` + `user_memories.py` + vec0 DDL; P4 drop numpy entirely (chat_search.py + user_memories.py:872 + requirements.direct.txt + test_numpy.py); P5 handler wiring + script + remaining tests; P6 docs sync (database-schema.md, database-schema-llm.md, llm/architecture.md, design/vector-search-native.md, CHANGELOG.md).

**Verification (when implementation lands):** test-rollback step counts bump (any test rolling back N migrations must bump `steps=` to N+1 for migration_025); `expectedTables`/`requiredTables` hardcoded lists in schema-creation tests need `models` added and `message_embeddings` removed; `test_numpy.py` deleted; `rg "import numpy" internal/ lib/` returns 0 matches.


## Opencode Slash-Command Mechanism

- Slash-commands are markdown files in a `commands/` dir. Filename `<name>.md` → `/<name>`.
- YAML frontmatter fields observed: `description`, `agent` (routes to a named agent from `agents/`), `subtask` (bool). Body = free-form prompt; `$ARGUMENTS` = args passed at invocation.
- Global commands live in `~/.config/opencode/commands/` (2 existing: `caveman-compress.md`, `caveman-review.md`). Repo-local commands live in `.opencode/commands/` (3 existing):
  - `changelog` — drafts a `CHANGELOG.md` entry from the current diff (see [`changelog.md`](changelog.md)).
  - `refine-memory` — extracts task-specific deep-dive sections from this file into [`memories/`](memories/index.md) to keep the main file compact; routed to `teamlead` with `subtask: true`.
  - `review-large` — runs the methodology in [`reviewing-large-changes.md`](reviewing-large-changes.md) for reviewing diffs >24 files (characterize → batch → per-batch review → integration → consolidated findings, stopping before remediation); routed to `teamlead`.
- Repo `.opencode/opencode.json` sets `default_agent: "teamlead"`; per-subagent model tiers under `agent`. Global config is `~/.config/opencode/opencode.jsonc`.
- Commands are discovered by filename, NOT registered via any `command`/`commands` key in config.
- **`make check-docs` excludes `.opencode/`** (`scripts/check_docs.py:70` `_EXCLUDED_DIR_NAMES`) — slashcommand files and agent configs under `.opencode/` are NOT validated by the markdown link checker. Manually verify any internal links in `.opencode/commands/*.md` against the actual target files; do not rely on `make check-docs` for them.
- **`docs-writer` cannot edit/write under `.opencode/**` or `.agents/**`** (explicit denies in `.opencode/agents/docs-writer.md` on top of the `*.md`/`*.txt` allow). Slashcommand files MUST be written by `software-developer`; `docs-writer` can still edit `docs/llm/teamlead-memory.md`, `docs/llm/memories/index.md`, and `CHANGELOG.md`.
- CHANGELOG.md exists at repo root (created 2026-07-15); `changelog` is checked off in `TODO.md`'s `# Done:` block. The full Keep-a-Changelog process spec lives at [`docs/llm/changelog.md`](changelog.md); `AGENTS.md` carries the compact summary.

## Changelog Process (embedded 2026-07-15)

- `CHANGELOG.md` at repo root uses Keep a Changelog: `## [Unreleased]` (always present, even empty) + dated sections. First section is a one-time `## Initial State - 2026-07-15` baseline snapshot (sanctioned exception documented in `docs/llm/changelog.md` §"Initial baseline") — NOT a semver release.
- Canonical process spec: `docs/llm/changelog.md` (moved from `docs/plans/changelog-process.md`). `AGENTS.md` has a compact `## Changelog` summary; the two must stay consistent (canonical is authoritative).
- **Entry style**: declarative, past tense, start with the thing that changed (NOT "Added"/"Fixed" — the category header conveys that); one capability per line; name the user-facing surface (command/config key/tool/path). NEVER imperative ("Add X").
- **When to entry**: new feature/capability/config/command/API, bug fix, behavior change, schema/data migration, docs-only-when-new-feature.
- **When NOT**: style/formatting fixes, internal refactors w/o user-visible effect, doc-only tweaks (unless new feature), dependency bumps w/o behavioral change, test-only changes.
- **Triggers (3, all active)**: (1) teamlead-auto — docs-sync phase + Self-Verification Checklist require a `CHANGELOG.md` `[Unreleased]` entry for user-visible changes (`.opencode/agents/teamlead.md`); (2) `/changelog` slash-command (`.opencode/commands/changelog.md`, `agent: software-developer`, `subtask: true`, non-interactive — drafts from diff, or `cut <X.Y.Z>` for release); (3) `update-project-docs` skill (`.agents/skills/update-project-docs/SKILL.md` Step 6) — CHANGELOG mandatory for user-visible, root `README.md` staleness check conditional. `docs-writer` loads this skill, so docs-writer dispatches cover CHANGELOG automatically.
- **Release cut**: rename `## [Unreleased]` → `## [X.Y.Z] - YYYY-MM-DD`, add fresh empty `## [Unreleased]` above. semver (patch/minor/major). `/changelog cut <version>` does this.
- `/changelog` command is non-interactive (subtask): on ambiguous diff it makes a best-effort decision + states the assumption (never blocks/asks); `cut` w/o version aborts cleanly with guidance.

## Config & Tier System

- **Config merge order for prod-telegram**: `00-defaults` → `common` → `prod` → `prod-telegram`. Deep-recursive merge in `ConfigManager._mergeConfigs()`: nested dicts merge recursively, scalars overwrite. Files within a dir sorted alphabetically.
- **`_loadConfig()` behavior**: starts from `config.toml` (if exists), then merges each config dir's TOML files in order. Parse/merge errors now cause `sys.exit(1)` with `logger.exception()` logging the failing file path (2026-06-12 fix — previously errors were silently caught and the bot continued without that file's overrides). Scan errors in `_findTomlFilesRecursive()` are also fatal; only non-existent/non-directory paths skip silently.
- **`tomli` rejects duplicate keys**: duplicate keys in a TOML table cause `tomli.load()` to raise. Before the fix, this was silently swallowed. Common footgun: TOML has no compile-time check for accidental duplicate keys.
- **Tier resolution** (`BaseBotHandler.getChatTier()`, `base.py:339-357`): checks `PAID_TIER` first (only if `PAID_TIER_UNTILL_TS >= time.time()` — default is `0`, so always expired), then falls back to `BASE_TIER`. If neither is in per-chat DB settings, falls back to `[bot.defaults].base-tier` (which chat-type defaults override: `free-personal` for private, `free` for group).
- **Defaults loading** (`HandlersManager.__init__`, `manager.py:392-421`): loads `[bot.defaults]` into cache key `"None"` (pre-populated with empty-string defaults for every `ChatSettingsKey`), then `[bot.{type}-defaults]` into cache keys `"private"`/`"group"`/`"channel"`, then `[bot.tier-defaults.{tier}]` into cache keys `"tier-{tier}"`.
- **Settings merge** (`BaseBotHandler.getChatSettings()`, `base.py:191-306`): global defaults → chat-type defaults → tier-specific defaults → per-chat DB settings (filtered by tier).
- **`[bot.tier-defaults.friend]`** in `configs/common/01-bot-defaults.toml` only has `allow-sandbox = true` — NO `chat-model` or other model overrides. Falls through to `[bot.defaults]`. Same for `bot-owner` tier.
- **Tier hierarchy** (`ChatTier` enum, `chat_settings.py:43-61`): `BANNED(1) < FREE(2) < FREE_PERSONAL(3) < PAID(4) < FRIEND(5) < BOT_OWNER(6)`. `isBetterOrEqualThan()` uses `getId()` comparison.
- **Common footgun**: setting `paid-tier` on a chat without a future `paid-tier-untill-ts` — the paid-tier check fails silently and falls back to `base-tier`.

## Test Mocking: Chat Settings Must Be Complete Dicts

- Production code accesses `chatSettings[KEY].toBool()` via direct subscript, never `.get()` with a default. Test mocks that return sparse `ChatSettingsDict` cause `KeyError` for any key the production path reads.
- `_makeChatSettings()` helpers must include every `ChatSettingsKey` that the production path accesses. When adding a new gate check in production (e.g., `REGENERATE_EMBEDDINGS`), the test helper must be updated to include it.
- `test_cron_no_enabled_chats` had a second-order bug: the assertion used a stale key (`REGENERATE_EMBEDDINGS`) that didn't match the current production query (`EMBEDDINGS_ENABLED`). When production queries change, test assertions must follow.

## Reviewing Large Changes

See [`docs/llm/reviewing-large-changes.md`](reviewing-large-changes.md) -- methodology for reviewing changes exceeding the single-pass budget of the `code-reviewer` agent (>24 files). Covers pre-review characterization, batching by feature domain, per-batch review with parallel execution, integration pass, and remediation workflow. Created 2026-06-28.

## User Memory V2 Pre-Merge Review (2026-07-14, in progress)

See [`memories/user-memory-v2-review.md`](memories/user-memory-v2-review.md) — full pre-merge review campaign for the 140-file `user_data`→`user_memories` feature branch: pre-review state/batching plan + post-review durable contracts/invariants established.

## Large Review Campaign Lessons (2026-06-28)

See [`memories/large-review-campaign.md`](memories/large-review-campaign.md) — durable lessons from the 78-file/6-batch parallel review campaign: batch sizing (15–20 sweet spot), parallel dispatch mechanics, integration pass for cross-batch drift, per-batch fix verification.

## Review-Fix Round Lessons (2026-07-01)

See [`memories/review-fix-lessons.md`](memories/review-fix-lessons.md) — durable lessons from the 2026-07-01 review-fix round on branch `max-v2`: single-developer many-fix dispatch, `logger.exception` misuse pattern, `except Exception` narrowing, config-defaults alignment, doc drift from review fixes.

## Teamlead Workflow Lessons

- The `code-reviewer` subagent may return empty results in some sessions. If it does twice, fall back to `general` agent for the review — use the same prompt structure, just route through `general`.
- Parallel `software-developer` edits to the same file cause conflicts. Always reconcile with a follow-up `software-developer` pass after parallel batches on the same file.
- The teamlead prompt grants direct read/edit/write access only for this file; all substantive project work must still be delegated.
- For multi-file docstring passes: batch by complexity (init files + small -> medium -> large -> manager), run Gate 1 per-batch, then Gate 2 whole-work.
- When code reviewers flag a Returns: format inconsistency, propagate the fix to ALL files in that batch (or the entire library) at once to avoid repeat reviews.
- Explicit type prefix format in Returns: sections (e.g., `int: Number of sessions`) is WRONG for this project -- use plain descriptions.
- Docstring correctness matters: always verify that docstring descriptions match actual implementation (not what the method is "supposed" to do).
- When fixing many small, independent issues from review documents: first explore thoroughly to determine which are already fixed, then batch independent fixes into parallel `software-developer` tasks (group by file to avoid conflicts), then do a single Gate 2 whole-work review. Per-subtask Gate 1 reviews are excessive for single-line fixes.
- Always verify the exploration phase -- several candidate fixes may already be present from prior sessions. Avoid re-fixing fixed issues.
- When the same fact appears in a focused doc and in handler/class docstrings, update both surfaces explicitly; one does not propagate to the other.
- When a `software-developer` subagent returns empty twice for the same task, it likely hit the ~60 step budget. Switch approach: either give the user exact instructions (before/after code) and let them apply it, or try the `general` agent. For truly tiny edits (<10 lines), the brief should be absolutely minimal.
- Subagents may auto-commit their work (commit messages like `Fix some issues`). When this happens, `git diff HEAD` will not show those changes. For whole-work reviews, use `git diff <base-commit>..HEAD` to capture everything.
- For multi-phase implementation from a design doc: exploration first to verify assumptions (code has drift), then implement foundation phase, review it, then wire consumers + config, review again, then docs, then whole-work review. Parallelize config changes with implementation phases when possible.
- When subagents fail with `ProviderModelNotFoundError`, check the `model:` field in each agent's `.md` file and in `.opencode/opencode.json` -- the `standard` model may not be provisioned while `cheap`/`smart`/`smartest` are.
- The `explore` subagent (model: `cheap`) and `code-reviewer` (model: `smart`) are reliable for read-only work; `software-developer` needs `standard` model to be functional.
- **Rename propagation:** after a module/symbol rename, run `rg "<oldSymbol>\b" internal/ docs/ tests/` and propagate to docstrings/comments/prose in LIVE files; leave `docs/plans/*`, `docs/archive/*`, and superseded-banner docs as historical. String-targeted `mock.patch` paths + AST/glob coverage tests are the two sneaky leak surfaces (see Repo Facts above).
- **Concurrent-session hazard:** two opencode sessions editing the same production file clobber each other's regions repeatedly. Ensure single-session before merge; a regression test that pins the contested invariant (e.g. media-only embedding) catches the regression.
- **Parallel dev agents MUST have disjoint file sets** — grep-driven "cleanup" agents are especially prone to touching files outside their intended scope. Concurrent `software-developer` agents that both run `make test`/`make lint`/`make check-docs` also see each other's INTERMEDIATE working-tree state → their cross-phase pass/fail verdicts are UNRELIABLE; do a fresh SERIAL verification pass after all parallel agents finish.
- **Scripts have tests** — `tests/scripts/test_*.py` is the established pattern (sibling tests for `prune_unknown_chat_settings.py`, `clear_memory_embeddings.py`, etc.). New scripts under `scripts/` should get a corresponding test file.
- **Docs-only change workflow:** `make lint` is the only gate needed (black/isort are no-ops on `.md`); no `make test`. Historical/plan/archived docs are frozen snapshots — update only LIVE docs.

## Test Suite Performance Profile (2026-07-12, measured)

See [`memories/test-suite-speedup.md`](memories/test-suite-speedup.md) — durable notes from the 2026-07-12 test-suite profiling + speedup effort (107s → 38.17s, −64.3%): profile findings, fake-clock + no-op asyncio.sleep patterns, unittest/pytest fixture-interaction gotchas, flagged-but-not-fixed items. Merges the diagnostic phase (this section) with the implementation phase (`Test Speedup IMPLEMENTED` section below) into one continuous narrative.

## Test Speedup IMPLEMENTED (2026-07-12): A+B applied, result 107s → 38.17s (−64.3%)

See [`memories/test-suite-speedup.md`](memories/test-suite-speedup.md) — implementation/outcome half of the merged speedup narrative (full-suite 38.17s, two reusable patterns: fake-clock for timing-assertion tests, no-op `asyncio.sleep` for pacing tests; unittest/pytest fixture-interaction gotchas; flagged-but-not-fixed WIP).

## Configs Tracking Gotcha (2026-07-04)

- **`configs/common/` is gitignored.** `.gitignore` line 4 is `/configs/*` with only `!/configs/00-defaults` whitelisted. So `configs/common/01-bot-defaults.toml` (and any other non-`00-defaults` config dir) is a **local deployment overlay, NOT version-controlled**.
- **All tier-defaults live only in the gitignored overlay.** `[bot.tier-defaults.banned]`/`free`/`free-personal`/`friend` (including the friend-tier `allow-sandbox = true`) exist ONLY in `configs/common/01-bot-defaults.toml`. The tracked `configs/00-defaults/bot-defaults.toml` has only an empty `[bot.tier-defaults.free]`.
- **Implication:** any tier-default that must ship with the code (e.g. friend-tier `memory-refinement-enabled = true`) will NOT propagate via git under the current model — it's a per-deployment manual overlay step, same as `allow-sandbox`. This is by design (configs are deployment-specific). Verify with `git check-ignore -v <path>` and `git ls-files configs/`.
- Only `configs/00-defaults/*` is tracked. New tracked config files go there.

## CI / `make ci` (added+consolidated 2026-07-16)

- **`.sourcecraft/ci.yaml`** is the CI definition. Its single cube's `image:` is `docker.io/library/alpine:3.24` and its `script:` is ONE entry: `sh scripts/ci.sh`.
- **`scripts/ci.sh` is the SINGLE SOURCE OF TRUTH** for the in-container CI script (apk deps → `make venv-alpine` → `make install` → pip `packaging` fix → `make check` → `make test`). It starts with `set -eu` to preserve abort-on-first-failure — sourcecraft previously got that from 6 separate `script:` entries, so collapsing to one script made `set -e` MANDATORY (without it a mid-script failure would be masked by the last command's exit code). READ THE FILE for the authoritative apk package list / step order; do NOT re-inline that sequence here or anywhere else — re-inlining re-creates the drift vector this consolidation removed.
- **`make ci`** (Makefile) reproduces CI locally in the SAME Alpine container. Design: `docker run --rm -v "$(CURDIR):/src:ro" $(CI_IMAGE) sh -c 'set -eo pipefail && tar-copy /src→/app (excluding venv/.git/__pycache__) && rm -rf /app/venv && cd /app && sh scripts/ci.sh'`. The Makefile's outer `set -eo pipefail` guards the `tar | tar` staging copy (pipefail matters THERE, for the pipe); the 6 CI steps run inside scripts/ci.sh under its own `set -eu` (no pipes in the script, so no pipefail needed there).
- **Host-safety is the load-bearing design decision:** repo bind-mounted READ-ONLY, copied into a CONTAINER-LOCAL `/app`; CI script runs there; host `./venv` NEVER touched. Reason: the Makefile's `venv`/`venv-alpine`/`install`/`lint` targets key their up-to-date check on a LITERAL file/dir named `venv` in cwd (NOT on `$(VENV_PATH)`), so the verbatim `make venv-alpine && make install` REQUIRES `./venv` to resolve in the container's cwd — a RW bind mount would clobber the host macOS venv with musl binaries. Overriding `VENV_PATH` to a non-`./venv` path does NOT work (the `venv` target's skip-logic checks for a file literally named `venv`, so `make install` would recreate the venv WITHOUT `--system-site-packages`, losing `py3-onnxruntime`). Read-only-mount+copy-in sidesteps all of this.
- **The "ci.yaml calls make ci" idea is INVALID** — ci.yaml's cube already runs INSIDE an Alpine container, so that would be docker-in-docker. The correct unification (now done) is a shared `scripts/ci.sh` invoked by both.
- **Residual duplication (accepted):** the image tag `docker.io/library/alpine:3.24` still appears in BOTH ci.yaml's `image:` field AND the Makefile's `CI_IMAGE` var (structurally different surfaces — YAML field vs make var; can't share without fragile YAML parsing in make). Single stable token; the two MUST be kept in sync manually. The part that actually drifts (apk list + step order) is now unified in scripts/ci.sh.
- **Trade-off of consolidation:** collapsing ci.yaml's 6 `script:` entries into one `sh scripts/ci.sh` loses sourcecraft UI per-step pass/fail attribution (a mid-script failure now reports as a generic scripts/ci.sh non-zero + ash line context). Accepted in exchange for no-drift.
- Makefile/shell/yaml edit gotcha: recipe indentation must be literal TABs; `make format`/`make lint`/`make test` target Python and do NOT validate Makefile/shell/yaml (and risk reformatting unrelated WIP). For such changes verify with `make -n <target>` (dry-run; catches "missing separator" tab bugs), `sh -n scripts/ci.sh` (shell syntax), and `make help`. `CI_IMAGE` uses plain `=` (hard-pin intended).
- `make ci` is dev tooling → NO CHANGELOG entry (per `docs/llm/changelog.md` skip rules). Doc surfaces carrying the `make ci` line ("; needs Docker"): `AGENTS.md` (Run/dev commands block), `README.md` (Development section), `docs/developer-guide.md` (### Make Commands block), plus the Makefile `help` target.

## LLM Tool-Call Healing (internal/services/llm/service.py) — implemented 2026-07-15

See [`memories/llm-tool-call-healing.md`](memories/llm-tool-call-healing.md) — durable notes for the tool-call healing subsystem: `_tryHealToolCall` orchestrator + 5 matchers (JSON-fence, `<tool_call>`, TOOL_CALL_START, `[name]{json}`, broken-known-tool fallback: as of 2026-07-19 scans ALL brackets via finditer and accepts at edge OR when the suffix is a fenced JSON params block (`hasJsonParams`), fixing two root-cause misses — wrong-bracket matching when a markdown link appears earlier, and over-strict edge constraint; same date: JSON-fence and `<tool_call>` matchers also accept `"function"` key as tool-name fallback when `"name"` is absent/empty), `LLMToolCall.errorMessage` consumer-audit gotcha, failure-log JSONL corpus.

## LLM maxRounds round-limit (`generateTextViaLLM`) — added 2026-07-16

See [`memories/llm-max-rounds.md`](memories/llm-max-rounds.md) — durable notes for the `maxRounds` budget/round-limit feature: `budgetExhausted` gates (tools=[] alone insufficient — must also clear `filteredToolNames` + gate healing + gate TOOL_CALLS execute-branch), `ModelRunResult.roundLimitHit` flag, steering fold-in, `internal/services/llm/constants.py` layering.

## LLM customParams Refactor (lib/ai, 2026-07-20)

`AbstractModel` (and every concrete model/provider) takes `customParams: Optional[Dict[str, Any]] = None` instead of the old explicit `temperature: float` ctor arg. Stored as `self._customParams: Dict[str, Any]` (defensive copy). `DEFAULT_TEMPERATURE = 0.5` module constant in `lib/ai/abstract.py` is the fallback when the dict doesn't carry `temperature`.

**Architecture (LOCKED):**
- **5 concrete model classes** inherit from `AbstractModel`: `BasicOpenAIModel` (with `YcOpenaiModel`, `OpenrouterModel` subclasses), `YcAIModel` (direct), `FastembedModel` (direct).
- **5 concrete provider classes** inherit from `AbstractLLMProvider`: `BasicOpenAIProvider` (abstract base; `YcOpenaiProvider`, `OpenrouterProvider`, `CustomOpenAIProvider` subclasses), `YcAIProvider` (direct), `FastembedProvider` (direct).
- Per-request param flow: `_getExtraParams()` base returns `dict(self._customParams)` — this is THE seam for inference params. Three text-generation sites in `basic_openai_provider.py` build `params = {...}` then `params.update(self._getExtraParams())` (last-wins).
- Subclass `_getExtraParams()` overrides MERGE: shape is `{**providerDefaults, **super()._getExtraParams()}` so user `customParams` wins. Example: `OpenrouterModel` returns `{"extra_headers": {...}, **super()._getExtraParams()}`.
- `_getImageRequestOptions()` returns `dict(self._customParams)` — NO whitelist (whitelist removed 2026-07-20). All `customParams` keys are sent to the OpenAI Images API; caller's responsibility to use keys valid for the transport.
- `YcAIModel._getModel(**configOverrides)` text path: `kwargs = dict(self._customParams); kwargs.update(configOverrides)`. Image path: same seed, then YC-specific `mime_type`/`width_ratio`/`height_ratio`/`seed` from `self._config` override customParams, then `configOverrides` win. Structured-output override at `yc_sdk_provider.py` uses `min(self._customParams.get("temperature", DEFAULT_TEMPERATURE), 0.3)`.
- `FastembedModel` passes `**self._customParams` directly to `TextEmbedding(...)` — `_CONSUMED_EXTRA_KEYS` filter is GONE. Fastembed library kwargs (cache_dir, threads, max_length, etc.) now live under `customParams.*` in TOML.
- `LLMManager._initModels` reads `customParams=modelConfig.get("customParams", {})` from per-model TOML. Still also passes the whole `modelConfig` as `extraConfig` (capability flags + provider wiring).
- `getInfo()` returns `"customParams": dict(self._customParams)` (defensive copy on read too). The `temperature` key is GONE.
- `dev_commands.py` `/models` command: i18n label `"customParams": "Кастомные параметры"`; display loop renders the dict via `utils.jsonDumps(v, indent=2)` (same treatment as the `"extra"` key).

**TOML shape (under `configs/00-defaults/*-models.toml`):** dotted-key form `customParams.temperature = 0.3`, NOT nested table headers. Image-API keys (`size`, `quality`, `n`, `output_format`, `moderation`) flatten into `customParams.*` (the old `[models.models.X.image_options]` sub-table is gone). Fastembed TOML has no `customParams` block at all if there are no library kwargs.

**Test patterns:** ctor `Model(..., customParams={"temperature": X})` (not `temperature=X`); attribute read/write via `model._customParams["temperature"]`; on `Mock(spec=AbstractModel)`, use `model._customParams = {"temperature": X}` (the `temperature` attribute is rejected by spec-restriction). Import `DEFAULT_TEMPERATURE` from `lib.ai.abstract` for fallback reads.

**Gitignored overlay configs to migrate manually (NOT in `configs/00-defaults/`):** `configs/common/01-opencode-go.toml` (8 entries), `configs/common/00-config.toml` (1 entry), `configs/prod/01-ollama.toml` (2 commented). User handles these per-deployment.

## LLM User-Message Format (verified 2026-07-11)

See [`memories/llm-user-message-format.md`](memories/llm-user-message-format.md) — durable notes for the LLM user-message JSON format: `EnsuredMessage.formatForLLM` JSON branch + falsy-value dropping, `chat-prompt-suffix` enumeration on the `BOT_OWNER_SYSTEM` settings page, ADR-018/019 render entry points, `CHAT_PROMPT`/`CHAT_PROMPT_SUFFIX` as `ChatSettingsKey` enum values.

## LLM Messages Handler Structure (verified 2026-07-05)

See [`memories/llm-messages-handler.md`](memories/llm-messages-handler.md) — durable anchors for `internal/bot/common/handlers/llm_messages.py` (`_sendLLMChatMessage` signature + JSON-unwrap gate, `handleReply`/`handleMention`/`handleRandomMessage` call sites, abstention sentinel INVARIANT, `<media-description>` extraction, `ModelMessage`/`getThreadByMessageForLLM`/`EnsuredMessage.__slots__` gotchas, chat-settings symbol locations, conftest fixtures).

## Docs Archive Layout (2026-07-04)

- `docs/plans/` holds active/retained design refs only. After the 2026-07-20 addition of `embedding-model-lookup-refactor-v1.md` it contains 3 files: `python-sandboxing-v1.md` (retained design ref for `lib/sandbox/`, status `implemented`), `llm-empty-truncated-final-handling-v1.md` (status `PARTIALLY IMPLEMENTED` — Option B handler-half shipped at `llm_messages.py:394`, Option A + `bot.py` empty-string guard + regression tests still pending), and `embedding-model-lookup-refactor-v1.md` (status `APPROVED` 2026-07-20, all design decisions resolved, awaiting Phase 1 implementation dispatch).
- `docs/design/` holds 2 retained docs: `markdown-specification.md` (living grammar spec) and `vector-search-native.md` (forward-looking pgvector/MySQL/SQLink contract; SQLite path implemented).
- `docs/database-multi-source.md` (at docs/ root, NOT in plans/) is the relocated operational reference for the multi-source DB architecture (was `docs/plans/database-multi-source-configuration.md`).
- `docs/archive/plans/README.md` and `docs/archive/design/README.md` are the authoritative indexes of archived docs with one-line descriptions. Update them when archiving new docs.
- Frozen historical session/review snapshots live under `docs/archive/llm-sessions/` and `docs/archive/review/` (relocated from `docs/llm-sessions/` and `docs/review/` on 2026-07-04). They retain old `docs/plans/...`-style internal paths intentionally — they are snapshots, not active cross-references. Do not rewrite their content.

## Docs Reorg Lessons (2026-07-04)

See [`memories/docs-reorg-lessons.md`](memories/docs-reorg-lessons.md) — durable lessons from the 2026-07-04 docs bulk-reorg: sibling-relative-link gap inside moved files, code-doc references in `*.py` docstrings + migration modules + `tests/**` golden-doc files, config-comment doc-path references, status/scope/phase header reconciliation. (`lib/` is currently clean; hotspots are `internal/**/*.py` ~16 refs + `tests/**` ~6 refs.)

## Documentation Audit Lessons (2026-06-28)

See [`memories/documentation-audit.md`](memories/documentation-audit.md) — durable notes from the 2026-06-28 documentation audit: drift-pattern taxonomy (line numbers / counts / method names / enum values / DDL phantoms), highest/medium/low-drift doc lists, fix-all-files-at-once rule.

## Skills & Agents Landscape Audit (2026-07-11)

See [`memories/skills-agents-audit.md`](memories/skills-agents-audit.md) — durable notes from the 2026-07-11 audit: inventory (8 project skills, 4 global, 7 custom agents), identified gaps + ROI ranking, session outcomes (getChatSettings drift resolved across 9+ surfaces, code-reviewer/docs-writer permission hardening, `make check-docs` shipped, add-handler ↔ add-llm-tool bidirectional cross-ref).

## Dependency-Usage Regression Tests (2026-07-15, COMPLETED)

See [`memories/dependency-usage-tests.md`](memories/dependency-usage-tests.md) — durable notes for the `tests/dependencies/` dep-usage regression test suite (6 files, 79 tests): PURE/EXTERNAL/MIXED/DEV classification, version-pinning convention (`importlib.metadata.version()` + native probes), philosophy (pin deterministic outputs / TOLERANCE for implementation-defined), behavioral findings (dateutil month-first, html-to-markdown `.content`, numpy tie-breaking, sqlite-vec DELETE shapes).

## user-memory-v2 Pre-Merge Review (2026-07-14)

See [`memories/user-memory-v2-review.md`](memories/user-memory-v2-review.md) — post-review half of the merged campaign narrative: 2 Critical + ~15 Important + ~25 Recommend + ~15 Nit found (all fixed); durable contracts (`CondensingDict.messageCount` counts ALL processed positions, per-message memory injection, `getThreadByMessageForLLM` dedup accumulator invariant, `condenseContext.batchLength` floor at 1, `MAX_SQL_VARIABLES=900`, `_normalizeTags` strips `"`/`\`); user-preference + process-lessons reinforcement.

## Full /docs Audit (2026-07-18, COMPLETED)

End-to-end audit of all 85 files under `/docs/` (excluding `docs/archive/`): 36 memories + 12 `docs/llm/` non-memory + 8 `docs/` root + 29 plans/designs/examples/templates/other. Outcomes: ~78 FIX, ~6 KEEP, 13 ARCHIVE moves (12 in Phase 2 + 1 in Phase 3d Wave 9 `condensing-prompt-tool-param.md` + 1 in Phase 3d Wave 11 `max-bot-client-generation-brief.md`). Gate 2 review closed cleanly. `make check-docs` green (106 files / 1615 links / 0 broken). Process: 1 inventory agent → 1 bulk-archive agent → 5 waves of 8 memory audits (Phase 3a) → 2 waves of 6 `docs/llm/` non-memory (Phase 3b) → 1 wave of 8 `docs/` root (Phase 3c) → 2 waves of 11+18 plans/examples/templates/other (Phase 3d) → 3 parallel reconciliation agents (Phase 4) → 1 whole-work review + 1 fix dispatch + 1 re-review (Phase 5). 8 files/wave was the right batch size; 2 of 6 high-drift `docs/llm/` files needed re-dispatch (libraries.md, configuration.md — step limit). Per-file agents were strict one-file-only; cross-file consistency was the explicit Phase 4+5 gap to close.

### Recurring drift patterns (for future audits — apply repo-wide grep verification)

1. **`_persistMemoryEntry` → `_runSingleRefinement` inlined cursor-persist** — method removed (inlined into `_runSingleRefinement` at `user_memories.py:1356-1374` under `cache.chatUserMetadataLock()`); class `UserDataHandler` → `UserMemoriesHandler`; file `user_data.py` deleted (now `user_memories.py`). Historical-pointer convention: *"`_runSingleRefinement`'s inlined cursor-persist (formerly `_persistMemoryEntry`)"*.
2. **`chatMessages.searchChatMessages` → `chatSearch.searchChatMessages`** — repository split; `chat_search.py` is a separate repo, accessed as `db.chatSearch`. Test: `grep -rn 'chatMessages.searchChatMessages' docs/` (outside `docs/archive/`) must return 0.
3. **`excludeMemoryIds` is OPTIONAL, not REQUIRED** — only `cache` is required keyword-only; `excludeMemoryIds: Optional[Set[str]] = None` at `ensured_message.py:1073, 1203, 1275` (3 sites). The "pyright enforces both" claim is false — pyright does NOT enforce optional-with-default.
4. **`handleRandomAnswer` → `handleRandomMessage`** — method at `llm_messages.py:790`.
5. **Repository class merges**: `DivinationLayoutsRepository` → `DivinationsRepository` (layout CRUD was merged in; `db.divinations` accessor); `CommonRepository` → `CommonFunctionsRepository`. Test: `grep -rn -E '(CommonRepository|DivinationRepository|DivinationLayoutsRepository)\b' docs/` (outside `docs/archive/` + clarifying-mention narrative) must return ~0.
6. **`[database.sources.*]` → `[database.providers.*]`** — config schema rename; `DatabaseManagerConfig.providers` is the live shape (`configs/00-defaults/00-config.toml`).
7. **SQLink is a REMOTE-DB HTTP client, NOT SQLite with async** — required kwargs are `url`/`user`/`password`/`database`. The `dbPath` kwarg belongs to `SQLite3Provider` only. Don't conflate them in multi-source examples. SQLink's `readOnly` is server-controlled (`db.access == "ro"`), not a client-side flag.
8. **Handler chain ordering** — full list (verified `manager.py:478-612`): 9 always-on + 3 Telegram-only (`DeleteFromUserMessageHandler` at position 10, `ReactOnUserMessageHandler`, `TopicManagerHandler`) + 6 config-gated (`MessagePreprocessorHandler`, `SpamHandler`, `ChatSearchHandler`, `ResenderHandler`, `SandboxHandler`, `DivinationHandler`) + custom-loader + `LLMMessageHandler` (MUST BE LAST — appended after conditional/custom handlers). Don't forget `DeleteFromUserMessageHandler` (registered before `ReactOnUserMessageHandler`).
9. **Method renames** — `saveChatUser`→`updateChatUser`, `saveChatInfo`→`updateChatInfo`, `saveChatTopic`→`updateChatTopicInfo`, `getMessages`→`getChatMessagesSince`, `addMessage`→`saveChatMessage`, `saveMediaAttachment`→`addMediaAttachment`, `saveSpamMessage`→`addSpamMessage`, `saveHamMessage`→`addHamMessage`, `saveDelayedTask`→`addDelayedTask`, `getCache`/`setCache`→`getCacheEntry`/`setCacheEntry`, `getChatSummarizationCache`/`setChatSummarizationCache`→`getChatSummarization`/`addChatSummarization`, `markDelayedTaskDone(taskId)`→`updateDelayedTask(id, isDone)`. Pattern: `save*`/`get*` (legacy) → `update*`/`add*`/descriptive (current). Always grep current code before trusting doc method names.
10. **`HandlersManager.injectBot` was renamed to `initialize`** — `BaseBotHandler.injectBot` (`base.py:178`) is now the narrower method that just sets `self._bot`. Don't conflate them in refactor proposals.
11. **`_sendLLMChatMessage` returns `LLMReplyOutcome` StrEnum** (3 members: SENT/ERROR/SKIPPED_BY_MODEL), not `bool`. Span `llm_messages.py:221-443`. `SKIPPED_BY_MODEL` returned by handler-level empty-guard at L394 (Option B handler-half of `llm-empty-truncated-final` fix).
12. **`ModelResultStatus` has 8 values**: UNSPECIFIED, PARTIAL, TRUNCATED_FINAL, FINAL, CONTENT_FILTER, TOOL_CALLS, UNKNOWN, ERROR (`lib/ai/models.py:923-950`). `ERROR_STATUSES = {UNSPECIFIED, CONTENT_FILTER, UNKNOWN, ERROR}` (excludes TRUNCATED_FINAL, PARTIAL, FINAL, TOOL_CALLS). Older docs fabricated `TIMEOUT`/`EMPTY` — they don't exist.
13. **`RANDOM_ANSWER_PROMPT` wiring** — `ChatSettingsKey` at `chat_settings.py:334`; entry at `:701-707` (page `BOT_OWNER_SYSTEM`); TOML default at `bot-defaults.toml:227-237`; used in `handleRandomMessage` at `llm_messages.py:865-874` (thread path, slice-rebuild) and `:878-887` (non-thread path).
14. **`HandlersManager` line refs drifted massively (~200+ lines)** since early 2026: class 177→382, `__init__` 185→416, `self.handlers` list 249→478, `awaitStepDone` 110→236, `messageProcessed` 149→330, `injectBot`/`initialize` 389→703, `shutdown` 430→738. **Always re-locate by symbol before trusting line numbers.**
15. **`lib/ext_modules/grabliarium/tests/` is sanctioned-collocated** — vendored subpackage with its own `pyproject.toml`/tests. **AGENTS.md L127 carve-out added 2026-07-18** (Phase 10 follow-up); `docs/llm/testing.md` also documents it.
16. **Counts as of 2026-07-18**: 36 memories + `memories/index.md` = 37; ADR count = 19 (ADR-001..019); `ToolName` StrEnum = 22 members; `registerTool` call sites = 22; migrations = 24 (`migration_001..024`); `Database` repos = 15; tests ≈ 3392 collected. These drift monotonically — re-verify before relying on absolute counts.
17. **YC SDK docs fully re-captured against pinned v0.22.0** (2026-07-18, Phase 12 wave of 7 parallel agents + Gate 2 fix dispatch + serial verification): all 7 files in `docs/other/yc-ai-sdk/` now have H1 stamp `(verified against pinned v0.22.0, 2026-07-18)` and a banner stating verification scope. ~30 newly-discovered drifts fixed across the bundle (most critical: `embeddings-and-other.md` had 13 — nonexistent `as_batch()`/`query()` methods, invalid `"BM25"`/`"TextGeneration"` enums, etc.; `chat-openai-compat.md` had wrong `ChatModelResult` dataclass fields; `speech.md`/`completions.md`/`chat-openai-compat.md` had `await run_stream()` bugs that would raise `TypeError` — async generator, not coroutine). `⚠` convention: server-side facts only (model catalogues, context sizes, required scopes). `make check-docs` green.
18. **Max Messenger host lineage**: `botapi.max.ru` (legacy, retired 2026-07-19) → `platform-api.max.ru` (deprecated, also retired 2026-07-19) → `platform-api2.max.ru` (current production host, `lib/max_bot/constants.py:18`). Migration COMPLETE per `memories/max-api-migration.md`. Schema snapshots in `docs/other/Max-Messenger/` carry deprecation banners.
19. **Dependency pins (verified 2026-07-18)**: `aiodocker==0.27.0` (was 0.26.0); `sqlite-vec==0.1.9` (was 0.1.10a4); `httpx-socks[asyncio]==0.11.0` (was `>=0.10.0`); `numpy==2.5.1` (was 2.4.6); `pillow==12.3.0` (new direct dep at `lib/ai/models.py:48`, **zero dep-usage coverage — candidate for future round**); `aiohttp==3.14.1`.

### Cross-cutting code-side follow-ups (ALL RESOLVED 2026-07-18 in Phase 8-9 follow-up pass)

All items below were flagged as out-of-`/docs`-scope during the initial audit; the user requested them resolved. Status: every item landed, `make format lint` clean, `make test` green (3389 passed).

- ✅ **`internal/database/database.py`** class docstring (removed `divinationLayouts`; added `userMemories`/`chatEmbeddings`/`chatSearch`) + module/class example `getMessages`→`getChatMessagesSince` (×2).
- ✅ **`internal/services/cache/service.py:1137`** + **`internal/bot/common/handlers/base.py:1174`** docstrings → `_runSingleRefinement`'s inlined cursor-persist (with "formerly `_persistMemoryEntry`" historical pointer).
- ✅ **`internal/services/llm/service.py:78-80`** `generateCondensingDict` docstring → `messageCount += 1` is unconditional; only metadata extraction skipped in None branch.
- ✅ **`internal/bot/models/message_metadata.py:289`** `mergeCondensingDicts` docstring → "set-unique (unsorted)" for participants; "plain extend (NO de-dup)" for messageIds.
- ✅ **`internal/bot/common/handlers/chat_search.py:974-978`** comment → `extra=` is commented out; runtime `str(mid).strip()` + `MessageId(midStr)` coercion is the actual safety net.
- ✅ **`internal/bot/common/handlers/dev_commands.py:842`** docstring → `reconstructMessages` replaced with `ModelMessage.fromDictList` (the actual consumer at `lib/ai/models.py:676`).
- ✅ **`internal/bot/max/application.py:127`** `unregister-webhook` code default `True` → `False` (RUNTIME change; aligns with config default `false`; doc-sync rippled to 4 docs).
- ✅ **`internal/bot/common/handlers/manager.py:491-492`** comment → corrected handler-ordering misattribution.
- ✅ **`internal/bot/constants.py:65,168`** stale paths → `docs/archive/plans/...`.
- ✅ **`lib/markdown/__init__.py:17`** docstring → camelCase `markdownToMarkdownV2` (was snake_case).
- ✅ **`lib/geocode_maps/client.py:14`** docstring → "TypedDict models" (was "Pydantic models"; file path was `client.py` not `__init__.py` as initially flagged).
- ✅ **Test-side stale comments**: `test_user_memories.py:819,855,28,1214,1729`; `test_user_memories_memory_regen.py:4`; `test_yandex_search.py:4`; `test_user_info.py:449` — all updated.
- ✅ **`.agents/skills/add-llm-tool/SKILL.md:353`** stale `~line 1306` ref → symbol-only reference.
- ✅ **17 stale `docs/plans/` paths in code/tests** all → `docs/archive/plans/...` (8 in `user_memories.py`, 2 in `constants.py`, 1 each in `migration_020/021`, `llm/models.py`, 5 across 4 test files).
- ✅ **Regression tests for `llm_messages.py:394` empty-guard** — `TestLLMEmptyResponseGuard` class (5 tests) added to `tests/bot/common/handlers/test_llm_messages.py`; `testPostStopUnregisterWebhookKeyAbsentDefaultsToFalse` added to `tests/bot/max/test_webhook_mode.py`. Test count: 3381 → 3389.

### Open documentation decisions (status as of 2026-07-18 end-of-day)

- ✅ **`docs/database-README.md`**: FREEZE-and-link framing removed (Phase 11); file is now a normal maintained overview with positive "Canonical sources" navigation pointer. All 27 Phase 3c drift fixes intact.
- ✅ **`docs/plans/llm-empty-truncated-final-handling-v1.md`**: Test Plan implemented (Phase 9, 5 tests); status remains `PARTIALLY IMPLEMENTED` (Option A provider downgrade + `bot.py` empty-string guard still pending — those are product decisions, not doc drift).
- ✅ **AGENTS.md L124-127**: `lib/ext_modules/*/tests/` sanctioned-exception carve-out added (Phase 10).
- ✅ **YC SDK version drift** (`docs/other/yc-ai-sdk/`): **FULLY RE-CAPTURED 2026-07-18 (Phase 12)**. All 7 files re-verified against installed v0.22.0 SDK source. ~30 newly-discovered drifts fixed. H1 + banners consistent across the bundle. `⚠` markers discipline: server-side facts only. See "Recurring drift patterns" item 17 above.
- ⚠ **`docs/archive/design/` count** = 23 archived + 1 README = 24 total (decremented from 24+1=25 after `custom-modules-design.md` was restored to `docs/design/` in Phase 7).
- ℹ **Per-section archive READMEs** enumerate files without explicit count statements; parent `docs/archive/README.md` carries the canonical counts. Intentional — enumeration suffices.

### Process lessons reinforced

- **Per-file agents need explicit cross-file-flag instructions.** When a drift is found, the agent should be told which sibling files might carry the same drift and instructed to flag (not fix — that would violate one-file-only scope) for Phase 4 reconciliation. This worked well; only 4 of ~85 files had residual cross-file drift after Phase 3.
- **Gate 2 (whole-work review) is non-optional for multi-file audits.** Caught 3 HIGH-severity cross-file inconsistencies (Pattern-1 incomplete in `user-memory-refinement.md`; Pattern-5 missed in `architecture.md` + `database-schema.md`) that per-file agents couldn't see.
- **Re-dispatch is normal for high-drift files.** 2 of 6 `docs/llm/` non-memory files hit the ~60 step budget on first pass; the brief was tightened and re-dispatched successfully. Don't fight it — just re-dispatch with the remaining scope made explicit.
- **Count methodology in archive indexes**: "content-only + `+ 1 README` suffix" is now the convention. `docs/archive/plans/` = 66 archived + 1 README = 67 total; `docs/archive/design/` = 23 archived + 1 README = 24 total (was 24+1=25 before `custom-modules-design.md` was restored to `docs/design/` in Phase 7).
- **Strict one-subagent-per-file + Phase 4 reconciliation**: worked well at 85 files; the alternative (parallel multi-file agents) would have caused more merge conflicts and harder review.
- **Archive-vs-live decision principle (learned from user feedback 2026-07-18)**: a doc referenced as **current operational guidance** by a live skill/code-path is NOT a historical-only candidate, regardless of its "Status: Implemented" header. Phase 2 incorrectly archived `custom-modules-design.md` because it looked like a "shipped-feature design doc"; the user pointed out that `.agents/skills/add-handler/SKILL.md` references it as routing/decision guidance under "When NOT to use" — so it's a living reference. Restoration to `docs/design/` (not original `docs/` root — that would re-create clutter) + revert of inbound links to current-guidance framing was the correct fix. Apply this principle to future archive decisions: grep for **operational** references (skills, "see this for how to X"), not just historical-plan-of-record references.
