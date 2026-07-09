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
    ``userData`` is left at its ``None`` default.

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

        output = await ensuredMessage.formatForLLM(testDatabase, format=LLMMessageFormat.JSON)

        parsed = json.loads(output)
        assert "userSummary" not in parsed
        # Byte-identity: the field name must not appear anywhere in the string.
        assert "userSummary" not in output

    async def test_formatForLLMJsonOmitsUserSummaryWhenUserMemoriesSet(self, testDatabase: Database) -> None:
        """Even when ``userMemories`` is populated, no ``userSummary`` key sneaks in.

        Confirms the removal did not leave the key reachable via the truthiness
        filter when a sibling optional field is populated.

        Args:
            testDatabase: Real in-memory database; never read because the
                message has no media.
        """
        ensuredMessage = _makeEnsuredMessage()
        ensuredMessage.setUserMemories(
            {
                "permanent": [
                    {"type": MemoryType.PREFERENCE, "content": "vegan", "tags": ["diet"]},
                ],
                "shortTerm": [],
            }
        )

        output = await ensuredMessage.formatForLLM(testDatabase, format=LLMMessageFormat.JSON)

        parsed = json.loads(output)
        assert "userSummary" not in parsed
        assert "userSummary" not in output
        # Sanity: userMemories is still emitted (proves the assertion is meaningful).
        assert "userMemories" in parsed


# ---------------------------------------------------------------------------
# Compact memory-ID format resolution (memory-compaction-v1 Phase 3a)
# ---------------------------------------------------------------------------


def _singleMemory(
    content: str, *, type_: MemoryType = MemoryType.FACT, tags: list[str] | None = None
) -> SingleMemoryDict:
    """Build a minimal :class:`SingleMemoryDict` without an ``id`` field.

    Mirrors the shape produced by ``convertDBMemoryToSingleMemoryDict(keepId=False)``
    (the by-id cache form): no ``id`` key, which is what ``resolveMemories`` must
    preserve so no uuid leaks into ``formatForLLM``.

    Args:
        content: Memory body text.
        type_: Memory category (default FACT).
        tags: Tag list (default a single sentinel tag).

    Returns:
        A fresh :class:`SingleMemoryDict` with no ``id`` key.
    """
    return {"type": type_, "content": content, "tags": tags if tags is not None else ["test"]}


class TestMemoriesResolution:
    """Tests for the compact memory-ID format stash/resolve methods.

    Phase 3a of the memory-compaction-v1 plan: ``loadMemoriesMetadata`` stashes
    the compact ID format into ``metadata["memories"]`` without resolving (leaving
    ``userMemories=None``), and ``resolveMemories`` resolves IDs -> content via
    the cache WITHOUT re-pointing ``metadata["memories"]`` (the condense write
    path persists the whole metadata dict, so re-pointing to content would
    defeat compaction).
    """

    # --- loadMemoriesMetadata ---

    def test_loadMemoriesMetadata_compactFormat_stashesIdsLeavesUserMemoriesNone(self) -> None:
        """Compact format (``permanentIds``/``shortTermIds``) stashes raw IDs and leaves ``userMemories`` unset.

        Regression guard for the read-path contract: the compact dict must be
        stored verbatim in ``metadata["memories"]`` (resolved later by
        ``resolveMemories``), and ``userMemories`` must remain ``None``.
        """
        msg = _makeEnsuredMessage()
        raw = {"permanentIds": ["a"], "shortTermIds": ["b"]}

        msg.loadMemoriesMetadata(raw)  # type: ignore[arg-type]

        assert msg.userMemories is None
        assert msg.metadata.get("memories") == {"permanentIds": ["a"], "shortTermIds": ["b"]}

    def test_loadMemoriesMetadata_compactFormat_detectsOnlyOneKey(self) -> None:
        """A compact dict with only ``permanentIds`` (no ``shortTermIds``) is still detected as compact."""
        msg = _makeEnsuredMessage()

        msg.loadMemoriesMetadata({"permanentIds": ["x"]})  # type: ignore[arg-type]

        assert msg.userMemories is None
        assert msg.metadata.get("memories") == {"permanentIds": ["x"]}

    def test_loadMemoriesMetadata_oldContentFormat_appliesSetUserMemories(self) -> None:
        """Old content format (``permanent``/``shortTerm``) is applied via ``setUserMemories``.

        ``setUserMemories`` deep-copies and re-points both ``userMemories`` and
        ``metadata["memories"]`` to the content, matching the pre-compaction behaviour.
        """
        msg = _makeEnsuredMessage()
        content = {
            "permanent": [_singleMemory("bio fact")],
            "shortTerm": [_singleMemory("recent fact")],
        }

        msg.loadMemoriesMetadata(content)  # type: ignore[arg-type]

        assert msg.userMemories is not None
        assert msg.userMemories["permanent"][0]["content"] == "bio fact"
        assert msg.metadata.get("memories") is msg.userMemories

    def test_loadMemoriesMetadata_none_isNoOp(self) -> None:
        """``None`` is a no-op (no TypeError).

        Regression guard: bypass sites that did ``metadata.get("memories")`` can
        pass ``None``; the old ``"permanentIds" in None`` would raise ``TypeError``.
        """
        msg = _makeEnsuredMessage()

        msg.loadMemoriesMetadata(None)

        assert msg.userMemories is None
        assert "memories" not in msg.metadata

    def test_loadMemoriesMetadata_nonDict_isNoOp(self) -> None:
        """A non-dict value (e.g. a stray string) is a no-op."""
        msg = _makeEnsuredMessage()

        msg.loadMemoriesMetadata("not a dict")  # type: ignore[arg-type]

        assert msg.userMemories is None
        assert "memories" not in msg.metadata

    # --- resolveMemories ---

    async def test_resolveMemories_compactFormat_resolvesBothCohorts(self) -> None:
        """A compact-format message resolves permanent + shortTerm IDs into ``userMemories``.

        Asserts ``metadata["memories"]`` is UNCHANGED after resolution (the
        no-re-point deviation — see resolveMemories docstring). This is the
        critical regression guard: re-pointing metadata to content would make
        the condense write persist content over compact IDs.
        """
        msg = _makeEnsuredMessage()
        msg.loadMemoriesMetadata({"permanentIds": ["a"], "shortTermIds": ["b"]})  # type: ignore[arg-type]
        rawBefore = msg.metadata.get("memories")
        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(
            return_value={"a": _singleMemory("perm fact"), "b": _singleMemory("short fact")}
        )

        await msg.resolveMemories(cache)  # type: ignore[arg-type]

        assert msg.userMemories is not None
        assert msg.userMemories["permanent"][0]["content"] == "perm fact"
        assert msg.userMemories["shortTerm"][0]["content"] == "short fact"
        # metadata["memories"] must stay the compact ID dict (no re-point).
        assert msg.metadata.get("memories") is rawBefore
        assert msg.metadata.get("memories") == {"permanentIds": ["a"], "shortTermIds": ["b"]}

    async def test_resolveMemories_noOpWhenUserMemoriesAlreadySet(self) -> None:
        """When ``userMemories`` is already populated (old content format), resolution is a no-op.

        The cache is never consulted.
        """
        msg = _makeEnsuredMessage()
        msg.setUserMemories({"permanent": [_singleMemory("inline")], "shortTerm": []})
        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(return_value={})

        await msg.resolveMemories(cache)  # type: ignore[arg-type]

        cache.getMemoriesByIds.assert_not_awaited()
        # Inline content preserved.
        assert msg.userMemories is not None
        assert msg.userMemories["permanent"][0]["content"] == "inline"

    async def test_resolveMemories_noOpWhenNoMemoriesMetadata(self) -> None:
        """When ``metadata["memories"]`` is absent, resolution is a no-op."""
        msg = _makeEnsuredMessage()
        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(return_value={})

        await msg.resolveMemories(cache)  # type: ignore[arg-type]

        cache.getMemoriesByIds.assert_not_awaited()
        assert msg.userMemories is None

    async def test_resolveMemories_noOpWhenMemoriesMetadataIsNone(self) -> None:
        """When ``metadata["memories"]`` is explicitly ``None`` (non-dict), resolution is a no-op."""
        msg = _makeEnsuredMessage()
        msg.metadata["memories"] = None  # type: ignore[assignment]

        await msg.resolveMemories(Mock())  # type: ignore[arg-type]

        assert msg.userMemories is None

    async def test_resolveMemories_noOpOnSecondCall(self) -> None:
        """A second ``resolveMemories`` call is a no-op (``userMemories`` already set)."""
        msg = _makeEnsuredMessage()
        msg.loadMemoriesMetadata({"permanentIds": ["a"], "shortTermIds": []})  # type: ignore[arg-type]
        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(return_value={"a": _singleMemory("perm")})

        await msg.resolveMemories(cache)  # type: ignore[arg-type]
        cache.getMemoriesByIds.assert_awaited_once()
        # Second call: userMemories is now populated, so the cache is not touched.
        await msg.resolveMemories(cache)  # type: ignore[arg-type]
        cache.getMemoriesByIds.assert_awaited_once()

    async def test_resolveMemories_deepCopiesAwayFromCache(self) -> None:
        """Resolved ``userMemories`` is a deep copy — mutating it does not affect the cache's source.

        Mirrors ``setUserMemories``'s deep-copy contract so the in-memory LLM
        snapshot can never mutate the shared cache entry.
        """
        msg = _makeEnsuredMessage()
        originalEntry = _singleMemory("original")
        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(return_value={"a": originalEntry})
        msg.loadMemoriesMetadata({"permanentIds": ["a"], "shortTermIds": []})  # type: ignore[arg-type]

        await msg.resolveMemories(cache)  # type: ignore[arg-type]

        assert msg.userMemories is not None
        msg.userMemories["permanent"][0]["content"] = "mutated"
        # The cache's source entry is untouched.
        assert originalEntry["content"] == "original"

    async def test_resolveMemories_entriesHaveNoId(self) -> None:
        """Resolved entries carry no ``id`` key (by-id cache is ``keepId=False``).

        Regression guard against uuid leaking into ``formatForLLM`` (the
        SingleMemoryDict.id "absent on injected snapshots" invariant).
        """
        msg = _makeEnsuredMessage()
        msg.loadMemoriesMetadata({"permanentIds": ["a"], "shortTermIds": ["b"]})  # type: ignore[arg-type]
        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(return_value={"a": _singleMemory("perm"), "b": _singleMemory("short")})

        await msg.resolveMemories(cache)  # type: ignore[arg-type]

        assert msg.userMemories is not None
        for entry in msg.userMemories["permanent"] + msg.userMemories["shortTerm"]:
            assert "id" not in entry

    async def test_resolveMemories_dropsMissingIds(self) -> None:
        """An ID that resolves to ``None`` (not in DB) is silently dropped from the cohort."""
        msg = _makeEnsuredMessage()
        msg.loadMemoriesMetadata({"permanentIds": ["a", "missing"], "shortTermIds": []})  # type: ignore[arg-type]
        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(return_value={"a": _singleMemory("perm")})

        await msg.resolveMemories(cache)  # type: ignore[arg-type]

        assert msg.userMemories is not None
        assert len(msg.userMemories["permanent"]) == 1
        assert msg.userMemories["permanent"][0]["content"] == "perm"


# ---------------------------------------------------------------------------
# formatForLLM read-path rendering (memory-compaction-v1 Phase 3b-i)
#
# Phase 3b-i wires ``resolveMemories`` into the read-path consumers so compact
# IDs are resolved to content before ``formatForLLM``. These tests guard the
# render output: the ``userMemories`` block must be identical between the old
# content format and the new compact-ID format (resolved), empty compact
# memories must omit the block (an improvement: empty blocks are LLM noise),
# and a mixed old/new pair referencing the same content renders identically.
# ---------------------------------------------------------------------------


def _userMemoriesBlockFromOutput(output: str) -> str:
    """Extract and canonicalise the ``userMemories`` JSON block from a ``formatForLLM`` string.

    Parses the full ``formatForLLM`` JSON output and re-serialises just the
    ``userMemories`` value with sorted keys, so old-vs-new comparisons are
    byte-stable regardless of dict insertion order.

    Args:
        output: The raw string returned by :meth:`EnsuredMessage.formatForLLM`
            (JSON branch).

    Returns:
        A canonical (sorted-key, compact) JSON string of the ``userMemories``
        value, or ``""`` when the key is absent.
    """
    parsed = json.loads(output)
    block = parsed.get("userMemories")
    if block is None:
        return ""
    return json.dumps(block, sort_keys=True, separators=(",", ":"))


class TestFormatForLLMMemoriesResolution:
    """Phase 3b-i: ``formatForLLM`` render output across the compact/new read path.

    Pins the read-path rendering contract after the compact-ID format is wired
    through ``resolveMemories``: the resolved ``userMemories`` block rendered by
    ``formatForLLM`` must be indistinguishable from the old inline-content
    format (regression guard on the read path), empty compact memories omit the
    block entirely, and a mixed old/new pair referencing identical content
    renders the same block.
    """

    async def test_formatForLLM_userMemoriesBlockIdenticalOldVsNewFormat(self, testDatabase: Database) -> None:
        """The ``userMemories`` block is byte-identical between old and new (resolved) format.

        Builds two messages — one old-format (content applied via
        ``setUserMemories``) and one new-format (compact IDs resolved via a stub
        cache returning the same content) — and asserts the rendered
        ``userMemories`` JSON block is canonical-equal. Regression guard: a
        future change to ``resolveMemories`` that altered the resolved shape
        (e.g. reintroduced ``id``, reordered keys, nested differently) would
        break this.

        Args:
            testDatabase: Real in-memory database; never read (no media).
        """
        permEntry = _singleMemory("perm fact", type_=MemoryType.PREFERENCE, tags=["diet"])
        shortEntry = _singleMemory("short fact")

        oldMsg = _makeEnsuredMessage()
        oldMsg.setUserMemories({"permanent": [permEntry], "shortTerm": [shortEntry]})

        newMsg = _makeEnsuredMessage()
        newMsg.loadMemoriesMetadata({"permanentIds": ["a"], "shortTermIds": ["b"]})  # type: ignore[arg-type]
        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(return_value={"a": permEntry, "b": shortEntry})
        await newMsg.resolveMemories(cache)  # type: ignore[arg-type]

        oldOutput = await oldMsg.formatForLLM(testDatabase, format=LLMMessageFormat.JSON)
        newOutput = await newMsg.formatForLLM(testDatabase, format=LLMMessageFormat.JSON)

        assert _userMemoriesBlockFromOutput(oldOutput) == _userMemoriesBlockFromOutput(newOutput)
        # Sanity: the block is actually present (not both empty).
        assert _userMemoriesBlockFromOutput(oldOutput) != ""

    async def test_formatForLLM_emptyCompactMemoriesOmitsUserMemoriesBlock(self, testDatabase: Database) -> None:
        """An empty compact-ID list (``permanentIds=[]``, ``shortTermIds=[]``) omits the block.

        ``resolveMemories`` early-returns when there are no IDs, leaving
        ``userMemories=None``; ``formatForLLM``'s JSON branch drops falsy values
        (``if v``), so the ``userMemories`` key is absent. Documents the
        behavioural improvement vs the old format: an old-format message with
        empty cohorts (``{"permanent":[],"shortTerm":[]}``) is itself a truthy
        dict, so it WAS rendered as an empty block (LLM noise); the compact
        path omits it.

        Args:
            testDatabase: Real in-memory database; never read (no media).
        """
        msg = _makeEnsuredMessage()
        msg.loadMemoriesMetadata({"permanentIds": [], "shortTermIds": []})  # type: ignore[arg-type]
        assert msg.userMemories is None
        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(return_value={})

        await msg.resolveMemories(cache)  # type: ignore[arg-type]

        assert msg.userMemories is None  # resolveMemories no-op'd
        output = await msg.formatForLLM(testDatabase, format=LLMMessageFormat.JSON)
        parsed = json.loads(output)
        assert "userMemories" not in parsed
        # And the literal key never appears in the raw string.
        assert "userMemories" not in output

    async def test_formatForLLM_mixedOldAndNewFormatRenderIdenticalBlock(self, testDatabase: Database) -> None:
        """One old-format + one new-format message referencing the same content render the same block.

        The tractable approximation of the plan's "mixed thread" integration
        test (``getThreadByMessageForLLM`` itself is mocked away in the handler
        tests). At the :class:`EnsuredMessage` level: the old message has its
        content set inline, the new message resolves compact IDs to the same
        content; both render the identical ``userMemories`` block via
        ``formatForLLM``.

        Args:
            testDatabase: Real in-memory database; never read (no media).
        """
        permEntry = _singleMemory("shared perm", type_=MemoryType.FACT)
        shortEntry = _singleMemory("shared short")

        oldMsg = _makeEnsuredMessage()
        oldMsg.setUserMemories({"permanent": [permEntry], "shortTerm": [shortEntry]})

        newMsg = _makeEnsuredMessage()
        newMsg.loadMemoriesMetadata({"permanentIds": ["p1"], "shortTermIds": ["s1"]})  # type: ignore[arg-type]
        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(return_value={"p1": permEntry, "s1": shortEntry})
        await newMsg.resolveMemories(cache)  # type: ignore[arg-type]

        oldBlock = _userMemoriesBlockFromOutput(await oldMsg.formatForLLM(testDatabase, format=LLMMessageFormat.JSON))
        newBlock = _userMemoriesBlockFromOutput(await newMsg.formatForLLM(testDatabase, format=LLMMessageFormat.JSON))

        assert oldBlock == newBlock
        assert oldBlock != ""
