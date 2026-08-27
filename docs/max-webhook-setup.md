# Max Messenger webhook — deployment guide

Operator-facing guide for switching the Max bot from long-polling to webhook
delivery. This is the **two-process local-API-proxy** design (ADR-013): a
standalone **receiver** accepts Max's webhook POSTs and buffers them in the
`webhook_updates` table; the **bot** polls the receiver's local
`GET /updates` instead of `platform-api2.max.ru`.

> Prerequisite reading: [`docs/llm/architecture.md`](llm/architecture.md)
> ADR-013 and the durable implementation notes in
> [`docs/llm/memories/max-webhook-support.md`](llm/memories/max-webhook-support.md).

## How it fits together

```
Max API ──HTTPS POST /webhook──► 443 (nginx, TLS) ──► RECEIVER (127.0.0.1:8443, HTTP)
                                                          │  verifies X-Max-Bot-Api-Secret
                                                          │  stores raw body
                                                          ▼
                                 webhook_updates (own SQLite: webhook_receiver_data.db)
                                                          ▲
                                                          │ polls GET /updates
                                          BOT  ◄──────────┘  (base-polling-url)
                                            │
                                            └──► platform-api2.max.ru  (outbound: send replies)
```

- Both processes run on **the same machine**, each with **its own SQLite
  file**: the receiver is the sole writer of `webhook_updates` in its
  `webhook_receiver_data.db`; the bot keeps `bot_data.db` and never touches
  the receiver's database — it only consumes the receiver's `GET /updates`.
  Back up both files.
- The bot still talks to `platform-api2.max.ru` to **send** messages; webhook
  mode only replaces the **inbound** update channel (long-poll → webhook).
- Outbound TLS (bot → Max) uses the existing `[bot].max-ca-bundle` Минцифры
  bundle in `certs/max/`. **Inbound** TLS (Max → your webhook URL) is new
  infrastructure you set up here. Do not conflate the two.

## Prerequisites

- A public hostname resolving to this server, e.g. `bot.example.com`.
- A **CA-trusted TLS certificate** for that hostname on port 443. Let's Encrypt
  works; a Минцифры certificate is also accepted by Max. Max validates the full
  chain and CN/SAN.
- nginx (or equivalent reverse proxy) to terminate TLS on 443.
- OpenRC (Alpine Linux) for process supervision.
- The repo checked out at a fixed path, e.g. `/opt/gromozeka`, with `./venv`
  already created (`make install`).
- Both `.env.prod-max` and the `prod-max` config stack already working for the
  bot in long-polling mode (you are migrating a known-good deployment).

## Step 1 — generate the two secrets

You need **two** independent random secrets:

| Secret | Used by | Purpose |
| --- | --- | --- |
| `MAX_WEBHOOK_SECRET` | Max → receiver | Max sends it in the `X-Max-Bot-Api-Secret` header on every POST; the receiver verifies it. **Shared with Max at subscription time.** |
| `MAX_WEBHOOK_GET_UPDATES_SECRET` | bot → receiver | Authorizes the bot's local `GET /updates` polls. Defense-in-depth on top of the localhost-only bind. |

```sh
openssl rand -hex 32    # -> MAX_WEBHOOK_SECRET
openssl rand -hex 32    # -> MAX_WEBHOOK_GET_UPDATES_SECRET
```

## Step 2 — add the secrets to `.env.prod-max`

Append to your existing `.env.prod-max` (never commit this file):

```sh
MAX_WEBHOOK_SECRET="<paste secret 1>"
MAX_WEBHOOK_GET_UPDATES_SECRET="<paste secret 2>"
```

Both the receiver and the bot read this dotenv file — the bot through its
config stack, the receiver through its own config file (Step 4) — so both
pick the values up through `${VAR}` substitution.

## Step 3 — create the bot-side webhook config override

The defaults live in [`configs/00-defaults/webhook-receiver.toml`](../configs/00-defaults/webhook-receiver.toml)
with `enabled = false`. Do **not** edit the defaults — add a prod-max override.

Create **`configs/prod-max/20-webhook.toml`**:

```toml
[webhook-receiver]
# Turn webhook mode on for the bot. The receiver process always runs.
enabled = true

# PUBLIC https URL Max POSTs to. Must be port 443 with a CA-trusted cert.
# The path MUST match the reverse-proxy route (default webhook-path = "/webhook").
webhook-url = "https://bot.example.com/webhook"

# Authorize the bot's GET /updates polls (Step 1's second secret).
get-updates-secret = "${MAX_WEBHOOK_GET_UPDATES_SECRET}"

# Defaults kept as-is (shown for clarity):
# register-webhook       = true   # bot registers with Max on startup
# unregister-webhook     = false  # keep the Max subscription across bot restarts
# mark-on-subsequent-poll = true  # at-least-once delivery (re-deliver on crash)
# base-polling-url       = "http://127.0.0.1:8443"  # where the bot polls the receiver
```

`secret` is already `${MAX_WEBHOOK_SECRET}` in the defaults — no need to
redeclare it. Confirm the merged config resolves correctly before going live:

```sh
./venv/bin/python3 main.py --print-config \
  --dotenv-file .env.prod-max \
  --config-dir ./configs/00-defaults \
  --config-dir ./configs/common \
  --config-dir ./configs/prod \
  --config-dir ./configs/prod-max
```

In the `[webhook-receiver]` section, `enabled` must read `true`, `webhook-url`
must be your URL, and `secret` / `get-updates-secret` must show the **resolved**
values (not `${...}` placeholders). Do not let secret values hit a shared screen.

## Step 4 — create the receiver's own config file

The receiver does **not** read the bot's config stack. It reads a single TOML
file of its own (`--config`; cwd-relative default `webhook-receiver.toml`)
plus the shared dotenv, and it is **not** part of the bot's config
hierarchy — there is no multi-directory merge and no auto-added `00-defaults`
on the receiver side. A missing or unreadable file fails startup.

Create **`webhook-receiver.toml`** in the repo root (next to `.env.prod-max`):

```toml
# Max Messenger webhook receiver -- receiver process config file.
# Read DIRECTLY by the receiver (lib.max_webhook_receiver); NOT part of the
# bot's config stack. The bot's own copy of secret / get-updates-secret
# lives in configs/ (00-defaults + the prod-max override from Step 3) --
# keep the two in sync (drift = 403s). Missing non-secret keys fall back
# to the receiver's built-in defaults.
[webhook-receiver]
# Listen address for the webhook receiver HTTP server.
# Default: 127.0.0.1 (localhost only -- use a reverse proxy for external TLS).
listen-host = "127.0.0.1"

# Listen port for the webhook receiver HTTP server.
listen-port = 8443

# Shared secret for verifying webhook requests from Max (Step 1's first
# secret). Must MATCH the bot's [webhook-receiver].secret value.
# Max sends this in the X-Max-Bot-Api-Secret header on every webhook POST.
secret = "${MAX_WEBHOOK_SECRET}"

# URL path for the webhook POST endpoint from Max. Must match the path in
# the bot's webhook-url and the nginx location (Step 5).
webhook-path = "/webhook"

# Secret for the GET /updates endpoint (Step 1's second secret). Must MATCH
# the bot's [webhook-receiver].get-updates-secret value. If empty, the
# receiver skips the auth check and relies on the localhost binding.
get-updates-secret = "${MAX_WEBHOOK_GET_UPDATES_SECRET}"

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
# The receiver stores webhook updates in its OWN database file. It never
# runs the bot's migrations and never touches the bot's database
# (bot_data.db); it creates and self-heals the webhook_updates table and
# index on startup. Shape mirrors [database] in 00-config.toml exactly.
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

> **Dual-secret warning:** `secret` and `get-updates-secret` are maintained
> in BOTH the bot's config stack (Step 3) and this file. In the standard
> deployment both are `${VAR}`-substituted from the same `.env.prod-max`, so
> keep the variable references identical — a diverged pair yields 403s on
> webhook POSTs (Max → receiver) and on `GET /updates` (bot → receiver) with
> no other symptom.

## Step 5 — nginx reverse proxy

The receiver binds `127.0.0.1:8443` (plain HTTP, localhost-only). nginx
terminates TLS on 443 and forwards. Put this in your nginx config:

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name bot.example.com;

    # CA-trusted cert (Let's Encrypt or Минцифры). Max validates the full chain.
    ssl_certificate     /etc/letsencrypt/live/bot.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bot.example.com/privkey.pem;

    # Forward Max webhook POSTs to the receiver.
    # IMPORTANT: no trailing slash on proxy_pass — it must preserve the /webhook
    # URI so it matches the receiver's route (webhook-path = "/webhook").
    location /webhook {
        proxy_pass http://127.0.0.1:8443;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        # X-Max-Bot-Api-Secret passes through automatically; nginx forwards
        # unknown client headers to the upstream by default.
    }
}
```

Reload nginx: `nginx -t && nginx -s reload`.

> The `location` must match the path in `webhook-url` (`/webhook`), and that
> path must equal `webhook-path` (default `/webhook`). If you want a different
> public path, change `webhook-url`, the nginx `location`, **and**
> `webhook-path` together — they are three views of the same thing.

## Step 6 — OpenRC init script for the receiver

Create **`/etc/init.d/gromozeka-webhook-receiver`**:

```sh
#!/sbin/openrc-run

name="gromozeka-webhook-receiver"
description="Max Messenger webhook receiver for Gromozeka"

: ${GROMOZEKA_DIR:=/opt/gromozeka}
: ${GROMOZEKA_USER:=gromozeka}

# The receiver's OWN single config file + the shared dotenv (see Step 8).
# The receiver does NOT take --config-dir flags; its secrets must match
# the bot's config values (Step 3/Step 4).
command="${GROMOZEKA_DIR}/venv/bin/python3"
command_args="-m lib.max_webhook_receiver \
  --dotenv-file .env.prod-max \
  --config ./webhook-receiver.toml"

directory="${GROMOZEKA_DIR}"
command_user="${GROMOZEKA_USER}:${GROMOZEKA_USER}"
command_background=true
pidfile="/run/${RC_SVCNAME}.pid"
output_log="/var/log/${RC_SVCNAME}.log"
error_log="/var/log/${RC_SVCNAME}.log"
respawn_delay=5
respawn_max=0   # infinite respawns

depend() {
    need net localmount
    after firewall
    # Start before the bot so the receiver is live before the bot registers
    # the webhook with Max (which triggers immediate POSTs from Max).
    before gromozeka-bot
}
```

Make it executable and enable on boot:

```sh
chmod +x /etc/init.d/gromozeka-webhook-receiver
rc-update add gromozeka-webhook-receiver default
```

## Step 7 — (optional) OpenRC init script for the bot

If you already launch the bot some other way, keep doing so — just make sure
the **receiver starts first** (start it manually before the bot, or add an
ordering dependency). The bot only needs the receiver reachable once
`enabled = true`, and it registers the webhook on its own startup, so order
matters.

To run the bot under OpenRC as well, create **`/etc/init.d/gromozeka-bot`**:

```sh
#!/sbin/openrc-run

name="gromozeka-bot"
description="Gromozeka Max Messenger bot"

: ${GROMOZEKA_DIR:=/opt/gromozeka}
: ${GROMOZEKA_USER:=gromozeka}

# Direct main.py invocation, equivalent to `run.sh --env=prod-max` but WITHOUT
# the pip/git side effects (run those as a separate deploy step instead of on
# every service start).
command="${GROMOZEKA_DIR}/venv/bin/python3"
command_args="main.py \
  --dotenv-file .env.prod-max \
  --config-dir ./configs/00-defaults \
  --config-dir ./configs/common \
  --config-dir ./configs/prod \
  --config-dir ./configs/prod-max"

directory="${GROMOZEKA_DIR}"
command_user="${GROMOZEKA_USER}:${GROMOZEKA_USER}"
command_background=true
pidfile="/run/${RC_SVCNAME}.pid"
output_log="/var/log/${RC_SVCNAME}.log"
error_log="/var/log/${RC_SVCNAME}.log"
respawn_delay=5
respawn_max=0

depend() {
    need net localmount gromozeka-webhook-receiver
    after firewall
}
```

`need gromozeka-webhook-receiver` guarantees the receiver is up before the bot.
`before gromozeka-bot` on the receiver's `depend()` is the matching half of that
edge.

```sh
chmod +x /etc/init.d/gromozeka-bot
rc-update add gromozeka-bot default
```

> **Deploy note:** `run.sh` runs `pip install` on every start because
> `.env.prod-max` sets `DO_PIP_UPDATE="1"`. Under a supervisor, prefer updating
> the venv as an explicit deploy step (`./venv/bin/pip install -r requirements.txt`)
> and letting the service just run `main.py` — that is what the script above
> does.

## Step 8 — the two config surfaces (important)

Since the receiver extraction, the two processes load config **differently**:

- **Bot** — the usual flag stack, exactly what `run.sh --env=prod-max`
  assembles (it reads `CONFIGS` from `.env.prod-max` and expands it into
  `--config-dir` flags):

  ```
  --dotenv-file .env.prod-max
  --config-dir ./configs/00-defaults
  --config-dir ./configs/common
  --config-dir ./configs/prod
  --config-dir ./configs/prod-max
  ```

- **Receiver** — a single `--config` file (Step 4) plus the shared dotenv.
  It takes **no** `--config-dir` flags:

  ```
  --dotenv-file .env.prod-max
  --config ./webhook-receiver.toml
  ```

The receiver's file is not merged with anything and gets no auto-added
`00-defaults` — a missing or unreadable file fails startup. What MUST stay
in sync across the two surfaces: `secret`, `get-updates-secret` (drift =
403s), and the `webhook-path` ↔ `webhook-url` path segment.

## Step 9 — start in order and verify

First time, start manually in dependency order:

```sh
rc-service gromozeka-webhook-receiver start
# wait for "======== Running on http://127.0.0.1:8443 ========" in the log
rc-service gromozeka-bot start
```

Verify:

1. **Receiver is listening** — `tail -f /var/log/gromozeka-webhook-receiver.log`
   shows the aiohttp startup banner on `127.0.0.1:8443`.
2. **Bot registered the webhook** — the bot log shows the Max
   `POST /subscriptions` succeeding. On failure it raises `RuntimeError` at
   startup (usually a bad `webhook-url` or Max rejecting the cert).
3. **Max is delivering** — send a test message to the bot in Max. The receiver
   log shows incoming POSTs; the bot log shows the update being processed.
4. **End-to-end** — the bot replies. If replies work, the full loop is good.

## Docker deployment

The receiver ships its own container artifacts: a pinned standalone lockfile
([`lib/max_webhook_receiver/requirements.txt`](../lib/max_webhook_receiver/requirements.txt))
and a [`Dockerfile`](../lib/max_webhook_receiver/Dockerfile) under
`lib/max_webhook_receiver/`, plus a root [`.dockerignore`](../.dockerignore).
The lockfile pins mirror the root `requirements.txt` and cover only the
receiver's import closure — with one deliberate exception: `httpx==0.28.1` is
NOT in the root lockfile (inside the bot it is a shadowed transitive dep,
remapped to httpx2 by `alias_httpx()`), but the receiver runs without that
alias and sqlink hard-imports httpx, so the real package is pinned explicitly.

Build from the **repo root** so the `.dockerignore` applies:

```sh
docker build -f lib/max_webhook_receiver/Dockerfile -t gromozeka-webhook-receiver .
```

The commit-pinned `sqlink` dependency is fetched from a private git host. If
anonymous fetch fails, pass credentials via a BuildKit secret instead of
baking them into the image or layers:

```sh
printf 'machine git.sourcecraft.dev login <user> password <token>' > /tmp/netrc
docker build --secret id=netrc,src=/tmp/netrc \
    -f lib/max_webhook_receiver/Dockerfile -t gromozeka-webhook-receiver .
```

As of August 2026, anonymous fetches from `git.sourcecraft.dev` still succeed
with no credentials at all — confirmed in a real smoke build — so try the plain
build command above first and set up this netrc secret only if the `sqlink`
fetch fails authentication.

Run the image with the receiver config mounted read-only at
`/app/webhook-receiver.toml` and a named volume on `/data`; pass the secrets
as environment variables instead of mounting a `.env` file — the receiver
substitutes `${VAR}` from the process environment:

```sh
docker run -d --name gromozeka-webhook-receiver \
    -p 127.0.0.1:8443:8443 \
    -v ./webhook-receiver.docker.toml:/app/webhook-receiver.toml:ro \
    -v webhook-receiver-data:/data \
    -e MAX_WEBHOOK_SECRET -e MAX_WEBHOOK_GET_UPDATES_SECRET \
    gromozeka-webhook-receiver
```

> **colima note:** on colima-based Docker daemons, host paths outside `$HOME`
> (notably `/tmp`) are not shared into the VM — bind-mounting a config from
> such a path silently mounts an **empty directory** and crashes startup.
> Keep `webhook-receiver.docker.toml` under `$HOME`, or use `docker create` +
> `docker cp` + `docker start` instead of a bind mount.

Without `--dotenv-file`, the launcher still probes its default `/app/.env`, so
the boot log shows one `ERROR - File .env not found` line at startup — this is
harmless, since `${VAR}` substitution reads the real environment and the `-e`
values still work.

This TOML block is a **fragment**, not a complete file — start from the full
receiver config file from Step 4 and apply these two overrides; the fragment
alone is missing required `[webhook-receiver.database]` keys and would fail
DatabaseManager validation:

```toml
[webhook-receiver]
# The built-in default 127.0.0.1 is unreachable outside the container; publish
# the port (-p) against this bind.
listen-host = "0.0.0.0"

# listen-port, secret, get-updates-secret, webhook-path, cleanup keys:
# exactly as in Step 4 -- ${VAR} secrets still resolve, now from the
# container's environment variables.

[webhook-receiver.database.providers.default.parameters]
# Keep the database on the persisted volume.
dbPath = "/data/webhook_receiver_data.db"
```

Docker notes:

- **Dual-secret rule unchanged.** The bot's config stack and the receiver's
  file must carry identical `secret` / `get-updates-secret` values (Step 8);
  export both variables into the container environment (`-e`).
- **No built-in `HEALTHCHECK`.** Once `get-updates-secret` is set, every
  endpoint requires auth, so an unauthenticated probe would just collect 403s.
  Check liveness manually — any HTTP response proves the process is
  listening; `timeout=0` avoids the 90-second long poll:

  ```sh
  curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8443/updates?timeout=0&limit=1"
  # 200 when get-updates-secret is empty;
  # 403 when it is set (append -H "Authorization: $MAX_WEBHOOK_GET_UPDATES_SECRET" for a real 200)
  ```

- **Data persistence.** Run with the `/data` volume (declared by the image):
  SQLite WAL mode creates `-wal` / `-shm` sibling files next to `dbPath`, so
  the directory must stay writable by the container's non-root user
  (`uid 10001`). Never point `dbPath` at the bot's database (see Invariants).
- The image handles `SIGTERM` gracefully. Buffered updates are never lost —
  they are already persisted to SQLite when the shutdown signal arrives — but
  in-flight long-polls drain only up to aiohttp's 60-second shutdown timeout,
  then are dropped, exactly as on a plain restart (see Operations below).

## Operations

- **Config changes require restarting both processes.** Each loads the config
  at its own startup; there is no live reload. `rc-service gromozeka-webhook-receiver restart && rc-service gromozeka-bot restart`.
- **Bot-only restart is safe.** Because `unregister-webhook = false` (default),
  restarting the bot does **not** tear down the Max subscription — Max keeps
  POSTing, the receiver keeps buffering, and the bot catches up on the buffered
  rows when it comes back. This is the whole point of the two-process split.
- **Receiver restart drops in-flight long-polls** but not buffered updates:
  already-stored rows survive in `webhook_updates` and are served on the next
  `GET /updates`. Unbuffered (POST-in-flight-at-crash) updates are retried by
  Max (the receiver returns 500 on DB write failure, which triggers retry).
- **Roll back to long-polling:** set `enabled = false` in the override (or
  remove `configs/prod-max/20-webhook.toml`), restart the bot, and optionally
  stop the receiver. The bot reverts to polling `platform-api2.max.ru`.
  Consider also calling `DELETE /subscriptions` manually or setting
  `unregister-webhook = true` for one shutdown so Max stops POSTing.
- **Upgrading an existing webhook-mode deployment:** migration_029 drops the
  `webhook_updates` table from the main bot DB — any unconsumed buffered
  updates are **destroyed**. If mid-buffer updates matter, let the bot drain
  the queue (or pause Max webhooks / back up `bot_data.db`) before upgrading.
  After the upgrade the receiver owns that table exclusively in its own
  `webhook_receiver_data.db`, created and self-healed on startup.
- **Logs:** `/var/log/gromozeka-webhook-receiver.log`,
  `/var/log/gromozeka-bot.log` (or wherever your init scripts point
  `output_log`/`error_log`).

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Receiver exits immediately with "secret is not configured" | `MAX_WEBHOOK_SECRET` missing in `.env.prod-max`, or the dotenv path is wrong | Add the secret; confirm `--dotenv-file .env.prod-max` resolves from `directory`. |
| Receiver exits with "unresolved env var placeholder" | The `${VAR}` was not substituted (env var unset) | Ensure both secrets are exported in `.env.prod-max` and the file is actually loaded. |
| Bot startup `RuntimeError` registering webhook | `webhook-url` empty/not HTTPS, or Max rejected the URL/cert | Verify `webhook-url`, the public cert chain, and that nginx serves 443. |
| Max returns 4xx on subscription | TLS validation failed (self-signed, incomplete chain, CN mismatch) | Use a full CA-trusted chain; CN/SAN must match the host in `webhook-url`. |
| Updates buffered but bot gets none | `base-polling-url` wrong, or `get-updates-secret` mismatch | Bot must reach `http://127.0.0.1:8443`; the bot's config and the receiver's file (Step 4) must carry the same `get-updates-secret` value. |
| Duplicate updates delivered | Expected under at-least-once (`mark-on-subsequent-poll = true`) after a crash | Normal; make handlers idempotent. Switch to `false` only if you accept loss on crash. |
| `proxy_pass` returns 404 at `/webhook` | Trailing slash on `proxy_pass` stripped the path | Use `proxy_pass http://127.0.0.1:8443;` (no trailing slash). |

## Invariants (don't violate these)

- **Receiver before bot.** The bot registers the webhook on startup; Max then
  POSTs immediately. The receiver must already be listening.
- **One machine, two SQLite files.** The receiver owns
  `webhook_receiver_data.db` (sole writer of `webhook_updates`); the bot's
  `bot_data.db` is never touched by the receiver. Back up both. Pointing the
  receiver at the bot's DB file is unsupported.
- **Matching secrets across both config surfaces.** `secret` and
  `get-updates-secret` live in the bot's config stack AND the receiver's
  `webhook-receiver.toml`. Drift = 403s with no other symptom.
- **`MAX_WEBHOOK_SECRET` must be set before the receiver starts** — it refuses
  to boot otherwise (and the bot rejects unresolved placeholders too).
- **`unregister-webhook` stays `false`** so bot restarts don't tear down the
  Max subscription and lose nothing.
- **Inbound TLS cert ≠ outbound cert.** The `certs/max/` Минцифры bundle is for
  bot → Max; the webhook endpoint needs its own CA-trusted cert on nginx.
