"""Tests for stripImagesForCondensing (internal/services/llm/service.py).

Covers the Wave C description-marker contract and the native-vision v2
lazy-resolver consumption (§4.6) at the unit level:

- Plain messages pass through IDENTITY (same instance), never touched —
  including plain messages that carry a resolver (it stays UNINVOKED).
- Image-bearing messages are swapped to plain text-only copies that preserve
  role / contentKey / weight / source (existing envelope contract).
- When the envelope text carries NO media description and no resolver
  resolves, a short marker is appended so a text-only condenser knows an
  image was there: singular form for ``ModelImageMessage``, count-bearing
  form (grammatical pluralization) for ``ModelImagesMessage``.
- When the message carries a ``descriptionResolver`` and it resolves to
  truthy text, the resolved description is injected wrapped in
  ``<media-description>...</media-description>`` (the TEXT envelope's tag)
  instead of the marker; the resolver is NOT copied onto the stripped copy,
  so re-stripping can never re-invoke it.
- When the envelope text DOES carry a media description — a non-empty
  ``"mediaDescription"`` key (JSON envelope, mirrored from
  ``EnsuredMessage.formatForLLM``) or a ``<media-description>`` block (TEXT
  envelope) — no marker is appended, the content is preserved exactly, and
  the resolver is never invoked (lazy consumption).
"""

import json
from unittest.mock import AsyncMock

from internal.services.llm.service import stripImagesForCondensing
from lib.ai.models import ModelImageMessage, ModelImagesMessage, ModelMessage


class TestStripImagesForCondensingMarker:
    """Unit tests for the stripped-copy envelope and the description marker."""

    async def testPlainMessageIdentity(self) -> None:
        """A plain message is returned as the SAME instance, no marker logic.

        Returns:
            None
        """
        message = ModelMessage(role="user", content="just text")
        assert await stripImagesForCondensing(message) is message

    async def testSingleImageWithoutDescriptionGetsSingularMarker(self) -> None:
        """A ModelImageMessage without a description gains the singular marker.

        Returns:
            None
        """
        source = object()
        message = ModelImageMessage(role="assistant", content="look at this", image=bytearray(b"IMG"))
        # Non-default envelope fields: preservation must be proven against
        # real values (defaults passing through defaults proves nothing).
        message.contentKey = "text"
        message.weight = 7
        message.source = source

        stripped = await stripImagesForCondensing(message)

        assert type(stripped) is ModelMessage
        assert stripped.content == "look at this\n[image attached, omitted for condensing]"
        # Envelope preserved on the copy.
        assert stripped.role == "assistant"
        assert stripped.contentKey == "text"
        assert stripped.weight == 7
        assert stripped.source is source
        # The original is untouched.
        assert message.content == "look at this"

    async def testMultiImageMarkerCarriesCount(self) -> None:
        """A multi-image message gains the count-bearing marker.

        Returns:
            None
        """
        message = ModelImagesMessage(role="user", content="album", images=[bytearray(b"1"), bytearray(b"2")])

        stripped = await stripImagesForCondensing(message)

        assert type(stripped) is ModelMessage
        assert stripped.content == "album\n[2 images attached, omitted for condensing]"

    async def testMultiImageSingleImageUsesGrammaticalSingular(self) -> None:
        """A 1-image ModelImagesMessage reads "1 image", not "1 images".

        Returns:
            None
        """
        message = ModelImagesMessage(role="user", content="one pic", images=[bytearray(b"1")])

        stripped = await stripImagesForCondensing(message)

        assert stripped.content == "one pic\n[1 image attached, omitted for condensing]"

    async def testJsonEnvelopeWithDescriptionGetsNoMarker(self) -> None:
        """A JSON envelope carrying ``mediaDescription`` is preserved exactly.

        Mirrors the ``EnsuredMessage.formatForLLM`` JSON rendering, which
        emits the ``mediaDescription`` key only when non-empty. The
        description-bearing envelope also short-circuits the resolver:
        lazy consumption means it is never invoked.

        Returns:
            None
        """
        content = json.dumps(
            {"login": "user1", "date": "1970-01-01T00:00:00", "text": "look", "mediaDescription": "a red square"}
        )
        source = object()
        message = ModelImageMessage(role="assistant", content=content, image=bytearray(b"IMG"))
        message.contentKey = "text"
        message.weight = 3
        message.source = source
        resolver = AsyncMock(return_value="should never resolve")
        message.descriptionResolver = resolver

        stripped = await stripImagesForCondensing(message)

        # Preserved exactly: no marker appended, envelope rides along.
        assert stripped.content == content
        assert stripped.role == "assistant"
        assert stripped.contentKey == "text"
        assert stripped.weight == 3
        assert stripped.source is source
        # Lazy: an envelope that already carries a description never pays
        # the resolver wait.
        resolver.assert_not_awaited()
        resolver.assert_not_called()

    async def testTextEnvelopeWithDescriptionGetsNoMarker(self) -> None:
        """A TEXT envelope with a ``<media-description>`` block is preserved.

        Mirrors the ``EnsuredMessage.formatForLLM`` TEXT rendering: the
        description block is prepended to the message text. The resolver
        stays uninvoked (lazy consumption).

        Returns:
            None
        """
        content = "<media-description>a red square</media-description>\n\nlook"
        source = object()
        message = ModelImagesMessage(role="system", content=content, images=[bytearray(b"1"), bytearray(b"2")])
        message.contentKey = "text"
        message.weight = 5
        message.source = source
        resolver = AsyncMock(return_value="should never resolve")
        message.descriptionResolver = resolver

        stripped = await stripImagesForCondensing(message)

        # Preserved exactly: no marker appended, envelope rides along.
        assert stripped.content == content
        assert stripped.role == "system"
        assert stripped.contentKey == "text"
        assert stripped.weight == 5
        assert stripped.source is source
        resolver.assert_not_awaited()
        resolver.assert_not_called()

    async def testEmptyContentStillGetsMarker(self) -> None:
        """An image message with empty text gains only the marker.

        Returns:
            None
        """
        message = ModelImageMessage(role="user", content="", image=bytearray(b"IMG"))

        stripped = await stripImagesForCondensing(message)

        assert stripped.content == "\n[image attached, omitted for condensing]"


class TestStripImagesForCondensingResolver:
    """Lazy descriptionResolver consumption (native-vision v2 §4.6).

    When the envelope text carries no media description, the resolver is
    awaited once; a truthy result is injected as
    ``<media-description>...</media-description>``, a ``None``/empty result
    falls back to today's count-aware markers, and the stripped copy never
    carries the resolver (it was consumed — re-stripping cannot re-invoke).
    """

    async def testResolvedTextInjectedAsMediaDescription(self) -> None:
        """A truthy resolver result is injected after the content, not the marker.

        Returns:
            None
        """
        source = object()
        resolver = AsyncMock(return_value="a red square on a green table")
        message = ModelImageMessage(role="assistant", content="look at this", image=bytearray(b"IMG"))
        message.contentKey = "text"
        message.weight = 7
        message.source = source
        message.descriptionResolver = resolver

        stripped = await stripImagesForCondensing(message)

        assert stripped.content == "look at this\n<media-description>a red square on a green table</media-description>"
        # Envelope preserved on the copy; no marker alongside the injection.
        assert stripped.role == "assistant"
        assert stripped.contentKey == "text"
        assert stripped.weight == 7
        assert stripped.source is source
        assert "[image attached" not in stripped.content
        resolver.assert_awaited_once()

    async def testResolvedTextInjectedOnMultiImageMessage(self) -> None:
        """A ModelImagesMessage with a resolving resolver gets the injection, not the count marker.

        Returns:
            None
        """
        resolver = AsyncMock(return_value="two dogs playing")
        message = ModelImagesMessage(
            role="user",
            content="album",
            images=[bytearray(b"1"), bytearray(b"2")],
            descriptionResolver=resolver,
        )

        stripped = await stripImagesForCondensing(message)

        assert stripped.content == "album\n<media-description>two dogs playing</media-description>"
        assert "images attached" not in stripped.content
        resolver.assert_awaited_once()

    async def testResolverReturningNoneFallsBackToCountMarker(self) -> None:
        """A resolver resolving to None falls back to the count-aware marker.

        Returns:
            None
        """
        resolver = AsyncMock(return_value=None)
        message = ModelImagesMessage(
            role="user",
            content="album",
            images=[bytearray(b"1"), bytearray(b"2")],
            descriptionResolver=resolver,
        )

        stripped = await stripImagesForCondensing(message)

        assert stripped.content == "album\n[2 images attached, omitted for condensing]"
        resolver.assert_awaited_once()

    async def testResolverReturningEmptyStringFallsBackToSingularMarker(self) -> None:
        """A resolver resolving to "" (empty) falls back to the marker.

        Empty means "nothing resolved" (timeout, parse failure), same as
        ``None``.

        Returns:
            None
        """
        resolver = AsyncMock(return_value="")
        message = ModelImageMessage(role="user", content="look", image=bytearray(b"IMG"))
        message.descriptionResolver = resolver

        stripped = await stripImagesForCondensing(message)

        assert stripped.content == "look\n[image attached, omitted for condensing]"
        resolver.assert_awaited_once()

    async def testStrippedCopyDropsResolver(self) -> None:
        """The stripped copy carries NO resolver — re-stripping never re-invokes.

        The resolver is consumed by the first strip: the output message's
        ``descriptionResolver`` is None, and a second strip of that output
        (whose content now carries the injected description, which the
        lazy gate honours anyway) cannot invoke the original closure again.

        Returns:
            None
        """
        resolver = AsyncMock(return_value="a red square")
        message = ModelImageMessage(role="user", content="look", image=bytearray(b"IMG"))
        message.descriptionResolver = resolver

        stripped = await stripImagesForCondensing(message)
        assert stripped.descriptionResolver is None
        assert stripped.content == "look\n<media-description>a red square</media-description>"

        restripped = await stripImagesForCondensing(stripped)

        # The injected description is preserved verbatim (lazy gate), the
        # resolver was never invoked a second time.
        assert restripped.content == "look\n<media-description>a red square</media-description>"
        resolver.assert_awaited_once()

    async def testNonImageMessageWithResolverReturnedAsIs(self) -> None:
        """A plain message carrying a resolver is returned as-is, resolver uninvoked.

        Only image-bearing messages consume resolvers; a plain message is
        the SAME instance with its resolver untouched for later rounds.

        Returns:
            None
        """
        resolver = AsyncMock(return_value="should never resolve")
        message = ModelMessage(role="user", content="just text", descriptionResolver=resolver)

        stripped = await stripImagesForCondensing(message)

        assert stripped is message
        assert stripped.descriptionResolver is resolver
        resolver.assert_not_awaited()
        resolver.assert_not_called()
