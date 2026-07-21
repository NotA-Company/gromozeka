"""Tests for ``ChatSettingsPage`` and ``ChatTier`` invariants.

Currently pins the tier-monotonic declaration-order invariant that
``internal/bot/common/handlers/configure.py`` relies on when walking the enum
forward via ``.next()`` to find the first tier-eligible page for a chat.
"""

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
