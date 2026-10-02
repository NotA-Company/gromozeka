"""
Session-ID construction for lib/ai calls.

This module is the central place where session identifiers for LLM requests
are built. A session id is passed to generation calls through the
keyword-only ``sessionId`` parameter (transported via a ContextVar) and is
consumed by the OpenCode Go provider as the mandatory ``x-opencode-session``
HTTP header (prompt-cache affinity + sticky routing).

Session ids must therefore be:

- token-safe ASCII (``[A-Za-z0-9._-]`` only) — they travel as HTTP header
  values;
- short (capped at :data:`_MAX_SESSION_ID_LENGTH` characters);
- built from *persistent* components (chat ids, message ids, stable names)
  so the same conversation maps to the same session id across restarts.
  Free-text components (URLs, file basenames, layout names) that are long or
  header-hostile should be passed through :func:`hashSessionIdComponent`
  first.

Compatibility: :func:`buildSessionId` reproduces previously issued raw
f-string ids byte-for-byte **only for nonempty, token-safe inputs whose
complete joined result fits within :data:`_MAX_SESSION_ID_LENGTH`
characters**. The raw f-string formatting accepted empty and arbitrarily
long components; the builder instead raises ``ValueError`` for both —
failing loudly beats silent truncation and the cache-affinity breakage it
invites.
"""

import hashlib
import re

DEFAULT_SESSION_NAMESPACE: str = "gromozeka"
"""Default session-id namespace prefix.

Matches ``DEFAULT_SESSION_ID`` in
``lib/ai/providers/opencode_go_provider.py`` (the provider's fallback when
no session id was supplied for a request).
"""

_MAX_SESSION_ID_LENGTH: int = 128
"""Maximum length of a built session id (HTTP-header-friendly budget)."""


def sanitizeSessionIdComponent(component: str) -> str:
    """Replace every character outside the token-safe set with ``-``.

    The token-safe set is ``[A-Za-z0-9._-]``. Leading/trailing dashes and
    runs of consecutive dashes are deliberately preserved (no stripping, no
    collapsing): production session ids embed negative Telegram group chat
    ids, producing shapes like ``gromozeka--100123-<messageId>`` (double
    dash), and byte-identity with previously issued session ids must be
    maintained. The total session-id length cap is NOT enforced here — that
    is :func:`buildSessionId`'s job.

    Args:
        component: Raw component text (e.g. a chat id or message id as a
            string). Must not be empty.

    Returns:
        The sanitized component: every character outside ``A-Z``, ``a-z``,
        ``0-9``, ``.`` and ``_`` replaced with ``-``. Never empty.

    Raises:
        ValueError: If ``component`` is empty (before or after
            sanitization).
    """
    if not component:
        raise ValueError("Session id component must not be empty")
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "-", component)
    if not sanitized:
        raise ValueError("Session id component is empty after sanitization")
    return sanitized


def hashSessionIdComponent(text: str) -> str:
    """Hash free-text into a fixed-width, token-safe session-id component.

    Deterministic (the same input always yields the same output) and
    token-safe by construction (lowercase hex digits only). Intended for
    free-text components (URLs, file basenames, layout names) that are long
    or header-hostile. The output is a 64-bit truncated digest (16 hex
    chars) suitable for cache-bucket naming — by the birthday bound,
    generic collisions require roughly 2³² work, not 2⁶⁴ — which is
    acceptable here, where the id only needs to route identical
    conversations to the same prompt-cache bucket.

    Args:
        text: Arbitrary text to hash. Encoded as UTF-8 before hashing; may
            be empty.

    Returns:
        The first 16 hex characters of the SHA-256 digest of ``text``.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def buildSessionId(*components: str, namespace: str = DEFAULT_SESSION_NAMESPACE) -> str:
    """Build a session id from persistent components.

    The namespace and every component are passed through
    :func:`sanitizeSessionIdComponent` and joined with ``-``:
    ``<namespace>-<component1>-<component2>...``. With no components the
    result is just the sanitized namespace — ``buildSessionId()`` returns
    ``"gromozeka"``. All inputs must be persistent identifiers (stable
    across restarts); pass long free-text inputs through
    :func:`hashSessionIdComponent` first to stay under the length cap.

    Compatibility: byte identity with previously issued raw f-string ids
    holds only for **nonempty, token-safe inputs whose complete joined
    result fits within :data:`_MAX_SESSION_ID_LENGTH` characters** — the
    raw f-string accepted empty and arbitrarily long components, which
    raise here instead (see ``Raises``).

    Args:
        *components: Persistent identifier components (chat id, message id,
            hashed free-text, ...).
        namespace: Namespace prefix, sanitized the same way as the
            components. Defaults to :data:`DEFAULT_SESSION_NAMESPACE`.

    Returns:
        The joined, sanitized session id, at most
        :data:`_MAX_SESSION_ID_LENGTH` characters long.

    Raises:
        ValueError: If the namespace or any component is empty (before or
            after sanitization), or if the joined result exceeds
            :data:`_MAX_SESSION_ID_LENGTH` (hash long components with
            :func:`hashSessionIdComponent` — failing loudly beats silent
            truncation and the collisions it invites).
    """
    sanitizedParts = [sanitizeSessionIdComponent(namespace)]
    sanitizedParts.extend(sanitizeSessionIdComponent(component) for component in components)
    sessionId = "-".join(sanitizedParts)
    if len(sessionId) > _MAX_SESSION_ID_LENGTH:
        raise ValueError(
            f"Session id exceeds the maximum length of {_MAX_SESSION_ID_LENGTH} characters "
            f"(got {len(sessionId)}): hash long components with hashSessionIdComponent()"
        )
    return sessionId
