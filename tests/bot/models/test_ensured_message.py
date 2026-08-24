"""Regression tests for :class:`EnsuredMessage` ``formatForLLM`` JSON output.

The legacy per-message ``userSummary`` injection path (the rolling-bio
``EnsuredMessage.applyUserMetadata`` → ``self.userSummary`` → ``formatForLLM``
JSON key) was removed in user-memories Phase 4b in favour of the structured
``<user-memories>`` system-prompt block. These tests guard against its
accidental reintroduction.

``formatForLLM`` is async and accepts a ``db`` argument, but with no media
attached (``mediaId is None`` and empty ``mediaList``) its
``updateMediaContent`` early-returns without ever touching ``db``. The real
``testDatabase`` fixture is passed for full type-correctness; it is never read.

Phase 5 additions: the lazy memory-resolution content tests
(:class:`TestFormatForLLMMemoryResolution`) verify that compact IDs in
``metadata["memories"]`` are resolved to rendered content via
``cache.getMemoriesByIds`` — covering both cohorts, ``excludeMemoryIds``
filtering, and the stale-ID omission contract.
"""

import datetime
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from internal.bot.models import (
    ChatType,
    EnsuredMessage,
    LLMMessageFormat,
    MessageRecipient,
    MessageSender,
    SingleMemoryDict,
)
from internal.database import Database
from internal.database.models import MemoryType
from internal.models import MessageId
from lib.ai import ModelMessage
from lib.db.utils import DEFAULT_THREAD_ID


def _makeEnsuredMessage() -> EnsuredMessage:
    """Build a minimal real :class:`EnsuredMessage` with no media attached.

    The sender fields are populated so the emitted JSON is non-empty and stable;
    ``metadata`` is left empty (no compact memory IDs).

    Returns:
        A freshly constructed :class:`EnsuredMessage`.
    """
    ensuredMessage = EnsuredMessage(
        sender=MessageSender(id=7, name="Alice", username="@alice"),
        recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
        messageId=42,
        date=datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
        messageText="hello",
    )
    ensuredMessage.threadId = DEFAULT_THREAD_ID
    return ensuredMessage


class TestFormatForLLMExcludesUserSummary:
    """Regression guard: ``userSummary`` must never appear in ``formatForLLM`` output.

    The field, its slot, and the ``applyUserMetadata`` extraction method were all
    removed in user-memories Phase 4b. A passing instance no longer has a
    ``userSummary`` attribute at all, and the JSON branch must not emit it. These
    tests assert both so the dead plumbing cannot silently reappear.
    """

    def test_userSummaryAttributeRemoved(self) -> None:
        """The ``userSummary`` attribute is gone from :class:`EnsuredMessage`.

        ``EnsuredMessage`` uses ``__slots__``; setting an unknown attribute raises
        ``AttributeError``, which confirms the slot was removed rather than merely
        defaulted to ``None``.
        """
        ensuredMessage = _makeEnsuredMessage()
        with pytest.raises(AttributeError):
            ensuredMessage.userSummary = "should fail"  # type: ignore[attr-defined]

    async def test_formatForLLMJsonOmitsUserSummary(self, testDatabase: Database) -> None:
        """The JSON branch of ``formatForLLM`` never emits a ``userSummary`` key.

        Guards both the parsed-dict and the raw-string representations so the
        field cannot reappear either as a serialised value or as a stray token.

        Args:
            testDatabase: Real in-memory database; never read because the
                message has no media.
        """
        ensuredMessage = _makeEnsuredMessage()

        output = await ensuredMessage.formatForLLM(
            testDatabase, format=LLMMessageFormat.JSON, cache=None, excludeMemoryIds=set()
        )

        parsed = json.loads(output)
        assert "userSummary" not in parsed
        # Byte-identity: the field name must not appear anywhere in the string.
        assert "userSummary" not in output

    async def test_formatForLLMJsonOmitsUserSummaryWhenUserMemoriesSet(self, testDatabase: Database) -> None:
        """Even when memories are populated, no ``userSummary`` key sneaks in.

        Confirms the removal did not leave the key reachable via the truthiness
        filter when a sibling optional field is populated.

        Args:
            testDatabase: Real in-memory database; never read because the
                message has no media.
        """
        ensuredMessage = _makeEnsuredMessage()
        # Phase 4: memories are stored as compact IDs in metadata["memories"]
        # and resolved lazily by formatForLLM via cache.getMemoriesByIds.
        entry: SingleMemoryDict = {"type": MemoryType.PREFERENCE, "content": "vegan", "tags": ["diet"]}
        ensuredMessage.metadata["memories"] = {"permanentIds": ["m1"], "shortTermIds": []}  # type: ignore[assignment]
        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(return_value={"m1": entry})

        output = await ensuredMessage.formatForLLM(
            testDatabase, format=LLMMessageFormat.JSON, cache=cache, excludeMemoryIds=set()  # type: ignore[arg-type]
        )

        parsed = json.loads(output)
        assert "userSummary" not in parsed
        assert "userSummary" not in output
        # Sanity: userMemories is still emitted (proves the assertion is meaningful).
        assert "userMemories" in parsed


class TestGetMemoryIds:
    """Tests for :meth:`EnsuredMessage.getMemoryIds` — the compact ID reader.

    ``getMemoryIds`` reads ``metadata["memories"]`` and returns the union of
    ``permanentIds`` and ``shortTermIds``. Its contract is to never raise on
    an unexpected shape (None, missing, non-canonical). These tests guard the
    defensive coalescing that backs that contract.
    """

    async def test_getMemoryIds_noneValuedCompactKeys(self) -> None:
        """A None-valued compact key must not raise; the other cohort's IDs are returned.

        Regression guard: ``{"permanentIds": None, "shortTermIds": ["id1"]}``
        previously raised ``TypeError`` at ``set(None)``; the ``or []``
        coalescing must make this return ``{"id1"}``.
        """
        msg = _makeEnsuredMessage()
        msg.metadata["memories"] = {"permanentIds": None, "shortTermIds": ["id1"]}  # type: ignore[assignment]

        assert msg.getMemoryIds() == {"id1"}


# ---------------------------------------------------------------------------
# formatForLLM lazy memory resolution — content, filtering, stale-ID omission
# ---------------------------------------------------------------------------


class TestFormatForLLMMemoryResolution:
    """Tests for the lazy memory resolution inside :meth:`formatForLLM`.

    Phase 3+ stores compact memory IDs in ``metadata["memories"]``
    (``{"permanentIds": [...], "shortTermIds": [...]}``); ``formatForLLM``
    resolves them to content on-demand via ``cache.getMemoriesByIds`` at render
    time. These tests assert the resolved CONTENT appears in the correct
    cohorts, that ``excludeMemoryIds`` filters individual IDs, and that stale
    IDs (resolving to ``None``) cause the ``userMemories`` key to be OMITTED
    entirely rather than emitted as an empty dict.
    """

    async def test_resolvesBothCohorts_contentInRightSlots(self, testDatabase: Database) -> None:
        """Permanent + shortTerm IDs resolve to content in their respective cohorts.

        Args:
            testDatabase: Real in-memory database; never read (no media).
        """
        msg = _makeEnsuredMessage()
        msg.metadata["memories"] = {"permanentIds": ["p1"], "shortTermIds": ["s1"]}  # type: ignore[assignment]

        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(
            return_value={
                "p1": {"type": MemoryType.FACT, "content": "vegan", "tags": ["diet"]},
                "s1": {"type": MemoryType.EVENT, "content": "just woke up", "tags": []},
            }
        )

        output = await msg.formatForLLM(
            testDatabase, format=LLMMessageFormat.JSON, cache=cache, excludeMemoryIds=set()  # type: ignore[arg-type]
        )

        parsed = json.loads(output)
        assert "userMemories" in parsed
        assert parsed["userMemories"]["permanent"][0]["content"] == "vegan"
        assert parsed["userMemories"]["shortTerm"][0]["content"] == "just woke up"

    async def test_excludeMemoryIds_dropsPermanentEntryKeepsShortTerm(self, testDatabase: Database) -> None:
        """``excludeMemoryIds`` drops the targeted ID while the other cohort survives.

        Args:
            testDatabase: Real in-memory database; never read (no media).
        """
        msg = _makeEnsuredMessage()
        msg.metadata["memories"] = {"permanentIds": ["p1"], "shortTermIds": ["s1"]}  # type: ignore[assignment]

        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(
            return_value={
                "p1": {"type": MemoryType.FACT, "content": "vegan", "tags": ["diet"]},
                "s1": {"type": MemoryType.EVENT, "content": "just woke up", "tags": []},
            }
        )

        output = await msg.formatForLLM(
            testDatabase, format=LLMMessageFormat.JSON, cache=cache, excludeMemoryIds={"p1"}  # type: ignore[arg-type]
        )

        parsed = json.loads(output)
        assert "userMemories" in parsed
        assert "permanent" not in parsed["userMemories"]
        assert parsed["userMemories"]["shortTerm"][0]["content"] == "just woke up"

    async def test_excludeMemoryIds_dropsScoredShortTermEntryAndKeepsUnscored(self, testDatabase: Database) -> None:
        """``excludeMemoryIds`` filters BEFORE score merge — excluded short-term ID's score never leaks.

        Regression guard: if the filtering order were reversed (merge scores, then filter),
        an excluded short-term ID's score could leak onto another entry. This test verifies
        the correct order: IDs are filtered first, scores are merged only for survivors.

        Args:
            testDatabase: Real in-memory database; never read (no media).
        """
        msg = _makeEnsuredMessage()
        msg.metadata["memories"] = {  # type: ignore[assignment]
            "permanentIds": [],
            "shortTermIds": ["m1", "m2"],
            "shortTermScores": {"m1": 0.9, "m2": 0.5},
        }

        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(
            return_value={
                "m1": {"type": MemoryType.EVENT, "content": "just woke up", "tags": []},
                "m2": {"type": MemoryType.PREFERENCE, "content": "likes coffee", "tags": []},
            }
        )

        output = await msg.formatForLLM(
            testDatabase, format=LLMMessageFormat.JSON, cache=cache, excludeMemoryIds={"m1"}  # type: ignore[arg-type]
        )

        parsed = json.loads(output)
        assert "userMemories" in parsed
        shortTerm = parsed["userMemories"]["shortTerm"]

        # Only m2 should be present (m1 was excluded).
        assert len(shortTerm) == 1
        assert shortTerm[0]["content"] == "likes coffee"
        assert shortTerm[0]["score"] == 0.5

        # Critical: no entry should have score 0.9 (m1's score must not leak).
        for entry in shortTerm:
            assert entry.get("score") != 0.9

    async def test_allStaleIds_omitsUserMemoriesKey(self, testDatabase: Database) -> None:
        """When all referenced memory IDs resolve to ``None``, ``userMemories`` is omitted.

        ``getMemoriesByIds`` signals not-found by mapping the ID to ``None``
        (negative caching). When every ID is stale, ``formatForLLM`` must OMIT
        the ``userMemories`` key entirely — NOT emit an empty
        ``{"permanent": [], "shortTerm": []}`` dict. This locks the behavioral
        delta vs the old eager-resolution code.

        Args:
            testDatabase: Real in-memory database; never read (no media).
        """
        msg = _makeEnsuredMessage()
        msg.metadata["memories"] = {"permanentIds": ["ghost"], "shortTermIds": []}  # type: ignore[assignment]

        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(return_value={"ghost": None})

        output = await msg.formatForLLM(
            testDatabase, format=LLMMessageFormat.JSON, cache=cache, excludeMemoryIds=set()  # type: ignore[arg-type]
        )

        parsed = json.loads(output)
        assert "userMemories" not in parsed
        # Byte-identity: the key must not appear anywhere in the raw string.
        assert "userMemories" not in output

    async def test_cacheNone_omitsUserMemoriesKey(self, testDatabase: Database) -> None:
        """With ``cache=None`` the ``userMemories`` key is never emitted (non-chat paths)."""
        msg = _makeEnsuredMessage()
        msg.metadata["memories"] = {"permanentIds": ["p1"], "shortTermIds": []}  # type: ignore[assignment]

        output = await msg.formatForLLM(testDatabase, format=LLMMessageFormat.JSON, cache=None, excludeMemoryIds=set())

        parsed = json.loads(output)
        assert "userMemories" not in parsed
        assert "userMemories" not in output

    async def test_shortTermScores_mergedIntoEntries(self, testDatabase: Database) -> None:
        """When ``shortTermScores`` is present, each matching short-term entry gets its score.

        The scores map stored in ``metadata["memories"]["shortTermScores"]`` is merged into
        the resolved short-term memory entries by memory ID.

        Args:
            testDatabase: Real in-memory database; never read (no media).
        """
        msg = _makeEnsuredMessage()
        msg.metadata["memories"] = {  # type: ignore[assignment]
            "permanentIds": [],
            "shortTermIds": ["s1", "s2"],
            "shortTermScores": {"s1": 0.95, "s2": 0.87},
        }

        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(
            return_value={
                "s1": {"type": MemoryType.EVENT, "content": "just woke up", "tags": []},
                "s2": {"type": MemoryType.PREFERENCE, "content": "likes coffee", "tags": []},
            }
        )

        output = await msg.formatForLLM(
            testDatabase, format=LLMMessageFormat.JSON, cache=cache, excludeMemoryIds=set()  # type: ignore[arg-type]
        )

        parsed = json.loads(output)
        assert "userMemories" in parsed
        shortTerm = parsed["userMemories"]["shortTerm"]
        # Scores are merged into each entry by memory_id.
        assert shortTerm[0]["score"] == 0.95
        assert shortTerm[1]["score"] == 0.87

    async def test_shortTermScoresAbsent_noScoreKey(self, testDatabase: Database) -> None:
        """When ``shortTermScores`` is absent, short-term entries have NO ``score`` key.

        The key is NOT added when the map is missing (e.g., latest-mode retrieval).

        Args:
            testDatabase: Real in-memory database; never read (no media).
        """
        msg = _makeEnsuredMessage()
        msg.metadata["memories"] = {"permanentIds": [], "shortTermIds": ["s1"]}  # type: ignore[assignment]

        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(
            return_value={"s1": {"type": MemoryType.EVENT, "content": "just woke up", "tags": []}}
        )

        output = await msg.formatForLLM(
            testDatabase, format=LLMMessageFormat.JSON, cache=cache, excludeMemoryIds=set()  # type: ignore[arg-type]
        )

        parsed = json.loads(output)
        assert "userMemories" in parsed
        shortTerm = parsed["userMemories"]["shortTerm"][0]
        assert "score" not in shortTerm

    async def test_permanentEntriesNeverHaveScore(self, testDatabase: Database) -> None:
        """Permanent entries NEVER get a ``score`` key, even when ``shortTermScores`` exists.

        The score-merge path only touches short-term entries.

        Args:
            testDatabase: Real in-memory database; never read (no media).
        """
        msg = _makeEnsuredMessage()
        msg.metadata["memories"] = {  # type: ignore[assignment]
            "permanentIds": ["p1"],
            "shortTermIds": ["s1"],
            "shortTermScores": {"s1": 0.95, "p1": 0.99},
        }

        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(
            return_value={
                "p1": {"type": MemoryType.FACT, "content": "vegan", "tags": ["diet"]},
                "s1": {"type": MemoryType.EVENT, "content": "just woke up", "tags": []},
            }
        )

        output = await msg.formatForLLM(
            testDatabase, format=LLMMessageFormat.JSON, cache=cache, excludeMemoryIds=set()  # type: ignore[arg-type]
        )

        parsed = json.loads(output)
        assert "userMemories" in parsed
        permanent = parsed["userMemories"]["permanent"][0]
        shortTerm = parsed["userMemories"]["shortTerm"][0]
        assert "score" not in permanent
        assert shortTerm["score"] == 0.95

    async def test_shortTermEntryNotInScores_staysScoreless(self, testDatabase: Database) -> None:
        """A short-term entry whose ID is NOT in ``shortTermScores`` gets NO ``score`` key.

        Partial map: only IDs present in the scores map get the key.

        Args:
            testDatabase: Real in-memory database; never read (no media).
        """
        msg = _makeEnsuredMessage()
        msg.metadata["memories"] = {  # type: ignore[assignment]
            "permanentIds": [],
            "shortTermIds": ["s1", "s2"],
            "shortTermScores": {"s1": 0.95},
        }

        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(
            return_value={
                "s1": {"type": MemoryType.EVENT, "content": "just woke up", "tags": []},
                "s2": {"type": MemoryType.PREFERENCE, "content": "likes coffee", "tags": []},
            }
        )

        output = await msg.formatForLLM(
            testDatabase, format=LLMMessageFormat.JSON, cache=cache, excludeMemoryIds=set()  # type: ignore[arg-type]
        )

        parsed = json.loads(output)
        assert "userMemories" in parsed
        shortTerm = parsed["userMemories"]["shortTerm"]
        # s1 is in the scores map, so it gets a score.
        assert shortTerm[0]["score"] == 0.95
        # s2 is NOT in the scores map, so it stays scoreless.
        assert "score" not in shortTerm[1]

    async def test_cacheMutation_bug_shortTermScoresLeakBetweenCalls(self, testDatabase: Database) -> None:
        """CRITICAL: First call with score must NOT pollute the cache entry for a second call without score.

        Regression test for the cache-mutation bug: ``resolved.get(mid)`` returns a DIRECT reference
        into the shared LRU cache (CacheService.getMemoriesByIds returns ``self.memories.get(...)`` raw).
        If we mutate that dict by doing ``entry["score"] = ...``, the score becomes permanently stored
        in the cache and leaks into subsequent renders even when they have no ``shortTermScores``.

        This test would FAIL with the buggy code (the second call would see ``score == 0.92`` because the
        first call mutated the cached entry). After the fix, it PASSES (scores are shallow-copied, cache
        is not mutated).

        Args:
            testDatabase: Real in-memory database; never read (no media).
        """
        # Shared cache instance carrying one short-term memory entry.
        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(
            return_value={"m1": {"type": MemoryType.EVENT, "content": "just woke up", "tags": []}}
        )

        # First message: HAS shortTermScores.
        msg1 = _makeEnsuredMessage()
        msg1.metadata["memories"] = {  # type: ignore[assignment]
            "permanentIds": [],
            "shortTermIds": ["m1"],
            "shortTermScores": {"m1": 0.92},
        }

        output1 = await msg1.formatForLLM(
            testDatabase, format=LLMMessageFormat.JSON, cache=cache, excludeMemoryIds=set()  # type: ignore[arg-type]
        )

        parsed1 = json.loads(output1)
        assert "userMemories" in parsed1
        assert parsed1["userMemories"]["shortTerm"][0]["score"] == 0.92

        # Second message: NO shortTermScores (simulating latest-mode / scoreless render).
        # The SAME cache instance is used — the cached entry must NOT have been mutated.
        msg2 = _makeEnsuredMessage()
        msg2.metadata["memories"] = {"permanentIds": [], "shortTermIds": ["m1"]}  # type: ignore[assignment]

        output2 = await msg2.formatForLLM(
            testDatabase, format=LLMMessageFormat.JSON, cache=cache, excludeMemoryIds=set()  # type: ignore[arg-type]
        )

        parsed2 = json.loads(output2)
        assert "userMemories" in parsed2
        # CRITICAL: The score key must NOT be present — it was never added this time.
        assert "score" not in parsed2["userMemories"]["shortTerm"][0]


# ---------------------------------------------------------------------------
# Phase 3b: toModelMessageList randomContext read site
# (dict shape injects text; legacy str still works)
# ---------------------------------------------------------------------------


class TestRandomContextReadSite:
    """Phase 4: ``toModelMessageList`` injects ``randomContext`` as JSON.

    After the P3b write-site reshape, ``randomContext`` can be a
    :class:`CondensingDict` (dict) or a legacy ``str``. Both shapes are now
    rendered as JSON via :func:`renderCondensedSummary` (Phase 4) — resolving
    the latent asymmetry where real user messages were JSON but summaries
    were raw text. The ``type: "condensed"`` discriminator marks the JSON
    object as a condensed summary.

    ``toModelMessage`` (the inner single-message method called at the end of
    ``toModelMessageList``) is patched to avoid DB/media access.
    """

    async def test_dictShapeInjectsJSON(self, testDatabase: Database) -> None:
        """CondensingDict randomContext -> JSON with type:"condensed" and metadata.

        Args:
            testDatabase: Real in-memory database; never read (inner method patched).
        """
        msg = _makeEnsuredMessage()
        msg.metadata["randomContext"] = {  # type: ignore[assignment]
            "text": "dict summary text",
            "tillMessageId": MessageId(99),
            "tillTS": 1234.0,
            "messageIds": [MessageId(1), MessageId(2)],
            "participants": ["alice"],
            "messageCount": 2,
        }

        with patch.object(
            EnsuredMessage,
            "toModelMessage",
            AsyncMock(return_value=ModelMessage(role="user", content="MAIN")),
        ):
            result = await msg.toModelMessageList(testDatabase, format=LLMMessageFormat.JSON, cache=None)

        assert len(result) == 2
        assert result[0].role == "user"
        parsed = json.loads(result[0].content)
        assert parsed["type"] == "condensed"
        assert parsed["summary"] == "dict summary text"
        assert parsed["coveredMessageIds"] == [1, 2]
        assert parsed["participants"] == ["alice"]
        assert parsed["messageCount"] == 2
        # The main message follows.
        assert result[1].content == "MAIN"

    async def test_strShapeInjectsJSONBackwardsCompat(self, testDatabase: Database) -> None:
        """Legacy str randomContext -> JSON with summary only (backwards-compat).

        Args:
            testDatabase: Real in-memory database; never read (inner method patched).
        """
        msg = _makeEnsuredMessage()
        msg.metadata["randomContext"] = "legacy str context"  # type: ignore[assignment]

        with patch.object(
            EnsuredMessage,
            "toModelMessage",
            AsyncMock(return_value=ModelMessage(role="user", content="MAIN")),
        ):
            result = await msg.toModelMessageList(testDatabase, format=LLMMessageFormat.JSON, cache=None)

        assert len(result) == 2
        parsed = json.loads(result[0].content)
        assert parsed["type"] == "condensed"
        assert parsed["summary"] == "legacy str context"
        # Metadata fields omitted for legacy str input
        assert "coveredMessageIds" not in parsed
        assert "participants" not in parsed
        assert result[1].content == "MAIN"

    async def test_absentRandomContextInjectsNothing(self, testDatabase: Database) -> None:
        """No randomContext -> only the main message (no injection).

        Args:
            testDatabase: Real in-memory database; never read (inner method patched).
        """
        msg = _makeEnsuredMessage()

        with patch.object(
            EnsuredMessage,
            "toModelMessage",
            AsyncMock(return_value=ModelMessage(role="user", content="MAIN")),
        ):
            result = await msg.toModelMessageList(testDatabase, format=LLMMessageFormat.JSON, cache=None)

        assert len(result) == 1
        assert result[0].content == "MAIN"
