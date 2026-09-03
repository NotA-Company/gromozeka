# Design: `GenericDatabaseCache` → `lib/cache/sql_cache.py` + `clearOld` on `CacheInterface` (v1)

**Date**: 2026-08-24
**Status**: **IMPLEMENTED — all phases landed** (code `c1ac3395`, docs `2bb9b2fb`). All decisions (D1–D15) user-ratified 2026-08-24. See ADR-024.
**Owner**: TBD
**Scope**: Extract `internal/database/generic_cache.py`
(`GenericDatabaseCache`, 161 lines) to `lib/cache/sql_cache.py` (path in backticks: does not exist
today) following the ADR-023 house pattern — `git mv` + tight dependency-cut overlay
(`manager=`/`namespace: str`), ALL `cache`-table SQL owned inline by the lib class. In the same
arc, `CacheInterface` ([`lib/cache/interface.py`](../../lib/cache/interface.py)) gains a new
abstract method `clearOld(ttl)` implemented by all three in-repo implementors;
`CacheRepository` shrinks to the `cache_storage` trio (its live and only remaining duty);
`HandlersManager`'s weekly cleanup rewires to per-namespace instance sweeps. Big-bang, no
re-export shim. Closes the last ABC-in-lib / impl-in-internal split flagged by the ADR-022
follow-up audit and realizes the clause in ADR-023 that said the utils move "unblocks the parked
`lib/cache` `GenericDatabaseCache` extraction".

> This is a **design document**, not an implementation. Every `file:line` claim below was
> verified against source on 2026-08-24 with fresh reads and greps (patterns:
> `GenericDatabaseCache`, `CacheInterface`, `getCacheStorage|setCacheStorage|unsetCacheStorage`,
> `clearOldCacheEntries|clearCacheEntries`, `class CacheType`, `\.cache\.`). Paths that do not
> exist today appear only in backticks/code fences
> ([`scripts/check_docs.py`](../../scripts/check_docs.py) skips those — mechanics verified in the
> lib-db design doc §2.5).

> **User-ratified modifications (2026-08-24, recorded verbatim intent).** The architect proposal
> of the same day recommended a classmethod sweep and an `internal`-side rewire; the user
> OVERRODE both, plus confirmed three other items. These are encoded as decisions D5–D7 and
> D13–D14 below and are **user decisions, not architect recommendations**:
> 1. `clearOld` is an **instance method on the ABC** (`CacheInterface`), scoped to the
>    instance's own namespace + `dataSource` — not a classmethod on the SQL class.
> 2. The weekly default cross-namespace sweep **loops via transient instances** over
>    `CacheType` members (~8 cheap weekly queries replace 1).
> 3. Inline SQL "just like stats storage"; the repository keeps the `cache_storage` trio and
>    **keeps the name `CacheRepository` / `db.cache`** (no rename).
> 4. The pre-existing `benchmark_queries.py:99` bug is fixed in Arc 1 (benchmark rider).
> 5. ADR-023's body stays untouched; ADR-024 records the realization.

---

## 1. Context and goal

ADR-022 moved the SQL provider layer and `DatabaseManager` to `lib/db/`; ADR-023 followed with
the decode utilities (`lib/db/utils.py`) and `DatabaseStatsStorage` → `lib/stats/sql_storage.py`,
explicitly naming this extraction as unblocked
([`docs/llm/architecture.md`](../llm/architecture.md):869-870). What remains split today:
`CacheInterface` ([`lib/cache/interface.py`](../../lib/cache/interface.py)) is bot-free, but its
only SQL-backed implementation, `GenericDatabaseCache`, lives in
`internal/database/generic_cache.py` because it goes
through the `Database` wrapper and the `db.cache` repository
([`internal/database/repositories/cache.py`](../../internal/database/repositories/cache.py)).

**Motivation, stated plainly:** nothing in `lib/` needs a SQL cache today — lib clients
(`lib/yandex_search`, `lib/geocode_maps`, `lib/openweathermap`) accept `CacheInterface` via DI
and default to `NullCache`/`DictCache`. This extraction is **pattern hygiene**, not unblocking:
it closes the last ABC-in-lib / impl-in-internal split (ADR-022 §follow-ups audit verdict,
[`docs/llm/teamlead-memory.md`](../llm/teamlead-memory.md):130), and lets lib packages grow
SQL-backed caching later without handlers pre-wiring internal classes.

**Goal in one paragraph:** git-mv `GenericDatabaseCache` to `lib/cache/sql_cache.py` with
constructor `(manager: DatabaseManager, namespace: str, …)` and the `cache`-table SQL owned
inline (get/set/clear ported verbatim from the repository quartet); add
`clearOld(ttl) -> bool` to `CacheInterface` and implement it in `GenericDatabaseCache` (SQL port
of `clearOldCacheEntries`, scoped to the instance namespace), `DictCache` (in-memory age purge),
and `NullCache` (no-op `True`); shrink `CacheRepository` to the live `cache_storage` trio;
rewire the two handler construction sites and the `HandlersManager` weekly cleanup to instance
sweeps; then land ADR-024 and the documentation sync. Old method bodies die in the same commit
their replacements land; `make check-docs` green at every commit; one commit per green arc.

### 1.1 Goals

- **G1** — `lib/cache` gains its SQL implementation; `internal/database/generic_cache.py` is
  deleted; the ABC-in-lib / impl-in-internal split for caches is gone.
- **G2** — Single ownership of `cache`-table SQL: the lib class owns ALL of it (get/set/clear +
  the TTL sweep). `CacheRepository` keeps exactly the `cache_storage` trio, which is
  `CacheService`'s live persistence backing (verified — §2.4).
- **G3** — `CacheInterface` gains `clearOld(ttl)` with a precisely documented contract; all
  three in-repo implementors provide it; ABC-conformance tests exist for each.
- **G4** — Behavior-preserving where touched: SQL text ported verbatim (including the
  `ttl <= 0 → None` early-return in `get` and the `None → 0` TTL normalization in the sweep);
  no schema, migration, or config change; `make check-docs` green at every commit.

### 1.2 Non-goals

- **NG1** — No renaming of `CacheRepository` / `db.cache` (user decision — zero churn default;
  the trio-only residue is honest enough).
- **NG2** — No move of the `cache_storage` trio, `CacheService`, `CacheType`
  (stays in [`internal/database/models.py`](../../internal/database/models.py) — it is bot-layer
  vocabulary), the `Database` wrapper, or migrations (tables stay owned by migration_004 /
  migration_012).
- **NG3** — No per-method `dataSource` migration: the constructor-level `dataSource` pattern is
  kept as-is (it is a documented third convention — dataSource-convention memory — and the stats
  precedent kept its constructor-level form too).
- **NG4** — No CHANGELOG entry (internal refactor, no user-visible change — AGENTS.md skip
  criteria; same call as ADR-022/023).
- **NG5** — No change to the `cache_storage` persistence semantics of `CacheService`
  (load/persist/flush paths untouched).

---

## 2. Verified grounding

### 2.1 `GenericDatabaseCache` inventory (161 lines, fully read)

`CacheInterface[K, V]` implementation. Internal imports exactly two:
`from .database import Database` (:14) and `from .models import CacheType` (:15); everything
else is already lib-side (`lib.cache`). Constructor
`(db: Database, namespace: CacheType, keyGenerator=None, valueConverter=None, *, dataSource=None)`
with `__slots__ = ("db", "dataSource", "namespace", "keyGenerator", "valueConverter")` (:54).
The constructor performs **no I/O** — provider access is per-call lazy — so transient instances
for the weekly sweep are cheap to construct. Methods `get`/`set`/`clear`/`getStats`; ALL DB
access via `self.db.cache.{getCacheEntry(:99), setCacheEntry(:123), clearCache(:137)}` —
repository pattern, zero direct SQL, zero decode-trio usage (row→dict decoding lives in the
repository; `valueConverter.decode` handles payload data). `getStats` returns
`self.namespace.value` (:157) — must become the plain string when the type widens to `str`
(pyright-enforced).

### 2.2 `CacheRepository` surface (375 lines, fully read) and its fate

Seven methods, `BaseRepository(manager)` subclass:

| Method | Lines | Table | Fate |
|---|---|---|---|
| `getCacheStorage` | :69-96 | `cache_storage` | **STAYS** (trio) |
| `setCacheStorage` | :98-141 | `cache_storage` | **STAYS** (trio) |
| `unsetCacheStorage` | :143-180 | `cache_storage` | **STAYS** (trio) |
| `getCacheEntry` | :182-242 | `cache` | **DIES** — SQL ports into lib `get` (incl. the `ttl is not None and ttl <= 0 → return None` early-return :215-216 and the `(:minimalUpdatedAt IS NULL OR updated_at >= :minimalUpdatedAt)` predicate :230) |
| `setCacheEntry` | :244-290 | `cache` | **DIES** — SQL ports into lib `set` (`provider.upsert` + `ExcludedValue` on `data`/`updated_at`, `created_at`/`updated_at` set in app code :271-286) |
| `clearCache` | :292-320 | `cache` | **DIES** — SQL ports into lib `clear` (DELETE by namespace :311-318) |
| `clearOldCacheEntries` | :322-375 | `cache` | **DIES** — SQL ports into lib `clearOld` (instance-scoped; see D5/D6), incl. `if ttl is None: ttl = 0` normalization :351-352, cutoff `now - ttl`, `updated_at < :cutoffTime` :358-369, returns `False` only on exception :373-375 |

Post-move residue: imports shrink (`CacheDict`, `CacheType`, `datetime` drop; `dbUtils` keeps
`getCurrentTimestamp` ×1 + `sqlToTypedDict` ×1; `ExcludedValue` stays for the trio upsert).
`CacheDict` (models.py:380) has **no other consumer** (grep-verified: only repositories/cache.py
:28,189,239) → deleted; the lib module defines a local row TypedDict instead (stats precedent:
`StatsEventDict` local to `lib/stats/sql_storage.py`:32).

Tables and ownership (unchanged): `cache_storage` (migration_004, PK `(namespace, key)`),
`cache` (migration_012 unified, PK `(namespace, key)`, `idx_cache_updated_at` for TTL cleanup).
Migrations keep owning the DDL.

### 2.3 Quartet + sweep consumers (closed)

1. `GenericDatabaseCache` — the only get/set/clear consumer (§2.1).
2. [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py):726,729
   — `_cleanupOldData` (weekly cron via `_dtCronJob` :671-693): line 726 is the default sweep
   `clearOldCacheEntries(ttl=CACHE_CLEANUP_DEFAULT_TTL_SECS)` with `cacheType=None`
   (all namespaces, 365-day floor — constant :95); lines 728-729 loop
   `AGGRESSIVE_CLEANUP_CACHE_TYPES` (:101-106, `Tuple[CacheType, ...]`, 4 members) with the
   7-day TTL (:96). `CacheType` is already imported (:61) and `Tuple` already imported — the
   rewire adds only the lib import.
3. Tests hitting the quartet directly:
   [`tests/database/repositories/test_cache_repository.py`](../../tests/database/repositories/test_cache_repository.py)
   (355 lines; `TestCacheStorage` 4 tests, `TestCacheEntry` 5, `TestCacheDataTypes` 4
   [2 storage + 2 entry], `TestClearOldCacheEntries` 5) and
   [`tests/integration/test_database_operations.py`](../../tests/integration/test_database_operations.py):862-885
   (`testCacheEntryOperations`) — :889-915 (`testCacheStorageOperations`, trio) stays.
   [`tests/database/performance/benchmark_queries.py`](../../tests/database/performance/benchmark_queries.py):47-65,89-109
   exercises the quartet AND :99 calls `repo.clearCacheEntries()` — a method that **exists
   nowhere** (grep-verified; pre-existing drift, D13 rider).

### 2.4 The closed census gap: the `cache_storage` trio is LIVE

An earlier exploration claim ("CacheService does not use `db.cache`") was **half-wrong** and is
corrected here: `CacheService` does not use the cache quartet (its hot path is in-memory
LRUs + `chatSettings`/`chatInfo` repositories), but it is the **sole production consumer of the
trio** — the `cache_storage` table is its save-on-write / load-on-startup / flush-on-exit
persistence store:

- [`internal/services/cache/service.py`](../../internal/services/cache/service.py):1489 —
  `unsetCacheStorage(namespace, str(key))` in the flush path (drops DB rows whose memory value
  vanished);
- :1519 — `getCacheStorage()` in `loadFromDatabase()` (startup load);
- :1594 — `setCacheStorage(namespace=…, key=…, value=…)` in `_persistCacheEntry`.

Test-side trio coverage (all stays, no churn):
[`tests/database/test_db_wrapper.py`](../../tests/database/test_db_wrapper.py):982-1020,1844-1847,
[`tests/database/integration/test_multi_source_routing.py`](../../tests/database/integration/test_multi_source_routing.py):171-248,
[`tests/services/cache/test_cache_service.py`](../../tests/services/cache/test_cache_service.py)
(mocks), benchmark_queries.py:68-87. **Conclusion:** none of the trio is dead; the repository's
post-move residue is a live, coherent persistence repository — a further argument for keeping its
name (D4).

### 2.5 `CacheType`, `Database.manager`, construction census

- **`CacheType` is a `StrEnum`** (models.py:406) with exactly 8 members (:409-426):
  `WEATHER`, `GEOCODING`, `YANDEX_SEARCH`, `URL_CONTENT`, `URL_CONTENT_CONDENSED`, `GM_SEARCH`,
  `GM_REVERSE`, `GM_LOOKUP`. `CacheType.X` IS a `str` → `namespace: str` accepts enum members
  unchanged; zero call-site churn; the type merely widens.
- **`Database.manager` is public** ([`internal/database/database.py`](../../internal/database/database.py):225,
  `self.manager = DatabaseManager(config)`); `db.cache = CacheRepository(self.manager)` at :256.
  Handlers/HandlersManager reach the manager with a one-token change per site.
- **Construction census — 8 sites in 2 handlers** (all pass a positional `Database`):
  [`internal/bot/common/handlers/weather.py`](../../internal/bot/common/handlers/weather.py):88,94,121,127,133
  (imports :27) and
  [`internal/bot/common/handlers/yandex_search.py`](../../internal/bot/common/handlers/yandex_search.py):123,241,247
  (imports :46). Nothing else imports `GenericDatabaseCache` — not even
  `internal/database/__init__.py` (its `__all__` is only `Database`, `ParametrizedQuery`).
  **No direct unit tests exist for the class today** (grep-verified).

### 2.6 `CacheInterface` shape and implementor census (for the ABC change)

Current ABC ([`lib/cache/interface.py`](../../lib/cache/interface.py)): four abstract methods —
`get(key, ttl=None)` :43, `set(key, value) -> bool` :71, `clear()` :94, `getStats()` :112.

**Implementor census (grep `CacheInterface`, all matches inspected): exactly 3 classes subclass
it, all in-repo:**

| Implementor | Site | Notes |
|---|---|---|
| `DictCache` | [`lib/cache/dict_cache.py`](../../lib/cache/dict_cache.py):41 | Entries are `(value, timestamp)` tuples in `Dict[str, Tuple[V, float]]` (:81); timestamp = `time.time()` at `set` (:210); `_isExpired(timestamp, ttl)` (:92-107) special-cases `ttl == 0 → always expired` and `ttl < 0 → never` (**get-semantics — must NOT be reused for `clearOld`**, see D9); `_cleanupExpired` (:109-124) and all mutations under `threading.RLock` (:89) |
| `NullCache` | [`lib/cache/null_cache.py`](../../lib/cache/null_cache.py):15 | `get → None`, `set → True`, `clear → pass`, `getStats → {"enabled": False}` |
| `GenericDatabaseCache` | `internal/database/generic_cache.py`:20 | This design's subject |

All other 46 grep hits are **type-only DI references** (constructor params / annotations), not
implementors: `lib/openweathermap/client.py`:105-106,135-138,
`lib/yandex_search/client.py`:115,178, `lib/geocode_maps/client.py`:123-125,151-157,
`lib/aurumentation/types.py`:43, plus tests. Adding an abstract method breaks **no in-repo
code** once the three implementors gain it in the same arc; DI consumers are unaffected (they
never subclass). See D11 for the external-implementor risk call.

Test fixtures available for the new coverage:
[`tests/lib/cache/conftest.py`](../../tests/lib/cache/conftest.py) provides a fake-clock context
manager (imported at `test_integration.py`:32, used by `test_dict_cache.py`:658) — reusable for
`DictCache.clearOld` age-purge tests.

### 2.7 Pre-existing drift found during census (fixed by this effort / flagged)

1. [`docs/llm/database.md`](../llm/database.md):389 — claims `CacheType` is "used by
   `CacheService` for hot-path access". **False**: CacheService uses its own `CacheNamespace`
   (service.py:1543-1546). Fixed in Arc 2 (D14 doc-sync).
2. [`tests/database/performance/benchmark_queries.py`](../../tests/database/performance/benchmark_queries.py):99
   — calls `repo.clearCacheEntries()`, which exists nowhere. The file runs under plain
   `make test` (no deselects in `Makefile` / `pyproject.toml` markers list), so its current
   suite status could not be verified from this doc-only session (no shell) — **the Arc 1
   implementer must confirm the baseline** and the rider fixes it regardless (D13).

### 2.8 Check-docs sweep duties for Arc 1

`generic_cache.py` is deleted at the Arc 1 commit, so any md **links** into it must be swept in
the same arc. Known prose/link touchpoints (implementer greps
`internal/database/generic_cache|internal\.database\.generic_cache`, dotted + slashed):
[`docs/llm/memories/db-cache-cleanup.md`](../llm/memories/db-cache-cleanup.md):10,
[`docs/database-schema.md`](../database-schema.md):146,154,1026,
[`docs/database-schema-llm.md`](../database-schema-llm.md):1218-1286,
[`docs/database-README.md`](../database-README.md):96,625,744,746,
[`docs/developer-guide.md`](../developer-guide.md):215,
[`docs/llm/database.md`](../llm/database.md):333,389. Link-form breakage fails
`make check-docs`; prose accuracy beyond targets is Arc 2/3 work (ADR-023 lesson: check-docs
validates resolution only).

---

## 3. Ratified decisions (D1–D15)

Decisions D5, D6, D7, D13, D14 encode the 2026-08-24 user modifications and are marked
**(user)**; the rest carry the user's blanket ratification of the proposal.

### D1 — Target: `lib/cache/sql_cache.py` via git-mv (user re-affirmed: "just like stats storage")

Mirrors `lib/stats/sql_storage.py` naming; whole-file `git mv` preserves history; tight
dependency-cut overlay applied on top. No re-export shim; `internal/database/generic_cache.py`
is deleted in the same commit (ADR-022/023 precedent; `import main` lint gate + suite as the
net).

### D2 — Class name kept: `GenericDatabaseCache`

Stats kept `DatabaseStatsStorage` despite the "Database" prefix; no name asserts exist in tests;
zero-churn.

### D3 — Constructor: `(manager: DatabaseManager, namespace: str, keyGenerator=None, valueConverter=None, *, dataSource=None)`

`__slots__` swap `db → manager`. `dataSource` stays constructor-level `Optional[str]` (NG3).
`namespace: str` — verified StrEnum passthrough (§2.5); handlers keep passing `CacheType.X`
unchanged. Construction sites change `self.db` → `self.db.manager` (one token per site).
`getStats()` drops `.value` (:157) — pyright enforces; renders identically. The docstring
example loses its `internal.database` imports.

### D4 — Repository fate: lib owns ALL `cache`-table SQL; `CacheRepository` keeps the trio, name kept (user)

The lib class owns `get`/`set`/`clear`/`clearOld` SQL (verbatim ports, §2.2); the repository
shrinks to the `cache_storage` trio — which §2.4 proves is `CacheService`'s live persistence
backing, not residue by accident. Alternatives rejected during proposal: (b) split table
ownership (duplication smell — every future `cache`-table migration touches two trees);
(c) inject a narrow storage Protocol into the lib class (keeps the impl-internal split
half-alive; the protocol would be shape-identical to `CacheInterface`, making the extraction
cosmetic). **Name `CacheRepository` / `db.cache` kept** — user decision, zero churn.

### D5 — `clearOld` is an ABSTRACT INSTANCE method on `CacheInterface` (user; overrides the architect's classmethod proposal)

```python
@abstractmethod
async def clearOld(self, ttl: Optional[int]) -> bool:
    """Delete this cache's entries older than the given TTL.

    Scoped to the instance's own namespace (and data source, where the
    implementation has one). Best-effort: implementation errors are logged
    and reported through the return value, never raised.

    Args:
        ttl: Age threshold in seconds. Entries strictly older than
            ``now - ttl`` are deleted. ``None`` is normalized to ``0``
            (delete every entry of the namespace) — the legacy
            ``clearOldCacheEntries`` semantics, ported verbatim. Negative
            values are not part of the contract (legacy SQL happened to
            delete everything; implementations need not honor them).

    Returns:
        bool: True if the sweep completed successfully — regardless of
        whether any entries matched — False on backend error.
    """
```

The namespace and `dataSource` come from the instance; there is no cross-namespace sweep method
on the ABC (the cross-namespace case is composed by callers looping instances — D7). Return
contract ported from the repository: `True` on success including no-op (pinned today by
`testReturnsTrueOnSuccess`), `False` only on exception, never raises.

> **Deviation note (2026-08-25):** The shipped `clearOld` implements `ttl=0`/`None` as an
> unconditional namespace DELETE, deliberately diverging from the legacy
> `clearOldCacheEntries` behavior (`cutoff = now`, `updated_at < now` — same-instant and
> future-dated rows survived that sweep). Sanctioned by parity item 6(c), D5's normalization
> parenthetical above, and the ADR-024 draft. Rationale: deterministic testability under
> frozen clocks — a just-set entry has age exactly `0.0`, and a strict `age > 0` comparison
> cannot delete it.

### D6 — Method name: `clearOld`

Terse, matches `get`/`set`/`clear`. (`clearOldCacheEntries` was the repository name;
`purgeOld`/`sweep` rejected as less consistent with the existing verb set.)

### D7 — Weekly sweep loops via transient instances (user; overrides the internal-side rewire)

`HandlersManager._cleanupOldData` becomes:

```python
# Purge every known namespace with the default TTL floor first
for member in CacheType:
    await GenericDatabaseCache(self.db.manager, namespace=member).clearOld(CACHE_CLEANUP_DEFAULT_TTL_SECS)
# Then purge fast-staling namespaces with the aggressive TTL
for cacheType in AGGRESSIVE_CLEANUP_CACHE_TYPES:
    await GenericDatabaseCache(self.db.manager, namespace=cacheType).clearOld(CACHE_CLEANUP_AGGRESSIVE_TTL_SECS)
```

Consequences recorded deliberately: ~8 cheap weekly DELETEs replace 1 (weekly cadence,
`idx_cache_updated_at` backs the predicate; transient construction is I/O-free — §2.1);
constants stay where they are (manager.py:95-106); `AGGRESSIVE_CLEANUP_CACHE_TYPES` stays typed
`Tuple[CacheType, ...]` (StrEnum binds as `str`). **Accepted semantic narrowing:** the old
single `cacheType=None` sweep deleted rows in ANY namespace, including stray values outside the
enum; the loop covers exactly the 8 known namespaces. Verified writers are exactly those 8
(§2.5 census), so only legacy pre-migration_012 rows could be affected — see Risks and §8.2.

> **Supersession note (2026-08-25):** landed code (user change, post-ADR-024) collapsed the two passes into a single loop with per-member conditional TTL — aggressive members (WEATHER, YANDEX_SEARCH, URL_CONTENT, URL_CONTENT_CONDENSED) receive the 7-day TTL inline, all others the 365-day floor; 8 `clearOld` calls total. Final DB state provably identical (the 7-day predicate is a strict superset of the 365-day one for aggressive namespaces). See ADR-024's "~8 cheap weekly DELETEs" gloss.

### D8 — `CacheDict` deleted; local row TypedDict in the lib module

Sole consumer is the dying quartet (§2.2). The lib module defines a private `_CacheRowDict`
(`key`/`data`/`created_at`/`updated_at`) — the `StatsEventDict` house pattern. `CacheType`
itself stays in internal models (NG2).

### D9 — `DictCache.clearOld`: direct age comparison, NOT `_isExpired`

`_isExpired` (:92-107) encodes **get-semantics** (`ttl == 0 → always expired`,
`ttl < 0 → never`) which would silently diverge from the SQL sweep. The correct parity
implementation is the direct comparison after the same `None → 0` normalization:

```python
async def clearOld(self, ttl: Optional[int]) -> bool:
    # normalizedTtl: None -> 0, matching the SQL sweep's cutoff semantics
    normalizedTtl = 0 if ttl is None else ttl
    cutoffAge = normalizedTtl  # delete entries with age > cutoffAge seconds
    # under self._lock: delete every (key, (value, timestamp)) where
    # time.time() - timestamp > cutoffAge   (strict >, like SQL's updated_at < now - ttl)
    ...
    return True
```

For any `ttl >= 0` this matches the SQL predicate exactly (both strict); for negative `ttl` both
formulas delete everything (`now - ts > negative` is always true for past timestamps), so
DictCache accidentally-but-correctly matches the legacy SQL behavior there too. Tests pin the
`None → 0` case and the age boundary (fake clock from
[`tests/lib/cache/conftest.py`](../../tests/lib/cache/conftest.py)).

### D10 — `NullCache.clearOld`: no-op returning `True`

Nothing is ever stored, so nothing can be old; `True` matches the success-including-no-op
contract (D5) and the `set → True` house style of NullCache.

### D11 — ABC breaking change accepted

Adding an abstract method breaks any EXTERNAL implementor of `CacheInterface` at instantiation.
Census (§2.6): exactly 3 implementors, all in-repo, all updated in the same arc. Accepted per
repo culture (single application, `lib/` is not a published API); to be noted in ADR-024.

### D12 — Big-bang, no shim

Old file + dying repository methods deleted in the same commit the replacements land. The
`make lint` `import main` cycle gate, the full suite, and residual greps are the net
(ADR-022/023 precedent).

### D13 — Benchmark rider in Arc 1 (user)

`benchmark_queries.py` gets rewired anyway (:47-65, :89-109); the nonexistent
`clearCacheEntries()` call at :99 is fixed in the same arc (→ `clearOld` on a lib instance or
`clear()` — implementer's choice consistent with what the benchmark measures). Implementer
confirms the current suite baseline first (§2.7).

### D14 — ADR-023 body untouched; ADR-024 records the realization (user)

ADR-023's "unblocks the parked `lib/cache` `GenericDatabaseCache` extraction" clause
(architecture.md:869-870) is realized, not superseded — ADR-023 keeps no scope clause this
design contradicts. ADR-024 (§5) says exactly that; no earlier ADR is edited (D9
history-immutability lesson from the ADR-023 round).

### D15 — CHANGELOG skipped

Internal refactor, no user-visible change (AGENTS.md criteria; same call as ADR-022/023).

---

## 4. Phased plan

Per-arc gates: `make format lint`, `make test`, `make check-docs`, plus the residual greps
listed per arc. One commit per green arc, explicit staging excluding `.opencode/memory.jsonl`
(house pattern). The commit agent MUST run `make check-docs` before every commit.

### Phase 0 — this document (THIS ROUND)

Write this file. Gate: `make check-docs` + `make lint`.
Commit: **"Add lib/cache sql_cache extraction design doc"**.

### Arc 1 — CODE: move + ABC + rewire (~10 production + ~7 test files)

| # | File | Change |
|---|---|---|
| 1 | `internal/database/generic_cache.py` | git-mv → `lib/cache/sql_cache.py` + overlay: `manager=`/`namespace: str` (D3), inline SQL `get`/`set`/`clear` (verbatim ports, §2.2), instance `clearOld` (D5), local `_CacheRowDict` (D8), `getStats` `.value` drop, docstring rewrite |
| 2 | `lib/cache/interface.py` | add abstract `clearOld` + contract docstring (D5/D6) |
| 3 | `lib/cache/dict_cache.py` | implement `clearOld` — direct comparison, NOT `_isExpired` (D9) |
| 4 | `lib/cache/null_cache.py` | implement `clearOld` — no-op `True` (D10) |
| 5 | `lib/cache/__init__.py` | export `GenericDatabaseCache` (`__all__` 13 → 14) |
| 6 | `internal/database/repositories/cache.py` | delete quartet (:182-375); import shrink (§2.2) |
| 7 | `internal/database/models.py` | delete `CacheDict` (:380) |
| 8 | `internal/bot/common/handlers/manager.py` | rewire :726-729 to the D7 loops; add lib import (`CacheType`/`Tuple` already imported) |
| 9 | `internal/bot/common/handlers/weather.py` | 5 sites `self.db` → `self.db.manager`; import flip :27 |
| 10 | `internal/bot/common/handlers/yandex_search.py` | 3 sites ditto; import flip :46 |
| 11 | `tests/lib/cache/test_sql_cache.py` | NEW — moved `TestCacheEntry` (5) + `TestClearOldCacheEntries` (5, reshaped to instance semantics) + 2 entry datatype tests from `TestCacheDataTypes` + the parity list below |
| 12 | `tests/database/repositories/test_cache_repository.py` | keep `TestCacheStorage` (4) + 2 storage datatype tests; the 12 quartet tests move to #11 |
| 13 | `tests/integration/test_database_operations.py` | :862-885 reshapes to a `GenericDatabaseCache` over `db.manager`; :889-915 (trio) stays |
| 14 | `tests/database/performance/benchmark_queries.py` | :47-65, :89-109 rewire; :99 rider fix (D13) |
| 15 | `tests/lib/cache/test_dict_cache.py` | `clearOld` coverage: age purge, `None → 0` deletes all, boundary strictness, lock-safety smoke, ABC conformance |
| 16 | `tests/lib/cache/test_null_cache.py` | `clearOld` returns `True`, stores nothing; ABC conformance (extends the existing interface test at :247-262) |
| 17 | `tests/lib/cache/test_integration.py` | light: `GenericDatabaseCache` joins the public-API export test (:52-60); a `clearOld` row in a replacement scenario |

**Parity regression test list** (the moved/reshaped suite must pin; anti-TTL-drift insurance):

1. `set` → `get` round-trip through keyGenerator/valueConverter.
2. TTL hit (`ttl=3600`) / expired (row backdated via provider `UPDATE cache SET updated_at`) → `None`.
3. **`ttl=0` → `None` without querying** — the "impossible future entry" early-return (legacy :215-216; pinned today at test_database_operations.py:884).
4. Namespace isolation: same key in two namespaces returns each namespace's value.
5. `clear()` scoped to the instance's own namespace only.
6. `clearOld` instance semantics ×6: (a) per-namespace sweep deletes only backdated entries of
   THAT namespace; (b) shorter (aggressive) TTL on the same namespace; (c) `clearOld(None)` and
   `clearOld(0)` delete every namespace entry; (d) recent entries survive; (e) `True` on
   success including no-op; (f) `False` + logged (never raised) on provider failure.
7. `getStats` shape: `backend="database"`, namespace as plain `str`, generator/converter class names.
8. **str-subclass namespace acceptance** — a `class FakeNamespace(str)` passed as `namespace`
   (proves StrEnum compatibility without a lib test importing `internal.*`).
9. Constructor `dataSource` routing (two-source `DatabaseManagerConfig`; entries land in the
   named source — lib-side, no internal imports needed).
10. Error-swallow contract: `get → None`, `set → False` on provider failure (mirrors #6f).
11. JSON and special-character values through the converters (moved datatype tests).
12. ABC conformance: `DictCache.clearOld` (D9 semantics incl. negative-ttl parity) and
    `NullCache.clearOld` (D10).

Residual grep gates (Arc 1): `internal\.database\.generic_cache|internal/database/generic_cache`
returns zero outside `docs/archive/`; `getCacheEntry|setCacheEntry|clearOldCacheEntries` returns
zero in production code (test history/docs aside); `clearCacheEntries` returns zero anywhere.

Commit: **"Move GenericDatabaseCache to lib/cache; clearOld on CacheInterface"**.

### Arc 2 — DOCS: ADR-024 + doc sync (~10 files)

Insert ADR-024 (§5) after ADR-023 in [`docs/llm/architecture.md`](../llm/architecture.md) (house
link format on insertion); update:

- [`docs/llm/libraries.md`](../llm/libraries.md) §2 — `lib/cache` table gains the
  `sql_cache.py` row + `clearOld` in the interface description; §9-style impl paragraph pattern
  (the stats §9 :633 paragraph is the model).
- [`docs/llm/index.md`](../llm/index.md) — lib/cache table (:300-301 region) + file-map rows.
- [`docs/llm/database.md`](../llm/database.md) — remove `CacheDict` row (:333); rewrite the
  `CacheType` section (:387-389): drop the dead quartet reference AND fix the pre-existing
  false "used by `CacheService`" claim (§2.7); repository section: cache repo now trio-only.
- [`docs/llm/memories/db-cache-cleanup.md`](../llm/memories/db-cache-cleanup.md):8-14 —
  mechanism rows repoint to the lib class + instance sweeps; the `cache_storage` exemption
  section stays as-is.
- [`docs/database-schema.md`](../database-schema.md) (:146,154,1026) and
  [`docs/database-schema-llm.md`](../database-schema-llm.md) (:1218-1286) — access-path
  examples: quartet examples → `GenericDatabaseCache` / `clearOld`; trio examples unchanged;
  both stay in sync (dual-doc rule).
- [`docs/database-README.md`](../database-README.md) (:96,625,744,746) and
  [`docs/developer-guide.md`](../developer-guide.md) (:215) — path/method references.
- [`docs/design/lib-db-extraction-v1.md`](./lib-db-extraction-v1.md) §8 — closure note on the
  lib/cache audit follow-up (item 4 of its follow-ups list; the ADR-023 round's §8.1 sibling).
- [`docs/llm/teamlead-memory.md`](../llm/teamlead-memory.md) — parked-audit closure line
  (:130 region; mechanical, docs-writer).

Gate: `make lint` + `make check-docs`.
Commit: **"Add ADR-024 and sync docs for GenericDatabaseCache move"**.

### Arc 3 — Gate-2 polish

Confirmatory review pass (Gate-2 pattern from the ADR-023 round): design-doc Status line flips
to IMPLEMENTED with commit hashes (house convention — Gate-2 catch of the stats round);
residual greps re-run; archive-banner / historical-census immutability check (D9 lesson: never
rewrite historical ADR bodies or past census tables); any one-liner fixes land together.
Commit: **"Gate-2 polish: lib/cache extraction"**.

---

## 5. ADR-024 (ready to paste; fenced — convert links on insertion)

```text
### ADR-024: `GenericDatabaseCache` to `lib/cache/sql_cache.py`; `clearOld` joins `CacheInterface`

**Date:** 2026-08-24 (ratified with user modifications; implementation per its design doc arcs)
**Status:** Accepted (realizes the ADR-023 "unblocks lib/cache" clause; supersedes nothing)

**Decision:** `GenericDatabaseCache` moved via git-mv from `internal/database/generic_cache.py`
to `lib/cache/sql_cache.py` (whole-file, no re-export shim; the internal path is deleted) and
now owns ALL `cache`-table SQL inline through a
`DatabaseManager`: constructor changed from `(db: Database, namespace: CacheType, …)` to
`(manager: DatabaseManager, namespace: str, …)` with per-call
`manager.getProvider(dataSource=…, readonly=…)`; the get/set/clear SQL was ported verbatim from
the former `CacheRepository` quartet, including the `ttl <= 0 → None` read early-return.
`CacheInterface` (lib/cache/interface.py) gained the abstract instance method
`clearOld(ttl: Optional[int]) -> bool` — namespace/dataSource come from the instance; `None`
normalizes to `0` (delete all namespace entries); returns True on success including no-op,
False on backend error, never raises — implemented by `GenericDatabaseCache` (SQL port of the
former `clearOldCacheEntries`, cutoff `updated_at < now - ttl`),
`DictCache` (direct age comparison `now - timestamp > ttl` — deliberately NOT the
get-semantics `_isExpired` helper), and `NullCache` (no-op, True). `CacheRepository` shrank to
the `cache_storage` trio — the live `CacheService` persistence backing (load/persist/flush);
its name and the `db.cache` attribute are kept. `CacheDict` was deleted from
internal/database/models.py (sole consumer was the quartet); the lib module keeps a local row
TypedDict (stats `StatsEventDict` pattern). The weekly `HandlersManager._cleanupOldData` sweep
now loops `CacheType` members constructing transient per-namespace instances (~8 cheap weekly
DELETEs replace 1; StrEnum members bind as `namespace: str`); sweep coverage narrows to the 8
known namespaces — accepted, since the verified writer census is exactly those 8. Adding an
abstract method is a breaking change for any external `CacheInterface` implementor — accepted
per single-app repo culture (all three implementors are in-repo and updated in the same arc).

**Why:** closes the last ABC-in-lib / impl-in-internal split flagged by the ADR-022 follow-up
audit and parked in the teamlead memory ("different shape, still blocked on decode trio — which
has NOW landed in lib/db"); ADR-023 explicitly listed this extraction as unblocked by the utils
move. Pure pattern hygiene — no lib package needs a SQL cache today (lib clients default to
DictCache/NullCache via DI); this lets lib packages offer SQL-backed caches later without
internal pre-wiring, and gives every CacheInterface implementation a uniform age-purge verb.

**Realization, not supersession:** ADR-023's body is untouched; its "unblocks the parked
lib/cache GenericDatabaseCache extraction" clause is hereby realized. No earlier ADR scope
clause is contradicted by this move.

Design doc: `docs/design/lib-cache-sql-cache-extraction-v1.md`.
```

> Paste-time checklist (Gate-2 caught the equivalent in the stats round): (1) convert the
> design-doc path to a house link; (2) insert AFTER ADR-023, renumber nothing; (3) update the
> **Status** line to record implementation completion once Arc 1-2 land (house convention).

---

## 6. Risks and gotchas

| Risk | Severity | Mitigation |
|---|---|---|
| TTL semantics drift between old repository SQL and new inline SQL | High | Verbatim ports (§2.2 quotes every predicate); parity list items 2/3/6 pin the exact semantics including `ttl=0 → None` and `None → 0` |
| `DictCache.clearOld` accidentally reuses `_isExpired` (get-semantics: `ttl<0 → never expires` → would NOT match SQL) | High | D9 forbids it with the exact formula; test pins negative-ttl + `None → 0` behavior |
| Sweep coverage narrowing: stray (legacy/enum-external) namespaces never purged by the weekly loop | Low-Med | Writers verified to be exactly the 8 CacheType members (§2.5); accepted consequence (D7); §8.2 offers the one-off manual purge |
| 8 weekly DELETEs replace 1 | Negligible | Weekly cadence; `idx_cache_updated_at` backs the predicate; transient construction is I/O-free (§2.1) |
| ABC break for hypothetical external implementors | Low (accepted) | D11: census found exactly 3 in-repo implementors; single-app culture; noted in ADR-024 |
| Missed rewire site | Med | Residual grep gates (Arc 1) + `import main` cycle gate + full suite; small blast radius (10 production files) |
| `benchmark_queries.py` pre-existing breakage (:99) confuses the Arc 1 baseline | Med | D13 rider fixes it in-arc; implementer MUST capture the pre-arc `make test` result first (§2.7 — this session could not run tests) |
| Dead md links at the Arc 1 commit (`generic_cache.py` deleted) | Med | §2.8 sweep list + `make check-docs` gate; prose accuracy beyond targets is Arc 2 |
| Tests hitting `db.cache` quartet directly fail at Arc 1 | Med | All enumerated (§2.3, Arc 1 table #12-14); trio-only test files verified unaffected (§2.4) |
| Someone later renames the trio-only `CacheRepository` "for honesty" | Low | D4 records the keep-name decision + the §2.4 evidence the trio is live |
| `getStats` `.value` removal changes output | None | `CacheType.X.value == CacheType.X` for StrEnum; pyright enforces the drop |
| Dual ownership of `cache`-table SQL | Eliminated | D4: single owner (the lib class); the repository no longer touches the `cache` table |

---

## 7. Documentation sync map (per the update-project-docs matrix)

- **Arc 1** → md link-target sweep for the deleted `generic_cache.py` (§2.8 list);
  [`docs/llm/libraries.md`](../llm/libraries.md) §2 table + interface description;
  [`docs/llm/index.md`](../llm/index.md) lib/cache rows.
- **Arc 2** → ADR-024 (§5); [`docs/llm/database.md`](../llm/database.md) (CacheDict row :333,
  CacheType section :387-389 + pre-existing-drift fix, repository section);
  [`docs/llm/libraries.md`](../llm/libraries.md) full §2 pass;
  [`docs/llm/index.md`](../llm/index.md) file map;
  [`docs/llm/memories/db-cache-cleanup.md`](../llm/memories/db-cache-cleanup.md) mechanism rows;
  [`docs/database-schema.md`](../database-schema.md) + [`docs/database-schema-llm.md`](../database-schema-llm.md)
  (kept in sync — dual-doc rule); [`docs/database-README.md`](../database-README.md);
  [`docs/developer-guide.md`](../developer-guide.md); lib-db design doc §8 closure note;
  teamlead-memory closure line. Optional check: `docs/llm/testing.md` (only if the moved tests
  change a documented convention — they follow the existing mirror layout, so likely no touch).
- **Arc 3** → this doc's Status line → IMPLEMENTED with commit hashes; final residual greps.
- **No CHANGELOG entry** (D15); no config docs (no config change); no migration docs (no
  migration change; migrations README untouched unless a link grep hits it — include in the
  Arc 1 sweep grep just in case).

---

## 8. Follow-ups (out of scope, tracked here)

1. **lib-db-extraction §8 item 4 (audit lib/cache for the ABC-in-lib/impl-in-internal
   pattern)** — closes when Arc 1 lands; closure note added in Arc 2.
2. **Optional one-off purge of stray `cache`-table namespaces** (rows outside the 8 CacheType
   values, e.g. pre-migration_012 legacy): a single manual
   `DELETE FROM cache WHERE namespace NOT IN (…8 values…)` run by the operator if such rows
   exist. Not code — a deployment note; the weekly loop will never touch them (D7 narrowing).
3. **lib packages adopting SQL-backed caches** (e.g. `lib/yandex_search` offering an optional
   persistent mode): now possible without internal wiring; no concrete plan.
4. **`DictCache` `defaultTtl: int` truncation bug** (pre-existing, flagged in
   test-suite-speedup memory: `defaultTtl=int(0.1)` truncates to 0) — separate decision,
   untouched here.

---

## 9. Open questions

**None.** All decisions were ratified by the user on 2026-08-24, including the five
modifications recorded in the header block (instance `clearOld` on the ABC; loop-based weekly
sweep; inline SQL with the repository name kept; benchmark rider; ADR-023 untouched). They are
encoded as D1–D15. Implementation proceeds arc by arc when scheduled.

---

## 10. References

- [`docs/design/lib-stats-sql-storage-extraction-v1.md`](./lib-stats-sql-storage-extraction-v1.md)
  — house-format template; the ADR-023 precedent this design mirrors
  (git-mv + manager= overlay, local row TypedDict, arc/commit pattern, Gate-2 lessons).
- [`docs/design/lib-db-extraction-v1.md`](./lib-db-extraction-v1.md) — ADR-022 grounding;
  §8 follow-up list (the lib/cache audit this closes).
- [`docs/llm/architecture.md`](../llm/architecture.md) — ADR-023 (:840-877, the "unblocks
  lib/cache" clause :869-870); ADR-024 insertion point after it.
- [`lib/cache/sql_cache.py`](../../lib/cache/sql_cache.py),
  [`internal/database/repositories/cache.py`](../../internal/database/repositories/cache.py),
  [`internal/database/models.py`](../../internal/database/models.py),
  [`internal/database/database.py`](../../internal/database/database.py) — the moved / shrunk /
  edited internals.
- [`lib/cache/interface.py`](../../lib/cache/interface.py),
  [`lib/cache/dict_cache.py`](../../lib/cache/dict_cache.py),
  [`lib/cache/null_cache.py`](../../lib/cache/null_cache.py),
  [`lib/cache/__init__.py`](../../lib/cache/__init__.py) — the ABC change surface.
- [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py)
  (:95-106 constants, :726-729 sweep) — the D7 rewire site;
  [`internal/services/cache/service.py`](../../internal/services/cache/service.py)
  (:1489/:1519/:1594) — the trio consumer that justifies D4.
- [`docs/llm/database.md`](../llm/database.md) (:333, :387-389),
  [`docs/llm/memories/db-cache-cleanup.md`](../llm/memories/db-cache-cleanup.md),
  [`docs/database-schema.md`](../database-schema.md),
  [`docs/database-schema-llm.md`](../database-schema-llm.md) — doc-sync targets (§7).
- [`scripts/check_docs.py`](../../scripts/check_docs.py) — link-gate mechanics (§2.8).
- [`AGENTS.md`](../../AGENTS.md) — hard rules, SQL portability, CHANGELOG skip criteria,
  regression-test rule.
