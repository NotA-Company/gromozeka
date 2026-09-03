from datetime import datetime
from typing import Optional, TypedDict


class WebhookUpdatesRow(TypedDict):
    """Dictionary representing a webhook_updates row.

    Each row stores one incoming Max webhook payload awaiting consumption.
    ``processed`` is an integer boolean (0/1). ``processed_at`` is ``None``
    for rows that have not yet been consumed.
    """

    id: str
    """Application-generated UUID identifying the update."""
    received_at: datetime
    """When the webhook payload was received and stored."""
    update_type: str
    """Coarse update_type tag extracted from the Max payload."""
    raw_json: str
    """Full webhook request body serialized as a JSON string."""
    processed: int
    """Whether the update has been consumed (0 = pending, 1 = processed)."""
    processed_at: Optional[datetime]
    """When the update was marked processed, or None if still pending."""
