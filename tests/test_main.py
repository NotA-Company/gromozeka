"""Regression tests for the stranded-thread exit guard in ``main.py``.

Background (Max-mode Ctrl+C hang, 2026-09-03): httpx2 defaults to
``truststore.SSLContext`` — a subclass of ``ssl.SSLContext`` — which makes
anyio's ``TLSStream.wrap()`` offload every TLS ``wrap_bio`` to a NON-daemon
"AnyIO worker thread". anyio only stops that worker after its current
function returns; a worker blocked forever on a ``threading`` lock survives
the entire graceful shutdown, and interpreter finalization
(``Py_Finalize → threading._shutdown → join``) then hangs the process
forever after "Bot stopped by user" is logged.

The fix is the exit guard (``installExitGuard`` /
``forceExitIfStrandedThreads`` / ``strandedNonDaemonThreads`` in ``main.py``),
registered via ``threading._register_atexit`` so it runs after executor
cleanup but before the joins that hang.

The subprocess tests embed a ``python -c`` snippet — the same sanctioned
exemption as ``tests/scripts/test_httpx_alias_import.py``: the repo's "no
``python -c``" rule targets manual shell experimentation, not self-contained
regression assertions. The force-exit path cannot be exercised in-process
(it would terminate the pytest runner).
"""

import subprocess
import sys
import threading
from pathlib import Path

import main as mainModule

REPO_ROOT = Path(__file__).resolve().parents[1]

# Stuck-thread child used by the subprocess tests. Mirrors the production
# failure shape: a non-daemon thread named like anyio's worker, blocked
# forever on a threading primitive while the main thread exits normally.
_CHILD_STUCK_THREAD = (
    "import sys, threading\n"
    f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
    "import main\n"
    "main.installExitGuard(0.5)\n"
    "started = threading.Event()\n"
    "release = threading.Event()\n"
    "def stuck():\n"
    "    started.set()\n"
    "    release.wait()\n"
    "t = threading.Thread(target=stuck, name='AnyIO worker thread')\n"
    "t.start()\n"
    "started.wait()\n"
    "print('CHILD MAIN DONE', flush=True)\n"
)

# Clean-exit child: a short-lived non-daemon thread that finishes before the
# main thread exits — the guard must NOT fire here (no false positives).
_CHILD_CLEAN_EXIT = (
    "import sys, threading\n"
    f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
    "import main\n"
    "main.installExitGuard(0.5)\n"
    "done = threading.Event()\n"
    "def finishes():\n"
    "    done.set()\n"
    "t = threading.Thread(target=finishes, name='short-lived')\n"
    "t.start()\n"
    "done.wait()\n"
    "t.join()\n"
    "print('CHILD MAIN DONE', flush=True)\n"
)


class TestStrandedNonDaemonThreads:
    """Unit tests for the thread-selection predicate."""

    def test_ignoresDaemonAndMainThread(self) -> None:
        """Daemon threads and the main thread must not be reported as stranded.

        Returns:
            None: Asserts membership semantics of strandedNonDaemonThreads().
        """
        release = threading.Event()
        startedDaemon = threading.Event()
        startedNonDaemon = threading.Event()

        def blocked(eventStarted: threading.Event) -> None:
            eventStarted.set()
            release.wait()

        daemonThread = threading.Thread(target=blocked, args=(startedDaemon,), daemon=True)
        nonDaemonThread = threading.Thread(target=blocked, args=(startedNonDaemon,))
        daemonThread.start()
        nonDaemonThread.start()
        try:
            startedDaemon.wait()
            startedNonDaemon.wait()
            stranded = mainModule.strandedNonDaemonThreads()
            assert daemonThread not in stranded
            assert nonDaemonThread in stranded
            assert threading.main_thread() not in stranded
        finally:
            release.set()
            daemonThread.join(timeout=5)
            nonDaemonThread.join(timeout=5)

    def test_ignoresExitedThread(self) -> None:
        """A finished non-daemon thread must not be reported as stranded.

        Returns:
            None: Asserts the exited thread is absent from the result.
        """
        finished = threading.Event()

        def finishes() -> None:
            finished.set()

        thread = threading.Thread(target=finishes)
        thread.start()
        finished.wait()
        thread.join(timeout=5)
        assert thread not in mainModule.strandedNonDaemonThreads()


class TestForceExitIfStrandedThreads:
    """Unit test for the grace-period path (no force exit)."""

    def test_returnsWhenThreadExitsWithinGrace(self) -> None:
        """A thread that finishes within the grace period must not trigger os._exit.

        Returns:
            None: Asserts the call returns and the process is still alive.
        """
        started = threading.Event()
        release = threading.Event()

        def brieflyBlocked() -> None:
            started.set()
            release.wait(0.2)  # unblocks itself after 0.2s

        thread = threading.Thread(target=brieflyBlocked)
        thread.start()
        started.wait()
        try:
            # Must return (rather than os._exit) once the thread finishes.
            mainModule.forceExitIfStrandedThreads(5.0)
            assert not thread.is_alive()
        finally:
            release.set()
            thread.join(timeout=5)


class TestExitGuardSubprocess:
    """End-to-end regression tests through real interpreter finalization."""

    def test_stuckNonDaemonThreadForcesExit(self) -> None:
        """A stuck non-daemon thread must not hang the process at exit.

        Before the fix this child hung forever inside threading._shutdown()
        (or, on unpatched main.py, raised AttributeError for the missing
        installExitGuard) — either way the assertions below fail.

        Returns:
            None: Asserts exit code 0, timely exit, and diagnostic logging.
        """
        result = subprocess.run(
            [sys.executable, "-c", _CHILD_STUCK_THREAD],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert "CHILD MAIN DONE" in result.stdout
        assert "forcing process exit" in result.stderr
        assert "AnyIO worker thread" in result.stderr

    def test_cleanExitDoesNotForceExit(self) -> None:
        """No stranded threads: guard must not fire and exit stays clean.

        Returns:
            None: Asserts exit code 0 and absence of the force-exit warning.
        """
        result = subprocess.run(
            [sys.executable, "-c", _CHILD_CLEAN_EXIT],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert "CHILD MAIN DONE" in result.stdout
        assert "forcing process exit" not in result.stderr
