"""Database-layer constants for the user-memories subsystem.

Centralised here so both the repository and future consumers share a single
source of truth. Bot-layer constants live in ``internal/bot/constants.py``.
"""

# Memory injection defaults
PERMANENT_INJECTION_CAP: int = 10
"""Maximum permanent memories injected per (chatId, userId) into a chat turn."""

EPHEMERAL_RETRIEVAL_LIMIT: int = 5
"""Default cap on ephemeral (non-permanent) memories per turn."""

# Memory search defaults
MEMORY_SEARCH_DEFAULT_LIMIT: int = 20
"""Default result cap for ``searchMemories``."""

MEMORY_SEARCH_TOPK_MULTIPLIER: int = 3
"""vec0 ``k`` multiplier: ``k = limit * this`` to absorb post-filter trimming."""

# Embedding regeneration defaults
BACKFILL_DEFAULT_BATCH_SIZE: int = 50
"""Default per-tick batch size for embedding-regen cron."""
