"""Light unit tests for lib.stt.abstract (AbstractSTTProvider interface).

Covers (per ``docs/design/lib-stt-v1.md`` §8):
- ``AbstractSTTProvider`` cannot be instantiated directly (abstract members
  present → ``TypeError``).
- A minimal concrete stub implementing all three abstract members CAN be
  instantiated, and its ``supportedInputFormats`` returns the supplied tuple.
- The stub's async ``transcribe`` / ``aclose`` are awaitable and return the
  expected types.
"""

import inspect
from collections.abc import Sequence
from typing import Tuple

import pytest

from lib.stt import audio as audioMod
from lib.stt.abstract import AbstractSTTProvider
from lib.stt.exceptions import NoAudioTrackError
from lib.stt.models import (
    AudioFormatSpec,
    ExtractedAudio,
    STTAudioContainerType,
    STTErrorCode,
    STTResultStatus,
    TranscriptionResult,
)

_FORMATS: Tuple[AudioFormatSpec, ...] = (
    AudioFormatSpec(
        container=STTAudioContainerType.OGG_OPUS,
        minChannels=1,
        maxChannels=2,
        minSampleRate=8000,
        maxSampleRate=48000,
    ),
    AudioFormatSpec(
        container=STTAudioContainerType.MP3,
        minChannels=1,
        maxChannels=2,
        minSampleRate=8000,
        maxSampleRate=48000,
    ),
    AudioFormatSpec(
        container=STTAudioContainerType.WAV,
        minChannels=1,
        maxChannels=1,
        minSampleRate=8000,
        maxSampleRate=16000,
    ),
)


class _StubProvider(AbstractSTTProvider):
    """Minimal concrete provider implementing all abstract members.

    Attributes:
        closed: Whether ``aclose`` was called.
    """

    def __init__(self, formats: Tuple[AudioFormatSpec, ...]) -> None:
        """Initialize the stub with its accepted input formats.

        Args:
            formats: The ordered accepted input formats to expose.
        """
        super().__init__()
        self._formats = formats
        self.closed = False

    def supportedInputFormats(self) -> Sequence[AudioFormatSpec]:
        """Return the ordered accepted input formats supplied at construction.

        Returns:
            Sequence[AudioFormatSpec]: The accepted input formats.
        """
        return self._formats

    async def _transcribe(self, audio: ExtractedAudio) -> TranscriptionResult:
        """Return a NO_SPEECH result for any input (stub never errors).

        Args:
            audio: The extracted audio to transcribe (ignored by the stub).

        Returns:
            TranscriptionResult: A NO_SPEECH result with no segments.
        """
        return TranscriptionResult(status=STTResultStatus.NO_SPEECH, segments=())

    async def aclose(self) -> None:
        """Mark the provider as closed.

        Returns:
            None
        """
        self.closed = True


# ============================================================================
# Abstract enforcement
# ============================================================================


def testAbstractProviderCannotBeInstantiated() -> None:
    """AbstractSTTProvider raises TypeError when constructed directly.

    Returns:
        None
    """
    with pytest.raises(TypeError):
        AbstractSTTProvider()  # type: ignore[abstract]


def testAbstractMembersAreAbstract() -> None:
    """supportedInputFormats, _transcribe, and aclose are all abstract.

    Returns:
        None
    """
    abstractNames = AbstractSTTProvider.__abstractmethods__
    assert {"supportedInputFormats", "_transcribe", "aclose"} <= abstractNames


# ============================================================================
# Concrete stub
# ============================================================================


def testConcreteStubCanBeInstantiated() -> None:
    """A stub implementing all abstract members constructs without error.

    Returns:
        None
    """
    provider = _StubProvider(_FORMATS)
    assert isinstance(provider, AbstractSTTProvider)


def testConcreteStubSupportedInputFormats() -> None:
    """The stub's supportedInputFormats returns the tuple supplied at construction.

    Returns:
        None
    """
    provider = _StubProvider(_FORMATS)
    assert provider.supportedInputFormats() == _FORMATS
    assert provider.supportedInputFormats()[0].container is STTAudioContainerType.OGG_OPUS


def testTranscribeAndAcloseAreCoroutines() -> None:
    """transcribe and aclose are declared async (coroutine functions).

    Returns:
        None
    """
    assert inspect.iscoroutinefunction(_StubProvider.transcribe)
    assert inspect.iscoroutinefunction(AbstractSTTProvider.transcribe)
    assert inspect.iscoroutinefunction(_StubProvider.aclose)
    assert inspect.iscoroutinefunction(AbstractSTTProvider.aclose)


async def testStubTranscribeReturnsTranscriptionResult() -> None:
    """The stub transcribe returns a TranscriptionResult (never raises).

    Returns:
        None
    """
    provider = _StubProvider(_FORMATS)
    audio = ExtractedAudio(
        container=STTAudioContainerType.OGG_OPUS,
        channels=1,
        sampleRate=16000,
        data=b"\x00",
        durationMs=1000,
    )
    result = await provider.transcribe(audio)
    assert isinstance(result, TranscriptionResult)
    assert result.status is STTResultStatus.NO_SPEECH


async def testStubAcloseReleases() -> None:
    """The stub aclose is awaitable and flips the closed flag.

    Returns:
        None
    """
    provider = _StubProvider(_FORMATS)
    assert provider.closed is False
    await provider.aclose()
    assert provider.closed is True


# ============================================================================
# stt() — never-raise high-level entry (extract + transcribe)
# ============================================================================


async def testSttNeverRaisesOnTypedExtractionFailure(monkeypatch: pytest.MonkeyPatch) -> None:
    """stt() maps a typed extraction failure to an ERROR result, never raising.

    A typed STTExtractionError (here NoAudioTrackError) is caught and its
    errorCode (NO_AUDIO) surfaces on the returned TranscriptionResult; the call
    does not propagate.

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        None
    """

    async def raisingExtract(data: bytes, *, supportedInputFormats: object) -> ExtractedAudio:
        raise NoAudioTrackError("no decodable audio stream")

    monkeypatch.setattr(audioMod, "extractAudio", raisingExtract)
    provider = _StubProvider(_FORMATS)
    result = await provider.stt(b"\x00")
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.NO_AUDIO


async def testSttNeverRaisesOnUnexpectedExtractionException(monkeypatch: pytest.MonkeyPatch) -> None:
    """stt() maps a non-STT exception to PROVIDER_ERROR, never raising.

    Defense-in-depth: an unexpected (non-STTExtractionError) exception from
    extractAudio is logged and mapped to PROVIDER_ERROR rather than escaping.

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        None
    """

    async def explodingExtract(data: bytes, *, supportedInputFormats: object) -> ExtractedAudio:
        raise RuntimeError("unexpected failure inside PyAV")

    monkeypatch.setattr(audioMod, "extractAudio", explodingExtract)
    provider = _StubProvider(_FORMATS)
    result = await provider.stt(b"\x00")
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROVIDER_ERROR


class _RaisingTranscribeProvider(_StubProvider):
    """Stub provider whose ``transcribe`` raises an unexpected exception.

    Used to verify the never-raise boundary in :meth:`stt` covers the
    ``transcribe`` call (not just extraction). Inherits
    ``supportedInputFormats`` / ``aclose`` from :class:`_StubProvider`.
    """

    async def _transcribe(self, audio: ExtractedAudio) -> TranscriptionResult:
        """Raise an unexpected RuntimeError instead of returning a result.

        Args:
            audio: The extracted audio (ignored).

        Returns:
            TranscriptionResult: Never returns; always raises RuntimeError.
        """
        raise RuntimeError("unexpected failure inside provider")


async def testSttDelegatesToTranscribeOnSuccess(monkeypatch: pytest.MonkeyPatch) -> None:
    """stt() delegates to transcribe and returns its result on a successful extraction.

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        None
    """
    fakeAudio = ExtractedAudio(
        container=STTAudioContainerType.OGG_OPUS,
        channels=1,
        sampleRate=16000,
        data=b"\x00",
        durationMs=1000,
    )

    async def okExtract(data: bytes, *, supportedInputFormats: object) -> ExtractedAudio:
        return fakeAudio

    monkeypatch.setattr(audioMod, "extractAudio", okExtract)
    provider = _StubProvider(_FORMATS)
    result = await provider.stt(b"\x00")
    assert result.status is STTResultStatus.NO_SPEECH  # the stub's transcribe


async def testSttNeverRaisesOnTranscribeFailure(monkeypatch: pytest.MonkeyPatch) -> None:
    """stt() maps an unexpected transcribe raise to PROVIDER_ERROR, never raising.

    Regression: ``transcribe`` is invoked INSIDE the never-raise try/except in
    :meth:`AbstractSTTProvider.stt`, so a provider whose ``transcribe`` raises
    an unexpected exception is caught by the defense-in-depth branch (logged +
    mapped to PROVIDER_ERROR) rather than propagating. Pre-fix, the
    ``transcribe`` call sat AFTER the try/except and an unexpected raise
    escaped :meth:`stt`, breaking the never-raise contract.

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        None
    """
    fakeAudio = ExtractedAudio(
        container=STTAudioContainerType.OGG_OPUS,
        channels=1,
        sampleRate=16000,
        data=b"\x00",
        durationMs=1000,
    )

    async def okExtract(data: bytes, *, supportedInputFormats: object) -> ExtractedAudio:
        return fakeAudio

    monkeypatch.setattr(audioMod, "extractAudio", okExtract)
    provider = _RaisingTranscribeProvider(_FORMATS)
    result = await provider.stt(b"\x00")
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROVIDER_ERROR
