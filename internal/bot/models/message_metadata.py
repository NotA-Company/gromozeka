"""TypedDicts and helpers for message metadata (condensed summaries, memories, forwarding)."""

import datetime
from collections.abc import Iterable, MutableSet
from enum import StrEnum
from typing import Any, Dict, List, NotRequired, Optional, TypedDict, Union

import lib.utils as utils
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


CondensedDateRangeDict = TypedDict("CondensedDateRangeDict", {"from": float, "to": float})
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

    Legacy rows (pre-feature) carry ``text``/``tillMessageId``/``tillTS``
    and are read defensively — readers fall back gracefully when the coverage
    fields are absent. New writes (produced by
    :func:`generateCondensingDict`) populate ``messageIds`` as the
    authoritative coverage list; ``tillMessageId``/``tillTS`` are NOT set by
    ``generateCondensingDict`` (left for legacy compatibility only).

    Required field (present on ALL rows, legacy and new):
        text: The condensing model's summary text.

    Optional fields (``NotRequired``):
        tillMessageId: Legacy boundary marker — last covered message ID.
            Present on old rows and on caller-set dicts, but NOT set by
            :func:`generateCondensingDict`; kept for backwards-compat reads.
        tillTS: Legacy boundary marker — unix timestamp of the last covered
            message. Present on old rows and on caller-set dicts, but NOT set
            by :func:`generateCondensingDict`; kept for backwards-compat reads.
        messageIds: Authoritative list of covered message IDs. Populated by
            :func:`generateCondensingDict` when source data is available;
            this is the canonical coverage list on new writes.
        participants: Sorted unique sender logins of covered messages.
            Populated by :func:`generateCondensingDict` when available.
        dateRange: :class:`CondensedDateRangeDict` — unix-timestamp pair
            (``from``/``to`` floats) covering the summarized messages.
            Populated by :func:`generateCondensingDict` when available.
        messageCount: Number of processed ModelMessage positions this summary
            covers (includes auxiliary tool-history emissions, not just original
            user/assistant messages). Populated by
            :func:`generateCondensingDict` when available.
    """

    text: str
    tillMessageId: NotRequired[MessageId]
    tillTS: NotRequired[float]
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


def renderCondensedSummary(data: CondensingDict) -> str:
    """Render a condensed-summary record as a JSON string for the LLM.

    Produces a JSON object shape consistent with real user messages
    (:meth:`EnsuredMessage.formatForLLM` JSON branch,
    ``ensured_message.py:1158-1177``) so the LLM sees a uniform format.

    The falsy-drop convention mirrors ``formatForLLM`` exactly (``if v`` at
    ``ensured_message.py:1173``): ``coveredMessageIds: []``, ``messageCount: 0``,
    ``participants: []``, and absent ``dateRange`` are all OMITTED from the
    output — never emitted as ``null`` or empty.

    The renderer accepts only :class:`CondensingDict`. Callers that hold a
    legacy ``str`` row (old ``randomContext`` pre-feature) are responsible
    for pre-wrapping it into ``CondensingDict(text=...)`` before calling
    this function — the sole caller
    (:meth:`EnsuredMessage.formatForLLM`, ``ensured_message.py:~1231``)
    does exactly that.

    Args:
        data: A :class:`CondensingDict` carrying the summary text and
            optional ``messageIds`` / ``participants`` / ``dateRange`` /
            ``messageCount`` coverage fields.

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
        shape is ``{"type":"condensed","summary":"..."}``).
        Serialised via :func:`utils.jsonDumps` (``compact=False``,
        ``sort_keys=True``) — same as the real-message renderer.
    """
    # New CondensingDict — extract optional metadata, drop falsy.
    messageIds = data.get("messageIds", [])
    coveredMessageIds = [mid.asMessageId() for mid in messageIds]

    dateRangeRaw = data.get("dateRange")
    dateRange: Optional[Dict[str, str]] = None
    if dateRangeRaw:
        dateRange = {
            "from": datetime.datetime.fromtimestamp(dateRangeRaw["from"], datetime.timezone.utc).isoformat(),
            "to": datetime.datetime.fromtimestamp(dateRangeRaw["to"], datetime.timezone.utc).isoformat(),
        }

    ret: Dict[str, Any] = {
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


def mergeCondensingDicts(dictList: Iterable[CondensingDict]) -> CondensingDict:
    """Merge a list of CondensingDicts into a single CondensingDict.

    Performs a field-wise union of the inputs:

    - ``text``: ``"\\n".join`` of each input's ``text`` (order preserved).
    - ``messageIds``: concatenation of all inputs' ``messageIds`` lists (plain
      ``list.extend`` at the implementation site — NO de-dup; duplicates are
      preserved if present in the inputs).
    - ``participants``: set-unique union of all inputs' ``participants`` (the
      implementation accumulates into a ``MutableSet[str]`` then emits
      ``list(participants)`` — iteration order is UNSPECIFIED, NOT sorted;
      callers must not rely on any particular ordering).
    - ``dateRange``: ``{"from": min(all froms), "to": max(all tos)}`` —
      omitted entirely when no input carries a ``dateRange``.
    - ``messageCount``: arithmetic sum of all inputs' ``messageCount``.

    The legacy boundary markers (``tillMessageId`` / ``tillTS``) are
    intentionally NOT carried over — the merged dict represents the union
    of all inputs and those single-value markers are meaningless in that
    context.

    Args:
        dictList: The list (or any iterable) of CondensingDicts to merge.

    Returns:
        The merged CondensingDict. When the input iterable is empty, the
        result is ``CondensingDict(text="")`` with no coverage fields.
    """
    text: str = ""
    coveredMessageIds: List[MessageId] = []
    participants: MutableSet[str] = set()
    fromDate: Optional[float] = None
    toDate: Optional[float] = None
    messageCount: int = 0
    for cDict in dictList:
        text += "\n" + cDict["text"]
        if "messageIds" in cDict:
            coveredMessageIds.extend(cDict["messageIds"])
        if "participants" in cDict:
            participants.update(cDict["participants"])
        if "dateRange" in cDict:
            if fromDate is None or cDict["dateRange"]["from"] < fromDate:
                fromDate = cDict["dateRange"]["from"]
            if toDate is None or cDict["dateRange"]["to"] > toDate:
                toDate = cDict["dateRange"]["to"]
        if "messageCount" in cDict:
            messageCount += cDict["messageCount"]
    ret = CondensingDict(
        text=text.strip(),
    )
    if coveredMessageIds:
        ret["messageIds"] = coveredMessageIds
    if participants:
        ret["participants"] = list(participants)
    if fromDate is not None and toDate is not None:
        ret["dateRange"] = {"from": fromDate, "to": toDate}
    if messageCount:
        ret["messageCount"] = messageCount
    return ret
