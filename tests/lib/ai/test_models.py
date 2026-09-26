"""Tests for ModelStructuredResult, ModelRunResult.__str__, ModelImageMessage.toDict shape, and normalizeVisionImage.

Covers:
- ModelStructuredResult instantiation with all fields and with defaults.
- ModelStructuredResult.data defaults to None.
- __slots__ enforcement: setting result.data works; setting result.bogus raises
  AttributeError.
- str(result) includes the data field when set on a ModelStructuredResult.
- str() on a plain ModelRunResult does NOT include a data entry.
- Auto-iteration via __slots__ MRO walk.
- Per-field renderer overrides (_STR_RENDERERS).
- Default-skip rules (None, False, empty containers).
- Integer 0 tokens are NOT skipped.
- ModelImageMessage.toDict multimodal payload shape (regression: the text
  part must carry the OpenAI ``text`` key, not ``content``).
- ModelImagesMessage.toDict (native-vision Phase 2a): multi-image sibling —
  text block + one image_url block per image in list order, empty content
  omitting the text part, single-image parity with ModelImageMessage,
  per-image format conversion, self.images never mutated, and identical
  consecutive serialisations.
- normalizeVisionImage (native-vision Phase 1a): long-edge resize cap with
  LANCZOS, never upscaling, maxDimension=0 disabling the resize, animated
  sources collapsing to the first frame, alpha flattening for JPEG, PNG
  output, EXIF stripping, EXIF orientation 6/8 baked into the pixel layout,
  palette/bilevel sources converted to truecolor before resizing so LANCZOS
  applies, the JPEG/PNG-only output contract, JPEG quality clamping into
  1-95, and the never-raise contract (original bytes returned on corrupt
  input, unsupported target format, oversized-header rejection BEFORE
  decode, MIME-detection failure, and encoder failure — the latter three
  via mocks).
- normalizeVisionImageStrict (native-vision Phase 1b): the same pipeline
  failing CLOSED — every lenient fallback branch (oversized-header
  rejection, corrupt input, unsupported target format, MIME-detection
  failure, encoder failure) must yield None so the receipt-time store can
  skip storage instead of publishing oversized / EXIF-bearing originals.
"""

import base64
import logging
from io import BytesIO
from typing import Dict, Tuple
from unittest.mock import MagicMock, Mock

import pytest
from PIL import Image, ImageOps

from lib.ai.models import (
    ModelImageMessage,
    ModelImagesMessage,
    ModelResultStatus,
    ModelRunResult,
    ModelStructuredResult,
    normalizeVisionImage,
    normalizeVisionImageStrict,
)

# ============================================================================
# ModelStructuredResult — instantiation
# ============================================================================


def testModelStructuredResultAllFields() -> None:
    """Verify that ModelStructuredResult stores all explicitly passed fields.

    Returns:
        None
    """
    rawResult = {"id": "abc"}
    data = {"answer": 42}
    err = ValueError("boom")

    result = ModelStructuredResult(
        rawResult=rawResult,
        status=ModelResultStatus.FINAL,
        data=data,
        resultText='{"answer": 42}',
        error=err,
        inputTokens=10,
        outputTokens=5,
        totalTokens=15,
        cachedInputTokens=8,
        reasoningTokens=3,
        cost=0.0005,
    )

    assert result.status is ModelResultStatus.FINAL
    assert result.data == data
    assert result.resultText == '{"answer": 42}'
    assert result.error is err
    assert result.inputTokens == 10
    assert result.outputTokens == 5
    assert result.totalTokens == 15
    assert result.cachedInputTokens == 8
    assert result.reasoningTokens == 3
    assert result.cost == 0.0005
    assert result.result is rawResult
    assert result.isFallback is False


def testModelStructuredResultDefaults() -> None:
    """Verify that ModelStructuredResult defaults: data=None, resultText='', etc.

    Returns:
        None
    """
    result = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.ERROR,
    )

    assert result.data is None
    assert result.resultText == ""
    assert result.error is None
    assert result.inputTokens is None
    assert result.outputTokens is None
    assert result.totalTokens is None
    assert result.cachedInputTokens is None
    assert result.reasoningTokens is None
    assert result.cost is None


def testModelStructuredResultDataDefaultsToNone() -> None:
    """Verify that data attribute defaults to None without explicit kwarg.

    Returns:
        None
    """
    result = ModelStructuredResult(rawResult=None, status=ModelResultStatus.UNSPECIFIED)
    assert result.data is None


# ============================================================================
# __slots__ enforcement
# ============================================================================


def testModelStructuredResultSlotsDataAssignment() -> None:
    """Verify that assigning to result.data slot succeeds.

    Returns:
        None
    """
    result = ModelStructuredResult(rawResult=None, status=ModelResultStatus.FINAL)
    result.data = {"x": 1}
    assert result.data == {"x": 1}


def testModelStructuredResultSlotsRaisesOnUnknownAttr() -> None:
    """Verify that setting an undeclared attribute raises AttributeError.

    Returns:
        None
    """
    result = ModelStructuredResult(rawResult=None, status=ModelResultStatus.FINAL)
    with pytest.raises(AttributeError):
        result.bogus = 1  # type: ignore[attr-defined]


# ============================================================================
# __str__ — data field inclusion  (Phase 1 tests, updated for new format)
# ============================================================================


def testModelStructuredResultStrIncludesData() -> None:
    """Verify that str(result) includes the data field when data is set.

    Returns:
        None
    """
    result = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        data={"nCards": 3},
        resultText='{"nCards": 3}',
    )
    text = str(result)
    assert "data" in text
    assert "nCards" in text


def testModelStructuredResultStrDataNoneOmitted() -> None:
    """Verify that str(result) omits the data key when data is None.

    The new __str__ auto-iterates __slots__ and skips None values by default,
    so data=None must not appear in the output.

    Returns:
        None
    """
    result = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.ERROR,
        data=None,
    )
    text = str(result)
    # data=None is filtered by the default-skip rule (None -> omit)
    assert "data=" not in text


def testModelRunResultStrDoesNotIncludeDataKey() -> None:
    """Verify that a plain ModelRunResult.__str__ does not include a data key.

    The plain class has no 'data' slot, so MRO iteration never produces it.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="hello",
    )
    text = str(result)
    assert "data=" not in text


# ============================================================================
# __str__ — new auto-iteration / renderer tests
# ============================================================================


def testStrIteratesSlots() -> None:
    """__str__ includes expected fields and omits result/error/mediaData by default.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="hello",
    )
    result.setFallback(True)
    text = str(result)

    assert "status=FINAL" in text
    assert "resultText='hello'" in text
    assert "isFallback=True" in text
    # result slot has a renderer that always returns _OMIT
    assert "result=" not in text
    # error and mediaData are None → renderer returns _OMIT / default skips
    assert "error=" not in text
    assert "mediaData=" not in text
    # toolCalls is an empty list → default-skip (empty container)
    assert "toolCalls=" not in text


def testStrSkipsFalsyByDefault() -> None:
    """isFallback=False and isToolsUsed=False are omitted from output.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
    )
    # Both default to False
    text = str(result)
    assert "isFallback" not in text
    assert "isToolsUsed" not in text


def testStrShowsZeroTokens() -> None:
    """Integer 0 token counts are NOT filtered even though 0 is falsy.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        inputTokens=0,
        outputTokens=0,
        totalTokens=0,
    )
    text = str(result)
    assert "inputTokens=0" in text
    assert "outputTokens=0" in text
    assert "totalTokens=0" in text


def testStrRendersErrorCompactly() -> None:
    """error field is rendered as 'TypeName: message', not a full repr.

    The renderer returns a plain string, so it is emitted without extra
    quotes: ``error=ValueError: oops``.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.ERROR,
        error=ValueError("oops"),
    )
    text = str(result)
    assert "error=ValueError: oops" in text


def testStrRendersStatusByName() -> None:
    """status is rendered as the enum's symbolic name, not its repr.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.TRUNCATED_FINAL,
    )
    text = str(result)
    assert "status=TRUNCATED_FINAL" in text
    # Must NOT appear as the default enum repr
    assert "<ModelResultStatus.TRUNCATED_FINAL" not in text


def testStrOmitsRawResult() -> None:
    """The raw 'result' slot is always omitted from __str__ output.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult={"big": "object"},
        status=ModelResultStatus.FINAL,
    )
    text = str(result)
    assert "result=" not in text


def testStrRendersMediaDataLength() -> None:
    """mediaData is rendered as '<bytes len=N>' and mediaMimeType prints normally.

    The mediaData renderer returns a plain string, so it is emitted without
    extra quotes: ``mediaData=<bytes len=100>``.  mediaMimeType has no
    renderer so it falls through to the default ``repr()`` path, which
    wraps the string in single quotes.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        mediaData=b"x" * 100,
        mediaMimeType="image/png",
    )
    text = str(result)
    assert "mediaData=<bytes len=100>" in text
    assert "mediaMimeType='image/png'" in text


def testStrSubclassDataField() -> None:
    """ModelStructuredResult.__str__ starts with class name and includes data.

    Returns:
        None
    """
    result = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        data={"x": 1},
        resultText='{"x": 1}',
    )
    text = str(result)
    assert text.startswith("ModelStructuredResult(")
    assert "data={'x': 1}" in text
    assert "status=FINAL" in text
    assert "resultText='{\"x\": 1}'" in text


def testStrSubclassDataNoneOmitted() -> None:
    """data=None on ModelStructuredResult is omitted; error IS shown.

    Returns:
        None
    """
    result = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.ERROR,
        data=None,
        error=Exception("oops"),
    )
    text = str(result)
    assert "data=" not in text
    assert "error=" in text


# ============================================================================
# ModelImageMessage.toDict — multimodal payload shape
# ============================================================================


def _tinyPngBytes() -> bytes:
    """Return a tiny valid PNG image (4x4 green).

    Returns:
        bytes of a PNG-encoded image.
    """
    buf = BytesIO()
    Image.new("RGB", (4, 4), (0, 255, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _pngBytesOfColor(color: Tuple[int, int, int]) -> bytes:
    """Return a tiny valid PNG image (4x4) of the requested solid color.

    Distinct colors yield distinct base64 payloads, letting multi-image
    order tests tell the blocks apart.

    Args:
        color: RGB color tuple.

    Returns:
        bytes of a PNG-encoded image.
    """
    buf = BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="PNG")
    return buf.getvalue()


def _tinyWebpBytes() -> bytes:
    """Return a tiny valid WebP image (4x4 blue).

    Returns:
        bytes of a WebP-encoded image.
    """
    buf = BytesIO()
    Image.new("RGB", (4, 4), (0, 0, 255)).save(buf, format="WEBP")
    return buf.getvalue()


def _pixelRgb(image: Image.Image, x: int, y: int) -> Tuple[int, int, int]:
    """Read one pixel as an RGB int tuple (JPEG-tolerant channel checks).

    Args:
        image: PIL image to sample (already converted to RGB).
        x: Pixel x coordinate.
        y: Pixel y coordinate.

    Returns:
        (r, g, b) tuple of ints.
    """
    pixel = image.getpixel((x, y))
    assert isinstance(pixel, tuple) and len(pixel) == 3
    return (int(pixel[0]), int(pixel[1]), int(pixel[2]))


class TestModelImageMessageTextPart:
    """Regression: multimodal text part must carry the OpenAI ``text`` key.

    Before the fix, ``ModelImageMessage.toDict()`` emitted
    ``{"type": "text", "content": ...}`` for a non-empty prompt. Strict
    OpenAI-compatible upstreams reject that payload with ``400 text content
    parts must carry a string "text" (got undefined)``. The OpenAI chat
    schema requires ``{"type": "text", "text": "..."}``.
    """

    def testTextPartUsesTextKey(self) -> None:
        """A non-empty prompt renders a text part keyed by ``text``, not ``content``.

        Returns:
            None
        """
        msg = ModelImageMessage(role="user", content="Что изображено на фотографии?", image=bytearray(_tinyPngBytes()))

        rendered = msg.toDict()

        content = rendered["content"]
        assert isinstance(content, list)
        textBlocks = [block for block in content if isinstance(block, dict) and block.get("type") == "text"]
        assert len(textBlocks) == 1
        assert textBlocks[0]["text"] == "Что изображено на фотографии?"
        assert "content" not in textBlocks[0]

    def testTextPartPrecedesImagePart(self) -> None:
        """The text part is emitted before the image_url part.

        Returns:
            None
        """
        msg = ModelImageMessage(role="user", content="describe", image=bytearray(_tinyPngBytes()))

        rendered = msg.toDict()

        typesList = [block["type"] for block in rendered["content"] if isinstance(block, dict)]
        assert typesList == ["text", "image_url"]

    def testEmptyPromptOmitsTextPart(self) -> None:
        """An empty prompt emits no text part — only the image_url block.

        Pins the production image-parsing path (base.py / media.py), which
        sends the prompt as a separate system message and leaves the user
        message content empty.

        Returns:
            None
        """
        msg = ModelImageMessage(role="user", content="", image=bytearray(_tinyPngBytes()))

        rendered = msg.toDict()

        typesList = [block["type"] for block in rendered["content"] if isinstance(block, dict)]
        assert typesList == ["image_url"]


# ============================================================================
# ModelImagesMessage.toDict — multi-image payload shape (native-vision 2a)
# ============================================================================


class TestModelImagesMessage:
    """Tests for :class:`lib.ai.models.ModelImagesMessage` (Phase 2a infra).

    The multi-image sibling of ``ModelImageMessage`` must serialise every
    embedded image into its own ``image_url`` block, in list order, after
    the optional text block; convert each image independently when the
    target model's ``supportedImageFormats`` demand it; never mutate
    ``self.images`` (primary/fallback retries re-serialise from the
    original bytes); and stay stateless across consecutive calls.
    """

    def testMultiImageToDictEmitsTextAndImageBlocksInOrder(self) -> None:
        """Text + 3 images render as one text block then 3 image_url blocks in order.

        Each data URL must carry exactly the base64 of the corresponding
        input image at its position — distinct-color PNGs make an order
        mismatch detectable.

        Returns:
            None
        """
        pngRed = _pngBytesOfColor((255, 0, 0))
        pngGreen = _tinyPngBytes()
        pngBlue = _pngBytesOfColor((0, 0, 255))
        msg = ModelImagesMessage(
            role="user",
            content="Что изображено на фотографиях?",
            images=[bytearray(pngRed), bytearray(pngGreen), bytearray(pngBlue)],
        )

        rendered = msg.toDict()

        content = rendered["content"]
        assert isinstance(content, list)
        typesList = [block["type"] for block in content]
        assert typesList == ["text", "image_url", "image_url", "image_url"]
        textBlocks = [block for block in content if block["type"] == "text"]
        assert len(textBlocks) == 1
        assert textBlocks[0]["text"] == "Что изображено на фотографиях?"
        imageBlocks = [block for block in content if block["type"] == "image_url"]
        for block, sourceBytes in zip(imageBlocks, [pngRed, pngGreen, pngBlue]):
            expectedUrl = f"data:{_PNG_MIME};base64,{base64.b64encode(sourceBytes).decode('utf-8')}"
            assert block["image_url"]["url"] == expectedUrl

    def testEmptyContentOmitsTextPartButKeepsImages(self) -> None:
        """An empty prompt emits no text part — only the image_url blocks.

        Mirrors the production image-parsing convention of leaving the user
        message content empty; with N images the payload must still carry
        all N blocks.

        Returns:
            None
        """
        msg = ModelImagesMessage(
            role="user", content="", images=[bytearray(_tinyPngBytes()), bytearray(_tinyWebpBytes())]
        )

        rendered = msg.toDict()

        typesList = [block["type"] for block in rendered["content"]]
        assert typesList == ["image_url", "image_url"]

    def testSingleImageMatchesModelImageMessageShape(self) -> None:
        """A one-image ModelImagesMessage serialises identically to ModelImageMessage.

        The structural-shape contract: with the same role/content/source
        bytes the two classes must produce equal dicts, so downstream
        providers cannot tell them apart in the single-image case.

        Returns:
            None
        """
        png = _tinyPngBytes()
        multi = ModelImagesMessage(role="user", content="describe", images=[bytearray(png)])
        single = ModelImageMessage(role="user", content="describe", image=bytearray(png))

        assert multi.toDict() == single.toDict()

    def testPerImageFormatConversionMixedSources(self) -> None:
        """PNG + WebP sources both convert to image/jpeg when the model demands it.

        Conversion must run PER IMAGE independently: each block's payload
        must decode as JPEG regardless of the source format, and each decoded
        image must retain its OWN source color — a bug reusing the first
        converted image for every block would swap the colors.

        Returns:
            None
        """
        pngGreen = _tinyPngBytes()  # 4x4 green
        webpBlue = _tinyWebpBytes()  # 4x4 blue
        msg = ModelImagesMessage(role="user", content="look", images=[bytearray(pngGreen), bytearray(webpBlue)])

        rendered = msg.toDict(supportedImageFormats=[_JPEG_MIME])

        imageBlocks = [block for block in rendered["content"] if block["type"] == "image_url"]
        assert len(imageBlocks) == 2
        for block in imageBlocks:
            url = block["image_url"]["url"]
            assert url.startswith(f"data:{_JPEG_MIME};base64,")
            payload = base64.b64decode(url.split(",", 1)[1])
            out = Image.open(BytesIO(payload))
            assert out.format == "JPEG"
            out.load()

        # JPEG is lossy: assert the dominant channel per position with a
        # tolerance instead of exact pixel equality.
        decodedColors = []
        for block in imageBlocks:
            payload = base64.b64decode(block["image_url"]["url"].split(",", 1)[1])
            decodedColors.append(Image.open(BytesIO(payload)).convert("RGB"))
        greenPixel = _pixelRgb(decodedColors[0], 2, 2)
        bluePixel = _pixelRgb(decodedColors[1], 2, 2)
        assert greenPixel[0] < 64 and greenPixel[1] > 192 and greenPixel[2] < 64
        assert bluePixel[0] < 64 and bluePixel[1] < 64 and bluePixel[2] > 192

    def testMixedPassthroughAndConversion(self) -> None:
        """A PNG-accepting model keeps PNG bytes and converts only the WebP one.

        With ``supportedImageFormats=["image/jpeg", "image/png"]`` a
        PNG source needs no conversion (its block must carry the EXACT
        original base64 under the PNG MIME) while the WebP source is
        re-encoded to the FIRST listed format (JPEG).

        Returns:
            None
        """
        pngRed = _pngBytesOfColor((255, 0, 0))
        webpBlue = _tinyWebpBytes()
        msg = ModelImagesMessage(role="user", content="look", images=[bytearray(pngRed), bytearray(webpBlue)])

        rendered = msg.toDict(supportedImageFormats=["image/jpeg", "image/png"])

        imageBlocks = [block for block in rendered["content"] if block["type"] == "image_url"]
        assert len(imageBlocks) == 2

        pngUrl = imageBlocks[0]["image_url"]["url"]
        assert pngUrl == f"data:{_PNG_MIME};base64,{base64.b64encode(pngRed).decode('utf-8')}"

        webpUrl = imageBlocks[1]["image_url"]["url"]
        assert webpUrl.startswith(f"data:{_JPEG_MIME};base64,")
        converted = Image.open(BytesIO(base64.b64decode(webpUrl.split(",", 1)[1])))
        assert converted.format == "JPEG"
        converted.load()
        bluePixel = _pixelRgb(converted.convert("RGB"), 2, 2)
        assert bluePixel[0] < 64 and bluePixel[1] < 64 and bluePixel[2] > 192

    def testImagesNotMutatedByToDictConversion(self) -> None:
        """toDict with conversion active leaves self.images byte-identical.

        Pins the derive-into-locals contract: primary-then-fallback
        serialisation must always restart from the original bytes.

        Returns:
            None
        """
        png = _tinyPngBytes()
        webp = _tinyWebpBytes()
        images = [bytearray(png), bytearray(webp)]
        msg = ModelImagesMessage(role="user", content="look", images=images)

        msg.toDict(supportedImageFormats=[_JPEG_MIME])

        assert len(msg.images) == 2
        assert bytes(msg.images[0]) == png
        assert bytes(msg.images[1]) == webp

    def testConsecutiveToDictCallsIdentical(self) -> None:
        """Two consecutive toDict calls (conversion active) produce identical output.

        No cross-call state: the second serialisation must be exactly the
        first, proving the conversion is derived fresh each time.

        Returns:
            None
        """
        msg = ModelImagesMessage(
            role="user",
            content="look",
            images=[bytearray(_tinyPngBytes()), bytearray(_tinyWebpBytes())],
        )

        first = msg.toDict(supportedImageFormats=[_JPEG_MIME])
        second = msg.toDict(supportedImageFormats=[_JPEG_MIME])

        assert first == second


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


class TestNormalizeVisionImage:
    """Tests for :func:`lib.ai.models.normalizeVisionImage` (Phase 1a infra)."""

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
        """outputFormat="image/png" yields PNG bytes and the image/png MIME.

        Returns:
            None
        """
        original = _jpegBytesOfSize(10, 10)

        result, mime = normalizeVisionImage(original, maxDimension=2048, outputFormat=_PNG_MIME)

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
        with caplog.at_level(logging.ERROR, logger="lib.ai.models"):
            result, mime = normalizeVisionImage(corrupt, maxDimension=100)
        # Original bytes returned untouched (graceful degradation; never raises).
        assert result == corrupt
        assert any(record.levelno == logging.ERROR for record in caplog.records)

    @pytest.mark.parametrize("outputFormat", ["image/webp", "image/gif", "image/bmp"])
    def testUnsupportedOutputFormatReturnsOriginal(self, outputFormat: str, caplog: pytest.LogCaptureFixture) -> None:
        """An output MIME outside the JPEG/PNG contract degrades gracefully.

        Normalization output is restricted to JPEG/PNG (design v1 §4) even
        though the shared ``_MIME_TO_PIL_FORMAT`` also maps WebP/GIF — those
        are accepted as send-time INPUT formats by
        :func:`convertImageIfNeeded`, never as normalized storage formats.
        Original bytes are returned unchanged with the detected source MIME
        and a WARNING (not ERROR) is logged.

        Args:
            outputFormat: Unsupported target MIME under test.
            caplog: pytest fixture capturing log records.

        Returns:
            None
        """
        original = _jpegBytesOfSize(10, 10)
        with caplog.at_level(logging.WARNING, logger="lib.ai.models"):
            result, mime = normalizeVisionImage(original, maxDimension=100, outputFormat=outputFormat)
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

        result, mime = normalizeVisionImage(original, maxDimension=4, outputFormat=_PNG_MIME)

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

        with caplog.at_level(logging.ERROR, logger="lib.ai.models"):
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

        monkeypatch.setattr("lib.ai.models.magic.from_buffer", failingFromBuffer)

        with caplog.at_level(logging.ERROR, logger="lib.ai.models"):
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
        re-encode blows up.

        Args:
            caplog: pytest fixture capturing log records.
            monkeypatch: pytest fixture for temporary attribute patching.

        Returns:
            None
        """
        original = _jpegBytesOfSize(10, 10)
        saveMock = Mock(side_effect=OSError("simulated encoder failure"))
        monkeypatch.setattr(Image.Image, "save", saveMock)

        with caplog.at_level(logging.ERROR, logger="lib.ai.models"):
            result, mime = normalizeVisionImage(original)

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
        explicitly, produce a valid image, and warn.

        Args:
            quality: Out-of-range quality value under test.
            expectedClamped: The clamped value expected in the warning.
            caplog: pytest fixture capturing log records.

        Returns:
            None
        """
        original = _jpegBytesOfSize(10, 10)

        with caplog.at_level(logging.WARNING, logger="lib.ai.models"):
            result, mime = normalizeVisionImage(original, quality=quality)

        assert mime == _JPEG_MIME
        out = Image.open(BytesIO(result))
        assert out.format == "JPEG"
        out.load()
        assert any(record.levelno == logging.WARNING for record in caplog.records)
        assert f"clamped to {expectedClamped}" in caplog.text


class TestNormalizeVisionImageStrict:
    """Tests for :func:`lib.ai.models.normalizeVisionImageStrict` (Phase 1b).

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

        with caplog.at_level(logging.ERROR, logger="lib.ai.models"):
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

        with caplog.at_level(logging.ERROR, logger="lib.ai.models"):
            result = normalizeVisionImageStrict(corrupt, maxDimension=100)

        assert result is None
        assert any(record.levelno == logging.ERROR for record in caplog.records)

    @pytest.mark.parametrize("outputFormat", ["image/webp", "image/gif", "image/bmp"])
    def testUnsupportedOutputFormatReturnsNone(self, outputFormat: str, caplog: pytest.LogCaptureFixture) -> None:
        """An output MIME outside the JPEG/PNG contract yields None.

        Args:
            outputFormat: Unsupported target MIME under test.
            caplog: pytest fixture capturing log records.

        Returns:
            None
        """
        original = _jpegBytesOfSize(10, 10)

        with caplog.at_level(logging.WARNING, logger="lib.ai.models"):
            result = normalizeVisionImageStrict(original, maxDimension=100, outputFormat=outputFormat)

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

        monkeypatch.setattr("lib.ai.models.magic.from_buffer", failingFromBuffer)

        with caplog.at_level(logging.ERROR, logger="lib.ai.models"):
            result = normalizeVisionImageStrict(original)

        assert result is None
        assert any(record.levelno == logging.ERROR for record in caplog.records)

    def testEncoderFailureReturnsNone(self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
        """A Pillow encoder failure on valid input yields None.

        Args:
            caplog: pytest fixture capturing log records.
            monkeypatch: pytest fixture for temporary attribute patching.

        Returns:
            None
        """
        original = _jpegBytesOfSize(10, 10)
        saveMock = Mock(side_effect=OSError("simulated encoder failure"))
        monkeypatch.setattr(Image.Image, "save", saveMock)

        with caplog.at_level(logging.ERROR, logger="lib.ai.models"):
            result = normalizeVisionImageStrict(original)

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

        with caplog.at_level(logging.ERROR, logger="lib.ai.models"):
            strict = normalizeVisionImageStrict(corrupt, maxDimension=100)
            lenientBytes, _lenientMime = normalizeVisionImage(corrupt, maxDimension=100)

        assert strict is None
        assert lenientBytes == corrupt
