"""Common type definitions used across the bot application.

This module provides type aliases and type definitions that are used throughout
the Gromozeka bot application to ensure type consistency and improve code
readability. These types are particularly important for handling messages from
different messaging platforms (Telegram, Max Messenger) which may use different
identifier formats.
"""

from typing import Union

MessageIdType = Union[int, str]
"""Type alias for message identifiers across different messaging platforms.

This type represents the identifier of a message, which can be either an integer
or a string depending on the messaging platform:
    - Telegram: Uses integer message IDs
    - Max Messenger: Uses string message IDs

Using this type alias allows the codebase to handle both platforms uniformly
while maintaining type safety.

Examples:
    >>> telegram_message_id: MessageIdType = 12345
    >>> max_message_id: MessageIdType = "msg_abc123"
    >>> def process_message(message_id: MessageIdType) -> None:
    ...     print(f"Processing message {message_id}")
"""
