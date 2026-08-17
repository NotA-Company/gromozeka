# Design: Statistics aggregation v1 — periodic trigger and retention

**Date**: 2026-08-17
**Status**: **PROPOSED** (design only — no production code changed)
**Owner**: TBD
**Branch**: `lib-stat-improvement`

**Scope**: Close the two operational gaps left open by
[stats-collecting-v1](./stats-collecting-v1.md) §11 ("Future work"): (1) **nothing in
production calls `aggregate()`** — `stat_aggregates` currently holds only the
migration-027 back-fill rows while live `stat_events` accumulate forever; (2) **no
retention** — processed `stat_events` rows are never deleted. This design adds a
self-rescheduling periodic task that drains all five stats storages into
`stat_aggregates` and purges processed events past a retention window, plus a minimal
period-truncation refactor shared between the live aggregator and migration 027.

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

**Goal in one paragraph:** a single periodic task, seeded at startup and
self-rescheduling like the existing CRON_JOB pattern, iterates all five storages
sequentially with per-storage failure isolation, drains each via repeated
`aggregate()` calls, then purges processed events older than the retention window
through each storage's own provider/datasource. No separate enable flag: the task
exists exactly when `[stats] enabled = true`.

### 1.1 Goals

- **G1** — Periodic aggregation: every stats storage's pending `stat_events` rows are
  rolled up into `stat_aggregates` at a configurable interval (default hourly),
  starting with an immediate catch-up run at startup.
- **G2** — Retention: processed `stat_events` rows older than
  `[stats] events-retention-days` (default 30, `0` = keep forever) are deleted,
  routed through each storage's own datasource.
- **G3** — Isolation: one storage's failure (DB error, missing table on a
  non-default datasource, …) never prevents the other storages from aggregating or
  the task from rescheduling.
- **G4** — Refactor: extract the period-truncation logic duplicated between
  `DatabaseStatsStorage._computePeriods` and migration 027's `_dayISO`/`_monthISO`
  into shared helpers, with **byte-identical** output (locked by the existing
  70-row migration test).
- **G5** — Zero behavior change when `[stats] enabled = false`: no task is seeded,
  no handler registered, nothing purged.

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
  ([`internal/database/stats_storage.py`](../../internal/database/stats_storage.py):129-267):
  1. **Claim** (lines 163-191): single `UPDATE` setting `processed_id = batchId,
     claimed_at = now` on up to `limit` rows with `processed = 0 AND (processed_id IS
     NULL OR claimed_at < :orphanTimeout)`, via `provider.applyPagination()` for
     portable LIMIT, double-nested for MySQL ERROR 1093.
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
  ([`internal/database/providers/utils.py`](../../internal/database/providers/utils.py):55-56).
  The existing timestamp-comparison precedent binds a **Python datetime** as a
  `:named` parameter and compares directly: `claimed_at < :orphanTimeout`
  (stats_storage.py:176, 189).

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
readonly=False)` (stats_storage.py:109, 161) — retention **must** use the same
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
- **Self-rescheduling precedent**: `_cronJobHandler` re-adds itself with
  `skipDB=True, skipLogs=True` (service.py:190-201); seeded at startup inside
  `startDelayedScheduler` with `delayedUntil=time.time()` (immediate first run) and
  `skipDB=True` (service.py:302-307). `skipDB=True` means the task lives only in the
  in-memory `delayedActionsQueue` — **lost on restart, re-seeded at startup**. That
  is the accepted CRON_JOB lifecycle this design mirrors.
- After every task's handlers run, the loop calls
  `self.db.delayedTasks.updateDelayedTask(delayedTask.taskId, True)`
  (service.py:401-402). For skipDB tasks the id was never persisted; the
  `UPDATE … WHERE id = :id` then affects **0 rows and raises nothing** — a silent
  no-op (delayed_tasks.py:206-220). Genuine DB errors are additionally swallowed by
  the repository's `except → return False`
  ([`internal/database/repositories/delayed_tasks.py`](../../internal/database/repositories/delayed_tasks.py):222-224).
  Safe by precedent.
- Tasks with **no registered handler** are re-queued +60 s with an error log
  (service.py:385-388) — seeding before registration would stall one minute;
  registration must precede seeding (it does — see D6).
- `addDelayedTask` with `skipDB=True` never requires the DB
  (service.py:470-472 — the "No database connection" raise applies only to
  `skipDB=False`), so seeding before/while `startDelayedScheduler` initializes is
  safe.
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
  way; a class registering a handler for **its own new** function is the same
  mechanism.
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
([`internal/database/providers/base.py`](../../internal/database/providers/base.py):301-321)
— there is no portable "rows affected" return. A rows-deleted **count** must come
from a `SELECT COUNT(*)` with the same predicate issued before the DELETE (the app
is single-writer per datasource; the count is for logging only, so a count/delete
race is immaterial).

### 2.6 Migration 027 and its parity lock

- Migration 027 already imports `_hashLabels` from `internal.database.stats_storage`
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
decided; D5-D10 resolve the assigned open points against the evidence in §2.

### D1 — Trigger: new `DelayedTaskFunction.STATS_AGGREGATION`, self-rescheduling *(ratified)*

New StrEnum member `STATS_AGGREGATION = "statsAggregation"` in
[`types.py`](../../internal/services/queue_service/types.py) (naming follows
`CRON_JOB = "cronJob"`). The task is seeded at startup with `delayedUntil = now` →
**first run is an immediate catch-up**, then each run reschedules
`now + interval`. Interval from new config `[stats] aggregation-interval-seconds`,
default **3600**, **read fresh each cycle** at reschedule time (see D9 for the
restart caveat). No separate enable flag — the task is seeded exactly when
`[stats] enabled = true` (stats disabled = no storages = nothing seeded).

StrEnum + `skipDB=True` mean the function value is **never persisted** to
`delayed_tasks`, so restoring old persisted tasks (`DelayedTaskFunction(task["function"])`,
service.py:313) can never encounter an unknown value introduced by this change.

### D2 — Coordinator: one task, five storages, sequential, isolated, drained *(ratified)*

The STATS_AGGREGATION handler owns one cycle over **all five storages in a fixed
order** (`llm_request`, `llm_tool_call`, `stt_request`, `message`, `command` —
construction order in main.py). Per storage, inside its own `try/except Exception`:

1. **Drain loop**: call `aggregate()` repeatedly until it returns `0` **or** a safety
   cap of **10 rounds** per storage per cycle is hit (`MAX_AGGREGATION_ROUNDS = 10`
   module constant; at the default `limit=1000` that bounds a cycle at 10 000 events
   per storage). The cap exists so a runaway backlog cannot monopolize the delayed
   queue (all delayed tasks — including the per-minute CRON_JOB handlers — run
   sequentially on one loop, service.py:347-418).
2. **Retention purge** (same `try/except`): if `events-retention-days > 0`, call
   `storage.purgeProcessed(retentionDays=…)` (D7). Purge **after** aggregation in the
   same cycle — a just-processed batch becomes purge-eligible only next cycle
   (cutoff is `now − N days`, so freshly processed rows are ~30 days from
   eligibility anyway; ordering is about never purging rows an in-flight cycle still
   needs).

One **INFO** log line per run summarizing per-storage processed and purged counts
plus which storages errored. Aggregation failures log at exception level per storage
but never abort the cycle.

### D3 — Retention: per-storage purge of processed events *(ratified)*

`DELETE FROM stat_events WHERE processed = 1 AND created_at < :cutoff`, executed
**through each storage's own provider/datasource** — datasources may differ per
storage ([§2.2](#22-storage-construction-and-datasources)); a single global DELETE
against one DB would miss the others. New config `[stats] events-retention-days`,
default **30**; `0` = keep forever (skip the purge call entirely; D7 adds a
defensive in-impl guard). Exact SQL mechanics in D8.

The `processed = 1` predicate is load-bearing: claimed-but-unprocessed rows
(`processed = 0`, e.g. after a crash) are never deleted — they are reclaimed by the
next `aggregate()` and only then become eligible.

### D4 — Refactor fold-in: shared period-truncation helpers *(ratified)*

Extract from `_computePeriods` (stats_storage.py:293-315) two module-level helpers
in [`internal/database/stats_storage.py`](../../internal/database/stats_storage.py):

```python
def truncateToDay(eventTime: datetime.datetime) -> str: ...
def truncateToMonth(eventTime: datetime.datetime) -> str: ...
```

Both return the ISO-8601 UTC string exactly as `_computePeriods` emits today —
plain `.replace()` truncation reproduced **byte-for-byte** (stats_storage.py:305-307
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

### D5 — Handler home: dedicated `StatsAggregationService` singleton *(resolves open point a)*

**Decision:** a new class-based singleton `StatsAggregationService` in a new package
`internal/services/stats/` (`service.py` + `__init__.py`, mirroring the layout of
`internal/services/{cache,llm,proxy,queue_service,storage,stt}/`), which registers
its own handler with QueueService and receives its dependencies via an
`initialize(...)` called from `main.py`.

**Evidence and rationale:**

- The alternative — a new QueueService method — is **against every precedent in the
  tree**: nine external classes already register their own handlers via
  `registerDelayedTaskHandler` ([§2.3](#23-the-queueservice-delayed-task-mechanism)).
  QueueService knows nothing about stats today; coupling it to the storages would
  invert the established dependency direction (consumers reach QueueService, never
  vice versa) and QueueService has no path to the storages — they are locals in
  `GromozekBot.__init__` (main.py:90-147).
- The repo prefers class-based singletons with `getInstance()` and an
  `initialize(configManager, …)` injection method — `STTService` is the exact
  template ([`internal/services/stt/service.py`](../../internal/services/stt/service.py):76-98:
  `_instance`/`_lock`, `__new__` create-or-return, `hasattr(self, "initialized")`
  guard, separate `initialize` receiving `configManager` at startup).
- The singleton pattern is mandatory here anyway: the handler must be reachable from
  `initialize` (registration) and from the QueueService dispatch (execution) — the
  same object via `getInstance()`.

**`initialize` signature:**

```python
async def initialize(self, configManager: ConfigManager, statsStorages: list[StatsStorage]) -> None:
```

Stores both, registers
`QueueService.getInstance().registerDelayedTaskHandler(DelayedTaskFunction.STATS_AGGREGATION,
self._dtStatsAggregation)`, then seeds the first task (D6). Defensive guard: empty
`statsStorages` logs a warning and skips seeding (main.py never calls it that way —
see D6 — but the service should not spin a task with nothing to do).

### D6 — Seeding: inside `initialize`, called from `main.py` after the storages exist *(resolves open point b)*

**Decision:** `GromozekBot.__init__` calls, right after `commandStatsStorage` is
built (after main.py:147, before the bot application at main.py:150):

```python
if statsEnabled:
    loop.run_until_complete(
        StatsAggregationService.getInstance().initialize(
            self.configManager,
            statsStorages=[
                llmStatsStorage,
                toolStatsStorage,
                sttStatsStorage,
                messageStatsStorage,
                commandStatsStorage,
            ],
        )
    )
```

`loop.run_until_complete` from the synchronous `__init__` is the established
precedent at main.py:119 (rateLimiterManager). The scheduler background task
already exists by then (created main.py:75-78; driven since the first
`run_until_complete`).

**Stats-disabled:** `initialize` is simply never called → no handler registered, no
task seeded → aggregation is **never started behind disabled stats** (risk-register
item R5). Nothing else needed.

**skipDB lifecycle (mirrors CRON_JOB exactly, §2.3):**

- Seed: `addDelayedTask(delayedUntil=time.time(),
  function=DelayedTaskFunction.STATS_AGGREGATION, kwargs={}, skipDB=True)` —
  in-memory only; safe even if the scheduler loop has not started (the task waits in
  the priority queue; `skipDB=True` never touches the DB, service.py:470-472).
- Reschedule: same call with `delayedUntil = time.time() + intervalSeconds`,
  `skipDB=True, skipLogs=True` — mirrors `_cronJobHandler` (service.py:201).
- **Lost on restart — fine**: startup re-seeds via `initialize`. This is precisely
  the CRON_JOB contract (seeded at service.py:302-307, rescheduled skipDB at 201,
  never persisted, never restored from `getPendingDelayedTasks`).
- The post-handler `updateDelayedTask(taskId, True)` (service.py:401-402) is a no-op
  for the never-persisted id — the `UPDATE` matches 0 rows and raises nothing
  (delayed_tasks.py:206-220); genuine DB errors are swallowed at
  delayed_tasks.py:222-224 — same as every CRON_JOB tick today.

**Ordering invariant:** inside `initialize`, the handler registration (synchronous
dict append) precedes the seeding `await` in program order, and the seeded task is
due immediately — so by the time any loop pass can execute the task, the handler is
registered (no 60 s "No handlers" stall, service.py:385-388).

### D7 — `purgeProcessed` on the ABC: raise-on-error, returns rows deleted *(resolves open point d)*

**Decision:** grow the `StatsStorage` ABC:

```python
@abstractmethod
async def purgeProcessed(self, *, retentionDays: int) -> int:
    """Delete processed stat events older than the retention window.

    Deletes rows with ``processed = 1 AND created_at < now - retentionDays``
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
  errors propagate (stats_storage.py:129-267); only `record()` is contractually
  never-raise (stats_storage.py:41-43 "Implementations SHOULD be best-effort").
  `purgeProcessed` follows `aggregate`: it may raise, the coordinator's per-storage
  `try/except` (D2) isolates. This keeps isolation in exactly one place instead of
  splitting it between storage and coordinator. (The bool-swallowing style of
  `clearOldCacheEntries` is the *other* precedent; it is rejected here because the
  coordinator already wraps every per-storage step, and an `int` return feeds the
  summary log line.)
- **Cutoff computation lives in the implementation** (`DatabaseStatsStorage`), as
  `dbUtils.getCurrentTimestamp() - datetime.timedelta(days=retentionDays)` — exactly
  the cache-repo pattern (cache.py:352). A shared helper would be one line used by
  one implementation; per-impl is simpler and matches `clearOldCacheEntries`.
- **Keep-forever guard in both layers:** the coordinator skips the call when
  `retentionDays <= 0`, and the impl returns 0 immediately on `retentionDays <= 0`
  (belt and suspenders; the impl guard is what the `0 = keep forever` test pins).

### D8 — Retention DELETE mechanics: portable, unbounded, counted, indexed *(resolves open point c)*

Inside `DatabaseStatsStorage.purgeProcessed`, through **this storage's** provider
(`await self.db.manager.getProvider(dataSource=self.dataSource, readonly=False)` —
same call as `record`/`aggregate`, stats_storage.py:109/161):

```python
if retentionDays <= 0:
    return 0
cutoff = dbUtils.getCurrentTimestamp() - datetime.timedelta(days=retentionDays)
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

- **`:named` placeholder, Python datetime bound** — the provider converts datetimes
  to ISO strings (`convertToSQLite`, providers/utils.py:55-56); the identical
  pattern already compares `claimed_at < :orphanTimeout` (stats_storage.py:176) and
  `updated_at < :cutoffTime` (cache.py:362). ISO-8601 strings compare correctly
  lexicographically across SQLite/PostgreSQL/MySQL.
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
reads, at the **top of every cycle**:

```python
statsConfig = self.configManager.getStatsConfig()
intervalSeconds = int(statsConfig.get("aggregation-interval-seconds", 3600))
retentionDays = int(statsConfig.get("events-retention-days", 30))
```

`getStatsConfig()` is a cheap dict lookup (manager.py:492-506). **Honest caveat**
(NG4): `ConfigManager` loads config once at construction (manager.py:127-130) —
there is no reload mechanism today, so "config changes take effect without restart"
holds only structurally (the value read at each reschedule is whatever the manager
currently holds; the moment a reload capability lands, hourly-interval changes
apply with ≤ 1 h latency and retention changes on the next cycle). This is the
right shape regardless; do not add a reload mechanism in this design.

### D10 — Reschedule first, work second (failure-tolerant chain)

The handler's first statement is the reschedule (mirroring `_cronJobHandler`,
service.py:201, which reschedules before doing anything):

```python
async def _dtStatsAggregation(self, task: DelayedTask) -> None:
    statsConfig = self.configManager.getStatsConfig()
    intervalSeconds = int(statsConfig.get("aggregation-interval-seconds", 3600))
    # Reschedule FIRST: even if this cycle raises, the chain survives.
    await QueueService.getInstance().addDelayedTask(
        time.time() + intervalSeconds,
        DelayedTaskFunction.STATS_AGGREGATION,
        kwargs={},
        skipDB=True,
        skipLogs=True,
    )
    ...  # per-storage drain + purge (D2/D3), then the INFO summary
```

A misconfigured `aggregation-interval-seconds = 0` or negative value would produce
a tight self-rescheduling loop on the shared delayed queue; the implementation
clamps it with a floor, e.g.
`intervalSeconds = max(60, int(statsConfig.get("aggregation-interval-seconds", 3600)))`.

Why first: QueueService catches handler exceptions so the loop survives a raise
(service.py:397-399), but **the self-rescheduling chain is our responsibility** — a
handler that raises before rescheduling kills aggregation until the next restart.
Rescheduling first makes the worst case "one skipped cycle", not "dead chain". The
interval is measured from cycle start; with a run-time of seconds and a 3600 s
interval the effective cadence is ≈ the interval.

---

## 4. Wiring diagram

```
GromozekBot.__init__ (main.py)
│
├─ main.py:90-147  statsEnabled? ── build 5× DatabaseStatsStorage
│                   (each with its own dataSource key)          [EXISTING]
│
├─ [NEW] after main.py:147, gated on the same statsEnabled:
│     loop.run_until_complete(
│         StatsAggregationService.getInstance().initialize(
│             configManager, statsStorages=[llm, tool, stt, message, command]))
│     │
│     ├─ (1) registerDelayedTaskHandler(                        [sync, dict append]
│     │        DelayedTaskFunction.STATS_AGGREGATION,
│     │        self._dtStatsAggregation)
│     └─ (2) addDelayedTask(delayedUntil=now,
│              function=STATS_AGGREGATION, kwargs={}, skipDB=True)
│
└─ main.py:75-78   loop.create_task(startDelayedScheduler(database)) [EXISTING]
      │
      └─ _startDelayedQueueProcessLoop (service.py:347)
            │  task due → run registered handlers sequentially,
            │  exceptions caught per handler (service.py:390-399)
            ▼
      StatsAggregationService._dtStatsAggregation(task)     [NEW]
            │
            ├─ re-read [stats] config (interval, retention)   [D9]
            ├─ reschedule next run: now + interval, skipDB    [D10, FIRST]
            ├─ for storage in [llm, tool, stt, message, command]:   [D2]
            │     try:
            │     │  drain: repeat aggregate() until 0 or 10 rounds
            │     │  purge: purgeProcessed(retentionDays=N) — via the
            │     │         storage's OWN provider/datasource      [D3/D8]
            │     except Exception: log (storage isolated)
            └─ one INFO summary line (per-storage processed/purged/errors)
```

Storage-side changes (Phase 1) are confined to `lib/stats/stats_storage.py` (ABC +
Null), `internal/database/stats_storage.py` (`purgeProcessed`, truncation helpers),
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
+aggregation-interval-seconds = 3600   # D1: cycle cadence; first run at startup
+events-retention-days = 30            # D3: processed-event retention; 0 = keep forever
```

No new enable flag. `ConfigManager.getStatsConfig()` already returns the merged
`[stats]` dict — no reader changes beyond `.get(...)` with the defaults above.

---

## 6. Phased implementation plan

Hard rules for **every** phase (`AGENTS.md`): `camelCase`; `StrEnum` for the enum
member; docstrings with `Args:`/`Returns:` on everything; type hints everywhere; no
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
- [`internal/database/stats_storage.py`](../../internal/database/stats_storage.py) —
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
  - future cutoff edge (row exactly at cutoff survives — `<` is strict).
- `tests/lib/stats/test_null_storage.py` — `purgeProcessed` returns 0.
- `tests/database/test_migration_028_*.py` (or extend the migrations suite per the
  migration-test pattern) — index exists after `up()`, gone after `down()`,
  idempotent re-run.
- **Refactor parity (no new test needed — verify and state):** the existing 70-row
  migration-027 test ([§2.6](#26-migration-027-and-its-parity-lock)) and
  `testMultiplePeriods` must pass **unchanged**; they independently recompute every
  expected `period_start` byte. If either fails, the refactor is wrong, not the
  test.

**Docs sync (this phase):** `docs/database-schema.md` + `docs/database-schema-llm.md`
(stat_events index; both files in sync), `docs/llm/database.md` (migration 028 in the
version list), `docs/llm/libraries.md` §9 (`purgeProcessed`), `CHANGELOG.md` — this
phase alone is not user-visible (no trigger yet); fold its `Added` entry into the
Phase-2 entry or add `Added: StatsStorage.purgeProcessed … (internal API)` per the
changelog "when-not" judgment — decide at implementation.

**Gate 1:** `make format lint`; `make test` (full suite — the parity lock is the
point); `make check-docs`.

### Phase 2 — `StatsAggregationService` + trigger + config + wiring

Sized ~60 steps: two new service files + three edited files + one test file + docs.

**Files:**

- `internal/services/stats/__init__.py` — package exports (mirrors
  `queue_service/__init__.py`).
- `internal/services/stats/service.py` — **new** `StatsAggregationService`
  singleton: `_instance`/`_lock`/`__new__`/`getInstance()`/`hasattr(self,
  "initialized")` guard exactly per the `STTService` template (stt/service.py:76-98;
  do not re-implement the guard differently); `initialize(configManager,
  statsStorages)` (D5/D6); `_dtStatsAggregation(task: DelayedTask) -> None` (D2/D10);
  `MAX_AGGREGATION_ROUNDS = 10` constant.
- [`internal/services/queue_service/types.py`](../../internal/services/queue_service/types.py) —
  `STATS_AGGREGATION = "statsAggregation"` StrEnum member.
- [`configs/00-defaults/stats.toml`](../../configs/00-defaults/stats.toml) — two keys
  (§5).
- [`main.py`](../../main.py) — the gated `initialize` call after line 147 (D6); import.

**Tests** — `tests/services/stats/test_service.py` (mirror
`tests/services/queue_service/test_queue_service.py` patterns: reset
`StatsAggregationService._instance = None` (and the QueueService singleton where
manipulated) in the fixture; `createAsyncMock` from `tests.utils`; real storages via
the `tests/lib/stats/conftest.py` in-memory-DB pattern where DB semantics matter):

| Behavior under test | Approach |
|---|---|
| Drain stops at 0 | storage with 3 events, `limit`-bounded mocks or real storage; assert total = 3 and aggregate-call count |
| Drain stops at the 10-round cap | mock `aggregate` always returning `limit`; assert exactly `MAX_AGGREGATION_ROUNDS` calls |
| Per-storage isolation | storage 1's `aggregate` raises; storage 2 still drained and purged; summary logs the error |
| Retention purge deletes only processed+old rows | real `DatabaseStatsStorage` on in-memory DB (Phase-1 semantics, re-verified through the coordinator path) |
| `0 = keep forever` skips purge | `retentionDays=0` → `purgeProcessed` never called (mock assert) |
| Purge goes through each storage's own datasource | two storages with different `dataSource` names; each provider sees the DELETE (mock provider or two in-memory sources) |
| Rescheduling uses the **current** interval | run handler with interval X → next queued task `delayedUntil ≈ now + X`; change mockConfigManager value; next run reschedules with the new value |
| Reschedule happens before work | handler whose work raises → a next-cycle task still exists in `queueService.delayedActionsQueue` |
| Stats-disabled seeds nothing | `initialize` never called → `QueueService.tasksHandlers` has no `STATS_AGGREGATION` entry and the queue is empty (unit-level mirror of the main.py gate) |
| Late-event correctness | **already covered** by `testMultiplePeriods` / `testTimestampNormalization` ([§2.7](#27-existing-test-coverage-already-locking-adjacent-behavior)) — cite, don't duplicate |
| Refactor parity | **already covered** by the 70-row migration test — cite, don't duplicate |

**Docs sync:** `docs/llm/services.md` (new `StatsAggregationService` section),
`docs/llm/configuration.md` `[stats]` table (two keys) **and** update the §[stats]
note that says "Disabled by default until aggregation trigger and query API are
implemented" (aggregation trigger now exists; query API still pending),
`docs/llm/architecture.md` stats-pipeline note (same stale sentence at its line
~421), `docs/llm/index.md` services listing, `docs/llm/libraries.md` §9 (trigger
note), `CHANGELOG.md` `Added` under `## [Unreleased]` (e.g. "Periodic stats
aggregation and event retention now run hourly when `[stats] enabled = true`;
configurable via `aggregation-interval-seconds` / `events-retention-days`").

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
| Stats-off silence | no handler registered / no task seeded when `initialize` not called | Phase 2 |
| Config print | `./venv/bin/python3 main.py --print-config --config-dir configs/00-defaults …` shows the new keys | Phase 2 |

No live/operator smoke gate: the feature is default-off telemetry; the suite plus
the parity lock is the safety net (same stance as stats-collecting-v1 §8).

---

## 8. Risk register + rollback

| # | Risk | Likelihood | Impact | Mitigation | Rollback |
|---|---|---|---|---|---|
| R1 | **Non-transactional aggregation (accepted gap)** — claim → upsert → mark-processed is not one transaction (TODO at stats_storage.py:232); a crash mid-batch leaves claimed rows that orphan-reclaim re-processes → **double-counted buckets** | Low | Med | **Accepted by decision** (2026-08-17). Bounded exposure: batches ≤ 1000 events; worst case one batch double-counted per crash; hourly cadence; aggregates are approximate telemetry, not billing. Orphan reclaim (stats_storage.py:176) prevents permanent stalls. A transactional batch API on `BaseSQLProvider` is an explicit **future follow-up (NG1)**, not a blocker | n/a (pre-existing); long-term fix = provider transaction primitive |
| R2 | **Orphan timeout vs batch runtime** — a claimed-but-unfinished batch is eligible for reclaim after `orphanTimeoutSeconds` (default 3600, fixed — not tied to the interval). If a process freeze/very slow cycle holds a claim > 1 h, the next cycle reclaims and re-processes it (same double-count as R1). Conversely, cycles cannot overlap in-process: the delayed loop runs handlers sequentially (service.py:347-418), so a lower `aggregation-interval-seconds` queues cycles rather than running them concurrently | Low | Med | Drain cap (10 rounds) bounds cycle runtime to seconds-minutes; the freeze must exceed the orphan timeout, not the interval, to matter; lowering the interval does **not** lower the reclaim bar. Document; optionally expose the timeout as config later (§9 Q1) | n/a |
| R3 | **Retention deletes needed data** — a predicate bug could purge unprocessed events (permanent loss — events are append-only) | Low | High | `processed = 1` is part of the ABC contract docstring AND pinned by tests (old-unprocessed row survives); count-before-delete makes the summary line an audit trail; default 30 days far exceeds the aggregation lag (≤ 1 h) | Set `events-retention-days = 0` (keep forever) — instant, no code |
| R4 | **Refactor changes truncation bytes** — back-fill buckets and live buckets split or shift | Low | Med | Shared helpers are the *only* truncation code path after D4; the 70-row test independently recomputes every expected byte and must pass unmodified | Revert Phase 1 |
| R5 | **Aggregation behind disabled stats is never seeded** — `[stats] enabled = false` constructs no storages and calls no `initialize`, so nothing aggregates. If an operator enables stats expecting aggregates from a period when stats were off: there are none — **and none were recorded** (disabled stats record nothing either), so there is no silent backlog gap; the first cycle after enabling is the immediate catch-up run | — (by design) | Low | Documented here; D1 ratified no separate flag | n/a |
| R6 | **Delayed-queue head-of-line blocking** — a big drain cycle (10 rounds × 5 storages) delays other delayed tasks on the single loop, including per-minute CRON_JOB handlers | Low | Low | Caps bound the cycle; hourly default cadence; worst-case backlog after long downtime drains over consecutive cycles (10 k events/storage/cycle) | Raise `aggregation-interval-seconds` |
| R7 | **Non-default datasources** — an operator pointing an event's `*-stats-data-source` at a source without migration 016/028 tables gets purge/aggregate errors | Low | Med | Per-storage try/except isolates to that storage; same precondition as recording today (stats-collecting-v1 §9 "Multi data-source mismatch"); the summary line names the failing storage | Keep `*-stats-data-source = "default"` |
| R8 | **Config caveat** — interval/retention changes need a restart today (no ConfigManager reload, NG4) | — | Low | Per-cycle read is future-proof; documented | n/a |

**Rollback principle:** the whole feature is gated on `[stats] enabled = false`
(default) — disabling stats removes recording *and* the aggregation task in one
flag. Each phase is independently revertible via git; migration 028's `down()`
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
  section (`StatsAggregationService`, the STATS_AGGREGATION task, retention).
- [`docs/llm/libraries.md`](../llm/libraries.md) §9 — `StatsStorage.purgeProcessed`;
  note that a production `aggregate()` caller now exists.
- [`docs/llm/database.md`](../llm/database.md) — migration 028 in the version list;
  retention-index note on the stat tables.
- [`docs/llm/architecture.md`](../llm/architecture.md) — stats pipeline section:
  add the aggregation/retention loop; fix the stale "disabled until aggregation
  trigger" sentence.
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
- DB backend: [`internal/database/stats_storage.py`](../../internal/database/stats_storage.py)
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
