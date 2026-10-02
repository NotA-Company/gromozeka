"""Lock ``httpx2`` distribution version.

This test pins the ``httpx2`` distribution version to 2.10.0. The httpx2 fork is
API-identical to httpx 0.28.1 but contains several upstream fixes relevant to this
codebase (notably SOCKS5 proxy support via native ``proxy=`` rather than a custom
transport). This test ensures that any accidental version bump is caught.
"""

import importlib.metadata

#: Pinned ``httpx2`` distribution version these assertions were observed against.
#: A bump that changes behaviour must be reviewed before updating the constant.
PINNED_VERSION: str = "2.10.0"


class TestPinnedVersion:
    """Force a conscious review pass on any ``httpx2`` bump.

    The whole point of this suite is that a dependency bump fails loudly on a
    real assertion rather than silently changing behaviour. When it fails, review
    the new version before updating the constant.
    """

    def testPinnedVersion(self) -> None:
        """The installed ``httpx2`` distribution matches :data:`PINNED_VERSION`.

        Args:
            None (self).

        Returns:
            None. Asserts the installed distribution version string.
        """
        assert importlib.metadata.version("httpx2") == PINNED_VERSION
