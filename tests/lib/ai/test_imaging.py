"""Tests for the image-manipulation helpers in lib.ai.imaging.

Covers:
- normalizeVisionImage (review refactor): thin lenient wrapper around the
  strict entry point — the never-raise fallback (original bytes returned on
  any failure) with a logged WARNING on the fallback path; long-edge resize
  cap with LANCZOS, never upscaling, maxDimension=0 disabling the resize,
  animated sources collapsing to the first frame, alpha flattening for JPEG,
  PNG output, EXIF stripping, EXIF orientation 6/8 baked into the pixel
  layout, palette/bilevel sources converted to truecolor before resizing so
  LANCZOS applies, the JPEG/PNG-only output contract, JPEG quality clamping
  into 1-95, and the never-raise contract (original bytes returned on corrupt
  input, unsupported target format, oversized-header rejection BEFORE
  decode, MIME-detection failure, and encoder failure — the latter three
  via mocks).
- normalizeVisionImageStrict (review refactor): the full pipeline inline,
  failing CLOSED — every lenient fallback branch (oversized-header
  rejection, corrupt input, unsupported target format, MIME-detection
  failure, encoder failure) must yield None so the receipt-time store can
  skip storage instead of publishing oversized / EXIF-bearing originals;
  except-block failures log via ``logger.exception`` so tracebacks are kept.
- VisionOutputImageFormat (review refactor): StrEnum value contract —
  members equal (and hash equal to) their ``image/*`` MIME strings, so
  raw-string callers keep working at runtime until migrated; JPEG/PNG are
  the only members (design v1 §4).
- _stripJpegExif (Wave C): marker-surgery contract — EXIF APP1 dropped with
  every other chunk byte-identical, XMP APP1 kept verbatim, and ``None``
  (surgery not applicable) on every structural anomaly (missing SOI,
  overrunning segment length, non-marker garbage, an understated segment
  length whose silent resync is caught by kept-APPn payload validation,
  unrecognized APPn payloads, and non-JFIF/JFXX APP0).
- normalizeVisionImageStrict EXIF lossless fast path (Wave C): eligible JPEGs
  (JPEG→JPEG, no resize needed, orientation absent/1) ship the original scan
  data minus the Exif APP1(s) with decoded pixels bit-identical; orientation
  6, over-cap, and PNG-input/output cases take the normal pipeline; an
  EXIF-free JPEG round-trips byte-identically; a corrupt marker stream warns
  and still normalizes via the fallback re-encode; XMP APP1 survives.
"""

import logging
from io import BytesIO
from typing import Dict, List, Optional, Tuple, cast
from unittest.mock import MagicMock, Mock

import pytest
from PIL import Image, ImageOps

from lib.ai.imaging import (
    VisionOutputImageFormat,
    _stripJpegExif,
    normalizeVisionImage,
    normalizeVisionImageStrict,
)

# ============================================================================
# normalizeVisionImage — native-vision Phase 1a normalization helper
# ============================================================================


_JPEG_MIME = "image/jpeg"
_PNG_MIME = "image/png"


def _jpegBytesOfSize(width: int, height: int) -> bytes:
    """Return a valid JPEG image of the requested size (solid red).

    Args:
        width: Image width in pixels.
        height: Image height in pixels.

    Returns:
        bytes of a JPEG-encoded image.
    """
    buf = BytesIO()
    Image.new("RGB", (width, height), (255, 0, 0)).save(buf, format="JPEG")
    return buf.getvalue()


def _rgbaPngBytesOfSize(width: int, height: int) -> bytes:
    """Return a valid RGBA PNG (red at 50% alpha) of the requested size.

    The non-full alpha channel exercises the RGB-flatten branch of
    :func:`normalizeVisionImage` when the target format is JPEG.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.

    Returns:
        bytes of an RGBA PNG-encoded image.
    """
    buf = BytesIO()
    Image.new("RGBA", (width, height), (255, 0, 0, 128)).save(buf, format="PNG")
    return buf.getvalue()


def _animatedGifBytes() -> bytes:
    """Return a 2-frame animated GIF (frame 0 red, frame 1 blue).

    Returns:
        bytes of an animated GIF-encoded image.
    """
    frame0 = Image.new("RGB", (20, 10), (255, 0, 0))
    frame1 = Image.new("RGB", (20, 10), (0, 0, 255))
    buf = BytesIO()
    frame0.save(buf, format="GIF", save_all=True, append_images=[frame1], duration=100, loop=0)
    return buf.getvalue()


def _jpegBytesWithExifTags(width: int, height: int, tags: Dict[int, object]) -> bytes:
    """Return JPEG bytes with a red-left/blue-right layout and EXIF tags set.

    The asymmetric layout lets orientation tests assert pixel PLACEMENT
    after transposition (not just dimensions); the EXIF tags let metadata
    tests assert stripping and let small/zero-cap tests prove that a
    re-encode happened rather than a passthrough.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        tags: Mapping of EXIF tag IDs to values (e.g. ``{0x0112: 6}`` for
            orientation, ``{0x010F: "TestCameraMaker"}`` for Make).

    Returns:
        bytes of a JPEG-encoded image carrying the requested EXIF tags.
    """
    img = Image.new("RGB", (width, height), (0, 0, 255))
    img.paste((255, 0, 0), (0, 0, width // 2, height))
    exif = Image.Exif()
    for tagId, value in tags.items():
        exif[tagId] = value
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _jpegBytesOfModeWithExifTags(width: int, height: int, mode: str, tags: Dict[int, object]) -> bytes:
    """Return JPEG bytes in the requested Pillow mode with EXIF tags set.

    A solid single-color source (red for ``"RGB"``/``"CMYK"``, mid-gray for
    ``"L"``) — the minimal fixture for the EXIF fast path's RGB-only mode
    gate.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        mode: Pillow mode of the source image (``"RGB"``, ``"L"``, or
            ``"CMYK"``).
        tags: Mapping of EXIF tag IDs to values (e.g.
            ``{0x010F: "TestCameraMaker"}`` for Make).

    Returns:
        bytes of a JPEG-encoded image in the requested mode carrying the
        requested EXIF tags.
    """
    if mode == "L":
        img: Image.Image = Image.new("L", (width, height), 128)
    elif mode == "CMYK":
        img = Image.new("CMYK", (width, height), (0, 255, 255, 0))
    else:
        img = Image.new("RGB", (width, height), (255, 0, 0))
    exif = Image.Exif()
    for tagId, value in tags.items():
        exif[tagId] = value
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _checkerboardPaletteGifBytes(size: int = 8) -> bytes:
    """Return a palette-mode (P) GIF with a 1px black/white checkerboard.

    A 1px checkerboard downscaled 2x is the LANCZOS/NEAREST discriminator:
    LANCZOS averages each 2x2 source block (2 black + 2 white) to mid-gray,
    while NEAREST keeps pure black/white pixels.

    Args:
        size: Side length in pixels (default 8, so a 4x4 output at 2x
            downscale).

    Returns:
        bytes of a GIF-encoded palette-mode image.
    """
    rgb = Image.new("RGB", (size, size), (0, 0, 0))
    for y in range(size):
        for x in range(size):
            if (x + y) % 2 == 1:
                rgb.putpixel((x, y), (255, 255, 255))
    buf = BytesIO()
    rgb.convert("P", palette=Image.Palette.ADAPTIVE).save(buf, format="GIF")
    return buf.getvalue()


def _checkerboardBilevelPngBytes(size: int = 8) -> bytes:
    """Return a bilevel (mode "1") PNG with a 1px black/white checkerboard.

    Same LANCZOS/NEAREST discriminator as :func:`_checkerboardPaletteGifBytes`,
    for the ``"1"`` mode branch of the truecolor pre-conversion.

    Args:
        size: Side length in pixels (default 8).

    Returns:
        bytes of a PNG-encoded bilevel image.
    """
    img = Image.new("1", (size, size), 0)
    for y in range(size):
        for x in range(size):
            if (x + y) % 2 == 1:
                img.putpixel((x, y), 1)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _splitJpegSegments(data: bytes) -> List[Tuple[Optional[int], bytes]]:
    """Parse a JPEG marker stream into (marker, rawChunk) tuples for assertions.

    One entry per marker segment: ``(0xD8, b"\\xff\\xd8")`` SOI first, then
    one ``(marker, chunk)`` per length-bearing segment (chunk includes the
    marker and length bytes), and standalone markers (TEM/RST) as bare 2-byte
    chunks. The walk ends at whichever terminator comes first: a
    header-level EOI (scanless stream) becomes a ``(0xD9, chunk)`` entry,
    while a SOS header gets its own entry followed by a final ``(None, ...)``
    entry holding EVERYTHING after the SOS header — the entropy-coded scan
    data including its terminating EOI, which therefore never gets its own
    entry. Raises AssertionError on non-marker garbage so a malformed
    fixture fails loudly instead of producing a bogus expectation.

    Args:
        data: JPEG byte stream to parse.

    Returns:
        List of (marker byte or None, raw chunk bytes) in stream order.
    """
    assert data[:2] == b"\xff\xd8"
    chunks: List[Tuple[Optional[int], bytes]] = [(0xD8, data[:2])]
    pos = 2
    while pos + 2 <= len(data):
        assert data[pos] == 0xFF, f"non-marker garbage at offset {pos}"
        marker = data[pos + 1]
        if marker == 0xD9:
            chunks.append((0xD9, data[pos : pos + 2]))
            return chunks
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            chunks.append((marker, data[pos : pos + 2]))
            pos += 2
            continue
        segLen = int.from_bytes(data[pos + 2 : pos + 4], "big")
        chunks.append((marker, data[pos : pos + 2 + segLen]))
        pos += 2 + segLen
        if marker == 0xDA:
            chunks.append((None, data[pos:]))
            return chunks
    return chunks


def _isExifApp1(entry: Tuple[Optional[int], bytes]) -> bool:
    """Return whether a parsed chunk is the EXIF-bearing APP1 segment.

    Args:
        entry: A (marker, chunk) tuple from :func:`_splitJpegSegments`.

    Returns:
        True when the chunk is an APP1 whose payload starts with the
        ``Exif\\x00\\x00`` identifier.
    """
    marker, chunk = entry
    return marker == 0xE1 and chunk[4:10] == b"Exif\x00\x00"


def _app1Segment(payload: bytes) -> bytes:
    """Wrap a payload (identifier header included) into a raw APP1 segment.

    Args:
        payload: Segment payload; its identifier header (e.g. ``Exif\\x00\\x00``
            or the XMP namespace URI) must already be prefixed.

    Returns:
        The full segment: marker + big-endian length (including the length
        bytes) + payload.
    """
    return b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload


class TestVisionOutputImageFormat:
    """Tests for the :class:`VisionOutputImageFormat` StrEnum contract.

    The enum IS the output-format contract (StrEnum over Literal per repo
    rule); its value identity is what keeps raw-string callers working at
    runtime during the bot-layer migration.
    """

    def testMembersEqualTheirMimeStringValues(self) -> None:
        """Members compare (and hash) equal to their ``image/*`` MIME values.

        Dict lookups in the normalizer (``_VISION_OUTPUT_PIL_FORMATS``) and
        equality checks against raw config strings rely on this StrEnum
        value semantics.

        Returns:
            None
        """
        assert VisionOutputImageFormat.JPEG == "image/jpeg"
        assert VisionOutputImageFormat.PNG == "image/png"
        assert str(VisionOutputImageFormat.JPEG) == "image/jpeg"
        assert str(VisionOutputImageFormat.PNG) == "image/png"
        # Hash equality is what lets a raw string hit an enum-keyed dict.
        assert hash(VisionOutputImageFormat.PNG) == hash("image/png")

    def testMembersAreTheOnlyContractValues(self) -> None:
        """Exactly JPEG/PNG exist — design v1 §4 normalized storage formats.

        Returns:
            None
        """
        assert {member.value for member in VisionOutputImageFormat} == {"image/jpeg", "image/png"}


class TestNormalizeVisionImage:
    """Tests for :func:`lib.ai.imaging.normalizeVisionImage` (Phase 1a infra)."""

    def testOversizeImageResizedToCapOnLongSide(self) -> None:
        """A 300x200 image with maxDimension=100 is downscaled to 100x67.

        The long edge is capped exactly; the short edge follows the aspect
        ratio (round(200 * 100/300) == 67). Output re-decodes as JPEG.

        Returns:
            None
        """
        original = _jpegBytesOfSize(300, 200)

        result, mime = normalizeVisionImage(original, maxDimension=100)

        assert mime == _JPEG_MIME
        assert result != original
        out = Image.open(BytesIO(result))
        assert out.format == "JPEG"
        assert out.size == (100, 67)
        out.load()

    def testSmallImageNotUpscaled(self) -> None:
        """A 50x30 image with maxDimension=100 keeps its original size.

        Never-upscale contract: dimensions must be untouched even though the
        cap is larger than the image. The input carries EXIF metadata and the
        assertions additionally require successful re-encoding (bytes differ,
        EXIF stripped), so a no-op passthrough implementation cannot pass.

        Returns:
            None
        """
        original = _jpegBytesWithExifTags(50, 30, {0x010F: "TestCameraMaker"})
        # Sanity: the fixture really carries metadata before normalization.
        srcExif = Image.open(BytesIO(original)).getexif()
        assert srcExif.get(0x010F) == "TestCameraMaker"

        result, mime = normalizeVisionImage(original, maxDimension=100)

        assert mime == _JPEG_MIME
        assert result != original
        out = Image.open(BytesIO(result))
        assert out.size == (50, 30)
        outExif = out.getexif()
        assert outExif.get(0x010F) is None
        assert len(outExif) == 0
        out.load()

    def testMaxDimensionZeroDisablesResize(self) -> None:
        """maxDimension=0 skips the resize step entirely (design §4 comment).

        An oversize (relative to any cap) image passes through with its
        original dimensions when the cap is disabled. Metadata-bearing input:
        skipping the resize must not imply skipping the RE-ENCODE, so EXIF
        stripping (and byte inequality) is asserted too.

        Returns:
            None
        """
        original = _jpegBytesWithExifTags(300, 200, {0x010F: "TestCameraMaker"})

        result, mime = normalizeVisionImage(original, maxDimension=0)

        assert mime == _JPEG_MIME
        assert result != original
        out = Image.open(BytesIO(result))
        assert out.size == (300, 200)
        outExif = out.getexif()
        assert outExif.get(0x010F) is None
        assert len(outExif) == 0
        out.load()

    def testRgbaPngFlattenedToJpeg(self) -> None:
        """An RGBA PNG is flattened to RGB and re-encoded as JPEG.

        Without the alpha flatten the JPEG encode would fail; the test pins
        that the flatten branch runs and produces a valid, decodable JPEG.

        Returns:
            None
        """
        original = _rgbaPngBytesOfSize(8, 8)

        result, mime = normalizeVisionImage(original, maxDimension=2048)

        assert mime == _JPEG_MIME
        assert result != original
        out = Image.open(BytesIO(result))
        assert out.format == "JPEG"
        assert out.mode == "RGB"
        out.load()

    def testAnimatedGifCollapsesToFirstFrame(self) -> None:
        """A 2-frame GIF normalizes to a single-frame JPEG of frame 0.

        Frame 0 is red, frame 1 is blue; the output pixel must be red-ish
        (JPEG encoding perturbs colors slightly) and the output must not be
        animated.

        Returns:
            None
        """
        original = _animatedGifBytes()
        # Sanity: the fixture really is animated before normalization.
        src = Image.open(BytesIO(original))
        assert getattr(src, "is_animated", False) is True

        result, mime = normalizeVisionImage(original, maxDimension=2048)

        assert mime == _JPEG_MIME
        out = Image.open(BytesIO(result))
        assert out.format == "JPEG"
        assert getattr(out, "is_animated", False) is False
        assert getattr(out, "n_frames", 1) == 1
        pixel = out.convert("RGB").getpixel((0, 0))
        assert isinstance(pixel, tuple) and len(pixel) >= 3
        red, green, blue = pixel[0], pixel[1], pixel[2]
        assert red > 200 and green < 60 and blue < 60, f"expected frame-0 red, got {pixel}"
        out.load()

    def testConfiguredPngOutput(self) -> None:
        """VisionOutputImageFormat.PNG yields PNG bytes and the image/png MIME.

        Returns:
            None
        """
        original = _jpegBytesOfSize(10, 10)

        result, mime = normalizeVisionImage(original, maxDimension=2048, outputFormat=VisionOutputImageFormat.PNG)

        assert mime == _PNG_MIME
        assert result != original
        out = Image.open(BytesIO(result))
        assert out.format == "PNG"
        out.load()

    def testExifDroppedByResave(self) -> None:
        """EXIF metadata (e.g. GPS/device tags) does not survive normalization.

        The Pillow re-save never passes an ``exif`` argument, so the output
        carries an empty EXIF block — the design's documented privacy property.

        Returns:
            None
        """
        buf = BytesIO()
        img = Image.new("RGB", (16, 16), (0, 128, 0))
        exif = Image.Exif()
        exif[0x010F] = "TestCameraMaker"  # Make tag
        img.save(buf, format="JPEG", exif=exif)
        original = buf.getvalue()
        # Sanity: the fixture really carries EXIF before normalization.
        srcExif = Image.open(BytesIO(original)).getexif()
        assert srcExif.get(0x010F) == "TestCameraMaker"

        result, mime = normalizeVisionImage(original, maxDimension=2048)

        assert mime == _JPEG_MIME
        outExif = Image.open(BytesIO(result)).getexif()
        assert outExif.get(0x010F) is None
        assert len(outExif) == 0

    def testCorruptBytesReturnsOriginalWithoutRaising(self, caplog: pytest.LogCaptureFixture) -> None:
        """Corrupt input that Pillow cannot open is returned unchanged with an error logged.

        Args:
            caplog: pytest fixture capturing log records.

        Returns:
            None
        """
        corrupt = b"\x00\x01\x02\x03not-an-image-at-all-garbage"
        with caplog.at_level(logging.ERROR, logger="lib.ai.imaging"):
            result, mime = normalizeVisionImage(corrupt, maxDimension=100)
        # Original bytes returned untouched (graceful degradation; never raises).
        assert result == corrupt
        assert any(record.levelno == logging.ERROR for record in caplog.records)

    @pytest.mark.parametrize("outputFormat", ["image/webp", "image/gif", "image/bmp"])
    def testUnsupportedOutputFormatReturnsOriginal(self, outputFormat: str, caplog: pytest.LogCaptureFixture) -> None:
        """A non-member output value degrades gracefully at runtime.

        Normalization output is restricted to JPEG/PNG
        (:class:`VisionOutputImageFormat`, design v1 §4) even though the
        shared ``_MIME_TO_PIL_FORMAT`` also maps WebP/GIF — those are
        accepted as send-time INPUT formats by :func:`convertImageIfNeeded`,
        never as normalized storage formats. This test passes RAW STRINGS
        (``cast`` past the enum annotation) on purpose: callers feeding
        config strings directly must keep degrading gracefully at runtime
        until they migrate to the enum. Original bytes are returned
        unchanged with the detected source MIME and a WARNING (not ERROR)
        is logged.

        Args:
            outputFormat: Unsupported target MIME under test.
            caplog: pytest fixture capturing log records.

        Returns:
            None
        """
        original = _jpegBytesOfSize(10, 10)
        with caplog.at_level(logging.WARNING, logger="lib.ai.imaging"):
            result, mime = normalizeVisionImage(
                original, maxDimension=100, outputFormat=cast(VisionOutputImageFormat, outputFormat)
            )
        assert result == original
        assert mime == _JPEG_MIME
        assert any(record.levelno == logging.WARNING for record in caplog.records)
        assert outputFormat in caplog.text

    @pytest.mark.parametrize(
        ("orientation", "topIsRed"),
        [(6, True), (8, False)],
    )
    def testExifOrientationAppliedToPixels(self, orientation: int, topIsRed: bool) -> None:
        """EXIF orientation 6/8 is baked into the pixels; metadata is dropped.

        A stored 40x20 image (left half red, right half blue) with
        orientation 6 ("rotate 90° CW to display") must normalize to 20x40
        with red on TOP; orientation 8 ("rotate 90° CCW") must put red on
        the BOTTOM — the two are only distinguishable via pixel placement.
        Dimensions, placement, and EXIF absence are all asserted.

        Args:
            orientation: EXIF orientation tag value under test.
            topIsRed: Whether the output's top half must be red.

        Returns:
            None
        """
        original = _jpegBytesWithExifTags(40, 20, {0x0112: orientation})
        # Sanity: the fixture really carries the orientation tag.
        srcExif = Image.open(BytesIO(original)).getexif()
        assert srcExif.get(0x0112) == orientation

        result, mime = normalizeVisionImage(original, maxDimension=2048)

        assert mime == _JPEG_MIME
        out = Image.open(BytesIO(result))
        assert out.format == "JPEG"
        assert out.size == (20, 40)
        # EXIF absence: orientation tag (and everything else) must be gone.
        outExif = out.getexif()
        assert outExif.get(0x0112) is None
        assert len(outExif) == 0
        # Pixel placement: sample mid-way inside each half (10px from the
        # y=20 boundary), JPEG-tolerant channel-dominance assertions.
        rgb = out.convert("RGB")
        topPixel = rgb.getpixel((10, 10))
        bottomPixel = rgb.getpixel((10, 30))
        for label, pixel, expectRed in (("top", topPixel, topIsRed), ("bottom", bottomPixel, not topIsRed)):
            assert isinstance(pixel, tuple) and len(pixel) >= 3
            red, green, blue = pixel[0], pixel[1], pixel[2]
            if expectRed:
                assert red > 200 and green < 60 and blue < 60, f"expected red-ish {label}, got {pixel}"
            else:
                assert blue > 200 and red < 60 and green < 60, f"expected blue-ish {label}, got {pixel}"
        out.load()

    @pytest.mark.parametrize(
        "fixtureName",
        ["paletteGif", "bilevelPng"],
    )
    def testPaletteAndBilevelDownscaledWithLanczos(self, fixtureName: str) -> None:
        """P/1 sources are converted to truecolor BEFORE resizing so LANCZOS applies.

        Pillow silently forces NEAREST resampling for modes "P" and "1". A
        1px checkerboard downscaled 8x8 -> 4x4 under LANCZOS averages each
        2x2 source block to mid-gray; under NEAREST the pixels would stay
        pure black/white, so this test fails if the pre-conversion is
        removed. PNG output keeps the values lossless.

        Args:
            fixtureName: Which checkerboard fixture to drive (palette GIF or
                bilevel PNG).

        Returns:
            None
        """
        fixtures: Dict[str, bytes] = {
            "paletteGif": _checkerboardPaletteGifBytes(8),
            "bilevelPng": _checkerboardBilevelPngBytes(8),
        }
        expectedModes: Dict[str, str] = {"paletteGif": "P", "bilevelPng": "1"}
        original = fixtures[fixtureName]
        # Sanity: the fixture really is in the palette/bilevel mode under test.
        assert Image.open(BytesIO(original)).mode == expectedModes[fixtureName]

        result, mime = normalizeVisionImage(original, maxDimension=4, outputFormat=VisionOutputImageFormat.PNG)

        assert mime == _PNG_MIME
        out = Image.open(BytesIO(result))
        assert out.format == "PNG"
        assert out.size == (4, 4)
        rgb = out.convert("RGB")
        for y in range(4):
            for x in range(4):
                pixel = rgb.getpixel((x, y))
                assert isinstance(pixel, tuple) and len(pixel) >= 3
                red, green, blue = pixel[0], pixel[1], pixel[2]
                # Neutral gray (channels aligned)...
                assert abs(red - green) <= 12 and abs(green - blue) <= 12, f"expected gray at {(x, y)}, got {pixel}"
                # ...and mid-tone: LANCZOS averaging; NEAREST would give 0/255.
                assert 96 <= red <= 160, f"expected mid-gray (LANCZOS) at {(x, y)}, got {pixel}"
        out.load()

    def testOversizeRejectedBeforeDecode(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The 50MP guard rejects via header dimensions BEFORE any decode.

        ``Image.open`` is mocked to report 10000x10000 (100 MP > 50 MP cap)
        from its cheap header read; ``ImageOps.exif_transpose`` (the first
        decode-forcing pipeline step) and the image's own ``load`` must
        never be invoked.

        Args:
            caplog: pytest fixture capturing log records.
            monkeypatch: pytest fixture for temporary attribute patching.

        Returns:
            None
        """
        original = _jpegBytesOfSize(10, 10)
        mockImg = MagicMock()
        mockImg.width = 10_000
        mockImg.height = 10_000
        openMock = Mock(return_value=mockImg)
        transposeMock = Mock()
        monkeypatch.setattr(Image, "open", openMock)
        monkeypatch.setattr(ImageOps, "exif_transpose", transposeMock)

        with caplog.at_level(logging.ERROR, logger="lib.ai.imaging"):
            result, mime = normalizeVisionImage(original, maxDimension=100)

        assert result == original
        assert mime == _JPEG_MIME
        openMock.assert_called_once()  # header read happened...
        transposeMock.assert_not_called()  # ...but no pixel work followed
        mockImg.load.assert_not_called()  # decode never ran
        assert "too large" in caplog.text
        assert any(record.levelno == logging.ERROR for record in caplog.records)

    def testMimeDetectionFailureReturnsOctetStreamFallback(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A libmagic failure returns the original bytes as application/octet-stream.

        Distinct failure point from corrupt bytes: MIME DETECTION itself
        raises, so the pipeline must bail out before even attempting to
        open the image — with the honest unknown-type fallback MIME.

        Args:
            caplog: pytest fixture capturing log records.
            monkeypatch: pytest fixture for temporary attribute patching.

        Returns:
            None
        """
        original = b"\x00\x01payload-that-is-never-inspected"

        def failingFromBuffer(*args: object, **kwargs: object) -> str:
            """Stub raising the simulated libmagic failure.

            Args:
                *args: Positional call arguments (ignored).
                **kwargs: Keyword call arguments (ignored).

            Returns:
                Never returns; always raises OSError.

            Raises:
                OSError: The simulated libmagic failure.
            """
            raise OSError("simulated libmagic failure")

        monkeypatch.setattr("lib.ai.imaging.magic.from_buffer", failingFromBuffer)

        with caplog.at_level(logging.ERROR, logger="lib.ai.imaging"):
            result, mime = normalizeVisionImage(original)

        assert result == original
        assert mime == "application/octet-stream"
        assert any(record.levelno == logging.ERROR for record in caplog.records)

    def testEncoderFailureReturnsOriginalBytes(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A Pillow encoder failure on valid input returns the original bytes.

        ``Image.Image.save`` is patched to raise after the input has been
        built (fixture creation happens BEFORE the patch), pinning the
        graceful-degradation path for a valid, openable, in-cap image whose
        re-encode blows up. The fixture is OVER the resize cap so the image
        takes the re-encode pipeline (an EXIF-free under-cap JPEG would take
        the lossless fast path and never reach the encoder).

        Args:
            caplog: pytest fixture capturing log records.
            monkeypatch: pytest fixture for temporary attribute patching.

        Returns:
            None
        """
        original = _jpegBytesOfSize(300, 200)
        saveMock = Mock(side_effect=OSError("simulated encoder failure"))
        monkeypatch.setattr(Image.Image, "save", saveMock)

        with caplog.at_level(logging.ERROR, logger="lib.ai.imaging"):
            result, mime = normalizeVisionImage(original, maxDimension=100)

        assert result == original
        assert mime == _JPEG_MIME
        saveMock.assert_called_once()
        assert any(record.levelno == logging.ERROR for record in caplog.records)

    @pytest.mark.parametrize(
        ("quality", "expectedClamped"),
        [(0, 1), (100, 95)],
    )
    def testJpegQualityClampedIntoValidRange(
        self, quality: int, expectedClamped: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        """JPEG quality outside 1-95 is clamped with a logged warning.

        Pillow's JPEG encoder ACCEPTS integers outside the documented band
        (96-100 save without error), so no exception enforces the project
        range: both boundaries (0 -> 1, 100 -> 95) must be clamped
        explicitly, produce a valid image, and warn. The fixture is OVER the
        resize cap so the image takes the re-encode pipeline — the only path
        where an encoder (and thus a clamp) is involved; an EXIF-free
        under-cap JPEG would take the lossless fast path and never re-encode.

        Args:
            quality: Out-of-range quality value under test.
            expectedClamped: The clamped value expected in the warning.
            caplog: pytest fixture capturing log records.

        Returns:
            None
        """
        original = _jpegBytesOfSize(300, 200)

        with caplog.at_level(logging.WARNING, logger="lib.ai.imaging"):
            result, mime = normalizeVisionImage(original, maxDimension=100, quality=quality)

        assert mime == _JPEG_MIME
        out = Image.open(BytesIO(result))
        assert out.format == "JPEG"
        out.load()
        assert any(record.levelno == logging.WARNING for record in caplog.records)
        assert f"clamped to {expectedClamped}" in caplog.text

    def testFallbackLogsWarningWithOriginalBytes(self, caplog: pytest.LogCaptureFixture) -> None:
        """The lenient wrapper warns that it fell back to the ORIGINAL bytes.

        Distinct from the strict-internal failure logs: the wrapper itself
        must log a WARNING saying normalization failed and original bytes
        are returned, so a degraded store is visible in logs even when the
        specific failure reason was logged deeper.

        Args:
            caplog: pytest fixture capturing log records.

        Returns:
            None
        """
        corrupt = b"\x00\x01\x02\x03not-an-image-at-all-garbage"

        with caplog.at_level(logging.WARNING, logger="lib.ai.imaging"):
            result, mime = normalizeVisionImage(corrupt, maxDimension=100)

        assert result == corrupt
        fallbackWarnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("ORIGINAL image bytes" in r.getMessage() for r in fallbackWarnings)


class TestNormalizeVisionImageStrict:
    """Tests for :func:`lib.ai.imaging.normalizeVisionImageStrict` (Phase 1b).

    The strict variant runs the same pipeline as
    :func:`normalizeVisionImage` but fails CLOSED: every branch where the
    lenient variant degrades to the original bytes must yield ``None``
    here. The receipt-time store relies on that signal — storing the
    lenient fallback would publish oversized, EXIF-bearing originals
    (review finding 2; send-time delivery does no resize).
    """

    def testSuccessReturnsNormalizedTuple(self) -> None:
        """A valid image yields ``(normalizedBytes, outputFormat)``, decodable.

        Returns:
            None
        """
        original = _jpegBytesOfSize(32, 24)

        result = normalizeVisionImageStrict(original, maxDimension=100)

        assert result is not None
        normalized, mime = result
        assert mime == _JPEG_MIME
        out = Image.open(BytesIO(normalized))
        assert out.format == "JPEG"
        out.load()

    def testOversizeGuardReturnsNone(self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
        """The 50MP guard yields None — NOT the oversized original bytes.

        Regression anchor for the review finding: the lenient variant
        returns the original here, which the old MIME-only store check
        wrongly treated as success.

        Args:
            caplog: pytest fixture capturing log records.
            monkeypatch: pytest fixture for temporary attribute patching.

        Returns:
            None
        """
        original = _jpegBytesOfSize(10, 10)
        mockImg = MagicMock()
        mockImg.width = 10_000
        mockImg.height = 10_000
        monkeypatch.setattr(Image, "open", Mock(return_value=mockImg))

        with caplog.at_level(logging.ERROR, logger="lib.ai.imaging"):
            result = normalizeVisionImageStrict(original, maxDimension=100)

        assert result is None
        assert "too large" in caplog.text
        assert any(record.levelno == logging.ERROR for record in caplog.records)

    def testCorruptBytesReturnNone(self, caplog: pytest.LogCaptureFixture) -> None:
        """Bytes Pillow cannot open yield None with an error logged.

        Args:
            caplog: pytest fixture capturing log records.

        Returns:
            None
        """
        corrupt = b"\x00\x01\x02\x03not-an-image-at-all-garbage"

        with caplog.at_level(logging.ERROR, logger="lib.ai.imaging"):
            result = normalizeVisionImageStrict(corrupt, maxDimension=100)

        assert result is None
        assert any(record.levelno == logging.ERROR for record in caplog.records)

    @pytest.mark.parametrize("outputFormat", ["image/webp", "image/gif", "image/bmp"])
    def testUnsupportedOutputFormatReturnsNone(self, outputFormat: str, caplog: pytest.LogCaptureFixture) -> None:
        """A non-member output value yields None (fail closed).

        Raw strings are passed deliberately (``cast`` past the enum
        annotation): the enum is not runtime-enforced, so callers still
        feeding config strings must see the strict variant FAIL CLOSED for
        non-JPEG/PNG targets, exactly as before the StrEnum introduction.

        Args:
            outputFormat: Unsupported target MIME under test.
            caplog: pytest fixture capturing log records.

        Returns:
            None
        """
        original = _jpegBytesOfSize(10, 10)

        with caplog.at_level(logging.WARNING, logger="lib.ai.imaging"):
            result = normalizeVisionImageStrict(
                original, maxDimension=100, outputFormat=cast(VisionOutputImageFormat, outputFormat)
            )

        assert result is None
        assert any(record.levelno == logging.WARNING for record in caplog.records)
        assert outputFormat in caplog.text

    def testMimeDetectionFailureReturnsNone(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A libmagic failure yields None (lenient variant: octet-stream fallback).

        Args:
            caplog: pytest fixture capturing log records.
            monkeypatch: pytest fixture for temporary attribute patching.

        Returns:
            None
        """
        original = b"\x00\x01payload-that-is-never-inspected"

        def failingFromBuffer(*args: object, **kwargs: object) -> str:
            """Stub raising the simulated libmagic failure.

            Args:
                *args: Positional call arguments (ignored).
                **kwargs: Keyword call arguments (ignored).

            Returns:
                Never returns; always raises OSError.

            Raises:
                OSError: The simulated libmagic failure.
            """
            raise OSError("simulated libmagic failure")

        monkeypatch.setattr("lib.ai.imaging.magic.from_buffer", failingFromBuffer)

        with caplog.at_level(logging.ERROR, logger="lib.ai.imaging"):
            result = normalizeVisionImageStrict(original)

        assert result is None
        assert any(record.levelno == logging.ERROR for record in caplog.records)

    def testEncoderFailureReturnsNone(self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
        """A Pillow encoder failure on valid input yields None.

        The fixture is OVER the resize cap so the image takes the re-encode
        pipeline (an EXIF-free under-cap JPEG would take the lossless fast
        path and never reach the encoder).

        Args:
            caplog: pytest fixture capturing log records.
            monkeypatch: pytest fixture for temporary attribute patching.

        Returns:
            None
        """
        original = _jpegBytesOfSize(300, 200)
        saveMock = Mock(side_effect=OSError("simulated encoder failure"))
        monkeypatch.setattr(Image.Image, "save", saveMock)

        with caplog.at_level(logging.ERROR, logger="lib.ai.imaging"):
            result = normalizeVisionImageStrict(original, maxDimension=100)

        assert result is None
        saveMock.assert_called_once()
        assert any(record.levelno == logging.ERROR for record in caplog.records)

    def testLenientFallbackCorrespondsToStrictNone(self, caplog: pytest.LogCaptureFixture) -> None:
        """Pairing invariant: strict None exactly where lenient degrades.

        For corrupt input the lenient variant returns the original bytes
        while the strict variant returns None — the two entry points stay
        consistent about what counts as failure.

        Args:
            caplog: pytest fixture capturing log records.

        Returns:
            None
        """
        corrupt = b"\x00\x01\x02\x03not-an-image-at-all-garbage"

        with caplog.at_level(logging.ERROR, logger="lib.ai.imaging"):
            strict = normalizeVisionImageStrict(corrupt, maxDimension=100)
            lenientBytes, _lenientMime = normalizeVisionImage(corrupt, maxDimension=100)

        assert strict is None
        assert lenientBytes == corrupt


class TestStripJpegExifHelper:
    """Direct marker-walk contract tests for :func:`lib.ai.imaging._stripJpegExif`.

    The walker must rebuild the marker stream byte-identically minus EXIF
    APP1 segments, and return ``None`` (surgery not applicable) on any
    structural anomaly — the caller then falls back to the full re-encode
    pipeline, which strips EXIF anyway.
    """

    def testNonJpegBytesReturnNone(self) -> None:
        """Missing SOI / empty input are surgery-inapplicable (None).

        Returns:
            None
        """
        assert _stripJpegExif(b"") is None
        assert _stripJpegExif(b"\xff\xd8") is None
        assert _stripJpegExif(b"\x89PNG\r\n\x1a\nnot-a-jpeg") is None

    def testBareSoiEoiPassesThroughIdentity(self) -> None:
        """A minimal SOI+EOI stream round-trips byte-identically.

        Returns:
            None
        """
        assert _stripJpegExif(b"\xff\xd8\xff\xd9") == b"\xff\xd8\xff\xd9"

    def testExifApp1DroppedEverythingElseByteIdentical(self) -> None:
        """Output = input minus the Exif APP1 chunk; all else identical, in order.

        Returns:
            None
        """
        original = _jpegBytesWithExifTags(64, 48, {0x010F: "TestCameraMaker", 0x0112: 1})

        result = _stripJpegExif(original)

        assert result is not None
        expectedChunks = [chunk for (marker, chunk) in _splitJpegSegments(original) if not _isExifApp1((marker, chunk))]
        assert [chunk for (_marker, chunk) in _splitJpegSegments(result)] == expectedChunks
        assert b"Exif\x00\x00" not in result

    def testXmpApp1KeptByteIdentical(self) -> None:
        """An XMP APP1 (different identifier) survives the walk verbatim.

        Returns:
            None
        """
        base = _jpegBytesOfSize(32, 24)
        xmpSegment = _app1Segment(b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta></x:xmpmeta>")
        original = base[:2] + xmpSegment + base[2:]

        result = _stripJpegExif(original)

        assert result == original

    def testSegmentLengthOverrunReturnsNone(self) -> None:
        """A segment length overrunning EOF is a structural anomaly (None).

        Returns:
            None
        """
        original = _jpegBytesWithExifTags(64, 48, {0x010F: "TestCameraMaker"})
        corrupt = bytearray(original)
        app1 = original.index(b"\xff\xe1", 2)
        corrupt[app1 + 2 : app1 + 4] = (0xFFFF).to_bytes(2, "big")

        assert _stripJpegExif(bytes(corrupt)) is None

    def testNonMarkerGarbageReturnsNone(self) -> None:
        """Non-marker garbage between segments is a structural anomaly (None).

        Returns:
            None
        """
        original = _jpegBytesOfSize(32, 24)
        corrupt = original[:2] + b"\x00\x00" + original[2:]

        assert _stripJpegExif(corrupt) is None

    def testFillBytesReturnNone(self) -> None:
        """Fill bytes (a second 0xFF where the marker byte belongs) yield None.

        Returns:
            None
        """
        original = _jpegBytesOfSize(32, 24)
        corrupt = original[:2] + b"\xff\xff" + original[2:]

        assert _stripJpegExif(corrupt) is None

    def testCompleteSegmentThenEofWithoutSosOrEoiReturnsNone(self) -> None:
        """A stream of complete segments that ends before SOS/EOI yields None.

        Pins the while/else exhaustion branch: the walk must not report
        success on a stream it never walked to completion.

        Returns:
            None
        """
        original = _jpegBytesOfSize(32, 24)
        sos = original.index(b"\xff\xda", 2)
        truncated = original[:sos]  # complete segments, but the scan never starts

        assert _stripJpegExif(truncated) is None

    def testTruncatedImmediatelyAfterSosHeaderReturnsNone(self) -> None:
        """A file ending right after the SOS header yields None (no EOI in scan).

        Regression for the review major: the fast path must not report
        success on such bytes (the decode gate / re-encode fallback reject
        them fail-closed).

        Returns:
            None
        """
        original = _jpegBytesOfSize(32, 24)
        sos = original.index(b"\xff\xda", 2)
        sosSegLen = int.from_bytes(original[sos + 2 : sos + 4], "big")
        truncatedAfterSos = original[: sos + 2 + sosSegLen]

        assert _stripJpegExif(truncatedAfterSos) is None

    def testStandaloneRstMarkerCopiedThrough(self) -> None:
        """A standalone RST marker (no length field) is copied as 2 bytes.

        Returns:
            None
        """
        original = _jpegBytesOfSize(32, 24)
        injected = original[:2] + b"\xff\xd0" + original[2:]

        assert _stripJpegExif(injected) == injected

    def testMultipleExifApp1SegmentsAllDropped(self) -> None:
        """Every Exif APP1 is dropped; everything else stays byte-identical.

        Returns:
            None
        """
        base = _jpegBytesOfSize(32, 24)
        exif = Image.Exif()
        exif[0x010F] = "TestCameraMaker"
        exifSegment = _app1Segment(exif.tobytes())
        original = base[:2] + exifSegment + exifSegment + base[2:]

        assert _stripJpegExif(original) == base

    def testExifApp1AfterSosDeclined(self) -> None:
        """An EXIF APP1 inside the scan region (after SOS) yields None.

        Regression for the review major: the surgery refuses streams whose
        post-scan-marker EXIF it cannot strip, deferring to the re-encode
        fallback instead of silently shipping the metadata.

        Returns:
            None
        """
        original = _jpegBytesOfSize(32, 24)
        exif = Image.Exif()
        exif[0x010F] = "TestCameraMaker"
        exifSegment = _app1Segment(exif.tobytes())
        sos = original.index(b"\xff\xda", 2)
        sosSegLen = int.from_bytes(original[sos + 2 : sos + 4], "big")
        scanStart = sos + 2 + sosSegLen
        injected = original[:scanStart] + exifSegment + original[scanStart:]

        assert _stripJpegExif(injected) is None

    def testTrailingDataAfterEoiDropped(self) -> None:
        """Trailing bytes after the EOI are not image data and are dropped.

        Returns:
            None
        """
        original = _jpegBytesOfSize(32, 24)

        assert _stripJpegExif(original + b"\x00garbage-after-eoi") == original

    def testTrailingDataAfterHeaderLevelEoiDropped(self) -> None:
        """Trailing bytes after a header-level (pre-SOS) EOI are dropped too.

        Regression: the pre-SOS EOI branch used to copy the EOI and break
        out of the walk, and the code after the loop then appended EVERYTHING
        remaining — so trailers survived, inconsistent with the scan-level
        EOI branch, which drops them.

        Returns:
            None
        """
        assert _stripJpegExif(b"\xff\xd8\xff\xd9TRAILER") == b"\xff\xd8\xff\xd9"

    def testHeaderTemMarkerCopiedThrough(self) -> None:
        """A standalone TEM marker (FF 01) in the header is copied as 2 bytes.

        Header parser position: TEM carries no length field, so the walk
        must treat it as a bare marker and keep it verbatim.

        Returns:
            None
        """
        original = _jpegBytesOfSize(32, 24)
        injected = original[:2] + b"\xff\x01" + original[2:]

        assert _stripJpegExif(injected) == injected

    def testStuffedFF00InsideScanCopiedVerbatim(self) -> None:
        """A byte-stuffed FF 00 at the start of the scan is copied verbatim.

        The expectation is built by explicit byte concatenation —
        ``_splitJpegSegments`` treats everything after SOS as one opaque
        chunk and cannot validate the scan walk. Dropping the header EXIF
        APP1 in the EXPECTATION (while the crafted scan bytes must survive
        byte-identically) makes the assertion fail for an implementation
        that rejects, mangles, or merely passes through the scan.

        Returns:
            None
        """
        base = _jpegBytesOfSize(32, 24)
        sos = base.index(b"\xff\xda", 2)
        sosSegLen = int.from_bytes(base[sos + 2 : sos + 4], "big")
        scanStart = sos + 2 + sosSegLen
        exif = Image.Exif()
        exif[0x010F] = "TestCameraMaker"
        exifSegment = _app1Segment(exif.tobytes())
        craftedScan = b"\x2c\x9d\xff\x00\x71\x33"
        original = base[:2] + exifSegment + base[2:scanStart] + craftedScan + base[scanStart:]
        expected = base[:2] + base[2:scanStart] + craftedScan + base[scanStart:]

        assert _stripJpegExif(original) == expected

    def testRstMarkerInsideScanCopiedVerbatim(self) -> None:
        """A restart marker (RST0) inside the entropy scan is copied verbatim.

        Scan parser position (before the EOI, after real scan data): RST0
        carries no length field, the scan continues after it, and the bytes
        must survive untouched. The EXIF APP1 dropped in the EXPECTATION
        discriminates a real walk from a passthrough.

        Returns:
            None
        """
        base = _jpegBytesOfSize(32, 24)
        exif = Image.Exif()
        exif[0x010F] = "TestCameraMaker"
        exifSegment = _app1Segment(exif.tobytes())
        craftedScan = b"\x1a\x2b\xff\xd0\x3c\x4d"
        original = base[:2] + exifSegment + base[2:-2] + craftedScan + base[-2:]
        expected = base[:2] + base[2:-2] + craftedScan + base[-2:]

        assert _stripJpegExif(original) == expected

    def testScanPaddingRunBeforeEoiCopiedVerbatim(self) -> None:
        """A 0xFF padding run inside the scan, right before the EOI, survives.

        Scan parser position: fill bytes (FF followed by FF) are legal
        padding before a real marker inside the scan — the walk must copy
        the whole run verbatim and still terminate at the EOI. The EXIF
        APP1 dropped in the EXPECTATION discriminates a real walk from a
        passthrough.

        Returns:
            None
        """
        base = _jpegBytesOfSize(32, 24)
        exif = Image.Exif()
        exif[0x010F] = "TestCameraMaker"
        exifSegment = _app1Segment(exif.tobytes())
        paddingRun = b"\xff\xff\xff"
        original = base[:2] + exifSegment + base[2:-2] + paddingRun + base[-2:]
        expected = base[:2] + base[2:-2] + paddingRun + base[-2:]

        assert _stripJpegExif(original) == expected

    def testHeaderPaddingRunBeforeSosReturnsNone(self) -> None:
        """A 0xFF padding run in the HEADER, right before SOS, yields None.

        Header parser position: unlike the scan walk (which tolerates fill
        bytes), the header walk requires the canonical single-0xFF marker
        form — a fill run there is a structural anomaly (None), pinning the
        asymmetry between the two walkers.

        Returns:
            None
        """
        original = _jpegBytesOfSize(32, 24)
        sos = original.index(b"\xff\xda", 2)
        injected = original[:sos] + b"\xff\xff" + original[sos:]

        assert _stripJpegExif(injected) is None

    def testSecondSosInsideScanReturnsNone(self) -> None:
        """A second SOS segment after the first scan's data yields None.

        The surgery only understands a single-scan stream: any inter-scan
        marker (a second SOS here, injected right before the EOI) is a
        structure whose EXIF it cannot fully strip → not applicable (None),
        deferring to the re-encode fallback.

        Returns:
            None
        """
        original = _jpegBytesOfSize(32, 24)
        secondSos = b"\xff\xda\x00\x02"  # minimal SOS header: empty payload
        injected = original[:-2] + secondSos + original[-2:]

        assert _stripJpegExif(injected) is None

    def testDhtInsideScanReturnsNone(self) -> None:
        """A DHT segment inside the scan region (between scans) yields None.

        Progressive streams legally place DHT segments between scans; the
        single-scan surgery must refuse them (None) rather than walk past
        metadata it cannot strip. Injected right after the SOS header —
        the first classification the scan walk makes.

        Returns:
            None
        """
        original = _jpegBytesOfSize(32, 24)
        sos = original.index(b"\xff\xda", 2)
        sosSegLen = int.from_bytes(original[sos + 2 : sos + 4], "big")
        scanStart = sos + 2 + sosSegLen
        dhtSegment = b"\xff\xc4\x00\x12" + b"\x00" * 16  # length-bearing DHT header + table
        injected = original[:scanStart] + dhtSegment + original[scanStart:]

        assert _stripJpegExif(injected) is None

    def testUnderstatedApp1LengthSilentResyncReturnsNone(self) -> None:
        """An understated APP1 length (ends mid-payload) must yield None.

        Regression for the review minor: the walk rejects OVERRUNNING
        segment lengths but a declared length SHORTER than the real segment
        used to make the header walk silently resync mid-payload. The
        fixture declares an APP1 length of 8 (just the ``Exif\\x00\\x00``
        identifier) while the real payload continues: from the resync point
        the raw payload bytes chain a COM-looking ``FF FE`` marker into a
        fake APP5 whose "payload" is raw TIFF junk — each fake segment's
        length lands the walk exactly on the next marker, ending on the
        original JFIF APP0, so the whole walk completes. Pre-fix this
        returned "successful" (and even decodable) but mangled output — the fast path's ``img.load()`` gate
        validates the INPUT stream, never the surgery output, so it could
        not catch this. Post-fix the bogus resynced APP5 has no recognised
        payload identifier and the surgery declines (None).

        Returns:
            None
        """
        base = _jpegBytesOfSize(32, 24)
        injected = (
            base[:2]
            + b"\xff\xe1\x00\x08"  # understated APP1: length covers only "Exif\x00\x00"
            + b"Exif\x00\x00"
            + b"\xff\xfe\x00\x02"  # COM-looking marker (empty payload) — resync hop 1
            + b"\xff\xe5\x00\x06JUNK"  # APP5-looking marker, unrecognized payload — resync hop 2
            + base[2:]
        )

        assert _stripJpegExif(injected) is None

    def testUnrecognizedAppSegmentPayloadReturnsNone(self) -> None:
        """A KEPT APPn whose payload lacks its standard identifier yields None.

        Every APP segment other than the dropped Exif APP1s must carry a
        recognised payload identifier (APP0 JFIF/JFXX, APP1 Adobe namespace,
        APP2 ICC_PROFILE, APP14 Adobe); APP3-APP13/APP15 have none, so any
        payload they carry is a structural anomaly (None). Covers an APP3
        and an APP15 with junk payloads, plus an APP0 whose payload does not
        match JFIF/JFXX.

        Returns:
            None
        """
        original = _jpegBytesOfSize(32, 24)

        assert _stripJpegExif(original[:2] + b"\xff\xe3\x00\x05JUNK" + original[2:]) is None  # APP3
        assert _stripJpegExif(original[:2] + b"\xff\xef\x00\x05JUNK" + original[2:]) is None  # APP15
        assert _stripJpegExif(original[:2] + b"\xff\xe0\x00\x07XXXX\x00" + original[2:]) is None  # APP0 non-JFIF

    def testStandardAppIdentifiersAllKept(self) -> None:
        """JFIF APP0 + XMP APP1 + ICC APP2 + Adobe APP14 all kept; surgery succeeds.

        Sanity for the kept-APPn payload validation: the standard identifier
        set must keep previously-succeeding surgeries succeeding. The
        fixture chains all four recognised segment kinds (the Pillow encoder
        already wrote the JFIF APP0 into the base) plus an EXIF APP1, which
        is the only chunk the surgery drops.

        Returns:
            None
        """
        base = _jpegBytesOfSize(32, 24)  # carries the JFIF APP0 from the Pillow encoder
        xmpSegment = _app1Segment(b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta></x:xmpmeta>")
        iccSegment = b"\xff\xe2\x00\x14" + b"ICC_PROFILE\x00" + b"\x01\x01" + b"\x00\x00\x00\x00"
        adobeSegment = b"\xff\xee\x00\x0e" + b"Adobe" + b"\x00\x64" + b"\x00\x00\x00\x00" + b"\x00"
        exif = Image.Exif()
        exif[0x010F] = "TestCameraMaker"
        exifSegment = _app1Segment(exif.tobytes())
        original = base[:2] + xmpSegment + iccSegment + adobeSegment + exifSegment + base[2:]
        expected = base[:2] + xmpSegment + iccSegment + adobeSegment + base[2:]

        assert _stripJpegExif(original) == expected


class TestNormalizeVisionImageJpegExifFastPath:
    """Tests for the EXIF lossless fast path in ``normalizeVisionImageStrict`` (Wave C).

    Eligibility (evaluated in order inside the normalizer): JPEG source AND
    JPEG output target; no resize needed (``maxDimension == 0`` or long side
    already within the cap); RGB pixel mode (the full pipeline converts any
    other mode to RGB on re-encode, so a grayscale/CMYK component layout
    must not ship unchanged); EXIF orientation absent or == 1; and the
    marker surgery succeeding. On success the ORIGINAL compressed bytes ship minus
    the Exif APP1 segment(s) — decoded pixels bit-identical, zero generational
    quality loss. PNG never takes a fast path. A surgery failure on an
    otherwise-eligible image must warn and fall through to the normal
    pipeline, which still succeeds.
    """

    def testExifJpegUnderCapTakesFastPath(self) -> None:
        """EXIF JPEG under the cap: bytes = input minus Exif APP1, pixels identical.

        The byte-level chunk comparison (plus exact pixel equality of the
        decoded images) is what distinguishes marker surgery from a Pillow
        re-encode, which would produce entirely different bytes.

        Returns:
            None
        """
        original = _jpegBytesWithExifTags(64, 48, {0x010F: "TestCameraMaker", 0x0112: 1})
        # Sanity: the fixture really carries EXIF and identity orientation.
        srcExif = Image.open(BytesIO(original)).getexif()
        assert srcExif.get(0x010F) == "TestCameraMaker"
        assert srcExif.get(0x0112) == 1

        result = normalizeVisionImageStrict(original, maxDimension=100)

        assert result is not None
        normalized, mime = result
        assert mime == _JPEG_MIME
        # Surgery, not re-encode: output chunks == input chunks minus the
        # Exif APP1(s), everything else byte-identical and in order.
        inputChunks = _splitJpegSegments(original)
        assert any(_isExifApp1(entry) for entry in inputChunks)
        outputChunks = _splitJpegSegments(normalized)
        assert outputChunks == [entry for entry in inputChunks if not _isExifApp1(entry)]
        # Decoded pixels are EXACTLY the input's (no generational loss).
        srcPixels = Image.open(BytesIO(original)).convert("RGB").tobytes()
        outPixels = Image.open(BytesIO(normalized)).convert("RGB").tobytes()
        assert outPixels == srcPixels
        # The privacy property holds: no EXIF survives in the output.
        outExif = Image.open(BytesIO(normalized)).getexif()
        assert outExif.get(0x010F) is None
        assert len(outExif) == 0

    def testExifOrientationSixDisqualifiesFastPath(self) -> None:
        """Orientation 6 → NOT the fast path: transposed re-encode (20x40 portrait).

        Were the fast path wrongly taken, the output would be the original
        40x20 landscape scan data with only metadata removed.

        Returns:
            None
        """
        original = _jpegBytesWithExifTags(40, 20, {0x0112: 6})
        # Sanity: the fixture really carries the disqualifying orientation.
        assert Image.open(BytesIO(original)).getexif().get(0x0112) == 6

        result = normalizeVisionImageStrict(original, maxDimension=2048)

        assert result is not None
        normalized, mime = result
        assert mime == _JPEG_MIME
        out = Image.open(BytesIO(normalized))
        assert out.format == "JPEG"
        # Transposed pixel layout proves the full pipeline ran.
        assert out.size == (20, 40)
        outExif = out.getexif()
        assert outExif.get(0x0112) is None
        assert len(outExif) == 0
        out.load()

    def testOverCapJpegTakesNormalResizePath(self) -> None:
        """A JPEG over the cap is downscaled — fast path does not apply.

        Returns:
            None
        """
        original = _jpegBytesOfSize(300, 200)

        result = normalizeVisionImageStrict(original, maxDimension=100)

        assert result is not None
        normalized, mime = result
        assert mime == _JPEG_MIME
        assert normalized != original
        out = Image.open(BytesIO(normalized))
        assert out.format == "JPEG"
        assert out.size == (100, 67)
        out.load()

    def testPngOutputTakesNormalPath(self) -> None:
        """A JPEG source with a PNG output target re-encodes as PNG.

        Returns:
            None
        """
        original = _jpegBytesOfSize(10, 10)

        result = normalizeVisionImageStrict(original, maxDimension=2048, outputFormat=VisionOutputImageFormat.PNG)

        assert result is not None
        normalized, mime = result
        assert mime == _PNG_MIME
        out = Image.open(BytesIO(normalized))
        assert out.format == "PNG"
        out.load()

    def testPngInputTakesNormalPath(self) -> None:
        """A PNG source never takes the JPEG fast path (re-encode is lossless).

        Returns:
            None
        """
        original = _rgbaPngBytesOfSize(8, 8)

        result = normalizeVisionImageStrict(original, maxDimension=2048)

        assert result is not None
        normalized, mime = result
        assert mime == _JPEG_MIME
        out = Image.open(BytesIO(normalized))
        assert out.format == "JPEG"
        assert out.mode == "RGB"
        out.load()

    def testCmykJpegDoesNotTakeFastPath(self) -> None:
        """A CMYK JPEG is re-encoded to RGB — the fast path is RGB-only.

        The normal pipeline converts every non-RGB mode to RGB during the
        re-encode; the byte surgery would instead ship the original CMYK
        component layout, a mode the pipeline never emits to providers.

        Returns:
            None
        """
        original = _jpegBytesOfModeWithExifTags(64, 48, "CMYK", {0x010F: "TestCameraMaker"})
        # Sanity: the fixture really is an EXIF-carrying CMYK JPEG with
        # identity orientation (so the mode is the only disqualifier).
        src = Image.open(BytesIO(original))
        assert src.mode == "CMYK"
        assert src.getexif().get(0x010F) == "TestCameraMaker"
        assert src.getexif().get(0x0112) is None

        result = normalizeVisionImageStrict(original, maxDimension=2048)

        assert result is not None
        normalized, mime = result
        assert mime == _JPEG_MIME
        # NOT the fast path: the output differs from the input-minus-APP1
        # surgery — it is a genuine re-encode.
        expectedSurgery = _stripJpegExif(original)
        assert expectedSurgery is not None
        assert normalized != expectedSurgery
        out = Image.open(BytesIO(normalized))
        assert out.format == "JPEG"
        assert out.mode == "RGB"
        assert out.size == src.size
        assert len(out.getexif()) == 0
        # Pixels match the CMYK source converted to RGB, within JPEG noise.
        expectedPixels = src.convert("RGB").tobytes()
        actualPixels = out.tobytes()
        maxDelta = max(abs(a - b) for a, b in zip(expectedPixels, actualPixels))
        assert maxDelta <= 16
        out.load()

    def testGrayscaleJpegDoesNotTakeFastPath(self) -> None:
        """A grayscale (``"L"``) JPEG is re-encoded to RGB — the fast path is RGB-only.

        Returns:
            None
        """
        original = _jpegBytesOfModeWithExifTags(64, 48, "L", {0x010F: "TestCameraMaker"})
        # Sanity: the fixture really is an EXIF-carrying grayscale JPEG with
        # identity orientation (so the mode is the only disqualifier).
        src = Image.open(BytesIO(original))
        assert src.mode == "L"
        assert src.getexif().get(0x010F) == "TestCameraMaker"
        assert src.getexif().get(0x0112) is None

        result = normalizeVisionImageStrict(original, maxDimension=2048)

        assert result is not None
        normalized, mime = result
        assert mime == _JPEG_MIME
        # NOT the fast path: the output differs from the input-minus-APP1
        # surgery — it is a genuine re-encode.
        expectedSurgery = _stripJpegExif(original)
        assert expectedSurgery is not None
        assert normalized != expectedSurgery
        out = Image.open(BytesIO(normalized))
        assert out.format == "JPEG"
        assert out.mode == "RGB"
        assert out.size == src.size
        assert len(out.getexif()) == 0
        # Pixels match the grayscale source converted to RGB, within JPEG noise.
        expectedPixels = src.convert("RGB").tobytes()
        actualPixels = out.tobytes()
        maxDelta = max(abs(a - b) for a, b in zip(expectedPixels, actualPixels))
        assert maxDelta <= 16
        out.load()

    def testExifFreeJpegReturnsOriginalBytesUnchanged(self) -> None:
        """An EXIF-free eligible JPEG round-trips BYTE-IDENTICALLY (pure passthrough).

        With nothing to drop, the marker walk must reconstruct the exact
        input — a re-encode would produce different bytes.

        Returns:
            None
        """
        original = _jpegBytesOfSize(32, 24)

        result = normalizeVisionImageStrict(original, maxDimension=2048)

        assert result == (original, _JPEG_MIME)

    def testExifJpegMaxDimensionZeroTakesFastPath(self) -> None:
        """maxDimension=0 (resize disabled) keeps the fast path eligible.

        The surgery output ships: input chunks minus the Exif APP1, with the
        original dimensions untouched.

        Returns:
            None
        """
        original = _jpegBytesWithExifTags(64, 48, {0x010F: "TestCameraMaker", 0x0112: 1})

        result = normalizeVisionImageStrict(original, maxDimension=0)

        assert result is not None
        normalized, mime = result
        assert mime == _JPEG_MIME
        inputChunks = _splitJpegSegments(original)
        assert _splitJpegSegments(normalized) == [entry for entry in inputChunks if not _isExifApp1(entry)]
        out = Image.open(BytesIO(normalized))
        assert out.size == (64, 48)
        assert len(out.getexif()) == 0
        out.load()

    def testTruncatedScanUndecodableJpegReturnsNone(self, caplog: pytest.LogCaptureFixture) -> None:
        """A JPEG whose entropy scan never terminates yields None (fail closed).

        Regression for the review major: a stream whose headers parse fine
        and whose surgery-eligible shape looks plausible can still be
        undecodable. Here the entropy-coded scan is cut short without a
        terminating EOI, so the marker walk declines (no EOI reached) and
        Pillow's header-only open succeeds while the decode fails — the
        fast path probe must decline and the re-encode fallback behind it
        must fail decode, reporting ``None`` instead of success. (A stream
        ending in EOI does NOT qualify: libjpeg silently gray-fills the
        missing scan data, so those bytes are genuinely decodable and the
        fast path legitimately ships them.)

        Args:
            caplog: pytest fixture capturing log records.

        Returns:
            None
        """
        original = _jpegBytesWithExifTags(64, 48, {0x010F: "TestCameraMaker", 0x0112: 1})
        sos = original.index(b"\xff\xda", 2)
        sosSegLen = int.from_bytes(original[sos + 2 : sos + 4], "big")
        scanStart = sos + 2 + sosSegLen
        eoi = original.rindex(b"\xff\xd9")
        truncated = original[: scanStart + (eoi - scanStart) // 2]  # cut mid-scan, no EOI
        # Sanity: the surgery declines the unterminated scan, and Pillow
        # opens the file (header-only parse) — yet no decoder can produce
        # pixels.
        assert _stripJpegExif(truncated) is None
        Image.open(BytesIO(truncated))
        with pytest.raises(OSError):
            Image.open(BytesIO(truncated)).load()

        with caplog.at_level(logging.ERROR, logger="lib.ai.imaging"):
            result = normalizeVisionImageStrict(truncated, maxDimension=2048)

        assert result is None
        assert any(record.levelno == logging.ERROR for record in caplog.records)

    def testFastPathSurgeryExceptionFallsBackToNormalPipeline(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An exception inside the fast-path probe must not fail normalization.

        The fast path is an optimization: when even its probe blows up, the
        normal re-encode pipeline runs and succeeds.

        Args:
            caplog: pytest fixture capturing log records.
            monkeypatch: pytest fixture for temporary attribute patching.

        Returns:
            None
        """

        def raisingStrip(data: bytes) -> Optional[bytes]:
            """Stub raising the simulated surgery failure.

            Args:
                data: The JPEG bytes (ignored).

            Returns:
                Never returns; always raises RuntimeError.

            Raises:
                RuntimeError: The simulated surgery failure.
            """
            raise RuntimeError("simulated surgery failure")

        monkeypatch.setattr("lib.ai.imaging._stripJpegExif", raisingStrip)
        original = _jpegBytesOfSize(32, 24)

        with caplog.at_level(logging.ERROR, logger="lib.ai.imaging"):
            result = normalizeVisionImageStrict(original, maxDimension=2048)

        assert result is not None
        normalized, mime = result
        assert mime == _JPEG_MIME
        Image.open(BytesIO(normalized)).load()
        assert any(record.levelno == logging.ERROR for record in caplog.records)
        assert "fast path" in caplog.text

    def testCorruptMarkerStreamWarnsAndFallsBackToNormalPipeline(self, caplog: pytest.LogCaptureFixture) -> None:
        """A surgery-inapplicable eligible image warns; the normal pipeline succeeds.

        The corruption (non-marker garbage between segments) is one the
        marker walker must reject while Pillow still opens and decodes the
        stream — so the fallback re-encode can genuinely run.

        Args:
            caplog: pytest fixture capturing log records.

        Returns:
            None
        """
        original = _jpegBytesWithExifTags(64, 48, {0x010F: "TestCameraMaker", 0x0112: 1})
        app1 = original.index(b"\xff\xe1", 2)
        segLen = int.from_bytes(original[app1 + 2 : app1 + 4], "big")
        corrupt = original[: app1 + 2 + segLen] + b"\x00\x00" + original[app1 + 2 + segLen :]
        # Sanity: Pillow still decodes the corrupted stream, so the normal
        # pipeline is genuinely expected to succeed.
        Image.open(BytesIO(corrupt)).load()

        with caplog.at_level(logging.WARNING, logger="lib.ai.imaging"):
            result = normalizeVisionImageStrict(corrupt, maxDimension=100)

        assert result is not None
        normalized, mime = result
        assert mime == _JPEG_MIME
        out = Image.open(BytesIO(normalized))
        assert out.format == "JPEG"
        assert len(out.getexif()) == 0
        out.load()
        assert any(record.levelno == logging.WARNING for record in caplog.records)
        assert "fast path" in caplog.text

    def testXmpApp1PreservedAlongsideExifApp1(self) -> None:
        """XMP APP1 survives the fast path verbatim; only the Exif APP1 goes.

        Returns:
            None
        """
        base = _jpegBytesOfSize(32, 24)
        exif = Image.Exif()
        exif[0x010F] = "TestCameraMaker"
        exif[0x0112] = 1
        # Image.Exif.tobytes() already includes the "Exif\x00\x00" header —
        # the segment models a canonical Pillow-style APP1 payload.
        exifSegment = _app1Segment(exif.tobytes())
        xmpSegment = _app1Segment(b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta></x:xmpmeta>")
        original = base[:2] + exifSegment + xmpSegment + base[2:]
        # Sanity: the injected EXIF is really readable before normalization.
        assert Image.open(BytesIO(original)).getexif().get(0x010F) == "TestCameraMaker"

        result = normalizeVisionImageStrict(original, maxDimension=2048)

        assert result is not None
        normalized, mime = result
        assert mime == _JPEG_MIME
        # The XMP segment is present verbatim; the EXIF payload is gone.
        assert xmpSegment in normalized
        assert b"Exif\x00\x00" not in normalized
        # Surgery again: chunks == input minus the Exif APP1.
        inputChunks = _splitJpegSegments(original)
        outputChunks = _splitJpegSegments(normalized)
        assert outputChunks == [entry for entry in inputChunks if not _isExifApp1(entry)]
        # Pixels untouched by the metadata surgery.
        srcPixels = Image.open(BytesIO(original)).convert("RGB").tobytes()
        outPixels = Image.open(BytesIO(normalized)).convert("RGB").tobytes()
        assert outPixels == srcPixels
