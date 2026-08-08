"""PyAV-based audio extraction with provider-driven format negotiation for lib.stt.

This module owns the only runtime raise-point inside ``lib/stt`` (the coroutine
:func:`extractAudio`). ``extractAudio`` downloads nothing — it receives the
already-downloaded source bytes, probes them with PyAV, negotiates one of three
paths (pass-through / transcode / reject) against the provider's
``supportedInputFormats``, and returns an :class:`~lib.stt.models.ExtractedAudio`.

Key invariants:
- **Pass-through preserves source channels; transcode converts out-of-spec
  channels/rates.** The pass-through path carries the source channel count and
  sample rate unchanged. The transcode path clamps channels to the target
  spec's ``[minChannels, maxChannels]`` (downmix when too many, upmix when too
  few) and the output rate to ``[minSampleRate, maxSampleRate]`` (nearest
  bound), both via an :class:`~av.audio.resampler.AudioResampler`.
- **Duration is measured from the actual sample count**, not container metadata
  alone, on every path.
- **All blocking PyAV work runs in** :func:`asyncio.to_thread`, and a ``finally``
  block closes BOTH the input and output PyAV containers on every path —
  success, exception, and cancellation.
- Each typed exception maps 1:1 to an :class:`~lib.stt.models.STTErrorCode`
  (via the class-level ``errorCode``) so the caller can map the failure category
  without re-mapping.

.. note::
   This module does NOT bound decoded PCM memory — a large/long source can
   decode to hundreds of MB of PCM during probing/measurement/transcoding. The
   caller (the future STTService) is responsible for bounding source bytes and
   duration BEFORE calling :func:`extractAudio`; decoded-memory bounding is
   intentionally not enforced here (an accepted trade-off for simplicity).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import Dict, Optional, cast

import av
import av.error
from av.audio.resampler import AudioResampler
from av.audio.stream import AudioStream
from av.container import InputContainer

from .exceptions import (
    AudioDecodeError,
    EncoderError,
    NoAudioTrackError,
)
from .models import (
    AudioFormatSpec,
    ExtractedAudio,
    STTAudioContainerType,
)

#: Compressed container targets the transcode path may encode to, in preference
#: order. The transcode path picks the provider's first ``supportedInputFormats``
#: entry whose container is in this tuple (OGG_OPUS for Yandex).
_COMPRESSED_TARGETS: Sequence[STTAudioContainerType] = (
    STTAudioContainerType.OGG_OPUS,
    STTAudioContainerType.MP3,
)

#: PyAV container/format name + libav codec for each transcode target container.
_CODEC_FOR_CONTAINER: Dict[STTAudioContainerType, str] = {
    STTAudioContainerType.OGG_OPUS: "libopus",
    STTAudioContainerType.MP3: "libmp3lame",
}

#: PyAV output ``format=`` name for each transcode target container. WAV is
#: never a transcode target (OGG_OPUS is always the provider's first compressed
#: target per §5), so it is intentionally absent.
_FORMAT_FOR_CONTAINER: Dict[STTAudioContainerType, str] = {
    STTAudioContainerType.OGG_OPUS: "ogg",
    STTAudioContainerType.MP3: "mp3",
}

#: Opus always produces a 48 kHz stream regardless of the input rate (the libopus
#: encoder resamples internally); the output ``ExtractedAudio.sampleRate`` reports
#: this native rate for an OGG_OPUS transcode target.
_OPUS_NATIVE_RATE = 48000


@dataclass(frozen=True, slots=True)
class _ProbeInfo:
    """Header-level probe result for a source container.

    Carries only what the path-decision needs (container, channels, sample rate);
    duration is NOT measured here — each path measures it from the actual sample
    count during its own decode (§5 step 3), so there is no redundant full decode
    of the source.

    Attributes:
        container: The mapped :class:`STTAudioContainerType`, or ``None`` when the
            source container is decodable but not one of the three inline
            containers (e.g. m4a/aac/flac) — which routes to the transcode path.
        channels: Source channel count (preserved through negotiation).
        sampleRate: Source sample rate in Hz (as PyAV decodes it — for an Opus
            source this is the 48 kHz Opus-native rate).
    """

    container: Optional[STTAudioContainerType]
    channels: int
    sampleRate: int


async def extractAudio(
    data: bytes,
    supportedInputFormats: Sequence[AudioFormatSpec],
) -> ExtractedAudio:
    """Extract and negotiate audio for a provider.

    Runs the blocking PyAV probe + negotiation in :func:`asyncio.to_thread`.
    Raises a typed :class:`~lib.stt.exceptions.STTExtractionError` (each mapping
    1:1 to an :class:`~lib.stt.models.STTErrorCode`) for every expected
    extraction failure; never returns ``None``.

    .. note::
       This function does NOT bound decoded PCM memory — a large/long source can
       decode to hundreds of MB. The caller (the future STTService) is
       responsible for bounding source bytes and duration BEFORE calling this;
       decoded-memory bounding is intentionally not enforced here (accepted
       trade-off for simplicity).

    Args:
        data: The source audio bytes to extract and negotiate.
        supportedInputFormats: The provider's ordered accepted input formats (the
            negotiation surface consumed here). The FIRST compressed entry
            (OGG_OPUS/MP3) is the transcode target.

    Returns:
        ExtractedAudio: The negotiated, format-aware audio handed to the provider.

    Raises:
        NoAudioTrackError: The source has no decodable audio stream.
        AudioDecodeError: The source is corrupt/truncated or PyAV is unavailable,
            or an unexpected non-typed exception from PyAV (caught by the caller's
            defense-in-depth).
        EncoderError: No compressed transcode target is available, or the
            encoder/muxer failed.
    """
    return await asyncio.to_thread(
        _extractBlocking,
        data,
        supportedInputFormats,
    )


def _extractBlocking(
    sourceBytes: bytes,
    supportedInputFormats: Sequence[AudioFormatSpec],
) -> ExtractedAudio:
    """Run the probe + negotiation + path execution in a worker thread.

    Args:
        sourceBytes: The source container bytes.
        supportedInputFormats: The provider's ordered accepted input formats.

    Returns:
        ExtractedAudio: The negotiated audio.

    Raises:
        STTExtractionError: A typed extraction failure (see :func:`extractAudio`).
    """
    probe = _probe(sourceBytes)

    matchedSpec = _matchFormatSpec(probe.container, probe.channels, probe.sampleRate, supportedInputFormats)

    if matchedSpec is not None:
        # Pass-through path: container supported and channels/rate in range.
        return _passthrough(sourceBytes, probe)

    # Transcode path: source container unsupported, or supported but channels/rate
    # out of range.
    targetSpec = _chooseTranscodeTarget(supportedInputFormats)
    if targetSpec is None:
        raise EncoderError("no compressed transcode target available in supportedInputFormats")
    return _transcode(sourceBytes, probe, targetSpec)


def _probe(sourceBytes: bytes) -> _ProbeInfo:
    """Open the source and read header-level stream info (no full decode).

    Selects the first audio stream and reads its container type, channel count,
    and sample rate. Does NOT decode frames — duration is measured later, from the
    actual sample count, on whichever path is chosen (§5 step 3).

    Args:
        sourceBytes: The source container bytes.

    Returns:
        _ProbeInfo: The mapped container (or ``None`` if decodable-but-unsupported),
        source channels, and source sample rate.

    Raises:
        NoAudioTrackError: The source has no audio stream.
        AudioDecodeError: The container is corrupt/truncated and cannot be opened
            or probed (a container whose header opens but whose stream descriptors
            are corrupt is caught here too, not leaked as a raw FFmpegError).
    """
    container = None
    try:
        container = av.open(BytesIO(sourceBytes), mode="r")
    except av.error.FFmpegError as exc:
        raise AudioDecodeError(f"failed to open source container: {exc}") from exc

    try:
        audioStream = _firstAudioStream(container)
        if audioStream is None:
            raise NoAudioTrackError("source contains no decodable audio stream")
        containerType = _mapContainerType(container.format.name, audioStream.codec_context.name)
        channels = int(audioStream.channels) if audioStream.channels else 0
        rate = int(audioStream.rate) if audioStream.rate else 0
        if channels <= 0 or rate <= 0:
            # Header claims no usable channels/rate; reject rather than negotiate
            # on garbage header fields.
            raise AudioDecodeError("audio stream reported non-positive channels or sample rate")
        return _ProbeInfo(container=containerType, channels=channels, sampleRate=rate)
    except av.error.FFmpegError as exc:
        raise AudioDecodeError(f"corrupt/truncated source probe: {exc}") from exc
    finally:
        if container is not None:
            container.close()


def _passthrough(
    sourceBytes: bytes,
    probe: _ProbeInfo,
) -> ExtractedAudio:
    """Pass-through path: return the source bytes in their original container.

    Decodes the source purely to measure duration from the actual sample count
    (not container metadata alone). Source channels and sample rate are
    preserved unchanged.

    Args:
        sourceBytes: The original source container bytes (returned verbatim).
        probe: The header probe result (container, channels, sample rate).

    Returns:
        ExtractedAudio: The source bytes wrapped with the source container,
        preserved channels/sample rate, and the measured duration.

    Raises:
        AudioDecodeError: The source is corrupt/truncated mid-decode.
    """
    durationMs = _measureDuration(
        sourceBytes,
        probe.sampleRate,
    )
    assert probe.container is not None  # pass-through only runs when container matched a spec
    return ExtractedAudio(
        container=probe.container,
        channels=probe.channels,
        sampleRate=probe.sampleRate,
        data=sourceBytes,
        durationMs=durationMs,
    )


def _transcode(
    sourceBytes: bytes,
    probe: _ProbeInfo,
    target: AudioFormatSpec,
) -> ExtractedAudio:
    """Transcode path: decode the source, convert channels/sample rate, and re-encode.

    Encodes to ``target.container`` (the provider's first supported compressed
    format — OGG_OPUS for Yandex). Source channels and sample rate are clamped
    to the target spec's ``[minChannels, maxChannels]`` and
    ``[minSampleRate, maxSampleRate]`` ranges via an
    :class:`~av.audio.resampler.AudioResampler` (downmix/upmix to the nearest
    in-range channel count, resample to the nearest in-range rate). A source
    already inside the spec is carried through the resampler unchanged (it is a
    passthrough for those dimensions). Decoded-memory bounding is intentionally
    not enforced here (see the module note on the accepted decoded-memory gap).

    Args:
        sourceBytes: The source container bytes.
        probe: The header probe result (container, channels, sample rate).
        target: The transcode target spec (the provider's first supported
            compressed format — OGG_OPUS or MP3), whose channel/sample-rate
            limits define the clamping bounds.

    Returns:
        ExtractedAudio: The re-encoded bytes with the target container, the
        clamped channel count, the clamped output sample rate, and the measured
        duration.

    Raises:
        AudioDecodeError: The source is corrupt/truncated mid-decode.
        EncoderError: The encoder/muxer failed, or the target spec declares a
            channel range the codec physically cannot encode (e.g. opus/mp3
            support at most 2 channels — a spec with ``maxChannels > 2`` is
            rejected up front rather than handed to the encoder).
    """
    outCodec = _CODEC_FOR_CONTAINER[target.container]
    outFormat = _FORMAT_FOR_CONTAINER[target.container]

    # Clamp the source channels to the spec's [min, max] range (downmix when
    # too many, upmix when too few). minChannels is clamped to >= 1 so a
    # misconfigured spec (minChannels=0) cannot produce a zero-channel output.
    outChannels = (
        max(target.minChannels, 1) if probe.channels < target.minChannels else min(probe.channels, target.maxChannels)
    )
    # Opus always produces a 48 kHz stream regardless of the input rate (the
    # libopus encoder resamples internally); for OGG_OPUS we use that native
    # rate directly. For MP3 we clamp the source rate to the spec's range.
    if target.container == STTAudioContainerType.OGG_OPUS:
        outRate = _OPUS_NATIVE_RATE
    else:
        outRate = (
            target.minSampleRate
            if probe.sampleRate < target.minSampleRate
            else min(probe.sampleRate, target.maxSampleRate)
        )
    outLayout = _layoutForChannels(outChannels)

    inContainer = None
    outContainer = None
    try:
        try:
            inContainer = av.open(BytesIO(sourceBytes), mode="r")
        except av.error.FFmpegError as exc:
            raise AudioDecodeError(f"failed to open source container: {exc}") from exc

        outBuffer = BytesIO()
        try:
            outContainer = av.open(outBuffer, mode="w", format=outFormat)
            outStream = cast(AudioStream, outContainer.add_stream(outCodec, rate=outRate))
            outStream.layout = outLayout
            if target.container == STTAudioContainerType.OGG_OPUS:
                # 'voip' is the appropriate application for speech recognition.
                # Gated on the enum (the authoritative signal), not the codec name.
                outStream.options = {"application": "voip"}
        except av.error.FFmpegError as exc:
            raise EncoderError(f"failed to configure {outCodec} encoder: {exc}") from exc

        # The resampler converts decoded frames to the target layout + rate
        # before encoding. ``format=None`` lets swresample pick a format the
        # encoder accepts (libopus/libmp3lame both take ``s16``). Only
        # instantiated when a conversion is actually needed — a source already
        # at the target channels+rate is encoded directly (zero-overhead path).
        needsResample = probe.channels != outChannels or probe.sampleRate != outRate
        resampler: Optional[AudioResampler] = AudioResampler(layout=outLayout, rate=outRate) if needsResample else None

        encodedSamples = 0
        try:
            for frame in inContainer.decode(audio=0):
                # Resample each decoded frame to the target channels+rate, then
                # encode every output frame. The resampler may emit 0 or N
                # frames per input (swresample buffers internally).
                outFrames = [frame] if resampler is None else resampler.resample(frame)
                for outFrame in outFrames:
                    try:
                        for packet in outStream.encode(outFrame):
                            outContainer.mux(packet)
                    except av.error.FFmpegError as exc:
                        raise EncoderError(f"{outCodec} encode failed: {exc}") from exc
                    encodedSamples += outFrame.samples
            # Flush the resampler (emits buffered tail frames), then flush the
            # encoder (emits delayed packets; preserves tail samples).
            if resampler is not None:
                for outFrame in resampler.resample(None):
                    try:
                        for packet in outStream.encode(outFrame):
                            outContainer.mux(packet)
                    except av.error.FFmpegError as exc:
                        raise EncoderError(f"{outCodec} encode failed: {exc}") from exc
                    encodedSamples += outFrame.samples
            try:
                for packet in outStream.encode(None):
                    outContainer.mux(packet)
            except av.error.FFmpegError as exc:
                raise EncoderError(f"{outCodec} flush failed: {exc}") from exc
        except av.error.FFmpegError as exc:
            raise AudioDecodeError(f"source decode failed: {exc}") from exc

        # Finalize the muxer (flush + write trailer). A failure here is an
        # encoder/muxer failure (not a decode failure), so it maps to
        # EncoderError. The error is captured and outContainer is cleared so the
        # ``finally`` below does not double-close a half-finalized container.
        muxerFinalizeError: Optional[av.error.FFmpegError] = None
        try:
            outContainer.close()
        except av.error.FFmpegError as exc:
            muxerFinalizeError = exc
        finally:
            # Clear the reference unconditionally (success, FFmpegError, or any
            # unexpected exception from close()) so the outer ``finally`` never
            # double-closes a half-finalized container.
            outContainer = None
        if muxerFinalizeError is not None:
            raise EncoderError(f"{outCodec} muxer finalize failed: {muxerFinalizeError}") from muxerFinalizeError
        outBytes = outBuffer.getvalue()
    finally:
        if outContainer is not None:
            outContainer.close()
        if inContainer is not None:
            inContainer.close()

    # durationMs from the actual encoded sample count at the OUTPUT rate (the
    # resampled frames fed to the encoder carry outRate samples each).
    durationMs = int(round(encodedSamples * 1000 / outRate))

    return ExtractedAudio(
        container=target.container,
        channels=outChannels,
        sampleRate=outRate,
        data=outBytes,
        durationMs=durationMs,
    )


def _measureDuration(
    sourceBytes: bytes,
    sampleRate: int,
) -> int:
    """Decode-count source samples to measure an accurate duration.

    Used by the pass-through path (which returns the original compressed bytes
    but still needs a sample-count-derived duration, not container metadata
    alone). Frames are discarded as they are counted, so no large PCM buffer
    accumulates.

    Args:
        sourceBytes: The source container bytes.
        sampleRate: Source sample rate in Hz.

    Returns:
        int: The measured duration in milliseconds.

    Raises:
        AudioDecodeError: The source is corrupt/truncated mid-decode.
    """
    container = None
    try:
        try:
            container = av.open(BytesIO(sourceBytes), mode="r")
        except av.error.FFmpegError as exc:
            raise AudioDecodeError(f"failed to open source container: {exc}") from exc

        sampleCount = 0
        try:
            sampleCount = sum(frame.samples for frame in container.decode(audio=0))
        except av.error.FFmpegError as exc:
            raise AudioDecodeError(f"source decode failed: {exc}") from exc

        return int(round(sampleCount / sampleRate * 1000))
    finally:
        if container is not None:
            container.close()


def _firstAudioStream(container: InputContainer) -> Optional[AudioStream]:
    """Return the first audio stream in the container, or ``None``.

    Args:
        container: An open PyAV input container.

    Returns:
        The first stream whose ``type`` is ``"audio"``, or ``None`` when the
        container holds no audio stream (e.g. a video-only file).
    """
    for stream in container.streams:
        if stream.type == "audio":
            return cast(AudioStream, stream)
    return None


def _mapContainerType(formatName: str, codecName: str) -> Optional[STTAudioContainerType]:
    """Map a PyAV container/format name + codec to an inline container type.

    PyAV reports the underlying FFmpeg demuxer name, which for the three inline
    containers is exactly ``"wav"`` / ``"ogg"`` / ``"mp3"``. Some demuxers report
    a comma-separated alias list (e.g. ``"mov,mp4,m4a,3gp,3g2,mj2"``); those never
    alias one of the three inline containers and route to the transcode path.

    The OGG mapping additionally requires ``codecName == "opus"``: an OGG
    container may hold a Vorbis (or other) stream, which must NOT be mislabelled
    OGG_OPUS (it would pass through and fail provider-side decode). A non-opus OGG
    stream falls through to ``None`` and routes to the transcode path. WAV and MP3
    are mapped on the format name alone (their demuxers imply the codec family).

    Args:
        formatName: The ``container.format.name`` reported by PyAV.
        codecName: The ``audioStream.codec_context.name`` reported by PyAV (e.g.
            ``"opus"`` / ``"vorbis"`` / ``"pcm_s16le"`` / ``"mp3float"``).

    Returns:
        The matching :class:`STTAudioContainerType`, or ``None`` when the source
        container is decodable but not one of the three inline containers (e.g.
        a Vorbis-in-OGG source).
    """
    tokens = {token.strip().lower() for token in formatName.split(",")}
    if "wav" in tokens:
        return STTAudioContainerType.WAV
    if "ogg" in tokens and codecName.lower() == "opus":
        return STTAudioContainerType.OGG_OPUS
    if "mp3" in tokens:
        return STTAudioContainerType.MP3
    return None


def _matchFormatSpec(
    container: Optional[STTAudioContainerType],
    channels: int,
    sampleRate: int,
    formats: Sequence[AudioFormatSpec],
) -> Optional[AudioFormatSpec]:
    """Find the provider spec matching the source container AND channel/rate range.

    Args:
        container: The mapped source container (``None`` never matches).
        channels: Source channel count.
        sampleRate: Source sample rate in Hz.
        formats: The provider's ordered accepted input formats.

    Returns:
        The first matching :class:`AudioFormatSpec`, or ``None`` when the source
        container is unsupported or its channels/rate fall outside the spec.
    """
    if container is None:
        return None
    for spec in formats:
        if (
            spec.container == container
            and spec.minChannels <= channels <= spec.maxChannels
            and spec.minSampleRate <= sampleRate <= spec.maxSampleRate
        ):
            return spec
    return None


def _chooseTranscodeTarget(formats: Sequence[AudioFormatSpec]) -> Optional[AudioFormatSpec]:
    """Pick the transcode target spec: the provider's first supported compressed format.

    The provider's preferred transcode target is the first ``supportedInputFormats``
    entry whose container is compressed (OGG_OPUS/MP3) — OGG_OPUS first for Yandex.
    The FULL spec (including its channel/sample-rate limits) is returned, not just
    the container, so the transcode path can clamp the source channels/sample rate
    to the provider's declared limits before encoding (§5).

    Args:
        formats: The provider's ordered accepted input formats.

    Returns:
        The first compressed :class:`AudioFormatSpec` in ``formats``, or ``None``
        when the provider accepts no compressed container (in which case transcode
        is impossible and the caller raises :class:`EncoderError`).
    """
    for spec in formats:
        if spec.container in _COMPRESSED_TARGETS:
            return spec
    return None


def _layoutForChannels(channels: int) -> str:
    """Return the PyAV channel layout name for a clamped channel count.

    The caller (:func:`_transcode`) clamps the source channels to the target
    spec's ``[minChannels, maxChannels]`` range BEFORE calling this, so
    ``channels`` is normally 1 or 2. Both transcode targets (libopus /
    libmp3lame) support at most 2 channels; a spec with ``maxChannels > 2`` is
    rejected up front in :func:`_transcode` (the codec cannot honour it), so
    this guard is a defense-in-depth backstop against a future caller that
    bypasses the clamp — it rejects an invalid count as a clean typed
    :class:`EncoderError` rather than emitting a positional ``"Nc"`` layout
    string FFmpeg does not recognise.

    Args:
        channels: Clamped output channel count (1 or 2 in normal operation).

    Returns:
        The PyAV layout name: ``"mono"`` for 1 channel or ``"stereo"`` for 2.

    Raises:
        EncoderError: ``channels`` is not positive or exceeds 2 (opus/mp3 cannot
            encode it; the spec ceiling is enforced in :func:`_transcode`).
    """
    if channels <= 0:
        raise EncoderError(f"cannot transcode a source with {channels} channels")
    if channels > 2:
        raise EncoderError(f"cannot transcode to {channels} channels: opus/mp3 support at most 2 channels")
    if channels == 1:
        return "mono"
    return "stereo"
