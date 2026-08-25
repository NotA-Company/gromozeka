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
"""

from .models import WebhookUpdatesRow
from .repository import WebhookUpdatesRepository
from .schema import (
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
