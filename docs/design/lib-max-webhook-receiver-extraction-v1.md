# Design: Extract the Max webhook receiver into `lib/max_webhook_receiver/` (v1)

**Date**: 2026-08-25
**Status:** Implemented — code arcs landed (commits 622eb060..f72f026a); docs arcs landing
**Owner**: TBD
**Scope**: Move the Max webhook receiver implementation — the aiohttp app (`app.py`), the `WebhookUpdatesRepository`, and the `WebhookUpdatesRow` TypedDict — out of `internal/` into a new bot-free `lib/max_webhook_receiver/` package, keeping the deployed command `-m internal.max_webhook_receiver` byte-identical via a thin internal launcher. The lib package becomes the single owner of the canonical `webhook_updates` DDL; `migration_019` delegates to it in place; the receiver's startup self-heals its table instead of triggering the full migration chain. Big-bang, no re-export shims, docs synced across arcs.
*(Amended 2026-08-25, amendment #2: the thin internal launcher is GONE — the launcher
itself moves to `lib/max_webhook_receiver/__main__.py`, reads a single TOML config file
directly (no `ConfigManager`), `internal/max_webhook_receiver/` is deleted entirely, and
the deployed command becomes `./venv/bin/python3 -m lib.max_webhook_receiver --config
<path> [--dotenv-file <path>]`. The "byte-identical command" clause above is superseded;
see D17.)*

> This is a **design document**, not an implementation. Every `file:line` claim below was
> re-verified against source on 2026-08-25 with fresh reads and greps (patterns:
> `\.webhookUpdates\b`, `WebhookUpdatesRow`, `internal[./]max_webhook_receiver`,
> `internal\.database\.repositories\.webhook_updates`, `CREATE INDEX`, `### ADR-0`).
> Paths that do not exist today appear only in backticks/code fences
> ([`scripts/check_docs.py`](../../scripts/check_docs.py) skips those — mechanics verified in
> [`lib-db-extraction-v1.md`](./lib-db-extraction-v1.md) §2.5, which this doc cross-references
> instead of re-deriving).
>
> **Ratified forks (user, 2026-08-25 — FIXED, not proposals):** destination = top-level
> `lib/max_webhook_receiver/` (NOT nested under lib/max_bot); entry = thin internal launcher
> with the `-m` command unchanged; schema = lib-owned canonical DDL with migration_019 in-place
> delegation and receiver self-heal. Everything else below is the architect's resolution of the
> open design points within those constraints.
>
> *(Amended 2026-08-25, amendment #2: the "entry" fork is superseded — entry = lib-side
> launcher module, new command `-m lib.max_webhook_receiver --config <path>
> [--dotenv-file <path>]`, no `ConfigManager`; D17.)*

## Amendments (2026-08-25 — full database independence, user-ratified)

After review of this PROPOSED doc, the user amended the ratified design: **the webhook
receiver gets FULL database independence — it must not use the bot's migrations or the bot's
database at all.** The receiver now owns its database file (`webhook_receiver_data.db`)
configured via a new `[webhook-receiver.database]` section shaped exactly like the bot's
`[database]`; the launcher builds a `DatabaseManager` from it as a pure passthrough (D12).
The `[webhook-receiver]` `datasource` key and `createApp(datasource=...)` are removed (D13),
and a new bot-side `migration_029` drops the `webhook_updates` table from the main bot
database (D14). The receiver's startup self-heal now creates BOTH the table and its index —
superseding D4's table-only reasoning, which relied on the bot's migration chain eventually
indexing a shared table that no longer exists (D15). D11's CHANGELOG skip is flipped to a
`### Changed` entry because the amendment is user-visible for webhook-mode deployments (D16).
The new decisions D12–D16 below carry the full detail; superseded decision bodies (D4, D11)
are preserved in place with dated supersession pointers, per house convention
(see [`docs/design/stats-display-v1.md`](./stats-display-v1.md) amendment blocks).

## Amendments #2 (2026-08-25 — full-lib launcher with its own config file, user-ratified)

After a second review, the user amended the design again: **the receiver launcher drops
`ConfigManager` entirely — it reads a single given TOML config file directly, and the whole
package moves to lib.** `internal/max_webhook_receiver/` is deleted in full (all three
files); the launcher lives at `lib/max_webhook_receiver/__main__.py` and the deployed
command becomes `./venv/bin/python3 -m lib.max_webhook_receiver --config <path>
[--dotenv-file <path>]` (module-invocable precedent: `lib.stats.stats_pages`) — D17.
`substituteEnvVars` + its `replaceMatchToEnv` helper move from
`internal/config/manager.py` to `lib/utils/utils.py`, with `ConfigManager` importing the
function from lib (internal→lib legal; single source of truth, no duplication) — D18.
The receiver's config becomes its OWN single TOML file (`[webhook-receiver]`-rooted,
including the D12 `[webhook-receiver.database]` section, whose placement in the bot
defaults file is superseded); `configs/00-defaults/webhook-receiver.toml` stays
bot-read-only, with a cross-reference comment — D19. D2 (thin internal launcher +
byte-identical command invariant) is superseded by D17; D12's config-file placement
clause and D16's CHANGELOG text carry in-place dated notes; the D12/Gate-1B
real-`ConfigManager` integration test is superseded by the §5.3 `TestLauncherConfig`
real-TOML tests. Superseded bodies are preserved per house convention. The new decisions
D17–D19 below carry the full detail.

---

## 1. Context and goal

ADR-013 ([`docs/llm/architecture.md`](../llm/architecture.md):443-483) established the
two-process webhook architecture: a standalone aiohttp receiver accepts Max webhook POSTs,
buffers them in `webhook_updates`, and serves them to the bot via a local `GET /updates` that
speaks the Max API protocol. **That architecture does not change one bit in this extraction** —
same two processes, same table, same HTTP contract, same marker protocol, same config keys,
same deployed command. Only the code location and the schema-ownership seam move.
*(Amended 2026-08-25: one thing DOES change — the table moves to the receiver's OWN database
file, so "same config keys" loses the `datasource` key and gains the
`[webhook-receiver.database]` section; see D12/D13. The HTTP contract, marker protocol, and
deployed command are still unchanged.)*
*(Amended 2026-08-25, amendment #2: the deployed command is NO LONGER unchanged either —
`-m lib.max_webhook_receiver --config <path>` replaces `-m internal.max_webhook_receiver`,
and the receiver reads its OWN config file rather than the ConfigManager hierarchy (D17/D19).
The HTTP contract and marker protocol still stand.)*

Why move it at all:

1. **The receiver is not bot code.** After the ADR-022/023/024 arc series moved the SQL
   provider layer, decode utils, stats storage, and the SQL cache into `lib/`, the receiver's
   implementation has exactly three `internal.*` imports left (§2.1) — all launcher-side
   config/DB wiring, none in the handlers. Everything the receiver *does* (aiohttp handlers,
   HMAC checks, marker protocol, TTL cleanup, provider-level SQL) is bot-free already.
2. **The receiver is a deployment peer, not a bot feature.** It runs as its own process
   (OpenRC init script per [`docs/max-webhook-setup.md`](../max-webhook-setup.md):156-199;
   the doc is OpenRC-only — "systemd" dropped 2026-08-25, Gate-1B fix round),
   may point at a different datasource, and must keep working when the bot is down. A
   `lib/` home states that independence structurally. *(Amended 2026-08-25: the receiver no
   longer "may" point elsewhere — it owns a separate database file by default and never sees
   the bot's `[database]` config at all; D12.)*
3. **`WebhookUpdatesRepository` is receiver-specific**, not generic — it must not go to
   `lib/db/` — but it also has no business in the bot's `Database` wrapper once the receiver
   owns it: today `internal/database/database.py:257` constructs `self.webhookUpdates` for
   exactly one consumer family (the receiver's `app.py`; verified §2.5 — zero bot-side
   callers).
4. **The migration-race wart dies.** Today the receiver triggers the bot's full migration
   chain at startup (`app.py:305` → `database.manager.getProvider()` → the wrapper's
   migration init-hook registered at `internal/database/database.py:268`). Two processes
   racing migrations is a known limitation
   ([`docs/llm/memories/max-webhook-support.md`](../llm/memories/max-webhook-support.md):54).
   With lib-owned DDL + self-heal, the receiver never runs migrations at all.
   *(Amended 2026-08-25: the severance is now by OWNERSHIP, not merely by bypassing the
   wrapper — the receiver has its own `DatabaseManager` over its own config section and its
   own DB file, so it cannot race the bot's chain even in principle; D12. The old
   "no cross-process migration guard" limitation is MOOT.)*

**Goal in one paragraph:** create `lib/max_webhook_receiver/` holding the aiohttp app, the
repository (manager-injected, provider-level SQL), the row TypedDict, and the canonical
`webhook_updates` DDL; shrink `internal/max_webhook_receiver/` to a thin launcher that parses
args, loads config, guards the secret placeholder, constructs a `DatabaseManager` + repository
directly, and hands off to `createApp` + `web.run_app`; edit `migration_019` in place to
delegate its DDL to lib; delete the internal repository, its export, and the
`Database.webhookUpdates` attribute in the same commit; relocate the tests per the mirror
rule; then land ADR-025 and the documentation sync. `make check-docs` green at every commit;
one commit per green arc.
*(Amended 2026-08-25: the launcher's `DatabaseManager` is built from the NEW
`[webhook-receiver.database]` config section — the receiver's OWN database file
(`webhook_receiver_data.db`), a pure config passthrough with zero dict-building code (D12);
the `datasource` key and `createApp(datasource=...)` die (D13); a NEW bot-side
`migration_029` drops `webhook_updates` from the main bot database while `migration_019`
keeps its delegated `up()` as history (D14); and a `### Changed` CHANGELOG entry lands with
Arc 1 (D16).)*
*(Amended 2026-08-25, amendment #2: "shrink `internal/max_webhook_receiver/` to a thin
launcher" is superseded — the launcher IS the lib module now (`__main__.py`, §4.3) and
`internal/max_webhook_receiver/` is deleted entirely; config comes from the receiver's OWN
TOML file via `load_dotenv` + `tomllib` + lib-side `substituteEnvVars` (D17/D18/D19); and
the D16 CHANGELOG line gains the new invocation (dated note in D16).)*

### 1.1 Goals

- **G1** — `lib/max_webhook_receiver/` is bot-free: zero `internal.*` imports (guarded by the
  `make lint` `import main` cycle gate + the residual grep in §6 Arc 1).
- **G2** — The deployed command `-m internal.max_webhook_receiver` and its observable
  behavior (endpoints, status codes, marker protocol, cleanup cadence, TLS, config keys) are
  unchanged. The only runtime-observable deltas are deliberate (D4/D9): the receiver no longer
  runs the migration chain, and it self-heals its table on startup.
  *(Amended 2026-08-25: config keys are NOT all unchanged — `datasource` is removed and
  `[webhook-receiver.database]` added (D12/D13); the receiver self-heals table AND index
  (D15) in its OWN database file.)*
  *(Amended 2026-08-25, amendment #2: G2's command invariance is SUPERSEDED by D17 — the
  command is now `./venv/bin/python3 -m lib.max_webhook_receiver --config <path>
  [--dotenv-file <path>]`. The behavioral invariants (endpoints, status codes, marker
  protocol, cleanup cadence, TLS) stand unchanged.)*
- **G3** — Single source of truth for `webhook_updates` DDL: lib owns the strings;
  `migration_019` imports them; the receiver warm-up uses the portable table subset.
  *(Amended 2026-08-25: the receiver warm-up now uses the FULL DDL subset — table + index
  (D15); the strings gain a second migration consumer, `migration_029.down()` (D14).)*
- **G4** — `internal/` shrinks honestly: the `Database` wrapper, `repositories/__init__.py`,
  and `internal/database/models.py` lose their webhook-only members in the same commit they
  move (no dead exports).

### 1.2 Non-goals

- **NG1** — No change to ADR-013's architecture, the `webhook_updates` schema itself, the
  marker protocol, the `[webhook-receiver]` config surface, or `lib/max_bot/client.py`
  (`basePollingUrl`/`_makeLocalRequest` untouched). *(Amended 2026-08-25: the config surface
  DOES change — `datasource` removed, `[webhook-receiver.database]` added (D12/D13); the
  bot-side storage location changes (migration_029, D14). The schema itself, marker protocol,
  and `lib/max_bot/client.py` remain untouched.)*
  *(Amended 2026-08-25, amendment #2: the config surface SPLITS in two — the receiver reads
  its OWN single TOML file (D19) while the bot's hierarchy keeps only the bot-read keys;
  `lib/max_bot/client.py` still untouched.)*
- **NG2** — No generic-DB work: `WebhookUpdatesRepository` stays receiver-specific (does NOT
  go to `lib/db/`); `BaseRepository` is not moved to lib (D6).
- **NG3** — No new dependency-management changes: `aiohttp==3.14.3` is already a direct pinned
  dependency (promoted during the original webhook work,
  [`docs/llm/memories/max-webhook-support.md`](../llm/memories/max-webhook-support.md):29);
  `python-dateutil` likewise already direct.
- **NG4** — No restructuring of the receiver's HTTP semantics (no new auth modes, no
  long-poll rework — the 0.5s busy-poll and the types-param gap carry over; §8).
- **NG5** — No config-file changes: `configs/00-defaults/webhook-receiver.toml` is untouched.
  *(Amended 2026-08-25: SUPERSEDED — `configs/00-defaults/webhook-receiver.toml` IS edited
  (remove the `datasource` key + its commented example; add the
  `[webhook-receiver.database]` section per D12/D13). `configs/00-defaults/00-config.toml`
  (the bot's `[database]`) stays untouched.)*
  *(Amended 2026-08-25, amendment #2: the previous note is itself superseded — the
  `[webhook-receiver.database]` section does NOT land in the defaults file; it lives in the
  receiver's OWN config file (D19). The defaults file keeps the bot-read keys only, loses
  the receiver-only keys, and gains a cross-reference comment (row 17 re-cut).)*

---

## 2. Verified grounding (current state)

Facts verified against source on 2026-08-25. Line numbers are current. This section resolves
every marked-VERIFY point from the planning brief; the Arc 1 census in §5 is authoritative
for the implementer.

### 2.1 The moving package and its outbound imports

`internal/max_webhook_receiver/` is three files, 483 lines total:

| File | Lines | Outbound imports | Fate |
|---|---|---|---|
| `__init__.py` | 6 | none (docstring only) | **STAYS** internal (docstring touch-up, D2) |
| `__main__.py` | 104 | stdlib (`argparse`, `logging`, `ssl`); `aiohttp.web`; `internal.config.manager.ConfigManager` (:15); `internal.database.Database` (:16); `.app.createApp` (:18) | **STAYS**, rewritten as thin launcher (D2) |
| `app.py` | 373 | stdlib + `aiohttp.web`; `internal.database.Database` (:34) — the ONLY internal import | **MOVES** to `lib/max_webhook_receiver/app.py` (D5) |

Exactly 3 internal imports total, as the brief stated. `app.py` touches the `Database`
wrapper in exactly three ways: `database.webhookUpdates.<method>` (5 call sites: :121, :189,
:201, :218, :251), `database.manager.getProvider()` (:305, warm-up), and
`database.manager.closeAll()` (:318, shutdown). All three are replaced by
repository/manager injection (D5).
*(Amended 2026-08-25, amendment #2: the Fate column above reflects amendment #1 and is
superseded for the launcher rows — `app.py` still MOVES (D5), but `__init__.py` and
`__main__.py` no longer STAY internal: the whole package is DELETED and the launcher is
rebuilt as `lib/max_webhook_receiver/__main__.py` (D17). The Lines/imports columns stay
valid as TODAY's-code grounding.)*

### 2.2 `WebhookUpdatesRepository` and `BaseRepository` (resolution 3)

`internal/database/repositories/webhook_updates.py` (318 lines) imports only stdlib
(`datetime`, `logging`, `typing`), `dateutil.parser`, and lib-side `lib.db` (`utils` as
dbUtils, `manager.DatabaseManager`, `providers.ParametrizedQuery`), plus the two internal bits:
`..models.WebhookUpdatesRow` (:27) and `.base.BaseRepository` (:28). Public surface:
`__init__(manager)`, static `_parseMarker(marker)`, `addUpdate(...) -> bool`,
`getUnprocessedUpdates(...) -> List[WebhookUpdatesRow]`, `markProcessed(...)`,
`markProcessedBeforeMarker(...)`, `deleteProcessedOlderThan(...) -> bool`. Every method routes
`await self.manager.getProvider(dataSource=..., readonly=...)`; all SQL is provider-level
portable (`:named` placeholders, `applyPagination`, app-side timestamps).

`BaseRepository` ([`internal/database/repositories/base.py`](../../internal/database/repositories/base.py),
104 lines) is **as thin as it looks**: an ABC whose entire executable content is
`__slots__ = ("manager",)` and `self.manager = manager` in `__init__` — everything else is
docstring. It has no methods, no lifecycle, no contract beyond holding the manager. **Decision
(D6): inline, don't move.** Moving it to lib would (a) drag an internal-layer abstraction into
a bot-free package where nothing else uses it (15 other repositories still subclass the
internal one), and (b) create a pointless `lib.max_webhook_receiver.base` for one consumer.
The moved repository declares `__slots__ = ("manager",)` and its own `__init__` verbatim, with
a docstring note that it deliberately does not subclass `BaseRepository` because it lives
outside the internal repository tree.

### 2.3 `WebhookUpdatesRow` importer sweep (resolution 4)

Defined at [`internal/database/models.py`](../../internal/database/models.py):310-330; pure
TypedDict (only `datetime` + `Optional` in scope). Complete importer census (grep
`WebhookUpdatesRow`, all hits inspected):

| Consumer | Site(s) | Arc 1 action |
|---|---|---|
| `internal/database/repositories/webhook_updates.py` | :27, :148, :171, :201 | moves with the repository; import flips to `.models` |
| `tests/max_webhook_receiver/test_app.py` | :24 (import), :40 (annotation) | flips to `lib.max_webhook_receiver.models` |
| `tests/database/repositories/test_webhook_updates.py` | :13, :231, :247 | flips in the moved file |
| `docs/database-schema.md` | :886, :1055 — md links to `internal/database/models.py:310` | repoint (Arc 2 prose pass; links still resolve — see §5.4) |
| `docs/database-schema-llm.md` | :547 (link), :1478 (table row) | Arc 2 |
| `docs/llm/database.md` | :65, :335, :478, :830 (prose/tables) | Arc 2 |
| archive / `.opencode` / teamlead-memory | prose only, not scanned or historical | untouched (D9 history-immutability lesson, cache-arc) |

Big-bang, no re-export shim from `internal.database.models` — repo precedent (lib-db D4).
The three production/test import flips are enumerated; nothing else imports it.

### 2.4 `Database.webhookUpdates` caller verification (resolution 5)

Grep `\.webhookUpdates\b` across production + tests, all 60 `.py` hits inspected (6 internal + 54 tests):

- **Production callers: exactly the receiver's `app.py`** (5 sites, §2.1). Zero bot-side,
  zero service-side, zero script-side callers. The only other production hit is the
  construction itself at [`internal/database/database.py`](../../internal/database/database.py):257.
- Test callers: `tests/max_webhook_receiver/test_app.py` (mock attribute wiring, moves+reshapes
  with the app) and `tests/database/repositories/test_webhook_updates.py`
  (`repo = testDatabase.webhookUpdates` ×14 — moves+reshapes with the repository, §5.3).
- Doc callers: prose/tables only (architecture.md :455/:476, database.md :64/:478/:830,
  database-schema-llm.md :549, database-schema.md :1090 — the last is a link, §5.4) — Arc 2/3.

**Verdict: receiver-only, as expected.** D8 specs full removal from the internal wrapper:
import at database.py:57, `__slots__` entry :134, class annotation + docstring :191-192,
construction :257; plus the export trio in
[`internal/database/repositories/__init__.py`](../../internal/database/repositories/__init__.py)
(docstring :31, import :69, `__all__` :88) and deletion of the repository file itself.
`internal/database/__init__.py` does not export the repository (verified — `__all__` is
`Database`, `ParametrizedQuery` only), so it needs no edit.

### 2.5 Launcher config surface and the `Database` cut (resolutions 1–2)

`__main__.py:60-78` reads exactly 8 keys from `[webhook-receiver]` (`listen-host`,
`listen-port`, `secret`, `get-updates-secret`, `webhook-path`, `datasource`,
`enable-cleanup`, `mark-on-subsequent-poll`) plus the `${VAR}` placeholder guard (:76-78) and
the TLS pair (:94-95). All of this **stays in the launcher** (D2): the guard protects a config
*value*, and `tests/max_webhook_receiver/test_main.py` (99 lines, 3 tests) tests the launcher
function — that test file therefore **stays at its current path** (mirror rule: tests for
`internal/X/__main__.py` live at `tests/X/test_main.py`) with its patch targets updated (§5.3).

The one structural cut in the launcher: `Database(configManager.getDatabaseConfig())` (:80,
with `# pyright: ignore[reportArgumentType]` because
[`internal/config/manager.py`](../../internal/config/manager.py):313 returns `Dict[str, Any]`)
becomes `DatabaseManager(configManager.getDatabaseConfig())` with the same ignore comment.
This is what severs the receiver from the migration chain: the migration init-hook is
registered by the internal `Database` *wrapper* (database.py:268), not by
[`lib/db/manager.py`](../../lib/db/manager.py) — constructing the manager directly means no
hook, no migrations, ever, from the receiver process. `DatabaseManager.__init__` accepts the
same config dict shape (manager.py:64-93; the `testDatabase` fixture in
[`tests/conftest.py`](../../tests/conftest.py):117-128 builds exactly this shape).

**Amended 2026-08-25 (D12/D13):** the launcher reads exactly **7** keys from
`[webhook-receiver]` (the 8 above minus `datasource`) plus the guard and TLS pair, and the
`DatabaseManager` config source changes: NOT `configManager.getDatabaseConfig()` (the bot's
`[database]` — which the receiver must not see) but the receiver's OWN section, reached by
inline nested lookup off the launcher's existing
`webhookConfig = configManager.config.get("webhook-receiver", {})` line (the current-tree
idiom, `__main__.py:66`):

```python
dbConfig = webhookConfig.get("database", {})
manager = DatabaseManager(dbConfig)  # pyright: ignore[reportArgumentType]
```

*(Corrected 2026-08-25, Gate-1B delta review: an earlier sketch read
`ConfigManager.get("webhook-receiver.database", {})` on the launcher's manager instance,
which would silently return the `{}`
default — `ConfigManager.get` is literal-key-only, no dot navigation
([`internal/config/manager.py`](../../internal/config/manager.py):280-282 docstring) — so
`DatabaseManager({})` would raise `ValueError` and the receiver would crash at startup with
shipped defaults. Inline nested `.get()` chaining is the sanctioned pattern (precedent:
`getStatsPagesConfig`, manager.py:525-528), pinned by the §5.3 real-`ConfigManager`
integration test.)* The `config` attribute is typed `Dict[str, Any]`
([`internal/config/manager.py`](../../internal/config/manager.py):130), so the nested
lookup's result lands in the same looseness bucket as `getDatabaseConfig() -> Dict[str, Any]`
and the `# pyright: ignore[reportArgumentType]` comment carries over; there is
zero dict-building code in the launcher — `DatabaseManager.__init__`
([`lib/db/manager.py`](../../lib/db/manager.py):64-93) already fail-fast validates the shape
(requires `providers` + `default`, the default must exist in `providers`; `chatMapping`
optional and defaulted). Config-surface census for
[`configs/00-defaults/webhook-receiver.toml`](../../configs/00-defaults/webhook-receiver.toml):
16 keys today (14 live + the 2 commented TLS pairs) → after the amendment **22** (13 live + 2
commented TLS after removing `datasource`, plus the 7-key `[webhook-receiver.database]`
section: `default`, `provider`, `dbPath`, `readOnly`, `timeout`, `useWal`, `keepConnection` —
exact TOML in D12).

*(Amended 2026-08-25, amendment #2: the navigation SOURCE above — `configManager.config` —
is superseded: the launcher has NO `ConfigManager`; it navigates its OWN `tomllib`-parsed
dict (D17, §4.3). The inline `.get()` chaining idiom, the zero-dict-building rule, and the
`# pyright: ignore[reportArgumentType]` carry-over all survive unchanged (the parsed dict is
the same looseness bucket `ConfigManager.config` was). The Gate-1B real-`ConfigManager`
integration test that pinned the navigation is superseded by the §5.3 `TestLauncherConfig`
real-TOML tests. The `[webhook-receiver.database]` section's HOME moves from the bot
defaults file to the receiver's OWN file, so the "→ 22 keys" census above now describes the
receiver's own config file (D19), not `configs/00-defaults/webhook-receiver.toml`.)*
*(Corrected 2026-08-25, Gate-1B fix round: that closing clause is wrong on the count — the
receiver's OWN file carries 7 live receiver-read keys + the 2 commented TLS pairs + the
7-key `[webhook-receiver.database]` section = **16 keys**, not 22. The 22 figure was the
amendment-#1 BOT-defaults-file count (13 live + 2 commented TLS + 7 database) including
the 6 bot-only live keys that D19 strips out of the receiver's file; the bot defaults file
itself keeps 8 live bot-read keys.)*

Injection-shape precedent for the lib side: `DatabaseStatsStorage.__init__(manager:
DatabaseManager, eventType: str, *, dataSource: str)`
([`lib/stats/sql_storage.py`](../../lib/stats/sql_storage.py):64) and
`GenericDatabaseCache(manager, namespace, ...)` ([`lib/cache/sql_cache.py`](../../lib/cache/sql_cache.py))
— manager + **typed scalar params**, no config system in lib, no TypedDict needed. D5 follows
this exactly.

### 2.6 `migration_019` and the index-portability wrinkle (resolution 6)

[`migration_019_add_webhook_updates_table.py`](../../internal/database/migrations/versions/migration_019_add_webhook_updates_table.py)
(106 lines): `up()` is a single `batchExecute` of two `ParametrizedQuery` DDL strings —
`CREATE TABLE IF NOT EXISTS webhook_updates (...)` and `CREATE INDEX IF NOT EXISTS
idx_webhook_updates_unprocessed ON webhook_updates (processed, received_at)`; `down()` drops
index then table, both `IF EXISTS`. Column set: `id TEXT PK`, `received_at TIMESTAMP NOT
NULL`, `update_type TEXT NOT NULL`, `raw_json TEXT NOT NULL`, `processed INTEGER NOT NULL
DEFAULT 0` (portable int-literal default), `processed_at TIMESTAMP` (app-set, no DB defaults —
migration-013 rule).

**The wrinkle:** `CREATE TABLE IF NOT EXISTS` is portable across SQLite/PostgreSQL/MySQL;
`CREATE INDEX IF NOT EXISTS` is not (MySQL rejects it). House precedent, verified: **13 of the
shipped migrations use `CREATE INDEX IF NOT EXISTS`** (migrations 001, 004, 012, 013, 014,
015, 016, 018, 019, 020, 024, 025, 028 — grep `CREATE INDEX`). The repo's portability posture
is: migrations own index DDL and may use the idempotent form; MySQL activation will need a
provider hook for it (a known future arc, same bucket as the dormant MySQL/PostgreSQL
providers). The self-heal path must NOT inherit that wart — resolution in D4.
*(Amended 2026-08-25: the D4 resolution is SUPERSEDED by D15 — with the receiver's own
database (D12) there is no migration side that would ever create the index, so the self-heal
creates BOTH table and index; the unportable form is kept out of lib *runtime invention* by
having `schema.py` own the string and migrations/self-heal share it.)*

### 2.7 Tests census (resolution 8)

| File | Lines / tests | Uses | Arc 1 action |
|---|---|---|---|
| `tests/max_webhook_receiver/test_main.py` | 99 / 3 | patches `receiverMain.{parseArgs, ConfigManager, Database, createApp, web}` | **STAYS**; patch-target updates only (§5.3) |
| `tests/max_webhook_receiver/test_app.py` | 456 / 22 | imports `internal.database.Database` (:23), `internal.database.models.WebhookUpdatesRow` (:24), `internal.max_webhook_receiver.app` names (:25); function-level `from internal.max_webhook_receiver import app as appModule` (:404, :434 — `asyncio` patch targets) | **MOVES** to `tests/lib/max_webhook_receiver/test_app.py` + reshape (§5.3) |
| `tests/database/repositories/test_webhook_updates.py` | 355 / 14 | `testDatabase: Database` fixture (conftest :97-133); `repo = testDatabase.webhookUpdates` ×14 | **MOVES** to `tests/lib/max_webhook_receiver/test_repository.py` + fixture swap (§5.3) |
| `tests/bot/max/test_webhook_mode.py` | — | bot-side config gating only | untouched |
| `tests/lib/max_bot/test_client_webhook.py` | — | client-side, already lib | untouched |

String patch targets containing the dotted module path — complete list (grep
`internal\.max_webhook_receiver` in `*.py`): test_app.py:25/:404/:434 and test_main.py:17.
Nothing else in production or tests patches into the receiver by dotted path. The
lib-db-arc lesson (string targets are not import statements; a pure import sweep misses them)
is covered by these four sites plus the residual greps in §6.

**Amended 2026-08-25 (D13/D12):** two census rows change shape. (1) `test_app.py` — the
`TestDataSourceForwarding` class (3 tests, :332-382) is REMOVED (the `datasource` routing it
pins no longer exists) and replaced by one small test asserting default-provider usage via
the receiver's own `DatabaseManager`; net test count 22 → 20. (2) `test_main.py` — its
`_patchMainEnv` currently patches `receiverMain.Database` (:53); after the amendment it
patches `receiverMain.DatabaseManager` + `receiverMain.WebhookUpdatesRepository` (the launcher
no longer imports the internal `Database` wrapper at all), and the happy-path mock moves from
`mockConfigManager.getDatabaseConfig.return_value = {}` (:93) to the dict-attribute idiom the
suite already uses (:71): `mockConfigManager.config = {"webhook-receiver": {...}}` with a
nested `database` table shaped like the D12 TOML — mock the `config` ATTR, never the `.get`
method (the launcher navigates the attribute; method mocks are what let a navigation
regression hide — see the §5.3 real-`ConfigManager` integration test).
Additionally `tests/dependencies/test_dateutil.py` joins the census (:9, :85, :88 — docstrings
cite `internal/database/repositories/webhook_updates.py`; the path updates on the move,
assertions untouched).

**Amended 2026-08-25, amendment #2:** `tests/max_webhook_receiver/test_main.py` no longer
stays — the whole `tests/max_webhook_receiver/` directory dies with the package. The file
MOVES to `tests/lib/max_webhook_receiver/test_main.py` and is REWRITTEN: no `ConfigManager`
patches at all; real temp TOML files + temp dotenv files (`tmp_path`) drive the launcher;
the amendment #1 `TestLauncherDatabaseConfigNavigation` real-`ConfigManager` integration
test is superseded and its intent absorbed into the new `TestLauncherConfig` class (§5.3).

### 2.8 Docs blast radius and check-docs mechanics

20 md files reference the receiver (teamlead census, :151). Per
[`scripts/check_docs.py`](../../scripts/check_docs.py) mechanics (lib-db design doc §2.5:
file-link resolution only, `#anchor`/`?query`/`:line` suffixes stripped, archive not
scanned), the Arc-1-gate-relevant split is:

- **Gate-breaking at Arc 1** (links into the *deleted* repository file):
  `docs/database-schema.md:1090`, `docs/database-README.md:512`,
  `docs/developer-guide.md:612` (a `/internal/...` root-absolute form).
- **Still-resolving but stale** (dir links into `internal/max_webhook_receiver/`, which
  survives as the launcher; `models.py:310` anchors whose `:310` is stripped so they
  resolve): AGENTS.md:17/:167, docs/llm/index.md:289, docs/llm/architecture.md:445,
  docs/llm/libraries.md:867, docs/llm/configuration.md:789,
  docs/design/stats-aggregation-v1.md:174, docs/database-schema.md:886/:1055,
  docs/database-schema-llm.md:547 — Arc 2/3 repoints during their prose passes.
  *(Amended 2026-08-25, amendment #2: "survives as the launcher" no longer holds — the
  package is deleted (D17), so this whole bucket becomes gate-breaking at Arc 1 and is
  repointed then; see the §5.4 amendment #2 note for the exact mechanics.)*
- **Prose-only**: developer-guide.md:2128/:236, memories/max-webhook-support.md,
  teamlead-memory.md, design siblings (stats-display-v1.md:1321, stt-v1.1.md:268 —
  historical design prose, left per the census-immutability lesson).

One knock-on to schedule explicitly (Arc 2): deleting `WebhookUpdatesRow` from models.py
shifts every later TypedDict's line anchor up ~21 lines — the exact anchor-rot class that was
hand-repaired on 2026-08-25 (SpamMessageDict :332→~311, ChatSummarizationCacheDict :355→~334,
CacheStorageDict :380→~359, UserMemoryDict :545→~524, ModelDict :596→~575, per the same
methodology used in the last repair). The Arc 2 database-schema pass must re-anchor these, in
both schema docs (dual-doc rule).

**Amended 2026-08-25 (D12/D14) — schema-docs REMOVAL, not repointing.** With the receiver
owning its database, `webhook_updates` leaves the bot's schema docs ENTIRELY instead of being
repointed: `docs/database-schema.md` (:37 TOC, :161 migration-table row — row stays but gains
the 029 drop note, :868-884 table section, :1090 wrapper row),
`docs/database-schema-llm.md` (:530-549 table section + :1478 models-map row),
`docs/database-README.md` (:92 table list, :512-513 repository entry),
`docs/llm/database.md` (:64-65 wrapper rows, :335 models row, :478 repository row, :830
migration_019 note — now also mentioning 029). The receiver's OWN schema gets documented for
operators in [`docs/max-webhook-setup.md`](../max-webhook-setup.md) (own DB file, DDL
reference) with `schema.py`'s module docstring as the canonical in-code reference — scheduled
in the Arc 2/3 lists below. `docs/llm/architecture.md` (:125 repository count/list, :445,
:453, :458, :470-471, :476, :971) and ADR-013's shared-DB wording gain the two-databases
correction; AGENTS.md (:18, :169) + developer-guide.md (:236, :612) as already scoped.

### 2.9 ADR numbering (resolution 10)

Highest existing ADR in [`docs/llm/architecture.md`](../llm/architecture.md) is ADR-024
(`GenericDatabaseCache`, :881). **This design allocates ADR-025**; ready-to-paste text is
drafted in §6 Arc 2.

### 2.10 `substituteEnvVars` importer census + invocation-site census (amendment #2)

**`substituteEnvVars` sweep** — grepped 2026-08-25
(`grep -rn 'substituteEnvVars|replaceMatchToEnv' --include='*.py'`, venv excluded); this is
the complete basis for the D18 move:

| Site | Role | D18 action |
|---|---|---|
| `internal/config/manager.py:41-52` | `replaceMatchToEnv` definition | MOVES to `lib/utils/utils.py` |
| `internal/config/manager.py:55-80` | `T = TypeVar("T")` + `substituteEnvVars` definition | MOVES to `lib/utils/utils.py` |
| `internal/config/manager.py:130` | sole production call site (`self.config: Dict[str, Any] = substituteEnvVars(self._loadConfig())`) | rewires to the lib import (via the existing `import lib.utils as utils`, :34) |
| `internal/config/__init__.py:16` | docstring "Main exports" mention only — `__all__` is `["ConfigManager"]`, no actual re-export | docstring line repointed at the lib location |
| tests | **ZERO importers/patchers** of the internal/config function (verified — no test references or patches `internal.config.manager.substituteEnvVars`) | no test sweep needed |
| `lib/aurumentation/collector.py:23` | a DIFFERENT, module-local `substituteEnvVars(value, loadDotenv=True)` (golden-recording semantics) | NOT an importer, NOT a collision (distinct module); untouched, out of scope |
| `lib/aurumentation/recorder.py:241` | `_substituteEnvVars` — a PRIVATE method, substring hit of the stated grep pattern (distinct method, importer of neither public function) | untouched, out of scope *(row added 2026-08-25, Gate-1B fix round — the sweep's completeness claim requires it)* |
| `tests/lib/{yandex_search,openweathermap}/golden/collect.py` (:21/:20), `tests/lib/{divination,stt}/golden/scenario_runner.py` (:17/:11) | importers of the *aurumentation* function only | untouched |

[`lib/utils/utils.py`](../../lib/utils/utils.py) already imports `os` + `re` (:8-9); the
move adds only `TypeVar` + `cast` to its `typing` import — no new dependency edges.

**Deployed-command invocation census** (grepped 2026-08-25; production code has no
invocation of `-m internal.max_webhook_receiver` besides the package itself — all hits are
docs). Complete list — **7 genuine invocation sites** across 6 files, plus two
informational max-webhook-setup.md rows (caution + prose-rework; see the correction note
below the table):

| Site | Today | Rewrite arc |
|---|---|---|
| [`AGENTS.md`](../../AGENTS.md):23 | bare `./venv/bin/python3 -m internal.max_webhook_receiver` | Arc 2 |
| [`docs/llm/architecture.md`](../llm/architecture.md):470 | ADR-013 receiver-process bullet (`python -m internal.max_webhook_receiver`) | Arc 2 |
| [`docs/llm/architecture.md`](../llm/architecture.md):968 | receiver component-tree diagram invocation (`python -m internal.max_webhook_receiver`) | Arc 2 |
| [`docs/llm/index.md`](../llm/index.md):289 | §4 map row + run command | Arc 2 |
| [`README.md`](../../README.md):106-107 | command with `--config-dir configs/00-defaults --config-dir configs/local` flags | Arc 3 |
| [`docs/developer-guide.md`](../developer-guide.md):2152-2155 | command with `--config-dir` flags | Arc 3 |
| [`docs/max-webhook-setup.md`](../max-webhook-setup.md):170-175 | OpenRC init script `command_args` (`--config-dir` × 4) — the file's only receiver service example; the doc is OpenRC-only (no systemd/supervisor sections exist) | Arc 3 |
| [`docs/max-webhook-setup.md`](../max-webhook-setup.md):225-230 | BOT-owned OpenRC script (`/etc/init.d/gromozeka-bot`, `command_args="main.py ..."`) — NOT an edit target for the receiver invocation | none — Arc 3 caution: do not touch |
| [`docs/max-webhook-setup.md`](../max-webhook-setup.md):266-272 | Step 7 shared-config-flags prose block | Arc 3 PROSE REWORK |

*(Corrected 2026-08-25, Gate-1B fix round — the table above is RE-CUT. The original listed
"8 line-ranges" with two phantom rows (:226-230 "supervisor command", :267-271 "init.d
daemon args"): ground truth (fresh read of the 347-line doc) is that :225-230 is the BOT's
`/etc/init.d/gromozeka-bot` script and :266-272 is Step 7's shared-flags prose; the doc is
OpenRC-only, and :170-175 (mislabeled "systemd unit ExecStart") is in fact the OpenRC init
script `command_args` — the file's ONE receiver service example. The missed
architecture.md component-tree invocation (:968) is added as an Arc 2 row. The :266-272
PROSE REWORK item: the "exact same flags" and receiver-does-not-auto-add-`00-defaults`
sentences need rewording — the receiver now takes `--config <file>` (D17/D19), so the two
processes no longer share a flag list. Corrected total: 7 genuine invocation sites.)*

All rewrites converge on `./venv/bin/python3 -m lib.max_webhook_receiver --config <path>
[--dotenv-file <path>]` (D17); the service example in max-webhook-setup.md embeds (or
links to) the D19 example receiver TOML shipped there.

---

## 3. Ratified decisions (D1–D19)

D1–D3 encode the user-ratified forks verbatim; D4–D11 are the architect's resolutions within
them, following house precedent. *(Amended 2026-08-25: D12–D16 encode the user-ratified
full-database-independence amendment — see the Amendments block; D4 and D11 are superseded by
D15 and D16 respectively, bodies preserved with dated pointers. Amended again 2026-08-25
(amendment #2): D17–D19 encode the user-ratified full-lib-launcher amendment; D2 is
superseded by D17 (body preserved with a dated pointer), and D12's config-file placement
clause plus D16's entry text carry in-place dated notes.)*

### D1 — Destination: top-level `lib/max_webhook_receiver/` (user-ratified)

Not nested under `lib/max_bot/`: the receiver is an HTTP-server + storage process, not a Max
API *client* feature — `lib/max_bot` is the client library the receiver is consumed *through*
(`basePollingUrl`), and nesting would invert that relationship conceptually. Top-level matches
the deployed reality (own process, own config section, optionally own datasource) and the
sibling extraction arcs. Package contents in §4.1.
*(Amended 2026-08-25: "optionally own datasource" understates the amendment — the receiver
owns its whole database now (D12); the structural-independence argument only got stronger.)*
*(Amended 2026-08-25, amendment #2: "own config section" upgraded again — own config FILE
and own module entry (D17/D19). The top-level-destination argument is now total: nothing of
the receiver remains in `internal/` at all.)*

### D2 — Thin internal launcher; `-m internal.max_webhook_receiver` unchanged (user-ratified)

> **Superseded 2026-08-25 by D17 (amendment #2 — full-lib launcher).** The thin internal
> launcher and the byte-identical `-m internal.max_webhook_receiver` invariant are GONE:
> `internal/max_webhook_receiver/` is deleted entirely and the launcher is rebuilt as
> `lib/max_webhook_receiver/__main__.py` reading its OWN single TOML config file (no
> `ConfigManager`). The surviving substance of D2 — the argparse shape, the config reads +
> TLS reads, the `${VAR}` secret guard, and the direct-`DatabaseManager` cut — carries into
> D17 unchanged in substance. Body preserved as history.

`internal/max_webhook_receiver/` survives as exactly two files: `__init__.py`
(docstring-only, as today) and `__main__.py` (thin launcher). The launcher keeps: argparse
(`--config-dir`, `--dotenv-file`), `ConfigManager` load, the 8 config reads + TLS reads, and
the `${VAR}` placeholder secret guard (it guards a config value; its test stays in place).
The launcher drops: `Database` (→ direct `DatabaseManager`, cutting the migration chain) and
`createApp` implementation (→ import from lib). Exact contents in §4.3. Deployed command,
init.d/systemd units, and `run.sh` conventions are untouched — zero operator impact.
*(Amended 2026-08-25: 7 config reads, not 8 — `datasource` is dropped (D13) — plus one read
of the receiver's OWN `[webhook-receiver.database]` section feeding the `DatabaseManager`
passthrough (D12); the migration-hook severance now happens by OWNERSHIP — own manager, own
config section, own DB file — not merely by bypassing the internal wrapper.)*

### D3 — Lib owns the canonical `webhook_updates` DDL; migration_019 delegates in place (user-ratified)

New module `lib/max_webhook_receiver/schema.py` holds the two DDL strings **verbatim from
migration_019** plus two helpers (§4.4). `migration_019` is edited in place (repo has
migration-edit precedent): its `up()` becomes
`await sqlProvider.batchExecute(getForwardDDL())`, importing from lib — the internal→lib
import direction is legal and the resulting graph is acyclic (lib imports only `lib.db`).
`down()` stays as-is in the migration file (rollback DDL is migration-owned; no other
consumer). Safety of editing an already-applied migration: the DDL *bytes* are identical by
construction (same strings, single source), the migration runner tracks applied state by
version number (19 is already recorded on live deployments and will not re-run), fresh
databases execute the identical strings, and SQLite is the only live provider today. This is
delegation-only refactoring of a migration file, not a schema change.
*(Amended 2026-08-25: `schema.py` gains a SECOND migration consumer — `migration_029.down()`
imports the same `getForwardDDL()` to recreate table + index (D14). `migration_019` keeps its
history role untouched: it created the table in the bot's chain; 029 removes it. Fresh bot
databases therefore create-then-drop — historically honest, the standard shape of an
append-only migration chain.)*

### D4 — Self-heal scope: table only; the index stays migration-only (the portability wrinkle)

> **Superseded 2026-08-25 by D15 (full database independence amendment).** The reasoning
> below assumed the receiver and bot share one database, so the bot's migration chain would
> eventually apply `migration_019`'s index to the receiver's table. With the receiver owning
> a SEPARATE database (D12), no migration ever runs against it — a table-only self-heal
> would leave the receiver's own DB permanently unindexed. D15 has the self-heal create BOTH
> table and index; D4's surviving concern (keeping the unportable `CREATE INDEX IF NOT
> EXISTS` string out of ad-hoc lib code) is retained by having `schema.py` own the string,
> shared by migrations and self-heal. Body preserved as history.

The receiver's startup self-heal runs **only** `CREATE TABLE IF NOT EXISTS` — the fully
portable subset. `CREATE INDEX IF NOT EXISTS` is NOT portable (MySQL), so it does not enter
the lib runtime path at all; the index is created solely by migration_019 (bot-side, where all
13 existing `CREATE INDEX IF NOT EXISTS` uses already live — §2.6).

Options considered:

- **(a) Table-only self-heal, index via migration** — **CHOSEN.** The index is perf-only: it
  backs `WHERE processed = 0 ORDER BY received_at ASC` on a table that is (i) TTL-reaped
  after 1h (`CLEANUP_TTL_SECONDS = 3600`) and (ii) normally empty of pending rows. A
  standalone receiver-first bring-up runs unindexed for minutes until the bot's migration
  chain applies migration_019 — the queries work, merely slower, on a small table. No new
  portable-SQL surface is invented in lib; the migration layer keeps the index exactly where
  the portability debt already lives and is already tracked (MySQL-activation arc).
- (b) Provider-conditional index creation — a new abstract `BaseSQLProvider` hook implemented
  in all four providers for zero behavioral gain today. Over-engineering; rejected.
- (c) try/except duplicate-error swallow — error codes differ across RDBMS
  (SQLITE_CONSTRAINT / 42P07 / 1061) and the swallow hides real failures; rejected.

Consequence recorded honestly: in the standalone-receiver-first window the table exists
without its index. Accepted (perf-only, minutes-wide, small table). If MySQL ever becomes
live, the index-portability problem is migration-layer-wide and gets solved once, there —
not piecemeal in the receiver.

### D5 — Lib API: `createApp(*, repository, manager, ...)` with typed scalar params

Config stays launcher-side; lib receives typed values. New signature
*(amended 2026-08-25: the `datasource: Optional[str] = None` param originally specced here is
REMOVED per D13 — the original spec forwarded it to every repository call; that sentence is
superseded)*:

```python
def createApp(
    *,
    repository: WebhookUpdatesRepository,
    manager: DatabaseManager,
    secret: str,
    getUpdatesSecret: str = "",
    webhookPath: str = "/webhook",
    enableCleanup: bool = True,
    markOnSubsequentPoll: bool = True,
) -> web.Application:
```

Rationale for **both** params (rather than reaching through `repository.manager`): the app's
lifecycle owns manager-level duties (startup self-heal fetches a provider; shutdown calls
`closeAll()`), and explicit DI of both collaborator tiers is the house pattern
(`DatabaseStatsStorage` takes the manager; the launcher composes).

App-state keys: `DATABASE_KEY` dies; replaced by
`REPOSITORY_KEY: web.AppKey[WebhookUpdatesRepository]` and
`MANAGER_KEY: web.AppKey[DatabaseManager]`. All other keys (`WEBHOOK_SECRET_KEY`,
`GET_UPDATES_SECRET_KEY`, `DATA_SOURCE_KEY`, `ENABLE_CLEANUP_KEY`,
`MARK_ON_SUBSEQUENT_POLL_KEY`, `CLEANUP_TASK_KEY`) are unchanged. Handler bodies change only
their first line (`repository: WebhookUpdatesRepository = request.app[REPOSITORY_KEY]`) and
drop the `database.webhookUpdates.` prefix to `repository.`; every SQL/protocol behavior is
byte-identical. *(Amended 2026-08-25: `DATA_SOURCE_KEY` ALSO dies (D13) — with no
`datasource` param there is nothing to store; handlers call repository methods without
`dataSource`, so the calls resolve to the default provider of the receiver's OWN
`DatabaseManager` (D12). The remaining keys are unchanged as listed.)*

### D6 — Repository: moves as `repository.py` with `BaseRepository` inlined

`git mv internal/database/repositories/webhook_updates.py lib/max_webhook_receiver/repository.py`
(rename is deliberate: the package name already says "webhook"; same rename-for-context move
as `generic_cache.py` → `sql_cache.py` / `stats_storage.py` → `sql_storage.py`). Overlay:
(1) drop `BaseRepository` — inline `__slots__ = ("manager",)` + `__init__` (§2.2 verdict);
(2) `WebhookUpdatesRow` import flips to `from .models import WebhookUpdatesRow`; (3) one
rider: the local `params: Dict[str, Any] = {}` in `getUnprocessedUpdates` (:183) is retyped
to the provider's `QueryParams` alias from [`lib/db/providers/base.py`](../../lib/db/providers/base.py)
(same container type `execute` accepts) — the move touches the file anyway and the repo's
no-`Any` rule applies. Method bodies otherwise verbatim.
*(Amended 2026-08-25 (D13): the repository KEEPS its low-level `dataSource=None` method
params exactly as-is — they are the generic `DatabaseManager` routing mechanism, and keeping
them is zero churn; after D12/D13 they route within the receiver's OWN provider map
(normally the single default provider). Only the app layer stops passing them.)*

### D7 — `WebhookUpdatesRow` → `lib/max_webhook_receiver/models.py`

Its own module (not inlined in `repository.py`): the row shape has cross-module consumers
(app tests construct rows) and the internal convention of a dedicated models module maps
cleanly to a small lib-side one. Big-bang: the TypedDict is deleted from
`internal/database/models.py`:310-330 in the same commit; **no re-export shim** (lib-db D4
precedent — a dual-home must not survive any commit). Importer sweep is closed (§2.3).

### D8 — Internal `Database` cleanup: `webhookUpdates` removed everywhere

Verified receiver-only (§2.4), so the attribute dies across all four wrapper sites —
import (database.py:57), `__slots__` (:134), class annotation + docstring (:191-192),
construction (:257) — plus `repositories/__init__.py` (docstring :31, import :69, `__all__`
:88) and the repository file deletion. No delegating attr is kept: a delegating attribute
would be dead code with zero callers and a standing invitation to re-couple the bot to
receiver storage (ADR-013's "receiver is the sole writer" invariant is better enforced by the
bot literally not having the handle).

### D9 — Package `__init__.py` is import-light: no aiohttp re-export

`lib/max_webhook_receiver/__init__.py` re-exports ONLY `models` / `repository` / `schema`
symbols (whose deps are `lib.db` + dateutil — all cheap and already loaded). It must NOT
import `.app`: migration_019 (D3) transitively executes this package `__init__` at *bot*
startup via the migration auto-discovery chain, and an `.app` import would drag aiohttp into
every bot boot's import graph for no reason. The receiver's launcher and tests import
`from lib.max_webhook_receiver.app import createApp` directly. This constraint is stated in
the `__init__.py` docstring so nobody "completes" the re-export list later.

### D10 — Test relocation per the mirror rule, with two fixture reshapes

Full map in §5.3. Headlines: `test_app.py` moves to `tests/lib/max_webhook_receiver/` and its
mock reshapes from one spec'd `Database` to a spec'd repository mock + an unspec'd manager
mock (exact sketch in §5.3, including the `provider.execute`-must-be-`AsyncMock` gotcha);
`test_webhook_updates.py` moves as `test_repository.py` and swaps the `testDatabase.webhookUpdates`
handle for a local fixture that builds a `DatabaseManager` + `ensureWebhookUpdatesTable` —
exercising exactly the standalone receiver's bring-up path (no migration chain), which is the
new production reality. `test_main.py` stays put with patch-target updates.
*(Amended 2026-08-25: the bring-up fixture now self-heals BOTH table and index via the renamed
`ensureWebhookUpdatesSchema` (D15); `TestDataSourceForwarding` (3 tests) is REMOVED and
replaced by a default-provider assertion via the receiver's own `DatabaseManager` (D13);
`test_main.py`'s patch target is `DatabaseManager`, not `Database` (D12). Exact shapes in
§5.3.)*
*(Amended 2026-08-25, amendment #2: "stays put" is superseded — `test_main.py` MOVES to
`tests/lib/max_webhook_receiver/test_main.py` and is REWRITTEN (real temp TOML + dotenv, no
`ConfigManager` mocks), absorbing the D12/Gate-1B navigation integration test; §5.3.)*

### D11 — CHANGELOG: skip

> **Superseded 2026-08-25 by D16 (full database independence amendment).** The amendment IS
> user-visible for webhook-mode deployments: the receiver stores updates in its own database
> file, and migration_029 removes the table from the main bot database. One `### Changed`
> entry under `## [Unreleased]` lands with Arc 1; drafted text in D16. Body preserved as
> history.

The deployed command, config, endpoints, and observable behavior are unchanged; the
migration-execution side effect removed from receiver startup is a robustness improvement in
an unobserved race, not a user-facing change — meets the AGENTS.md "when NOT to update"
criteria (internal refactor; same call as ADR-022/023/024). If the maintainer prefers a line
anyway, the drafted fallback is: *Changed: internal relocation of the Max webhook receiver
implementation to `lib/max_webhook_receiver/`; deployed command and behavior unchanged.*

### D12 — Receiver owns its database: `[webhook-receiver.database]` + own DB file (user-ratified amendment)

*(Amended 2026-08-25, amendment #2: the section's HOME below — the bot defaults file — is
SUPERSEDED: `[webhook-receiver.database]` lives in the receiver's OWN config file (D19), not
in `configs/00-defaults/webhook-receiver.toml`. The section SHAPE (the TOML block below) is
unchanged and is copied verbatim into the D19 example file. Item 2's navigation source
(`configManager.config`) is likewise superseded by the launcher's own `tomllib`-parsed dict
(D17). Items 3-4 stand.)*

The receiver gets FULL database independence: it must not use the bot's migrations or the
bot's database at all. Concretely:

1. **New config section** `[webhook-receiver.database]` in
   [`configs/00-defaults/webhook-receiver.toml`](../../configs/00-defaults/webhook-receiver.toml),
   mirroring the `[database]` section shape EXACTLY (as it lives in
   [`configs/00-defaults/00-config.toml`](../../configs/00-defaults/00-config.toml):41-59:
   `default = "..."` + `[<...>.providers.<name>]` with `provider = "sqlite3"` and a
   `parameters` sub-table). Exact TOML to add (replacing the removed `datasource` block, see
   D13):

   ```toml
   # --- Receiver-owned database (independent from the bot's [database]) ---
   # The receiver process stores webhook updates in its OWN database file.
   # It never runs the bot's migrations and never touches the bot's database
   # (bot_data.db). Shape mirrors [database] in 00-config.toml exactly.
   # Pointing the receiver at the bot's DB file is unsupported (two processes
   # writing one SQLite file contend); it is not enforced.
   [webhook-receiver.database]
   default = "default"

   [webhook-receiver.database.providers.default]
   provider = "sqlite3"

   [webhook-receiver.database.providers.default.parameters]
   dbPath = "webhook_receiver_data.db"
   readOnly = false
   timeout = 30
   useWal = true
   keepConnection = true  # Connect on creation and keep connection open
   ```

   `webhook_receiver_data.db` lives at the repo root next to `bot_data.db` and is gitignored
   by the existing `/*.db` rule ([`.gitignore`](../../.gitignore):6) — no .gitignore edit.
2. **Launcher is a pure passthrough** — `internal/max_webhook_receiver/__main__.py`
   constructs `DatabaseManager(webhookConfig.get("database", {}))` via inline nested lookup
   off the launcher's existing `webhookConfig = configManager.config.get("webhook-receiver",
   {})` line (`ConfigManager.get` is literal-key-only — a dotted key silently misses and
   yields `DatabaseManager({})` → `ValueError`; §2.5 corrected note), with NO dict-building
   code (sketch in §4.3). `DatabaseManager.__init__`
   ([`lib/db/manager.py`](../../lib/db/manager.py):64-93) already fail-fast validates the
   shape: requires `providers` + `default`, the default must exist in `providers`;
   `chatMapping` is optional and defaulted.
3. **Two files on disk:** the bot keeps `bot_data.db`; the receiver gets
   `webhook_receiver_data.db`. Pointing the receiver at the bot's `bot_data.db` (by editing
   `dbPath`) is DOCUMENTED as unsupported — two processes writing one SQLite file contend on
   the write lock — but NOT enforced (config-level policing is out of scope; noted in the
   risk register).
4. **The receiver process NEVER runs bot migrations and never touches the bot's DB.** The
   old "no cross-process migration guard" limitation (ADR-013 memory) becomes MOOT: there is
   no shared schema to guard. The bot side of the split is D14.

### D13 — `datasource` key removed (amendment; folds the old routing into D12's default)

- The `[webhook-receiver]` `datasource` key is REMOVED from the TOML (both the `datasource =
  ""` line and its commented example block). Its purpose — routing webhook storage away from
  the main DB — is now the DEFAULT behavior (D12): the old key routed into the BOT's
  `[database.providers]` map, which the receiver no longer sees (and which no longer contains
  a webhook datasource once the table leaves the bot DB, D14).
- `createApp(...)` DROPS its `datasource` parameter (current signature at
  `internal/max_webhook_receiver/app.py:321-330` has `datasource: Optional[str] = None`);
  `DATA_SOURCE_KEY` is removed from the app state (D5 amendment); handlers call repository
  methods without `dataSource`.
- The moved `WebhookUpdatesRepository` KEEPS its low-level `dataSource=None` method params
  as-is — the generic `DatabaseManager` routing mechanism, zero churn; they now route within
  the receiver's OWN provider map (normally the single default).
- Tests: `TestDataSourceForwarding` (3 tests, `tests/max_webhook_receiver/test_app.py:332-382`)
  is REMOVED, replaced by a small test asserting default-provider usage via the receiver's
  own `DatabaseManager` (sketch in §5.3). D10/§5.3 sections are updated accordingly.

### D14 — Bot-side drop migration: `migration_029_drop_webhook_updates` (amendment)

- NEW `internal/database/migrations/versions/migration_029_drop_webhook_updates.py` — next
  free number verified (`migration_028_add_stat_events_retention_index.py` is the latest
  shipped; `ls -1 ... | grep migration_ | sort -V | tail -1` per AGENTS.md).
- `up()`: `DROP INDEX IF EXISTS idx_webhook_updates_unprocessed` THEN
  `DROP TABLE IF EXISTS webhook_updates` — portable across the repo's supported shapes in
  the same qualified sense as the index-create form: `DROP TABLE IF EXISTS` is fully
  portable, but `DROP INDEX IF EXISTS` shares the MySQL caveat of
  `CREATE INDEX IF NOT EXISTS` (see the D15 portability note and follow-up #1), via the
  provider (`batchExecute` of `ParametrizedQuery`, mirroring
  migration_019's mechanics exactly). Full sketch in §4.7.
- `down()`: recreates table + index by importing the canonical DDL from
  `lib/max_webhook_receiver/schema.py` (`getForwardDDL()`) — the internal→lib import
  direction is legal (D3 precedent), this gives `schema.py` a second live migration consumer,
  and the DDL stays single-sourced.
- `migration_019` itself stays UNTOUCHED by this amendment beyond D3's existing in-place
  delegation edit: history is preserved — 019 created the table in the bot's chain; 029
  removes it. Fresh bot databases create-then-drop, the standard append-only-chain shape.
- Scaffolding requirements (load-bearing; the versions discovery canary enforces them):
  annotated `version: int` and `description: str` class attributes
  (`migration_019:46-49` / migration_024 precedent;
  `internal/database/migrations/versions/__init__.py:100-104` validates `.version` and reads
  `.description` — a missing attr silently drops the file from discovery with a log line
  only). `getMigration()` factory as in every sibling.
- Migration test at `tests/database/test_migration_029_drop_webhook_updates.py` using the
  `rollbackTo(targetVersion=28)` pattern (house precedent: `test_migration_028` rolls to 27,
  `test_migration_020` to 19 — NEVER `rollback(steps=N)`, which breaks when versions are
  inserted).
- Docs follow-ups scheduled for the docs arcs: migrations README count 28 → 29
  ([`internal/database/migrations/README.md`](../../internal/database/migrations/README.md):134
  + table row); the bot schema docs LOSE the `webhook_updates` table entirely (census in
  §2.8 amendment).

### D15 — Receiver self-heal creates BOTH table and index (amendment; supersedes D4)

The receiver's own database (D12) has NO migration side — nothing else will ever create the
index there (D4's reasoning relied on the bot's migration chain eventually applying
migration_019 to a SHARED database). So `ensureSchema` (the `warmUpDatabase` replacement)
creates BOTH:

- `CREATE TABLE IF NOT EXISTS webhook_updates (...)` — the canonical table DDL, and
- `CREATE INDEX IF NOT EXISTS idx_webhook_updates_unprocessed ON webhook_updates
  (processed, received_at)` — the canonical index DDL.

The `schema.py` helper is renamed `ensureWebhookUpdatesSchema` (it no longer heals "table"
only) and executes both strings; `getForwardDDL()` stays the migration-side batch. D4's
surviving concern — keeping the unportable string out of ad-hoc lib runtime code — is
retained by having `schema.py` OWN the string, shared by migrations (019 `up()`, 029
`down()`) and the self-heal.

Portability note: `CREATE INDEX IF NOT EXISTS` is not MySQL-portable, but 13 existing
migrations already use it (001, 004, 012, 013, 014, 015, 016, 018, 019, 020, 024, 025, 028 —
§2.6) and the factory registers only `sqlite3` + `sqlink` today — consistent with repo
practice. MySQL activation would need the `BaseSQLProvider`-hook treatment for the whole
migration layer (follow-up #1, amended below), not a receiver-side workaround.

### D16 — CHANGELOG: one `### Changed` entry with Arc 1 (amendment; supersedes D11)

The amendment is user-visible for webhook-mode deployments (the receiver stores updates in
its own DB file; migration_029 removes the table from the main DB), so D11's skip is
reversed. Exactly one entry under `## [Unreleased]` → `### Changed`, landing WITH Arc 1:

```markdown
- Webhook receiver now stores Max webhook updates in its own database file
  (`webhook_receiver_data.db`, `[webhook-receiver.database]` config); migration_029 removes
  the `webhook_updates` table from the main bot database.
```

No other CHANGELOG lines (the code relocation itself stays skip-worthy per D11's reasoning).

*(Amended 2026-08-25, amendment #2 — entry text superseded in place; the fenced line above
is preserved as the amendment #1 draft. The move is now user-visible in its INVOCATION as
well (own module path, own config file), so the shipped line becomes:)*

```markdown
- Webhook receiver moved to `lib.max_webhook_receiver` (run with
  `./venv/bin/python3 -m lib.max_webhook_receiver --config webhook-receiver.toml`) with its
  own config file and its own database (`webhook_receiver_data.db`); migration_029 removes
  the `webhook_updates` table from the main bot database.
```

*(Still exactly one `### Changed` entry, one user-visible line, landing with Arc 1.)*

### D17 — Full-lib launcher: package deleted, `-m lib.max_webhook_receiver --config <file>` (user-ratified amendment #2; supersedes D2)

The receiver launcher drops `ConfigManager` entirely and the whole package moves to lib:

1. **`internal/max_webhook_receiver/` is DELETED ENTIRELY** — all three files
   (`__init__.py`, `__main__.py`, `app.py`; `app.py` moves per D5/§5.1 row 1, the two
   launcher files are simply gone). Nothing internal re-exports or wraps the receiver. New
   deployed command:

   ```bash
   ./venv/bin/python3 -m lib.max_webhook_receiver --config <path> [--dotenv-file <path>]
   ```

   Module-invocable entry precedent: `lib.stats.stats_pages`
   ([`lib/stats/stats_pages/__main__.py`](../../lib/stats/stats_pages/__main__.py)) —
   already the sanctioned shape for lib-side `-m` entry points.
2. **argparse surface**: `--config` — path to the receiver's single TOML config file,
   default `webhook-receiver.toml` (cwd-relative); `--dotenv-file` — default `.env` (same
   as today). `--config-dir` dies (there is no ConfigManager hierarchy to feed).
3. **Launcher flow** (sketched fully in §4.3, which REPLACES the superseded
   internal-launcher sketch): `parseArgs()` → `load_dotenv(args.dotenv_file)` (already lib
   code, [`lib/utils/utils.py`](../../lib/utils/utils.py):282-309 — KEY=VALUE lines only,
   populates `os.environ`; missing file logs and returns `{}`) → `tomllib.load` the config
   file (stdlib; the repo is py3.12) → `substituteEnvVars(...)` over the parsed dict (D18)
   → read `[webhook-receiver]` → secret placeholder guard (unchanged semantics: empty or
   `${...}` → log + `SystemExit(1)`) → `dbConfig = webhookConfig.get("database", {})`
   (inline nested navigation — NOT `configManager.get`, which no longer exists here) →
   `DatabaseManager(dbConfig)` → `WebhookUpdatesRepository(manager)` → `createApp(...)` →
   optional TLS (ssl context from `tls-cert-file`/`tls-key-file`, unchanged) →
   `web.run_app(...)`.
4. **ZERO internal imports in the entire lib package** — new Arc-1 grep gate: no
   `internal\.` / `from internal` imports anywhere under `lib/max_webhook_receiver/`
   (§5.5). This generalizes D1/G1 from "the app" to the whole package including the
   launcher; the package's dependency set grows only by `lib.utils` (+ stdlib
   `tomllib`/`ssl`/`argparse` in `__main__`).
5. **Operator impact**: exactly two deployment deltas — the invocation (above) and the
   config file (D19) — both carried by the D16 CHANGELOG line and the Arc 2/3 invocation
   rewrites (§2.10 census). Everything observable after startup (endpoints, status codes,
   marker protocol, cleanup cadence, TLS) is unchanged.

### D18 — `substituteEnvVars` moves to `lib/utils/utils.py` (amendment #2)

- `substituteEnvVars` + its `replaceMatchToEnv` helper move verbatim from
  [`internal/config/manager.py`](../../internal/config/manager.py):41-80 to
  [`lib/utils/utils.py`](../../lib/utils/utils.py). `ConfigManager` imports the function
  from lib afterwards (internal→lib is the legal import direction; single source of truth,
  no duplication). Mechanically cheap: manager.py ALREADY does `import lib.utils as utils`
  (:34), so the call site (:130) becomes `utils.substituteEnvVars(self._loadConfig())` (a
  direct `from lib.utils.utils import substituteEnvVars` is equally fine — `make format`
  owns the final shape). `lib/utils/utils.py` already imports `os` + `re`; the move adds
  only `TypeVar` + `cast` to its `typing` import.
- **Semantics preserved exactly**: regex `\$\{([A-Za-z_][A-Za-z0-9_-]*)\}`, recursion into
  dicts/lists, and an UNSET env var leaves the placeholder untouched — which the
  launcher's secret guard then catches (D17 flow). No behavior change for the bot's own
  config loading.
- **Importer census** (§2.10, grepped 2026-08-25): the sole production call site is
  manager.py:130 itself; `internal/config/__init__.py:16` mentions the function in a
  docstring only (`__all__` never exported it — the docstring line just gets repointed);
  **zero test importers or patchers**, so no test sweep is required. The same-named
  `lib.aurumentation.collector.substituteEnvVars` is a distinct module-local function
  (golden-recording semantics, `loadDotenv` param) — not an importer, not a collision,
  untouched and out of scope.

### D19 — Receiver config file: single TOML, `[webhook-receiver]`-rooted (amendment #2; supersedes D12's placement)

- **Shape**: `[webhook-receiver]`-rooted sections — the SAME shape as
  [`configs/00-defaults/webhook-receiver.toml`](../../configs/00-defaults/webhook-receiver.toml)
  (receiver-read keys only) plus the `[webhook-receiver.database]` section from D12. The
  file can start as a copy of the defaults file's receiver block plus the database section.
  Complete example — every receiver-read key (this exact block also ships in user docs in
  Arc 3, [`docs/max-webhook-setup.md`](../max-webhook-setup.md)):

  ```toml
  # Max Messenger webhook receiver -- receiver process config file.
  # Read DIRECTLY by the receiver launcher (lib.max_webhook_receiver.__main__);
  # NOT part of the bot's ConfigManager hierarchy. The bot's own copy of
  # secret / get-updates-secret lives in configs/ (00-defaults + local) --
  # keep the two in sync (drift = 403s). Missing non-secret keys fall back
  # to the launcher's inline defaults.
  [webhook-receiver]
  # Listen address for the webhook receiver HTTP server.
  # Default: 127.0.0.1 (localhost only -- use a reverse proxy for external TLS).
  listen-host = "127.0.0.1"

  # Listen port for the webhook receiver HTTP server.
  listen-port = 8443

  # Shared secret for verifying webhook requests from Max.
  # Set via environment variable -- never commit the actual value.
  # Max sends this in the X-Max-Bot-Api-Secret header on every webhook POST.
  secret = "${MAX_WEBHOOK_SECRET}"

  # URL path for the webhook POST endpoint from Max.
  webhook-path = "/webhook"

  # Optional secret for the GET /updates endpoint.
  # If set, the receiver checks the Authorization header on GET /updates.
  # If empty (default), no auth check -- relies on localhost binding.
  get-updates-secret = ""

  # Whether to periodically delete old processed webhook updates.
  enable-cleanup = true

  # When true, updates are marked as processed only on the NEXT poll after
  # the bot acknowledges receipt by passing the marker back (at-least-once).
  mark-on-subsequent-poll = true

  # Optional: path to TLS certificate and key for direct HTTPS serving.
  # If both are set, the receiver serves HTTPS directly (no reverse proxy).
  # tls-cert-file = "/path/to/cert.pem"
  # tls-key-file = "/path/to/key.pem"

  # --- Receiver-owned database (independent from the bot's [database]) ---
  # The receiver process stores webhook updates in its OWN database file.
  # It never runs the bot's migrations and never touches the bot's database
  # (bot_data.db). Shape mirrors [database] in 00-config.toml exactly.
  # Pointing the receiver at the bot's DB file is unsupported (two processes
  # writing one SQLite file contend); it is not enforced.
  [webhook-receiver.database]
  default = "default"

  [webhook-receiver.database.providers.default]
  provider = "sqlite3"

  [webhook-receiver.database.providers.default.parameters]
  dbPath = "webhook_receiver_data.db"
  readOnly = false
  timeout = 30
  useWal = true
  keepConnection = true  # Connect on creation and keep connection open
  ```

- **Missing-key behavior: unchanged** — the launcher's inline `.get()` defaults apply for
  non-secret keys; a missing `[webhook-receiver]` section parses to an empty dict → the
  secret guard exits 1 (D17 flow). No ConfigManager-style merge/defaults machinery is
  introduced on the receiver side.
- **`configs/00-defaults/webhook-receiver.toml` STAYS** — the bot still reads
  `[webhook-receiver]` from its ConfigManager hierarchy
  ([`internal/bot/max/application.py`](../../internal/bot/max/application.py):133/:317/:336-337/:366
  — `enabled`, `base-polling-url`, `secret`, `get-updates-secret`,
  `register-webhook`/`unregister-webhook`, `webhook-url`, `webhook-update-types`). The
  receiver-only keys (`listen-host`, `listen-port`, `webhook-path`, `enable-cleanup`,
  `mark-on-subsequent-poll`, the TLS pair) are REMOVED from it — they are consumed by the
  receiver's OWN file now, and leaving them in the bot hierarchy would be a silent no-op
  trap (an operator editing `listen-port` there would see no effect). A header comment is
  added pointing at the receiver's own config file (Arc-1 TOML edit row).
- **ACCEPTED COST (risk register)**: `secret` + `get-updates-secret` are now maintained in
  BOTH the bot config and the receiver file — drift → 403s. Mitigation: cross-reference
  comments in BOTH example files (the block above and the bot defaults file), plus the
  max-webhook-setup.md copy (Arc 3); both values are `${VAR}`-substituted from the same
  dotenv source in the standard deployment, which keeps single-env deployments honest.

---

## 4. The new package surface

### 4.1 Layout

*(Amended 2026-08-25, amendment #2: the package also ships the LAUNCHER —
`__main__.py` (D17) — and `internal/max_webhook_receiver/` disappears entirely.)*

```
lib/max_webhook_receiver/
├── __init__.py          # NEW — import-light re-exports (models/repository/schema ONLY — D9)
├── __main__.py          # NEW — full-lib launcher (D17; replaces the deleted internal package)
├── app.py               # moved from internal/max_webhook_receiver/app.py (git mv + D5 overlay)
├── models.py            # NEW — WebhookUpdatesRow TypedDict (moved code from internal/database/models.py)
├── repository.py        # moved from internal/database/repositories/webhook_updates.py (git mv + D6 overlay)
└── schema.py            # NEW — canonical webhook_updates DDL + self-heal helper (D3/D15)
```

Dependency direction: `lib.max_webhook_receiver → {lib.db, lib.utils, dateutil,
aiohttp(.app/.repository only), stdlib}` — no `internal.*`, no cycles (aiohttp loads only
when `.app` is imported, i.e. never via the migration chain — D9). *(Amended 2026-08-25: the
migration chain now reaches `schema.py` from TWO files — migration_019 `up()` and
migration_029 `down()` (D14) — both still via the import-light `__init__`, so the aiohttp
constraint is unchanged.)* *(Amended 2026-08-25, amendment #2: `lib.utils` joins the
dependency set — `__main__.py` uses `load_dotenv` + `substituteEnvVars` from
[`lib/utils/utils.py`](../../lib/utils/utils.py) (D17/D18); stdlib `tomllib`/`ssl`/
`argparse` likewise enter via `__main__` only.)*

### 4.2 `lib/max_webhook_receiver/__init__.py` (sketch)

```python
"""Max Messenger webhook receiver library.

Standalone aiohttp application that accepts webhook POSTs from the Max API,
stores raw updates via a ``webhook_updates`` table in the receiver's OWN
database, and serves them back to a consumer via a GET /updates endpoint
speaking the Max API protocol.

Note: this ``__init__`` deliberately does NOT import ``.app`` — the bot's
migrations (019 up / 029 down) import ``.schema`` and thus execute this module
at bot startup; the aiohttp dependency must stay out of that import chain.
Import app members directly:
``from lib.max_webhook_receiver.app import createApp``.
"""

from .models import WebhookUpdatesRow
from .repository import WebhookUpdatesRepository
from .schema import (
    WEBHOOK_UPDATES_INDEX_DDL,
    WEBHOOK_UPDATES_TABLE_DDL,
    ensureWebhookUpdatesSchema,
    getForwardDDL,
)

__all__ = [
    "WEBHOOK_UPDATES_INDEX_DDL",
    "WEBHOOK_UPDATES_TABLE_DDL",
    "WebhookUpdatesRepository",
    "WebhookUpdatesRow",
    "ensureWebhookUpdatesSchema",
    "getForwardDDL",
]
```

*(Amended 2026-08-25, amendment #2: the package now also ships `__main__.py` (D17) —
deliberately NOT re-exported here. `-m lib.max_webhook_receiver` executes this import-light
`__init__` first, then `__main__`, which imports `.app` directly — that is outside the
migration path, so the D9 aiohttp constraint is unaffected.)*


### 4.3 The launcher (final contents — `lib/max_webhook_receiver/__main__.py`)

*(Amended 2026-08-25, amendment #2 (D17): this sketch REPLACES the superseded
thin-internal-launcher sketch — `internal/max_webhook_receiver/` is deleted entirely (the
preserved D2 body and git history carry the old shape, including the docstring-only internal
`__init__.py`, which is deleted rather than reworded). No `ConfigManager` anywhere: the
launcher reads its OWN single TOML file, dotenv-first.)*

`lib/max_webhook_receiver/__main__.py` — full final shape:

```python
"""Entry point for the Max webhook receiver process.

Full-lib launcher (module-invocable like ``lib.stats.stats_pages``; deployed
command ``./venv/bin/python3 -m lib.max_webhook_receiver --config <path>
[--dotenv-file <path>]``). Parses command-line arguments, populates the
environment from an optional dotenv file, loads the receiver's OWN single
TOML config file, substitutes ``${VAR}`` placeholders, reads the
``webhook-receiver`` section, guards against unresolved secrets, constructs
a :class:`DatabaseManager` over the receiver's OWN
``webhook-receiver.database`` config section (the receiver never touches the
bot's database and never runs the bot's migrations — startup self-heals the
webhook_updates table AND index), builds the aiohttp application via
:func:`createApp`, optionally enables TLS, and starts serving.

ZERO internal imports: this package is bot-free by construction (D17).
"""

import argparse
import logging
import ssl
import tomllib

from aiohttp import web

from lib.db.manager import DatabaseManager
from lib.max_webhook_receiver.app import createApp
from lib.max_webhook_receiver.repository import WebhookUpdatesRepository
from lib.utils.utils import load_dotenv, substituteEnvVars

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def parseArgs() -> argparse.Namespace:
    """Parse command-line arguments for the webhook receiver.

    Returns:
        Parsed argument namespace with ``config`` (path to the receiver's
        single TOML config file) and ``dotenv_file`` (path string)
        attributes.
    """
    parser = argparse.ArgumentParser(description="Max Messenger Webhook Receiver")
    parser.add_argument(
        "--config",
        default="webhook-receiver.toml",
        help="Path to the receiver's TOML config file (cwd-relative default)",
    )
    parser.add_argument(
        "--dotenv-file",
        default=".env",
        help="Path to .env file",
    )
    return parser.parse_args()


def main() -> None:
    """Run the webhook receiver process.

    Loads the receiver's own config file, validates the webhook secret,
    wires the receiver's own database manager and repository, and serves
    the aiohttp application.
    Exits with a non-zero status when ``webhook-receiver.secret`` is empty,
    unset, or an unresolved ``${VAR}`` env var placeholder (the latter would
    otherwise be treated as a literal, publicly-known secret).

    Raises:
        SystemExit: When ``webhook-receiver.secret`` is not configured
            or is an unresolved env var placeholder.
    """
    args = parseArgs()

    # Dotenv first, so ${VAR} placeholders resolve from it (lib code since
    # the stats arc; a missing file logs an error and returns {}).
    load_dotenv(args.dotenv_file)

    # Single-file config load: stdlib tomllib (py3.12) + lib-side env
    # substitution (D18). NO ConfigManager exists in this package.
    with open(args.config, "rb") as configFile:
        rawConfig = tomllib.load(configFile)
    config = substituteEnvVars(rawConfig)

    webhookConfig = config.get("webhook-receiver", {})
    host = webhookConfig.get("listen-host", "127.0.0.1")
    port = webhookConfig.get("listen-port", 8443)
    secret = webhookConfig.get("secret", "")
    getUpdatesSecret = webhookConfig.get("get-updates-secret", "")
    webhookPath = webhookConfig.get("webhook-path", "/webhook")
    enableCleanup = webhookConfig.get("enable-cleanup", True)
    markOnSubsequentPoll = webhookConfig.get("mark-on-subsequent-poll", True)

    if not secret or (secret.startswith("${") and secret.endswith("}")):
        logger.error("webhook-receiver.secret is not configured (missing or unresolved env var) -- exiting")
        raise SystemExit(1)

    # The receiver's OWN database (D12): a DatabaseManager over the
    # webhook-receiver.database config section — pure nested navigation, no
    # dict-building. NEVER the internal Database wrapper and NEVER the bot's
    # [database] config: the receiver must not run the bot's migrations or
    # touch the bot's DB file. Startup self-heals the webhook_updates table
    # AND index instead (see lib.max_webhook_receiver.schema).
    dbConfig = webhookConfig.get("database", {})
    manager = DatabaseManager(dbConfig)  # pyright: ignore[reportArgumentType]
    repository = WebhookUpdatesRepository(manager)

    app = createApp(
        repository=repository,
        manager=manager,
        secret=secret,
        getUpdatesSecret=getUpdatesSecret,
        webhookPath=webhookPath,
        enableCleanup=enableCleanup,
        markOnSubsequentPoll=markOnSubsequentPoll,
    )

    # Optional TLS: serve HTTPS directly when both cert and key are configured.
    sslCtx = None
    certFile = webhookConfig.get("tls-cert-file")
    keyFile = webhookConfig.get("tls-key-file")
    if certFile and keyFile:
        sslCtx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        sslCtx.load_cert_chain(certFile, keyFile)

    web.run_app(app, host=host, port=port, ssl_context=sslCtx)


if __name__ == "__main__":
    main()
```

(Exact import ordering is `make format`'s job; the sketch shows content, not isort layout.
`substituteEnvVars`' generic keeps `tomllib`'s parsed dict exactly as opaque as
`ConfigManager.config` was — the lone `# pyright: ignore[reportArgumentType]` carries over
to the `DatabaseManager` line, same looseness bucket as today, and no NEW `Any` appears.)

### 4.4 `lib/max_webhook_receiver/schema.py` (sketch)

*(Amended 2026-08-25 per D15: the self-heal helper is renamed
`ensureWebhookUpdatesSchema` and creates BOTH the table and the index — the receiver's own
database has no migration side, so nothing else would ever create the index there. D4's
table-only sketch is superseded.)*

```python
"""Canonical DDL for the ``webhook_updates`` table.

Single source of truth for the table and index shapes: the bot's migrations
import ``getForwardDDL()`` (migration_019 ``up()`` creates; migration_029
``down()`` recreates on rollback) so the migration chain and this library can
never drift, and the standalone receiver self-heals its OWN database at
startup via ``ensureWebhookUpdatesSchema()`` — which creates BOTH the table
and the index. The receiver's database has no migration side; the self-heal
is its only schema authority.

Portability: ``CREATE TABLE IF NOT EXISTS`` is portable across
SQLite/PostgreSQL/MySQL; ``CREATE INDEX IF NOT EXISTS`` is not (MySQL rejects
it) — but 13 shipped migrations already use that form and only sqlite3/sqlink
providers are registered today, so the string lives here, single-sourced,
shared by migrations and self-heal. MySQL activation will address the index
form once, centrally, via a provider hook.
"""

from typing import List

from lib.db.providers import BaseSQLProvider, ParametrizedQuery

WEBHOOK_UPDATES_TABLE_DDL: str = """
    CREATE TABLE IF NOT EXISTS webhook_updates (
        id            TEXT      PRIMARY KEY NOT NULL,
        received_at   TIMESTAMP NOT NULL,
        update_type   TEXT      NOT NULL,
        raw_json      TEXT      NOT NULL,
        processed     INTEGER   NOT NULL DEFAULT 0,
        processed_at  TIMESTAMP
    )
    """
"""Portable table DDL (verbatim from migration_019 at extraction time)."""

WEBHOOK_UPDATES_INDEX_DDL: str = """
    CREATE INDEX IF NOT EXISTS idx_webhook_updates_unprocessed
    ON webhook_updates (processed, received_at)
    """
"""Index DDL (NOT MySQL-portable; shared by migrations + self-heal — see module docstring)."""


def getForwardDDL() -> List[ParametrizedQuery]:
    """Build the forward-migration DDL batch (table + index).

    Returns:
        List[ParametrizedQuery]: The DDL statements migrations execute
        (migration_019 up(); migration_029 down()).
    """
    return [
        ParametrizedQuery(WEBHOOK_UPDATES_TABLE_DDL),
        ParametrizedQuery(WEBHOOK_UPDATES_INDEX_DDL),
    ]


async def ensureWebhookUpdatesSchema(sqlProvider: BaseSQLProvider) -> None:
    """Create the ``webhook_updates`` table AND index when missing (self-heal).

    The receiver's own database has no migration side — this self-heal is its
    only schema authority, so it must be complete (table + index). Idempotent
    by construction.

    Args:
        sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

    Returns:
        None
    """
    await sqlProvider.execute(WEBHOOK_UPDATES_TABLE_DDL)
    await sqlProvider.execute(WEBHOOK_UPDATES_INDEX_DDL)
```

### 4.5 `app.py` overlay deltas (everything else is byte-identical)

*(Amended 2026-08-25 per D13/D15/D12: `DATA_SOURCE_KEY` dies with the `datasource` param;
`ensureSchema` self-heals table AND index in the receiver's OWN database, no datasource
routing.)*

1. Imports: drop `from internal.database import Database`; add
   `from lib.db.manager import DatabaseManager`, `from .repository import
   WebhookUpdatesRepository`, `from .schema import ensureWebhookUpdatesSchema`.
2. Keys: `DATABASE_KEY` → `REPOSITORY_KEY` + `MANAGER_KEY` (D5); `DATA_SOURCE_KEY`
   is DELETED (D13 — nothing stores a datasource any more).
3. `warmUpDatabase` → renamed `ensureSchema`; body becomes the self-heal:

   ```python
   async def ensureSchema(app: web.Application) -> None:
       """Ensure the webhook_updates table and index exist before the first request.

       Self-heals the receiver's OWN database via the canonical DDL
       (lib.max_webhook_receiver.schema — table AND index, D15). The receiver
       never runs the migration chain and never touches the bot's database.

       Args:
           app: The aiohttp application holding the receiver's manager.

       Returns:
           None
       """
       manager: DatabaseManager = app[MANAGER_KEY]
       sqlProvider = await manager.getProvider(readonly=False)
       await ensureWebhookUpdatesSchema(sqlProvider)
   ```

4. `closeDatabase` reads `MANAGER_KEY` and calls `manager.closeAll()`.
5. Handlers and `cleanupTask` read `REPOSITORY_KEY` and call `repository.<method>`
   (drop the wrapper prefix; no `dataSource=` kwarg — the calls resolve to the
   default provider of the receiver's own manager, D13). Registration order in
   `createApp` is unchanged (`ensureSchema` FIRST — schema exists before the cleanup
   task starts polling — then `startCleanupTask`; cleanup hooks unchanged).
6. Module docstring: receiver-first bring-up note (own-database self-heal instead
   of migrations).

### 4.6 `migration_019` overlay (final shape of `up()`)

```python
from lib.max_webhook_receiver.schema import getForwardDDL
# (existing imports: ..base.BaseMigration; the lib.db.providers import may drop
#  ParametrizedQuery/BaseSQLProvider only if no longer referenced — up() keeps
#  its sqlProvider annotation, so BaseSQLProvider stays.)

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create the webhook_updates table and its unprocessed-rows index.

        DDL is delegated to lib.max_webhook_receiver.schema (single source of
        truth — the standalone receiver self-heals the same table at startup).

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(getForwardDDL())
```

`down()` and `getMigration()` are untouched. The module docstring gains one line noting the
delegation. *(Amended 2026-08-25: 019's `down()` stays migration-owned even though 029's
`down()` delegates to lib — 019 is sealed history; 029 is the new code and single-sources
its recreate-DDL, D14.)*

### 4.7 `internal/database/migrations/versions/migration_029_drop_webhook_updates.py` (NEW — D14)

```python
"""Drop webhook_updates from the bot database (receiver owns its own DB).

Amendment D12 gives the Max webhook receiver full database independence: it
stores updates in its OWN database file (``webhook_receiver_data.db`` via
``[webhook-receiver.database]``) and self-heals its schema there. The bot's
database no longer needs the table, so this migration removes it plus its
index. migration_019 (which created both) stays in the chain as history:
fresh bot databases create-then-drop, the standard append-only-chain shape.

Rollback (``down()``) recreates table + index by importing the canonical DDL
from ``lib.max_webhook_receiver.schema`` — single-sourced with the receiver's
self-heal and migration_019's delegated ``up()``.
"""

from typing import Type

from lib.db.providers import BaseSQLProvider, ParametrizedQuery
from lib.max_webhook_receiver.schema import getForwardDDL

from ..base import BaseMigration


class Migration029DropWebhookUpdates(BaseMigration):
    """Drop the webhook_updates table from the bot's database.

    The table moved to the webhook receiver's own database (design D12/D14);
    the bot's chain no longer needs it. Idempotent via DROP IF EXISTS.

    Attributes:
        version: Migration version number (29).
        description: Human-readable description of the migration.
    """

    version: int = 29
    """The version number of this migration."""
    description: str = "Drop webhook_updates table (moved to the webhook receiver's own database)"
    """A human-readable description of what this migration does."""

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop the unprocessed-rows index then the webhook_updates table.

        Index is dropped before the table so the order mirrors migration_019's
        down() and stays valid on providers that require an explicit index
        drop. ``DROP TABLE IF EXISTS`` is portable across the repo's supported
        shapes; ``DROP INDEX IF EXISTS`` shares the MySQL caveat of
        ``CREATE INDEX IF NOT EXISTS`` (D15 portability note; follow-up #1 —
        the MySQL-activation hook covers both index forms once, centrally).

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP INDEX IF EXISTS idx_webhook_updates_unprocessed"),
                ParametrizedQuery("DROP TABLE IF EXISTS webhook_updates"),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Recreate the webhook_updates table and index (bot-side rollback).

        Delegates to lib.max_webhook_receiver.schema.getForwardDDL() so the
        recreate DDL is single-sourced with migration_019's up() and the
        receiver's startup self-heal.

        Args:
            sqlProvider: SQL provider abstraction; do NOT use raw sqlite3.

        Returns:
            None
        """
        await sqlProvider.batchExecute(getForwardDDL())


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module.
    """
    return Migration029DropWebhookUpdates
```

(Sketch shows content; `make format` owns final layout. The annotated `version: int` /
`description: str` class attributes are load-bearing — see D14 for the discovery-canary
rationale. One subtlety: `from lib.max_webhook_receiver.schema import getForwardDDL`
executes the lib package `__init__` (import-light, D9) at bot startup — same as 019's
delegated import, no new edge.)

**Migration test** — `tests/database/test_migration_029_drop_webhook_updates.py`, following
the `test_migration_028` shape: build a manager over the shared in-memory fixture, roll
forward, assert table + index exist (019 created them), apply 029, assert both are gone;
rollback via `rollbackTo(targetVersion=28)` and assert both are back (exercises the
lib-delegated `down()`); never `rollback(steps=N)` (fragile under version insertion). A
`TestReceiverOwnDatabaseIndependence`-style assertion (bot manager + receiver-config manager
over separate temp files see disjoint schemas) lives in the receiver test suite instead
(§5.3), keeping this file a pure migration test.

---

## 5. Arc 1 census (the implementer's checklist)

### 5.1 File-move table

| # | Source | Destination | Transform |
|---|---|---|---|
| 1 | `internal/max_webhook_receiver/app.py` | `lib/max_webhook_receiver/app.py` | git-mv + §4.5 overlay |
| 2 | `internal/database/repositories/webhook_updates.py` | `lib/max_webhook_receiver/repository.py` | git-mv (renamed) + §D6 overlay |
| 3 | `internal/database/models.py:310-330` (`WebhookUpdatesRow`) | `lib/max_webhook_receiver/models.py` | moved code block, verbatim |
| 4 | — | `lib/max_webhook_receiver/schema.py` | NEW (§4.4) |
| 5 | — | `lib/max_webhook_receiver/__init__.py` | NEW (§4.2) |
| 6 | — | `tests/lib/max_webhook_receiver/__init__.py` | NEW (packaging; tests/lib convention) |
| 7 | `internal/max_webhook_receiver/__main__.py` | — | **DELETE** *(amendment #2, D17 — launcher rebuilt as the lib module, row 20; supersedes the amendment #1 "rewritten per §4.3" fate)* |
| 8 | `internal/max_webhook_receiver/__init__.py` | — | **DELETE** *(amendment #2, D17 — the package disappears entirely; no docstring touch-up; supersedes the amendment #1 fate)* |
| 9 | `internal/database/database.py` | (in place) | remove :57, :134, :191-192, :257 (D8) |
| 10 | `internal/database/repositories/__init__.py` | (in place) | remove :31, :69, :88 (D8) |
| 11 | `internal/database/models.py` | (in place) | delete :310-330 (row moves; re-anchor later TypedDicts is an Arc 2 doc duty, not a code one) |
| 12 | `internal/database/migrations/versions/migration_019_add_webhook_updates_table.py` | (in place) | `up()` delegates (§4.6); docstring note |
| 13 | `tests/max_webhook_receiver/test_app.py` | `tests/lib/max_webhook_receiver/test_app.py` | git-mv + reshape (§5.3) |
| 14 | `tests/database/repositories/test_webhook_updates.py` | `tests/lib/max_webhook_receiver/test_repository.py` | git-mv (renamed) + fixture swap (§5.3) |
| 15 | `tests/max_webhook_receiver/test_main.py` | `tests/lib/max_webhook_receiver/test_main.py` | git-mv + **REWRITE** *(amendment #2, §5.3 — no `ConfigManager` patches; real temp TOML + dotenv files; `TestLauncherConfig` absorbs the amendment #1 navigation integration test; supersedes the amendment #1 patch-target-update fate)*; the `tests/max_webhook_receiver/` dir must not survive |
| 16 | — | `internal/database/migrations/versions/migration_029_drop_webhook_updates.py` | NEW (D14, §4.7 sketch) |
| 17 | `configs/00-defaults/webhook-receiver.toml` | (in place) | EDIT *(D19, superseding the D12/D13 instruction)*: remove `datasource` key + its commented example; REMOVE the receiver-only keys (`listen-host`, `listen-port`, `webhook-path`, `enable-cleanup`, `mark-on-subsequent-poll`, commented TLS pair — consumed by the receiver's OWN file now); add the cross-reference comment (receiver-only keys + `[webhook-receiver.database]` → receiver's own config file); NO `[webhook-receiver.database]` section lands here |
| 18 | — | `CHANGELOG.md` | EDIT (D16): one `### Changed` entry under `## [Unreleased]` (drafted text in D16) |
| 19 | `tests/dependencies/test_dateutil.py` | (in place) | docstring path updates (:9, :85, :88 cite `internal/database/repositories/webhook_updates.py` — flips to the lib path); assertions untouched |
| 20 | — | `lib/max_webhook_receiver/__main__.py` | NEW *(amendment #2, D17 — §4.3 sketch)* |
| 21 | `internal/config/manager.py` (+ `internal/config/__init__.py:16` docstring) | (in place) | EDIT *(amendment #2, D18)*: `replaceMatchToEnv` + `substituteEnvVars` (:41-80) MOVE OUT to `lib/utils/utils.py`; call site :130 rewires via the existing `import lib.utils as utils` (:34); `__init__.py:16` docstring mention repointed |
| 22 | `lib/utils/utils.py` | (in place) | EDIT *(amendment #2, D18)*: GAINS `replaceMatchToEnv` + `substituteEnvVars` verbatim (+ `TypeVar`/`cast` imports; `os`/`re` already imported) |

Configs (except row 17), `run.sh`, `requirements*`, `lib/max_bot/client.py`,
`internal/bot/max/application.py`: **no changes** (NG1/NG3; NG5 superseded by row 17).
*(Rows 16-19 and the row-15 detail added by the 2026-08-25 amendment.)*
*(Amended 2026-08-25, amendment #2: rows 7/8/15/17 re-cut and rows 20-22 added (D17/D18/D19);
`internal/max_webhook_receiver/` and `tests/max_webhook_receiver/` must not survive the
Arc 1 commit AT ALL — the "dual-home check" is now an everything-gone check.)*

### 5.2 Production edit-site detail (all sites)

- `internal/database/database.py` — the four D8 sites (:57 import from the
  `from .repositories import (...)` block, :134 `__slots__` entry `"webhookUpdates"`,
  :191-192 class annotation + docstring, :257 construction).
- `internal/database/repositories/__init__.py` — docstring line :31, import :69,
  `__all__` entry :88.
- `internal/database/models.py` — delete the `WebhookUpdatesRow` block (:310-330);
  no other edits (imports of `Optional`/`datetime` stay — still used by other TypedDicts).
- `migration_019` — §4.6.
- Launcher — NEW `lib/max_webhook_receiver/__main__.py` per §4.3 (D17); the two internal
  launcher files (`__init__.py`, `__main__.py`) are DELETED (rows 7-8) — the package dir
  itself goes away with them.
- `internal/database/migrations/versions/migration_029_drop_webhook_updates.py` — NEW file,
  §4.7 sketch verbatim (D14; annotated `version`/`description` attrs are load-bearing).
- `configs/00-defaults/webhook-receiver.toml` — remove the `datasource` key AND its
  commented example block (:76-81); remove the receiver-only keys (`listen-host` :58,
  `listen-port` :61, `webhook-path` :65, `enable-cleanup` :74, `mark-on-subsequent-poll` :52,
  the commented TLS pair :86-87 — consumed by the receiver's OWN file, D19; note
  `get-updates-secret` :70 STAYS — it is bot-read, `internal/bot/max/application.py:337`);
  adjust the header comment to the cross-reference form
  (receiver-only keys + `[webhook-receiver.database]` live in the receiver's own config file;
  `secret`/`get-updates-secret` are dual-maintained — keep in sync); NO
  `[webhook-receiver.database]` section lands here (D19 supersedes D12's placement).
- `internal/config/manager.py` — DELETE :41-80 (`replaceMatchToEnv`, `T = TypeVar("T")`,
  `substituteEnvVars`); the `re` import drops if otherwise unreferenced; the call site :130
  rewires to the lib function via the existing `import lib.utils as utils` (:34).
  `internal/config/__init__.py:16` — docstring "Main exports" line repointed at the lib
  location (no `__all__` change; it never exported the function). (D18)
- `lib/utils/utils.py` — GAINS the two moved functions verbatim; `TypeVar` + `cast` join the
  `typing` import; `os` + `re` are already imported. (D18)
- `CHANGELOG.md` — one `### Changed` entry under `## [Unreleased]` (D16 text, amendment #2
  draft), same commit as the code (Arc 1).

### 5.3 Test reshapes

**`tests/lib/max_webhook_receiver/test_app.py`** (moved):

- Import flips: `Database` → `WebhookUpdatesRepository` (from `lib.max_webhook_receiver.repository`)
  and `DatabaseManager` (from `lib.db.manager`); `WebhookUpdatesRow` → from
  `lib.max_webhook_receiver.models`; app names (`ENABLE_CLEANUP_KEY`,
  `SECRET_HEADER`, `createApp`) → from `lib.max_webhook_receiver.app`
  *(amended 2026-08-25: `DATA_SOURCE_KEY` is NOT imported — the symbol no longer exists
  (D13); the old list included it)*. The two function-level
  `from internal.max_webhook_receiver import app as appModule` (:404, :434) become a single
  top-level `from lib.max_webhook_receiver import app as appModule` (AGENTS-compliant; the
  patch targets keep working — they use the module object).
- **`TestDataSourceForwarding` (:332-382, 3 tests) is DELETED** (D13 — the routing it pins
  no longer exists). Replaced by one focused test in its place:

  ```python
  class TestDefaultProviderUsage:
      """The app routes repository calls via the receiver's OWN manager default.

      With ``datasource`` gone (D13), handlers call repository methods without
      ``dataSource``; the calls resolve to the default provider of the
      receiver's own ``DatabaseManager`` (D12) — never into the bot's
      ``[database.providers]`` map.
      """

      async def testRepositoryCallsOmitDataSource(self) -> None:
          """POST and GET call repository methods with no ``dataSource`` kwarg."""
          mockRepository = _makeMockRepository()
          app = _buildApp(mockRepository)
          async with TestClient(TestServer(app)) as client:
              await client.post(
                  WEBHOOK_PATH,
                  headers={SECRET_HEADER: WEBHOOK_SECRET},
                  json={"update_type": "message_created"},
              )
          addArgs = mockRepository.addUpdate.await_args
          assert addArgs is not None
          assert "dataSource" not in addArgs.kwargs
  ```

  Net app-test count: 22 − 3 + 1 = 20.
- Mock reshape — `_makeMockDatabase()` (:62-83) splits into two builders; the exact shape
  matters because the startup hook now *awaits* `provider.execute(...)`:

  ```python
  def _makeMockRepository() -> MagicMock:
      """Build a fully-mocked WebhookUpdatesRepository (all five methods no-op)."""
      repository = MagicMock(spec=WebhookUpdatesRepository)
      repository.addUpdate = AsyncMock(return_value=True)
      repository.getUnprocessedUpdates = AsyncMock(return_value=[])
      repository.markProcessed = AsyncMock(return_value=None)
      repository.markProcessedBeforeMarker = AsyncMock(return_value=None)
      repository.deleteProcessedOlderThan = AsyncMock(return_value=None)
      return repository

  def _makeMockManager() -> MagicMock:
      """Build a mocked DatabaseManager with an awaitable-execute provider.

      Unspec'd on purpose: DatabaseManager uses __slots__, and the project
      mock convention for slotted classes is unspec'd MagicMock children
      (see project memory on Database/DatabaseManager mocking).
      """
      manager = MagicMock()
      provider = MagicMock()
      provider.execute = AsyncMock(return_value=None)  # ensureSchema awaits this
      manager.getProvider = AsyncMock(return_value=provider)
      manager.closeAll = AsyncMock(return_value=None)
      return manager
  ```

  (`spec=WebhookUpdatesRepository` is safe: the five methods are class attributes, and
  `manager` is a declared slot — both writable on a spec'd mock.)
- `_buildApp` (:86-116) passes `repository=cast(WebhookUpdatesRepository, mockRepository),
  manager=cast(DatabaseManager, mockManager), ...`; every `mockDb.webhookUpdates.X` assertion
  (≈40 sites) becomes `mockRepository.X`. All 22 test *behaviors* are unchanged.
  *(Amended 2026-08-25: minus the 3 deleted `TestDataSourceForwarding` behaviors — 19 carry
  over unchanged, +1 new `TestDefaultProviderUsage` test = 20; `_buildApp` drops any
  `datasource=` kwarg from the original sketch.)*

**`tests/lib/max_webhook_receiver/test_repository.py`** (moved + fixture swap):

- The 14 `repo = testDatabase.webhookUpdates` lines collapse into one local fixture the tests
  request instead of `testDatabase`. The fixture mirrors the receiver's real bring-up
  (manager + self-heal, NO migration chain — which is precisely the new production path):

  ```python
  @pytest.fixture
  async def webhookRepository(inMemoryDbPath: str) -> AsyncGenerator[WebhookUpdatesRepository, None]:
      """Fresh manager over in-memory SQLite with the webhook_updates schema self-healed.

      Mirrors the standalone receiver's bring-up exactly: DatabaseManager over
      the receiver-own config shape + ensureWebhookUpdatesSchema (table AND
      index, D15), no migration chain.
      """
      config: DatabaseManagerConfig = {
          "default": "default",
          "chatMapping": {},
          "providers": {
              "default": {
                  "provider": "sqlite3",
                  "parameters": {"dbPath": inMemoryDbPath},
              }
          },
      }
      manager = DatabaseManager(config)
      sqlProvider = await manager.getProvider(readonly=False)
      await ensureWebhookUpdatesSchema(sqlProvider)
      yield WebhookUpdatesRepository(manager)
      await manager.closeAll()
  ```

  (`inMemoryDbPath` comes from [`tests/conftest.py`](../../tests/conftest.py):58-66 — shared,
  no conftest edits needed. All 14 tests keep their assertions verbatim; only the fixture
  signature and import lines change.)

**`tests/lib/max_webhook_receiver/test_main.py`** (MOVED from
`tests/max_webhook_receiver/test_main.py` + REWRITTEN — amendment #2, D17/D18/D19; the old
file's `_patchMainEnv`/`ConfigManager`-mock rewiring notes from amendment #1 are superseded
and the whole `tests/max_webhook_receiver/` dir dies with the package):

- ZERO `ConfigManager` patches — the launcher has none. The patch surface is
  `lib.max_webhook_receiver.__main__` imported names only: `DatabaseManager`,
  `WebhookUpdatesRepository`, `createApp`, `web` (`run_app`), and `parseArgs` (patched to
  return a namespace whose `config`/`dotenv_file` attributes point at real `tmp_path`
  files).
- Config comes from REAL temp files (`tmp_path` fixtures): a TOML file written per test
  (the D19 example shape, trimmed per case) and a real dotenv file
  (`MAX_WEBHOOK_SECRET=resolved-secret` line) — the rewrite deliberately exercises the
  actual `load_dotenv` + `substituteEnvVars` path end-to-end, never method mocks. One
  coherent class shape — `TestLauncherConfig` — absorbs (and supersedes) the amendment #1
  `TestLauncherDatabaseConfigNavigation` real-`ConfigManager` integration test:

  ```python
  class TestLauncherConfig:
      """Launcher behavior over REAL temp TOML + dotenv files (no config mocks).

      Pins the D17 flow at the unit seam: dotenv -> tomllib ->
      substituteEnvVars -> [webhook-receiver] reads -> secret guard ->
      DatabaseManager(webhookConfig.get("database", {})) pure passthrough ->
      createApp(...). Real files, never method mocks — a navigation or
      substitution regression cannot hide (supersedes the amendment #1
      real-ConfigManager integration test: same intent, one less layer).
      """

      def _writeConfig(self, tmp_path: Path, tomlBody: str) -> str:
          """Write a receiver TOML file under tmp_path and return its path.

          Args:
              tmp_path: Per-test temporary directory.
              tomlBody: Raw TOML text to write.

          Returns:
              str: Absolute path of the written config file.
          """
          configPath = tmp_path / "webhook-receiver.toml"
          configPath.write_text(tomlBody, encoding="utf-8")
          return str(configPath)

      def _writeDotenv(self, tmp_path: Path) -> str:
          """Write a dotenv file defining MAX_WEBHOOK_SECRET under tmp_path.

          Args:
              tmp_path: Per-test temporary directory.

          Returns:
              str: Absolute path of the written dotenv file.
          """
          dotenvPath = tmp_path / ".env"
          dotenvPath.write_text("MAX_WEBHOOK_SECRET=resolved-secret\n", encoding="utf-8")
          return str(dotenvPath)
  ```

  *(Corrected 2026-08-25, Gate-1B fix round: the class docstring above said
  `DatabaseManager(webhookConfig["database"])` — aligned to the sketch code's actual
  navigation, `webhookConfig.get("database", {})` (the §4.3 launcher sketch's `dbConfig`
  line), which is what `main()` hands to `DatabaseManager`.)*

  Test matrix (each test patches `parseArgs` to the real file paths, then drives `main()`):

  | Test | TOML fixture | Expectation |
  |---|---|---|
  | `testSecretPresentAndResolvedProceeds` | full D19 shape incl. `[webhook-receiver.database]` + dotenv file | proceeds: `DatabaseManager` called ONCE with the nested `database` dict UNMODIFIED (the pure-passthrough contract), `WebhookUpdatesRepository` + `createApp` called, `web.run_app` called with the file's host/port |
  | `testSecretMissingExits` | full shape, `secret` key absent | `SystemExit(1)`; `DatabaseManager` NOT called |
  | `testSecretUnresolvedPlaceholderExits` | `secret = "${MAX_WEBHOOK_SECRET}"`, NO dotenv written + `monkeypatch.delenv` | `SystemExit(1)` — the placeholder survives substitution and the guard fires; `DatabaseManager` NOT called |
  | `testMissingSectionExits` | `[bot]`-only TOML (no `[webhook-receiver]` table) | `SystemExit(1)` — empty section dict hits the guard; `DatabaseManager` NOT called |

  (`DatabaseManager` is mocked everywhere — the passthrough is asserted on CALL ARGS, so no
  provider is ever opened. Sync tests, nothing async. Env hygiene via
  `monkeypatch.setenv`/`delenv` so a developer shell exporting `MAX_WEBHOOK_SECRET` cannot
  flip the placeholder test.)

  **Superseded 2026-08-25 (amendment #2): `TestLauncherDatabaseConfigNavigation`** — the
  Gate-1B real-`ConfigManager` integration test specced by amendment #1 (build a real
  `ConfigManager` over a temp TOML dir containing `[webhook-receiver.database]`, run the
  launcher's exact navigation, assert `DatabaseManager(...)` constructs without
  `ValueError` — construction IS the assertion, `DatabaseManager.__init__` validates shape
  only and opens no provider) is MOOT in its `ConfigManager` form: the launcher no longer
  has a `ConfigManager` to feed. Its intent — pin the nested
  `[webhook-receiver.database]` navigation against real files so a navigation regression
  cannot hide behind method mocks — migrates VERBATIM into
  `testSecretPresentAndResolvedProceeds` above: the real TOML file replaces the real
  `ConfigManager`, and the unmodified-dict call-args assertion is the construction
  assertion's successor. The superseded sketch (preserved as history):

  ```python
  class TestLauncherDatabaseConfigNavigation:
      """The launcher's ``[webhook-receiver.database]`` lookup against a REAL config.

      Pins the sanctioned nested navigation (``configManager.config`` → chained
      ``.get()``): a regression to a dotted-key
      ``ConfigManager.get("webhook-receiver.database")`` call silently returns the
      ``{}`` default while method-mocked launcher tests stay green — this test
      cannot, because it feeds a real :class:`ConfigManager`.
      """

      def testDatabaseManagerConstructsFromRealConfig(self, tmp_path: Path) -> None:
          """``DatabaseManager`` builds from the nested lookup over a real temp TOML dir.

          Args:
              tmp_path: Per-test temporary directory holding the config fixture.

          Returns:
              None
          """
          configDir = tmp_path / "configs"
          configDir.mkdir()
          (configDir / "webhook-receiver.toml").write_text(
              "[bot]\ntoken = \"test-token\"\n\n"
              "[webhook-receiver.database]\ndefault = \"default\"\n\n"
              "[webhook-receiver.database.providers.default]\nprovider = \"sqlite3\"\n\n"
              "[webhook-receiver.database.providers.default.parameters]\n"
              "dbPath = \"webhook_receiver_data.db\"\n",
              encoding="utf-8",
          )
          configManager = ConfigManager(
              configPath=str(tmp_path / "missing-config.toml"),
              configDirs=[str(configDir)],
              dotEnvFile=str(tmp_path / "missing.env"),
          )
          webhookConfig = configManager.config.get("webhook-receiver", {})
          dbConfig = webhookConfig.get("database", {})
          manager = DatabaseManager(dbConfig)  # no ValueError — construction is the assertion
          assert manager.default == "default"
  ```

  (Historical sketch — was a sync test with nothing async; the `[bot] token` line was
  load-bearing because `_loadConfig` exits without it, manager.py:267-269. All of that
  ConfigManager scaffolding is exactly what D17 removes.)

### 5.4 Markdown link-target sweep (Arc 1 gate — target-only, no prose rewrites)

Repoint links into **deleted** files (gate-breaking; verified complete via grep):

| Doc | Line | Old target | New target |
|---|---|---|---|
| `docs/database-schema.md` | :1090 | `../internal/database/repositories/webhook_updates.py` | `../lib/max_webhook_receiver/repository.py` |
| `docs/database-README.md` | :512 | `../internal/database/repositories/webhook_updates.py:1` | `../lib/max_webhook_receiver/repository.py` |
| `docs/developer-guide.md` | :612 | `/internal/database/repositories/webhook_updates.py` | `/lib/max_webhook_receiver/repository.py` (keep its root-absolute form) |

Everything else still resolves at Arc 1 (dir links into the surviving launcher package;
`:310`-suffixed models.py links resolve to the file) and is repointed during the Arc 2/3 prose
passes (§2.8). The implementer re-greps
`internal[./]max_webhook_receiver|repositories/webhook_updates|internal\.max_webhook_receiver`
over scanned `*.md` to catch stragglers the census missed.
*(Amended 2026-08-25: the three Arc-1 link repoints above still apply — the target file is
deleted regardless — but the Arc 2 schema-docs pass now REMOVES the `webhook_updates`
sections entirely instead of repointing them (§2.8 amendment); the :886/:1055/:547
`models.py:310` links die with those sections.)*
*(Amended 2026-08-25, amendment #2: "dir links into the surviving launcher package" no
longer resolve — the package is DELETED (D17). Every scanned link (file OR dir) into
`internal/max_webhook_receiver/` becomes gate-breaking at Arc 1: AGENTS.md:17/:167,
docs/llm/index.md:289, docs/llm/architecture.md:445, docs/llm/libraries.md:867,
docs/llm/configuration.md:789, docs/design/stats-aggregation-v1.md:174 (§2.8 buckets) —
Arc 1 repoints them target-only to `lib/max_webhook_receiver/`; the invocation/prose
rewrites stay in Arc 2/3 per the §2.10 census. The implementer's re-grep
`internal[./]max_webhook_receiver` over scanned `*.md` must return ZERO at the Arc 1 gate.)*
*(Corrected 2026-08-25, Gate-1B fix round: that Arc-1 zero-grep was UNSATISFIABLE as
written — invocation PROSE in the Arc 2/3 census files survives by design until its arc
(§2.10), and check-docs does not see prose. The Arc-1 md re-grep is therefore scoped to
LINK FORMS ONLY: `]\([^)]*internal[./]max_webhook_receiver` over scanned `*.md` must
return ZERO at the Arc 1 gate, in addition to the six named link-repoint files above
resolving (AGENTS.md:17/:167, docs/llm/index.md:289, docs/llm/architecture.md:445,
docs/llm/libraries.md:867, docs/llm/configuration.md:789,
docs/design/stats-aggregation-v1.md:174). Prose/invocation rewrites stay where the
census puts them — Arc 2 and Arc 3, each of which gets its own live-docs zero-grep gate
(see the Arc 2/Arc 3 Gate lines and the §5.5 re-scope).)*

### 5.5 Residual grep gates (must be zero before the Arc 1 commit)

- `internal\.database\.repositories\.webhook_updates` in `*.py` and scanned `*.md`
- `from internal\.database\.models import WebhookUpdatesRow` in `*.py`
- `webhook-receiver\.datasource` in `*.py` and scanned `*.md` — the key is REMOVED (D13);
  zero live references may remain (historical/archive docs excepted per house rules)
- `internal\.max_webhook_receiver` in `*.py` and scanned `*.md` — **ZERO hits ANYWHERE**
  *(amendment #2: the package is deleted, so the old carve-outs for the package's own files
  and `tests/max_webhook_receiver/test_main.py` are MOOT)*; the launcher tests now live at
  `tests/lib/max_webhook_receiver/test_main.py` and reference
  `lib.max_webhook_receiver.__main__` only
  *(Corrected 2026-08-25, Gate-1B fix round: "ANYWHERE" gains the historical/design-docs
  exception the `datasource` bullet above already carries — historical/archive docs
  excepted, and the design docs' preserved supersession bodies plus memories are exempt
  (census-immutability convention). In `*.py` the zero is absolute; in scanned `*.md` the
  live-doc zero is due no later than the end of Arc 3 — at the Arc 1 gate only the LINK
  FORMS are zero (§5.4 correction), with Arc 2/Arc 3 each gating their own live-doc sets.)*
- `\.webhookUpdates` under `internal/` (production — the attribute no longer exists; docs may
  keep prose until Arc 2)
- `internal\.` OR `from internal` under `lib/max_webhook_receiver/` → zero
  *(amendment #2, D17 — the bot-free-package gate, now covering the launcher too; subsumes
  the pre-amendment `internal\.`-under-lib check)*
- `ConfigManager` under `lib/max_webhook_receiver/` → zero
  *(amendment #2, D17 — no config-manager coupling may re-enter the package)*
- `def substituteEnvVars|def replaceMatchToEnv` under `internal/config/` → zero
  *(amendment #2, D18 — only the lib location defines them afterwards; the same-named
  `lib.aurumentation.collector.substituteEnvVars` is a distinct pre-existing function and is
  out of scope)*

---

## 6. Phased implementation plan

Each arc = exactly one commit. Hard rules every arc ([`AGENTS.md`](../../AGENTS.md)):
camelCase; docstrings + `Args:`/`Returns:` + full type hints on any new code; no `Any`
in new code; `./venv/bin/python3` only; `make format lint` before AND after edits;
`make test` after any code change; no `python -c`. The commit agent MUST run
`make check-docs` before every commit.

### Arc 0 — This design doc (committed alone)

One file: `docs/design/lib-max-webhook-receiver-extraction-v1.md`. Nothing else.
**Gate:** `make check-docs` + `make lint`.
**Commit message:** `Add lib/max_webhook_receiver extraction design doc`.

### Arc 1 — CODE (one commit)

**Scope:** §5 in order — moves (1-6), launcher delete+rebuild (7-8 DELETE, 20 NEW),
config-fn move (21-22), internal cleanup (9-11), migration delegation (12), test
moves/reshapes (13-15), md link sweep (§5.4). No
fail-first regression test is required for this arc (no behavior change to pin — the
moved tests ARE the parity suite; the one new behavior, self-heal-without-migrations, is
covered by the `webhookRepository` fixture's bring-up path plus a dedicated test that a
manager-only bring-up can `addUpdate` immediately — add it to
`tests/lib/max_webhook_receiver/test_repository.py` as `TestReceiverBringUp`).
*(Amended 2026-08-25: Arc 1 GAINS — migration_029 + its test (rows 16, §4.7 — the
create-then-drop pair is the one place a fail-first regression test fits: write
`tests/database/test_migration_029_drop_webhook_updates.py` FIRST against the absent
migration and watch it fail, then add the migration); the TOML edit (row 17); the
`test_main.py` patch-target rewire (row 15); the `CHANGELOG.md` entry (row 18, D16 text);
and the `test_dateutil.py` docstring path flips (row 19). The `webhookRepository` fixture
now heals table AND index (D15).)*
*(Amended 2026-08-25, amendment #2: Arc 1 ADDITIONALLY — deletes `internal/max_webhook_receiver/`
entirely (rows 7-8) and the emptied `tests/max_webhook_receiver/` dir; creates
`lib/max_webhook_receiver/__main__.py` (row 20, §4.3); moves `substituteEnvVars` to
`lib/utils/utils.py` + rewires `ConfigManager` (rows 21-22, D18); re-cuts the defaults-TOML
edit (row 17, D19); and moves+rewrites `test_main.py` into `tests/lib/max_webhook_receiver/`
as `TestLauncherConfig` (row 15, §5.3). The row-15 patch-target rewire of the previous note
is superseded by the full rewrite.)*

**Gates (all green before commit):** `make format lint` (incl. the `import main` cycle
check — the net proving `lib/max_webhook_receiver` has no internal edge, and that
migration_019 → lib does not cycle), `make test` (full suite), `make check-docs`,
residual greps (§5.5, incl. the amendment #2 gates: no `internal.`/`from internal`/
`ConfigManager` under `lib/max_webhook_receiver/`, and `internal\.max_webhook_receiver`
zero in `*.py` + link-forms zero in scanned `*.md` — Gate-1B fix-round re-scope per the
§5.4/§5.5 corrections; the original "zero ANYWHERE" wording was unsatisfiable at Arc 1),
`git status` shows no dual-home remnants
(`internal/database/repositories/webhook_updates.py` and
`tests/database/repositories/test_webhook_updates.py` gone;
`internal/max_webhook_receiver/app.py` gone). *(Amended 2026-08-25, amendment #2: the
dual-home check is now an everything-gone check — `internal/max_webhook_receiver/` and
`tests/max_webhook_receiver/` must not exist AT ALL after the arc.)*

**Dispatch note:** one `software-developer` dispatch for the edit arc, then a
gate-running finisher (same dispatch or a second one) that runs the full gate list and
commits: `Move Max webhook receiver to lib/max_webhook_receiver`.

### Arc 2 — AGENT DOCS + ADR (one commit)

**Scope:**

- [`docs/llm/architecture.md`](../llm/architecture.md) — insert ADR-025 (text below) after
  ADR-024; update ADR-013's body minimally: the receiver-process bullet (:470) and diagram
  (:453) gain "(implementation in `lib/max_webhook_receiver/`, thin launcher in
  `internal/max_webhook_receiver/`)" wording; :476 invariant reworded (bot has no
  `db.webhookUpdates` handle at all now); :971 component-tree line repointed; :125
  repository count 15 → 14 and the `webhook_updates` entry dropped from the list.
  *(Amended 2026-08-25: the ADR-013 diagram (:453-458) and :471 wording lose the
  "shared SQLite" framing — the receiver's box holds its OWN `webhook_receiver_data.db`;
  :476's "sole writer" invariant becomes "sole database".)*
  *(Amended 2026-08-25, amendment #2: the :470 receiver-process bullet's INVOCATION is
  rewritten too — `python -m lib.max_webhook_receiver --config <path>` (§2.10 census);
  the :445 dir link was already repointed at Arc 1 (§5.4 amendment #2), this pass fixes
  the surrounding "thin launcher in `internal/`" wording — there is no internal launcher
  any more.)*
  *(Corrected 2026-08-25, Gate-1B fix round: the ":971 component-tree line repointed" item
  in the base bullet above is WIDENED to the whole :965-974 receiver component-tree
  diagram — the live invocation at :968 (`python -m internal.max_webhook_receiver` → the
  D17 command; §2.10 census row), the `ConfigManager` node at :969 (the receiver no
  longer uses it — dotenv + `tomllib` + lib-side `substituteEnvVars` per D17/D18), the
  "[shared SQLite with the bot]" note at :970 (two databases now, D12), and the
  `webhookUpdates` repository row at :971 (lib repository over the receiver's own
  table).)*
- [`docs/llm/index.md`](../llm/index.md) — §4 map: `internal/max_webhook_receiver/` row
  (:289) rewritten as thin-launcher row; new `lib/max_webhook_receiver/` row.
  *(Amended 2026-08-25, amendment #2: :289 is rewritten as a pure LIB row instead —
  `lib/max_webhook_receiver/` with the new run command
  `./venv/bin/python3 -m lib.max_webhook_receiver --config webhook-receiver.toml`
  (§2.10 census); no internal row remains anywhere in the map.)*
- [`docs/llm/libraries.md`](../llm/libraries.md) — new `lib/max_webhook_receiver` entry
  (house pattern: purpose, public API, used-by, dependency note); the aiohttp §15 "Used by"
  (:867) repointed.
- [`docs/llm/database.md`](../llm/database.md) — delete the `webhookUpdates` wrapper-table row
  (:64-65), the `WebhookUpdatesRow` models row (:335), the repository table row (:478);
  rewrite the migration_019 note (:830) to mention lib-owned DDL + delegation.
  *(Amended 2026-08-25: the :830 rewrite now covers BOTH migrations — 019 delegates its
  DDL, 029 drops the table from the bot DB (the table lives in the receiver's own
  database now); a one-line pointer to the receiver-owned schema lands here — see the
  database-schema bullet below.)*
- [`docs/llm/configuration.md`](../llm/configuration.md) — :789 receiver-process link repointed
  (launcher + lib split noted).
- [`docs/llm/testing.md`](../llm/testing.md) — tests tree (:77): `max_webhook_receiver/`
  (launcher tests only) + new `tests/lib/max_webhook_receiver/` rows.
- [`docs/database-schema.md`](../database-schema.md) + [`docs/database-schema-llm.md`](../database-schema-llm.md)
  (dual-doc rule) — :870/:531 receiver path mentions; :1090/:547/:886/:1055 WebhookUpdatesRow
  links/rows repointed to lib; **re-anchor every TypedDict line reference after the models.py
  deletion** (§2.8 knock-on list); webhook_updates section notes lib-owned DDL.
  *(Amended 2026-08-25 — SUPERSEDES the "repointed to lib" wording above: the
  `webhook_updates` sections are REMOVED from the bot schema docs ENTIRELY (schema.md :37
  TOC, :868-884 section, :1090 wrapper row; schema-llm.md :530-549 section, :1478 row; the
  :161 migration-table row STAYS but reads "created by 019, dropped by 029 (table moved to
  the receiver's own database)"). In their place, ONE short paragraph per doc notes that
  webhook updates live in the receiver's own `webhook_receiver_data.db`
  (`[webhook-receiver.database]`), with the canonical DDL reference being the
  `lib/max_webhook_receiver/schema.py` module docstring and the operator guide
  [`docs/max-webhook-setup.md`](../max-webhook-setup.md) — the receiver's own schema is
  documented THERE (Arc 3), not in the bot schema docs.)*
- [`docs/database-README.md`](../database-README.md) + [`internal/database/migrations/README.md`](../../internal/database/migrations/README.md)
  — *(added 2026-08-25)* database-README :92 schema-list entry and :512-513 repository
  entry REMOVED (bot database no longer has the table/repository); migrations README:
  table row for 029 + `Total Migrations` 28 → 29 (:134) + file-list entry (:52 area).
- [`docs/llm/memories/max-webhook-support.md`](../llm/memories/max-webhook-support.md) — Files
  section repointed; add a line: implementation now in lib, launcher thin, receiver no longer
  runs migrations (self-heal). *(Amended 2026-08-25: also — receiver owns its database file
  (`webhook_receiver_data.db` via `[webhook-receiver.database]`); the cross-process
  migration-guard limitation is MOOT; the two-DB-files operational note is added.)*
- [`AGENTS.md`](../../AGENTS.md) — :17 and :167 receiver bullets (thin launcher + lib path);
  architecture-cheatsheet layout bullet.
  *(Amended 2026-08-25, amendment #2: the bullets describe the LIB package + its
  `__main__.py` launcher (no thin-launcher wording survives); the :23 run command becomes
  `./venv/bin/python3 -m lib.max_webhook_receiver --config webhook-receiver.toml`
  (§2.10 census); the architecture-cheatsheet layout bullet for
  `internal/max_webhook_receiver/` is replaced by the `lib/max_webhook_receiver/` row.)*
- [`docs/llm/teamlead-memory.md`](../llm/teamlead-memory.md) — closure line on the :142-156
  extraction task (append-style, house convention).
- This design doc §8 — no-touch (follow-ups list only updated if something landed).

**Gate:** `make lint` + `make check-docs` + the Arc-2 invocation zero-grep: ZERO
`internal[./]max_webhook_receiver` remains in the LIVE Arc-2 docs (AGENTS.md,
docs/llm/architecture.md, docs/llm/index.md) *(added 2026-08-25, Gate-1B fix round — Arc 2
and Arc 3 each get their own zero-grep gate over LIVE, non-historical docs;
historical/archive docs and the design docs' preserved supersession bodies and memories
are exempt)*.
**Commit message:** `Add ADR-025 and sync agent docs for lib/max_webhook_receiver`.

**Ready-to-paste ADR-025 text** (fenced — convert the design-doc path to a house link on
insertion; insert AFTER ADR-024, renumber nothing):

*(ADR text below rewritten 2026-08-25 per the full-database-independence amendment — D12–D16;
it replaces the earlier shared-database draft. Rewritten again 2026-08-25 per amendment #2 —
the receiver is now fully lib-standalone: own config file, own database, no internal
imports, `-m lib.max_webhook_receiver` invocation (D17–D19); the amendment #1 draft is
superseded.)*

```text
### ADR-025: Max webhook receiver extracted to `lib/max_webhook_receiver/` — fully standalone (own config file, own database)

**Date:** 2026-08-25 (decision forks + full-database-independence amendment + full-lib-launcher amendment #2 ratified by user; implementation per its design doc arcs)
**Status:** Accepted (ADR-013's two-process architecture is unchanged; the shared-database and internal-launcher details are superseded)

**Decision:** The Max webhook receiver moved out of `internal/` into a bot-free
`lib/max_webhook_receiver/` package — the ENTIRE receiver, launcher included:
`internal/max_webhook_receiver/` was deleted. The package holds the aiohttp app (`app.py`,
handlers and lifecycle unchanged), `WebhookUpdatesRepository` (now `repository.py`, taking a
`DatabaseManager` directly with `BaseRepository` inlined — it was a manager-holding ABC with
no methods), the `WebhookUpdatesRow` TypedDict (now `models.py`), a new `schema.py` owning
the canonical `webhook_updates` DDL, and the launcher itself (`__main__.py`, module-invocable
like `lib.stats.stats_pages`). The receiver is fully lib-standalone: it is started with
`./venv/bin/python3 -m lib.max_webhook_receiver --config <path> [--dotenv-file <path>]`,
reads its OWN single TOML config file (dotenv → stdlib `tomllib` → lib-side
`substituteEnvVars`, which moved to `lib/utils/utils.py` for the purpose — `ConfigManager`
imports it from lib), and has ZERO internal imports. It also owns its DATABASE: the
`[webhook-receiver.database]` section in its own config file (same shape as the bot's
`[database]`) points it at its own file (`webhook_receiver_data.db` by default); the
launcher constructs a bare `DatabaseManager` from that section as a pure passthrough. The
receiver never runs the bot's migrations and never touches the bot's database: its startup
self-heals BOTH the table and the index from `schema.py` (its database has no migration
side, so the self-heal must be complete; the `CREATE INDEX IF NOT EXISTS` form follows the
13-migration house precedent — MySQL activation will address it once, centrally). The bot's
chain dropped the table via migration_029 (`DROP INDEX`/`DROP TABLE IF EXISTS`; `down()`
recreates from the same lib-owned DDL — single-sourced with migration_019's delegated
`up()`). The internal `Database` wrapper lost its `webhookUpdates` attribute (verified
receiver-only consumer), `internal/database/repositories/webhook_updates.py` was deleted
(big-bang, no shims), and the `[webhook-receiver]` `datasource` key was removed
(separate-storage is the default now). The package `__init__.py` deliberately does not
import `.app`: the migrations execute it transitively at bot startup, and aiohttp must stay
out of that import chain.

**Why:** the receiver is a deployment peer, not a bot feature (own process, own config
file, own database); after ADR-022/023/024 its implementation had zero bot-side
dependencies left in `app.py`. Full-lib standing eliminates the two-process migration race
and the shared-SQLite write contention in one move (ADR-013 known limitations become moot),
enforces ADR-013's "receiver is the sole writer" invariant structurally (the bot literally
lacks the handle AND the table), keeps the deployed surface honest (one module, one config
file, one database file), and lets either process restart without the other's schema
involvement. Operational costs accepted: two DB files on disk (backups must cover both),
and `secret`/`get-updates-secret` maintained in both the bot config and the receiver file
(cross-reference comments in both example files; drift = 403s). Pointing the receiver at
the bot's `bot_data.db` is documented as unsupported and not enforced.

**Explicitly unchanged:** ADR-013's two-process architecture, the `webhook_updates` schema,
the marker protocol, delivery semantics, TLS handling, and `lib/max_bot/client.py`. Design
doc with the D1–D19 decisions and the full census:
`docs/design/lib-max-webhook-receiver-extraction-v1.md`.
```

### Arc 3 — USER DOCS + Gate-2 polish (one commit)

**Scope:**

- [`docs/max-webhook-setup.md`](../max-webhook-setup.md) — the init.d scripts' command
  (`-m internal.max_webhook_receiver`, :170) is unchanged; sweep any file-path references to
  receiver sources (none found in the census — verify by grep); optionally note the
  receiver-first bring-up is now migration-free (self-heal).
  *(Amended 2026-08-25: this doc becomes the operator home for the receiver's OWN database:
  update the architecture sketch (:16-:29 — receiver box holds `webhook_receiver_data.db`,
  not the bot's SQLite) and the "sole writer" note (:29); document the
  `[webhook-receiver.database]` section (D12 TOML as the example), the two-files-on-disk
  backup implication, the unsupported-but-unenforced same-file-as-bot footgun, and that the
  receiver self-heals its complete schema (table + index) on startup; reference
  `lib/max_webhook_receiver/schema.py`'s docstring as the canonical DDL. The datasource
  example in the config-override section (:310 area) is removed with the key; :339 storage
  wording updated. This is where the Arc 2 agent-doc pointers land.)*
  *(Corrected 2026-08-25, Gate-1B fix round: the "datasource example in the config-override
  section (:310 area)" clause above is STRUCK — `rg datasource docs/max-webhook-setup.md`
  returns ZERO hits; the clause was a phantom. The :339 storage-wording item STANDS: the
  "One machine, one SQLite file" invariant needs the two-databases correction, with :28
  and the architecture sketch :16-29 as the bullet already covers.)*
  *(Amended 2026-08-25, amendment #2: ALL THREE service examples are rewritten to the new
  invocation — systemd :170-175, supervisor :226-230, init.d :267-271 — `--config <single
  file>` (e.g. `--config webhook-receiver.toml`) replaces every `--config-dir` flag; the
  leading "command is unchanged" clause of this bullet is superseded. The COMPLETE D19
  example receiver config file lands in this doc as the canonical operator copy (every
  receiver-read key + the `[webhook-receiver.database]` block), alongside the dual-secret
  cross-reference note (bot config vs receiver file — keep in sync).)*
  *(Corrected 2026-08-25, Gate-1B fix round: "ALL THREE service examples" was wrong — the
  doc is OpenRC-only with exactly ONE receiver service example, :170-175 `command_args`
  (the "systemd"/"supervisor" labels were phantoms). The rewrite applies to that one
  script; the BOT's own script at :225-230 (`command_args="main.py ..."`) is NOT touched;
  and Step 7's shared-flags prose (:266-272) gets the PROSE REWORK scheduled in the §2.10
  re-cut ("exact same flags" no longer holds once the receiver takes `--config <file>`).)*
- [`docs/developer-guide.md`](../developer-guide.md) — :236 tree line (repo file moved),
  :612 table row (link already swept in Arc 1; fix the prose columns now), :2128/:2152
  two-process section wording (launcher + lib).
  *(Amended 2026-08-25, amendment #2: the :2152-2155 command example is rewritten to
  `./venv/bin/python3 -m lib.max_webhook_receiver --config webhook-receiver.toml
  [--dotenv-file .env]` — the `--config-dir` flags are gone (§2.10 census); the two-process
  wording describes the lib launcher + its own config file.)*
- [`README.md`](../../README.md) — any receiver path mentions (grep; the command stays).
  *(Amended 2026-08-25, amendment #2: the command does NOT stay — :106-107 is rewritten to
  `./venv/bin/python3 -m lib.max_webhook_receiver --config webhook-receiver.toml` (the
  `--config-dir configs/00-defaults --config-dir configs/local` flags are gone; §2.10
  census).)*
- [`docs/database-README.md`](../database-README.md) — :512 row prose columns (link swept in
  Arc 1; fix prose). *(Amended 2026-08-25: superseded — the :92/:512-513 entries are REMOVED
  wholesale in Arc 2; only a residual-prose grep remains here.)*
- **Gate-2 polish** (cache-arc pattern): flip this design doc's Status line to IMPLEMENTED
  with commit hashes; re-run residual greps; archive-banner check (none needed —
  `docs/archive/plans/max-webhook-support.md` is unscanned historical census, left per the
  immutability lesson); any one-liner fixes land together.

**Gate:** `make check-docs` + the Arc-3 invocation zero-grep: ZERO
`internal[./]max_webhook_receiver` remains in the LIVE Arc-3 docs (README.md,
docs/developer-guide.md, docs/max-webhook-setup.md) *(added 2026-08-25, Gate-1B fix
round — see the Arc-2 gate note for the LIVE-docs scope and exemptions)*.
**Commit message:** `Sync user docs for lib/max_webhook_receiver extraction`.

**No CHANGELOG entry** (D11). No `docs/llm/changelog.md` action.
*(Amended 2026-08-25: the "No CHANGELOG entry" line is SUPERSEDED by D16 — the entry lands
WITH Arc 1; Arc 3 itself adds nothing further to `CHANGELOG.md`, and `docs/llm/changelog.md`
still needs no action.)*

---

## 7. Risk register

| Risk / wrinkle | Severity | Mitigation / argument |
|---|---|---|
| **Editing an already-applied migration in place** (migration_019) | Low | Delegation-only; DDL bytes identical (same strings, single source); runner tracks applied state by version number — live deployments never re-run 019; fresh DBs execute identical DDL; SQLite is the only live provider. Same-shape precedent: migration_013 already rewrote earlier migrations' DDL history. |
| **Receiver-first bring-up runs without the index** (D4) | Low | *(Superseded 2026-08-25 by D15: the self-heal creates BOTH table and index — the receiver's own DB has no migration side to wait for. Risk closed; row kept as history.)* |
| **Migration chain now imports lib code at bot startup** (migration_019 → lib.max_webhook_receiver.schema) | Low | Import-light `__init__` (D9) keeps aiohttp out; `lib.db` + dateutil are already loaded by the bot; `import main` lint gate + full suite are the net. *(Amended 2026-08-25: TWO migrations import it now — 019 `up()` and 029 `down()` — same edge, same net.)* |
| **Missed rewire site** (string patch targets, mock attributes) | Med | Closed censuses (§2.3, §2.4, §2.7) + residual greps (§5.5) + full suite; blast radius is small (15 file entries). |
| **Mock-shape breakage in moved app tests** — `ensureSchema` awaits `provider.execute(...)`; a plain MagicMock provider is not awaitable and would fail every TestClient startup | Med | Exact `_makeMockManager` sketch in §5.3 (provider.execute = AsyncMock); this is the one reshape detail most likely to bite — it is called out in the test-reshape spec. |
| **`getDatabaseConfig() -> Dict[str, Any]`** — pre-existing looseness crossing into the launcher's DatabaseManager call | None (pre-existing) | Same `# pyright: ignore[reportArgumentType]` the current line carries (:80); no NEW `Any` introduced anywhere (the repository rider in D6 removes one). *(Amended 2026-08-25: the looseness moves to the nested lookup off `configManager.config: Dict[str, Any]` ([`internal/config/manager.py`](../../internal/config/manager.py):130) for the `webhook-receiver.database` passthrough (D12; §2.5 corrected note — the lookup is inline `.get()` chaining, NOT a dotted `ConfigManager.get` key) — same ignore comment, still no NEW `Any`; the navigation shape is pinned by the §5.3 real-`ConfigManager` integration test.)* *(Amended 2026-08-25, amendment #2: the looseness source is now the `tomllib`-parsed dict in the lib launcher (D17) — same ignore comment on the same `DatabaseManager` line, still no NEW `Any`; the pin is the §5.3 `TestLauncherConfig` real-TOML tests, successor of the real-`ConfigManager` test named in the dated note above.)* |
| **models.py anchor-rot knock-on** — deleting :310-330 shifts every later TypedDict anchor; schema docs were hand-repaired for exactly this on 2026-08-25 | Med (docs) | Explicitly scheduled as an Arc 2 line item with the shifted-anchor list (§2.8); `make check-docs` does not catch content drift, so the item is checklist-enforced. |
| **Dual-home survival** (old repo file / old row TypedDict left behind) | Med | git-mv + `git status` verification + §5.5 greps; house rule: no dual-home survives a commit. |
| **Someone later "completes" the `__init__.py` re-exports with `.app`** | Low | D9 note in the `__init__.py` docstring itself explains the constraint where the future editor will see it. |
| **Carried-over limitations** (unchanged by design, see ADR-013 memory): busy-poll every 0.5s; marker advance on handler error defeats at-least-once; `types` param ignored; duplicate delivery if `markProcessed` fails | Accepted | Out of scope (NG4); tracked in [`docs/llm/memories/max-webhook-support.md`](../llm/memories/max-webhook-support.md) §Known limitations. *(Amended 2026-08-25: the cross-process migration guard item is REMOVED from the carry-over list — MOOT, the databases are fully separate (D12); the two-DB-files note below is ADDED to the operational list.)* |
| **Removed receiver-side migration execution surprises an operator** who relied on the receiver to bring up a fresh shared DB | Low | Documented in ADR-025 + max-webhook-setup note (Arc 3): the receiver self-heals its own table; the bot remains responsible for the full chain — which matches every documented deployment (init.d orders receiver before bot, but the bot still migrates on ITS start). *(Amended 2026-08-25: reworded reality — the receiver self-heals its OWN database's complete schema (table + index, D15); there is no shared DB to bring up.)* |
| **Destructive drop: migration_029 loses pending `webhook_updates` rows** — any unprocessed rows in an existing main DB are deleted when 029 applies | Accepted (user, pre-prod) | User-ratified acceptance: deployments are pre-production and the table is a transient buffer (TTL 1h); operators upgrading mid-flight should let the bot drain the queue (or stop Max webhooks) before upgrading. `down()` restores the (empty) table. Documented in the CHANGELOG entry (D16). |
| **Two DB files on disk** — `bot_data.db` + `webhook_receiver_data.db`; operational awareness needed | Low | Both live at the repo root; both gitignored (`/*.db`). Backups must cover the receiver file too — documented in max-webhook-setup.md (Arc 3, D12 note) and the ADR-025 "Why". |
| **Same-file-as-bot misconfiguration footgun** — an operator may point `[webhook-receiver.database]` at `bot_data.db` | Low (documented, not enforced) | Unsupported (two processes writing one SQLite file contend on the write lock; the receiver's self-heal DDL would also fight the bot's migration chain). Documented in the TOML comment (D12 sketch) + max-webhook-setup.md; config-level policing explicitly out of scope. |
| **Secret dual-maintenance drift** *(amendment #2, D19)* — `secret` + `get-updates-secret` live in BOTH the bot config hierarchy and the receiver's own file; a diverged pair yields 403s | Accepted (user, amendment #2) | Cross-reference comments in BOTH example files (the D19 block + the bot defaults file) and the max-webhook-setup.md copy (Arc 3); both values are `${VAR}`-substituted from the same dotenv in the standard deployment, keeping single-env setups honest. |
| **Receiver config leaves the ConfigManager hierarchy** *(amendment #2, D17/D19)* — no multi-dir merge/defaults for the receiver; a typo'd `--config` path or unreadable file fails startup | Low (by design) | Single-file-by-design is the amendment's point; a missing/unreadable file fails fast at launch (same bucket as the secret guard); the D19 example file ships in user docs (Arc 3); `TestLauncherConfig` pins the real-file flow (§5.3). |
| **Same-named `substituteEnvVars` in `lib.aurumentation.collector`** *(amendment #2, D18)* — two lib functions share the name with different semantics after the move | Low | Distinct modules, no import collision (§2.10 census); D18 records the distinction; docstrings on both state their scope (config-tree substitution vs golden-recording kwargs). |
| **Package deletion misses a straggler** *(amendment #2, D17)* — a doc link or patch target the censuses missed points at the deleted `internal/max_webhook_receiver/` | Med | §2.10 invocation census *(corrected 2026-08-25, Gate-1B fix round: 7 genuine invocation sites, 6 files)* + §5.4 amended link sweep + §5.5 `internal\.max_webhook_receiver` grep (link-forms zero at the Arc 1 gate, live-doc zero by end of Arc 3 — Gate-1B re-scope) + `make check-docs` at the Arc 1 gate. |

---

## 8. Follow-ups (out of scope, tracked here)

1. **MySQL/PostgreSQL activation arc** — will need a provider-level answer for
   `CREATE INDEX IF NOT EXISTS` across ALL migrations (13 uses, §2.6), not just this one;
   D4 keeps the receiver out of that blast radius.
   *(Amended 2026-08-25: D15 brings the receiver self-heal INTO this blast radius —
   `ensureWebhookUpdatesSchema` executes the index DDL too; the activation arc must cover
   `lib/max_webhook_receiver/schema.py` alongside the migration layer. The string stays
   single-sourced there, so it is one fix site, centrally. The same hook must also cover
   `DROP INDEX IF EXISTS` — migration_029 (D14) uses it, and MySQL rejects that form just
   like `CREATE INDEX IF NOT EXISTS`, so the activation work covers the CREATE and DROP
   index forms together.)*
2. **Receiver HTTP semantics improvements** (long-poll push instead of 0.5s busy-poll,
   honoring `types`) — separate design if ever wanted.
3. **`tests/lib/max_bot/test_client_webhook.py` end-to-end pairing** — an optional
   integration test wiring the lib receiver app + MaxBotClient against in-memory SQLite
   (now trivial since both sides are lib); no concrete plan.
4. **Prose references in live plan docs** (`docs/plans/embedding-model-lookup-refactor-v1.md:952`
   mentions the `self.webhookUpdates` wiring in a code fence; `docs/design/stats-display-v1.md:1321`
   cites the receiver `-m` precedent) — historical/prose, non-gate; sweep only if those docs
   get edited for other reasons.

---

## 9. Open questions

**None blocking.** All eleven resolution points from the planning brief are settled from
code: (1) `createApp` shape pinned (D5, §4.5); (2) launcher contents pinned (§4.3), guard
stays, `test_main.py` stays (§5.3); (3) `BaseRepository` verified thin → inlined (D6, §2.2);
(4) `WebhookUpdatesRow` importers closed, sweep spec'd (D7, §2.3); (5) `Database.webhookUpdates`
verified receiver-only → removed (D8, §2.4); (6) index wrinkle resolved — option (a) (D4,
§2.6); (7) warm-up replacement pinned (§4.5 `ensureSchema`); (8) test relocation + fixture
strategy pinned (D10, §5.3); (9) Arc-1 census tables complete (§5); (10) arcs + ADR-025
drafted (§6); (11) risk register complete (§7). The one judgment call left to the user by
design: CHANGELOG skip vs one-liner (D11 — skip recommended, fallback line drafted).
*(Amended 2026-08-25: item (6)'s D4 resolution is superseded by D15 (self-heal creates both
table and index — §2.6/§4.4 amendments); item (11)'s judgment call is RESOLVED by D16 (the
user ratified the CHANGELOG entry — it lands with Arc 1); the 2026-08-25
full-database-independence amendment added D12–D16, all settled. Still none blocking.)*
*(Amended 2026-08-25, amendment #2: D17–D19 added — launcher, config file, and env-var
substitution all settled; the launcher-contents pin in item (2) now points at the §4.3 lib
sketch (no `ConfigManager`). Still none blocking.)*

---

## 10. References

- [`docs/design/lib-db-extraction-v1.md`](./lib-db-extraction-v1.md) — house-format template,
  ADR-022 grounding, check-docs mechanics (§2.5), big-bang/no-shim precedent (D4), the
  link-sweep-in-the-same-arc lesson.
- [`docs/design/lib-cache-sql-cache-extraction-v1.md`](./lib-cache-sql-cache-extraction-v1.md)
  — the most recent sibling arc (ADR-024): manager-injection overlay pattern, historical
  census immutability, Gate-2 polish.
- [`docs/design/lib-stats-sql-storage-extraction-v1.md`](./lib-stats-sql-storage-extraction-v1.md)
  — ADR-023, the `manager=` constructor precedent D5/D6 follow.
- [`docs/llm/architecture.md`](../llm/architecture.md) — ADR-013 (:443-483, architecture
  unchanged by this move), ADR-024 (:881, highest existing; ADR-025 drafted in §6 here).
- [`docs/llm/memories/max-webhook-support.md`](../llm/memories/max-webhook-support.md) —
  receiver architecture context, post-review fixes, known limitations that carry over.
- [`docs/llm/teamlead-memory.md`](../llm/teamlead-memory.md) — the extraction task record
  (:142-156) incl. the ratified decision forks.
- [`internal/database/repositories/base.py`](../../internal/database/repositories/base.py) —
  the verified-thin base being inlined (D6).
- [`internal/database/migrations/versions/migration_019_add_webhook_updates_table.py`](../../internal/database/migrations/versions/migration_019_add_webhook_updates_table.py)
  — the DDL source of truth being delegated (D3).
- [`lib/db/manager.py`](../../lib/db/manager.py),
  [`lib/db/providers/base.py`](../../lib/db/providers/base.py) — the `DatabaseManager` /
  provider surface the lib package builds on (`getProvider(*, dataSource, readonly)`,
  `execute(str | ParametrizedQuery)`).
- [`lib/stats/sql_storage.py`](../../lib/stats/sql_storage.py) — the config-injection
  precedent (manager + typed scalars).
- [`tests/conftest.py`](../../tests/conftest.py) — `inMemoryDbPath` / `testDatabase`
  fixtures (§5.3 fixture strategy).
- [`configs/00-defaults/webhook-receiver.toml`](../../configs/00-defaults/webhook-receiver.toml)
  — the config surface (NG5). *(Amended 2026-08-25: the file is EDITED per D12/D13 —
  `datasource` removed, `[webhook-receiver.database]` section added; see the D12 TOML.)*
  *(Amended 2026-08-25, amendment #2: the D12/D13 edit is re-cut per D19 — no
  `[webhook-receiver.database]` here; bot-read keys stay, receiver-only keys move to the
  receiver's OWN file, cross-reference comment added. The complete receiver file example
  lives in D19.)*
- [`lib/utils/utils.py`](../../lib/utils/utils.py) — *(added by amendment #2)* the launcher's
  dotenv step (`load_dotenv`, :282-309) and the new home of `substituteEnvVars` (D18).
- [`lib/stats/stats_pages/__main__.py`](../../lib/stats/stats_pages/__main__.py) —
  *(added by amendment #2)* the module-invocable `-m` entry precedent D17 follows.
- [`internal/database/migrations/README.md`](../../internal/database/migrations/README.md)
  — the migration registry whose count goes 28 → 29 with migration_029 (D14; Arc 2 line
  item).
- [`scripts/check_docs.py`](../../scripts/check_docs.py) + [`Makefile`](../../Makefile) — the
  check-docs gate and its scan scope.
- [`AGENTS.md`](../../AGENTS.md) — hard rules, SQL portability, mirror test layout,
  changelog skip criteria.
