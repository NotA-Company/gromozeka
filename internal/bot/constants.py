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

from enum import StrEnum

import telegram.constants


class ToolName(StrEnum):
    """Names of all registered LLM tools.

    Each member's value matches the string passed to ``registerTool(name=...)``.
    Using these constants instead of raw string literals enables type-safe
    per-tool filtering via the ``useTools: dict[str, bool]`` parameter.

    When adding a new LLM tool, add a member here AND a matching
    ``registerTool(name=ToolName.YOUR_TOOL, ...)`` call site in the handler's
    ``__init__``. See the add-handler skill for the full registration workflow.
    """

    # Weather
    GET_WEATHER_BY_CITY = "get_weather_by_city"
    GET_WEATHER_BY_ADDRESS = "get_weather_by_address"
    GET_WEATHER_BY_COORDS = "get_weather_by_coords"

    # Media
    GENERATE_AND_SEND_IMAGE = "generate_and_send_image"

    # Yandex Search
    WEB_SEARCH = "web_search"
    GET_URL_CONTENT = "get_url_content"

    # Chat Search
    SEARCH_MESSAGES = "search_messages"
    LIST_USERS = "list_users"
    GET_THREAD = "get_thread"

    # Sandbox
    RUN_PYTHON = "run_python"
    SANDBOX_LIST_FILES = "sandbox_list_files"
    SANDBOX_READ_FILE = "sandbox_read_file"
    SANDBOX_SEND_FILE = "sandbox_send_file"
    SANDBOX_LIST_LIBRARIES = "sandbox_list_libraries"

    # User Data
    ADD_USER_DATA = "add_user_data"

    # Common
    GET_CURRENT_DATETIME = "get_current_datetime"

    # Example
    EXAMPLE = "example"

    # Divination
    DO_TAROT_READING = "do_tarot_reading"
    DO_RUNES_READING = "do_runes_reading"


# Reserved key in useTools dict for fallback tool enablement
TOOLS_DEFAULT_DICT_KEY: str = "default"
"""Reserved key in the ``useTools`` dict used by ``_resolveTools`` for fallback tool
enablement when no explicit per-tool entry exists."""

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
MAX_RANDOM_CONTEXT_MESSAGES: int = 8
"""Maximum number of recent messages to include in random answer context.

This constant determines how many recent messages from the conversation
history are considered when generating contextual responses. The value
must be at least 3 to provide meaningful context. Default is 8 messages.
"""
