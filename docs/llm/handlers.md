# Gromozeka — Handler System

> **Audience:** LLM agents  
> **Purpose:** Complete guide to creating, modifying, and registering bot command handlers  
> **Self-contained:** Everything needed for handler work is here

---

## Table of Contents

1. [Handler Files Reference](#1-handler-files-reference)
2. [Handler Creation Checklist](#2-handler-creation-checklist)
3. [Handler Skeleton Template](#3-handler-skeleton-template)
4. [Command Decorator Pattern](#4-command-decorator-pattern)
5. [Registering Handlers in HandlersManager](#5-registering-handlers-in-handlersmanager)
6. [Handler Chain Order](#6-handler-chain-order)
7. [HandlerResultStatus Reference](#7-handlerresultstatus-reference)
8. [Chat Accessibility Tracking](#8-chat-accessibility-tracking)

---

## 1. Handler Files Reference

**Directory:** [`internal/bot/common/handlers/`](../../internal/bot/common/handlers/)

| File | Handler Class | Purpose |
|---|---|---|
| [`base.py`](../../internal/bot/common/handlers/base.py) | `BaseBotHandler` | Abstract base for all handlers |
| [`manager.py`](../../internal/bot/common/handlers/manager.py) | `HandlersManager` | Orchestrates all handlers |
| [`message_preprocessor.py`](../../internal/bot/common/handlers/message_preprocessor.py) | `MessagePreprocessorHandler` | First in chain; saves message + processes media. **Media transcription (STT)** is folded directly into the inherited `BaseBotHandler._processMediaV2` (the per-attachment media method this handler delegates to via `processTelegramMedia`/`processMaxMedia`) — it is **not** a separate `STTHandler`. For `VIDEO`/`VIDEO_NOTE`/`VOICE`/`AUDIO` attachments, transcription fires only when **four** gates are all on: config `[stt].enabled` (cached in `BaseBotHandler.__init__` as `_sttEnabled`, mirrors `_searchEnabled`), an eligible media type, and the per-chat `PARSE_ATTACHMENTS` **and** `TRANSCRIBE_MEDIA` settings (the latter is `FRIEND`-page; both default `false`). `PARSE_ATTACHMENTS` is the general attachment-processing gate (it gates any attachment processing, not just images); `TRANSCRIBE_MEDIA` is the additional opt-in for the expensive STT sub-feature, so transcription requires *both*. When the gate is on, `_processMediaV2` persists the row as `PENDING`, downloads the bytes once (shared download block — when `SAVE_ATTACHMENTS` + STT are both on, the SAVE block downloads first and STT reuses the bytes via an `if mediaData is None` guard), and schedules a fire-and-forget background task (`_transcribeMedia(mediaId, chatId, data)` via `queueService.addBackgroundTask`) that calls `STTService.transcribeMedia(data, chatId=...)` and terminalizes the row via plain `updateMediaAttachment` (`PENDING`→`DONE`+transcript on success | `PENDING`→`FAILED` on failure/exception; `asyncio.CancelledError` propagates and leaves the row `PENDING` for orphan-reclaim). The transcript lands in `media_attachments.description` and reaches the model as a structured JSON `mediaDescription` field through the existing render path. STT **mirrors the image-parsing pattern**: `ret.task = sttTask` (the live STT background task), so `EnsuredMessage.updateMediaContent()` awaits the task and then confirms via the DB poll in `_awaitMedia` (~300 s cap). See [`services.md`](services.md) §7, [ADR-020](architecture.md#adr-020-sttservice--synchronous-stateless-stt-service-and-dependency-firewall), and [`docs/design/media-transcription-stt-v1.md`](../design/media-transcription-stt-v1.md) §12. Also owns **memory injection** — `injectMemories()` runs inside `newMessageHandler` **after** `saveChatMessage(...)` to load permanent memories (via `cache.getChatUserPermanentMemories`) + ephemeral memories (`getLatestMemories`, or `searchMemories` driven by `LLMService.generateEmbedding` when memory embeddings are on — i.e. `MEMORY_ENABLED && EMBEDDINGS_ENABLED`). Since the context-dedup change (ADR-018) it writes **compact memory IDs** directly into `metadata["memories"]` (`{"permanentIds": [...], "shortTermIds": [...]}`) — no `setUserMemories` setter and no per-message `userMemories` content field (both removed). It performs **no cache warming**: the by-id cache populates lazily (cache-aside) on the first `formatForLLM` read via `cache.getMemoriesByIds`. Because `injectMemories()` mutates `metadata` after the row was already saved, the compact IDs are re-persisted to `chat_messages.metadata` via a separate `db.chatMessages.updateChatMessageMetadata(...)` call. Resolution is lazy: each render site calls `toModelMessage(..., cache=self.cache, excludeMemoryIds=...)` and `formatForLLM` resolves IDs → content on-demand via `cache.getMemoriesByIds`; in `getThreadByMessageForLLM` and `handleRandomMessage` dedup is applied inline newest→oldest (an accumulating exclude-set per call site; no shared helper). Enforcement is split: `cache=` is a **required keyword-only** param on every render method (no default — pyright errors on any caller that omits it), while `excludeMemoryIds: Optional[Set[str]] = None` carries an `= None` default and is coerced to `set()` in the method body, so pyright does **not** enforce its presence (intentional — every dedup call site passes it explicitly, but incidental render paths may omit it). There is no AST value-checking guard — value-correctness (i.e. `cache=self.cache` on chat paths vs `cache=None` on non-chat/TEXT paths) is upheld by the call-site audit and the test suite. Gated by `MEMORY_ENABLED`; see [`memories/user-memories.md`](memories/user-memories.md) "Injection" / "Render-time resolution (lazy + dedup)" |
| [`spam.py`](../../internal/bot/common/handlers/spam.py) | `SpamHandler` | Spam detection (runs after preprocessor) |
| [`configure.py`](../../internal/bot/common/handlers/configure.py) | `ConfigureCommandHandler` | Chat settings configuration |
| [`summarization.py`](../../internal/bot/common/handlers/summarization.py) | `SummarizationHandler` | Chat summarization |
| [`user_memories.py`](../../internal/bot/common/handlers/user_memories.py) | `UserMemoriesHandler` | Unified per-`(chat, user, thread)` structured memory system (the `user_memories` store — supersedes the old `user_data` key-value tools and the rolling-bio `userSummary` blob; see [`architecture.md`](architecture.md) ADR-016). Registers three LLM tools — `add_memory` / `delete_memory` / `search_memories` (`ToolName.ADD_MEMORY` / `DELETE_MEMORY` / `SEARCH_MEMORIES`) — gated on the global `[user-memory].enabled` kill switch (no registration when off → nothing exposed via the chat-time `useTools` wildcard); all three resolve chat context from `extraData["ensuredMessage"].recipient.id` / `.sender.id` / `.threadId`. `delete_memory` is **refinement-only at chat time** — `_sendLLMChatMessage` forces `useTools[DELETE_MEMORY] = False` on every chat-time turn (D3 gating), so it is only ever callable from the refinement pass. `newMessageHandler` increments an in-memory per-`(chatId, userId, threadId)` counter (gated by the `MEMORY_REFINEMENT_ENABLED` chat setting; refinement dispatch also requires `MEMORY_ENABLED=true && EMBEDDINGS_ENABLED=true` — the scan gate re-checks all three because memory embeddings are on only then and the `search_memories` tool is semantic and returns nothing without them; intentional asymmetry: `_runSingleRefinement`'s runtime re-check stays `MEMORY_REFINEMENT_ENABLED`-only) at the very top — before any gates — and returns `NEXT`. Registers a `CRON_JOB` (`_dtCronJob`, every 60s) that, under a single global `asyncio.Lock` (`_refineLock`), scans the counter and runs up to `max-refines-per-tick` refinements sequentially (a slow LLM call makes subsequent ticks early-return rather than flood the provider). `_runSingleRefinement` (Phase 4a rewrite) no longer emits a summary — it pre-loads permanent + latest memories, renders them into the `{existingMemories}` prompt placeholder, and lets the refinement LLM curate the store **live** via the three tools (`extraData["isRefinement"] = True` so `add_memory` surfaces the dedup grey-zone signal); only the message cursor is persisted to `chat_users.metadata.memoryRefinement` via direct `updateUserMetadata` read-modify-write (NOT `setUserMetadata` — shallow-merge gotcha). A second cron body `_runMemoryEmbeddingRegen` runs every tick **outside** `_refineLock` (mirrors `ChatSearchHandler._dtCronJob` one-to-one): discovers chats by round-robin over the in-memory `_trackedChats` set (populated by `newMessageHandler` when `MEMORY_ENABLED` + `EMBEDDINGS_ENABLED` are both true — i.e. memory embeddings on; no DB scan; cold-start: empty on restart, grows only from live messages; eviction is one-way), detects model drift, and re-embeds stale rows in batches of `memory-reindex-batch-size` — never raises (a regen failure never breaks the refinement body sharing the same tick). Memory injection into chat context is **centralised** in `MessagePreprocessorHandler.injectMemories()` (called at message-arrival time, before the message is saved; compact memory IDs are persisted into `chat_messages.metadata.memories` and ride per-message — resolution is lazy in `formatForLLM`, JSON key `userMemories`). The previous `BaseBotHandler._buildMemoriesBlock` / `_injectMemoriesBlock` helpers and the four handler-level injection sites were deleted in the refactoring — there is no `<user-memories>` system-message block any more. Embeddings (regen cron + the `add_memory`/`search_memories`/`delete_memory` tools) are produced via `LLMService.generateEmbedding(text, chatId, chatSettings) -> Optional[Tuple[modelName, List[float]]]`; the old `internal/bot/common/memory_embedding_utils.py` module (`embedAndSaveMemory`) and the `UserMemoriesHandler._resolveEmbeddingModel` / `_floatsToBytes` helpers were removed (the old `EnsuredMessage.userSummary` / `applyUserMetadata` path was removed entirely in Phase 4b). The memory chat settings (`MEMORY_ENABLED` (master gate for all memory features) / `MEMORY_REFINEMENT_ENABLED` / `MEMORY_REFINE_MODEL` / `MEMORY_REFINE_FALLBACK_MODEL` / `MEMORY_REFINE_SYSTEM_PROMPT` / `MEMORY_REFINE_USER_PROMPT_TEMPLATE`) are user-configurable via `/settings` (page `FRIEND`). Memory embeddings are a derived condition (`MEMORY_ENABLED && EMBEDDINGS_ENABLED`), not a separate flag — three former memory-embedding settings (a separate embeddings-on flag, a regen trigger, and a latest/relevant retrieval-mode selector) were dropped in the chatSettings consolidation. Owns `/memory_config` — an interactive wizard over the `user_memories` store (shipped in Phase 5): add memories, view/list them, delete by id, and filter by tag. Optional `[user-memory.json-logging]` writes one JSONL line per successful refinement run with per-tool counts (`addCount` / `deleteCount` / `searchCount` — the primary observability for the grey-zone dedup review); see [`configuration.md`](configuration.md) §`[user-memory.json-logging]`. See [`architecture.md`](architecture.md) ADR-016 (unified-store decision) and ADR-014 (refinement machinery), and [`memories/user-memories.md`](memories/user-memories.md) (canonical durable summary). |
| [`dev_commands.py`](../../internal/bot/common/handlers/dev_commands.py) | `DevCommandsHandler` | Developer/debug commands |
| [`media.py`](../../internal/bot/common/handlers/media.py) | `MediaHandler` | Media message processing |
| [`common.py`](../../internal/bot/common/handlers/common.py) | `CommonHandler` | Common bot commands |
| [`help_command.py`](../../internal/bot/common/handlers/help_command.py) | `HelpHandler` | `/help` command |
| [`delete_from_user.py`](../../internal/bot/common/handlers/delete_from_user.py) | `DeleteFromUserMessageHandler` | Telegram-only auto-delete of messages from configured authors (via `DELETE_AUTHOR_LIST` chat setting, a JSON array of user IDs and usernames). Commands: `/set_delete_author`, `/unset_delete_author`, `/dump_delete_authors`. `newMessageHandler` returns `FINAL` on successful deletion so downstream handlers (e.g. `ReactOnUserMessageHandler`, `LLMMessageHandler`) skip the deleted message; `SKIPPED` otherwise. Modeled on `ReactOnUserMessageHandler`. |
| [`react_on_user.py`](../../internal/bot/common/handlers/react_on_user.py) | `ReactOnUserMessageHandler` | Telegram-only reactions |
| [`topic_manager.py`](../../internal/bot/common/handlers/topic_manager.py) | `TopicManagerHandler` | Telegram forum topics |
| [`weather.py`](../../internal/bot/common/handlers/weather.py) | `WeatherHandler` | Weather commands (if enabled). Proxy: resolves proxy separately for `OpenWeatherMapClient` and `GeocodeMapsClient` in `__init__()`, using the `[openweathermap]` and `[geocode-maps]` config sections respectively. |
| [`yandex_search.py`](../../internal/bot/common/handlers/yandex_search.py) | `YandexSearchHandler` | Yandex Search (if enabled). Proxy: resolves proxy in `__init__()` for both the Yandex Search client and the `_downloadUrl()` web-fetch method. HTTP/2 is always enabled for web-fetch (negotiated via TLS ALPN above the proxy tunnel; degrades gracefully to HTTP/1.1). |
| [`resender.py`](../../internal/bot/common/handlers/resender.py) | `ResenderHandler` | Message resending (if enabled). Architecturally distinct: a **cron-only** handler — does **not** override `newMessageHandler`, has no slash commands, no LLM tools. Operates entirely from `_dtCronJob` (≈60s tick via `QueueService`), passively scanning for new messages with `getChatMessagesSince()`. Registers `DO_EXIT` (`_dtOnExit`) to flip `isExiting = True` on shutdown. |
| [`divination.py`](../../internal/bot/common/handlers/divination.py) | `DivinationHandler` | `/taro` & `/runes` readings (if `divination.enabled`) — includes layout discovery via LLM + web search |
| [`sandbox.py`](../../internal/bot/common/handlers/sandbox.py) | `SandboxHandler` | Sandboxed Python code execution (if `sandbox.enabled` and `allow-sandbox` chat setting). Commands: `/run <code>` (alias: `/python`), `/sandbox files|read|status|install`. LLM tools: `run_python(code)`, `sandbox_list_files`, `sandbox_read_file`, `sandbox_send_file`, `sandbox_list_libraries`. Lifecycle: registers `CRON_JOB` (periodic GC) and `DO_EXIT` (graceful shutdown) delayed-task handlers; performs one-time `SandboxManager.recover()` on first cron tick to reconcile stale containers after restarts. |
| [`chat_search.py`](../../internal/bot/common/handlers/chat_search.py) | `ChatSearchHandler` | Chat-history search (if `[search-history].enabled`). Commands: `/search [args]` (DSL of `keywords` / `user` / `days` / `category` / `thread` filters) — returns the matching messages as a raw, human-readable list (no LLM summary); `/users [limit=N] [min_messages=N] [last_active=N]` — lists chat participants with activity statistics. LLM tools: `search_messages(query, limit, max_age_days, user_name, thread_message_id, current_thread_only, substring)` — semantic search over chat history; when `query` is empty the search degrades to a substring/filter-only lookup that runs WITHOUT `EMBEDDINGS_ENABLED` (no embedding generated); `current_thread_only` (default `true`) scopes results to the current thread/topic and is overridden by an explicit `thread_message_id`; `substring` is a case-insensitive exact-text filter; `list_users(limit, min_messages)` — list participants with stats; `get_thread(message_id)` — retrieve full conversation thread; `get_messages_by_ids(message_ids)` — batch-fetch full content of messages by ID (`ToolName.GET_MESSAGES_BY_IDS`, returns `{messages:[...], notFound:[...], count:N}`; reuses `_formatMessageDict`; never-raise). Used by the model to read the originals underlying a condensed summary (summaries render their `coveredMessageIds` — see [`architecture.md`](architecture.md) ADR-019). **Two-layer gating**: (1) `[search-history].enabled` via the handler's conditional registration (the tool is a normal `registerTool(...)` in `__init__` — *no manager.py change*); (2) at chat time, all four LLM tools (`search_messages`, `list_users`, `get_thread`, `get_messages_by_ids`) are gated solely by `USE_TOOLS` — the model is never sent the tools when `USE_TOOLS=false`. They are NOT gated by `ALLOW_TOOLS_COMMANDS` (which gates only slash commands of `CommandCategory.TOOLS`). `get_messages_by_ids` is additionally **NOT** gated on `EMBEDDINGS_ENABLED` — it is a pure DB lookup (available whenever chat-search is on, even with semantic search disabled). Accepts a list of ID strings (`extra={"items": {"type": "string"}}`); input clamped to `MAX_GET_MESSAGES_BATCH` (32). `newMessageHandler` is pass-through (`SKIPPED`); work runs via the command. Lifecycle: registers `CRON_JOB` (`_dtCronJob` — embedding backfill for chats with `EMBEDDINGS_ENABLED=true`, round-robin across enabled chats, default batch `BACKFILL_DEFAULT_BATCH_SIZE` messages) delayed-task handlers. There is no separate `BackfillWorker` class — backfill duty lives in this handler. |
| [`stats.py`](../../internal/bot/common/handlers/stats.py) | `StatsHandler` | Usage-statistics display (if `[stats].enabled`; `__init__` raises `RuntimeError` when stats are disabled — belt-and-suspenders, since registration in `manager.py` is itself conditional). Commands: `/stats` and `/stats_web` — ONE `@commandHandlerV2` registration with `commands=("stats", "stats_web")`; invoking `stats_web` forces web mode. Category `TOOLS` (rides the `allow-tools-commands` gate). Grammar: at most one positional `help` \| `chatId` (negative numbers are positionals — group IDs), options `--period=1d|7d|30d|all` (default `7d`), `--section=messages|commands|tools|llm` (default `messages`), `--user=<id>`, valueless `--web`; any parse error replies with the usage text. Scoping: group → current chat only; private → the user's private-chat stats plus a top-10 chat list (via `getUserChats`, sorted by `messages_count`); positional `chatId` (private only, membership-checked) → full four-section drill-down; `--user=<id>` → per-user breakdown over messages/commands/tools (the `llm` section is annotated chat-level — `llm_request` rows carry no `user_id` label). Chat-setting gate: `ALLOW_SHOW_STATS` (`allow-show-stats`, default `true`) — group/channel ONLY; when disabled the handler sends an informative reply with zero stats queries; not consulted in private chats. Reads via `StatsAggregationService.getQueryStorage(eventType)` + `StatsAnalyzer` (pure-Python filtering; the `consumer` label filter excludes `__global__` rows; message counts split into users/bot/history buckets via the `sent` label). Output capped at `_MAX_OUTPUT_LENGTH = 2500` chars (whole lines only); STT stats folded into the `llm` section. Web tier (`--web`/`/stats_web`, gated by `[stats-pages]`): config is read at construction via `getStatsPagesConfig()` — when `enabled = true` it is validated fail-loud (`base-url` non-empty str; `generate-command`/`delete-command` non-empty `list[str]` of non-empty strings; `ttl-hours` positive int — `RuntimeError` naming the offending key) and the `_dtStatsPagesCleanup` delayed-task handler (`DelayedTaskFunction.STATS_PAGES_CLEANUP`) is registered; when `enabled = false` (default) there is no validation and no registration, and `--web` gets the informative "disabled" reply. When enabled, `--web` runs: per-ISSUING-chat rate-limit pre-check (`RateLimiterManager.getStats` on the `ratelimiter-queue` queue, key `stats-pages-<issuing chatId>`; never-used key → `ValueError` → treated as 0 used; `RuntimeError` → brief+note+return; full window → refuse with an informative reply, CLI never invoked), payload build (same analysis data as the chat brief; typed section dicts with `possiblyIncomplete` flags; `chatList` when private ∧ no `--user` filter), `{user_id}`/`{chat_id}`/`{platform}` substitution into `generate-command`, subprocess via `runCliCommand` ([`lib/stats/stats_pages/launcher.py`](../../lib/stats/stats_pages/launcher.py); 30 s timeout, kill on timeout; payload on stdin as JSON), stdout `{"id","url"}` → reply link `base-url + "/" + url`, then ONE persisted one-shot `STATS_PAGES_CLEANUP` deletion task (`delayedUntil = now + ttl-hours × 3600`, `kwargs = {"pageId", "command"}` with the `delete-command` argv `{page_id}`-substituted, `skipDB=False`; pending task with handler absent re-delays in memory for process lifetime but DB row marked done on first firing — after restart the task is gone; orphaned page file is the accepted R13 outcome). On ANY web-tier failure the in-chat brief is still delivered plus a one-line failure note (WARNING log) — nothing raises out of `statsCommand`. The cleanup task runs the resolved argv once (30 s timeout), tolerates `{"deleted": 0}`, and completes on failure (WARNING; no reschedule). See [`configuration.md`](configuration.md) `[stats-pages]`. |
| [`llm_messages.py`](../../internal/bot/common/handlers/llm_messages.py) | `LLMMessageHandler` | **LAST** in chain; LLM responses. Wraps `LLMService.generateTextViaLLM` via `_generateTextViaLLM`, forwarding a `useTools` value (`bool \| dict[str, bool]`, type alias `UseToolsType`) that supports per-tool enable/disable with a `TOOLS_DEFAULT_DICT_KEY` fallback (see [`services.md`](services.md)). When constructing the dict form, use members of the `ToolName` StrEnum from [`internal.bot.constants`](../../internal/bot/constants.py) as keys (raw strings also work since `ToolName` is a `StrEnum`). Default `useTools` comes from the `USE_TOOLS` chat setting (`.toBool()` — callers wanting dict-level control must bypass the setting and pass a dict explicitly). **`newMessageHandler` gating order** (each gate can short-circuit with `SKIPPED`/`FINAL`): (1) **bot-sender probability gate** — if the sender's username ends with `bot`, the message is skipped unless a `random.random()` roll passes the `BOT_ANSWER_PROBABILITY` chat setting (default `0.05`); `0.0` = never answer bots. This gate runs **before** reply/mention, so even explicit replies or mentions from bot accounts are throttled — intentional, to prevent bot-to-bot reply loops; (2) `handleReply` (reply to a bot message); (3) `handleMention` (bot mentioned); (4) `handleRandomMessage` (`RANDOM_ANSWER_PROBABILITY`). `_sendLLMChatMessage` returns `LLMReplyOutcome` (`SENT` / `SKIPPED_BY_MODEL` / `ERROR`), not `bool` — callers compare `== LLMReplyOutcome.SENT`, never truthiness. `handleRandomMessage` additionally appends `RANDOM_ANSWER_PROMPT` to the system message (both thread and non-thread paths) and abstains on `SKIPPED_BY_MODEL` (see "Random-answer context & model abstention" below). |
| [`example.py`](../../internal/bot/common/handlers/example.py) | `ExampleHandler` | Standalone reference example (not registered in handler chain) |
| [`example_custom_handler.py`](../../internal/bot/common/handlers/example_custom_handler.py) | `ExampleCustomHandler` | Template for custom handlers |

**`DivinationHandler` — reply behavior by invocation path:**

- **Slash-command path** (`/taro`, `/runes`): the handler renders a **structured reply template** (`DIVINATION_REPLY_TEMPLATE` chat setting) containing the layout name, a numbered drawn-symbols block (with position, localized name, and reversal flag), and the LLM interpretation. This lets users verify the LLM didn't hallucinate any cards. Photo (if image generation succeeded) is sent as caption + image in one `sendMessage` call
- **LLM-tool path** (`do_tarot_reading` / `do_runes_reading`, `invoked_via = 'llm_tool'`): the handler returns the **bare LLM interpretation** in the JSON tool result (fields: `done`, `summary`, `imageGenerated`, `layout`, `draws`, `interpretation`) so the host LLM can incorporate it naturally — no text bot message is sent. Only the generated image (if `image-generation = true` and generation succeeded) is sent directly to the user with an empty caption. The template is NOT applied on this path.

### Layout Discovery (Multi-Tier Resolution)

When `divination discovery-enabled = true`, unknown layouts trigger automatic discovery:

**Resolution tiers (from highest to lowest priority):**

1. **Predefined layouts** in `lib/divination/layouts.py` (`TAROT_LAYOUTS`, `RUNES_LAYOUTS`)
2. **Cached layouts** from `divination_layouts` table (Database cache, includes negative cache for failed discoveries)
3. **LLM + Web Search discovery** (if enabled):
   - Call 1: `LLMService.generateText(tools=True)` with web search to find layout info
   - Call 2: `LLMService.generateStructured()` to parse into structured JSON schema
   - Save: Persist successful layouts to `divination_layouts` cache
   - Negative cache: Failed discoveries stored with `name_en=''`, `n_symbols=0` (24-hour TTL)

**Discovery prompts** (configured via chat settings):
- `divination-discovery-system-prompt` — System instruction for both LLM calls
- `divination-discovery-info-prompt` — Prompt for web search (first call)
- `divination-discovery-structure-prompt` — Prompt for structured JSON parsing (second call)

**Negative cache pattern:** Prevents repeated failed discovery attempts for the same non-existent layout. Stored as a special entry in `divination_layouts` with empty name and zero symbols.

### DevCommandsHandler Commands

Developer/debug commands available only to `BOT_OWNER` users.

#### `/llm_replay <model_name>`

- **Class:** `DevCommandsHandler` (`internal/bot/common/handlers/dev_commands.py`)
- **Permission:** `BOT_OWNER`
- **Description:** Replays an LLM conversation from an attached JSON log file through `LLMService.generateTextViaLLM` with all registered tools available. Useful for debugging prompts and LLM behavior with the same tool context as production.
- **Usage:** Send `/llm_replay <model_name>` with a JSON document attachment (or as a reply to a JSON document message). The model name must be a known model in the LLM configuration (e.g., `gpt-4o`, `openrouter/claude-haiku-4.5`).
- **Flow:**
  1. Validates the model name argument
  2. Downloads and parses the attached JSON file
  3. Reconstructs `ModelMessage` objects from the log's `request` array via `internal.services.llm.utils.reconstructMessages()`
  4. Calls `LLMService.generateTextViaLLM()` with the specified model, chat tool settings, and all registered tools
  5. Streams intermediate results back to chat via callback
  6. Reports final summary: model, status, token counts, tool calls, elapsed time
- **Related scripts:** `scripts/run_llm_debug_query.py` (CLI-based replay without tools), `scripts/convert_readable_to_llm_log.py` (YAML-to-JSON conversion)

### Random-answer context & model abstention (`LLMMessageHandler`)

`handleRandomMessage` (the `RANDOM_ANSWER_PROBABILITY` gate) is structurally different from `handleReply` / `handleMention`: the bot is joining an ongoing chat, not being directly addressed. Two pieces let the model behave accordingly:

1. **`RANDOM_ANSWER_PROMPT` suffix.** In **both** system-message assembly paths inside `handleRandomMessage` the `RANDOM_ANSWER_PROMPT` chat setting (TOML key `random-answer-prompt`, page `LLM_PROMPTS`; default in [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml)) is appended to the existing `CHAT_PROMPT` + `CHAT_PROMPT_SUFFIX` system message:
   - **Thread path** — after `getThreadByMessageForLLM(...)` returns, the leading system `ModelMessage` is rebuilt with the fragment appended (the returned list is fresh and not shared, so it is rebuilt rather than mutated).
   - **Non-thread path** — the inline `ModelMessage(role="system", ...)` is constructed with `CHAT_PROMPT + CHAT_PROMPT_SUFFIX + RANDOM_ANSWER_PROMPT` in one content string.

   `handleReply` and `handleMention` **never** append this fragment — they are explicit addresses and the bot always answers.

2. **`<skip>` abstention sentinel.** The `random-answer-prompt` default tells the model: if it has nothing natural to add, return exactly `<skip>` (optionally surrounded by whitespace / backticks). Detection lives in `_sendLLMChatMessage`, **after** JSON-unwrap + `<media-description>` extraction and **before** the image-generation branch:
   ```python
   if lmRetText.strip().strip("`").strip() == "<skip>":
       logger.debug("Model abstained (<skip>), not sending a reply")
       return LLMReplyOutcome.SKIPPED_BY_MODEL
   ```
   Placing it after JSON-unwrap means a JSON-wrapped `{"text": "<skip>"}` also abstains; placing it before the image branch means `<skip>` never triggers image generation. Only `random-answer-prompt` requests `<skip>`, but detection is global in `_sendLLMChatMessage` (any `<skip>` output abstains) — see plan §9 risk #2.

#### `LLMReplyOutcome` return type

`_sendLLMChatMessage` returns [`LLMReplyOutcome`](../../internal/bot/common/handlers/llm_messages.py) (a `StrEnum`), not `bool`:

| Member | Meaning |
|---|---|
| `SENT` | Message was generated and sent successfully. |
| `SKIPPED_BY_MODEL` | Model returned the `<skip>` sentinel; nothing was sent. |
| `ERROR` | Generation or send failed; the error notification has already been logged. |

Call sites:
- `handleRandomMessage` treats `SKIPPED_BY_MODEL` and `ERROR` identically — returns `False`, so `newMessageHandler` falls through to `HandlerResultStatus.NEXT` (as far as the rest of the chain is concerned, the bot didn't handle the message; `NEXT` rather than `SKIPPED` because the random path did run, it just chose to do nothing).
- `handleReply` / `handleMention` compare `!= LLMReplyOutcome.SENT` to preserve their previous error-swallow / return-`False` semantics respectively. Those paths never trigger abstention (the prompt isn't appended there), so `SKIPPED_BY_MODEL` is unreachable from them in practice.

**Callers must compare `== LLMReplyOutcome.SENT` explicitly — never use truthiness.** All three members are truthy strings.

---

## 2. Handler Creation Checklist

Step-by-step for adding a new bot command handler

### Step 1: Create handler file

**Path:** `internal/bot/common/handlers/my_handler.py`

Use the skeleton from [Section 3](#3-handler-skeleton-template)

### Step 2: Register handler in `HandlersManager`

**File:** [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py) (`HandlersManager.__init__`, the `self.handlers: List[HandlerTuple] = [...]` literal)

See [Section 5](#5-registering-handlers-in-handlersmanager) for registration code

### Step 3: Define commands with decorator

Use `@commandHandlerV2` — see [Section 4](#4-command-decorator-pattern)

### Step 4: Implement `newMessageHandler` (if needed)

Only implement if your handler reacts to non-command messages:
```python
async def newMessageHandler(
    self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
) -> HandlerResultStatus:
    """Process incoming messages

    Args:
        ensuredMessage: The incoming message
        updateObj: Raw update object from platform

    Returns:
        HandlerResultStatus indicating processing result
    """
    # Check if this handler should process this message
    if not self._shouldHandle(ensuredMessage):
        return HandlerResultStatus.SKIPPED

    # Process...
    await self.sendMessage(ensuredMessage, messageText="response")
    return HandlerResultStatus.FINAL
```

### Step 5: Register LLM tools (if handler provides them)

If your handler registers tools for the LLM to call:

1. Add a member to the `ToolName` StrEnum in [`internal/bot/constants.py`](../../internal/bot/constants.py).
2. In your handler's `__init__`, call `self.llmService.registerTool(name=ToolName.YOUR_TOOL, ...)`.
3. Gate registration on your feature's `enabled` config flag.
4. Name the handler method with the `_llmTool*` prefix.

Full details in the [add-handler skill](../../.agents/skills/add-handler/SKILL.md) (Step 5), [`AGENTS.md`](../../AGENTS.md) (tool handler conventions), and [`teamlead-memory.md`](../../docs/llm/teamlead-memory.md) (ToolName StrEnum details).

### Step 6: Write tests

**Path:** `tests/bot/common/handlers/test_my_handler.py` (mirrors the source path `internal/bot/common/handlers/my_handler.py` — strip `internal/`, keep the rest)

See [`testing.md`](testing.md) for test patterns

### Step 7: Run quality checks

```bash
make format lint
make test
```

### Checklist after creating/modifying a handler

- [ ] Docstring on class and all methods
- [ ] Type hints on all method arguments and returns
- [ ] Added handler to `HandlersManager.__init__()` if it's a new built-in handler (the `self.handlers = [...]` literal in [`manager.py`](../../internal/bot/common/handlers/manager.py))
- [ ] OR configured as custom handler via TOML if it's a plugin
- [ ] Added tests in `tests/bot/` directory
- [ ] If handler registers LLM tools: `ToolName` member added, `registerTool(name=ToolName.XXX, ...)` used, gated on feature flag.
- [ ] Ran `make format lint` and `make test`

---

## 3. Handler Skeleton Template

```python
"""
Module docstring describing what this handler does
"""

import logging
from typing import Optional

from internal.bot.common.models import UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    commandHandlerV2,
)
from internal.config.manager import ConfigManager
from internal.database.models import MessageCategory
from internal.database import Database

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class MyNewHandler(BaseBotHandler):
    """Handler description

    Attributes:
        configManager: Configuration manager instance
        database: Database wrapper for persistence
        botProvider: Bot provider type
    """

    def __init__(
        self,
        *,
        configManager: ConfigManager,
        database: Database,
        botProvider: BotProvider,
    ):
        """Initialize handler

        Args:
            configManager: Configuration manager
            database: Database wrapper
            botProvider: Bot provider type
        """
        super().__init__(
            configManager=configManager,
            database=database,
            botProvider=botProvider,
        )

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """Process incoming messages

        Args:
            ensuredMessage: The incoming message
            updateObj: Raw update object from platform

        Returns:
            HandlerResultStatus indicating processing result
        """
        # Return SKIPPED if this handler doesn't apply
        return HandlerResultStatus.SKIPPED

    @commandHandlerV2(
        commands=("mycommand",),
        shortDescription="- short description for help",
        helpMessage="Full help message explaining the command",
        visibility={CommandPermission.DEFAULT},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def myCommand(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        updateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle /mycommand

        Args:
            ensuredMessage: The command message
            command: Command name (e.g. "mycommand")
            args: Arguments string after command
            updateObj: Raw update object
            typingManager: Optional typing indicator
        """
        await self.sendMessage(
            ensuredMessage,
            messageText="Response here",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
```

**Required imports for handler:** Always include all shown above. Additional imports as needed.

**Required patterns:**
- Inherit from `BaseBotHandler`
- Call `super().__init__()` with all three args
- Use `self.sendMessage()` (NOT direct bot API)
- Return `HandlerResultStatus` from `newMessageHandler()`
- Use `@commandHandlerV2` decorator for commands
- Save bot replies via `messageCategory=MessageCategory.BOT_COMMAND_REPLY`

---

## 4. Command Decorator Pattern

### Full decorator signature

```python
@commandHandlerV2(
    commands=("cmd_name",),           # command without /
    shortDescription="- short desc",  # shown in /help list
    helpMessage="Full help text",     # shown in /help cmd_name
    visibility={CommandPermission.DEFAULT},   # who sees it in /help
    availableFor={CommandPermission.DEFAULT}, # who can run it
    helpOrder=CommandHandlerOrder.NORMAL,
    category=CommandCategory.TOOLS,   # permission category
)
async def myCommandMethod(
    self,
    ensuredMessage: EnsuredMessage,
    command: str,
    args: str,
    updateObj: UpdateObjectType,
    typingManager: Optional[TypingManager],
) -> None:
    """Handle /mycommand

    Args:
        ensuredMessage: The command message
        command: Command name without slash
        args: Arguments string after command
        updateObj: Raw update object from platform
        typingManager: Optional typing indicator manager
    """
```

### `CommandPermission` values

| Value | Who it is |
|---|---|
| `DEFAULT` | All users |
| `ADMIN` | Chat admins |
| `BOT_OWNER` | Bot owner from config |
| `DEVELOPER` | Dev accounts |

### `CommandCategory` values

| Value | Purpose |
|---|---|
| `UNSPECIFIED` | Default category for commands without specific categorization |
| `PRIVATE` | Commands for private chats only |
| `ADMIN` | Admin/configuration commands |
| `TOOLS` | Utility/tool commands (Web search, draw, weather, etc.) |
| `SPAM` | SPAM-related commands |
| `SPAM_ADMIN` | SPAM-related commands for admins |
| `TECHNICAL` | Technical/debug commands |

### `CommandHandlerOrder` values

| Value | Purpose |
|---|---|
| `NORMAL` | Standard position in `/help` |
| `FIRST` | Shown at top of `/help` |
| `LAST` | Shown at bottom of `/help` |

---

## 5. Registering Handlers in HandlersManager

**File:** [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py) — `HandlersManager.__init__` builds the `self.handlers: List[HandlerTuple] = [...]` literal (the `LLMMessageHandler` tuple is appended **after** any conditional/custom handlers to preserve the must-stay-last invariant).

The `HandlersManager` constructor accepts:
- `configManager` — `ConfigManager` instance
- `database` — `Database` instance
- `botProvider` — `BotProvider` enum (Telegram or Max)
- `messageStatsStorage` — Optional `StatsStorage` instance for `message` events (both directions; default `NullStatsStorage`)
- `commandStatsStorage` — Optional `StatsStorage` instance for `command` events (default `NullStatsStorage`)

**Command statistics:** When `commandStatsStorage` is provided (not `NullStatsStorage`), `handleCommand()` records a `command` event for every executed command with `command_count=1`, `is_error=0` on success or `is_error=1` on exception. Labels are `user_id` and `commandName` (lowercased, matching handler lookup — `/Help` and `/help` share one bucket). The `consumerId` is the chat ID. Commands denied by permission or category gates (early returns) are **not** recorded. Recording is gated on `[stats] enabled` (default `false`).

```python
# At top of file, add import:
from .my_handler import MyNewHandler

# In HandlersManager.__init__(), add to self.handlers list:
self.handlers: List[HandlerTuple] = [
    # ... existing handlers ...
    (MyNewHandler(configManager=configManager, database=database, botProvider=botProvider), HandlerParallelism.PARALLEL),
    # LLMMessageHandler MUST stay last!
    (LLMMessageHandler(configManager=configManager, database=database, botProvider=botProvider), HandlerParallelism.SEQUENTIAL),
]
```

### Conditional registration (for optional features)

```python
# CORRECT — conditional registration
if self.configManager.getOpenWeatherMapConfig().get("enabled", False):
    self.handlers.append(
        (WeatherHandler(configManager=configManager, database=database, botProvider=botProvider), HandlerParallelism.PARALLEL)
    )
```

### Shutdown state dump

Shutdown diagnostics are emitted by `HandlersManager._dumpAllState()` — a parameterless method with a **single call site**: `shutdown()` awaits it directly after `_shutdownEvent.set()` and **before** per-chat queues are drained (so pending-message counts are still populated). Because there is exactly one caller, there is no DO_EXIT registration and no `_stateDumped` idempotency guard.

`_dumpAllState()` does two things inline (no separate `_dumpChatStates` helper):

1. **Per-chat queue state** — snapshots `chatStates.values()` under `stateLock` (avoids `RuntimeError` from concurrent modification), then inspects each chat's queue under its own per-chat lock. Empty queues are skipped. For each non-empty queue it logs `chat_id=%d.%s pending_messages=%d` — the `%s` is `threadId`, so a `None` thread renders as the literal string `None`. Per-chat errors are isolated via try/except + `logger.warning(..., exc_info=True)`.
2. **Rate limiter state** — calls `RateLimiterManager.getInstance().dumpAllStats()` (see [services.md §5](services.md#5-ratelimitermanager)), which **returns** a `List[RateLimiterStatsEntry]` (one entry per queue across all limiters; the method itself does not log). Each returned entry is logged at INFO via `logger.info(utils.jsonDumps(entry, indent=2))`.

To add new shutdown diagnostics, extend `_dumpAllState()` (or add another step to `shutdown()`). There is no hook registry for this — the DO_EXIT delayed-task mechanism (`queueService.registerDelayedTaskHandler(DelayedTaskFunction.DO_EXIT, ...)`) is used by other subsystems (`SandboxHandler`, `ProxyService`, `ResenderHandler`, plus `HandlersManager._dtOnExit` itself which forwards to `_cleanupOldData`) but is not involved in the state dump.

---

## 6. Handler Chain Order

**CRITICAL ORDER RULES:**
- `MessagePreprocessorHandler` — **MUST BE FIRST**
- `SpamHandler` — **MUST BE SECOND**
- `LLMMessageHandler` — **MUST BE LAST**

Full chain:
1. `MessagePreprocessorHandler` — SEQUENTIAL — saves message + media
2. `SpamHandler` — SEQUENTIAL — spam check before all others
3. `ConfigureCommandHandler` — PARALLEL — settings config
4. `SummarizationHandler` — PARALLEL — summarization
5. `UserMemoriesHandler` — PARALLEL — user memories
6. `DevCommandsHandler` — PARALLEL — debug commands
7. `MediaHandler` — PARALLEL — media processing
8. `CommonHandler` — PARALLEL — standard commands
9. `HelpHandler` — PARALLEL — help command
10. (Telegram only) `DeleteFromUserMessageHandler` — PARALLEL — auto-deletes messages from authors in `DELETE_AUTHOR_LIST`; runs before `ReactOnUserMessageHandler` so the bot doesn't react to a message it's about to delete
11. (Telegram only) `ReactOnUserMessageHandler` — PARALLEL
12. (Telegram only) `TopicManagerHandler` — PARALLEL
13. (if enabled) `WeatherHandler` — PARALLEL — gated by `[openweathermap].enabled`
14. (if enabled) `YandexSearchHandler` — PARALLEL — gated by `[yandex-search].enabled`
15. (if enabled) `ResenderHandler` — PARALLEL — gated by `[resender].enabled`
16. (if enabled) `DivinationHandler` — PARALLEL — gated by `[divination].enabled`
17. (if enabled) `SandboxHandler` — PARALLEL — gated by `[sandbox].enabled`
18. (if enabled) `ChatSearchHandler` — PARALLEL — gated by `[search-history].enabled`
19. (if enabled) `StatsHandler` — PARALLEL — gated by `[stats].enabled`
20. (custom handlers) — PARALLEL by default (configurable per-handler)
21. `LLMMessageHandler` — SEQUENTIAL — **MUST BE LAST**

---

## 7. HandlerResultStatus Reference

**File:** [`internal/bot/common/handlers/base.py`](../../internal/bot/common/handlers/base.py) — `class HandlerResultStatus(Enum)` (exported via `__all__`).

| Status | Meaning | Chain effect |
|---|---|---|
| `FINAL` | Success, handler fully processed message | **Stops** chain |
| `SKIPPED` | This handler does not apply | Continues |
| `NEXT` | Processed but continue | Continues |
| `ERROR` | Recoverable error occurred | Continues |
| `FATAL` | Unrecoverable error | **Stops** chain |

**Usage guidance:**
- Return `SKIPPED` when message is not relevant to this handler (most common)
- Return `FINAL` when you've fully handled the message and no other handler should run
- Return `NEXT` when you've done some work but want subsequent handlers to also process it
- Return `ERROR` for recoverable errors (logged, chain continues)
- Return `FATAL` only for critical unrecoverable errors

---

## 8. Chat Accessibility Tracking

The bot records per-chat presence in `chat_info.bot_status` (`ChatBotStatus.ACTIVE` / `ChatBotStatus.INACCESSIBLE`) so it can stop iterating chats it has been kicked from. Three handler-layer touch points implement it; the authoritative design (binding decisions, recovery semantics, restart edge cases) lives in [`docs/design/chat-accessibility-tracking.md`](../design/chat-accessibility-tracking.md#implementation-divergence-2026-08-12).

### 8.1 `MessagePreprocessorHandler` — recovery hook

[`MessagePreprocessorHandler.newMessageHandler`](../../internal/bot/common/handlers/message_preprocessor.py) is the **sole** recovery hook. Near the top of every inbound message it runs:

```python
if await self.cache.isChatInaccessible(chatId):
    await self.cache.markChatActive(chatId)
```

An `INACCESSIBLE` chat recovers to `ACTIVE` within **one** inbound message. `isChatInaccessible` is an **async** cache-aside lookup (in-memory chat-info cache first, DB on miss), so an active chat that is already cached pays only the cheap cached `getChatInfo` read — no platform API call and, on the steady-state hot path, no DB write. `markChatActive` writes only when the chat was actually `INACCESSIBLE` (it routes through `getChatInfo` → `setChatInfo` → `updateChatInfo(botStatus=...)`).

### 8.2 `TheBot.getChatAdmins` — async short-circuit + mark-on-failure

[`TheBot.getChatAdmins`](../../internal/bot/common/bot.py) is the **primary detection hook**. It layers accessibility writes on top of its existing graceful-degradation `{}` return:

- **Async short-circuit (top of method):** `if await self.cache.isChatInaccessible(chat.id): return {}`. The check is cache-aside — cheap (a cached `getChatInfo` hit) when the chat is already in the in-memory chat-info cache, with a DB read only on a miss. A chat already marked dead this process therefore provokes **zero** platform API calls — `isAdmin` returns `False` and chat-list callers silently skip the chat. Recovery (§8.1) flips the cached `bot_status` back to `ACTIVE`, so the short-circuit is self-healing.
- **Mark-on-failure (the existing three catch arms):** Telegram `telegram.error.Forbidden`, Telegram `telegram.error.BadRequest` **only** when the message contains `"chat not found"` (other `BadRequest`s re-raise — real API-usage errors still surface), and Max `lib.max_bot.exceptions.NotFoundError` → `await self.cache.markChatInaccessible(chat.id)` (reads `getChatInfo`, sets `bot_status = INACCESSIBLE`, persists via `setChatInfo`), log a warning, and `return {}` **without poisoning the admin cache** (the existing no-cache-on-failure behaviour is preserved). `isAdmin` returning `False` for the chat is identical to the prior graceful-degradation shape, so existing callers degrade unchanged.

There is intentionally **no mark-on-success hook** and **no** in-memory `_inaccessibleChats` set — see the design doc divergence section linked above for why the dedicated set was dropped in favour of the cache-aside `getChatInfo` path. Note that `TheBot.getChatInfo` hardcodes `bot_status = ChatBotStatus.ACTIVE` in both platform return dicts, and `CacheService.setChatInfo` forwards `info["bot_status"]` (direct subscript) into `updateChatInfo`, whose `botStatus` default is also `ACTIVE`. The every-message refresh path (`BaseBotHandler.updateChatInfo` → `TheBot.getChatInfo` → `CacheService.setChatInfo` → repo `updateChatInfo`) therefore ALWAYS writes `ACTIVE` to both the cache and the DB, so a transient `INACCESSIBLE` set by `markChatInaccessible` self-heals to `ACTIVE` on the next inbound message — which is the intended behaviour, since receiving a message proves the chat is accessible. The `INACCESSIBLE` state only persists between the failed `getChatAdmins` probe and the next inbound message from that chat; `bot_status` is a short-lived "getChatAdmins probe failed" flag, not a permanent state.

### 8.3 `/list_chats` — the `botStatus=None` owner escape hatch

Every chat-listing consumer excludes inaccessible chats by default: the repository methods `ChatUsersRepository.getUserChats` / `getAllGroupChats` default to `botStatus=ChatBotStatus.ACTIVE`. So `/configure`, the topic-manager / summarization / user-memories chat pickers, the non-owner `/list_chats` branch, and the spam-stats scan all silently hide chats the bot was kicked from — this is what stops `/configure` from iterating (and crashing on) dead chats. (Consumers call the repository directly; the old `BaseBotHandler.getUserChats` wrapper was removed when the accessibility feature was simplified.)

The **one** exception is the bot-owner `/list_chats all` branch in [`CommonHandler`](../../internal/bot/common/handlers/common.py), which passes `botStatus=None` (no SQL predicate) so the owner sees inaccessible chats for diagnostics. That branch is already gated `isBotOwner(...)`, so it is the single user-facing signal that means "show me everything, including chats I was kicked from". See design doc §7.4 (owner-visibility note) for the rationale.

## See Also

- [`index.md`](index.md) — Project overview, mandatory rules
- [`architecture.md`](architecture.md) — Handler chain ADR, singleton services
- [`database.md`](database.md) — Using `self.db` in handlers
- [`services.md`](services.md) — Using `CacheService`, `QueueService`, `LLMService` from handlers
- [`testing.md`](testing.md) — Writing handler tests with fixtures
- [`tasks.md`](tasks.md) — Step-by-step: "add a new bot command" decision tree

---

*This guide is auto-maintained and should be updated whenever significant handler changes are made*  
*Last updated: 2026-07-18*
