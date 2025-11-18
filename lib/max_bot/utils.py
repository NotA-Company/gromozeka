"""TODO"""

from typing import Optional

from .models import Message


def MessageLinkToMessage(baseMessage: Message) -> Optional[Message]:
    """TODO"""
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
