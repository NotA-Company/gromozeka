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
- ModelImagesMessage.toDict multimodal payload shape (regression: the text
  part must carry the OpenAI ``text`` key, not ``content``).
- ModelImagesMessage.toDict (native-vision Phase 2a): image message class —
  text block + one image_url block per image in list order, empty content
  omitting the text part, per-image format conversion, self.images never
  mutated, and identical consecutive serialisations.
- ModelImagesMessage.toDict (alpha compositing): ``alphaBackground`` threads
  through to ``convertImageIfNeeded`` — pure parameter threading (lib/ stays
  free of bot deps; config-aware internal callers pass it in a later phase,
  lib-internal callers keep the ADAPTIVE default).

Image-manipulation coverage (convertImageIfNeeded, normalizeVisionImage,
normalizeVisionImageStrict, VisionOutputImageFormat, _stripJpegExif) lives in
``tests/lib/ai/test_imaging.py`` and ``tests/lib/ai/test_image_format_conversion.py``.
"""

import base64
from io import BytesIO
from typing import Optional, Tuple

import pytest
from PIL import Image

from lib.ai.imaging import AlphaBackground
from lib.ai.models import (
    ModelImagesMessage,
    ModelMessage,
    ModelMessageDescriptionResolver,
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
# ModelImagesMessage.toDict — multimodal payload shape
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


class TestModelImagesMessageTextPart:
    """Regression: multimodal text part must carry the OpenAI ``text`` key.

    Before the fix, ``ModelImagesMessage.toDict()`` emitted
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
        msg = ModelImagesMessage(
            role="user", content="Что изображено на фотографии?", images=[bytearray(_tinyPngBytes())]
        )

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
        msg = ModelImagesMessage(role="user", content="describe", images=[bytearray(_tinyPngBytes())])

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
        msg = ModelImagesMessage(role="user", content="", images=[bytearray(_tinyPngBytes())])

        rendered = msg.toDict()

        typesList = [block["type"] for block in rendered["content"] if isinstance(block, dict)]
        assert typesList == ["image_url"]


# ============================================================================
# ModelImagesMessage.toDict — multi-image payload shape (native-vision 2a)
# ============================================================================


class TestModelImagesMessage:
    """Tests for :class:`lib.ai.models.ModelImagesMessage` (Phase 2a infra).

    The image message class must serialise every
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


class TestModelImagesMessageImagesDefaultIsolation:
    """Regression: ``images`` must never be a shared mutable default.

    The constructor used to declare ``images: List[bytearray] = []`` — a
    single list object created once at function-definition time and aliased
    by EVERY message constructed without an explicit ``images``. Appending
    an image to one such message silently made every other one serialize it
    too (potential cross-conversation image disclosure).
    """

    def testDefaultConstructedMessagesDoNotShareImagesList(self) -> None:
        """Two messages built without ``images`` each own a fresh empty list.

        Must fail for an implementation whose default is a shared
        function-definition-time list: independent messages would alias one
        list, so appending to one leaks into the other's serialization.

        Returns:
            None
        """
        first = ModelImagesMessage(role="user", content="first")
        second = ModelImagesMessage(role="user", content="second")

        assert first.images == []
        assert second.images == []
        assert first.images is not second.images

        first.images.append(bytearray(b"FIRST-ONLY-IMAGE"))

        assert second.images == []
        assert [bytes(image) for image in first.images] == [b"FIRST-ONLY-IMAGE"]

    def testExplicitImagesListIsCopiedNotAliased(self) -> None:
        """A caller-passed list is copied; later caller mutation is invisible.

        The message owns its list: post-construction mutation of the
        caller's list must not change what the message serializes.

        Returns:
            None
        """
        callerList = [bytearray(b"KEEP")]
        message = ModelImagesMessage(role="user", content="snapshot", images=callerList)

        assert message.images == callerList
        assert message.images is not callerList

        callerList.append(bytearray(b"APPENDED-AFTER-CONSTRUCTION"))

        assert [bytes(image) for image in message.images] == [b"KEEP"]


async def _resolveDescription() -> Optional[str]:
    """Fixed-description async resolver stub for descriptionResolver tests.

    Returns:
        Optional[str]: A fixed non-empty description string.
    """
    return "a red square"


# ============================================================================
# ModelMessage.descriptionResolver — metadata-only field (native-vision v2 §4.1)
# ============================================================================


class TestModelMessageDescriptionResolver:
    """Tests for the ``descriptionResolver`` metadata field (Phase A, inert).

    The field mirrors ``source``: carried in-memory only and NEVER
    serialized — absent from ``toDict`` output (hence invisible to
    providers, the token estimator, and JSON logs via ``toLogMessage``) and
    never read back by ``fromDict``/``fromDictList``. Defaults to ``None``
    on every message class, and ``ModelImagesMessage.__init__`` passes the
    ``source`` / ``descriptionResolver`` kwargs through to the parent
    constructor.
    """

    def testDefaultsToNoneOnAllMessageClasses(self) -> None:
        """Every message class defaults ``descriptionResolver`` to None.

        Returns:
            None
        """
        for message in (
            ModelMessage(role="user", content="text"),
            ModelImagesMessage(role="user", content="text", images=[bytearray(b"IMG")]),
        ):
            assert message.descriptionResolver is None

    def testAbsentFromToDict(self) -> None:
        """A set resolver never appears in ``toDict`` output.

        Proven by equality: the serialization of a message carrying a
        resolver is byte-identical to an otherwise-equal message without
        one — for both the base class and the multi-image subclass payload.

        Returns:
            None
        """
        withResolver = ModelMessage(role="user", content="text", weight=3, descriptionResolver=_resolveDescription)
        withoutResolver = ModelMessage(role="user", content="text", weight=3)
        assert withResolver.toDict() == withoutResolver.toDict()

        imagesWith = ModelImagesMessage(
            role="user", content="album", images=[bytearray(b"1")], descriptionResolver=_resolveDescription
        )
        imagesWithout = ModelImagesMessage(role="user", content="album", images=[bytearray(b"1")])
        assert imagesWith.toDict() == imagesWithout.toDict()

    def testAbsentFromFromDictRoundTrip(self) -> None:
        """``fromDict``/``fromDictList`` never read the resolver back.

        Returns:
            None
        """
        message = ModelMessage(role="user", content="text", weight=3, descriptionResolver=_resolveDescription)

        restored = ModelMessage.fromDict(message.toDict())
        assert restored.descriptionResolver is None

        restoredList = ModelMessage.fromDictList([message.toDict()])
        assert restoredList[0].descriptionResolver is None

        # Deserialization must IGNORE a ``descriptionResolver`` key present in
        # the INPUT dict (the field is never read back): a payload carrying one
        # — hand-crafted, provider-echoed, or future-drifted JSON — must not
        # poison the restored message.
        poisoned = {"role": "user", "content": "text", "descriptionResolver": "should be ignored"}
        restoredPoisoned = ModelMessage.fromDict(poisoned)
        assert restoredPoisoned.descriptionResolver is None

        restoredPoisonedList = ModelMessage.fromDictList([poisoned])
        assert restoredPoisonedList[0].descriptionResolver is None

    def testAbsentFromToLogMessage(self) -> None:
        """A set resolver never appears in ``toLogMessage`` output.

        Returns:
            None
        """
        resolver: ModelMessageDescriptionResolver = _resolveDescription
        withResolver = ModelImagesMessage(
            role="user", content="album", images=[bytearray(b"1")], descriptionResolver=resolver
        )
        withoutResolver = ModelImagesMessage(role="user", content="album", images=[bytearray(b"1")])

        logLine = withResolver.toLogMessage()

        assert "_resolveDescription" not in logLine
        assert logLine == withoutResolver.toLogMessage()

    def testImagesMessageKwargsPassThrough(self) -> None:
        """``ModelImagesMessage`` lands ``source``/``descriptionResolver`` on the instance.

        Both kwargs are needed by Phase B's construction-time attach; this
        pins the pass-through so a silent kwarg drop cannot reintroduce
        itself.

        Returns:
            None
        """
        source = object()
        resolver: ModelMessageDescriptionResolver = _resolveDescription

        message = ModelImagesMessage(
            role="assistant",
            content="album",
            images=[bytearray(b"1"), bytearray(b"2")],
            source=source,
            descriptionResolver=resolver,
        )

        assert message.source is source
        assert message.descriptionResolver is resolver
        assert message.images == [bytearray(b"1"), bytearray(b"2")]


# ============================================================================
# ModelImagesMessage.toDict — alphaBackground threading (alpha compositing)
# ============================================================================


def _whiteContentOnTransparentPngBytes() -> bytes:
    """Return a 32x32 RGBA PNG: white content square on fully transparent margins.

    The RGB under the transparent margins is white too — the shape real
    white-on-transparent stickers have — so the old alpha-DISCARD convert
    rendered the whole image white/garbage instead of compositing.

    Returns:
        bytes of an RGBA PNG-encoded image.
    """
    img = Image.new("RGBA", (32, 32), (255, 255, 255, 0))
    content = Image.new("RGBA", (12, 12), (255, 255, 255, 255))
    img.paste(content, (10, 10))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestModelImagesMessageAlphaBackground:
    """``toDict`` forwards ``alphaBackground`` into ``convertImageIfNeeded``.

    Pure parameter threading (lib/ must stay free of bot deps): config-aware
    internal callers pass the value in (a later phase); lib-internal callers
    keep the ADAPTIVE default. Two OPPOSITE forced backgrounds over one
    fixture prove the parameter really reaches the converter — dropping the
    kwarg would render both serialisations identically.
    """

    def testToDictForwardsAlphaBackgroundToImageConversion(self) -> None:
        """Forced BLACK vs forced WHITE produce contrasting composite backgrounds.

        White content on transparent margins, JPEG-only model (conversion
        mandatory): with BLACK the margins must composite to black and the
        content stay visible-white; with WHITE everything must be white
        (the documented forced-background trade-off).

        Returns:
            None
        """
        png = _whiteContentOnTransparentPngBytes()
        msg = ModelImagesMessage(role="user", content="look", images=[bytearray(png)])

        renderedBlack = msg.toDict(supportedImageFormats=[_JPEG_MIME], alphaBackground=AlphaBackground.BLACK)
        renderedWhite = msg.toDict(supportedImageFormats=[_JPEG_MIME], alphaBackground=AlphaBackground.WHITE)

        for rendered, marginIsLight in ((renderedBlack, False), (renderedWhite, True)):
            content = rendered["content"]
            assert isinstance(content, list)
            imageBlock = next(block for block in content if block.get("type") == "image_url")
            url = imageBlock["image_url"]["url"]
            assert url.startswith(f"data:{_JPEG_MIME};base64,")
            rgb = Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
            for corner in ((2, 2), (29, 2), (2, 29), (29, 29)):
                channels = _pixelRgb(rgb, *corner)
                if marginIsLight:
                    assert all(
                        channel > 200 for channel in channels
                    ), f"expected white margin at {corner}, got {channels}"
                else:
                    assert all(
                        channel < 60 for channel in channels
                    ), f"expected black margin at {corner}, got {channels}"
            contentChannels = _pixelRgb(rgb, 15, 15)
            assert all(
                channel > 200 for channel in contentChannels
            ), f"expected visible white content, got {contentChannels}"
