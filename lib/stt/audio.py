"""PyAV-based audio extraction with provider-driven format negotiation for lib.stt.

This module owns the only runtime raise-point inside ``lib/stt``
(load-bearing contract #2, ``docs/plans/lib-stt-v1.md`` §4/§5): the coroutine
:func:`extractAudio`. It downloads nothing itself — it invokes the
service-supplied typed :data:`~lib.stt.models.STTMediaLoader` to obtain the
source bytes, then probes them with PyAV, negotiates one of three paths
(pass-through / transcode / reject) against the provider's
``supportedInputFormats`` and the caps, and returns an
:class:`~lib.stt.models.ExtractedAudio`.

Key invariants (all from §5):
- **Caps are parameters, not config.** ``extractAudio`` receives
  ``maxSourceBytes``, ``maxDurationSeconds``, ``maxAudioBytes`` and
  ``maxInlineBytes``; it never reads ``[stt]`` config (the dependency firewall,
  §1; caps ownership, contract #3).
- **Always preserve source channels; never downmix** (hard rule). Both the
  pass-through and transcode paths carry the source channel count unchanged.
- **Duration is measured from the actual sample count**, not container metadata
  alone, on every path.
- **All blocking PyAV work runs in** :func:`asyncio.to_thread`, and a ``finally``
  block closes BOTH the input and output PyAV containers on every path —
  success, exception, and cancellation.
- Each typed exception maps 1:1 to an :class:`~lib.stt.models.STTErrorCode`
  (via the class-level ``errorCode``) so ``STTService`` can map the failure
  category without re-mapping.

Guarded import (load-bearing contract #6, §2): PyAV is imported with the
project-approved module-level ``try/except ImportError`` and a private
``_PYAV_AVAILABLE`` flag. When STT is enabled, a missing PyAV is a startup error
handled by ``STTService`` (§11.2); if :func:`extractAudio` is nonetheless
reached without PyAV it raises :class:`~lib.stt.exceptions.AudioDecodeError`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from typing import Dict, Optional, Tuple, cast

try:
    import av
    import av.error
    from av.audio.stream import AudioStream
    from av.container import InputContainer

    _PYAV_AVAILABLE = True
except ImportError:
    _PYAV_AVAILABLE = False

from lib.stt.exceptions import (
    AudioDecodeError,
    AudioTooLargeError,
    DurationExceededError,
    EncoderError,
    NoAudioTrackError,
    SourceTooLargeError,
)
from lib.stt.models import (
    AudioFormatSpec,
    ExtractedAudio,
    STTAudioContainerType,
    STTMediaLoader,
)

#: Compressed container targets the transcode path may encode to, in preference
#: order. The transcode path picks the provider's first ``supportedInputFormats``
#: entry whose container is in this tuple (OGG_OPUS for Yandex).
_COMPRESSED_TARGETS: Tuple[STTAudioContainerType, ...] = (
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

#: Number of bytes per decoded PCM sample per channel (signed 16-bit, the format
#: the decoded-buffer cap formula assumes: ``duration * channels * sampleRate * 2``).
_BYTES_PER_SAMPLE_PER_CHANNEL = 2


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
    loader: STTMediaLoader,
    supportedInputFormats: Tuple[AudioFormatSpec, ...],
    maxSourceBytes: int,
    maxDurationSeconds: int,
    maxAudioBytes: int,
    maxInlineBytes: int,
) -> ExtractedAudio:
    """Extract and negotiate audio for a provider.

    Invokes the service-supplied ``loader`` (which closes over the platform
    identifiers and receives ``maxSourceBytes`` as its byte bound), defensively
    rechecks the returned source size, then runs the blocking PyAV probe +
    negotiation in :func:`asyncio.to_thread`. Raises a typed
    :class:`~lib.stt.exceptions.STTExtractionError` (each mapping 1:1 to an
    :class:`~lib.stt.models.STTErrorCode`) for every expected extraction failure;
    never returns ``None``.

    Args:
        loader: The service-supplied bounded media loader
            (:data:`~lib.stt.models.STTMediaLoader`). It receives ``maxSourceBytes``
            and returns the source bytes; ``lib/stt`` never imports platform
            download code (dependency-firewall seam #2).
        supportedInputFormats: The provider's ordered accepted input formats (the
            negotiation surface consumed here). The FIRST compressed entry
            (OGG_OPUS/MP3) is the transcode target.
        maxSourceBytes: Source-container byte cap (defensive recheck at entry).
        maxDurationSeconds: Decoded-duration cap in seconds. Rejects
            (``DurationExceededError``) on the pass-through path; stop-at-cap on
            the transcode path.
        maxAudioBytes: Decoded in-memory PCM cap in bytes
            (``duration * channels * sampleRate * 2``), enforced during every
            decode step (channel-aware).
        maxInlineBytes: Inline-payload cap in bytes bounding ``ExtractedAudio.data``
            (base64-expanded into the submit body). Drives the pass-through-vs-
            transcode decision and the post-encode check.

    Returns:
        ExtractedAudio: The negotiated, format-aware audio handed to the provider.

    Raises:
        SourceTooLargeError: The returned source byte length exceeds
            ``maxSourceBytes``.
        NoAudioTrackError: The source has no decodable audio stream.
        AudioDecodeError: The source is corrupt/truncated or PyAV is unavailable.
        DurationExceededError: Measured duration exceeds ``maxDurationSeconds`` on
            the pass-through path (compressed audio cannot be truncated without a
            re-encode).
        AudioTooLargeError: The decoded in-memory buffer exceeds
            ``maxAudioBytes``, or a transcoded payload exceeds ``maxInlineBytes``.
        EncoderError: No compressed transcode target is available, or the
            encoder/muxer failed.
    """
    if not _PYAV_AVAILABLE:
        raise AudioDecodeError("PyAV (av) is not available; cannot extract audio")

    # The loader closes over platform identifiers and receives the byte bound;
    # it is awaited outside the thread because it is itself async.
    loaderResult = await loader(maxSourceBytes)

    # Step 1: defensive source-byte recheck (the primary bound is owned by the
    # STTService loader/admission; this is the lib/stt backstop).
    sourceBytes = loaderResult.data
    if loaderResult.fileSize > maxSourceBytes or len(sourceBytes) > maxSourceBytes:
        raise SourceTooLargeError(f"source size {loaderResult.fileSize} bytes exceeds maxSourceBytes {maxSourceBytes}")

    return await asyncio.to_thread(
        _extractBlocking,
        sourceBytes,
        supportedInputFormats,
        maxDurationSeconds,
        maxAudioBytes,
        maxInlineBytes,
    )


def _extractBlocking(
    sourceBytes: bytes,
    supportedInputFormats: Tuple[AudioFormatSpec, ...],
    maxDurationSeconds: int,
    maxAudioBytes: int,
    maxInlineBytes: int,
) -> ExtractedAudio:
    """Run the probe + negotiation + path execution in a worker thread.

    Args:
        sourceBytes: The downloaded source container bytes (already rechecked).
        supportedInputFormats: The provider's ordered accepted input formats.
        maxDurationSeconds: Decoded-duration cap in seconds.
        maxAudioBytes: Decoded in-memory PCM cap in bytes.
        maxInlineBytes: Inline-payload cap in bytes.

    Returns:
        ExtractedAudio: The negotiated audio.

    Raises:
        STTExtractionError: A typed extraction failure (see :func:`extractAudio`).
    """
    probe = _probe(sourceBytes)

    matchedSpec = _matchFormatSpec(probe.container, probe.channels, probe.sampleRate, supportedInputFormats)
    inlineFits = len(sourceBytes) <= maxInlineBytes

    if matchedSpec is not None and inlineFits:
        # Step 4 — pass-through path: container supported, channels/rate in range,
        # and the source payload fits the inline cap.
        return _passthrough(sourceBytes, probe, maxDurationSeconds, maxAudioBytes)

    # Step 4 — transcode path: source container unsupported, or supported but the
    # payload exceeds the inline cap. Stop-at-duration-cap instead of rejecting.
    target = _chooseTranscodeTarget(supportedInputFormats)
    if target is None:
        raise EncoderError("no compressed transcode target available in supportedInputFormats")
    return _transcode(sourceBytes, probe, target, maxDurationSeconds, maxAudioBytes, maxInlineBytes)


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
    maxDurationSeconds: int,
    maxAudioBytes: int,
) -> ExtractedAudio:
    """Pass-through path: return the source bytes in their original container.

    Decodes the source purely to measure duration from the actual sample count
    (§5 step 3 — not container metadata alone) and to enforce the decoded-buffer
    and duration caps. Compressed audio cannot be truncated without a re-encode,
    so an over-cap duration is rejected (``DurationExceededError``) rather than
    silently truncated. Source channels and sample rate are preserved unchanged.

    Args:
        sourceBytes: The original source container bytes (returned verbatim).
        probe: The header probe result (container, channels, sample rate).
        maxDurationSeconds: Decoded-duration cap in seconds.
        maxAudioBytes: Decoded in-memory PCM cap in bytes.

    Returns:
        ExtractedAudio: The source bytes wrapped with the source container,
        preserved channels/sample rate, and the measured duration.

    Raises:
        AudioDecodeError: The source is corrupt/truncated mid-decode.
        AudioTooLargeError: The decoded buffer exceeds ``maxAudioBytes``.
        DurationExceededError: The measured duration exceeds ``maxDurationSeconds``.
    """
    durationMs, exceeded = _measureDurationAndEnforceCaps(
        sourceBytes, probe.channels, probe.sampleRate, maxDurationSeconds, maxAudioBytes
    )
    if exceeded:
        raise DurationExceededError(f"measured duration exceeds the {maxDurationSeconds}s cap on the pass-through path")
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
    target: STTAudioContainerType,
    maxDurationSeconds: int,
    maxAudioBytes: int,
    maxInlineBytes: int,
) -> ExtractedAudio:
    """Transcode path: decode the source and re-encode to a compressed container.

    Encodes to ``target`` (the provider's first supported compressed format —
    OGG_OPUS for Yandex), **channel-preserving** (no downmix), stopping at the
    duration cap during encode so an over-cap source is truncated rather than
    rejected. Enforces the decoded-buffer cap during decode. After encode, the
    inline-payload cap is rechecked (a transcoded payload may still exceed it).

    Args:
        sourceBytes: The source container bytes.
        probe: The header probe result (container, channels, sample rate).
        target: The transcode target container (OGG_OPUS or MP3).
        maxDurationSeconds: Decoded-duration cap in seconds (stop-at-cap).
        maxAudioBytes: Decoded in-memory PCM cap in bytes.
        maxInlineBytes: Inline-payload cap in bytes (post-encode check).

    Returns:
        ExtractedAudio: The re-encoded bytes with the target container, preserved
        source channel count, the target sample rate, and the (capped) duration.

    Raises:
        AudioDecodeError: The source is corrupt/truncated mid-decode.
        AudioTooLargeError: The decoded buffer exceeds ``maxAudioBytes``, or the
            transcoded payload exceeds ``maxInlineBytes``.
        EncoderError: The encoder/muxer failed.
    """
    outCodec = _CODEC_FOR_CONTAINER[target]
    outFormat = _FORMAT_FOR_CONTAINER[target]
    outRate = _OPUS_NATIVE_RATE if target is STTAudioContainerType.OGG_OPUS else probe.sampleRate

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
            # Validate the layout here (after both containers are open) so a
            # >2-channel source raises EncoderError and the outer ``finally``
            # still closes both containers — no leak when the encoder rejects the
            # source mid-configuration (§5; opus/mp3 support <= 2 channels and
            # the never-downmix hard rule makes >2-channel unrecoverable).
            outStream.layout = _layoutForChannels(probe.channels)
            if target is STTAudioContainerType.OGG_OPUS:
                # 'voip' is the appropriate application for speech recognition.
                # Gated on the enum (the authoritative signal), not the codec name.
                outStream.options = {"application": "voip"}
        except av.error.FFmpegError as exc:
            raise EncoderError(f"failed to configure {outCodec} encoder: {exc}") from exc

        encodedSamples = 0
        capSamples = maxDurationSeconds * probe.sampleRate
        try:
            for frame in inContainer.decode(audio=0):
                # Stop-at-duration-cap: do not encode past the cap.
                if encodedSamples + frame.samples > capSamples:
                    break
                # Enforce the decoded-buffer cap during decode (channel-aware).
                if (encodedSamples + frame.samples) * probe.channels * _BYTES_PER_SAMPLE_PER_CHANNEL > maxAudioBytes:
                    raise AudioTooLargeError(f"decoded buffer exceeds maxAudioBytes {maxAudioBytes} during transcode")
                try:
                    for packet in outStream.encode(frame):
                        outContainer.mux(packet)
                except av.error.FFmpegError as exc:
                    raise EncoderError(f"{outCodec} encode failed: {exc}") from exc
                encodedSamples += frame.samples
            # Flush the encoder (emits delayed packets; preserves tail samples).
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
        outContainer = None
        if muxerFinalizeError is not None:
            raise EncoderError(f"{outCodec} muxer finalize failed: {muxerFinalizeError}") from muxerFinalizeError
        outBytes = outBuffer.getvalue()
    finally:
        if outContainer is not None:
            outContainer.close()
        if inContainer is not None:
            inContainer.close()

    # Post-encode inline-payload cap (§5 caps table: drives the decision AND the
    # post-encode check).
    if len(outBytes) > maxInlineBytes:
        raise AudioTooLargeError(f"transcoded payload {len(outBytes)} bytes exceeds maxInlineBytes {maxInlineBytes}")

    # durationMs from the actual encoded sample count (the source-rate samples we
    # fed to the encoder, capped). stoppedAtCap means we hit the duration cap, so
    # the reported duration is the capped portion.
    durationMs = int(round(encodedSamples * 1000 / probe.sampleRate))

    return ExtractedAudio(
        container=target,
        channels=probe.channels,
        sampleRate=outRate,
        data=outBytes,
        durationMs=durationMs,
    )


def _measureDurationAndEnforceCaps(
    sourceBytes: bytes,
    channels: int,
    sampleRate: int,
    maxDurationSeconds: int,
    maxAudioBytes: int,
) -> Tuple[int, bool]:
    """Decode-count source samples to measure duration, enforcing caps.

    Used by the pass-through path (which returns the original compressed bytes
    but still needs an accurate, sample-count-derived duration). Frames are
    discarded as they are counted, so no large PCM buffer accumulates; the
    decoded-buffer cap is enforced incrementally as a channel-aware policy bound
    (§5 step 5). Counting stops as soon as the duration cap is crossed (returns
    ``exceeded=True``) since the caller rejects over-cap durations anyway.

    Args:
        sourceBytes: The source container bytes.
        channels: Source channel count.
        sampleRate: Source sample rate in Hz.
        maxDurationSeconds: Decoded-duration cap in seconds.
        maxAudioBytes: Decoded in-memory PCM cap in bytes.

    Returns:
        Tuple[int, bool]: ``(durationMs, exceeded)`` where ``durationMs`` is the
        measured (or cap-crossing) duration in milliseconds and ``exceeded`` is
        ``True`` iff the source had more samples than the duration cap allows.

    Raises:
        AudioDecodeError: The source is corrupt/truncated mid-decode.
        AudioTooLargeError: The decoded-buffer cap is exceeded.
    """
    capSamples = maxDurationSeconds * sampleRate
    container = None
    try:
        try:
            container = av.open(BytesIO(sourceBytes), mode="r")
        except av.error.FFmpegError as exc:
            raise AudioDecodeError(f"failed to open source container: {exc}") from exc

        sampleCount = 0
        try:
            for frame in container.decode(audio=0):
                sampleCount += frame.samples
                # Decoded-buffer cap (channel-aware, §5 step 5).
                if sampleCount * channels * _BYTES_PER_SAMPLE_PER_CHANNEL > maxAudioBytes:
                    raise AudioTooLargeError(f"decoded buffer exceeds maxAudioBytes {maxAudioBytes}")
                # Duration cap: reject only when strictly OVER the cap (§5 step 4 —
                # "over the cap"). The decoded-buffer cap above already uses strict
                # `>`; this matches it so a source exactly at the cap is accepted.
                if sampleCount > capSamples:
                    return (int(round(sampleCount / sampleRate * 1000)), True)
        except av.error.FFmpegError as exc:
            raise AudioDecodeError(f"source decode failed: {exc}") from exc

        return (int(round(sampleCount / sampleRate * 1000)), False)
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
    formats: Tuple[AudioFormatSpec, ...],
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


def _chooseTranscodeTarget(formats: Tuple[AudioFormatSpec, ...]) -> Optional[STTAudioContainerType]:
    """Pick the transcode target: the provider's first supported compressed format.

    The provider's preferred transcode target is the first ``supportedInputFormats``
    entry whose container is compressed (OGG_OPUS/MP3) — OGG_OPUS first for Yandex.

    Args:
        formats: The provider's ordered accepted input formats.

    Returns:
        The first compressed container in ``formats``, or ``None`` when the
        provider accepts no compressed container (in which case transcode is
        impossible and the caller raises :class:`EncoderError`).
    """
    for spec in formats:
        if spec.container in _COMPRESSED_TARGETS:
            return spec.container
    return None


def _layoutForChannels(channels: int) -> str:
    """Return the PyAV channel layout name for a channel count.

    Both transcode targets (libopus / libmp3lame) support at most 2 channels, and
    the never-downmix hard rule (§5) makes a >2-channel source unrecoverable — it
    would fail at the encoder anyway, so it is rejected up front as a clean typed
    :class:`EncoderError` rather than emitting an invalid ``"Nc"`` layout string
    (FFmpeg does not recognise positional names like ``"3c"``).

    Args:
        channels: Source channel count (preserved through negotiation).

    Returns:
        The PyAV layout name: ``"mono"`` for 1 channel or ``"stereo"`` for 2.

    Raises:
        EncoderError: ``channels`` is not positive or exceeds 2 (opus/mp3 cannot
            encode it and the source is never downmixed).
    """
    if channels <= 0:
        raise EncoderError(f"cannot transcode a source with {channels} channels")
    if channels > 2:
        raise EncoderError(
            f"cannot transcode a {channels}-channel source: opus/mp3 support at most 2 channels "
            "and the never-downmix hard rule (§5) makes >2-channel unrecoverable"
        )
    if channels == 1:
        return "mono"
    return "stereo"
