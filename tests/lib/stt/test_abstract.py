"""Light unit tests for lib.stt.abstract (AbstractSTTProvider interface).

Covers (per ``docs/plans/lib-stt-v1.md`` §8):
- ``AbstractSTTProvider`` cannot be instantiated directly (abstract members
  present → ``TypeError``).
- A minimal concrete stub implementing all three abstract members CAN be
  instantiated, and its ``supportedInputFormats`` returns the supplied tuple.
- The stub's async ``transcribe`` / ``aclose`` are awaitable and return the
  expected types.
"""

import inspect
from typing import Tuple

import pytest

from lib.stt.abstract import AbstractSTTProvider
from lib.stt.models import (
    AudioFormatSpec,
    ExtractedAudio,
    STTAudioContainerType,
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
        self._formats = formats
        self.closed = False

    @property
    def supportedInputFormats(self) -> Tuple[AudioFormatSpec, ...]:
        """Return the ordered accepted input formats supplied at construction.

        Returns:
            Tuple[AudioFormatSpec, ...]: The accepted input formats.
        """
        return self._formats

    async def transcribe(self, audio: ExtractedAudio) -> TranscriptionResult:
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
    """supportedInputFormats, transcribe, and aclose are all abstract.

    Returns:
        None
    """
    abstractNames = AbstractSTTProvider.__abstractmethods__
    assert {"supportedInputFormats", "transcribe", "aclose"} <= abstractNames


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
    assert provider.supportedInputFormats == _FORMATS
    assert provider.supportedInputFormats[0].container is STTAudioContainerType.OGG_OPUS


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
