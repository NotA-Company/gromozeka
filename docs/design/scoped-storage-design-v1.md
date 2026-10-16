---
category: design
---

# Scoped Storage — Named StorageService Instances (v1)

**Author:** OpenCode Architect
**Date:** 2026-10-04
**Status:** Ratified 2026-10-04 — implemented

Splits the single global `StorageService` singleton into **scoped/named storages** so the
attachments pipeline and the native-vision pipeline can use **different backends**
(e.g. attachments on S3, vision on local FS). Extends, and does not break, the
ADR-001 singleton contract: `StorageService.getInstance()` keeps returning the
default-scope instance everywhere it is called today.

---

## 1. Overview

### 1.1 Problem

One `StorageService` singleton
([`service.py`](../../internal/services/storage/service.py)) is consumed by two
features that share **only** the backend object:

- **Attachments** — `storeAttachment`
  ([`base.py`](../../internal/bot/common/handlers/base.py):2292-2327), gated by the
  save-attachments chat setting; key `{save-prefix}{mediaType}-{sha512}.{ext}`;
  writes `media_attachments.local_url`; read back by the resender
  ([`resender.py`](../../internal/bot/common/handlers/resender.py):406,
  `storage.get(local_url)`).
- **Native vision** — `_storeVisionImage`
  ([`base.py`](../../internal/bot/common/handlers/base.py):2174-2290; null-backend
  warning at :2234-2239; key `{vision/}{sha512}.{ext}` built at :2279 from
  `_visionStorePrefix` cached at `__init__` :193 from
  `[bot.vision].store-prefix` in
  [`vision.toml`](../../configs/00-defaults/vision.toml):8); writes
  `vision_url`; read back by `_loadNativeVisionImages`
  ([`ensured_message.py`](../../internal/bot/models/ensured_message.py):1087-1108,
  `StorageService.getInstance()` at :1088, never-raise).

Both features want different deployment characteristics (long-lived originals on
S3 vs disposable normalized copies on local FS), which a single shared backend
cannot express.

### 1.2 Approach (ratified)

**Approach A — scoped instances on `StorageService`.** The service keeps its
class-level identity guarantee but keys it by *scope* instead of a single
`_instance`. The default scope reads the existing `[storage]` table verbatim;
named scopes read `[storage.storages.NAME]` tables whose shape is **exactly the
default `[storage]` shape** (a `type` key plus `fs`/`s3` sub-tables).

### 1.3 Non-goals

- No new backends, no backend API changes, no GC (one informational note in §9).
- No migration or dual-read fallback for already-stored vision objects
  (ratified decision 3, §3).
- No multi-process or cross-bot sharing story — same single-process assumption
  as today.

## 2. Current State (verified against working tree 2026-10-04)

All anchors re-verified on 2026-10-04 before writing this document.

- **Singleton mechanics.** `StorageService.__new__`
  ([`service.py`](../../internal/services/storage/service.py):58-68) forces a
  single identity via `_instance` + `_lock` (`threading.RLock`).
  `getInstance()` (:83-91) is arg-less. `__init__` (:70-81) uses the
  `hasattr(self, "initialized")` guard. Per-instance state is only
  `self.backend` + `self.initialized` — two coexisting instances would not
  corrupt each other; the only obstacle is `__new__`.
- **Config plumbing.** `injectConfig(configManager)` (:93-184) reads
  `configManager.getStorageConfig()`
  ([`config/manager.py`](../../internal/config/manager.py):406-451, returns
  `self.get("storage", {})`), then an if/elif chain on `config["type"]` →
  `NullStorageBackend` / `FSStorageBackend` (base-dir from
  `config["fs"]["base-dir"]`) / `S3StorageBackend` (endpoint/region/key-id/
  key-secret/bucket/prefix from `config["s3"]`). Raises `StorageConfigError` on
  empty config / missing type / unknown type / missing backend params.
  Re-calling `injectConfig` silently replaces `self.backend` (tested legal).
  Unknown extra keys in the config dict are **ignored** — a `[storage.storages.*]`
  table already flows through `getStorageConfig()` today without touching
  behavior.
- **TOML deep-merge.** Nested tables deep-merge into dicts, so
  `[storage.storages.vision]` is reachable via
  `getStorageConfig().get("storages", {}).get("vision", {})` today. House
  precedent for `.get()`-chain accessors: `getVisionConfig()`
  ([`config/manager.py`](../../internal/config/manager.py):453-485) and
  `getStatsPagesConfig()` (:503-520).
- **Injection site.** Exactly one production inject:
  [`manager.py`](../../internal/bot/common/handlers/manager.py):454-455
  (`self.storage = StorageService.getInstance();
  self.storage.injectConfig(self.configManager)`), inside
  `HandlersManager.__init__` **before** the handler pipeline is constructed.
  `BaseBotHandler.__init__` ([`base.py`](../../internal/bot/common/handlers/base.py):166)
  does `self.storage = StorageService.getInstance()` with no inject — it relies
  on the manager having run. Bad `[storage]` config is a hard startup crash:
  `StorageConfigError` escapes `HandlersManager.__init__` →
  [`main.py`](../../main.py):497-500 → `sys.exit(1)`. No production code
  catches it.
- **Singleton rule.** ADR-001 in [`architecture.md`](../llm/architecture.md)
  codifies the singleton rule and names `StorageService` explicitly ("Always use
  `getInstance()` — never `SomeService()` directly");
  [`services.md`](../llm/services.md) §8 repeats it. All 10 singletons in the
  repo (7 under `internal/services/` + `lib/proxy`, `lib/rate_limiter`,
  `lib/sandbox`) have arg-less `getInstance(cls)`. No `getInstance(args)`
  precedent exists.
- **Scope of blast radius.** `backendType`'s only production consumer is the
  vision null-check at `base.py`:2234. `configure.py` has zero storage
  references. `scripts/` and `lib/` have zero `StorageService` references. STT
  object storage is boto3-direct
  ([`yandex_object_storage.py`](../../lib/stt/providers/yandex_object_storage.py)),
  NOT `StorageService`.
- **Key sanitization.** `sanitizeKey`
  ([`utils.py`](../../internal/services/storage/utils.py):62) maps `/` → `_`.
  The FS backend sanitizes the whole key
  ([`filesystem.py`](../../internal/services/storage/backends/filesystem.py):79-80,
  flat `vision_<sha>.jpg` files); the S3 backend sanitizes the key and then
  prepends its **raw backend prefix**
  ([`s3.py`](../../internal/services/storage/backends/s3.py):108-110). See §9
  for the GC implication.
- **Test landscape.**
  - Autouse `_instance = None` resets:
    [`test_service.py`](../../tests/services/storage/test_service.py):18-23,
    [`test_integration.py`](../../tests/services/storage/test_integration.py):17-22,
    and two autouse variants in
    [`test_base.py`](../../tests/bot/common/handlers/test_base.py)
    (:760-779 and :1795-1813).
  - **Also** `StorageService._instance = None` inside two non-autouse tests in
    [`test_stats.py`](../../tests/bot/common/handlers/test_stats.py):1538 and
    :1605 — these construct the **real** `HandlersManager` with a mocked
    `ConfigManager` (`getStorageConfig` mocked to `{"type": "null"}` at :1557
    and :1623), so they exercise the real inject path and must be migrated too.
  - `patch.object(StorageService, "getInstance", return_value=<mock>)` doubles:
    [`test_llm_messages.py`](../../tests/bot/common/handlers/test_llm_messages.py)
    (`_storageDouble` :2025-2042, ~20 activation sites, plus plain-`Mock`
    patches at :133/:593/:2753) and
    [`test_ensured_message.py`](../../tests/bot/models/test_ensured_message.py)
    (13 sites, :701-:1062). A `Mock` return value ignores call arguments, so
    these doubles tolerate a scope argument **by construction**.
  - Root [`tests/conftest.py`](../../tests/conftest.py) does **not** reset
    `StorageService`.
- **Default config shape.**
  [`storage.toml`](../../configs/00-defaults/storage.toml): `[storage] type =
  "null"`, `[storage.s3]` (endpoint/region/key-id via `${AWS_*}` substitution/
  key-secret/bucket/prefix), `[storage.fs] base-dir = "storage"`.
  [`vision.toml`](../../configs/00-defaults/vision.toml): five keys under
  `[bot.vision]`, including `store-prefix = "vision/"` at :8.

## 3. Ratified Decisions (user, 2026-10-04)
Binding — the design implements exactly these. Items 1, 3, and 4 are unchanged from the first ratification round; item 2's destination and items 5-6 come from the FINAL ratification deltas (user, 2026-10-04), which supersede the earlier "prefix moves into the named-storage table" wording:

1. **Approach A — scoped instances on `StorageService`**, with named storages
   under `[storage.storages.STORAGE_NAME]`, each named table shaped exactly like
   the default `[storage]` table (`type` + `.fs`/`.s3` sub-tables with the same
   keys) — **and nothing else** (see decision 5).
2. **`store-prefix` is removed from `[bot.vision]` and dies entirely** — it is
   NOT migrated anywhere: no app-layer prefix key exists after the split. (The
   removal itself was ratified in round 1; the final round changed the
   destination from "moves to storage config" to "deleted outright".)
3. **No migration, no dual-read fallback** for existing vision objects — after
   the split, reads target the vision-scoped store; misses degrade to the
   existing description fallback. Accepted. Strengthened by decision 5:
   pre-split `vision_url` values (format `vision/{sha512}.{ext}`) become
   permanently unreadable after cutover — new reads use bare keys in the
   scoped store, and the description fallback covers those rows.
4. **Bad storage config (default OR named) → startup crash**, consistent with
   today's `[storage]` behavior.
5. **No app-layer prefix at all; vision keys are bare `{sha512}.{ext}`.**
   Named tables carry ONLY the default-storage shape; separation between the
   attachments store and the vision store is achieved by backend placement —
   a different `base-dir` (fs), or a different bucket, optionally plus the
   EXISTING backend-level s3 `prefix` (already part of the default shape,
   unchanged). `_storeVisionImage` key building simplifies to
   `f"{sha512}.{ext}"`; the cached `self._visionStorePrefix` attribute is
   deleted, not re-sourced (§4.4, §4.7).
6. **Scopes are typed as a `StorageScope(StrEnum)`**
   (`DEFAULT = "default"`, `VISION = "vision"`) living in the storage
   package. `getInstance`/`injectConfig` take it, the `_instances` registry
   keys on `scope.value`, and argless calls keep returning the default
   instance — backward compatible with every existing call site (§4.5).

Also confirmed as-is in the final round (previously §5 recommendations):
absent `[storage.storages.vision]` table → null backend, with **no
inheritance** from the default `[storage]` (re-coupling rejected);
malformed named table → startup crash (parity with the default table);
`self.visionStorage` attribute on `HandlersManager` (symmetry with
`self.storage`).
## 4. Detailed Design

### 4.1 Config shape
The default `[storage]` table is **unchanged** — it keeps its exact current
keys, and its scope remains the store used by attachments
(`storeAttachment` + resender read-back). Conceptually the default scope
becomes "the attachments store", but the scope keeps the name `"default"` for
backward compatibility; no config rename, no code-side aliasing of
`[storage]` as `[storage.storages.attachments]`.

Named storages are new tables under `[storage.storages.NAME]`, each shaped
**exactly like `[storage]` — nothing more, nothing less**: a `type` key plus
the optional `.fs`/`.s3` sub-tables carrying the same keys the default table
already documents. There is deliberately **no app-layer `prefix` key**
(ratified decision 5, §3): separation from the default store is achieved by
backend placement only — a different `base-dir` (fs), or a different bucket,
optionally plus the existing backend-level s3 `prefix`.

```toml
# configs/00-defaults/storage.toml (additions; existing tables unchanged)

[storage]
# ... unchanged: type = "null" ...

# --- Named storages (optional; each table has the same shape as [storage]) ---
# Absent table  -> that scope resolves to a NullStorageBackend (feature off).
# Present table -> validated exactly like [storage]; invalid -> startup crash.
# Separation from the default store comes from backend placement ONLY: a
# different fs base-dir, or a different bucket (optionally + the existing
# backend-level s3 prefix). No other keys exist at this level (see §4.4).
#
# [storage.storages.vision]
# type = "fs"
#
# [storage.storages.vision.fs]
# base-dir = "storage/vision"
#
# # S3 example instead of fs:
# # [storage.storages.vision.s3]
# # endpoint = "https://s3.amazonaws.com"
# # region = "us-east-1"
# # key-id = "${AWS_ACCESS_KEY_ID}"
# # key-secret = "${AWS_SECRET_ACCESS_KEY}"
# # bucket = "your-bucket"
# # prefix = "vision/"          # backend-level s3 prefix (the ONLY prefix that
# #                              # exists after the split — see §4.4)
```

The example ships **commented out** in `storage.toml`, mirroring how
inactive optional config is presented elsewhere in `configs/00-defaults/`.
Deep-merge semantics mean a deployment enables the vision store by adding a
real `[storage.storages.vision]` table in its `configs/local/` overlay — no
changes to the defaults file structure.

TOML nesting note: `[storage.storages.vision]` is legal even though
`[storage]` is itself a table with scalar keys (`type`) — TOML super-tables
accommodate this, and the config loader already deep-merges it.
### 4.2 ConfigManager — no new accessor (getNamedStorageConfig dropped)
**Decision: DROP the `getNamedStorageConfig(name)` accessor** (final
ratification, 2026-10-04). Its only specced consumer was the
`BaseBotHandler.__init__` prefix caching that decision 5 deletes; after the
no-prefix delta nothing outside `injectConfig` reads named tables, so no
accessor is warranted. The `getStatsPagesConfig()` `.get()`-chain precedent
([`config/manager.py`](../../internal/config/manager.py):503-520) is not
needed here: that accessor exists because non-config code reads the
stats-pages table, while here the sole reader is `StorageService` itself.

`injectConfig` reads the named table internally — the TOML deep-merge
already flows `[storage.storages.*]` through `getStorageConfig()` (verified
§2), so the lookup is:

```python
storages = configManager.getStorageConfig().get("storages", {})
namedConfig = storages.get(scope.value, {}) if isinstance(storages, dict) else {}
```

(The `isinstance` guard mirrors the defensive shape of
`getStatsPagesConfig()`; the plain `.get()`-chain without it is equally
correct since the loader only ever merges dicts here.)

`getStorageConfig()` (:406-451) is **unchanged** — its contract stays "the
whole `[storage]` table", and the extra `storages` key is ignored by the
backend-building chain exactly as unknown keys are ignored today (verified).
`config/manager.py` is therefore touched by this design only for the
`getVisionConfig` docstring deletions in §4.7 — no new accessor is added
anywhere.

Test ripple (recorded in §8): the real-`HandlersManager` tests in
`test_stats.py` need **no new config mock** — their existing
`getStorageConfig` mock (`{"type": "null"}`, set at :1557/:1623) already
yields an absent named table (`.get("storages", {})` → `{}`), which
resolves the vision scope to a null backend without raising.
### 4.3 StorageService scoped instances
`internal/services/storage/service.py` changes (plus one re-export in the
package `__init__.py`):

```python
class StorageScope(StrEnum):
    """Sanctioned storage scopes; each names a [storage.storages.{value}] table."""
    DEFAULT = "default"
    VISION = "vision"


class StorageService:
    _instances: Dict[str, "StorageService"] = {}   # replaces _instance; keys are scope.value
    _lock = threading.RLock()                       # reused, unchanged

    def __new__(cls, scope: StorageScope = StorageScope.DEFAULT) -> "StorageService":
        with cls._lock:
            if scope.value not in cls._instances:
                cls._instances[scope.value] = super().__new__(cls)
            return cls._instances[scope.value]

    def __init__(self):          # unchanged (arg-less, hasattr guard)

    @classmethod
    def getInstance(cls, scope: StorageScope = StorageScope.DEFAULT) -> "StorageService":
        return cls(scope)
```

`StorageScope` is defined in `service.py` and re-exported by the package —
`internal/services/storage/__init__.py` currently exports only
`StorageService`; it gains `from .service import StorageService, StorageScope`
and the `__all__` entry — so call sites spell
`from internal.services.storage import StorageScope`.

- **Backward compatibility is structural**: `getInstance()` →
  `getInstance(StorageScope.DEFAULT)` → the same instance every existing
  arg-less call site and every existing test patch already handles.
  `StorageService()` direct construction still returns the registered
  default-scope instance (relied on by `test_service.py` singleton tests).
- `__init__` stays arg-less; the `hasattr(self, "initialized")` guard now
  protects **per-scope** instances independently, which is exactly the
  existing pattern applied N times.
- `injectConfig` gains a scope parameter and reads the named table internally
  (accessor dropped — §4.2):

```python
def injectConfig(self, configManager: "ConfigManager",
                 scope: StorageScope = StorageScope.DEFAULT) -> None:
    try:
        if scope is StorageScope.DEFAULT:
            config = configManager.getStorageConfig()  # pyright: ignore[reportAttributeAccessIssue]
            if not config:
                raise StorageConfigError("Storage configuration is missing")
        else:
            storages = configManager.getStorageConfig().get("storages", {})
            config = storages.get(scope.value, {}) if isinstance(storages, dict) else {}
            if not config:
                # Absent named storage = feature explicitly off, NOT an error
                # (confirmed in the final ratification round; §3, §5a).
                self.backend = NullStorageBackend()
                self.initialized = True
                logger.info(
                    f"StorageService scope '{scope.value}' not configured; using NullStorageBackend"
                )
                return

        self.backend = _buildBackend(config)   # shared validation chain
        self.initialized = True
        logger.info(f"StorageService scope '{scope.value}' initialized with "
                    f"{config.get('type')} backend")
    except StorageConfigError:
        raise
    except Exception as e:
        raise StorageConfigError(f"Failed to initialize storage service: {e}") from e
```

- The current if/elif type→backend chain (:128-176) is extracted **verbatim**
  into a module-level `_buildBackend(config: Dict[str, Any]) ->
  AbstractStorageBackend` helper (same `StorageConfigError` cases: missing
  type, unknown type, missing `fs`/`fs.base-dir`, missing `s3`/required s3
  params). Both scopes call it — validation parity is the point (ratified
  decision 4).
- Re-inject legality is preserved **per scope**: calling `injectConfig` again
  for a scope replaces that scope's `backend` and leaves other scopes alone.
- **HandlersManager** ([`manager.py`](../../internal/bot/common/handlers/manager.py):453-455)
  gains a second inject immediately after the first:

```python
self.storage = StorageService.getInstance()
self.storage.injectConfig(self.configManager)
self.visionStorage = StorageService.getInstance(StorageScope.VISION)
self.visionStorage.injectConfig(self.configManager, scope=StorageScope.VISION)
```

  Order: default first, vision second. Rationale: the default scope is the
  long-standing crash surface and keeps its error primacy (a broken
  attachments config fails before anything vision-specific is consulted);
  vision inject follows deterministically. A bad **named** config raises
  `StorageConfigError` from `HandlersManager.__init__` and crashes exactly
  like a bad default config today (`main.py`:497-500 → `sys.exit(1)`), per
  ratified decision 4. `self.visionStorage` on the manager is kept for
  symmetry with `self.storage` (confirmed in the final ratification round;
  cheap, useful for future consumers) even though `BaseBotHandler` caches
  its own reference.

**Implementation note** (2026-10-04): the shipped, ratified implementation
deviates from the illustrative sketch above in two deliberate ways — both
supersede the sketch and match the §6 failure matrix; do not "fix" the code
to match the sketch. (1) `__init__` is **not** arg-less: it accepts the
`scope` parameter (Python forwards `__new__`'s arguments to `__init__`) and
safely ignores it. (2) The named-table presence check is `config is None`,
not a truthiness check: only a genuinely absent table resolves to the silent
null backend — a present-but-empty table is malformed and raises
`StorageConfigError` from `_buildBackend` (missing `type`), per §6
("present but invalid").
### 4.4 No app-layer prefix — separation via backend placement (micro-decision b, ratified)
**There is no app-layer prefix key anywhere after the split** (ratified
decision 5, §3). Named storage tables carry only the default-storage shape
(`type` + `.fs`/`.s3` sub-tables); the round-1 idea of a top-level `prefix`
key inside the named table is superseded — deleted, not re-sourced. The only
prefix that exists is the **backend-level s3 `prefix`**, which was already
part of the default `[storage.s3]` shape before this design and stays exactly
as it is.

Separation between the attachments store and the vision store is achieved
entirely by **backend placement**:

- **fs**: a different `base-dir` per table — e.g.
  `[storage.storages.vision.fs] base-dir = "storage/vision"` alongside the
  default `[storage.fs] base-dir`.
- **s3**: a different bucket per table, or a shared bucket plus the existing
  backend-level `prefix` inside the `.s3` sub-table — the deployment recipe
  that replaces the old app-layer `vision/` prefix for bucket-sharing setups
  (the backend prepends it after key sanitization, `s3.py`:108-110).

Consequences:

- **Vision keys are bare**: `_storeVisionImage`'s key building
  ([`base.py`](../../internal/bot/common/handlers/base.py):2279) simplifies
  from `f"{self._visionStorePrefix}{sha512}.{ext}"` to
  `f"{sha512}.{ext}"`. The `vision/` prefix is gone entirely — new objects
  land as `<sha512>.<ext>` at the root of the scoped store (fs: flat files
  in the vision `base-dir`; S3: `<backend-prefix?><sha512>.<ext>` in the
  vision bucket).
- **`self._visionStorePrefix` is deleted** (cached today at
  `BaseBotHandler.__init__` :193 from `[bot.vision].store-prefix`) — the
  attribute, its sourcing, and its docstring mentions all die (§4.7); the
  `__init__` vision block instead adds only
  `self.visionStorage = StorageService.getInstance(StorageScope.VISION)`.
- **Migration note (strengthens ratified decision 3):** pre-split
  `vision_url` values (format `vision/{sha512}.{ext}`) become **permanently
  unreadable** after cutover — reads go to the vision-scoped store with bare
  keys, the old objects live in the old default store, and there is no
  migration or dual-read fallback. Rows holding such values degrade to the
  existing description fallback, exactly like rows that were never stored
  (failure-matrix row in §6).
- **GC becomes trivial** (natural consequence): the scoped vision store
  contains ONLY vision objects, so a future TTL-GC sweep lists everything in
  it — no prefix filtering, no foreign objects to spare. And since bare keys
  contain no slash, `sanitizeKey`
  ([`utils.py`](../../internal/services/storage/utils.py):62) passes them
  through unchanged, which moots the old fs/S3 prefix-asymmetry caveat for
  vision (§9 has the full note).
### 4.5 Scope enum — StorageScope(StrEnum) (micro-decision a, ratified)
Scopes are typed — `getInstance`/`injectConfig`/`__new__` take a
`StorageScope` enum, not a plain string (ratified decision 6, §3):

```python
class StorageScope(StrEnum):
    """Sanctioned storage scopes; each names a [storage.storages.{value}] table."""
    DEFAULT = "default"
    VISION = "vision"
```

- **Location:** the storage package — defined in
  [`service.py`](../../internal/services/storage/service.py) next to the
  service it parameterizes, re-exported by the package `__init__.py`, so
  call sites spell `from internal.services.storage import StorageScope`
  (the same import they already make for `StorageService` itself).
  `StorageScope` is a working name — refining it at implementation time is
  fine as long as it stays a `StrEnum` with members `DEFAULT = "default"`
  and `VISION = "vision"` living in, and importable from, the storage
  package.
- **Rationale:** typo-proof call sites — pyright/IDE reject arbitrary
  strings (a plain `"vision"` literal is a type error where a `StorageScope`
  is expected, so misspellings cannot pass review clean); and adding a new
  storage later = adding one enum member plus its config table. House rule:
  `StrEnum` over `Literal` (AGENTS.md); in-repo precedent:
  `ToolName(StrEnum)`
  ([`internal/bot/constants.py`](../../internal/bot/constants.py):29).
- **Dependency direction preserved:** the bot layer imports the enum from
  the storage package (downward — the same edge as importing
  `StorageService`); the storage package treats members as opaque, using
  `scope.value` only for the config table lookup
  `[storage.storages.{scope.value}]` and the `_instances` registry key. The
  draft's plain-string constants sketch (`DEFAULT_STORAGE_SCOPE` in
  service.py + `VISION_STORAGE_SCOPE` in bot constants) is superseded.

**Signatures:** `getInstance(scope: StorageScope = StorageScope.DEFAULT)`,
`injectConfig(configManager, scope: StorageScope = StorageScope.DEFAULT)`,
`__new__(scope: StorageScope = StorageScope.DEFAULT)` — argless calls still
return the default instance (§4.3). There is deliberately **no coercion**
from raw strings: a `str` smuggled past the type checker fails fast at
runtime (`scope.value` → `AttributeError`) instead of silently resolving to
a null-backed store (see §6, unknown-scope row).

There are exactly **two sanctioned scopes** (`DEFAULT` + `VISION`) at design
time; the enum is the closed set of sanctioned spellings.

**Semantics of an absent `[storage.storages.vision]` (confirmed as-is in the
final ratification round):** the vision scope resolves to a
`NullStorageBackend` — vision storage simply off. The existing null-backend
warning at `base.py`:2234-2239 keeps firing at store time (message updated
to point at `[storage.storages.vision]`), and `_loadNativeVisionImages`
null-`get`s degrade to the description fallback. This is the cleaner mental
model: every scope's backend is always fully determined by its own config
table; nothing implicit crosses scope boundaries. The alternative —
inheriting the default `[storage]` backend — is rejected because it would
silently re-couple the two features the split exists to decouple (flipping
the attachments backend would flip vision storage too), and because "no
fallback" was the ratified stance in the migration context (decision 3);
absent-config inheritance is the same class of hidden fallback.
### 4.6 Call-site migration list (exact)
| Site | Change |
|---|---|
| [`base.py`](../../internal/bot/common/handlers/base.py):166 `self.storage = StorageService.getInstance()` | **None** — stays default scope (attachments). |
| `base.py` `__init__` :181-193 vision caching block | Delete the `self._visionStorePrefix` line (:193 — the attribute dies, not re-sourced, §4.4); add `self.visionStorage = StorageService.getInstance(StorageScope.VISION)` (import `StorageScope` from `internal.services.storage`). |
| `base.py`:2234 null-check | `self.storage.backendType` → `self.visionStorage.backendType`; warning text names `[storage.storages.vision]`. |
| `base.py`:2279 key building | `key = f"{self._visionStorePrefix}{sha512}.{ext}"` → `key = f"{sha512}.{ext}"` (bare key, §4.4). |
| `base.py`:2281-2282 exists/store | `self.storage` → `self.visionStorage`. |
| `base.py`:2292-2327 `storeAttachment` | **None** — default scope. |
| [`ensured_message.py`](../../internal/bot/models/ensured_message.py):1088 | `StorageService.getInstance()` → `StorageService.getInstance(StorageScope.VISION)` (`StorageScope` imported from `internal.services.storage` — same direction as the existing `StorageService` import; no cycle). |
| [`manager.py`](../../internal/bot/common/handlers/manager.py):454-455 | Default inject unchanged; vision inject + `self.visionStorage` added per §4.3 (default first, then vision; absent vision table → null backend, no crash). |
| [`resender.py`](../../internal/bot/common/handlers/resender.py):406 | **None** — default scope via `self.storage`. |

Ordering note: `HandlersManager.__init__` injects both scopes **before** the
handler pipeline is constructed, so `BaseBotHandler.__init__`'s
`getInstance(StorageScope.VISION)` returns an already-injected instance in
production. In tests that construct handlers directly without the manager,
`self.visionStorage` may be an uninitialized instance (backend `None`) —
identical to the pre-split behavior of `self.storage` in the same situation:
`_storeVisionImage` is never-raise and `_loadNativeVisionImages` is
never-raise, so both degrade exactly as they do today.
### 4.7 Deletion list (ratified decision 2 sweep)
Production code and default configs:

1. [`vision.toml`](../../configs/00-defaults/vision.toml):8 — the
   `store-prefix` line. **Dies entirely — no destination**: nothing replaces
   it (ratified decisions 2/5; the round-1 "moves into `storage.toml`'s
   commented named-storage block" destination is superseded). The file keeps
   its other four keys and header comment.
2. [`internal/config/models.py`](../../internal/config/models.py):29 — the
   `"store-prefix": str` entry in `VisionConfigDict` (class docstring needs
   no change; its example does not mention the key).
3. [`internal/config/manager.py`](../../internal/config/manager.py) —
   `getVisionConfig` docstring: drop the `store-prefix` bullet (:463) and the
   example line (:477).
4. [`base.py`](../../internal/bot/common/handlers/base.py):193 — the
   `self._visionStorePrefix` attribute **and** its
   `getVisionConfig().get("store-prefix", ...)` sourcing (deleted, not
   re-sourced — §4.4); also the `_storeVisionImage` docstring wording at
   :2212-2216 (drop `_visionStorePrefix` from the cached-settings list; the
   storage key is now the bare `{sha512}.{ext}`, no cached prefix involved).

**Explicit migration consequence** (also a failure-matrix row in §6): every
pre-split `vision_url` value (format `vision/{sha512}.{ext}`) becomes
**permanently unreadable** at cutover — post-split reads target the
vision-scoped store with bare keys, and there is no migration or dual-read
fallback (ratified decision 3, strengthened by decision 5). Affected rows
degrade to the existing description fallback; no DB data is lost, only the
byte availability of those normalized copies.

Live docs (Phase 3; see §7 for the full matrix). Dated artifacts are **not**
edited — ADR-027/ADR-028 bodies in [`architecture.md`](../llm/architecture.md)
and the design docs
[`native-vision-design-v1.md`](native-vision-design-v1.md) /
[`native-vision-v2-construction-attach.md`](native-vision-v2-construction-attach.md)
keep their historical `store-prefix` references (house history-immutability
rule; the ADR-029 record and this doc carry the change).

Grep-clean acceptance for Phase 2: `store-prefix` matches only in dated
artifacts (ADR-027/028 bodies, the two native-vision design docs,
`teamlead-memory.md` history bullets) — zero matches in production code,
`configs/`, or live doc sections; additionally `_visionStorePrefix` has
zero matches in production code.
## 5. Micro-decisions (a–j) — resolved (2026-10-04 final ratification)
Status after the 2026-10-04 final ratification: rows a and b carry the
user's final-delta answers (they supersede the draft's recommendations and
are no longer recommendations); rows c-j are design decisions carried in the
ratified doc, updated below where the deltas ripple.

| # | Question | Decision (status) | Where |
|---|---|---|---|
| a | Absent `[storage.storages.vision]` semantics + scope constants | **User-confirmed as-is + StrEnum delta**: absent table → null backend (vision off; existing store-time warning fires); NO inheritance from the default. Default `[storage]` conceptually the attachments store, keeps the `default` scope name. Scopes typed as `StorageScope(StrEnum)` (`DEFAULT`/`VISION`) in the storage package — the draft's plain-string constants sketch is superseded. | §4.5 |
| b | Prefix key placement + layering | **User-decided (final delta): NO app-layer prefix at all.** Named tables carry only the default shape; separation via `base-dir`/bucket (+ the existing backend-level s3 `prefix`, which stays as-is). Vision keys are bare `{sha512}.{ext}`; `_storeVisionImage` key building simplifies at `base.py`:2279; `_visionStorePrefix` deleted. The draft's named-storage-level `prefix` recommendation is superseded. | §4.4 |
| c | Registry design | `_instances: Dict[str, StorageService]` replacing `_instance`; `__new__(scope)` registers per `scope.value` under the reused `_lock`; `getInstance(scope=StorageScope.DEFAULT)` — argless keeps returning the default instance; `injectConfig(configManager, scope=StorageScope.DEFAULT)` reads the named table internally (accessor dropped, §4.2) with a shared `_buildBackend` validation chain; absent named → null, bad named → `StorageConfigError`; manager injects default then vision, both crash identically on bad config. | §4.3 |
| d | Call-site migration | Exact table: base.py `self.storage` unchanged (attachments); `_storeVisionImage` (bare-key building at :2279) + null-warning + `_loadNativeVisionImages` move to the vision scope (`self.visionStorage` cached at `BaseBotHandler.__init__`; `_visionStorePrefix` deleted); resender + `storeAttachment` untouched. | §4.6 |
| e | Deletion list | vision.toml key, `VisionConfigDict` entry, `getVisionConfig` docstring lines, base.py `_visionStorePrefix` attribute + sourcing + docstring mentions (dies entirely, no re-source); live docs in §7; dated ADR/design texts untouched. | §4.7, §7 |
| f | ADR | New **ADR-029** (next number verified — ADR-028 is the last in `architecture.md`) documenting scoped storage instances + the singleton-rule refinement (arg-less `getInstance()` preserved for default; scoped `getInstance(StorageScope.NAME)` is the sanctioned extension, referencing ADR-001 without rewriting it) + the no-prefix/bare-key decision + the StrEnum scope typing. | §7, §8 |
| g | Test strategy | Scoped-instance unit tests; reset-site updates (now **five** files — incl. `test_stats.py`, missed by the original census; with the accessor dropped its real-manager tests need **no** new config mock — §8); `_storageDouble`/patch compatibility (Mock ignores the scope arg — pin with the suite itself); vision store/read integration through the vision scope with bare keys; attachments-isolation regression. | §8 |
| h | Docs/CHANGELOG matrix | Decision-matrix style table in §7 covering configuration.md (storage + vision keys), services.md §4/§8, handlers.md §9, index.md, ADR-029, CHANGELOG, schema docs (vision_url key shape becomes bare `{sha512}.{ext}`; verified: no doc claims vision shares the attachments store — both schema docs explicitly say "distinct from `local_url`"), storage README, README.md. No ConfigManager-accessor row (dropped, §4.2). | §7 |
| i | Phasing | Three software-developer-sized phases: (1) inert scoped service + enum + tests; (2) vision call-site migration + prefix deletion + deletion sweep + test migration; (3) docs-writer sync + ADR-029 + CHANGELOG. Each with acceptance criteria and gates (`make format lint`, `make test`; `make check-docs` for Phase 3). | §8 |
| j | fs/s3 prefix asymmetry | **Moot for vision** under bare keys (no slash to sanitize asymmetrically); the scoped store holds only vision objects → future GC lists everything, no prefix filtering. One informational paragraph for the future GC follow-up — no action in this arc. | §9 |
## 6. Edge cases / failure matrix
| Case | Behavior | Rationale / verification |
|---|---|---|
| `[storage.storages.vision]` absent | Vision scope = `NullStorageBackend`; INFO log at inject; store-time warning fires at `base.py`:2234; `_loadNativeVisionImages` `get` returns `None` → description fallback. | Confirmed as-is in the final ratification round (§3); parity with today's default `[storage] type = "null"` deployment. |
| `[storage.storages.vision]` present but invalid (missing/unknown `type`, missing `fs.base-dir`, missing s3 params) | `StorageConfigError` from the shared `_buildBackend` → escapes `HandlersManager.__init__` → startup crash (`main.py`:497-500). | Ratified decision 4. |
| `[storage.storages.vision]` present with `type = "null"` | Legal, explicit off — same runtime behavior as absent. | Explicit beats implicit; no special-casing. |
| Default `[storage]` missing/empty | Crash — **unchanged** from today (`getStorageConfig()` → `{}` → `StorageConfigError`). The asymmetry vs absent-named is intentional: the default store is mandatory (attachments is a long-standing feature with defaults shipping `[storage]`); named stores are opt-in per feature. | §4.3. |
| Misspelled/unknown scope at a call site | **Compile-time rejection**: pyright flags any non-`StorageScope` argument — plain strings are type errors, including correctly-spelled ones. A raw string smuggled past the type checker fails fast at runtime (`scope.value` → `AttributeError`) instead of silently resolving to a store. The enum is the closed set of sanctioned spellings. | Ratified decision 6; supersedes the draft's open-keyed plain-string registry row. |
| Pre-split `vision_url` rows (format `vision/{sha512}.{ext}`) after cutover | Read misses in the vision-scoped store (bare keys) → `_loadNativeVisionImages` degrades to the description fallback. **Permanently unreadable** — no migration, no dual-read; the old objects live in the old default store. | Ratified decision 3, strengthened by decision 5 (§4.4, §4.7). |
| Handler constructed before manager inject (tests only) | `self.visionStorage` uninitialized → `backendType` is `None` (≠ `"null"`) → `_storeVisionImage` proceeds to `exists()` → `StorageConfigError` → caught by the never-raise boundary → WARNING. Same degradation class as `self.storage` today. | §4.6 ordering note. |
| Re-inject for one scope while another is live | Only the target scope's `backend` is replaced; other scopes untouched. | Per-instance state isolation (verified: `backend` + `initialized` only). |
| `[storage]` gains a `storages` key (always, after defaults ship the commented block) | Ignored by `_buildBackend` — unknown-key tolerance is existing behavior. | Verified §2. |
| Concurrent `getInstance(scope)` from threads | `RLock` guards registry mutation; per-scope instances are handed out immutably once created. | Same guarantee as today, keyed on `scope.value`. |
## 7. Docs / CHANGELOG impact matrix
| Surface | Change | When |
|---|---|---|
| [`configuration.md`](../llm/configuration.md) | §`[storage]` (:350): document `[storage.storages.*]`, the commented example, the no-prefix decision (§4.4 — the backend-level s3 `prefix` is the only prefix), absent-named → null, bad-named → crash. Vision key table (:88-95): drop the `store-prefix` row (five → four keys); fix the "FIVE keys" claim at :1074. No accessor-table row (dropped, §4.2). | Phase 3 |
| [`services.md`](../llm/services.md) | §4 StorageService: scoped instances (registry, `StorageScope` enum + import path, `getInstance(scope)`, `injectConfig(scope)`, absent-named semantics). §8: note the StorageService exception to the `_instance = None` reset rule — tests reset with `StorageService._instances.clear()`. | Phase 3 |
| [`handlers.md`](../llm/handlers.md) | §9 (:626): vision bytes go to the **vision-scoped** store (`[storage.storages.vision]`) under **bare `{sha512}.{ext}` keys** (replaces the `vision/{sha512}.{ext}` + `store-prefix` wording); :629 config-caching bullet drops `_visionStorePrefix`; null-check warning wording. | Phase 3 |
| [`architecture.md`](../llm/architecture.md) | New **ADR-029** after ADR-028 (:1191) — full decision record (§8 of this doc sketches the content). ADR-001 body untouched (referenced, not rewritten). | Phase 3 (architect supplies text; docs-writer inserts) |
| [`index.md`](../llm/index.md) | :53 vision bullet ("requires a configured storage backend … stored under `vision/`" → requires a configured vision storage (`[storage.storages.vision]`); bare `{sha512}.{ext}` keys in the scoped store); StorageService rows (:312/:333/:358) mention scoped `getInstance(StorageScope…)`. | Phase 3 |
| [`database-schema.md`](../database-schema.md) + [`database-schema-llm.md`](../database-schema-llm.md) | `vision_url` semantics rows (:480 / :203): key format becomes bare `{sha512}.{ext}` held in the **vision-scoped** storage; note that pre-split rows hold legacy `vision/…` values that are no longer readable (description fallback). **Verified**: neither doc claims vision shares the attachments store — both explicitly say "distinct from `local_url`" — so no same-store correction is needed. | Phase 3 |
| [`internal/services/storage/README.md`](../../internal/services/storage/README.md) | Add the named-storage config shape + scoped `getInstance` example (with `StorageScope`) to the inline README (edited with normal file tools — outside the markdown-mcp docs root). | Phase 3 |
| [`README.md`](../../README.md) | :22 native-vision bullet — "requires a configured storage backend" → "requires a configured vision storage (`[storage.storages.vision]`)". :32 File-storage line optionally mentions named storages. | Phase 3 |
| [`CHANGELOG.md`](../../CHANGELOG.md) | Under `## [Unreleased]`: **Added** — named storages under `[storage.storages.*]` allowing per-feature backends (attachments vs native vision), selected via the new `StorageScope`-typed `getInstance`/`injectConfig`; **Changed** — `bot.vision.store-prefix` removed: vision objects now live in their own scoped storage under bare `{sha512}.{ext}` keys, and pre-existing `vision_url` rows become unreadable (description fallback applies); invalid named-storage config now aborts startup. | Phase 3 (entry drafted with the Phase 2 commit per house changelog rules) |
| ADR-027 / ADR-028 / native-vision design docs v1+v2 / `teamlead-memory.md` history | **No edits** (dated artifacts; history immutability). | — |
## 8. Phasing and test strategy

Sized for ~three `software-developer` invocations; each phase lands green
behind `make format lint` + `make test` (Phase 3 additionally
`make check-docs`).

### Phase 1 — inert scoped StorageService (no production call-site changes)
**Changes**

1. `service.py`: `StorageScope` enum + package `__init__.py` re-export
   (`from .service import StorageService, StorageScope`, `__all__` gains it),
   `_instances` registry, scoped `__new__`/`getInstance`,
   `injectConfig(scope=...)` with the internal named-table read (§4.2),
   `_buildBackend` extraction (verbatim chain move).
2. `storage.toml`: commented `[storage.storages.vision]` example (§4.1 —
   default shape only, no prefix key).
3. Tests:
   - `tests/services/storage/test_service.py`: autouse reset →
     `StorageService._instances.clear()`; new `TestStorageServiceScopedInstances`
     — distinct instance per scope; same instance per scope across repeated
     calls; **argless `getInstance()` is `getInstance(StorageScope.DEFAULT)`**
     (identity assert — the backward-compat pin); `injectConfig` per scope via
     a mocked `getStorageConfig` returning `{"storages": {"vision": {...}}}`;
     absent named (no `storages` key) → null backend, no raise; bad named
     (missing type / unknown type / missing `fs.base-dir` / missing s3
     params) → `StorageConfigError`; re-inject per scope independence;
     `_buildBackend` parity (same table-driven error cases as the existing
     default-scope tests).
   - `tests/services/storage/test_integration.py`: same reset change; scoped
     roundtrip with a real `FSStorageBackend` on a tmpdir through
     `injectConfig(scope=StorageScope.VISION)`.
   - Existing default-scope tests must pass **unmodified except the reset
     fixture** — that is the inertness proof.

**Acceptance**: no production file outside `service.py` / the storage
package `__init__.py` / `storage.toml` changed — notably `config/manager.py`
and `internal/bot/constants.py` are untouched in Phase 1 (the accessor was
dropped, §4.2; the scope enum lives in the storage package, §4.5); full
suite green. **Gates**: `make format lint`, `make test`.
### Phase 2 — vision call-site migration + prefix deletion + deletion sweep
**Changes**

1. `manager.py`: vision inject + `self.visionStorage` (§4.3).
2. `base.py`: `__init__` block (delete `_visionStorePrefix`, add
   `self.visionStorage`, §4.4); `:2279` bare-key building; `:2234` /
   `:2281-2282` scope flips; warning text; docstring wording (:2212-2216).
3. `ensured_message.py`: `getInstance(StorageScope.VISION)` at :1088.
4. Deletion sweep (§4.7 items 1-4).
5. Test migration (census-gap lesson: grep tests for
   `StorageService\._instance|getStorageConfig|getInstance`, not just known
   files):
   - Reset updates: `test_base.py` ×2 autouse fixtures, `test_stats.py`
     :1538/:1605. **No new config mock needed in `test_stats.py`**: with the
     accessor dropped (§4.2), the vision inject reads `getStorageConfig()` —
     already mocked there to `{"type": "null"}` (:1557/:1623) — and
     `.get("storages", {})` → `{}` resolves the vision scope to a null
     backend without raising. Verify, don't add.
   - `test_base.py` real-inject sites (:1848, :2664, :2701): inject the
     vision scope alongside the default where the test exercises vision
     paths; `_visionStorePrefix` init-caching tests are **deleted** with the
     attribute — key-building coverage moves to asserting bare
     `{sha512}.{ext}` keys.
   - `test_llm_messages.py` / `test_ensured_message.py`: no changes expected
     — `patch.object(..., return_value=...)` doubles ignore the scope
     argument by construction; the suite passing post-migration **is** the
     compatibility pin. If any patch uses `side_effect` or asserts call args
     on `getInstance`, extend it to accept the scope argument.
   - New: vision store → read integration through the vision scope (fs
     tmpdir): `_storeVisionImage` writes **bare `{sha512}.{ext}` keys**,
     `vision_url` published, `_loadNativeVisionImages` reads back via the
     vision scope.
   - New: isolation regression — default scope fs + vision scope on a
     different tmpdir; assert `storeAttachment` writes land only in the
     default dir and vision writes only in the vision dir; resender read-back
     unchanged.
   - New: manager-level crash — bad `[storage.storages.vision]` →
     `HandlersManager` construction raises `StorageConfigError`.

**Acceptance**: §4.7 grep-clean (`store-prefix` only in dated artifacts;
`_visionStorePrefix` zero matches in production code); suite green.
**Gates**: `make format lint`, `make test`.
### Phase 3 — docs-writer sync + ADR + CHANGELOG
1. Load the `update-project-docs` skill; apply the §7 matrix.
2. ADR-029 insertion into `architecture.md` after ADR-028 (architect supplies
   the text; `doc_section_edit` insert-after is the house mechanism). Content
   sketch: context (two features, one backend object); decision (scoped
   instances keyed by `[storage.storages.NAME]`, same-shape tables, selected
   via a `StorageScope` StrEnum — plain strings are type errors at call
   sites; one enum member per future storage); singleton-rule refinement
   (ADR-001 referenced: arg-less `getInstance()` remains the default-scope
   contract everywhere; `getInstance(StorageScope.NAME)` is the sanctioned
   extension for features needing isolated backends — not a license for
   casual scope proliferation); no app-layer prefix — bare
   `{sha512}.{ext}` vision keys, separation via backend placement only
   (supersedes the `[bot.vision].store-prefix` part of ADR-027's config
   sketch — dated ADR text untouched, this ADR records the deletion);
   absent-named → null; bad-named → crash; no-migration stance with
   pre-split `vision_url` rows permanently unreadable (description fallback
   covers them); GC note (the scoped store holds only vision objects — a
   future TTL-GC lists everything, no prefix filtering); test-reset
   convention change (`_instances.clear()`).
3. CHANGELOG entries (§7).
4. Flip this doc's Status line per house convention when the arc lands
   (Ratified → Implemented at completion).

**Gates**: `make check-docs` (plus `markdown-mcp lint` advisory), `make test`
still green.
## 9. Note for the future GC follow-up (no action)
Under bare keys (§4.4) the fs/S3 prefix-asymmetry caveat this section used
to carry is **moot for vision**: `{sha512}.{ext}` contains no slash, so
`sanitizeKey` ([`utils.py`](../../internal/services/storage/utils.py):62)
passes it through unchanged — the fs backend stores flat `<sha512>.<ext>`
files
([`filesystem.py`](../../internal/services/storage/backends/filesystem.py):79-80)
and the S3 backend stores the same key shape, optionally under its
backend-level prefix
([`s3.py`](../../internal/services/storage/backends/s3.py):108-110), which
stays transparent to readers. There is no app-layer prefix whose sanitized
form (`vision_`) could diverge from its raw form (`vision/`) anymore; that
divergence is now only a property of the attachments store's legacy keys,
pre-existing and unchanged by this design.

The natural consequence recorded in §4.4: the scoped vision store contains
ONLY vision objects, so a future TTL-GC sweep (the `[bot.vision].ttl-days`
retention knob) simply lists everything in the scoped store — no prefix
filtering, no foreign objects to spare. Pre-split objects (written to the
old default store as `vision_<sha>.<ext>` on fs / `vision/<sha>.<ext>` or
backend-prefixed on S3) are unreachable by reads after cutover anyway
(§3 decisions 3/5); reclaiming their space in the old store is possible as
a one-off manual cleanup but is deliberately not specced here. This note
exists so the GC follow-up starts from the right key model.
## 10. Open questions — resolved (2026-10-04 final ratification)
All questions from the draft are closed by the 2026-10-04 final ratification
deltas; none remain open.

1. **Prefix default when the named table exists but omits `prefix`** —
   RESOLVED: **no prefix at all**. The question is void — there is no
   app-layer `prefix` key, no `"vision/"` default, and no
   `_visionStorePrefix` to default. Vision keys are bare `{sha512}.{ext}`
   (§4.4); of the draft's two options the bare-key side won outright, on
   stronger grounds than the draft argued (separation belongs to backend
   placement, not key spelling).
2. **`self.visionStorage` on `HandlersManager`** — RESOLVED: **yes**
   (confirmed as-is; symmetry with `self.storage`, §4.3), even though
   `BaseBotHandler`/`ensured_message` fetch the scope themselves.
3. **Scope constants: plain strings vs enum** — RESOLVED: **enum**
   (`StorageScope(StrEnum)`, members `DEFAULT = "default"` /
   `VISION = "vision"`, defined in and re-exported from the storage package —
   §4.5). The draft's plain-string constants sketch
   (`DEFAULT_STORAGE_SCOPE` in service.py + `VISION_STORAGE_SCOPE` in bot
   constants) is superseded.
4. **`getNamedStorageConfig` accessor** — RESOLVED: **dropped** (§4.2); its
   only consumer died with the prefix, so `injectConfig` reads named tables
   internally.

No other blockers — every remaining question from the brief is resolved by
§4/§5/§6.
## 11. References
- Source: [`service.py`](../../internal/services/storage/service.py),
  [`__init__.py`](../../internal/services/storage/__init__.py) (gains the
  `StorageScope` re-export),
  [`utils.py`](../../internal/services/storage/utils.py),
  [`backends/s3.py`](../../internal/services/storage/backends/s3.py),
  [`backends/filesystem.py`](../../internal/services/storage/backends/filesystem.py),
  [`backends/null.py`](../../internal/services/storage/backends/null.py)
- Call sites: [`base.py`](../../internal/bot/common/handlers/base.py),
  [`manager.py`](../../internal/bot/common/handlers/manager.py),
  [`resender.py`](../../internal/bot/common/handlers/resender.py),
  [`ensured_message.py`](../../internal/bot/models/ensured_message.py)
- Config: [`config/manager.py`](../../internal/config/manager.py),
  [`config/models.py`](../../internal/config/models.py),
  [`storage.toml`](../../configs/00-defaults/storage.toml),
  [`vision.toml`](../../configs/00-defaults/vision.toml)
- Docs: [`architecture.md`](../llm/architecture.md) (ADR-001, ADR-027,
  ADR-028; ADR-029 to come),
  [`services.md`](../llm/services.md) §4/§8,
  [`handlers.md`](../llm/handlers.md) §9,
  [`configuration.md`](../llm/configuration.md),
  [`index.md`](../llm/index.md),
  [`database-schema.md`](../database-schema.md),
  [`database-schema-llm.md`](../database-schema-llm.md)
- Tests: [`test_service.py`](../../tests/services/storage/test_service.py),
  [`test_integration.py`](../../tests/services/storage/test_integration.py),
  [`test_base.py`](../../tests/bot/common/handlers/test_base.py),
  [`test_llm_messages.py`](../../tests/bot/common/handlers/test_llm_messages.py),
  [`test_stats.py`](../../tests/bot/common/handlers/test_stats.py),
  [`test_ensured_message.py`](../../tests/bot/models/test_ensured_message.py)
- Related designs: [`native-vision-design-v1.md`](native-vision-design-v1.md),
  [`native-vision-v2-construction-attach.md`](native-vision-v2-construction-attach.md)
- Entry point: [`main.py`](../../main.py):497-500 (crash path)
