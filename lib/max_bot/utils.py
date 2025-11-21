"""
Max Messenger Bot utilities.

This module provides utility functions for working with Max Messenger Bot API models,
specifically for converting linked messages to standalone messages.
"""

from typing import Optional

from .models import Message


def MessageLinkToMessage(baseMessage: Message) -> Optional[Message]:
    """Convert a linked message to a standalone message.

    Args:
        baseMessage: The original message containing a link to another message.

    Returns:
        A new Message object representing the linked message, or None if no link exists.
        Missing fields are filled with values from the base message.
    """
    if baseMessage.link is None:
        return None

    # Filling unknown fields with baseMessage ones
    return Message(
        sender=baseMessage.link.sender or baseMessage.sender,
        recipient=baseMessage.recipient,  # In case of private chat we need to change recipient.user_id but whatever
        timestamp=baseMessage.timestamp,
        body=baseMessage.link.message,
        api_kwargs=baseMessage.link.api_kwargs,
    )
