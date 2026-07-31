"""Unit tests for lib.stt.manager (STTManager).

Covers (per ``docs/plans/lib-stt-v1.md`` §8 — authoritative):
- The manager holds the single selected provider and exposes it read-only
  (``provider`` property); selection is the act of construction (the integration
  layer resolves + injects the one provider per the §1 dependency firewall).
- ``transcribe`` delegates to the selected provider, passing the
  :class:`~lib.stt.models.ExtractedAudio` through unchanged and returning the
  provider's :class:`~lib.stt.models.TranscriptionResult` verbatim (FINAL /
  NO_SPEECH / ERROR). The manager does NOT extract audio or format the transcript.
- ``aclose`` closes the held provider's resources.
- ``aclose`` is best-effort / robust: a provider close failure is logged and NOT
  propagated, so graceful shutdown always completes (parent §11.3).
- ``aclose`` is safe to call more than once (idempotent via the provider's own
  idempotent close; the manager never raises on a second call).
- Defensive type guard: constructing with a non-``AbstractSTTProvider`` raises
  ``TypeError``.

All tests use a STUB provider that records calls and returns canned results — NO
real network, NO real Yandex provider.
"""

import inspect
from typing import List, Tuple

import pytest

import lib.stt as stt
from lib.stt.abstract import AbstractSTTProvider
from lib.stt.manager import STTManager
from lib.stt.models import (
    AudioFormatSpec,
    ExtractedAudio,
    STTAudioContainerType,
    STTErrorCode,
    STTResultStatus,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionWord,
)

_FORMATS: Tuple[AudioFormatSpec, ...] = (
    AudioFormatSpec(
        container=STTAudioContainerType.OGG_OPUS,
        minChannels=1,
        maxChannels=2,
        minSampleRate=8000,
        maxSampleRate=48000,
    ),
)


def _makeAudio() -> ExtractedAudio:
    """Build a minimal ExtractedAudio fixture for delegation tests.

    Returns:
        ExtractedAudio: A small mono OGG_OPUS fixture.
    """
    return ExtractedAudio(
        container=STTAudioContainerType.OGG_OPUS,
        channels=1,
        sampleRate=16000,
        data=b"\x00\x01\x02\x03",
        durationMs=1000,
    )


def _finalResult() -> TranscriptionResult:
    """Build a FINAL TranscriptionResult with one segment.

    Returns:
        TranscriptionResult: A FINAL result carrying a single recognized segment.
    """
    return TranscriptionResult(
        status=STTResultStatus.FINAL,
        segments=(
            TranscriptionSegment(
                text="hello world",
                startMs=0,
                endMs=1200,
                words=(
                    TranscriptionWord(text="hello", startMs=0, endMs=500),
                    TranscriptionWord(text="world", startMs=500, endMs=1200),
                ),
            ),
        ),
    )


class _RecordingProvider(AbstractSTTProvider):
    """Stub provider that records every call and returns a canned result.

    Used to verify STTManager delegates transcribe to the held provider and closes
    it on ``aclose``. Records the exact ``ExtractedAudio`` passed to transcribe and a
    count of ``aclose`` calls.

    Attributes:
        transcribeCalls: List of ``ExtractedAudio`` objects passed to ``transcribe``,
            in call order.
        closeCallCount: Number of times ``aclose`` was called.
        supportedInputFormatsValue: The ordered formats to expose.
        transcribeResult: The canned ``TranscriptionResult`` returned by transcribe.
    """

    def __init__(
        self,
        transcribeResult: TranscriptionResult,
        formats: Tuple[AudioFormatSpec, ...] = _FORMATS,
    ) -> None:
        """Initialize the recording stub with a canned transcribe result.

        Args:
            transcribeResult: The ``TranscriptionResult`` this stub returns from
                ``transcribe`` (FINAL / NO_SPEECH / ERROR — caller controls it).
            formats: The ordered accepted input formats to expose.

        Returns:
            None
        """
        self.transcribeCalls: List[ExtractedAudio] = []
        self.closeCallCount: int = 0
        self.supportedInputFormatsValue: Tuple[AudioFormatSpec, ...] = formats
        self.transcribeResult: TranscriptionResult = transcribeResult

    @property
    def supportedInputFormats(self) -> Tuple[AudioFormatSpec, ...]:
        """Return the ordered accepted input formats supplied at construction.

        Returns:
            Tuple[AudioFormatSpec, ...]: The accepted input formats.
        """
        return self.supportedInputFormatsValue

    async def transcribe(self, audio: ExtractedAudio) -> TranscriptionResult:
        """Record the audio and return the canned result.

        Args:
            audio: The extracted audio to transcribe (recorded verbatim).

        Returns:
            TranscriptionResult: The canned result supplied at construction.
        """
        self.transcribeCalls.append(audio)
        return self.transcribeResult

    async def aclose(self) -> None:
        """Increment the close-call counter.

        Returns:
            None
        """
        self.closeCallCount += 1


class _RaisingCloseProvider(AbstractSTTProvider):
    """Stub provider whose ``aclose`` always raises, to test best-effort shutdown.

    Used to verify STTManager.aclose does NOT propagate a provider close failure
    (parent §11.3 — graceful shutdown must complete). Its ``transcribe`` returns a
    NO_SPEECH result; only the close path is under test.

    Attributes:
        closed: Whether ``aclose`` was attempted (set True even though it raises).
    """

    def __init__(self) -> None:
        """Initialize the raising-close stub.

        Returns:
            None
        """
        self.closed: bool = False

    @property
    def supportedInputFormats(self) -> Tuple[AudioFormatSpec, ...]:
        """Return the ordered accepted input formats.

        Returns:
            Tuple[AudioFormatSpec, ...]: The accepted input formats.
        """
        return _FORMATS

    async def transcribe(self, audio: ExtractedAudio) -> TranscriptionResult:
        """Return a NO_SPEECH result (transcribe is not under test for this stub).

        Args:
            audio: The extracted audio (ignored by this stub).

        Returns:
            TranscriptionResult: A NO_SPEECH result with no segments.
        """
        return TranscriptionResult(status=STTResultStatus.NO_SPEECH, segments=())

    async def aclose(self) -> None:
        """Mark attempted-close then raise (simulating a provider close failure).

        Raises:
            RuntimeError: Always, to exercise the manager's best-effort close.

        Returns:
            None
        """
        self.closed = True
        raise RuntimeError("simulated provider close failure")


# ============================================================================
# Construction + provider selection
# ============================================================================


def testManagerHoldsInjectedProvider() -> None:
    """The manager exposes the single injected provider via the read-only property.

    §8: the manager "selects the single configured provider" — selection is the act of
    construction (the integration layer resolves + injects the one provider per the §1
    firewall; the manager holds it).

    Returns:
        None
    """
    provider = _RecordingProvider(_finalResult())
    manager = STTManager(provider)
    assert manager.provider is provider
    assert isinstance(manager.provider, AbstractSTTProvider)


def testManagerIsNotAProviderRegistry() -> None:
    """STTManager exposes no registry/getProvider discovery surface (§8 "instead of a registry").

    Confirms the manager deliberately diverges from LLMManager: it holds ONE provider
    and does not expose a multi-provider registry, model→provider lookup, or
    getProvider/listProviders API.

    Returns:
        None
    """
    provider = _RecordingProvider(_finalResult())
    manager = STTManager(provider)
    for absent in ("providers", "getProvider", "listProviders", "modelRegistry", "registerProvider"):
        assert not hasattr(manager, absent), f"STTManager unexpectedly exposes registry member {absent!r}"


def testTranscribeAndAcloseAreCoroutines() -> None:
    """STTManager.transcribe and aclose are declared async (coroutine functions).

    Returns:
        None
    """
    assert inspect.iscoroutinefunction(STTManager.transcribe)
    assert inspect.iscoroutinefunction(STTManager.aclose)


def testConstructorRejectsNonProvider() -> None:
    """Constructing with a non-AbstractSTTProvider raises TypeError (defensive guard).

    Args:
        None

    Returns:
        None
    """
    with pytest.raises(TypeError):
        STTManager("not-a-provider")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        STTManager(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        STTManager(object())  # type: ignore[arg-type]


# ============================================================================
# transcribe delegation
# ============================================================================


async def testTranscribeDelegatesToSelectedProvider() -> None:
    """transcribe forwards to the held provider's transcribe and returns its result verbatim.

    The manager itself does NO audio extraction or formatting (§5 owns extraction, §6
    owns formatting): it passes the ExtractedAudio through unchanged and returns the
    provider's TranscriptionResult as-is.

    Returns:
        None
    """
    expected = _finalResult()
    provider = _RecordingProvider(expected)
    manager = STTManager(provider)
    audio = _makeAudio()

    result = await manager.transcribe(audio)

    assert result is expected
    assert result.status is STTResultStatus.FINAL
    assert len(result.segments) == 1
    assert result.segments[0].text == "hello world"
    # The provider saw exactly one call, with the audio passed through unchanged.
    assert len(provider.transcribeCalls) == 1
    assert provider.transcribeCalls[0] is audio
    assert provider.transcribeCalls[0].data == b"\x00\x01\x02\x03"
    assert provider.transcribeCalls[0].container is STTAudioContainerType.OGG_OPUS


async def testTranscribeReturnsProviderErrorVerbatim() -> None:
    """transcribe returns the provider's ERROR result unchanged (provider never raises, §4/§8).

    The manager does not remap, swallow, or retry provider failures — it trusts the
    provider's never-raise contract and forwards the ERROR TranscriptionResult.

    Returns:
        None
    """
    errorResult = TranscriptionResult(
        status=STTResultStatus.ERROR,
        segments=(),
        errorCode=STTErrorCode.PROVIDER_ERROR,
    )
    provider = _RecordingProvider(errorResult)
    manager = STTManager(provider)

    result = await manager.transcribe(_makeAudio())

    assert result is errorResult
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROVIDER_ERROR


async def testTranscribeReturnsNoSpeechVerbatim() -> None:
    """transcribe returns the provider's NO_SPEECH result unchanged.

    Returns:
        None
    """
    noSpeechResult = TranscriptionResult(status=STTResultStatus.NO_SPEECH, segments=())
    provider = _RecordingProvider(noSpeechResult)
    manager = STTManager(provider)

    result = await manager.transcribe(_makeAudio())

    assert result is noSpeechResult
    assert result.status is STTResultStatus.NO_SPEECH


async def testTranscribeDelegatesPerCall() -> None:
    """Each transcribe call is a separate delegation (no caching/skip-once at the manager).

    Returns:
        None
    """
    provider = _RecordingProvider(_finalResult())
    manager = STTManager(provider)

    await manager.transcribe(_makeAudio())
    await manager.transcribe(_makeAudio())
    await manager.transcribe(_makeAudio())

    assert len(provider.transcribeCalls) == 3


# ============================================================================
# aclose — closes the provider, best-effort, idempotent
# ============================================================================


async def testAcloseClosesProvider() -> None:
    """aclose delegates to the held provider's aclose.

    Returns:
        None
    """
    provider = _RecordingProvider(_finalResult())
    manager = STTManager(provider)
    assert provider.closeCallCount == 0

    await manager.aclose()

    assert provider.closeCallCount == 1


async def testAcloseDoesNotPropagateProviderCloseFailure() -> None:
    """aclose is best-effort: a provider close failure is suppressed (parent §11.3).

    §8 / parent §11.3: graceful shutdown must drain and close without being blocked by
    a provider close failure. The manager logs and swallows the exception rather than
    propagating it. (§8 specifies a single provider, so "the others still get closed"
    is vacuous here — the load-bearing property is that the manager's aclose does not
    raise.)

    Returns:
        None
    """
    provider = _RaisingCloseProvider()
    manager = STTManager(provider)

    # Must NOT raise, despite the provider's aclose raising RuntimeError.
    await manager.aclose()
    assert provider.closed is True


async def testAcloseIsIdempotent() -> None:
    """Calling aclose more than once is safe (never raises on the second call).

    §8 does not require the manager to guard a closed flag; idempotency comes from the
    provider's own idempotent close. The manager must not raise on repeated aclose.

    Returns:
        None
    """
    provider = _RecordingProvider(_finalResult())
    manager = STTManager(provider)

    await manager.aclose()
    await manager.aclose()
    await manager.aclose()

    # The provider's aclose was called each time (no guard short-circuit); none raised.
    assert provider.closeCallCount == 3


async def testAcloseIdempotentEvenWhenProviderCloseRaises() -> None:
    """Repeated best-effort aclose never raises even when the provider close always fails.

    Returns:
        None
    """
    provider = _RaisingCloseProvider()
    manager = STTManager(provider)

    await manager.aclose()
    await manager.aclose()
    assert provider.closed is True


async def testTranscribeAfterAcloseStillDelegates() -> None:
    """After aclose the manager still forwards transcribe to the provider (no closed-guard).

    The manager does not short-circuit transcribe after aclose; it delegates every time
    and lets the provider decide (the real provider maps a closed-client RuntimeError to
    PROVIDER_ERROR per its never-raise contract).

    Returns:
        None
    """
    provider = _RecordingProvider(_finalResult())
    manager = STTManager(provider)
    await manager.aclose()

    result = await manager.transcribe(_makeAudio())

    assert result.status is STTResultStatus.FINAL
    assert len(provider.transcribeCalls) == 1


# ============================================================================
# Top-level public surface wiring
# ============================================================================


def testManagerAndProviderExportedFromLibStt() -> None:
    """lib.stt re-exports STTManager and YandexSpeechKitProvider on its public surface (§3).

    Returns:
        None
    """
    assert "STTManager" in stt.__all__
    assert "YandexSpeechKitProvider" in stt.__all__
    assert stt.STTManager is STTManager
    assert hasattr(stt, "YandexSpeechKitProvider")
