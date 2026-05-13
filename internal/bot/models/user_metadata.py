"""User metadata models for the Gromozeka bot.

This module defines the TypedDict structure used to store and manage
user metadata throughout the bot system. User metadata includes flags
for spam detection, message handling preferences, and user state tracking.
"""

from typing import TypedDict


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
    """

    isSpammer: bool
    """Flag indicating whether the user has been identified as a spammer."""
    notSpammer: bool
    """Flag indicating whether the user has been explicitly marked as not a spammer."""
    dropMessages: bool
    """Flag indicating whether the bot should automatically delete all new messages from this user."""
    leftChat: bool
    """Flag indicating whether the user has left the chat."""
