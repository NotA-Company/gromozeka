"""Regression tests pinning python-magic (0.4.27) MIME detection for load-bearing formats.

These tests pin ``python-magic``'s MIME output for the exact formats our code
routes on. The output depends on the **libmagic database** bundled with the
installed wheel (or the system libmagic), NOT just the python-magic wrapper
version. A dependency bump that changes detection (e.g. ``image/jpeg`` vs
``image/jpg``, WebP/HEIC recognition, JSON-vs-text classification) fails here.

Production routing decisions that depend on these exact strings:

- ``internal/bot/common/handlers/base.py`` — ``processTelegramMedia`` checks
  ``mimeType.lower().startswith("image/")`` to decide whether to parse a
  downloaded attachment; ``storeAttachment`` extracts the subtype via
  ``magic.from_buffer(data, mime=True).split("/")[-1]`` for the storage key.
- ``internal/bot/common/handlers/media.py`` — ``/analyze`` rejects anything not
  ``image/*``.
- ``internal/bot/common/bot.py`` — derives MIME + extension for Max/Telegram
  media upload.

A change in any pinned MIME string below would silently break image routing,
storage keys, or upload extensions. We feed real, minimal valid file headers
(not arbitrary bytes) because bare magic signatures are often insufficient for
libmagic to classify.
"""

import importlib.metadata

import magic
import pytest

#: Pinned ``python-magic`` distribution version these assertions were observed
#: against. A bump that changes MIME detection must be re-verified against every
#: pin in this file before shipping.
PINNED_VERSION: str = "0.4.27"

# ---------------------------------------------------------------------------
# Minimal valid byte fixtures per format.
# ---------------------------------------------------------------------------

# Minimal 1x1 PNG (8-bit RGB). Bare 8-byte signature is NOT enough for
# libmagic; it needs the IHDR chunk (per docs/llm gotcha).
MINIMAL_PNG: bytes = (
    b"\x89PNG\r\n\x1a\n"  # PNG signature (8 bytes)
    b"\x00\x00\x00\rIHDR"  # IHDR chunk length + type
    b"\x00\x00\x00\x01"  # width = 1
    b"\x00\x00\x00\x01"  # height = 1
    b"\x08\x02\x00\x00\x00"  # 8-bit depth, RGB, no interlace
    b"\x90wS\xde"  # CRC
    b"\x00\x00\x00\x0cIDATx\x9c"  # IDAT chunk
    b"c\xf8\x0f\x00\x00\x11\x00\x01\x1a\xce\xd4\x8d"  # IDAT data + CRC
    b"\x00\x00\x00\x00IEND\xaeB`\x82"  # IEND chunk
)

# Minimal JPEG: SOI + APP0 + JFIF header prefix.
MINIMAL_JPEG: bytes = (
    b"\xff\xd8\xff\xe0"  # SOI + APP0 marker
    b"\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"  # JFIF header
)

# Minimal GIF87a / GIF89a headers with logical screen descriptor + trailer.
MINIMAL_GIF87A: bytes = b"GIF87a" + b"\x01\x00\x01\x00\x00\x00\x00" + b"\x00," + b"\x00" * 8 + b"\x00;"
MINIMAL_GIF89A: bytes = b"GIF89a" + b"\x01\x00\x01\x00\x00\x00\x00" + b"\x00," + b"\x00" * 8 + b"\x00;"

# Minimal WebP: RIFF container + WEBP + VP8 chunk. The VP8 chunk-size field
# (0x0e = 14) and the RIFF file-size field (0x1a = 26 = "WEBP"(4) + chunk
# header(8) + chunk data(14)) are kept internally consistent: the VP8 data is
# padded to exactly 14 bytes so a stricter future container validator cannot
# reject it as malformed and reclassify it — only real signature drift can
# trip the assertion.
MINIMAL_WEBP: bytes = (
    b"RIFF"
    + b"\x1a\x00\x00\x00"  # file size = 26 (matches the 26-byte payload below)
    + b"WEBP"
    + b"VP8 "  # chunk fourcc
    + b"\x0e\x00\x00\x00"  # chunk size = 14
    + b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # exactly 14 bytes
)

# Minimal non-image binary: PDF magic-bytes prefix. libmagic classifies this
# from the leading ``%PDF-1.x`` signature alone; the object body is inert.
# Used to protect production's non-image rejection branch (see
# ``media.py:514`` / ``base.py:1892``): a bump that misclassifies a binary as
# ``image/*`` would route it into image parsing with no failing test.
MINIMAL_PDF: bytes = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\n"

# Text/JSON blobs — libmagic classifies by content heuristics, not extension.
JSON_BLOB: bytes = b'{"key": "value", "list": [1, 2, 3]}'
PLAIN_TEXT: bytes = b"hello world, this is plain text"


class TestPinnedVersion:
    """Force a conscious re-verification pass on any ``python-magic`` bump.

    The whole point of this suite is that a dependency bump which silently
    changes behaviour fails loudly. A docstring version string can rot without
    a failing test; this assertion compares the ACTUAL installed distribution
    version against :data:`PINNED_VERSION` so a bump fails on a real assertion.
    When it fails, re-verify every other pin in this file against the new
    version before updating the constant.

    Note: the pinned MIME strings also depend on the bundled libmagic database,
    which can change between wheels of the SAME python-magic version — so a
    version match is necessary but not sufficient; the MIME assertions below are
    the authoritative behaviour pins.
    """

    def testPinnedVersion(self) -> None:
        """The installed ``python-magic`` distribution matches :data:`PINNED_VERSION`.

        Args:
            None (self).

        Returns:
            None. Asserts the installed distribution version string.
        """
        assert importlib.metadata.version("python-magic") == PINNED_VERSION


class TestPythonMagicMimeDetection:
    """Pins ``magic.from_buffer(data, mime=True)`` output for routed formats.

    Each pinned MIME string was observed against the pinned
    ``python-magic==0.4.27`` + bundled libmagic-db. If a
    bump changes any string, the corresponding assertion fails and the routing
    code above must be re-checked before the bump ships.
    """

    @pytest.mark.parametrize(
        "data,expectedMime",
        [
            (MINIMAL_PNG, "image/png"),
            (MINIMAL_JPEG, "image/jpeg"),
            (MINIMAL_GIF87A, "image/gif"),
            (MINIMAL_GIF89A, "image/gif"),
            (MINIMAL_WEBP, "image/webp"),
            (MINIMAL_PDF, "application/pdf"),
            (JSON_BLOB, "application/json"),
            (PLAIN_TEXT, "text/plain"),
        ],
        ids=["png", "jpeg", "gif87a", "gif89a", "webp", "pdf", "json", "text"],
    )
    def testFromBufferReturnsExpectedMime(self, data: bytes, expectedMime: str) -> None:
        """Assert ``magic.from_buffer`` returns the pinned MIME string.

        Args:
            data: The byte fixture to classify.
            expectedMime: The exact MIME string pinned for this fixture.

        Returns:
            None. Raises ``AssertionError`` if detection drifts.
        """
        mimeType = magic.from_buffer(data, mime=True)
        assert mimeType == expectedMime

    def testImageMimesStartWithImageSlashPrefix(self) -> None:
        """Pin that all image formats satisfy the production ``image/`` gate.

        ``base.py``/``media.py`` guard with ``mimeType.startswith("image/")``
        before parsing or uploading media. This locks the invariant for every
        image fixture together, independently of the per-format strings.

        Returns:
            None.
        """
        imageDataList = [MINIMAL_PNG, MINIMAL_JPEG, MINIMAL_GIF87A, MINIMAL_GIF89A, MINIMAL_WEBP]
        for imageData in imageDataList:
            mimeType = magic.from_buffer(imageData, mime=True)
            assert mimeType.startswith("image/"), f"{mimeType!r} did not start with 'image/'"

    def testNonImageBinaryFailsImageSlashGate(self) -> None:
        """Pin that a representative non-image binary is rejected by the ``image/`` gate.

        Production's non-image rejection branch (``media.py:514`` "unsupported
        MIME", ``base.py:1892`` "skipping parsing") is guarded by
        ``mimeType.startswith("image/")``. Without a pinned non-image binary, a
        bump that misclassifies e.g. a PDF as ``image/*`` would route it into
        image parsing with no failing test. The PDF magic-bytes prefix is
        trivially stable across libmagic versions, so this fixture isolates
        real drift from noise.

        Returns:
            None.
        """
        for nonImageData in (MINIMAL_PDF, JSON_BLOB, PLAIN_TEXT):
            mimeType = magic.from_buffer(nonImageData, mime=True)
            assert not mimeType.startswith("image/"), (
                f"{mimeType!r} unexpectedly satisfied the 'image/' gate; "
                "production rejection branch no longer fires for this fixture"
            )

    def testSubtypeExtractionMatchesProductionPattern(self) -> None:
        """Pin that both subtype-extraction patterns yield the expected value.

        Production extracts the file subtype from the detected MIME at three
        sites via two different slicing patterns:

        - ``base.py:1952`` (``storeAttachment``) uses
          ``mimeType.split("/")[-1]`` to build the storage key.
        - ``bot.py:527`` and ``bot.py:767`` (Max / Telegram filename
          derivation) use ``mimeType.split("/")[1]`` to build the extension.

        The two patterns coincide for every pinned image MIME today, but a
        bump emitting a multi-slash MIME (e.g. ``image/vnd.microsoft.icon``)
        would make ``[-1]`` and ``[1]`` diverge — silently corrupting
        Max/Telegram filenames while a ``[-1]``-only test stayed green. This
        test pins both slices per format so either site breaks loudly.

        Returns:
            None.
        """
        subtypeExpectations = [
            (MINIMAL_PNG, "png"),
            (MINIMAL_JPEG, "jpeg"),
            (MINIMAL_GIF87A, "gif"),
            (MINIMAL_GIF89A, "gif"),
            (MINIMAL_WEBP, "webp"),
        ]
        for imageData, expectedSubtype in subtypeExpectations:
            mimeType = magic.from_buffer(imageData, mime=True)
            # bot.py:527,767 — ``.split("/")[1]`` extension derivation.
            headSubtype = mimeType.split("/")[1]
            # base.py:1952 — ``.split("/")[-1]`` storage-key subtype.
            tailSubtype = mimeType.split("/")[-1]
            assert headSubtype == expectedSubtype, f"{mimeType!r} -> [1] subtype {headSubtype!r}"
            assert tailSubtype == expectedSubtype, f"{mimeType!r} -> [-1] subtype {tailSubtype!r}"
