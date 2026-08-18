# Design: Statistics display v1 — `/stats` command and optional web pages

**Date**: 2026-08-18
**Status**: **Amended 2026-08-18 (user round 3 + U11 same-day)** (PROPOSED content as amended)
**Owner**: TBD
**Branch**: `lib-stat-improvement`

## Amendments (2026-08-18, user round 3 — user-ratified; U11 later the same day)

Ten user-ratified amendments (U1-U10) supersede parts of the original
decisions; the affected D-decisions are reworked in place and marked
*(amended 2026-08-18)*, and one decision is added (D16). Everything this round
does not touch — the query API (D4/D5), rate-limiting pre-check+refuse (D13),
stdin-JSON / stdout-`{"id","url"}` CLI contract, relative `url` + `base-url`
composition, failure-mode table shape (D15), UTC labeling, username join,
three-bucket `sent` rendering, and Phase 1 — stands unchanged. New grounding
for this round lives in §2.5 (addendum), §2.6 (addendum), and §2.12-§2.13;
all file:line claims there were verified against source on 2026-08-18.

A later same-day user decision adds **U11** (below): the page-registry
mechanism of U9 is superseded — NO page tracking at all. D14 is rewritten
again in place, D10's validation home moves to `StatsHandler` construction,
§2.13's seeding analysis is mooted, and §4-§11 are updated accordingly.
U9's ratified text below stays as history.

- **U1 — Default outputs** (supersedes the D6 multi-section digest default and
  part of D3): GROUP chat → MESSAGE STATS ONLY for that chat (other sections
  via `--section=`); PRIVATE chat → message stats for the current private
  chat + a list of the user's chats (chat id + name + the USER's messages
  count in each — operational `chat_users` data via `getUserChats`, works
  even where aggregates are sparse). Positional chatId (private only)
  selects the target chat; must be a chat the user is a member of; in a
  group a chatId argument is a usage error.
- **U2 — Handler naming**: `StatsHandler`, file
  `internal/bot/common/handlers/stats.py` (NOT `StatsDisplayHandler`) —
  leaves room for future stat-related actions in the same handler.
- **U3 — Args grammar** (rewrites D2): argparse-like. Positionals `help` OR
  chatId (mutually exclusive; chatId private-only); options `--period=`,
  `--section=`, `--user=<id>`, `--web`. Unknown option / bad value / dangling
  positional → usage reply. FLAG: a NEW args-pattern for the repo — deliberate
  divergence from the `/users` token-loop precedent.
- **U4 — `/stats_web` alias**: an alias running the SAME handler with web
  generation forced on — the `commands=` tuple mechanism (`/taro`|`/tarot`),
  not a second handler class.
- **U5 — Scoping** (amends D3): chat type comes canonically from
  `ensuredMessage.recipient.chatType` (`ChatType` StrEnum); any chatId-sign
  (`> 0` → private) parsing is removed from the design's scope logic.
- **U6 — Chat-settings gate**: new chat setting `ALLOW_SHOW_STATS`
  (`allow-show-stats`), default ENABLED, following the add-chat-setting
  four-site pattern; a chat admin can disable stats showing FOR THAT CHAT.
  Explicitly NOT the LLM tool-gate — a plain chat setting read by the
  command handler.
- **U7 — CLI config**: TWO templates — `generate-command` and
  `delete-command` — instead of one mode-switched `command`. Substitutions:
  generate `{user_id}`/`{chat_id}`/`{platform}`; delete `{page_id}` only.
  `{mode}` and `{output_dir}` are REMOVED entirely — the CLI owns all storage
  decisions; the bot neither knows nor cares where pages are stored, or
  whether they are files at all.
- **U8 — Built-in generator location**: `lib/stats/stats_pages/`
  (module-invocable: `./venv/bin/python3 -m lib.stats.stats_pages`), NOT
  `internal/stats_pages/`. Default values of both command templates point at
  it.
- **U9 — TTL cleanup via a persisted delayed task** (rewrites the cron-rider
  cleanup decision D14): new `DelayedTaskFunction.STATS_PAGES_CLEANUP`,
  DB-persisted (skipDB=False) and self-rescheduling — survives bot restarts
  naturally. REQUIRED CONSEQUENCE (teamlead judgment call, flagged for the
  reviewer in D14): since delete is by `{page_id}` and the bot no longer
  knows output paths, the bot must REMEMBER generated pages → small
  **page-registry table** `stats_pages` (migration 029), inserted on
  successful generation; the cleanup task selects rows older than TTL and
  invokes `delete-command` per `page_id` (bounded batch, per-page failure
  isolation), then removes registry rows.
- **U10 — Housekeeping**: §4 wiring, §5 config, §6 phases, §7 gates, §8
  risks, §9 open questions, §10 documentation impact, and §11 references
  updated; D-numbers unchanged (D14 rewritten in place; D16 added).
- **U11 — No page tracking: one persisted one-shot deletion task per page**
  (2026-08-18, later than U9-U10; supersedes U9's *mechanism* — U9's
  ratified text above stays as history): NO page registry at all — no
  `stats_pages` table, no migration 029, no `StatsPagesRepository` /
  `getExpiredPages`, no periodic self-rescheduling cleanup task, no
  first-CRON-tick seeding, and no `[stats-pages]` handling in
  `StatsAggregationService` (the A4-style `[stats-pages]` caching there is
  gone; D10 validation moves to `StatsHandler` construction). New mechanism:
  after SUCCESSFUL page generation (CLI returned `{"id","url"}`),
  `StatsHandler` schedules ONE DB-persisted delayed task —
  `addDelayedTask(delayedUntil = now + ttl-hours × 3600, function =
  DelayedTaskFunction.STATS_PAGES_CLEANUP, kwargs = {"pageId": <id>,
  "command": <the delete-command template with {page_id} ALREADY
  substituted>}, skipDB=False)` — survives restarts; kwargs are
  self-contained (config frozen at load — no ConfigManager reload, NG6). The
  `STATS_PAGES_CLEANUP` enum name is retained; semantics: one-shot per-page
  deletion, NOT periodic cleanup. Handler owner = `StatsHandler`:
  `registerDelayedTaskHandler(DelayedTaskFunction.STATS_PAGES_CLEANUP, …)`
  in its `__init__` (the handler exists exactly when `[stats] enabled`,
  since construction is gated; `[stats-pages]` requires `[stats]` —
  dependency unchanged; NO seeding needed, the seed race is moot).
  Pending deletion task while stats is disabled hits the queue-service
  no-handler re-delay path (task re-delays in memory for the process lifetime
  but the DB row is marked done on first firing — after restart the task is gone;
  orphaned page file is the accepted R13 outcome) — documented (R10). Handler behavior: run the resolved argv via
  `asyncio.create_subprocess_exec` (same conventions as generation: ~30 s
  timeout, DEVNULL/PIPE per `docs/llm/tasks.md:489`); CLI output
  `{"deleted": 0}` tolerated; failure → WARNING log and the task completes
  (SINGLE attempt, no retry loop — an orphaned page file is the accepted
  bounded risk, R13). `ttl-hours` semantics: per-page deletion task delay
  (was "page-registry cutoff").

 - **Deviation 2026-08-18 (Gate-1 Round B P3b) — D11's "grouping logic exists exactly once" not fully achieved**: The reply-text renderers and the payload builders remain two pipelines (unification deferred — follow-up candidate). Mitigations shipped: chatList condition aligned (private ∧ no user filter), possiblyIncomplete propagated into payload sections (FIX 5), averages now correct (FIX 1), subprocess mechanics extracted to `lib/stats/stats_pages/launcher.py` (satisfying the "exactly once" principle at the subprocess level).

**Scope**: The read/display tier over `stat_aggregates`: a `query()` read API on the
`lib/stats` `StatsStorage` ABC, ONE user-facing `/stats` bot command with a
`/stats_web` alias (single-section default reply, scope-derived visibility,
`--section`/`--user` drill-downs), and an optional config-gated web-page
generation tier (payload → local CLI subprocess → self-contained static HTML,
TTL-cleaned via ONE DB-persisted one-shot delayed deletion task per page —
no page tracking, U11).
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
label work to Python; (2) ONE `/stats` command (+`/stats_web` alias; argparse-style
grammar, scope-derived access, bounded single-section default reply, drill-downs)
registered only when `[stats] enabled`; (3) an optional `--web` flag (equivalent to
the `/stats_web` alias) that renders the same query results into a self-contained
static HTML page via a configurable local CLI subprocess, rate-limited per chat and
cleaned up by TTL through one persisted one-shot delayed deletion task per page
(no page tracking, U11). The in-chat output must never depend on tier 3 working.

### 1.1 Goals

- **G1** — Read API: `query()` on the `lib/stats` ABC returning rows with **parsed**
  labels dicts; `NullStatsStorage.query` returns `[]`; portable SQL (no JSON1, no
  dialect functions, `:named` placeholders, provider-routed, `applyPagination`).
- **G2** — ONE `/stats` command (+ `/stats_web` alias), permission `DEFAULT`,
  registered only when `[stats] enabled` (WeatherHandler-style conditional
  registration).
- **G3** — Scope-derived visibility: group chat → that chat only; private chat →
  the user's chats via the existing `getUserChats` (default view = current
  private chat + the chat list; positional chatId targets a member chat);
  **no permission tiers** — all operational detail is visible to everyone
  within their scope.
- **G4** — Default reply *(amended 2026-08-18, U1)*: group → message stats for
  that chat; private → message stats for the current private chat + a list of
  the user's chats (id, title, the user's messages count per chat). Other
  sections via `--section=messages|commands|tools|llm`; user drill-down via
  `--user=<id>`; chat drill-down via the positional chatId (private only);
  `/stats help`.
- **G5** — Optional web tier *(amended 2026-08-18, U3/U4)*: `--web` (or the
  `/stats_web` alias) generates a self-contained HTML page (UUID filename,
  inline CSS, no external resources, zero new runtime dependencies) via a
  configurable CLI subprocess (stdin JSON in, stdout JSON `{"id", "url"}` out),
  rate-limited per chat, TTL-cleaned via one persisted one-shot delayed
  deletion task per page (U11), best-effort — failure never degrades the
  in-chat reply.
- **G6** — All displayed periods are labeled UTC.

### 1.2 Non-goals

- **NG1** — No new tables, no migration, no schema change *(restored
  2026-08-18, U11 — the U9-era page-registry table was removed before any
  implementation)*. The read API over `stat_events`/`stat_aggregates` is
  migration-free, and U11's per-page deletion tasks need no tracking table;
  the only data-model change is the additive `ChatInfoDict` extension with
  the user's `messages_count` (existing column, no DDL, §2.5 addendum).
- **NG2** — No `stat_aggregates` retention/cardinality management
  (carried over from stats-aggregation-v1 §9 Q2; see R1).
- **NG3** — No per-user attribution for `llm_request` events (they carry no
  `user_id` label; see §2.3 and O2). No rework of the recording label vocabulary —
  changing labels would split `labels_hash` buckets (frozen per
  stats-collecting-v1 Caveats).
- **NG4** — No auth on generated pages. Ratified: unguessable UUID URL + TTL is the
  protection (aggregates deemed non-sensitive within scope).
- **NG5** — No bot-side USER-facing UI for deleting a page by id in v1
  *(amended 2026-08-18)*: the CLI `delete` verb now exists and is wired to the
  TTL cleanup task (D12/D14); a user-facing delete/list verb remains future
  work, see O1.
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
  ([chat_search.py:552-556](../../internal/bot/common/handlers/chat_search.py),
  deliberate per its docstring :532-534) and
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
  and *absent* (backfill). The reply renders the absent bucket explicitly as
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

**Addendum (2026-08-18, U1 grounding): the returned shape has id + title but NOT
the user's messages count.** `ChatUsersRepository.getUserChats` selects `ci.*`
only — `SELECT ci.* FROM chat_info ci JOIN chat_users cu ON cu.chat_id =
ci.chat_id WHERE user_id = :userId`
([chat_users.py:303-315](../../internal/database/repositories/chat_users.py)) —
so the returned `ChatInfoDict` (`chat_id`/`title`/`username`/`type`/`is_forum`/
`bot_status`/…, [models.py:213-231](../../internal/database/models.py)) carries
chat identity but NOT `cu.messages_count`, even though the join already visits
the row that holds it: `chat_users` is keyed `(chat_id, user_id)` and
`messages_count` lives there ([chat_users.py:246-253](../../internal/database/repositories/chat_users.py),
the `getChatUsers` filter). The private-scope chat list needs chat id + name +
the USER's messages count per chat, so the SMALLEST addition is: add
`cu.messages_count` to that one SELECT and a `messages_count: int` field to
`ChatInfoDict` (additive — `dbUtils.sqlToTypedDict` fills matching keys, and
existing consumers ignore the new field; `/list_chats` output is unaffected).
Multi-source dedup keeps the first source's count
([chat_users.py:316-321](../../internal/database/repositories/chat_users.py)) —
acceptable for an operational counter. **No new query.**

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
  This remains the documented precedent FOR THAT STYLE; the amended D2
  deliberately diverges from it (argparse-style) — see D2's flag.
- **Canonical chat type (2026-08-18 amendment grounding, U5)**:
  `ensuredMessage.recipient.chatType` is the canonical chat-type source at
  command time. `ChatType` is a StrEnum (`PRIVATE`/`GROUP`/`CHANNEL`,
  [ensured_message.py:57-71](../../internal/bot/models/ensured_message.py))
  living on `MessageRecipient` ([ensured_message.py:86-97](../../internal/bot/models/ensured_message.py)),
  populated platform-side by `fromTelegramChat`
  ([ensured_message.py:108-130](../../internal/bot/models/ensured_message.py))
  and `fromMaxRecipient` (:132-159). `handleCommand` itself already reads it
  ([manager.py:966](../../internal/bot/common/handlers/manager.py)) and
  handlers branch on it (e.g. [base.py:750](../../internal/bot/common/handlers/base.py)).
  Chat-type checks MUST use this enum, never the `chatId > 0` sign heuristic.
- **Command aliases and platform (2026-08-18 amendment grounding, U4/U7)**:
  `@commandHandlerV2(commands=…)` accepts a Sequence of names — ONE
  registration, N aliases; the established shape is
  `commands=("taro", "tarot", "таро")`
  ([divination.py:284-292](../../internal/bot/common/handlers/divination.py);
  also `("runes", "rune", "руны")` :322-329, `("summary", "topic_summary")`
  [summarization.py:705](../../internal/bot/common/handlers/summarization.py)).
  `getCommandHandlersDict` maps every alias (lower-cased) to the SAME handler
  info ([manager.py:877-880](../../internal/bot/common/handlers/manager.py));
  the INVOKED command name reaches the handler as its `command` argument
  ([manager.py:1037-1039](../../internal/bot/common/handlers/manager.py);
  signature [command_handlers.py:96-98](../../internal/bot/models/command_handlers.py));
  `/help` renders ONE entry per registration with the aliases pipe-joined —
  `"|".join(v.commands)` ([help_command.py:212](../../internal/bot/common/handlers/help_command.py)).
  Platform: every handler is constructed with `botProvider: BotProvider`
  (`BotProvider.TELEGRAM = "telegram"`, `BotProvider.MAX = "max"`,
  [enums.py:8-20](../../internal/bot/models/enums.py); ctor
  [base.py:143-151](../../internal/bot/common/handlers/base.py)) and stores it
  as `self.botProvider` — `self.botProvider.value` is the `{platform}`
  substitution value.

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
   boundary can cut an escaped entity mid-way — **the in-chat reply must stay well
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

### 2.12 Chat settings (grounding for the command gate, U6)

- `ChatSettingsKey` is a StrEnum whose Python names are UPPER_CASE and whose
  string values are **kebab-case** matching the TOML key
  ([chat_settings.py:287](../../internal/bot/models/chat_settings.py)). The
  `allow-*` family precedents: `ALLOW_TOOLS_COMMANDS = "allow-tools-commands"`
  (:389), `ALLOW_SANDBOX = "allow-sandbox"` (:391), `ALLOW_MENTION =
  "allow-mention"` (:398).
- Metadata lives in `_chatSettingsInfo` — dict literals of `ChatSettingsInfoValue`
  (`type`/`short`/`long`/`page`, dict declared at
  [chat_settings.py:628](../../internal/bot/models/chat_settings.py)):
  `ALLOW_TOOLS_COMMANDS` → BOOL/page `PAID` (:907-912), `ALLOW_SANDBOX` →
  BOOL/page `FRIEND` (:913-923), `ALLOW_MENTION` → BOOL/page `STANDARD`
  (:963-968). `ChatSettingsPage` is an IntEnum
  ([chat_settings.py:160-186](../../internal/bot/models/chat_settings.py));
  `STANDARD` has minimum tier `FREE` (:227-231) — the page for basic
  any-tier flags.
- Defaults live under `[bot.defaults]` in
  [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml)
  (e.g. `allow-sandbox = false`, :90; `allow-tools-commands = true`, :88). The
  `allow-tools-commands = false` at :54 sits under `[bot.channel-defaults]`
  (channel-only override), not the operative default.
- **Who sets them**: `/set`|`/unset`
  ([dev_commands.py:322-327](../../internal/bot/common/handlers/dev_commands.py),
  category `TECHNICAL` → centrally admin-gated per
  [manager.py:1007-1009](../../internal/bot/common/handlers/manager.py)) and
  the `/settings` configure wizard
  ([configure.py](../../internal/bot/common/handlers/configure.py)), with
  `ADMIN_CAN_CHANGE_SETTINGS` ("Whether chat admins can modify chat settings",
  [chat_settings.py:368-369](../../internal/bot/models/chat_settings.py))
  deciding whether chat admins may change settings (enforced at
  [configure.py:203](../../internal/bot/common/handlers/configure.py) and
  :832); bot owners bypass.
- **No GENERIC per-command disable mechanism exists today.** `handleCommand`'s
  central gates are per-CATEGORY
  ([manager.py:994-1013](../../internal/bot/common/handlers/manager.py)):
  `CommandCategory.TOOLS` → `ALLOW_TOOLS_COMMANDS` or bot owner (:1002-1004);
  `SPAM` → admin or `ALLOW_USER_SPAM_COMMAND` (:1005-1006); `ADMIN` /
  `SPAM_ADMIN` / `TECHNICAL` → admin; `PRIVATE` → private chats only;
  `UNSPECIFIED` → **deny by default** (:995-997). Feature toggles are
  otherwise per-feature keys checked inside the feature's own handler — the
  precedent is `ALLOW_SANDBOX`, checked at each sandbox command entry
  ([sandbox.py:285](../../internal/bot/common/handlers/sandbox.py) and five
  more sites).
- Handler-layer read shape: `self.getChatSettings(chatId)` returns
  `ChatSettingsValue` objects — `settings[key].toBool()`; never tuple-index
  (add-chat-setting skill, Gotcha A). Writing goes through `setChatSetting(...,
  user=MessageSender)` (keyword-only `user` at the handler layer).
- The four-site pattern (enum value + `_chatSettingsInfo` entry + TOML default
  + consumer) is codified in the
  [`add-chat-setting`](../../.agents/skills/add-chat-setting/SKILL.md) skill
  (:32-118).

### 2.13 Delayed tasks — persisted lifecycle (grounding for the cleanup task, U9)

> **Superseded by U11 (2026-08-18):** the live design no longer uses a
> periodic self-rescheduling STATS_PAGES_CLEANUP task, so this section's
> seeding analysis (the idempotent-seed consequence, the first-CRON-tick
> placement rule, and the duplicate-chain crash window — risks R15/R16,
> removed from §8) is MOOT — no seeded task exists. The body below stands
> as the verified historical record. The live mechanism (ONE one-shot
> per-page task scheduled on generation, D14) still relies on the per-task
> facts here: DB persistence + restart restoration (:309-318), mark-done
> after handlers run (:401-402), and the no-handler re-delay path
> (:385-388).

- `DelayedTaskFunction` StrEnum today: `SEND_MESSAGE`, `DELETE_MESSAGE`,
  `CRON_JOB`, `DO_EXIT` — no stats member
  ([types.py:9-19](../../internal/services/queue_service/types.py));
  `DelayedTask(taskId, delayedUntil, function, kwargs)` (:22-44);
  `DelayedTaskHandler = Callable[[DelayedTask], Awaitable[None]]` (:71).
- `QueueService.addDelayedTask(delayedUntil, function, kwargs, taskId=None,
  skipDB=False, skipLogs=False)`
  ([service.py:420-481](../../internal/services/queue_service/service.py)):
  auto-generated `taskId` when None (:464-465); in-memory priority-queue put
  (:469); DB persistence ONLY when `skipDB=False` (:470-478; raises when the
  DB is missing, :471-472).
- `registerDelayedTaskHandler(function, handler)`
  ([service.py:233-266](../../internal/services/queue_service/service.py)) —
  append-based; handlers run sequentially per fired task (:390-399).
- **The self-reschedule handler SHAPE (the precedent cited by the brief)**:
  QueueService's own `_cronJobHandler` re-adds CRON_JOB at `time.time() + 60`
  with `skipDB=True, skipLogs=True`
  ([service.py:190-201](../../internal/services/queue_service/service.py)) —
  in-memory only, re-seeded at startup. The stats-pages cleanup task copies
  this SHAPE but passes `skipDB=False` — PERSISTENCE is the point: the task
  survives restarts without re-seeding.
- **Restart restoration**: `startDelayedScheduler` seeds the CRON tick
  (`skipDB=True`, :302-307), then reads `db.delayedTasks.getPendingDelayedTasks()`
  and re-adds EVERY pending DB row to the in-memory queue (:309-318, restore
  passes `skipDB=True`) before starting the processing loop (:320). This is
  what makes a persisted task restart-surviving — and it means the first CRON
  tick handler execution happens STRICTLY AFTER restoration (sequential inside
  `startDelayedScheduler`).
- After a task's handlers run, the loop marks the row done in the DB:
  `updateDelayedTask(taskId, True)` (:401-402). Tasks with no registered
  handler are re-delayed +60 s with an error log (:385-388).
- Repository ([delayed_tasks.py](../../internal/database/repositories/delayed_tasks.py)):
  `addDelayedTask` is a **plain INSERT** (:155-176) — a duplicate id raises
  inside the repo and is swallowed into `return False` (no upsert), so a
  FIXED taskId re-add is unusable for self-rescheduling (and a completed row
  is never overwritten); `getPendingDelayedTasks` returns ALL pending rows
  with **no function filter** (:226-269; `DelayedTaskDict.function` exists —
  [models.py:291-292](../../internal/database/models.py) — so filter in
  Python); completed rows are removed only by
  `cleanupOldCompletedDelayedTasks` (:271-324).
- **Idempotent-seed consequence**: seed with a FRESH auto `taskId`
  (`skipDB=False`), guarded by a Python-side check over
  `getPendingDelayedTasks()` for the new function value. Do NOT seed from
  `GromozekBot.__init__` — `startDelayedScheduler` runs as a `create_task`
  ([main.py:75-78](../../main.py)) and a seed racing its restoration read can
  double-add the same pending row (permanent duplicates via self-reschedule).
  Seed from the FIRST CRON tick instead (strictly post-restore, §2.13 above).
  Residual crash window between a handler's persisted re-add and the old
  row's mark-done can leave two pending rows → two live instances; the
  cleanup is idempotent (delete by `page_id`), so a duplicate instance is
  benign (R15).

---

## 3. Architecture decisions

All of D1-D15 encode the user-ratified direction (2026-08-18); sub-choices the
ratified text left open are resolved against the evidence in §2 and marked
**flagged** with rationale. The **2026-08-18 amendments** (user round 3,
U1-U10, plus the later same-day U11, above) rework D1/D2/D3/D6/D7/D10/D11/
D12/D14 in place, adjust D15's table, and add D16; U11 rewrites D14's
mechanism again (one-shot per-page deletion, no registry) and moves D10's
validation home. Amended decisions are marked *(amended 2026-08-18)*.

### D1 — ONE `/stats` command (+ `/stats_web` alias), DEFAULT permission, gated registration *(amended 2026-08-18: U2/U4)*

`StatsHandler(BaseBotHandler)` in
`internal/bot/common/handlers/stats.py` — **not** `StatsDisplayHandler`
(U2: leave room for future stat-related actions in the same handler) —
registered in `HandlersManager` **only when `[stats] enabled`** using the
verified conditional-append mechanism
([manager.py:565-609](../../internal/bot/common/handlers/manager.py) pattern), with
the `__init__` self-check raising `RuntimeError` when stats are off
([weather.py:75-78](../../internal/bot/common/handlers/weather.py) pattern).

```python
@commandHandlerV2(
    commands=("stats", "stats_web"),
    shortDescription="[--period=…] [--section=…] [--user=<id>] [chatId] [--web] - Statistics",
    helpMessage=" … ",                       # usage text, Russian per repo precedent
    visibility={CommandPermission.DEFAULT},
    availableFor={CommandPermission.DEFAULT},
    helpOrder=CommandHandlerOrder.NORMAL,
    category=CommandCategory.TOOLS,
)
async def statsCommand(self, ensuredMessage, command, args, updateObj, typingManager) -> None:
```

- **The alias is the `commands=` tuple, not a second handler** (U4): one
  registration, two names — the `/taro`|`/tarot` mechanism
  ([divination.py:284-292](../../internal/bot/common/handlers/divination.py),
  §2.6). `getCommandHandlersDict` maps both names to this one handler info
  ([manager.py:877-880](../../internal/bot/common/handlers/manager.py)), and the
  INVOKED name arrives as the `command` argument
  ([manager.py:1037-1039](../../internal/bot/common/handlers/manager.py)); the
  handler sets `web = (command == "stats_web") or parsedWebFlag`.
  Help-text implication: `/help` shows ONE `/stats|stats_web` entry
  ([help_command.py:212](../../internal/bot/common/handlers/help_command.py));
  registration-order implications: none (one registration = one dict entry per
  alias; the handler list and the LLMMessageHandler-stays-last invariant are
  untouched). Stats recording notes each alias separately (`commandName`
  label, [manager.py:1045](../../internal/bot/common/handlers/manager.py)) —
  fine.
- **Coarse category gate (documented consequence)**: `category=TOOLS` means
  `handleCommand` centrally requires `ALLOW_TOOLS_COMMANDS` or bot owner
  ([manager.py:1002-1004](../../internal/bot/common/handlers/manager.py)) — the
  same coarse gate `/users` already rides
  ([chat_search.py:1088](../../internal/bot/common/handlers/chat_search.py)).
  The dedicated per-chat opt-out is the new `ALLOW_SHOW_STATS` setting (D16).
  Effective out-of-the-box visibility: `[bot.defaults]
  allow-tools-commands = true` (§2.12) makes `/stats` available in groups and
  private chats, and denied in channels (`[bot.channel-defaults]
  allow-tools-commands = false`, :54).

**No permission tiers** (user decision, explicitly against an owner-only tier for
operational detail): modelName, provider, tokens, error rates are visible to
everyone within their scope (D3). Registration block sits beside the sandbox /
chat-search blocks (before `LLMMessageHandler`'s final append) — the
stays-last invariant is untouched. The handler is platform-agnostic (common/), so
it serves both Telegram and Max.

### D2 — Args grammar: argparse-like, and period→bucket mapping *(rewritten 2026-08-18: U3)*

```
/stats [help | chatId] [--period=1d|7d|30d|all] [--section=messages|commands|tools|llm]
       [--user=<id>] [--web]

positional (at most one):
  help    usage text (Russian per repo precedent)
  chatId  target chat whose stats are shown — PRIVATE scope only;
          membership-checked (D3); negative numbers are valid
          (group ids), e.g. /stats -100123 --period=30d

options (both --opt=value and --opt value accepted):
  --period=…    default 7d
  --section=…   default messages
  --user=<id>   user drill-down (replaces the old "user <id>" subcommand form)
  --web         web-page generation (boolean flag; equivalent to /stats_web)
```

- **⚠ FLAG — this is a NEW args-pattern for the repo, a deliberate
  divergence** from the `/users` token-loop precedent
  ([chat_search.py:1112-1134](../../internal/bot/common/handlers/chat_search.py),
  §2.6). Rationale (user-ratified): an options-based grammar scales to future
  multi-option commands, which may copy this pattern. Implement with stdlib
  `argparse` over `args.split()` (no new dependencies) or a hand-rolled loop
  with identical observable semantics — the contract below is what matters.
- **Number-vs-option rule** (needed because group chat ids are negative):
  a token starting with `--` is an option; a token starting with `-` followed
  by digits is a positional chatId candidate (argparse's negative-number
  behavior); any other `-x…` token is an unknown option.
- **Error behavior (one rule for everything)**: unknown option, bad option
  value, more than one positional, `help` mixed with anything else, or a
  chatId given in a group/channel context → the reply becomes the usage text
  (no exception, no partial output). This keeps the original unknown-token
  rule; the previous grammar's "dangling `user`/`chat` token" concept is
  **superseded and removed** (options carry their values; a missing value is
  just a bad invocation).
- **Period → bucket mapping (unchanged, previously validated):** `1d →
  period_type=hourly` (last 24 hourly buckets), `7d`/`30d → daily`, `all →
  total` (sentinel row, no range). Mechanical note: a 7d daily window spans 8
  buckets (7 full days + the partial current day) — bucket-granularity
  rounding, documented in `help`.
- `--web` composes with everything: `/stats --period=30d --section=llm --web`
  ≡ `/stats_web --period=30d --section=llm`.

### D3 — Scoping: chat type from `recipient.chatType`; group → this chat; private → current chat or a member chat *(amended 2026-08-18: U1/U5)*

- **Chat type is determined canonically from
  `ensuredMessage.recipient.chatType`** (the `ChatType` StrEnum, §2.6) — the
  same source `handleCommand` itself uses
  ([manager.py:966](../../internal/bot/common/handlers/manager.py)). The
  original design's chatId-sign reading ("group chat = `chatId < 0` per the
  sign convention") is **removed** from this design's scope logic.
- **Group or channel chat**: scope = that chat only. Analysis filter:
  `labels["consumer"] == str(chatId)` (this also excludes `__global__` rows —
  §2.1 corollary). A positional chatId argument is a **usage error** here
  (D2).
- **Private chat**: default scope = **the current private chat**. The chat
  list in the default reply comes from
  `BaseBotHandler.getUserChats(userId)`
  ([base.py:1322-1355](../../internal/bot/common/handlers/base.py), the
  `/list_chats` backend — §2.5 with the messages_count addendum). A
  positional chatId argument selects the target chat whose stats are shown;
  **membership = presence in the `getUserChats` result** — anything else gets
  an informative error ("chat not found among your chats"). The target may be
  any member chat (group or another private chat); the analysis filter is
  always `labels["consumer"] == str(targetChatId)`.
- *(Superseded by U1: the old private default — a multi-section digest over
  the UNION of all the user's chats — no longer exists; the union is replaced
  by the chat list plus per-chat targeting. `getUserChats` is still resolved
  once per private-scope command — the `getUserChats` join plus per-chat
  cache lookups ([base.py:1343-1354](../../internal/bot/common/handlers/base.py)),
  bounded by the user's chat count (§2.5).)*
- `--user=<id>` filters the `user_id` label wherever the event type carries
  it (D7). Authorization for both drills is scope membership, not
  permissions — any user id may be inspected within your scope (same
  visibility rule as before).

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

### D6 — Default outputs and section rendering, bounded output *(amended 2026-08-18: U1 supersedes the multi-section digest default)*

Default no-args reply = **message stats only** (group) or **message stats +
chat list** (private) — NOT a multi-section digest. Sketches (wording frozen
at implementation; user-facing text in Russian per repo precedent —
`/list_chats`, `/users`):

```
GROUP default (/stats in a group):

📊 Stats — 7d (UTC) — this chat
Messages: 1234 (users 1000 / bot 234 / history 0)
  Top: Alice 300 · Bob 210 · Carol 95
/stats help — полная справка
```

```
PRIVATE default (/stats in a private chat):

📊 Stats — 7d (UTC) — this chat
Messages: 42 (users 42 / bot 0 / history 0)
Ваши чаты:
#`-100123` Group A — 300
#`-100456` Group B — 210
#`789012` Private With Bob — 42
/stats help — полная справка
```

- **The chat list is operational `chat_users` data** (`getUserChats` +
  `messages_count`, §2.5 addendum) — it renders even where aggregates are
  sparse or empty (pre-enablement chats still list with their live counter).
  Long lists truncate to top-N by messages count with an "… and K more" line
  (bounded output, below).
- **`--section=` renders any single section** (`messages|commands|tools|llm`)
  at full drill-down depth (top-10) for the current scope/target chat. The
  section keyword `messages` is the default; the former multi-section digest
  no longer exists as a reply shape (U1).
- **`stt` folds into the `llm` section** as its final line (unchanged flagged
  decision): both are model-API requests; STT is default-off in most
  deployments ([main.py:117-121](../../main.py)). The `llm` drill-down shows
  STT detail; the web page renders it as its own sub-table. The section
  keyword stays `llm`.
- **The `llm` section reflects §2.3** (unchanged): scoped views count
  interactive text/structured/image generation (correctly chat-scoped) and
  STT; embeddings and background requests land in `__global__` and are
  invisible to scoped queries (R3) — `help` words this as "LLM counts cover
  interactive generation".
- **Direction split with the three-bucket honesty rule** (unchanged, §2.4):
  users / bot / history-before-stats. The explicit "history (before stats
  enabled)" line is an honesty label on otherwise-missing data, not
  per-view special-case logic.
- **Bounded: ≤ ~30 lines / ~2 500 chars** so every reply fits one message and
  never hits the mechanical character-split (§2.10). Top lists are top-3 in
  default/section replies; drill-downs may use top-10; anything longer
  belongs on the page (tier 3).

### D7 — Drill-downs `--user=<id>` and the positional chatId *(amended 2026-08-18: U1/U3; full drill-downs in scope unchanged)*

- `--user=<id>` (replaces the old `user <id>` subcommand form): per-user
  breakdown across sections — `message` / `command` / `llm_tool_call`
  filtered by `user_id == str(id)` within the scope; totals, per-section
  lines, top message types. **`llm_request` carries no `user_id` label
  (§2.2) and is therefore excluded from user drill-downs** — documented in
  `help` ("LLM requests are chat-level, not user-level"). Authorization:
  none beyond scope (any user id may be inspected within your scope — same
  visibility rule).
- Positional chatId (private scope only, D3): full per-chat detail for all
  four sections at drill-down depth, including llm top-models/tokens and stt
  lines. Membership check per D3; in a group context the chatId positional
  is a usage error (D2).
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

Both the reply header ("7d (UTC)") and the page meta label all periods as UTC.
No local-time conversion is offered in v1 (the `chat_users.timezone` column exists
but per-user rendering timezone is out of scope).

### D10 — Web tier config-gated: `[stats-pages]`, default off *(amended 2026-08-18: U7 — two command templates, no output-dir; U11 — validation moved to StatsHandler construction)*

New config section (§5 for the diff). When `enabled = false` (default) or the
section is absent: `--web`/`/stats_web` produces an informative reply ("web
pages disabled — ask the operator to configure `[stats-pages]`") and the
in-chat output is unaffected — exactly the WeatherHandler-gating philosophy
applied to a sub-feature. Keys: `enabled`, `base-url` (composed into the
reply link), `ttl-hours` (per-page deletion task delay *(superseded
2026-08-18, U11 — was "page-registry cutoff")*, unit-explicit, default 24),
`generate-command` and `delete-command` (template lists, D12),
`ratelimiter-queue` (default `"stats-pages"`).

- **`output-dir` is REMOVED** (U7): the CLI owns all storage decisions — the
  bot neither knows nor cares where pages are stored, or whether they are
  files at all. TTL is likewise the BOT's decision — the per-page deletion
  task's delay (`ttl-hours`, U11) — not a CLI argument.
- Accessed via a typed accessor `ConfigManager.getStatsPagesConfig()`
  mirroring `getStatsConfig()` (§2.7 dominant pattern); the handler only
  reads cached scalars (NG6). Validation lives at exactly ONE site
  *(moved 2026-08-18, U11 — previously
  `StatsAggregationService.initialize`, A4-style)*: **`StatsHandler`
  construction**. When `[stats-pages] enabled = true` → validate that
  `generate-command` and `delete-command` are non-empty `list[str]` entries
  and `ttl-hours` is a positive int; fail loud (construction raises → bot
  startup fails — operator error, consistent with the repo's fail-loud
  philosophy and the gated-handler `__init__` self-check precedent, §2.6).
  When `enabled = false` (default) → NO validation; `--web`/`/stats_web`
  returns the disabled reply. (This replaces the old "validate even when
  stats off" stance, whose rationale — the unconditional service
  `initialize` — is gone since the service no longer touches
  `[stats-pages]` at all.)

### D11 — CLI contract: stdin JSON in, self-contained HTML out, JSON stdout *(user-ratified; amended 2026-08-18: U7/U8 — placement and storage ownership)*

- Invocation via `asyncio.create_subprocess_exec` (no shell), payload JSON on
  **stdin** (no temp dump files), following the `_runCommand` conventions
  (§2.9) plus `stdin=PIPE`; `asyncio.wait_for(communicate(input=…), timeout=30)`
  with kill-on-timeout; stderr decoded for the log; WARNING-level failure logs.
- The bot-visible contract is only **stdin view-model JSON → stdout JSON**;
  where (and whether) the page is stored is the CLI's own business (U7). The
  **built-in** generator writes a self-contained static HTML page — UUID
  filename (`uuid.uuid4().hex + ".html"`), inline CSS, **no CDN/external
  resources, no JS, zero new runtime dependencies** (stdlib
  `argparse`/`html`/`json` only) — into its own internally-defaulted location
  (its own flag/env concern, outside bot config).
- **STDOUT contract: one JSON object `{"id": "<uuid>", "url": "…"}`**
  (user requirement: the id enables deletion; not a bare filename).
  **Flagged (unchanged): `url` is relative (the `<uuid>.html` filename) and
  the bot composes `base-url + "/" + url` for the reply link.** Rationale: the
  CLI stays a pure local tool with no knowledge of the serving web server;
  `base-url` is deployment config that would otherwise be duplicated into the
  CLI (and could drift). An absolute URL would require passing `base-url`
  into every invocation.
- In-repo generator placement *(amended 2026-08-18, U8 — user decision)*:
  **`lib/stats/stats_pages/`** with a `__main__.py`, run as
  `./venv/bin/python3 -m lib.stats.stats_pages` (the module-invocation
  precedent is `internal.max_webhook_receiver`, AGENTS.md — the *location*
  moves to `lib/` so the generator + launcher live beside the stats library,
  importable and testable like the rest of `lib/stats/`). It imports nothing
  from the bot.
- Exit codes: 0 success; nonzero any failure (with a human-readable stderr line).
  Anything non-JSON on stdout = failure (D15).
- Page content = the same view-model the in-chat reply renders from (meta +
  sections with full grouped lists; the in-chat reply truncates, the page
  does not), so grouping logic exists exactly once (bot side, D5).

### D12 — Configurable command templates: `generate-command` and `delete-command` *(rewritten 2026-08-18: U7 — replaces the mode-switched `command`)*

Both are `list[str]` templates; substitution is `str.format_map` over the
defined placeholder set (strict — an unknown placeholder is a config error and
surfaces as the D15 failure note, logged):

| Template | Placeholders | Meaning |
|---|---|---|
| `generate-command` | `{user_id}` | The calling user's id |
| | `{chat_id}` | **The chat the command was issued in** — in private scope with a chatId positional this is the TARGET chat id (its stats are what the page shows) *(amendment: follows U1 targeting)* |
| | `{platform}` | `"max"` \| `"telegram"` — `self.botProvider.value` (§2.6) |
| `delete-command` | `{page_id}` | The page id returned by `generate` (the per-page deletion task's key, U11) |

- **`{platform}` on `delete-command`: decided NO** — deletion needs only the
  id; keeping the placeholder set minimal documents that the delete contract
  is storage-agnostic (U7's "keep minimal" option).
- **`{mode}`, `{output_dir}`, `{ttl_hours}` placeholders are REMOVED
  entirely** (U7; every prior mention purged from this doc): there is no mode
  switch (two commands instead), the CLI owns storage location, and TTL is
  the bot's per-page deletion-task delay (`ttl-hours` key, D14/U11) — never
  a CLI argument.
- Default values (both point at the built-in generator, U8):

  ```toml
  generate-command = [
      "./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate",
      "--user-id={user_id}", "--chat-id={chat_id}", "--platform={platform}",
  ]
  delete-command = [
      "./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}",
  ]
  ```

- `generate` prints `{"id": "<uuid>", "url": "<uuid>.html"}` (D11);
  `delete` prints `{"deleted": 0|1}` (0 = no such page — still a success
  exit so the deletion task completes, D14). The page id is DATA, not
  configuration — it appears only as the `{page_id}` placeholder the bot
  substitutes into the scheduled deletion task's argv; no
  trailing-positional convention anymore.
- The built-in CLI's own storage flags/defaults are its internal affair
  (D11); external tools honor the same stdin/stdout JSON contracts.

### D13 — Rate limiting: per-chat, check-then-apply *(user-ratified purpose; mechanism flagged; unchanged by the 2026-08-18 round)*

- Purpose (user's words): "so users can't generate millions of stat files and eat
  all space". Only `--web`/`/stats_web` is limited — never the in-chat reply
  (both entry paths share one limit — the alias forces the same flag).
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
  concurrent `--web` calls — benign (R11). Suggested defaults: **3 pages per chat per
  hour** (`windowSeconds = 3600`, `maxRequests = 3`).

### D14 — TTL cleanup: ONE persisted one-shot delayed deletion task per page, no page tracking *(rewritten 2026-08-18: U9, then U11 — supersedes the U9 registry mechanism)*

> **Superseded by U11 (2026-08-18).** The prior U9-era body of this decision
> — the `stats_pages` page-registry DDL (migration 029), the
> `StatsPagesRepository` (`addPage` / `getExpiredPages(cutoff, limit)` /
> `deletePage`), the bounded batch (≤10) with `ORDER BY created_at ASC`,
> retry-forever semantics for failing deletes, the hourly self-rescheduling
> handler chain registered by `StatsAggregationService`, and the idempotent
> first-CRON-tick seed with its placement rules — is **removed from the live
> spec**; see U9's ratified bullet and §2.13 for the historical record. The
> user decided (2026-08-18): no page tracking at all.

- **Enum member — name retained, semantics changed**:
  `DelayedTaskFunction.STATS_PAGES_CLEANUP = "statsPagesCleanup"`
  ([types.py](../../internal/services/queue_service/types.py), §2.13) — now
  a **one-shot per-page deletion**, NOT a periodic cleanup.
- **Scheduling — on generation, exactly one task per page**: after a
  SUCCESSFUL generation (the CLI returned `{"id","url"}`, D11) and the reply
  link is composed, `StatsHandler` schedules the deletion immediately:

  ```python
  await QueueService.getInstance().addDelayedTask(
      delayedUntil=time.time() + self._pagesTtlHours * 3600,   # ttl-hours × 3600
      function=DelayedTaskFunction.STATS_PAGES_CLEANUP,
      kwargs={
          "pageId": pageId,
          # delete-command template with {page_id} substituted NOW:
          "command": [part.format_map({"page_id": pageId}) for part in self._pagesDeleteCommand],
      },
      skipDB=False,   # DB-backed → survives restarts (§2.13 restoration :309-318)
  )
  ```

  DB-persisted (`skipDB=False`) → restored by `startDelayedScheduler`
  across restarts (service.py:309-318, §2.13). The kwargs are
  **self-contained**: the delete argv is resolved at scheduling time from
  the config cached at handler construction — config frozen at load, no
  ConfigManager reload at fire time (NG6). Auto `taskId` (each task fires
  exactly once; the repo's no-upsert INSERT quirk, §2.13, is irrelevant
  here).
- **Handler ownership = StatsHandler**: `__init__` calls
  `QueueService.getInstance().registerDelayedTaskHandler(
  DelayedTaskFunction.STATS_PAGES_CLEANUP, self._dtStatsPagesCleanup)`
  ([service.py:233-266](../../internal/services/queue_service/service.py)).
  Construction is gated on `[stats] enabled` (D1), so the handler exists
  exactly when the command does — and `[stats-pages]` requires `[stats]`
  (dependency unchanged, D10). **NO seeding**: there is no periodic task to
  seed; the U9-era first-CRON-tick seed and its placement rules are moot
  (§2.13 supersession note).
- **No-handler consequence (accepted, documented — R10)**: a pending
  deletion task that fires while stats is disabled (handler not
  constructed) hits the queue-service no-handler re-delay path — re-delayed
  +60 s with an error log (service.py:385-388, §2.13). The task re-delays
  in memory for the process lifetime but the DB row is marked done on first
  firing — after restart the task is gone; orphaned page file is the accepted
  R13 outcome.
- **Handler behavior — SINGLE attempt, no retry**:

  ```python
  async def _dtStatsPagesCleanup(self, task: DelayedTask) -> None:
      pageId = task.kwargs.get("pageId")
      try:
          # run task.kwargs["command"] (the RESOLVED argv) via
          # asyncio.create_subprocess_exec / the shared launcher — same
          # conventions as generation (D11): ~30 s wait_for + kill-on-timeout,
          # DEVNULL/PIPE per docs/llm/tasks.md:489; stdout {"deleted": 0}
          # tolerated (page already gone — nothing to do).
          ...
      except Exception:
          logger.warning("stats-pages deletion failed for page %s", pageId)
      # either way the task COMPLETES (the loop marks the row done,
      # service.py:401-402) — no retry loop, no reschedule; an orphaned
      # page file is the accepted bounded risk (R13).
  ```

- **No page registry**: the bot does NOT remember generated pages (U11) —
  no table, no migration, no repository (NG1's migration-free stance
  restored). Consequence: a failed deletion is NOT retried — the page id
  exists only in the WARNING log and the original reply link; an operator
  can invoke `delete-command` manually with that page_id (the bot knows
  nothing else about storage, U7). This is the accepted trade for the
  removed tracking machinery.
- A user-facing delete/list UI remains NG5/O1.

### D15 — Failure modes: in-chat reply always wins *(user-ratified; table rows adjusted 2026-08-18: U7/U9)*

The `--web` tier is best-effort and **must never raise out of the command handler**
(whole tier wrapped in `try/except Exception` + `logger.exception`):

| Failure | Behavior |
|---|---|
| `[stats-pages]` disabled/absent | informative reply, no CLI |
| rate limit exceeded | informative reply (with retry hint), no CLI |
| nonzero exit / unparseable stdout / timeout (30 s, kill) | in-chat reply delivered + one-line "page generation failed" note |
| unknown template placeholder (`KeyError`) / missing `generate-command` or `delete-command` | same as above (config error, logged at WARNING with the key) |
| deletion-task scheduling fails after a successful generation | in-chat reply + link still delivered; page becomes UNTRACKED (orphan — outlives TTL, manual delete possible); WARNING log (R13) |
| any unexpected exception in the tier | same as above |

Query-layer errors (D4 raise-on-error) are caught one level up: the handler
renders a one-line "stats query failed" reply and returns normally.

### D16 — Chat-settings gate: `ALLOW_SHOW_STATS` *(added 2026-08-18: U6)*

- **Grounding (G1, §2.12): no generic per-command disable mechanism exists** —
  central gates are per-category, feature toggles are per-feature keys. So
  the gate is a NEW chat setting following the
  [`add-chat-setting`](../../.agents/skills/add-chat-setting/SKILL.md)
  four-site pattern:
  1. **Enum**: `ALLOW_SHOW_STATS = "allow-show-stats"` in the "Allowing
     different commands in chat" section of `ChatSettingsKey`
     ([chat_settings.py:388-396](../../internal/bot/models/chat_settings.py) —
     beside `ALLOW_TOOLS_COMMANDS`/`ALLOW_SANDBOX`), with a docstring.
     Naming: the user's spirit, and it matches both conventions — UPPER_CASE
     Python name ↔ kebab-case value, and the `allow-<thing>` family
     (`allow-sandbox`, `allow-tools-commands`, `allow-mention`). (A shorter
     `ALLOW_STATS` was considered and rejected: "show" names the user-visible
     action the admin is toggling.)
  2. **`_chatSettingsInfo` entry**: `{"type": ChatSettingsType.BOOL, "short":
     "Показывать статистику чата", "long": "Разрешить команду /stats
     (и /stats_web) в этом чате", "page": ChatSettingsPage.STANDARD}` —
     STANDARD = FREE-tier page, the precedent of the other basic allow-flags
     (`ALLOW_MENTION`, chat_settings.py:963-968).
  3. **Default**: `allow-show-stats = true` (default ENABLED — stats show)
     under `[bot.defaults]` in
     [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml)
     (the `allow-sandbox = false` line :90 is the placement precedent).
  4. **Consumer**: `StatsHandler` — at command entry (both aliases), BEFORE
     any query or scope work:

      ```python
      if ensuredMessage.recipient.chatType != ChatType.PRIVATE:   # group/channel only (see below)
          chatSettings = await self.getChatSettings(ensuredMessage.recipient.id)
          if not chatSettings[ChatSettingsKey.ALLOW_SHOW_STATS].toBool():
              await self.sendMessage(ensuredMessage, messageText=INFORMATIVE_TEXT, …)
              return
      ```

     When disabled: informative reply, **no queries**. Handler-layer read via
     `.toBool()` (never tuple indexing); writes (if ever) via
     `setChatSetting(..., user=MessageSender)`.
- **Scope of the setting**: group and channel chats — the admin's moderation
  control for THAT chat. **In private chats the setting is NOT consulted**
  (decided): a private `/stats` is the user inspecting their own operational
  data, and the private chat's only "admin" is the user themselves — there is
  no moderation surface. (Judgment call, flagged: the alternative — honoring
  the user's own private-chat setting — adds a self-negation toggle with no
  moderation value.)
- **This is NOT the LLM tool-gate** (the add-llm-tool D3 chat-time gating
  rule): no `ToolName`, no `useTools` interplay — a plain chat setting read
  by a command handler, exactly the `ALLOW_SANDBOX` pattern
  ([sandbox.py:285](../../internal/bot/common/handlers/sandbox.py)).
- Who can flip it: the existing settings machinery — `/set`/`/unset` (admin)
  or the `/settings` wizard, subject to `ADMIN_CAN_CHANGE_SETTINGS`
  (§2.12); bot owners bypass.
- Stacks with the coarse category gate (D1): `category=TOOLS` still requires
  `ALLOW_TOOLS_COMMANDS`-or-bot-owner centrally; `ALLOW_SHOW_STATS` is the
  dedicated fine-grained opt-out on top.

---

## 4. Wiring diagram

```
User: /stats [help|chatId] [--period=…] [--section=…] [--user=<id>] [--web]   (or /stats_web)
         │
         ▼
StatsHandler.statsCommand                    internal/bot/common/handlers/stats.py [NEW]
  ├─ __init__: [stats-pages] validation when enabled (D10/U11) + register
  │     STATS_PAGES_CLEANUP handler (D14/U11) — exists exactly when [stats] enabled
  ├─ ALLOW_SHOW_STATS gate (D16): group/channel only; off → informative reply, STOP
  ├─ parse args (D2, argparse-style — NEW pattern; usage reply on any bad input)
  ├─ chat type: ensuredMessage.recipient.chatType (D3/§2.6 — never chatId sign)
  ├─ resolve scope (D3): group/channel → {chatId}; private → {chatId} default,
  │     positional chatId → membership check against getUserChats(userId)
  │     [base.py:1322; + messages_count per §2.5 addendum]
  ├─ for each section eventType in {message, command, llm_tool_call, llm_request, stt_request}:
  │     StatsAggregationService.getInstance().getQueryStorage(eventType)    [service.py, NEW accessor]
  │           └─ _statsStorages registry (populated by main.py:96-131 factory calls)
  │     await storage.query(eventType=…, periodType=…, periodStartFrom/To=…)   [ABC, NEW]
  │           └─ DatabaseStatsStorage.query → provider.executeFetchAll (SQL: event_type+period only)
  ├─ StatsAnalyzer (lib/stats/analysis.py [NEW]): consumer-scope filter → group/topN/Σ/Σ÷Σ
  ├─ username join via chat_users / cache.getChatUser (D8)
  ├─ render reply (D6: group → messages-only; private → messages + chat list; bounded)
  │     → sendMessage                                              [base.py:568]
  └─ if --web or /stats_web:  [stats-pages] gate → rate-limit pre-check (D13)
        → launcher (lib/stats/stats_pages/launcher.py [NEW])
        │   asyncio.create_subprocess_exec(*format_map(generate-command,
        │     {user_id}, {chat_id}, {platform}=self.botProvider.value), stdin=PIPE)
        │   payload = view-model JSON on stdin
        │   ◀ stdout {"id": "<uuid>", "url": "<uuid>.html"}
        ├─ reply: base-url + "/" + url          (failures → D15 table)
        └─ on success: ONE delayed task (D14/U11) —
              addDelayedTask(now + ttl-hours×3600, STATS_PAGES_CLEANUP,
                kwargs={"pageId": id, "command": delete-command argv
                        with {page_id} substituted}, skipDB=False)

QueueService delayed scheduler                                    [service.py:268-320]
  ├─ CRON_JOB tick (existing, skipDB=True) → StatsAggregationService._dtCronJob
  │     (UNCHANGED by U11 — no seed step; the service never touches [stats-pages])
  └─ STATS_PAGES_CLEANUP task [one-shot PER PAGE, DB-PERSISTED, restored on restart :309-318]
        → StatsHandler._dtStatsPagesCleanup(task)   [registered in handler __init__, D14/U11]
              ├─ run task.kwargs["command"] (resolved argv) via the launcher /
              │   asyncio.create_subprocess_exec (~30 s timeout, kill; {"deleted": 0} tolerated)
              └─ failure → WARNING log (page id); task completes — SINGLE attempt,
                  no retry, no reschedule (orphaned page = accepted bounded risk, R13);
                  no handler registered (stats disabled) → +60 s re-delay, task waits (R10)

lib/stats/stats_pages/ [NEW package, ./venv/bin/python3 -m lib.stats.stats_pages]
  ├─ __main__.py   argparse: generate | delete <page_id> (no cleanup verb — TTL is the bot's job)
  ├─ generator.py  stdin JSON view-model → self-contained HTML (uuid4 name, inline CSS)
  └─ launcher.py   the one subprocess invocation helper (timeout 30 s, kill, JSON stdout parse)
```

Read path over `stat_aggregates` (provider, `readonly=True`) is unchanged;
`stat_events` untouched. Schema delta: NONE (U11 removed the page registry —
no migration, no new table); the only data-model change is the additive
`ChatInfoDict.messages_count` field (existing column, no DDL).

---

## 5. Configuration changes

New file [`configs/00-defaults/stats-pages.toml`](../../configs/00-defaults) (created;
default-off so merged behavior is unchanged):

```toml
[stats-pages]
enabled = false
# base-url = "https://example.com/stats"    # REQUIRED when enabled; composed into the reply link
ttl-hours = 24                              # per-page deletion task delay (D14/U11) — the BOT's TTL decision
ratelimiter-queue = "stats-pages"
generate-command = [                        # D12; defaults point at the built-in generator (U8)
    "./venv/bin/python3", "-m", "lib.stats.stats_pages", "generate",
    "--user-id={user_id}", "--chat-id={chat_id}", "--platform={platform}",
]
delete-command = [
    "./venv/bin/python3", "-m", "lib.stats.stats_pages", "delete", "{page_id}",
]
```

No `output-dir` key exists (U7): the CLI owns all storage decisions.

Chat-setting default (U6/D16) — diff to
[`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml),
`[bot.defaults]` section (kebab-case key matching the enum value):

```toml
 [bot.defaults]
 # … existing …
+allow-show-stats = true
```

Diff to [`configs/00-defaults/00-config.toml`](../../configs/00-defaults/00-config.toml)
(new limiter + queue binding, appended after `stt-global` / into the queues
table — **unchanged by this amendment round**):

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
`base-url`, empty `generate-command`/`delete-command` when enabled,
non-positive-int `ttl-hours`) fail loudly at the single validation site —
`StatsHandler` construction (D10/U11; construction raises → bot startup
fails). No validation when `enabled = false` (default).

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

### Phase 2 — `/stats` command: registration, grammar, scoping, defaults, gate, drill-downs *(amended 2026-08-18: U1-U6)*

Sized ~60 steps: one new lib file, one new handler file, four edited production
files (manager, chat_settings ×2 sites, bot-defaults TOML, chat_users repo +
models), tests. (The four-site and `messages_count` additions are one-line
sites each — the ceiling holds.) **Split contingency (pre-declared):** if the
phase overflows the budget, split **P2a** (`lib/stats/analysis.py` + the
`getUserChats`/`messages_count` extension + their tests) / **P2b** (handler +
registration + chat-setting + handler tests).

**Files:**

- `lib/stats/analysis.py` — **new**; `StatsAnalyzer` (D5).
- `internal/bot/common/handlers/stats.py` — **new**; `StatsHandler`
  (D1/D2/D3/D6/D7/D8/D9/D16): `@commandHandlerV2(commands=("stats",
  "stats_web"))` registration, `__init__` stats-enabled self-check,
  argparse-style parser, `ALLOW_SHOW_STATS` gate, chat-type dispatch on
  `recipient.chatType`, scope resolution, per-section queries via
  `getQueryStorage`, view-model builder, renderers (group default / private
  default + chat list / section / drill-downs), username join.
- [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py) —
  conditional registration block beside sandbox/chat-search (D1):
  `if self.configManager.getStatsConfig().get("enabled", False): self.handlers.append((StatsHandler(...), HandlerParallelism.PARALLEL))`.
- `internal/bot/common/handlers/__init__.py` — export (follow the WeatherHandler
  export pattern).
- [`internal/bot/models/chat_settings.py`](../../internal/bot/models/chat_settings.py) —
  U6 sites 1+2: `ALLOW_SHOW_STATS` enum member + `_chatSettingsInfo` entry
  (D16).
- [`configs/00-defaults/bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml) —
  U6 site 3: `allow-show-stats = true` under `[bot.defaults]` (D16).
- [`internal/database/repositories/chat_users.py`](../../internal/database/repositories/chat_users.py)
  + [`internal/database/models.py`](../../internal/database/models.py) — U1
  ground: add `cu.messages_count` to the `getUserChats` SELECT and
  `messages_count: int` to `ChatInfoDict` (§2.5 addendum).

**Interim `--web` behavior (pre-Phase-3):** until Phase 3 lands, `--web` /
`/stats_web` replies "page generation is disabled" (informative, not an
error), decided by an ad-hoc `configManager.get("stats-pages", {})` read
(§2.7 ad-hoc precedent — no `getStatsPagesConfig()` dependency; the accessor
arrives in Phase 3a), so P2 alias/grammar tests have a defined expectation
for the web path.

**Tests:**

- `tests/lib/stats/test_analysis.py` — `StatsAnalyzer` matrix: consumer-scope
  filter excludes `__global__`; groupSum ordering; topN; Σvalue/Σcount average
  (incl. 0-count); three-bucket `sent` grouping (True/False/absent).
- `tests/bot/common/handlers/test_stats.py` — real `EnsuredMessage`
  construction (conftest pattern); mocked storages returning canned
  `StatsAggregateDict` rows:
  - grammar matrix (D2): `--period`/`--section`/`--user`/`--web` in both
    `--opt=value` and `--opt value` forms; negative chatId positional
    (`-100123` parsed as positional, not option); unknown option / bad
    value / second positional / `help`+args → usage; chatId in group →
    usage;
  - defaults (D6/U1): group → messages-only reply; private → messages +
    chat list with `messages_count` (mock `getUserChats`);
  - scope (D3/U5): chat type taken from `recipient.chatType` (patch nothing —
    construct recipients of each type); positional chatId membership
    (in-scope ok / out-of-scope informative error);
  - `--user=<id>` excludes `llm_request`;
  - period→bucket mapping (1d→hourly, 7d/30d→daily, all→total+no range);
  - chat-setting gate (D16): `ALLOW_SHOW_STATS = false` (complete-dict
    `chatSettings` mock) → informative reply, **no storage queries**;
    default `true` → normal reply; private chat → gate not consulted;
  - alias (U4): `/stats_web` ≡ `/stats --web` (same web path, forced);
  - username fallback to raw id;
  - **stats-off → handler construction raises + manager registers nothing**
    (registration test at the manager level, mirror the WeatherHandler
    gating test if one exists).
- `tests/database/repositories/test_chat_users.py` (extend) — `getUserChats`
  returns `messages_count` per chat (seed two chats with different counts).
- Singleton hygiene: reset `StatsAggregationService._instance` where manipulated.

**Docs:** [`docs/llm/handlers.md`](../llm/handlers.md) (new handler + alias +
gating + `ALLOW_SHOW_STATS`),
[`docs/llm/libraries.md`](../llm/libraries.md) §9 (`StatsAnalyzer`),
[`docs/llm/configuration.md`](../llm/configuration.md) (chat-setting default
note), [`docs/llm/index.md`](../llm/index.md) §4 handler-list entry.
**CHANGELOG:** `Added` — `/stats` (+`/stats_web`) command (argparse-style
period/section/user/chat drill-downs, scope-derived visibility) gated on
`[stats] enabled`, with per-chat `allow-show-stats` setting.

**Gate 2:** `make format lint`; `make test`; `make check-docs`.

### Phase 3a — Web tier: CLI generator + config *(amended 2026-08-18: U7/U8/U9/U11 — U11 removed the migration + repository deliverables)*

Sized ~25 steps: new lib package (3 files), 2 config files, 1 edited
internal file, tests. (The 3a/3b split is **unconditional** — combined the
two sub-phases span 10+ files, so each carries its own budget and the
~60-step-per-invocation ceiling holds by construction. The pre-declared
3a-split contingency — migration + repository vs generator — is gone with
the U11 removals; there is no migration-vs-generator split left.)

**Files:**

- `lib/stats/stats_pages/__init__.py`, `__main__.py`, `generator.py` —
  **new** (D11/D12, U8): argparse verbs `generate` / `delete <page_id>`
  (no cleanup verb — TTL is the bot's per-page deletion task, U11);
  self-contained HTML renderer (inline CSS, `html.escape` everything, UTC
  footer with meta incl. user/chat/platform ids); storage location is the
  CLI's own internal default/flag (no bot-config coupling).
- [`configs/00-defaults/stats-pages.toml`](../../configs/00-defaults) — **new**
  (§5); [`configs/00-defaults/00-config.toml`](../../configs/00-defaults/00-config.toml) —
  limiter + queue binding (§5).
- [`internal/config/manager.py`](../../internal/config/manager.py) —
  `getStatsPagesConfig()`.

**Tests:**

- `tests/lib/stats/test_stats_pages_generator.py` — golden-ish: given a fixed
  view-model JSON → HTML contains escaped values, no external URLs
  (`http`/`https` absent outside the footer meta), inline `<style>`, UTC
  label; uuid filename shape.
- `tests/lib/stats/test_stats_pages_cli.py` — subprocess-in-process (import
  `__main__` functions directly): generate writes file + stdout JSON; delete
  removes by id and prints `{"deleted": 0|1}` (0 for unknown id, exit 0);
  nonzero exit on bad stdin JSON.

**Docs:** [`docs/llm/configuration.md`](../llm/configuration.md)
(`[stats-pages]` table + ratelimiter additions),
[`docs/llm/libraries.md`](../llm/libraries.md) (`lib/stats/stats_pages/`),
[`docs/llm/index.md`](../llm/index.md) (lib map entry).
**CHANGELOG:** none yet — fold into the Phase 3b entry (single user-visible
feature).

**Gate 3a:** `make format lint`; `make test`; `make check-docs`.

### Phase 3b — Web tier: bot integration — invocation, rate limit, per-page deletion task, failure modes *(amended 2026-08-18: U9/U11 — U11 replaced the registry + periodic cleanup with the one-shot per-page task)*

Sized ~30 steps: 1 new lib file, 2 edited files (handler, queue types),
tests.

**Files:**

- `lib/stats/stats_pages/launcher.py` — **new** (D11): the one subprocess
  invocation helper (exec, stdin payload, `wait_for` 30 s, kill, stdout JSON
  parse + `{"id","url"}` / `{"deleted",…}` validation) — pure, config-free
  (callers pass the template + substitutions).
- `internal/bot/common/handlers/stats.py` —
  the `--web`/`/stats_web` tier: config gate + `[stats-pages]` validation at
  construction (D10/U11), rate-limit pre-check + apply (D13), payload build
  (view-model JSON), launcher call with `generate-command` substitutions
  (`{platform}` = `self.botProvider.value`), link composition (`base-url +
  "/" + url`), and on success ONE persisted deletion task with the RESOLVED
  delete argv in kwargs (D14/U11); `registerDelayedTaskHandler(
  STATS_PAGES_CLEANUP, self._dtStatsPagesCleanup)` + `_dtStatsPagesCleanup`
  in the same handler; D15 failure table.
- [`internal/services/queue_service/types.py`](../../internal/services/queue_service/types.py) —
  `STATS_PAGES_CLEANUP = "statsPagesCleanup"` enum member.

**Tests:**

- `tests/lib/stats/test_stats_pages_launcher.py` — patch
  `lib.stats.stats_pages.launcher.asyncio.create_subprocess_exec`
  ([tests/services/proxy/test_lifecycle.py:69](../../tests/services/proxy/test_lifecycle.py)
  pattern): timeout kill; nonzero exit; unparseable stdout; happy path returns
  `{"id","url"}`.
- `tests/bot/common/handlers/test_stats.py` — extend: disabled
  `[stats-pages]` → informative reply, no subprocess; malformed
  `[stats-pages]` with `enabled = true` (empty command template, bad
  `ttl-hours`) → handler construction raises; rate-limit refusal (mock
  `getStats` full window) → reply, no subprocess; success → link composed +
  ONE deletion task scheduled with the RESOLVED delete argv in kwargs
  (`skipDB=False` asserted); deletion-task scheduling failure → link still
  delivered (D15 row); failure modes per D15 (in-chat reply still sent);
  `/stats_web` alias shares the rate limit.
- `tests/bot/common/handlers/test_stats.py` — deletion-task handler matrix
  (D14/§2.13): handler registered in `__init__`; runs `task.kwargs["command"]`
  through the launcher; `{"deleted": 0}` tolerated; failure → WARNING + task
  completes (no second `addDelayedTask`, no retry); task is persisted
  (`skipDB=False`) and restored across restarts.

**Docs:** [`docs/llm/handlers.md`](../llm/handlers.md) (web tier +
per-page deletion task in `StatsHandler`),
[`docs/llm/architecture.md`](../llm/architecture.md) (display tier
paragraph), this design doc's status line when it lands.
**CHANGELOG:** `Added` — optional `--web`/`/stats_web` web-page generation
with `[stats-pages]` config (two command templates), per-chat rate limit,
per-page TTL deletion via a persisted one-shot delayed task.

**Gate 3b:** `make format lint`; `make test`; `make check-docs`; manual smoke
(local, operator-optional): enable `[stats]` + `[stats-pages]`, `/stats
--period=7d --web`, open the generated HTML offline (no network) and verify
the link resolves; forge the scheduled deletion task's `delayedUntil` into
the past (or temporarily lower `ttl-hours`) and watch the task invoke
`delete-command` once.

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
| Chat-setting gate *(added 2026-08-18)* | `allow-show-stats = false` → informative reply and ZERO storage queries; private chat ignores the gate | Phase 2 |
| Alias *(added 2026-08-18)* | `/stats_web` ≡ `/stats --web` — same code path, web forced; one `/help` entry | Phase 2 |
| Grammar *(amended 2026-08-18)* | argparse matrix: both `--opt=value`/`--opt value`, negative chatId positional, all bad inputs → usage | Phase 2 |
| Scope correctness | group/private/chat-drill authorization tests (chat type from `recipient.chatType`) | Phase 2 |
| Bounded reply | default/section render tests assert length < 3500 chars | Phase 2 |
| Stats-off silence | entire feature (command + pages) inert when `[stats] enabled = false` | every phase |
| CLI contract | generate/delete + stdout JSON + failure exits | Phase 3 |
| Subprocess safety | timeout-kill, nonzero-exit, unparseable-stdout tests | Phase 3 |
| Rate limit | refusal path never invokes the CLI | Phase 3 |
| Deletion task *(amended 2026-08-18, U11)* | ONE task scheduled on generation with the RESOLVED delete argv in kwargs (`skipDB=False`); single attempt — failure → WARNING, no retry; `{"deleted": 0}` tolerated | Phase 3 |
| Offline page | generated HTML contains no external resource references | Phase 3 |

No live/operator smoke gate is mandatory beyond the optional Phase 3 local smoke
(default-off feature; same stance as the two prior stats designs).

---

## 8. Risk register

| # | Risk | Likelihood | Impact | Mitigation | Rollback |
|---|---|---|---|---|---|
| R1 | **Query cost / cardinality** — `stat_aggregates` grows with distinct label combos × periods; a scope query scans all label buckets of the window | Med | Med | PK prefix `(event_type, period_start)` serves the SQL predicate; `limit=10000` cap + explicit truncation line (D5); SUM-only buckets stay small vs `stat_events` (aggregation-v1 NG3 analysis); revisit retention per its §9 Q2 | Raise nothing — read-only; lower `limit` |
| R2 | **Double counting via `__global__` rows** — naively summing a window counts every event twice | Med | High | The D3 consumer-scope filter structurally excludes `__global__`; pinned by an explicit analysis test (Gate: no-double-count) | n/a (test-locked) |
| R3 | **Per-chat LLM undercount** (§2.3 exceptions: embeddings, background calls, condensing land in `__global__`) | Certain (today) | Low | Documented in `help`/reply honesty ("LLM counts cover interactive generation"); fix path is a small follow-up (O2), not a display-layer concern | n/a |
| R4 | **Backfill/live label split** — direction breakdown misread as undercount | Low | Low | Three-bucket rendering (users/bot/history) per §2.4/D6 | n/a |
| R5 | **Reply too long → mechanical split breaks MarkdownV2** | Low | Low | Bounded reply (< 3500 chars, Gate); top-3 lists; drill-downs bounded to top-10; chat list truncation with "and K more" | Shorten reply |
| R6 | **Disk exhaustion via page generation** | Med | Med | Per-chat rate limit (3/h default) + UUID names (no overwrite) + per-page TTL deletion via persisted one-shot tasks (D14/U11) | Disable `[stats-pages]`; run `delete-command` manually per page_id |
| R7 | **CLI hangs / misbehaves** | Low | Med | 30 s `wait_for` + kill (§2.9 conventions); JSON-validated stdout; D15 failure table; external commands are operator-supplied (WARNING not ERROR, proxy precedent) | `--web` off / fix the command templates |
| R8 | **Command-template misconfiguration** *(reworked 2026-08-18 — no more output-dir)*: missing/malformed `generate-command`/`delete-command`, wrong bin path | Med | Low | Construction-time validation when enabled (fail loudly — `StatsHandler.__init__`, D10/U11); strict `format_map` → KeyError → D15 note + WARNING log naming the key | Fix the templates |
| R9 | **Unguessable-URL-only "auth"** — link sharing exposes scope aggregates | — (ratified) | Low | Ratified for non-sensitive aggregates (NG4); UUIDv4 hex; TTL; scope already bounds what is visible | Lower ttl-hours |
| R10 | **Pending deletion task while stats disabled** — handler not constructed → the task hits the no-handler re-delay path (+60 s, error log, §2.13) and waits; pages generated before disabling outlive their TTL until re-enable | Low | Low | Accepted & documented (D14/U11): the waiting task costs ~nothing and fires once stats is re-enabled and the handler registers again; meanwhile the operator can invoke `delete-command` manually per page_id (from the reply link / logs) | Re-enable stats, or delete pages manually |
| R11 | **Check-then-apply rate-limit race** over-admits a few concurrent `--web` | Low | Low | Single event loop bounds interleaving; consequence ≤ a few extra files per window (D13) | n/a |
| R12 | **Template placeholder drift** (unknown placeholder in a custom template) | Med | Low | Strict `format_map` → KeyError → D15 note + WARNING log naming the command | Fix the templates |
| R13 | **Orphaned page on failed deletion** — the one-shot task's delete-command call fails (external tool broken/removed); SINGLE attempt, no retry | Low | Low | WARNING log naming the page id; **accepted** (U11): the page just outlives TTL — no data risk, only storage | Fix or remove the external tool; manual delete |
| R14 | **`request_count` counts attempts, not logical requests** (fallback loop, §2.2) | — (documented) | Low | Rendered as "requests (attempts)" in help/footnote; not fixable display-side | n/a |

**Rollback principle:** the whole display tier is gated on `[stats] enabled`
(the command, the chat-setting gate and page generation disappear with one
flag; the read API is inert code when nothing calls it; pending per-page
deletion tasks either fire once through the registered handler or wait on
the no-handler re-delay path until stats is re-enabled). Each phase is
independently revertible via git; there is NO migration to roll back (U11
removed the page registry before implementation); the
`ChatInfoDict.messages_count` extension is additive and inert if unused.

---

## 9. Open questions

1. **O1 — Bot-side delete/list UI for pages** (NG5, reworded 2026-08-18):
   the CLI `delete` verb exists and the bot schedules one deletion task per
   generated page (D12/D14/U11). If page litter becomes a user complaint, a
   follow-up can add a user-facing delete verb — noting that the bot now
   deliberately keeps NO page list (U11), so such a UI implies re-introducing
   lightweight tracking; page ids live only in reply links and WARNING logs.
   Verification plan: none needed now.
2. **O2 — Per-user `llm_request` attribution** (R3): thread `consumerId`
   through `LLMService.generateEmbedding` ([service.py:1499](../../internal/services/llm/service.py))
   and the condensing call (:1239), and optionally real chat ids into the two
   background callers; separately consider a `user_id` label for interactive
   generation (would change label vocabulary → new buckets only going forward —
   same freeze caveat as stats-collecting-v1 Caveats). Follow-up design/task, not
   a blocker; display layer needs no change either way.
3. **Aggregates retention**: still open repo-wide (aggregation-v1 §9 Q2); with a
   query API now landing, row counts become observable — revisit after real-world
   cardinality data exists.
4. **i18n of `/stats` output**: v1 follows repo precedent (Russian replies). If a
   localization pass ever happens repo-wide, the reply strings ride along; no
   design change.

---

## 10. Documentation impact (when implementation lands)

Load the [`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md)
skill and update:

- [`docs/llm/libraries.md`](../llm/libraries.md) §9 — `StatsStorage.query()`,
  `StatsAggregateDict` (lib/stats/types.py), `StatsAnalyzer`, and the
  `lib/stats/stats_pages/` package (generator + launcher, module-invocable).
- [`docs/llm/services.md`](../llm/services.md) — `StatsAggregationService`:
  `getQueryStorage` accessor (Phase 1); the service no longer touches
  `[stats-pages]` in any way (U11).
- [`docs/llm/handlers.md`](../llm/handlers.md) — `StatsHandler` (`stats.py`):
  command grammar (argparse-style), `/stats_web` alias, scoping via
  `recipient.chatType`, conditional registration on `[stats] enabled`, the
  `ALLOW_SHOW_STATS` gate, the `--web` tier + per-page STATS_PAGES_CLEANUP
  deletion task (Phase 3, U11).
- [`docs/llm/configuration.md`](../llm/configuration.md) — `[stats-pages]`
  table (`generate-command`/`delete-command` templates and their placeholder
  sets; NO output-dir); `[ratelimiter]` additions; the `allow-show-stats`
  chat-setting default in `bot-defaults.toml`; note that `[stats]` is
  unchanged.
- **Chat-setting four-site sync (U6, per the
  [`add-chat-setting`](../../.agents/skills/add-chat-setting/SKILL.md)
  skill)**: enum + `_chatSettingsInfo` (code) land with Phase 2; verify
  `/settings` shows the entry with the default populated, and keep
  `docs/llm/tasks.md` §4.1's example list current if the setting illustrates
  a new category (it does not — routine BOOL flag).
- [`docs/llm/architecture.md`](../llm/architecture.md) — stats pipeline section:
  add the read/display tier (query API → /stats → optional page generation →
  per-page one-shot TTL deletion task, U11).
- [`docs/llm/index.md`](../llm/index.md) — §4 map: `lib/stats/stats_pages/`
  in the lib tree; handler-list entry for `/stats`(+`/stats_web`).
- `CHANGELOG.md` — Phase 2 and Phase 3 `Added` entries per
  [`docs/llm/changelog.md`](../llm/changelog.md) rules (this amended PROPOSED
  doc itself gets no entry — doc-only).
- The `ChatInfoDict.messages_count` extension is a TypedDict change only (no
  DDL — the column exists); mention it in the Phase 2 PR description so
  reviewers don't hunt for a migration.

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
  [`chat_users.py`](../../internal/database/repositories/chat_users.py):271-327,
  [`models.py`](../../internal/database/models.py):213-231 (`ChatInfoDict`).
- Command machinery: [`command_handlers.py`](../../internal/bot/models/command_handlers.py):27-146,
  args precedent [`chat_search.py`](../../internal/bot/common/handlers/chat_search.py):1074-1141,
  gating [`manager.py`](../../internal/bot/common/handlers/manager.py):565-627 +
  [`weather.py`](../../internal/bot/common/handlers/weather.py):75-78.
- Alias mechanism (2026-08-18 grounding): [`divination.py`](../../internal/bot/common/handlers/divination.py):284-329,
  dispatch [`manager.py`](../../internal/bot/common/handlers/manager.py):877-880/1037-1039,
  help rendering [`help_command.py`](../../internal/bot/common/handlers/help_command.py):212.
- Chat settings (2026-08-18 grounding): [`chat_settings.py`](../../internal/bot/models/chat_settings.py),
  consumer precedent [`sandbox.py`](../../internal/bot/common/handlers/sandbox.py):285,
  wizard enforcement [`configure.py`](../../internal/bot/common/handlers/configure.py):203,
  defaults [`bot-defaults.toml`](../../configs/00-defaults/bot-defaults.toml).
- Chat type + platform (2026-08-18 grounding): [`ensured_message.py`](../../internal/bot/models/ensured_message.py):57-159,
  [`enums.py`](../../internal/bot/models/enums.py):8-20.
- Delayed-task mechanism (2026-08-18 grounding): [`internal/services/queue_service/service.py`](../../internal/services/queue_service/service.py),
  [`types.py`](../../internal/services/queue_service/types.py),
  [`internal/database/repositories/delayed_tasks.py`](../../internal/database/repositories/delayed_tasks.py).
- Rate limiting: [`lib/rate_limiter/manager.py`](../../lib/rate_limiter/manager.py),
  [`lib/rate_limiter/sliding_window.py`](../../lib/rate_limiter/sliding_window.py),
  consumer [`stt/service.py`](../../internal/services/stt/service.py):298-301,
  config [`00-config.toml`](../../configs/00-defaults/00-config.toml):68-102.
- Subprocess conventions: [`internal/services/proxy/lifecycle.py`](../../internal/services/proxy/lifecycle.py):105-150;
  rendering: [`lib/markdown/parser.py`](../../lib/markdown/parser.py):589-618,
  [`internal/bot/common/bot.py`](../../internal/bot/common/bot.py):654-669/969-978.
- SQL portability: [`docs/sql-portability-guide.md`](../sql-portability-guide.md).
- Skills: [`add-handler`](../../.agents/skills/add-handler/SKILL.md),
  [`add-chat-setting`](../../.agents/skills/add-chat-setting/SKILL.md),
  [`run-quality-gates`](../../.agents/skills/run-quality-gates/SKILL.md),
  [`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md).
  *(The `add-database-migration` skill reference was pruned 2026-08-18, U11 —
  the design has no migration anymore; all registry-era citations above are
  historical.)*
