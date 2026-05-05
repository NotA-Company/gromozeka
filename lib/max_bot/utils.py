"""
Max Messenger Bot utilities.

This module provides utility functions for working with Max Messenger Bot API models,
specifically for converting linked messages (forwards and replies) to standalone messages.

The main functionality includes:
- Converting linked messages to standalone Message objects
- Filling missing fields from the base message when creating standalone versions

Note:
    Linked messages are messages that reference other messages, such as forwards or replies.
    This utility helps extract the linked message content into a standalone Message object.
"""

from typing import Optional

from .models import Message


def messageLinkToMessage(baseMessage: Message) -> Optional[Message]:
    """Convert a linked message to a standalone message.

    This function extracts a linked message (forward or reply) from a base message
    and creates a standalone Message object. Missing fields in the linked message
    are filled with values from the base message to ensure a complete Message object.

    Args:
        baseMessage: The original Message object containing a link to another message.
            The message must have a `link` attribute of type LinkedMessage.

    Returns:
        Optional[Message]: A new Message object representing the linked message,
        or None if the base message has no link. The returned Message includes:
        - sender: From the linked message, or base message if not available
        - recipient: From the base message (note: for private chats, recipient.user_id
          may need adjustment)
        - timestamp: From the base message
        - body: The message content from the linked message
        - api_kwargs: Additional API parameters from the linked message

    Example:
        >>> message = Message(...)
        >>> linked = messageLinkToMessage(message)
        >>> if linked:
        ...     print(f"Linked message from: {linked.sender}")
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
