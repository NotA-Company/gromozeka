"""User metadata models for the Gromozeka bot.

This module defines the TypedDict structure used to store and manage
user metadata throughout the bot system. User metadata includes flags
for spam detection, message handling preferences, and user state tracking.
"""

from typing import Dict, TypedDict


class UserMemoryThreadDict(TypedDict, total=False):
    """TypedDict representing per-thread memory refinement state for a user.

    Stored as a nested dict inside ``UserMetadataDict.memoryRefinement``,
    keyed by ``str(threadId)`` (``"0"`` for the main thread). All fields are
    optional (``total=False``) since a freshly-created entry may only carry a
    subset of them.

    Note: the ``lastRefinedTS`` (unix timestamp of the last refinement run) is
    NO LONGER persisted here — it is tracked in-memory on the handler
    (``UserDataHandler._lastRefinedTS``) so the persisted entry stays limited
    to message cursors (the ``summary`` field is legacy — no longer written or
    read).

    Attributes:
        summary: Rolling short summary/bio of the user in this thread.
        lastProcessedMessageId: MessageId.asStr() of the newest message ingested by the
            last refinement (logging/debug only).
        lastProcessedMessageDate: ISO datetime of the newest message ingested by the last
            refinement — the cursor for getChatMessagesSince.
    """

    # LEGACY: no longer written (Phase 4a) or read at runtime (Phase 4b);
    # kept for backward-compat with old blobs in chat_users.metadata.
    summary: str
    """Rolling short summary/bio of the user in this thread."""
    lastProcessedMessageId: str
    """MessageId.asStr() of the newest message ingested by the last refinement (logging/debug only)."""
    lastProcessedMessageDate: str
    """ISO datetime of the newest message ingested by the last refinement — the cursor for getChatMessagesSince."""


class UserMetadataDict(TypedDict, total=False):
    """TypedDict representing user metadata stored in JSON format.

    This TypedDict defines the structure for user metadata that is persisted
    in the database. All fields are optional (total=False) to allow for
    partial metadata updates and flexible storage.

    Attributes:
        isSpammer: Flag indicating whether the user has been identified as a spammer.
            When True, the bot may apply special handling to the user's messages.
        notSpammer: Flag indicating whether the user has been explicitly marked as not a spammer.
            This can override automated spam detection results.
        dropMessages: Flag indicating whether the bot should automatically delete all new messages
            from this user. When True, messages are dropped without processing.
        leftChat: Flag indicating whether the user has left the chat. Used to track user presence
            and potentially skip processing for users who are no longer active.
        memoryRefinement: Per-thread memory refinement state, keyed by str(threadId); "0" for main thread.
    """

    isSpammer: bool
    """Flag indicating whether the user has been identified as a spammer."""
    notSpammer: bool
    """Flag indicating whether the user has been explicitly marked as not a spammer."""
    dropMessages: bool
    """Flag indicating whether the bot should automatically delete all new messages from this user."""
    leftChat: bool
    """Flag indicating whether the user has left the chat."""
    memoryRefinement: Dict[str, UserMemoryThreadDict]
    """Per-thread memory refinement state, keyed by str(threadId); "0" for main thread."""
