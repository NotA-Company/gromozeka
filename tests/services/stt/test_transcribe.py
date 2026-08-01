"""Tests for STTService.transcribeMedia pipeline (Phase 3a + 3b).

Covers the full failure-half and success-half of the transcription pipeline:
cache hit, gate-off normalization, pre-admission declared-size rejection,
download failures (None / raises / oversized), provider ERROR mapping
(PROVIDER_ERROR, PROTOCOL_ERROR, NO_AUDIO), never-raise boundary (provider
raises, service exception), admission timeout (with row terminalization),
claim transitions (NEW→PENDING, orphan PENDING→PENDING→FAILED, DONE→PENDING),
FINAL/NO_SPEECH happy paths with formatTranscript verification, verified
terminal persist, persist-exhaustion reclaim, and rate-limiter application.

Uses a FakeProvider (implements AbstractSTTProvider) and a configurable
async loader for white-box unit testing against a real in-memory database
(via the testDatabase fixture).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import AsyncGenerator, Generator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from internal.database import Database
from internal.database.models import MediaStatus
from internal.models.shared_enums import MessageType
from internal.services.stt.service import STTMediaRequest, STTService
from lib.stt.abstract import AbstractSTTProvider
from lib.stt.formatter import formatTranscript
from lib.stt.models import (
    AudioFormatSpec,
    ExtractedAudio,
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
        self._result = result or TranscriptionResult(status=STTResultStatus.ERROR, segments=())
        self._shouldRaise = shouldRaise
        self.sttCallCount: int = 0

    def supportedInputFormats(self) -> Sequence[AudioFormatSpec]:
        """Return a single WAV format spec.

        Returns:
            Sequence of AudioFormatSpec with a single WAV entry.
        """
        from lib.stt.models import STTAudioContainerType

        return [
            AudioFormatSpec(
                container=STTAudioContainerType.WAV,
                minChannels=1,
                maxChannels=2,
                minSampleRate=8000,
                maxSampleRate=48000,
            )
        ]

    async def transcribe(self, audio: ExtractedAudio) -> TranscriptionResult:
        """Return the configured result or raise.

        Args:
            audio: The extracted audio data.

        Returns:
            The configured TranscriptionResult.

        Raises:
            Exception: If shouldRaise was configured.
        """
        if self._shouldRaise is not None:
            raise self._shouldRaise
        return self._result

    async def stt(self, data: bytes) -> TranscriptionResult:
        """Override base stt() to bypass extractAudio and count calls.

        Args:
            data: The source audio bytes.

        Returns:
            The configured TranscriptionResult.

        Raises:
            Exception: If shouldRaise was configured.
        """
        self.sttCallCount += 1
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


@pytest.fixture
async def sttDb(testDatabase: Database) -> AsyncGenerator[Database, None]:
    """Provide the testDatabase as 'sttDb' for explicit naming.

    Args:
        testDatabase: The shared in-memory Database fixture.

    Yields:
        Database: The test database with all migrations applied.
    """
    yield testDatabase


def _buildService(
    sttDb: Database,
    provider: Optional[FakeProvider] = None,
    maxSourceBytes: int = 1024,
    admissionTimeoutSeconds: int = 5,
    maxConcurrency: int = 2,
    chatLimiterQueue: Optional[str] = None,
    globalLimiterQueue: Optional[str] = None,
    maxTranscriptChars: int = 48000,
) -> STTService:
    """Build and wire an STTService for testing with real DB.

    Sets private fields directly (white-box unit-test approach) to avoid
    needing a full ConfigManager.

    Args:
        sttDb: The test database.
        provider: Fake provider to inject.
        maxSourceBytes: Source byte cap.
        admissionTimeoutSeconds: Admission timeout in seconds.
        maxConcurrency: Semaphore concurrency limit.
        chatLimiterQueue: Per-chat rate-limiter queue name.
        globalLimiterQueue: Global rate-limiter queue name.
        maxTranscriptChars: Maximum persisted transcript length.

    Returns:
        Configured STTService instance.
    """
    svc = STTService.getInstance()
    svc._provider = provider or FakeProvider()
    svc._database = sttDb
    svc._enabled = True
    svc._initialized = True
    svc._semaphore = asyncio.Semaphore(maxConcurrency)
    svc._maxSourceBytes = maxSourceBytes
    svc._maxDurationSeconds = 600
    svc._maxTranscriptChars = maxTranscriptChars
    svc._admissionTimeoutSeconds = admissionTimeoutSeconds
    svc._chatLimiterQueue = chatLimiterQueue
    svc._globalLimiterQueue = globalLimiterQueue
    return svc


async def _nullLoader(maxBytes: int) -> Optional[bytes]:
    """Loader that returns None (size unknown).

    Args:
        maxBytes: Ignored.

    Returns:
        None.
    """
    return None


async def _oversizedLoader(maxBytes: int) -> Optional[bytes]:
    """Loader that returns bytes exceeding the requested max.

    Args:
        maxBytes: Ignored (returns fixed oversized payload).

    Returns:
        Bytes larger than any reasonable maxSourceBytes.
    """
    return b"\x00" * 2048


async def _raisingLoader(maxBytes: int) -> Optional[bytes]:
    """Loader that always raises.

    Args:
        maxBytes: Ignored.

    Raises:
        RuntimeError: Always.
    """
    raise RuntimeError("download failed")


async def _smallLoader(maxBytes: int) -> Optional[bytes]:
    """Loader that returns a small valid payload.

    Args:
        maxBytes: Ignored.

    Returns:
        Small bytes payload.
    """
    return b"\x00" * 64


def _makeRequest(
    mediaId: str = "media-001",
    fileId: str = "file-001",
    mediaType: MessageType = MessageType.VOICE,
    chatId: int = 100,
    declaredSize: Optional[int] = None,
    loader=None,
) -> STTMediaRequest:
    """Build a test STTMediaRequest.

    Args:
        mediaId: The file_unique_id.
        fileId: The platform file_id.
        mediaType: The media type.
        chatId: The chat ID.
        declaredSize: Declared file size.
        loader: The async download callable.

    Returns:
        STTMediaRequest for testing.
    """
    return STTMediaRequest(
        mediaId=mediaId,
        fileId=fileId,
        mediaType=mediaType,
        chatId=chatId,
        declaredSize=declaredSize,
        loader=loader or _smallLoader,
    )


async def _seedRow(
    db: Database,
    mediaId: str = "media-001",
    fileId: str = "file-001",
    status: MediaStatus = MediaStatus.NEW,
    description: Optional[str] = None,
) -> None:
    """Insert a media attachment row via the repository.

    Args:
        db: The test database.
        mediaId: The file_unique_id.
        fileId: The platform file_id.
        status: The initial status.
        description: Optional description text.
    """
    await db.mediaAttachments.addMediaAttachment(
        fileUniqueId=mediaId,
        fileId=fileId,
        mediaType=MessageType.VOICE,
        status=status,
        description=description,
    )


# ---------------------------------------------------------------------------
# Test 1: Cache hit
# ---------------------------------------------------------------------------


class TestCacheHitReturnsCachedTranscriptNoWork:
    """DONE+description row returns immediately without provider/loader calls."""

    async def test_cacheHit(self, sttDb: Database) -> None:
        """Cache hit returns DONE with the stored description."""
        await _seedRow(sttDb, mediaId="c1", status=MediaStatus.DONE, description="hello world")
        provider = FakeProvider()
        svc = _buildService(sttDb, provider=provider)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="c1", loader=_smallLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.DONE
        assert outcome.description == "hello world"
        assert provider.sttCallCount == 0


# ---------------------------------------------------------------------------
# Test 1b: Cache hit returned even when gate is off
# ---------------------------------------------------------------------------


class TestCacheHitReturnedEvenWhenGateOff:
    """DONE+description row is returned as-is when gate is off (step 2 fires before step 3).

    Regression guard: step 2 (cache-hit on DONE+description) fires BEFORE step 3
    (gate-off normalize), so a previously-transcribed row is returned as-is even
    when the gate is now off — no re-transcription, no provider/loader calls.
    """

    async def test_cacheHitReturnedEvenWhenGateOff(self, sttDb: Database) -> None:
        """Previously transcribed DONE row is returned unchanged even when gateEnabled=False."""
        await _seedRow(sttDb, mediaId="ch1", status=MediaStatus.DONE, description="cached transcript")
        provider = FakeProvider()
        svc = _buildService(sttDb, provider=provider)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="ch1", loader=_smallLoader), gateEnabled=False)

        assert outcome.status == MediaStatus.DONE
        assert outcome.description == "cached transcript"
        assert provider.sttCallCount == 0


# ---------------------------------------------------------------------------
# Test 2: Gate off + no description
# ---------------------------------------------------------------------------


class TestGateOffNoDescriptionNormalizesToDoneNull:
    """Gate off with no description normalizes to DONE/null."""

    async def test_gateOffNew(self, sttDb: Database) -> None:
        """Gate off with NEW row → DONE/null, no provider call."""
        await _seedRow(sttDb, mediaId="g1", status=MediaStatus.NEW)
        provider = FakeProvider()
        svc = _buildService(sttDb, provider=provider)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="g1", loader=_smallLoader), gateEnabled=False)

        assert outcome.status == MediaStatus.DONE
        assert outcome.description is None
        assert provider.sttCallCount == 0
        row = await sttDb.mediaAttachments.getMediaAttachment("g1")
        assert row is not None
        assert row["status"] == MediaStatus.DONE

    async def test_gateOffPending(self, sttDb: Database) -> None:
        """Gate off with PENDING row → DONE/null."""
        await _seedRow(sttDb, mediaId="g2", status=MediaStatus.PENDING)
        provider = FakeProvider()
        svc = _buildService(sttDb, provider=provider)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="g2", loader=_smallLoader), gateEnabled=False)

        assert outcome.status == MediaStatus.DONE
        assert outcome.description is None
        assert provider.sttCallCount == 0


# ---------------------------------------------------------------------------
# Test 3: Pre-admission declared-size rejection
# ---------------------------------------------------------------------------


class TestSourceTooLargePreAdmissionFromDeclaredSize:
    """declaredSize > max-source-bytes short-circuits before download."""

    async def test_declaredSizeRejectsBeforeDownload(self, sttDb: Database) -> None:
        """declaredSize > maxSourceBytes → FAILED+SOURCE_TOO_LARGE, loader not called."""
        await _seedRow(sttDb, mediaId="ds1")
        loaderCalled = False

        async def trackLoader(maxBytes: int) -> Optional[bytes]:
            nonlocal loaderCalled
            loaderCalled = True
            return b"\x00"

        svc = _buildService(sttDb, maxSourceBytes=100)

        outcome = await svc.transcribeMedia(
            _makeRequest(mediaId="ds1", declaredSize=200, loader=trackLoader), gateEnabled=True
        )

        assert outcome.status == MediaStatus.FAILED
        assert outcome.errorCode == STTErrorCode.SOURCE_TOO_LARGE
        assert loaderCalled is False


# ---------------------------------------------------------------------------
# Test 4: Loader returns None → SOURCE_SIZE_UNKNOWN
# ---------------------------------------------------------------------------


class TestSourceSizeUnknownWhenLoaderReturnsNone:
    """Loader returning None maps to SOURCE_SIZE_UNKNOWN."""

    async def test_loaderReturnsNone(self, sttDb: Database) -> None:
        """Loader returns None → FAILED+SOURCE_SIZE_UNKNOWN; row → FAILED."""
        await _seedRow(sttDb, mediaId="su1")
        svc = _buildService(sttDb)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="su1", loader=_nullLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.FAILED
        assert outcome.errorCode == STTErrorCode.SOURCE_SIZE_UNKNOWN
        row = await sttDb.mediaAttachments.getMediaAttachment("su1")
        assert row is not None
        assert row["status"] == MediaStatus.FAILED
        assert row["description"] is None


# ---------------------------------------------------------------------------
# Test 5: Loader raises → DOWNLOAD_ERROR
# ---------------------------------------------------------------------------


class TestDownloadErrorWhenLoaderRaises:
    """Loader raising maps to DOWNLOAD_ERROR."""

    async def test_loaderRaises(self, sttDb: Database) -> None:
        """Loader raises → FAILED+DOWNLOAD_ERROR; row → FAILED."""
        await _seedRow(sttDb, mediaId="de1")
        svc = _buildService(sttDb)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="de1", loader=_raisingLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.FAILED
        assert outcome.errorCode == STTErrorCode.DOWNLOAD_ERROR
        row = await sttDb.mediaAttachments.getMediaAttachment("de1")
        assert row is not None
        assert row["status"] == MediaStatus.FAILED


# ---------------------------------------------------------------------------
# Test 6: Loader returns oversized → SOURCE_TOO_LARGE
# ---------------------------------------------------------------------------


class TestSourceTooLargeOnRecheckWhenLoaderOversized:
    """Loader returning bytes > maxSourceBytes maps to SOURCE_TOO_LARGE."""

    async def test_loaderOversized(self, sttDb: Database) -> None:
        """Loader returns 2048 bytes, max is 1024 → FAILED+SOURCE_TOO_LARGE."""
        await _seedRow(sttDb, mediaId="os1")
        svc = _buildService(sttDb, maxSourceBytes=1024)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="os1", loader=_oversizedLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.FAILED
        assert outcome.errorCode == STTErrorCode.SOURCE_TOO_LARGE
        row = await sttDb.mediaAttachments.getMediaAttachment("os1")
        assert row is not None
        assert row["status"] == MediaStatus.FAILED


# ---------------------------------------------------------------------------
# Test 7: Provider ERROR → PROVIDER_ERROR
# ---------------------------------------------------------------------------


class TestProviderErrorMapsToFailed:
    """Provider returns ERROR+PROVIDER_ERROR → FAILED+PROVIDER_ERROR."""

    async def test_providerError(self, sttDb: Database) -> None:
        """Provider ERROR+PROVIDER_ERROR → FAILED+PROVIDER_ERROR."""
        await _seedRow(sttDb, mediaId="pe1")
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.ERROR, segments=(), errorCode=STTErrorCode.PROVIDER_ERROR)
        )
        svc = _buildService(sttDb, provider=provider)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="pe1", loader=_smallLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.FAILED
        assert outcome.errorCode == STTErrorCode.PROVIDER_ERROR
        assert provider.sttCallCount == 1


# ---------------------------------------------------------------------------
# Test 8: Provider ERROR → PROTOCOL_ERROR
# ---------------------------------------------------------------------------


class TestProtocolErrorMapsToFailed:
    """Provider returns ERROR+PROTOCOL_ERROR → FAILED+PROTOCOL_ERROR."""

    async def test_protocolError(self, sttDb: Database) -> None:
        """Provider ERROR+PROTOCOL_ERROR → FAILED+PROTOCOL_ERROR."""
        await _seedRow(sttDb, mediaId="pr1")
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.ERROR, segments=(), errorCode=STTErrorCode.PROTOCOL_ERROR)
        )
        svc = _buildService(sttDb, provider=provider)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="pr1", loader=_smallLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.FAILED
        assert outcome.errorCode == STTErrorCode.PROTOCOL_ERROR


# ---------------------------------------------------------------------------
# Test 9: Provider ERROR → NO_AUDIO
# ---------------------------------------------------------------------------


class TestNoAudioMapsToFailed:
    """Provider returns ERROR+NO_AUDIO → FAILED+NO_AUDIO."""

    async def test_noAudio(self, sttDb: Database) -> None:
        """Provider ERROR+NO_AUDIO → FAILED+NO_AUDIO."""
        await _seedRow(sttDb, mediaId="na1")
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.ERROR, segments=(), errorCode=STTErrorCode.NO_AUDIO)
        )
        svc = _buildService(sttDb, provider=provider)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="na1", loader=_smallLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.FAILED
        assert outcome.errorCode == STTErrorCode.NO_AUDIO


# ---------------------------------------------------------------------------
# Test 10: Never-raise on unexpected provider exception
# ---------------------------------------------------------------------------


class TestNeverRaisesOnUnexpectedProviderException:
    """Provider.stt() raising is caught; returns FAILED+PROVIDER_ERROR."""

    async def test_providerRaisesRuntimeError(self, sttDb: Database) -> None:
        """Provider raises RuntimeError → does not propagate; FAILED+PROVIDER_ERROR."""
        await _seedRow(sttDb, mediaId="re1")
        provider = FakeProvider(shouldRaise=RuntimeError("provider boom"))
        svc = _buildService(sttDb, provider=provider)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="re1", loader=_smallLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.FAILED
        assert outcome.errorCode == STTErrorCode.PROVIDER_ERROR
        row = await sttDb.mediaAttachments.getMediaAttachment("re1")
        assert row is not None
        assert row["status"] == MediaStatus.FAILED


# ---------------------------------------------------------------------------
# Test 11: Never-raise on unexpected service exception
# ---------------------------------------------------------------------------


class TestNeverRaisesOnUnexpectedServiceException:
    """DB layer raising during read is caught; returns FAILED+PROVIDER_ERROR."""

    async def test_dbRaisesDuringRead(self, sttDb: Database) -> None:
        """DB read raises → transcribeMedia does not propagate."""
        svc = _buildService(sttDb)
        realRepo = sttDb.mediaAttachments

        async def raisingGet(mediaId: str, **kwargs: object) -> None:
            raise RuntimeError("DB boom")

        class RaisingRepo:
            async def getMediaAttachment(self, mediaId: str, **kwargs: object) -> None:
                raise RuntimeError("DB boom")

            async def addMediaAttachment(self, **kwargs: object) -> bool:
                return False

            async def setStatusVerified(self, mediaId: str, **kwargs: object) -> None:
                return None

        sttDb.mediaAttachments = RaisingRepo()  # type: ignore[assignment]

        try:
            outcome = await svc.transcribeMedia(_makeRequest(mediaId="x1", loader=_smallLoader), gateEnabled=True)
            assert outcome.status == MediaStatus.FAILED
            assert outcome.errorCode == STTErrorCode.PROVIDER_ERROR
        finally:
            sttDb.mediaAttachments = realRepo  # type: ignore[assignment]


class TestAdmissionTimeoutYieldsFailed:
    """Admission timeout → FAILED+ADMISSION_TIMEOUT."""

    async def test_admissionTimeout(self, sttDb: Database) -> None:
        """Semaphore held by background task → ADMISSION_TIMEOUT."""
        await _seedRow(sttDb, mediaId="at1")
        svc = _buildService(sttDb, maxConcurrency=1, admissionTimeoutSeconds=1)
        assert svc._semaphore is not None

        # Hold the semaphore in a background task.
        held = asyncio.Event()

        async def holdSemaphore() -> None:
            assert svc._semaphore is not None
            await svc._semaphore.acquire()
            held.set()
            # Hold for longer than admission timeout.
            await asyncio.sleep(10)

        task = asyncio.create_task(holdSemaphore())
        try:
            # Wait until the semaphore is held.
            await held.wait()

            outcome = await svc.transcribeMedia(_makeRequest(mediaId="at1", loader=_smallLoader), gateEnabled=True)

            assert outcome.status == MediaStatus.FAILED
            assert outcome.errorCode == STTErrorCode.ADMISSION_TIMEOUT
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


# ---------------------------------------------------------------------------
# Test 13: Claim transitions NEW→PENDING→FAILED
# ---------------------------------------------------------------------------


class TestClaimTransitionsNewToPending:
    """Seeded NEW row transitions NEW→PENDING→FAILED."""

    async def test_newToPendingToFailed(self, sttDb: Database) -> None:
        """NEW row → provider ERROR → row is FAILED."""
        await _seedRow(sttDb, mediaId="cl1", status=MediaStatus.NEW)
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.ERROR, segments=(), errorCode=STTErrorCode.PROVIDER_ERROR)
        )
        svc = _buildService(sttDb, provider=provider)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="cl1", loader=_smallLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.FAILED
        assert outcome.errorCode == STTErrorCode.PROVIDER_ERROR

        row = await sttDb.mediaAttachments.getMediaAttachment("cl1")
        assert row is not None
        assert row["status"] == MediaStatus.FAILED
        assert row["description"] is None


# ---------------------------------------------------------------------------
# Test 14: Orphan reclaim PENDING row
# ---------------------------------------------------------------------------


class TestOrphanReclaimReprocessesPendingRow:
    """Seeded PENDING row (orphan) is reclaimed and processed."""

    async def test_orphanPendingReclaimed(self, sttDb: Database) -> None:
        """PENDING row → reclaimed → provider ERROR → FAILED."""
        await _seedRow(sttDb, mediaId="or1", status=MediaStatus.PENDING)
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.ERROR, segments=(), errorCode=STTErrorCode.PROVIDER_ERROR)
        )
        svc = _buildService(sttDb, provider=provider)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="or1", loader=_smallLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.FAILED
        assert outcome.errorCode == STTErrorCode.PROVIDER_ERROR

        row = await sttDb.mediaAttachments.getMediaAttachment("or1")
        assert row is not None
        assert row["status"] == MediaStatus.FAILED


# ---------------------------------------------------------------------------
# Test 15: FAILED persist is verified
# ---------------------------------------------------------------------------


class TestFailedPersistIsVerified:
    """After a FAILED outcome, row is FAILED+null via fresh read."""

    async def test_persistVerified(self, sttDb: Database) -> None:
        """Row is FAILED+null after transcribeMedia returns FAILED."""
        await _seedRow(sttDb, mediaId="pv1")
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.ERROR, segments=(), errorCode=STTErrorCode.NO_AUDIO)
        )
        svc = _buildService(sttDb, provider=provider)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="pv1", loader=_smallLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.FAILED
        assert outcome.errorCode == STTErrorCode.NO_AUDIO

        # Fresh read to verify persist.
        row = await sttDb.mediaAttachments.getMediaAttachment("pv1")
        assert row is not None
        assert row["status"] == MediaStatus.FAILED
        assert row["description"] is None


# ---------------------------------------------------------------------------
# Test 17 (3b): FINAL transcription persists formatted transcript
# ---------------------------------------------------------------------------


class TestFinalTranscriptionPersistsFormattedTranscript:
    """Provider FINAL with segments → DONE + formatted transcript persisted."""

    async def test_finalWithXmlEscapesAndTruncation(self, sttDb: Database) -> None:
        """FINAL with XML-escape chars and truncation under small cap → DONE + exact formatTranscript output."""
        cap = 200
        segments = (
            TranscriptionSegment(text="hello <world> & friends", startMs=0, endMs=1000, words=()),
            TranscriptionSegment(text="x" * 500, startMs=1000, endMs=2000, words=()),
        )
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.FINAL, segments=segments),
        )
        svc = _buildService(sttDb, provider=provider, maxTranscriptChars=cap)

        await _seedRow(sttDb, mediaId="ft1")
        outcome = await svc.transcribeMedia(_makeRequest(mediaId="ft1", loader=_smallLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.DONE
        assert outcome.description is not None
        # Compute expected independently via formatTranscript.
        expected = formatTranscript(TranscriptionResult(status=STTResultStatus.FINAL, segments=segments), cap)
        assert outcome.description == expected
        assert len(outcome.description) == cap

        row = await sttDb.mediaAttachments.getMediaAttachment("ft1")
        assert row is not None
        assert row["status"] == MediaStatus.DONE
        assert row["description"] == expected


# ---------------------------------------------------------------------------
# Test 18 (3b): NO_SPEECH persists sentinel
# ---------------------------------------------------------------------------


class TestNoSpeechPersistsSentinel:
    """Provider NO_SPEECH (empty segments) → DONE + [No speech detected]."""

    async def test_noSpeech(self, sttDb: Database) -> None:
        """NO_SPEECH → DONE + '[No speech detected]' persisted."""
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.NO_SPEECH, segments=()),
        )
        svc = _buildService(sttDb, provider=provider)

        await _seedRow(sttDb, mediaId="ns1")
        outcome = await svc.transcribeMedia(_makeRequest(mediaId="ns1", loader=_smallLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.DONE
        assert outcome.description == "[No speech detected]"

        row = await sttDb.mediaAttachments.getMediaAttachment("ns1")
        assert row is not None
        assert row["status"] == MediaStatus.DONE
        assert row["description"] == "[No speech detected]"


# ---------------------------------------------------------------------------
# Test 19 (3b): FINAL under cap persists full body
# ---------------------------------------------------------------------------


class TestFinalUnderCapPersistsFullBody:
    """FINAL with segments well under the cap → DONE + full body, no truncation."""

    async def test_finalUnderCap(self, sttDb: Database) -> None:
        """FINAL with short segments → DONE + header + full body, no truncation marker."""
        segments = (TranscriptionSegment(text="short text", startMs=0, endMs=1000, words=()),)
        provider = FakeProvider(
            result=TranscriptionResult(status=STTResultStatus.FINAL, segments=segments),
        )
        svc = _buildService(sttDb, provider=provider)

        await _seedRow(sttDb, mediaId="fu1")
        outcome = await svc.transcribeMedia(_makeRequest(mediaId="fu1", loader=_smallLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.DONE
        assert outcome.description is not None
        assert "[Untrusted media transcript" in outcome.description
        assert "short text" in outcome.description
        assert "truncated" not in outcome.description
        assert len(outcome.description) <= svc._maxTranscriptChars

        row = await sttDb.mediaAttachments.getMediaAttachment("fu1")
        assert row is not None
        assert row["status"] == MediaStatus.DONE


# ---------------------------------------------------------------------------
# Test 20 (R5): Admission timeout terminalizes the row
# ---------------------------------------------------------------------------


class TestAdmissionTimeoutPersistsFailedRow:
    """Admission timeout → FAILED + ADMISSION_TIMEOUT + row is FAILED."""

    async def test_admissionTimeoutPersistsRow(self, sttDb: Database) -> None:
        """Semaphore held by background task → ADMISSION_TIMEOUT + row FAILED."""
        await _seedRow(sttDb, mediaId="atp1")
        svc = _buildService(sttDb, maxConcurrency=1, admissionTimeoutSeconds=1)
        assert svc._semaphore is not None

        # Hold the semaphore in a background task.
        held = asyncio.Event()

        async def holdSemaphore() -> None:
            assert svc._semaphore is not None
            await svc._semaphore.acquire()
            held.set()
            # Hold for longer than admission timeout.
            await asyncio.sleep(10)

        task = asyncio.create_task(holdSemaphore())
        try:
            # Wait until the semaphore is held.
            await held.wait()

            outcome = await svc.transcribeMedia(_makeRequest(mediaId="atp1", loader=_smallLoader), gateEnabled=True)

            assert outcome.status == MediaStatus.FAILED
            assert outcome.errorCode == STTErrorCode.ADMISSION_TIMEOUT

            row = await sttDb.mediaAttachments.getMediaAttachment("atp1")
            assert row is not None
            assert row["status"] == MediaStatus.FAILED
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


# ---------------------------------------------------------------------------
# Test 21 (R6): Rate limiters applied during admission
# ---------------------------------------------------------------------------


class TestRateLimitersAppliedDuringAdmission:
    """Rate limiter branches in _admit execute with correct keys."""

    async def test_rateLimitersApplied(self, sttDb: Database) -> None:
        """Both chat and global rate limiters are called with correct queue names and keys."""
        await _seedRow(sttDb, mediaId="rl1")
        provider = FakeProvider(
            result=TranscriptionResult(
                status=STTResultStatus.FINAL,
                segments=(TranscriptionSegment(text="hello", startMs=0, endMs=1000, words=()),),
            ),
        )
        svc = _buildService(
            sttDb,
            provider=provider,
            chatLimiterQueue="stt-chat",
            globalLimiterQueue="stt-global",
        )

        mockManager = MagicMock()
        mockManager.applyLimit = AsyncMock()

        with patch("lib.rate_limiter.manager.RateLimiterManager.getInstance", return_value=mockManager):
            outcome = await svc.transcribeMedia(
                _makeRequest(mediaId="rl1", chatId=42, loader=_smallLoader),
                gateEnabled=True,
            )

        assert outcome.status == MediaStatus.DONE
        mockManager.applyLimit.assert_any_call("stt-chat", key="42")
        mockManager.applyLimit.assert_any_call("stt-global")


# ---------------------------------------------------------------------------
# Test 22 (R7): Persist exhaustion leaves PENDING and is reclaimable
# ---------------------------------------------------------------------------


class TestPersistExhaustionLeavesPendingAndIsReclaimable:
    """Persist exhaustion (CAS never matches) leaves row PENDING; subsequent call reclaims."""

    async def test_persistExhaustionReclaimable(self, sttDb: Database, caplog: pytest.LogCaptureFixture) -> None:
        """setStatusVerified always returns None for terminal targets → PENDING stays, reclaimable."""
        realRepo = sttDb.mediaAttachments

        class FailingPersistRepo:
            """Repo whose setStatusVerified returns None for terminal targets only."""

            async def getMediaAttachment(self, mediaId: str) -> Optional[dict]:
                return await realRepo.getMediaAttachment(mediaId)  # type: ignore[return-value]

            async def addMediaAttachment(self, **kwargs: object) -> bool:
                return await realRepo.addMediaAttachment(**kwargs)  # type: ignore[arg-type]

            async def setStatusVerified(
                self,
                mediaId: str,
                *,
                expected: MediaStatus,
                target: MediaStatus,
                description: Optional[str] = None,
            ) -> Optional[dict]:
                if target == MediaStatus.PENDING:
                    return await realRepo.setStatusVerified(  # type: ignore[arg-type, return-value]
                        mediaId=mediaId, expected=expected, target=target, description=description
                    )
                return None

        await _seedRow(sttDb, mediaId="ex1")
        provider = FakeProvider(
            result=TranscriptionResult(
                status=STTResultStatus.ERROR, segments=(), errorCode=STTErrorCode.PROVIDER_ERROR
            ),
        )
        svc = _buildService(sttDb, provider=provider)
        sttDb.mediaAttachments = FailingPersistRepo()  # type: ignore[assignment]

        try:
            with caplog.at_level(logging.CRITICAL, logger="internal.services.stt.service"):
                outcome = await svc.transcribeMedia(_makeRequest(mediaId="ex1", loader=_smallLoader), gateEnabled=True)

            # (a) Returns FAILED (never raises).
            assert outcome.status == MediaStatus.FAILED
            assert outcome.errorCode == STTErrorCode.PROVIDER_ERROR

            # (b) Row remains PENDING (not terminalized).
            row = await realRepo.getMediaAttachment("ex1")
            assert row is not None
            assert row["status"] == MediaStatus.PENDING

            # (c) CRITICAL exhaustion log emitted.
            assert any("persist exhausted" in r.message for r in caplog.records)
        finally:
            sttDb.mediaAttachments = realRepo  # type: ignore[assignment]

        # (d) Subsequent call with working repo reclaims PENDING row.
        outcome2 = await svc.transcribeMedia(_makeRequest(mediaId="ex1", loader=_smallLoader), gateEnabled=True)
        assert outcome2.status == MediaStatus.FAILED
        assert outcome2.errorCode == STTErrorCode.PROVIDER_ERROR

        row2 = await realRepo.getMediaAttachment("ex1")
        assert row2 is not None
        assert row2["status"] == MediaStatus.FAILED


# ---------------------------------------------------------------------------
# Test 23 (R8): DONE+null reclaimed under gate on
# ---------------------------------------------------------------------------


class TestDoneNullReclaimedUnderGateOn:
    """DONE row with null description is reclaimable when gate is on."""

    async def test_doneNullReclaimed(self, sttDb: Database) -> None:
        """DONE+null + gateEnabled → reclaimed (DONE→PENDING) → provider ERROR → FAILED."""
        await _seedRow(sttDb, mediaId="dr1", status=MediaStatus.DONE, description=None)
        provider = FakeProvider(
            result=TranscriptionResult(
                status=STTResultStatus.ERROR, segments=(), errorCode=STTErrorCode.PROVIDER_ERROR
            ),
        )
        svc = _buildService(sttDb, provider=provider)

        outcome = await svc.transcribeMedia(_makeRequest(mediaId="dr1", loader=_smallLoader), gateEnabled=True)

        assert outcome.status == MediaStatus.FAILED
        assert outcome.errorCode == STTErrorCode.PROVIDER_ERROR

        row = await sttDb.mediaAttachments.getMediaAttachment("dr1")
        assert row is not None
        assert row["status"] == MediaStatus.FAILED


# ---------------------------------------------------------------------------
# Test 24 (R2): formatTranscript bug terminalizes the row to FAILED
# ---------------------------------------------------------------------------


class TestFormatTranscriptBugTerminalizesRow:
    """formatTranscript raising inside _mapOutcome catches and terminalizes to FAILED+PROVIDER_ERROR.

    Exercises the widened ``except Exception`` around ``_mapOutcome`` (Phase 3b
    R2 safety net).  If ``formatTranscript`` ever raises due to a formatter
    bug, the row must terminalize to FAILED instead of being left PENDING with
    silent transcript loss.
    """

    async def test_formatTranscriptBugTerminalizesRow(self, sttDb: Database) -> None:
        """formatTranscript raises RuntimeError → row terminalizes to FAILED, not PENDING."""
        await _seedRow(sttDb, mediaId="fb1")
        provider = FakeProvider(
            result=TranscriptionResult(
                status=STTResultStatus.FINAL,
                segments=(TranscriptionSegment(text="hi", startMs=0, endMs=1, words=()),),
            ),
        )
        svc = _buildService(sttDb, provider=provider)

        with patch("internal.services.stt.service.formatTranscript", side_effect=RuntimeError("fmt boom")):
            outcome = await svc.transcribeMedia(_makeRequest(mediaId="fb1", loader=_smallLoader), gateEnabled=True)

        # (a) Returns FAILED + PROVIDER_ERROR, does not propagate.
        assert outcome.status == MediaStatus.FAILED
        assert outcome.errorCode == STTErrorCode.PROVIDER_ERROR

        # (b) Row is terminalized to FAILED (NOT PENDING — the load-bearing assertion).
        row = await sttDb.mediaAttachments.getMediaAttachment("fb1")
        assert row is not None
        assert row["status"] == MediaStatus.FAILED
