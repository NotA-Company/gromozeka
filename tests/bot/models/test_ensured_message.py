"""Tests for :class:`EnsuredMessage` ``userSummary`` handling.

Two concerns:

* :meth:`EnsuredMessage.formatForLLM` JSON serialisation of ``userSummary``
  (behaviour area (D) of the memory-refinements test plan) — when ``userSummary``
  is ``None`` (the default), the JSON output must omit the ``userSummary`` key
  entirely, both as a parsed-key absence and as a raw substring absence, so a
  pre-feature ``EnsuredMessage`` and a post-feature one with no summary produce
  byte-identical JSON (no trailing comma, no empty field); when ``userSummary``
  is set, the key must appear with the exact value.
* :meth:`EnsuredMessage.applyUserMetadata` summary extraction (relocated from
  the old ``BaseBotHandler.getUserMemorySummary``) — no entry / current-thread /
  sibling-thread / empty-summary cases, asserting on ``ensuredMessage.userSummary``.

``formatForLLM`` is async and accepts a ``db`` argument, but with no media
attached (``mediaId is None`` and empty ``mediaList``) its
``updateMediaContent`` early-returns without ever touching ``db``. The real
``testDatabase`` fixture is passed for full type-correctness; it is never read.
The ``applyUserMetadata`` tests are pure (no DB / cache) and take no fixture.
"""

import datetime
import json
from typing import cast

from internal.bot.models import (
    ChatType,
    EnsuredMessage,
    LLMMessageFormat,
    MessageRecipient,
    MessageSender,
    UserMetadataDict,
)
from internal.database import Database
from internal.database.utils import DEFAULT_THREAD_ID


def _makeEnsuredMessage() -> EnsuredMessage:
    """Build a minimal real :class:`EnsuredMessage` with no media and no summary.

    The sender fields are populated so the emitted JSON is non-empty and stable;
    ``userSummary`` / ``userData`` are left at their ``None`` defaults.

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


class TestFormatForLLMUserSummary:
    """Tests for the ``userSummary`` field in :meth:`EnsuredMessage.formatForLLM`."""

    async def test_userSummaryOmittedWhenNone(self, testDatabase: Database) -> None:
        """Default ``userSummary=None`` → key absent from parsed JSON and raw string.

        Also confirms ``userData`` is likewise dropped when ``None`` (sanity
        check that the truthiness filter treats the new optional field
        consistently with the old one), and that the raw JSON contains no
        ``userSummary`` token at all (byte-identity with pre-feature output).

        Args:
            testDatabase: Real in-memory database; never read because the
                message has no media.
        """
        ensuredMessage = _makeEnsuredMessage()
        assert ensuredMessage.userSummary is None

        output = await ensuredMessage.formatForLLM(testDatabase, format=LLMMessageFormat.JSON)

        parsed = json.loads(output)
        assert "userSummary" not in parsed
        assert "userData" not in parsed
        # Byte-identity: the field name must not appear anywhere in the string.
        assert "userSummary" not in output

    async def test_userSummaryIncludedWhenSet(self, testDatabase: Database) -> None:
        """A non-empty ``userSummary`` is emitted verbatim under the right key.

        Args:
            testDatabase: Real in-memory database; never read because the
                message has no media.
        """
        ensuredMessage = _makeEnsuredMessage()
        ensuredMessage.userSummary = "Likes chess and Python"

        output = await ensuredMessage.formatForLLM(testDatabase, format=LLMMessageFormat.JSON)

        parsed = json.loads(output)
        assert parsed["userSummary"] == "Likes chess and Python"

    async def test_userSummaryDropsEmptyString(self, testDatabase: Database) -> None:
        """An empty-string ``userSummary`` is dropped by the truthiness filter.

        The ``formatForLLM`` JSON branch drops every falsy value, so an empty
        summary must not leak as ``"userSummary": ""`` — it must be absent,
        matching the ``None`` case byte-for-byte.

        Args:
            testDatabase: Real in-memory database; never read because the
                message has no media.
        """
        noneMessage = _makeEnsuredMessage()
        emptyMessage = _makeEnsuredMessage()
        emptyMessage.userSummary = ""

        outputNone = await noneMessage.formatForLLM(testDatabase, format=LLMMessageFormat.JSON)
        outputEmpty = await emptyMessage.formatForLLM(testDatabase, format=LLMMessageFormat.JSON)

        assert "userSummary" not in outputEmpty
        assert outputEmpty == outputNone


class TestApplyUserMetadata:
    """Tests for :meth:`EnsuredMessage.applyUserMetadata` summary extraction.

    Drives four cases (empty metadata / current-thread / sibling-thread isolation
    / empty-string-summary), extending the old ``BaseBotHandler.getUserMemorySummary``
    coverage with an explicit empty-string-summary case for the ``if summary:``
    truthiness guard, through :meth:`EnsuredMessage.applyUserMetadata` directly and
    asserting on ``ensuredMessage.userSummary``. No DB or cache is involved — the
    method is a pure reader of the passed-in metadata dict, so no fixture is required.
    """

    async def test_emptyMetadata_userSummaryStaysNone(self) -> None:
        """No ``memoryRefinement`` section -> ``userSummary`` stays at its ``None`` default.

        ``metadata.get("memoryRefinement", {})`` resolves to an empty dict, so
        no thread entry is found and the assignment is skipped.
        """
        ensuredMessage = _makeEnsuredMessage()
        assert ensuredMessage.userSummary is None

        ensuredMessage.applyUserMetadata(cast(UserMetadataDict, {}))

        assert ensuredMessage.userSummary is None

    async def test_summaryForCurrentThread_isAttached(self) -> None:
        """A ``memoryRefinement[str(threadId)].summary`` is assigned to ``userSummary``.

        The message's ``threadId`` is ``DEFAULT_THREAD_ID`` (0), matching the
        ``"0"`` key in the metadata, so the summary is attached verbatim.
        """
        ensuredMessage = _makeEnsuredMessage()  # threadId = DEFAULT_THREAD_ID (0)
        metadata = cast(
            UserMetadataDict,
            {
                "memoryRefinement": {
                    "0": {
                        "summary": "Likes chess and Python",
                        "lastProcessedMessageId": "1",
                        "lastProcessedMessageDate": "2026-05-05T12:00:00+00:00",
                    }
                }
            },
        )

        ensuredMessage.applyUserMetadata(metadata)

        assert ensuredMessage.userSummary == "Likes chess and Python"

    async def test_summaryForDifferentThread_userSummaryStaysNone(self) -> None:
        """A summary under a sibling thread is ignored (thread isolation).

        The message's ``threadId`` is ``5`` but the metadata only carries a
        summary for thread ``0``; ``userSummary`` must stay ``None`` rather than
        fall back to another thread's summary.
        """
        ensuredMessage = _makeEnsuredMessage()
        ensuredMessage.threadId = 5
        metadata = cast(
            UserMetadataDict,
            {
                "memoryRefinement": {
                    "0": {
                        "summary": "bio text",
                        "lastProcessedMessageId": "1",
                        "lastProcessedMessageDate": "2026-05-05T12:00:00+00:00",
                    }
                }
            },
        )

        ensuredMessage.applyUserMetadata(metadata)

        assert ensuredMessage.userSummary is None

    async def test_emptySummary_userSummaryStaysNone(self) -> None:
        """An empty-string ``summary`` is treated as absent (truthiness filter).

        ``applyUserMetadata`` guards the assignment with ``if summary:``, so a
        falsy summary (empty string) leaves ``userSummary`` at its ``None``
        default.
        """
        ensuredMessage = _makeEnsuredMessage()
        metadata = cast(
            UserMetadataDict,
            {
                "memoryRefinement": {
                    "0": {
                        "summary": "",
                        "lastProcessedMessageId": "1",
                        "lastProcessedMessageDate": "2026-05-05T12:00:00+00:00",
                    }
                }
            },
        )

        ensuredMessage.applyUserMetadata(metadata)

        assert ensuredMessage.userSummary is None
