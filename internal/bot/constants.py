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
- Memory refinement / dedup / search / regeneration thresholds
- Knowledge-config wizard limits
- Chat-search-history defaults and backfill tuning
- Sandbox file-size limits

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
    GET_MESSAGES_BY_IDS = "get_messages_by_ids"

    # Sandbox
    RUN_PYTHON = "run_python"
    SANDBOX_LIST_FILES = "sandbox_list_files"
    SANDBOX_READ_FILE = "sandbox_read_file"
    SANDBOX_SEND_FILE = "sandbox_send_file"
    SANDBOX_LIST_LIBRARIES = "sandbox_list_libraries"

    # User Memories (Phase 2 — see docs/plans/user-memories-v1.md §8)
    ADD_MEMORY = "add_memory"
    DELETE_MEMORY = "delete_memory"
    SEARCH_MEMORIES = "search_memories"

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

RANDOM_ANSWER_CONTEXT_LENGTH: int = 64
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

# Memory refinement thresholds
MEMORY_COUNT_THRESHOLD: int = 5
"""Per-(chat, user, thread) new-message count that triggers a refinement run."""

MEMORY_TIME_THRESHOLD_SECONDS: int = 6 * 60 * 60
"""Max seconds since the last refinement run before another is forced (6 hours)."""

MEMORY_MIN_MESSAGES_TO_REFINE: int = 5
"""Don't refine if fewer than this many new messages are available."""

MEMORY_MAX_MESSAGES_PER_RUN: int = 128
"""Cap on messages fed to a single refinement LLM call."""

MEMORY_MAX_REFINES_PER_TICK: int = 3
"""Upper bound on refinement LLM calls per 60s cron tick."""

# Memory dedup thresholds (user-memories dedup / search tuning — see
# docs/plans/user-memories-v1.md §8.2).
MEMORY_DEDUP_DUPLICATE_THRESHOLD: float = 0.95
"""Cosine similarity at/above which ``add_memory`` treats the new memory as a
duplicate of an existing one (no-op insert)."""

MEMORY_DEDUP_SIMILAR_THRESHOLD: float = 0.85
"""Cosine similarity above which ``add_memory`` returns ``similar_exists`` to
the refinement LLM (grey-zone), and above which ``delete_memory`` by-query
will delete a matching memory."""

# Memory search limits
MEMORY_SEARCH_DEFAULT_LIMIT: int = 20
"""Default result cap for the ``search_memories`` LLM tool when no ``limit`` is
passed by the model."""

MEMORY_SEARCH_MAX_LIMIT: int = 100
"""Upper bound on the ``search_memories`` ``limit`` parameter.

Mirrors the sibling ``_llmToolSearchMessages`` clamp
(``internal/bot/common/handlers/chat_search.py``): a model passing a huge
``limit`` would otherwise trigger an unbounded query (and the vec0 ``k`` is
sized as ``limit * 3``). Clamped to this value; the lower bound is 1."""

# Memory embedding regeneration
MEMORY_BACKFILL_DEFAULT_BATCH_SIZE: int = 50
"""Default per-tick batch size for the memory-embedding regeneration cron.

Read from ``[user-memory.thresholds].memory-reindex-batch-size``; falls back
to this constant when unset. Mirrors the sibling ``BACKFILL_DEFAULT_BATCH_SIZE``
(chat-search-history backfill, defined below) and the repository-level
default on ``UserMemoriesRepository.getMemoriesWithoutEmbeddings``."""

MEMORY_BACKFILL_INTER_MESSAGE_DELAY_SECS: float = 0.1
"""Pause between consecutive memory-embedding API calls within a regen batch.

Mirrors the sibling ``BACKFILL_INTER_MESSAGE_DELAY_SECS``
(chat-search-history backfill, defined below).
``LLMService`` already rate-limits at the provider level, but a small extra
cushion keeps the handler from monopolising the asyncio loop and leaves
headroom for user-facing message traffic."""

# Knowledge config wizard
KNOWLEDGE_CONFIG_PAGE_SIZE: int = 8
"""Max memories shown per page in the ``/memory_config`` wizard memory list.

Chosen to keep the inline-keyboard list short enough to be scannable on a
phone screen while limiting the number of ``CallbackButton`` rows (each row
is a separate ``memory_id`` payload — at 8 per page plus pagination / nav
buttons the keyboard stays under the Telegram per-message button budget)."""

KNOWLEDGE_CONFIG_TAG_FILTER_FETCH_LIMIT: int = 200
"""Max rows fetched when a tag filter is active in the wizard memory list.

When a tag filter is applied, the tags post-filter in ``searchMemories`` runs
AFTER the SQL-level offset — so paginating via SQL offset would silently
straddle trimmed rows (see the note in
:meth:`UserMemoriesRepository._filterOnlySearchMemories`). To keep wizard
pagination correct under a tag filter, ``_renderMemoryList`` fetches up to
this many matching rows at offset 0 and paginates the filtered result in
Python. 200 comfortably exceeds any realistic single-user tagged set; a user
with more tagged memories simply sees the first 200 (documented edge)."""

# Chat search history
SEARCH_DEFAULT_MAX_RESULTS: int = 10
"""Default ``max-results`` for `/search` when `[search-history.defaults]` is
unset. Matches the TOML default in `configs/00-defaults/search-history.toml`."""

SEARCH_DEFAULT_DAYS: int = 30
"""Default `days` window for `/search` when `[search-history.defaults]` is unset.
Matches the TOML default in `configs/00-defaults/search-history.toml`."""

BACKFILL_DEFAULT_BATCH_SIZE: int = 50
"""Default per-tick batch size for the backfill CRON_JOB when
``[search-history.embeddings].reindex-batch-size`` is unset."""

SEARCH_TOOL_MAX_MESSAGE_LENGTH: int = 512
"""Max chars per message text in LLM tool search results. Longer texts
are truncated with ``…`` to avoid blowing up the LLM context window."""

BACKFILL_INTER_MESSAGE_DELAY_SECS: float = 0.1
"""Pause inserted between consecutive embedding API calls within a
backfill batch. ``LLMService`` already rate-limits at the provider level,
but a small extra cushion keeps the handler from monopolising the
asyncio loop and leaves headroom for user-facing message traffic."""

MAX_GET_MESSAGES_BATCH: int = 32
"""Maximum number of message IDs the ``get_messages_by_ids`` LLM tool will
fetch in one batch (caps tool abuse). See :class:`CondenseBatchCoverage` /
condensed-context-retrieval plan §3.8."""

# Sandbox limits
MAX_SANDBOX_READ_FILE_BYTES: int = 65536  # 64 KB
"""Max bytes read by the ``sandbox_read_file`` LLM tool (text-mode reads,
truncation tolerated)."""

MAX_SANDBOX_SEND_BYTES: int = 20 * 1024 * 1024  # 20 MB
"""Max bytes for a file sent via the ``sandbox_send_file`` LLM tool; larger
files are rejected before being sent to the user."""
