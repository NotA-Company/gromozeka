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

On import this package aliases httpx→httpx2 (see below).
"""

import httpx2

# Process-wide: make ``import httpx`` resolve to httpx2. The imports below
# transitively pull sqlink (lib.db.providers eagerly imports it), which does a
# hard module-level ``import httpx``; the alias lets the receiver share the
# bot's HTTP stack instead of installing a separate real httpx. This MUST run
# before those imports — under ``python -m lib.max_webhook_receiver`` this
# package __init__ executes before __main__, and the chain below is the FIRST
# httpx import on that path. In the bot process main.py aliases first;
# a repeat call is a documented no-op. See docs/design/httpx2-migration-v1.md §6.
httpx2.alias_httpx()

from .models import WebhookUpdatesRow  # noqa: E402
from .repository import WebhookUpdatesRepository  # noqa: E402
from .schema import (  # noqa: E402
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
