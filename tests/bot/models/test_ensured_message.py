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

Native-vision v2 Phase B additions (:class:`TestNativeVisionConstructionAttach`):
the opt-in, unwired construction-time image attach — ``toModelMessage``
``nativeImages=`` sequencing (skip/partial/plain paths, ghost rule,
never-raise boundary), ``formatForLLM`` ``skipMediaDescription=`` (including
the TEXT-branch pre-populated-attribute trap), and the at-most-once lazy
description resolver.
"""

import datetime
import json
from typing import Dict, Optional
from unittest.mock import AsyncMock, Mock, call, patch

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
from internal.services.storage.exceptions import StorageConfigError
from internal.services.storage.service import StorageService
from lib.ai import ModelImagesMessage, ModelMessage
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


# ---------------------------------------------------------------------------
# Native-vision v2 Phase B: construction-time image attach (opt-in, unwired)
# ---------------------------------------------------------------------------


def _makeMediaMessage() -> EnsuredMessage:
    """Build a real :class:`EnsuredMessage` carrying a two-image album.

    Descriptions are pre-filled via ``addMedia`` (the ``fromDBChatMessage``
    shape) so renders do not depend on DB fills; ``self.mediaContent`` is
    deliberately pre-populated ("a red square") — exactly the attribute state
    that makes the §4.2 TEXT-branch guard a trap on the skip path.

    Returns:
        A freshly constructed :class:`EnsuredMessage` with two described media.
    """
    ensuredMessage = EnsuredMessage(
        sender=MessageSender(id=7, name="Alice", username="@alice"),
        recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
        messageId=42,
        date=datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
        messageText="look at these",
    )
    ensuredMessage.threadId = DEFAULT_THREAD_ID
    ensuredMessage.addMedia(mediaId="media-1", mediaContent="a red square", setMediaId=True)
    ensuredMessage.addMedia(mediaId="media-2", mediaContent="a blue circle", setMediaId=False)
    return ensuredMessage


def _mediaRow(mediaId: str, visionUrl: Optional[str] = None, description: str = "a red square") -> Dict[str, object]:
    """Build a minimal ``MediaAttachmentDict``-shaped row (DONE status).

    Only keys the production code reads are populated; timestamps are dummy
    (unused on the DONE fast path of ``_awaitMedia``).

    Args:
        mediaId: Value for ``file_unique_id``.
        visionUrl: Value for ``vision_url`` (None = describable-not-attached).
        description: Value for ``description``.

    Returns:
        A dict shaped like a ``media_attachments`` row.
    """
    return {
        "file_unique_id": mediaId,
        "file_id": None,
        "file_size": 3,
        "media_type": "photo",
        "metadata": "{}",
        "status": "done",
        "mime_type": "image/jpeg",
        "local_url": None,
        "prompt": None,
        "description": description,
        "vision_url": visionUrl,
        "created_at": datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
        "updated_at": datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
    }


def _makeDb(rows: Dict[str, Dict[str, object]]) -> Mock:
    """Build a Mock ``db`` whose ``mediaAttachments.getMediaAttachment`` serves the given rows.

    Args:
        rows: Mapping from media id to row dict; unknown ids return None (ghost).

    Returns:
        A Mock suitable for the ``db: Database`` parameters.
    """
    db = Mock()
    db.mediaAttachments.getMediaAttachment = AsyncMock(side_effect=lambda mediaId, **kwargs: rows.get(mediaId))
    return db


class TestNativeVisionConstructionAttach:
    """Phase B: opt-in construction attach on :meth:`EnsuredMessage.toModelMessage`.

    Nothing in production passes ``nativeImages=True`` yet (Phase C owns the
    wiring); these tests drive the flag directly. Covering: the §4.3
    skip/partial/plain sequencing (bytes BEFORE render), the ghost rule, the
    never-raise boundary around the vision attempt, the §4.2
    ``skipMediaDescription`` render (both branches, incl. the TEXT-branch
    pre-populated-attribute trap), and the §4.4 at-most-once lazy resolver.
    """

    async def test_constructionHappyPath_allBytesAttach_skipDescription(self) -> None:
        """All bytes load -> ModelImagesMessage, no description rendered, no wait.

        Returns:
            None
        """
        msg = _makeMediaMessage()
        db = _makeDb(
            {
                "media-1": _mediaRow("media-1", visionUrl="vision/media-1.jpg"),
                "media-2": _mediaRow("media-2", visionUrl="vision/media-2.jpg"),
            }
        )
        storage = Mock()
        storage.get = Mock(return_value=b"IMG")
        with (
            patch.object(StorageService, "getInstance", return_value=storage),
            patch.object(EnsuredMessage, "updateMediaContent", new=AsyncMock()) as updateMediaContentMock,
        ):
            result = await msg.toModelMessage(db, cache=None, nativeImages=True)

        assert type(result) is ModelImagesMessage
        assert result.images == [bytearray(b"IMG"), bytearray(b"IMG")]
        assert result.source is msg
        # Skip path: the JSON envelope carries NO mediaDescription key.
        parsed = json.loads(result.content)
        assert "mediaDescription" not in parsed
        assert "mediaDescription" not in result.content
        # The description wait never ran on the skip path...
        updateMediaContentMock.assert_not_awaited()
        # ...but the resolver closure exists for the condenser.
        assert result.descriptionResolver is not None
        # Storage consulted once per describable media, with the row's url.
        storage.get.assert_has_calls([call("vision/media-1.jpg"), call("vision/media-2.jpg")])
        assert storage.get.call_count == 2

    async def test_constructionHappyPath_textFormat_noPrependDespitePopulatedAttribute(self) -> None:
        """TEXT skip path: no `<media-description>` prepend even with mediaContent populated.

        The §4.2 trap: ``self.mediaContent`` is pre-populated ("a red square");
        the old attribute-only guard would prepend a description block on the
        skip path.

        Returns:
            None
        """
        msg = _makeMediaMessage()
        db = _makeDb(
            {
                "media-1": _mediaRow("media-1", visionUrl="vision/media-1.jpg"),
                "media-2": _mediaRow("media-2", visionUrl="vision/media-2.jpg"),
            }
        )
        storage = Mock()
        storage.get = Mock(return_value=b"IMG")
        with (
            patch.object(StorageService, "getInstance", return_value=storage),
            patch.object(EnsuredMessage, "updateMediaContent", new=AsyncMock()),
        ):
            result = await msg.toModelMessage(db, format=LLMMessageFormat.TEXT, cache=None, nativeImages=True)

        assert type(result) is ModelImagesMessage
        assert result.content == "look at these"
        assert "<media-description>" not in result.content

    async def test_formatForLLMSkipDescription_jsonOmitsKeyAndSkipsWait(self) -> None:
        """``skipMediaDescription=True`` drops the JSON key and skips the wait.

        Returns:
            None
        """
        msg = _makeMediaMessage()
        db = Mock()
        with patch.object(EnsuredMessage, "updateMediaContent", new=AsyncMock()) as updateMediaContentMock:
            skipped = await msg.formatForLLM(db, format=LLMMessageFormat.JSON, skipMediaDescription=True, cache=None)
            updateMediaContentMock.assert_not_awaited()

            # Control: default render waits and emits the description.
            default = await msg.formatForLLM(db, format=LLMMessageFormat.JSON, cache=None)
            updateMediaContentMock.assert_awaited_once()

        assert "mediaDescription" not in json.loads(skipped)
        assert json.loads(default)["mediaDescription"] == "a red square"

    async def test_formatForLLMSkipDescription_textTrap_prePopulatedAttribute(self) -> None:
        """Direct TEXT render with skip: no prepend despite populated mediaContent.

        Regression for the §4.2 trap at the ``formatForLLM`` level: the guard
        must not fire on the attribute alone.

        Returns:
            None
        """
        msg = _makeMediaMessage()  # self.mediaContent == "a red square"
        db = Mock()
        with patch.object(EnsuredMessage, "updateMediaContent", new=AsyncMock()):
            skipped = await msg.formatForLLM(db, format=LLMMessageFormat.TEXT, skipMediaDescription=True, cache=None)
            control = await msg.formatForLLM(db, format=LLMMessageFormat.TEXT, cache=None)

        assert skipped == "look at these"
        assert control == "<media-description>a red square</media-description>\n\nlook at these"

    async def test_bytesMiss_fallsBackToPlainMessageWithDescriptionAndWait(self) -> None:
        """Storage misses every url -> plain ModelMessage WITH description and the wait.

        Returns:
            None
        """
        msg = _makeMediaMessage()
        db = _makeDb(
            {
                "media-1": _mediaRow("media-1", visionUrl="vision/media-1.jpg"),
                "media-2": _mediaRow("media-2", visionUrl="vision/media-2.jpg"),
            }
        )
        storage = Mock()
        storage.get = Mock(return_value=None)
        with (
            patch.object(StorageService, "getInstance", return_value=storage),
            patch.object(
                EnsuredMessage, "_awaitMedia", new=AsyncMock(return_value=_mediaRow("media-1"))
            ) as awaitMediaMock,
        ):
            result = await msg.toModelMessage(db, cache=None, nativeImages=True)

        assert type(result) is ModelMessage
        parsed = json.loads(result.content)
        assert parsed["mediaDescription"] == "a red square"
        # The wait executed (updateMediaContent runs unmocked over the mocked
        # _awaitMedia: once per mediaList entry + once for self.mediaId).
        assert awaitMediaMock.await_count == 3
        # The bytes load was still attempted before falling back.
        assert storage.get.call_count == 2

    async def test_partialAlbum_attachSubsetWithDescription_noResolver(self) -> None:
        """Partially loaded album: subset attached ALONGSIDE the description; no resolver.

        Returns:
            None
        """
        msg = _makeMediaMessage()
        db = _makeDb(
            {
                "media-1": _mediaRow("media-1", visionUrl="vision/media-1.jpg"),
                "media-2": _mediaRow("media-2", visionUrl="vision/media-2.jpg"),
            }
        )
        storage = Mock()
        storage.get = Mock(side_effect=lambda key: b"IMG" if key == "vision/media-1.jpg" else None)
        with (
            patch.object(StorageService, "getInstance", return_value=storage),
            patch.object(EnsuredMessage, "updateMediaContent", new=AsyncMock()),
        ):
            result = await msg.toModelMessage(db, cache=None, nativeImages=True)

        assert type(result) is ModelImagesMessage
        assert result.images == [bytearray(b"IMG")]
        parsed = json.loads(result.content)
        assert parsed["mediaDescription"] == "a red square"
        # Envelope already carries the descriptions — no resolver needed.
        assert result.descriptionResolver is None

    async def test_ghostMedia_doesNotBlockSkip(self) -> None:
        """A row-less (ghost) entry never blocks the skip path.

        Returns:
            None
        """
        msg = _makeMediaMessage()
        db = _makeDb({"media-1": _mediaRow("media-1", visionUrl="vision/media-1.jpg")})  # media-2: ghost
        storage = Mock()
        storage.get = Mock(return_value=b"IMG")
        with (
            patch.object(StorageService, "getInstance", return_value=storage),
            patch.object(EnsuredMessage, "updateMediaContent", new=AsyncMock()) as updateMediaContentMock,
        ):
            result = await msg.toModelMessage(db, cache=None, nativeImages=True)

        assert type(result) is ModelImagesMessage
        assert result.images == [bytearray(b"IMG")]
        assert "mediaDescription" not in json.loads(result.content)
        updateMediaContentMock.assert_not_awaited()
        assert result.descriptionResolver is not None

    async def test_neverRaises_dbFetchFailure_fallsBackToDescriptionPath(self) -> None:
        """A DB fetch exception inside the vision attempt degrades to the description path.

        Returns:
            None
        """
        msg = _makeMediaMessage()
        # Call order: _loadNativeVisionImages(media-1) raises, then the real
        # updateMediaContent serves media-1, media-2, mediaId(media-1).
        db = Mock()
        db.mediaAttachments.getMediaAttachment = AsyncMock(
            side_effect=[
                RuntimeError("db boom"),
                _mediaRow("media-1", description="a red square"),
                _mediaRow("media-2", description="a blue circle"),
                _mediaRow("media-1", description="a red square"),
            ]
        )
        storage = Mock()
        storage.get = Mock(return_value=b"IMG")
        with patch.object(StorageService, "getInstance", return_value=storage):
            result = await msg.toModelMessage(db, cache=None, nativeImages=True)

        assert type(result) is ModelMessage
        parsed = json.loads(result.content)
        assert parsed["mediaDescription"] == "a red square"
        # If the exception had escaped the never-raise boundary, storage.get
        # would never have been reached; reaching the description path means
        # the boundary swallowed it.
        storage.get.assert_not_called()

    async def test_neverRaises_storageGetFailure_fallsBackToDescriptionPath(self) -> None:
        """A storage.get exception degrades to the description path.

        Returns:
            None
        """
        msg = _makeMediaMessage()
        db = _makeDb(
            {
                "media-1": _mediaRow("media-1", visionUrl="vision/media-1.jpg"),
                "media-2": _mediaRow("media-2", visionUrl="vision/media-2.jpg"),
            }
        )
        storage = Mock()
        storage.get = Mock(side_effect=RuntimeError("storage boom"))
        with (
            patch.object(StorageService, "getInstance", return_value=storage),
            patch.object(EnsuredMessage, "_awaitMedia", new=AsyncMock(return_value=_mediaRow("media-1"))),
        ):
            result = await msg.toModelMessage(db, cache=None, nativeImages=True)

        assert type(result) is ModelMessage
        assert json.loads(result.content)["mediaDescription"] == "a red square"

    async def test_neverRaises_storageUninitialized_fallsBackToDescriptionPath(self) -> None:
        """An uninitialized StorageService (StorageConfigError) degrades to the description path.

        Returns:
            None
        """
        msg = _makeMediaMessage()
        db = _makeDb(
            {
                "media-1": _mediaRow("media-1", visionUrl="vision/media-1.jpg"),
                "media-2": _mediaRow("media-2", visionUrl="vision/media-2.jpg"),
            }
        )
        storage = Mock()
        storage.get = Mock(side_effect=StorageConfigError("StorageService is not initialized"))
        with (
            patch.object(StorageService, "getInstance", return_value=storage),
            patch.object(EnsuredMessage, "_awaitMedia", new=AsyncMock(return_value=_mediaRow("media-1"))),
        ):
            result = await msg.toModelMessage(db, cache=None, nativeImages=True)

        assert type(result) is ModelMessage
        assert json.loads(result.content)["mediaDescription"] == "a red square"

    async def test_defaultFalse_nativeImagesAbsent_byteIdenticalAndNoLoad(self) -> None:
        """Default call: today's exact render; the vision load is never attempted.

        Returns:
            None
        """
        msg = _makeMediaMessage()
        db = _makeDb(
            {
                "media-1": _mediaRow("media-1", visionUrl="vision/media-1.jpg"),
                "media-2": _mediaRow("media-2", visionUrl="vision/media-2.jpg"),
            }
        )
        storage = Mock()
        storage.get = Mock(return_value=b"IMG")  # bytes WOULD be available
        with (
            patch.object(StorageService, "getInstance", return_value=storage),
            patch.object(EnsuredMessage, "_awaitMedia", new=AsyncMock(return_value=_mediaRow("media-1"))),
            patch.object(EnsuredMessage, "_loadNativeVisionImages", new=Mock()) as loadMock,
        ):
            result = await msg.toModelMessage(db, cache=None)
            directRender = await msg.formatForLLM(db, format=LLMMessageFormat.JSON, cache=None)

        loadMock.assert_not_called()
        storage.get.assert_not_called()
        assert type(result) is ModelMessage
        parsed = json.loads(result.content)
        assert parsed["mediaDescription"] == "a red square"
        # Byte-identity with the PRE-Phase-B render: a fixed expected string
        # for this deterministic fixture (independent of today's renderer), so
        # any drift in the default JSON envelope fails here.
        expectedRender = (
            '{"date": "2026-05-05T12:00:00+00:00", "login": "@alice", "mediaDescription": "a red square", '
            '"messageId": 42, "name": "Alice", "text": "look at these", "type": "unknown"}'
        )
        assert result.content == expectedRender
        assert result.content == directRender

    async def test_resolver_atMostOnce_joinsDescriptions(self) -> None:
        """The resolver joins descriptions, awaits the wait once, and caches.

        Returns:
            None
        """
        msg = _makeMediaMessage()
        db = _makeDb(
            {
                "media-1": _mediaRow("media-1", visionUrl="vision/media-1.jpg"),
                "media-2": _mediaRow("media-2", visionUrl="vision/media-2.jpg"),
            }
        )
        storage = Mock()
        storage.get = Mock(return_value=b"IMG")
        with (
            patch.object(StorageService, "getInstance", return_value=storage),
            patch.object(EnsuredMessage, "updateMediaContent", new=AsyncMock()) as updateMediaContentMock,
        ):
            result = await msg.toModelMessage(db, cache=None, nativeImages=True)
            assert result.descriptionResolver is not None

            first = await result.descriptionResolver()
            updateMediaContentMock.assert_awaited_once()
            assert first == "a red square\na blue circle"

            # Second call: served from the closure cache, no second wait.
            second = await result.descriptionResolver()
            updateMediaContentMock.assert_awaited_once()
            assert second == "a red square\na blue circle"

    async def test_resolver_emptyDescriptions_resolvesNone(self) -> None:
        """The §4.4 empty branch: no descriptions anywhere resolves to None.

        Returns:
            None
        """
        msg = _makeMediaMessage()
        for media in msg.mediaList:
            media.content = None  # nothing described anywhere
        db = _makeDb(
            {
                "media-1": _mediaRow("media-1", visionUrl="vision/media-1.jpg"),
                "media-2": _mediaRow("media-2", visionUrl="vision/media-2.jpg"),
            }
        )
        storage = Mock()
        storage.get = Mock(return_value=b"IMG")
        with (
            patch.object(StorageService, "getInstance", return_value=storage),
            patch.object(EnsuredMessage, "updateMediaContent", new=AsyncMock()) as updateMediaContentMock,
        ):
            result = await msg.toModelMessage(db, cache=None, nativeImages=True)
            assert result.descriptionResolver is not None

            resolved = await result.descriptionResolver()

        assert resolved is None
        updateMediaContentMock.assert_awaited_once()

    async def test_resolver_swallowsUpdateMediaContentException(self) -> None:
        """The resolver never raises: a failed wait resolves to None.

        Returns:
            None
        """
        msg = _makeMediaMessage()
        db = _makeDb(
            {
                "media-1": _mediaRow("media-1", visionUrl="vision/media-1.jpg"),
                "media-2": _mediaRow("media-2", visionUrl="vision/media-2.jpg"),
            }
        )
        storage = Mock()
        storage.get = Mock(return_value=b"IMG")
        with (
            patch.object(StorageService, "getInstance", return_value=storage),
            patch.object(
                EnsuredMessage, "updateMediaContent", new=AsyncMock(side_effect=RuntimeError("boom"))
            ) as updateMediaContentMock,
        ):
            result = await msg.toModelMessage(db, cache=None, nativeImages=True)
            assert result.descriptionResolver is not None

            resolved = await result.descriptionResolver()

        assert resolved is None
        updateMediaContentMock.assert_awaited_once()

    async def test_toModelMessageList_forwardsNativeImages(self) -> None:
        """``toModelMessageList`` forwards ``nativeImages`` 1:1 to the main message.

        Returns:
            None
        """
        msg = _makeMediaMessage()
        with patch.object(
            EnsuredMessage,
            "toModelMessage",
            new=AsyncMock(return_value=ModelMessage(role="user", content="MAIN")),
        ) as toModelMessageMock:
            await msg.toModelMessageList(db=Mock(), cache=None, nativeImages=True)
            forwardCall = toModelMessageMock.await_args
            assert forwardCall is not None
            assert forwardCall.kwargs["nativeImages"] is True

            await msg.toModelMessageList(db=Mock(), cache=None)
            defaultCall = toModelMessageMock.await_args
            assert defaultCall is not None
            assert defaultCall.kwargs["nativeImages"] is False
