# Chat Accessibility Tracking — Design Document

> Status: implementation-ready, single phase
> Owner: see implementer hand-off (section 9)
> Scope marker: this is the **only** phase. There is no Phase 2 (event wiring) and no
> Phase 3 (outbound deferral). See section 2 (Out of scope) for the binding exclusions.

---

## Implementation Divergence (2026-08-12)

> **The body below is the original design rationale and is preserved as historical.**
> The shipped implementation simplifies this design in roughly fifty places. For the
> CURRENT behavior, read [`docs/llm/services.md`](../llm/services.md) (CacheService
> accessibility surface), [`docs/llm/handlers.md`](../llm/handlers.md) (mark-on-failure
> and recovery hooks), and [`docs/llm/database.md`](../llm/database.md) (repository
> surface) — not the sections under this heading.

The implementation consolidated accessibility state into the existing
`chat_info.bot_status` column, accessed through the existing
`CacheService.getChatInfo` / `setChatInfo` cache-aside path. There is no longer a
separate in-memory mirror of the column. Concretely, the shipped code diverges from
the body below in these ways:

- **No `_inaccessibleChats` in-memory set.** `CacheService` does not hold a per-process
  mirror of `bot_status`. The accessibility surface is read-through `getChatInfo`
  (in-memory cache first, DB on miss).
- **`CacheService.isChatInaccessible(chatId) -> bool` is `async`** and is a cache-aside
  lookup: it returns `True` if the chat is unknown to `getChatInfo` (fail-closed) or if
  `bot_status == ChatBotStatus.INACCESSIBLE`, otherwise `False`. It is no longer a
  synchronous O(1) set-membership check.
- **`CacheService.markChatInaccessible(chatId) -> bool` and `markChatActive(chatId) -> bool`
  are `async`** and route through `getChatInfo` (read) and `setChatInfo` (write) — they
  set `bot_status` in the `ChatInfoDict` and persist cache + DB via `setChatInfo`. Both
  return `False` if the chat is not found; they do not call a dedicated status-mutation
  repository method.
- **`ChatInfoRepository.setChatBotStatus` and `ChatInfoRepository.getInactiveChatIds`
  were REMOVED.** Persistence of `bot_status` goes through the existing
  `updateChatInfo`, which gained an optional keyword-only argument
  `botStatus: Optional[ChatBotStatus] = None`:
  - `None` (the default) → `bot_status` is omitted from the upsert's `values` *and* its
    `CONFLICT`-UPDATE expressions. The routine every-message refresh callers pass
    nothing, so a refresh can never clobber an `INACCESSIBLE` row back to `ACTIVE`
    (the non-clobber invariant from §3 of the body still holds, now implemented by
    argument omission rather than by a hardcoded column skip).
  - provided → `bot_status` is written into both the INSERT `values` and the
    CONFLICT-UPDATE expressions. `CacheService.setChatInfo` forwards
    `info.get("bot_status")`, so `markChatInaccessible` / `markChatActive` reach the
    column via the same upsert path as every other `chat_info` write.
- **The `idx_chat_info_bot_status` index was REMOVED from migration 026.** Migration 026
  now adds ONLY the `bot_status TEXT NOT NULL DEFAULT 'active'` column (no supporting
  index). `down()` drops the column (SQLite ≥3.35); there is no index to drop.
- **The `BaseBotHandler.getUserChats` wrapper was REMOVED.** Consumers call
  `self.db.chatUsers.getUserChats(...)` (and `getAllGroupChats(...)`) directly and
  inherit the `botStatus=ChatBotStatus.ACTIVE` default.
- **The `CacheService.injectDatabase` startup-seed of the in-memory set was REMOVED.**
  It is no longer needed: `isChatInaccessible` is cache-aside and reads the DB on a
  cache miss, so the first post-restart probe of a known-dead chat hits the DB once
  and is then cached — there is no separate warm-up pass.

**Behavioral nuance (self-healing).** The every-message refresh writes a
`bot_status`-less `ChatInfoDict` into the `CacheService` cache. Until the next
`getChatAdmins` failure re-marks the chat `INACCESSIBLE`, `isChatInaccessible` returns
`False` for a chat that is `INACCESSIBLE` in the DB. The DB column and the
`getUserChats` / `getAllGroupChats` `botStatus` filter remain authoritative throughout
— only the in-process cache-aside short-circuit is briefly lenient — and the next
failure probe restores the cache. This is the trade-off for dropping the in-memory
mirror: no startup-seed, no eviction bookkeeping, at the cost of a transient
cache/DB divergence on the read-short-circuit path.

For everything else — binding decisions (no `bot_left_at`, no event wiring, no
Phase 3), the `ChatBotStatus` enum values, the lazy mark-on-failure / activity-based
recovery shape, the `botStatus` filter parameter on the chat-list queries, the DM
dormancy rationale — the body below remains accurate.

---

## 1. Overview / Goal

Today the bot has no durable record of whether it is still present in a given chat. When
the bot is kicked from a group or blocked in a DM, that fact is only observable as a
transient API failure inside [`TheBot.getChatAdmins`](../../internal/bot/common/bot.py)
([`internal/bot/common/bot.py:166`](../../internal/bot/common/bot.py)), which already
degrades gracefully by returning `{}` and skipping the cache. The failure is not
persisted, so every chat-listing consumer keeps surfacing the dead chat. This forces
handlers such as `/configure` ([`chatConfiguration_Init`](../../internal/bot/common/handlers/configure.py)
at [`internal/bot/common/handlers/configure.py:191`](../../internal/bot/common/handlers/configure.py))
to iterate chats the bot can no longer reach, and for each one re-attempt an admin probe
that will fail again — visibly slow, and it has caused crashes when downstream code
assumed the chat was reachable.

**Goal:** persist a per-chat accessibility flag on the `chat_info` table, set it to
`INACCESSIBLE` lazily at the existing `getChatAdmins` failure catch sites, recover it to
`ACTIVE` lazily from inbound activity, and have every chat-listing consumer skip
`INACCESSIBLE` chats by default. A small in-memory short-circuit in `CacheService`
additionally prevents repeated redundant probes of known-dead chats within a single
process lifetime.

---

## 2. Scope

### In scope (single phase)

1. A new `bot_status` column on `chat_info` + a `ChatBotStatus` StrEnum
   (`ACTIVE`, `INACCESSIBLE`).
2. Migration **026** adding the column (with a portable `'active'` default that backfills
   existing rows) + a supporting index.
3. Lazy mark-on-failure at the existing `getChatAdmins` catch sites (Telegram + Max).
4. Lazy activity-based recovery in the message preprocessor (the sole recovery hook).
   The in-memory known-inaccessible set is seeded from the DB at startup
   (`CacheService.injectDatabase`) so the preprocessor hook works immediately after a
   restart — no second recovery hook is needed (see §5, including §5.3 for why the
   mark-on-success backstop originally considered was rejected).
5. An optional `botStatus` filter parameter on every chat-listing repository method and
   its handler wrapper (default = `ACTIVE` only; `None` = all chats).
6. An in-memory "known-inaccessible" set in `CacheService` that short-circuits
   `getChatAdmins`/`isAdmin` for chats already known to be dead this process.

### Out of scope (binding user decisions — do not re-litigate)

- **No `bot_left_at` timestamp.** Storage is the `bot_status` column alone (binding
  decision 1).
- **No event-driven wiring.** No Telegram `my_chat_member` handler, no `ChatMemberHandler`,
  no Max `BOT_ADDED` / `BOT_REMOVED` / `BOT_STOPPED` event handling. Recovery is purely
  activity-based (binding decision 3).
- **No Phase 3 outbound deferral.** `QueueService` and `delayed_tasks` are untouched; no
  deferred-send queue for dead chats (binding open-question resolution c).
- **No owner-facing command / UI** for inspecting or mutating accessibility status
  (binding open-question resolution e).
- **`getChatInfo` (the platform metadata probe) is NOT a detection hook** in this phase.
  Detection stays pinned to `getChatAdmins` (binding decision 2). See section 12.
- DM-block **is** tracked as `INACCESSIBLE` via the same `getChatAdmins` mechanism
  (binding open-question resolution d). Section 8 covers the practical caveats.

### Binding decisions encoded

| # | Decision | Where encoded |
|---|---|---|
| 1 | Storage = `bot_status` column only; no `bot_left_at` | §3 |
| 2 | Detection = lazy mark-on-failure at `getChatAdmins` catch sites | §4 |
| 3 | Recovery = lazy via inbound activity in the preprocessor; no events | §5 |
| 4 | Consumers skip `INACCESSIBLE` by default; optional `botStatus` param (None = all) | §7 |
| 5a | StrEnum (not boolean) | §3 |
| 5b | Backfill existing rows to `active` | §3 (DDL `DEFAULT 'active'`) |
| 5c | No Phase 3 outbound deferral | §2 (out of scope) |
| 5d | Track private-chat / DM-block as `INACCESSIBLE` too | §4, §8 |
| 5e | No owner-facing command/UI | §2 (out of scope) |
| 5f | In-memory `CacheService` short-circuit included now | §6 |

---

## 3. Data Model

### 3.1 `ChatBotStatus` StrEnum

Minimal two-member set. Lives in [`internal/database/models.py`](../../internal/database/models.py)
alongside `MediaStatus` / `ChatType` etc., because it is a column value (DB layer) and
must not create an upward import into `internal.bot`.

```python
from enum import StrEnum


class ChatBotStatus(StrEnum):
    """Durable accessibility state of the bot for a chat (``chat_info.bot_status``).

    Members:
        ACTIVE: The bot is (or is assumed to be) present in the chat. This is the
            optimistic default for every row — newly inserted chats and all pre-existing
            rows backfilled by migration 026 start here. Recovery (inbound activity in
            the preprocessor, §5.1) flips ``INACCESSIBLE`` back to ``ACTIVE``.
        INACCESSIBLE: A platform API call failed because the bot is no longer in the
            chat / was blocked (Telegram ``Forbidden`` / ``BadRequest("chat not found")``
            / Max ``NotFoundError``). Set lazily at the ``getChatAdmins`` catch sites.
            Chat-listing consumers exclude these chats by default.
    """

    ACTIVE = "active"
    """Bot is present or assumed present (optimistic default)."""

    INACCESSIBLE = "inaccessible"
    """Bot was kicked/blocked/removed; last ``getChatAdmins`` probe failed."""
```

**Why two values and not three (`UNKNOWN`)?** With (a) optimistic `'active'` backfill of
all existing rows, (b) no event source, and (c) lazy detection that only ever observes
definite outcomes (a confirmed API failure), there is no code path that produces a
genuine "unknown" state. A row is `ACTIVE` until a probe definitively fails, at which
point it becomes `INACCESSIBLE`. `UNKNOWN` would be a third state with no writer and no
reader — pure dead surface area. If a future phase introduces `my_chat_member` events
(where a "left" event can arrive without a prior probe), `UNKNOWN` becomes meaningful and
can be added then. Recommended: ship the minimal two-value set now.

### 3.2 Migration 026 — portable DDL

File: `internal/database/migrations/versions/migration_026_chat_accessibility_bot_status.py`
(next free number; highest existing is
[`migration_025_embedding_model_lookup.py`](../../internal/database/migrations/versions/migration_025_embedding_model_lookup.py)).
Follow the shape of
[`migration_010_add_updated_by_to_chat_settings.py`](../../internal/database/migrations/versions/migration_010_add_updated_by_to_chat_settings.py)
(`ALTER TABLE … ADD COLUMN … NOT NULL DEFAULT`) and
[`migration_024_add_bayes_tokens_updated_at_index.py`](../../internal/database/migrations/versions/migration_024_add_bayes_tokens_updated_at_index.py)
(`CREATE INDEX IF NOT EXISTS`, `batchExecute`).

Portable DDL (SQLite / PostgreSQL / MySQL — see [`docs/sql-portability-guide.md`](../sql-portability-guide.md)):

```sql
-- 1. Add the column. The string-literal DEFAULT 'active' is portable across all three
--    RDBMS families AND backfills every existing row to 'active' as part of the
--    ALTER (the app never has to run a separate UPDATE). TEXT NOT NULL with a
--    string default avoids any AUTOINCREMENT/SERIAL/DEFAULT CURRENT_TIMESTAMP concerns.
ALTER TABLE chat_info
    ADD COLUMN bot_status TEXT NOT NULL DEFAULT 'active'

-- 2. Supporting index. The dominant query shape is "list ACTIVE chats" / "list
--    INACCESSIBLE chats" (chat-list filter, section 7); a low-cardinality index on
--    bot_status keeps those filters cheap. snake_case name, idx_ prefix (repo convention).
CREATE INDEX IF NOT EXISTS idx_chat_info_bot_status
    ON chat_info (bot_status)
```

Notes:

- No `AUTOINCREMENT` / `SERIAL` / `DEFAULT CURRENT_TIMESTAMP` — column is plain
  `TEXT NOT NULL DEFAULT '<string-literal>'`, fully portable.
- `DEFAULT 'active'` backfills existing rows on `ALTER TABLE … ADD COLUMN` on all three
  backends (satisfies binding decision 5b without a separate backfill statement).
- No booleans cross the wire; `bot_status` is a string enum value.
- Rollback (`down`): `DROP INDEX IF EXISTS idx_chat_info_bot_status` then
  `ALTER TABLE chat_info DROP COLUMN bot_status` (SQLite ≥3.35 supports `DROP COLUMN`;
  matches the `migration_010` rollback caveat).

Class sketch (AGENTS.md conventions: camelCase methods, docstrings, type hints):

```python
class Migration026ChatAccessibilityBotStatus(BaseMigration):
    """Add ``bot_status`` column + index to ``chat_info`` for accessibility tracking."""

    version: int = 26
    description: str = "Add bot_status column and index to chat_info"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery(
                    "ALTER TABLE chat_info ADD COLUMN bot_status TEXT NOT NULL DEFAULT 'active'"
                ),
                ParametrizedQuery(
                    "CREATE INDEX IF NOT EXISTS idx_chat_info_bot_status ON chat_info (bot_status)"
                ),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP INDEX IF EXISTS idx_chat_info_bot_status"),
                ParametrizedQuery("ALTER TABLE chat_info DROP COLUMN bot_status"),
            ]
        )
```

### 3.3 `ChatInfoDict` extension

In [`internal/database/models.py`](../../internal/database/models.py) (`ChatInfoDict` at
[`internal/database/models.py:192`](../../internal/database/models.py)):

```python
class ChatInfoDict(TypedDict):
    """Dictionary representing chat information."""

    chat_id: int
    title: Optional[str]
    username: Optional[str]
    type: str
    is_forum: bool
    bot_status: NotRequired[ChatBotStatus]
    """Accessibility state of the bot for this chat. Populated on DB-row-backed reads
    (``SELECT *``/``SELECT ci.*`` include the column). Absent on platform-sourced write
    dicts produced by :meth:`TheBot.getChatInfo`, because the accessibility subsystem
    owns this column (see §3.4) and the ``updateChatInfo`` upsert omits it. The
    authoritative value is the DB column; consumers that need it read it via the
    chat-list SQL filter or the dedicated status methods, not from a cached dict."""
    created_at: datetime.datetime
    updated_at: datetime.datetime
```

`NotRequired` (not plain required) mirrors the existing `score` / `model_id` pattern in
`ChatMessageDict` ([`internal/database/models.py:144`](../../internal/database/models.py)):
DB rows always carry the column, platform-sourced write dicts omit it, and the upsert
(§3.4) intentionally does not thread it. `from typing import NotRequired` is already
imported in that module.

### 3.4 `updateChatInfo` non-clobber rule (CRITICAL)

The accessibility subsystem **owns** the `bot_status` column. The routine chat-info
refresh path must not touch it.

The repository upsert
[`ChatInfoRepository.updateChatInfo`](../../internal/database/repositories/chat_info.py)
at [`internal/database/repositories/chat_info.py:42`](../../internal/database/repositories/chat_info.py)
is invoked on every inbound message via
[`BaseBotHandler.saveChatMessage`](../../internal/bot/common/handlers/base.py) →
[`BaseBotHandler.updateChatInfo`](../../internal/bot/common/handlers/base.py) at
[`internal/bot/common/handlers/base.py:1112`](../../internal/bot/common/handlers/base.py)
→ `cache.setChatInfo` → `database.chatInfo.updateChatInfo`. Today its
`updateExpressions` covers `type`, `title`, `username`, `is_forum`, `updated_at`.

Rule:

- **Do NOT add `bot_status` to the `values` dict** of the upsert.
- **Do NOT add `bot_status` to the `updateExpressions` dict.**

Consequence:

- On **INSERT** (new chat), the row gets `bot_status = 'active'` from the column
  `DEFAULT 'active'` — correct (a freshly-seen chat is assumed accessible).
- On **CONFLICT** (existing chat being refreshed), `bot_status` is not in
  `updateExpressions`, so it is **preserved** — a routine refresh can never reset an
  `INACCESSIBLE` chat back to `ACTIVE`, nor clobber an `ACTIVE` chat.

All `bot_status` writes go through dedicated accessibility-subsystem methods on
`ChatInfoRepository` (section 4 / 5), never through `updateChatInfo`.

**Proof that the non-clobber rule holds** (this is the load-bearing claim, so it is
verified against the actual provider, not asserted):

- The SQLite provider's `upsert` ([`internal/database/providers/sqlite3.py:404`](../../internal/database/providers/sqlite3.py))
  builds the INSERT column list **only** from the `values` dict keys
  ([`sqlite3.py:429`](../../internal/database/providers/sqlite3.py): `colsStr = ", ".join(values.keys())`)
  and the `ON CONFLICT … DO UPDATE SET` clause **only** from the `updateExpressions` dict
  ([`sqlite3.py:450`](../../internal/database/providers/sqlite3.py):
  `updateStr = ", ".join([f"{col} = {expr}" for col, expr in translatedExpressions.items()])`).
- Therefore a column absent from **both** dicts is: omitted from the INSERT column list
  on the INSERT path → the row takes the column `DEFAULT 'active'`; and omitted from the
  SET clause on the CONFLICT path → the existing value is preserved.
- The abstract contract on `BaseSQLProvider.upsert`
  ([`internal/database/providers/base.py:390`](../../internal/database/providers/base.py))
  specifies the same semantics ("`values`: Dictionary of column names and values to
  insert"; "`updateExpressions`: Optional dict of column -> expression for UPDATE clause.
  If None, all non-conflict columns are updated with their values"). `updateChatInfo`
  passes an explicit `updateExpressions`, so only its listed columns are touched. The
  PostgreSQL/MySQL providers inherit this contract (they are not selectable today per
  AGENTS.md, but must implement the same shape).

This is why §3.4 is framed as "omit `bot_status` from both dicts" rather than "write a
sentinel": the provider's column-list construction gives us the non-clobber for free.

---

## 4. Inaccessible Detection (lazy mark-on-failure)

### 4.1 Hook point

[`TheBot.getChatAdmins`](../../internal/bot/common/bot.py) at
[`internal/bot/common/bot.py:166`](../../internal/bot/common/bot.py) already implements
graceful degradation. Today it:

- Checks `cache.getChatAdmins(chat.id)` first ([L188](../../internal/bot/common/bot.py));
  on a hit returns the cached admins.
- On a miss, calls the platform API:
  - **Telegram** ([L193-212](../../internal/bot/common/bot.py)): catches
    `telegram.error.Forbidden`, and `telegram.error.BadRequest` **only** when the message
    contains `"chat not found"` (else re-raises — conservative, so real API-usage errors
    still surface). On either, logs a warning and `return {}` **without caching**.
  - **Max** ([L214-229](../../internal/bot/common/bot.py)): catches
    `lib.max_bot.exceptions.NotFoundError` (imported as `maxExceptions` at
    [L20](../../internal/bot/common/bot.py)), logs a warning, `return {}` without caching.
- On success, caches via `cache.setChatAdmins(chat.id, chatAdmins)` ([L234](../../internal/bot/common/bot.py)).

The top-level import `import lib.max_bot.exceptions as maxExceptions` is already present.

**This is the primary detection hook.** The change layers a DB write + an in-memory-set
add on top of the existing empty-`{}` return; the no-cache-on-failure behaviour is
preserved.

### 4.2 What the catch site does (both platforms)

At each of the three `return {}` failure points (Telegram `Forbidden` at L200-203,
Telegram `BadRequest("chat not found")` at L204-212, Max `NotFoundError` at L226-229),
before returning, the bot must:

1. **Persist** the transition: call a new repository method that flips
   `chat_info.bot_status` to `INACCESSIBLE` for `chat.id` (idempotent conditional
   `UPDATE … WHERE bot_status != 'inaccessible'`).
2. **Memoize** in the in-memory set: `cache.markChatInaccessible(chat.id)` (adds
   `chat.id` to the known-inaccessible set — see section 6).
3. **Preserve** the existing `return {}` (no behaviour change for callers; `isAdmin`
   still returns `False`, lists still degrade gracefully).

The `chat.id` is available at all three sites. The bot instance needs a handle to the
database; see section 9 (P3) — the cleanest wiring is to expose the write through
`self.cache` (which already holds `self.database`, see
[`CacheService.injectDatabase`](../../internal/services/cache/service.py) and the
`self.database` references throughout the cache service), so `TheBot` calls
`await self.cache.markChatInaccessible(chat.id)` and the cache service performs both the
in-memory-set add and the DB write against the repo it already holds. This keeps `TheBot`
free of a direct DB dependency for this concern and colocates the two effects (memory +
DB) that must stay in sync.

Sketch (`CacheService.markChatInaccessible`, new method):

```python
async def markChatInaccessible(self, chatId: int) -> None:
    """Record that the bot is inaccessible in ``chatId`` (memory + DB).

    Idempotent. Adds ``chatId`` to the in-memory known-inaccessible set and flips
    ``chat_info.bot_status`` to ``inaccessible`` via a conditional UPDATE (no-op if
    already inaccessible). Called from ``TheBot.getChatAdmins`` failure catch sites.
    """
    self._inaccessibleChats.add(chatId)
    if self.database is not None:
        await self.database.chatInfo.setChatBotStatus(chatId, ChatBotStatus.INACCESSIBLE)
```

Repository method (`ChatInfoRepository.setChatBotStatus`, new):

```python
async def setChatBotStatus(self, chatId: int, status: ChatBotStatus) -> bool:
    """Conditionally set ``chat_info.bot_status`` for ``chatId``.

    Uses a conditional UPDATE (``WHERE bot_status != :status``) so the common case of
    setting the current value is a no-op write and the method is safe to call on every
    probe. Routed by ``chatId``. Cannot write to readonly sources.

    Args:
        chatId: Chat identifier.
        status: Target :class:`ChatBotStatus`.

    Returns:
        True if the row was updated (status actually changed), False otherwise
        (including row-not-found — unknown chats are left to be inserted by the normal
        ``updateChatInfo`` path).
    """
    # provider.execute with :named placeholders; portable across SQLite/PG/MySQL.
    ...
```

The conditional `WHERE bot_status != :status` clause keeps the steady-state cost of
repeated failure probes at a no-op write (matches 0 rows when already inaccessible).

### 4.3 Interaction with the existing stopgap

The existing empty-`{}` no-cache return is the graceful-degradation behaviour callers
rely on (`isAdmin` returns `False`, chat lists degrade). This design **preserves it
exactly** — the DB write and the in-memory-set add are purely additive effects layered
on top. The only new caller-visible effect is that chat-listing consumers will now also
exclude the chat (section 7), which is the desired outcome.

---

## 5. Active Recovery (activity-based)

Recovery flips `INACCESSIBLE → ACTIVE`. Per binding decision 3, the **sole** recovery
hook is inbound activity in the message preprocessor (§5.1). The in-memory set that
gates that hook is seeded from the DB at process startup (§5.2) so recovery works
immediately after a restart. No second (mark-on-success) recovery hook is needed; §5.3
records the mark-on-success backstop that was considered and rejected, and why.

### 5.1 Recovery hook (sole, per binding) — message preprocessor

[`MessagePreprocessorHandler`](../../internal/bot/common/handlers/message_preprocessor.py)
at [`internal/bot/common/handlers/message_preprocessor.py:37`](../../internal/bot/common/handlers/message_preprocessor.py)
processes every inbound message in `newMessageHandler`
([L143](../../internal/bot/common/handlers/message_preprocessor.py)). It already calls
`saveChatMessage` ([L183](../../internal/bot/common/handlers/message_preprocessor.py)),
which in turn calls `updateChatInfo` (`base.py:1112`).

**Write-frequency constraint (binding):** do NOT write to the DB on every message. Only
write on an actual `INACCESSIBLE → ACTIVE` transition.

Implementation: add a recovery step early in `newMessageHandler` (before
`saveChatMessage`, since presence of the inbound message is itself proof of
accessibility). Gate it on the in-memory set so the steady-state cost for active chats is
an O(1) set lookup with zero DB I/O:

```python
# Inside MessagePreprocessorHandler.newMessageHandler, near the top:
chatId = ensuredMessage.recipient.id
if self.cache.isKnownInaccessible(chatId):
    # Inbound message in a chat we thought was dead → recover. Conditional UPDATE
    # only writes on a real transition; evict from the in-memory set regardless.
    if await self.cache.markChatActive(chatId):
        # status flipped in DB (INACCESSIBLE -> ACTIVE); set already evicted inside
        # markChatActive. Log at info for operability.
        logger.info(f"Chat {chatId} recovered to ACTIVE by inbound activity")
```

`CacheService` additions:

```python
def isKnownInaccessible(self, chatId: int) -> bool:
    """O(1) check against the in-memory known-inaccessible set. No DB I/O."""
    return chatId in self._inaccessibleChats

async def markChatActive(self, chatId: int) -> bool:
    """Recover ``chatId`` to ACTIVE: evict from the in-memory set + conditional UPDATE.

    Idempotent and write-light: the DB UPDATE is conditional on the current value being
    ``inaccessible``, so calling this on an already-active chat is a no-op write. The
    in-memory eviction is unconditional (cheap, and correct either way).
    """
    self._inaccessibleChats.discard(chatId)
    if self.database is not None:
        return await self.database.chatInfo.setChatBotStatus(chatId, ChatBotStatus.ACTIVE)
    return False
```

Why the conditional UPDATE rather than a read-then-write: it collapses the
"check-then-flip" into a single statement (`UPDATE chat_info SET bot_status = 'active'
WHERE chat_id = :chatId AND bot_status != 'active'`), eliminating a read and making the
transition naturally idempotent and race-free (concurrent recovery attempts both produce
`ACTIVE`; both report "no rows" except the first). The repository method's return value
("did the status actually change?") lets the caller log a real recovery vs. silently
no-op'ing.

### 5.2 Startup seed of the in-memory set

The recovery hook above (§5.1) is gated on the in-memory `_inaccessibleChats` set, so
for it to fire after a restart the set must reflect the DB at startup. Rather than add a
second recovery hook (the rejected option in §5.3), the set is seeded once from the DB
inside [`CacheService.injectDatabase`](../../internal/services/cache/service.py) at
[`internal/services/cache/service.py:390`](../../internal/services/cache/service.py),
which already runs once at bot startup
([`HandlersManager`](../../internal/bot/common/handlers/manager.py) →
`await self.cache.injectDatabase(self.db)` at
[`internal/bot/common/handlers/manager.py:721`](../../internal/bot/common/handlers/manager.py))
and already performs `await self.loadFromDatabase()`. The seed is one additional query
run at the same point:

```python
# Inside CacheService.injectDatabase, after self.database = database / loadFromDatabase():
if self.database is not None:
    rows = await self.database.chatInfo.getInactiveChatIds()  # SELECT chat_id FROM chat_info WHERE bot_status = 'inaccessible'
    self._inaccessibleChats.update(int(r["chat_id"]) for r in rows)
```

Repository method (`ChatInfoRepository.getInactiveChatIds`, new, read-only):

```python
async def getInactiveChatIds(self) -> List[Dict[str, int]]:
    """Return ``[{chat_id: int}, ...]`` for every chat currently ``INACCESSIBLE``.

    Used by ``CacheService.injectDatabase`` to seed the in-memory known-inaccessible
    set at startup so the preprocessor recovery hook (§5.1) works immediately after a
    restart. Read-only; aggregates across sources like the other chat-listing reads.
    """
    ...
```

Why this is correct and sufficient:

- After the seed, `_inaccessibleChats` mirrors the DB. The first inbound message in any
  seeded chat trips the §5.1 hook and recovers it (conditional `UPDATE … WHERE
  bot_status = 'inaccessible'` + set eviction). Convergence is immediate — one message,
  not up to 12 hours.
- The seed is bounded by the number of genuinely-inaccessible chats (small), runs once,
  and never runs again in the process lifetime. The set stays in sync thereafter via the
  failure path (§4.2 adds) and the recovery path (§5.1 discards).
- This is cache warm-up, **not** a recovery hook: it does not change any `bot_status`
  value, it only populates the non-authoritative in-memory mirror. Recovery itself stays
  pinned to the preprocessor exactly as binding decision 3 requires.

### 5.3 Why not a mark-on-success hook (alternative considered and rejected)

An earlier draft of this design added a second recovery hook ("Hook B") at the
`getChatAdmins` success path ([`bot.py:234`](../../internal/bot/common/bot.py)) that
unconditionally ran `markChatActive`. It was rejected for three reasons:

1. **It does not actually converge quickly.** A successful `getChatAdmins` only happens
   on a cache miss, and for groups the only regular cache-miss caller is `updateChatInfo`'s
   12-hourly refresh ([`base.py:967`](../../internal/bot/common/handlers/base.py):
   `needChange = timeDiff.total_seconds() > 60 * 60 * 12`). Post-restart, an
   `INACCESSIBLE` group whose `chat_info.updated_at` is fresh receives messages for up
   to 12 hours before `getChatAdmins` is called again — during which the chat-list filter
   (§7) hides it from `/configure` despite active traffic. For DMs Hook B never fires at
   all (no `getChatAdmins` on the DM path — see §8). The startup seed (§5.2) recovers on
   the very first inbound message instead.
2. **In the presence of the §6.2 short-circuit, Hook B is almost always a no-op.** The
   short-circuit returns `{}` for any chat in `_inaccessibleChats` before the API is
   reached, so a successful API call can only occur for chats **not** in the set — i.e.
   chats that are already `ACTIVE`. For those, the conditional
   `WHERE bot_status != 'active'` matches 0 rows. Hook B's only real effect was the
   post-restart window (set empty, DB `INACCESSIBLE`), and the seed (§5.2) closes that
   window without a second hook.
3. **Scope.** Hook B is a recovery path outside the preprocessor, i.e. a deviation from
   the literal "recovery = lazy via inbound activity in the preprocessor" wording of
   binding decision 3. The startup seed keeps recovery preprocessor-only (it is cache
   warm-up, not recovery), so the design stays inside the binding.

### 5.4 Interaction with `updateChatInfo` / `saveChatMessage`

Both the recovery hook and the routine refresh run on inbound messages. The ordering and
interactions are safe by construction:

- `MessagePreprocessorHandler.newMessageHandler` runs recovery (§5.1) **before**
  `saveChatMessage`/`updateChatInfo`. If recovery flips `INACCESSIBLE → ACTIVE`, the
  subsequent `updateChatInfo` upsert honours the non-clobber rule (§3.4) and does **not**
  touch `bot_status` — so the just-recovered `ACTIVE` value survives the refresh.
- `updateChatInfo` ([`base.py:975-976`](../../internal/bot/common/handlers/base.py))
  calls `getChatAdmins` for non-private chats during the 12-hourly refresh. By the time
  it runs, §5.1 has already run for this message, so any chat previously in the
  `_inaccessibleChats` set has already been evicted and (if the DB was `INACCESSIBLE`)
  flipped to `ACTIVE`. Thus the `getChatAdmins` call here either succeeds against an
  already-`ACTIVE` chat (a no-op — there is no mark-on-success hook by design, §5.3) or
  fails and triggers detection (§4.2). These compose correctly: a chat refreshed while
  the bot is present stays `ACTIVE`; one refreshed while the bot is gone is marked
  `INACCESSIBLE`.

### 5.5 DM-unblock is covered

Recovery via inbound activity (§5.1) is chat-type-agnostic: any inbound message in chat X
recovers X. A user unblocking the bot in a DM and then sending a message triggers the
preprocessor recovery exactly as a group-chat message does. The caveat is detection-side
(when does a DM get *marked* `INACCESSIBLE` in the first place) — see section 8.

---

## 6. In-Memory `CacheService` Short-Circuit

### 6.1 The known-inaccessible set

A `set[int]` of chat ids known to be `INACCESSIBLE` within the current process. Add it to
[`CacheService.__init__`](../../internal/services/cache/service.py) at
[`internal/services/cache/service.py:245`](../../internal/services/cache/service.py)
(alongside the existing namespace LRU caches, inside the `hasattr(self, "initialized")`
guard):

```python
# In-memory mirror of {chat_id : bot_status == INACCESSIBLE}. Pure optimization — the
# DB column is the source of truth. Seeded from the DB at startup (CacheService.injectDatabase,
# §5.2) and thereafter kept in sync: added by getChatAdmins failures (§4.2), discarded by
# the preprocessor recovery (§5.1). Used to short-circuit getChatAdmins/isAdmin for chats
# already known dead this process, avoiding repeated redundant API+DB work.
self._inaccessibleChats: set[int] = set()
```

Why a plain `set[int]` and not an LRU/TTL dict: membership is all that is needed; the set
is bounded by the number of genuinely-inaccessible chats (small), and eviction happens
explicitly on recovery (`markChatActive`). A TTL is not required because the set is
non-authoritative (the DB is) — see section 6.4 and section 12 (open question on TTL).

### 6.2 Contract: how `getChatAdmins`/`isAdmin` consult it

Decision: **`getChatAdmins` short-circuits to `{}` for known-inaccessible chats**, not
`isAdmin` short-circuiting to `False`. Rationale:

- `isAdmin` ([`TheBot.isAdmin`](../../internal/bot/common/bot.py) at
  [`internal/bot/common/bot.py:237`](../../internal/bot/common/bot.py)) delegates to
  `getChatAdmins` ([L276-277](../../internal/bot/common/bot.py): `chatAdmins = await
  self.getChatAdmins(chat=chat); return user.id in chatAdmins`). Short-circuiting
  `getChatAdmins` to `{}` makes `isAdmin` naturally return `False` — identical to the
  existing graceful-degradation behaviour where a failed probe returns `{}` and
  `isAdmin` returns `False`.
- This keeps a single chokepoint (`getChatAdmins`) and avoids duplicating the
  short-circuit logic in `isAdmin`'s owner/private/fast-paths.

Implementation: at the top of
[`TheBot.getChatAdmins`](../../internal/bot/common/bot.py), immediately after the
existing cache check (or before it — order does not matter since a chat is never both
cached-admins and in the inaccessible set), add:

```python
# Short-circuit: if this process already knows the bot is inaccessible here, do not
# hit the DB or the platform API. Returns the same {} the failure path would, so
# callers (isAdmin, chat-list builders) degrade identically. Recovery (§5) evicts.
if self.cache.isKnownInaccessible(chat.id):
    return {}
```

This is the "zero DB and zero API cost" short-circuit the binding asks for: a known-dead
chat provokes no probe within the process until it recovers.

### 6.3 Population and eviction

| Event | Effect on `_inaccessibleChats` | Effect on DB `bot_status` |
|---|---|---|
| Process startup — `CacheService.injectDatabase` (§5.2) | **seed** = every chat the DB has as `INACCESSIBLE` | none (read-only warm-up) |
| `getChatAdmins` failure (§4.2) | **add** chatId | `INACCESSIBLE` (conditional) |
| Inbound message in chat, chat in set (§5.1) | **discard** chatId | `ACTIVE` (conditional) |

After the startup seed the set mirrors the DB and is kept in sync by exactly two
in-process events: a probe failure adds a chat (and writes `INACCESSIBLE`), the
preprocessor recovery discards a chat (and writes `ACTIVE`). There are no platform events
(binding decision 3), so no event handler ever touches the set. The startup seed is the
only "bulk" population; the failure path is the only per-event population.

### 6.4 Restart semantics

After a restart, `injectDatabase` (§5.2) seeds `_inaccessibleChats` from the DB before
the bot accepts its first message. Consequences:

- The `getChatAdmins` short-circuit (§6.2) is correct from the first request: a chat the
  DB has as `INACCESSIBLE` is in the set, so it short-circuits to `{}` with **zero** API
  calls this process (no "first redundant probe" tax — the seed removes even that).
- Recovery is immediate: the first inbound message in a seeded chat trips the §5.1 hook
  and flips it back to `ACTIVE` (conditional UPDATE + set eviction). One message, not up
  to 12 hours.
- The **chat-list filter** (section 7) reads the DB column directly and is therefore
  correct immediately regardless of the set state. This is the meaning of "DB is the
  source of truth": user-facing correctness does not depend on the in-memory set, only
  the optimization does. The seed simply makes the optimization correct from t=0 too.

One edge: if the bot process is restarted while a chat is `INACCESSIBLE` in the DB but
the bot has in fact been re-added out-of-band (no event arrives — binding decision 3),
that chat stays in the seeded set (and thus short-circuited) until the next inbound
message recovers it via §5.1. This is the intended trade-off of an activity-based
recovery model with no event source, and it is self-healing on the next message.

---

## 7. Consumer Changes / Chat-List Filter

### 7.1 Filter shape

The filter is a SQL predicate applied at the **repository layer**, threaded up through
the handler wrapper as an optional param:

- **Default (`botStatus = ChatBotStatus.ACTIVE`):** `AND bot_status = :botStatus` is
  appended to the chat-list query → only accessible chats returned. This is the
  behaviour every existing consumer gets without changing its call site, satisfying
  "skip `INACCESSIBLE` by default".
- **All chats (`botStatus = None`):** no predicate is appended → `INACCESSIBLE` chats
  included. Use this for any future diagnostic/owner path that wants the full list.

Because the existing queries already `SELECT ci.* FROM chat_info ci …`, the predicate
`ci.bot_status = :botStatus` (qualified with the `ci` alias already used in
[`chat_users.py:296`](../../internal/database/repositories/chat_users.py) and
[`chat_users.py:340`](../../internal/database/repositories/chat_users.py)) drops in
without restructuring.

### 7.2 Repository methods to change

Both live in [`internal/database/repositories/chat_users.py`](../../internal/database/repositories/chat_users.py).

**1. `getUserChats`** — [`chat_users.py:271`](../../internal/database/repositories/chat_users.py)

Current:

```python
async def getUserChats(self, userId: int, *, dataSource: Optional[str] = None) -> List[ChatInfoDict]:
```

Proposed:

```python
async def getUserChats(
    self,
    userId: int,
    *,
    dataSource: Optional[str] = None,
    botStatus: Optional[ChatBotStatus] = ChatBotStatus.ACTIVE,
) -> List[ChatInfoDict]:
```

SQL change: append `AND (:botStatus IS NULL OR ci.bot_status = :botStatus)` — the
portable "optional predicate" shape (works across SQLite/PG/MySQL without dynamic SQL),
bound with `{"userId": userId, "botStatus": botStatus.value if botStatus else None}`.
The clause order (`:param IS NULL OR …`) deliberately mirrors the existing
`(:seenSince IS NULL OR updated_at > :seenSince)` pattern already used at
[`chat_users.py:250`](../../internal/database/repositories/chat_users.py) for parity, and
the column is qualified `ci.bot_status` because the `ci` alias is already in use in this
query. (Building the SQL string with/without the clause in Python is also acceptable;
the `OR :param IS NULL` form is preferred here because it avoids string-building.)

**2. `getAllGroupChats`** — [`chat_users.py:318`](../../internal/database/repositories/chat_users.py)

Current:

```python
async def getAllGroupChats(self, *, dataSource: Optional[str] = None) -> List[ChatInfoDict]:
```

Proposed:

```python
async def getAllGroupChats(
    self,
    *,
    dataSource: Optional[str] = None,
    botStatus: Optional[ChatBotStatus] = ChatBotStatus.ACTIVE,
) -> List[ChatInfoDict]:
```

Same predicate pattern, same order (`AND (:botStatus IS NULL OR ci.bot_status = :botStatus)`),
qualified with the `ci` alias already used in this query for consistency with `getUserChats`.

### 7.3 Handler wrapper to change

**`BaseBotHandler.getUserChats`** — [`internal/bot/common/handlers/base.py:1290`](../../internal/bot/common/handlers/base.py)

Current:

```python
async def getUserChats(self, userId: int) -> List[ChatInfoDict]:
```

Proposed (thread the param through; keep the existing `leftChat` metadata filter):

```python
async def getUserChats(
    self,
    userId: int,
    *,
    botStatus: Optional[ChatBotStatus] = ChatBotStatus.ACTIVE,
) -> List[ChatInfoDict]:
```

Body passes `botStatus=botStatus` into `self.db.chatUsers.getUserChats(userId,
botStatus=botStatus)` at [`base.py:1303`](../../internal/bot/common/handlers/base.py).
The existing per-user `leftChat` metadata filter ([`base.py:1310-1313`](../../internal/bot/common/handlers/base.py))
is orthogonal and stays.

### 7.4 Consumer call sites (enumerated)

Every site below currently calls one of the two chat-listing paths. With the wrapper /
repo default flipped to ACTIVE-only, **all of the chat-picker sites get the desired
behaviour for free** (no call-site edit). The single call-site edit is the bot-owner
`/list_chats all` branch, which passes `botStatus=None` for the diagnostic reason in the
note below.

**Via the handler wrapper `BaseBotHandler.getUserChats` (default becomes ACTIVE-only):**

| File | Line | Consumer | Action |
|---|---|---|---|
| [`internal/bot/common/handlers/configure.py`](../../internal/bot/common/handlers/configure.py) | [191](../../internal/bot/common/handlers/configure.py) | `chatConfiguration_Init` (`/configure`) | No call-site change; inherits ACTIVE-only default. This is the crash motivation (§1). |
| [`internal/bot/common/handlers/topic_manager.py`](../../internal/bot/common/handlers/topic_manager.py) | [112](../../internal/bot/common/handlers/topic_manager.py) | topic-manager chat picker | No call-site change; inherits default. |
| [`internal/bot/common/handlers/summarization.py`](../../internal/bot/common/handlers/summarization.py) | [381](../../internal/bot/common/handlers/summarization.py) | summarization chat picker | No call-site change; inherits default. |
| [`internal/bot/common/handlers/user_memories.py`](../../internal/bot/common/handlers/user_memories.py) | [1648](../../internal/bot/common/handlers/user_memories.py) | user-memory chat picker | No call-site change; inherits default. |
| [`internal/bot/common/handlers/common.py`](../../internal/bot/common/handlers/common.py) | [416](../../internal/bot/common/handlers/common.py) | `/list_chats` (non-`all` branch) | No call-site change; inherits default. |

**Via the repo `getAllGroupChats` directly:**

| File | Line | Consumer | Action |
|---|---|---|---|
| [`internal/bot/common/handlers/common.py`](../../internal/bot/common/handlers/common.py) | [416](../../internal/bot/common/handlers/common.py) | `/list_chats` (`listAll`/bot-owner branch) | **Pass `botStatus=None`** (see note below the table). This branch is already gated `if listAll: listAll = self.isBotOwner(...)` at [`common.py:412-413`](../../internal/bot/common/handlers/common.py), so it is bot-owner-only; the owner's `all` flag is the one user-facing signal that means "show me everything, including chats I was kicked from". |
| [`internal/bot/common/handlers/spam.py`](../../internal/bot/common/handlers/spam.py) | [1134](../../internal/bot/common/handlers/spam.py) | spam-stats scan (bot-owner) | Inherits default (ACTIVE-only). Stats for dead groups are not actionable; if an owner ever wants them, pass `botStatus=None`. |

**Owner-visibility note.** The default-ACTIVE filter is correct for every user-facing
chat *picker* (`/configure`, topic-manager, summarization, user-memories, and the
non-`all` `/list_chats` branch) — those exist to let the user act on a chat the bot can
reach, so hiding inaccessible ones is the goal. The single exception is the bot-owner
`/list_chats all` branch, whose entire purpose is diagnostics ("which chats does the bot
know about?"). Letting it inherit ACTIVE-only would hide exactly the chats the owner most
wants to see — the ones the bot was kicked from. Passing `botStatus=None` on that one
branch uses the escape hatch binding decision 4 explicitly provides (`None` = all chats),
so this is **not** a binding conflict. (`spam.py:1134` is also bot-owner-only, but its
purpose is actionable stats, so default-ACTIVE is the right call there.)

**No change required:**

- [`internal/bot/common/handlers/dev_commands.py`](../../internal/bot/common/handlers/dev_commands.py) — has no chat-listing method.
  `/get_admins` uses `isAdmin` (not a listing) and is unaffected (it targets a single
  chat id).

### 7.5 Tests touched by the filter

The two repo tests that currently call `getUserChats` / `getAllGroupChats` with default
args must stay green: the default flips to ACTIVE-only, and their seeded chats will be
ACTIVE (column default), so they return as before. New tests for the `None` (all) and
explicit-`INACCESSIBLE` paths are added (section 10).

- [`tests/integration/test_database_operations.py:1119,1127`](../../tests/integration/test_database_operations.py)
- [`tests/database/test_db_wrapper.py:668,682`](../../tests/database/test_db_wrapper.py)
- [`tests/database/repositories/test_chat_users.py:225-252`](../../tests/database/repositories/test_chat_users.py)

---

## 8. Edge Cases

- **Private chats (DM block/unblock) — detection is dormant in current code paths.** A
  DM can only be marked `INACCESSIBLE` by the `getChatAdmins` failure path, but **no
  normal code path calls `getChatAdmins` on a private chat**: the inbound refresh path
  skips it ([`base.py:975`](../../internal/bot/common/handlers/base.py):
  `if message.recipient.chatType != ChatType.PRIVATE`), and `isAdmin` short-circuits
  private chats to `True` without ever calling `getChatAdmins`
  ([`bot.py:268-269`](../../internal/bot/common/bot.py)). A DM is therefore probed only
  by an explicit out-of-band call (e.g. a `/get_admins`-style dev command pointed at a
  private chat). **Net effect for binding decision 5d: the tracking *infrastructure*
  (column, enum, `setChatBotStatus`, mark-on-failure) is fully functional for DMs and
  will mark a DM `INACCESSIBLE` the moment any probe fails, but no current flow triggers
  such a probe — so in practice DMs are never marked `INACCESSIBLE` and there is nothing
  to recover.** This is honest about 5d's practical effect: it is forward-compatible
  coverage, not active detection today. Adding a DM probe (e.g. probing on first DM
  contact) is deliberately out of scope — it would expand the detection surface beyond
  the `getChatAdmins` catch sites pinned by binding decision 2. Recovery itself is
  chat-type-agnostic and works for DMs: any inbound DM message recovers the chat (§5.1) —
  but, per above, a DM has to have been marked first. **No change to the private-chat
  skip in `updateChatInfo`** — that would be a behaviour change beyond this phase's scope.

- **Chats with no inbound activity yet.** A chat row is inserted by `updateChatInfo` with
  `bot_status = 'active'` (column default). It has never been probed, so the optimistic
  default is correct — it appears in chat lists until a probe fails. There is no
  "unprobed" state; `ACTIVE` is exactly "assumed present".

- **Conditional-write race.** Both `setChatBotStatus` writes are conditional
  (`WHERE bot_status != :status`) and idempotent. Concurrent recovery attempts for the
  same chat both converge on `ACTIVE`; concurrent failure markings converge on
  `INACCESSIBLE`. A recovery and a failure racing is resolved by last-writer-wins on the
  row, which is acceptable: the next probe reconciles it. No locking required.

- **Restart behaviour.** `CacheService.injectDatabase` seeds `_inaccessibleChats` from
  the DB before the first message is processed (§5.2 / §6.4), so the in-memory set
  matches the DB from t=0. The chat-list filter (which reads the DB column) is correct
  immediately; the `getChatAdmins` short-circuit (§6.2) is also correct immediately — a
  dead chat provokes zero API calls this process, and the first inbound message in a
  recoverable chat flips it back to `ACTIVE` via §5.1.

- **Chat deleted/never-existed mid-probe.** Telegram `BadRequest("chat not found")` and
  Max `NotFoundError` are the existing catch arms; they mark `INACCESSIBLE`. If the chat
  row did not yet exist in `chat_info` (never inserted), `setChatBotStatus`'s
  conditional UPDATE matches 0 rows (returns `False`) — no spurious row is created. The
  chat will be inserted with the default `ACTIVE` status by the normal `updateChatInfo`
  path the next time it is seen.

- **Migration on a non-empty DB.** `ADD COLUMN … DEFAULT 'active'` backfills every
  existing `chat_info` row to `ACTIVE` as part of the `ALTER` (portable across
  SQLite/PG/MySQL). No separate backfill statement, no app-level migration step.

---

## 9. Implementation Phases (within this single feature)

Each sub-phase is a reviewable unit for the `software-developer` agent (≤~60 steps). Run
`make format lint` before and after each phase and `make test` after each phase that
touches code (per AGENTS.md and the `run-quality-gates` skill). No phase introduces event
wiring, `QueueService`/`delayed_tasks` changes, or an owner command.

### P1 — Migration + enum + `ChatInfoDict`
- Files:
  - New: `internal/database/migrations/versions/migration_026_chat_accessibility_bot_status.py`
  - Edit: `internal/database/models.py` (add `ChatBotStatus`; add `bot_status: NotRequired[ChatBotStatus]` to `ChatInfoDict`; import `NotRequired` already present).
- Signatures: `class ChatBotStatus(StrEnum): ACTIVE="active"; INACCESSIBLE="inaccessible"`; `Migration026ChatAccessibilityBotStatus(BaseMigration)` with `version=26`, `up`, `down`, `getMigration`.
- Acceptance:
  - `make test` green; a new repo test confirms `chat_info.bot_status` exists and defaults to `'active'` on a fresh `testDatabase`.
  - Existing `ChatInfoDict` consumers still type-check under pyright (`NotRequired` keeps the platform-sourced dicts valid).

### P2 — Repository layer (status methods + chat-list filter param)
- Files:
  - `internal/database/repositories/chat_info.py`: add `setChatBotStatus(chatId, status) -> bool` (conditional UPDATE); add `getInactiveChatIds() -> List[Dict[str, int]]` (read-only, used by the startup seed in §5.2).
  - `internal/database/repositories/chat_users.py`: add `botStatus` kwarg (default `ChatBotStatus.ACTIVE`) to `getUserChats` and `getAllGroupChats`; add the `AND (:botStatus IS NULL OR ci.bot_status = :botStatus)` predicate.
  - **Verify** `ChatInfoRepository.updateChatInfo` ([`chat_info.py:42`](../../internal/database/repositories/chat_info.py)) does **not** list `bot_status` in `values` or `updateExpressions` (non-clobber rule, §3.4 — proof at §3.4). Add a regression test that an `updateChatInfo` refresh does not reset a chat marked `INACCESSIBLE`.
- Signatures: as in §7.2 and §4.2.
- Acceptance:
  - Repo tests: default call excludes `INACCESSIBLE` chats; `botStatus=None` includes them; explicit `ChatBotStatus.INACCESSIBLE` returns only those.
  - Existing `getUserChats`/`getAllGroupChats` tests stay green (their seeded chats are ACTIVE).

### P3 — Lazy mark-on-failure + in-memory set + startup seed (CacheService)
- Files:
  - `internal/services/cache/service.py`: add `self._inaccessibleChats: set[int]` in `__init__`; add `isKnownInaccessible`, `markChatInaccessible`, `markChatActive`; seed the set inside `injectDatabase` via `await self.database.chatInfo.getInactiveChatIds()` (§5.2).
  - `internal/bot/common/bot.py`: in `getChatAdmins`, add the short-circuit at the top (§6.2) and the `markChatInaccessible` call at the three failure catch sites (§4.2). **The success path ([`bot.py:234-235`](../../internal/bot/common/bot.py)) is unchanged** — there is no mark-on-success hook by design (§5.3).
- Signatures: as in §4.2, §5.1, §5.2, §6.1.
- Acceptance:
  - New test: a `Forbidden`/`NotFoundError` probe writes `INACCESSIBLE` to the DB, adds the chat to `_inaccessibleChats`, and `getChatAdmins` returns `{}`. A subsequent `getChatAdmins` for the same chat short-circuits without a second API call.
  - New test (startup seed): a `CacheService` whose DB has one `INACCESSIBLE` chat and zero prior failures populates `_inaccessibleChats` during `injectDatabase`; the short-circuit (§6.2) then fires for that chat on the very first `getChatAdmins` call.
  - Singleton reset (`_instance`/`initialized` guard) in the test fixture (per `tests/conftest.py` conventions; `CacheService` uses the `hasattr(self, "initialized")` guard at [`service.py:254`](../../internal/services/cache/service.py)).

### P4 — Activity-based recovery in the preprocessor
- Files:
  - `internal/bot/common/handlers/message_preprocessor.py`: add the recovery step at the top of `newMessageHandler` (§5.1).
- Signatures: none new (uses `cache.isKnownInaccessible` + `cache.markChatActive`).
- Acceptance:
  - New test: a chat in `_inaccessibleChats` receiving an inbound message is flipped to `ACTIVE` in the DB and evicted from the set; a chat **not** in the set triggers no DB write (assert `setChatBotStatus` not called / 0 rows).
  - Recovery covers a private-chat (DM) message (chat-type-agnostic).

### P5 — Consumer wiring (filter applied to all chat-list paths)
- Files:
  - `internal/bot/common/handlers/base.py`: add `botStatus` kwarg (default `ACTIVE`) to `BaseBotHandler.getUserChats` and thread into the repo call.
  - `internal/bot/common/handlers/common.py`: on the bot-owner `/list_chats all` branch ([`common.py:415-417`](../../internal/bot/common/handlers/common.py)), pass `botStatus=None` to `getAllGroupChats` so the owner sees inaccessible chats (§7.4 owner-visibility note). All other call sites are untouched.
- Signatures: as in §7.3.
- Acceptance:
  - The five handler-wrapper consumers (`configure.py:191`, `topic_manager.py:112`, `summarization.py:381`, `user_memories.py:1648`, `common.py:416` non-`all` branch) and the spam repo-direct consumer (`spam.py:1134`) now exclude `INACCESSIBLE` chats by default with **no call-site edits** (verified by grep: no call passes `botStatus=`).
  - The bot-owner `/list_chats all` branch passes `botStatus=None` (the one deliberate edit).
  - New test: `/configure` (`chatConfiguration_Init`) with one ACTIVE and one INACCESSIBLE chat yields a keyboard listing only the ACTIVE chat.
  - New test: `/list_chats all` issued by a bot owner with one ACTIVE and one INACCESSIBLE chat lists **both**; a non-owner `/list_chats` (non-`all`) lists only the ACTIVE chat.

### P6 — Tests + docs sync
- Tests: complete the test plan (section 10); ensure singleton resets and the `tests/` mirror layout (`internal/X/Y.py` → `tests/X/test_Y.py`).
- Docs: see section 11. Load the `update-project-docs` skill and run the decision matrix.
- `CHANGELOG.md`: one-line `Added` entry under `## [Unreleased]`.
- Acceptance: `make format lint` and `make test` green; `make check-docs` green.

---

## 10. Test Plan

Conventions (AGENTS.md / [`docs/llm/testing.md`](../llm/testing.md)):

- All tests under `tests/`, mirroring source (`internal/database/repositories/chat_info.py` → `tests/database/repositories/test_chat_info.py`; `internal/bot/common/handlers/message_preprocessor.py` → `tests/bot/common/handlers/test_message_preprocessor.py`). No collocated tests.
- `async def test_…` with no decorator (`asyncio_mode = "auto"`).
- Reuse `tests/conftest.py` fixtures: `testDatabase` (fresh in-memory SQLite, all migrations applied — so migration 026 is exercised implicitly), `mockBot`, `mockConfigManager`. Reset `CacheService` singleton state between tests (the autouse reset / `hasattr(self, "initialized")` guard).
- Complete-`chatSettings` dicts when mocking handler paths (production subscripts `chatSettings[KEY]` directly, never `.get()`).

Cases (regression + new):

1. **Migration 026 / default (P1).** `testDatabase` `chat_info` rows have `bot_status = 'active'` by default; `ChatBotStatus.ACTIVE == "active"` and serializes as `"active"`.
2. **`setChatBotStatus` conditional (P2).** Marking a chat `INACCESSIBLE` flips the column; marking an already-`INACCESSIBLE` chat `INACCESSIBLE` again returns `False` / affects 0 rows; marking `ACTIVE` on an `INACCESSIBLE` chat flips it and returns `True`.
3. **`updateChatInfo` non-clobber (P2, CRITICAL regression).** Mark a chat `INACCESSIBLE`; call `ChatInfoRepository.updateChatInfo(...)` (the routine refresh upsert); assert `bot_status` is still `INACCESSIBLE`. This is the test that pins the §3.4 rule.
4. **Chat-list filter (P2).** Seed two chats, one `ACTIVE` one `INACCESSIBLE`, both with a `chat_users` row for the same user. `getUserChats(userId)` returns only the ACTIVE chat; `getUserChats(userId, botStatus=None)` returns both; `getUserChats(userId, botStatus=ChatBotStatus.INACCESSIBLE)` returns only the inaccessible one. Repeat the three cases for `getAllGroupChats`.
5. **Mark-on-failure (P3).** Stub `tgBot.get_chat_administrators` to raise `telegram.error.Forbidden`; call `TheBot.getChatAdmins(chat)`; assert it returns `{}`, the chat is in `_inaccessibleChats`, and the DB row is `INACCESSIBLE`. Repeat with `telegram.error.BadRequest("chat not found")`; assert a non-access `BadRequest` (e.g. `"bad request"`) is **re-raised** (existing behaviour preserved). Repeat for Max with `maxExceptions.NotFoundError`.
6. **In-memory short-circuit (P3).** After case 5, a second `getChatAdmins` call for the same chat returns `{}` and does **not** invoke the platform API again (assert the mock was called exactly once across both calls).
7. **Startup seed (P3, replaces the rejected mark-on-success hook).** Seed one chat `INACCESSIBLE` in the DB; construct a fresh `CacheService` (set empty) and call `injectDatabase(testDatabase)`; assert `_inaccessibleChats` now contains that chat id with **no** prior failure having occurred. Then assert the §6.2 short-circuit fires for that chat on the first `getChatAdmins` call (mock API not invoked). A `getChatAdmins` for a chat **not** in the DB-INACCESSIBLE set is unaffected (proceeds to cache/API as before).
8. **Recovery in preprocessor (P4).** A chat in `_inaccessibleChats` receives an inbound message; after `newMessageHandler`, the chat is `ACTIVE` in the DB and evicted from the set. A chat **not** in the set receiving a message triggers **no** `setChatBotStatus` call (write-frequency guarantee).
9. **DM recovery (P4).** Same as case 8 but the inbound message is in a `ChatType.PRIVATE` chat — recovery still fires (chat-type-agnostic). (Note: per §8, DMs are not *marked* `INACCESSIBLE` by any current flow, so this test must seed the DM into `_inaccessibleChats` manually to exercise the recovery path.)
10. **`/configure` excludes inaccessible (P5).** `chatConfiguration_Init` with one ACTIVE and one INACCESSIBLE chat (both owned/administered by the user) builds a keyboard listing only the ACTIVE chat. Directly addresses the §1 motivation.
11. **`/list_chats` owner-vs-user split (P5).** A bot owner issuing `/list_chats all` with one ACTIVE and one INACCESSIBLE chat sees **both** (the `listAll` branch passes `botStatus=None`, §7.4). A non-owner `/list_chats` (non-`all`) for the same data sees only the ACTIVE chat.
12. **Restart round-trip (P3, optional/`slow`).** With one chat DB-`INACCESSIBLE`: (a) after `injectDatabase`, the chat is in `_inaccessibleChats` and `getChatAdmins` short-circuits with zero API calls; (b) the chat-list filter excludes it (DB authoritative); (c) deliver one inbound message in that chat and assert §5.1 flips the DB to `ACTIVE`, evicts the chat from the set, and the next `getChatAdmins` call proceeds to the API (short-circuit no longer fires).

---

## 11. Docs Impact (to sync when implemented)

Enumerated only — no edits in this phase. Load the `update-project-docs` skill and apply
its decision matrix during P6.

| Doc | Change |
|---|---|
| [`docs/database-schema.md`](../database-schema.md) | Add `bot_status` column to the `chat_info` table section (around [`docs/database-schema.md:308`](../database-schema.md)); document the `'active'` default and the index. |
| [`docs/database-schema-llm.md`](../database-schema-llm.md) | Mirror the `chat_info` column addition (around [`docs/database-schema-llm.md:87`](../database-schema-llm.md); keep the two schema docs in sync). |
| [`docs/llm/database.md`](../llm/database.md) | New column + the non-clobber ownership rule for `updateChatInfo`; new `setChatBotStatus` repo method; `botStatus` filter param on the chat-list queries. |
| [`docs/llm/handlers.md`](../llm/handlers.md) | Note the recovery hook in `MessagePreprocessorHandler.newMessageHandler`; note the `getChatAdmins` short-circuit and mark-on-failure (no mark-on-success — §5.3); note the `botStatus` param on `BaseBotHandler.getUserChats`, the `botStatus=None` pass-through on the owner `/list_chats all` branch (§7.4), and that the other chat-list consumers exclude `INACCESSIBLE` by default. |
| [`docs/llm/services.md`](../llm/services.md) | Document the `CacheService` `_inaccessibleChats` set: `isKnownInaccessible` / `markChatInaccessible` / `markChatActive`, the startup seed in `injectDatabase` (§5.2), the short-circuit contract, and restart semantics. |
| [`CHANGELOG.md`](../../CHANGELOG.md) | One-line `Added` entry under `## [Unreleased]`: chat accessibility tracking (`chat_info.bot_status`, lazy mark-on-failure, activity-based recovery, chat-list filter, in-memory short-circuit). |

(Architecture-level shift is small and contained; no `docs/llm/architecture.md` / `index.md`
change is strictly required, but a one-line note in `architecture.md`'s bot-core section
referencing this design doc is a nice-to-have.)

---

## 12. Open Questions / Risks

- **Should `_inaccessibleChats` have a TTL?** Currently it has none — eviction is purely
  on recovery. Since the set is non-authoritative (DB is source of truth) and bounded by
  the number of genuinely-dead chats, a TTL is not required for correctness. A long TTL
  (e.g. 24h) could bound memory in a pathological deployment with many ephemeral chats,
  but that is not a realistic concern for this bot. **Recommendation: ship without a TTL
  in this phase; revisit if the set grows unexpectedly.**

- **Should `getChatInfo` (the platform metadata probe at
  [`bot.py:1122`](../../internal/bot/common/bot.py)) also be a detection hook?** Binding
  decision 2 pins detection to `getChatAdmins` only. `getChatInfo` is called on the
  12-hourly refresh path
  ([`base.py:970`](../../internal/bot/common/handlers/base.py)); if it failed for an
  inaccessible chat it could be a second detection signal. **Decision for this phase: no.**
  `getChatInfo` does not currently catch inaccessibility-class exceptions, adding catch
  sites there expands scope and risks over-marking. Revisit if `getChatAdmins`-only
  detection proves too narrow in practice (e.g. channels where the bot is admin but
  cannot list administrators).

- **Stale `INACCESSIBLE` for private chats after restart.** In current code paths DMs are
  never *marked* `INACCESSIBLE` in the first place (§8: no normal flow calls
  `getChatAdmins` on a private chat), so this scenario does not arise in practice. If a
  future phase adds a DM probe that does mark one, the startup seed (§5.2) would load it
  into `_inaccessibleChats` at the next restart and the next inbound DM would recover it
  via §5.1. Recovery is therefore eventual (one message), consistent with the
  activity-based model in binding decision 3. No action this phase.
- **Mark-on-success recovery hook (resolved — rejected).** An earlier draft added a
  second recovery hook at the `getChatAdmins` success path. It was evaluated and rejected
  in favour of the startup seed; see §5.3 for the three reasons (slow convergence,
  no-op-in-the-presence-of-the-short-circuit, and scope drift beyond binding decision 3).

- **`OR :param IS NULL` vs. dynamic SQL for the optional filter.** The `OR :param IS NULL`
  form is chosen for parity with the existing `(:seenSince IS NULL OR …)` pattern in
  [`chat_users.py:250`](../../internal/database/repositories/chat_users.py). It is
  portable across SQLite/PG/MySQL. The minor downside is that the optimizer sees the
  predicate on every call; the `idx_chat_info_bot_status` index (§3.2) keeps the ACTIVE
  default fast. No action.

---

*Implementation hand-off: dispatch phases P1–P6 to `software-developer`. P6 loads the
`update-project-docs` skill for the documentation sync. This design doc itself is not
edited during implementation except by the implementer to record any deviation from the
binding decisions (there should be none).*
