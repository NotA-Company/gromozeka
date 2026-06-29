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

import logging
import ssl
from pathlib import Path
from typing import Optional

from .models import Message

logger = logging.getLogger(__name__)


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


def buildMaxSslContext(caBundlePath: Optional[str] = None) -> Optional[ssl.SSLContext]:
    """Build an SSL context that trusts both system CAs and custom CA certificates.

    Loads the default system/certifi CA bundle, then loads any additional PEM
    certificate files found in the specified directory. This is needed for
    platform-api2.max.ru, which uses certificates issued by the Russian
    Минцифры CA that are not in standard CA bundles.

    Args:
        caBundlePath: Path to a directory containing additional PEM certificate
            files (.pem, .crt). If None or empty string, returns None (use
            system defaults). Path is resolved relative to the current working
            directory.

    Returns:
        An ssl.SSLContext with system CAs + custom CAs loaded, or None if
        no custom CA path was provided.

    Raises:
        FileNotFoundError: If the specified directory does not exist.

    Note:
        Individual certificate files that cannot be loaded by this OpenSSL
        build (e.g. GOST certificates on macOS / non-GOST OpenSSL) are
        skipped with a warning rather than raising.
    """
    if not caBundlePath:
        return None

    certDir = Path(caBundlePath)
    if not certDir.is_dir():
        raise FileNotFoundError(
            f"Max CA bundle directory not found: {certDir.resolve()}. "
            f"Download certificates from https://www.gosuslugi.ru/crt"
        )

    # Start with system defaults (loads certifi or OS CA bundle)
    ctx = ssl.create_default_context()

    # Load each PEM file from the directory
    loaded = 0
    for certFile in sorted(certDir.iterdir()):
        if certFile.suffix in (".pem", ".crt") and certFile.is_file():
            try:
                ctx.load_verify_locations(cafile=str(certFile))
                logger.info("Loaded CA certificate: %s", certFile.name)
                loaded += 1
            except ssl.SSLError as e:
                logger.warning(
                    "Skipping unloadable CA certificate %s (likely GOST, not supported by this OpenSSL build): %s",
                    certFile.name,
                    e,
                )

    if loaded == 0:
        logger.warning(
            "No .pem/.crt files found in %s. TLS connections to platform-api2.max.ru may fail.",
            certDir.resolve(),
        )
        return None

    logger.info("SSL context ready with %d additional CA certificate(s)", loaded)
    return ctx
