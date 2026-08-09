"""Unit tests for lib.stt foundation: models + exceptions.

Covers:
- Enum membership and exact string values (``STTResultStatus``,
  ``STTErrorCode``, ``STTAudioContainerType``), including the
  ``STTAudioContainerType.toYandexSpeechKit()`` wire-label mapping.
- Frozen/slot record construction and immutability (``setattr`` raises
  ``dataclasses.FrozenInstanceError``).
- Default-value behaviour for ``TranscriptionResult.errorCode``.
- The typed extraction-exception taxonomy: the 1:1 (and shared) exception →
  ``STTErrorCode`` mapping and the ``isinstance`` relationship to
  ``STTExtractionError``.
"""

import dataclasses

import pytest

from lib.stt.exceptions import (
    AudioDecodeError,
    EncoderError,
    NoAudioTrackError,
    STTExtractionError,
)
from lib.stt.models import (
    AudioFormatSpec,
    ExtractedAudio,
    STTAttributionType,
    STTAudioContainerType,
    STTErrorCode,
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


def testSTTAttributionTypeMembershipAndValues() -> None:
    """STTAttributionType exposes the unified channel and speaker roles.

    Returns:
        None
    """
    members = {member.name: member.value for member in STTAttributionType}
    assert members == {"CHANNEL": "channel", "SPEAKER": "speaker"}


def testSTTErrorCodeMembershipAndValues() -> None:
    """STTErrorCode exposes exactly the nine shared failure-category members.

    Returns:
        None
    """
    members = {member.name: member.value for member in STTErrorCode}
    assert members == {
        "STT_DISABLED": "stt-disabled",
        "SOURCE_TOO_LARGE": "source-too-large",
        "SOURCE_SIZE_UNKNOWN": "source-size-unknown",
        "NO_AUDIO": "no-audio",
        "DURATION_EXCEEDED": "duration-exceeded",
        "DOWNLOAD_ERROR": "download-error",
        "PROVIDER_ERROR": "provider-error",
        "PROTOCOL_ERROR": "protocol-error",
        "OBJECT_STORAGE_ERROR": "object-storage-error",
    }


@pytest.mark.parametrize(
    "container, expectedLabel",
    [
        (STTAudioContainerType.WAV, "WAV"),
        (STTAudioContainerType.OGG_OPUS, "OGG_OPUS"),
        (STTAudioContainerType.MP3, "MP3"),
    ],
)
def testToYandexSpeechKitWireLabels(container: STTAudioContainerType, expectedLabel: str) -> None:
    """Each STTAudioContainerType maps to its Yandex SpeechKit proto wire label.

    Args:
        container: The container member to convert.
        expectedLabel: The expected Yandex wire label string.

    Returns:
        None
    """
    assert container.toYandexSpeechKit() == expectedLabel


def testToYandexSpeechKitInvalidValueRaisesValueError() -> None:
    """The defensive fallthrough raises ValueError for a non-member value.

    STTAudioContainerType is a StrEnum with exactly three members, so the
    ``case _`` branch is unreachable for a real member. It is exercised here by
    calling the underlying function with a bare string (a non-member), which
    fails every enum-member pattern and hits the fallthrough.

    Returns:
        None
    """
    with pytest.raises(ValueError):
        STTAudioContainerType.toYandexSpeechKit("bogus")  # type: ignore[arg-type]


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
    assert result.attributionType is STTAttributionType.CHANNEL


def testTranscriptionSegmentExposesOnlyUnifiedAttributionField() -> None:
    """TranscriptionSegment exposes only the unified optional attribution field.

    Returns:
        None
    """
    segment = TranscriptionSegment(text="left", startMs=0, endMs=1, words=())
    result = TranscriptionResult(status=STTResultStatus.FINAL, segments=(segment,))

    assert segment.attributionTag is None
    assert tuple(field.name for field in dataclasses.fields(segment)) == (
        "text",
        "startMs",
        "endMs",
        "words",
        "attributionTag",
    )
    assert not hasattr(segment, "channelTag")
    assert not hasattr(segment, "speakerTag")
    assert result.attributionType is STTAttributionType.CHANNEL


def testTranscriptionSegmentAcceptsUnifiedAttributionPositionally() -> None:
    """The fifth positional field is the unified attribution tag.

    Returns:
        None
    """
    segment = TranscriptionSegment("left", 0, 1, (), "attribution-left")

    assert segment.attributionTag == "attribution-left"


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
    ],
)
def testFrozenRecordsAreImmutable(instance: object, field: str) -> None:
    """Every frozen record raises FrozenInstanceError on attribute assignment.

    Each case mutates a REAL field declared on that record. The previous form
    mutated ``.text`` uniformly, which ``AudioFormatSpec`` / ``ExtractedAudio``
    do not even declare — it only passed because frozen
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
# STT v1.1 — Object Storage error code + ownership docstrings
# ============================================================================


def testObjectStorageErrorIsMember() -> None:
    """OBJECT_STORAGE_ERROR is a member of STTErrorCode with the correct value.

    Returns:
        None
    """
    assert STTErrorCode.OBJECT_STORAGE_ERROR.value == "object-storage-error"


def testObjectStorageErrorDocstringMentionsUpload() -> None:
    """STTErrorCode class docstring references OBJECT_STORAGE_ERROR in the provider group.

    Per-member docstrings on StrEnum are source-only (not accessible via
    ``member.__doc__``, which returns the class docstring).  The class
    docstring is the runtime-accessible surface that documents ownership.

    Returns:
        None
    """
    doc = STTErrorCode.__doc__
    assert doc is not None
    assert "OBJECT_STORAGE_ERROR" in doc


def testSourceTooLargeDocstringMentionsProviderCase() -> None:
    """STTErrorCode class docstring mentions the provider-surfaced SOURCE_TOO_LARGE case.

    The extended ownership: the provider also surfaces ``SOURCE_TOO_LARGE``
    when the extracted payload exceeds the inline threshold and Object
    Storage is disabled (design §4.2/§4.5).  This is documented in the
    class-level ownership docstring.

    Returns:
        None
    """
    doc = STTErrorCode.__doc__
    assert doc is not None
    assert "provider" in doc.lower()
    assert "SOURCE_TOO_LARGE" in doc
    # The class docstring mentions the provider surfaces SOURCE_TOO_LARGE.
    assert "surfaces" in doc.lower()
