"""Tests for STTService.transcribeMedia pipeline.

Covers the failure-half and success-half of the stateless transcription
pipeline: admission early returns (STT_DISABLED, SOURCE_TOO_LARGE), provider
ERROR mapping (PROVIDER_ERROR, PROTOCOL_ERROR, NO_AUDIO), never-raise
boundary (provider raises, service exception), FINAL/NO_SPEECH happy paths
with formatTranscript verification, formatTranscript-bug never-raise safety
net, and rate-limiter application.

Uses a FakeProvider (implements AbstractSTTProvider) for white-box unit testing.
The service is stateless — no DB, no cache, no gate, no admission timeout.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Generator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from internal.services.stt.service import STTOutcome, STTService
from lib.stt.abstract import AbstractSTTProvider
from lib.stt.models import (
    AudioFormatSpec,
    ExtractedAudio,
    STTAttributionType,
    STTAudioContainerType,
    STTErrorCode,
    STTResultStatus,
    TranscriptionResult,
    TranscriptionSegment,
)

# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------


class FakeProvider(AbstractSTTProvider):
    """Configurable fake STT provider for testing.

    Attributes:
        _result: The TranscriptionResult to return from stt().
        _shouldRaise: Optional exception class to raise instead of returning.
        sttCallCount: Number of times stt() was called.
        lastConsumerId: The ``consumerId`` kwarg from the most recent stt() call.
    """

    def __init__(
        self,
        result: Optional[TranscriptionResult] = None,
        shouldRaise: Optional[BaseException] = None,
    ) -> None:
        """Initialise the fake provider.

        Args:
            result: The TranscriptionResult to return from stt().
                Ignored when shouldRaise is set.
            shouldRaise: Exception to raise from stt().
        """
        super().__init__()
        self._result = result or TranscriptionResult(status=STTResultStatus.ERROR, segments=())
        self._shouldRaise = shouldRaise
        self.sttCallCount: int = 0
        self.lastConsumerId: Optional[str] = None

    def supportedInputFormats(self) -> Sequence[AudioFormatSpec]:
        """Return a single WAV format spec.

        Returns:
            Sequence of AudioFormatSpec with a single WAV entry.
        """
        return [
            AudioFormatSpec(
                container=STTAudioContainerType.WAV,
                minChannels=1,
                maxChannels=2,
                minSampleRate=8000,
                maxSampleRate=48000,
            )
        ]

    async def _transcribe(self, audio: ExtractedAudio) -> TranscriptionResult:
        """Return the configured result or raise.

        Args:
            audio: The extracted audio data (unused by fake).

        Returns:
            The configured TranscriptionResult.

        Raises:
            Exception: If shouldRaise was configured.
        """
        if self._shouldRaise is not None:
            raise self._shouldRaise
        return self._result

    async def stt(self, data: bytes, *, consumerId: Optional[str] = None) -> TranscriptionResult:
        """Override base stt() to bypass extractAudio and count calls.

        Args:
            data: The source audio bytes.
            consumerId: Optional consumer identifier passed through from the caller.

        Returns:
            The configured TranscriptionResult.

        Raises:
            Exception: If shouldRaise was configured.
        """
        self.sttCallCount += 1
        self.lastConsumerId = consumerId
        if self._shouldRaise is not None:
            raise self._shouldRaise
        return self._result

    async def aclose(self) -> None:
        """No-op close."""
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def resetSttServiceSingleton() -> Generator[None, None, None]:
    """Reset STTService singleton between tests to prevent state leakage.

    Yields:
        None: Fixture runs before and after each test.
    """
    STTService._instance = None

    yield

    STTService._instance = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _buildService(
    provider: Optional[FakeProvider] = None,
    maxSourceBytes: int = 1024,
    maxConcurrency: int = 2,
    chatLimiterQueue: Optional[str] = None,
    globalLimiterQueue: Optional[str] = None,
) -> STTService:
    """Build and wire an STTService for testing.

    Sets private fields directly (white-box unit-test approach) to avoid
    needing a full ConfigManager.

    Args:
        provider: Fake provider to inject.
        maxSourceBytes: Source byte cap.
        maxConcurrency: Semaphore concurrency limit.
        chatLimiterQueue: Per-chat rate-limiter queue name.
        globalLimiterQueue: Global rate-limiter queue name.

    Returns:
        Configured STTService instance.
    """
    svc = STTService.getInstance()
    svc._provider = provider or FakeProvider()
    svc._enabled = True
    svc._initialized = True
    svc._semaphore = asyncio.Semaphore(maxConcurrency)
    svc._maxSourceBytes = maxSourceBytes
    svc._chatLimiterQueue = chatLimiterQueue
    svc._globalLimiterQueue = globalLimiterQueue
    return svc


# ---------------------------------------------------------------------------
# Test: Provider ERROR → PROVIDER_ERROR
# ---------------------------------------------------------------------------


class TestProviderErrorMapsToFailed:
    """Provider returns ERROR+PROVIDER_ERROR → FAILED+PROVIDER_ERROR."""

    async def test_providerError(self) -> None:
        """Provider ERROR+PROVIDER_ERROR → FAILED+PROVIDER_ERROR."""
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.ERROR, segments=(), errorCode=STTErrorCode.PROVIDER_ERROR)
        )
        svc = _buildService(provider=provider)

        outcome: STTOutcome = await svc.transcribeMedia(b"\x00" * 64, chatId=100)

        assert outcome.success is False
        assert outcome.errorCode == STTErrorCode.PROVIDER_ERROR
        assert provider.sttCallCount == 1


# ---------------------------------------------------------------------------
# Test: Provider ERROR → PROTOCOL_ERROR
# ---------------------------------------------------------------------------


class TestProtocolErrorMapsToFailed:
    """Provider returns ERROR+PROTOCOL_ERROR → FAILED+PROTOCOL_ERROR."""

    async def test_protocolError(self) -> None:
        """Provider ERROR+PROTOCOL_ERROR → FAILED+PROTOCOL_ERROR."""
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.ERROR, segments=(), errorCode=STTErrorCode.PROTOCOL_ERROR)
        )
        svc = _buildService(provider=provider)

        outcome: STTOutcome = await svc.transcribeMedia(b"\x00" * 64, chatId=100)

        assert outcome.success is False
        assert outcome.errorCode == STTErrorCode.PROTOCOL_ERROR


# ---------------------------------------------------------------------------
# Test: Provider ERROR → NO_AUDIO
# ---------------------------------------------------------------------------


class TestNoAudioMapsToFailed:
    """Provider returns ERROR+NO_AUDIO → FAILED+NO_AUDIO."""

    async def test_noAudio(self) -> None:
        """Provider ERROR+NO_AUDIO → FAILED+NO_AUDIO."""
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.ERROR, segments=(), errorCode=STTErrorCode.NO_AUDIO)
        )
        svc = _buildService(provider=provider)

        outcome: STTOutcome = await svc.transcribeMedia(b"\x00" * 64, chatId=100)

        assert outcome.success is False
        assert outcome.errorCode == STTErrorCode.NO_AUDIO


# ---------------------------------------------------------------------------
# Test: Never-raise on unexpected provider exception
# ---------------------------------------------------------------------------


class TestNeverRaisesOnUnexpectedProviderException:
    """Provider.stt() raising is caught; returns FAILED+PROVIDER_ERROR."""

    async def test_providerRaisesRuntimeError(self) -> None:
        """Provider raises RuntimeError → does not propagate; FAILED+PROVIDER_ERROR."""
        provider = FakeProvider(shouldRaise=RuntimeError("provider boom"))
        svc = _buildService(provider=provider)

        outcome: STTOutcome = await svc.transcribeMedia(b"\x00" * 64, chatId=100)

        assert outcome.success is False
        assert outcome.errorCode == STTErrorCode.PROVIDER_ERROR


# ---------------------------------------------------------------------------
# Test: FINAL transcription produces DONE + formatted transcript
# ---------------------------------------------------------------------------


class TestFinalTranscriptionProducesDone:
    """Provider FINAL with segments → DONE + formatted transcript."""

    async def test_finalWithXmlCharsNotTruncated(self) -> None:
        """FINAL with XML-escape chars and long text → DONE + thin formatTranscript output.

        The thin formatter does NOT truncate, NOT XML-escape, and does NOT add
        a header. Special chars appear as-is, the timestamp prefix is present,
        and the output is NOT truncated (length exceeds any old cap).
        """
        segments = (
            TranscriptionSegment(text="hello <world> & friends", startMs=0, endMs=1000, words=()),
            TranscriptionSegment(text="x" * 500, startMs=1000, endMs=2000, words=()),
        )
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.FINAL, segments=segments),
        )
        svc = _buildService(provider=provider)

        outcome: STTOutcome = await svc.transcribeMedia(b"\x00" * 64, chatId=100)

        assert outcome.success is True
        assert outcome.description is not None
        # Special chars are NOT escaped in the thin formatter.
        assert "<world>" in outcome.description
        assert "&" in outcome.description
        # Timestamp ranges are present (0ms..1000ms and 1000ms..2000ms).
        assert "[00:00:00..00:00:01]" in outcome.description
        assert "[00:00:01..00:00:02]" in outcome.description
        # Output is NOT truncated (well over 200 chars).
        assert len(outcome.description) > 200


# ---------------------------------------------------------------------------
# Test: NO_SPEECH → DONE with empty description
# ---------------------------------------------------------------------------


class TestNoSpeechYieldsDoneEmpty:
    """Provider NO_SPEECH (empty segments) → DONE with description == \"\"."""

    async def test_noSpeech(self) -> None:
        """NO_SPEECH → DONE with empty-string description."""
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.NO_SPEECH, segments=()),
        )
        svc = _buildService(provider=provider)

        outcome: STTOutcome = await svc.transcribeMedia(b"\x00" * 64, chatId=100)

        assert outcome.success is True
        assert outcome.description == ""


# ---------------------------------------------------------------------------
# Test: FINAL under cap → DONE + timestamped text, no header
# ---------------------------------------------------------------------------


class TestFinalUnderCapYieldsDone:
    """FINAL with short segments → DONE + timestamped text, no untrusted header."""

    async def test_finalUnderCap(self) -> None:
        """FINAL with short segment → DONE + timestamp prefix + text, no header."""
        segments = (TranscriptionSegment(text="short text", startMs=0, endMs=1000, words=()),)
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.FINAL, segments=segments),
        )
        svc = _buildService(provider=provider)

        outcome: STTOutcome = await svc.transcribeMedia(b"\x00" * 64, chatId=100)

        assert outcome.success is True
        assert outcome.description is not None
        assert "[00:00:00..00:00:01]" in outcome.description
        assert "short text" in outcome.description
        # The untrusted header was dropped in the thin formatter.
        assert "[Untrusted media transcript" not in outcome.description

    async def testSingleChannelAttributionRendersWithoutPrefix(self) -> None:
        """FINAL with one channel attribution propagates its range-only line.

        Returns:
            None: The assertion verifies service-level formatter propagation.
        """
        segments = (TranscriptionSegment(text="speaker", startMs=125, endMs=1500, words=(), attributionTag="left"),)
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.FINAL, segments=segments),
        )
        svc = _buildService(provider=provider)

        outcome: STTOutcome = await svc.transcribeMedia(b"\x00" * 64, chatId=100)

        assert outcome.success is True
        assert outcome.description == "[00:00:00.125..00:00:01.500] speaker"

    async def testSpeakerTaggedSegmentPropagatesFormattedDescription(self) -> None:
        """FINAL speaker attribution propagates into STTOutcome.description.

        Returns:
            None: The assertion verifies service-level speaker formatting.
        """
        segments = (TranscriptionSegment(text="speaker", startMs=125, endMs=1500, words=(), attributionTag="1"),)
        provider = FakeProvider(
            result=TranscriptionResult(
                status=STTResultStatus.FINAL,
                segments=segments,
                attributionType=STTAttributionType.SPEAKER,
            ),
        )
        svc = _buildService(provider=provider)

        outcome: STTOutcome = await svc.transcribeMedia(b"\x00" * 64, chatId=100)

        assert outcome.success is True
        assert outcome.description == "[00:00:00.125..00:00:01.500] speaker"


# ---------------------------------------------------------------------------
# Test: formatTranscript bug → never-raise safety net
# ---------------------------------------------------------------------------


class TestFormatTranscriptBugNeverRaises:
    """formatTranscript raising inside _mapOutcome is caught → FAILED+PROVIDER_ERROR.

    Exercises the never-raise boundary in transcribeMedia. If formatTranscript
    ever raises due to a formatter bug, the service returns FAILED instead of
    propagating.
    """

    async def test_formatTranscriptBugTerminalizesRow(self) -> None:
        """formatTranscript raises RuntimeError → FAILED+PROVIDER_ERROR, does not propagate."""
        provider = FakeProvider(
            result=TranscriptionResult(
                status=STTResultStatus.FINAL,
                segments=(TranscriptionSegment(text="hi", startMs=0, endMs=1, words=()),),
            ),
        )
        svc = _buildService(provider=provider)

        with patch("internal.services.stt.service.formatTranscript", side_effect=RuntimeError("fmt boom")):
            outcome: STTOutcome = await svc.transcribeMedia(b"\x00" * 64, chatId=100)

        assert outcome.success is False
        assert outcome.errorCode == STTErrorCode.PROVIDER_ERROR


# ---------------------------------------------------------------------------
# Test: Admission early returns (STT_DISABLED / SOURCE_TOO_LARGE)
# ---------------------------------------------------------------------------


class TestAdmissionEarlyReturns:
    """Admission gates in transcribeMedia return FAILED without calling the provider."""

    async def test_sourceTooLargeReturnsEarly(self) -> None:
        """``len(data) > maxSourceBytes`` → FAILED+SOURCE_TOO_LARGE, provider not called."""
        provider = FakeProvider()
        svc = _buildService(provider=provider, maxSourceBytes=1024)

        outcome: STTOutcome = await svc.transcribeMedia(b"\x00" * 2048, chatId=100)

        assert outcome.success is False
        assert outcome.errorCode == STTErrorCode.SOURCE_TOO_LARGE
        assert provider.sttCallCount == 0

    async def test_disabledReturnsEarly(self) -> None:
        """``_enabled=False`` → FAILED+STT_DISABLED, provider not called."""
        provider = FakeProvider()
        svc = _buildService(provider=provider)
        svc._enabled = False

        outcome: STTOutcome = await svc.transcribeMedia(b"\x00" * 64, chatId=100)

        assert outcome.success is False
        assert outcome.errorCode == STTErrorCode.STT_DISABLED
        assert provider.sttCallCount == 0


# ---------------------------------------------------------------------------
# Test: Rate limiters applied during admission
# ---------------------------------------------------------------------------


class TestRateLimitersAppliedDuringAdmission:
    """Rate limiter branches in transcribeMedia execute with correct keys."""

    async def test_rateLimitersApplied(self) -> None:
        """Both chat and global rate limiters are called with correct queue names and keys."""
        provider = FakeProvider(
            result=TranscriptionResult(
                status=STTResultStatus.FINAL,
                segments=(TranscriptionSegment(text="hello", startMs=0, endMs=1000, words=()),),
            ),
        )
        svc = _buildService(
            provider=provider,
            chatLimiterQueue="stt-chat",
            globalLimiterQueue="stt-global",
        )

        mockManager = MagicMock()
        mockManager.applyLimit = AsyncMock()

        with patch("lib.rate_limiter.manager.RateLimiterManager.getInstance", return_value=mockManager):
            outcome: STTOutcome = await svc.transcribeMedia(b"\x00" * 64, chatId=42)

        assert outcome.success is True
        mockManager.applyLimit.assert_any_call("stt-chat", key="42")
        mockManager.applyLimit.assert_any_call("stt-global")


# ---------------------------------------------------------------------------
# Regression: transcribeMedia passes consumerId to provider.stt()
# ---------------------------------------------------------------------------


class TestConsumerIdPlumbedToProvider:
    """Regression: transcribeMedia threads ``chatId`` as ``consumerId``
    (``str(chatId)`` or ``None``) to ``provider.stt()``.

    Without this, the per-consumer STT stats rollup in ``_recordStats``
    receives ``consumerId=None`` for every call — the feature ships dead.
    """

    @pytest.mark.parametrize("chatId,expectedConsumerId", [(42, "42"), (0, "0"), (None, None)])
    async def test_consumerIdPassedThrough(self, chatId: Optional[int], expectedConsumerId: Optional[str]) -> None:
        """transcribeMedia forwards ``str(chatId)`` (or None) as ``consumerId`` to the provider.

        Args:
            chatId: Chat ID passed to transcribeMedia.
            expectedConsumerId: Expected ``consumerId`` received by the provider.
        """
        provider = FakeProvider(
            result=TranscriptionResult(
                status=STTResultStatus.FINAL,
                segments=(TranscriptionSegment(text="hello", startMs=0, endMs=1000, words=()),),
            ),
        )
        svc = _buildService(provider=provider)

        outcome: STTOutcome = await svc.transcribeMedia(b"\x00" * 64, chatId=chatId)

        assert outcome.success is True
        assert provider.lastConsumerId == expectedConsumerId
