"""Tests for :meth:`EnsuredMessage.formatForLLM` ``userSummary`` handling.

Covers behaviour area (D) of the memory-refinements test plan:

* When ``userSummary`` is ``None`` (the default), the JSON output must omit the
  ``userSummary`` key entirely — both as a parsed-key absence and as a raw
  substring absence, so a pre-feature ``EnsuredMessage`` and a post-feature one
  with no summary produce byte-identical JSON (no trailing comma, no empty
  field).
* When ``userSummary`` is set, the key must appear with the exact value.

``formatForLLM`` is async and accepts a ``db`` argument, but with no media
attached (``mediaId is None`` and empty ``mediaList``) its
``updateMediaContent`` early-returns without ever touching ``db``. The real
``testDatabase`` fixture is passed for full type-correctness; it is never read.
"""

import datetime
import json

from internal.bot.models import (
    ChatType,
    EnsuredMessage,
    LLMMessageFormat,
    MessageRecipient,
    MessageSender,
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
