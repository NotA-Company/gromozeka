# Design: Statistics display v1 — `/stats` command and optional web pages

**Date**: 2026-08-18
**Status**: **PROPOSED**
**Owner**: TBD
**Branch**: `lib-stat-improvement`

**Scope**: The read/display tier over `stat_aggregates`: a `query()` read API on the
`lib/stats` `StatsStorage` ABC, ONE user-facing `/stats` bot command (brief in-chat
digest + full drill-downs, scope-derived visibility), and an optional config-gated
web-page generation tier (payload → local CLI subprocess → self-contained static HTML).
This closes the last deferred item of
[stats-collecting-v1](./stats-collecting-v1.md) NG3 / [stats-aggregation-v1](./stats-aggregation-v1.md) NG2.

> This is a **design document**, not an implementation. Every `file:line` reference
> cited for a NEW claim was verified against source on 2026-08-18 (branch
> `lib-stat-improvement`, suite 4040 passed / 11 skipped). Code sketches follow the
> repo's `camelCase` convention (`AGENTS.md`); SQL sketches follow the
> SQL-portability rules ([`docs/sql-portability-guide.md`](../sql-portability-guide.md),
> `AGENTS.md` "SQL portability" — in particular: **JSON1 SQL functions are banned**,
> so no server-side label parsing).

---

## 1. Context and goal

Gromozeka has a complete **write side** for statistics (five event types recorded,
gated on `[stats] enabled`) and a complete **maintenance side** (hourly aggregation +
retention via `StatsAggregationService`,
[stats-aggregation-v1](./stats-aggregation-v1.md)). The **read side does not exist**:
nothing in the tree queries `stat_aggregates`, and users have no way to see any of it.
The legacy `chat_users.messages_count` counter (operational, kept) backs `/users`, but
that is a different, non-historical data source.

**Goal in one paragraph:** expose the aggregates through three tiers of increasing
optional cost — (1) a portable `query()` on the existing `StatsStorage` ABC that
filters on `event_type` + `period_type` + `period_start` range in SQL and leaves all
label work to Python; (2) ONE `/stats` command (args grammar, scope-derived access,
bounded digest, full drill-downs) registered only when `[stats] enabled`; (3) an
optional `-w` flag that renders the same query results into a self-contained static
HTML page via a configurable local CLI subprocess, rate-limited per chat and cleaned
up by TTL. The brief in-chat output must never depend on tier 3 working.

### 1.1 Goals

- **G1** — Read API: `query()` on the `lib/stats` ABC returning rows with **parsed**
  labels dicts; `NullStatsStorage.query` returns `[]`; portable SQL (no JSON1, no
  dialect functions, `:named` placeholders, provider-routed, `applyPagination`).
- **G2** — ONE `/stats` command, permission `DEFAULT`, registered only when
  `[stats] enabled` (WeatherHandler-style conditional registration).
- **G3** — Scope-derived visibility: group chat → that chat only; private chat → all
  chats where the issuing user appears (existing `getUserChats`); **no permission
  tiers** — all operational detail is visible to everyone within their scope.
- **G4** — Bounded multi-section digest by default (messages / commands / tools /
  llm+stt) with top-N lists, plus `user <id>` and `chat <id>` full drill-downs, and
  `/stats help`.
- **G5** — Optional web tier: `-w` generates a self-contained HTML page (UUID
  filename, inline CSS, no external resources, zero new runtime dependencies) via a
  configurable CLI subprocess (stdin JSON in, stdout JSON `{"id", "url"}` out),
  rate-limited per chat, TTL-cleaned, best-effort — failure never degrades the brief.
- **G6** — All displayed periods are labeled UTC.

### 1.2 Non-goals

- **NG1** — No new tables, no migration, no schema change. This design is read-only
  over `stat_events`/`stat_aggregates` (both from migration 016).
- **NG2** — No `stat_aggregates` retention/cardinality management
  (carried over from stats-aggregation-v1 §9 Q2; see R1).
- **NG3** — No per-user attribution for `llm_request` events (they carry no
  `user_id` label; see §2.3 and O2). No rework of the recording label vocabulary —
  changing labels would split `labels_hash` buckets (frozen per
  stats-collecting-v1 Caveats).
- **NG4** — No auth on generated pages. Ratified: unguessable UUID URL + TTL is the
  protection (aggregates deemed non-sensitive within scope).
- **NG5** — No bot-side UI for deleting a page by id in v1 (the CLI delete mode
  exists and is documented; wiring a command around it is future work, see O1).
- **NG6** — No config hot-reload; `[stats-pages]` is read once at startup like the
  rest of the config (aggregation-v1 NG4 precedent).
- **NG7** — No charts, no JS, no per-page assets. Static HTML with inline CSS only.

---

## 2. Verified grounding (current state)

Facts verified against source on 2026-08-18 unless attributed to a prior design doc.

### 2.1 The aggregate table and its query-relevant shape

- `stat_aggregates` DDL ([migration_016_add_stat_tables.py](../../internal/database/migrations/versions/migration_016_add_stat_tables.py):120-131):
  `event_type`, `period_start` TEXT, `period_type` TEXT, `labels_hash` TEXT,
  `labels` TEXT, `metric_key` TEXT, `metric_value` REAL, `updated_at` TIMESTAMP;
  `PRIMARY KEY (event_type, period_start, period_type, labels_hash, metric_key)`.
  The PK's **leading columns `(event_type, period_start)`** match exactly the
  predicate `event_type = :t AND period_start >= :from` — no new index is needed.
- All metrics are **SUM**-accumulated
  ([internal/database/stats_storage.py](../../internal/database/stats_storage.py):260-262,
  `metric_value = metric_value + :metric_value` upsert).
- `period_type ∈ {hourly, daily, monthly, total}`; `period_start` is the ISO-8601
  string of the UTC timestamp truncated to the period
  (`_computePeriods`, [stats_storage.py:382-404](../../internal/database/stats_storage.py));
  `total` uses the fixed sentinel `1970-01-01T00:00:00+00:00`
  ([stats_storage.py:397](../../internal/database/stats_storage.py)). Because every
  stored value is `datetime.isoformat()` of an aware-UTC datetime, ISO strings
  **compare correctly lexicographically** — the identical argument that backs the
  retention DELETE's string cutoff (aggregation-v1 D8).
- `labels` holds human-readable canonical JSON — sorted keys, compact separators —
  produced by `lib.utils.jsonDumps` ([lib/utils/utils.py:108-123](../../lib/utils/utils.py),
  `sort_keys=True`, `separators=(",", ":")`); `labels_hash` is its MD5 hex
  (`_hashLabels`, [stats_storage.py:364-379](../../internal/database/stats_storage.py)).
- **`labels_hash` is useless for partial-label filtering**: it hashes the *full*
  label combo, so `WHERE labels_hash = ...` only matches an exact combo. Combined
  with the JSON1 ban, the consequence is fixed: **SQL filters only on
  `event_type` + `period_type` + `period_start` range (plain string comparisons);
  label filtering / grouping / top-N / true totals happen in Python above the
  query layer** (D4/D5).
- **`__global__` rollup rows are a second row per event with ONLY the `consumer`
  label replaced** ([stats_storage.py:216-222](../../internal/database/stats_storage.py),
  `globalLabelsDict["consumer"] = GLOBAL_CONSUMER_ID`) — they do **not** strip
  `user_id`/`modelName`/etc. True cross-label totals therefore require a post-query
  SUM over rows. Load-bearing corollary (D5): the analysis layer must filter
  `labels["consumer"] ∈ scope-set` and thereby exclude `__global__` rows, or every
  number would be double-counted.

### 2.2 Event taxonomy (labels → metrics), record sites re-verified

| eventType | Labels | Metrics | Record site (verified) |
|---|---|---|---|
| `message` | `user_id`, `chat_type`, `message_type`, `message_category`, `sent` ("True"/"False"), `consumer = str(chatId)` | `message_count`, `text_length` | [`base.py:1146-1169`](../../internal/bot/common/handlers/base.py) `saveChatMessage` |
| `command` | `user_id`, `commandName` (lowercased), `consumer = str(chatId)` | `command_count`, `is_error` | [`manager.py:1042-1046, 1052-1056`](../../internal/bot/common/handlers/manager.py) `handleCommand` |
| `llm_tool_call` | `user_id`, `toolName`, `consumer = str(chatId)` | `tool_call_count`, `elapsed_time`, `is_error` | [`llm/service.py:1009-1019`](../../internal/services/llm/service.py) tool loop |
| `llm_request` | `modelName`, `modelId`, `provider`, `generationType` (`text`/`structured`/`image`/`embedding`), `status` (+ optional `error` for embeddings) | `generation_<type>`, `request_count`, `input_tokens`, `output_tokens`, `total_tokens`, `is_error`, `status_<STATUS>`, `elapsed_time` (embeddings: `generation_embeddings`, `embedding_attempts`, no tokens) | [`lib/ai/abstract.py:850-887`](../../lib/ai/abstract.py) `_recordAttemptStats`, [`889-935`](../../lib/ai/abstract.py) `_recordEmbeddingStats` |
| `stt_request` | `provider` (class name), `generationType = "stt"`, `status`, optional `errorCode`, `_extraLabels` (`model` for Yandex, [yandex_speechkit.py:351](../../lib/stt/providers/yandex_speechkit.py)) — **no modelName/modelId** | `generation_stt`, `request_count`, `audio_duration_ms`, `elapsed_time`, `is_error`, `status_<STATUS>` | [`lib/stt/abstract.py:254-275`](../../lib/stt/abstract.py) `_recordStats` |

Corrections vs. the task brief (code wins): `stt_request` labels are
`provider`/`generationType`/`status`/`errorCode`/`model` — not
`modelName`/`modelId` (those exist only on `llm_request`); the optional `error`
label exists on the **embedding** path only ([abstract.py:920-921](../../lib/ai/abstract.py)).
`llm_request` rows carry **no `user_id` label** — they are chat-scoped (consumer)
only. Also note `request_count` counts **attempts** (one record per model tried —
the fallback loop threads `consumerId` through each model's `generateText`,
[abstract.py:197-208](../../lib/ai/abstract.py)), not logical requests.

### 2.3 consumerId verification (grounding task 1) — chat id *mostly*, with three exceptions

- `message`, `command`, `llm_tool_call`: `consumerId = str(chatId)` — verified
  first-hand (§2.2 record sites).
- `llm_request` **text/structured/image**: `LLMService.generateText` /
  `generateStructured` / `generateImage` thread
  `consumerId=str(chatId) if chatId is not None else None`
  ([llm/service.py:1320](../../internal/services/llm/service.py),
  [:1415](../../internal/services/llm/service.py),
  [:1460](../../internal/services/llm/service.py)); handler callers pass the real
  chat id (e.g. [summarization.py:278-284](../../internal/bot/common/handlers/summarization.py)).
- `stt_request`: `STTService.transcribeMedia` passes
  `consumerId=str(chatId) if chatId is not None else None`
  ([stt/service.py:311-314](../../internal/services/stt/service.py)). **Verified —
  the brief's "MUST REVERIFY" concern is resolved affirmatively.**
- **Exception 1 — embeddings never carry consumerId**: `LLMService.generateEmbedding`
  calls `embeddingModel.generateEmbeddings(text)` **without** the `consumerId`
  argument ([llm/service.py:1499](../../internal/services/llm/service.py)), even
  though `AbstractModel.generateEmbeddings` accepts it
  ([abstract.py:504-508](../../lib/ai/abstract.py)) and records with it
  ([abstract.py:557-563, 578-584](../../lib/ai/abstract.py)). Every embedding stat
  row lands under `consumer = "__global__"`.
- **Exception 2 — background calls pass `chatId = None`**: chat-search indexing
  ([chat_search.py:532, 554](../../internal/bot/common/handlers/chat_search.py)) and
  background memory refinement ([user_memories.py:1301](../../internal/bot/common/handlers/user_memories.py),
  synthetic-ensuredMessage refinement uses `chatId=None` for rate limiting). `None` →
  `consumer = "__global__"` ([stats_storage.py:107](../../internal/database/stats_storage.py)).
- **Exception 3 — the history-condensing call bypasses the wrapper entirely**:
  `condensingModel.generateText(reqMessages)` with no `consumerId`
  ([llm/service.py:1239](../../internal/services/llm/service.py)).

**Consequence (documented, not a blocker):** per-chat scoping of the `llm` section
**undercounts** embeddings, background refinement/indexing, and condensing requests —
those rows exist only in `__global__`-consumer buckets. Interactive text/image/
structured generation (the user-visible bulk) is correctly chat-scoped. Fix path =
small follow-up (thread `consumerId=str(chatId)` at service.py:1499 and :1239;
optionally thread real chat ids into the background callers), see O2. Design assumes
the current state.

### 2.4 Backfill rows (migration 027) and the `sent` consequence

Backfilled history (sourced from `chat_messages`, fix-set `fcdf5663`) carries every
live label **except `sent`**, with daily/monthly/total periods only (no hourly), and
lands in disjoint `labels_hash` buckets from live rows
([stats-collecting-v1.md D3 amendment](./stats-collecting-v1.md)). Mechanical
consequences for display:

- **Direction (users vs. bot) breakdowns render only from live rows.** The
  `groupSum("sent", ...)` view naturally produces three buckets — `"True"`, `"False"`,
  and *absent* (backfill). The digest renders the absent bucket explicitly as
  "history (before stats enabled)" so the split never silently undercounts (D6).
- Totals (`message_count`, `text_length`) remain correct across backfill + live:
  post-query SUM over disjoint label buckets.
- Period windows that predate stats enablement (30d/all) mix both row kinds; 1d
  windows are live-only in practice (post-enablement).

### 2.5 Scoping sources (grounding task 2) — the function EXISTS

`/list_chats` ([common.py:372-427](../../internal/bot/common/handlers/common.py),
`commands=("list_chats",)`, `CommandPermission.PRIVATE`) resolves the user's chats
via `self.getUserChats(ensuredMessage.sender.id)`
([common.py:415-419](../../internal/bot/common/handlers/common.py)).
`BaseBotHandler.getUserChats(userId, *, botStatus=ACTIVE)`
([base.py:1322-1355](../../internal/bot/common/handlers/base.py)) wraps
`ChatUsersRepository.getUserChats(userId, ...)` — a `chat_info ⋈ chat_users` query
with multi-datasource aggregation and dedup
([chat_users.py:271-327](../../internal/database/repositories/chat_users.py)) — and
additionally filters out chats the user has left (via per-chat `chat_users` metadata
through the cache, [base.py:1346-1353](../../internal/bot/common/handlers/base.py)).
Return type: `List[ChatInfoDict]` (has `chat_id`, `title`, `username`, `type`,
[models.py:213-231](../../internal/database/models.py)). **Reuse as-is for the
private scope; do not invent a new query.** (A stale note in teamlead memory saying
the reverse query "does not exist" predates verification; the repo wins.)

### 2.6 Registration, permissions, and command machinery (grounding task 4)

- Conditional handler registration mechanism (copy verbatim):
  `if self.configManager.get<Section>Config().get("enabled", False): self.handlers.append((XHandler(...), HandlerParallelism.PARALLEL))`
  — WeatherHandler at [manager.py:565-572](../../internal/bot/common/handlers/manager.py),
  YandexSearch at :573-579, resender :580-586, divination :587-593, sandbox :594-600,
  chat-search :603-609. All conditional appends happen **before** the unconditional
  `LLMMessageHandler` final append ([manager.py:621-627](../../internal/bot/common/handlers/manager.py)) —
  the stays-last invariant is structural as long as new blocks go next to the others.
- Defense in depth: gated handlers also self-check in `__init__` and raise
  `RuntimeError` when their integration is off
  ([weather.py:75-78](../../internal/bot/common/handlers/weather.py)).
- Command metadata: `@commandHandlerV2(commands=("stats",), ..., visibility=…,
  availableFor=…, category=…)` with `CommandPermission.DEFAULT` = "available
  everywhere" ([command_handlers.py:27-44](../../internal/bot/models/command_handlers.py));
  the established permission-agnostic shape is
  `visibility={CommandPermission.DEFAULT}, availableFor={CommandPermission.DEFAULT}`
  (e.g. `/users` uses `availableFor={CommandPermission.DEFAULT}`,
  [chat_search.py:1085-1086](../../internal/bot/common/handlers/chat_search.py)).
- Args-parsing precedent (grounding task 5): `/users` — token loop over
  `args.split()`, `token.startswith("key=")`, `int()` inside `try/except
  (ValueError, TypeError): pass` (keep default), then clamp
  ([chat_search.py:1112-1134](../../internal/bot/common/handlers/chat_search.py)).

### 2.7 Config access (grounding task 6)

- `ConfigManager.getStatsConfig()` is `return self.get("stats", {})`
  ([manager.py:492-506](../../internal/config/manager.py)); the generic
  dot-notation `get(key, default)` is at
  [manager.py:278-293](../../internal/config/manager.py). Typed section accessors
  are the dominant pattern for named sections (`getSearchHistoryConfig`
  [manager.py:532-539](../../internal/config/manager.py), `getSttConfig`
  :541+); ad-hoc inline `self.configManager.get("resender", {})` also exists
  ([manager.py:580](../../internal/bot/common/handlers/manager.py)).
- Config is loaded once at construction (no reload — aggregation-v1 NG4).
- Current `[stats]` defaults: [`configs/00-defaults/stats.toml`](../../configs/00-defaults/stats.toml)
  (`enabled = false`, five data-source keys, `aggregation-interval-seconds = 3600`,
  `aggregation-batch-limit = 1000`, `events-retention-days = 30`).

### 2.8 Rate limiter (grounding task 3)

- Singleton `RateLimiterManager` with `applyLimit(queue, key=None)` → routes to the
  queue's bound limiter, `key=None` means the queue name itself
  ([lib/rate_limiter/manager.py:303-325](../../lib/rate_limiter/manager.py)).
  Per-key sub-limits are the per-chat mechanism: existing consumer passes
  `key=str(chatId)` ([stt/service.py:298-299](../../internal/services/stt/service.py)).
- **`applyLimit` SLEEPS when the window is full** — it never refuses
  ([lib/rate_limiter/sliding_window.py:192-219](../../lib/rate_limiter/sliding_window.py)).
  A non-blocking refusal therefore needs a pre-check:
  `getStats(queue, key)` returns `requestsInWindow`/`maxRequests`/`windowSeconds`/
  `resetTime` ([manager.py:327-352](../../lib/rate_limiter/manager.py)) and raises
  `ValueError` for a never-used key
  ([sliding_window.py:243-244](../../lib/rate_limiter/sliding_window.py)) — treat
  that as "0 used".
- Configuration shape: named limiters + queue bindings under `[ratelimiter.*]`
  ([configs/00-defaults/00-config.toml:68-102](../../configs/00-defaults/00-config.toml)),
  loaded once in `main.py` via `RateLimiterManager.loadConfig`
  ([main.py:113-115](../../main.py)). Services reference a *queue name* from their
  own config section (`openweathermap` → [weather.py:104](../../internal/bot/common/handlers/weather.py);
  `chat-ratelimiter-queue` → [stt/service.py:222-237](../../internal/services/stt/service.py)).

### 2.9 Subprocess precedent (grounding task 7)

`ProxyLifecycle._runCommand` is the tree's `asyncio.create_subprocess_exec`
convention ([internal/services/proxy/lifecycle.py:105-150](../../internal/services/proxy/lifecycle.py)):
`stdout/stderr = PIPE if waitForCompletion else DEVNULL`;
`asyncio.wait_for(process.communicate(), timeout=…)` with kill-on-timeout
(lifecycle.py:131-146); decode with `errors="replace"`; failures logged at WARNING
  and return `None` (never raise). The fire-and-forget DEVNULL rule is codified in
  [`docs/llm/tasks.md:489`](../llm/tasks.md). The stats-pages invocation always waits
(it needs stdout JSON) but additionally needs **stdin** — `communicate(input=…)`
covers this without new machinery. Test mocking precedent:
patch `…asyncio.create_subprocess_exec`
([tests/services/proxy/test_lifecycle.py:69+](../../tests/services/proxy/test_lifecycle.py)).

### 2.10 Rendering constraints (grounding task 9)

- `BaseBotHandler.sendMessage(..., tryMarkdownV2=True, splitIfTooLong=True, …)`
  ([base.py:568-643](../../internal/bot/common/handlers/base.py)).
- Telegram send path applies `markdownToMarkdownV2` (escapes MarkdownV2 specials;
  preserves leading spaces / soft line breaks by default —
  [lib/markdown/parser.py:589-618](../../lib/markdown/parser.py)) automatically
  ([bot.py:875, 938, 978](../../internal/bot/common/bot.py)).
- Long-message splitting is **mechanical character chunking**, not entity-aware:
  Max splits at `MAX_MESSAGE_LENGTH = 4000`
  ([lib/max_bot/constants.py:33](../../lib/max_bot/constants.py),
   [bot.py:654-659](../../internal/bot/common/bot.py)); Telegram at
   `telegram.constants.MessageLimit.MAX_TEXT_LENGTH`
   ([bot.py:968](../../internal/bot/common/bot.py), same value as
   `TELEGRAM_MAX_MESSAGE_LENGTH` in
   [internal/bot/constants.py:96](../../internal/bot/constants.py)). A chunk
   boundary can cut an escaped entity mid-way — **the digest must stay well
   under ~3500 chars** so it always renders as one message (D6). (The function
   name `splitIfTooLong` in the task brief is this send-path *parameter*, not a
   standalone helper — verified, no such function exists.)
- Username resolution source: `ChatUserDict` has `username` and `full_name`
  ([models.py:197-200](../../internal/database/models.py)); per-(chat, user)
  lookup exists via the cache (`getChatUser(chatId=…, userId=…)`, used at
  [base.py:1346](../../internal/bot/common/handlers/base.py)); per-chat user lists
  via `ChatUsersRepository.getChatUsers` (the `/users` backend,
  [chat_users.py:230-269](../../internal/database/repositories/chat_users.py)).
  Rows are never deleted from `chat_users` (user-verified; the table is
  append/update-only), so resolution always succeeds — defensive raw-id fallback
  anyway (D8).

### 2.11 TypedDict conventions (grounding task 8) and current stats surface

- DB row TypedDicts live next to their consumers and mirror **DB column names** in
  snake_case when produced by `dbUtils.sqlToTypedDict` (e.g. `StatsEventDict`,
  [internal/database/stats_storage.py:27-36](../../internal/database/stats_storage.py);
  `ChatUserDict`, [models.py:187-210](../../internal/database/models.py)).
  API-level TypedDicts that are *not* direct row mappings use camelCase fields
  (e.g. `RateLimiterStatsEntry`, [lib/rate_limiter/manager.py:37-54](../../lib/rate_limiter/manager.py)).
  `StatsAggregateDict` is an API shape with a parsed `labels` dict → **camelCase
  fields, defined in `lib/stats/`** so the ABC and the DB impl can both import it
  without an internal→lib dependency (D4).
- The ABC today ([lib/stats/stats_storage.py](../../lib/stats/stats_storage.py)):
  `record` (never raises, :26-53), `aggregate` (:55-78),
  `purgeProcessed` (:80-97, raise-on-error like `aggregate`); `NullStatsStorage`
  no-ops all three (:100-148). `__init__.py` re-exports
  `StatsStorage`/`NullStatsStorage`/`GLOBAL_CONSUMER_ID`
  ([lib/stats/__init__.py:19-20](../../lib/stats/__init__.py)).
- `StatsAggregationService` (post-A4): singleton; `initialize(configManager,
  database)` parses and caches `[stats]` once, fail-loudly
  ([internal/services/stats/service.py:142-202](../../internal/services/stats/service.py));
  `createStatsStorage(eventType, dataSource=None)` factory + `_statsStorages`
  registry keyed by eventType (:204-246); `_dtCronJob` gates on elapsed time and
  early-returns when the registry is empty (:248-272).
- All five storages are constructed in [`main.py`](../../main.py):96-131 **after**
  `StatsAggregationService.initialize` (:90) and **before** the bot applications
  are built (:137-153) — by the time handlers are constructed, the registry is
  populated. This ordering makes a lazy `getQueryStorage` accessor safe (D4).

---

## 3. Architecture decisions

All of D1-D15 encode the user-ratified direction (2026-08-18); sub-choices the
ratified text left open are resolved against the evidence in §2 and marked
**flagged** with rationale.

### D1 — ONE `/stats` command, DEFAULT permission, gated registration *(user-ratified)*

`StatsDisplayHandler(BaseBotHandler)` in
`internal/bot/common/handlers/stats_display.py`, registered in `HandlersManager`
**only when `[stats] enabled`** using the verified conditional-append mechanism
([manager.py:565-609](../../internal/bot/common/handlers/manager.py) pattern), with
the `__init__` self-check raising `RuntimeError` when stats are off
([weather.py:75-78](../../internal/bot/common/handlers/weather.py) pattern).

```python
@commandHandlerV2(
    commands=("stats",),
    shortDescription="[period] [section] [user <id>|chat <id>] [-w] - Statistics digest",
    helpMessage=" … ",                       # usage text, Russian per repo precedent
    visibility={CommandPermission.DEFAULT},
    availableFor={CommandPermission.DEFAULT},
    helpOrder=CommandHandlerOrder.NORMAL,
    category=CommandCategory.TOOLS,
)
async def statsCommand(self, ensuredMessage, command, args, updateObj, typingManager) -> None:
```

**No permission tiers** (user decision, explicitly against an owner-only tier for
operational detail): modelName, provider, tokens, error rates are visible to
everyone within their scope (D3). Registration block sits beside the sandbox /
chat-search blocks (before `LLMMessageHandler`'s final append) — the
stays-last invariant is untouched. The handler is platform-agnostic (common/), so
it serves both Telegram and Max.

### D2 — Args grammar and period→bucket mapping *(user-ratified shape; grammar formalized)*

```
/stats [period] [section] [drill] [-w] [help]

period  ∈ {1d, 7d, 30d, all}          default 7d
section ∈ {messages, commands, tools, llm}   default: all four
drill   ∈ {user <int id>} | {chat <int id>}
-w      generate the web page too (tier 3)
help    usage text
```

- Tokens are order-insensitive; parsing follows the `/users` precedent — a token
  loop over `args.split()` with `try/except (ValueError, TypeError)` per token and
  defaults kept on parse failure ([chat_search.py:1112-1134](../../internal/bot/common/handlers/chat_search.py));
  `user`/`chat` consume the **next** token as the id. Unknown tokens → the reply
  becomes the usage text (no exception, no partial output); a dangling
  `user`/`chat` token with no following id falls under that same rule (usage
  reply).
- **Period → bucket mapping (validated):** `1d → period_type=hourly` (last 24
  hourly buckets), `7d`/`30d → daily`, `all → total` (sentinel row, no range).
  Mechanical note: a 7d daily window spans 8 buckets (7 full days + the partial
  current day) — bucket-granularity rounding, documented in `help`.
- `-w` composes with everything: `/stats 30d llm chat -100123 -w`.

### D3 — Scoping: group → this chat; private → all the user's chats *(user-ratified)*

- **Group chat** (`chatId < 0`, sign convention per AGENTS.md): scope = that chat
  only. Analysis filter: `labels["consumer"] == str(chatId)` (this also excludes
  `__global__` rows — §2.1 corollary).
- **Private chat**: scope = **all chats where the user appears**, resolved with the
  existing `BaseBotHandler.getUserChats(userId)` ([base.py:1322-1355](../../internal/bot/common/handlers/base.py),
  the `/list_chats` backend — §2.5). Analysis filter:
  `labels["consumer"] ∈ {str(c.chat_id) for c in scopeChats}`.
- **Drill authorization is scope membership, not permissions**: `chat <id>` is
  honored only if `id` is the current chat (group scope) or a member of the user's
  scope set (private scope); otherwise the reply says the chat is not in scope.
  `user <id>` filters the `user_id` label wherever the event type carries it.
- No caching of the scope resolution beyond the single command invocation (one
  `getUserChats` call per `/stats` in private — a cheap indexed join, §2.5).

### D4 — Read API: `query()` on the lib/stats ABC *(user-ratified)*

Grow the ABC (`lib/stats/stats_storage.py`), with a row TypedDict in new
`lib/stats/types.py` (§2.11 conventions — camelCase API shape):

```python
class StatsAggregateDict(TypedDict):
    periodStart: str   # ISO-8601 UTC, or the total sentinel
    periodType: str    # "hourly" | "daily" | "monthly" | "total"
    labels: dict[str, str]      # PARSED from the labels JSON column
    metricKey: str
    metricValue: float
```

```python
@abstractmethod
async def query(
    self,
    *,
    eventType: str,
    periodType: Optional[str] = None,
    periodStartFrom: Optional[str] = None,
    periodStartTo: Optional[str] = None,
    limit: int = 10000,
) -> list[StatsAggregateDict]:
    """Read aggregated rows. … (docstring with Args:/Returns: per repo rules) """
```

- **`eventType` is a query parameter** (user decision): the per-instance
  `eventType` stays **write-only** (one `DatabaseStatsStorage` per event type keeps
  its write isolation, [stats_storage.py:59-69](../../internal/database/stats_storage.py));
  one table per datasource serves cross-eventType overview views.
- SQL (provider-routed, `:named`, no JSON1, `applyPagination` for LIMIT):

  ```python
  sqlProvider = await self.db.manager.getProvider(dataSource=self.dataSource, readonly=True)
  conditions = ["event_type = :eventType"]
  params: dict[str, str | int] = {"eventType": eventType}
  # optional ANDs: period_type = :periodType / period_start >= :periodStartFrom / period_start <= :periodStartTo
  sql = sqlProvider.applyPagination(
      "SELECT period_start, period_type, labels, metric_key, metric_value FROM stat_aggregates"
      " WHERE " + " AND ".join(conditions),
      limit=limit, offset=0,
  )
  rows = await sqlProvider.executeFetchAll(sql, params)
  return [StatsAggregateDict(periodStart=r["period_start"], periodType=r["period_type"],
          labels=json.loads(r["labels"]), metricKey=r["metric_key"],
          metricValue=float(r["metric_value"])) for r in rows]
  ```

  ISO string bounds compare lexicographically against the stored `isoformat()`
  values (§2.1); `truncateToDay`/hour truncation produce exactly the stored shape.
  Read-only provider (`readonly=True`) — the repositories' read convention
  (e.g. [chat_users.py:302](../../internal/database/repositories/chat_users.py)).
- **Error semantics: raise-on-error** — matches `aggregate()`/`purgeProcessed`
  (both propagate; only `record` is never-raise, §2.11). The command handler
  catches and renders a one-line failure. `NullStatsStorage.query` returns `[]`.
- **Flagged (accessor):** the handler reaches the storages through a new public
  read accessor on the existing service rather than a sixth factory call:

  ```python
  # internal/services/stats/service.py
  def getQueryStorage(self, eventType: str) -> StatsStorage:
      """Return the registered storage for eventType (NullStatsStorage if none)."""
      return self._statsStorages.get(eventType, NullStatsStorage())
  ```

  Rationale: the five display-relevant event types are always registered when
  stats are enabled ([main.py:96-131](../../main.py)); a plain registry read
  avoids `createStatsStorage`'s last-wins overwrite and keeps the read path free
  of construction side effects. Datasource routing stays per-eventType for free
  (each registry entry was constructed with its own `*-stats-data-source`).

### D5 — Python-side analysis layer *(user-ratified placement; shape flagged)*

New `lib/stats/analysis.py` (reusable, no bot deps — the `lib/` rule):
`StatsAnalyzer`, an immutable helper over `list[StatsAggregateDict]`:

```python
class StatsAnalyzer:
    def __init__(self, rows: list[StatsAggregateDict]) -> None: ...
    def filterByLabelIn(self, key: str, values: set[str]) -> "StatsAnalyzer": ...   # consumer scoping
    def filterByLabel(self, key: str, value: str) -> "StatsAnalyzer": ...           # user_id / drill
    def sumMetric(self, metricKey: str) -> float: ...                               # true totals (Σ over buckets)
    def groupSum(self, groupLabel: str, metricKey: str) -> list[tuple[str, float]]: ...  # sorted desc
    def topN(self, groupLabel: str, metricKey: str, n: int) -> list[tuple[str, float]]: ...
    def average(self, valueKey: str, countKey: str) -> float: ...                   # Σvalue / Σcount, 0-safe
```

- **Averages are Σvalue/Σcount** (user-ratified) — e.g. tool avg elapsed =
  `Σelapsed_time / Σtool_call_count`, never an average of averages.
- **True totals** are `sumMetric` over the consumer-scoped row set — never the
  `__global__` rows (excluded by the D3 consumer filter) and never per-bucket
  values (§2.1).
- If a query returns exactly `limit` rows, renderers append a
  "⚠ results possibly truncated" line (honesty at the 10 000-row cap).

### D6 — Digest content, section folding, bounded output *(digest shape flagged; stt folding flagged)*

Default no-args reply = multi-section digest (user-ratified) + pointer to
`/stats help`. Sketch (wording frozen at implementation; user-facing text in
Russian per repo precedent — `/list_chats`, `/users`):

```
📊 Stats — 7d (UTC) — scope: this chat
Messages: 1234 (users 1000 / bot 234 / history 0)
  Top: Alice 300 · Bob 210 · Carol 95
Commands: 45 (errors 2) — Top: /stats 12 · /help 8 · /users 5
Tools: 88 calls (errors 3, avg 1.2s) — Top: search_messages 40 · run_python 20
LLM: 200 requests (text 150 · structured 40 · image 10)
  tokens in 1.2M / out 340K · errors 5 · avg 2.1s · top model gpt-4o-mini
STT: 12 req · 34 min audio
/stats help — полная справка
```

- **`stt` folds into the `llm` section** as its final line (**flagged decision**,
  brief left it open): both are model-API requests; a separate 5th section adds
  digest length while `stt_request` is empty in most deployments (STT is
  default-off, [main.py:117-121](../../main.py)). `llm` drill-down shows STT
  detail; the web page renders it as its own sub-table. The section keyword stays
  `llm`.
- **The `llm` section reflects §2.3**: scoped views count interactive
  text/structured/image generation (correctly chat-scoped) and STT; embeddings and
  background requests land in `__global__` and are invisible to scoped queries
  (R3) — `help` words this as "LLM counts cover interactive generation".
- **Direction split with the three-bucket honesty rule** (§2.4): users / bot /
  history-before-stats. This honors the ratified "direction breakdowns render
  only for live period; totals correct — no UI special-casing": the explicit
  "history (before stats enabled)" line is an honesty label on otherwise-missing
  data, not per-view special-case logic.
- **Bounded: ≤ ~30 lines / ~2 500 chars** so it always fits one message and never
  hits the mechanical character-split (§2.10). Top lists are top-3 in the digest;
  drill-downs may use top-10; anything longer belongs on the page (tier 3).
- Section keyword filters: `/stats 30d commands` renders only that section, full
  drill-down depth (top-10) still bounded to one message.

### D7 — Drill-downs `user <id>` and `chat <id>` *(user-ratified: full drill-downs in scope)*

- `user <id>`: per-user breakdown across sections — `message` / `command` /
  `llm_tool_call` filtered by `user_id == str(id)` within the scope; totals,
  per-section lines, top message types. **`llm_request` carries no `user_id` label
  (§2.2) and is therefore excluded from user drill-downs** — documented in `help`
  ("LLM requests are chat-level, not user-level"). Authorization: none beyond
  scope (any user id may be inspected within your scope — same visibility rule).
- `chat <id>`: full per-chat detail for all four sections (scope membership check
  per D3), including llm top-models/tokens and stt lines.
- Username resolution applies to every rendered user id (D8).

### D8 — Username resolution via `chat_users`, raw-id fallback *(user-ratified)*

Render-time join only (no persistence): for group scope, build the id→name map
from `db.chatUsers.getChatUsers(chatId=…)` rows (`username`/`full_name`,
[models.py:197-200](../../internal/database/models.py)); for private scope,
resolve via the cache's `getChatUser(chatId=…, userId=…)` against any scoped chat
(the `getUserChats` path already does exactly this,
[base.py:1346](../../internal/bot/common/handlers/base.py)). Users are never
deleted from the DB (user-verified) so resolution succeeds; defensively fall back
to the raw id on any miss/exception. Resolution is bounded: only for ids that
actually render (top-N lists, ≤ ~10 lookups).

### D9 — UTC everywhere *(user-ratified)*

Both the digest header ("7d (UTC)") and the page meta label all periods as UTC.
No local-time conversion is offered in v1 (the `chat_users.timezone` column exists
but per-user rendering timezone is out of scope).

### D10 — Web tier config-gated: `[stats-pages]`, default off *(user-ratified)*

New config section (§5 for the diff). When `enabled = false` (default) or the
section is absent: `-w` produces an informative reply ("web pages disabled — ask
the operator to configure `[stats-pages]`") and the brief output is unaffected —
exactly the WeatherHandler-gating philosophy applied to a sub-feature. Keys:
`enabled`, `output-dir` (web-served path the bot can write), `base-url`
(composed into the reply link), `ttl-hours` (unit-explicit, default 24),
`command` (template list, D12), `ratelimiter-queue` (default `"stats-pages"`).
Accessed via a typed accessor `ConfigManager.getStatsPagesConfig()` mirroring
`getStatsConfig()` (§2.7 dominant pattern), cached once at handler init (NG6).

### D11 — CLI contract: stdin JSON in, self-contained HTML out, JSON stdout *(user-ratified; url shape flagged)*

- Invocation via `asyncio.create_subprocess_exec` (no shell), payload JSON on
  **stdin** (no temp dump files), following the `_runCommand` conventions
  (§2.9) plus `stdin=PIPE`; `asyncio.wait_for(communicate(input=…), timeout=30)`
  with kill-on-timeout; stderr decoded for the log; WARNING-level failure logs.
- The CLI writes a **self-contained static HTML page** — UUID filename
  (`uuid.uuid4().hex + ".html"`), inline CSS, **no CDN/external resources, no JS,
  zero new runtime dependencies** (stdlib `argparse`/`html`/`json` only) — into
  `output-dir`.
- **STDOUT contract: one JSON object `{"id": "<uuid>", "url": "…"}`**
  (user requirement: the id enables deletion; not a bare filename).
  **Flagged: `url` is relative (the `<uuid>.html` filename) and the bot composes
  `base-url + "/" + url` for the reply link.** Rationale: the CLI stays a pure
  local tool with no knowledge of the serving web server; `base-url` is
  deployment config that would otherwise be duplicated into the CLI (and could
  drift). An absolute URL would require passing `base-url` into every invocation.
- In-repo generator placement (**flagged**): `internal/stats_pages/` with a
  `__main__.py`, mirroring the standalone-module precedent
  `internal/max_webhook_receiver/` (run as
  `./venv/bin/python3 -m internal.max_webhook_receiver`, AGENTS.md). Rationale:
  module-invocable standalone processes live in `internal/`; `lib/` stays
  import-only primitives. It imports nothing from the bot.
- Exit codes: 0 success; nonzero any failure (with a human-readable stderr line).
  Anything non-JSON on stdout = failure (D15).
- Page content = the same view-model the brief renders (meta + sections with
  full grouped lists; the digest truncates, the page does not), so grouping logic
  exists exactly once (bot side, D5).

### D12 — Configurable command template *(user-ratified; placeholder set formalized)*

`command` is a `list[str]` template; substitution is `str.format_map` over the
defined placeholder set (strict — an unknown placeholder is a config error and
surfaces as the D15 failure note, logged):

| Placeholder | Meaning |
|---|---|
| `{mode}` | `generate` \| `cleanup` \| `delete` — the mode switch |
| `{user_id}` | The calling user's id (`"0"` in cron-cleanup context) |
| `{chat_id}` | **The chat the command was issued in** — in private-multi-chat scope this is the private chat id (the scope itself is the user's chat union; there is no single "target" chat) *(user-ratified recommendation)* |
| `{output_dir}` | `[stats-pages] output-dir` |
| `{ttl_hours}` | `[stats-pages] ttl-hours` |

- Default value:

  ```toml
  command = [
      "./venv/bin/python3", "-m", "internal.stats_pages", "{mode}",
      "--output-dir={output_dir}", "--ttl-hours={ttl_hours}",
      "--user-id={user_id}", "--chat-id={chat_id}",
  ]
  ```

  (The in-repo CLI records user/chat ids in the page footer meta; external tools
  may use them for their own accounting. In `cleanup`/`delete` modes they are
  substituted with the same values and ignored.)
- **Delete-by-id invocation shape:** the bot (or an operator) appends the page id
  as one trailing positional argument after substitution —
  `<command {mode}=delete …> <uuid>` → deletes `<output-dir>/<uuid>.html`,
  prints `{"deleted": 0|1}`. No template placeholder for the id (it is data, not
  configuration). Bot-side wiring around delete is NG5/O1.
- **Cleanup invocation:** `<command {mode}=cleanup …>` deletes `*.html` files
  older than TTL (mtime) in `output-dir`, prints `{"deleted": N}`.

### D13 — Rate limiting: per-chat, check-then-apply *(user-ratified purpose; mechanism flagged)*

- Purpose (user's words): "so users can't generate millions of stat files and eat
  all space". Only `-w` is limited — never the brief.
- Mechanism: the **existing** `RateLimiterManager` with a dedicated queue
  `"stats-pages"` bound to a new named limiter (§5 config diff — the
  `[ratelimiter]` mechanism, §2.8), keyed **per chatId**:
  `applyLimit(queue, key=str(chatId))` — the STT precedent
  ([stt/service.py:298-299](../../internal/services/stt/service.py)).
- **Flagged (refusal semantics):** `applyLimit` sleeps when full (§2.8), so the
  handler does a non-blocking **pre-check** first:

  ```python
  try:
      stats = RateLimiterManager.getInstance().getStats(queue, key=str(chatId))
      used = stats["requestsInWindow"]
  except ValueError:
      used = 0                                    # never-used key
  if used >= stats["maxRequests"]:  → informative reply, NO CLI invocation
  else: await applyLimit(queue, key=str(chatId))  # records the attempt
  ```

  The pre-check makes the sleep branch unreachable in practice; the residual
  check-then-record race on the shared loop can over-admit by at most a couple of
  concurrent `-w` calls — benign (R12). Suggested defaults: **3 pages per chat per
  hour** (`windowSeconds = 3600`, `maxRequests = 3`).

### D14 — TTL cleanup rides the StatsAggregationService cycle; delete-by-id exists *(user-ratified choice; rider pick flagged)*

- Two precedents were on the table (§ refs): the **StatsAggregationService tick**
  (hourly cycle, [service.py:248-318](../../internal/services/stats/service.py))
  and the **weekly `_cleanupOldData`** gate
  ([manager.py:657-679](../../internal/bot/common/handlers/manager.py), the
  `nowMinutes == 0 and nowHour == 0 and nowWDay == 0` Sunday-midnight pattern).
  **Flagged pick: the StatsAggregationService cycle.** Rationale: TTL default is
  24 h — weekly cleanup would retain files up to ~7× TTL; the aggregation cycle is
  already the stats subsystem's maintenance heartbeat and runs (by default)
  hourly, i.e. at TTL granularity; and it early-returns cheaply when stats are
  off, which is exactly when no new pages can be generated anyway (R10 covers the
  disable-later residue). Cost of the coupling: the cleanup cadence inherits
  `aggregation-interval-seconds` (an operator setting a 24 h interval gets
  daily cleanup — still ≤ TTL+1 day, acceptable and documented).
- Mechanics: `initialize` additionally parses+caches `[stats-pages]`
  (enabled/outputDir/ttlHours/commandTemplate — A4 fail-loud pattern,
  `_parseIntKey` for `ttl-hours`); `_dtCronJob` gains a final step (after the
  per-storage drain/purge, outside the per-storage try/excepts, inside its own):

  ```python
  if self._pagesEnabled:
      try:
          await self._cleanupStatsPages()   # subprocess {mode}=cleanup; WARNING on failure
      except Exception:
          logger.exception("stats-pages TTL cleanup failed")
  ```

  The rider invokes the CLI via the same D11 invocation helper (shared with the
  handler — placed in `internal/stats_pages/launcher.py` so both callers use one
  code path) with `{user_id}`/`{chat_id}` = `"0"`.
- `delete <id>` mode is implemented in the CLI (D12) with no bot UI in v1 (O1).

### D15 — Failure modes: brief always wins *(user-ratified)*

The `-w` tier is best-effort and **must never raise out of the command handler**
(whole tier wrapped in `try/except Exception` + `logger.exception`):

| Failure | Behavior |
|---|---|
| `[stats-pages]` disabled/absent | informative reply, no CLI |
| rate limit exceeded | informative reply (with retry hint), no CLI |
| nonzero exit / unparseable stdout / timeout (30 s, kill) | brief delivered + one-line "page generation failed" note |
| unknown template placeholder (`KeyError`) / missing output-dir | same as above (config error, logged at WARNING with the key) |
| any unexpected exception in the tier | same as above |

Query-layer errors (D4 raise-on-error) are caught one level up: the handler
renders a one-line "stats query failed" reply and returns normally.

---

## 4. Wiring diagram

```
User: /stats [period] [section] [drill] [-w]
        │
        ▼
StatsDisplayHandler.statsCommand            internal/bot/common/handlers/stats_display.py [NEW]
  ├─ parse args (D2, /users token-loop pattern)
  ├─ resolve scope (D3): group → {chatId}; private → getUserChats(userId)  [base.py:1322]
  ├─ for each section eventType in {message, command, llm_tool_call, llm_request, stt_request}:
  │     StatsAggregationService.getInstance().getQueryStorage(eventType)    [service.py, NEW accessor]
  │           └─ _statsStorages registry (populated by main.py:96-131 factory calls)
  │     await storage.query(eventType=…, periodType=…, periodStartFrom/To=…)   [ABC, NEW]
  │           └─ DatabaseStatsStorage.query → provider.executeFetchAll (SQL: event_type+period only)
  ├─ StatsAnalyzer (lib/stats/analysis.py [NEW]): consumer-scope filter → group/topN/Σ/Σ÷Σ
  ├─ username join via chat_users / cache.getChatUser (D8)
  ├─ render digest (bounded, MarkdownV2-safe) → sendMessage                     [base.py:568]
  └─ if -w:  [stats-pages] gate → rate-limit pre-check (D13) → launcher (D11)
              asyncio.create_subprocess_exec(*templatedArgv, stdin=PIPE)
              payload = view-model JSON on stdin
              ◀ stdout {"id": "<uuid>", "url": "<uuid>.html"}
              reply: base-url + "/" + url          (failures → D15 table)

StatsAggregationService._dtCronJob (existing hourly cycle)                       [service.py:248]
  └─ [NEW last step] if [stats-pages] enabled: _cleanupStatsPages()
        └─ launcher({mode}=cleanup) → CLI deletes output-dir/*.html older than ttl-hours

internal/stats_pages/ [NEW standalone module, python3 -m internal.stats_pages]
  ├─ __main__.py   argparse: generate|cleanup|delete, --output-dir, --ttl-hours, --user-id, --chat-id
  ├─ generator.py  stdin JSON view-model → self-contained HTML (uuid4 name, inline CSS)
  └─ launcher.py   the one subprocess invocation helper (timeout 30 s, kill, JSON stdout parse)
```

Read path only — `stat_events` is untouched; `stat_aggregates` is read via the
provider (readonly=True). No migration, no schema change.

---

## 5. Configuration changes

New file [`configs/00-defaults/stats-pages.toml`](../../configs/00-defaults) (created;
default-off so merged behavior is unchanged):

```toml
[stats-pages]
enabled = false
# output-dir = "/var/www/gromozeka/stats"   # REQUIRED when enabled; web-served, bot-writable
# base-url = "https://example.com/stats"    # REQUIRED when enabled; composed into the reply link
ttl-hours = 24
ratelimiter-queue = "stats-pages"
command = [
    "./venv/bin/python3", "-m", "internal.stats_pages", "{mode}",
    "--output-dir={output_dir}", "--ttl-hours={ttl_hours}",
    "--user-id={user_id}", "--chat-id={chat_id}",
]
```

Diff to [`configs/00-defaults/00-config.toml`](../../configs/00-defaults/00-config.toml)
(new limiter + queue binding, appended after `stt-global` / into the queues table):

```toml
 [ratelimiter.ratelimiters.stt-global]
 type = "SlidingWindow"

 [ratelimiter.ratelimiters.stt-global.config]
 windowSeconds = 60
 maxRequests = 10

+[ratelimiter.ratelimiters.stats-pages]
+type = "SlidingWindow"
+
+[ratelimiter.ratelimiters.stats-pages.config]
+windowSeconds = 3600
+maxRequests = 3
+
 [ratelimiter.queues]
 yandex-search = "default"
 openweathermap = "default"
 geocode-maps = "one-per-second"
 chat-default = "default"
 stt-chat = "stt-chat"
 stt-global = "stt-global"
+stats-pages = "stats-pages"
```

`[stats]` itself is unchanged. Reader: new typed accessor
`ConfigManager.getStatsPagesConfig()` (D10). Validation errors (missing
output-dir/base-url when enabled, malformed ttl) fail loudly at startup /
handler-init per the A4 precedent.

---

## 6. Phased implementation plan

Hard rules for **every** phase (`AGENTS.md`): `camelCase`; docstrings with
`Args:`/`Returns:`; type hints everywhere; no `Any` (genuine generic containers
excepted); no pydantic; `StrEnum` where applicable; imports at file top; Python
via `./venv/bin/python3`; `make format lint` **before AND after** edits; `make
test` (timeout-wrapped) mandatory; regression test first on any bug fix.
Implement via `software-developer`; docs pass via the
[`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md) skill.

### Phase 1 — Read API: `query()` + `StatsAggregateDict` + `getQueryStorage`

Sized ~45 steps: three lib files (one new), two internal files, three test files.

**Files:**

- `lib/stats/types.py` — **new**; `StatsAggregateDict` (D4).
- [`lib/stats/stats_storage.py`](../../lib/stats/stats_storage.py) — abstract
  `query(...)` (D4 signature + full docstring); `NullStatsStorage.query` → `[]`.
- [`lib/stats/__init__.py`](../../lib/stats/__init__.py) — re-export
  `StatsAggregateDict`.
- [`internal/database/stats_storage.py`](../../internal/database/stats_storage.py) —
  `DatabaseStatsStorage.query` per D4 (dynamic conditions list, `applyPagination`,
  `json.loads` labels, readonly provider).
- [`internal/services/stats/service.py`](../../internal/services/stats/service.py) —
  `getQueryStorage(eventType)` accessor (D4).

**Tests** (`tests/` mirror layout, `asyncio_mode = "auto"`, reuse the
`tests/lib/stats/conftest.py` in-memory fixture — migration 016 only):

- `tests/lib/stats/test_sql_storage.py` — new `TestQuery` class:
  filters by event_type only / + periodType / + range (inclusive bounds);
  lexicographic ISO comparison correctness incl. the `+00:00` suffix shape;
  `total` sentinel pass-through (no range); parsed labels dict; `limit` respected
  via `applyPagination`; rows from other eventTypes/datasources excluded.
- `tests/lib/stats/test_null_storage.py` — `query` returns `[]` for any args.
- `tests/services/stats/test_service.py` — `getQueryStorage` returns registered
  storage / `NullStatsStorage` for unknown eventType / when stats disabled.

**Docs:** [`docs/llm/libraries.md`](../llm/libraries.md) §9 (`query()` + row shape),
[`docs/llm/services.md`](../llm/services.md) (`getQueryStorage`).
**CHANGELOG:** skip (internal API, no user-visible change — per
[`docs/llm/changelog.md`](../llm/changelog.md) when-not criteria; fold into the
Phase 2 entry if preferred).

**Gate 1:** `make format lint`; `make test`; `make check-docs`.

### Phase 2 — `/stats` command: registration, grammar, scoping, digest, drill-downs

Sized ~60 steps: one new lib file, one new handler file, two edited files, tests.

**Files:**

- `lib/stats/analysis.py` — **new**; `StatsAnalyzer` (D5).
- `internal/bot/common/handlers/stats_display.py` — **new**;
  `StatsDisplayHandler` (D1/D2/D3/D6/D7/D8/D9): `@commandHandlerV2` registration,
  `__init__` stats-enabled self-check, args parser, scope resolution, per-section
  queries via `getQueryStorage`, view-model builder, digest renderer, drill-down
  renderers, username join.
- [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py) —
  conditional registration block beside sandbox/chat-search (D1):
  `if self.configManager.getStatsConfig().get("enabled", False): self.handlers.append((StatsDisplayHandler(...), HandlerParallelism.PARALLEL))`.
- `internal/bot/common/handlers/__init__.py` — export (follow the WeatherHandler
  export pattern).

**Tests:**

- `tests/lib/stats/test_analysis.py` — `StatsAnalyzer` matrix: consumer-scope
  filter excludes `__global__`; groupSum ordering; topN; Σvalue/Σcount average
  (incl. 0-count); three-bucket `sent` grouping (True/False/absent).
- `tests/bot/common/handlers/test_stats_display.py` — real `EnsuredMessage`
  construction (conftest pattern); mocked storages returning canned
  `StatsAggregateDict` rows: digest renders all sections bounded; group vs
  private scope filter sets (patch `getUserChats`); `chat <id>` authorization
  (in-scope ok / out-of-scope refused); `user <id>` excludes `llm_request`;
  period→bucket mapping (1d→hourly, 7d/30d→daily, all→total+no range);
  unknown token → usage; username fallback to raw id; **stats-off → handler
  construction raises + manager registers nothing** (registration test at the
  manager level, mirror the WeatherHandler gating test if one exists).
- Singleton hygiene: reset `StatsAggregationService._instance` where manipulated.

**Docs:** [`docs/llm/handlers.md`](../llm/handlers.md) (new handler + gating),
[`docs/llm/libraries.md`](../llm/libraries.md) §9 (`StatsAnalyzer`),
[`docs/llm/index.md`](../llm/index.md) §4 handler-list entry.
**CHANGELOG:** `Added` — `/stats` command (period/section/user/chat drill-downs,
scope-derived visibility) gated on `[stats] enabled`.

**Gate 2:** `make format lint`; `make test`; `make check-docs`.

### Phase 3a — Web tier: CLI generator + config

Sized ~30 steps: new module (3 files), 2 config files, 1 edited internal file,
tests. (The 3a/3b split is **unconditional** — the combined ~60 steps span 14
files, so each sub-phase carries its own budget and the ~60-step-per-invocation
ceiling holds by construction.)

**Files:**

- `internal/stats_pages/__init__.py`, `__main__.py`, `generator.py` — **new**
  (D11/D12): argparse modes generate/cleanup/delete; self-contained HTML
  renderer (inline CSS, `html.escape` everything, UTC footer with meta incl.
  user/chat ids).
- [`configs/00-defaults/stats-pages.toml`](../../configs/00-defaults) — **new**
  (§5); [`configs/00-defaults/00-config.toml`](../../configs/00-defaults/00-config.toml) —
  limiter + queue binding (§5).
- [`internal/config/manager.py`](../../internal/config/manager.py) —
  `getStatsPagesConfig()`.

**Tests:**

- `tests/stats_pages/test_generator.py` — golden-ish: given a fixed view-model
  JSON → HTML contains escaped values, no external URLs (`http`/`https` absent
  outside the footer meta), inline `<style>`, UTC label; uuid filename shape.
- `tests/stats_pages/test_cli.py` — subprocess-in-process (import `__main__`
  functions directly): generate writes file + stdout JSON; cleanup deletes by
  mtime TTL; delete removes by id; nonzero exit on bad stdin JSON / missing
  output-dir.

**Docs:** [`docs/llm/configuration.md`](../llm/configuration.md) (`[stats-pages]`
table + ratelimiter additions), [`docs/llm/index.md`](../llm/index.md)
(`internal/stats_pages/` in the layout map).
**CHANGELOG:** none yet — fold into the Phase 3b entry (single user-visible
feature).

**Gate 3a:** `make format lint`; `make test`; `make check-docs`.

### Phase 3b — Web tier: bot integration — subprocess invocation, rate limiter, cleanup, failure modes

Sized ~30 steps: 1 new module file, 2 edited internal files, tests.

**Files:**

- `internal/stats_pages/launcher.py` — **new** (D11): launcher helper (exec,
  stdin payload, `wait_for` 30 s, kill, stdout JSON parse + `{"id","url"}`
  validation).
- `internal/bot/common/handlers/stats_display.py` — the `-w` tier: config gate,
  rate-limit pre-check + apply (D13), payload build (view-model JSON), launcher
  call, link composition (`base-url + "/" + url`), D15 failure table.
- [`internal/services/stats/service.py`](../../internal/services/stats/service.py) —
  parse/cache `[stats-pages]` at `initialize` (A4 pattern); `_cleanupStatsPages`
  rider at the end of `_dtCronJob` (D14).

**Tests:**

- `tests/stats_pages/test_launcher.py` — patch
  `internal.stats_pages.launcher.asyncio.create_subprocess_exec`
  ([tests/services/proxy/test_lifecycle.py:69](../../tests/services/proxy/test_lifecycle.py)
  pattern): timeout kill; nonzero exit; unparseable stdout; happy path returns
  `{"id","url"}`.
- `tests/bot/common/handlers/test_stats_display.py` — extend: disabled
  `[stats-pages]` → informative reply, no subprocess; rate-limit refusal (mock
  `getStats` full window) → reply, no subprocess; success → link composed;
  failure modes per D15 (brief still sent).
- `tests/services/stats/test_service.py` — cleanup rider: enabled → launcher
  called with `{mode}=cleanup` once per cycle; disabled → not called; launcher
  exception isolated (cycle still advances gate).

**Docs:** [`docs/llm/services.md`](../llm/services.md) (cleanup rider),
[`docs/llm/architecture.md`](../llm/architecture.md) (display tier paragraph),
this design doc's status line when it lands.
**CHANGELOG:** `Added` — optional `-w` web-page generation with `[stats-pages]`
config, per-chat rate limit, TTL cleanup.

**Gate 3b:** `make format lint`; `make test`; `make check-docs`; manual smoke
(local, operator-optional): enable `[stats]` + `[stats-pages]` with a temp
output-dir, `/stats 7d -w`, open the generated HTML offline (no network) and
verify the link resolves.

---

## 7. Verification gates

| Gate | Command / action | When |
|---|---|---|
| Format + lint | `make format lint` (before AND after edits) | every phase |
| Full suite | `make test` (timeout-wrapped; mandatory) | every phase |
| Docs links | `make check-docs` | every phase |
| Query portability | `TestQuery` matrix (filters, ISO bounds, sentinel, pagination) | Phase 1 |
| No-double-count | analysis test asserting `__global__` rows excluded by scope filter | Phase 1/2 |
| Command gating | stats-off → no registration + `__init__` raises; stats-on → registered, `LLMMessageHandler` still last | Phase 2 |
| Scope correctness | group/private/chat-drill authorization tests | Phase 2 |
| Bounded digest | digest-render test asserts length < 3500 chars | Phase 2 |
| Stats-off silence | entire feature (command + pages) inert when `[stats] enabled = false` | every phase |
| CLI contract | generate/cleanup/delete + stdout JSON + failure exits | Phase 3 |
| Subprocess safety | timeout-kill, nonzero-exit, unparseable-stdout tests | Phase 3 |
| Rate limit | refusal path never invokes the CLI | Phase 3 |
| Cleanup rider | invoked once per cycle when enabled; isolated on failure | Phase 3 |
| Offline page | generated HTML contains no external resource references | Phase 3 |

No live/operator smoke gate is mandatory beyond the optional Phase 3 local smoke
(default-off feature; same stance as the two prior stats designs).

---

## 8. Risk register

| # | Risk | Likelihood | Impact | Mitigation | Rollback |
|---|---|---|---|---|---|
| R1 | **Query cost / cardinality** — `stat_aggregates` grows with distinct label combos × periods; a scope query scans all label buckets of the window | Med | Med | PK prefix `(event_type, period_start)` serves the SQL predicate; `limit=10000` cap + explicit truncation line (D5); SUM-only buckets stay small vs `stat_events` (aggregation-v1 NG3 analysis); revisit retention per its §9 Q2 | Raise nothing — read-only; lower `limit` |
| R2 | **Double counting via `__global__` rows** — naively summing a window counts every event twice | Med | High | The D3 consumer-scope filter structurally excludes `__global__`; pinned by an explicit analysis test (Gate: no-double-count) | n/a (test-locked) |
| R3 | **Per-chat LLM undercount** (§2.3 exceptions: embeddings, background calls, condensing land in `__global__`) | Certain (today) | Low | Documented in `help`/digest honesty ("LLM counts cover interactive generation"); fix path is a small follow-up (O2), not a display-layer concern | n/a |
| R4 | **Backfill/live label split** — direction breakdown misread as undercount | Low | Low | Three-bucket rendering (users/bot/history) per §2.4/D6 | n/a |
| R5 | **Digest too long → mechanical split breaks MarkdownV2** | Low | Low | Bounded digest (< 3500 chars, Gate); top-3 lists; drill-downs bounded to top-10 | Shorten digest |
| R6 | **Disk exhaustion via page generation** | Med | Med | Per-chat rate limit (3/h default) + UUID names (no overwrite) + TTL cleanup rider + `output-dir` is operator-designated | Disable `[stats-pages]`; `cleanup`/`delete` CLI modes |
| R7 | **CLI hangs / misbehaves** | Low | Med | 30 s `wait_for` + kill (§2.9 conventions); JSON-validated stdout; D15 failure table; external commands are operator-supplied (WARNING not ERROR, proxy precedent) | `-w` off / fix `command` |
| R8 | **`output-dir` unwritable or outside web root** | Med | Low | Startup validation when enabled (fail loudly, A4 pattern); runtime failure → D15 note | Fix config |
| R9 | **Unguessable-URL-only "auth"** — link sharing exposes scope aggregates | — (ratified) | Low | Ratified for non-sensitive aggregates (NG4); UUIDv4 hex; TTL; scope already bounds what is visible | Lower ttl-hours |
| R10 | **Stale pages after stats disabled** — cleanup rider early-returns on empty registry | Low | Low | Documented (D14); operator can run `{mode}=cleanup` manually or `rm`; NG5 keeps no bot UI | Manual cleanup |
| R11 | **Check-then-apply rate-limit race** over-admits a few concurrent `-w` | Low | Low | Single event loop bounds interleaving; consequence ≤ a few extra files per window (D13) | n/a |
| R12 | **Template misconfiguration** (unknown placeholder, wrong bin path) | Med | Low | Strict `format_map` → KeyError → D15 note + WARNING log naming the command | Fix `command` |
| R13 | **Cleanup cadence inherits aggregation interval** | Low | Low | Documented (D14); worst case files live TTL + interval | Lower `aggregation-interval-seconds` or run manual cleanup |
| R14 | **`request_count` counts attempts, not logical requests** (fallback loop, §2.2) | — (documented) | Low | Rendered as "requests (attempts)" in help/footnote; not fixable display-side | n/a |

**Rollback principle:** the whole display tier is gated on `[stats] enabled` (the
command and page generation disappear with one flag; the read API is inert code
when nothing calls it). Each phase is independently revertible via git; no
migration exists to unwind.

---

## 9. Open questions

1. **O1 — Bot-side delete-by-id UI** (NG5): v1 ships the CLI `delete <id>` mode only.
   If page litter becomes a user complaint, a follow-up can add e.g.
   `/stats pages` (list recent ids for this chat) + a delete verb. Verification
   plan: none needed now — the invocation contract (D12) is frozen so the future
   UI needs no CLI change.
2. **O2 — Per-user `llm_request` attribution** (R3): thread `consumerId` through
   `LLMService.generateEmbedding` ([service.py:1499](../../internal/services/llm/service.py))
   and the condensing call (:1239), and optionally real chat ids into the two
   background callers; separately consider a `user_id` label for interactive
   generation (would change label vocabulary → new buckets only going forward —
   same freeze caveat as stats-collecting-v1 Caveats). Follow-up design/task, not
   a blocker; display layer needs no change either way.
3. **Aggregates retention**: still open repo-wide (aggregation-v1 §9 Q2); with a
   query API now landing, row counts become observable — revisit after real-world
   cardinality data exists.
4. **i18n of `/stats` output**: v1 follows repo precedent (Russian replies). If a
   localization pass ever happens repo-wide, the digest strings ride along; no
   design change.

---

## 10. Documentation impact (when implementation lands)

Load the [`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md)
skill and update:

- [`docs/llm/libraries.md`](../llm/libraries.md) §9 — `StatsStorage.query()`,
  `StatsAggregateDict` (lib/stats/types.py), `StatsAnalyzer`.
- [`docs/llm/services.md`](../llm/services.md) — `StatsAggregationService`:
  `getQueryStorage` accessor (Phase 1) and the `[stats-pages]` TTL-cleanup rider
  (Phase 3).
- [`docs/llm/handlers.md`](../llm/handlers.md) — `StatsDisplayHandler`: command
  grammar, scoping, conditional registration on `[stats] enabled`.
- [`docs/llm/configuration.md`](../llm/configuration.md) — `[stats-pages]` table
  (keys, defaults, placeholders); `[ratelimiter]` additions; note that `[stats]`
  is unchanged.
- [`docs/llm/architecture.md`](../llm/architecture.md) — stats pipeline section:
  add the read/display tier (query API → /stats → optional page generation).
- [`docs/llm/index.md`](../llm/index.md) — §4 map: `internal/stats_pages/`;
  handler-list entry for `/stats`.
- [`CHANGELOG.md`](../../CHANGELOG.md) — Phase 2 and Phase 3 `Added` entries per
  [`docs/llm/changelog.md`](../llm/changelog.md) rules (this PROPOSED doc itself
  gets no entry — doc-only).
- **Schema docs unchanged** — no migration, no DDL (state explicitly in the PR
  description so reviewers don't hunt for one).

---

## 11. References

- Predecessor designs: [`stats-collecting-v1.md`](./stats-collecting-v1.md)
  (event taxonomy, wiring, backfill semantics),
  [`stats-aggregation-v1.md`](./stats-aggregation-v1.md) (aggregation cycle,
  factory/registry, A1-A4 amendments); archived aggregate()-flow design:
  [`docs/archive/plans/lib-stats-stats-library-v3.md`](../archive/plans/lib-stats-stats-library-v3.md).
- Stats interface + rows: [`lib/stats/stats_storage.py`](../../lib/stats/stats_storage.py),
  [`internal/database/stats_storage.py`](../../internal/database/stats_storage.py);
  schema: [`migration_016_add_stat_tables.py`](../../internal/database/migrations/versions/migration_016_add_stat_tables.py).
- Aggregation service + registry: [`internal/services/stats/service.py`](../../internal/services/stats/service.py);
  construction order: [`main.py`](../../main.py):88-153.
- Record sites: [`base.py`](../../internal/bot/common/handlers/base.py):1143-1169,
  [`manager.py`](../../internal/bot/common/handlers/manager.py):1041-1056,
  [`llm/service.py`](../../internal/services/llm/service.py):1009-1019,
  [`lib/ai/abstract.py`](../../lib/ai/abstract.py):850-935,
  [`lib/stt/abstract.py`](../../lib/stt/abstract.py):228-278.
- Scoping: [`common.py`](../../internal/bot/common/handlers/common.py):372-427,
  [`base.py`](../../internal/bot/common/handlers/base.py):1322-1355,
  [`chat_users.py`](../../internal/database/repositories/chat_users.py):271-327.
- Command machinery: [`command_handlers.py`](../../internal/bot/models/command_handlers.py):27-146,
  args precedent [`chat_search.py`](../../internal/bot/common/handlers/chat_search.py):1074-1141,
  gating [`manager.py`](../../internal/bot/common/handlers/manager.py):565-627 +
  [`weather.py`](../../internal/bot/common/handlers/weather.py):75-78.
- Rate limiting: [`lib/rate_limiter/manager.py`](../../lib/rate_limiter/manager.py),
  [`lib/rate_limiter/sliding_window.py`](../../lib/rate_limiter/sliding_window.py),
  consumer [`stt/service.py`](../../internal/services/stt/service.py):298-301,
  config [`00-config.toml`](../../configs/00-defaults/00-config.toml):68-102.
- Subprocess conventions: [`internal/services/proxy/lifecycle.py`](../../internal/services/proxy/lifecycle.py):105-150;
  rendering: [`lib/markdown/parser.py`](../../lib/markdown/parser.py):589-618,
  [`internal/bot/common/bot.py`](../../internal/bot/common/bot.py):654-669/969-978.
- SQL portability: [`docs/sql-portability-guide.md`](../sql-portability-guide.md).
- Skills: [`add-handler`](../../.agents/skills/add-handler/SKILL.md),
  [`run-quality-gates`](../../.agents/skills/run-quality-gates/SKILL.md),
  [`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md).
