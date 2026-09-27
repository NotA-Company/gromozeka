"""Tests for ModelStructuredResult, ModelRunResult.__str__, and the image message classes' toDict payloads.

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

Image-manipulation coverage (convertImageIfNeeded, normalizeVisionImage,
normalizeVisionImageStrict, VisionOutputImageFormat, _stripJpegExif) lives in
``tests/lib/ai/test_imaging.py`` and ``tests/lib/ai/test_image_format_conversion.py``.
"""

import base64
from io import BytesIO
from typing import Tuple

import pytest
from PIL import Image

from lib.ai.models import (
    ModelImageMessage,
    ModelImagesMessage,
    ModelResultStatus,
    ModelRunResult,
    ModelStructuredResult,
)

#: MIME types python-magic reports for the factory images below. Shared with
#: ``tests/lib/ai/test_imaging.py``, which keeps its own copy (constants were
#: split with the image-manipulation tests during the lib.ai.imaging move).
_JPEG_MIME = "image/jpeg"
_PNG_MIME = "image/png"


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
