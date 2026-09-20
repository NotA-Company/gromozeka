"""Tests for :mod:`lib.ai.session` — session-id builder helpers for lib/ai calls.

Covers:

- ``sanitizeSessionIdComponent``: token-safe pass-through, invalid-character
  replacement (spaces, ``#``, ``/``, unicode, CR/LF/NUL), dash preservation
  (leading/trailing/repeated — negative Telegram group chat ids rely on
  this), ``ValueError`` on empty input, no length cap (inputs longer than
  128 characters are accepted — capping is ``buildSessionId``'s job).
- ``hashSessionIdComponent``: stability across calls, known SHA-256 prefix
  for a known input, 16-char token-safe output (including for the empty
  string, which the hash docstring explicitly permits).
- ``buildSessionId``: default and custom namespaces, namespace-only calls
  (no components — returns just the sanitized namespace), multiple
  components, component sanitization, empty-namespace / empty-component
  rejections, the literal 128-accepted / 129-rejected length boundary, and
  the byte-identity cases pinning the shapes consumed by
  ``BaseBotHandler.getLLMRequestSessionId`` (positive chat id, negative
  group chat id with the double dash, string message ids).
"""

import re

import pytest

from lib.ai.session import (
    _MAX_SESSION_ID_LENGTH,
    DEFAULT_SESSION_NAMESPACE,
    buildSessionId,
    hashSessionIdComponent,
    sanitizeSessionIdComponent,
)


class TestSanitizeSessionIdComponent:
    """Tests for :func:`sanitizeSessionIdComponent`."""

    def test_tokenSafeStringsPassThrough(self) -> None:
        """Every character in ``[A-Za-z0-9._-]`` is returned unchanged."""
        assert sanitizeSessionIdComponent("abcXYZ012._-") == "abcXYZ012._-"

    def test_invalidCharactersReplacedWithDash(self) -> None:
        """Spaces, ``#`` and ``/`` are each replaced with ``-``."""
        assert sanitizeSessionIdComponent("a b#c/d") == "a-b-c-d"

    def test_unicodeReplacedWithDash(self) -> None:
        """Non-ASCII characters are replaced with ``-`` (one dash each)."""
        assert sanitizeSessionIdComponent("café") == "caf-"

    def test_controlCharactersReplacedWithDash(self) -> None:
        """CR, LF and NUL are each replaced with ``-`` (one dash per char)."""
        assert sanitizeSessionIdComponent("a\r\nb\x00c") == "a--b-c"

    def test_dashesPreserved_noStripNoCollapse(self) -> None:
        """Leading/trailing dashes and consecutive-dash runs are preserved.

        Byte-identity requirement: negative Telegram group chat ids
        (``-100123``) must pass through untouched so the built session id
        keeps the historical double dash.
        """
        assert sanitizeSessionIdComponent("--a--b--") == "--a--b--"
        assert sanitizeSessionIdComponent("-100123") == "-100123"

    def test_emptyRaises(self) -> None:
        """The empty string is rejected with ``ValueError``."""
        with pytest.raises(ValueError):
            sanitizeSessionIdComponent("")

    def test_acceptsInputLongerThan128Chars(self) -> None:
        """No length cap at sanitize level — a >128-char input passes through.

        Capping is ``buildSessionId``'s job; the sanitizer must stay
        length-agnostic.
        """
        long = "x" * 200
        assert sanitizeSessionIdComponent(long) == long


class TestHashSessionIdComponent:
    """Tests for :func:`hashSessionIdComponent`."""

    def test_stableAcrossCalls(self) -> None:
        """The same input yields the same digest on every call."""
        text = "https://example.com/some/long/path?query=1"
        assert hashSessionIdComponent(text) == hashSessionIdComponent(text)

    def test_knownSha256Prefix(self) -> None:
        """A known input yields the expected SHA-256 prefix (16 chars)."""
        assert hashSessionIdComponent("hello") == "2cf24dba5fb0a30e"

    def test_outputIsTokenSafeAnd16Chars(self) -> None:
        """Output is always 16 lowercase hex digits (token-safe)."""
        digest = hashSessionIdComponent("файл с пробелами.txt")
        assert len(digest) == 16
        assert re.fullmatch(r"[0-9a-f]{16}", digest) is not None

    def test_emptyStringHashes(self) -> None:
        """The empty string is a valid input (docstring-permitted): a 16-char digest."""
        digest = hashSessionIdComponent("")
        assert len(digest) == 16
        assert re.fullmatch(r"[0-9a-f]{16}", digest) is not None


class TestBuildSessionId:
    """Tests for :func:`buildSessionId`, including byte-identity cases."""

    def test_defaultNamespace(self) -> None:
        """Without a namespace override the ``gromozeka`` prefix is used."""
        assert buildSessionId("a", "b") == "gromozeka-a-b"

    def test_defaultNamespaceConstantMatchesProviderFallback(self) -> None:
        """``DEFAULT_SESSION_NAMESPACE`` is ``gromozeka`` (provider fallback)."""
        assert DEFAULT_SESSION_NAMESPACE == "gromozeka"

    def test_customNamespace(self) -> None:
        """A custom namespace replaces the default prefix."""
        assert buildSessionId("a", "b", namespace="other") == "other-a-b"

    def test_multipleComponents(self) -> None:
        """Components are joined in order with ``-``."""
        assert buildSessionId("1", "2", "3") == "gromozeka-1-2-3"

    def test_componentsAreSanitized(self) -> None:
        """Namespace and components are sanitized before joining."""
        assert buildSessionId("a b", namespace="ns x") == "ns-x-a-b"

    def test_namespaceOnly_defaultNamespace(self) -> None:
        """No components: just the sanitized default namespace is returned."""
        assert buildSessionId() == "gromozeka"

    def test_namespaceOnly_customNamespace(self) -> None:
        """No components: just the sanitized custom namespace is returned."""
        assert buildSessionId(namespace="my ns") == "my-ns"

    def test_emptyNamespaceRaises(self) -> None:
        """An empty namespace is rejected with ``ValueError``."""
        with pytest.raises(ValueError):
            buildSessionId("a", namespace="")

    def test_emptyComponentRaises(self) -> None:
        """An empty component is rejected with ``ValueError``."""
        with pytest.raises(ValueError):
            buildSessionId("a", "")

    def test_overLengthRaises(self) -> None:
        """A result longer than 128 characters is rejected with ``ValueError``."""
        with pytest.raises(ValueError):
            buildSessionId("x" * 150)

    def test_atCapDoesNotRaise(self) -> None:
        """Exactly 128 characters is accepted (literal pin, not constant-derived).

        Arithmetic: namespace ``gromozeka`` (9) + joiner ``-`` (1) +
        component ``a`` * 118 = 128.
        """
        sessionId = buildSessionId("a" * 118)
        assert sessionId == "gromozeka-" + "a" * 118
        assert len(sessionId) == 128

    def test_oneOverCapRaises(self) -> None:
        """Exactly 129 characters is rejected (literal pin, not constant-derived).

        Arithmetic: namespace ``gromozeka`` (9) + joiner ``-`` (1) +
        component ``a`` * 119 = 129 — one character over the cap.
        """
        with pytest.raises(ValueError):
            buildSessionId("a" * 119)

    def test_maxLengthConstantPinnedTo128(self) -> None:
        """The implementation constant stays pinned to the specified 128."""
        assert _MAX_SESSION_ID_LENGTH == 128

    # ------------------------------------------------------------------
    # Byte-identity cases (shapes consumed by getLLMRequestSessionId)
    # ------------------------------------------------------------------

    def test_byteIdentity_positiveChatId(self) -> None:
        """Positive chat id: ``gromozeka-<chatId>-<messageId>``."""
        assert buildSessionId(str(123), "456") == "gromozeka-123-456"

    def test_byteIdentity_negativeChatId_doubleDashPreserved(self) -> None:
        """Negative group chat id keeps the leading dash (double dash)."""
        assert buildSessionId(str(-100123), "456") == "gromozeka--100123-456"

    def test_byteIdentity_stringMessageIdPassesThrough(self) -> None:
        """Token-safe Max string message ids pass through unchanged."""
        assert buildSessionId("777", "abc.def") == "gromozeka-777-abc.def"
