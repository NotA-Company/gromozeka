"""Tests for the STT transcript formatter."""

import pytest

from internal.services.stt.formatter import formatTranscript
from lib.stt.models import STTAttributionType, STTResultStatus, TranscriptionResult, TranscriptionSegment


class TestFormatTranscript:
    """Exact output coverage for tagged and untagged transcript segments."""

    def testSingleChannelAttributionRendersTimestampRangeOnly(self) -> None:
        """A sole channel attribution tag is suppressed before the timestamp.

        Returns:
            None: The assertion verifies exact tagged transcript output.
        """
        result = TranscriptionResult(
            status=STTResultStatus.FINAL,
            segments=(TranscriptionSegment(text="speaker", startMs=125, endMs=1500, words=(), attributionTag="left"),),
        )

        formattedTranscript = formatTranscript(result)

        assert formattedTranscript == "[00:00:00.125..00:00:01.500] speaker"

    @pytest.mark.parametrize("attributionTag", [None, ""])
    def test_untaggedSegmentRendersTimestampRangeOnly(self, attributionTag: str | None) -> None:
        """Missing or empty attribution tags render the range-only line shape.

        Args:
            attributionTag: Missing or empty per-segment attribution tag.

        Returns:
            None: The assertion verifies exact untagged transcript output.
        """
        result = TranscriptionResult(
            status=STTResultStatus.FINAL,
            segments=(
                TranscriptionSegment(text="speaker", startMs=0, endMs=1000, words=(), attributionTag=attributionTag),
            ),
        )

        formattedTranscript = formatTranscript(result)

        assert formattedTranscript == "[00:00:00..00:00:01] speaker"

    def test_zeroDurationSegmentPreservesSingleTimestampFormatting(self) -> None:
        """Equal timestamps preserve the formatter's single-timestamp form.

        Returns:
            None: The assertion verifies existing zero-duration formatting.
        """
        result = TranscriptionResult(
            status=STTResultStatus.FINAL,
            segments=(TranscriptionSegment(text="speaker", startMs=125, endMs=125, words=()),),
        )

        formattedTranscript = formatTranscript(result)

        assert formattedTranscript == "[00:00:00.125] speaker"

    def testSpeakerTagRendersForSingleSpeaker(self) -> None:
        """A sole non-empty speaker tag renders before the timestamp.

        Returns:
            None: The assertion verifies exact speaker-attributed output.
        """
        result = TranscriptionResult(
            status=STTResultStatus.FINAL,
            segments=(TranscriptionSegment(text="hello", startMs=0, endMs=1000, words=(), attributionTag="1"),),
            attributionType=STTAttributionType.SPEAKER,
        )

        formattedTranscript = formatTranscript(result)

        assert formattedTranscript == "[00:00:00..00:00:01] hello"

    def testSpeakerTagsRenderOnTheirRespectiveSegments(self) -> None:
        """Different speaker tags render on their own timestamped lines.

        Returns:
            None: The assertion verifies segment-specific speaker attribution.
        """
        result = TranscriptionResult(
            status=STTResultStatus.FINAL,
            segments=(
                TranscriptionSegment(text="first", startMs=0, endMs=1000, words=(), attributionTag="1"),
                TranscriptionSegment(text="second", startMs=1000, endMs=2000, words=(), attributionTag="2"),
            ),
            attributionType=STTAttributionType.SPEAKER,
        )

        formattedTranscript = formatTranscript(result)

        assert formattedTranscript == "[Speaker#1] [00:00:00..00:00:01] first\n[Speaker#2] [00:00:01..00:00:02] second"

    def testMultipleChannelTagsRetainChannelPrefixes(self) -> None:
        """Multiple distinct ordinary channels retain their existing prefixes.

        Returns:
            None: The assertion verifies unchanged multi-channel output.
        """
        result = TranscriptionResult(
            status=STTResultStatus.FINAL,
            segments=(
                TranscriptionSegment(text="left", startMs=0, endMs=1000, words=(), attributionTag="left"),
                TranscriptionSegment(text="right", startMs=1000, endMs=2000, words=(), attributionTag="right"),
            ),
            attributionType=STTAttributionType.CHANNEL,
        )

        formattedTranscript = formatTranscript(result)

        assert formattedTranscript == "[Ch#left] [00:00:00..00:00:01] left\n[Ch#right] [00:00:01..00:00:02] right"

    @pytest.mark.parametrize(
        ("attributionType", "expectedPrefix"),
        [(STTAttributionType.SPEAKER, ""), (STTAttributionType.CHANNEL, "")],
    )
    def testAttributionTypeDeterminesGenericTagFormatting(
        self, attributionType: STTAttributionType, expectedPrefix: str
    ) -> None:
        """The result role determines how the same generic tag renders.

        Args:
            attributionType: Result-level role assigned to the generic tag.
            expectedPrefix: Attribution prefix expected for that role.

        Returns:
            None: The assertion verifies role-based attribution formatting.
        """
        result = TranscriptionResult(
            status=STTResultStatus.FINAL,
            segments=(TranscriptionSegment(text="speaker", startMs=0, endMs=1000, words=(), attributionTag="7"),),
            attributionType=attributionType,
        )

        formattedTranscript = formatTranscript(result)

        assert formattedTranscript == f"{expectedPrefix}[00:00:00..00:00:01] speaker"

    def testMissingAttributionTagDoesNotRenderPrefix(self) -> None:
        """A missing unified attribution tag renders no prefix.

        Returns:
            None: The assertion verifies range-only output without attribution.
        """
        result = TranscriptionResult(
            status=STTResultStatus.FINAL,
            segments=(TranscriptionSegment(text="untagged", startMs=0, endMs=1000, words=()),),
            attributionType=STTAttributionType.CHANNEL,
        )

        formattedTranscript = formatTranscript(result)

        assert formattedTranscript == "[00:00:00..00:00:01] untagged"
