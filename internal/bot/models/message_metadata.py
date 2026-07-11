import datetime
from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Dict, List, NotRequired, Optional, TypedDict, Union

import lib.utils as utils
from internal.database.models import ChatMessageDict, MemoryType, UserMemoryDict
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


class UserMemoriesDict(TypedDict, total=False):
    """Transient render shape for the two cohorts of resolved memories.

    Not stored on :class:`EnsuredMessage` — the canonical stored form is
    :class:`CompactMemoryIdsDict` under ``metadata["memories"]``.
    :meth:`EnsuredMessage.formatForLLM` resolves the compact IDs to content
    via ``cache.getMemoriesByIds`` at render time and emits this shape in its
    JSON output so the LLM message builder sees a single snapshot of what was
    known about the user at the time the message was processed.

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
    message under ``metadata["memories"]``. The read path resolves these IDs
    to content lazily inside :meth:`EnsuredMessage.formatForLLM` via
    ``cache.getMemoriesByIds`` at render time.

    Attributes:
        permanentIds: UUID hex strings of permanent memories.
        shortTermIds: UUID hex strings of short-term memories.
    """

    permanentIds: list[str]
    shortTermIds: list[str]


CondensedDateRangeDict = TypedDict(
    "CondensedDateRangeDict",
    {"from": float, "to": float},
)
"""Storage shape for the date range covered by a condensed summary.

Two unix-timestamp floats keyed ``from``/``to``. The JSON key ``from`` is a
Python reserved keyword, so this TypedDict uses functional syntax (class-body
syntax cannot express a field named ``from``). This is the *storage* form
persisted on :class:`CondensingDict.dateRange`; the render helper (added in a
later phase) converts these floats to ISO strings at call-time — ISO strings
are NOT pre-baked into storage.

Fields (keys):
    from: Inclusive unix-timestamp start of the covered range.
    to: Inclusive unix-timestamp end of the covered range.
"""


class CondensingDict(TypedDict):
    """Condensed-summary record persisted under ``metadata.condensedThread``
    (Path A, a list of these) or ``metadata.randomContext`` (Path B, a single
    one).

    Legacy rows (pre-feature) carry only ``text``/``tillMessageId``/``tillTS``
    and are read defensively — readers fall back gracefully when the new fields
    are absent. New writes populate ``messageIds`` as the authoritative coverage
    list; ``tillMessageId``/``tillTS`` are kept for backwards-compat reading by
    older code paths and as a cheap boundary marker.

    Required fields (present on ALL rows, legacy and new):
        text: The condensing model's summary text (unchanged).
        tillMessageId: Legacy boundary marker — last covered message ID. Kept
            for backwards-compat reads; not authoritative on new writes.
        tillTS: Legacy boundary marker — unix timestamp of the last covered
            message. Kept for backwards-compat reads.

    Optional fields (``NotRequired`` — absent on legacy rows, present on new):
        messageIds: Authoritative list of covered message IDs. This is the
            canonical coverage list on new writes.
        participants: Sorted unique sender logins of covered messages.
        dateRange: :class:`CondensedDateRangeDict` — unix-timestamp pair
            (``from``/``to`` floats) covering the summarized messages.
        messageCount: Number of original messages this summary covers.
    """

    text: str
    tillMessageId: MessageId
    tillTS: float
    messageIds: NotRequired[List[MessageId]]
    participants: NotRequired[List[str]]
    dateRange: NotRequired[CondensedDateRangeDict]
    messageCount: NotRequired[int]


class CondensedSummaryKind(StrEnum):
    """Render-side discriminator for the condensed-summary JSON shape.

    Deliberately SEPARATE from :class:`MessageType` (which classifies real
    message media: text/image/sticker). ``condensed`` is a render-only
    construct for injected summaries — the condensed JSON shape is
    structurally disjoint from real user messages (no login/name/messageId
    keys; carries coveredMessageIds/participants/dateRange/messageCount/
    summary instead). The ``type`` key on a condensed summary therefore never
    collides with the ``type`` key on a real message because the surrounding
    object shapes are unambiguously different.
    """

    CONDENSED = "condensed"


def renderCondensedSummary(data: Union[CondensingDict, str]) -> str:
    """Render a condensed-summary record as a JSON string for the LLM.

    Produces a JSON object shape consistent with real user messages
    (:meth:`EnsuredMessage.formatForLLM` JSON branch,
    ``ensured_message.py:1158-1177``) so the LLM sees a uniform format.
    Legacy ``str`` input (old ``randomContext`` rows) is rendered as the new
    shape with metadata fields omitted — graceful degradation, consistent
    output shape, and the LLM simply does not call ``get_messages_by_ids``
    for summaries with no ``coveredMessageIds``.

    The falsy-drop convention mirrors ``formatForLLM`` exactly (``if v`` at
    ``ensured_message.py:1173``): ``coveredMessageIds: []``, ``messageCount: 0``,
    ``participants: []``, and absent ``dateRange`` are all OMITTED from the
    output — never emitted as ``null`` or empty.

    Args:
        data: A :class:`CondensingDict` (new writes, carries optional
            ``messageIds``/``participants``/``dateRange``/``messageCount``)
            or a legacy ``str`` (old ``randomContext`` rows).

    Returns:
        JSON string of shape::

            {
              "type": "condensed",
              "coveredMessageIds": ["100", "101", ...],
              "participants": ["alice", "bob"],
              "dateRange": {"from": "<ISO>", "to": "<ISO>"},
              "messageCount": 42,
              "summary": "<condensing model text>"
            }

        Falsy/absent fields are omitted. ``type`` and ``summary`` are always
        present (a summary with no summary text is meaningless; the minimal
        shape is ``{"type":"condensed","summary":"..."}``). For a legacy
        ``str`` input, only ``type`` and ``summary`` are emitted.
        Serialised via :func:`utils.jsonDumps` (``compact=False``,
        ``sort_keys=True``) — same as the real-message renderer.
    """
    if isinstance(data, str):
        # Legacy randomContext (flat str) → minimal shape.
        ret: Dict[str, Any] = {
            "type": CondensedSummaryKind.CONDENSED,
            "summary": data,
        }
    else:
        # New CondensingDict — extract optional metadata, drop falsy.
        messageIds = data.get("messageIds")
        coveredMessageIds = [mid.asMessageId() for mid in messageIds] if messageIds else []

        dateRangeRaw = data.get("dateRange")
        dateRange: Optional[Dict[str, str]] = None
        if dateRangeRaw:
            dateRange = {
                "from": datetime.datetime.fromtimestamp(dateRangeRaw["from"], datetime.timezone.utc).isoformat(),
                "to": datetime.datetime.fromtimestamp(dateRangeRaw["to"], datetime.timezone.utc).isoformat(),
            }

        ret = {
            k: v
            for k, v in {
                "type": CondensedSummaryKind.CONDENSED,
                "coveredMessageIds": coveredMessageIds,
                "participants": data.get("participants"),
                "dateRange": dateRange,
                "messageCount": data.get("messageCount", 0),
            }.items()
            if v
        }
        # summary is hoisted out of the falsy-drop so it is ALWAYS present,
        # honoring the contract that the minimal shape is
        # {"type":"condensed","summary":"..."} — a summary with no summary
        # text is meaningless.
        ret["summary"] = data["text"]

    return utils.jsonDumps(ret, compact=False)


class MetadataDict(TypedDict, total=False):
    """TypedDict for message metadata.

    Stores optional metadata associated with a message, including condensed
    thread information, random context, forwarding details, and tool usage history.

    Attributes:
        condensedThread: List of condensed thread entries
        randomContext: Random context for the message. New writes store a single
            :class:`CondensingDict` (Path B reshape); legacy rows store a flat
            ``str`` and are read defensively. The reader handles both shapes.
        forwardedFrom: Dictionary containing forwarding information
        messagePrefix: Prefix text prepended to the message
        usedTools: List of tool usage records from AI interactions
        memories: Compact memory IDs (:class:`CompactMemoryIdsDict`),
            resolved to content lazily by :meth:`EnsuredMessage.formatForLLM`
            via ``cache.getMemoriesByIds`` at render time.
    """

    condensedThread: List[CondensingDict]
    randomContext: Union[str, CondensingDict]
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


def buildCondensingFields(
    entries: Sequence[Optional[Union[ChatMessageDict, "CondensingDict"]]],
) -> Dict[str, Any]:
    """Compute messageIds/participants/dateRange/messageCount from covered entries.

    Handles both raw message rows and pre-existing condensed summaries
    (re-condense cascade union). Pure function; zero DB/LLM cost. For legacy
    CondensingDict entries lacking the new fields, degrades gracefully.

    The caller slices its ``indexToEntry`` parallel list using a
    :class:`CondenseBatchCoverage` index range, then passes the slice here.
    The returned dict is merged into a :class:`CondensingDict` alongside
    ``text``/``tillMessageId``/``tillTS``.

    Entry kind discrimination: a :class:`ChatMessageDict` row carries the key
    ``"message_id"`` (the raw DB column); a :class:`CondensingDict` does not —
    it carries ``"tillMessageId"`` and optionally ``"messageIds"``. This is the
    runtime discriminator used to branch.

    Args:
        entries: The covered entries — each is either a ChatMessageDict (raw
            source message) or a CondensingDict (a pre-existing summary being
            re-merged). Mixed lists are allowed (a re-condense batch can span
            old summaries and raw messages). ``None`` entries (system-prompt
            positions from the parallel index list) are silently skipped.

    Returns:
        Dict with keys ``messageIds`` (List[MessageId]), ``participants``
        (List[str], sorted unique), ``dateRange`` (CondensedDateRangeDict or
        absent if no dates), ``messageCount`` (int — number of UNIQUE original
        messages covered; raw rows are counted by distinct ``message_id`` so a
        row that appears multiple times in the parallel index list due to
        multi-emit is counted once; summary entries contribute their stored
        count). Caller merges this into a CondensingDict alongside
        ``text``/``tillMessageId``/``tillTS``.
    """
    messageIds: List[MessageId] = []
    participants: set[str] = set()
    timestamps: List[float] = []
    # Raw-row contribution to messageCount is the number of UNIQUE original
    # message_ids (callers build parallel index lists with ``[row] * n`` to tag
    # every emitted ModelMessage, so one original message can appear several
    # times). Summary entries contribute their own stored (already-unique) count.
    rawMessageIds: set[MessageId] = set()
    summaryCount = 0

    for entry in entries:
        if entry is None:
            continue

        if "message_id" in entry:
            # --- ChatMessageDict (raw source row) ---
            row: ChatMessageDict = entry  # type: ignore[assignment]
            msgId = row["message_id"]
            if msgId not in messageIds:
                messageIds.append(msgId)
            rawMessageIds.add(msgId)
            username = row.get("username", "")
            if username:
                participants.add(username)
            timestamps.append(row["date"].timestamp())
        else:
            # --- CondensingDict (pre-existing summary being re-merged) ---
            summary: CondensingDict = entry  # type: ignore[assignment]
            existingIds = summary.get("messageIds")
            if existingIds:
                for mid in existingIds:
                    if mid not in messageIds:
                        messageIds.append(mid)
            elif "tillMessageId" in summary:
                # Legacy fallback: no messageIds field, use boundary marker.
                tmid = summary["tillMessageId"]
                if tmid not in messageIds:
                    messageIds.append(tmid)

            for p in summary.get("participants", []):
                participants.add(p)

            dr = summary.get("dateRange")
            if dr:
                timestamps.append(dr["from"])
                timestamps.append(dr["to"])

            summaryCount += summary.get("messageCount", 0)

    messageCount = len(rawMessageIds) + summaryCount
    result: Dict[str, Any] = {
        "messageIds": messageIds,
        "participants": sorted(participants),
        "messageCount": messageCount,
    }
    if timestamps:
        result["dateRange"] = {"from": min(timestamps), "to": max(timestamps)}  # type: ignore[typeddict-item]

    return result
