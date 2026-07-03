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

## Max Bot API

- **Current API endpoint**: `https://platform-api2.max.ru` — defined at `lib/max_bot/constants.py` as `API_BASE_URL`. Migrated from the deprecated `platform-api.max.ru` per `docs/plans/max-api-migration.md`. The legacy endpoints (`platform-api.max.ru`, `botapi.max.ru`) are kept as comments only.
- **Deadline**: 2026-07-19 — all requests must use `platform-api2.max.ru` and trust the Минцифры (Russian Ministry of Digital Development) root CA certificate. Migration implemented June 2026.
- **Auth**: Raw access token sent as `Authorization` header (no `Bearer` prefix, no query param). This is already correct for the new API — the deprecated query-param auth never applied to this client.
- **TLS/SSL**: Custom SSL context built by `libMax.utils.buildMaxSslContext(caBundlePath)` from the `[bot].max-ca-bundle` config key. Default is `"../certs/max"` — relative to `application.root-dir` (`"storage"`), resolves to `<repo-root>/certs/max/`. The directory holds the Russian Минцифры root/intermediate PEM certs (5 files: 3 RSA + 2 GOST). The raw `caBundlePath` config value is passed directly to `MaxBotClient(caBundlePath=...)`, which builds the `ssl.SSLContext` internally via `buildMaxSslContext()`. `_getHttpClient()` conditionally passes `verify=` to `httpx.AsyncClient` only when no SOCKS5 transport is present AND a custom CA context exists (`if "transport" not in proxyKwargs and self._sslContext is not None`). When the key is empty/unset, no `verify=` is passed — httpx falls back to its default CA bundle. **SOCKS5 proxy caveat**: httpx ignores the top-level `verify=` when a custom `transport=` is supplied, so for SOCKS5 proxies (`ProxyType.SOCKS5`) the SSL context is threaded into the transport via `ProxyConfig.toKwargs(verify=self._sslContext)` (which calls `AsyncProxyTransport.from_url(url, verify=sslContext)`); the client-level `verify=` is skipped via the `"transport" not in clientKwargs` guard.
- **Polling**: Long-poll via `GET /updates` with timeout=30s, limit=100. Implemented in `MaxBotClient._pollingLoop()` (client.py:1301-1370). Called from `MaxBotApplication._runPolling()` (application.py:264-311). Continuous loop with no fixed interval — on update receipt or timeout, immediately polls again.
- **Webhook methods exist** in client (`setWebhook`, `deleteWebhook`, `getWebhookInfo`). `setWebhook`/`deleteWebhook` are now used by `MaxBotApplication` when `webhook-receiver.enabled = true` and `register-webhook`/`unregister-webhook` are enabled. Application uses long-polling by default; webhook mode polls local receiver's GET /updates.
- **Only 4 of 16** Max update types are handled: `message_created`, `message_callback`, `user_added`, `user_removed`. Rest logged as "Unsupported Update."
- **Max docs source**: `https://dev.max.ru/docs-api` — fetched 2026-06-29. Webhook events stored in project memory (id `52755987-4a03-4464-abf7-717df512f59e`).
  - Subscription: `POST /subscriptions` with `url`, `update_types`, `secret`. Secret sent back as `X-Max-Bot-Api-Secret` header.
  - TLS validation required for webhook endpoint (CN/SAN match, full chain, CA-trusted or Минцифры cert).
  - Rate limit: 30 rps on platform-api2.
  - `GET /chats` deprecated as of June 2026 — use `POST /subscriptions` instead.
  - Минцифры certificate: two PEM files from `https://www.gosuslugi.ru/crt` — `russian_trusted_root_ca_pem.crt` and `russian_trusted_sub_ca_pem.crt`.
  - No official Python SDK — `lib/max_bot/` is hand-rolled and must be updated.

### Max API Migration — IMPLEMENTED (2026-06-29)

Plan: `docs/plans/max-api-migration.md`. The endpoint migration + certificate trust has been fully implemented, reviewed, and tested (2710 tests pass).

**Files changed:**
- `lib/max_bot/constants.py` — `API_BASE_URL` → `platform-api2.max.ru`, `DEFAULT_RATE_LIMIT` 100→30
- `lib/max_bot/utils.py` — `buildMaxSslContext(caBundlePath)` loads PEM certs from directory into `ssl.SSLContext` (additive to system CAs), with try/except for GOST certs on non-GOST platforms
- `lib/max_bot/client.py` — optional `caBundlePath` param on `MaxBotClient.__init__` (builds SSL context internally via `buildMaxSslContext()`), conditional `verify=` in `_getHttpClient`, SSL context threaded into SOCKS5 transport via `ProxyConfig.toKwargs(verify=...)`, `getChats()` deprecation notice
- `internal/bot/max/application.py` — SSL context built from `[bot].max-ca-bundle` config and passed to `MaxBotClient` (raw config value, no intermediate resolution function)
- `configs/00-defaults/00-config.toml` — `max-ca-bundle = "../certs/max"` under `[bot]` (relative to `application.root-dir` which is `"storage"` → resolves to `<repo-root>/certs/max/`)
- `certs/max/` — 5 Минцифры CA PEM files (3 RSA + 2 GOST)
- `tests/lib/max_bot/test_client.py` — 14 tests (constants, SSL context loading, GOST skip, SOCKS5+SSL, caBundlePath pass-through)
- `tests/bot/max/test_application.py` — 3 tests (path resolution relative to cwd, absolute pass-through, empty returns empty) — **DELETED** 2026-07-01: `_resolveCaBundlePath` was removed; tests were stale
- `docs/llm/configuration.md` — max-ca-bundle in bot config table
- `docs/llm/libraries.md` — Max bot section updated with new API, SSL, deprecation
- `docs/developer-guide.md` — endpoint, rate limit, retries updated

**Bugs found and fixed during implementation:**
1. **GOST cert crash**: `russian_trusted_root_ca_gost_2025.pem` and `russian_trusted_sub_ca_gost_2025.pem` crash `ssl.SSLError` on macOS (no GOST engine). Fixed with try/except per-cert load.
2. **Relative path + cwd change** (final fix): `ConfigManager.__init__` does `os.chdir(rootDir)` to `storage/`. To keep path behavior consistent across the whole project, `max-ca-bundle` is now `"../certs/max"` — relative to `application.root-dir`, resolves to `<repo-root>/certs/max/`. The raw config value is passed directly to `MaxBotClient`; path resolution happens inside `buildMaxSslContext()` in `lib/max_bot/utils.py`. The initially-attempted `_STARTUP_CWD` special-case was reverted as confusing (it made `max-ca-bundle` behave differently from all other paths).
3. **SOCKS5 + verify drop**: httpx ignores top-level `verify=` when a custom `transport=` is supplied. Fixed by threading the SSL context into the transport via `ProxyConfig.toKwargs(verify=self._sslContext)` (which calls `AsyncProxyTransport.from_url(proxyUrl, verify=sslContext)` for SOCKS5) and guarding the client-level `verify=` with `"transport" not in clientKwargs`.

### Max Webhook Support — IMPLEMENTED (2026-07-01)

Plan: `docs/plans/max-webhook-support.md` (updated to local-API-proxy architecture). Two-process design: standalone aiohttp.web receiver (`internal/max_webhook_receiver/`) accepts POST /webhook from Max, stores in `webhook_updates` table, serves GET /updates in Max API format. Bot's `MaxBotClient` gets `basePollingUrl` override — polls receiver's local GET /updates instead of `platform-api2.max.ru`. Bot's polling loop unchanged.

**Key architecture decisions:**
- `basePollingUrl` (not `baseUrl`) — overrides only `/updates` endpoint, not all API calls
- `_makeLocalRequest()` — separate httpx client, no proxy/TLS, fresh per poll
- `localReceiverToken` — optional auth for GET /updates (separate from bot token; bot token never leaked to receiver)
- Webhook registration (`POST /subscriptions`) owned by bot, configurable via `register-webhook`; shutdown unregistration (`DELETE /subscriptions`) gated by separate `unregister-webhook` key (independent of registration)
- `_webhookMode` flag on `MaxBotApplication` — gating, no new polling method
- **Separate datasource support**: `webhook-receiver.datasource` config routes webhook storage to a different DB provider; `WebhookUpdatesRepository` methods accept `dataSource` param (like `DelayedTasksRepository`)
- **Cleanup toggle**: `webhook-receiver.enable-cleanup` (default true) controls periodic deletion of old processed rows
- **Deferred processing** (`mark-on-subsequent-poll`, default true): at-least-once delivery — updates are NOT marked on first read. Bot passes compound marker `{received_at}|{id}` back on next poll to acknowledge. `markProcessedBeforeMarker` marks all rows at/below the marker. Immediate mode (`false`) preserves old at-most-once behavior. Marker filtering in `getUnprocessedUpdates` uses compound tiebreaker: `received_at > :markerTs OR (received_at = :markerTs AND id > :markerId)`. Marker timestamps round-trip through `datetime` for cross-DB string-format consistency.

**Files created (7):**
- `configs/00-defaults/webhook-receiver.toml` — 16 config keys under `[webhook-receiver]`
- `internal/database/migrations/versions/migration_019_add_webhook_updates_table.py`
- `internal/database/repositories/webhook_updates.py` — `WebhookUpdatesRepository` (addUpdate, getUnprocessedUpdates with marker filtering, markProcessed with batchExecute atomicity, markProcessedBeforeMarker, deleteProcessedOlderThan)
- `internal/max_webhook_receiver/__init__.py`, `__main__.py`, `app.py` — aiohttp.web server with handleWebhook, handleGetUpdates (deferred/immediate modes), cleanupTask
- (Plus `WebhookUpdatesRow` TypedDict in `internal/database/models.py`)

**Files modified (6):**
- `requirements.direct.txt` — `aiohttp==3.14.1` promoted from transitive to direct
- `lib/max_bot/client.py` — `_basePollingUrl` + `_localReceiverToken` in __slots__/__init__, `_makeLocalRequest()`, `getUpdates()` branch, `_getHttpClient()` conditional `verify=` fix
- `internal/bot/max/application.py` — webhook config reading, `basePollingUrl`/`localReceiverToken` pass-through, `setWebhook`/`deleteWebhook` lifecycle, placeholder-secret guard
- `internal/database/repositories/__init__.py` — export
- `internal/database/database.py` — wiring (5 locations: import, __slots__, annotation, docstring, init)

**Tests (5 files, 51 tests, all pass):**
- `tests/database/repositories/test_webhook_updates.py` — 14 CRUD + marker tests
- `tests/max_webhook_receiver/test_app.py` — 19 endpoint tests (deferred/immediate modes, datasource, cleanup)
- `tests/max_webhook_receiver/test_main.py` — 3 secret-guard tests
- `tests/lib/max_bot/test_client_webhook.py` — 6 client routing tests
- `tests/bot/max/test_webhook_mode.py` — 14 config gating tests (unregister-webhook split)

**Post-review fixes applied (2026-07-01):**
- `handleWebhook` now returns 500 (not 200) on DB write failure → Max retries the delivery; `logger.exception` corrected to `logger.error` (no active exception).
- Bad marker handling: narrow `except (ValueError, OverflowError, TypeError)` around `_parseMarker`; bad marker treated as no-marker poll (prevents 500 infinite-retry wedge).
- `getUpdates` type: `lastEventId: Optional[int]` → `Optional[Union[int, str]]` for compound string marker from local receiver.
- `_makeLocalRequest`: catches `json.JSONDecodeError` around `response.json()`; persistent `_localHttpClient` (lazy-create, reuse across polls, closed in `aclose()`).
- Secret validation moved to webhook-mode block: fires whenever `enabled=true`, not just on `register-webhook=true`. Empty secret rejected.
- `unregister-webhook` code default aligned with config default: `True` → `False`.
- `toKwargs` docstring cross-references `MaxBotClient._getHttpClient()` for SSL context routing.
- `buildMaxSslContext`: GOST skip counter + louder warning (TLS may fail if chain requires skipped certs).
- `from dateutil import parser` (was bare `import dateutil`) in `webhook_updates.py`.

**Known limitations (design tradeoffs, not bugs):**
- DB write failure now returns 500 (Max retries); duplicate delivery still possible if `markProcessed` fails
- No cross-process migration guard — safe for 019 (idempotent DDL) but needs guard for future non-idempotent migrations
- Busy-polls SQLite every 0.5s during long-poll
- `_pollingLoop` marker advance on handler error defeats at-least-once in deferred mode (pre-existing, same as real Max API)
- `types` query param ignored by GET /updates (filtering at Max→receiver subscription layer)
- No deployment wiring (no `run.sh` / systemd config for receiver process)
- Unsubstituted `${MAX_WEBHOOK_SECRET}` placeholder rejected by guards in both `__main__.py` and `application.py`

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

## Any Type Cleanup (2026-06-28) — COMPLETED

Full audit and fix of `Any` type annotations in production code. 61 usages found across 24 files → 25 narrowed, 36 kept (genuine), 16 files changed.

### Files changed and what was done:

| File | Changes |
|---|---|
| `lib/ai/models.py` | `_OmitSentinel` class (real union for `str \| _OmitSentinel`), `_StrOrOmit`/`_RendererCallable` aliases, `_renderStatus`→`str`, `LLMToolCall.id`→`str`, `toolCallId`→`Optional[str]`, `parameters`→`Dict[str, Any]` |
| `lib/ai/providers/basic_openai_provider.py` | `id=tool.id`→`id=tool.id or str(uuid.uuid4())` (null guard for `Optional[str]` from SDK) |
| `lib/ai/providers/fastembed_provider.py` | `embedOne` return: `Any`→`"np.ndarray"` (string forward ref) |
| `internal/database/database.py` | `__aexit__`: `Any`→`Optional[type[BaseException]]`, `Optional[BaseException]`, `Optional[types.TracebackType]` |
| `internal/database/providers/base.py` | Same `__aexit__` fix + logging bug fix (`exc_info=`) |
| `lib/max_bot/client.py` | `exc_tb: Optional[Any]`→`Optional[types.TracebackType]` |
| `internal/bot/common/handlers/spam.py` | `extra: Any = None`→`extra: bool = False` |
| `internal/services/llm/models.py` | `ExtraDataDict` fields: `TYPE_CHECKING`+forward refs (`"EnsuredMessage"`, `"Optional[TypingManager]"`) |
| `internal/services/llm/service.py` | `LLMToolHandler`→`Awaitable[Union[str, Dict[str, Any], None]]`, `parameters`→`Dict[str, Any]` |
| `internal/bot/models/command_handlers.py` | `CommandHandlerFunc*`: `TypeVar("_HandlerSelfT", bound="BaseBotHandler")`+`Optional["TypingManager"]` |
| `internal/config/manager.py` | `substituteEnvVars`: `TypeVar`+`cast(T, ...)` for honest `T→T` |
| `lib/aurumentation/collector.py` | `substituteEnvVars`: kept `Any→Any` (module/class branch makes `T→T` dishonest) + docstring note |
| `internal/bot/common/handlers/weather.py` | `_fixCountry`: `TypeVar`+`cast` for identity-like transform |
| `lib/markdown/parser.py` | `_OptionValue = Union[bool, int, str, Dict[str, Any]]` for `set_option`/`get_option` |
| `lib/aurumentation/types.py` | `cache: Optional[Any]`→`Optional[CacheInterface[str, Any]]` |

### Patterns established for future use:
- **`_OmitSentinel` class** with `__slots__`, `__repr__`, `__bool__` — enables real discriminated union `str | SentinelType`
- **`TYPE_CHECKING` + string forward refs** — textbook solution for circular-import workarounds (used in `ExtraDataDict`, `CommandHandlerFunc*`)
- **`TypeVar` + `cast(T, ...)`** — for identity-like recursive transforms (only when the contract is honest)
- **`assert` for Optional narrowing** — `assert x is not None` after `if guard` for pyright-compatible narrowing (accepted pattern)

### GENUINE patterns preserved:
- `**kwargs: Any` passthrough (12+ LLM tool handlers, markdown convenience functions, httpx params)
- `rawResult: Any` for provider-agnostic LLM responses
- `jsonDumps(data: Any)` — `default=str` fallback makes it genuinely any
- `convertToSQLite(data: Any)` — dispatches on type with `str()` fallback
- `ConfigManager.get(key, default=Any) -> Any` — generic config access
- `Dict[str, Any]` — JSON-like dicts (~20 files, excluded from audit scope)

## Vector Search — Design for Native Provider Support

- Design document: [`docs/design/vector-search-native.md`](docs/design/vector-search-native.md) — produced 2026-06-28, reviewed and corrected through 5 review cycles. **Implemented 2026-06-29** — see "Native Implementation" section below.

### Interface — BaseSQLProvider additions

- `isVectorSearchSupported() -> bool` — concrete, default `False`.
- `vectorSearch(*, table, vectorColumn, returnColumns: list[str], queryVector: bytes, k, filterClause, filterParams, distanceMetric: VectorDistanceMetric) -> list[VectorSearchResult]` — concrete, default `NotImplementedError`.
- `listTables(likePattern: str = "%") -> list[str]` — concrete, default `NotImplementedError`. SQLite: `SELECT name FROM sqlite_master WHERE type='table' AND name LIKE :pattern`.
- `createVectorTable(tableName: str, columns: list[VectorColumnDef]) -> None` — concrete, default `NotImplementedError`.
- `VectorSearchResult` TypedDict: `rowKey: dict[str, str]` (column-name-to-value, supports composite keys) + `distance: float`.
- `VectorDistanceMetric` StrEnum: `COSINE`, `L2`.
- `VectorColumnType` StrEnum: `TEXT`, `INTEGER`, `FLOAT`, `BLOB`, `VECTOR`.
- `VectorColumnDef` TypedDict: `name: str`, `columnType: VectorColumnType`, `isPartitionKey: NotRequired[bool]`, `vectorDimension: NotRequired[int]`, `distanceMetric: NotRequired[VectorDistanceMetric]`. Uses `NotRequired[]` (NOT `total=False` — pyright rejects bracket access on total=False).
- No config key — auto-detection at connect time. `pip uninstall sqlite-vec` to disable.

### SQLite backend: sqlite-vec, vec0-first, dimension-aware

- **Table naming**: `vec_message_embeddings_{dimension}` (e.g. `vec_message_embeddings_384`). Enables multiple dimensions to coexist.
- **Schema**: `message_id TEXT`, `chat_id INTEGER PARTITION KEY`, `model TEXT PARTITION KEY`, `date TEXT` (ISO-8601), `embedding FLOAT[N] distance_metric=cosine`.
- **Tables created lazily**: in `saveMessageEmbedding()` write path (`readonly=False`), NOT in search path (`readonly=True` would fail — SQLite PRAGMA query_only blocks DDL). If vec0 table missing during search → exception → numpy fallback.
- **No migration backfill**: vec0 tables start empty, populated by CRON job + dual-write. Empty vec0 results → fall through to numpy (not return `[]`). Pre-existing embeddings populate via `REGENERATE_EMBEDDINGS` or model change.
- **maxMessages cap**: pre-filter `date >= :minDate` in vec0 MATCH query (Option B). `minDate` computed from `chat_messages`. Fallback: post-filter if vec0 doesn't support WHERE on non-partition metadata columns.
- **Dimension resolution**: `len(queryEmbedding)` — always available, no model introspection needed.
- **Model change cleanup**: stateless, idempotent — on every CRON tick, `DELETE FROM {table} WHERE chat_id = :chatId AND model != :currentModel` across all vec0 tables discovered via `listTables("vec_message_embeddings_%")`. No in-memory tracking dict.
- **Dual-write**: always DELETE first (by metadata columns or fallback to SELECT rowid → DELETE by rowid), then INSERT. Vec0 has no unique constraint on metadata columns. Write failures logged at `warning`, swallowed.

### aiosqlite / sqlite-vec gotchas

- Extension loading: `enable_load_extension(True)`, `load_extension(sqlite_vec.loadable_path())`, `enable_load_extension(False)`. No `run()`, no bare `SELECT load_extension('vec0')`.
- `aiosqlite.execute()` returns async context manager — use `async with ... as cursor:`.
- `SQLite3Provider.__slots__`: `_vectorSearchAvailable` must be in both `__slots__` AND `__init__`.
- `BaseSQLProvider`: 17 total methods (10 abstract + 7 concrete).
- Vec0 compatibility verifications needed: TIMESTAMP → TEXT, INSERT...SELECT...JOIN may not work, DELETE WHERE metadata may not work, WHERE on non-partition columns may not work — all have documented fallbacks.
- BLOB format: `array.array("f", vec).tobytes()` is already sqlite-vec compatible.
- Native path wrapped in try/except with numpy fallback. Empty vec0 results also fall through to numpy.

## Vector Search — Native Implementation

The design in [`docs/design/vector-search-native.md`](../design/vector-search-native.md) has been implemented. Concrete implementation facts (supplement the design notes above):

- **New dependency**: `sqlite-vec==0.1.9` in `requirements.direct.txt` under `# Runtime`. Optional at runtime — guarded by a module-level `try/except ImportError` + `_SQLITE_VEC_AVAILABLE` flag in `internal/database/providers/sqlite3.py`.
- **Dual-write**: `ChatEmbeddingsRepository.saveMessageEmbedding()` writes to BOTH `message_embeddings` (authoritative) and the dimension-specific `vec0` table `vec_message_embeddings_{N}` (lazily created via `_upsertVecMessageEmbedding()` → `provider.createVectorTable()` with `readonly=False`). vec0 has no unique constraint on metadata columns, so dual-write is DELETE-then-INSERT (delete by metadata columns, or fallback SELECT rowid → DELETE by rowid).
- **Native search path**: `ChatSearchRepository._semanticSearch()` calls `isVectorSearchSupported()`; if true, tries `_nativeVectorSearch()` first. On exception OR empty native results, falls through to the numpy path. **Empty native results are NOT returned as `[]`** — they fall through to numpy so a pre-backfill vec0 table doesn't silently return nothing.
- **Dimension-aware table naming**: `vec_message_embeddings_{N}` where `N = len(queryEmbedding)` (e.g. `vec_message_embeddings_384`, `vec_message_embeddings_1024`). Multiple dimensions coexist; the repository picks the table from the query vector length. No model introspection API needed.
- **Auto-connect in `vectorSearch()`**: `vectorSearch()` may be called on a provider whose connection was opened lazily (`keepConnection=false`) or that has not yet connected. It auto-connects when needed to handle the lazy connection lifecycle. Table creation happens ONLY in the write path (`readonly=False`); the search path uses `readonly=True` (SQLite PRAGMA `query_only` blocks DDL), so a missing vec0 table raises and triggers numpy fallback rather than attempting to create it.
- **Extension loading via aiosqlite**: `enable_load_extension(True)` → `load_extension(sqlite_vec.loadable_path())` → `enable_load_extension(False)`, wrapped in `try/finally` so loading is always disabled afterward (safety against leaving extension loading on after a failure). No `sqlite_vec.load(conn)` (that touches the raw `connection._conn` and is fragile), no bare `SELECT load_extension('vec0')`. Version verified via `SELECT vec_version()`.
- **Model-change cleanup with in-memory tracking**: `ChatSearchHandler._dtCronJob()` delegates to `ChatEmbeddingsRepository.deleteObsoleteModelEmbeddings()` (returns `bool`). Gated by an in-memory `_embeddingModelTracker: Dict[int, str]` (chatId → modelKey where modelKey is `modelName` or `modelName:dimensions`). Cleanup only fires once per model switch; skipped on subsequent ticks until the model changes again. Tracker is only updated on successful cleanup (prevents one-shot misses on transient failures). The repo method cleans **both** `message_embeddings` (authoritative) **and** all `vec_message_embeddings_{N}` tables, skipping the vec0 table matching `currentDimensions`. Dimension-aware: DELETE from `message_embeddings` matches on `(model, dimensions)` tuple; vec0 cleanup skips the current-dimension table (its rows are not stale).
- **vec0 tables are ephemeral**: `message_embeddings` is authoritative. vec0 tables are rebuildable sidecar indexes — they carry nothing the app cannot reconstruct. No migration creates them; no backfill job is required to populate them (dual-write + CRON re-embed catch them up). They exist only when `sqlite-vec` is loaded.
- **maxMessages cutoff joins `message_embeddings`** (not just `chat_messages`) in the native path to mirror the numpy path's candidate-pool semantics: `minDate` is computed and pushed into the vec0 MATCH query via `filterClause` (`date >= :minDate`) as a pre-filter (Option B from the design), so both paths rank over the same recent-N candidate set.
- **No config key needed**: auto-detection at connect time. To disable native search: `pip uninstall sqlite-vec` → `isVectorSearchSupported()` returns `False` → numpy path used transparently. There is no `[vector-search]` TOML section.
- **Custom extension path (Alpine Linux / source builds)**: When the `sqlite-vec` pip package is unavailable (no musl wheel), set `vectorExtensionPath = "/path/to/vec0.so"` under `[database.providers.<name>.parameters]` in TOML. The provider loads the extension from that path instead of `sqlite_vec.loadable_path()`. Use `${VEC0_EXTENSION_PATH}` env-var substitution for Docker flexibility. Commented example in `configs/00-defaults/00-config.toml`. The pip package takes priority when both are present.
- **`SQLite3Provider.__slots__`**: `_vectorSearchAvailable` must be declared in `__slots__` AND initialized in `__init__()` (to `False`), not only in `connect()`. Otherwise `isVectorSearchSupported()` called before `connect()` (early init / error paths) raises `AttributeError`.
- **Known transitional limitation: partial vec0 mirror**: After rollout, pre-existing embeddings in `message_embeddings` are only dual-written to vec0 when re-generated (via `REGENERATE_EMBEDDINGS` chat setting or model change). Until then, vec0 may have fewer rows than `message_embeddings` for the same chat+model, and native results reflect only the dual-written subset. Resolution: enable `REGENERATE_EMBEDDINGS` for affected chats to trigger a full re-embedding pass (populates vec0 via dual-write). Documented in a code comment in `_semanticSearch()`. Note: changing the `EMBEDDING_MODEL` or its dimensions now triggers `deleteObsoleteModelEmbeddings()` on both `message_embeddings` AND vec0, so model switches cleanly re-embed from scratch — this limitation only applies to same-model initial rollout.
- **maxMessages timestamp ties**: The native path uses a compound filter `(date > :minDate OR (date = :minDate AND message_id >= :minMessageId))` to match the numpy path's `ORDER BY c.date DESC, me.message_id DESC` + `LIMIT/OFFSET` semantics. Both `date` and `message_id` are captured from the cutoff query which joins `message_embeddings` to `chat_messages`.

## Review-Fix Round Lessons (2026-07-01)

From fixing review findings on the Max webhook support feature (branch `max-v2`):

- **Single `software-developer` for many small fixes works**: 7 fixes across 6 files dispatched in one brief. Developer applied them all correctly AND fixed a pre-existing test failure as a bonus. Gate 1 review caught 2 issues the developer missed (`logger.exception` misuse, `except Exception` too broad) — the review gate is essential even for "trivial" fixes.
- **`logger.exception` misuse pattern**: When wrapping a call that internally swallows exceptions and returns `False` (like `addUpdate` does), `logger.exception` in the caller has no active exception to attach a traceback to — degrades to plain `logger.error`. Always check whether the upstream call preserves the exception before using `exception()`.
- **`except Exception` too broad for parse errors**: Narrowing to `except (ValueError, OverflowError, TypeError)` for `dateutil.parser.parse` prevents masking genuine DB/programming errors. Specific exception types > broad catches.
- **Pre-existing bugs surface during review**: The `_pollingLoop` marker-advance-on-handler-error issue (marker advances even when a handler raises, defeating at-least-once in deferred mode) is pre-existing and not fixed — the real Max API has the same behavior. Flagged to user as known limitation rather than fixed.
- **Config defaults must align code ↔ config files**: The `unregister-webhook` default was `True` in code but `false` in `00-defaults/webhook-receiver.toml`. Config overrode it in practice, but the inconsistency was confusing. Fixed to align both at `False`.
- **Doc drift from review fixes is real**: 4 docs (`architecture.md`, `configuration.md`, `developer-guide.md`, `libraries.md`) had stale claims about default values and error behavior after the fix round. Updated via `update-project-docs` skill.

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

## Dedoodization (2026-07-02)

- Repo-wide removal of "dood" from comments, docstrings, log messages, error messages — 1231 of 1294 occurrences removed across 90 `.py` files.
- Script: `scripts/dedoodize.py` — line-based state machine with triple-quote tracking and bracket-depth awareness. Handles multi-line raise/logger/assert, standalone-dood docstring lines, assert condition-vs-message classification. Idempotent (re-run produces 0 changes). Excludes itself. Covers `lib/ext_modules/grabliarium` too.
- Kept "dood" in: `print()`, `messageText=`/`helpMessage=`, argparse `description=`/`help=`, `__author__`, test fixture data, mock strings — 53 occurrences preserved.
- Found and fixed 4 mid-sentence comma-loss cases in `collect.py` / `scenario_runner.py` where `, dood! ` was between clauses.
- Tests: `make test` 2802 pass, 1 pre-existing failure (`test_forwardOriginAuthorMatching[originUser-matchByUsername]` — unrelated).
- `scripts/dedoodize.py` is untracked; user should decide keep vs delete.

## DeleteFromUserMessageHandler (2026-07-02)

- New handler at `internal/bot/common/handlers/delete_from_user.py`, modeled on `ReactOnUserMessageHandler`. Telegram-only, platform-gated. Registered BEFORE `ReactOnUserMessageHandler` in the chain (deletion before reaction). Returns `FINAL` after successful deletion to stop the chain — unlike `ReactOnUserMessageHandler` which returns `NEXT`.
- Uses `ChatSettingsKey.DELETE_AUTHOR_LIST` (JSON array of `int | str` — user IDs and lowercased usernames). Commands: `set_delete_author`, `unset_delete_author`, `dump_delete_authors`.
- `_getAuthorList` type validation: `isinstance(x, (int, str)) and not isinstance(x, bool)` — explicitly excludes `bool` (a subclass of `int`). Logs warning if entries filtered.

## Telegram Author Extraction Gotcha

- `_getMessageAuthor` is duplicated verbatim between `react_on_user.py` and `delete_from_user.py`. No shared utility yet. If a third handler copies it, extract to `internal/bot/common/handlers/_author_utils.py`.
- `MessageSender.fromTelegramUser` reads `user.name` (not `user.username`). In production, PTB's `User.name` returns `@username` when a username is set. Tests mocking `from_user.name` should use `"@TestUser"` to match real behavior.
- `MessageSender.fromTelegramChat` prefixes username with `@` itself (`f"@{chat.username}"`). Mock `sender_chat.username` without `@`.

## Resender Module (2026-07-03)

- **Core file**: `internal/bot/common/handlers/resender.py` (456 lines). Cron-based handler (fires every 60s via `QueueService.CRON_JOB`). Reads messages from source chat's DB, reconstructs text/media, sends as new bot-authored messages to `targetChatId`. Zero tests.
- **Config**: `configs/00-defaults/resender.toml` — `enabled = false` by default, one example job. No override in `configs/common/` or `configs/local/` — disabled everywhere.
- **Registration**: `manager.py:516-522`, gated on `resender.enabled`. `HandlerParallelism.PARALLEL`. 3rd of 6 config-gated handlers.
- **Flow**: `_dtCronJob` → `resendCronJob` → for each job: `getChatMessagesSince(sourceChatId, since=lastMessageDate)` → reconstruct text via `FormatEntity.parseText` → prefix/suffix template substitution → `self.sendMessage(None, text=..., chatId=targetChatId)` with `replyToMessage=None` → update `lastMessageDate` in settings table (key: `resender:{job.id}:lastMessageDate`).
- **`sendMessage` returns `List[EnsuredMessage]`** with `messageId` — currently discarded by the resender.
- **Media groups**: waits for completion via `mediaGroupDelaySecs` (default 10s), retrieves binary data from `StorageService` via `local_url` key (not re-downloaded from platform), sends via `send_media_group`.
- **Error handling**: resend failure → error notification sent to target chat, `lastMessageDate` NOT advanced (retry next tick). Backoff: `messageSendDelay` doubles from 0.25s to max 10s between successful sends.
- **`ResendJob.__slots__`**: `id`, `dataSource`, `sourceChatId`, `sourceTheadId` (typo — should be `sourceThreadId`), `targetChatId`, `messageTypes`, `messagePrefix`, `messageSuffix`, `lastMessageDate`, `notification`, `mediaGroupDelaySecs`, `_lock`.
- **No native forward API** (`copyMessage`/`forwardMessage`/`copyMessages`) exists anywhere in the codebase. Max's `MaxBotClient.sendMessage()` accepts `forwardFrom: Optional[str]` but no call site passes it.
- **Forward feature** (implemented 2026-07-03, plan: `docs/plans/resender-forward-feature.md`): `ForwardTarget` TypedDict with `chatId: int`, `threadId: NotRequired[int]`, `notify: NotRequired[bool]`. `ResendJob.forwardTo: Optional[List[ForwardTarget]]` (defaults to `[]`). Forward loop in `resendCronJob` iterates targets with `await asyncio.sleep(0.1)` between them, calls `TheBot.forwardMessages(fromChatId, messageIds, toChatId, *, threadId, notify)`. Telegram: `tgBot.copy_messages()`. Max: loops over all `messageIds`, calls `sendMessage(forwardFrom=)` per message. Failures swallowed per-target (bot.py logs traceback), don't block `lastMessageDate` advancement. 13 tests in `tests/bot/common/handlers/test_resender.py`. Config: `docs/llm/configuration.md` resender section, `configs/00-defaults/resender.toml` commented example.
