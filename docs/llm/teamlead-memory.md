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

## Task-Specific Memory Files

- [`memories/proxy.md`](memories/proxy.md) — archived durable notes from the completed proxy support work. Read it when touching `lib/proxy/`, proxy config, per-service proxy overrides, or HTTP client wiring. **Note:** `fromServiceDict` was renamed to `fromServiceConfig` after the initial implementation.
- [`memories/sandbox.md`](memories/sandbox.md) — archived durable notes from the completed `lib/sandbox` / sandbox-handler work. Read it when touching sandbox code, config, or docs.
- **Sandbox improvements design**: [`docs/sandbox-improvements-design.md`](../../sandbox-improvements-design.md) is the design document for the sandbox enhancements (per-run workDir, file listing/reading/sending/list-libraries LLM tools). Read it before implementing any of the changes. Key decisions: per-run workDir at `.run/<runId>/work/`, `workDir` field only in `RunResult` (no `files` — handler scans via `listFiles()`), MIME detection in handler layer (not in `lib/sandbox/`), line-based offset/limit in handler only, 20 MB send cap. LLM tool names: `sandbox_list_files`, `sandbox_read_file`, `sandbox_send_file`, `sandbox_list_libraries` (all alongside existing `run_python`). Session lifecycle is already idle-based (no hard max lifetime) — confirmed no-op. **Completed 2026-06-09, extended 2026-06-14.** Handler conventions from this work: `_llmTool*` naming, dict returns (not JSON strings), constants for magic numbers, direct bytes-or-str decode (no str→bytes→str).
- **Sandbox path normalization (2026-06-13):** `resolveWorkspacePath()` now normalizes absolute paths instead of rejecting them. `/workspace/...` → strip prefix; `/...` → strip leading `/`. Security preserved via `resolve()` + `relative_to()` jail after normalization. The `path == "/"` special case in `listFiles` was removed. LLM tool descriptions + handler docstrings updated accordingly. Both `listFiles` and `readFile` use `Path(record.workspacePath)` without redundant `.resolve().absolute()` — `resolveWorkspacePath` handles resolution.
- **Sandbox list_libraries + packages removal (2026-06-14):** Added `sandbox_list_libraries` LLM tool (wraps `SandboxManager.listRuntimeLibraries(RuntimeName.PYTHON)`, returns `{done, packages: [{name, version}]}`). Removed `packages` parameter from `run_python` LLM tool (security: no auto-install; LLM should discover via `list_libraries` and ask admin to `/sandbox install` missing ones). Fixed pre-existing `errorMessage`→`error` key inconsistency in `_llmToolRunSandboxCode` to match all other sandbox LLM tools. Design doc updated from "four" to "five" tools.
- [`memories/test-reorganization.md`](memories/test-reorganization.md) — archived durable notes from the test layout migration. Read it when moving tests or changing test layout conventions.

## Proxy Module Conventions

- `ProxyConfig` uses `fromServiceConfig()` (not `fromServiceDict`) — renamed in kill-switch fix.
- Master kill-switch: `globalProxyConfig.enabled=False` → `getCombined()` returns `ProxyType.NONE` regardless of per-service overrides.
- Service kill-switch: `self.enabled=False` → `getCombined()` returns copy of global config (inherit everything from global).
- Both enabled: field-level merge with service taking precedence. `None`-valued user/password mean "inherit from global"; empty strings override global.
- `fromDict(useProxy=None)`: treats as global config — reads `enabled` from data dict. `fromDict(useProxy=False)`: forces NONE type, marks enabled=True (so getCombined doesn't fall back to global). `fromDict(useProxy=True)`: reads proxy fields from data dict; **does NOT auto-set `enabled=True`** — the `enabled` flag comes from the data dict. If the per-service proxy sub-section omits `enabled: true`, the override is silently ignored (getCombined falls back to global). This is intentional.
- `ProxyConfig.__repr__` masks non-empty passwords as `'***'` (`None` and `""` render verbatim). `__str__` delegates to `__repr__`.
- `ProxyConfig.__init__` does **not** validate address for non-NONE types anymore — address validation was removed and deferred to `_buildProxyUrl` (called by `getProxyURL`/`toKwargs`). This allows intermediate disabled configs like `ProxyConfig(type=HTTP, address="", enabled=False)` without crashing.
- sqlink proxy config goes under `[database.providers.<name>.parameters]`, not at provider level. `getSqlProvider()` forwards `config["parameters"]` to the constructor, so `use-proxy` and `proxy` must be nested there.
- `ProxyConfig.enabled` (bool) is distinct from `use-proxy` TOML key — `use-proxy=False` sets type to NONE + enabled=True; `enabled: False` in dict means "inherit from global".
- SQLink `_proxy` stores a `ProxyConfig` object (lazy resolution); `getProxyURL()` is called in `connect()`, not `__init__`.
- Telegram bot calls `getCombined()` explicitly before the match block because it needs the resolved `proxyType` for type dispatch; subsequent `getProxyURL()`/`toKwargs()` calls find the already-combined config and are no-ops.

## Repo Facts And Gotchas

- `lib/utils/ttl_dict.py` provides a thread-safe TTL dict with GC, lazy expiration, and full dict API. Uses sentinel pattern for unspecified TTL vs ttl=None.
- `pathlib.relative_to()` is preferred over `str.startswith()` for path containment checks (cross-platform, handles symlinks/trailing slashes).
- `dict.setdefault()` is the canonical one-liner fix for check-then-create race conditions in CPython (GIL-protected).
- Async tests should use `async def test_...` without `@pytest.mark.asyncio`; `asyncio_mode = "auto"` handles them.
- Bot handler config-gating pattern: `if self.configManager.get("section", {}).get("enabled", False)` in HandlersManager, register before LLMMessageHandler (line ~534). Use `HandlerParallelism.PARALLEL` for most handlers.
- Chat setting access: `settings[key][0]` returns the value (tuple is `(value, updatedBy)`). Direct indexing preferred, not `.get()`. Writes need keyword-only `updatedBy=`.
- `isBotOwner()` is on `BaseBotHandler` (not `_bot`). Mock it as `handler.isBotOwner = Mock(...)` in tests, not `handler._bot.isBotOwner`.
- `ConfigManager.get()` does NOT support dotted-path traversal -- it is plain `dict.get(key, default)`. Always use nested `.get()` calls.
- Multi-section truncation: update cumulative length after each section or all sections share the same remaining space (overflow risk).
- `newMessageHandler` does NOT gate commands. Commands are dispatched via `@commandHandlerV2` decorator and bypass the message handler chain. Per-command access checks must be in each command method (use a shared `_checkAccess()` helper).
- LLM tool registration: `self.llmService.registerTool(name, description, [LLMFunctionParameter(...)], handler=self._method)` in `__init__`. Gate with feature-enabled flag. Imports: `from lib.ai import LLMFunctionParameter, LLMParameterType`.
- LLM tool handler method naming: use `_llmTool*` prefix (e.g., `_llmToolRunSandboxCode`, `_llmToolSandboxListFiles`) so the method's role is clear without reading the registration code.
- LLM tool handler signature: `async def _llmTool*(self, extraData: Optional[Dict[str, Any]], param1, ..., **kwargs: Any) -> Dict[str, Any]`. Return a dict with `{"done": bool, ...}` — the LLM service handles JSON serialization. NEVER raise. Get chat context from `extraData["ensuredMessage"]`.
- LLM tool handlers can return dicts directly (not JSON strings). This is cleaner — no `json.dumps()`/`jsonDumps()` needed. The LLM service serializes the dict.
- `lib/ai/providers/basic_openai_provider.py`: `BasicOpenAIModel` has two image-generation transports: (1) `_generateImage()` using `chat.completions.create` with `modalities=["image", "text"]`, (2) `_generateImageViaImagesApi()` using `client.images.generate()`. Models opt into the second via `image_generation_api = "openai-images"` in `extraConfig`.
- Hook methods available for subclasses: `_getModelId()` (text models), `_getImageModelId()` (image models), `_getExtraParams()`, `_getImageRequestOptions()` (whitelisted image API params), `_getClientParams()` (extra AsyncOpenAI constructor kwargs).
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

## Chat History Search — Step 1 (completed 2026-06-21)

- Implementation plan: `docs/plans/chat-history-search-plan.md`
- Step 2 plan: `docs/plans/chat-history-search-step2.md` — adds `/users` command + `search_messages`, `list_users`, `get_thread` LLM tools
- Embedding model: `intfloat/multilingual-e5-large` (1024d) via `local-embeddings` provider (fastembed)
- Default model name: `"local-embedding"` in `bot-defaults.toml`
- `fastembed==0.8.0` pinned in `requirements.direct.txt`
- Key repos: `ChatEmbeddingsRepository` (embedding CRUD), `ChatSearchRepository` (search dispatcher), `ChatUsersRepository.getChatUsers` (activity filters)
- Backfill: `_dtCronJob` in `ChatSearchHandler` — round-robin per-chat, reads `REGENERATE_EMBEDDINGS` boolean, no flag reset
- Shared helper: `embedAndSaveMessage` in `internal/bot/common/embedding_utils.py` — takes `EnsuredMessage`, resolves `LLMService` via `getInstance()`
- Config cached: `_searchEnabled`, `_reindexBatchSize` in handler `__init__`
- `DO_EXIT` registration is OPTIONAL — not required by `QueueService`
- See "Anti-Patterns Learned" below for the full list of 20 mistakes made and fixed during Step 1

## Chat History Search — Implementation Decisions (2026-06-20)

- **`MAX_MESSAGES_FOR_SEMANTIC_SEARCH` page**: `BOT_OWNER` (resolved from plan inconsistency).
- **Backfill chat discovery**: Query DB directly for chats with `REGENERATE_EMBEDDINGS = true`. Add a repository method or direct query. Process N chats per CRON_JOB tick with configurable batch size.
- **Plan gaps fixed**: `ChatSettingsPage.BOT_OWNER` reconciled; backfill discovery specified.
- **Two-tier embedding model resolution** (chat setting → hardcoded fallback): `MessagePreprocessorHandler._embedMessage` and `ChatSearchHandler._dtCronJob`. The per-chat `EMBEDDING_MODEL` default is now set in `bot-defaults.toml` to `"local-embedding"`, so the chat-settings default provides the value. The `[search-history.embeddings].model` server-wide default was removed (redundant with chat settings default).
- **Parser merge semantics in `_parseSearchArgs`**: bare words merge with `keywords:`, first occurrence wins for other keys, values span tokens until next known key.
- **Lazy import of `ChatSettingsValue` in `internal/database/repositories/chat_settings.py`**: `listChatsBySetting` imports `ChatSettingsValue` inside the method body to break a package-initialization cycle (`internal.database → internal.bot.models → internal.database`).
- **Backfill is now a CRON_JOB handler in `ChatSearchHandler`**: there is no longer a separate `BackfillWorker` class. `ChatSearchHandler.__init__` registers `_dtCronJob` against `queueService.registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB, ...)`. The previous `internal/bot/common/workers/backfill_worker.py` module was removed and the round-robin / per-tick batch / per-message error-handling logic now lives in `ChatSearchHandler._dtCronJob`. `HandlersManager.__init__` simply appends `ChatSearchHandler` to the handler list when `[search-history].enabled` is true — no separate import, no try/except.
- **`DO_EXIT` registration via `registerDelayedTaskHandler` is OPTIONAL, not required by `QueueService`**. `QueueService.startDelayedScheduler` already registers its own built-in `DO_EXIT` handler (`_doExitHandler`) that performs the actual graceful-shutdown bookkeeping, so a handler that has nothing to do on shutdown is free to skip the `registerDelayedTaskHandler(DelayedTaskFunction.DO_EXIT, ...)` call entirely. The `SandboxHandler` / `ResenderHandler` / `HandlersManager` register one because they own resources (active sandbox runs, pending message sends, periodic cleanups) that need a coordinated teardown — `ChatSearchHandler` does not, so it only registers `CRON_JOB`. Do not assume every handler needs a `_dtOnExit`.
- **Gate 2 review outcome (2026-06-20)**: 3 critical issues found, all fixed. 6 important issues, 2 fixed. 4 deferred.
- **Production bugs found and fixed**: `convertToSQLite` didn't handle `bytes`; `TTLDict(defaultTtl=...)` kwarg was silently swallowed; `_filterMessageIds` AND→OR; `_parseSearchArgs` couldn't handle `key: value` with space; keyword filter applied after SQL LIMIT; IN() portability issue.
- **Circular import workaround**: `listChatsBySetting` in `chat_settings.py` lazily imports `ChatSettingsValue`.
- **Post-implementation refinements (2026-06-21)**: 
  - Embedding model: switched from English-only `bge-small-en-v1.5` (384d) to multilingual `intfloat/multilingual-e5-large` (1024d) for Russian support.
  - Cache removed from DB layer; model resolution simplified to 2-tier (chat setting → `"local-embedding"`); `on-save` config dropped (always embed if enabled); `_searchEnabled` cached in `MessagePreprocessorHandler.__init__`.
  - `listChatsBySetting` simplified: returns `List[Dict]` with `chat_id`/`value`; callers filter via `ChatSettingsValue.toBool()`.
  - `ChatEmbeddingsRepository` created; all embedding methods + semantic search moved there from `ChatMessagesRepository`. `listChatUsers` moved to `ChatUsersRepository`, then merged into `getChatUsers` (now exposes `limit` / `minMessages` / `lastActiveDays` / `seenSince` on a single method).
  - `BackfillWorker` deleted; backfill is now a CRON_JOB handler (`_dtCronJob`) directly in `ChatSearchHandler` — round-robin per-chat, no flag reset.
  - Semantic search wired into `/search`: keywords → `generateEmbeddings` → `queryEmbedding` passed to `searchChatMessages` (falls back to filter-only on failure).
  - `fastembed==0.8.0` / `numpy==2.4.6` in requirements.

## Chat History Search — Anti-Patterns Learned (2026-06-21)

These mistakes were made during Step 1 implementation and fixed. Don't repeat them.

### Architecture & Layering

1. **Don't put caching in repositories.** The DB layer is for data access only. Caches (TTLDict, CacheService) belong in handlers. The embedding cache was initially inside `ChatMessagesRepository` and had to be removed entirely.

2. **Don't create separate classes for features that fit in existing handlers.** `BackfillWorker` was a standalone class with lazy imports — user rejected it. A CRON_JOB handler directly in `ChatSearchHandler` is simpler and doesn't need a new file.

3. **Don't put code that needs `internal/` types into `lib/`.** The summarization module used `llmService: Any` because `lib/` can't import `internal/`. It was moved to `internal/bot/common/`, then deleted entirely. If a module needs types from `internal/`, it belongs in `internal/`.

4. **Extend existing methods, don't create near-duplicates.** `listChatUsers` was a separate method alongside `getChatUsers`. Merged: `getChatUsers` now accepts optional `minMessages`, `lastActiveDays`, `limit`.

5. **One domain per repository.** Embedding methods were scattered across `ChatMessagesRepository`. They were split into `ChatEmbeddingsRepository` (embedding CRUD) and `ChatSearchRepository` (search dispatcher). Each repo owns one domain.

### Repository Design

6. **Always return TypedDicts from repository methods.** Never return raw `dict` or `tuple` — too hard to track what fields exist. Every method that queries the DB should return a TypedDict (`ChatMessageDict`, `MessageEmbeddingDict`, `ThreadResultDict`, etc.).

7. **All repo methods that return the same entity should return the same TypedDict with ALL fields.** `getMessageEmbedding` and `getMessagesWithoutEmbeddings` initially returned different subsets of fields. Both now return full `MessageEmbeddingDict` (one has NULL embedding, the other has the vector).

8. **Use `dbUtils.sqlToTypedDict` for row conversion.** Don't build dicts manually in repository methods. The project has standard converters — use them. Only handle special cases (BLOB → list[float]) manually before passing to the converter.

### Config & State

9. **Cache config values in `__init__`, don't re-read on every invocation.** `configManager.getSearchHistoryConfig()` was called on every message and every CRON_JOB tick. Cache `_searchEnabled`, `_reindexBatchSize` etc. once.

10. **Don't add config options without a real use case.** `on-save` toggle was added but served no purpose: "If embeddings are enabled + enabled for chat, then they are saved on save." Removed.

11. **Model resolution: if a chat setting has a default, don't add a server-wide fallback.** `EMBEDDING_MODEL` now has a default in `bot-defaults.toml` (`"local-embedding"`), so the `[search-history.embeddings].model` server-wide fallback was redundant. Two-tier, not three-tier.

### Feature Design

12. **If you build semantic search infrastructure, wire it in.** Embeddings were generated and stored but `/search` only used filter-only mode. The entire point of the feature is semantic search — the query embedding path must be wired.

13. **Filters must apply before result truncation.** The keyword filter was applied client-side AFTER the SQL LIMIT, silently dropping matching results outside the limit window. Always filter first, then truncate.

14. **Backfill should use `REGENERATE_EMBEDDINGS` for chat discovery, not `EMBEDDINGS_ENABLED`.** The regeneration trigger is a one-shot flag — backfill processes chats that have it set, not all chats with embeddings enabled.

15. **Don't list all rows to find one.** `_resolveUserId` called `listChatUsers(limit=None)` to find one user by username. Use targeted queries: `getChatUserByUsername(chatId, username)`.

### Code Quality

16. **Extract duplicated logic into shared helpers.** `_dtCronJob` and `_embedMessage` had identical embed+save code. Extracted to `embedAndSaveMessage` in `internal/bot/common/embedding_utils.py`.

17. **No redundant guard checks.** `supportsEmbedding` was checked in both `abstract.py` (public method) and `basic_openai_provider.py` (private method). The provider check is redundant — the public method already guards.

18. **No lazy imports inside methods.** AGENTS.md forbids this. Initial `BackfillWorker` import was lazy — removed when the worker was deleted.

19. **Parser must handle documented syntax.** `/search` DSL uses `key: value` with space. The initial token-by-token parser broke on this. Parser must consume multi-token values until the next known key.

20. **Keywords are optional if other filters exist.** The parser required keywords even when `user:` or `days:` were provided. Check that at least one argument is given, not that keywords specifically is present.

## Teamlead Workflow Lessons

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
