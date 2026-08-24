# Design: Statistics aggregation v1 — periodic trigger and retention

**Date**: 2026-08-17
**Status**: **IMPLEMENTED — both phases committed.** Phase 1 implemented (commit `3c3c156a`); Phase 2 implemented (commit `549d0a81` + follow-up fix); amendment A4 (config cached at `initialize`, fail-loud parse, `aggregation-batch-limit`) shipped. Post-review remediation 2026-08-21 — see the amendments block below.
**Owner**: TBD
**Branch**: `lib-stat-improvement`

## Amendments (2026-08-17, user-ratified)

Four user-ratified design changes supersede parts of the original Phase-2 decisions;
the affected D-decisions are reworked in place and marked *(amended)*. Phase 1 is
untouched except the purge-cutoff sentence (A2). All mechanics cited below were
verified against source on 2026-08-17.

- **A1 — Trigger: ride the shared CRON_JOB tick, no dedicated task.** The
  `DelayedTaskFunction.STATS_AGGREGATION` self-rescheduling task (old D1/D6/D10) is
  dropped entirely — no new enum member, no seeding. `StatsAggregationService`
  registers `registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB,
  self._dtCronJob)` in `initialize`, and the handler gates on elapsed time
  in-memory (`self._lastRunTime: float = 0.0`; per tick: skip if
  `time.time() - _lastRunTime < intervalSeconds`). CRON_JOB is a shared 60-second
  tick owned by QueueService (`_cronJobHandler` reschedules `time.time() + 60`,
  service.py:190-201, seeded at service.py:302-307); handler lists are append-based
  (service.py:233-266) and three consumers already coexist on it. First tick after
  startup is an immediate catch-up (`_lastRunTime = 0.0`) — the ratified "first run
  is catch-up" property without seeding. The old reschedule-first machinery and its
  chain-death risk are obsolete: the tick survives handler exceptions structurally
  (per-handler try/except, service.py:390-399).
- **A2 — Purge cutoff day-truncation.**
  `cutoff = truncateToDay(getCurrentTimestamp() - timedelta(days=retentionDays))` —
  the UTC midnight of N days ago, reusing the Phase-1 shared helper
  (sql_storage.py:471). An event is deleted only once it is beyond N **whole**
  days; hours/minutes/seconds of age within the boundary day do not count. The
  strict-`<` boundary is now midnight: a row created during the boundary day
  survives.
- **A3 — Storage factory + registry.**
  `StatsAggregationService.createStatsStorage(eventType: str, dataSource: str | None
  = None) -> StatsStorage` is the single construction seam: it reads `[stats]
  enabled` itself — disabled returns an **unregistered** `NullStatsStorage`; enabled
  constructs `DatabaseStatsStorage` (today's type; the seam exists for future
  non-DB backends) and registers it in `self._statsStorages: Dict[str,
  StatsStorage]` keyed by eventType, returning it. main.py's five per-event
  constructions become five `createStatsStorage(...)` calls at the same sites; the
  returned storages flow to the existing consumers exactly as today. The static
  storages list and the `initialize(statsStorages=…)` parameter disappear.
   Cyclic-import safety: `internal/services/stats` importing
   `lib/stats` is fine (main.py already imports both; services
   import `internal.database` elsewhere, e.g. queue_service/service.py:36).
- **A4 — Config cached at initialize, fail-loudly on malformed (2026-08-17).**
  `StatsAggregationService.initialize(configManager, database)` now reads `[stats]`
  configuration once at startup, parsing and caching all values as typed scalars
  (`self._statsEnabled`, `self._intervalSeconds`, `self._retentionDays`,
  `self._batchLimit`). Config parsing MUST happen BEFORE setting
  `self._initialized = True` and BEFORE registering the CRON_JOB handler — a failed
  initialize leaves the service retryable (config fixed → initialize again succeeds).
  On malformed values (TypeError/ValueError from `int()` parse), `initialize` RAISES
  `ValueError` with a clear error message naming the offending key (chained `from e`);
  startup fails loudly, forcing the user to fix the config. This replaces the
  per-cycle guarded-parse block in `_dtCronJob` — there is no per-cycle config read
  anymore; the handler uses the cached values directly. Summary logging uses
  registry keys as labels (`eventType` keys from `_statsStorages.items()`), removing
  the double derivation and `storageLabels` precompute dict.
  New config key `aggregation-batch-limit` (default 1000, clamp >= 1) bounds the drain
  batch size; the drain loop passes `limit=self._batchLimit` to `aggregate()`, and
  `MAX_AGGREGATION_ROUNDS` bounds a cycle at `MAX_AGGREGATION_ROUNDS × batch-limit`
  events per storage.

## Amendments (2026-08-21, post-review remediation)

Post-implementation remediation after review of the shipped phases; all facts
verified against source on 2026-08-21.

- **Retention purge runs once per distinct datasource** — the purge predicate is
  type-agnostic and runs per datasource, not per storage; pinned by tests.
  (Supersedes the per-storage purge wording in D2/D3/D8.)
  *(Corrected 2026-08-21 later the same day, commit aee2463b: per-storage
  event_type-scoped purge restored; the datasource-dedupe mechanism was
  removed.)*
- **The purge DELETE is batched** — double-nested subquery + `applyPagination`,
  safe against MySQL ERROR 1093/1235. (Supersedes D8's "no LIMIT batching"
  unbounded-DELETE stance and closes §9 Q4's open question.)
- **The cron handler iterates a registry snapshot** (a `list(...)` copy of
  `_statsStorages`) — the dict-mutation race is fixed and regression-tested.
- **`_parseIntKey` strictly validates** — bools, floats, and non-integral strings
  are rejected with an error naming the offending key; integral strings are
  accepted (so `${VAR}` env substitution keeps working).
- **`query()` supports limit+offset paging** — `offset` is forwarded through
  `applyPagination`.
- **`main.py` registers all five storages before the event loop is first driven** —
  every factory call completes during startup, ahead of any scheduler or handler
  execution.

**Scope**: Close the two operational gaps left open by
[stats-collecting-v1](./stats-collecting-v1.md) §11 ("Future work"): (1) **nothing in
production calls `aggregate()`** — `stat_aggregates` currently holds only the
migration-027 back-fill rows while live `stat_events` accumulate forever; (2) **no
retention** — processed `stat_events` rows are never deleted. This design adds a
periodic aggregation cycle — a handler riding the existing shared CRON_JOB
60-second tick, gated in-memory by a configurable interval — that drains the stats
storages into `stat_aggregates` and purges processed events past a retention
window, plus a minimal period-truncation refactor shared between the live
aggregator and migration 027.

> This is a **design document**, not an implementation. Every `file:line` reference
> cited for a NEW claim was verified against source on 2026-08-17 (branch
> `lib-stat-improvement`). Code sketches follow the repo's `camelCase` convention and
> SQL sketches follow the SQL-portability rules
> ([`AGENTS.md`](../../AGENTS.md) "SQL portability",
> [`docs/sql-portability-guide.md`](../sql-portability-guide.md)).

---

## 1. Context and goal

Gromozeka has a complete **write side** for statistics: five `DatabaseStatsStorage`
instances are constructed in [`main.py`](../../main.py):90-148 (one per event type:
`llm_request`, `llm_tool_call`, `stt_request`, `message`, `command`), each gated on
`[stats] enabled` (default `false` → storage stays `None` → `NullStatsStorage`
no-ops downstream) and each with its own `dataSource` key from `[stats]
<event>-stats-data-source` (default `"default"`). Events land in `stat_events` via
`record()`; the claim-based `aggregate()` rolls them into hourly/daily/monthly/total
buckets in `stat_aggregates`.

The **read/maintenance side is missing**: no production caller of `aggregate()`
exists, and processed events are never purged. Consequences today:

- Live aggregates are invisible (only the migration-027 back-fill rows exist in
  `stat_aggregates`).
- `stat_events` grows without bound for as long as stats stay enabled.

**Goal in one paragraph:** a single coordinator handler, registered on the existing
shared CRON_JOB 60-second tick and gated in-memory by a configurable interval (the
first tick after startup is an immediate catch-up), iterates all registered storages
sequentially with per-storage failure isolation, drains each via repeated
`aggregate()` calls, then purges processed events older than the retention window
through each storage's own provider/datasource. No separate enable flag: storages
are registered exactly when `[stats] enabled = true` — otherwise the factory hands
out unregistered `NullStatsStorage`s and the handler no-ops every tick.

### 1.1 Goals

- **G1** — Periodic aggregation: every stats storage's pending `stat_events` rows are
  rolled up into `stat_aggregates` at a configurable interval (default hourly),
  starting with an immediate catch-up run at startup.
- **G2** — Retention: processed `stat_events` rows older than
  `[stats] events-retention-days` (default 30, `0` = keep forever) are deleted,
  routed through each storage's own datasource.
- **G3** — Isolation: one storage's failure (DB error, missing table on a
  non-default datasource, …) never prevents the other storages from aggregating
  or future cycles from running.
- **G4** — Refactor: extract the period-truncation logic duplicated between
  `DatabaseStatsStorage._computePeriods` and migration 027's `_dayISO`/`_monthISO`
  into shared helpers, with **byte-identical** output (locked by the existing
  70-row migration test).
- **G5** — Stats-off silence when `[stats] enabled = false`: no storages are
  constructed or registered (the factory returns unregistered `NullStatsStorage`s),
  nothing is purged; the registered tick handler returns after one truthiness
  check — zero per-tick cost, equivalent to the old nothing-seeded state.

### 1.2 Non-goals

- **NG1** — No transactional claim→upsert→mark batch API on `BaseSQLProvider`. The
  non-atomicity of `aggregate()` is an **accepted** pre-existing gap (see §8 R1).
- **NG2** — No query/read API over `stat_aggregates` and no user-facing display
  (separate future design).
- **NG3** — No retention for `stat_aggregates` itself (buckets are small and
  cumulative; revisit if/when label cardinality grows).
- **NG4** — No config hot-reload mechanism. `ConfigManager` loads config once at
  construction ([`internal/config/manager.py`](../../internal/config/manager.py):127-130);
  the interval/retention keys are re-read each cycle so the design is robust to a
  future reload capability, but **today changing them still requires a restart**
  (honest caveat on D1's rationale — flagged, not relitigated).
- **NG5** — No multi-process coordination. The Max webhook receiver
  ([`internal/max_webhook_receiver/`](../../internal/max_webhook_receiver/)) does not
  touch stats; aggregation runs only in the bot process.

---

## 2. Verified grounding (current state)

Facts verified against source on 2026-08-17.

### 2.1 The stats pipeline

- `StatsStorage` ABC ([`lib/stats/stats_storage.py`](../../lib/stats/stats_storage.py)):
  `record(stats, *, consumerId, labels, eventTime)` (lines 26-53 — abstract, async,
  **never raises** by contract) and
  `aggregate(*, limit=1000, orphanTimeoutSeconds=3600) -> int` (lines 55-78 — returns
  events processed; claim-based). `NullStatsStorage` no-ops both (lines 81-118).
- `DatabaseStatsStorage.aggregate()`
   ([`lib/stats/sql_storage.py`](../../lib/stats/sql_storage.py):134):
   1. **Claim** (lines 163-191): single `UPDATE` setting `processed_id = batchId,
      claimed_at = now` on up to `limit` rows with `processed = 0 AND
      event_type = :eventType AND (processed_id IS NULL OR claimed_at < :orphanTimeout)`,
      via `provider.applyPagination()` for portable LIMIT, double-nested for
      MySQL ERROR 1093. The `event_type` predicate ensures per-type isolation
      when multiple storages share one table (Gate-2 fix, 2026-08-17).
  2. **Fetch** claimed rows by `processed_id = batchId` (lines 193-199); returns 0 if
     none.
  3. **Python pre-aggregation** keyed `(labelsJson, periodType, periodStart,
     metricKey)` with a parallel `__global__` label-set per event (lines 204-229).
  4. **One upsert per bucket** with SUM accumulation (lines 233-257; `TODO` at line
     232 flags the non-transactionality).
  5. **Mark processed** `processed = 1` by batchId (lines 259-265).
- `_computePeriods` (lines 293-315): hourly/daily/monthly truncation via
  `datetime.replace(...)` + ISO format; `total` uses the fixed epoch sentinel
  `"1970-01-01T00:00:00+00:00"`.
- `stat_events` schema ([`migration_016_add_stat_tables.py`](../../internal/database/migrations/versions/migration_016_add_stat_tables.py):98-110):
  `event_id TEXT PK` (app-generated UUID — no AUTOINCREMENT), `event_time/data/labels`,
  `processed INTEGER NOT NULL DEFAULT 0`, `processed_id TEXT NULL`,
  `claimed_at TIMESTAMP NULL`, **`created_at TIMESTAMP NOT NULL`** (line 108).
  Existing indexes: `idx_stat_events_unprocessed (processed, processed_id, claimed_at)`
  (lines 112-115) and `idx_stat_events_lookup (event_type, event_time)` (lines 116-119).
  **No index covers `(processed, created_at)`** — the retention DELETE's predicate.
- Timestamps cross the wire as ISO-8601 strings:
  `convertToSQLite` maps `datetime.datetime` → `data.isoformat()`
  ([`lib/db/providers/utils.py`](../../lib/db/providers/utils.py):55-56).
  The existing timestamp-comparison precedent binds a **Python datetime** as a
  `:named` parameter and compares directly: `claimed_at < :orphanTimeout`
  (sql_storage.py:187).

### 2.2 Storage construction and datasources

Five storages in [`main.py`](../../main.py), all gated on `statsEnabled`
(`statsConfig.get("enabled", False)`, line 92):

| Storage | Lines | eventType | dataSource key |
|---|---|---|---|
| `llmStatsStorage` | 90-98 | `llm_request` | `llm-stats-data-source` |
| `toolStatsStorage` | 107-115 | `llm_tool_call` | `tool-stats-data-source` |
| `sttStatsStorage` | 121-129 | `stt_request` | `stt-stats-data-source` |
| `messageStatsStorage` | 131-138 | `message` | `message-stats-data-source` |
| `commandStatsStorage` | 140-147 | `command` | `command-stats-data-source` |

Each key may name a **different datasource** (all default `"default"`). The provider
is obtained per storage as `await self.db.manager.getProvider(dataSource=self.dataSource,
readonly=False)` (sql_storage.py:114, 171) — retention **must** use the same
per-storage routing.

### 2.3 The QueueService delayed-task mechanism

- Handler registration: `registerDelayedTaskHandler(function: DelayedTaskFunction,
  handler: DelayedTaskHandler)` ([`internal/services/queue_service/service.py`](../../internal/services/queue_service/service.py):233-266).
  `DelayedTaskHandler` is `Callable[[DelayedTask], Awaitable[None]]`
  ([`types.py`](../../internal/services/queue_service/types.py):71) — handlers receive
  the `DelayedTask` only (kwargs live on `task.kwargs`; the seed passes `{}`).
  Multiple handlers per function are appended and run **sequentially** in
  registration order (service.py:261-264, 390).
- Handler exceptions are caught and logged per handler — they neither kill the loop
  nor sibling handlers (service.py:397-399).
- **The CRON_JOB tick (shared 60-second cadence)**: QueueService's own
  `_cronJobHandler` re-adds the task at `time.time() + 60` with `skipDB=True,
  skipLogs=True` (service.py:190-201); seeded once at startup inside
  `startDelayedScheduler` with `delayedUntil=time.time()` (immediate first tick) and
  `skipDB=True` (service.py:302-307). `skipDB=True` means the tick lives only in the
  in-memory `delayedActionsQueue` — **lost on restart, re-seeded at startup**. This
  is the accepted CRON_JOB lifecycle; the tick is QueueService's, and this design
  (A1) **rides** it rather than mirroring it.
- **No kwargs dispatch / time-gate precedent**: every CRON_JOB handler receives the
  same `task` (`kwargs={}`) — there is no per-handler payload. Each consumer gates
  internally on time checks; the established precedent is the weekly cache-cleanup
  gate `if nowMinutes == 0 and nowHour == 0 and nowWDay == 0` followed by
  `_cleanupOldData()` (manager.py:671-679). Job handlers never self-reschedule —
  the tick provides cadence.
- **CRON_JOB consumers coexist today (append-based, verified)**: QueueService's own
  tick handler, `HandlersManager._dtCronJob` (registered manager.py:634, handler
  657-696), and `ProxyService._dtCronJob` (proxy/service.py:108) all live on the one
  CRON_JOB function via list append (service.py:261-264). The stats handler becomes
  the fourth — the same mechanism.
- After every task's handlers run, the loop calls
  `self.db.delayedTasks.updateDelayedTask(delayedTask.taskId, True)`
  (service.py:401-402). For skipDB tasks the id was never persisted; the
  `UPDATE … WHERE id = :id` then affects **0 rows and raises nothing** — a silent
  no-op (delayed_tasks.py:206-220). Genuine DB errors are additionally swallowed by
  the repository's `except → return False`
  ([`internal/database/repositories/delayed_tasks.py`](../../internal/database/repositories/delayed_tasks.py):222-224).
  Safe by precedent.
- Tasks with **no registered handler** are re-queued +60 s with an error log
  (service.py:385-388). This cannot affect the tick our handler rides: CRON_JOB's
  own handler is registered before the tick is seeded (service.py:300-307).
- `addDelayedTask` with `skipDB=True` never requires the DB
  (service.py:470-472 — the "No database connection" raise applies only to
  `skipDB=False`) — this covers the tick's own seeding; A1 removes all seeding
  from this design.
- **External-class handler-registration precedent** (nine classes, all in
  `__init__`-time methods): `HandlersManager._dtCronJob`
  ([`manager.py`](../../internal/bot/common/handlers/manager.py):634,
  handler at 657-679), `ChatSearchHandler`
  ([`chat_search.py`](../../internal/bot/common/handlers/chat_search.py):237),
  `ResenderHandler` ([`resender.py`](../../internal/bot/common/handlers/resender.py):272),
  `SandboxHandler` ([`sandbox.py`](../../internal/bot/common/handlers/sandbox.py):94),
  `UserMemoriesHandler` ([`user_memories.py`](../../internal/bot/common/handlers/user_memories.py):249),
  `ProxyService` ([`internal/services/proxy/service.py`](../../internal/services/proxy/service.py):108-109,
  registers CRON_JOB and DO_EXIT), `CacheService`
  ([`internal/services/cache/service.py`](../../internal/services/cache/service.py):310),
  `ExampleHandler` ([`example.py`](../../internal/bot/common/handlers/example.py):82),
  and `common.py:82-86`. Multiple classes already share the `CRON_JOB` function this
  way — exactly what A1 does (no new function, no new mechanism).
- The scheduler is started from `main.py:75-78` via
  `loop.create_task(QueueService.getInstance().startDelayedScheduler(self.database))`
  — a background task on the shared loop. An `await`-driving precedent inside the
  synchronous `GromozekBot.__init__` exists at `main.py:119`
  (`loop.run_until_complete(self.rateLimiterManager.loadConfig(...))`).

### 2.4 The large-DELETE precedent (retention template)

`CacheRepository.clearOldCacheEntries` ([`internal/database/repositories/cache.py`](../../internal/database/repositories/cache.py):321-374):

- Computes `cutoffTime = dbUtils.getCurrentTimestamp() - datetime.timedelta(seconds=ttl)`
  in Python (line 352) and binds it as a `:named` param.
- Executes a **single unbounded** `DELETE FROM cache WHERE … AND updated_at <
  :cutoffTime` (lines 357-368) — **no LIMIT batching** (`DELETE … LIMIT` is not
  portable: PostgreSQL does not support it; SQLite only with a compile-time option).
- Runs weekly via `HandlersManager._dtCronJob` → `_cleanupOldData()`
  (manager.py:657-679) and on shutdown via `_dtOnExit` (manager.py:634-655).
- Its supporting index `idx_cache_updated_at` was created specifically "for TTL
  cleanup" ([`migration_012_unify_cache_tables.py`](../../internal/database/migrations/versions/migration_012_unify_cache_tables.py):78;
  recreated in migration_013:597).

### 2.5 Provider rowcount limitation

`BaseSQLProvider.execute` with `FetchType.NO_FETCH` returns `None`
([`lib/db/providers/base.py`](../../lib/db/providers/base.py):301-321)
— there is no portable "rows affected" return. A rows-deleted **count** must come
from a `SELECT COUNT(*)` with the same predicate issued before the DELETE (the app
is single-writer per datasource; the count is for logging only, so a count/delete
race is immaterial).

### 2.6 Migration 027 and its parity lock

- Migration 027 already imports `_hashLabels` from `lib.stats.sql_storage`
  ([`migration_027_drop_chat_stats_backfill_aggregates.py`](../../internal/database/migrations/versions/migration_027_drop_chat_stats_backfill_aggregates.py):40)
  and defines **local duplicates** of the period truncation: `_dayISO` (lines 323-343)
  and `_monthISO` (lines 346-366), each docstring'd "Mirrors the daily/monthly
  truncation from `_computePeriods`".
- The existing test
  [`tests/database/test_migration_027_drop_chat_stats_backfill_aggregates.py`](../../tests/database/test_migration_027_drop_chat_stats_backfill_aggregates.py)
  computes expected `period_start` ISO strings **independently** of the helpers
  (lines 422-426) and asserts exactly **70 rows** with exact `labels`, `labels_hash`,
  and `period_start` values (line 526, key-matched at 514-522). Any refactor that
  changes truncation output by one byte fails this test. The branch is unmerged, so
  migration 027 is still editable.

### 2.7 Existing test coverage already locking adjacent behavior

- Late/historical events: `testMultiplePeriods`
  ([`tests/lib/stats/test_sql_storage.py`](../../tests/lib/stats/test_sql_storage.py):134-168)
  records an event at a fixed past timestamp and asserts it lands in that hour's/
  day's/ month's buckets; `testTimestampNormalization` (lines 248-284) covers
  ISO-string event_time parsing. **Late-event correctness is already covered — no
  new test needed for it** (verified, per design brief).
- Drain semantics of a single storage: `testAggregateRespectsLimit` (lines 54-75)
  shows consecutive `aggregate()` calls claim 2 → 1 → 0; `testOrphanReclaim` /
  `testOrphanNotReclaimedWhenFresh` (lines 78-131) lock the orphan-timeout behavior.
- The `statsStorage` fixture ([`tests/lib/stats/conftest.py`](../../tests/lib/stats/conftest.py):18-56)
  builds an in-memory SQLite DB and applies **only migration 016** — the template
  for purge tests.
- Queue-service test patterns: singleton reset fixture
  (`QueueService._instance = None`, [`tests/services/queue_service/test_queue_service.py`](../../tests/services/queue_service/test_queue_service.py):25-37),
  `createAsyncMock` from `tests.utils`, `Mock` database wrapper (lines 40-47).
- Shared fixtures: `testDatabase` ([`tests/conftest.py`](../../tests/conftest.py):98)
  and `mockConfigManager` (line 265).

### 2.8 Config access

`ConfigManager.getStatsConfig()` ([`internal/config/manager.py`](../../internal/config/manager.py):492-506)
returns the merged `[stats]` dict per call. Config is loaded once in
`ConfigManager.__init__` (lines 127-130) — no reload mechanism exists. Other
periodic handlers hold a `configManager` reference from construction and read
section dicts per tick (e.g. `ChatSearchHandler` caches its per-tick batch size
precisely to avoid re-reading every minute — chat_search.py:197-198; reading once
per hour is negligible).

---

## 3. Architecture decisions

Decisions D1-D4 were **ratified by the user** (2026-08-17) and are encoded as
decided; D5-D10 resolve the assigned open points against the evidence in §2. The
**2026-08-17 amendments** (A1-A4, above) supersede the trigger/seeding design in
D1/D6/D10, the wiring in D5, and the cutoff in D3/D8; amended decisions are marked
*(amended)*.

### D1 — Trigger: shared CRON_JOB tick + in-memory interval gate *(amended 2026-08-17, user-ratified A1; supersedes the ratified STATS_AGGREGATION self-rescheduling task)*

**No new `DelayedTaskFunction` member.** `StatsAggregationService.initialize`
registers a rider on the existing tick:

```python
QueueService.getInstance().registerDelayedTaskHandler(
    DelayedTaskFunction.CRON_JOB, self._dtCronJob
)
```

CRON_JOB is a shared 60-second tick owned by QueueService ([§2.3](#23-the-queueservice-delayed-task-mechanism)):
`_cronJobHandler` re-adds it at `time.time() + 60` with `skipDB=True, skipLogs=True`
(service.py:190-201), seeded once at startup (service.py:302-307). Handler lists are
append-based (service.py:233-266); three consumers coexist on CRON_JOB today — the
stats handler is the fourth — and the per-handler try/except in the invocation loop
(service.py:390-399) means **the tick survives our handler raising, structurally**.

Cadence comes from an in-memory elapsed-time gate, not from task scheduling:

```python
# __init__ (runs once, before initialize):
self._lastRunTime: float = 0.0
self._intervalSeconds: int = 3600  # last-known-good interval (D10)

# per tick, in _dtCronJob:
if not self._statsStorages:
    return  # stats disabled → registry empty → zero per-tick cost (A3)
cycleStart = time.time()
if cycleStart - self._lastRunTime < self._intervalSeconds:
    return  # interval not elapsed — the tick itself keeps ticking
...  # guarded config read (D9/D10), cycle per D2/D3, INFO summary
self._lastRunTime = cycleStart  # set at cycle completion, to the cycle-start timestamp
```

- **First tick after startup is an immediate catch-up run** (`_lastRunTime = 0.0` →
  the gate always passes) — preserves the ratified "first run is catch-up" property
  with no seeding at all.
- **Interval from `[stats] aggregation-interval-seconds`, default 3600, read fresh
  each cycle** (D9). The gate itself uses the stored last-known-good value, so a
  malformed config cannot corrupt the gate (D10).
- **Interval clamp `max(60, int(...))` stays**: 60 s is the tick granularity — a
  sub-60 value would run every tick anyway; the clamp just makes it honest.
- **No kwargs dispatch** (§2.3): the handler receives the shared `task`
  (`kwargs={}`) and gates internally — the same shape as the cache-cleanup
  precedent (manager.py:671-679). Handler signature contract:
  `async def _dtCronJob(self, task: DelayedTask) -> None`.
- **Duplicate/concurrent cycles are structurally impossible in-process**: a
  singleton handler, one gate advanced only at cycle completion, and a tick that
  runs its handler list sequentially (service.py:390).
- Consequence: the old D10 reschedule-first machinery and its chain-death risk are
  **obsolete** — see the amended D10 for the one thing that remains
  config-sensitive.

### D2 — Coordinator: one cycle, all registered storages, sequential, isolated, drained *(ratified; wording amended 2026-08-17 for A1/A3)*

The stats cron handler (`_dtCronJob`) owns one cycle over **all registered storages
in a fixed order** — `self._statsStorages.values()` in insertion order
(`llm_request`, `llm_tool_call`, `stt_request`, `message`, `command` — the main.py
factory-call order; Python dicts preserve insertion order). Per storage, inside its
own `try/except Exception`:

1. **Drain loop**: call `aggregate()` repeatedly until it returns `0` **or** a safety
   cap of **10 rounds** per storage per cycle is hit (`MAX_AGGREGATION_ROUNDS = 10`
   module constant; at the default `limit=1000` that bounds a cycle at 10 000 events
   per storage). The cap exists so a runaway backlog cannot monopolize the shared
   tick — the cycle runs **inside** the CRON_JOB tick, whose sibling handlers and
   next tick run sequentially on one loop (service.py:347-418).
2. **Retention purge** (same `try/except`): if `events-retention-days > 0`, call
   `storage.purgeProcessed(retentionDays=…)` (D7). Purge **after** aggregation in the
   same cycle — a just-processed batch becomes purge-eligible only next cycle
   (cutoff is the UTC midnight of `now − N days` (A2/D8), so freshly processed rows
   are ~30 days from eligibility anyway; ordering is about never purging rows an
   in-flight cycle still needs).

One **INFO** log line per run summarizing per-storage processed and purged counts
plus which storages errored. Aggregation failures log at exception level per storage
but never abort the cycle.

### D3 — Retention: per-storage purge of processed events *(ratified; cutoff amended 2026-08-17, A2)*

`DELETE FROM stat_events WHERE processed = 1 AND created_at < :cutoff`, executed
**through each storage's own provider/datasource** — datasources may differ per
storage ([§2.2](#22-storage-construction-and-datasources)); a single global DELETE
against one DB would miss the others. New config `[stats] events-retention-days`,
default **30**; `0` = keep forever (skip the purge call entirely; D7 adds a
defensive in-impl guard). Exact SQL mechanics in D8.

**Day-truncated cutoff (A2):** the cutoff is
`truncateToDay(getCurrentTimestamp() - timedelta(days=retentionDays))` — the **UTC
midnight of N days ago**, reusing the Phase-1 shared helper
(sql_storage.py:471). Semantics: an event is deleted only once it is beyond
**N whole days** — hours/minutes/seconds of age within the boundary day do not
count, so effective retention is between N and N+1 days depending on time of day.
Truncation can only delay a deletion, never accelerate it, which strictly
strengthens R3's safety margin.

The `processed = 1` predicate is load-bearing: claimed-but-unprocessed rows
(`processed = 0`, e.g. after a crash) are never deleted — they are reclaimed by the
next `aggregate()` and only then become eligible.

### D4 — Refactor fold-in: shared period-truncation helpers *(ratified)*

Extract from `_computePeriods` (sql_storage.py:523) two module-level helpers
in [`lib/stats/sql_storage.py`](../../lib/stats/sql_storage.py):

```python
def truncateToDay(eventTime: datetime.datetime) -> str: ...
def truncateToMonth(eventTime: datetime.datetime) -> str: ...
```

Both return the ISO-8601 UTC string exactly as `_computePeriods` emits today —
plain `.replace()` truncation reproduced **byte-for-byte** (sql_storage.py:484
contains no naive handling, and none may be added). The contract is pinned on the
input: callers must pass **aware-UTC** datetimes — all live callers do
(`getCurrentTimestamp()` is aware-UTC; migration 027 combines its values with
`tzinfo=utc`, the naive→UTC handling its local `_dayISO`/`_monthISO` perform today
at lines 335-339/358-362). Naive normalization thus stays OUT of the shared
helpers; no implementer should add naive handling inside `_computePeriods`' new
composition. `_computePeriods` becomes a thin composer
over them (+ hourly + total sentinel); migration 027 **deletes its local
`_dayISO`/`_monthISO`** (lines 323-366) and imports the shared helpers (it already
imports `_hashLabels` from the same module, line 40 — no new import surface). Keep
it minimal: shared helpers, not a rewrite. Parity is locked by the existing 70-row
test ([§2.6](#26-migration-027-and-its-parity-lock)) — it must pass **unchanged**
after the refactor (the only permitted edit is the mechanical removal of the deleted
helper definitions; the test itself imports only `_hashLabels`, test line 34, so no
test edit is expected at all).

### D5 — Handler home + storage factory: dedicated `StatsAggregationService` singleton *(amended 2026-08-17, A3; resolves open point a)*

**Decision:** a new class-based singleton `StatsAggregationService` in a new package
`internal/services/stats/` (`service.py` + `__init__.py`, mirroring the layout of
`internal/services/{cache,llm,proxy,queue_service,storage,stt}/`), which registers
its own CRON_JOB handler with QueueService **and owns the storage factory +
registry** — the single construction seam for stats storages.

**Evidence and rationale:**

- The alternative — a new QueueService method — is **against every precedent in the
  tree**: nine external classes already register their own handlers via
  `registerDelayedTaskHandler` ([§2.3](#23-the-queueservice-delayed-task-mechanism)).
  QueueService knows nothing about stats today; coupling it to the storages would
  invert the established dependency direction (consumers reach QueueService, never
  vice versa).
- The repo prefers class-based singletons with `getInstance()` and an
  `initialize(...)` injection method — `STTService` is the exact
  template ([`internal/services/stt/service.py`](../../internal/services/stt/service.py):76-98:
  `_instance`/`_lock`, `__new__` create-or-return, `hasattr(self, "initialized")`
  guard, separate `initialize` receiving `configManager` at startup).
- The singleton pattern is mandatory here anyway: the handler must be reachable from
  `initialize` (registration) and from the QueueService dispatch (execution) — and,
  after A3, the factory + registry must be reachable from main.py's five
  construction sites — the same object via `getInstance()` in every case.
- **Cyclic-import safety (verified):** `internal/services/stats` importing
  `lib/stats` is safe — main.py already imports both
  (main.py:33 plus the storage import), and services already import
  `internal.database` elsewhere (`internal/services/queue_service/service.py:36`).

**Factory — the single construction seam:**

```python
def createStatsStorage(self, eventType: str, dataSource: str | None = None) -> StatsStorage:
```

- Reads `[stats] enabled` itself
  (`self._configManager.getStatsConfig().get("enabled", False)`) — the enable
  gating moves out of main.py into the seam.
- **Disabled** → returns `NullStatsStorage()` and does **not** register it: the
  registry stays empty, so the handler's empty-dict early return (D1) makes
  stats-disabled a zero-per-tick cost — equivalent to the old nothing-seeded state.
- **Enabled** → constructs
  `DatabaseStatsStorage(db=self._database, eventType=eventType,
  dataSource=dataSource or self._database.manager.default)` — today's concrete
  type; the seam exists so a future non-DB backend is a one-site change — registers
  it in `self._statsStorages: Dict[str, StatsStorage]` keyed by eventType, and
  returns it.
- `dataSource=None` resolves to the database manager's default datasource: main.py
  passes `statsConfig.get("<event>-stats-data-source")` (which is `None` when the
  key is absent), preserving today's
  `statsConfig.get(key, self.database.manager.default)` resolution
  (main.py:98/114/128/138/147) inside the seam.

**`initialize` signature (amended):**

```python
def initialize(self, configManager: ConfigManager, database: Database) -> None:
```

Stores both, then registers
`QueueService.getInstance().registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB,
self._dtCronJob)`. **Synchronous** — registration is a dict append, nothing to
await (precedents: `ProxyService.initialize`, main.py:88; `STTService.initialize`,
main.py:130). **No `statsStorages` parameter and no seeding** — the storages arrive
later, one factory call at a time (D6).

> **Flagged deviation from the ratified note:** A3's note says "`initialize(configManager)`
> only". Taken literally, the service cannot construct `DatabaseStatsStorage` that
> way: the storage constructor requires the `DatabaseManager` reference
> (sql_storage.py:64-74), `DatabaseManager` is a plain class — not a singleton
> (manager.py:43) — and the only reference lives in `GromozekBot.__init__`
> (main.py:66-68). The ratified intent — the static storages list and its parameter
> disappear — is preserved; `database` rides along as the factory's unavoidable
> dependency. The alternative (a `db=` parameter on `createStatsStorage` per call)
> was rejected: it moves the same dependency to five call sites and churns the
> ratified factory signature.

### D6 — Startup wiring & lifecycle: `initialize` before the factory calls, no seeding *(amended 2026-08-17, A1/A3; supersedes the seeding design)*

**Decision:** `GromozekBot.__init__` calls, before the first storage construction
(after the proxy init at main.py:88, before main.py:90):

```python
StatsAggregationService.getInstance().initialize(self.configManager, self.database)
```

Then each of the five per-event sites (main.py:90-147) becomes a factory call at the
same site, e.g.:

```python
llmStatsStorage = StatsAggregationService.getInstance().createStatsStorage(
    "llm_request", statsConfig.get("llm-stats-data-source")
)
```

(the remaining four: `"llm_tool_call"`/`tool-stats-data-source`,
`"stt_request"`/`stt-stats-data-source`, `"message"`/`message-stats-data-source`,
`"command"`/`command-stats-data-source`). The returned storages flow to the existing
consumers — `LLMManager(statsStorage=…)`, `LLMService.injectStatsStorage`,
`STTService.initialize`, the bot applications and `HandlersManager`'s
message/command storages — **exactly as today**. Downstream
`or NullStatsStorage()` fallbacks (llm/service.py:230, manager.py:443-444) remain
harmless: when disabled they receive a real `NullStatsStorage` instead of `None`.
The current working tree's static-list block (main.py:150-168) is **deleted** —
`initialize` moves up, becomes synchronous, and there is no storages list and no
`run_until_complete` (nothing to await).

**Stats-disabled:** `initialize` is still called (it registers the tick handler);
the factory returns unregistered `NullStatsStorage`s → `self._statsStorages` stays
empty → the handler returns after one truthiness check per tick (D1). Nothing
aggregated, nothing purged (risk-register item R5).

**Lifecycle:**

- **No task to seed or reschedule** — the tick is QueueService's (seeded at
  service.py:302-307, rescheduled at service.py:201). The entire skipDB lifecycle
  analysis of the original D6 is obsolete: no STATS_AGGREGATION task exists, no
  `updateDelayedTask` no-op needs reasoning, and the "no handlers" stall
  (service.py:385-388) cannot touch CRON_JOB, whose handler is registered before
  the tick is seeded (service.py:300-307).
- **Restart resets the gate** (`__init__` re-runs → `_lastRunTime = 0.0`) → the
  first tick after startup is the immediate catch-up cycle — the ratified G1
  property, now provided by the gate instead of by seeding.

### D7 — `purgeProcessed` on the ABC: raise-on-error, returns rows deleted *(resolves open point d)*

**Decision:** grow the `StatsStorage` ABC:

```python
@abstractmethod
async def purgeProcessed(self, *, retentionDays: int) -> int:
    """Delete processed stat events older than the retention window.

    Deletes rows with ``processed = 1 AND created_at < truncateToDay(now -
    retentionDays)`` (UTC midnight of N days ago, A2)
    through this storage's own data source. ``retentionDays <= 0`` is a no-op
    (keep forever). Errors propagate to the caller (matching ``aggregate()``'s
    contract — isolation is the coordinator's job, D2); ``record()`` remains the
    only never-raise method.

    Args:
        retentionDays: Minimum age in days for a processed row to be deleted.

    Returns:
        Number of rows deleted (0 if nothing was eligible or retention is off).
    """
```

- `NullStatsStorage.purgeProcessed` returns 0 (mirrors its `aggregate`).
- **Raise vs never-raise:** `aggregate()` has **no** internal try/except — provider
  errors propagate (sql_storage.py:134); only `record()` is contractually
  never-raise (stats_storage.py:41-43 "Implementations SHOULD be best-effort").
  `purgeProcessed` follows `aggregate`: it may raise, the coordinator's per-storage
  `try/except` (D2) isolates. This keeps isolation in exactly one place instead of
  splitting it between storage and coordinator. (The bool-swallowing style of
  `clearOldCacheEntries` is the *other* precedent; it is rejected here because the
  coordinator already wraps every per-storage step, and an `int` return feeds the
  summary log line.)
- **Cutoff computation lives in the implementation** (`DatabaseStatsStorage`), as
  `truncateToDay(dbUtils.getCurrentTimestamp() - datetime.timedelta(days=retentionDays))`
  (A2) — the same-module Phase-1 helper (sql_storage.py:471), so no import is
  needed; the un-truncated cache-repo shape (cache.py:352) remains the precedent for
  the `timedelta` subtraction itself.
- **Keep-forever guard in both layers:** the coordinator skips the call when
  `retentionDays <= 0`, and the impl returns 0 immediately on `retentionDays <= 0`
  (belt and suspenders; the impl guard is what the `0 = keep forever` test pins).

### D8 — Retention DELETE mechanics: portable, unbounded, counted, indexed *(resolves open point c)*

Inside `DatabaseStatsStorage.purgeProcessed`, through **this storage's** provider
(`await self.db.manager.getProvider(dataSource=self.dataSource, readonly=False)` —
same call as `record`/`aggregate`, sql_storage.py:114/171):

```python
if retentionDays <= 0:
    return 0
# A2: day-truncated cutoff — UTC midnight of N days ago (ISO string; see notes)
cutoff = truncateToDay(dbUtils.getCurrentTimestamp() - datetime.timedelta(days=retentionDays))
sqlProvider = await self.db.manager.getProvider(dataSource=self.dataSource, readonly=False)

countRow = await sqlProvider.executeFetchOne(
    """SELECT COUNT(*) AS cnt FROM stat_events
       WHERE processed = 1 AND created_at < :cutoff""",
    {"cutoff": cutoff},
)
await sqlProvider.execute(
    """DELETE FROM stat_events
       WHERE processed = 1 AND created_at < :cutoff""",
    {"cutoff": cutoff},
)
return int(countRow["cnt"]) if countRow is not None else 0
```

Portability notes (each per `AGENTS.md` "SQL portability" /
[`docs/sql-portability-guide.md`](../sql-portability-guide.md)):

- **`:named` placeholder, ISO-8601 string bound (A2)** — the cutoff is now the
  helper's ISO string rather than a Python datetime; this is **wire-equivalent**:
  `convertToSQLite` would map a datetime to `isoformat()` anyway
  (providers/utils.py:55-56) and string params pass through unchanged. ISO-8601
  strings compare correctly lexicographically across SQLite/PostgreSQL/MySQL — the
  identical argument backing `claimed_at < :orphanTimeout` (sql_storage.py:176)
  and `updated_at < :cutoffTime` (cache.py:362), whose stored values share the same
  `isoformat()` shape.
- **No dialect functions** — no `DATE()`, no `NOW()`, no `COLLATE`, no
  `DEFAULT CURRENT_TIMESTAMP`; the cutoff is computed in application code (the
  repo-wide rule since migration 013).
- **No LIMIT batching** — `DELETE … LIMIT` is not portable (PostgreSQL rejects it;
  SQLite needs a non-default compile option). The repo's large-delete precedent is a
  single unbounded DELETE (`clearOldCacheEntries`, §2.4), running against a far
  larger table (`cache`) than `stat_events` will ever be under a 30-day retention.
  Mirror it.
- **Count via `SELECT COUNT(*)` first** — `execute` with NO_FETCH returns no rowcount
  (§2.5), so the count for the return value/summary comes from a COUNT with the same
  predicate. Single-writer app → no meaningful race; count is telemetry.
- **Boundary semantics (A2)** — the strict-`<` boundary is now a UTC midnight. A row
  created **during the boundary day survives** (its `created_at` sorts after the
  midnight cutoff), as does a row timestamped exactly at midnight (`<` is strict);
  only rows from whole days before the boundary are deleted. The Phase-1
  `TestPurgeProcessed` edge case pins this.

**Supporting index (new migration 028):** add

```sql
CREATE INDEX IF NOT EXISTS idx_stat_events_retention ON stat_events (processed, created_at)
```

in `migration_028_add_stat_events_retention_index.py` (`version: int = 28`;
027 is the highest today — verified). Rationale: the retention DELETE's predicate is
exactly `(processed, created_at)`; today only `idx_stat_events_unprocessed
(processed, processed_id, claimed_at)` exists (migration_016:112-115), which gives a
`processed = 1` prefix scan over every processed row on every purge. The
`idx_cache_updated_at` "for TTL cleanup" precedent (migration_012:78) is exactly
this. `down()` drops the index. `CREATE INDEX IF NOT EXISTS` + `DROP INDEX IF
EXISTS` match existing migration precedent (migration_016:113/117,
migration_024:66/83) and are idempotent — not fully portable, since MySQL proper
lacks `IF [NOT] EXISTS` on index DDL; follow the
[`add-database-migration`](../../.agents/skills/add-database-migration/SKILL.md)
skill.

### D9 — Config access: hold `configManager`, re-read `[stats]` each cycle *(resolves open point e)*

The service stores the `configManager` reference from `initialize` (the
`STTService.initialize(configManager)` pattern, stt/service.py:90) and the handler
reads, **once per cycle — after the interval gate passes, inside the guarded parse
of D10** (the gate itself uses the stored last-known-good, so no config access
happens on gated ticks):

```python
statsConfig = self.configManager.getStatsConfig()
intervalSeconds = max(60, int(statsConfig.get("aggregation-interval-seconds", 3600)))
retentionDays = int(statsConfig.get("events-retention-days", 30))
```

`getStatsConfig()` is a cheap dict lookup (manager.py:492-506). **Honest caveat**
(NG4): `ConfigManager` loads config once at construction (manager.py:127-130) —
there is no reload mechanism today, so "config changes take effect without restart"
holds only structurally (the value read at each cycle is whatever the manager
currently holds; the moment a reload capability lands, interval changes apply with
≤ 1 interval of latency and retention changes on the next cycle). This is the
right shape regardless; do not add a reload mechanism in this design.

### D10 — Guarded config parse: a malformed value must not turn every tick into an exception *(amended 2026-08-17, A1)*

The reschedule-first machinery of the original decision is **obsolete** — there is no
chain to keep alive. The tick belongs to QueueService and survives our handler
raising **structurally**: the invocation loop try/excepts per handler
(service.py:390-399), so a failing stats cycle can neither kill the tick nor its
sibling handlers. What remains config-sensitive is the per-cycle read (D9): a
malformed `aggregation-interval-seconds` (or `events-retention-days`) value would
otherwise raise inside the handler **every tick** — 1440 exception-level log lines
per day. The remaining guarded-config rationale is exactly that: **a malformed
interval value must not crash the cycle every tick.** Keep the guarded parse, the
last-known-good fallback, and `logger.exception`; on parse failure skip the cycle's
work — the tick keeps ticking, and the worst case is a no-op cycle with an error
log, not a dead chain:

```python
cycleStart = time.time()
if cycleStart - self._lastRunTime < self._intervalSeconds:
    return  # gate uses the STORED last-known-good interval
try:
    statsConfig = self.configManager.getStatsConfig()
    self._intervalSeconds = max(60, int(statsConfig.get("aggregation-interval-seconds", 3600)))
    retentionDays = int(statsConfig.get("events-retention-days", 30))
except (TypeError, ValueError):
    logger.exception("stats aggregation: malformed [stats] config; skipping cycle")
    self._lastRunTime = cycleStart  # consume the cycle; retry next interval, not next tick
    return
...  # per-storage drain + purge (D2/D3), then the INFO summary
self._lastRunTime = cycleStart
```

- **Last-known-good**: the gate reads `self._intervalSeconds`, which is updated only
  by successful parses (initialized to 3600 in `__init__`) — a malformed value can
  never widen or corrupt the gate.
- **A skipped cycle still advances the gate** (to its start timestamp): a persistent
  config fault costs one error log per interval, not one per tick. Config repair
  requires a restart anyway (NG4/R8), which re-seeds the default cleanly.
- **An exception escaping the cycle scaffolding** (outside the per-storage
  try/excepts — e.g. a bug in the summary log) leaves the gate un-advanced, so the
  retry comes on the next tick (60 s). Still no tight loop is possible: the tick,
  not the handler, provides scheduling. The interval is measured from cycle start;
  with a run-time of seconds and a 3600 s interval the effective cadence is ≈ the
  interval.

---

## 4. Wiring diagram

```
GromozekBot.__init__ (main.py)
│
├─ main.py:66-68   Database(config)                                   [EXISTING]
├─ main.py:76-79   loop.create_task(startDelayedScheduler(database)) [EXISTING]
│
├─ [REWORKED] before the first factory call (~main.py:89):
│     StatsAggregationService.getInstance().initialize(
│         self.configManager, self.database)              [sync; dict append]
│     └─ registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB,
│            self._dtCronJob)                                        [D1]
│
├─ main.py:90-147  five createStatsStorage(...) calls at the same     [REWORKED]
│     per-event sites (llm_request, llm_tool_call, stt_request,
│     message, command); the factory reads [stats] enabled itself:
│       disabled → NullStatsStorage (NOT registered)
│       enabled  → DatabaseStatsStorage, registered by eventType
│                  in StatsAggregationService._statsStorages       [D5/A3]
│     returned storages flow to LLMManager / LLMService.injectStatsStorage /
│     STTService.initialize / applications exactly as today   [EXISTING consumers]
│
└─ scheduler loop (service.py:347)
      │  CRON_JOB seeded once (service.py:302-307);
      │  _cronJobHandler re-adds the tick every 60 s (service.py:201)
      ▼
      every 60 s, all CRON_JOB handlers run sequentially,
      exceptions caught per handler (service.py:390-399):
        QueueService._cronJobHandler        (the tick itself)
        HandlersManager._dtCronJob          (chat states; weekly cache cleanup)
        ProxyService._dtCronJob
        StatsAggregationService._dtCronJob(task)              [NEW rider]
              │
              ├─ empty _statsStorages? → return (stats disabled)   [D1]
              ├─ gate: time.time() - _lastRunTime < intervalSeconds
              │  (stored last-known-good) → return; tick keeps ticking [D1]
              ├─ cycleStart = time.time()
              ├─ guarded config read (interval, retention);
              │  parse failure → logger.exception + skip cycle     [D9/D10]
              ├─ for storage in _statsStorages.values():          [D2]
              │     try:
              │     │  drain: repeat aggregate() until 0 or 10 rounds
              │     │  purge: purgeProcessed(retentionDays=N) via the
              │     │    storage's OWN provider/datasource, cutoff =
              │     │    truncateToDay(now - N days)               [D3/D8/A2]
              │     except Exception: log (storage isolated)
              ├─ one INFO summary line (per-storage processed/purged/errors)
              └─ _lastRunTime = cycleStart                          [D1]
```

Storage-side changes (Phase 1) are confined to `lib/stats/stats_storage.py` (ABC +
Null), `lib/stats/sql_storage.py` (`purgeProcessed`, truncation helpers),
migration 027 (import shared helpers), and new migration 028 (retention index).

---

## 5. Configuration changes

[`configs/00-defaults/stats.toml`](../../configs/00-defaults/stats.toml) (diff):

```toml
 [stats]
 enabled = false

 llm-stats-data-source = "default"
 stt-stats-data-source = "default"
 message-stats-data-source = "default"
 tool-stats-data-source = "default"
 command-stats-data-source = "default"
 +aggregation-interval-seconds = 3600   # D1 (amended): min elapsed between cycles;
 +                                     # 60 s tick granularity; first tick after
 +                                     # startup is catch-up; cached at init (A4)
 +aggregation-batch-limit = 1000       # A4: bounds drain batch size; clamp >= 1;
 +                                     # bounds cycle at MAX_AGGREGATION_ROUNDS × limit
 +events-retention-days = 30            # D3 (amended): whole-day retention (A2);
 +                                     # 0 = keep forever; cached at init (A4)
```

No new enable flag — the **factory reads `[stats] enabled` itself** (D5/A3), so the
gating lives in the construction seam instead of main.py. `ConfigManager.getStatsConfig()`
already returns the merged `[stats]` dict — no reader changes beyond `.get(...)` with
the defaults above. All three keys are already present in the working tree (Phase 2's
first cut landed them); the rework leaves them unchanged. **A4 adds `aggregation-batch-limit`**
and changes the semantics: config is read once at `initialize` (not per-cycle), malformed
values raise `ValueError`, and the handler uses cached values (no guarded parse).

---

## 6. Phased implementation plan

Hard rules for **every** phase (`AGENTS.md`): `camelCase`; `StrEnum` for any enum
member (the amended design adds none — Phase 2 removes one); docstrings with
`Args:`/`Returns:` on everything; type hints everywhere; no
`Any`; no pydantic; Python via `./venv/bin/python3`; `make format lint` **before AND
after** edits; `make test` (timeout-wrapped) mandatory; regression test first on any
bug fix. Implement via `software-developer`; docs pass via the
[`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md) skill.

### Phase 1 — `purgeProcessed` + truncation refactor + retention index

Sized ~55 steps: four production files (three edited + new migration 028) + three
test files.

**Files:**

- [`lib/stats/stats_storage.py`](../../lib/stats/stats_storage.py) — abstract
  `purgeProcessed(*, retentionDays: int) -> int` (D7 docstring contract).
- Null implementation: `purgeProcessed` returns 0.
- [`lib/stats/sql_storage.py`](../../lib/stats/sql_storage.py) —
  `purgeProcessed` implementation per D8; extract `truncateToDay` /
  `truncateToMonth`; `_computePeriods` recomposed over them (byte-identical output).
- [`internal/database/migrations/versions/migration_027_drop_chat_stats_backfill_aggregates.py`](../../internal/database/migrations/versions/migration_027_drop_chat_stats_backfill_aggregates.py) —
  delete `_dayISO`/`_monthISO` (323-366); import the shared helpers (extend the
  existing `from ...stats_storage import _hashLabels`, line 40).
- `internal/database/migrations/versions/migration_028_add_stat_events_retention_index.py` —
  **new**; `CREATE INDEX IF NOT EXISTS idx_stat_events_retention ON stat_events
  (processed, created_at)`; `down()` = `DROP INDEX IF EXISTS`. Follow the
  [`add-database-migration`](../../.agents/skills/add-database-migration/SKILL.md)
  skill (no AUTOINCREMENT / CURRENT_TIMESTAMP / COLLATE / dialect DDL; `:named`
  params).

**Tests** (`asyncio_mode = "auto"` — `async def test_…`, no decorator):

- `tests/lib/stats/test_sql_storage.py` — new `TestPurgeProcessed` class on the
  existing `statsStorage` fixture (migration 016 only — the index is a performance
  concern, not a semantic one; the fixture stays unchanged):
  - deletes only `processed = 1 AND created_at < cutoff` (seed old-processed,
    new-processed, old-unprocessed; only the first disappears);
  - returns the correct count;
  - `retentionDays = 0` → no-op returning 0;
  - cutoff edge (row exactly at cutoff survives — `<` is strict; with A2 the cutoff
    is always a UTC midnight, and a row created **during the boundary day**
    survives too — pins the `truncateToDay` truncation).
- `tests/lib/stats/test_null_storage.py` — `purgeProcessed` returns 0.
- `tests/database/test_migration_028_*.py` (or extend the migrations suite per the
  migration-test pattern) — index exists after `up()`, gone after `down()`,
  idempotent re-run.
- **Refactor parity (no new test needed — verify and state):** the existing 70-row
  migration-027 test ([§2.6](#26-migration-027-and-its-parity-lock)) and
  `testMultiplePeriods` must pass **unchanged**; they independently recompute every
  expected `period_start` byte. If either fails, the refactor is wrong, not the
  test.

**A2 rework touch-point (post-amendment):** Phase 1 as implemented in the working
tree uses the un-truncated cutoff; the rework changes that one line in
`purgeProcessed` to the day-truncated form (D8) and adds the boundary-day case to
`TestPurgeProcessed`. Everything else in Phase 1 stands.

**Docs sync (this phase):** `docs/database-schema.md` + `docs/database-schema-llm.md`
(stat_events index; both files in sync), `docs/llm/database.md` (migration 028 in the
version list), `docs/llm/libraries.md` §9 (`purgeProcessed`), `CHANGELOG.md` — this
phase alone is not user-visible (no trigger yet); fold its `Added` entry into the
Phase-2 entry or add `Added: StatsStorage.purgeProcessed … (internal API)` per the
changelog "when-not" judgment — decide at implementation.

**Gate 1:** `make format lint`; `make test` (full suite — the parity lock is the
point); `make check-docs`.

### Phase 2 — `StatsAggregationService` rework: CRON_JOB trigger + factory + wiring (amended)

Sized ~50 steps — a **rework of the working-tree implementation** (which follows the
superseded self-rescheduling design): one reworked service file, two edited
production files (enum revert + main.py rewiring), one rewritten test file + docs.

**Files:**

- `internal/services/stats/__init__.py` — package exports (mirrors
  `queue_service/__init__.py`); docstring updated to the CRON_JOB rider.
- `internal/services/stats/service.py` — **rework**: the singleton scaffolding per
  the `STTService` template stays (`_instance`/`_lock`/`__new__`/`getInstance()`/
  `hasattr(self, "initialized")` guard — stt/service.py:76-98; do not re-implement
  the guard differently). **Remove**: `_statsAggregationHandler` (the
  reschedule-first handler), the seeding `addDelayedTask`, and the empty-list
  warning guard. **Add**: `initialize(configManager, database)` (sync; registers
  the CRON_JOB handler — D5/D6), `createStatsStorage(eventType, dataSource=None)`
  factory + `_statsStorages: Dict[str, StatsStorage]` registry (D5/A3),
  `_lastRunTime: float = 0.0` and `_intervalSeconds: int = 3600` state, and
  `_dtCronJob(task: DelayedTask) -> None` per D1/D10. The per-storage
  drain/purge/summary cycle body (D2) carries over essentially unchanged.
  `MAX_AGGREGATION_ROUNDS = 10` constant stays.
- [`internal/services/queue_service/types.py`](../../internal/services/queue_service/types.py) —
  **remove** the `STATS_AGGREGATION = "statsAggregation"` member (working-tree
  line 21) and its references.
- [`main.py`](../../main.py) — replace the five `if statsEnabled:`
  `DatabaseStatsStorage(...)` constructions (main.py:90-147) with five
  `createStatsStorage(...)` calls at the same sites; insert the sync
  `initialize(self.configManager, self.database)` call before the first factory
  call; delete the static-list init block (main.py:150-168).
- [`configs/00-defaults/stats.toml`](../../configs/00-defaults/stats.toml) —
  unchanged (keys already landed, §5).

**Tests** — `tests/services/stats/test_service.py` (**rewritten**; mirror
`tests/services/queue_service/test_queue_service.py` patterns: reset
`StatsAggregationService._instance = None` (and the QueueService singleton where
manipulated) in the fixture; `createAsyncMock` from `tests.utils`; real storages via
the `tests/lib/stats/conftest.py` in-memory-DB pattern where DB semantics matter).
The seeding/reschedule tests of the first cut are **replaced** by tick-gating and
factory tests:

| Behavior under test | Approach |
|---|---|
| Handler registered on CRON_JOB, no new function | after `initialize`: `QueueService.tasksHandlers[CRON_JOB]` contains `_dtCronJob`; `STATS_AGGREGATION` no longer exists on the enum |
| Interval not elapsed → no work | `_lastRunTime = now`, interval 3600 → run handler → no `aggregate`/`purgeProcessed` calls |
| Interval elapsed → cycle runs | `_lastRunTime = now − 3601` → storages drained + purged; `_lastRunTime` advanced to the cycle-start timestamp |
| First tick after startup is catch-up | fresh singleton (`_lastRunTime = 0.0`) → the first handler run does work |
| Empty registry → no-op | `_statsStorages = {}` → handler returns immediately; no config read, no work |
| Factory: disabled → unregistered Null | `enabled = false` → `createStatsStorage` returns `NullStatsStorage`; `_statsStorages` stays empty |
| Factory: enabled → registered | `enabled = true` → returns a `DatabaseStatsStorage`; `_statsStorages[eventType]` is it; the five calls preserve insertion order |
| Malformed config skips cycle work without killing future cycles | interval key set to a non-int → no `aggregate` calls, error logged, gate advanced; fix the mock value and elapse the interval → the next run works |
 | Drain stops at 0 | storage with 3 events, `limit`-bounded mocks or real storage; assert total = 3 and aggregate-call count |
 | Drain stops at the 10-round cap | mock `aggregate` always returning `limit`; assert exactly `MAX_AGGREGATION_ROUNDS` calls |
 | Per-storage isolation | storage 1's `aggregate` raises; storage 2 still drained and purged; summary logs the error |
 | Retention purge deletes only processed+old rows | **DEFERRED** — coordinator-path retention is already covered by Phase-1 unit tests (`TestPurgeProcessed` matrix at §6 Phase 1). The compositional rationale: the coordinator only calls per-storage methods; purgeProcessed routing is unit-covered. |
 | `0 = keep forever` skips purge | `retentionDays=0` → `purgeProcessed` never called (mock assert) |
 | Purge goes through each storage's own datasource | **DEFERRED** — cross-datasource routing is covered by Phase-1 unit tests (`DatabaseStatsStorage` instantiates with a specific dataSource). The compositional rationale: coordinator only calls per-storage methods; each storage uses its own provider. |
 | Five-call insertion order | **DEFERRED** — insertion order is an implementation detail of main.py call order (llm_request, llm_tool_call, stt_request, message, command). The compositional rationale: coordinator iterates `_statsStorages.values()` which preserves insertion order; the factory test verifies registration. |
 | Late-event correctness | **already covered** by `testMultiplePeriods` / `testTimestampNormalization` ([§2.7](#27-existing-test-coverage-already-locking-adjacent-behavior)) — cite, don't duplicate |
| Refactor parity | **already covered** by the 70-row migration test — cite, don't duplicate |

**Docs sync:** `docs/llm/services.md` (new `StatsAggregationService` section —
wording per the amendments: a CRON_JOB-rider aggregation cycle plus the
`createStatsStorage` factory/registry, **not** a dedicated delayed task),
`docs/llm/configuration.md` `[stats]` table (two keys) **and** update the §[stats]
note that says "Disabled by default until aggregation trigger and query API are
implemented" (aggregation trigger now exists; query API still pending),
`docs/llm/architecture.md` stats-pipeline note (same stale sentence at its line
~421; wording per the amendments), `docs/llm/index.md` services listing,
`docs/llm/libraries.md` §9 (trigger note), `CHANGELOG.md` `Added` under
`## [Unreleased]` (e.g. "Periodic stats aggregation and event retention now run
hourly when `[stats] enabled = true`; configurable via
`aggregation-interval-seconds` / `events-retention-days`").

**Gate 2:** `make format lint`; `make test`; `make check-docs`.

---

## 7. Verification gates

| Gate | Command / action | When |
|---|---|---|
| Format + lint | `make format lint` (before AND after edits) | every phase |
| Full suite | `make test` (timeout-wrapped; mandatory) | every phase |
| Docs links | `make check-docs` | every phase (schema/config doc edits) |
| Refactor parity | migration-027 70-row test + `testMultiplePeriods` pass **unmodified** | Phase 1 |
| Purge semantics | `TestPurgeProcessed` matrix (§6 Phase 1) | Phase 1 |
| Coordinator behavior | `tests/services/stats/test_service.py` matrix (§6 Phase 2) | Phase 2 |
| Tick gating + factory | gate/catch-up/empty-registry/factory/malformed-config tests (§6 Phase 2) | Phase 2 |
| Stats-off silence | factory returns unregistered `NullStatsStorage`; empty registry → handler no-ops every tick (zero per-tick cost) | Phase 2 |
| Config print | `./venv/bin/python3 main.py --print-config --config-dir configs/00-defaults …` shows the new keys | Phase 2 |

No live/operator smoke gate: the feature is default-off telemetry; the suite plus
the parity lock is the safety net (same stance as stats-collecting-v1 §8).

---

## 8. Risk register + rollback

| # | Risk | Likelihood | Impact | Mitigation | Rollback |
|---|---|---|---|---|---|
| R1 | **Non-transactional aggregation (accepted gap)** — claim → upsert → mark-processed is not one transaction (TODO at sql_storage.py:244); a crash mid-batch leaves claimed rows that orphan-reclaim re-processes → **double-counted buckets** | Low | Med | **Accepted by decision** (2026-08-17). Bounded exposure: batches ≤ 1000 events; worst case one batch double-counted per crash; hourly cadence; aggregates are approximate telemetry, not billing. Orphan reclaim (sql_storage.py:176) prevents permanent stalls. A transactional batch API on `BaseSQLProvider` is an explicit **future follow-up (NG1)**, not a blocker | n/a (pre-existing); long-term fix = provider transaction primitive |
| R2 | **Orphan timeout vs batch runtime** — a claimed-but-unfinished batch is eligible for reclaim after `orphanTimeoutSeconds` (default 3600, fixed — not tied to the interval). If a process freeze/very slow cycle holds a claim > 1 h, the next cycle reclaims and re-processes it (same double-count as R1). Conversely, cycles cannot overlap in-process: the singleton's in-memory gate plus the tick's sequential handler list (service.py:390) make concurrent/duplicate cycles structurally impossible (R10) | Low | Med | Drain cap (10 rounds) bounds cycle runtime to seconds-minutes; the freeze must exceed the orphan timeout, not the interval, to matter; lowering the interval does **not** lower the reclaim bar. Document; optionally expose the timeout as config later (§9 Q1) | n/a |
| R3 | **Retention deletes needed data** — a predicate bug could purge unprocessed events (permanent loss — events are append-only) | Low | High | `processed = 1` is part of the ABC contract docstring AND pinned by tests (old-unprocessed row survives); count-before-delete makes the summary line an audit trail; default 30 days far exceeds the aggregation lag (≤ 1 h); the day-truncated cutoff (A2) can only delay a deletion, never accelerate it — retention is effectively N..N+1 days, never less than N | Set `events-retention-days = 0` (keep forever) — instant, no code |
| R4 | **Refactor changes truncation bytes** — back-fill buckets and live buckets split or shift | Low | Med | Shared helpers are the *only* truncation code path after D4; the 70-row test independently recomputes every expected byte and must pass unmodified | Revert Phase 1 |
| R5 | **Stats disabled = silent no-op ticks** — `[stats] enabled = false` makes the factory hand out unregistered `NullStatsStorage`s; the registry stays empty and the registered handler returns after one truthiness check per tick (zero per-tick cost, equivalent to the old nothing-seeded state). If an operator enables stats expecting aggregates from a period when stats were off: there are none — **and none were recorded** (disabled stats record nothing either), so there is no silent backlog gap; enabling requires a restart, and the restart's first tick is the catch-up run (R11) | — (by design) | Low | Documented here; D5/A3 ratified no separate flag | n/a |
| R6 | **Tick head-of-line blocking** — a big drain cycle (10 rounds × 5 storages) runs inside the shared CRON_JOB tick, delaying sibling tick handlers and the next tick on the single sequential loop (service.py:347-418) | Low | Low | Caps bound the cycle; the interval gate limits cycles to once per interval (default hourly); worst-case backlog after long downtime drains over consecutive cycles (10 k events/storage/cycle) | Raise `aggregation-interval-seconds` |
| R7 | **Non-default datasources** — an operator pointing an event's `*-stats-data-source` at a source without migration 016/028 tables gets purge/aggregate errors | Low | Med | Per-storage try/except isolates to that storage; same precondition as recording today (stats-collecting-v1 §9 "Multi data-source mismatch"); the summary line names the failing storage | Keep `*-stats-data-source = "default"` |
| R8 | **Config caveat** — interval/retention changes need a restart today (no ConfigManager reload, NG4) | — | Low | Per-cycle read is future-proof; documented | n/a |
| R9 | **CRON_JOB tick coexistence** — the stats rider joins three existing consumers (QueueService's tick, `HandlersManager._dtCronJob`, `ProxyService._dtCronJob`) on the one shared 60-second tick; a registration mistake or handler misbehavior could disturb them | — (verified safe) | Low | Append-based registration is the **verified** mechanism (service.py:233-266; manager.py:634; proxy/service.py:108); the per-handler try/except isolates failures (service.py:390-399); the gated rider costs one comparison per tick; the old chain-death failure mode is gone because the tick's survival is structural, not the handler's responsibility | Revert the registration (the service/factory remain harmless) |
| R10 | **Duplicate/concurrent cycles** — two overlapping cycles could double-claim batches (compounding R1) | — (structurally impossible) | Med | Singleton handler + a single in-memory gate advanced only at cycle completion + a tick that runs its handler list sequentially (service.py:390); NG5 keeps aggregation single-process | n/a |
| R11 | **Restart resets the gate** — `_lastRunTime` is in-memory, so every restart makes the first tick a catch-up cycle (extra startup work, e.g. under frequent restarts or crash loops) | Certain | Low | By design — preserves G1's ratified catch-up property; the drain caps bound the catch-up cycle (R6); with an empty backlog the catch-up is a few no-op `aggregate()` calls | n/a |

**Rollback principle:** the whole feature is gated on `[stats] enabled = false`
(default) — disabling stats removes recording *and* empties the aggregation
registry in one flag (the registered handler degrades to a no-op tick). Each phase
is independently revertible via git; migration 028's `down()`
drops only the index (no data change); Phase 1's refactor is behavior-neutral by
construction (parity-locked).

---

## 9. Open questions

1. **Expose the orphan timeout as config?** `aggregate(orphanTimeoutSeconds=3600)`
   keeps its default; the coordinator does not override it. If operators run very
   long drain cycles or want faster crash recovery, `[stats]
   aggregation-orphan-timeout-seconds` could be added. Recommendation: not now —
   no demonstrated need; revisit with R2 telemetry.
2. **`stat_aggregates` retention / cardinality management** — out of scope (NG3);
   revisit when a query API lands and real bucket counts are observable.
3. **Config hot reload** — the per-cycle config read (D9) makes interval changes
   restart-free the moment `ConfigManager` gains a reload capability. Whether to
   build that is a separate, repo-wide decision.
4. **Purge batching for very large first runs** — the first purge after enabling a
   short retention on a long-running DB may delete a large backlog in one
   unbounded DELETE (SQLite locks the table for the duration). The cache-cleanup
   precedent accepts this; if it ever bites, a portable chunked loop
   (SELECT ids with `applyPagination` → DELETE `WHERE event_id IN (:ids)`) can be
   added inside `purgeProcessed` without touching the coordinator.

---

## 10. Documentation impact (when implementation lands)

Load the [`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md)
skill and update:

- [`docs/llm/configuration.md`](../llm/configuration.md) — `[stats]` table: the two
  new keys; **update the note** "Disabled by default until aggregation trigger and
  query API are implemented" (trigger now exists).
- [`docs/llm/services.md`](../llm/services.md) — new `internal/services/stats/`
  section; wording per the amendments: `StatsAggregationService` = CRON_JOB-rider
  aggregation cycle + `createStatsStorage` factory/registry + retention — **no**
  dedicated delayed task, no `STATS_AGGREGATION` enum member.
- [`docs/llm/libraries.md`](../llm/libraries.md) §9 — `StatsStorage.purgeProcessed`;
  note that a production `aggregate()` caller now exists.
- [`docs/llm/database.md`](../llm/database.md) — migration 028 in the version list;
  retention-index note on the stat tables.
- [`docs/llm/architecture.md`](../llm/architecture.md) — stats pipeline section:
  add the aggregation/retention cycle (wording per the amendments: shared-tick
  rider + factory seam); fix the stale "disabled until aggregation trigger"
  sentence.
- [`docs/llm/index.md`](../llm/index.md) — services listing gains
  `internal/services/stats/`.
- [`docs/database-schema.md`](../database-schema.md) **and**
  [`docs/database-schema-llm.md`](../database-schema-llm.md) — `stat_events` index
  (both in sync, per the dual-schema rule).
- `CHANGELOG.md` — one `Added` entry under `## [Unreleased]` with Phase 2 (per
  [`docs/llm/changelog.md`](../llm/changelog.md) rules; this PROPOSED doc itself gets
  no entry — doc-only).

---

## 11. References

- Predecessor design (event taxonomy, wiring): [`stats-collecting-v1.md`](./stats-collecting-v1.md)
- Archived stats-library design (aggregate() v3 flow): [`docs/archive/plans/lib-stats-stats-library-v3.md`](../archive/plans/lib-stats-stats-library-v3.md)
- Stats interface: [`lib/stats/stats_storage.py`](../../lib/stats/stats_storage.py)
- DB backend: [`lib/stats/sql_storage.py`](../../lib/stats/sql_storage.py)
- Stat tables schema: [`migration_016_add_stat_tables.py`](../../internal/database/migrations/versions/migration_016_add_stat_tables.py)
- Parity lock: [`tests/database/test_migration_027_drop_chat_stats_backfill_aggregates.py`](../../tests/database/test_migration_027_drop_chat_stats_backfill_aggregates.py)
- Delayed-task mechanism: [`internal/services/queue_service/service.py`](../../internal/services/queue_service/service.py),
  [`types.py`](../../internal/services/queue_service/types.py)
- Large-DELETE + TTL-index precedent: [`internal/database/repositories/cache.py`](../../internal/database/repositories/cache.py):321-374,
  [`migration_012_unify_cache_tables.py`](../../internal/database/migrations/versions/migration_012_unify_cache_tables.py)
- Singleton + initialize template: [`internal/services/stt/service.py`](../../internal/services/stt/service.py):76-98
- Schema docs: [`docs/database-schema.md`](../database-schema.md),
  [`docs/database-schema-llm.md`](../database-schema-llm.md)
- Skills: [`add-database-migration`](../../.agents/skills/add-database-migration/SKILL.md),
  [`run-quality-gates`](../../.agents/skills/run-quality-gates/SKILL.md),
  [`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md)
