"""Tests for the sandbox exception hierarchy (lib.sandbox.errors).

Covers:
- Inheritance: every error is an instance of SandboxError and its direct
  parent.
- Structured fields on MissingDependenciesError and InvalidPackageSpec.
- raise / except chains for every class.
- SessionDropped caught as SessionError, SandboxError, and Exception.
- SandboxBusy is NOT under RunError or SessionError.
"""

import pytest

from lib.sandbox.errors import (
    BackendError,
    ConfigError,
    DockerUnavailable,
    FileError,
    ImageBuildFailed,
    ImageNotFound,
    InvalidPackageSpec,
    LibraryError,
    LibraryInstallFailed,
    LibraryPoolLocked,
    MissingDependenciesError,
    PathOutsideWorkspace,
    RunCancelled,
    RunError,
    RunOomKilled,
    RunTimedOut,
    RuntimeError,
    SandboxBusy,
    SandboxError,
    SessionBusy,
    SessionDropped,
    SessionError,
    SessionNotFound,
    UnknownRuntime,
)

# ============================================================================
# Inheritance: every error is a SandboxError
# ============================================================================

_ALL_ERROR_CLASSES = [
    SandboxError,
    ConfigError,
    BackendError,
    DockerUnavailable,
    ImageNotFound,
    ImageBuildFailed,
    SessionError,
    SessionNotFound,
    SessionBusy,
    SessionDropped,
    RuntimeError,
    UnknownRuntime,
    MissingDependenciesError,
    RunError,
    RunTimedOut,
    RunOomKilled,
    RunCancelled,
    LibraryError,
    LibraryInstallFailed,
    LibraryPoolLocked,
    InvalidPackageSpec,
    FileError,
    PathOutsideWorkspace,
    SandboxBusy,
]


@pytest.mark.parametrize("cls", _ALL_ERROR_CLASSES, ids=lambda c: c.__name__)
def testIsInstanceOfSandboxError(cls: type) -> None:
    """Verify that every error class produces instances that are also SandboxError instances.

    Args:
        cls: Parameterised error class under test.

    Returns:
        None
    """
    if cls is MissingDependenciesError:
        exc = cls(["pkg"])
    elif cls is InvalidPackageSpec:
        exc = cls("spec", "reason")
    else:
        exc = cls("msg")
    assert isinstance(exc, SandboxError)


# ============================================================================
# Specific parent relationships
# ============================================================================

_PARENT_CHILD_PAIRS: list[tuple[type, type]] = [
    (SandboxError, ConfigError),
    (SandboxError, BackendError),
    (BackendError, DockerUnavailable),
    (BackendError, ImageNotFound),
    (BackendError, ImageBuildFailed),
    (SandboxError, SessionError),
    (SessionError, SessionNotFound),
    (SessionError, SessionBusy),
    (SessionError, SessionDropped),
    (SandboxError, RuntimeError),
    (RuntimeError, UnknownRuntime),
    (RuntimeError, MissingDependenciesError),
    (SandboxError, RunError),
    (RunError, RunTimedOut),
    (RunError, RunOomKilled),
    (RunError, RunCancelled),
    (SandboxError, LibraryError),
    (LibraryError, LibraryInstallFailed),
    (LibraryError, LibraryPoolLocked),
    (LibraryError, InvalidPackageSpec),
    (SandboxError, FileError),
    (FileError, PathOutsideWorkspace),
    (SandboxError, SandboxBusy),
]


@pytest.mark.parametrize(
    "parent,child",
    _PARENT_CHILD_PAIRS,
    ids=[f"{parent.__name__}->{child.__name__}" for parent, child in _PARENT_CHILD_PAIRS],
)
def testSpecificParentRelationship(parent: type, child: type) -> None:
    """Verify that each child is an instance of its declared parent.

    Args:
        parent: Expected parent class.
        child: Child class to instantiate and check.

    Returns:
        None
    """
    if child is MissingDependenciesError:
        exc = child(["pkg"])
    elif child is InvalidPackageSpec:
        exc = child("spec", "reason")
    else:
        exc = child("msg")
    assert isinstance(exc, parent)


# ============================================================================
# MissingDependenciesError structured fields
# ============================================================================


def testMissingDependenciesErrorStoresList() -> None:
    """Verify that MissingDependenciesError stores the missing list and includes names in str().

    Returns:
        None
    """
    missing = ["numpy", "pandas"]
    exc = MissingDependenciesError(missing)
    assert exc.missing == missing
    assert "numpy" in str(exc)
    assert "pandas" in str(exc)


def testMissingDependenciesErrorEmptyList() -> None:
    """Verify that MissingDependenciesError works with an empty list.

    Returns:
        None
    """
    exc = MissingDependenciesError([])
    assert exc.missing == []
    assert isinstance(exc, RuntimeError)
    assert isinstance(exc, SandboxError)


# ============================================================================
# InvalidPackageSpec structured fields
# ============================================================================


def testInvalidPackageSpecStoresFields() -> None:
    """Verify that InvalidPackageSpec stores spec and reason, and includes them in str().

    Returns:
        None
    """
    spec = "numpy; rm -rf /"
    reason = "shell metachar"
    exc = InvalidPackageSpec(spec, reason)
    assert exc.spec == spec
    assert exc.reason == reason
    assert spec in str(exc)
    assert reason in str(exc)


# ============================================================================
# raise / except chains for every class
# ============================================================================


@pytest.mark.parametrize("cls", _ALL_ERROR_CLASSES, ids=lambda c: c.__name__)
def testRaiseAndCatchOwnType(cls: type) -> None:
    """Verify that each error can be raised and caught by its own type.

    Args:
        cls: Parameterised error class under test.

    Returns:
        None
    """
    if cls is MissingDependenciesError:
        expected = cls(["pkg"])
    elif cls is InvalidPackageSpec:
        expected = cls("spec", "reason")
    else:
        expected = cls("msg")
    with pytest.raises(cls):
        raise expected


# ============================================================================
# SessionDropped caught as multiple parent types
# ============================================================================


def testSessionDroppedCaughtAsSessionError() -> None:
    """Verify that SessionDropped can be caught as SessionError.

    Returns:
        None
    """
    with pytest.raises(SessionError):
        raise SessionDropped("force-dropped")


def testSessionDroppedCaughtAsSandboxError() -> None:
    """Verify that SessionDropped can be caught as SandboxError.

    Returns:
        None
    """
    with pytest.raises(SandboxError):
        raise SessionDropped("force-dropped")


def testSessionDroppedCaughtAsException() -> None:
    """Verify that SessionDropped can be caught as Exception.

    Returns:
        None
    """
    with pytest.raises(Exception):
        raise SessionDropped("force-dropped")


# ============================================================================
# SandboxBusy is NOT under RunError or SessionError
# ============================================================================


def testSandboxBusyNotInstanceOfRunError() -> None:
    """Verify that SandboxBusy is not a subclass of RunError.

    Returns:
        None
    """
    exc = SandboxBusy("concurrency cap reached")
    assert not isinstance(exc, RunError)


def testSandboxBusyNotInstanceOfSessionError() -> None:
    """Verify that SandboxBusy is not a subclass of SessionError.

    Returns:
        None
    """
    exc = SandboxBusy("concurrency cap reached")
    assert not isinstance(exc, SessionError)


def testSandboxBusyIsDirectChildOfSandboxError() -> None:
    """Verify that SandboxBusy is a direct child of SandboxError (not a grandchild).

    Returns:
        None
    """
    assert SandboxBusy.__bases__ == (SandboxError,)
