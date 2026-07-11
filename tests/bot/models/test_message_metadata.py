"""Tests for :func:`buildCondensingFields` in :mod:`message_metadata`.

Covers the pure helper that computes ``messageIds``/``participants``/
``dateRange``/``messageCount`` from a coverage slice — the parallel-list
entries that a :class:`CondenseBatchCoverage` index range maps to. The slice
can contain :class:`ChatMessageDict` rows (raw source messages), pre-existing
:class:`CondensingDict` summaries (re-condense cascade), or a mix of both.

The function lives in
:mod:`internal.bot.models.message_metadata` alongside :class:`CondensingDict`.
These tests exercise it in isolation (zero DB / LLM cost) with crafted
dict literals that match the TypedDict shapes.
"""

import datetime
import inspect
import json

from internal.bot.common.handlers.base import BaseBotHandler
from internal.bot.common.handlers.llm_messages import buildRandomContextDict
from internal.bot.models import ChatType, EnsuredMessage, MessageRecipient, MessageSender
from internal.bot.models.message_metadata import (
    CondensedSummaryKind,
    CondensingDict,
    buildCondensingFields,
    renderCondensedSummary,
)
from internal.database import Database
from internal.database.models import ChatMessageDict, MessageCategory
from internal.database.utils import DEFAULT_THREAD_ID
from internal.models import MessageId
from internal.services.llm import CondenseBatchCoverage

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
# Unit tests
# ---------------------------------------------------------------------------


class TestBuildCondensingFieldsRowsOnly:
    """Tests with only ChatMessageDict entries (no pre-existing summaries)."""

    def testSingleRow(self):
        """One row → messageIds/participants/dateRange/messageCount from it."""
        row = _makeRow(101, "alice", 1000.0)
        result = buildCondensingFields([row])

        assert result["messageIds"] == [MessageId(101)]
        assert result["participants"] == ["alice"]
        assert result["messageCount"] == 1
        assert result["dateRange"] == {"from": 1000.0, "to": 1000.0}

    def testMultipleRows(self):
        """Multiple rows → union of IDs, sorted participants, min/max dates."""
        rows = [
            _makeRow(101, "alice", 1000.0),
            _makeRow(102, "bob", 2000.0),
            _makeRow(103, "alice", 1500.0),
        ]
        result = buildCondensingFields(rows)

        assert result["messageIds"] == [MessageId(101), MessageId(102), MessageId(103)]
        assert result["participants"] == ["alice", "bob"]
        assert result["messageCount"] == 3
        assert result["dateRange"] == {"from": 1000.0, "to": 2000.0}

    def testEmptyUsernameSkipped(self):
        """Rows with empty username are excluded from participants."""
        rows = [
            _makeRow(101, "", 1000.0),
            _makeRow(102, "bob", 2000.0),
        ]
        result = buildCondensingFields(rows)

        assert result["participants"] == ["bob"]

    def testDuplicateMessageIdDeduped(self):
        """Duplicate message_id values are deduped (MessageId __eq__).

        The same row appearing twice (e.g. multi-emit: one original message
        emitting several ModelMessages) counts once in both ``messageIds``
        and ``messageCount``, per the ``messageCount`` docstring ("Number of
        original messages this summary covers").
        """
        rows = [
            _makeRow(101, "alice", 1000.0),
            _makeRow(101, "alice", 1000.0),
        ]
        result = buildCondensingFields(rows)

        assert result["messageIds"] == [MessageId(101)]
        assert result["messageCount"] == 1

    def testMultiEmitRowsCountUniqueIds(self):
        """Regression: multi-emit (same row repeated) must count unique message_ids.

        Callers (Path A ``base.py`` and Path B ``llm_messages.py``) build their
        parallel index lists with ``[row] * len(emittedMessages)`` to tag every
        emitted ModelMessage. A single original message that emits multiple
        ModelMessages (e.g. a ``randomContext`` message + per-tool messages)
        therefore appears N times in the entries. ``messageCount`` must reflect
        the number of UNIQUE original messages covered, per its docstring — not
        the raw entry count. This test locks in the fix for the overcount bug.
        """
        # Three entries, but only two distinct message_ids (100 appears twice).
        rows = [
            _makeRow(100, "alice", 1000.0),
            _makeRow(100, "alice", 1000.0),  # multi-emit duplicate of id 100
            _makeRow(101, "bob", 2000.0),
        ]
        result = buildCondensingFields(rows)

        # messageIds deduped via MessageId.__eq__.
        assert result["messageIds"] == [MessageId(100), MessageId(101)]
        # messageCount counts UNIQUE original messages, NOT entries (would be 3
        # under the old entry-counter logic).
        assert result["messageCount"] == 2


class TestBuildCondensingFieldsSummariesOnly:
    """Tests with only CondensingDict entries (re-condense cascade)."""

    def testNewSummaryFieldsUnioned(self):
        """Post-feature summary → its messageIds/participants/dateRange/count unioned."""
        summary = _makeNewSummary(
            text="old summary",
            messageIds=[MessageId(10), MessageId(11)],
            participants=["alice", "bob"],
            dateRange={"from": 500.0, "to": 900.0},
            messageCount=2,
        )
        result = buildCondensingFields([summary])

        assert result["messageIds"] == [MessageId(10), MessageId(11)]
        assert result["participants"] == ["alice", "bob"]
        assert result["messageCount"] == 2
        assert result["dateRange"] == {"from": 500.0, "to": 900.0}

    def testMultipleNewSummariesUnioned(self):
        """Multiple summaries → union all fields."""
        s1 = _makeNewSummary("s1", [MessageId(10)], ["alice"], {"from": 100.0, "to": 200.0}, 1)
        s2 = _makeNewSummary("s2", [MessageId(20), MessageId(21)], ["bob"], {"from": 300.0, "to": 400.0}, 2)
        result = buildCondensingFields([s1, s2])

        assert result["messageIds"] == [MessageId(10), MessageId(20), MessageId(21)]
        assert result["participants"] == ["alice", "bob"]
        assert result["messageCount"] == 3
        assert result["dateRange"] == {"from": 100.0, "to": 400.0}


class TestBuildCondensingFieldsMixed:
    """Tests with mixed ChatMessageDict + CondensingDict entries (cascade union)."""

    def testRowAndSummaryUnion(self):
        """A raw row + a pre-existing summary → all fields unioned."""
        summary = _makeNewSummary(
            "old summary",
            [MessageId(10), MessageId(11)],
            ["alice"],
            {"from": 500.0, "to": 900.0},
            2,
        )
        row = _makeRow(50, "bob", 1000.0)
        result = buildCondensingFields([summary, row])

        assert result["messageIds"] == [MessageId(10), MessageId(11), MessageId(50)]
        assert result["participants"] == ["alice", "bob"]
        assert result["messageCount"] == 3  # 2 (summary) + 1 (row)
        assert result["dateRange"] == {"from": 500.0, "to": 1000.0}

    def testOverlappingMessageIdsDeduped(self):
        """A summary's messageId overlapping with a raw row's id is deduped in messageIds.

        ``messageCount`` is the sum of the summary's stored count (2) plus the
        number of UNIQUE raw-row message_ids (1 — id 10). The overlap (id 10 is
        in both the summary and the raw row) is NOT subtracted: summary and raw
        contributions are independent. So messageCount == 3, while messageIds
        dedupes id 10 to a single entry.
        """
        summary = _makeNewSummary(
            "old summary",
            [MessageId(10), MessageId(11)],
            ["alice"],
            {"from": 500.0, "to": 900.0},
            2,
        )
        # Row 10 is already in the summary → deduped in messageIds list.
        row = _makeRow(10, "bob", 1000.0)
        result = buildCondensingFields([summary, row])

        assert MessageId(10) in result["messageIds"]
        # messageCount = summary's stored count (2) + unique raw-row ids (1) = 3.
        # The raw id 10 is counted once despite overlapping the summary.
        assert result["messageCount"] == 3


class TestBuildCondensingFieldsLegacy:
    """Tests for legacy CondensingDict entries (pre-feature, no new fields)."""

    def testLegacySummaryUsesTillMessageId(self):
        """Legacy summary (only text/tillMessageId/tillTS) → tillMessageId as single-element list."""
        legacy = _makeLegacySummary("legacy text", 42, 1234.0)
        result = buildCondensingFields([legacy])

        assert result["messageIds"] == [MessageId(42)]
        # No participants/dateRange/count info on legacy summaries
        assert result["participants"] == []
        assert result["messageCount"] == 0
        assert "dateRange" not in result

    def testLegacyAndRowMixed(self):
        """Legacy summary + raw row → tillMessageId unioned with row's message_id."""
        legacy = _makeLegacySummary("legacy", 42, 1234.0)
        row = _makeRow(50, "bob", 2000.0)
        result = buildCondensingFields([legacy, row])

        assert result["messageIds"] == [MessageId(42), MessageId(50)]
        assert result["participants"] == ["bob"]
        assert result["messageCount"] == 1  # only the row counts (legacy has no messageCount)
        assert result["dateRange"] == {"from": 2000.0, "to": 2000.0}


class TestBuildCondensingFieldsEdgeCases:
    """Edge cases: empty input, None entries."""

    def testEmpty(self):
        """Empty list → empty defaults, no dateRange."""
        result = buildCondensingFields([])

        assert result["messageIds"] == []
        assert result["participants"] == []
        assert result["messageCount"] == 0
        assert "dateRange" not in result

    def testNoneEntriesSkipped(self):
        """None entries (system-prompt positions) are silently skipped."""
        row = _makeRow(101, "alice", 1000.0)
        result = buildCondensingFields([None, row, None])

        assert result["messageIds"] == [MessageId(101)]
        assert result["participants"] == ["alice"]
        assert result["messageCount"] == 1

    def testOnlyNoneEntries(self):
        """All-None list → empty defaults."""
        result = buildCondensingFields([None, None])

        assert result["messageIds"] == []
        assert result["participants"] == []
        assert result["messageCount"] == 0
        assert "dateRange" not in result

    def testRowsWithSameTimestamps(self):
        """Multiple rows at the same timestamp → degenerate dateRange (from == to)."""
        rows = [
            _makeRow(101, "alice", 1000.0),
            _makeRow(102, "bob", 1000.0),
        ]
        result = buildCondensingFields(rows)

        assert result["dateRange"] == {"from": 1000.0, "to": 1000.0}


# ---------------------------------------------------------------------------
# _condensingDictFromCoverage tests
# ---------------------------------------------------------------------------


class TestCondensingDictFromCoverage:
    """Tests for BaseBotHandler._condensingDictFromCoverage static method.

    This method merges a CondenseBatchCoverage descriptor with the fields
    computed by buildCondensingFields into a full CondensingDict. It is the
    single construction site for new CondensingDict entries in
    getThreadByMessageForLLM.
    """

    def testFullFields(self):
        """Coverage + full fields -> CondensingDict with all fields populated."""
        cov: CondenseBatchCoverage = {
            "summaryText": "Summary of the conversation",
            "coveredFromIndex": 2,
            "coveredToIndex": 5,
        }
        fields = {
            "messageIds": [MessageId(10), MessageId(11), MessageId(12)],
            "participants": ["alice", "bob"],
            "dateRange": {"from": 1000.0, "to": 3000.0},
            "messageCount": 3,
        }
        result: dict = dict(BaseBotHandler._condensingDictFromCoverage(cov, fields))

        assert result["text"] == "Summary of the conversation"
        assert result["messageIds"] == [MessageId(10), MessageId(11), MessageId(12)]
        assert result["participants"] == ["alice", "bob"]
        assert result["messageCount"] == 3
        assert result["dateRange"] == {"from": 1000.0, "to": 3000.0}
        # tillMessageId/tillTS derived from last messageId / max timestamp
        assert result["tillMessageId"] == MessageId(12)
        assert result["tillTS"] == 3000.0

    def testNoDateRange(self):
        """Fields without dateRange -> tillTS falls back to 0.0."""
        cov: CondenseBatchCoverage = {
            "summaryText": "Summary",
            "coveredFromIndex": 1,
            "coveredToIndex": 2,
        }
        fields = {
            "messageIds": [MessageId(5)],
            "participants": ["alice"],
            "messageCount": 1,
        }
        result = BaseBotHandler._condensingDictFromCoverage(cov, fields)

        assert result["tillMessageId"] == MessageId(5)
        assert result["tillTS"] == 0.0
        assert "dateRange" not in result

    def testEmptyMessageIds(self):
        """Empty messageIds -> tillMessageId falls back to MessageId(0)."""
        cov: CondenseBatchCoverage = {
            "summaryText": "Summary",
            "coveredFromIndex": 0,
            "coveredToIndex": 1,
        }
        fields = {
            "messageIds": [],
            "participants": [],
            "messageCount": 0,
        }
        result = BaseBotHandler._condensingDictFromCoverage(cov, fields)

        assert result["tillMessageId"] == MessageId(0)
        assert result["tillTS"] == 0.0


# ---------------------------------------------------------------------------
# Coverage -> fields -> CondensingDict mapping simulation
# (simulates what getThreadByMessageForLLM does at each coverage entry)
# ---------------------------------------------------------------------------


class TestCoverageMappingSimulation:
    """Simulate the coverage->fields->dict mapping that getThreadByMessageForLLM does.

    Instead of instantiating the full handler (heavy: DB, cache, LLM service),
    these tests craft an ``indexToEntry`` parallel list, slice it with coverage
    index ranges, and verify the resulting CondensingDict fields. This directly
    exercises the alignment between coverage indices and source entries.
    """

    def testSingleBatchFieldsPresent(self):
        """Single coverage batch -> fields scoped to the covered messages."""
        # Simulate: indexToEntry = [None(sys), row0(head), row1, row2, row3, row4(tail)]
        indexToEntry = [
            None,
            _makeRow(100, "root_user", 500.0),
            _makeRow(101, "alice", 1000.0),
            _makeRow(102, "bob", 2000.0),
            _makeRow(103, "alice", 3000.0),
            _makeRow(104, "carol", 4000.0),
        ]

        # Coverage: batch covers indices 2:4 (row101, row102)
        cov: CondenseBatchCoverage = {
            "summaryText": "Alice and Bob discussed something",
            "coveredFromIndex": 2,
            "coveredToIndex": 4,
        }

        coveredSlice = [e for e in indexToEntry[cov["coveredFromIndex"] : cov["coveredToIndex"]] if e is not None]
        fields = buildCondensingFields(coveredSlice)
        entry: dict = dict(BaseBotHandler._condensingDictFromCoverage(cov, fields))

        assert entry["text"] == "Alice and Bob discussed something"
        assert entry["messageIds"] == [MessageId(101), MessageId(102)]
        assert entry["participants"] == ["alice", "bob"]
        assert entry["messageCount"] == 2
        assert entry["dateRange"] == {"from": 1000.0, "to": 2000.0}
        assert entry["tillMessageId"] == MessageId(102)
        assert entry["tillTS"] == 2000.0

    def testMultiBatchFieldsScopedPerSlice(self):
        """Two coverage batches -> each CondensingDict scoped to ITS slice."""
        # indexToEntry = [None(sys), row0(head), row1, row2, row3, row4, row5(tail)]
        indexToEntry = [
            None,
            _makeRow(100, "root_user", 500.0),
            _makeRow(101, "alice", 1000.0),
            _makeRow(102, "bob", 2000.0),
            _makeRow(103, "alice", 3000.0),
            _makeRow(104, "carol", 4000.0),
            _makeRow(105, "dave", 5000.0),
        ]

        coverage = [
            CondenseBatchCoverage(
                summaryText="Batch 1: Alice and Bob",
                coveredFromIndex=2,
                coveredToIndex=4,
            ),
            CondenseBatchCoverage(
                summaryText="Batch 2: Alice and Carol",
                coveredFromIndex=4,
                coveredToIndex=6,
            ),
        ]

        condenseCache = []
        for cov in coverage:
            coveredSlice = [e for e in indexToEntry[cov["coveredFromIndex"] : cov["coveredToIndex"]] if e is not None]
            fields = buildCondensingFields(coveredSlice)
            condenseCache.append(BaseBotHandler._condensingDictFromCoverage(cov, fields))

        # Batch 1: covers row101, row102
        assert condenseCache[0]["messageIds"] == [MessageId(101), MessageId(102)]
        assert condenseCache[0]["participants"] == ["alice", "bob"]
        assert condenseCache[0]["text"] == "Batch 1: Alice and Bob"

        # Batch 2: covers row103, row104
        assert condenseCache[1]["messageIds"] == [MessageId(103), MessageId(104)]
        assert condenseCache[1]["participants"] == ["alice", "carol"]
        assert condenseCache[1]["text"] == "Batch 2: Alice and Carol"

    def testRecondenseCascadeUnion(self):
        """Coverage slice spanning old summary + raw rows -> fields unioned.

        Simulates the re-condense cascade (plan section 11 #3): a re-condense
        batch that merges a pre-existing summary (carrying its own messageIds/
        participants) with adjacent raw messages.
        """
        # indexToEntry2 for re-condense: [oldSummary, None(sys), row1, row2, rowTail]
        oldSummary = _makeNewSummary(
            "Previous summary",
            [MessageId(10), MessageId(11)],
            ["alice", "bob"],
            {"from": 500.0, "to": 900.0},
            2,
        )
        indexToEntry2 = [
            oldSummary,
            None,  # system prompt from condensedRet
            _makeRow(50, "carol", 1000.0),
            _makeRow(51, "alice", 1100.0),
            _makeRow(99, "dave", 5000.0),  # tail (protected)
        ]

        # Coverage: batch spans indices 0:4 (oldSummary + None + row50 + row51)
        cov: CondenseBatchCoverage = {
            "summaryText": "Merged summary of old + new",
            "coveredFromIndex": 0,
            "coveredToIndex": 4,
        }

        coveredSlice = [e for e in indexToEntry2[cov["coveredFromIndex"] : cov["coveredToIndex"]] if e is not None]
        fields = buildCondensingFields(coveredSlice)
        entry: dict = dict(BaseBotHandler._condensingDictFromCoverage(cov, fields))

        # Union of old summary's messageIds (10, 11) + raw rows' ids (50, 51)
        assert entry["messageIds"] == [MessageId(10), MessageId(11), MessageId(50), MessageId(51)]
        # Union of participants
        assert entry["participants"] == ["alice", "bob", "carol"]
        # Count = old summary's count (2) + raw rows (2)
        assert entry["messageCount"] == 4
        # Date range spans old summary's range + raw rows
        assert entry["dateRange"] == {"from": 500.0, "to": 1100.0}

    def testBackwardsCompatTillMessageIdAndTillTS(self):
        """Every new CondensingDict has tillMessageId/tillTS (backwards-compat)."""
        indexToEntry = [
            None,
            _makeRow(100, "root", 500.0),
            _makeRow(101, "alice", 1000.0),
            _makeRow(102, "bob", 2000.0),
            _makeRow(103, "carol", 3000.0),
        ]

        cov: CondenseBatchCoverage = {
            "summaryText": "Summary",
            "coveredFromIndex": 2,
            "coveredToIndex": 4,
        }

        coveredSlice = [e for e in indexToEntry[cov["coveredFromIndex"] : cov["coveredToIndex"]] if e is not None]
        fields = buildCondensingFields(coveredSlice)
        entry = BaseBotHandler._condensingDictFromCoverage(cov, fields)

        # tillMessageId/tillTS present and derived from last covered message
        assert "tillMessageId" in entry
        assert "tillTS" in entry
        assert entry["tillMessageId"] == MessageId(102)
        assert entry["tillTS"] == 2000.0

    def testAlignmentWithMultiEmitRows(self):
        """Alignment holds when toModelMessageList emits multiple messages per row.

        Simulate: each source row emits 2 ModelMessages (e.g. randomContext + main).
        The indexToEntry list tags each emitted message with the source row.
        A coverage slice correctly maps to the underlying rows — messageIds
        are deduped via MessageId.__eq__ even when a row appears multiple times.
        """
        row1 = _makeRow(101, "alice", 1000.0)
        row2 = _makeRow(102, "bob", 2000.0)

        # Simulate ret = [sys, row1_msg1, row1_msg2, row2_msg1, row2_msg2, tail]
        # indexToEntry tags each emitted message with its source row
        indexToEntry = [
            None,  # system prompt
            row1,  # row1's first emitted message
            row1,  # row1's second emitted message
            row2,  # row2's first emitted message
            row2,  # row2's second emitted message
            _makeRow(103, "tail", 3000.0),  # tail (protected)
        ]

        # len(indexToEntry) == len(ret) is the invariant
        assert len(indexToEntry) == 6  # 6 ModelMessages in ret

        # Coverage: batch covers indices 1:5 (all of row1 + row2)
        cov: CondenseBatchCoverage = {
            "summaryText": "Summary of Alice and Bob",
            "coveredFromIndex": 1,
            "coveredToIndex": 5,
        }

        coveredSlice = [e for e in indexToEntry[cov["coveredFromIndex"] : cov["coveredToIndex"]] if e is not None]
        fields = buildCondensingFields(coveredSlice)

        # Even though row1 and row2 each appear twice in the slice, their
        # messageIds are deduped (MessageId.__eq__)
        assert fields["messageIds"] == [MessageId(101), MessageId(102)]
        # And messageCount reflects the 2 unique original messages, not the 4
        # entries (regression for the multi-emit overcount bug).
        assert fields["messageCount"] == 2


# ---------------------------------------------------------------------------
# indexToEntry2 alignment — batch failure regression tests
#
# These tests simulate the re-condense path's indexToEntry2 construction
# (base.py ~lines 960-980) with the retHeadLen formula:
#
#   retHeadLen = len(condensedRet) - len(coverage) - keepLastN
#
# The OLD code used coverage[0]["coveredFromIndex"] / coverage[-1]["coveredToIndex"]
# which broke when batches failed (no coverage emitted for them → gap in the
# index ranges). The new formula derives head/tail from condensedRet's actual
# structure so failed batches don't cause misalignment.
# ---------------------------------------------------------------------------


class TestIndexToEntry2Alignment:
    """Regression tests for the indexToEntry2 alignment formula.

    Simulates the re-condense path's parallel-list construction with various
    batch-failure scenarios and verifies ``len(indexToEntry2) == len(condenseCacheMessages)``.
    """

    @staticmethod
    def _buildIndexToEntry2(
        indexToEntry: list,
        intermediateEntries: list,
        condensedRetLen: int,
        coverage: list,
        originalCondenseCache: list,
        keepLastN: int,
    ) -> list:
        """Replicate the fixed indexToEntry2 construction from base.py.

        Args:
            indexToEntry: Parallel list aligned to the first-pass ret.
            intermediateEntries: CondensingDict entries from first-pass coverage.
            condensedRetLen: Length of the first-pass condensedRet.
            coverage: First-pass coverage list (only successful batches).
            originalCondenseCache: Pre-existing summary entries.
            keepLastN: Number of protected tail messages.

        Returns:
            The indexToEntry2 parallel list (should be 1:1 with condenseCacheMessages).
        """
        indexToEntry2: list = []
        for cm in originalCondenseCache:
            indexToEntry2.append(cm)
        retHeadLen = condensedRetLen - len(coverage) - keepLastN
        indexToEntry2.extend(indexToEntry[:retHeadLen])
        indexToEntry2.extend(intermediateEntries)
        indexToEntry2.extend(indexToEntry[len(indexToEntry) - keepLastN :])
        return indexToEntry2

    def testBatchFailureInMiddle(self):
        """Alignment holds when a middle batch fails (no coverage for it).

        Scenario: 3 batches, batch 2 fails. Messages in the failed batch are
        dropped from condensedRet and no coverage entry is emitted. The
        retHeadLen formula correctly maps head/tail/intermediates regardless.
        """
        keepFirstN = 1
        keepLastN = 1

        indexToEntry = [
            None,  # 0: system prompt
            _makeRow(0, "root", 0.0),  # 1: head (protected)
            _makeRow(1, "alice", 100.0),  # 2: batch 1
            _makeRow(2, "bob", 200.0),  # 3: batch 1
            _makeRow(3, "carol", 300.0),  # 4: batch 2 FAILS (dropped)
            _makeRow(4, "dave", 400.0),  # 5: batch 2 FAILS (dropped)
            _makeRow(5, "alice", 500.0),  # 6: batch 3
            _makeRow(6, "bob", 600.0),  # 7: batch 3
            _makeRow(7, "tail", 700.0),  # 8: tail (protected)
        ]

        coverage = [
            CondenseBatchCoverage(summaryText="Summary 1", coveredFromIndex=1, coveredToIndex=4),
            # Batch 2 (indices 4-6) FAILED — silently dropped, no coverage entry
            CondenseBatchCoverage(summaryText="Summary 3", coveredFromIndex=6, coveredToIndex=8),
        ]

        # condensedRet = [head(1)] + [summary_1, summary_3(2)] + [tail(1)] = 4
        condensedRetLen = keepFirstN + len(coverage) + keepLastN

        intermediateEntries = []
        for cov in coverage:
            coveredSlice = [e for e in indexToEntry[cov["coveredFromIndex"] : cov["coveredToIndex"]] if e is not None]
            fields = buildCondensingFields(coveredSlice)
            intermediateEntries.append(BaseBotHandler._condensingDictFromCoverage(cov, fields))

        originalCondenseCache: list = []
        indexToEntry2 = self._buildIndexToEntry2(
            indexToEntry, intermediateEntries, condensedRetLen, coverage, originalCondenseCache, keepLastN
        )

        condenseCacheMessagesLen = len(originalCondenseCache) + condensedRetLen

        # INVARIANT: alignment holds despite the gap from the failed batch
        assert len(indexToEntry2) == condenseCacheMessagesLen

        # Verify content: head(system prompt) + intermediate(2) + tail(row7).
        # retHeadLen = 4 - 2 - 1 = 1, so head = indexToEntry[:1] = [None] (system prompt).
        assert len(indexToEntry2) == 4
        assert indexToEntry2[0] is None  # head = system prompt
        assert indexToEntry2[1] == intermediateEntries[0]  # summary 1
        assert indexToEntry2[2] == intermediateEntries[1]  # summary 3
        assert indexToEntry2[3] == indexToEntry[8]  # tail = row7

    def testOldFormulaWouldBreak(self):
        """The old coverage-index formula produces WRONG alignment with failures.

        This documents WHY the fix was needed: using coverage[0]["coveredFromIndex"]
        and coverage[-1]["coveredToIndex"] for head/tail gives wrong slice boundaries
        when batches fail in the middle.
        """
        keepFirstN = 1
        keepLastN = 1

        indexToEntry = [
            None,  # 0
            _makeRow(0, "root", 0.0),  # 1: head
            _makeRow(1, "alice", 100.0),  # 2: batch 1
            _makeRow(2, "bob", 200.0),  # 3: batch 1
            _makeRow(3, "carol", 300.0),  # 4: batch 2 FAILS
            _makeRow(4, "dave", 400.0),  # 5: batch 2 FAILS
            _makeRow(5, "eve", 500.0),  # 6: batch 3
            _makeRow(6, "frank", 600.0),  # 7: batch 3
            _makeRow(7, "tail", 700.0),  # 8: tail
        ]

        coverage = [
            CondenseBatchCoverage(summaryText="S1", coveredFromIndex=1, coveredToIndex=4),
            CondenseBatchCoverage(summaryText="S3", coveredFromIndex=6, coveredToIndex=8),
        ]

        condensedRetLen = keepFirstN + len(coverage) + keepLastN  # 4

        # OLD (buggy) formula:
        oldHeadLen = coverage[0]["coveredFromIndex"]  # 1
        oldTailStart = coverage[-1]["coveredToIndex"]  # 8
        oldIntermediateCount = len(coverage)  # 2
        oldTotal = oldHeadLen + oldIntermediateCount + (len(indexToEntry) - oldTailStart)  # 1 + 2 + 1 = 4

        # NEW (fixed) formula:
        newRetHeadLen = condensedRetLen - len(coverage) - keepLastN  # 1
        newTotal = newRetHeadLen + len(coverage) + keepLastN  # 1 + 2 + 1 = 4

        # In THIS case both agree (the last successful batch ends right at the tail boundary).
        assert oldTotal == newTotal == condensedRetLen

        # The real divergence happens when the LAST batch fails (tail boundary shifts):
        coverage2 = [
            CondenseBatchCoverage(summaryText="S1", coveredFromIndex=1, coveredToIndex=4),
            # Batch 2 (indices 4-6) succeeds
            CondenseBatchCoverage(summaryText="S2", coveredFromIndex=4, coveredToIndex=7),
            # Batch 3 (indices 7-8) FAILS — overlaps with tail region
        ]
        condensedRetLen2 = keepFirstN + len(coverage2) + keepLastN  # 1 + 2 + 1 = 4

        # OLD formula with coverage2:
        oldHeadLen2 = coverage2[0]["coveredFromIndex"]  # 1
        oldTailStart2 = coverage2[-1]["coveredToIndex"]  # 7
        # old tail = indexToEntry[7:] = [row6, tail] = 2 entries
        # but condensedRet only has 1 tail entry!
        oldTailLen2 = len(indexToEntry) - oldTailStart2  # 9 - 7 = 2
        oldTotal2 = oldHeadLen2 + len(coverage2) + oldTailLen2  # 1 + 2 + 2 = 5
        # WRONG! condenseCacheMessages = 0 + condensedRetLen2 = 4, but old formula produces 5

        # NEW formula:
        newRetHeadLen2 = condensedRetLen2 - len(coverage2) - keepLastN  # 1
        newTotal2 = newRetHeadLen2 + len(coverage2) + keepLastN  # 1 + 2 + 1 = 4
        assert newTotal2 == condensedRetLen2  # CORRECT
        assert oldTotal2 != condensedRetLen2  # OLD IS WRONG (5 != 4)

    def testAllBatchesFail(self):
        """Coverage empty (all batches failed / truncation mode) → formula degrades gracefully.

        With empty coverage, retHeadLen = len(condensedRet) - keepLastN,
        and intermediateEntries is empty. Result = all of indexToEntry, matching
        the old fallback behaviour.
        """
        keepLastN = 1

        indexToEntry = [
            None,
            _makeRow(0, "root", 0.0),
            _makeRow(1, "alice", 100.0),
            _makeRow(2, "bob", 200.0),
            _makeRow(3, "tail", 300.0),
        ]

        coverage: list = []
        intermediateEntries: list = []
        # Truncation mode: condensedRet = head + tail (no summaries)
        condensedRetLen = len(indexToEntry)  # unchanged

        originalCondenseCache: list = []
        indexToEntry2 = self._buildIndexToEntry2(
            indexToEntry, intermediateEntries, condensedRetLen, coverage, originalCondenseCache, keepLastN
        )

        condenseCacheMessagesLen = len(originalCondenseCache) + condensedRetLen
        assert len(indexToEntry2) == condenseCacheMessagesLen
        assert len(indexToEntry2) == len(indexToEntry)  # all entries mapped

    def testWithPreExistingSummaries(self):
        """Alignment holds when originalCondenseCache has pre-existing summaries.

        indexToEntry2 = [old summaries] + [head + intermediates + tail].
        condenseCacheMessages = [old summaries] + [condensedRet].
        Both sides must match.
        """
        keepFirstN = 1
        keepLastN = 1

        oldSummary1 = _makeNewSummary("Old summary", [MessageId(10)], ["alice"], {"from": 50.0, "to": 50.0}, 1)
        oldSummary2 = _makeNewSummary("Old summary 2", [MessageId(20)], ["bob"], {"from": 60.0, "to": 60.0}, 1)

        originalCondenseCache = [oldSummary1, oldSummary2]

        indexToEntry = [
            None,  # 0: system prompt
            _makeRow(0, "root", 0.0),  # 1: head
            _makeRow(1, "alice", 100.0),  # 2: batch 1
            _makeRow(2, "bob", 200.0),  # 3: batch 1
            _makeRow(3, "tail", 300.0),  # 4: tail
        ]

        coverage = [
            CondenseBatchCoverage(summaryText="Summary 1", coveredFromIndex=1, coveredToIndex=4),
        ]
        condensedRetLen = keepFirstN + len(coverage) + keepLastN  # 3

        intermediateEntries = []
        for cov in coverage:
            coveredSlice = [e for e in indexToEntry[cov["coveredFromIndex"] : cov["coveredToIndex"]] if e is not None]
            fields = buildCondensingFields(coveredSlice)
            intermediateEntries.append(BaseBotHandler._condensingDictFromCoverage(cov, fields))

        indexToEntry2 = self._buildIndexToEntry2(
            indexToEntry, intermediateEntries, condensedRetLen, coverage, originalCondenseCache, keepLastN
        )

        condenseCacheMessagesLen = len(originalCondenseCache) + condensedRetLen  # 2 + 3 = 5
        assert len(indexToEntry2) == condenseCacheMessagesLen  # 5

        # Verify structure: [old1, old2, head(sys=None), intermediate, tail].
        # retHeadLen = 3 - 1 - 1 = 1, so head = indexToEntry[:1] = [None].
        assert indexToEntry2[0] == oldSummary1
        assert indexToEntry2[1] == oldSummary2
        assert indexToEntry2[2] is None  # head = system prompt
        assert indexToEntry2[3] == intermediateEntries[0]
        assert indexToEntry2[4] == indexToEntry[4]  # tail


# ---------------------------------------------------------------------------
# Phase 3b: buildRandomContextDict — Path B single-CondensingDict builder
# (unions ALL coverage batches into one dict, unlike Path A's per-batch helper)
# ---------------------------------------------------------------------------


class TestBuildRandomContextDict:
    """Tests for :func:`buildRandomContextDict` — Path B's CondensingDict builder.

    Path B (``randomContext``) stores ONE summary (not a list). When
    :meth:`condenseContext` emits multiple coverage batches, this helper
    unions ALL batches into a single :class:`CondensingDict`. It mirrors Path
    A's ``_condensingDictFromCoverage`` assembly (same
    ``tillMessageId``/``tillTS`` derivation) but slices+concatenates the
    parallel ``sourceRows`` list by every batch's index range before feeding
    the union through :func:`buildCondensingFields`.

    Pure-function tests — zero DB/LLM cost. The ``summaryText`` argument is
    the caller's joined summary (``"\\n".join(m.content ...)``); the helper
    does NOT re-derive it from the coverage.
    """

    def testSingleBatchAllFieldsPopulated(self):
        """One batch covering several rows -> all coverage fields present."""
        sourceRows = [
            _makeRow(101, "alice", 1000.0),
            _makeRow(102, "bob", 2000.0),
            _makeRow(103, "alice", 3000.0),
        ]
        coverage = [
            CondenseBatchCoverage(
                summaryText="irrelevant — helper takes summaryText separately",
                coveredFromIndex=0,
                coveredToIndex=3,
            )
        ]
        result: dict = dict(
            buildRandomContextDict(summaryText="SUMMARY TEXT", coverage=coverage, sourceRows=sourceRows)
        )

        assert result["text"] == "SUMMARY TEXT"
        assert result["messageIds"] == [MessageId(101), MessageId(102), MessageId(103)]
        assert result["participants"] == ["alice", "bob"]
        assert result["messageCount"] == 3
        assert result["dateRange"] == {"from": 1000.0, "to": 3000.0}
        # tillMessageId/tillTS derived from last messageId / max timestamp
        # (same convention as Path A's _condensingDictFromCoverage).
        assert result["tillMessageId"] == MessageId(103)
        assert result["tillTS"] == 3000.0

    def testMultiBatchCoverageUnion(self):
        """Two non-overlapping batches -> union of all covered rows."""
        sourceRows = [
            _makeRow(101, "alice", 1000.0),
            _makeRow(102, "bob", 2000.0),
            _makeRow(103, "carol", 3000.0),
            _makeRow(104, "dave", 4000.0),
        ]
        coverage = [
            CondenseBatchCoverage(summaryText="batch1", coveredFromIndex=0, coveredToIndex=2),
            CondenseBatchCoverage(summaryText="batch2", coveredFromIndex=2, coveredToIndex=4),
        ]
        result: dict = dict(buildRandomContextDict(summaryText="JOINED", coverage=coverage, sourceRows=sourceRows))

        # messageIds from BOTH batches (in source-order, deduped).
        assert result["messageIds"] == [MessageId(101), MessageId(102), MessageId(103), MessageId(104)]
        assert result["participants"] == ["alice", "bob", "carol", "dave"]
        assert result["messageCount"] == 4
        assert result["dateRange"] == {"from": 1000.0, "to": 4000.0}

    def testMultiBatchPartialCoverage(self):
        """Batches covering only a subset -> only covered rows contribute."""
        sourceRows = [
            _makeRow(101, "alice", 1000.0),
            _makeRow(102, "bob", 2000.0),
            _makeRow(103, "carol", 3000.0),
            _makeRow(104, "dave", 4000.0),
            _makeRow(105, "eve", 5000.0),
        ]
        # Two batches covering indices 1:3 and 3:4 — row 0 and row 4 are NOT covered.
        coverage = [
            CondenseBatchCoverage(summaryText="b1", coveredFromIndex=1, coveredToIndex=3),
            CondenseBatchCoverage(summaryText="b2", coveredFromIndex=3, coveredToIndex=4),
        ]
        result: dict = dict(buildRandomContextDict(summaryText="S", coverage=coverage, sourceRows=sourceRows))

        assert result["messageIds"] == [MessageId(102), MessageId(103), MessageId(104)]
        assert result["participants"] == ["bob", "carol", "dave"]
        assert result["messageCount"] == 3
        assert result["dateRange"] == {"from": 2000.0, "to": 4000.0}

    def testTextIsCallerProvidedNotRecomputed(self):
        """summaryText is injected verbatim (the caller's joined text)."""
        sourceRows = [_makeRow(1, "alice", 100.0)]
        coverage = [CondenseBatchCoverage(summaryText="DIFFERENT", coveredFromIndex=0, coveredToIndex=1)]
        result: dict = dict(buildRandomContextDict(summaryText="CALLER TEXT", coverage=coverage, sourceRows=sourceRows))

        assert result["text"] == "CALLER TEXT"

    def testEmptySourceRowsDefensive(self):
        """Empty sourceRows + a coverage slice -> defensive MessageId(0)/0.0.

        This is defensive dead code (a coverage slice always has at least one
        source row in production), but the helper must not crash.
        """
        coverage = [CondenseBatchCoverage(summaryText="x", coveredFromIndex=0, coveredToIndex=0)]
        result: dict = dict(buildRandomContextDict(summaryText="S", coverage=coverage, sourceRows=[]))

        assert result["text"] == "S"
        assert result["messageIds"] == []
        assert result["participants"] == []
        assert result["messageCount"] == 0
        assert result["tillMessageId"] == MessageId(0)
        assert result["tillTS"] == 0.0
        assert "dateRange" not in result


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

    def testLegacyStrInput(self):
        """Legacy str input → {"type":"condensed","summary":"<str>"} only."""
        result = renderCondensedSummary("Old summary text from legacy row")
        parsed = json.loads(result)

        assert parsed["type"] == "condensed"
        assert parsed["summary"] == "Old summary text from legacy row"
        # All metadata fields omitted
        assert "coveredMessageIds" not in parsed
        assert "participants" not in parsed
        assert "dateRange" not in parsed
        assert "messageCount" not in parsed

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
