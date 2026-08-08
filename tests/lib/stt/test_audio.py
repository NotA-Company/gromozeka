"""Unit tests for lib.stt.audio (PyAV extraction + format negotiation).

Covers:
- Probe success across voice and audio containers and mono/stereo sources.
- No-audio-track and corrupt-source failure modes.
- Channel preservation through BOTH the pass-through and transcode paths.
- Path selection: supported-container pass-through vs. unsupported-container
  transcode (and out-of-spec channel/rate routing to transcode).
- PyAV container close on every path (success, each exception type, and
  cancellation) via a close-tracking proxy.
"""

import io
from typing import Callable, List, Tuple, cast

import av
import numpy as np
import pytest
from av.audio.stream import AudioStream

from lib.stt import audio as audioMod
from lib.stt.audio import extractAudio
from lib.stt.exceptions import (
    AudioDecodeError,
    EncoderError,
    NoAudioTrackError,
)
from lib.stt.models import (
    AudioFormatSpec,
    ExtractedAudio,
    STTAudioContainerType,
)

# ============================================================================
# Constants — a Yandex-like provider format surface
# ============================================================================

#: A Yandex-like ordered format surface: OGG_OPUS first (the preferred transcode
#: target), then MP3, then a mono-only 8–16 kHz WAV spec. OGG_OPUS/MP3 accept
#: 1–2 channels at 8–48 kHz; WAV is restricted to mono 8–16 kHz so a stereo or
#: 48 kHz WAV routes to the transcode path.
_YANDEX_FORMATS: Tuple[AudioFormatSpec, ...] = (
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

#: Default synthesis sample rate (a common STT rate).
_TONE_RATE = 16000


# ============================================================================
# Fixture helpers — in-test audio synthesis via PyAV (no binary blobs)
# ============================================================================


def _synthTone(seconds: float = 0.5, freq: float = 440.0, sampleRate: int = _TONE_RATE) -> np.ndarray:
    """Synthesise a signed-16-bit sine tone as a 1-D numpy array.

    Args:
        seconds: Tone duration in seconds.
        freq: Tone frequency in Hz.
        sampleRate: Synthesis sample rate in Hz.

    Returns:
        np.ndarray: A 1-D ``int16`` array of the tone samples.
    """
    n = int(sampleRate * seconds)
    t = np.linspace(0, seconds, n, endpoint=False)
    return (0.3 * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)


def _encode(
    containerFmt: str,
    codec: str,
    channels: int,
    seconds: float = 0.5,
    sampleRate: int = _TONE_RATE,
) -> bytes:
    """Encode a sine tone to a container via PyAV.

    Args:
        containerFmt: PyAV output ``format=`` name (e.g. ``"wav"`` / ``"ogg"`` /
            ``"mp3"`` / ``"mp4"``).
        codec: libav codec name (e.g. ``"pcm_s16le"`` / ``"libopus"`` /
            ``"libmp3lame"`` / ``"aac"``).
        channels: 1 (mono) or 2 (stereo).
        seconds: Tone duration in seconds.
        sampleRate: Synthesis sample rate in Hz.

    Returns:
        bytes: The encoded container bytes.
    """
    layout = "mono" if channels == 1 else "stereo"
    tone = _synthTone(seconds=seconds, sampleRate=sampleRate)
    if channels == 1:
        frame = av.AudioFrame.from_ndarray(tone.reshape(1, -1), format="s16", layout="mono")
    else:
        frame = av.AudioFrame.from_ndarray(np.stack([tone, tone]), format="s16p", layout="stereo")
    frame.sample_rate = sampleRate

    buffer = io.BytesIO()
    container = av.open(buffer, mode="w", format=containerFmt)
    stream = cast(AudioStream, container.add_stream(codec, rate=sampleRate))
    stream.layout = layout
    if codec == "libopus":
        stream.options = {"application": "voip"}
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()
    return buffer.getvalue()


def _makeWav(channels: int = 1, seconds: float = 0.5) -> bytes:
    """Encode a mono/stereo WAV (pcm_s16le) source.

    Args:
        channels: 1 or 2.
        seconds: Tone duration in seconds.

    Returns:
        bytes: The WAV container bytes.
    """
    return _encode("wav", "pcm_s16le", channels, seconds=seconds)


def _makeOggOpus(channels: int = 1, seconds: float = 0.5) -> bytes:
    """Encode a mono/stereo OGG_OPUS (libopus) source.

    Args:
        channels: 1 or 2.
        seconds: Tone duration in seconds.

    Returns:
        bytes: The OGG_OPUS container bytes.
    """
    return _encode("ogg", "libopus", channels, seconds=seconds)


def _makeMp3(channels: int = 1, seconds: float = 0.5) -> bytes:
    """Encode a mono/stereo MP3 (libmp3lame) source.

    Args:
        channels: 1 or 2.
        seconds: Tone duration in seconds.

    Returns:
        bytes: The MP3 container bytes.
    """
    return _encode("mp3", "libmp3lame", channels, seconds=seconds)


def _makeM4a(channels: int = 1, seconds: float = 0.5) -> bytes:
    """Encode a mono/stereo AAC-in-MP4 source (an unsupported container).

    MP4's PyAV ``format.name`` is ``"mov,mp4,m4a,3gp,3g2,mj2"`` which does not map
    to any inline container, so it routes to the transcode path.

    Args:
        channels: 1 or 2.
        seconds: Tone duration in seconds.

    Returns:
        bytes: The MP4/AAC container bytes.
    """
    return _encode("mp4", "aac", channels, seconds=seconds)


def _makeVideoOnly() -> bytes:
    """Encode a tiny video-only MP4 (no audio stream).

    Returns:
        bytes: The MP4 container bytes with one video stream and no audio stream.
    """
    buffer = io.BytesIO()
    container = av.open(buffer, mode="w", format="mp4")
    stream = container.add_stream("libx264", rate=10)
    frame = av.VideoFrame.from_ndarray(np.zeros((64, 64, 3), dtype=np.uint8), format="rgb24")
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()
    return buffer.getvalue()


def _makeCorrupt() -> bytes:
    """Return garbage bytes that PyAV cannot open as a container.

    Returns:
        bytes: Non-audio garbage.
    """
    return b"\x00\x01\x02\x03not-an-audio-container"


def _makeTruncated() -> bytes:
    """Build a FLAC source whose header opens but whose audio data is truncated.

    A valid native-FLAC source is encoded, then roughly half its bytes are
    discarded. FLAC's per-frame CRC checks are strict, so the truncated stream
    opens cleanly (the streaminfo header parses) but fails mid-``decode(audio=0)``
    with an ``InvalidDataError`` — the corrupt-but-openable path that must surface
    as :class:`AudioDecodeError`, not a raw :class:`av.error.FFmpegError` (§5
    step 2; the only-raise-point contract, §4). Unlike a truncated OGG (which
    fails at ``av.open``) or a middle-corrupted OGG (which OGG conceals and
    decodes short without raising), truncated FLAC deterministically fails
    mid-decode.

    Returns:
        bytes: A truncated native-FLAC container.
    """
    full = _encode("flac", "flac", channels=1, seconds=1.0)
    return full[: len(full) // 2]


#: Standard FFmpeg named channel layouts for >2-channel test fixtures.
_MULTI_CHANNEL_LAYOUTS = {3: "3.0", 4: "quad", 5: "4.1", 6: "5.1"}


def _makeMultiChannelWav(channels: int = 3, seconds: float = 0.5) -> bytes:
    """Encode a >2-channel WAV (pcm_s16le) source.

    Opus and mp3 support at most 2 channels; the never-downmix hard rule (§5)
    makes a >2-channel source unrecoverable, so it must raise
    :class:`EncoderError` at layout time rather than emit an invalid ``"Nc"``
    layout. This fixture builds such a source so the >2-channel transcode
    rejection is exercised end-to-end.

    Args:
        channels: Channel count (>= 3 to exceed the opus/mp3 ceiling; defaults to
            3, the ``"3.0"`` standard FFmpeg layout).
        seconds: Tone duration in seconds.

    Returns:
        bytes: The multi-channel WAV container bytes.
    """
    layout = _MULTI_CHANNEL_LAYOUTS.get(channels)
    if layout is None:
        raise ValueError(f"no test fixture layout for {channels} channels")
    tone = _synthTone(seconds=seconds)
    # s16p (planar signed 16-bit): one plane per channel.
    planes = np.stack([tone] * channels)
    frame = av.AudioFrame.from_ndarray(planes, format="s16p", layout=layout)
    frame.sample_rate = _TONE_RATE

    buffer = io.BytesIO()
    container = av.open(buffer, mode="w", format="wav")
    stream = cast(AudioStream, container.add_stream("pcm_s16le", rate=_TONE_RATE))
    stream.layout = layout
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()
    return buffer.getvalue()


async def _extract(
    data: bytes,
    *,
    formats: Tuple[AudioFormatSpec, ...] = _YANDEX_FORMATS,
) -> ExtractedAudio:
    """Call :func:`extractAudio` with the given source and provider format surface.

    Args:
        data: The source container bytes.
        formats: The provider format surface (defaults to the Yandex-like set).

    Returns:
        ExtractedAudio: The negotiated audio.
    """
    return await extractAudio(
        data,
        formats,
    )


# ============================================================================
# Close-tracking proxy — asserts the finally cleanup on every path
# ============================================================================


class _TrackedContainer:
    """Proxy delegating to a real PyAV container but tracking ``close()``.

    PyAV container ``close`` is read-only, so a delegating proxy is the only way
    to observe whether the module closed a container. Every attribute access
    other than ``close`` is forwarded to the wrapped container.

    Attributes:
        closed: A one-element list whose first element flips to ``True`` once
            ``close`` has been called (a list so the flag is mutable from the
            closure without re-binding the attribute).
    """

    _real: object
    closed: List[bool]

    def __init__(self, real: object, closed: List[bool]) -> None:
        """Wrap a real container and attach the close-flag list.

        Args:
            real: The real PyAV container.
            closed: A one-element list used as a mutable close flag.
        """
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "closed", closed)

    def close(self) -> None:
        """Record the close and forward it to the real container.

        Returns:
            None
        """
        self.closed[0] = True
        getattr(self._real, "close")()

    def __getattr__(self, name: str) -> object:
        """Forward any other attribute access to the wrapped container.

        Args:
            name: The attribute name.

        Returns:
            The attribute value from the wrapped container.
        """
        return getattr(self._real, name)


def _installCloseSpy(monkeypatch: pytest.MonkeyPatch) -> List[_TrackedContainer]:
    """Monkeypatch ``av.open`` in the audio module to return tracked containers.

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        List[_TrackedContainer]: A list (appended to on every ``av.open``) of the
        tracked containers opened during the patched scope.
    """
    opened: List[_TrackedContainer] = []
    realOpen = audioMod.av.open

    def spyOpen(*args: object, **kwargs: object) -> _TrackedContainer:
        """Wrap the real ``av.open`` result in a tracked container.

        Args:
            *args: Positional args forwarded to ``av.open``.
            **kwargs: Keyword args forwarded to ``av.open``.

        Returns:
            _TrackedContainer: The wrapped, close-tracked container.
        """
        real = realOpen(*args, **kwargs)  # type: ignore[arg-type]
        tracked = _TrackedContainer(real, [False])
        opened.append(tracked)
        return tracked

    monkeypatch.setattr(audioMod.av, "open", spyOpen)
    return opened


def _assertAllClosed(opened: List[_TrackedContainer]) -> None:
    """Assert every tracked container was closed.

    Args:
        opened: The list returned by :func:`_installCloseSpy`.
    """
    unclosed = [i for i, c in enumerate(opened) if not c.closed[0]]
    assert not unclosed, f"{len(unclosed)} container(s) left open at indices {unclosed}"


# ============================================================================
# Probe success — voice/audio containers, mono AND stereo
# ============================================================================


@pytest.mark.parametrize(
    "maker, channels, expectedContainer",
    [
        (_makeOggOpus, 1, STTAudioContainerType.OGG_OPUS),
        (_makeOggOpus, 2, STTAudioContainerType.OGG_OPUS),
        (_makeMp3, 1, STTAudioContainerType.MP3),
        (_makeMp3, 2, STTAudioContainerType.MP3),
        (_makeWav, 1, STTAudioContainerType.WAV),
    ],
)
async def testProbeAndPassthroughPreservesContainer(
    maker: Callable[..., bytes], channels: int, expectedContainer: STTAudioContainerType
) -> None:
    """A supported source within caps passes through with its container and channels.

    Args:
        maker: The fixture builder.
        channels: Source channel count (1 or 2).
        expectedContainer: The expected :class:`STTAudioContainerType` of the result.

    Returns:
        None
    """
    data = maker(channels=channels)
    result = await _extract(data)
    assert result.container is expectedContainer
    assert result.channels == channels
    assert result.data == data  # pass-through returns the source bytes verbatim
    assert result.durationMs > 0


async def testProbeStereoOggReportsStereoChannels() -> None:
    """A stereo OGG_OPUS source reports ``channels == 2`` through pass-through.

    Returns:
        None
    """
    result = await _extract(_makeOggOpus(channels=2))
    assert result.channels == 2
    assert result.container is STTAudioContainerType.OGG_OPUS


async def testProbeOggOpusReportsOpusNativeRate() -> None:
    """An OGG_OPUS source reports the 48 kHz Opus-native decoded rate.

    Opus always decodes to 48 kHz regardless of the nominal encode rate, so the
    measured ``sampleRate`` is 48000.

    Returns:
        None
    """
    result = await _extract(_makeOggOpus(channels=1))
    assert result.sampleRate == 48000


async def testProbeWavReportsSourceRate() -> None:
    """A WAV source reports its 16 kHz source rate through pass-through.

    Returns:
        None
    """
    result = await _extract(_makeWav(channels=1))
    assert result.sampleRate == 16000


# ============================================================================
# No-audio-track and corrupt-source failures
# ============================================================================


async def testNoAudioTrackRaisesNoAudioTrackError() -> None:
    """A video-only container (no audio stream) raises NoAudioTrackError.

    Returns:
        None
    """
    with pytest.raises(NoAudioTrackError) as excInfo:
        await _extract(_makeVideoOnly())
    assert excInfo.value.errorCode.value == "no-audio"


async def testCorruptBytesRaiseAudioDecodeError() -> None:
    """Garbage bytes PyAV cannot open raise AudioDecodeError.

    Returns:
        None
    """
    with pytest.raises(AudioDecodeError) as excInfo:
        await _extract(_makeCorrupt())
    assert excInfo.value.errorCode.value == "provider-error"


# ============================================================================
# Path selection
# ============================================================================


async def testSupportedContainerWithinCapIsPassthrough() -> None:
    """A supported container within all caps returns the source bytes unchanged.

    Returns:
        None
    """
    data = _makeOggOpus(channels=1)
    result = await _extract(data)
    assert result.container is STTAudioContainerType.OGG_OPUS
    assert result.data == data  # verbatim pass-through, no transcode


async def testUnsupportedContainerTranscodesToOggOpus() -> None:
    """A decodable-but-unsupported container (MP4/AAC) transcodes to OGG_OPUS.

    Returns:
        None
    """
    data = _makeM4a(channels=1)
    result = await _extract(data)
    assert result.container is STTAudioContainerType.OGG_OPUS
    assert result.data != data  # re-encoded, not pass-through
    assert result.sampleRate == 48000  # opus-native rate
    assert result.durationMs > 0


async def testUnsupportedContainerTranscodesToMp3WhenOpusAbsent() -> None:
    """An unsupported container transcodes to MP3 (NOT OGG_OPUS) when OGG_OPUS is absent.

    The default Yandex-like surface lists OGG_OPUS first, so ``_chooseTranscodeTarget``
    always picks it and every other transcode test exercises the opus path. With a
    surface of ``(MP3, WAV)`` (NO OGG_OPUS) the target is MP3, whose transcode
    branch diverges from the opus path in two ways: the codec is ``libmp3lame``
    and the output sample rate is the SOURCE rate (``probe.sampleRate``), NOT the
    opus-native 48 kHz. This pins that branch (Phase-3 coverage gap R1).

    Returns:
        None
    """
    mp3FirstSurface: Tuple[AudioFormatSpec, ...] = (
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
    data = _makeM4a(channels=1)  # MP4/AAC — unsupported container -> transcode; source rate is 16 kHz
    result = await _extract(data, formats=mp3FirstSurface)
    assert result.container is STTAudioContainerType.MP3
    assert result.data != data  # re-encoded, not pass-through
    assert result.sampleRate != 48000  # NOT the opus-native rate — the key divergence
    assert result.sampleRate == 16000  # keeps the SOURCE rate (m4a encoded at 16 kHz)
    assert result.durationMs > 0


async def testSupportedButStereoWavTranscodesBecauseOutOfWavSpec() -> None:
    """A stereo WAV (outside the mono-only WAV spec) transcodes to OGG_OPUS.

    The container matches WAV but the channel count exceeds the spec's range, so
    no spec matches and the source routes to transcode.

    Returns:
        None
    """
    data = _makeWav(channels=2)
    result = await _extract(data)
    assert result.container is STTAudioContainerType.OGG_OPUS
    assert result.data != data
    assert result.channels == 2  # channel-preserving


async def testUnderCapTranscodeDurationApproximatesSource() -> None:
    """An under-cap transcode reports a duration within ~50ms of the source.

    The transcode path measures duration from the actual encoded sample count
    (§5 step 3 — not container metadata alone). For a source well under the
    duration cap the reported ``durationMs`` tracks the source duration within
    encoder-flush tail tolerance (the count is of source-rate decoded samples,
    independent of the opus encoder's internal delay).

    Returns:
        None
    """
    seconds = 1.0
    data = _makeWav(channels=2, seconds=seconds)  # stereo WAV -> transcode
    result = await _extract(data)
    assert result.container is STTAudioContainerType.OGG_OPUS
    sourceMs = int(round(seconds * 1000))
    assert abs(result.durationMs - sourceMs) <= 50


# ============================================================================
# Channel preservation (hard rule — never downmix)
# ============================================================================


async def testStereoSourceStaysStereoThroughTranscode() -> None:
    """A stereo source stays stereo (channels == 2) after transcode — no downmix.

    Returns:
        None
    """
    data = _makeWav(channels=2)
    result = await _extract(data)
    assert result.channels == 2


async def testMonoSourceStaysMonoThroughTranscode() -> None:
    """A mono unsupported source stays mono (channels == 1) after transcode.

    Returns:
        None
    """
    data = _makeM4a(channels=1)
    result = await _extract(data)
    assert result.channels == 1


async def testStereoSourceStaysStereoThroughPassthrough() -> None:
    """A stereo OGG_OPUS source stays stereo through pass-through.

    Returns:
        None
    """
    result = await _extract(_makeOggOpus(channels=2))
    assert result.channels == 2


# ============================================================================
# Container close on every path (finally cleanup contract)
# ============================================================================


async def testContainersClosedOnSuccessPassthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    """The input container is closed on a successful pass-through.

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        None
    """
    data = _makeOggOpus(channels=1)  # build fixture before the spy patches av.open
    opened = _installCloseSpy(monkeypatch)
    await _extract(data)
    # This count is implementation-specific — if probe/transcode refactored, update expected count.
    assert len(opened) == 2  # probe + pass-through duration measurement
    _assertAllClosed(opened)


async def testContainersClosedOnSuccessTranscode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both input and output containers are closed on a successful transcode.

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        None
    """
    data = _makeWav(channels=2)  # stereo WAV -> transcode; build before the spy
    opened = _installCloseSpy(monkeypatch)
    await _extract(data)
    # This count is implementation-specific — if probe/transcode refactored, update expected count.
    assert len(opened) == 3  # probe + transcode input + transcode output
    _assertAllClosed(opened)


async def testContainersClosedOnNoAudioTrack(monkeypatch: pytest.MonkeyPatch) -> None:
    """The container is closed when NoAudioTrackError is raised.

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        None
    """
    data = _makeVideoOnly()  # build before the spy patches av.open
    opened = _installCloseSpy(monkeypatch)
    with pytest.raises(NoAudioTrackError):
        await _extract(data)
    _assertAllClosed(opened)


async def testTruncatedButOpenableSourceRaisesAudioDecodeError(monkeypatch: pytest.MonkeyPatch) -> None:
    """A source that opens but fails mid-decode raises AudioDecodeError (not raw FFmpegError).

    A truncated FLAC source opens cleanly (its streaminfo header parses) so its
    audio frames are incomplete, and the transcode decode loop hits an
    ``InvalidDataError`` mid-``decode(audio=0)``. Per §5 step 2 and the
    only-raise-point contract (§4), this must surface as
    :class:`AudioDecodeError`, never a raw :class:`av.error.FFmpegError`.
    Containers opened before the failure are closed by each path's ``finally``
    (no leak). This replaces the tautological close-on-corrupt-open test (garbage
    bytes fail at ``av.open`` before the spy records any container).

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        None
    """
    data = _makeTruncated()  # build fixture before the spy patches av.open
    opened = _installCloseSpy(monkeypatch)
    with pytest.raises(AudioDecodeError) as excInfo:
        await _extract(data)
    assert excInfo.value.errorCode.value == "provider-error"
    _assertAllClosed(opened)


# ============================================================================
# Guarded-import and encoder-failure paths
# ============================================================================


async def testNoCompressedTranscodeTargetRaisesEncoderError() -> None:
    """An unsupported source with no compressed transcode target raises EncoderError.

    A provider accepting only WAV (no OGG_OPUS/MP3) cannot transcode, so an
    unsupported source (MP4/AAC) raises EncoderError rather than corrupting output.

    Returns:
        None
    """
    wavOnlyFormats: Tuple[AudioFormatSpec, ...] = (
        AudioFormatSpec(
            container=STTAudioContainerType.WAV,
            minChannels=1,
            maxChannels=2,
            minSampleRate=8000,
            maxSampleRate=48000,
        ),
    )
    with pytest.raises(EncoderError):
        await _extract(_makeM4a(channels=1), formats=wavOnlyFormats)


async def testMultiChannelSourceRaisesEncoderErrorAndClosesContainers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A >2-channel source raises EncoderError and leaks no container.

    Opus and mp3 support at most 2 channels; the never-downmix hard rule (§5)
    makes a >2-channel source unrecoverable, so ``_layoutForChannels`` raises a
    clean :class:`EncoderError` after both the input and output containers are
    opened — and the ``finally`` closes both (no leak when the encoder rejects
    the source mid-configuration, the EncoderError-mid-encode gap).

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        None
    """
    data = _makeMultiChannelWav(channels=3)  # build fixture before the spy
    opened = _installCloseSpy(monkeypatch)
    with pytest.raises(EncoderError) as excInfo:
        await _extract(data)
    assert excInfo.value.errorCode.value == "provider-error"
    # probe (1) + transcode input (1) + transcode output (1); all closed, none leaked.
    # This count is implementation-specific — if probe/transcode refactored, update expected count.
    assert len(opened) == 3
    _assertAllClosed(opened)
