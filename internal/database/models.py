"""
Database models and type definitions.

This module contains all database-related models, enums, and TypedDict definitions
used throughout the application for representing database entities and their structures.
"""

import datetime
from enum import StrEnum
from typing import NotRequired, Optional, TypedDict, Union

from internal.models import MessageId


class MediaStatus(StrEnum):
    """Status of media attachment processing."""

    NEW = "new"
    """Media is newly created and not yet processed."""
    PENDING = "pending"
    """Media is currently being processed."""
    DONE = "done"
    """Media processing completed successfully."""
    FAILED = "failed"
    """Media processing failed."""


class MessageCategory(StrEnum):
    """Category of a message in the chat system."""

    UNSPECIFIED = "unspecified"
    """Unspecified message category."""

    USER = "user"
    """Message from user."""
    USER_COMMAND = "user-command"
    """Command from user."""

    CHANNEL = "channel"
    """Message from channel/automatic forward."""

    BOT = "bot"
    """Message from bot."""
    BOT_COMMAND_REPLY = "bot-command-reply"
    """Bot reply to command."""
    BOT_ERROR = "bot-error"
    """Bot returned some error."""
    BOT_SUMMARY = "bot-summary"
    """Summary message from bot."""
    BOT_RESENDED = "bot-resended"
    """Bot resended message."""

    BOT_SPAM_NOTIFICATION = "bot-spam-notification"
    """Spam notification message from bot."""
    USER_SPAM = "user-spam"
    """Spam message from user."""

    DELETED = "deleted"
    """Message deleted."""
    USER_CONFIG_ANSWER = "user-config-answer"
    """Answer to some config option."""

    @classmethod
    def fromStr(cls, value: str, default: Optional["MessageCategory"] = None) -> "MessageCategory":
        """Convert string to MessageCategory enum value.

        Args:
            value: String value to convert.
            default: Optional default value to return if conversion fails. If not provided,
                defaults to MessageCategory.UNSPECIFIED.

        Returns:
            MessageCategory enum value, or default if conversion fails and default was
            provided, otherwise MessageCategory.UNSPECIFIED.
        """
        try:
            return cls(value)
        except ValueError:
            if default is None:
                default = MessageCategory.UNSPECIFIED
            return default

    def toRole(self) -> str:
        """Convert message category to role for LLM context.

        Returns:
            "assistant" for bot messages, "user" for all other messages.
        """
        if self.value.startswith("bot"):
            return "assistant"

        return "user"


class SpamReason(StrEnum):
    """Reason for spam classification or action."""

    AUTO = "auto"
    """Automatically detected spam."""
    USER = "user"
    """User reported spam."""
    ADMIN = "admin"
    """Admin marked as spam."""
    UNBAN = "unban"
    """User was unbanned."""


class ChatMessageDict(TypedDict):
    """Dictionary representing a chat message with user information.

    Combines data from chat_message and User tables. ``score`` is
    populated by :meth:`ChatSearchRepository.searchChatMessages` when the
    result is ranked (semantic-search mode); it is absent from messages
    produced by the other chat-message repository methods.
    """

    # From chat_message table
    chat_id: int
    """Chat identifier."""
    message_id: MessageId
    """Message identifier."""
    date: datetime.datetime
    """Message date/time."""
    user_id: int
    """User identifier."""
    reply_id: Optional[MessageId]
    """Replied message identifier."""
    thread_id: int
    """Thread identifier."""
    root_message_id: Optional[MessageId]
    """Root message identifier in thread."""
    message_text: str
    """Message text content."""
    message_type: str
    """Message type."""
    message_category: MessageCategory
    """Message category."""
    quote_text: Optional[str]
    """Quoted text if present."""
    media_id: Optional[str]
    """Media attachment identifier."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    model_id: NotRequired[Optional[int]]
    """Embedding model lookup key (FK to models.model_id); ``None`` when
    not yet embedded. Absent on rows produced before ``migration_025``."""
    metadata: str
    """Optional JSON metadata. Should be valid MetadataDict"""
    markup: str
    """Message markup."""
    media_group_id: Optional[str]
    """Media group identifier."""

    # From User table
    username: str
    """User username."""
    full_name: str
    """User full name."""

    # Populated only by ChatSearchRepository (semantic-search mode)
    score: NotRequired[float]
    """Cosine similarity score (0.0 to 1.0). 0.0 in filter-only mode.
    Absent on chat-message rows produced by the other repository methods."""


class ChatUserDict(TypedDict):
    """Dictionary representing a user in a chat.

    Data from chat_user table.
    """

    chat_id: int
    """Chat identifier."""
    user_id: int
    """User identifier."""
    username: str
    """User username."""
    full_name: str
    """User full name."""
    timezone: Optional[str]
    """User timezone."""
    messages_count: int
    """Number of messages sent by user."""
    metadata: str
    """JSON metadata."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class ChatInfoDict(TypedDict):
    """Dictionary representing chat information."""

    chat_id: int
    """Chat identifier."""
    title: Optional[str]
    """Chat title."""
    username: Optional[str]
    """Chat username."""
    type: str
    """Chat type."""
    is_forum: bool
    """Whether chat is a forum."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class ChatTopicInfoDict(TypedDict):
    """Dictionary representing a chat topic information."""

    chat_id: int
    """Chat identifier."""
    topic_id: int
    """Topic identifier."""

    icon_color: Optional[int]
    """Topic icon color."""
    icon_custom_emoji_id: Optional[str]
    """Topic custom emoji icon identifier."""
    name: Optional[str]
    """Topic name."""

    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class MediaAttachmentDict(TypedDict):
    """Dictionary representing a media attachment."""

    file_unique_id: str
    """Unique file identifier."""
    file_id: Optional[str]
    """File identifier."""
    file_size: Optional[int]
    """File size in bytes."""
    media_type: str
    """Media type."""
    metadata: str
    """JSON metadata."""
    status: MediaStatus
    """Processing status."""
    mime_type: Optional[str]
    """MIME type."""
    local_url: Optional[str]
    """Local file URL."""
    prompt: Optional[str]
    """Prompt for media generation."""
    description: Optional[str]
    """Media description."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class DelayedTaskDict(TypedDict):
    """Dictionary representing a delayed task."""

    id: str
    """Task identifier."""
    delayed_ts: int
    """Delayed timestamp."""
    function: str
    """Function name to execute."""
    kwargs: str
    """JSON-serialized keyword arguments."""
    is_done: bool
    """Whether task is completed."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class WebhookUpdatesRow(TypedDict):
    """Dictionary representing a webhook_updates row.

    Each row stores one incoming Max webhook payload awaiting consumption.
    ``processed`` is an integer boolean (0/1). ``processed_at`` is ``None``
    for rows that have not yet been consumed.
    """

    id: str
    """Application-generated UUID identifying the update."""
    received_at: datetime.datetime
    """When the webhook payload was received and stored."""
    update_type: str
    """Coarse update_type tag extracted from the Max payload."""
    raw_json: str
    """Full webhook request body serialized as a JSON string."""
    processed: int
    """Whether the update has been consumed (0 = pending, 1 = processed)."""
    processed_at: Optional[datetime.datetime]
    """When the update was marked processed, or None if still pending."""


class SpamMessageDict(TypedDict):
    """Dictionary representing a spam message record."""

    chat_id: int
    """Chat identifier."""
    user_id: int
    """User identifier."""
    message_id: MessageId
    """Message identifier."""
    text: str
    """Message text."""
    reason: Union[str, SpamReason]
    """Spam reason."""
    score: float
    """Spam score."""
    confidence: float
    """Confidence level."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class ChatSummarizationCacheDict(TypedDict):
    """Dictionary representing a cached chat summarization."""

    csid: str
    """Cache identifier."""
    chat_id: int
    """Chat identifier."""
    topic_id: Optional[int]
    """Topic identifier."""
    first_message_id: MessageId
    """First message identifier in range."""
    last_message_id: MessageId
    """Last message identifier in range."""

    prompt: str
    """Summarization prompt."""
    summary: str
    """Generated summary."""

    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class CacheDict(TypedDict):
    """Weather cache entry from database."""

    key: str
    """Cache key."""
    data: str
    """JSON-serialized response data."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class CacheStorageDict(TypedDict):
    """Cache storage entry from cache_storage table."""

    namespace: str
    """Cache namespace."""
    key: str
    """Cache key."""
    value: str
    """Cached value."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class CacheType(StrEnum):
    """Cache type enum for different cache namespaces."""

    WEATHER = "weather"
    """Weather cache (coordinates -> weather data)."""
    GEOCODING = "geocoding"
    """Geocoding cache (city name -> coordinates)."""
    YANDEX_SEARCH = "yandex_search"
    """Yandex Search API Client cache (request -> Search Result)."""
    URL_CONTENT = "url_content"
    """Cached content of URL (url -> content+contentType)."""
    URL_CONTENT_CONDENSED = "url_content_condensed"
    """Cached condensed content of URL (url+max_size -> content)."""

    # Geocode Maps cache
    GM_SEARCH = "geocode_maps_search"
    """Geocode Maps search cache."""
    GM_REVERSE = "geocode_maps_reverse"
    """Geocode Maps reverse geocoding cache."""
    GM_LOOKUP = "geocode_maps_lookup"
    """Geocode Maps lookup cache."""


class DivinationLayoutDict(TypedDict):
    """Dictionary representing a cached divination layout definition.

    Layouts are cached from external divination APIs to avoid repeated API calls.
    """

    system_id: str
    """Divination system identifier (e.g., 'tarot', 'runes')."""

    layout_id: str
    """Layout name within the system."""

    name_en: str
    """English layout name."""

    name_ru: str
    """Russian layout name."""

    n_symbols: int
    """Number of symbols/positions in the layout."""

    positions: list[str]
    """List of position definitions."""

    description: Optional[str]
    """Optional layout description."""

    created_at: datetime.datetime
    """Record creation timestamp."""

    updated_at: datetime.datetime
    """Record last update timestamp."""


class ThreadResultDict(TypedDict):
    """Thread context for a single message.

    Returned by `ChatMessagesRepository.getMessageThread`. The target is
    always present; the root is only set when the target is itself a reply
    in a thread (i.e. has a non-null `root_message_id`). `thread_messages`
    always includes the target and is ordered chronologically (ascending).
    """

    root_message: Optional[ChatMessageDict]
    """Root message of the thread, or None if the target is itself a root."""
    target_message: ChatMessageDict
    """The message the caller asked about."""
    thread_messages: list[ChatMessageDict]
    """All messages in the thread, including the target, in chronological order."""


class MemoryType(StrEnum):
    """Closed set of user-memory categories.

    Stored as the TEXT ``type`` column on the ``user_memories`` table
    (see ``migration_020_user_memories``). Freeform categorisation beyond
    these is handled by the JSON ``tags`` column. Lives in the database
    layer so :class:`UserMemoryDict` (and the rest of ``internal.database``)
    can reference it without importing from ``internal.bot.models`` —
    that upward import created a circular dependency at app startup
    (``internal.database`` initialises before ``internal.bot``).

    Members:
        BIO: High-level, evolving summary of who the user is. Exactly one
            permanent bio memory is maintained per (chat, user, thread) by
            the refinement pass; the rolling-bio migration
            (``migration_020`` Backfill B) seeds it.
        PREFERENCE: A stated or inferred preference ("prefers dark mode",
            "vegan").
        FACT: A durable, non-preferential fact ("lives in Berlin",
            "works as a nurse").
        EVENT: A point-in-time happening ("got married 2024-06",
            "travelling to Tokyo in May").
        RELATIONSHIP: A connection to another person/entity ("married to
            Alex", "mentor is Dr. Lee").
    """

    BIO = "bio"
    """High-level user summary; one permanent bio maintained per (chat, user, thread)."""

    PREFERENCE = "preference"
    """A stated or inferred user preference."""

    FACT = "fact"
    """A durable, non-preferential fact about the user."""

    EVENT = "event"
    """A point-in-time happening in the user's life."""

    RELATIONSHIP = "relationship"
    """A connection between the user and another person/entity."""


class UserMemorySource(StrEnum):
    """Provenance of a row in the ``user_memories`` table.

    Records which subsystem created the memory so refinement, search, and
    audit code can distinguish user-authored facts from background-derived
    ones. Stored as the TEXT ``source`` column (see
    ``migration_020_user_memories``). Lives in the database layer for the
    same circular-import reason as :class:`MemoryType` (``internal.database``
    initialises before ``internal.bot``).

    Members:
        REFINEMENT: Created by the background refinement pass
            (``UserMemoriesHandler._runSingleRefinement``), which runs an LLM over
            recent messages and emits ``add_memory`` / ``delete_memory``
            tool calls. See ``isRefinement=True`` in the add path.
        CHAT: Created inline during an interactive conversation via the same
            memory tools, but outside the refinement cron (i.e. the LLM
            decided to remember something while answering the user).
        MIGRATION: Backfilled from the legacy ``user_data`` store by
            ``migration_020`` (Backfill A + B). Idempotent — a sentinel probe
            on ``source='migration'`` guards re-runs.
        USER: Explicitly authored or imported by the user themselves (direct
            user intent rather than system inference). Reserved for
            user-facing memory-management entry points.
    """

    REFINEMENT = "refinement"
    """Created by the background refinement cron (LLM tool calls)."""
    CHAT = "chat"
    """Created inline during an interactive conversation (LLM tool calls)."""
    MIGRATION = "migration"
    """Backfilled from the legacy user_data store by migration_020."""
    USER = "user"
    """Explicitly authored/imported by the user (direct intent)."""


class UserMemoryDict(TypedDict):
    """Row shape returned by ``UserMemoriesRepository`` read methods.

    Keys are snake_case to match DB column names (repo convention — see
    ``ChatMessageDict`` in ``internal/database/models.py``). Repository METHOD
    parameters stay camelCase per AGENTS.md; only the dict keys mirror the
    columns so the universal converter ``dbUtils.sqlToTypedDict`` can map them
    directly.

    Attributes:
        chat_id: Chat the memory belongs to.
        user_id: User the memory is about.
        thread_id: Thread scope. ``None`` for cross-thread permanent
            memories (e.g. ``user_data``-migrated facts); set to the
            originating thread for thread-specific permanent bio
            memories (``migration_020`` Backfill B).
        memory_id: App-generated UUID hex; unique within (chat_id, user_id).
        type: ``MemoryType`` string value
            (bio|preference|fact|event|relationship).
        content: Free-text memory body (source of truth for re-embedding).
        tags: Decoded list of tag strings (stored as JSON TEXT in the row).
        permanent: True if the memory is always injected into the system block.
        source: Provenance — refinement | chat | migration | user.
        model_id: Embedding model lookup key (FK to ``models.model_id``);
            ``None`` when the memory has not been embedded yet.
            Post-``migration_025`` shape: the legacy
            ``embedding_model`` / ``embedding_dimensions`` provenance pair
            was normalised into the ``models`` lookup table keyed by this
            integer.
        created_at: Creation timestamp.
        updated_at: Last-update timestamp.
        score: Cosine similarity (0.0–1.0) when returned by semantic
            ``searchMemories`` (Phase 1b); absent on rows from non-search
            methods. Mirrors ``ChatMessageDict.score``.
    """

    chat_id: int
    user_id: int
    thread_id: Optional[int]
    memory_id: str
    type: MemoryType
    content: str
    tags: list[str]
    permanent: bool
    source: UserMemorySource
    model_id: Optional[int]
    created_at: datetime.datetime
    updated_at: datetime.datetime
    score: NotRequired[float]


class ModelDict(TypedDict):
    """Row in the ``models`` embedding-provenance lookup table.

    Backs :class:`internal.database.repositories.embedding_models.EmbeddingModelsRepository`.
    The ``models`` table is created by ``migration_025`` (Phase 2 of the
    embedding-model-lookup refactor). Each row represents one distinct
    ``(model, dimensions)`` pair seen by the system; the small integer
    ``model_id`` is the FK-like key stored on every embedding-bearing row
    (``chat_messages.model_id``, ``user_memories.model_id``, and the vec0
    partition keys) so the provenance pair itself is stored exactly once.

    Keys are snake_case to match the DB column names (repo convention —
    see ``UserMemoryDict`` and ``ChatMessageDict``).

    Attributes:
        model_id: App-generated sequential integer primary key (Decision D2
            of the embedding-model-lookup refactor — small ints are more
            compact and faster as vec0 partition keys than UUID strings;
            the DB does not generate IDs).
        model: Embedding model name string (e.g. the resolved value of the
            ``EMBEDDING_MODEL`` chat setting).
        dimensions: Vector dimensionality (e.g. 384, 1024).
        created_at: Row creation timestamp (set app-side; no DB default).
    """

    model_id: int
    """App-generated sequential integer primary key."""
    model: str
    """Embedding model name string (e.g. the resolved ``EMBEDDING_MODEL`` value)."""
    dimensions: int
    """Vector dimensionality (e.g. 384, 1024)."""
    created_at: datetime.datetime
    """Row creation timestamp (set app-side; no DB default)."""
