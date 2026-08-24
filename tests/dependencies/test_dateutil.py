"""Lock ``python-dateutil`` parsing behaviour our code depends on.

These tests pin the CURRENT behaviour of the pinned ``python-dateutil``
(2.9.0.post0) as observed at the three production call sites:

- ``internal/database/utils.py`` — ``sqlToCustomType`` parses SQL/LLM-emitted
  timestamp strings via ``dateutil.parser.parse`` and then force-applies UTC
  (``FORCE_SQL_TIMEZONE``) when the parsed value has no ``tzinfo``.
- ``internal/database/repositories/webhook_updates.py`` — parses Max webhook
  ``received_at`` markers directly with ``dateutil.parser.parse``.
- ``internal/bot/common/handlers/user_memories.py`` — parses an
  LLM/human-written ``lastProcessedMessageDate`` string directly with
  ``dateutilParser.parse``.

If dateutil changes resolution of naive ``tzinfo``, ambiguous day/month
ordering, human-format parsing, or the exception type raised on garbage on a
version bump, these tests fail loudly so the bump is caught before it ships.

The through-production-code assertions (``sqlToCustomType``) cover the
UTC-forcing wrapper; the direct-lib assertions cover timestamp formats that
only appear at the other two call sites.
"""

import datetime
import importlib.metadata

import dateutil.parser
import pytest

from lib.db.utils import sqlToCustomType

#: Pinned ``python-dateutil`` distribution version these assertions were observed
#: against. A bump that changes parsing output must be re-verified against every
#: pin in this file before shipping.
PINNED_VERSION: str = "2.9.0.post0"


# ---------------------------------------------------------------------------
# 0. Pinned distribution version.
# ---------------------------------------------------------------------------


class TestPinnedVersion:
    """Force a conscious re-verification pass on any ``python-dateutil`` bump.

    The whole point of this suite is that a dependency bump which silently
    changes behaviour fails loudly. A docstring version string can rot without
    a failing test; this assertion compares the ACTUAL installed distribution
    version against :data:`PINNED_VERSION` so a bump fails on a real assertion.
    When it fails, re-verify every other pin in this file against the new
    version before updating the constant.
    """

    def testPinnedVersion(self) -> None:
        """The installed ``python-dateutil`` distribution matches :data:`PINNED_VERSION`.

        Args:
            None (self).

        Returns:
            None. Asserts the installed distribution version string.
        """
        assert importlib.metadata.version("python-dateutil") == PINNED_VERSION


# ---------------------------------------------------------------------------
# Direct ``dateutil.parser.parse`` behaviour
# ---------------------------------------------------------------------------


class TestDateutilParseResolution:
    """Pin ``dateutil.parser.parse`` output for the timestamp formats our code feeds it.

    Covers:
    - ISO timestamps with and without explicit timezone.
    - Bare calendar dates.
    - Human/LLM-written date phrases (``"Jan 2 2024"``, ``"02 Jan 2024 3pm"``).
    - The current resolution of ambiguous day-first vs month-first numeric dates.
    - The exception type raised on unparseable input (ValueError subclass).
    """

    def testIsoWithTimezonePreservesTzinfo(self) -> None:
        """ISO string with a ``+00:00`` offset keeps a non-None tzinfo at offset 0.

        ``internal/database/repositories/webhook_updates.py`` stamps
        ``received_at`` via ``dbUtils.getCurrentTimestamp()`` =
        ``datetime.now(timezone.utc)`` then ``.isoformat()``, which always emits
        ``+00:00``; the marker is re-parsed at ``webhook_updates.py:95`` to
        order buffered rows. This is the ONLY offset form production
        round-trips, so a bump that silently dropped ``tzinfo`` (or shifted the
        offset) would mis-order those rows.

        Args:
            None (self).

        Returns:
            None. Asserts tzinfo presence and a zero offset.
        """
        parsed = dateutil.parser.parse("2024-06-01T12:00:00+00:00")

        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == datetime.timedelta(0)

    def testIsoNaiveHasNoTzinfoAtParseLayer(self) -> None:
        """ISO string without an offset parses to a naive datetime (``tzinfo is None``).

        This is the precondition for the UTC-forcing branch in
        ``sqlToCustomType`` (asserted separately in
        :class:`TestSqlToCustomTypeUtcForcing`).

        Args:
            None (self).

        Returns:
            None. Asserts ``tzinfo is None``.
        """
        parsed = dateutil.parser.parse("2024-06-01T12:00:00")

        assert parsed.tzinfo is None

    def testBareDateParsesToCorrectYearMonthDay(self) -> None:
        """A bare ``YYYY-MM-DD`` date yields the exact year/month/day at midnight.

        Args:
            None (self).

        Returns:
            None. Asserts component equality and a midnight time-of-day.
        """
        parsed = dateutil.parser.parse("2024-01-02")

        assert (parsed.year, parsed.month, parsed.day) == (2024, 1, 2)
        assert (parsed.hour, parsed.minute, parsed.second) == (0, 0, 0)

    @pytest.mark.parametrize(
        "inputStr,expectedYear,expectedMonth,expectedDay,expectedHour,expectedUtcoffset",
        [
            ("Jan 2 2024", 2024, 1, 2, 0, None),
            ("02 Jan 2024 3pm", 2024, 1, 2, 15, None),
            ("March 15, 2025 8:30", 2025, 3, 15, 8, None),
            ("2024-06-01T12:00:00Z", 2024, 6, 1, 12, datetime.timedelta(0)),
        ],
        ids=["monthNameDayYear", "dayMonthNameAmPm", "monthNameCommaTime", "isoZulu"],
    )
    def testHumanOrLlmFormatParsesExpectedComponents(
        self,
        inputStr: str,
        expectedYear: int,
        expectedMonth: int,
        expectedDay: int,
        expectedHour: int,
        expectedUtcoffset: "datetime.timedelta | None",
    ) -> None:
        """Human/LLM-written phrases parse to the expected date+hour+tzinfo components.

        ``internal/bot/common/handlers/user_memories.py`` feeds an
        ``lastProcessedMessageDate`` string of unpredictable human shape
        straight into ``dateutilParser.parse``; a bump that grew stricter and
        raised on these formats would silently fall back to "refine from
        scratch" (the except branch there), losing refinement progress.

        The ``expectedUtcoffset`` column additionally locks the naive-vs-aware
        split: the three human phrases are naive (``utcoffset() is None``),
        while the ``Z`` (Zulu) suffix produces an aware UTC datetime
        (``utcoffset() == timedelta(0)``). The Zulu path matters because
        ``sqlToCustomType`` only force-applies UTC when the parsed value is
        naive — an aware value passes through untouched.

        Args:
            inputStr: The timestamp string to parse.
            expectedYear: Expected calendar year of the parsed datetime.
            expectedMonth: Expected calendar month (1-12).
            expectedDay: Expected calendar day-of-month.
            expectedHour: Expected hour-of-day (24h).
            expectedUtcoffset: Expected ``utcoffset()`` result — ``None`` for
                naive datetimes, ``timedelta(0)`` for a Zulu/UTC-aware value.

        Returns:
            None. Asserts component equality and the offset.
        """
        parsed = dateutil.parser.parse(inputStr)

        assert parsed.year == expectedYear
        assert parsed.month == expectedMonth
        assert parsed.day == expectedDay
        assert parsed.hour == expectedHour
        assert parsed.utcoffset() == expectedUtcoffset

    def testAmbiguousNumericDateResolvesMonthFirst(self) -> None:
        """``"01/02/2024"`` resolves to January 2 (month-first), the current default.

        ``dateutil`` defaults to ``dayfirst=False``, so an ambiguous
        ``MM/DD``-or-``DD/MM`` numeric date is read month-first. This pins the
        CURRENT resolution of 2.9.0.post0: a future default flip would change
        which messages memory-refinements considers "already processed", so it
        must be caught.

        NOTE: this asserts what the pinned version *does*, not what it
        *should*. The value 1 is the month (January), the value 2 is the day.

        Args:
            None (self).

        Returns:
            None. Asserts ``(month, day) == (1, 2)``.
        """
        parsed = dateutil.parser.parse("01/02/2024")

        assert (parsed.month, parsed.day) == (1, 2)

    def testImpossibleMonthFallsBackToDayFirst(self) -> None:
        """``"13/02/2024"`` resolves to February 13, because 13 cannot be a month.

        This documents dateutil's value-range fallback: when the first numeric
        group exceeds 12 it is reinterpreted as the day. Paired with
        ``testAmbiguousNumericDateResolvesMonthFirst`` this locks the full
        disambiguation rule used at 2.9.0.post0.

        NOTE: this documents dateutil's full disambiguation rule; it is NOT a
        production call-site contract — no call site feeds an impossible-month
        string. Kept as an intentional companion to the ambiguous-date test so
        the complete rule is visible at a glance.

        Args:
            None (self).

        Returns:
            None. Asserts ``(month, day) == (2, 13)``.
        """
        parsed = dateutil.parser.parse("13/02/2024")

        assert (parsed.month, parsed.day) == (2, 13)

    def testGarbageInputRaisesValueError(self) -> None:
        """Unparseable input raises a ``ValueError`` subclass (``ParserError``).

        ``internal/bot/common/handlers/user_memories.py:1225`` wraps
        ``dateutilParser.parse`` in ``except (ValueError, OverflowError,
        TypeError)`` and falls back to "refine from scratch" on failure. That
        contract holds ONLY because dateutil raises a ``ValueError`` subclass
        (``ParserError``) on garbage. If a future version raised a
        non-``ValueError`` exception on unparseable input, the except-tuple
        would miss it and refinement would crash with an unhandled exception.
        This test locks the except-tuple contract by asserting the actual
        exception is a ``ValueError``.

        Args:
            None (self).

        Returns:
            None. Asserts via ``pytest.raises(ValueError)``.
        """
        with pytest.raises(ValueError):
            dateutil.parser.parse("not a date")


# ---------------------------------------------------------------------------
# Through-production-code UTC forcing (``sqlToCustomType``)
# ---------------------------------------------------------------------------


class TestSqlToCustomTypeUtcForcing:
    """Pin the UTC-forcing side-effect of ``sqlToCustomType`` for datetime strings.

    ``internal/database/utils.py`` documents that a datetime parsed from a SQL
    value with no timezone is force-stamped with ``FORCE_SQL_TIMEZONE``
    (``datetime.timezone.utc``). These tests go through that wrapper so a
    dateutil bump that, say, started injecting a default ``tzinfo`` would no
    longer trigger the forcing branch and would silently change every stored
    naive timestamp's timezone semantics.
    """

    def testNaiveIsoStringIsForcedToUtc(self) -> None:
        """A naive ISO string returns a datetime whose tzinfo is exactly UTC.

        The parse layer yields ``tzinfo is None`` (see
        ``testIsoNaiveHasNoTzinfoAtParseLayer``); the wrapper must then apply
        ``datetime.timezone.utc``.

        Args:
            None (self).

        Returns:
            None. Asserts success flag, datetime type, and exact UTC tzinfo.
        """
        success, value = sqlToCustomType("2024-06-01T12:00:00", datetime.datetime)

        assert success is True
        assert isinstance(value, datetime.datetime)
        assert value.tzinfo is not None
        assert value.tzinfo == datetime.timezone.utc
        assert value.utcoffset() == datetime.timedelta(0)

    def testTimezonedIsoStringKeepsItsOffset(self) -> None:
        """A timezoned ISO string keeps its original offset; UTC is NOT force-overwritten.

        The forcing branch only runs when ``tzinfo is None``, so a value that
        already carries an offset must pass through with that offset intact.

        Args:
            None (self).

        Returns:
            None. Asserts success flag, datetime type, and preserved offset.
        """
        success, value = sqlToCustomType("2024-06-01T12:00:00+03:00", datetime.datetime)

        assert success is True
        assert isinstance(value, datetime.datetime)
        assert value.utcoffset() == datetime.timedelta(hours=3)
