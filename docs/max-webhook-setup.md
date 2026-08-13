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
                                                   webhook_updates (SQLite)
                                                          ▲
                                                          │ polls GET /updates
                                          BOT  ◄──────────┘  (base-polling-url)
                                            │
                                            └──► platform-api2.max.ru  (outbound: send replies)
```

- Both processes run on **the same machine** and share **one SQLite file**.
  The receiver is the sole writer of `webhook_updates`; the bot never touches
  that table directly — it only consumes the receiver's `GET /updates`.
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

Both the receiver and the bot read this dotenv file, so both pick the values up
through `${VAR}` substitution in the merged config.

## Step 3 — create the webhook config override

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

## Step 4 — nginx reverse proxy

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

## Step 5 — OpenRC init script for the receiver

Create **`/etc/init.d/gromozeka-webhook-receiver`**:

```sh
#!/sbin/openrc-run

name="gromozeka-webhook-receiver"
description="Max Messenger webhook receiver for Gromozeka"

: ${GROMOZEKA_DIR:=/opt/gromozeka}
: ${GROMOZEKA_USER:=gromozeka}

# Same config stack + dotenv the bot uses (see Step 7). Both processes MUST
# load identical config so [webhook-receiver] resolves the same way.
command="${GROMOZEKA_DIR}/venv/bin/python3"
command_args="-m internal.max_webhook_receiver \
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

## Step 6 — (optional) OpenRC init script for the bot

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

## Step 7 — the shared config stack (important)

Both init scripts deliberately pass the **exact same** flags:

```
--dotenv-file .env.prod-max
--config-dir ./configs/00-defaults
--config-dir ./configs/common
--config-dir ./configs/prod
--config-dir ./configs/prod-max
```

This mirrors what `run.sh --env=prod-max` assembles (it reads `CONFIGS` from
`.env.prod-max` and expands it into `--config-dir` flags). The receiver's
`__main__.py` does **not** auto-add `00-defaults`, so you must pass every layer
explicitly. If the two processes ever load different config, the secrets and
URLs will disagree silently — keep the stacks identical.

## Step 8 — start in order and verify

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
| Updates buffered but bot gets none | `base-polling-url` wrong, or `get-updates-secret` mismatch | Bot must reach `http://127.0.0.1:8443`; both processes must share the same `get-updates-secret` value. |
| Duplicate updates delivered | Expected under at-least-once (`mark-on-subsequent-poll = true`) after a crash | Normal; make handlers idempotent. Switch to `false` only if you accept loss on crash. |
| `proxy_pass` returns 404 at `/webhook` | Trailing slash on `proxy_pass` stripped the path | Use `proxy_pass http://127.0.0.1:8443;` (no trailing slash). |

## Invariants (don't violate these)

- **Receiver before bot.** The bot registers the webhook on startup; Max then
  POSTs immediately. The receiver must already be listening.
- **One machine, one SQLite file.** Both processes share the DB; the receiver
  writes `webhook_updates`, the bot reads via HTTP only.
- **Identical config stack on both processes.** Same `--config-dir` order, same
  `--dotenv-file`. Divergence = silent secret/URL mismatch.
- **`MAX_WEBHOOK_SECRET` must be set before the receiver starts** — it refuses
  to boot otherwise (and the bot rejects unresolved placeholders too).
- **`unregister-webhook` stays `false`** so bot restarts don't tear down the
  Max subscription and lose nothing.
- **Inbound TLS cert ≠ outbound cert.** The `certs/max/` Минцифры bundle is for
  bot → Max; the webhook endpoint needs its own CA-trusted cert on nginx.
