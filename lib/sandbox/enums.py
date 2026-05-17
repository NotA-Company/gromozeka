"""Enumeration classes for sandboxed code execution.

This module defines string-based enumerations used throughout the sandbox library
for identifying runtime environments and execution backends. All enums inherit
from StrEnum to ensure string representation and comparison capabilities.

Enums:
    RuntimeName: Identifies the programming language runtime for sandboxed execution.
    BackendName: Identifies the execution backend that runs sandboxed code.
"""

from enum import StrEnum


class RuntimeName(StrEnum):
    """Runtime name enumeration for sandboxed code execution environments.

    Identifies the programming language runtime in which sandboxed code
    will be executed.

    Attributes:
        PYTHON: Python runtime environment.
    """

    PYTHON = "python"


class BackendName(StrEnum):
    """Backend name enumeration for sandboxed code execution backends.

    Identifies the execution backend responsible for running sandboxed code.

    Attributes:
        DOCKER: Docker container-based execution backend.
    """

    DOCKER = "docker"
