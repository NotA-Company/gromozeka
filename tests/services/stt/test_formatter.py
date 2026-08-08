"""Tests for the STT transcript formatter."""

import pytest

from internal.services.stt.formatter import formatTranscript
from lib.stt.models import STTResultStatus, TranscriptionResult, TranscriptionSegment


class TestFormatTranscript:
    """Exact output coverage for tagged and untagged transcript segments."""

    def test_taggedSegmentRendersChannelPrefixAndTimestampRange(self) -> None:
        """A non-empty channel tag renders before the timestamp range.

        Returns:
            None: The assertion verifies exact tagged transcript output.
        """
        result = TranscriptionResult(
            status=STTResultStatus.FINAL,
            segments=(TranscriptionSegment(text="speaker", startMs=125, endMs=1500, words=(), channelTag="left"),),
        )

        formattedTranscript = formatTranscript(result)

        assert formattedTranscript == "[00:00:00.125..00:00:01.500] speaker"

    @pytest.mark.parametrize("channelTag", [None, ""])
    def test_untaggedSegmentRendersTimestampRangeOnly(self, channelTag: str | None) -> None:
        """Missing or empty channel tags render the range-only line shape.

        Args:
            channelTag: Missing or empty per-segment channel tag.

        Returns:
            None: The assertion verifies exact untagged transcript output.
        """
        result = TranscriptionResult(
            status=STTResultStatus.FINAL,
            segments=(TranscriptionSegment(text="speaker", startMs=0, endMs=1000, words=(), channelTag=channelTag),),
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
            segments=(TranscriptionSegment(text="speaker", startMs=125, endMs=125, words=(), channelTag="left"),),
        )

        formattedTranscript = formatTranscript(result)

        assert formattedTranscript == "[00:00:00.125] speaker"
