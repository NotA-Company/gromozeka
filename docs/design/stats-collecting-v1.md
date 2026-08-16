# Design: Statistics collection v1 — messages, tool calls, commands

**Date**: 2026-08-14
**Status**: **IMPLEMENTED — all phases landed.** Phase 4 implemented (commit `b61c67aa` — both-direction `message` events, direction via sender identity, `sent`/`message_category` labels). Phase 3 implemented (commit `92040759` — `command` events via `HandlersManager.handleCommand`, gated on `[stats] enabled`). Phase 2 implemented (commit `ed378378` + fix `0fea86b6` — `llm_tool_call` events via `LLMService.injectStatsStorage`, gated on `[stats] enabled`). Phase 1 implemented (commits `46cac39f` + `f885702b` — `message` events + migration 027 back-fill/drop, gated on `[stats] enabled`). Remaining deferred items (next design): aggregation trigger, retention, query API, display. The body below is the original design rationale and is preserved as-is.

**Caveats (post-implementation):** (a) a handler timed out by the manager's `wait_for` records no `command` event (CancelledError bypasses the except; accepted best-effort undercount); (b) denied/not-found commands record no events of any kind (saveChatMessage is post-gate) — command-origin message ⊇ command, minus denials; (c) label naming is mixed camelCase/snake_case across events (pre-existing; harmonizing would split labels_hash buckets — do not change).

**Owner**: TBD
**Branch**: `lib-stat-improvement`
**Scope**: Extend Gromozeka's `lib/stats` event pipeline to three new bot-level event
types (`message_received`, `llm_tool_call`, `command`), retire two write-only legacy
counter tables (`chat_stats`, `chat_user_stats`) by back-filling their history into the
`stat_aggregates` table, and gate every new recording behind the existing
`[stats] enabled` flag so that **stats-off behavior is byte-identical to today**.

> This is a **design document**, not an implementation. Every `file:line` reference
> cited for a NEW claim was verified against source on 2026-08-14. The "Verified
> facts" supplied in the task brief are treated as given and reused where cited.
> Code sketches are illustrative and follow the repo's `camelCase` convention
> (`AGENTS.md`). SQL sketches follow the SQL-portability rules
> ([`docs/sql-portability-guide.md`](../sql-portability-guide.md), `AGENTS.md`
> "SQL portability").

---

## 1. Context and goal

Gromozeka already has a working statistics pipeline:

- An abstract [`StatsStorage`](../../lib/stats/stats_storage.py) with a no-op
  `NullStatsStorage`, and a database-backed
  [`DatabaseStatsStorage`](../../internal/database/stats_storage.py) that appends raw
  events to `stat_events` and rolls them up into `stat_aggregates`
  (hourly/daily/monthly/`total` periods, per-consumer + `__global__` rollup).
- Two consumers wired today: `llm_request`
  ([`lib/ai/abstract.py`](../../lib/ai/abstract.py), generation + embeddings) and
  `stt_request` ([`lib/stt/abstract.py:264`](../../lib/stt/abstract.py) `_recordStats`).
  Construction lives in [`main.py`](../../main.py):89-119, gated on
  `configManager.getStatsConfig().get("enabled", False)`.
- Two legacy per-day message-counter tables — `chat_stats` and `chat_user_stats` —
  written on every inbound message by
  [`ChatMessagesRepository.saveChatMessage`](../../internal/database/repositories/chat_messages.py)
  but with **zero readers anywhere in the tree** (verified — write-only since
  `migration_001`). They are a strict subset of what `stat_aggregates` will hold once
  `message_received` events flow.

**Goal in one paragraph:** route three new event streams into the existing pipeline,
preserve the historical message counts by back-filling `chat_user_stats` into
`stat_aggregates` as part of the same migration that drops the legacy tables, and do it
in three independently-shippable phases (one per event type) so each lands as a small,
reviewable commit. STT needs no work — it is already wired.

### 1.1 Goals

- **G1** — Record a `message_received` event exactly once per inbound message
  (commands and regular messages alike), with `message_count`, `text_length`, and
  `user_id` / `chat_type` / `message_type` labels.
- **G2** — Record an `llm_tool_call` event for every tool dispatch through the single
  centralized site in `LLMService`, with `tool_call_count`, `elapsed_time`, `is_error`,
  and `user_id` / `toolName` labels.
- **G3** — Record a `command` event for every executed slash command through the single
  `HandlersManager.handleCommand` choke point, with `command_count`, `is_error`, and
  `user_id` / `commandName` labels.
- **G4** — Drop `chat_stats` and `chat_user_stats`; back-fill all historical
  `chat_user_stats` rows into `stat_aggregates` as pre-aggregated `message_received`
  data so no history is lost.
- **G5** — Zero behavior change when `[stats] enabled = false` (the default): every new
  recording path holds a `NullStatsStorage` and emits nothing.

### 1.2 Non-goals (explicitly deferred — see §11 Future work)

- **NG1** — No aggregation trigger yet. Wiring a periodic `aggregate()` caller
  (scheduler task / startup loop) is a separate concern.
- **NG2** — No retention/cleanup of processed `stat_events` rows.
- **NG3** — No query/read API and no user-facing display of stats.
- **NG4** — No true cross-user global totals. The current `__global__` rollup replaces
  only the `consumer` label and keeps `user_id`; cross-user rollup is a future
  post-query SUM or a stripped-labels rollup pass.
- **NG5** — No rework of the `claim → upsert → mark-processed` non-atomicity in
  `DatabaseStatsStorage.aggregate` (accepted gap, see §9).

---

## 2. Verified grounding (current state)

Facts verified against source on 2026-08-14. Line numbers are current as of branch
`lib-stat-improvement`.

### 2.1 The stats interface and DB backend

- [`StatsStorage.record`](../../lib/stats/stats_storage.py):27-53 — abstract, async,
  **best-effort, never raises**; signature
  `record(stats: dict[str, float|int], *, consumerId=None, labels=None, eventTime=None)`.
  `NullStatsStorage.record` ([stats_storage.py:87](../../lib/stats/stats_storage.py))
  is a no-op.
- [`DatabaseStatsStorage`](../../internal/database/stats_storage.py):39 — constructed as
  `DatabaseStatsStorage(db, eventType, *, dataSource)`; **one `eventType` per instance**
  ([stats_storage.py:59](../../internal/database/stats_storage.py)).
  `record()` ([stats_storage.py:75](../../internal/database/stats_storage.py)) merges
  `consumerId` into `labels["consumer"]` (default `GLOBAL_CONSUMER_ID = "__global__"`,
  [stats_storage.py:8,107](../../lib/stats/stats_storage.py)) before hashing.
- `aggregate()` ([stats_storage.py:129](../../internal/database/stats_storage.py)) is
  the v3 claim-first flow. For each event it writes **two label-sets**: the event's own
  labels (per-consumer) and a `__global__` rollup where **only** `consumer` is replaced
  ([stats_storage.py:209-229](../../internal/database/stats_storage.py)). All metrics
  are **SUM**. The claim/upsert/mark steps are **not** wrapped in one transaction
  (Step 4 upsert at [stats_storage.py:233](../../internal/database/stats_storage.py),
  Step 5 mark at [stats_storage.py:260](../../internal/database/stats_storage.py); a
  `TODO` at [stats_storage.py:232](../../internal/database/stats_storage.py) flags this).

### 2.2 The `stat_aggregates` shape (the back-fill target)

From [`migration_016_add_stat_tables.py`](../../internal/database/migrations/versions/migration_016_add_stat_tables.py):120-131:

```text
event_type   TEXT   -- e.g. 'message_received'
period_start TEXT   -- ISO-8601; 'total' uses the epoch sentinel '1970-01-01T00:00:00+00:00'
period_type  TEXT   -- 'hourly' | 'daily' | 'monthly' | 'total'
labels_hash  TEXT   -- MD5 hex of canonical labels JSON
labels       TEXT   -- canonical JSON (sorted keys, compact)
metric_key   TEXT   -- e.g. 'message_count'
metric_value REAL
PRIMARY KEY (event_type, period_start, period_type, labels_hash, metric_key)
```

Canonical labels JSON = `lib.utils.jsonDumps(labelsDict)`
([utils.py:108](../../lib/utils/utils.py), `sort_keys=True`, compact separators
`(",", ":")`); `labels_hash = hashlib.md5(canonicalJson.encode()).hexdigest()`
([stats_storage.py:275-290](../../internal/database/stats_storage.py)). The back-fill
**must** produce byte-identical JSON so its `labels_hash` collides with live-aggregated
rows for the same label set.

Period truncation ([stats_storage.py:293-315](../../internal/database/stats_storage.py)):
`hourly`/`daily`/`monthly` are the ISO form of the UTC timestamp truncated to
hour/day/month; `total` is the fixed epoch sentinel above.

### 2.3 The existing construction pattern (the template for the three new instances)

[`main.py`](../../main.py):89-119:

```python
statsConfig = self.configManager.getStatsConfig()
statsEnabled = statsConfig.get("enabled", False)
if statsEnabled:
    llmStatsStorage = DatabaseStatsStorage(
        db=self.database,
        eventType="llm_request",
        dataSource=statsConfig.get("llm-stats-data-source", self.database.manager.default),
    )
# ... passed to LLMManager(statsStorage=...) and STTService.initialize(statsStorage=...)
```

Config today ([`configs/00-defaults/stats.toml`](../../configs/00-defaults/stats.toml)):

```toml
[stats]
enabled = false
llm-stats-data-source = "default"
stt-stats-data-source = "default"
```

### 2.4 The legacy message counters (the migration target)

[`ChatMessagesRepository.saveChatMessage`](../../internal/database/repositories/chat_messages.py)
does four things in one method:

1. INSERT into `chat_messages` ([chat_messages.py:118-151](../../internal/database/repositories/chat_messages.py)).
2. UPDATE `chat_users SET messages_count = messages_count + 1` ([chat_messages.py:154-166](../../internal/database/repositories/chat_messages.py)) — **this is read** by `/users`,
   `LIST_USERS`, `getChatUsers` and **must stay**; it is operational, not analytical.
3. upsert `chat_stats` (chat_id, date, daily count) ([chat_messages.py:169-183](../../internal/database/repositories/chat_messages.py)) — **no readers**.
4. upsert `chat_user_stats` (chat_id, user_id, date, daily count) ([chat_messages.py:186-201](../../internal/database/repositories/chat_messages.py)) — **no readers**.

Both legacy tables come from
[`migration_001_initial_schema.py`](../../internal/database/migrations/versions/migration_001_initial_schema.py):

```text
chat_stats        ( chat_id, date, messages_count, ... )  PK (chat_id, date)            -- 001:132-138
chat_user_stats   ( chat_id, user_id, date, messages_count, ... )
                                                  PK (chat_id, user_id, date)          -- 001:143-150
```

`chat_user_stats` is the back-fill source because it carries `user_id`.

### 2.5 The single choke points for the three new events

- **`message_received`** — every inbound message (command **and** regular) funnels
  through one wrapper:
  [`BaseBotHandler.saveChatMessage`](../../internal/bot/common/handlers/base.py):1080-1139.
  - Regular messages: `MessagePreprocessorHandler` calls
    `await self.saveChatMessage(...)` ([message_preprocessor.py:193](../../internal/bot/common/handlers/message_preprocessor.py)).
  - Commands: `HandlersManager.handleCommand` calls
    `await handlerObj.saveChatMessage(...)` ([manager.py:1012](../../internal/bot/common/handlers/manager.py)).
    `handlerObj` is whichever handler owns the command
    ([manager.py:939](../../internal/bot/common/handlers/manager.py)), but every handler
    is a `BaseBotHandler` subclass, so the wrapper is shared. `_processMessageRec`
    returns early when `handleCommand()` returns non-None
    ([manager.py:1078-1084](../../internal/bot/common/handlers/manager.py)) — a message
    is saved exactly once. No edit/metadata-update re-fire.
  - The wrapper has the full [`EnsuredMessage`](../../internal/bot/models/ensured_message.py):
    `message.sender.id` (userId), `message.recipient.id` (chatId),
    `message.recipient.chatType` (a `ChatType` enum — used the same way at
    [manager.py:949](../../internal/bot/common/handlers/manager.py)),
    `message.messageType` (a [`MessageType`](../../internal/models/shared_enums.py):25
    enum, with `TEXT = "text"` at [shared_enums.py:56](../../internal/models/shared_enums.py)),
    and `message.messageText`.

- **`llm_tool_call`** — the single centralized dispatch is in
  [`LLMService`](../../internal/services/llm/service.py), inside the tool-use loop:

  ```python
  # internal/services/llm/service.py:973-1003
  for toolCall in ret.toolCalls:
      if toolCall.errorMessage is not None:
          toolRet = {"done": False, "error": toolCall.errorMessage}     # branch 1 — synthesised
      elif toolCall.name in filteredToolNames:
          toolRet = await self.toolsHandlers[toolCall.name].call(extraData, **toolCall.parameters)  # branch 2 — real call
      else:
          toolRet = {"done": False, "error": f"Tool {toolCall.name} not available, ..."}            # branch 3 — unknown tool
  ```

  The enclosing method has `chatId` in scope (used at
  [service.py:936](../../internal/services/llm/service.py) `chatId=chatId`), and
  `extraData` carries `ensuredMessage` (the established contract — see
  [yandex_search.py:452](../../internal/bot/common/handlers/yandex_search.py),
  [chat_search.py:639](../../internal/bot/common/handlers/chat_search.py),
  [media.py:152](../../internal/bot/common/handlers/media.py), etc.), giving
  `extraData["ensuredMessage"].sender.id`. No timing wrapper exists yet. Tools obey a
  never-raise contract: they return error dicts rather than raising.

- **`command`** — the single choke point is
  [`HandlersManager.handleCommand`](../../internal/bot/common/handlers/manager.py):910-1034.
  It parses the command name ([manager.py:927](../../internal/bot/common/handlers/manager.py)),
  has the `EnsuredMessage` (sender, recipient), runs the bound handler inside a
  `try/except` ([manager.py:1015-1034](../../internal/bot/common/handlers/manager.py)),
  and returns `True` (success), `False` (permission-denied **or** exception), or `None`
  (not a command). Only the success/exception paths reach the execution attempt; the
  permission-denied early returns ([manager.py:963-974](../../internal/bot/common/handlers/manager.py),
  [manager.py:998-1009](../../internal/bot/common/handlers/manager.py)) happen first.

### 2.6 Where dependencies are injected today (the wiring facts behind D10)

- `HandlersManager.__init__(self, *, configManager, database, botProvider)`
  ([manager.py:416](../../internal/bot/common/handlers/manager.py)) — constructs every
  handler inline with the same three kwargs (e.g.
  [manager.py:482](../../internal/bot/common/handlers/manager.py)). It already performs
  post-construction injection of another dependency:
  `await self.cache.injectDatabase(self.db)` ([manager.py:721](../../internal/bot/common/handlers/manager.py)).
- `BaseBotHandler.__init__` ([base.py:137](../../internal/bot/common/handlers/base.py))
  stores `self.db = database` ([base.py:157](../../internal/bot/common/handlers/base.py));
  all handlers share the `(configManager, database, botProvider)` signature.
- The two bot applications construct the manager:
  - [`TelegramBotApplication.__init__`](../../internal/bot/telegram/application.py):67-88
    — `HandlersManager(configManager=..., database=..., botProvider=BotProvider.TELEGRAM)`.
  - [`MaxBotApplication.__init__`](../../internal/bot/max/application.py):53,
    `HandlersManager(...)` at [max/application.py:71](../../internal/bot/max/application.py).
  - Both are themselves constructed in
    [`main.py:127-137`](../../main.py) with `(configManager=..., botToken=..., database=...)`.
- `LLMService` is a singleton
  ([service.py:183-205](../../internal/services/llm/service.py)) with **no `initialize`
  method** — verified. Its only dependency-injection path today is
  `LLMService.getInstance().injectLLMManager(self.llmManager)`
  ([service.py:207-216](../../internal/services/llm/service.py); called at
  [`main.py:105`](../../main.py)). It has **no** `statsStorage` attribute today (verified
  by grep — only `injectLLMManager` matches).

---

## 3. Architecture decisions

### D1 — Three new event types; STT untouched

Add `message_received`, `llm_tool_call`, `command`. `stt_request` is already implemented
([lib/stt/abstract.py:264](../../lib/stt/abstract.py)) and needs no work.

### D2 — `consumerId = str(chatId)` for all three

Every event uses the chat id as the consumer. This matches the existing
`llm_request`/`stt_request` convention (`consumerId` threaded as `chatId`, see
[abstract.py:844](../../lib/ai/abstract.py) `"consumer": consumerId`). For messages and
commands the chat id is `message.recipient.id`; for tool calls it is the `chatId`
parameter of the enclosing `LLMService` method.

### D3 — `message` event shape

| Field | Value |
|---|---|
| `eventType` | `"message"` |
| `consumerId` | `str(message.recipient.id)` |
| stats | `message_count: 1` (int); `text_length: len(messageText or "")` (int) |
| labels | `user_id = str(message.sender.id)`; `chat_type = message.recipient.chatType.value` (`"private"` \| `"group"` \| `"channel"`); `message_type = message.messageType.value` (raw `MessageType` StrEnum, e.g. `"text"`, `"image"`, `"video"`); `message_category = messageCategory` (raw `MessageCategory` StrEnum); `sent = "True"` if `sender.id == botId`, `"False"` otherwise |

*Amended by user after Phase 1: message_type (raw enum) replaces has_media.* *Amended after Phase 4 (2026-08-16): eventType renamed to `message`; both directions recorded; direction determined by `sender.id == await self.getBotId()` (not by messageCategory); added `message_category` and `sent` labels; excluded only DELETED/UNSPECIFIED categories; split parts counted as raw saves.* No `platform` label. The platform is unique per database (one bot process = one platform), so it is a constant for every row in the store; carrying it as a label would needlessly multiply label cardinality. Applied consistently to all three events.

`message_type` is the raw `MessageType` enum value (e.g. `"text"`, `"image"`, `"video"`, `"audio"`, `"document"`, `"sticker"`). Note the `MessageType.UNKNOWN` early-return in the wrapper ([base.py:1098-1100](../../internal/bot/common/handlers/base.py)) means unknown-type messages are never saved and therefore never recorded — desirable.

**Direction rule:** `sent = "True"` when the sender is the bot (`sender.id == await self.getBotId()`), `sent = "False"` otherwise. Direction is determined by sender identity, NOT by messageCategory. This enables counting both inbound user messages and outbound bot messages (including split parts and streaming intermediates), preserving raw-save semantics.

**Exclusions:** Only `MessageCategory.DELETED` and `MessageCategory.UNSPECIFIED` are excluded (rewrites/defaults, not fresh messages). All other categories (USER, USER_COMMAND, USER_SPAM, USER_CONFIG_ANSWER, CHANNEL, BOT, BOT_COMMAND_REPLY, BOT_ERROR, BOT_SUMMARY, BOT_RESENDED, BOT_SPAM_NOTIFICATION) are recorded.

**Best-effort guard:** `getBotId()` is called once per `saveChatMessage` invocation, wrapped in a `try/except` that logs debug-level errors and skips recording when `botId is None`. This ensures stats recording never breaks message saving (getBotId can raise RuntimeError or hit the Max API on first call).

**Backfill compatibility:** Historical rows from migration 027 lack the `message_category` and `sent` labels (direction is derivable at query time via `user_id` — if `user_id` matches the bot id, `sent="True"`). Live rows always carry these labels, so backfill and live land in different `labels_hash` buckets.

### D4 — `llm_tool_call` event shape, error rule, and exception handling

| Field | Value |
|---|---|
| `eventType` | `"llm_tool_call"` |
| `consumerId` | `str(ensuredMessage.recipient.id)` (chat from ensuredMessage, NOT the method's `chatId` parameter) |
| stats | `tool_call_count: 1` (int); `elapsed_time: <seconds>` (float); `is_error: 0 \| 1` (int) |
| labels | `user_id = str(extraData["ensuredMessage"].sender.id)`; `toolName = toolCall.name` |

No `platform` label (same rationale as D3). Recording is skipped when `ensuredMessage` is absent (no "unknown" fallback). The attribute name on `LLMService` is `toolStatsStorage`.

**Error-detection rule (exact):** after the dispatch produces `toolRet`,

```python
isError = isinstance(toolRet, dict) and ("error" in toolRet or "errorMessage" in toolRet)
```

This flags all three branches correctly: branch 1 (synthesised `{"error": ...}`),
branch 3 (`{"error": "Tool ... not available"}`), and any branch-2 tool that honors the
contract by returning `{"error": ...}` / `{"errorMessage": ...}`.

**Timing (exact):** the timer wraps **only the real `.call()`** (branch 2,
[service.py:981](../../internal/services/llm/service.py)):

```python
t0 = time.monotonic()
toolRet = await self.toolsHandlers[toolCall.name].call(extraData, **toolCall.parameters)
elapsed = time.monotonic() - t0
```

For branches 1 and 3 (no real call) `elapsed_time = 0.0`. One `record()` call per
`toolCall` iteration, regardless of branch.

**Exceptions (minimal-change decision):** do **not** add a `try/except` around `.call()`.
A contract-violating tool that raises will propagate exactly as it does today and abort
the LLM generation; it will **not** be recorded (the `record()` call is never reached).
Rationale: catching-then-reraising would change control flow and risk masking/mangling
the exception; the never-raise contract means a raising tool is already a bug, and
counting it in stats is not worth the behavioral change. This is a deliberate,
documented trade-off — see §9.

### D5 — `command` event shape and `is_error` semantics

| Field | Value |
|---|---|
| `eventType` | `"command"` |
| `consumerId` | `str(ensuredMessage.recipient.id)` |
| stats | `command_count: 1` (int); `is_error: 0 \| 1` (int) |
| labels | `user_id = str(ensuredMessage.sender.id)`; `commandName = commandLower` (the lowercased parsed name, matches handler lookup; case variants like `/Help` and `/help` share one bucket. Amended 2026-08-14: normalized to lowercased to match handler lookup semantics.) |

No `platform` label.

**`is_error` semantics (interpretation of the ratified decision):** record **after the
execution attempt** so `is_error` reflects the handler outcome. Concretely:

- Record `is_error = 0` on the success path (just before `return True`,
  [manager.py:1024](../../internal/bot/common/handlers/manager.py)).
- Record `is_error = 1` in the `except` block (just before `return False`,
  [manager.py:1025-1034](../../internal/bot/common/handlers/manager.py)).

Permission/category-denied commands (the early `return False` at
[manager.py:963-974](../../internal/bot/common/handlers/manager.py) and
[manager.py:998-1009](../../internal/bot/common/handlers/manager.py)) are **not
recorded** — they were rejected before execution and are not "usage" from a stats
standpoint. This is a documented interpretation, not a denial of the decision.

### D6 — Drop the legacy tables; remove the two upserts; keep `chat_users`

A single new migration (number **027** — highest existing is
`migration_026_chat_accessibility_bot_status.py`, per
`ls -1 internal/database/migrations/versions/ | grep migration_ | sort -V | tail -1`)
will:

1. **Back-fill** `chat_user_stats` → `stat_aggregates` (see D7), reading the source
   first.
2. **Drop** `chat_stats` and `chat_user_stats` via portable `DROP TABLE IF EXISTS`.

In [`ChatMessagesRepository.saveChatMessage`](../../internal/database/repositories/chat_messages.py):
**remove** the two upserts ([chat_messages.py:169-201](../../internal/database/repositories/chat_messages.py),
steps 3 and 4) and their now-unused `today`/`ExcludedValue` bindings if those become
unused. **Keep** the `chat_users` increment ([chat_messages.py:154-166](../../internal/database/repositories/chat_messages.py))
untouched — it is operational and must work with `[stats] enabled = false`.

Follow the [`add-database-migration`](../../.agents/skills/add-database-migration/SKILL.md)
skill: `version: int = 27`, `async up/down(self, sqlProvider: BaseSQLProvider)`,
`getMigration()` export, `:named` placeholders, no `AUTOINCREMENT`/`DEFAULT CURRENT_TIMESTAMP`/`COLLATE NOCASE`/dialect DDL.

### D7 — Back-fill semantics

Migrate **all** `chat_user_stats` history into `stat_aggregates` as
`message_received` / `message_count`, in the **same migration**, **unconditionally**
(independent of `[stats] enabled` — this is data preservation, not a feature).

- **Source SELECT:** `chat_id, user_id, date, messages_count` from `chat_user_stats`.
- **Target rows written (per source row, six upserts):**
  - `event_type = "message_received"`, `metric_key = "message_count"`,
    `metric_value = messages_count`.
  - **Periods:** `daily`, `monthly`, `total` only — **no `hourly`** (source granularity
    is per-day; an hourly bucket would be misleading). `daily`/`monthly` derived from the
    `date` column (already midnight of the message day,
    [chat_messages.py:114](../../internal/database/repositories/chat_messages.py));
    `total` = the epoch sentinel `1970-01-01T00:00:00+00:00`.
  - **Two label-sets per period** (mirroring `aggregate()` exactly):
    - per-consumer: `{"consumer": str(chat_id), "user_id": str(user_id), "chat_type": <derived>}`
    - `__global__` rollup: `{"consumer": "__global__", "user_id": str(user_id), "chat_type": <derived>}`
  - `chat_type` derived from `chat_id` sign (`> 0` → `"private"`, else `"group"`) — the
    repo-wide convention; matches `ChatType.PRIVATE.value`/`GROUP.value`
    ([ensured_message.py:69-70](../../internal/bot/models/ensured_message.py)).
- **Label-set difference (documented):** back-filled rows have **no `message_type`** label
  (unknown historically). Live `message_received` rows always carry `message_type`
  ([D3](#d3--message_received-event-shape)). They therefore land in **different**
  `labels_hash` buckets and never accidentally merge — which is correct (you cannot
  aggregate "type unknown" with concrete `MessageType` values). A consequence: `total`/daily totals for
  `message_count` are split across `message_type` variants for live data and a single
  no-`message_type` bucket for historical data; cross-bucket totals need a post-query SUM
  (see §11).
- **Canonicalization (load-bearing):** the labels JSON **must** be produced with
  `lib.utils.jsonDumps(labelsDict)` (same call the aggregator makes at
  [stats_storage.py:211](../../internal/database/stats_storage.py)) and hashed with the
  `_hashLabels` helper from [`internal/database/stats_storage.py`](../../internal/database/stats_storage.py):275.
  Reusing both guarantees `labels_hash` collides with live-aggregated rows for an
  identical label set.
- **Write target:** `stat_aggregates` only — **never synthesize `stat_events` rows**.
  Writing events would let a future `aggregate()` pass double-count them. Writing
  pre-aggregated rows bypasses the event pipeline entirely.
- **Accumulation:** upsert with the same on-conflict SUM the aggregator uses
  (`metric_value = metric_value + :metric_value`,
  [stats_storage.py:253-254](../../internal/database/stats_storage.py)) so multiple
  source rows contributing to the same `(period, labels_hash)` bucket accumulate
  correctly (notably the `__global__` rollup, which sums across chats per
  `(user_id, chat_type)`).
- **Order:** back-fill **before** the `DROP`s. After a successful run the source table is
  gone, so a re-run is a no-op for the back-fill (empty source) and a no-op for the
  `DROP IF EXISTS`. The migration is one-shot (standard for this codebase); the
  partial-failure window between back-fill and drop is noted in §9.

### D8 — Deferred items (out of scope, listed)

Aggregation trigger (periodic `aggregate()` caller), retention/cleanup of processed
`stat_events`, query/read API, and user-facing display are all **deferred to a follow-up
design doc**. See §11.

### D9 — Configuration

Add three per-event data-source keys mirroring the existing pattern, all defaulting to
`"default"`. All new recording is gated on `[stats] enabled` (default `false` →
`NullStatsStorage` → zero behavior change).

```toml
# configs/00-defaults/stats.toml  (diff)
 [stats]
 enabled = false

 llm-stats-data-source = "default"
 stt-stats-data-source = "default"
+message-stats-data-source = "default"
+tool-stats-data-source = "default"
+command-stats-data-source = "default"
```

### D10 — Injection wiring (verified chains)

Three new `DatabaseStatsStorage` instances in [`main.py`](../../main.py), one per event
type, following the pattern at [`main.py:89-98`](../../main.py). Each is constructed only
when `statsEnabled`; otherwise the recipient holds a `NullStatsStorage`.

**Decision beyond the brief (flagged):** the brief's "message → repo **or** handler
base" choice is resolved in favor of **`BaseBotHandler.saveChatMessage`** (the handler
layer), not the repository. Rationale: (a) it is the proven single choke point for both
the command and the regular-message path ([§2.5](#25-the-single-choke-points-for-the-three-new-events));
(b) recording at the data-repo layer would import bot-level semantics (the
`consumer = chatId` concept, label vocabulary) into a persistence layer that is otherwise
pure — inconsistent with the LLM/STT precedent, which records in `lib/` not in repos;
(c) the wrapper already holds the `EnsuredMessage` with a typed `ChatType` enum, so
`chat_type` is read directly rather than re-derived from the `chatId` sign.

**Decision beyond the brief (flagged):** the brief asked to "verify how
`LLMService.initialize` receives dependencies." Verified: **there is no `initialize`
method** — `LLMService` injects dependencies via `injectLLMManager`
([service.py:207](../../internal/services/llm/service.py)). Tool-call stats therefore go
through a new parallel injector `LLMService.injectStatsStorage(statsStorage)`, mirroring
the existing one.

**Decision beyond the brief (flagged):** to avoid editing ~15 handler constructors,
message-stats injection is done **post-construction** by the manager (the manager already
injects another dependency post-construction at
[manager.py:721](../../internal/bot/common/handlers/manager.py)). `BaseBotHandler` keeps a
default `NullStatsStorage` so stats-off needs no `None` checks.

#### D10.1 `message_received` chain

```
main.py  ──messageStatsStorage──▶  TelegramBotApplication / MaxBotApplication
                                   (new kwarg messageStatsStorage)
         ──▶  HandlersManager.__init__  (new kwarg messageStatsStorage)
                   │  after self.handlers is built, iterate and set
                   │  handler.messageStatsStorage = self.messageStatsStorage
                   ▼
              BaseBotHandler.saveChatMessage  (records; default NullStatsStorage)
```

- `main.py`: build `messageStatsStorage` (gated on `statsEnabled`) right after the
  existing `llmStatsStorage` block ([main.py:90-98](../../main.py)).
- `TelegramBotApplication.__init__` ([application.py:67](../../internal/bot/telegram/application.py))
  and `MaxBotApplication.__init__` ([max/application.py:53](../../internal/bot/max/application.py)):
  accept `messageStatsStorage` and forward to `HandlersManager(...)`.
- `HandlersManager.__init__` ([manager.py:416](../../internal/bot/common/handlers/manager.py)):
  accept `messageStatsStorage: Optional[StatsStorage] = None`; store
  `self.messageStatsStorage = messageStatsStorage or NullStatsStorage()`; after
  `self.handlers` is assembled, set it on every handler.
- `BaseBotHandler.__init__` ([base.py:137](../../internal/bot/common/handlers/base.py)):
  `self.messageStatsStorage: StatsStorage = NullStatsStorage()`.
- `BaseBotHandler.saveChatMessage` ([base.py:1080](../../internal/bot/common/handlers/base.py)):
  after the successful `self.db.chatMessages.saveChatMessage(...)` await
  ([base.py:1121-1137](../../internal/bot/common/handlers/base.py)), record per [D3](#d3--message_received-event-shape).
  `record()` is best-effort/never-raises, so it cannot affect the save outcome.

#### D10.2 `llm_tool_call` chain

```
main.py  ──toolStatsStorage──▶  LLMService.getInstance().injectStatsStorage(...)
                                                                        │
                                                                        ▼
                                            LLMService tool-dispatch loop (service.py:973-1003)
```

- `main.py`: build `toolStatsStorage` (gated on `statsEnabled`); call
  `LLMService.getInstance().injectStatsStorage(toolStatsStorage)` immediately after the
  existing `injectLLMManager` call ([main.py:105](../../main.py)).
- `LLMService.__init__` ([service.py:183](../../internal/services/llm/service.py)): add
  `self.statsStorage: StatsStorage = NullStatsStorage()`; add
  `def injectStatsStorage(self, statsStorage: StatsStorage) -> None` mirroring
  `injectLLMManager`.
- In the tool loop ([service.py:973-1003](../../internal/services/llm/service.py)): time
  branch 2, compute `isError` per [D4](#d4--llm_tool_call-event-shape-error-rule-and-exception-handling),
  and `await self.statsStorage.record(...)` once per `toolCall`.

No application/handler/manager changes for this event — `LLMService` is a singleton
reachable from `main.py` directly.

#### D10.3 `command` chain

```
main.py  ──commandStatsStorage──▶  TelegramBotApplication / MaxBotApplication
                                    (new kwarg commandStatsStorage)
          ──▶  HandlersManager.__init__  (new kwarg commandStatsStorage)
                        │  self.commandStatsStorage = commandStatsStorage or NullStatsStorage()
                        ▼
              HandlersManager.handleCommand  (records; service.py... manager.py:910-1034)
```

- `main.py`: build `commandStatsStorage` (gated on `statsEnabled`); forward through both
  application classes to `HandlersManager`.
- `HandlersManager.__init__` ([manager.py:416](../../internal/bot/common/handlers/manager.py)):
  accept `commandStatsStorage: Optional[StatsStorage] = None`; store
  `self.commandStatsStorage = commandStatsStorage or NullStatsStorage()`.
- `handleCommand` ([manager.py:910](../../internal/bot/common/handlers/manager.py)):
  record per [D5](#d5--command-event-shape-and-is_error-semantics) on the success and
  exception paths.

`messageStatsStorage` and `commandStatsStorage` are **separate** `DatabaseStatsStorage`
instances (one `eventType` per instance, [§2.1](#21-the-stats-interface-and-db-backend));
each uses its own data-source key ([D9](#d9--configuration)).

---

## 4. Wiring summary (file:line touch list)

| Event | Record site (file:line) | Storage lives on | New injector |
|---|---|---|---|
| `message_received` | [`base.py:1080`](../../internal/bot/common/handlers/base.py) `BaseBotHandler.saveChatMessage` | each `BaseBotHandler` instance (set by manager) | `HandlersManager` → handlers |
| `llm_tool_call` | [`service.py:973-1003`](../../internal/services/llm/service.py) tool loop | `LLMService` singleton | `LLMService.injectStatsStorage` (new) |
| `command` | [`manager.py:910`](../../internal/bot/common/handlers/manager.py) `handleCommand` | `HandlersManager` instance | application class → `HandlersManager` |

Construction (all three) in [`main.py`](../../main.py) beside
[`main.py:89-98`](../../main.py), gated on `statsEnabled`.

---

## 5. Database migration specification

**File:** `internal/database/migrations/versions/migration_027_drop_chat_stats_backfill_aggregates.py`
(number verified — `migration_026_*` is the highest today).

**Class:** `Migration027DropChatStatsBackfillAggregates(BaseMigration)`,
`version: int = 27`.

**`up(self, sqlProvider)`:**

1. **Back-fill** (before any DROP):

   ```python
   rows = await sqlProvider.executeFetchAll(
       "SELECT chat_id, user_id, date, messages_count FROM chat_user_stats"
   )
   totalSentinel = "1970-01-01T00:00:00+00:00"
   for row in rows:
       chatId, userId, dateVal, count = row["chat_id"], row["user_id"], row["date"], row["messages_count"]
       chatType = "private" if chatId > 0 else "group"
       for labels in (
           {"consumer": str(chatId), "user_id": str(userId), "chat_type": chatType},
           {"consumer": "__global__", "user_id": str(userId), "chat_type": chatType},
       ):
           labelsJson = libUtils.jsonDumps(labels)              # canonical, matches aggregator
           for periodType, periodStart in (
               ("daily",   _dayISO(dateVal)),
               ("monthly", _monthISO(dateVal)),
               ("total",   totalSentinel),
           ):
               await sqlProvider.upsert(
                   table="stat_aggregates",
                   values={
                       "event_type": "message_received",
                       "period_start": periodStart,
                       "period_type": periodType,
                       "labels_hash": _hashLabels(labelsJson),   # reuse from stats_storage.py:275
                       "labels": labelsJson,
                       "metric_key": "message_count",
                       "metric_value": count,
                       "updated_at": dbUtils.getCurrentTimestamp(),
                   },
                   conflictColumns=["event_type", "period_start", "period_type", "labels_hash", "metric_key"],
                   updateExpressions={"metric_value": "metric_value + :metric_value", "updated_at": ExcludedValue()},
               )
   ```

   - `_dayISO`/`_monthISO` normalize the stored `date` (midnight timestamp) to the same
     ISO-8601 UTC form `_computePeriods` emits ([stats_storage.py:305-314](../../internal/database/stats_storage.py)).
   - `libUtils.jsonDumps` + `_hashLabels` are imported from existing modules so the bytes
     and hashes match the live aggregator exactly.

2. **Drop** (portable, idempotent):

   ```python
   await sqlProvider.batchExecute([
       ParametrizedQuery("DROP TABLE IF EXISTS chat_stats"),
       ParametrizedQuery("DROP TABLE IF EXISTS chat_user_stats"),
   ])
   ```

**`down(self, sqlProvider)`:** recreate `chat_stats` and `chat_user_stats` empty using
the exact DDL from `migration_001` ([001:132-150](../../internal/database/migrations/versions/migration_001_initial_schema.py)).
The back-fill is **not reversible** (the original rows are destroyed by `up`'s DROP and
cannot be reconstructed from `stat_aggregates` without a per-event granularity that does
not exist). Document this in the `down()` docstring.

**Portability checklist (per the migration skill):** no `AUTOINCREMENT`, no
`DEFAULT CURRENT_TIMESTAMP`, no `COLLATE NOCASE`, no dialect-specific types, `:named`
placeholders only, `upsert` via the provider, timestamps set in application code.

**Tests:** add a migration test in
[`tests/database/migrations/test_migrations.py`](../../tests/database/migrations/test_migrations.py)
exercising `up()` (seed `chat_user_stats`, assert `stat_aggregates` rows for all
six combinations per source row including the `__global__` rollup and the SUM behavior,
then assert both tables are gone) and `down()` (tables recreated empty). `asyncio_mode =
"auto"` — write `async def test_...` with no decorator; reuse `testDatabase` from
[`tests/conftest.py`](../../tests/conftest.py).

---

## 6. Configuration changes

See [D9](#d9--configuration). Only [`configs/00-defaults/stats.toml`](../../configs/00-defaults/stats.toml)
changes. `ConfigManager.getStatsConfig()` already returns the merged `[stats]` dict, so
no code change is needed to *read* the new keys — they are consumed via
`statsConfig.get("message-stats-data-source", self.database.manager.default)` etc. in
`main.py`, mirroring [`main.py:97,117`](../../main.py).

---

## 7. Phased implementation plan

Hard rules for **every** phase (`AGENTS.md`): `camelCase` identifiers; invoke Python as
`./venv/bin/python3` (never `python`/`python3`); run `make format lint` **before AND
after** edits; `make test` (wrapped in `timeout 5m`) is mandatory after any change;
regression tests on every bug fix (write the failing test first). Load the
[`run-quality-gates`](../../.agents/skills/run-quality-gates/SKILL.md) skill for the
exact commands.

Each phase is independently revertible via git and ships on its own. The phases are
ordered so the riskiest schema change (Phase 1) lands with the highest-value event and
the other two events are additive wiring on top.

### Phase 1 — `message_received` + migration (drop + back-fill) + config

The largest phase because it carries the schema change. Split into two commits if review
benefits: (1a) migration + repo cleanup + config; (1b) `message_received` wiring. Both
must land before Phase 1 is considered done.

**Files touched:**

- `internal/database/migrations/versions/migration_027_drop_chat_stats_backfill_aggregates.py` — new.
- `internal/database/repositories/chat_messages.py` — remove the two upserts
  ([169-201](../../internal/database/repositories/chat_messages.py)); prune `today` if
  it becomes unused.
- `configs/00-defaults/stats.toml` — add the three keys ([D9](#d9--configuration)).
- `main.py` — build `messageStatsStorage`; thread to both application classes.
- `internal/bot/telegram/application.py`,
  `internal/bot/max/application.py` — accept + forward `messageStatsStorage`.
- `internal/bot/common/handlers/manager.py` — `HandlersManager.__init__` accepts
  `messageStatsStorage`; sets it on handlers after `self.handlers` is built.
- `internal/bot/common/handlers/base.py` — `BaseBotHandler.__init__` default
  `NullStatsStorage`; `saveChatMessage` records per [D3](#d3--message_received-event-shape).
- `lib/stats/__init__.py` (only if `NullStatsStorage` is not already re-exported for
  handler-layer import — verify during implementation).

**Tests required (under `tests/`, mirror layout, `asyncio_mode = "auto"`):**

- `tests/database/migrations/test_migrations.py` — migration `up`/`down` (see §5).
- `tests/database/test_db_wrapper.py` (or collocated `tests/database/repositories/test_chat_messages.py`)
  — assert `saveChatMessage` no longer writes `chat_stats`/`chat_user_stats` and still
  increments `chat_users.messages_count`; regression test that the two upserts are gone.
- `tests/bot/common/handlers/test_message_preprocessor.py` (or the base-handler test
  home) — assert `message_received` is recorded once per message with the right
  stats/labels when `statsEnabled`, and **not at all** when the storage is
  `NullStatsStorage`; construct real `EnsuredMessage` objects per the `conftest.py`
  pattern.
- Reset `CacheService`/singleton state in fixtures (`tests/conftest.py`).

**Docs to sync (load the [`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md) skill):**

- [`docs/database-schema.md`](../database-schema.md) **and**
  [`docs/database-schema-llm.md`](../database-schema-llm.md) — remove `chat_stats` and
  `chat_user_stats` entries (both files must stay in sync).
- [`docs/llm/database.md`](../llm/database.md) — add migration 027 to the version list.
- [`docs/llm/configuration.md`](../llm/configuration.md) — document the three new
  `[stats]` keys.
- `CHANGELOG.md` — one `Changed` entry under `## [Unreleased]` (schema change +
  user-visible stats capability behind a flag).

**Verification:** `make format lint`; `make test`; `make check-docs`.

**Gate 1:** legacy tables dropped + history back-filled; `message_received` records with
stats on and is silent with stats off; `chat_users` counts still increment.

### Phase 2 — `llm_tool_call`

**Files touched:**

- `internal/services/llm/service.py` — `__init__` default `statsStorage`; new
  `injectStatsStorage`; timing + record in the tool loop ([service.py:973-1003](../../internal/services/llm/service.py)).
- `main.py` — build `toolStatsStorage`; `LLMService.getInstance().injectStatsStorage(...)`
  after [`main.py:105`](../../main.py).

**Tests required:**

- `tests/services/llm/test_service.py` (or the existing LLM-service test home) — assert
  one `record()` per tool call across all three branches; `is_error` correct for each;
  `elapsed_time > 0` for branch 2 and `0.0` for branches 1/3; `user_id` fallback
  `"unknown"` when `ensuredMessage` absent; nothing recorded with `NullStatsStorage`.
- A regression test asserting that a raising tool still propagates (the never-raise
  contract is unchanged) and is **not** recorded.

**Docs to sync:** [`docs/llm/services.md`](../llm/services.md) (note the new
`injectStatsStorage` and the `llm_tool_call` event); `CHANGELOG.md` `Added` entry.

**Verification:** `make format lint`; `make test`.

**Gate 2:** tool calls recorded with timing + error label; exception behavior unchanged.

### Phase 3 — `command`

**Files touched:**

- `main.py` — build `commandStatsStorage`; thread through both application classes.
- `internal/bot/telegram/application.py`,
  `internal/bot/max/application.py` — accept + forward `commandStatsStorage`.
- `internal/bot/common/handlers/manager.py` — `HandlersManager.__init__` accepts
  `commandStatsStorage`; `handleCommand` records per [D5](#d5--command-event-shape-and-is_error-semantics).

**Tests required:**

- `tests/bot/common/handlers/test_manager.py` (or the command-handling test home) —
  assert a `command` event on the success path (`is_error = 0`) and the exception path
  (`is_error = 1`); assert **no** event on permission-denied / category-denied early
  returns; correct labels (`user_id`, `commandName`); silent with `NullStatsStorage`.
- Regression test that a denied command is still rejected (behavior unchanged) and simply
  not counted.

**Docs to sync:** [`docs/llm/handlers.md`](../llm/handlers.md) (note the new
`HandlersManager` kwargs and the `command` event); `CHANGELOG.md` `Added` entry.

**Verification:** `make format lint`; `make test`.

**Gate 3:** commands recorded with outcome label; denial/exception behavior unchanged.

---

## 8. Verification gates

| Gate | Command / action | When |
|---|---|---|
| Format + lint | `make format lint` (before AND after edits) | every phase |
| Test suite | `make test` (wrapped in `timeout 5m`) | every phase |
| Docs links | `make check-docs` | Phase 1 (schema-doc sync) |
| Migration up/down | `tests/database/migrations/test_migrations.py` | Phase 1 |
| Stats-off silence | unit tests assert `NullStatsStorage` records nothing | every phase |
| Back-fill equivalence | migration test asserts six rows per `chat_user_stats` row + `__global__` SUM | Phase 1 |

There is no live/operator smoke gate for this design: stats are best-effort, off by
default, and the existing test suite plus the migration test are the safety net.

---

## 9. Risk register + rollback

| Risk | Likelihood | Impact | Mitigation | Rollback |
|---|---|---|---|---|
| **Hot-path cost of `await record()` INSERT** — `message_received` fires on every inbound message, adding an awaited `stat_events` INSERT to the message-save path | Med | Med | Consistent with the `lib/ai` precedent (every LLM call already awaits `record()`); `record()` is best-effort and the INSERT is a single row; if it proves hot, a future async fire-and-forget queue is an option (out of scope here, NG1) | Set `[stats] enabled = false` |
| **Back-fill partial failure** — crash between back-fill and DROP leaves `chat_user_stats` intact but `stat_aggregates` already populated; a re-run would double-count | Low | High | Migration is one-shot (standard for this codebase); document the window; operator can `DELETE FROM stat_aggregates WHERE event_type='message' AND labels NOT LIKE '%message_type%'` to undo a partial back-fill before re-running | Manual cleanup per above, then re-run |
| **`labels_hash` mismatch** — back-fill produces a different canonical JSON than the aggregator, splitting buckets | Low | Med | Reuse `lib.utils.jsonDumps` + `_hashLabels` verbatim ([D7](#d7--back-fill-semantics)); migration test asserts a back-filled row and a live-aggregated row for the same labels share a `labels_hash` | Revert migration; regenerate after fixing canonicalization |
| **Label cardinality** — `user_id` is a high-cardinality label; `stat_aggregates` grows with distinct (consumer, user_id, chat_type, …) combos | Med | Low | SUM-only aggregation keeps row count = distinct combos × periods; `message_type` multiplies by the bounded `MessageType` enum cardinality. Monitor row count; a future retention/cleanup pass is NG2 | n/a |
| **Non-atomic aggregation** (claim → upsert → mark) — a crash mid-`aggregate()` can double-count or leave orphans | Low | Med | Already accepted in the v3 design (`TODO` at [stats_storage.py:232](../../internal/database/stats_storage.py)); orphan reclaim is built into the claim step. Not introduced by this design | n/a (pre-existing) |
| **Multi data-source mismatch** — if an operator sets `message-stats-data-source` to a non-`default` source, the migration (which runs where `chat_user_stats` lives) writes `stat_aggregates` to a different source than live events | Low | Med | Default config puts everything in `"default"` (no mismatch). Document that non-default stats data sources require `stat_aggregates` to exist there (already a precondition for `llm_request`/`stt_request` to work) | Keep `*-stats-data-source = "default"` |
| **Tool-exception blind spot** (D4) — a raising tool is not recorded | Low | Low | Never-raise contract makes this a bug, not a stats gap; catching would change behavior | n/a |
| **`chat_users` regression** — accidentally removing the operational increment along with the legacy upserts | Low | High | The increment ([chat_messages.py:154-166](../../internal/database/repositories/chat_messages.py)) is a distinct block; regression test asserts it still fires with stats off | Revert Phase 1 repo edit |

**Rollback principle:** every phase is independently revertible via git. Phase 1's
migration `down()` recreates the legacy tables **empty** (the back-fill is irreversible
— documented). Because `[stats] enabled = false` by default, rolling back the wiring
while leaving the migration in place is safe (no recording happens).

---

## 10. Open questions

1. **`NullStatsStorage` import surface for the handler layer.** `BaseBotHandler` and
   `HandlersManager` need to reference `NullStatsStorage` as a default. Confirm whether
   `lib/stats/__init__.py` re-exports it (if not, import from
   `lib.stats.stats_storage`). Resolve during Phase 1 implementation.
2. **`text_length` for media-only messages.** D3 sets `text_length = len(messageText or "")`
  (0 for media-only). Confirm this is the desired semantic versus omitting the metric
  for media-only messages. (Recommendation: keep it uniform at 0 — simpler, and SUM is
  still meaningful as "total text characters authored".)
3. **Back-fill `date` timezone normalization.** Historical `chat_user_stats.date` values
  are midnight timestamps whose timezone encoding depends on the writer at the time.
  `_dayISO`/`_monthISO` must produce the same ISO-8601 UTC form as `_computePeriods`.
  Verify against a sample of real rows during Phase 1.

---

## 11. Future work (deferred per D8)

- **Aggregation trigger** — a periodic `aggregate()` caller (scheduler task or startup
  loop) so `stat_events` actually rolls up into `stat_aggregates`. Required before any of
  the three new event types produce queryable aggregates from live data (the back-fill
  writes pre-aggregated rows directly, so it does not depend on this).
- **Retention / cleanup** of processed `stat_events` rows.
- **Query / read API** and **user-facing display** of stats.
- **Transactional aggregation** — wrap claim + upsert + mark in one transaction once the
  provider gains a transactional batch primitive (the `TODO` at
  [stats_storage.py:232](../../internal/database/stats_storage.py)).
- **True cross-user global totals.** The current `__global__` rollup replaces only
  `consumer` and keeps `user_id`, so it is a per-user-across-chats rollup, not a
  grand total. Cross-user totals today require a post-query SUM across `user_id`
  buckets (and across `message_type` buckets for the live/historical split, [D7](#d7--back-fill-semantics)).
  A future stripped-labels rollup pass (drop `user_id` too) would give true globals.

---

## 12. Documentation impact (when implementation lands)

Load the [`update-project-docs`](../../.agents/skills/update-project-docs/SKILL.md) skill
and update:

- [`docs/database-schema.md`](../database-schema.md) **and**
  [`docs/database-schema-llm.md`](../database-schema-llm.md) — remove `chat_stats` and
  `chat_user_stats` (both files must stay in sync).
- [`docs/llm/database.md`](../llm/database.md) — add migration 027 to the version list.
- [`docs/llm/configuration.md`](../llm/configuration.md) — the three new `[stats]` keys.
- [`docs/llm/services.md`](../llm/services.md) — `LLMService.injectStatsStorage` and the
  `llm_tool_call` event (Phase 2).
- [`docs/llm/handlers.md`](../llm/handlers.md) — new `HandlersManager` kwargs and the
  `command` event (Phase 3).
- [`docs/llm/libraries.md`](../llm/libraries.md) — note the new `lib/stats` event types
  if that file enumerates them.
- `CHANGELOG.md` — entries per phase under `## [Unreleased]`.

This design document itself gets **no** changelog entry (doc-only, no shipped feature —
per `AGENTS.md`).

---

## 13. References

- Stats interface: [`lib/stats/stats_storage.py`](../../lib/stats/stats_storage.py)
- DB backend: [`internal/database/stats_storage.py`](../../internal/database/stats_storage.py)
- Stat-tables migration: [`migration_016_add_stat_tables.py`](../../internal/database/migrations/versions/migration_016_add_stat_tables.py)
- Legacy tables: [`migration_001_initial_schema.py`](../../internal/database/migrations/versions/migration_001_initial_schema.py):132-150
- Construction pattern: [`main.py`:89-119](../../main.py)
- Migration skill: [`add-database-migration`](../../.agents/skills/add-database-migration/SKILL.md)
- Precedent design doc (structure): [`httpx2-migration-v1.md`](./httpx2-migration-v1.md)
