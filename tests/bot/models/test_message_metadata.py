"""Tests for :func:`renderCondensedSummary` and condensed-context injection.

Covers the JSON renderer for condensed summaries (``renderCondensedSummary``),
Path B ``randomContext`` injection in ``toModelMessageList``, and Path A
injection-site wiring. Uses crafted dict literals that match the TypedDict
shapes.
"""

import datetime
import inspect
import json

from internal.bot.common.handlers.base import BaseBotHandler
from internal.bot.models import ChatType, EnsuredMessage, MessageRecipient, MessageSender
from internal.bot.models.message_metadata import (
    CondensedSummaryKind,
    CondensingDict,
    mergeCondensingDicts,
    renderCondensedSummary,
)
from internal.database import Database
from internal.database.models import ChatMessageDict, MessageCategory
from internal.models import MessageId
from lib.db.utils import DEFAULT_THREAD_ID

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _makeRow(
    messageId: int,
    username: str,
    ts: float,
    *,
    chatId: int = 1,
    userId: int = 100,
) -> ChatMessageDict:
    """Build a minimal ChatMessageDict-compatible dict for testing.

    Args:
        messageId: Message ID integer.
        username: Sender login.
        ts: Unix timestamp for the message date.
        chatId: Chat ID (default 1).
        userId: User ID (default 100).

    Returns:
        A dict matching the ChatMessageDict shape.
    """
    ret: ChatMessageDict = {
        "chat_id": chatId,
        "message_id": MessageId(messageId),
        "date": datetime.datetime.fromtimestamp(ts, datetime.timezone.utc),
        "user_id": userId,
        "reply_id": None,
        "thread_id": 0,
        "root_message_id": None,
        "message_text": f"msg-{messageId}",
        "message_type": "text",
        "message_category": MessageCategory.USER,
        "quote_text": None,
        "media_id": None,
        "created_at": datetime.datetime.fromtimestamp(ts, datetime.timezone.utc),
        "metadata": "{}",
        "markup": "",
        "media_group_id": None,
        "username": username,
        "full_name": username,
    }
    return ret


def _makeNewSummary(
    text: str,
    messageIds: list,
    participants: list,
    dateRange: dict | None,
    messageCount: int,
    *,
    tillMessageId: int | None = None,
    tillTS: float | None = None,
) -> CondensingDict:
    """Build a CondensingDict (post-feature) for testing.

    Args:
        text: Summary text.
        messageIds: Covered message ID list.
        participants: Sorted unique participants.
        dateRange: ``{"from": float, "to": float}`` or None.
        messageCount: Number of original messages covered.
        tillMessageId: Legacy boundary marker (defaults to last messageId).
        tillTS: Legacy boundary timestamp (defaults to dateRange["to"]).

    Returns:
        A dict matching the CondensingDict shape with all new fields.
    """
    ret: CondensingDict = {
        "text": text,
        "tillMessageId": MessageId(
            tillMessageId if tillMessageId is not None else (messageIds[-1] if messageIds else 0)
        ),
        "tillTS": tillTS if tillTS is not None else (dateRange["to"] if dateRange else 0.0),
        "messageIds": messageIds,
        "participants": participants,
        "messageCount": messageCount,
    }
    if dateRange:
        ret["dateRange"] = dateRange  # type: ignore[typeddict-item]
    return ret


def _makeLegacySummary(text: str, tillMessageId: int, tillTS: float) -> CondensingDict:
    """Build a legacy CondensingDict (pre-feature, only 3 required fields).

    Args:
        text: Summary text.
        tillMessageId: Legacy boundary marker.
        tillTS: Legacy boundary timestamp.

    Returns:
        A dict matching the legacy CondensingDict shape (no new fields).
    """
    ret: CondensingDict = {
        "text": text,
        "tillMessageId": MessageId(tillMessageId),
        "tillTS": tillTS,
    }
    return ret


# ---------------------------------------------------------------------------
# Phase 4: renderCondensedSummary — JSON renderer for condensed summaries
# ---------------------------------------------------------------------------


class TestRenderCondensedSummary:
    """Unit tests for :func:`renderCondensedSummary`.

    The renderer mirrors :meth:`EnsuredMessage.formatForLLM` JSON branch
    (falsy-drop via ``if v``, serialised via ``utils.jsonDumps(compact=False)``)
    so the LLM sees a uniform JSON format — resolving the latent asymmetry
    where real user messages were JSON but summaries were raw text.
    """

    def testFullNewShape(self):
        """Full CondensingDict → all fields present, correct types, type:"condensed"."""
        summary = _makeNewSummary(
            "Alice and Bob discussed the plan",
            [MessageId(100), MessageId(101), MessageId(102)],
            ["alice", "bob"],
            {"from": 1000.0, "to": 3000.0},
            3,
        )
        result = renderCondensedSummary(summary)
        parsed = json.loads(result)

        assert parsed["type"] == "condensed"
        assert parsed["summary"] == "Alice and Bob discussed the plan"
        assert parsed["coveredMessageIds"] == [100, 101, 102]
        assert parsed["participants"] == ["alice", "bob"]
        assert parsed["messageCount"] == 3
        assert isinstance(parsed["dateRange"], dict)

    def testDateRangeAbsent(self):
        """dateRange absent → key omitted entirely (NOT null)."""
        summary = _makeNewSummary(
            "Summary without date info",
            [MessageId(1)],
            ["alice"],
            None,
            1,
        )
        result = renderCondensedSummary(summary)
        parsed = json.loads(result)

        assert "dateRange" not in parsed

    def testEmptyMessageIdsAndZeroMessageCountOmitted(self):
        """Empty messageIds / 0 messageCount / empty participants → omitted (falsy-drop)."""
        summary = _makeNewSummary(
            "Summary with no metadata",
            [],
            [],
            None,
            0,
        )
        result = renderCondensedSummary(summary)
        parsed = json.loads(result)

        assert "coveredMessageIds" not in parsed
        assert "messageCount" not in parsed
        assert "participants" not in parsed
        assert "dateRange" not in parsed
        # type and summary always present
        assert parsed["type"] == "condensed"
        assert parsed["summary"] == "Summary with no metadata"

    def testEmptyTextSummaryKeyStillPresent(self):
        """Regression: empty ``text`` → ``summary`` key still present (value "").

        The dict-path falsy-drop (``if v``) previously included ``summary``, so
        when ``data["text"]`` was the empty string ``summary`` got dropped —
        contradicting the design contract that a condensed summary's minimal
        shape is ``{"type":"condensed","summary":"..."}`` and that ``summary``
        is always present. ``summary`` is now hoisted out of the falsy-drop so
        it is emitted unconditionally. This test locks that in.
        """
        summary = _makeNewSummary(
            "",
            [],
            [],
            None,
            0,
        )
        result = renderCondensedSummary(summary)
        parsed = json.loads(result)

        # summary MUST be present even though its value is the empty string.
        assert "summary" in parsed
        assert parsed["summary"] == ""
        # type is always present too.
        assert parsed["type"] == "condensed"

    def testValidJSONRoundTrip(self):
        """Output is valid JSON (round-trip via json.loads)."""
        summary = _makeNewSummary(
            'Summary with "quotes" and special chars: \\n \\t',
            [MessageId(1), MessageId(2)],
            ["alice"],
            {"from": 1000.0, "to": 2000.0},
            2,
        )
        result = renderCondensedSummary(summary)
        # Must not raise
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert parsed["summary"] == 'Summary with "quotes" and special chars: \\n \\t'

    def testDateRangeISOFormat(self):
        """dateRange timestamps converted to ISO strings with +00:00 offset."""
        summary = _makeNewSummary(
            "Summary",
            [MessageId(1)],
            ["alice"],
            {"from": 1000.0, "to": 3000.0},
            1,
        )
        result = renderCondensedSummary(summary)
        parsed = json.loads(result)

        # 1000.0 seconds from epoch = 1970-01-01T00:16:40+00:00
        assert parsed["dateRange"]["from"] == "1970-01-01T00:16:40+00:00"
        # 3000.0 seconds from epoch = 1970-01-01T00:50:00+00:00
        assert parsed["dateRange"]["to"] == "1970-01-01T00:50:00+00:00"

    def testCoveredMessageIdsViaAsMessageId(self):
        """coveredMessageIds serialized via MessageId.asMessageId() — ints for numeric, strs for non-numeric."""
        # Telegram-style numeric IDs → serialized as JSON ints
        summary = _makeNewSummary(
            "Summary",
            [MessageId(100), MessageId(200)],
            ["alice"],
            {"from": 1000.0, "to": 2000.0},
            2,
        )
        result = renderCondensedSummary(summary)
        parsed = json.loads(result)
        assert parsed["coveredMessageIds"] == [100, 200]

        # Max-style string IDs → serialized as JSON strings
        summaryStr: CondensingDict = {
            "text": "Summary",
            "tillMessageId": MessageId("max-123"),
            "tillTS": 2000.0,
            "messageIds": [MessageId("max-100"), MessageId("max-200")],
            "participants": ["alice"],
            "messageCount": 2,
        }
        resultStr = renderCondensedSummary(summaryStr)
        parsedStr = json.loads(resultStr)
        assert parsedStr["coveredMessageIds"] == ["max-100", "max-200"]

    def testFalsyDropMatchesFormatForLLMConvention(self):
        """Falsy-drop: None participants, 0 count, empty list → all omitted."""
        # Craft a dict where participants is absent (legacy), messageIds absent,
        # messageCount absent — only text/tillMessageId/tillTS present.
        legacy = _makeLegacySummary("Legacy summary", 42, 1234.0)
        result = renderCondensedSummary(legacy)
        parsed = json.loads(result)

        # Only type and summary survive the falsy-drop
        assert set(parsed.keys()) == {"type", "summary"}

    def testLegacyCondensingDictMinimalShape(self):
        """Legacy 3-field CondensingDict (backwards-compat) → summary only, metadata omitted."""
        legacy = _makeLegacySummary("Legacy condensing entry", 99, 5678.0)
        result = renderCondensedSummary(legacy)
        parsed = json.loads(result)

        assert parsed["type"] == "condensed"
        assert parsed["summary"] == "Legacy condensing entry"
        assert "coveredMessageIds" not in parsed
        assert "participants" not in parsed
        assert "dateRange" not in parsed
        assert "messageCount" not in parsed

    def testCondensedSummaryKindValue(self):
        """CondensedSummaryKind.CONDENSED == 'condensed' (string value for StrEnum)."""
        assert CondensedSummaryKind.CONDENSED == "condensed"
        assert str(CondensedSummaryKind.CONDENSED) == "condensed"

    def testParticipantsPresentWhenNonEmpty(self):
        """Non-empty participants list → included in output."""
        summary = _makeNewSummary(
            "Summary",
            [MessageId(1)],
            ["alice", "bob", "carol"],
            {"from": 1000.0, "to": 2000.0},
            1,
        )
        result = renderCondensedSummary(summary)
        parsed = json.loads(result)

        assert parsed["participants"] == ["alice", "bob", "carol"]


# ---------------------------------------------------------------------------
# mergeCondensingDicts — field-wise union of CondensingDicts
# ---------------------------------------------------------------------------


class TestMergeCondensingDicts:
    """Unit tests for :func:`mergeCondensingDicts`.

    Covers the field-wise union: ``text`` newline-join, ``messageIds``
    de-duplication (first-seen order keyed on :meth:`MessageId.asStr`),
    ``participants`` unique union, ``dateRange`` min/max, ``messageCount``
    arithmetic sum, and the empty-input fallback.
    """

    def testEmptyListReturnsTextOnlyDict(self):
        """Empty input iterable -> ``CondensingDict(text="")`` with no coverage fields.

        Guards the boundary: no inputs means no union to compute, so every
        coverage field (messageIds/participants/dateRange/messageCount) is
        falsy and therefore omitted from the result.
        """
        merged = mergeCondensingDicts([])

        assert merged["text"] == ""
        assert "messageIds" not in merged
        assert "participants" not in merged
        assert "dateRange" not in merged
        assert "messageCount" not in merged

    def testOverlappingParticipantsUnionAndDateRangeMinMax(self):
        """participants -> unique union (sorted compare); dateRange -> global min(from)/max(to).

        Both inputs carry overlapping participants and partially-overlapping
        date ranges. The merged ``participants`` must collapse to the unique
        set (storage order is set-iteration, so the assertion sorts both
        sides); ``dateRange`` must span the global min ``from`` and global
        max ``to``.
        """
        a: CondensingDict = {
            "text": "A",
            "participants": ["alice", "bob"],
            "dateRange": {"from": 1000.0, "to": 2000.0},
            "messageCount": 1,
        }
        b: CondensingDict = {
            "text": "B",
            "participants": ["bob", "carol"],
            "dateRange": {"from": 500.0, "to": 3000.0},
            "messageCount": 1,
        }
        merged = mergeCondensingDicts([a, b])

        assert sorted(merged.get("participants", [])) == ["alice", "bob", "carol"]
        dateRange = merged.get("dateRange")
        assert dateRange is not None
        assert dateRange["from"] == 500.0
        assert dateRange["to"] == 3000.0
        assert merged.get("messageCount", 0) == 2


# ---------------------------------------------------------------------------
# Path B integration: toModelMessageList randomContext injection
# ---------------------------------------------------------------------------


def _makeEnsuredMessageWithRandomContext(randomContext: object) -> EnsuredMessage:
    """Build a minimal EnsuredMessage with a given randomContext in metadata.

    Args:
        randomContext: The value to store under metadata["randomContext"].
            Can be a CondensingDict (new writes) or a legacy str.

    Returns:
        An EnsuredMessage with no media (so formatForLLM never touches DB).
    """
    ensuredMessage = EnsuredMessage(
        sender=MessageSender(id=7, name="Alice", username="@alice"),
        recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
        messageId=42,
        date=datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
        messageText="hello",
    )
    ensuredMessage.threadId = DEFAULT_THREAD_ID
    ensuredMessage.metadata["randomContext"] = randomContext  # type: ignore[typeddict-item]
    return ensuredMessage


class TestPathBInjectionSite:
    """Path B: ``randomContext`` in :meth:`toModelMessageList` → JSON via renderer.

    The randomContext injection is the FIRST ModelMessage appended in
    ``toModelMessageList`` (before tools history and the main message).
    After Phase 4, it must be JSON (via ``renderCondensedSummary``) rather
    than raw text.
    """

    async def testNewShapeRandomContextInjectsJSON(self, testDatabase: Database):
        """CondensingDict in randomContext → first ModelMessage is JSON with type:"condensed"."""
        ensuredMessage = _makeEnsuredMessageWithRandomContext(
            randomContext={
                "text": "Summary of earlier discussion",
                "tillMessageId": MessageId(50),
                "tillTS": 1000.0,
                "messageIds": [MessageId(10), MessageId(11)],
                "participants": ["alice", "bob"],
                "dateRange": {"from": 500.0, "to": 1000.0},
                "messageCount": 2,
            }
        )
        messages = await ensuredMessage.toModelMessageList(testDatabase, cache=None, excludeMemoryIds=set())

        # First message is the randomContext injection
        assert messages[0].role == "user"
        parsed = json.loads(messages[0].content)
        assert parsed["type"] == "condensed"
        assert parsed["summary"] == "Summary of earlier discussion"
        assert parsed["coveredMessageIds"] == [10, 11]
        assert parsed["participants"] == ["alice", "bob"]
        assert parsed["messageCount"] == 2

    async def testLegacyStrRandomContextInjectsJSON(self, testDatabase: Database):
        """Legacy str in randomContext → first ModelMessage is JSON with summary only."""
        ensuredMessage = _makeEnsuredMessageWithRandomContext(randomContext="Old summary text")
        messages = await ensuredMessage.toModelMessageList(testDatabase, cache=None, excludeMemoryIds=set())

        assert messages[0].role == "user"
        parsed = json.loads(messages[0].content)
        assert parsed["type"] == "condensed"
        assert parsed["summary"] == "Old summary text"
        assert "coveredMessageIds" not in parsed
        assert "participants" not in parsed

    async def testNoRandomContextInjectsNothing(self, testDatabase: Database):
        """No randomContext in metadata → no extra ModelMessage injected."""
        ensuredMessage = EnsuredMessage(
            sender=MessageSender(id=7, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
            messageId=42,
            date=datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="hello",
        )
        ensuredMessage.threadId = DEFAULT_THREAD_ID
        messages = await ensuredMessage.toModelMessageList(testDatabase, cache=None, excludeMemoryIds=set())

        # With no randomContext and no tools history, there should be exactly
        # one message (the main message itself).
        assert len(messages) == 1


# ---------------------------------------------------------------------------
# Path A wiring: base.py injection site uses renderCondensedSummary
# ---------------------------------------------------------------------------


class TestPathAWiring:
    """Verify Path A (base.py) injection site is wired to :func:`renderCondensedSummary`.

    Driving the full ``getThreadByMessageForLLM`` requires heavy handler mocking
    (DB, cache, LLM service, chat settings). Instead, this verifies the import
    wiring is correct — the renderer function reference in ``base.py`` is the
    same object as the one from ``message_metadata``. The rendering logic itself
    is covered by :class:`TestRenderCondensedSummary` above.
    """

    def testRendererImportedInBaseModule(self):
        """``renderCondensedSummary`` is imported and wired into the injection site.

        Two cheap assertions:
        1. Import identity — ``base.renderCondensedSummary`` IS the renderer
           (not a stale copy / wrapper).
        2. Source inspection — ``getThreadByMessageForLLM`` actually CALLS the
           renderer with the ``condensedMessage`` dict argument. This catches a
           regression where the injection site reverts to
           ``content=condensedMessage["text"]`` (raw text), which the
           import-identity assertion alone would miss.
        """
        from internal.bot.common.handlers import base

        # 1. Import identity.
        assert hasattr(base, "renderCondensedSummary")
        assert base.renderCondensedSummary is renderCondensedSummary

        # 2. The injection site actually calls the renderer with the dict.
        src = inspect.getsource(BaseBotHandler.getThreadByMessageForLLM)
        assert "renderCondensedSummary(condensedMessage)" in src
