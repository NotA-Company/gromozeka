# syntax=docker/dockerfile:1
# Standalone image for the Max webhook receiver (lib.max_webhook_receiver).
# Build from the REPO ROOT so the .dockerignore applies:
#   docker build -f lib/max_webhook_receiver/Dockerfile -t gromozeka-webhook-receiver .
# sqlink is fetched from a private git host; pass credentials via a BuildKit secret:
#   printf 'machine git.sourcecraft.dev login <user> password <token>' > /tmp/netrc
#   docker build --secret id=netrc,src=/tmp/netrc -f lib/max_webhook_receiver/Dockerfile -t gromozeka-webhook-receiver .
FROM python:3.13-alpine

# git is required to install the commit-pinned sqlink dependency.
RUN apk add --no-cache git

WORKDIR /app

COPY lib/max_webhook_receiver/requirements.txt ./requirements.txt
# --no-deps is deliberate: sqlink's metadata requires real httpx, but the
# receiver aliases httpx→httpx2 at package import (see lib.max_webhook_receiver),
# so plain dependency resolution must be bypassed — requirements.txt carries the
# complete closure.
RUN --mount=type=secret,id=netrc,target=/root/.netrc,required=false \
    pip install --no-cache-dir --no-deps -r requirements.txt

# Runtime source closure of the receiver — the five lib packages it imports.
# If the receiver ever gains another lib dependency, add it here AND to requirements.txt.
COPY lib/__init__.py ./lib/__init__.py
COPY lib/utils ./lib/utils
COPY lib/db ./lib/db
COPY lib/proxy ./lib/proxy
COPY lib/max_webhook_receiver ./lib/max_webhook_receiver

RUN adduser -D -u 10001 receiver && mkdir -p /data && chown receiver:receiver /data
USER receiver
VOLUME ["/data"]

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8443

# Container configs must set listen-host = "0.0.0.0" (the 127.0.0.1 default is
# unreachable outside the container) and dbPath under /data (persisted volume).
ENTRYPOINT ["python3", "-m", "lib.max_webhook_receiver"]
CMD ["--config", "/app/webhook-receiver.toml"]
