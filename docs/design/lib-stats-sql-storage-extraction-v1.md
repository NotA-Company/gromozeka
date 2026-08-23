# Design: Decode trio → `lib/db` and `DatabaseStatsStorage` → `lib/stats` (v1)

**Date**: 2026-08-24
**Status**: **Ratified 2026-08-24 — implementation deferred (doc-only round)** — this document is the
only artifact of the round; Arcs 1–3 below await a separate implementation go. All decisions
(D1–D11) user-ratified 2026-08-24, including the S2 decode-trio extraction and ADR-023.
**Owner**: TBD
**Scope**: Two chained extractions. First, move the SQL decode trio (`sqlToTypedDict`,
`sqlToCustomType`, `_checkType` + its private constants) out of
[`internal/database/utils.py`](../../internal/database/utils.py) into a new bot-free
`lib/db` module (decision S2 — supersedes the ADR-022 scope item "internal `utils.py`
survives"). Second, move [`internal/database/stats_storage.py`](../../internal/database/stats_storage.py)
(`DatabaseStatsStorage`, 545 lines) to `lib/stats/` with a `DatabaseManager`-based
constructor. Big-bang cutover per file, no re-export shims (ADR-022 precedent). Also
unblocks the parked `lib/cache` `GenericDatabaseCache` extraction as a follow-up (§9).

> This is a **design document**, not an implementation. Every `file:line` claim below was
> re-verified against source on 2026-08-24 with fresh greps (patterns: `dbUtils\.sqlTo`,
> `sqlToTypedDict|sqlToCustomType`, `getCurrentTimestamp`, `FORCE_SQL_TIMEZONE|_checkType`,
> `internal\.database\.stats_storage`, `from internal\.database\.utils import`). This is the
> D6 follow-up of [`docs/design/lib-db-extraction-v1.md`](./lib-db-extraction-v1.md) (its §8
> item 1). Paths that do not exist today appear only in backticks/code fences
> ([`scripts/check_docs.py`](../../scripts/check_docs.py) skips those — verified mechanics in
> the lib-db doc §2.5).

---

## 1. Context and goal

ADR-022 moved the SQL provider layer and `DatabaseManager` to `lib/db/` explicitly to unblock
this extraction: the `StatsStorage` ABC ([`lib/stats/stats_storage.py`](../../lib/stats/stats_storage.py))
is bot-free, but its only SQL implementation, `DatabaseStatsStorage`, lives in
`internal/database/stats_storage.py` because it needs two internal things — the `Database`
wrapper (for `db.manager.getProvider`) and the decode trio in `internal/database/utils.py`.

The 2026-08-24 ratification resolved the earlier S1-vs-S2 fork **in favor of S2**: instead of
a private narrow decoder inside the storage module, the canonical decode trio itself moves to
`lib/db`. This is a bigger blast radius (~17 production rewire files) but yields a single
canonical implementation, removes the decode-seam parity-test burden entirely (same code
object, new location), and settles the question that had parked the `lib/cache` audit
([`docs/llm/teamlead-memory.md`](../llm/teamlead-memory.md) :130 — "PARKED until the
decode-trio question is settled").

**Goal in one paragraph:** extract the decode trio to `lib/db` (Arc 1), then `git mv`
`DatabaseStatsStorage` to `lib/stats/sql_storage.py` with constructor
`(manager: DatabaseManager, eventType: str, *, dataSource: str)` (Arc 2), then land ADR-023
and the documentation sync (Arc 3). Old locations deleted in the same commit their
replacements land; `make check-docs` green at every commit; one commit per green arc.

### 1.1 Goals

- **G1** — `lib/stats` gains its SQL implementation; `internal/database/stats_storage.py` is
  deleted; the ABC-in-lib / impl-in-internal split for stats is gone.
- **G2** — Behavior-preserving: no SQL text, schema, config, or public-API change. The two
  runtime-observable deltas are (a) decode functions resolve from `lib.db` instead of
  `internal.database.utils`, and (b) `DatabaseStatsStorage` takes `manager=` instead of
  `db=`. Both are type-identical relocations.
- **G3** — `internal/database/utils.py` SURVIVES with `DEFAULT_THREAD_ID` and
  `getCurrentTimestamp` (both have deep internal consumer bases — §2.1); only the trio and
  its private machinery leave.
- **G4** — `make check-docs` green at every commit: Arc 2 carries a mandatory md
  link-target sweep (the stats module file is deleted); Arc 1 needs none (the utils file
  survives, and `check_docs.py` strips `:line` anchors — §2.5).

### 1.2 Non-goals

- **NG1** — No moving of `DEFAULT_THREAD_ID`, `getCurrentTimestamp`, migrations,
  repositories, the `Database` wrapper, or `bayes_storage.py`.
- **NG2** — No `lib/cache` extraction in this effort — listed as a follow-up it unblocks (§9).
- **NG3** — No transactional-batch provider work (separate standing follow-up from the stats
  v3 design; the `TODO` at `internal/database/stats_storage.py:244` rides along unchanged).
- **NG4** — No CHANGELOG entry for either code arc (internal refactor, no user-visible
  change — same call as ADR-022).

---

## 2. Verified grounding

### 2.1 `internal/database/utils.py` inventory (383 lines, fully read)

Moves with the trio (zero internal dependencies — file imports are stdlib + `dateutil` only,
:9-17):

| Symbol | Line | Notes |
|---|---|---|
| `FORCE_SQL_TIMEZONE` | :23 | Used only inside the trio (:123,157,178,234-235) + test docstrings; no external importers (grep-verified) |
| `LIST/TUPLE/SET/DICT/SEQUENCE/CONTAINER_LIKE_TYPES` | :26-31 | Private machinery of `sqlToCustomType`; no external users |
| `_T` TypeVar | :34 | Internal |
| `_checkType` | :38 | Private helper; directly imported only by `tests/database/test_utils.py:21` |
| `sqlToCustomType` | :89 | Public; recursive converter |
| `sqlToTypedDict` | :319 | Public; TypedDict row validator/coercer |

Stays (internal consumers):

| Symbol | Line | Consumers (verified) |
|---|---|---|
| `DEFAULT_THREAD_ID` | :21 | 3 handlers (`message_preprocessor.py:29`, `user_memories.py:57`, `chat_search.py:59`) + 5 test files — untouched |
| `getCurrentTimestamp` | :377 | ~30 sites: `migrations/manager.py:40`, `repositories/chat_settings.py:14`, `migration_027:43`, 11 dual-use repos, `bayes_storage.py`, `internal/services/cache/service.py:1194,1277`, `stats_storage.py:105,168,311` (until Arc 2), + tests |

Lib equivalent already exists: `libUtils.now()`
([`lib/utils/utils.py`](../../lib/utils/utils.py):362-364) — identical body
(`datetime.datetime.now(datetime.timezone.utc)`).

### 2.2 Decode-trio consumer census — 17 production + 2 test rewire files

**Dual-use files (13)** — use the trio AND `getCurrentTimestamp`; keep their `dbUtils`
module import, add a decode import:

| File | Decode sites |
|---|---|
| `internal/database/stats_storage.py` | :219 |
| `internal/services/cache/service.py` (import `:35`) | :151, :155 |
| `repositories/chat_messages.py` | :246,286,355,410,457,509 |
| `repositories/user_memories.py` | :449,497,539,602,858,1066,1485 |
| `repositories/chat_users.py` | :121,199,268,326,377 |
| `repositories/spam.py` | :220,250,322 |
| `repositories/media_attachments.py` | :292,326,365 |
| `repositories/webhook_updates.py` | :201 |
| `repositories/delayed_tasks.py` | :267 |
| `repositories/divinations.py` | :226 |
| `repositories/chat_info.py` | :127,208 |
| `repositories/chat_summarization.py` | :163 |
| `repositories/cache.py` | :93,239 |

**Decode-only files (4)** — drop the dbUtils import entirely (subject to a per-file flake8
F401 check for stray other-symbol usage):

| File | Decode sites |
|---|---|
| `repositories/chat_search.py` | :344,608 |
| `repositories/chat_embeddings.py` | :515 |
| `repositories/embedding_models.py` | :191,207 |
| `internal/bot/models/ensured_message.py` (import `:30`) | :819 |

**Test-side (2)**: `tests/database/test_utils.py` (the dedicated suite; `git mv` →
`tests/lib/db/test_decode.py`, import block :20-22) and `tests/dependencies/test_dateutil.py`
(:30 direct import flip). NOT in Arc 1 (getCurrentTimestamp-only dbUtils users):
`tests/database/test_bayes_storage.py:13,60`, `tests/database/repositories/test_cache_repository.py:15,266+`,
`tests/lib/stats/test_sql_storage.py:10,587` (Arc 2 flips its patch target — §2.4).

Prose/docstring mentions (Arc 3 sweep, no gate impact): `internal/database/models.py:564`,
`docs/llm/database.md:323,515,547,608,748-764`, `docs/llm/tasks.md:483`,
`docs/llm/memories/*.md`, `docs/suggestions/refactoring.md:30,746`,
`docs/sql-portability-guide.md:1343,1443,1595`. No TYPE_CHECKING or string-patch targets for
the trio exist (grep-verified).

### 2.3 `DatabaseStatsStorage` internal surface (fully read, 545 lines)

Only two internal imports: `from . import utils as dbUtils` (:23) and
`from .database import Database` (:24). The `Database` wrapper is touched solely via
`self.db.manager.getProvider(dataSource=self.dataSource, readonly=…)` at :114 (`record`),
:171 (`aggregate`), :312 (`purgeProcessed`), :416 (`query`, readonly=True). Everything else
is already lib-side (`lib.utils`, `lib.db.providers.base.ExcludedValue`, `lib.stats.*`).
Constructor today: `__init__(self, db: Database, eventType: str, *, dataSource: str)` with
`__slots__ = ("db", "eventType", "dataSource")` (:62-74).

### 2.4 Stats-storage consumer census — 6 external sites

1. `internal/services/stats/service.py:27` (import) and `:252` — the ONLY production
   construction (`DatabaseStatsStorage(db=self._database, …)` inside the
   `createStatsStorage` factory). Wiring chain: `main.py:91` initializes the service,
   `main.py:108-111` loops five `createStatsStorage` calls. `initialize(configManager,
   database)` signature UNCHANGED (service still needs `Database` for `.manager.default`,
   service.py:250).
2. `internal/database/migrations/versions/migration_027_drop_chat_stats_backfill_aggregates.py:42`
   — real import of `_hashLabels`, `truncateToDay`, `truncateToMonth` (+ docstring :14).
   In-place edit sanctioned by the migration's own header ("edited in place; it is not yet
   deployed").
3. `tests/lib/stats/conftest.py:14,49` — import + `db=db` kwarg.
4. `tests/lib/stats/test_sql_storage.py:10,12` — dbUtils (patch target :561,587 flips to
   `lib.utils` when the storage switches to `libUtils.now()`), module import, and 15×
   `statsStorage.db.manager.…` → `statsStorage.manager.…` (:32-698).
5. `tests/database/test_migration_027_…py:36` — `_hashLabels` import flip.
6. `tests/services/stats/test_service.py` — ZERO changes: `Mock(spec=Database)` (:90),
   class-name string asserts only (:758, :1064).

Tests are already parked at the mirror location `tests/lib/stats/` — naming the module
`sql_storage.py` makes the existing `test_sql_storage.py` filename correct with zero renames.

### 2.5 Check-docs mechanics and sweep duties

[`scripts/check_docs.py`](../../scripts/check_docs.py) validates md file links repo-wide,
skips `docs/archive/`, `.opencode/`, fences and inline code, and strips `#anchor`/`:line`
suffixes (verified in the lib-db doc §2.5). Consequences:

- **Arc 1** — NO mandatory link sweep: `internal/database/utils.py` survives the trio
  extraction, so every existing link to it (including `:line`-anchored ones) keeps resolving.
  Symbol-level prose accuracy is Arc 3 work.
- **Arc 2** — MANDATORY sweep: `internal/database/stats_storage.py` is deleted; md links into
  it exist in 7 live files: `docs/database-schema.md` (:426,460),
  `docs/design/stats-aggregation-v1.md` (~8), `stats-collecting-v1.md` (~15),
  `stats-display-v1.md` (~11), `stats-consumerid-gaps.md` (:40), `stt-v1.1.md` (:76,432),
  `docs/design/lib-db-extraction-v1.md` (:28).

### 2.6 Facade shape

[`lib/db/__init__.py`](../../lib/db/__init__.py) already re-exports the public API
(:32-49). The decode module's public names join it in Arc 1 (D4).

---

## 3. Ratified decisions (D1–D11)

### D1 — Decode trio target: `lib/db/decode.py` (S2)

The trio + `_checkType` + `FORCE_SQL_TIMEZONE` + the container-type constants move to a new
module `lib/db/decode.py` (path in backticks: does not exist today). Alternatives rejected:
`lib/db/utils.py` — a second "utils" module next to
[`lib/db/providers/utils.py`](../../lib/db/providers/utils.py) (the ENCODE side,
`convertToSQLite`) invites import confusion; folding into `providers/utils.py` — decode is
consumer-side plumbing (repositories), not provider internals, and that module is imported
only by providers today. Encode/decode cohesion is served by the shared `lib/db` package,
not by a shared module name.

### D2 — Facade export

`lib/db/__init__.py` gains `sqlToCustomType`, `sqlToTypedDict`, and `FORCE_SQL_TIMEZONE`
in `__all__`. Container-type constants stay module-level public in `decode.py` but are not
facade-exported (no external consumers; grep-verified).

### D3 — Arc ordering: decode trio FIRST

Arc 1 lands the trio so Arc 2's storage module imports decode from `lib.db` — no S1-style
local decoder, no parity tests. S2 removes the decode-seam risk entirely: it is the same
code, relocated.

### D4 — Stats storage target: `lib/stats/sql_storage.py`, class name kept

Module named for the already-parked test file; class `DatabaseStatsStorage` kept (name
asserted at `tests/services/stats/test_service.py:758,1064`; ADR-022 and consumer docs
reference it). Exported from `lib/stats/__init__.py` alongside the ABC. Internal imports of
the module use relative form (`.stats_storage`, `.types`) matching
`lib/stats/stats_storage.py:7` style.

### D5 — Constructor: `(manager: DatabaseManager, eventType: str, *, dataSource: str)`

`__slots__ = ("manager", "eventType", "dataSource")`. Per-call
`await self.manager.getProvider(dataSource=…, readonly=…)` is kept — it preserves lazy
provider init + migration hooks ([`lib/db/manager.py`](../../lib/db/manager.py):174-180)
and readonly write-validation (:185-189). The storage stays lifecycle-agnostic: verified no
connect/disconnect anywhere in the module; `closeAll` runs in `Database.__aexit__`
(`internal/database/database.py:365`). `dbUtils.getCurrentTimestamp()` (:105,168,311) →
`libUtils.now()`; `dbUtils.sqlToTypedDict` (:219) → decode import from `lib.db`.

### D6 — Factory stays internal, signature unchanged

`StatsAggregationService` reads bot config → internal is its home. Only two edits:
import flip (service.py:27) and `manager=self._database.manager` (service.py:252).
`initialize(configManager, database)` and the disabled-gate NullStatsStorage behavior are
untouched (ratified amendment A3 shape preserved).

### D7 — migration_027 in-place import flip

`from ...stats_storage import …` → lib import, per its own "edited in place" header.
Migrations stay internal — they own the DDL; the storage only queries the tables
(migration_016/028 create them regardless of where the class lives).

### D8 — Big-bang, no shim, both arcs

Old symbols/file deleted in the same commit the new location lands (git-mv where whole-file,
symbol-extraction for utils.py). Precedent: ADR-022. The `make lint` `import main` gate and
the full suite cover missed rewires; residual greps are arc gates (§5).

### D9 — ADR-023, house append pattern

New ADR (text ready to paste, §6). It records BOTH supersessions of ADR-022's
"internal/database/ SURVIVES with …" clause ([`docs/llm/architecture.md`](../llm/architecture.md):821):
`stats_storage.py` (this design) and internal `utils.py` (`sqlToTypedDict`) — S2 scope
change. ADR-022's body is never edited; history is immutable, successors supersede.

### D10 — Doc-only round

This document is written and committed now; implementation (Arcs 1-3) is deferred to a later
go. The Status line records it.

### D11 — CHANGELOG skipped

Internal refactor, no user-visible change (AGENTS.md skip criteria; same call as ADR-022).

---

## 4. Phased plan

Per-arc gates: `make format lint`, `make test`, `make check-docs` (docs-only arcs: lint +
check-docs), plus the residual greps listed per arc. One commit per green arc, explicit
staging excluding `.opencode/memory.jsonl` (house pattern).

### Phase 0 — this document (NOW, doc-only round)

Write + commit this file. Gate: `make check-docs` + `make lint`.

### Arc 1 — CODE: decode trio → `lib/db/decode.py` (~60 steps; split contingency below)

1. Create `lib/db/decode.py` with the moved symbols (D1/D2) — code copy is verbatim;
   update module docstring.
2. Facade export (D2).
3. Delete the moved symbols from `internal/database/utils.py` (file survives with
   `DEFAULT_THREAD_ID` + `getCurrentTimestamp`; prune now-unused imports there).
4. Rewire the 13 dual-use production files (keep dbUtils import, add decode import).
5. Rewire the 4 decode-only files (drop dbUtils import; F401 check per file).
6. `git mv tests/database/test_utils.py` → `tests/lib/db/test_decode.py` + import rewrite;
   flip `tests/dependencies/test_dateutil.py:30`.
7. Residual grep gate: `sqlToTypedDict|sqlToCustomType` definitions/usages resolve only via
   `lib.db` (or local names); `internal\.database\.utils` dotted+slashed greps show only
   `DEFAULT_THREAD_ID`/`getCurrentTimestamp` importers; `_checkType` only inside decode
   module + its test.
8. Full gates; single commit ("Extract SQL decode trio to lib/db").

Contingency: if steps 4-5 overflow the step budget, split Arc 1 into 1a (module + repos) and
1b (non-repo consumers + tests), commit each green.

### Arc 2 — CODE: `DatabaseStatsStorage` → `lib/stats/sql_storage.py` (~40 steps)

1. `git mv internal/database/stats_storage.py lib/stats/sql_storage.py`; rewrite internals
   per D5 (imports, constructor, 4× getProvider, `libUtils.now()`, decode from `lib.db`).
2. Export from `lib/stats/__init__.py`.
3. Rewire the census sites (§2.4): factory (2 lines), migration_027 (:42 + docstring :14),
   `tests/lib/stats/conftest.py` (`manager=db.manager`), `tests/lib/stats/test_sql_storage.py`
   (imports, 15× `.db.manager` → `.manager`, patch target :587 → `lib.utils`), and
   `tests/database/test_migration_027_…py:36`.
4. Mandatory md link-target sweep (§2.5) in the 7 files.
5. Residual grep gate: `internal\.database\.stats_storage` returns zero outside
   `docs/archive/`.
6. Full gates; single commit ("Move DatabaseStatsStorage to lib/stats").

### Arc 3 — DOCS: ADR-023 + agent docs (~25 steps)

Insert ADR-023 (§6) after ADR-022 in [`docs/llm/architecture.md`](../llm/architecture.md)
(convert to house link format); update `docs/llm/database.md` (utils section :748+ → decode
module; :482 sibling-classes note — Bayes stays, Stats moves), `docs/llm/libraries.md` (§9
impl paragraph :633; §18 lib/db table gains decode module), `docs/llm/index.md` (:313 lib/stats
row; §4.5/§4.6 maps), `docs/llm/services.md` (:598,656), `docs/llm/configuration.md` (:475),
`docs/database-schema.md` + `docs/database-schema-llm.md` pointers, §8-follow-up closure
note in the lib-db doc (§9 below), one dated addendum line in
`docs/design/stats-aggregation-v1.md`'s amendment block (originals preserved). Gate:
`make lint` + `make check-docs`; commit.

---

## 5. ADR-023 (ready to paste; fenced — convert links on insertion)

```text
### ADR-023: Decode trio to `lib/db`; `DatabaseStatsStorage` to `lib/stats`

**Date:** 2026-08-24 (ratified; implementation per its design doc arcs)
**Status:** Accepted (supersedes two scope clauses of ADR-022)

**Decision:** Two chained extractions, both big-bang with no re-export shim (ADR-022
precedent). (1) The SQL decode trio — `sqlToTypedDict`, `sqlToCustomType`, `_checkType`,
plus `FORCE_SQL_TIMEZONE` and the container-type constants — moved from
`internal/database/utils.py` to a new bot-free `lib/db/decode.py`, facade-exported from
`lib/db/__init__.py`. `internal/database/utils.py` survives with `DEFAULT_THREAD_ID` and
`getCurrentTimestamp`. (2) `DatabaseStatsStorage` moved from
`internal/database/stats_storage.py` to `lib/stats/sql_storage.py`, exported from the
`lib/stats` package; its constructor changed from `(db: Database, eventType, *, dataSource)`
to `(manager: DatabaseManager, eventType, *, dataSource)` with per-call
`manager.getProvider(dataSource=…, readonly=…)`. The `StatsAggregationService` factory
(`createStatsStorage`) stays internal and unchanged in signature; migration_027's helper
imports (`_hashLabels`, `truncateToDay`, `truncateToMonth`) were flipped in place (its
header sanctions in-place edits). Stats tables remain owned by internal migrations
(016/027/028).

**Why:** ADR-022 extracted the provider layer precisely to make a `lib/stats` SQL storage
possible; the two remaining blockers were the storage's `Database`-wrapper dependency and
its dependence on internal decode utilities. Moving the trio (user decision S2, over a
narrower local-decoder alternative) keeps one canonical decode implementation, unblocks the
parked `lib/cache` `GenericDatabaseCache` extraction, and makes the storage move a pure
relocation.

**Supersessions of ADR-022:** its "internal/database/ SURVIVES with … stats_storage.py …"
clause is superseded by the storage move; its "internal utils.py (`sqlToTypedDict`)"
survives-item is superseded by the trio move. ADR-022's text stands as history.

Design doc: `docs/design/lib-stats-sql-storage-extraction-v1.md`.
```

---

## 6. Risks and gotchas

| Risk | Severity | Mitigation |
|---|---|---|
| Missed decode rewire site (17 files) | Med | Residual grep gate (Arc 1 step 7) + `import main` cycle gate + full suite |
| Dual-use files keep dbUtils while adding decode import — import-order churn | Low | `make format` (isort) is an arc gate |
| Decode-only file actually uses another utils symbol | Low | Per-file F401 check (Arc 1 step 5); when unsure, keep the dbUtils import |
| `test_sql_storage.py` patch target (`patch.object(dbUtils, "getCurrentTimestamp")` :587) silently patches the wrong module after Arc 2 | High (test-only) | Explicit checklist item Arc 2 step 3; the frozen-clock test FAILS loudly if missed (it asserts fixed-now behavior) |
| Dead md links at the Arc 2 commit | Med | Mandatory 7-file sweep rides Arc 2 (§2.5); check-docs gate |
| ADR-022 clause drift | Low | ADR-023 records both supersessions; ADR-022 body never edited (D9) |
| `docs/archive/**` references | None | Not scanned by check-docs; intentionally untouched |
| Singleton/lifecycle traps | None | Verified: no connect/disconnect in the storage; factory semantics untouched |
| Chat-time behavior change | None | Factory gating, `[stats] enabled=false` default, never-raise `record()` all untouched; suite is the gate |

---

## 7. Documentation sync map (per the update-project-docs matrix)

- Arc 1 → `docs/llm/libraries.md` (§18 lib/db table + §rows citing `dbUtils` decode),
  `docs/llm/database.md` (utils section), `docs/llm/tasks.md` (utils gotcha row :483).
- Arc 2 → `docs/llm/libraries.md` §9, `docs/llm/database.md` :482, `docs/llm/index.md`,
  `docs/llm/services.md`, `docs/llm/configuration.md`, both schema docs, design-doc
  link sweep (§2.5 list).
- Arc 3 → ADR-023 + all of the above prose + §8/follow-up closures below.

---

## 8. Follow-ups (out of scope, tracked here)

1. **`lib/cache` extraction — UNBLOCKED by S2.** The parked audit verdict
   (`docs/llm/teamlead-memory.md` :130): `GenericDatabaseCache`
   (`internal/database/generic_cache.py`) goes through the `Database` wrapper + the
   `db.cache` repository and implicitly needs the decode trio. With the trio in `lib/db`,
   the remaining work is rewriting it to own SQL via `DatabaseManager` — own design pass.
   This also closes lib-db-extraction §8 item 4 (the ABC-in-lib/impl-in-internal audit).
2. **lib-db-extraction §8 item 1 closes when Arc 2 lands** — add the closure note there
   (Arc 3).
3. Optional later cleanup: retire `internal/database/utils.py`'s `getCurrentTimestamp` in
   favor of `libUtils.now()` across its ~30 internal sites (mechanical, no design needed).

---

## 9. Open questions

**None.** All decisions were ratified by the user on 2026-08-24 (S2 decode-trio extraction,
ADR-023, doc-only round) and are encoded as D1-D11. Implementation proceeds arc by arc on a
later go.

---

## 10. References

- [`docs/design/lib-db-extraction-v1.md`](./lib-db-extraction-v1.md) — house-format template,
  ADR-022 grounding, §8 follow-up list (item 1 = this design)
- [`docs/llm/architecture.md`](../llm/architecture.md) — ADR-022 (:819-823; the superseded
  clauses), ADR-023 insertion point
- [`internal/database/utils.py`](../../internal/database/utils.py),
  [`internal/database/stats_storage.py`](../../internal/database/stats_storage.py),
  [`lib/db/manager.py`](../../lib/db/manager.py), [`lib/stats/stats_storage.py`](../../lib/stats/stats_storage.py)
  — the moved/modified sources
- [`docs/design/stats-aggregation-v1.md`](./stats-aggregation-v1.md) — the stats architecture
  this storage serves (amendment block gets the Arc 3 addendum)
- [`scripts/check_docs.py`](../../scripts/check_docs.py) — link-gate mechanics (§2.5)
- [`AGENTS.md`](../../AGENTS.md) — hard rules, SQL portability, changelog skip criteria
