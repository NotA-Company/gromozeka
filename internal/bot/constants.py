"""Constants for Telegram bot handlers.

This module defines all constant values used throughout the Telegram bot
implementation, including emoji icons, Telegram API limits, processing
timeouts, and configuration parameters for various bot features.

The constants are organized into logical groups:
- Emoji constants for UI elements
- Telegram API limits and constraints
- Processing timeouts and context settings
- Weather data conversion coefficients
- Geocoder configuration
- Message context limits

These constants provide centralized configuration for bot behavior and
ensure consistency across all bot handlers and services.
"""

import telegram.constants

# Emoji constants
DUNNO_EMOJI: str = "🤷‍♂️"
"""Emoji used to indicate uncertainty or lack of knowledge."""

ROBOT_EMOJI: str = "🤖"
"""Emoji used to represent the bot or automated responses."""

CHAT_ICON: str = "👥"
"""Emoji used to represent group chats."""

PRIVATE_ICON: str = "👤"
"""Emoji used to represent private chats."""

# Telegram limits
# TELEGRAM_MAX_MESSAGE_LENGTH = 4096
TELEGRAM_MAX_MESSAGE_LENGTH: int = telegram.constants.MessageLimit.MAX_TEXT_LENGTH
"""Maximum length of a text message in Telegram.

This value is retrieved from the telegram.constants module to ensure
it stays synchronized with the Telegram API specification.
"""

# Processing settings
PROCESSING_TIMEOUT: int = 30 * 60  # 30 minutes
"""Maximum time in seconds allowed for processing a single request.

After this timeout, the processing will be cancelled to prevent
resource exhaustion. Default is 30 minutes (1800 seconds).
"""

RANDOM_ANSWER_CONTEXT_LENGTH: int = 50
"""Maximum number of messages to include in the context for random answer generation.

This controls how much recent conversation history is considered when
generating random responses. Larger values provide more context but
increase processing time and token usage.
"""

SUMMARIZATION_MAX_BATCH_LENGTH: int = 256
"""Maximum number of messages per batch during message summarization.

When summarizing long conversations, messages are processed in batches
of this size to manage memory usage and API rate limits.
"""

# Weather conversion
HPA_TO_MMHG: float = 0.75006157584567
"""Conversion coefficient from hectopascals (hPa) to millimeters of mercury (mmHg).

Used to convert atmospheric pressure readings from the standard metric
unit (hPa) to the traditional unit (mmHg) commonly used in some regions.
"""

# Geocoder settings
GEOCODER_LOCATION_LANGS: list[str] = ["en", "ru"]
"""List of supported language codes for geocoding results.

The geocoder will attempt to return location names in these languages,
in order of preference. Currently supports English ('en') and Russian ('ru').
"""

# Max messages in random message context, should be >=3
MAX_RANDOM_CONTEXT_MESSAGES: int = 6
"""Maximum number of recent messages to include in random answer context.

This constant determines how many recent messages from the conversation
history are considered when generating contextual responses. The value
must be at least 3 to provide meaningful context. Default is 6 messages.
"""
