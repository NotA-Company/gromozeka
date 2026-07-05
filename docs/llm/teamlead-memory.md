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
- **`.opencode/memory.jsonl` is OpenCode's own session memory store.** It is auto-appended/modified by OpenCode on every task and is expected to show as modified in `git status` during any session. NEVER read, edit, stage it — and do NOT flag it as a stray/unrelated change. Always exclude it from doc/cleanup commits.

## Task-Specific Memory Files

Full index and one-line descriptions live in [`memories/index.md`](memories/index.md) — read the relevant file before working on a subsystem. Topics covered: proxy config & lifecycle, Max Messenger API migration & webhooks, chat history & vector search, bot handlers (delete-from-user, resender, bot-answer-probability), LLM tooling (use-tools filtering, shutdown state dump), codebase cleanup (Any types, dedoodization), testing & sandbox.

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

## Test Mocking: Chat Settings Must Be Complete Dicts

- Production code accesses `chatSettings[KEY].toBool()` via direct subscript, never `.get()` with a default. Test mocks that return sparse `ChatSettingsDict` cause `KeyError` for any key the production path reads.
- `_makeChatSettings()` helpers must include every `ChatSettingsKey` that the production path accesses. When adding a new gate check in production (e.g., `REGENERATE_EMBEDDINGS`), the test helper must be updated to include it.
- `test_cron_no_enabled_chats` had a second-order bug: the assertion used a stale key (`REGENERATE_EMBEDDINGS`) that didn't match the current production query (`EMBEDDINGS_ENABLED`). When production queries change, test assertions must follow.

## Reviewing Large Changes

See [`docs/llm/reviewing-large-changes.md`](reviewing-large-changes.md) -- methodology for reviewing changes exceeding the single-pass budget of the `code-reviewer` agent (>24 files). Covers pre-review characterization, batching by feature domain, per-batch review with parallel execution, integration pass, and remediation workflow. Created 2026-06-28.

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

## Configs Tracking Gotcha (2026-07-04)

- **`configs/common/` is gitignored.** `.gitignore` line 4 is `/configs/*` with only `!/configs/00-defaults` whitelisted. So `configs/common/01-bot-defaults.toml` (and any other non-`00-defaults` config dir) is a **local deployment overlay, NOT version-controlled**.
- **All tier-defaults live only in the gitignored overlay.** `[bot.tier-defaults.banned]`/`free`/`free-personal`/`friend` (including the friend-tier `allow-sandbox = true`) exist ONLY in `configs/common/01-bot-defaults.toml`. The tracked `configs/00-defaults/bot-defaults.toml` has only an empty `[bot.tier-defaults.free]`.
- **Implication:** any tier-default that must ship with the code (e.g. friend-tier `memory-refinement-enabled = true`) will NOT propagate via git under the current model — it's a per-deployment manual overlay step, same as `allow-sandbox`. This is by design (configs are deployment-specific). Verify with `git check-ignore -v <path>` and `git ls-files configs/`.
- Only `configs/00-defaults/*` is tracked. New tracked config files go there.

## User Memory Refinement Feature (2026-07-04, IMPLEMENTED)

Background per-`(chat, user, thread)` memory refinement, owned by `UserDataHandler`. Implemented from `docs/plans/memory-refine-plan-v1.md` (status line updated to IMPLEMENTED). Full durable implementation notes live in [`memories/user-memory-refinement.md`](memories/user-memory-refinement.md); canonical docs: [`handlers.md`](handlers.md) `UserDataHandler` row, [`configuration.md`](configuration.md) §`[user-memory]`, [`architecture.md`](architecture.md) ADR-014. Reusable cross-task facts to remember:

- **Nested `chat_users.metadata` writes:** `setUserMetadata(isUpdate=True)` shallow-merges at the top level — a partial `{"memoryRefinement": {<threadId>: ...}}` wipes every other thread's summary. Write nested sub-dicts via direct read-modify-write through `chatUsers.updateUserMetadata()`. Recorded as a reusable gotcha in [`tasks.md`](tasks.md) §3.
- **`configs/common/` is gitignored** — the friend-tier `memory-refinement-enabled = true` is a local-deployment overlay (same model as `allow-sandbox`), NOT version-controlled. See "Configs Tracking Gotcha" above.
- **Single global `asyncio.Lock`** serializes all refinement; a slow LLM call blocks the next 60s tick rather than flooding the provider. No per-entry locks, no `createTask`.

## Review-Fix Round: Memory Refinement + Chat Users Cache (2026-07-05)

Post-review fixes for the memory-refinement + chat-users-cache branch. User decisions on review findings:
- **Accepted risks** (memory summarization, nothing breaks): (1) `_dtCronJob` subtracts `preCount` from accounting regardless of messages actually ingested by `_runRefinement` (capped at 128); (2) cursor advances to `messages[0]` (newest) so bursts >128 permanently skip overflow. **Mitigation: add warning log** when `len(messages) >= _memoryMaxMessagesPerRun`.
- **Fix**: metadata RMW race — add a lock in `CacheService` covering the full read-modify-write window, held by both `_persistMemoryEntry` and `setUserMetadata(isUpdate=True)`.
- **Document** (no code change): failed refinement zeroes accounting (backoff-by-accident); spam `_getUserInfoFreshIfMessagesLessThan` monotonicity depends on `messages_count` only-incrementing; `getChatUser` returns shallow copy.
- **Lock add**: `_lastRefinedTS` read at `user_data.py:353` should take `_accountingLock` for consistency with the comment at line 108.
- **Exploration confirmed (Q2)**: `CacheService.updateUserMetadata` is the SOLE production write path for `chat_users.metadata`. The repo method `ChatUsersRepository.updateUserMetadata` (`internal/database/repositories/chat_users.py:126-162`) has exactly one production caller (the cache). All 6 handler `setUserMetadata(isUpdate=True)` callsites (spam.py x4, message_preprocessor.py x2) + the 1 `_persistMemoryEntry` direct caller route through `cache.updateUserMetadata`. No `_chatUsersLock` existed prior to this fix. The `chat_messages.py:154` raw SQL bypass only touches `messages_count`, not `metadata` — irrelevant to the race.

**Line-number drift from the review report (authoritative current numbers):**
- `chat_settings.py` is at `internal/bot/models/chat_settings.py` (NOT `internal/bot/common/`).
- "реобновления" @ line **888** (under `MEMORY_REFINE_MODEL`); "при фонового обновления" @ line **901** (under `MEMORY_REFINE_SYSTEM_PROMPT`).
- `_runRefinement` fetch-cap (`limit=self._memoryMaxMessagesPerRun`) @ `user_data.py:488`; cursor advance (`newest = messages[0]`) @ `user_data.py:542-550`. (Review said 519-535 — that's the LLM call, mislocated.)
- `_persistMemoryEntry` RMW @ `user_data.py:555-596` (confirmed; line numbers drift with edits — verify before relying). `setUserMetadata` @ `base.py:~1077-1104` (drifted up ~6 lines after `getUserMemorySummary` deletion).
- `spam.py` `_getUserInfoFreshIfMessagesLessThan` @ **202-243** (not 199-241).
- `_dtCronJob` finally subtract (`preCount`) @ `user_data.py:422` (block 415-431).
- No `len(messages) >= _memoryMaxMessagesPerRun` comparison exists today — must be added for the warning log.

## Chat Users Cache (2026-07-05, IMPLEMENTED)

Write-through `chat_users` cache in `CacheService`, eliminating 2–5 redundant `chat_users` reads per inbound message. Canonical doc: [`architecture.md`](architecture.md) ADR-015; plan: [`docs/plans/user-info-cache-plan-v1.md`](../plans/user-info-cache-plan-v1.md). Reusable cross-task facts:

- **Reused `CacheNamespace.CHAT_USERS`** (keyed `f"{chatId}:{userId}"`, `MEMORY_ONLY`); extended `HCChatUserCacheDict` with a second lazily-loaded field `userInfo: NotRequired[ChatUserDict]` (non-Optional; presence-of-key = "loaded") alongside the existing `data` (`user_data` blob). No new namespace. Lazy-field independence: `data` and `userInfo` load independently. An absent DB row is NOT memoized — `getChatUser` returns `None` and leaves the cache cold, so the next call re-queries the DB (an absent row indicates a problem upstream; not worth caching).
- **5 new `CacheService` methods** (`internal/services/cache/service.py`): `getChatUser(refresh=False)` (returns defensive shallow copy; absent row not cached), `updateChatUser` (write-through upsert, skip-when-unchanged; cold path leaves cache cold — no warming re-read), `getUserMetadata` (parsed metadata), `updateUserMetadata` (full-dict replace, NO merge), `invalidateChatUser` (sync; pops only `userInfo`, preserves `data`). All single-row `(chatId, userId)` handler reads/writes route through `self.cache.*`, not `self.db.chatUsers.*`. Aggregate/by-username queries (`getChatUserByUsername`, `getChatUsers`, `getUserChats`, `getAllGroupChats`, `getUserIdByUserName`) are NOT cached.
- **`messages_count` is stale on a cached row** — incremented by raw SQL in `ChatMessagesRepository.saveChatMessage` (`chat_messages.py:154`), bypassing the cache. Callers needing an accurate count SHOULD use the conditional-refresh helper `SpamHandler._getUserInfoFreshIfMessagesLessThan(chatId, userId, threshold)`, which re-fetches only when the cached count is strictly below the threshold (monotonic value at/above the threshold stays valid). The two correctness-critical spam readers (gating on `AUTO_SPAM_MAX_MESSAGES`) use it: `checkSpam` (`>=` gate) passes the threshold unchanged; `markAsSpam` (strict `>` gate) passes `threshold + 1` so the boundary case (`cached == maxSpamMessages`) still refreshes, closing the false-ban window.
- **Skip-when-unchanged optimization** in `updateChatUser`: a no-op call (same `username`/`full_name`) skips the DB upsert, so `updated_at` no longer refreshes on such calls.
- **Nested-write invariant:** `updateUserMetadata` does NO merge — nested writers (`_persistMemoryEntry`) must read full metadata → mutate one nested key → write full dict back. A shallow `{**old, **new}` would wipe sibling threads. Same hazard ADR-014 documents for `setUserMetadata(isUpdate=True)`.
- **Coupling note:** every `metadata` writer MUST route through the cache. A future raw `db.chatUsers.updateUserMetadata(...)` bypass would silently desync the cache and corrupt subsequent `setUserMetadata(isUpdate=True)` merges. Do not add such bypasses for `metadata` (the `messages_count` increment is the sole accepted bypass, and it does not touch `metadata`).
- **Metadata RMW lock (added 2026-07-05, widened same day):** `CacheService._chatUsersMetadataLock` (single process-global `asyncio.Lock`) serializes `chat_users.metadata` access. Exposed via `chatUserMetadataLock()` async context manager (`@contextlib.asynccontextmanager`, `-> AsyncIterator[None]`). **Holders:** `BaseBotHandler.setUserMetadata` (BOTH `isUpdate=True` read-merge-write AND `isUpdate=False` full-replace — the `async with` wraps the entire method body; serializing the full-replace prevents it from being clobbered by a concurrent RMW) and `UserDataHandler._persistMemoryEntry`. **Non-holders:** plain `getUserMetadata` reads and bare `cache.updateUserMetadata(...)` calls with no preceding read. Lock ordering: `_refineLock` (outer) → `chatUserMetadataLock` (inner) — no reverse path exists (`setUserMetadata` never takes `_refineLock`). Verification (Q2 from review): `CacheService.updateUserMetadata` is the SOLE production write path for `chat_users.metadata` (the repo method has exactly one production caller); all handler metadata writes route through it. The `chat_messages.py:154` raw SQL bypass only touches `messages_count`, not `metadata`. NOTE: an earlier version of this note claimed `isUpdate=False` did NOT take the lock — that was superseded when the user widened the lock to wrap both branches; do not "optimize" the full-replace path back out of the lock.
- **Accepted risks (memory refinement, documented 2026-07-05):** (1) `_dtCronJob` subtracts `preCount` from accounting regardless of messages actually ingested; (2) `_runRefinement` cursor advances to `messages[0]` (newest) so bursts > `_memoryMaxMessagesPerRun` (128) permanently skip overflow. Both accepted because it's memory summarization — nothing breaks. Mitigation: `logger.warning` fires when `len(messages) >= _memoryMaxMessagesPerRun` (overflow detection).

## Settings-Summary Refactor: applyUserMetadata (2026-07-05)

User simplified memory-summary attachment to `EnsuredMessage`:
- **Deleted** `BaseBotHandler.getUserMemorySummary` (folded into `EnsuredMessage`).
- **New method** `EnsuredMessage.applyUserMetadata(metadata)` (renamed from `setUserMetadata` to avoid collision with the DB-writer `BaseBotHandler.setUserMetadata`). It's a PURE READER: reads `memoryRefinement[str(self.threadId or DEFAULT_THREAD_ID)].summary` → `self.userSummary`; does NOT persist metadata. Two call sites: `base.py` `_updateEMessageUserData` and `manager.py` `_processMessageRec`, both now do `ensuredMessage.applyUserMetadata(await self.cache.getUserMetadata(...))`.
- **Removed the `MEMORY_REFINEMENT_ENABLED` injection gate** (intentional simplification — the write side still gates, so absence-of-summary-in-metadata is the gate; a stale summary for a since-disabled chat now still injects, accepted). Documented in the method docstring + ADR-014.
- **Naming disambiguation**: `EnsuredMessage.applyUserMetadata` (pure reader) vs `BaseBotHandler.setUserMetadata` (DB writer). The `applyUserMetadata` docstring cross-references this explicitly.
- **Lock widening (same session)**: the user ALSO restructured `BaseBotHandler.setUserMetadata` so `async with self.cache.chatUserMetadataLock():` wraps the ENTIRE method body (both `isUpdate=True` and `isUpdate=False`). See the updated "Metadata RMW lock" note under "Chat Users Cache" above. Docstring Note + test (`test_setUserMetadata_fullReplace_alsoAcquiresMetadataLock`, `enterCount == 1`) reconciled.
- **Tests**: `TestGetUserMemorySummary` deleted from `tests/bot/common/handlers/test_base.py`; 4 extraction cases relocated to `tests/bot/models/test_ensured_message.py::TestApplyUserMetadata` (drives `applyUserMetadata` directly, no DB fixture needed — simpler than the old DB-backed suite; adds an explicit empty-string-summary case). 2 regression tests in `test_user_info_cache_regression.py` re-pointed at `cache.getUserMetadata`.
- **Canonical docs updated**: `memories/user-memory-refinement.md`, `architecture.md` ADR-014 (context-injection bullet), `handlers.md`. Two historical plan docs got addendum-only correction notes (bodies preserved as snapshots).

## Empty TRUNCATED_FINAL LLM Bug (2026-07-05)

Recurring production failure: OpenAI-compatible API returns `finish_reason="length"` with empty `message.content` (suspected reasoning-token budget exhaustion on Qwen3-class models — failing logs show `outputTokens=32768` matching `max_tokens`). Empty content flows unchecked through every layer → `send_message(text="")` → `telegram.BadRequest: Message text is empty`. Plan: [`docs/plans/llm-empty-truncated-final-handling-v1.md`](../plans/llm-empty-truncated-final-handling-v1.md) (Options A–E, A+B recommended next).

**Durable code-path facts (verified 2026-07-05, line numbers approximate — re-locate by symbol):**
- `lib/ai/models.py` `ModelResultStatus`: NO bare `TRUNCATED`, NO `SUCCESS`. "Success" is named `FINAL = 3`. `TRUNCATED_FINAL = 2`.
- `lib/ai/models.py` `ERROR_STATUSES` frozenset does NOT include `TRUNCATED_FINAL` or `PARTIAL` → both treated as success by `_runWithFallback` (`lib/ai/abstract.py`).
- `lib/ai/providers/basic_openai_provider.py::_executeChatCompletion`: `finish_reason="length"` → `TRUNCATED_FINAL`; `resText = retMessage.content if retMessage.content else ""`. The STRUCTURED path (`_generateStructured`) has `if not outcome.resText: raise ValueError(...)` — the TEXT path (`_generateText`) does NOT. Central inconsistency.
- `lib/ai/abstract.py::printJSONLog` skips empty results (`if not result.resultText: return`) — so file JSON log also misses this case.
- `internal/services/llm/service.py::generateTextViaLLM`: only special-cases `FINAL` and `TOOL_CALLS`; `TRUNCATED_FINAL` falls through to `break`.
- `internal/bot/common/handlers/llm_messages.py`: `lmRetText = mlRet.resultText.strip()` → no guard before `sendMessage`.
- `internal/bot/common/bot.py::_sendTelegramMessage`: guard rejects `None` text only, NOT empty string `""`.
- `"Message text is empty"` string does NOT exist in repo — it's python-telegram-bot's `BadRequest` message text.
- YC SDK provider (`lib/ai/providers/yc_sdk_provider.py:487`) returns `result.alternatives[0].text` with no emptiness check — same hazard.

**Item 1 IMPLEMENTED (2026-07-05):** observability-only WARNING dump added in `BasicOpenAIModel._executeChatCompletion`. Trigger: `not resText.strip() and status in (TRUNCATED_FINAL, CONTENT_FILTER, UNKNOWN)`. Dumps: finishReason, status, resText, token counts, `completion_tokens_details` (exposes `reasoning_tokens` — the diagnostic for the budget-exhaustion hypothesis), `prompt_tokens_details`, full `response.model_dump_json(indent=2)`. All vendor-object serialization wrapped in try/except with `str()` fallback so the observability probe can never mask the original outcome. No behavior change — empty TRUNCATED_FINAL still flows downstream; fix is Options A+B in the plan.

## Docs Archive Layout (2026-07-04)

- `docs/plans/` now holds ONLY active/retained design refs. After the 2026-07-04 cleanup it contains a single file: `python-sandboxing-v1.md` (retained design ref for `lib/sandbox/`; status line updated to "implemented").
- `docs/design/` holds 2 retained docs: `markdown-specification.md` (living grammar spec) and `vector-search-native.md` (forward-looking pgvector/MySQL/SQLink contract; SQLite path implemented).
- `docs/database-multi-source.md` (at docs/ root, NOT in plans/) is the relocated operational reference for the multi-source DB architecture (was `docs/plans/database-multi-source-configuration.md`).
- `docs/archive/plans/README.md` and `docs/archive/design/README.md` are the authoritative indexes of archived docs with one-line descriptions. Update them when archiving new docs.
- Frozen historical session/review snapshots live under `docs/archive/llm-sessions/` and `docs/archive/review/` (relocated from `docs/llm-sessions/` and `docs/review/` on 2026-07-04). They retain old `docs/plans/...`-style internal paths intentionally — they are snapshots, not active cross-references. Do not rewrite their content.

## Docs Reorg Lessons (2026-07-04)

- When bulk-moving docs with `git mv`, sibling-relative links INSIDE the moved files are the easy-to-miss gap. A dev reported "fixed relative links" but Gate 1 review caught 3 unfixed sibling links in a retained doc pointing to a moved companion. Always grep the moved files' OWN content for sibling refs after relocation.
- Source-tree READMEs (`lib/*/README.md`, `internal/services/*/README.md`) and code-doc comments (`*.py` docstrings, migration module docstrings) also reference design/plan docs — these are easy to miss because they're outside `docs/`. Grep `lib/` and `internal/` for `docs/plans/` and `docs/design/` paths, not just `docs/`.
- `configs/00-defaults/*.toml` files carry doc-path references in comments (e.g. `# See docs/plans/chat-history-search-plan.md`). These need repointing too.
- A status-line-only edit can create an internal contradiction if the doc has a separate `Scope:` line making similar claims — reconcile ALL status/scope/phase headers, not just the one flagged.
- For docs-only reorgs: `make lint` is the only needed gate (no `make test`); black/isort are no-ops on .md and comment-only .py edits.

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
