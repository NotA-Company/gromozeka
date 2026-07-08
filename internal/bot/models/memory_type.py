"""MemoryType discriminator for the ``user_memories`` store.

Defines the closed set of high-level categories a user memory can belong
to. Stored as the TEXT ``type`` column on the ``user_memories`` table
(see ``migration_020_user_memories``). Freeform categorisation beyond
these is handled by the JSON ``tags`` column.

The repo mandates ``StrEnum`` (from ``enum``) over ``Literal[...]`` so
the values serialise naturally and stay self-documenting
(AGENTS.md: "use ``StrEnum`` (from ``enum``), not ``Literal[...]``").
"""

from enum import StrEnum


class MemoryType(StrEnum):
    """Closed set of user-memory categories.

    Members:
        BIO: High-level, evolving summary of who the user is. Exactly one
            permanent bio memory is maintained per (chat, user, thread) by
            the refinement pass; the rolling-bio migration
            (``migration_020`` Backfill B) seeds it.
        PREFERENCE: A stated or inferred preference ("prefers dark mode",
            "vegan").
        FACT: A durable, non-preferential fact ("lives in Berlin",
            "works as a nurse").
        EVENT: A point-in-time happening ("got married 2024-06",
            "travelling to Tokyo in May").
        RELATIONSHIP: A connection to another person/entity ("married to
            Alex", "mentor is Dr. Lee").
    """

    BIO = "bio"
    """High-level user summary; one permanent bio maintained per (chat, user, thread)."""

    PREFERENCE = "preference"
    """A stated or inferred user preference."""

    FACT = "fact"
    """A durable, non-preferential fact about the user."""

    EVENT = "event"
    """A point-in-time happening in the user's life."""

    RELATIONSHIP = "relationship"
    """A connection between the user and another person/entity."""
