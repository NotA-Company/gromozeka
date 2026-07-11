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
from unittest.mock import AsyncMock, Mock

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
from internal.database.utils import DEFAULT_THREAD_ID


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
