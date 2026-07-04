# Max Webhook Support

Durable notes from the Max Messenger webhook receiver implementation. Read this when working on `internal/max_webhook_receiver/`, Max webhook infrastructure, `webhook_updates` table, or the two-process local-API-proxy architecture.

## Architecture

Plan: `docs/plans/max-webhook-support.md` (updated to local-API-proxy architecture). Two-process design: standalone aiohttp.web receiver (`internal/max_webhook_receiver/`) accepts POST /webhook from Max, stores in `webhook_updates` table, serves GET /updates in Max API format. Bot's `MaxBotClient` gets `basePollingUrl` override — polls receiver's local GET /updates instead of `platform-api2.max.ru`. Bot's polling loop unchanged.

### Key architecture decisions:
- `basePollingUrl` (not `baseUrl`) — overrides only `/updates` endpoint, not all API calls
- `_makeLocalRequest()` — separate httpx client, no proxy/TLS, fresh per poll
- `localReceiverToken` — optional auth for GET /updates (separate from bot token; bot token never leaked to receiver)
- Webhook registration (`POST /subscriptions`) owned by bot, configurable via `register-webhook`; shutdown unregistration (`DELETE /subscriptions`) gated by separate `unregister-webhook` key (independent of registration)
- `_webhookMode` flag on `MaxBotApplication` — gating, no new polling method
- **Separate datasource support**: `webhook-receiver.datasource` config routes webhook storage to a different DB provider; `WebhookUpdatesRepository` methods accept `dataSource` param (like `DelayedTasksRepository`)
- **Cleanup toggle**: `webhook-receiver.enable-cleanup` (default true) controls periodic deletion of old processed rows
- **Deferred processing** (`mark-on-subsequent-poll`, default true): at-least-once delivery — updates are NOT marked on first read. Bot passes compound marker `{received_at}|{id}` back on next poll to acknowledge. `markProcessedBeforeMarker` marks all rows at/below the marker. Immediate mode (`false`) preserves old at-most-once behavior. Marker filtering in `getUnprocessedUpdates` uses compound tiebreaker: `received_at > :markerTs OR (received_at = :markerTs AND id > :markerId)`. Marker timestamps round-trip through `datetime` for cross-DB string-format consistency.

## Files

### Files created (7):
- `configs/00-defaults/webhook-receiver.toml` — 16 config keys under `[webhook-receiver]`
- `internal/database/migrations/versions/migration_019_add_webhook_updates_table.py`
- `internal/database/repositories/webhook_updates.py` — `WebhookUpdatesRepository` (addUpdate, getUnprocessedUpdates with marker filtering, markProcessed with batchExecute atomicity, markProcessedBeforeMarker, deleteProcessedOlderThan)
- `internal/max_webhook_receiver/__init__.py`, `__main__.py`, `app.py` — aiohttp.web server with handleWebhook, handleGetUpdates (deferred/immediate modes), cleanupTask
- (Plus `WebhookUpdatesRow` TypedDict in `internal/database/models.py`)

### Files modified (6):
- `requirements.direct.txt` — `aiohttp==3.14.1` promoted from transitive to direct
- `lib/max_bot/client.py` — `_basePollingUrl` + `_localReceiverToken` in __slots__/__init__, `_makeLocalRequest()`, `getUpdates()` branch, `_getHttpClient()` conditional `verify=` fix
- `internal/bot/max/application.py` — webhook config reading, `basePollingUrl`/`localReceiverToken` pass-through, `setWebhook`/`deleteWebhook` lifecycle, placeholder-secret guard
- `internal/database/repositories/__init__.py` — export
- `internal/database/database.py` — wiring (5 locations: import, __slots__, annotation, docstring, init)

### Tests (5 files, 51 tests, all pass):
- `tests/database/repositories/test_webhook_updates.py` — 14 CRUD + marker tests
- `tests/max_webhook_receiver/test_app.py` — 19 endpoint tests (deferred/immediate modes, datasource, cleanup)
- `tests/max_webhook_receiver/test_main.py` — 3 secret-guard tests
- `tests/lib/max_bot/test_client_webhook.py` — 6 client routing tests
- `tests/bot/max/test_webhook_mode.py` — 14 config gating tests (unregister-webhook split)

## Post-review fixes (2026-07-01):
- `handleWebhook` now returns 500 (not 200) on DB write failure → Max retries the delivery; `logger.exception` corrected to `logger.error` (no active exception).
- Bad marker handling: narrow `except (ValueError, OverflowError, TypeError)` around `_parseMarker`; bad marker treated as no-marker poll (prevents 500 infinite-retry wedge).
- `getUpdates` type: `lastEventId: Optional[int]` → `Optional[Union[int, str]]` for compound string marker from local receiver.
- `_makeLocalRequest`: catches `json.JSONDecodeError` around `response.json()`; persistent `_localHttpClient` (lazy-create, reuse across polls, closed in `aclose()`).
- Secret validation moved to webhook-mode block: fires whenever `enabled=true`, not just on `register-webhook=true`. Empty secret rejected.
- `unregister-webhook` code default aligned with config default: `True` → `False`.
- `toKwargs` docstring cross-references `MaxBotClient._getHttpClient()` for SSL context routing.
- `buildMaxSslContext`: GOST skip counter + louder warning (TLS may fail if chain requires skipped certs).
- `from dateutil import parser` (was bare `import dateutil`) in `webhook_updates.py`.

## Known limitations (design tradeoffs, not bugs):
- DB write failure now returns 500 (Max retries); duplicate delivery still possible if `markProcessed` fails
- No cross-process migration guard — safe for 019 (idempotent DDL) but needs guard for future non-idempotent migrations
- Busy-polls SQLite every 0.5s during long-poll
- `_pollingLoop` marker advance on handler error defeats at-least-once in deferred mode (pre-existing, same as real Max API)
- `types` query param ignored by GET /updates (filtering at Max→receiver subscription layer)
- No deployment wiring (no `run.sh` / systemd config for receiver process)
- Unsubstituted `${MAX_WEBHOOK_SECRET}` placeholder rejected by guards in both `__main__.py` and `application.py`
