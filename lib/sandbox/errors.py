"""Exception hierarchy for sandboxed code execution.

This module defines all exceptions raised by the sandbox library.  Every
exception inherits from :class:`SandboxError`, making it easy to catch the
entire family with a single ``except SandboxError`` handler.

Hierarchy::

    SandboxError
      ConfigError
      BackendError
        DockerUnavailable
        ImageNotFound
        ImageBuildFailed
      SessionError
        SessionNotFound
        SessionBusy
        SessionDropped
      RuntimeError
        UnknownRuntime
        MissingDependenciesError
      RunError
        RunTimedOut
        RunOomKilled
        RunCancelled
      LibraryError
        LibraryInstallFailed
        LibraryPoolLocked
        InvalidPackageSpec
      FileError
        PathOutsideWorkspace
      SandboxBusy
"""

from __future__ import annotations


class SandboxError(Exception):
    """Root exception for all sandbox-related errors.

    Catching this base class catches every error the sandbox library can
    raise.
    """


class ConfigError(SandboxError):
    """Raised when sandbox configuration is invalid or incomplete."""


class BackendError(SandboxError):
    """Raised when the execution backend fails or is unavailable."""


class DockerUnavailable(BackendError):
    """Raised when the Docker daemon cannot be reached."""


class ImageNotFound(BackendError):
    """Raised when the requested container image does not exist."""


class ImageBuildFailed(BackendError):
    """Raised when building a container image fails."""


class SessionError(SandboxError):
    """Raised when a sandbox session operation fails."""


class SessionNotFound(SessionError):
    """Raised when referencing a session that does not exist."""


class SessionBusy(SessionError):
    """Raised when a session's FIFO queue cap is reached."""


class SessionDropped(SessionError):
    """Raised at waiters when a session is force-dropped."""


class RuntimeError(SandboxError):  # noqa: A001  — intentional shadow of builtins.RuntimeError
    """Raised when a runtime-related error occurs in the sandbox."""


class UnknownRuntime(RuntimeError):
    """Raised when the requested runtime is not recognised."""


class MissingDependenciesError(RuntimeError):
    """Raised when required dependencies are not installed in the sandbox.

    Attributes:
        missing: List of package names that could not be found.
    """

    missing: list[str]

    def __init__(self, missing: list[str]) -> None:
        """Initialize the missing dependencies error.

        Args:
            missing: List of package names that could not be found.

        Returns:
            None
        """
        self.missing: list[str] = missing
        super().__init__(f"missing dependencies: {', '.join(missing)}")


class RunError(SandboxError):
    """Raised when a sandboxed code run fails."""


class RunTimedOut(RunError):
    """Raised when a sandboxed run exceeds its time limit."""


class RunOomKilled(RunError):
    """Raised when a sandboxed run is killed because it exceeded its memory limit."""


class RunCancelled(RunError):
    """Raised when a sandboxed run is cancelled by the caller."""


class LibraryError(SandboxError):
    """Raised when a library operation fails."""


class LibraryInstallFailed(LibraryError):
    """Raised when installing a library into the sandbox fails."""


class LibraryPoolLocked(LibraryError):
    """Raised when the library pool is locked and cannot be modified."""


class InvalidPackageSpec(LibraryError):
    """Raised when a package specification is invalid or unsafe.

    Attributes:
        spec: The original package specification string.
        reason: Human-readable explanation of why the spec is invalid.
    """

    spec: str
    reason: str

    def __init__(self, spec: str, reason: str) -> None:
        """Initialize the invalid package spec error.

        Args:
            spec: The original package specification string.
            reason: Human-readable explanation of why the spec is invalid.

        Returns:
            None
        """
        self.spec: str = spec
        self.reason: str = reason
        super().__init__(f"invalid package spec {spec!r}: {reason}")


class FileError(SandboxError):
    """Raised when a file operation in the sandbox fails."""


class PathOutsideWorkspace(FileError):
    """Raised when a file path resolves outside the sandbox workspace."""


class SandboxBusy(SandboxError):
    """Raised when the global sandbox concurrency cap is reached."""
