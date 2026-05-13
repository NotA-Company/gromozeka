"""Common type definitions used across the bot application.

This module provides type aliases and type definitions that are used throughout
the Gromozeka bot application to ensure type consistency and improve code
readability. These types are particularly important for handling messages from
different messaging platforms (Telegram, Max Messenger) which may use different
identifier formats.
"""

import logging
from typing import Self

logger = logging.getLogger(__name__)

MessageIdType = int | str
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


class MessageIdClass:
    """Class for message identifiers across different messaging platforms.

    This class wraps a message identifier which can be either an integer
    or a string depending on the messaging platform:
        - Telegram: Uses integer message IDs
        - Max Messenger: Uses string message IDs

    Using this class allows the codebase to handle both platforms uniformly
    while maintaining type safety. Supports copying, string/int conversion,
    and equality comparison with other MessageIdClass instances, ints, and strs.

    Attributes:
        messageId: The raw message identifier value (int or str).
    """

    __slots__ = ("messageId",)

    def __init__(self, messageId: MessageIdType | Self) -> None:
        """Initialize a MessageIdClass instance.

        Args:
            messageId: A message ID value (int or str), or another
                MessageIdClass instance to copy from.

        Raises:
            ValueError: If messageId is not an int, str, or MessageIdClass.
        """
        self.messageId: MessageIdType
        if isinstance(messageId, self.__class__):
            self.messageId = messageId.messageId
        elif isinstance(messageId, (str, int)) and not isinstance(messageId, bool):
            self.messageId = messageId
        else:
            raise ValueError(f"Invalid message ID type: {type(messageId).__name__}")

    def copy(self) -> Self:
        """Return a new MessageIdClass with the same underlying value.

        Returns:
            A new MessageIdClass instance that is a shallow copy of this one.
        """
        return self.__class__(self)

    def asStr(self) -> str:
        """Return the message ID as a string.

        Returns:
            The string representation of the message ID.
        """
        return str(self.messageId)

    def asInt(self) -> int:
        """Return the message ID as an integer.

        If the underlying value is already an int, it is returned directly.
        If it is a string, it is parsed as an integer. This is useful when
        a Telegram message ID has been retrieved from the database as a string
        and needs to be converted back to its original integer form.

        Returns:
            The message ID as an integer.

        Raises:
            ValueError: If the message ID cannot be parsed as an integer.
        """
        if isinstance(self.messageId, int):
            return self.messageId

        try:
            return int(self.messageId)
        except ValueError:
            raise ValueError("Message ID is not an integer")

    def asMessageId(self) -> MessageIdType:
        """Return the message ID as an int if possible, otherwise as a string.

        Useful for serialising to JSON where an int representation takes less
        space than a string representation when the value is numeric.

        Returns:
            The message ID as an int if it can be parsed as one, otherwise
            as a string.
        """
        try:
            return self.asInt()
        except ValueError:
            return self.asStr()

    def __str__(self) -> str:
        """Return the string representation of the message ID.

        Returns:
            The message ID as a string.
        """
        return self.asStr()

    def __repr__(self) -> str:
        """Return an unambiguous string representation of the instance.

        Returns:
            A string in the form ``MessageIdClass(messageId=<value>)``.
        """
        return f"{self.__class__.__name__}(messageId={self.messageId})"

    def __eq__(self, value: object) -> bool:
        """Compare this message ID with another value for equality.

        Supports comparison with:
            - Another MessageIdClass instance (compares string representations).
            - A bool (always False)
            - An int (tries to represent the message ID as an int if possible, or str in other cases).
            - A str (compares string representations).
            - Any other type (logs a warning and compares string representations).

        Args:
            value: The value to compare against.

        Returns:
            True if the values are equal, False otherwise.
        """
        if isinstance(value, MessageIdClass):
            return self.asStr() == value.asStr()
        elif isinstance(value, bool):
            # Bool is subtype of int, so we better to handle it separately
            return False
        elif isinstance(value, int):
            return self.asMessageId() == value
        elif isinstance(value, str):
            return self.asStr() == value
        else:
            logger.warning(f"Unsupported type for MessageIdClass equality comparison: {type(value).__name__}")
            return self.asStr() == str(value)

    def __hash__(self) -> int:
        """Return a hash value for this instance.

        Uses the string representation so that MessageIdClass instances
        are usable as dict keys and in sets, and are consistent with
        ``__eq__`` when comparing two MessageIdClass instances.

        Note: ``MessageIdClass(5) == 5`` is True, but
        ``hash(MessageIdClass(5)) != hash(5)``.  Do not mix
        MessageIdClass instances with plain ints or strs in the same
        set or dict keys — cross-type equality is a convenience for
        comparisons only, not for hash-based lookups.

        Returns:
            A hash of the string representation of the message ID.
        """
        return hash(self.asStr())
