from typing import Any, Dict, List, NotRequired, TypedDict

from internal.database.models import MemoryType, UserMemoryDict
from internal.models import MessageId


class SingleMemoryDict(TypedDict):
    """A single user-memory entry in its slimmed-down, bot-facing form.

    Produced by :func:`convertDBMemoryToSingleMemoryDict` from a heavier
    :class:`UserMemoryDict` row: it drops the DB plumbing keys
    (``chat_id`` / ``user_id`` / timestamps / embedding metadata) and keeps
    only what the bot layer consumes — the category, content, tags, and the
    optional provenance/search fields. Carried through
    :class:`UserMemoriesDict` into :class:`MetadataDict.memories` and the
    permanent-memories cache in :class:`CacheService`.

    Attributes:
        id: App-generated memory UUID hex; only present when the converter
            was called with ``keepId=True`` (e.g. so an LLM delete tool can
            target a row by id). Absent on injected/in-memory snapshots.
        type: Memory category (one of :class:`MemoryType`).
        tags: Freeform tag list (lower-cased before persistence); may be
            omitted by callers that only need ``type`` + ``content``.
        content: Free-text memory body — the source of truth for both
            injection into the system block and re-embedding.
        score: Cosine similarity (0.0–1.0) when this entry came back from a
            semantic ``searchMemories`` query; absent on non-search reads.
    """

    id: NotRequired[str]
    type: MemoryType
    tags: NotRequired[list[str]]
    content: str
    score: NotRequired[float]


class UserMemoriesDict(TypedDict):
    """Container for the two cohorts of memories attached to a message.

    Stored under :class:`MetadataDict`'s ``memories`` key and on
    :class:`EnsuredMessage.userMemories`, so handlers and the LLM message
    builder see a single snapshot of what was known about the user at the
    time the message was processed.

    Attributes:
        permanent: Memories flagged ``permanent=True`` — always injected into
            the system block (bio, durable facts, etc.).
        shortTerm: Non-permanent memories relevant to the current message
            (e.g. recent additions or semantic-search hits used for context).
    """

    permanent: list[SingleMemoryDict]
    shortTerm: list[SingleMemoryDict]


class CompactMemoryIdsDict(TypedDict):
    """Compact per-message memory ID lists (the compact storage form).

    The memory-compaction feature stores memory IDs (not full content) per
    message under ``metadata["memories"]``. The read path
    (:meth:`EnsuredMessage.resolveMemories`) resolves these IDs to content
    via the cache at render time.

    Attributes:
        permanentIds: UUID hex strings of permanent memories.
        shortTermIds: UUID hex strings of short-term memories.
    """

    permanentIds: list[str]
    shortTermIds: list[str]


class CondensingDict(TypedDict):
    """TypedDict for condensed thread information.

    Stores thread condensing data including the condensed text and the
    boundary message ID and timestamp where condensing occurred.

    Attributes:
        text: The condensed thread text
        tillMessageId: The message ID up to which thread was condensed
        tillTS: The timestamp up to which thread was condensed
    """

    text: str
    tillMessageId: MessageId
    tillTS: float


class MetadataDict(TypedDict, total=False):
    """TypedDict for message metadata.

    Stores optional metadata associated with a message, including condensed
    thread information, random context, forwarding details, and tool usage history.

    Attributes:
        condensedThread: List of condensed thread entries
        randomContext: Random context string for the message
        forwardedFrom: Dictionary containing forwarding information
        messagePrefix: Prefix text prepended to the message
        usedTools: List of tool usage records from AI interactions
        memories: User memories — either the content form
            (:class:`UserMemoriesDict`, legacy/pre-compaction) or the compact
            ID form (:class:`CompactMemoryIdsDict`, post-compaction). The read
            path detects the shape at render time.
    """

    condensedThread: List[CondensingDict]
    randomContext: str
    forwardedFrom: Dict[str, Any]
    messagePrefix: str
    usedTools: List[Dict[str, Any]]
    memories: CompactMemoryIdsDict


def convertDBMemoryToSingleMemoryDict(dbMemory: UserMemoryDict, *, keepId: bool = False) -> SingleMemoryDict:
    """Convert a UserMemoryDict from the database to a SingleMemoryDict.

    Args:
        dbMemory: The UserMemoryDict to convert.

    Returns:
        The converted SingleMemoryDict.
    """
    ret: SingleMemoryDict = {
        "type": MemoryType(dbMemory["type"]),
        "tags": dbMemory["tags"],
        "content": dbMemory["content"],
    }
    if "score" in dbMemory:
        ret["score"] = dbMemory["score"]
    if keepId:
        ret["id"] = dbMemory["memory_id"]

    return ret
