"""Tests for sandbox enums (RuntimeName, BackendName).

Covers:
- StrEnum construction from string values.
- Member value equality.
- String compatibility (str() returns the value).
- Iteration over enum members.
- Package-level re-export via ``from lib.sandbox import``.
- Public-surface re-export of the package-update result types
  (``PackageUpdate``, ``LibraryUpdateResult``).
"""

from enum import StrEnum

import lib.sandbox
from lib.sandbox import BackendName, LibraryUpdateResult, PackageUpdate, RuntimeName
from lib.sandbox import types as sandboxTypes

# ============================================================================
# RuntimeName
# ============================================================================


def testRuntimeNameConstructionFromValue() -> None:
    """Verify that RuntimeName('python') returns the PYTHON member.

    Returns:
        None
    """
    assert RuntimeName("python") is RuntimeName.PYTHON


def testRuntimeNameValue() -> None:
    """Verify that RuntimeName.PYTHON.value equals 'python'.

    Returns:
        None
    """
    assert RuntimeName.PYTHON.value == "python"


def testRuntimeNameStringCompatibility() -> None:
    """Verify that str(RuntimeName.PYTHON) returns 'python'.

    Returns:
        None
    """
    assert str(RuntimeName.PYTHON) == "python"


# ============================================================================
# BackendName
# ============================================================================


def testBackendNameConstructionFromValue() -> None:
    """Verify that BackendName('docker') returns the DOCKER member.

    Returns:
        None
    """
    assert BackendName("docker") is BackendName.DOCKER


def testBackendNameValue() -> None:
    """Verify that BackendName.DOCKER.value equals 'docker'.

    Returns:
        None
    """
    assert BackendName.DOCKER.value == "docker"


# ============================================================================
# General StrEnum behaviour
# ============================================================================


def testIterationOverEnumMembers() -> None:
    """Verify that iterating over a sandbox StrEnum yields all members.

    Returns:
        None
    """
    runtimeMembers = list(RuntimeName)
    assert len(runtimeMembers) == 1
    assert RuntimeName.PYTHON in runtimeMembers

    backendMembers = list(BackendName)
    assert len(backendMembers) == 1
    assert BackendName.DOCKER in backendMembers


def testStrEnumIsStrSubclass() -> None:
    """Verify that sandbox enums are proper StrEnum subclasses (string-compatible).

    Returns:
        None
    """
    assert isinstance(RuntimeName.PYTHON, str)
    assert isinstance(BackendName.DOCKER, str)
    assert issubclass(RuntimeName, StrEnum)
    assert issubclass(BackendName, StrEnum)


def testPackageReExport() -> None:
    """Verify that RuntimeName and BackendName are importable from lib.sandbox.

    Returns:
        None
    """
    # The imports at the top of this file already prove re-export works;
    # this test asserts they are the correct types, not accidental rebinds.
    from lib.sandbox import BackendName as ImportedBackendName
    from lib.sandbox import RuntimeName as ImportedRuntimeName

    assert ImportedRuntimeName is RuntimeName
    assert ImportedBackendName is BackendName


def testPackageResultTypesReExport() -> None:
    """Verify PackageUpdate and LibraryUpdateResult are public from lib.sandbox.

    Both dataclasses are part of the public updateRuntimeLibraries() result
    surface and must be re-exported from the package root (importable, bound
    to the canonical types, and listed in ``__all__``).

    Returns:
        None
    """
    # The module-level imports already prove importability; assert the
    # re-exports are the canonical types, not accidental rebinds.
    assert PackageUpdate is sandboxTypes.PackageUpdate
    assert LibraryUpdateResult is sandboxTypes.LibraryUpdateResult
    assert "PackageUpdate" in lib.sandbox.__all__
    assert "LibraryUpdateResult" in lib.sandbox.__all__
