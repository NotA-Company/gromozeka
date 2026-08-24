# Design: Decode trio → `lib/db` and `DatabaseStatsStorage` → `lib/stats` (v1)

**Date**: 2026-08-24
**Status**: **Ratified 2026-08-24, amended 2026-08-24 — implementation in progress.** All
decisions (D1–D11) user-ratified 2026-08-24; the same-day amendment (below) rescoped Arc 1
from decode-trio-only extraction to a whole-module move. Arcs 1–3 are authorized to proceed.
**Owner**: TBD
**Scope**: Two chained extractions. First, move the SQL decode trio (`sqlToTypedDict`,
`sqlToCustomType`, `_checkType` + its private constants) out of
[`lib/db/utils.py`](../../lib/db/utils.py) into a new bot-free
`lib/db` module (decision S2 — supersedes the ADR-022 scope item "internal `utils.py`
survives"). Second, move [`internal/database/stats_storage.py`](../../internal/database/stats_storage.py)
(`DatabaseStatsStorage`, 545 lines) to `lib/stats/` with a `DatabaseManager`-based
constructor. Big-bang cutover per file, no re-export shims (ADR-022 precedent). Also
unblocks the parked `lib/cache` `GenericDatabaseCache` extraction as a follow-up (§9).

> **2026-08-24 amendment (user, verbatim intent; supersedes the original Arc-1 shape):**
> Arc 1 becomes a **whole-module move** — `git mv internal/database/utils.py` →
> `lib/db/utils.py` — carrying `getCurrentTimestamp`, `DEFAULT_THREAD_ID`, and every other
> occupant, not just the decode trio (original D1 target `lib/db/decode.py` is dropped; the
> module name `lib/db/utils.py` is FIXED by the user). `internal/database/utils.py` is
> DELETED; nothing survives in internal. Consequences propagated below: the consumer census
> grows to 25 production + 10 test rewire files (§2.2), Arc 1 now REQUIRES the md
> link-target sweep (§2.5), and implementation is no longer deferred (D10).

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
a private narrow decoder inside the storage module, the canonical decode utilities themselves
move to `lib/db`. The same-day amendment widened this to the whole module. This is a bigger
blast radius (25 production rewire files — §2.2) but yields a single canonical
implementation, removes the decode-seam parity-test burden entirely (same code objects, new
location), and settles the question that had parked the `lib/cache` audit
([`docs/llm/teamlead-memory.md`](../llm/teamlead-memory.md) :130 — "PARKED until the
decode-trio question is settled").

**Goal in one paragraph:** move the whole `internal/database/utils.py` module to
`lib/db/utils.py` (Arc 1), then `git mv`
`DatabaseStatsStorage` to `lib/stats/sql_storage.py` with constructor
`(manager: DatabaseManager, eventType: str, *, dataSource: str)` (Arc 2), then land ADR-023
and the documentation sync (Arc 3). Old locations deleted in the same commit their
replacements land; `make check-docs` green at every commit; one commit per green arc.

### 1.1 Goals

- **G1** — `lib/stats` gains its SQL implementation; `internal/database/stats_storage.py` is
  deleted; the ABC-in-lib / impl-in-internal split for stats is gone.
- **G2** — Behavior-preserving: no SQL text, schema, config, or public-API change. The two
  runtime-observable deltas are (a) `sqlToTypedDict` / `sqlToCustomType` /
  `getCurrentTimestamp` / `DEFAULT_THREAD_ID` resolve from `lib.db` instead of
  `internal.database.utils`, and (b) `DatabaseStatsStorage` takes `manager=` instead of
  `db=`. Both are type-identical relocations.
- **G3** — `internal/database/utils.py` is DELETED; the whole module (decode trio +
  `getCurrentTimestamp` + `DEFAULT_THREAD_ID` + private machinery) lives at
  `lib/db/utils.py` (amendment). Nothing survives in internal.
- **G4** — `make check-docs` green at every commit: BOTH code arcs carry mandatory md
  link-target sweeps (Arc 1: the utils file is deleted — §2.5; Arc 2: the stats module file
  is deleted).

### 1.2 Non-goals

- **NG1** — No moving of migrations, repositories, the `Database` wrapper, or
  `bayes_storage.py` (their IMPORTS flip; the files stay).
- **NG2** — No `lib/cache` extraction in this effort — listed as a follow-up it unblocks (§9).
- **NG3** — No transactional-batch provider work (separate standing follow-up from the stats
  v3 design; the `TODO` at `internal/database/stats_storage.py:244` rides along unchanged).
- **NG4** — No CHANGELOG entry for either code arc (internal refactor, no user-visible
  change — same call as ADR-022).

---

## 2. Verified grounding

### 2.1 `internal/database/utils.py` inventory (383 lines, fully read)

Under the amendment, the WHOLE module moves (zero internal dependencies — file imports are
stdlib + `dateutil` only, :9-17). Occupants and their consumer classes:

| Symbol | Line | Consumers (verified) |
|---|---|---|
| `DEFAULT_THREAD_ID` | :21 | 3 handlers + 5 test files (see §2.2) — now rewired to `lib.db.utils` |
| `FORCE_SQL_TIMEZONE` | :23 | Used only inside the module (:123,157,178,234-235) + test docstrings; no external importers (grep-verified) |
| `LIST/TUPLE/SET/DICT/SEQUENCE/CONTAINER_LIKE_TYPES` | :26-31 | Private machinery of `sqlToCustomType`; no external users |
| `_T` TypeVar | :34 | Internal |
| `_checkType` | :38 | Private helper; directly imported only by `tests/database/test_utils.py:21` |
| `sqlToCustomType` | :89 | Public; recursive converter (17 production files — §2.2) |
| `sqlToTypedDict` | :319 | Public; TypedDict row validator/coercer (17 production files — §2.2) |
| `getCurrentTimestamp` | :377 | ~30 production sites + 3 test files (§2.2) — now rewired to `lib.db.utils` |

Lib equivalent already exists: `libUtils.now()`
([`lib/utils/utils.py`](../../lib/utils/utils.py):362-364) — identical body
(`datetime.datetime.now(datetime.timezone.utc)`). NOT forced in Arc 1 (D2); only Arc 2's
stats rewrite adopts it for the storage module.

### 2.2 Module consumer census — 25 production + 10 test rewire files (post-amendment)

Every import form verified by fresh greps (`from internal\.database import utils`,
`from internal\.database\.utils import`, `import internal\.database\.utils`,
`from \. import utils`, `from \.\. import utils`, `from \.\.\.utils`, inside internal/ and
tests/). Negative verifications: **zero** importers under `lib/` and `scripts/`; the
`from . import utils` hits in `lib/db/providers/{mysql,sqlink,sqlite3}.py` refer to their OWN
`providers/utils.py` (encode side — unrelated). One string-ish patch target:
`tests/lib/stats/test_sql_storage.py:587` (`patch.object(dbUtils, "getCurrentTimestamp", …)`)
— flips with the module move.

**Decode users — dual-use (14 production files)** (decode + `getCurrentTimestamp`; the
module-import alias flips to `from lib.db import utils as dbUtils`):

| File | Decode sites |
|---|---|
| `internal/database/stats_storage.py` (import `:23`) | :219 (+ timestamp :105,168,311) |
| `internal/services/cache/service.py` (import `:35`) | :151, :155 (+ timestamp :1194,1277) |
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
| (12 repos above via `from .. import utils as dbUtils`) | |

**Decode-only (4 production files)** — decode sites only; flip import, then F401-check
before dropping (drop only if no other symbol used):

| File | Decode sites |
|---|---|
| `repositories/chat_search.py` | :344,608 |
| `repositories/chat_embeddings.py` | :515 |
| `repositories/embedding_models.py` | :191,207 |
| `internal/bot/models/ensured_message.py` (import `:30`, `import … as dbUtils`) | :819 |

**Timestamp-only (4 production files)** — NEW in scope under the amendment:

| File | Import site |
|---|---|
| `internal/database/bayes_storage.py` | `:17` (`from . import utils as dbUtils`) |
| `internal/database/migrations/manager.py` | `:40` (`from ..utils import getCurrentTimestamp`) |
| `internal/database/migrations/versions/migration_027_…py` | `:43` (same form, one level deeper) |
| `repositories/chat_settings.py` | `:14` (same form) |

**`DEFAULT_THREAD_ID`-only (3 production files)** — NEW in scope:

`internal/bot/common/handlers/message_preprocessor.py:29`, `user_memories.py:57`,
`chat_search.py:59` — all `from internal.database.utils import DEFAULT_THREAD_ID` → flip to
`from lib.db.utils import DEFAULT_THREAD_ID`.

**Test-side (10 files)**:

| File | What flips |
|---|---|
| `tests/database/test_utils.py` (:20-22) | whole suite `git mv` → `tests/lib/db/test_utils.py` + import rewrite (no collision: `tests/lib/db/providers/test_utils.py` tests the ENCODE-side providers utils — different path, mirror rule intact) |
| `tests/dependencies/test_dateutil.py:30` | direct decode import flip |
| `tests/database/test_bayes_storage.py:13,60` | timestamp-only (NEW in scope) |
| `tests/database/repositories/test_cache_repository.py:15,266+` | timestamp-only (NEW in scope) |
| `tests/lib/stats/test_sql_storage.py:10,587` | timestamp + the patch target — MUST land in Arc 1 or the frozen-clock test patches a dead module (production `stats_storage.py:23` flips in the same arc); Arc 2 then retires dbUtils there entirely |
| `tests/bot/models/test_message_metadata.py:23` | `DEFAULT_THREAD_ID` (NEW) |
| `tests/bot/models/test_ensured_message.py:37` | `DEFAULT_THREAD_ID` (NEW) |
| `tests/bot/common/handlers/test_user_memories.py:72` | `DEFAULT_THREAD_ID` (NEW) |
| `tests/bot/common/handlers/test_message_preprocessor.py:50` | `DEFAULT_THREAD_ID` (NEW) |
| `tests/bot/common/handlers/test_user_info_cache_regression.py:53` | `DEFAULT_THREAD_ID` (NEW) |

Prose/docstring mentions (Arc 3 sweep, no gate impact): `internal/database/models.py:564`,
`docs/llm/database.md:323,515,547,608,748-764`, `docs/llm/tasks.md:483`,
`docs/llm/memories/*.md`, `docs/suggestions/refactoring.md:30,746`,
`docs/sql-portability-guide.md:1343,1443,1595`. No TYPE_CHECKING imports of the module exist
(grep-verified).

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

- **Arc 1** — MANDATORY sweep (post-amendment: the utils file is DELETED): md links into
  `internal/database/utils.py` exist in 5 live scanned files —
  `internal/database/migrations/README.md:689` (relative `../utils.py` →
  `../../../lib/db/utils.py`), `docs/sql-portability-guide.md:1343,1443,1595`
  (root-absolute `/internal/database/utils.py` → `/lib/db/utils.py`),
  `docs/suggestions/refactoring.md:30,746` (`../../internal/database/utils.py` + `:164`/`:69`
  anchors → `../../../lib/db/utils.py`), `docs/llm/database.md:748`, and THIS design doc
  (Scope + §2.1/§10 links). Symbol-level prose accuracy beyond targets is Arc 3 work.
- **Arc 2** — MANDATORY sweep: `internal/database/stats_storage.py` is deleted; md links into
  it exist in 7 live files: `docs/database-schema.md` (:426,460),
  `docs/design/stats-aggregation-v1.md` (~8), `stats-collecting-v1.md` (~15),
  `stats-display-v1.md` (~11), `stats-consumerid-gaps.md` (:40), `stt-v1.1.md` (:76,432),
  `docs/design/lib-db-extraction-v1.md` (:28).

### 2.6 Facade shape

[`lib/db/__init__.py`](../../lib/db/__init__.py) already re-exports the public API
(:32-49). The moved module's decode names join it in Arc 1 (D2); `getCurrentTimestamp` and
`DEFAULT_THREAD_ID` consumers import from `lib.db.utils` directly (module shape preserved).

---

## 3. Ratified decisions (D1–D11)

### D1 — Utils module target: `lib/db/utils.py`, WHOLE module (S2 + 2026-08-24 amendment)

The ENTIRE `internal/database/utils.py` moves via `git mv` to `lib/db/utils.py` (path in
backticks: does not exist today) — decode trio, `getCurrentTimestamp`, `DEFAULT_THREAD_ID`,
and all private machinery. Module name FIXED by the user. **Deliberate coexistence, do not
"fix" later:** after this arc, BOTH `lib/db/utils.py` (decode + timestamps, consumer-side)
and [`lib/db/providers/utils.py`](../../lib/db/providers/utils.py) (ENCODE side,
`convertToSQLite`, provider-internal) exist — the user chose this naming deliberately; the
`providers.` path segment is the disambiguator. Original alternative (`lib/db/decode.py` for
the trio only) was superseded by the amendment; nothing survives in internal.

### D2 — Facade export + no forced timestamp migration

`lib/db/__init__.py` gains `sqlToCustomType`, `sqlToTypedDict`, and `FORCE_SQL_TIMEZONE` in
`__all__`. All other consumers keep the module-import shape (`from lib.db import utils as
dbUtils` / `from lib.db.utils import getCurrentTimestamp|DEFAULT_THREAD_ID`) — NO forced
migration of `getCurrentTimestamp` callers to `libUtils.now()` in Arc 1 (that stays an
optional cleanup, §8.3). Only Arc 2's storage rewrite adopts `libUtils.now()` (D5).

### D3 — Arc ordering: utils module FIRST

Arc 1 lands the module so Arc 2's storage imports decode from `lib.db` — no S1-style
local decoder, no parity tests. S2 removes the decode-seam risk entirely: same code objects,
relocated.

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

Old file deleted in the same commit the new location lands; both moves are whole-file
`git mv` (history preserved). Precedent: ADR-022. The `make lint` `import main` gate and
the full suite cover missed rewires; residual greps are arc gates (§4).

### D9 — ADR-023, house append pattern

New ADR (text ready to paste, §6). It records BOTH supersessions of ADR-022's
"internal/database/ SURVIVES with …" clause ([`docs/llm/architecture.md`](../llm/architecture.md):821):
`stats_storage.py` (this design) and internal `utils.py` (`sqlToTypedDict`) — S2 scope
change. ADR-022's body is never edited; history is immutable, successors supersede.

### D10 — Implementation in progress (supersedes the original doc-only round)

Originally ratified as doc-only; the 2026-08-24 amendment authorized implementation to
proceed immediately: Arc 1a/1b → Arc 2 → Arc 3 (§4). The Status line records it.

### D11 — CHANGELOG skipped

Internal refactor, no user-visible change (AGENTS.md skip criteria; same call as ADR-022).

---

## 4. Phased plan

Per-arc gates: `make format lint`, `make test`, `make check-docs`, plus the residual greps
listed per arc. One commit per green arc, explicit staging excluding `.opencode/memory.jsonl`
(house pattern). The commit agent MUST run `make check-docs` before every commit (no agent
in this design round ran it — no shell).

### Phase 0 — this document (DONE, needs re-commit with the amendment)

Write + amend this file. Gate: `make check-docs` + `make lint`.

### Arc 1 — CODE: whole-module `git mv internal/database/utils.py → lib/db/utils.py`

**Pre-declared split into 1a/1b** — the full surface (module move + facade + 25 production
rewires + 10 test rewires + `test_utils.py` git-mv + md link sweep + gates) estimates
~75-85 software-developer steps, over the ~60 budget; splitting keeps each half well under.

**Arc 1a — module + production rewire (~45 steps):**

1. `git mv internal/database/utils.py lib/db/utils.py` (verbatim; module docstring tweak).
2. Facade export (D2).
3. Rewire the 14 dual-use production files (§2.2 — alias flips to
   `from lib.db import utils as dbUtils`), including `internal/database/stats_storage.py:23`
   (its patch-target coupling in `tests/lib/stats/test_sql_storage.py` flips in 1b — both
   must be in a green suite before EITHER commit; if 1a alone would leave the frozen-clock
   test patching a dead module, pull that one test edit into 1a).
4. Rewire the 4 decode-only files (F401 check before dropping the alias).
5. Rewire the 4 timestamp-only files (`bayes_storage.py:17`, `migrations/manager.py:40`,
   `migration_027:43`, `repositories/chat_settings.py:14`) and the 3
   `DEFAULT_THREAD_ID` handlers (:29/:57/:59).
6. Residual grep gate: `internal\.database\.utils|internal/database/utils` (dotted+slashed,
   `*.py`) returns zero; `from \. import utils|from \.\. import utils` inside internal/
   returns zero (lib/db/providers hits are its OWN utils — exclude).
7. Full gates (`make format lint`, `make test`, `make check-docs`); commit ("Move
   internal/database/utils to lib/db/utils").

**Arc 1b — tests + link sweep (~25 steps):**

1. `git mv tests/database/test_utils.py tests/lib/db/test_utils.py` + import rewrite
   (no collision with `tests/lib/db/providers/test_utils.py` — mirror rule intact).
2. Flip the 9 remaining test files (§2.2 table): `test_dateutil.py:30`,
   `test_bayes_storage.py:13`, `test_cache_repository.py:15`,
   `tests/lib/stats/test_sql_storage.py:10` + patch target `:587`
   (`patch.object(dbUtils, "getCurrentTimestamp", …)` — must patch the module object the
   production code now reads, i.e. `lib.db.utils`; Arc 2 moves it to `lib.utils`), and the
   5 `DEFAULT_THREAD_ID` test importers.
3. Mandatory md link-target sweep (§2.5 Arc-1 list, 5 files incl. this doc).
4. Full gates; commit ("Rewire utils consumers/tests after lib/db/utils move").

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

Insert ADR-023 (§5) after ADR-022 in [`docs/llm/architecture.md`](../llm/architecture.md)
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
### ADR-023: `internal/database/utils.py` to `lib/db/utils.py`; `DatabaseStatsStorage` to `lib/stats`

**Date:** 2026-08-24 (ratified + same-day amendment: whole-module move; implementation per
its design doc arcs)
**Status:** Accepted (supersedes two scope clauses of ADR-022)

**Decision:** Two chained extractions, both whole-file big-bang with no re-export shim
(ADR-022 precedent). (1) The ENTIRE `internal/database/utils.py` module moved via git-mv to
a bot-free `lib/db/utils.py` — the SQL decode trio (`sqlToTypedDict`, `sqlToCustomType`,
`_checkType`, `FORCE_SQL_TIMEZONE`, container-type constants) plus `getCurrentTimestamp` and
`DEFAULT_THREAD_ID`; the decode names are facade-exported from `lib/db/__init__.py`.
Nothing survives at the internal path; `internal/database/utils.py` is deleted. Note: BOTH
`lib/db/utils.py` (decode+timestamps) and `lib/db/providers/utils.py` (encode:
`convertToSQLite`) now exist — deliberate naming, disambiguated by the `providers.` segment.
(2) `DatabaseStatsStorage` moved from `internal/database/stats_storage.py` to
`lib/stats/sql_storage.py`, exported from the `lib/stats` package; its constructor changed
from `(db: Database, eventType, *, dataSource)` to `(manager: DatabaseManager, eventType, *,
dataSource)` with per-call `manager.getProvider(dataSource=…, readonly=…)`. The
`StatsAggregationService` factory (`createStatsStorage`) stays internal and unchanged in
signature; migration_027's helper imports (`_hashLabels`, `truncateToDay`,
`truncateToMonth`) were flipped in place (its header sanctions in-place edits). Stats tables
remain owned by internal migrations (016/027/028).

**Why:** ADR-022 extracted the provider layer precisely to make a `lib/stats` SQL storage
possible; the two remaining blockers were the storage's `Database`-wrapper dependency and
its dependence on internal decode utilities. Moving the whole utils module (user decision S2
widened by same-day amendment, over a narrower trio-only or local-decoder alternative) keeps
one canonical decode implementation, unblocks the parked `lib/cache`
`GenericDatabaseCache` extraction, and makes the storage move a pure relocation.

**Supersessions of ADR-022:** its "internal/database/ SURVIVES with … stats_storage.py …"
clause is superseded by the storage move; its "internal utils.py (`sqlToTypedDict`)"
survives-item is superseded ENTIRELY by the whole-module move (not just the decode symbols).
ADR-022's text stands as history.

Design doc: `docs/design/lib-stats-sql-storage-extraction-v1.md`.
```

---

## 6. Risks and gotchas

| Risk | Severity | Mitigation |
|---|---|---|
| Missed rewire site (25 production + 10 test files) | Med | Residual grep gates (Arc 1a step 6 / 1b) + `import main` cycle gate + full suite |
| 1a/1b seam: production flips in 1a but coupled test edits land in 1b | Med | 1a step 3 rule: if `test_sql_storage.py`'s frozen-clock test would patch a dead module after 1a alone, pull that single test edit into 1a; every arc commits only with the full suite green |
| `test_sql_storage.py:587` patch target (`patch.object(dbUtils, "getCurrentTimestamp")`) patches the wrong module object after Arc 1b (and again after Arc 2) | High (test-only) | Explicit checklist items (Arc 1b step 2, Arc 2 step 3); the frozen-clock test FAILS loudly if missed (asserts fixed-now behavior) |
| Decode-only file actually uses another utils symbol | Low | Per-file F401 check (Arc 1a step 4); when unsure, keep the alias import |
| Dead md links at BOTH code-arc commits | Med | Mandatory sweeps: Arc 1b (5-file utils list, §2.5) and Arc 2 (7-file stats list); check-docs gate |
| Someone later "fixes" the `lib/db/utils.py` vs `lib/db/providers/utils.py` coexistence | Low | D1 disambiguation sentence + ADR-023 note record it as deliberate |
| ADR-022 clause drift | Low | ADR-023 records both supersessions; ADR-022 body never edited (D9) |
| `docs/archive/**` references | None | Not scanned by check-docs; intentionally untouched |
| Singleton/lifecycle traps | None | Verified: no connect/disconnect in the storage; factory semantics untouched |
| Chat-time behavior change | None | Factory gating, `[stats] enabled=false` default, never-raise `record()` all untouched; suite is the gate |

---

## 7. Documentation sync map (per the update-project-docs matrix)

- Arc 1 (1a+1b) → link-target sweep (§2.5 5-file list, incl. this doc) +
  `docs/llm/libraries.md` (§18 lib/db table gains the utils module; §rows citing `dbUtils`
  decode), `docs/llm/database.md` (utils section), `docs/llm/tasks.md` (utils gotcha row
  :483), `internal/database/migrations/README.md` (:689 link).
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
3. Optional later cleanup: retire `lib.db.utils.getCurrentTimestamp` in
   favor of `libUtils.now()` across its ~30 internal sites (mechanical, no design needed).

---

## 9. Open questions

**None.** All decisions were ratified by the user on 2026-08-24 (S2 extraction, ADR-023) and
amended the same day (whole-module Arc 1 to `lib/db/utils.py`, implementation authorized).
All are encoded as D1-D11 + the amendment block. Implementation proceeds arc by arc.

---

## 10. References

- [`docs/design/lib-db-extraction-v1.md`](./lib-db-extraction-v1.md) — house-format template,
  ADR-022 grounding, §8 follow-up list (item 1 = this design)
- [`docs/llm/architecture.md`](../llm/architecture.md) — ADR-022 (:819-823; the superseded
  clauses), ADR-023 insertion point
- [`lib/db/utils.py`](../../lib/db/utils.py),
  [`internal/database/stats_storage.py`](../../internal/database/stats_storage.py),
  [`lib/db/manager.py`](../../lib/db/manager.py), [`lib/stats/stats_storage.py`](../../lib/stats/stats_storage.py)
  — the moved/modified sources
- [`docs/design/stats-aggregation-v1.md`](./stats-aggregation-v1.md) — the stats architecture
  this storage serves (amendment block gets the Arc 3 addendum)
- [`scripts/check_docs.py`](../../scripts/check_docs.py) — link-gate mechanics (§2.5)
- [`AGENTS.md`](../../AGENTS.md) — hard rules, SQL portability, changelog skip criteria
