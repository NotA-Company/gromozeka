## Short Verdict

Good direction, but I would **not implement this plan as-is**.

The core idea is solid: `lib/stats` as a storage-neutral interface, DB-backed implementation under `internal/database`, append-only raw events, and materialized aggregate buckets. That fits the repo’s `lib/` vs `internal/` boundary and the existing database/provider architecture.

But the v2 plan has several correctness and product-scope gaps that are worth fixing before implementation. The biggest ones:

1. **Crash after aggregate upsert but before marking events processed can double-count stats.**
2. **The stated requirements include global totals and “which model was used”, but the schema/aggregation path does not actually support them well.**
3. **Timestamp handling assumes DB rows return `datetime`, but this provider layer stores datetimes as ISO strings.**
4. **Stats recording is on the LLM hot path and must be best-effort/non-fatal.**
5. **`stats.enabled = true` while aggregation trigger/query API are deferred means we may collect unbounded raw data without a usable feature.**

So: **yes, we should build this if LLM usage/cost observability is a real near-term need. But we should narrow and harden the plan first.**

## What Looks Good

- **Migration number 016 is right.** Current highest migration is 015 (`version: int = 15`) in `migration_015_add_divination_layouts_table.py:39-41`.
- **The `lib/` / `internal/` split is correct.** `lib/stats` stays reusable; the DB implementation depends on `internal.database`, similar to `GenericDatabaseCache`, which wraps `Database` and uses internal repositories/providers (`internal/database/generic_cache.py:20-24`, `internal/database/generic_cache.py:54-83`).
- **Using provider APIs is the right direction.** The repo requires provider-based DB access and portable upserts (`AGENTS.md:116-122`), and `BaseSQLProvider.upsert()` already exists (`internal/database/providers/base.py:303-328`).
- **Wiring through `LLMManager` is plausible.** `main.py` currently creates `Database` before `LLMManager` (`main.py:42-47`), so injecting stats storage into `LLMManager` at construction time is clean.

## Blocking Improvements I’d Make

### 1. Fix exactly-once aggregation semantics

The current flow is:

1. claim rows,
2. read rows,
3. increment `stat_aggregates`,
4. mark events processed (`docs/plans/lib-stats-stats-library-v2.md:91-95`).

The plan handles “crash after claim before read” and similar cases (`docs/plans/lib-stats-stats-library-v2.md:1102-1104`), but it misses the dangerous case:

> crash after aggregate rows were incremented, before `stat_events.processed = 1`

On the next run, those claimed rows become stale, are reclaimed, and get added again. That double-counts.

This is made worse by the plan’s default of separate `stats_log` and `stats_agg` data sources (`docs/plans/lib-stats-stats-library-v2.md:687-697`). `DatabaseManager` caches providers by provider name (`internal/database/manager.py:166-170`), so `stats_log` and `stats_agg` are separate provider instances even if they point to the same file. You do not have a transaction boundary across them.

**Recommended fix for v1:**

- Default to **one data source**, e.g. `stats`, not `stats_log` + `stats_agg`.
- Do not advertise split log/aggregate DBs until idempotency is solved.
- Add either:
  - a provider-level batch upsert / transaction primitive, or
  - an idempotency ledger such as `stat_aggregate_contributions`, or
  - recompute-and-set aggregates for affected buckets instead of incrementing.

The simplest good-enough MVP: one `stats` provider + `upsertMany()`/transactional batch API so “apply aggregate increments + mark processed” commits atomically.

### 2. Add dimensions/labels now, or you won’t answer “which model was used”

The problem statement says you want to know “which models were used” (`docs/plans/lib-stats-stats-library-v2.md:15`). But the proposed aggregate key is only:

```text
event_type, consumer_id, period_start, period_type, metric_key
```

from `stat_aggregates` (`docs/plans/lib-stats-stats-library-v2.md:133-142`).

That can count tokens per chat, but it cannot cleanly slice by:

- model name,
- provider,
- generation type,
- fallback vs primary,
- status/error class.

Encoding all of that into `metric_key` will become ugly fast.

**Recommended schema adjustment before migration lands:**

Add a small generic dimension layer:

```sql
labels_hash TEXT NOT NULL,
labels      TEXT NOT NULL, -- canonical JSON, e.g. {"model":"gpt-4o","provider":"openrouter","generationType":"text"}
```

Then make aggregate PK include `labels_hash`:

```sql
PRIMARY KEY (
    event_type,
    consumer_id,
    period_start,
    period_type,
    labels_hash,
    metric_key
)
```

And change the API to:

```python
record(
    consumerId: str,
    stats: dict[str, float | int],
    *,
    labels: Optional[dict[str, str]] = None,
    eventTime: Optional[datetime] = None,
)
```

For LLM events, labels should include at least:

- `modelName` or configured model key,
- `modelId`,
- `provider`,
- `generationType`.

`AbstractModel.getInfo()` already exposes provider/model metadata (`lib/ai/abstract.py:484-530`), and token fields are already present on `ModelRunResult` (`lib/ai/models.py:841-887`).

### 3. Actually implement global/all-time stats

The plan says stats must be aggregateable hourly/daily/monthly/global (`docs/plans/lib-stats-stats-library-v2.md:20`) and sliceable per consumer and globally (`docs/plans/lib-stats-stats-library-v2.md:21`).

But `_computePeriods()` only returns hourly, daily, monthly (`docs/plans/lib-stats-stats-library-v2.md:611-631`). It does not return `total`.

Also, recording `consumerId=str(chatId)` only produces per-chat rows. It does not produce a global rollup unless `consumerId` is missing and becomes `"global"` (`docs/plans/lib-stats-stats-library-v2.md:810-813`).

**Recommended fix:**

- Add a reserved constant, e.g. `GLOBAL_CONSUMER_ID = "__global__"`.
- During aggregation, for each event, aggregate into:
  - its real `consumerId`,
  - `GLOBAL_CONSUMER_ID`.
- Add `period_type = "total"` with a fixed `period_start`, e.g. `"1970-01-01T00:00:00+00:00"`.

### 4. Fix timestamp assumptions

The planned code says:

```python
eventTime = event["event_time"]  # already a datetime from the driver
```

(`docs/plans/lib-stats-stats-library-v2.md:562`)

That is not safe in this codebase. The provider utility converts `datetime.datetime` to ISO strings before binding (`internal/database/providers/utils.py:48-49`), and SQLite results are returned as plain row dicts without timestamp parsing (`internal/database/providers/sqlite3.py:193-230`).

**Recommended fix:**

- Treat DB timestamps as `str | datetime`.
- Add a helper like `normalizeDatetime(value) -> datetime.datetime`.
- Normalize to UTC before truncating.
- If you intentionally store ISO strings for `period_start`, make the migration column `TEXT NOT NULL`, not `TIMESTAMP NOT NULL`. The plan itself says ISO strings are chosen to avoid RDBMS timestamp truncation differences (`docs/plans/lib-stats-stats-library-v2.md:673-678`), so the schema should reflect that.

### 5. Make stats recording best-effort

Right now the plan awaits `statsStorage.record()` from `AbstractModel` after each attempt (`docs/plans/lib-stats-stats-library-v2.md:809-822`). If that insert raises because the stats DB is locked/misconfigured, a successful LLM call could fail user-visible behavior.

That is not acceptable for observability.

**Recommended fix:**

- Either `record()` catches/logs and never raises, or `_recordStats()` wraps it.
- Consider returning `bool` from `record()` if callers/tests care.
- Do not let stats failure affect LLM response flow.
- Validate metrics at `record()` time: numeric only, finite values only.

Also, avoid this planned dynamic SQL:

```python
"metric_value": f"metric_value + {total}",
```

(`docs/plans/lib-stats-stats-library-v2.md:590-593`)

Use a parameterized expression if supported, or add a provider-supported additive expression helper. Dynamic numeric SQL is still unnecessary risk and can break on `nan`/`inf`.

### 6. Respect the repo’s SQL portability rules more strictly

The plan hardcodes `LIMIT :limit` inside the claim subquery (`docs/plans/lib-stats-stats-library-v2.md:526-537`). The project rule says to use provider hooks for pagination and “never append `LIMIT … OFFSET …` yourself” (`AGENTS.md:123-126`). `BaseSQLProvider.applyPagination()` exists for this (`internal/database/providers/base.py:342-357`).

Even if `LIMIT` inside a subquery works on SQLite/PostgreSQL/MySQL, the plan should be aligned with repo rules:

```python
innerQuery = logProvider.applyPagination(
    """
    SELECT event_id
    FROM stat_events
    WHERE processed = 0
      AND (processed_id IS NULL OR claimed_at < :orphanTimeout)
    ORDER BY event_time
    """,
    limit=limit,
)
```

Then embed that provider-generated select in the update.

### 7. Don’t default-enable collection without trigger/query/retention

The plan adds:

```toml
[stats]
enabled = true
```

(`docs/plans/lib-stats-stats-library-v2.md:712-718`)

But aggregation trigger, message stats, and query API are deferred (`docs/plans/lib-stats-stats-library-v2.md:1069-1081`). That means production starts writing raw stats, but nothing periodically aggregates them and no API reads them.

**Recommended fix:**

Pick one:

- **Option A:** Add minimal aggregation trigger + minimal query API in this plan.
- **Option B:** Keep `enabled = false` by default until those exist.

I’d choose Option A if the goal is real observability. Otherwise, this feature is mostly plumbing.

### 8. Add missing config getter or change the wiring example

The plan’s `main.py` snippet calls:

```python
self.configManager.getStatsConfig()
```

(`docs/plans/lib-stats-stats-library-v2.md:918`)

`ConfigManager` currently has getters for bot/database/models/storage/etc. but no stats getter (`internal/config/manager.py:285-480`). The config guide says adding config should include a getter (`docs/llm/configuration.md:309-321`).

So either:

- add `getStatsConfig()`, or
- use `self.configManager.get("stats", {})`.

I’d add the getter for consistency.

### 9. Rename the DB-backed class

The plan has:

```python
from lib.stats.stats_storage import StatsStorage

class StatsStorage(StatsStorage):
```

(`docs/plans/lib-stats-stats-library-v2.md:385-394`)

That is confusing at best and may upset lint/type tooling. Use:

```python
from lib.stats.stats_storage import StatsStorage as BaseStatsStorage

class DatabaseStatsStorage(BaseStatsStorage):
    ...
```

Then import `DatabaseStatsStorage` in `main.py`.

## Suggested Revised MVP

I’d revise the plan to this smaller but stronger MVP:

1. **Migration 016**
   - `stat_events`
   - `stat_aggregates`
   - include `labels_hash` + `labels`
   - use `period_start TEXT NOT NULL` if storing ISO strings
   - add `period_type = "total"` support
   - add indexes for:
     - claim scanning,
     - `processed_id`,
     - aggregate lookup.

2. **`lib/stats`**
   - `StatsStorage.record(consumerId, stats, labels=None, eventTime=None)`
   - `aggregate(...)`
   - minimal `getAggregates(...)` query API.
   - `NullStatsStorage`.

3. **`internal/database/stats_storage.py`**
   - `DatabaseStatsStorage`
   - one default `dataSource="stats"`
   - best-effort `record()`
   - robust timestamp parsing
   - global rollup and total bucket
   - no split log/agg data source until idempotency is solved.

4. **LLM integration**
   - record **attempt-level** metrics:
     - `attempt_count`
     - `input_tokens`
     - `output_tokens`
     - `total_tokens`
     - `error_count`
     - `fallback_attempt_count`
   - labels:
     - `modelName`
     - `modelId`
     - `provider`
     - `generationType`.

5. **Minimal trigger**
   - Either use existing delayed/cron task infrastructure, or explicitly document manual aggregation and keep `enabled=false`.

6. **Tests**
   - timestamp string parsing,
   - global rollup,
   - total bucket,
   - model labels,
   - stats failure does not break LLM call,
   - crash/retry/idempotency scenario,
   - disabled config uses `NullStatsStorage`.
   - Avoid `@pytest.mark.asyncio`; repo uses `asyncio_mode = "auto"` (`docs/llm/testing.md:81-87`).

## Should We Build It?

**Yes, if you want operational answers like:**

- Which models are costing us tokens?
- Which chats/users generate the most LLM load?
- How often do fallbacks happen?
- Are errors/provider failures increasing?
- How does usage trend hourly/daily/monthly?

But I would **not** build the fully generic “future stats for everything” system until the LLM use case is proven. Start with LLM stats, keep the storage generic enough, and avoid over-designing query/reporting for hypothetical future domains.

So my recommendation is:

> **Proceed, but revise the plan first. Treat the current v2 as a good draft, not implementation-ready.**