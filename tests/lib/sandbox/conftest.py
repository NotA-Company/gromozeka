"""Shared test helpers for the sandbox test suite (tests/lib/sandbox/).

Currently provides ``swapBackend()``: the one supported way to isolate a
``SandboxManager`` built through ``getInstance()`` from the real Docker
daemon. The manager captures its backend in TWO places (see the helper's
docstring), so swapping only one reference leaves the garbage collector
holding the real backend — real Docker I/O on a live daemon, silently
swallowed connection failures on CI. Tests import the helper explicitly
from this module, mirroring ``tests.lib.rate_limiter.conftest`` /
``installFakeClock``.
"""

from unittest.mock import MagicMock

from lib.sandbox.manager import SandboxManager


def swapBackend(manager: SandboxManager, backend: MagicMock) -> None:
    """Install a mock backend everywhere the manager captured the real one.

    ``SandboxManager.__init__`` hands the real ``DockerBackend`` to BOTH
    ``manager._backend`` and the internal ``GarbageCollector``
    (``manager._gc._backend``). Swapping only ``manager._backend`` left the
    GC holding the real backend, so any test reaching ``recover()`` →
    ``collectGarbage()`` → ``_gc.collectAll()`` performed REAL Docker I/O
    (list/kill/remove of managed containers) whenever ``DOCKER_HOST``
    resolved to a live daemon — and on daemon-less CI the same tests passed
    only because the GC swallows backend connection failures. The aiodocker
    client that I/O opened was then dropped unclosed by the singleton reset,
    surfacing as ``ResourceWarning: Unclosed connector/socket``.

    Every test that builds a manager via ``getInstance()`` and then drives
    any path that can reach the backend (``collectGarbage``, ``recover``,
    ``cancelRun``, ``dropSession(force=True)``, ``runCode``, ...) must call
    this right after construction. ``TestSwapBackendHelper`` in
    ``test_manager.py`` pins the two-reference invariant structurally,
    independent of daemon reachability.

    Args:
        manager: The manager whose backend references to replace.
        backend: Mock backend to install.

    Returns:
        None
    """
    manager._backend = backend
    manager._gc._backend = backend
