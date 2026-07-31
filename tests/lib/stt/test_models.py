"""Unit tests for lib.stt Phase 1 foundation: models + exceptions.

Covers (per ``docs/plans/lib-stt-v1.md`` §4/§5):
- Enum membership and exact string values, including the wire-fixed
  ``STTAudioContainerType`` labels.
- Frozen/slot record construction and immutability (``setattr`` raises
  ``dataclasses.FrozenInstanceError``).
- Default-value behaviour for ``TranscriptionResult.errorCode`` and
  ``STTLoaderResult.mimeType``.
- The typed extraction-exception taxonomy: the 1:1 (and shared) exception →
  ``STTErrorCode`` mapping and the ``isinstance`` relationship to
  ``STTExtractionError``.
- ``STTMediaLoader`` usability as a type hint.
"""

import dataclasses
import typing

import pytest

from lib.stt.exceptions import (
    AudioDecodeError,
    AudioTooLargeError,
    DurationExceededError,
    EncoderError,
    NoAudioTrackError,
    SourceTooLargeError,
    STTExtractionError,
)
from lib.stt.models import (
    AudioFormatSpec,
    ExtractedAudio,
    STTAudioContainerType,
    STTErrorCode,
    STTLoaderResult,
    STTMediaLoader,
    STTResultStatus,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionWord,
)

# ============================================================================
# Enums — membership and exact values
# ============================================================================


def testSTTResultStatusMembershipAndValues() -> None:
    """STTResultStatus exposes exactly the three named members with their values.

    Returns:
        None
    """
    members = {member.name: member.value for member in STTResultStatus}
    assert members == {
        "FINAL": "final",
        "NO_SPEECH": "no-speech",
        "ERROR": "error",
    }


def testSTTErrorCodeMembershipAndValues() -> None:
    """STTErrorCode exposes exactly the nine named categories with their values.

    Returns:
        None
    """
    members = {member.name: member.value for member in STTErrorCode}
    assert members == {
        "ADMISSION_TIMEOUT": "admission-timeout",
        "SOURCE_TOO_LARGE": "source-too-large",
        "SOURCE_SIZE_UNKNOWN": "source-size-unknown",
        "NO_AUDIO": "no-audio",
        "AUDIO_TOO_LARGE": "audio-too-large",
        "DURATION_EXCEEDED": "duration-exceeded",
        "DOWNLOAD_ERROR": "download-error",
        "PROVIDER_ERROR": "provider-error",
        "PROTOCOL_ERROR": "protocol-error",
    }


def testSTTAudioContainerTypeWireFixedValues() -> None:
    """STTAudioContainerType values are the exact protobuf-JSON wire labels.

    These labels are written verbatim into ``container_audio.container_audio_type``
    and are a wire contract, so casing is load-bearing.

    Returns:
        None
    """
    assert STTAudioContainerType.WAV == "WAV"
    assert STTAudioContainerType.OGG_OPUS == "OGG_OPUS"
    assert STTAudioContainerType.MP3 == "MP3"
    members = {member.name: member.value for member in STTAudioContainerType}
    assert members == {"WAV": "WAV", "OGG_OPUS": "OGG_OPUS", "MP3": "MP3"}


def testStrEnumStringIdentity() -> None:
    """StrEnum members compare equal to their plain string values.

    Returns:
        None
    """
    assert STTResultStatus.FINAL == "final"
    assert STTErrorCode.NO_AUDIO == "no-audio"
    assert STTAudioContainerType.OGG_OPUS == "OGG_OPUS"


# ============================================================================
# Records — construction, immutability, defaults
# ============================================================================


def testTranscriptionRecordsConstruct() -> None:
    """Nested transcript records construct with nested immutable tuples.

    Returns:
        None
    """
    word = TranscriptionWord(text="hello", startMs=0, endMs=500)
    segment = TranscriptionSegment(
        text="hello world",
        startMs=0,
        endMs=1200,
        words=(word, TranscriptionWord(text="world", startMs=500, endMs=1200)),
    )
    result = TranscriptionResult(status=STTResultStatus.FINAL, segments=(segment,))

    assert result.status is STTResultStatus.FINAL
    assert len(result.segments) == 1
    assert result.segments[0].words[0].text == "hello"
    assert isinstance(result.segments, tuple)
    assert isinstance(result.segments[0].words, tuple)


def testTranscriptionResultErrorCodeDefaultsToNone() -> None:
    """TranscriptionResult.errorCode defaults to None when omitted.

    Returns:
        None
    """
    result = TranscriptionResult(status=STTResultStatus.ERROR, segments=())
    assert result.errorCode is None


def testSTTLoaderResultMimeTypeDefaultsToNone() -> None:
    """STTLoaderResult.mimeType defaults to None when omitted.

    Returns:
        None
    """
    loaderResult = STTLoaderResult(data=b"\x00\x01", fileSize=2)
    assert loaderResult.mimeType is None
    assert loaderResult.fileSize == 2
    assert loaderResult.data == b"\x00\x01"


def testAudioFormatSpecAndExtractedAudioConstruct() -> None:
    """AudioFormatSpec and ExtractedAudio construct with their declared fields.

    Returns:
        None
    """
    spec = AudioFormatSpec(
        container=STTAudioContainerType.OGG_OPUS,
        minChannels=1,
        maxChannels=2,
        minSampleRate=8000,
        maxSampleRate=48000,
    )
    assert spec.container is STTAudioContainerType.OGG_OPUS
    assert spec.maxChannels == 2

    extracted = ExtractedAudio(
        container=STTAudioContainerType.OGG_OPUS,
        channels=2,
        sampleRate=48000,
        data=b"\x49\x4f",
        durationMs=1500,
    )
    assert extracted.channels == 2
    assert extracted.data == b"\x49\x4f"
    assert extracted.durationMs == 1500


@pytest.mark.parametrize(
    "instance, field",
    [
        (TranscriptionWord(text="x", startMs=0, endMs=1), "text"),
        (TranscriptionSegment(text="x", startMs=0, endMs=1, words=()), "text"),
        (TranscriptionResult(status=STTResultStatus.FINAL, segments=()), "status"),
        (
            AudioFormatSpec(
                container=STTAudioContainerType.WAV,
                minChannels=1,
                maxChannels=1,
                minSampleRate=16000,
                maxSampleRate=16000,
            ),
            "container",
        ),
        (
            ExtractedAudio(
                container=STTAudioContainerType.WAV,
                channels=1,
                sampleRate=16000,
                data=b"",
                durationMs=0,
            ),
            "container",
        ),
        (STTLoaderResult(data=b"", fileSize=0), "data"),
    ],
)
def testFrozenRecordsAreImmutable(instance: object, field: str) -> None:
    """Every frozen record raises FrozenInstanceError on attribute assignment.

    Each case mutates a REAL field declared on that record. The previous form
    mutated ``.text`` uniformly, which ``AudioFormatSpec`` / ``ExtractedAudio`` /
    ``STTLoaderResult`` do not even declare — it only passed because frozen
    ``__setattr__`` raises before checking attribute existence, so the intent was
    unclear. The value is irrelevant (frozen ``__setattr__`` raises before the
    assignment completes), so a uniform ``"mutated"`` sentinel is used.

    Args:
        instance: A constructed frozen dataclass instance.
        field: A real field name declared on ``instance`` to attempt to mutate.

    Returns:
        None
    """
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, field, "mutated")


# ============================================================================
# Exceptions — taxonomy, errorCode mapping, base relationship
# ============================================================================


@pytest.mark.parametrize(
    "excType, expectedCode",
    [
        (NoAudioTrackError, STTErrorCode.NO_AUDIO),
        (SourceTooLargeError, STTErrorCode.SOURCE_TOO_LARGE),
        (DurationExceededError, STTErrorCode.DURATION_EXCEEDED),
        (AudioTooLargeError, STTErrorCode.AUDIO_TOO_LARGE),
        (AudioDecodeError, STTErrorCode.PROVIDER_ERROR),
        (EncoderError, STTErrorCode.PROVIDER_ERROR),
    ],
)
def testExceptionErrorCodeMapping(excType: type[STTExtractionError], expectedCode: STTErrorCode) -> None:
    """Each typed exception maps to the expected STTErrorCode via its class attribute.

    Args:
        excType: The concrete exception class to instantiate.
        expectedCode: The STTErrorCode its ``errorCode`` class attribute must equal.

    Returns:
        None
    """
    assert excType.errorCode is expectedCode
    instance = excType("boom")
    assert instance.errorCode is expectedCode


def testAudioDecodeAndEncoderShareProviderErrorCode() -> None:
    """AudioDecodeError and EncoderError both map to PROVIDER_ERROR (many→one).

    Returns:
        None
    """
    assert AudioDecodeError.errorCode is STTErrorCode.PROVIDER_ERROR
    assert EncoderError.errorCode is STTErrorCode.PROVIDER_ERROR
    assert AudioDecodeError.errorCode is EncoderError.errorCode


@pytest.mark.parametrize(
    "excType",
    [
        NoAudioTrackError,
        SourceTooLargeError,
        DurationExceededError,
        AudioTooLargeError,
        AudioDecodeError,
        EncoderError,
    ],
)
def testExceptionIsSubclassOfBase(excType: type[STTExtractionError]) -> None:
    """Each typed exception is an instance/subclass of STTExtractionError.

    Args:
        excType: The concrete exception class to instantiate and check.

    Returns:
        None
    """
    assert issubclass(excType, STTExtractionError)
    instance = excType("boom")
    assert isinstance(instance, STTExtractionError)
    assert isinstance(instance, Exception)


def testBaseExceptionIsExceptionSubclass() -> None:
    """STTExtractionError subclasses Exception itself.

    Returns:
        None
    """
    assert issubclass(STTExtractionError, Exception)


def testExceptionCarriesMessage() -> None:
    """The human message passed to __init__ is forwarded to Exception.

    Returns:
        None
    """
    message = "no decodable audio stream in source"
    instance = NoAudioTrackError(message)
    assert str(instance) == message
    assert instance.args == (message,)


# ============================================================================
# STTMediaLoader type alias — usable as a type hint
# ============================================================================


def testSTTMediaLoaderUsableAsTypeHint() -> None:
    """A function annotated with STTMediaLoader resolves the alias via get_type_hints.

    Returns:
        None
    """

    async def sampleLoader(maxBytes: int) -> STTLoaderResult:
        """A loader matching the STTMediaLoader signature.

        Args:
            maxBytes: The download byte bound.

        Returns:
            STTLoaderResult: The loaded bytes.
        """
        return STTLoaderResult(data=b"abc", fileSize=3)

    def consume(loader: STTMediaLoader) -> STTMediaLoader:
        """Echo the loader to exercise the alias on both parameter and return.

        Args:
            loader: A media loader callable.

        Returns:
            STTMediaLoader: The same loader, unchanged.
        """
        return loader

    hints = typing.get_type_hints(consume)
    assert hints["loader"] is STTMediaLoader
    assert hints["return"] is STTMediaLoader

    # The alias is the expected Callable form, and a matching callable is accepted.
    assert STTMediaLoader == typing.Callable[[int], typing.Awaitable[STTLoaderResult]]
    assert consume(sampleLoader) is sampleLoader
