---
category: guide
---

# Operations

Deploying the bot in production (including Max webhook mode) and bootstrapping the sandbox runtime.

## 11. Deployment

### Deployment Prerequisites

- Python 3.12+
- Virtual environment with all dependencies
- Configured TOML config file(s)
- Bot token from @BotFather (Telegram) or Max Developer Portal

### Setup

```bash
# 1. Clone the repo
git clone <repo-url> gromozeka
cd gromozeka

# 2. Create venv and install deps
make install

# 3. Create your config directory
mkdir -p my-config

# 4. Create main config with your secrets
cat > my-config/config.toml << 'EOF'
[bot]
mode = "telegram"
token = "YOUR_BOT_TOKEN"
bot_owners = ["your_username"]
spam-button-salt = "random-secret-salt-here"

[database]
default = "default"

[database.providers.default]
provider = "sqlite3"

[database.providers.default.parameters]
dbPath = "bot_data.db"
readOnly = false
timeout = 30
useWal = true

[models.providers.openrouter]
type = "openrouter"
api-key = "YOUR_OPENROUTER_KEY"

[models.models.main]
provider = "openrouter"
model_id = "mistralai/mistral-7b-instruct"
customParams.temperature = 0.7
context = 32768
enabled = true
EOF

# 5. Verify configuration loads correctly
./venv/bin/python3 main.py \
    --config-dir configs/00-defaults \
    --config my-config/config.toml \
    --print-config
```

### Running the Bot

```bash
# Standard start
./venv/bin/python3 main.py \
    --config-dir configs/00-defaults \
    --config my-config/config.toml

# Daemon mode (background process)
./venv/bin/python3 main.py \
    --config-dir configs/00-defaults \
    --config my-config/config.toml \
    --daemon \
    --pid-file /var/run/gromozeka.pid

# With .env file for secrets
./venv/bin/python3 main.py \
    --config-dir configs/00-defaults \
    --config my-config/config.toml \
    --dotenv-file /etc/gromozeka/.env
```

### Deployment Storage Directory

By default, the bot changes its working directory to the `root-dir` specified in `[application]` All relative paths (database, logs) are relative to this directory

```toml
[application]
root-dir = "/var/lib/gromozeka"   # All files created here

[database.providers.default.parameters]
dbPath = "bot_data.db"            # -> /var/lib/gromozeka/bot_data.db

[logging]
file = "logs/gromozeka.log"       # -> /var/lib/gromozeka/logs/gromozeka.log
```

### Systemd Service Example

```ini
# /etc/systemd/system/gromozeka.service
[Unit]
Description=Gromozeka Telegram Bot
After=network.target

[Service]
Type=simple
User=gromozeka
WorkingDirectory=/opt/gromozeka
ExecStart=/opt/gromozeka/venv/bin/python3 main.py \
    --config-dir /opt/gromozeka/configs/00-defaults \
    --config /etc/gromozeka/config.toml \
    --dotenv-file /etc/gromozeka/.env
Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl enable gromozeka
sudo systemctl start gromozeka
sudo journalctl -u gromozeka -f
```

### Production Config Tips

```toml
[application]
root-dir = "/var/lib/gromozeka"

[logging]
level = "WARNING"    # Reduce verbosity in production
file = "logs/gromozeka.log"
error-file = "logs/gromozeka.err.log"
rotate = true

[database.providers.default.parameters]
timeout = 60
useWal = true

[ratelimiter.ratelimiters.default]
type = "SlidingWindow"
[ratelimiter.ratelimiters.default.config]
windowSeconds = 5
maxRequests = 10     # Increase for production volume
```

### Environment Variables

Sensitive values should always be provided via environment variables or `.env` file

```bash
# .env file example
TELEGRAM_BOT_TOKEN=1234567890:ABCdef...
OPENROUTER_API_KEY=sk-or-v1-...
OPENWEATHERMAP_API_KEY=abc123...
YANDEX_API_KEY=AQVN...
YANDEX_FOLDER_ID=b1g...
GEOCODE_MAPS_API_KEY=...
```

```toml
# Reference in TOML config
[bot]
token = "${TELEGRAM_BOT_TOKEN}"

[models.providers.openrouter]
api-key = "${OPENROUTER_API_KEY}"
```

### Max Messenger Webhook Receiver (Two-Process Mode)

In Max webhook mode the deployment is **two processes**: the normal bot process plus a standalone aiohttp webhook receiver (`lib/max_webhook_receiver/`) that accepts Max's webhook POSTs and serves them back to the bot via a local `GET /updates` endpoint. See [`docs/llm/architecture.md`](../llm/architecture.md) ADR-013.

**1. Configure** the bot under `[webhook-receiver]` (defaults live in `configs/00-defaults/webhook-receiver.toml`; the receiver process reads its own single TOML file — see step 2):

```toml
[webhook-receiver]
enabled = true                       # bot polls the local receiver instead of the real Max API
register-webhook = true              # bot registers the subscription with Max on startup (default true)
unregister-webhook = true            # bot unregisters the subscription on shutdown (default false; set true to clean up on exit)
webhook-url = "https://bot.example.com/webhook"   # public HTTPS URL Max POSTs to
secret = "${MAX_WEBHOOK_SECRET}"     # shared secret (env var — never commit the value)
base-polling-url = "http://127.0.0.1:8443"        # where the bot polls
```

Set `MAX_WEBHOOK_SECRET` in your `.env`:

```bash
# .env
MAX_WEBHOOK_SECRET=some-long-random-secret
```

**2. Start the receiver process** (it must be reachable before the bot registers the webhook). The receiver reads its OWN single TOML config file (`--config`; cwd-relative default `webhook-receiver.toml`) — not the bot's `--config-dir` stack — and stores updates in its own SQLite database (`webhook_receiver_data.db`), created and self-healed on startup. A complete example file (including the `[webhook-receiver.database]` section) lives in [`docs/max-webhook-setup.md`](../max-webhook-setup.md):

```bash
./venv/bin/python3 -m lib.max_webhook_receiver \
    --config webhook-receiver.toml \
    --dotenv-file .env
```

The receiver binds `127.0.0.1:8443` by default and refuses to start when `secret` is empty or an unresolved `${VAR}` placeholder, or when the config file is missing/unreadable. `secret` / `get-updates-secret` are maintained in BOTH the bot's config and the receiver's file — keep them identical (drift = 403s). Put it behind a reverse proxy (nginx/Caddy) that terminates TLS and forwards `POST /webhook` to the receiver; alternatively set `tls-cert-file` + `tls-key-file` in the receiver's config file to have it serve HTTPS directly.

**3. Start the bot** as usual. When `webhook-receiver.enabled = true`, the bot's `MaxBotClient` polls the receiver's `GET /updates` (via `base-polling-url`) instead of `platform-api2.max.ru`; on startup it calls Max's `POST /subscriptions` (when `register-webhook = true`, the default), and on shutdown `DELETE /subscriptions` (when `unregister-webhook = true`; defaults to `false`, so the subscription survives a restart unless you opt in).

```bash
./venv/bin/python3 main.py \
    --config-dir configs/00-defaults \
    --config-dir configs/local \
    --dotenv-file .env
```

**Systemd**: run the two processes as separate units (e.g. `gromozeka.service` for the bot and `gromozeka-webhook.service` for the receiver). They no longer share a config stack or a database: the bot points at the usual `--config-dir` dirs / `.env`, while the receiver takes its own `--config` file (plus `--dotenv-file` for `${VAR}` substitution) and keeps its own SQLite file — only `secret` / `get-updates-secret` must match across the two.

---

## 13. Bootstrapping the Sandbox

The sandbox library (`lib/sandbox/`) executes untrusted Python code inside Docker containers. Before using it, you need to set up the storage directory and build the Docker images.

### Sandbox Prerequisites

- **Docker** must be installed and running on the host. The sandbox communicates with Docker via the daemon socket (default: `unix:///var/run/docker.sock`).

### Sandbox Storage Directory

The sandbox stores session workspaces, metadata, and library pools under `[sandbox.storage].root_dir` (default: `/var/lib/gromozeka/sandbox`). Create this directory and ensure the bot process can write to it:

```bash
sudo mkdir -p /var/lib/gromozeka/sandbox
sudo chown $USER /var/lib/gromozeka/sandbox
```

### Building Docker Images

`SandboxManager.prepareRuntime()` checks whether each image exists and builds missing images (or rebuilds them when `rebuildImage=True`). No manual build step is required.

Packages are not baked into the images — they are installed into the library pool at runtime via the `/sandbox install` bot command.

### Configuration

All sandbox settings live in [`configs/00-defaults/sandbox.toml`](/configs/00-defaults/sandbox.toml). See [`docs/llm/configuration.md`](../llm/configuration.md) for the full `[sandbox.*]` reference.

---
