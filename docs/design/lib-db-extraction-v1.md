---
category: design
---

# Design: Extract SQL providers and DatabaseManager into `lib/db` (v1)

**Date**: 2026-08-23
**Status**: **IMPLEMENTED — all phases landed** (code `1a953117`, agent docs `67e3edb7`, user docs `db101e74`). All decisions (D1–D8) user-approved 2026-08-23. See ADR-022.
**Owner**: TBD
**Scope**: Move `internal/database/providers/` (all 7 modules) and `internal/database/manager.py` into a new bot-free `lib/db/` package, cutting the one `internal.*` dependency (MessageId) via a Protocol, rewriting every consumer import in one big-bang arc, and syncing all documentation across three doc arcs. `internal/database/` survives (migrations, repositories, `Database` wrapper, utils, models) and flips its imports to `lib.db`.

> This is a **design document**, not an implementation. Every `file:line` claim below was
> re-verified against source on 2026-08-23 with fresh greps (patterns: `internal\.database\.providers`,
> `internal\.database\.manager`, `from \.\.\.providers`, `from \.\.providers`, `from \.providers`).
> Code sketches follow the repo's `camelCase` convention ([`AGENTS.md`](../../AGENTS.md)).
> Where the planning brief and the code disagreed, the code won and the correction is flagged
> inline (§2.6).

---

## 1. Context and goal

`internal/database/providers/` is a generic, multi-RDBMS SQL provider abstraction
(`BaseSQLProvider` + SQLite3/SQLink implementations + dormant MySQL/PostgreSQL) and
`internal/database/manager.py` (`DatabaseManager`) is a generic provider-routing factory.
Neither contains bot knowledge, yet both live under `internal/` — which by this repo's
layering convention means "bot-specific". The standing wish is even tracked in
[`TODO.md`](../../TODO.md): `- [ ] move database providers to lib`.

The concrete pressure: `lib/stats` (bot-free) defines the `StatsStorage` ABC, but its only
SQL implementation is `DatabaseStatsStorage` in
[`lib/stats/sql_storage.py`](../../lib/stats/sql_storage.py) — an
ABC-in-lib / impl-in-internal split that exists **only because** the provider layer sits in
`internal/` and a `lib/` implementation would have to import `internal.*` to reach it.
Extracting the provider layer to `lib/db/` makes a `lib/stats` SQL storage possible and
removes the last structural excuse for the pattern (an audit for other instances of the
pattern is a follow-up, §8).

**Goal in one paragraph:** create `lib/db/` (providers at `lib/db/providers/`, mirroring
the `lib/stt/providers/` layout; `DatabaseManager` at `lib/db/manager.py`), cut the single
`internal.models.MessageId` dependency in `providers/utils.py` with a
`@runtime_checkable` Protocol, delete the old locations in the **same commit** the copies
land (no shim, no dual-home window), mechanically rewrite every consumer import, and bring
the documentation along in two further arcs. Resulting dependency direction:
`internal → lib.db → {lib.proxy, lib.utils, stdlib, 3rd-party}` — no cycles.

### 1.1 Goals

- **G1** — `lib/db/` is bot-free: zero `internal.*` imports anywhere under it (verified by
  the `make lint` `import main` cycle gate + grep).
- **G2** — Behavior-preserving: no SQL, no schema, no config, no public-API change. The
  only runtime-observable delta is the Protocol branch in `convertToSQLite` (D3), which is
  value-identical for every type that exists today.
- **G3** — One-arc cutover: old `internal/database/providers/` and
  `internal/database/manager.py` are deleted in the same commit the `lib/db/` copies land;
  git history is preserved via `git mv`.
- **G4** — `make check-docs` stays green at every commit (link-target sweep rides the code
  arc; full prose accuracy is the doc arcs' job).

### 1.2 Non-goals

- **NG1** — No migration of `DatabaseStatsStorage` to `lib/stats` (separate follow-up arc
  with its own design pass — it needs a `Database`-dependency replacement; D6).
- **NG2** — No activation/registration of the MySQL/PostgreSQL providers, and no
  conversion of their hard optional-driver imports to the repo `_AVAILABLE` convention
  (they move AS-IS; D5).
- **NG3** — No renaming of the `sqlite3.py` provider module, no restructuring inside the
  package, no public-API reshaping beyond additive re-exports in `lib/db/__init__.py`.
- **NG4** — No CHANGELOG entry (internal refactor, no user-visible change — per
  [`AGENTS.md`](../../AGENTS.md) changelog criteria; D7).

---

## 2. Verified grounding (current state)

Facts verified against source on 2026-08-23. Line numbers are current.

### 2.1 The moving package and its outbound imports

Seven modules move. Their complete outbound import surface (this is what makes the
extraction clean — everything except `utils.py`'s MessageId import is already lib/stdlib/
third-party):

| Module | Outbound imports | Notes |
|---|---|---|
| `base.py` | stdlib only (`logging`, `types`, `abc`, `collections.abc`, `enum`, `typing`) | `BaseSQLProvider`, `ParametrizedQuery`, `FetchType`, `QueryResult*`, `ExcludedValue`, vector TypedDicts/enums |
| `sqlite3.py` | `aiosqlite`; conditional `sqlite_vec` (`_SQLITE_VEC_AVAILABLE` flag); `.base`, `.utils` | Module name shadows stdlib `sqlite3` in name only — see §4.4 |
| `sqlink.py` | `sqlink`; `lib.proxy` (`ProxyConfig`, `ProxyConfigDict`); `.base`, `.utils` | Legal lib→lib edge post-move |
| `mysql.py` | `import aiomysql  # type: ignore[reportMissingImports]`; `.base`, `.utils` | Dormant; not registered in factory (D5) |
| `postgresql.py` | `import asyncpg  # type: ignore[reportMissingImports]`; `.base` | Dormant; not registered in factory (D5) |
| `utils.py` | `lib.utils`; **`internal.models.MessageId`** | The one `internal.*` edge — cut via D3 |
| `__init__.py` | `typing`; `.base`, `.sqlink`, `.sqlite3` | Factory `getSqlProvider` + `SQLProviderConfig`; registers exactly `sqlite3` + `sqlink` |

`internal/database/manager.py` (206 lines) imports only stdlib (`logging`,
`collections.abc`, `typing`) plus `from .providers import BaseSQLProvider,
SQLProviderConfig, getSqlProvider` (manager.py:7). It is fully generic — verified, no
`internal.config` / `internal.models` / bot imports. Its relative import keeps resolving
after the move (`lib/db/manager.py` → `lib/db/providers/`).

### 2.2 The MessageId branch being cut

`convertToSQLite` in `internal/database/providers/utils.py` (the moving copy) currently
branches on the concrete class (utils.py:14, 45-48):

```python
from internal.models import MessageId
...
    elif isinstance(data, MessageId):
        # Exclusive handling for MessageId isn't needed, actually,
        # but this way we'll suppress warning message
        return data.asStr()
```

Key fact grounding D3: `MessageId.__str__` already returns `asStr()`
([`internal/models/types.py`](../../internal/models/types.py):105-111). So today the
final `else` branch (`logger.warning(...); return str(data)`) stores **identical values**
for `MessageId` — the explicit branch exists only to suppress the warning and state
intent. The Protocol replacement therefore cannot change any stored value for any type
that exists in the codebase today; it keeps the explicit intent + warning suppression
without the `internal.*` import.

### 2.3 What survives in `internal/database/`

`Database` wrapper ([`internal/database/database.py`](../../internal/database/database.py)),
`stats_storage.py`, `bayes_storage.py`, `generic_cache.py`, `utils.py` (the OTHER utils —
`sqlToTypedDict` etc.), `models.py`, `constants.py`, the whole `repositories/` tree, and
the whole `migrations/` tree (bot-schema-specific by design — they stay). All of these
flip their provider/manager imports to `lib.db` (§5).

### 2.4 Non-consumers (verified negative — do not touch)

- [`main.py`](../../main.py) — imports `from internal.database import Database` (line 28)
  and uses `self.database.manager.*` as **attribute access** (lines 110, 194). No
  `internal.database.manager` / `internal.database.providers` module imports. No rewrite.
- `scripts/` — `check_condensing.py`, `reproduce_llm_dialog.py`,
  `reproduce_layout_extraction.py` all import `internal.database.Database` / `.models`
  only. No rewrite.
- `lib/` — currently imports nothing from `internal.database` (the dependency firewall
  makes this structural; the extraction preserves it in the reverse direction).

### 2.5 Check-docs mechanics (grounds the Phase 1 link sweep)

[`scripts/check_docs.py`](../../scripts/check_docs.py) validates markdown **file links**
repo-wide (`make check-docs`, [`Makefile`](../../Makefile):111-112). Load-bearing details
verified from the script:

- Scans every `*.md` under the repo root **except**: `.git`, `venv`, caches, `.opencode`,
  `docs/archive`, `docs/templates`, `lib/ext_modules` (check_docs.py:56-84). So
  `docs/archive/**` is NOT scanned — the archive banner (D8) is a mislead-prevention
  measure, not a gate requirement; and `.agents/**/*.md` IS scanned.
- Strips `#anchor`, `?query`, and trailing `:line`/`:line-line` suffixes before resolving
  (check_docs.py:321-334) — `[`x`](../internal/database/providers/base.py:1)` links
  resolve to the file path.
- Ignores links inside inline code spans and fenced code blocks (check_docs.py:104-109,
  363-371) — code-fence import examples do NOT break the gate, but are rewritten in the
  doc arcs for accuracy.

Consequence (the operational requirement): several **live** scanned docs carry markdown
links directly into the moving files. The CODE arc must include a mechanical
link-TARGET-ONLY sweep (`internal/database/providers/...` → `lib/db/providers/...`,
`internal/database/manager.py` → `lib/db/manager.py`, inside markdown link parens,
repo-wide `*.md` including `docs/`, `.agents/`, and `docs/design/`; `docs/archive` is not
scanned and is handled by D8 instead) so check-docs is green at the code commit. Full
prose accuracy (rewriting code-fence examples, mentions in running text) is Arc 2/3 work.

### 2.6 Consumer census — corrections vs. the planning brief

Fresh greps (2026-08-23) found the brief's list incomplete. Corrections, code wins:

1. **`internal/database/bayes_storage.py` was missing** — it imports
   `from .providers import ParametrizedQuery` (line 17) and
   `from .providers.base import ExcludedValue` (line 18). Added to the checklist.
2. **`internal/database/migrations/create_migration.py` was missing** — its scaffolding
   TEMPLATE string emits `from ...providers import BaseSQLProvider, ParametrizedQuery`
   (create_migration.py:128). Load-bearing: after the move, every newly scaffolded
   migration would be born broken. The template must flip to
   `from lib.db.providers import ...` in the code arc.
3. **Repository consumers number 10, not 15** — the "15 repositories" figure counts repo
   files; only 10 actually import providers (the rest go through the `Database` wrapper /
   `BaseRepository`). Verified list in §5.1.
4. **SQL-portability-guide refs = 21 path references (14 link targets + 7 in code/text)**,
   not ~30. Live-doc link counts per file are in §5.3.

### 2.7 ADR numbering

The highest existing ADR in [`docs/llm/architecture.md`](../llm/architecture.md) is
ADR-021 (HTTP layer migrated to httpx2). **This design allocates ADR-022**; the full
ready-to-paste ADR text is drafted in §6 Phase 2.

---

## 3. Architecture decisions (all ratified 2026-08-23 — do not re-litigate)

### D1 — Target `lib/db/`; `internal/database/` survives and flips its imports

Providers move to `lib/db/providers/` (mirroring the `lib/stt/providers/` structure);
`DatabaseManager` moves to `lib/db/manager.py`. `internal/database/` **survives** with
everything bot-specific: migrations, repositories, the `Database` wrapper, internal utils
(`sqlToTypedDict`), `models.py`, `stats_storage.py`, `bayes_storage.py`,
`generic_cache.py`, `constants.py` — and flips its imports to `lib.db`. Resulting
dependency direction: `internal → lib.db → {lib.proxy, lib.utils, stdlib, 3rd-party}`.
No cycles (verified: lib.db's only lib edges are `lib.utils` and `lib.proxy`, neither of
which imports lib.db or anything internal).

### D2 — ALL 7 provider modules move

`base.py`, `sqlite3.py`, `sqlink.py`, `mysql.py`, `postgresql.py`, `utils.py`, and
`__init__.py` (with the `getSqlProvider` factory). No partial extraction, no split
abstraction, no minimal facade — those alternatives were considered and rejected in
planning (three-option analysis on record in `.opencode` session memory, 2026-08-23);
full extraction is the ratified choice.

### D3 — MessageId dependency cut via `@runtime_checkable` Protocol

In the moved `lib/db/providers/utils.py`, replace the `internal.models` import and the
`isinstance(data, MessageId)` branch with a module-local Protocol:

```python
from typing import Protocol, runtime_checkable


@runtime_checkable
class SQLStringifiable(Protocol):
    """Objects that render themselves to their canonical SQL string form."""

    def asStr(self) -> str: ...
```

and the branch becomes:

```python
    elif isinstance(data, SQLStringifiable):
        return data.asStr()
```

The Protocol is defined in `utils.py` itself (keeps the module dependency-free; it is NOT
added to the `lib/db/__init__.py` re-export list). Grounding: `MessageId.__str__` already
returns `asStr()` (§2.2), so the `str()` fallback stores identical values today — the
Protocol keeps the explicit intent + warning suppression without importing
`internal.models`.

**Regression test (REQUIRED, fail-first per repo discipline):** a test object whose
`.asStr()` returns e.g. `"42"` while `__str__` returns e.g. `"WRONG"`. Old code (no
matching `isinstance`, falls to the final `else`) stores `"WRONG"` → the test FAILS
pre-fix; new code matches the Protocol and stores `"42"` → PASSES. The test lives at
`tests/lib/db/providers/test_utils.py` (mirror layout; see §4.3 for the full spec).

### D4 — Big-bang: no shim, no dual-home window

The old `internal/database/providers/` package and `internal/database/manager.py` are
DELETED in the same arc the `lib/db/` copies land. No re-export shim, no transition
window. The planning brief estimated "~55 mechanical one-line import rewrites"; the
verified census (§5) is **86 rewrite sites** — 48 production (including the
create_migration template) + 38 test-side (imports and string patch targets). A dual-home
state must not survive any commit (it would silently reintroduce the internal→internal
edge and drift).

### D5 — mysql.py / postgresql.py move AS-IS (known temporary deviation)

Both keep their hard module-level `import aiomysql` / `import asyncpg` +
`# type: ignore[reportMissingImports]` and stay unregistered in the factory. This is a
**KNOWN TEMPORARY DEVIATION** from the repo's optional-dependency convention
(module-level `try/except ImportError` + `_AVAILABLE` flag, per AGENTS.md). Rationale:
the drivers are not in requirements, so both files are unimportable and untested today;
and their class-level annotations evaluate at import time
(`self._pool: Optional[aiomysql.Pool] = None` — mysql.py:96; the annotation's
`aiomysql.Pool` reference is evaluated with the class body), making a mechanical
`_AVAILABLE` conversion non-trivial (annotations would need string-quoting or
restructuring). Convert only when the providers are actually wired (follow-up, §8).

### D6 — `DatabaseStatsStorage` → `lib/stats` is a separate follow-up arc

Out of scope here. It needs its own design pass (chiefly: replacing the
`Database`-handle dependency with `DatabaseManager`/provider access, mirroring how
repositories take a manager). Listed in §8.

### D7 — CHANGELOG: skip

Internal refactor, no user-visible change — meets the AGENTS.md "when NOT to update"
criteria exactly. No `## [Unreleased]` entry.

### D8 — Docs policy for stale references

`docs/archive/**` gets **at most** a one-line `> Superseded by ADR-022` banner at file
top, and only where the stale path would actively mislead (the archived lib-stats session
transcript, `docs/archive/llm-sessions/lib-stats-gpt-5.5-decision.md`, which embeds the
old import paths in a decision-record context). Dated suggestion logs are left untouched.
Live docs are fully updated (Arcs 2–3). Note: `docs/archive` is excluded from check-docs
scanning (§2.5), so banners are editorial, not gate-driven.

---

## 4. The new package surface

### 4.1 Layout

```
lib/db/
├── __init__.py          # NEW — public API re-exports (lib/stats __init__ style)
├── manager.py           # moved from internal/database/manager.py (git mv)
└── providers/
    ├── __init__.py      # moved — factory getSqlProvider + SQLProviderConfig
    ├── base.py          # moved — BaseSQLProvider, ParametrizedQuery, ExcludedValue, ...
    ├── sqlite3.py       # moved (module name kept — §4.4)
    ├── sqlink.py        # moved
    ├── mysql.py         # moved AS-IS (D5)
    ├── postgresql.py    # moved AS-IS (D5)
    └── utils.py         # moved + D3 Protocol cut
```

### 4.2 `lib/db/__init__.py`

Written in the [`lib/stats/__init__.py`](../../lib/stats/__init__.py) house style:
module docstring (neutral, no "Gromozeka bot" framing) + from-imports + `__all__`.
Re-exports:

- From `.providers.base`: `BaseSQLProvider`, `FetchType`, `ParametrizedQuery`,
  `QueryResult`, `QueryResultFetchOne`, `QueryResultFetchAll`, `ExcludedValue`,
  `VectorColumnDef`, `VectorColumnType`, `VectorDistanceMetric`, `VectorSearchResult`.
- From `.providers` (factory surface): `SQLite3Provider`, `SQLinkProvider`,
  `getSqlProvider`, `SQLProviderConfig`.
- From `.manager`: `DatabaseManager`, `DatabaseManagerConfig`,
  `SQLProviderInitializationHook`.

### 4.3 Regression test spec (fail-first)

File: `tests/lib/db/providers/test_utils.py` (with `tests/lib/db/__init__.py` and
`tests/lib/db/providers/__init__.py` — the latter arrives via `git mv` of the old
`tests/database/providers/__init__.py`). Sketch (camelCase, docstrings, type hints per
AGENTS.md):

```python
class _PretendStringifiable:
    """Test double whose asStr() deliberately disagrees with __str__.

    Pins the SQLStringifiable Protocol branch: conversion must use asStr(),
    never the generic str() fallback.
    """

    def asStr(self) -> str:
        """Return the canonical SQL string form."""
        return "42"

    def __str__(self) -> str:
        """Return a deliberately wrong fallback representation."""
        return "WRONG"


async def test_convertToSQLite_prefersAsStrOverStrFallback() -> None:
    """SQLStringifiable objects convert via asStr(), not str().

    Fails against the pre-extraction code (MessageId-only branch): the
    double falls through to the str() else-branch and yields "WRONG".
    """
    assert convertToSQLite(_PretendStringifiable()) == "42"
```

Order of operations per the repo's regression discipline: write the test FIRST, run it
against the old code (pre-cut), confirm it FAILS with `"WRONG" != "42"`, then apply the
D3 cut and confirm it PASSES. Add the adjacent edge cases the branch touches in the same
file: a `MessageId` round-trip still stores `asStr()` (equivalence guard), and an object
with **no** `asStr` still hits the warning fallback unchanged.

### 4.4 `sqlite3.py` module name: keep

The name shadows stdlib `sqlite3` in name only. All imports in the tree are absolute or
package-relative (`import aiosqlite`, `from lib.db.providers.sqlite3 import ...`); no code
does a bare `import sqlite3` while relying on the stdlib module from inside the package.
Add ONE clarifying docstring line to the moved module noting the deliberate name keep and
the absolute-import assumption, so future readers don't "fix" it.

### 4.5 Module-docstring neutralization (rides the move commit)

Moved module docstrings referencing internal paths or bot framing get neutralized in the
move commit: `providers/__init__.py` ("...abstraction layer for the Gromozeka database
system", "...for the Gromozeka bot"), `manager.py` ("Database manager for Gromozeka bot
with..."). Keep it minimal — rewording, not rewriting.

---

## 5. Import-rewrite checklist (the implementer's census)

Verified 2026-08-23. **Totals: 86 rewrite sites = 48 production + 38 test-side.**

### 5.1 Production (48 sites)

| File | Line(s) | Current import |
|---|---|---|
| `internal/database/__init__.py` | 51 | `from .providers import ParametrizedQuery` |
| `internal/database/database.py` | 37 | `from .manager import DatabaseManager, DatabaseManagerConfig` |
| `internal/database/database.py` | 39 | `from .providers import BaseSQLProvider` |
| `internal/database/stats_storage.py` | 24 | `from .providers.base import ExcludedValue` |
| `internal/database/bayes_storage.py` | 17 | `from .providers import ParametrizedQuery` |
| `internal/database/bayes_storage.py` | 18 | `from .providers.base import ExcludedValue` |
| `internal/database/migrations/base.py` | 38 | TYPE_CHECKING `from ..providers import BaseSQLProvider` |
| `internal/database/migrations/manager.py` | 37 | `from ..providers import BaseSQLProvider` |
| `internal/database/migrations/manager.py` | 38 | `from ..providers.base import ExcludedValue` |
| `internal/database/migrations/create_migration.py` | 128 | TEMPLATE emits `from ...providers import BaseSQLProvider, ParametrizedQuery` → must emit `from lib.db.providers import ...` |
| `internal/database/migrations/versions/migration_001..028` | 1 each | `from ...providers import BaseSQLProvider, ParametrizedQuery` (migration_027 also imports `ExcludedValue`) — **28 files** |
| `internal/database/repositories/cache.py` | 27 | `from ..providers.base import ExcludedValue` |
| `internal/database/repositories/chat_info.py` | 14 | `from ..providers.base import ExcludedValue` |
| `internal/database/repositories/chat_summarization.py` | 18 | `from ..providers.base import ExcludedValue` |
| `internal/database/repositories/chat_settings.py` | 12 | `from ..providers.base import ExcludedValue` |
| `internal/database/repositories/chat_users.py` | 21 | `from ..providers.base import ExcludedValue` |
| `internal/database/repositories/chat_embeddings.py` | 46 | `from ..providers.base import (` (multi-line) |
| `internal/database/repositories/chat_search.py` | 39 | `from ..providers.base import BaseSQLProvider, VectorDistanceMetric` |
| `internal/database/repositories/user_memories.py` | 76 | `from ..providers.base import (` (multi-line) |
| `internal/database/repositories/divinations.py` | 20 | `from ..providers import ExcludedValue, QueryResultFetchOne` |
| `internal/database/repositories/webhook_updates.py` | 26 | `from ..providers import ParametrizedQuery` |

Rewrite shapes: `from ..providers...` / `from ...providers...` / `from .providers...`
→ `from lib.db.providers...`; `from .manager import ...` → `from lib.db.manager import ...`.
Plus the one intra-package cut: the moved `utils.py` drops
`from internal.models import MessageId` (D3). `lib/db/manager.py`'s own
`from .providers import ...` keeps working unchanged.

**Docstring-only path mentions in production code** (accuracy sweep, not load-bearing —
flip in the code arc while touching nearby files, or at latest in Arc 2):
`database.py:24,108`; `repositories/common.py:9`; `repositories/spam.py:10`;
`repositories/__init__.py:35`; `migrations/base.py:14`; `migrations/manager.py:16`;
`migrations/__init__.py:22`; `migrations/README.md:152,284`;
`repositories/embedding_models.py:127` (comment).

### 5.2 Tests (38 sites)

**Physically moved:** `tests/database/providers/` → `tests/lib/db/providers/` (4 test
files + `__init__.py`, `git mv`; imports inside flip to `lib.db...`):

| File | Sites |
|---|---|
| `test_base_provider.py` | :10 |
| `test_sqlite3_provider.py` | :14, :15 |
| `test_sqlite3_vector_search.py` | :8, :12, **:30, :74, :103** — the bold ones are STRING patch targets (`"internal.database.providers.sqlite3._SQLITE_VEC_AVAILABLE"`), not imports; easy to miss |
| `test_vector_search.py` | :8 |

**In-place flips:**

| File | Line(s) |
|---|---|
| `tests/conftest.py` | 21 |
| `tests/verification/test_keepconnection_edge_cases.py` | 16, 17 (file stays; import flips) |
| `tests/database/repositories/test_chat_search.py` | 43, 44 |
| `tests/database/repositories/test_user_memories.py` | 30, 32 |
| `tests/database/repositories/test_chat_embeddings.py` | 37 |
| `tests/database/repositories/test_divinations.py` | 17 |
| `tests/database/repositories/test_cache_repository.py` | 16 |
| `tests/database/repositories/test_embedding_models.py` | 19 |
| `tests/database/test_migration_020_user_memories.py` | 38 |
| `tests/database/test_migration_021_user_memories_soft_delete.py` | 33 |
| `tests/database/test_migration_022_drop_user_data.py` | 21 |
| `tests/database/test_migration_023_...memory_enabled.py` | 30 |
| `tests/database/test_migration_025_embedding_model_lookup.py` | 36 |
| `tests/database/test_migration_028_add_stat_events_retention_index.py` | 15, 20 |
| `tests/database/test_bayes_storage.py` | 15 |
| `tests/database/test_db_wrapper.py` | 16 |
| `tests/database/migrations/test_migrations.py` | 41 |
| `tests/database/integration/test_multi_source_routing.py` | 14 |
| `tests/database/performance/benchmark_queries.py` | 17, 294, 327 (two are function-level imports) |
| `tests/integration/test_database_operations.py` | 21 |
| `tests/lib/stats/conftest.py` | 11 |
| `tests/lib/stats/test_sql_storage.py` | 11, 695 (function-level) |

`tests/dependencies/test_sqlite_vec.py` references the old path in **docstrings only**
(:11, :116, :162) — Arc 3 item, not a rewrite site.

### 5.3 Live markdown link targets (the Phase 1 gate sweep)

Link-TARGET-ONLY sweep in the code arc (inside `](...)` parens), repo-wide scanned `*.md`.
Verified live-doc link counts into moving files:

| Doc | Link targets into moving files |
|---|---|
| [`AGENTS.md`](../../AGENTS.md) | 3 (:193, :202, :219) |
| `docs/database-README.md` | 12 (:135, :136, :181, :188, :195, :202, :418-:422, :710) |
| `docs/sql-portability-guide.md` | 14 (:113, :1250, :1347-:1350, :1447-:1454) |
| `docs/developer-guide.md` | 0 links (code-fence import at :687 → Arc 3) |
| `docs/llm/database.md` | 2 (:143, :640) |
| `docs/suggestions/improvements.md` | 1 (:459) |
| `docs/suggestions/refactoring.md` | 1 (:52) |
| `docs/plans/embedding-model-lookup-refactor-v1.md` | 3 (:664, :926, :1805) |
| `docs/design/stats-aggregation-v1.md` | 2 (:217, :323) |
| `docs/design/chat-accessibility-tracking.md` | 4 (:345, :347, :349, :355) |
| `docs/database-multi-source.md` | 3 (:584, :848, :878) |

(`docs/archive/**` and `.opencode/` are not scanned — §2.5. This design doc deliberately
uses backticks, never links, for every moving path, so the sweep has nothing to touch
here.)

---

## 6. Phased implementation plan

Each arc = exactly one commit. Hard rules every arc (AGENTS.md): camelCase; docstrings +
type hints on any new code; `./venv/bin/python3` only; `make format lint` before AND after
edits; `make test` after any code change; no `python -c`.

### Phase 0 — This design doc (committed alone)

**Commit message:** `Add lib/db extraction design doc`.

One file: `docs/design/lib-db-extraction-v1.md` (this document). Nothing else.
**Gate:** `make check-docs` (this doc's links all resolve — moving paths are backticked
by construction).

### Phase 1 — CODE (one commit: `Extract SQL providers and DatabaseManager into lib/db`)

**Scope:** the move, the cut, the rewire, the test moves, the link-target sweep, the
docstring neutralization. Steps in order:

1. **Fail-first regression test.** Create `tests/lib/db/providers/test_utils.py` (+ the
   `tests/lib/db/__init__.py` packaging). Run it against the CURRENT code — it must FAIL
   (`"WRONG" != "42"`). Do not proceed until the failure is demonstrated.
2. **Move.** `git mv internal/database/providers lib/db/providers` and
   `git mv internal/database/manager.py lib/db/manager.py` (history-preserving). Write
   the new `lib/db/__init__.py` (§4.2). Create `tests/lib/db/providers/__init__.py` via
   `git mv tests/database/providers/__init__.py` and `git mv` the 4 provider test files.
3. **Cut.** Apply D3 in `lib/db/providers/utils.py` (Protocol + branch). Confirm the
   Phase-1-step-1 test now PASSES; add the edge-case tests (§4.3).
4. **Rewire.** All 48 production sites + 38 test sites per §5 (including the three string
   patch targets and the `create_migration.py` template). A grep for
   `internal[./]database[./]providers|internal[\.]database\.manager` over `*.py` must
   return zero import/patch hits afterwards (docstring path mentions per §5.1 may remain
   until Arc 2).
5. **Link-target sweep.** Mechanical, target-only, per §5.3 — inside markdown link parens
   in scanned `*.md` (including `docs/design/`, `.agents/`). Do NOT attempt prose rewrites
   here.
6. **Neutralize** moved module docstrings (§4.5) and add the `sqlite3.py` name-note line
   (§4.4).
7. **Delete** any straggler `internal/database/providers/` or old `manager.py` remnants —
   dual-home must not survive the commit (the `git mv`s in step 2 already effect this;
   verify with `ls`/`git status`).

**Gates (all must pass before commit):** `make format lint` (flake8 + isort + the
`import main` cycle check — the safety net proving `lib.db` has no internal edge — +
pyright), `make test` (full suite), `make check-docs`.

**Dispatch note:** split into TWO sequential software-developer dispatches to respect
step budgets — (a) the edit arc (steps 1-6), (b) a gate-running finisher (straggler greps,
`make format lint`, `make test`, `make check-docs`, fix-ups, commit). The finisher's
straggler grep list: `from \.\.\.providers`, `from \.\.providers`, `from \.providers`,
`from \.manager import`, `internal\.database\.providers`, `internal\.database\.manager`,
`internal/database/providers`, `internal/database/manager` over `*.py` and scanned
`*.md`.

### Phase 2 — AGENT DOCS (one commit: `Sync agent docs for lib/db extraction`)

**Scope:**

- [`docs/llm/architecture.md`](../llm/architecture.md) — add ADR-022 (full text below,
  ready to paste); update the §2.1 component graph node
  `DatabaseManager (internal/database/manager.py)` → `lib/db/manager.py`.
- [`docs/llm/index.md`](../llm/index.md) — §4 layout map: new `lib/db/` row; adjust any
  internal/database row wording.
- [`docs/llm/database.md`](../llm/database.md) — provider-section rewrite (§"File:"
  headers at :640 area, the `SQLProviderConfig` row :143, portability rule #6 wording
  :301, provider code examples :234/:678, vector-types section :715, testing-tree §).
- [`docs/llm/libraries.md`](../llm/libraries.md) — new `lib/db` entry (house pattern:
  purpose, public API, used-by, dependency firewall note).
- [`AGENTS.md`](../../AGENTS.md) — path refs in the SQL-portability section
  (:193 factory, :202 base, :219 utils) + section preamble wording; architecture
  cheatsheet bullet if it names the provider home.
- [`docs/llm/memories/proxy.md`](../llm/memories/proxy.md) — sqlink refs (:23 file list,
  :113 factory-path explanation).
- [`docs/llm/testing.md`](../llm/testing.md) — the tests tree at :56
  (`tests/database/.../providers/` → `tests/lib/db/providers/`).
- [`docs/llm/teamlead-memory.md`](../llm/teamlead-memory.md) — :117 consumer-map line
  gains a "superseded by ADR-022" note (teamlead memory is append-style; follow its
  conventions).

**Gate:** `make check-docs`.

**Ready-to-paste ADR-022 text:**

```markdown
### ADR-022: SQL providers and DatabaseManager extracted to `lib/db`

**Decision:** The generic SQL layer moved out of `internal/` into a bot-free `lib/db/`
package: all seven provider modules (`base.py`, `sqlite3.py`, `sqlink.py`, `mysql.py`,
`postgresql.py`, `utils.py`, and `__init__.py` with the `getSqlProvider` factory +
`SQLProviderConfig`) now live at `lib/db/providers/` (mirroring the `lib/stt/providers/`
layout), and `DatabaseManager` / `DatabaseManagerConfig` /
`SQLProviderInitializationHook` live at `lib/db/manager.py`. A new `lib/db/__init__.py`
re-exports the public API. `internal/database/` SURVIVES with everything bot-specific —
migrations, repositories, the `Database` wrapper, `stats_storage.py`,
`bayes_storage.py`, internal `utils.py` (`sqlToTypedDict`), `models.py` — and imports
the SQL layer from `lib.db`. Cutover was big-bang: the old locations were deleted in the
same commit the copies landed (git-mv, history preserved); there is no shim and no
dual-home. Dependency direction is now `internal → lib.db → {lib.proxy, lib.utils,
stdlib, 3rd-party}` — no cycles (the `make lint` `import main` gate guards this).

**Why:** the provider layer and `DatabaseManager` contain zero bot knowledge but sat
under `internal/`, blocking `lib/` code from using them. The concrete case is
`lib/stats`: its `StatsStorage` ABC is bot-free, but the only SQL implementation
(`DatabaseStatsStorage`) lives in `internal/database/stats_storage.py` as an
ABC-in-lib / impl-in-internal split that existed solely because the provider layer was
internal. Extracting to `lib/db` makes a `lib/stats` SQL storage possible (that move
itself is a separate follow-up arc). Design doc with the D1–D8 decisions and the full
consumer census: `docs/design/lib-db-extraction-v1.md`.

**The MessageId cut:** `providers/utils.py`'s `convertToSQLite` had the layer's single
`internal.*` import (`from internal.models import MessageId` + an `isinstance` branch).
It was replaced with a module-local `@runtime_checkable` Protocol
(`SQLStringifiable`, `def asStr(self) -> str`) and an
`isinstance(data, SQLStringifiable)` branch. `MessageId.__str__` already returned
`asStr()`, so stored values are identical before and after; the Protocol keeps the
explicit intent and the warning suppression without the internal import. Locked by a
fail-first regression test (`tests/lib/db/providers/test_utils.py`) using a double whose
`asStr()` returns `"42"` while `__str__` returns `"WRONG"`.

**Known temporary deviation (mysql/postgresql):** `lib/db/providers/mysql.py` and
`postgresql.py` moved AS-IS with hard module-level `import aiomysql` / `import asyncpg`
(+ `# type: ignore[reportMissingImports]`), unregistered in the factory. This deviates
from the repo's optional-dependency convention (module-level `try/except ImportError` +
`_AVAILABLE` flag). Rationale: the drivers are not in requirements, both files are
unimportable and untested today, and their class-level annotations
(`Optional[aiomysql.Pool]`) evaluate at import time, making conversion non-trivial.
Convert to the `_AVAILABLE` pattern only when the providers are actually wired.

**Status:** Implemented (Phase 1 code arc + Phase 2/3 doc sync). `make test` green;
`make check-docs` green at every arc.

**References:**

- `docs/design/lib-db-extraction-v1.md` — the ratified design (D1–D8), consumer census,
  phased plan.
- [`database.md`](database.md) — provider section (post-rewrite).
- [`libraries.md`](libraries.md) — the `lib/db` library entry.
```

### Phase 3 — USER DOCS (one commit: `Sync user docs and skill for lib/db extraction`)

**Scope:**

- `docs/database-README.md` — link targets already swept in Phase 1; now fix the
  code-fence import examples (:216, :303, :659) and any prose ("Registered providers"
  section :135-:136, file map :418-:422, :710).
- `docs/sql-portability-guide.md` — the ~21 path references: link targets swept in
  Phase 1; now the code examples and text (:264, :1290, :1559-:1560, :1620, :1662,
  :1751 and surrounding prose).
- `docs/developer-guide.md` — the code-fence import at :687 + nearby prose.
- `docs/database-schema-llm.md` — provider-path mentions (e.g. vector types attribution).
- `docs/examples/multi-source-advanced.toml` — comments referencing where providers live
  (the file's `[database.providers.*]` TOML keys are CONFIG keys and DO NOT change; only
  comments naming code paths do).
- `.agents/skills/add-database-migration/SKILL.md` — the migration template example
  (:63, `from ...providers import ...` → `from lib.db.providers import ...`) and any
  path prose.
- `tests/dependencies/test_sqlite_vec.py` — docstring paths (:11, :116, :162).
- `docs/suggestions/improvements.md:459` — the aiosqlite-provider suggestion's path ref
  (the suggestion itself stays open; only the path updates — dated suggestion logs are
  otherwise left untouched per D8).
- **Archive banner (D8):** add the one-line `> Superseded by ADR-022 (lib/db extraction)
  — paths below predate the move` banner at the top of
  `docs/archive/llm-sessions/lib-stats-gpt-5.5-decision.md` only. No other archive edits.

**Gate:** `make check-docs`.

---

## 7. Risks and gotchas

| Risk / gotcha | Mitigation |
|---|---|
| **Hidden cycle** — `lib.db` accidentally imports `internal.*` (e.g. a stray `internal.utils` in a moved module) | The `make lint` `import main` gate is the safety net; plus the finisher grep for `internal[\.]` under `lib/db/` |
| **String patch targets** — `"internal.database.providers.sqlite3._SQLITE_VEC_AVAILABLE"` monkeypatch strings are not import statements; a pure import-rewrite pass misses them | Explicitly listed (§5.2, `test_sqlite3_vector_search.py:30,74,103`); finisher grep covers dotted-form `internal.database.providers` |
| **`create_migration.py` template drift** — forgetting it means every future migration is born broken | Explicit checklist item (§5.1); Arc 3 also updates the skill's copy of the template |
| **Dual-home survival** — a stale `internal/database/providers/` leftover (e.g. `__pycache__` or a missed file) silently shadows | `git mv` + `git status` verification in step 7; dual-home must not survive the commit (D4) |
| **`__slots__`** — `SQLite3Provider` and `DatabaseManager` define `__slots__`; tests cannot patch attributes on instances (known gotcha class). The move changes nothing about this, but moved tests that patch must use class-level `patch.object` / dotted string targets — which must flip with the move | Existing tests already follow the class-level pattern; verify after the move via `make test` |
| **pyright basic mode + `runtime_checkable` Protocol** | Fine — `isinstance` against a `@runtime_checkable` Protocol is standard typing; no `Any` involved; the Protocol is module-local |
| **`lib/ext_modules/` formatting** | N/A — nothing under `lib/ext_modules/` is touched; plain `make format` covers the moved files |
| **Moved-file test discovery** — `tests/database/providers/` disappears; anything referencing the old test paths (docs, CI) must follow | `docs/llm/testing.md` tree is an Arc 2 item; pytest discovers by `testpaths` glob, no config change needed |
| **`docs/design/` sibling docs link into moving files** (stats-aggregation-v1, chat-accessibility-tracking, embedding-model-lookup plan) | Covered by the Phase 1 link-target sweep (they are scanned live docs); this doc itself links only to surviving files |

---

## 8. Follow-ups (out of scope, tracked here)

1. **`DatabaseStatsStorage` → `lib/stats` — DONE (2026-08-24, commits `d60bb1e5` +
   `ff51563a`; ADR-023).** The separate design pass happened —
   [`lib-stats-sql-storage-extraction-v1.md`](./lib-stats-sql-storage-extraction-v1.md) —
   and resolved the chief design question by taking `DatabaseManager` directly in the
   constructor (per-call `manager.getProvider(dataSource=…, readonly=…)`), so the impl can
   live in lib while staying config-source-aware.
2. **MySQL/PostgreSQL activation arc** — wiring the providers into the factory +
   requirements; includes converting their hard imports to the `_AVAILABLE` convention
   (D5 deviation resolved then).
3. **`SQLinkProvider` test coverage** — no dedicated test module exists under the
   (pre-move) provider test directory (4 files, none sqlink); audit incidental coverage
   and add a real suite when the provider next changes.
4. **ABC-in-lib / impl-in-internal audit — DONE (2026-08-25, commit `c1ac3395`; ADR-024).**
   `lib/cache` was the flagged instance and it WAS extracted:
   [`lib-cache-sql-cache-extraction-v1.md`](./lib-cache-sql-cache-extraction-v1.md) moved
   `GenericDatabaseCache` to `lib/cache/sql_cache.py` over a direct `DatabaseManager`
   (per-call `manager.getProvider(...)`), closing the last split of this shape.

---

## 9. Open questions

**None remaining.** All decisions were ratified by the user on 2026-08-23 and are encoded
as D1–D8; the consumer census corrections (§2.6) are factual updates to the plan's
checklist, not open design questions. Implementation may proceed phase by phase.

---

## 10. References

- [`AGENTS.md`](../../AGENTS.md) — hard rules, SQL-portability section, changelog criteria
- [`docs/llm/architecture.md`](../llm/architecture.md) — ADR-021 is the highest existing
  ADR; ADR-022 is drafted in §6 Phase 2 above
- [`docs/llm/index.md`](../llm/index.md) §4 — layout map (Arc 2 update target)
- [`docs/llm/database.md`](../llm/database.md), [`docs/llm/libraries.md`](../llm/libraries.md),
  [`docs/llm/memories/proxy.md`](../llm/memories/proxy.md) — Arc 2 targets
- [`docs/database-README.md`](../database-README.md), [`docs/sql-portability-guide.md`](../sql-portability-guide.md),
  [`docs/developer-guide.md`](../developer-guide.md), [`docs/database-schema-llm.md`](../database-schema-llm.md) —
  Arc 3 targets
- [`scripts/check_docs.py`](../../scripts/check_docs.py) + [`Makefile`](../../Makefile) —
  the check-docs gate and its scan scope
- [`TODO.md`](../../TODO.md) — "- [ ] move database providers to lib" (close it in Phase 1)
- [`docs/design/httpx2-migration-v1.md`](./httpx2-migration-v1.md) — house-format sibling
  design doc (phased migration with per-arc gates)
