# Gromozeka — Improvement Suggestions, dood!

> **Scope:** New features, performance optimizations, reliability improvements, observability, DX, security, scalability, testing, and UX enhancements, dood!  
> **NOT in scope:** Structural refactoring → see [`docs/suggestions/refactoring.md`](refactoring.md) | Complexity reduction → see [`docs/suggestions/simplification.md`](simplification.md)  
> **Last updated:** 2026-04-18
> **Status review:** 2026-05-02

---

## Summary Table

| # | Status | Title | Category | Priority | Effort |
|---|--------|-------|----------|----------|--------|
| 1 | [ ] | [Prometheus Metrics Endpoint](#1-prometheus-metrics-endpoint) | Observability | High | M |
| 2 | [ ] | [Structured JSON Request Tracing](#2-structured-json-request-tracing) | Observability | High | M |
| 3 | [ ] | [Health Check HTTP Endpoint](#3-health-check-http-endpoint) | Reliability | Critical | S |
| 4 | [ ] | [LLM Provider Circuit Breaker](#4-llm-provider-circuit-breaker) | Reliability | High | M |
| 5 | [ ] | [Graceful Degradation on DB Errors](#5-graceful-degradation-on-db-errors) | Reliability | High | M |
| 6 | [ ] | [Async SQLite Connection Pooling](#6-async-sqlite-connection-pooling) | Performance | High | L |
| 7 | [ ] | [Database Query Index Audit](#7-database-query-index-audit) | Performance | High | S |
| 8 | [ ] | [LLM Response Streaming](#8-llm-response-streaming) | Feature / UX | High | L |
| 9 | [ ] | [Per-User Rate Limiting](#9-per-user-rate-limiting) | Security | High | M |
| 10 | [ ] | [Admin Command Permission Hardening](#10-admin-command-permission-hardening) | Security | High | M |
| 11 | [ ] | [Secrets in Environment Variables](#11-secrets-in-environment-variables) | Security | Critical | S |
| 12 | [ ] | [User Preferences & Per-Chat Personas](#12-user-preferences--per-chat-personas) | Feature | Medium | L |
| 13 | [ ] | [Scheduled Messages & Reminders](#13-scheduled-messages--reminders) | Feature | Medium | M |
| 14 | [ ] | [Bot Usage Analytics Dashboard](#14-bot-usage-analytics-dashboard) | Observability | Medium | L |
| 15 | [ ] | [Hot-Reload Configuration](#15-hot-reload-configuration) | DX | Medium | M |
| 16 | [ ] | [Development Seed & Fixture Mode](#16-development-seed--fixture-mode) | DX | Medium | S |
| 17 | [ ] | [Performance / Load Tests](#17-performance--load-tests) | Testing | Medium | M |
| 18 | [ ] | [Chaos / Fault-Injection Tests](#18-chaos--fault-injection-tests) | Testing | Medium | M |
| 19 | [ ] | [End-to-End Integration Test Suite](#19-end-to-end-integration-test-suite) | Testing | Medium | L |
| 20 | [ ] | [Cache Hit-Rate Tracking](#20-cache-hit-rate-tracking) | Observability | Medium | S |
| 21 | [ ] | [LLM Cost Tracking & Budget Alerts](#21-llm-cost-tracking--budget-alerts) | Feature | Medium | M |
| 22 | [ ] | [Plugin / Custom Handler Hot-Load](#22-plugin--custom-handler-hot-load) | Scalability | Low | XL |
| 23 | [ ] | [Horizontal Scaling with Redis Queue Backend](#23-horizontal-scaling-with-redis-queue-backend) | Scalability | Low | XL |
| 24 | [ ] | [Admin Web Panel](#24-admin-web-panel) | Feature | Low | XL |
| 25 | [ ] | [Makefile: Watch Mode & Parallel CI Jobs](#25-makefile-watch-mode--parallel-ci-jobs) | DX | Low | S |
| 26 | [ ] | [Automated Dependency Updates via Renovate/Dependabot](#26-automated-dependency-updates-via-renovatedependabot) | DX | Low | S |
| 27 | [ ] | [Input Sanitization & Max Message Length Guard](#27-input-sanitization--max-message-length-guard) | Security | Medium | S |

---

## Observability

---

### 1. Prometheus Metrics Endpoint

**Category:** Observability  
**Priority:** High  
**Effort:** M (1-2 days)

#### Current State

There is no metrics collection at all, dood! The only observability is standard Python `logging`. The [`RateLimiterManager.getStats()`](../lib/rate_limiter/manager.py:256) method exists but its output is never exposed outside the process. There are no counters for messages processed, LLM calls, cache hits, or errors, dood!

#### Proposed Improvement

Add a lightweight `aiohttp` or `fastapi` metrics server exposing a `/metrics` endpoint in Prometheus text format, dood!

```python
# lib/metrics/collector.py
from prometheus_client import Counter, Histogram, Gauge, start_http_server

MESSAGES_PROCESSED = Counter("gromozeka_messages_total", "Total messages processed", ["platform", "chat_type"])
LLM_REQUESTS = Counter("gromozeka_llm_requests_total", "LLM requests", ["provider", "model", "status"])
LLM_LATENCY = Histogram("gromozeka_llm_latency_seconds", "LLM request latency", ["provider", "model"])
CACHE_HITS = Counter("gromozeka_cache_hits_total", "Cache hits", ["namespace"])
CACHE_MISSES = Counter("gromozeka_cache_misses_total", "Cache misses", ["namespace"])
ACTIVE_CHATS = Gauge("gromozeka_active_chats", "Number of active chats in the last hour")
QUEUE_DEPTH = Gauge("gromozeka_queue_depth", "Current message queue depth")
SPAM_BLOCKED = Counter("gromozeka_spam_blocked_total", "Messages blocked by spam filter")
```

Increment counters at instrumentation points in [`HandlersManager`](../internal/bot/common/handlers/manager.py), [`LLMService`](../internal/services/llm/service.py), and [`CacheService`](../internal/services/cache/service.py), dood!

Start the metrics HTTP server in [`GromozekBot.__init__()`](../main.py:34) based on config flag, dood!

#### Expected Impact

- Real-time visibility into bot health and throughput, dood!
- Alerts on LLM error spikes, cache degradation, or queue buildup, dood!
- ~5% overhead from `prometheus_client` counters (lock-free in CPython), dood!

#### Implementation Notes

- Add `prometheus_client` to `requirements.txt`
- Config: `[metrics] enabled = true`, `port = 9090` in `configs/00-defaults/00-config.toml`
- Add getter `getMetricsConfig()` to [`ConfigManager`](../internal/config/manager.py)
- Expose metrics port in Docker/deployment config

#### Affected Files

- [`main.py`](../main.py)
- [`internal/config/manager.py`](../internal/config/manager.py)
- [`internal/services/llm/service.py`](../internal/services/llm/service.py)
- [`internal/services/cache/service.py`](../internal/services/cache/service.py)
- [`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py)
- `lib/metrics/collector.py` (new)
- `configs/00-defaults/00-config.toml`

---

### 2. Structured JSON Request Tracing

**Category:** Observability  
**Priority:** High  
**Effort:** M (1-2 days)

#### Current State

Log lines are unstructured plain text. The [`lib/logging_utils.py`](../lib/logging_utils.py) provides `initLogging()` but only configures standard format strings. Correlating logs across a multi-step message processing flow (preprocessor → spam → LLM) is impossible, dood!

#### Proposed Improvement

Assign a `traceId` (UUID4 short) per message at [`MessagePreprocessorHandler`](../internal/bot/common/handlers/message_preprocessor.py) and propagate it through the handler chain via `EnsuredMessage.traceId`, dood!

Emit structured JSON logs via `python-json-logger`:

```python
# Each log entry automatically includes:
{
  "timestamp": "2026-04-18T15:00:00Z",
  "level": "INFO",
  "logger": "internal.services.llm.service",
  "traceId": "a3f7b2c1",
  "chatId": -1001234567890,
  "userId": 42,
  "handler": "LLMMessageHandler",
  "event": "llm_request_sent",
  "provider": "openrouter",
  "model": "gpt-4o",
  "durationMs": 1234
}
```

Add `logging.LoggerAdapter` that injects `traceId` + `chatId` into every log record, dood!

#### Expected Impact

- Sub-second root cause analysis of failures in production, dood!
- Enables log aggregation in Loki / Elasticsearch / CloudWatch, dood!
- Zero behavior change — purely additive logging enhancement, dood!

#### Implementation Notes

- Add `python-json-logger` to `requirements.txt`
- Config: `[logging] json = true` in TOML
- `EnsuredMessage.traceId: Optional[str]` is a non-breaking field addition
- The existing `json-logging` config key in [`LLMManager._initModels()`](../lib/ai/manager.py:64) already shows intent for JSON logs — unify it, dood!

#### Affected Files

- [`lib/logging_utils.py`](../lib/logging_utils.py)
- [`internal/bot/models/ensured_message.py`](../internal/bot/models/ensured_message.py)
- [`internal/bot/common/handlers/message_preprocessor.py`](../internal/bot/common/handlers/message_preprocessor.py)
- `configs/00-defaults/00-config.toml`

---

### 20. Cache Hit-Rate Tracking

**Category:** Observability  
**Priority:** Medium  
**Effort:** S (hours)

#### Current State

[`CacheService`](../internal/services/cache/service.py:88) has no hit/miss counters, dood! The internal [`LRUCache`](../internal/services/cache/service.py:39) has a `maxSize` but its eviction counter only goes to `logger.debug`, dood! There is no way to know if the LRU cache is undersized or if persistence round-trips are happening frequently, dood!

#### Proposed Improvement

Add lightweight counters to [`LRUCache`](../internal/services/cache/service.py:39) and expose them in a `getStats()` method, dood!

```python
class LRUCache[K, V](OrderedDict[K, V]):
    def __init__(self, maxSize: int = 1000):
        super().__init__()
        self.maxSize = maxSize
        self.lock = RLock()
        self.hits: int = 0
        self.misses: int = 0
        self.evictions: int = 0

    def getStats(self) -> Dict[str, Any]:
        """Return cache statistics, dood!"""
        total: int = self.hits + self.misses
        hitRate: float = (self.hits / total * 100) if total > 0 else 0.0
        return {"hits": self.hits, "misses": self.misses, "evictions": self.evictions, "hitRatePct": hitRate, "size": len(self)}
```

Surface via `/dev stats` command in [`DevCommandsHandler`](../internal/bot/common/handlers/dev_commands.py), dood!

#### Expected Impact

- Instant visibility into cache effectiveness, dood!
- Enables data-driven tuning of `maxSize` and cache TTLs, dood!

#### Affected Files

- [`internal/services/cache/service.py`](../internal/services/cache/service.py)
- [`internal/bot/common/handlers/dev_commands.py`](../internal/bot/common/handlers/dev_commands.py)

---

### 14. Bot Usage Analytics Dashboard

**Category:** Observability  
**Priority:** Medium  
**Effort:** L (3-5 days)

#### Current State

All data exists in SQLite (`chat_messages`, `chat_users`) but there are no aggregate queries or reporting endpoints, dood! Operators have no visibility into: daily active users (DAU), command popularity, most active chats, LLM model usage distribution, dood!

#### Proposed Improvement

Add an analytics module that queries the read-only DB source and produces a JSON report or Markdown summary, dood!

```python
# internal/analytics/report.py
class AnalyticsReport:
    """Generates usage analytics from the database, dood!"""

    async def generateDailyReport(self, database: Database, days: int = 7) -> AnalyticsReportDict:
        """Generate daily active users, top commands, top chats, dood!"""
```

Expose via a `/admin analytics` command (admin-only, using `CommandPermission.OWNER`) and optionally post automatically at midnight via `DelayedTaskFunction.CRON_JOB`, dood!

#### Expected Impact

- Informed decisions on which features to invest in, dood!
- Detect inactive/abusive chats, dood!

#### Affected Files

- `internal/analytics/` (new module)
- [`internal/bot/common/handlers/dev_commands.py`](../internal/bot/common/handlers/dev_commands.py)
- [`internal/services/queue_service/service.py`](../internal/services/queue_service/service.py)

---

## Reliability

---

### 3. Health Check HTTP Endpoint

**Category:** Reliability  
**Priority:** Critical  
**Effort:** S (hours)

#### Current State

There is no health-check endpoint, dood! Container orchestrators (Docker Healthcheck, Kubernetes liveness/readiness probes) cannot verify whether the bot process is healthy or merely zombie-alive, dood! A crash in the Telegram long-polling loop would go undetected until manually spotted, dood!

#### Proposed Improvement

Add a minimal `aiohttp` server on a configurable port that responds to `GET /health`:

```python
# lib/health/server.py
from aiohttp import web

async def handleHealth(request: web.Request) -> web.Response:
    """Return 200 OK if bot is healthy, 503 otherwise, dood!"""
    checks: Dict[str, bool] = {
        "queue": queueService.isHealthy(),
        "database": database.ping(),
    }
    allHealthy: bool = all(checks.values())
    status: int = 200 if allHealthy else 503
    return web.json_response({"status": "ok" if allHealthy else "degraded", "checks": checks}, status=status)
```

Start server alongside bot in [`main.py`](../main.py:74), dood!

#### Expected Impact

- Zero-downtime container restarts via proper liveness probes, dood!
- Prevents traffic routing to a crashed bot pod, dood!
- ~0 performance impact (single tiny aiohttp route), dood!

#### Implementation Notes

- Reuses `aiohttp` already likely in requirements (check `requirements.txt`)
- Config: `[health] enabled = true`, `port = 8080`
- `DatabaseWrapper.ping()`: `SELECT 1` with 1s timeout

#### Affected Files

- [`main.py`](../main.py)
- `lib/health/server.py` (new)
- [`internal/config/manager.py`](../internal/config/manager.py)
- `configs/00-defaults/00-config.toml`

---

### 4. LLM Provider Circuit Breaker

**Category:** Reliability  
**Priority:** High  
**Effort:** M (1-2 days)

#### Current State

[`LLMManager`](../lib/ai/manager.py:17) supports provider fallback, but there is no circuit breaker, dood! If the primary provider is consistently returning errors (5XX, timeouts), every single message still hits it and waits for a timeout before falling back, dood! Under heavy load this creates a thundering-herd retry storm, dood!

#### Proposed Improvement

Implement a simple half-open circuit breaker per provider, dood!

```python
# lib/ai/circuit_breaker.py
from enum import StrEnum

class CircuitState(StrEnum):
    """Circuit breaker state, dood!"""
    CLOSED = "closed"    # Normal operation
    OPEN = "open"        # Failing — skip this provider
    HALF_OPEN = "half_open"  # Probe to see if recovered

class ProviderCircuitBreaker:
    """Tracks provider health and opens/closes circuit, dood!"""

    def __init__(self, failureThreshold: int = 5, recoveryWindowSecs: float = 60.0):
        self.failureThreshold = failureThreshold
        self.recoveryWindowSecs = recoveryWindowSecs
        self._failureCount: int = 0
        self._openedAt: Optional[float] = None
        self._state: CircuitState = CircuitState.CLOSED

    def recordSuccess(self) -> None: ...
    def recordFailure(self) -> None: ...
    def isAvailable(self) -> bool: ...
```

Integrate into [`AbstractLLMProvider`](../lib/ai/abstract.py) so each provider instance has a circuit breaker, dood!

#### Expected Impact

- Fallback kicks in within 1 failed request instead of after timeout cascade, dood!
- Reduces mean LLM response latency by up to 80% when primary provider is degraded, dood!
- Self-healing: circuit closes automatically after recovery window, dood!

#### Implementation Notes

- Configurable thresholds per-provider via TOML `[models.providers.<name>.circuit-breaker]`
- Add circuit state to Prometheus metrics (suggestion #1)

#### Affected Files

- `lib/ai/circuit_breaker.py` (new)
- [`lib/ai/abstract.py`](../lib/ai/abstract.py)
- [`lib/ai/manager.py`](../lib/ai/manager.py)
- [`internal/services/llm/service.py`](../internal/services/llm/service.py)

---

### 5. Graceful Degradation on DB Errors

**Category:** Reliability  
**Priority:** High  
**Effort:** M (1-2 days)

#### Current State

[`DatabaseWrapper`](../internal/database/wrapper.py) raises raw `sqlite3.OperationalError` and `sqlite3.IntegrityError` exceptions, dood! In [`HandlersManager`](../internal/bot/common/handlers/manager.py) there is no catch-all error recovery for DB failures in the handler chain, dood! A transient SQLite `database is locked` error would crash the entire message processing coroutine, dood!

#### Proposed Improvement

1. Wrap all `DatabaseWrapper` public methods with a retry decorator for transient errors, dood!

```python
# internal/database/retry.py
import functools
import sqlite3
import time

TRANSIENT_ERRORS: Tuple[int, ...] = (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)

def withRetry(maxAttempts: int = 3, delayMs: float = 50.0):
    """Retry decorator for transient SQLite errors, dood!"""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(maxAttempts):
                try:
                    return fn(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if attempt < maxAttempts - 1:
                        time.sleep(delayMs / 1000.0 * (2 ** attempt))
                        continue
                    raise
        return wrapper
    return decorator
```

2. Add a `try/except` fallback in `HandlersManager._processMessageRec()` that sends a user-friendly error message instead of silently dropping it, dood!

#### Expected Impact

- Eliminates silent message drops under high DB contention, dood!
- Users receive "I'm having trouble right now, try again in a moment" instead of silence, dood!

#### Affected Files

- [`internal/database/wrapper.py`](../internal/database/wrapper.py)
- [`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py)
- `internal/database/retry.py` (new)

---

## Performance

---

### 6. Async SQLite Connection Pooling

**Category:** Performance  
**Priority:** High  
**Effort:** L (3-5 days)

#### Current State

[`DatabaseWrapper`](../internal/database/wrapper.py) uses `threading.local()` or a custom pool for synchronous SQLite connections, dood! All DB calls run in the same thread as the asyncio event loop, blocking it during I/O, dood! With 15+ tables and 3000+ lines of wrapper code, the DB layer is the most likely bottleneck under concurrent messages, dood!

#### Proposed Improvement

Migrate DB calls to use `aiosqlite` with an async context manager, dood! Wrap all database method calls with `asyncio.to_thread()` as an intermediate step that unblocks the event loop without a full rewrite, dood!

```python
# Intermediate approach — minimal invasiveness
import asyncio

class DatabaseWrapper:
    async def getChatMessageAsync(self, chatId: int, messageId: MessageIdType) -> Optional[ChatMessageDict]:
        """Async wrapper using thread pool, dood!"""
        return await asyncio.to_thread(self.getChatMessageByMessageId, chatId, messageId)
```

Long-term: migrate `_getConnection()` to use `aiosqlite.connect()`, dood!

#### Expected Impact

- Removes event-loop blocking during DB reads — up to 3x throughput improvement for I/O-heavy workloads, dood!
- Enables true concurrent message processing, dood!

#### Implementation Notes

- Add `aiosqlite` to `requirements.txt`
- Connection pooling config: `pool-size` already exists in DB config (section 8.2)
- Test with `pytest-asyncio` and the `testDatabase` fixture

#### Affected Files

- [`internal/database/wrapper.py`](../internal/database/wrapper.py)
- [`internal/bot/common/handlers/base.py`](../internal/bot/common/handlers/base.py)
- All handlers that call `self.db.*` directly

---

### 7. Database Query Index Audit

**Category:** Performance  
**Priority:** High  
**Effort:** S (hours)

#### Current State

The migrations in [`internal/database/migrations/versions/`](../internal/database/migrations/versions/) create tables but some high-frequency query patterns may lack covering indexes, dood! Common queries like `getChatMessagesSince(chatId, since)` or `getSpamMessagesByUserId(chatId, userId)` filter on multiple columns, dood! Without composite indexes these do full table scans as data grows, dood!

#### Proposed Improvement

Run `EXPLAIN QUERY PLAN` on the top 10 most frequent queries and add composite indexes where needed, dood!

```sql
-- High-frequency multi-column lookups that need composite indexes:
CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_thread_ts
    ON chat_messages(chat_id, thread_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_spam_messages_chat_user
    ON spam_messages(chat_id, user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_delayed_tasks_status_ts
    ON delayed_tasks(status, delayed_until ASC);

CREATE INDEX IF NOT EXISTS idx_media_attachments_group
    ON media_attachments(media_group_id, created_at DESC);
```

Create a migration for each batch, dood!

#### Expected Impact

- Query time for common patterns drops from O(N) to O(log N), dood!
- Critical for group chats with 10,000+ messages in history, dood!
- Zero application code changes required, dood!

#### Affected Files

- `internal/database/migrations/versions/NNN_add_composite_indexes.py` (new migration)

---

## Security

---

### 11. Secrets in Environment Variables

**Category:** Security  
**Priority:** Critical  
**Effort:** S (hours)

#### Current State

Bot token and API keys are stored directly in TOML config files, dood! The [`ConfigManager`](../internal/config/manager.py) reads raw values from TOML with `getBotToken()` which calls `sys.exit()` if missing, but provides no environment variable interpolation, dood! This means tokens can accidentally be committed to version control, dood!

#### Proposed Improvement

Add environment variable interpolation to [`ConfigManager._mergeConfigs()`](../internal/config/manager.py) — resolve `${ENV_VAR}` placeholders at load time, dood!

```python
# internal/config/manager.py
import re
import os

ENV_VAR_PATTERN: re.Pattern = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

def _resolveEnvVars(self, value: Any) -> Any:
    """Resolve ${ENV_VAR} placeholders in config values, dood!

    Args:
        value: Config value, may contain ${ENV_VAR} tokens

    Returns:
        Value with env vars substituted
    """
    if isinstance(value, str):
        def replaceEnvVar(match: re.Match) -> str:
            envName: str = match.group(1)
            return os.environ.get(envName, match.group(0))
        return ENV_VAR_PATTERN.sub(replaceEnvVar, value)
    elif isinstance(value, dict):
        return {k: self._resolveEnvVars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [self._resolveEnvVars(item) for item in value]
    return value
```

Update example configs to use `${BOT_TOKEN}` placeholders, dood!

#### Expected Impact

- Enables secrets management best practices (Docker secrets, k8s Secrets, HashiCorp Vault), dood!
- Prevents accidental token exposure in git history, dood!

#### Affected Files

- [`internal/config/manager.py`](../internal/config/manager.py)
- `configs/common/00-config.toml`
- `configs/00-defaults/00-config.toml`

---

### 9. Per-User Rate Limiting

**Category:** Security  
**Priority:** High  
**Effort:** M (1-2 days)

#### Current State

[`RateLimiterManager`](../lib/rate_limiter/manager.py:12) applies limits per named queue (e.g., `yandex-search`, `openweathermap`), but these are global limits, not per-user, dood! A single user can flood the bot with commands and consume the full global API budget, starving other users, dood!

#### Proposed Improvement

Extend [`SlidingWindowRateLimiter`](../lib/rate_limiter/sliding_window.py) to support per-key tracking (it already has a `key` parameter in `applyLimit()` but the window storage needs per-key state), dood!

```python
# lib/rate_limiter/sliding_window.py
class SlidingWindowRateLimiter:
    def __init__(self, maxRequests: int = 10, windowSeconds: float = 60.0, perKey: bool = False):
        """Support per-key rate windows (for per-user limits), dood!"""
        self._perKey = perKey
        self._keyWindows: Dict[str, Deque[float]] = {}  # key -> timestamps

    async def applyLimit(self, queue: str = "default", key: Optional[str] = None) -> None:
        """Apply limit — if key is provided and perKey=True, use per-key window, dood!"""
```

In LLM / weather / search handlers, pass `key=str(userId)` to rate limiting, dood!

```python
# In WeatherHandler or YandexSearchHandler:
await self.rateLimiterManager.applyLimit("openweathermap", key=str(ensuredMessage.sender.id))
```

#### Expected Impact

- Prevents single-user API budget exhaustion, dood!
- Configurable via TOML: `per-user = true` + `per-user-limit = 5` per queue, dood!

#### Affected Files

- [`lib/rate_limiter/sliding_window.py`](../lib/rate_limiter/sliding_window.py)
- [`lib/rate_limiter/manager.py`](../lib/rate_limiter/manager.py)
- [`internal/bot/common/handlers/weather.py`](../internal/bot/common/handlers/weather.py)
- [`internal/bot/common/handlers/yandex_search.py`](../internal/bot/common/handlers/yandex_search.py)
- [`internal/bot/common/handlers/llm_messages.py`](../internal/bot/common/handlers/llm_messages.py)

---

### 10. Admin Command Permission Hardening

**Category:** Security  
**Priority:** High  
**Effort:** M (1-2 days)

#### Current State

`CommandPermission.OWNER` restricts some commands, but the check in [`BaseBotHandler`](../internal/bot/common/handlers/base.py) relies on `bot_owners` config list which includes both usernames (strings) and user IDs (ints), dood! There is no cryptographic verification of admin actions, and the spam action button uses a `spam-button-salt` HMAC but this pattern isn't applied to admin commands, dood!

#### Proposed Improvement

1. Normalize `bot_owners` at startup — resolve usernames to user IDs via the Telegram API and cache the result, preventing username-squatting attacks, dood!
2. Add an audit log table `admin_actions` to the database for all owner/admin commands, dood!
3. Add 2FA confirmation for destructive admin commands via callback buttons, dood!

```python
# Database migration: admin_actions table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS admin_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        command TEXT NOT NULL,
        args TEXT,
        result TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")
```

#### Expected Impact

- Prevents privilege escalation via username reassignment, dood!
- Full audit trail for compliance/debugging, dood!
- Destructive operations require explicit confirmation, dood!

#### Affected Files

- [`internal/bot/common/handlers/base.py`](../internal/bot/common/handlers/base.py)
- [`internal/database/wrapper.py`](../internal/database/wrapper.py)
- `internal/database/migrations/versions/NNN_add_admin_actions.py` (new)
- [`main.py`](../main.py)

---

### 27. Input Sanitization & Max Message Length Guard

**Category:** Security  
**Priority:** Medium  
**Effort:** S (hours)

#### Current State

[`MessagePreprocessorHandler`](../internal/bot/common/handlers/message_preprocessor.py) saves all incoming messages, but there is no guard on message length before passing to LLM or storing in DB, dood! An adversary could send 100KB messages to exhaust LLM token budgets or inflate DB size, dood!

#### Proposed Improvement

Add a `MAX_INPUT_LENGTH` constant and truncation/rejection logic in the preprocessor, dood!

```python
# internal/bot/common/handlers/message_preprocessor.py
MAX_INPUT_LENGTH: int = 4096  # chars, configurable via TOML

if len(ensuredMessage.messageText) > MAX_INPUT_LENGTH:
    logger.warning(f"Message too long ({len(ensuredMessage.messageText)} chars), truncating, dood!")
    ensuredMessage = ensuredMessage._replace(messageText=ensuredMessage.messageText[:MAX_INPUT_LENGTH] + "…")
```

Add config key `[bot] max-input-length = 4096`, dood!

#### Expected Impact

- Prevents token-budget exhaustion attacks on LLM providers, dood!
- Caps DB storage growth from malicious large messages, dood!

#### Affected Files

- [`internal/bot/common/handlers/message_preprocessor.py`](../internal/bot/common/handlers/message_preprocessor.py)
- [`internal/config/manager.py`](../internal/config/manager.py)
- `configs/00-defaults/bot-defaults.toml`

---

## Features

---

### 8. LLM Response Streaming

**Category:** Feature / UX  
**Priority:** High  
**Effort:** L (3-5 days)

#### Current State

[`LLMService.generateText()`](../internal/services/llm/service.py:80) waits for the full LLM response before sending it to the user, dood! For long responses (summaries, code generation) users see nothing for 5-30 seconds, dood! Both OpenAI and OpenRouter APIs support SSE streaming, dood!

#### Proposed Improvement

Add streaming support to [`AbstractModel`](../lib/ai/abstract.py) and implement it in the OpenAI-based providers, dood!

```python
# lib/ai/abstract.py — new abstract method
from collections.abc import AsyncGenerator

class AbstractModel:
    async def generateTextStream(
        self,
        messages: Sequence[ModelMessage],
        tools: Optional[List[LLMAbstractTool]] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream text response token-by-token, dood!

        Yields:
            Partial text chunks as they arrive from the provider
        """
        raise NotImplementedError
```

In [`LLMMessageHandler`](../internal/bot/common/handlers/llm_messages.py) accumulate chunks and update the bot message every ~500ms using `editMessage()`, dood!

```python
async def _streamResponse(self, ensuredMessage: EnsuredMessage, model: AbstractModel) -> str:
    """Stream LLM response with live message editing, dood!"""
    sentMessage: Optional[MessageIdType] = None
    buffer: str = ""
    lastUpdate: float = 0.0

    async for chunk in model.generateTextStream(messages):
        buffer += chunk
        now: float = time.monotonic()
        if now - lastUpdate > 0.5:  # Update every 500ms
            if sentMessage is None:
                sentMessage = await self.sendMessage(ensuredMessage, messageText=buffer + "▋")
            else:
                await self.editMessage(ensuredMessage, messageId=sentMessage, newText=buffer + "▋")
            lastUpdate = now

    return buffer
```

#### Expected Impact

- Users see first tokens in < 500ms instead of waiting 10-30s, dood!
- Dramatically better perceived performance for long responses, dood!
- Aligns with modern UX expectations from ChatGPT/Claude interfaces, dood!

#### Implementation Notes

- Configurable via `[bot] streaming-enabled = true` in TOML
- Graceful fallback to non-streaming for providers that don't support it
- Telegram `editMessage` API has rate limits — respect them

#### Affected Files

- [`lib/ai/abstract.py`](../lib/ai/abstract.py)
- [`lib/ai/providers/basic_openai_provider.py`](../lib/ai/providers/basic_openai_provider.py)
- [`lib/ai/providers/openrouter_provider.py`](../lib/ai/providers/openrouter_provider.py)
- [`internal/services/llm/service.py`](../internal/services/llm/service.py)
- [`internal/bot/common/handlers/llm_messages.py`](../internal/bot/common/handlers/llm_messages.py)
- [`internal/bot/common/bot.py`](../internal/bot/common/bot.py)

---

### 12. User Preferences & Per-Chat Personas

**Category:** Feature  
**Priority:** Medium  
**Effort:** L (3-5 days)

#### Current State

Chat settings exist via [`ChatSettingsKey`](../internal/bot/models/chat_settings.py) but there is no UI for users to manage personal preferences (language, response style, preferred model) distinct from the group-level settings set by admins, dood! Every user in a group shares the same LLM persona/system prompt, dood!

#### Proposed Improvement

Add a `UserPreferences` data store (new DB table + cache layer) and a `/preferences` command, dood!

```python
# New table: user_preferences
# Fields: user_id, key, value, updated_at

# New ChatSettingsKey values:
class ChatSettingsKey(StrEnum):
    # ... existing keys ...
    USER_LANGUAGE = "user_language"
    USER_RESPONSE_STYLE = "user_response_style"   # "concise" | "detailed" | "casual"
    USER_PREFERRED_MODEL = "user_preferred_model"
```

In [`LLMMessageHandler`](../internal/bot/common/handlers/llm_messages.py) merge user preferences on top of chat settings when building the system prompt, dood!

#### Expected Impact

- Individual users can customize their experience without affecting the group, dood!
- Enables premium-tier features (personal model selection for paid users), dood!

#### Affected Files

- `internal/database/migrations/versions/NNN_add_user_preferences.py` (new)
- [`internal/database/wrapper.py`](../internal/database/wrapper.py)
- [`internal/services/cache/service.py`](../internal/services/cache/service.py)
- `internal/bot/common/handlers/preferences.py` (new handler)
- [`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py)

---

### 13. Scheduled Messages & Reminders

**Category:** Feature  
**Priority:** Medium  
**Effort:** M (1-2 days)

#### Current State

[`QueueService`](../internal/services/queue_service/service.py) already has `DelayedTaskFunction.SEND_MESSAGE` and a working delayed task scheduler, dood! But there is no user-facing command to create reminders, dood! The infrastructure is there — only the handler is missing, dood!

#### Proposed Improvement

Add a `/remind` command that creates a delayed task via `QueueService`, dood!

```python
# Usage: /remind 1h Call mom
# Usage: /remind 2026-04-19 10:00 Team standup

@commandHandlerV2(
    commands=("remind",),
    shortDescription="- set a reminder",
    helpMessage="Set a reminder. Usage: /remind <duration|datetime> <text>",
    visibility={CommandPermission.DEFAULT},
    availableFor={CommandPermission.DEFAULT},
    helpOrder=CommandHandlerOrder.NORMAL,
    category=CommandCategory.TOOLS,
)
async def remindCommand(self, ensuredMessage: EnsuredMessage, command: str, args: str, ...) -> None:
    """Parse reminder time and create a delayed task, dood!"""
    delayedUntil, reminderText = self._parseReminderArgs(args)
    await queueService.addDelayedTask(
        delayedUntil=delayedUntil,
        function=DelayedTaskFunction.SEND_MESSAGE,
        kwargs={"chat_id": ensuredMessage.recipient.id, "text": f"⏰ Reminder: {reminderText}"},
    )
```

#### Expected Impact

- High-value user-facing feature with minimal new infrastructure, dood!
- Leverages existing `DelayedTaskFunction.SEND_MESSAGE` — pure handler work, dood!

#### Affected Files

- `internal/bot/common/handlers/reminders.py` (new handler)
- [`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py)

---

### 21. LLM Cost Tracking & Budget Alerts

**Category:** Feature  
**Priority:** Medium  
**Effort:** M (1-2 days)

#### Current State

[`ModelRunResult`](../lib/ai/models.py) likely contains token usage data (input/output tokens) from provider responses, but there is no aggregation or cost calculation, dood! Operators have no way to know monthly LLM costs until they receive a provider invoice, dood!

#### Proposed Improvement

Add token tracking to `ModelRunResult` and a cost calculation module, dood!

```python
# internal/analytics/cost_tracker.py
MODEL_COSTS_PER_1K_TOKENS: Dict[str, Dict[str, float]] = {
    "gpt-4o": {"input": 0.0025, "output": 0.010},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
}

class CostTracker:
    """Tracks LLM token usage and estimated costs, dood!"""

    def recordUsage(self, modelId: str, inputTokens: int, outputTokens: int, chatId: int) -> None: ...
    def getDailyCost(self) -> float: ...
    def getMonthlyCost(self) -> float: ...
    def getAlertThreshold(self) -> Optional[float]: ...  # From config
```

Trigger `DelayedTaskFunction.CRON_JOB` daily to post cost summary to admin chat, dood!

#### Expected Impact

- Early warning before unexpected provider bills, dood!
- Per-chat cost breakdown enables fair-use tiering, dood!

#### Affected Files

- `internal/analytics/cost_tracker.py` (new)
- [`lib/ai/models.py`](../lib/ai/models.py)
- [`internal/services/llm/service.py`](../internal/services/llm/service.py)
- [`internal/database/wrapper.py`](../internal/database/wrapper.py)

---

## Developer Experience (DX)

---

### 15. Hot-Reload Configuration

**Category:** DX  
**Priority:** Medium  
**Effort:** M (1-2 days)

#### Current State

Configuration requires a full bot restart to take effect, dood! During development, changing a model's temperature or enabling a feature flag requires killing and restarting the process and waiting for DB migrations + Telegram long-poll reconnection, dood!

#### Proposed Improvement

Add a `SIGHUP` handler that reloads non-structural config keys (models, rate limits, feature flags) without restarting, dood!

```python
# main.py
import signal

def setupSignalHandlers(self) -> None:
    """Set up UNIX signal handlers for graceful operations, dood!"""
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGHUP, self._onSigHup)
    loop.add_signal_handler(signal.SIGTERM, self._onSigTerm)

def _onSigHup(self) -> None:
    """Reload non-structural config on SIGHUP, dood!"""
    logger.info("SIGHUP received — reloading configuration, dood!")
    self.configManager.reload()
    self.llmManager.reloadModels(self.configManager.getModelsConfig())
    asyncio.create_task(self.rateLimiterManager.loadConfig(self.configManager.getRateLimiterConfig()))
```

#### Expected Impact

- Config changes apply in < 1s without reconnection delay, dood!
- Development iteration speed improvement of ~10x for config tuning, dood!
- Zero downtime for production config updates, dood!

#### Affected Files

- [`main.py`](../main.py)
- [`internal/config/manager.py`](../internal/config/manager.py)
- [`lib/ai/manager.py`](../lib/ai/manager.py)

---

### 16. Development Seed & Fixture Mode

**Category:** DX  
**Priority:** Medium  
**Effort:** S (hours)

#### Current State

Starting a fresh development environment requires manually sending messages to populate the bot's DB state, dood! There is no seed data script, dood! Testing handler behavior requires an actual Telegram account and sending messages, dood!

#### Proposed Improvement

Add a `make seed` target that populates a dev DB with realistic fixture data, dood!

```python
# scripts/seed_dev_db.py
"""Seed development database with realistic test data, dood!"""

from internal.database import Database
from tests.fixtures.seed_data import SEED_CHATS, SEED_USERS, SEED_MESSAGES

def seedDatabase(dbPath: str = "./dev_data.db") -> None:
    """Populate dev database with test fixtures, dood!"""
    db = DatabaseWrapper(...)
    for chat in SEED_CHATS:
        db.saveChatInfo(...)
    for user in SEED_USERS:
        db.updateChatUser(...)
    for message in SEED_MESSAGES:
        db.saveChatMessage(...)
```

Add `make seed` and `make reset-dev` targets to [`Makefile`](../Makefile), dood!

#### Expected Impact

- New developer onboarding time reduced from hours to minutes, dood!
- Consistent dev environment state for reproducing bugs, dood!

#### Affected Files

- `scripts/seed_dev_db.py` (new)
- [`Makefile`](../Makefile)
- `tests/fixtures/seed_data.py` (new)

---

### 25. Makefile: Watch Mode & Parallel CI Jobs

**Category:** DX  
**Priority:** Low  
**Effort:** S (hours)

#### Current State

The [`Makefile`](../Makefile) has `test`, `lint`, `format` targets but no watch mode for auto-running tests on file changes, dood! CI runs all checks serially, dood! There is no `make ci` target that runs lint + tests in parallel, dood!

#### Proposed Improvement

Add `make watch` (using `watchdog` or `entr`) and `make ci` (parallel jobs), dood!

```makefile
# Watch mode — auto-run tests on file changes
watch: venv
	@echo "👁 Watching for changes, dood!"
	find . -name "*.py" -not -path "./venv/*" | entr -c $(PYTEST) --tb=short $(ARGS)

# Parallel CI: lint and tests at the same time
ci: venv
	@echo "🚀 Running CI checks in parallel, dood!"
	$(MAKE) lint & $(MAKE) test & wait
	@echo "✅ CI complete, dood!"

# Type check only (fast feedback)
typecheck: venv
	$(PYRIGHT)
```

#### Expected Impact

- TDD feedback loop reduced from 30s to < 5s (watch mode), dood!
- CI pipeline ~40% faster with parallel lint+test, dood!

#### Affected Files

- [`Makefile`](../Makefile)

---

### 26. Automated Dependency Updates via Renovate/Dependabot

**Category:** DX  
**Priority:** Low  
**Effort:** S (hours)

#### Current State

Dependencies are pinned in `requirements.txt` without a policy for updates, dood! There is a `make list-outdated-requirements` target but it must be run manually, dood! Security vulnerabilities in dependencies go undetected until manually checked, dood!

#### Proposed Improvement

Add a `renovate.json` or `.github/dependabot.yml` configuration for automated PRs on dependency updates, dood!

```json
// renovate.json
{
  "extends": ["config:base"],
  "packageRules": [
    {
      "matchPackagePatterns": ["*"],
      "rangeStrategy": "pin",
      "automerge": false,
      "schedule": ["every weekend"]
    }
  ],
  "vulnerabilityAlerts": {
    "enabled": true,
    "labels": ["security"]
  }
}
```

Also add `pip-audit` to the `make lint` pipeline for vulnerability scanning, dood!

#### Expected Impact

- Security vulnerabilities detected within days of CVE publication, dood!
- Dependency rot prevented with weekly update proposals, dood!

#### Affected Files

- `renovate.json` (new) or `.github/dependabot.yml` (new)
- [`Makefile`](../Makefile)

---

## Testing

---

### 17. Performance / Load Tests

**Category:** Testing  
**Priority:** Medium  
**Effort:** M (1-2 days)

#### Current State

The test suite has 1185+ tests but they are all unit/integration tests, dood! There are pytest markers `@pytest.mark.performance` and `@pytest.mark.benchmark` defined in `pyproject.toml` but no tests use them, dood! The benchmark suite is empty, dood!

#### Proposed Improvement

Add `pytest-benchmark` tests for the critical path: message parsing → handler chain → LLM call (mocked), dood!

```python
# tests/performance/test_handler_throughput.py
"""Performance benchmarks for the handler chain, dood!"""
import pytest

class TestHandlerChainPerformance:
    """Benchmark handler chain throughput, dood!"""

    @pytest.mark.benchmark(group="handler-chain")
    def testMessageProcessingThroughput(self, benchmark, mockHandlersManager, mockEnsuredMessage):
        """Handler chain should process 1000 messages/s with mocked LLM, dood!"""
        result = benchmark(mockHandlersManager.processMessage, mockEnsuredMessage)
        assert result is not None

    @pytest.mark.benchmark(group="database")
    def testDbWriteThroughput(self, benchmark, testDatabase):
        """Database should handle 5000 message saves/s, dood!"""
        benchmark(testDatabase.saveChatMessage, chatId=1, ...)
```

Add `make benchmark` target to [`Makefile`](../Makefile), dood!

#### Expected Impact

- Regressions in throughput caught before deployment, dood!
- Establishes baseline: "message processing must be < 5ms P99", dood!

#### Affected Files

- `tests/performance/` (new directory)
- `tests/performance/test_handler_throughput.py` (new)
- `tests/performance/test_db_performance.py` (new)
- [`Makefile`](../Makefile)
- `pyproject.toml`

---

### 18. Chaos / Fault-Injection Tests

**Category:** Testing  
**Priority:** Medium  
**Effort:** M (1-2 days)

#### Current State

Tests mock external dependencies with `Mock`/`AsyncMock` that always succeed, dood! There are no tests for failure scenarios: LLM timeout, DB lock, rate limiter exhaustion, provider returning 500, dood! The reliability improvements (circuit breaker, retry) proposed above have no test coverage, dood!

#### Proposed Improvement

Add a `ChaosProxy` that intercepts service calls and injects configurable failures, dood!

```python
# tests/chaos/chaos_proxy.py
class ChaosProxy:
    """Wraps a service and injects configurable failures, dood!

    Attributes:
        failureRate: Float 0.0-1.0 chance of failure per call
        failureType: Exception class to raise
    """

    def __init__(self, target: Any, failureRate: float = 0.5, failureType: type = Exception):
        self._target = target
        self._failureRate = failureRate
        self._failureType = failureType

    def __getattr__(self, name: str) -> Any:
        originalMethod = getattr(self._target, name)
        if callable(originalMethod):
            return self._makeFailingMethod(originalMethod)
        return originalMethod

    def _makeFailingMethod(self, method: Callable) -> Callable:
        """Wrap method to randomly fail, dood!"""
        import random
        def wrapper(*args, **kwargs):
            if random.random() < self._failureRate:
                raise self._failureType("Chaos proxy injected failure, dood!")
            return method(*args, **kwargs)
        return wrapper
```

#### Expected Impact

- Verifies all error recovery paths actually work, dood!
- Catches regressions in circuit breaker / retry logic, dood!

#### Affected Files

- `tests/chaos/` (new directory)
- `tests/chaos/chaos_proxy.py` (new)
- `tests/chaos/test_llm_failures.py` (new)
- `tests/chaos/test_db_failures.py` (new)

---

### 19. End-to-End Integration Test Suite

**Category:** Testing  
**Priority:** Medium  
**Effort:** L (3-5 days)

#### Current State

The `tests/integration/` directory exists but is sparse, dood! There is no full bot lifecycle test that: starts the bot, sends a message via Telegram Test API, and asserts the bot responds correctly, dood! Current tests test components in isolation but not the full pipeline, dood!

#### Proposed Improvement

Add an E2E test harness using Telegram's test server credentials, dood!

```python
# tests/integration/test_e2e_bot.py
"""End-to-end bot integration tests using Telegram test API, dood!"""
import pytest

@pytest.mark.integration
@pytest.mark.slow
class TestBotE2E:
    """Full bot pipeline tests against Telegram test server, dood!"""

    async def testEchoFlow(self, testBotClient, testChatId):
        """Bot should respond to /help within 5 seconds, dood!"""
        await testBotClient.sendMessage(testChatId, "/help")
        response = await testBotClient.waitForMessage(testChatId, timeout=5.0)
        assert response is not None
        assert "help" in response.text.lower()
```

E2E tests run via `make test-e2e` (separate from the main test suite to avoid Telegram API quota usage), dood!

#### Expected Impact

- Catches integration regressions that unit tests miss, dood!
- Validates the full handler chain with real message format, dood!

#### Affected Files

- `tests/integration/test_e2e_bot.py` (new)
- `tests/integration/conftest.py` (new)
- [`Makefile`](../Makefile)

---

## Scalability

---

### 22. Plugin / Custom Handler Hot-Load

**Category:** Scalability  
**Priority:** Low  
**Effort:** XL (1+ week)

#### Current State

Custom handlers are loaded at startup via TOML config (`[bot.custom-handlers]`), dood! Adding or removing a custom handler requires a full restart, dood! There is no plugin discovery mechanism — custom handlers must be Python modules in the known import path, dood!

#### Proposed Improvement

Implement a plugin loader using `importlib` and a watch thread for hot-reloading custom handler modules, dood!

```python
# internal/bot/common/handlers/plugin_loader.py
class PluginLoader:
    """Discovers and hot-loads custom handler plugins, dood!

    Attributes:
        pluginsDir: Directory to scan for plugin modules
        loadedPlugins: Dict of plugin name to handler instance
    """

    def __init__(self, pluginsDir: str, handlersManager: "HandlersManager"):
        self.pluginsDir = pluginsDir
        self._handlersManager = handlersManager
        self._loadedPlugins: Dict[str, BaseBotHandler] = {}
        self._watcher: Optional[asyncio.Task] = None

    async def startWatching(self) -> None:
        """Watch plugins directory for changes and hot-reload, dood!"""

    async def loadPlugin(self, modulePath: str) -> Optional[BaseBotHandler]:
        """Load a single plugin module and instantiate its handler, dood!"""
```

#### Expected Impact

- Feature deployment without bot downtime, dood!
- Custom handlers developed independently from core bot, dood!

#### Affected Files

- `internal/bot/common/handlers/plugin_loader.py` (new)
- [`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py)
- `configs/00-defaults/00-config.toml`

---

### 23. Horizontal Scaling with Redis Queue Backend

**Category:** Scalability  
**Priority:** Low  
**Effort:** XL (1+ week)

#### Current State

[`QueueService`](../internal/services/queue_service/service.py) uses an in-process `asyncio.PriorityQueue`, dood! This is single-process only — running multiple bot instances for high availability requires each instance to independently receive and process updates, causing duplicate processing, dood!

#### Proposed Improvement

Abstract the queue backend behind an interface and add a Redis-backed implementation, dood!

```python
# internal/services/queue_service/backends/interface.py
class QueueBackendInterface(ABC):
    """Abstract queue backend for task persistence, dood!"""

    @abstractmethod
    async def push(self, task: DelayedTask) -> None: ...

    @abstractmethod
    async def pop(self) -> Optional[DelayedTask]: ...

    @abstractmethod
    async def peek(self) -> Optional[DelayedTask]: ...

# internal/services/queue_service/backends/redis_backend.py
class RedisQueueBackend(QueueBackendInterface):
    """Redis-backed queue using sorted sets for priority ordering, dood!"""
```

Config: `[queue] backend = "redis"`, `[queue.redis] url = "redis://localhost:6379/0"`, dood!

#### Expected Impact

- Enables active-active bot deployment (2+ instances behind a load balancer), dood!
- Delayed tasks survive process restart via Redis persistence, dood!

#### Affected Files

- `internal/services/queue_service/backends/` (new)
- [`internal/services/queue_service/service.py`](../internal/services/queue_service/service.py)
- [`internal/config/manager.py`](../internal/config/manager.py)

---

### 24. Admin Web Panel

**Category:** Feature  
**Priority:** Low  
**Effort:** XL (1+ week)

#### Current State

All administration is done via bot commands (e.g., `/configure`, `/dev`), dood! There is no web UI to view chat history, manage settings across multiple chats, view analytics, or manage the spam filter training data, dood!

#### Proposed Improvement

Add a minimal `FastAPI` admin panel (separate process, read-only DB access) with basic auth, dood!

```python
# admin/main.py
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBasic

adminApp = FastAPI(title="Gromozeka Admin Panel", docs_url=None)

@adminApp.get("/api/chats")
async def listChats(db: DatabaseWrapper = Depends(getReadOnlyDb)) -> List[ChatInfoDict]:
    """List all active chats, dood!"""
    return db.getAllGroupChats()

@adminApp.get("/api/stats")
async def getStats() -> Dict[str, Any]:
    """Get bot statistics, dood!"""
```

Simple read-only panel that connects to the existing SQLite file via the `readonly` database source, dood!

#### Expected Impact

- Non-technical operators can manage the bot without Telegram, dood!
- Faster debugging: browse chat history and settings in a web UI, dood!

#### Affected Files

- `admin/` (new directory)
- `admin/main.py` (new)
- `admin/requirements.txt` (new)
- [`Makefile`](../Makefile)

---

*All improvement suggestions reference actual code locations and are based on analysis of the Gromozeka codebase at commit state 2026-04-18, dood!*
*Cross-reference with [`docs/suggestions/refactoring.md`](refactoring.md) for structural changes and [`docs/suggestions/simplification.md`](simplification.md) for complexity reduction, dood!*

> **Status Review Note (2026-05-02):** All 27 improvement suggestions remain pending. No new features from this list have been implemented. However, references to `DatabaseWrapper` in suggestions #5, #6, #10, #12, and #21 should be updated to reference the new [`Database`](../../internal/database/database.py) class and its repositories, since the `wrapper.py` file no longer exists. The `f-string without f prefix` quick win referenced in the simplification doc's appendix (at [`lib/ai/manager.py:51`](../../lib/ai/manager.py:51)) is still present.
*Status review updated: 2026-05-02*
