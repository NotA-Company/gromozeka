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

- [`memories/proxy.md`](memories/proxy.md) — archived durable notes from the completed proxy support work. Read it when touching `lib/proxy/`, proxy config, per-service proxy overrides, or HTTP client wiring.
- [`memories/proxy-lifecycle.md`](memories/proxy-lifecycle.md) — proxy lifecycle management: `ProxyService`, `ProxyLifecycle`, subprocess management, health checks, startup/event-loop, SandboxHandler analogue pattern, call-site migration.
- [`memories/sandbox.md`](memories/sandbox.md) — archived durable notes from the completed `lib/sandbox` / sandbox-handler work. Read it when touching sandbox code, config, or docs. Includes sandbox improvements design, path normalization, list_libraries, and handler conventions (`_llmTool*` naming, dict returns, constants for magic numbers).
- [`memories/chat-history-search.md`](memories/chat-history-search.md) — chat history search feature: implementation decisions, 20 anti-patterns learned, Step 2 gotchas, embedding pipeline, and all review fix rounds.
- [`memories/test-reorganization.md`](memories/test-reorganization.md) — archived durable notes from the test layout migration. Read it when moving tests or changing test layout conventions.

## Proxy Lifecycle Management

See [`memories/proxy-lifecycle.md`](memories/proxy-lifecycle.md) — architecture, startup/event-loop, SandboxHandler analogue pattern, gotchas, call-site migration, and kill-switch bypass fix.

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

## Chat History Search

See [`memories/chat-history-search.md`](memories/chat-history-search.md) — implementation decisions, 20 anti-patterns learned, Step 2 gotchas, embedding pipeline, and all review fix rounds.

## Test Mocking: Chat Settings Must Be Complete Dicts

- Production code accesses `chatSettings[KEY].toBool()` via direct subscript, never `.get()` with a default. Test mocks that return sparse `ChatSettingsDict` cause `KeyError` for any key the production path reads.
- `_makeChatSettings()` helpers must include every `ChatSettingsKey` that the production path accesses. When adding a new gate check in production (e.g., `REGENERATE_EMBEDDINGS`), the test helper must be updated to include it.
- `test_cron_no_enabled_chats` had a second-order bug: the assertion used a stale key (`REGENERATE_EMBEDDINGS`) that didn't match the current production query (`EMBEDDINGS_ENABLED`). When production queries change, test assertions must follow.

## Reviewing Large Changes

- See [`docs/llm/reviewing-large-changes.md`](reviewing-large-changes.md) -- methodology for reviewing changes exceeding the single-pass budget of the `code-reviewer` agent (>24 files). Covers pre-review characterization, batching by feature domain, per-batch review with parallel execution, integration pass, and remediation workflow. Created 2026-06-28.

## Large Review Campaign Lessons (2026-06-28)

- Ran a 78-file review across 6 batches. Key learnings:
  - **Parallel dispatch works**: 6 `code-reviewer` agents dispatched in a single message, all completed independently. Read-only agents have zero conflicts.
  - **Batch size 15-20 files is the sweet spot**: batch at 30 files needed splitting; 4-7 file batches were trivial. 20 files is the practical upper bound.
  - **Integration pass caught cross-batch issues**: documentation in one batch was wrong about code in another batch — no per-batch reviewer could catch this.
  - **Per-batch findings must be verified**: several "IMPORTANT" findings from per-batch reviews were still present in the code — the per-batch review loop had never actually landed the fixes.
  - **Documentation drift is the most common cross-batch failure mode**: docs described `get_summary` tool, `asyncio.run()`, and `initialize(queueService, configManager)` — none matching shipped code.
  - **User triage for recs/nits is efficient**: 22 auto-fix items + 16 user-decision items. User approved ~10 rec fixes and skipped ~6.
  - **7 parallel fix groups dispatched**: no file overlaps → zero conflicts. All 2635+ tests green after each pass.
- The `reviewing-large-changes.md` methodology was updated with these lessons (Section 4.2.1, Section 6 restructured, Section 6.1 added).

## Any Type Audit (2026-06-28)

- Full audit of all `Any` type annotations in production code (`lib/`, `internal/`, `main.py`).
- 61 direct `Any` usages across 24 files. 36 GENUINE, 25 NARROWABLE.
- Key NARROWABLE categories:
  - **`__aexit__` signatures** (3 sites): should be `Optional[type[BaseException]]`, `Optional[BaseException]`, `Optional[types.TracebackType]`.
  - **Circular-import workarounds** in `internal/services/llm/models.py` `ExtraDataDict`: `ensuredMessage: Any` and `typingManager: Any` — should use `TYPE_CHECKING` + string forward refs.
  - **`LLMToolCall.id`** and **`ModelMessage.toolCallId`**: all callers pass `str`, should be `str` / `Optional[str]`.
  - **`_STR_RENDERERS` dict** in `lib/ai/models.py`: value is `Callable[[Any], Any]`, input union is `Exception | bytes | ModelResultStatus | None`.
  - **`CommandHandlerFuncUnbound/Bound`** in `internal/bot/models/command_handlers.py`: 3 `Any`s — self is `BaseBotHandler`, last param is `Optional[TypingManager]`.
  - **`_makeSpamButtonSignature`** extra param: always `bool`.
  - **`LLMToolHandler`** return: `Awaitable[Any]` should be `Awaitable[Union[str, Dict[str, Any]]]`.
  - **`LLMToolCall.parameters`** (2 sites): `Dict[Any, Any]` should be `Dict[str, Any]` (keys are always strings).
  - **Render helpers** (`_renderError`, `_renderMediaData`, `_renderStatus`): return `Any` but actually return `str | _OMIT` sentinel.
  - **`substituteEnvVars`** (2 sites): identity-like, `TypeVar` candidates.
- GENUINE patterns that should stay: `**kwargs: Any` passthrough (12+ sites), `rawResult: Any` for provider-agnostic LLM responses, `jsonDumps(data: Any)`, `convertToSQLite(data: Any)`, `ConfigManager.get(key, default=Any) -> Any`, `TTLDict.__init__` wrapping dict.
- ~20 additional files import `Any` but only use it within `Dict[str, Any]` (JSON-like dicts) — these are accepted and excluded from the audit scope.

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

## Documentation Audit Lessons (2026-06-28)

- **Three index.md files** in the repo: `docs/llm/index.md` (main agent entry), `docs/llm/memories/index.md` (archived memory index), `docs/other/yc-ai-sdk/index.md` (YC SDK reference). All three must be kept in sync with the file tree.
- **Highest-drift docs** (age fastest, most claims become stale): `database-README.md`, `database-schema.md`, `database-schema-llm.md`, `developer-guide.md`. These contain migration counts, repository lists, line numbers, method signatures, enum values, and table counts — all of which drift with every code change.
- **Medium-drift docs**: `docs/llm/architecture.md` (handler chain, ADR counts), `docs/llm/handlers.md` (handler list, registration order), `docs/llm/index.md` (line counts, test count, entry point lines).
- **Low-drift docs**: `docs/llm/memories/` files, `sql-portability-guide.md`, `docs/llm/sandbox.md`, `docs/llm/tasks.md` (gotchas/anti-patterns are stable), `docs/llm/testing.md`.
- **Common drift patterns across all docs**: (1) line number references rot within weeks, (2) counts (repository, migration, table, handler, test) always lag, (3) method names change in code but not in doc examples (e.g., `setUserData` → `addUserData`), (4) enum values grow but docs aren't updated, (5) DDL in docs can have phantom columns not in actual migrations.
- **database-README.md** is the worst offender — it's a 732-line marketing-style doc full of hard counts, method signatures, and provider examples that are almost all stale. Consider whether it's worth maintaining at all vs. just linking to the more-focused schema docs.
- **developer-guide.md** is human-oriented and partially redundant with `docs/llm/`; its handler list and repository list are frequently out of date.
- **`docs/reports/`** directory doesn't exist but `database-README.md` links to it — a common pattern of referencing files that were never created or were moved.
- **`docs/TODO.md`** was extensively referenced by `documentation-review-process.md` but didn't exist. All references have been removed from that document (2026-06-28 fix).
- **`.roo/rules/`** directory doesn't exist but `docs/llm/index.md` used to reference it — the rules now live in `AGENTS.md`.
- **When the same stale value appears in multiple docs** (e.g., 12 repos, manager.py:249, RateLimiterManager:12), fix ALL files at once — partial fixes create cross-file inconsistencies that confuse agents and users.
