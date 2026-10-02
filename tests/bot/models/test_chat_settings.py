"""Tests for ``ChatSettingsPage`` and ``ChatTier`` invariants.

Pins the tier-monotonic declaration-order invariant that
``internal/bot/common/handlers/configure.py`` relies on when walking the enum
forward via ``.next()`` to find the first tier-eligible page for a chat, and
the ``ChatTier.resolveModelTier`` resolver used by every model-tier gate
(picker, selection validation, chat-settings filter).
"""

import logging
from typing import Optional

import pytest

from internal.bot.models.chat_settings import ChatSettingsPage, ChatTier


def testChatSettingsPageDeclarationOrderIsTierMonotonic() -> None:
    """ChatSettingsPage declaration order must be tier-monotonic non-decreasing.

    ``internal/bot/common/handlers/configure.py`` walks the enum forward via
    ``.next()`` until a tier-eligible page is found for the requesting chat's
    tier. A lower-tier page declared AFTER a higher-tier one would either land
    a low-tier user on a too-high page or terminate at ``None`` (the
    ``while``-loop None-guard raises a user-facing error in that case). This
    test pins the invariant so a future enum-member reorder is caught at test
    time rather than at runtime in production.

    Returns:
        None
    """
    pages = list(ChatSettingsPage)
    tierIds = [page.minTier().getId() for page in pages]
    assert tierIds == sorted(tierIds), (
        "ChatSettingsPage is not tier-monotonic in declaration order: "
        f"{[(page.name, tierId) for page, tierId in zip(pages, tierIds)]}"
    )
    assert ChatSettingsPage.STANDARD.minTier() == ChatTier.FREE, (
        "STANDARD page must be FREE-tier — it is the default entry point for "
        "the /settings command (configure.py default arg)."
    )


class TestResolveModelTier:
    """Pin ``ChatTier.resolveModelTier`` semantics for model-config tiers.

    Regression class for the silently-invisible-model bug: a model whose
    ``tier`` config value was missing or invalid (e.g. ``"bot_owner"`` with an
    underscore, which ``ChatTier.fromStr`` rejects) was dropped from the model
    picker and chat settings everywhere with no diagnostic. The resolver makes
    such models owner-only visible and logs a warning for invalid values.
    """

    @pytest.mark.parametrize(
        "tierStr",
        [
            None,
            "",
            "   ",
        ],
    )
    def test_missingTierIsBotOwnerSilently(self, caplog: pytest.LogCaptureFixture, tierStr: Optional[str]) -> None:
        """None, empty or whitespace-only tier resolves to BOT_OWNER without
        a warning.

        A missing tier is the documented default (owner-only visibility), so
        it must not spam the log. Only whitespace-only input counts as
        missing — anything else unparseable must warn (see the
        whitespace-padded test below).

        Args:
            caplog: pytest log-capture fixture.
            tierStr: None, empty or whitespace-only tier value.

        Returns:
            None
        """
        with caplog.at_level(logging.WARNING):
            assert ChatTier.resolveModelTier("some/model", tierStr) == ChatTier.BOT_OWNER
        assert "invalid tier" not in caplog.text

    def test_validValuesParseUnchanged(self) -> None:
        """Valid hyphenated tier values parse to their enum members.

        Returns:
            None
        """
        assert ChatTier.resolveModelTier("some/model", "free") == ChatTier.FREE
        assert ChatTier.resolveModelTier("some/model", "paid") == ChatTier.PAID
        assert ChatTier.resolveModelTier("some/model", "bot-owner") == ChatTier.BOT_OWNER

    @pytest.mark.parametrize(
        "tierStr,wouldBeTier",
        [
            (" free ", ChatTier.FREE),
            ("paid\n", ChatTier.PAID),
        ],
    )
    def test_whitespacePaddedValueIsInvalid_warnsAndResolvesToBotOwner(
        self, caplog: pytest.LogCaptureFixture, tierStr: str, wouldBeTier: ChatTier
    ) -> None:
        """A present-but-whitespace-padded tier string is NOT normalized.

        Only whitespace-only input counts as missing; the raw string is
        parsed as-is, so ``" free "`` must NOT silently parse as ``FREE`` —
        it is unparseable and therefore warns and resolves to BOT_OWNER.

        Args:
            caplog: pytest log-capture fixture.
            tierStr: Whitespace-padded tier string (rejected when parsed raw).
            wouldBeTier: The tier the string would yield if stripped; asserted
                NOT to be the result.

        Returns:
            None
        """
        with caplog.at_level(logging.WARNING):
            result = ChatTier.resolveModelTier("opencode/glm-5.3", tierStr)
        assert result == ChatTier.BOT_OWNER
        assert result != wouldBeTier
        assert "opencode/glm-5.3" in caplog.text
        assert f"has invalid tier '{tierStr}'" in caplog.text
        assert "treating as 'bot-owner'" in caplog.text

    @pytest.mark.parametrize(
        "tierStr",
        [
            "bot_owner",
            "Free",
            "garbage",
        ],
    )
    def test_invalidTierWarnsAndResolvesToBotOwner(self, caplog: pytest.LogCaptureFixture, tierStr: str) -> None:
        """Invalid non-empty tier resolves to BOT_OWNER and logs a warning
        naming the model and the raw invalid value.

        Args:
            caplog: pytest log-capture fixture.
            tierStr: Invalid tier string (rejected by ``ChatTier.fromStr``).

        Returns:
            None
        """
        with caplog.at_level(logging.WARNING):
            assert ChatTier.resolveModelTier("opencode/glm-5.3", tierStr) == ChatTier.BOT_OWNER
        assert "opencode/glm-5.3" in caplog.text
        assert f"has invalid tier '{tierStr}'" in caplog.text
        assert "treating as 'bot-owner'" in caplog.text
