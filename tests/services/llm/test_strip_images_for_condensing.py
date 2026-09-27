"""Tests for stripImagesForCondensing (internal/services/llm/service.py).

Covers the Wave C description-marker contract at the unit level:

- Plain messages pass through IDENTITY (same instance), never touched.
- Image-bearing messages are swapped to plain text-only copies that preserve
  role / contentKey / weight / source (existing envelope contract).
- When the envelope text carries NO media description, a short marker is
  appended so a text-only condenser knows an image was there: singular form
  for ``ModelImageMessage``, count-bearing form (grammatical pluralization)
  for ``ModelImagesMessage``.
- When the envelope text DOES carry a media description — a non-empty
  ``"mediaDescription"`` key (JSON envelope, mirrored from
  ``EnsuredMessage.formatForLLM``) or a ``<media-description>`` block (TEXT
  envelope) — no marker is appended and the content is preserved exactly.
"""

import json

from internal.services.llm.service import stripImagesForCondensing
from lib.ai.models import ModelImageMessage, ModelImagesMessage, ModelMessage


class TestStripImagesForCondensingMarker:
    """Unit tests for the stripped-copy envelope and the description marker."""

    def testPlainMessageIdentity(self) -> None:
        """A plain message is returned as the SAME instance, no marker logic.

        Returns:
            None
        """
        message = ModelMessage(role="user", content="just text")
        assert stripImagesForCondensing(message) is message

    def testSingleImageWithoutDescriptionGetsSingularMarker(self) -> None:
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

        stripped = stripImagesForCondensing(message)

        assert type(stripped) is ModelMessage
        assert stripped.content == "look at this\n[image attached, omitted for condensing]"
        # Envelope preserved on the copy.
        assert stripped.role == "assistant"
        assert stripped.contentKey == "text"
        assert stripped.weight == 7
        assert stripped.source is source
        # The original is untouched.
        assert message.content == "look at this"

    def testMultiImageMarkerCarriesCount(self) -> None:
        """A multi-image message gains the count-bearing marker.

        Returns:
            None
        """
        message = ModelImagesMessage(role="user", content="album", images=[bytearray(b"1"), bytearray(b"2")])

        stripped = stripImagesForCondensing(message)

        assert type(stripped) is ModelMessage
        assert stripped.content == "album\n[2 images attached, omitted for condensing]"

    def testMultiImageSingleImageUsesGrammaticalSingular(self) -> None:
        """A 1-image ModelImagesMessage reads "1 image", not "1 images".

        Returns:
            None
        """
        message = ModelImagesMessage(role="user", content="one pic", images=[bytearray(b"1")])

        stripped = stripImagesForCondensing(message)

        assert stripped.content == "one pic\n[1 image attached, omitted for condensing]"

    def testJsonEnvelopeWithDescriptionGetsNoMarker(self) -> None:
        """A JSON envelope carrying ``mediaDescription`` is preserved exactly.

        Mirrors the ``EnsuredMessage.formatForLLM`` JSON rendering, which
        emits the ``mediaDescription`` key only when non-empty.

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

        stripped = stripImagesForCondensing(message)

        # Preserved exactly: no marker appended, envelope rides along.
        assert stripped.content == content
        assert stripped.role == "assistant"
        assert stripped.contentKey == "text"
        assert stripped.weight == 3
        assert stripped.source is source

    def testTextEnvelopeWithDescriptionGetsNoMarker(self) -> None:
        """A TEXT envelope with a ``<media-description>`` block is preserved.

        Mirrors the ``EnsuredMessage.formatForLLM`` TEXT rendering: the
        description block is prepended to the message text.

        Returns:
            None
        """
        content = "<media-description>a red square</media-description>\n\nlook"
        source = object()
        message = ModelImagesMessage(role="system", content=content, images=[bytearray(b"1"), bytearray(b"2")])
        message.contentKey = "text"
        message.weight = 5
        message.source = source

        stripped = stripImagesForCondensing(message)

        # Preserved exactly: no marker appended, envelope rides along.
        assert stripped.content == content
        assert stripped.role == "system"
        assert stripped.contentKey == "text"
        assert stripped.weight == 5
        assert stripped.source is source

    def testEmptyContentStillGetsMarker(self) -> None:
        """An image message with empty text gains only the marker.

        Returns:
            None
        """
        message = ModelImageMessage(role="user", content="", image=bytearray(b"IMG"))

        stripped = stripImagesForCondensing(message)

        assert stripped.content == "\n[image attached, omitted for condensing]"
