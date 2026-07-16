"""Tests for image input-format conversion.

Covers :func:`lib.ai.models.convertImageIfNeeded` and the
``supportedImageFormats`` threading in :meth:`ModelImageMessage.toDict`:

- Passthrough when *supportedFormats* is None / empty / already contains the MIME.
- WebP -> JPEG and WebP -> PNG conversion via Pillow (first listed format wins).
- Graceful degradation on corrupt bytes: original bytes returned, error logged.
- ``ModelImageMessage.toDict`` converts the embedded image into the data URL and
  does NOT mutate ``self.image`` (so primary/fallback re-derive from originals).
"""

import base64
import logging
from io import BytesIO

import pytest
from PIL import Image

from lib.ai.models import ModelImageMessage, convertImageIfNeeded

#: MIME types python-magic reports for our tiny factory images.
_JPEG_MIME = "image/jpeg"
_PNG_MIME = "image/png"
_WEBP_MIME = "image/webp"


# ---------------------------------------------------------------------------
# In-test image factories (self-contained; no external fixture files)
# ---------------------------------------------------------------------------


def _jpegBytes() -> bytes:
    """Return a tiny valid JPEG image (4x4 red).

    Returns:
        bytes of a JPEG-encoded image.
    """
    buf = BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, format="JPEG")
    return buf.getvalue()


def _pngBytes() -> bytes:
    """Return a tiny valid PNG image (4x4 green).

    Returns:
        bytes of a PNG-encoded image.
    """
    buf = BytesIO()
    Image.new("RGB", (4, 4), (0, 255, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _webpBytes() -> bytes:
    """Return a tiny valid WebP image (4x4 blue).

    Returns:
        bytes of a WebP-encoded image.
    """
    buf = BytesIO()
    Image.new("RGB", (4, 4), (0, 0, 255)).save(buf, format="WEBP")
    return buf.getvalue()


def _rgbaPngBytes() -> bytes:
    """Return a tiny valid PNG image (4x4 red, 50% alpha).

    The alpha channel is deliberately non-full so the image cannot be saved
    directly to JPEG — it exercises the RGB-flatten branch of
    :func:`convertImageIfNeeded`.

    Returns:
        bytes of an RGBA PNG-encoded image.
    """
    buf = BytesIO()
    Image.new("RGBA", (4, 4), (255, 0, 0, 128)).save(buf, format="PNG")
    return buf.getvalue()


class TestConvertImageIfNeeded:
    """Tests for :func:`lib.ai.models.convertImageIfNeeded`."""

    def testPassthroughWhenNone(self) -> None:
        """supportedFormats=None returns the original bytes and detected MIME.

        Returns:
            None
        """
        original = _webpBytes()
        result, mime = convertImageIfNeeded(original, None)
        assert result is original
        assert mime == _WEBP_MIME

    def testPassthroughWhenEmpty(self) -> None:
        """An empty supportedFormats list is falsy and yields passthrough.

        Returns:
            None
        """
        original = _webpBytes()
        result, mime = convertImageIfNeeded(original, [])
        assert result is original
        assert mime == _WEBP_MIME

    def testPassthroughWhenAlreadySupported(self) -> None:
        """A JPEG input already in the list is returned unchanged.

        Returns:
            None
        """
        original = _jpegBytes()
        result, mime = convertImageIfNeeded(original, [_JPEG_MIME, _PNG_MIME])
        assert result is original
        assert mime == _JPEG_MIME

    def testConvertsWebpToJpeg(self) -> None:
        """WebP not in [jpeg, png] is converted to the FIRST listed format (JPEG).

        The returned bytes must differ from the original and re-decode as JPEG.

        Returns:
            None
        """
        original = _webpBytes()
        result, mime = convertImageIfNeeded(original, [_JPEG_MIME, _PNG_MIME])
        assert mime == _JPEG_MIME
        assert result != original
        reOpened = Image.open(BytesIO(result))
        assert reOpened.format == "JPEG"
        reOpened.load()  # force full decode to confirm validity

    def testConvertsWebpToPng(self) -> None:
        """WebP + [png, jpeg] converts to PNG (the first listed format).

        Returns:
            None
        """
        original = _webpBytes()
        result, mime = convertImageIfNeeded(original, [_PNG_MIME, _JPEG_MIME])
        assert mime == _PNG_MIME
        assert result != original
        reOpened = Image.open(BytesIO(result))
        assert reOpened.format == "PNG"
        reOpened.load()

    def testUnknownTargetMimeReturnsOriginal(self, caplog: pytest.LogCaptureFixture) -> None:
        """A target MIME absent from _MIME_TO_PIL_FORMAT degrades gracefully with a warning.

        Distinct from the corrupt-bytes path: the input is a perfectly valid
        image, only the REQUESTED target format is unsupported. Original bytes
        are returned unchanged, the detected MIME is reported (NOT the target),
        and a WARNING (not ERROR) is logged.

        Args:
            caplog: pytest fixture capturing log records.

        Returns:
            None
        """
        original = _webpBytes()
        with caplog.at_level(logging.WARNING, logger="lib.ai.models"):
            result, mime = convertImageIfNeeded(original, ["image/bmp"])
        # Original bytes returned untouched.
        assert result == original
        # Reported MIME is the detected WebP, not the unsupported "image/bmp".
        assert mime == _WEBP_MIME
        assert mime != "image/bmp"
        # A WARNING record mentioned both the unsupported target and the source MIME.
        assert any(record.levelno == logging.WARNING for record in caplog.records)
        logText = caplog.text
        assert "image/bmp" in logText
        assert _WEBP_MIME in logText

    def testConvertsRgbaImageToJpeg(self) -> None:
        """An RGBA PNG is flattened to RGB and re-encoded as JPEG.

        Without the ``img.convert("RGB")`` flatten this would raise (JPEG has
        no alpha channel); the test pins that the flatten branch runs and
        produces a valid, decodable JPEG.

        Returns:
            None
        """
        original = _rgbaPngBytes()
        result, mime = convertImageIfNeeded(original, [_JPEG_MIME])
        assert mime == _JPEG_MIME
        assert result != original
        reOpened = Image.open(BytesIO(result))
        assert reOpened.format == "JPEG"
        reOpened.load()  # force full decode to confirm validity

    def testGracefulDegradationOnCorruptBytes(self, caplog: pytest.LogCaptureFixture) -> None:
        """Corrupt input that Pillow cannot open is returned unchanged with an error logged.

        Args:
            caplog: pytest fixture capturing log records.

        Returns:
            None
        """
        corrupt = b"\x00\x01\x02\x03not-an-image-at-all-garbage"
        with caplog.at_level(logging.ERROR, logger="lib.ai.models"):
            result, mime = convertImageIfNeeded(corrupt, [_JPEG_MIME])
        # Original bytes returned untouched (graceful degradation; never raises).
        assert result == corrupt
        # An ERROR record was emitted mentioning both MIME contexts.
        assert any(record.levelno == logging.ERROR for record in caplog.records)
        logText = caplog.text
        assert _JPEG_MIME in logText


class TestModelImageMessageToDict:
    """Tests for ``supportedImageFormats`` threading in ModelImageMessage.toDict."""

    def testToDictConvertsWebpToJpeg(self) -> None:
        """toDict(supportedImageFormats=[jpeg]) emits a data:image/jpeg URL from a WebP source.

        Also asserts ``self.image`` is NOT mutated by the conversion.

        Returns:
            None
        """
        webp = _webpBytes()
        msg = ModelImageMessage(role="user", content="look", image=bytearray(webp))
        imageBefore = bytes(msg.image)

        rendered = msg.toDict(supportedImageFormats=[_JPEG_MIME])

        # self.image untouched — fallback/primary must re-derive from originals.
        assert bytes(msg.image) == imageBefore

        content = rendered["content"]
        assert isinstance(content, list)
        imageBlock = next(block for block in content if isinstance(block, dict) and block.get("type") == "image_url")
        url: str = imageBlock["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")

        header, encoded = url.split(",", 1)
        decoded = base64.b64decode(encoded)
        reOpened = Image.open(BytesIO(decoded))
        assert reOpened.format == "JPEG"
        reOpened.load()

    def testToDictPassthroughWhenDefault(self) -> None:
        """toDict() with no supportedImageFormats preserves the original WebP format.

        Returns:
            None
        """
        webp = _webpBytes()
        msg = ModelImageMessage(role="user", content="look", image=bytearray(webp))

        rendered = msg.toDict()

        content = rendered["content"]
        assert isinstance(content, list)
        imageBlock = next(block for block in content if isinstance(block, dict) and block.get("type") == "image_url")
        url: str = imageBlock["image_url"]["url"]
        assert url.startswith("data:image/webp;base64,")
