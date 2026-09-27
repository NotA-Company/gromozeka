"""Image manipulation helpers for the AI/LLM vision pipelines.

This module centralizes every byte-level image operation used by the AI layer,
kept separate from the message models in :mod:`lib.ai.models` (which imports
from here — the dependency is one-directional, models -> imaging):

- VisionOutputImageFormat: StrEnum of the normalized storage formats
  (JPEG/PNG, native-vision design v1 §4).
- convertImageIfNeeded: send-time, per-model INPUT format conversion
  (never-raise; passthrough unless re-encoding to the first supported MIME
  is required).
- normalizeVisionImage / normalizeVisionImageStrict: receipt-time
  normalization for native-vision storage (resize cap, EXIF stripping,
  animated-frame collapse). The strict variant is the implementation and
  fails CLOSED (returns ``None``); the lenient one is a thin never-raise
  wrapper returning the original bytes on failure.
- _stripJpegExif: JPEG marker surgery backing the strict normalizer's
  EXIF lossless fast path (with its kept-APPn payload-identifier validation
  helper _isRecognizedAppSegmentPayload).

Example:
    >>> from lib.ai.imaging import convertImageIfNeeded  # doctest: +SKIP
    >>> converted, mime = convertImageIfNeeded(pngBytes, ["image/jpeg"])  # doctest: +SKIP
"""

import logging
from enum import StrEnum
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import magic
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Image format conversion helper
# ---------------------------------------------------------------------------

#: Maps an image MIME type to the Pillow ``Image.save`` format string.
#: Used by :func:`convertImageIfNeeded` to re-encode image bytes into a format
#: the target LLM accepts as vision input.
_MIME_TO_PIL_FORMAT: Dict[str, str] = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
    "image/gif": "GIF",
}


class VisionOutputImageFormat(StrEnum):
    """Output formats the vision normalizer may re-encode into.

    Deliberately NARROWER than the send-time INPUT formats in
    :data:`_MIME_TO_PIL_FORMAT` (which also serves
    :func:`convertImageIfNeeded` and accepts WebP/GIF): design v1 §4 defines
    only JPEG/PNG as normalized storage formats, and the normalizer fails
    (strict) or falls back to the original bytes (lenient) for anything else.

    Being a :class:`enum.StrEnum`, members ARE their MIME-string values, so
    raw config strings (``"image/jpeg"`` / ``"image/png"``) remain
    RUNTIME-compatible during the migration (dict lookups and equality
    against the members follow the string value); typed callers should
    construct and pass the enum members.

    Example:
        >>> print(VisionOutputImageFormat.PNG)
        image/png
    """

    #: JPEG output (the default): alpha flattened onto RGB, encoder
    #: controlled by ``quality``.
    JPEG = "image/jpeg"
    #: PNG output (lossless): alpha preserved, ``quality`` ignored.
    PNG = "image/png"


#: Output formats :func:`normalizeVisionImage` may re-encode into, mapped to
#: the Pillow ``Image.save`` format string. Deliberately NARROWER than
#: :data:`_MIME_TO_PIL_FORMAT` (which also serves :func:`convertImageIfNeeded`
#: and accepts WebP/GIF as send-time INPUT formats): design v1 §4 defines only
#: JPEG/PNG as normalized storage formats. Keyed by
#: :class:`VisionOutputImageFormat`; raw-string lookups still hit because
#: StrEnum members equal their values.
_VISION_OUTPUT_PIL_FORMATS: Dict[VisionOutputImageFormat, str] = {
    VisionOutputImageFormat.JPEG: "JPEG",
    VisionOutputImageFormat.PNG: "PNG",
}

#: Maximum pixel count (width × height) for an image we are willing to
#: re-encode for a vision request. Real vision inputs are never this large;
#: the cap bounds memory use on crafted decompression bombs BEFORE the
#: expensive decode runs. Pillow's own ``DecompressionBombError`` still fires
#: above ~2× its threshold and is caught by the broad except below. Scoped to
#: this function only — the global ``Image.MAX_IMAGE_PIXELS`` is left untouched
#: so other Pillow users in the process (e.g. python-telegram-bot) are unaffected.
MAX_VISION_IMAGE_PIXELS = 50_000_000  # 50 MP


def convertImageIfNeeded(imageBytes: bytes, supportedFormats: Optional[List[str]]) -> Tuple[bytes, str]:
    """Return image bytes in a MIME format the target model accepts, converting only when required.

    Detects the current MIME type of *imageBytes*. When *supportedFormats* is
    falsy (``None`` or empty) or already contains the detected MIME, the bytes
    are returned unchanged (passthrough). Otherwise the bytes are re-encoded to
    the FIRST entry in *supportedFormats* via Pillow.

    This function NEVER raises: any conversion failure (unreadable bytes,
    unknown target format, oversized image, Pillow error, or even a libmagic
    failure during MIME detection) is logged and the ORIGINAL bytes are
    returned unchanged so the caller can still attempt the request. When MIME
    detection itself fails the returned type is ``application/octet-stream``
    (honest about not knowing the type; the API will reject if it can't handle
    it).

    Args:
        imageBytes: Raw image bytes in any format Pillow can open.
        supportedFormats: Ordered list of acceptable input MIME types for the
            target model, e.g. ``["image/jpeg", "image/png"]``. ``None`` or an
            empty list disables conversion (passthrough). The first element is
            used as the conversion target when the current MIME is absent.

    Returns:
        A ``(finalBytes, finalMimeType)`` tuple where *finalBytes* is the
        (possibly converted) image bytes and *finalMimeType* is the MIME type
        of those bytes.
    """
    try:
        currentMime = magic.from_buffer(imageBytes, mime=True)
    except Exception:  # noqa: BLE001 — libmagic failure on malformed bytes; never-raise contract
        logger.exception("Failed to detect image MIME for conversion; sending original bytes")
        return (imageBytes, "application/octet-stream")
    if not supportedFormats or currentMime in supportedFormats:
        return (imageBytes, currentMime)

    targetMime = supportedFormats[0]
    pilFormat = _MIME_TO_PIL_FORMAT.get(targetMime)
    if pilFormat is None:
        logger.warning(
            f"Cannot convert image to unsupported target MIME {targetMime!r} "
            f"(current {currentMime!r}); sending original"
        )
        return (imageBytes, currentMime)
    try:
        logger.debug(
            f"Got image in {currentMime} format. " f"Supported formats: {supportedFormats}; converting to {targetMime}"
        )
        with BytesIO(imageBytes) as inBuf:
            img = Image.open(inBuf)
            # Cheap header read has populated width/height before any decode;
            # reject oversized images so the (memory-expensive) decode never
            # runs. Scoped cap — the global Image.MAX_IMAGE_PIXELS is NOT mutated.
            if img.width * img.height > MAX_VISION_IMAGE_PIXELS:
                logger.error(
                    f"Image too large to convert ({img.width}x{img.height}="
                    f"{img.width * img.height} pixels > {MAX_VISION_IMAGE_PIXELS}); "
                    f"current={currentMime!r} target={targetMime!r}"
                )
                return (imageBytes, currentMime)
            # JPEG has no alpha channel; flatten onto an RGB canvas first so
            # Pillow can encode transparency-bearing sources (PNG/WebP) into JPEG.
            if targetMime == "image/jpeg":
                img = img.convert("RGB")
            with BytesIO() as outBuf:
                img.save(outBuf, format=pilFormat)
                converted = outBuf.getvalue()
        return (converted, targetMime)
    except Exception:  # noqa: BLE001 — graceful degradation is the contract
        logger.exception(
            f"Failed to convert image from {currentMime!r} to {targetMime!r}; " f"returning original bytes unchanged"
        )
        return (imageBytes, currentMime)


#: Recognised payload identifiers for KEPT APPn segments (APP0-APP15), keyed
#: by marker byte. Per ITU-T T.871 / the Adobe & ICC specs: APP0 JFIF/JFXX,
#: APP1 XMP (the Adobe namespace URI prefix — the standard XMP segment uses
#: ``http://ns.adobe.com/xap/1.0/\\x00``; the shorter namespace prefix is
#: accepted), APP2 ``ICC_PROFILE\\x00``, APP14 ``Adobe``. APP3-APP13/APP15
#: have no standard payload identifier. Used by :func:`_stripJpegExif` to
#: validate that every KEPT APPn segment really is what its marker claims —
#: see that function's docstring for why (understated-length resync).
_APPN_RECOGNIZED_PAYLOAD_PREFIXES: Dict[int, Tuple[bytes, ...]] = {
    0xE0: (b"JFIF\x00", b"JFXX\x00"),
    0xE1: (b"http://ns.adobe.com/",),
    0xE2: (b"ICC_PROFILE\x00",),
    0xEE: (b"Adobe",),
}


def _isRecognizedAppSegmentPayload(marker: int, payload: bytes) -> bool:
    """Return whether a KEPT APPn segment's payload starts with a standard identifier.

    Args:
        marker: APPn marker byte (``0xE0``-``0xEF``).
        payload: The segment payload (everything after the 2-byte length
            field).

    Returns:
        True when *payload* starts with one of the recognised identifiers
        for *marker* (see :data:`_APPN_RECOGNIZED_PAYLOAD_PREFIXES`);
        False for unknown markers (APP3-APP13/APP15), too-short payloads,
        or non-matching identifiers.
    """
    return any(payload.startswith(prefix) for prefix in _APPN_RECOGNIZED_PAYLOAD_PREFIXES.get(marker, ()))


def _stripJpegExif(imageBytes: bytes) -> Optional[bytes]:
    """Surgically remove EXIF APP1 segments from JPEG bytes WITHOUT re-encoding.

    Walks the JPEG marker stream and rebuilds it, dropping every APP1
    (``FF E1``) segment whose payload starts with ``Exif\\x00\\x00`` — the
    segment type that wholly carries the EXIF/TIFF metadata block (GPS and
    device tags included). XMP APP1 segments (``http://ns.adobe.com/xap/1.0/``
    identifier) and APP2/ICC color profiles are KEPT, as are the other
    standard APPn payloads (JFIF/JFXX APP0, Adobe APP14) — every KEPT APPn
    must start with its standard identifier (see
    :data:`_APPN_RECOGNIZED_PAYLOAD_PREFIXES`), otherwise the stream is
    declined. The walk understands this canonical layout:

    - ``FF D8`` (SOI) must open the stream;
    - each following segment is ``FF <marker>`` plus a 2-byte big-endian
      length field that INCLUDES itself but not the marker;
    - standalone markers without a length field (``FF 01`` TEM,
      ``FF D0``-``FF D7`` RST0-7) are copied as bare 2-byte markers;
    - at ``FF DA`` (SOS) the length-bearing header is copied, then the
      entropy-coded scan is walked to its terminating ``FF D9`` (EOI).
      EXIF APP1 segments can also hide AFTER the first scan (multi-scan
      streams), so any other marker encountered inside the scan
      (``APPn``/``COM``/``DHT``/a second ``SOS``...) marks a structure this
      surgery does not strip and yields ``None`` — the caller's re-encode
      fallback strips everything instead. Byte stuffing (``FF 00``) and
      restart markers inside the scan are skipped via a C-speed
      ``bytes.find``-driven walk; the scan bytes are copied verbatim;
    - ``FF D9`` (EOI) terminates the image wherever it appears — after a
      scan or header-level (scanless stream); trailing bytes after it are
      not image data and are dropped, so the result always ends at the EOI.

    Because the scan data is never touched, the decoded pixels of the result
    are BIT-IDENTICAL to the input's — this is what distinguishes the surgery
    from a Pillow re-encode (generational quality loss). ORIENTATION CAVEAT:
    dropping the EXIF block also drops the orientation tag, so the CALLER must
    only use this surgery when the orientation is absent or identity (1);
    otherwise the shipped pixels would display rotated/mirrored in decoders
    that ignore EXIF. This function does not enforce that — it is metadata
    surgery only.

    Any structural anomaly (missing SOI, fill bytes, a truncated or
    overrunning segment length, non-marker garbage, a scan that never
    reaches EOI, an unstrippable marker inside the scan, or a KEPT APPn
    segment whose payload does not start with its standard identifier)
    yields ``None`` — "surgery not applicable" — and the caller falls back
    to the full re-encode pipeline. The identifier validation closes the
    understated-length hole: a declared segment length SHORTER than the
    real segment would otherwise let the walk silently resync mid-payload,
    reading raw payload bytes as segments (a bogus resynced "APPn" never
    carries a recognised identifier, so the mangled stream is declined
    instead of shipped — the fast path's decode gate validates the INPUT
    stream, never the surgery output). Pure byte arithmetic; Pillow is
    never involved and the function NEVER raises.

    Args:
        imageBytes: Raw bytes supposedly holding a JPEG image.

    Returns:
        The JPEG bytes with every EXIF APP1 segment removed (everything else
        byte-identical), or ``None`` when the marker stream is not one this
        surgery fully understands.
    """
    total = len(imageBytes)
    if total < 4 or imageBytes[:2] != b"\xff\xd8":
        return None
    out = bytearray(imageBytes[:2])
    pos = 2
    while pos + 2 <= total:
        if imageBytes[pos] != 0xFF:
            return None  # non-marker garbage between segments
        marker = imageBytes[pos + 1]
        if marker == 0xFF:
            return None  # fill bytes — not the canonical single-0xFF marker form
        if marker == 0xD9:  # EOI before SOS: scanless stream; image ends here
            out += imageBytes[pos : pos + 2]
            # Trailing bytes after the EOI are not image data; drop them —
            # same contract as the scan-level EOI branch below.
            return bytes(out)
        if marker == 0xDA:  # SOS: copy its header, then walk the scan to EOI
            if pos + 4 > total:
                return None
            segLen = int.from_bytes(imageBytes[pos + 2 : pos + 4], "big")
            if segLen < 2 or pos + 2 + segLen > total:
                return None
            out += imageBytes[pos : pos + 2 + segLen]
            scanPos = pos + 2 + segLen
            # Walk the entropy-coded scan: EXIF APP1 segments can also hide
            # AFTER the first scan (multi-scan streams), so the walk must
            # reach the EOI classifying every 0xFF — anything except byte
            # stuffing, restart markers, fill bytes and the EOI itself means
            # a structure this surgery does not strip → not applicable.
            while True:
                ff = imageBytes.find(b"\xff", scanPos)
                if ff < 0 or ff + 1 >= total:
                    return None  # scan never terminated by EOI
                nextByte = imageBytes[ff + 1]
                if nextByte == 0x00 or 0xD0 <= nextByte <= 0xD7:
                    # Byte-stuffed FF or restart marker: scan continues.
                    out += imageBytes[scanPos : ff + 2]
                    scanPos = ff + 2
                elif nextByte == 0xFF:
                    # Fill byte before the next real marker.
                    out += imageBytes[scanPos : ff + 1]
                    scanPos = ff + 1
                elif nextByte == 0xD9:
                    # EOI terminates the image. Trailing bytes after it are
                    # not image data and are dropped.
                    out += imageBytes[scanPos:ff] + b"\xff\xd9"
                    return bytes(out)
                else:
                    # Inter-scan marker segment (APPn/COM/DHT/SOS...): a
                    # structure whose EXIF this surgery cannot fully strip.
                    return None
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            # Standalone markers (TEM / RST0-7) carry no length field.
            out += imageBytes[pos : pos + 2]
            pos += 2
            continue
        # Length-bearing metadata segment.
        if pos + 4 > total:
            return None
        segLen = int.from_bytes(imageBytes[pos + 2 : pos + 4], "big")
        if segLen < 2 or pos + 2 + segLen > total:
            return None
        if marker == 0xE1 and imageBytes[pos + 4 : pos + 10] == b"Exif\x00\x00":
            pass  # EXIF APP1 — dropped (GPS/device-data privacy property)
        else:
            if 0xE0 <= marker <= 0xEF and not _isRecognizedAppSegmentPayload(
                marker, imageBytes[pos + 4 : pos + 2 + segLen]
            ):
                # KEPT APPn without its standard payload identifier: a
                # structural anomaly. This closes the understated-length
                # hole — a declared length ending mid-payload would
                # otherwise let the walk silently resync and classify raw
                # payload bytes as segments, shipping mangled output.
                return None
            out += imageBytes[pos : pos + 2 + segLen]
        pos += 2 + segLen
    else:
        # The walk ran off the end without reaching SOS/EOI: the marker
        # stream is not one this surgery fully understands.
        return None
    # Unreachable: the loop above returns on EOI (both header-level and
    # scan-level) and its else-clause returns on exhaustion — every path
    # out of the walk has already produced a result.


def normalizeVisionImage(
    imageBytes: bytes,
    maxDimension: int = 2048,
    outputFormat: VisionOutputImageFormat = VisionOutputImageFormat.JPEG,
    quality: int = 85,
) -> Tuple[bytes, str]:
    """Normalize raw image bytes for storage as a native-vision attachment.

    Lenient, never-raise wrapper around :func:`normalizeVisionImageStrict` —
    see that function for the full pipeline description. Intended to run ONCE
    at receipt time (before storing), unlike :func:`convertImageIfNeeded`
    which runs at send time per target model.

    This function NEVER raises: whenever strict normalization fails (returns
    ``None``), the ORIGINAL bytes are returned unchanged so the caller can
    still store/parse them. When MIME detection itself fails the returned
    type is ``application/octet-stream``. Because the fallback is
    indistinguishable from success by inspecting the result alone,
    STORAGE callers must use :func:`normalizeVisionImageStrict` instead:
    storing the fallback would publish oversized, EXIF-bearing originals.

    Args:
        imageBytes: Raw image bytes in any format Pillow can open.
        maxDimension: Pixel cap for the long edge; never upscales.
            ``0`` disables resizing. Defaults to 2048.
        outputFormat: Target format; only
            :class:`VisionOutputImageFormat` JPEG/PNG re-encode (JPEG is
            the default). Anything else degrades to a passthrough of the
            original bytes.
        quality: JPEG encoder quality (1-95); values outside the range
            are clamped into it with a logged warning. Ignored for PNG.

    Returns:
        A ``(normalizedBytes, mimeType)`` tuple where *normalizedBytes*
        is the (possibly original) image bytes and *mimeType* is the MIME
        type of those bytes — *outputFormat* on success, the detected
        source MIME on graceful degradation.
    """
    result = normalizeVisionImageStrict(
        imageBytes=imageBytes,
        maxDimension=maxDimension,
        outputFormat=outputFormat,
        quality=quality,
    )
    if result is not None:
        return result
    logger.warning(
        f"Vision normalization failed (outputFormat={str(outputFormat)!r}, maxDimension={maxDimension}); "
        f"returning ORIGINAL image bytes ({len(imageBytes)} bytes) unchanged"
    )
    # Graceful degradation per the never-raise contract: hand back the
    # ORIGINAL bytes tagged with the best MIME we can detect for them.
    try:
        return (imageBytes, magic.from_buffer(imageBytes, mime=True))
    except Exception:  # noqa: BLE001 — never-raise contract on libmagic failure
        return (imageBytes, "application/octet-stream")


def normalizeVisionImageStrict(
    imageBytes: bytes,
    maxDimension: int = 2048,
    outputFormat: VisionOutputImageFormat = VisionOutputImageFormat.JPEG,
    quality: int = 85,
) -> Optional[Tuple[bytes, str]]:
    """Normalize raw image bytes for vision, FAILING CLOSED on any problem.

    The normalization pipeline (shared contract with the lenient wrapper
    :func:`normalizeVisionImage`, which degrades to the original bytes where
    this function returns ``None``):

    - RGB JPEG sources that need no resize and carry identity orientation
      take a LOSSLESS fast path: the image is decoded once as a decodability
      gate, the EXIF APP1 segment(s) are surgically removed from the
      compressed bytes (:func:`_stripJpegExif`) and the ORIGINAL scan data is
      returned — zero generational quality loss (only the re-encode is
      skipped, never the decode, so truncated/undecodable streams still fail
      closed exactly like the full pipeline). The fast path is restricted to
      mode ``RGB``: the full pipeline converts every other pixel mode
      (grayscale, CMYK, ...) to RGB during the re-encode, so their original
      component layouts must not ship unchanged to vision providers. If the
      marker surgery is not applicable (structurally unrecognisable stream),
      a warning is logged and the full decode/re-encode pipeline below runs
      instead; PNG sources never take the fast path (their re-encode is
      lossless already);
    - Animated sources (GIF/WebP stickers) collapse to the FIRST frame;
    - EXIF orientation (e.g. 6/8 from portrait phone shots) is baked into
      the pixel layout via ``ImageOps.exif_transpose`` so the image is not
      left sideways once the metadata is stripped;
    - The image is downscaled so the LONG side is at most *maxDimension*
      pixels using LANCZOS resampling; it is NEVER upscaled. When
      *maxDimension* is ``0`` the resize step is skipped entirely
      (``0 = no resize``, see ``configs/00-defaults/vision.toml``).
      Palette/bilevel sources (modes ``P``/``1``) are converted to RGB/RGBA
      BEFORE resizing, because Pillow silently forces NEAREST resampling
      for those modes and would ignore the LANCZOS request;
    - The image is re-encoded to *outputFormat*; for JPEG an alpha channel
      is flattened onto RGB and *quality* controls the encoder (values
      outside 1-95 are clamped into range with a logged warning — Pillow
      itself accepts out-of-range integers). The re-save also drops EXIF
      metadata (GPS/device data) as a deliberate privacy property;
    - The same decompression-bomb guard as :func:`convertImageIfNeeded`
      (:data:`MAX_VISION_IMAGE_PIXELS`, 50 MP) rejects crafted oversized
      images BEFORE the expensive decode runs.

    Unlike the lenient wrapper this function reports success explicitly:
    instead of degrading to the original bytes, it returns ``None``
    whenever normalization did not fully succeed (MIME detection failure,
    unsupported target format, oversized image rejected by the
    :data:`MAX_VISION_IMAGE_PIXELS` guard, or a Pillow error). Every
    failure is logged; the function NEVER raises.

    Storage callers (the receipt-time vision store) MUST use this variant:
    the lenient fallback returned by :func:`normalizeVisionImage` may be
    oversized and still carry EXIF metadata — the re-encode is what strips
    it — and send-time delivery does no resize, so storing the fallback
    would break both the pixel cap and the EXIF privacy promise.

    Args:
        imageBytes: Raw image bytes in any format Pillow can open.
        maxDimension: Pixel cap for the long edge; never upscales.
            ``0`` disables resizing. Defaults to 2048.
        outputFormat: Target format; only
            :class:`VisionOutputImageFormat` JPEG/PNG re-encode (JPEG is
            the default).
        quality: JPEG encoder quality (1-95); values outside the range
            are clamped into it with a logged warning. Ignored for PNG.

    Returns:
        A ``(normalizedBytes, outputFormat)`` tuple on success, or
        ``None`` when normalization failed for any reason.
    """
    try:
        currentMime = magic.from_buffer(imageBytes, mime=True)
    except Exception:  # noqa: BLE001 — libmagic failure on malformed bytes; fail closed
        logger.exception("Failed to detect image MIME for vision normalization; normalization failed")
        return None

    pilFormat = _VISION_OUTPUT_PIL_FORMATS.get(outputFormat)
    if pilFormat is None:
        logger.warning(
            f"Cannot normalize image to unsupported target MIME {outputFormat!r} "
            f"(current {currentMime!r}); normalization failed"
        )
        return None

    try:
        logger.debug(f"Normalizing image for vision: {currentMime} -> {outputFormat} (maxDimension={maxDimension})")
        with BytesIO(imageBytes) as inBuf:
            img = Image.open(inBuf)
            # Cheap header read has populated width/height before any decode;
            # reject oversized images so the (memory-expensive) decode never
            # runs. Scoped cap — the global Image.MAX_IMAGE_PIXELS is NOT
            # mutated. MUST stay before ImageOps.exif_transpose below, which
            # decodes pixels.
            if img.width * img.height > MAX_VISION_IMAGE_PIXELS:
                logger.error(
                    f"Image too large to normalize for vision ({img.width}x{img.height}="
                    f"{img.width * img.height} pixels > {MAX_VISION_IMAGE_PIXELS}); "
                    f"current={currentMime!r} target={outputFormat!r}"
                )
                return None
            # --- EXIF lossless fast path (marker surgery, no re-encode) ---
            # Eligibility, evaluated in order:
            #   (1) detected source is JPEG AND the output target is JPEG;
            #   (2) no resize needed: maxDimension == 0 (resize disabled) or
            #       the header-reported long side already fits the cap — with
            #       identity orientation (checked below) the pre/post-transpose
            #       dimensions agree, so the header numbers are authoritative;
            #   (3) the pixel mode is RGB: the full pipeline converts every
            #       other mode (grayscale, CMYK, ...) to RGB on re-encode, so
            #       their original component layouts must not ship unchanged;
            #       mode is available from the header-opened image — no pixel
            #       decode;
            #   (4) EXIF orientation absent or == 1 (0x0112 read from the
            #       header — no pixel decode): values 2-8 disqualify, because
            #       dropping the tag would ship rotated/mirrored pixels that
            #       EXIF-ignoring decoders render sideways;
            #   (5) the marker surgery itself succeeds. A surgery failure is
            #       NOT a normalization failure: warn and fall through to the
            #       full re-encode pipeline below, which strips EXIF anyway.
            # On success the ORIGINAL compressed scan data ships minus the
            # Exif APP1 segment(s) — zero generational quality loss. PNG
            # never takes a fast path (its re-encode is lossless already).
            try:
                if currentMime == "image/jpeg" and outputFormat == VisionOutputImageFormat.JPEG:
                    if maxDimension == 0 or max(img.width, img.height) <= maxDimension:
                        orientation = img.getexif().get(0x0112)
                        if img.mode == "RGB" and (orientation is None or orientation == 1):
                            # Decodability gate: the strict contract must not
                            # accept bytes the re-encode pipeline would
                            # reject. Header parsing (and the marker surgery
                            # below) never decodes pixels, so a JPEG
                            # truncated mid-scan could otherwise ship as
                            # "success"; decoding once here preserves the
                            # fail-closed behaviour at a fraction of the
                            # normal path's cost (no resize, no re-encode).
                            img.load()
                            fastPathBytes = _stripJpegExif(imageBytes)
                            if fastPathBytes is not None:
                                logger.debug(
                                    f"EXIF fast path: dropped JPEG metadata without re-encoding "
                                    f"({len(imageBytes)} -> {len(fastPathBytes)} bytes)"
                                )
                                return (fastPathBytes, outputFormat)
                            logger.warning(
                                "EXIF fast path not applicable (unrecognised JPEG marker structure); "
                                "falling back to the full normalization pipeline"
                            )
            except Exception:  # noqa: BLE001 — the fast path must never fail normalization
                logger.exception("EXIF fast path probe failed; falling back to the full normalization pipeline")
            # Animated content (GIF/WebP stickers): keep the first frame only.
            if getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1:
                img.seek(0)
            # Bake EXIF orientation into the pixels BEFORE stripping metadata:
            # portrait phone shots carry orientation 6/8 while the stored
            # pixel layout stays landscape, so a plain re-save would produce
            # a sideways image with no tag left to explain it. exif_transpose
            # returns a new image with the transform applied (and DECODES
            # pixels — hence it runs after the guard above).
            transposed = ImageOps.exif_transpose(img)
            if transposed is not None:
                img = transposed
            # Palette/bilevel sources: Pillow silently forces NEAREST
            # resampling for modes "P" and "1", ignoring the LANCZOS request
            # in the resize below. Convert to truecolor BEFORE resizing
            # (keeping the alpha channel when the palette carries
            # transparency) so the requested resampler actually applies.
            if img.mode == "P":
                img = img.convert("RGBA" if "transparency" in img.info else "RGB")
            elif img.mode == "1":
                img = img.convert("RGB")
            # Downscale so the long edge is at most maxDimension; never
            # upscale. maxDimension == 0 disables the resize step.
            longSide = max(img.width, img.height)
            if maxDimension > 0 and longSide > maxDimension:
                scale = maxDimension / longSide
                newWidth = max(1, round(img.width * scale))
                newHeight = max(1, round(img.height * scale))
                img = img.resize((newWidth, newHeight), Image.Resampling.LANCZOS)
            # JPEG has no alpha channel; flatten onto an RGB canvas first so
            # Pillow can encode transparency-bearing sources (PNG/WebP) into JPEG.
            if outputFormat == "image/jpeg":
                img = img.convert("RGB")
            # Pillow's JPEG encoder accepts integer qualities outside the
            # documented 1-95 band (e.g. 96-100 save without error), so
            # out-of-range values are clamped explicitly, with a warning
            # when an adjustment happens. Inside the guarded path so the
            # never-raise contract holds even for pathological input.
            effectiveQuality = quality
            if outputFormat == "image/jpeg" and not 1 <= quality <= 95:
                effectiveQuality = min(95, max(1, quality))
                logger.warning(f"JPEG quality {quality} outside 1-95; clamped to {effectiveQuality}")
            with BytesIO() as outBuf:
                # Saving without an ``exif`` argument strips ALL EXIF metadata
                # (GPS/device data) — the orientation tag was already consumed
                # by exif_transpose above.
                if outputFormat == "image/jpeg":
                    img.save(outBuf, format=pilFormat, quality=effectiveQuality)
                else:
                    img.save(outBuf, format=pilFormat)
                normalized = outBuf.getvalue()
        return (normalized, outputFormat)
    except Exception:  # noqa: BLE001 — fail-closed contract: report None, never raise
        logger.exception(f"Failed to normalize image for vision from {currentMime!r} to {outputFormat!r}")
        return None
